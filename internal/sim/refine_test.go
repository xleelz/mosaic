package sim_test

import (
	"os"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// loadRefined parses the §14 parent and child fixtures and attaches the
// child as the engine's loaded refinement.
func loadRefined(t *testing.T) *model.Document {
	t.Helper()
	docs := map[string]*model.Document{}
	for _, name := range []string{"parent", "child"} {
		data, err := os.ReadFile("../model/testdata/refine/" + name + ".yaml")
		if err != nil {
			t.Fatal(err)
		}
		d, err := model.ParseDocument(data)
		if err != nil {
			t.Fatal(err)
		}
		docs[name] = d
	}
	docs["parent"].Refinements = map[string]*model.Document{"engine": docs["child"]}
	return docs["parent"]
}

func passed(t *testing.T, res *sim.Result) {
	t.Helper()
	if res.Summary.Status != "ok" || !res.Summary.Passed {
		t.Fatalf("status %s, passed %v, assertions %+v, abort %q", res.Summary.Status, res.Summary.Passed, res.Summary.Assertions, res.Summary.Abort)
	}
}

// TestRefinementSameScenarioBothResolutions runs one scenario black box and
// refined: both pass, the black box takes the parent's 50 ms and the refined
// run the child's own timing, through the namespaced child components.
func TestRefinementSameScenarioBothResolutions(t *testing.T) {
	doc := loadRefined(t)
	bb := run(t, doc, sim.Request{Scenario: "ask-ok"})
	passed(t, bb)
	eq(t, "black box duration", bb.Summary.DurationMS, int64(51))
	for _, ev := range bb.Trace {
		if strings.HasPrefix(ev.Component, "engine/") {
			t.Fatalf("black box run entered the child: %+v", ev)
		}
	}

	ref := run(t, doc, sim.Request{Scenario: "ask-ok", Resolution: map[string]string{"engine": model.ResolutionRefined}})
	passed(t, ref)
	eq(t, "refined duration", ref.Summary.DurationMS, int64(27)) // gateway 1 (the default) + shell 0 + scheduler 5 + worker 20 + metrics 1
	eq(t, "effective resolution", ref.Request.Resolution["engine"], "refined")
	var calls []string
	for _, ev := range ref.Trace {
		if ev.Type == "call.start" {
			calls = append(calls, ev.Interface)
		}
	}
	want := []string{"gateway.handle", "engine.run", "engine/scheduler.submit", "engine/worker.execute", "metrics.record"}
	if strings.Join(calls, " ") != strings.Join(want, " ") {
		t.Errorf("refined calls = %v, want %v", calls, want)
	}
	eq(t, "child calls", ref.Summary.Calls["engine/worker.execute"], 1)

	// The scenario's own resolution field.
	passed(t, run(t, doc, sim.Request{Scenario: "ask-refined"}))
	// The request overrides it back to black box.
	bb2 := run(t, doc, sim.Request{Scenario: "ask-ok", Resolution: map[string]string{"engine": model.ResolutionBlackBox}})
	passed(t, bb2)
	eq(t, "black box again", bb2.Summary.DurationMS, int64(51))
}

// TestRefinementErrorsCrossTheBoundary: an error raised deep in the child
// reaches the parent's caller with its code and status, as the black box's.
func TestRefinementErrorsCrossTheBoundary(t *testing.T) {
	doc := loadRefined(t)
	fault := func(target string) []model.Fault {
		return []model.Fault{{Target: target, Type: "error", Code: "overloaded", Status: 503}}
	}
	bb := run(t, doc, sim.Request{Flow: "ask", Faults: fault("engine.run")})
	ref := run(t, doc, sim.Request{Flow: "ask", Faults: fault("engine/worker.execute"), Resolution: map[string]string{"engine": "refined"}})
	for _, res := range []*sim.Result{bb, ref} {
		if e := res.Summary.Result.Error; res.Summary.Status != "error" || e == nil || e.Code != "overloaded" || e.Status != 503 {
			t.Errorf("result = %s %+v", res.Summary.Status, res.Summary.Result)
		}
	}
}

func TestRefinementRequestErrors(t *testing.T) {
	doc := loadRefined(t)
	if _, err := sim.Run(doc, sim.Request{Flow: "ask", Resolution: map[string]string{"engine": "zoomed"}}); err == nil {
		t.Error("a bad resolution was accepted")
	}
	doc.Refinements = nil
	if _, err := sim.Run(doc, sim.Request{Scenario: "ask-refined"}); err == nil || !strings.Contains(err.Error(), "no refinement") {
		t.Errorf("refined without a loaded child: %v", err)
	}
}

// TestImportsMergedForRun: a run merges the document's loaded imports
// under their as: prefix.
func TestImportsMergedForRun(t *testing.T) {
	kv, err := model.ParseDocument([]byte(`
id: kv
components: [{id: store}]
interfaces:
  - {component: store, name: get, latency_ms: 2, behavior: [{return: {v: 7}}]}
`))
	if err != nil {
		t.Fatal(err)
	}
	d, err := model.ParseDocument([]byte(`
id: app
imports: [{ontology: kv, as: cache}]
components: [{id: client}, {id: app}]
interfaces:
  - component: app
    name: read
    behavior:
      - {call: cache/store.get, as: g}
      - return: "=vars.g.value.v"
flows: [{id: read, entry: {caller: client, interface: app.read}}]
`))
	if err != nil {
		t.Fatal(err)
	}
	d.ImportDocs = map[string]*model.Document{"kv": kv}
	res := run(t, d, sim.Request{Flow: "read"})
	if res.Summary.Status != "ok" || res.Summary.DurationMS != 3 {
		t.Errorf("summary = %+v", res.Summary)
	}
	eq(t, "value", res.Summary.Result.Value, int64(7))
}

// TestRefinedBoundaryTimingIsTheChilds: the refined engine.run call lasts
// exactly the child's own time (scheduler 5 + worker 20 + metrics 1), with
// no millisecond added by the shell.
func TestRefinedBoundaryTimingIsTheChilds(t *testing.T) {
	ref := run(t, loadRefined(t), sim.Request{Flow: "ask", Resolution: map[string]string{"engine": "refined"}})
	ends := eventsFor(ref, "call.end", "engine.run")
	if len(ends) != 1 {
		t.Fatalf("engine.run call.end events: %d", len(ends))
	}
	eq(t, "engine.run duration", ends[0].DurationMS, int64(26))
}

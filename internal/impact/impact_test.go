package impact

import (
	"reflect"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

// base has one flow with a scenario (main) whose entry calls svc.read, one
// of two declared dynamic targets (the scenario picks worker.run, never
// worker.batch) and emits q.handle; and one flow without scenarios (nosc).
const base = `
schema_version: 1
components:
  - {id: client}
  - {id: platform}
  - {id: gw, parent: platform}
  - {id: svc, parent: platform}
  - {id: worker}
  - {id: q}
interfaces:
  - component: gw
    name: in
    behavior:
      - {call: svc.read}
      - {call: "= 'worker.' + input.op", targets: [worker.run, worker.batch]}
      - {emit: q.handle}
  - component: gw
    name: side
    behavior:
      - {call: worker.batch}
  - {component: svc, name: read, response: Item}
  - {component: worker, name: run}
  - {component: worker, name: batch}
  - {component: q, name: handle}
schemas:
  - {id: Item, schema: {type: object}}
flows:
  - {id: main, entry: {caller: client, interface: gw.in}}
  - {id: nosc, entry: {caller: client, interface: gw.side}}
scenarios:
  - {id: main-ok, flow: main, input: {op: run}}
`

func doc(t *testing.T, src string) *model.Document {
	t.Helper()
	d, err := model.ParseDocument([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func edit(t *testing.T, old, new string) *model.Document {
	t.Helper()
	if !strings.Contains(base, old) {
		t.Fatalf("base lacks %q", old)
	}
	return doc(t, strings.Replace(base, old, new, 1))
}

func affected(imp *model.Impact) map[string]model.FlowImpact {
	out := map[string]model.FlowImpact{}
	for _, f := range imp.FlowsAffected {
		out[f.Flow] = f
	}
	return out
}

func TestTracesBasis(t *testing.T) {
	// worker.batch is a declared target main never takes: static reach says
	// main is affected, its trace says not. nosc (no scenarios) is.
	after := edit(t, "{component: worker, name: batch}", "{component: worker, name: batch, description: changed}")
	if st := affected(model.ComputeImpact(doc(t, base), after)); st["main"].Flow == "" {
		t.Fatalf("static reach should include worker.batch: %+v", st)
	}
	got := affected(Compute(doc(t, base), after))
	if _, ok := got["main"]; ok {
		t.Errorf("main affected by an untaken target: %+v", got)
	}
	want := model.FlowImpact{Flow: "nosc", Reasons: []string{"interface:worker.batch"}, Basis: BasisStatic}
	if !reflect.DeepEqual(got["nosc"], want) {
		t.Errorf("nosc: got %+v, want %+v", got["nosc"], want)
	}

	// worker.run is taken: main is affected, on the traces basis.
	after = edit(t, "{component: worker, name: run}", "{component: worker, name: run, description: changed}")
	got = affected(Compute(doc(t, base), after))
	want = model.FlowImpact{Flow: "main", Reasons: []string{"interface:worker.run"}, Basis: BasisTraces}
	if !reflect.DeepEqual(got["main"], want) || len(got) != 1 {
		t.Errorf("got %+v, want only %+v", got, want)
	}

	// Components, ancestors and referenced schemas of exercised interfaces count.
	after = edit(t, "{id: Item, schema: {type: object}}", "{id: Item, schema: {type: string}}")
	if f := affected(Compute(doc(t, base), after))["main"]; !reflect.DeepEqual(f.Reasons, []string{"schema:Item"}) {
		t.Errorf("schema: %+v", f)
	}
	after = edit(t, "{id: platform}", "{id: platform, description: changed}")
	if f := affected(Compute(doc(t, base), after))["main"]; !reflect.DeepEqual(f.Reasons, []string{"component:platform"}) {
		t.Errorf("ancestor: %+v", f)
	}
}

func TestStaticFallback(t *testing.T) {
	// Without scenarios main falls back to its static reach.
	noScen := strings.Replace(base, "  - {id: main-ok, flow: main, input: {op: run}}\n", "", 1)
	before := doc(t, noScen)
	after := doc(t, strings.Replace(noScen, "{component: worker, name: batch}", "{component: worker, name: batch, description: changed}", 1))
	got := affected(Compute(before, after))
	if got["main"].Basis != BasisStatic || !reflect.DeepEqual(got["main"].Reasons, []string{"interface:worker.batch"}) {
		t.Errorf("main: %+v", got["main"])
	}
}

func TestEmittedAsyncCounted(t *testing.T) {
	after := edit(t, "{component: q, name: handle}", "{component: q, name: handle, description: changed}")
	got := affected(Compute(doc(t, base), after))
	want := model.FlowImpact{Flow: "main", Reasons: []string{"interface:q.handle"}, Basis: BasisTraces}
	if !reflect.DeepEqual(got["main"], want) {
		t.Errorf("got %+v, want %+v", got["main"], want)
	}
}

func TestBeforeOnlyReach(t *testing.T) {
	// after drops worker.run and the call that took it: only the before
	// trace reaches the removed interface.
	src := strings.Replace(base, `      - {call: "= 'worker.' + input.op", targets: [worker.run, worker.batch]}`+"\n", "", 1)
	src = strings.Replace(src, "  - {component: worker, name: run}\n", "", 1)
	after := doc(t, src)
	imp := Compute(doc(t, base), after)
	if !reflect.DeepEqual(imp.Interfaces.Removed, []string{"worker.run"}) {
		t.Fatalf("removed: %v", imp.Interfaces.Removed)
	}
	got := affected(imp)["main"]
	want := model.FlowImpact{Flow: "main", Reasons: []string{"interface:gw.in", "interface:worker.run"}, Basis: BasisTraces}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %+v, want %+v", got, want)
	}
}

func TestCacheAndNoChange(t *testing.T) {
	c := NewCache(1)
	b := doc(t, base)
	if imp := c.Compute(b, "k1", doc(t, base), "k2"); len(imp.FlowsAffected) != 0 {
		t.Errorf("no change: %+v", imp.FlowsAffected)
	}
	after := edit(t, "{component: worker, name: run}", "{component: worker, name: run, description: changed}")
	first := c.Compute(b, "k1", after, "k3")
	second := c.Compute(b, "k1", after, "k3")
	if !reflect.DeepEqual(first, second) || len(c.docs) != 1 {
		t.Errorf("cache: %+v %+v (%d docs)", first.FlowsAffected, second.FlowsAffected, len(c.docs))
	}
}

func TestMultiStepScenarioGrouped(t *testing.T) {
	// A multi-step scenario without a flow is grouped under its first
	// step's flow (nosc), and every interface its steps call counts toward
	// nosc's traced reach, including the second step's q.handle.
	src := base + "  - {id: steps, steps: [{flow: nosc}, {interface: q.handle, caller: client}]}\n"
	before := doc(t, src)
	after := doc(t, strings.Replace(src, "{component: q, name: handle}", "{component: q, name: handle, description: changed}", 1))
	got := affected(Compute(before, after))
	want := model.FlowImpact{Flow: "nosc", Reasons: []string{"interface:q.handle"}, Basis: BasisTraces}
	if !reflect.DeepEqual(got["nosc"], want) {
		t.Errorf("got %+v, want %+v", got["nosc"], want)
	}
	// worker.run is in no step's trace, so nosc is not affected.
	after = doc(t, strings.Replace(src, "{component: worker, name: run}", "{component: worker, name: run, description: changed}", 1))
	if f, ok := affected(Compute(before, after))["nosc"]; ok {
		t.Errorf("nosc affected: %+v", f)
	}
}

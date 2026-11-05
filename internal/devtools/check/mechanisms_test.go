package main

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// A small neutral system: an http api over a real indexer, a pooler that
// returns a constant, an audit log nobody reads, an observer nothing calls,
// and a helper only an internal assertion checks.
const mechModel = `
schema_version: 1
id: mech
components:
  - {id: user, kind: external}
  - {id: api}
  - {id: indexer}
  - {id: pooler}
  - {id: embedder}
  - {id: audit}
  - {id: observer}
  - {id: helper}
  - {id: db}
  - {id: shelved}
interfaces:
  - {component: db, name: put, store: {table: rows, op: put, key: "= input.id", value: "= input"}}
  - {component: db, name: get, store: {table: rows, op: get, key: "= input.id"}}
  - component: api
    name: index
    kind: http
    behavior:
      - {call: audit.record, input: {id: "= input.id"}}
      - {call: helper.note, input: {id: "= input.id"}}
      - {call: indexer.write, input: {id: "= input.id"}, as: w}
      - {return: {id: "= vars.w.value.id"}}
  - component: indexer
    name: write
    behavior:
      - {call: db.put, input: {id: "= input.id"}}
      - {return: {id: "= input.id"}}
  - component: api
    name: pool
    kind: http
    behavior:
      - {call: pooler.encode, as: enc}
      - {return: {vectors: "= vars.enc.value.vectors"}}
  - component: api
    name: count
    kind: http
    behavior:
      - {call: pooler.constant, as: c}
      - {return: {n: "= vars.c.value.n"}}
  - component: api
    name: embed
    kind: http
    behavior:
      - {call: embedder.run, input: {bad: "= input.bad"}, as: e, on_error: continue}
      - if: "!vars.e.ok"
        then: [{fail: {code: bad_input, status: 400}}]
      - {return: {done: true}}
  - component: embedder
    name: run
    behavior:
      - if: "input.bad"
        then: [{fail: {code: bad_input, status: 400}}]
      - {return: {vectors: "= []"}}
  - component: pooler
    name: encode
    behavior:
      - {set: {vars.v: "= []"}}
      - {return: {vectors: "= vars.v"}}
  - component: pooler
    name: constant
    behavior:
      - {return: {n: 7}}
  - component: audit
    name: record
    behavior:
      - {set: {state.last: "= input.id"}}
      - {return: {done: true}}
  - component: helper
    name: note
    behavior:
      - {set: {vars.seen: "= input.id"}}
      - {return: {note: "= vars.seen"}}
  - component: observer
    name: observe
    behavior:
      - {set: {state.n: 1}}
      - {return: {n: "= state.n"}}
  - component: observer
    name: tally
    behavior:
      - {set: {state.n: 1}}
      - {return: {n: "= state.n"}}
  - component: shelved
    name: run
    behavior:
      - {set: {vars.x: "= input.id"}}
      - {return: {x: "= vars.x"}}
flows:
  - {id: index, entry: {caller: user, interface: api.index, input: {id: a}}}
  - {id: pool, entry: {caller: user, interface: api.pool}}
  - {id: count, entry: {caller: user, interface: api.count}}
  - {id: embed, entry: {caller: user, interface: api.embed}}
  - {id: raced, entry: {caller: user, interface: shelved.run, input: {id: a}}}
scenarios:
  - id: embed-refuses
    steps:
      - {flow: embed, input: {bad: true}, as: e}
    expect: ["!steps.e.result.ok && steps.e.result.error.status == 400"]
  - id: index-writes
    flow: index
    expect:
      - "result.ok"
      - "state.db.rows['a'].id == 'a'"
      - "calls['helper.note'] == 1"
  - id: pool-answers
    flow: pool
    expect: ["result.ok"]
  - id: count-answers
    flow: count
    expect: ["result.value.n == 7"]
  - id: internal-check
    flow: index
    expect: ["result.ok", "state.helper == null || true", "trace.filter(e, e.type == 'call.end' && e.interface == 'helper.note' && e.output.note == 'a').size() == 1"]
  - id: tally-unit
    steps:
      - {interface: observer.tally, caller: user, as: t}
    expect: ["steps.t.result.value.n == 1"]
  - id: shelved-race
    flow: raced
    tags: [race]
    expect: ["result.value.x == 'a'"]
`

func mechFixture(t *testing.T) (*model.Document, *mechanismList) {
	t.Helper()
	doc, err := model.ParseDocument([]byte(mechModel))
	if err != nil {
		t.Fatal(err)
	}
	if is := model.Validate(doc); model.HasErrors(is) {
		t.Fatalf("invalid fixture: %+v", is)
	}
	m := func(id, kind, fidelity string, ifaces ...string) mechanism {
		return mechanism{ID: id, Kind: kind, Fidelity: fidelity, Interfaces: ifaces, Area: "core"}
	}
	return doc, &mechanismList{
		Mechanisms: []mechanism{
			m("core.index", "pipeline", "modeled", "api.index", "indexer.write"),
			m("core.pool", "pipeline", "modeled", "pooler.encode"),
			m("core.constant", "metric", "modeled", "pooler.constant"),
			m("core.observer", "metric", "shell", "observer.observe"),
			m("core.tally", "metric", "modeled", "observer.tally"),
			m("core.helper", "cache", "shell", "helper.note"),
			m("core.audit", "loop", "modeled", "audit.record"),
			m("core.gone", "sweep", "absent"),
			m("core.typo", "sweep", "partial", "nothing.here"),
			m("core.partly", "pipeline", "modeled", "indexer.write", "nothing.here"),
			m("core.raced", "retry", "modeled", "shelved.run"),
			m("core.embed", "pipeline", "modeled", "embedder.run"),
			m("core.embed-gate", "gate", "modeled", "embedder.run"),
			m("core.parts", "pipeline", "modeled", "indexer.write", "audit.record", "observer.tally"),
			m("core.excused", "gate", "absent"),
			m("core.badskip", "gate", "absent"),
		},
		Skips: map[string][]featureSkip{"core": {
			{ID: "core.excused", Reason: "the demo binary only, never in a deployment"},
			{ID: "core.badskip", Reason: "out of scope for now"},
		}},
	}
}

func measureFixture(t *testing.T, variant string, gate2 bool) *mechReport {
	t.Helper()
	doc, l := mechFixture(t)
	rr := runAll(io.Discard, doc, nil, runOpts{Track: l.interfaces()})
	if rr.Failed != 0 {
		t.Fatalf("fixture scenarios failed: %v", rr.FailedIDs)
	}
	r := measureMechanisms(doc, l, rr.Base, nil)
	if gate2 {
		runMechanismE2E(r, doc, rr.Base, e2eOpts{Scenarios: 10, Workers: 4, Variant: variant})
	}
	r.finish()
	return r
}

func byID(r *mechReport) map[string]*mechResult {
	out := map[string]*mechResult{}
	for _, res := range r.Results {
		out[res.ID] = res
	}
	return out
}

func TestMechanismStatuses(t *testing.T) {
	got := byID(measureFixture(t, "zero", true))
	for _, c := range []struct{ id, status, detail string }{
		{"core.index", mechOK, ""},                  // removal loses the store row
		{"core.pool", mechShell, "removing it"},     // the constant is what zero answers
		{"core.constant", mechShell, "constant"},    // a check of a constant isn't a check
		{"core.observer", mechUncovered, "reaches"}, // nothing calls it, no scenario enters it
		{"core.tally", mechShell, "no caller"},      // only its own unit scenario enters it
		{"core.helper", mechShell, "removing it"},   // only an internal assertion notices
		{"core.audit", mechShell, "removing it"},    // nothing reads what it does
		{"core.gone", mechMissing, "no interface"},
		{"core.typo", mechMissing, "exists"},
		{"core.partly", mechOK, ""},
		{"core.raced", mechUncovered, "racing"},                        // a race-tagged scenario stays out
		{"core.embed", mechShell, "only fails a check of its refusal"}, // losing a validation isn't losing the pipeline
		{"core.embed-gate", mechOK, ""},                                // a gate's work is the refusal
		{"core.parts", mechOK, ""},
		{"core.excused", mechSkipped, "demo binary"},
		{"core.badskip", mechMissing, "invalid skip: rejected reason"},
	} {
		res := got[c.id]
		if res == nil || res.Status != c.status || !strings.Contains(res.Detail, c.detail) {
			t.Errorf("%s: got %+v, want %s with %q", c.id, res, c.status, c.detail)
		}
	}
	var weak []string
	for _, w := range got["core.parts"].E2E.Weak {
		weak = append(weak, w.ID+": "+w.Why)
	}
	if len(weak) != 2 || !strings.Contains(weak[0], "audit.record: removing it alone") || !strings.Contains(weak[1], "observer.tally: no caller") {
		t.Errorf("weak interfaces of an ok mechanism: %q", weak)
	}
	if got["core.partly"].Unknown[0] != "nothing.here" {
		t.Errorf("unknown interface not reported: %+v", got["core.partly"])
	}
	// The internal assertion failed under mutation, and is named as not counting.
	helper := got["core.helper"].E2E
	var internal, survived []string
	for _, run := range helper.Runs {
		internal = append(internal, run.Internal...)
		survived = append(survived, run.Survived...)
	}
	if len(internal) == 0 || !strings.Contains(strings.Join(survived, "\n"), "result.ok") {
		t.Errorf("helper evidence: internal %v survived %v", internal, survived)
	}
}

func TestMechanismDisagreements(t *testing.T) {
	got := byID(measureFixture(t, "zero", true))
	for id, want := range map[string]string{
		"core.pool":     "enumerator says modeled, measured shell",
		"core.observer": "", // a shell with no caller reads as uncovered
		"core.helper":   "", // the enumerator said shell, and it is
		"core.gone":     "",
		"core.typo":     "enumerator says partial, measured missing",
		"core.index":    "",
		"core.badskip":  "",
		"core.excused":  "",
	} {
		if got[id].Disagree != want {
			t.Errorf("%s: disagree %q, want %q", id, got[id].Disagree, want)
		}
	}
	if d := fidelityAgrees("shell", mechOK); d {
		t.Error("an enumerator's shell measured ok must disagree (the reverse direction)")
	}
}

func TestMechanismGate1WithoutMutation(t *testing.T) {
	r := measureFixture(t, "zero", false)
	got := byID(r)
	if got["core.index"].Status != mechReached || got["core.observer"].Status != mechUncovered {
		t.Fatalf("statuses: %+v %+v", got["core.index"], got["core.observer"])
	}
	var b bytes.Buffer
	r.print(&b, false)
	if !strings.Contains(b.String(), "reached (Gate 2 not run)") {
		t.Fatalf("no Gate 2 note: %s", b.String())
	}
}

func TestMechanismReportAndGates(t *testing.T) {
	r := measureFixture(t, "zero", true)
	var b bytes.Buffer
	r.print(&b, false)
	out := b.String()
	for _, want := range []string{
		"mechanisms of core: 4 ok, 6 shell, 2 uncovered, 3 missing, 1 skipped",
		"mechanisms of kind metric:",
		"mechanisms: 4 of 15 unskipped ok (26.7%)",
		"✗ mechanism core.pool (core, pipeline) shell [enumerator: modeled]",
		"interfaces: pooler.encode",
		"ran pool-answers with pooler.encode disabled: 1 boundary expectations survived",
		"survived: result.ok",
		"variant zero",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("report lacks %q:\n%s", want, out)
		}
	}
	if strings.Contains(out, "mechanism core.index ") {
		t.Errorf("an ok mechanism is listed:\n%s", out)
	}

	for _, c := range []struct {
		min   float64
		max   int
		fail  bool
		wants []string
	}{
		{-1, -1, false, []string{"recorded, not gated"}},
		{0.1, -1, false, []string{"✓ mechanisms gate", "can go up to 0.266", "only goes up"}},
		{0.5, -1, true, []string{"✗ mechanisms gate: share 0.267, --min-mechanisms 0.500"}},
		{-1, 6, false, []string{"✓ shell-mechanisms gate: 6"}},
		{-1, 9, false, []string{"can go down to 6"}},
		{-1, 5, true, []string{"✗ shell-mechanisms gate: 6"}},
	} {
		var g bytes.Buffer
		if got := r.gates(&g, c.min, c.max); got != c.fail {
			t.Errorf("gates(%v, %d) = %v: %s", c.min, c.max, got, g.String())
		}
		for _, w := range c.wants {
			if !strings.Contains(g.String(), w) {
				t.Errorf("gates(%v, %d) lacks %q: %s", c.min, c.max, w, g.String())
			}
		}
	}
}

func TestMechanismVariants(t *testing.T) {
	// Failing makes every required call notice, so it can't find a shell whose
	// caller only propagates the error: that is why zero is the default.
	fail := byID(measureFixture(t, "fail", true))
	if fail["core.pool"].Status != mechOK || fail["core.helper"].Status != mechOK {
		t.Errorf("fail variant: pool %s helper %s", fail["core.pool"].Status, fail["core.helper"].Status)
	}
	// {} makes the caller's read of the missing field abort on the entry's chain.
	empty := byID(measureFixture(t, "empty", true))
	if empty["core.pool"].Status != mechOK {
		t.Errorf("empty variant: pool %s", empty["core.pool"].Status)
	}
}

func TestAbortReachesEntry(t *testing.T) {
	start := func(span, parent int, iface string, async bool) sim.Event {
		return sim.Event{Type: "call.start", Span: span, Parent: parent, Interface: iface, Async: async}
	}
	end := func(span int) sim.Event { return sim.Event{Type: "call.end", Span: span} }
	caps := &sim.Caps{Hit: "max_events"}
	for _, c := range []struct {
		name  string
		abort string
		caps  *sim.Caps
		trace []sim.Event
		want  bool
	}{
		{"a read on the entry's chain", "b.read.behavior[1].return: no such key", nil,
			[]sim.Event{start(1, 0, "a.entry", false), start(2, 1, "b.read", false)}, true},
		{"a read in background work", "b.read.behavior[1].return: no such key", nil,
			[]sim.Event{start(1, 0, "a.entry", false), end(1), start(2, 1, "b.read", true)}, false},
		{"the cap with the entry open", "event budget of 20000 exceeded", caps,
			[]sim.Event{start(1, 0, "a.entry", false), start(2, 1, "b.poll", false), end(2)}, true},
		{"the cap after the entry answered", "event budget of 20000 exceeded", caps,
			[]sim.Event{start(1, 0, "a.entry", false), end(1), start(2, 1, "b.poll", true)}, false},
		{"the depth limit", "call depth limit of 64 exceeded at b.read", nil,
			[]sim.Event{start(1, 0, "a.entry", false)}, false},
	} {
		res := &sim.Result{Trace: c.trace, Summary: sim.Summary{Abort: c.abort, Caps: c.caps}}
		if got := abortReachesEntry(res); got != c.want {
			t.Errorf("%s: %v", c.name, got)
		}
	}
}

func TestZeroShape(t *testing.T) {
	got := mergeZero(zeroShape(map[string]any{"a": "x", "b": []any{1}, "c": map[string]any{"d": true}}), zeroShape(map[string]any{"e": int64(4)}))
	b, _ := json.Marshal(got)
	if string(b) != `{"a":"","b":[],"c":{"d":false},"e":0}` {
		t.Fatalf("%s", b)
	}
}

func TestMechanismCap(t *testing.T) {
	doc, l := mechFixture(t)
	l.Mechanisms = []mechanism{{ID: "core.audit", Kind: "loop", Area: "core", Interfaces: []string{"audit.record"}}}
	rr := runAll(io.Discard, doc, nil, runOpts{Track: l.interfaces()})
	r := measureMechanisms(doc, l, rr.Base, nil)
	runMechanismE2E(r, doc, rr.Base, e2eOpts{Scenarios: 1, Workers: 1, Variant: "zero"})
	if got := r.Results[0].E2E; got.Reaching != 2 || len(got.Runs) != 1 || got.Runs[0].Scenario != "index-writes" {
		t.Fatalf("the cap should run the scenario with the most boundary checks: %+v", got)
	}
}

func TestDirectEntryOnBoundaryCounts(t *testing.T) {
	doc, err := model.ParseDocument([]byte(`
schema_version: 1
components: [{id: user, kind: external}, {id: api}]
interfaces:
  - component: api
    name: ping
    kind: http
    behavior:
      - {set: {vars.a: "= input.x"}}
      - {return: {x: "= vars.a"}}
scenarios:
  - id: ping
    steps:
      - {interface: api.ping, caller: user, input: {x: 1}, as: p}
    expect: ["steps.p.result.value.x == 1"]
`))
	if err != nil {
		t.Fatal(err)
	}
	l := &mechanismList{Mechanisms: []mechanism{{ID: "a.ping", Area: "a", Interfaces: []string{"api.ping"}}}}
	rr := runAll(io.Discard, doc, nil, runOpts{Track: l.interfaces()})
	r := measureMechanisms(doc, l, rr.Base, nil)
	runMechanismE2E(r, doc, rr.Base, e2eOpts{Scenarios: 10, Workers: 1, Variant: "zero"})
	if r.Results[0].Status != mechOK {
		t.Fatalf("a boundary entry entered directly: %+v", r.Results[0])
	}
}

func TestLoadMechanisms(t *testing.T) {
	dir := t.TempDir()
	write := func(name string, v any) {
		b, _ := json.Marshal(v)
		if err := os.MkdirAll(filepath.Dir(filepath.Join(dir, name)), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, name), b, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write("core.json", map[string]any{"area": "core", "mechanisms": []map[string]any{
		{"id": "core.a", "kind": "sweep", "interfaces": []string{"x.y"}, "fidelity": "modeled", "citations": []string{"f.go:1"}},
		{"id": "core.a", "kind": "sweep", "fidelity": "modeled"},
		{"id": "core.b", "kind": "whim", "fidelity": "maybe"},
	}})
	write("skips/core.json", []map[string]any{{"id": "core.b", "reason": "only in the demo binary"}})
	l, err := loadMechanisms(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(l.Mechanisms) != 2 || l.Mechanisms[0].Area != "core" || len(l.Skips["core"]) != 1 {
		t.Fatalf("%+v", l)
	}
	w := strings.Join(l.Warnings, "\n")
	for _, want := range []string{"duplicate id core.a", `unknown kind "whim"`, `unknown fidelity "maybe"`} {
		if !strings.Contains(w, want) {
			t.Errorf("warnings lack %q: %s", want, w)
		}
	}
	if _, err := loadMechanisms(filepath.Join(dir, "nope")); err == nil {
		t.Error("a missing directory must fail")
	}
}

package sim_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// storeBuild adds a datastore with one interface per store operation; the
// interfaces of component a in body drive it (build adds a flow for each).
// The shared fixture has no db component, so "db" is written for the
// stateless component c.
func storeBuild(t *testing.T, body string) *model.Document {
	t.Helper()
	return build(t, strings.ReplaceAll(`
interfaces:
  - component: db
    name: get
    errors: [{code: not_found, status: 410, retryable: true}]
    store: {table: vms, op: get, key: "= input.id", where: "!has(input.org) || row.org == input.org"}
  - {component: db, name: get-or-default, store: {table: vms, op: get, key: "= input.id", default: {id: "= input.id", status: absent}}}
  - component: db
    name: create
    errors: [{code: already_exists, status: 409}]
    store: {table: vms, op: put, key: "= input.id", value: "= input", where: "row == null", conflict: already_exists}
  - {component: db, name: put, store: {table: vms, op: put, key: "= input.id", value: "= input"}}
  - {component: db, name: update, store: {table: vms, op: update, key: "= input.id", value: {status: "= input.status"}}}
  - {component: db, name: delete, store: {table: vms, op: delete, key: "= input.id"}}
  - {component: db, name: running, store: {table: vms, op: query, where: "row.status == 'running'"}}
  - {component: db, name: bump, store: {table: counts, op: incr, key: "= input.id", value: {done: "= input.n", failed: 0}}}
  - {component: db, name: tick, store: {table: seq, op: incr, key: global, value: 1}}
`+body, "db", "c"))
}

func TestStoreReadsBackWrites(t *testing.T) {
	doc := storeBuild(t, `
  - component: a
    name: main
    behavior:
      - {call: db.put, input: {id: vm1, org: o1, status: pending}}
      - {call: db.put, input: {id: vm2, org: o1, status: running}}
      - {call: db.update, input: {id: vm1, status: running}, as: upd}
      - {call: db.get, input: {id: vm1}, as: got}
      - {call: db.running, input: {}, as: run}
      - {call: db.bump, input: {id: j, n: 2}}
      - {call: db.bump, input: {id: j, n: 3}, as: bumped}
      - {call: db.tick, input: {}}
      - {call: db.tick, input: {}, as: ticked}
      - {call: db.delete, input: {id: vm2}, as: del}
      - {call: db.delete, input: {id: vm2}, as: del2}
      - return:
          updated: "= vars.upd.value"
          got: "= vars.got.value"
          running: "= vars.run.value.map(r, r.id)"
          bumped: "= vars.bumped.value"
          ticked: "= vars.ticked.value"
          deleted: "= vars.del.value.id"
          deleted_again: "= vars.del2.value"
`)
	res := run(t, doc, sim.Request{Flow: "main"})
	eq(t, "result", okValue(t, res), map[string]any{
		"updated":       map[string]any{"id": "vm1", "org": "o1", "status": "running"},
		"got":           map[string]any{"id": "vm1", "org": "o1", "status": "running"},
		"running":       []any{"vm1", "vm2"},
		"bumped":        map[string]any{"done": int64(5), "failed": int64(0)},
		"ticked":        int64(2),
		"deleted":       "vm2",
		"deleted_again": nil,
	})
	eq(t, "final state", res.Summary.State["c"], map[string]any{
		"vms":    map[string]any{"vm1": map[string]any{"id": "vm1", "org": "o1", "status": "running"}},
		"counts": map[string]any{"j": map[string]any{"done": int64(5), "failed": int64(0)}},
		"seq":    map[string]any{"global": int64(2)},
	})
	sets := eventsFor(res, "set", "c.update")
	if len(sets) != 1 || sets[0].Path != "state.vms.vm1" || sets[0].Scope != "state" || sets[0].Component != "c" {
		t.Errorf("update set event: %+v", sets)
	}
	if n := len(eventsFor(res, "set", "c.get")); n != 0 {
		t.Errorf("reads record no set events, got %d", n)
	}
	eq(t, "warnings", res.Summary.Warnings, []string{})
}

func TestStoreMissesConflictsAndSeeds(t *testing.T) {
	doc := storeBuild(t, `
  - component: a
    name: main
    behavior:
      - {call: db.get, input: "= input", as: got, on_error: continue}
      - {call: db.get-or-default, input: {id: "= input.id"}, as: dflt}
      - {call: db.create, input: {id: "= input.id", org: o9}, as: created, on_error: continue}
      - {call: db.update, input: {id: nobody, status: x}, as: upd, on_error: continue}
      - return: {got: "= vars.got", dflt: "= vars.dflt.value", created: "= vars.created.error", upd: "= vars.upd.error.code"}
`)
	type out = map[string]any
	// A miss returns the declared not_found error (its status and retryable
	// come from the declaration); default answers instead of failing.
	v := okValue(t, run(t, doc, sim.Request{Flow: "main", Input: json.RawMessage(`{"id": "vm1"}`)})).(out)
	got := v["got"].(out)
	if got["ok"] != false || got["error"].(out)["code"] != "not_found" || got["error"].(out)["status"] != int64(410) || got["error"].(out)["retryable"] != true {
		t.Errorf("miss: %v", got)
	}
	eq(t, "default", v["dflt"], out{"id": "vm1", "status": "absent"})
	eq(t, "create on a miss succeeds", v["created"], nil)
	eq(t, "update miss falls back to a plain not_found", v["upd"], "not_found")

	// Seeded rows drive the branches: the scenario state is the table.
	seed := map[string]map[string]any{"c": {"vms": map[string]any{"vm1": map[string]any{"id": "vm1", "org": "o1"}}}}
	v = okValue(t, run(t, doc, sim.Request{Flow: "main", State: seed, Input: json.RawMessage(`{"id": "vm1"}`)})).(out)
	eq(t, "seeded get", v["got"].(out)["value"], out{"id": "vm1", "org": "o1"})
	eq(t, "seeded default not used", v["dflt"], out{"id": "vm1", "org": "o1"})
	created := v["created"].(out)
	if created["code"] != "already_exists" || created["status"] != int64(409) {
		t.Errorf("conflict: %v", created)
	}
	// where hides rows of another org: a miss, not a hit.
	v = okValue(t, run(t, doc, sim.Request{Flow: "main", State: seed, Input: json.RawMessage(`{"id": "vm1", "org": "o2"}`)})).(out)
	if v["got"].(out)["ok"] != false {
		t.Errorf("where should hide the row: %v", v["got"])
	}
}

func TestStoreFaultsAndAborts(t *testing.T) {
	doc := storeBuild(t, `
  - {component: a, name: get, behavior: [{call: db.get, input: "= input"}]}
  - {component: a, name: bump, behavior: [{call: db.bump, input: "= input"}]}
  - {component: a, name: tick, behavior: [{call: db.tick}]}
  - component: db
    name: both
    store: {table: vms, op: query}
    behavior: [{return: from-behavior}]
  - {component: a, name: both, behavior: [{call: db.both, as: r}, {return: "= vars.r.value"}]}
`)
	// Faults apply before the store runs.
	res := run(t, doc, sim.Request{Flow: "get", Input: json.RawMessage(`{"id": "x"}`), Faults: []model.Fault{{Target: "c", Type: "unavailable"}}})
	if res.Summary.Result.Error == nil || res.Summary.Result.Error.Code != "unavailable" {
		t.Errorf("fault: %+v", res.Summary.Result)
	}
	for name, c := range map[string]struct {
		flow, input string
		state       map[string]map[string]any
		abort       string
	}{
		"table not a map": {"get", `{"id": "x"}`, map[string]map[string]any{"c": {"vms": int64(3)}}, "c.get.store: state.vms is a int64, not a table of rows"},
		"empty key":       {"get", `{"id": ""}`, nil, "c.get.store.key: needs a non-empty string"},
		"list key":        {"get", `{"id": [1]}`, nil, "needs a non-empty string or a whole number"},
		"missing input":   {"get", `{}`, nil, "c.get.store.key"},
		"non-numeric row": {"bump", `{"id": "j", "n": 1}`, map[string]map[string]any{"c": {"counts": map[string]any{"j": map[string]any{"done": "many"}}}}, "field done: cannot add"},
		"map onto number": {"bump", `{"id": "j", "n": 1}`, map[string]map[string]any{"c": {"counts": map[string]any{"j": int64(4)}}}, "cannot add a map of deltas"},
		"number onto map": {"tick", ``, map[string]map[string]any{"c": {"seq": map[string]any{"global": map[string]any{}}}}, "cannot add"},
	} {
		req := sim.Request{Flow: c.flow, State: c.state}
		if c.input != "" {
			req.Input = json.RawMessage(c.input)
		}
		res := run(t, doc, req)
		if res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, c.abort) {
			t.Errorf("%s: status %s abort %q", name, res.Summary.Status, res.Summary.Abort)
		}
	}
	// An integer key is a string id.
	res = run(t, doc, sim.Request{Flow: "get", Input: json.RawMessage(`{"id": 7}`), State: map[string]map[string]any{"c": {"vms": map[string]any{"7": "seven"}}}})
	okValue(t, res)
	if out := eventsFor(res, "call.end", "c.get")[0].Output; out != "seven" {
		t.Errorf("integer key read %v", out)
	}
	// A behavior beside a store wins.
	eq(t, "behavior wins", okValue(t, run(t, doc, sim.Request{Flow: "both"})), "from-behavior")
}

func TestForeach(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: b, name: deliver, behavior: [{set: {state.count: "= state.count + 1"}}, {return: "= input.url"}]}
  - component: a
    name: fanout
    behavior:
      - {set: {vars.item: before}}
      - foreach: "= input.hooks"
        steps:
          - {call: b.deliver, input: {url: "= vars.item"}, as: d}
          - {set: {ctx.seen: "= has(ctx.seen) ? ctx.seen + [vars.index] : [vars.index]"}}
      - return: {item: "= vars.item", has_index: "= has(vars.index)", seen: "= ctx.seen"}
  - component: a
    name: sweep
    behavior:
      - foreach: "= state.rows"
        as: row
        index: id
        steps:
          - {if: "vars.row == 'skip'", then: [{continue: true}]}
          - {if: "vars.row == 'stop'", then: [{break: true}]}
          - {set: {ctx.done: "= has(ctx.done) ? ctx.done + [vars.id] : [vars.id]"}}
      - return: "= ctx.done"
  - component: a
    name: find
    behavior:
      - foreach: [3, "= 1 + 3", 5]
        as: n
        steps:
          - {if: "vars.n % 2 == 0", then: [{return: "= vars.n"}]}
      - fail: {code: none_even}
  - component: a
    name: capped
    behavior:
      - foreach: "= [1, 2, 3, 4, 5]"
        max: 2
        steps: [{set: {ctx.n: "= has(ctx.n) ? ctx.n + 1 : 1"}}]
      - return: "= ctx.n"
  - component: a
    name: empty
    behavior:
      - foreach: "= null"
        steps: [{fail: {code: never}}]
      - return: done
  - component: a
    name: scalar
    behavior:
      - {foreach: "= 3", steps: [{wait: 1}]}
  - component: a
    name: nested
    behavior:
      - foreach: "= [1, 2, 3]"
        steps:
          - foreach: "= [10, 20, 30]"
            as: j
            index: jj
            steps:
              - {if: "vars.j == 20", then: [{break: true}]}
              - {set: {ctx.pairs: "= (has(ctx.pairs) ? ctx.pairs : []) + [vars.item * vars.j]"}}
      - return: "= ctx.pairs"
`)
	res := run(t, doc, sim.Request{Flow: "fanout", Input: json.RawMessage(`{"hooks": ["h1", "h2", "h3"]}`)})
	// Loop variables are restored afterwards; iterations run in order.
	eq(t, "fanout", okValue(t, res), map[string]any{"item": "before", "has_index": false, "seen": []any{int64(0), int64(1), int64(2)}})
	eq(t, "fanout calls", res.Summary.Calls["b.deliver"], 3)
	eq(t, "fanout state", res.Summary.State["b"]["count"], int64(3))
	var urls []any
	for _, e := range eventsFor(res, "call.end", "b.deliver") {
		urls = append(urls, e.Output)
	}
	eq(t, "delivery order", urls, []any{"h1", "h2", "h3"})

	// Maps iterate by sorted key; continue skips, break stops.
	seed := map[string]map[string]any{"a": {"rows": map[string]any{"d": "x", "a": "x", "c": "stop", "b": "skip"}}}
	eq(t, "sweep", okValue(t, run(t, doc, sim.Request{Flow: "sweep", State: seed})), []any{"a"})
	eq(t, "return inside a loop", okValue(t, run(t, doc, sim.Request{Flow: "find"})), int64(4))

	res = run(t, doc, sim.Request{Flow: "capped"})
	eq(t, "capped", okValue(t, res), int64(2))
	eq(t, "cap warning", res.Summary.Warnings, []string{"a.capped.behavior[0]: foreach stopped after max 2 of 5 items"})
	eq(t, "null is empty", okValue(t, run(t, doc, sim.Request{Flow: "empty"})), "done")
	eq(t, "break leaves the inner loop only", okValue(t, run(t, doc, sim.Request{Flow: "nested"})), []any{int64(10), int64(20), int64(30)})

	res = run(t, doc, sim.Request{Flow: "scalar"})
	if res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, "a.scalar.behavior[0].foreach: needs a list or a map, got int64") {
		t.Errorf("scalar foreach: %+v", res.Summary)
	}
	res, err := sim.RunWithLimits(doc, sim.Request{Flow: "nested"}, sim.Limits{MaxEvents: 1000, MaxDepth: 8, MaxEmits: 3, MaxIterations: 4})
	if err != nil || res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, "loop budget of 4 iterations exceeded") {
		t.Errorf("loop budget: %v %+v", err, res.Summary)
	}
}

func TestRepeat(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: b, name: audit, behavior: [{set: {state.count: "= state.count + 1"}}]}
  - component: a
    name: reconcile
    behavior:
      - {set: {state.x: "= state.x + 1"}}
      - {emit: b.audit}
      - {wait: 10}
      - {if: "state.x == 4", then: [{fail: {code: drift, status: 500}}]}
      - return: {x: "= state.x", at: "= now"}
  - {component: a, name: once, behavior: [{return: 1}]}
`)
	for i := range doc.Flows {
		if doc.Flows[i].ID == "reconcile" {
			doc.Flows[i].Entry.Repeat = &model.Repeat{Count: 3, IntervalMS: 1000}
		}
	}
	res := run(t, doc, sim.Request{Flow: "reconcile", Expect: []string{
		"size(passes) == 3",
		"passes[0].result.ok && passes[0].result.value.x == 2",
		"passes[1].start_ms == passes[0].start_ms + passes[0].duration_ms + 1000",
		"passes[2].result.error.code == 'drift'",
		"state.a.x == 4 && state.b.count == 3",
		"status == 'error'",
	}})
	for _, a := range res.Summary.Assertions {
		if !a.Passed {
			t.Errorf("assertion %s failed %s", a.Expr, a.Error)
		}
	}
	s := res.Summary
	if len(s.Passes) != 3 || s.Passes[1].Pass != 2 {
		t.Fatalf("passes: %+v", s.Passes)
	}
	// Each pass delivers its emits before the clock moves on: pass 1 takes
	// 1 ms latency + 10 ms wait + 1 ms for the audit delivery.
	eq(t, "pass 1 duration", s.Passes[0].DurationMS, int64(12))
	eq(t, "pass 2 start", s.Passes[1].StartMS, int64(1012))
	eq(t, "pass 2 value", s.Passes[1].Result.Value, map[string]any{"x": int64(3), "at": int64(1023)})
	eq(t, "calls", s.Calls["a.reconcile"], 3)
	if s.Result.Error == nil || s.Result.Error.Code != "drift" {
		t.Errorf("the result is the last pass: %+v", s.Result)
	}

	// Without repeat the summary has no passes, but expectations see one.
	res = run(t, doc, sim.Request{Flow: "once", Expect: []string{"size(passes) == 1 && passes[0].result.value == 1 && passes[0].pass == 1"}})
	if res.Summary.Passes != nil || !res.Summary.Passed {
		t.Errorf("single pass: %+v", res.Summary)
	}
	b, _ := json.Marshal(res.Summary)
	if strings.Contains(string(b), `"passes"`) {
		t.Errorf("a run without repeat must not encode passes: %s", b)
	}
}

func TestDisabledInterfaces(t *testing.T) {
	doc, err := model.ParseDocument([]byte(`
schema_version: 1
components: [{id: user, kind: external}, {id: api}, {id: work, capacity: {concurrency: 1}}, {id: db}]
interfaces:
  - {component: db, name: put, store: {table: rows, op: put, key: "= input.id", value: "= input"}}
  - component: api
    name: go
    behavior:
      - {call: work.do, as: r, on_error: continue}
      - {return: {ok: "= vars.r.ok", n: "= vars.r.ok && has(vars.r.value.n) ? vars.r.value.n : -1"}}
  - component: work
    name: do
    latency_ms: 50
    behavior:
      - {call: db.put, input: {id: a}}
      - {set: {state.ran: true}}
      - {return: {n: 1}}
flows:
  - {id: go, entry: {caller: user, interface: api.go}}
`))
	if err != nil {
		t.Fatal(err)
	}
	run := func(d map[string]sim.DisabledResult, req sim.Request) *sim.Result {
		t.Helper()
		lim := sim.DefaultLimits
		lim.DisabledInterfaces = d
		req.Flow = "go"
		res, err := sim.RunWithLimits(doc, req, lim)
		if err != nil {
			t.Fatal(err)
		}
		return res
	}
	on := run(nil, sim.Request{})
	if v := on.Summary.Result.Value.(map[string]any); v["n"] != int64(1) || on.Summary.Calls["db.put"] != 1 || on.Summary.DurationMS < 50 {
		t.Fatalf("unmutated: %+v", on.Summary)
	}
	for name, c := range map[string]struct {
		d     sim.DisabledResult
		ok    bool
		wantN int64
	}{
		"empty": {sim.DisabledResult{}, true, -1},
		"value": {sim.DisabledResult{Value: map[string]any{"n": int64(0)}}, true, 0},
		"error": {sim.DisabledResult{Err: &sim.Error{Code: "off", Status: 500}}, false, -1},
	} {
		res := run(map[string]sim.DisabledResult{"work.do": c.d}, sim.Request{})
		s := res.Summary
		if v := s.Result.Value.(map[string]any); v["ok"] != c.ok || v["n"] != c.wantN {
			t.Errorf("%s: result %+v", name, s.Result)
		}
		if s.Calls["work.do"] != 1 || s.Calls["db.put"] != 0 || s.DurationMS >= 50 {
			t.Errorf("%s: the behavior ran or took time: %+v, %d ms", name, s.Calls, s.DurationMS)
		}
		if len(s.State["work"]) != 0 || len(s.State["db"]) != 0 {
			t.Errorf("%s: state written: %+v", name, s.State)
		}
	}
	// A fault is the world's: it still applies to a disabled interface.
	f := run(map[string]sim.DisabledResult{"work.do": {}}, sim.Request{Faults: []model.Fault{{Target: "work.do", Type: "unavailable"}}})
	if v := f.Summary.Result.Value.(map[string]any); v["ok"] != false {
		t.Errorf("fault on a disabled interface: %+v", f.Summary.Result)
	}
}

package sim_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// The §11 language additions, tested on the §11.10 generality cases.

// langDoc parses a whole document and requires it to validate.
func langDoc(t *testing.T, src string) *model.Document {
	t.Helper()
	doc, err := model.ParseDocument([]byte("schema_version: 1\n" + src))
	if err != nil {
		t.Fatal(err)
	}
	for _, is := range model.Validate(doc) {
		if is.Severity == model.SeverityError {
			t.Fatalf("test document: %s: %s", is.Path, is.Message)
		}
	}
	return doc
}

// passes runs a scenario and requires every expectation to hold.
func passes(t *testing.T, doc *model.Document, req sim.Request) *sim.Result {
	t.Helper()
	res := run(t, doc, req)
	s := res.Summary
	if s.Status == "aborted" {
		t.Fatalf("aborted: %s", s.Abort)
	}
	for _, a := range s.Assertions {
		if !a.Passed {
			t.Errorf("failed: %s %s (status %s, result %+v, duration %d)", a.Expr, a.Error, s.Status, s.Result, s.DurationMS)
		}
	}
	return res
}

const quorumDoc = `
components:
  - {id: client}
  - {id: coord}
  - {id: replica, state: {initial: {rows: {}}}}
interfaces:
  - component: coord
    name: write
    latency_ms: 0
    behavior:
      - parallel: [n1, n2, n3]
        as: replica
        steps:
          - {call: replica.apply, on: "= vars.replica", input: {k: "= input.k"}}
        join: {need: 2}
        as_result: acks
        on_insufficient: {code: unavailable, status: 503}
      - {return: "= vars.acks"}
  - component: replica
    name: apply
    latency_ms: "= self == 'n1' ? 1000 : (self == 'n2' ? 2000 : 4000)"
    behavior:
      - set: {state.rows: "= merge(state.rows, {input.k: self})"}
flows:
  - {id: write, entry: {caller: client, interface: coord.write, input: {k: v1}}}
scenarios:
  - id: quorum
    flow: write
    topology: {replica: [n1, n2, n3]}
    expect:
      - result.ok
      - duration_ms == 2000
      - result.value.received == 2 && result.value.required == 2
      - result.value.results.map(r, r.late) == [false, false, true]
      - calls_by_instance['replica.apply@n3'] == 1
      - state['replica@n3'].rows.v1 == 'n3'
      - trace.exists(e, e.type == 'call.end' && e.instance == 'n3' && e.late && e.t == 4000)
      - trace.exists(e, e.type == 'parallel.end' && e.t == 2000)
`

// TestQuorumWrite: a QUORUM write returns at the second ack (2,000 ms, not
// 4,000), and the third replica's write still lands, marked late.
func TestQuorumWrite(t *testing.T) {
	doc := langDoc(t, quorumDoc)
	res := passes(t, doc, sim.Request{Scenario: "quorum"})
	s := res.Summary
	eq(t, "duration", s.DurationMS, int64(2000))
	eq(t, "calls by instance", s.CallsByInstance, map[string]int{"replica.apply@n1": 1, "replica.apply@n2": 1, "replica.apply@n3": 1})
	start := events(res, "parallel.start")
	if len(start) != 1 || !jsonEq(start[0].Output, map[string]any{"branches": 3, "need": 2}) {
		t.Errorf("parallel.start %+v", start)
	}
	for _, e := range res.Trace {
		if e.Instance == "n3" && e.Type == "set" && (!e.Late || e.Branch == nil || *e.Branch != 2) {
			t.Errorf("n3's write should be late in branch 2: %+v", e)
		}
	}

	// Two replicas down: the join fails as soon as success is impossible.
	res = run(t, doc, sim.Request{Scenario: "quorum", Faults: []model.Fault{
		{Target: "replica", Type: "unavailable", Instance: "n1"}, {Target: "replica", Type: "unavailable", Instance: "n2"}}})
	s = res.Summary
	if s.Result.OK || s.Result.Error.Code != "unavailable" || s.Result.Error.Status != 503 || s.DurationMS != 0 {
		t.Fatalf("result %+v at %d", s.Result, s.DurationMS)
	}
	if !jsonEq(s.Result.Error.Data, map[string]any{"received": 0, "required": 2, "failed": 2}) {
		t.Errorf("error data %v", s.Result.Error.Data)
	}
	eq(t, "late write still lands", s.State["replica@n3"]["rows"], map[string]any{"v1": "n3"})
	if end := events(res, "parallel.end"); len(end) != 1 || end[0].Error == nil {
		t.Errorf("parallel.end %+v", end)
	}
}

// TestHedgedRead: a speculative read starts a second replica after
// stagger_ms only while the first has not answered, and the third never.
func TestHedgedRead(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: client}
  - {id: coord}
  - {id: replica}
interfaces:
  - component: coord
    name: read
    latency_ms: 0
    behavior:
      - parallel: [n1, n2, n3]
        steps:
          - {call: replica.read, on: "= vars.item", input: {slow: "= input.slow"}, as: got}
          - {return: "= vars.got.value"}
        join: {need: any}
        stagger_ms: "= input.stagger"
        as_result: r
      - {return: "= vars.r"}
  - component: replica
    name: read
    latency_ms: "= self == 'n1' ? input.slow : 100"
    response: {type: string, const: data}
flows:
  - {id: read, entry: {caller: client, interface: coord.read}}
scenarios:
  - id: hedged
    flow: read
    topology: {replica: [n1, n2, n3]}
    input: {stagger: 200, slow: 500}
    expect:
      - duration_ms == 300
      - result.value.results.map(r, r.started) == [true, true, false]
      - calls_by_instance['replica.read@n3'] == 0
      - result.value.results[1].value == 'data'
  - id: fast-first
    flow: read
    topology: {replica: [n1, n2, n3]}
    input: {stagger: 200, slow: 50}
    expect:
      - duration_ms == 50
      - calls['replica.read'] == 1
`)
	passes(t, doc, sim.Request{Scenario: "hedged"})
	passes(t, doc, sim.Request{Scenario: "fast-first"})
}

const allReduceDoc = `
components:
  - {id: client}
  - {id: engine}
  - {id: gpu-worker}
configs:
  - {id: tensor-parallel-size, type: integer, value: 4}
interfaces:
  - component: engine
    name: step
    latency_ms: 0
    behavior:
      - parallel: "= ['r0', 'r1', 'r2', 'r3'].filter(r, int(r.substring(1)) < config['tensor-parallel-size'])"
        as: rank
        steps:
          - {call: gpu-worker.all-reduce, on: "= vars.rank", input: {part: "= int(vars.rank.substring(1))"}}
          - {return: "= int(vars.rank.substring(1))"}
        join: {need: all}
        as_result: reduce
      - return: {total: "= sum(vars.reduce.results.map(r, r.value))", ok: "= vars.reduce.ok"}
  - component: gpu-worker
    name: all-reduce
    latency_ms: "= 10 * (input.part + 1)"
flows:
  - {id: step, entry: {caller: client, interface: engine.step}}
scenarios:
  - id: all-reduce
    flow: step
    topology: {gpu-worker: [r0, r1, r2, r3]}
    expect: ["result.value == {'total': 6, 'ok': true}", "duration_ms == 40", "size(calls_by_instance) == 4"]
`

// TestAllReduce: tensor-parallel all-reduce waits for every rank (join all)
// and fails when one rank is down.
func TestAllReduce(t *testing.T) {
	doc := langDoc(t, allReduceDoc)
	passes(t, doc, sim.Request{Scenario: "all-reduce"})
	res := run(t, doc, sim.Request{Scenario: "all-reduce", Faults: []model.Fault{{Target: "gpu-worker.all-reduce", Type: "error", Code: "nccl_error", Instance: "r2"}}})
	if e := res.Summary.Result.Error; e == nil || e.Code != "insufficient" || !e.Retryable {
		t.Fatalf("result %+v", res.Summary.Result)
	}
	// The failure is known when r2 fails, at 30 ms.
	eq(t, "fails at r2", res.Summary.DurationMS, int64(30))
	// A smaller tensor-parallel size from config means fewer ranks.
	res = run(t, doc, sim.Request{Scenario: "all-reduce", Config: map[string]any{"tensor-parallel-size": 2},
		Expect: []string{"config['tensor-parallel-size'] == 2", "calls['gpu-worker.all-reduce'] == 2", "result.value.total == 1"}})
	for _, a := range res.Summary.Assertions[3:] {
		if !a.Passed {
			t.Errorf("failed: %s %s", a.Expr, a.Error)
		}
	}
	if !jsonEq(res.Request.Config, map[string]any{"tensor-parallel-size": 2}) {
		t.Errorf("effective request should echo the config override: %v", res.Request.Config)
	}
}

// TestDeadline: a cancellation deadline cuts calls short, refuses calls
// that start after it, stops retries, and is inherited by nested calls.
func TestDeadline(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: client}
  - {id: host}
  - {id: provider}
interfaces:
  - component: host
    name: complete
    latency_ms: 0
    behavior:
      - {set: {ctx.deadline: "= deadline"}}
      - {call: provider.slow, as: first}
      - {call: provider.nested, as: second, on_error: continue}
      - {call: provider.slow, as: third, on_error: continue}
      - return: {first: "= vars.first.ok", second: "= vars.second.error.code", third: "= vars.third.error.code"}
  - component: host
    name: retrying
    latency_ms: 0
    behavior:
      - call: provider.flaky
        deadline_ms: "= 250"
        retry: {max_attempts: 10, backoff_ms: 100}
        on_error: continue
        as: r
      - {return: "= vars.r.attempts"}
  - {component: provider, name: slow, latency_ms: 80}
  - component: provider
    name: nested
    latency_ms: 0
    behavior:
      - {call: provider.slow, on_error: continue}
      - {call: provider.slow}
  - {component: provider, name: flaky, latency_ms: 10}
flows:
  - {id: complete, entry: {caller: client, interface: host.complete, deadline_ms: 100}}
  - {id: retrying, entry: {caller: client, interface: host.retrying}}
scenarios:
  - id: cancel
    flow: complete
    clock: {epoch_ms: 1000000}
    expect:
      - "ctx.deadline == 1000100"
      - "result.value.first"
      - "result.value.second == 'deadline_exceeded'"
      - "result.value.third == 'deadline_exceeded'"
      - "trace.exists(e, e.type == 'deadline' && e.interface == 'provider.slow')"
      - "duration_ms == 100"
`)
	res := passes(t, doc, sim.Request{Scenario: "cancel"})
	if d := events(res, "deadline"); len(d) != 2 {
		// the nested second slow call and the third call are both refused
		t.Errorf("deadline events %+v", d)
	}
	res = run(t, doc, sim.Request{Flow: "retrying", Faults: []model.Fault{{Target: "provider.flaky", Type: "unavailable"}}})
	// attempts at 0, 100 and 200; the fourth would start at 300, after the deadline at 250
	eq(t, "attempts", res.Summary.Result.Value, int64(3))
}

// TestTimers: a debounced save (only the last keystroke's timer saves), a
// periodic gossip timer, repeat.initial_delay_ms and the timer budget.
func TestTimers(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: user}
  - {id: editor, state: {initial: {last: -1, saves: []}}}
  - {id: gossiper, state: {initial: {rounds: []}}}
interfaces:
  - component: editor
    name: type
    latency_ms: 0
    behavior:
      - {set: {state.last: "= now"}}
      - {emit: editor.save, input: {at: "= now"}, after_ms: 500}
  - component: editor
    name: save
    latency_ms: 0
    behavior:
      - if: "input.at == state.last"
        then: [{set: {state.saves: "= state.saves + [now]"}}]
  - component: gossiper
    name: start
    latency_ms: 0
    behavior:
      - {emit: gossiper.round, every_ms: "= 1000", count: 3, after_ms: 1000}
  - component: gossiper
    name: round
    latency_ms: 0
    behavior:
      - {set: {state.rounds: "= state.rounds + [now]"}}
  - component: gossiper
    name: storm
    latency_ms: 0
    behavior:
      - {emit: gossiper.round, every_ms: 1, count: 1000}
      - {emit: gossiper.round, every_ms: 1, count: 1000}
flows:
  - {id: type, entry: {caller: user, interface: editor.type}}
  - {id: gossip, entry: {caller: user, interface: gossiper.start}}
  - {id: storm, entry: {caller: user, interface: gossiper.storm}}
  - {id: tick, entry: {caller: user, interface: gossiper.round, repeat: {count: 2, interval_ms: 10, initial_delay_ms: 5}}}
scenarios:
  - id: debounce
    steps:
      - {flow: type, at_ms: 0}
      - {flow: type, at_ms: 100}
      - {flow: type, at_ms: 200}
  - id: debounce-burst
    flow: type
    steps:
      - {flow: type}
    expect: ["state.editor.saves == [500]", "duration_ms == 500"]
`)
	// at_ms steps start on time while the earlier steps' timers are
	// pending (§17 item 9), so only the last keystroke saves.
	res := run(t, doc, sim.Request{Scenario: "debounce"})
	if w := res.Summary.Warnings; len(w) != 0 {
		t.Errorf("warnings %v", w)
	}
	eq(t, "saves", res.Summary.State["editor"]["saves"], []any{int64(700)})
	passes(t, doc, sim.Request{Scenario: "debounce-burst"})

	res = run(t, doc, sim.Request{Flow: "gossip"})
	eq(t, "rounds", res.Summary.State["gossiper"]["rounds"], []any{int64(1000), int64(2000), int64(3000)})

	res = run(t, doc, sim.Request{Flow: "tick"})
	if p := res.Summary.Passes; len(p) != 2 || p[0].StartMS != 5 || p[1].StartMS != 15 {
		t.Errorf("passes %+v", res.Summary.Passes)
	}

	res = run(t, doc, sim.Request{Flow: "storm"})
	if res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, "timer budget of 1000") {
		t.Errorf("status %s abort %q", res.Summary.Status, res.Summary.Abort)
	}
}

// TestDebounce: three keystrokes inside one step, 100 ms apart; only the
// last one's timer saves, 500 ms after it.
func TestDebounce(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: user}
  - {id: editor, state: {initial: {last: -1, saves: []}}}
interfaces:
  - component: editor
    name: burst
    latency_ms: 0
    behavior:
      - foreach: [1, 2, 3]
        steps:
          - {call: editor.type}
          - {wait: 100}
  - component: editor
    name: type
    latency_ms: 0
    behavior:
      - {set: {state.last: "= now"}}
      - {emit: editor.save, input: {at: "= now"}, after_ms: 500}
  - component: editor
    name: save
    latency_ms: 0
    behavior:
      - if: "input.at == state.last"
        then: [{set: {state.saves: "= state.saves + [now]"}}]
flows:
  - {id: burst, entry: {caller: user, interface: editor.burst}}
scenarios:
  - id: debounce
    flow: burst
    clock: {epoch: "2026-10-30T00:00:00Z"}
    expect:
      - "calls['editor.save'] == 3"
      - "size(state.editor.saves) == 1"
      - "state.editor.saves[0] - 1793318400000 == 700"
      - "duration_ms == 700"
      - "trace.filter(e, e.type == 'call.start' && e.interface == 'editor.save').map(e, e.t) == [500, 600, 700]"
`)
	passes(t, doc, sim.Request{Scenario: "debounce"})
}

// TestCapacity: an extension host with one thread serializes calls from
// parallel activations; queue_limit and queue_timeout_ms refuse calls.
func TestCapacity(t *testing.T) {
	src := `
components:
  - {id: window}
  - {id: ext-host, capacity: {concurrency: 1CAP}}
interfaces:
  - component: window
    name: activate-all
    latency_ms: 0
    behavior:
      - parallel: [git, python, eslint]
        steps: [{call: ext-host.activate, input: {ext: "= vars.item"}}]
        as_result: acts
      - {return: "= vars.acts"}
  - component: ext-host
    name: activate
    latency_ms: 100
    behavior:
      - {call: ext-host.register}
  - {component: ext-host, name: register, latency_ms: 0}
flows:
  - {id: activate, entry: {caller: window, interface: window.activate-all}}
`
	doc := langDoc(t, strings.Replace(src, "CAP", "", 1))
	res := run(t, doc, sim.Request{Flow: "activate"})
	s := res.Summary
	if !s.Result.OK || s.DurationMS != 300 || s.Queued != 2 {
		t.Fatalf("result %+v, duration %d, queued %d", s.Result, s.DurationMS, s.Queued)
	}
	var waits []int64
	for _, e := range events(res, "queue") {
		waits = append(waits, e.WaitMS)
	}
	eq(t, "waits", waits, []int64{100, 200})

	doc = langDoc(t, strings.Replace(src, "CAP", ", queue_limit: 1", 1))
	res = run(t, doc, sim.Request{Flow: "activate"})
	if e := res.Summary.Result.Error; e == nil || e.Code != "insufficient" {
		t.Fatalf("result %+v", res.Summary.Result)
	}
	if ends := eventsFor(res, "call.end", "ext-host.activate"); len(ends) != 3 || ends[2].Error == nil || ends[2].Error.Code != "overloaded" {
		t.Errorf("third activation should be overloaded: %+v", ends)
	}

	doc = langDoc(t, strings.Replace(src, "CAP", ", queue_timeout_ms: 150", 1))
	res = run(t, doc, sim.Request{Flow: "activate"})
	ends := eventsFor(res, "call.end", "ext-host.activate")
	if len(ends) != 3 || ends[2].Error == nil || ends[2].Error.Code != "overloaded" || ends[2].T != 150 {
		t.Errorf("third activation should give up at 150: %+v", ends)
	}
}

const pubsubDoc = `
components:
  - {id: user}
  - {id: doc-model}
  - {id: outline}
  - {id: problems}
  - {id: minimap}
interfaces:
  - component: doc-model
    name: edit
    latency_ms: 0
    behavior:
      - {publish: doc-model.changed, input: {version: 2}, delivery: "= input.delivery"}
      - {set: {ctx.after_publish: "= now"}}
  - component: doc-model
    name: edit-strict
    latency_ms: 0
    behavior:
      - {publish: doc-model.changed, input: {version: 2}, delivery: sync, on_error: propagate}
  - {component: doc-model, name: changed, kind: event}
  - component: outline
    name: on-change
    subscribe: [doc-model.changed]
    latency_ms: 5
    behavior: [{set: {ctx.seen: "= (has(ctx.seen) ? ctx.seen : []) + ['outline']"}}]
  - component: problems
    name: on-change
    subscribe: [doc-model.changed]
    latency_ms: 5
    behavior:
      - {set: {ctx.seen: "= (has(ctx.seen) ? ctx.seen : []) + ['problems']"}}
      - {fail: {code: lint_crash}}
  - component: minimap
    name: on-change
    subscribe: [doc-model.changed]
    latency_ms: 5
    behavior: [{set: {ctx.seen: "= (has(ctx.seen) ? ctx.seen : []) + ['minimap']"}}]
flows:
  - {id: edit, entry: {caller: user, interface: doc-model.edit}}
  - {id: edit-strict, entry: {caller: user, interface: doc-model.edit-strict}}
`

// TestPublishSync: a VS Code-style sync emitter with three subscribers runs
// them inline in sorted order; a failing listener does not fail the
// publisher unless on_error is propagate. Async delivery queues them.
func TestPublishSync(t *testing.T) {
	// delivery is not a template; the test swaps it in the source.
	sync := langDoc(t, strings.Replace(pubsubDoc, `"= input.delivery"`, "sync", 1))
	res := run(t, sync, sim.Request{Flow: "edit"})
	s := res.Summary
	if !s.Result.OK {
		t.Fatalf("result %+v", s.Result)
	}
	eq(t, "order", s.Ctx["seen"], []any{"minimap", "outline", "problems"})
	eq(t, "inline", s.Ctx["after_publish"], int64(15))
	if p := events(res, "publish"); len(p) != 1 || p[0].Topic != "doc-model.changed" {
		t.Errorf("publish %+v", p)
	}

	res = run(t, sync, sim.Request{Flow: "edit-strict"})
	if e := res.Summary.Result.Error; e == nil || e.Code != "lint_crash" {
		t.Errorf("propagate: %+v", res.Summary.Result)
	}

	async := langDoc(t, strings.Replace(pubsubDoc, `"= input.delivery"`, "async", 1))
	res = run(t, async, sim.Request{Flow: "edit"})
	eq(t, "async after publisher", res.Summary.Ctx["after_publish"], int64(0))
	eq(t, "async order", res.Summary.Ctx["seen"], []any{"minimap", "outline", "problems"})
	if em := events(res, "emit"); len(em) != 3 || em[0].Topic != "doc-model.changed" {
		t.Errorf("emits %+v", em)
	}
	for _, e := range events(res, "call.start") {
		if e.Interface != "doc-model.edit" && !e.Async {
			t.Errorf("subscriber call should be async: %+v", e)
		}
	}
}

// TestLatencyExpression: vLLM prefill time grows with the token count and a
// per-token cost from config; decode time with the batch size.
func TestLatencyExpression(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: client}
  - {id: engine}
configs:
  - {id: prefill-us-per-token, type: integer, value: 500, default: 250}
interfaces:
  - component: engine
    name: generate
    latency_ms: 0
    behavior:
      - {call: engine.prefill, input: {tokens: "= input.prompt.split(' ')"}}
      - {call: engine.decode, input: {batch: 8}, timeout_ms: "= config['prefill-us-per-token'] / 10"}
  - component: engine
    name: prefill
    latency_ms: "= size(input.tokens) * config['prefill-us-per-token'] / 1000"
  - component: engine
    name: decode
    latency_ms: "= 2 * input.batch + (state.warm ? 0 : 100)"
flows:
  - {id: generate, entry: {caller: client, interface: engine.generate}}
scenarios:
  - id: prefill
    flow: generate
    input: {prompt: "a b c d e f g h"}
    state: {engine: {warm: true}}
    expect: ["result.ok", "duration_ms == 4 + 16"]
  - id: cold-and-cheap
    flow: generate
    input: {prompt: "a b c d e f g h"}
    config: {prefill-us-per-token: 250}
    state: {engine: {warm: false}}
    expect: ["result.error.code == 'timeout'", "duration_ms == 2 + 25"]
`)
	passes(t, doc, sim.Request{Scenario: "prefill"})
	passes(t, doc, sim.Request{Scenario: "cold-and-cheap"})
}

const writeReadDoc = `
components:
  - {id: client}
  - {id: node}
  - {id: coord, parent: node}
  - {id: memtable, parent: node, state: {initial: {rows: {}}}}
fixtures:
  - id: base
    config: {consistency: QUORUM}
  - id: three-nodes
    extends: [base]
    topology: {node: [n1, n2, n3]}
    state: {"memtable@n2": {rows: {old: {v: 0}}}}
configs:
  - {id: consistency, type: string, value: ONE}
interfaces:
  - component: coord
    name: write
    latency_ms: 1
    behavior:
      - parallel: [n1, n2, n3]
        steps: [{call: memtable.put, on: "= vars.item", input: "= input"}]
        join: {need: "= config.consistency == 'QUORUM' ? 2 : 1"}
      - {return: {key: "= input.key"}}
  - component: coord
    name: read
    latency_ms: 1
    behavior:
      - {call: memtable.get, input: {key: "= input.key"}, as: got}
      - {return: "= vars.got.value"}
  - {component: memtable, name: put, latency_ms: 2, store: {table: rows, op: put, key: "= input.key", value: "= input"}}
  - {component: memtable, name: get, latency_ms: 2, store: {table: rows, op: get, key: "= input.key"}}
flows:
  - {id: write, entry: {caller: client, interface: coord.write, input: {key: k1, v: 7}}}
  - {id: read, entry: {caller: client, interface: coord.read, on: n1}}
scenarios:
  - id: write-then-read
    fixtures: [three-nodes]
    steps:
      - {flow: write, as: w}
      - {flow: read, at_ms: 50, input: {key: "= steps.w.result.value.key"}, as: r}
      - {interface: memtable.get, caller: client, on: "= 'n' + string(1 + 1)", input: {key: old}}
    expect:
      - steps.w.result.ok && steps.w.status == 'ok' && steps.w.start_ms == 0
      - steps.r.start_ms == 50
      - steps.r.result.value.v == 7
      - steps[2].result.value.v == 0
      - "result.value == {'v': 0}"
      - config.consistency == 'QUORUM'
      - topology.node == ['n1', 'n2', 'n3']
      - state['memtable@n3'].rows.k1.v == 7
`

// TestWriteThenRead: a multi-step scenario writes through one flow and
// reads the write back through another, on fixture-built instances.
func TestWriteThenRead(t *testing.T) {
	doc := langDoc(t, writeReadDoc)
	res := passes(t, doc, sim.Request{Scenario: "write-then-read"})
	s := res.Summary
	if len(s.Steps) != 3 || s.Steps[0].As != "w" || s.Steps[0].Flow != "write" || s.Steps[1].On != "n1" || s.Steps[2].On != "n2" ||
		s.Steps[1].StartMS != 50 || s.Steps[2].Interface != "memtable.get" {
		t.Errorf("steps %+v", s.Steps)
	}
	var keys []string
	for _, e := range res.Trace {
		if e.Type == "step.start" || e.Type == "step.end" {
			keys = append(keys, e.Type+":"+e.Key)
		}
	}
	eq(t, "step events", keys, []string{"step.start:w", "step.end:w", "step.start:r", "step.end:r", "step.start:2", "step.end:2"})
	if res.Request.Flow != "write" || len(res.Request.Fixtures) != 1 || res.Request.Topology["node"] == nil {
		t.Errorf("effective request %+v", res.Request)
	}
	if _, ok := s.InitialState["memtable@n2"]["rows"].(map[string]any)["old"]; !ok {
		t.Errorf("initial state %v", s.InitialState)
	}

	// The fixture can come from the request too.
	res = passes(t, doc, sim.Request{Flow: "write", Fixtures: []string{"three-nodes"}, Expect: []string{"calls_by_instance.filter(k, calls_by_instance[k] > 0).size() == 4"}})
	if _, err := sim.Run(doc, sim.Request{Flow: "write", Fixtures: []string{"nope"}}); err == nil {
		t.Errorf("unknown fixture should be a request error")
	}
}

// TestGossipState: per-instance state, instance overrides, self, the
// cross-group warning and unknown instances.
func TestGossipState(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: operator}
  - {id: cluster}
  - {id: node, parent: cluster}
  - {id: gossiper, parent: node, state: {initial: {version: 0, peers: {}}}}
  - {id: seed-provider}
interfaces:
  - component: gossiper
    name: run
    latency_ms: 0
    behavior:
      - {set: {state.version: "= state.version + 1"}}
      - {call: gossiper.syn, on: "= input.peer", input: {from: "= self", version: "= state.version"}}
      - {call: seed-provider.seeds}
  - component: gossiper
    name: syn
    latency_ms: 0
    behavior:
      - {set: {"state.peers": "= merge(state.peers, {input.from: input.version})"}}
  - {component: seed-provider, name: seeds, latency_ms: 0}
  - component: operator
    name: bad
    latency_ms: 0
    behavior:
      - {call: gossiper.syn, on: n9, as: r, on_error: continue}
      - {return: "= vars.r.error.code"}
  - component: operator
    name: default
    latency_ms: 0
    behavior:
      - {call: gossiper.syn, input: {from: operator, version: 1}}
flows:
  - {id: gossip, entry: {caller: operator, interface: gossiper.run, input: {peer: n3}}}
  - {id: bad, entry: {caller: operator, interface: operator.bad}}
  - {id: default, entry: {caller: operator, interface: operator.default}}
scenarios:
  - id: rounds
    topology: {node: [n1, n2, n3]}
    state: {gossiper: {version: 5}, "gossiper@n2": {version: 10}}
    steps:
      - {flow: gossip, on: n1}
      - {flow: gossip, on: n2}
      - {interface: gossiper.run, caller: operator, on: n2, input: {peer: n1}}
    expect:
      - state['gossiper@n1'].version == 6
      - state['gossiper@n2'].version == 12
      - "state['gossiper@n3'].peers == {'n1': 6, 'n2': 11}"
      - "state['gossiper@n1'].peers == {'n2': 12}"
      - calls_by_instance['gossiper.syn@n3'] == 2
      - calls_by_instance['gossiper.run@n3'] == 0
      - trace.exists(e, e.type == 'call.start' && e.interface == 'gossiper.syn' && e.instance == 'n1')
`)
	res := passes(t, doc, sim.Request{Scenario: "rounds"})
	if _, ok := res.Summary.State["gossiper"]; ok {
		t.Errorf("a grouped component has no unnamed state: %v", res.Summary.State)
	}
	res = run(t, doc, sim.Request{Flow: "bad", Topology: map[string][]string{"node": {"n1", "n2"}}})
	eq(t, "unknown instance", res.Summary.Result.Value, "unknown_instance")
	res = run(t, doc, sim.Request{Flow: "default", Topology: map[string][]string{"node": {"n1", "n2"}}})
	if w := res.Summary.Warnings; len(w) != 1 || !strings.Contains(w[0], "first of the 2 instances of node") {
		t.Errorf("warnings %v", w)
	}
	eq(t, "default instance", res.Summary.CallsByInstance, map[string]int{"gossiper.syn@n1": 1})
}

// TestMocks: a mock replaces matching calls, is marked in the trace and
// counted in the summary.
func TestMocks(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: client}
  - {id: svc}
  - {id: dep}
interfaces:
  - component: svc
    name: main
    latency_ms: 0
    behavior:
      - {call: dep.lookup, input: {id: 1}, as: one}
      - {call: dep.lookup, input: {id: 2}, as: two}
      - {call: dep.lookup, input: {id: 2}, as: three, on_error: continue}
      - return: ["= vars.one.value", "= vars.two.value", "= vars.three.error.code"]
  - component: dep
    name: lookup
    latency_ms: 3
    behavior: [{return: real}]
flows:
  - {id: main, entry: {caller: client, interface: svc.main}}
scenarios:
  - id: mocked
    flow: main
    mocks:
      - {interface: dep.lookup, when: "input.id == 2", return: "= 'mock-' + string(input.id)", calls: [1]}
      - {interface: dep.lookup, when: "input.id == 2", fail: {code: gone, status: 410}}
    expect: ["result.value == ['real', 'mock-2', 'gone']", "duration_ms == 9", "trace.filter(e, e.mock).size() == 2"]
`)
	res := passes(t, doc, sim.Request{Scenario: "mocked"})
	eq(t, "mocks", res.Summary.Mocks, 2)
}

// TestHelpersAndExecuted: CEL helpers, executed step paths and IntOrExpr
// templates.
func TestHelpersAndExecuted(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: client}
  - {id: svc}
interfaces:
  - component: svc
    name: main
    latency_ms: 0
    behavior:
      - if: "true"
        then:
          - set:
              vars.sum: "= sum([1, 2, 3])"
              vars.fsum: "= sum([1.5, 2])"
              vars.merged: "= merge({'a': {'x': 1, 'y': 2}, 'b': 1}, {'a': {'y': 3}})"
              vars.omitted: "= omit({'a': 1, 'b': 2, 'c': 3}, 'a', 'c')"
              vars.tm: "= {'a': 1, 'b': 2}.transformMap(k, v, v * 10)"
              vars.tl: "= [5, 6].transformList(i, v, i + v)"
              vars.all2: "= {'a': 1, 'b': 2}.all(k, v, v > 0)"
              vars.r: "= [random(10), random(10), random(10)]"
        else:
          - {return: never}
      - {wait: 1, when: "false"}
      - choice: path
        options:
          left: [{return: "= vars"}]
flows:
  - {id: main, entry: {caller: client, interface: svc.main}}
`)
	res := run(t, doc, sim.Request{Flow: "main"})
	v, _ := okValue(t, res).(map[string]any)
	eq(t, "sum", v["sum"], int64(6))
	eq(t, "fsum", v["fsum"], 3.5)
	eq(t, "merge", v["merged"], map[string]any{"a": map[string]any{"x": int64(1), "y": int64(3)}, "b": int64(1)})
	eq(t, "omit", v["omitted"], map[string]any{"b": int64(2)})
	eq(t, "transformMap", v["tm"], map[string]any{"a": int64(10), "b": int64(20)})
	eq(t, "transformList", v["tl"], []any{int64(5), int64(7)})
	eq(t, "all two vars", v["all2"], true)
	again := run(t, doc, sim.Request{Flow: "main"})
	eq(t, "random is seeded", okValue(t, again).(map[string]any)["r"], v["r"])
	other := run(t, doc, sim.Request{Flow: "main", Seed: ptr(int64(99))})
	if jsonEq(okValue(t, other).(map[string]any)["r"], v["r"]) {
		t.Logf("random draws match across seeds (possible, unlikely)")
	}
	eq(t, "executed", res.Summary.Executed, []string{"svc.main:behavior[0]", "svc.main:behavior[0].then[0]",
		"svc.main:behavior[2]", "svc.main:behavior[2].options.left[0]"})
}

func ptr[T any](v T) *T { return &v }

// TestDeterministicResults: the same request gives byte-identical results,
// including comprehensions over maps.
func TestDeterministicResults(t *testing.T) {
	doc := langDoc(t, writeReadDoc+`
  - id: map-order
    flow: write
    state: {"memtable@n1": {rows: {z: 1, a: 2, m: 3, b: 4, y: 5, c: 6, x: 7, d: 8}}}
    fixtures: [three-nodes]
    expect: ["state['memtable@n1'].rows.map(k, k) == ['a', 'b', 'c', 'd', 'k1', 'm', 'x', 'y', 'z']"]
`)
	var first []byte
	for i := 0; i < 5; i++ {
		res := passes(t, doc, sim.Request{Scenario: "map-order"})
		b, _ := json.Marshal(res)
		if i == 0 {
			first = b
		} else if string(b) != string(first) {
			t.Fatalf("run %d differs", i)
		}
	}
}

func jsonEq(a, b any) bool {
	x, _ := json.Marshal(a)
	y, _ := json.Marshal(b)
	return string(x) == string(y)
}

package sim_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §13.1 item 12: additions from the Cassandra round 2 gaps.

// failFastDoc is a quorum read: three replicas contacted at once, need 2,
// and a speculative branch delayed 2500 ms by a per-branch stagger_ms
// template. n1 and n2 fail at 39 ms; n3 answers at 50 ms.
const failFastDoc = `
components:
  - {id: client}
  - {id: coord}
  - {id: replica}
interfaces:
  - component: coord
    name: read
    latency_ms: 0
    behavior:
      - parallel: "= [{'r': 'n1', 'spec': false}, {'r': 'n2', 'spec': false}, {'r': 'n3', 'spec': false}, {'r': 'n3', 'spec': true}]"
        as: it
        stagger_ms: "= vars.it.spec ? 2500 : 0"
        JOIN
        as_result: join
        on_insufficient: {code: read-failure, status: 500}
        steps:
          - {call: replica.read, on: "= vars.it.r", input: {spec: "= vars.it.spec"}}
      - {return: "= vars.join"}
  - component: replica
    name: read
    latency_ms: "= self == 'n3' ? 50 : 39"
    behavior:
      - if: "self != 'n3'"
        then: [{fail: {code: tombstone-overwhelming}}]
      - {return: {from: "= self"}}
flows:
  - {id: read, entry: {caller: client, interface: coord.read}}
scenarios:
  - id: fail-fast
    flow: read
    topology: {replica: [n1, n2, n3]}
    expect:
      - "!result.ok"
      - result.error.code == 'read-failure'
      - "result.error.data == {'received': 0, 'required': 2, 'failed': 2}"
      - duration_ms == 39
      - "trace.exists(e, e.type == 'parallel.end' && e.output.results.map(r, r.started) == [true, true, true, false])"
      - "trace.exists(e, e.type == 'parallel.end' && e.output.results[2].late && e.output.results[2].end_ms == 50)"
      - calls['replica.read'] == 3
  - id: default-waits
    flow: read
    topology: {replica: [n1, n2, n3]}
    expect:
      - result.ok
      - duration_ms == 2550
      - result.value.received == 2 && result.value.failed == 2
      - result.value.results[3].start_ms == 2500
      - calls['replica.read'] == 4
`

func TestFailFastJoin(t *testing.T) {
	for _, c := range []struct {
		scenario, value string
	}{{"fail-fast", "false"}, {"default-waits", ""}} {
		t.Run(c.scenario, func(t *testing.T) {
			repl := "join: {need: 2}"
			if c.value != "" {
				repl = "join: {need: 2, count_unstarted: " + c.value + "}"
			}
			doc := langDoc(t, strings.Replace(failFastDoc, "JOIN", repl, 1))
			passes(t, doc, sim.Request{Scenario: c.scenario})
		})
	}
}

// TestFailFastStartsDueBranches: a join that becomes impossible at a
// branch's due time counted that branch as running, so it starts; a join
// with too few branches due at the start fails at once.
func TestFailFastAtStart(t *testing.T) {
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
      - parallel: [a, b]
        stagger_ms: 100
        join: {need: 2, count_unstarted: false}
        as_result: join
        steps:
          - {call: replica.read}
      - {return: "= vars.join"}
  - {component: replica, name: read, latency_ms: 10}
flows:
  - {id: read, entry: {caller: client, interface: coord.read}}
scenarios:
  - id: at-start
    flow: read
    expect:
      - "!result.ok"
      - result.error.code == 'insufficient'
      - duration_ms == 0
      - "trace.exists(e, e.type == 'parallel.end' && e.output.results.map(r, r.started) == [true, false])"
`)
	passes(t, doc, sim.Request{Scenario: "at-start"})
}

const onLateDoc = `
components:
  - {id: client}
  - {id: coord, state: {initial: {late: []}}}
  - {id: replica}
interfaces:
  - component: coord
    name: write
    latency_ms: 0
    behavior:
      - parallel: [n1, n2, n3]
        as: replica
        join: {need: 1}
        as_result: acks
        steps:
          - {call: replica.apply, on: "= vars.replica"}
        on_late:
          - set: {state.late: "= state.late + [{'replica': vars.replica, 'index': vars.index, 'ok': vars.late.ok, 'start': vars.late.start_ms, 'end': vars.late.end_ms, 'now': now, 'code': vars.late.error == null ? '' : vars.late.error.code}]"}
          - {call: replica.cleanup, on: "= vars.replica"}
      - {wait: 100}
      - {return: {received: "= vars.acks.received"}}
  - component: replica
    name: apply
    latency_ms: "= self == 'n1' ? 10 : (self == 'n2' ? 20 : 30)"
    behavior:
      - if: "self == 'n3'"
        then: [{fail: {code: down}}]
  - {component: replica, name: cleanup, latency_ms: 1}
flows:
  - {id: write, entry: {caller: client, interface: coord.write}}
scenarios:
  - id: late
    flow: write
    topology: {replica: [n1, n2, n3]}
    expect:
      - result.ok
      - duration_ms == 110
      - "state.coord.late == [{'replica': 'n2', 'index': 1, 'ok': true, 'start': 0, 'end': 20, 'now': 20, 'code': ''}, {'replica': 'n3', 'index': 2, 'ok': false, 'start': 0, 'end': 30, 'now': 30, 'code': 'down'}]"
      - "trace.filter(e, e.type == 'call.start' && e.interface == 'replica.cleanup').map(e, [e.t, e.late, e.instance, e.branch]) == [[20, true, 'n2', 1], [30, true, 'n3', 2]]"
      - calls['replica.cleanup'] == 2
`

func TestOnLate(t *testing.T) {
	doc := langDoc(t, onLateDoc)
	res := passes(t, doc, sim.Request{Scenario: "late"})
	again := run(t, doc, sim.Request{Scenario: "late"})
	a, _ := json.Marshal(res)
	b, _ := json.Marshal(again)
	if string(a) != string(b) {
		t.Error("two runs differ")
	}
	// Every event of the on_late work is marked late, and the work's
	// executed paths are recorded.
	for _, e := range res.Trace {
		if e.Interface == "replica.cleanup" && !e.Late {
			t.Errorf("event %d (%s) not late", e.Seq, e.Type)
		}
	}
	found := false
	for _, p := range res.Summary.Executed {
		if p == "coord.write:behavior[0].on_late[1]" {
			found = true
		}
	}
	if !found {
		t.Errorf("executed %v lacks the on_late steps", res.Summary.Executed)
	}
}

func TestPastAtMSWarning(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: user}
  - {id: svc}
interfaces:
  - {component: svc, name: slow, latency_ms: 500}
flows:
  - {id: slow, entry: {caller: user, interface: svc.slow}}
scenarios:
  - id: past
    steps:
      - {flow: slow}
      - {flow: slow}
      - {flow: slow, at_ms: 100, as: third}
    expect: ["steps.third.start_ms == 500", "duration_ms == 1000"]
  - id: overlap
    steps:
      - {flow: slow}
      - {flow: slow, at_ms: 100, as: second}
    expect: ["steps.second.start_ms == 100", "duration_ms == 600"]
`)
	// The driver reaches the third step only once the second has started
	// (after the first ended, since it has no at_ms), past the third's
	// at_ms.
	res := passes(t, doc, sim.Request{Scenario: "past"})
	eq(t, "warnings", res.Summary.Warnings, []string{"step third: at_ms 100 is before the previous step ended (500); started at 500"})
	// An at_ms step starts on time even while the previous step runs, in
	// every run (§17 item 9).
	res = passes(t, doc, sim.Request{Scenario: "overlap"})
	eq(t, "warnings", len(res.Summary.Warnings), 0)
}

// TestNullDeletes: a null in state or config overrides deletes a key that
// the earlier layers or the initial state set, across fixtures, the
// scenario and the request; inside a map the override introduces, a null
// stays a value (a row may hold null fields, as before).
func TestNullDeletes(t *testing.T) {
	doc := langDoc(t, `
configs:
  - {id: a, type: integer, value: 1}
  - {id: b, type: object, value: {x: 1, y: 2}}
  - {id: c, type: integer, value: 3}
components:
  - {id: user}
  - {id: svc, state: {initial: {keep: 1, drop: 2, nested: {p: 1, q: 2}, gone: 0}}}
  - {id: node}
interfaces:
  - {component: svc, name: get, latency_ms: 0, behavior: [{return: "= state"}]}
flows:
  - {id: get, entry: {caller: user, interface: svc.get}}
fixtures:
  - id: base
    config: {b: {y: null}}
    state: {svc: {drop: null, added: {z: 1}}, "node@n1": {v: 1, w: 2}}
  - id: readd
    config: {c: 4}
    state: {svc: {added: null}}
scenarios:
  - id: deletes
    flow: get
    fixtures: [base, readd]
    topology: {node: [n1, n2]}
    config: {a: null}
    state: {svc: {nested: {q: null}, gone: null, fresh: {v: null}}, "node@n1": {w: null}}
    expect:
      - "!('a' in config)"
      - "config.b == {'x': 1}"
      - "config.c == 4"
      - "state.svc == {'keep': 1, 'nested': {'p': 1}, 'fresh': {'v': null}}"
      - "result.value == state.svc"
      - "state['node@n1'] == {'v': 1}"
`)
	res := passes(t, doc, sim.Request{Scenario: "deletes"})
	if _, ok := res.Request.Config["a"]; !ok || res.Request.Config["a"] != nil {
		t.Errorf("effective config %v should echo the deletion of a", res.Request.Config)
	}
	// A request's own nulls delete too, after its fixtures.
	passes(t, doc, sim.Request{Flow: "get", Fixtures: []string{"base", "readd"}, State: map[string]map[string]any{"svc": {"keep": nil}},
		Config: map[string]any{"c": nil}, Expect: []string{"state.svc == {'nested': {'p': 1, 'q': 2}, 'gone': 0}", "!('c' in config)", "config.b == {'x': 1}"}})
	// A null for a whole state key drops the earlier overrides: the
	// initial state applies.
	passes(t, doc, sim.Request{Flow: "get", Fixtures: []string{"base"}, State: map[string]map[string]any{"svc": nil},
		Expect: []string{"state.svc == {'keep': 1, 'drop': 2, 'nested': {'p': 1, 'q': 2}, 'gone': 0}"}})
}

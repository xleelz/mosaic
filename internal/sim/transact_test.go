package sim_test

import (
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §13.1 item 25: conditional writes, transactions and
// crash-after-effect faults.
const storeFaultDoc = `
components:
  - {id: client}
  - {id: api}
  - id: db
    state: {initial: {config: {main: {v: 1, body: old}}, accounts: {a: {bal: 10}, b: {bal: 0}}}}
interfaces:
  - component: db
    name: create
    latency_ms: 0
    store: {table: config, op: put, key: "= input.id", value: "= input", if_absent: true}
  - component: db
    name: cas
    latency_ms: 0
    errors: [{code: stale, status: 409}]
    store: {table: config, op: update, key: "= input.id", value: {v: "= input.v + 1", body: "= input.body"}, if: "row.v == input.v", conflict: stale}
  - component: db
    name: transfer
    latency_ms: 1
    behavior:
      - transact:
          - {table: accounts, op: update, key: "= input.from", value: {bal: "= state.accounts[input.from].bal - input.amt"}, if: "row.bal >= input.amt"}
          - {table: accounts, op: incr, key: "= input.to", value: {bal: "= input.amt"}}
          - {table: ledger, op: put, key: "= input.id", value: "= input", if_absent: true}
        as: tx
      - {return: "= vars.tx"}
  - component: db
    name: record
    latency_ms: 1
    behavior:
      - {set: {state.log: "= (has(state.log) ? state.log : []) + [input.id]"}}
      - {set: {state.done: true}}
      - {return: {ok: true}}
  - component: api
    name: start
    latency_ms: 0
    behavior:
      - {call: db.record, input: {id: x}, timeout_ms: 50, retry: {max_attempts: 3, backoff_ms: 10}, as: r}
      - {return: "= vars.r"}
  - component: api
    name: once
    latency_ms: 0
    behavior:
      - {call: db.create, input: {id: n1, v: 1}, retry: {max_attempts: 3, backoff_ms: 10}, as: r, on_error: continue}
      - {return: "= vars.r"}
flows:
  - {id: create, entry: {caller: client, interface: db.create, input: {id: main, v: 9}}}
  - {id: create-new, entry: {caller: client, interface: db.create, input: {id: other, v: 1}}}
  - {id: cas-ok, entry: {caller: client, interface: db.cas, input: {id: main, v: 1, body: new}}}
  - {id: cas-stale, entry: {caller: client, interface: db.cas, input: {id: main, v: 0, body: new}}}
  - {id: transfer, entry: {caller: client, interface: db.transfer, input: {id: t1, from: a, to: b, amt: 4}}}
  - {id: overdraw, entry: {caller: client, interface: db.transfer, input: {id: t2, from: a, to: b, amt: 40}}}
  - {id: start, entry: {caller: client, interface: api.start}}
  - {id: once, entry: {caller: client, interface: api.once}}
scenarios:
  - id: if-absent-fails
    flow: create
    expect:
      - "result.error.code == 'condition_failed' && result.error.status == 412"
      - "state.db.config.main.v == 1"
  - id: if-absent-writes
    flow: create-new
    expect: ["state.db.config.other.v == 1"]
  - id: cas-ok
    flow: cas-ok
    expect: ["state.db.config.main == {'v': 2, 'body': 'new'}"]
  - id: cas-stale
    flow: cas-stale
    expect:
      - "result.error.code == 'stale' && result.error.status == 409"
      - "state.db.config.main.body == 'old'"
  - id: transfer
    flow: transfer
    expect:
      - "state.db.accounts.a.bal == 6 && state.db.accounts.b.bal == 4 && state.db.ledger.t1.amt == 4"
      - "result.value.ok && size(result.value.value) == 3"
  - id: overdraw
    flow: overdraw
    expect:
      - "result.error.code == 'condition_failed' && result.error.data.index == 0"
      - "state.db.accounts.a.bal == 10 && state.db.accounts.b.bal == 0 && !has(state.db.ledger)"
  - id: ledger-replay
    flow: transfer
    state: {db: {ledger: {t1: {id: t1}}}}
    expect:
      - "result.error.code == 'condition_failed' && result.error.data.index == 2"
      - "state.db.accounts.a.bal == 10 && state.db.accounts.b.bal == 0"
  - id: lost-reply-timeout
    flow: start
    faults: [{target: db.record, type: lost_reply, calls: [1]}]
    expect:
      - "result.value.ok && result.value.attempts == 2"
      - "state.db.log == ['x', 'x']"
      - "calls['db.record'] == 2"
      - "duration_ms == 50 + 10 + 1"
  - id: lost-reply-code
    flow: start
    faults: [{target: db.record, type: lost_reply, code: reset, calls: [1, 2, 3]}]
    expect:
      - "result.error.code == 'reset'"
      - "state.db.log == ['x', 'x', 'x']"
      - "duration_ms == 3 + 20"
  - id: crash-midway
    flow: start
    faults: [{target: db.record, type: crash, after_steps: 1, calls: [1]}]
    expect:
      - "result.value.ok && result.value.attempts == 2"
      - "state.db.log == ['x', 'x'] && state.db.done"
  - id: crash-before
    flow: start
    faults: [{target: db.record, type: crash, after_steps: 0, calls: [1]}]
    expect: ["state.db.log == ['x']"]
  - id: crash-store-after
    flow: once
    faults: [{target: db.create, type: crash, after_steps: 1, calls: [1]}]
    expect:
      - "!result.value.ok && result.value.attempts == 2"
      - "result.value.error.code == 'condition_failed'"
      - "state.db.config.n1.v == 1"
  - id: crash-store-before
    flow: once
    faults: [{target: db.create, type: crash, after_steps: 0, calls: [1]}]
    expect: ["result.value.ok && result.value.attempts == 2 && state.db.config.n1.v == 1"]
`

func TestStoreConditionsAndTransact(t *testing.T) {
	doc := langDoc(t, storeFaultDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			res := passes(t, doc, sim.Request{Scenario: sc.ID})
			if sc.ID == "overdraw" {
				for _, e := range res.Trace {
					if e.Type == "set" {
						t.Errorf("a canceled transaction wrote %s", e.Path)
					}
				}
			}
		})
	}
}

func TestStoreFaultValidation(t *testing.T) {
	bad := map[string]string{
		"if_absent goes with put": `
components: [{id: db}]
interfaces:
  - {component: db, name: u, store: {table: t, op: update, key: k, value: {}, if_absent: true}}`,
		"if goes with put": `
components: [{id: db}]
interfaces:
  - {component: db, name: g, store: {table: t, op: get, key: k, if: "row == null"}}`,
		"a transact write is one of": `
components: [{id: db}]
interfaces:
  - {component: db, name: g, behavior: [{transact: [{table: t, op: get, key: k}]}]}`,
		"not one of db.g's declared errors": `
components: [{id: db}]
interfaces:
  - {component: db, name: g, behavior: [{transact: [{table: t, op: put, key: k, value: 1, if_absent: true, conflict: nope}]}]}`,
		"a crash fault needs after_steps": `
components: [{id: db}]
interfaces: [{component: db, name: g}]
flows: [{id: f, entry: {caller: db, interface: db.g}}]
scenarios: [{id: s, flow: f, faults: [{target: db.g, type: crash}]}]`,
		"after_steps goes with a crash fault": `
components: [{id: db}]
interfaces: [{component: db, name: g}]
flows: [{id: f, entry: {caller: db, interface: db.g}}]
scenarios: [{id: s, flow: f, faults: [{target: db.g, type: lost_reply, after_steps: 1}]}]`,
	}
	for want, src := range bad {
		doc, err := model.ParseDocument([]byte("schema_version: 1\n" + src))
		if err != nil {
			t.Fatal(err)
		}
		found := false
		for _, is := range model.Validate(doc) {
			if is.Severity == model.SeverityError && strings.Contains(is.Message, want) {
				found = true
			}
		}
		if !found {
			t.Errorf("no error containing %q; got %+v", want, model.Validate(doc))
		}
	}
}

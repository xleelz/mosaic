package sim_test

import (
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §13.1 item 35: run caps, response headers, fault match and
// caller, hang forever, sessions and retry on status.
const item35Doc = `
components:
  - {id: client}
  - {id: api}
  - {id: db, state: {initial: {n: 0}}}
  - {id: tunnel}
schemas:
  - id: limited
    schema:
      type: object
      properties:
        status: {type: integer}
        headers: {type: object, properties: {retry-after: {type: string}}}
interfaces:
  - {component: db, name: read, latency_ms: 1, behavior: [{return: {count: "= input.count"}}]}
  - component: db
    name: flaky
    latency_ms: 1
    behavior:
      - {set: {state.n: "= state.n + 1"}}
      - {if: "state.n < 3", then: [{fail: {code: busy, status: 503, retryable: false}}]}
      - {return: {n: "= state.n"}}
  - component: api
    name: embed
    latency_ms: 0
    behavior:
      - {call: db.read, input: {count: "= input.count"}, as: r, on_error: continue}
      - {return: "= vars.r"}
  - component: api
    name: recharge
    latency_ms: 0
    behavior:
      - {call: db.read, input: {count: 0}, as: r, on_error: continue}
      - {return: "= vars.r"}
  - component: api
    name: bounded
    latency_ms: 0
    behavior:
      - {call: db.read, input: {count: 1}, timeout_ms: 100, as: r, on_error: continue}
      - {return: "= vars.r"}
  - component: api
    name: limited
    response: limited
    latency_ms: 0
    behavior:
      - return: {status: 429, headers: {Retry-After: "30", x-req: a}}
  - component: api
    name: refuse
    latency_ms: 0
    errors: [{code: rate_limited, status: 429}]
    behavior:
      - fail: {code: rate_limited, status: 429, headers: {Retry-After: "5"}}
  - component: api
    name: retry-status
    latency_ms: 0
    behavior:
      - {call: db.flaky, retry: {max_attempts: 3, on_status: [429, 503]}, as: r, on_error: continue}
      - {return: "= vars.r"}
  - component: api
    name: retry-codes
    latency_ms: 0
    behavior:
      - {call: db.flaky, retry: {max_attempts: 3, on_codes: [busy]}, as: r, on_error: continue}
      - {return: "= vars.r"}
  - component: api
    name: retry-plain
    latency_ms: 0
    behavior:
      - {call: db.flaky, retry: {max_attempts: 3}, as: r, on_error: continue}
      - {return: "= vars.r"}
  - {component: tunnel, name: stream, latency_ms: 1000, behavior: [{return: {done: true}}]}
  - component: api
    name: open
    latency_ms: 0
    behavior:
      - {call: tunnel.stream, session: "= input.sid", as: r, on_error: continue}
      - {return: "= vars.r"}
  - component: api
    name: drop
    latency_ms: 0
    behavior:
      - close: {session: "= input.sid"}
      - {return: {closed: "= input.sid"}}
  - component: api
    name: busy
    latency_ms: 0
    behavior:
      - {foreach: "= [1, 2, 3, 4, 5, 6, 7, 8]", steps: [{set: {vars.x: "= vars.item"}}]}
flows:
  - {id: embed-big, entry: {caller: client, interface: api.embed, input: {count: 1025}}}
  - {id: embed-small, entry: {caller: client, interface: api.embed, input: {count: 3}}}
  - {id: recharge, entry: {caller: client, interface: api.recharge}}
  - {id: bounded, entry: {caller: client, interface: api.bounded}}
  - {id: read, entry: {caller: client, interface: db.read, input: {count: 1}}}
  - {id: limited, entry: {caller: client, interface: api.limited}}
  - {id: refuse, entry: {caller: client, interface: api.refuse}}
  - {id: retry-status, entry: {caller: client, interface: api.retry-status}}
  - {id: retry-codes, entry: {caller: client, interface: api.retry-codes}}
  - {id: retry-plain, entry: {caller: client, interface: api.retry-plain}}
  - {id: busy, entry: {caller: client, interface: api.busy}}
scenarios:
  - id: match-big
    flow: embed-big
    faults: [{target: db.read, type: error, code: too_many, status: 400, match: "input.count > 1024"}]
    expect: ["result.value.error.code == 'too_many' && faults == 1"]
  - id: match-small
    flow: embed-small
    faults: [{target: db.read, type: error, code: too_many, status: 400, match: "input.count > 1024"}]
    expect: ["result.value.ok && faults == 0"]
  - id: caller-hit
    flow: recharge
    faults: [{target: db.read, type: unavailable, caller: "api.re*"}]
    expect: ["result.value.error.code == 'unavailable'"]
  - id: caller-miss
    flow: embed-small
    faults: [{target: db.read, type: unavailable, caller: api.recharge}]
    expect: ["result.value.ok && faults == 0"]
  - id: caller-entry
    flow: read
    faults: [{target: db.read, type: unavailable, caller: client}]
    expect: ["result.error.code == 'unavailable'"]
  - id: match-calls-count-matches
    steps:
      - {interface: api.embed, caller: client, input: {count: 1}, as: a}
      - {interface: api.embed, caller: client, input: {count: 2000}, as: b}
      - {interface: api.embed, caller: client, input: {count: 3000}, as: c}
    faults: [{target: db.read, type: error, code: too_many, match: "input.count > 1024", calls: [2]}]
    expect:
      - "steps.a.result.value.ok && steps.b.result.value.ok"
      - "steps.c.result.value.error.code == 'too_many'"
  - id: hang-timeout
    flow: bounded
    faults: [{target: db.read, type: hang, forever: true}]
    expect: ["result.value.error.code == 'timeout' && duration_ms == 100"]
  - id: hang-forever-entry
    flow: read
    faults: [{target: db.read, type: hang, forever: true}]
  - id: hang-forever-steps
    steps:
      - {flow: read, as: a}
      - {flow: embed-small, as: b}
    faults: [{target: db.read, type: timeout, forever: true, calls: [1]}]
    expect:
      - "steps.a.status == 'pending' && !steps.a.result.ok && steps.a.result.error == null"
      - "steps.b.result.ok && steps.b.result.value.ok"
  - id: hang-forever-killed
    steps:
      - {flow: read, as: a}
    faults:
      - {target: db.read, type: hang, forever: true}
      - {target: db, type: kill, at_ms: 50}
    expect: ["steps.a.result.error.code == 'peer-killed'"]
  - id: limited-headers
    flow: limited
    expect:
      - "result.value.headers['retry-after'] == '30' && result.value.headers['Retry-After'] == '30'"
      - "result.value.headers['x-req'] == 'a'"
  - id: refuse-headers
    flow: refuse
    expect:
      - "result.error.code == 'rate_limited' && result.error.headers['retry-after'] == '5'"
      - "result.value.headers['retry-after'] == '5'"
  - id: retry-status
    flow: retry-status
    expect: ["result.value.ok && result.value.attempts == 3 && retries == 2"]
  - id: retry-codes
    flow: retry-codes
    expect: ["result.value.ok && result.value.attempts == 3"]
  - id: retry-plain
    flow: retry-plain
    expect: ["!result.value.ok && result.value.attempts == 1 && retries == 0"]
  - id: session-close
    steps:
      - {interface: api.open, caller: client, input: {sid: s1}, as: o1, await: false}
      - {interface: api.open, caller: client, input: {sid: s2}, as: o2, await: false}
      - {interface: api.drop, caller: client, input: {sid: s1}, at_ms: 100, as: d}
      - {interface: api.open, caller: client, input: {sid: s1}, as: o3}
    expect:
      - "steps.o1.result.value.error.code == 'canceled' && steps.o1.duration_ms == 100"
      - "steps.o2.result.value.ok"
      - "steps.o3.result.value.ok"
      - "trace.exists(e, e.type == 'close' && e.key == 's1' && e.output.pending == 1)"
  - id: session-close-hung
    steps:
      - {interface: api.open, caller: client, input: {sid: s1}, as: o1, await: false}
      - {interface: api.drop, caller: client, input: {sid: s1}, at_ms: 100, as: d}
    faults: [{target: tunnel.stream, type: hang, forever: true}]
    expect: ["steps.o1.result.value.error.code == 'canceled' && steps.o1.duration_ms == 100"]
  - id: events-capped
    flow: busy
    max_events: 5
  - id: time-capped
    flow: bounded
    max_virtual_ms: 50
`

func TestItem35Scenarios(t *testing.T) {
	doc := langDoc(t, item35Doc)
	for _, sc := range doc.Scenarios {
		switch sc.ID {
		case "hang-forever-entry", "events-capped", "time-capped":
			continue
		}
		t.Run(sc.ID, func(t *testing.T) { passes(t, doc, sim.Request{Scenario: sc.ID}) })
	}
}

func TestHangForeverReportsPending(t *testing.T) {
	doc := langDoc(t, item35Doc)
	res := run(t, doc, sim.Request{Scenario: "hang-forever-entry"})
	s := res.Summary
	if s.Status != "pending" || s.Result.OK || s.Result.Error != nil {
		t.Fatalf("status %s, result %+v", s.Status, s.Result)
	}
	if len(s.Pending) != 1 || s.Pending[0].Interface != "db.read" || s.Pending[0].Fault != "hang" || s.Pending[0].From != "client" {
		t.Errorf("pending %+v", s.Pending)
	}
	for _, e := range res.Trace {
		if e.Type == "call.end" || e.Type == "timeout" {
			t.Errorf("a call that never answered recorded %s", e.Type)
		}
	}
	if len(s.Warnings) != 1 || !strings.Contains(s.Warnings[0], "never answered") {
		t.Errorf("warnings %q", s.Warnings)
	}
	// The pending step of a multi-step scenario.
	res = run(t, doc, sim.Request{Scenario: "hang-forever-steps"})
	if len(res.Summary.Pending) != 1 || res.Summary.Steps[0].Status != "pending" || res.Summary.Status != "ok" {
		t.Errorf("steps: status %s, pending %+v, steps %+v", res.Summary.Status, res.Summary.Pending, res.Summary.Steps)
	}
	// A caller that gave up through a closed session leaves nothing pending.
	res = passes(t, doc, sim.Request{Scenario: "session-close-hung"})
	if len(res.Summary.Pending) != 0 || len(res.Summary.Warnings) != 0 {
		t.Errorf("closed: pending %+v, warnings %q", res.Summary.Pending, res.Summary.Warnings)
	}
	// Killed: nothing is pending.
	res = run(t, doc, sim.Request{Scenario: "hang-forever-killed"})
	if len(res.Summary.Pending) != 0 {
		t.Errorf("killed: pending %+v", res.Summary.Pending)
	}
}

func TestRunCaps(t *testing.T) {
	doc := langDoc(t, item35Doc)
	res := run(t, doc, sim.Request{Scenario: "events-capped"})
	s := res.Summary
	if s.Status != "aborted" || s.Abort != "event budget of 5 exceeded" || len(res.Trace) != 5 {
		t.Fatalf("status %s, abort %q, %d events", s.Status, s.Abort, len(res.Trace))
	}
	if s.Caps == nil || s.Caps.Hit != "max_events" || s.Caps.MaxEvents != 5 || s.Caps.MaxVirtualMS != nil {
		t.Errorf("caps %+v", s.Caps)
	}
	res = run(t, doc, sim.Request{Scenario: "time-capped", Faults: []model.Fault{{Target: "db.read", Type: "hang", Forever: true}}})
	s = res.Summary
	if s.Caps == nil || s.Caps.Hit != "max_virtual_ms" || s.Caps.MaxEvents != model.DefaultMaxEvents || s.Caps.MaxVirtualMS == nil || *s.Caps.MaxVirtualMS != 50 {
		t.Errorf("time caps %+v (warnings %q)", s.Caps, s.Warnings)
	}
	// A run that hits no cap reports none.
	res = run(t, doc, sim.Request{Flow: "busy"})
	if res.Summary.Caps != nil || res.Summary.Status != "ok" {
		t.Errorf("uncapped: %+v", res.Summary.Caps)
	}
}

func TestResponseHeadersInTrace(t *testing.T) {
	doc := langDoc(t, item35Doc)
	for id, want := range map[string]string{"limited-headers": "30", "refuse-headers": "5"} {
		res := passes(t, doc, sim.Request{Scenario: id})
		found := false
		for _, e := range res.Trace {
			if e.Type == "call.end" && e.Interface != "" && e.Headers != nil {
				if e.Headers["retry-after"] != want || e.Headers["Retry-After"] != nil {
					t.Errorf("%s: call.end headers %v", id, e.Headers)
				}
				found = true
			}
		}
		if !found {
			t.Errorf("%s: no call.end carries headers", id)
		}
	}
	// A call without headers carries none.
	res := passes(t, doc, sim.Request{Scenario: "retry-plain"})
	for _, e := range res.Trace {
		if e.Headers != nil {
			t.Errorf("unexpected headers on %s", e.Type)
		}
	}
}

func TestItem35Validation(t *testing.T) {
	base := `
components: [{id: c}, {id: db}]
schemas:
  - id: resp
    schema: {type: object, properties: {headers: {type: object, properties: {retry-after: {type: string}}}}}
interfaces:
  - {component: db, name: g, response: resp}
  - {component: db, name: h}
flows: [{id: f, entry: {caller: c, interface: db.g}}]
`
	cases := []struct{ src, want, sev string }{
		{"scenarios: [{id: s, flow: f, max_events: 0}]", "max_events must be between 1 and 1000000", model.SeverityError},
		{"scenarios: [{id: s, flow: f, max_events: 1000001}]", "max_events must be between", model.SeverityError},
		{"scenarios: [{id: s, flow: f, faults: [{target: db.g, type: error, code: x, match: 'input.'}]}]", "invalid expression", model.SeverityError},
		{"scenarios: [{id: s, flow: f, faults: [{target: db.g, type: error, code: x, caller: '[bad'}]}]", "caller is an interface id or a glob", model.SeverityError},
		{"scenarios: [{id: s, flow: f, faults: [{target: db.g, type: error, code: x, caller: nobody}]}]", "no interface or component", model.SeverityWarning},
		{"scenarios: [{id: s, flow: f, faults: [{target: db.g, type: error, code: x, forever: true}]}]", "forever goes with a hang", model.SeverityError},
		{"scenarios: [{id: s, flow: f, faults: [{target: db, type: kill, at_ms: 1, match: 'true'}]}]", "match and caller do not go with a kill fault", model.SeverityError},
		{"scenarios: [{id: s, flow: f, expect: [\"result.value.headers['x-nope'] == '1'\"]}]", `reads header "x-nope"`, model.SeverityWarning},
		{"scenarios: [{id: s, steps: [{interface: db.g, caller: c, as: a}], expect: [\"steps.a.result.value.headers.etag == '1'\"]}]", `reads header "etag"`, model.SeverityWarning},
	}
	extra := map[string]string{
		"session goes with call":          "  - {component: db, name: x, behavior: [{wait: 1, session: s}]}",
		"a session needs a key":           "  - {component: db, name: x, behavior: [{close: {session: ''}}]}",
		"session does not go with stream": "  - {component: db, name: x, behavior: [{call: db.h, stream: true, session: s}]}",
		"a status is between 100 and 599": "  - {component: db, name: x, behavior: [{call: db.h, retry: {max_attempts: 2, on_status: [42]}}]}",
	}
	type doc struct{ src, want, sev string }
	var docs []doc
	for _, c := range cases {
		docs = append(docs, doc{base + c.src, c.want, c.sev})
	}
	for want, iface := range extra {
		docs = append(docs, doc{strings.Replace(base, "  - {component: db, name: h}\n", "  - {component: db, name: h}\n"+iface+"\n", 1), want, model.SeverityError})
	}
	for _, c := range docs {
		src := c.src
		doc, err := model.ParseDocument([]byte("schema_version: 1\n" + src))
		if err != nil {
			t.Fatalf("%s: %v", c.want, err)
		}
		found := false
		for _, is := range model.Validate(doc) {
			if is.Severity == c.sev && strings.Contains(is.Message, c.want) {
				found = true
			}
		}
		if !found {
			t.Errorf("no %s containing %q; got %+v", c.sev, c.want, model.Validate(doc))
		}
	}
	// A declared header, and a header of a free-form headers object, don't warn.
	for _, src := range []string{
		"scenarios: [{id: s, flow: f, expect: [\"result.value.headers['Retry-After'] == '1'\"]}]",
		"scenarios: [{id: s, steps: [{interface: db.h, caller: c, as: a}], expect: [\"steps.a.result.value.headers.etag == '1'\"]}]",
	} {
		doc, err := model.ParseDocument([]byte("schema_version: 1\n" + base + src))
		if err != nil {
			t.Fatal(err)
		}
		for _, is := range model.Validate(doc) {
			if strings.Contains(is.Message, "reads header") {
				t.Errorf("%s: %s", src, is.Message)
			}
		}
	}
}

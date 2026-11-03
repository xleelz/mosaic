package sim_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §15.3: streams on route calls, nested headers, respect_retry_after,
// removing fields in update, fault payloads, per-scenario caps, mid-run set
// steps, the JSON and hex CEL helpers and the {$bytes} and {$bigint} input
// markers.
const s153Doc = `
components:
  - {id: client}
  - {id: gw, router: {hosts: [llm.test]}}
  - {id: engine}
  - {id: db, state: {initial: {rows: {a: {x: 1, y: 2, meta: {k: 1, j: 2}}}}}}
  - id: nodes
    state: {initial: {up: false}}
schemas:
  - id: raw-req
    schema:
      type: object
      properties: {blob: {type: string}, big: {type: integer}, n: {type: integer}}
interfaces:
  - component: gw
    name: generate
    attributes: {method: POST, path: /v1/generate}
    latency_ms: 0
    behavior:
      - {yield: {data: a, headers: {Content-Type: text/event-stream}}}
      - {wait: 10}
      - {yield: {data: b}}
      - {wait: 10}
      - {return: {status: 200, headers: {X-Tokens: "2"}}}
  - component: client
    name: stream-route
    latency_ms: 0
    behavior:
      - {set: {vars.got: [], vars.ct: ""}}
      - call: {host: llm.test, method: POST, path: /v1/generate}
        stream: true
        as: r
        on_item:
          - {set: {vars.got: "= vars.got + [[vars.item.data, now]]"}}
          - {if: "has(vars.item.headers)", then: [{set: {vars.ct: "= vars.item.headers['content-type']"}}]}
      - return: {got: "= vars.got", ct: "= vars.ct", status: "= vars.r.value.status", tokens: "= vars.r.value.headers['x-tokens']", target: "= vars.r.target"}
  - component: client
    name: stream-route-early
    latency_ms: 0
    behavior:
      - call: {host: llm.test, method: POST, path: /v1/generate}
        stream: true
        on_item:
          - {return: {first: "= vars.item.data"}}
      - {return: {first: none}}
  - component: client
    name: collect-route
    latency_ms: 0
    behavior:
      - call: {host: llm.test, method: POST, path: /v1/generate}
        as: r
      - return: {n: "= size(vars.r.value.items)", tokens: "= vars.r.value.headers['x-tokens']"}
  - {component: engine, name: limited, latency_ms: 0, behavior: [{return: {ok: true}}]}
  - component: client
    name: retry-after
    latency_ms: 0
    behavior:
      - call: engine.limited
        retry: {max_attempts: 3, backoff_ms: 1, respect_retry_after: true, max_backoff_ms: 5000}
        as: r
      - return: "= vars.r"
  - component: client
    name: retry-plain
    latency_ms: 0
    behavior:
      - call: engine.limited
        retry: {max_attempts: 3, backoff_ms: 1}
        as: r
      - return: "= vars.r"
  - {component: db, name: strip, store: {table: rows, op: update, key: "= input.id", value: {y: {$absent: true}, meta: {j: {$absent: true}}, z: 3}}}
  - component: engine
    name: decode
    latency_ms: 0
    behavior:
      - {set: {vars.tokens: 0}}
      - foreach: "= lists.range(input.steps)"
        max: 1000
        steps:
          - foreach: "= lists.range(input.batch)"
            max: 1000
            steps:
              - {set: {vars.tokens: "= vars.tokens + 1"}}
      - {return: {tokens: "= vars.tokens"}}
  - component: engine
    name: cel
    latency_ms: 0
    behavior:
      - return:
          j: "= json({'b': [1, 2.5, 'x<y'], 'a': {'z': null, 'c': true}})"
          p: "= jsonParse('{\"n\": 3, \"l\": [1, \"two\"]}')"
          h: "= hex(bytes('hi'))"
          hs: "= hex('A')"
          rt: "= jsonParse(json(input))"
  - component: engine
    name: raw
    request: raw-req
    latency_ms: 0
    behavior:
      - return: {hex: "= hex(input.blob)", len: "= size(input.blob)", big: "= input.big", is_str: "= type(input.big) == string"}
  - component: nodes
    name: wait-up
    latency_ms: 0
    behavior:
      - foreach: "= lists.range(20)"
        steps:
          - {if: "state.up", then: [{return: {up_at: "= now"}}]}
          - {wait: 100}
      - {fail: {code: never_up}}
flows:
  - {id: stream-route, entry: {caller: client, interface: client.stream-route}}
  - {id: stream-route-early, entry: {caller: client, interface: client.stream-route-early}}
  - {id: collect-route, entry: {caller: client, interface: client.collect-route}}
  - {id: retry-after, entry: {caller: client, interface: client.retry-after}}
  - {id: retry-plain, entry: {caller: client, interface: client.retry-plain}}
  - {id: limited, entry: {caller: client, interface: engine.limited}}
  - {id: strip, entry: {caller: client, interface: db.strip, input: {id: a}}}
  - {id: decode, entry: {caller: client, interface: engine.decode, input: {steps: 200, batch: 60}}}
  - {id: cel, entry: {caller: client, interface: engine.cel, input: {m: {b: 1, a: [true]}}}}
  - {id: raw, entry: {caller: client, interface: engine.raw}}
scenarios:
  - id: stream-route
    flow: stream-route
    expect:
      - "result.value.got == [['a', 0], ['b', 10]]"
      - "result.value.ct == 'text/event-stream'"
      - "result.value.status == 200 && result.value.tokens == '2' && result.value.target == 'gw.generate'"
      - "trace.exists(e, e.type == 'route' && e.interface == 'gw.generate')"
      - "trace.filter(e, e.type == 'yield').size() == 2"
  - id: stream-route-early
    flow: stream-route-early
    expect: ["result.value.first == 'a'"]
  - id: collect-route
    flow: collect-route
    expect: ["result.value.n == 2 && result.value.tokens == '2'"]
  - id: retry-after-header
    flow: retry-after
    faults: [{target: engine.limited, type: error, code: rate_limited, status: 429, retryable: true, calls: [1], headers: {Retry-After: "2"}}]
    expect: ["result.value.ok && result.value.attempts == 2 && duration_ms == 2000"]
  - id: retry-after-data
    flow: retry-after
    faults: [{target: engine.limited, type: unavailable, calls: [1], data: {retry_after_ms: 750}}]
    expect: ["result.value.ok && result.value.attempts == 2 && duration_ms == 750"]
  - id: retry-after-capped
    flow: retry-after
    faults: [{target: engine.limited, type: error, code: rate_limited, status: 429, retryable: true, calls: [1], headers: {retry-after: 60}}]
    expect: ["result.value.ok && duration_ms == 5000"]
  - id: retry-after-ignored
    flow: retry-plain
    faults: [{target: engine.limited, type: error, code: rate_limited, status: 429, retryable: true, calls: [1], headers: {Retry-After: "2"}}]
    expect: ["result.value.ok && duration_ms == 1"]
  - id: fault-payload
    flow: limited
    faults: [{target: engine.limited, type: unavailable, data: {reason: draining}, headers: {X-Trace: t1}}]
    expect:
      - "result.error.code == 'unavailable' && result.error.data.reason == 'draining'"
      - "result.error.headers['x-trace'] == 't1' && result.value.headers['x-trace'] == 't1'"
  - id: strip-fields
    flow: strip
    expect:
      - "state.db.rows.a == {'x': 1, 'z': 3, 'meta': {'k': 1}}"
      - "result.value == {'x': 1, 'z': 3, 'meta': {'k': 1}}"
  - id: decode-default-cap
    flow: decode
  - id: decode-raised-cap
    flow: decode
    max_iterations: 20000
    expect: ["result.value.tokens == 12000"]
  - id: cel-tight
    flow: cel
    max_cel_cost: 2
  - id: cel-helpers
    flow: cel
    expect:
      - "result.value.j == '{\"a\":{\"c\":true,\"z\":null},\"b\":[1,2.5,\"x<y\"]}'"
      - "result.value.p == {'n': 3, 'l': [1, 'two']}"
      - "result.value.h == '6869' && result.value.hs == '41'"
      - "result.value.rt.m == {'b': 1, 'a': [true]}"
  - id: markers
    flow: raw
    input: {blob: {$bytes: "/wA="}, big: {$bigint: "123456789012345678901234567890"}}
    expect:
      - "result.value.hex == 'ff00' && result.value.len == 2"
      - "result.value.big == '123456789012345678901234567890' && result.value.is_str"
  - id: node-back
    steps:
      - {interface: nodes.wait-up, caller: client, as: w, await: false}
      - {set: {nodes: {up: true}}, at_ms: 250}
    expect:
      - "steps.w.result.value.up_at == 300"
      - "state.nodes.up"
      - "trace.exists(e, e.type == 'set' && e.component == 'nodes' && e.t == 250)"
`

func TestSim153Scenarios(t *testing.T) {
	doc := langDoc(t, s153Doc)
	for _, sc := range doc.Scenarios {
		switch sc.ID {
		case "decode-default-cap", "cel-tight":
			continue
		}
		t.Run(sc.ID, func(t *testing.T) { passes(t, doc, sim.Request{Scenario: sc.ID}) })
	}
}

// max_iterations unblocks a vLLM-style decode loop: 200 scheduler steps of
// a 60-request batch is 12,000 iterations, past the default cap of 10,000.
func TestSim153MaxIterations(t *testing.T) {
	doc := langDoc(t, s153Doc)
	res := run(t, doc, sim.Request{Scenario: "decode-default-cap"})
	if res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, "loop budget of 10000 iterations exceeded") ||
		!strings.Contains(res.Summary.Abort, "max_iterations") {
		t.Fatalf("default cap: %s %q", res.Summary.Status, res.Summary.Abort)
	}
	res = run(t, doc, sim.Request{Scenario: "decode-raised-cap"})
	if res.Summary.Status != "ok" {
		t.Fatalf("raised cap: %s %q", res.Summary.Status, res.Summary.Abort)
	}
}

func TestSim153MaxCELCost(t *testing.T) {
	doc := langDoc(t, s153Doc)
	res := run(t, doc, sim.Request{Scenario: "cel-tight"})
	if res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, "cost") {
		t.Fatalf("max_cel_cost 2: %s %q", res.Summary.Status, res.Summary.Abort)
	}
}

func TestSim153FrameHeadersInTrace(t *testing.T) {
	doc := langDoc(t, s153Doc)
	res := run(t, doc, sim.Request{Scenario: "stream-route"})
	ys := events(res, "yield")
	if len(ys) != 2 || ys[0].Headers["content-type"] != "text/event-stream" || ys[1].Headers != nil {
		t.Fatalf("yield headers: %+v", ys)
	}
}

func TestSim153BigIntJSON(t *testing.T) {
	doc := langDoc(t, s153Doc)
	res := run(t, doc, sim.Request{Scenario: "markers"})
	b, err := json.Marshal(res.Trace[0].Input)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), `"big":{"$bigint":"123456789012345678901234567890"}`) || !strings.Contains(string(b), `"blob":"/wA="`) {
		t.Errorf("entry input JSON: %s", b)
	}
	for _, w := range res.Summary.Warnings {
		if strings.Contains(w, "request") {
			t.Errorf("schema warning for marked input: %s", w)
		}
	}
}

func TestSim153Validation(t *testing.T) {
	base := "schema_version: 1\ncomponents: [{id: c}, {id: n}]\ninterfaces: [{component: c, name: g, behavior: [{return: 1}]}]\nflows: [{id: f, entry: {caller: c, interface: c.g}}]\n"
	for _, tc := range []struct{ src, want string }{
		{"scenarios: [{id: s, flow: f, max_iterations: 0}]", "max_iterations must be between 1 and 1000000"},
		{"scenarios: [{id: s, flow: f, max_iterations: 2000000}]", "max_iterations must be between"},
		{"scenarios: [{id: s, flow: f, max_cel_cost: 0}]", "max_cel_cost must be positive"},
		{"scenarios: [{id: s, flow: f, max_cel_cost: 5, cost_limit: 6}]", "give one of them"},
		{"scenarios: [{id: s, steps: [{set: {nope: {a: 1}}}]}]", `unknown component "nope"`},
		{"scenarios: [{id: s, steps: [{set: {n: {'a..b': 1}}}]}]", "invalid state path"},
		{"scenarios: [{id: s, steps: [{set: {n: {a: 1}}, flow: f}]}]", "one of a flow, an interface, cancel, restart, kill or set"},
		{"scenarios: [{id: s, steps: [{set: {n: {a: 1}}, input: {x: 1}}]}]", "go with a flow or interface step"},
	} {
		doc, err := model.ParseDocument([]byte(base + tc.src))
		if err != nil {
			t.Fatalf("%s: %v", tc.src, err)
		}
		found := false
		for _, is := range model.Validate(doc) {
			if is.Severity == model.SeverityError && strings.Contains(is.Message, tc.want) {
				found = true
			}
		}
		if !found {
			t.Errorf("%s: no error %q in %v", tc.src, tc.want, model.Validate(doc))
		}
	}
	// A route call may stream.
	doc, err := model.ParseDocument([]byte("schema_version: 1\ncomponents: [{id: c}]\ninterfaces:\n" +
		"  - {component: c, name: y, attributes: {path: /x}, behavior: [{yield: 1}]}\n" +
		"  - {component: c, name: s, behavior: [{call: {component: c, path: /x}, targets: [c.y], stream: true, on_item: [{set: {vars.x: 1}}]}]}\n"))
	if err != nil {
		t.Fatal(err)
	}
	for _, is := range model.Validate(doc) {
		if is.Severity == model.SeverityError {
			t.Errorf("route stream: %s: %s", is.Path, is.Message)
		}
	}
}

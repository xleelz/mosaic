package sim_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §17 items 16–21: $absent on whole rows, the microsecond clock,
// run caps, string(map), fault latency on errors and scenario close steps.
const s17bDoc = `
components:
  - {id: client}
  - id: db
    kind: store
    state: {initial: {core: {a: {v: 1, tags: {x: 1, y: 2}}, b: {v: 2}}, other: 1}}
  - {id: svc}
  - {id: tunnel}
interfaces:
  - component: db
    name: read
    latency_ms: 0
    behavior:
      - {return: "= state"}
  - component: svc
    name: loop
    latency_ms: 0
    behavior:
      - {set: {vars.n: 0}}
      - {foreach: "= input.items", steps: [{set: {vars.n: "= vars.n + 1"}}]}
      - {return: "= vars.n"}
  - component: svc
    name: fan
    latency_ms: 0
    behavior:
      - {foreach: "= input.items", max: 3, steps: [{wait: 0}]}
      - {return: ok}
  - component: svc
    name: show
    latency_ms: 0
    behavior:
      - {return: {m: "= string({'b': 1, 'a': [1, 'x', {'z': true}]})", l: "= string([2, 'y'])", e: "= string({})"}}
  - component: svc
    name: clock
    latency_ms: 0.25
    behavior:
      - {return: {us: "= now_us", ts: "= string(timestampUS(now_us))", ms: "= string(timestampMS(now))"}}
  - {component: svc, name: flaky, latency_ms: 2, behavior: [{return: ok}]}
  - component: svc
    name: callflaky
    latency_ms: 0
    behavior:
      - {call: svc.flaky, as: r, on_error: continue}
      - {return: "= vars.r"}
  - {component: tunnel, name: stream, latency_ms: 1000, behavior: [{return: {done: true}}]}
  - component: svc
    name: open
    latency_ms: 0
    behavior:
      - {call: tunnel.stream, session: "= input.sid", as: r, on_error: continue}
      - {return: "= vars.r"}
flows:
  - {id: read, entry: {caller: client, interface: db.read}}
  - {id: loop, entry: {caller: client, interface: svc.loop, input: {items: "= [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]"}}}
  - {id: show, entry: {caller: client, interface: svc.show}}
  - {id: clock, entry: {caller: client, interface: svc.clock}}
  - {id: callflaky, entry: {caller: client, interface: svc.callflaky}}
scenarios:
  - id: absent-row
    flow: read
    state: {db: {core: {a: {$absent: true}}, other: {$absent: true}}}
    expect:
      - "result.value == {'core': {'b': {'v': 2}}}"
  - id: absent-nested
    flow: read
    state: {db: {core: {a: {tags: {x: {$absent: true}}}, c: {v: 3}}}}
    expect:
      - "result.value.core == {'a': {'v': 1, 'tags': {'y': 2}}, 'b': {'v': 2}, 'c': {'v': 3}}"
  - id: absent-missing-key
    flow: read
    state: {db: {core: {zz: {$absent: true}}}}
    expect:
      - "!('zz' in result.value.core) && size(result.value.core) == 2"
  - id: string-map
    flow: show
    expect:
      - "result.value.m == '{\"a\":[1,\"x\",{\"z\":true}],\"b\":1}'"
      - "result.value.l == '[2,\"y\"]'"
      - "result.value.e == '{}'"
  - id: clock-us
    flow: clock
    clock: {epoch_ms: 1700000000000}
    expect:
      - "result.value.us == 1700000000000250"
      - "result.value.ts == '2023-11-14T22:13:20.00025Z'"
      - "result.value.ms == '2023-11-14T22:13:20Z'"
      - "io[0].t == 0 && io[0].t_us == 0"
  - id: error-latency
    flow: callflaky
    faults: [{target: svc.flaky, type: error, code: boom, status: 500, latency_ms: 30}]
    expect:
      - "result.value.error.code == 'boom' && duration_ms == 32"
  - id: unavailable-latency
    flow: callflaky
    faults: [{target: svc.flaky, type: unavailable, latency_ms: 7.5}]
    expect:
      - "result.value.error.code == 'unavailable' && duration_us == 7500"
  - id: foreach-default
    flow: loop
    expect: ["result.value == 20"]
  - id: close-from-step
    steps:
      - {interface: svc.open, caller: client, input: {sid: s1}, as: o1, await: false}
      - {interface: svc.open, caller: client, input: {sid: s2}, as: o2, await: false}
      - {close: {session: s1}, at_ms: 100}
      - {close: {session: "= 's' + '2'"}, at_ms: 200}
    expect:
      - "steps.o1.result.value.error.code == 'canceled' && steps.o1.duration_ms == 100"
      - "steps.o2.result.value.error.code == 'canceled' && steps.o2.duration_ms == 200"
      - "trace.exists(e, e.type == 'close' && e.key == 's1' && e.output.pending == 1)"
`

func TestS17bScenarios(t *testing.T) {
	doc := langDoc(t, s17bDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) { passes(t, doc, sim.Request{Scenario: sc.ID}) })
	}
}

// A request's state may drop a fixture row with {$absent: true}, and a
// whole component's {$absent: true} restores its initial state.
func TestS17bAbsentInRequestState(t *testing.T) {
	doc := langDoc(t, s17bDoc)
	res := run(t, doc, sim.Request{Flow: "read", State: map[string]map[string]any{"db": {"core": map[string]any{"b": map[string]any{"$absent": true}}}}})
	core := res.Summary.Result.Value.(map[string]any)["core"].(map[string]any)
	if _, ok := core["b"]; ok || core["a"] == nil {
		t.Errorf("core %v", core)
	}
	res = run(t, doc, sim.Request{Scenario: "absent-row", State: map[string]map[string]any{"db": {"$absent": true}}})
	if v := res.Summary.Result.Value.(map[string]any); v["other"] != int64(1) {
		t.Errorf("state %v", v)
	}
}

// max_foreach raises the foreach cap for steps without max and cuts steps
// with one; the default cap (100 without max) is unchanged.
func TestS17bForeachCaps(t *testing.T) {
	big := `
  - id: big
    flow: loop
    max_foreach: 150
    max_iterations: 200
  - id: big-default
    flow: loop
  - id: cut
    flow: loop
    max_foreach: 5
`
	doc := langDoc(t, s17bDoc+big)
	items := make([]int, 130)
	b, _ := json.Marshal(map[string]any{"items": items})
	in := json.RawMessage(b)
	if v := run(t, doc, sim.Request{Scenario: "big-default", Input: in}).Summary.Result.Value; v != int64(100) {
		t.Errorf("default cap: %v", v)
	}
	if v := run(t, doc, sim.Request{Scenario: "big", Input: in}).Summary.Result.Value; v != int64(130) {
		t.Errorf("max_foreach 150: %v", v)
	}
	res := run(t, doc, sim.Request{Scenario: "cut", Input: in})
	if v := res.Summary.Result.Value; v != int64(5) {
		t.Errorf("max_foreach 5: %v", v)
	}
	if len(res.Summary.Warnings) == 0 || !strings.Contains(res.Summary.Warnings[0], "max 5 of 130") {
		t.Errorf("warnings %v", res.Summary.Warnings)
	}
	// The limits' MaxForeach (check --max-foreach) is the default.
	lim := sim.DefaultLimits
	lim.MaxForeach = 120
	r2, err := sim.RunWithLimits(doc, sim.Request{Scenario: "big-default", Input: in}, lim)
	if err != nil || r2.Summary.Result.Value != int64(120) {
		t.Fatalf("limits 120: %v %v", err, r2.Summary.Result.Value)
	}
	// A scenario's own max_foreach wins over the limits'.
	r2, err = sim.RunWithLimits(doc, sim.Request{Scenario: "cut", Input: in}, lim)
	if err != nil || r2.Summary.Result.Value != int64(5) {
		t.Fatalf("scenario over limits: %v %v", err, r2.Summary.Result.Value)
	}
}

func TestS17bValidation(t *testing.T) {
	cases := map[string]string{
		"max_foreach must be between 1 and 1000000": "  - {id: bad-cap, flow: read, max_foreach: 0}",
		"a session needs a key":                     "  - {id: bad-close, steps: [{close: {session: ''}}]}",
		"cancel, restart, kill, set or close":       "  - {id: two, steps: [{close: {session: s}, interface: db.read, caller: client}]}",
		"caller, input, on, choices":                "  - {id: inp, steps: [{close: {session: s}, input: {a: 1}}]}",
	}
	for want, sc := range cases {
		doc, err := model.ParseDocument([]byte("schema_version: 1\n" + s17bDoc + sc + "\n"))
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
			t.Errorf("no error containing %q", want)
		}
	}
}

package sim_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §13.1 item 24: absent inputs, per-call choices and repeat in steps.

const mechDoc = `
components:
  - {id: client}
  - {id: svc}
schemas:
  - id: Req
    schema:
      type: object
      properties:
        name: {type: string}
        tag: {type: string}
        meta: {type: object, properties: {a: {type: string}, b: {type: string}}}
interfaces:
  - component: svc
    name: echo
    request: Req
    behavior:
      - return:
          has_tag: "= has(input.tag)"
          tag_null: "= has(input.tag) && input.tag == null"
          has_meta_b: "= has(input.meta) && has(input.meta.b)"
          has_name: "= has(input.name)"
  - component: svc
    name: pick
    behavior:
      - set: {"state.n": "= has(state.n) ? state.n + 1 : 1"}
      - choice: route
        default: x
        options:
          x: [{set: {"state.picks": "= (has(state.picks) ? state.picks : []) + ['x']"}}]
          y: [{set: {"state.picks": "= (has(state.picks) ? state.picks : []) + ['y']"}}]
          z: [{set: {"state.picks": "= (has(state.picks) ? state.picks : []) + ['z']"}}]
      - return: "= state.picks"
  - component: svc
    name: loop
    behavior:
      - call: svc.pick
      - call: svc.pick
      - call: svc.pick
      - call: svc.pick
      - return: "= state.picks"
flows:
  - id: echo
    entry: {caller: client, interface: svc.echo, input: {tag: {$absent: true}}}
  - {id: loop, entry: {caller: client, interface: svc.loop}}
  - id: tick
    entry: {caller: client, interface: svc.pick, repeat: {count: 3, interval_ms: 10}}
`

func TestAbsentInputs(t *testing.T) {
	doc := langDoc(t, mechDoc)
	val := func(res *sim.Result) map[string]any {
		t.Helper()
		m, _ := okValue(t, res).(map[string]any)
		return m
	}
	// The flow entry removes tag; the faked name and meta stay.
	res := run(t, doc, sim.Request{Flow: "echo"})
	eq(t, "entry $absent", val(res), map[string]any{"has_tag": false, "tag_null": false, "has_meta_b": true, "has_name": true})
	// A request overlay sets tag back, and removes a nested key.
	res = run(t, doc, sim.Request{Flow: "echo", Input: json.RawMessage(`{"tag": "t", "meta": {"b": {"$absent": true}}}`)})
	eq(t, "overlay", val(res), map[string]any{"has_tag": true, "tag_null": false, "has_meta_b": false, "has_name": true})
	// {$null: true} is a real null.
	res = run(t, doc, sim.Request{Flow: "echo", Input: json.RawMessage(`{"tag": {"$null": true}}`)})
	eq(t, "$null", val(res), map[string]any{"has_tag": true, "tag_null": true, "has_meta_b": true, "has_name": true})
	if got := string(res.Request.Input); got != `{"tag":{"$null":true}}` {
		t.Errorf("effective input keeps the markers: %s", got)
	}
	// A literal null keeps its old meaning: the faked value.
	res = run(t, doc, sim.Request{Flow: "echo", Input: json.RawMessage(`{"name": null}`)})
	eq(t, "literal null", val(res)["has_name"], true)

	// Steps: the step input removes a key, and later overrides the entry.
	doc = langDoc(t, mechDoc+`
scenarios:
  - id: steps
    steps:
      - {interface: svc.echo, caller: client, as: a, input: {name: {$absent: true}}}
      - {flow: echo, as: b, input: {tag: "=steps.a.status"}}
    expect:
      - "!steps.a.result.value.has_name && steps.a.result.value.has_tag"
      - "steps.b.result.value.has_tag && steps.b.result.value.has_name"
`)
	passes(t, doc, sim.Request{Scenario: "steps"})
}

func TestPerCallChoices(t *testing.T) {
	doc := langDoc(t, mechDoc+`
scenarios:
  - id: list
    flow: loop
    choices: {svc.pick.route: [y, z]}
    expect: ["result.value == ['y', 'z', 'z', 'z']"]
  - id: by-call
    flow: loop
    choices: {svc.pick.route: {"2": z, "4": y}}
    expect: ["result.value == ['x', 'z', 'x', 'y']"]
  - id: scalar
    flow: loop
    choices: {svc.pick.route: y}
    expect: ["result.value == ['y', 'y', 'y', 'y']"]
  - id: steps
    choices: {svc.pick.route: [y, z, x]}
    steps:
      - {flow: tick, as: a}
      - {flow: tick, as: b, choices: {svc.pick.route: [z, y]}}
      - {flow: tick, as: c}
    expect:
      - "steps.a.result.value == ['y']"
      - "steps.b.result.value == ['y', 'z']"
      - "steps.c.result.value == ['y', 'z', 'z']"
`)
	for _, id := range []string{"list", "by-call", "scalar", "steps"} {
		t.Run(id, func(t *testing.T) { passes(t, doc, sim.Request{Scenario: id}) })
	}
	// A request's list choice is checked and echoed.
	res := run(t, doc, sim.Request{Flow: "loop", Choices: map[string]model.Choice{"svc.pick.route": {Seq: []string{"z", "y"}}}})
	eq(t, "request list", okValue(t, res), []any{"z", "y", "y", "y"})
	b, _ := json.Marshal(res.Request.Choices)
	eq(t, "echo", string(b), `{"svc.pick.route":["z","y"]}`)
	if _, err := sim.Run(doc, sim.Request{Flow: "loop", Choices: map[string]model.Choice{"svc.pick.route": {Seq: []string{"y", "nope"}}}}); err == nil {
		t.Error("an unknown option in a list is refused")
	}
}

func TestChoiceJSON(t *testing.T) {
	for _, src := range []string{`"a"`, `["a","b"]`, `{"1":"a","3":"b"}`} {
		var c model.Choice
		if err := json.Unmarshal([]byte(src), &c); err != nil {
			t.Fatalf("%s: %v", src, err)
		}
		b, _ := json.Marshal(c)
		eq(t, src, string(b), src)
	}
	for _, src := range []string{`[]`, `{"0":"a"}`, `{"x":"a"}`, `[1]`} {
		var c model.Choice
		if err := json.Unmarshal([]byte(src), &c); err == nil {
			t.Errorf("%s: want an error", src)
		}
	}
	c := model.Choice{Seq: []string{"a", "b"}}
	for n, want := range map[int]string{1: "a", 2: "b", 9: "b"} {
		if o, ok := c.At(n); !ok || o != want {
			t.Errorf("At(%d) = %q, %v", n, o, ok)
		}
	}
	if _, ok := (model.Choice{Calls: map[int]string{2: "a"}}).At(1); ok {
		t.Error("an unlisted call falls back to the default")
	}
}

func TestStepRepeat(t *testing.T) {
	doc := langDoc(t, mechDoc+`
scenarios:
  - id: repeat
    steps:
      - {flow: tick, as: once}
      - {flow: tick, as: thrice, repeat: {count: 3, interval_ms: 10, initial_delay_ms: 5}}
      - {interface: svc.pick, caller: client, as: twice, repeat: {count: 2, interval_ms: 1}}
    expect:
      - "steps.once.result.value.size() == 1"
      - "steps.thrice.result.value.size() == 4 && steps.thrice.duration_ms >= 25"
      - "steps.twice.result.value.size() == 6"
      - "calls['svc.pick'] == 6"
`)
	passes(t, doc, sim.Request{Scenario: "repeat"})

	bad := langDoc(t, mechDoc)
	bad.Scenarios = []model.Scenario{{ID: "bad", Steps: []model.ScenarioStep{
		{Flow: "tick", Repeat: &model.Repeat{Count: 0}},
		{Cancel: "t", Repeat: &model.Repeat{Count: 2}},
	}}}
	var msgs []string
	for _, is := range model.Validate(bad) {
		msgs = append(msgs, is.Path+": "+is.Message)
	}
	all := strings.Join(msgs, "\n")
	for _, want := range []string{"scenarios[bad].steps[0].repeat.count: must be between 1 and", "scenarios[bad].steps[1].repeat: repeat goes with a flow or interface step"} {
		if !strings.Contains(all, want) {
			t.Errorf("missing %q in:\n%s", want, all)
		}
	}
}

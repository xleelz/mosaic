package model

import (
	"strings"
	"testing"
)

// TestStreamsChannelsKillsValidation: §13.1 item 18 steps, kill faults and
// cost_limit.
func TestStreamsChannelsKillsValidation(t *testing.T) {
	doc, err := ParseDocument([]byte(`
schema_version: 1
components: [{id: c}, {id: w}]
interfaces:
  - component: c
    name: ok
    behavior:
      - {call: w.gen, stream: true, on_item: [{yield: "= vars.item"}], as: g}
      - {put: "= 'q-' + self", value: "= input", capacity: 2, timeout_ms: 5, on_error: continue}
      - {receive: q, as: item, timeout_ms: "= 10", on_error: [{return: idle}]}
      - {kill: {component: w}}
      - {yield: {done: true}}
  - component: w
    name: gen
  - component: c
    name: bad
    behavior:
      - {call: w.gen, on_item: [{return: 1}]}
      - {set: {state.a: 1}, capacity: 3}
      - {put: q, capacity: 0.5}
      - {receive: q, as: "not ok"}
      - {kill: {component: nope}}
      - {yield: 1, stream: true}
flows:
  - {id: f, entry: {caller: c, interface: c.ok}}
scenarios:
  - id: good
    flow: f
    cost_limit: 20000000
    faults: [{target: w, type: kill, at_ms: 10}]
    steps:
      - {flow: f}
      - {kill: {component: w}}
  - id: bad
    flow: f
    cost_limit: 0
    faults: [{target: w, type: kill}, {target: w, type: error, code: x, at_ms: 3}]
    steps:
      - {flow: f, kill: {component: w}}
`))
	if err != nil {
		t.Fatal(err)
	}
	var msgs []string
	for _, is := range Validate(doc) {
		if is.Severity == SeverityError {
			msgs = append(msgs, is.Path+": "+is.Message)
		}
	}
	all := strings.Join(msgs, "\n")
	for _, want := range []string{
		"interfaces[c.bad].behavior[0].on_item: on_item needs stream: true",
		"interfaces[c.bad].behavior[1].capacity: capacity goes with put",
		"interfaces[c.bad].behavior[2].capacity: a channel capacity is a whole number of at least 1",
		"interfaces[c.bad].behavior[3].as: invalid variable name",
		"interfaces[c.bad].behavior[4].kill.component: unknown component",
		"interfaces[c.bad].behavior[5]: stream and on_item go with call",
		"scenarios[bad].cost_limit: cost_limit must be positive",
		"scenarios[bad].faults[0].at_ms: a kill fault needs at_ms",
		"scenarios[bad].faults[1].at_ms: at_ms goes with a kill fault",
		"scenarios[bad].steps[0]: a step names one of a flow, an interface, cancel, restart or kill",
	} {
		if !strings.Contains(all, want) {
			t.Errorf("missing %q in:\n%s", want, all)
		}
	}
	if strings.Contains(all, "c.ok") || strings.Contains(all, "scenarios[good]") {
		t.Errorf("valid steps reported:\n%s", all)
	}
}

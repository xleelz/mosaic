package model

import (
	"strings"
	"testing"
)

// TestConcurrencyValidation: the §13.1 item 14 fields (token, cancel,
// restart, dynamic set paths, await, cancel and restart steps,
// max_virtual_ms) decode and are checked.
func TestConcurrencyValidation(t *testing.T) {
	doc, err := ParseDocument([]byte(`
schema_version: 1
components: [{id: c}, {id: w}, {id: k, parent: w}]
interfaces:
  - component: c
    name: ok
    behavior:
      - {call: c.ok, token: t1}
      - {wait: 10, token: "= 'x' + input.id", on_error: continue}
      - {emit: c.ok, after_ms: 5, token: t2}
      - {cancel: "= 'x' + input.id"}
      - {restart: {component: w, instance: "= self", keep: [k]}}
      - {set: {"= 'state.s.' + input.id": 1}}
  - component: c
    name: bad
    behavior:
      - {set: {state.a: 1}, token: t}
      - {cancel: ""}
      - {restart: {component: nope, keep: [gone]}}
      - {set: {"= 'state.' +": 1}}
flows:
  - {id: f, entry: {caller: c, interface: c.ok}}
scenarios:
  - id: s
    max_virtual_ms: 1000
    steps:
      - {flow: f, await: false}
      - {cancel: t1, at_ms: 5}
      - {restart: {component: w, instance: w9}}
  - id: bad
    max_virtual_ms: 0
    steps:
      - {cancel: t1, flow: f}
      - {cancel: t1, input: {a: 1}}
      - {restart: {component: nope}}
`))
	if err != nil {
		t.Fatal(err)
	}
	st := doc.Scenarios[0].Steps
	if st[0].Awaited() || !st[1].Awaited() || st[1].Cancel != "t1" || st[2].Restart.Instance != "w9" || *doc.Scenarios[0].MaxVirtualMS != 1000 {
		t.Errorf("decoded %+v", st)
	}
	if acts := doc.Interfaces[0].Behavior[4].Actions(); len(acts) != 1 || acts[0] != "restart" {
		t.Errorf("actions %v", acts)
	}
	var msgs []string
	for _, is := range Validate(doc) {
		if is.Severity == SeverityError {
			msgs = append(msgs, is.Path+": "+is.Message)
		}
	}
	all := strings.Join(msgs, "\n")
	for _, want := range []string{
		"interfaces[c.bad].behavior[0].token: token goes with call, wait, parallel, emit or publish",
		"interfaces[c.bad].behavior[2].restart.component: unknown component \"nope\"",
		"interfaces[c.bad].behavior[2].restart.keep[0]: unknown component \"gone\"",
		"scenarios[bad].max_virtual_ms: max_virtual_ms must be positive",
		"scenarios[bad].steps[0]: a step names one of a flow, an interface, cancel or restart",
		"scenarios[bad].steps[1]: caller, input, on, choices and deadline_ms go with a flow or interface step",
		"scenarios[bad].steps[2].restart.component: unknown component \"nope\"",
	} {
		if !strings.Contains(all, want) {
			t.Errorf("missing %q in:\n%s", want, all)
		}
	}
	if strings.Contains(all, "c.ok") || strings.Contains(all, "scenarios[s]") {
		t.Errorf("valid steps reported:\n%s", all)
	}
	if !strings.Contains(all, "interfaces[c.bad].behavior[3].set") {
		t.Errorf("a bad dynamic path expression should be reported:\n%s", all)
	}
	if !strings.Contains(all, "interfaces[c.bad].behavior[1]") {
		t.Errorf("an empty cancel should be reported:\n%s", all)
	}
}

// TestRendezvousValidation: rendezvous steps (§13.1 item 17) take count,
// value, as, timeout_ms, latency_ms and on_error; value and latency_ms go
// with nothing else.
func TestRendezvousValidation(t *testing.T) {
	doc, err := ParseDocument([]byte(`
schema_version: 1
components: [{id: c}]
interfaces:
  - component: c
    name: ok
    behavior:
      - {rendezvous: "= 'ar-' + string(input.step)", count: 4, value: "= input.part", as: ar, timeout_ms: 10, latency_ms: 0.5, on_error: continue}
      - {rendezvous: barrier, count: "= size(input.ranks)", latency_ms: "= 0.001 * double(input.bytes)"}
  - component: c
    name: bad
    behavior:
      - {rendezvous: b}
      - {set: {state.a: 1}, value: 1}
      - {rendezvous: b, count: 2, latency_ms: "= 1 +"}
`))
	if err != nil {
		t.Fatal(err)
	}
	if acts := doc.Interfaces[0].Behavior[0].Actions(); len(acts) != 1 || acts[0] != "rendezvous" {
		t.Errorf("actions %v", acts)
	}
	var msgs []string
	for _, is := range Validate(doc) {
		if is.Severity == SeverityError {
			msgs = append(msgs, is.Path+": "+is.Message)
		}
	}
	all := strings.Join(msgs, "\n")
	for _, want := range []string{
		"interfaces[c.bad].behavior[0].count: a rendezvous needs a count of at least 1",
		"interfaces[c.bad].behavior[1]: value and latency_ms go with rendezvous",
		"interfaces[c.bad].behavior[2].latency_ms: invalid expression",
	} {
		if !strings.Contains(all, want) {
			t.Errorf("missing %q in:\n%s", want, all)
		}
	}
	if strings.Contains(all, "c.ok") {
		t.Errorf("valid steps reported:\n%s", all)
	}
}

package model

import (
	"strings"
	"testing"
)

// TestStreamFlowValidation: §16.4 window and stall_ms.
func TestStreamFlowValidation(t *testing.T) {
	doc, err := ParseDocument([]byte(`
schema_version: 1
components: [{id: c}, {id: w}]
interfaces:
  - component: c
    name: ok
    behavior:
      - {call: w.gen, stream: true, window: 4, stall_ms: 250, on_item: [{set: {state.n: 1}}]}
      - {call: w.gen, stream: true, window: "= 2", stall_ms: "= 10"}
  - component: w
    name: gen
  - component: c
    name: bad
    behavior:
      - {call: w.gen, window: 2}
      - {call: w.gen, stream: true, window: 0.5}
      - {call: w.gen, stream: true, stall_ms: 10}
      - {call: w.gen, stream: true, window: -1, stall_ms: -5}
      - {set: {state.a: 1}, window: 3}
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
		"interfaces[c.bad].behavior[0]: window, window_bytes and stall_ms go with stream: true",
		"interfaces[c.bad].behavior[1].window: a stream window is a whole number of at least 1",
		"interfaces[c.bad].behavior[2].stall_ms: stall_ms needs a window",
		"interfaces[c.bad].behavior[3].window: a stream window is a whole number of at least 1",
		"interfaces[c.bad].behavior[3].stall_ms: stall_ms must be positive",
		"interfaces[c.bad].behavior[4]: window, window_bytes and stall_ms go with stream: true",
	} {
		if !strings.Contains(all, want) {
			t.Errorf("missing %q in:\n%s", want, all)
		}
	}
	if strings.Contains(all, "c.ok") {
		t.Errorf("valid steps reported:\n%s", all)
	}
}

// TestByteWindowValidation: §17 item 5 window_bytes and relay, and §17
// item 6 the literal-null warning in update values.
func TestByteWindowValidation(t *testing.T) {
	doc, err := ParseDocument([]byte(`
schema_version: 1
components: [{id: c}, {id: w}, {id: db, kind: datastore}]
interfaces:
  - component: c
    name: ok
    behavior:
      - {call: w.gen, stream: true, window_bytes: 4096, stall_ms: 250, relay: true}
      - {call: w.gen, stream: true, window: 2, window_bytes: "= 10"}
  - component: w
    name: gen
  - component: c
    name: bad
    behavior:
      - {call: w.gen, window_bytes: 2}
      - {call: w.gen, relay: true}
  - {component: db, name: patch, store: {table: t, op: update, key: k, value: {a: null, b: {c: null, d: {$null: true}}, e: {$absent: true}}}}
`))
	if err != nil {
		t.Fatal(err)
	}
	var errs, warns []string
	for _, is := range Validate(doc) {
		if is.Severity == SeverityError {
			errs = append(errs, is.Path+": "+is.Message)
		} else if strings.Contains(is.Message, "literal null") {
			warns = append(warns, is.Path)
		}
	}
	all := strings.Join(errs, "\n")
	for _, want := range []string{
		"interfaces[c.bad].behavior[0]: window, window_bytes and stall_ms go with stream: true",
		"interfaces[c.bad].behavior[1].relay: relay goes with stream: true",
	} {
		if !strings.Contains(all, want) {
			t.Errorf("missing %q in:\n%s", want, all)
		}
	}
	if strings.Contains(all, "c.ok") {
		t.Errorf("valid steps reported:\n%s", all)
	}
	if len(warns) != 2 || !strings.HasSuffix(warns[0], ".store.value.a") || !strings.HasSuffix(warns[1], ".store.value.b.c") {
		t.Errorf("null warnings %v", warns)
	}
}

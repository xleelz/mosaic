package model

import (
	"strings"
	"testing"
)

// TestGaps12Validation: join.count_unstarted and on_late (DESIGN §13.1
// item 12) decode, round-trip and are checked.
func TestGaps12Validation(t *testing.T) {
	doc, err := ParseDocument([]byte(`
schema_version: 1
components: [{id: c}]
interfaces:
  - component: c
    name: a
    behavior:
      - parallel: [x, y]
        stagger_ms: 10
        join: {need: 1, count_unstarted: false}
        steps: [{return: 1}]
        on_late: [{set: {state.n: "= vars.late.end_ms"}}]
  - component: c
    name: b
    behavior:
      - parallel: [x]
        join: {count_unstarted: false}
        steps: [{return: 1}]
      - {set: {state.n: 1}, on_late: [{return: 1}]}
`))
	if err != nil {
		t.Fatal(err)
	}
	s := doc.Interfaces[0].Behavior[0]
	if s.Join.Unstarted() || len(s.OnLate) != 1 || doc.Interfaces[1].Behavior[0].Join.Unstarted() {
		t.Errorf("decoded %+v", s)
	}
	if !(*JoinSpec)(nil).Unstarted() || !(&JoinSpec{}).Unstarted() {
		t.Error("count_unstarted defaults to true")
	}
	var got []string
	for _, is := range Validate(doc) {
		got = append(got, is.Path+": "+is.Message)
	}
	all := strings.Join(got, "\n")
	for _, want := range []string{
		"interfaces[c.b].behavior[0].join.count_unstarted: count_unstarted: false has no effect without stagger_ms",
		"on_late go with parallel",
	} {
		if !strings.Contains(all, want) {
			t.Errorf("issues lack %q:\n%s", want, all)
		}
	}
	if strings.Contains(all, "interfaces[c.a]") {
		t.Errorf("unexpected issues for interfaces[0]:\n%s", all)
	}
}

package main

import (
	"bytes"
	"strings"
	"testing"
)

// TestRefinementExpectationFlips: a scenario's own expectation that passes
// black box and fails refined is reported, though the result agrees
// (§15.4).
func TestRefinementExpectationFlips(t *testing.T) {
	child := strings.ReplaceAll(refChild("overloaded", 5, "string"), "'n' + string(input.n)", "'m' + string(input.n)")
	r, out := checkRef(t, child)
	want := "✗ answers: expect: expect state.db.answers['a'].text == 'n1': parent pass, child fail"
	if !strings.Contains(out, want) {
		t.Errorf("flip not reported (want %q):\n%s", want, out)
	}
	if strings.Contains(out, "✗ overloaded: expect") {
		t.Errorf("an unchanged expectation reported as a flip:\n%s", out)
	}
	if r.differing() != 1 {
		t.Errorf("want 1 differing scenario:\n%s", out)
	}
	// Matching runs flip nothing.
	if _, out := checkRef(t, refChild("overloaded", 5, "string")); strings.Contains(out, ": expect:") {
		t.Errorf("flips in matching runs:\n%s", out)
	}
}

// TestRefinementTrace: --refinement-trace prints the two runs side by side,
// lining up shared steps and marking the child's own.
func TestRefinementTrace(t *testing.T) {
	trace := func(sc string) string {
		t.Helper()
		p, c := refDocs(t, refChild("overloaded", 40, "string"))
		r, err := checkRefinement(p, c, refinementOpts{Trace: sc})
		if err != nil {
			t.Fatal(err)
		}
		var b bytes.Buffer
		r.printTrace(&b)
		return b.String()
	}
	out := trace("answers")
	if !strings.HasPrefix(out, "refinement trace answers: engine black box | engine refined by engine-logic\n") {
		t.Fatalf("header:\n%s", out)
	}
	var shared, childOnly bool
	for _, line := range strings.Split(out, "\n") {
		if strings.Contains(line, "→ db.put") && strings.Count(line, "→ db.put") == 2 && strings.Contains(line, " │ ") {
			shared = true
		}
		if strings.Contains(line, " > ") && strings.Contains(line, "sched.step") {
			childOnly = true
		}
	}
	if !shared || !childOnly {
		t.Errorf("shared step lined up %v, child step marked %v:\n%s", shared, childOnly, out)
	}
	if out := trace("ping"); !strings.Contains(out, `scenario "ping" doesn't cross engine`) {
		t.Errorf("non-crossing scenario: %s", out)
	}
	if out := trace("nope"); !strings.Contains(out, `no scenario "nope"`) {
		t.Errorf("unknown scenario: %s", out)
	}
}

// TestSideBySideAligns: shared lines line up across inserted and removed
// ones, timings ignored.
func TestSideBySideAligns(t *testing.T) {
	var b bytes.Buffer
	sideBySide(&b, []string{"a 1ms", "b", "x", "c", "d"}, []string{"a 7ms", "b", "y1", "y2", "c", "d"}, 6)
	got := strings.Split(strings.TrimRight(b.String(), "\n"), "\n")
	want := []string{
		"  black… │ refined",
		"  a 1ms  │ a 7ms",
		"  b      │ b",
		"  x      < ",
		"         > y1",
		"         > y2",
		"  c      │ c",
		"  d      │ d",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Errorf("got:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
}

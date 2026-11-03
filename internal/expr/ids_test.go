package expr

import (
	"regexp"
	"testing"
)

var uuidShape = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-8[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

// DESIGN §15.1: id(prefix, key...) is deterministic from the run seed, the
// prefix and the keys, never from the clock; seq(name) counts per run.
func TestIDIsDeterministic(t *testing.T) {
	eval := func(src string, act map[string]any) any {
		t.Helper()
		v, err := Behavior.Eval(src, act)
		if err != nil {
			t.Fatalf("%s: %v", src, err)
		}
		return v
	}
	a := eval("id('req', input.k, 3)", map[string]any{IDsKey: NewIDs(7), "input": map[string]any{"k": "x"}, "now": int64(1)})
	// Another IDs value with the same seed, at another time: the same id.
	b := eval("id('req', 'x', 3)", map[string]any{IDsKey: NewIDs(7), "now": int64(999999)})
	if a != b {
		t.Errorf("same seed and keys gave %v and %v", a, b)
	}
	if s, _ := a.(string); !uuidShape.MatchString(s) {
		t.Errorf("id %v isn't UUID-shaped", a)
	}
	for src, act := range map[string]map[string]any{
		"id('req', 'x', 3)":   {IDsKey: NewIDs(8)}, // another seed
		"id('resp', 'x', 3)":  {IDsKey: NewIDs(7)}, // another prefix
		"id('req', 'x', '3')": {IDsKey: NewIDs(7)}, // another key type
		"id('req', 'x')":      {IDsKey: NewIDs(7)}, // fewer keys
		"id('req', ['x', 3])": {IDsKey: NewIDs(7)}, // a list key
	} {
		if v := eval(src, act); v == a {
			t.Errorf("%s gave the same id as id('req', 'x', 3)", src)
		}
	}
	// Map keys hash canonically, whatever their order.
	ids := NewIDs(1)
	m1 := eval("id('m', {'a': 1, 'b': 2})", map[string]any{IDsKey: ids})
	m2 := eval("id('m', {'b': 2, 'a': 1})", map[string]any{IDsKey: ids})
	if m1 != m2 {
		t.Errorf("map keys: %v != %v", m1, m2)
	}
	// Without run state, id uses seed 1.
	if eval("id('m', {'a': 1, 'b': 2})", map[string]any{}) != m1 {
		t.Errorf("id without run state should use seed 1")
	}
	if _, err := Expect.Eval("id('x')", map[string]any{IDsKey: NewIDs(1)}); err != nil {
		t.Errorf("expectations should see id: %v", err)
	}
}

func TestSeqCountsPerRun(t *testing.T) {
	ids := NewIDs(1)
	act := map[string]any{IDsKey: ids}
	got, err := Behavior.Eval("[seq('a'), seq('a'), seq('b')]", act)
	if err != nil {
		t.Fatal(err)
	}
	if want := []any{int64(1), int64(2), int64(1)}; !equalList(got, want) {
		t.Errorf("got %#v, want %#v", got, want)
	}
	// The counter lives in the run's state, across evaluations.
	if v, _ := Behavior.Eval("seq('a')", act); v != int64(3) {
		t.Errorf("third seq('a') = %v", v)
	}
	if v, _ := Behavior.Eval("seq('a')", map[string]any{IDsKey: NewIDs(1)}); v != int64(1) {
		t.Errorf("a new run's seq('a') = %v", v)
	}
	// eval's sandbox has no run-bound helpers.
	if _, err := Behavior.Eval("eval('seq(\"a\")', {})", act); err == nil {
		t.Errorf("seq should not be reachable from eval")
	}
}

func equalList(got any, want []any) bool {
	l, ok := got.([]any)
	if !ok || len(l) != len(want) {
		return false
	}
	for i := range l {
		if l[i] != want[i] {
			return false
		}
	}
	return true
}

package expr

import (
	"reflect"
	"strings"
	"testing"
)

// DESIGN §17 item 13: list.indexOf and list.lastIndexOf.
func TestListIndexOf(t *testing.T) {
	act := map[string]any{"input": map[string]any{"l": []any{"a", "b", "a"}, "n": []any{int64(1), 2.0, int64(3)}}}
	for src, want := range map[string]any{
		"input.l.indexOf('a')":                   int64(0),
		"input.l.lastIndexOf('a')":               int64(2),
		"input.l.indexOf('b')":                   int64(1),
		"input.l.indexOf('z')":                   int64(-1),
		"input.l.lastIndexOf('z')":               int64(-1),
		"[].indexOf(1)":                          int64(-1),
		"input.n.indexOf(2)":                     int64(1), // CEL equality: 2 == 2.0
		"[[1], [2]].indexOf([2])":                int64(1),
		"[{'k': 1}].indexOf({'k': 1})":           int64(0),
		"'hello'.indexOf('l')":                   int64(2), // the string library's own
		"'hello'.lastIndexOf('l')":               int64(3),
		`eval("x.indexOf(3)", {"x": [1, 2, 3]})`: int64(2),
	} {
		got, err := Behavior.Eval(src, act)
		if err != nil {
			t.Errorf("%s: %v", src, err)
			continue
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s = %#v, want %#v", src, got, want)
		}
	}
}

func TestListIndexOfCountsAgainstTheCostLimit(t *testing.T) {
	long := make([]any, 10_000)
	for i := range long {
		long[i] = int64(i)
	}
	act := map[string]any{"vars": map[string]any{"l": long}, CostLimitKey: int64(500)}
	for _, src := range []string{"vars.l.indexOf(-1)", "vars.l.lastIndexOf(-1)", "eval('x.indexOf(-1)', {'x': vars.l})"} {
		if _, err := Behavior.Eval(src, act); err == nil || !strings.Contains(err.Error(), "cost") {
			t.Errorf("%s over 10,000 elements under a cost limit of 500: got %v, want a cost error", src, err)
		}
	}
	act[CostLimitKey] = int64(20_000)
	if got, err := Behavior.Eval("vars.l.indexOf(9999)", act); err != nil || got != int64(9999) {
		t.Errorf("under 20,000: got %v %v", got, err)
	}
}

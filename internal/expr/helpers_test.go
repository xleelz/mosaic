package expr

import (
	"reflect"
	"testing"
)

func TestHelpers(t *testing.T) {
	act := map[string]any{"vars": map[string]any{"m": map[string]any{"b": int64(2), "a": int64(1), "c": map[string]any{"x": int64(1)}}}}
	for src, want := range map[string]any{
		"sum([1, 2, 3])":                          int64(6),
		"sum([])":                                 int64(0),
		"sum([1, 0.5])":                           1.5,
		"merge(vars.m, {'c': {'y': 2}, 'd': 4})":  map[string]any{"a": int64(1), "b": int64(2), "c": map[string]any{"x": int64(1), "y": int64(2)}, "d": int64(4)},
		"omit(vars.m, 'a')":                       map[string]any{"b": int64(2), "c": map[string]any{"x": int64(1)}},
		"omit(vars.m, ['a', 'b'], 'c')":           map[string]any{},
		"vars.m.map(k, k)":                        []any{"a", "b", "c"},
		"vars.m.transformList(k, v, k)":           []any{"a", "b", "c"},
		"vars.m.exists(k, v, k == 'b' && v == 2)": true,
		"[3, 4].transformMap(i, v, v * i)":        map[string]any{"0": int64(0), "1": int64(4)},
		"random(1)":                               int64(0),
	} {
		got, err := Behavior.Eval(src, act)
		if err != nil {
			t.Errorf("%s: %v", src, err)
			continue
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s: got %#v, want %#v", src, got, want)
		}
	}
	if _, err := Behavior.Eval("random(0)", act); err == nil {
		t.Errorf("random(0) should fail")
	}
}

func TestRandomIsSeededByTheActivation(t *testing.T) {
	n := int64(0)
	act := map[string]any{RandomKey: func(k int64) int64 { n++; return n % k }}
	got, err := Behavior.Eval("[random(10), random(10)]", act)
	if err != nil || !reflect.DeepEqual(got, []any{int64(1), int64(2)}) {
		t.Errorf("got %v, %v", got, err)
	}
	a, _ := Behavior.Eval("random(1000000)", map[string]any{})
	b, _ := Behavior.Eval("random(1000000)", map[string]any{})
	if a != b {
		t.Errorf("unseeded random differs: %v %v", a, b)
	}
}

func TestEnvironments(t *testing.T) {
	for _, c := range []struct {
		env *Env
		src string
		ok  bool
	}{
		{Behavior, "self + string(deadline) + string(config.x)", true},
		{Behavior, "steps.a", false},
		{Step, "steps.a.result.ok && self == ''", true},
		{Expect, "trace.size() + size(topology) + size(calls_by_instance) + size(steps) + size(config) > 0", true},
		{Expect, "self == ''", false},
		{Expect, "deadline == null", false},
	} {
		if _, err := c.env.Compile(c.src); (err == nil) != c.ok {
			t.Errorf("%s: compile error %v, want ok=%v", c.src, err, c.ok)
		}
	}
	steps := NewSteps(map[string]any{"w": map[string]any{"status": "ok"}}, []any{map[string]any{"status": "ok"}, map[string]any{"status": "error"}})
	got, err := Step.Eval("[steps.w.status, steps[1].status, has(steps.w), size(steps)]", map[string]any{"steps": steps})
	if err != nil || !reflect.DeepEqual(got, []any{"ok", "error", true, int64(3)}) {
		t.Errorf("steps: %v %v", got, err)
	}
}

func TestStringAndEvalHelpers(t *testing.T) {
	act := map[string]any{"vars": map[string]any{"ctx": map[string]any{"editorTextFocus": true, "editorReadonly": false}}}
	for src, want := range map[string]any{
		"replace('a--b-c', '-+', '_')":                         "a_b_c",
		"replace('k=v', '(\\\\w)=(\\\\w)', '$2=$1')":           "v=k",
		"matches('editor.action', '^editor\\\\.')":             true,
		"'abc'.replace('b', 'x')":                              "axc",
		"eval('editorTextFocus && !editorReadonly', vars.ctx)": true,
		"eval('editorTextFocus && editorReadonly', vars.ctx)":  false,
		"eval('a + b', {'a': 1, 'b': 2})":                      int64(3),
		"eval('size(xs) > 1 && sum(xs) == 3', {'xs': [1, 2]})": true,
		"canceled('t1')": false,
	} {
		got, err := Behavior.Eval(src, act)
		if err != nil {
			t.Errorf("%s: %v", src, err)
			continue
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s: got %#v, want %#v", src, got, want)
		}
	}
	// eval is sandboxed: the run's variables are not visible.
	for _, src := range []string{"eval('vars.ctx', {})", "eval('random(2)', {})", "eval('(', {})", "replace('a', '(', 'b')"} {
		if _, err := Behavior.Eval(src, act); err == nil {
			t.Errorf("%s should fail", src)
		}
	}
	act[CanceledKey] = func(n string) bool { return n == "t1" }
	if got, err := Behavior.Eval("canceled('t1') && !canceled('t2')", act); err != nil || got != true {
		t.Errorf("canceled: %v %v", got, err)
	}
	if got, err := Expect.Eval("eval('x == 1', {'x': 1})", map[string]any{}); err != nil || got != true {
		t.Errorf("eval in expectations: %v %v", got, err)
	}
}

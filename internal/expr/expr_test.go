package expr

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func TestExprOf(t *testing.T) {
	cases := []struct {
		in     any
		src    string
		isExpr bool
	}{
		{"=input.a", "input.a", true},
		{"=  input.a  ", "input.a", true},
		{"=", "", true},
		{"input.a", "", false},
		{" =input.a", "", false},
		{"", "", false},
		{int64(3), "", false},
		{nil, "", false},
		{map[string]any{"a": "=x"}, "", false},
	}
	for _, c := range cases {
		src, ok := ExprOf(c.in)
		if ok != c.isExpr || (ok && src != c.src) {
			t.Errorf("ExprOf(%#v) = %q, %v; want %q, %v", c.in, src, ok, c.src, c.isExpr)
		}
	}
}

func TestTemplate(t *testing.T) {
	act := map[string]any{
		"input": map[string]any{"n": int64(2), "name": "ada", "list": []any{int64(1), int64(2)}},
		"state": map[string]any{}, "ctx": map[string]any{}, "vars": map[string]any{},
		"attempt": int64(1), "now": int64(5), "error": nil,
	}
	cases := []struct {
		name string
		tpl  any
		want any
	}{
		{"literal string", "hello", "hello"},
		{"expression", "= input.n * 3", int64(6)},
		{"expression string", "= input.name + '!'", "ada!"},
		{"json number literal", json.Number("7"), int64(7)},
		{"float literal", json.Number("7.5"), 7.5},
		{"bool literal", true, true},
		{"nil", nil, nil},
		{"map recursion", map[string]any{"a": "= input.n", "b": map[string]any{"c": "= now", "d": "x"}},
			map[string]any{"a": int64(2), "b": map[string]any{"c": int64(5), "d": "x"}}},
		{"list recursion", []any{"= input.n", "lit", []any{"= input.list[1]"}},
			[]any{int64(2), "lit", []any{int64(2)}}},
		{"expression yields map", "= {'k': input.list}", map[string]any{"k": []any{int64(1), int64(2)}}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := Behavior.Template(c.tpl, act)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("got %#v, want %#v", got, c.want)
			}
		})
	}
	// An error deep inside a template surfaces.
	for _, tpl := range []any{
		map[string]any{"a": map[string]any{"b": "= input.missing"}},
		[]any{"ok", "= 1 +"},
	} {
		if _, err := Behavior.Template(tpl, act); err == nil {
			t.Errorf("Template(%#v): expected an error", tpl)
		}
	}
}

func TestTemplateExprs(t *testing.T) {
	tpl := map[string]any{
		"b": []any{"= two", "literal", map[string]any{"z": "= four", "a": "= three"}},
		"a": "= one",
		"c": int64(1),
	}
	got := TemplateExprs(tpl)
	want := []string{"one", "two", "three", "four"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
	if TemplateExprs("plain") != nil {
		t.Error("a literal has no expressions")
	}
}

func TestDecodeTemplate(t *testing.T) {
	cases := []struct {
		raw  string
		want any
	}{
		{"", nil},
		{"null", nil},
		{"3", int64(3)},
		{"-3", int64(-3)},
		{"3.25", 3.25},
		{`"=input"`, "=input"},
		{`{"a": [1, 2.5, {"b": 9007199254740993}]}`, map[string]any{"a": []any{int64(1), 2.5, map[string]any{"b": int64(9007199254740993)}}}},
	}
	for _, c := range cases {
		got, err := DecodeTemplate(json.RawMessage(c.raw))
		if err != nil {
			t.Errorf("%q: %v", c.raw, err)
			continue
		}
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("%q: got %#v, want %#v", c.raw, got, c.want)
		}
	}
	if _, err := DecodeTemplate(json.RawMessage(`{"a":`)); err == nil {
		t.Error("expected an error for truncated JSON")
	}
}

func TestNative(t *testing.T) {
	cases := []struct {
		name string
		in   any
		want any
	}{
		{"whole json number", json.Number("42"), int64(42)},
		{"negative whole", json.Number("-42"), int64(-42)},
		{"fraction", json.Number("4.5"), 4.5},
		{"decimal point is float", json.Number("4.0"), 4.0},
		{"exponent is float", json.Number("1e3"), 1000.0},
		{"beyond int64 is float", json.Number("99999999999999999999"), 1e20},
		{"int", 7, int64(7)},
		{"int32", int32(7), int64(7)},
		{"int64 unchanged", int64(7), int64(7)},
		{"float32", float32(0.5), 0.5},
		{"float64 unchanged", 2.0, 2.0},
		{"string", "s", "s"},
		{"nil", nil, nil},
		{"nested map and list", map[string]any{"a": []any{json.Number("1"), map[string]any{"b": 2}}},
			map[string]any{"a": []any{int64(1), map[string]any{"b": int64(2)}}}},
		{"map of maps", map[string]map[string]any{"c": {"n": json.Number("3")}},
			map[string]any{"c": map[string]any{"n": int64(3)}}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := Native(c.in)
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("Native(%#v) = %#v (%T), want %#v (%T)", c.in, got, got, c.want, c.want)
			}
		})
	}
}

func TestToNative(t *testing.T) {
	act := map[string]any{"input": map[string]any{"n": int64(2)}, "state": nil, "ctx": nil, "vars": nil,
		"attempt": int64(1), "now": int64(0), "error": nil}
	cases := []struct {
		src  string
		want any
	}{
		{"null", nil},
		{"true", true},
		{"1", int64(1)},
		{"1u", int64(1)},
		{"2.5", 2.5},
		{"'s'", "s"},
		{"b'hi'", "hi"},
		{"[1, 'a', null, [2.5]]", []any{int64(1), "a", nil, []any{2.5}}},
		{"[]", []any{}},
		{"{'a': {'b': [true]}}", map[string]any{"a": map[string]any{"b": []any{true}}}},
		{"{1: 'x'}", map[string]any{"1": "x"}},
		{"{}", map[string]any{}},
		{"timestamp('2026-01-02T03:04:05Z')", "2026-01-02T03:04:05Z"},
		{"timestamp('2026-01-02T03:04:05.5+01:00')", "2026-01-02T02:04:05.5Z"},
		{"duration('90s')", "1m30s"},
		{"input", map[string]any{"n": int64(2)}},
	}
	for _, c := range cases {
		got, err := Behavior.Eval(c.src, act)
		if err != nil {
			t.Errorf("%s: %v", c.src, err)
			continue
		}
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: got %#v (%T), want %#v", c.src, got, got, c.want)
		}
	}
}

func TestEvalBool(t *testing.T) {
	act := map[string]any{"input": map[string]any{"n": int64(2), "f": 2.0, "s": "x"}, "state": map[string]any{},
		"ctx": map[string]any{}, "vars": map[string]any{}, "attempt": int64(1), "now": int64(0), "error": nil}
	cases := []struct {
		src  string
		want bool
	}{
		{"1 < 2.5", true},
		{"2.5 > 1", true},
		{"1u < 2", true},
		{"input.n == 2.0", true},
		{"input.f == 2", true},
		{"input.n < input.f", false},
		{"'x' in ['x', 'y']", true},
		{"has(input.n) && !has(input.missing)", true},
		{"'a,b'.split(',').size() == 2", true},              // ext.Strings
		{"math.greatest(1, 3) == 3", true},                  // ext.Math
		{"[3, 1, 2].slice(1, 2) == [1]", true},              // ext.Lists
		{"base64.encode(b'hi') == 'aGk='", true},            // ext.Encoders
		{"error == null && attempt == 1 && now == 0", true}, // every behavior variable is declared
		{"size(ctx) == 0 && size(vars) == 0 && size(state) == 0", true},
	}
	for _, c := range cases {
		got, err := Behavior.EvalBool(c.src, act)
		if err != nil {
			t.Errorf("%s: %v", c.src, err)
			continue
		}
		if got != c.want {
			t.Errorf("%s = %v, want %v", c.src, got, c.want)
		}
	}
}

func TestErrors(t *testing.T) {
	act := map[string]any{"input": map[string]any{}, "state": map[string]any{}, "ctx": map[string]any{},
		"vars": map[string]any{}, "attempt": int64(1), "now": int64(0), "error": nil}
	cases := []struct {
		name, src, want string
		env             *Env
		boolean         bool
	}{
		{"empty", "  ", "empty expression", Behavior, false},
		{"syntax", "1 +", "Syntax error", Behavior, false},
		{"undeclared", "nope + 1", "undeclared reference", Behavior, false},
		{"expect has no input", "input.a", "undeclared reference", Expect, false},
		{"behavior has no result", "result.ok", "undeclared reference", Behavior, false},
		{"runtime division", "1 / 0", "1 / 0: division by zero", Behavior, false},
		{"missing key", "input.missing", "no such key", Behavior, false},
		{"not a boolean", "1 + 1", "expected a boolean, got int64", Behavior, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var err error
			if c.boolean {
				_, err = c.env.EvalBool(c.src, act)
			} else {
				_, err = c.env.Eval(c.src, act)
			}
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Errorf("got %v, want an error containing %q", err, c.want)
			}
			if err != nil && strings.Contains(err.Error(), "\n") {
				t.Errorf("compile errors are one line: %q", err)
			}
		})
	}
}

func TestExpectEnv(t *testing.T) {
	act := map[string]any{"result": map[string]any{"ok": true}, "status": "ok", "calls": map[string]any{"a.x": int64(0)},
		"ctx": map[string]any{}, "state": map[string]any{}, "retries": int64(0), "faults": int64(0),
		"duration_ms": int64(10), "warnings": []any{}}
	ok, err := Expect.EvalBool("result.ok && status == 'ok' && calls['a.x'] == 0 && retries == 0 && faults == 0 && duration_ms < 11 && size(warnings) == 0", act)
	if err != nil || !ok {
		t.Fatalf("got %v, %v", ok, err)
	}
}

func TestCompileCache(t *testing.T) {
	e := mustEnv(BehaviorVars)
	if _, err := e.Compile("1 + 1"); err != nil {
		t.Fatal(err)
	}
	if _, err := e.Compile("  1 + 1\n"); err != nil {
		t.Fatal(err)
	}
	if n := len(e.cache); n != 1 {
		t.Errorf("surrounding space shares a cache entry; cache has %d entries", n)
	}
	if _, err := e.Compile("1 +"); err == nil {
		t.Fatal("expected a compile error")
	}
	if n := len(e.cache); n != 1 {
		t.Errorf("failed compiles are not cached; cache has %d entries", n)
	}
	if _, err := e.Compile("2 + 2"); err != nil {
		t.Fatal(err)
	}
	if n := len(e.cache); n != 2 {
		t.Errorf("cache has %d entries, want 2", n)
	}
}

func TestConcurrentEval(t *testing.T) {
	done := make(chan error)
	for i := 0; i < 8; i++ {
		go func(i int) {
			act := map[string]any{"input": map[string]any{"i": int64(i)}, "state": nil, "ctx": nil, "vars": nil,
				"attempt": int64(1), "now": int64(0), "error": nil}
			v, err := Behavior.Eval("input.i * 2", act)
			if err == nil && v != int64(2*i) {
				err = &json.UnsupportedValueError{Str: "wrong value"}
			}
			done <- err
		}(i)
	}
	for i := 0; i < 8; i++ {
		if err := <-done; err != nil {
			t.Error(err)
		}
	}
}

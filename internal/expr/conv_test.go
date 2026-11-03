package expr

import "testing"

func TestWrapConversions(t *testing.T) {
	for in, want := range map[string]string{
		"string(input['x'])":               "string(dyn(input['x']))",
		"a + string(m['k']) + 'string(x)'": "a + string(dyn(m['k'])) + 'string(x)'",
		"double(int(x.y))":                 "double(dyn(int(dyn(x.y))))",
		"x.string()":                       "x.string()",
		"mystring(x)":                      "mystring(x)",
		"string()":                         "string()",
		"string(":                          "string(",
	} {
		if got := wrapConversions(in); got != want {
			t.Errorf("%q: got %q, want %q", in, got, want)
		}
	}
	act := map[string]any{"input": map[string]any{"x": int64(4), "f": 2.5, "m": map[string]any{"j": int64(5)}}}
	for src, want := range map[string]any{
		"string(input['x'])":       "4",
		"string(input.m['j'])":     "5",
		"double(input['x'])":       4.0,
		"int(input['f'])":          int64(2),
		"string(input['x']) + 'a'": "4a",
	} {
		got, err := Behavior.Eval(src, act)
		if err != nil || got != want {
			t.Errorf("%s = %v (%v), want %v", src, got, err, want)
		}
	}
}

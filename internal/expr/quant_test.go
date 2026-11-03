package expr

import "testing"

func TestCountingQuantifiers(t *testing.T) {
	act := map[string]any{"calls": []any{
		map[string]any{"interface": "lock.acquire", "ok": true},
		map[string]any{"interface": "lock.acquire", "ok": false},
		map[string]any{"interface": "db.write", "ok": true},
	}}
	cases := map[string]bool{
		"exactlyOne(calls, it.interface == 'lock.acquire' && it.ok)": true,
		"exactlyOne(calls, c, c.interface == 'lock.acquire')":        false,
		"atMostOne(calls, c, c.interface == 'db.write')":             true,
		"atMostOne(calls, it.ok)":                                    false,
		"atLeastOne(calls, it.interface == 'db.write')":              true,
		"atLeastOne(calls, it.interface == 'nope')":                  false,
		"exactlyOne([true, false, false])":                           true,
		"exactlyOne([])":                                             false,
		"atMostOne([])":                                              true,
		"exactlyOne(calls.map(c, c.ok)) == false":                    true,
	}
	for src, want := range cases {
		got, err := Expect.EvalBool(src, act)
		if err != nil {
			t.Errorf("%s: %v", src, err)
			continue
		}
		if got != want {
			t.Errorf("%s = %v, want %v", src, got, want)
		}
	}
	if _, err := Expect.Compile("exactlyOne(calls, 1, true)"); err == nil {
		t.Error("a non-name iteration variable should not compile")
	}
}

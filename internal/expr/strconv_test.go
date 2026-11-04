package expr

import "testing"

// DESIGN §17 items 17 and 19: timestampUS/timestampMS, and string() of maps
// and lists as canonical JSON.
func TestStringOfMapsListsAndTimestamps(t *testing.T) {
	act := map[string]any{"input": map[string]any{"m": map[string]any{"b": int64(1), "a": "x"}, "l": []any{int64(1), "x"}},
		"now_us": int64(1700000000000250), "now": int64(1700000000000)}
	for src, want := range map[string]any{
		"string({'b': 1, 'a': [1, 'x']})":       `{"a":[1,"x"],"b":1}`,
		"string(input.m)":                       `{"a":"x","b":1}`,
		"string(input['m'])":                    `{"a":"x","b":1}`,
		"string(input.l)":                       `[1,"x"]`,
		"string([{'z': null, 'y': 1.5}])":       `[{"y":1.5,"z":null}]`,
		"string([])":                            `[]`,
		"string(input.m) == json(input.m)":      true,
		"string(1.5)":                           "1.5", // scalars keep CEL's own
		"string('s')":                           "s",
		`eval("string({'k': [2]})", {})`:        `{"k":[2]}`,
		"string(timestampUS(now_us))":           "2023-11-14T22:13:20.00025Z",
		"string(timestampUS(1700000000000000))": "2023-11-14T22:13:20Z",
		"string(timestampMS(now + 7))":          "2023-11-14T22:13:20.007Z",
		"timestampUS(now_us) - timestampMS(now) == duration('250us')": true,
		"timestampUS(now * 1000) == timestamp(int(now / 1000))":       true,
	} {
		got, err := Behavior.Eval(src, act)
		if err != nil {
			t.Errorf("%s: %v", src, err)
			continue
		}
		if got != want {
			t.Errorf("%s = %#v, want %#v", src, got, want)
		}
	}
}

package expr

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

// DESIGN §15.3: json, jsonParse, bytes and hex.
func TestJSONHelpers(t *testing.T) {
	act := map[string]any{"input": map[string]any{"z": int64(1), "a": []any{"<&>", 1.5}}}
	for src, want := range map[string]any{
		"json(input)":                      `{"a":["<&>",1.5],"z":1}`,
		"json({'b': 1, 'a': {'d': null}})": `{"a":{"d":null},"b":1}`,
		"json('x')":                        `"x"`,
		"jsonParse('[1, {\"a\": 2.5}]')":   []any{int64(1), map[string]any{"a": 2.5}},
		"jsonParse(json(input)) == input":  true,
		"jsonParse(b'{\"k\": true}').k":    true,
		"hex(bytes('hi'))":                 "6869",
		"hex(b'\\xff\\x00')":               "ff00",
		"hex('é')":                         "c3a9",
		"size(bytes('é'))":                 int64(2),
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
	for _, src := range []string{"jsonParse('{')", "jsonParse('1 2')"} {
		if _, err := Behavior.Eval(src, act); err == nil || !strings.Contains(err.Error(), "jsonParse") {
			t.Errorf("%s: want a jsonParse error, got %v", src, err)
		}
	}
	// The eval sandbox gets them too.
	if got, err := Behavior.Eval(`eval("hex(x)", {"x": "A"})`, act); err != nil || got != "41" {
		t.Errorf("sandbox hex: %v %v", got, err)
	}
}

func TestBigInt(t *testing.T) {
	b := BigInt("123456789012345678901234567890")
	got, err := Behavior.Eval("input.n + '!'", map[string]any{"input": map[string]any{"n": b}})
	if err != nil || got != "123456789012345678901234567890!" {
		t.Errorf("CEL sees %v %v", got, err)
	}
	out, _ := json.Marshal(map[string]any{"n": b})
	if string(out) != `{"n":{"$bigint":"123456789012345678901234567890"}}` {
		t.Errorf("JSON %s", out)
	}
	// Raw bytes are CEL bytes.
	got, err = Behavior.Eval("hex(input.b) + ':' + string(size(input.b))", map[string]any{"input": map[string]any{"b": []byte{0xff, 0}}})
	if err != nil || got != "ff00:2" {
		t.Errorf("bytes %v %v", got, err)
	}
}

// behavior-language §30: integers beyond int64.
func TestNativeBigInts(t *testing.T) {
	if v := Native(json.Number("18446744073709551615")); v != uint64(18446744073709551615) {
		t.Errorf("uint64 max: %T %v", v, v)
	}
	if v := Native(json.Number("18446744073709551616")); v != float64(18446744073709551616) {
		t.Errorf("2^64: %T %v", v, v)
	}
	if v := Native(json.Number("-9223372036854775808")); v != int64(-9223372036854775808) {
		t.Errorf("int64 min: %T %v", v, v)
	}
	v, err := Behavior.Eval("input.n + 0u", map[string]any{"input": map[string]any{"n": uint64(18446744073709551615)}})
	if err != nil || v != uint64(18446744073709551615) {
		t.Errorf("uint round trip: %T %v %v", v, v, err)
	}
	if got := LossyInts([]byte(`{"a": [1, {"id": "x", "n": 18446744073709551616}], "u": 18446744073709551615, "f": 1e30}`)); len(got) != 1 || got[0] != "a[x].n=18446744073709551616" {
		t.Errorf("LossyInts %v", got)
	}
	if v := SchemaView(map[string]any{"u": uint64(1 << 63)}).(map[string]any)["u"]; v != BigInt("9223372036854775808") {
		t.Errorf("SchemaView %v", v)
	}
}

// Over the cost limit, the error names the limit and what it costs.
func TestCostError(t *testing.T) {
	_, err := Behavior.Eval("input.s.split('').map(c, c + c).size()", map[string]any{"input": map[string]any{"s": strings.Repeat("ab", 40)}, CostLimitKey: int64(50)})
	if err == nil || !strings.Contains(err.Error(), "CEL cost limit 50 exceeded; it costs ") || !IsCostLimit(err) {
		t.Errorf("err %v", err)
	}
	t.Log(err)
}

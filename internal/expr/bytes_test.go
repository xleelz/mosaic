package expr

import (
	"reflect"
	"strconv"
	"strings"
	"testing"
)

func TestByteHelpers(t *testing.T) {
	act := map[string]any{"vars": map[string]any{"s": "héllo"}}
	for src, want := range map[string]any{
		"sha256('abc')":       "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
		"sha256Bytes(b'abc')": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
		"sha256('')":          "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
		"hmacSha256('key', 'The quick brown fox jumps over the lazy dog')":       "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8",
		"hmacSha256Base64('key', 'The quick brown fox jumps over the lazy dog')": "97yD9DBThCSxMpjmqm+xQ+9NWaFJRhdZl0edvC0aPNg=",
		"hmacSha256(b'key', 'The quick brown fox jumps over the lazy dog')":      "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8",
		"byteLen(vars.s)":                    int64(6),
		"size(vars.s)":                       int64(5),
		"byteLen(b'ab')":                     int64(2),
		"substrBytes(vars.s, 0, 3)":          "hé",
		"substrBytes(vars.s, 3, 6)":          "llo",
		"substrBytes(vars.s, 2, 2)":          "",
		"byteLen(substrBytes(vars.s, 0, 2))": int64(2), // cuts inside é, as Go does
		"base64Encode('hello')":              "aGVsbG8=",
		"base64Encode(b'hi')":                "aGk=",
		"base64Decode('aGVsbG8=')":           "hello",
		"base64Decode('aGVsbG8')":            "hello",
		"fnv64a('')":                         "14695981039346656037",
		"fnv64a('a')":                        "12638187200555641996",
		"uint(fnv64a('a')) % 10u":            int64(6),
		"log2(8.0)":                          3.0,
		"log2(1024)":                         10.0,
		"ln(1.0)":                            0.0,
		"ln(1)":                              0.0,
		"eval('sha256(x)', {'x': 'abc'})":    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
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
	// A hash below 2^63 is a uint (an int64 natively).
	for i := range 64 {
		got, err := Behavior.Eval("fnv64a('key"+strconv.Itoa(i)+"')", act)
		if err != nil {
			t.Fatal(err)
		}
		if _, ok := got.(int64); ok {
			return
		}
	}
	t.Errorf("no fnv64a result fit in an int")
}

func TestByteHelperErrors(t *testing.T) {
	for _, src := range []string{
		"substrBytes('abc', 2, 1)",
		"substrBytes('abc', -1, 2)",
		"substrBytes('abc', 0, 4)",
		"base64Decode('!!')",
		"base64Decode('/w==')", // 0xff is not UTF-8
	} {
		if _, err := Behavior.Eval(src, nil); err == nil {
			t.Errorf("%s should fail", src)
		}
	}
}

func TestByteHelpersCountAgainstTheCostLimit(t *testing.T) {
	long := strings.Repeat("x", 10_000)
	act := map[string]any{"vars": map[string]any{"s": long}, CostLimitKey: int64(500)}
	if _, err := Behavior.Eval("sha256(vars.s)", act); err == nil || !strings.Contains(err.Error(), "cost") {
		t.Errorf("sha256 of 10,000 bytes under a cost limit of 500: got %v, want a cost error", err)
	}
	act[CostLimitKey] = int64(5000)
	if _, err := Behavior.Eval("sha256(vars.s)", act); err != nil {
		t.Errorf("under 5000: %v", err)
	}
	if _, err := Behavior.Eval("eval('sha256(x)', {'x': vars.s})", map[string]any{"vars": map[string]any{"s": long}, CostLimitKey: int64(500)}); err == nil {
		t.Errorf("eval of sha256 should count against the cost limit too")
	}
}

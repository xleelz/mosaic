package model

import (
	"reflect"
	"strings"
	"testing"
)

// behavior-language §30: quoted path segments.
func TestParsePath(t *testing.T) {
	ok := map[string][]string{
		"state.a.b":                 {"state", "a", "b"},
		"allocs.job-1":              {"allocs", "job-1"},
		"state['ORG#acme.v2'].plan": {"state", "ORG#acme.v2", "plan"},
		`state["ORG#acme.v2"]`:      {"state", "ORG#acme.v2"},
		"['a.b'].c":                 {"a.b", "c"},
		`state['it\'s']["q\"x"]`:    {"state", "it's", `q"x`},
		"state.['a.b']":             {"state", "a.b"},
		`vars['back\\slash'].x`:     {"vars", `back\slash`, "x"},
		"state['a]b.c']['d'].e":     {"state", "a]b.c", "d", "e"},
	}
	for in, want := range ok {
		got, err := SplitPath(in)
		if err != nil || !reflect.DeepEqual(got, want) {
			t.Errorf("SplitPath(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	for _, in := range []string{"", "a..b", "a.", ".a", "a['b'", "a[b]", "a['']", "a['b']c", "a[\"b']"} {
		if _, err := ParsePath(in); err == nil {
			t.Errorf("ParsePath(%q): no error", in)
		}
	}
	if err := checkPath("state['ORG#acme.v2'].n"); err != nil {
		t.Error(err)
	}
	if err := checkPath("state.ORG#acme"); err == nil || !strings.Contains(err.Error(), "quote a key") {
		t.Errorf("checkPath: %v", err)
	}
	if err := checkPath("['state'].x"); err == nil {
		t.Error("a quoted root passed")
	}
}

// YAML integers beyond int64 keep their digits; ones like 08 stay floats.
func TestToJSONBigInts(t *testing.T) {
	js, err := ToJSON([]byte("a: 18446744073709551616\nb: 18446744073709551615\nc: 08\nd: -18446744073709551616\ne: 0x10\n"))
	if err != nil {
		t.Fatal(err)
	}
	want := `{"a":18446744073709551616,"b":18446744073709551615,"c":8,"d":-18446744073709551616,"e":16}`
	if string(js) != want {
		t.Errorf("got %s", js)
	}
}

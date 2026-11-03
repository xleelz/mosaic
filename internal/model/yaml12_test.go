package model

import "testing"

// TestToJSONYAML12 keeps YAML 1.1 boolean words as strings.
func TestToJSONYAML12(t *testing.T) {
	got, err := ToJSON([]byte("on: off\nyes: n\nflag: true\ncount: 3\nratio: 1.5\nwhen: 2026-01-01\n"))
	if err != nil {
		t.Fatal(err)
	}
	want := `{"count":3,"flag":true,"on":"off","ratio":1.5,"when":"2026-01-01","yes":"n"}`
	if string(got) != want {
		t.Fatalf("got %s, want %s", got, want)
	}
}

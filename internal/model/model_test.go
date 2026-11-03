package model

import (
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
)

func TestDecodeRejectsUnknownFields(t *testing.T) {
	cases := []struct {
		name, kind, spec, want string
	}{
		{"component", KindComponent, `{"id": "a", "colour": "red"}`, `unknown field "colour"`},
		{"component state", KindComponent, `{"id": "a", "state": {"initial": {}, "extra": 1}}`, `unknown field "extra"`},
		{"interface", KindInterface, `{"component": "a", "name": "x", "verb": "GET"}`, `unknown field "verb"`},
		{"error spec", KindInterface, `{"component": "a", "name": "x", "errors": [{"code": "e", "http": 500}]}`, `unknown field "http"`},
		{"latency object", KindInterface, `{"component": "a", "name": "x", "latency_ms": {"min": 1, "max": 2, "p99": 3}}`, `unknown field "p99"`},
		{"behavior step", KindInterface, `{"component": "a", "name": "x", "behavior": [{"cal": "b.y"}]}`, `unknown field "cal"`},
		{"nested then step", KindInterface, `{"component": "a", "name": "x", "behavior": [{"if": "true", "then": [{"retrun": 1}]}]}`, `unknown field "retrun"`},
		{"nested option step", KindInterface, `{"component": "a", "name": "x", "behavior": [{"choice": "c", "options": {"o": [{"sett": {}}]}}]}`, `unknown field "sett"`},
		{"on_error step", KindInterface, `{"component": "a", "name": "x", "behavior": [{"call": "b.y", "on_error": [{"fial": {}}]}]}`, `unknown field "fial"`},
		{"on_error nested step", KindInterface, `{"component": "a", "name": "x", "behavior": [{"call": "b.y", "on_error": [{"if": "true", "else": [{"bogus": 1}]}]}]}`, `unknown field "bogus"`},
		{"retry", KindInterface, `{"component": "a", "name": "x", "behavior": [{"call": "b.y", "retry": {"max_attempts": 2, "jiter": "full"}}]}`, `unknown field "jiter"`},
		{"retry in on_error", KindInterface, `{"component": "a", "name": "x", "behavior": [{"call": "b.y", "on_error": [{"call": "b.z", "retry": {"tries": 2}}]}]}`, `unknown field "tries"`},
		{"step source object", KindInterface, `{"component": "a", "name": "x", "behavior": [{"title": "t", "source": {"path": "p", "col": 2}}]}`, `unknown field "col"`},
		{"link", KindLink, `{"id": "l", "from": "a", "to": "b", "weight": 1}`, `unknown field "weight"`},
		{"schema", KindSchema, `{"id": "S", "schema": {}, "title": "x"}`, `unknown field "title"`},
		{"flow entry", KindFlow, `{"id": "f", "entry": {"caller": "a", "interface": "b.y", "method": "x"}}`, `unknown field "method"`},
		{"flow step", KindFlow, `{"id": "f", "steps": [{"component": "a", "title": "t", "note": "n"}]}`, `unknown field "note"`},
		{"scenario", KindScenario, `{"id": "s", "flow": "f", "expects": []}`, `unknown field "expects"`},
		{"fault", KindScenario, `{"id": "s", "flow": "f", "faults": [{"target": "a", "type": "error", "rate": 0.5}]}`, `unknown field "rate"`},
		{"trailing data", KindComponent, `{"id": "a"} {"id": "b"}`, "unexpected data after the JSON value"},
		{"wrong type", KindComponent, `{"id": 5}`, "cannot unmarshal number"},
		{"bad on_error", KindInterface, `{"component": "a", "name": "x", "behavior": [{"call": "b.y", "on_error": 5}]}`, `on_error must be "propagate", "continue" or a list of steps`},
		{"unknown kind", "widget", `{}`, `unknown kind "widget"`},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, _, err := DecodeEntity(c.kind, []byte(c.spec))
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Errorf("got %v, want an error containing %q", err, c.want)
			}
		})
	}
	// The same documents parse from YAML strictly too.
	_, err := ParseDocument([]byte("components:\n  - id: a\ninterfaces:\n  - component: a\n    name: x\n    behavior:\n      - call: a.x\n        on_error:\n          - set: {vars.a: 1}\n            sett: {}\n"))
	if err == nil || !strings.Contains(err.Error(), `unknown field "sett"`) {
		t.Errorf("YAML: got %v", err)
	}
	if _, err := ParseDocument([]byte("componets: []")); err == nil {
		t.Error("an unknown top-level field must be rejected")
	}
	if _, err := ParseDocument([]byte("components: [\n")); err == nil || !strings.Contains(err.Error(), "invalid YAML") {
		t.Errorf("got %v", err)
	}
}

func TestSource(t *testing.T) {
	cases := []struct {
		in   string
		want Source
	}{
		{`"a/b.go"`, Source{Path: "a/b.go"}},
		{`"a/b.go:12"`, Source{Path: "a/b.go", Line: 12}},
		{`"a/b.go:12-20"`, Source{Path: "a/b.go", Line: 12, EndLine: 20}},
		{`"a/b.go:12-"`, Source{Path: "a/b.go", Line: 12}},
		{`"a/b.go:20-12"`, Source{Path: "a/b.go", Line: 20}},
		{`"a/b.go:0"`, Source{Path: "a/b.go:0"}},
		{`"a/b.go:x"`, Source{Path: "a/b.go:x"}},
		{`"a:b.go:7"`, Source{Path: "a:b.go", Line: 7}},
		{`":7"`, Source{Path: ":7"}},
		{`"https://host/x.go"`, Source{Path: "https://host/x.go"}},
		{`{"repo": "r", "path": "p.go", "line": 3, "end_line": 9, "sha": "abc"}`, Source{Repo: "r", Path: "p.go", Line: 3, EndLine: 9, SHA: "abc"}},
		{`{"path": "p.go"}`, Source{Path: "p.go"}},
	}
	for _, c := range cases {
		var s Source
		if err := json.Unmarshal([]byte(c.in), &s); err != nil {
			t.Errorf("%s: %v", c.in, err)
			continue
		}
		if s != c.want {
			t.Errorf("%s: got %+v, want %+v", c.in, s, c.want)
		}
	}
	for _, s := range []string{"p.go", "p.go:3", "p.go:3-9"} {
		if got := ParseSource(s).String(); got != s {
			t.Errorf("String round trip: %q -> %q", s, got)
		}
	}
	var s Source
	if err := json.Unmarshal([]byte(`12`), &s); err == nil {
		t.Error("a number is not a source")
	}
	// Sources decode from either form inside documents.
	d, err := ParseDocument([]byte("components:\n  - id: a\n    sources: [x.go, 'y.go:4-5', {path: z.go, line: 2}]\n"))
	if err != nil {
		t.Fatal(err)
	}
	want := []Source{{Path: "x.go"}, {Path: "y.go", Line: 4, EndLine: 5}, {Path: "z.go", Line: 2}}
	if !reflect.DeepEqual(d.Components[0].Sources, want) {
		t.Errorf("got %+v", d.Components[0].Sources)
	}
}

func TestLatency(t *testing.T) {
	cases := []struct {
		in, want string
		lat      Latency
	}{
		{`25`, `25`, Latency{Min: 25, Max: 25}},
		{`0`, `0`, Latency{Min: 0, Max: 0}},
		{`{"min": 5, "max": 9}`, `{"min":5,"max":9}`, Latency{Min: 5, Max: 9}},
		{`{"min": 4, "max": 4}`, `4`, Latency{Min: 4, Max: 4}},
		{`"= 10 + size(input.tokens)"`, `"= 10 + size(input.tokens)"`, Latency{Expr: " 10 + size(input.tokens)"}},
	}
	for _, c := range cases {
		var l Latency
		if err := json.Unmarshal([]byte(c.in), &l); err != nil {
			t.Errorf("%s: %v", c.in, err)
			continue
		}
		if l != c.lat {
			t.Errorf("%s: got %+v", c.in, l)
		}
		b, _ := json.Marshal(l)
		if string(b) != c.want {
			t.Errorf("%s: marshals as %s, want %s", c.in, b, c.want)
		}
	}
	for _, bad := range []string{`{"min": 1, "max": 2, "avg": 1}`, `"fast"`, `[1]`} {
		var l Latency
		if err := json.Unmarshal([]byte(bad), &l); err == nil {
			t.Errorf("%s: expected an error", bad)
		}
	}
}

func TestOnError(t *testing.T) {
	cases := []struct {
		in    string
		mode  string
		steps int
	}{
		{`"propagate"`, "propagate", 0},
		{`"continue"`, "continue", 0},
		{`[{"title": "a"}, {"return": 1}]`, "", 2},
		{`[]`, "", 0},
	}
	for _, c := range cases {
		var o OnError
		if err := json.Unmarshal([]byte(c.in), &o); err != nil {
			t.Errorf("%s: %v", c.in, err)
			continue
		}
		if o.Mode != c.mode || len(o.Steps) != c.steps {
			t.Errorf("%s: got %+v", c.in, o)
		}
		b, _ := json.Marshal(o)
		var back OnError
		if err := json.Unmarshal(b, &back); err != nil || back.Mode != o.Mode || len(back.Steps) != len(o.Steps) {
			t.Errorf("%s: round trip gave %s -> %+v, %v", c.in, b, back, err)
		}
	}
}

func TestInterfaceNormalize(t *testing.T) {
	cases := []struct {
		name string
		in   Interface
		want Interface
	}{
		{"from component and name", Interface{Component: "svc", Name: "get"}, Interface{ID: "svc.get", Component: "svc", Name: "get"}},
		{"from id", Interface{ID: "svc.get"}, Interface{ID: "svc.get", Component: "svc", Name: "get"}},
		{"id splits at the first dot", Interface{ID: "svc.get.v2"}, Interface{ID: "svc.get.v2", Component: "svc", Name: "get.v2"}},
		{"explicit id kept", Interface{ID: "x.y", Component: "svc", Name: "get"}, Interface{ID: "x.y", Component: "svc", Name: "get"}},
		{"partial fields untouched", Interface{ID: "svc.get", Component: "other"}, Interface{ID: "svc.get", Component: "other"}},
		{"id without dot", Interface{ID: "svc"}, Interface{ID: "svc"}},
	}
	for _, c := range cases {
		got := c.in
		got.Normalize()
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: got %+v, want %+v", c.name, got, c.want)
		}
	}
	for _, spec := range []string{`{"id": "svc.get"}`, `{"component": "svc", "name": "get"}`} {
		v, id, err := DecodeEntity(KindInterface, []byte(spec))
		if err != nil || id != "svc.get" {
			t.Fatalf("%s: %v %q", spec, err, id)
		}
		if f := v.(Interface); f.Component != "svc" || f.Name != "get" || f.ID != "svc.get" {
			t.Errorf("%s: got %+v", spec, f)
		}
	}
	d, err := ParseDocument([]byte("interfaces: [{id: a.x}, {component: b, name: get}]"))
	if err != nil {
		t.Fatal(err)
	}
	if d.Interfaces[0].Component != "a" || d.Interfaces[1].ID != "b.get" {
		t.Errorf("ParseDocument does not normalize: %+v", d.Interfaces)
	}
}

func TestJSONNumberPreservation(t *testing.T) {
	spec := `{"id": "a", "attributes": {"big": 12345678901234567890, "pi": 3.14159265358979323846, "n": 7},
		"state": {"initial": {"count": 9007199254740993}}}`
	v, _, err := DecodeEntity(KindComponent, []byte(spec))
	if err != nil {
		t.Fatal(err)
	}
	c := v.(Component)
	for k, want := range map[string]string{"big": "12345678901234567890", "pi": "3.14159265358979323846", "n": "7"} {
		n, ok := c.Attributes[k].(json.Number)
		if !ok || string(n) != want {
			t.Errorf("attributes.%s = %#v, want json.Number(%s)", k, c.Attributes[k], want)
		}
	}
	if n := c.State.Initial["count"].(json.Number); n != "9007199254740993" {
		t.Errorf("state.initial.count = %s", n)
	}
	b, _ := json.Marshal(c)
	if !strings.Contains(string(b), "12345678901234567890") || !strings.Contains(string(b), "9007199254740993") {
		t.Errorf("re-encoding loses precision: %s", b)
	}
	// Behavior templates keep numbers too.
	v, _, err = DecodeEntity(KindInterface, []byte(`{"component": "a", "name": "x", "behavior": [{"set": {"vars.n": 1.50}}, {"wait": 10}, {"call": "a.y", "retry": {"max_attempts": 3}}]}`))
	if err != nil {
		t.Fatal(err)
	}
	f := v.(Interface)
	if f.Behavior[0].Set["vars.n"] != json.Number("1.50") || f.Behavior[1].Wait != json.Number("10") || f.Behavior[2].Retry.MaxAttempts != json.Number("3") {
		t.Errorf("numbers: %#v %#v %#v", f.Behavior[0].Set, f.Behavior[1].Wait, f.Behavior[2].Retry.MaxAttempts)
	}
}

func TestStepActions(t *testing.T) {
	cases := []struct {
		step string
		want []string
	}{
		{`{"title": "t"}`, nil},
		{`{"set": {}}`, []string{"set"}},
		{`{"call": "a.x"}`, []string{"call"}},
		{`{"if": "true"}`, []string{"if"}},
		{`{"choice": "c"}`, []string{"choice"}},
		{`{"return": null}`, []string{"return"}},
		{`{"fail": "x"}`, []string{"fail"}},
		{`{"emit": "a.x"}`, []string{"emit"}},
		{`{"wait": 0}`, []string{"wait"}},
		{`{"set": {"vars.a": 1}, "call": "a.x", "return": 1}`, []string{"set", "call", "return"}},
	}
	for _, c := range cases {
		var s Step
		if err := Decode([]byte(c.step), &s); err != nil {
			t.Fatal(err)
		}
		if got := s.Actions(); !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: got %v, want %v", c.step, got, c.want)
		}
	}
}

func TestKindsAndIDs(t *testing.T) {
	for _, k := range Kinds {
		if got, ok := KindOf(k); !ok || got != k {
			t.Errorf("KindOf(%q) = %q, %v", k, got, ok)
		}
		if got, ok := KindOf(Plural(k)); !ok || got != k {
			t.Errorf("KindOf(%q) = %q, %v", Plural(k), got, ok)
		}
	}
	if _, ok := KindOf("widgets"); ok {
		t.Error("widgets is not a kind")
	}
	ids := map[string]bool{
		"a": true, "0": true, "a-b_c9": true, strings.Repeat("a", 64): true,
		"": false, "A": false, "-a": false, "_a": false, "a.b": false, "a b": false, strings.Repeat("a", 65): false, "é": false,
	}
	for id, want := range ids {
		if ValidID(id) != want {
			t.Errorf("ValidID(%q) = %v", id, !want)
		}
	}
	idents := map[string]bool{"a": true, "_x": true, "camelCase9": true, "": false, "9a": false, "a-b": false, "a.b": false}
	for id, want := range idents {
		if ValidIdent(id) != want {
			t.Errorf("ValidIdent(%q) = %v", id, !want)
		}
	}
}

func TestEntitiesRoundTrip(t *testing.T) {
	data, err := os.ReadFile("../testdata/gateway/ontology.yaml")
	if err != nil {
		t.Fatal(err)
	}
	doc, err := ParseDocument(data)
	if err != nil {
		t.Fatal(err)
	}
	ents, err := doc.Entities()
	if err != nil {
		t.Fatal(err)
	}
	// Shuffle (reverse) to check that FromEntities sorts, and keep a copy to
	// check that it does not reorder the caller's slice.
	for i, j := 0, len(ents)-1; i < j; i, j = i+1, j-1 {
		ents[i], ents[j] = ents[j], ents[i]
	}
	before := append([]Entity(nil), ents...)
	back, issues := FromEntities(ents)
	if len(issues) > 0 {
		t.Fatalf("issues: %v", issues)
	}
	if !reflect.DeepEqual(before, ents) {
		t.Error("FromEntities reordered its argument")
	}
	ents2, err := back.Entities()
	if err != nil {
		t.Fatal(err)
	}
	byKey := func(es []Entity) map[string]string {
		m := map[string]string{}
		for _, e := range es {
			m[e.Kind+"/"+e.ID] = string(e.Spec)
		}
		return m
	}
	if !reflect.DeepEqual(byKey(before), byKey(ents2)) {
		t.Error("entities differ after a round trip")
	}
	if back.Components[0].ID > back.Components[1].ID {
		t.Error("components are not sorted by id")
	}
	if HasErrors(Validate(back)) {
		t.Error("the round-tripped document is invalid")
	}
	// A spec that does not decode is reported, not dropped silently.
	_, issues = FromEntities([]Entity{{Kind: KindComponent, ID: "a", Spec: json.RawMessage(`{"id": "a", "zzz": 1}`)}})
	if len(issues) != 1 || issues[0].Path != "components[a]" || issues[0].Severity != SeverityError {
		t.Errorf("got %+v", issues)
	}
	// An empty document encodes empty lists, not null.
	empty, _ := FromEntities(nil)
	b, _ := json.Marshal(empty)
	if strings.Contains(string(b), "null") {
		t.Errorf("got %s", b)
	}
}

func TestParseDocumentJSONAndDefaults(t *testing.T) {
	d, err := ParseDocument([]byte(`  {"components": [{"id": "a"}]}`))
	if err != nil {
		t.Fatal(err)
	}
	if d.SchemaVersion != SchemaVersion || len(d.Components) != 1 || d.Flows == nil || d.Scenarios == nil {
		t.Errorf("got %+v", d)
	}
	b, err := ToJSON([]byte("a: 1\nb: [x, 2.5]\n"))
	if err != nil || string(b) != `{"a":1,"b":["x",2.5]}` {
		t.Errorf("ToJSON: %s %v", b, err)
	}
}

func TestResolveSchema(t *testing.T) {
	d, err := ParseDocument([]byte(`
schemas:
  - {id: A, schema: {type: string}}
  - {id: B, schema: {$ref: A}}
  - {id: Loop, schema: {$ref: Loop}}
`))
	if err != nil {
		t.Fatal(err)
	}
	x := NewIndex(d)
	str := map[string]any{"type": "string"}
	cases := []struct {
		ref  any
		want map[string]any
		ok   bool
	}{
		{"A", str, true},
		{"#/schemas/A", str, true},
		{"B", str, true},
		{map[string]any{"$ref": "B"}, str, true},
		{map[string]any{"$ref": "A", "description": "kept"}, map[string]any{"$ref": "A", "description": "kept"}, true},
		{map[string]any{"type": "integer"}, map[string]any{"type": "integer"}, true},
		{"Nope", nil, false},
		{"Loop", nil, false},
		{nil, nil, false},
		{int64(3), nil, false},
	}
	for _, c := range cases {
		got, ok := x.ResolveSchema(c.ref)
		if ok != c.ok || !reflect.DeepEqual(got, c.want) {
			t.Errorf("ResolveSchema(%#v) = %v, %v", c.ref, got, ok)
		}
	}
}

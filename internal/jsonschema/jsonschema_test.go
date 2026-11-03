package jsonschema

import (
	"encoding/json"
	"math/rand/v2"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"
)

// schema decodes an inline JSON schema the way the model does (json.Number).
func schema(t *testing.T, js string) map[string]any {
	t.Helper()
	dec := json.NewDecoder(strings.NewReader(js))
	dec.UseNumber()
	var m map[string]any
	if err := dec.Decode(&m); err != nil {
		t.Fatalf("bad schema %s: %v", js, err)
	}
	return m
}

func gen(seed uint64, resolve Resolver) *Generator {
	return &Generator{Rng: rand.New(rand.NewPCG(seed, 7)), Resolve: resolve}
}

func TestGenerateDeterminism(t *testing.T) {
	s := schema(t, `{"type": "object", "properties": {
		"id": {"type": "string", "format": "uuid"},
		"n": {"type": "integer"},
		"f": {"type": "number"},
		"tags": {"type": "array", "items": {"type": "string"}},
		"ok": {"type": "boolean"}}}`)
	a := gen(42, nil).Generate(s)
	b := gen(42, nil).Generate(s)
	if !reflect.DeepEqual(a, b) {
		t.Errorf("same seed differs:\n%v\n%v", a, b)
	}
	c := gen(43, nil).Generate(s)
	if reflect.DeepEqual(a, c) {
		t.Errorf("different seeds give the same value %v", a)
	}
}

func TestGeneratePrecedence(t *testing.T) {
	cases := []struct {
		name, schema string
		want         any
	}{
		{"const beats all", `{"type": "integer", "const": 1, "default": 2, "examples": [3], "enum": [4]}`, int64(1)},
		{"default beats examples", `{"type": "integer", "default": 2, "examples": [3], "enum": [4]}`, int64(2)},
		{"examples beat enum", `{"type": "integer", "examples": [3], "enum": [4]}`, int64(3)},
		{"enum beats type", `{"type": "integer", "enum": [4]}`, int64(4)},
		{"const null", `{"const": null, "type": "string"}`, nil},
		{"default object", `{"type": "object", "default": {"a": 1.5}}`, map[string]any{"a": 1.5}},
		{"oneOf takes the first branch", `{"oneOf": [{"const": "first"}, {"const": "second"}]}`, "first"},
		{"anyOf takes the first branch", `{"anyOf": [{"const": 5}, {"const": 6}]}`, int64(5)},
		{"type list skips null", `{"type": ["null", "integer"], "minimum": 9, "maximum": 9}`, int64(9)},
		{"null type", `{"type": "null"}`, nil},
		{"no type", `{}`, nil},
		{"inferred object", `{"properties": {"a": {"const": true}}}`, map[string]any{"a": true}},
		{"inferred array", `{"items": {"const": 1}, "minItems": 2, "maxItems": 2}`, []any{int64(1), int64(1)}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := gen(1, nil).Generate(schema(t, c.schema))
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("got %#v, want %#v", got, c.want)
			}
		})
	}
	if gen(1, nil).Generate(nil) != nil {
		t.Error("a nil schema yields nil")
	}
	// examples and enum values come from their lists.
	for seed := uint64(0); seed < 20; seed++ {
		v := gen(seed, nil).Generate(schema(t, `{"type": "string", "examples": ["a", "b", "c"]}`))
		if v != "a" && v != "b" && v != "c" {
			t.Fatalf("seed %d: %v is not an example", seed, v)
		}
		v = gen(seed, nil).Generate(schema(t, `{"enum": ["x", 2]}`))
		if v != "x" && v != int64(2) {
			t.Fatalf("seed %d: %v is not an enum value", seed, v)
		}
	}
}

var (
	uuidRE  = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-a[0-9a-f]{3}-[0-9a-f]{12}$`)
	emailRE = regexp.MustCompile(`^[a-z]+\.[a-z]+@example\.com$`)
)

func TestGenerateFormatsAndNames(t *testing.T) {
	isDateTime := func(s string) bool { _, err := time.Parse(time.RFC3339, s); return err == nil }
	isDate := func(s string) bool { _, err := time.Parse("2006-01-02", s); return err == nil }
	cases := []struct {
		name, schema string
		ok           func(string) bool
	}{
		{"uuid format", `{"properties": {"x": {"type": "string", "format": "uuid"}}}`, uuidRE.MatchString},
		{"uuid hint", `{"properties": {"x": {"type": "string", "x-fake": "uuid"}}}`, uuidRE.MatchString},
		{"email format", `{"properties": {"x": {"type": "string", "format": "email"}}}`, emailRE.MatchString},
		{"email name", `{"properties": {"contact_email": {"type": "string"}}}`, emailRE.MatchString},
		{"date-time format", `{"properties": {"x": {"type": "string", "format": "date-time"}}}`, isDateTime},
		{"_at name", `{"properties": {"created_at": {"type": "string"}}}`, isDateTime},
		{"date format", `{"properties": {"x": {"type": "string", "format": "date"}}}`, isDate},
		{"uri format", `{"properties": {"x": {"type": "string", "format": "uri"}}}`, func(s string) bool { return strings.HasPrefix(s, "https://example.com/") }},
		{"url name", `{"properties": {"url": {"type": "string"}}}`, func(s string) bool { return strings.HasPrefix(s, "https://example.com/") }},
		{"name", `{"properties": {"name": {"type": "string"}}}`, regexp.MustCompile(`^[A-Z][a-z]+ [A-Z][a-z]+$`).MatchString},
		{"_name", `{"properties": {"display_name": {"type": "string"}}}`, regexp.MustCompile(`^[A-Z][a-z]+ [A-Z][a-z]+$`).MatchString},
		{"id", `{"properties": {"id": {"type": "string"}}}`, regexp.MustCompile(`^id_[0-9a-f]{8}$`).MatchString},
		{"_id", `{"properties": {"org_id": {"type": "string"}}}`, regexp.MustCompile(`^org_[0-9a-f]{8}$`).MatchString},
		{"key", `{"properties": {"api_key": {"type": "string"}}}`, regexp.MustCompile(`^key_[0-9a-f]{16}$`).MatchString},
		{"model", `{"properties": {"model": {"type": "string"}}}`, func(s string) bool { return strings.HasPrefix(s, "model-") }},
		{"message", `{"properties": {"message": {"type": "string"}}}`, regexp.MustCompile(`^[A-Z][a-z]+( [a-z]+){2,7}\.$`).MatchString},
		{"default words", `{"properties": {"color": {"type": "string"}}}`, regexp.MustCompile(`^[a-z]+-[a-z]+$`).MatchString},
		{"minLength pads", `{"properties": {"x": {"type": "string", "minLength": 40}}}`, func(s string) bool { return len(s) >= 40 }},
		{"maxLength cuts", `{"properties": {"x": {"type": "string", "format": "uuid", "maxLength": 5}}}`, func(s string) bool { return len(s) == 5 }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			for seed := uint64(0); seed < 10; seed++ {
				out := gen(seed, nil).Generate(schema(t, c.schema)).(map[string]any)
				for _, v := range out {
					s, ok := v.(string)
					if !ok || !c.ok(s) {
						t.Fatalf("seed %d: unexpected value %#v", seed, v)
					}
				}
			}
		})
	}
}

func TestGenerateBounds(t *testing.T) {
	cases := []struct {
		name, schema string
		lo, hi       float64
		integer      bool
	}{
		{"integer bounds", `{"type": "integer", "minimum": 5, "maximum": 7}`, 5, 7, true},
		{"integer default range", `{"type": "integer"}`, 0, 1000, true},
		{"integer minimum only", `{"type": "integer", "minimum": 5000}`, 5000, 6000, true},
		{"integer maximum only", `{"type": "integer", "maximum": -5}`, -5, -5, true},
		{"fractional integer bounds", `{"type": "integer", "minimum": 0.5, "maximum": 2.5}`, 1, 2, true},
		{"huge integer range", `{"type": "integer", "minimum": -1e19, "maximum": 1e19}`, -1e19, 1e19, true},
		{"count heuristic", `{"properties": {"retry_count": {"type": "integer"}}}`, 1, 10, true},
		{"cents heuristic", `{"properties": {"amount_cents": {"type": "integer"}}}`, 1, 10000, true},
		{"token heuristic", `{"properties": {"tokens_out": {"type": "integer", "maximum": 64}}}`, 1, 64, true},
		{"number bounds", `{"type": "number", "minimum": 1.5, "maximum": 2.5}`, 1.5, 2.5, false},
		{"tiny number range", `{"type": "number", "minimum": 0.001, "maximum": 0.002}`, 0.001, 0.002, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			s := schema(t, c.schema)
			for seed := uint64(0); seed < 50; seed++ {
				v := gen(seed, nil).Generate(s)
				if m, ok := v.(map[string]any); ok {
					for _, x := range m {
						v = x
					}
				}
				var f float64
				switch n := v.(type) {
				case int64:
					if !c.integer {
						t.Fatalf("got integer %d for a number", n)
					}
					f = float64(n)
				case float64:
					if c.integer {
						t.Fatalf("got float %v for an integer", n)
					}
					f = n
				default:
					t.Fatalf("got %T", v)
				}
				if f < c.lo || f > c.hi {
					t.Fatalf("seed %d: %v outside [%v, %v]", seed, v, c.lo, c.hi)
				}
			}
		})
	}
}

func TestGenerateArrays(t *testing.T) {
	cases := []struct {
		name, schema string
		lo, hi       int
	}{
		{"default length", `{"type": "array", "items": {"type": "string"}}`, 1, 3},
		{"min and max", `{"type": "array", "minItems": 2, "maxItems": 3, "items": {"type": "string"}}`, 2, 3},
		{"max capped at min+4", `{"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "string"}}`, 1, 5},
		{"max below min", `{"type": "array", "minItems": 3, "maxItems": 1, "items": {"type": "string"}}`, 3, 3},
		{"maxItems 0", `{"type": "array", "maxItems": 0, "items": {"type": "string"}}`, 0, 0},
		{"negative minItems", `{"type": "array", "minItems": -2, "items": {"type": "string"}}`, 0, 2},
		{"no items schema", `{"type": "array", "minItems": 2, "maxItems": 2}`, 2, 2},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			for seed := uint64(0); seed < 30; seed++ {
				v, ok := gen(seed, nil).Generate(schema(t, c.schema)).([]any)
				if !ok {
					t.Fatalf("not an array")
				}
				if len(v) < c.lo || len(v) > c.hi {
					t.Fatalf("seed %d: length %d outside [%d, %d]", seed, len(v), c.lo, c.hi)
				}
			}
		})
	}
	// Array items use the singular of the property name for heuristics.
	v := gen(1, nil).Generate(schema(t, `{"properties": {"emails": {"type": "array", "items": {"type": "string"}}}}`))
	for _, e := range v.(map[string]any)["emails"].([]any) {
		if !emailRE.MatchString(e.(string)) {
			t.Errorf("item %v of emails is not an email", e)
		}
	}
}

func TestGenerateRefsAndAllOf(t *testing.T) {
	defs := map[string]map[string]any{
		"Money": schema(t, `{"type": "object", "required": ["cents"], "properties": {"cents": {"type": "integer", "minimum": 1, "maximum": 1}}}`),
		"Order": schema(t, `{"type": "object", "properties": {"total": {"$ref": "Money"}, "lines": {"type": "array", "minItems": 1, "maxItems": 1, "items": {"$ref": "Money"}}}}`),
		"Loop":  schema(t, `{"type": "object", "properties": {"next": {"$ref": "Loop"}}}`),
	}
	resolve := func(ref string) (map[string]any, bool) {
		s, ok := defs[strings.TrimPrefix(ref, "#/schemas/")]
		return s, ok
	}
	money := map[string]any{"cents": int64(1)}
	cases := []struct {
		name, schema string
		want         any
	}{
		{"nested ref", `{"$ref": "Order"}`, map[string]any{"total": money, "lines": []any{money}}},
		{"pointer ref", `{"$ref": "#/schemas/Money"}`, money},
		{"unresolved ref", `{"$ref": "Nope"}`, nil},
		{"allOf merges objects", `{"allOf": [{"$ref": "Money"}, {"properties": {"currency": {"const": "EUR"}}}]}`,
			map[string]any{"cents": int64(1), "currency": "EUR"}},
		{"allOf of non-objects keeps the first value", `{"allOf": [{"const": "x"}, {"minLength": 1}]}`, "x"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := gen(1, resolve).Generate(schema(t, c.schema))
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("got %#v, want %#v", got, c.want)
			}
		})
	}
	// A recursive schema terminates at the depth limit.
	v := gen(1, resolve).Generate(defs["Loop"])
	depth := 0
	for m, ok := v.(map[string]any); ok; m, ok = m["next"].(map[string]any) {
		depth++
	}
	if depth == 0 || depth > maxDepth+1 {
		t.Errorf("recursion depth %d", depth)
	}
	// Without a resolver a $ref yields nil.
	if v := gen(1, nil).Generate(schema(t, `{"$ref": "Money"}`)); v != nil {
		t.Errorf("got %v without a resolver", v)
	}
}

// Generated data must satisfy its own schema, for every seed.
func TestGeneratedValuesValidate(t *testing.T) {
	s := schema(t, `{"type": "object", "required": ["id", "items", "status"], "properties": {
		"id": {"type": "string", "format": "uuid"},
		"status": {"type": "string", "enum": ["open", "closed"]},
		"score": {"type": "number", "minimum": 0, "maximum": 1},
		"count": {"type": "integer", "minimum": 3, "maximum": 9},
		"label": {"type": "string", "minLength": 3, "maxLength": 8},
		"items": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "object", "properties": {"sku": {"type": "string"}, "qty": {"type": "integer", "minimum": 1}}}},
		"maybe": {"type": ["string", "null"]},
		"flag": {"type": "boolean"}}}`)
	for seed := uint64(0); seed < 100; seed++ {
		v := gen(seed, nil).Generate(s)
		if msgs := Validate(s, v, nil); len(msgs) > 0 {
			t.Fatalf("seed %d: %v for %v", seed, msgs, v)
		}
	}
}

func TestValidate(t *testing.T) {
	defs := map[string]map[string]any{"Pos": schema(t, `{"type": "integer", "minimum": 1}`)}
	resolve := func(ref string) (map[string]any, bool) { s, ok := defs[ref]; return s, ok }
	cases := []struct {
		name, schema, value string
		want                []string
	}{
		{"valid", `{"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}`, `{"a": "x", "extra": 1}`, nil},
		{"type", `{"type": "string"}`, `5`, []string{"$: expected string, got integer"}},
		{"type list", `{"type": ["string", "null"]}`, `true`, []string{"$: expected [string null], got boolean"}},
		{"null allowed", `{"type": ["string", "null"]}`, `null`, nil},
		{"integer accepts whole float", `{"type": "integer"}`, `2.0`, nil},
		{"integer rejects fraction", `{"type": "integer"}`, `2.5`, []string{"$: expected integer, got number"}},
		{"number accepts integer", `{"type": "number"}`, `2`, nil},
		{"required", `{"type": "object", "required": ["a", "b"]}`, `{"a": 1}`, []string{`$: missing required property "b"`}},
		{"nested property", `{"properties": {"a": {"properties": {"b": {"type": "boolean"}}}}}`, `{"a": {"b": "no"}}`, []string{"$.a.b: expected boolean, got string"}},
		{"enum", `{"enum": ["x", 1]}`, `"y"`, []string{"$: y is not one of the allowed values"}},
		{"enum numeric equality", `{"enum": [1]}`, `1.0`, nil},
		{"const", `{"const": "x"}`, `"y"`, []string{"$: must equal x"}},
		{"minimum", `{"type": "integer", "minimum": 3}`, `2`, []string{"$: 2 is below the minimum 3"}},
		{"maximum", `{"type": "number", "maximum": 3}`, `3.5`, []string{"$: 3.5 is above the maximum 3"}},
		{"minLength", `{"type": "string", "minLength": 3}`, `"ab"`, []string{"$: shorter than 3"}},
		{"maxLength counts runes", `{"type": "string", "maxLength": 2}`, `"héé"`, []string{"$: longer than 2"}},
		{"minItems", `{"type": "array", "minItems": 2}`, `[1]`, []string{"$: needs at least 2 items"}},
		{"maxItems", `{"type": "array", "maxItems": 1}`, `[1, 2]`, []string{"$: allows at most 1 items"}},
		{"items", `{"type": "array", "items": {"type": "integer"}}`, `[1, "x", 3, false]`,
			[]string{"$[1]: expected integer, got string", "$[3]: expected integer, got boolean"}},
		{"ref", `{"properties": {"n": {"$ref": "Pos"}}}`, `{"n": 0}`, []string{"$.n: 0 is below the minimum 1"}},
		{"unresolved ref", `{"$ref": "Nope"}`, `1`, []string{`$: unresolved $ref "Nope"`}},
		{"oneOf matches", `{"oneOf": [{"type": "string"}, {"type": "integer"}]}`, `1`, nil},
		{"oneOf none", `{"oneOf": [{"type": "string"}, {"type": "integer"}]}`, `true`, []string{"$: matches none of oneOf"}},
		{"anyOf none", `{"anyOf": [{"type": "string"}]}`, `1`, []string{"$: matches none of anyOf"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var v any
			dec := json.NewDecoder(strings.NewReader(c.value))
			dec.UseNumber()
			if err := dec.Decode(&v); err != nil {
				t.Fatal(err)
			}
			got := Validate(schema(t, c.schema), v, resolve)
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("got %q, want %q", got, c.want)
			}
		})
	}
	if got := Validate(nil, 1, nil); got != nil {
		t.Errorf("a nil schema accepts everything, got %v", got)
	}
	// Go values (ints, nested maps) are normalized before checking.
	if got := Validate(schema(t, `{"properties": {"n": {"type": "integer", "maximum": 3}}}`), map[string]any{"n": 2}, nil); got != nil {
		t.Errorf("got %v", got)
	}
}

func TestValidateTruncates(t *testing.T) {
	items := make([]any, 25)
	for i := range items {
		items[i] = "x"
	}
	got := Validate(map[string]any{"items": map[string]any{"type": "integer"}}, items, nil)
	if len(got) != 21 || got[20] != "and 5 more" {
		t.Errorf("got %d messages, last %q", len(got), got[len(got)-1])
	}
}

func TestTypeOf(t *testing.T) {
	cases := []struct {
		schema string
		want   string
	}{
		{`{"type": "string"}`, "string"},
		{`{"type": ["null", "number"]}`, "number"},
		{`{"type": ["null"]}`, "null"},
		{`{"properties": {}}`, "object"},
		{`{"items": {}}`, "array"},
		{`{}`, ""},
	}
	for _, c := range cases {
		if got := TypeOf(schema(t, c.schema)); got != c.want {
			t.Errorf("TypeOf(%s) = %q, want %q", c.schema, got, c.want)
		}
	}
}

// Package jsonschema generates deterministic fake data from a JSON Schema
// subset and checks values against it. The subset is: type, properties,
// required, items, enum, const, format, minimum, maximum, minLength,
// maxLength, minItems, maxItems, default, examples, oneOf, anyOf, allOf,
// $ref and the x-fake hint.
package jsonschema

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"math/rand/v2"
	"reflect"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/xleelz/mosaic/internal/expr"
)

// Resolver resolves a "$ref" value to a schema.
type Resolver func(ref string) (map[string]any, bool)

// Generator produces fake values. It is deterministic for a given RNG state.
type Generator struct {
	Rng     *rand.Rand
	Resolve Resolver
}

const maxDepth = 8

var words = []string{"alpha", "amber", "atlas", "beacon", "cedar", "comet", "delta", "ember", "falcon", "fjord",
	"garnet", "harbor", "indigo", "juniper", "kestrel", "lumen", "maple", "nimbus", "onyx", "orbit", "pixel",
	"quartz", "raven", "sable", "summit", "tango", "umber", "vector", "willow", "zephyr"}

var firstNames = []string{"Ada", "Grace", "Alan", "Linus", "Margaret", "Ken", "Barbara", "Dennis", "Radia", "Edsger"}
var lastNames = []string{"Lovelace", "Hopper", "Turing", "Torvalds", "Hamilton", "Thompson", "Liskov", "Ritchie", "Perlman", "Dijkstra"}

var epoch = time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

// Generate returns a fake value for schema. A nil schema yields nil.
func (g *Generator) Generate(schema map[string]any) any { return g.gen(schema, "", 0) }

func (g *Generator) gen(s map[string]any, name string, depth int) any {
	if s == nil || depth > maxDepth {
		return nil
	}
	if r, ok := s["$ref"].(string); ok {
		if g.Resolve != nil {
			if t, ok := g.Resolve(r); ok {
				return g.gen(t, name, depth+1)
			}
		}
		return nil
	}
	if v, ok := s["const"]; ok {
		return expr.Native(v)
	}
	if v, ok := s["default"]; ok {
		return expr.Native(v)
	}
	if ex, ok := s["examples"].([]any); ok && len(ex) > 0 {
		return expr.Native(ex[g.Rng.IntN(len(ex))])
	}
	if en, ok := s["enum"].([]any); ok && len(en) > 0 {
		return expr.Native(en[g.Rng.IntN(len(en))])
	}
	for _, k := range []string{"oneOf", "anyOf"} {
		if br, ok := s[k].([]any); ok && len(br) > 0 {
			if m, ok := br[0].(map[string]any); ok {
				return g.gen(m, name, depth+1)
			}
		}
	}
	if all, ok := s["allOf"].([]any); ok && len(all) > 0 {
		merged := map[string]any{}
		var first any
		objects, seen := false, false
		for _, b := range all {
			if m, ok := b.(map[string]any); ok {
				v := g.gen(m, name, depth+1)
				if !seen {
					first, seen = v, true
				}
				if mv, ok := v.(map[string]any); ok {
					objects = true
					for k, x := range mv {
						merged[k] = x
					}
				}
			}
		}
		if !objects && seen {
			// Non-object branches (allOf: [{type: string}, ...]) keep the
			// first branch's value rather than collapsing to {}.
			return first
		}
		return merged
	}
	switch TypeOf(s) {
	case "object":
		props, _ := s["properties"].(map[string]any)
		out := map[string]any{}
		for _, k := range sortedKeys(props) {
			if ps, ok := props[k].(map[string]any); ok {
				out[k] = g.gen(ps, k, depth+1)
			}
		}
		return out
	case "array":
		items, _ := s["items"].(map[string]any)
		lo := intOr(s["minItems"], 1)
		if _, ok := s["minItems"]; !ok {
			if mx, ok := num(s["maxItems"]); ok && int(mx) < lo {
				lo = int(mx) // maxItems: 0 means an empty array
			}
		}
		lo = max(lo, 0)
		hi := intOr(s["maxItems"], lo+2)
		if hi > lo+4 {
			hi = lo + 4
		}
		if hi < lo {
			hi = lo
		}
		n := lo + g.Rng.IntN(hi-lo+1)
		out := make([]any, n)
		for i := range out {
			out[i] = g.gen(items, singular(name), depth+1)
		}
		return out
	case "string":
		return g.str(s, name)
	case "integer":
		lo, hi := g.bounds(s, name)
		// Integral bounds, clamped so that hi-lo+1 fits in an int64.
		const limit = 1 << 61
		lo = max(min(math.Ceil(lo), limit), -limit)
		hi = max(min(math.Floor(hi), limit), lo)
		return int64(lo) + g.Rng.Int64N(int64(hi)-int64(lo)+1)
	case "number":
		lo, hi := g.bounds(s, name)
		// Rounding to cents must not leave the bounds.
		return max(min(math.Round((lo+g.Rng.Float64()*(hi-lo))*100)/100, hi), lo)
	case "boolean":
		return g.Rng.IntN(2) == 1
	}
	return nil
}

func (g *Generator) bounds(s map[string]any, name string) (float64, float64) {
	lo, hi := 0.0, 1000.0
	n := strings.ToLower(name)
	switch {
	case strings.Contains(n, "count") || strings.Contains(n, "attempt"):
		lo, hi = 1, 10
	case strings.Contains(n, "cents") || strings.Contains(n, "amount"):
		lo, hi = 1, 10000
	case strings.Contains(n, "token"):
		lo, hi = 1, 4096
	}
	if v, ok := num(s["minimum"]); ok {
		lo = v
		if hi < lo {
			hi = lo + 1000
		}
	}
	if v, ok := num(s["maximum"]); ok {
		hi = v
		if lo > hi {
			lo = hi
		}
	}
	return lo, hi
}

func (g *Generator) word() string { return words[g.Rng.IntN(len(words))] }

func (g *Generator) hex(n int) string {
	b := make([]byte, n)
	for i := range b {
		b[i] = byte(g.Rng.IntN(256))
	}
	return hex.EncodeToString(b)
}

func (g *Generator) uuid() string {
	h := g.hex(16)
	return h[0:8] + "-" + h[8:12] + "-4" + h[13:16] + "-a" + h[17:20] + "-" + h[20:32]
}

func (g *Generator) str(s map[string]any, name string) string {
	hint, _ := s["x-fake"].(string)
	format, _ := s["format"].(string)
	n := strings.ToLower(name)
	var out string
	switch {
	case format == "uuid" || hint == "uuid":
		out = g.uuid()
	case format == "email" || hint == "email" || strings.Contains(n, "email"):
		out = fmt.Sprintf("%s.%s@example.com", g.word(), g.word())
	case format == "date-time" || hint == "date-time" || strings.HasSuffix(n, "_at"):
		out = epoch.Add(time.Duration(g.Rng.Int64N(365*24*3600)) * time.Second).Format(time.RFC3339)
	case format == "date" || hint == "date":
		out = epoch.AddDate(0, 0, g.Rng.IntN(365)).Format("2006-01-02")
	case format == "uri" || format == "url" || hint == "url" || n == "url" || n == "uri":
		out = "https://example.com/" + g.word()
	case hint == "name" || n == "name" || strings.HasSuffix(n, "_name"):
		out = firstNames[g.Rng.IntN(len(firstNames))] + " " + lastNames[g.Rng.IntN(len(lastNames))]
	case hint == "id" || n == "id" || strings.HasSuffix(n, "_id"):
		prefix := strings.TrimSuffix(strings.TrimSuffix(n, "id"), "_")
		if prefix == "" {
			prefix = "id"
		}
		out = prefix + "_" + g.hex(4)
	case strings.Contains(n, "key") || strings.Contains(n, "token") || strings.Contains(n, "secret"):
		out = "key_" + g.hex(8)
	case strings.Contains(n, "model"):
		out = "model-" + g.word()
	case hint == "sentence" || strings.Contains(n, "message") || strings.Contains(n, "content") ||
		strings.Contains(n, "prompt") || strings.Contains(n, "text") || strings.Contains(n, "description"):
		parts := make([]string, 3+g.Rng.IntN(5))
		for i := range parts {
			parts[i] = g.word()
		}
		out = strings.ToUpper(parts[0][:1]) + strings.Join(parts, " ")[1:] + "."
	default:
		out = g.word() + "-" + g.word()
	}
	if minL := intOr(s["minLength"], 0); utf8.RuneCountInString(out) < minL {
		out += strings.Repeat("x", minL-utf8.RuneCountInString(out))
	}
	if maxL := intOr(s["maxLength"], 0); maxL > 0 && utf8.RuneCountInString(out) > maxL {
		out = string([]rune(out)[:maxL])
	}
	return out
}

func singular(name string) string {
	if strings.HasSuffix(name, "s") && len(name) > 1 {
		return strings.TrimSuffix(name, "s")
	}
	return name
}

// TypeOf returns a schema's effective type: its type (the first non-null
// one), or "object" or "array" inferred from properties or items.
func TypeOf(s map[string]any) string {
	switch t := s["type"].(type) {
	case string:
		return t
	case []any:
		for _, x := range t {
			if str, ok := x.(string); ok && str != "null" {
				return str
			}
		}
		return "null"
	}
	if _, ok := s["properties"]; ok {
		return "object"
	}
	if _, ok := s["items"]; ok {
		return "array"
	}
	return ""
}

// Validate checks v against schema and returns messages for every mismatch,
// at most 20.
func Validate(schema map[string]any, v any, resolve Resolver) []string {
	var out []string
	validate(schema, expr.Native(v), "$", resolve, &out, 0)
	if len(out) > 20 {
		out = append(out[:20], fmt.Sprintf("and %d more", len(out)-20))
	}
	return out
}

func validate(s map[string]any, v any, path string, resolve Resolver, out *[]string, depth int) {
	if s == nil || depth > maxDepth*2 {
		return
	}
	add := func(format string, a ...any) { *out = append(*out, path+": "+fmt.Sprintf(format, a...)) }
	if r, ok := s["$ref"].(string); ok {
		if resolve != nil {
			if t, ok := resolve(r); ok {
				validate(t, v, path, resolve, out, depth+1)
				return
			}
		}
		add("unresolved $ref %q", r)
		return
	}
	for _, k := range []string{"oneOf", "anyOf"} {
		if br, ok := s[k].([]any); ok && len(br) > 0 {
			for _, b := range br {
				if m, ok := b.(map[string]any); ok {
					var tmp []string
					validate(m, v, path, resolve, &tmp, depth+1)
					if len(tmp) == 0 {
						return
					}
				}
			}
			add("matches none of %s", k)
			return
		}
	}
	if c, ok := s["const"]; ok && !equal(c, v) {
		add("must equal %v", c)
	}
	if en, ok := s["enum"].([]any); ok {
		found := false
		for _, e := range en {
			if equal(e, v) {
				found = true
				break
			}
		}
		if !found {
			add("%v is not one of the allowed values", v)
		}
	}
	if !typeMatches(s, v) {
		add("expected %v, got %s", s["type"], kindOf(v))
		return
	}
	switch t := v.(type) {
	case map[string]any:
		if req, ok := s["required"].([]any); ok {
			for _, r := range req {
				if name, ok := r.(string); ok {
					if _, present := t[name]; !present {
						add("missing required property %q", name)
					}
				}
			}
		}
		props, _ := s["properties"].(map[string]any)
		for _, k := range sortedKeys(props) {
			if ps, ok := props[k].(map[string]any); ok {
				if x, present := t[k]; present {
					validate(ps, x, path+"."+k, resolve, out, depth+1)
				}
			}
		}
	case []any:
		if lo, ok := num(s["minItems"]); ok && float64(len(t)) < lo {
			add("needs at least %v items", lo)
		}
		if hi, ok := num(s["maxItems"]); ok && float64(len(t)) > hi {
			add("allows at most %v items", hi)
		}
		if items, ok := s["items"].(map[string]any); ok {
			for i, x := range t {
				validate(items, x, fmt.Sprintf("%s[%d]", path, i), resolve, out, depth+1)
			}
		}
	case string:
		n := float64(utf8.RuneCountInString(t))
		if lo, ok := num(s["minLength"]); ok && n < lo {
			add("shorter than %v", lo)
		}
		if hi, ok := num(s["maxLength"]); ok && n > hi {
			add("longer than %v", hi)
		}
	case int64, float64:
		f, _ := num(t)
		if lo, ok := num(s["minimum"]); ok && f < lo {
			add("%v is below the minimum %v", t, lo)
		}
		if hi, ok := num(s["maximum"]); ok && f > hi {
			add("%v is above the maximum %v", t, hi)
		}
	}
}

func typeMatches(s map[string]any, v any) bool {
	var allowed []string
	switch t := s["type"].(type) {
	case string:
		allowed = []string{t}
	case []any:
		for _, x := range t {
			if str, ok := x.(string); ok {
				allowed = append(allowed, str)
			}
		}
	default:
		return true
	}
	k := kindOf(v)
	for _, a := range allowed {
		if a == k || a == "number" && k == "integer" {
			return true
		}
		if a == "integer" && k == "number" {
			if f, ok := v.(float64); ok && f == math.Trunc(f) {
				return true
			}
		}
	}
	return false
}

func kindOf(v any) string {
	switch v.(type) {
	case nil:
		return "null"
	case bool:
		return "boolean"
	case int64, expr.BigInt: // a {$bigint} input is an integer (§15.3)
		return "integer"
	case float64:
		return "number"
	case string, []byte: // {$bytes} input is raw bytes (§15.3)
		return "string"
	case []any:
		return "array"
	case map[string]any:
		return "object"
	}
	return fmt.Sprintf("%T", v)
}

func equal(a, b any) bool {
	na, nb := expr.Native(a), expr.Native(b)
	if fa, ok := num(na); ok {
		if fb, ok := num(nb); ok {
			return fa == fb
		}
	}
	return reflect.DeepEqual(na, nb)
}

func num(v any) (float64, bool) {
	switch t := v.(type) {
	case int64:
		return float64(t), true
	case int:
		return float64(t), true
	case float64:
		return t, true
	case json.Number:
		f, err := t.Float64()
		return f, err == nil
	}
	return 0, false
}

func intOr(v any, def int) int {
	if f, ok := num(v); ok {
		return int(f)
	}
	return def
}

func sortedKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

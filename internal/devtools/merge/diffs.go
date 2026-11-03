package merge

import (
	"encoding/json"
	"fmt"
	"sort"
)

// Union deep-merges b into a: objects merge key by key, arrays of strings
// (such as required lists and enums) are combined without duplicates, and for
// any other disagreement the first value wins.
func Union(a, b any) any {
	am, ok1 := a.(map[string]any)
	bm, ok2 := b.(map[string]any)
	if ok1 && ok2 {
		out := map[string]any{}
		for k, v := range am {
			out[k] = v
		}
		for k, v := range bm {
			if cur, ok := out[k]; ok {
				out[k] = Union(cur, v)
			} else {
				out[k] = v
			}
		}
		return out
	}
	as, ok1 := a.([]any)
	bs, ok2 := b.([]any)
	if ok1 && ok2 {
		seen := map[string]bool{}
		var out []any
		for _, x := range append(append([]any{}, as...), bs...) {
			key, _ := json.Marshal(x)
			if !seen[string(key)] {
				seen[string(key)] = true
				out = append(out, x)
			}
		}
		return out
	}
	return a
}

// IsStub reports whether an entity spec is a boundary stub (attributes.boundary: true).
func IsStub(m map[string]any) bool {
	a, _ := m["attributes"].(map[string]any)
	b, _ := a["boundary"].(bool)
	return b
}

// Canonical encodes a decoded JSON value; maps encode with sorted keys.
func Canonical(m any) []byte {
	b, _ := json.Marshal(m)
	return b
}

// Top-level fields whose disagreement is prose, not contract.
var proseKeys = map[string]bool{"summary": true, "description": true, "name": true, "title": true,
	// compared structurally below
	"request": true, "response": true, "errors": true, "store": true}

// ScalarDiffs lists the contract scalars two definitions of one interface
// disagree on: top-level scalars (kind, latency), attributes (owner), the
// type, $ref, format and const of every request and response schema node,
// and the status or retryability of an error code. union keeps a's value
// for each of these, silently, so they are worth a warning.
func ScalarDiffs(a, b map[string]any) []string {
	var out []string
	keys := func(m map[string]any) []string {
		var k []string
		for x := range m {
			k = append(k, x)
		}
		sort.Strings(k)
		return k
	}
	for _, k := range keys(a) {
		if proseKeys[k] {
			continue
		}
		bv, ok := b[k]
		if !ok {
			continue
		}
		if isScalar(a[k]) && isScalar(bv) && fmt.Sprint(a[k]) != fmt.Sprint(bv) {
			out = append(out, fmt.Sprintf("%s: %v vs %v", k, a[k], bv))
		}
	}
	if aa, ok := a["attributes"].(map[string]any); ok {
		if ba, ok := b["attributes"].(map[string]any); ok {
			for _, k := range keys(aa) {
				if bv, ok := ba[k]; ok && k != "boundary" && isScalar(aa[k]) && isScalar(bv) && fmt.Sprint(aa[k]) != fmt.Sprint(bv) {
					out = append(out, fmt.Sprintf("attributes.%s: %v vs %v", k, aa[k], bv))
				}
			}
		}
	}
	for _, k := range []string{"request", "response"} {
		out = append(out, SchemaDiffs(k, a[k], b[k])...)
	}
	out = append(out, storeDiffs(a["store"], b["store"])...)
	errs := func(m map[string]any) map[string]string {
		o := map[string]string{}
		l, _ := m["errors"].([]any)
		for _, e := range l {
			if em, ok := e.(map[string]any); ok {
				o[str(em["code"])] = fmt.Sprintf("status %v retryable %v", em["status"], em["retryable"] == true)
			}
		}
		return o
	}
	ae, be := errs(a), errs(b)
	var codes []string
	for c := range ae {
		codes = append(codes, c)
	}
	sort.Strings(codes)
	for _, c := range codes {
		if bv, ok := be[c]; ok && bv != ae[c] {
			out = append(out, fmt.Sprintf("errors[%s]: %s vs %s", c, ae[c], bv))
		}
	}
	return out
}

func isScalar(v any) bool {
	switch v.(type) {
	case string, bool, float64, json.Number, int, int64:
		return true
	}
	return false
}

// SchemaDiffs compares the structural scalars of two schemas at the same path.
func SchemaDiffs(path string, a, b any) []string {
	if a == nil || b == nil {
		return nil
	}
	// A schema is a name (a reference) or an inline object. Two different
	// names disagree; a name against an inline object is only a difference
	// of representation, so it isn't reported.
	as, aok := a.(string)
	bs, bok := b.(string)
	if aok || bok {
		if aok && bok && as != bs {
			return []string{fmt.Sprintf("%s: %s vs %s", path, as, bs)}
		}
		return nil
	}
	am, ok1 := a.(map[string]any)
	bm, ok2 := b.(map[string]any)
	if !ok1 || !ok2 {
		return nil
	}
	var out []string
	for _, k := range []string{"type", "$ref", "format", "const"} {
		if av, ok := am[k]; ok {
			if bv, ok := bm[k]; ok && fmt.Sprint(av) != fmt.Sprint(bv) {
				out = append(out, fmt.Sprintf("%s.%s: %v vs %v", path, k, av, bv))
			}
		}
	}
	if ap, ok := am["properties"].(map[string]any); ok {
		if bp, ok := bm["properties"].(map[string]any); ok {
			var names []string
			for n := range ap {
				names = append(names, n)
			}
			sort.Strings(names)
			for _, n := range names {
				out = append(out, SchemaDiffs(path+"."+n, ap[n], bp[n])...)
			}
		}
	}
	out = append(out, SchemaDiffs(path+"[]", am["items"], bm["items"])...)
	return out
}

// storeDiffs compares two store specs ({table, op, key, value, where,
// default, not_found, conflict}). The union would mix their fields into a
// spec neither side wrote, so any difference is reported: table and op first,
// then the other fields by their JSON.
func storeDiffs(a, b any) []string {
	am, ok1 := a.(map[string]any)
	bm, ok2 := b.(map[string]any)
	switch {
	case a == nil && b == nil:
		return nil
	case !ok1 || !ok2:
		if (a == nil) != (b == nil) {
			return nil // one side doesn't model the store; nothing mixes
		}
		return []string{fmt.Sprintf("store: %s vs %s", Canonical(a), Canonical(b))}
	}
	var out []string
	for _, k := range []string{"table", "op"} {
		if fmt.Sprint(am[k]) != fmt.Sprint(bm[k]) {
			out = append(out, fmt.Sprintf("store.%s: %v vs %v", k, am[k], bm[k]))
		}
	}
	keys := map[string]bool{}
	for k := range am {
		keys[k] = true
	}
	for k := range bm {
		keys[k] = true
	}
	var rest []string
	for k := range keys {
		if k != "table" && k != "op" {
			rest = append(rest, k)
		}
	}
	sort.Strings(rest)
	for _, k := range rest {
		av, bv := Canonical(am[k]), Canonical(bm[k])
		if string(av) != string(bv) {
			out = append(out, fmt.Sprintf("store.%s: %s vs %s", k, av, bv))
		}
	}
	return out
}

func str(v any) string { s, _ := v.(string); return s }

// FieldDiffs lists the top-level fields two definitions of a config or a
// fixture disagree on, by their JSON, ignoring prose, sources and the
// boundary marker. A field only one side sets isn't a difference: a
// reference may name just the id. AllFieldDiffs counts those too.
func FieldDiffs(a, b map[string]any) []string { return fieldDiffs(a, b, false) }

// AllFieldDiffs is FieldDiffs where a field only one side sets differs.
func AllFieldDiffs(a, b map[string]any) []string { return fieldDiffs(a, b, true) }

func fieldDiffs(a, b map[string]any, missing bool) []string {
	skip := map[string]bool{"summary": true, "description": true, "name": true, "title": true, "sources": true, "tags": true}
	keys := map[string]bool{}
	for k := range a {
		keys[k] = true
	}
	for k := range b {
		keys[k] = true
	}
	var names []string
	for k := range keys {
		if !skip[k] {
			names = append(names, k)
		}
	}
	sort.Strings(names)
	var out []string
	for _, k := range names {
		av, aok := a[k]
		bv, bok := b[k]
		if !missing && (!aok || !bok) {
			continue
		}
		if k == "attributes" {
			av, bv = dropBoundary(av), dropBoundary(bv)
		}
		if ac, bc := string(Canonical(av)), string(Canonical(bv)); ac != bc {
			out = append(out, fmt.Sprintf("%s: %s vs %s", k, ac, bc))
		}
	}
	return out
}

func dropBoundary(v any) any {
	m, ok := v.(map[string]any)
	if !ok {
		return v
	}
	out := map[string]any{}
	for k, x := range m {
		if k != "boundary" && k != "owner" {
			out[k] = x
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

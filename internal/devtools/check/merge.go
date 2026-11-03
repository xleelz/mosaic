package main

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

// The merge itself lives in internal/devtools/merge, shared with the history
// builder; these names keep the report code below and the tests short.
var (
	isStub      = merge.IsStub
	scalarDiffs = merge.ScalarDiffs
	schemaDiffs = merge.SchemaDiffs
)

func canonical(m any) []byte {
	b, _ := json.Marshal(m)
	return b
}

// Annotation keys that don't change what a schema accepts.
var annotationKeys = map[string]bool{"description": true, "title": true, "examples": true, "example": true, "$comment": true, "default": true}

func stripAnnotations(v any) any {
	switch v := v.(type) {
	case map[string]any:
		out := map[string]any{}
		for k, x := range v {
			if !annotationKeys[k] {
				out[k] = stripAnnotations(x)
			}
		}
		return out
	case []any:
		out := make([]any, len(v))
		for i, x := range v {
			out[i] = stripAnnotations(x)
		}
		return out
	}
	return v
}

// substantial keeps trivial schemas ({type: string}, an object with one field)
// out of the duplicate report: those coincide by accident.
func substantial(s map[string]any) bool {
	if p, ok := s["properties"].(map[string]any); ok && len(p) >= 2 {
		return true
	}
	if e, ok := s["enum"].([]any); ok && len(e) >= 3 {
		return true
	}
	return false
}

// dupGroup is a set of schemas identical except for their names.
type dupGroup struct {
	IDs   []string
	Exact bool // false: they differ only in descriptions, titles or examples
}

func duplicateSchemas(schemas []model.Schema) []dupGroup {
	groups := map[string][]model.Schema{}
	var order []string
	for _, s := range schemas {
		if !substantial(s.Schema) {
			continue
		}
		k := string(canonical(stripAnnotations(s.Schema)))
		if _, ok := groups[k]; !ok {
			order = append(order, k)
		}
		groups[k] = append(groups[k], s)
	}
	var out []dupGroup
	for _, k := range order {
		g := groups[k]
		if len(g) < 2 {
			continue
		}
		d := dupGroup{Exact: true}
		first := string(canonical(g[0].Schema))
		for _, s := range g {
			d.IDs = append(d.IDs, s.ID)
			if string(canonical(s.Schema)) != first {
				d.Exact = false
			}
		}
		sort.Strings(d.IDs)
		out = append(out, d)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].IDs[0] < out[j].IDs[0] })
	return out
}

func (d dupGroup) String() string {
	note := "identical"
	if !d.Exact {
		note = "identical except descriptions/examples"
	}
	return fmt.Sprintf("%s (%s)", strings.Join(d.IDs, ", "), note)
}

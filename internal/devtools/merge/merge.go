// Package merge combines ontology fragments into one document, with the rules
// internal/devtools/check documents: entities with the same kind and id must
// be identical, except that a boundary stub (attributes.boundary: true) yields
// to a non-stub definition, and several stubs of one interface are combined by
// union. Configs and fixtures (DESIGN §13.1 item 4) have one owner each:
// identical duplicates merge, differing duplicates are conflicts, and a
// duplicate marked attributes.boundary is a reference that defers to the
// owner (references are never combined by union). The check tool and the
// history builder share it.
package merge

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// Input is one fragment: a name for messages (usually its path) and its document.
type Input struct {
	Name string
	Doc  *model.Document
}

// Result is a merged document and what the merge noticed.
type Result struct {
	Doc           *model.Document
	Issues        []model.Issue       // entities that don't decode after the merge
	Conflicts     []string            // "<kind> \"<id>\" is defined differently in A and B"
	StubFiles     map[string][]string // "<kind>/<id>" -> inputs whose stubs were combined
	Disagreements []string            // stub-vs-stub scalar disagreements (the union keeps the first)
	OwnerDiffs    []string            // stub-vs-owner scalar differences (the owner wins)
	Stubs         int                 // boundary stubs left in the merged document
	// Refs counts config and fixture boundary references that deferred to
	// their owner, or to an earlier reference, keyed "<kind>/<id>".
	Refs map[string][]string
	// Origins maps "<kind>/<id>" to the input whose definition the merged
	// document keeps (the owner over a stub; the first of combined stubs).
	Origins map[string]string
}

// world reports whether a kind follows the one-owner rule of §13.1 item 4.
func world(kind string) bool { return kind == model.KindConfig || kind == model.KindFixture }

// ParseError is a fragment that doesn't parse.
type ParseError struct {
	Path string
	Err  error
}

func (e *ParseError) Error() string { return e.Path + ": " + e.Err.Error() }

// Load reads and parses fragment files (YAML or JSON), in order.
func Load(paths []string) ([]Input, error) {
	var out []Input
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			return nil, err
		}
		doc, err := model.ParseDocument(data)
		if err != nil {
			return nil, &ParseError{p, err}
		}
		out = append(out, Input{p, doc})
	}
	return out, nil
}

type entry struct {
	ent    model.Entity
	file   string
	parsed map[string]any
}

// Merge combines the inputs in order. The merged document takes its id, name,
// description and source from the first input. Conflicts keep the first
// definition and are reported, not returned as an error.
func Merge(inputs []Input) (*Result, error) {
	res := &Result{StubFiles: map[string][]string{}, Refs: map[string][]string{}, Origins: map[string]string{}}
	merged := map[string]*entry{}
	var order []string
	var first *model.Document
	for _, in := range inputs {
		if first == nil {
			first = in.Doc
		}
		ents, err := in.Doc.Entities()
		if err != nil {
			return nil, err
		}
		for _, e := range ents {
			key := e.Kind + "/" + e.ID
			var parsed map[string]any
			_ = json.Unmarshal(e.Spec, &parsed)
			cur, ok := merged[key]
			if !ok {
				merged[key] = &entry{e, in.Name, parsed}
				order = append(order, key)
				continue
			}
			if bytes.Equal(Canonical(cur.parsed), Canonical(parsed)) {
				continue
			}
			diffs := ScalarDiffs
			if world(e.Kind) {
				diffs = FieldDiffs
			}
			disagree := func(to *[]string, a, b map[string]any, aFile, bFile string) {
				for _, d := range diffs(a, b) {
					*to = append(*to, fmt.Sprintf("%s %q: %s (%s vs %s)", e.Kind, e.ID, d, aFile, bFile))
				}
			}
			switch {
			case world(e.Kind) && IsStub(parsed):
				// A reference defers to whatever came first: the owner, or
				// an earlier reference until the owner arrives.
				if IsStub(cur.parsed) {
					disagree(&res.Disagreements, cur.parsed, parsed, cur.file, in.Name)
				} else {
					disagree(&res.OwnerDiffs, cur.parsed, parsed, cur.file, in.Name)
				}
				res.Refs[key] = append(res.Refs[key], in.Name)
			case world(e.Kind) && IsStub(cur.parsed):
				disagree(&res.OwnerDiffs, parsed, cur.parsed, in.Name, cur.file)
				res.Refs[key] = append(res.Refs[key], cur.file)
				merged[key] = &entry{e, in.Name, parsed}
			case world(e.Kind):
				d := strings.Join(AllFieldDiffs(cur.parsed, parsed), "; ")
				if d == "" {
					continue // only prose (summary, sources, tags) differs: the first is kept
				}
				res.Conflicts = append(res.Conflicts, fmt.Sprintf("%s %q is defined differently in %s and %s: %s (one must own it; mark the other attributes.boundary)", e.Kind, e.ID, cur.file, in.Name, d))
			case IsStub(cur.parsed) && !IsStub(parsed):
				disagree(&res.OwnerDiffs, parsed, cur.parsed, in.Name, cur.file)
				merged[key] = &entry{e, in.Name, parsed}
			case IsStub(parsed) && !IsStub(cur.parsed):
				disagree(&res.OwnerDiffs, cur.parsed, parsed, cur.file, in.Name)
			case IsStub(parsed) && IsStub(cur.parsed):
				// Two areas stub the same interface: union their fields so
				// every caller's view of the contract survives the merge.
				// The union keeps the first value of a disagreeing scalar.
				disagree(&res.Disagreements, cur.parsed, parsed, cur.file, in.Name)
				if len(res.StubFiles[key]) == 0 {
					res.StubFiles[key] = []string{cur.file}
				}
				res.StubFiles[key] = append(res.StubFiles[key], in.Name)
				u := Union(cur.parsed, parsed).(map[string]any)
				spec, err := json.Marshal(u)
				if err != nil {
					return nil, err
				}
				merged[key] = &entry{model.Entity{Kind: e.Kind, ID: e.ID, Spec: spec}, cur.file, u}
			default:
				res.Conflicts = append(res.Conflicts, fmt.Sprintf("%s %q is defined differently in %s and %s", e.Kind, e.ID, cur.file, in.Name))
			}
		}
	}
	var ents []model.Entity
	for _, k := range order {
		ents = append(ents, merged[k].ent)
		res.Origins[k] = merged[k].file
		if IsStub(merged[k].parsed) {
			res.Stubs++
		}
	}
	res.Doc, res.Issues = model.FromEntities(ents)
	if first != nil {
		res.Doc.ID, res.Doc.Name, res.Doc.Description, res.Doc.Source = first.ID, first.Name, first.Description, first.Source
	}
	// The §14 document metadata: the first level and refines given, and
	// every import once (by ontology, revision and prefix).
	seenImport := map[model.ImportRef]bool{}
	for _, in := range inputs {
		if res.Doc.Level == "" {
			res.Doc.Level = in.Doc.Level
		}
		if res.Doc.Refines == nil && in.Doc.Refines != nil {
			r := *in.Doc.Refines
			res.Doc.Refines = &r
		}
		for _, im := range in.Doc.Imports {
			if !seenImport[im] {
				seenImport[im] = true
				res.Doc.Imports = append(res.Doc.Imports, im)
			}
		}
	}
	return res, nil
}

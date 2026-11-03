package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

// The document-level hierarchy fields (§14.11, §15.4) live in the ontology's
// meta table, next to its source, so they are versioned with its entities:
// level (a JSON string), refines (an object) and imports (a list). A
// component's refined_by is part of its spec.
var hierarchyKeys = []string{"level", "refines", "imports"}

// hierarchyMeta encodes doc's hierarchy fields per meta key; an absent field
// is nil, which deletes the key.
func hierarchyMeta(doc *model.Document) map[string][]byte {
	out := map[string][]byte{}
	if doc.Level != "" {
		out["level"], _ = json.Marshal(doc.Level)
	}
	if doc.Refines != nil {
		out["refines"], _ = json.Marshal(doc.Refines)
	}
	if len(doc.Imports) > 0 {
		out["imports"], _ = json.Marshal(doc.Imports)
	}
	return out
}

// applyMeta sets one meta value on doc: the source or a hierarchy field.
// Values that don't decode are left out.
func applyMeta(doc *model.Document, k string, v []byte) {
	if len(v) == 0 || string(v) == "null" {
		return
	}
	switch k {
	case "source":
		var ds model.DocSource
		if json.Unmarshal(v, &ds) == nil {
			doc.Source = &ds
		}
	case "level":
		var s string
		if json.Unmarshal(v, &s) == nil {
			doc.Level = s
		}
	case "refines":
		var r model.RefinesRef
		if json.Unmarshal(v, &r) == nil {
			doc.Refines = &r
		}
	case "imports":
		var ims []model.ImportRef
		if json.Unmarshal(v, &ims) == nil && len(ims) > 0 {
			doc.Imports = ims
		}
	}
}

// maxLinkDepth bounds how deep imports and refinements nest when loaded.
const maxLinkDepth = 16

// Link follows a stored document's links (§14.11, §15.4): it loads the
// imports doc names, recursively, into ImportDocs, and, for each component
// path that resolution refines, the child ontology its refined_by names into
// Refinements (a nested path "a/b" from a's child). A run composes them.
//
// A reference is a stored ontology id. Its revision is a selector (N, rN,
// latest or draft); without one it is the latest revision, or the draft
// when the ontology has none. Of several refined_by entries, the first that
// is stored is loaded. An import, or a refinement the resolution needs, that
// the store can't resolve is a bad request.
func (s *Store) Link(ctx context.Context, doc *model.Document, resolution map[string]string) error {
	l := &linker{s: s, docs: map[string]*model.Document{}}
	if err := l.imports(ctx, doc, 0); err != nil {
		return err
	}
	var refined []string
	for k, v := range resolution {
		if v == model.ResolutionRefined {
			refined = append(refined, k)
		}
	}
	sort.Strings(refined)
	for _, path := range refined {
		if err := l.refine(ctx, doc, path); err != nil {
			return err
		}
	}
	return nil
}

// linker loads linked documents once per (ontology, revision).
type linker struct {
	s    *Store
	docs map[string]*model.Document
	// lenient leaves an import the store can't resolve unloaded, for
	// validation to report, instead of failing.
	lenient bool
}

// load returns a stored ontology's document at a revision selector, with
// ok false when ref names no stored ontology (a file path, for one).
func (l *linker) load(ctx context.Context, ont, rev string) (*model.Document, bool, error) {
	if !model.ValidID(ont) {
		return nil, false, nil
	}
	if err := l.s.Exists(ctx, ont); err != nil {
		if isCode(err, CodeNotFound) {
			return nil, false, nil
		}
		return nil, false, err
	}
	sel := strings.TrimSpace(rev)
	if sel == "" {
		sel = "latest"
		if _, err := l.s.resolveRev(ctx, ont, sel); isCode(err, CodeNotFound) {
			sel = "draft"
		}
	}
	rv, err := l.s.resolveRev(ctx, ont, sel)
	if err != nil {
		return nil, false, err
	}
	key := ont + "@" + rv.String()
	if d, ok := l.docs[key]; ok {
		return d, true, nil
	}
	d, _, err := l.s.Document(ctx, ont, rv)
	if err != nil {
		return nil, false, err
	}
	l.docs[key] = d
	return d, true, nil
}

// imports fills d.ImportDocs from the store, recursively.
func (l *linker) imports(ctx context.Context, d *model.Document, depth int) error {
	if len(d.Imports) == 0 {
		return nil
	}
	if depth >= maxLinkDepth {
		return errf(CodeBadRequest, "imports nest deeper than %d", maxLinkDepth)
	}
	for _, im := range d.Imports {
		if d.ImportDocs[im.Ontology] != nil {
			continue
		}
		sub, ok, err := l.load(ctx, im.Ontology, im.Revision)
		if l.lenient && (!ok || isStoreErr(err)) {
			continue
		}
		if err != nil {
			return linkErr("import", im.Ontology, err)
		}
		if !ok {
			return errf(CodeBadRequest, "import %q: no stored ontology %q", im.Ontology, im.Ontology)
		}
		if err := l.imports(ctx, sub, depth+1); err != nil {
			return err
		}
		if d.ImportDocs == nil {
			d.ImportDocs = map[string]*model.Document{}
		}
		d.ImportDocs[im.Ontology] = sub
	}
	return nil
}

// refine loads the child of each segment of a component path that isn't
// loaded yet: "a/b" loads a's child from doc, then b's from a's child.
func (l *linker) refine(ctx context.Context, doc *model.Document, path string) error {
	segs := strings.Split(path, "/")
	if len(segs) > maxLinkDepth {
		return errf(CodeBadRequest, "refinement path %q nests deeper than %d", path, maxLinkDepth)
	}
	cur := doc
	for i, seg := range segs {
		if child := cur.Refinements[seg]; child != nil {
			cur = child
			continue
		}
		at := strings.Join(segs[:i+1], "/")
		var comp *model.Component
		for j := range cur.Components {
			if cur.Components[j].ID == seg {
				comp = &cur.Components[j]
				break
			}
		}
		if comp == nil {
			return errf(CodeBadRequest, "resolution refines %q: no component %q", at, seg)
		}
		if len(comp.RefinedBy) == 0 {
			return errf(CodeBadRequest, "resolution refines %q: the component lists no refined_by", at)
		}
		var child *model.Document
		var tried []string
		for _, rb := range comp.RefinedBy {
			d, ok, err := l.load(ctx, rb.Ontology, rb.Revision)
			if err != nil {
				return linkErr("refinement of "+at, rb.Ontology, err)
			}
			if ok {
				child = d
				break
			}
			tried = append(tried, rb.Ontology)
		}
		if child == nil {
			return errf(CodeBadRequest, "resolution refines %q: none of its refined_by is a stored ontology (%s)", at, strings.Join(tried, ", "))
		}
		// A document is shared between the paths that load it; compose
		// clones what it changes, but give each path its own maps.
		child = shallowLinked(child)
		if err := l.imports(ctx, child, 0); err != nil {
			return err
		}
		if cur.Refinements == nil {
			cur.Refinements = map[string]*model.Document{}
		}
		cur.Refinements[seg] = child
		cur = child
	}
	return nil
}

// shallowLinked copies a document's top level so its Refinements map is
// its own.
func shallowLinked(d *model.Document) *model.Document {
	c := *d
	c.Refinements = nil
	return &c
}

// linkErr names the link a store error came from, keeping its code.
func linkErr(what, ont string, err error) error {
	var se *Error
	if errors.As(err, &se) {
		return &Error{Code: CodeBadRequest, Message: fmt.Sprintf("%s %q: %s", what, ont, se.Message)}
	}
	return err
}

func isStoreErr(err error) bool {
	var se *Error
	return errors.As(err, &se)
}

// validateLinked validates a stored document following the imports it names
// in the store (§15.4). An import the store can't resolve stays unloaded,
// and validation reports it.
func (s *Store) validateLinked(ctx context.Context, doc *model.Document) ([]model.Issue, error) {
	l := &linker{s: s, docs: map[string]*model.Document{}, lenient: true}
	if err := l.imports(ctx, doc, 0); err != nil {
		return nil, err
	}
	return model.ValidateWithImports(doc), nil
}

// draftHierarchy fills the detail's hierarchy fields from the draft's meta.
func (s *Store) draftHierarchy(ctx context.Context, id string, out *api.OntologyDetail) error {
	rows, err := s.db.QueryContext(ctx, "SELECT k, v FROM "+table(id, "meta")+" WHERE k IN ('level', 'refines', 'imports')")
	if err != nil {
		return err
	}
	defer rows.Close()
	var d model.Document
	for rows.Next() {
		var k string
		var v []byte
		if err := rows.Scan(&k, &v); err != nil {
			return err
		}
		applyMeta(&d, k, v)
	}
	out.Level, out.Refines, out.Imports = d.Level, d.Refines, d.Imports
	return rows.Err()
}

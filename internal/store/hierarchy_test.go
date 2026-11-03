package store_test

import (
	"context"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
	"github.com/xleelz/mosaic/internal/store"
	"github.com/xleelz/mosaic/pkg/api"
)

func readDoc(t *testing.T, path string) *model.Document {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	d, err := model.ParseDocument(data)
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func parseDoc(t *testing.T, src string) *model.Document {
	t.Helper()
	d, err := model.ParseDocument([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func putDoc(t *testing.T, id string, d *model.Document, revise bool) {
	t.Helper()
	ctx := context.Background()
	if _, err := st.CreateOntology(ctx, api.CreateOntology{ID: id}); err != nil {
		t.Fatal(err)
	}
	if _, err := st.PutDocument(ctx, id, d); err != nil {
		t.Fatal(err)
	}
	if revise {
		if _, err := st.CreateRevision(ctx, id, api.CreateRevision{Message: "r1"}); err != nil {
			t.Fatal(err)
		}
	}
}

// TestHierarchyPersists: the document-level level, refines and imports,
// and a component's refined_by, survive the store at the draft and at a
// revision, and clearing them removes them (§15.4).
func TestHierarchyPersists(t *testing.T) {
	ctx := context.Background()
	parent := readDoc(t, "../model/testdata/refine/parent.yaml")
	child := readDoc(t, "../model/testdata/refine/child.yaml")
	child.Imports = []model.ImportRef{{Ontology: "hp-kv", Revision: "1", As: "kv"}}
	putDoc(t, "hp-kv", parseDoc(t, "components: [{id: store}]\n"), true)
	putDoc(t, "hp-shop", parent, true)
	putDoc(t, "hp-child", child, true)

	for _, r := range []store.Rev{store.Draft, {N: 1}} {
		got, _, err := st.Document(ctx, "hp-child", r)
		if err != nil {
			t.Fatal(err)
		}
		if got.Level != "service" || !reflect.DeepEqual(got.Refines, child.Refines) || !reflect.DeepEqual(got.Imports, child.Imports) {
			t.Errorf("child at %s: level %q, refines %+v, imports %+v", r, got.Level, got.Refines, got.Imports)
		}
		p, _, err := st.Document(ctx, "hp-shop", r)
		if err != nil {
			t.Fatal(err)
		}
		var rb []model.OntologyRef
		for _, c := range p.Components {
			if c.ID == "engine" {
				rb = c.RefinedBy
			}
		}
		if p.Level != "system" || len(rb) != 1 || rb[0].Ontology != "engine-logic" || rb[0].Revision != "1" {
			t.Errorf("parent at %s: level %q, refined_by %+v", r, p.Level, rb)
		}
	}
	d, err := st.GetOntology(ctx, "hp-child")
	if err != nil {
		t.Fatal(err)
	}
	if d.Level != "service" || d.Refines == nil || d.Refines.Component != "engine" || len(d.Imports) != 1 || d.DraftDirty {
		t.Errorf("detail = %+v", d)
	}

	// Changing only a hierarchy field dirties the draft; clearing removes it,
	// and the revision keeps the old value.
	child.Level, child.Imports = "", nil
	if _, err := st.PutDocument(ctx, "hp-child", child); err != nil {
		t.Fatal(err)
	}
	got, _, _ := st.Document(ctx, "hp-child", store.Draft)
	if got.Level != "" || got.Imports != nil || got.Refines == nil {
		t.Errorf("cleared draft: level %q, imports %+v, refines %+v", got.Level, got.Imports, got.Refines)
	}
	if d, _ := st.GetOntology(ctx, "hp-child"); !d.DraftDirty {
		t.Error("a hierarchy-only change left the draft clean")
	}
	if old, _, _ := st.Document(ctx, "hp-child", store.Rev{N: 1}); old.Level != "service" || len(old.Imports) != 1 {
		t.Errorf("revision 1 changed: %q %+v", old.Level, old.Imports)
	}
}

// TestLinkRefinementsAndImports: Link loads the refinements a resolution
// opens by refined_by, and the imports, from the store, so a stored parent
// runs refined (§15.4).
func TestLinkRefinementsAndImports(t *testing.T) {
	ctx := context.Background()
	parent := readDoc(t, "../model/testdata/refine/parent.yaml")
	parent.Components[3].RefinedBy = []model.OntologyRef{{Ontology: "not/stored.yaml"}, {Ontology: "lk-engine"}}
	putDoc(t, "lk-shop", parent, false)
	child := readDoc(t, "../model/testdata/refine/child.yaml")
	putDoc(t, "lk-engine", child, false) // draft only: an unpinned ref falls back to it

	doc, _, err := st.Document(ctx, "lk-shop", store.Draft)
	if err != nil {
		t.Fatal(err)
	}
	if err := st.Link(ctx, doc, map[string]string{"engine": "refined"}); err != nil {
		t.Fatal(err)
	}
	if doc.Refinements["engine"] == nil || doc.Refinements["engine"].ID != "lk-engine" {
		t.Fatalf("refinement not loaded: %v", doc.Refinements)
	}
	res, err := sim.Run(doc, sim.Request{Scenario: "ask-refined"})
	if err != nil {
		t.Fatal(err)
	}
	if !res.Summary.Passed {
		t.Fatalf("refined run: %+v", res.Summary)
	}

	// Black box loads nothing; a refined component without a stored child is
	// a bad request.
	doc, _, _ = st.Document(ctx, "lk-shop", store.Draft)
	if err := st.Link(ctx, doc, map[string]string{"engine": "black_box"}); err != nil || doc.Refinements != nil {
		t.Fatalf("black box: %v %v", err, doc.Refinements)
	}
	err = st.Link(ctx, doc, map[string]string{"gateway": "refined"})
	if se, ok := err.(*store.Error); !ok || se.Code != store.CodeBadRequest || !strings.Contains(se.Message, "refined_by") {
		t.Fatalf("no refined_by: %v", err)
	}

	// Imports resolve by store id; a missing one fails a run's link and is a
	// validation error, under imports[0].
	kv := parseDoc(t, "components: [{id: store}]\ninterfaces: [{component: store, name: get, behavior: [{return: {v: 1}}]}]\n")
	putDoc(t, "lk-kv", kv, true)
	app := parseDoc(t, "imports: [{ontology: lk-kv, as: cache}]\ncomponents: [{id: app}, {id: client}]\n"+
		"interfaces: [{component: app, name: read, behavior: [{call: cache/store.get, as: r}, {return: \"=vars.r.value\"}]}]\n"+
		"flows: [{id: read, entry: {caller: client, interface: app.read}}]\n")
	putDoc(t, "lk-app", app, false)
	issues, err := st.Validate(ctx, "lk-app", store.Draft)
	if err != nil || model.HasErrors(issues) {
		t.Fatalf("app with a stored import: %v %+v", err, issues)
	}
	// A revision validates following the import too.
	if _, err := st.CreateRevision(ctx, "lk-app", api.CreateRevision{Message: "r1"}); err != nil {
		t.Fatal(err)
	}
	doc, _, _ = st.Document(ctx, "lk-app", store.Rev{N: 1})
	if err := st.Link(ctx, doc, nil); err != nil {
		t.Fatal(err)
	}
	if res, err := sim.Run(doc, sim.Request{Flow: "read"}); err != nil || !res.Summary.Result.OK {
		t.Fatalf("run with a stored import: %v %+v", err, res)
	}

	app.Imports[0].Ontology = "lk-missing"
	if _, err := st.PutDocument(ctx, "lk-app", app); err != nil {
		t.Fatal(err)
	}
	issues, err = st.Validate(ctx, "lk-app", store.Draft)
	if err != nil || !model.HasErrors(issues) || issues[0].Path != "imports[0].ontology" {
		t.Fatalf("missing import: %v %+v", err, issues)
	}
	doc, _, _ = st.Document(ctx, "lk-app", store.Draft)
	if err := st.Link(ctx, doc, nil); err == nil || !strings.Contains(err.Error(), "lk-missing") {
		t.Fatalf("missing import linked: %v", err)
	}
}

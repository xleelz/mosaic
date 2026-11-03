package client

import (
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
	"github.com/xleelz/mosaic/pkg/api"
)

// TestHierarchyFields: the client carries the §14.11 hierarchy fields both
// ways: a document's level, refines, imports and refined_by, the detail's
// hierarchy fields, and a run's resolution (§15.4).
func TestHierarchyFields(t *testing.T) {
	s := newStub(t)
	c := New(s.srv.URL, "")

	s.reply(200, `{"schema_version":1,"id":"child","level":"logic","refines":{"ontology":"shop","component":"engine","revision":"2"},
		"imports":[{"ontology":"kv","revision":"1","as":"cache"}],"components":[{"id":"w","refined_by":[{"ontology":"w-runtime"}]}],
		"interfaces":[],"links":[],"schemas":[],"flows":[],"scenarios":[]}`)
	doc, err := c.GetDocument(ctx, "child", "")
	if err != nil {
		t.Fatal(err)
	}
	if doc.Level != "logic" || doc.Refines == nil || doc.Refines.Revision != "2" || len(doc.Imports) != 1 || doc.Imports[0].As != "cache" ||
		len(doc.Components[0].RefinedBy) != 1 || doc.Components[0].RefinedBy[0].Ontology != "w-runtime" {
		t.Errorf("doc = %+v", doc)
	}
	s.reply(200, `{"counts":{},"valid":true,"issues":[]}`)
	if _, err := c.PutDocument(ctx, "child", doc); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{`"level":"logic"`, `"refines":{"ontology":"shop","component":"engine","revision":"2"}`,
		`"imports":[{"ontology":"kv","revision":"1","as":"cache"}]`, `"refined_by":[{"ontology":"w-runtime"}]`} {
		if !strings.Contains(s.last.Body, want) {
			t.Errorf("PUT body lacks %s: %s", want, s.last.Body)
		}
	}

	s.reply(200, `{"id":"child","name":"child","counts":{},"draft_dirty":false,"level":"logic","refines":{"ontology":"shop","component":"engine"},"imports":[{"ontology":"kv"}]}`)
	d, err := c.GetOntology(ctx, "child")
	if err != nil {
		t.Fatal(err)
	}
	if d.Level != "logic" || d.Refines == nil || d.Refines.Component != "engine" || len(d.Imports) != 1 {
		t.Errorf("detail = %+v", d)
	}

	s.reply(200, `{"ontology":"shop","revision":"draft","request":{},"summary":{"status":"completed","result":{"ok":true}},"trace":[]}`)
	req := api.SimulationRequest{Request: sim.Request{Flow: "ask", Resolution: map[string]string{"engine": model.ResolutionRefined}}}
	if _, err := c.RunSimulation(ctx, "shop", req); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(s.last.Body, `"resolution":{"engine":"refined"}`) {
		t.Errorf("run body = %s", s.last.Body)
	}
}

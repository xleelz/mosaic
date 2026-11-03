package api_test

import (
	"encoding/json"
	"os"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	wire "github.com/xleelz/mosaic/pkg/api"
)

func putFile(t *testing.T, id, path string) wire.PutDocumentResult {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	doc, err := model.ParseDocument(data)
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	call(t, "POST", "/v1/ontologies", wire.CreateOntology{ID: id}, 201)
	return decode[wire.PutDocumentResult](t, call(t, "PUT", "/v1/ontologies/"+id+"/document", b, 200))
}

// TestHierarchyThroughAPI: the document endpoints keep level, refines,
// imports and refined_by, and a stored parent runs refined, its child
// loaded by refined_by (§15.4), from a request's or a scenario's resolution.
func TestHierarchyThroughAPI(t *testing.T) {
	// The parent pins engine-logic at revision 1.
	if res := putFile(t, "engine-logic", "../model/testdata/refine/child.yaml"); !res.Valid {
		t.Fatalf("child: %+v", res.Issues)
	}
	call(t, "POST", "/v1/ontologies/engine-logic/revisions", wire.CreateRevision{Message: "r1"}, 201)
	if res := putFile(t, "shop", "../model/testdata/refine/parent.yaml"); !res.Valid {
		t.Fatalf("parent: %+v", res.Issues)
	}

	child := decode[model.Document](t, call(t, "GET", "/v1/ontologies/engine-logic/document?rev=1", nil, 200))
	if child.Level != "service" || child.Refines == nil || child.Refines.Ontology != "shop" || child.Refines.Component != "engine" {
		t.Fatalf("child document: level %q, refines %+v", child.Level, child.Refines)
	}
	parent := decode[model.Document](t, call(t, "GET", "/v1/ontologies/shop/document", nil, 200))
	found := false
	for _, c := range parent.Components {
		found = found || (c.ID == "engine" && len(c.RefinedBy) == 1 && c.RefinedBy[0].Ontology == "engine-logic")
	}
	if parent.Level != "system" || !found {
		t.Fatalf("parent document: level %q, components %+v", parent.Level, parent.Components)
	}
	if d := decode[wire.OntologyDetail](t, call(t, "GET", "/v1/ontologies/engine-logic", nil, 200)); d.Level != "service" || d.Refines == nil {
		t.Fatalf("detail: %+v", d)
	}

	// The request's resolution.
	run := decode[wire.SimulationRun](t, call(t, "POST", "/v1/ontologies/shop/simulations",
		`{"flow":"ask","resolution":{"engine":"refined"},"save":false}`, 200))
	if !run.Summary.Result.OK || run.Summary.Calls["engine/worker.execute"] != 1 {
		t.Fatalf("refined run: %+v", run.Summary)
	}
	run = decode[wire.SimulationRun](t, call(t, "POST", "/v1/ontologies/shop/simulations", `{"flow":"ask","save":false}`, 200))
	if !run.Summary.Result.OK || run.Summary.Calls["engine/worker.execute"] != 0 {
		t.Fatalf("black-box run: %+v", run.Summary)
	}
	// The scenario's resolution, and the test endpoint.
	run = decode[wire.SimulationRun](t, call(t, "POST", "/v1/ontologies/shop/simulations", `{"scenario":"ask-refined","save":false}`, 200))
	if !run.Summary.Passed {
		t.Fatalf("ask-refined: %+v", run.Summary)
	}
	rep := decode[wire.TestReport](t, call(t, "POST", "/v1/ontologies/shop/test?save=false", nil, 200))
	if !rep.Passed || rep.Total != 2 {
		t.Fatalf("test report: %+v", rep)
	}

	// A refinement the store doesn't hold is a bad request.
	e := errCode(t, call(t, "POST", "/v1/ontologies/shop/simulations", `{"flow":"ask","resolution":{"gateway":"refined"}}`, 400))
	if e.Code != "bad_request" || !strings.Contains(e.Message, "refined_by") {
		t.Fatalf("unrefinable component: %+v", e)
	}
}

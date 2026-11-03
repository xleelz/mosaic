package merge

import (
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// TestLoadImportsSubstrateExample: the substrate example's imports load
// relative to its file, it validates following them, and its scenarios
// pass on the merged document, as check -f runs it (§15.6).
func TestLoadImportsSubstrateExample(t *testing.T) {
	inputs, err := Load([]string{"../../../substrates/examples/vm-service/ontology.yaml"})
	if err != nil {
		t.Fatal(err)
	}
	res, err := Merge(inputs)
	if err != nil {
		t.Fatal(err)
	}
	doc := res.Doc
	if err := LoadImports(inputs, doc); err != nil {
		t.Fatal(err)
	}
	if len(doc.ImportDocs) != 2 {
		t.Fatalf("imports loaded: %v", doc.ImportDocs)
	}
	for _, is := range model.ValidateWithImports(doc) {
		if is.Severity == model.SeverityError {
			t.Errorf("%s: %s", is.Path, is.Message)
		}
	}
	merged, err := model.MergeImports(doc, doc.ImportDocs)
	if err != nil {
		t.Fatal(err)
	}
	if len(merged.Scenarios) == 0 {
		t.Fatal("no scenarios")
	}
	for _, sc := range merged.Scenarios {
		r, err := sim.Run(merged, sim.Request{Scenario: sc.ID})
		if err != nil {
			t.Fatalf("%s: %v", sc.ID, err)
		}
		if !r.Summary.Passed {
			t.Errorf("%s failed: %+v", sc.ID, r.Summary.Assertions)
		}
	}
}

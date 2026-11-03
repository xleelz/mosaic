package sim_test

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// loadExample parses the shared inference gateway fixture.
func loadExample(t *testing.T) *model.Document {
	t.Helper()
	data, err := os.ReadFile("../testdata/gateway/ontology.yaml")
	if err != nil {
		t.Fatal(err)
	}
	doc, err := model.ParseDocument(data)
	if err != nil {
		t.Fatal(err)
	}
	return doc
}

// TestExampleValidates requires the fixture to have no validation errors.
func TestExampleValidates(t *testing.T) {
	for _, is := range model.Validate(loadExample(t)) {
		if is.Severity == model.SeverityError {
			t.Errorf("%s: %s", is.Path, is.Message)
		}
	}
}

// TestExampleScenarios is the acceptance test: every scenario of the gateway
// fixture must meet its expectations, with no warnings.
func TestExampleScenarios(t *testing.T) {
	doc := loadExample(t)
	if len(doc.Scenarios) < 12 {
		t.Fatalf("expected at least 12 scenarios, got %d", len(doc.Scenarios))
	}
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			res, err := sim.Run(doc, sim.Request{Scenario: sc.ID})
			if err != nil {
				t.Fatal(err)
			}
			s := res.Summary
			if s.Status == "aborted" {
				t.Fatalf("aborted: %s", s.Abort)
			}
			if len(s.Assertions) != len(sc.Expect) {
				t.Fatalf("evaluated %d of %d expectations", len(s.Assertions), len(sc.Expect))
			}
			for _, a := range s.Assertions {
				if !a.Passed {
					ctx, _ := json.Marshal(s.Ctx)
					t.Errorf("failed: %s %s\n  result=%+v\n  ctx=%s", a.Expr, a.Error, s.Result, ctx)
				}
			}
			for _, w := range s.Warnings {
				t.Errorf("warning: %s", w)
			}
		})
	}
}

// TestDeterminism requires identical traces for identical requests.
func TestDeterminism(t *testing.T) {
	doc := loadExample(t)
	for _, id := range []string{"happy-path", "retry-before-commit", "upstream-timeout-retry"} {
		a, err := sim.Run(doc, sim.Request{Scenario: id})
		if err != nil {
			t.Fatal(err)
		}
		b, err := sim.Run(loadExample(t), sim.Request{Scenario: id})
		if err != nil {
			t.Fatal(err)
		}
		ja, _ := json.Marshal(a)
		jb, _ := json.Marshal(b)
		if string(ja) != string(jb) {
			t.Errorf("%s: two runs differ", id)
		}
	}
}

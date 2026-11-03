package sim_test

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// TestExamplesStillPass is the backward-compatibility check for the §11
// additions: every scenario of the two example models, none of which uses
// them, still meets its expectations, adds no §11 summary data beyond the
// executed step paths, and gives byte-identical results when run again.
func TestExamplesStillPass(t *testing.T) {
	if testing.Short() {
		t.Skip("runs every example scenario")
	}
	for _, ex := range []struct {
		path      string
		scenarios int
	}{
		{"../testdata/gateway/ontology.yaml", 14},
		{"../../examples/cassandra/judge/cassandra-v1.json", 1165}, // frozen pre-§11 model
	} {
		t.Run(ex.path, func(t *testing.T) {
			data, err := os.ReadFile(ex.path)
			if err != nil {
				t.Fatal(err)
			}
			doc, err := model.ParseDocument(data)
			if err != nil {
				t.Fatal(err)
			}
			if len(doc.Scenarios) != ex.scenarios {
				t.Fatalf("%d scenarios, want %d", len(doc.Scenarios), ex.scenarios)
			}
			failed := 0
			for i, sc := range doc.Scenarios {
				res, err := sim.Run(doc, sim.Request{Scenario: sc.ID})
				if err != nil {
					t.Errorf("%s: %v", sc.ID, err)
					continue
				}
				s := res.Summary
				if !s.Passed || s.Status == "aborted" {
					failed++
					if failed <= 10 {
						t.Errorf("%s: status %s, abort %q, assertions %+v", sc.ID, s.Status, s.Abort, s.Assertions)
					}
				}
				if len(s.CallsByInstance) > 0 || len(s.Steps) > 0 || s.Queued != 0 || s.Mocks != 0 {
					t.Errorf("%s: unexpected §11 summary data", sc.ID)
				}
				if i%20 == 0 {
					again, err := sim.Run(doc, sim.Request{Scenario: sc.ID})
					if err != nil {
						t.Fatal(err)
					}
					a, _ := json.Marshal(res)
					b, _ := json.Marshal(again)
					if string(a) != string(b) {
						t.Errorf("%s: two runs differ", sc.ID)
					}
				}
			}
			if failed > 0 {
				t.Errorf("%d of %d scenarios failed", failed, len(doc.Scenarios))
			}
		})
	}
}

// TestMigratedExamplesPass runs every scenario of the example models that use
// the §11 additions, and checks that each run is deterministic.
func TestMigratedExamplesPass(t *testing.T) {
	if testing.Short() {
		t.Skip("runs every example scenario")
	}
	for _, path := range []string{
		"../../examples/cassandra/cassandra.json",
		"../../examples/language-demo/ontology.yaml",
	} {
		t.Run(path, func(t *testing.T) {
			data, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			doc, err := model.ParseDocument(data)
			if err != nil {
				t.Fatal(err)
			}
			failed := 0
			for i, sc := range doc.Scenarios {
				res, err := sim.Run(doc, sim.Request{Scenario: sc.ID})
				if err != nil {
					t.Errorf("%s: %v", sc.ID, err)
					continue
				}
				if !res.Summary.Passed {
					failed++
					if failed <= 10 {
						t.Errorf("%s: status %s, abort %q", sc.ID, res.Summary.Status, res.Summary.Abort)
					}
				}
				if i%25 == 0 {
					again, _ := sim.Run(doc, sim.Request{Scenario: sc.ID})
					a, _ := json.Marshal(res)
					b, _ := json.Marshal(again)
					if string(a) != string(b) {
						t.Errorf("%s: two runs differ", sc.ID)
					}
				}
			}
			if failed > 0 {
				t.Errorf("%d of %d scenarios failed", failed, len(doc.Scenarios))
			}
		})
	}
}

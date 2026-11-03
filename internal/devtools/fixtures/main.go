// Command fixtures writes API-shaped JSON for the example ontologies so the web
// UI can be developed and tested without a running mosaicd. By default it
// writes the §11 language demo and the Envoy worked example; -in (repeatable)
// picks other documents. ontologies.json lists every generated ontology.
//
//	go run ./internal/devtools/fixtures -out web/fixtures [-in doc.yaml]...
package main

import (
	"encoding/json"
	"flag"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
	"github.com/xleelz/mosaic/pkg/api"
)

type inputs []string

func (f *inputs) String() string     { return strings.Join(*f, ",") }
func (f *inputs) Set(v string) error { *f = append(*f, v); return nil }

func main() {
	var in inputs
	flag.Var(&in, "in", "ontology document; repeatable (default: the language demo and the Envoy example)")
	out := flag.String("out", "web/fixtures", "output directory")
	flag.Parse()
	if len(in) == 0 {
		in = inputs{"examples/language-demo/ontology.yaml", "examples/envoy/ontology.yaml"}
	}
	list := api.OntologyList{Ontologies: []api.OntologySummary{}}
	for _, path := range in {
		list.Ontologies = append(list.Ontologies, generate(path, *out))
	}
	write(filepath.Join(*out, "ontologies.json"), list)
}

// generate writes one ontology's fixtures under out/<id> and returns its summary.
func generate(in, out string) api.OntologySummary {
	data, err := os.ReadFile(in)
	check(err)
	doc, err := model.ParseDocument(data)
	check(err)
	dir := filepath.Join(out, doc.ID)
	check(os.MkdirAll(filepath.Join(dir, "runs"), 0o755))
	at := time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)
	x := model.NewIndex(doc)
	summary := api.OntologySummary{ID: doc.ID, Name: doc.Name, Description: doc.Description, CreatedAt: at, UpdatedAt: at, LatestRevision: 1, RevisionCount: 1}
	counts := map[string]int{"component": len(doc.Components), "interface": len(doc.Interfaces), "link": len(doc.Links), "schema": len(doc.Schemas), "flow": len(doc.Flows), "scenario": len(doc.Scenarios)}
	if len(doc.Configs) > 0 || len(doc.Fixtures) > 0 {
		counts["config"], counts["fixture"] = len(doc.Configs), len(doc.Fixtures)
	}
	write(filepath.Join(dir, "detail.json"), api.OntologyDetail{OntologySummary: summary, Counts: counts})
	write(filepath.Join(dir, "document.json"), doc)
	write(filepath.Join(dir, "graph.json"), x.Graph())
	msg := "Model " + doc.Name
	write(filepath.Join(dir, "revisions.json"), api.RevisionList{Revisions: []api.Revision{{Number: 1, Hash: "64sdvkii8b4tpbf8mod7hihrkjdaset6", Message: msg, Author: "Mosaic <mosaic@localhost>", CreatedAt: at}}})
	issues := model.Validate(doc)
	write(filepath.Join(dir, "validation.json"), api.Validation{Revision: "draft", Valid: !model.HasErrors(issues), Issues: append([]model.Issue{}, issues...)})
	report := api.TestReport{Revision: "1", Passed: true}
	for _, f := range doc.Flows {
		p, err := x.Plan(f.ID)
		check(err)
		write(filepath.Join(dir, "plan."+f.ID+".json"), p)
	}
	for i, sc := range doc.Scenarios {
		res, err := sim.Run(doc, sim.Request{Scenario: sc.ID})
		check(err)
		run := api.SimulationRun{ID: "run_fixture_" + sc.ID, Ontology: doc.ID, Revision: "1", Flow: sc.Flow, Scenario: sc.ID,
			CreatedAt: at.Add(time.Duration(i) * time.Minute), Request: res.Request, Summary: res.Summary, Trace: res.Trace}
		write(filepath.Join(dir, "runs", sc.ID+".json"), run)
		report.Total++
		r := api.TestResult{Scenario: sc.ID, Name: sc.Name, Passed: res.Summary.Passed, Status: res.Summary.Status, Assertions: res.Summary.Assertions, RunID: run.ID}
		if !r.Passed {
			report.Failed++
			report.Passed = false
		}
		report.Results = append(report.Results, r)
	}
	write(filepath.Join(dir, "test-report.json"), report)
	return summary
}

func write(path string, v any) {
	b, err := json.MarshalIndent(v, "", "  ")
	check(err)
	check(os.WriteFile(path, append(b, '\n'), 0o644))
}

func check(err error) {
	if err != nil {
		log.Fatal(err)
	}
}

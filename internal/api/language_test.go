package api_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	wire "github.com/xleelz/mosaic/pkg/api"
)

// langDoc uses the §11 kinds (config, fixture) and a multi-step, mocked and
// instanced set of scenarios.
const langDoc = `
schema_version: 1
components:
  - {id: client}
  - {id: node}
  - {id: storage, parent: node}
configs:
  - {id: timeout-ms, type: integer, value: 2000, default: 1000}
fixtures:
  - {id: base, config: {timeout-ms: 300}}
  - {id: three, topology: {node: [n1, n2, n3]}, extends: [base], clock: {epoch_ms: 1000}}
interfaces:
  - component: node
    name: read
    behavior:
      - {call: storage.get, as: got}
      - return: {timeout: "= config['timeout-ms']", self: "= self", now: "= now", got: "= vars.got"}
  - component: storage
    name: get
    behavior: [{return: real}]
flows:
  - id: read
    entry: {caller: client, interface: node.read}
scenarios:
  - id: plain
    flow: read
    expect: ["result.value.timeout == 2000", "result.value.self == ''"]
  - id: fixtured
    flow: read
    fixtures: [three]
    expect: ["result.value.timeout == 300", "result.value.self == 'n1'"]
  - id: two-steps
    fixtures: [three]
    steps:
      - {flow: read, as: a}
      - {flow: read, on: n2, as: b}
    expect: ["steps.a.result.ok", "result.value.self == 'n2'"]
  - id: mocked
    flow: read
    mocks: [{interface: storage.get, return: fake}]
    expect: ["result.value.got.value == 'fake'"]
`

func langOntology(t *testing.T, id string) string {
	t.Helper()
	doc, err := model.ParseDocument([]byte(langDoc))
	if err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(doc)
	call(t, "POST", "/v1/ontologies", wire.CreateOntology{ID: id, Name: id}, 201)
	res := decode[wire.PutDocumentResult](t, call(t, "PUT", "/v1/ontologies/"+id+"/document", b, 200))
	if !res.Valid {
		t.Fatalf("langDoc does not validate: %+v", res.Issues)
	}
	if res.Counts["config"] != 1 || res.Counts["fixture"] != 2 {
		t.Fatalf("counts = %v", res.Counts)
	}
	return "/v1/ontologies/" + id
}

func TestConfigAndFixtureEntities(t *testing.T) {
	base := langOntology(t, "lang-entities")
	call(t, "POST", base+"/revisions", wire.CreateRevision{Message: "r1"}, 201)

	d := decode[wire.OntologyDetail](t, call(t, "GET", base, nil, 200))
	if d.Counts["config"] != 1 || d.Counts["fixture"] != 2 {
		t.Fatalf("detail counts = %v", d.Counts)
	}
	// List and read, singular and plural paths.
	items := decode[wire.Items](t, call(t, "GET", base+"/configs", nil, 200))
	if len(items.Items) != 1 {
		t.Fatalf("configs = %s", items.Items)
	}
	fx := decode[model.Fixture](t, call(t, "GET", base+"/fixture/three", nil, 200))
	if len(fx.Topology["node"]) != 3 || len(fx.Extends) != 1 || fx.Clock == nil || fx.Clock.EpochMS != 1000 {
		t.Fatalf("fixture = %+v", fx)
	}
	// Create, upsert, patch, delete.
	call(t, "POST", base+"/configs", `{"id":"retries","type":"integer","value":3}`, 201)
	call(t, "POST", base+"/configs", `{"id":"retries","value":4}`, 409)
	call(t, "PUT", base+"/configs/retries", `{"id":"retries","type":"integer","value":5,"default":3}`, 200)
	call(t, "PATCH", base+"/configs/retries", `{"value":6}`, 200)
	c := decode[model.Config](t, call(t, "GET", base+"/configs/retries", nil, 200))
	if c.Value != float64(6) || c.Default != float64(3) {
		t.Fatalf("patched config = %+v", c)
	}
	call(t, "POST", base+"/configs", `{"id":"bad","colour":1}`, 400)
	call(t, "PUT", base+"/fixtures", `{"items":[{"id":"extra","config":{"timeout-ms":1},"extends":["three"]}]}`, 200)
	// A fixture extending an unknown one is reported by validation.
	res := decode[wire.UpsertResult](t, call(t, "PUT", base+"/fixtures/broken", `{"id":"broken","extends":["nope"]}`, 200))
	if res.Kind != "fixture" || !hasIssue(res.Issues, "fixtures") {
		t.Fatalf("broken fixture issues = %+v", res.Issues)
	}
	call(t, "DELETE", base+"/fixtures/broken", nil, 204)
	call(t, "DELETE", base+"/fixtures/broken", nil, 404)

	// Diff, revisions and export carry the new kinds.
	diff := decode[wire.Diff](t, call(t, "GET", base+"/diff", nil, 200))
	got := map[string]string{}
	for _, ch := range diff.Changes {
		got[ch.Kind+"/"+ch.ID] = ch.Change
	}
	if got["config/retries"] != "added" || got["fixture/extra"] != "added" || len(got) != 2 {
		t.Fatalf("diff = %v", got)
	}
	call(t, "POST", base+"/revisions", wire.CreateRevision{Message: "r2"}, 201)
	var doc model.Document
	if err := json.Unmarshal(call(t, "GET", base+"/document?rev=1", nil, 200), &doc); err != nil {
		t.Fatal(err)
	}
	if len(doc.Configs) != 1 || len(doc.Fixtures) != 2 {
		t.Fatalf("r1 export: %d configs, %d fixtures", len(doc.Configs), len(doc.Fixtures))
	}
	if err := json.Unmarshal(call(t, "GET", base+"/document?rev=latest", nil, 200), &doc); err != nil {
		t.Fatal(err)
	}
	if len(doc.Configs) != 2 || len(doc.Fixtures) != 3 {
		t.Fatalf("r2 export: %d configs, %d fixtures", len(doc.Configs), len(doc.Fixtures))
	}
	if l := decode[wire.Items](t, call(t, "GET", base+"/configs?rev=1", nil, 200)); len(l.Items) != 1 {
		t.Fatalf("configs at r1 = %d", len(l.Items))
	}
	// A draft holding only configs and fixtures is not empty.
	call(t, "POST", "/v1/ontologies", wire.CreateOntology{ID: "lang-only-config", Name: "x"}, 201)
	call(t, "POST", "/v1/ontologies/lang-only-config/configs", `{"id":"k","value":1}`, 201)
	call(t, "POST", "/v1/ontologies/lang-only-config/revisions", wire.CreateRevision{Message: "r1"}, 201)
	// Unknown kinds name the new ones.
	if e := errCode(t, call(t, "GET", base+"/widgets", nil, 404)); !strings.Contains(e.Message, "fixtures") {
		t.Fatalf("unknown kind message = %q", e.Message)
	}
}

func hasIssue(issues []model.Issue, prefix string) bool {
	for _, i := range issues {
		if strings.HasPrefix(i.Path, prefix) {
			return true
		}
	}
	return false
}

func TestSimulationWorldAndScenarios(t *testing.T) {
	base := langOntology(t, "lang-sims")

	// fixtures, topology, config and clock pass through to the engine.
	run := decode[wire.SimulationRun](t, call(t, "POST", base+"/simulations",
		`{"flow":"read","fixtures":["three"],"topology":{"node":["a","b"]},"config":{"timeout-ms":42},"clock":{"epoch_ms":5000},`+
			`"expect":["result.value.timeout == 42","result.value.self == 'a'","result.value.now >= 5000"],"save":false}`, 200))
	if !run.Summary.Passed {
		t.Fatalf("world run = %+v", run.Summary)
	}
	if len(run.Request.Fixtures) != 1 || len(run.Request.Topology["node"]) != 2 || run.Request.Config["timeout-ms"] == nil || run.Request.Clock == nil {
		t.Fatalf("request echo = %+v", run.Request)
	}
	call(t, "POST", base+"/simulations", `{"flow":"read","fixtures":["nope"]}`, 400)

	// A multi-step scenario is listed under its first step's flow.
	steps := decode[wire.SimulationRun](t, call(t, "POST", base+"/simulations", `{"scenario":"two-steps"}`, 201))
	if !steps.Summary.Passed || steps.Flow != "read" || len(steps.Summary.Steps) != 2 {
		t.Fatalf("steps run: flow %q, summary %+v", steps.Flow, steps.Summary)
	}
	list := decode[wire.RunList](t, call(t, "GET", base+"/simulations", nil, 200))
	if len(list.Runs) != 1 || list.Runs[0].Flow != "read" || list.Runs[0].Scenario != "two-steps" || len(list.Runs[0].Summary.Steps) != 2 {
		t.Fatalf("listed runs = %+v", list.Runs)
	}

	rep := decode[wire.TestReport](t, call(t, "POST", base+"/test?save=false", nil, 200))
	if !rep.Passed || rep.Total != 4 {
		t.Fatalf("test report = %+v", rep)
	}
	by := map[string]wire.TestResult{}
	for _, r := range rep.Results {
		by[r.Scenario] = r
	}
	if by["two-steps"].Steps != 2 || by["plain"].Steps != 0 {
		t.Fatalf("steps counts = %+v", by)
	}
	if m := by["mocked"]; m.Mocks != 1 || m.MockedCalls != 1 {
		t.Fatalf("mock counts = %+v", m)
	}
}

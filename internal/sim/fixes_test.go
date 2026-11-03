package sim_test

import (
	"os"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

func loadDemo(t *testing.T) *model.Document {
	t.Helper()
	data, err := os.ReadFile("../../examples/language-demo/ontology.yaml")
	if err != nil {
		t.Skip("no language demo")
	}
	doc, err := model.ParseDocument(data)
	if err != nil {
		t.Fatal(err)
	}
	return doc
}

// TestJoinTimesOutAtDeadline: branches that fail because their calls hit
// the inherited deadline make the join time out, not report insufficient.
func TestJoinTimesOutAtDeadline(t *testing.T) {
	doc := loadDemo(t)
	res := run(t, doc, sim.Request{Scenario: "kv-silent-replicas-time-out",
		Config: map[string]any{"kv-write-timeout-ms": 2000, "kv-request-deadline-ms": 400}})
	var end *sim.Event
	for i, e := range res.Trace {
		if e.Type == "parallel.end" {
			end = &res.Trace[i]
		}
	}
	if end == nil || end.Error == nil || end.Error.Code != "timeout" || !end.Error.Retryable ||
		!jsonEq(end.Error.Data, map[string]any{"received": 1, "required": 2}) {
		t.Fatalf("parallel.end %+v", end)
	}
	if e := res.Summary.Result.Error; e == nil || e.Code != "write-timeout" {
		t.Errorf("result %+v", res.Summary.Result)
	}
}

// TestDemoScenarios: every scenario of the language demo passes.
func TestDemoScenarios(t *testing.T) {
	doc := loadDemo(t)
	for _, sc := range doc.Scenarios {
		passes(t, doc, sim.Request{Scenario: sc.ID})
	}
}

// TestDeadlineTemplatesAndEvents: entry and scenario step deadline_ms take
// "=cel"; timeout and deadline events describe the caller; store set events
// carry table and key.
func TestDeadlineTemplatesAndEvents(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: client}
  - {id: node}
  - {id: svc, parent: node}
  - {id: db, parent: node}
configs:
  - {id: budget-ms, type: integer, value: 50}
interfaces:
  - component: svc
    name: main
    latency_ms: 0
    behavior:
      - {call: db.put, input: {id: a.b, v: 1}}
      - {call: db.slow, on_error: continue}
      - {call: db.slow, on_error: continue}
  - {component: db, name: slow, latency_ms: 80}
  - {component: db, name: put, latency_ms: 1, store: {table: rows, op: put, key: "= input.id", value: "= input"}}
flows:
  - {id: main, entry: {caller: client, interface: svc.main, deadline_ms: "= config['budget-ms']"}}
scenarios:
  - id: stepped
    topology: {node: [n1, n2]}
    steps:
      - {flow: main, on: n2, deadline_ms: "= config['budget-ms'] / 2"}
    expect: ["duration_ms == 25", "trace.exists(e, e.type == 'set' && e.table == 'rows' && e.key == 'a.b')"]
`)
	res := run(t, doc, sim.Request{Flow: "main", Topology: map[string][]string{"node": {"n1", "n2"}}})
	eq(t, "entry deadline from config", res.Summary.DurationMS, int64(50))
	to, dl := events(res, "timeout"), events(res, "deadline")
	if len(to) != 1 || to[0].Component != "svc" || to[0].Instance != "n1" {
		t.Errorf("timeout %+v", to)
	}
	if len(dl) != 1 || dl[0].Component != "svc" || dl[0].Instance != "n1" || dl[0].To != "db" {
		t.Errorf("deadline %+v", dl)
	}
	sets := events(res, "set")
	if len(sets) != 1 || sets[0].Table != "rows" || sets[0].Key != "a.b" || sets[0].Path != "state.rows.a.b" {
		t.Errorf("store set %+v", sets)
	}
	passes(t, doc, sim.Request{Scenario: "stepped"})
}

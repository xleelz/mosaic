package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

func jv(t *testing.T, s string) any {
	t.Helper()
	var v any
	if err := json.Unmarshal([]byte(s), &v); err != nil {
		t.Fatal(err)
	}
	return v
}

func TestCompareStateMasksTiming(t *testing.T) {
	epoch := int64(1790812800000) // 2026-10-01T00:00:00Z
	pa, pb := clockSpan{EpochMS: epoch, DurMS: 4000}, clockSpan{EpochMS: epoch, DurMS: 4500}
	cases := []struct {
		name, a, b   string
		diffs, times int
	}{
		{"clock read", `{"last_resync_ms": 1790812845059, "tick": 4}`, `{"last_resync_ms": 1790812845078, "tick": 4}`, 0, 1},
		{"named duration", `{"elapsed": 30}`, `{"elapsed": 45}`, 0, 1},
		{"stamp", `{"createdAt": "2026-10-01T00:00:01Z"}`, `{"createdAt": "2026-10-01T00:00:03Z"}`, 0, 1},
		{"seconds ttl", `{"ttl": 1790812801}`, `{"ttl": 1790812803}`, 0, 1},
		{"id with the clock in it", `{"id": "audit-1790812800048-ok"}`, `{"id": "audit-1790812800051-ok"}`, 0, 1},
		{"key with the clock in it", `{"AUDIT#1790812800048": {"at": 1790812800048, "n": 1}}`, `{"AUDIT#1790812800051": {"at": 1790812800051, "n": 1}}`, 0, 2},
		{"counter", `{"tick": 4}`, `{"tick": 5}`, 1, 0},
		{"unnamed small number", `{"amount": 30}`, `{"amount": 45}`, 1, 0},
		{"beyond the runs' durations", `{"createdAt": "2026-10-01T00:00:01Z"}`, `{"createdAt": "2026-10-01T01:00:00Z"}`, 1, 0},
		{"timing plus a real difference", `{"at_ms": 1790812800001, "status": "open"}`, `{"at_ms": 1790812800002, "status": "closed"}`, 1, 1},
		{"extra key", `{"a": 1}`, `{"a": 1, "b": 2}`, 1, 0},
		{"array length", `{"xs": [1]}`, `{"xs": [1, 2]}`, 1, 0},
		{"type", `{"at_ms": 1790812800001}`, `{"at_ms": "1790812800001"}`, 1, 0},
		{"text around the clock differs", `{"id": "a-1790812800048"}`, `{"id": "b-1790812800051"}`, 1, 0},
	}
	for _, c := range cases {
		r := compareState(jv(t, c.a), jv(t, c.b), pa, pb)
		if len(r.Diffs) != c.diffs || len(r.Timing) != c.times {
			t.Errorf("%s: want %d diffs, %d timing; got %v / %v", c.name, c.diffs, c.times, r.Diffs, r.Timing)
		}
	}
	// No real-date epoch: only time names count.
	r := compareState(jv(t, `{"v": 1200, "t_ms": 1200}`), jv(t, `{"v": 1300, "t_ms": 1300}`), clockSpan{DurMS: 2000}, clockSpan{DurMS: 2000})
	if len(r.Diffs) != 1 || r.Diffs[0].Path != ".v" || len(r.Timing) != 1 {
		t.Errorf("epoch 0: got %v / %v", r.Diffs, r.Timing)
	}
}

// refTimedParent stamps the time of the answer into the store, so a slower
// child changes the state the expectations read only by timing.
const refTimedParent = `schema_version: 1
id: shop
level: service
components:
  - {id: client}
  - {id: api}
  - {id: engine}
  - {id: db}
interfaces:
  - component: engine
    name: serve
    latency_ms: 5
    behavior:
      - {return: {text: "= 'n' + string(input.n)"}}
  - {component: db, name: put, store: {table: answers, op: put, key: "= input.id", value: "= input.row"}}
  - component: api
    name: handle
    behavior:
      - {call: engine.serve, input: {n: "= input.n"}, as: out}
      - {call: db.put, input: {id: "a", row: {text: "= vars.out.value.text", answered_at: "= now", seen: "= now"}}}
      - {return: "= vars.out.value"}
flows:
  - {id: handle, entry: {caller: client, interface: api.handle}}
scenarios:
  - id: answers
    flow: handle
    input: {n: 1}
    clock: {epoch: "2026-10-01T00:00:00Z"}
    expect: ["result.ok", "state.db.answers['a'].text == 'n1'"]
`

const refTimedChild = `schema_version: 1
id: engine-logic
level: logic
refines: {ontology: shop, component: engine}
components:
  - {id: front}
interfaces:
  - component: front
    name: serve
    implements: engine.serve
    latency_ms: 40
    behavior:
      - {return: {text: "= 'n' + string(input.n)"}}
`

func TestRefinementStateTimingIsNotADifference(t *testing.T) {
	p, err := model.ParseDocument([]byte(refTimedParent))
	if err != nil {
		t.Fatal(err)
	}
	c, err := model.ParseDocument([]byte(refTimedChild))
	if err != nil {
		t.Fatal(err)
	}
	r, err := checkRefinement(p, c, refinementOpts{})
	if err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	r.print(&b, false)
	out := b.String()
	if r.differing() != 0 || !strings.Contains(out, "1 scenarios, 1 equal, 0 differ") {
		t.Errorf("timing read back as state counted as a difference:\n%s", out)
	}
	if !strings.Contains(out, "~ answers: timing: state db: answers.a.answered_at: parent ") ||
		!strings.Contains(out, "timing: 1 scenarios read back state that differs only in timing values") {
		t.Errorf("state timing not reported:\n%s", out)
	}
}

func TestRefinementMaxEvents(t *testing.T) {
	// A child that loops long enough to pass a tiny cap: inconclusive at
	// the cap, compared with it raised.
	child := strings.Replace(refTimedChild, "    behavior:\n", "    behavior:\n      - foreach: \"= [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30]\"\n        steps: [{wait: 1}]\n", 1)
	p, _ := model.ParseDocument([]byte(refTimedParent))
	c, err := model.ParseDocument([]byte(child))
	if err != nil {
		t.Fatal(err)
	}
	r, err := checkRefinement(p, c, refinementOpts{MaxEvents: 5})
	if err != nil {
		t.Fatal(err)
	}
	if r.inconclusive() != 1 {
		t.Fatalf("want the capped run inconclusive, got %+v", r.Scenarios[0])
	}
	r, _ = checkRefinement(p, c, refinementOpts{MaxEvents: 100000})
	if r.inconclusive() != 0 || r.differing() != 0 {
		t.Fatalf("want the raised cap compared and equal, got %+v", r.Scenarios[0])
	}
}

func TestExtractContract(t *testing.T) {
	doc, err := model.ParseDocument([]byte(strings.Replace(refParent, "  - {id: engine}\n",
		"  - {id: engine, sources: [{path: \"svc/engine.go:10\"}]}\n  - {id: other, sources: [{path: svc/engine.go}]}\n", 1)))
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	o := extractOpts{Component: "engine", Out: filepath.Join(dir, "c.json"), ScopeOut: filepath.Join(dir, "s.json"),
		Repo: "/repo", ParentTask: "manual"}
	var b bytes.Buffer
	if err := extractContract(&b, doc, []string{"parent.yaml"}, o); err != nil {
		t.Fatal(err)
	}
	var c contractInput
	data, _ := os.ReadFile(o.Out)
	if err := json.Unmarshal(data, &c); err != nil {
		t.Fatal(err)
	}
	// ping never calls the engine; answers and overloaded do.
	if strings.Join(c.Interfaces, ",") != "engine.serve" || strings.Join(c.Scenarios, ",") != "answers,overloaded" {
		t.Errorf("contract: %+v", c)
	}
	if c.Parent.Task != "manual" || c.Parent.Ontology != "shop" || !filepath.IsAbs(c.Parent.Document) {
		t.Errorf("parent: %+v", c.Parent)
	}
	if l := c.LatencyMS["engine.serve"]; l == nil || l.Min != 5 || l.Max != 5 {
		t.Errorf("latency: %+v", c.LatencyMS)
	}
	var s scopeInput
	data, _ = os.ReadFile(o.ScopeOut)
	_ = json.Unmarshal(data, &s)
	if s.Repo != "/repo" || s.Component != "engine" || strings.Join(s.Paths, ",") != "svc/engine.go" {
		t.Errorf("scope: %+v", s)
	}
	if !strings.Contains(b.String(), "hint: other also cites svc/engine.go") {
		t.Errorf("no sibling hint:\n%s", b.String())
	}
	o.MaxScenarios = 1
	b.Reset()
	if err := extractContract(&b, doc, nil, o); err != nil {
		t.Fatal(err)
	}
	data, _ = os.ReadFile(o.Out)
	_ = json.Unmarshal(data, &c)
	if len(c.Scenarios) != 1 || !strings.Contains(b.String(), "2 crossing scenarios (kept 1") {
		t.Errorf("--max-scenarios: %v\n%s", c.Scenarios, b.String())
	}
	o.Component = "engin"
	if err := extractContract(&b, doc, nil, o); err == nil || !strings.Contains(err.Error(), `no component "engin"`) {
		t.Errorf("unknown component: %v", err)
	}
}

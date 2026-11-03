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

// refParent is a service whose api calls an engine and records the answer in
// a store; the engine is the component refined.
const refParent = `schema_version: 1
id: shop
level: service
components:
  - {id: client}
  - {id: api}
  - {id: engine}
  - {id: db}
schemas:
  - id: serve-req
    schema: {type: object, properties: {n: {type: integer}}, required: [n]}
  - id: serve-resp
    schema: {type: object, properties: {text: {type: string}}}
interfaces:
  - component: engine
    name: serve
    latency_ms: 5
    request: serve-req
    response: serve-resp
    errors: [{code: overloaded, status: 503}]
    behavior:
      - if: "input.n > 10"
        then: [{fail: {code: overloaded, status: 503}}]
      - {return: {text: "= 'n' + string(input.n)"}}
  - {component: db, name: put, store: {table: answers, op: put, key: "= input.id", value: "= input.row"}}
  - component: api
    name: handle
    behavior:
      - {call: engine.serve, input: {n: "= input.n"}, as: out}
      - {call: db.put, input: {id: "a", row: "= vars.out.value"}}
      - {return: "= vars.out.value"}
  - {component: api, name: ping, behavior: [{return: {pong: true}}]}
flows:
  - {id: handle, entry: {caller: client, interface: api.handle}}
  - {id: ping, entry: {caller: client, interface: api.ping}}
scenarios:
  - id: answers
    flow: handle
    input: {n: 1}
    expect: ["result.ok", "calls['db.put'] == 1", "state.db.answers['a'].text == 'n1'"]
  - id: overloaded
    flow: handle
    input: {n: 20}
    expect: ["!result.ok", "result.error.code == 'overloaded'", "calls['db.put'] == 0"]
  - id: ping
    flow: ping
    expect: ["result.ok"]
`

// refChild refines engine at the logic level: serve goes through a
// scheduler step. code, latency and the text field's type vary per test.
func refChild(code string, latency int, textType string) string {
	return strings.NewReplacer("CODE", code, "LAT", itoa(latency), "TTYPE", textType).Replace(`schema_version: 1
id: engine-logic
level: logic
refines: {ontology: shop, component: engine}
components:
  - {id: front}
  - {id: sched}
schemas:
  - id: serve-req
    schema: {type: object, properties: {n: {type: integer}}, required: [n]}
  - id: serve-resp
    schema: {type: object, properties: {text: {type: TTYPE}}}
interfaces:
  - component: front
    name: serve
    implements: engine.serve
    latency_ms: 0
    request: serve-req
    response: serve-resp
    errors: [{code: CODE, status: 503}]
    behavior:
      - {call: sched.step, input: {n: "= input.n"}, as: s}
      - {return: "= vars.s.value"}
  - component: sched
    name: step
    latency_ms: LAT
    behavior:
      - if: "input.n > 10"
        then: [{fail: {code: CODE, status: 503}}]
      - {return: {text: "= 'n' + string(input.n)"}}
`)
}

func itoa(n int) string { b, _ := json.Marshal(n); return string(b) }

func refDocs(t *testing.T, child string) (*model.Document, *model.Document) {
	t.Helper()
	p, err := model.ParseDocument([]byte(refParent))
	if err != nil {
		t.Fatal(err)
	}
	c, err := model.ParseDocument([]byte(child))
	if err != nil {
		t.Fatal(err)
	}
	return p, c
}

func checkRef(t *testing.T, child string) (*refinementResult, string) {
	t.Helper()
	p, c := refDocs(t, child)
	r, err := checkRefinement(p, c, refinementOpts{})
	if err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	r.print(&b, false)
	return r, b.String()
}

func TestRefinementMatches(t *testing.T) {
	r, out := checkRef(t, refChild("overloaded", 5, "string"))
	if !strings.Contains(out, "refinement engine <- engine-logic: 2 scenarios, 2 equal, 0 differ") {
		t.Errorf("report:\n%s", out)
	}
	if r.diffCount() != 0 || strings.Contains(out, "✗") {
		t.Errorf("want no differences:\n%s", out)
	}
	if !strings.Contains(out, "implements: 1 pairs, 0 schema issues") {
		t.Errorf("report:\n%s", out)
	}
}

func TestRefinementDifferentErrorCode(t *testing.T) {
	r, out := checkRef(t, refChild("busy", 5, "string"))
	if r.differing() != 1 {
		t.Errorf("want 1 differing scenario:\n%s", out)
	}
	if !strings.Contains(out, "✗ overloaded: result: parent error overloaded (status 503), child error busy (status 503)") {
		t.Errorf("error code difference not reported:\n%s", out)
	}
	// The declared codes disagree too.
	if !strings.Contains(out, "error-missing error overloaded") || !strings.Contains(out, "error-extra error busy") {
		t.Errorf("error code schema issue not reported:\n%s", out)
	}
}

func TestRefinementSlowerChildReportsTiming(t *testing.T) {
	p, _ := refDocs(t, refChild("overloaded", 40, "string"))
	dir := t.TempDir()
	cf := filepath.Join(dir, "child.yaml")
	if err := os.WriteFile(cf, []byte(refChild("overloaded", 40, "string")), 0o644); err != nil {
		t.Fatal(err)
	}
	tf := filepath.Join(dir, "timing.json")
	var b bytes.Buffer
	over, err := runRefinements(&b, p, []string{cf}, refinementOpts{Max: 0, ApplyTiming: tf})
	if err != nil {
		t.Fatal(err)
	}
	out := b.String()
	if over {
		t.Errorf("timing alone failed the gate:\n%s", out)
	}
	for _, want := range []string{"2 equal, 0 differ", "~ answers: timing: parent 5 ms, child 40 ms", "timing: parent 10 ms, child 80 ms", "✓ refinement differences: 0 (max 0)"} {
		if !strings.Contains(out, want) {
			t.Errorf("output lacks %q:\n%s", want, out)
		}
	}
	raw, err := os.ReadFile(tf)
	if err != nil {
		t.Fatal(err)
	}
	var rep struct {
		Refinements []struct {
			Component  string `json:"component"`
			Interfaces []struct {
				Interface     string            `json:"interface"`
				LatencyMS     json.RawMessage   `json:"latency_ms"`
				LatencySource map[string]string `json:"latency_source"`
				Samples       int               `json:"samples"`
				Applies       bool              `json:"applies"`
			} `json:"interfaces"`
		} `json:"refinements"`
	}
	if err := json.Unmarshal(raw, &rep); err != nil {
		t.Fatal(err)
	}
	if len(rep.Refinements) != 1 || len(rep.Refinements[0].Interfaces) != 1 {
		t.Fatalf("timing report:\n%s", raw)
	}
	e := rep.Refinements[0].Interfaces[0]
	if e.Interface != "engine.serve" || string(e.LatencyMS) != "40" || e.LatencySource["refined"] != "engine-logic@local" || e.Samples != 2 || !e.Applies {
		t.Errorf("timing entry:\n%s", raw)
	}
}

func TestRefinementSchemaMismatch(t *testing.T) {
	r, out := checkRef(t, refChild("overloaded", 5, "integer"))
	if !strings.Contains(out, "✗ implements engine.serve <- front.serve: type response.text: parent string, child integer") {
		t.Errorf("schema mismatch not reported:\n%s", out)
	}
	if r.diffCount() == 0 {
		t.Errorf("schema issue not counted:\n%s", out)
	}
	var b bytes.Buffer
	dir := t.TempDir()
	cf := filepath.Join(dir, "child.yaml")
	if err := os.WriteFile(cf, []byte(refChild("overloaded", 5, "integer")), 0o644); err != nil {
		t.Fatal(err)
	}
	p, _ := refDocs(t, refChild("overloaded", 5, "integer"))
	over, err := runRefinements(&b, p, []string{cf}, refinementOpts{Max: 0})
	if err != nil || !over {
		t.Errorf("--max-refinement-diffs 0 should fail on a schema issue (over %v, err %v):\n%s", over, err, b.String())
	}
}

// TestRefinementRefinedRunAddsWorldAndDynamicCalls runs the composed
// document end to end: the import resolves by path, the dynamic call
// reaches the renamed worker, and the world's topology and state apply.
func TestRefinementImportByPathAndWorld(t *testing.T) {
	dir := t.TempDir()
	sub := `schema_version: 1
id: sub
components: [{id: disp}, {id: worker}]
interfaces:
  - component: disp
    name: run
    behavior:
      - {call: "= 'worker.' + input.op", targets: [worker.add], input: {n: "= input.n"}, on: w0, as: r}
      - {return: "= vars.r.value"}
  - {component: worker, name: add, behavior: [{return: {text: "= 'n' + string(input.n + state.bias)"}}]}
fixtures:
  - {id: one-worker, topology: {worker: [w0]}, state: {"worker@w0": {bias: 0}}}
`
	child := `schema_version: 1
id: engine-sub
level: logic
refines: {ontology: shop, component: engine}
imports: [{ontology: sub.yaml, as: s}]
fixtures: [{id: world, attributes: {world: true}, extends: [s/one-worker]}]
components: [{id: front}]
interfaces:
  - component: front
    name: serve
    implements: engine.serve
    errors: [{code: overloaded, status: 503}]
    request: {type: object, properties: {n: {type: integer}}, required: [n]}
    response: {type: object, properties: {text: {type: string}}}
    behavior:
      - if: "input.n > 10"
        then: [{fail: {code: overloaded, status: 503}}]
      - {call: s/disp.run, input: {op: add, n: "= input.n"}, as: r}
      - {return: "= vars.r.value"}
`
	for name, body := range map[string]string{"sub.yaml": sub, "child.yaml": child} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	c, err := loadRefinement(filepath.Join(dir, "child.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	p, _ := refDocs(t, refChild("overloaded", 5, "string"))
	r, err := checkRefinement(p, c, refinementOpts{})
	if err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	r.print(&b, false)
	out := b.String()
	if !strings.Contains(out, "2 scenarios, 2 equal, 0 differ") || strings.Contains(out, "✗") {
		t.Errorf("report:\n%s", out)
	}
}

// TestRefinementDeclaredCalleeErrors: an implementing interface that calls a
// child server answers that server's declared errors, not every code raised
// and handled inside it.
func TestRefinementDeclaredCalleeErrors(t *testing.T) {
	child := `schema_version: 1
id: engine-logic
level: logic
refines: {ontology: shop, component: engine}
components: [{id: front}, {id: server}, {id: inner}]
interfaces:
  - component: front
    name: serve
    implements: engine.serve
    request: {type: object, properties: {n: {type: integer}}, required: [n]}
    response: {type: object, properties: {text: {type: string}}}
    behavior:
      - {call: server.handle, input: "= input", as: r}
      - {return: "= vars.r.value"}
  - component: server
    name: handle
    errors: [{code: overloaded, status: 503}]
    behavior:
      - {call: inner.step, input: "= input", as: s, on_error: [{fail: {code: overloaded, status: 503}}]}
      - {return: {text: "= 'n' + string(input.n)"}}
  - component: inner
    name: step
    behavior:
      - if: "input.n > 10"
        then: [{fail: {code: key-error}}]
      - {return: {}}
`
	_, out := checkRef(t, child)
	if strings.Contains(out, "keyerror") || !strings.Contains(out, "implements: 1 pairs, 0 schema issues") {
		t.Errorf("internal codes leaked:\n%s", out)
	}
}

// TestRefinementCappedRunIsInconclusive: a refined run ended by its event
// budget has no outcome; it is reported, not counted as equal or differing.
func TestRefinementCappedRunIsInconclusive(t *testing.T) {
	child := strings.Replace(refChild("overloaded", 5, "string"),
		"      - {call: sched.step, input: {n: \"= input.n\"}, as: s}\n",
		"      - {foreach: \"= lists.range(90)\", as: i, steps: [{foreach: \"= lists.range(90)\", as: j, steps: [{call: sched.step, input: {n: 1}}, {call: sched.step, input: {n: 1}}]}]}\n      - {call: sched.step, input: {n: \"= input.n\"}, as: s}\n", 1)
	r, out := checkRef(t, child)
	if r.inconclusive() == 0 || r.differing() != 0 || !strings.Contains(out, "inconclusive") || !strings.Contains(out, "? answers: not compared") {
		t.Errorf("report:\n%s", out)
	}
	rep := timingReport([]*refinementResult{r})
	b, _ := json.Marshal(rep)
	if !strings.Contains(string(b), "inconclusive") || strings.Contains(string(b), `"applies":true`) {
		t.Errorf("timing report: %s", b)
	}
}

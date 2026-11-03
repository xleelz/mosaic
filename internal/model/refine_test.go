package model_test

import (
	"os"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

func loadRefine(t *testing.T, name string) *model.Document {
	t.Helper()
	data, err := os.ReadFile("testdata/refine/" + name)
	if err != nil {
		t.Fatal(err)
	}
	d, err := model.ParseDocument(data)
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func errorsOf(issues []model.Issue) []model.Issue {
	var out []model.Issue
	for _, is := range issues {
		if is.Severity == model.SeverityError {
			out = append(out, is)
		}
	}
	return out
}

func hasIssue(issues []model.Issue, path, msg string) bool {
	for _, is := range issues {
		if is.Path == path && strings.Contains(is.Message, msg) {
			return true
		}
	}
	return false
}

func TestRefinementDocumentsValidate(t *testing.T) {
	parent, child := loadRefine(t, "parent.yaml"), loadRefine(t, "child.yaml")
	for _, d := range []*model.Document{parent, child} {
		if errs := errorsOf(model.Validate(d)); len(errs) > 0 {
			t.Errorf("%s: %v", d.ID, errs)
		}
	}
	if errs := errorsOf(model.ValidateRefinement(parent, child)); len(errs) > 0 {
		t.Errorf("refinement: %v", errs)
	}
	pairs, err := model.ImplementsPairs(parent, child)
	if err != nil {
		t.Fatal(err)
	}
	if len(pairs) != 1 || pairs[0] != [2]string{"engine.run", "scheduler.submit"} {
		t.Errorf("pairs = %v", pairs)
	}
	if child.Level != model.LevelService || child.Refines.Component != "engine" || parent.Components[3].RefinedBy[0].Ontology != "engine-logic" {
		t.Errorf("hierarchy fields not decoded: %+v %+v", child.Level, child.Refines)
	}
}

func TestRefinementMissingImplements(t *testing.T) {
	child := loadRefine(t, "child.yaml")
	for i := range child.Interfaces {
		child.Interfaces[i].Implements = ""
	}
	issues := model.Validate(child)
	if !hasIssue(issues, "interfaces[scheduler.submit].implements", "must declare implements") {
		t.Errorf("missing implements not caught: %v", issues)
	}
	// worker.execute is called inside the child and metrics is a boundary
	// stub: neither is a boundary interface.
	if got := model.BoundaryInterfaces(child); len(got) != 1 || got[0] != "scheduler.submit" {
		t.Errorf("boundary = %v", got)
	}
}

func TestRefinementBadTarget(t *testing.T) {
	parent, child := loadRefine(t, "parent.yaml"), loadRefine(t, "child.yaml")
	child.Interfaces[0].Implements = "gateway.handle"
	if issues := model.Validate(child); !hasIssue(issues, "interfaces[scheduler.submit].implements", `not the refined component "engine"`) {
		t.Errorf("wrong component not caught: %v", issues)
	}
	child.Interfaces[0].Implements = "engine.nope"
	if errs := errorsOf(model.Validate(child)); len(errs) > 0 {
		t.Errorf("without the parent the target cannot be checked: %v", errs)
	}
	if issues := model.ValidateRefinement(parent, child); !hasIssue(issues, "interfaces[scheduler.submit].implements", `unknown parent interface "engine.nope"`) {
		t.Errorf("unknown target not caught: %v", issues)
	}
	if _, err := model.ImplementsPairs(parent, child); err == nil {
		t.Error("ImplementsPairs accepted an unknown target")
	}
	// The parent loaded alongside (-f parent.yaml -f child.yaml merged).
	merged := *child
	merged.Components = append(append([]model.Component{}, parent.Components...), child.Components[:2]...)
	merged.Interfaces = append(append([]model.Interface{}, parent.Interfaces...), child.Interfaces[:2]...)
	if issues := model.Validate(&merged); !hasIssue(issues, "interfaces[scheduler.submit].implements", `unknown parent interface "engine.nope"`) {
		t.Errorf("unknown target not caught with the parent alongside: %v", issues)
	}
	if _, err := model.ComposeRefinements(parent, map[string]*model.Document{"engine": child}, map[string]string{"engine": "refined"}); err == nil {
		t.Error("composition accepted an unknown target")
	}
}

func TestHierarchyFieldValidation(t *testing.T) {
	d := loadRefine(t, "parent.yaml")
	d.Level = "galaxy"
	d.Imports = []model.ImportRef{{Ontology: "redis", As: "Bad/As"}, {}}
	d.Interfaces[1].LatencySource = &model.LatencySource{Refined: "no-rev"}
	d.Interfaces[2].Implements = "engine.run"
	d.Scenarios[1].Resolution = map[string]string{"engine": "zoomed", "nope": "refined"}
	issues := model.Validate(d)
	for _, want := range [][2]string{
		{"level", "unknown level"},
		{"imports[0].as", "invalid prefix"},
		{"imports[1].ontology", "required"},
		{"interfaces[metrics.record].latency_source.refined", "<ontology>@<rev>"},
		{"interfaces[engine.run].implements", "needs the document's refines"},
		{"scenarios[ask-refined].resolution.engine", "black_box or refined"},
		{"scenarios[ask-refined].resolution.nope", "unknown component"},
	} {
		if !hasIssue(issues, want[0], want[1]) {
			t.Errorf("no issue %s: %s in %v", want[0], want[1], issues)
		}
	}
}

func TestComposeRefinements(t *testing.T) {
	parent, child := loadRefine(t, "parent.yaml"), loadRefine(t, "child.yaml")
	children := map[string]*model.Document{"engine": child}
	same, err := model.ComposeRefinements(parent, children, map[string]string{"engine": "black_box"})
	if err != nil || same != parent {
		t.Fatalf("black box changed the document: %v", err)
	}
	doc, err := model.ComposeRefinements(parent, children, map[string]string{"engine": "refined"})
	if err != nil {
		t.Fatal(err)
	}
	if errs := errorsOf(model.Validate(doc)); len(errs) > 0 {
		t.Errorf("composed document: %v", errs)
	}
	x := model.NewIndex(doc)
	for _, id := range []string{"engine/scheduler", "engine/worker"} {
		c, ok := x.Components[id]
		if !ok || c.Parent != "engine" {
			t.Errorf("component %s missing or not under engine: %+v", id, c)
		}
	}
	if _, ok := x.Components["engine/metrics"]; ok {
		t.Error("the boundary stub was namespaced instead of resolving to the parent's metrics")
	}
	run := x.Interfaces["engine.run"]
	if run.LatencyMS == nil || run.LatencyMS.Max != 0 || len(run.Behavior) != 2 || run.Behavior[0].Call != "engine/scheduler.submit" {
		t.Errorf("engine.run is not a shell: %+v", run)
	}
	if got := x.Interfaces["engine/scheduler.submit"].Behavior[0].Call; got != "engine/worker.execute" {
		t.Errorf("child call not rewired: %s", got)
	}
	if got := x.Interfaces["engine/worker.execute"].Behavior[0].Call; got != "metrics.record" {
		t.Errorf("stub call not resolved to the parent: %s", got)
	}
	// The parent is untouched.
	if parent.Interfaces[2].LatencyMS == nil || len(parent.Components) != 4 {
		t.Error("composition modified the parent")
	}
	if _, err := model.ComposeRefinements(parent, nil, map[string]string{"engine": "refined"}); err == nil || !strings.Contains(err.Error(), "no refinement") {
		t.Errorf("missing child: %v", err)
	}
	if _, err := model.ComposeRefinements(parent, children, map[string]string{"engine/scheduler": "refined"}); err == nil {
		t.Error("a nested refinement without its parent refined was accepted")
	}
}

func TestMergeImports(t *testing.T) {
	kv, err := model.ParseDocument([]byte(`
id: kv
components: [{id: store}]
schemas: [{id: Row, schema: {type: object}}]
interfaces:
  - {component: store, name: get, latency_ms: 2, response: Row, behavior: [{return: {v: 1}}]}
`))
	if err != nil {
		t.Fatal(err)
	}
	d, err := model.ParseDocument([]byte(`
id: app
imports: [{ontology: kv, as: cache}]
components: [{id: app}]
interfaces:
  - {component: app, name: read, behavior: [{call: cache/store.get}]}
`))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := model.MergeImports(d, nil); err == nil {
		t.Error("an unloaded import was accepted")
	}
	m, err := model.MergeImports(d, map[string]*model.Document{"kv": kv})
	if err != nil {
		t.Fatal(err)
	}
	x := model.NewIndex(m)
	f, ok := x.Interfaces["cache/store.get"]
	if !ok || f.Response != "cache.Row" || x.Schemas["cache.Row"] == nil {
		t.Errorf("import not merged under its prefix: %+v", f)
	}
	if errs := errorsOf(model.Validate(m)); len(errs) > 0 {
		t.Errorf("merged document: %v", errs)
	}
}

// TestCompositionKeepsHierarchyMetadata: composing and merging imports keep
// the document's level, refines and imports.
func TestCompositionKeepsHierarchyMetadata(t *testing.T) {
	parent, child := loadRefine(t, "parent.yaml"), loadRefine(t, "child.yaml")
	parent.Imports = []model.ImportRef{{Ontology: "kv", As: "cache"}}
	parent.ImportDocs = map[string]*model.Document{"kv": {ID: "kv"}}
	parent.Refines = &model.RefinesRef{Ontology: "fleet", Component: "shop"}
	doc, err := model.ComposeRefinements(parent, map[string]*model.Document{"engine": child}, map[string]string{"engine": "refined"})
	if err != nil {
		t.Fatal(err)
	}
	if doc.Level != model.LevelSystem || doc.Refines == nil || doc.Refines.Component != "shop" || len(doc.Imports) != 1 || doc.Imports[0].As != "cache" {
		t.Errorf("metadata lost: level %q refines %+v imports %+v", doc.Level, doc.Refines, doc.Imports)
	}
}

// TestShellAddsNoLatency: a refined component's shell interfaces carry an
// explicit 0 ms, not nil (which the simulator would read as its 1 ms default).
func TestShellAddsNoLatency(t *testing.T) {
	parent, child := loadRefine(t, "parent.yaml"), loadRefine(t, "child.yaml")
	doc, err := model.ComposeRefinements(parent, map[string]*model.Document{"engine": child}, map[string]string{"engine": "refined"})
	if err != nil {
		t.Fatal(err)
	}
	l := model.NewIndex(doc).Interfaces["engine.run"].LatencyMS
	if l == nil || l.Min != 0 || l.Max != 0 || l.Expr != "" {
		t.Errorf("shell latency = %+v, want an explicit 0", l)
	}
}

// A substrate with a dynamic call (a dispatcher naming its target by
// expression), an instance topology and a world fixture.
const subDoc = `schema_version: 1
id: sub
components:
  - {id: disp}
  - {id: worker}
interfaces:
  - component: disp
    name: run
    behavior:
      - call: "= 'worker.' + input.op"
        targets: [worker.add, worker.sub]
        input: {n: "= input.n"}
        on: w0
        as: r
      - {return: "= vars.r.value"}
  - component: worker
    name: add
    behavior: [{return: {n: "= input.n + state.bias"}}]
  - component: worker
    name: sub
    behavior: [{return: {n: "= input.n - state.bias"}}]
fixtures:
  - id: one-worker
    topology: {worker: [w0]}
    state: {"worker@w0": {bias: 10}}
`

const subParent = `schema_version: 1
id: app
components:
  - {id: client}
  - {id: api}
  - {id: engine}
interfaces:
  - component: engine
    name: compute
    behavior: [{return: {n: 0}}]
  - component: api
    name: go
    behavior:
      - {call: engine.compute, input: {op: add, n: 1}, as: r}
      - {return: "= vars.r.value"}
flows:
  - {id: go, entry: {caller: client, interface: api.go}}
scenarios:
  - {id: go, flow: go, expect: ["result.ok"]}
`

const subChild = `schema_version: 1
id: engine-sub
level: service
refines: {ontology: app, component: engine}
imports: [{ontology: sub.yaml, as: s}]
fixtures:
  - {id: world, attributes: {world: true}, extends: [s/one-worker]}
components:
  - {id: adapter}
interfaces:
  - component: adapter
    name: compute
    implements: engine.compute
    behavior:
      - {call: s/disp.run, input: "= input", as: r}
      - {return: "= vars.r.value"}
`

func writeSub(t *testing.T) (*model.Document, *model.Document) {
	t.Helper()
	dir := t.TempDir()
	for name, body := range map[string]string{"sub.yaml": subDoc, "child.yaml": subChild} {
		if err := os.WriteFile(dir+"/"+name, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	child, err := model.ParseDocument([]byte(subChild))
	if err != nil {
		t.Fatal(err)
	}
	if err := model.LoadImportFiles(child, dir, os.ReadFile); err != nil {
		t.Fatal(err)
	}
	parent, err := model.ParseDocument([]byte(subParent))
	if err != nil {
		t.Fatal(err)
	}
	return parent, child
}

func TestLoadImportFiles(t *testing.T) {
	_, child := writeSub(t)
	sub := child.ImportDocs["sub.yaml"]
	if sub == nil || sub.ID != "sub" {
		t.Fatalf("import not loaded: %v", child.ImportDocs)
	}
	// A missing file stays unloaded and fails at merge, not at load.
	d := &model.Document{Imports: []model.ImportRef{{Ontology: "nope.yaml"}}}
	if err := model.LoadImportFiles(d, t.TempDir(), os.ReadFile); err != nil || d.ImportDocs != nil {
		t.Fatalf("missing import: %v %v", err, d.ImportDocs)
	}
}

func TestMergeImportsCarriesFixtures(t *testing.T) {
	_, child := writeSub(t)
	m, err := model.MergeImports(child, child.ImportDocs)
	if err != nil {
		t.Fatal(err)
	}
	x := model.NewIndex(m)
	fx := x.Fixtures["s/one-worker"]
	if fx == nil {
		t.Fatalf("imported fixture missing: %v", m.Fixtures)
	}
	if got := fx.Topology["s/worker"]; len(got) != 1 || got[0] != "w0" {
		t.Errorf("topology not renamed: %v", fx.Topology)
	}
	if _, ok := fx.State["s/worker@w0"]; !ok {
		t.Errorf("state key not renamed: %v", fx.State)
	}
}

func TestComposeRenamesDynamicCallsAndCarriesWorld(t *testing.T) {
	parent, child := writeSub(t)
	doc, err := model.ComposeRefinements(parent, map[string]*model.Document{"engine": child}, map[string]string{"engine": "refined"})
	if err != nil {
		t.Fatal(err)
	}
	x := model.NewIndex(doc)
	run := x.Interfaces["engine/s/disp.run"]
	if run == nil {
		t.Fatal("engine/s/disp.run missing")
	}
	call := run.Behavior[0]
	if call.Targets[0] != "engine/s/worker.add" || !strings.Contains(call.Call, "'s/worker.add': 'engine/s/worker.add'") || strings.Count(call.Call, "input.op") != 1 {
		t.Errorf("dynamic call not renamed: %q %v", call.Call, call.Targets)
	}
	for _, id := range []string{"engine/world", "engine/s/one-worker"} {
		if x.Fixtures[id] == nil {
			t.Errorf("fixture %s not carried: %v", id, doc.Fixtures)
		}
	}
	if fx := x.Fixtures["engine/s/one-worker"]; fx != nil {
		if _, ok := fx.Topology["engine/s/worker"]; !ok {
			t.Errorf("world topology not renamed: %v", fx.Topology)
		}
	}
	if sc := doc.Scenarios[0]; len(sc.Fixtures) == 0 || sc.Fixtures[0] != "engine/world" {
		t.Errorf("world not applied to scenario: %v", sc.Fixtures)
	}
}

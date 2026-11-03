package main

import (
	"bytes"
	"io"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

// modeledDoc has a reachable interface with a behavior (svc.handle), one
// with a store (svc.lookup), one without either (svc.list, registered but
// never modeled), and a workflow named for its inventory entry.
const modeledDoc = `schema_version: 1
id: m
components:
  - {id: client}
  - {id: svc, sources: [svc]}
  - {id: wf}
interfaces:
  - {component: svc, name: handle, sources: ["svc/api.go:10"], behavior: [{call: svc.lookup, input: {}}, {return: {}}]}
  - {component: svc, name: lookup, sources: ["svc/db.go:5"], store: {table: t, op: get, key: "= 'k'"}}
  - {component: svc, name: list, sources: ["svc/api.go:30"]}
  - {component: wf, name: batch-workflow, sources: ["wf/run.go:1"], behavior: [{return: {}}]}
flows:
  - {id: handle, entry: {caller: client, interface: svc.handle}}
  - {id: list, entry: {caller: client, interface: svc.list}}
  - {id: batch, entry: {caller: client, interface: wf.batch-workflow}}
scenarios:
  - {id: handle, steps: [{flow: handle}]}
  - {id: batch, steps: [{flow: batch}]}
`

var modeledInv = []invEntry{
	{Kind: "http-route", Name: "GET /handle", File: "svc/api.go", Line: 10},             // cited by handle, which runs
	{Kind: "http-route", Name: "GET /list", File: "svc/api.go", Line: 30},               // cited by list: no behavior, no store
	{Kind: "service", Name: "Lookup", File: "svc/db.go", Line: 6},                       // cited by the store interface, called by handle
	{Kind: "temporal-workflow", Name: "W.BatchWorkflow", File: "wf/other.go", Line: 40}, // named for wf.batch-workflow
	{Kind: "http-route", Name: "GET /skip", File: "svc/api.go", Line: 50, Skip: "test only"},
	{Kind: "http-route", Name: "GET /none", File: "other/x.go", Line: 1}, // no fragment owns it
}

func modeledFixture(t *testing.T) (*model.Document, *runReport, []citation) {
	t.Helper()
	doc, err := model.ParseDocument([]byte(modeledDoc))
	if err != nil {
		t.Fatal(err)
	}
	rr := runAll(io.Discard, doc, nil, runOpts{Quiet: true})
	if rr.Failed > 0 {
		t.Fatalf("scenarios failed: %+v", rr)
	}
	return doc, rr, collectCitations(doc)
}

func TestRunCollectsCalledInterfaces(t *testing.T) {
	_, rr, _ := modeledFixture(t)
	for _, id := range []string{"svc.handle", "svc.lookup", "wf.batch-workflow"} {
		if !rr.Called[id] {
			t.Errorf("%s not called: %v", id, rr.Called)
		}
	}
	if rr.Called["svc.list"] {
		t.Error("svc.list called though no scenario runs it")
	}
}

func TestModeledBy(t *testing.T) {
	doc, rr, cites := modeledFixture(t)
	got := modeledBy(doc, cites, modeledInv, rr.Called)
	want := []string{"interface:svc.handle", "", "interface:svc.lookup", "interface:wf.batch-workflow", "", ""}
	for n := range want {
		if got[n] != want[n] {
			t.Errorf("entry %d (%s): modeled by %q, want %q", n, modeledInv[n].Name, got[n], want[n])
		}
	}
	// Without a trace calling them, nothing is modeled.
	for n, by := range modeledBy(doc, cites, modeledInv, map[string]bool{}) {
		if by != "" {
			t.Errorf("entry %d modeled by %s with no calls", n, by)
		}
	}
	// list is registered (its flow reaches it) but not modeled.
	if res := coverage(doc, cites, modeledInv); !res[1].covered() {
		t.Errorf("GET /list status %s, want registered", res[1].Status)
	}
}

func TestEntryOwners(t *testing.T) {
	cites := []citation{
		{Entity: "component:svc", Src: model.ParseSource("svc")},
		{Entity: "interface:svc.handle", Src: model.ParseSource("svc/api.go:10")},
		{Entity: "interface:wf.run", Src: model.ParseSource("wf/run.go:1")},
		{Entity: "interface:orphan", Src: model.ParseSource("other/x.go:1")}, // no origin
	}
	origins := map[string]string{"component/svc": "skeleton.yaml", "interface/svc.handle": "api.yaml", "interface/wf.run": "wf.yaml"}
	inv := []invEntry{
		{File: "svc/api.go", Line: 99},     // file cited by api.yaml, under svc/ cited by the skeleton
		{File: "svc/sub/deep.go", Line: 1}, // under svc/
		{File: "wf/run.go", Line: 500},     // same file, other lines
		{File: "wf/other.go", Line: 1},     // wf/ isn't cited as a directory
		{File: "other/x.go", Line: 1},      // cited only by an entity with no origin
		{File: "svcextra/a.go", Line: 1},   // a prefix of the name, not a parent directory
	}
	want := []string{"api.yaml,skeleton.yaml", "skeleton.yaml", "wf.yaml", "", "", ""}
	for n, o := range entryOwners(cites, origins, inv) {
		if got := strings.Join(o, ","); got != want[n] {
			t.Errorf("%s: owners %q, want %q", inv[n].File, got, want[n])
		}
	}
}

func TestMinModeled(t *testing.T) {
	doc, rr, cites := modeledFixture(t)
	origins := map[string]string{}
	for _, i := range doc.Interfaces {
		origins["interface/"+i.ID] = "svc.yaml"
	}
	origins["interface/wf.batch-workflow"] = "wf.yaml"
	tb := tabulate(coverage(doc, cites, modeledInv))
	mr := tb.setModeled(modeledBy(doc, cites, modeledInv, rr.Called), nil, entryOwners(cites, origins, modeledInv))
	// svc.yaml owns svc/api.go (3 entries, 1 skipped) and svc/db.go: 2 of 3 modeled.
	// wf.yaml owns wf/run.go only; the named workflow lives in wf/other.go.
	if len(mr.Fragments) != 1 || mr.Fragments[0].Fragment != "svc.yaml" {
		t.Fatalf("fragments %+v", mr.Fragments)
	}
	f := mr.Fragments[0]
	if f.Owned != 4 || f.Skipped != 1 || f.Modeled != 2 || f.Registered != 3 {
		t.Errorf("svc.yaml %+v", f)
	}
	if mr.Modeled != 3 || mr.Counted != 5 || mr.Unowned != 2 {
		t.Errorf("totals %+v", mr)
	}
	var b bytes.Buffer
	if mr.print(&b, 0.5, -1) {
		t.Errorf("2/3 failed --min-modeled 0.5:\n%s", b.String())
	}
	if !strings.Contains(b.String(), "  modeled in svc.yaml: 2/3 67%, substantive 2 67% (registered 3, owned 4, skipped 1)") ||
		!strings.Contains(b.String(), "modeled: 3 of 5 entry points modeled (60%)") {
		t.Errorf("report:\n%s", b.String())
	}
	b.Reset()
	if !mr.print(&b, 0.7, -1) || !strings.Contains(b.String(), "✗ modeled in svc.yaml") {
		t.Errorf("2/3 passed --min-modeled 0.7:\n%s", b.String())
	}
	b.Reset()
	tb.print(&b, false)
	if !strings.Contains(b.String(), "uncovered 1)  modeled 1  substantive 1\n") {
		t.Errorf("per-kind line lacks the modeled column:\n%s", b.String())
	}
	// Without setModeled the per-kind lines are unchanged.
	b.Reset()
	tabulate(coverage(doc, cites, modeledInv)).print(&b, false)
	if strings.Contains(b.String(), "modeled") {
		t.Errorf("modeled column without setModeled:\n%s", b.String())
	}
}

// TestMinModeledExempt: a fragment that defines no interface with a behavior
// or a store (a skeleton) is reported as exempt and never fails the gate.
func TestMinModeledExempt(t *testing.T) {
	doc, rr, cites := modeledFixture(t)
	origins := map[string]string{"component/svc": "skeleton.yaml", "interface/svc.list": "skeleton.yaml"}
	for _, id := range []string{"svc.handle", "svc.lookup", "wf.batch-workflow"} {
		origins["interface/"+id] = "svc.yaml"
	}
	tb := tabulate(coverage(doc, cites, modeledInv))
	mr := tb.setModeled(modeledBy(doc, cites, modeledInv, rr.Called), nil, entryOwners(cites, origins, modeledInv))
	mr.exemptFragments(doc, origins)
	ex := map[string]bool{}
	for _, f := range mr.Fragments {
		ex[f.Fragment] = f.Exempt
	}
	if !ex["skeleton.yaml"] || ex["svc.yaml"] {
		t.Fatalf("exempt %v", ex)
	}
	var b bytes.Buffer
	// skeleton.yaml owns svc/ (2 of 3 modeled) but is exempt; svc.yaml is 2/3.
	if !mr.print(&b, 0.7, -1) || strings.Contains(b.String(), "✗ modeled in skeleton.yaml") ||
		!strings.Contains(b.String(), "skipped 1, exempt)") || mr.below(0.7) != 1 {
		t.Errorf("report:\n%s", b.String())
	}
	b.Reset()
	if mr.print(&b, 0.5, -1) {
		t.Errorf("failed at 0.5:\n%s", b.String())
	}
}

// trivialDoc: svc.handle calls (substantive), svc.ping only returns, svc.mark
// sets twice, svc.mark3 sets three times, svc.guard returns under a when,
// svc.lookup is a store, and svc.dead is trivial but no flow reaches it.
const trivialDoc = `schema_version: 1
id: t
components:
  - {id: client}
  - {id: svc}
interfaces:
  - {component: svc, name: handle, sources: ["svc/a.go:10"], behavior: [{call: svc.lookup, input: {}}, {return: {}}]}
  - {component: svc, name: lookup, sources: ["svc/a.go:20"], store: {table: t, op: get, key: "= 'k'", default: {}}}
  - {component: svc, name: ping, sources: ["svc/a.go:30"], behavior: [{return: {}}]}
  - {component: svc, name: mark, sources: ["svc/b.go:10"], behavior: [{set: {state.a: 1}}, {set: {state.b: 2}}, {return: {}}]}
  - {component: svc, name: mark3, sources: ["svc/b.go:20"], behavior: [{set: {state.a: 1}}, {set: {state.b: 2}}, {set: {state.c: 3}}, {return: {}}]}
  - {component: svc, name: guard, sources: ["svc/b.go:30"], behavior: [{when: "1 == 2", return: {x: 1}}, {return: {}}]}
  - {component: svc, name: dead, sources: ["svc/b.go:40"], behavior: [{return: {}}]}
flows:
  - {id: handle, entry: {caller: client, interface: svc.handle}}
  - {id: ping, entry: {caller: client, interface: svc.ping}}
  - {id: mark, entry: {caller: client, interface: svc.mark}}
  - {id: mark3, entry: {caller: client, interface: svc.mark3}}
  - {id: guard, entry: {caller: client, interface: svc.guard}}
scenarios:
  - {id: handle, flow: handle}
  - {id: ping, flow: ping}
  - {id: mark, flow: mark}
  - {id: mark3, flow: mark3}
  - {id: guard, flow: guard}
`

var trivialInv = []invEntry{
	{Kind: "rpc", Name: "Handle", File: "svc/a.go", Line: 10, Area: "a"},
	{Kind: "rpc", Name: "Lookup", File: "svc/a.go", Line: 20, Area: "a"},
	{Kind: "rpc", Name: "Ping", File: "svc/a.go", Line: 30, Area: "a"},
	{Kind: "rpc", Name: "Mark", File: "svc/b.go", Line: 10, Area: "b"},
	{Kind: "rpc", Name: "Mark3", File: "svc/b.go", Line: 20, Area: "b"},
	{Kind: "rpc", Name: "Guard", File: "svc/b.go", Line: 30, Area: "b"},
	{Kind: "rpc", Name: "Dead", File: "svc/b.go", Line: 40, Area: "b"},
	{Kind: "decl", Name: "Decl", File: "svc/b.go", Line: 50, Area: "b", Level: "registered"},
}

func trivialFixture(t *testing.T) (*model.Document, *runReport, []citation, map[string]string) {
	t.Helper()
	doc, err := model.ParseDocument([]byte(trivialDoc))
	if err != nil {
		t.Fatal(err)
	}
	rr := runAll(io.Discard, doc, nil, runOpts{Quiet: true})
	if rr.Failed > 0 {
		t.Fatalf("scenarios failed: %+v", rr)
	}
	origins := map[string]string{}
	for _, id := range []string{"svc.handle", "svc.lookup", "svc.ping"} {
		origins["interface/"+id] = "a.yaml"
	}
	for _, id := range []string{"svc.mark", "svc.mark3", "svc.guard", "svc.dead"} {
		origins["interface/"+id] = "b.yaml"
	}
	return doc, rr, collectCitations(doc), origins
}

func TestTrivialBehavior(t *testing.T) {
	doc, _, _, _ := trivialFixture(t)
	got := trivialIDs(doc)
	for id, want := range map[string]bool{"svc.handle": false, "svc.lookup": false, "svc.ping": true,
		"svc.mark": true, "svc.mark3": false, "svc.guard": false, "svc.dead": true} {
		if got[id] != want {
			t.Errorf("%s trivial %v, want %v", id, got[id], want)
		}
	}
	// No behavior at all isn't trivial: it isn't modeled.
	if tr, _ := trivialBehavior(&model.Interface{ID: "x"}); tr {
		t.Error("an interface without a behavior counted as trivial")
	}
	// Nested steps count: a call inside a foreach isn't trivial.
	nested := &model.Interface{ID: "n", Behavior: []model.Step{{Foreach: []any{1}, Steps: []model.Step{{Call: "svc.ping"}}}}}
	if tr, _ := trivialBehavior(nested); tr {
		t.Error("a nested call counted as trivial")
	}
}

func TestLintTrivial(t *testing.T) {
	doc, _, cites, origins := trivialFixture(t)
	r := lintTrivial(doc, cites, trivialInv, origins)
	// a.yaml: handle, lookup, ping cite entries; ping is trivial (1/3).
	// b.yaml: mark, mark3, guard (dead isn't reachable); mark is trivial (1/3).
	if r.Citing != 6 || r.Trivial != 2 || len(r.Hits) != 2 || r.Hits[0].ID != "svc.ping" || r.Hits[1].ID != "svc.mark" {
		t.Fatalf("report %+v", r)
	}
	var b bytes.Buffer
	if r.print(&b, -1, false) {
		t.Errorf("failed with the gate off:\n%s", b.String())
	}
	for _, want := range []string{
		"! trivial interface svc.ping (a.yaml, cites 1 entries): no call",
		"  trivial in b.yaml: 1 of 3 entry-citing interfaces 33.3%",
		"trivial lint: 2 of 6 entry-citing interfaces trivial (33.3%)\n",
	} {
		if !strings.Contains(b.String(), want) {
			t.Errorf("output lacks %q:\n%s", want, b.String())
		}
	}
	b.Reset()
	if !r.print(&b, 0.3, true) || !strings.Contains(b.String(), "✗ trivial in a.yaml") ||
		!strings.Contains(b.String(), "--max-trivial 0.30: 2 fragments above") || strings.Contains(b.String(), "! trivial interface") {
		t.Errorf("0.3 gate:\n%s", b.String())
	}
	b.Reset()
	if r.print(&b, 0.34, false) {
		t.Errorf("1/3 failed --max-trivial 0.34:\n%s", b.String())
	}
	// Skipped entries don't make an interface entry-citing.
	inv := append([]invEntry(nil), trivialInv...)
	inv[2].Skip = "test only"
	if r := lintTrivial(doc, cites, inv, origins); r.Citing != 5 || r.Trivial != 1 {
		t.Errorf("with ping's entry skipped: %+v", r)
	}
}

func TestMinSubstantive(t *testing.T) {
	doc, rr, cites, origins := trivialFixture(t)
	tb := tabulate(coverage(doc, cites, trivialInv))
	sub := modeledBy(doc, cites, trivialInv, withoutTrivial(rr.Called, trivialIDs(doc)))
	mr := tb.setModeled(modeledBy(doc, cites, trivialInv, rr.Called), sub, entryOwners(cites, origins, trivialInv))
	// Eight counted entries: dead is unreached, decl is uncovered (both
	// unmodeled); six are modeled, of which ping and mark are trivial.
	if mr.Modeled != 6 || mr.Substantive != 4 || mr.SubByKind["rpc"] != 4 {
		t.Fatalf("totals %+v", mr)
	}
	byFrag := map[string]fragModeled{}
	for _, f := range mr.Fragments {
		byFrag[f.Fragment] = f
	}
	if a := byFrag["a.yaml"]; a.Modeled != 3 || a.Substantive != 2 {
		t.Errorf("a.yaml %+v", a)
	}
	if b := byFrag["b.yaml"]; b.Owned != 5 || b.Modeled != 3 || b.Substantive != 2 {
		t.Errorf("b.yaml %+v", b)
	}
	var b bytes.Buffer
	// b.yaml: modeled 3/5, substantive 2/5.
	if mr.print(&b, 0.5, -1) {
		t.Errorf("failed --min-modeled 0.5:\n%s", b.String())
	}
	b.Reset()
	if !mr.print(&b, 0.5, 0.5) || !strings.Contains(b.String(), "✗ modeled in b.yaml: 3/5 60%, substantive 2 40%") ||
		strings.Contains(b.String(), "✗ modeled in a.yaml") ||
		!strings.Contains(b.String(), "--min-substantive 0.50: 1 fragments below") ||
		!strings.Contains(b.String(), "6 of 8 entry points modeled (75%), 4 substantive (50%)") {
		t.Errorf("--min-substantive 0.5:\n%s", b.String())
	}
	// A declaration-only entry counts as substantive once registered.
	inv := append([]invEntry(nil), trivialInv...)
	inv[7].File, inv[7].Line = "svc/a.go", 30 // shares ping's lines, so it is registered
	tb = tabulate(coverage(doc, cites, inv))
	mr = tb.setModeled(modeledBy(doc, cites, inv, rr.Called), modeledBy(doc, cites, inv, withoutTrivial(rr.Called, trivialIDs(doc))), entryOwners(cites, origins, inv))
	if mr.SubByKind["decl"] != 1 {
		t.Errorf("declaration-only entry not substantive: %+v", mr)
	}
}

// TestSharedStoresExempt: a skeleton whose only stores are shared datastore
// operations is exempt from --min-modeled.
func TestSharedStoresExempt(t *testing.T) {
	doc := &model.Document{Interfaces: []model.Interface{{Component: "db", Name: "get", Store: &model.StoreSpec{}, Attributes: map[string]any{"owner": "shared", "boundary": true}}}}
	r := &modeledReport{Fragments: []fragModeled{{Fragment: "skeleton.yaml"}}}
	origins := map[string]string{}
	for _, i := range doc.Interfaces {
		i.Normalize()
		origins[model.KindInterface+"/"+i.ID] = "skeleton.yaml"
	}
	r.exemptFragments(doc, origins)
	if !r.Fragments[0].Exempt {
		t.Fatal("skeleton with only shared stores should be exempt")
	}
}

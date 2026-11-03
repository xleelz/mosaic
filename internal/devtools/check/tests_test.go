package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Reuses modeledDoc: svc.handle (svc/api.go:10) and svc.lookup (svc/db.go:5)
// and wf.batch-workflow (wf/run.go:1) are called; svc.list (svc/api.go:30) is
// not, and the flow "list" has no scenario.

func TestTargetPath(t *testing.T) {
	for in, want := range map[string]string{
		"svc/api.go":          "svc/api.go",
		"./svc/api.go#Handle": "svc/api.go",
		"svc/api.go:12":       "svc/api.go",
		"Handle":              "",
		"api.go":              "api.go",
	} {
		if got := targetPath(in); got != want {
			t.Errorf("targetPath(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestTestReach(t *testing.T) {
	doc, rr, cites := modeledFixture(t)
	tests := []testTarget{
		{Test: "t/api_test.go", Targets: []string{"svc/api.go"}, Area: "svc"},                // reached via svc.handle
		{Test: "t/db_test.go", Targets: []string{"x/y.go", "svc/db.go#Lookup"}, Area: "svc"}, // second target reached
		{Test: "t/other_test.go", Targets: []string{"other/z.go"}, Area: "svc"},              // nothing cites it
		{Test: "t/none_test.go", Area: "svc"},                                                // no target: not counted
		{Test: "t/wf_test.go", Targets: []string{"wf/run.go:1"}, Area: "wf"},
		{Test: "t/sym_test.go", Targets: []string{"BatchWorkflow"}, Area: "wf"}, // a bare symbol
		{Test: "t/orphan_test.go", Targets: []string{"svc/nope.go"}},
	}
	r := testReach(doc, cites, tests, rr.Called)
	got := map[string]areaReach{}
	for _, a := range r.Areas {
		got[a.Area] = a
	}
	if a := got["svc"]; a.Tests != 4 || a.Resolved != 3 || a.Reached != 2 {
		t.Errorf("svc: %+v, want 4 tests, 3 resolved, 2 reached", a)
	}
	if a := got["wf"]; a.Resolved != 2 || a.Reached != 2 {
		t.Errorf("wf: %+v, want 2 of 2 reached", a)
	}
	if a := got["(none)"]; a.Resolved != 1 || a.Reached != 0 {
		t.Errorf("(none): %+v", a)
	}
	if r.Total.Tests != 7 || r.Total.Resolved != 6 || r.Total.Reached != 4 {
		t.Errorf("total: %+v", r.Total)
	}
	if u := r.Unreached["svc"]; len(u) != 1 || u[0] != "t/other_test.go" {
		t.Errorf("unreached svc: %v", u)
	}

	// The gate is per area; the (none) area (0%) never fails it.
	var b bytes.Buffer
	if !r.print(&b, 0.7, true, nil) {
		t.Errorf("svc at 2/3 passed --min-test-reach 0.7:\n%s", b.String())
	}
	out := b.String()
	for _, want := range []string{
		"✗ test reach in svc: 2/3 67% (4 test files, 1 with no target)",
		"  test reach in wf: 2/2 100%",
		"  test reach in (none): 0/1 0%",
		"    unreached: t/other_test.go",
		"test reach: 4 of 6 test files reached (67%), 1 with no target; --min-test-reach 0.70: 1 areas below",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in:\n%s", want, out)
		}
	}
	b.Reset()
	if r.print(&b, 0.6, false, nil) {
		t.Errorf("failed --min-test-reach 0.6:\n%s", b.String())
	}
	if strings.Contains(b.String(), "unreached:") {
		t.Error("lists unreached tests without verbose")
	}

	// An area-local run gates only its own area.
	b.Reset()
	if r.print(&b, 0.7, false, map[string]bool{"wf": true, "skeleton": true}) {
		t.Errorf("gated svc, which isn't in the merge:\n%s", b.String())
	}
	if !strings.Contains(b.String(), "  test reach in svc: 2/3 67% (4 test files, 1 with no target, not in this merge)") ||
		!strings.Contains(b.String(), "0 areas below") {
		t.Errorf("area-local:\n%s", b.String())
	}

	// Without calls nothing is reached; a directory citation reaches the files under it.
	if r := testReach(doc, cites, tests, map[string]bool{}); r.Total.Reached != 0 {
		t.Errorf("reached %d tests with no calls", r.Total.Reached)
	}
	dirCites := append(cites, citation{Entity: "interface:svc.handle", Src: cites[0].Src})
	dirCites[len(dirCites)-1].Src.Path = "other"
	if r := testReach(doc, dirCites, tests, rr.Called); r.Total.Reached != 5 {
		t.Errorf("directory citation: reached %d, want 5", r.Total.Reached)
	}
}

func TestLoadTests(t *testing.T) {
	dir := t.TempDir()
	f := filepath.Join(dir, "tt.json")
	os.WriteFile(f, []byte(`[{"test": "a_test.py", "targets": ["a.py"], "area": "x"}]`), 0o644)
	got, err := loadTests(f)
	if err != nil || len(got) != 1 || got[0].Targets[0] != "a.py" || got[0].Area != "x" {
		t.Errorf("loadTests: %+v %v", got, err)
	}
	os.WriteFile(f, []byte(`{"not": "a list"}`), 0o644)
	if _, err := loadTests(f); err == nil {
		t.Error("loaded a non-list")
	}
}

const featureProfile = `id: m
features:
  - {id: handle, summary: "handle a request", sources: [docs/handle.md], owner: svc}
  - {id: listing, summary: "list things", owner: svc}
  - {id: batch, summary: "batch runs", owner: wf}
  - {id: export, owner: wf}
  - {id: audit, owner: svc}
  - {id: purge, owner: svc}
  - {id: replay, owner: svc}
  - {id: stray, owner: wf}
`

func TestFeatureCoverage(t *testing.T) {
	doc, rr, _ := modeledFixture(t)
	for n := range doc.Flows {
		switch doc.Flows[n].ID {
		case "handle":
			doc.Flows[n].Tags = []string{"writes", "feature:handle"}
		case "list": // no scenario runs it
			doc.Flows[n].Tags = []string{"feature:listing"}
		case "batch":
			doc.Flows[n].Tags = []string{"feature:batch", "feature:nosuch"}
		}
	}
	dir := t.TempDir()
	prof := filepath.Join(dir, "profile.yaml")
	os.WriteFile(prof, []byte(featureProfile), 0o644)
	os.MkdirAll(filepath.Join(dir, "skips"), 0o755)
	os.WriteFile(filepath.Join(dir, "skips", "wf.features.json"), []byte(`[
  {"id": "export", "reason": "the export is a client-side download with no server behavior"},
  {"id": "handle", "reason": "not ours"},
  {"id": "stray", "reason": "covered by the batch flow"}
]`), 0o644)
	os.WriteFile(filepath.Join(dir, "skips", "svc.features.json"), []byte(`[
  {"id": "audit", "reason": "Out of scope for now"},
  {"id": "purge", "reason": "covered by svc.handle's delete branch", "covered_by": "interface:svc.handle"},
  {"id": "replay", "reason": "replays reuse batch", "covered_by": "svc.nosuch"},
  {"id": "ghost", "reason": "x"}
]`), 0o644)
	os.WriteFile(filepath.Join(dir, "skips", "svc.json"), []byte(`[{"kind": "inventory", "not": "a feature skip"}]`), 0o644)

	feats, skips, err := loadFeatures(prof)
	if err != nil {
		t.Fatal(err)
	}
	if len(feats) != 8 || feats[0].Sources[0] != "docs/handle.md" || len(skips) != 2 {
		t.Fatalf("loaded %+v, skips %v", feats, skips)
	}
	r := featureCoverage(doc, feats, skips, rr.Flows, nil)
	want := map[string]string{
		"handle":  featCovered,
		"listing": featMissing, // tagged flow, but no scenario runs it
		"batch":   featCovered,
		"export":  featSkipped,
		"audit":   featMissing, // rejected reason
		"purge":   featSkipped, // covered_by resolves
		"replay":  featMissing, // covered_by names no entity
		"stray":   featMissing, // "covered by" without covered_by
	}
	for _, x := range r.Results {
		if x.Status != want[x.ID] {
			t.Errorf("feature %s: %s (%s), want %s", x.ID, x.Status, x.Detail, want[x.ID])
		}
	}
	if c, s, m, a := r.counts(); c != 2 || s != 2 || m != 4 || a != 0 {
		t.Errorf("counts %d %d %d %d", c, s, m, a)
	}
	var b bytes.Buffer
	if !r.print(&b, false) {
		t.Error("print reported no missing features")
	}
	out := b.String()
	for _, w := range []string{
		"  features of svc: 1 covered, 1 skipped, 3 missing",
		"  features of wf: 1 covered, 1 skipped, 1 missing",
		"✗ feature listing (svc) missing: no run scenario runs flow list",
		`✗ feature audit (svc) missing: invalid skip: rejected reason "out of scope"`,
		"✗ feature replay (svc) missing: invalid skip: covered_by svc.nosuch names no entity",
		`✗ feature stray (wf) missing: invalid skip: says "covered by" without covered_by`,
		"! unknown feature tag on flow batch: feature:nosuch",
		"! feature skip ignored: skips/svc.features.json: ghost is not a profile feature",
		"! feature skip ignored: skips/wf.features.json: handle belongs to svc",
		"features: 2 of 8 covered, 2 skipped, 4 missing",
	} {
		if !strings.Contains(out, w) {
			t.Errorf("missing %q in:\n%s", w, out)
		}
	}
	if strings.Contains(out, "feature handle (svc) covered") {
		t.Error("lists covered features without verbose")
	}
	b.Reset()
	r.print(&b, true)
	if !strings.Contains(b.String(), "  feature handle (svc) covered: flow handle") ||
		!strings.Contains(b.String(), "  feature purge (svc) skipped: covered by svc.handle's delete branch (covered by interface:svc.handle)") {
		t.Errorf("verbose:\n%s", b.String())
	}

	// An area-local run of wf: svc's missing features are absent, not missing.
	r = featureCoverage(doc, feats, skips, rr.Flows, map[string]bool{"wf": true})
	if c, s, m, a := r.counts(); c != 2 || s != 2 || m != 1 || a != 3 {
		t.Errorf("area-local counts %d %d %d %d", c, s, m, a)
	}
	b.Reset()
	r.print(&b, false)
	for _, w := range []string{
		"  features of svc: 1 covered, 1 skipped, 3 not in this merge",
		"features: 2 of 8 covered, 2 skipped, 1 missing, 3 owned by areas not in this merge",
	} {
		if !strings.Contains(b.String(), w) {
			t.Errorf("missing %q in:\n%s", w, b.String())
		}
	}
	if strings.Contains(b.String(), "feature listing") {
		t.Errorf("reports another area's feature:\n%s", b.String())
	}

	// No features at all: nothing missing.
	if (&featReport{}).print(&bytes.Buffer{}, false) {
		t.Error("an empty feature list is missing something")
	}
}

func TestRunCollectsFlows(t *testing.T) {
	_, rr, _ := modeledFixture(t)
	if !rr.Flows["handle"] || !rr.Flows["batch"] || rr.Flows["list"] {
		t.Errorf("flows run: %v", rr.Flows)
	}
}

package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

const failureProfile = `id: m
features:
  - {id: handle, owner: svc}
failures:
  - {id: lookup-down, summary: "the lookup store is unavailable", sources: [svc/db.go], owner: svc, on: svc.lookup}
  - {id: list-down, owner: svc, on: svc.list}
  - {id: batch-killed, owner: wf, on: wf node death}
  - {id: client-gone, owner: wf, on: client disconnect}
  - {id: audit-down, owner: svc, on: audit}
  - {id: lease-lost, owner: svc, on: lease}
  - {id: stray, owner: wf}
`

func TestFailureCoverage(t *testing.T) {
	doc, rr, _ := modeledFixture(t)
	for n := range doc.Flows {
		switch doc.Flows[n].ID {
		case "handle":
			doc.Flows[n].Tags = []string{"writes", "failure:lookup-down", "feature:handle"}
		case "list": // no scenario runs it
			doc.Flows[n].Tags = []string{"failure:list-down"}
		case "batch": // run, but nothing fails
			doc.Flows[n].Tags = []string{"failure:batch-killed", "failure:nosuch"}
		}
	}
	for n := range doc.Scenarios {
		if doc.Scenarios[n].ID == "handle" {
			doc.Scenarios[n].Faults = []model.Fault{{Target: "svc.lookup", Type: "unavailable"}}
		}
	}
	dir := t.TempDir()
	prof := filepath.Join(dir, "profile.yaml")
	os.WriteFile(prof, []byte(failureProfile), 0o644)
	os.MkdirAll(filepath.Join(dir, "skips"), 0o755)
	os.WriteFile(filepath.Join(dir, "skips", "wf.failures.json"), []byte(`[
  {"id": "client-gone", "reason": "the batch workflow has no client connection to lose"},
  {"id": "lookup-down", "reason": "not ours"},
  {"id": "stray", "reason": "covered by the batch flow"}
]`), 0o644)
	os.WriteFile(filepath.Join(dir, "skips", "svc.failures.json"), []byte(`[
  {"id": "audit-down", "reason": "TODO"},
  {"id": "lease-lost", "reason": "leases are handled by svc.handle's retry", "covered_by": "interface:svc.handle"},
  {"id": "ghost", "reason": "x"}
]`), 0o644)
	// Feature skips are not failure skips.
	os.WriteFile(filepath.Join(dir, "skips", "svc.features.json"), []byte(`[{"id": "handle", "reason": "x"}]`), 0o644)

	fails, skips, err := loadFailures(prof)
	if err != nil {
		t.Fatal(err)
	}
	if len(fails) != 7 || fails[0].On != "svc.lookup" || fails[0].Sources[0] != "svc/db.go" || len(skips) != 2 {
		t.Fatalf("loaded %+v, skips %v", fails, skips)
	}
	inj := failureRuns(doc, rr.Flows, nil)
	if !inj["handle"] || inj["batch"] || inj["list"] {
		t.Fatalf("injected %v", inj)
	}
	r := failureCoverage(doc, fails, skips, rr.Flows, inj, nil)
	want := map[string]string{
		"lookup-down":  featCovered,
		"list-down":    featMissing, // tagged flow, but no scenario runs it
		"batch-killed": featMissing, // run, but nothing is injected
		"client-gone":  featSkipped,
		"audit-down":   featMissing, // rejected reason
		"lease-lost":   featSkipped,
		"stray":        featMissing, // "covered by" without covered_by
	}
	for _, x := range r.Results {
		if x.Status != want[x.ID] {
			t.Errorf("failure %s: %s (%s), want %s", x.ID, x.Status, x.Detail, want[x.ID])
		}
	}
	if c, s, m, a := r.counts(); c != 1 || s != 2 || m != 4 || a != 0 {
		t.Errorf("counts %d %d %d %d", c, s, m, a)
	}
	var b bytes.Buffer
	if !r.print(&b, false) {
		t.Error("print reported no missing failures")
	}
	out := b.String()
	for _, w := range []string{
		"  failures of svc: 1 covered, 1 skipped, 2 missing",
		"  failures of wf: 0 covered, 1 skipped, 2 missing",
		"✗ failure list-down (svc, on svc.list) missing: no run scenario runs flow list",
		"✗ failure batch-killed (wf, on wf node death) missing: no run scenario of flow batch injects a fault, kill, cancel, failing mock or state",
		`✗ failure audit-down (svc, on audit) missing: invalid skip: rejected reason "todo"`,
		`✗ failure stray (wf) missing: invalid skip: says "covered by" without covered_by`,
		"! failure stray names no failing component or edge (on)",
		"! unknown failure tag on flow batch: failure:nosuch",
		"! failure skip ignored: skips/svc.failures.json: ghost is not a profile failure",
		"! failure skip ignored: skips/wf.failures.json: lookup-down belongs to svc",
		"failures: 1 of 7 covered, 2 skipped, 4 missing",
	} {
		if !strings.Contains(out, w) {
			t.Errorf("missing %q in:\n%s", w, out)
		}
	}
	if strings.Contains(out, "lookup-down (svc, on svc.lookup) covered") {
		t.Error("lists covered failures without verbose")
	}
	b.Reset()
	r.print(&b, true)
	if !strings.Contains(b.String(), "  failure lookup-down (svc, on svc.lookup) covered: flow handle") {
		t.Errorf("verbose:\n%s", b.String())
	}

	// An area-local run of wf: svc's missing failures are absent.
	r = failureCoverage(doc, fails, skips, rr.Flows, inj, map[string]bool{"wf": true})
	if c, s, m, a := r.counts(); c != 1 || s != 2 || m != 2 || a != 2 {
		t.Errorf("area-local counts %d %d %d %d", c, s, m, a)
	}
	b.Reset()
	r.print(&b, false)
	if !strings.Contains(b.String(), "failures: 1 of 7 covered, 2 skipped, 2 missing, 2 owned by areas not in this merge") ||
		strings.Contains(b.String(), "failure list-down") {
		t.Errorf("area-local:\n%s", b.String())
	}

	// A --scenario filter that excludes the faulted scenario covers nothing.
	if inj := failureRuns(doc, rr.Flows, regexp.MustCompile("^batch$")); len(inj) != 0 {
		t.Errorf("filtered injected %v", inj)
	}
	if (&failReport{}).print(&bytes.Buffer{}, false) {
		t.Error("an empty failure list is missing something")
	}
}

func TestInjects(t *testing.T) {
	yes := []model.Scenario{
		{Faults: []model.Fault{{Target: "x", Type: model.FaultKill}}},
		{State: map[string]map[string]any{"t": {"k": 1}}},
		{Steps: []model.ScenarioStep{{Flow: "f"}, {Cancel: "a"}}},
		{Steps: []model.ScenarioStep{{Kill: &model.Kill{}}}},
		{Mocks: []model.Mock{{Interface: "x", Fail: json.RawMessage(`{"code": "e"}`)}}},
	}
	for i, sc := range yes {
		if !injects(&sc) {
			t.Errorf("scenario %d injects nothing", i)
		}
	}
	no := model.Scenario{Flow: "f", Mocks: []model.Mock{{Interface: "x", Return: json.RawMessage(`{}`)}}}
	if injects(&no) {
		t.Error("a returning mock injects a failure")
	}
}

const sidedProfile = `id: m
failures:
  - {id: lookup-down, owner: svc, on: svc.lookup}
  - id: retry
    on: client
    sides:
      - {owner: wf, role: client-retry, summary: "the client retries with the same key"}
      - {owner: svc, role: server-dedupe}
  - id: both-skipped
    on: client
    sides: [{owner: wf, role: a}, {owner: svc, role: b}]
  - id: half
    on: client
    sides: [{owner: wf, role: a}, {owner: svc, role: b}]
`

func TestTwoSidedFailures(t *testing.T) {
	doc, rr, _ := modeledFixture(t)
	for n := range doc.Flows {
		switch doc.Flows[n].ID {
		case "handle": // faulted below
			doc.Flows[n].Tags = []string{"failure:lookup-down", "failure:retry:client-retry", "failure:half:a", "failure:retry:nosuch", "failure:lookup-down:x"}
		case "batch": // run, nothing injected
			doc.Flows[n].Tags = []string{"failure:half:b", "failure:retry"}
		}
	}
	for n := range doc.Scenarios {
		if doc.Scenarios[n].ID == "handle" {
			doc.Scenarios[n].Faults = []model.Fault{{Target: "svc.lookup", Type: "unavailable"}}
		}
	}
	dir := t.TempDir()
	prof := filepath.Join(dir, "profile.yaml")
	os.WriteFile(prof, []byte(sidedProfile), 0o644)
	os.MkdirAll(filepath.Join(dir, "skips"), 0o755)
	os.WriteFile(filepath.Join(dir, "skips", "svc.failures.json"), []byte(`[
  {"id": "retry", "role": "server-dedupe", "reason": "the store's conditional put dedupes", "covered_by": "interface:svc.handle"},
  {"id": "both-skipped", "role": "b", "reason": "the server never sees the retry"},
  {"id": "half", "reason": "no role"},
  {"id": "lookup-down", "role": "x", "reason": "one owner"}
]`), 0o644)
	os.WriteFile(filepath.Join(dir, "skips", "wf.failures.json"), []byte(`[
  {"id": "both-skipped", "role": "a", "reason": "the batch client never retries"},
  {"id": "retry", "role": "server-dedupe", "reason": "not ours"}
]`), 0o644)
	fails, skips, err := loadFailures(prof)
	if err != nil {
		t.Fatal(err)
	}
	if len(fails[1].Sides) != 2 || fails[1].Sides[0].Role != "client-retry" || fails[1].Sides[0].Summary == "" || skips["svc"][0].Role != "server-dedupe" {
		t.Fatalf("loaded %+v skips %+v", fails, skips)
	}
	inj := failureRuns(doc, rr.Flows, nil)
	r := failureCoverage(doc, fails, skips, rr.Flows, inj, nil)
	want := map[string]string{"lookup-down": featCovered, "retry": featCovered, "both-skipped": featSkipped, "half": featMissing}
	for _, x := range r.Results {
		if x.Status != want[x.ID] {
			t.Errorf("failure %s: %s (%s), want %s", x.ID, x.Status, x.Detail, want[x.ID])
		}
	}
	if c, s, m, a := r.counts(); c != 2 || s != 1 || m != 1 || a != 0 {
		t.Errorf("counts %d %d %d %d", c, s, m, a)
	}
	// Per owner, a side counts under its owner.
	if c, s, m, _ := r.counts("svc"); c != 1 || s != 2 || m != 1 {
		t.Errorf("svc counts %d %d %d", c, s, m)
	}
	var b bytes.Buffer
	if !r.print(&b, true) {
		t.Error("print reported no missing failures")
	}
	out := b.String()
	for _, w := range []string{
		"  failures of svc: 1 covered, 2 skipped, 1 missing",
		"  failures of wf: 2 covered, 1 skipped, 0 missing",
		"  failure retry (side client-retry of wf, on client) covered: flow handle",
		"  failure retry (side server-dedupe of svc, on client) skipped: the store's conditional put dedupes (covered by interface:svc.handle)",
		"  failure retry (two-sided, on client) covered: client-retry covered, server-dedupe skipped",
		"✗ failure half (side b of svc, on client) missing: no run scenario of flow batch injects a fault, kill, cancel, failing mock or state",
		"! unknown failure tag on flow batch: failure:retry (a two-sided failure: tag failure:retry:<role>)",
		"! unknown failure tag on flow handle: failure:retry:nosuch (retry has no side nosuch)",
		"! unknown failure tag on flow handle: failure:lookup-down:x (lookup-down has one owner: tag failure:lookup-down)",
		"! failure skip ignored: skips/svc.failures.json: half is two-sided; a skip names its side's role",
		"! failure skip ignored: skips/svc.failures.json: lookup-down has one owner and no side x",
		"! failure skip ignored: skips/wf.failures.json: retry side server-dedupe belongs to svc",
		"failure sides: 2 of 6 covered, 3 skipped, 1 missing",
		"failures: 2 of 4 covered, 1 skipped, 1 missing",
	} {
		if !strings.Contains(out, w) {
			t.Errorf("missing %q in:\n%s", w, out)
		}
	}
	// An area-local run of wf: svc's missing side is absent, and so is the failure.
	r = failureCoverage(doc, fails, skips, rr.Flows, inj, map[string]bool{"wf": true})
	for _, x := range r.Results {
		if x.ID == "half" && (x.Status != featAbsent || x.Sides[0].Status != featCovered || x.Sides[1].Status != featAbsent) {
			t.Errorf("area-local half: %+v", x)
		}
	}
	if b.Reset(); r.print(&b, false) {
		t.Errorf("area-local run missing something:\n%s", b.String())
	}
}

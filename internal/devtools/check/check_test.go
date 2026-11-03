package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

const code = "../testdata/check/code"

func src(s string) *model.Source { v := model.ParseSource(s); return &v }

func fixtureDoc() *model.Document {
	return &model.Document{
		SchemaVersion: 1,
		Components: []model.Component{
			{ID: "svc", Summary: "the service", Sources: []model.Source{model.ParseSource("svc/handler.go:3"), model.ParseSource("svc/pkg")}},
			{ID: "lonely", Sources: []model.Source{model.ParseSource("svc/handler.go:20")}},
		},
		Interfaces: []model.Interface{{
			Component: "svc", Name: "handle", Kind: "http", Summary: "handles",
			Sources: []model.Source{model.ParseSource("svc/handler.go:99"), model.ParseSource("svc/gone.go:1")},
			Behavior: []model.Step{
				{Title: "check", Source: src("svc/handler.go:4"), Call: "svc.check",
					Retry: &model.RetrySpec{MaxAttempts: 3, Source: src("svc/handler.go:4-5")}},
				{If: "true", Then: []model.Step{
					{Title: "refuse 403", Source: src("svc/handler.go:5, svc/handler.go:9"), Fail: json.RawMessage(`{"code":"forbidden"}`)},
				}},
				{Choice: "mode", Options: map[string][]model.Step{"a": {{Title: "nested option", Source: src("svc/handler.go:8"), Return: json.RawMessage(`{}`)}}}},
			},
		}, {
			Component: "svc", Name: "check", Sources: []model.Source{model.ParseSource("svc/handler.go:9")},
		}},
		Flows: []model.Flow{{
			ID: "f", Entry: &model.FlowEntry{Caller: "user", Interface: "svc.handle"},
			Steps: []model.FlowStep{{Component: "svc", Title: "narrated", Source: src("svc/handler.go:1-6")}},
		}},
	}
}

func TestCollectCitationsWalksNestedSteps(t *testing.T) {
	cites := collectCitations(fixtureDoc())
	claims := map[string]string{}
	for _, c := range cites {
		claims[c.Src.String()] = c.Claim
	}
	for s, claim := range map[string]string{
		"svc/handler.go:4":   "check",
		"svc/handler.go:4-5": "check (retry)",
		"svc/handler.go:8":   "nested option",
		"svc/handler.go:1-6": "narrated",
		"svc/handler.go:3":   "the service",
	} {
		if claims[s] != claim {
			t.Errorf("claim for %s = %q, want %q", s, claims[s], claim)
		}
	}
	if len(cites) != 11 {
		t.Errorf("got %d citations, want 11", len(cites))
	}
}

func TestCheckCitations(t *testing.T) {
	r := checkCitations(fixtureDoc(), newCodeRoot(code))
	want := map[string]int{citeOK: 7, citeMissing: 1, citeBadLine: 1, citeDir: 1, citePacked: 1}
	for k, v := range want {
		if r.totals[k] != v {
			t.Errorf("%s = %d, want %d (totals %v)", k, r.totals[k], v, r.totals)
		}
	}
	if r.failures() != 3 { // directory citations are reported, not refused
		t.Errorf("failures = %d", r.failures())
	}
	var b bytes.Buffer
	r.print(&b)
	out := b.String()
	for _, s := range []string{
		"✗ cite component:svc: dir svc/pkg",
		"✗ cite interface:svc.handle: bad_line svc/handler.go:99, missing svc/gone.go:1, packed svc/handler.go:5, svc/handler.go:9 [svc/handler.go:5 (ok); svc/handler.go:9 (ok)]",
		"citations: 11 cited, 7 ok",
	} {
		if !strings.Contains(out, s) {
			t.Errorf("output lacks %q:\n%s", s, out)
		}
	}
}

func TestPackedAndPaths(t *testing.T) {
	for s, packed := range map[string]bool{
		"a/b.go:12, c/d.go:3":            true,
		"a/b.go:12; c/d.go":              true,
		"a/b.go:12 c/d.go:4":             true,
		"miscellaneous information/x.md": false,
		"a/b.go:12-20":                   false,
	} {
		if got := isPacked(model.ParseSource(s)); got != packed {
			t.Errorf("isPacked(%q) = %v", s, got)
		}
	}
	c := newCodeRoot(code)
	for s, want := range map[string]string{
		"./svc/handler.go:10": citeOK,
		"svc/handler.go:21":   citeBadLine,
		"svc/handler.go#L3":   citeOK,
		"../check/code/svc":   citeMissing,
		"svc/.env.production": citeSkipped,
		"svc/handler.go:9-22": citeBadLine,
	} {
		if got, _ := c.resolve(model.ParseSource(s)); got != want {
			t.Errorf("resolve(%q) = %s, want %s", s, got, want)
		}
	}
}

func TestCiteSample(t *testing.T) {
	r := checkCitations(fixtureDoc(), newCodeRoot(code))
	var a, b bytes.Buffer
	r.sample(&a, newCodeRoot(code), 3, 42)
	r.sample(&b, newCodeRoot(code), 3, 42)
	if a.String() != b.String() {
		t.Error("the same seed must print the same sample")
	}
	out := a.String()
	if !strings.Contains(out, "citation sample: 3 of 8") || strings.Count(out, "claim:") != 3 || !strings.Contains(out, " | ") {
		t.Errorf("sample output:\n%s", out)
	}
}

func TestCoverage(t *testing.T) {
	doc := fixtureDoc()
	inv := []invEntry{
		{Kind: "http-route", Name: "GET /x", File: "svc/handler.go", Line: 5},                    // cited lines 4-5 by svc.handle
		{Kind: "temporal-workflow", Name: "Workflow", File: "svc/handler.go", Line: 20},          // only "lonely", which no flow reaches
		{Kind: "temporal-activity", Name: "Svc.Check", File: "svc/other.go", Line: 40},           // named like the reachable svc.check, nearby
		{Kind: "cron", Name: "sweep", File: "svc/handler.go", Line: 30, EndLine: 40},             // file cited, other lines
		{Kind: "cli-command", Name: "tool", File: "cmd/tool/main.go", Line: 3},                   // nothing
		{Kind: "cli-command", Name: "seed", File: "cmd/seed/main.go", Line: 3, Skip: "dev only"}, // skipped
	}
	res := coverage(doc, collectCitations(doc), inv)
	want := []string{covLine, covUnreached, covName, covFile, covUncovered, covSkipped}
	for i, r := range res {
		if r.Status != want[i] {
			t.Errorf("%s %s: %s (by %s), want %s", r.Kind, r.Name, r.Status, r.By, want[i])
		}
	}
	tb := tabulate(res)
	if c, d := tb.coveredOf(tb.totals); c != 2 || d != 5 {
		t.Errorf("covered %d of %d", c, d)
	}
	var b bytes.Buffer
	tb.markdown(&b, 5)
	if !strings.Contains(b.String(), "| **all** | 6 | 1 | 1 | 1 | 1 | 1 | 1 | 40% |") || !strings.Contains(b.String(), "| `svc` | 2 |") {
		t.Errorf("markdown:\n%s", b.String())
	}
}

// TestCoverageDenseEntries keeps the line tolerance from spilling onto a
// neighboring entry, as in an enum with one verb per line.
func TestCoverageDenseEntries(t *testing.T) {
	doc := fixtureDoc()
	inv := []invEntry{
		{Kind: "http-route", Name: "GET /x", File: "svc/handler.go", Line: 10}, // line 9 cited, within tolerance
		{Kind: "http-route", Name: "GET /y", File: "svc/handler.go", Line: 11}, // also within 3 of line 9, but past its neighbor
	}
	res := coverage(doc, collectCitations(doc), inv)
	if res[0].Status != covLine || res[1].Status == covLine {
		t.Errorf("got %s and %s", res[0].Status, res[1].Status)
	}
}

func TestRouteSlug(t *testing.T) {
	if s := routeSlug("POST", "/v1/orgs/{orgId}/vms"); s != "post-v1-orgs-orgid-vms" {
		t.Error(s)
	}
	if s := routeSlug("ANY", "/v1/endpoints/{id}/{path...}"); s != "any-v1-endpoints-id-path" {
		t.Error(s)
	}
	if s := funcSlug("Workflows.BatchWorkflow"); s != "batch-workflow" {
		t.Error(s)
	}
}

func TestScalarDiffs(t *testing.T) {
	var a, b map[string]any
	_ = json.Unmarshal([]byte(`{"kind":"rpc","summary":"x","attributes":{"boundary":true,"owner":"billing"},
		"request":{"type":"object","properties":{"id":{"type":"string"}}},
		"response":"Thing","errors":[{"code":"not_found","status":404}],
		"store":{"table":"vms","op":"get","key":"= input.id"}}`), &a)
	_ = json.Unmarshal([]byte(`{"kind":"sql","summary":"y","attributes":{"boundary":true,"owner":"serving"},
		"request":{"type":"object","properties":{"id":{"type":"integer"}}},
		"response":"OtherThing","errors":[{"code":"not_found","status":400}],
		"store":{"table":"vms","op":"put","key":"= input.vm_id"}}`), &b)
	got := strings.Join(scalarDiffs(a, b), "\n")
	for _, s := range []string{
		"kind: rpc vs sql",
		"attributes.owner: billing vs serving",
		"request.id.type: string vs integer",
		"response: Thing vs OtherThing",
		"errors[not_found]: status 404 retryable false vs status 400 retryable false",
		"store.op: get vs put",
		`store.key: "= input.id" vs "= input.vm_id"`,
	} {
		if !strings.Contains(got, s) {
			t.Errorf("diffs lack %q:\n%s", s, got)
		}
	}
	if strings.Contains(got, "summary") || strings.Contains(got, "store.table") {
		t.Errorf("prose or equal fields reported:\n%s", got)
	}
	// A name against an inline schema is representation, not disagreement.
	if d := schemaDiffs("response", "Thing", map[string]any{"type": "object"}); len(d) != 0 {
		t.Error(d)
	}
}

func TestDuplicateSchemas(t *testing.T) {
	obj := func(desc string, extra ...string) map[string]any {
		p := map[string]any{"id": map[string]any{"type": "string", "description": desc}, "n": map[string]any{"type": "integer"}}
		for _, e := range extra {
			p[e] = map[string]any{"type": "boolean"}
		}
		return map[string]any{"type": "object", "properties": p}
	}
	groups := duplicateSchemas([]model.Schema{
		{ID: "BillingError", Schema: obj("a")},
		{ID: "ServingError", Schema: obj("b")},
		{ID: "ServingError2", Schema: obj("b")},
		{ID: "Different", Schema: obj("a", "extra")},
		{ID: "Tiny1", Schema: map[string]any{"type": "string"}},
		{ID: "Tiny2", Schema: map[string]any{"type": "string"}},
	})
	if len(groups) != 1 || strings.Join(groups[0].IDs, ",") != "BillingError,ServingError,ServingError2" || groups[0].Exact {
		t.Errorf("groups = %+v", groups)
	}
}

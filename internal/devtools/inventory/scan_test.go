package main

import (
	"sort"
	"strings"
	"testing"
)

func TestScanFixture(t *testing.T) {
	// The Java fixtures live under java/; restricting the languages keeps
	// the Go, TS and Python results exactly as before Java support.
	got, err := Scan("../testdata/inventory", Options{Langs: []string{"go", "ts", "python"}})
	if err != nil {
		t.Fatal(err)
	}
	have := map[string]Entry{}
	var keys []string
	for _, e := range got {
		k := e.Kind + " " + e.Name
		have[k] = e
		keys = append(keys, k+" @"+e.File)
	}
	sort.Strings(keys)
	want := []string{
		"http-route GET /healthz",
		"http-route ANY /v1/raw/{path...}",
		"http-route POST /v1/orgs/{orgId}/vms",
		"http-route PUT /v1/legacy",
		"http-route GET /v1/orgs/{orgId}/vms",
		"http-route DELETE /v1/orgs/{orgId}/vms/{vmId}",
		"temporal-workflow ProvisionWorkflow",
		"temporal-activity Activities.Provision",
		"temporal-activity Activities.Teardown",
		"cron sweep",
		"cli-command tool",
		"cli-command tool sync",
		"cli-command tool prune",
		"cli-command deploy",
		"next-route GET /api/vms/{id}",
		"next-route DELETE /api/vms/{id}",
		"next-route GET /health",
		"next-route POST /health",
		"trpc-procedure banners.list",
		"trpc-procedure banners.create",
		"python-cli tool",
		"python-cli tool collect",
		"python-cli tool render",
		"python-cli reltool",
		// The python-gpu fixture's FastAPI routes, which base python lists too.
		"http-route POST /v1/chat/completions",
		"http-route GET /health",
		"http-route GET /ping",
		"http-route POST /ping",
		"http-route POST /abort",
	}
	for _, w := range want {
		if _, ok := have[w]; !ok {
			t.Errorf("missing %q", w)
		}
	}
	if len(got) != len(want) {
		t.Errorf("got %d entries, want %d:\n%s", len(got), len(want), strings.Join(keys, "\n"))
	}
	// False positives the heuristics must avoid.
	for _, k := range keys {
		for _, bad := range []string{"runStep", "helper", "waitReady", "/test-only", "/mock-only", "hidden"} {
			if strings.Contains(k, bad) {
				t.Errorf("unexpected entry %q", k)
			}
		}
	}
	// The generated server's operations are listed once each, from the interface.
	if e := have["http-route GET /v1/orgs/{orgId}/vms"]; e.Via != "openapi-gen" || e.Line != 5 {
		t.Errorf("gen route = %+v", e)
	}
	// Function entries carry the function's extent.
	if e := have["temporal-activity Activities.Provision"]; e.EndLine != e.Line || e.File != "svc/worker/worker.go" {
		t.Errorf("activity = %+v", e)
	}
	if e := have["temporal-workflow ProvisionWorkflow"]; e.EndLine <= e.Line {
		t.Errorf("workflow extent = %+v", e)
	}
}

func TestScanIncludeTestSupport(t *testing.T) {
	got, err := Scan("../testdata/inventory", Options{IncludeTestSupport: true, Langs: []string{"go", "ts", "python"}})
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, e := range got {
		if e.Name == "ANY /mock-only" {
			found = true
		}
		if strings.Contains(e.Name, "test-only") {
			t.Errorf("_test.go files are never scanned: %+v", e)
		}
	}
	if !found {
		t.Error("--include-test-support should keep mocks")
	}
}

func TestNextURL(t *testing.T) {
	cases := map[string]string{
		"apps/site/app/(marketing)/[slug]/opengraph": "/{slug}/opengraph",
		"apps/x/src/app/api/[[...rest]]":             "/api/{rest...}",
		"apps/x/app/@modal/a/[...all]":               "/a/{all...}",
	}
	for in, want := range cases {
		got, ok := nextURL(strings.Split(in, "/"), "app")
		if !ok || got != want {
			t.Errorf("nextURL(%s) = %q, want %q", in, got, want)
		}
	}
}

package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
	"github.com/xleelz/mosaic/pkg/client"
)

func fixture(t *testing.T, scenarios bool) (*step, []*step) {
	t.Helper()
	b, steps, err := build(buildOptions{Base: "testdata/base", History: "testdata/history", Scenarios: scenarios})
	if err != nil {
		t.Fatal(err)
	}
	return b, steps
}

func TestBuild(t *testing.T) {
	base, steps := fixture(t, true)
	if len(steps) != 3 {
		t.Fatalf("%d steps", len(steps))
	}
	if !reflect.DeepEqual(base.Changed, []string{"api", "skeleton", "storage"}) || !base.ok() || base.Passed != 1 {
		t.Errorf("base: %+v", base)
	}

	s1 := steps[0]
	if !reflect.DeepEqual(s1.Changed, []string{"storage"}) || !s1.ok() || s1.Doc.Source.SHA != s1.Meta.SHA || s1.Doc.Source.Repo != "example/tiny" {
		t.Errorf("step 1: %+v", s1)
	}
	if !reflect.DeepEqual(s1.Impact.Interfaces.Modified, []string{"store.read"}) ||
		!reflect.DeepEqual(s1.Impact.FlowsAffected, []model.FlowImpact{
			{Flow: "get", Reasons: []string{"interface:store.read"}, Basis: "traces"},
			{Flow: "read", Reasons: []string{"interface:store.read"}, Basis: "static"}}) {
		t.Errorf("step 1 impact: %+v", s1.Impact)
	}
	if base.Doc.Source.SHA != "0000000000000000000000000000000000000000" {
		t.Error("a step's source leaked into the base")
	}

	s2 := steps[1]
	if len(s2.Changed) != 0 || impactText(s2.Impact) != "no change" || !s2.Ran || s2.Passed != 1 {
		t.Errorf("step 2 (no modeled change): %+v %s", s2, impactText(s2.Impact))
	}

	s3 := steps[2]
	if !reflect.DeepEqual(s3.Changed, []string{"audit"}) || !reflect.DeepEqual(s3.Removed, []string{"storage"}) {
		t.Errorf("step 3 areas: %v %v", s3.Changed, s3.Removed)
	}
	if s3.Passed != 1 || s3.Failed != 1 || len(s3.Failures) != 1 || !strings.HasPrefix(s3.Failures[0], "get-fails") {
		t.Errorf("step 3 scenarios: %d passed %d failed %v", s3.Passed, s3.Failed, s3.Failures)
	}
	if !reflect.DeepEqual(s3.Impact.Flows.Removed, []string{"read"}) || !reflect.DeepEqual(s3.Impact.Components.Added, []string{"audit"}) {
		t.Errorf("step 3 impact: %+v", s3.Impact)
	}

	out := t.TempDir()
	md, err := writeOutputs(out, base, steps)
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{"base.json", "01-aaaaaaaaaaaa.json", "02-bbbbbbbbbbbb.json", "03-cccccccccccc.json", "summary.json", "summary.md"} {
		if _, err := os.Stat(filepath.Join(out, f)); err != nil {
			t.Error(err)
		}
	}
	data, _ := os.ReadFile(filepath.Join(out, "02-bbbbbbbbbbbb.json"))
	doc, err := model.ParseDocument(data)
	if err != nil || len(doc.Components) != 4 || doc.Source.SHA != s2.Meta.SHA {
		t.Errorf("02 document: %v %+v", err, doc)
	}
	for _, want := range []string{
		"| 01-aaaaaaaaaaaa | aaaaaaaaaaaa storage: return two rows | storage | 4 | 2 | 0 | 0 | 2 | 1 | 1/1 passed | interfaces ~1; 2 flows affected |",
		"| 03-cccccccccccc | cccccccccccc add audit; drop the storage area | audit (removed storage) | 5 | 3 | 0 | 0 | 1 | 2 | 1/2 passed |",
	} {
		if !strings.Contains(md, want) {
			t.Errorf("summary lacks %q:\n%s", want, md)
		}
	}
	if code := report(io.Discard, base, steps, true); code != 1 {
		t.Errorf("exit status %d, want 1 for the failing scenario", code)
	}
}

func TestBuildAreaOrderAndErrors(t *testing.T) {
	b := &builder{opts: buildOptions{Areas: []string{"storage"}}}
	got := b.order(map[string]string{"api": "", "storage": "", "skeleton": "", "audit": ""})
	if !reflect.DeepEqual(got, []string{"skeleton", "storage", "api", "audit"}) {
		t.Errorf("order %v", got)
	}
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, "01-abcdabcdabcd"), 0o755)
	os.WriteFile(filepath.Join(dir, "01-abcdabcdabcd", "commit.json"), []byte(`{"sha": "ffff"}`), 0o644)
	if _, _, err := build(buildOptions{Base: "testdata/base", History: dir}); err == nil || !strings.Contains(err.Error(), "doesn't match") {
		t.Errorf("sha mismatch: %v", err)
	}
}

func TestImport(t *testing.T) {
	base, steps := fixture(t, false)
	steps = steps[:2]
	var mu sync.Mutex
	var calls []string
	var revs []api.CreateRevision
	var docs []model.Document
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		calls = append(calls, r.Method+" "+r.URL.Path)
		body, _ := io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == "GET" && r.URL.Path == "/v1/ontologies/tiny":
			w.WriteHeader(404)
			io.WriteString(w, `{"error": {"code": "not_found", "message": "no such ontology"}}`)
		case r.Method == "POST" && r.URL.Path == "/v1/ontologies":
			io.WriteString(w, `{"id": "tiny", "name": "Tiny", "counts": {}}`)
		case r.Method == "PUT" && r.URL.Path == "/v1/ontologies/tiny/document":
			var d model.Document
			json.Unmarshal(body, &d)
			docs = append(docs, d)
			io.WriteString(w, `{"counts": {}, "valid": true, "issues": []}`)
		case r.Method == "POST" && r.URL.Path == "/v1/ontologies/tiny/revisions":
			var cr api.CreateRevision
			json.Unmarshal(body, &cr)
			revs = append(revs, cr)
			json.NewEncoder(w).Encode(api.Revision{Number: len(revs), Message: cr.Message, Source: cr.Source})
		default:
			w.WriteHeader(500)
		}
	}))
	defer srv.Close()
	var log strings.Builder
	err := importSteps(context.Background(), client.New(srv.URL, ""), "tiny", base, steps, importOptions{
		repoName: func(m commitMeta) string { return "example/tiny" }, withBase: true, log: &log})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"GET /v1/ontologies/tiny", "POST /v1/ontologies",
		"PUT /v1/ontologies/tiny/document", "POST /v1/ontologies/tiny/revisions",
		"PUT /v1/ontologies/tiny/document", "POST /v1/ontologies/tiny/revisions",
		"PUT /v1/ontologies/tiny/document", "POST /v1/ontologies/tiny/revisions"}
	if !reflect.DeepEqual(calls, want) {
		t.Errorf("calls:\n%v\nwant\n%v", calls, want)
	}
	if len(revs) != 3 || !revs[1].AllowEmpty || revs[1].Source == nil || revs[1].Source.SHA != steps[0].Meta.SHA ||
		revs[1].Source.Parent != steps[0].Meta.Parent || revs[1].Source.Repo != "example/tiny" || revs[1].Author != "Dev" ||
		revs[1].Message != "aaaaaaaaaaaa storage: return two rows" || revs[0].Source.SHA != "0000000000000000000000000000000000000000" {
		t.Errorf("revisions: %+v", revs)
	}
	if len(docs) != 3 || docs[2].Source.SHA != steps[1].Meta.SHA {
		t.Errorf("documents: %+v", docs)
	}
}

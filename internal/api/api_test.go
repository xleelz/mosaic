package api_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/api"
	"github.com/xleelz/mosaic/internal/doltserver"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/store"
	wire "github.com/xleelz/mosaic/pkg/api"
)

var (
	st      *store.Store
	baseURL string
)

func TestMain(m *testing.M) {
	if _, err := exec.LookPath("dolt"); err != nil {
		fmt.Println("skipping: dolt binary not found")
		os.Exit(0)
	}
	os.Exit(runMain(m))
}

func runMain(m *testing.M) int {
	dir, err := os.MkdirTemp("", "mosaic-api-test-")
	if err != nil {
		log.Fatal(err)
	}
	defer os.RemoveAll(dir)
	ctx := context.Background()
	srv, err := doltserver.Start(ctx, doltserver.Options{Bin: "dolt", DataDir: dir})
	if err != nil {
		log.Fatal(err)
	}
	defer srv.Stop()
	st, err = store.Open(ctx, srv.DB)
	if err != nil {
		log.Print(err)
		return 1
	}
	h := api.New(api.Config{Store: st, Version: "test", Logger: log.New(io.Discard, "", 0),
		DoltVersion: func(context.Context) (string, error) { return srv.Version(ctx), nil }})
	ts := httptest.NewServer(h)
	defer ts.Close()
	baseURL = ts.URL
	return m.Run()
}

// call sends a request and checks the status. body may be nil, []byte, a
// string or a value to encode as JSON.
func call(t *testing.T, method, path string, body any, want int) []byte {
	t.Helper()
	return callURL(t, baseURL, nil, method, path, body, want)
}

func callURL(t *testing.T, base string, hdr http.Header, method, path string, body any, want int) []byte {
	t.Helper()
	var rd io.Reader
	switch b := body.(type) {
	case nil:
	case []byte:
		rd = bytes.NewReader(b)
	case string:
		rd = strings.NewReader(b)
	default:
		js, err := json.Marshal(b)
		if err != nil {
			t.Fatal(err)
		}
		rd = bytes.NewReader(js)
	}
	req, err := http.NewRequest(method, base+path, rd)
	if err != nil {
		t.Fatal(err)
	}
	for k, v := range hdr {
		req.Header[k] = v
	}
	if rd != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	out, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != want {
		t.Fatalf("%s %s: status %d, want %d: %s", method, path, resp.StatusCode, want, out)
	}
	return out
}

func decode[T any](t *testing.T, b []byte) T {
	t.Helper()
	var v T
	if err := json.Unmarshal(b, &v); err != nil {
		t.Fatalf("decode %T: %v: %s", v, err, b)
	}
	return v
}

func exampleJSON(t *testing.T) []byte {
	t.Helper()
	data, err := os.ReadFile("../testdata/gateway/ontology.yaml")
	if err != nil {
		t.Fatal(err)
	}
	doc, err := model.ParseDocument(data)
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// newOntology creates an ontology and loads the example into its draft.
func newOntology(t *testing.T, id string, load bool) {
	t.Helper()
	call(t, "POST", "/v1/ontologies", wire.CreateOntology{ID: id, Name: "Test " + id}, 201)
	if load {
		res := decode[wire.PutDocumentResult](t, call(t, "PUT", "/v1/ontologies/"+id+"/document", exampleJSON(t), 200))
		if !res.Valid {
			t.Fatalf("example does not validate: %+v", res.Issues)
		}
	}
}

func sameRev(a, b wire.Revision) bool {
	return a.Number == b.Number && a.Hash == b.Hash && a.Message == b.Message && a.Author == b.Author && a.CreatedAt.Equal(b.CreatedAt)
}

func errCode(t *testing.T, b []byte) wire.ErrorDetail {
	t.Helper()
	return decode[wire.ErrorBody](t, b).Error
}

func TestHealth(t *testing.T) {
	h := decode[wire.Health](t, call(t, "GET", "/v1/health", nil, 200))
	if h.Status != "ok" || h.Version != "test" || h.Dolt == "" {
		t.Fatalf("health = %+v", h)
	}
}

func TestOntologyLifecycle(t *testing.T) {
	d := decode[wire.OntologyDetail](t, call(t, "POST", "/v1/ontologies", wire.CreateOntology{ID: "life-cycle_1", Name: "Life", Description: "d"}, 201))
	if d.ID != "life-cycle_1" || d.Name != "Life" || d.RevisionCount != 0 || d.DraftDirty || d.Counts["component"] != 0 {
		t.Fatalf("created = %+v", d)
	}
	e := errCode(t, call(t, "POST", "/v1/ontologies", wire.CreateOntology{ID: "life-cycle_1", Name: "Again"}, 409))
	if e.Code != "conflict" {
		t.Fatalf("duplicate create: %+v", e)
	}
	if e := errCode(t, call(t, "POST", "/v1/ontologies", wire.CreateOntology{ID: "Bad.Id"}, 400)); e.Code != "bad_request" {
		t.Fatalf("bad id: %+v", e)
	}
	call(t, "POST", "/v1/ontologies", `{"id":"x1","name":"n","bogus":1}`, 400)

	list := decode[wire.OntologyList](t, call(t, "GET", "/v1/ontologies", nil, 200))
	found := false
	for _, o := range list.Ontologies {
		found = found || o.ID == "life-cycle_1"
	}
	if !found {
		t.Fatalf("list misses the ontology: %+v", list)
	}
	name := "Renamed"
	d = decode[wire.OntologyDetail](t, call(t, "PATCH", "/v1/ontologies/life-cycle_1", wire.UpdateOntology{Name: &name}, 200))
	if d.Name != "Renamed" || d.Description != "d" {
		t.Fatalf("renamed = %+v", d)
	}
	d = decode[wire.OntologyDetail](t, call(t, "GET", "/v1/ontologies/life-cycle_1", nil, 200))
	if d.Name != "Renamed" || len(d.Counts) != len(model.Kinds) {
		t.Fatalf("get = %+v", d)
	}
	if e := errCode(t, call(t, "GET", "/v1/ontologies/nope", nil, 404)); e.Code != "not_found" {
		t.Fatalf("missing: %+v", e)
	}
}

func TestDocumentAndRevisions(t *testing.T) {
	id := "gateway"
	newOntology(t, id, true)

	d := decode[wire.OntologyDetail](t, call(t, "GET", "/v1/ontologies/"+id, nil, 200))
	if !d.DraftDirty || d.Counts["component"] != 20 || d.Counts["scenario"] != 14 {
		t.Fatalf("detail after import = %+v", d)
	}
	// latest before any revision is a 404.
	call(t, "GET", "/v1/ontologies/"+id+"/document?rev=latest", nil, 404)

	rev := decode[wire.Revision](t, call(t, "POST", "/v1/ontologies/"+id+"/revisions",
		wire.CreateRevision{Message: "Model the gateway", Author: "Ada <ada@example.com>"}, 201))
	if rev.Number != 1 || rev.Hash == "" || rev.Author != "Ada <ada@example.com>" || rev.Message != "Model the gateway" || rev.CreatedAt.IsZero() {
		t.Fatalf("revision = %+v", rev)
	}
	// Unchanged: 409.
	if e := errCode(t, call(t, "POST", "/v1/ontologies/"+id+"/revisions", wire.CreateRevision{Message: "again"}, 409)); e.Code != "conflict" {
		t.Fatalf("unchanged revision: %+v", e)
	}
	// Re-importing the same document leaves the draft clean.
	call(t, "PUT", "/v1/ontologies/"+id+"/document", exampleJSON(t), 200)
	d = decode[wire.OntologyDetail](t, call(t, "GET", "/v1/ontologies/"+id, nil, 200))
	if d.DraftDirty || d.LatestRevision != 1 || d.RevisionCount != 1 {
		t.Fatalf("detail after re-import = %+v", d)
	}
	call(t, "POST", "/v1/ontologies/"+id+"/revisions", wire.CreateRevision{Message: "again"}, 409)

	revs := decode[wire.RevisionList](t, call(t, "GET", "/v1/ontologies/"+id+"/revisions", nil, 200))
	if len(revs.Revisions) != 1 || !sameRev(revs.Revisions[0], rev) {
		t.Fatalf("revisions = %+v, want [%+v]", revs, rev)
	}
	got := decode[wire.Revision](t, call(t, "GET", "/v1/ontologies/"+id+"/revisions/1", nil, 200))
	if !sameRev(got, rev) {
		t.Fatalf("revision 1 = %+v", got)
	}
	call(t, "GET", "/v1/ontologies/"+id+"/revisions/2", nil, 404)

	// Documents read back equal at the draft and at revision 1.
	for _, sel := range []string{"draft", "latest", "1", "r1"} {
		doc := decode[model.Document](t, call(t, "GET", "/v1/ontologies/"+id+"/document?rev="+sel, nil, 200))
		if len(doc.Components) != 20 || len(doc.Scenarios) != 14 || doc.ID != id || doc.Source == nil || doc.Source.Repo != "example/gateway" {
			t.Fatalf("document at %s: %d components, %d scenarios, id %q, source %+v", sel, len(doc.Components), len(doc.Scenarios), doc.ID, doc.Source)
		}
	}
	v := decode[wire.Validation](t, call(t, "POST", "/v1/ontologies/"+id+"/validate?rev=1", nil, 200))
	if !v.Valid || v.Revision != "1" {
		t.Fatalf("validation = %+v", v)
	}
}

func TestInvalidDraft(t *testing.T) {
	id := "invalid-draft"
	newOntology(t, id, false)
	call(t, "POST", "/v1/ontologies/"+id+"/revisions", wire.CreateRevision{Message: "empty"}, 409)
	// A link to nowhere is stored, but the draft no longer validates.
	res := decode[wire.UpsertResult](t, call(t, "POST", "/v1/ontologies/"+id+"/links", `{"id":"dangling","from":"a","to":"b"}`, 201))
	if len(res.Issues) == 0 || res.IDs[0] != "dangling" {
		t.Fatalf("upsert result = %+v", res)
	}
	v := decode[wire.Validation](t, call(t, "POST", "/v1/ontologies/"+id+"/validate", nil, 200))
	if v.Valid || v.Revision != "draft" || len(v.Issues) == 0 {
		t.Fatalf("validation = %+v", v)
	}
	e := errCode(t, call(t, "POST", "/v1/ontologies/"+id+"/revisions", wire.CreateRevision{Message: "bad"}, 422))
	if e.Code != "invalid" || len(e.Issues) == 0 {
		t.Fatalf("invalid revision: %+v", e)
	}
	if !strings.Contains(e.Issues[0].Path, "links[dangling]") {
		t.Fatalf("issues = %+v", e.Issues)
	}
}

func TestEntityCRUDAndHistory(t *testing.T) {
	id := "entities"
	newOntology(t, id, true)
	call(t, "POST", "/v1/ontologies/"+id+"/revisions", wire.CreateRevision{Message: "r1"}, 201)
	base := "/v1/ontologies/" + id

	// GET one and list.
	var comp model.Component
	comp = decode[model.Component](t, call(t, "GET", base+"/components/billing", nil, 200))
	if comp.ID != "billing" || comp.Name == "" {
		t.Fatalf("component = %+v", comp)
	}
	oldName := comp.Name
	items := decode[wire.Items](t, call(t, "GET", base+"/components", nil, 200))
	if len(items.Items) != 20 {
		t.Fatalf("components: %d", len(items.Items))
	}
	items = decode[wire.Items](t, call(t, "GET", base+"/scenario", nil, 200)) // singular works too
	if len(items.Items) != 14 {
		t.Fatalf("scenarios: %d", len(items.Items))
	}
	call(t, "GET", base+"/widgets", nil, 404)
	call(t, "GET", base+"/components/nope", nil, 404)

	// Strict decoding and id checks.
	if e := errCode(t, call(t, "PUT", base+"/components/billing", `{"id":"billing","colour":"red"}`, 400)); !strings.Contains(e.Message, "colour") {
		t.Fatalf("unknown field: %+v", e)
	}
	call(t, "PUT", base+"/components/billing", `{"id":"other"}`, 400)
	call(t, "POST", base+"/components", `{"id":"billing"}`, 409)
	call(t, "POST", base+"/components", `{"name":"no id"}`, 400)

	// PUT (the path supplies a missing id), PATCH, DELETE.
	res := decode[wire.UpsertResult](t, call(t, "PUT", base+"/components/audit-log", `{"name":"Audit log","kind":"datastore"}`, 200))
	if res.Kind != "component" || len(res.IDs) != 1 || res.IDs[0] != "audit-log" {
		t.Fatalf("put = %+v", res)
	}
	call(t, "PATCH", base+"/components/billing", `{"name":"Billing v2","tags":["billing"],"summary":null}`, 200)
	comp = decode[model.Component](t, call(t, "GET", base+"/components/billing", nil, 200))
	if comp.Name != "Billing v2" || len(comp.Tags) != 1 || comp.Summary != "" || comp.Kind == "" {
		t.Fatalf("patched = %+v", comp)
	}
	call(t, "PATCH", base+"/components/billing", `{"bogus":true}`, 400)
	call(t, "PATCH", base+"/components/billing", `{"id":"renamed"}`, 400)
	call(t, "PATCH", base+"/components/ghost", `{"name":"x"}`, 404)
	// Interfaces normalize their id from component and name.
	iface := decode[wire.UpsertResult](t, call(t, "PUT", base+"/interfaces/audit-log.append", `{"component":"audit-log","name":"append","kind":"function"}`, 200))
	if iface.IDs[0] != "audit-log.append" {
		t.Fatalf("interface = %+v", iface)
	}
	call(t, "PUT", base+"/interfaces/audit-log.other", `{"component":"audit-log","name":"append"}`, 400)
	// Upsert many.
	many := decode[wire.UpsertResult](t, call(t, "PUT", base+"/links", `{"items":[{"id":"l-one","from":"billing","to":"audit-log"},{"id":"l-two","from":"audit-log","to":"billing"}]}`, 200))
	if len(many.IDs) != 2 {
		t.Fatalf("many = %+v", many)
	}
	call(t, "DELETE", base+"/links/l-two", nil, 204)
	call(t, "DELETE", base+"/links/l-two", nil, 404)

	// AS OF: revision 1 still has the old values.
	old := decode[model.Component](t, call(t, "GET", base+"/components/billing?rev=1", nil, 200))
	if old.Name != oldName {
		t.Fatalf("billing at r1 = %q, want %q", old.Name, oldName)
	}
	call(t, "GET", base+"/components/audit-log?rev=1", nil, 404)
	call(t, "GET", base+"/components/audit-log?rev=draft", nil, 200)
	call(t, "GET", base+"/components?rev=9", nil, 404)
	call(t, "GET", base+"/components?rev=banana", nil, 400)

	// Diff 1 -> draft (and the default, latest -> draft).
	for _, q := range []string{"?from=1&to=draft", ""} {
		diff := decode[wire.Diff](t, call(t, "GET", base+"/diff"+q, nil, 200))
		if diff.From != "1" || diff.To != "draft" {
			t.Fatalf("diff%s from/to = %s/%s", q, diff.From, diff.To)
		}
		got := map[string]string{}
		for _, c := range diff.Changes {
			got[c.Kind+"/"+c.ID] = c.Change
		}
		want := map[string]string{"component/audit-log": "added", "component/billing": "modified",
			"interface/audit-log.append": "added", "link/l-one": "added"}
		if fmt.Sprint(got) != fmt.Sprint(want) {
			t.Fatalf("diff%s = %v, want %v", q, got, want)
		}
		for _, c := range diff.Changes {
			if c.Kind+"/"+c.ID == "component/billing" && (c.Before == nil || c.After == nil) {
				t.Fatalf("modified change lacks before/after: %+v", c)
			}
		}
	}
	// The draft is dirty; revision 2 records it and diff 1 -> 2 matches.
	call(t, "POST", base+"/revisions", wire.CreateRevision{Message: "r2"}, 201)
	diff := decode[wire.Diff](t, call(t, "GET", base+"/diff?from=1&to=2", nil, 200))
	if len(diff.Changes) != 4 {
		t.Fatalf("diff 1->2 = %+v", diff.Changes)
	}
	diff = decode[wire.Diff](t, call(t, "GET", base+"/diff", nil, 200))
	if diff.From != "2" || len(diff.Changes) != 0 {
		t.Fatalf("diff latest->draft after r2 = %+v", diff)
	}
}

func TestSimulations(t *testing.T) {
	id := "sims"
	newOntology(t, id, true)
	call(t, "POST", "/v1/ontologies/"+id+"/revisions", wire.CreateRevision{Message: "r1"}, 201)
	base := "/v1/ontologies/" + id

	run := decode[wire.SimulationRun](t, call(t, "POST", base+"/simulations", `{"scenario":"retry-before-commit","rev":"1"}`, 201))
	if !run.Summary.Passed || run.Scenario != "retry-before-commit" || run.Flow != "chat-stream" || run.Revision != "1" ||
		!strings.HasPrefix(run.ID, "run_") || len(run.Trace) == 0 || run.Ontology != id {
		t.Fatalf("run = %+v", run.Summary)
	}
	// Not saved.
	adhoc := decode[wire.SimulationRun](t, call(t, "POST", base+"/simulations", `{"flow":"chat-stream","save":false}`, 200))
	if adhoc.Revision != "draft" {
		t.Fatalf("adhoc revision = %s", adhoc.Revision)
	}
	call(t, "GET", "/v1/simulations/"+adhoc.ID, nil, 404)
	// Request errors.
	if e := errCode(t, call(t, "POST", base+"/simulations", `{"scenario":"no-such"}`, 400)); e.Code != "bad_request" {
		t.Fatalf("unknown scenario: %+v", e)
	}
	call(t, "POST", base+"/simulations", `{"flow":"chat-stream","colour":1}`, 400)
	call(t, "POST", base+"/simulations", `{"flow":"chat-stream","rev":"7"}`, 404)

	second := decode[wire.SimulationRun](t, call(t, "POST", base+"/simulations", `{"scenario":"happy-path"}`, 201))
	list := decode[wire.RunList](t, call(t, "GET", base+"/simulations", nil, 200))
	if len(list.Runs) != 2 || list.Runs[0].ID != second.ID || list.Runs[1].ID != run.ID {
		t.Fatalf("runs = %+v", list.Runs)
	}
	for _, r := range list.Runs {
		if r.Trace != nil {
			t.Fatalf("listed run %s has a trace", r.ID)
		}
	}
	if l := decode[wire.RunList](t, call(t, "GET", base+"/simulations?limit=1", nil, 200)); len(l.Runs) != 1 {
		t.Fatalf("limit=1 gave %d runs", len(l.Runs))
	}
	got := decode[wire.SimulationRun](t, call(t, "GET", "/v1/simulations/"+run.ID, nil, 200))
	if got.ID != run.ID || !got.Summary.Passed || len(got.Trace) != len(run.Trace) || got.Request.Scenario != "retry-before-commit" {
		t.Fatalf("stored run = %+v", got.Summary)
	}
	a, _ := json.Marshal(run.Trace)
	b, _ := json.Marshal(got.Trace)
	if !bytes.Equal(a, b) {
		t.Fatalf("stored trace differs")
	}

	rep := decode[wire.TestReport](t, call(t, "POST", base+"/test?rev=latest", nil, 200))
	if !rep.Passed || rep.Total != 14 || rep.Failed != 0 || rep.Revision != "1" {
		t.Fatalf("test report = %+v", rep)
	}
	for _, r := range rep.Results {
		if !r.Passed || r.RunID == "" || len(r.Assertions) == 0 {
			t.Fatalf("result = %+v", r)
		}
	}
	call(t, "GET", "/v1/simulations/"+rep.Results[0].RunID, nil, 200)
	if l := decode[wire.RunList](t, call(t, "GET", base+"/simulations?limit=100", nil, 200)); len(l.Runs) != 16 {
		t.Fatalf("after test: %d runs", len(l.Runs))
	}
}

func TestGraphAndPlan(t *testing.T) {
	id := "graph-plan"
	newOntology(t, id, true)
	base := "/v1/ontologies/" + id
	g := decode[model.Graph](t, call(t, "GET", base+"/graph", nil, 200))
	if len(g.Nodes) != 20 || len(g.Edges) == 0 {
		t.Fatalf("graph: %d nodes, %d edges", len(g.Nodes), len(g.Edges))
	}
	p := decode[model.Plan](t, call(t, "GET", base+"/flows/chat-stream/plan", nil, 200))
	if p.Flow != "chat-stream" || len(p.Interfaces) == 0 || len(p.Choices) == 0 || len(p.Scenarios) != 14 || len(p.Faultable) == 0 {
		t.Fatalf("plan = %+v", p)
	}
	call(t, "GET", base+"/flows/nope/plan", nil, 404)
	call(t, "GET", base+"/graph?rev=latest", nil, 404)
}

func TestAuthAndCORS(t *testing.T) {
	h := api.New(api.Config{Store: st, Version: "test", Token: "s3cret", Logger: log.New(io.Discard, "", 0)})
	ts := httptest.NewServer(h)
	defer ts.Close()

	if e := errCode(t, callURL(t, ts.URL, nil, "GET", "/v1/ontologies", nil, 401)); e.Code != "unauthorized" {
		t.Fatalf("no token: %+v", e)
	}
	callURL(t, ts.URL, http.Header{"Authorization": {"Bearer wrong"}}, "GET", "/v1/health", nil, 401)
	callURL(t, ts.URL, http.Header{"Authorization": {"Bearer s3cret"}}, "GET", "/v1/ontologies", nil, 200)

	// Preflight needs no token.
	req, _ := http.NewRequest("OPTIONS", ts.URL+"/v1/ontologies", nil)
	req.Header.Set("Origin", "http://localhost:3000")
	req.Header.Set("Access-Control-Request-Method", "PUT")
	req.Header.Set("Access-Control-Request-Headers", "authorization, content-type")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 204 || resp.Header.Get("Access-Control-Allow-Origin") != "http://localhost:3000" ||
		!strings.Contains(resp.Header.Get("Access-Control-Allow-Methods"), "PATCH") ||
		!strings.Contains(resp.Header.Get("Access-Control-Allow-Headers"), "Authorization") {
		t.Fatalf("preflight: %d %v", resp.StatusCode, resp.Header)
	}
	// A disallowed origin gets no CORS headers.
	req.Header.Set("Origin", "http://evil.example")
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.Header.Get("Access-Control-Allow-Origin") != "" {
		t.Fatalf("disallowed origin allowed: %v", resp.Header)
	}
	// Actual requests from an allowed origin carry the header, even on 401.
	req, _ = http.NewRequest("GET", ts.URL+"/v1/health", nil)
	req.Header.Set("Origin", "http://127.0.0.1:3000")
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 401 || resp.Header.Get("Access-Control-Allow-Origin") != "http://127.0.0.1:3000" {
		t.Fatalf("cors on 401: %d %v", resp.StatusCode, resp.Header)
	}
}

func TestDeleteOntology(t *testing.T) {
	id := "doomed"
	newOntology(t, id, true)
	call(t, "POST", "/v1/ontologies/"+id+"/revisions", wire.CreateRevision{Message: "r1"}, 201)
	run := decode[wire.SimulationRun](t, call(t, "POST", "/v1/ontologies/"+id+"/simulations", `{"scenario":"happy-path"}`, 201))
	call(t, "DELETE", "/v1/ontologies/"+id, nil, 204)
	call(t, "GET", "/v1/ontologies/"+id, nil, 404)
	call(t, "GET", "/v1/ontologies/"+id+"/components", nil, 404)
	call(t, "GET", "/v1/simulations/"+run.ID, nil, 404)
	call(t, "DELETE", "/v1/ontologies/"+id, nil, 404)
	// Recreating starts from scratch: no revisions, empty clean draft.
	d := decode[wire.OntologyDetail](t, call(t, "POST", "/v1/ontologies", wire.CreateOntology{ID: id, Name: "Again"}, 201))
	if d.RevisionCount != 0 || d.DraftDirty || d.Counts["component"] != 0 {
		t.Fatalf("recreated = %+v", d)
	}
}

package client

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
	"github.com/xleelz/mosaic/pkg/api"
)

// recorded is one request the test server saw.
type recorded struct {
	Method, Path, Query, Body, Auth, ContentType string
}

// stub answers every request with status and body, and records it.
type stub struct {
	t      *testing.T
	srv    *httptest.Server
	last   recorded
	status int
	body   string
}

func newStub(t *testing.T) *stub {
	s := &stub{t: t, status: 200}
	s.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		s.last = recorded{Method: r.Method, Path: r.URL.Path, Query: r.URL.RawQuery, Body: string(b),
			Auth: r.Header.Get("Authorization"), ContentType: r.Header.Get("Content-Type")}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(s.status)
		io.WriteString(w, s.body)
	}))
	t.Cleanup(s.srv.Close)
	return s
}

func (s *stub) reply(status int, body string) { s.status, s.body = status, body }

func (s *stub) expect(method, path, query string) {
	s.t.Helper()
	if s.last.Method != method || s.last.Path != path || s.last.Query != query {
		s.t.Fatalf("request = %s %s?%s, want %s %s?%s", s.last.Method, s.last.Path, s.last.Query, method, path, query)
	}
}

func (s *stub) expectBody(want string) {
	s.t.Helper()
	if !jsonEqual(s.t, s.last.Body, want) {
		s.t.Fatalf("body = %s, want %s", s.last.Body, want)
	}
	if s.last.ContentType != "application/json" {
		s.t.Fatalf("content-type = %q", s.last.ContentType)
	}
}

func jsonEqual(t *testing.T, a, b string) bool {
	t.Helper()
	var x, y any
	if err := json.Unmarshal([]byte(a), &x); err != nil {
		t.Fatalf("not JSON: %s: %v", a, err)
	}
	if err := json.Unmarshal([]byte(b), &y); err != nil {
		t.Fatalf("not JSON: %s: %v", b, err)
	}
	return reflect.DeepEqual(x, y)
}

var ctx = context.Background()

func TestNewNormalizesBaseURL(t *testing.T) {
	for _, in := range []string{"http://h:1", "http://h:1/", "http://h:1/v1", "http://h:1/v1/"} {
		if got := New(in, "").BaseURL(); got != "http://h:1/v1" {
			t.Errorf("New(%q).BaseURL() = %q", in, got)
		}
	}
	c := New("http://h:1", "")
	if c.http.Timeout != DefaultTimeout || DefaultTimeout != 60*time.Second {
		t.Errorf("default timeout = %v", c.http.Timeout)
	}
}

func TestHealthAndToken(t *testing.T) {
	s := newStub(t)
	s.reply(200, `{"status":"ok","version":"v0","dolt":"ok"}`)
	h, err := New(s.srv.URL, "sekret").Health(ctx)
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/health", "")
	if s.last.Auth != "Bearer sekret" {
		t.Errorf("auth = %q", s.last.Auth)
	}
	if *h != (api.Health{Status: "ok", Version: "v0", Dolt: "ok"}) {
		t.Errorf("health = %+v", h)
	}
	if _, err := New(s.srv.URL, "").Health(ctx); err != nil {
		t.Fatal(err)
	}
	if s.last.Auth != "" {
		t.Errorf("auth sent without a token: %q", s.last.Auth)
	}
}

func TestOntologies(t *testing.T) {
	s := newStub(t)
	c := New(s.srv.URL, "")

	s.reply(200, `{"ontologies":[{"id":"a","name":"A","latest_revision":2,"revision_count":2}]}`)
	list, err := c.ListOntologies(ctx)
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies", "")
	if len(list) != 1 || list[0].ID != "a" || list[0].LatestRevision != 2 {
		t.Errorf("list = %+v", list)
	}

	s.reply(200, `{"ontologies":null}`)
	if list, err = c.ListOntologies(ctx); err != nil || list == nil || len(list) != 0 {
		t.Errorf("empty list = %#v, %v", list, err)
	}

	s.reply(200, `{"id":"a","name":"A","counts":{"component":3},"draft_dirty":true}`)
	d, err := c.GetOntology(ctx, "a")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/a", "")
	if d.Counts["component"] != 3 || !d.DraftDirty || d.Name != "A" {
		t.Errorf("detail = %+v", d)
	}

	s.reply(201, `{"id":"b","name":"B"}`)
	if _, err := c.CreateOntology(ctx, api.CreateOntology{ID: "b", Name: "B"}); err != nil {
		t.Fatal(err)
	}
	s.expect("POST", "/v1/ontologies", "")
	s.expectBody(`{"id":"b","name":"B"}`)

	name := "B2"
	s.reply(200, `{"id":"b","name":"B2"}`)
	if d, err = c.UpdateOntology(ctx, "b", api.UpdateOntology{Name: &name}); err != nil || d.Name != "B2" {
		t.Fatal(d, err)
	}
	s.expect("PATCH", "/v1/ontologies/b", "")
	s.expectBody(`{"name":"B2"}`)

	s.reply(204, ``)
	if err := c.DeleteOntology(ctx, "b"); err != nil {
		t.Fatal(err)
	}
	s.expect("DELETE", "/v1/ontologies/b", "")
}

func TestDocuments(t *testing.T) {
	s := newStub(t)
	c := New(s.srv.URL, "")

	s.reply(200, `{"schema_version":1,"id":"a","components":[{"id":"svc","attributes":{"big":12345678901234567890}}],
		"interfaces":[{"component":"svc","name":"get","latency_ms":{"min":1,"max":3}}],"links":[],"schemas":[],"flows":[],"scenarios":[]}`)
	doc, err := c.GetDocument(ctx, "a", "latest")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/a/document", "rev=latest")
	if len(doc.Components) != 1 || doc.Interfaces[0].LatencyMS.Max != 3 {
		t.Errorf("doc = %+v", doc)
	}
	// Numbers survive a round trip exactly.
	b, _ := json.Marshal(doc.Components[0].Attributes)
	if string(b) != `{"big":12345678901234567890}` {
		t.Errorf("attributes = %s", b)
	}

	raw, err := c.GetDocumentJSON(ctx, "a", "")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/a/document", "")
	if !strings.HasPrefix(string(raw), `{"schema_version":1`) {
		t.Errorf("raw = %s", raw)
	}

	s.reply(200, `{"counts":{"component":1},"valid":false,"issues":[{"path":"components[0].parent","message":"unknown","severity":"error"}]}`)
	res, err := c.PutDocument(ctx, "a", json.RawMessage(`{"schema_version":1,"components":[{"id":"x","parent":"y"}]}`))
	if err != nil {
		t.Fatal(err)
	}
	s.expect("PUT", "/v1/ontologies/a/document", "")
	s.expectBody(`{"schema_version":1,"components":[{"id":"x","parent":"y"}]}`)
	if res.Valid || len(res.Issues) != 1 || res.Issues[0].Path != "components[0].parent" || res.Counts["component"] != 1 {
		t.Errorf("result = %+v", res)
	}
}

func TestEntities(t *testing.T) {
	s := newStub(t)
	c := New(s.srv.URL, "")

	s.reply(200, `{"items":[{"id":"a"},{"id":"b"}]}`)
	items, err := c.ListEntities(ctx, "o", "component", "3")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/o/components", "rev=3")
	if len(items) != 2 || string(items[1]) != `{"id":"b"}` {
		t.Errorf("items = %s", items)
	}

	s.reply(200, `{"component":"svc","name":"get"}`)
	e, err := c.GetEntity(ctx, "o", "interfaces", "svc.get", "")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/o/interfaces/svc.get", "")
	if string(e) != `{"component":"svc","name":"get"}` {
		t.Errorf("entity = %s", e)
	}

	s.reply(200, `{"kind":"link","ids":["l1"],"issues":[]}`)
	r, err := c.PutEntity(ctx, "o", "link", "l1", json.RawMessage(`{"id":"l1","from":"a","to":"b"}`))
	if err != nil {
		t.Fatal(err)
	}
	s.expect("PUT", "/v1/ontologies/o/links/l1", "")
	s.expectBody(`{"id":"l1","from":"a","to":"b"}`)
	if r.Kind != "link" || !reflect.DeepEqual(r.IDs, []string{"l1"}) {
		t.Errorf("result = %+v", r)
	}

	s.reply(201, `{"kind":"flow","ids":["f"]}`)
	if _, err := c.CreateEntity(ctx, "o", "flow", map[string]string{"id": "f"}); err != nil {
		t.Fatal(err)
	}
	s.expect("POST", "/v1/ontologies/o/flows", "")
	s.expectBody(`{"id":"f"}`)

	s.reply(200, `{"kind":"schema","ids":["s1","s2"]}`)
	if r, err = c.UpsertEntities(ctx, "o", "schemas", []json.RawMessage{json.RawMessage(`{"id":"s1"}`), json.RawMessage(`{"id":"s2"}`)}); err != nil {
		t.Fatal(err)
	}
	s.expect("PUT", "/v1/ontologies/o/schemas", "")
	s.expectBody(`{"items":[{"id":"s1"},{"id":"s2"}]}`)
	if len(r.IDs) != 2 {
		t.Errorf("result = %+v", r)
	}

	s.reply(200, `{"kind":"scenario","ids":["sc"]}`)
	if _, err := c.PatchEntity(ctx, "o", "scenario", "sc", json.RawMessage(`{"seed":4,"name":null}`)); err != nil {
		t.Fatal(err)
	}
	s.expect("PATCH", "/v1/ontologies/o/scenarios/sc", "")
	s.expectBody(`{"seed":4,"name":null}`)

	s.reply(204, ``)
	if err := c.DeleteEntity(ctx, "o", "components", "a b"); err != nil {
		t.Fatal(err)
	}
	s.expect("DELETE", "/v1/ontologies/o/components/a b", "")

	if _, err := c.ListEntities(ctx, "o", "widgets", ""); err == nil || !strings.Contains(err.Error(), `unknown kind "widgets"`) {
		t.Errorf("unknown kind error = %v", err)
	}
}

func TestRevisionsAndDiff(t *testing.T) {
	s := newStub(t)
	c := New(s.srv.URL, "")

	s.reply(200, `{"revisions":[{"number":1,"hash":"h1","message":"m","author":"a","created_at":"2026-10-30T12:00:00Z"}]}`)
	revs, err := c.ListRevisions(ctx, "o")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/o/revisions", "")
	if len(revs) != 1 || revs[0].Hash != "h1" || revs[0].CreatedAt.Year() != 2026 {
		t.Errorf("revs = %+v", revs)
	}

	s.reply(200, `{"number":2,"message":"m2"}`)
	rev, err := c.GetRevision(ctx, "o", 2)
	if err != nil || rev.Number != 2 {
		t.Fatal(rev, err)
	}
	s.expect("GET", "/v1/ontologies/o/revisions/2", "")

	s.reply(201, `{"number":3,"message":"add x","author":"bot"}`)
	if rev, err = c.CreateRevision(ctx, "o", api.CreateRevision{Message: "add x", Author: "bot"}); err != nil || rev.Number != 3 {
		t.Fatal(rev, err)
	}
	s.expect("POST", "/v1/ontologies/o/revisions", "")
	s.expectBody(`{"message":"add x","author":"bot"}`)

	s.reply(200, `{"from":"1","to":"draft","changes":[{"kind":"component","id":"x","change":"added","after":{"id":"x"}}]}`)
	d, err := c.Diff(ctx, "o", "1", "draft")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/o/diff", "from=1&to=draft")
	if len(d.Changes) != 1 || d.Changes[0].Change != "added" || string(d.Changes[0].After) != `{"id":"x"}` {
		t.Errorf("diff = %+v", d)
	}
	if _, err := c.Diff(ctx, "o", "", ""); err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/o/diff", "")
}

func TestAnalysis(t *testing.T) {
	s := newStub(t)
	c := New(s.srv.URL, "")

	s.reply(200, `{"revision":"draft","valid":false,"issues":[{"path":"flows[f].entry","message":"missing","severity":"error"}]}`)
	v, err := c.Validate(ctx, "o", "draft")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("POST", "/v1/ontologies/o/validate", "rev=draft")
	if v.Valid || v.Issues[0].Severity != model.SeverityError {
		t.Errorf("validation = %+v", v)
	}

	s.reply(200, `{"nodes":[{"id":"a","name":"A","interfaces":[],"leaf":true,"stateful":false}],"edges":[{"id":"e","from":"a","to":"a","kind":"calls","derived":true}]}`)
	g, err := c.Graph(ctx, "o", "")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/o/graph", "")
	if len(g.Nodes) != 1 || !g.Edges[0].Derived {
		t.Errorf("graph = %+v", g)
	}

	s.reply(200, `{"flow":"f","entry":"svc.get","caller":"cli","interfaces":["svc.get"],"components":["cli","svc"],"choices":[{"key":"svc.get.mode","interface":"svc.get","name":"mode","options":["a","b"]}],"state":[],"faultable":["svc"],"scenarios":[]}`)
	p, err := c.Plan(ctx, "o", "f", "latest")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/o/flows/f/plan", "rev=latest")
	if p.Entry != "svc.get" || p.Choices[0].Options[1] != "b" {
		t.Errorf("plan = %+v", p)
	}
}

func TestSimulations(t *testing.T) {
	s := newStub(t)
	c := New(s.srv.URL, "")

	seed := int64(7)
	no := false
	req := api.SimulationRequest{Rev: "latest", Save: &no, Request: sim.Request{
		Flow: "f", Seed: &seed, Input: json.RawMessage(`{"a":1}`), Choices: map[string]model.Choice{"svc.get.mode": model.ChoiceOf("b")},
		State:  map[string]map[string]any{"svc": {"n": 2}},
		Faults: []model.Fault{{Target: "db", Type: "unavailable", Calls: []int{1}}}, Expect: []string{"result.ok"}}}
	s.reply(201, `{"id":"run_1","ontology":"o","revision":"2","flow":"f","request":{"flow":"f"},
		"summary":{"status":"ok","result":{"ok":true,"value":{"n":1}},"duration_ms":5,"events":2,"calls":{},"retries":0,"faults":1,
		"ctx":{},"state":{},"initial_state":{},"assertions":[{"expr":"result.ok","passed":true}],"passed":true,"warnings":[],"seed":7},
		"trace":[{"seq":1,"t":0,"type":"call.start","span":1,"interface":"svc.get"}]}`)
	run, err := c.RunSimulation(ctx, "o", req)
	if err != nil {
		t.Fatal(err)
	}
	s.expect("POST", "/v1/ontologies/o/simulations", "")
	s.expectBody(`{"rev":"latest","flow":"f","seed":7,"input":{"a":1},"choices":{"svc.get.mode":"b"},"state":{"svc":{"n":2}},
		"faults":[{"target":"db","type":"unavailable","calls":[1]}],"expect":["result.ok"],"save":false}`)
	if run.ID != "run_1" || run.Summary.Faults != 1 || len(run.Trace) != 1 || !run.Summary.Assertions[0].Passed {
		t.Errorf("run = %+v", run)
	}

	s.reply(200, `{"runs":[{"id":"run_1"},{"id":"run_0"}]}`)
	runs, err := c.ListRuns(ctx, "o", 2)
	if err != nil || len(runs) != 2 {
		t.Fatal(runs, err)
	}
	s.expect("GET", "/v1/ontologies/o/simulations", "limit=2")
	if _, err := c.ListRuns(ctx, "o", 0); err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/o/simulations", "")

	s.reply(200, `{"id":"run_1","summary":{"status":"error","result":{"ok":false,"error":{"code":"boom","status":500}}}}`)
	run, err = c.GetRun(ctx, "run_1")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/simulations/run_1", "")
	if run.Summary.Result.Error.Code != "boom" {
		t.Errorf("run = %+v", run)
	}

	s.reply(200, `{"revision":"1","passed":false,"total":2,"failed":1,"results":[{"scenario":"a","passed":true,"status":"ok","assertions":[]},{"scenario":"b","passed":false,"status":"error","assertions":[{"expr":"x","passed":false,"error":"no such key"}]}]}`)
	rep, err := c.Test(ctx, "o", "1")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("POST", "/v1/ontologies/o/test", "rev=1")
	if rep.Passed || rep.Failed != 1 || rep.Results[1].Assertions[0].Error != "no such key" {
		t.Errorf("report = %+v", rep)
	}
}

func TestAPIError(t *testing.T) {
	s := newStub(t)
	c := New(s.srv.URL, "")

	s.reply(422, `{"error":{"code":"invalid","message":"the draft is invalid","issues":[{"path":"links[l].to","message":"unknown target","severity":"error"}]}}`)
	_, err := c.CreateRevision(ctx, "o", api.CreateRevision{Message: "m"})
	var ae *APIError
	if !errors.As(err, &ae) {
		t.Fatalf("err = %T %v", err, err)
	}
	if ae.Status != 422 || ae.Code != "invalid" || ae.Message != "the draft is invalid" || len(ae.Issues) != 1 || ae.Issues[0].Path != "links[l].to" {
		t.Errorf("api error = %+v", ae)
	}
	if got := ae.Error(); got != "the draft is invalid (invalid, HTTP 422)" {
		t.Errorf("Error() = %q", got)
	}
	if IsUnreachable(err) {
		t.Error("an API error is not unreachable")
	}

	s.reply(404, `{"error":{"code":"not_found","message":"no ontology \"x\""}}`)
	_, err = c.GetOntology(ctx, "x")
	if !IsNotFound(err) {
		t.Errorf("IsNotFound(%v) = false", err)
	}

	// A body that is not an ErrorBody still yields an APIError.
	s.reply(502, `<html>bad gateway</html>`)
	_, err = c.Health(ctx)
	if !errors.As(err, &ae) || ae.Status != 502 || ae.Code != "internal" || ae.Message != "<html>bad gateway</html>" {
		t.Errorf("err = %#v", err)
	}
	s.reply(401, ``)
	_, err = c.Health(ctx)
	if !errors.As(err, &ae) || ae.Code != "unauthorized" || ae.Message != "Unauthorized" {
		t.Errorf("err = %#v", err)
	}

	// A 2xx body that is not JSON is an error, but not an API or network one.
	s.reply(200, `not json`)
	_, err = c.Health(ctx)
	if err == nil || errors.As(err, &ae) || IsUnreachable(err) {
		t.Errorf("err = %#v", err)
	}
}

func TestUnreachable(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := l.Addr().String()
	l.Close()
	_, err = New("http://"+addr, "").Health(ctx)
	if !IsUnreachable(err) {
		t.Fatalf("IsUnreachable(%v) = false", err)
	}
	if !strings.Contains(err.Error(), "cannot reach mosaicd at http://"+addr) {
		t.Errorf("message = %q", err)
	}
	var ae *APIError
	if errors.As(err, &ae) {
		t.Error("unreachable is not an API error")
	}

	// A server that does not answer in time is unreachable too.
	block := make(chan struct{})
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-block }))
	defer slow.Close()
	defer close(block)
	_, err = New(slow.URL, "", WithTimeout(50*time.Millisecond)).Health(ctx)
	if !IsUnreachable(err) || !strings.Contains(err.Error(), "timed out") {
		t.Errorf("timeout err = %v", err)
	}
}

func TestCollection(t *testing.T) {
	for in, want := range map[string]string{"component": "components", "components": "components", "interface": "interfaces",
		"links": "links", "schema": "schemas", "flow": "flows", "scenarios": "scenarios"} {
		if got, err := Collection(in); err != nil || got != want {
			t.Errorf("Collection(%q) = %q, %v", in, got, err)
		}
	}
	if _, err := Collection("Component"); err == nil {
		t.Error("kinds are case-sensitive")
	}
}

func TestCommitsAndImpact(t *testing.T) {
	s := newStub(t)
	c := New(s.srv.URL, "")

	s.reply(200, `{"repo":"/r","commits":[{"sha":"abc","subject":"s","date":"2026-01-01T00:00:00Z","files":["a"],"revision":2,"changed":true}]}`)
	list, err := c.ImportCommits(ctx, "o", api.ImportCommits{Repo: "/r", Commits: []api.Commit{{SHA: "abc", Subject: "s", Files: []string{"a"}}}})
	if err != nil {
		t.Fatal(err)
	}
	s.expect("POST", "/v1/ontologies/o/commits", "")
	if !strings.Contains(s.last.Body, `"repo":"/r"`) || !strings.Contains(s.last.Body, `"files":["a"]`) {
		t.Errorf("body = %s", s.last.Body)
	}
	if list.Repo != "/r" || len(list.Commits) != 1 || list.Commits[0].Revision != 2 || !list.Commits[0].Changed {
		t.Errorf("list = %+v", list)
	}

	s.reply(200, `{"repo":"","commits":null}`)
	if list, err = c.ListCommits(ctx, "o"); err != nil || list.Commits == nil {
		t.Fatal(list, err)
	}
	s.expect("GET", "/v1/ontologies/o/commits", "")

	s.reply(200, `{"commit":{"sha":"abcdef1","subject":"s","date":"2026-01-01T00:00:00Z","files":[]},"before":1,"after":2,"changes":[],"impact":{"components":{"added":["x"],"removed":[],"modified":[]},"flows_affected":[]}}`)
	d, err := c.GetCommit(ctx, "o", "abcdef1")
	if err != nil {
		t.Fatal(err)
	}
	s.expect("GET", "/v1/ontologies/o/commits/abcdef1", "")
	if d.Before != 1 || d.After != 2 || d.Impact == nil || len(d.Impact.Components.Added) != 1 {
		t.Errorf("detail = %+v", d)
	}

	s.reply(200, `{"components":{"added":[],"removed":["y"],"modified":[]},"flows_affected":[]}`)
	im, err := c.Impact(ctx, "o", "1", "2")
	if err != nil || len(im.Components.Removed) != 1 {
		t.Fatal(im, err)
	}
	s.expect("GET", "/v1/ontologies/o/impact", "from=1&to=2")

	s.reply(409, `{"error":{"code":"conflict","message":"ambiguous"}}`)
	if _, err := c.GetCommit(ctx, "o", "abcdef0"); err == nil {
		t.Fatal("want conflict")
	} else if ae := (*APIError)(nil); !errors.As(err, &ae) || ae.Status != 409 {
		t.Fatalf("err = %v", err)
	}
}

func TestEvidenceAndTestResults(t *testing.T) {
	s := newStub(t)
	c := New(s.srv.URL, "")

	s.reply(200, `{"revision":2,"built_by":"generated"}`)
	ev, err := c.PutEvidence(ctx, "o", "2", api.Evidence{BuiltBy: "generated"})
	if err != nil || ev.Revision != 2 {
		t.Fatalf("put = %+v, %v", ev, err)
	}
	s.expect("PUT", "/v1/ontologies/o/evidence", "rev=2")

	s.reply(200, `{"revision":3,"blind":{"measured_on_revision":2,"steps_total":1}}`)
	ev, err = c.GetEvidence(ctx, "o", "3")
	if err != nil || ev.Revision != 3 || ev.Blind.MeasuredOnRevision != 2 {
		t.Fatalf("get = %+v, %v", ev, err)
	}
	s.expect("GET", "/v1/ontologies/o/evidence", "rev=3")

	s.reply(200, `{"revision":"1","passed":true,"total":0,"failed":0,"results":[],"ran_at":"2026-11-05T01:02:03Z"}`)
	rep, err := c.TestResults(ctx, "o", "1")
	if err != nil || rep.Revision != "1" || rep.RanAt.IsZero() || rep.Results == nil {
		t.Fatalf("results = %+v, %v", rep, err)
	}
	s.expect("GET", "/v1/ontologies/o/test-results", "rev=1")
}

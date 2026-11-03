package api_test

import (
	"encoding/json"
	"io"
	"log"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/xleelz/mosaic/internal/api"
	"github.com/xleelz/mosaic/internal/compose"
	"github.com/xleelz/mosaic/internal/explore"
)

// localServer serves the shared store with workdir as its repo root.
func localServer(t *testing.T, workdir string) string {
	t.Helper()
	ts := httptest.NewServer(api.New(api.Config{Store: st, Version: "test", Logger: log.New(io.Discard, "", 0), Workdir: workdir}))
	t.Cleanup(ts.Close)
	return ts.URL
}

func getLocal[T any](t *testing.T, base, method, path string, want int) T {
	t.Helper()
	return decode[T](t, callURL(t, base, nil, method, path, nil, want))
}

// TestComposeRunsReadOnly: the compose run store is listed, read as a tree
// with stats, and its run records, requests and artifacts are served
// (§16.6). Ids and keys outside the store are refused.
func TestComposeRunsReadOnly(t *testing.T) {
	dir := t.TempDir()
	base := localServer(t, dir)

	// No store yet: an empty list.
	if l := getLocal[api.ComposeRunList](t, base, "GET", "/v1/compose/runs", 200); len(l.Runs) != 0 {
		t.Fatalf("empty store: %+v", l)
	}

	cs := compose.NewStore(filepath.Join(dir, compose.DefaultRoot))
	at := time.Date(2026, 11, 2, 12, 0, 0, 0, time.UTC)
	done := at.Add(90 * time.Second)
	root := &compose.RunRecord{ID: "sys", Workflow: "system", TreeRoot: "sys", Depth: 1, State: compose.StateDone,
		Template: json.RawMessage(`{"id":"system"}`), Created: at, Updated: done,
		Stages:    map[string]*compose.StageState{"model": {State: compose.StateDone, Started: &at, Finished: &done}},
		Artifacts: map[string]*compose.ArtifactMeta{"contract": {Provenance: "stage:model", Recorded: done}}}
	child := &compose.RunRecord{ID: "sys.zoom.1", Workflow: "component", Parent: "sys", TreeRoot: "sys", Depth: 2,
		State: compose.StateDone, Template: json.RawMessage(`{"id":"component"}`), Created: at, Updated: done,
		Stages: map[string]*compose.StageState{}, Artifacts: map[string]*compose.ArtifactMeta{}}
	for _, r := range []*compose.RunRecord{root, child} {
		if err := cs.Save(r); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := cs.WriteArtifact("sys", "contract", json.RawMessage(`{"interfaces":["get","put"]}`)); err != nil {
		t.Fatal(err)
	}
	if err := cs.AddRequest(&compose.ChangeRequest{ID: "sys.zoom.1.disagree", FromTask: "sys.zoom.1", FromStage: "disagree",
		Target: compose.RequestTarget{Task: "sys", Artifact: "contract"}, Body: json.RawMessage(`{"interface":"put"}`), State: "pending", Recorded: done}); err != nil {
		t.Fatal(err)
	}
	if err := cs.WriteTurnMeta(&compose.TurnMeta{Task: "sys", Stage: "model", Attempts: []compose.SessionStats{{NumTurns: 7, DurationMS: 4000}}}); err != nil {
		t.Fatal(err)
	}
	// A stray file in the artifacts directory is not served.
	if err := os.WriteFile(filepath.Join(cs.RunDir("sys"), "artifacts", "stray.json"), []byte(`{}`), 0o644); err != nil {
		t.Fatal(err)
	}

	l := getLocal[api.ComposeRunList](t, base, "GET", "/v1/compose/runs", 200)
	if len(l.Runs) != 2 || l.Runs[0].ID != "sys" || l.Runs[1].Parent != "sys" {
		t.Fatalf("list: %+v", l)
	}
	tree := getLocal[compose.Tree](t, base, "GET", "/v1/compose/runs/sys.zoom.1/tree", 200)
	if tree.Root == nil || tree.Root.ID != "sys" || len(tree.Root.Children) != 1 || tree.Tasks != 2 || len(tree.Root.Requests) != 1 {
		t.Fatalf("tree: %+v", tree)
	}
	if tree.Stats == nil || tree.Root.Stats == nil || tree.Root.Stats.Agent.NumTurns != 7 {
		t.Fatalf("tree stats: %+v / %+v", tree.Stats, tree.Root.Stats)
	}
	d := getLocal[api.ComposeRunDetail](t, base, "GET", "/v1/compose/runs/sys", 200)
	if d.Run.ID != "sys" || len(d.Requests) != 1 || d.Requests[0].FromTask != "sys.zoom.1" || d.Turns["model"] == nil {
		t.Fatalf("detail: %+v", d)
	}
	a := getLocal[map[string]any](t, base, "GET", "/v1/compose/runs/sys/artifacts/contract", 200)
	if is, _ := a["interfaces"].([]any); len(is) != 2 {
		t.Fatalf("artifact: %v", a)
	}

	errCodeAt := func(path string, want int, code string) {
		t.Helper()
		if e := errCode(t, callURL(t, base, nil, "GET", path, nil, want)); e.Code != code {
			t.Fatalf("%s: %+v", path, e)
		}
	}
	errCodeAt("/v1/compose/runs/nope", 404, "not_found")
	errCodeAt("/v1/compose/runs/sys/artifacts/stray", 404, "not_found")
	errCodeAt("/v1/compose/runs/..hidden", 400, "bad_request")
	// Nothing writes.
	callURL(t, base, nil, "POST", "/v1/compose/runs", nil, 404)
}

// TestReplays: replay files are listed, and one runs against a stored
// ontology under its schedule without being saved (§16.6).
func TestReplays(t *testing.T) {
	dir := t.TempDir()
	base := localServer(t, dir)
	if l := getLocal[api.ReplayList](t, base, "GET", "/v1/replays", 200); len(l.Replays) != 0 {
		t.Fatalf("no dir: %+v", l)
	}
	writeReplays(t, dir)
	putFile(t, "replay-shop", "../model/testdata/refine/parent.yaml")
	l := getLocal[api.ReplayList](t, base, "GET", "/v1/replays", 200)
	if len(l.Replays) != 2 || l.Replays[0].Name != "ask-ok" || l.Replays[0].Scenario != "ask-ok" || len(l.Replays[0].Failed) != 1 {
		t.Fatalf("list: %+v", l)
	}
	if in := l.Replays[0].ScenarioIn; in == nil || !slices.Contains(*in, "replay-shop") {
		t.Fatalf("ask-ok scenario_in: %v", in)
	}
	if in := l.Replays[1].ScenarioIn; in == nil || len(*in) != 0 {
		t.Fatalf("ghost scenario_in: %v", in)
	}

	before := decode[map[string][]any](t, call(t, "GET", "/v1/ontologies/replay-shop/simulations", nil, 200))
	run := getLocal[api.ReplayRun](t, base, "POST", "/v1/ontologies/replay-shop/replays/ask-ok", 200)
	if run.Run.ID != "" || run.Run.Scenario != "ask-ok" || !run.Run.Summary.Passed || len(run.Failures) != 0 || run.Diverged != "" {
		t.Fatalf("replay run: %+v", run)
	}
	after := decode[map[string][]any](t, call(t, "GET", "/v1/ontologies/replay-shop/simulations", nil, 200))
	if len(after["runs"]) != len(before["runs"]) {
		t.Fatalf("a replay run was saved")
	}
	if e := errCode(t, callURL(t, base, nil, "POST", "/v1/ontologies/replay-shop/replays/ghost", nil, 400)); e.Code != "bad_request" {
		t.Fatalf("ghost: %+v", e)
	}
	if e := errCode(t, callURL(t, base, nil, "POST", "/v1/ontologies/replay-shop/replays/missing", nil, 404)); e.Code != "not_found" {
		t.Fatalf("missing: %+v", e)
	}
}

func writeReplays(t *testing.T, dir string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Join(dir, api.ReplayDir), 0o755); err != nil {
		t.Fatal(err)
	}
	rp := &explore.Replay{Version: 1, Scenario: "ask-ok", Decisions: []int{}, Failed: []string{"result.ok"}}
	if err := rp.Write(filepath.Join(dir, api.ReplayDir, "ask-ok.replay.json")); err != nil {
		t.Fatal(err)
	}
	ghost := &explore.Replay{Version: 1, Scenario: "no-such-scenario", Decisions: []int{}}
	if err := ghost.Write(filepath.Join(dir, api.ReplayDir, "ghost.replay.json")); err != nil {
		t.Fatal(err)
	}
}

// TestReplaysForOntology: ?ontology= lists only the replays whose scenario
// the ontology has at ?rev= (§6).
func TestReplaysForOntology(t *testing.T) {
	dir := t.TempDir()
	base := localServer(t, dir)
	writeReplays(t, dir)
	putFile(t, "replay-filter", "../model/testdata/refine/parent.yaml")
	l := getLocal[api.ReplayList](t, base, "GET", "/v1/replays?ontology=replay-filter", 200)
	if l.Ontology != "replay-filter" || l.Revision != "draft" || len(l.Replays) != 1 || l.Replays[0].Name != "ask-ok" || l.Replays[0].ScenarioIn != nil {
		t.Fatalf("filtered: %+v", l)
	}
	// An ontology without the scenario: nothing.
	call(t, "POST", "/v1/ontologies", map[string]string{"id": "replay-empty", "name": "empty"}, 201)
	if l := getLocal[api.ReplayList](t, base, "GET", "/v1/replays?ontology=replay-empty", 200); len(l.Replays) != 0 {
		t.Fatalf("other ontology: %+v", l)
	}
	if e := errCode(t, callURL(t, base, nil, "GET", "/v1/replays?ontology=no-such-ontology", nil, 404)); e.Code != "not_found" {
		t.Fatalf("unknown ontology: %+v", e)
	}
	if e := errCode(t, callURL(t, base, nil, "GET", "/v1/replays?ontology=replay-filter&rev=bogus", nil, 400)); e.Code != "bad_request" {
		t.Fatalf("bad rev: %+v", e)
	}
}

// TestDeleteReplay: DELETE /v1/replays/{name} is local-only like
// /system/update: loopback, the token, an allowed origin, a clean name.
func TestDeleteReplay(t *testing.T) {
	dir := t.TempDir()
	writeReplays(t, dir)
	h := api.New(api.Config{Store: st, Version: "test", Token: "s3cret", Logger: log.New(io.Discard, "", 0), Workdir: dir})
	do := func(path, remote string, hdr map[string]string) *httptest.ResponseRecorder {
		req := httptest.NewRequest("DELETE", path, nil)
		req.RemoteAddr = remote
		for k, v := range hdr {
			req.Header.Set(k, v)
		}
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		return rec
	}
	auth := map[string]string{"Authorization": "Bearer s3cret"}
	file := filepath.Join(dir, api.ReplayDir, "ghost.replay.json")
	present := func() bool { _, err := os.Stat(file); return err == nil }

	if rec := do("/v1/replays/ghost", "127.0.0.1:5000", nil); rec.Code != 401 || !present() {
		t.Fatalf("without token: %d %s", rec.Code, rec.Body)
	}
	if rec := do("/v1/replays/ghost", "192.0.2.7:4000", auth); rec.Code != 403 || !present() {
		t.Fatalf("not loopback: %d %s", rec.Code, rec.Body)
	}
	if rec := do("/v1/replays/ghost", "127.0.0.1:5000", map[string]string{"Authorization": "Bearer s3cret", "Origin": "http://evil.example"}); rec.Code != 403 || !present() {
		t.Fatalf("foreign origin: %d %s", rec.Code, rec.Body)
	}
	// The mux redirects a dot-dot path to its clean form; nothing is removed.
	if rec := do("/v1/replays/..", "127.0.0.1:5000", auth); rec.Code/100 == 2 || !present() {
		t.Fatalf("dot-dot: %d %s", rec.Code, rec.Body)
	}
	for _, bad := range []string{".hidden", "a..b", "-x"} {
		if rec := do("/v1/replays/"+bad, "127.0.0.1:5000", auth); rec.Code != 400 {
			t.Fatalf("name %q: %d %s", bad, rec.Code, rec.Body)
		}
	}
	if rec := do("/v1/replays/..%2Fask-ok", "127.0.0.1:5000", auth); rec.Code != 400 {
		t.Fatalf("escaped path: %d %s", rec.Code, rec.Body)
	}
	if rec := do("/v1/replays/ghost", "[::1]:5000", map[string]string{"Authorization": "Bearer s3cret", "Origin": "http://localhost:3000"}); rec.Code != 204 || present() {
		t.Fatalf("delete: %d %s", rec.Code, rec.Body)
	}
	if rec := do("/v1/replays/ghost", "127.0.0.1:5000", auth); rec.Code != 404 {
		t.Fatalf("delete again: %d %s", rec.Code, rec.Body)
	}
	if _, err := os.Stat(filepath.Join(dir, api.ReplayDir, "ask-ok.replay.json")); err != nil {
		t.Fatalf("the other replay is gone: %v", err)
	}
}

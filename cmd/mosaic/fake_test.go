package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"sort"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
	"github.com/xleelz/mosaic/pkg/api"
)

// fakeServer implements enough of mosaicd's API (docs/DESIGN.md §6) in
// memory to drive every CLI command. Validation, plans, graphs and
// simulations use the real pure packages, so responses have real shapes.
type fakeServer struct {
	t     *testing.T
	srv   *httptest.Server
	token string

	mu      sync.Mutex
	onts    map[string]*fakeOnt
	runs    map[string]*api.SimulationRun
	runIDs  []string
	log     []string // "METHOD /path?query"
	lastSim *api.SimulationRequest
	lastRaw string // last request body
	behind  int    // commits the fake checkout is behind its upstream
}

type ekey struct{ kind, id string }

type fakeOnt struct {
	sum      api.OntologySummary
	draft    map[ekey]json.RawMessage
	revs     []fakeRev
	repo     string
	commits  []api.Commit // import order
	evidence map[int]api.Evidence
}

type fakeRev struct {
	rev  api.Revision
	ents map[ekey]json.RawMessage
}

var fakeNow = time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)

func newFake(t *testing.T) *fakeServer {
	f := &fakeServer{t: t, onts: map[string]*fakeOnt{}, runs: map[string]*api.SimulationRun{}, behind: 2}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, api.Health{Status: "ok", Version: "fake", Dolt: "ok"})
	})
	mux.HandleFunc("GET /v1/ontologies", f.listOntologies)
	mux.HandleFunc("POST /v1/ontologies", f.createOntology)
	mux.HandleFunc("GET /v1/ontologies/{id}", f.withOnt(f.getOntology))
	mux.HandleFunc("PATCH /v1/ontologies/{id}", f.withOnt(f.updateOntology))
	mux.HandleFunc("DELETE /v1/ontologies/{id}", f.withOnt(f.deleteOntology))
	mux.HandleFunc("GET /v1/ontologies/{id}/document", f.withOnt(f.getDocument))
	mux.HandleFunc("PUT /v1/ontologies/{id}/document", f.withOnt(f.putDocument))
	mux.HandleFunc("GET /v1/ontologies/{id}/{kind}", f.withOnt(f.listEntities))
	mux.HandleFunc("POST /v1/ontologies/{id}/{kind}", f.withOnt(f.createEntity))
	mux.HandleFunc("PUT /v1/ontologies/{id}/{kind}", f.withOnt(f.upsertEntities))
	mux.HandleFunc("GET /v1/ontologies/{id}/{kind}/{eid}", f.withOnt(f.getEntity))
	mux.HandleFunc("PUT /v1/ontologies/{id}/{kind}/{eid}", f.withOnt(f.putEntity))
	mux.HandleFunc("PATCH /v1/ontologies/{id}/{kind}/{eid}", f.withOnt(f.patchEntity))
	mux.HandleFunc("DELETE /v1/ontologies/{id}/{kind}/{eid}", f.withOnt(f.deleteEntity))
	mux.HandleFunc("GET /v1/ontologies/{id}/revisions", f.withOnt(f.listRevisions))
	mux.HandleFunc("POST /v1/ontologies/{id}/revisions", f.withOnt(f.createRevision))
	mux.HandleFunc("GET /v1/ontologies/{id}/revisions/{n}", f.withOnt(f.getRevision))
	mux.HandleFunc("GET /v1/ontologies/{id}/diff", f.withOnt(f.diff))
	mux.HandleFunc("GET /v1/ontologies/{id}/commits", f.withOnt(f.listCommits))
	mux.HandleFunc("POST /v1/ontologies/{id}/commits", f.withOnt(f.importCommits))
	mux.HandleFunc("GET /v1/ontologies/{id}/commits/{sha}", f.withOnt(f.getCommit))
	mux.HandleFunc("POST /v1/ontologies/{id}/validate", f.withOnt(f.validate))
	mux.HandleFunc("GET /v1/ontologies/{id}/graph", f.withOnt(f.graph))
	mux.HandleFunc("GET /v1/ontologies/{id}/flows/{flow}/plan", f.withOnt(f.plan))
	mux.HandleFunc("GET /v1/ontologies/{id}/simulations", f.withOnt(f.listRuns))
	mux.HandleFunc("POST /v1/ontologies/{id}/simulations", f.withOnt(f.runSimulation))
	mux.HandleFunc("POST /v1/ontologies/{id}/test", f.withOnt(f.test))
	mux.HandleFunc("GET /v1/ontologies/{id}/evidence", f.withOnt(f.getEvidence))
	mux.HandleFunc("PUT /v1/ontologies/{id}/evidence", f.withOnt(f.putEvidence))
	mux.HandleFunc("GET /v1/simulations/{run}", f.getRun)
	mux.HandleFunc("GET /v1/ontologies/{id}/source", f.withOnt(f.source))
	mux.HandleFunc("GET /v1/system/version", f.systemVersion)
	mux.HandleFunc("POST /v1/system/update", f.systemUpdate)
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeErr(w, 404, "not_found", "no route "+r.Method+" "+r.URL.Path, nil)
	})
	f.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		r.Body = io.NopCloser(bytes.NewReader(body))
		f.mu.Lock()
		defer f.mu.Unlock()
		entry := r.Method + " " + r.URL.Path
		if r.URL.RawQuery != "" {
			entry += "?" + r.URL.RawQuery
		}
		f.log = append(f.log, entry)
		f.lastRaw = string(body)
		if f.token != "" && r.Header.Get("Authorization") != "Bearer "+f.token {
			writeErr(w, 401, "unauthorized", "a valid bearer token is required", nil)
			return
		}
		mux.ServeHTTP(w, r)
	}))
	t.Cleanup(f.srv.Close)
	return f
}

// URL is the server's base URL.
func (f *fakeServer) URL() string { return f.srv.URL }

// lastRequest returns the most recent "METHOD /path?query".
func (f *fakeServer) lastRequest() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.log) == 0 {
		return ""
	}
	return f.log[len(f.log)-1]
}

func (f *fakeServer) setToken(tok string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.token = tok
}

func (f *fakeServer) raw() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.lastRaw
}

func (f *fakeServer) sim() *api.SimulationRequest {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.lastSim
}

func (f *fakeServer) requests() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.log...)
}

// load creates an ontology from a document file and records revision 1.
func (f *fakeServer) load(id, path string) {
	f.t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		f.t.Fatal(err)
	}
	doc, err := model.ParseDocument(data)
	if err != nil {
		f.t.Fatal(err)
	}
	ents, err := doc.Entities()
	if err != nil {
		f.t.Fatal(err)
	}
	o := &fakeOnt{sum: api.OntologySummary{ID: id, Name: doc.Name, Description: doc.Description, CreatedAt: fakeNow, UpdatedAt: fakeNow},
		draft: map[ekey]json.RawMessage{}}
	for _, e := range ents {
		o.draft[ekey{e.Kind, e.ID}] = e.Spec
	}
	o.commit("initial", "test")
	f.mu.Lock()
	f.onts[id] = o
	f.mu.Unlock()
}

func (o *fakeOnt) commit(msg, author string) api.Revision {
	n := len(o.revs) + 1
	rev := api.Revision{Number: n, Hash: fmt.Sprintf("hash%d", n), Message: msg, Author: author, CreatedAt: fakeNow.Add(time.Duration(n) * time.Minute)}
	o.revs = append(o.revs, fakeRev{rev: rev, ents: clone(o.draft)})
	o.sum.LatestRevision, o.sum.RevisionCount = n, n
	return rev
}

func clone(m map[ekey]json.RawMessage) map[ekey]json.RawMessage {
	out := make(map[ekey]json.RawMessage, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

func sameEntities(a, b map[ekey]json.RawMessage) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if w, ok := b[k]; !ok || !jsonSame(v, w) {
			return false
		}
	}
	return true
}

func jsonSame(a, b []byte) bool {
	var x, y any
	_ = json.Unmarshal(a, &x)
	_ = json.Unmarshal(b, &y)
	return reflect.DeepEqual(x, y)
}

// Responses.

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, status int, code, msg string, issues []model.Issue) {
	writeJSON(w, status, api.ErrorBody{Error: api.ErrorDetail{Code: code, Message: msg, Issues: issues}})
}

type ontHandler func(w http.ResponseWriter, r *http.Request, o *fakeOnt)

func (f *fakeServer) withOnt(h ontHandler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		o, ok := f.onts[r.PathValue("id")]
		if !ok {
			writeErr(w, 404, "not_found", fmt.Sprintf("ontology %q not found", r.PathValue("id")), nil)
			return
		}
		h(w, r, o)
	}
}

// at resolves ?rev= to a set of entities and the revision label.
func (o *fakeOnt) at(rev string) (map[ekey]json.RawMessage, string, error) {
	switch rev {
	case "", api.RevDraft:
		return o.draft, api.RevDraft, nil
	case api.RevLatest:
		if len(o.revs) == 0 {
			return nil, "", errors.New("the ontology has no revisions yet")
		}
		r := o.revs[len(o.revs)-1]
		return r.ents, strconv.Itoa(r.rev.Number), nil
	}
	n, err := strconv.Atoi(rev)
	if err != nil || n < 1 {
		return nil, "", fmt.Errorf("bad revision %q", rev)
	}
	if n > len(o.revs) {
		return nil, "", fmt.Errorf("revision %d not found", n)
	}
	return o.revs[n-1].ents, rev, nil
}

func (f *fakeServer) entsAt(w http.ResponseWriter, r *http.Request, o *fakeOnt, rev string) (map[ekey]json.RawMessage, string, bool) {
	ents, label, err := o.at(rev)
	if err != nil {
		writeErr(w, 404, "not_found", err.Error(), nil)
		return nil, "", false
	}
	return ents, label, true
}

func document(ents map[ekey]json.RawMessage) (*model.Document, []model.Issue) {
	list := make([]model.Entity, 0, len(ents))
	for k, v := range ents {
		list = append(list, model.Entity{Kind: k.kind, ID: k.id, Spec: v})
	}
	return model.FromEntities(list)
}

func validateEnts(ents map[ekey]json.RawMessage) []model.Issue {
	doc, issues := document(ents)
	issues = append(issues, model.Validate(doc)...)
	if issues == nil {
		issues = []model.Issue{}
	}
	return issues
}

func counts(ents map[ekey]json.RawMessage) map[string]int {
	c := map[string]int{}
	for _, k := range model.Kinds {
		c[k] = 0
	}
	for k := range ents {
		c[k.kind]++
	}
	return c
}

func (o *fakeOnt) detail() api.OntologyDetail {
	dirty := len(o.revs) == 0 && len(o.draft) > 0
	if len(o.revs) > 0 {
		dirty = !sameEntities(o.draft, o.revs[len(o.revs)-1].ents)
	}
	return api.OntologyDetail{OntologySummary: o.sum, Counts: counts(o.draft), DraftDirty: dirty}
}

// Ontologies.

func (f *fakeServer) listOntologies(w http.ResponseWriter, r *http.Request) {
	out := api.OntologyList{Ontologies: []api.OntologySummary{}}
	ids := make([]string, 0, len(f.onts))
	for id := range f.onts {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		out.Ontologies = append(out.Ontologies, f.onts[id].sum)
	}
	writeJSON(w, 200, out)
}

func (f *fakeServer) createOntology(w http.ResponseWriter, r *http.Request) {
	var req api.CreateOntology
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	if !model.ValidID(req.ID) {
		writeErr(w, 400, "bad_request", fmt.Sprintf("invalid ontology id %q", req.ID), nil)
		return
	}
	if _, dup := f.onts[req.ID]; dup {
		writeErr(w, 409, "conflict", fmt.Sprintf("ontology %q already exists", req.ID), nil)
		return
	}
	o := &fakeOnt{sum: api.OntologySummary{ID: req.ID, Name: req.Name, Description: req.Description, CreatedAt: fakeNow, UpdatedAt: fakeNow},
		draft: map[ekey]json.RawMessage{}}
	f.onts[req.ID] = o
	writeJSON(w, 201, o.detail())
}

func (f *fakeServer) getOntology(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	writeJSON(w, 200, o.detail())
}

func (f *fakeServer) updateOntology(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	var req api.UpdateOntology
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	if req.Name != nil {
		o.sum.Name = *req.Name
	}
	if req.Description != nil {
		o.sum.Description = *req.Description
	}
	writeJSON(w, 200, o.detail())
}

func (f *fakeServer) deleteOntology(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	delete(f.onts, o.sum.ID)
	w.WriteHeader(204)
}

// Documents.

func (f *fakeServer) getDocument(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	ents, _, ok := f.entsAt(w, r, o, r.URL.Query().Get("rev"))
	if !ok {
		return
	}
	doc, _ := document(ents)
	doc.ID, doc.Name, doc.Description = o.sum.ID, o.sum.Name, o.sum.Description
	writeJSON(w, 200, doc)
}

func (f *fakeServer) putDocument(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	body, _ := io.ReadAll(r.Body)
	doc, err := model.ParseDocument(body)
	if err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	ents, err := doc.Entities()
	if err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	o.draft = map[ekey]json.RawMessage{}
	for _, e := range ents {
		o.draft[ekey{e.Kind, e.ID}] = e.Spec
	}
	issues := validateEnts(o.draft)
	writeJSON(w, 200, api.PutDocumentResult{Counts: counts(o.draft), Valid: !model.HasErrors(issues), Issues: issues})
}

// Entities. Only plural kinds are routes, as in DESIGN §6.

func pathKind(w http.ResponseWriter, r *http.Request) (string, bool) {
	name := r.PathValue("kind")
	k, ok := model.KindOf(name)
	if !ok || model.Plural(k) != name {
		writeErr(w, 404, "not_found", fmt.Sprintf("unknown collection %q", name), nil)
		return "", false
	}
	return k, true
}

func (f *fakeServer) listEntities(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	kind, ok := pathKind(w, r)
	if !ok {
		return
	}
	ents, _, ok := f.entsAt(w, r, o, r.URL.Query().Get("rev"))
	if !ok {
		return
	}
	var ids []string
	for k := range ents {
		if k.kind == kind {
			ids = append(ids, k.id)
		}
	}
	sort.Strings(ids)
	out := api.Items{Items: []json.RawMessage{}}
	for _, id := range ids {
		out.Items = append(out.Items, ents[ekey{kind, id}])
	}
	writeJSON(w, 200, out)
}

func (f *fakeServer) getEntity(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	kind, ok := pathKind(w, r)
	if !ok {
		return
	}
	ents, _, ok := f.entsAt(w, r, o, r.URL.Query().Get("rev"))
	if !ok {
		return
	}
	spec, ok := ents[ekey{kind, r.PathValue("eid")}]
	if !ok {
		writeErr(w, 404, "not_found", fmt.Sprintf("%s %q not found", kind, r.PathValue("eid")), nil)
		return
	}
	writeJSON(w, 200, spec)
}

// store decodes and stores one entity spec; want is the id the path names.
func (o *fakeOnt) store(kind, want string, spec []byte) (string, error) {
	v, id, err := model.DecodeEntity(kind, spec)
	if err != nil {
		return "", err
	}
	if want != "" && id != want {
		return "", fmt.Errorf("the spec's id %q does not match the path's %q", id, want)
	}
	if id == "" {
		return "", errors.New("missing id")
	}
	b, _ := json.Marshal(v)
	o.draft[ekey{kind, id}] = b
	return id, nil
}

func (f *fakeServer) upserted(w http.ResponseWriter, status int, o *fakeOnt, kind string, ids []string) {
	writeJSON(w, status, api.UpsertResult{Kind: kind, IDs: ids, Issues: validateEnts(o.draft)})
}

func (f *fakeServer) putEntity(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	kind, ok := pathKind(w, r)
	if !ok {
		return
	}
	body, _ := io.ReadAll(r.Body)
	id, err := o.store(kind, r.PathValue("eid"), body)
	if err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	f.upserted(w, 200, o, kind, []string{id})
}

func (f *fakeServer) createEntity(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	kind, ok := pathKind(w, r)
	if !ok {
		return
	}
	body, _ := io.ReadAll(r.Body)
	_, id, err := model.DecodeEntity(kind, body)
	if err == nil {
		if _, dup := o.draft[ekey{kind, id}]; dup {
			writeErr(w, 409, "conflict", fmt.Sprintf("%s %q already exists", kind, id), nil)
			return
		}
		_, err = o.store(kind, "", body)
	}
	if err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	f.upserted(w, 201, o, kind, []string{id})
}

func (f *fakeServer) upsertEntities(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	kind, ok := pathKind(w, r)
	if !ok {
		return
	}
	var items api.Items
	if err := json.NewDecoder(r.Body).Decode(&items); err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	ids := []string{}
	for i, it := range items.Items {
		id, err := o.store(kind, "", it)
		if err != nil {
			writeErr(w, 400, "bad_request", fmt.Sprintf("items[%d]: %v", i, err), nil)
			return
		}
		ids = append(ids, id)
	}
	f.upserted(w, 200, o, kind, ids)
}

func (f *fakeServer) patchEntity(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	kind, ok := pathKind(w, r)
	if !ok {
		return
	}
	k := ekey{kind, r.PathValue("eid")}
	cur, ok := o.draft[k]
	if !ok {
		writeErr(w, 404, "not_found", fmt.Sprintf("%s %q not found", kind, k.id), nil)
		return
	}
	var base, patch any
	_ = json.Unmarshal(cur, &base)
	if err := json.NewDecoder(r.Body).Decode(&patch); err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	merged, _ := json.Marshal(mergePatch(base, patch))
	if _, err := o.store(kind, k.id, merged); err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	f.upserted(w, 200, o, kind, []string{k.id})
}

// mergePatch applies an RFC 7396 merge patch.
func mergePatch(base, patch any) any {
	pm, ok := patch.(map[string]any)
	if !ok {
		return patch
	}
	bm, ok := base.(map[string]any)
	if !ok {
		bm = map[string]any{}
	}
	for k, v := range pm {
		if v == nil {
			delete(bm, k)
		} else {
			bm[k] = mergePatch(bm[k], v)
		}
	}
	return bm
}

func (f *fakeServer) deleteEntity(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	kind, ok := pathKind(w, r)
	if !ok {
		return
	}
	k := ekey{kind, r.PathValue("eid")}
	if _, ok := o.draft[k]; !ok {
		writeErr(w, 404, "not_found", fmt.Sprintf("%s %q not found", kind, k.id), nil)
		return
	}
	delete(o.draft, k)
	w.WriteHeader(204)
}

// Revisions.

func (f *fakeServer) listRevisions(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	out := api.RevisionList{Revisions: []api.Revision{}}
	for _, rv := range o.revs {
		out.Revisions = append(out.Revisions, rv.rev)
	}
	writeJSON(w, 200, out)
}

func (f *fakeServer) getRevision(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	n, err := strconv.Atoi(r.PathValue("n"))
	if err != nil || n < 1 || n > len(o.revs) {
		writeErr(w, 404, "not_found", fmt.Sprintf("revision %s not found", r.PathValue("n")), nil)
		return
	}
	writeJSON(w, 200, o.revs[n-1].rev)
}

func (f *fakeServer) createRevision(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	var req api.CreateRevision
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Message == "" {
		writeErr(w, 400, "bad_request", "a message is required", nil)
		return
	}
	issues := validateEnts(o.draft)
	if model.HasErrors(issues) {
		writeErr(w, 422, "invalid", "the draft does not validate", issues)
		return
	}
	if len(o.revs) > 0 && !req.AllowEmpty && sameEntities(o.draft, o.revs[len(o.revs)-1].ents) {
		writeErr(w, 409, "conflict", "the draft is unchanged since revision "+strconv.Itoa(len(o.revs)), nil)
		return
	}
	author := req.Author
	if author == "" {
		author = "Mosaic <mosaic@localhost>"
	}
	rev := o.commit(req.Message, author)
	if req.Source != nil {
		o.revs[len(o.revs)-1].rev.Source = req.Source
		rev.Source = req.Source
	}
	writeJSON(w, 201, rev)
}

func (f *fakeServer) diff(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	q := r.URL.Query()
	from, to := q.Get("from"), q.Get("to")
	if from == "" {
		from = api.RevLatest
	}
	if to == "" {
		to = api.RevDraft
	}
	a, fromLabel, ok := f.entsAt(w, r, o, from)
	if !ok {
		return
	}
	b, toLabel, ok := f.entsAt(w, r, o, to)
	if !ok {
		return
	}
	out := api.Diff{From: fromLabel, To: toLabel, Changes: []api.Change{}}
	keys := map[ekey]bool{}
	for k := range a {
		keys[k] = true
	}
	for k := range b {
		keys[k] = true
	}
	var sorted []ekey
	for k := range keys {
		sorted = append(sorted, k)
	}
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].kind != sorted[j].kind {
			return sorted[i].kind < sorted[j].kind
		}
		return sorted[i].id < sorted[j].id
	})
	for _, k := range sorted {
		before, inA := a[k]
		after, inB := b[k]
		switch {
		case inA && !inB:
			out.Changes = append(out.Changes, api.Change{Kind: k.kind, ID: k.id, Change: "removed", Before: before})
		case !inA && inB:
			out.Changes = append(out.Changes, api.Change{Kind: k.kind, ID: k.id, Change: "added", After: after})
		case !jsonSame(before, after):
			out.Changes = append(out.Changes, api.Change{Kind: k.kind, ID: k.id, Change: "modified", Before: before, After: after})
		}
	}
	writeJSON(w, 200, out)
}

// Analysis.

func (f *fakeServer) validate(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	ents, label, ok := f.entsAt(w, r, o, r.URL.Query().Get("rev"))
	if !ok {
		return
	}
	issues := validateEnts(ents)
	writeJSON(w, 200, api.Validation{Revision: label, Valid: !model.HasErrors(issues), Issues: issues})
}

func (f *fakeServer) graph(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	ents, _, ok := f.entsAt(w, r, o, r.URL.Query().Get("rev"))
	if !ok {
		return
	}
	doc, _ := document(ents)
	writeJSON(w, 200, model.NewIndex(doc).Graph())
}

func (f *fakeServer) plan(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	ents, _, ok := f.entsAt(w, r, o, r.URL.Query().Get("rev"))
	if !ok {
		return
	}
	doc, _ := document(ents)
	p, err := model.NewIndex(doc).Plan(r.PathValue("flow"))
	if err != nil {
		writeErr(w, 404, "not_found", err.Error(), nil)
		return
	}
	writeJSON(w, 200, p)
}

// Simulations.

func (f *fakeServer) runSimulation(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	var req api.SimulationRequest
	dec := json.NewDecoder(r.Body)
	dec.UseNumber()
	if err := dec.Decode(&req); err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	f.lastSim = &req
	ents, label, ok := f.entsAt(w, r, o, req.Rev)
	if !ok {
		return
	}
	doc, _ := document(ents)
	res, err := sim.Run(doc, req.Request)
	if err != nil {
		var re *sim.RequestError
		if errors.As(err, &re) {
			writeErr(w, 400, "bad_request", re.Msg, nil)
		} else {
			writeErr(w, 500, "internal", err.Error(), nil)
		}
		return
	}
	run := &api.SimulationRun{Ontology: o.sum.ID, Revision: label, Flow: res.Request.Flow, Scenario: res.Request.Scenario,
		CreatedAt: fakeNow, Request: res.Request, Summary: res.Summary, Trace: res.Trace}
	if req.Save == nil || *req.Save {
		run.ID = fmt.Sprintf("run_%d", len(f.runIDs)+1)
		f.runs[run.ID] = run
		f.runIDs = append(f.runIDs, run.ID)
	}
	writeJSON(w, 201, run)
}

func (f *fakeServer) listRuns(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	limit := 50
	if s := r.URL.Query().Get("limit"); s != "" {
		limit, _ = strconv.Atoi(s)
	}
	out := api.RunList{Runs: []api.SimulationRun{}}
	for i := len(f.runIDs) - 1; i >= 0 && len(out.Runs) < limit; i-- {
		run := *f.runs[f.runIDs[i]]
		if run.Ontology != o.sum.ID {
			continue
		}
		run.Trace = nil
		out.Runs = append(out.Runs, run)
	}
	writeJSON(w, 200, out)
}

func (f *fakeServer) getRun(w http.ResponseWriter, r *http.Request) {
	run, ok := f.runs[r.PathValue("run")]
	if !ok {
		writeErr(w, 404, "not_found", fmt.Sprintf("run %q not found", r.PathValue("run")), nil)
		return
	}
	writeJSON(w, 200, run)
}

func (f *fakeServer) test(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	ents, label, ok := f.entsAt(w, r, o, r.URL.Query().Get("rev"))
	if !ok {
		return
	}
	doc, _ := document(ents)
	rep := api.TestReport{Revision: label, Passed: true, Results: []api.TestResult{}}
	for _, sc := range doc.Scenarios {
		res := api.TestResult{Scenario: sc.ID, Name: sc.Name}
		out, err := sim.Run(doc, sim.Request{Scenario: sc.ID})
		if err != nil {
			res.Error = err.Error()
			res.Assertions = []sim.Assertion{}
		} else {
			res.Passed, res.Status, res.Assertions, res.Abort = out.Summary.Passed, out.Summary.Status, out.Summary.Assertions, out.Summary.Abort
		}
		rep.Total++
		if !res.Passed {
			rep.Failed++
			rep.Passed = false
		}
		rep.Results = append(rep.Results, res)
	}
	writeJSON(w, 200, rep)
}

const (
	fakeHead   = "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	fakeLatest = "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
)

func (f *fakeServer) systemVersion(w http.ResponseWriter, r *http.Request) {
	checked := fakeNow
	v := api.SystemVersion{Version: "fake", Commit: fakeHead, Branch: "main", Upstream: "origin/main", SourceDir: "/src/mosaic",
		Update: api.UpdateStatus{Available: f.behind > 0, Behind: f.behind, LatestCommit: fakeLatest, LatestSubject: "web: a new page", CheckedAt: &checked}}
	if f.behind == 0 {
		v.Commit = fakeLatest
		v.Update.Reason = "up to date with origin/main"
	}
	writeJSON(w, 200, v)
}

func (f *fakeServer) source(w http.ResponseWriter, r *http.Request, _ *fakeOnt) {
	q := r.URL.Query()
	if q.Get("path") != "main.go" {
		writeErr(w, 404, "not_found", "file not found at that commit", nil)
		return
	}
	repo, sha := q.Get("repo"), q.Get("sha")
	if repo == "" {
		repo = "acme/shop"
	}
	if sha == "" {
		sha = fakeHead
	}
	writeJSON(w, 200, api.SourceFile{Repo: repo, SHA: sha, Path: "main.go", Content: "package main\n", LanguageHint: "go", Size: 13,
		URL: "https://github.com/" + repo + "/blob/" + sha + "/main.go"})
}

func (f *fakeServer) systemUpdate(w http.ResponseWriter, r *http.Request) {
	if f.behind == 0 {
		writeErr(w, 409, "conflict", "up to date with origin/main", nil)
		return
	}
	f.behind = 0
	writeJSON(w, 200, api.SystemUpdate{From: fakeHead, UpdatedTo: fakeLatest, Restarting: true})
}

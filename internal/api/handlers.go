package api

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
	"github.com/xleelz/mosaic/internal/store"
	wire "github.com/xleelz/mosaic/pkg/api"
)

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	h := wire.Health{Status: "ok", Version: s.cfg.Version}
	if s.cfg.DoltVersion != nil {
		v, err := s.cfg.DoltVersion(r.Context())
		if err != nil {
			writeError(w, http.StatusServiceUnavailable, "internal", "dolt is unreachable: "+err.Error(), nil)
			return
		}
		h.Dolt = v
	}
	writeJSON(w, http.StatusOK, h)
}

// ---- ontologies ----

func (s *Server) listOntologies(w http.ResponseWriter, r *http.Request) {
	list, err := s.store.ListOntologies(r.Context())
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, wire.OntologyList{Ontologies: list})
}

func (s *Server) createOntology(w http.ResponseWriter, r *http.Request) {
	var in wire.CreateOntology
	if err := decodeBody(w, r, &in); err != nil {
		s.fail(w, r, err)
		return
	}
	d, err := s.store.CreateOntology(r.Context(), in)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusCreated, d)
}

func (s *Server) getOntology(w http.ResponseWriter, r *http.Request) {
	d, err := s.store.GetOntology(r.Context(), r.PathValue("id"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, d)
}

func (s *Server) updateOntology(w http.ResponseWriter, r *http.Request) {
	var in wire.UpdateOntology
	if err := decodeBody(w, r, &in); err != nil {
		s.fail(w, r, err)
		return
	}
	d, err := s.store.UpdateOntology(r.Context(), r.PathValue("id"), in)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, d)
}

func (s *Server) deleteOntology(w http.ResponseWriter, r *http.Request) {
	if err := s.store.DeleteOntology(r.Context(), r.PathValue("id")); err != nil {
		s.fail(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- documents ----

// rev resolves ?rev= for the ontology in the path.
func (s *Server) rev(r *http.Request) (string, store.Rev, error) {
	id := r.PathValue("id")
	rv, err := s.store.ResolveRev(r.Context(), id, r.URL.Query().Get("rev"))
	return id, rv, err
}

// document loads the document at ?rev=.
func (s *Server) document(r *http.Request) (*model.Document, store.Rev, []model.Issue, error) {
	id, rv, err := s.rev(r)
	if err != nil {
		return nil, rv, nil, err
	}
	doc, issues, err := s.store.Document(r.Context(), id, rv)
	return doc, rv, issues, err
}

func (s *Server) getDocument(w http.ResponseWriter, r *http.Request) {
	doc, _, _, err := s.document(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, doc)
}

func (s *Server) putDocument(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := s.store.Exists(r.Context(), id); err != nil {
		s.fail(w, r, err)
		return
	}
	b, err := readBody(w, r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	doc, err := model.ParseDocument(b)
	if err != nil {
		s.fail(w, r, badRequest("%v", err))
		return
	}
	counts, err := s.store.PutDocument(r.Context(), id, doc)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	issues, err := s.store.Validate(r.Context(), id, store.Draft)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, wire.PutDocumentResult{Counts: counts, Valid: !model.HasErrors(issues), Issues: issues})
}

func (s *Server) validate(w http.ResponseWriter, r *http.Request) {
	id, rv, err := s.rev(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	issues, err := s.store.Validate(r.Context(), id, rv)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, wire.Validation{Revision: rv.String(), Valid: !model.HasErrors(issues), Issues: issues})
}

func (s *Server) graph(w http.ResponseWriter, r *http.Request) {
	doc, _, _, err := s.document(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, model.NewIndex(doc).Graph())
}

func (s *Server) plan(w http.ResponseWriter, r *http.Request) {
	doc, rv, _, err := s.document(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	x := model.NewIndex(doc)
	flow := r.PathValue("flow")
	if _, ok := x.Flows[flow]; !ok {
		s.fail(w, r, notFound("flow %q not found at %s", flow, rv))
		return
	}
	p, err := x.Plan(flow)
	if err != nil {
		s.fail(w, r, &store.Error{Code: store.CodeInvalid, Message: err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, p)
}

// ---- revisions and diffs ----

func (s *Server) listRevisions(w http.ResponseWriter, r *http.Request) {
	revs, err := s.store.Revisions(r.Context(), r.PathValue("id"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, wire.RevisionList{Revisions: revs})
}

func (s *Server) createRevision(w http.ResponseWriter, r *http.Request) {
	var in wire.CreateRevision
	if err := decodeBody(w, r, &in); err != nil {
		s.fail(w, r, err)
		return
	}
	rev, err := s.store.CreateRevision(r.Context(), r.PathValue("id"), in)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusCreated, rev)
}

func (s *Server) getRevision(w http.ResponseWriter, r *http.Request) {
	rev, err := s.store.Revision(r.Context(), r.PathValue("id"), r.PathValue("n"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, rev)
}

func (s *Server) diff(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	d, err := s.store.Diff(r.Context(), r.PathValue("id"), q.Get("from"), q.Get("to"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, d)
}

func (s *Server) impact(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	im, err := s.store.Impact(r.Context(), r.PathValue("id"), q.Get("from"), q.Get("to"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, im)
}

// ---- commits ----

func (s *Server) listCommits(w http.ResponseWriter, r *http.Request) {
	list, err := s.store.ListCommits(r.Context(), r.PathValue("id"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, list)
}

func (s *Server) importCommits(w http.ResponseWriter, r *http.Request) {
	var in wire.ImportCommits
	if err := decodeBody(w, r, &in); err != nil {
		s.fail(w, r, err)
		return
	}
	list, err := s.store.ImportCommits(r.Context(), r.PathValue("id"), in)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, list)
}

func (s *Server) getCommit(w http.ResponseWriter, r *http.Request) {
	d, err := s.store.CommitDetail(r.Context(), r.PathValue("id"), r.PathValue("sha"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, d)
}

// ---- entities ----

func kindOf(r *http.Request) (string, error) {
	k, ok := model.KindOf(r.PathValue("kind"))
	if !ok {
		return "", notFound("unknown kind %q: use components, interfaces, links, schemas, flows, scenarios, configs or fixtures", r.PathValue("kind"))
	}
	return k, nil
}

func (s *Server) listEntities(w http.ResponseWriter, r *http.Request) {
	kind, err := kindOf(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	id, rv, err := s.rev(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	es, err := s.store.Entities(r.Context(), id, rv, kind)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	items := make([]json.RawMessage, 0, len(es))
	for _, e := range es {
		items = append(items, e.Spec)
	}
	writeJSON(w, http.StatusOK, wire.Items{Items: items})
}

func (s *Server) getEntity(w http.ResponseWriter, r *http.Request) {
	kind, err := kindOf(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	id, rv, err := s.rev(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	spec, err := s.store.Entity(r.Context(), id, rv, kind, r.PathValue("eid"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, spec)
}

// upserted reports a write, with the draft's issues about the written entities.
func (s *Server) upserted(w http.ResponseWriter, r *http.Request, status int, id, kind string, ids []string) {
	all, err := s.store.Validate(r.Context(), id, store.Draft)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	issues := []model.Issue{}
	for _, is := range all {
		for _, eid := range ids {
			p := model.Plural(kind) + "[" + eid + "]"
			if is.Path == p || strings.HasPrefix(is.Path, p+".") || strings.HasPrefix(is.Path, p+"[") {
				issues = append(issues, is)
				break
			}
		}
	}
	writeJSON(w, status, wire.UpsertResult{Kind: kind, IDs: ids, Issues: issues})
}

func (s *Server) entityWrite(w http.ResponseWriter, r *http.Request, status int, specs func([]byte) ([]json.RawMessage, error), pathID string, create bool) {
	kind, err := kindOf(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	id := r.PathValue("id")
	if err := s.store.Exists(r.Context(), id); err != nil {
		s.fail(w, r, err)
		return
	}
	b, err := readBody(w, r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	list, err := specs(b)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	ids, err := s.store.Upsert(r.Context(), id, kind, list, pathID, create)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	s.upserted(w, r, status, id, kind, ids)
}

func oneSpec(b []byte) ([]json.RawMessage, error) {
	b = bytes.TrimSpace(b)
	if len(b) == 0 || b[0] != '{' {
		return nil, badRequest("the body must be one JSON object")
	}
	return []json.RawMessage{b}, nil
}

// manySpecs accepts {"items": [...]} or a bare list.
func manySpecs(b []byte) ([]json.RawMessage, error) {
	b = bytes.TrimSpace(b)
	if len(b) > 0 && b[0] == '[' {
		var list []json.RawMessage
		if err := json.Unmarshal(b, &list); err != nil {
			return nil, badRequest("invalid body: %v", err)
		}
		return list, nil
	}
	var items wire.Items
	if err := model.Decode(b, &items); err != nil {
		return nil, badRequest("the body must be {\"items\": [...]}: %v", err)
	}
	return items.Items, nil
}

func (s *Server) createEntity(w http.ResponseWriter, r *http.Request) {
	s.entityWrite(w, r, http.StatusCreated, oneSpec, "", true)
}

func (s *Server) upsertEntities(w http.ResponseWriter, r *http.Request) {
	s.entityWrite(w, r, http.StatusOK, manySpecs, "", false)
}

func (s *Server) putEntity(w http.ResponseWriter, r *http.Request) {
	s.entityWrite(w, r, http.StatusOK, oneSpec, r.PathValue("eid"), false)
}

func (s *Server) patchEntity(w http.ResponseWriter, r *http.Request) {
	kind, err := kindOf(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	id, eid := r.PathValue("id"), r.PathValue("eid")
	b, err := readBody(w, r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	if _, err := s.store.Patch(r.Context(), id, kind, eid, b); err != nil {
		s.fail(w, r, err)
		return
	}
	s.upserted(w, r, http.StatusOK, id, kind, []string{eid})
}

func (s *Server) deleteEntity(w http.ResponseWriter, r *http.Request) {
	kind, err := kindOf(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	if err := s.store.DeleteEntity(r.Context(), r.PathValue("id"), kind, r.PathValue("eid")); err != nil {
		s.fail(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- simulations ----

// newRunID returns a time-sortable id: run_<UTC timestamp to µs>_<random hex>.
func (s *Server) newRunID(t time.Time) string {
	var b [4]byte
	_, _ = rand.Read(b[:])
	t = t.UTC()
	return fmt.Sprintf("run_%s%06d_%s", t.Format("20060102T150405"), t.Nanosecond()/1000, hex.EncodeToString(b[:]))
}

// runOne runs a request against a loaded document and saves it when asked.
func (s *Server) runOne(r *http.Request, id string, rv store.Rev, doc *model.Document, req sim.Request, save bool) (*wire.SimulationRun, error) {
	res, err := sim.Run(doc, req)
	if err != nil {
		var re *sim.RequestError
		if errors.As(err, &re) {
			return nil, badRequest("%s", re.Msg)
		}
		return nil, err
	}
	now := s.cfg.Now().UTC().Truncate(time.Microsecond)
	run := &wire.SimulationRun{Ontology: id, Revision: rv.String(), Flow: runFlow(doc, res.Request),
		Scenario: res.Request.Scenario, CreatedAt: now, Request: res.Request, Summary: res.Summary, Trace: res.Trace}
	// Only stored runs get an id, so every id resolves with GET /simulations/{id}.
	if save {
		run.ID = s.newRunID(now)
		if err := s.store.SaveRun(r.Context(), run); err != nil {
			return nil, err
		}
	}
	return run, nil
}

// runFlow is the flow a run is listed under: the request's flow, or for a
// multi-step scenario without one, the flow of its first step (§11.7).
func runFlow(doc *model.Document, req sim.Request) string {
	if req.Flow != "" || req.Scenario == "" {
		return req.Flow
	}
	for i := range doc.Scenarios {
		if doc.Scenarios[i].ID == req.Scenario {
			return doc.Scenarios[i].GroupFlow()
		}
	}
	return ""
}

// runResolution is a run's resolution: its scenario's, with the request's
// on top (as the simulator composes it), so the refinements it opens can be
// loaded from the store first.
func runResolution(doc *model.Document, req sim.Request) map[string]string {
	res := map[string]string{}
	if req.Scenario != "" {
		for i := range doc.Scenarios {
			if doc.Scenarios[i].ID == req.Scenario {
				for k, v := range doc.Scenarios[i].Resolution {
					res[k] = v
				}
				break
			}
		}
	}
	for k, v := range req.Resolution {
		res[k] = v
	}
	return res
}

func (s *Server) simulate(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var in wire.SimulationRequest
	if err := decodeBody(w, r, &in); err != nil {
		s.fail(w, r, err)
		return
	}
	rv, err := s.store.ResolveRev(r.Context(), id, in.Rev)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	doc, _, err := s.store.Document(r.Context(), id, rv)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	if err := s.store.Link(r.Context(), doc, runResolution(doc, in.Request)); err != nil {
		s.fail(w, r, err)
		return
	}
	save := in.Save == nil || *in.Save
	run, err := s.runOne(r, id, rv, doc, in.Request, save)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	status := http.StatusOK
	if save {
		status = http.StatusCreated
	}
	writeJSON(w, status, run)
}

func (s *Server) listRuns(w http.ResponseWriter, r *http.Request) {
	limit := 0
	if v := r.URL.Query().Get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 || n > 10000 {
			s.fail(w, r, badRequest("limit must be a number from 1 to 10000"))
			return
		}
		limit = n
	}
	runs, err := s.store.ListRuns(r.Context(), r.PathValue("id"), limit)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, wire.RunList{Runs: runs})
}

func (s *Server) getRun(w http.ResponseWriter, r *http.Request) {
	run, err := s.store.GetRun(r.Context(), r.PathValue("run"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, run)
}

// test runs every scenario at ?rev= and saves the runs (unless ?save=false)
// so they can be opened later.
func (s *Server) test(w http.ResponseWriter, r *http.Request) {
	doc, rv, _, err := s.document(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	// Load the imports, and the refinements every scenario's resolution
	// needs, once.
	all := map[string]string{}
	for _, sc := range doc.Scenarios {
		for k, v := range sc.Resolution {
			if v == model.ResolutionRefined {
				all[k] = v
			}
		}
	}
	if err := s.store.Link(r.Context(), doc, all); err != nil {
		s.fail(w, r, err)
		return
	}
	save := r.URL.Query().Get("save") != "false"
	id := r.PathValue("id")
	rep := wire.TestReport{Revision: rv.String(), Passed: true, Results: []wire.TestResult{}}
	for _, sc := range doc.Scenarios {
		res := wire.TestResult{Scenario: sc.ID, Name: sc.Name, Assertions: []sim.Assertion{}, Steps: len(sc.Steps), Mocks: len(sc.Mocks)}
		run, err := s.runOne(r, id, rv, doc, sim.Request{Scenario: sc.ID}, save)
		var se *store.Error
		switch {
		case errors.As(err, &se):
			res.Status, res.Error = "error", se.Message
		case err != nil:
			s.fail(w, r, err)
			return
		default:
			res.Passed, res.Status, res.Abort = run.Summary.Passed, run.Summary.Status, run.Summary.Abort
			res.MockedCalls = run.Summary.Mocks
			if run.Summary.Assertions != nil {
				res.Assertions = run.Summary.Assertions
			}
			if save {
				res.RunID = run.ID
			}
		}
		rep.Total++
		if !res.Passed {
			rep.Failed++
			rep.Passed = false
		}
		rep.Results = append(rep.Results, res)
	}
	if err := s.store.SaveTestReport(r.Context(), id, &rep); err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, rep)
}

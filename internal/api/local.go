package api

// Views of the repo-local stores next to mosaicd's working directory
// (DESIGN §16.6): the compose run store (.mosaic/compose/runs, §14.11) and
// the replay files `check --explore` writes (.mosaic/replay, §15.5).
// Replaying a schedule runs the simulator against a stored ontology and
// saves nothing. The only write is DELETE /v1/replays/{name}, accepted
// from loopback only (§6), to drop a replay that passes now.

import (
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/compose"
	"github.com/xleelz/mosaic/internal/explore"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
	"github.com/xleelz/mosaic/internal/store"
	wire "github.com/xleelz/mosaic/pkg/api"
)

// ReplayDir is the replay store's location under the work directory.
const ReplayDir = ".mosaic/replay"

const replaySuffix = ".replay.json"

func (s *Server) localRoutes(m *http.ServeMux) {
	m.HandleFunc("GET /v1/compose/runs", s.listComposeRuns)
	m.HandleFunc("GET /v1/compose/runs/{task}", s.getComposeRun)
	m.HandleFunc("GET /v1/compose/runs/{task}/tree", s.getComposeTree)
	m.HandleFunc("GET /v1/compose/runs/{task}/artifacts/{key...}", s.getComposeArtifact)
	m.HandleFunc("GET /v1/replays", s.listReplays)
	m.HandleFunc("DELETE /v1/replays/{name}", s.deleteReplay)
	m.HandleFunc("POST /v1/ontologies/{id}/replays/{name}", s.runReplay)
}

func (s *Server) workdir() string {
	if s.cfg.Workdir == "" {
		return "."
	}
	return s.cfg.Workdir
}

func (s *Server) composeStore() *compose.Store {
	return compose.NewStore(filepath.Join(s.workdir(), compose.DefaultRoot))
}

// ---- compose runs ----

// ComposeRunSummary is one task of the run store.
type ComposeRunSummary struct {
	ID       string    `json:"id"`
	Workflow string    `json:"workflow"`
	Version  string    `json:"version,omitempty"`
	Parent   string    `json:"parent,omitempty"`
	TreeRoot string    `json:"tree_root"`
	Depth    int       `json:"depth"`
	State    string    `json:"state"`
	Reason   string    `json:"reason,omitempty"`
	Created  time.Time `json:"created"`
	Updated  time.Time `json:"updated"`
}

// ComposeRunList is GET /v1/compose/runs.
type ComposeRunList struct {
	Root string              `json:"root"`
	Runs []ComposeRunSummary `json:"runs"`
}

// ComposeRunDetail is GET /v1/compose/runs/{task}: run.json, the change
// requests addressed to the task, and its agent sessions by stage path.
type ComposeRunDetail struct {
	Run      *compose.RunRecord           `json:"run"`
	Requests []*compose.ChangeRequest     `json:"requests"`
	Turns    map[string]*compose.TurnMeta `json:"turns"`
}

// validTask refuses ids that would leave the run store.
func validTask(id string) bool {
	return id != "" && id != "." && id != ".." && !strings.ContainsAny(id, `/\`) && !strings.HasPrefix(id, ".")
}

func (s *Server) loadTask(r *http.Request) (*compose.Store, *compose.RunRecord, error) {
	id := r.PathValue("task")
	if !validTask(id) {
		return nil, nil, badRequest("invalid task id %q", id)
	}
	cs := s.composeStore()
	rec, err := cs.Load(id)
	if errors.Is(err, compose.ErrNotFound) {
		return nil, nil, notFound("unknown compose task %s", id)
	}
	return cs, rec, err
}

func (s *Server) listComposeRuns(w http.ResponseWriter, r *http.Request) {
	cs := s.composeStore()
	recs, err := cs.List()
	if err != nil {
		s.fail(w, r, err)
		return
	}
	out := ComposeRunList{Root: compose.DefaultRoot, Runs: []ComposeRunSummary{}}
	for _, x := range recs {
		out.Runs = append(out.Runs, ComposeRunSummary{ID: x.ID, Workflow: x.Workflow, Version: x.Version, Parent: x.Parent,
			TreeRoot: x.TreeRoot, Depth: x.Depth, State: x.State, Reason: x.Reason, Created: x.Created, Updated: x.Updated})
	}
	writeJSON(w, http.StatusOK, out)
}

func (s *Server) getComposeRun(w http.ResponseWriter, r *http.Request) {
	cs, rec, err := s.loadTask(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	reqs, err := cs.Requests(rec.ID)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	turns, err := cs.TurnMetas(rec.ID)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	if reqs == nil {
		reqs = []*compose.ChangeRequest{}
	}
	writeJSON(w, http.StatusOK, ComposeRunDetail{Run: rec, Requests: reqs, Turns: turns})
}

func (s *Server) getComposeTree(w http.ResponseWriter, r *http.Request) {
	cs, rec, err := s.loadTask(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	t, err := compose.ReadTree(cs, rec.ID)
	if err == nil {
		err = t.AddStats(cs)
	}
	if err != nil {
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, t)
}

// getComposeArtifact serves a recorded artifact's JSON. Only keys run.json
// records are served, so a key can't name another file.
func (s *Server) getComposeArtifact(w http.ResponseWriter, r *http.Request) {
	cs, rec, err := s.loadTask(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	key := r.PathValue("key")
	if _, ok := rec.Artifacts[key]; !ok || strings.Contains(key, "..") {
		s.fail(w, r, notFound("task %s has no artifact %s", rec.ID, key))
		return
	}
	data, err := cs.ReadArtifact(rec.ID, key)
	if errors.Is(err, os.ErrNotExist) {
		err = notFound("artifact %s of task %s is recorded but its file is missing", key, rec.ID)
	}
	if err != nil {
		s.fail(w, r, err)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(append(data, '\n'))
}

// ---- exploration replays ----

// ReplayFile is one replay file, named by its file name without
// ".replay.json".
type ReplayFile struct {
	Name     string    `json:"name"`
	Modified time.Time `json:"modified"`
	// ScenarioIn lists the ontologies whose draft has the replay's
	// scenario. It is set only on an unfiltered list (no ?ontology=);
	// an empty list means no stored ontology has the scenario.
	ScenarioIn *[]string `json:"scenario_in,omitempty"`
	explore.Replay
}

// ReplayList is GET /v1/replays[?ontology=ID[&rev=R]]. With ?ontology=,
// it holds only the replays whose scenario exists in that ontology at
// ?rev= (default draft), and names both.
type ReplayList struct {
	Dir      string       `json:"dir"`
	Ontology string       `json:"ontology,omitempty"`
	Revision string       `json:"revision,omitempty"`
	Replays  []ReplayFile `json:"replays"`
}

// ReplayRun is POST /v1/ontologies/{id}/replays/{name}: the scenario run
// under the replay's schedule (never saved), whether the model diverged
// from the schedule, and the run's failures (empty when it passes).
type ReplayRun struct {
	Replay   ReplayFile         `json:"replay"`
	Diverged string             `json:"diverged,omitempty"`
	Failures []string           `json:"failures"`
	Run      wire.SimulationRun `json:"run"`
}

var replayName = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9._-]*$`)

func (s *Server) replayDir() string { return filepath.Join(s.workdir(), ReplayDir) }

func (s *Server) loadReplay(name string) (*ReplayFile, error) {
	if !replayName.MatchString(name) || strings.Contains(name, "..") {
		return nil, badRequest("invalid replay name %q", name)
	}
	path := filepath.Join(s.replayDir(), name+replaySuffix)
	fi, err := os.Stat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, notFound("no replay %s in %s", name, ReplayDir)
	}
	if err != nil {
		return nil, err
	}
	rp, err := explore.Load(path)
	if err != nil {
		return nil, badRequest("replay %s: %v", name, err)
	}
	return &ReplayFile{Name: name, Modified: fi.ModTime().UTC(), Replay: *rp}, nil
}

func (s *Server) listReplays(w http.ResponseWriter, r *http.Request) {
	out := ReplayList{Dir: ReplayDir, Replays: []ReplayFile{}}
	// The scenario ids of the ontology asked for, or of every ontology's
	// draft when none is (for scenario_in).
	var only map[string]bool
	var byOntology map[string]map[string]bool
	if id := r.URL.Query().Get("ontology"); id != "" {
		rv, err := s.store.ResolveRev(r.Context(), id, r.URL.Query().Get("rev"))
		if err != nil {
			s.fail(w, r, err)
			return
		}
		if only, err = s.scenarioIDs(r, id, rv); err != nil {
			s.fail(w, r, err)
			return
		}
		out.Ontology, out.Revision = id, rv.String()
	}
	entries, err := os.ReadDir(s.replayDir())
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		s.fail(w, r, err)
		return
	}
	for _, e := range entries {
		name, ok := strings.CutSuffix(e.Name(), replaySuffix)
		if e.IsDir() || !ok {
			continue
		}
		rf, err := s.loadReplay(name)
		if err != nil {
			continue // unreadable files are skipped, as the run store does
		}
		if only != nil {
			if !only[rf.Scenario] {
				continue
			}
		} else {
			if byOntology == nil {
				if byOntology, err = s.allScenarioIDs(r); err != nil {
					s.fail(w, r, err)
					return
				}
			}
			in := []string{}
			for id, ids := range byOntology {
				if ids[rf.Scenario] {
					in = append(in, id)
				}
			}
			sort.Strings(in)
			rf.ScenarioIn = &in
		}
		out.Replays = append(out.Replays, *rf)
	}
	sort.Slice(out.Replays, func(i, j int) bool { return out.Replays[i].Name < out.Replays[j].Name })
	writeJSON(w, http.StatusOK, out)
}

// scenarioIDs is the set of an ontology's scenario ids at a revision.
func (s *Server) scenarioIDs(r *http.Request, id string, rv store.Rev) (map[string]bool, error) {
	es, err := s.store.Entities(r.Context(), id, rv, model.KindScenario)
	if err != nil {
		return nil, err
	}
	ids := make(map[string]bool, len(es))
	for _, e := range es {
		ids[e.ID] = true
	}
	return ids, nil
}

// allScenarioIDs maps every stored ontology to its draft's scenario ids.
func (s *Server) allScenarioIDs(r *http.Request) (map[string]map[string]bool, error) {
	onts, err := s.store.ListOntologies(r.Context())
	if err != nil {
		return nil, err
	}
	out := make(map[string]map[string]bool, len(onts))
	for _, o := range onts {
		ids, err := s.scenarioIDs(r, o.ID, store.Draft)
		if err != nil {
			return nil, err
		}
		out[o.ID] = ids
	}
	return out, nil
}

// deleteReplay removes one replay file: a stale one whose scenario passes
// now. Like POST /v1/system/update it is local-only (§6): a loopback
// remote address, the bearer token when one is set (s.auth), and no
// Origin header or an allowed one.
func (s *Server) deleteReplay(w http.ResponseWriter, r *http.Request) {
	if !s.localOnly(w, r, "replay files are only removed") {
		return
	}
	name := r.PathValue("name")
	if !replayName.MatchString(name) || strings.Contains(name, "..") {
		s.fail(w, r, badRequest("invalid replay name %q", name))
		return
	}
	err := os.Remove(filepath.Join(s.replayDir(), name+replaySuffix))
	if errors.Is(err, os.ErrNotExist) {
		err = notFound("no replay %s in %s", name, ReplayDir)
	}
	if err != nil {
		s.fail(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// runReplay runs a replay's scenario against the ontology at ?rev= under
// the recorded schedule. The run is not saved.
func (s *Server) runReplay(w http.ResponseWriter, r *http.Request) {
	rf, err := s.loadReplay(r.PathValue("name"))
	if err != nil {
		s.fail(w, r, err)
		return
	}
	doc, rv, _, err := s.document(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	found := false
	for i := range doc.Scenarios {
		found = found || doc.Scenarios[i].ID == rf.Scenario
	}
	if !found {
		s.fail(w, r, badRequest("ontology %s has no scenario %s", r.PathValue("id"), rf.Scenario))
		return
	}
	req := sim.Request{Scenario: rf.Scenario}
	if err := s.store.Link(r.Context(), doc, runResolution(doc, req)); err != nil {
		s.fail(w, r, err)
		return
	}
	res, diverged, err := explore.Run(doc, &rf.Replay, sim.Limits{})
	if err != nil {
		var re *sim.RequestError
		if errors.As(err, &re) {
			err = badRequest("%s", re.Msg)
		}
		s.fail(w, r, err)
		return
	}
	failures := explore.Failures(res, &rf.Replay)
	if failures == nil {
		failures = []string{}
	}
	now := s.cfg.Now().UTC().Truncate(time.Microsecond)
	run := wire.SimulationRun{Ontology: r.PathValue("id"), Revision: rv.String(), Flow: runFlow(doc, res.Request),
		Scenario: rf.Scenario, CreatedAt: now, Request: res.Request, Summary: res.Summary, Trace: res.Trace}
	writeJSON(w, http.StatusOK, ReplayRun{Replay: *rf, Diverged: diverged, Failures: failures, Run: run})
}

package compose

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

// DefaultRoot is the run store's location under the repo root.
const DefaultRoot = ".mosaic/compose/runs"

// Run states.
const (
	StatePending     = "pending"
	StateRunning     = "running"
	StateDone        = "done"
	StateFailed      = "failed"
	StateSkipped     = "skipped"
	StateCancelled   = "cancelled"
	StateInterrupted = "interrupted"
)

// Failure reasons.
const (
	ReasonRecursionBudget = "recursion_budget"
	ReasonMaxBranches     = "max_branches"
	ReasonGate            = "gate"
	ReasonSchema          = "schema"
	ReasonExecutor        = "executor"
	ReasonBranchFailed    = "branch_failed"
	ReasonJoin            = "join"
	ReasonChildFailed     = "child_failed"
	ReasonAdmission       = "admission"
	ReasonOutputs         = "outputs"
	ReasonStage           = "stage_failed"
	ReasonCommand         = "command"
	ReasonChangeRequest   = "change_request"
	ReasonBinding         = "binding"
	ReasonBudget          = "budget"
	ReasonWriteScope      = "write_scope"
)

// RunRecord is run.json: one task of a run tree.
type RunRecord struct {
	ID           string                     `json:"id"`
	Workflow     string                     `json:"workflow"`
	Version      string                     `json:"version,omitempty"`
	TemplatePath string                     `json:"template_path,omitempty"`
	Template     json.RawMessage            `json:"template"`
	Inputs       map[string]json.RawMessage `json:"inputs"`
	FromParent   map[string]string          `json:"from_parent,omitempty"`
	Parent       string                     `json:"parent,omitempty"`
	TreeRoot     string                     `json:"tree_root"`
	Depth        int                        `json:"depth"`
	Origin       *Origin                    `json:"origin,omitempty"`
	OutDir       string                     `json:"out_dir"`
	State        string                     `json:"state"`
	Reason       string                     `json:"reason,omitempty"`
	Error        string                     `json:"error,omitempty"`
	Created      time.Time                  `json:"created"`
	Updated      time.Time                  `json:"updated"`
	Stages       map[string]*StageState     `json:"stages"`
	Artifacts    map[string]*ArtifactMeta   `json:"artifacts"`
}

// Origin records how a child was admitted.
type Origin struct {
	Stage    string `json:"stage,omitempty"`
	Visit    int    `json:"visit,omitempty"`
	Branch   *int   `json:"branch,omitempty"`
	Detached bool   `json:"detached,omitempty"`
}

// StageState is a stage's recorded state.
type StageState struct {
	State    string         `json:"state"`
	Reason   string         `json:"reason,omitempty"`
	Error    string         `json:"error,omitempty"`
	Visit    int            `json:"visit,omitempty"`
	RoutedTo string         `json:"routed_to,omitempty"`
	Routed   *Failure       `json:"routed,omitempty"` // on a handler: the failure routed to it
	Started  *time.Time     `json:"started,omitempty"`
	Finished *time.Time     `json:"finished,omitempty"`
	Children []string       `json:"children,omitempty"`
	Count    *int           `json:"count,omitempty"` // fanout width
	Branches []*BranchState `json:"branches,omitempty"`
	Request  string         `json:"request,omitempty"` // change_request id
}

// BranchState is one fanout branch instance.
type BranchState struct {
	Index  int                    `json:"index"`
	State  string                 `json:"state"`
	Reason string                 `json:"reason,omitempty"`
	Error  string                 `json:"error,omitempty"`
	Stages map[string]*StageState `json:"stages"`
}

// Failure is bound as the artifact "failure" in a handler stage.
type Failure struct {
	Stage  string `json:"stage"`
	Reason string `json:"reason"`
	Error  string `json:"error,omitempty"`
}

// ArtifactMeta describes a recorded artifact. Its key in the record is its
// path under artifacts/ without ".json" (branch artifacts are
// "<fanout>/<index>/<name>").
type ArtifactMeta struct {
	Provenance string    `json:"provenance"`
	SHA256     string    `json:"sha256"`
	Recorded   time.Time `json:"recorded"`
}

// ChangeRequest is a request a child addresses to an ancestor (FAE-WF-101).
type ChangeRequest struct {
	ID        string          `json:"id"`
	FromTask  string          `json:"from_task"`
	FromStage string          `json:"from_stage"`
	Target    RequestTarget   `json:"target"`
	Body      json.RawMessage `json:"body"`
	State     string          `json:"state"` // pending until a controller decides
	Recorded  time.Time       `json:"recorded"`
}

// RequestTarget names the task and artifact a change request is about.
type RequestTarget struct {
	Task     string `json:"task"`
	Artifact string `json:"artifact,omitempty"`
}

// Event is one line of a run's events.jsonl, its task history.
type Event struct {
	Time       time.Time      `json:"time"`
	Type       string         `json:"type"`
	Task       string         `json:"task"`
	ParentTask string         `json:"parent_task,omitempty"`
	TreeRoot   string         `json:"tree_root"`
	Stage      string         `json:"stage,omitempty"`
	Data       map[string]any `json:"data,omitempty"`
}

// Store is the run store: one directory per task.
type Store struct {
	Root string
	mu   sync.Mutex // serializes events and request writes in this process
}

// NewStore returns a store rooted at root.
func NewStore(root string) *Store { return &Store{Root: root} }

// ErrNotFound is returned for an unknown task.
var ErrNotFound = errors.New("no such task")

// RunDir returns a task's directory.
func (s *Store) RunDir(id string) string { return filepath.Join(s.Root, id) }

// Exists reports whether a task has a run.json.
func (s *Store) Exists(id string) bool {
	_, err := os.Stat(filepath.Join(s.RunDir(id), "run.json"))
	return err == nil
}

// Load reads a task's run.json.
func (s *Store) Load(id string) (*RunRecord, error) {
	data, err := os.ReadFile(filepath.Join(s.RunDir(id), "run.json"))
	if errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("%w: %s", ErrNotFound, id)
	}
	if err != nil {
		return nil, err
	}
	var r RunRecord
	if err := json.Unmarshal(data, &r); err != nil {
		return nil, fmt.Errorf("%s: run.json: %v", id, err)
	}
	return &r, nil
}

// Save writes a task's run.json atomically.
func (s *Store) Save(r *RunRecord) error {
	data, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		return err
	}
	return writeAtomic(filepath.Join(s.RunDir(r.ID), "run.json"), append(data, '\n'))
}

func writeAtomic(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".tmp-*")
	if err != nil {
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		os.Remove(tmp.Name())
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmp.Name())
		return err
	}
	return os.Rename(tmp.Name(), path)
}

func (s *Store) artifactPath(id, key string) string {
	return filepath.Join(s.RunDir(id), "artifacts", filepath.FromSlash(key)+".json")
}

// WriteArtifact records an artifact's value and returns its digest.
func (s *Store) WriteArtifact(id, key string, value json.RawMessage) (string, error) {
	var buf bytes.Buffer
	if err := json.Indent(&buf, value, "", "  "); err != nil {
		return "", err
	}
	buf.WriteByte('\n')
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:]), writeAtomic(s.artifactPath(id, key), buf.Bytes())
}

// ReadArtifact reads an artifact's value.
func (s *Store) ReadArtifact(id, key string) (json.RawMessage, error) {
	data, err := os.ReadFile(s.artifactPath(id, key))
	if err != nil {
		return nil, err
	}
	return bytes.TrimSpace(data), nil
}

// List returns every task in the store, sorted by id.
func (s *Store) List() ([]*RunRecord, error) {
	entries, err := os.ReadDir(s.Root)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []*RunRecord
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		r, err := s.Load(e.Name())
		if err != nil {
			continue
		}
		out = append(out, r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

// AppendEvent appends an event to a task's history.
func (s *Store) AppendEvent(id string, ev Event) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	data, err := json.Marshal(ev)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(s.RunDir(id), 0o755); err != nil {
		return err
	}
	f, err := os.OpenFile(filepath.Join(s.RunDir(id), "events.jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.Write(append(data, '\n'))
	return err
}

// Events reads a task's history.
func (s *Store) Events(id string) ([]Event, error) {
	f, err := os.Open(filepath.Join(s.RunDir(id), "events.jsonl"))
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var out []Event
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 64<<20)
	for sc.Scan() {
		var ev Event
		if json.Unmarshal(sc.Bytes(), &ev) == nil {
			out = append(out, ev)
		}
	}
	return out, sc.Err()
}

// TurnMeta is turns/<stage path>.meta.json: the agent sessions of one
// agent_turn stage (DESIGN §14.13). Every attempt of every turn (resumes,
// schema retries) is a separate entry.
type TurnMeta struct {
	Task     string         `json:"task"`
	Stage    string         `json:"stage"` // the stage path, e.g. "areas/0/build"
	Attempts []SessionStats `json:"attempts"`
}

// TurnMetaPath returns the meta file of a stage path ("<fanout>/<i>/<id>").
func (s *Store) TurnMetaPath(id, stagePath string) string {
	return filepath.Join(s.RunDir(id), "turns", filepath.FromSlash(stagePath)+".meta.json")
}

// ReadTurnMeta reads a stage's meta file; nil when there is none.
func (s *Store) ReadTurnMeta(id, stagePath string) (*TurnMeta, error) {
	data, err := os.ReadFile(s.TurnMetaPath(id, stagePath))
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var m TurnMeta
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("%s: %s.meta.json: %v", id, stagePath, err)
	}
	return &m, nil
}

// WriteTurnMeta writes a stage's meta file atomically.
func (s *Store) WriteTurnMeta(m *TurnMeta) error {
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	return writeAtomic(s.TurnMetaPath(m.Task, m.Stage), append(data, '\n'))
}

// TurnMetas reads every meta file of a task, by stage path.
func (s *Store) TurnMetas(id string) (map[string]*TurnMeta, error) {
	root := filepath.Join(s.RunDir(id), "turns")
	out := map[string]*TurnMeta{}
	err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				return filepath.SkipDir
			}
			return err
		}
		if d.IsDir() || !strings.HasSuffix(path, ".meta.json") {
			return nil
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		stage := filepath.ToSlash(strings.TrimSuffix(rel, ".meta.json"))
		m, err := s.ReadTurnMeta(id, stage)
		if err != nil {
			return err
		}
		out[stage] = m
		return nil
	})
	return out, err
}

// AddRequest records a change request in its target's requests/ directory.
func (s *Store) AddRequest(req *ChangeRequest) error {
	data, err := json.MarshalIndent(req, "", "  ")
	if err != nil {
		return err
	}
	name := strings.ReplaceAll(req.ID, "/", "_") + ".json"
	return writeAtomic(filepath.Join(s.RunDir(req.Target.Task), "requests", name), append(data, '\n'))
}

// Requests lists the change requests addressed to a task, by id.
func (s *Store) Requests(id string) ([]*ChangeRequest, error) {
	dir := filepath.Join(s.RunDir(id), "requests")
	entries, err := os.ReadDir(dir)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []*ChangeRequest
	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".json" {
			continue
		}
		data, err := os.ReadFile(filepath.Join(dir, e.Name()))
		if err != nil {
			return nil, err
		}
		var r ChangeRequest
		if err := json.Unmarshal(data, &r); err != nil {
			return nil, fmt.Errorf("%s: %v", e.Name(), err)
		}
		out = append(out, &r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

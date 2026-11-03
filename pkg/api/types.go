// Package api holds the wire types of mosaicd's HTTP API (docs/DESIGN.md §6).
// The server, the Go client and the CLI share them, so they cannot drift.
package api

import (
	"encoding/json"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// Revision selectors accepted by ?rev= and by request bodies.
const (
	RevDraft  = "draft"
	RevLatest = "latest"
)

// Health is GET /v1/health.
type Health struct {
	Status  string `json:"status"`
	Version string `json:"version"`
	Dolt    string `json:"dolt"`
}

// SystemVersion is GET /v1/system/version: the running build and whether the
// checkout it was built from (--source-dir) can be fast-forwarded.
type SystemVersion struct {
	Version   string       `json:"version"`
	Commit    string       `json:"commit"`     // the running build's commit ("" when unknown)
	Dirty     bool         `json:"dirty"`      // the build had local changes
	Branch    string       `json:"branch"`     // the checkout's branch
	Upstream  string       `json:"upstream"`   // its upstream, such as origin/main
	SourceDir string       `json:"source_dir"` // "" when mosaicd has no --source-dir
	Update    UpdateStatus `json:"update"`
}

// UpdateStatus says whether POST /v1/system/update would fast-forward the
// checkout, and why not.
type UpdateStatus struct {
	Available     bool       `json:"available"`
	Reason        string     `json:"reason,omitempty"` // why not, when unavailable
	Behind        int        `json:"behind"`           // commits in HEAD..@{u}
	Ahead         int        `json:"ahead"`            // commits in @{u}..HEAD
	LatestCommit  string     `json:"latest_commit"`    // the upstream's head
	LatestSubject string     `json:"latest_subject"`
	CheckedAt     *time.Time `json:"checked_at"` // the last fetch; null when never
}

// SystemUpdate is the response of POST /v1/system/update.
type SystemUpdate struct {
	UpdatedTo  string `json:"updated_to"`
	From       string `json:"from"`
	Restarting bool   `json:"restarting"` // mosaicd exits for scripts/serve.sh to rebuild and restart it
	Note       string `json:"note,omitempty"`
}

// SourceFile is GET /v1/ontologies/{id}/source: one file of the code an
// ontology was derived from, fetched from GitHub at a pinned commit.
type SourceFile struct {
	Repo         string `json:"repo"`          // owner/name
	SHA          string `json:"sha"`           // the commit
	Path         string `json:"path"`          // relative to the repo root
	Content      string `json:"content"`       // the file's text
	LanguageHint string `json:"language_hint"` // from the extension, such as go, python, cpp ("" when unknown)
	Size         int    `json:"size"`          // bytes
	URL          string `json:"url"`           // the github.com blob URL, without a line anchor
}

// OntologySummary is one ontology in the registry.
type OntologySummary struct {
	ID             string    `json:"id"`
	Name           string    `json:"name"`
	Description    string    `json:"description"`
	CreatedAt      time.Time `json:"created_at"`
	UpdatedAt      time.Time `json:"updated_at"`
	LatestRevision int       `json:"latest_revision"`
	RevisionCount  int       `json:"revision_count"`
}

// OntologyDetail is GET /v1/ontologies/{id}: the summary plus draft state.
type OntologyDetail struct {
	OntologySummary
	Counts     map[string]int `json:"counts"`
	DraftDirty bool           `json:"draft_dirty"`
	// The draft's document-level hierarchy fields (§14.11), when set.
	Level   string            `json:"level,omitempty"`
	Refines *model.RefinesRef `json:"refines,omitempty"`
	Imports []model.ImportRef `json:"imports,omitempty"`
}

// OntologyList is GET /v1/ontologies.
type OntologyList struct {
	Ontologies []OntologySummary `json:"ontologies"`
}

// CreateOntology is POST /v1/ontologies.
type CreateOntology struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
}

// UpdateOntology is PATCH /v1/ontologies/{id}.
type UpdateOntology struct {
	Name        *string `json:"name,omitempty"`
	Description *string `json:"description,omitempty"`
}

// Revision is one immutable revision.
type Revision struct {
	Number    int           `json:"number"`
	Hash      string        `json:"hash"`
	Message   string        `json:"message"`
	Author    string        `json:"author"`
	CreatedAt time.Time     `json:"created_at"`
	Source    *CommitSource `json:"source,omitempty"` // the code commit this revision models
}

// CommitSource names the code commit an ontology revision models.
type CommitSource struct {
	Repo    string    `json:"repo"`
	SHA     string    `json:"sha"`
	Parent  string    `json:"parent,omitempty"`
	Subject string    `json:"subject,omitempty"`
	Author  string    `json:"author,omitempty"`
	Date    time.Time `json:"date,omitzero"`
	URL     string    `json:"url,omitempty"`
}

// Commit is a code commit known to an ontology, linked to the revision that
// models it when one exists.
type Commit struct {
	SHA      string    `json:"sha"`
	Parent   string    `json:"parent,omitempty"`
	Subject  string    `json:"subject"`
	Author   string    `json:"author,omitempty"`
	Date     time.Time `json:"date"`
	URL      string    `json:"url,omitempty"`      // link to the commit, e.g. from --url-template
	Files    []string  `json:"files"`              // paths changed relative to the parent
	Revision int       `json:"revision,omitempty"` // revision whose source.sha is this commit; 0 if none
	Changed  bool      `json:"changed"`            // that revision differs from the previous one
}

// ImportCommits is POST /v1/ontologies/{id}/commits: upsert commit metadata.
// The CLI reads git locally; the server never touches a repository.
type ImportCommits struct {
	Repo    string   `json:"repo"`
	Commits []Commit `json:"commits"`
}

// CommitList is GET /v1/ontologies/{id}/commits, oldest first.
type CommitList struct {
	Repo    string   `json:"repo"`
	Commits []Commit `json:"commits"`
}

// CommitDetail is GET /v1/ontologies/{id}/commits/{sha}: the revisions before
// and after the commit, the entity changes between them and their impact.
type CommitDetail struct {
	Commit  Commit        `json:"commit"`
	Before  int           `json:"before"` // revision modelling the parent (or the latest earlier one); 0 if none
	After   int           `json:"after"`  // revision modelling this commit; 0 if none
	Changes []Change      `json:"changes"`
	Impact  *model.Impact `json:"impact"`
}

// RevisionList is GET /v1/ontologies/{id}/revisions.
type RevisionList struct {
	Revisions []Revision `json:"revisions"`
}

// CreateRevision is POST /v1/ontologies/{id}/revisions.
type CreateRevision struct {
	Message    string        `json:"message"`
	Author     string        `json:"author,omitempty"`
	Source     *CommitSource `json:"source,omitempty"`
	AllowEmpty bool          `json:"allow_empty,omitempty"` // record a revision even when the draft is unchanged (a commit that changes no modelled code)
}

// Items is a list of entity specs: GET /v1/ontologies/{id}/{kind} returns it,
// and PUT /v1/ontologies/{id}/{kind} upserts it.
type Items struct {
	Items []json.RawMessage `json:"items"`
}

// UpsertResult reports an entity write.
type UpsertResult struct {
	Kind   string        `json:"kind"`
	IDs    []string      `json:"ids"`
	Issues []model.Issue `json:"issues"`
}

// PutDocumentResult is PUT /v1/ontologies/{id}/document. The draft is
// replaced even when it does not validate; Issues says what to fix.
type PutDocumentResult struct {
	Counts map[string]int `json:"counts"`
	Valid  bool           `json:"valid"`
	Issues []model.Issue  `json:"issues"`
}

// Change is one entity difference between two revisions or the draft.
type Change struct {
	Kind   string          `json:"kind"`
	ID     string          `json:"id"`
	Change string          `json:"change"` // added | removed | modified
	Before json.RawMessage `json:"before,omitempty"`
	After  json.RawMessage `json:"after,omitempty"`
}

// Diff is GET /v1/ontologies/{id}/diff?from=&to=.
type Diff struct {
	From    string   `json:"from"`
	To      string   `json:"to"`
	Changes []Change `json:"changes"`
}

// Validation is POST /v1/ontologies/{id}/validate.
type Validation struct {
	Revision string        `json:"revision"`
	Valid    bool          `json:"valid"`
	Issues   []model.Issue `json:"issues"`
}

// SimulationRequest is POST /v1/ontologies/{id}/simulations.
type SimulationRequest struct {
	Rev string `json:"rev,omitempty"` // draft (default) | latest | N
	sim.Request
	Save *bool `json:"save,omitempty"` // default true
}

// SimulationRun is a stored or ad hoc run.
type SimulationRun struct {
	ID        string      `json:"id"`
	Ontology  string      `json:"ontology"`
	Revision  string      `json:"revision"` // "draft" or the revision number
	Flow      string      `json:"flow"`
	Scenario  string      `json:"scenario,omitempty"`
	CreatedAt time.Time   `json:"created_at"`
	Request   sim.Request `json:"request"`
	Summary   sim.Summary `json:"summary"`
	Trace     []sim.Event `json:"trace,omitempty"`
}

// RunList is GET /v1/ontologies/{id}/simulations (runs without traces).
type RunList struct {
	Runs []SimulationRun `json:"runs"`
}

// TestResult is one scenario's outcome in POST /v1/ontologies/{id}/test.
type TestResult struct {
	Scenario   string          `json:"scenario"`
	Name       string          `json:"name"`
	Passed     bool            `json:"passed"`
	Status     string          `json:"status"`
	Assertions []sim.Assertion `json:"assertions"`
	Abort      string          `json:"abort,omitempty"`
	Error      string          `json:"error,omitempty"`
	RunID      string          `json:"run_id,omitempty"`
	// Steps is the scenario's step count when it is multi-step (§11.7).
	Steps int `json:"steps,omitempty"`
	// Mocks is how many mocks the scenario declares, and MockedCalls how
	// many calls they replaced in the run (§11.8).
	Mocks       int `json:"mocks,omitempty"`
	MockedCalls int `json:"mocked_calls,omitempty"`
}

// TestReport is POST /v1/ontologies/{id}/test.
type TestReport struct {
	Revision string       `json:"revision"`
	Passed   bool         `json:"passed"`
	Total    int          `json:"total"`
	Failed   int          `json:"failed"`
	Results  []TestResult `json:"results"`
}

// ErrorBody is every non-2xx response.
type ErrorBody struct {
	Error ErrorDetail `json:"error"`
}

// ErrorDetail describes a failed request. Codes: bad_request, not_found,
// conflict, invalid (422, with issues), unauthorized, internal.
type ErrorDetail struct {
	Code    string        `json:"code"`
	Message string        `json:"message"`
	Issues  []model.Issue `json:"issues,omitempty"`
}

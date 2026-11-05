// Package client is the Go client of mosaicd's HTTP API (docs/DESIGN.md §6).
// Every method maps to one endpoint and uses the wire types of pkg/api.
//
// Errors are typed: a non-2xx response is an *APIError carrying the server's
// code, message and validation issues, and a request that never reached the
// server (connection refused, DNS failure, timeout) satisfies IsUnreachable.
package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

// DefaultTimeout bounds every request made with the default HTTP client.
const DefaultTimeout = 60 * time.Second

// Client calls one mosaicd server.
type Client struct {
	base      string // ends in /v1, no trailing slash
	token     string
	http      *http.Client
	userAgent string
}

// Option configures a Client.
type Option func(*Client)

// WithHTTPClient replaces the default HTTP client (whose timeout is DefaultTimeout).
func WithHTTPClient(h *http.Client) Option { return func(c *Client) { c.http = h } }

// WithTimeout sets the timeout of the default HTTP client.
func WithTimeout(d time.Duration) Option {
	return func(c *Client) { c.http = &http.Client{Timeout: d} }
}

// WithUserAgent sets the User-Agent header.
func WithUserAgent(ua string) Option { return func(c *Client) { c.userAgent = ua } }

// New returns a client for the server at baseURL, such as
// "http://127.0.0.1:7878". A trailing "/v1" is optional. When token is not
// empty, every request carries "Authorization: Bearer <token>".
func New(baseURL, token string, opts ...Option) *Client {
	base := strings.TrimRight(baseURL, "/")
	if !strings.HasSuffix(base, "/v1") {
		base += "/v1"
	}
	c := &Client{base: base, token: token, http: &http.Client{Timeout: DefaultTimeout}, userAgent: "mosaic-client"}
	for _, o := range opts {
		o(c)
	}
	return c
}

// BaseURL returns the API root the client calls, ending in /v1.
func (c *Client) BaseURL() string { return c.base }

// APIError is a non-2xx response.
type APIError struct {
	Status  int           // HTTP status code
	Code    string        // bad_request, not_found, conflict, invalid, unauthorized, internal, ...
	Message string        // human-readable explanation
	Issues  []model.Issue // validation issues, when Code is "invalid"
}

func (e *APIError) Error() string {
	msg := e.Message
	if msg == "" {
		msg = http.StatusText(e.Status)
	}
	if e.Code != "" {
		return fmt.Sprintf("%s (%s, HTTP %d)", msg, e.Code, e.Status)
	}
	return fmt.Sprintf("%s (HTTP %d)", msg, e.Status)
}

// IsNotFound reports whether err is an API error with status 404.
func IsNotFound(err error) bool {
	var ae *APIError
	return errors.As(err, &ae) && ae.Status == http.StatusNotFound
}

// UnreachableError is a request that did not get an HTTP response.
type UnreachableError struct {
	URL string
	Err error
}

func (e *UnreachableError) Error() string {
	return fmt.Sprintf("cannot reach mosaicd at %s: %v", e.URL, e.Err)
}

func (e *UnreachableError) Unwrap() error { return e.Err }

// IsUnreachable reports whether err means the server could not be reached:
// connection refused, name resolution failure, TLS failure or timeout.
func IsUnreachable(err error) bool {
	var ue *UnreachableError
	return errors.As(err, &ue)
}

// Kind path segments.

// Collection returns the plural path segment for a kind given in singular or
// plural form ("component" or "components").
func Collection(kind string) (string, error) {
	k, ok := model.KindOf(kind)
	if !ok {
		return "", fmt.Errorf("unknown kind %q (want one of %s)", kind, strings.Join(collections(), ", "))
	}
	return model.Plural(k), nil
}

func collections() []string {
	out := make([]string, len(model.Kinds))
	for i, k := range model.Kinds {
		out[i] = model.Plural(k)
	}
	return out
}

// Transport.

func revQuery(rev string) url.Values {
	q := url.Values{}
	if rev != "" {
		q.Set("rev", rev)
	}
	return q
}

func esc(s string) string { return url.PathEscape(s) }

// do sends a request. body, when not nil, is encoded as JSON (a
// json.RawMessage is sent as is). out, when not nil, receives the decoded
// response; numbers decode as json.Number so that values round-trip exactly.
func (c *Client) do(ctx context.Context, method, path string, query url.Values, body, out any) error {
	u := c.base + path
	if len(query) > 0 {
		u += "?" + query.Encode()
	}
	var rd io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("encode request: %w", err)
		}
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, u, rd)
	if err != nil {
		return fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.userAgent != "" {
		req.Header.Set("User-Agent", c.userAgent)
	}
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		if ctx.Err() != nil && errors.Is(err, context.Canceled) {
			return err
		}
		return &UnreachableError{URL: strings.TrimSuffix(c.base, "/v1"), Err: unwrapURLError(err)}
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return &UnreachableError{URL: strings.TrimSuffix(c.base, "/v1"), Err: fmt.Errorf("reading response: %w", err)}
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return decodeError(resp.StatusCode, data)
	}
	if out == nil {
		return nil
	}
	if len(bytes.TrimSpace(data)) == 0 {
		return fmt.Errorf("%s %s: empty response from server", method, path)
	}
	if raw, ok := out.(*json.RawMessage); ok {
		if !json.Valid(data) {
			return fmt.Errorf("%s %s: response is not JSON", method, path)
		}
		*raw = append((*raw)[:0], bytes.TrimSpace(data)...)
		return nil
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	if err := dec.Decode(out); err != nil {
		return fmt.Errorf("%s %s: decode response: %w", method, path, err)
	}
	return nil
}

// unwrapURLError drops the "Get "http://...": " prefix that *url.Error adds,
// since UnreachableError already names the server.
func unwrapURLError(err error) error {
	var ue *url.Error
	if errors.As(err, &ue) {
		if ue.Timeout() {
			return fmt.Errorf("request timed out: %w", ue.Err)
		}
		return ue.Err
	}
	return err
}

func decodeError(status int, data []byte) error {
	var eb api.ErrorBody
	if json.Unmarshal(data, &eb) == nil && (eb.Error.Code != "" || eb.Error.Message != "") {
		return &APIError{Status: status, Code: eb.Error.Code, Message: eb.Error.Message, Issues: eb.Error.Issues}
	}
	msg := strings.TrimSpace(string(data))
	if len(msg) > 500 {
		msg = msg[:500] + "…"
	}
	if msg == "" {
		msg = http.StatusText(status)
	}
	return &APIError{Status: status, Code: codeForStatus(status), Message: msg}
}

func codeForStatus(status int) string {
	switch status {
	case http.StatusBadRequest:
		return "bad_request"
	case http.StatusUnauthorized, http.StatusForbidden:
		return "unauthorized"
	case http.StatusNotFound:
		return "not_found"
	case http.StatusConflict:
		return "conflict"
	case http.StatusUnprocessableEntity:
		return "invalid"
	}
	if status >= 500 {
		return "internal"
	}
	return "http_" + strconv.Itoa(status)
}

// Health is GET /v1/health.
func (c *Client) Health(ctx context.Context) (*api.Health, error) {
	var out api.Health
	if err := c.do(ctx, http.MethodGet, "/health", nil, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// SystemVersion is GET /v1/system/version; refresh forces a fetch of the
// upstream (the server rate-limits it).
func (c *Client) SystemVersion(ctx context.Context, refresh bool) (*api.SystemVersion, error) {
	var q url.Values
	if refresh {
		q = url.Values{"refresh": {"1"}}
	}
	var out api.SystemVersion
	if err := c.do(ctx, http.MethodGet, "/system/version", q, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// SystemUpdate is POST /v1/system/update: fast-forward mosaicd's checkout,
// then restart when supervised.
func (c *Client) SystemUpdate(ctx context.Context) (*api.SystemUpdate, error) {
	var out api.SystemUpdate
	if err := c.do(ctx, http.MethodPost, "/system/update", nil, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Ontologies.

// ListOntologies is GET /v1/ontologies.
func (c *Client) ListOntologies(ctx context.Context) ([]api.OntologySummary, error) {
	var out api.OntologyList
	if err := c.do(ctx, http.MethodGet, "/ontologies", nil, nil, &out); err != nil {
		return nil, err
	}
	if out.Ontologies == nil {
		out.Ontologies = []api.OntologySummary{}
	}
	return out.Ontologies, nil
}

// GetOntology is GET /v1/ontologies/{id}.
func (c *Client) GetOntology(ctx context.Context, id string) (*api.OntologyDetail, error) {
	var out api.OntologyDetail
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(id), nil, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// CreateOntology is POST /v1/ontologies.
func (c *Client) CreateOntology(ctx context.Context, req api.CreateOntology) (*api.OntologyDetail, error) {
	var out api.OntologyDetail
	if err := c.do(ctx, http.MethodPost, "/ontologies", nil, req, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// UpdateOntology is PATCH /v1/ontologies/{id}: it renames or redescribes.
func (c *Client) UpdateOntology(ctx context.Context, id string, req api.UpdateOntology) (*api.OntologyDetail, error) {
	var out api.OntologyDetail
	if err := c.do(ctx, http.MethodPatch, "/ontologies/"+esc(id), nil, req, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// DeleteOntology is DELETE /v1/ontologies/{id}.
func (c *Client) DeleteOntology(ctx context.Context, id string) error {
	return c.do(ctx, http.MethodDelete, "/ontologies/"+esc(id), nil, nil, nil)
}

// Documents.

// GetDocument is GET /v1/ontologies/{id}/document?rev=. An empty rev means
// the server's default (the draft).
func (c *Client) GetDocument(ctx context.Context, ont, rev string) (*model.Document, error) {
	var out model.Document
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/document", revQuery(rev), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// GetDocumentJSON is GET /v1/ontologies/{id}/document?rev= returning the
// server's JSON unchanged.
func (c *Client) GetDocumentJSON(ctx context.Context, ont, rev string) (json.RawMessage, error) {
	var out json.RawMessage
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/document", revQuery(rev), nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// PutDocument is PUT /v1/ontologies/{id}/document: it replaces the draft.
// doc is a *model.Document or the document's JSON as a json.RawMessage. The
// draft is replaced even when invalid; the result's Issues say what to fix.
func (c *Client) PutDocument(ctx context.Context, ont string, doc any) (*api.PutDocumentResult, error) {
	var out api.PutDocumentResult
	if err := c.do(ctx, http.MethodPut, "/ontologies/"+esc(ont)+"/document", nil, doc, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Entities. kind is singular or plural ("component" or "components").

func (c *Client) entityPath(ont, kind string, id ...string) (string, error) {
	coll, err := Collection(kind)
	if err != nil {
		return "", err
	}
	p := "/ontologies/" + esc(ont) + "/" + coll
	for _, s := range id {
		p += "/" + esc(s)
	}
	return p, nil
}

// ListEntities is GET /v1/ontologies/{id}/{kind}?rev=.
func (c *Client) ListEntities(ctx context.Context, ont, kind, rev string) ([]json.RawMessage, error) {
	p, err := c.entityPath(ont, kind)
	if err != nil {
		return nil, err
	}
	var out api.Items
	if err := c.do(ctx, http.MethodGet, p, revQuery(rev), nil, &out); err != nil {
		return nil, err
	}
	if out.Items == nil {
		out.Items = []json.RawMessage{}
	}
	return out.Items, nil
}

// GetEntity is GET /v1/ontologies/{id}/{kind}/{eid}?rev=.
func (c *Client) GetEntity(ctx context.Context, ont, kind, id, rev string) (json.RawMessage, error) {
	p, err := c.entityPath(ont, kind, id)
	if err != nil {
		return nil, err
	}
	var out json.RawMessage
	if err := c.do(ctx, http.MethodGet, p, revQuery(rev), nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// CreateEntity is POST /v1/ontologies/{id}/{kind}: it creates one entity.
// spec is any JSON-encodable value, typically a json.RawMessage.
func (c *Client) CreateEntity(ctx context.Context, ont, kind string, spec any) (*api.UpsertResult, error) {
	p, err := c.entityPath(ont, kind)
	if err != nil {
		return nil, err
	}
	var out api.UpsertResult
	if err := c.do(ctx, http.MethodPost, p, nil, spec, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// PutEntity is PUT /v1/ontologies/{id}/{kind}/{eid}: it upserts one entity.
func (c *Client) PutEntity(ctx context.Context, ont, kind, id string, spec any) (*api.UpsertResult, error) {
	p, err := c.entityPath(ont, kind, id)
	if err != nil {
		return nil, err
	}
	var out api.UpsertResult
	if err := c.do(ctx, http.MethodPut, p, nil, spec, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// UpsertEntities is PUT /v1/ontologies/{id}/{kind} with {"items": [...]}.
func (c *Client) UpsertEntities(ctx context.Context, ont, kind string, items []json.RawMessage) (*api.UpsertResult, error) {
	p, err := c.entityPath(ont, kind)
	if err != nil {
		return nil, err
	}
	if items == nil {
		items = []json.RawMessage{}
	}
	var out api.UpsertResult
	if err := c.do(ctx, http.MethodPut, p, nil, api.Items{Items: items}, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// PatchEntity is PATCH /v1/ontologies/{id}/{kind}/{eid} with a JSON merge
// patch (RFC 7396).
func (c *Client) PatchEntity(ctx context.Context, ont, kind, id string, patch any) (*api.UpsertResult, error) {
	p, err := c.entityPath(ont, kind, id)
	if err != nil {
		return nil, err
	}
	var out api.UpsertResult
	if err := c.do(ctx, http.MethodPatch, p, nil, patch, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// DeleteEntity is DELETE /v1/ontologies/{id}/{kind}/{eid}.
func (c *Client) DeleteEntity(ctx context.Context, ont, kind, id string) error {
	p, err := c.entityPath(ont, kind, id)
	if err != nil {
		return err
	}
	return c.do(ctx, http.MethodDelete, p, nil, nil, nil)
}

// Revisions.

// ListRevisions is GET /v1/ontologies/{id}/revisions.
func (c *Client) ListRevisions(ctx context.Context, ont string) ([]api.Revision, error) {
	var out api.RevisionList
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/revisions", nil, nil, &out); err != nil {
		return nil, err
	}
	if out.Revisions == nil {
		out.Revisions = []api.Revision{}
	}
	return out.Revisions, nil
}

// GetRevision is GET /v1/ontologies/{id}/revisions/{n}.
func (c *Client) GetRevision(ctx context.Context, ont string, n int) (*api.Revision, error) {
	var out api.Revision
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/revisions/"+strconv.Itoa(n), nil, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// CreateRevision is POST /v1/ontologies/{id}/revisions. The server answers
// 422 (Code "invalid", with Issues) when the draft is invalid and 409 when
// it is unchanged since the latest revision, unless req.AllowEmpty is set.
func (c *Client) CreateRevision(ctx context.Context, ont string, req api.CreateRevision) (*api.Revision, error) {
	var out api.Revision
	if err := c.do(ctx, http.MethodPost, "/ontologies/"+esc(ont)+"/revisions", nil, req, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Diff is GET /v1/ontologies/{id}/diff?from=&to=. Empty values use the
// server's defaults.
func (c *Client) Diff(ctx context.Context, ont, from, to string) (*api.Diff, error) {
	q := url.Values{}
	if from != "" {
		q.Set("from", from)
	}
	if to != "" {
		q.Set("to", to)
	}
	var out api.Diff
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/diff", q, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Impact is GET /v1/ontologies/{id}/impact?from=&to=. Empty values use the
// server's defaults (latest, or the empty base, to the draft).
func (c *Client) Impact(ctx context.Context, ont, from, to string) (*model.Impact, error) {
	q := url.Values{}
	if from != "" {
		q.Set("from", from)
	}
	if to != "" {
		q.Set("to", to)
	}
	var out model.Impact
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/impact", q, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Commits.

// ImportCommits is POST /v1/ontologies/{id}/commits: upsert commit metadata.
// It returns every commit of the ontology, oldest first.
func (c *Client) ImportCommits(ctx context.Context, ont string, req api.ImportCommits) (*api.CommitList, error) {
	var out api.CommitList
	if err := c.do(ctx, http.MethodPost, "/ontologies/"+esc(ont)+"/commits", nil, req, &out); err != nil {
		return nil, err
	}
	if out.Commits == nil {
		out.Commits = []api.Commit{}
	}
	return &out, nil
}

// ListCommits is GET /v1/ontologies/{id}/commits, oldest first.
func (c *Client) ListCommits(ctx context.Context, ont string) (*api.CommitList, error) {
	var out api.CommitList
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/commits", nil, nil, &out); err != nil {
		return nil, err
	}
	if out.Commits == nil {
		out.Commits = []api.Commit{}
	}
	return &out, nil
}

// GetCommit is GET /v1/ontologies/{id}/commits/{sha}. sha may be a prefix of
// at least 7 characters; an ambiguous prefix is a 409.
func (c *Client) GetCommit(ctx context.Context, ont, sha string) (*api.CommitDetail, error) {
	var out api.CommitDetail
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/commits/"+esc(sha), nil, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Analysis.

// Validate is POST /v1/ontologies/{id}/validate?rev=.
func (c *Client) Validate(ctx context.Context, ont, rev string) (*api.Validation, error) {
	var out api.Validation
	if err := c.do(ctx, http.MethodPost, "/ontologies/"+esc(ont)+"/validate", revQuery(rev), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Graph is GET /v1/ontologies/{id}/graph?rev=.
func (c *Client) Graph(ctx context.Context, ont, rev string) (*model.Graph, error) {
	var out model.Graph
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/graph", revQuery(rev), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// SourceOptions select the revision and, for a citation in another repo or at
// another commit, its repo and sha.
type SourceOptions struct {
	Rev  string
	Repo string
	SHA  string
}

// Source is GET /v1/ontologies/{id}/source?path=: a file of the code the
// ontology cites, fetched by mosaicd from GitHub at the document's commit.
func (c *Client) Source(ctx context.Context, ont, path string, opts SourceOptions) (*api.SourceFile, error) {
	q := url.Values{"path": {path}}
	for k, v := range map[string]string{"rev": opts.Rev, "repo": opts.Repo, "sha": opts.SHA} {
		if v != "" {
			q.Set(k, v)
		}
	}
	var out api.SourceFile
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/source", q, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Plan is GET /v1/ontologies/{id}/flows/{flow}/plan?rev=.
func (c *Client) Plan(ctx context.Context, ont, flow, rev string) (*model.Plan, error) {
	var out model.Plan
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/flows/"+esc(flow)+"/plan", revQuery(rev), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Simulations.

// RunSimulation is POST /v1/ontologies/{id}/simulations.
func (c *Client) RunSimulation(ctx context.Context, ont string, req api.SimulationRequest) (*api.SimulationRun, error) {
	var out api.SimulationRun
	if err := c.do(ctx, http.MethodPost, "/ontologies/"+esc(ont)+"/simulations", nil, req, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// ListRuns is GET /v1/ontologies/{id}/simulations?limit=. A limit of 0 or
// less uses the server's default.
func (c *Client) ListRuns(ctx context.Context, ont string, limit int) ([]api.SimulationRun, error) {
	q := url.Values{}
	if limit > 0 {
		q.Set("limit", strconv.Itoa(limit))
	}
	var out api.RunList
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/simulations", q, nil, &out); err != nil {
		return nil, err
	}
	if out.Runs == nil {
		out.Runs = []api.SimulationRun{}
	}
	return out.Runs, nil
}

// GetRun is GET /v1/simulations/{run}.
func (c *Client) GetRun(ctx context.Context, id string) (*api.SimulationRun, error) {
	var out api.SimulationRun
	if err := c.do(ctx, http.MethodGet, "/simulations/"+esc(id), nil, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// PutEvidence is PUT /v1/ontologies/{id}/evidence?rev=: it stores evidence on
// a revision (empty rev: the latest).
func (c *Client) PutEvidence(ctx context.Context, ont, rev string, e api.Evidence) (*api.Evidence, error) {
	var out api.Evidence
	if err := c.do(ctx, http.MethodPut, "/ontologies/"+esc(ont)+"/evidence", revQuery(rev), e, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// GetEvidence is GET /v1/ontologies/{id}/evidence?rev=: the evidence in force
// at a revision, which it may inherit from an earlier one. Not found when none
// is stored.
func (c *Client) GetEvidence(ctx context.Context, ont, rev string) (*api.Evidence, error) {
	var out api.Evidence
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/evidence", revQuery(rev), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// TestResults is GET /v1/ontologies/{id}/test-results?rev=: the latest report
// recorded for a revision. Not found when it was never run.
func (c *Client) TestResults(ctx context.Context, ont, rev string) (*api.StoredTestReport, error) {
	var out api.StoredTestReport
	if err := c.do(ctx, http.MethodGet, "/ontologies/"+esc(ont)+"/test-results", revQuery(rev), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Test is POST /v1/ontologies/{id}/test?rev=: it runs every scenario's expectations.
func (c *Client) Test(ctx context.Context, ont, rev string) (*api.TestReport, error) {
	var out api.TestReport
	if err := c.do(ctx, http.MethodPost, "/ontologies/"+esc(ont)+"/test", revQuery(rev), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

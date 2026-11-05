package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"math"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

// Evidence and test reports describe a revision, but a revision's commit is
// immutable and they are usually measured after it is cut, so they can't live
// in the ontology's meta table. They live in main's registry, keyed by
// revision: evidence is committed like commits (it is a record of what was
// measured), and test reports stay in the working set like runs (results, not
// history; Dolt still persists them).

// PutEvidence stores evidence on a revision, replacing what that revision had,
// and returns it. An empty sel means the latest revision. The draft is refused:
// it changes under any measure, so a figure stored on it would mean nothing.
func (s *Store) PutEvidence(ctx context.Context, id, sel string, in api.Evidence) (*api.Evidence, error) {
	if strings.TrimSpace(sel) == "" {
		sel = "latest"
	}
	r, err := s.ResolveRev(ctx, id, sel)
	if err != nil {
		return nil, err
	}
	if r.IsDraft() {
		return nil, errf(CodeBadRequest, "evidence is stored on a revision, not the draft: create a revision first")
	}
	in.Normalize(r.N)
	if issues := in.Validate(r.N); model.HasErrors(issues) {
		return nil, &Error{Code: CodeInvalid, Message: "the evidence does not validate", Issues: issues}
	}
	spec, err := json.Marshal(&in)
	if err != nil {
		return nil, err
	}
	s.regMu.Lock()
	defer s.regMu.Unlock()
	err = s.withConn(ctx, Database, func(c *sql.Conn) error {
		if _, err := c.ExecContext(ctx, "INSERT INTO evidence (ontology_id, revision, spec, updated_at) VALUES (?, ?, ?, ?) "+
			"ON DUPLICATE KEY UPDATE spec = VALUES(spec), updated_at = VALUES(updated_at)", id, r.N, string(spec), s.now()); err != nil {
			return err
		}
		return commitIfDirty(ctx, c, []string{"evidence"}, fmt.Sprintf("Store evidence on %s revision %d", id, r.N))
	})
	if err != nil {
		return nil, err
	}
	return &in, nil
}

// Evidence returns the evidence in force at a revision: its own, or that of the
// newest earlier revision with some (any revision, for the draft). Revision is
// the one asked for, and 0 for the draft; each measure keeps the revision it
// was taken on.
func (s *Store) Evidence(ctx context.Context, id, sel string) (*api.Evidence, error) {
	r, err := s.ResolveRev(ctx, id, sel)
	if err != nil {
		return nil, err
	}
	upTo := r.N
	if r.IsDraft() {
		upTo = math.MaxInt32
	}
	var spec []byte
	err = s.db.QueryRowContext(ctx, "SELECT spec FROM "+Database+".evidence WHERE ontology_id = ? AND revision <= ? "+
		"ORDER BY revision DESC LIMIT 1", id, upTo).Scan(&spec)
	if isNotFound(err) {
		if r.IsDraft() {
			return nil, errf(CodeNotFound, "ontology %q has no evidence", id)
		}
		return nil, errf(CodeNotFound, "ontology %q has no evidence at or before revision %d", id, r.N)
	}
	if err != nil {
		return nil, err
	}
	var out api.Evidence
	if err := json.Unmarshal(spec, &out); err != nil {
		return nil, fmt.Errorf("evidence of %s: %w", id, err)
	}
	out.Revision = r.N
	return &out, nil
}

// SaveTestReport records a report as its revision's latest (rep.Revision is
// "draft" or a number). Reports hold each scenario's outcome and assertions,
// never a trace.
func (s *Store) SaveTestReport(ctx context.Context, id string, rep *api.TestReport) error {
	b, err := json.Marshal(rep)
	if err != nil {
		return err
	}
	s.regMu.Lock()
	defer s.regMu.Unlock()
	_, err = s.db.ExecContext(ctx, "INSERT INTO "+Database+".test_reports (ontology_id, revision, report, ran_at) VALUES (?, ?, ?, ?) "+
		"ON DUPLICATE KEY UPDATE report = VALUES(report), ran_at = VALUES(ran_at)", id, rep.Revision, string(b), s.now())
	return err
}

// TestResults returns the latest report recorded for exactly this revision.
// Unlike evidence it isn't inherited: a test result is about one model.
func (s *Store) TestResults(ctx context.Context, id string, r Rev) (*api.StoredTestReport, error) {
	var out api.StoredTestReport
	var report []byte
	err := s.db.QueryRowContext(ctx, "SELECT report, ran_at FROM "+Database+".test_reports WHERE ontology_id = ? AND revision = ?",
		id, r.String()).Scan(&report, &out.RanAt)
	if isNotFound(err) {
		return nil, errf(CodeNotFound, "ontology %q has no test report for revision %s", id, r)
	}
	if err != nil {
		return nil, err
	}
	if err := decodeLoose(report, &out.TestReport); err != nil {
		return nil, fmt.Errorf("test report of %s: %w", id, err)
	}
	out.RanAt = out.RanAt.UTC()
	return &out, nil
}

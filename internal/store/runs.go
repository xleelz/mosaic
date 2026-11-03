package store

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"

	"github.com/xleelz/mosaic/pkg/api"
)

// SaveRun stores a simulation run in main's working set. Runs are results,
// not history, so they are never committed (Dolt still persists them).
func (s *Store) SaveRun(ctx context.Context, run *api.SimulationRun) error {
	req, err := json.Marshal(run.Request)
	if err != nil {
		return err
	}
	sum, err := json.Marshal(run.Summary)
	if err != nil {
		return err
	}
	trace, err := json.Marshal(run.Trace)
	if err != nil {
		return err
	}
	s.regMu.Lock()
	defer s.regMu.Unlock()
	_, err = s.db.ExecContext(ctx, "INSERT INTO "+Database+".simulation_runs "+
		"(id, ontology_id, revision, flow_id, scenario_id, request, summary, trace, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
		run.ID, run.Ontology, run.Revision, run.Flow, run.Scenario, string(req), string(sum), string(trace), run.CreatedAt)
	return err
}

const runColumns = "id, ontology_id, revision, flow_id, scenario_id, request, summary, created_at"

func scanRun(sc interface{ Scan(...any) error }, extra ...any) (*api.SimulationRun, error) {
	var r api.SimulationRun
	var req, sum []byte
	dest := append([]any{&r.ID, &r.Ontology, &r.Revision, &r.Flow, &r.Scenario, &req, &sum, &r.CreatedAt}, extra...)
	if err := sc.Scan(dest...); err != nil {
		return nil, err
	}
	if err := decodeLoose(req, &r.Request); err != nil {
		return nil, fmt.Errorf("run %s: request: %w", r.ID, err)
	}
	if err := decodeLoose(sum, &r.Summary); err != nil {
		return nil, fmt.Errorf("run %s: summary: %w", r.ID, err)
	}
	return &r, nil
}

// decodeLoose keeps numbers as written (json.Number) without refusing fields
// older versions may have stored.
func decodeLoose(b []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	return dec.Decode(v)
}

// ListRuns returns an ontology's runs, newest first, without traces.
func (s *Store) ListRuns(ctx context.Context, id string, limit int) ([]api.SimulationRun, error) {
	if err := s.Exists(ctx, id); err != nil {
		return nil, err
	}
	if limit <= 0 {
		limit = 100
	}
	rows, err := s.db.QueryContext(ctx, "SELECT "+runColumns+" FROM "+Database+".simulation_runs WHERE ontology_id = ? "+
		"ORDER BY created_at DESC, id DESC LIMIT ?", id, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []api.SimulationRun{}
	for rows.Next() {
		r, err := scanRun(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *r)
	}
	return out, rows.Err()
}

// GetRun returns a run with its trace.
func (s *Store) GetRun(ctx context.Context, runID string) (*api.SimulationRun, error) {
	var trace []byte
	r, err := scanRun(s.db.QueryRowContext(ctx, "SELECT "+runColumns+", trace FROM "+Database+".simulation_runs WHERE id = ?", runID), &trace)
	if err == sql.ErrNoRows {
		return nil, errf(CodeNotFound, "run %q not found", runID)
	}
	if err != nil {
		return nil, err
	}
	if err := decodeLoose(trace, &r.Trace); err != nil {
		return nil, fmt.Errorf("run %s: trace: %w", r.ID, err)
	}
	return r, nil
}

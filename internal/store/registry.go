package store

import (
	"context"
	"database/sql"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

// ontologyRow is a registry row.
type ontologyRow struct {
	ID, Name, Description string
	CreatedAt, UpdatedAt  time.Time
}

func (s *Store) getRow(ctx context.Context, id string) (ontologyRow, error) {
	var r ontologyRow
	if !model.ValidID(id) {
		return r, errf(CodeNotFound, "ontology %q not found", id)
	}
	err := s.db.QueryRowContext(ctx, "SELECT id, name, description, created_at, updated_at FROM "+Database+".ontologies WHERE id = ?", id).
		Scan(&r.ID, &r.Name, &r.Description, &r.CreatedAt, &r.UpdatedAt)
	if isNotFound(err) {
		return r, errf(CodeNotFound, "ontology %q not found", id)
	}
	return r, err
}

// Exists returns a not_found error unless the ontology exists.
func (s *Store) Exists(ctx context.Context, id string) error {
	_, err := s.getRow(ctx, id)
	return err
}

// revisionNumbers returns each ontology's revision numbers, ascending, from
// the ont/<id>/r<N> tags; with id set, only that ontology's.
func (s *Store) revisionNumbers(ctx context.Context, id string) (map[string][]int, error) {
	prefix := "ont/"
	if id != "" {
		prefix = branchName(id) + "/r"
	}
	rows, err := s.db.QueryContext(ctx, "SELECT tag_name FROM "+Database+".dolt_tags WHERE tag_name LIKE ?", likePrefix(prefix))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string][]int{}
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		if ont, n, ok := parseTag(name); ok && (id == "" || ont == id) {
			out[ont] = append(out[ont], n)
		}
	}
	for _, ns := range out {
		sort.Ints(ns)
	}
	return out, rows.Err()
}

// parseTag splits "ont/<id>/r<N>".
func parseTag(name string) (string, int, bool) {
	rest, ok := strings.CutPrefix(name, "ont/")
	if !ok {
		return "", 0, false
	}
	i := strings.LastIndex(rest, "/r")
	if i <= 0 {
		return "", 0, false
	}
	n, err := strconv.Atoi(rest[i+2:])
	if err != nil || n < 1 || strconv.Itoa(n) != rest[i+2:] {
		return "", 0, false
	}
	return rest[:i], n, true
}

func likePrefix(p string) string {
	r := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`)
	return r.Replace(p) + "%"
}

func summary(r ontologyRow, revs []int) api.OntologySummary {
	o := api.OntologySummary{ID: r.ID, Name: r.Name, Description: r.Description, CreatedAt: r.CreatedAt, UpdatedAt: r.UpdatedAt, RevisionCount: len(revs)}
	if len(revs) > 0 {
		o.LatestRevision = revs[len(revs)-1]
	}
	return o
}

// ListOntologies returns every ontology, ordered by id.
func (s *Store) ListOntologies(ctx context.Context) ([]api.OntologySummary, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT id, name, description, created_at, updated_at FROM "+Database+".ontologies ORDER BY id")
	if err != nil {
		return nil, err
	}
	var list []ontologyRow
	for rows.Next() {
		var r ontologyRow
		if err := rows.Scan(&r.ID, &r.Name, &r.Description, &r.CreatedAt, &r.UpdatedAt); err != nil {
			rows.Close()
			return nil, err
		}
		list = append(list, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	revs, err := s.revisionNumbers(ctx, "")
	if err != nil {
		return nil, err
	}
	out := make([]api.OntologySummary, 0, len(list))
	for _, r := range list {
		out = append(out, summary(r, revs[r.ID]))
	}
	return out, nil
}

// GetOntology returns the summary plus draft counts and dirtiness.
func (s *Store) GetOntology(ctx context.Context, id string) (*api.OntologyDetail, error) {
	r, err := s.getRow(ctx, id)
	if err != nil {
		return nil, err
	}
	revs, err := s.revisionNumbers(ctx, id)
	if err != nil {
		return nil, err
	}
	counts, err := s.counts(ctx, id)
	if err != nil {
		return nil, err
	}
	dirty, err := s.dirty(ctx, id)
	if err != nil {
		return nil, err
	}
	out := &api.OntologyDetail{OntologySummary: summary(r, revs[id]), Counts: counts, DraftDirty: dirty}
	if err := s.draftHierarchy(ctx, id, out); err != nil {
		return nil, err
	}
	return out, nil
}

// counts returns the draft's entity count per kind, every kind included.
func (s *Store) counts(ctx context.Context, id string) (map[string]int, error) {
	out := map[string]int{}
	for _, k := range model.Kinds {
		out[k] = 0
	}
	rows, err := s.db.QueryContext(ctx, "SELECT kind, COUNT(*) FROM "+table(id, "entities")+" GROUP BY kind")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var k string
		var n int
		if err := rows.Scan(&k, &n); err != nil {
			return nil, err
		}
		out[k] = n
	}
	return out, rows.Err()
}

// dirty reports whether the draft differs from the branch head.
func (s *Store) dirty(ctx context.Context, id string) (bool, error) {
	var n int
	err := s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM "+table(id, "dolt_status")).Scan(&n)
	return n > 0, err
}

// commitRegistry stages and commits the ontologies table on main. The caller
// holds regMu and has already written the change through c.
func commitRegistry(ctx context.Context, c *sql.Conn, msg string) error {
	return commitIfDirty(ctx, c, []string{"ontologies"}, msg)
}

// CreateOntology registers an ontology and creates its branch from ontology-base.
func (s *Store) CreateOntology(ctx context.Context, in api.CreateOntology) (*api.OntologyDetail, error) {
	if !model.ValidID(in.ID) {
		return nil, errf(CodeBadRequest, "invalid ontology id %q: use [a-z0-9][a-z0-9_-]{0,63}", in.ID)
	}
	name := strings.TrimSpace(in.Name)
	if name == "" {
		name = in.ID
	}
	if len(name) > 255 {
		return nil, errf(CodeBadRequest, "name is longer than 255 characters")
	}
	unlock := s.lock(in.ID)
	defer unlock()
	s.regMu.Lock()
	defer s.regMu.Unlock()
	if _, err := s.getRow(ctx, in.ID); err == nil {
		return nil, errf(CodeConflict, "ontology %q already exists", in.ID)
	} else if !isCode(err, CodeNotFound) {
		return nil, err
	}
	err := s.withConn(ctx, Database, func(c *sql.Conn) error {
		// A branch without a registry row is left over from an interrupted
		// create or delete; it holds nothing anyone can reach, so drop it.
		if err := dropBranchAndTags(ctx, c, in.ID); err != nil {
			return err
		}
		// Likewise for commits left by an interrupted delete.
		if _, err := c.ExecContext(ctx, "DELETE FROM commits WHERE ontology_id = ?", in.ID); err != nil {
			return err
		}
		if _, err := c.ExecContext(ctx, "CALL dolt_branch(?, ?)", branchName(in.ID), BaseBranch); err != nil {
			return err
		}
		now := s.now()
		if _, err := c.ExecContext(ctx, "INSERT INTO ontologies (id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
			in.ID, name, in.Description, now, now); err != nil {
			_, _ = c.ExecContext(ctx, "CALL dolt_branch('-D', ?)", branchName(in.ID))
			return err
		}
		return commitIfDirty(ctx, c, []string{"ontologies", "commits"}, "Create ontology "+in.ID)
	})
	if err != nil {
		return nil, err
	}
	return s.GetOntology(ctx, in.ID)
}

// UpdateOntology renames an ontology or changes its description.
func (s *Store) UpdateOntology(ctx context.Context, id string, in api.UpdateOntology) (*api.OntologyDetail, error) {
	s.regMu.Lock()
	r, err := s.getRow(ctx, id)
	if err != nil {
		s.regMu.Unlock()
		return nil, err
	}
	if in.Name != nil {
		r.Name = strings.TrimSpace(*in.Name)
		if r.Name == "" {
			s.regMu.Unlock()
			return nil, errf(CodeBadRequest, "name must not be empty")
		}
		if len(r.Name) > 255 {
			s.regMu.Unlock()
			return nil, errf(CodeBadRequest, "name is longer than 255 characters")
		}
	}
	if in.Description != nil {
		r.Description = *in.Description
	}
	err = s.withConn(ctx, Database, func(c *sql.Conn) error {
		if _, err := c.ExecContext(ctx, "UPDATE ontologies SET name = ?, description = ?, updated_at = ? WHERE id = ?",
			r.Name, r.Description, s.now(), id); err != nil {
			return err
		}
		return commitRegistry(ctx, c, "Update ontology "+id)
	})
	s.regMu.Unlock()
	if err != nil {
		return nil, err
	}
	return s.GetOntology(ctx, id)
}

// DeleteOntology drops an ontology's tags, branch, runs, commits and registry row.
func (s *Store) DeleteOntology(ctx context.Context, id string) error {
	unlock := s.lock(id)
	defer unlock()
	s.regMu.Lock()
	defer s.regMu.Unlock()
	if _, err := s.getRow(ctx, id); err != nil {
		return err
	}
	return s.withConn(ctx, Database, func(c *sql.Conn) error {
		if err := dropBranchAndTags(ctx, c, id); err != nil {
			return err
		}
		if _, err := c.ExecContext(ctx, "DELETE FROM simulation_runs WHERE ontology_id = ?", id); err != nil {
			return err
		}
		if _, err := c.ExecContext(ctx, "DELETE FROM commits WHERE ontology_id = ?", id); err != nil {
			return err
		}
		if _, err := c.ExecContext(ctx, "DELETE FROM ontologies WHERE id = ?", id); err != nil {
			return err
		}
		return commitIfDirty(ctx, c, []string{"ontologies", "commits"}, "Delete ontology "+id)
	})
}

// dropBranchAndTags deletes ont/<id> and its revision tags, if present.
func dropBranchAndTags(ctx context.Context, c *sql.Conn, id string) error {
	rows, err := c.QueryContext(ctx, "SELECT tag_name FROM dolt_tags WHERE tag_name LIKE ?", likePrefix(branchName(id)+"/r"))
	if err != nil {
		return err
	}
	var tags []string
	for rows.Next() {
		var t string
		if err := rows.Scan(&t); err != nil {
			rows.Close()
			return err
		}
		if ont, _, ok := parseTag(t); ok && ont == id {
			tags = append(tags, t)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, t := range tags {
		if _, err := c.ExecContext(ctx, "CALL dolt_tag('-d', ?)", t); err != nil {
			return fmt.Errorf("delete tag %s: %w", t, err)
		}
	}
	var n int
	if err := c.QueryRowContext(ctx, "SELECT COUNT(*) FROM dolt_branches WHERE name = ?", branchName(id)).Scan(&n); err != nil {
		return err
	}
	if n > 0 {
		if _, err := c.ExecContext(ctx, "CALL dolt_branch('-D', ?)", branchName(id)); err != nil {
			return fmt.Errorf("delete branch %s: %w", branchName(id), err)
		}
	}
	return nil
}

func isCode(err error, code string) bool {
	e, ok := err.(*Error)
	return ok && e.Code == code
}

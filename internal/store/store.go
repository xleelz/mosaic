// Package store persists ontologies in Dolt (docs/DESIGN.md §1).
//
// Everything lives in one database, `mosaic`:
//
//   - branch main holds the registry: `ontologies`, `commits` and `evidence`
//     (committed on every change) and `simulation_runs` and `test_reports`
//     (left in the working set, never committed);
//   - branch ontology-base holds the empty `entities` and `meta` tables;
//   - branch ont/<id> holds one ontology. Its working set is the draft, and
//     revision N is a commit tagged ont/<id>/r<N>. Sessions reach the branch as
//     the revision database `mosaic/ont/<id>`.
package store

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/xleelz/mosaic/internal/impact"
	"github.com/xleelz/mosaic/internal/model"
)

// Names of the database and its fixed branches.
const (
	Database   = "mosaic"
	BaseBranch = "ontology-base"
)

// DefaultAuthor signs commits when a request names no author.
const DefaultAuthor = "Mosaic <mosaic@localhost>"

// Error codes, matching the API's error codes.
const (
	CodeBadRequest = "bad_request"
	CodeNotFound   = "not_found"
	CodeConflict   = "conflict"
	CodeInvalid    = "invalid"
)

// Error is a refusal the caller can act on; anything else is internal.
type Error struct {
	Code    string
	Message string
	Issues  []model.Issue
}

func (e *Error) Error() string { return e.Message }

func errf(code, format string, a ...any) *Error {
	return &Error{Code: code, Message: fmt.Sprintf(format, a...)}
}

// Store is the Dolt-backed ontology store.
type Store struct {
	db    *sql.DB
	now   func() time.Time
	regMu sync.Mutex // serializes writes to branch main (registry commits and runs)

	mu    sync.Mutex
	locks map[string]*sync.Mutex // one per ontology: draft writes and revisions

	impact *impact.Cache // exercised reach per immutable revision
}

// Open initializes the schema when needed and returns a store.
func Open(ctx context.Context, db *sql.DB) (*Store, error) {
	s := &Store{db: db, now: func() time.Time { return time.Now().UTC().Truncate(time.Microsecond) }, locks: map[string]*sync.Mutex{},
		impact: impact.NewCache(impact.DefaultCacheSize)}
	if err := s.init(ctx); err != nil {
		return nil, fmt.Errorf("initialize store: %w", err)
	}
	return s, nil
}

// DB returns the underlying pool.
func (s *Store) DB() *sql.DB { return s.db }

func (s *Store) lock(id string) func() {
	s.mu.Lock()
	m, ok := s.locks[id]
	if !ok {
		m = &sync.Mutex{}
		s.locks[id] = m
	}
	s.mu.Unlock()
	m.Lock()
	return m.Unlock
}

// branchName is the ontology's branch; dbName is its revision database.
func branchName(id string) string { return "ont/" + id }
func dbName(id string) string     { return Database + "/" + branchName(id) }
func tagName(id string, n int) string {
	return fmt.Sprintf("%s/r%d", branchName(id), n)
}

// table qualifies an ontology table, e.g. `mosaic/ont/x`.entities. Ontology
// ids are slugs, so they never contain a backtick.
func table(id, name string) string { return "`" + dbName(id) + "`." + name }

// withConn runs fn on a dedicated session whose current database is dbname.
// Dolt procedures act on the session's database, so commits, tags, branches
// and dolt_diff against WORKING go through here. The session is moved back to
// `mosaic` before it returns to the pool, or discarded if that fails.
func (s *Store) withConn(ctx context.Context, dbname string, fn func(*sql.Conn) error) error {
	conn, err := s.db.Conn(ctx)
	if err != nil {
		return err
	}
	defer conn.Close()
	if _, err := conn.ExecContext(ctx, "USE `"+dbname+"`"); err != nil {
		_ = conn.Raw(func(any) error { return driver.ErrBadConn })
		return err
	}
	ferr := fn(conn)
	if dbname != Database {
		if _, err := conn.ExecContext(context.WithoutCancel(ctx), "USE `"+Database+"`"); err != nil {
			_ = conn.Raw(func(any) error { return driver.ErrBadConn })
		}
	}
	return ferr
}

const (
	ddlEntities = "CREATE TABLE IF NOT EXISTS entities (" +
		"kind VARCHAR(32) NOT NULL, id VARCHAR(160) NOT NULL, spec JSON NOT NULL, " +
		"updated_at DATETIME(6) NOT NULL, PRIMARY KEY (kind, id))"
	ddlMeta       = "CREATE TABLE IF NOT EXISTS meta (k VARCHAR(64) NOT NULL PRIMARY KEY, v JSON)"
	ddlOntologies = "CREATE TABLE IF NOT EXISTS ontologies (" +
		"id VARCHAR(64) NOT NULL PRIMARY KEY, name VARCHAR(255) NOT NULL, description TEXT NOT NULL, " +
		"created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL)"
	ddlRuns = "CREATE TABLE IF NOT EXISTS simulation_runs (" +
		"id VARCHAR(64) NOT NULL PRIMARY KEY, ontology_id VARCHAR(64) NOT NULL, revision VARCHAR(16) NOT NULL, " +
		"flow_id VARCHAR(160) NOT NULL, scenario_id VARCHAR(160) NOT NULL, request JSON NOT NULL, " +
		"summary JSON NOT NULL, trace LONGTEXT NOT NULL, created_at DATETIME(6) NOT NULL, " +
		"INDEX runs_by_ontology (ontology_id, created_at))"
	ddlCommits = "CREATE TABLE IF NOT EXISTS commits (" +
		"ontology_id VARCHAR(64) NOT NULL, sha VARCHAR(64) NOT NULL, parent VARCHAR(64) NOT NULL, " +
		"subject TEXT NOT NULL, author VARCHAR(512) NOT NULL, date DATETIME(6) NOT NULL, files JSON NOT NULL, " +
		"repo VARCHAR(1024) NOT NULL, seq BIGINT NOT NULL, url VARCHAR(2048) NOT NULL DEFAULT '', " +
		"PRIMARY KEY (ontology_id, sha))"
	ddlEvidence = "CREATE TABLE IF NOT EXISTS evidence (" +
		"ontology_id VARCHAR(64) NOT NULL, revision INT NOT NULL, spec LONGTEXT NOT NULL, updated_at DATETIME(6) NOT NULL, " +
		"PRIMARY KEY (ontology_id, revision))"
	ddlTestReports = "CREATE TABLE IF NOT EXISTS test_reports (" +
		"ontology_id VARCHAR(64) NOT NULL, revision VARCHAR(16) NOT NULL, report LONGTEXT NOT NULL, ran_at DATETIME(6) NOT NULL, " +
		"PRIMARY KEY (ontology_id, revision))"
)

// init creates the database, the ontology-base branch and the registry
// tables. It is idempotent and runs at every start.
func (s *Store) init(ctx context.Context) error {
	if _, err := s.db.ExecContext(ctx, "CREATE DATABASE IF NOT EXISTS "+Database); err != nil {
		return err
	}
	return s.withConn(ctx, Database, func(c *sql.Conn) error {
		var n int
		if err := c.QueryRowContext(ctx, "SELECT COUNT(*) FROM dolt_branches WHERE name = ?", BaseBranch).Scan(&n); err != nil {
			return err
		}
		if n == 0 {
			// Branch before the registry tables exist on main, so the base holds
			// only ontology tables (the drops cover a half-finished first start).
			if _, err := c.ExecContext(ctx, "CALL dolt_branch(?, 'main')", BaseBranch); err != nil {
				return err
			}
		}
		if err := s.withConn(ctx, Database+"/"+BaseBranch, func(b *sql.Conn) error {
			for _, q := range []string{"DROP TABLE IF EXISTS simulation_runs", "DROP TABLE IF EXISTS ontologies", "DROP TABLE IF EXISTS commits", "DROP TABLE IF EXISTS evidence", "DROP TABLE IF EXISTS test_reports", ddlEntities, ddlMeta} {
				if _, err := b.ExecContext(ctx, q); err != nil {
					return err
				}
			}
			return commitIfDirty(ctx, b, nil, "Ontology base schema")
		}); err != nil {
			return err
		}
		for _, q := range []string{ddlOntologies, ddlRuns, ddlCommits, ddlEvidence, ddlTestReports} {
			if _, err := c.ExecContext(ctx, q); err != nil {
				return err
			}
		}
		// Migrate a commits table created before it had a url column.
		var hasURL int
		if err := c.QueryRowContext(ctx, "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = ? AND table_name = 'commits' AND column_name = 'url'", Database).Scan(&hasURL); err != nil {
			return err
		}
		if hasURL == 0 {
			if _, err := c.ExecContext(ctx, "ALTER TABLE commits ADD COLUMN url VARCHAR(2048) NOT NULL DEFAULT ''"); err != nil {
				return err
			}
			if err := commitIfDirty(ctx, c, []string{"commits"}, "Add commits.url"); err != nil {
				return err
			}
		}
		// Commit the registry tables' creation only; run rows stay uncommitted.
		rows, err := c.QueryContext(ctx, "SELECT table_name FROM dolt_status WHERE status = 'new table'")
		if err != nil {
			return err
		}
		var fresh []string
		for rows.Next() {
			var t string
			if err := rows.Scan(&t); err != nil {
				rows.Close()
				return err
			}
			fresh = append(fresh, t)
		}
		rows.Close()
		if len(fresh) == 0 {
			return nil
		}
		return commitIfDirty(ctx, c, fresh, "Registry schema")
	})
}

// commitIfDirty stages tables (all when nil) and commits them, doing nothing
// when there is nothing to commit.
func commitIfDirty(ctx context.Context, c *sql.Conn, tables []string, msg string) error {
	if tables == nil {
		var n int
		if err := c.QueryRowContext(ctx, "SELECT COUNT(*) FROM dolt_status").Scan(&n); err != nil {
			return err
		}
		if n == 0 {
			return nil
		}
		tables = []string{"-A"}
	}
	for _, t := range tables {
		if _, err := c.ExecContext(ctx, "CALL dolt_add(?)", t); err != nil {
			return err
		}
	}
	if _, err := c.ExecContext(ctx, "CALL dolt_commit('-m', ?, '--author', ?)", msg, DefaultAuthor); err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "nothing to commit") {
			return nil
		}
		return err
	}
	return nil
}

// normalizeAuthor turns "Name" into "Name <mosaic@localhost>"; Dolt needs both.
func normalizeAuthor(a string) string {
	a = strings.TrimSpace(a)
	switch {
	case a == "":
		return DefaultAuthor
	case strings.Contains(a, "<") && strings.HasSuffix(a, ">"):
		return a
	}
	return a + " <mosaic@localhost>"
}

// isNotFound tells sql.ErrNoRows apart from real failures.
func isNotFound(err error) bool { return errors.Is(err, sql.ErrNoRows) }

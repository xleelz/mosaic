package store

import (
	"bytes"
	"context"
	"database/sql"
	"sort"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

type commitInfo struct {
	hash, author, message string
	date                  time.Time
}

// commits returns the ontology branch's commits by hash.
func (s *Store) commits(ctx context.Context, id string) (map[string]commitInfo, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT commit_hash, committer, email, date, message FROM "+table(id, "dolt_log"))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]commitInfo{}
	for rows.Next() {
		var c commitInfo
		var name, email string
		if err := rows.Scan(&c.hash, &name, &email, &c.date, &c.message); err != nil {
			return nil, err
		}
		c.author = name + " <" + email + ">"
		out[c.hash] = c
	}
	return out, rows.Err()
}

// Revisions lists an ontology's revisions in ascending order. Metadata comes
// from each tag's commit.
func (s *Store) Revisions(ctx context.Context, id string) ([]api.Revision, error) {
	if err := s.Exists(ctx, id); err != nil {
		return nil, err
	}
	rows, err := s.db.QueryContext(ctx, "SELECT tag_name, tag_hash, date, message FROM "+Database+".dolt_tags WHERE tag_name LIKE ?", likePrefix(branchName(id)+"/r"))
	if err != nil {
		return nil, err
	}
	var revs []api.Revision
	for rows.Next() {
		var name, tagMsg string
		var r api.Revision
		if err := rows.Scan(&name, &r.Hash, &r.CreatedAt, &tagMsg); err != nil {
			rows.Close()
			return nil, err
		}
		ont, n, ok := parseTag(name)
		if !ok || ont != id {
			continue
		}
		r.Number = n
		r.Message, r.Source = splitTagMessage(tagMsg)
		revs = append(revs, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	commits, err := s.commits(ctx, id)
	if err != nil {
		return nil, err
	}
	for i := range revs {
		if c, ok := commits[revs[i].Hash]; ok {
			revs[i].Author, revs[i].Message, revs[i].CreatedAt = c.author, c.message, c.date
		}
	}
	sortRevisions(revs)
	if revs == nil {
		revs = []api.Revision{}
	}
	return revs, nil
}

func sortRevisions(r []api.Revision) {
	sort.Slice(r, func(a, b int) bool { return r[a].Number < r[b].Number })
}

// Revision returns one revision's metadata; sel is N, rN or latest.
func (s *Store) Revision(ctx context.Context, id, sel string) (*api.Revision, error) {
	r, err := s.ResolveRev(ctx, id, sel)
	if err != nil {
		return nil, err
	}
	if r.IsDraft() {
		return nil, errf(CodeBadRequest, "the draft is not a revision")
	}
	revs, err := s.Revisions(ctx, id)
	if err != nil {
		return nil, err
	}
	for i := range revs {
		if revs[i].Number == r.N {
			return &revs[i], nil
		}
	}
	return nil, errf(CodeNotFound, "ontology %q has no revision %d", id, r.N)
}

// CreateRevision validates the draft and records it as the next revision: a
// commit on ont/<id> tagged ont/<id>/r<N>. An unchanged draft is a conflict,
// an invalid one is refused with its issues.
func (s *Store) CreateRevision(ctx context.Context, id string, in api.CreateRevision) (*api.Revision, error) {
	if err := s.Exists(ctx, id); err != nil {
		return nil, err
	}
	unlock := s.lock(id)
	defer unlock()
	if err := s.Exists(ctx, id); err != nil {
		return nil, err
	}
	revs, err := s.revisionNumbers(ctx, id)
	if err != nil {
		return nil, err
	}
	ns := revs[id]
	latest := 0
	if len(ns) > 0 {
		latest = ns[len(ns)-1]
	}
	src, err := normalizeSource(in.Source)
	if err != nil {
		return nil, err
	}
	dirty, err := s.dirty(ctx, id)
	if err != nil {
		return nil, err
	}
	if !dirty {
		if latest == 0 {
			return nil, errf(CodeConflict, "the draft is empty and there are no revisions yet")
		}
		if !in.AllowEmpty {
			return nil, errf(CodeConflict, "the draft has no changes since revision %d", latest)
		}
	}
	doc, decodeIssues, err := s.Document(ctx, id, Draft)
	if err != nil {
		return nil, err
	}
	if latest == 0 && len(doc.Components)+len(doc.Interfaces)+len(doc.Links)+len(doc.Schemas)+len(doc.Flows)+len(doc.Scenarios)+len(doc.Configs)+len(doc.Fixtures)+len(decodeIssues) == 0 {
		return nil, errf(CodeConflict, "the draft is empty and there are no revisions yet")
	}
	vi, err := s.validateLinked(ctx, doc)
	if err != nil {
		return nil, err
	}
	issues := append(decodeIssues, vi...)
	if model.HasErrors(issues) {
		return nil, &Error{Code: CodeInvalid, Message: "the draft does not validate", Issues: issues}
	}
	n := latest + 1
	msg := strings.TrimSpace(in.Message)
	if msg == "" {
		msg = "Revision " + itoa(n)
	}
	author := normalizeAuthor(in.Author)
	var rev api.Revision
	err = s.withConn(ctx, dbName(id), func(c *sql.Conn) error {
		commit := "CALL dolt_commit('-Am', ?, '--author', ?)"
		if !dirty {
			commit = "CALL dolt_commit('-Am', ?, '--author', ?, '--allow-empty')"
		}
		if _, err := c.ExecContext(ctx, commit, msg, author); err != nil {
			return err
		}
		if _, err := c.ExecContext(ctx, "CALL dolt_tag('-m', ?, ?, 'HEAD')", tagMessage(msg, src), tagName(id, n)); err != nil {
			return err
		}
		var name, email string
		if err := c.QueryRowContext(ctx, "SELECT commit_hash, committer, email, date, message FROM dolt_log LIMIT 1").
			Scan(&rev.Hash, &name, &email, &rev.CreatedAt, &rev.Message); err != nil {
			return err
		}
		rev.Number, rev.Author, rev.Source = n, name+" <"+email+">", src
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &rev, nil
}

func itoa(n int) string { return Rev{N: n}.String() }

// Diff lists entity changes between two selectors. An empty from means the
// latest revision (the empty base when there is none); an empty to means the
// draft.
func (s *Store) Diff(ctx context.Context, id, from, to string) (*api.Diff, error) {
	if err := s.Exists(ctx, id); err != nil {
		return nil, err
	}
	fromRef, fromName := BaseBranch, "base"
	if from == "" {
		revs, err := s.revisionNumbers(ctx, id)
		if err != nil {
			return nil, err
		}
		if ns := revs[id]; len(ns) > 0 {
			from = "latest"
		}
	}
	if from == "base" {
		from = "" // the empty ontology every branch starts from
	} else if from != "" {
		r, err := s.resolveRev(ctx, id, from)
		if err != nil {
			return nil, err
		}
		fromRef, fromName = s.ref(id, r), r.String()
	}
	tr, err := s.resolveRev(ctx, id, to)
	if err != nil {
		return nil, err
	}
	toRef := s.ref(id, tr)
	changes, err := s.diffRefs(ctx, id, fromRef, toRef)
	if err != nil {
		return nil, err
	}
	return &api.Diff{From: fromName, To: tr.String(), Changes: changes}, nil
}

// revRef is the Dolt ref of revision n, or of the empty base when n is 0.
func revRef(id string, n int) string {
	if n == 0 {
		return BaseBranch
	}
	return tagName(id, n)
}

// diffRefs lists entity changes between two refs built by the store (tags,
// the base branch or WORKING), sorted by kind and id.
func (s *Store) diffRefs(ctx context.Context, id, fromRef, toRef string) ([]api.Change, error) {
	out := &api.Diff{Changes: []api.Change{}}
	if fromRef == toRef {
		return out.Changes, nil
	}
	err := s.withConn(ctx, dbName(id), func(c *sql.Conn) error {
		// The refs are built here from slugs and numbers, never from raw input.
		rows, err := c.QueryContext(ctx, "SELECT diff_type, from_kind, from_id, from_spec, to_kind, to_id, to_spec FROM dolt_diff('"+
			fromRef+"', '"+toRef+"', 'entities')")
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var typ string
			var fk, fid, tk, tid sql.NullString
			var fspec, tspec []byte
			if err := rows.Scan(&typ, &fk, &fid, &fspec, &tk, &tid, &tspec); err != nil {
				return err
			}
			ch := api.Change{Change: typ}
			if fk.Valid {
				ch.Kind, ch.ID = fk.String, fid.String
				ch.Before = canonical(fk.String, fspec)
			}
			if tk.Valid {
				ch.Kind, ch.ID = tk.String, tid.String
				ch.After = canonical(tk.String, tspec)
			}
			if typ == "modified" && bytes.Equal(ch.Before, ch.After) {
				continue // only updated_at changed
			}
			out.Changes = append(out.Changes, ch)
		}
		return rows.Err()
	})
	if err != nil {
		return nil, err
	}
	sortChanges(out.Changes)
	return out.Changes, nil
}

func (s *Store) ref(id string, r Rev) string {
	if r.IsDraft() {
		return "WORKING"
	}
	return tagName(id, r.N)
}

func sortChanges(cs []api.Change) {
	order := map[string]int{}
	for i, k := range model.Kinds {
		order[k] = i
	}
	sort.Slice(cs, func(a, b int) bool {
		if cs[a].Kind != cs[b].Kind {
			return order[cs[a].Kind] < order[cs[b].Kind]
		}
		return cs[a].ID < cs[b].ID
	})
}

package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

// A revision's source (the code commit it models) is kept in its tag's
// message, after the revision message, as a trailer line:
//
//	<message>
//
//	Mosaic-Source: {"repo":...,"sha":...}
//
// Tags are immutable and live with the revision, so the source survives
// restarts and is deleted with the ontology's tags.
const sourceTrailer = "\n\nMosaic-Source: "

func tagMessage(msg string, src *api.CommitSource) string {
	if src == nil {
		return msg
	}
	b, err := json.Marshal(src)
	if err != nil {
		return msg
	}
	return msg + sourceTrailer + string(b)
}

// splitTagMessage separates a tag message into the revision message and its
// source, if any.
func splitTagMessage(m string) (string, *api.CommitSource) {
	i := strings.LastIndex(m, sourceTrailer)
	if i < 0 {
		return m, nil
	}
	var src api.CommitSource
	if err := json.Unmarshal([]byte(strings.TrimSpace(m[i+len(sourceTrailer):])), &src); err != nil || src.SHA == "" {
		return m, nil
	}
	return m[:i], &src
}

// isHex reports whether s is lowercase hexadecimal.
func isHex(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if (r < '0' || r > '9') && (r < 'a' || r > 'f') {
			return false
		}
	}
	return true
}

// fullSHA normalizes a full commit hash (40 hex for SHA-1, 64 for SHA-256).
func fullSHA(field, s string) (string, error) {
	s = strings.ToLower(strings.TrimSpace(s))
	if !isHex(s) || (len(s) != 40 && len(s) != 64) {
		return "", errf(CodeBadRequest, "%s must be a full commit hash (40 or 64 hex characters), got %q", field, s)
	}
	return s, nil
}

// normalizeSource checks a revision source and lowercases its hashes.
func normalizeSource(in *api.CommitSource) (*api.CommitSource, error) {
	if in == nil {
		return nil, nil
	}
	src := *in
	var err error
	if src.SHA, err = fullSHA("source.sha", src.SHA); err != nil {
		return nil, err
	}
	if strings.TrimSpace(src.Parent) != "" {
		if src.Parent, err = fullSHA("source.parent", src.Parent); err != nil {
			return nil, err
		}
	} else {
		src.Parent = ""
	}
	if !src.Date.IsZero() {
		src.Date = src.Date.UTC()
	}
	return &src, nil
}

// ImportCommits upserts commit metadata into the registry's commits table on
// main and commits it. New commits are numbered in request order, which
// breaks ties between commits with the same date.
func (s *Store) ImportCommits(ctx context.Context, id string, in api.ImportCommits) (*api.CommitList, error) {
	if err := s.Exists(ctx, id); err != nil {
		return nil, err
	}
	if len(in.Commits) == 0 {
		return nil, errf(CodeBadRequest, "commits must not be empty")
	}
	repo := strings.TrimSpace(in.Repo)
	if len(repo) > 1024 {
		return nil, errf(CodeBadRequest, "repo is longer than 1024 characters")
	}
	type row struct {
		sha, parent, subject, author, files, url string
		date                                     time.Time
	}
	rows := make([]row, 0, len(in.Commits))
	for i, c := range in.Commits {
		sha, err := fullSHA("commits["+itoa(i)+"].sha", c.SHA)
		if err != nil {
			return nil, err
		}
		parent := ""
		if strings.TrimSpace(c.Parent) != "" {
			if parent, err = fullSHA("commits["+itoa(i)+"].parent", c.Parent); err != nil {
				return nil, err
			}
		}
		files := c.Files
		if files == nil {
			files = []string{}
		}
		fb, err := json.Marshal(files)
		if err != nil {
			return nil, err
		}
		author := c.Author
		if len(author) > 512 {
			author = author[:512]
		}
		url := strings.TrimSpace(c.URL)
		if len(url) > 2048 {
			return nil, errf(CodeBadRequest, "commits[%d].url is longer than 2048 characters", i)
		}
		rows = append(rows, row{sha: sha, parent: parent, subject: c.Subject, author: author, files: string(fb), url: url, date: c.Date.UTC().Truncate(time.Microsecond)})
	}
	s.regMu.Lock()
	err := s.withConn(ctx, Database, func(c *sql.Conn) error {
		var seq int64
		if err := c.QueryRowContext(ctx, "SELECT COALESCE(MAX(seq), 0) FROM commits WHERE ontology_id = ?", id).Scan(&seq); err != nil {
			return err
		}
		for _, r := range rows {
			seq++
			// A re-import without a url keeps the stored one.
			if _, err := c.ExecContext(ctx, "INSERT INTO commits (ontology_id, sha, parent, subject, author, date, files, repo, seq, url) "+
				"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE parent = VALUES(parent), subject = VALUES(subject), "+
				"author = VALUES(author), date = VALUES(date), files = VALUES(files), repo = VALUES(repo), "+
				"url = IF(VALUES(url) = '', url, VALUES(url))",
				id, r.sha, r.parent, r.subject, r.author, r.date, r.files, repo, seq, r.url); err != nil {
				return err
			}
		}
		return commitIfDirty(ctx, c, []string{"commits"}, "Import commits into "+id)
	})
	s.regMu.Unlock()
	if err != nil {
		return nil, err
	}
	return s.ListCommits(ctx, id)
}

type commitRow struct {
	api.Commit
	repo string
	seq  int64
}

// loadCommits reads an ontology's commits, oldest first: by date and import
// order, with every parent placed before its children.
func (s *Store) loadCommits(ctx context.Context, id string) ([]commitRow, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT sha, parent, subject, author, date, files, repo, seq, url FROM "+Database+
		".commits WHERE ontology_id = ? ORDER BY date, seq", id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var list []commitRow
	for rows.Next() {
		var r commitRow
		var files []byte
		if err := rows.Scan(&r.SHA, &r.Parent, &r.Subject, &r.Author, &r.Date, &files, &r.repo, &r.seq, &r.URL); err != nil {
			return nil, err
		}
		r.Date = r.Date.UTC()
		if err := json.Unmarshal(files, &r.Files); err != nil || r.Files == nil {
			r.Files = []string{}
		}
		list = append(list, r)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	// Topological order: a commit's parent comes first even when clocks lie.
	idx := make(map[string]int, len(list))
	for i, r := range list {
		idx[r.SHA] = i
	}
	state := make([]uint8, len(list)) // 0 new, 1 visiting, 2 done
	out := make([]commitRow, 0, len(list))
	var visit func(i int)
	visit = func(i int) {
		if state[i] != 0 {
			return
		}
		state[i] = 1
		if p, ok := idx[list[i].Parent]; ok {
			visit(p)
		}
		state[i] = 2
		out = append(out, list[i])
	}
	for i := range list {
		visit(i)
	}
	return out, nil
}

// revisionsBySHA maps each source sha to the latest revision modelling it.
func revisionsBySHA(revs []api.Revision) map[string]int {
	out := map[string]int{}
	for _, r := range revs {
		if r.Source != nil && r.Source.SHA != "" && r.Number > out[r.Source.SHA] {
			out[r.Source.SHA] = r.Number
		}
	}
	return out
}

// ListCommits returns the ontology's commits, oldest first, each linked to
// the revision modelling it and marked changed when that revision changes the
// model (citation-only edits, such as re-anchored lines, don't count).
func (s *Store) ListCommits(ctx context.Context, id string) (*api.CommitList, error) {
	revs, err := s.Revisions(ctx, id) // checks existence
	if err != nil {
		return nil, err
	}
	rows, err := s.loadCommits(ctx, id)
	if err != nil {
		return nil, err
	}
	bySHA := revisionsBySHA(revs)
	changed := map[int]bool{}
	out := &api.CommitList{Commits: make([]api.Commit, 0, len(rows))}
	var lastSeq int64 = -1
	for _, r := range rows {
		if r.seq > lastSeq {
			out.Repo, lastSeq = r.repo, r.seq
		}
		c := r.Commit
		c.Revision = bySHA[c.SHA]
		if c.Revision > 0 {
			ch, ok := changed[c.Revision]
			if !ok {
				diff, err := s.diffRefs(ctx, id, revRef(id, c.Revision-1), revRef(id, c.Revision))
				if err != nil {
					return nil, err
				}
				// Changed means the model changed: re-anchored citations alone don't count.
				for _, d := range diff {
					if d.Change != "modified" || !model.SameExceptCitations(d.Before, d.After) {
						ch = true
						break
					}
				}
				changed[c.Revision] = ch
			}
			c.Changed = ch
		}
		out.Commits = append(out.Commits, c)
	}
	return out, nil
}

// CommitDetail returns one commit, found by a hash prefix of at least seven
// characters, with the revisions before and after it, the entity changes
// between them and their impact. before is the revision modelling the parent
// commit; failing that, the latest revision created before after (or, when
// the commit has no revision, the revision of the nearest earlier commit).
func (s *Store) CommitDetail(ctx context.Context, id, prefix string) (*api.CommitDetail, error) {
	if err := s.Exists(ctx, id); err != nil {
		return nil, err
	}
	prefix = strings.ToLower(strings.TrimSpace(prefix))
	if !isHex(prefix) || len(prefix) < 7 || len(prefix) > 64 {
		return nil, errf(CodeBadRequest, "invalid commit %q: use a hash or a prefix of at least 7 hex characters", prefix)
	}
	list, err := s.ListCommits(ctx, id)
	if err != nil {
		return nil, err
	}
	at := -1
	for i, c := range list.Commits {
		if strings.HasPrefix(c.SHA, prefix) {
			if at >= 0 {
				return nil, errf(CodeConflict, "commit prefix %q is ambiguous: it matches %s and %s", prefix, list.Commits[at].SHA, c.SHA)
			}
			at = i
		}
	}
	if at < 0 {
		return nil, errf(CodeNotFound, "ontology %q has no commit %q", id, prefix)
	}
	c := list.Commits[at]
	revs, err := s.Revisions(ctx, id)
	if err != nil {
		return nil, err
	}
	bySHA := revisionsBySHA(revs)
	d := &api.CommitDetail{Commit: c, After: c.Revision, Changes: []api.Change{}}
	switch {
	case c.Parent != "" && bySHA[c.Parent] > 0 && (d.After == 0 || bySHA[c.Parent] < d.After):
		d.Before = bySHA[c.Parent]
	case d.After > 0:
		for _, r := range revs {
			if r.Number < d.After && r.Number > d.Before {
				d.Before = r.Number
			}
		}
	default:
		for i := at - 1; i >= 0; i-- {
			if list.Commits[i].Revision > 0 {
				d.Before = list.Commits[i].Revision
				break
			}
		}
	}
	if d.After == 0 {
		d.Impact = s.impact.Compute(emptyDocument(id), revKey(id, revs, 0), emptyDocument(id), revKey(id, revs, 0))
		return d, nil
	}
	if d.Changes, err = s.diffRefs(ctx, id, revRef(id, d.Before), revRef(id, d.After)); err != nil {
		return nil, err
	}
	before, err := s.docAt(ctx, id, d.Before)
	if err != nil {
		return nil, err
	}
	after, err := s.docAt(ctx, id, d.After)
	if err != nil {
		return nil, err
	}
	d.Impact = s.impact.Compute(before, revKey(id, revs, d.Before), after, revKey(id, revs, d.After))
	return d, nil
}

// revKey identifies revision n of an ontology for the impact cache: its
// number and commit hash, which never change (0 is the empty base). It is
// empty, so the cache hashes the document, when n is unknown or the draft.
func revKey(id string, revs []api.Revision, n int) string {
	if n == 0 {
		return id + "@base"
	}
	for _, r := range revs {
		if r.Number == n && r.Hash != "" {
			return fmt.Sprintf("%s@%d@%s", id, n, r.Hash)
		}
	}
	return ""
}

func emptyDocument(id string) *model.Document {
	return &model.Document{SchemaVersion: 1, ID: id, Components: []model.Component{}, Interfaces: []model.Interface{},
		Links: []model.Link{}, Schemas: []model.Schema{}, Flows: []model.Flow{}, Scenarios: []model.Scenario{},
		Configs: []model.Config{}, Fixtures: []model.Fixture{}}
}

// docAt loads revision n, or the empty base when n is 0.
func (s *Store) docAt(ctx context.Context, id string, n int) (*model.Document, error) {
	if n == 0 {
		return emptyDocument(id), nil
	}
	doc, _, err := s.Document(ctx, id, Rev{N: n})
	return doc, err
}

// Impact compares two selectors. An empty from means the latest revision (the
// empty base when there is none, also selectable as "base"); an empty to
// means the draft.
func (s *Store) Impact(ctx context.Context, id, from, to string) (*model.Impact, error) {
	if err := s.Exists(ctx, id); err != nil {
		return nil, err
	}
	revs, err := s.Revisions(ctx, id)
	if err != nil {
		return nil, err
	}
	// load returns the selected document and its cache key ("" for the
	// draft, which changes: the cache then keys it by content).
	load := func(sel string, defLatest bool) (*model.Document, string, error) {
		sel = strings.TrimSpace(sel)
		if sel == "" && defLatest {
			if len(revs) == 0 {
				return emptyDocument(id), revKey(id, revs, 0), nil
			}
			sel = "latest"
		}
		if sel == "base" {
			return emptyDocument(id), revKey(id, revs, 0), nil
		}
		r, err := s.resolveRev(ctx, id, sel)
		if err != nil {
			return nil, "", err
		}
		doc, _, err := s.Document(ctx, id, r)
		if err != nil || r.IsDraft() {
			return doc, "", err
		}
		return doc, revKey(id, revs, r.N), nil
	}
	before, bk, err := load(from, true)
	if err != nil {
		return nil, err
	}
	after, ak, err := load(to, false)
	if err != nil {
		return nil, err
	}
	return s.impact.Compute(before, bk, after, ak), nil
}

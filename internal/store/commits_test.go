package store_test

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/store"
	"github.com/xleelz/mosaic/pkg/api"
)

// sha pads a hex prefix with zeros to a 40-hex commit hash.
func sha(prefix string) string { return prefix + strings.Repeat("0", 40-len(prefix)) }

func TestCommitsAndSourcedRevisions(t *testing.T) {
	ctx := context.Background()
	id := "commits-store"
	if _, err := st.CreateOntology(ctx, api.CreateOntology{ID: id}); err != nil {
		t.Fatal(err)
	}
	t0 := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	c1, c2, c3 := sha("aaaaaaa1"), sha("aaaaaaa2"), sha("ccc3")
	// Commits arrive out of order and with equal dates; c3's clock is behind.
	in := api.ImportCommits{Repo: "/src/app", Commits: []api.Commit{
		{SHA: c2, Parent: c1, Subject: "second", Author: "A <a@x>", Date: t0, Files: []string{"b.go"}},
		{SHA: c3, Parent: c2, Subject: "third", Date: t0.Add(-time.Hour), Files: []string{"README.md"}},
		{SHA: c1, Subject: "first", Date: t0, Files: []string{"a.go"}, URL: "https://example.com/c/" + c1},
	}}
	list, err := st.ImportCommits(ctx, id, in)
	if err != nil {
		t.Fatal(err)
	}
	if list.Repo != "/src/app" || len(list.Commits) != 3 {
		t.Fatalf("list = %+v", list)
	}
	for i, want := range []string{c1, c2, c3} {
		if list.Commits[i].SHA != want {
			t.Fatalf("commit %d = %s, want %s", i, list.Commits[i].SHA, want)
		}
	}
	if !equalStrings(list.Commits[1].Files, []string{"b.go"}) || list.Commits[1].Author != "A <a@x>" {
		t.Fatalf("c2 = %+v", list.Commits[1])
	}

	// r1 models c1, r2 models c2 (a change), r3 models c3 (empty).
	src := func(s, parent string) *api.CommitSource {
		return &api.CommitSource{Repo: "/src/app", SHA: strings.ToUpper(s), Parent: parent, Subject: "s", Date: t0}
	}
	mustUpsert(t, id, comp("svc", "v1"))
	if _, err := st.CreateRevision(ctx, id, api.CreateRevision{Message: "c1", Source: src(c1, "")}); err != nil {
		t.Fatal(err)
	}
	mustUpsert(t, id, comp("svc", "v2"))
	mustUpsert(t, id, comp("db", "db"))
	if _, err := st.CreateRevision(ctx, id, api.CreateRevision{Message: "c2", Source: src(c2, c1)}); err != nil {
		t.Fatal(err)
	}
	if _, err := st.CreateRevision(ctx, id, api.CreateRevision{Message: "c3", Source: src(c3, c2)}); !isCode(err, store.CodeConflict) {
		t.Fatalf("unchanged draft without allow_empty: %v", err)
	}
	r3, err := st.CreateRevision(ctx, id, api.CreateRevision{Message: "c3", Source: src(c3, c2), AllowEmpty: true})
	if err != nil {
		t.Fatal(err)
	}
	if r3.Number != 3 || r3.Source == nil || r3.Source.SHA != c3 || r3.Message != "c3" {
		t.Fatalf("r3 = %+v", r3)
	}
	if _, err := st.CreateRevision(ctx, id, api.CreateRevision{Message: "bad", AllowEmpty: true, Source: &api.CommitSource{SHA: "xyz"}}); !isCode(err, store.CodeBadRequest) {
		t.Fatalf("bad sha: %v", err)
	}

	// The source survives a reopen and comes back from list and get.
	st2, err := store.Open(ctx, srv.DB)
	if err != nil {
		t.Fatal(err)
	}
	revs, err := st2.Revisions(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	if len(revs) != 3 || revs[1].Source == nil || revs[1].Source.Parent != c1 || revs[1].Message != "c2" || !revs[1].Source.Date.Equal(t0) {
		t.Fatalf("revisions = %+v", revs)
	}
	if got, err := st2.Revision(ctx, id, "3"); err != nil || got.Source == nil || got.Source.SHA != c3 {
		t.Fatalf("revision 3 = %+v, %v", got, err)
	}

	list, err = st2.ListCommits(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	type link struct {
		rev     int
		changed bool
	}
	for i, want := range []link{{1, true}, {2, true}, {3, false}} {
		if got := (link{list.Commits[i].Revision, list.Commits[i].Changed}); got != want {
			t.Fatalf("commit %d link = %+v, want %+v", i, got, want)
		}
	}

	if list.Commits[0].URL != "https://example.com/c/"+c1 || list.Commits[1].URL != "" {
		t.Fatalf("urls = %q, %q", list.Commits[0].URL, list.Commits[1].URL)
	}
	if d, err := st2.CommitDetail(ctx, id, c1); err != nil || d.Commit.URL != "https://example.com/c/"+c1 {
		t.Fatalf("c1 detail url = %+v, %v", d, err)
	}
	d, err := st2.CommitDetail(ctx, id, c2[:8])
	if err != nil {
		t.Fatal(err)
	}
	if d.Before != 1 || d.After != 2 || d.Commit.SHA != c2 || d.Impact == nil {
		t.Fatalf("detail = %+v", d)
	}
	if len(d.Changes) != 2 || d.Changes[0].ID != "db" || d.Changes[0].Change != "added" || d.Changes[1].Change != "modified" {
		t.Fatalf("changes = %+v", d.Changes)
	}
	d, err = st2.CommitDetail(ctx, id, c1)
	if err != nil || d.Before != 0 || d.After != 1 || len(d.Changes) != 1 {
		t.Fatalf("c1 detail = %+v, %v", d, err)
	}
	// The prefix "aaaaaaa" matches c1 and c2.
	if _, err := st2.CommitDetail(ctx, id, "AAAAAAA"); !isCode(err, store.CodeConflict) {
		t.Fatalf("ambiguous prefix: %v", err)
	}
	if _, err := st2.CommitDetail(ctx, id, "aaaa"); !isCode(err, store.CodeBadRequest) {
		t.Fatalf("short prefix: %v", err)
	}
	if _, err := st2.CommitDetail(ctx, id, "bbbbbbbb"); !isCode(err, store.CodeNotFound) {
		t.Fatalf("unknown commit: %v", err)
	}
	if im, err := st2.Impact(ctx, id, "1", "2"); err != nil || im == nil {
		t.Fatalf("impact = %v, %v", im, err)
	}
	if _, err := st2.Impact(ctx, id, "9", ""); !isCode(err, store.CodeNotFound) {
		t.Fatalf("impact from missing revision: %v", err)
	}

	// Re-importing updates metadata without duplicating.
	if list, err = st2.ImportCommits(ctx, id, api.ImportCommits{Repo: "/src/app", Commits: []api.Commit{{SHA: c1, Subject: "first!", Date: t0}}}); err != nil {
		t.Fatal(err)
	}
	if len(list.Commits) != 3 || list.Commits[0].Subject != "first!" || list.Commits[0].URL != "https://example.com/c/"+c1 {
		t.Fatalf("after re-import = %+v", list.Commits)
	}
	if _, err := st2.ImportCommits(ctx, id, api.ImportCommits{Commits: []api.Commit{{SHA: "abc"}}}); !isCode(err, store.CodeBadRequest) {
		t.Fatalf("short sha import: %v", err)
	}

	// Deleting the ontology deletes its commits; a new one with the same id starts clean.
	if err := st2.DeleteOntology(ctx, id); err != nil {
		t.Fatal(err)
	}
	var n int
	if err := srv.DB.QueryRow("SELECT COUNT(*) FROM mosaic.commits WHERE ontology_id = ?", id).Scan(&n); err != nil || n != 0 {
		t.Fatalf("commits after delete = %d, %v", n, err)
	}
	if err := srv.DB.QueryRow("SELECT COUNT(*) FROM mosaic.dolt_status WHERE table_name = 'commits'").Scan(&n); err != nil || n != 0 {
		t.Fatalf("commits table left uncommitted: %d, %v", n, err)
	}
	if _, err := st2.CreateOntology(ctx, api.CreateOntology{ID: id}); err != nil {
		t.Fatal(err)
	}
	if list, err := st2.ListCommits(ctx, id); err != nil || len(list.Commits) != 0 {
		t.Fatalf("recreated list = %+v, %v", list, err)
	}
}

func mustUpsert(t *testing.T, id string, spec json.RawMessage) {
	t.Helper()
	if _, err := st.Upsert(context.Background(), id, model.KindComponent, []json.RawMessage{spec}, "", false); err != nil {
		t.Fatal(err)
	}
}

func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// TestCommitsURLMigration drops the url column, as in a database from before
// it existed, and checks that opening the store adds it back and commits it.
func TestCommitsURLMigration(t *testing.T) {
	ctx := context.Background()
	conn, err := srv.DB.Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	for _, q := range []string{"USE mosaic", "ALTER TABLE commits DROP COLUMN url", "CALL dolt_add('commits')",
		"CALL dolt_commit('-m', 'drop url', '--author', 'T <t@x>')"} {
		if _, err := conn.ExecContext(ctx, q); err != nil {
			t.Fatalf("%s: %v", q, err)
		}
	}
	if _, err := store.Open(ctx, srv.DB); err != nil {
		t.Fatal(err)
	}
	var n int
	if err := srv.DB.QueryRow("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = 'mosaic' AND table_name = 'commits' AND column_name = 'url'").Scan(&n); err != nil || n != 1 {
		t.Fatalf("url column = %d, %v", n, err)
	}
	if err := srv.DB.QueryRow("SELECT COUNT(*) FROM mosaic.dolt_status WHERE table_name = 'commits'").Scan(&n); err != nil || n != 0 {
		t.Fatalf("migration left commits uncommitted: %d, %v", n, err)
	}
	id := "commits-migrated"
	if _, err := st.CreateOntology(ctx, api.CreateOntology{ID: id}); err != nil {
		t.Fatal(err)
	}
	list, err := st.ImportCommits(ctx, id, api.ImportCommits{Commits: []api.Commit{{SHA: sha("dd"), Subject: "x", URL: "https://u/dd"}}})
	if err != nil || len(list.Commits) != 1 || list.Commits[0].URL != "https://u/dd" {
		t.Fatalf("after migration = %+v, %v", list, err)
	}
}

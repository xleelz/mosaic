package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

// testRepo builds a git repository:
//
//	c1 (a.go) - c2 (a.go, b.go) - merge - c4 (removes b.go)
//	              \- f1 (feature.go) -/
type testRepo struct {
	dir                   string
	c1, c2, f1, merge, c4 string
}

func gitT(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
	cmd.Env = append(os.Environ(), "GIT_AUTHOR_NAME=Ada", "GIT_AUTHOR_EMAIL=ada@example.com",
		"GIT_COMMITTER_NAME=Ada", "GIT_COMMITTER_EMAIL=ada@example.com", "GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_NOSYSTEM=1")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %s: %v\n%s", strings.Join(args, " "), err, out)
	}
	return strings.TrimSpace(string(out))
}

func newTestRepo(t *testing.T) *testRepo {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not found")
	}
	r := &testRepo{dir: t.TempDir()}
	write := func(name, content string) {
		if err := os.WriteFile(filepath.Join(r.dir, name), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	commit := func(msg string, date int) string {
		gitT(t, r.dir, "add", "-A")
		d := time.Date(2026, 5, 1, 10, date, 0, 0, time.UTC).Format(time.RFC3339)
		cmd := []string{"-c", "commit.gpgsign=false", "commit", "-q", "-m", msg, "--date", d}
		gitT(t, r.dir, cmd...)
		return gitT(t, r.dir, "rev-parse", "HEAD")
	}
	gitT(t, r.dir, "init", "-q", "-b", "main")
	write("a.go", "package a\n")
	r.c1 = commit("first", 1)
	write("a.go", "package a // v2\n")
	write("b.go", "package a\n")
	r.c2 = commit("second", 2)
	gitT(t, r.dir, "checkout", "-q", "-b", "feature")
	write("feature.go", "package a\n")
	r.f1 = commit("feature", 3)
	gitT(t, r.dir, "checkout", "-q", "main")
	gitT(t, r.dir, "-c", "commit.gpgsign=false", "merge", "-q", "--no-ff", "-m", "merge feature", "feature")
	r.merge = gitT(t, r.dir, "rev-parse", "HEAD")
	if err := os.Remove(filepath.Join(r.dir, "b.go")); err != nil {
		t.Fatal(err)
	}
	r.c4 = commit("drop b", 5)
	return r
}

// snapshot hashes every file under .git with its mode and mtime, so any
// write to the repository changes it.
func snapshot(t *testing.T, dir string) string {
	t.Helper()
	h := sha256.New()
	err := filepath.WalkDir(filepath.Join(dir, ".git"), func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		h.Write([]byte(p + info.Mode().String() + info.ModTime().String()))
		if !d.IsDir() {
			b, err := os.ReadFile(p)
			if err != nil {
				return err
			}
			h.Write(b)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return hex.EncodeToString(h.Sum(nil))
}

func TestCommitsImportFromGit(t *testing.T) {
	r := newTestRepo(t)
	f := withExample(t)
	before := snapshot(t, r.dir)

	out, _ := mustCLI(t, f, 0, "commits", "import", exampleOnt, "--repo", r.dir, "--range", r.c1+"..HEAD", "--first-parent",
		"--url-template", "https://github.com/org/repo/commit/{sha}")
	got := decode[api.CommitList](t, out)
	root, _ := filepath.EvalSymlinks(r.dir)
	if gotRoot, _ := filepath.EvalSymlinks(got.Repo); gotRoot != root {
		t.Fatalf("repo = %q, want %q", got.Repo, root)
	}
	if len(got.Commits) != 3 {
		t.Fatalf("first-parent import = %+v", got.Commits)
	}
	want := []struct {
		sha, parent, subject string
		files                []string
	}{
		{r.c2, r.c1, "second", []string{"a.go", "b.go"}},
		{r.merge, r.c2, "merge feature", []string{"feature.go"}},
		{r.c4, r.merge, "drop b", []string{"b.go"}},
	}
	for i, w := range want {
		c := got.Commits[i]
		if c.SHA != w.sha || c.Parent != w.parent || c.Subject != w.subject || strings.Join(c.Files, ",") != strings.Join(w.files, ",") {
			t.Fatalf("commit %d = %+v, want %+v", i, c, w)
		}
		if c.Author != "Ada <ada@example.com>" || c.Date.IsZero() || c.URL != "https://github.com/org/repo/commit/"+w.sha {
			t.Fatalf("commit %d metadata = %+v", i, c)
		}
	}

	// Without --first-parent the feature commit is included; the root commit lists its files.
	out, _ = mustCLI(t, f, 0, "commits", "import", exampleOnt, "--repo", r.dir, "--range", "HEAD")
	list := decode[api.CommitList](t, out)
	if len(list.Commits) != 5 {
		t.Fatalf("full import = %d commits", len(list.Commits))
	}
	for _, c := range list.Commits {
		if c.SHA == r.c1 && (c.Parent != "" || strings.Join(c.Files, ",") != "a.go") {
			t.Fatalf("root commit = %+v", c)
		}
	}

	// A revision sourced from git, then an empty one for the next commit.
	out, _ = mustCLI(t, f, 0, "put", exampleOnt, "component", "--json", `{"id":"newsvc","name":"New","kind":"service"}`)
	_ = out
	out, _ = mustCLI(t, f, 0, "revision", "create", exampleOnt, "-m", "model c2", "--source-sha", r.c2[:8], "--repo", r.dir,
		"--url-template", "https://example.com/{sha}")
	rev := decode[api.Revision](t, out)
	if rev.Source == nil || rev.Source.SHA != r.c2 || rev.Source.Parent != r.c1 || rev.Source.Subject != "second" ||
		rev.Source.Author != "Ada <ada@example.com>" || rev.Source.URL != "https://example.com/"+r.c2 || rev.Source.Date.IsZero() {
		t.Fatalf("revision source = %+v", rev.Source)
	}
	mustCLI(t, f, 1, "revision", "create", exampleOnt, "-m", "model merge", "--source-sha", r.merge, "--repo", r.dir)
	out, _ = mustCLI(t, f, 0, "revision", "create", exampleOnt, "-m", "model merge", "--source-sha", r.merge, "--repo", r.dir, "--allow-empty")
	if rev := decode[api.Revision](t, out); rev.Source == nil || rev.Source.SHA != r.merge || rev.Source.Parent != r.c2 {
		t.Fatalf("merge revision = %+v", rev)
	}
	// apply with a source.
	out, _ = mustCLI(t, f, 0, "apply", exampleOnt, "-f", examplePath, "-m", "c4", "--source-sha", "HEAD", "--repo", r.dir, "--allow-empty")
	applied := decode[struct {
		Revision api.Revision `json:"revision"`
	}](t, out)
	if applied.Revision.Source == nil || applied.Revision.Source.SHA != r.c4 {
		t.Fatalf("apply revision = %+v", applied.Revision)
	}

	out, _ = mustCLI(t, f, 0, "commits", "list", exampleOnt)
	list = decode[api.CommitList](t, out)
	linked := map[string]api.Commit{}
	for _, c := range list.Commits {
		linked[c.SHA] = c
	}
	if c := linked[r.c2]; c.Revision != 2 || !c.Changed {
		t.Fatalf("c2 = %+v", c)
	}
	if c := linked[r.merge]; c.Revision != 3 || c.Changed {
		t.Fatalf("merge = %+v", c)
	}
	if c := linked[r.f1]; c.Revision != 0 {
		t.Fatalf("feature = %+v", c)
	}
	out, _ = mustCLI(t, f, 0, "commits", "show", exampleOnt, r.merge[:9])
	for _, s := range []string{"commit " + r.merge, "url    https://github.com/org/repo/commit/" + r.merge, "merge feature", "feature.go", "revisions: before r2, after r3", "impact:"} {
		if !strings.Contains(out, s) {
			t.Fatalf("show output misses %q:\n%s", s, out)
		}
	}

	if after := snapshot(t, r.dir); after != before {
		t.Fatal("the repository changed during import and revision creation")
	}
}

func TestCommitsUsageAndErrors(t *testing.T) {
	f := withExample(t)
	mustCLI(t, f, 2, "commits", "import", exampleOnt, "--repo", ".")
	mustCLI(t, f, 2, "commits", "import", exampleOnt, "--range", "--all")
	mustCLI(t, f, 2, "commits", "import", exampleOnt, "--range", "a..b", "--url-template", "https://x/")
	mustCLI(t, f, 2, "commits", "import", exampleOnt, "--range", "a..b", "--repo", t.TempDir()) // not a repository
	mustCLI(t, f, 2, "commits", "show", exampleOnt, "abc")
	mustCLI(t, f, 2, "revision", "create", exampleOnt, "-m", "x", "--repo", ".")
	mustCLI(t, f, 1, "commits", "show", exampleOnt, "abcdef0")
	if _, err := git(context.Background(), ".", "checkout", "main"); err == nil {
		t.Fatal("git checkout was allowed")
	}
	if _, err := git(context.Background(), ".", "fetch"); err == nil {
		t.Fatal("git fetch was allowed")
	}
}

func TestCommitsShowAmbiguous(t *testing.T) {
	f := withExample(t)
	a, b := "abcdef1"+strings.Repeat("0", 33), "abcdef1"+strings.Repeat("1", 33)
	f.mu.Lock()
	o := f.onts[exampleOnt]
	o.commits = []api.Commit{{SHA: a, Subject: "a"}, {SHA: b, Subject: "b"}}
	f.mu.Unlock()
	_, errOut := mustCLI(t, f, 1, "commits", "show", exampleOnt, "abcdef1")
	if !strings.Contains(errOut, "ambiguous") {
		t.Fatalf("stderr = %s", errOut)
	}
	out, _ := mustCLI(t, f, 0, "commits", "show", exampleOnt, "abcdef10", "--format", "json")
	if d := decode[api.CommitDetail](t, out); d.Commit.SHA != a {
		t.Fatalf("detail = %+v", d)
	}
	out, _ = mustCLI(t, f, 0, "commits", "list", exampleOnt, "--format", "text")
	if !strings.Contains(out, "abcdef1000") || !strings.Contains(out, "2 commits") {
		t.Fatalf("text list = %s", out)
	}
}

func TestWriteCommitDetail(t *testing.T) {
	d := &api.CommitDetail{
		Commit: api.Commit{SHA: "abc1234", Subject: "route to b", Files: []string{"x.go"}},
		Before: 1, After: 2,
		Changes: []api.Change{{Kind: "component", ID: "b", Change: "added"}, {Kind: "flow", ID: "f", Change: "modified"}},
		Impact: &model.Impact{
			Components:    model.ImpactSet{Added: []string{"b"}, Removed: []string{"old"}, Modified: []string{"gw"}},
			Flows:         model.ImpactSet{Added: []string{"new-flow"}, Modified: []string{"f"}},
			FlowsAffected: []model.FlowImpact{{Flow: "chat", Reasons: []string{"component:gw"}}},
		},
	}
	var b strings.Builder
	if err := writeCommitDetail(&b, d); err != nil {
		t.Fatal(err)
	}
	out := b.String()
	for _, s := range []string{"revisions: before r1, after r2", "model changes: 2 (1 added, 0 removed, 1 modified)",
		"components added (1):", "components removed (1):", "old", "components modified (1):", "flows created (1):",
		"new-flow", "flows modified (1):", "flows affected (1):", "chat: component:gw"} {
		if !strings.Contains(out, s) {
			t.Fatalf("output misses %q:\n%s", s, out)
		}
	}
	b.Reset()
	_ = writeCommitDetail(&b, &api.CommitDetail{Commit: api.Commit{SHA: "x"}, Before: 3})
	if !strings.Contains(b.String(), "no revision models this commit (previous: r3)") {
		t.Fatalf("unrevisioned output:\n%s", b.String())
	}
}

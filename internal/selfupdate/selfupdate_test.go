package selfupdate

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime/debug"
	"strings"
	"testing"
	"time"
)

// repo is a test fixture: a bare "remote", a checkout cloned from it (the
// source dir) and a second clone that pushes new upstream commits.
type repo struct {
	t                   *testing.T
	remote, src, pusher string
}

func newRepo(t *testing.T) *repo {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not found")
	}
	dir := t.TempDir()
	r := &repo{t: t, remote: filepath.Join(dir, "remote.git"), src: filepath.Join(dir, "src"), pusher: filepath.Join(dir, "pusher")}
	r.git(dir, "init", "--quiet", "--bare", "--initial-branch=main", r.remote)
	r.git(dir, "clone", "--quiet", r.remote, r.pusher)
	r.commit("first")
	r.git(r.pusher, "push", "--quiet", "origin", "HEAD:main")
	r.git(dir, "clone", "--quiet", r.remote, r.src)
	return r
}

func (r *repo) git(dir string, args ...string) string {
	r.t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"}, args...)...)
	cmd.Env = append(os.Environ(), "GIT_CONFIG_NOSYSTEM=1", "HOME="+r.t.TempDir())
	out, err := cmd.CombinedOutput()
	if err != nil {
		r.t.Fatalf("git %s: %v\n%s", strings.Join(args, " "), err, out)
	}
	return strings.TrimSpace(string(out))
}

// commit adds a commit to the pusher clone (not pushed).
func (r *repo) commit(subject string) string {
	r.t.Helper()
	f := filepath.Join(r.pusher, "log.txt")
	b, _ := os.ReadFile(f)
	if err := os.WriteFile(f, append(b, subject+"\n"...), 0o644); err != nil {
		r.t.Fatal(err)
	}
	r.git(r.pusher, "add", "log.txt")
	r.git(r.pusher, "commit", "--quiet", "-m", subject)
	return r.git(r.pusher, "rev-parse", "HEAD")
}

// pushUpstream commits n times to the remote's main.
func (r *repo) pushUpstream(subjects ...string) string {
	var sha string
	for _, s := range subjects {
		sha = r.commit(s)
	}
	r.git(r.pusher, "push", "--quiet", "origin", "HEAD:main")
	return sha
}

func noBuildInfo() (*debug.BuildInfo, bool) { return nil, false }

func (r *repo) updater(opt Options) *Updater {
	opt.SourceDir = r.src
	opt.Version = "test"
	opt.BuildInfo = noBuildInfo
	return New(opt)
}

func TestBehindThenUpdate(t *testing.T) {
	r := newRepo(t)
	start := r.git(r.src, "rev-parse", "HEAD")
	latest := r.pushUpstream("second", "third")
	u := r.updater(Options{Supervised: true})
	if u.Commit() != start {
		t.Fatalf("commit = %s, want %s", u.Commit(), start)
	}
	v := u.Status(context.Background(), false)
	if !v.Update.Available || v.Update.Behind != 2 || v.Update.Ahead != 0 {
		t.Fatalf("status = %+v", v.Update)
	}
	if v.Branch != "main" || v.Upstream != "origin/main" || v.Update.LatestCommit != latest || v.Update.LatestSubject != "third" || v.Update.CheckedAt == nil {
		t.Fatalf("status = %+v", v)
	}
	res, err := u.Update(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if res.From != start || res.UpdatedTo != latest || !res.Restarting {
		t.Fatalf("update = %+v", res)
	}
	if head := r.git(r.src, "rev-parse", "HEAD"); head != latest {
		t.Fatalf("HEAD = %s, want %s", head, latest)
	}
	// Once restarting, a second update is refused.
	var refused *Refused
	if _, err := u.Update(context.Background()); !errors.As(err, &refused) {
		t.Fatalf("second update: %v", err)
	}
}

func TestUnsupervisedUpdateKeepsRunning(t *testing.T) {
	r := newRepo(t)
	r.pushUpstream("second")
	u := r.updater(Options{})
	res, err := u.Update(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if res.Restarting || !strings.Contains(res.Note, "restart") {
		t.Fatalf("update = %+v", res)
	}
	// The checkout moved but the running build didn't: restart needed.
	v := u.Status(context.Background(), false)
	if v.Update.Available || !strings.Contains(v.Update.Reason, "restart mosaicd") {
		t.Fatalf("status = %+v", v.Update)
	}
}

func TestUpToDate(t *testing.T) {
	r := newRepo(t)
	v := r.updater(Options{}).Status(context.Background(), false)
	if v.Update.Available || v.Update.Behind != 0 || !strings.Contains(v.Update.Reason, "up to date") {
		t.Fatalf("status = %+v", v.Update)
	}
}

func TestDiverged(t *testing.T) {
	r := newRepo(t)
	r.pushUpstream("upstream")
	if err := os.WriteFile(filepath.Join(r.src, "local.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	r.git(r.src, "add", "local.txt")
	r.git(r.src, "commit", "--quiet", "-m", "local")
	u := r.updater(Options{})
	v := u.Status(context.Background(), false)
	if v.Update.Available || v.Update.Behind != 1 || v.Update.Ahead != 1 || !strings.Contains(v.Update.Reason, "diverged") {
		t.Fatalf("status = %+v", v.Update)
	}
	before := r.git(r.src, "rev-parse", "HEAD")
	var refused *Refused
	if _, err := u.Update(context.Background()); !errors.As(err, &refused) {
		t.Fatalf("update: %v", err)
	}
	if after := r.git(r.src, "rev-parse", "HEAD"); after != before {
		t.Fatal("a refused update moved HEAD")
	}
}

func TestDirty(t *testing.T) {
	r := newRepo(t)
	r.pushUpstream("second")
	if err := os.WriteFile(filepath.Join(r.src, "log.txt"), []byte("edited\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	u := r.updater(Options{})
	v := u.Status(context.Background(), false)
	if v.Update.Available || !strings.Contains(v.Update.Reason, "local changes") {
		t.Fatalf("status = %+v", v.Update)
	}
	var refused *Refused
	if _, err := u.Update(context.Background()); !errors.As(err, &refused) {
		t.Fatalf("update: %v", err)
	}
	// Untracked files alone don't block an update.
	r.git(r.src, "checkout", "--quiet", "--", "log.txt")
	if err := os.WriteFile(filepath.Join(r.src, "scratch.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if v := u.Status(context.Background(), false); !v.Update.Available {
		t.Fatalf("with an untracked file: %+v", v.Update)
	}
}

func TestNoUpstream(t *testing.T) {
	r := newRepo(t)
	r.git(r.src, "checkout", "--quiet", "-b", "local-only")
	v := r.updater(Options{}).Status(context.Background(), false)
	if v.Update.Available || !strings.Contains(v.Update.Reason, "no upstream") || v.Branch != "local-only" {
		t.Fatalf("status = %+v", v)
	}
}

func TestDisabled(t *testing.T) {
	r := newRepo(t)
	r.pushUpstream("second")
	u := r.updater(Options{Disabled: true})
	v := u.Status(context.Background(), false)
	if v.Update.Available || v.Update.Behind != 1 || !strings.Contains(v.Update.Reason, "disabled") {
		t.Fatalf("status = %+v", v.Update)
	}
	var refused *Refused
	if _, err := u.Update(context.Background()); !errors.As(err, &refused) {
		t.Fatalf("update: %v", err)
	}
}

func TestNoSourceDirAndNotGit(t *testing.T) {
	v := New(Options{Version: "test", BuildInfo: noBuildInfo}).Status(context.Background(), false)
	if v.Update.Available || !strings.Contains(v.Update.Reason, "--source-dir") {
		t.Fatalf("no source dir: %+v", v.Update)
	}
	v = New(Options{SourceDir: t.TempDir(), Version: "test", BuildInfo: noBuildInfo}).Status(context.Background(), false)
	if v.Update.Available || !strings.Contains(v.Update.Reason, "not a git checkout") {
		t.Fatalf("not git: %+v", v.Update)
	}
}

func TestBuildInfoWins(t *testing.T) {
	bi := func() (*debug.BuildInfo, bool) {
		return &debug.BuildInfo{Settings: []debug.BuildSetting{{Key: "vcs.revision", Value: "abc123"}, {Key: "vcs.modified", Value: "true"}}}, true
	}
	u := New(Options{Version: "test", BuildInfo: bi})
	if v := u.Status(context.Background(), false); v.Commit != "abc123" || !v.Dirty {
		t.Fatalf("status = %+v", v)
	}
}

func TestFetchCachingAndFailure(t *testing.T) {
	r := newRepo(t)
	now := time.Date(2026, 11, 3, 12, 0, 0, 0, time.UTC)
	u := r.updater(Options{Now: func() time.Time { return now }})
	ctx := context.Background()
	if v := u.Status(ctx, false); v.Update.Behind != 0 {
		t.Fatalf("status = %+v", v.Update)
	}
	r.pushUpstream("second")
	// Within FetchEvery, no fetch: still 0 behind.
	now = now.Add(time.Minute)
	if v := u.Status(ctx, false); v.Update.Behind != 0 {
		t.Fatalf("cached status = %+v", v.Update)
	}
	// ?refresh=1 forces one.
	if v := u.Status(ctx, true); v.Update.Behind != 1 || !v.Update.CheckedAt.Equal(now) {
		t.Fatalf("refreshed status = %+v", v.Update)
	}
	// A second refresh within RefreshEvery doesn't fetch.
	r.pushUpstream("third")
	now = now.Add(10 * time.Second)
	if v := u.Status(ctx, true); v.Update.Behind != 1 {
		t.Fatalf("rate-limited refresh = %+v", v.Update)
	}
	// After FetchEvery, it fetches again.
	now = now.Add(DefaultFetchEvery)
	if v := u.Status(ctx, false); v.Update.Behind != 2 {
		t.Fatalf("stale status = %+v", v.Update)
	}
	// A failing fetch is reported with git's error.
	if err := os.RemoveAll(r.remote); err != nil {
		t.Fatal(err)
	}
	now = now.Add(DefaultFetchEvery)
	v := u.Status(ctx, false)
	if v.Update.Available || !strings.Contains(v.Update.Reason, "fetch failed") {
		t.Fatalf("fetch failure = %+v", v.Update)
	}
}

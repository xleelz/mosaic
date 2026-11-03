// Package selfupdate reports whether the mosaic checkout mosaicd was built
// from has new upstream commits, and fast-forwards it (docs/DESIGN.md §6, §8).
//
// It never builds anything: scripts/serve.sh rebuilds and restarts mosaicd
// and the web UI when mosaicd exits with ExitRestart after an update. Git runs
// through exec.CommandContext with fixed arguments and a timeout, never a shell.
package selfupdate

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"runtime/debug"
	"strconv"
	"strings"
	"sync"
	"time"

	wire "github.com/xleelz/mosaic/pkg/api"
)

// ExitRestart is the exit code mosaicd uses to ask its supervisor
// (scripts/serve.sh) to rebuild and restart it: EX_TEMPFAIL from sysexits.h.
const ExitRestart = 75

// Defaults for Options.
const (
	DefaultFetchEvery   = 10 * time.Minute
	DefaultRefreshEvery = 30 * time.Second
	gitTimeout          = 10 * time.Second
	fetchTimeout        = 90 * time.Second
)

// Options configures an Updater.
type Options struct {
	// SourceDir is the checkout mosaicd was built from; empty means updates
	// are unavailable.
	SourceDir string
	// Version is mosaicd's version string.
	Version string
	// Disabled refuses every update (--no-self-update).
	Disabled bool
	// Supervised means a supervisor restarts mosaicd when it exits with
	// ExitRestart (MOSAIC_SUPERVISED=1).
	Supervised bool
	// Git is the git binary (default "git").
	Git string
	// FetchEvery is how long a fetch stays fresh (default 10 min).
	FetchEvery time.Duration
	// RefreshEvery bounds forced fetches (?refresh=1; default 30 s).
	RefreshEvery time.Duration
	// Now overrides the clock (tests).
	Now func() time.Time
	// BuildInfo overrides debug.ReadBuildInfo (tests).
	BuildInfo func() (*debug.BuildInfo, bool)
}

// Updater answers version queries and performs updates. It is safe for
// concurrent use; git commands are serialized.
type Updater struct {
	opt Options

	// The running build, fixed at construction.
	commit string
	dirty  bool

	mu         sync.Mutex
	fetchedAt  time.Time // last fetch attempt
	forcedAt   time.Time // last forced fetch attempt
	fetchErr   string
	restarting bool
}

// New returns an Updater. It reads the running commit from the build info
// (vcs.revision, vcs.modified) and falls back to `git rev-parse HEAD` and
// `git status` in SourceDir.
func New(opt Options) *Updater {
	if opt.Git == "" {
		opt.Git = "git"
	}
	if opt.FetchEvery <= 0 {
		opt.FetchEvery = DefaultFetchEvery
	}
	if opt.RefreshEvery <= 0 {
		opt.RefreshEvery = DefaultRefreshEvery
	}
	if opt.Now == nil {
		opt.Now = time.Now
	}
	if opt.BuildInfo == nil {
		opt.BuildInfo = debug.ReadBuildInfo
	}
	u := &Updater{opt: opt}
	if bi, ok := opt.BuildInfo(); ok && bi != nil {
		for _, s := range bi.Settings {
			switch s.Key {
			case "vcs.revision":
				u.commit = s.Value
			case "vcs.modified":
				u.dirty = s.Value == "true"
			}
		}
	}
	if u.commit == "" && opt.SourceDir != "" {
		ctx, cancel := context.WithTimeout(context.Background(), gitTimeout)
		defer cancel()
		if out, err := u.git(ctx, "rev-parse", "HEAD"); err == nil {
			u.commit = out
			u.dirty = u.worktreeDirty(ctx)
		}
	}
	return u
}

// Supervised reports whether a supervisor restarts mosaicd after an update.
func (u *Updater) Supervised() bool { return u.opt.Supervised }

// Commit is the commit of the running build ("" when unknown).
func (u *Updater) Commit() string { return u.commit }

// Status reports the running version and whether an update is available.
// It fetches the upstream when the last fetch is older than FetchEvery, or
// when refresh is set and the last forced fetch is older than RefreshEvery.
func (u *Updater) Status(ctx context.Context, refresh bool) wire.SystemVersion {
	u.mu.Lock()
	defer u.mu.Unlock()
	return u.status(ctx, refresh, false)
}

// status computes the version; force fetches unconditionally. u.mu is held.
func (u *Updater) status(ctx context.Context, refresh, force bool) wire.SystemVersion {
	v := wire.SystemVersion{Version: u.opt.Version, Commit: u.commit, Dirty: u.dirty, SourceDir: u.opt.SourceDir}
	unavailable := func(reason string) wire.SystemVersion {
		v.Update.Available = false
		v.Update.Reason = reason
		return v
	}
	if u.opt.SourceDir == "" {
		return unavailable("mosaicd has no --source-dir (the mosaic checkout it was built from), so it can't update itself")
	}
	if _, err := u.git(ctx, "rev-parse", "--show-toplevel"); err != nil {
		return unavailable(fmt.Sprintf("%s is not a git checkout: %s", u.opt.SourceDir, err))
	}
	head, err := u.git(ctx, "rev-parse", "HEAD")
	if err != nil {
		return unavailable(fmt.Sprintf("git rev-parse HEAD: %s", err))
	}
	if v.Commit == "" {
		v.Commit = head
	}
	if b, err := u.git(ctx, "symbolic-ref", "--quiet", "--short", "HEAD"); err == nil {
		v.Branch = b
	}
	if v.Branch == "" {
		return unavailable("HEAD is detached, so there is no upstream branch to update from")
	}
	upstream, err := u.git(ctx, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
	if err != nil || upstream == "" {
		return unavailable(fmt.Sprintf("branch %s has no upstream (set one with git branch --set-upstream-to)", v.Branch))
	}
	v.Upstream = upstream

	now := u.opt.Now()
	if force || u.fetchedAt.IsZero() || now.Sub(u.fetchedAt) >= u.opt.FetchEvery ||
		(refresh && now.Sub(u.forcedAt) >= u.opt.RefreshEvery) {
		if refresh || force {
			u.forcedAt = now
		}
		u.fetchedAt = now
		u.fetchErr = ""
		if err := u.fetch(ctx, v.Branch); err != nil {
			u.fetchErr = err.Error()
		}
	}
	checked := u.fetchedAt
	v.Update.CheckedAt = &checked

	if n, err := u.count(ctx, "HEAD..@{u}"); err == nil {
		v.Update.Behind = n
	}
	if n, err := u.count(ctx, "@{u}..HEAD"); err == nil {
		v.Update.Ahead = n
	}
	if out, err := u.git(ctx, "log", "-1", "--format=%H%x00%s", "@{u}"); err == nil {
		sha, subject, _ := strings.Cut(out, "\x00")
		v.Update.LatestCommit, v.Update.LatestSubject = sha, subject
	}

	switch {
	case u.fetchErr != "":
		return unavailable("fetch failed: " + u.fetchErr)
	case u.restarting:
		return unavailable("an update was applied; mosaicd is restarting")
	case u.opt.Disabled:
		return unavailable("self-update is disabled (mosaicd --no-self-update)")
	case u.worktreeDirty(ctx):
		return unavailable(fmt.Sprintf("%s has local changes to tracked files; commit or stash them first", u.opt.SourceDir))
	case v.Update.Ahead > 0 && v.Update.Behind > 0:
		return unavailable(fmt.Sprintf("%s has diverged from %s (%d local commits, %d upstream); a fast-forward is impossible", v.Branch, upstream, v.Update.Ahead, v.Update.Behind))
	case v.Update.Behind == 0 && u.commit != "" && u.commit != head:
		return unavailable(fmt.Sprintf("the checkout is at %s but mosaicd runs %s: restart mosaicd and the web UI to run it", short(head), short(u.commit)))
	case v.Update.Behind == 0:
		return unavailable("up to date with " + upstream)
	}
	v.Update.Available = true
	return v
}

// Refused is an update that isn't possible right now (HTTP 409).
type Refused struct{ Reason string }

func (e *Refused) Error() string { return "update refused: " + e.Reason }

// GitError is a git command that failed during an update (HTTP 500).
type GitError struct {
	Args   []string
	Stderr string
	Err    error
}

func (e *GitError) Error() string {
	msg := strings.TrimSpace(e.Stderr)
	if msg == "" && e.Err != nil {
		msg = e.Err.Error()
	}
	return fmt.Sprintf("git %s: %s", strings.Join(e.Args, " "), msg)
}

func (e *GitError) Unwrap() error { return e.Err }

// Update fetches the upstream and fast-forwards the checkout to it. It
// refuses (*Refused) unless an update is available. When supervised, the
// result says restarting and later calls refuse; the caller is responsible
// for exiting with ExitRestart once the response is written.
func (u *Updater) Update(ctx context.Context) (*wire.SystemUpdate, error) {
	u.mu.Lock()
	defer u.mu.Unlock()
	v := u.status(ctx, true, true)
	if !v.Update.Available {
		return nil, &Refused{Reason: v.Update.Reason}
	}
	from, err := u.git(ctx, "rev-parse", "HEAD")
	if err != nil {
		return nil, err
	}
	mctx, cancel := context.WithTimeout(ctx, fetchTimeout)
	defer cancel()
	if _, err := u.git(mctx, "merge", "--ff-only", "--quiet", "@{u}"); err != nil {
		return nil, err
	}
	to, err := u.git(ctx, "rev-parse", "HEAD")
	if err != nil {
		return nil, err
	}
	res := &wire.SystemUpdate{From: from, UpdatedTo: to, Restarting: u.opt.Supervised}
	if u.opt.Supervised {
		u.restarting = true
		res.Note = "mosaicd is exiting so that scripts/serve.sh rebuilds and restarts it and the web UI"
	} else {
		res.Note = "the checkout is updated, but mosaicd isn't supervised: rebuild and restart mosaicd and the web UI yourself (or run them with scripts/serve.sh)"
	}
	return res, nil
}

// fetch fetches the branch's upstream ref from its remote.
func (u *Updater) fetch(ctx context.Context, branch string) error {
	remote, err := u.git(ctx, "config", "--get", "branch."+branch+".remote")
	if err != nil || remote == "" {
		return fmt.Errorf("branch %s has no remote", branch)
	}
	if remote == "." {
		return nil // the upstream is a local branch: nothing to fetch
	}
	if strings.HasPrefix(remote, "-") {
		return fmt.Errorf("refusing remote name %q", remote)
	}
	args := []string{"fetch", "--quiet", "--no-tags", remote}
	if merge, err := u.git(ctx, "config", "--get", "branch."+branch+".merge"); err == nil && merge != "" && !strings.HasPrefix(merge, "-") {
		args = append(args, merge)
	}
	fctx, cancel := context.WithTimeout(ctx, fetchTimeout)
	defer cancel()
	_, err = u.git(fctx, args...)
	return err
}

func (u *Updater) count(ctx context.Context, rng string) (int, error) {
	out, err := u.git(ctx, "rev-list", "--count", rng)
	if err != nil {
		return 0, err
	}
	return strconv.Atoi(out)
}

// worktreeDirty reports local changes to tracked files. Untracked files don't
// count: a fast-forward refuses by itself to overwrite one.
func (u *Updater) worktreeDirty(ctx context.Context) bool {
	out, err := u.git(ctx, "status", "--porcelain", "--untracked-files=no")
	return err != nil || out != ""
}

// git runs git in SourceDir and returns its trimmed stdout. Commands without
// a deadline get gitTimeout.
func (u *Updater) git(ctx context.Context, args ...string) (string, error) {
	if _, ok := ctx.Deadline(); !ok {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, gitTimeout)
		defer cancel()
	}
	full := append([]string{"-C", u.opt.SourceDir}, args...)
	cmd := exec.CommandContext(ctx, u.opt.Git, full...)
	cmd.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0", "LC_ALL=C")
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		if ctx.Err() != nil && errors.Is(ctx.Err(), context.DeadlineExceeded) {
			err = fmt.Errorf("timed out: %w", ctx.Err())
		}
		return "", &GitError{Args: args, Stderr: stderr.String(), Err: err}
	}
	return strings.TrimSpace(stdout.String()), nil
}

func short(sha string) string {
	if len(sha) > 7 {
		return sha[:7]
	}
	return sha
}

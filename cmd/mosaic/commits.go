package main

import (
	"bytes"
	"context"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

// Git access is strictly read-only: only these subcommands ever run, and
// optional locks (index refreshes) are disabled. The CLI never fetches,
// checks out, writes refs or otherwise modifies a repository.
var readOnlyGit = map[string]bool{"log": true, "show": true, "diff": true, "rev-parse": true, "rev-list": true}

// gitBin is replaced by tests that need to observe git invocations.
var gitBin = "git"

// importBatch bounds the commits sent in one request.
const importBatch = 500

func git(ctx context.Context, repo, sub string, args ...string) (string, error) {
	if !readOnlyGit[sub] {
		return "", fmt.Errorf("refusing to run git %s: only read-only git commands are allowed", sub)
	}
	full := append([]string{"-C", repo, "--no-pager", sub}, args...)
	cmd := exec.CommandContext(ctx, gitBin, full...)
	cmd.Env = append(os.Environ(), "GIT_OPTIONAL_LOCKS=0", "GIT_TERMINAL_PROMPT=0")
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(errb.String())
		if msg == "" {
			msg = err.Error()
		}
		return "", inputErrorf("git %s: %s", sub, msg)
	}
	return out.String(), nil
}

// repoPath returns the absolute path of a repository, which also names it.
func repoPath(ctx context.Context, repo string) (string, error) {
	if repo == "" {
		repo = "."
	}
	abs, err := filepath.Abs(repo)
	if err != nil {
		return "", inputErrorf("%v", err)
	}
	top, err := git(ctx, abs, "rev-parse", "--show-toplevel")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(top), nil
}

// Commit metadata, one record per commit: fields split by NUL, records by RS.
const logFormat = "--format=%H%x00%P%x00%an <%ae>%x00%aI%x00%s%x1e"

func parseLog(out string) ([]api.Commit, error) {
	var cs []api.Commit
	for _, rec := range strings.Split(out, "\x1e") {
		rec = strings.TrimLeft(rec, "\n")
		if rec == "" {
			continue
		}
		f := strings.SplitN(rec, "\x00", 5)
		if len(f) != 5 {
			return nil, fmt.Errorf("unexpected git log output %q", rec)
		}
		date, err := time.Parse(time.RFC3339, f[3])
		if err != nil {
			return nil, fmt.Errorf("commit %s: %v", f[0], err)
		}
		c := api.Commit{SHA: f[0], Subject: f[4], Author: f[2], Date: date.UTC(), Files: []string{}}
		if parents := strings.Fields(f[1]); len(parents) > 0 {
			c.Parent = parents[0]
		}
		cs = append(cs, c)
	}
	return cs, nil
}

// changedFiles lists the paths a commit changed against its first parent
// (every path, for a root commit).
func changedFiles(ctx context.Context, repo string, c api.Commit) ([]string, error) {
	var out string
	var err error
	if c.Parent == "" {
		out, err = git(ctx, repo, "show", "--name-only", "--no-renames", "--format=", "-z", c.SHA)
	} else {
		out, err = git(ctx, repo, "diff", "--name-only", "--no-renames", "-z", c.Parent, c.SHA, "--")
	}
	if err != nil {
		return nil, err
	}
	files := []string{}
	for _, p := range strings.Split(out, "\x00") {
		if p = strings.TrimSpace(p); p != "" {
			files = append(files, p)
		}
	}
	return files, nil
}

// readCommits reads the commits of a range, oldest first, with their files.
func readCommits(ctx context.Context, repo, rng string, firstParent bool) ([]api.Commit, error) {
	args := []string{"--reverse", logFormat}
	if firstParent {
		args = append(args, "--first-parent")
	}
	args = append(args, rng, "--")
	out, err := git(ctx, repo, "log", args...)
	if err != nil {
		return nil, err
	}
	cs, err := parseLog(out)
	if err != nil {
		return nil, err
	}
	for i := range cs {
		if cs[i].Files, err = changedFiles(ctx, repo, cs[i]); err != nil {
			return nil, err
		}
	}
	return cs, nil
}

// commitSource resolves sha in repo and describes it as a revision source.
func commitSource(ctx context.Context, repo, sha, urlTemplate string) (*api.CommitSource, error) {
	if strings.HasPrefix(sha, "-") {
		return nil, usageErrorf("--source-sha must be a commit, got %q", sha)
	}
	root, err := repoPath(ctx, repo)
	if err != nil {
		return nil, err
	}
	full, err := git(ctx, root, "rev-parse", "--verify", "--end-of-options", sha+"^{commit}")
	if err != nil {
		return nil, err
	}
	out, err := git(ctx, root, "log", "-1", logFormat, strings.TrimSpace(full), "--")
	if err != nil {
		return nil, err
	}
	cs, err := parseLog(out)
	if err != nil || len(cs) != 1 {
		return nil, inputErrorf("cannot read commit %s: %v", sha, err)
	}
	c := cs[0]
	return &api.CommitSource{Repo: root, SHA: c.SHA, Parent: c.Parent, Subject: c.Subject, Author: c.Author, Date: c.Date,
		URL: commitURL(urlTemplate, c.SHA)}, nil
}

func commitURL(tmpl, sha string) string {
	if tmpl == "" {
		return ""
	}
	return strings.ReplaceAll(tmpl, "{sha}", sha)
}

func checkURLTemplate(t string) error {
	if t != "" && !strings.Contains(t, "{sha}") {
		return usageErrorf("--url-template must contain {sha}, got %q", t)
	}
	return nil
}

// sourceFlags are the revision-source flags of revision create and apply.
type sourceFlags struct {
	sha, repo, urlTemplate *string
	allowEmpty             *bool
}

func addSourceFlags(fs *flag.FlagSet) sourceFlags {
	return sourceFlags{
		sha:         fs.String("source-sha", "", "code commit `SHA` this revision models (read from --repo)"),
		repo:        fs.String("repo", "", "git repository `PATH` for --source-sha (default: the current directory)"),
		urlTemplate: fs.String("url-template", "", "commit URL `TEMPLATE` for --source-sha, e.g. https://github.com/org/repo/commit/{sha}"),
		allowEmpty:  fs.Bool("allow-empty", false, "record a revision even when the draft is unchanged"),
	}
}

// source reads the revision source from git, or returns nil without --source-sha.
func (f sourceFlags) source(e *env) (*api.CommitSource, error) {
	if *f.sha == "" {
		if *f.repo != "" || *f.urlTemplate != "" {
			return nil, usageErrorf("--repo and --url-template need --source-sha")
		}
		return nil, nil
	}
	if err := checkURLTemplate(*f.urlTemplate); err != nil {
		return nil, err
	}
	return commitSource(e.ctx, *f.repo, *f.sha, *f.urlTemplate)
}

// Commands.

func cmdCommitsImport(e *env, c *command, args []string) error {
	fs := e.flags(c)
	repo := fs.String("repo", "", "git repository `PATH` (default: the current directory)")
	rng := fs.String("range", "", "commit `RANGE` such as v1.0..main (required)")
	firstParent := fs.Bool("first-parent", false, "follow only the first parent of merges")
	urlTemplate := fs.String("url-template", "", "commit URL `TEMPLATE`, e.g. https://github.com/org/repo/commit/{sha}, stored as each commit's url")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	switch {
	case strings.TrimSpace(*rng) == "":
		return usageErrorf("missing --range A..B")
	case strings.HasPrefix(*rng, "-"):
		return usageErrorf("--range must be a revision range, got %q", *rng)
	}
	if err := checkURLTemplate(*urlTemplate); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	root, err := repoPath(e.ctx, *repo)
	if err != nil {
		return err
	}
	cs, err := readCommits(e.ctx, root, *rng, *firstParent)
	if err != nil {
		return err
	}
	if len(cs) == 0 {
		return inputErrorf("range %s of %s has no commits", *rng, root)
	}
	for i := range cs {
		cs[i].URL = commitURL(*urlTemplate, cs[i].SHA)
	}
	var list *api.CommitList
	for i := 0; i < len(cs); i += importBatch {
		end := min(i+importBatch, len(cs))
		if list, err = cl.ImportCommits(e.ctx, pos[0], api.ImportCommits{Repo: root, Commits: cs[i:end]}); err != nil {
			return err
		}
	}
	fmt.Fprintf(e.stderr, "imported %d commits from %s into %s\n", len(cs), root, pos[0])
	return printJSON(e.stdout, list)
}

func cmdCommitsList(e *env, c *command, args []string) error {
	fs := e.flags(c)
	format := formatFlag(fs, "json", "output `FORMAT`: json or text")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if err := oneOf("format", *format, "json", "text"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	list, err := cl.ListCommits(e.ctx, pos[0])
	if err != nil {
		return err
	}
	if *format == "json" {
		return printJSON(e.stdout, list)
	}
	var b strings.Builder
	for _, cm := range list.Commits {
		rev := "     -"
		if cm.Revision > 0 {
			mark := " "
			if cm.Changed {
				mark = "*"
			}
			rev = fmt.Sprintf("%s r%-3d", mark, cm.Revision)
		}
		fmt.Fprintf(&b, "%s %s %s %s\n", short(cm.SHA), rev, cm.Date.Format("2006-01-02"), cm.Subject)
	}
	fmt.Fprintf(&b, "%d commits; * marks a revision that changed the model\n", len(list.Commits))
	_, err = io.WriteString(e.stdout, b.String())
	return err
}

func cmdCommitsShow(e *env, c *command, args []string) error {
	fs := e.flags(c)
	format := formatFlag(fs, "text", "output `FORMAT`: text or json")
	pos, err := e.parse(fs, args, 2, 2, "<ont> <sha>")
	if err != nil {
		return err
	}
	if err := oneOf("format", *format, "text", "json"); err != nil {
		return err
	}
	if len(pos[1]) < 7 {
		return usageErrorf("<sha> must be at least 7 characters, got %q", pos[1])
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	d, err := cl.GetCommit(e.ctx, pos[0], pos[1])
	if err != nil {
		return err
	}
	if *format == "json" {
		return printJSON(e.stdout, d)
	}
	return writeCommitDetail(e.stdout, d)
}

func short(sha string) string {
	if len(sha) > 10 {
		return sha[:10]
	}
	return sha
}

func revLabel(n int) string {
	if n == 0 {
		return "base (empty)"
	}
	return fmt.Sprintf("r%d", n)
}

// writeCommitDetail prints a commit, its revisions and a readable impact summary.
func writeCommitDetail(w io.Writer, d *api.CommitDetail) error {
	var b strings.Builder
	cm := d.Commit
	fmt.Fprintf(&b, "commit %s\n", cm.SHA)
	if cm.URL != "" {
		fmt.Fprintf(&b, "url    %s\n", cm.URL)
	}
	if cm.Parent != "" {
		fmt.Fprintf(&b, "parent %s\n", cm.Parent)
	}
	if cm.Author != "" {
		fmt.Fprintf(&b, "author %s\n", cm.Author)
	}
	if !cm.Date.IsZero() {
		fmt.Fprintf(&b, "date   %s\n", cm.Date.Format(time.RFC3339))
	}
	fmt.Fprintf(&b, "\n    %s\n\n", cm.Subject)
	fmt.Fprintf(&b, "files changed: %d\n", len(cm.Files))
	for _, f := range cm.Files {
		fmt.Fprintf(&b, "  %s\n", f)
	}
	b.WriteString("\n")
	if d.After == 0 {
		fmt.Fprintf(&b, "revisions: no revision models this commit (previous: %s)\n", revLabel(d.Before))
		_, err := io.WriteString(w, b.String())
		return err
	}
	fmt.Fprintf(&b, "revisions: before %s, after %s\n", revLabel(d.Before), revLabel(d.After))
	counts := map[string]int{}
	for _, ch := range d.Changes {
		counts[ch.Change]++
	}
	if len(d.Changes) == 0 {
		b.WriteString("model changes: none\n")
	} else {
		fmt.Fprintf(&b, "model changes: %d (%d added, %d removed, %d modified)\n",
			len(d.Changes), counts["added"], counts["removed"], counts["modified"])
	}
	writeImpact(&b, d.Impact)
	_, err := io.WriteString(w, b.String())
	return err
}

func writeImpact(b *strings.Builder, im *model.Impact) {
	if im == nil {
		return
	}
	b.WriteString("\nimpact:\n")
	line := func(label string, ids []string) {
		if len(ids) > 0 {
			fmt.Fprintf(b, "  %-22s %s\n", label+" ("+fmt.Sprint(len(ids))+"):", strings.Join(ids, ", "))
		}
	}
	empty := true
	sets := []struct {
		name string
		set  model.ImpactSet
	}{{"components", im.Components}, {"interfaces", im.Interfaces}, {"links", im.Links}, {"schemas", im.Schemas}, {"scenarios", im.Scenarios}, {"configs", im.Configs}, {"fixtures", im.Fixtures}}
	for _, s := range sets {
		line(s.name+" added", s.set.Added)
		line(s.name+" removed", s.set.Removed)
		line(s.name+" modified", s.set.Modified)
		empty = empty && len(s.set.Added)+len(s.set.Removed)+len(s.set.Modified) == 0
	}
	line("flows created", im.Flows.Added)
	line("flows removed", im.Flows.Removed)
	line("flows modified", im.Flows.Modified)
	empty = empty && len(im.Flows.Added)+len(im.Flows.Removed)+len(im.Flows.Modified) == 0
	if len(im.FlowsAffected) > 0 {
		empty = false
		fmt.Fprintf(b, "  flows affected (%d):\n", len(im.FlowsAffected))
		for _, f := range im.FlowsAffected {
			fmt.Fprintf(b, "    %s: %s\n", f.Flow, strings.Join(f.Reasons, ", "))
		}
	}
	if empty {
		b.WriteString("  no entities or flows changed\n")
	}
}

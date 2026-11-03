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
	"github.com/xleelz/mosaic/pkg/client"
)

func cmdBuild(args []string) (int, error) {
	fs := flag.NewFlagSet("build", flag.ExitOnError)
	base := fs.String("base", "", "directory with skeleton.yaml and fragments/")
	hist := fs.String("history", "", "directory of <NN>-<sha12> commit steps")
	out := fs.String("out", "", "output directory")
	areas := fs.String("areas", "", "comma-separated merge order of areas (skeleton is always first)")
	id := fs.String("id", "", "id of the merged documents (default: the skeleton's)")
	skip := fs.Bool("skip-scenarios", false, "validate only; don't run scenarios")
	quiet := fs.Bool("q", false, "print only the table and failures")
	_ = fs.Parse(args)
	if *base == "" || *hist == "" || *out == "" || fs.NArg() > 0 {
		usage()
	}
	b, steps, err := build(buildOptions{Base: *base, History: *hist, Areas: splitList(*areas), ID: *id, Scenarios: !*skip})
	if err != nil {
		return 0, err
	}
	md, err := writeOutputs(*out, b, steps)
	if err != nil {
		return 0, err
	}
	code := report(os.Stdout, b, steps, *quiet)
	fmt.Print(md)
	return code, nil
}

// report prints each step's problems and returns the exit status.
func report(w io.Writer, base *step, steps []*step, quiet bool) int {
	code := 0
	for _, s := range append([]*step{base}, steps...) {
		if s.ok() {
			if !quiet {
				fmt.Fprintf(w, "✓ %s\n", s.Name)
			}
			continue
		}
		code = 1
		fmt.Fprintf(w, "✗ %s\n", s.Name)
		for _, c := range s.Conflicts {
			fmt.Fprintf(w, "    conflict: %s\n", c)
		}
		for _, e := range s.Errors {
			fmt.Fprintf(w, "    %s\n", e)
		}
		for _, f := range s.Failures {
			fmt.Fprintf(w, "    scenario %s\n", f)
		}
	}
	return code
}

func cmdImport(args []string) error {
	fs := flag.NewFlagSet("import", flag.ExitOnError)
	server := fs.String("server", "http://127.0.0.1:8080", "mosaic server URL")
	ont := fs.String("ontology", "", "ontology id")
	token := fs.String("token", os.Getenv("MOSAIC_TOKEN"), "bearer token (default $MOSAIC_TOKEN)")
	base := fs.String("base", "", "directory with skeleton.yaml and fragments/")
	hist := fs.String("history", "", "directory of <NN>-<sha12> commit steps")
	repo := fs.String("repo", "", "local git checkout, to fill in commit metadata and changed files (read-only)")
	repoName := fs.String("repo-name", "", "repository name recorded in revision sources (default: commit.json repo, the skeleton's source.repo, or the --repo directory name)")
	areas := fs.String("areas", "", "comma-separated merge order of areas")
	id := fs.String("id", "", "id of the merged documents (default: the ontology id)")
	noBase := fs.Bool("no-base", false, "don't record the base as a revision first")
	noCommits := fs.Bool("no-commits", false, "don't post commit metadata")
	author := fs.String("author", "", "revision author (default: each commit's author)")
	_ = fs.Parse(args)
	if *ont == "" || *base == "" || *hist == "" || fs.NArg() > 0 {
		usage()
	}
	if *id == "" {
		*id = *ont
	}
	b, steps, err := build(buildOptions{Base: *base, History: *hist, Areas: splitList(*areas), ID: *id})
	if err != nil {
		return err
	}
	if report(os.Stderr, b, steps, true) != 0 {
		return fmt.Errorf("some documents don't merge or validate; nothing was posted")
	}
	if *repo != "" {
		for _, s := range steps {
			if err := fillFromGit(*repo, &s.Meta); err != nil {
				return err
			}
		}
	}
	name := func(m commitMeta) string {
		switch {
		case *repoName != "":
			return *repoName
		case m.Repo != "":
			return m.Repo
		case b.Doc.Source != nil && b.Doc.Source.Repo != "":
			return b.Doc.Source.Repo
		case *repo != "":
			abs, _ := filepath.Abs(*repo)
			return filepath.Base(abs)
		}
		return ""
	}
	ctx := context.Background()
	c := client.New(*server, *token)
	return importSteps(ctx, c, *ont, b, steps, importOptions{
		repoName: name, withBase: !*noBase, commits: !*noCommits && *repo != "", repo: *repo, author: *author,
		log: os.Stdout,
	})
}

type importOptions struct {
	repoName func(commitMeta) string
	withBase bool
	commits  bool
	repo     string
	author   string
	log      io.Writer
}

func importSteps(ctx context.Context, c *client.Client, ont string, base *step, steps []*step, o importOptions) error {
	if _, err := c.GetOntology(ctx, ont); client.IsNotFound(err) {
		if _, err := c.CreateOntology(ctx, api.CreateOntology{ID: ont, Name: base.Doc.Name, Description: base.Doc.Description}); err != nil {
			return err
		}
		fmt.Fprintf(o.log, "created ontology %s\n", ont)
	} else if err != nil {
		return err
	}
	if o.commits && len(steps) > 0 {
		req := api.ImportCommits{Repo: o.repoName(steps[0].Meta)}
		for _, s := range steps {
			files, err := changedFiles(o.repo, s.Meta)
			if err != nil {
				return err
			}
			req.Commits = append(req.Commits, api.Commit{SHA: s.Meta.SHA, Parent: s.Meta.Parent, Subject: s.Meta.Subject,
				Author: s.Meta.Author, Date: parseDate(s.Meta.Date), Files: files})
		}
		if _, err := c.ImportCommits(ctx, ont, req); err != nil {
			return fmt.Errorf("import commits: %w", err)
		}
		fmt.Fprintf(o.log, "imported %d commits\n", len(req.Commits))
	}
	post := func(s *step, msg string, src *api.CommitSource) error {
		res, err := c.PutDocument(ctx, ont, s.Doc)
		if err != nil {
			return fmt.Errorf("%s: replace draft: %w", s.Name, err)
		}
		if model.HasErrors(res.Issues) {
			return fmt.Errorf("%s: the server finds the document invalid: %v", s.Name, res.Issues)
		}
		author := o.author
		if author == "" && src != nil {
			author = src.Author
		}
		rev, err := c.CreateRevision(ctx, ont, api.CreateRevision{Message: msg, Author: author, Source: src, AllowEmpty: true})
		if err != nil {
			return fmt.Errorf("%s: create revision: %w", s.Name, err)
		}
		fmt.Fprintf(o.log, "revision %d  %s  %s\n", rev.Number, s.Name, msg)
		return nil
	}
	if o.withBase {
		var src *api.CommitSource
		msg := "base"
		if ds := base.Doc.Source; ds != nil && ds.SHA != "" {
			src = &api.CommitSource{Repo: o.repoName(commitMeta{}), SHA: ds.SHA, URL: ds.URL}
			msg = "base at " + short(ds.SHA)
		}
		if err := post(base, msg, src); err != nil {
			return err
		}
	}
	for _, s := range steps {
		m := s.Meta
		src := &api.CommitSource{Repo: o.repoName(m), SHA: m.SHA, Parent: m.Parent, Subject: m.Subject,
			Author: m.Author, Date: parseDate(m.Date), URL: m.URL}
		msg := strings.TrimSpace(short(m.SHA) + " " + m.Subject)
		if err := post(s, msg, src); err != nil {
			return err
		}
	}
	return nil
}

func parseDate(s string) time.Time {
	t, _ := time.Parse(time.RFC3339, s)
	return t
}

// git runs a read-only git subcommand against repo.
func git(repo string, args ...string) (string, error) {
	switch args[0] {
	case "diff", "show", "rev-parse", "log":
	default:
		return "", fmt.Errorf("refusing to run git %s: only diff, show, rev-parse and log are allowed", args[0])
	}
	cmd := exec.Command("git", append([]string{"-C", repo, "-c", "core.quotePath=false"}, args...)...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("git %s: %v: %s", strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return string(out), nil
}

// fillFromGit completes commit metadata from the repository: the full sha,
// first parent, subject, author and date, where commit.json leaves them out.
func fillFromGit(repo string, m *commitMeta) error {
	out, err := git(repo, "log", "-1", "--format=%H%x00%P%x00%s%x00%an%x00%aI", "--end-of-options", m.SHA)
	if err != nil {
		return err
	}
	f := strings.Split(strings.TrimRight(out, "\n"), "\x00")
	if len(f) != 5 {
		return fmt.Errorf("git log %s: unexpected output %q", m.SHA, out)
	}
	m.SHA = f[0]
	if m.Parent == "" {
		if ps := strings.Fields(f[1]); len(ps) > 0 {
			m.Parent = ps[0]
		}
	}
	if m.Subject == "" {
		m.Subject = f[2]
	}
	if m.Author == "" {
		m.Author = f[3]
	}
	if m.Date == "" {
		m.Date = f[4]
	}
	return nil
}

// changedFiles lists the paths a commit changed relative to its first parent.
func changedFiles(repo string, m commitMeta) ([]string, error) {
	var out string
	var err error
	if m.Parent != "" {
		out, err = git(repo, "diff", "--name-only", "--no-renames", m.Parent, m.SHA, "--")
	} else {
		out, err = git(repo, "show", "--name-only", "--format=", "--no-renames", m.SHA, "--")
	}
	if err != nil {
		return nil, err
	}
	files := []string{}
	for _, l := range strings.Split(out, "\n") {
		if l = strings.TrimSpace(l); l != "" {
			files = append(files, l)
		}
	}
	return files, nil
}

// Command history assembles one ontology per code commit from per-area
// fragment versions, and imports them into a mosaic server as revisions.
//
//	go run ./internal/devtools/history build --base DIR --history DIR --out DIR
//	    [--areas a,b,...] [--id ID] [--skip-scenarios] [-q]
//	go run ./internal/devtools/history import --server URL --ontology ID
//	    --base DIR --history DIR [--repo PATH] [--repo-name NAME] [--token T]
//	    [--areas a,b,...] [--id ID] [--no-base] [--no-commits] [--author NAME]
//
// Layout. The base is the model before the first commit: DIR/skeleton.yaml
// (area "skeleton") and DIR/fragments/<area>.yaml. Each commit is a directory
// <NN>-<sha12> under the history directory, taken in numeric order, holding
// commit.json ({sha, parent, subject, author, date, url, repo,
// removed_areas}) and fragments/<area>.yaml for only the areas that changed
// at that commit (fragments/skeleton.yaml replaces the skeleton). A commit
// that changes no modeled code has a commit.json and no fragments.
//
// build merges, for every commit, the latest version of each area at or
// before it, with the check tool's merge rules (internal/devtools/merge), in
// the order skeleton, --areas, then the rest alphabetically. It validates the
// result, runs every scenario (unless --skip-scenarios), and compares it with
// the previous step using impact.Compute (affected flows from scenario
// traces, see internal/impact). It writes base.json and
// <NN>-<sha12>.json (each document's source.sha is its commit), summary.json
// and summary.md, and prints the summary table. Exit status 1 means a step
// has merge conflicts, validation errors or failing scenarios.
//
// import builds the same documents (without running scenarios) and, in
// order, replaces the ontology's draft with each one and records a revision
// with source {repo, sha, parent, subject, author, date, url} and
// allow_empty, so that every commit has a revision. The base goes first, as
// the revision of the skeleton's source.sha, unless --no-base. With --repo,
// commit metadata missing from commit.json and each commit's changed files
// are read with read-only git (log, diff, show) and posted first to
// /ontologies/{id}/commits, unless --no-commits. The ontology is created when
// it doesn't exist. Nothing is posted when any document is invalid.
package main

import (
	"fmt"
	"os"
	"strings"
)

func main() {
	if len(os.Args) < 2 {
		usage()
	}
	var err error
	code := 0
	switch os.Args[1] {
	case "build":
		code, err = cmdBuild(os.Args[2:])
	case "import":
		err = cmdImport(os.Args[2:])
	case "-h", "--help", "help":
		usage()
	default:
		fmt.Fprintf(os.Stderr, "history: unknown command %q\n", os.Args[1])
		usage()
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "history:", err)
		os.Exit(2)
	}
	os.Exit(code)
}

func usage() {
	fmt.Fprintln(os.Stderr, `usage:
  history build --base DIR --history DIR --out DIR [--areas a,b] [--id ID] [--skip-scenarios] [-q]
  history import --server URL --ontology ID --base DIR --history DIR [--repo PATH] [--repo-name NAME]
                 [--token T] [--areas a,b] [--id ID] [--no-base] [--no-commits] [--author NAME]`)
	os.Exit(2)
}

func splitList(s string) []string {
	var out []string
	for _, x := range strings.Split(s, ",") {
		if x = strings.TrimSpace(x); x != "" {
			out = append(out, x)
		}
	}
	return out
}

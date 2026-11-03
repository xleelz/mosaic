// Command reanchor moves an ontology document's code citations from one
// commit to another, so a model built at FROM cites the right lines at TO.
//
//	go run ./internal/devtools/reanchor --repo PATH --from SHA --to SHA -f doc.yaml|doc.json
//	    [-o OUT] [--report] [--dry-run] [--strict]
//
// Every cited "path", "path:line" and "path:line-end" (strings, packed
// strings, and {path, line, end_line} objects under any "sources" or "source"
// key) is mapped through the hunks of `git diff -M --unified=0 FROM TO`:
//
//   - unchanged: the file or the cited lines didn't move;
//   - shifted: lines were added or removed above, so the numbers change;
//   - edited: some cited lines were replaced, or lines were inserted inside the
//     range; the range now spans their replacement;
//   - renamed: the file moved (also shifted or edited when its lines did);
//   - stale: every cited line was deleted; the citation now points at the line
//     that follows the deletion;
//   - file_deleted: the file is gone; the citation is left as it was;
//   - pinned: an object citation whose sha names another commit; left alone.
//
// Object citations and the document's source whose sha is FROM get TO's sha.
//
// YAML is rewritten textually: only citation values change, at the positions
// the parser reports, so comments and layout survive. JSON is decoded keeping
// key order and number text, rewritten, and written back indented.
//
// The document is rewritten in place unless -o names another file or
// --dry-run is given. The tool runs only read-only git subcommands (diff,
// rev-parse); it never fetches, checks out or writes to the repository.
//
// Exit status 1 with --strict means stale or deleted-file citations.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	repo := flag.String("repo", "", "git repository the citations point into")
	from := flag.String("from", "", "commit the citations were written against")
	to := flag.String("to", "", "commit to move them to")
	in := flag.String("f", "", "ontology document (YAML or JSON)")
	out := flag.String("o", "", "write the result here instead of rewriting -f in place")
	report := flag.Bool("report", false, "list every citation that moved, changed or went stale")
	dry := flag.Bool("dry-run", false, "write nothing; print the summary (and --report)")
	strict := flag.Bool("strict", false, "exit 1 when a citation is stale or its file was deleted")
	flag.Parse()
	if *repo == "" || *from == "" || *to == "" || *in == "" || flag.NArg() > 0 {
		fmt.Fprintln(os.Stderr, "usage: reanchor --repo PATH --from SHA --to SHA -f DOC [-o OUT] [--report] [--dry-run] [--strict]")
		os.Exit(2)
	}
	r, data, err := run(*repo, *from, *to, *in)
	if err != nil {
		fmt.Fprintln(os.Stderr, "reanchor:", err)
		os.Exit(2)
	}
	if *report {
		r.printReport(os.Stdout)
	}
	r.printSummary(os.Stderr)
	if !*dry {
		dest := *out
		if dest == "" {
			dest = *in
		}
		if err := os.WriteFile(dest, data, 0o644); err != nil {
			fmt.Fprintln(os.Stderr, "reanchor:", err)
			os.Exit(2)
		}
	}
	if *strict {
		for _, f := range r.found {
			if f.has(stStale) || f.has(stFileDeleted) {
				os.Exit(1)
			}
		}
	}
}

// run reanchors the document at path and returns the rewritten bytes.
func run(repo, from, to, path string) (*rewriter, []byte, error) {
	fromSHA, err := resolve(repo, from)
	if err != nil {
		return nil, nil, err
	}
	toSHA, err := resolve(repo, to)
	if err != nil {
		return nil, nil, err
	}
	ch, err := loadChanges(repo, fromSHA, toSHA)
	if err != nil {
		return nil, nil, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, err
	}
	r := &rewriter{ch: ch, from: fromSHA, to: toSHA}
	var outData []byte
	switch strings.ToLower(filepath.Ext(path)) {
	case ".json":
		outData, err = r.json(data)
	case ".yaml", ".yml":
		outData, err = r.yaml(filepath.Base(path), data)
	default:
		err = fmt.Errorf("%s: want a .yaml, .yml or .json document", path)
	}
	if err != nil {
		return nil, nil, fmt.Errorf("%s: %w", path, err)
	}
	return r, outData, nil
}

func (r *rewriter) counts() map[string]int {
	c := map[string]int{}
	for _, f := range r.found {
		for _, s := range f.Statuses {
			c[s]++
		}
	}
	return c
}

func (r *rewriter) printSummary(w io.Writer) {
	c := r.counts()
	var parts []string
	for _, s := range statusOrder {
		if c[s] > 0 {
			parts = append(parts, fmt.Sprintf("%d %s", c[s], s))
		}
	}
	fmt.Fprintf(w, "citations: %d (%s); %d values rewritten (%s..%s)\n", len(r.found), strings.Join(parts, ", "), r.edits, r.from[:12], r.to[:12])
	for _, p := range r.problems {
		fmt.Fprintln(w, "!", p)
	}
}

func (r *rewriter) printReport(w io.Writer) {
	for _, f := range r.found {
		if f.has(stUnchanged) {
			continue
		}
		mark := "~"
		if f.has(stStale) || f.has(stFileDeleted) {
			mark = "✗"
		}
		fmt.Fprintf(w, "%s %-14s %s -> %s  (%s)\n", mark, strings.Join(f.Statuses, ","), f.Old, f.New, f.Where)
	}
}

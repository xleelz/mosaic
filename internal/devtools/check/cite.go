package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math/rand"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// Citation statuses.
const (
	citeOK      = "ok"
	citeMissing = "missing"  // the path does not exist under the code root
	citeBadLine = "bad_line" // the line or end line is past the end of the file
	citeDir     = "dir"      // the path is a directory, not a file
	citePacked  = "packed"   // several sources in one string
	citeSkipped = "skipped"  // a secret file (.env, .age, keys): never opened
)

var citeStatuses = []string{citeOK, citeMissing, citeBadLine, citeDir, citePacked, citeSkipped}

// citation is one cited source and the claim it is meant to support.
type citation struct {
	Entity string // kind:id, such as interface:control-plane.post-v1-vms
	Claim  string // the entity summary or the step title
	Src    model.Source
	Status string
	Parts  []string // the separate sources of a packed citation, with their status
}

// collectCitations lists every cited source in the document: components,
// interfaces and their behavior steps (nested steps of any kind and retry
// sources included), links, configs, flows and flow steps.
func collectCitations(doc *model.Document) []citation {
	var out []citation
	add := func(entity, claim string, s model.Source) {
		out = append(out, citation{Entity: entity, Claim: claim, Src: s})
	}
	for _, c := range doc.Components {
		for _, s := range c.Sources {
			add("component:"+c.ID, first(c.Summary, c.Name, c.ID), s)
		}
	}
	for _, i := range doc.Interfaces {
		i.Normalize()
		ent := "interface:" + i.ID
		claim := first(i.Summary, i.Description, i.ID)
		for _, s := range i.Sources {
			add(ent, claim, s)
		}
		// Walk the behavior as plain JSON so step kinds added to the model
		// later (loops and the like) are covered without changes here.
		var steps []any
		b, _ := json.Marshal(i.Behavior)
		_ = json.Unmarshal(b, &steps)
		walkStepSources(steps, func(s model.Source, title string) { add(ent, first(title, claim), s) })
	}
	for _, l := range doc.Links {
		for _, s := range l.Sources {
			add("link:"+l.ID, first(l.Summary, l.Label, l.From+" -> "+l.To), s)
		}
	}
	for _, c := range doc.Configs {
		for _, s := range c.Sources {
			add("config:"+c.ID, first(c.Summary, c.Description, c.ID), s)
		}
	}
	for _, f := range doc.Flows {
		claim := first(f.Name, f.Description, f.ID)
		for _, s := range f.Sources {
			add("flow:"+f.ID, claim, s)
		}
		for _, st := range f.Steps {
			if st.Source != nil {
				add("flow:"+f.ID, first(st.Title, st.Detail, claim), *st.Source)
			}
		}
	}
	return out
}

// Keys of a step whose values are data, not steps.
var dataKeys = map[string]bool{"input": true, "return": true, "fail": true, "set": true, "source": true, "wait": true, "when": true, "retry": true}

// walkStepSources calls fn for every source in a list of steps, recursing
// into any nested list of steps (then, else, on_error, loop bodies) and map of
// lists (choice options).
func walkStepSources(steps []any, fn func(model.Source, string)) {
	for _, raw := range steps {
		m, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		title := stepClaim(m)
		if s, ok := decodeSource(m["source"]); ok {
			fn(s, title)
		}
		if r, ok := m["retry"].(map[string]any); ok {
			if s, ok := decodeSource(r["source"]); ok {
				fn(s, first(str(r["title"]), title)+" (retry)")
			}
		}
		for k, v := range m {
			if dataKeys[k] {
				continue
			}
			switch v := v.(type) {
			case []any:
				walkStepSources(v, fn)
			case map[string]any:
				for _, opt := range v {
					if l, ok := opt.([]any); ok {
						walkStepSources(l, fn)
					}
				}
			}
		}
	}
}

func stepClaim(m map[string]any) string {
	if t := first(str(m["title"]), str(m["detail"])); t != "" {
		return t
	}
	for _, k := range []string{"call", "emit", "if", "choice"} {
		if v := str(m[k]); v != "" {
			return k + " " + v
		}
	}
	for _, k := range []string{"return", "fail", "set", "wait"} {
		if _, ok := m[k]; ok {
			return k
		}
	}
	return ""
}

func decodeSource(v any) (model.Source, bool) {
	if v == nil {
		return model.Source{}, false
	}
	b, _ := json.Marshal(v)
	var s model.Source
	if err := json.Unmarshal(b, &s); err != nil || s.Path == "" {
		return model.Source{}, false
	}
	return s, true
}

func str(v any) string { s, _ := v.(string); return s }

func first(s ...string) string {
	for _, x := range s {
		if x = strings.TrimSpace(x); x != "" {
			return x
		}
	}
	return ""
}

// codeRoot resolves citations against a code snapshot, caching file lines.
type codeRoot struct {
	root  string
	lines map[string][]string
}

func newCodeRoot(root string) *codeRoot { return &codeRoot{root: root, lines: map[string][]string{}} }

// normPath strips a leading ./ and a #fragment.
func normPath(p string) string {
	p = strings.TrimSpace(p)
	for strings.HasPrefix(p, "./") {
		p = p[2:]
	}
	if i := strings.Index(p, "#"); i >= 0 {
		p = p[:i]
	}
	return p
}

var (
	packedSep = regexp.MustCompile(`[,;]\s*|\s+(?:and\s+)?`)
	pathLike  = regexp.MustCompile(`[\w.-]+/[\w./-]*|[\w-]+\.\w+`)
)

// isPacked reports whether a source's path holds several sources, such as
// "a.go:12, b.go:30" or "a.go:12 b.go".
func isPacked(s model.Source) bool {
	p := strings.TrimSpace(s.Path)
	if strings.ContainsAny(p, ",;") {
		return true
	}
	if strings.ContainsAny(p, " \t") {
		n := 0
		for _, part := range packedSep.Split(p, -1) {
			if pathLike.MatchString(part) {
				n++
			}
		}
		return n > 1
	}
	return false
}

func secretPath(p string) bool {
	b := filepath.Base(p)
	return strings.Contains(b, ".env") || strings.HasSuffix(b, ".age") || strings.HasSuffix(b, ".pem") || strings.HasSuffix(b, ".key") ||
		strings.HasPrefix(strings.ToLower(b), "credentials")
}

// resolve checks one citation.
func (c *codeRoot) resolve(s model.Source) (string, []string) {
	if isPacked(s) {
		var parts []string
		for _, part := range packedSep.Split(s.String(), -1) {
			if part = strings.TrimSpace(part); part == "" || part == "and" {
				continue
			}
			st, _ := c.resolve(model.ParseSource(part))
			parts = append(parts, part+" ("+st+")")
		}
		return citePacked, parts
	}
	p := normPath(s.Path)
	if p == "" {
		return citeMissing, nil
	}
	clean := filepath.Clean(filepath.FromSlash(p))
	if filepath.IsAbs(clean) || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return citeMissing, nil
	}
	if secretPath(clean) {
		return citeSkipped, nil
	}
	fi, err := os.Stat(filepath.Join(c.root, clean))
	switch {
	case err != nil:
		return citeMissing, nil
	case fi.IsDir():
		return citeDir, nil
	}
	if s.Line > 0 {
		n := len(c.file(clean))
		if s.Line > n || s.EndLine > n {
			return citeBadLine, nil
		}
	}
	return citeOK, nil
}

// file returns a file's lines. A secret file is never opened: it has none.
func (c *codeRoot) file(rel string) []string {
	if secretPath(rel) {
		return nil
	}
	if l, ok := c.lines[rel]; ok {
		return l
	}
	b, err := os.ReadFile(filepath.Join(c.root, rel))
	var l []string
	if err == nil {
		b = bytes.TrimSuffix(b, []byte("\n"))
		if len(b) > 0 {
			l = strings.Split(string(b), "\n")
		}
	}
	c.lines[rel] = l
	return l
}

// citeReport holds resolved citations and their totals.
type citeReport struct {
	cites  []citation
	totals map[string]int
	// bad lists each entity's citations that are not ok, in document order.
	bad   map[string][]citation
	order []string
}

func checkCitations(doc *model.Document, code *codeRoot) *citeReport {
	r := &citeReport{totals: map[string]int{}, bad: map[string][]citation{}}
	for _, c := range collectCitations(doc) {
		c.Status, c.Parts = code.resolve(c.Src)
		r.totals[c.Status]++
		if c.Status != citeOK {
			if _, ok := r.bad[c.Entity]; !ok {
				r.order = append(r.order, c.Entity)
			}
			r.bad[c.Entity] = append(r.bad[c.Entity], c)
		}
		r.cites = append(r.cites, c)
	}
	return r
}

// failures counts the citations --strict-citations refuses. A directory
// citation is reported but allowed: a deployable unit legitimately cites its
// directory.
func (r *citeReport) failures() int {
	return r.totals[citeMissing] + r.totals[citeBadLine] + r.totals[citePacked]
}

func (r *citeReport) print(w io.Writer) {
	for _, ent := range r.order {
		var parts []string
		for _, c := range r.bad[ent] {
			s := c.Status + " " + c.Src.String()
			if len(c.Parts) > 0 {
				s += " [" + strings.Join(c.Parts, "; ") + "]"
			}
			parts = append(parts, s)
		}
		fmt.Fprintf(w, "✗ cite %s: %s\n", ent, strings.Join(parts, ", "))
	}
	var t []string
	for _, s := range citeStatuses[1:] {
		t = append(t, fmt.Sprintf("%d %s", r.totals[s], s))
	}
	fmt.Fprintf(w, "citations: %d cited, %d ok, %s; %d entities with problems\n", len(r.cites), r.totals[citeOK], strings.Join(t, ", "), len(r.order))
}

// sample prints n random resolvable citations with the cited code next to the
// claim, for a person or a judge agent to check that the code supports it.
func (r *citeReport) sample(w io.Writer, code *codeRoot, n int, seed int64) {
	var pool []citation
	for _, c := range r.cites {
		if c.Status == citeOK || c.Status == citeBadLine {
			pool = append(pool, c)
		}
	}
	sort.SliceStable(pool, func(a, b int) bool { return pool[a].Entity < pool[b].Entity })
	rng := rand.New(rand.NewSource(seed))
	idx := rng.Perm(len(pool))
	if n > len(idx) {
		n = len(idx)
	}
	fmt.Fprintf(w, "citation sample: %d of %d resolvable citations (seed %d)\n", n, len(pool), seed)
	for k, i := range idx[:n] {
		c := pool[i]
		fmt.Fprintf(w, "\n[%d/%d] %s\n  claim: %s\n  cites: %s", k+1, n, c.Entity, oneLine(c.Claim, 200), c.Src.String())
		if c.Status != citeOK {
			fmt.Fprintf(w, "  (%s)", c.Status)
		}
		fmt.Fprintln(w)
		lines := code.file(filepath.Clean(filepath.FromSlash(normPath(c.Src.Path))))
		if c.Src.Line == 0 {
			fmt.Fprintf(w, "    (whole file, %d lines)\n", len(lines))
			continue
		}
		lo, hi := c.Src.Line, c.Src.EndLine
		ctxAfter := 0
		if hi < lo {
			hi, ctxAfter = lo, 3 // a single line: show what follows too
		}
		last := hi + ctxAfter
		if last > lo+14 {
			last = lo + 14
		}
		for ln := lo; ln <= last && ln <= len(lines); ln++ {
			mark := ">"
			if ln > hi {
				mark = " "
			}
			fmt.Fprintf(w, "  %s %5d | %s\n", mark, ln, codeLine(lines[ln-1], 160))
		}
		if hi > last {
			fmt.Fprintf(w, "    ... %d more cited lines\n", hi-last)
		}
	}
}

func oneLine(s string, max int) string {
	s = strings.ReplaceAll(strings.TrimRight(s, " \t\r"), "\t", "    ")
	s = strings.Join(strings.Fields(strings.ReplaceAll(s, "\n", " ")), " ")
	if len(s) > max {
		s = s[:max] + "…"
	}
	return s
}

func codeLine(s string, max int) string {
	s = strings.ReplaceAll(strings.TrimRight(s, " \t\r"), "\t", "  ")
	if len(s) > max {
		s = s[:max] + "…"
	}
	return s
}

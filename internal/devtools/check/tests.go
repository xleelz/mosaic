package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// Test-weighted coverage (DESIGN §13.1 item 19). The repo's test files, with
// the code each one tests (test_targets.py writes them), weight the model by
// what the project itself thinks is worth testing. A test is reached when
// some interface that a run scenario's trace calls cites one of its target
// files (or a directory above one).

// testTarget is one test file and the code under test.
type testTarget struct {
	Test    string   `json:"test"`
	Targets []string `json:"targets"`
	Area    string   `json:"area"`
}

func loadTests(file string) ([]testTarget, error) {
	b, err := os.ReadFile(file)
	if err != nil {
		return nil, err
	}
	var out []testTarget
	if err := json.Unmarshal(b, &out); err != nil {
		return nil, fmt.Errorf("%s: not a test-targets list: %w", file, err)
	}
	return out, nil
}

// targetPath turns a target into a snapshot-relative path, dropping a
// "#Symbol" or ":line" suffix. It returns "" for a bare symbol.
func targetPath(t string) string {
	p := normPath(t)
	if i := strings.LastIndex(p, ":"); i > strings.LastIndex(p, "/") {
		p = p[:i]
	}
	if !strings.Contains(p, "/") && path.Ext(p) == "" {
		return ""
	}
	return path.Clean(p)
}

// areaReach is one area's test reach.
type areaReach struct {
	Area                     string
	Tests, Resolved, Reached int
}

// Ratio is reached / resolved tests; ok is false when no test resolved.
func (a areaReach) Ratio() (float64, bool) {
	if a.Resolved == 0 {
		return 0, false
	}
	return float64(a.Reached) / float64(a.Resolved), true
}

type reachReport struct {
	Areas []areaReach
	Total areaReach
	// Unreached lists, per area, the resolved tests no called interface reaches.
	Unreached map[string][]string
}

// testReach scores each test. called holds the interface ids of every
// call.start in the run scenarios' traces. A target that is a bare symbol
// (no path) matches a called interface whose id, name or component id is the
// symbol's kebab-case.
func testReach(doc *model.Document, cites []citation, tests []testTarget, called map[string]bool) *reachReport {
	files := map[string]bool{} // files and directories cited by called interfaces
	for _, c := range cites {
		kind, id, _ := strings.Cut(c.Entity, ":")
		if kind != model.KindInterface || !called[id] {
			continue
		}
		if p := path.Clean(normPath(c.Src.Path)); p != "." && p != "" {
			files[p] = true
		}
	}
	symbols := map[string]bool{}
	for _, i := range doc.Interfaces {
		if !called[i.ID] {
			continue
		}
		symbols[i.ID] = true
		comp, op, _ := strings.Cut(i.ID, ".")
		symbols[comp] = true
		symbols[op] = true
		if i.Name != "" {
			symbols[funcSlug(i.Name)] = true
		}
		if i.Component != "" {
			symbols[i.Component] = true
		}
	}
	hit := func(t string) bool {
		p := targetPath(t)
		if p == "" {
			return symbols[funcSlug(t)]
		}
		for d := p; d != "." && d != "/"; d = path.Dir(d) {
			if files[d] {
				return true
			}
		}
		return false
	}
	r := &reachReport{Unreached: map[string][]string{}}
	by := map[string]*areaReach{}
	for _, t := range tests {
		a := t.Area
		if a == "" {
			a = "(none)"
		}
		ar := by[a]
		if ar == nil {
			ar = &areaReach{Area: a}
			by[a] = ar
		}
		ar.Tests++
		if len(t.Targets) == 0 {
			continue
		}
		ar.Resolved++
		reached := false
		for _, x := range t.Targets {
			if hit(x) {
				reached = true
				break
			}
		}
		if reached {
			ar.Reached++
		} else {
			r.Unreached[a] = append(r.Unreached[a], t.Test)
		}
	}
	for _, ar := range by {
		r.Areas = append(r.Areas, *ar)
		r.Total.Tests += ar.Tests
		r.Total.Resolved += ar.Resolved
		r.Total.Reached += ar.Reached
	}
	sort.Slice(r.Areas, func(a, b int) bool { return r.Areas[a].Area < r.Areas[b].Area })
	r.Total.Area = "total"
	return r
}

// print writes one line per area and the total. With min >= 0 it marks the
// areas whose reach is below min and reports whether any is. Only areas in
// this merge are gated (present holds the -f files' base names; nil means
// every area): an area-local run doesn't fail on the areas it leaves out.
// The "(none)" area, tests no area owns, is reported but never gated.
// verbose lists the unreached tests.
func (r *reachReport) print(w io.Writer, min float64, verbose bool, present map[string]bool) bool {
	gated := func(a areaReach) bool {
		return min >= 0 && a.Area != "(none)" && (present == nil || present[a.Area])
	}
	below, n := false, 0
	for _, a := range r.Areas {
		mark := " "
		if ratio, ok := a.Ratio(); ok && gated(a) && ratio < min {
			mark, below = "✗", true
			n++
		}
		note := ""
		if present != nil && !present[a.Area] && a.Area != "(none)" {
			note = ", not in this merge"
		}
		fmt.Fprintf(w, "%s test reach in %s: %d/%d %s (%d test files, %d with no target%s)\n",
			mark, a.Area, a.Reached, a.Resolved, pct(a.Reached, a.Resolved), a.Tests, a.Tests-a.Resolved, note)
		if verbose {
			for _, t := range r.Unreached[a.Area] {
				fmt.Fprintf(w, "    unreached: %s\n", t)
			}
		}
	}
	gate := ""
	if min >= 0 {
		gate = fmt.Sprintf("; --min-test-reach %.2f: %d areas below", min, n)
	}
	t := r.Total
	fmt.Fprintf(w, "test reach: %d of %d test files reached (%s), %d with no target%s\n",
		t.Reached, t.Resolved, pct(t.Reached, t.Resolved), t.Tests-t.Resolved, gate)
	return below
}

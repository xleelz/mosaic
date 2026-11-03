package main

// The trivial-behavior lint and substantive modeled coverage (DESIGN §13.1
// item 15). Coverage gates can be met by thin behaviors: an interface that
// cites an entry point and only returns is "modeled" without modeling
// anything. --lint trivial lists them, --max-trivial gates the share per
// fragment, and the modeled report counts the entries whose modeling
// interface isn't trivial as substantive (--min-substantive).

import (
	"fmt"
	"io"
	"path"
	"sort"

	"github.com/xleelz/mosaic/internal/model"
)

// trivialBehavior reports whether an interface has a behavior that is
// trivial: no store, and, at any depth, no call, if, choice, fail, emit or
// publish step and at most two set steps. A step guarded by `when` counts as
// a condition (it is an if by another name), so it isn't trivial either. An
// interface with no behavior isn't trivial: it isn't modeled at all, which
// the modeled level already reports.
func trivialBehavior(f *model.Interface) (bool, string) {
	if f.Store != nil || len(f.Behavior) == 0 {
		return false, ""
	}
	sets := 0
	for _, sp := range behaviorPaths(f) {
		s := sp.Step
		if s.Call != "" || s.If != "" || s.When != "" || s.Choice != "" || s.Fail != nil || s.Emit != "" || s.Publish != "" {
			return false, ""
		}
		if len(s.Set) > 0 {
			sets++
		}
	}
	if sets > 2 {
		return false, ""
	}
	if sets == 0 {
		return true, "no call, branch, fail, emit, publish, store or set"
	}
	return true, fmt.Sprintf("%d set step(s) and no call, branch, fail, emit, publish or store", sets)
}

// trivialIDs returns every interface whose behavior is trivial.
func trivialIDs(doc *model.Document) map[string]bool {
	out := map[string]bool{}
	for k := range doc.Interfaces {
		i := &doc.Interfaces[k]
		i.Normalize()
		if t, _ := trivialBehavior(i); t {
			out[i.ID] = true
		}
	}
	return out
}

// withoutTrivial copies called, leaving out the trivial interfaces, so that
// modeledBy over it gives the substantive level.
func withoutTrivial(called, trivial map[string]bool) map[string]bool {
	out := make(map[string]bool, len(called))
	for id := range called {
		if !trivial[id] {
			out[id] = true
		}
	}
	return out
}

// trivialHit is one interface the lint lists.
type trivialHit struct {
	ID, Fragment, Why string
	Entries           int // unskipped inventory entries it cites or is named for
}

// fragTrivial totals one fragment: the flow-reachable interfaces with a
// behavior or a store that cite an inventory entry, and how many are trivial.
type fragTrivial struct {
	Fragment        string
	Citing, Trivial int
}

func (f fragTrivial) Share() float64 {
	if f.Citing == 0 {
		return 0
	}
	return float64(f.Trivial) / float64(f.Citing)
}

type trivialReport struct {
	Hits      []trivialHit
	Fragments []fragTrivial
	Citing    int
	Trivial   int
}

// lintTrivial lists the flow-reachable interfaces that cite an unskipped
// inventory entry's lines (or are named for one, as coverage matches names)
// and whose behavior is trivial, with the share per fragment (the -f file
// that defined the interface).
func lintTrivial(doc *model.Document, cites []citation, inv []invEntry, origins map[string]string) *trivialReport {
	reach := reachableEntities(doc)
	cand := map[string]*model.Interface{}
	var names []named
	for k := range doc.Interfaces {
		i := &doc.Interfaces[k]
		i.Normalize()
		if reach["interface:"+i.ID] && (len(i.Behavior) > 0 || i.Store != nil) {
			cand["interface:"+i.ID] = i
			names = append(names, named{i.Name, i.ID})
		}
	}
	spans := map[string][]span{}
	dirs := map[string]bool{}
	for _, c := range cites {
		if cand[c.Entity] == nil {
			continue
		}
		f := path.Clean(normPath(c.Src.Path))
		hi := c.Src.EndLine
		if hi < c.Src.Line {
			hi = c.Src.Line
		}
		spans[f] = append(spans[f], span{c.Src.Line, hi, c.Entity})
		dirs[path.Dir(f)] = true
		dirs["area:"+area(f)] = true
	}
	hit := newHitter(inv)
	entries := map[string]int{} // entity -> entries it cites
	for _, e := range inv {
		if e.Skip != "" {
			continue
		}
		seen := map[string]bool{}
		for _, s := range spans[path.Clean(e.File)] {
			if !seen[s.entity] {
				if _, ok := hit([]span{s}, e); ok {
					seen[s.entity] = true
				}
			}
		}
		if want, nearKey := nameWants(e); nearKey != "" && dirs[nearKey] {
			if id := nameMatch(want, names); id != "" {
				seen["interface:"+id] = true
			}
		}
		for k := range seen {
			entries[k]++
		}
	}
	r := &trivialReport{}
	frags := map[string]*fragTrivial{}
	for k, n := range entries {
		i := cand[k]
		frag := origins[model.KindInterface+"/"+i.ID]
		fm := frags[frag]
		if fm == nil {
			fm = &fragTrivial{Fragment: frag}
			frags[frag] = fm
		}
		fm.Citing++
		r.Citing++
		if t, why := trivialBehavior(i); t {
			fm.Trivial++
			r.Trivial++
			r.Hits = append(r.Hits, trivialHit{i.ID, frag, why, n})
		}
	}
	sort.Slice(r.Hits, func(a, b int) bool {
		if r.Hits[a].Fragment != r.Hits[b].Fragment {
			return r.Hits[a].Fragment < r.Hits[b].Fragment
		}
		return r.Hits[a].ID < r.Hits[b].ID
	})
	for _, fm := range frags {
		r.Fragments = append(r.Fragments, *fm)
	}
	sort.Slice(r.Fragments, func(a, b int) bool { return r.Fragments[a].Fragment < r.Fragments[b].Fragment })
	return r
}

// print lists the trivial interfaces (unless quiet), one line per fragment
// and the totals. With max >= 0 it marks with ✗ the fragments whose trivial
// share is above max and reports whether any is.
func (r *trivialReport) print(w io.Writer, max float64, quiet bool) bool {
	if !quiet {
		for _, h := range r.Hits {
			fmt.Fprintf(w, "! trivial interface %s (%s, cites %d entries): %s\n", h.ID, h.Fragment, h.Entries, h.Why)
		}
	}
	above := 0
	for _, f := range r.Fragments {
		mark := " "
		if max >= 0 && f.Share() > max {
			mark = "✗"
			above++
		}
		fmt.Fprintf(w, "%s trivial in %s: %d of %d entry-citing interfaces %s\n", mark, f.Fragment, f.Trivial, f.Citing, pct1(f.Trivial, f.Citing))
	}
	gate := ""
	if max >= 0 {
		gate = fmt.Sprintf("; --max-trivial %.2f: %d fragments above", max, above)
	}
	fmt.Fprintf(w, "trivial lint: %d of %d entry-citing interfaces trivial (%s)%s\n", r.Trivial, r.Citing, pct1(r.Trivial, r.Citing), gate)
	return above > 0
}

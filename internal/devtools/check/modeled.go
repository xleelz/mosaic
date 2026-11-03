package main

import (
	"fmt"
	"io"
	"path"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// Coverage levels (DESIGN §13.1 item 13). An entry is registered when a
// reachable entity cites it or is named for it (covResult.covered). It is
// modeled when an interface that cites it, or is named for it, has a behavior
// or a store and some run scenario's trace calls that interface.

// modeledBy returns, for each inventory entry, the interface that models it,
// or "" when none does. called holds the interface ids of every call.start in
// the run scenarios' traces. Skipped entries are never modeled.
func modeledBy(doc *model.Document, cites []citation, inv []invEntry, called map[string]bool) []string {
	live := map[string]bool{} // "interface:<id>"
	var names []named
	for k := range doc.Interfaces {
		i := &doc.Interfaces[k]
		i.Normalize()
		if (len(i.Behavior) > 0 || i.Store != nil) && called[i.ID] {
			live["interface:"+i.ID] = true
			names = append(names, named{i.Name, i.ID})
		}
	}
	spans := map[string][]span{}
	dirs := map[string]bool{}
	for _, c := range cites {
		if !live[c.Entity] {
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
	out := make([]string, len(inv))
	for n, e := range inv {
		if e.Skip != "" {
			continue
		}
		if by, ok := hit(spans[path.Clean(e.File)], e); ok {
			out[n] = by
			continue
		}
		if want, nearKey := nameWants(e); nearKey != "" && dirs[nearKey] {
			if id := nameMatch(want, names); id != "" {
				out[n] = "interface:" + id
			}
		}
	}
	return out
}

// entryOwners attributes each inventory entry to the fragments (the -f files
// entities come from, as origins records) that own it: a fragment owns an
// entry when one of its entities cites the entry's file, or when the entry's
// path falls under a directory one of its entities cites.
func entryOwners(cites []citation, origins map[string]string, inv []invEntry) [][]string {
	frags := map[string]map[string]bool{} // fragment -> cited paths
	for _, c := range cites {
		kind, id, ok := strings.Cut(c.Entity, ":")
		if !ok {
			continue
		}
		frag := origins[kind+"/"+id]
		if frag == "" {
			continue
		}
		p := path.Clean(normPath(c.Src.Path))
		if p == "." || p == "" {
			continue
		}
		if frags[frag] == nil {
			frags[frag] = map[string]bool{}
		}
		frags[frag][p] = true
	}
	names := make([]string, 0, len(frags))
	for f := range frags {
		names = append(names, f)
	}
	sort.Strings(names)
	out := make([][]string, len(inv))
	for n, e := range inv {
		if e.Area != "" {
			for _, frag := range names {
				if strings.TrimSuffix(path.Base(frag), path.Ext(frag)) == e.Area {
					out[n] = append(out[n], frag)
				}
			}
			continue
		}
		f := path.Clean(e.File)
		for _, frag := range names {
			ps := frags[frag]
			owned := ps[f]
			for d := path.Dir(f); !owned && d != "." && d != "/"; d = path.Dir(d) {
				owned = ps[d]
			}
			if owned {
				out[n] = append(out[n], frag)
			}
		}
	}
	return out
}

// fragModeled is one fragment's modeled coverage of the entries it owns.
type fragModeled struct {
	Fragment                            string
	Owned, Skipped, Modeled, Registered int
	// Substantive counts the modeled entries whose modeling interface isn't
	// trivial (DESIGN §13.1 item 15).
	Substantive int
	Exempt      bool // defines no interface with a behavior or a store
}

// Ratio is modeled / (owned − skipped); ok is false when nothing is counted
// or the fragment is exempt from the gate.
func (f fragModeled) Ratio() (float64, bool) {
	d := f.Owned - f.Skipped
	if d <= 0 || f.Exempt {
		return 0, false
	}
	return float64(f.Modeled) / float64(d), true
}

// SubRatio is substantive / (owned − skipped), like Ratio.
func (f fragModeled) SubRatio() (float64, bool) {
	d := f.Owned - f.Skipped
	if d <= 0 || f.Exempt {
		return 0, false
	}
	return float64(f.Substantive) / float64(d), true
}

// modeledReport sums the modeled level per kind, per fragment and in total.
type modeledReport struct {
	ByKind      map[string]int
	SubByKind   map[string]int // substantive entries per kind
	Fragments   []fragModeled
	Modeled     int
	Substantive int
	Registered  int
	Counted     int // entries − skipped
	Unowned     int // counted entries no fragment owns
}

// setModeled records the modeled level of the table's results (by, sub and
// owners are aligned with them) and returns the per-fragment and total
// report. sub is modeledBy over the non-trivial interfaces only (the
// substantive level); nil counts every modeled entry as substantive. An entry
// of a declaration-only kind (level registered) is modeled, and substantive,
// once it is registered: there is no behavior to be thin.
func (t *covTable) setModeled(by, sub []string, owners [][]string) *modeledReport {
	if sub == nil {
		sub = by
	}
	r := &modeledReport{ByKind: map[string]int{}, SubByKind: map[string]int{}}
	frags := map[string]*fragModeled{}
	for n, res := range t.results {
		skipped := res.Status == covSkipped
		decl := res.Level == "registered" && res.covered()
		mod := by[n] != "" || decl
		subst := sub[n] != "" || decl
		if !skipped {
			r.Counted++
			if mod {
				r.Modeled++
				r.ByKind[res.Kind]++
			}
			if subst {
				r.Substantive++
				r.SubByKind[res.Kind]++
			}
			if res.covered() {
				r.Registered++
			}
			if len(owners[n]) == 0 {
				r.Unowned++
			}
		}
		for _, f := range owners[n] {
			fm := frags[f]
			if fm == nil {
				fm = &fragModeled{Fragment: f}
				frags[f] = fm
			}
			fm.Owned++
			switch {
			case skipped:
				fm.Skipped++
			case mod:
				fm.Modeled++
			}
			if !skipped && subst {
				fm.Substantive++
			}
			if !skipped && res.covered() {
				fm.Registered++
			}
		}
	}
	for _, fm := range frags {
		r.Fragments = append(r.Fragments, *fm)
	}
	sort.Slice(r.Fragments, func(a, b int) bool { return r.Fragments[a].Fragment < r.Fragments[b].Fragment })
	t.modeled = r.ByKind
	t.substantive = r.SubByKind
	return r
}

// print writes one line per fragment and the totals. A gate below 0 is off.
// It marks with ✗ the fragments whose modeled ratio is below minMod or whose
// substantive ratio is below minSub, and reports whether any is.
func (r *modeledReport) print(w io.Writer, minMod, minSub float64) bool {
	below := false
	for _, f := range r.Fragments {
		mark := " "
		if ratio, ok := f.Ratio(); ok && minMod >= 0 && ratio < minMod {
			mark, below = "✗", true
		}
		if ratio, ok := f.SubRatio(); ok && minSub >= 0 && ratio < minSub {
			mark, below = "✗", true
		}
		d := f.Owned - f.Skipped
		ex := ""
		if f.Exempt {
			ex = ", exempt"
		}
		fmt.Fprintf(w, "%s modeled in %s: %d/%d %s, substantive %d %s (registered %d, owned %d, skipped %d%s)\n",
			mark, f.Fragment, f.Modeled, d, pct(f.Modeled, d), f.Substantive, pct(f.Substantive, d), f.Registered, f.Owned, f.Skipped, ex)
	}
	gates := ""
	if minMod >= 0 {
		gates += fmt.Sprintf("; --min-modeled %.2f: %d fragments below", minMod, r.below(minMod))
	}
	if minSub >= 0 {
		gates += fmt.Sprintf("; --min-substantive %.2f: %d fragments below", minSub, r.subBelow(minSub))
	}
	fmt.Fprintf(w, "modeled: %d of %d entry points modeled (%s), %d substantive (%s), %d registered (%s), %d owned by no fragment%s\n",
		r.Modeled, r.Counted, pct(r.Modeled, r.Counted), r.Substantive, pct(r.Substantive, r.Counted), r.Registered, pct(r.Registered, r.Counted), r.Unowned, gates)
	return below
}

func (r *modeledReport) below(min float64) int {
	n := 0
	for _, f := range r.Fragments {
		if ratio, ok := f.Ratio(); ok && ratio < min {
			n++
		}
	}
	return n
}

func (r *modeledReport) subBelow(min float64) int {
	n := 0
	for _, f := range r.Fragments {
		if ratio, ok := f.SubRatio(); ok && ratio < min {
			n++
		}
	}
	return n
}

// exemptFragments marks the fragments that define no interface with a
// behavior or a store (a skeleton, a fixtures file): the --min-modeled gate
// reports them as exempt instead of failing them. Shared infrastructure
// (owner: shared, such as a skeleton's datastore operations) models no area,
// so its stores don't count.
func (r *modeledReport) exemptFragments(doc *model.Document, origins map[string]string) {
	models := map[string]bool{}
	for _, i := range doc.Interfaces {
		if owner, _ := i.Attributes["owner"].(string); owner == "shared" {
			continue
		}
		if len(i.Behavior) > 0 || i.Store != nil {
			i.Normalize()
			models[origins[model.KindInterface+"/"+i.ID]] = true
		}
	}
	for n := range r.Fragments {
		r.Fragments[n].Exempt = !models[r.Fragments[n].Fragment]
	}
}

package main

// Model-quality checks (DESIGN §12, §13.1 items 5 and 7): behavior coverage,
// the hollow-scenario lint, and mock counts.

import (
	"fmt"
	"io"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// stepPath is one behavior step and the path the simulator records for it
// in Summary.Executed: "<interface>:behavior[i].then[j].steps[k]...".
type stepPath struct {
	Path string
	Step model.Step
}

// behaviorPaths lists every step of an interface's behavior, at any depth,
// with the field names of §13.1 item 9: then, else, options.<name>, steps,
// branches[b] and on_error.
func behaviorPaths(f *model.Interface) []stepPath {
	var out []stepPath
	var walk func(prefix string, steps []model.Step)
	walk = func(prefix string, steps []model.Step) {
		for i, s := range steps {
			p := fmt.Sprintf("%s[%d]", prefix, i)
			out = append(out, stepPath{p, s})
			walk(p+".then", s.Then)
			walk(p+".else", s.Else)
			names := make([]string, 0, len(s.Options))
			for n := range s.Options {
				names = append(names, n)
			}
			sort.Strings(names)
			for _, n := range names {
				walk(p+".options."+n, s.Options[n])
			}
			walk(p+".steps", s.Steps)
			for b, br := range s.Branches {
				walk(fmt.Sprintf("%s.branches[%d]", p, b), br)
			}
			if s.OnError != nil {
				walk(p+".on_error", s.OnError.Steps)
			}
		}
	}
	walk(f.ID+":behavior", f.Behavior)
	return out
}

// ifaceCov is one interface's behavior coverage.
type ifaceCov struct {
	ID       string
	Fragment string
	Total    int
	Run      int
	Missing  []string // unexecuted step paths
}

// branchGap is an unexecuted fail step or if branch.
type branchGap struct {
	Interface string
	Fragment  string
	Path      string // the fail step, or the if step's branch ("....then", "....else")
	Kind      string // "fail", "if-then" or "if-else"
	Label     string // the step's title, or the if condition
}

// fragCov totals one fragment (the -f file that defined the interfaces).
type fragCov struct {
	Fragment             string
	Interfaces, Complete int
	Total, Run           int
	Gaps                 int
}

type behaviorCov struct {
	Interfaces []ifaceCov
	Gaps       []branchGap
	Fragments  []fragCov
	Total, Run int
	Scenarios  int // scenarios whose executed sets were counted
}

// behaviorCoverage compares the union of executed step paths against every
// behavior step. origin maps "<kind>/<id>" to the file that defined it.
func behaviorCoverage(doc *model.Document, executed map[string]bool, origin map[string]string, scenarios int) *behaviorCov {
	r := &behaviorCov{Scenarios: scenarios}
	frags := map[string]*fragCov{}
	for i := range doc.Interfaces {
		f := &doc.Interfaces[i]
		paths := behaviorPaths(f)
		if len(paths) == 0 {
			continue
		}
		c := ifaceCov{ID: f.ID, Fragment: origin[model.KindInterface+"/"+f.ID], Total: len(paths)}
		for _, sp := range paths {
			if executed[sp.Path] {
				c.Run++
			} else {
				c.Missing = append(c.Missing, sp.Path)
			}
			s := sp.Step
			if s.Fail != nil && !executed[sp.Path] {
				r.Gaps = append(r.Gaps, branchGap{f.ID, c.Fragment, sp.Path, "fail", label(s.Title, string(s.Fail))})
			}
			if s.If != "" {
				if len(s.Then) > 0 && !executed[sp.Path+".then[0]"] {
					r.Gaps = append(r.Gaps, branchGap{f.ID, c.Fragment, sp.Path + ".then", "if-then", "if " + s.If})
				}
				if len(s.Else) > 0 && !executed[sp.Path+".else[0]"] {
					r.Gaps = append(r.Gaps, branchGap{f.ID, c.Fragment, sp.Path + ".else", "if-else", "else of " + s.If})
				}
			}
		}
		r.Interfaces = append(r.Interfaces, c)
		fc := frags[c.Fragment]
		if fc == nil {
			fc = &fragCov{Fragment: c.Fragment}
			frags[c.Fragment] = fc
		}
		fc.Interfaces++
		if c.Run == c.Total {
			fc.Complete++
		}
		fc.Total += c.Total
		fc.Run += c.Run
		r.Total += c.Total
		r.Run += c.Run
	}
	for _, g := range r.Gaps {
		frags[g.Fragment].Gaps++
	}
	sort.Slice(r.Interfaces, func(a, b int) bool { return r.Interfaces[a].ID < r.Interfaces[b].ID })
	for _, fc := range frags {
		r.Fragments = append(r.Fragments, *fc)
	}
	sort.Slice(r.Fragments, func(a, b int) bool { return r.Fragments[a].Fragment < r.Fragments[b].Fragment })
	return r
}

func label(title, fallback string) string {
	if title != "" {
		return title
	}
	return fallback
}

// pct1 is a percentage with one decimal.
func pct1(n, d int) string {
	if d == 0 {
		return "-"
	}
	return fmt.Sprintf("%.1f%%", 100*float64(n)/float64(d))
}

func (r *behaviorCov) print(w io.Writer, verbose bool) {
	for _, c := range r.Interfaces {
		if c.Run == c.Total {
			continue
		}
		fmt.Fprintf(w, "~ behavior %s: %d/%d steps run (%s)\n", c.ID, c.Run, c.Total, c.Fragment)
		if verbose {
			for _, p := range c.Missing {
				fmt.Fprintf(w, "    not run: %s\n", p)
			}
		}
	}
	for _, g := range r.Gaps {
		fmt.Fprintf(w, "~ unexecuted %s %s: %s\n", g.Kind, g.Path, oneLine(g.Label, 120))
	}
	for _, f := range r.Fragments {
		fmt.Fprintf(w, "behavior coverage %s: %d/%d steps (%s), %d/%d interfaces complete, %d unexecuted fail/if branches\n",
			f.Fragment, f.Run, f.Total, pct1(f.Run, f.Total), f.Complete, f.Interfaces, f.Gaps)
	}
	fmt.Fprintf(w, "behavior coverage: %d/%d steps (%s) over %d scenarios, %d unexecuted fail/if branches\n",
		r.Run, r.Total, pct1(r.Run, r.Total), r.Scenarios, len(r.Gaps))
}

// markdown writes the per-fragment and per-interface tables and the
// unexecuted branches; limit bounds the interface and branch lists (0: all).
func (r *behaviorCov) markdown(w io.Writer, limit int) {
	fmt.Fprintf(w, "**Behavior coverage: %d/%d steps (%s) over %d scenarios; %d unexecuted `fail`/`if` branches.**\n\n",
		r.Run, r.Total, pct1(r.Run, r.Total), r.Scenarios, len(r.Gaps))
	fmt.Fprintln(w, "| fragment | interfaces with behavior | fully covered | steps run | steps | coverage | unexecuted fail/if branches |")
	fmt.Fprintln(w, "|---|---:|---:|---:|---:|---:|---:|")
	for _, f := range r.Fragments {
		fmt.Fprintf(w, "| `%s` | %d | %d | %d | %d | %s | %d |\n", f.Fragment, f.Interfaces, f.Complete, f.Run, f.Total, pct1(f.Run, f.Total), f.Gaps)
	}
	fmt.Fprintf(w, "| **all** | %d | %d | %d | %d | %s | %d |\n\n", len(r.Interfaces), r.complete(), r.Run, r.Total, pct1(r.Run, r.Total), len(r.Gaps))

	gaps := map[string]int{}
	for _, g := range r.Gaps {
		gaps[g.Interface]++
	}
	var partial []ifaceCov
	for _, c := range r.Interfaces {
		if c.Run < c.Total {
			partial = append(partial, c)
		}
	}
	sort.SliceStable(partial, func(a, b int) bool {
		ma, mb := partial[a].Total-partial[a].Run, partial[b].Total-partial[b].Run
		if ma != mb {
			return ma > mb
		}
		return partial[a].ID < partial[b].ID
	})
	fmt.Fprintf(w, "Interfaces with unexecuted steps (%d), most unexecuted first:\n\n", len(partial))
	fmt.Fprintln(w, "| interface | fragment | steps run | steps | unexecuted fail/if branches |")
	fmt.Fprintln(w, "|---|---|---:|---:|---:|")
	for i, c := range partial {
		if limit > 0 && i == limit {
			fmt.Fprintf(w, "| … %d more | | | | |\n", len(partial)-limit)
			break
		}
		fmt.Fprintf(w, "| `%s` | `%s` | %d | %d | %d |\n", c.ID, c.Fragment, c.Run, c.Total, gaps[c.ID])
	}
	fmt.Fprintf(w, "\nUnexecuted `fail` and `if` branches (%d):\n\n", len(r.Gaps))
	fmt.Fprintln(w, "| kind | step path | what |")
	fmt.Fprintln(w, "|---|---|---|")
	for i, g := range r.Gaps {
		if limit > 0 && i == limit {
			fmt.Fprintf(w, "| … %d more | | |\n", len(r.Gaps)-limit)
			break
		}
		fmt.Fprintf(w, "| %s | `%s` | %s |\n", g.Kind, g.Path, mdCell(g.Label))
	}
}

func (r *behaviorCov) complete() int {
	n := 0
	for _, c := range r.Interfaces {
		if c.Run == c.Total {
			n++
		}
	}
	return n
}

func mdCell(s string) string { return strings.ReplaceAll(oneLine(s, 120), "|", "\\|") }

// ---- hollow-scenario lint (§12, §13.1 item 7) ----

// writesState reports whether an interface can change state: a store put,
// update, delete or incr, or a behavior step (at any depth) that sets
// state.*. Reads (store get and query) change nothing, so a scenario that
// only reaches them isn't hollow.
func writesState(f *model.Interface) bool {
	if f.Store != nil {
		switch f.Store.Op {
		case "put", "update", "delete", "incr":
			return true
		}
	}
	for _, sp := range behaviorPaths(f) {
		for k := range sp.Step.Set {
			// A dynamic key ("= 'state.x.' + id", DESIGN §13.1 item 14) writes state when
			// its expression mentions a state path.
			if k == "state" || strings.HasPrefix(k, "state.") ||
				(strings.HasPrefix(k, "=") && strings.Contains(k, "'state.")) || strings.Contains(k, "\"state.") {
				return true
			}
		}
	}
	return false
}

// reach follows static calls, emits, declared dynamic targets and publish
// subscribers from the given interfaces.
func reach(x *model.Index, from []string) []string {
	seen := map[string]bool{}
	queue := append([]string(nil), from...)
	for len(queue) > 0 {
		id := queue[0]
		queue = queue[1:]
		if seen[id] {
			continue
		}
		f, ok := x.Interfaces[id]
		if !ok {
			continue
		}
		seen[id] = true
		for _, sp := range behaviorPaths(f) {
			s := sp.Step
			if s.Route != nil {
				queue = append(queue, s.Targets...)
			}
			if s.Call != "" {
				if strings.HasPrefix(s.Call, "=") {
					queue = append(queue, s.Targets...)
				} else {
					queue = append(queue, s.Call)
				}
			}
			if s.Emit != "" {
				queue = append(queue, s.Emit)
			}
			if s.Publish != "" {
				queue = append(queue, x.Subscribers[s.Publish]...)
			}
		}
	}
	out := make([]string, 0, len(seen))
	for id := range seen {
		out = append(out, id)
	}
	sort.Strings(out)
	return out
}

// entries are the interfaces a scenario calls first: its flow's entry, or
// each step's flow entry or interface.
func entries(x *model.Index, sc *model.Scenario) []string {
	var out []string
	flowEntry := func(id string) {
		if f, ok := x.Flows[id]; ok && f.Entry != nil {
			out = append(out, f.Entry.Interface)
		}
	}
	if len(sc.Steps) == 0 {
		flowEntry(sc.Flow)
	}
	for _, st := range sc.Steps {
		if st.Interface != "" {
			out = append(out, st.Interface)
		} else {
			flowEntry(st.Flow)
		}
	}
	return out
}

var stateOrTrace = regexp.MustCompile(`\b(state|trace)\b`)

// hollowFinding is one lint finding.
type hollowFinding struct {
	Kind     string // "no-set", "unchecked-set", "writes-no-readback"
	ID       string // the scenario, or the flow for writes-no-readback
	Fragment string
	Detail   string
}

func (h hollowFinding) String() string {
	switch h.Kind {
	case "writes-no-readback":
		return fmt.Sprintf("hollow: flow %s is tagged writes but no multi-step scenario writes through it and then reads the effect back (%s)", h.ID, h.Fragment)
	case "no-set":
		return fmt.Sprintf("hollow: scenario %s can reach state-writing %s but records no state change (%s)", h.ID, h.Detail, h.Fragment)
	}
	return fmt.Sprintf("hollow: scenario %s changes state (%s) but no expectation mentions state or trace (%s)", h.ID, h.Detail, h.Fragment)
}

// incidentalKinds and incidentalTags mark components whose state is
// incidental bookkeeping (caches, limiters, metrics) rather than an effect a
// scenario should assert on.
var (
	incidentalKinds = map[string]bool{"cache": true, "metrics": true, "limiter": true}
	incidentalTags  = map[string]bool{"incidental": true, "cache": true, "metrics": true, "limiter": true}
)

// incidental reports whether a component, or an ancestor, is declared
// incidental: its kind is cache, metrics or limiter, or it carries one of
// those tags or "incidental". State it sets doesn't count for the hollow
// lint: a run that only touches incidental state counts as changing nothing.
func incidental(x *model.Index, comp string) bool {
	for seen := 0; comp != "" && seen < 64; seen++ {
		c, ok := x.Components[comp]
		if !ok {
			return false
		}
		if incidentalKinds[c.Kind] {
			return true
		}
		for _, t := range c.Tags {
			if incidentalTags[t] {
				return true
			}
		}
		comp = c.Parent
	}
	return false
}

// lintScenario applies the two §12 rules to one run scenario. Neither
// fires when an expectation mentions state or trace. Rule 2 (unchecked-set):
// the run records state set events on a component that isn't incidental.
// Rule 1 (no-set): the run's result is ok, it records no such set, and the
// scenario can reach a state-writing interface of a component that isn't
// incidental; refusals and errors are exempt, since they change nothing by
// design. ok is the run's result.ok.
func lintScenario(x *model.Index, sc *model.Scenario, tr []sim.Event, ok bool, fragment string) *hollowFinding {
	for _, ex := range sc.Expect {
		if stateOrTrace.MatchString(ex) {
			return nil
		}
	}
	sets := map[string]bool{}
	for _, e := range tr {
		if e.Type == "set" && e.Scope == "state" && !incidental(x, e.Component) {
			sets[e.Component] = true
		}
	}
	if len(sets) > 0 {
		comps := make([]string, 0, len(sets))
		for c := range sets {
			comps = append(comps, c)
		}
		sort.Strings(comps)
		return &hollowFinding{"unchecked-set", sc.ID, fragment, "sets " + strings.Join(comps, ", ")}
	}
	if !ok {
		return nil
	}
	var st []string
	for _, id := range reach(x, entries(x, sc)) {
		if f := x.Interfaces[id]; writesState(f) && !incidental(x, f.Component) {
			st = append(st, id)
		}
	}
	if len(st) == 0 {
		return nil
	}
	d := strings.Join(st, ", ")
	if len(st) > 3 {
		d = fmt.Sprintf("%s and %d more", strings.Join(st[:3], ", "), len(st)-3)
	}
	return &hollowFinding{"no-set", sc.ID, fragment, d}
}

// lintWrites applies §13.1 item 7: each flow tagged writes needs a
// multi-step scenario where a step through the flow (its id, or its entry
// interface) is followed by a later step that calls something else.
func lintWrites(doc *model.Document, origin map[string]string) []hollowFinding {
	var out []hollowFinding
	for _, f := range doc.Flows {
		if !hasTag(f.Tags, "writes") {
			continue
		}
		entry := ""
		if f.Entry != nil {
			entry = f.Entry.Interface
		}
		ok := false
		for i := range doc.Scenarios {
			if readsBack(doc.Scenarios[i].Steps, f.ID, entry) {
				ok = true
				break
			}
		}
		if !ok {
			out = append(out, hollowFinding{"writes-no-readback", f.ID, origin[model.KindFlow+"/"+f.ID], ""})
		}
	}
	return out
}

func readsBack(steps []model.ScenarioStep, flow, entry string) bool {
	is := func(s model.ScenarioStep) bool {
		return s.Flow == flow || (s.Flow == "" && entry != "" && s.Interface == entry)
	}
	for i, s := range steps {
		if !is(s) {
			continue
		}
		for _, later := range steps[i+1:] {
			if !is(later) {
				return true
			}
		}
	}
	return false
}

func hasTag(tags []string, t string) bool {
	for _, x := range tags {
		if x == t {
			return true
		}
	}
	return false
}

// hollowReport totals the findings per fragment.
// Advisory reports whether a finding is a warning that doesn't fail the
// check. Rule 1 (no-set) is advisory: sampled on two benchmarks, about a
// third of its hits were real (the rest were no-op or read paths that
// legitimately change nothing), too few for a gate.
func (h hollowFinding) Advisory() bool { return h.Kind == "no-set" }

func printHollow(w io.Writer, fs []hollowFinding) {
	byFrag := map[string]map[string]int{}
	for _, f := range fs {
		mark := "✗"
		if f.Advisory() {
			mark = "!"
		}
		fmt.Fprintf(w, "%s %s\n", mark, f)
		if byFrag[f.Fragment] == nil {
			byFrag[f.Fragment] = map[string]int{}
		}
		byFrag[f.Fragment][f.Kind]++
	}
	frags := make([]string, 0, len(byFrag))
	for k := range byFrag {
		frags = append(frags, k)
	}
	sort.Strings(frags)
	for _, k := range frags {
		m := byFrag[k]
		fmt.Fprintf(w, "hollow %s: %d unchecked state change, %d writes flows without read-back; advisory: %d no state change\n",
			k, m["unchecked-set"], m["writes-no-readback"], m["no-set"])
	}
	n := map[string]int{}
	for _, f := range fs {
		n[f.Kind]++
	}
	fmt.Fprintf(w, "hollow lint: %d failing (%d unchecked state change, %d writes flows without read-back), %d advisory (no state change)\n",
		n["unchecked-set"]+n["writes-no-readback"], n["unchecked-set"], n["writes-no-readback"], n["no-set"])
}

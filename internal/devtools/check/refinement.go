package main

// Cross-level conformance (DESIGN §14.4, §14.11 "Check").
//
// --refinement CHILD (repeatable) loads a child ontology whose refines names a
// component of the parent (the -f documents). Every parent scenario whose
// black-box run calls into that component runs a second time with the
// component refined (model.ComposeRefinements), and the two runs must agree
// exactly at the boundary:
//   - result: the final result's ok, error code and status (and the run's
//     status), and each step's in a multi-step scenario;
//   - calls: the call counts of every other component's interface the
//     scenario's expectations name; their order too when an expectation reads
//     e.seq or e.t;
//   - state: every other component's state the expectations read
//     (state.<c> or state['<c>'], instances included);
//   - expectations: each of the scenario's own expectations passes or fails
//     alike in both runs (§15.4); a flip is a difference.
//
// --refinement-trace SCENARIO prints that scenario's black-box and refined
// traces side by side (refinement_trace.go).
//
// State and calls of the refined component itself are internal to it and not
// compared. Timing never fails the check, nor does state that differs only
// in timing values (a ctx.now stamp read back; timemask.go): the boundary latency (the summed
// durations of the calls into the component) is reported as
// "timing: parent <x> ms, child <y> ms", and --apply-timing FILE writes the
// child's measured latency per implements interface, in latency_ms's shape,
// with latency_source {refined: <child>@<rev>} and whether 14.3's rule lets it
// replace the parent's (a deeper level and no boundary difference). The
// latency is also grouped by outcome class with a proposed
// latency_by_outcome (§14.13; refinement_timing.go).
//
// Each implements pair is also compared schema to schema with item 21's
// comparison, both ways (parent as the spec, child as the model): request and
// response fields, required-ness and types, and the error codes the parent
// declares versus the ones the child can raise.
//
// --max-refinement-diffs N fails the gate above N differences: scenario
// differences plus implements schema issues.

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

type refinementOpts struct {
	Only        *regexp.Regexp
	Max         int    // --max-refinement-diffs; -1 reports only
	ApplyTiming string // --apply-timing FILE
	// ApplyTo is --apply-timing-to FRAGMENT (refinement_apply.go), and
	// DryRun --dry-run: print its diff without writing.
	ApplyTo     string
	DryRun      bool
	ParentLevel string // overrides the parent document's level when set
	Quiet       bool
	// Trace is --refinement-trace: the crossing scenario whose black-box and
	// refined traces are printed side by side.
	Trace string
	// MaxEvents is the refined runs' event cap (--refinement-max-events);
	// 0 means the simulator's default. A scenario's own max_events still
	// wins.
	MaxEvents int
}

// refDiff is one boundary difference in one scenario.
type refDiff struct {
	Kind string // result, calls, order, state
	Msg  string
}

type refScenario struct {
	ID       string
	Diffs    []refDiff
	ParentMS int64 // summed boundary call durations, black box
	ChildMS  int64 // the same, refined
	// StateTiming lists the state the expectations read whose only
	// differences are timing values (timemask.go): reported, not counted.
	StateTiming []string
	BoundaryErr string
	// Inconclusive says why the runs weren't compared: the refined run hit
	// a run cap (its event budget or virtual-time cap) the black-box run
	// didn't, so it has no outcome to compare.
	Inconclusive string
}

type refPair struct {
	Parent, Child string
	Issues        []confIssue
}

// refinementResult is one child's report.
type refinementResult struct {
	File, Child, Component string
	Scenarios              []*refScenario
	Pairs                  []*refPair
	Skipped                int // crossing scenarios the black-box run couldn't run
	// samples are the child's boundary call durations per parent interface,
	// and parentLat the parent's declared latency.
	samples   map[string][]timingSample
	parentLat map[string]*model.Latency
	parentBy  map[string][]model.OutcomeLatency
	levels    [2]string // parent, child
	childRev  string
	// trace holds --refinement-trace's two runs, or traceNote why it has
	// none.
	trace     *refTrace
	traceNote string
}

func (r *refinementResult) differing() int {
	n := 0
	for _, s := range r.Scenarios {
		if len(s.Diffs) > 0 {
			n++
		}
	}
	return n
}

func (r *refinementResult) inconclusive() int {
	n := 0
	for _, s := range r.Scenarios {
		if s.Inconclusive != "" {
			n++
		}
	}
	return n
}

func (r *refinementResult) diffCount() int {
	n := 0
	for _, s := range r.Scenarios {
		n += len(s.Diffs)
	}
	for _, p := range r.Pairs {
		n += len(p.Issues)
	}
	return n
}

// loadRefinement parses one child file.
func loadRefinement(path string) (*model.Document, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	d, err := model.ParseDocument(data)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	// Imports by path resolve against the child's directory (§14.11).
	if err := model.LoadImportFiles(d, filepath.Dir(path), os.ReadFile); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return d, nil
}

// inputsLevel is the parent's level: the first -f document that declares
// one (the merge keeps entities, not document fields).
func inputsLevel(in []merge.Input) string {
	for _, i := range in {
		if i.Doc != nil && i.Doc.Level != "" {
			return i.Doc.Level
		}
	}
	return ""
}

// runRefinements checks each child file against the parent, prints the
// report, writes --apply-timing, and says whether the gate fails.
func runRefinements(w io.Writer, parent *model.Document, paths []string, o refinementOpts) (bool, error) {
	var results []*refinementResult
	for _, p := range paths {
		child, err := loadRefinement(p)
		if err != nil {
			return false, err
		}
		r, err := checkRefinement(parent, child, o)
		if err != nil {
			return false, fmt.Errorf("--refinement %s: %w", p, err)
		}
		r.File = p
		if o.ParentLevel != "" {
			r.levels[0] = o.ParentLevel
		}
		results = append(results, r)
	}
	total := 0
	for _, r := range results {
		r.print(w, o.Quiet)
		r.printTrace(w)
		total += r.diffCount()
	}
	over := o.Max >= 0 && total > o.Max
	if o.Max >= 0 {
		mark := "✓"
		if over {
			mark = "✗"
		}
		fmt.Fprintf(w, "%s refinement differences: %d (max %d)\n", mark, total, o.Max)
	}
	if o.ApplyTiming != "" {
		b, _ := json.MarshalIndent(timingReport(results), "", "  ")
		if err := os.WriteFile(o.ApplyTiming, append(b, '\n'), 0o644); err != nil {
			return over, err
		}
		fmt.Fprintf(w, "refinement timing written to %s\n", o.ApplyTiming)
	}
	if o.ApplyTo != "" {
		if err := applyTimingTo(w, o.ApplyTo, results, o.DryRun); err != nil {
			return over, err
		}
	}
	return over, nil
}

func ifaceIDOf(f *model.Interface) string {
	if f.ID != "" {
		return f.ID
	}
	return f.Component + "." + f.Name
}

// checkRefinement compares the parent's black-box runs with its refined runs.
func checkRefinement(parent, child *model.Document, o refinementOpts) (*refinementResult, error) {
	only := o.Only
	lim := sim.DefaultLimits
	if o.MaxEvents > 0 {
		lim.MaxEvents = o.MaxEvents
	}
	if child.Refines == nil || child.Refines.Component == "" {
		return nil, fmt.Errorf("the child %q declares no refines component", child.ID)
	}
	comp := child.Refines.Component
	found := false
	for i := range parent.Components {
		if parent.Components[i].ID == comp {
			found = true
		}
	}
	if !found {
		return nil, fmt.Errorf("the parent has no component %q (the child %q refines it)", comp, child.ID)
	}
	r := &refinementResult{Child: child.ID, Component: comp, samples: map[string][]timingSample{},
		parentLat: map[string]*model.Latency{}, parentBy: map[string][]model.OutcomeLatency{},
		levels: [2]string{levelOf(parent), levelOf(child)}, childRev: childRevision(child)}

	pairs, err := model.ImplementsPairs(parent, child)
	if err != nil {
		return nil, err
	}
	// The implementing interfaces call into the child's imports: compare
	// against the child with its imports merged in.
	merged := child
	if len(child.ImportDocs) > 0 {
		if merged, err = model.MergeImports(child, child.ImportDocs); err != nil {
			return nil, err
		}
	}
	r.Pairs = implementsConformance(parent, merged, pairs)
	owned := map[string]bool{} // the refined component's parent interfaces
	for i := range parent.Interfaces {
		f := &parent.Interfaces[i]
		if f.Component == comp {
			owned[ifaceIDOf(f)] = true
			r.parentLat[ifaceIDOf(f)] = f.LatencyMS
			r.parentBy[ifaceIDOf(f)] = f.LatencyByOutcome
		}
	}

	refined, err := model.ComposeRefinements(parent, map[string]*model.Document{comp: child}, map[string]string{comp: "refined"})
	if err != nil {
		return nil, err
	}
	// The composer keeps each implemented parent interface's id as a shell
	// forwarding to the child, so results, calls and state compare under
	// the same ids. Timing measures the parent's calls into the component
	// from outside it (black box) against the shells' calls to the
	// implementing interfaces (refined): the child's own latency, without
	// the shell's.
	impl := map[string]string{} // composed implementing interface -> parent interface
	for i := range refined.Interfaces {
		f := &refined.Interfaces[i]
		if f.Implements == "" || !strings.HasPrefix(f.Component, comp+"/") {
			continue
		}
		if _, name, ok := strings.Cut(f.Implements, "."); ok && owned[comp+"."+name] {
			impl[ifaceIDOf(f)] = comp + "." + name
		}
	}
	outside := func(e sim.Event) (string, bool) { return e.Interface, owned[e.Interface] && !internalTo(e.From, comp) }
	fromShell := func(e sim.Event) (string, bool) {
		p, ok := impl[e.Interface]
		if !ok || e.From != comp {
			return "", false
		}
		return p, true
	}

	scs := append([]model.Scenario(nil), parent.Scenarios...)
	sort.Slice(scs, func(a, b int) bool { return scs[a].ID < scs[b].ID })
	for i := range scs {
		sc := &scs[i]
		if only != nil && !only.MatchString(sc.ID) {
			continue
		}
		bb, err := sim.Run(parent, sim.Request{Scenario: sc.ID})
		if err != nil {
			if crossesStatic(sc, owned) {
				r.Skipped++
			}
			continue
		}
		if !crosses(bb.Trace, owned) {
			continue
		}
		rs := &refScenario{ID: sc.ID}
		r.Scenarios = append(r.Scenarios, rs)
		rs.ParentMS, _ = boundaryTiming(bb.Trace, outside)
		rf, err := sim.RunWithLimits(refined, sim.Request{Scenario: sc.ID}, lim)
		if err != nil {
			rs.Diffs = append(rs.Diffs, refDiff{"result", fmt.Sprintf("the refined run failed to run: %v", err)})
			continue
		}
		if capped(rf) && !capped(bb) {
			rs.Inconclusive = fmt.Sprintf("the refined run hit a cap: %s", rf.Summary.Abort)
			continue
		}
		var per map[string][]timingSample
		rs.ChildMS, per = boundarySamples(rf.Trace, fromShell)
		for k, v := range per {
			r.samples[k] = append(r.samples[k], v...)
		}
		rs.Diffs, rs.StateTiming = compareBoundary(sc, comp, owned, bb, rf)
		rs.Diffs = append(rs.Diffs, expectFlips(bb, rf)...)
		if o.Trace != "" && sc.ID == o.Trace {
			r.trace = &refTrace{Scenario: sc.ID, BlackBox: bb.Trace, Refined: rf.Trace}
		}
	}
	if o.Trace != "" && r.trace == nil {
		r.traceNote = traceMiss(parent, o, owned, comp)
	}
	return r, nil
}

// capped says whether a run was ended by one of the simulator's budgets or
// caps (events, loop iterations, emits, timers, virtual time; §13.1 item
// 35) rather than finishing: it has no outcome to compare.
func capped(r *sim.Result) bool {
	if r.Summary.Status != "aborted" {
		return false
	}
	if r.Summary.Caps != nil && r.Summary.Caps.Hit != "" {
		return true
	}
	return strings.Contains(r.Summary.Abort, " budget of ")
}

// internalTo says whether a component (or state key) belongs to the
// refined component comp: comp itself, an instance of it, or a namespaced
// child component.
func internalTo(c, comp string) bool {
	return c == comp || strings.HasPrefix(c, comp+"/") || strings.HasPrefix(c, comp+"@")
}

func crosses(trace []sim.Event, owned map[string]bool) bool {
	for _, e := range trace {
		if e.Type == "call.start" && owned[e.Interface] {
			return true
		}
	}
	return false
}

// crossesStatic guesses from the scenario alone (when it couldn't run)
// whether it enters the component.
func crossesStatic(sc *model.Scenario, owned map[string]bool) bool {
	b, _ := json.Marshal(sc)
	s := string(b)
	for id := range owned {
		if strings.Contains(s, `"`+id+`"`) {
			return true
		}
	}
	return false
}

// boundaryTiming sums the durations of the boundary calls at picks, and
// lists them per parent interface.
func boundaryTiming(trace []sim.Event, at func(sim.Event) (string, bool)) (int64, map[string][]float64) {
	sum, per := boundarySamples(trace, at)
	out := make(map[string][]float64, len(per))
	for k, ss := range per {
		for _, s := range ss {
			out[k] = append(out[k], s.MS)
		}
	}
	return sum, out
}

// boundarySamples is boundaryTiming with each call's outcome.
func boundarySamples(trace []sim.Event, at func(sim.Event) (string, bool)) (int64, map[string][]timingSample) {
	var sum int64
	per := map[string][]timingSample{}
	for _, e := range trace {
		if e.Type != "call.end" {
			continue
		}
		p, ok := at(e)
		if !ok {
			continue
		}
		sum += e.DurationMS
		per[p] = append(per[p], sampleOf(e))
	}
	return sum, per
}

var (
	reStateDot   = regexp.MustCompile(`\bstate\.([A-Za-z0-9_\-]+)`)
	reStateIndex = regexp.MustCompile(`\bstate\[\s*['"]([^'"]+)['"]\s*\]`)
	reQuoted     = regexp.MustCompile(`['"]([^'"]+)['"]`)
	reOrder      = regexp.MustCompile(`\.(seq|t)\b`)
)

// asserted lists what a scenario's expectations read: other components'
// interfaces (calls), state keys, and whether they read event order.
func asserted(sc *model.Scenario, comp string, ifaces map[string]bool) (calls, state []string, order bool) {
	exprs := sc.Expect
	cs, ss := map[string]bool{}, map[string]bool{}
	for _, x := range exprs {
		for _, m := range reQuoted.FindAllStringSubmatch(x, -1) {
			if ifaces[m[1]] {
				cs[m[1]] = true
			}
		}
		for _, re := range []*regexp.Regexp{reStateDot, reStateIndex} {
			for _, m := range re.FindAllStringSubmatch(x, -1) {
				if !internalTo(m[1], comp) {
					ss[m[1]] = true
				}
			}
		}
		if reOrder.MatchString(x) {
			order = true
		}
	}
	return sortedKeys(cs), sortedKeys(ss), order
}

func outcomeKey(o sim.Outcome) string {
	if o.OK {
		return "ok"
	}
	if o.Error == nil {
		return "error"
	}
	return fmt.Sprintf("error %s (status %d)", o.Error.Code, o.Error.Status)
}

// compareBoundary lists how the refined run departs from the black-box run,
// and the state whose only differences are timing values.
func compareBoundary(sc *model.Scenario, comp string, owned map[string]bool, bb, rf *sim.Result) ([]refDiff, []string) {
	var out []refDiff
	var timing []string
	add := func(kind, f string, a ...any) { out = append(out, refDiff{kind, fmt.Sprintf(f, a...)}) }
	if bb.Summary.Status != rf.Summary.Status {
		add("result", "run status: parent %s, child %s %s", bb.Summary.Status, rf.Summary.Status, rf.Summary.Abort)
	}
	if a, b := outcomeKey(bb.Summary.Result), outcomeKey(rf.Summary.Result); a != b {
		add("result", "parent %s, child %s", a, b)
	}
	for i, st := range bb.Summary.Steps {
		if i >= len(rf.Summary.Steps) {
			add("result", "step %d (%s): parent %s, child no step", i+1, st.Interface, outcomeKey(st.Result))
			continue
		}
		if a, b := outcomeKey(st.Result), outcomeKey(rf.Summary.Steps[i].Result); a != b {
			add("result", "step %d (%s): parent %s, child %s", i+1, st.Interface, a, b)
		}
	}

	others := map[string]bool{} // parent interfaces outside the component
	for _, e := range bb.Trace {
		if e.Interface != "" && !owned[e.Interface] {
			others[e.Interface] = true
		}
	}
	for k := range bb.Summary.Calls {
		if !owned[k] {
			others[k] = true
		}
	}
	calls, state, order := asserted(sc, comp, others)
	for _, c := range calls {
		if a, b := bb.Summary.Calls[c], rf.Summary.Calls[c]; a != b {
			add("calls", "calls %s: parent %d, child %d", c, a, b)
		}
	}
	if order && len(calls) > 1 {
		set := map[string]bool{}
		for _, c := range calls {
			set[c] = true
		}
		a, b := callOrder(bb.Trace, set), callOrder(rf.Trace, set)
		if !reflect.DeepEqual(a, b) {
			add("order", "call order: parent %s, child %s", strings.Join(a, " > "), strings.Join(b, " > "))
		}
	}
	for _, k := range state {
		for _, key := range stateKeys(bb.Summary.State, rf.Summary.State, k) {
			a, b := bb.Summary.State[key], rf.Summary.State[key]
			if canonJSON(a) == canonJSON(b) {
				continue
			}
			c := compareState(a, b, spanOf(bb), spanOf(rf))
			if len(c.Diffs) > 0 {
				add("state", "state %s: %s", key, describeLeaves(c.Diffs, 3))
			} else if len(c.Timing) > 0 {
				timing = append(timing, fmt.Sprintf("state %s: %s", key, describeLeaves(c.Timing, 3)))
			}
		}
	}
	return out, timing
}

func callOrder(trace []sim.Event, set map[string]bool) []string {
	var out []string
	for _, e := range trace {
		if e.Type == "call.start" && set[e.Interface] {
			out = append(out, e.Interface)
		}
	}
	return out
}

// stateKeys lists k and its instances (k@i) present in either state.
func stateKeys(a, b map[string]map[string]any, k string) []string {
	ks := map[string]bool{}
	for _, m := range []map[string]map[string]any{a, b} {
		for key := range m {
			if key == k || strings.HasPrefix(key, k+"@") {
				ks[key] = true
			}
		}
	}
	return sortedKeys(ks)
}

func canonJSON(v any) string {
	if v == nil {
		return "null"
	}
	b, err := json.Marshal(v) // map keys sorted
	if err != nil {
		return fmt.Sprintf("%v", v)
	}
	return string(b)
}

func clip(s string) string {
	if len(s) > 160 {
		return s[:157] + "..."
	}
	return s
}

// implementsConformance compares each implements pair with item 21's
// comparison: the parent interface as the spec, the child's as the model,
// so missing means absent from the child and extra absent from the parent.
func implementsConformance(parent, child *model.Document, pairs [][2]string) []*refPair {
	pIdx, cIdx := model.NewIndex(parent), model.NewIndex(child)
	resolve := func(x *model.Index) func(string) (any, bool) {
		return func(r string) (any, bool) { s, ok := x.ResolveSchema(r); return s, ok }
	}
	ifaces := func(d *model.Document) map[string]*model.Interface {
		m := map[string]*model.Interface{}
		for i := range d.Interfaces {
			m[ifaceIDOf(&d.Interfaces[i])] = &d.Interfaces[i]
		}
		return m
	}
	pIf, cIf := ifaces(parent), ifaces(child)
	var out []*refPair
	for _, p := range pairs {
		rp := &refPair{Parent: p[0], Child: p[1]}
		out = append(out, rp)
		pf, cf := pIf[p[0]], cIf[p[1]]
		if pf == nil || cf == nil {
			rp.Issues = append(rp.Issues, confIssue{"missing", "the pair doesn't resolve"})
			continue
		}
		op := &confOp{ID: p[0], Iface: p[1]}
		empty := func(v any, s *shape) *shape {
			if v == nil {
				return &shape{Types: map[string]bool{}}
			}
			return s
		}
		rq := &comparer{op: op, request: true}
		rq.compare("request", "", empty(pf.Request, buildShape(pf.Request, resolve(pIdx), 0)), empty(cf.Request, buildShape(cf.Request, resolve(cIdx), 0)), 0)
		rs := &comparer{op: op}
		rs.compare("response", "", empty(pf.Response, buildShape(pf.Response, resolve(pIdx), 0)), empty(cf.Response, buildShape(cf.Response, resolve(cIdx), 0)), 0)
		pc, cc := boundaryCodes(pf, pIf), boundaryCodes(cf, cIf)
		for _, c := range sortedKeys(pc) {
			if !cc[c] {
				op.Issues = append(op.Issues, confIssue{"error-missing", "error " + c + ": the parent declares it, the child never raises it"})
			}
		}
		for _, c := range sortedKeys(cc) {
			if !pc[c] {
				op.Issues = append(op.Issues, confIssue{"error-extra", "error " + c + ": the child raises it, the parent doesn't declare it"})
			}
		}
		for _, is := range op.Issues {
			is.Msg = strings.NewReplacer("spec ", "parent ", "model ", "child ").Replace(is.Msg)
			rp.Issues = append(rp.Issues, is)
		}
	}
	return out
}

// boundaryCodes lists the error codes an interface can raise at its
// boundary: its declared errors and the codes its behavior fails with, and,
// for each interface it calls, that callee's declared errors when it
// declares any (its contract), else the callee's own boundary codes. A
// callee's internal failures stay behind its declaration: a refinement's
// adapter calling a 1,800-interface child sees the child server's errors,
// not every code raised and handled inside it.
func boundaryCodes(root *model.Interface, ifaces map[string]*model.Interface) map[string]bool {
	out := map[string]bool{}
	seen := map[string]bool{}
	var visit func(f *model.Interface, depth int)
	visit = func(f *model.Interface, depth int) {
		if f == nil || seen[f.ID] || depth > 12 {
			return
		}
		seen[f.ID] = true
		for _, e := range f.Errors {
			if e.Code != "" {
				out[normName(e.Code)] = true
			}
		}
		if depth > 0 && len(f.Errors) > 0 {
			return
		}
		walkConfSteps(f.Behavior, func(s model.Step) {
			if len(s.Fail) > 0 {
				var fs struct {
					Code any `json:"code"`
				}
				if json.Unmarshal(s.Fail, &fs) == nil {
					if c, ok := fs.Code.(string); ok && !strings.HasPrefix(c, "=") {
						out[normName(c)] = true
					}
				}
			}
			if s.Call != "" {
				visit(ifaces[s.Call], depth+1)
			}
		})
	}
	visit(root, 0)
	return out
}

func (r *refinementResult) print(w io.Writer, quiet bool) {
	inc := ""
	if n := r.inconclusive(); n > 0 {
		inc = fmt.Sprintf(", %d inconclusive", n)
	}
	fmt.Fprintf(w, "refinement %s <- %s: %d scenarios, %d equal, %d differ%s\n",
		r.Component, r.Child, len(r.Scenarios), len(r.Scenarios)-r.differing()-r.inconclusive(), r.differing(), inc)
	if r.Skipped > 0 {
		fmt.Fprintf(w, "  ! %d scenarios crossing %s didn't run black box (not compared)\n", r.Skipped, r.Component)
	}
	var pms, cms int64
	stateTiming := 0
	for _, s := range r.Scenarios {
		if s.Inconclusive == "" {
			pms += s.ParentMS
			cms += s.ChildMS
		}
		for _, d := range s.Diffs {
			fmt.Fprintf(w, "  ✗ %s: %s: %s\n", s.ID, d.Kind, d.Msg)
		}
		if s.Inconclusive != "" {
			fmt.Fprintf(w, "  ? %s: not compared: %s\n", s.ID, s.Inconclusive)
		}
		if s.Inconclusive == "" && s.ParentMS != s.ChildMS && !quiet {
			fmt.Fprintf(w, "  ~ %s: timing: parent %d ms, child %d ms\n", s.ID, s.ParentMS, s.ChildMS)
		}
		if len(s.StateTiming) > 0 {
			stateTiming++
			if !quiet {
				for _, t := range s.StateTiming {
					fmt.Fprintf(w, "  ~ %s: timing: %s\n", s.ID, t)
				}
			}
		}
	}
	fmt.Fprintf(w, "  timing: parent %d ms, child %d ms (boundary calls, compared scenarios; not gated)\n", pms, cms)
	r.printOutcomeTiming(w)
	if stateTiming > 0 {
		fmt.Fprintf(w, "  timing: %d scenarios read back state that differs only in timing values (not gated)\n", stateTiming)
	}
	issues := 0
	for _, p := range r.Pairs {
		issues += len(p.Issues)
	}
	fmt.Fprintf(w, "  implements: %d pairs, %d schema issues\n", len(r.Pairs), issues)
	for _, p := range r.Pairs {
		for _, is := range p.Issues {
			fmt.Fprintf(w, "  ✗ implements %s <- %s: %s %s\n", p.Parent, p.Child, is.Kind, is.Msg)
		}
	}
}

// Levels in depth order (§14.2).
var levelDepth = map[string]int{"system": 0, "service": 1, "logic": 2, "runtime": 3, "machine": 4}

func levelOf(d *model.Document) string {
	if d.Level == "" {
		return "system"
	}
	return d.Level
}

// childRevision names the child's revision for latency_source: its source
// SHA when it records one, else "local" (an unstored file).
func childRevision(d *model.Document) string {
	if d.Source != nil && d.Source.SHA != "" {
		return d.Source.SHA
	}
	return "local"
}

type timingEntry struct {
	Interface     string               `json:"interface"`
	ImplementedBy string               `json:"implemented_by,omitempty"`
	LatencyMS     *model.Latency       `json:"latency_ms,omitempty"`
	LatencySource *model.LatencySource `json:"latency_source,omitempty"`
	ParentLatency *model.Latency       `json:"parent_latency_ms,omitempty"`
	// ParentByOutcome is the parent's own latency_by_outcome, when it has one.
	ParentByOutcome []model.OutcomeLatency `json:"parent_latency_by_outcome,omitempty"`
	Samples         int                    `json:"samples"`
	// Outcomes are the samples per outcome class, and LatencyByOutcome the
	// list they propose (§14.13), under the same latency_source.
	Outcomes         []outcomeClass         `json:"outcomes,omitempty"`
	LatencyByOutcome []model.OutcomeLatency `json:"latency_by_outcome,omitempty"`
	Applies          bool                   `json:"applies"`
	Reason           string                 `json:"reason,omitempty"`
}

type timingRefinement struct {
	Component    string        `json:"component"`
	Child        string        `json:"child"`
	File         string        `json:"file"`
	ParentLevel  string        `json:"parent_level"`
	ChildLevel   string        `json:"child_level"`
	Scenarios    int           `json:"scenarios"`
	Differ       int           `json:"differ"`
	Inconclusive int           `json:"inconclusive,omitempty"`
	Interfaces   []timingEntry `json:"interfaces"`
}

// timingReport is --apply-timing's output: per implements interface, the
// child's measured boundary latency as a latency_ms value ({min, max}, or a
// number when constant) and its latency_source, for the parent's owner to
// apply. applies follows §14.3: the child is at a deeper level and its
// boundary scenarios all match.
func timingReport(results []*refinementResult) map[string]any {
	var out []timingRefinement
	for _, r := range results {
		tr := timingRefinement{Component: r.Component, Child: r.Child, File: r.File,
			ParentLevel: r.levels[0], ChildLevel: r.levels[1], Scenarios: len(r.Scenarios), Differ: r.differing(), Inconclusive: r.inconclusive()}
		deeper := levelDepth[r.levels[1]] > levelDepth[r.levels[0]]
		for _, p := range r.Pairs {
			e := timingEntry{Interface: p.Parent, ImplementedBy: p.Child, ParentLatency: r.parentLat[p.Parent],
				ParentByOutcome: r.parentBy[p.Parent]}
			s := r.samples[p.Parent]
			e.Samples = len(s)
			if len(s) > 0 {
				lo, hi := s[0].MS, s[0].MS
				for _, v := range s {
					lo, hi = min(lo, v.MS), max(hi, v.MS)
				}
				e.LatencyMS = &model.Latency{Min: lo, Max: hi}
				e.Outcomes = outcomeClasses(s)
				e.LatencyByOutcome = proposeByOutcome(e.Outcomes)
				e.LatencySource = &model.LatencySource{Refined: r.Child + "@" + r.childRev}
			}
			switch {
			case len(s) == 0:
				e.Reason = "no scenario called it"
			case !deeper:
				e.Reason = fmt.Sprintf("the child (%s) is not deeper than the parent (%s)", r.levels[1], r.levels[0])
			case r.differing() > 0:
				e.Reason = fmt.Sprintf("%d boundary scenarios differ", r.differing())
			case r.inconclusive() > 0:
				e.Reason = fmt.Sprintf("%d boundary scenarios are inconclusive", r.inconclusive())
			default:
				e.Applies = true
			}
			tr.Interfaces = append(tr.Interfaces, e)
		}
		out = append(out, tr)
	}
	return map[string]any{"refinements": out}
}

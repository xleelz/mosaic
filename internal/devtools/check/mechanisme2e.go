package main

// Gate 2 of the mechanism list (DESIGN §13.1 item 39): mutation. For each
// reached mechanism, rerun scenarios that reach it with its interfaces
// disabled (sim.Limits.DisabledInterfaces), and require that a boundary
// expectation then fails. A mechanism whose removal no boundary expectation
// notices doesn't reach the boundary: it is a shell, or its scenarios don't
// check it.

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"regexp"
	"runtime"
	"slices"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

var (
	mechanismE2E          = flag.Bool("mechanism-e2e", false, "with --mechanisms, rerun each reached mechanism's scenarios with its interfaces disabled and call it a shell when no boundary expectation fails (DESIGN §13.1 item 39)")
	mechanismE2EScenarios = flag.Int("mechanism-e2e-scenarios", 0, "with --mechanism-e2e, the most scenarios run per mechanism, chosen deterministically, those starting at a boundary entry first (0: every one, so a capped-out shell is never reported; a cap is faster and can only add shells)")
	mechanismE2EWorkers   = flag.Int("mechanism-e2e-workers", min(runtime.NumCPU(), 8), "with --mechanism-e2e, how many mechanisms run at once")
	mechanismE2EVariant   = flag.String("mechanism-e2e-variant", "zero", "with --mechanism-e2e, what a disabled interface answers: zero (its usual result's shape with every value emptied), empty ({}), or fail (an error)")
	maxShellMechanisms    = flag.Int("max-shell-mechanisms", -1, "with --mechanisms, run --mechanism-e2e and exit 1 when more than N mechanisms are shells (unset: recorded, not gated)")
)

// e2eVariants names the mutation variants.
var e2eVariants = map[string]bool{"zero": true, "empty": true, "fail": true}

// racingScenario selects what exploration owns (the gate's --explore
// 'race|concurr'): a tag or id word naming a race, concurrency or
// exploration. Their expectations may hold on one schedule only.
var racingScenario = regexp.MustCompile(`(?i)(^|[-_.:])(race[sd]?|racing|concurr\w*|explor\w*)`)

// baseRun is what an unmutated run of a scenario shows Gate 2.
type baseRun struct {
	Passed     bool
	Assertions []sim.Assertion
	// Reach holds the tracked interfaces the trace calls, mocked calls aside:
	// true when something in the model called it, false when only the
	// scenario entered it.
	Reach map[string]bool
	// Shape is each reached interface's successful results, emptied.
	Shape map[string]any
	// Refused holds the reached interfaces that answered an error at least
	// once, so that removing them fails a check of that refusal.
	Refused map[string]bool
}

// recordBase reads the tracked interfaces out of a finished run.
func recordBase(res *sim.Result, track map[string]bool) *baseRun {
	b := &baseRun{Passed: res.Summary.Passed, Assertions: res.Summary.Assertions, Reach: map[string]bool{}, Shape: map[string]any{}, Refused: map[string]bool{}}
	mocked := map[int]bool{}
	for i := range res.Trace {
		if e := &res.Trace[i]; e.Type == "call.end" && e.Mock {
			mocked[e.Span] = true
		}
	}
	for i := range res.Trace {
		e := &res.Trace[i]
		if !track[e.Interface] || mocked[e.Span] {
			continue
		}
		switch e.Type {
		case "call.start":
			b.Reach[e.Interface] = b.Reach[e.Interface] || e.Parent != 0
		case "call.end":
			if e.OK != nil && *e.OK && e.Output != nil {
				b.Shape[e.Interface] = mergeZero(b.Shape[e.Interface], zeroShape(e.Output))
			}
			if e.Error != nil {
				b.Refused[e.Interface] = true
			}
		}
	}
	return b
}

// zeroShape keeps a value's shape and empties its values: the same keys,
// lists empty, strings "", numbers 0, booleans false. A caller reading a
// field gets an empty value instead of a missing-key abort, so the absence
// travels on to what the caller does with it.
func zeroShape(v any) any {
	switch t := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, e := range t {
			out[k] = zeroShape(e)
		}
		return out
	case []any:
		return []any{}
	case string:
		return ""
	case bool:
		return false
	case int:
		return 0
	case int64:
		return int64(0)
	case uint64:
		return uint64(0)
	case float64:
		return float64(0)
	case json.Number:
		return int64(0)
	}
	return nil
}

// mergeZero is the union of two emptied shapes.
func mergeZero(a, b any) any {
	am, aok := a.(map[string]any)
	bm, bok := b.(map[string]any)
	if !aok || !bok {
		if a != nil {
			return a
		}
		return b
	}
	for k, v := range bm {
		am[k] = mergeZero(am[k], v)
	}
	return am
}

// e2eOpts configure Gate 2.
type e2eOpts struct {
	Scenarios, Workers int
	Variant            string
}

// e2eRun is one scenario's rerun under a mutation.
type e2eRun struct {
	Scenario string
	Disabled []string
	Survived []string // the boundary expectations that held
	Internal []string // failed, but they name internals: they don't count
	Abort    string   // an abort that didn't count, and why
	Refusal  string   // failed, but only checks a refusal the interface made
}

// mechE2E is Gate 2's evidence on one mechanism.
type mechE2E struct {
	Reaching int      // scenarios whose trace reaches it
	Excluded int      // of those, racing or exploration, or failing unmutated
	Direct   int      // of those, entering it directly at a non-boundary interface
	Runs     []e2eRun // the reruns, in order; a caught one is last
	Caught   string   // what noticed the removal: "<scenario>: <expectation>"
	Constant []string // when every reached interface returns a constant
	// Weak lists, for a mechanism of several interfaces, the listed interfaces
	// whose own removal nothing notices: the rest of the mechanism proved it
	// reaches the boundary, and these didn't.
	Weak []weakInterface
	// AbortOnly: an abort noticed the removal, and no expectation did.
	AbortOnly bool
}

// weakInterface is one interface of a noticed mechanism that didn't prove itself.
type weakInterface struct {
	ID, Why string
	Runs    []e2eRun
}

func (e *mechE2E) print(w io.Writer, listed, unreached []string, verbose bool) {
	fmt.Fprintf(w, "    interfaces: %s\n", strings.Join(listed, ", "))
	if len(unreached) > 0 {
		fmt.Fprintf(w, "    never reached: %s\n", strings.Join(unreached, ", "))
	}
	fmt.Fprintf(w, "    scenarios: %d reach it (%d racing or failing unmutated, %d entering it directly), %d run\n", e.Reaching, e.Excluded, e.Direct, len(e.Runs))
	if e.Caught != "" {
		fmt.Fprintf(w, "    caught by %s\n", oneLine(e.Caught, 200))
	}
	printE2ERuns(w, e.Runs, verbose)
}

// printE2ERuns lists the reruns and what survived them.
func printE2ERuns(w io.Writer, runs []e2eRun, verbose bool) {
	for _, run := range runs {
		fmt.Fprintf(w, "    ran %s with %s disabled: %d boundary expectations survived\n", run.Scenario, strings.Join(run.Disabled, ", "), len(run.Survived))
		limit := 6
		if verbose {
			limit = len(run.Survived)
		}
		for i, s := range run.Survived {
			if i == limit {
				fmt.Fprintf(w, "      survived: … %d more (-v)\n", len(run.Survived)-limit)
				break
			}
			fmt.Fprintf(w, "      survived: %s\n", oneLine(s, 160))
		}
		for _, s := range run.Internal {
			fmt.Fprintf(w, "      failed, but names internals: %s\n", oneLine(s, 160))
		}
		if run.Refusal != "" {
			fmt.Fprintf(w, "      failed, but only checks its refusal: %s\n", oneLine(run.Refusal, 160))
		}
		if run.Abort != "" {
			fmt.Fprintf(w, "      abort not counted: %s\n", oneLine(run.Abort, 200))
		}
	}
}

// e2eCandidate is a scenario a mechanism's mutation can run.
type e2eCandidate struct {
	id       string
	named    int  // words of the mechanism's name in the scenario's id
	refused  bool // a listed interface answered an error in it
	tier     int  // 0: starts at a boundary entry
	boundary int  // the boundary expectations it passes unmutated
	disabled []string
}

// runMechanismE2E settles every reached mechanism: ok, weak or shell, or uncovered
// when only scenarios the gate leaves out reach it.
func runMechanismE2E(r *mechReport, doc *model.Document, base map[string]*baseRun, o e2eOpts) {
	start := time.Now()
	g := newE2EGate(doc, base, o)
	var jobs []*mechResult
	for _, res := range r.Results {
		if res.Status == mechReached {
			jobs = append(jobs, res)
		}
	}
	workers := min(max(o.Workers, 1), max(len(jobs), 1))
	ch := make(chan *mechResult)
	var wg sync.WaitGroup
	for range workers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for res := range ch {
				g.settle(res)
			}
		}()
	}
	for _, res := range jobs {
		ch <- res
	}
	close(ch)
	wg.Wait()
	r.Elapsed, r.Runs, r.Workers, r.Variant = time.Since(start).Round(time.Millisecond).String(), int(g.runs.Load()), workers, o.Variant
}

// e2eGate is what the workers share. All of it is read-only once built,
// except for the run count.
type e2eGate struct {
	doc      *model.Document
	x        *model.Index
	base     map[string]*baseRun
	o        e2eOpts
	internal func(string) string
	entries  map[string]bool   // interfaces that are boundary entries
	start    map[string]string // scenario -> the interface it starts at
	racing   map[string]bool
	ids      []string // the base runs' scenarios, sorted
	runs     atomic.Int64
}

func newE2EGate(doc *model.Document, base map[string]*baseRun, o e2eOpts) *e2eGate {
	x := indexed(doc)
	g := &e2eGate{doc: doc, x: x, base: base, o: o, internal: internalClassifier(doc, x), entries: boundaryEntries(doc, x),
		start: map[string]string{}, racing: map[string]bool{}, ids: sortedKeysOf(base)}
	flowEntry := map[string]string{}
	for _, fl := range doc.Flows {
		if fl.Entry != nil {
			flowEntry[fl.ID] = fl.Entry.Interface
		}
	}
	for i := range doc.Scenarios {
		sc := &doc.Scenarios[i]
		g.racing[sc.ID] = sc.MatchesIDOrTag(racingScenario)
		g.start[sc.ID] = flowEntry[sc.Flow]
		for _, st := range sc.Steps {
			if st.Flow != "" {
				g.start[sc.ID] = flowEntry[st.Flow]
				break
			}
			if st.Interface != "" {
				g.start[sc.ID] = st.Interface
				break
			}
		}
	}
	return g
}

// boundaryEntries is the set of interfaces something outside the system
// enters by: a flow's declared entry, an interface of a boundary component,
// one whose kind is a transport (anything but a plain function, a kernel, a
// store or an unnamed kind), or one named for what enters it from outside,
// whatever its kind (a server calls ServeHTTP, the OS calls main: a label can't
// make them units). A scenario step entering any other plain function is a
// unit test, not a boundary.
func boundaryEntries(doc *model.Document, x *model.Index) map[string]bool {
	out := map[string]bool{}
	for id, f := range x.Interfaces {
		switch f.Kind {
		case "", "function", "kernel", "store":
			if sim.IsBoundaryComponent(x.Components[f.Component]) || f.Name == "serve-http" || f.Name == "main" {
				out[id] = true
			}
		default:
			out[id] = true
		}
	}
	for _, fl := range doc.Flows {
		if fl.Entry != nil {
			out[fl.Entry.Interface] = true
		}
	}
	return out
}

// candidates are the scenarios a mechanism's mutation can run, best first.
// A scenario that reaches a listed interface by a call disables the ones it
// reaches that way: disabling the scenario's own entry too would fail every
// expectation on its result, whatever the mechanism does. A scenario that
// only enters a listed interface runs when that is a boundary entry; a unit
// scenario entering it directly shows nothing about its callers.
func (g *e2eGate) candidates(res *mechResult) ([]e2eCandidate, *mechE2E) {
	ev := &mechE2E{}
	words := mechanismWords(res)
	var out []e2eCandidate
	for _, id := range g.ids {
		b := g.base[id]
		var deep, entered []string
		for _, f := range res.Interfaces {
			if via, hit := b.Reach[f]; hit {
				if via {
					deep = append(deep, f)
				} else {
					entered = append(entered, f)
				}
			}
		}
		if len(deep)+len(entered) == 0 {
			continue
		}
		ev.Reaching++
		if g.racing[id] || !b.Passed {
			ev.Excluded++
			continue
		}
		c := e2eCandidate{id: id, disabled: deep}
		if len(deep) == 0 {
			boundary := entered[:0:0]
			for _, f := range entered {
				if g.entries[f] {
					boundary = append(boundary, f)
				}
			}
			if len(boundary) == 0 {
				ev.Direct++
				continue
			}
			c.disabled = boundary
		}
		if !g.entries[g.start[id]] {
			c.tier = 1
		}
		for _, f := range c.disabled {
			c.refused = c.refused || b.Refused[f]
		}
		c.named = wordsIn(words, id)
		for _, a := range b.Assertions {
			if a.Passed && g.internal(a.Expr) == "" {
				c.boundary++
			}
		}
		out = append(out, c)
	}
	return rankCandidates(out, refusalProves(res.Kind)), ev
}

// mechanismWords are the words naming a mechanism, for ranking scenarios.
func mechanismWords(res *mechResult) map[string]bool {
	out := map[string]bool{}
	id := strings.TrimPrefix(res.ID, res.Area+".")
	for _, w := range strings.FieldsFunc(strings.ToLower(id+" "+res.Name), func(r rune) bool { return !unicode.IsLetter(r) && !unicode.IsDigit(r) }) {
		if len(w) > 2 {
			out[w] = true
		}
	}
	return out
}

// wordsIn counts the words of a scenario id that are in words.
func wordsIn(words map[string]bool, id string) int {
	n := 0
	for _, w := range strings.FieldsFunc(strings.ToLower(id), func(r rune) bool { return !unicode.IsLetter(r) && !unicode.IsDigit(r) }) {
		if words[w] {
			n++
		}
	}
	return n
}

// rankCandidates orders the scenarios a capped mutation tries, deterministically.
// A scenario with no boundary expectation to fail goes last. Within a set of
// disabled interfaces the order is: the boundary entries first, a refusal
// where refusals prove the kind (and last where they don't), the most checks,
// the id. Every other slot goes to the scenario naming the mechanism most, a
// better guess at what checks it than any boundary scenario that merely passes
// through. Then the sets take turns, the largest first, so one interface
// reached everywhere doesn't take every slot from the mechanism's main work.
func rankCandidates(cs []e2eCandidate, refusals bool) []e2eCandidate {
	sort.SliceStable(cs, func(i, j int) bool {
		a, b := cs[i], cs[j]
		switch {
		case (a.boundary == 0) != (b.boundary == 0):
			return b.boundary == 0
		case a.tier != b.tier:
			return a.tier < b.tier
		case a.refused != b.refused:
			return a.refused == refusals
		case a.boundary != b.boundary:
			return a.boundary > b.boundary
		}
		return a.id < b.id
	})
	groups := map[string][]e2eCandidate{}
	var keys []string
	for _, c := range cs {
		k := strings.Join(c.disabled, ",")
		if groups[k] == nil {
			keys = append(keys, k)
		}
		groups[k] = append(groups[k], c)
	}
	sort.SliceStable(keys, func(i, j int) bool { return len(groups[keys[i]][0].disabled) > len(groups[keys[j]][0].disabled) })
	for _, k := range keys {
		groups[k] = alternateNamed(groups[k])
	}
	out := make([]e2eCandidate, 0, len(cs))
	for turn := 0; len(out) < len(cs); turn++ {
		for _, k := range keys {
			if turn < len(groups[k]) {
				out = append(out, groups[k][turn])
			}
		}
	}
	return out
}

// alternateNamed takes turns between cs as ordered and the scenarios naming
// the mechanism, those naming it most first.
func alternateNamed(cs []e2eCandidate) []e2eCandidate {
	byName := slices.Clone(cs)
	sort.SliceStable(byName, func(i, j int) bool { return byName[i].named > byName[j].named })
	out := make([]e2eCandidate, 0, len(cs))
	seen := make(map[string]bool, len(cs))
	take := func(from []e2eCandidate) {
		for _, c := range from {
			if !seen[c.id] {
				seen[c.id] = true
				out = append(out, c)
				return
			}
		}
	}
	for len(out) < len(cs) {
		take(cs)
		take(byName)
	}
	return out
}

// settle runs one mechanism's mutation and gives it its final status.
func (g *e2eGate) settle(res *mechResult) {
	cands, ev := g.candidates(res)
	res.E2E = ev
	if len(cands) == 0 {
		switch {
		case ev.Direct > 0:
			res.Status = mechShell
			res.Detail = fmt.Sprintf("no caller: only %d unit scenarios enter it, directly", ev.Direct)
		default:
			res.Status = mechUncovered
			res.Detail = fmt.Sprintf("only racing or failing scenarios reach it (%d)", ev.Excluded)
		}
		return
	}
	if ev.Constant = g.constantInterfaces(res); ev.Constant != nil {
		res.Status = mechShell
		res.Detail = "every reached interface returns a constant: " + strings.Join(ev.Constant, ", ")
		return
	}
	m := g.mutateUntilCaught(cands, refusalProves(res.Kind))
	ev.Runs, ev.AbortOnly = m.Runs, m.Abort
	if m.Caught == "" {
		res.Status = mechShell
		res.Detail = fmt.Sprintf("removing it fails no boundary expectation in %d scenarios", len(ev.Runs))
		if m.Refusal != "" {
			res.Detail = fmt.Sprintf("in %d scenarios, removing it only fails a check of its refusal (%s); none notices its work when it succeeds", len(ev.Runs), oneLine(m.Refusal, 120))
		}
		return
	}
	ev.Caught = m.Scenario + ": " + m.Caught
	n := len(res.Interfaces) - len(res.Unknown) - len(res.Unreached)
	if n > 1 {
		var byExpectation bool
		ev.Weak, byExpectation = g.weakInterfaces(res)
		ev.AbortOnly = ev.AbortOnly && !byExpectation
	}
	res.Status = mechOK
	switch {
	case ev.AbortOnly:
		res.Status, res.Detail = mechWeak, "no expectation notices its removal, only an abort: "+oneLine(ev.Caught, 200)
	case len(ev.Weak) > 0:
		res.Status, res.Detail = mechWeak, fmt.Sprintf("%d of %d reached interfaces prove nothing alone", len(ev.Weak), n)
	}
	if ev.AbortOnly && len(ev.Weak) > 0 {
		res.Detail += fmt.Sprintf("; and %d of %d reached interfaces prove nothing alone", len(ev.Weak), n)
	}
}

// refusalProves says whether a mechanism of this kind proves itself by
// refusing. A gate's or a retry's work is the refusal. Anything else that
// fails in a scenario still has to show its work where it succeeds: losing
// its validation step isn't evidence of the pipeline behind it.
func refusalProves(kind string) bool { return kind == "gate" || kind == "retry" }

// refusalCheck recognizes an expectation that asserts an error.
var refusalCheck = regexp.MustCompile(`!\s*(steps\.\w+\.)?result\.ok|\.error\b|error_code|status\s*==\s*'error'|\.status\s*==\s*[45]\d\d`)

// mutation is what a capped run of a mechanism's scenarios found.
type mutation struct {
	Runs     []e2eRun
	Scenario string // the scenario that noticed
	Caught   string // what noticed; "" when nothing did
	Abort    bool   // that was an abort, and no expectation in the runs noticed
	Refusal  string // the first check of a refusal that didn't count
}

// mutateUntilCaught runs candidates, up to the cap, until an expectation
// notices. An abort doesn't stop it: an expectation in a later scenario makes
// the mechanism more than ok only by an abort.
func (g *e2eGate) mutateUntilCaught(cands []e2eCandidate, refusals bool) mutation {
	var m mutation
	for i, c := range cands {
		if g.o.Scenarios > 0 && i == g.o.Scenarios {
			break
		}
		run, what, abort := g.mutate(c, refusals)
		m.Runs = append(m.Runs, run)
		if m.Refusal == "" {
			m.Refusal = run.Refusal
		}
		if what == "" {
			continue
		}
		if !abort {
			m.Scenario, m.Caught, m.Abort = c.id, what, false
			return m
		}
		if m.Caught == "" {
			m.Scenario, m.Caught, m.Abort = c.id, what, true
		}
	}
	return m
}

// weakInterfaces disables a noticed mechanism's interfaces one at a time. One
// real interface proves the whole list by its own removal, so a dead part
// (an observer with no caller, an encode whose result nobody reads) would
// otherwise stay hidden behind it. It also reports whether an expectation
// noticed any of them alone.
func (g *e2eGate) weakInterfaces(res *mechResult) (out []weakInterface, byExpectation bool) {
	for _, id := range res.Interfaces {
		if slices.Contains(res.Unknown, id) || slices.Contains(res.Unreached, id) {
			continue
		}
		one := *res
		one.Interfaces = []string{id}
		cands, ev := g.candidates(&one)
		if len(cands) == 0 {
			if ev.Direct > 0 {
				out = append(out, weakInterface{ID: id, Why: fmt.Sprintf("no caller: only %d unit scenarios enter it, directly", ev.Direct)})
			}
			continue
		}
		m := g.mutateUntilCaught(cands, refusalProves(res.Kind))
		byExpectation = byExpectation || (m.Caught != "" && !m.Abort)
		if m.Caught == "" {
			why := fmt.Sprintf("removing it alone fails no boundary expectation in %d scenarios", len(m.Runs))
			if m.Refusal != "" {
				why = fmt.Sprintf("removing it alone only fails a check of its refusal (%s) in %d scenarios", oneLine(m.Refusal, 120), len(m.Runs))
			}
			out = append(out, weakInterface{ID: id, Why: why, Runs: m.Runs})
		}
	}
	return out, byExpectation
}

// constantInterfaces lists the mechanism's reached interfaces when every one
// of them is a constant, nil otherwise. Disabling a constant fails a check of
// that constant, so mutation alone would call it ok.
func (g *e2eGate) constantInterfaces(res *mechResult) []string {
	var out []string
	for _, id := range res.Interfaces {
		if slices.Contains(res.Unreached, id) || slices.Contains(res.Unknown, id) {
			continue
		}
		if !constantBehavior(g.x.Interfaces[id]) {
			return nil
		}
		out = append(out, id)
	}
	return out
}

// constantBehavior reports whether an interface answers the same whatever
// happens: no store, no limits, and steps that only return literal values.
func constantBehavior(f *model.Interface) bool {
	if f.Store != nil || len(f.Limits) > 0 {
		return false
	}
	for _, s := range f.Behavior {
		acts := s.Actions()
		if s.When != "" || len(acts) > 1 || (len(acts) == 1 && acts[0] != "return") {
			return false
		}
		if len(acts) == 1 && strings.Contains(string(s.Return), `"=`) {
			return false
		}
	}
	return true
}

// mutate reruns a scenario with the candidate's interfaces disabled. It
// returns what noticed, or "", and whether that was an abort. An expectation
// counts when it passed unmutated, fails now, and doesn't name internals,
// unless it only checks a refusal a disabled interface made in this scenario
// and refusals don't prove this mechanism (refusalProves). An abort counts by
// abortReachesEntry.
func (g *e2eGate) mutate(c e2eCandidate, refusals bool) (e2eRun, string, bool) {
	g.runs.Add(1)
	run := e2eRun{Scenario: c.id, Disabled: c.disabled}
	b := g.base[c.id]
	lim := sim.DefaultLimits
	lim.DisabledInterfaces = make(map[string]sim.DisabledResult, len(c.disabled))
	for _, id := range c.disabled {
		lim.DisabledInterfaces[id] = g.disabledResult(b, id)
	}
	res, err := sim.RunWithLimits(g.doc, sim.Request{Scenario: c.id}, lim)
	if err != nil {
		run.Abort = err.Error()
		return run, "", false
	}
	if res.Summary.Status == "aborted" {
		if abortReachesEntry(res) {
			return run, "abort on the entry's call chain: " + res.Summary.Abort, true
		}
		run.Abort = res.Summary.Abort
		return run, "", false
	}
	failed := make(map[string]bool, len(res.Summary.Assertions))
	for _, a := range res.Summary.Assertions {
		if !a.Passed {
			failed[a.Expr] = true
		}
	}
	for _, a := range b.Assertions {
		if !a.Passed {
			continue
		}
		boundary := g.internal(a.Expr) == ""
		switch {
		case failed[a.Expr] && boundary && c.refused && !refusals && refusalCheck.MatchString(a.Expr):
			if run.Refusal == "" {
				run.Refusal = a.Expr
			}
		case failed[a.Expr] && boundary:
			return run, a.Expr, false
		case failed[a.Expr]:
			run.Internal = append(run.Internal, a.Expr)
		case boundary:
			run.Survived = append(run.Survived, a.Expr)
		}
	}
	return run, "", false
}

// disabledResult is what a disabled interface answers in this variant.
func (g *e2eGate) disabledResult(b *baseRun, id string) sim.DisabledResult {
	switch g.o.Variant {
	case "fail":
		return sim.DisabledResult{Err: &sim.Error{Code: "mechanism_disabled", Status: 500, Message: id + " is disabled"}}
	case "empty":
		return sim.DisabledResult{}
	}
	v := b.Shape[id]
	if f := g.x.Interfaces[id]; f != nil && f.CanYield() {
		if m, ok := v.(map[string]any); ok { // the simulator wraps a collected stream's value again
			v = m["value"]
		}
	}
	return sim.DisabledResult{Value: v}
}

// abortReachesEntry says whether a mutated run's abort is the mechanism's
// absence surfacing at the boundary. The unmutated run didn't abort, so the
// mutation caused it; what matters is whether a caller outside would see it:
//   - a behavior's evaluation failure counts when the aborting step is on the
//     synchronous call chain from the scenario's entry: it dies as the entry's
//     caller waits. In background work (an emit, a timer, a subscriber) it
//     doesn't count: the boundary answered without it;
//   - a run cap (events, virtual time) counts when an entry call is still open
//     at the cap: the system spun and its caller never got an answer. A
//     background loop spinning after the entry answered doesn't count;
//   - anything else (the depth limit) doesn't count.
func abortReachesEntry(res *sim.Result) bool {
	bySpan := map[int]*sim.Event{}
	ended := map[int]bool{}
	if res.Summary.Caps != nil {
		for i := range res.Trace {
			if e := &res.Trace[i]; e.Type == "call.end" {
				ended[e.Span] = true
			}
		}
		for i := range res.Trace {
			if e := &res.Trace[i]; e.Type == "call.start" && e.Parent == 0 && !e.Async && !ended[e.Span] {
				return true
			}
		}
		return false
	}
	iface, _, ok := strings.Cut(res.Summary.Abort, ".behavior")
	if !ok {
		return false
	}
	var open *sim.Event
	for i := range res.Trace {
		e := &res.Trace[i]
		switch e.Type {
		case "call.start":
			bySpan[e.Span] = e
		case "call.end":
			ended[e.Span] = true
		}
	}
	for i := len(res.Trace) - 1; i >= 0; i-- {
		if e := &res.Trace[i]; e.Type == "call.start" && e.Interface == iface && !ended[e.Span] {
			open = e
			break
		}
	}
	for e := open; e != nil; e = bySpan[e.Parent] {
		if e.Async {
			return false
		}
		if e.Parent == 0 {
			return true
		}
	}
	return false
}

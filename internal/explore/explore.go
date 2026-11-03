// Package explore reruns a scenario under many schedules (DESIGN §15.5):
// systematic perturbations of the simulator's choice points, the
// tie-break of same-time tasks and deliveries, the order of parallel
// branches and fan-out joins, and bounded at_ms jitter. Scenario steps
// that share a lane (§17 item 11) keep their program order: the tie-break
// only reorders steps in different lanes, or in none. A scenario fails
// if any schedule fails its expectations; the failing schedule is kept as
// a replay that reproduces it exactly.
//
// The search is stateless and systematic. Each run takes a prefix of
// forced decisions and the default (0) after it; every point past the
// prefix then offers its other alternatives as new prefixes. Prefixes are
// run fewest deviations from the default first (delay bounding), so
// small bugs are found within a small budget. A partial-order reduction
// (sim.Schedule.Alternatives) drops alternatives that would only reorder
// work touching disjoint components, keys and ctx, or only reading keys
// that no other task writes.
//
// A scenario with invariants (§16.2) is checked on its expect only under
// the default schedule, and on its invariants under every schedule. The
// report counts coverage: choice points seen, alternatives tried, pruned
// and left untried.
package explore

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// Options configure a search.
type Options struct {
	// Schedules is the most schedules to run, the default one included.
	Schedules int
	// JitterMS bounds the at_ms jitter of scenario steps (0: none). It may
	// be fractional: the jitter is in µs (§17 item 4).
	JitterMS float64
	// Limits are the runs' limits (zero: sim.DefaultLimits).
	Limits sim.Limits
}

// Replay is a failing schedule, as written to a replay file.
type Replay struct {
	Version   int     `json:"version"`
	Scenario  string  `json:"scenario"`
	JitterMS  float64 `json:"jitter_ms,omitempty"`
	Decisions []int   `json:"decisions"`
	// Points describe the choice points up to the last decision, for
	// reading; Decisions alone drive the replay.
	Points []sim.Point `json:"points,omitempty"`
	// Failed lists the expectations that failed, or the run's status.
	Failed []string `json:"failed,omitempty"`
}

// Report is the outcome of a search.
type Report struct {
	Scenario string
	Runs     int // schedules run
	// Invariants is set when the scenario has invariants (§16.2): they
	// are checked under every schedule, and expect only on the default.
	Invariants bool
	Coverage   Coverage
	// Exhausted means every schedule the reduction keeps was run.
	Exhausted bool
	// Failure is the first failing schedule, if any; DefaultFailed when
	// it is the default one.
	Failure       *Replay
	DefaultFailed bool
}

// Coverage counts the search (§16.2). A choice point is counted once, in
// the run that first reaches it past its forced prefix; each of its other
// alternatives is then pruned (the reduction shows it equivalent), tried
// (run as a schedule) or untried (kept, but past the budget).
type Coverage struct {
	Points       int `json:"points"`
	Alternatives int `json:"alternatives"`
	Tried        int `json:"tried"`
	Pruned       int `json:"pruned"`
	Untried      int `json:"untried"`
	// ByKind splits the counts by choice point kind (tie, delivery,
	// branch, join, jitter).
	ByKind map[string]*KindCoverage `json:"by_kind,omitempty"`
}

// KindCoverage is the coverage of one kind of choice point.
type KindCoverage struct {
	Points       int `json:"points"`
	Alternatives int `json:"alternatives"`
	Tried        int `json:"tried"`
	Pruned       int `json:"pruned"`
}

func (c *Coverage) kind(k string) *KindCoverage {
	if c.ByKind == nil {
		c.ByKind = map[string]*KindCoverage{}
	}
	if c.ByKind[k] == nil {
		c.ByKind[k] = &KindCoverage{}
	}
	return c.ByKind[k]
}

// String renders the coverage on one line.
func (c Coverage) String() string {
	s := fmt.Sprintf("%d choice points, %d alternatives: %d tried, %d pruned, %d untried", c.Points, c.Alternatives, c.Tried, c.Pruned, c.Untried)
	if len(c.ByKind) == 0 {
		return s
	}
	kinds := make([]string, 0, len(c.ByKind))
	for k := range c.ByKind {
		kinds = append(kinds, k)
	}
	sort.Strings(kinds)
	parts := make([]string, len(kinds))
	for i, k := range kinds {
		kc := c.ByKind[k]
		parts[i] = fmt.Sprintf("%s %d/%d/%d/%d", k, kc.Points, kc.Alternatives, kc.Tried, kc.Pruned)
	}
	return s + " (points/alternatives/tried/pruned: " + strings.Join(parts, ", ") + ")"
}

// prefix is a queued schedule: forced decisions, and the kind of the
// choice point its last decision deviates at.
type prefix struct {
	decisions []int
	kind      string
}

// Explore searches the schedules of one scenario.
func Explore(doc *model.Document, scenario string, o Options) (*Report, error) {
	if o.Schedules <= 0 {
		o.Schedules = 1
	}
	rep := &Report{Scenario: scenario}
	cov := &rep.Coverage
	// buckets[d] holds the prefixes with d deviations from the default.
	buckets := [][]prefix{{{}}}
	for rep.Runs < o.Schedules {
		pf, ok := pop(buckets)
		if !ok {
			rep.Exhausted = true
			break
		}
		res, sch, err := run(doc, scenario, pf.decisions, o.JitterMS, o.Limits)
		if err != nil {
			return nil, err
		}
		rep.Runs++
		if pf.kind != "" {
			cov.Tried++
			cov.kind(pf.kind).Tried++
		}
		first := rep.Runs == 1
		rep.Invariants = rep.Invariants || hasInvariants(res)
		if failed := failures(res, first); failed != nil {
			rep.Failure = replayOf(scenario, o.JitterMS, sch, failed)
			rep.DefaultFailed = first
			cov.Untried = queued(buckets)
			return rep, nil
		}
		devs := deviations(pf.decisions)
		decided := make([]int, len(sch.Points))
		for i, p := range sch.Points {
			decided[i] = p.Choice
		}
		for i := len(pf.decisions); i < len(sch.Points); i++ {
			p := sch.Points[i]
			alts := sch.Alternatives(i)
			kc := cov.kind(p.Kind)
			cov.Points++
			kc.Points++
			cov.Alternatives += p.N - 1
			kc.Alternatives += p.N - 1
			cov.Pruned += p.N - 1 - len(alts)
			kc.Pruned += p.N - 1 - len(alts)
			for _, k := range alts {
				next := append(append([]int{}, decided[:i]...), k)
				d := devs + 1
				for len(buckets) <= d {
					buckets = append(buckets, nil)
				}
				buckets[d] = append(buckets[d], prefix{next, p.Kind})
			}
		}
	}
	cov.Untried = queued(buckets)
	rep.Exhausted = cov.Untried == 0
	return rep, nil
}

// pop takes the first prefix with the fewest deviations.
func pop(buckets [][]prefix) (prefix, bool) {
	for d := range buckets {
		if len(buckets[d]) > 0 {
			p := buckets[d][0]
			buckets[d] = buckets[d][1:]
			return p, true
		}
	}
	return prefix{}, false
}

func queued(buckets [][]prefix) int {
	n := 0
	for _, b := range buckets {
		n += len(b)
	}
	return n
}

func deviations(prefix []int) int {
	n := 0
	for _, c := range prefix {
		if c != 0 {
			n++
		}
	}
	return n
}

// run runs a scenario under the given decisions.
func run(doc *model.Document, scenario string, decisions []int, jitter float64, lim sim.Limits) (*sim.Result, *sim.Schedule, error) {
	sch := &sim.Schedule{Decisions: decisions, JitterMS: jitter}
	if lim.MaxEvents == 0 {
		lim = sim.DefaultLimits
	}
	res, err := sim.RunWithLimits(doc, sim.Request{Scenario: scenario, Schedule: sch}, lim)
	return res, sch, err
}

// hasInvariants reports whether a run checked invariants (§16.2).
func hasInvariants(res *sim.Result) bool {
	for _, a := range res.Summary.Assertions {
		if a.Invariant {
			return true
		}
	}
	return false
}

// failures lists why a run failed, or nil when it passed. Off the default
// schedule, a run with invariants fails only on them (or by aborting): its
// expect, such as which writer wins, holds only on the default (§16.2).
func failures(res *sim.Result, defaultSchedule bool) []string {
	onlyInv := !defaultSchedule && hasInvariants(res)
	out := []string{}
	if res.Summary.Status == "aborted" {
		out = append(out, "aborted: "+res.Summary.Abort)
	}
	for _, a := range res.Summary.Assertions {
		if a.Passed || (onlyInv && !a.Invariant) {
			continue
		}
		s := a.Expr
		if a.Invariant {
			s = "invariant " + s
		}
		if a.Error != "" {
			s += " (" + a.Error + ")"
		}
		out = append(out, s)
	}
	if len(out) == 0 {
		if res.Summary.Passed || onlyInv {
			return nil
		}
		out = append(out, "status "+res.Summary.Status)
	}
	return out
}

func replayOf(scenario string, jitter float64, sch *sim.Schedule, failed []string) *Replay {
	last := -1
	for i, p := range sch.Points {
		if p.Choice != 0 {
			last = i
		}
	}
	rp := &Replay{Version: 1, Scenario: scenario, JitterMS: jitter, Decisions: []int{}, Failed: failed}
	for i := 0; i <= last; i++ {
		rp.Decisions = append(rp.Decisions, sch.Points[i].Choice)
		rp.Points = append(rp.Points, sch.Points[i])
	}
	return rp
}

// Run replays a schedule. diverged is set when a decision no longer fits
// its choice point (the model changed since the replay was written).
func Run(doc *model.Document, rp *Replay, lim sim.Limits) (res *sim.Result, diverged string, err error) {
	res, sch, err := run(doc, rp.Scenario, rp.Decisions, rp.JitterMS, lim)
	if err != nil {
		return nil, "", err
	}
	diverged = sch.Diverged
	if diverged == "" {
		for i, p := range rp.Points {
			if i < len(sch.Points) && (sch.Points[i].Kind != p.Kind || sch.Points[i].N != p.N) {
				diverged = fmt.Sprintf("point %d was %s with %d alternatives, now %s with %d", i, p.Kind, p.N, sch.Points[i].Kind, sch.Points[i].N)
				break
			}
		}
	}
	return res, diverged, nil
}

// Failures lists why a replayed run failed, or nil when it passed: off
// the default schedule, a scenario with invariants fails only on them.
func Failures(res *sim.Result, rp *Replay) []string {
	return failures(res, deviations(rp.Decisions) == 0)
}

// Write writes a replay file.
func (rp *Replay) Write(path string) error {
	b, err := json.MarshalIndent(rp, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0o644)
}

// Load reads a replay file.
func Load(path string) (*Replay, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var rp Replay
	if err := json.Unmarshal(b, &rp); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if rp.Scenario == "" {
		return nil, fmt.Errorf("%s: no scenario", path)
	}
	return &rp, nil
}

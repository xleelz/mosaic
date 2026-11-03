package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"go.yaml.in/yaml/v3"

	"github.com/xleelz/mosaic/internal/model"
)

// Failure matrices (DESIGN §13.1 item 22). The profile names the failures of
// the shared components and edges the system depends on (redis, a scheduler,
// a client disconnect, a node death, a lease loss, an upstream provider),
// each with an owning area. The owner models a failure as a flow tagged
// failure:<id> that some run scenario runs while injecting it (a fault, a
// kill, a cancel or restart step, a failing mock, or seeded state), or skips
// it in skips/<area>.failures.json with a valid reason (the feature rules).
//
// A failure at a seam has two sides (DESIGN §13.1 item 30): it gives sides
// [{owner, role, summary}] instead of one owner, each side's owner tags a
// flow failure:<id>:<role>, and the failure is covered only when every side
// is covered or skipped by that side's owner with {id, role, reason}.

type failure struct {
	ID      string        `yaml:"id"`
	Summary string        `yaml:"summary"`
	Sources []string      `yaml:"sources"`
	Owner   string        `yaml:"owner"`
	On      string        `yaml:"on"`    // the shared component or edge that fails
	Sides   []failureSide `yaml:"sides"` // a two-sided failure: one entry per side, instead of owner
}

// failureSide is one side of a two-sided failure: the area that models it
// and its role at the seam (client-retry, server-dedupe).
type failureSide struct {
	Owner   string `yaml:"owner"`
	Role    string `yaml:"role"`
	Summary string `yaml:"summary"`
}

// loadFailures reads the profile's failures and every skips/*.failures.json
// next to it, keyed by area (the file name before .failures.json).
func loadFailures(profile string) ([]failure, map[string][]featureSkip, error) {
	b, err := os.ReadFile(profile)
	if err != nil {
		return nil, nil, err
	}
	var p struct {
		Failures []failure `yaml:"failures"`
	}
	if err := yaml.Unmarshal(b, &p); err != nil {
		return nil, nil, fmt.Errorf("%s: %w", profile, err)
	}
	skips := map[string][]featureSkip{}
	files, _ := filepath.Glob(filepath.Join(filepath.Dir(profile), "skips", "*.failures.json"))
	for _, f := range files {
		b, err := os.ReadFile(f)
		if err != nil {
			return nil, nil, err
		}
		var s []featureSkip
		if err := json.Unmarshal(b, &s); err != nil {
			return nil, nil, fmt.Errorf("%s: %w", f, err)
		}
		skips[strings.TrimSuffix(filepath.Base(f), ".failures.json")] = s
	}
	return p.Failures, skips, nil
}

type failResult struct {
	failure
	Status string // featCovered, featSkipped, featMissing or featAbsent
	Detail string
	Sides  []sideResult // a two-sided failure's sides, in profile order
}

// sideResult is one side of a two-sided failure, scored like a failure.
type sideResult struct {
	failureSide
	Status, Detail string
}

type failReport struct {
	Results []failResult
	Unknown []string // failure:<id>[:<role>] tags naming no profile failure or side
	Ignored []string // skips of failures the area doesn't own, or unknown ones
	NoOn    []string // failures that name no failing component or edge
	Bad     []string // malformed sides
}

// injects reports whether a scenario makes something fail: a fault (a kill
// included), a cancel, restart or kill step, a failing mock, or seeded state.
func injects(sc *model.Scenario) bool {
	if len(sc.Faults) > 0 || len(sc.State) > 0 {
		return true
	}
	for _, st := range sc.Steps {
		if st.IsControl() {
			return true
		}
	}
	for _, m := range sc.Mocks {
		if len(m.Fail) > 0 {
			return true
		}
	}
	return false
}

// failureRuns maps each flow to whether a run scenario that runs it also
// injects a failure. ran holds the flows the run scenarios run; only is the
// --scenario filter (nil runs every scenario).
func failureRuns(doc *model.Document, ran map[string]bool, only *regexp.Regexp) map[string]bool {
	inj := map[string]bool{}
	for i := range doc.Scenarios {
		sc := &doc.Scenarios[i]
		if only != nil && !only.MatchString(sc.ID) || !injects(sc) {
			continue
		}
		flows := []string{sc.Flow}
		for _, st := range sc.Steps {
			flows = append(flows, st.Flow)
		}
		for _, f := range flows {
			if f != "" && ran[f] {
				inj[f] = true
			}
		}
	}
	return inj
}

// failureCoverage scores each failure. ran holds the flows some run scenario
// runs and injected the flows some run scenario runs while injecting a
// failure (failureRuns). present holds the base names of the -f files (nil
// means every area), as in featureCoverage. A two-sided failure scores each
// side on its own tag and skips, and is covered only when every side is.
func failureCoverage(doc *model.Document, fails []failure, skips map[string][]featureSkip, ran, injected, present map[string]bool) *failReport {
	r := &failReport{}
	known := map[string]*failure{}
	for i := range fails {
		known[fails[i].ID] = &fails[i]
	}
	// unit is a failure (id) or one of its sides (id:role).
	hasSide := func(f *failure, role string) bool {
		for _, sd := range f.Sides {
			if sd.Role == role {
				return true
			}
		}
		return false
	}
	tagged := map[string][]string{}
	for _, f := range doc.Flows {
		for _, t := range f.Tags {
			rest, ok := strings.CutPrefix(t, "failure:")
			if !ok {
				continue
			}
			unit := rest
			if fl := known[rest]; fl != nil && len(fl.Sides) > 0 {
				r.Unknown = append(r.Unknown, fmt.Sprintf("flow %s: %s (a two-sided failure: tag failure:%s:<role>)", f.ID, t, rest))
			} else if fl == nil {
				id, role, cut := strings.Cut(rest, ":")
				switch fl := known[id]; {
				case !cut || fl == nil:
					r.Unknown = append(r.Unknown, fmt.Sprintf("flow %s: %s", f.ID, t))
				case len(fl.Sides) == 0:
					r.Unknown = append(r.Unknown, fmt.Sprintf("flow %s: %s (%s has one owner: tag failure:%s)", f.ID, t, id, id))
				case !hasSide(fl, role):
					r.Unknown = append(r.Unknown, fmt.Sprintf("flow %s: %s (%s has no side %s)", f.ID, t, id, role))
				}
			}
			tagged[unit] = append(tagged[unit], f.ID)
		}
	}
	skipOf := map[string]featureSkip{}
	skipProb := map[string]string{}
	areas := make([]string, 0, len(skips))
	for a := range skips {
		areas = append(areas, a)
	}
	sort.Strings(areas)
	for _, a := range areas {
		for _, s := range skips[a] {
			f := known[s.ID]
			unit := s.ID
			switch {
			case f == nil:
				r.Ignored = append(r.Ignored, fmt.Sprintf("skips/%s.failures.json: %s is not a profile failure", a, s.ID))
				continue
			case len(f.Sides) > 0:
				owner := ""
				for _, sd := range f.Sides {
					if sd.Role == s.Role {
						owner = sd.Owner
					}
				}
				switch {
				case s.Role == "":
					r.Ignored = append(r.Ignored, fmt.Sprintf("skips/%s.failures.json: %s is two-sided; a skip names its side's role", a, s.ID))
					continue
				case !hasSide(f, s.Role):
					r.Ignored = append(r.Ignored, fmt.Sprintf("skips/%s.failures.json: %s has no side %s", a, s.ID, s.Role))
					continue
				case owner != "" && owner != a:
					r.Ignored = append(r.Ignored, fmt.Sprintf("skips/%s.failures.json: %s side %s belongs to %s", a, s.ID, s.Role, owner))
					continue
				}
				unit = s.ID + ":" + s.Role
			case s.Role != "":
				r.Ignored = append(r.Ignored, fmt.Sprintf("skips/%s.failures.json: %s has one owner and no side %s", a, s.ID, s.Role))
				continue
			case f.Owner != "" && f.Owner != a:
				r.Ignored = append(r.Ignored, fmt.Sprintf("skips/%s.failures.json: %s belongs to %s", a, s.ID, f.Owner))
				continue
			}
			if p := skipProblem(s, doc); p != "" {
				skipProb[unit] = p
			} else {
				skipOf[unit] = s
			}
		}
	}
	// score scores one unit: a failure with one owner, or one side.
	score := func(unit, owner string) (status, detail string) {
		status = featMissing
		var inj, plain, idle []string
		for _, fl := range tagged[unit] {
			switch {
			case injected[fl]:
				inj = append(inj, fl)
			case ran[fl]:
				plain = append(plain, fl)
			default:
				idle = append(idle, fl)
			}
		}
		s, skipped := skipOf[unit]
		switch {
		case len(inj) > 0:
			status, detail = featCovered, "flow "+strings.Join(inj, ", ")
		case skipped:
			status, detail = featSkipped, s.Reason
			if s.CoveredBy != "" {
				detail += " (covered by " + s.CoveredBy + ")"
			}
		case len(plain) > 0:
			detail = "no run scenario of flow " + strings.Join(plain, ", ") + " injects a fault, kill, cancel, failing mock or state"
		case len(idle) > 0:
			detail = "no run scenario runs flow " + strings.Join(idle, ", ")
		case skipProb[unit] != "":
			detail = "invalid skip: " + skipProb[unit]
		default:
			detail = "no flow tagged failure:" + unit
		}
		if status == featMissing && present != nil && owner != "" && !present[owner] {
			status = featAbsent
		}
		return
	}
	for _, f := range fails {
		if strings.TrimSpace(f.On) == "" {
			r.NoOn = append(r.NoOn, f.ID)
		}
		res := failResult{failure: f}
		if len(f.Sides) == 0 {
			res.Status, res.Detail = score(f.ID, f.Owner)
			r.Results = append(r.Results, res)
			continue
		}
		if f.Owner != "" {
			r.Bad = append(r.Bad, fmt.Sprintf("failure %s gives both owner and sides; the sides count", f.ID))
		}
		seen := map[string]bool{}
		n := map[string]int{}
		for _, sd := range f.Sides {
			if sd.Owner == "" || sd.Role == "" {
				r.Bad = append(r.Bad, fmt.Sprintf("failure %s has a side without owner or role", f.ID))
			} else if seen[sd.Role] {
				r.Bad = append(r.Bad, fmt.Sprintf("failure %s names side %s twice", f.ID, sd.Role))
			}
			seen[sd.Role] = true
			st, d := score(f.ID+":"+sd.Role, sd.Owner)
			res.Sides = append(res.Sides, sideResult{failureSide: sd, Status: st, Detail: d})
			n[st]++
		}
		// Every side covered or skipped covers the failure (skipped when no
		// side is covered); a missing side makes it missing; otherwise an
		// absent side leaves it to the other areas' merges.
		switch {
		case n[featMissing] > 0:
			res.Status = featMissing
		case n[featAbsent] > 0:
			res.Status = featAbsent
		case n[featCovered] > 0:
			res.Status = featCovered
		default:
			res.Status = featSkipped
		}
		var parts []string
		for _, sd := range res.Sides {
			parts = append(parts, sd.Role+" "+sd.Status)
		}
		res.Detail = strings.Join(parts, ", ")
		r.Results = append(r.Results, res)
	}
	sort.Strings(r.Unknown)
	return r
}

// counts returns covered, skipped, missing and absent over every failure
// or, with an owner, over that owner's failures and sides of two-sided
// failures.
func (r *failReport) counts(owner ...string) (c, s, m, a int) {
	tally := func(st string) {
		switch st {
		case featCovered:
			c++
		case featSkipped:
			s++
		case featAbsent:
			a++
		default:
			m++
		}
	}
	for _, x := range r.Results {
		if len(owner) == 0 {
			tally(x.Status)
			continue
		}
		if len(x.Sides) == 0 {
			if x.Owner == owner[0] {
				tally(x.Status)
			}
			continue
		}
		for _, sd := range x.Sides {
			if sd.Owner == owner[0] {
				tally(sd.Status)
			}
		}
	}
	return
}

// sideCounts returns covered, skipped, missing and absent over the sides of
// every two-sided failure, and how many sides there are.
func (r *failReport) sideCounts() (c, s, m, a, n int) {
	for _, x := range r.Results {
		for _, sd := range x.Sides {
			n++
			switch sd.Status {
			case featCovered:
				c++
			case featSkipped:
				s++
			case featAbsent:
				a++
			default:
				m++
			}
		}
	}
	return
}

// print writes one line per owning area (a two-sided failure counts once
// under each side's owner), every missing failure or side, and the totals;
// verbose also lists the covered and skipped ones. It reports whether any
// failure is missing.
func (r *failReport) print(w io.Writer, verbose bool) bool {
	owners := map[string]bool{}
	for _, x := range r.Results {
		if len(x.Sides) == 0 {
			owners[x.Owner] = true
		}
		for _, sd := range x.Sides {
			owners[sd.Owner] = true
		}
	}
	names := make([]string, 0, len(owners))
	for o := range owners {
		names = append(names, o)
	}
	sort.Strings(names)
	for _, o := range names {
		c, s, m, a := r.counts(o)
		label := first(o, "(no owner)")
		if a > 0 {
			fmt.Fprintf(w, "  failures of %s: %d covered, %d skipped, %d not in this merge\n", label, c, s, a)
			continue
		}
		fmt.Fprintf(w, "  failures of %s: %d covered, %d skipped, %d missing\n", label, c, s, m)
	}
	for _, x := range r.Results {
		if len(x.Sides) > 0 {
			on := ""
			if x.On != "" {
				on = ", on " + x.On
			}
			for _, sd := range x.Sides {
				who := fmt.Sprintf("side %s of %s%s", sd.Role, first(sd.Owner, "no owner"), on)
				if sd.Status == featMissing {
					fmt.Fprintf(w, "✗ failure %s (%s) missing: %s\n", x.ID, who, sd.Detail)
				} else if verbose && sd.Status != featAbsent {
					fmt.Fprintf(w, "  failure %s (%s) %s: %s\n", x.ID, who, sd.Status, sd.Detail)
				}
			}
			if verbose && x.Status != featAbsent {
				fmt.Fprintf(w, "  failure %s (two-sided%s) %s: %s\n", x.ID, on, x.Status, x.Detail)
			}
			continue
		}
		who := first(x.Owner, "no owner")
		if x.On != "" {
			who += ", on " + x.On
		}
		if x.Status == featMissing {
			fmt.Fprintf(w, "✗ failure %s (%s) missing: %s\n", x.ID, who, x.Detail)
		} else if verbose && x.Status != featAbsent {
			fmt.Fprintf(w, "  failure %s (%s) %s: %s\n", x.ID, who, x.Status, x.Detail)
		}
	}
	for _, id := range r.NoOn {
		fmt.Fprintf(w, "! failure %s names no failing component or edge (on)\n", id)
	}
	for _, b := range r.Bad {
		fmt.Fprintf(w, "! %s\n", b)
	}
	for _, u := range r.Unknown {
		fmt.Fprintf(w, "! unknown failure tag on %s\n", u)
	}
	for _, s := range r.Ignored {
		fmt.Fprintf(w, "! failure skip ignored: %s\n", s)
	}
	if sc, ss, sm, sa, n := r.sideCounts(); n > 0 {
		absent := ""
		if sa > 0 {
			absent = fmt.Sprintf(", %d owned by areas not in this merge", sa)
		}
		fmt.Fprintf(w, "failure sides: %d of %d covered, %d skipped, %d missing%s\n", sc, n, ss, sm, absent)
	}
	c, s, m, a := r.counts()
	absent := ""
	if a > 0 {
		absent = fmt.Sprintf(", %d owned by areas not in this merge", a)
	}
	fmt.Fprintf(w, "failures: %d of %d covered, %d skipped, %d missing%s\n", c, len(r.Results), s, m, absent)
	return m > 0
}

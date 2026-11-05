package main

import (
	"encoding/json"
	"fmt"
	"io"
	"regexp"
	"sort"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

type runOpts struct {
	Only                    *regexp.Regexp // run only matching scenarios
	Quiet, Trace, Verbose   bool
	State                   bool // print each run scenario's final state
	Steps, StepsFull        bool // print each run scenario's step results (steps.go)
	Hollow, NoMocks, BehCov bool
	Track                   map[string]bool // interfaces to record each run's reach for, in Base (--mechanisms)
}

type mockUse struct {
	ID           string
	Decl, Called int
}

// runReport is what running the scenarios found.
type runReport struct {
	Passed, Failed int
	FailedIDs      []string        // the failing scenarios, for --stage's attribution (stage.go)
	Executed       map[string]bool // union of Summary.Executed
	Counted        int             // runs whose executed sets are in the union
	Called         map[string]bool // interfaces of every call.start in the run traces
	Flows          map[string]bool // flows the run scenarios run (their flow or a step's)
	Hollow         []hollowFinding
	Mocks          []mockUse
	Cov            *behaviorCov        // with BehCov
	Base           map[string]*baseRun // with Track: per run scenario (mechanisme2e.go)
	HollowFail     bool
	MockFail       bool
}

func originOf(origins map[string]string, kind, id string) string { return origins[kind+"/"+id] }

// runAll runs the selected scenarios in id order and prints their results,
// the mock counts, and, when asked for, the hollow lint and behavior coverage.
func runAll(w io.Writer, doc *model.Document, origins map[string]string, o runOpts) *runReport {
	r := &runReport{Executed: map[string]bool{}, Called: map[string]bool{}, Flows: map[string]bool{}}
	x := model.NewIndex(doc)
	scs := append([]model.Scenario(nil), doc.Scenarios...)
	sort.Slice(scs, func(a, b int) bool { return scs[a].ID < scs[b].ID })
	for i := range scs {
		sc := &scs[i]
		if o.Only != nil && !o.Only.MatchString(sc.ID) {
			continue
		}
		res, err := sim.Run(doc, sim.Request{Scenario: sc.ID})
		switch {
		case err != nil:
			r.Failed++
			r.FailedIDs = append(r.FailedIDs, sc.ID)
			fmt.Fprintf(w, "✗ scenario %s: %v\n", sc.ID, err)
		case !res.Summary.Passed:
			r.Failed++
			r.FailedIDs = append(r.FailedIDs, sc.ID)
			fmt.Fprintf(w, "✗ scenario %s: status %s %s\n", sc.ID, res.Summary.Status, res.Summary.Abort)
			for _, a := range res.Summary.Assertions {
				if !a.Passed {
					fmt.Fprintf(w, "    ✗ %s %s\n", a.Expr, a.Error)
				}
			}
		default:
			r.Passed++
			if !o.Quiet {
				fmt.Fprintf(w, "✓ scenario %s\n", sc.ID)
			}
		}
		called := 0
		if err == nil {
			if o.Steps {
				printSteps(w, &res.Summary, o.StepsFull)
			}
			if o.Trace {
				printTrace(w, res.Trace)
			}
			if o.State {
				printState(w, res.Summary.State)
			}
			for _, wn := range res.Summary.Warnings {
				fmt.Fprintf(w, "    ! %s: %s\n", sc.ID, wn)
			}
			if o.Track != nil {
				if r.Base == nil {
					r.Base = map[string]*baseRun{}
				}
				r.Base[sc.ID] = recordBase(res, o.Track)
			}
			called = mockedCalls(&res.Summary)
			r.Counted++
			if sc.Flow != "" {
				r.Flows[sc.Flow] = true
			}
			for _, st := range sc.Steps {
				if st.Flow != "" {
					r.Flows[st.Flow] = true
				}
			}
			for _, p := range executedOf(&res.Summary) {
				r.Executed[p] = true
			}
			for _, e := range res.Trace {
				if e.Type == "call.start" && e.Interface != "" {
					r.Called[e.Interface] = true
				}
			}
			if o.Hollow {
				if h := lintScenario(x, sc, res.Trace, res.Summary.Result.OK, originOf(origins, model.KindScenario, sc.ID)); h != nil {
					r.Hollow = append(r.Hollow, *h)
				}
			}
		}
		if len(sc.Mocks) > 0 || called > 0 {
			r.Mocks = append(r.Mocks, mockUse{sc.ID, len(sc.Mocks), called})
		}
	}
	fmt.Fprintf(w, "scenarios: %d passed, %d failed\n", r.Passed, r.Failed)

	// Mocks (§11.8) are always counted.
	nDecl, nCalls := 0, 0
	for _, m := range r.Mocks {
		nDecl += m.Decl
		nCalls += m.Called
		mark := "!"
		if o.NoMocks {
			mark = "✗"
		}
		fmt.Fprintf(w, "%s mocks: scenario %s declares %d mocks, %d mocked calls (%s)\n", mark, m.ID, m.Decl, m.Called, originOf(origins, model.KindScenario, m.ID))
	}
	fmt.Fprintf(w, "mocks: %d declared in %d scenarios, %d mocked calls\n", nDecl, len(r.Mocks), nCalls)
	r.MockFail = o.NoMocks && nDecl > 0

	if o.Hollow {
		r.Hollow = append(r.Hollow, lintWrites(doc, origins)...)
		printHollow(w, r.Hollow)
		for _, h := range r.Hollow {
			if !h.Advisory() {
				r.HollowFail = true
			}
		}
	}
	if o.BehCov {
		r.Cov = behaviorCoverage(doc, r.Executed, origins, r.Counted)
		r.Cov.print(w, o.Verbose)
	}
	return r
}

// printState writes a run's final state (DESIGN §13.1 item 12, --state):
// one line per state key, in sorted order, with the state as compact JSON
// (map keys sorted).
func printState(w io.Writer, st map[string]map[string]any) {
	keys := make([]string, 0, len(st))
	for k := range st {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	fmt.Fprintf(w, "    state: %d keys\n", len(keys))
	for _, k := range keys {
		b, err := json.Marshal(st[k])
		if err != nil {
			b = []byte(fmt.Sprintf("%q", err.Error()))
		}
		fmt.Fprintf(w, "      %s: %s\n", k, b)
	}
}

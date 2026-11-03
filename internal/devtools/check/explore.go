package main

// Schedule exploration (DESIGN §15.5; internal/explore):
//
//	--explore REGEX --schedules N [--jitter-ms M] [--replay-dir DIR]
//	--replay FILE
//
// --explore reruns each scenario whose id or one of whose tags (§17 item
// 1) matches REGEX under up to N
// schedules (default 50, the default schedule included): perturbations of
// the simulator's choice points (same-time ties of tasks and deliveries,
// parallel branch and join order, and with --jitter-ms, step at_ms
// jitter), with partial-order reduction. A scenario fails if any schedule
// fails its expectations; that schedule is written to DIR (default
// .mosaic/replay) as <scenario>.replay.json. --replay FILE runs a replay
// file's scenario under its schedule, exactly. Both count as failing
// scenarios in the exit status. A scenario with invariants (§16.2) is
// held to its expect on the default schedule only, and to its invariants
// on every schedule. Each search reports its coverage: choice points
// seen, alternatives tried, pruned and left untried. The ordinary
// scenario runs still happen; use --scenario to limit them.

import (
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/xleelz/mosaic/internal/explore"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

var (
	exploreRE    = flag.String("explore", "", "rerun scenarios whose id or a tag matches this `REGEX` under many schedules (DESIGN §15.5, §17 item 1); a failing schedule is written as a replay file")
	exploreN     = flag.Int("schedules", 50, "with --explore, the most schedules to run per scenario, the default one included")
	exploreJit   = flag.Float64("jitter-ms", 0, "with --explore, also jitter each step's at_ms by up to ±`M` ms (fractional: µs, §17 item 4)")
	exploreDir   = flag.String("replay-dir", filepath.Join(".mosaic", "replay"), "with --explore, the directory replay files are written to")
	exploreRerun = flag.String("replay", "", "run the scenario of this replay `FILE` under its recorded schedule (DESIGN §15.5)")
)

// runExplore runs --explore and --replay, when asked for, and returns the
// number of failing scenarios. run is false when the document has
// validation errors: nothing runs.
func runExplore(w io.Writer, doc *model.Document, run bool) int {
	set := map[string]bool{}
	flag.Visit(func(f *flag.Flag) { set[f.Name] = true })
	if *exploreRE == "" && (set["schedules"] || set["jitter-ms"] || set["replay-dir"]) {
		fail(fmt.Errorf("--schedules, --jitter-ms and --replay-dir need --explore"))
	}
	if *exploreRE == "" && *exploreRerun == "" {
		return 0
	}
	if *exploreN < 1 || *exploreJit < 0 {
		fail(fmt.Errorf("--schedules must be at least 1 and --jitter-ms at least 0"))
	}
	if !run {
		fmt.Fprintln(w, "explore: skipped (validation errors)")
		return 0
	}
	failed := 0
	if *exploreRerun != "" {
		failed += replayFile(w, doc, *exploreRerun)
	}
	if *exploreRE != "" {
		re, err := regexp.Compile(*exploreRE)
		if err != nil {
			fail(fmt.Errorf("--explore: %w", err))
		}
		failed += exploreAll(w, doc, re, explore.Options{Schedules: *exploreN, JitterMS: *exploreJit}, *exploreDir)
	}
	return failed
}

func exploreAll(w io.Writer, doc *model.Document, re *regexp.Regexp, o explore.Options, dir string) int {
	var ids []string
	for i := range doc.Scenarios {
		if doc.Scenarios[i].MatchesIDOrTag(re) {
			ids = append(ids, doc.Scenarios[i].ID)
		}
	}
	sort.Strings(ids)
	passed, failed, runs := 0, 0, 0
	var cov coverageTotal
	for _, id := range ids {
		rep, err := explore.Explore(doc, id, o)
		if err != nil {
			failed++
			fmt.Fprintf(w, "✗ explore %s: %v\n", id, err)
			continue
		}
		runs += rep.Runs
		scope := "budget reached"
		if rep.Exhausted {
			scope = "exhausted"
		}
		inv := ""
		if rep.Invariants {
			inv = ", invariants on every schedule, expect on the default"
		}
		cov.add(rep.Coverage)
		if rep.Failure == nil {
			passed++
			fmt.Fprintf(w, "✓ explore %s: %d schedules (%s%s)\n    coverage: %s\n", id, rep.Runs, scope, inv, rep.Coverage)
			continue
		}
		failed++
		what := fmt.Sprintf("schedule %d of %d", rep.Runs, o.Schedules)
		if rep.DefaultFailed {
			what = "the default schedule"
		}
		path := filepath.Join(dir, safeName(id)+".replay.json")
		werr := os.MkdirAll(dir, 0o755)
		if werr == nil {
			werr = rep.Failure.Write(path)
		}
		fmt.Fprintf(w, "✗ explore %s: fails under %s (%d decisions%s)\n    coverage: %s\n", id, what, len(rep.Failure.Decisions), inv, rep.Coverage)
		for _, f := range rep.Failure.Failed {
			fmt.Fprintf(w, "    ✗ %s\n", f)
		}
		for _, p := range rep.Failure.Points {
			if p.Choice != 0 {
				fmt.Fprintf(w, "    ~ %s at %s ms: alternative %d of %d (%s)\n", p.Kind, strconv.FormatFloat(float64(p.AtUS)/1000, 'f', -1, 64), p.Choice, p.N, p.Label)
			}
		}
		if werr != nil {
			fmt.Fprintf(w, "    ! replay not written: %v\n", werr)
		} else {
			fmt.Fprintf(w, "    replay: %s\n", path)
		}
	}
	fmt.Fprintf(w, "explore: %d scenarios, %d passed every schedule, %d failed (%d schedules run; %s)\n", len(ids), passed, failed, runs, cov.Coverage)
	return failed
}

func replayFile(w io.Writer, doc *model.Document, path string) int {
	rp, err := explore.Load(path)
	if err != nil {
		fail(fmt.Errorf("--replay: %w", err))
	}
	res, diverged, err := explore.Run(doc, rp, sim.Limits{})
	if err != nil {
		fmt.Fprintf(w, "✗ replay %s: scenario %s: %v\n", path, rp.Scenario, err)
		return 1
	}
	if diverged != "" {
		fmt.Fprintf(w, "! replay %s: the model changed since it was written: %s\n", path, diverged)
	}
	if bad := explore.Failures(res, rp); bad != nil {
		fmt.Fprintf(w, "✗ replay %s: scenario %s fails under its schedule\n", path, rp.Scenario)
		for _, f := range bad {
			fmt.Fprintf(w, "    ✗ %s\n", f)
		}
		return 1
	}
	fmt.Fprintf(w, "✓ replay %s: scenario %s passes under its schedule\n", path, rp.Scenario)
	return 0
}

func safeName(id string) string {
	return strings.Map(func(r rune) rune {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9', r == '-', r == '_', r == '.':
			return r
		}
		return '_'
	}, id)
}

// coverageTotal sums the coverage of several searches (§16.2).
type coverageTotal struct{ explore.Coverage }

func (t *coverageTotal) add(c explore.Coverage) {
	t.Points += c.Points
	t.Alternatives += c.Alternatives
	t.Tried += c.Tried
	t.Pruned += c.Pruned
	t.Untried += c.Untried
}

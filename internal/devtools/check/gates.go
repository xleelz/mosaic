package main

// Per-repo check thresholds (DESIGN §16.1), read from the profile's
// `gates:` section with --profile:
//
//	gates:
//	  strict_stubs: true            # --strict-stubs
//	  max_exemption_issues: 0       # --max-exemption-issues N
//	  max_internal_assertions: 0.5  # --max-internal-assertions R (per fragment)
//	  max_clock_ids: 0              # --max-clock-ids N
//	  max_unknown_inputs: 0         # --max-unknown-inputs N
//	  max_racy: 0                   # --max-racy R (per fragment)
//	  max_seam_names: 0             # --max-seam-names N
//	  min_test_reach: 0.5           # --min-test-reach R (per area), with --tests
//	  max_contract_issues: 0        # --max-contract-issues N, with --contract
//	  max_conformance_issues: 0     # --max-conformance-issues N, with --openapi
//	  max_explore_failures: 0       # --max-explore-failures N; unset: recorded, not gated
//	  min_mechanisms: 0.6           # --min-mechanisms R, with --mechanisms; only goes up; unset: recorded, not gated
//	  max_shell_mechanisms: 5       # --max-shell-mechanisms N, with --mechanisms; unset: recorded, not gated
//
// Each gate is the default of its flag; a flag given on the command line
// wins. A profile without `gates:`, or a gate missing from it, takes the
// template default (examples/_profile-template/profile.yaml). A gate whose
// flag needs another (--tests, --contract, --openapi) applies only when
// that one is given. Thresholds tighten only: a max goes down and a min
// (min_test_reach, min_mechanisms) goes up. The pipeline moves them as fixes
// land, and the check prints the value a gate can move to.

import (
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"sort"
	"strings"

	"go.yaml.in/yaml/v3"
)

var (
	maxClockIDs        = flag.Int("max-clock-ids", -1, "run --lint clock-ids and exit 1 when more than N id-shaped templates read now")
	maxUnknownInputs   = flag.Int("max-unknown-inputs", -1, "run --lint unknown-inputs and exit 1 when more than N input keys aren't declared by the target's request schema")
	maxExploreFailures = flag.Int("max-explore-failures", -1, "with --explore, exit 1 only when more than N scenarios fail some schedule (default: any failure fails; with --profile, the profile's gates.max_explore_failures, and when it's unset failures are recorded, not gated)")
	// exploreRecordOnly: --profile is given and its gates don't set
	// max_explore_failures, so exploration failures are reported and their
	// replays written, but don't fail the check.
	exploreRecordOnly bool
)

// profileGateDefs maps each `gates:` key to its flag, the template default
// ("" for none) and the flag it needs.
var profileGateDefs = []struct{ key, flag, def, needs string }{
	{"strict_stubs", "strict-stubs", "true", ""},
	{"max_exemption_issues", "max-exemption-issues", "0", ""},
	{"max_internal_assertions", "max-internal-assertions", "0.5", ""},
	{"max_clock_ids", "max-clock-ids", "0", ""},
	{"max_unknown_inputs", "max-unknown-inputs", "0", ""},
	{"max_racy", "max-racy", "0", ""},
	{"max_seam_names", "max-seam-names", "0", ""},
	{"min_test_reach", "min-test-reach", "0.5", "tests"},
	{"max_contract_issues", "max-contract-issues", "0", "contract"},
	{"max_conformance_issues", "max-conformance-issues", "0", "openapi"},
	{"max_explore_failures", "max-explore-failures", "", "explore"},
}

// applyProfileGates sets the gate flags not given on the command line from
// --profile's gates. Without --profile it does nothing.
func applyProfileGates() {
	if *lintProfileFlag == "" {
		return
	}
	b, err := os.ReadFile(*lintProfileFlag)
	if err != nil {
		fail(fmt.Errorf("--profile: %w", err))
	}
	var p struct {
		Gates map[string]any `yaml:"gates"`
	}
	if err := yaml.Unmarshal(b, &p); err != nil {
		fail(fmt.Errorf("--profile %s: %w", *lintProfileFlag, err))
	}
	known := map[string]bool{}
	for _, d := range profileGateDefs {
		known[d.key] = true
	}
	var unknown []string
	for k := range p.Gates {
		if !known[k] {
			unknown = append(unknown, k)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		fail(fmt.Errorf("--profile %s: unknown gates %s", *lintProfileFlag, strings.Join(unknown, ", ")))
	}
	set := map[string]bool{}
	flag.Visit(func(f *flag.Flag) { set[f.Name] = true })
	for _, d := range profileGateDefs {
		if set[d.flag] || (d.needs != "" && !set[d.needs]) {
			continue
		}
		v, ok := p.Gates[d.key]
		val := d.def
		if ok && v != nil {
			val = fmt.Sprint(v)
		}
		if val == "" {
			if d.key == "max_explore_failures" {
				exploreRecordOnly = true
			}
			continue
		}
		if err := flag.Set(d.flag, val); err != nil {
			fail(fmt.Errorf("--profile %s: gates.%s: %w", *lintProfileFlag, d.key, err))
		}
	}
}

// gatesImplied turns on the lints the count gates imply.
func gatesImplied(lints map[string]bool) {
	if *maxClockIDs >= 0 {
		lints["clock-ids"] = true
	}
	if *maxUnknownInputs >= 0 {
		lints["unknown-inputs"] = true
	}
}

// countGate prints the gate line of a count gate over r's findings (when
// max >= 0) and reports whether the count is above max.
func countGate(w io.Writer, r *integrityReport, flagName string, max int) bool {
	if max < 0 {
		return false
	}
	n := 0
	for _, f := range r.Fragments {
		n += f.Hits
	}
	mark := "✓"
	if n > max {
		mark = "✗"
	}
	fmt.Fprintf(w, "%s %s gate: %d, --%s %d\n", mark, r.Lint, n, flagName, max)
	ratchetHint(w, flagName, float64(n), float64(max))
	return n > max
}

// shareRatchet prints the ratchet hint of a per-fragment share gate.
func shareRatchet(w io.Writer, r *integrityReport, flagName string, max float64) {
	if max < 0 {
		return
	}
	top := 0.0
	for _, f := range r.Fragments {
		if s := f.Share(); s > top {
			top = s
		}
	}
	// Rounded up to 3 places, so the hinted value still passes.
	ratchetHint(w, flagName, math.Ceil(top*1000-1e-9)/1000, max)
}

// ratchetHint says when a gate can be lowered to the measured value.
func ratchetHint(w io.Writer, flagName string, measured, max float64) {
	if measured < max {
		fmt.Fprintf(w, "~ ratchet: --%s can go down to %s (gates in the profile only go down)\n", flagName, trimFloat(measured))
	}
}

func trimFloat(v float64) string {
	if v == float64(int64(v)) {
		return fmt.Sprintf("%d", int64(v))
	}
	return fmt.Sprintf("%.3f", v)
}

// exploreGate turns the failing exploration scenarios into the count that
// fails the check, under --max-explore-failures and the profile's gates.
func exploreGate(w io.Writer, failed int) int {
	switch {
	case *exploreRE == "" && *exploreRerun == "":
		return failed
	case exploreRecordOnly:
		if failed > 0 {
			fmt.Fprintf(w, "~ explore: %d failing scenarios recorded, not gated (the profile's gates set no max_explore_failures)\n", failed)
		}
		return 0
	case *maxExploreFailures >= 0:
		mark := "✓"
		if failed > *maxExploreFailures {
			mark = "✗"
		}
		fmt.Fprintf(w, "%s explore gate: %d failing scenarios, --max-explore-failures %d\n", mark, failed, *maxExploreFailures)
		ratchetHint(w, "max-explore-failures", float64(failed), float64(*maxExploreFailures))
		if failed > *maxExploreFailures {
			return failed
		}
		return 0
	}
	return failed
}

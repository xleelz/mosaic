package main

// Flags of the round-4 lints (DESIGN §13.1 item 33), kept apart from
// main.go: unraised-errors, choice-for-computed and the profile they and
// racy's transitions read.

import "flag"

var (
	maxUnraised     = flag.Float64("max-unraised", -1, "run --lint unraised-errors and exit 1 when a fragment's share of declared errors that nothing raises is above this ratio")
	maxChoice       = flag.Int("max-choice-for-computed", -1, "run --lint choice-for-computed and exit 1 when more than N choice points decide what the code computes from config, a flag or a policy")
	lintProfileFlag = flag.String("profile", "", "generation profile for the lints' naming.state_fields (racy transitions) and config.sources (choice-for-computed); default: the --features or --failures file")
)

// round4Implied turns on the lints their gates imply.
func round4Implied(lints map[string]bool) {
	if *maxUnraised >= 0 {
		lints["unraised-errors"] = true
	}
	if *maxChoice >= 0 {
		lints["choice-for-computed"] = true
	}
}

// anyIntegrityLint reports whether runIntegrity has a lint to run.
func anyIntegrityLint(lints map[string]bool) bool {
	for l := range integrityLints {
		if lints[l] {
			return true
		}
	}
	return false
}

// round4Gates adds the round-4 gates, the code root and the profile (from
// --profile, else the features or failures profile) to g.
func round4Gates(g integrityGates, code, features, failures string) integrityGates {
	g.Unraised, g.ChoiceComputed, g.Code = *maxUnraised, *maxChoice, code
	g.Profile = first(*lintProfileFlag, features, failures)
	return g
}

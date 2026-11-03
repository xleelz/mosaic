package main

// Flags and runner of the input and exemption lints (DESIGN §15.2), kept
// apart from main.go: --lint unknown-inputs, --lint exemptions and
// --max-exemption-issues N.

import (
	"flag"
	"io"

	"github.com/xleelz/mosaic/internal/model"
)

var maxExemptionIssues = flag.Int("max-exemption-issues", -1, "run --lint exemptions and exit 1 when more than N exemptions (racy_in_code, single_writer, reachable_by, choice_ok) have unresolved citations or cited lines that don't support them")

// The --lint names this file implements; main accepts every integrityLints name.
func init() {
	integrityLints["unknown-inputs"] = true
	integrityLints["exemptions"] = true
}

// runInputLints runs unknown-inputs and exemptions when asked for (or implied
// by --max-exemption-issues) and reports whether a gate failed.
func runInputLints(w io.Writer, doc *model.Document, origins map[string]string, lints map[string]bool, code string, quiet bool) bool {
	failed := false
	if lints["unknown-inputs"] {
		r := lintUnknownInputs(doc, origins)
		r.print(w, -1, quiet)
		if countGate(w, r, "max-unknown-inputs", *maxUnknownInputs) { // gates.go
			failed = true
		}
	}
	if lints["exemptions"] || *maxExemptionIssues >= 0 {
		var root *codeRoot
		if code != "" {
			root = newCodeRoot(code)
		}
		rep := lintExemptions(doc, origins, root)
		if rep.print(w, *maxExemptionIssues, code != "", quiet) {
			failed = true
		}
		if *maxExemptionIssues >= 0 {
			ratchetHint(w, "max-exemption-issues", float64(len(rep.Findings)), float64(*maxExemptionIssues)) // gates.go
		}
	}
	return failed
}

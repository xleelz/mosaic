// Command check merges ontology documents, validates the result and runs every
// scenario, offline. Agents building ontology fragments use it without a server.
//
//	go run ./internal/devtools/check -f skeleton.yaml -f fragments/billing.yaml [-o merged.json] [-q] [-v]
//	    [--scenario REGEX] [--scenario-tag TAG,...] [--trace] [--state] [--steps [--steps-full]]
//	    [--behavior-coverage [--behavior-coverage-md FILE]] [--lint hollow,trivial,inert,unscheduled,dataflow,racy,seam-names] [--no-mocks]
//	    [--code DIR [--strict-citations] [--cite-sample N --seed S]]
//	    [--inventory inventory.json [--coverage-md FILE] [--strict-coverage] [--min-modeled R]
//	     [--min-substantive R] [--max-trivial R]]
//	    [--tests test-targets.json [--min-test-reach R]] [--features profile.yaml [--strict-features]]
//	    [--failures profile.yaml [--strict-failures]]
//	    [--mechanisms DIR [--min-mechanisms R] [--mechanisms-json FILE] [--mechanism-e2e [--mechanism-e2e-scenarios N] [--max-shell-mechanisms N]]]
//
// Merging rules: entities with the same kind and id must be identical, except
// that a boundary stub (attributes.boundary: true) yields to a non-stub
// definition, and several stubs of one interface are combined by union.
// Conflicts are errors. -v lists the combined stubs; stubs that disagree on a
// contract scalar (kind, a schema type, an error status) are warnings, and so
// are schemas identical except for their names. Configs and fixtures have one
// owner each (DESIGN §13.1 item 4): identical duplicates merge, differing ones
// are conflicts, and a duplicate marked attributes.boundary is a reference
// that defers to the owner (differences are warnings).
//
// Model quality (DESIGN §12):
//   - --behavior-coverage takes the union of every run scenario's executed
//     step paths and reports, per interface and per fragment (the -f file
//     that defined the interface), the behavior steps no scenario runs, and
//     lists the unexecuted fail steps and if branches. -v lists every
//     unexecuted step; --behavior-coverage-md writes markdown tables.
//   - --lint hollow skips a scenario when an expectation mentions state or
//     trace. Otherwise it fails a run that records state set events (nothing
//     checks them), and a flow tagged writes with no multi-step scenario
//     where a step through the flow is followed by a step that reads
//     something else. As an advisory warning only, it flags an ok run that
//     records no state change though it can reach a state-writing interface
//     (a store put, update, delete or incr, or a behavior that sets state.*).
//   - --lint trivial (with --inventory; DESIGN §13.1 item 15) lists the
//     flow-reachable interfaces that cite an unskipped inventory entry and
//     whose behavior is trivial: no store and, at any depth, no call, if,
//     when, choice, fail, emit or publish, and at most two set steps. It
//     prints the trivial share per fragment; --max-trivial R (which implies
//     the lint) fails when a fragment's share is above R.
//   - --lint inert,unscheduled,dataflow (DESIGN §13.1 item 20; see
//     integrity.go) list owned interfaces with no behavior or store that
//     something calls, scheduled-kind interfaces nothing schedules, and state
//     read but never written; --max-inert, --max-unscheduled and
//     --max-dataflow R gate each share per fragment.
//   - --lint racy (DESIGN §13.1 item 28; see racy.go) lists behaviors that
//     read a store row or state path and later write it with an
//     unconditional put, update or set outside a transact, when the
//     behavior can race; --max-racy R gates the share per fragment.
//   - --lint seam-names (DESIGN §13.1 item 29; see seamnames.go) lists a
//     field read under one spelling and written under another that only
//     matches after normalizing (case, _, - and spaces), at store tables,
//     interface calls, events and topics; --max-seam-names N gates the
//     total.
//   - --lint unraised-errors and choice-for-computed (DESIGN §13.1 item 33;
//     see unraised.go, choicecomputed.go and lintflags.go) list declared
//     errors nothing raises and choice points the code computes from config,
//     a flag or a policy; racy also lists unconditional status transitions
//     as racy (transition). --max-unraised R gates the share per fragment,
//     --max-choice-for-computed N the total; --profile names the profile
//     (naming.state_fields, config.sources), else --features or --failures.
//   - Mock counts are always printed; --no-mocks fails when a scenario
//     declares mocks.
//
// With --code, every cited source (components, interfaces, behavior steps at
// any depth and retry sources, links, flows, flow steps) is resolved against
// the code root and reported per entity: missing paths, lines past the end of
// the file, directories, and packed strings holding several sources.
// --cite-sample prints random citations next to their claims for spot checks.
//
// With --inventory (from internal/devtools/inventory), each entry point is
// scored as covered when an entity some flow reaches cites its lines or is
// named after it, and the rest are grouped by kind and directory. Covered
// means registered (DESIGN §13.1 item 13); each kind's line also counts the
// entries that are modeled: an interface that cites the entry or is named for
// it has a behavior or a store, and some run scenario's trace calls it.
// --min-modeled R prints the modeled level per fragment (the -f files whose
// entities cite an entry's file or a directory above it) and in total, and
// fails when a fragment's modeled / (owned entries − skipped) is below R.
// A fragment that defines no interface with a behavior or a store (a skeleton,
// a fixtures file) is reported as exempt and never fails it. The report also
// counts substantive entries: modeled by an interface whose behavior isn't
// trivial. --min-substantive R gates on substantive / (owned − skipped).
//
// Test-weighted coverage and feature lists (DESIGN §13.1 item 19):
//   - --tests FILE reads [{test, targets, area}] (test_targets.py in the
//     mosaic-generate skill) and reports test reach per area and in total: a
//     test file is reached when an interface some run scenario's trace calls
//     cites one of its target files, or a directory above one. Reach is over
//     the tests with at least one target; the others are counted apart.
//     --min-test-reach R fails when an area's reach is below R; only areas
//     with a fragment in this merge (an -f file named <area>.yaml) are gated.
//     -v lists the unreached tests.
//   - --features PROFILE reads the profile's features [{id, summary, sources,
//     owner}] and skips/<area>.features.json next to it. A feature is covered
//     when a flow tagged feature:<id> exists and a run scenario runs it,
//     skipped when its owner's skip file lists it with a valid reason (not
//     "not modeled", "out of scope", "too large" or "todo"; a "covered by"
//     reason needs covered_by naming an entity), and missing otherwise.
//     --strict-features fails on missing features. A feature whose owner has
//     no fragment in this merge is reported apart, so an area-local run
//     doesn't fail on other areas' features.
//
// Failure matrices (DESIGN §13.1 item 22): --failures PROFILE reads the
// profile's failures [{id, summary, sources, owner, on}] and
// skips/<area>.failures.json, under the feature rules, except that a flow
// tagged failure:<id> covers it only when a run scenario runs the flow while
// injecting a failure (a fault, a cancel, restart or kill step, a failing
// mock, or seeded state). --strict-failures fails on missing failures.
// A two-sided failure (item 30) gives sides [{owner, role, summary}]
// instead of owner: each side is a flow tagged failure:<id>:<role> or a
// skip {id, role, reason} in its owner's file, and the failure is covered
// only when every side is covered or skipped. The report lists each side.
//
// Mechanism lists (DESIGN §13.1 items 38 and 39; see mechanisms.go and
// mechanisme2e.go): --mechanisms DIR measures each mechanism an enumerator
// listed from the code as missing, uncovered, shell, weak, ok or skipped, and
// --mechanism-e2e reruns its scenarios with its interfaces disabled to tell a
// shell from a mechanism a boundary expectation notices. --min-mechanisms R
// only goes up; --max-shell-mechanisms N only goes down.
//
// Contract conformance (DESIGN §13.1 item 21): --openapi FILE (repeatable)
// matches each operation to the interface for it (attributes.method and
// attributes.path, else the name <method>-<path slug>) and reports missing,
// extra, required-mismatch and mistyped request and response fields, success
// and error statuses the two disagree on, unmodeled operations and route
// interfaces matching no operation (see conformance.go).
// --max-conformance-issues N fails above N issues.
//
// Contracts beyond OpenAPI (DESIGN §13.1 item 34): --contract FILE
// (repeatable) compares the interfaces each contract matches (by interface
// id or glob, route, or attributes) with its request, response, errors and,
// from the run scenarios' yields, its stream frames, order and terminator
// (see contract.go). --max-contract-issues N fails above N issues.
//
// Strictness and staging (DESIGN §15.2): --strict-stubs makes stub-vs-stub
// disagreements errors. --stage F (repeatable, or F,G: a joint stage) runs
// the -f fragments' working copies against the other -f files' last-good
// copies in .mosaic/stage/ (--stage-dir), or their working copies when they
// have none; --accept records every staged fragment as last-good, only when
// the run passes, and a failed run is attributed per fragment (stage.go). --lint unknown-inputs lists scenario, step and flow
// entry input keys the target's request schema doesn't declare; --lint
// exemptions checks the citations of racy_in_code, single_writer,
// reachable_by and choice_ok, and --max-exemption-issues N gates them
// (inputlints.go).
//
// Schedule exploration (DESIGN §15.5): --explore REGEX --schedules N
// [--jitter-ms M] reruns matching scenarios under perturbed schedules and
// writes a failing one as a replay file; --replay FILE reproduces it
// (explore.go).
//
// Exit status 1 means conflicts, validation errors, failing scenarios, or,
// when asked for with the strict flags, citation problems or uncovered entry
// points, hollow-lint findings, mocks under --no-mocks, or a fragment below
// --min-modeled, --min-substantive or --min-test-reach, above --max-trivial,
// or missing features under --strict-features or failures under
// --strict-failures, or below --min-mechanisms or above --max-shell-mechanisms.
package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

type files []string

func (f *files) String() string     { return strings.Join(*f, ",") }
func (f *files) Set(v string) error { *f = append(*f, v); return nil }

func main() {
	var in files
	flag.Var(&in, "f", "ontology document (YAML or JSON); repeatable")
	out := flag.String("o", "", "write the merged document as JSON (with --extract-contract, the contract)")
	id := flag.String("id", "", "id of the merged document (default: the first file's)")
	quiet := flag.Bool("q", false, "print only failures and the totals")
	verbose := flag.Bool("v", false, "list combined boundary stubs and every uncovered entry point")
	code := flag.String("code", "", "code root to resolve cited sources against")
	strictCite := flag.Bool("strict-citations", false, "with --code, exit 1 on missing, bad-line or packed citations (directory citations are reported, not refused)")
	sample := flag.Int("cite-sample", 0, "with --code, print N random citations next to the cited code")
	seed := flag.Int64("seed", 1, "random seed for --cite-sample")
	inventory := flag.String("inventory", "", "inventory JSON (internal/devtools/inventory) to measure entry-point coverage against")
	covMD := flag.String("coverage-md", "", "with --inventory, write the coverage tables as markdown")
	only := flag.String("scenario", "", "run only scenarios whose id matches this regular expression")
	trace := flag.Bool("trace", false, "print each run scenario's trace (calls, notes, faults, retries)")
	state := flag.Bool("state", false, "print each run scenario's final state")
	steps := flag.Bool("steps", false, "print each run scenario's step results (as, interface, status, result value as compact JSON, truncated to 200 bytes); a scenario without steps prints its result")
	stepsFull := flag.Bool("steps-full", false, "with --steps, print result values in full")
	behCov := flag.Bool("behavior-coverage", false, "report the behavior steps no run scenario executes, per interface and fragment")
	behCovMD := flag.String("behavior-coverage-md", "", "write the behavior coverage tables as markdown (implies --behavior-coverage)")
	lint := flag.String("lint", "", "comma-separated lints: \"hollow\" (scenarios, DESIGN §12), \"trivial\" (thin behaviors, with --inventory, §13.1 item 15), \"inert\", \"unscheduled\", \"dataflow\" (item 20), \"racy\" (item 28), \"seam-names\" (item 29), \"unraised-errors\", \"choice-for-computed\" (item 33)")
	noMocks := flag.Bool("no-mocks", false, "exit 1 when any scenario uses mocks")
	strictCov := flag.Bool("strict-coverage", false, "with --inventory, exit 1 when an entry point is neither covered nor skipped")
	minModeled := flag.Float64("min-modeled", -1, "with --inventory, print the modeled level per fragment and exit 1 when a fragment's modeled / (owned entries - skipped) is below this ratio")
	minSub := flag.Float64("min-substantive", -1, "with --inventory, print the modeled level per fragment and exit 1 when a fragment's substantive / (owned entries - skipped) is below this ratio")
	maxTrivial := flag.Float64("max-trivial", -1, "with --inventory, run --lint trivial and exit 1 when a fragment's share of trivial entry-citing interfaces is above this ratio")
	maxInert := flag.Float64("max-inert", -1, "run --lint inert and exit 1 when a fragment's share of inert interfaces is above this ratio")
	maxUnsched := flag.Float64("max-unscheduled", -1, "run --lint unscheduled and exit 1 when a fragment's share of unscheduled interfaces is above this ratio")
	maxDataflow := flag.Float64("max-dataflow", -1, "run --lint dataflow and exit 1 when a fragment's share of read-never-written state paths is above this ratio")
	maxRacy := flag.Float64("max-racy", -1, "run --lint racy and exit 1 when a fragment's share of store- or state-writing behaviors that read then write unconditionally is above this ratio")
	maxSeam := flag.Int("max-seam-names", -1, "run --lint seam-names and exit 1 when there are more than N one-field-two-spellings findings")
	testsFile := flag.String("tests", "", "test targets JSON (test_targets.py) to report test reach against: tests whose target files a called interface cites")
	minReach := flag.Float64("min-test-reach", -1, "with --tests, exit 1 when an area's reached / resolved tests is below this ratio")
	featuresFile := flag.String("features", "", "profile.yaml whose features (and skips/<area>.features.json) to report as covered, skipped or missing")
	strictFeat := flag.Bool("strict-features", false, "with --features, exit 1 when a feature is missing")
	failuresFile := flag.String("failures", "", "profile.yaml whose failures (and skips/<area>.failures.json) to report as covered, skipped or missing")
	strictFailures := flag.Bool("strict-failures", false, "with --failures, exit 1 when a failure is missing")
	var openapis files
	flag.Var(&openapis, "openapi", "OpenAPI document to check the model's interfaces against (DESIGN §13.1 item 21); repeatable; a relative path missing here is resolved against --code")
	maxConf := flag.Int("max-conformance-issues", -1, "with --openapi, exit 1 when the conformance issues are more than N")
	var contractFiles files
	flag.Var(&contractFiles, "contract", "contract file (contracts: [{id, match, request, response, errors, stream, sources}]) to check the matched interfaces against (DESIGN §13.1 item 34); repeatable; a relative path missing here is resolved against --code")
	maxContract := flag.Int("max-contract-issues", -1, "with --contract, exit 1 when the contract issues are more than N")
	var refinements files
	flag.Var(&refinements, "refinement", "child ontology refining a component of the -f parent: run the parent's scenarios crossing it black box and refined, and compare the boundary (DESIGN §14.4); repeatable")
	maxRefine := flag.Int("max-refinement-diffs", -1, "with --refinement, exit 1 when the boundary differences and implements schema issues are more than N")
	applyTiming := flag.String("apply-timing", "", "with --refinement, write the child's measured latency per implements interface (latency_ms, latency_source) as JSON to this file")
	applyTo := flag.String("apply-timing-to", "", "with --refinement, write the proposed latency_by_outcome and latency_source onto the implements interfaces of this parent YAML fragment, in place, and print the diff (DESIGN §16.3); pinned interfaces are skipped")
	dryRun := flag.Bool("dry-run", false, "with --apply-timing-to, print the diff without writing")
	refMaxEvents := flag.Int("refinement-max-events", sim.DefaultLimits.MaxEvents, "with --refinement, the refined runs' event cap (a scenario's own max_events still wins); up to 1000000")
	refTrace := flag.String("refinement-trace", "", "with --refinement, print this crossing `SCENARIO`'s black-box and refined traces side by side (DESIGN §15.4)")
	extract := flag.String("extract-contract", "", "write the compose pipeline's contract input for this component of the -f parent to -o (DESIGN §14.3): its interfaces, the scenarios whose run crosses it, observed latency_ms; skips the other checks")
	scopeOut := flag.String("scope-out", "", "with --extract-contract, write the pipeline's scope input (the files the component and its interfaces cite) to this file")
	repo := flag.String("repo", "", "with --scope-out, the scope's repo (the read-only checkout; default --code)")
	parentTask := flag.String("parent-task", "manual", "with --extract-contract, the contract's parent.task")
	parentDoc := flag.String("parent-document", "", "with --extract-contract, the contract's parent.document (default: the first -f path, absolute)")
	maxScenarios := flag.Int("max-scenarios", 0, "with --extract-contract, keep only the first N crossing scenarios (0: all)")
	flag.Parse()
	applyProfileGates() // --profile's gates: defaults of the §16.1 gate flags (gates.go)
	applySimLimits()    // --max-events, --max-iterations, --max-foreach (simlimits.go)
	if len(in) == 0 {
		fmt.Fprintln(os.Stderr, "usage: check -f FILE [-f FILE]... [-o OUT] [-q] [-v] [--scenario RE] [--trace] [--state] [--steps [--steps-full]] [--behavior-coverage [--behavior-coverage-md FILE]] [--lint hollow,trivial,inert,unscheduled,dataflow,racy,seam-names] [--no-mocks] [--code DIR [--strict-citations] [--cite-sample N --seed S]] [--inventory FILE [--coverage-md FILE] [--strict-coverage] [--min-modeled R] [--min-substantive R] [--max-trivial R]] [--tests FILE [--min-test-reach R]] [--features PROFILE [--strict-features]] [--failures PROFILE [--strict-failures]] [--mechanisms DIR [--min-mechanisms R] [--mechanisms-json FILE] [--mechanism-e2e] [--max-shell-mechanisms N]]")
		os.Exit(2)
	}
	lints := map[string]bool{}
	if *lint != "" {
		for _, l := range strings.Split(*lint, ",") {
			l = strings.TrimSpace(l)
			if l != "hollow" && l != "trivial" && !integrityLints[l] && !blackboxLints[l] && !unwrittenLints[l] {
				fmt.Fprintf(os.Stderr, "check: unknown --lint %q (want hollow, trivial, inert, unscheduled, dataflow, racy, seam-names, unwritten-fields, unraised-errors or choice-for-computed, comma-separated)\n", l)
				os.Exit(2)
			}
			lints[l] = true
		}
	}
	if *maxTrivial >= 0 {
		lints["trivial"] = true
	}
	for l, max := range map[string]float64{"inert": *maxInert, "unscheduled": *maxUnsched, "dataflow": *maxDataflow, "racy": *maxRacy, "seam-names": float64(*maxSeam)} {
		if max >= 0 {
			lints[l] = true
		}
	}
	round4Implied(lints) // --max-unraised, --max-choice-for-computed (lintflags.go)
	// --max-internal-assertions (blackbox.go)
	blackboxImplied(lints)
	if lints["trivial"] && *inventory == "" {
		fmt.Fprintln(os.Stderr, "check: --lint trivial and --max-trivial need --inventory")
		os.Exit(2)
	}
	if *minSub >= 0 && *inventory == "" {
		fmt.Fprintln(os.Stderr, "check: --min-substantive needs --inventory")
		os.Exit(2)
	}
	if *behCovMD != "" {
		*behCov = true
	}
	if *minModeled >= 0 && *inventory == "" {
		fmt.Fprintln(os.Stderr, "check: --min-modeled needs --inventory")
		os.Exit(2)
	}
	if *minReach >= 0 && *testsFile == "" {
		fmt.Fprintln(os.Stderr, "check: --min-test-reach needs --tests")
		os.Exit(2)
	}
	if *strictFeat && *featuresFile == "" {
		fmt.Fprintln(os.Stderr, "check: --strict-features needs --features")
		os.Exit(2)
	}
	if *strictFailures && *failuresFile == "" {
		fmt.Fprintln(os.Stderr, "check: --strict-failures needs --failures")
		os.Exit(2)
	}
	if *maxContract >= 0 && len(contractFiles) == 0 {
		fmt.Fprintln(os.Stderr, "check: --max-contract-issues needs --contract")
		os.Exit(2)
	}
	refMaxSet := false
	flag.Visit(func(f *flag.Flag) { refMaxSet = refMaxSet || f.Name == "refinement-max-events" })
	if refMaxSet && len(refinements) == 0 {
		fmt.Fprintln(os.Stderr, "check: --refinement-max-events needs --refinement")
		os.Exit(2)
	}
	if *refMaxEvents < 1 || *refMaxEvents > model.MaxMaxEvents {
		fmt.Fprintf(os.Stderr, "check: --refinement-max-events must be from 1 to %d\n", model.MaxMaxEvents)
		os.Exit(2)
	}
	if *extract == "" && (*scopeOut != "" || *repo != "" || *parentDoc != "" || *maxScenarios != 0) {
		fmt.Fprintln(os.Stderr, "check: --scope-out, --repo, --parent-document and --max-scenarios need --extract-contract")
		os.Exit(2)
	}
	if *extract != "" {
		if *out == "" {
			fmt.Fprintln(os.Stderr, "check: --extract-contract needs -o FILE")
			os.Exit(2)
		}
		if *scopeOut != "" && *repo == "" && *code == "" {
			fmt.Fprintln(os.Stderr, "check: --scope-out needs --repo (or --code)")
			os.Exit(2)
		}
		if len(refinements) > 0 {
			fmt.Fprintln(os.Stderr, "check: --extract-contract and --refinement don't combine")
			os.Exit(2)
		}
	}
	if *dryRun && *applyTo == "" {
		fmt.Fprintln(os.Stderr, "check: --dry-run needs --apply-timing-to")
		os.Exit(2)
	}
	if (*maxRefine >= 0 || *applyTiming != "" || *applyTo != "" || *refTrace != "") && len(refinements) == 0 {
		fmt.Fprintln(os.Stderr, "check: --max-refinement-diffs, --apply-timing, --apply-timing-to and --refinement-trace need --refinement")
		os.Exit(2)
	}
	if *maxConf >= 0 && len(openapis) == 0 {
		fmt.Fprintln(os.Stderr, "check: --max-conformance-issues needs --openapi")
		os.Exit(2)
	}
	if (*strictCite || *sample > 0) && *code == "" {
		fmt.Fprintln(os.Stderr, "check: --strict-citations and --cite-sample need --code")
		os.Exit(2)
	}
	mechList := mechanismsPrepare()          // --mechanisms (mechanisms.go)
	inputs, err := loadInputs(os.Stdout, in) // merge.Load, or --stage's last-good copies (stage.go)
	if err != nil {
		var pe *merge.ParseError
		if errors.As(err, &pe) {
			fmt.Printf("✗ %s: %v\n", pe.Path, pe.Err)
			os.Exit(1)
		}
		fail(err)
	}
	res, err := merge.Merge(inputs)
	if err != nil {
		fail(err)
	}
	bad := len(res.Conflicts) > 0
	for _, c := range res.Conflicts {
		fmt.Printf("✗ conflict: %s\n", c)
	}
	doc, issues := res.Doc, res.Issues
	origins := res.Origins
	stubFiles, disagreements, ownerDiffs := res.StubFiles, res.Disagreements, res.OwnerDiffs
	if *id != "" {
		doc.ID = *id
	}
	// Imports load relative to each -f file; validation follows them, and
	// the checks below see the document with them merged (§15.4, §15.6).
	if err := merge.LoadImports(inputs, doc); err != nil {
		fail(err)
	}
	issues = append(issues, model.ValidateWithImports(doc)...)
	if len(doc.Imports) > 0 && !model.HasErrors(issues) {
		if doc, err = model.MergeImports(doc, doc.ImportDocs); err != nil {
			fail(err)
		}
	}
	errs, warns := 0, 0
	for _, is := range issues {
		if is.Severity == model.SeverityError {
			errs++
			fmt.Printf("✗ %s: %s\n", is.Path, is.Message)
		} else {
			warns++
			if !*quiet {
				fmt.Printf("! %s: %s\n", is.Path, is.Message)
			}
		}
	}
	stubs := res.Stubs
	fmt.Printf("entities: %d components, %d interfaces, %d links, %d schemas, %d flows, %d scenarios (%d boundary stubs)\n",
		len(doc.Components), len(doc.Interfaces), len(doc.Links), len(doc.Schemas), len(doc.Flows), len(doc.Scenarios), stubs)
	fmt.Printf("validation: %d errors, %d warnings\n", errs, warns)
	if *extract != "" {
		if errs > 0 || bad {
			fmt.Fprintln(os.Stderr, "check: --extract-contract needs a parent without validation errors or conflicts")
			os.Exit(1)
		}
		r := *repo
		if r == "" {
			r = *code
		}
		if r != "" {
			if abs, err := filepath.Abs(r); err == nil {
				r = abs
			}
		}
		if err := extractContract(os.Stdout, doc, in, extractOpts{Component: *extract, Out: *out, ScopeOut: *scopeOut,
			Repo: r, ParentTask: *parentTask, ParentDoc: *parentDoc, MaxScenarios: *maxScenarios}); err != nil {
			fail(err)
		}
		return
	}

	// Merge report: combined stubs, scalar disagreements, duplicate schemas.
	if len(stubFiles) > 0 {
		if *verbose {
			keys := make([]string, 0, len(stubFiles))
			for k := range stubFiles {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				fmt.Printf("~ stub %s combined from %s\n", k, strings.Join(stubFiles[k], ", "))
			}
		}
		fmt.Printf("boundary stubs merged by union: %d\n", len(stubFiles))
	}
	warnDisagree, strictBad := strictStubs(os.Stdout, disagreements) // --strict-stubs (stage.go)
	bad = bad || strictBad
	if !*quiet {
		for _, d := range warnDisagree {
			fmt.Printf("! stubs disagree (the union keeps the first): %s\n", d)
		}
		for _, d := range ownerDiffs {
			fmt.Printf("! stub differs from the owner (the owner wins): %s\n", d)
		}
	}
	dups := duplicateSchemas(doc.Schemas)
	if !*quiet {
		for _, d := range dups {
			fmt.Printf("! possible duplicate schemas: %s\n", d)
		}
	}
	if len(res.Refs) > 0 {
		if *verbose {
			keys := make([]string, 0, len(res.Refs))
			for k := range res.Refs {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				fmt.Printf("~ reference %s deferred to %s from %s\n", k, res.Origins[k], strings.Join(res.Refs[k], ", "))
			}
		}
		fmt.Printf("config/fixture boundary references deferred to the owner: %d\n", len(res.Refs))
	}
	if len(disagreements) > 0 || len(ownerDiffs) > 0 || len(dups) > 0 {
		fmt.Printf("merge warnings: %d stub-vs-stub disagreements, %d stub-vs-owner differences, %d possible duplicate schema groups\n", len(disagreements), len(ownerDiffs), len(dups))
	}

	var onlyRE *regexp.Regexp
	if *only != "" {
		re, err := regexp.Compile(*only)
		if err != nil {
			fail(fmt.Errorf("--scenario: %w", err))
		}
		onlyRE = re
	}
	onlyRE = scenarioTagFilter(os.Stdout, doc, onlyRE) // --scenario-tag (§17 item 1, scenariotags.go)
	var track map[string]bool
	if mechList != nil {
		track = mechList.interfaces()
	}
	var rr *runReport
	if errs == 0 {
		rr = runAll(os.Stdout, doc, origins, runOpts{Track: track, Only: onlyRE, Quiet: *quiet, Trace: *trace, State: *state, Steps: *steps || *stepsFull, StepsFull: *stepsFull, Verbose: *verbose,
			Hollow: lints["hollow"], NoMocks: *noMocks, BehCov: *behCov})
	} else {
		rr = &runReport{}
		fmt.Printf("scenarios: 0 passed, 0 failed\n")
	}
	failed := rr.Failed
	failed += exploreGate(os.Stdout, runExplore(os.Stdout, doc, errs == 0)) // --explore, --replay (explore.go, DESIGN §15.5); --max-explore-failures (gates.go)
	if rr.Cov != nil && *behCovMD != "" {
		var b bytes.Buffer
		rr.Cov.markdown(&b, 0)
		if err := os.WriteFile(*behCovMD, b.Bytes(), 0o644); err != nil {
			fail(err)
		}
	}
	hollowFail, mockFail := rr.HollowFail, rr.MockFail

	strictFail := false
	var cites []citation
	if *code != "" {
		if fi, err := os.Stat(*code); err != nil || !fi.IsDir() {
			fail(fmt.Errorf("--code %s is not a directory", *code))
		}
		root := newCodeRoot(*code)
		rep := checkCitations(doc, root)
		cites = rep.cites
		rep.print(os.Stdout)
		if *sample > 0 {
			rep.sample(os.Stdout, root, *sample, *seed)
		}
		if *strictCite && rep.failures() > 0 {
			strictFail = true
		}
	}
	if *inventory != "" {
		inv, err := loadInventory(*inventory)
		if err != nil {
			fail(err)
		}
		if cites == nil {
			cites = collectCitations(doc)
		}
		t := tabulate(coverage(doc, cites, inv))
		sub := modeledBy(doc, cites, inv, withoutTrivial(rr.Called, trivialIDs(doc)))
		mr := t.setModeled(modeledBy(doc, cites, inv, rr.Called), sub, entryOwners(cites, origins, inv))
		mr.exemptFragments(doc, origins)
		t.print(os.Stdout, *verbose)
		if (*minModeled >= 0 || *minSub >= 0) && mr.print(os.Stdout, *minModeled, *minSub) {
			strictFail = true
		}
		if lints["trivial"] && lintTrivial(doc, cites, inv, origins).print(os.Stdout, *maxTrivial, *quiet) {
			strictFail = true
		}
		if *covMD != "" {
			var b bytes.Buffer
			t.markdown(&b, 20)
			if err := os.WriteFile(*covMD, b.Bytes(), 0o644); err != nil {
				fail(err)
			}
		}
		if *strictCov {
			if c, d := t.coveredOf(t.totals); c < d {
				strictFail = true
			}
		}
	}
	if runBlackbox(os.Stdout, doc, origins, lints, *quiet) { // internal-assertions, clock-ids (blackbox.go)
		strictFail = true
	}
	if anyIntegrityLint(lints) {
		over, err := runIntegrity(os.Stdout, doc, origins, *inventory, cites, lints,
			round4Gates(integrityGates{Inert: *maxInert, Unscheduled: *maxUnsched, Dataflow: *maxDataflow, Racy: *maxRacy, SeamNames: *maxSeam}, *code, *featuresFile, *failuresFile), *quiet)
		if err != nil {
			fail(err)
		}
		if over {
			strictFail = true
		}
	}
	if runUnwrittenFields(os.Stdout, doc, origins, lints, *quiet) { // unwritten-fields (unwritten.go)
		strictFail = true
	}
	if runInputLints(os.Stdout, doc, origins, lints, *code, *quiet) { // unknown-inputs, exemptions (inputlints.go)
		strictFail = true
	}
	present := map[string]bool{} // the -f files' base names: the areas in this merge
	for _, f := range in {
		present[strings.TrimSuffix(filepath.Base(f), filepath.Ext(f))] = true
	}
	if *testsFile != "" {
		tests, err := loadTests(*testsFile)
		if err != nil {
			fail(err)
		}
		if cites == nil {
			cites = collectCitations(doc)
		}
		if testReach(doc, cites, tests, rr.Called).print(os.Stdout, *minReach, *verbose, present) {
			strictFail = true
		}
	}
	if *featuresFile != "" {
		feats, skips, err := loadFeatures(*featuresFile)
		if err != nil {
			fail(err)
		}
		if featureCoverage(doc, feats, skips, rr.Flows, present).print(os.Stdout, *verbose) && *strictFeat {
			strictFail = true
		}
	}
	if *failuresFile != "" {
		fails, skips, err := loadFailures(*failuresFile)
		if err != nil {
			fail(err)
		}
		inj := failureRuns(doc, rr.Flows, onlyRE)
		if failureCoverage(doc, fails, skips, rr.Flows, inj, present).print(os.Stdout, *verbose) && *strictFailures {
			strictFail = true
		}
	}
	if runMechanisms(os.Stdout, doc, mechList, rr.Base, present, *code, errs == 0, *verbose) { // --mechanisms, --mechanism-e2e
		strictFail = true
	}
	if len(openapis) > 0 {
		over, err := runConformance(os.Stdout, doc, openapis, *code, *maxConf, *quiet)
		if err != nil {
			fail(err)
		}
		if over {
			strictFail = true
		}
	}
	if len(contractFiles) > 0 {
		over, err := runContracts(os.Stdout, doc, contractFiles, contractOpts{Code: *code, Max: *maxContract, Quiet: *quiet, Only: onlyRE, Run: errs == 0})
		if err != nil {
			fail(err)
		}
		if over {
			strictFail = true
		}
	}
	if len(refinements) > 0 && errs == 0 {
		over, err := runRefinements(os.Stdout, doc, refinements, refinementOpts{Only: onlyRE, Max: *maxRefine, ApplyTiming: *applyTiming, ApplyTo: *applyTo, DryRun: *dryRun, Quiet: *quiet, ParentLevel: inputsLevel(inputs), MaxEvents: *refMaxEvents, Trace: *refTrace})
		if err != nil {
			fail(err)
		}
		if over {
			strictFail = true
		}
	}

	if *out != "" {
		b, _ := json.MarshalIndent(doc, "", "  ")
		if err := os.WriteFile(*out, append(b, '\n'), 0o644); err != nil {
			fail(err)
		}
	}
	stageFinish(os.Stdout, !(bad || errs > 0 || failed > 0 || strictFail || hollowFail || mockFail), // --stage, --accept (stage.go)
		stageFailures{Conflicts: res.Conflicts, Issues: issues, Scenarios: rr.FailedIDs, Origins: origins, Doc: doc})
	if bad || errs > 0 || failed > 0 || strictFail || hollowFail || mockFail {
		os.Exit(1)
	}
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, "check:", err)
	os.Exit(2)
}

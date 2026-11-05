package main

// The mechanism list (DESIGN §13.1 items 38 and 39). Inventory coverage
// counts entry points: it reads 100% while whole mechanisms are absent, and a
// behavior passes its own scenario while its result reaches nobody. An
// enumerator agent lists each area's mechanisms from the code
// (templates/MECHANISMS.md), and this measures each one:
//
//	--mechanisms DIR [--min-mechanisms R] [--mechanisms-json FILE]
//	--mechanism-e2e [--mechanism-e2e-scenarios N] [--mechanism-e2e-workers N]
//	    [--mechanism-e2e-variant zero|empty|fail] [--max-shell-mechanisms N]
//
// DIR holds <area>.json ({area, mechanisms: [...]}) and skips/<area>.json
// ([{id, reason, covered_by}], under the feature skip rules). A mechanism is
// missing (no interface exists), uncovered (no scenario's trace reaches one),
// shell (reached, but the mutation of mechanisme2e.go finds no boundary
// expectation that notices its removal), weak (something notices, but only an
// abort, or not for each of its interfaces), ok, or skipped.

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

var (
	mechanismsDir  = flag.String("mechanisms", "", "`DIR` of <area>.json mechanism lists (and skips/<area>.json) to report as ok, weak, shell, uncovered, missing or skipped (DESIGN §13.1 item 38)")
	minMechanisms  = flag.Float64("min-mechanisms", -1, "with --mechanisms, run --mechanism-e2e and exit 1 when ok / unskipped mechanisms is below this ratio (a weak mechanism isn't ok); it only ratchets up (unset: recorded, not gated)")
	mechanismsJSON = flag.String("mechanisms-json", "", "with --mechanisms, run --mechanism-e2e and write each mechanism with its measured gate_status to `FILE`, as a JSON array of web's EvidenceMechanism")
)

func init() {
	// No template default: a profile that doesn't set them records without
	// gating. Both apply only when --mechanisms is given.
	profileGateDefs = append(profileGateDefs,
		struct{ key, flag, def, needs string }{"min_mechanisms", "min-mechanisms", "", "mechanisms"},
		struct{ key, flag, def, needs string }{"max_shell_mechanisms", "max-shell-mechanisms", "", "mechanisms"})
}

// mechanism is one entry of a list (the format is templates/MECHANISMS.md).
type mechanism struct {
	ID         string   `json:"id"`
	Kind       string   `json:"kind"`
	Name       string   `json:"name"`
	Trigger    string   `json:"trigger"`
	Observable string   `json:"observable"`
	Citations  []string `json:"citations"`
	Interfaces []string `json:"interfaces"`
	Fidelity   string   `json:"fidelity"`
	Note       string   `json:"note"`
	Area       string   `json:"-"` // the list's file name
}

// mechanismList is a loaded DIR.
type mechanismList struct {
	Mechanisms []mechanism
	Skips      map[string][]featureSkip // by area: skips/<area>.json
	Warnings   []string
}

var (
	mechanismKinds = map[string]bool{"loop": true, "sweep": true, "lifecycle": true, "pipeline": true, "handshake": true, "cache": true,
		"money": true, "retry": true, "gate": true, "dispatch": true, "metric": true}
	mechanismFidelities = map[string]bool{"absent": true, "shell": true, "partial": true, "modeled": true}
)

// loadMechanisms reads DIR/*.json and DIR/skips/*.json, in name order.
func loadMechanisms(dir string) (*mechanismList, error) {
	if fi, err := os.Stat(dir); err != nil || !fi.IsDir() {
		return nil, fmt.Errorf("--mechanisms %s is not a directory", dir)
	}
	l := &mechanismList{Skips: map[string][]featureSkip{}}
	files, _ := filepath.Glob(filepath.Join(dir, "*.json"))
	sort.Strings(files)
	seen := map[string]string{}
	for _, f := range files {
		b, err := os.ReadFile(f)
		if err != nil {
			return nil, err
		}
		var doc struct {
			Area       string      `json:"area"`
			Mechanisms []mechanism `json:"mechanisms"`
		}
		if err := json.Unmarshal(b, &doc); err != nil {
			return nil, fmt.Errorf("%s: %w", f, err)
		}
		area := strings.TrimSuffix(filepath.Base(f), ".json")
		if doc.Area != "" && doc.Area != area {
			l.Warnings = append(l.Warnings, fmt.Sprintf("%s: says area %q; the file name wins", filepath.Base(f), doc.Area))
		}
		for _, m := range doc.Mechanisms {
			m.Area = area
			if prev, dup := seen[m.ID]; dup {
				l.Warnings = append(l.Warnings, fmt.Sprintf("%s: duplicate id %s, first in %s; the first is kept", filepath.Base(f), m.ID, prev))
				continue
			}
			seen[m.ID] = filepath.Base(f)
			if !mechanismKinds[m.Kind] {
				l.Warnings = append(l.Warnings, fmt.Sprintf("%s: unknown kind %q", m.ID, m.Kind))
			}
			if !mechanismFidelities[m.Fidelity] {
				l.Warnings = append(l.Warnings, fmt.Sprintf("%s: unknown fidelity %q", m.ID, m.Fidelity))
			}
			l.Mechanisms = append(l.Mechanisms, m)
		}
	}
	skipFiles, _ := filepath.Glob(filepath.Join(dir, "skips", "*.json"))
	sort.Strings(skipFiles)
	for _, f := range skipFiles {
		b, err := os.ReadFile(f)
		if err != nil {
			return nil, err
		}
		var s []featureSkip
		if err := json.Unmarshal(b, &s); err != nil {
			return nil, fmt.Errorf("%s: %w", f, err)
		}
		l.Skips[strings.TrimSuffix(filepath.Base(f), ".json")] = s
	}
	return l, nil
}

// interfaces is the set of interfaces any mechanism lists: what the scenario
// runs record reach for.
func (l *mechanismList) interfaces() map[string]bool {
	out := map[string]bool{}
	for _, m := range l.Mechanisms {
		for _, id := range m.Interfaces {
			out[id] = true
		}
	}
	return out
}

// Mechanism statuses.
const (
	mechOK        = "ok"
	mechWeak      = "weak" // noticed, but only by an abort, or not for each interface
	mechShell     = "shell"
	mechUncovered = "uncovered"
	mechMissing   = "missing"
	mechSkipped   = "skipped"
	mechReached   = "reached" // reached, but Gate 2 didn't run: not known to be ok
	mechAbsent    = "absent"  // would be missing or uncovered, but its area isn't in this merge
)

// mechResult is one mechanism's measured status.
type mechResult struct {
	mechanism
	Status    string
	Raw       string   // Status, before an absent area hides missing or uncovered
	Detail    string   // the skip reason, or why it isn't ok
	Unknown   []string // listed ids that name no interface
	Unreached []string // listed interfaces, known, that no trace reaches
	Disagree  string   // the enumerator's fidelity against the status
	E2E       *mechE2E // Gate 2's evidence, when it ran
}

// mechReport is the measure of a whole list.
type mechReport struct {
	Results  []*mechResult
	Warnings []string
	Shared   []string // interfaces several areas list
	Elapsed  string   // Gate 2's wall time; "" when it didn't run
	Runs     int      // Gate 2's mutated runs
	Workers  int
	Variant  string
}

// measureMechanisms gives each mechanism its Gate 1 status from the baseline
// runs: skipped, missing, uncovered or reached. present holds the -f files'
// base names (nil: every area), as for features.
func measureMechanisms(doc *model.Document, l *mechanismList, base map[string]*baseRun, present map[string]bool) *mechReport {
	x := indexed(doc)
	r := &mechReport{Warnings: append([]string(nil), l.Warnings...)}
	problems, shared := l.listProblems()
	r.Warnings, r.Shared = append(r.Warnings, problems...), shared
	known := map[string]string{} // mechanism id -> area
	for _, m := range l.Mechanisms {
		known[m.ID] = m.Area
	}
	skipOf, skipProb := map[string]featureSkip{}, map[string]string{}
	for _, area := range sortedKeysOf(l.Skips) {
		for _, s := range l.Skips[area] {
			owner, ok := known[s.ID]
			switch {
			case !ok:
				r.Warnings = append(r.Warnings, fmt.Sprintf("skips/%s.json: %s is not a mechanism", area, s.ID))
			case owner != area:
				r.Warnings = append(r.Warnings, fmt.Sprintf("skips/%s.json: %s belongs to %s", area, s.ID, owner))
			default:
				if p := skipProblem(s, doc); p != "" {
					skipProb[s.ID] = p
				} else {
					skipOf[s.ID] = s
				}
			}
		}
	}
	reached := map[string]bool{}
	for _, b := range base {
		for id := range b.Reach {
			reached[id] = true
		}
	}
	for _, m := range l.Mechanisms {
		res := &mechResult{mechanism: m}
		r.Results = append(r.Results, res)
		if s, ok := skipOf[m.ID]; ok {
			res.Status, res.Detail = mechSkipped, s.Reason
			if s.CoveredBy != "" {
				res.Detail += " (covered by " + s.CoveredBy + ")"
			}
			continue
		}
		exists, hit := 0, 0
		for _, id := range m.Interfaces {
			switch {
			case x.Interfaces[id] == nil:
				res.Unknown = append(res.Unknown, id)
			case reached[id]:
				exists++
				hit++
			default:
				exists++
				res.Unreached = append(res.Unreached, id)
			}
		}
		switch {
		case len(m.Interfaces) == 0:
			res.Status, res.Detail = mechMissing, "lists no interface"
		case exists == 0:
			res.Status, res.Detail = mechMissing, "no listed interface exists"
		case hit == 0:
			res.Status, res.Detail = mechUncovered, "no scenario's trace reaches "+strings.Join(res.Unreached, ", ")
		default:
			res.Status = mechReached
		}
		if p := skipProb[m.ID]; p != "" {
			res.Detail = strings.TrimPrefix(res.Detail+"; invalid skip: "+p, "; ")
		}
		if (res.Status == mechMissing || res.Status == mechUncovered) && present != nil && !present[m.Area] {
			res.Raw, res.Status = res.Status, mechAbsent
		}
	}
	return r
}

func sortedKeysOf[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// fidelityAgrees reports whether an enumerator's reading matches a measured
// status. Modeled says it all runs as the code runs: ok, and a weak one has a
// part nothing notices. Partial says the main path runs: ok or weak. A shell
// can show as a mutation survivor or as nothing reaching it. Absent is missing.
// Skipped, and reached (Gate 2 didn't run), measure nothing to disagree with,
// except that an absent mechanism shouldn't be reached at all.
func fidelityAgrees(fidelity, status string) bool {
	switch status {
	case mechSkipped, mechAbsent:
		return true
	case mechReached:
		return fidelity != "absent"
	}
	switch fidelity {
	case "modeled":
		return status == mechOK
	case "partial":
		return status == mechOK || status == mechWeak
	case "shell":
		return status == mechShell || status == mechUncovered
	case "absent":
		return status == mechMissing
	}
	return true // no fidelity, or an unknown one (warned about at load)
}

// finish records the disagreements, once the statuses are final.
func (r *mechReport) finish() {
	for _, res := range r.Results {
		if !fidelityAgrees(res.Fidelity, res.Status) {
			res.Disagree = fmt.Sprintf("enumerator says %s, measured %s", res.Fidelity, res.Status)
		}
	}
}

// mechCounts is one line of the report.
type mechCounts struct {
	OK, Weak, Shell, Uncovered, Missing, Skipped, Reached, Absent, Disagree int
}

func (c *mechCounts) add(res *mechResult) {
	switch res.Status {
	case mechOK:
		c.OK++
	case mechWeak:
		c.Weak++
	case mechShell:
		c.Shell++
	case mechUncovered:
		c.Uncovered++
	case mechMissing:
		c.Missing++
	case mechSkipped:
		c.Skipped++
	case mechReached:
		c.Reached++
	case mechAbsent:
		c.Absent++
	}
	if res.Disagree != "" {
		c.Disagree++
	}
}

// unskipped is the gate's denominator.
func (c mechCounts) unskipped() int {
	return c.OK + c.Weak + c.Shell + c.Uncovered + c.Missing + c.Reached
}

func (c mechCounts) String() string {
	s := fmt.Sprintf("%d ok, %d weak, %d shell, %d uncovered, %d missing, %d skipped", c.OK, c.Weak, c.Shell, c.Uncovered, c.Missing, c.Skipped)
	if c.Reached > 0 {
		s += fmt.Sprintf(", %d reached (Gate 2 not run)", c.Reached)
	}
	if c.Absent > 0 {
		s += fmt.Sprintf(", %d in areas not in this merge", c.Absent)
	}
	if c.Disagree > 0 {
		s += fmt.Sprintf("; %d disagree with the enumerator", c.Disagree)
	}
	return s
}

// totals counts every result; the first map is per area, the second per kind.
func (r *mechReport) totals() (map[string]*mechCounts, map[string]*mechCounts, mechCounts) {
	areas, kinds := map[string]*mechCounts{}, map[string]*mechCounts{}
	var total mechCounts
	for _, res := range r.Results {
		for _, g := range []struct {
			m map[string]*mechCounts
			k string
		}{{areas, res.Area}, {kinds, first(res.Kind, "(no kind)")}} {
			if g.m[g.k] == nil {
				g.m[g.k] = &mechCounts{}
			}
			g.m[g.k].add(res)
		}
		total.add(res)
	}
	return areas, kinds, total
}

// print writes the counts, the non-ok mechanisms and the disagreements; verbose
// also lists the ok ones and every survivor.
func (r *mechReport) print(w io.Writer, verbose bool) {
	for _, s := range r.Warnings {
		fmt.Fprintf(w, "! mechanisms: %s\n", s)
	}
	if verbose {
		for _, s := range r.Shared {
			fmt.Fprintf(w, "! mechanisms: %s\n", s)
		}
	}
	for _, res := range r.Results {
		switch res.Status {
		case mechAbsent:
			continue
		case mechOK, mechSkipped, mechReached:
			if verbose {
				res.printLine(w, " ", verbose)
			}
		default:
			res.printLine(w, "✗", verbose)
		}
		if len(res.Unknown) > 0 && (res.Status == mechOK || res.Status == mechReached) {
			fmt.Fprintf(w, "! mechanism %s: unknown interface %s\n", res.ID, strings.Join(res.Unknown, ", "))
		}
	}
	for _, res := range r.Results {
		if res.Disagree != "" {
			fmt.Fprintf(w, "! mechanism %s: %s\n", res.ID, res.Disagree)
		}
	}
	areas, kinds, total := r.totals()
	for _, a := range sortedKeysOf(areas) {
		fmt.Fprintf(w, "  mechanisms of %s: %s\n", a, areas[a])
	}
	for _, k := range sortedKeysOf(kinds) {
		fmt.Fprintf(w, "  mechanisms of kind %s: %s\n", k, kinds[k])
	}
	if r.Elapsed != "" {
		weak, aborts := 0, 0
		for _, res := range r.Results {
			if res.E2E != nil {
				weak += len(res.E2E.Weak)
				if res.E2E.AbortOnly {
					aborts++
				}
			}
		}
		fmt.Fprintf(w, "mechanism e2e: %d mutated runs, variant %s, %d workers, %s; %d noticed only by an abort; %d weak interfaces\n", r.Runs, r.Variant, r.Workers, r.Elapsed, aborts, weak)
	}
	unknown := 0
	for _, res := range r.Results {
		unknown += len(res.Unknown)
	}
	fmt.Fprintf(w, "mechanism list: %d unknown interface ids, %d problems named above, %d interfaces listed by several areas\n", unknown, len(r.Warnings), len(r.Shared))
	fmt.Fprintf(w, "mechanisms: %d of %d unskipped ok (%.1f%%): %s\n", total.OK, total.unskipped(), 100*mechShare(total), total)
}

func (res *mechResult) printLine(w io.Writer, mark string, verbose bool) {
	fmt.Fprintf(w, "%s mechanism %s (%s, %s) %s [enumerator: %s]", mark, res.ID, res.Area, first(res.Kind, "no kind"), res.Status, first(res.Fidelity, "none"))
	if res.Detail != "" {
		fmt.Fprintf(w, ": %s", res.Detail)
	}
	fmt.Fprintln(w)
	if len(res.Unknown) > 0 {
		fmt.Fprintf(w, "    unknown interface: %s\n", strings.Join(res.Unknown, ", "))
	}
	if res.E2E != nil {
		for _, weak := range res.E2E.Weak {
			fmt.Fprintf(w, "    interface %s: %s\n", weak.ID, weak.Why)
			if verbose {
				printE2ERuns(w, weak.Runs, verbose)
			}
		}
		if res.Status == mechShell || verbose {
			res.E2E.print(w, res.Interfaces, res.Unreached, verbose)
		}
	}
}

// mechShare is ok / unskipped; nothing unskipped reads as 1.
func mechShare(c mechCounts) float64 {
	if c.unskipped() == 0 {
		return 1
	}
	return float64(c.OK) / float64(c.unskipped())
}

// gates prints the two gates' lines and reports whether one failed. Unset, a
// gate records the measure without failing.
func (r *mechReport) gates(w io.Writer, minShare float64, maxShell int) bool {
	_, _, total := r.totals()
	failed := false
	share := mechShare(total)
	if minShare < 0 {
		fmt.Fprintf(w, "~ mechanisms gate: share %.3f recorded, not gated (no --min-mechanisms; gates.min_mechanisms is unset)\n", share)
	} else {
		mark := "✓"
		if share < minShare {
			mark, failed = "✗", true
		}
		fmt.Fprintf(w, "%s mechanisms gate: share %.3f, --min-mechanisms %s\n", mark, share, trimFloat(minShare))
		ratchetUpHint(w, "min-mechanisms", share, minShare)
	}
	if r.Elapsed != "" {
		if maxShell < 0 {
			fmt.Fprintf(w, "~ shell-mechanisms gate: %d recorded, not gated (no --max-shell-mechanisms; gates.max_shell_mechanisms is unset)\n", total.Shell)
		} else if countGate(w, &integrityReport{Lint: "shell-mechanisms", Fragments: []fragShare{{Hits: total.Shell}}}, "max-shell-mechanisms", maxShell) {
			failed = true
		}
	}
	return failed
}

// ratchetUpHint is ratchetHint for a min gate, which only goes up. The value
// is rounded down to 3 places, so the hinted value still passes.
func ratchetUpHint(w io.Writer, flagName string, measured, min float64) {
	v := math.Floor(measured*1000+1e-9) / 1000
	if v > min {
		fmt.Fprintf(w, "~ ratchet: --%s can go up to %s (this gate only goes up, the opposite of the max_* gates)\n", flagName, trimFloat(v))
	}
}

// mechanismsPrepare checks the flags and loads the list before the scenarios
// run, so that a run can record reach for it. It returns nil without
// --mechanisms.
func mechanismsPrepare() *mechanismList {
	if *minMechanisms >= 0 || *maxShellMechanisms >= 0 || *mechanismsJSON != "" {
		*mechanismE2E = true
	}
	if *mechanismsDir == "" {
		set := map[string]bool{}
		flag.Visit(func(f *flag.Flag) { set[f.Name] = true })
		for _, n := range []string{"min-mechanisms", "mechanisms-json", "mechanism-e2e", "mechanism-e2e-scenarios", "mechanism-e2e-workers", "mechanism-e2e-variant", "max-shell-mechanisms"} {
			if set[n] {
				fail(fmt.Errorf("--%s needs --mechanisms", n))
			}
		}
		return nil
	}
	if *minMechanisms > 1 {
		fail(fmt.Errorf("--min-mechanisms must be at most 1"))
	}
	if *mechanismE2EScenarios < 0 {
		fail(fmt.Errorf("--mechanism-e2e-scenarios must be 0 (every scenario) or more"))
	}
	if *mechanismE2EWorkers < 1 {
		fail(fmt.Errorf("--mechanism-e2e-workers must be at least 1"))
	}
	if _, ok := e2eVariants[*mechanismE2EVariant]; !ok {
		fail(fmt.Errorf("--mechanism-e2e-variant must be zero, empty or fail"))
	}
	l, err := loadMechanisms(*mechanismsDir)
	if err != nil {
		fail(err)
	}
	return l
}

// runMechanisms runs both gates over the list and reports whether one failed.
func runMechanisms(w io.Writer, doc *model.Document, l *mechanismList, base map[string]*baseRun, present map[string]bool, code string, run, verbose bool) bool {
	if l == nil {
		return false
	}
	if !run {
		fmt.Fprintln(w, "mechanisms: skipped (validation errors)")
		return false
	}
	r := measureMechanisms(doc, l, base, present)
	if *mechanismE2E {
		runMechanismE2E(r, doc, base, e2eOpts{Scenarios: *mechanismE2EScenarios, Workers: *mechanismE2EWorkers, Variant: *mechanismE2EVariant})
	}
	r.finish()
	r.print(w, verbose)
	if code != "" {
		printMechanismCitations(w, l, newCodeRoot(code))
	}
	if *mechanismsJSON != "" {
		if err := writeMechanismsJSON(*mechanismsJSON, r); err != nil {
			fail(err)
		}
	}
	return r.gates(w, *minMechanisms, *maxShellMechanisms)
}

// evidenceMechanism is one mechanism of --mechanisms-json, in the shape of
// EvidenceMechanism in web/src/lib/api/types.ts.
type evidenceMechanism struct {
	ID         string   `json:"id"`
	Area       string   `json:"area"`
	Kind       string   `json:"kind"`
	Name       string   `json:"name"`
	Trigger    string   `json:"trigger,omitempty"`
	Observable string   `json:"observable,omitempty"`
	Citations  []string `json:"citations"`
	Interfaces []string `json:"interfaces"`
	Fidelity   string   `json:"fidelity"`
	Note       string   `json:"note,omitempty"`
	GateStatus string   `json:"gate_status"`
}

// gateStatus is the status --mechanisms-json writes. An absent mechanism is
// still missing or uncovered: its area not being in this merge doesn't change
// what was measured.
func (res *mechResult) gateStatus() string {
	if res.Status == mechAbsent {
		return res.Raw
	}
	return res.Status
}

// writeMechanismsJSON writes the measured list for an evidence loader.
func writeMechanismsJSON(path string, r *mechReport) error {
	out := make([]evidenceMechanism, 0, len(r.Results))
	for _, res := range r.Results {
		out = append(out, evidenceMechanism{
			ID: res.ID, Area: res.Area, Kind: res.Kind, Name: res.Name, Trigger: res.Trigger, Observable: res.Observable,
			Citations: append([]string{}, res.Citations...), Interfaces: append([]string{}, res.Interfaces...),
			Fidelity: res.Fidelity, Note: res.Note, GateStatus: res.gateStatus(),
		})
	}
	b, err := json.MarshalIndent(out, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(path, append(b, '\n'), 0o644); err != nil {
		return fmt.Errorf("--mechanisms-json: %w", err)
	}
	return nil
}

// listProblems checks the list's own data. It returns the problems to name
// (a mechanism id outside its file's area), and the interfaces several areas
// list, which an area can do for a reason, so only -v names them. Unknown
// interfaces are on each mechanism's line, and duplicate ids warned at load.
func (l *mechanismList) listProblems() (problems, shared []string) {
	byInterface := map[string]map[string]bool{}
	for _, m := range l.Mechanisms {
		for _, id := range m.Interfaces {
			if byInterface[id] == nil {
				byInterface[id] = map[string]bool{}
			}
			byInterface[id][m.Area] = true
		}
		if !strings.HasPrefix(m.ID, m.Area+".") {
			problems = append(problems, fmt.Sprintf("%s is in %s.json", m.ID, m.Area))
		}
	}
	for _, id := range sortedKeysOf(byInterface) {
		if len(byInterface[id]) > 1 {
			shared = append(shared, fmt.Sprintf("interface %s is listed by areas %s", id, strings.Join(sortedKeysOf(byInterface[id]), ", ")))
		}
	}
	return problems, shared
}

// printMechanismCitations resolves the list's citations against the code, as
// --code does the model's, and names those that don't resolve. A secret path
// is never opened: it reads as skipped.
func printMechanismCitations(w io.Writer, l *mechanismList, code *codeRoot) {
	total, bad, secret := 0, 0, 0
	for _, m := range l.Mechanisms {
		for _, c := range m.Citations {
			total++
			switch st, _ := code.resolve(model.ParseSource(c)); st {
			case citeOK:
			case citeSkipped:
				secret++
			default:
				bad++
				fmt.Fprintf(w, "! mechanism %s: citation %s: %s\n", m.ID, c, st)
			}
		}
	}
	fmt.Fprintf(w, "mechanism citations: %d cited, %d don't resolve, %d in secret files, not opened\n", total, bad, secret)
}

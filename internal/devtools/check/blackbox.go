package main

// The DESIGN §15.1 lints: internal-assertions (expectations that reach
// past the system's boundary into its internals) and clock-ids (ids minted
// from now instead of id() and seq()).

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// blackboxLints are the --lint names this file implements.
var blackboxLints = map[string]bool{"internal-assertions": true, "clock-ids": true}

var maxInternal = flag.Float64("max-internal-assertions", -1, "run --lint internal-assertions and exit 1 when a fragment's share of expectations that name a non-boundary interface or the state of a component that isn't a store is above this ratio")

// blackboxImplied turns on the lints their gates imply.
func blackboxImplied(lints map[string]bool) {
	if *maxInternal >= 0 {
		lints["internal-assertions"] = true
	}
	gatesImplied(lints) // --max-clock-ids, --max-unknown-inputs (gates.go)
}

// runBlackbox runs the requested §15.1 lints and reports whether a gate
// failed.
func runBlackbox(w io.Writer, doc *model.Document, origins map[string]string, lints map[string]bool, quiet bool) bool {
	failed := false
	if lints["internal-assertions"] {
		r := lintInternalAssertions(doc, origins)
		if r.print(w, *maxInternal, quiet) {
			failed = true
		}
		shareRatchet(w, r, "max-internal-assertions", *maxInternal)
	}
	if lints["clock-ids"] {
		r := lintClockIDs(doc, origins)
		r.print(w, -1, quiet)
		if countGate(w, r, "max-clock-ids", *maxClockIDs) {
			failed = true
		}
	}
	return failed
}

var (
	celStrLit = regexp.MustCompile(`'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"`)
	stateRef  = regexp.MustCompile(`(?:^|[^\w.])state\s*(?:\.\s*([A-Za-z_]\w*)|\[\s*(?:'([^']*)'|"([^"]*)")\s*\])`)
)

// lintInternalAssertions counts, per fragment, the scenario expectations
// that name a non-boundary interface (one whose component isn't external
// or attributes.boundary, and that no flow or scenario step enters by) or
// a state path inside a component that isn't a store. Expectations on io,
// result and steps survive internal renames; these don't.
func lintInternalAssertions(doc *model.Document, origins map[string]string) *integrityReport {
	x := indexed(doc)
	boundary := map[string]bool{}
	for id, f := range x.Interfaces {
		if sim.IsBoundaryComponent(x.Components[f.Component]) {
			boundary[id] = true
		}
	}
	for _, fl := range doc.Flows {
		if fl.Entry != nil {
			boundary[fl.Entry.Interface] = true
		}
	}
	for _, sc := range doc.Scenarios {
		for _, st := range sc.Steps {
			if st.Interface != "" {
				boundary[st.Interface] = true
			}
		}
	}
	stores := map[string]bool{}
	for _, f := range x.Interfaces {
		if f.Store != nil {
			stores[f.Component] = true
		}
	}
	r := &integrityReport{Lint: "internal-assertions", Unit: "expectations"}
	s := shareCounter{}
	for _, sc := range doc.Scenarios {
		frag := originOf(origins, model.KindScenario, sc.ID)
		for i, e := range sc.Expect {
			why := internalNames(e, x, boundary, stores)
			s.add(frag, why != "")
			if why != "" {
				r.Findings = append(r.Findings, integrityFinding{Fragment: frag, Subject: fmt.Sprintf("%s.expect[%d]", sc.ID, i), Why: why})
			}
		}
	}
	r.finish(s)
	return r
}

// internalNames says what internals an expectation names, or "".
func internalNames(e string, x *model.Index, boundary, stores map[string]bool) string {
	var names []string
	seen := map[string]bool{}
	note := func(n string) {
		if !seen[n] {
			seen[n] = true
			names = append(names, n)
		}
	}
	for _, m := range celStrLit.FindAllStringSubmatch(e, -1) {
		lit := m[1] + m[2]
		if _, ok := x.Interfaces[lit]; ok && !boundary[lit] {
			note("interface " + lit)
		}
	}
	for _, m := range stateRef.FindAllStringSubmatch(e, -1) {
		comp := m[1] + m[2] + m[3]
		if at := strings.IndexByte(comp, '@'); at >= 0 {
			comp = comp[:at]
		}
		c, ok := x.Components[comp]
		if !ok || stores[comp] || sim.IsBoundaryComponent(c) {
			continue
		}
		note("state of " + comp)
	}
	sort.Strings(names)
	return strings.Join(names, ", ")
}

var (
	nowRef    = regexp.MustCompile(`(?:^|[^\w.])now(_us)?\b`) // the clock, not vars.now
	nowString = regexp.MustCompile(`\bstring\(\s*now(_us)?\s*\)`)
	// duration(string(now) + 'ms') turns now into a timestamp, not an id.
	nowDuration = regexp.MustCompile(`\bduration\(\s*string\(\s*now(_us)?\s*\)`)
	idShapedKy  = regexp.MustCompile(`(?i)^(id|uuid|guid|nonce|token|key|sk|pk)$|(?i)[_-](id|uuid|guid|key|token|nonce)$|[a-z0-9](Id|ID|Uuid|UUID|Key|Token|Nonce)$`)
)

// clockID reports whether a template mints an id from the clock: it reads
// now (or now_us) and either turns it straight into a string (string(now),
// as in 'req-' + string(now)) or sets an id-shaped field (id, *_id, token,
// nonce, key and the like). Timestamps such as
// string(timestamp(int(now / 1000))) on non-id fields aren't flagged.
func clockID(field, tpl string) bool {
	if !nowRef.MatchString(tpl) {
		return false
	}
	if nowString.MatchString(nowDuration.ReplaceAllString(tpl, "")) {
		return true
	}
	if i := strings.LastIndexByte(field, '.'); i >= 0 {
		field = field[i+1:]
	}
	return idShapedKy.MatchString(field)
}

// lintClockIDs lists the templates that mint ids from now, in behaviors
// and in scenario, step and flow entry inputs. Of counts the templates
// that read now. It's advisory: move them to id(prefix, key...) and
// seq(name), which come from the run seed.
func lintClockIDs(doc *model.Document, origins map[string]string) *integrityReport {
	r := &integrityReport{Lint: "clock-ids", Unit: "templates reading now"}
	s := shareCounter{}
	visit := func(frag, subject string, v any) {
		walkTemplates(v, "", func(path, field, tpl string) {
			if !nowRef.MatchString(tpl) {
				return
			}
			hit := clockID(field, tpl)
			s.add(frag, hit)
			if hit {
				r.Findings = append(r.Findings, integrityFinding{Fragment: frag, Subject: subject + path, Why: strings.TrimSpace(tpl)})
			}
		})
	}
	for i := range doc.Interfaces {
		f := &doc.Interfaces[i]
		if len(f.Behavior) == 0 {
			continue
		}
		visit(originOf(origins, model.KindInterface, f.ID), f.ID+":behavior", asJSON(f.Behavior))
	}
	for _, fl := range doc.Flows {
		if fl.Entry != nil && len(fl.Entry.Input) > 0 {
			visit(originOf(origins, model.KindFlow, fl.ID), fl.ID+":entry.input", rawJSON(fl.Entry.Input))
		}
	}
	for _, sc := range doc.Scenarios {
		frag := originOf(origins, model.KindScenario, sc.ID)
		if len(sc.Input) > 0 {
			visit(frag, sc.ID+":input", rawJSON(sc.Input))
		}
		for i, st := range sc.Steps {
			if len(st.Input) > 0 {
				visit(frag, fmt.Sprintf("%s:steps[%d].input", sc.ID, i), rawJSON(st.Input))
			}
		}
	}
	r.finish(s)
	return r
}

func rawJSON(b []byte) any {
	var out any
	if json.Unmarshal(b, &out) != nil {
		return nil
	}
	return out
}

// walkTemplates calls fn for each "=cel" string in v, with its path and the
// map key it sits under (or "" in a list).
func walkTemplates(v any, path string, fn func(path, field, tpl string)) {
	var walk func(v any, path, field string)
	walk = func(v any, path, field string) {
		switch t := v.(type) {
		case map[string]any:
			keys := make([]string, 0, len(t))
			for k := range t {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				walk(t[k], path+"."+k, k)
			}
		case []any:
			for i, e := range t {
				walk(e, fmt.Sprintf("%s[%d]", path, i), field)
			}
		case string:
			if strings.HasPrefix(strings.TrimSpace(t), "=") {
				fn(path, field, strings.TrimPrefix(strings.TrimSpace(t), "="))
			}
		}
	}
	walk(v, path, "")
}

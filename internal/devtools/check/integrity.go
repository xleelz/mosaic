package main

// Model-integrity lints (DESIGN §13.1 item 20): declared logic that never
// runs, scheduled work that nothing schedules, and state that is read but
// never written. Each catches a class of defect that passing scenarios hid
// in a generated gateway-platform model: a liveness check that was a stub
// (inert), a cleanup sweep that only scenario steps called (unscheduled),
// and a gate reading a field nothing wrote (dataflow).

import (
	"encoding/json"
	"fmt"
	"io"
	"path"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// integrityLints are the --lint names this file implements.
var integrityLints = map[string]bool{"inert": true, "unscheduled": true, "dataflow": true, "racy": true, "seam-names": true,
	"unraised-errors": true, "choice-for-computed": true}

// scheduledKinds are the inventory kinds whose code runs because something
// schedules or starts it, not because a caller asks: timers, listeners,
// consumers and service mains, under each repo's inventory name.
var scheduledKinds = map[string]bool{
	"cron": true, "listener": true, "queue-consumer": true, "service-main": true,
	"scheduled-task": true, "background-task": true, "busy-loop": true, "process-main": true,
}

// drivenKinds are scheduled kinds that any flow also drives: a listener or
// consumer runs when a request or message arrives (a flow entry or an event
// delivery), and a process main runs when a flow starts the process.
var drivenKinds = map[string]bool{"listener": true, "queue-consumer": true, "service-main": true, "process-main": true}

// startupFlow matches the flows that model a process starting.
var startupFlow = regexp.MustCompile(`(^|[^a-z])(startup|boot|bootstrap|launch|start|init|main)([^a-z]|$)`)

// integrityGates are the --max-<lint> ratios; a negative one prints without gating.
// SeamNames is a count (--max-seam-names N), negative when off.
type integrityGates struct {
	Inert, Unscheduled, Dataflow, Racy float64
	SeamNames                          int
	// Round 4 (item 33): --max-unraised R, --max-choice-for-computed N,
	// the --code root and the profile the lints read.
	Unraised       float64
	ChoiceComputed int
	Code, Profile  string
}

// fragShare is one fragment's count of findings out of the candidates.
type fragShare struct {
	Fragment string
	Of, Hits int
}

func (f fragShare) Share() float64 {
	if f.Of == 0 {
		return 0
	}
	return float64(f.Hits) / float64(f.Of)
}

// integrityFinding is one line a lint lists.
type integrityFinding struct {
	Lint, Fragment, Subject, Why string
}

// integrityReport is one lint's findings and shares.
type integrityReport struct {
	Lint      string
	Unit      string // what Of counts, for the share line
	Findings  []integrityFinding
	Fragments []fragShare
	Unknown   int // dataflow: reads or writes the lint couldn't resolve
	// racy: findings exempted by attributes.racy_in_code (races the code
	// itself has, findings about the system), and malformed exemptions.
	System   []integrityFinding
	Warnings []string
	// unraised-errors: unraised entries of shared error catalogs, not listed.
	Catalog int
}

type shareCounter map[string]*fragShare

func (s shareCounter) add(frag string, hit bool) {
	f := s[frag]
	if f == nil {
		f = &fragShare{Fragment: frag}
		s[frag] = f
	}
	f.Of++
	if hit {
		f.Hits++
	}
}

func (r *integrityReport) finish(s shareCounter) {
	for _, f := range s {
		r.Fragments = append(r.Fragments, *f)
	}
	sort.Slice(r.Fragments, func(a, b int) bool { return r.Fragments[a].Fragment < r.Fragments[b].Fragment })
	sort.Slice(r.Findings, func(a, b int) bool {
		if r.Findings[a].Fragment != r.Findings[b].Fragment {
			return r.Findings[a].Fragment < r.Findings[b].Fragment
		}
		return r.Findings[a].Subject < r.Findings[b].Subject
	})
}

// print lists the findings (unless quiet) and the share per fragment, marks
// with ✗ the fragments above max (when max >= 0) and reports whether any is.
func (r *integrityReport) print(w io.Writer, max float64, quiet bool) bool {
	if !quiet {
		for _, f := range r.Findings {
			fmt.Fprintf(w, "! %s %s (%s): %s\n", first(f.Lint, r.Lint), f.Subject, f.Fragment, f.Why)
		}
	}
	above, hits, of := 0, 0, 0
	for _, f := range r.Fragments {
		mark := " "
		if max >= 0 && f.Share() > max {
			mark = "✗"
			above++
		}
		hits += f.Hits
		of += f.Of
		fmt.Fprintf(w, "%s %s in %s: %d of %d %s %s\n", mark, r.Lint, f.Fragment, f.Hits, f.Of, r.Unit, pct1(f.Hits, f.Of))
	}
	for _, f := range r.System {
		fmt.Fprintf(w, "! racy in code (system finding) %s (%s): %s\n", f.Subject, f.Fragment, f.Why)
	}
	for _, s := range r.Warnings {
		fmt.Fprintf(w, "! %s\n", s)
	}
	extra := ""
	if r.Lint == "racy" {
		extra = fmt.Sprintf("; %d racy in code (system findings)", len(r.System))
	}
	if r.Lint == "racy" {
		n := 0
		for _, f := range r.Findings {
			if f.Lint == "racy (transition)" {
				n++
			}
		}
		extra += fmt.Sprintf("; %d of them transitions", n)
	}
	if r.Lint == "dataflow" {
		extra = fmt.Sprintf("; %d dynamic paths unknown", r.Unknown)
	}
	if r.Lint == "unraised-errors" {
		extra = fmt.Sprintf("; %d interfaces skipped for a fail code the lint can't resolve; %d unraised entries of shared error catalogs not counted", r.Unknown, r.Catalog)
	}
	gate := ""
	if max >= 0 {
		gate = fmt.Sprintf("; --max-%s %.2f: %d fragments above", r.Lint, max, above)
	}
	fmt.Fprintf(w, "%s lint: %d of %d %s (%s)%s%s\n", r.Lint, hits, of, r.Unit, pct1(hits, of), extra, gate)
	return above > 0
}

// runIntegrity runs the requested integrity lints, loading the inventory
// when one is given (inert and unscheduled use it; without it, unscheduled
// sees only interfaces tagged periodic). It reports whether a gate failed.
func runIntegrity(w io.Writer, doc *model.Document, origins map[string]string, inventory string, cites []citation,
	lints map[string]bool, g integrityGates, quiet bool) (bool, error) {
	var inv []invEntry
	if inventory != "" {
		var err error
		if inv, err = loadInventory(inventory); err != nil {
			return false, err
		}
	}
	if cites == nil {
		cites = collectCitations(doc)
	}
	failed := false
	if lints["inert"] && lintInert(doc, cites, inv, origins).print(w, g.Inert, quiet) {
		failed = true
	}
	if lints["unscheduled"] && lintUnscheduled(doc, cites, inv, origins).print(w, g.Unscheduled, quiet) {
		failed = true
	}
	if lints["dataflow"] && lintDataflow(doc, origins).print(w, g.Dataflow, quiet) {
		failed = true
	}
	var prof *lintProfile
	if lints["racy"] || lints["choice-for-computed"] {
		var err error
		if prof, err = loadLintProfile(g.Profile); err != nil {
			return false, err
		}
	}
	if lints["racy"] && lintRacyWith(doc, origins, prof).print(w, g.Racy, quiet) {
		failed = true
	}
	if lints["seam-names"] && lintSeamNames(doc, origins).print(w, g.SeamNames, quiet) {
		failed = true
	}
	if lints["unraised-errors"] && lintUnraised(doc, origins).print(w, g.Unraised, quiet) {
		failed = true
	}
	if lints["choice-for-computed"] {
		var root *codeRoot
		if g.Code != "" {
			root = newCodeRoot(g.Code)
		}
		if lintChoiceForComputed(doc, origins, prof, root).printCount(w, g.ChoiceComputed, quiet) {
			failed = true
		}
	}
	return failed, nil
}

// owned reports whether an interface belongs to its fragment: not a
// boundary stub and not owned by "shared".
func owned(attrs map[string]any) bool {
	if b, ok := attrs["boundary"]; ok && (b == true || b == "true") {
		return false
	}
	return str(attrs["owner"]) != "shared"
}

// citedEntries maps each candidate interface key (interface:<id>) to the
// unskipped inventory entries it cites at their lines or is named for, as
// coverage matches them.
func citedEntries(cand map[string]*model.Interface, cites []citation, inv []invEntry) map[string][]invEntry {
	out := map[string][]invEntry{}
	if len(inv) == 0 {
		return out
	}
	var names []named
	for _, i := range cand {
		names = append(names, named{i.Name, i.ID})
	}
	sort.Slice(names, func(a, b int) bool { return names[a].id < names[b].id })
	spans := map[string][]span{}
	dirs := map[string]bool{}
	for _, c := range cites {
		if cand[c.Entity] == nil {
			continue
		}
		f := path.Clean(normPath(c.Src.Path))
		hi := c.Src.EndLine
		if hi < c.Src.Line {
			hi = c.Src.Line
		}
		spans[f] = append(spans[f], span{c.Src.Line, hi, c.Entity})
		dirs[path.Dir(f)] = true
		dirs["area:"+area(f)] = true
	}
	hit := newHitter(inv)
	for _, e := range inv {
		if e.Skip != "" {
			continue
		}
		seen := map[string]bool{}
		for _, s := range spans[path.Clean(e.File)] {
			if !seen[s.entity] {
				if _, ok := hit([]span{s}, e); ok {
					seen[s.entity] = true
				}
			}
		}
		if want, nearKey := nameWants(e); nearKey != "" && dirs[nearKey] {
			if id := nameMatch(want, names); id != "" {
				seen["interface:"+id] = true
			}
		}
		for k := range seen {
			out[k] = append(out[k], e)
		}
	}
	return out
}

// headEntries is citedEntries for the scheduled work itself: an interface's
// own sources (not its steps') must cite an entry's first line, or the
// interface must be named for it. A helper that a step cites inside a
// service main or next to a cron loop isn't the scheduled work.
func headEntries(cand map[string]*model.Interface, inv []invEntry) map[string][]invEntry {
	out := map[string][]invEntry{}
	if len(inv) == 0 {
		return out
	}
	byFile := map[string][]span{}
	dirs := map[string]bool{}
	var names []named
	for k, i := range cand {
		names = append(names, named{i.Name, i.ID})
		for _, src := range i.Sources {
			f := path.Clean(normPath(src.Path))
			hi := max(src.EndLine, src.Line)
			byFile[f] = append(byFile[f], span{src.Line, hi, k})
			dirs[path.Dir(f)] = true
		}
	}
	sort.Slice(names, func(a, b int) bool { return names[a].id < names[b].id })
	for _, e := range inv {
		if e.Skip != "" || !scheduledKinds[e.Kind] {
			continue
		}
		seen := map[string]bool{}
		for _, sp := range byFile[path.Clean(e.File)] {
			if sp.lo > 0 && sp.lo <= e.Line+lineTolerance && sp.hi >= e.Line-lineTolerance {
				seen[sp.entity] = true
			}
		}
		// A name match must also cite the entry's file: generic names
		// (run, start) otherwise match across the directory.
		if want, nearKey := nameWants(e); nearKey != "" && dirs[nearKey] {
			if id := nameMatch(want, names); id != "" {
				for _, sp := range byFile[path.Clean(e.File)] {
					if sp.entity == "interface:"+id {
						seen[sp.entity] = true
					}
				}
			}
		}
		for k := range seen {
			out[k] = append(out[k], e)
		}
	}
	return out
}

func indexed(doc *model.Document) *model.Index {
	for k := range doc.Interfaces {
		doc.Interfaces[k].Normalize()
	}
	return model.NewIndex(doc)
}

// targetsOf lists what one step sends work to: its static call, its
// declared dynamic targets, its emit, and its publish topic's subscribers.
func targetsOf(x *model.Index, s model.Step) []string {
	var out []string
	if s.Call != "" {
		if strings.HasPrefix(s.Call, "=") {
			out = append(out, s.Targets...)
		} else {
			out = append(out, s.Call)
		}
	}
	if s.Emit != "" && !strings.HasPrefix(s.Emit, "=") {
		out = append(out, s.Emit)
	}
	if s.Publish != "" && !strings.HasPrefix(s.Publish, "=") {
		out = append(out, x.Subscribers[s.Publish]...)
	}
	return out
}

// ---- inert ----

// lintInert lists the owned interfaces with no behavior and no store that a
// flow enters, another interface's behavior calls (or emits to, or
// delivers a publish to), or that cite an inventory entry: logic the model
// declares as running, which runs as a schema-fake stub.
func lintInert(doc *model.Document, cites []citation, inv []invEntry, origins map[string]string) *integrityReport {
	x := indexed(doc)
	callers := map[string][]string{}
	for _, f := range doc.Flows {
		if f.Entry != nil {
			callers[f.Entry.Interface] = append(callers[f.Entry.Interface], "flow "+f.ID)
		}
	}
	ids := sortedIfaces(x)
	static := map[string]bool{} // reached other than as a dynamic call's declared target
	for t := range callers {
		static[t] = true
	}
	for _, id := range ids {
		i := x.Interfaces[id]
		for _, sp := range behaviorPaths(i) {
			dynamic := strings.HasPrefix(sp.Step.Call, "=")
			for _, t := range targetsOf(x, sp.Step) {
				if t != id {
					callers[t] = append(callers[t], id)
					if !dynamic || sp.Step.Emit != "" || sp.Step.Publish != "" {
						static[t] = true
					}
				}
			}
		}
	}
	// A boundary stub that is still a stub after the merge, with an area as
	// its owner, is an orphan: the owner never defined it. It counts against
	// the owner when the owner's fragment is in the merge, or when the merge
	// is one document (a merged model).
	files := map[string]string{} // base name without extension -> origin
	for _, o := range origins {
		files[strings.TrimSuffix(path.Base(o), path.Ext(o))] = o
	}
	orphanOf := map[string]string{} // interface id -> the owner's fragment
	cand := map[string]*model.Interface{}
	for _, id := range ids {
		i := x.Interfaces[id]
		if owned(i.Attributes) {
			cand["interface:"+id] = i
			continue
		}
		owner := str(i.Attributes["owner"])
		if owner == "" || owner == "shared" || (len(files) > 1 && files[owner] == "") {
			continue
		}
		cand["interface:"+id] = i
		orphanOf[id] = files[owner]
		if orphanOf[id] == "" {
			orphanOf[id] = origins[model.KindInterface+"/"+id]
		}
	}
	cited := citedEntries(cand, cites, inv)
	r := &integrityReport{Lint: "inert", Unit: "called or entry-citing owned interfaces"}
	sc := shareCounter{}
	for _, id := range ids {
		i := cand["interface:"+id]
		if i == nil {
			continue
		}
		cs, es := uniq(callers[id]), cited["interface:"+id]
		if _, orphan := orphanOf[id]; !orphan && !static[id] && allRegistered(es) {
			// Uncalled, or only listed among a dispatcher's possible targets
			// (a DI container's constructors), and only declaration-only
			// entries cite it, or none.
			continue
		}
		frag := origins[model.KindInterface+"/"+id]
		if o, ok := orphanOf[id]; ok {
			frag = o
		}
		hit := len(i.Behavior) == 0 && i.Store == nil
		if hit && (i.LatencyMS != nil || external(x.Components[i.Component])) {
			// A latency leaf (a kernel that only takes time) or a third-party
			// service: a stub by design, not logic left out.
			continue
		}
		sc.add(frag, hit)
		if !hit {
			continue
		}
		var why []string
		if len(cs) > 0 {
			why = append(why, "called by "+listSome(cs, 3))
		}
		if len(es) > 0 {
			why = append(why, fmt.Sprintf("cites %s %s", es[0].Kind, es[0].Name))
		}
		if _, ok := orphanOf[id]; ok {
			why = append([]string{"a boundary stub its owner never defined"}, why...)
		}
		r.Findings = append(r.Findings, integrityFinding{"inert", frag, id, "no behavior or store; " + strings.Join(why, "; ")})
	}
	r.finish(sc)
	return r
}

// external reports whether a component stands for third-party code: kind
// external, or attributes boundary or external.
func external(c *model.Component) bool {
	if c == nil {
		return false
	}
	return c.Kind == "external" || c.Attributes["external"] == true
}

// allRegistered reports whether every entry is of a declaration-only kind
// (level registered), which a stub models; true for none.
func allRegistered(es []invEntry) bool {
	for _, e := range es {
		if e.Level != "registered" {
			return false
		}
	}
	return true
}

// ---- unscheduled ----

// periodic reports whether an interface is tagged periodic: attributes
// tags: [periodic], periodic: true, or a schedule.
func periodic(attrs map[string]any) bool {
	if attrs["periodic"] == true || str(attrs["schedule"]) != "" {
		return true
	}
	if ts, ok := attrs["tags"].([]any); ok {
		for _, t := range ts {
			if t == "periodic" {
				return true
			}
		}
	}
	return false
}

// isStartup reports whether a flow models a process or service starting:
// its id or a tag says startup, boot, launch, init, start or main (or the
// tag is periodic or scheduled). A user action named "start" passes too,
// which can hide a finding but never makes one.
func isStartup(f *model.Flow) bool {
	if startupFlow.MatchString(strings.ToLower(f.ID)) {
		return true
	}
	for _, t := range f.Tags {
		if startupFlow.MatchString(strings.ToLower(t)) || t == "periodic" || t == "scheduled" {
			return true
		}
	}
	return false
}

// lintUnscheduled lists the owned interfaces that cite an entry of a
// scheduled kind (or are tagged periodic) but that no timer (an emit or
// publish with after_ms or every_ms), no repeating flow entry and no startup
// flow reaches. Listeners and queue consumers also count as scheduled when
// any flow delivers an event to them.
func lintUnscheduled(doc *model.Document, cites []citation, inv []invEntry, origins map[string]string) *integrityReport {
	x := indexed(doc)
	ids := sortedIfaces(x)
	var roots []string
	delivered := map[string]bool{} // emit and publish targets anywhere
	for _, id := range ids {
		for _, sp := range behaviorPaths(x.Interfaces[id]) {
			s := sp.Step
			if s.Emit == "" && s.Publish == "" {
				continue
			}
			ts := targetsOf(x, model.Step{Emit: s.Emit, Publish: s.Publish})
			for _, t := range ts {
				delivered[t] = true
			}
			if !s.AfterMS.IsZero() || !s.EveryMS.IsZero() {
				roots = append(roots, ts...)
			}
		}
	}
	for _, f := range doc.Flows {
		if f.Entry != nil && (f.Entry.Repeat != nil || isStartup(&f)) {
			roots = append(roots, f.Entry.Interface)
		}
	}
	scheduled := map[string]bool{}
	for _, id := range reach(x, roots) {
		scheduled[id] = true
	}
	// The flows and the deliveries that reach each interface otherwise, for the report.
	reachedBy := map[string][]string{}
	for _, f := range doc.Flows {
		if f.Entry == nil {
			continue
		}
		for _, id := range reach(x, []string{f.Entry.Interface}) {
			reachedBy[id] = append(reachedBy[id], f.ID)
		}
	}
	inScenario := map[string]bool{}
	for _, s := range doc.Scenarios {
		for _, id := range reach(x, entries(x, &s)) {
			inScenario[id] = true
		}
	}
	cand := map[string]*model.Interface{}
	for _, id := range ids {
		if i := x.Interfaces[id]; owned(i.Attributes) {
			cand["interface:"+id] = i
		}
	}
	var byDelivery map[string]bool
	viaDelivery := func() map[string]bool {
		if byDelivery == nil {
			byDelivery = reachedViaDelivery(x, delivered)
		}
		return byDelivery
	}
	cited := headEntries(cand, inv)
	// An entry is scheduled when any interface heading it is: the others
	// are parts of the same work (a loop's shutdown branch, one of a
	// loop's passes).
	entryDone := map[string]bool{} // file:line:name
	for k, es := range cited {
		if id := strings.TrimPrefix(k, "interface:"); scheduled[id] {
			for _, e := range es {
				entryDone[entryKey(e)] = true
			}
		}
	}
	r := &integrityReport{Lint: "unscheduled", Unit: "scheduled-kind or periodic interfaces"}
	sc := shareCounter{}
	for _, id := range ids {
		i := cand["interface:"+id]
		if i == nil {
			continue
		}
		var kind, name string
		driven, done := false, false
		for _, e := range cited["interface:"+id] {
			if kind == "" {
				kind, name = e.Kind, e.Name
			}
			driven = driven || drivenKinds[e.Kind]
			done = done || entryDone[entryKey(e)]
		}
		if kind == "" && periodic(i.Attributes) {
			kind, name = "periodic", "attributes"
		}
		if kind == "" {
			continue
		}
		frag := origins[model.KindInterface+"/"+id]
		hit := !scheduled[id] && !done && !(driven && (len(reachedBy[id]) > 0 || viaDelivery()[id]))
		sc.add(frag, hit)
		if !hit {
			continue
		}
		var why string
		switch {
		case len(reachedBy[id]) > 0:
			why = "reached only by flows with no repeat and no startup: " + listSome(reachedBy[id], 3)
		case inScenario[id]:
			why = "reached only by scenario steps"
		default:
			why = "nothing reaches it"
		}
		r.Findings = append(r.Findings, integrityFinding{"unscheduled", frag, id, fmt.Sprintf("cites %s %s; %s", kind, name, why)})
	}
	r.finish(sc)
	return r
}

func entryKey(e invEntry) string { return fmt.Sprintf("%s:%d:%s", e.File, e.Line, e.Name) }

// reachedViaDelivery returns the interfaces an event delivery (an emit or a
// publish) reaches, directly or through calls.
func reachedViaDelivery(x *model.Index, delivered map[string]bool) map[string]bool {
	from := make([]string, 0, len(delivered))
	for t := range delivered {
		from = append(from, t)
	}
	sort.Strings(from)
	out := map[string]bool{}
	for _, id := range reach(x, from) {
		out[id] = true
	}
	return out
}

// ---- dataflow ----

// A state path is a component and the literal segments under its state.
// Reads and writes are compared by prefix: a write of state.a covers a read
// of state.a.b and the other way round, so only paths no write or seed
// touches at all are reported.
type stateRead struct {
	comp    string
	segs    []string
	keyPfx  string // a store read's literal row-key prefix ("" when unknown)
	readers []string
	open    bool // some read isn't under has(): not only an optional knob
}

type stateWrite struct {
	segs   []string
	keyPfx string // a store write's literal row-key prefix, under segs[0]
	exact  bool   // keyPfx is the whole key
}

// celStateRef finds state references in CEL: "state" not preceded by an
// identifier character or a dot.
var celStateRef = regexp.MustCompile(`(^|[^A-Za-z0-9_.])state\b`)

var (
	segIdent = regexp.MustCompile(`^\.([A-Za-z_][A-Za-z0-9_]*)`)
	segIndex = regexp.MustCompile(`^\[\s*(?:'([^']*)'|"([^"]*)")\s*\]`)
)

// statePaths returns the literal segment lists of the state references in
// one CEL source, and how many references had no literal segment at all.
func statePaths(src string) (paths [][]string, unknown int) {
	for _, m := range celStateRef.FindAllStringIndex(src, -1) {
		rest := src[m[1]:]
		var segs []string
		for {
			if sm := segIdent.FindStringSubmatch(rest); sm != nil {
				after := rest[len(sm[0]):]
				if strings.HasPrefix(strings.TrimLeft(after, " "), "(") {
					break // a method: state.x.exists(...)
				}
				segs = append(segs, sm[1])
				rest = after
				continue
			}
			if sm := segIndex.FindStringSubmatch(rest); sm != nil {
				segs = append(segs, sm[1]+sm[2])
				rest = rest[len(sm[0]):]
				continue
			}
			break
		}
		if len(segs) == 0 {
			unknown++
			continue
		}
		paths = append(paths, segs)
	}
	return paths, unknown
}

// celKeys are the step keys whose string values are always CEL.
var celKeys = map[string]bool{"if": true, "when": true, "where": true, "foreach": true, "parallel": true}

// narrativeKeys hold prose, not templates.
var narrativeKeys = map[string]bool{"title": true, "detail": true, "source": true, "summary": true, "description": true}

// celStrings calls fn for every CEL source in a behavior or store spec
// decoded as plain JSON.
func celStrings(v any, key string, fn func(string)) {
	switch v := v.(type) {
	case string:
		if celKeys[key] {
			fn(v)
		} else if e, ok := strings.CutPrefix(v, "="); ok {
			fn(e)
		}
	case []any:
		for _, x := range v {
			celStrings(x, key, fn)
		}
	case map[string]any:
		for k, x := range v {
			if narrativeKeys[k] {
				continue
			}
			if k == "set" {
				if m, ok := x.(map[string]any); ok {
					for sk, sv := range m {
						if e, ok := strings.CutPrefix(sk, "="); ok {
							fn(e)
						}
						celStrings(sv, "", fn)
					}
					continue
				}
			}
			celStrings(x, k, fn)
		}
	}
}

func asJSON(v any) any {
	var out any
	b, _ := json.Marshal(v)
	_ = json.Unmarshal(b, &out)
	return out
}

// literalPrefix is the literal start of a template: the whole string when
// it isn't CEL, the leading quoted string of a CEL concatenation, or "".
var leadingQuote = regexp.MustCompile(`^\s*(?:'([^']*)'|"([^"]*)")`)

func literalPrefix(t any) (pfx string, exact bool) {
	s, ok := t.(string)
	if !ok {
		if t == nil {
			return "", false
		}
		return fmt.Sprint(t), true
	}
	e, isCEL := strings.CutPrefix(s, "=")
	if !isCEL {
		return s, true
	}
	if m := leadingQuote.FindStringSubmatch(e); m != nil {
		rest := strings.TrimSpace(e[len(m[0]):])
		return m[1] + m[2], rest == ""
	}
	return "", false
}

// leafPaths lists the paths to the leaves of a literal value (a map's empty
// value or a non-map counts as a leaf); a CEL string stops the descent.
func leafPaths(prefix []string, v any, fn func([]string)) {
	m, ok := v.(map[string]any)
	if !ok || len(m) == 0 {
		fn(prefix)
		return
	}
	for k, x := range m {
		leafPaths(append(append([]string(nil), prefix...), k), x, fn)
	}
}

func baseComp(key string) string {
	c, _, _ := strings.Cut(key, "@")
	return c
}

// lintDataflow lists the state paths and store tables that a behavior
// reads but that no behavior writes (a state set, or a store put, update or
// incr), no fixture seeds and no component initial state declares.
// Dynamic paths with no literal segment are counted as unknown, not
// flagged.
func lintDataflow(doc *model.Document, origins map[string]string) *integrityReport {
	x := indexed(doc)
	writes := map[string][]stateWrite{} // component -> writes
	wild := map[string]bool{}           // components with a dynamic state write
	reads := map[string]*stateRead{}
	r := &integrityReport{Lint: "dataflow", Unit: "read state paths and store tables"}
	addRead := func(comp, iface string, segs []string, keyPfx string) *stateRead {
		k := comp + "\x00" + strings.Join(segs, ".") + "\x00" + keyPfx
		rd := reads[k]
		if rd == nil {
			rd = &stateRead{comp: comp, segs: segs, keyPfx: keyPfx}
			reads[k] = rd
		}
		if len(rd.readers) == 0 || rd.readers[len(rd.readers)-1] != iface {
			rd.readers = append(rd.readers, iface)
		}
		return rd
	}
	for _, id := range sortedIfaces(x) {
		i := x.Interfaces[id]
		comp := i.Component
		if st := i.Store; st != nil && len(i.Behavior) == 0 && st.Table != "" {
			pfx, exact := literalPrefix(st.Key)
			switch st.Op {
			case "get", "query":
				addRead(comp, id, []string{st.Table}, pfx).open = true
			case "put", "update", "incr":
				writes[comp] = append(writes[comp], stateWrite{segs: []string{st.Table}, keyPfx: pfx, exact: exact})
			}
			if st.Where != "" {
				ps, _ := statePaths(st.Where)
				for _, p := range ps {
					addRead(comp, id, p, "").open = true
				}
			}
		}
		for _, sp := range behaviorPaths(i) {
			for k, v := range sp.Step.Set {
				var segs []string
				if e, ok := strings.CutPrefix(k, "="); ok {
					pfx, _ := literalPrefix("=" + e)
					rest, isState := strings.CutPrefix(pfx, "state.")
					if !isState {
						if strings.HasPrefix(pfx, "state") || (pfx == "" && strings.Contains(e, "state")) {
							wild[comp] = true
							r.Unknown++
						}
						continue
					}
					for _, s := range strings.Split(rest, ".") {
						if s != "" {
							segs = append(segs, s)
						}
					}
					// The last segment may be cut mid-name: keep only whole ones.
					if !strings.HasSuffix(rest, ".") && len(segs) > 0 {
						segs = segs[:len(segs)-1]
					}
					if len(segs) == 0 {
						wild[comp] = true
						r.Unknown++
						continue
					}
					writes[comp] = append(writes[comp], stateWrite{segs: segs})
					continue
				}
				rest, ok := strings.CutPrefix(k, "state.")
				if !ok {
					continue
				}
				segs = strings.Split(rest, ".")
				leafPaths(segs, asJSON(v), func(p []string) { writes[comp] = append(writes[comp], stateWrite{segs: p}) })
			}
		}
		var steps any = asJSON(i.Behavior)
		celStrings(steps, "", func(src string) {
			ps, unk := statePaths(src)
			r.Unknown += unk
			for _, p := range ps {
				rd := addRead(comp, id, p, "")
				if !strings.Contains(src, "has(state."+strings.Join(p, ".")+")") {
					rd.open = true
				}
			}
		})
	}
	// Seeds: fixtures and component initial state. Scenario state is noted, not counted.
	seed := func(comp string, st map[string]any) {
		for k, v := range st {
			leafPaths([]string{k}, asJSON(v), func(p []string) { writes[comp] = append(writes[comp], stateWrite{segs: p}) })
		}
	}
	for _, f := range doc.Fixtures {
		for c, st := range f.State {
			seed(baseComp(c), st)
		}
	}
	for _, c := range doc.Components {
		if c.State != nil {
			seed(c.ID, c.State.Initial)
		}
	}
	scenarioSeeded := map[string][]stateWrite{}
	for _, s := range doc.Scenarios {
		for c, st := range s.State {
			for k, v := range st {
				leafPaths([]string{k}, asJSON(v), func(p []string) {
					scenarioSeeded[baseComp(c)] = append(scenarioSeeded[baseComp(c)], stateWrite{segs: p})
				})
			}
		}
	}
	keys := make([]string, 0, len(reads))
	for k := range reads {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	sc := shareCounter{}
	for _, k := range keys {
		rd := reads[k]
		frag := origins[model.KindInterface+"/"+rd.readers[0]] // the first reader's fragment
		hit := !wild[rd.comp] && !covers(writes[rd.comp], rd)
		sc.add(frag, hit)
		if !hit {
			continue
		}
		subject := "state." + strings.Join(rd.segs, ".")
		if rd.keyPfx != "" {
			subject += " key " + rd.keyPfx + "*"
		}
		why := "read by " + listSome(rd.readers, 3) + "; no set, store write, fixture or initial state writes it"
		if !rd.open {
			why += "; every read is under has(), so the branch that uses it runs only when a scenario seeds it"
		}
		if covers(scenarioSeeded[rd.comp], rd) {
			why += " (only scenarios seed it)"
		}
		r.Findings = append(r.Findings, integrityFinding{"dataflow", frag, rd.comp + " " + subject, why})
	}
	r.finish(sc)
	return r
}

// covers reports whether some write touches the read's path: one is a
// prefix of the other and, for a store row key prefix, the keys agree.
func covers(ws []stateWrite, rd *stateRead) bool {
	for _, w := range ws {
		n := min(len(w.segs), len(rd.segs))
		if !equalSegs(w.segs[:n], rd.segs[:n]) {
			continue
		}
		if rd.keyPfx == "" {
			return true
		}
		// A store read with a key prefix: a whole-table write, a write
		// whose key or row path agrees with the prefix.
		var wk string
		switch {
		case len(w.segs) > 1:
			wk = w.segs[1]
			if strings.HasPrefix(wk, rd.keyPfx) || strings.HasPrefix(rd.keyPfx, wk) {
				return true
			}
		case w.keyPfx == "":
			return true
		default:
			wk = w.keyPfx
			if strings.HasPrefix(wk, rd.keyPfx) || (!w.exact && strings.HasPrefix(rd.keyPfx, wk)) {
				return true
			}
		}
	}
	return false
}

func equalSegs(a, b []string) bool {
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func sortedIfaces(x *model.Index) []string {
	ids := make([]string, 0, len(x.Interfaces))
	for id := range x.Interfaces {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func uniq(s []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, v := range s {
		if !seen[v] {
			seen[v] = true
			out = append(out, v)
		}
	}
	return out
}

func listSome(s []string, n int) string {
	s = uniq(s)
	if len(s) <= n {
		return strings.Join(s, ", ")
	}
	return fmt.Sprintf("%s and %d more", strings.Join(s[:n], ", "), len(s)-n)
}

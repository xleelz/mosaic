package main

// The unraised-errors lint (DESIGN §13.1 item 33): an owned interface
// declares an error that nothing in its behavior can produce, the "declared
// but dead" validation the round-4 blind measure found (batch's
// invalid_file, compute's cloud-init and pod admission checks, metadata
// lengths, embeddings validation).

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// engineCodes are the codes the simulator itself raises (timeouts,
// cancellation, capacity, kills and crashes): reachable on any call, so a
// declared one is never dead.
var engineCodes = map[string]bool{
	"timeout": true, "deadline_exceeded": true, "canceled": true, "cancelled": true, "overloaded": true,
	"unavailable": true, "killed": true, "peer-killed": true, "crashed": true, "insufficient": true,
}

// A catalog is an error list of at least catalogSize codes declared
// verbatim by at least catalogUses interfaces.
const catalogSize, catalogUses = 8, 5

// genericCodes are the catch-all errors of each language: internal, a
// server error, an unchecked exception.
var genericCodes = map[string]bool{
	"internal": true, "internal_error": true, "internal_server_error": true, "server_error": true,
	"exception": true, "runtime_exception": true, "error": true, "unknown": true, "unknown_error": true,
}

// genericError reports the errors the lint never lists: the generic
// internal error and status 500.
func genericError(e model.ErrorSpec) bool {
	c := strings.ToLower(strings.ReplaceAll(e.Code, "-", "_"))
	return e.Status == 500 || genericCodes[c] || engineCodes[strings.ReplaceAll(c, "_", "-")] || engineCodes[c]
}

// raiseSet is what a behavior can fail with: codes, statuses of fails whose
// code is dynamic, and whether a fail's code couldn't be resolved.
type raiseSet struct {
	codes    map[string]bool
	statuses map[int]bool
	unknown  string // the first fail the lint couldn't resolve, "" when none
	// passthrough: a fail re-raises an error its caller passes in
	// (fail: "= input.error"), so a call raises the error in the caller's
	// scope.
	passthrough bool
}

func newRaiseSet() *raiseSet { return &raiseSet{codes: map[string]bool{}, statuses: map[int]bool{}} }

func (r *raiseSet) union(o *raiseSet) {
	if o == nil {
		return
	}
	for c := range o.codes {
		r.codes[c] = true
	}
	for s := range o.statuses {
		r.statuses[s] = true
	}
}

var (
	celStringLit = regexp.MustCompile(`'([^'\\]*)'|"([^"\\]*)"`)
	celVarRef    = regexp.MustCompile(`\bvars\.([A-Za-z_][A-Za-z0-9_]*)`)
	celErrorRef  = regexp.MustCompile(`(^|[^A-Za-z0-9_.])error\b`)
	celInputRef  = regexp.MustCompile(`\binput\.[A-Za-z_]`)
)

type raiseAnalysis struct {
	x      *model.Index
	memo   map[string]*raiseSet
	active map[string]bool
	faults map[string]map[string]bool // target interface -> injected fault codes
}

// storeRaises is what a store operation can fail with (§5 and §13.1 item
// 25): a miss, and a failed write condition.
func storeRaises(st *model.StoreSpec, out *raiseSet) {
	switch st.Op {
	case "get", "update", "delete":
		if st.Op != "get" || st.Default == nil {
			out.codes[first(st.NotFound, "not_found")] = true
		}
	}
	if st.If != "" || st.IfAbsent {
		out.codes[first(st.Conflict, "condition_failed")] = true
	}
	if st.Where != "" && st.Op != "get" && st.Op != "query" {
		out.codes[first(st.Conflict, "conflict")] = true
	}
}

func (a *raiseAnalysis) limiterRaises(comp string, refs []model.LimitRef, out *raiseSet) {
	for _, ref := range refs {
		l, _, ok := a.x.Limiter(comp, ref.Limiter)
		if !ok {
			continue
		}
		out.codes[l.ErrorCode()] = true
		if l.Backend != "" && (l.OnBackendError == "" || l.OnBackendError == model.BackendPropagate) {
			out.union(a.callee(l.Backend))
		}
	}
}

// literals are the strings an interface's behavior and response hold, the
// codes it can return as data; false when it has no behavior.
func (a *raiseAnalysis) literals(id string) (map[string]bool, bool) {
	i := a.x.Interfaces[id]
	if i == nil || len(i.Behavior) == 0 {
		return nil, false
	}
	out := map[string]bool{}
	var walk func(v any)
	walk = func(v any) {
		switch v := v.(type) {
		case string:
			if e, ok := strings.CutPrefix(v, "="); ok {
				for _, m := range celStringLit.FindAllStringSubmatch(e, -1) {
					out[m[1]+m[2]] = true
				}
			} else {
				out[v] = true
			}
		case []any:
			for _, x := range v {
				walk(x)
			}
		case map[string]any:
			for _, x := range v {
				walk(x)
			}
		}
	}
	walk(asJSON(i.Behavior))
	walk(asJSON(i.Response))
	return out, true
}

// callee is what a call to an interface can fail with: what it raises,
// plus the codes scenarios inject on it as faults.
func (a *raiseAnalysis) callee(id string) *raiseSet {
	out := newRaiseSet()
	out.union(a.raises(id))
	for c := range a.faults[id] {
		out.codes[c] = true
	}
	return out
}

// raises is what an interface's own store, limits and behavior can fail
// with, following propagated errors through its callees.
func (a *raiseAnalysis) raises(id string) *raiseSet {
	if r, ok := a.memo[id]; ok {
		return r
	}
	out := newRaiseSet()
	i := a.x.Interfaces[id]
	if i == nil || a.active[id] {
		return out
	}
	a.active[id] = true
	defer delete(a.active, id)
	if i.Store != nil {
		storeRaises(i.Store, out)
	}
	a.limiterRaises(i.Component, i.Limits, out)
	if c := a.x.Components[i.Component]; c != nil && c.Capacity != nil {
		out.codes["overloaded"] = true
	}
	b := &behaviorRaises{a: a, iface: i, out: out, as: map[string]string{}, sets: map[string][]any{}}
	b.index(i.Behavior)
	b.steps(i.Behavior, nil)
	a.memo[id] = out
	return out
}

// behaviorRaises walks one behavior.
type behaviorRaises struct {
	a     *raiseAnalysis
	iface *model.Interface
	out   *raiseSet
	as    map[string]string // a call's as -> its static callee
	sets  map[string][]any  // vars.<name> -> the templates set into it
	all   []string          // every callee, for an "error" outside on_error
}

func (b *behaviorRaises) index(steps []model.Step) {
	for _, s := range steps {
		if s.Call != "" && !strings.HasPrefix(s.Call, "=") {
			if s.As != "" {
				b.as[s.As] = s.Call
			}
			b.all = append(b.all, s.Call)
		}
		for k, v := range s.Set {
			if n, ok := strings.CutPrefix(k, "vars."); ok {
				n, _, _ = strings.Cut(n, ".")
				b.sets[n] = append(b.sets[n], v)
			}
		}
		b.index(s.Then)
		b.index(s.Else)
		for _, o := range s.Options {
			b.index(o)
		}
		b.index(s.Steps)
		for _, br := range s.Branches {
			b.index(br)
		}
		b.index(s.OnItem)
		b.index(s.OnLate)
		if s.OnError != nil {
			b.index(s.OnError.Steps)
		}
	}
}

// inScope is the error a fail can re-raise here: the on_error call's, or
// outside on_error any callee's.
func (b *behaviorRaises) inScope(errCtx *raiseSet) *raiseSet {
	if errCtx != nil {
		return errCtx
	}
	out := newRaiseSet()
	for _, c := range b.all {
		if c != b.iface.ID {
			out.union(b.a.callee(c))
		}
	}
	return out
}

// call is what a call to id raises here: a callee that re-raises the error
// its caller passes in raises the error in scope.
func (b *behaviorRaises) call(id string, errCtx *raiseSet) *raiseSet {
	errs := b.a.callee(id)
	if b.a.raises(id).passthrough {
		errs.union(b.inScope(errCtx))
	}
	return errs
}

// propagated handles a step's on_error: the default and "propagate" pass
// the error up, a list of steps runs with the error in scope.
func (b *behaviorRaises) propagated(o *model.OnError, errs *raiseSet) {
	switch {
	case o == nil || o.Mode == "propagate":
		b.out.union(errs)
	case o.Mode == "" && o.Steps != nil:
		b.steps(o.Steps, errs)
	}
}

// dynamic resolves a fail whose code (or whole value) is CEL: its string
// literals, the errors of the calls whose result it reads, the literals set
// into the variables it reads, and the error in scope.
func (b *behaviorRaises) dynamic(src string, errCtx *raiseSet, seen map[string]bool) bool {
	found := false
	for _, m := range celStringLit.FindAllStringSubmatch(src, -1) {
		if s := m[1] + m[2]; s != "" {
			b.out.codes[s] = true
			found = true
		}
	}
	for _, m := range celVarRef.FindAllStringSubmatch(src, -1) {
		n := m[1]
		if seen[n] {
			continue
		}
		seen[n] = true
		if c, ok := b.as[n]; ok {
			if regexp.MustCompile(`\bvars\.` + n + `\.value\b`).MatchString(src) {
				// A code the callee returns as data: any string its
				// behavior or response holds; unknowable from a stub.
				lits, ok := b.a.literals(c)
				if !ok {
					return false
				}
				for l := range lits {
					b.out.codes[l] = true
				}
			} else {
				b.out.union(b.a.callee(c))
			}
			found = true
		}
		for _, t := range b.sets[n] {
			celStrings(asJSON(t), "", func(e string) {
				if b.dynamic(e, errCtx, seen) {
					found = true
				}
			})
			if s, ok := t.(string); ok && !strings.HasPrefix(s, "=") {
				b.out.codes[s] = true
				found = true
			}
		}
	}
	if celErrorRef.MatchString(src) {
		b.out.union(b.inScope(errCtx))
		found = true
	}
	if celInputRef.MatchString(src) {
		b.out.passthrough = true
		found = true
	}
	return found
}

func (b *behaviorRaises) fail(raw json.RawMessage, errCtx *raiseSet) {
	var v any
	if json.Unmarshal(raw, &v) != nil {
		return
	}
	switch f := v.(type) {
	case string:
		if e, ok := strings.CutPrefix(f, "="); ok && b.dynamic(e, errCtx, map[string]bool{}) {
			return
		}
	case map[string]any:
		// A literal status counts for the declared errors with that status
		// only when the code isn't literal.
		if c, lit := f["code"].(string); !lit || strings.HasPrefix(c, "=") {
			if st, ok := f["status"].(float64); ok {
				b.out.statuses[int(st)] = true
			}
		}
		switch c := f["code"].(type) {
		case string:
			if e, ok := strings.CutPrefix(c, "="); ok {
				if b.dynamic(e, errCtx, map[string]bool{}) {
					return
				}
			} else {
				b.out.codes[c] = true
				return
			}
		case nil:
			if _, ok := f["status"].(float64); ok {
				return
			}
		}
	case bool:
		return
	}
	if b.out.unknown == "" {
		b.out.unknown = oneLine(string(raw), 80)
	}
}

func (b *behaviorRaises) steps(steps []model.Step, errCtx *raiseSet) {
	for _, s := range steps {
		if len(s.Fail) > 0 {
			b.fail(s.Fail, errCtx)
		}
		switch {
		case s.Call != "":
			errs := newRaiseSet()
			if strings.HasPrefix(s.Call, "=") {
				for _, t := range s.Targets {
					errs.union(b.call(t, errCtx))
				}
			} else {
				errs.union(b.call(s.Call, errCtx))
			}
			b.propagated(s.OnError, errs)
		case s.Route != nil:
			errs := newRaiseSet()
			errs.codes["not_found"], errs.codes["method_not_allowed"] = true, true
			comp := s.Route.Component
			if comp == "" || strings.HasPrefix(comp, "=") {
				// A route by host: any routed interface may answer.
				for id, i := range b.a.x.Interfaces {
					if _, ok := model.RouteOf(i); ok {
						errs.union(b.a.callee(id))
					}
				}
			} else {
				for _, id := range b.a.x.ByComp[comp] {
					errs.union(b.a.callee(id))
				}
			}
			b.propagated(s.OnError, errs)
		case len(s.Transact) > 0:
			errs := newRaiseSet()
			for k := range s.Transact {
				storeRaises(&s.Transact[k], errs)
			}
			b.propagated(s.OnError, errs)
		case s.Admit != nil:
			errs := newRaiseSet()
			refs := s.Admit.Limiters
			if s.Admit.Limiter != "" {
				refs = append(refs, model.LimitRef{Limiter: s.Admit.Limiter})
			}
			b.a.limiterRaises(b.iface.Component, refs, errs)
			b.propagated(s.Admit.OnError, errs)
		case s.Publish != "" || s.Emit != "":
			if s.OnError != nil && s.OnError.Mode == "propagate" {
				x := b.a.x
				var ts []string
				if s.Emit != "" {
					ts = append(ts, s.Emit)
				} else {
					ts = x.Subscribers[s.Publish]
				}
				for _, t := range ts {
					b.out.union(b.a.callee(t))
				}
			}
		}
		b.handlers(s, errCtx) // receive, parallel and other handlers (§17 item 7)
		if s.IsParallel() {
			if s.OnInsufficient != nil && s.OnInsufficient.Code != "" {
				b.out.codes[s.OnInsufficient.Code] = true
			}
		}
		b.steps(s.Then, errCtx)
		b.steps(s.Else, errCtx)
		names := make([]string, 0, len(s.Options))
		for n := range s.Options {
			names = append(names, n)
		}
		sort.Strings(names)
		for _, n := range names {
			b.steps(s.Options[n], errCtx)
		}
		b.steps(s.Steps, errCtx)
		for _, br := range s.Branches {
			b.steps(br, errCtx)
		}
		b.steps(s.OnItem, errCtx)
		b.steps(s.OnLate, errCtx)
	}
}

// reachableBy reports whether a declared error is marked reachable by
// something the lint can't see: {reachable_by: "<cel or note>"} on the
// error, or the interface's attributes.reachable_by naming the code (a
// map of code to note, a list of codes, or "*").
func reachableBy(e model.ErrorSpec, attrs map[string]any) bool {
	var m map[string]any
	if b, err := json.Marshal(e); err == nil && json.Unmarshal(b, &m) == nil {
		if s := fmt.Sprint(m["reachable_by"]); m["reachable_by"] != nil && strings.TrimSpace(s) != "" {
			return true
		}
	}
	switch v := attrs["reachable_by"].(type) {
	case string:
		return v == "*"
	case []any:
		for _, c := range v {
			if str(c) == e.Code {
				return true
			}
		}
	case map[string]any:
		return str(v[e.Code]) != ""
	}
	return false
}

// lintUnraised lists the declared errors of owned interfaces with a
// behavior that no fail step, store miss or condition, transact or limiter
// in the behavior (or in an interface it propagates from) can produce. The
// share is over the declared errors the lint checks.
func lintUnraised(doc *model.Document, origins map[string]string) *integrityReport {
	x := indexed(doc)
	a := &raiseAnalysis{x: x, memo: map[string]*raiseSet{}, active: map[string]bool{}, faults: map[string]map[string]bool{}}
	addFaults := func(fs []model.Fault) {
		for _, f := range fs {
			if f.Code == "" {
				continue
			}
			if a.faults[f.Target] == nil {
				a.faults[f.Target] = map[string]bool{}
			}
			a.faults[f.Target][f.Code] = true
		}
	}
	for _, s := range doc.Scenarios {
		addFaults(s.Faults)
	}
	r := &integrityReport{Lint: "unraised-errors", Unit: "declared errors"}
	sc := shareCounter{}
	// A large error list declared verbatim by many interfaces is a protocol
	// catalog (CQL's error table on every statement), not the interface's
	// own checks: its unraised entries are counted apart.
	sets := map[string]int{}
	setOf := func(i *model.Interface) string {
		var cs []string
		for _, e := range i.Errors {
			cs = append(cs, e.Code)
		}
		sort.Strings(cs)
		return strings.Join(cs, "\x00")
	}
	for _, id := range sortedIfaces(x) {
		if i := x.Interfaces[id]; len(i.Behavior) > 0 && owned(i.Attributes) && len(i.Errors) >= catalogSize {
			sets[setOf(i)]++
		}
	}
	for _, id := range sortedIfaces(x) {
		i := x.Interfaces[id]
		if len(i.Behavior) == 0 || !owned(i.Attributes) || len(i.Errors) == 0 {
			continue
		}
		catalog := len(i.Errors) >= catalogSize && sets[setOf(i)] >= catalogUses
		frag := origins[model.KindInterface+"/"+id]
		rs := a.raises(id)
		if rs.unknown != "" {
			r.Unknown++
			continue
		}
		dup := map[string]bool{}
		for _, e := range i.Errors {
			if genericError(e) || reachableBy(e, i.Attributes) || dup[e.Code] {
				continue
			}
			dup[e.Code] = true
			hit := !rs.codes[e.Code] && !(e.Status != 0 && rs.statuses[e.Status])
			if catalog {
				if hit {
					r.Catalog++
				}
				continue
			}
			sc.add(frag, hit)
			if !hit {
				continue
			}
			var cites []string
			for _, s := range i.Sources {
				cites = append(cites, s.String())
			}
			where := "no sources cited"
			if len(cites) > 0 {
				where = "check the code at " + listSome(cites, 4)
			}
			code := e.Code
			if e.Status != 0 {
				code += fmt.Sprintf(" (%d)", e.Status)
			}
			r.Findings = append(r.Findings, integrityFinding{"unraised-errors", frag, id + " " + e.Code,
				fmt.Sprintf("declares %s, but no fail step, store miss or condition, transact or limiter in its behavior or its propagated callees produces it; %s; fix: model the check that raises it, or mark the error {reachable_by: \"<cel or note>\"}", code, where)})
		}
	}
	r.finish(sc)
	return r
}

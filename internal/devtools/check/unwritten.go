package main

// The unwritten-fields lint (DESIGN §13.1 item 37): a field a behavior
// reads that no writer ever writes. In one generated model a gateway's auth
// refused a deleted owner when profile.deletedAt was set, while the code
// and the model's own deletion writers store the marker as deletion: the
// refusal never fired, and seam-names (same name, other spelling) and
// dataflow (state paths and tables) both passed.
//
// It runs the seam-names shape inference (seamnames.go) in a stricter mode:
//   - writers are only store writes (put, update, incr, transact items),
//     fixture rows, component initial state, emits, publishes, call inputs
//     and return templates. Request and response schemas declare fields and
//     scenarios seed them; neither writes one.
//   - A store is partitioned by key pattern: the literal text of a key
//     template with a wildcard for each unknown part ('USER#' + id + '|' +
//     'A#PROFILE' is USER#*|A#PROFILE), so one single-table entity doesn't
//     lend its fields to another. A store-only interface (get, put, ...) is
//     evaluated at each call site, with that caller's input; a query takes
//     its pattern from key.startsWith / endsWith / contains / == in its
//     where; a condition string a store evaluates over row
//     (eval(input.cond, ...)) is read against the row it guards. A key with
//     no letter or digit is dynamic: its read is unknown and its write is in
//     no partition.
//   - A value of unknown shape (an expression the inference can't follow, a
//     request body, a channel receive, a dynamically keyed map) makes what
//     it is written into open; an open shape, and everything read out of
//     it, is unknown, not a finding. So is the input of an interface that
//     something outside the model enters (a route, a flow entry, a scenario
//     step, an interface nothing calls), and the state of an external
//     component, which the world writes.
//
// A finding is a member read (x.f, x['f'], has(x.f)) from a closed shape
// that names no f: a row, a call's result or value, an event's input, a
// comprehension item, or a nested field of a variable. Not findings:
//   - reads of a called interface's input (optional parameters by design),
//     and the top level of vars and state (dataflow's unit);
//   - a shape only the reader itself writes (not a seam);
//   - an optional read with a fallback (optionalIdiom): has(x.f) ? <uses
//     x.f> : d, !has(x.f) ? d : <uses x.f>, !has(x.f) || <uses x.f>.

import (
	"fmt"
	"io"
	"sort"
	"strings"

	celast "cel.dev/cel-go/common/ast"
	"cel.dev/cel-go/common/types"

	"github.com/xleelz/mosaic/internal/model"
)

// unwrittenLints are the --lint names this file implements.
var unwrittenLints = map[string]bool{"unwritten-fields": true}

func init() {
	// gates.max_unwritten_fields: no template default, so a profile that
	// doesn't set it records the findings without gating.
	profileGateDefs = append(profileGateDefs, struct{ key, flag, def, needs string }{"max_unwritten_fields", "max-unwritten-fields", "", ""})
}

// patWild is the wildcard of a key pattern: any text, possibly empty.
const patWild = "\x00"

// patMax bounds a value's pattern set; a larger one is the wildcard.
const patMax = 32

// patLen bounds a pattern's length; a longer one (a string built in a
// loop) is the wildcard.
const patLen = 256

var wildPats = &[]string{patWild}

// openLeaf is the shared shape of an unknown value. Never mutated.
var openLeaf = &nt{open: true}

// openWrap returns n marked open: an unknown value read out of an open one.
func openWrap(n *nt) *nt {
	if n == nil {
		return openLeaf
	}
	if n.open {
		return n
	}
	return &nt{kids: n.kids, elem: n.elem, open: true, pats: n.pats}
}

// patUnion is the sorted union of two pattern sets; a when b adds nothing.
func patUnion(a, b *[]string) *[]string {
	switch {
	case b == nil || a == b || isWild(a):
		return a
	case a == nil || isWild(b):
		return b
	}
	if subset(*b, *a) {
		return a
	}
	seen := map[string]bool{}
	for _, p := range *a {
		seen[p] = true
	}
	for _, p := range *b {
		seen[p] = true
	}
	if len(seen) > patMax {
		return wildPats
	}
	out := sortedKeys(seen)
	return &out
}

// isWild reports whether a pattern set admits any string.
func isWild(a *[]string) bool {
	return a != nil && len(*a) == 1 && (*a)[0] == patWild
}

// subset reports whether sorted b is within sorted a.
func subset(b, a []string) bool {
	i := 0
	for _, x := range b {
		for i < len(a) && a[i] < x {
			i++
		}
		if i == len(a) || a[i] != x {
			return false
		}
	}
	return true
}

// patsOf is n's pattern set, the wildcard when n carries none.
func patsOf(n *nt) []string {
	if n == nil || n.pats == nil {
		return []string{patWild}
	}
	return *n.pats
}

// patConcat is every pattern of a followed by every pattern of b.
func patConcat(a, b []string) []string {
	seen := map[string]bool{}
	for _, x := range a {
		for _, y := range b {
			p := x + y
			for strings.Contains(p, patWild+patWild) {
				p = strings.ReplaceAll(p, patWild+patWild, patWild)
			}
			if len(p) > patLen {
				return []string{patWild}
			}
			seen[p] = true
		}
	}
	if len(seen) > patMax {
		return []string{patWild}
	}
	return sortedKeys(seen)
}

// patMeet reports whether some string matches both patterns.
func patMeet(p, q string) bool {
	memo := map[[2]int]bool{}
	var m func(i, j int) bool
	m = func(i, j int) bool {
		k := [2]int{i, j}
		if v, ok := memo[k]; ok {
			return v
		}
		var r bool
		switch {
		case i == len(p) && j == len(q):
			r = true
		case i < len(p) && p[i] == patWild[0]:
			r = m(i+1, j) || (j < len(q) && m(i, j+1))
		case j < len(q) && q[j] == patWild[0]:
			r = m(i, j+1) || (i < len(p) && m(i+1, j))
		default:
			r = i < len(p) && j < len(q) && p[i] == q[j] && m(i+1, j+1)
		}
		memo[k] = r
		return r
	}
	return m(0, 0)
}

// patShow renders a pattern for a report, * for the wildcard.
func patShow(p string) string { return strings.ReplaceAll(p, patWild, "*") }

// uwState is the unwritten-fields mode of a seam analysis.
type uwState struct {
	lits   map[string]*nt
	views  map[uwViewKey]*uwView
	keys   map[*nt]*tableKeys
	events map[string]bool // interfaces only emitted or published to
	found  map[string]*unwrittenFinding
	skip   map[string]int // reads inside has(x.f) ? x.f : ... (defaultIdiom)
}

// tableKeys lists a table's anchored row keys in the order they appeared.
type tableKeys struct {
	seen map[string]bool
	list []string
}

// uwView is the persistent union of the rows whose key meets a pattern
// set: upto keys of the table's list are matched so far.
type uwView struct {
	n       *nt
	upto    int
	matched []*nt
}

type uwViewKey struct {
	rows *nt
	pats string
}

func newUWState() *uwState {
	return &uwState{lits: map[string]*nt{}, views: map[uwViewKey]*uwView{}, keys: map[*nt]*tableKeys{},
		events: map[string]bool{}, found: map[string]*unwrittenFinding{}, skip: map[string]int{}}
}

// lit is the shared shape of a string literal. Never mutated.
func (u *uwState) lit(s string) *nt {
	n := u.lits[s]
	if n == nil {
		p := []string{s}
		n = &nt{pats: &p}
		u.lits[s] = n
	}
	return n
}

// patAnchored reports whether a pattern has a letter or digit: a key with
// none ('*', '*|*') is dynamic, unknown to read and too wide to write.
func patAnchored(p string) bool {
	for _, r := range p {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' {
			return true
		}
	}
	return false
}

// keysOf brings a table's key list up to date with its rows.
func (u *uwState) keysOf(rows *nt) *tableKeys {
	t := u.keys[rows]
	if t == nil {
		t = &tableKeys{seen: map[string]bool{}}
		u.keys[rows] = t
	}
	if len(t.seen) < len(rows.kids) {
		var add []string
		for k := range rows.kids {
			if !t.seen[k] {
				t.seen[k] = true
				if patAnchored(k) {
					add = append(add, k)
				}
			}
		}
		sort.Strings(add)
		t.list = append(t.list, add...)
	}
	return t
}

// prepare marks the inputs of interfaces entered from outside the model
// open and finds the interfaces only events reach.
func (u *uwState) prepare(a *seamAnalysis, doc *model.Document) {
	x := a.x
	called, sent := map[string]bool{}, map[string]bool{}
	for _, id := range sortedIfaces(x) {
		for _, sp := range behaviorPaths(x.Interfaces[id]) {
			s := sp.Step
			if s.Call != "" {
				if strings.HasPrefix(s.Call, "=") {
					for _, t := range s.Targets {
						called[t] = true
					}
				} else {
					called[s.Call] = true
				}
			}
			if s.Route != nil {
				// a route call reaches whatever the router matches
				for _, t := range s.Targets {
					called[t] = true
				}
			}
			if s.Emit != "" && !strings.HasPrefix(s.Emit, "=") {
				sent[s.Emit] = true
			}
			if s.Publish != "" && !strings.HasPrefix(s.Publish, "=") {
				for _, t := range x.Subscribers[s.Publish] {
					sent[t] = true
				}
			}
		}
	}
	entered := map[string]bool{}
	for _, f := range doc.Flows {
		if f.Entry != nil {
			entered[f.Entry.Interface] = true
		}
	}
	for _, sc := range doc.Scenarios {
		for _, st := range sc.Steps {
			if st.Interface != "" {
				entered[st.Interface] = true
			}
		}
	}
	for _, comp := range doc.Components {
		if comp.Kind == "external" {
			// the world writes an external system's state; scenarios seed it
			a.node(a.state, comp.ID).open = true
		}
	}
	for _, id := range sortedIfaces(x) {
		external := a.routes[id] || entered[id] || (!called[id] && !sent[id])
		if external {
			n := a.node(a.in, id)
			n.open = true
		} else if sent[id] && !called[id] {
			u.events[id] = true
		}
	}
}

// callRes is the shape of vars.<as> after a call; the unwritten-fields mode
// knows every key the engine sets.
func (a *seamAnalysis) callRes(value *nt) *nt {
	if a.uw == nil {
		return callResult(value)
	}
	return callResultKeys(value, []string{"duration_us", "cancelled_at_ms", "items", "results"})
}

// openUnmodeled marks open the variables a step sets that the inference
// doesn't follow: a route call's, a receive's or a rendezvous's result, a
// stream's items, a join's result.
func (a *seamAnalysis) openUnmodeled(c *seamCtx, s model.Step, handled bool) {
	mark := func(name string) {
		n := a.child(c.vars, name, c.writer)
		if !n.open {
			n.open = true
			a.touch(n)
		}
	}
	if s.As != "" && (!handled || s.Stream) {
		mark(s.As)
	}
	if s.AsResult != "" {
		mark(s.AsResult)
	}
	if len(s.OnItem) > 0 {
		mark("item")
	}
}

// isUnknown reports whether arg evaluated to nil because its shape is
// unknown rather than because it is a literal.
func isUnknown(arg celast.Expr, v *nt) bool {
	return v == nil && arg.Kind() != celast.LiteralKind
}

// uwCall evaluates the calls whose shape the unwritten-fields mode tracks:
// string concatenation (key patterns), and merges and ternaries with an
// operand of unknown shape (open).
func (c *seamCtx) uwCall(fn string, args []celast.Expr, vals []*nt) (*nt, bool) {
	off := len(vals) - len(args) // a member call's target comes first
	switch fn {
	case "_+_":
		if len(args) != 2 || off != 0 {
			return nil, false
		}
		str := false
		for i, x := range args {
			if vals[i] != nil && vals[i].pats != nil {
				str = true
			}
			if x.Kind() == celast.LiteralKind {
				if _, ok := x.AsLiteral().(types.String); ok {
					str = true
				}
			}
		}
		if str {
			p := patConcat(patsOf(vals[0]), patsOf(vals[1]))
			return &nt{pats: &p}, true
		}
		out := seamMerge(vals[0], vals[1], 0)
		if isUnknown(args[0], vals[0]) || isUnknown(args[1], vals[1]) {
			out = openWrap(out)
		}
		return out, true
	case "_?_:_":
		if len(vals) != 3 || off != 0 {
			return nil, false
		}
		out := seamMerge(vals[1], vals[2], 0)
		if isUnknown(args[1], vals[1]) || isUnknown(args[2], vals[2]) {
			out = openWrap(out)
		}
		return out, true
	case "merge":
		var out *nt
		unknown := false
		for i, v := range vals {
			out = seamMerge(out, v, 0)
			if i >= off && isUnknown(args[i-off], v) {
				unknown = true
			} else if i < off && v == nil {
				unknown = true
			}
		}
		if unknown {
			out = openWrap(out)
		}
		return out, true
	case "first", "last":
		if len(vals) > 0 && vals[0] != nil {
			if vals[0].open {
				return openWrap(vals[0].elem), true
			}
			return vals[0].elem, true
		}
	}
	return nil, false
}

// optionalIdiom recognizes an optional field read with a fallback and
// returns the keys (exprPath(x), f) of the fields it reads that way:
//   - has(x.f) [&& ...] ? <uses x.f> : <fallback>, and 'f' in x likewise;
//   - !has(x.f) [|| ...] ? <fallback> : <uses x.f>;
//   - has(x.f) ? x.f : x.g, a second spelling as the fallback;
//   - !has(x.f) || <uses x.f>, a default of true.
//
// Nothing is decided on f there beyond using it when present, so an f no
// writer writes is not a finding. A test whose branch doesn't use the field
// (has(x.f) && x.f != "" ? a : b) still is.
func optionalIdiom(fn string, args []celast.Expr) []string {
	var keys []string
	use := func(k fieldKey, in celast.Expr) {
		if usesField(in, k) {
			keys = append(keys, k.path+"\x00"+k.field)
		}
	}
	switch {
	case fn == "_?_:_" && len(args) == 3:
		for _, k := range presenceTests(args[0], "_&&_", false) {
			use(k, args[1])
			if args[2].Kind() == celast.SelectKind && !args[2].AsSelect().IsTestOnly() && exprPath(args[2].AsSelect().Operand()) == k.path && usesField(args[1], k) {
				keys = append(keys, k.path+"\x00"+args[2].AsSelect().FieldName())
			}
		}
		for _, k := range presenceTests(args[0], "_||_", true) {
			use(k, args[2])
		}
	case fn == "_||_" && len(args) == 2:
		for _, k := range presenceTests(args[0], "_||_", true) {
			use(k, args[1])
		}
	}
	return keys
}

type fieldKey struct{ path, field string }

// presenceTests lists the has(x.f) and 'f' in x tests among the operands of
// a chain of op (&& or ||), each under ! when negated.
func presenceTests(e celast.Expr, op string, negated bool) []fieldKey {
	if e.Kind() != celast.CallKind {
		if !negated && e.Kind() == celast.SelectKind && e.AsSelect().IsTestOnly() {
			if p := exprPath(e.AsSelect().Operand()); !strings.Contains(p, "(...)") {
				return []fieldKey{{p, e.AsSelect().FieldName()}}
			}
		}
		return nil
	}
	call := e.AsCall()
	args := call.Args()
	switch fn := call.FunctionName(); {
	case fn == op && len(args) == 2:
		return append(presenceTests(args[0], op, negated), presenceTests(args[1], op, negated)...)
	case fn == "!_" && len(args) == 1:
		if negated {
			return presenceTests(args[0], op, false)
		}
	case fn == "@in" && len(args) == 2 && !negated:
		if args[0].Kind() == celast.LiteralKind {
			if f, ok := args[0].AsLiteral().(types.String); ok {
				if p := exprPath(args[1]); !strings.Contains(p, "(...)") {
					return []fieldKey{{p, string(f)}}
				}
			}
		}
	}
	return nil
}

// usesField reports whether e reads x.f (or x['f']) for k = (x, f).
func usesField(e celast.Expr, k fieldKey) bool {
	found := false
	var walk func(e celast.Expr)
	walk = func(e celast.Expr) {
		if found {
			return
		}
		switch e.Kind() {
		case celast.SelectKind:
			s := e.AsSelect()
			if s.FieldName() == k.field && exprPath(s.Operand()) == k.path {
				found = true
				return
			}
			walk(s.Operand())
		case celast.CallKind:
			c := e.AsCall()
			if c.FunctionName() == "_[_]" && len(c.Args()) == 2 && c.Args()[1].Kind() == celast.LiteralKind {
				if f, ok := c.Args()[1].AsLiteral().(types.String); ok && string(f) == k.field && exprPath(c.Args()[0]) == k.path {
					found = true
					return
				}
			}
			if c.IsMemberFunction() {
				walk(c.Target())
			}
			for _, a := range c.Args() {
				walk(a)
			}
		case celast.ListKind:
			for _, x := range e.AsList().Elements() {
				walk(x)
			}
		case celast.MapKind:
			for _, en := range e.AsMap().Entries() {
				if en.Kind() == celast.MapEntryKind {
					walk(en.AsMapEntry().Key())
					walk(en.AsMapEntry().Value())
				}
			}
		case celast.ComprehensionKind:
			cp := e.AsComprehension()
			for _, x := range []celast.Expr{cp.IterRange(), cp.AccuInit(), cp.LoopCondition(), cp.LoopStep(), cp.Result()} {
				walk(x)
			}
		}
	}
	walk(e)
	return found
}

// rootIdent is the identifier a member chain starts from, "" when none.
func rootIdent(e celast.Expr) string {
	for {
		switch e.Kind() {
		case celast.IdentKind:
			return e.AsIdent()
		case celast.SelectKind:
			e = e.AsSelect().Operand()
		case celast.CallKind:
			c := e.AsCall()
			if c.FunctionName() != "_[_]" || len(c.Args()) != 2 {
				return ""
			}
			e = c.Args()[0]
		default:
			return ""
		}
	}
}

// unwrittenFinding is one field read that no writer writes.
type unwrittenFinding struct {
	Reader  string   // the reading interface
	Field   string   // the field read
	At      string   // the operand it is read from
	Written []string // the fields the operand's writers write
	Writers []string // who writes them
	Closest string   // the written name closest to Field, "" when none is close
}

// unwrittenSelect checks one member read in the unwritten-fields mode.
func (c *seamCtx) unwrittenSelect(op *nt, operand celast.Expr, field string) {
	if !c.a.check || c.nocheck || c.iface == "" || op == nil || op.open || op.elem != nil || len(op.kids) == 0 || headerAlias(field) {
		return
	}
	if _, ok := op.kids[field]; ok {
		return
	}
	if operand.Kind() == celast.IdentKind {
		switch operand.AsIdent() {
		case "vars", "state":
			return // the top level: dataflow's unit
		}
	}
	if r := rootIdent(operand); r == "input" && !c.a.uw.events[c.iface] {
		return // a request: an optional parameter of a called interface
	}
	at := exprPath(operand)
	if c.a.uw.skip[at+"\x00"+field] > 0 {
		return
	}
	k := c.iface + "\x00" + at + "\x00" + field
	if c.a.uw.found[k] != nil {
		return
	}
	f := &unwrittenFinding{Reader: c.iface, Field: field, At: at}
	ws := map[string]bool{}
	mixed := false // vars reused for a call and its value: list the value's names
	for _, v := range op.kids {
		if v.src != "the call result" {
			mixed = true
		}
	}
	for _, name := range sortedKeys(op.kids) {
		w := op.kids[name].src
		if mixed && w == "the call result" {
			continue
		}
		f.Written = append(f.Written, name)
		if w != "" && w != "the call result" {
			ws[w] = true
		}
	}
	f.Writers = sortedKeys(ws)
	if len(f.Writers) == 1 && f.Writers[0] == c.iface {
		return // a shape the reader builds itself: not a seam
	}
	f.Closest = closestName(field, f.Written)
	c.a.uw.found[k] = f
}

// closestName is the written name most like field: the longest common
// prefix (case-insensitive), then the smallest edit distance; "" when no
// name is close (an edit distance above half the longer name and a common
// prefix under 4).
func closestName(field string, names []string) string {
	lf := strings.ToLower(field)
	best, bestPfx, bestDist := "", -1, 0
	for _, n := range names {
		ln := strings.ToLower(n)
		p := 0
		for p < len(lf) && p < len(ln) && lf[p] == ln[p] {
			p++
		}
		d := editDistance(lf, ln)
		longer := max(len(lf), len(ln))
		if p < 4 && 2*d > longer {
			continue
		}
		if p > bestPfx || (p == bestPfx && d < bestDist) {
			best, bestPfx, bestDist = n, p, d
		}
	}
	return best
}

func editDistance(a, b string) int {
	prev := make([]int, len(b)+1)
	cur := make([]int, len(b)+1)
	for j := range prev {
		prev[j] = j
	}
	for i := 1; i <= len(a); i++ {
		cur[0] = i
		for j := 1; j <= len(b); j++ {
			cost := 1
			if a[i-1] == b[j-1] {
				cost = 0
			}
			cur[j] = min(prev[j]+1, cur[j-1]+1, prev[j-1]+cost)
		}
		prev, cur = cur, prev
	}
	return prev[len(b)]
}

// storeInline evaluates a store-only interface at one call site: its key,
// value and conditions see the caller's input.
func (a *seamAnalysis) storeInline(c *seamCtx, callee *model.Interface, st *model.StoreSpec, input any) *nt {
	v := c.tmpl(input)
	if v == nil {
		v = openLeaf
	}
	rc := &seamCtx{a: a, iface: c.iface, writer: c.writer, input: v, vars: newNT(), state: a.node(a.state, callee.Component), nocheck: true}
	rows := a.child(rc.state, st.Table, callee.ID)
	raw, _ := input.(map[string]any)
	return a.storeUW(rc, st, rows, raw)
}

// keyPats is the key patterns a store operation touches.
func (a *seamAnalysis) keyPats(c *seamCtx, st *model.StoreSpec) []string {
	if st.Key != nil && st.Op != "query" {
		return patsOf(c.tmpl(asJSON(st.Key)))
	}
	if st.Where != "" {
		if e := a.parse(strings.TrimSpace(st.Where)); e != nil {
			if p := c.wherePats(e); p != nil {
				return p
			}
		}
	}
	return []string{patWild}
}

// wherePats is the key patterns a where admits: key.startsWith(x),
// key.endsWith(x), key.contains(x) and key == x, through ?:, || and &&;
// nil when it doesn't constrain the key.
func (c *seamCtx) wherePats(e celast.Expr) []string {
	if e.Kind() != celast.CallKind {
		return nil
	}
	call := e.AsCall()
	args := call.Args()
	isKey := func(x celast.Expr) bool { return x.Kind() == celast.IdentKind && x.AsIdent() == "key" }
	either := func(x, y celast.Expr) []string {
		p, q := c.wherePats(x), c.wherePats(y)
		if p == nil || q == nil {
			return nil
		}
		return sortedKeys(setOf(append(p, q...)))
	}
	switch fn := call.FunctionName(); {
	case fn == "_?_:_" && len(args) == 3:
		return either(args[1], args[2])
	case fn == "_||_" && len(args) == 2:
		return either(args[0], args[1])
	case fn == "_&&_" && len(args) == 2:
		if p := c.wherePats(args[0]); p != nil {
			return p
		}
		return c.wherePats(args[1])
	case fn == "_==_" && len(args) == 2:
		if isKey(args[0]) {
			return patsOf(c.eval(args[1]))
		}
		if isKey(args[1]) {
			return patsOf(c.eval(args[0]))
		}
	case call.IsMemberFunction() && isKey(call.Target()) && len(args) == 1:
		p := patsOf(c.eval(args[0]))
		switch fn {
		case "startsWith":
			return patConcat(p, []string{patWild})
		case "endsWith":
			return patConcat([]string{patWild}, p)
		case "contains":
			return patConcat(patConcat([]string{patWild}, p), []string{patWild})
		}
	}
	return nil
}

func setOf(xs []string) map[string]bool {
	m := map[string]bool{}
	for _, x := range xs {
		m[x] = true
	}
	return m
}

// rowsView is the persistent union of the rows of a table whose key
// pattern meets one of pats. A dynamic key (no pattern anchored) reads an
// unknown row, and a row written under a dynamic key is in no view.
func (a *seamAnalysis) rowsView(rows *nt, pats []string) *nt {
	for _, p := range pats {
		if !patAnchored(p) {
			return openLeaf
		}
	}
	k := uwViewKey{rows, strings.Join(pats, "\x01")}
	v := a.uw.views[k]
	if v == nil {
		v = &uwView{n: newNT()}
		v.n.persist = true
		a.uw.views[k] = v
	}
	t := a.uw.keysOf(rows)
	for ; v.upto < len(t.list); v.upto++ {
		rk := t.list[v.upto]
		for _, p := range pats {
			if patMeet(rk, p) {
				v.matched = append(v.matched, rows.kids[rk].n)
				break
			}
		}
	}
	a.union(v.n, rows.elem, 0, false)
	for _, m := range v.matched {
		a.union(v.n, m, 0, false)
	}
	return v.n
}

// storeUW is storeSpec in the unwritten-fields mode: rows are kept per key
// pattern. raw is the caller's literal input of an inlined store interface,
// whose condition strings are read against the row they guard.
func (a *seamAnalysis) storeUW(c *seamCtx, st *model.StoreSpec, rows *nt, raw map[string]any) *nt {
	pats := a.keyPats(c, st)
	view := a.rowsView(rows, pats)
	rc := *c
	rc.row = view
	for _, src := range []string{st.Where, st.If} {
		if src == "" {
			continue
		}
		e := a.parse(strings.TrimSpace(src))
		if e == nil {
			continue
		}
		rc.eval(e)
		if raw != nil {
			a.condStrings(c, e, raw, view)
		}
	}
	switch st.Op {
	case "put", "update", "incr":
		v := c.tmpl(asJSON(st.Value))
		if v == nil {
			v = openLeaf
		}
		for _, p := range pats {
			if patAnchored(p) {
				a.grow(a.child(rows, p, c.writer), v)
			}
		}
		return a.rowsView(rows, pats)
	case "get", "delete":
		out := view
		if st.Default != nil {
			out = seamMerge(out, c.tmpl(asJSON(st.Default)), 0)
		}
		return out
	case "query":
		l := newNT()
		l.elem = view
		return l
	}
	return nil
}

// condStrings reads the CEL strings a store condition evaluates
// (eval(input.<k>, ...)) from the caller's literal input against row.
func (a *seamAnalysis) condStrings(c *seamCtx, e celast.Expr, raw map[string]any, row *nt) {
	var walk func(e celast.Expr)
	walk = func(e celast.Expr) {
		if e.Kind() != celast.CallKind {
			return
		}
		call := e.AsCall()
		args := call.Args()
		if call.FunctionName() == "eval" && len(args) >= 1 && args[0].Kind() == celast.SelectKind {
			s := args[0].AsSelect()
			if op := s.Operand(); op.Kind() == celast.IdentKind && op.AsIdent() == "input" {
				if src, ok := raw[s.FieldName()].(string); ok && !strings.HasPrefix(src, "=") {
					if ce := a.parse(strings.TrimSpace(src)); ce != nil {
						cc := &seamCtx{a: a, iface: c.iface, writer: c.writer, row: row}
						cc.eval(ce)
					}
				}
			}
		}
		if call.IsMemberFunction() {
			walk(call.Target())
		}
		for _, x := range args {
			walk(x)
		}
	}
	walk(e)
}

type unwrittenReport struct {
	Findings []unwrittenFinding
	Frags    map[string]string // reader -> fragment
}

// lintUnwrittenFields runs the unwritten-fields analysis.
func lintUnwrittenFields(doc *model.Document, origins map[string]string) *unwrittenReport {
	u := newUWState()
	runSeamAnalysis(doc, u)
	r := &unwrittenReport{Frags: map[string]string{}}
	for _, f := range u.found {
		r.Findings = append(r.Findings, *f)
		r.Frags[f.Reader] = writerFrag(origins, f.Reader)
	}
	sort.Slice(r.Findings, func(i, j int) bool {
		p, q := r.Findings[i], r.Findings[j]
		if p.Reader != q.Reader {
			return p.Reader < q.Reader
		}
		if p.At != q.At {
			return p.At < q.At
		}
		return p.Field < q.Field
	})
	return r
}

// listShort joins at most n names, then "and N more".
func listShort(xs []string, n int) string {
	if len(xs) == 0 {
		return "-"
	}
	if len(xs) <= n {
		return strings.Join(xs, ", ")
	}
	return fmt.Sprintf("%s and %d more", strings.Join(xs[:n], ", "), len(xs)-n)
}

// print lists the findings (unless quiet), the count per reader fragment
// and the total, with the gate line when max >= 0, and reports whether the
// total is above max.
func (r *unwrittenReport) print(w io.Writer, max int, quiet bool) bool {
	per := map[string]int{}
	for _, f := range r.Findings {
		fr := first(r.Frags[f.Reader], "(no fragment)")
		per[fr]++
		if quiet {
			continue
		}
		hint := ""
		if f.Closest != "" {
			hint = "; closest written: " + f.Closest
		}
		fmt.Fprintf(w, "! unwritten-fields %s (%s): %s reads %s.%s; no writer writes it%s. Written: %s, by %s\n",
			f.Field, fr, f.Reader, f.At, f.Field, hint, listShort(f.Written, 8), listShort(f.Writers, 4))
	}
	for _, fr := range sortedKeys(per) {
		fmt.Fprintf(w, "  unwritten-fields in %s: %d\n", fr, per[fr])
	}
	n := len(r.Findings)
	over := max >= 0 && n > max
	mark := ""
	if over {
		mark = "✗ "
	}
	fmt.Fprintf(w, "%sunwritten-fields lint: %d fields read that no writer writes\n", mark, n)
	if max >= 0 {
		gm := "✓"
		if over {
			gm = "✗"
		}
		fmt.Fprintf(w, "%s unwritten-fields gate: %d, --max-unwritten-fields %d\n", gm, n, max)
		ratchetHint(w, "max-unwritten-fields", float64(n), float64(max))
	}
	return over
}

// runUnwrittenFields runs --lint unwritten-fields and reports whether its
// gate failed.
func runUnwrittenFields(w io.Writer, doc *model.Document, origins map[string]string, lints map[string]bool, quiet bool) bool {
	if !lints["unwritten-fields"] {
		return false
	}
	return lintUnwrittenFields(doc, origins).print(w, *maxUnwritten, quiet)
}

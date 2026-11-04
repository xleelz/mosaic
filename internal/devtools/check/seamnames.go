package main

// The seam-names lint (DESIGN §13.1 item 29): one field, two spellings. In
// one generated model a key service stored a key's budget as limitUSD and a
// budget gate read limitUsd; every gate passed because each side was
// consistent with itself.
//
// The lint infers the field names each seam carries and follows them across
// the model: the literal keys of store writes (put, update, incr, transact
// items), fixture and initial rows; of call, emit and publish inputs; of
// returns; and the declared request and response schema properties. A value
// passed whole (an input field, a variable, a row read back, a call's
// result) carries its names along, through vars, merges, ternaries, list
// macros and nested calls, until no shape grows. Then every member a
// behavior selects (x.f, x['f'], has(x.f), row.f in a store's where or if)
// is checked against the names its operand carries: a name with no exact
// match that matches another after normalizing (lower case, without _, -
// and spaces) is a finding. So is a call key that matches the callee's
// request schema property only after normalizing.
//
// Not findings: route inputs (headers are normalized by design, item 26),
// x_* header aliases, and a behavior's own vars (not a seam). Scenarios are
// not writers: they are how a misspelled seam passes.

import (
	"fmt"
	"io"
	"sort"
	"strings"

	"cel.dev/cel-go/cel"
	celast "cel.dev/cel-go/common/ast"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/ext"

	"github.com/xleelz/mosaic/internal/model"
)

// nt is an inferred value shape: the field names it carries, who first
// wrote each, and the shape of its list items or dynamically keyed values.
// Persistent nodes (interface inputs and outputs, vars, state, table rows)
// form trees with parent links; a stamp records the clock of the last change
// anywhere below, so a union from an unchanged persistent node is skipped.
// Temporaries (a template's value, a ternary) are never persistent.
//
// kids stays nil until the first name: most nodes are leaves, and a large
// model holds millions of them.
type nt struct {
	kids    map[string]seamField
	elem    *nt
	parent  *nt
	persist bool
	// open (unwritten-fields mode only): some writer put a value of unknown
	// shape here, so a name missing from kids may still be written.
	open bool
	lvl  int
	// pats (unwritten-fields mode only): the string patterns this value can
	// take, literal text with patWild for an unknown part.
	pats  *[]string
	stamp uint64
	// The last copy into this node from below a tracked one (see union).
	copyFrom  *nt
	copyDepth int
	copyAt    uint64
}

// seamField is one name of a shape: its value's shape and who first wrote
// it. A temporary shares value shapes, so the writer is kept per parent.
type seamField struct {
	n   *nt
	src string
}

func newNT() *nt { return &nt{} }

// kid returns field k's shape, nil when there is none.
func (n *nt) kid(k string) *nt { return n.kids[k].n }

// set adds or replaces field k, written by writer.
func (n *nt) set(k string, v *nt, writer string) {
	if n.kids == nil {
		n.kids = map[string]seamField{}
	}
	n.kids[k] = seamField{v, writer}
}

// seamMaxDepth bounds shape depth, so self-referencing values stay finite.
const seamMaxDepth = 6

// sub makes a child node of n: persistent under a persistent parent.
func (n *nt) sub() *nt {
	d := newNT()
	if n.persist {
		d.persist, d.parent, d.lvl = true, n, n.lvl+1
	}
	return d
}

// touch records a change at n and above.
func (a *seamAnalysis) touch(n *nt) {
	a.clock++
	a.changed = true
	for p := n; p != nil; p = p.parent {
		p.stamp = a.clock
	}
}

// child returns n's field k, adding it (written by writer) when missing.
func (a *seamAnalysis) child(n *nt, k, writer string) *nt {
	if d, ok := n.kids[k]; ok {
		return d.n
	}
	d := n.sub()
	n.set(k, d, writer)
	if n.persist {
		a.touch(n)
	}
	return d
}

// elemOf returns n's item shape, adding it when missing.
func (a *seamAnalysis) elemOf(n *nt) *nt {
	if n.elem == nil {
		n.elem = n.sub()
		if n.persist {
			a.touch(n)
		}
	}
	return n.elem
}

// union copies src's names into dst and reports whether dst grew. under
// says src lies below a persistent node already being copied whole.
func (a *seamAnalysis) union(dst, src *nt, depth int, under bool) bool {
	if src == nil || dst == nil || dst == src || depth > seamMaxDepth || (dst.persist && dst.lvl > seamMaxDepth+2) {
		return false
	}
	track := src.persist && !under
	key := [2]*nt{dst, src}
	if track {
		if s, ok := a.sync[key]; ok && src.stamp <= s {
			return false
		}
	}
	// Below a tracked node the copy is a plain one, bounded by depth. If src
	// has not changed since it was last copied into dst at this depth, dst
	// already holds it (dst only grows), so the copy would add nothing. The
	// clock is taken before the copy, so a src that grows during it (dst
	// below src) is copied again next time.
	memo := under && src.persist
	start := a.clock
	if memo && dst.copyFrom == src && dst.copyDepth == depth && src.stamp <= dst.copyAt {
		return false
	}
	changed := false
	for k, v := range src.kids {
		f, ok := dst.kids[k]
		d := f.n
		if !ok {
			d = dst.sub()
			dst.set(k, d, v.src)
			changed = true
		}
		if a.union(d, v.n, depth+1, under || src.persist) {
			changed = true
		}
	}
	if src.elem != nil {
		if dst.elem == nil {
			dst.elem = dst.sub()
			changed = true
		}
		if a.union(dst.elem, src.elem, depth+1, under || src.persist) {
			changed = true
		}
	}
	if src.open && !dst.open {
		dst.open, changed = true, true
	}
	if src.pats != nil {
		if p := patUnion(dst.pats, src.pats); p != dst.pats {
			dst.pats, changed = p, true
		}
	}
	if changed && dst.persist {
		a.touch(dst)
	}
	if track {
		a.sync[key] = a.clock
	}
	if memo {
		dst.copyFrom, dst.copyDepth, dst.copyAt = src, depth, start
	}
	return changed
}

// seamMerge is a shallow union that shares structure and changes neither
// side; it is for temporaries (a ternary, merge(), a dynamic index).
func seamMerge(a, b *nt, depth int) *nt {
	switch {
	case a == nil:
		return b
	case b == nil || a == b || depth > seamMaxDepth:
		return a
	}
	n := newNT()
	for k, v := range a.kids {
		n.set(k, v.n, v.src)
	}
	for k, v := range b.kids {
		if o, ok := n.kids[k]; ok {
			n.set(k, seamMerge(o.n, v.n, depth+1), o.src)
		} else {
			n.set(k, v.n, v.src)
		}
	}
	n.elem = seamMerge(a.elem, b.elem, depth+1)
	n.open = a.open || b.open
	n.pats = patUnion(a.pats, b.pats)
	return n
}

// seamMergeAll is seamMerge folded left over xs, in one pass: folding pair
// by pair copies the growing union once per operand, which is quadratic in
// the number of names.
func seamMergeAll(xs []*nt, depth int) *nt {
	var first *nt
	live := xs[:0:0]
	for _, x := range xs {
		if x == nil {
			continue
		}
		if first == nil {
			first = x
		}
		if x != first {
			live = append(live, x)
		}
	}
	if first == nil || len(live) == 0 || depth > seamMaxDepth {
		return first
	}
	live = append([]*nt{first}, live...)
	n := newNT()
	var order []string
	group := map[string][]*nt{}
	writer := map[string]string{}
	var elems []*nt
	for _, x := range live {
		for k, v := range x.kids {
			if _, ok := group[k]; !ok {
				order = append(order, k)
				writer[k] = v.src
			}
			group[k] = append(group[k], v.n)
		}
		elems = append(elems, x.elem)
		n.open = n.open || x.open
		n.pats = patUnion(n.pats, x.pats)
	}
	for _, k := range order {
		n.set(k, seamMergeAll(group[k], depth+1), writer[k])
	}
	n.elem = seamMergeAll(elems, depth+1)
	return n
}

// dynIndex is what x[e] gives for a non-literal e: a list's item or any of
// a map's values.
func dynIndex(n *nt) *nt {
	if n == nil {
		return nil
	}
	xs := []*nt{n.elem}
	for _, k := range sortedKeys(n.kids) {
		xs = append(xs, n.kids[k].n)
	}
	if n.open {
		return openWrap(seamMergeAll(xs, 0))
	}
	return seamMergeAll(xs, 0)
}

// seamNorm is the spelling-insensitive form of a field name.
func seamNorm(s string) string {
	return strings.NewReplacer("_", "", "-", "", " ", "").Replace(strings.ToLower(s))
}

// headerAlias reports an x_* header alias, which routes normalize by design.
func headerAlias(s string) bool {
	l := strings.ToLower(s)
	return strings.HasPrefix(l, "x_") || strings.HasPrefix(l, "x-")
}

type seamFinding struct {
	Read, Write    string // the reader's and the writer's spelling
	Reader, Writer string // interface ids, or "fixture <id>", "initial state of <c>", "schema of <iface>"
	At             string // the operand the reader selects from, or "call <callee>"
	Call           bool   // a call key against the callee's request schema
}

type seamReport struct {
	Findings []seamFinding
	Frags    map[string]string // reader or writer -> fragment
}

type seamAnalysis struct {
	x       *model.Index
	env     *cel.Env
	asts    map[string]celast.Expr
	in, out map[string]*nt
	vars    map[string]*nt
	state   map[string]*nt
	routes  map[string]bool
	reqs    map[string]*shape
	resolve func(string) (any, bool)
	check   bool
	changed bool
	clock   uint64
	sync    map[[2]*nt]uint64 // (dst, persistent src) -> clock of their last union
	views   map[*nt]*nt       // a table node -> the union of its rows
	found   map[string]*seamFinding
	// uw is the unwritten-fields mode (unwritten.go); nil in seam-names.
	uw *uwState
}

// seamCtx is what one template or expression is evaluated against.
type seamCtx struct {
	a      *seamAnalysis
	iface  string // the reading and writing interface ("" for a fixture)
	writer string
	input  *nt
	vars   *nt
	state  *nt
	row    *nt
	route  bool // input is a route's input (headers normalized)
	locals map[string]*nt
	// nocheck: an inlined store interface's own expressions (unwritten-fields)
	nocheck bool
}

func (a *seamAnalysis) parse(src string) celast.Expr {
	if e, ok := a.asts[src]; ok {
		return e
	}
	var e celast.Expr
	if p, iss := a.env.Parse(src); iss == nil || iss.Err() == nil {
		e = p.NativeRep().Expr()
	}
	a.asts[src] = e
	return e
}

// node returns a persistent root.
func (a *seamAnalysis) node(m map[string]*nt, k string) *nt {
	n := m[k]
	if n == nil {
		n = newNT()
		n.persist = true
		m[k] = n
	}
	return n
}

func (a *seamAnalysis) grow(dst, src *nt) {
	a.union(dst, src, 0, false)
}

// tmpl evaluates a template: a literal map's keys are written by the
// context's writer; an "=cel" string is evaluated.
func (c *seamCtx) tmpl(v any) *nt {
	switch t := v.(type) {
	case string:
		if e, ok := strings.CutPrefix(t, "="); ok {
			v := c.cel(e)
			if v == nil && c.a.uw != nil {
				return openLeaf
			}
			return v
		}
		if c.a.uw != nil {
			return c.a.uw.lit(t)
		}
	case map[string]any:
		n := newNT()
		for k, x := range t {
			v := c.tmpl(x)
			if v == nil {
				v = newNT()
			}
			n.set(k, v, c.writer)
		}
		return n
	case []any:
		var el *nt
		for _, x := range t {
			el = seamMerge(el, c.tmpl(x), 0)
		}
		n := newNT()
		n.elem = el
		if n.elem == nil {
			n.elem = newNT()
		}
		return n
	}
	return nil
}

func (c *seamCtx) cel(src string) *nt {
	e := c.a.parse(strings.TrimSpace(src))
	if e == nil {
		return nil
	}
	return c.eval(e)
}

// exprPath renders a member chain for a report: input.principal.auth.
func exprPath(e celast.Expr) string {
	switch e.Kind() {
	case celast.IdentKind:
		return e.AsIdent()
	case celast.SelectKind:
		return exprPath(e.AsSelect().Operand()) + "." + e.AsSelect().FieldName()
	case celast.CallKind:
		if c := e.AsCall(); c.FunctionName() == "_[_]" && len(c.Args()) == 2 {
			return exprPath(c.Args()[0]) + "[...]"
		}
	}
	return "(...)"
}

// selects checks a member selection: field read from the shape op.
func (c *seamCtx) selects(op *nt, operand celast.Expr, field string) {
	if c.a.uw != nil {
		c.unwrittenSelect(op, operand, field)
		return
	}
	if !c.a.check || op == nil || len(op.kids) == 0 || headerAlias(field) {
		return
	}
	if _, ok := op.kids[field]; ok {
		return
	}
	if operand.Kind() == celast.IdentKind {
		switch operand.AsIdent() {
		case "vars":
			return // a behavior's own variables are not a seam
		case "input":
			if c.route {
				return
			}
		}
	}
	n := seamNorm(field)
	for _, k := range sortedKeys(op.kids) {
		if k != field && seamNorm(k) == n && !headerAlias(k) {
			c.a.report(seamFinding{Read: field, Write: k, Reader: c.iface, Writer: op.kids[k].src, At: exprPath(operand)})
		}
	}
}

func (a *seamAnalysis) report(f seamFinding) {
	if f.Reader == "" {
		return
	}
	k := strings.Join([]string{f.Reader, f.Read, f.Write, f.Writer, f.At}, "\x00")
	if a.found[k] == nil {
		a.found[k] = &f
	}
}

func (c *seamCtx) eval(e celast.Expr) *nt {
	switch e.Kind() {
	case celast.IdentKind:
		name := e.AsIdent()
		if n, ok := c.locals[name]; ok {
			return n
		}
		switch name {
		case "input":
			return c.input
		case "vars":
			return c.vars
		case "state":
			return c.state
		case "row":
			return c.row
		}
	case celast.SelectKind:
		s := e.AsSelect()
		op := c.eval(s.Operand())
		c.selects(op, s.Operand(), s.FieldName())
		if op == nil || s.IsTestOnly() {
			return nil
		}
		if op.open {
			return openWrap(op.kid(s.FieldName()))
		}
		return op.kid(s.FieldName())
	case celast.LiteralKind:
		if s, ok := e.AsLiteral().(types.String); ok && c.a.uw != nil {
			return c.a.uw.lit(string(s))
		}
	case celast.ListKind:
		n := newNT()
		for _, x := range e.AsList().Elements() {
			n.elem = seamMerge(n.elem, c.eval(x), 0)
		}
		return n
	case celast.MapKind:
		n := newNT()
		for _, en := range e.AsMap().Entries() {
			if en.Kind() != celast.MapEntryKind {
				continue
			}
			me := en.AsMapEntry()
			v := c.eval(me.Value())
			if v == nil {
				v = newNT()
			}
			if k := me.Key(); k.Kind() == celast.LiteralKind {
				if s, ok := k.AsLiteral().(types.String); ok {
					n.set(string(s), v, c.writer)
					continue
				}
			}
			c.eval(me.Key())
			n.elem = seamMerge(n.elem, v, 0)
		}
		return n
	case celast.ComprehensionKind:
		cp := e.AsComprehension()
		item := dynIndex(c.eval(cp.IterRange()))
		saved := c.locals
		c.locals = map[string]*nt{}
		for k, v := range saved {
			c.locals[k] = v
		}
		if cp.HasIterVar2() {
			c.locals[cp.IterVar()] = nil
			c.locals[cp.IterVar2()] = item
		} else {
			c.locals[cp.IterVar()] = item
		}
		accu := c.eval(cp.AccuInit())
		c.locals[cp.AccuVar()] = accu
		c.eval(cp.LoopCondition())
		step := c.eval(cp.LoopStep())
		accu = seamMerge(accu, step, 0)
		if c.a.uw != nil && isUnknown(cp.LoopStep(), step) {
			accu = openWrap(accu) // a step the inference can't follow (@mapInsert, a bool)
		}
		c.locals[cp.AccuVar()] = accu
		res := c.eval(cp.Result())
		c.locals = saved
		return res
	case celast.CallKind:
		call := e.AsCall()
		args := call.Args()
		var vals []*nt
		if call.IsMemberFunction() {
			vals = append(vals, c.eval(call.Target()))
		}
		fn := call.FunctionName()
		if c.a.uw != nil && (fn == "_?_:_" || fn == "_||_") {
			if ks := optionalIdiom(fn, args); len(ks) > 0 {
				for _, k := range ks {
					c.a.uw.skip[k]++
				}
				defer func() {
					for _, k := range ks {
						c.a.uw.skip[k]--
					}
				}()
			}
		}
		if fn == "_[_]" && len(args) == 2 {
			op := c.eval(args[0])
			if args[1].Kind() == celast.LiteralKind {
				if s, ok := args[1].AsLiteral().(types.String); ok {
					c.selects(op, args[0], string(s))
					if op == nil {
						return nil
					}
					n := op.kid(string(s))
					if n == nil {
						n = op.elem
					}
					if op.open {
						return openWrap(n)
					}
					return n
				}
			}
			c.eval(args[1])
			return dynIndex(op)
		}
		for _, x := range args {
			vals = append(vals, c.eval(x))
		}
		if c.a.uw != nil {
			if v, ok := c.uwCall(fn, args, vals); ok {
				return v
			}
		}
		switch fn {
		case "_?_:_":
			if len(vals) == 3 {
				return seamMerge(vals[1], vals[2], 0)
			}
		case "merge", "_+_":
			var out *nt
			for _, v := range vals {
				out = seamMerge(out, v, 0)
			}
			return out
		case "omit", "dyn", "orValue", "value":
			if len(vals) > 0 {
				return vals[0]
			}
		case "first", "last":
			if len(vals) > 0 && vals[0] != nil {
				return vals[0].elem
			}
		}
	}
	return nil
}

// shapeNT turns a schema shape into the names it declares.
func shapeNT(s *shape, writer string, depth int) *nt {
	if s == nil || depth > seamMaxDepth {
		return nil
	}
	n := newNT()
	for norm, decl := range s.Names {
		k := shapeNT(s.Props[norm], writer, depth+1)
		if k == nil {
			k = newNT()
		}
		n.set(decl, k, writer)
	}
	if s.Items != nil {
		n.elem = shapeNT(s.Items, writer, depth+1)
	}
	return n
}

// callKeys checks a call's literal input keys against the callee's request
// schema properties, recursing where both sides are objects.
func (a *seamAnalysis) callKeys(caller, callee string, in any, s *shape, depth int) {
	m, ok := in.(map[string]any)
	if !ok || s == nil || len(s.Names) == 0 || depth > seamMaxDepth {
		return
	}
	for _, k := range sortedKeys(m) {
		if headerAlias(k) {
			continue
		}
		exact := false
		for _, d := range s.Names {
			if d == k {
				exact = true
			}
		}
		if exact {
			a.callKeys(caller, callee, m[k], s.Props[normName(k)], depth+1)
			continue
		}
		for _, norm := range sortedKeys(s.Names) {
			if d := s.Names[norm]; seamNorm(d) == seamNorm(k) {
				a.report(seamFinding{Read: d, Write: k, Reader: callee, Writer: caller, At: "call " + callee, Call: true})
			}
		}
	}
}

func (a *seamAnalysis) reqShape(id string) *shape {
	if s, ok := a.reqs[id]; ok {
		return s
	}
	var s *shape
	if i := a.x.Interfaces[id]; i != nil && i.Request != nil {
		s = buildShape(asJSON(i.Request), a.resolve, 0)
	}
	a.reqs[id] = s
	return s
}

// send delivers a step's input to a callee: it grows the callee's input
// shape and, on the check pass, compares literal keys to its schema.
func (a *seamAnalysis) send(c *seamCtx, callee string, input any) *nt {
	v := c.tmpl(input)
	if a.x.Interfaces[callee] == nil {
		return v
	}
	if v != nil {
		a.grow(a.node(a.in, callee), v)
	}
	if a.check && !a.routes[callee] {
		a.callKeys(c.iface, callee, input, a.reqShape(callee), 0)
	}
	return v
}

// setPath returns the node at segs under root (its item shape when dyn),
// adding what is missing.
func (a *seamAnalysis) setPath(root *nt, segs []string, writer string, dyn bool) *nt {
	n := root
	for _, s := range segs {
		n = a.child(n, s, writer)
	}
	if dyn {
		n = a.elemOf(n)
	}
	return n
}

// callResult is the shape of vars.<as> after a call: {ok, value, error, ...}.
func callResult(value *nt) *nt { return callResultKeys(value, nil) }

// callResultKeys is callResult with extra fixed keys.
func callResultKeys(value *nt, extra []string) *nt {
	n := newNT()
	for _, k := range append([]string{"ok", "error", "attempts", "duration_ms", "target", "route"}, extra...) {
		n.set(k, newNT(), "the call result")
	}
	if value == nil {
		value = newNT()
	}
	n.set("value", value, "the call result")
	return n
}

func (a *seamAnalysis) behavior(i *model.Interface, c *seamCtx) {
	comp := i.Component
	for _, sp := range behaviorPaths(i) {
		s := sp.Step
		for _, src := range []string{s.If, s.When, s.Choice} {
			if src != "" {
				c.cel(src)
			}
		}
		if s.Set != nil {
			for _, k := range sortedKeys(s.Set) {
				v := c.tmpl(asJSON(s.Set[k]))
				path, dyn := k, false
				if e, ok := strings.CutPrefix(k, "="); ok {
					c.cel(e)
					pfx, _ := literalPrefix(k)
					path, dyn = strings.TrimSuffix(pfx, "."), true
					if !strings.HasSuffix(pfx, ".") {
						if j := strings.LastIndex(pfx, "."); j >= 0 {
							path = pfx[:j]
						} else {
							path = ""
						}
					}
				}
				segs := strings.Split(path, ".")
				if v == nil || len(segs) == 0 {
					continue
				}
				switch segs[0] {
				case "vars":
					if len(segs) > 1 || dyn {
						a.grow(a.setPath(c.vars, segs[1:], c.writer, dyn), v)
					}
				case "state":
					if len(segs) > 1 || dyn {
						a.grow(a.setPath(c.state, segs[1:], c.writer, dyn), v)
					}
				}
			}
		}
		var targets []string
		if s.Call != "" {
			if strings.HasPrefix(s.Call, "=") {
				c.cel(strings.TrimPrefix(s.Call, "="))
				targets = s.Targets
			} else {
				targets = []string{s.Call}
			}
		}
		var input any
		if len(s.Input) > 0 {
			input = asJSON(s.Input)
		}
		for _, t := range targets {
			if a.uw != nil {
				if st := storeOnly(a.x.Interfaces[t]); st != nil {
					v := a.storeInline(c, a.x.Interfaces[t], st, input)
					if s.As != "" {
						a.grow(a.child(c.vars, s.As, c.writer), a.callRes(v))
					}
					continue
				}
			}
			a.send(c, t, input)
			if s.As != "" {
				a.grow(a.child(c.vars, s.As, c.writer), a.callRes(a.out[t]))
			}
		}
		if len(targets) == 0 && input != nil && s.Emit == "" && s.Publish == "" {
			c.tmpl(input) // a route call's or a put's input: checked as reads only
		}
		if s.Emit != "" && !strings.HasPrefix(s.Emit, "=") {
			a.send(c, s.Emit, input)
		}
		if s.Publish != "" && !strings.HasPrefix(s.Publish, "=") {
			for _, t := range a.x.Subscribers[s.Publish] {
				a.send(c, t, input)
			}
		}
		if s.Foreach != nil || s.Parallel != nil {
			src := s.Foreach
			if src == nil {
				src = s.Parallel
			}
			item := dynIndex(c.tmpl(asJSON(src)))
			as := s.As
			if as == "" {
				as = "item"
			}
			if item != nil {
				a.grow(a.child(c.vars, as, c.writer), item)
			}
		}
		if len(s.Return) > 0 {
			if v := c.tmpl(asJSON(s.Return)); v != nil {
				a.grow(a.node(a.out, i.ID), v)
			}
		}
		if len(s.Fail) > 0 {
			c.tmpl(asJSON(s.Fail))
		}
		if len(s.Yield) > 0 {
			c.tmpl(asJSON(s.Yield))
		}
		if len(s.Transact) > 0 {
			var vals *nt
			for k := range s.Transact {
				st := &s.Transact[k]
				rows := a.child(a.node(a.state, comp), st.Table, c.writer)
				a.storeSpec(c, st, rows)
				vals = seamMerge(vals, a.rowsOf(rows), 0)
			}
			if s.As != "" {
				l := newNT()
				l.elem = vals
				a.grow(a.child(c.vars, s.As, c.writer), a.callRes(l))
			}
		}
		if a.uw != nil {
			a.openUnmodeled(c, s, len(targets) > 0 || len(s.Transact) > 0 || s.Foreach != nil || s.Parallel != nil)
		}
	}
}

// rowsOf is dynIndex for a table's persistent node: a persistent view that
// unions every row's names, kept up to date as rows are added.
func (a *seamAnalysis) rowsOf(rows *nt) *nt {
	v := a.views[rows]
	if v == nil {
		v = newNT()
		v.persist = true
		a.views[rows] = v
	}
	a.union(v, rows.elem, 0, false)
	for _, k := range sortedKeys(rows.kids) {
		a.union(v, rows.kids[k].n, 0, false)
	}
	return v
}

// storeSpec evaluates one store operation against its table's rows and
// returns what it gives back.
func (a *seamAnalysis) storeSpec(c *seamCtx, st *model.StoreSpec, rows *nt) *nt {
	if a.uw != nil {
		return a.storeUW(c, st, rows, nil)
	}
	rc := *c
	rc.row = a.rowsOf(rows)
	if st.Key != nil {
		rc.tmpl(asJSON(st.Key))
	}
	for _, src := range []string{st.Where, st.If} {
		if src != "" {
			rc.cel(src)
		}
	}
	switch st.Op {
	case "put", "update", "incr":
		if v := c.tmpl(asJSON(st.Value)); v != nil {
			a.grow(a.elemOf(rows), v)
		}
		return a.rowsOf(rows)
	case "get", "delete":
		out := a.rowsOf(rows)
		if st.Default != nil {
			out = seamMerge(out, c.tmpl(asJSON(st.Default)), 0)
		}
		return out
	case "query":
		l := newNT()
		l.elem = a.rowsOf(rows)
		return l
	}
	return nil
}

func newSeamEnv() *cel.Env {
	env, err := cel.NewEnv(ext.Strings(), ext.Math(), ext.Lists(), ext.Encoders(), ext.TwoVarComprehensions())
	if err != nil {
		panic(err)
	}
	return env
}

// lintSeamNames runs the analysis to a fixed point, then checks every read.
func lintSeamNames(doc *model.Document, origins map[string]string) *seamReport {
	a := runSeamAnalysis(doc, nil)
	return a.seamReport(origins)
}

// runSeamAnalysis infers the shapes to a fixed point and runs the check
// pass. With uw it is the unwritten-fields analysis: no schema is a
// writer, stores are partitioned by key pattern and unknown values are
// open (unwritten.go).
func runSeamAnalysis(doc *model.Document, uw *uwState) *seamAnalysis {
	x := indexed(doc)
	a := &seamAnalysis{uw: uw,
		x: x, env: newSeamEnv(), asts: map[string]celast.Expr{},
		in: map[string]*nt{}, out: map[string]*nt{}, vars: map[string]*nt{}, state: map[string]*nt{},
		routes: map[string]bool{}, reqs: map[string]*shape{}, found: map[string]*seamFinding{},
		sync: map[[2]*nt]uint64{}, views: map[*nt]*nt{},
		resolve: func(r string) (any, bool) { s, ok := x.ResolveSchema(r); return s, ok },
	}
	ids := sortedIfaces(x)
	for _, id := range ids {
		i := x.Interfaces[id]
		if _, _, ok := ifaceRoute(i); ok {
			a.routes[id] = true
		} else if c := x.Components[i.Component]; c != nil && c.Router != nil {
			a.routes[id] = true
		}
		// The declared contract: request and response schema properties.
		if uw != nil {
			continue // a schema declares a field; it doesn't write one
		}
		if i.Request != nil {
			a.grow(a.node(a.in, id), shapeNT(buildShape(asJSON(i.Request), a.resolve, 0), "schema of "+id, 0))
		}
		if i.Response != nil {
			a.grow(a.node(a.out, id), shapeNT(buildShape(asJSON(i.Response), a.resolve, 0), "schema of "+id, 0))
		}
	}
	// Seeds: fixture rows and initial state.
	for _, f := range doc.Fixtures {
		c := &seamCtx{a: a, writer: "fixture " + f.ID}
		for _, comp := range sortedKeys(f.State) {
			a.grow(a.node(a.state, baseComp(comp)), c.tmpl(asJSON(f.State[comp])))
		}
	}
	for _, comp := range doc.Components {
		if comp.State != nil && comp.State.Initial != nil {
			c := &seamCtx{a: a, writer: "initial state of " + comp.ID}
			a.grow(a.node(a.state, comp.ID), c.tmpl(asJSON(comp.State.Initial)))
		}
	}
	if uw != nil {
		uw.prepare(a, doc)
	}
	pass := func() {
		for _, id := range ids {
			i := x.Interfaces[id]
			c := &seamCtx{a: a, iface: id, writer: id, input: a.node(a.in, id),
				vars: a.node(a.vars, id), state: a.node(a.state, i.Component), route: a.routes[id]}
			if st := storeOnly(i); st != nil {
				if uw != nil {
					continue // inlined at each call site
				}
				rows := a.child(c.state, st.Table, id)
				if v := a.storeSpec(c, st, rows); v != nil {
					a.grow(a.node(a.out, id), v)
				}
				continue
			}
			if len(i.Behavior) > 0 {
				a.behavior(i, c)
			}
		}
	}
	for n := 0; n < 24; n++ {
		a.changed = false
		pass()
		if !a.changed {
			break
		}
	}
	a.check = true
	pass()
	return a
}

// seamReport collects the seam-names findings.
func (a *seamAnalysis) seamReport(origins map[string]string) *seamReport {
	r := &seamReport{Frags: map[string]string{}}
	frag := func(who string) string { return writerFrag(origins, who) }
	for _, f := range a.found {
		r.Findings = append(r.Findings, *f)
		r.Frags[f.Reader] = frag(f.Reader)
		r.Frags[f.Writer] = frag(f.Writer)
	}
	sort.Slice(r.Findings, func(i, j int) bool {
		p, q := r.Findings[i], r.Findings[j]
		if p.Reader != q.Reader {
			return p.Reader < q.Reader
		}
		if p.Read != q.Read {
			return p.Read < q.Read
		}
		if p.Write != q.Write {
			return p.Write < q.Write
		}
		return p.Writer+p.At < q.Writer+q.At
	})
	return r
}

// writerFrag is the fragment of a reader or writer: an interface id,
// "fixture <id>", "initial state of <c>" or "schema of <iface>".
func writerFrag(origins map[string]string, who string) string {
	switch {
	case strings.HasPrefix(who, "fixture "):
		return origins[model.KindFixture+"/"+strings.TrimPrefix(who, "fixture ")]
	case strings.HasPrefix(who, "initial state of "):
		return origins[model.KindComponent+"/"+strings.TrimPrefix(who, "initial state of ")]
	case strings.HasPrefix(who, "schema of "):
		return origins[model.KindInterface+"/"+strings.TrimPrefix(who, "schema of ")]
	}
	return origins[model.KindInterface+"/"+who]
}

// print lists the findings (unless quiet), the count per reader fragment
// and the total, and reports whether the total is above max (max >= 0).
func (r *seamReport) print(w io.Writer, max int, quiet bool) bool {
	per := map[string]int{}
	for _, f := range r.Findings {
		per[first(r.Frags[f.Reader], "(no fragment)")]++
		if quiet {
			continue
		}
		wf := first(r.Frags[f.Writer], "-")
		if f.Call {
			fmt.Fprintf(w, "! seam-names %s vs %s (%s): %s (%s) calls %s with key %s; its request schema says %s\n",
				f.Write, f.Read, first(r.Frags[f.Reader], "-"), f.Writer, wf, f.Reader, f.Write, f.Read)
			continue
		}
		fmt.Fprintf(w, "! seam-names %s vs %s (%s): %s reads %s.%s; %s (%s) writes %s\n",
			f.Read, f.Write, first(r.Frags[f.Reader], "-"), f.Reader, f.At, f.Read, first(f.Writer, "?"), wf, f.Write)
	}
	for _, fr := range sortedKeys(per) {
		fmt.Fprintf(w, "  seam-names in %s: %d\n", fr, per[fr])
	}
	over := max >= 0 && len(r.Findings) > max
	gate := ""
	if max >= 0 {
		mark := "within"
		if over {
			mark = "above"
		}
		gate = fmt.Sprintf("; --max-seam-names %d: %s", max, mark)
	}
	mark := ""
	if over {
		mark = "✗ "
	}
	fmt.Fprintf(w, "%sseam-names lint: %d fields read under one spelling and written under another%s\n", mark, len(r.Findings), gate)
	return over
}

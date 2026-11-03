package main

// Go entry points registered indirectly: routes through local helpers and
// tables, named passes behind a shared loop helper, cobra trees hung from a
// data table, argv-selected daemon modes, accept-loop listeners, message
// consumers, flag-less service mains, Nomad job builders and Temporal
// schedules. See goScan.prepare for the helper analysis these share.

import (
	"go/ast"
	"go/token"
	"path/filepath"
	"regexp"
	"strings"
)

// ---------------------------------------------------------------- constant evaluation

// gbind is a composite literal value an identifier stands for: a package
// var, a table row bound to a range variable, or a method receiver.
type gbind struct {
	lit *ast.CompositeLit
	typ string
	pkg *goPkg
}

// kvExpr returns the value of key in a keyed composite literal.
func kvExpr(c *ast.CompositeLit, key string) ast.Expr {
	for _, el := range c.Elts {
		if kv, ok := el.(*ast.KeyValueExpr); ok {
			if k, ok := kv.Key.(*ast.Ident); ok && k.Name == key {
				return kv.Value
			}
		}
	}
	return nil
}

func kvPos(c *ast.CompositeLit, key string) token.Pos {
	for _, el := range c.Elts {
		if kv, ok := el.(*ast.KeyValueExpr); ok {
			if k, ok := kv.Key.(*ast.Ident); ok && k.Name == key {
				return kv.Pos()
			}
		}
	}
	return c.Pos()
}

// evalStr folds a string expression: literals, concatenation, package
// constants and vars (also of imported scanned packages), fields of
// composite-literal vars or bound table rows, and argument-less methods
// whose body is a single return of such an expression.
func (g *goScan) evalStr(p *goPkg, e ast.Expr, env map[string]any, depth int) (string, bool) {
	if depth > 10 || e == nil {
		return "", false
	}
	switch x := e.(type) {
	case *ast.BasicLit:
		return stringLit(x)
	case *ast.ParenExpr:
		return g.evalStr(p, x.X, env, depth+1)
	case *ast.BinaryExpr:
		if x.Op != token.ADD {
			return "", false
		}
		a, ok1 := g.evalStr(p, x.X, env, depth+1)
		b, ok2 := g.evalStr(p, x.Y, env, depth+1)
		return a + b, ok1 && ok2
	case *ast.Ident:
		if v, ok := env[x.Name]; ok {
			s, ok := v.(string)
			return s, ok
		}
		if v := p.vals[x.Name]; v != nil {
			return g.evalStr(p, v, nil, depth+1)
		}
	case *ast.SelectorExpr:
		if id, ok := x.X.(*ast.Ident); ok && env[id.Name] == nil && p.vals[id.Name] == nil {
			if q := g.importedPkg(p, id.Name); q != nil {
				return g.evalStr(q, q.vals[x.Sel.Name], nil, depth+1)
			}
		}
		if b, ok := g.evalLit(p, x.X, env, depth+1); ok {
			return g.evalStr(b.pkg, kvExpr(b.lit, x.Sel.Name), nil, depth+1)
		}
	case *ast.CallExpr:
		sel, ok := x.Fun.(*ast.SelectorExpr)
		if !ok || len(x.Args) != 0 {
			return "", false
		}
		b, ok := g.evalLit(p, sel.X, env, depth+1)
		if !ok {
			return "", false
		}
		owner := g.typeOwner(b)
		refs := owner.funcs[b.typ+"."+sel.Sel.Name]
		if len(refs) != 1 || refs[0].decl.Body == nil || len(refs[0].decl.Body.List) != 1 {
			return "", false
		}
		d := refs[0].decl
		r, ok := d.Body.List[0].(*ast.ReturnStmt)
		if !ok || len(r.Results) != 1 {
			return "", false
		}
		env2 := map[string]any{}
		if names := d.Recv.List[0].Names; len(names) == 1 {
			env2[names[0].Name] = b
		}
		return g.evalStr(owner, r.Results[0], env2, depth+1)
	}
	return "", false
}

// evalLit finds the composite literal an expression denotes.
func (g *goScan) evalLit(p *goPkg, e ast.Expr, env map[string]any, depth int) (gbind, bool) {
	if depth > 10 || e == nil {
		return gbind{}, false
	}
	switch x := e.(type) {
	case *ast.ParenExpr:
		return g.evalLit(p, x.X, env, depth+1)
	case *ast.UnaryExpr:
		if x.Op == token.AND {
			return g.evalLit(p, x.X, env, depth+1)
		}
	case *ast.CompositeLit:
		if x.Type != nil {
			return gbind{x, typeName(x.Type), p}, true
		}
	case *ast.Ident:
		if v, ok := env[x.Name]; ok {
			b, ok := v.(gbind)
			return b, ok
		}
		if v := p.vals[x.Name]; v != nil {
			return g.evalLit(p, v, nil, depth+1)
		}
	case *ast.SelectorExpr:
		if id, ok := x.X.(*ast.Ident); ok && env[id.Name] == nil {
			if q := g.importedPkg(p, id.Name); q != nil {
				return g.evalLit(q, q.vals[x.Sel.Name], nil, depth+1)
			}
		}
	}
	return gbind{}, false
}

// evalSlice expands a package-level slice or array literal (a route or
// command table) into its rows.
func (g *goScan) evalSlice(p *goPkg, e ast.Expr) ([]gbind, bool) {
	owner := p
	var v ast.Expr
	switch x := e.(type) {
	case *ast.Ident:
		v = p.vals[x.Name]
	case *ast.SelectorExpr:
		if id, ok := x.X.(*ast.Ident); ok {
			if q := g.importedPkg(p, id.Name); q != nil {
				owner, v = q, q.vals[x.Sel.Name]
			}
		}
	}
	lit, ok := v.(*ast.CompositeLit)
	if !ok {
		return nil, false
	}
	at, ok := lit.Type.(*ast.ArrayType)
	if !ok {
		return nil, false
	}
	elt := typeName(at.Elt)
	var out []gbind
	for _, el := range lit.Elts {
		if kv, ok := el.(*ast.KeyValueExpr); ok {
			el = kv.Value
		}
		if u, ok := el.(*ast.UnaryExpr); ok && u.Op == token.AND {
			el = u.X
		}
		c, ok := el.(*ast.CompositeLit)
		if !ok {
			if b, ok := g.evalLit(owner, el, nil, 1); ok {
				out = append(out, b)
			}
			continue
		}
		t := elt
		if c.Type != nil {
			t = typeName(c.Type)
		}
		out = append(out, gbind{c, t, owner})
	}
	return out, len(out) > 0 && len(out) <= 200
}

// typeOwner is the package declaring a bound literal's type.
func (g *goScan) typeOwner(b gbind) *goPkg {
	if b.pkg.types[b.typ] {
		return b.pkg
	}
	var found *goPkg
	for _, q := range g.pkgs {
		if q.types[b.typ] {
			if found != nil {
				return b.pkg
			}
			found = q
		}
	}
	if found == nil {
		return b.pkg
	}
	return found
}

// render folds what it can of a string expression and shows the rest as
// {expr}.
func (g *goScan) render(p *goPkg, e ast.Expr, env map[string]any) string {
	if s, ok := g.evalStr(p, e, env, 0); ok {
		return s
	}
	if b, ok := e.(*ast.BinaryExpr); ok && b.Op == token.ADD {
		return g.render(p, b.X, env) + g.render(p, b.Y, env)
	}
	return "{" + exprString(e) + "}"
}

// splitPattern turns "GET /p" or "/p" into a route name.
func splitPattern(pat string) string {
	method, path := "ANY", pat
	if i := strings.Index(pat, " "); i > 0 && isUpper(pat[:i]) {
		method, path = pat[:i], strings.TrimSpace(pat[i+1:])
	}
	return method + " " + path
}

// ---------------------------------------------------------------- scopes

// funcParams lists a function type's parameters in order.
func funcParams(t *ast.FuncType) []*ast.Field {
	var out []*ast.Field
	if t == nil || t.Params == nil {
		return nil
	}
	for _, fl := range t.Params.List {
		if len(fl.Names) == 0 {
			out = append(out, fl)
			continue
		}
		for range fl.Names {
			out = append(out, fl)
		}
	}
	return out
}

func paramNames(t *ast.FuncType) []string {
	var out []string
	if t == nil || t.Params == nil {
		return nil
	}
	for _, fl := range t.Params.List {
		if len(fl.Names) == 0 {
			out = append(out, "_")
			continue
		}
		for _, n := range fl.Names {
			out = append(out, n.Name)
		}
	}
	return out
}

// boundAt reports whether e mentions a parameter of a function (declaration
// or literal) enclosing pos, or a range variable of a loop around pos: the
// value is chosen by a caller or a table the scan could not expand.
func boundAt(fn *ast.FuncDecl, e ast.Expr, pos token.Pos) bool {
	if fn == nil || e == nil {
		return false
	}
	bound := map[string]bool{}
	for _, n := range paramNames(fn.Type) {
		bound[n] = true
	}
	if fn.Body != nil {
		ast.Inspect(fn.Body, func(n ast.Node) bool {
			if n == nil || pos < n.Pos() || pos >= n.End() {
				return false
			}
			switch x := n.(type) {
			case *ast.FuncLit:
				for _, p := range paramNames(x.Type) {
					bound[p] = true
				}
			case *ast.RangeStmt:
				for _, v := range []ast.Expr{x.Key, x.Value} {
					if id, ok := v.(*ast.Ident); ok {
						bound[id.Name] = true
					}
				}
			}
			return true
		})
	}
	found := false
	ast.Inspect(e, func(n ast.Node) bool {
		if id, ok := n.(*ast.Ident); ok && bound[id.Name] {
			found = true
		}
		if s, ok := n.(*ast.SelectorExpr); ok {
			ast.Inspect(s.X, func(m ast.Node) bool {
				if id, ok := m.(*ast.Ident); ok && bound[id.Name] {
					found = true
				}
				return true
			})
			return false
		}
		return !found
	})
	return found
}

// closures maps the local names of function literals assigned in fn
// (name := func(...) {...}) to the literals.
func (g *goScan) closures(fn *ast.FuncDecl) map[string]*ast.FuncLit {
	if fn == nil || fn.Body == nil {
		return nil
	}
	if m, ok := g.closureCache[fn]; ok {
		return m
	}
	m := map[string]*ast.FuncLit{}
	ast.Inspect(fn.Body, func(n ast.Node) bool {
		switch x := n.(type) {
		case *ast.AssignStmt:
			for i, l := range x.Lhs {
				if id, ok := l.(*ast.Ident); ok && i < len(x.Rhs) {
					if lit, ok := x.Rhs[i].(*ast.FuncLit); ok {
						m[id.Name] = lit
					}
				}
			}
		case *ast.ValueSpec:
			for i, id := range x.Names {
				if i < len(x.Values) {
					if lit, ok := x.Values[i].(*ast.FuncLit); ok {
						m[id.Name] = lit
					}
				}
			}
		}
		return true
	})
	g.closureCache[fn] = m
	return m
}

// callee resolves the function a call runs: a local closure, a package
// function, a function of an imported scanned package, or a method whose
// name is unique in the package or the repository.
func (g *goScan) callee(p *goPkg, fn *ast.FuncDecl, call *ast.CallExpr) (ast.Node, string) {
	switch x := call.Fun.(type) {
	case *ast.Ident:
		if lit := g.closures(fn)[x.Name]; lit != nil {
			return lit, x.Name
		}
		if refs := p.funcs[x.Name]; len(refs) == 1 && refs[0].decl.Recv == nil {
			return refs[0].decl, x.Name
		}
	case *ast.SelectorExpr:
		name := x.Sel.Name
		if id, ok := x.X.(*ast.Ident); ok {
			if _, imp := importOf(p, id.Name); imp {
				if q := g.importedPkg(p, id.Name); q != nil {
					if refs := q.funcs[name]; len(refs) == 1 && refs[0].decl.Recv == nil {
						return refs[0].decl, id.Name + "." + name
					}
				}
				return nil, ""
			}
		}
		var methods []funcRef
		for _, r := range p.funcs[name] {
			if r.decl.Recv != nil {
				methods = append(methods, r)
			}
		}
		if len(methods) == 1 {
			return methods[0].decl, qualName(methods[0].decl)
		}
		if len(methods) == 0 {
			if refs := g.methods[name]; len(refs) == 1 {
				return refs[0].decl, qualName(refs[0].decl)
			}
		}
	}
	return nil, ""
}

func importOf(p *goPkg, local string) (string, bool) {
	for _, f := range p.files {
		if ip, ok := f.imports[local]; ok {
			return ip, true
		}
	}
	return "", false
}

// ---------------------------------------------------------------- helper analysis

type routeHelper struct {
	idx  int // the pattern parameter
	name string
}

type loopHelper struct {
	nameIdx, fnIdx int
	name           string
	decl           *ast.FuncDecl
}

// unit is a function body the helper analysis looks at: a declaration or a
// closure assigned inside one.
type unit struct {
	node ast.Node
	typ  *ast.FuncType
	body *ast.BlockStmt
	decl *ast.FuncDecl // the enclosing declaration
	name string
}

func (g *goScan) units(p *goPkg) []unit {
	var out []unit
	for _, f := range p.files {
		for _, d := range f.ast.Decls {
			fd, ok := d.(*ast.FuncDecl)
			if !ok || fd.Body == nil {
				continue
			}
			out = append(out, unit{fd, fd.Type, fd.Body, fd, qualName(fd)})
			for name, lit := range g.closures(fd) {
				out = append(out, unit{lit, lit.Type, lit.Body, fd, name})
			}
		}
	}
	return out
}

// inspectOwn walks a body without entering nested function literals.
func inspectOwn(body ast.Node, fn func(ast.Node) bool) {
	ast.Inspect(body, func(n ast.Node) bool {
		if _, ok := n.(*ast.FuncLit); ok && n != body {
			return false
		}
		return fn(n)
	})
}

// prepare finds, repository-wide, the route helpers (functions passing a
// string parameter on as a ServeMux pattern, directly or through another
// helper) and loop helpers (functions running a func parameter on every
// tick of an endless loop, directly or through another helper).
func (g *goScan) prepare() {
	g.routeHelpers = map[ast.Node]routeHelper{}
	g.loopHelpers = map[ast.Node]loopHelper{}
	var all []struct {
		p *goPkg
		u unit
	}
	for _, p := range g.pkgs {
		for _, u := range g.units(p) {
			all = append(all, struct {
				p *goPkg
				u unit
			}{p, u})
		}
	}
	for round := 0; round < 6; round++ {
		changed := false
		for _, a := range all {
			if _, done := g.routeHelpers[a.u.node]; !done {
				if idx, ok := g.routeHelperParam(a.p, a.u); ok {
					g.routeHelpers[a.u.node] = routeHelper{idx, a.u.name}
					changed = true
				}
			}
			if _, done := g.loopHelpers[a.u.node]; !done {
				if lh, ok := g.loopHelperParams(a.p, a.u); ok {
					lh.name = a.u.name
					g.loopHelpers[a.u.node] = lh
					changed = true
				}
			}
		}
		if !changed {
			break
		}
	}
}

func (g *goScan) routeHelperParam(p *goPkg, u unit) (int, bool) {
	strParams := map[string]int{}
	for i, fl := range funcParams(u.typ) {
		if id, ok := fl.Type.(*ast.Ident); ok && id.Name == "string" {
			strParams[paramNames(u.typ)[i]] = i
		}
	}
	if len(strParams) == 0 {
		return 0, false
	}
	idx, found := -1, false
	inspectOwn(u.body, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok || found {
			return !found
		}
		argParam := func(i int) {
			if i < len(call.Args) {
				if id, ok := call.Args[i].(*ast.Ident); ok {
					if k, ok := strParams[id.Name]; ok {
						idx, found = k, true
					}
				}
			}
		}
		if sel, ok := call.Fun.(*ast.SelectorExpr); ok && (sel.Sel.Name == "HandleFunc" || sel.Sel.Name == "Handle") && len(call.Args) == 2 {
			argParam(0)
			return true
		}
		if t, _ := g.callee(p, u.decl, call); t != nil && t != u.node {
			if h, ok := g.routeHelpers[t]; ok {
				argParam(h.idx)
			}
		}
		return true
	})
	return idx, found
}

func noResults(t ast.Expr) bool {
	ft, ok := t.(*ast.FuncType)
	return ok && (ft.Results == nil || len(ft.Results.List) == 0)
}

// loopHelperParams recognizes a loop helper: a function whose endless,
// waiting loop runs a result-less func parameter as a statement (a retry
// helper, whose callback's result decides the loop, is not one), or which
// hands such a parameter to another loop helper.
func (g *goScan) loopHelperParams(p *goPkg, u unit) (loopHelper, bool) {
	params := funcParams(u.typ)
	names := paramNames(u.typ)
	fnParams, strParams := map[string]int{}, map[string]int{}
	firstStr := -1
	for i, fl := range params {
		if noResults(fl.Type) {
			fnParams[names[i]] = i
		}
		if id, ok := fl.Type.(*ast.Ident); ok && id.Name == "string" {
			strParams[names[i]] = i
			if firstStr < 0 {
				firstStr = i
			}
		}
	}
	if len(fnParams) == 0 {
		return loopHelper{}, false
	}
	usesParam := func(e ast.Expr) (int, bool) {
		if id, ok := e.(*ast.Ident); ok {
			k, ok := fnParams[id.Name]
			return k, ok
		}
		return 0, false
	}
	// Hand-off to a known loop helper.
	best := -1
	nameIdx := firstStr
	inspectOwn(u.body, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		if t, _ := g.callee(p, u.decl, call); t != nil && t != u.node {
			if h, ok := g.loopHelpers[t]; ok && h.fnIdx < len(call.Args) {
				if k, ok := usesParam(call.Args[h.fnIdx]); ok && k > best {
					best = k
					if h.nameIdx >= 0 && h.nameIdx < len(call.Args) {
						if id, ok := call.Args[h.nameIdx].(*ast.Ident); ok {
							if s, ok := strParams[id.Name]; ok {
								nameIdx = s
							}
						}
					}
				}
			}
		}
		return true
	})
	if best >= 0 {
		return loopHelper{nameIdx: nameIdx, fnIdx: best, decl: u.decl}, true
	}
	hasTicker := false
	inspectOwn(u.body, func(n ast.Node) bool {
		if c, ok := n.(*ast.CallExpr); ok {
			if s := exprString(c.Fun); s == "time.NewTicker" || s == "time.Tick" {
				hasTicker = true
			}
		}
		return true
	})
	inspectOwn(u.body, func(n ast.Node) bool {
		var body *ast.BlockStmt
		switch x := n.(type) {
		case *ast.ForStmt:
			if x.Cond != nil || !(loopSleeps(x.Body) || hasTicker) {
				return true
			}
			body = x.Body
		case *ast.RangeStmt:
			s := exprString(x.X)
			if !strings.HasSuffix(s, ".C") && !strings.HasPrefix(s, "time.Tick(") {
				return true
			}
			body = x.Body
		default:
			return true
		}
		ast.Inspect(body, func(m ast.Node) bool {
			st, ok := m.(*ast.ExprStmt)
			if !ok {
				return true
			}
			call, ok := st.X.(*ast.CallExpr)
			if !ok {
				return true
			}
			if k, ok := usesParam(call.Fun); ok && k > best {
				best = k
			}
			for _, a := range call.Args {
				if k, ok := usesParam(a); ok && k > best {
					best = k
				}
			}
			return true
		})
		return true
	})
	if best < 0 {
		return loopHelper{}, false
	}
	return loopHelper{nameIdx: nameIdx, fnIdx: best, decl: u.decl}, true
}

// helperCall reports the entries a call to a route or loop helper makes.
// handled is true when the call is a helper call (even one forwarding its
// caller's parameters, which makes no entry).
func (g *goScan) helperCall(p *goPkg, f *goFile, fn *ast.FuncDecl, call *ast.CallExpr, prefix string) (out []Entry, handled bool) {
	t, name := g.callee(p, fn, call)
	if t == nil {
		return nil, false
	}
	if h, ok := g.routeHelpers[t]; ok {
		if h.idx >= len(call.Args) {
			return nil, true
		}
		pat := g.render(p, call.Args[h.idx], nil)
		if !strings.Contains(pat, "/") {
			return nil, true
		}
		e := g.entry(KindHTTP, splitPattern(pat), f.rel, call.Pos(), "route-helper")
		if prefix != "" {
			e.Name = strings.Replace(e.Name, " ", " "+prefix, 1)
		}
		e.Detail = "registered through " + name
		return []Entry{e}, true
	}
	if h, ok := g.loopHelpers[t]; ok {
		if h.fnIdx >= len(call.Args) {
			return nil, true
		}
		// A helper forwarding its own func parameter is not a call site.
		if id, ok := call.Args[h.fnIdx].(*ast.Ident); ok && boundAt(fn, id, call.Pos()) {
			return nil, true
		}
		target := exprString(call.Args[h.fnIdx])
		if _, lit := call.Args[h.fnIdx].(*ast.FuncLit); lit {
			target = "func literal"
		}
		label := target
		if h.nameIdx >= 0 && h.nameIdx < len(call.Args) {
			if s, ok := g.evalStr(p, call.Args[h.nameIdx], nil, 0); ok && s != "" {
				label = s
			}
		}
		e := g.entry(KindCron, label, f.rel, call.Pos(), "loop-helper")
		e.Detail = name + " runs " + target
		g.usedLoops[h.decl] = true
		return []Entry{e}, true
	}
	return nil, false
}

// dropUsedLoops removes the ticker entry inside a loop helper that the scan
// found named call sites for: the passes, not the shared skeleton, are the
// entry points.
func (g *goScan) dropUsedLoops(in []Entry) []Entry {
	type span struct {
		file     string
		from, to int
	}
	var spans []span
	for d := range g.usedLoops {
		pos := g.fset.Position(d.Pos())
		rel := relOf(g, d)
		spans = append(spans, span{rel, pos.Line, g.line(d.End())})
	}
	var out []Entry
outer:
	for _, e := range in {
		if e.Kind == KindCron && (e.Via == "ticker" || e.Via == "sleep-loop") {
			for _, s := range spans {
				if e.File == s.file && e.Line >= s.from && e.Line <= s.to {
					continue outer
				}
			}
		}
		out = append(out, e)
	}
	return out
}

// ---------------------------------------------------------------- routes from tables

// rangeRoutes expands `for _, row := range Table { mux.Handle(... row.X ...) }`
// over a package-level table literal: one route per row, at the
// registration.
func (g *goScan) rangeRoutes(p *goPkg, f *goFile, x *ast.RangeStmt, prefix string, consumed map[*ast.CallExpr]bool) []Entry {
	v, ok := x.Value.(*ast.Ident)
	if !ok {
		return nil
	}
	rows, ok := g.evalSlice(p, x.X)
	if !ok {
		return nil
	}
	var out []Entry
	ast.Inspect(x.Body, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		sel, ok := call.Fun.(*ast.SelectorExpr)
		if !ok || (sel.Sel.Name != "HandleFunc" && sel.Sel.Name != "Handle") || len(call.Args) != 2 {
			return true
		}
		mentions := false
		ast.Inspect(call.Args[0], func(m ast.Node) bool {
			if id, ok := m.(*ast.Ident); ok && id.Name == v.Name {
				mentions = true
			}
			return true
		})
		if !mentions {
			return true
		}
		for _, row := range rows {
			pat, ok := g.evalStr(p, call.Args[0], map[string]any{v.Name: row}, 0)
			if !ok || !strings.Contains(pat, "/") {
				continue
			}
			consumed[call] = true
			e := g.entry(KindHTTP, splitPattern(pat), f.rel, call.Pos(), "route-table")
			if prefix != "" {
				e.Name = strings.Replace(e.Name, " ", " "+prefix, 1)
			}
			e.Detail = "one per row of " + exprString(x.X)
			out = append(out, e)
		}
		return true
	})
	return out
}

// ---------------------------------------------------------------- listeners and consumers

// acceptLoop reports whether a loop body accepts connections (ln.Accept()).
func acceptLoop(body *ast.BlockStmt) bool {
	found := false
	inspectOwn(body, func(n ast.Node) bool {
		if c, ok := n.(*ast.CallExpr); ok {
			if s, ok := c.Fun.(*ast.SelectorExpr); ok && s.Sel.Name == "Accept" && len(c.Args) <= 1 {
				found = true
			}
		}
		return !found
	})
	return found
}

var muxLike = regexp.MustCompile(`(?i)(mux|router)`)

// concreteHandler names the handler type an http.Server literal serves when
// it is a concrete handler (a proxy, a websocket front) rather than a router,
// whose routes are entries of their own.
func concreteHandler(x *ast.CompositeLit) string {
	h := kvExpr(x, "Handler")
	if h == nil {
		return ""
	}
	name := ""
	ast.Inspect(h, func(n ast.Node) bool {
		switch c := n.(type) {
		case *ast.FuncLit:
			return false
		case *ast.CompositeLit:
			if t := typeName(c.Type); t != "" && name == "" && !muxLike.MatchString(t) {
				name = exprString(c.Type)
			}
		}
		return name == ""
	})
	return name
}

// consumerMethods are the subscribe or receive calls of message brokers and
// event streams: Redis and NATS pub/sub, Redis streams, SQS, AMQP, Kafka
// readers, and event-stream clients that take a callback.
var consumerMethods = map[string]bool{
	"Subscribe": true, "PSubscribe": true, "SSubscribe": true, "QueueSubscribe": true, "ChanSubscribe": true,
	"ChanQueueSubscribe": true, "XReadGroup": true, "ReceiveMessage": true, "Consume": true,
	"ConsumeMessages": true, "StreamEvents": true, "ReadMessage": true, "FetchMessage": true,
}

func hasLoop(fn *ast.FuncDecl) bool {
	if fn == nil || fn.Body == nil {
		return false
	}
	found := false
	ast.Inspect(fn.Body, func(n ast.Node) bool {
		switch n.(type) {
		case *ast.ForStmt, *ast.RangeStmt:
			found = true
		}
		return !found
	})
	return found
}

// ---------------------------------------------------------------- packages

var nomadBuilder = regexp.MustCompile(`^(Build|New|Make|Render|Gen|Generate)\w*Job(Spec)?$`)

const (
	nomadAPI     = "github.com/hashicorp/nomad/api"
	temporalCli  = "go.temporal.io/sdk/client"
	lambdaGo     = "github.com/aws/aws-lambda-go/lambda"
	nomadPlugins = "github.com/hashicorp/nomad/plugins"
)

// pkgEntries finds the per-package entries: Nomad job builders, flag-less
// service mains and command tables.
func (g *goScan) pkgEntries(p *goPkg) []Entry {
	var out []Entry
	taskGroups := false
	cli, longRunning := false, false
	var mainFn funcRef
	var nomadCands []funcRef
	for _, f := range p.files {
		for _, ip := range f.imports {
			if ip == cobraPkg || strings.HasPrefix(ip, "github.com/urfave/cli") || strings.Contains(ip, "kingpin") {
				cli = true
			}
		}
		ast.Inspect(f.ast, func(n ast.Node) bool {
			switch x := n.(type) {
			case *ast.BasicLit:
				if x.Value == `"TaskGroups"` {
					taskGroups = true
				}
			case *ast.KeyValueExpr:
				if id, ok := x.Key.(*ast.Ident); ok && id.Name == "TaskGroups" {
					taskGroups = true
				}
			case *ast.SelectStmt:
				if x.Body == nil || len(x.Body.List) == 0 {
					longRunning = true
				}
			case *ast.SwitchStmt:
				if x.Tag != nil && isArgSelector(x.Tag) {
					cli = true
				}
			case *ast.CallExpr:
				sel, ok := x.Fun.(*ast.SelectorExpr)
				if !ok {
					return true
				}
				pkg := ""
				if id, ok := sel.X.(*ast.Ident); ok {
					pkg = f.imports[id.Name]
				}
				switch name := sel.Sel.Name; {
				case pkg == "flag" && (name == "Parse" || name == "NewFlagSet"):
					cli = true
				case pkg == "os/signal" && (name == "Notify" || name == "NotifyContext"):
					longRunning = true
				case pkg == lambdaGo && name == "Start", pkg == nomadPlugins && name == "Serve":
					longRunning = true
				case pkg != "" && pkg != "net/http":
				case name == "ListenAndServe" || name == "ListenAndServeTLS" || (name == "Serve" || name == "ServeTLS") && len(x.Args) > 0:
					longRunning = true
				}
			}
			return true
		})
		for _, d := range f.ast.Decls {
			fd, ok := d.(*ast.FuncDecl)
			if !ok {
				continue
			}
			ref := funcRef{fd, f.rel, g.fset}
			if p.name == "main" && fd.Recv == nil && fd.Name.Name == "main" {
				mainFn = ref
			}
			if fd.Type.Results != nil && len(fd.Type.Results.List) > 0 {
				r := fd.Type.Results.List[0].Type
				if st, ok := r.(*ast.StarExpr); ok {
					r = st.X
				}
				if s, ok := r.(*ast.SelectorExpr); ok && s.Sel.Name == "Job" {
					if id, ok := s.X.(*ast.Ident); ok && f.imports[id.Name] == nomadAPI {
						out = append(out, g.declEntry(KindNomad, ref, "nomad-jobspec"))
						continue
					}
				}
			}
			if fd.Recv == nil && fd.Name.IsExported() && nomadBuilder.MatchString(fd.Name.Name) && fd.Type.Results != nil {
				nomadCands = append(nomadCands, ref)
			}
		}
	}
	if taskGroups {
		for _, ref := range nomadCands {
			out = append(out, g.declEntry(KindNomad, ref, "nomad-jobspec"))
		}
	}
	if mainFn.decl != nil && !cli && longRunning {
		e := g.declEntry(KindSvcMain, mainFn, "service-main")
		e.Name = filepath.Base(p.dir)
		out = append(out, e)
	}
	out = append(out, g.commandTables(p)...)
	return dedupe(out)
}

// commandTables finds cobra trees hung from data: a struct type whose
// []string path field (c.Path[len(c.Path)-1] or strings.Join(c.Path, " "))
// names the command a function builds as a cobra.Command, and every literal
// of it (or of a type whose path field feeds it) with a literal path.
func (g *goScan) commandTables(p *goPkg) []Entry {
	strFields := map[string]map[string]bool{} // type -> []string fields
	for name, st := range p.structs {
		for _, fl := range st.Fields.List {
			at, ok := fl.Type.(*ast.ArrayType)
			if !ok || at.Len != nil {
				continue
			}
			if id, ok := at.Elt.(*ast.Ident); !ok || id.Name != "string" {
				continue
			}
			for _, n := range fl.Names {
				if strFields[name] == nil {
					strFields[name] = map[string]bool{}
				}
				strFields[name][n.Name] = true
			}
		}
	}
	if len(strFields) == 0 {
		return nil
	}
	isStrField := func(field string) bool {
		for _, fs := range strFields {
			if fs[field] {
				return true
			}
		}
		return false
	}
	pathFields := map[string]bool{}
	root := ""
	for _, f := range p.files {
		for _, d := range f.ast.Decls {
			fd, ok := d.(*ast.FuncDecl)
			if !ok || fd.Body == nil {
				continue
			}
			builds := false
			ast.Inspect(fd.Body, func(n ast.Node) bool {
				if c, ok := n.(*ast.CompositeLit); ok {
					if s, ok := c.Type.(*ast.SelectorExpr); ok && s.Sel.Name == "Command" {
						if id, ok := s.X.(*ast.Ident); ok && f.imports[id.Name] == cobraPkg {
							builds = true
							if use := kvString(c, "Use"); use != "" && root == "" && strings.Contains(strings.ToLower(fd.Name.Name), "root") {
								root = strings.Fields(use)[0]
							}
						}
					}
				}
				return true
			})
			if !builds {
				continue
			}
			ast.Inspect(fd.Body, func(n ast.Node) bool {
				switch x := n.(type) {
				case *ast.IndexExpr:
					if s, ok := x.X.(*ast.SelectorExpr); ok && isStrField(s.Sel.Name) {
						if b, ok := x.Index.(*ast.BinaryExpr); ok && b.Op == token.SUB && strings.HasPrefix(exprString(b.X), "len(") && strings.HasSuffix(exprString(b.X), "."+s.Sel.Name+")") {
							pathFields[s.Sel.Name] = true
						}
					}
				case *ast.CallExpr:
					if exprString(x.Fun) == "strings.Join" && len(x.Args) == 2 {
						if s, ok := x.Args[0].(*ast.SelectorExpr); ok && isStrField(s.Sel.Name) {
							if sep, _ := stringLit(x.Args[1]); sep == " " {
								pathFields[s.Sel.Name] = true
							}
						}
					}
				}
				return true
			})
		}
	}
	if len(pathFields) == 0 {
		return nil
	}
	tableType := func(t string) string {
		for fld := range strFields[t] {
			if pathFields[fld] {
				return fld
			}
		}
		return ""
	}
	type row struct {
		lit *ast.CompositeLit
		fld string
		typ string
		f   *goFile
	}
	collect := func() []row {
		var rows []row
		for _, f := range p.files {
			ast.Inspect(f.ast, func(n ast.Node) bool {
				c, ok := n.(*ast.CompositeLit)
				if !ok {
					return true
				}
				switch t := c.Type.(type) {
				case *ast.ArrayType, *ast.MapType:
					var elt ast.Expr
					if at, ok := t.(*ast.ArrayType); ok {
						elt = at.Elt
					} else {
						elt = t.(*ast.MapType).Value
					}
					if fld := tableType(typeName(elt)); fld != "" {
						for _, el := range c.Elts {
							if kv, ok := el.(*ast.KeyValueExpr); ok {
								el = kv.Value
							}
							if u, ok := el.(*ast.UnaryExpr); ok {
								el = u.X
							}
							if r, ok := el.(*ast.CompositeLit); ok && r.Type == nil {
								rows = append(rows, row{r, fld, typeName(elt), f})
							}
						}
					}
				default:
					if fld := tableType(typeName(c.Type)); fld != "" {
						rows = append(rows, row{c, fld, typeName(c.Type), f})
					}
				}
				return true
			})
		}
		return rows
	}
	// A table type's path field filled from another type's []string field
	// (capability{CmdPath: op.CmdPath}) makes that type a table too.
	for round := 0; round < 3; round++ {
		grew := false
		for _, r := range collect() {
			if s, ok := kvExpr(r.lit, r.fld).(*ast.SelectorExpr); ok && isStrField(s.Sel.Name) && !pathFields[s.Sel.Name] {
				pathFields[s.Sel.Name] = true
				grew = true
			}
		}
		if !grew {
			break
		}
	}
	var out []Entry
	for _, r := range collect() {
		v, ok := kvExpr(r.lit, r.fld).(*ast.CompositeLit)
		if !ok || len(v.Elts) == 0 {
			continue
		}
		var words []string
		for _, el := range v.Elts {
			s, ok := stringLit(el)
			if !ok {
				words = nil
				break
			}
			words = append(words, s)
		}
		if len(words) == 0 {
			continue
		}
		name := strings.TrimSpace(root + " " + strings.Join(words, " "))
		e := g.entry(KindCLI, name, r.f.rel, kvPos(r.lit, r.fld), "command-table")
		e.Detail = r.typ + "." + r.fld
		out = append(out, e)
	}
	return out
}

// argvModes expands a main()'s switch on a mode the arguments select
// (mode := modeFromArgs(); switch mode { case modeX: runX(ctx) }): each case
// runs one daemon mode.
func (g *goScan) argvModes(p *goPkg, fn *ast.FuncDecl, x *ast.SwitchStmt) []Entry {
	if fn == nil || fn.Name.Name != "main" || fn.Recv != nil || x.Tag == nil {
		return nil
	}
	if !g.fromArgs(p, fn, x.Tag) {
		return nil
	}
	var out []Entry
	for _, s := range x.Body.List {
		cc := s.(*ast.CaseClause)
		if len(cc.List) != 1 {
			continue
		}
		var target *ast.FuncDecl
		var file string
		for _, st := range cc.Body {
			es, ok := st.(*ast.ExprStmt)
			if !ok {
				continue
			}
			call, ok := es.X.(*ast.CallExpr)
			if !ok {
				continue
			}
			if id, ok := call.Fun.(*ast.Ident); ok {
				if refs := p.funcs[id.Name]; len(refs) == 1 && refs[0].decl.Recv == nil {
					target, file = refs[0].decl, refs[0].file
					break
				}
			}
		}
		if target == nil {
			continue
		}
		mode, ok := stringLit(cc.List[0])
		if !ok {
			mode = exprString(cc.List[0])
			for _, pre := range []string{"mode", "Mode", "cmd", "Cmd"} {
				if strings.HasPrefix(mode, pre) && len(mode) > len(pre) {
					mode = mode[len(pre):]
					break
				}
			}
			mode = strings.TrimPrefix(kebab(mode), "-")
		}
		e := g.declEntry(KindCLI, funcRef{target, file, g.fset}, "argv-mode")
		e.Name = filepath.Base(p.dir) + " " + mode
		out = append(out, e)
	}
	return out
}

// fromArgs reports whether a switch tag comes from the command line: it
// reads os.Args or flag.Args, directly or through a package function (also
// via a local the function's result was assigned to).
func (g *goScan) fromArgs(p *goPkg, fn *ast.FuncDecl, tag ast.Expr) bool {
	readsArgs := func(n ast.Node) bool {
		found := false
		ast.Inspect(n, func(m ast.Node) bool {
			if s, ok := m.(*ast.SelectorExpr); ok {
				if e := exprString(s); e == "os.Args" || e == "flag.Args" || e == "flag.Arg" {
					found = true
				}
			}
			return !found
		})
		return found
	}
	viaCall := func(e ast.Expr) bool {
		c, ok := e.(*ast.CallExpr)
		if !ok {
			return false
		}
		if readsArgs(c) {
			return true
		}
		if id, ok := c.Fun.(*ast.Ident); ok {
			if refs := p.funcs[id.Name]; len(refs) == 1 && refs[0].decl.Body != nil {
				return readsArgs(refs[0].decl.Body)
			}
		}
		return false
	}
	if viaCall(tag) {
		return true
	}
	id, ok := tag.(*ast.Ident)
	if !ok {
		return false
	}
	found := false
	ast.Inspect(fn.Body, func(n ast.Node) bool {
		if as, ok := n.(*ast.AssignStmt); ok {
			for i, l := range as.Lhs {
				if lid, ok := l.(*ast.Ident); ok && lid.Name == id.Name && i < len(as.Rhs) && viaCall(as.Rhs[i]) {
					found = true
				}
			}
		}
		return !found
	})
	return found
}

// temporalSchedule recognizes a Temporal Schedule: a client.ScheduleOptions
// literal, or a schedule-table row with an ID, a workflow and an interval
// or cron spec in a file using the Temporal client.
func temporalSchedule(f *goFile, c *ast.CompositeLit) (string, bool) {
	uses := false
	for _, ip := range f.imports {
		if ip == temporalCli {
			uses = true
		}
	}
	if !uses {
		return "", false
	}
	show := func(e ast.Expr) string {
		if s, ok := stringLit(e); ok {
			return s
		}
		return exprString(e)
	}
	id := kvExpr(c, "ID")
	if id == nil {
		id = kvExpr(c, "ScheduleID")
	}
	if id == nil {
		return "", false
	}
	if s, ok := c.Type.(*ast.SelectorExpr); ok && s.Sel.Name == "ScheduleOptions" {
		var wf ast.Expr
		ast.Inspect(c, func(n ast.Node) bool {
			if x, ok := n.(*ast.CompositeLit); ok && wf == nil {
				wf = kvExpr(x, "Workflow")
			}
			return wf == nil
		})
		if wf == nil {
			return "temporal-schedule " + show(id), true
		}
		return "temporal-schedule " + show(id) + " -> " + show(wf), true
	}
	var wf ast.Expr
	for _, k := range []string{"WorkflowType", "Workflow", "WorkflowName"} {
		if wf = kvExpr(c, k); wf != nil {
			break
		}
	}
	if wf == nil {
		return "", false
	}
	for _, k := range []string{"Interval", "Every", "Period", "CronSchedule", "Cron", "Spec", "Schedule"} {
		if kvExpr(c, k) != nil {
			return "temporal-schedule " + show(id) + " -> " + show(wf), true
		}
	}
	return "", false
}

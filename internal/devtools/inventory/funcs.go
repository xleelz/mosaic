package main

// Function-level kinds, for logic-level scopes (DESIGN §14.2). They are
// opt-in (--kinds): a system-level inventory lists entry points, while a
// component refined to `logic` needs its functions as the parts to cover.
// Each entry spans the whole declaration (line to end_line), says whether
// the name is exported, and is flagged `test` when it comes from a test file;
// test files are read only with --include-test-funcs.

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// Opt-in function kinds.
const (
	KindGoFunc = "go-func" // top-level Go functions and methods ("Type.Method")
	KindPyFunc = "py-func" // module-level Python functions and class methods ("Class.method")
	KindTSFunc = "ts-func" // top-level TS/JS functions and class methods ("Class.method")
)

// OptKinds lists the kinds a scan produces only when asked (Options.Kinds).
var OptKinds = []string{KindGoFunc, KindPyFunc, KindTSFunc}

func (o Options) kind(k string) bool {
	for _, x := range o.Kinds {
		if x == k {
			return true
		}
	}
	return false
}

// inPaths reports whether rel is one of paths or under one of them. No paths
// means everywhere.
func inPaths(rel string, paths []string) bool {
	if len(paths) == 0 {
		return true
	}
	for _, p := range paths {
		if p == "." || rel == p || strings.HasPrefix(rel, p+"/") {
			return true
		}
	}
	return false
}

// cleanPaths normalizes scope paths to slash-separated paths relative to the
// root.
func cleanPaths(paths []string) []string {
	var out []string
	for _, p := range paths {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		out = append(out, filepath.ToSlash(filepath.Clean(p)))
	}
	return out
}

func boolp(b bool) *bool { return &b }

var pyTestFile = regexp.MustCompile(`^(test_.*|.*_test|conftest)\.py$`)

// funcEntries returns the function entries of one walked file for the kinds
// opt enables, or nil when the file is none of theirs.
func funcEntries(path, rel, name string, opt Options) []Entry {
	switch {
	case strings.HasSuffix(name, ".go") && opt.kind(KindGoFunc):
		test := strings.HasSuffix(name, "_test.go")
		if test && !opt.IncludeTestFuncs {
			return nil
		}
		return goFuncs(path, rel, test)
	case strings.HasSuffix(name, ".py") && opt.kind(KindPyFunc):
		test := pyTestFile.MatchString(name)
		if test && !opt.IncludeTestFuncs {
			return nil
		}
		return pyFuncs(path, rel, test)
	case isTS(name) && opt.kind(KindTSFunc):
		test := testName.MatchString(name) || tsFrontTest(rel)
		if test && !opt.IncludeTestFuncs {
			return nil
		}
		return tsFuncs(path, rel, test)
	}
	return nil
}

// goFuncs lists a Go file's top-level functions and methods.
func goFuncs(path, rel string, test bool) []Entry {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, path, nil, parser.SkipObjectResolution)
	if err != nil {
		return nil
	}
	var out []Entry
	for _, d := range f.Decls {
		fn, ok := d.(*ast.FuncDecl)
		if !ok {
			continue
		}
		e := Entry{Kind: KindGoFunc, Name: fn.Name.Name, File: rel, Via: "go/ast",
			Line: fset.Position(fn.Pos()).Line, EndLine: fset.Position(fn.End()).Line,
			Exported: boolp(fn.Name.IsExported()), Test: test}
		if r := recvType(fn); r != "" {
			e.Name = r + "." + fn.Name.Name
			e.Detail = "method"
		}
		out = append(out, e)
	}
	return out
}

// pyFuncs lists a Python file's module-level functions and the methods of its
// classes (nested classes included); functions nested in functions are not
// listed.
func pyFuncs(path, rel string, test bool) []Entry {
	src, err := os.ReadFile(path)
	if err != nil || len(src) > 4<<20 {
		return nil
	}
	f := parsePy(rel, src)
	var out []Entry
	for _, d := range f.defs {
		if d.kind != "def" {
			continue
		}
		method := false
		nested := false
		for o := d.owner; o != nil; o = o.owner {
			if o.kind != "class" {
				nested = true
				break
			}
			method = true
		}
		if nested {
			continue
		}
		dunder := strings.HasPrefix(d.name, "__") && strings.HasSuffix(d.name, "__")
		e := Entry{Kind: KindPyFunc, Name: d.qual(), File: rel, Via: "py-def",
			Line: d.line, EndLine: d.endLine,
			Exported: boolp(dunder || !strings.HasPrefix(d.name, "_")), Test: test}
		if method {
			e.Detail = "method"
		}
		out = append(out, e)
	}
	return out
}

// tsMods are member modifiers that may precede a class method's name.
var tsMods = map[string]bool{
	"public": true, "private": true, "protected": true, "static": true, "async": true,
	"readonly": true, "abstract": true, "override": true, "get": true, "set": true,
	"declare": true, "accessor": true,
}

// tsFuncs lists a TS/JS file's top-level functions (function declarations
// and const arrow or function expressions) and its classes' methods
// (including arrow-function fields and constructors). Signatures without a
// body (overloads, abstract and ambient declarations) are not listed.
func tsFuncs(path, rel string, test bool) []Entry {
	src, err := os.ReadFile(path)
	if err != nil || len(src) > 4<<20 {
		return nil
	}
	f := parseTS(rel, src)
	var out []Entry
	add := func(name string, start, body int, exported bool, method bool) {
		e := Entry{Kind: KindTSFunc, Name: name, File: rel, Via: "ts-decl",
			Line: f.line(start), EndLine: f.line(f.end(body)), Exported: boolp(exported), Test: test}
		if method {
			e.Detail = "method"
		}
		out = append(out, e)
	}
	n := len(f.toks)
	for i := 0; i < n; i++ {
		if f.depth[i] != 0 || f.toks[i].k != 'i' || !tsStmtStart(f, i) {
			continue
		}
		// start of the declaration, with its export flag
		start, exported := i, false
		j := i
		if f.s(j) == "export" {
			exported = true
			j++
			if f.is(j, 'i', "default") {
				j++
			}
		}
		if f.is(j, 'i', "declare") {
			continue
		}
		switch {
		case f.is(j, 'i', "async") && f.is(j+1, 'i', "function"), f.is(j, 'i', "function"):
			if f.is(j, 'i', "async") {
				j++
			}
			k := j + 1
			if f.p(k, "*") {
				k++
			}
			name := "default"
			if f.ident(k) {
				name = f.s(k)
				k++
			}
			if body, ok := tsBody(f, k); ok {
				add(name, start, body, exported, false)
				i = f.end(body)
			}
		case f.is(j, 'i', "abstract") && f.is(j+1, 'i', "class"), f.is(j, 'i', "class"):
			if f.is(j, 'i', "abstract") {
				j++
			}
			c := (*tsFront)(nil).classAt(f, j)
			if c == nil {
				continue
			}
			cname := c.name
			if cname == "" {
				cname = "default"
			}
			out = append(out, tsMethods(f, c.brace, cname, exported, rel, test)...)
			i = f.end(c.brace)
		case f.is(j, 'i', "const") || f.is(j, 'i', "let") || f.is(j, 'i', "var"):
			if !f.ident(j + 1) {
				continue
			}
			k := j + 2
			if f.p(k, ":") { // type annotation up to '='
				for k < n && !f.p(k, "=") && !f.p(k, ";") && f.toks[k].line == f.toks[j].line {
					if f.p(k, "(") || f.p(k, "[") || f.p(k, "{") {
						k = f.end(k)
					}
					k++
				}
			}
			if !f.p(k, "=") {
				continue
			}
			if body, ok := tsFuncExpr(f, k+1); ok {
				add(f.s(j+1), start, body, exported, false)
				i = f.end(body)
			}
		}
	}
	return out
}

// tsStmtStart reports whether token i starts a statement: first in the
// file, after ';', '{' or '}', or on a new line after a token that doesn't
// continue an expression.
func tsStmtStart(f *tsFile, i int) bool {
	if i == 0 {
		return true
	}
	p := f.s(i - 1)
	if p == ";" || p == "{" || p == "}" {
		return true
	}
	return f.line(i) > f.line(i-1) && !tsContinues(p)
}

// tsContinues reports whether a line ending in token s continues on the next.
func tsContinues(s string) bool {
	switch s {
	case "(", "[", ",", "=", ":", "?", ".", "=>", "+", "-", "*", "/", "&&", "||", "??", "|", "&", "<", ">", "!",
		"export", "default", "async", "return", "new", "await", "typeof", "in", "of", "extends", "implements":
		return true
	}
	return false
}

// tsBody returns the body '{' of a function whose parameter list (after any
// generic arguments) starts at k.
func tsBody(f *tsFile, k int) (int, bool) {
	if f.p(k, "<") {
		k = f.skipAngles(k)
	}
	if !f.p(k, "(") {
		return 0, false
	}
	k = f.end(k) + 1
	if f.p(k, "{") {
		return k, true
	}
	if !f.p(k, ":") {
		return 0, false
	}
	// return type: the body is the first '{' not in type position
	for k++; k < len(f.toks); k++ {
		switch {
		case f.p(k, ";") || f.p(k, "}"):
			return 0, false
		case f.p(k, "<"):
			if e := f.skipAngles(k); e > k {
				k = e - 1
			}
		case f.p(k, "(") || f.p(k, "["):
			k = f.end(k)
		case f.p(k, "{"):
			if p := f.s(k - 1); p == ":" || p == "|" || p == "&" || p == "=>" || p == "," || p == "<" || p == "keyof" || p == "typeof" {
				k = f.end(k)
				continue
			}
			return k, true
		}
	}
	return 0, false
}

// tsFuncExpr returns the body '{' of an arrow function or function expression
// starting at k. Expression-bodied arrows return their last token.
func tsFuncExpr(f *tsFile, k int) (int, bool) {
	if f.is(k, 'i', "async") {
		k++
	}
	if f.is(k, 'i', "function") {
		k++
		if f.p(k, "*") {
			k++
		}
		if f.ident(k) {
			k++
		}
		return tsBody(f, k)
	}
	if f.p(k, "<") {
		k = f.skipAngles(k)
	}
	switch {
	case f.p(k, "("):
		k = f.end(k) + 1
	case f.ident(k) && f.p(k+1, "=>"):
		k++
	default:
		return 0, false
	}
	if f.p(k, ":") { // return type up to '=>'
		for k < len(f.toks) && !f.p(k, "=>") && !f.p(k, ";") {
			if f.p(k, "(") || f.p(k, "[") || f.p(k, "{") {
				k = f.end(k)
			}
			k++
		}
	}
	if !f.p(k, "=>") {
		return 0, false
	}
	k++
	if f.p(k, "{") {
		return k, true
	}
	// expression body: up to the statement's end at this depth
	e := k
	for e+1 < len(f.toks) && !f.p(e+1, ";") && f.depth[e+1] >= f.depth[k] && !(f.p(e+1, "}") && f.depth[e+1] < f.depth[k]) {
		if f.p(e+1, "(") || f.p(e+1, "[") || f.p(e+1, "{") {
			e = f.end(e + 1)
			continue
		}
		if f.toks[e+1].line != f.toks[e].line && f.depth[e+1] == f.depth[k] && f.ident(e+1) && (f.s(e+1) == "export" || f.s(e+1) == "const" || f.s(e+1) == "function") {
			break
		}
		e++
	}
	return e, true
}

// tsMethods lists the methods of the class whose body opens at brace.
func tsMethods(f *tsFile, brace int, class string, exported bool, rel string, test bool) []Entry {
	var out []Entry
	md := f.depth[brace] + 1
	end := f.end(brace)
	memberStart := true
	for i := brace + 1; i < end; i++ {
		if f.depth[i] != md {
			continue
		}
		if f.p(i, ";") || f.p(i, "}") {
			memberStart = true
			continue
		}
		if f.line(i) > f.line(i-1) && !tsContinues(f.s(i-1)) {
			memberStart = true // a member on a new line, after one without ';'
		}
		if !memberStart {
			if f.p(i, "{") || f.p(i, "(") || f.p(i, "[") {
				i = f.end(i)
			}
			continue
		}
		if f.p(i, "@") { // decorator: @name(.name)*(args)?
			j := i + 1
			for f.ident(j) && f.p(j+1, ".") {
				j += 2
			}
			if f.p(j+1, "(") {
				j = f.end(j + 1)
			}
			i = j
			continue
		}
		start := i
		private := false
		j := i
		for (f.ident(j) && tsMods[f.s(j)] && (f.ident(j+1) || f.p(j+1, "*") || f.p(j+1, "#") || f.p(j+1, "["))) || f.p(j, "*") {
			if f.s(j) == "private" || f.s(j) == "protected" {
				private = true
			}
			j++
		}
		if f.p(j, "#") {
			private = true
			j++
		}
		memberStart = false
		if !f.ident(j) {
			if f.p(j, "{") || f.p(j, "(") || f.p(j, "[") {
				i = f.end(j)
			}
			continue
		}
		name := f.s(j)
		k := j + 1
		if f.p(k, "?") || f.p(k, "!") {
			k++
		}
		var body int
		var ok bool
		switch {
		case f.p(k, "(") || f.p(k, "<"):
			body, ok = tsBody(f, k)
		case f.p(k, "=") || f.p(k, ":"):
			if f.p(k, ":") { // field type up to '='
				for k < end && !f.p(k, "=") && !f.p(k, ";") && f.depth[k] == md {
					if f.p(k, "(") || f.p(k, "[") || f.p(k, "{") {
						k = f.end(k)
					}
					k++
				}
				if !f.p(k, "=") {
					i = k - 1
					continue
				}
			}
			body, ok = tsFuncExpr(f, k+1)
		}
		if !ok {
			i = k - 1
			continue
		}
		e := Entry{Kind: KindTSFunc, Name: class + "." + name, File: rel, Via: "ts-decl", Detail: "method",
			Line: f.line(start), EndLine: f.line(f.end(body)), Exported: boolp(exported && !private), Test: test}
		out = append(out, e)
		i = f.end(body)
		memberStart = true
	}
	return out
}

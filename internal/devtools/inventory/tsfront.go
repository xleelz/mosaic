package main

// The ts-frontend plugin: entry points of a VS Code style TypeScript desktop
// and web front end. Sources are lexed (comments dropped, strings and
// templates opaque), brackets matched, and registrations recognised at the
// token level: commands (Action2 subclasses, CommandsRegistry,
// KeybindingsRegistry, editor actions and commands), workbench and editor
// contributions, extension points, services (createDecorator plus their
// registerSingleton implementations), IPC channels, extension host RPC
// shapes and their MainThread customers, the vscode.d.ts API namespaces,
// built-in extensions' package.json commands and activation events, process
// main files and the Rust CLI's clap subcommands. Command and channel ids
// that are constants are resolved through a repository-wide index of string
// constants (const, enum members, static class fields, object literal keys).

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// ts-frontend entry kinds. Rust clap subcommands reuse KindCLI.
const (
	KindVSCommand    = "vscode-command"         // Action2, CommandsRegistry, keybinding rules, editor actions and commands
	KindContribution = "workbench-contribution" // workbench and editor contributions
	KindExtPoint     = "extension-point"        // ExtensionsRegistry.registerExtensionPoint (package.json contribution points)
	KindService      = "service"                // createDecorator service identifiers, with their registerSingleton implementations
	KindIPC          = "ipc-channel"            // registerChannel('name', channel)
	KindExtHostRPC   = "exthost-rpc"            // $methods of MainThread*Shape / ExtHost*Shape in extHost.protocol.ts
	KindExtHostCust  = "exthost-customer"       // @extHostNamedCustomer / @extHostCustomer MainThread classes
	KindExtAPI       = "extension-api"          // functions of the vscode.d.ts namespaces
	KindExtCommand   = "extension-command"      // built-in extensions' contributes.commands
	KindActivation   = "activation-event"       // built-in extensions' activationEvents
	KindProcessMain  = "process-main"           // process entry files (main, cli, server, extension host, utility processes, workers)
)

// tsFile is one lexed TypeScript file.
type tsFile struct {
	rel   string
	toks  []jtok
	m     []int
	depth []int // brace depth of each token
}

func parseTS(rel string, src []byte) *tsFile {
	f := &tsFile{rel: rel, toks: tslex(src)}
	f.m = jmatch(f.toks)
	f.depth = make([]int, len(f.toks))
	d := 0
	for i, t := range f.toks {
		if t.k == 'p' && t.s == "}" && d > 0 {
			d--
		}
		f.depth[i] = d
		if t.k == 'p' && t.s == "{" {
			d++
		}
	}
	return f
}

func (f *tsFile) s(i int) string {
	if i < 0 || i >= len(f.toks) {
		return ""
	}
	return f.toks[i].s
}

func (f *tsFile) is(i int, k byte, s string) bool {
	return i >= 0 && i < len(f.toks) && f.toks[i].k == k && f.toks[i].s == s
}

func (f *tsFile) p(i int, s string) bool { return f.is(i, 'p', s) }

func (f *tsFile) ident(i int) bool { return i >= 0 && i < len(f.toks) && f.toks[i].k == 'i' }

func (f *tsFile) end(i int) int {
	if i < 0 || i >= len(f.m) || f.m[i] < 0 {
		return i
	}
	return f.m[i]
}

func (f *tsFile) line(i int) int {
	if i >= len(f.toks) {
		i = len(f.toks) - 1
	}
	if i < 0 {
		return 0
	}
	return f.toks[i].line
}

// args splits the bracketed list opened at open into top-level ranges.
func (f *tsFile) args(open int) [][2]int {
	close := f.end(open)
	var out [][2]int
	lo := open + 1
	for i := lo; i < close; i++ {
		t := f.toks[i]
		if t.k == 'p' && (t.s == "(" || t.s == "[" || t.s == "{") {
			i = f.end(i)
			continue
		}
		if t.k == 'p' && t.s == "," {
			out = append(out, [2]int{lo, i})
			lo = i + 1
		}
	}
	if lo < close {
		out = append(out, [2]int{lo, close})
	}
	return out
}

// text renders tokens compactly.
func (f *tsFile) text(lo, hi int) string {
	var b strings.Builder
	for i := lo; i < hi && i < len(f.toks); i++ {
		t := f.toks[i]
		switch t.k {
		case 's':
			b.WriteString("'" + t.s + "'")
		case 't':
			b.WriteString("`" + t.s + "`")
		default:
			if i > lo && t.k == 'i' && f.toks[i-1].k == 'i' {
				b.WriteByte(' ')
			}
			b.WriteString(t.s)
		}
		if b.Len() > 120 {
			b.WriteString("...")
			break
		}
	}
	return b.String()
}

// objKey finds key: value at the top level of the object literal opened at
// brace and returns the value's token range.
func (f *tsFile) objKey(brace int, key string) (int, int, bool) {
	if !f.p(brace, "{") {
		return 0, 0, false
	}
	for _, a := range f.args(brace) {
		if a[1]-a[0] >= 3 && (f.is(a[0], 'i', key) || f.is(a[0], 's', key)) && f.p(a[0]+1, ":") {
			return a[0] + 2, a[1], true
		}
	}
	return 0, 0, false
}

// callDecl reports whether the identifier at i followed by (...) is a
// declaration or signature rather than a call.
func (f *tsFile) callDecl(i, open int) bool {
	if f.is(i-1, 'i', "function") || f.is(i-1, 'i', "async") && f.is(i-2, 'i', "function") {
		return true
	}
	c := f.end(open)
	return f.p(c+1, "{") || f.p(c+1, ":")
}

// skipAngles returns the token after the generic arguments opened at i.
func (f *tsFile) skipAngles(i int) int {
	d := 0
	for j := i; j < len(f.toks) && j < i+200; j++ {
		switch {
		case f.p(j, "<"):
			d++
		case f.p(j, ">"):
			d--
			if d == 0 {
				return j + 1
			}
		case f.p(j, "(") || f.p(j, "[") || f.p(j, "{"):
			j = f.end(j)
		case f.p(j, ";"):
			return i
		}
	}
	return i
}

// receiver returns the identifier before ".name" at i, or "".
func (f *tsFile) receiver(i int) string {
	if f.p(i-1, ".") && f.ident(i-2) {
		return f.s(i - 2)
	}
	return ""
}

// ---------------------------------------------------------------- index

type tsConst struct {
	f      *tsFile
	lo, hi int
}

type tsClass struct {
	name, base string
	f          *tsFile
	at, brace  int // 'class' token and body '{'
}

type tsFront struct {
	files     []*tsFile
	consts    map[string][]tsConst // qualified name -> definitions
	fconsts   map[*tsFile]map[string]tsConst
	classes   map[string][]*tsClass
	fclasses  map[*tsFile]map[string]*tsClass
	anon      map[*tsFile]map[int]*tsClass // inline classes by 'class' token
	nsImports map[*tsFile]map[string]bool  // import * as X
	singles   map[string][]string          // service decorator -> implementations
	impls     map[string][]string          // Shape interface -> implementing classes
	extCmds   map[string]string            // extension command id -> handler site
	pkgs      []string                     // extension package.json paths (abs)
	pkgRels   []string
	rust      [][2]string // abs, rel
	dts       [][2]string // vscode.d.ts files
	mains     []*tsFile
}

func newTSFront() *tsFront {
	return &tsFront{consts: map[string][]tsConst{}, fconsts: map[*tsFile]map[string]tsConst{},
		classes: map[string][]*tsClass{}, fclasses: map[*tsFile]map[string]*tsClass{},
		anon: map[*tsFile]map[int]*tsClass{}, nsImports: map[*tsFile]map[string]bool{}, singles: map[string][]string{}, impls: map[string][]string{},
		extCmds: map[string]string{}}
}

// tsFrontSource reports whether a TS file belongs to the core sources the
// registration heuristics read (not extensions, not test or generated code).
var tsGenerated = regexp.MustCompile(`(?i)(@generated\b|do not edit|auto-?generated)`)

func generatedPath(rel string) bool {
	for _, s := range strings.Split(rel, "/") {
		if s == "generated" || s == "gen" || s == "third_party" || s == "thirdparty" {
			return true
		}
	}
	return false
}

func tsFrontTest(rel string) bool {
	base := filepath.Base(rel)
	return strings.Contains(base, ".test.") || strings.Contains(base, ".spec.") || strings.Contains(base, ".integrationTest.")
}

// add takes one walked file.
func (fe *tsFront) add(path, rel string) {
	name := filepath.Base(rel)
	switch {
	case name == "package.json":
		segs := strings.Split(rel, "/")
		if len(segs) == 3 && segs[0] == "extensions" && !testExtension(segs[1]) {
			fe.pkgs = append(fe.pkgs, path)
			fe.pkgRels = append(fe.pkgRels, rel)
		}
	case strings.HasSuffix(name, ".rs"):
		if strings.HasPrefix(rel, "cli/src/") {
			fe.rust = append(fe.rust, [2]string{path, rel})
		}
	case name == "vscode.d.ts":
		fe.dts = append(fe.dts, [2]string{path, rel})
	case strings.HasSuffix(name, ".ts") && !strings.HasSuffix(name, ".d.ts"):
		if tsFrontTest(rel) || generatedPath(rel) {
			return
		}
		segs := strings.Split(rel, "/")
		if segs[0] == "extensions" {
			if len(segs) > 2 && !testExtension(segs[1]) {
				fe.extHandlers(path, rel, segs[1])
			}
			return
		}
		if segs[0] != "src" {
			return
		}
		src, err := os.ReadFile(path)
		if err != nil || len(src) > 4<<20 || tsGenerated.Match(src[:min(len(src), 600)]) {
			return
		}
		f := parseTS(rel, src)
		fe.files = append(fe.files, f)
		fe.index(f)
	}
}

func testExtension(name string) bool {
	return regexp.MustCompile(`(^|-)tests?(-|$)|test-resolver`).MatchString(name)
}

var extHandlerRe = regexp.MustCompile(`(?:registerCommand|registerTextEditorCommand|@command)\(\s*['"]([\w.\-:/]+)['"]`)

// extHandlers records where an extension registers its commands, by id.
func (fe *tsFront) extHandlers(path, rel, ext string) {
	src, err := os.ReadFile(path)
	if err != nil || len(src) > 4<<20 || !bytes.Contains(src, []byte("ommand")) {
		return
	}
	f := tslex(src)
	for i := 0; i+2 < len(f); i++ {
		t := f[i]
		if t.k != 'i' || (t.s != "registerCommand" && t.s != "registerTextEditorCommand" && t.s != "command") {
			continue
		}
		if t.s == "command" && (i == 0 || f[i-1].s != "@") {
			continue
		}
		if f[i+1].s == "(" && f[i+1].k == 'p' && f[i+2].k == 's' {
			id := f[i+2].s
			if _, ok := fe.extCmds[ext+"\x00"+id]; !ok {
				fe.extCmds[ext+"\x00"+id] = fmt.Sprintf("%s:%d", rel, t.line)
			}
		}
	}
}

// index records string constants, classes, singletons and Shape
// implementations of one file.
func (fe *tsFront) index(f *tsFile) {
	fc := map[string]tsConst{}
	fe.fconsts[f] = fc
	fe.fclasses[f] = map[string]*tsClass{}
	fe.anon[f] = map[int]*tsClass{}
	fe.nsImports[f] = map[string]bool{}
	for i := 0; i+3 < len(f.toks); i++ {
		if f.is(i, 'i', "import") && f.p(i+1, "*") && f.is(i+2, 'i', "as") && f.ident(i+3) {
			fe.nsImports[f][f.s(i+3)] = true
		}
	}
	type scope struct {
		name   string
		lo, hi int
		depth  int // depth of direct members
	}
	var scopes []scope
	qual := func(i int) (string, bool) {
		var parts []string
		d := 0
		for _, s := range scopes {
			if i > s.lo && i < s.hi {
				parts = append(parts, s.name)
				d = s.depth
			}
		}
		if f.depth[i] != d {
			return "", false
		}
		return strings.Join(parts, "."), true
	}
	record := func(q, name string, lo, hi int, global bool) {
		key := name
		if q != "" {
			key = q + "." + name
		}
		c := tsConst{f, lo, hi}
		if _, ok := fc[key]; !ok {
			fc[key] = c
			if global {
				fe.consts[key] = append(fe.consts[key], c)
			}
		}
		if _, ok := fc[name]; !ok {
			fc[name] = c // function-local and unqualified lookups
		}
	}
	var object func(prefix string, brace int, global bool)
	object = func(prefix string, brace int, global bool) {
		for _, a := range f.args(brace) {
			if a[1]-a[0] >= 3 && (f.ident(a[0]) || f.toks[a[0]].k == 's') && f.p(a[0]+1, ":") {
				k := prefix + "." + f.s(a[0])
				if f.p(a[0]+2, "{") {
					object(k, a[0]+2, global)
					continue
				}
				c := tsConst{f, a[0] + 2, a[1]}
				if global {
					fe.consts[k] = append(fe.consts[k], c)
				}
				fc[k] = c
			}
		}
	}
	n := len(f.toks)
	for i := 0; i < n; i++ {
		t := f.toks[i]
		if t.k != 'i' {
			continue
		}
		switch t.s {
		case "class":
			if f.p(i-1, ".") {
				continue
			}
			c := fe.classAt(f, i)
			if c == nil {
				continue
			}
			if c.name != "" {
				if _, dup := fe.fclasses[f][c.name]; !dup {
					fe.fclasses[f][c.name] = c
				}
				fe.classes[c.name] = append(fe.classes[c.name], c)
				scopes = append(scopes, scope{c.name, c.brace, f.end(c.brace), f.depth[c.brace] + 1})
			}
			fe.anon[f][i] = c
			// implements X, Y: Shape implementations
			for j := i + 1; j < c.brace; j++ {
				if f.is(j, 'i', "implements") {
					for k := j + 1; k < c.brace; k++ {
						if f.ident(k) && shapeName.MatchString(f.s(k)) && c.name != "" {
							fe.impls[f.s(k)] = append(fe.impls[f.s(k)], c.name+" ("+f.rel+")")
						}
					}
				}
			}
		case "namespace", "enum":
			if f.ident(i+1) && f.p(i+2, "{") {
				scopes = append(scopes, scope{f.s(i + 1), i + 2, f.end(i + 2), f.depth[i+2] + 1})
				if t.s == "enum" {
					for _, a := range f.args(i + 2) {
						if a[1]-a[0] >= 3 && f.ident(a[0]) && f.p(a[0]+1, "=") {
							k := f.s(i+1) + "." + f.s(a[0])
							if q, ok := qual(i); ok && q != "" {
								k = q + "." + k
							}
							c := tsConst{f, a[0] + 2, a[1]}
							fe.consts[k] = append(fe.consts[k], c)
							fc[k] = c
							if _, ok := fc[f.s(i+1)+"."+f.s(a[0])]; !ok {
								fc[f.s(i+1)+"."+f.s(a[0])] = c
							}
						}
					}
				}
			}
		case "const", "let", "var", "static", "readonly":
			j := i + 1
			for f.is(j, 'i', "readonly") || f.is(j, 'i', "static") {
				j++
			}
			if t.s == "static" || t.s == "readonly" {
				if f.is(i-1, 'i', "static") || f.is(i-1, 'i', "readonly") {
					continue // handled from the first modifier
				}
			}
			if !f.ident(j) {
				continue
			}
			name := f.s(j)
			k := j + 1
			if f.p(k, ":") { // type annotation up to '='
				for k < n && !f.p(k, "=") && !f.p(k, ";") {
					if f.p(k, "(") || f.p(k, "[") || f.p(k, "{") {
						k = f.end(k)
					}
					k++
				}
			}
			if !f.p(k, "=") {
				continue
			}
			lo := k + 1
			hi := lo
			for hi < n && !f.p(hi, ";") && !f.p(hi, ",") && !(f.p(hi, "}") && f.depth[hi] < f.depth[lo]) {
				if f.p(hi, "(") || f.p(hi, "[") || f.p(hi, "{") {
					hi = f.end(hi)
				}
				hi++
				if hi < n && f.toks[hi].line != f.toks[hi-1].line && !f.p(hi, "+") && !f.p(hi-1, "+") && !f.p(hi, ".") {
					break
				}
			}
			q, ok := qual(i)
			if t.s == "static" || t.s == "readonly" {
				if !ok || q == "" {
					continue
				}
			} else if !ok {
				q = ""
			}
			if oe := f.end(lo); f.p(lo, "{") && (oe == hi-1 || f.is(oe+1, 'i', "as") || f.is(oe+1, 'i', "satisfies")) {
				prefix := name
				if q != "" && (t.s == "static" || t.s == "readonly") {
					prefix = q + "." + name
				}
				object(prefix, lo, ok)
				continue
			}
			record(q, name, lo, hi, ok)
		case "registerSingleton":
			if !f.p(i+1, "(") || f.callDecl(i, i+1) || f.p(i-1, ".") {
				continue
			}
			a := f.args(i + 1)
			if len(a) >= 2 && f.ident(a[0][0]) {
				impl := f.text(a[1][0], a[1][1])
				if f.is(a[1][0], 'i', "new") && f.is(a[1][0]+1, 'i', "SyncDescriptor") && f.p(a[1][0]+2, "(") {
					if b := f.args(a[1][0] + 2); len(b) > 0 {
						impl = f.text(b[0][0], b[0][1])
					}
				}
				id := f.text(a[0][0], a[0][1])
				fe.singles[id] = append(fe.singles[id], fmt.Sprintf("%s (%s:%d)", impl, f.rel, t.line))
			}
		}
	}
}

// classAt parses the class header at the 'class' token i.
func (fe *tsFront) classAt(f *tsFile, i int) *tsClass {
	c := &tsClass{f: f, at: i}
	j := i + 1
	if f.ident(j) && f.s(j) != "extends" && f.s(j) != "implements" {
		c.name = f.s(j)
		j++
	}
	angle := 0
	for ; j < len(f.toks); j++ {
		switch {
		case f.p(j, "<"):
			angle++
		case f.p(j, ">"):
			if angle > 0 {
				angle--
			}
		case f.p(j, "=>"):
		case f.p(j, "(") || f.p(j, "["):
			j = f.end(j)
		case f.p(j, ";"):
			return nil
		case f.p(j, "{"):
			if angle > 0 {
				j = f.end(j)
				continue
			}
			c.brace = j
			return c
		case f.is(j, 'i', "extends") && c.base == "" && angle == 0:
			k := j + 1
			for f.ident(k) && f.p(k+1, ".") {
				k += 2
			}
			if f.ident(k) {
				c.base = f.s(k)
			}
		}
	}
	return nil
}

// eval resolves a string-valued expression: literals, templates, constant
// references (qualified or not) and '+' concatenations.
func (fe *tsFront) eval(f *tsFile, lo, hi, depth int) (string, bool) {
	if depth > 6 || lo >= hi {
		return "", false
	}
	// strip "as const", "as string" and a wrapping (...)
	if hi-lo > 2 && f.is(hi-2, 'i', "as") {
		hi -= 2
	}
	if f.p(lo, "(") && f.end(lo) == hi-1 {
		return fe.eval(f, lo+1, hi-1, depth+1)
	}
	var out strings.Builder
	start := lo
	for i := lo; i <= hi; i++ {
		if i < hi && !f.p(i, "+") {
			if f.p(i, "(") || f.p(i, "[") {
				i = f.end(i)
			}
			continue
		}
		v, ok := fe.term(f, start, i, depth)
		if !ok {
			return "", false
		}
		out.WriteString(v)
		start = i + 1
	}
	return out.String(), true
}

func (fe *tsFront) term(f *tsFile, lo, hi, depth int) (string, bool) {
	if hi-lo == 1 {
		switch f.toks[lo].k {
		case 's', 't':
			return f.toks[lo].s, true
		}
	}
	// a dotted identifier chain
	var parts []string
	for i := lo; i < hi; i++ {
		if (i-lo)%2 == 0 {
			if !f.ident(i) {
				return "", false
			}
			parts = append(parts, f.s(i))
		} else if !f.p(i, ".") {
			return "", false
		}
	}
	if len(parts) == 0 || (hi-lo)%2 == 0 {
		return "", false
	}
	v, ok := fe.lookup(f, strings.Join(parts, "."), depth)
	if !ok && len(parts) > 1 && fe.nsImports[f][parts[0]] {
		// import * as Constants from '...': Constants.X.Y names X.Y there
		v, ok = fe.lookup(f, strings.Join(parts[1:], "."), depth)
	}
	return v, ok
}

func (fe *tsFront) lookup(f *tsFile, name string, depth int) (string, bool) {
	if c, ok := fe.fconsts[f][name]; ok {
		if v, ok := fe.eval(c.f, c.lo, c.hi, depth+1); ok {
			return v, true
		}
	}
	defs := fe.consts[name]
	val, found := "", false
	for _, c := range defs {
		v, ok := fe.eval(c.f, c.lo, c.hi, depth+1)
		if !ok {
			continue
		}
		if found && v != val {
			return "", false // ambiguous
		}
		val, found = v, true
	}
	return val, found
}

// classID finds the id a class passes to its super constructor, following
// base classes without a constructor of their own.
func (fe *tsFront) classID(c *tsClass, depth int) (string, bool) {
	v, _, ok := fe.classIDExpr(c, depth)
	return v, ok
}

// idExpr matches an id-like argument: X.ID, X.id, FOO_ID, fooId.
var idExpr = regexp.MustCompile(`(\.ID|\.id|_ID|Id|^ID)$`)

// classIDExpr also returns the id expression's text when it can't be
// resolved, so a registration can be named by it.
func (fe *tsFront) classIDExpr(c *tsClass, depth int) (string, string, bool) {
	if c == nil || depth > 5 {
		return "", "", false
	}
	f := c.f
	static := func() (string, bool) {
		if c.name == "" {
			return "", false
		}
		if v, ok := fe.lookup(f, c.name+".ID", 0); ok {
			return v, true
		}
		return fe.lookup(f, c.name+".id", 0)
	}
	body := c.brace
	for i := body + 1; i < f.end(body); i++ {
		if f.depth[i] != f.depth[body]+1 || !f.is(i, 'i', "constructor") || !f.p(i+1, "(") {
			continue
		}
		cl := f.end(i + 1)
		if !f.p(cl+1, "{") {
			break
		}
		for j := cl + 1; j < f.end(cl+1); j++ {
			if !f.is(j, 'i', "super") || !f.p(j+1, "(") {
				continue
			}
			a := f.args(j + 1)
			for _, x := range a {
				if lo, hi, ok := f.objKey(x[0], "id"); ok {
					if v, ok := fe.eval(f, lo, hi, 0); ok {
						return v, "", true
					}
					return "", f.text(lo, hi), false
				}
			}
			for _, x := range a {
				if t := f.text(x[0], x[1]); idExpr.MatchString(t) {
					if v, ok := fe.eval(f, x[0], x[1], 0); ok {
						return v, "", true
					}
					return "", t, false
				}
			}
			if v, ok := static(); ok {
				return v, "", true
			}
			return "", "", false
		}
		break
	}
	if v, ok := static(); ok {
		return v, "", true
	}
	return fe.classIDExpr(fe.class(f, c.base), depth+1)
}

// class resolves a class name, preferring the given file.
func (fe *tsFront) class(f *tsFile, name string) *tsClass {
	if name == "" {
		return nil
	}
	if c := fe.fclasses[f][name]; c != nil {
		return c
	}
	if cs := fe.classes[name]; len(cs) == 1 {
		return cs[0]
	}
	return nil
}

// ---------------------------------------------------------------- entries

func (fe *tsFront) entries() []Entry {
	var out []Entry
	for _, f := range fe.files {
		out = append(out, fe.fileEntries(f)...)
		if strings.HasSuffix(f.rel, "/extHost.protocol.ts") {
			out = append(out, fe.shapes(f)...)
		}
		if e, ok := fe.processMain(f); ok {
			out = append(out, e)
		}
	}
	for _, d := range fe.dts {
		out = append(out, scanVSCodeDTS(d[0], d[1])...)
	}
	for i, p := range fe.pkgs {
		out = append(out, fe.packageJSON(p, fe.pkgRels[i])...)
	}
	if len(fe.rust) > 0 {
		out = append(out, scanClap(fe.rust)...)
	}
	return out
}

// constLike reports whether an unresolved id expression names a constant
// (worth listing under its expression) rather than a parameter of a helper.
func constLike(expr string) bool {
	if expr == "" || strings.HasPrefix(expr, "this.") {
		return false
	}
	c := expr[0]
	return (c >= 'A' && c <= 'Z') || c == '_'
}

func (fe *tsFront) fileEntries(f *tsFile) []Entry {
	var out []Entry
	n := len(f.toks)
	add := func(kind, name string, i, endTok int, via, detail string) {
		e := Entry{Kind: kind, Name: name, File: f.rel, Line: f.line(i), Via: via, Detail: detail}
		if endTok > i && f.line(endTok) > e.Line {
			e.EndLine = f.line(endTok)
		}
		out = append(out, e)
	}
	// idOf resolves an id expression; ok=false drops the entry.
	idOf := func(lo, hi int) (string, string, bool) {
		if v, ok := fe.eval(f, lo, hi, 0); ok {
			return v, "", true
		}
		expr := f.text(lo, hi)
		if constLike(expr) {
			return expr, "id unresolved", true
		}
		return "", "", false
	}
	for i := 0; i < n; i++ {
		t := f.toks[i]
		if t.k != 'i' {
			continue
		}
		open := i + 1
		if f.p(open, "<") && t.s != "createDecorator" {
			open = f.skipAngles(open)
		}
		switch t.s {
		case "registerAction2", "registerEditorAction", "registerEditorCommand", "registerInstantiatedEditorAction", "registerMultiEditorAction":
			if !f.p(open, "(") || f.callDecl(i, open) || f.p(i-1, ".") {
				continue
			}
			a := f.args(open)
			if len(a) == 0 {
				continue
			}
			via := map[string]string{"registerAction2": "action2", "registerEditorAction": "editor-action", "registerEditorCommand": "editor-command",
				"registerInstantiatedEditorAction": "editor-action", "registerMultiEditorAction": "editor-action"}[t.s]
			lo := a[0][0]
			if f.is(lo, 'i', "new") {
				lo++
			}
			var c *tsClass
			id, detail, ok := "", "", false
			switch {
			case f.is(lo, 'i', "class"):
				c = fe.anon[f][lo]
				if c != nil {
					var expr string
					id, expr, ok = fe.classIDExpr(c, 0)
					detail = "class " + c.name
					if c.name == "" {
						detail = "anonymous " + c.base + " subclass"
					}
					if !ok && constLike(expr) {
						id, ok = expr, true
						detail += ", id unresolved"
					}
				}
			case f.ident(lo):
				k := lo
				for f.ident(k) && f.p(k+1, ".") {
					k += 2
				}
				name := f.s(k)
				c = fe.class(f, name)
				// new Ctor({ id: ... }) passes the id directly
				if f.p(k+1, "(") {
					if b := f.args(k + 1); len(b) > 0 {
						if vlo, vhi, has := f.objKey(b[0][0], "id"); has {
							id, detail, ok = idOf(vlo, vhi)
							if ok {
								detail = strings.TrimSpace("class " + name + " " + detail)
							}
							break
						}
					}
				}
				detail = "class " + name
				if c != nil {
					id, ok = fe.classID(c, 0)
					if c.f != f {
						detail += fmt.Sprintf(" (%s:%d)", c.f.rel, c.f.line(c.at))
					}
				}
				if !ok {
					id, ok = name, true
					detail += ", id unresolved"
				}
			}
			if !ok || id == "" {
				if c != nil && c.name != "" {
					id, ok = c.name, true
					detail += ", id unresolved"
				} else {
					continue
				}
			}
			add(KindVSCommand, id, i, f.end(open), via, detail)
		case "registerCommand", "registerCommandAndKeybindingRule":
			rcv := f.receiver(i)
			if !f.p(open, "(") || f.callDecl(i, open) {
				continue
			}
			if (t.s == "registerCommand" && rcv != "CommandsRegistry") || (t.s == "registerCommandAndKeybindingRule" && rcv != "KeybindingsRegistry") {
				continue
			}
			a := f.args(open)
			if len(a) == 0 {
				continue
			}
			via := "commands-registry"
			if rcv == "KeybindingsRegistry" {
				via = "keybinding-rule"
			}
			var id, detail string
			var ok bool
			if vlo, vhi, has := f.objKey(a[0][0], "id"); has {
				id, detail, ok = idOf(vlo, vhi)
				if hlo, hhi, has := f.objKey(a[0][0], "handler"); has {
					detail = strings.TrimSpace(detail + " handler " + handlerSummary(f, hlo, hhi))
				}
			} else {
				id, detail, ok = idOf(a[0][0], a[0][1])
				if len(a) > 1 {
					detail = strings.TrimSpace(detail + " handler " + handlerSummary(f, a[1][0], a[1][1]))
				}
			}
			if ok {
				add(KindVSCommand, id, i, f.end(open), via, strings.TrimSpace(detail))
			}
		case "registerWorkbenchContribution2", "registerWorkbenchContribution", "registerEditorContribution":
			if !f.p(open, "(") || f.callDecl(i, open) {
				continue
			}
			if t.s == "registerWorkbenchContribution" && !f.p(i-1, ".") || t.s != "registerWorkbenchContribution" && f.p(i-1, ".") {
				continue
			}
			a := f.args(open)
			ci := 0
			via := "contribution-registry"
			if t.s != "registerWorkbenchContribution" {
				ci = 1
				via = "workbench-contribution2"
				if t.s == "registerEditorContribution" {
					via = "editor-contribution"
				}
			}
			if len(a) <= ci {
				continue
			}
			cls := f.text(a[ci][0], a[ci][1])
			var parts []string
			if ci == 1 {
				if v, ok := fe.eval(f, a[0][0], a[0][1], 0); ok {
					parts = append(parts, "id "+v)
				}
			}
			if len(a) > ci+1 {
				parts = append(parts, f.text(a[ci+1][0], a[ci+1][1]))
			}
			add(KindContribution, cls, i, 0, via, strings.Join(parts, ", "))
		case "registerExtensionPoint":
			if f.receiver(i) != "ExtensionsRegistry" || !f.p(open, "(") || f.callDecl(i, open) {
				continue
			}
			if a := f.args(open); len(a) > 0 {
				if lo, hi, ok := f.objKey(a[0][0], "extensionPoint"); ok {
					if v, ok := fe.eval(f, lo, hi, 0); ok {
						add(KindExtPoint, v, i, f.end(open), "extension-point", "")
					}
				} else if a[0][1]-a[0][0] == 1 && f.ident(a[0][0]) {
					// a descriptor constant: const d = { extensionPoint: '...' }
					if v, ok := fe.lookup(f, f.s(a[0][0])+".extensionPoint", 0); ok {
						add(KindExtPoint, v, i, f.end(open), "extension-point", "descriptor "+f.s(a[0][0]))
					}
				}
			}
		case "createDecorator":
			if !f.p(open, "<") || f.p(i-1, ".") {
				continue
			}
			j := open
			for j < n && !f.p(j, ">") {
				j++
			}
			if !f.p(j+1, "(") || f.callDecl(i, j+1) {
				continue
			}
			a := f.args(j + 1)
			if len(a) != 1 {
				continue
			}
			sid, ok := fe.eval(f, a[0][0], a[0][1], 0)
			if !ok {
				continue
			}
			name := f.text(open+1, j)
			if f.p(i-1, "=") && f.ident(i-2) {
				name = f.s(i - 2)
			}
			detail := "id " + sid
			if impls := fe.singles[name]; len(impls) > 0 {
				detail += "; registerSingleton " + strings.Join(uniq(impls), ", ")
			}
			add(KindService, name, i, 0, "create-decorator", detail)
		case "registerChannel":
			if !(f.p(i-1, ".") || f.p(i-1, "?.")) || !f.p(open, "(") || f.callDecl(i, open) {
				continue
			}
			a := f.args(open)
			if len(a) != 2 {
				continue
			}
			name, extra, ok := idOf(a[0][0], a[0][1])
			if !ok {
				continue
			}
			detail := strings.TrimSpace(extra + " channel " + f.text(a[1][0], a[1][1]))
			add(KindIPC, name, i, f.end(open), "register-channel", detail)
		case "extHostNamedCustomer", "extHostCustomer":
			if !f.p(i-1, "@") {
				continue
			}
			k := i + 1
			arg := ""
			if f.p(k, "(") {
				arg = f.text(k+1, f.end(k))
				k = f.end(k) + 1
			}
			for k < n && k < i+12 && !f.is(k, 'i', "class") {
				k++
			}
			if f.is(k, 'i', "class") && f.ident(k+1) {
				c := fe.anon[f][k]
				end := 0
				if c != nil {
					end = f.end(c.brace)
				}
				add(KindExtHostCust, f.s(k+1), i-1, end, t.s, arg)
			}
		}
	}
	return out
}

// handlerSummary names a command handler: a function reference, or the
// kind of inline function.
func handlerSummary(f *tsFile, lo, hi int) string {
	switch {
	case f.is(lo, 'i', "async") && (f.is(lo+1, 'i', "function") || f.p(lo+1, "(")):
		return "(inline async function)"
	case f.is(lo, 'i', "function") || f.p(lo, "(") || (f.ident(lo) && f.p(lo+1, "=>")):
		return "(inline function)"
	}
	return f.text(lo, hi)
}

// shapeName matches the RPC shape interfaces (MainThreadXShape,
// ExtHostXShape2, IExtHostEditorTabsShape, IChatAgentProgressShape).
var shapeName = regexp.MustCompile(`^I?[A-Z]\w*Shape\d*$`)

// shapes lists the $methods of the RPC shape interfaces.
func (fe *tsFront) shapes(f *tsFile) []Entry {
	var out []Entry
	for i := 0; i+2 < len(f.toks); i++ {
		if !f.is(i, 'i', "interface") || !f.ident(i+1) {
			continue
		}
		name := f.s(i + 1)
		if !shapeName.MatchString(name) {
			continue
		}
		j := i + 2
		for j < len(f.toks) && !f.p(j, "{") {
			j++
		}
		detail := ""
		if impl := fe.impls[name]; len(impl) > 0 {
			detail = "implemented by " + strings.Join(uniq(impl), ", ")
		}
		body := j
		for k := body + 1; k < f.end(body); k++ {
			if f.depth[k] != f.depth[body]+1 {
				continue
			}
			if f.ident(k) && strings.HasPrefix(f.s(k), "$") && (f.p(k+1, "(") || f.p(k+1, "<") || f.p(k+1, "?") && f.p(k+2, "(")) && (f.p(k-1, ";") || f.p(k-1, "{") || f.p(k-1, "}")) {
				out = append(out, Entry{Kind: KindExtHostRPC, Name: name + "." + f.s(k), File: f.rel, Line: f.line(k), Via: "rpc-shape", Detail: detail})
			}
		}
		i = f.end(body)
	}
	return out
}

var processStem = regexp.MustCompile(`(^main$|^cli$|^server-main$|^server-cli$|Main$|\.main$|\.workerMain$|^extensionHostProcess$|^bootstrap-fork$)`)

// processMain recognises a process entry file: an entry-like name and
// top-level startup code (a call statement, an exported main, or a bundle of
// side-effect imports).
func (fe *tsFront) processMain(f *tsFile) (Entry, bool) {
	stem := strings.TrimSuffix(filepath.Base(f.rel), ".ts")
	if !processStem.MatchString(stem) || strings.HasSuffix(stem, ".common.main") {
		return Entry{}, false
	}
	if strings.Count(f.rel, "/") == 1 && stem != "main" && stem != "cli" && stem != "server-main" && stem != "server-cli" && stem != "bootstrap-fork" {
		return Entry{}, false
	}
	sideImports, call, mainFn := 0, -1, -1
	skip := map[string]bool{"import": true, "export": true, "class": true, "function": true, "interface": true, "type": true,
		"const": true, "let": true, "var": true, "enum": true, "declare": true, "abstract": true, "namespace": true, "async": true}
	for i := 0; i < len(f.toks); i++ {
		if f.depth[i] != 0 {
			continue
		}
		start := i == 0 || f.p(i-1, ";") || (f.p(i-1, "}") && f.depth[i-1] == 0)
		if !start {
			continue
		}
		t := f.toks[i]
		switch {
		case t.k == 'i' && t.s == "import" && i+1 < len(f.toks) && f.toks[i+1].k == 's':
			sideImports++
		case t.k == 'i' && t.s == "export" && (f.is(i+1, 'i', "function") && f.is(i+2, 'i', "main") || f.is(i+1, 'i', "async") && f.is(i+3, 'i', "main")):
			if mainFn < 0 {
				mainFn = i
			}
		case t.k == 'i' && t.s == "await", t.k == 'i' && t.s == "if", t.k == 'p' && t.s == "(":
			if call < 0 {
				call = i
			}
		case t.k == 'i' && !skip[t.s] && (f.p(i+1, "(") || f.p(i+1, ".")):
			if call < 0 {
				call = i
			}
		}
	}
	name := strings.TrimSuffix(f.rel, ".ts")
	switch {
	case call >= 0:
		return Entry{Kind: KindProcessMain, Name: name, File: f.rel, Line: f.line(call), Via: "top-level-startup"}, true
	case mainFn >= 0:
		return Entry{Kind: KindProcessMain, Name: name, File: f.rel, Line: f.line(mainFn), Via: "export-main"}, true
	case sideImports >= 3:
		return Entry{Kind: KindProcessMain, Name: name, File: f.rel, Line: 1, Via: "bundle-entry", Detail: fmt.Sprintf("%d side-effect imports", sideImports)}, true
	}
	return Entry{}, false
}

// scanVSCodeDTS lists the functions of the API namespaces in vscode.d.ts.
func scanVSCodeDTS(path, rel string) []Entry {
	src, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	f := parseTS(rel, src)
	var out []Entry
	var walk func(prefix string, lo, hi int)
	walk = func(prefix string, lo, hi int) {
		for i := lo; i < hi; i++ {
			if f.is(i, 'i', "namespace") && f.ident(i+1) && f.p(i+2, "{") {
				walk(prefix+"."+f.s(i+1), i+3, f.end(i+2))
				i = f.end(i + 2)
				continue
			}
			if f.p(i, "{") || f.p(i, "(") {
				if prefix != "vscode" && f.p(i, "{") {
					i = f.end(i)
				} else if f.p(i, "(") {
					i = f.end(i)
				}
				continue
			}
			if prefix != "vscode" && f.is(i, 'i', "function") && f.is(i-1, 'i', "export") && f.ident(i+1) {
				out = append(out, Entry{Kind: KindExtAPI, Name: prefix + "." + f.s(i+1), File: rel, Line: f.line(i), Via: "vscode-dts"})
			}
		}
	}
	for i := 0; i+2 < len(f.toks); i++ {
		if f.is(i, 'i', "module") && f.is(i+1, 's', "vscode") && f.p(i+2, "{") {
			walk("vscode", i+3, f.end(i+2))
			break
		}
	}
	return out
}

// packageJSON lists a built-in extension's commands and activation events.
func (fe *tsFront) packageJSON(path, rel string) []Entry {
	src, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var pkg struct {
		Name             string          `json:"name"`
		ActivationEvents []string        `json:"activationEvents"`
		Contributes      json.RawMessage `json:"contributes"`
	}
	if json.Unmarshal(src, &pkg) != nil {
		return nil
	}
	ext := strings.Split(rel, "/")[1]
	var contrib struct {
		Commands json.RawMessage `json:"commands"`
	}
	_ = json.Unmarshal(pkg.Contributes, &contrib)
	type cmd struct {
		Command string `json:"command"`
		Title   any    `json:"title"`
	}
	var cmds []cmd
	if json.Unmarshal(contrib.Commands, &cmds) != nil {
		var one cmd
		if json.Unmarshal(contrib.Commands, &one) == nil && one.Command != "" {
			cmds = []cmd{one}
		}
	}
	lineAt := func(off int) int { return bytes.Count(src[:off], []byte("\n")) + 1 }
	var out []Entry
	cmdsAt := bytes.Index(src, []byte(`"commands"`))
	for _, c := range cmds {
		if c.Command == "" {
			continue
		}
		re := regexp.MustCompile(`"command"\s*:\s*"` + regexp.QuoteMeta(c.Command) + `"`)
		ln := 0
		if cmdsAt >= 0 {
			if loc := re.FindIndex(src[cmdsAt:]); loc != nil {
				ln = lineAt(cmdsAt + loc[0])
			}
		}
		detail := "extension " + pkg.Name
		if h, ok := fe.extCmds[ext+"\x00"+c.Command]; ok {
			detail += "; handler " + h
		}
		out = append(out, Entry{Kind: KindExtCommand, Name: c.Command, File: rel, Line: ln, Via: "package-json", Detail: detail})
	}
	actAt := bytes.Index(src, []byte(`"activationEvents"`))
	for _, a := range pkg.ActivationEvents {
		ln := 0
		if actAt >= 0 {
			if k := bytes.Index(src[actAt:], []byte(`"`+a+`"`)); k >= 0 {
				ln = lineAt(actAt + k)
			}
		}
		out = append(out, Entry{Kind: KindActivation, Name: pkg.Name + " " + a, File: rel, Line: ln, Via: "package-json"})
	}
	return out
}

// ---------------------------------------------------------------- Rust clap

// scanClap lists clap derive subcommands: variants of #[derive(Subcommand)]
// enums, named in kebab case (or by #[clap(name = ...)]) and prefixed with
// the command path that reaches them through #[clap(subcommand)] fields.
func scanClap(files [][2]string) []Entry {
	type variant struct {
		name, typ, file string
		line            int
	}
	enums := map[string][]variant{}
	enumOrder := []string{}
	structSub := map[string]string{} // Args struct -> subcommand enum
	for _, fp := range files {
		src, err := os.ReadFile(fp[0])
		if err != nil || !bytes.Contains(src, []byte("Subcommand")) {
			continue
		}
		toks := tslex(src) // Rust lifetimes are unterminated quotes; tslex keeps lines right
		m := jmatch(toks)
		for i := 0; i+3 < len(toks); i++ {
			// #[derive(..., Subcommand, ...)]
			if toks[i].s != "#" || toks[i+1].s != "[" {
				continue
			}
			attrEnd := m[i+1]
			if attrEnd < 0 || attrEnd >= len(toks) {
				continue
			}
			derive, sub := false, false
			for k := i + 2; k < attrEnd; k++ {
				if toks[k].s == "derive" {
					derive = true
				}
				if toks[k].s == "Subcommand" {
					sub = true
				}
			}
			if !derive {
				continue
			}
			k := attrEnd + 1
			for k+1 < len(toks) && toks[k].s == "#" && toks[k+1].s == "[" && m[k+1] > 0 {
				k = m[k+1] + 1
			}
			for k < len(toks) && (toks[k].s == "pub" || toks[k].s == "(" || toks[k].s == "crate" || toks[k].s == ")") {
				k++
			}
			if k+2 >= len(toks) {
				continue
			}
			kw, name := toks[k].s, toks[k+1].s
			b := k + 2
			for b < len(toks) && toks[b].s != "{" && toks[b].s != ";" {
				b++
			}
			if b >= len(toks) || toks[b].s != "{" {
				continue
			}
			end := m[b]
			if kw == "enum" && sub {
				enumOrder = append(enumOrder, name)
				over := ""
				for j := b + 1; j < end; j++ {
					if toks[j].s == "#" && toks[j+1].s == "[" {
						ae := m[j+1]
						for q := j + 2; q+2 < ae; q++ {
							if toks[q].s == "name" && toks[q+1].s == "=" && toks[q+2].k == 's' {
								over = toks[q+2].s
							}
						}
						j = ae
						continue
					}
					if toks[j].k == 'i' && (toks[j-1].s == "{" || toks[j-1].s == "," || toks[j-1].s == "]" || toks[j-1].s == "}" && m[j-1] < j) {
						v := variant{name: kebab(toks[j].s), file: fp[1], line: toks[j].line}
						if over != "" {
							v.name = over
						}
						over = ""
						if j+1 < end && toks[j+1].s == "(" {
							// the payload type, unwrapping Box<...>
							for q := j + 2; q < m[j+1]; q++ {
								if toks[q].k == 'i' && toks[q].s != "Box" {
									v.typ = toks[q].s
									break
								}
							}
							j = m[j+1]
						} else if j+1 < end && toks[j+1].s == "{" {
							j = m[j+1]
						}
						enums[name] = append(enums[name], v)
					}
				}
			} else if kw == "struct" {
				// #[clap(subcommand)] field: Option<Enum> or Enum
				for j := b + 1; j+4 < end; j++ {
					if toks[j].s == "#" && toks[j+1].s == "[" {
						ae := m[j+1]
						isSub := false
						for q := j + 2; q < ae; q++ {
							if toks[q].s == "subcommand" {
								isSub = true
							}
						}
						if isSub {
							for q := ae + 1; q < end && toks[q].s != ","; q++ {
								if toks[q].k == 'i' && toks[q].s != "pub" && toks[q].s != "Option" && toks[q+1].s != ":" {
									structSub[name] = toks[q].s
								}
							}
						}
						j = ae
					}
				}
			}
		}
	}
	// prefixes: enum reached from a variant whose payload struct has a subcommand field
	prefix := map[string]string{}
	var resolve func(e string, depth int) string
	resolve = func(e string, depth int) string {
		if p, ok := prefix[e]; ok || depth > 6 {
			return p
		}
		for _, parent := range enumOrder {
			for _, v := range enums[parent] {
				if v.typ != "" && (structSub[v.typ] == e || v.typ == e) && parent != e {
					p := strings.TrimSpace(resolve(parent, depth+1) + " " + v.name)
					prefix[e] = p
					return p
				}
			}
		}
		prefix[e] = ""
		return ""
	}
	var out []Entry
	for _, e := range enumOrder {
		p := resolve(e, 0)
		for _, v := range enums[e] {
			name := strings.Join(strings.Fields("code "+p+" "+v.name), " ")
			out = append(out, Entry{Kind: KindCLI, Name: name, File: v.file, Line: v.line, Via: "clap-subcommand", Detail: e})
		}
	}
	return out
}

func kebab(s string) string {
	var b strings.Builder
	for i, r := range s {
		if r >= 'A' && r <= 'Z' {
			if i > 0 {
				b.WriteByte('-')
			}
			b.WriteRune(r - 'A' + 'a')
		} else {
			b.WriteRune(r)
		}
	}
	return b.String()
}

// sortedKeys returns a map's keys in order.
func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

package main

// The python-gpu plugin: entry points of a Python serving engine with C++,
// CUDA and Triton kernels (vLLM style). Python is lexed (comments dropped,
// strings opaque, logical lines and indentation kept) into a block model of
// classes and functions; C++ and CUDA go through jlex. Heuristics: FastAPI
// routes, CLISubcommand classes, the public engine API exported by the
// package, engine and worker RPC targets invoked by name, busy and step
// loops, torch custom ops (TORCH_LIBRARY schemas, Python registrations and
// the Python wrappers of C++ ops), CUDA __global__ kernels, Triton kernels,
// model registry tables and plugin entry points.

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strings"
)

// python-gpu entry kinds. FastAPI routes reuse KindHTTP and CLISubcommand
// classes reuse KindCLI.
const (
	KindPyAPI     = "python-api"       // public methods of the engine classes the package exports
	KindEngineRPC = "engine-rpc"       // collective_rpc / call_utility targets, by method name
	KindBusyLoop  = "busy-loop"        // engine busy loops, thread-target loops and step functions
	KindTorchOp   = "torch-op"         // torch custom ops: TORCH_LIBRARY defs and Python registrations
	KindOpWrapper = "torch-op-wrapper" // Python functions wrapping torch.ops.<_C ns>.<op>
	KindCUDA      = "cuda-kernel"      // CUDA __global__ kernels
	KindTriton    = "triton-kernel"    // @triton.jit kernels
	KindModel     = "model-registry"   // model architecture registry entries
	KindPlugin    = "plugin"           // entry points, plugin groups and built-in platform plugins
)

// ---------------------------------------------------------------- model

type pyBlock struct {
	kind, name    string // kind "def" or "class"
	owner         *pyBlock
	line, endLine int
	lo, hi        int // tokens of the block, header to last body token
	indent        int
	decos         [][2]int // decorator expressions (after '@')
	bases         []string // class bases, last identifier of each
	f             *pyFile
}

func (d *pyBlock) qual() string {
	if d.owner != nil {
		return d.owner.qual() + "." + d.name
	}
	return d.name
}

type pyLine struct {
	lo, hi int // tokens, hi exclusive of the 'l' token
	indent int
}

type pyFile struct {
	rel    string
	toks   []pyTok
	m      []int
	lines  []pyLine
	defs   []*pyBlock
	lineOf []int // logical line index of each token
}

func parsePy(rel string, src []byte) *pyFile {
	f := &pyFile{rel: rel, toks: pylex(src)}
	jt := make([]jtok, len(f.toks))
	for i, t := range f.toks {
		jt[i] = t.jtok
	}
	f.m = jmatch(jt)
	f.lineOf = make([]int, len(f.toks))
	lo := 0
	for i, t := range f.toks {
		f.lineOf[i] = len(f.lines)
		if t.k == 'l' {
			if i > lo {
				f.lines = append(f.lines, pyLine{lo, i, f.toks[lo].col})
			}
			lo = i + 1
		}
	}
	var stack []*pyBlock
	var pendingDecos [][2]int
	for li, l := range f.lines {
		for len(stack) > 0 && l.indent <= stack[len(stack)-1].indent {
			stack = stack[:len(stack)-1]
		}
		first := f.toks[l.lo]
		if first.k == 'p' && first.s == "@" {
			pendingDecos = append(pendingDecos, [2]int{l.lo + 1, l.hi})
			continue
		}
		j := l.lo
		if first.k == 'i' && first.s == "async" {
			j++
		}
		if f.is(j, 'i', "def") || f.is(j, 'i', "class") {
			if !f.ident(j + 1) {
				pendingDecos = nil
				continue
			}
			d := &pyBlock{kind: f.toks[j].s, name: f.toks[j+1].s, line: first.line, lo: l.lo, indent: l.indent, decos: pendingDecos, f: f}
			if len(pendingDecos) > 0 {
				d.line = f.toks[pendingDecos[0][0]-1].line
			}
			if len(stack) > 0 {
				d.owner = stack[len(stack)-1]
			}
			if d.kind == "class" && f.p(j+2, "(") {
				for _, a := range f.args(j + 2) {
					if f.is(a[1]-2, 'p', "=") || f.is(a[0]+1, 'p', "=") {
						continue // metaclass=...
					}
					k := a[1] - 1
					if f.p(k, "]") { // Generic[T]
						k = f.m[k] - 1
					}
					if f.ident(k) {
						d.bases = append(d.bases, f.toks[k].s)
					}
				}
			}
			// block end: the last line before one indented at or left of the header
			end := li
			for k := li + 1; k < len(f.lines); k++ {
				if f.lines[k].indent <= l.indent {
					break
				}
				end = k
			}
			d.hi = f.lines[end].hi
			d.endLine = f.toks[f.lines[end].hi-1].line
			f.defs = append(f.defs, d)
			stack = append(stack, d)
		}
		pendingDecos = nil
	}
	return f
}

func (f *pyFile) is(i int, k byte, s string) bool {
	return i >= 0 && i < len(f.toks) && f.toks[i].k == k && f.toks[i].s == s
}
func (f *pyFile) p(i int, s string) bool { return f.is(i, 'p', s) }
func (f *pyFile) ident(i int) bool       { return i >= 0 && i < len(f.toks) && f.toks[i].k == 'i' }
func (f *pyFile) s(i int) string {
	if i < 0 || i >= len(f.toks) {
		return ""
	}
	return f.toks[i].s
}

func (f *pyFile) end(i int) int {
	if i < 0 || i >= len(f.m) || f.m[i] < 0 {
		return i
	}
	return f.m[i]
}

// args splits the bracketed list opened at open into top-level ranges.
func (f *pyFile) args(open int) [][2]int {
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

// kwarg finds name=value among args.
func (f *pyFile) kwarg(args [][2]int, name string) (int, int, bool) {
	for _, a := range args {
		if a[1]-a[0] >= 3 && f.is(a[0], 'i', name) && f.p(a[0]+1, "=") {
			return a[0] + 2, a[1], true
		}
	}
	return 0, 0, false
}

// str concatenates adjacent string literals filling [lo,hi).
func (f *pyFile) str(lo, hi int) (string, bool) {
	if lo >= hi {
		return "", false
	}
	var b strings.Builder
	for i := lo; i < hi; i++ {
		if f.toks[i].k != 's' {
			return "", false
		}
		b.WriteString(f.toks[i].s)
	}
	return b.String(), true
}

func (f *pyFile) text(lo, hi int) string {
	var b strings.Builder
	for i := lo; i < hi && i < len(f.toks); i++ {
		t := f.toks[i]
		if t.k == 's' {
			b.WriteString(`"` + t.s + `"`)
		} else {
			if i > lo && t.k == 'i' && (f.toks[i-1].k == 'i' || f.toks[i-1].k == 'n') {
				b.WriteByte(' ')
			}
			b.WriteString(t.s)
		}
		if b.Len() > 100 {
			b.WriteString("...")
			break
		}
	}
	return b.String()
}

// innermost returns the innermost def containing token i.
func (f *pyFile) innermost(i int) *pyBlock {
	var best *pyBlock
	for _, d := range f.defs {
		if i >= d.lo && i < d.hi && (best == nil || d.lo > best.lo) {
			best = d
		}
	}
	return best
}

// ---------------------------------------------------------------- scan state

type pyGPU struct {
	py      []*pyFile
	byRel   map[string]*pyFile
	cfiles  [][2]string // C++/CUDA abs, rel
	tomls   [][2]string
	setups  [][2]string
	classes map[string][]*pyBlock
}

func newPyGPU() *pyGPU {
	return &pyGPU{byRel: map[string]*pyFile{}, classes: map[string][]*pyBlock{}}
}

// gpuSkip reports paths outside the product: examples, docs, benchmarks,
// tools, vendored and generated code.
func gpuSkip(rel string) bool {
	for i, s := range strings.Split(rel, "/") {
		if i == 0 && (s == "examples" || s == "docs" || s == "benchmarks" || s == "tools") {
			return true
		}
		if s == "third_party" || s == "thirdparty" || s == "generated" {
			return true
		}
	}
	return false
}

var cudaExt = map[string]bool{".cu": true, ".cuh": true, ".cpp": true, ".cc": true, ".h": true, ".hpp": true, ".cxx": true}

func (g *pyGPU) add(path, rel string) {
	name := filepath.Base(rel)
	if gpuSkip(rel) {
		return
	}
	switch {
	case name == "pyproject.toml" && !strings.Contains(rel, "/"):
		g.tomls = append(g.tomls, [2]string{path, rel})
	case name == "setup.py" && !strings.Contains(rel, "/"):
		g.setups = append(g.setups, [2]string{path, rel})
	case strings.HasSuffix(name, ".py"):
		if strings.HasPrefix(name, "test_") || strings.HasSuffix(name, "_test.py") || name == "conftest.py" {
			return
		}
		src, err := os.ReadFile(path)
		if err != nil || len(src) > 4<<20 || generatedSrc(src) {
			return
		}
		f := parsePy(rel, src)
		g.py = append(g.py, f)
		g.byRel[rel] = f
		for _, d := range f.defs {
			if d.kind == "class" {
				g.classes[d.name] = append(g.classes[d.name], d)
			}
		}
	case cudaExt[filepath.Ext(name)]:
		g.cfiles = append(g.cfiles, [2]string{path, rel})
	}
}

var generatedMarker = regexp.MustCompile(`(?i)(@generated\b|do not edit|auto-?generated by|this file (is|was) (auto-?)?generated)`)

func generatedSrc(src []byte) bool { return generatedMarker.Match(src[:min(len(src), 1000)]) }

func (g *pyGPU) entries() []Entry {
	var out []Entry
	prog := g.program()
	cli := g.cliClasses()
	for _, f := range g.py {
		threadTargets := map[string]bool{} // per file: a bare name is too common across a repository
		for i := 0; i+3 < len(f.toks); i++ {
			// Thread(target=X) / Process(target=X)
			if f.is(i, 'i', "target") && f.p(i+1, "=") {
				k := i + 2
				for f.ident(k) && f.p(k+1, ".") {
					k += 2
				}
				if f.ident(k) {
					threadTargets[f.s(k)] = true
				}
			}
		}
		out = append(out, g.routes(f)...)
		out = append(out, g.loops(f, threadTargets)...)
		out = append(out, g.pyOps(f)...)
		out = append(out, g.models(f)...)
		for _, d := range f.defs {
			if d.kind == "class" && cli[d] != "" {
				name := strings.TrimSpace(prog + " " + cli[d])
				out = append(out, Entry{Kind: KindCLI, Name: name, File: f.rel, Line: d.line, EndLine: d.endLine, Via: "cli-subcommand", Detail: "class " + d.name})
			}
		}
	}
	out = append(out, g.api()...)
	out = append(out, g.rpc()...)
	out = append(out, g.plugins()...)
	out = append(out, g.native()...)
	return out
}

// program is the console script that runs the CLI ([project.scripts]).
func (g *pyGPU) program() string {
	for _, t := range g.tomls {
		for _, e := range scanPyproject(t[0], t[1]) {
			return e.Name
		}
	}
	for _, e := range g.setupEntryPoints() {
		if group, name, _ := strings.Cut(e.Name, " "); group == "console_scripts" {
			return name
		}
	}
	return ""
}

// ---------------------------------------------------------------- FastAPI

var routeVerbs = map[string]string{"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE", "patch": "PATCH",
	"head": "HEAD", "options": "OPTIONS", "api_route": "", "websocket": "WS"}

func routeReceiver(s string) bool {
	return s == "app" || strings.Contains(strings.ToLower(s), "router")
}

func (g *pyGPU) routes(f *pyFile) []Entry {
	var out []Entry
	for _, d := range f.defs {
		if d.kind != "def" {
			continue
		}
		for _, dc := range d.decos {
			lo := dc[0]
			if !(f.ident(lo) && f.p(lo+1, ".") && f.ident(lo+2) && f.p(lo+3, "(")) || !routeReceiver(f.s(lo)) {
				continue
			}
			verb, ok := routeVerbs[f.s(lo+2)]
			if !ok {
				continue
			}
			a := f.args(lo + 3)
			if len(a) == 0 {
				continue
			}
			path, ok := f.str(a[0][0], a[0][1])
			if !ok {
				if f.is(a[0][0], 'i', "path") && f.p(a[0][0]+1, "=") {
					path, ok = f.str(a[0][0]+2, a[0][1])
				}
				if !ok {
					path = "{" + f.text(a[0][0], a[0][1]) + "}"
				}
			}
			methods := []string{verb}
			if verb == "" {
				methods = f.methodsKw(a)
			}
			for _, m := range methods {
				out = append(out, Entry{Kind: KindHTTP, Name: m + " " + path, File: f.rel, Line: f.toks[lo].line, EndLine: d.endLine, Via: "fastapi", Detail: "handler " + d.qual()})
			}
		}
	}
	// router.add_api_route("/path", handler, methods=[...])
	for i := 2; i+2 < len(f.toks); i++ {
		if !f.is(i, 'i', "add_api_route") || !f.p(i-1, ".") || !f.p(i+1, "(") || !routeReceiver(f.s(i-2)) {
			continue
		}
		a := f.args(i + 1)
		if len(a) < 2 {
			continue
		}
		path, ok := f.str(a[0][0], a[0][1])
		if !ok {
			continue
		}
		methods := f.methodsKw(a)
		for _, m := range methods {
			out = append(out, Entry{Kind: KindHTTP, Name: m + " " + path, File: f.rel, Line: f.toks[i].line, Via: "fastapi-add-route", Detail: "handler " + f.text(a[1][0], a[1][1])})
		}
	}
	return out
}

func (f *pyFile) methodsKw(a [][2]int) []string {
	var out []string
	if lo, hi, ok := f.kwarg(a, "methods"); ok {
		for i := lo; i < hi; i++ {
			if f.toks[i].k == 's' {
				out = append(out, strings.ToUpper(f.toks[i].s))
			}
		}
	}
	if len(out) == 0 {
		out = []string{"GET"}
	}
	return out
}

// ---------------------------------------------------------------- CLI

// cliClasses maps each concrete CLISubcommand subclass to its command path:
// its own `name`, prefixed with the name of the command that registers its
// base class's __subclasses__().
func (g *pyGPU) cliClasses() map[*pyBlock]string {
	out := map[*pyBlock]string{}
	var isCLI func(d *pyBlock, depth int) bool
	isCLI = func(d *pyBlock, depth int) bool {
		if depth > 6 {
			return false
		}
		for _, b := range d.bases {
			if b == "CLISubcommand" {
				return true
			}
			for _, c := range g.classes[b] {
				if c != d && isCLI(c, depth+1) {
					return true
				}
			}
		}
		return false
	}
	nameOf := func(d *pyBlock) string {
		f := d.f
		for _, l := range f.lines {
			if l.lo <= d.lo || l.lo >= d.hi || f.innermost(l.lo) != d {
				continue
			}
			if l.hi-l.lo == 3 && f.is(l.lo, 'i', "name") && f.p(l.lo+1, "=") && f.toks[l.lo+2].k == 's' {
				return f.toks[l.lo+2].s
			}
		}
		return ""
	}
	// base class -> name of the command whose body iterates its __subclasses__()
	parentOf := map[string]string{}
	for _, f := range g.py {
		for i := 0; i+2 < len(f.toks); i++ {
			if f.ident(i) && f.p(i+1, ".") && f.is(i+2, 'i', "__subclasses__") {
				for d := f.innermost(i); d != nil; d = d.owner {
					if d.kind == "class" {
						if n := nameOf(d); n != "" {
							parentOf[f.s(i)] = n
						}
						break
					}
				}
			}
		}
	}
	for _, f := range g.py {
		for _, d := range f.defs {
			if d.kind != "class" || !isCLI(d, 0) {
				continue
			}
			n := nameOf(d)
			if n == "" {
				continue
			}
			path := n
			for _, b := range d.bases {
				if p := parentOf[b]; p != "" && p != n {
					path = p + " " + n
				}
			}
			out[d] = path
		}
	}
	return out
}

// ---------------------------------------------------------------- public API

var pyAttrMap = regexp.MustCompile(`^([\w.]*):(\w+)$`)

// api lists the public methods of the engine classes (LLM, *Engine, *LLM)
// the top-level package exports, following `Alias = Class` and `import ...
// as Alias` indirections.
func (g *pyGPU) api() []Entry {
	var out []Entry
	for _, f := range g.py {
		segs := strings.Split(f.rel, "/")
		if len(segs) != 2 || segs[1] != "__init__.py" {
			continue
		}
		pkg := segs[0]
		exports := map[string]string{} // name -> module path (dotted, absolute)
		for i := 0; i+2 < len(f.toks); i++ {
			// "Name": ".mod:Attr" lazy maps
			if f.toks[i].k == 's' && f.p(i+1, ":") && f.toks[i+2].k == 's' {
				if m := pyAttrMap.FindStringSubmatch(f.toks[i+2].s); m != nil && m[2] == f.toks[i].s {
					exports[m[2]] = absModule(pkg, m[1])
				}
			}
			// from .mod import A, B
			if f.is(i, 'i', "from") {
				j := i + 1
				var mod strings.Builder
				for j < len(f.toks) && !f.is(j, 'i', "import") && f.toks[j].k != 'l' {
					mod.WriteString(f.toks[j].s)
					j++
				}
				if !f.is(j, 'i', "import") {
					continue
				}
				for k := j + 1; k < len(f.toks) && f.toks[k].k != 'l'; k++ {
					if f.ident(k) && !f.is(k-1, 'i', "as") && !f.is(k+1, 'i', "as") {
						if _, ok := exports[f.s(k)]; !ok {
							exports[f.s(k)] = absModule(pkg, mod.String())
						}
					}
				}
			}
		}
		for _, name := range sortedKeys(exports) {
			if !(name == "LLM" || strings.HasSuffix(name, "Engine") || strings.HasSuffix(name, "LLM")) {
				continue
			}
			c, via := g.resolveClass(exports[name], name, 0)
			if c == nil {
				continue
			}
			detail := pkg + "." + name
			if via != "" {
				detail += " = " + via
			}
			// the class's own public methods, then those it inherits from
			// mixins and bases in the repository (abstract ones aside)
			seen := map[string]bool{}
			queue := []*pyBlock{c}
			for depth := 0; len(queue) > 0 && depth < 20; depth++ {
				k := queue[0]
				queue = queue[1:]
				for _, d := range k.f.defs {
					if d.owner != k || d.kind != "def" || seen[d.name] || strings.HasPrefix(d.name, "_") || decorated(d, "property") || decorated(d, "overload") || decorated(d, "abstractmethod") {
						continue
					}
					seen[d.name] = true
					e := Entry{Kind: KindPyAPI, Name: name + "." + d.name, File: k.f.rel, Line: d.line, EndLine: d.endLine, Via: "package-export", Detail: detail}
					if k != c {
						e.Via, e.Detail = "package-export-inherited", detail+" (from "+k.name+")"
					}
					out = append(out, e)
				}
				for _, b := range k.bases {
					if cs := g.classes[b]; len(cs) == 1 {
						queue = append(queue, cs[0])
					}
				}
			}
		}
	}
	return out
}

func decorated(d *pyBlock, name string) bool {
	for _, dc := range d.decos {
		if d.f.is(dc[1]-1, 'i', name) || d.f.is(dc[0], 'i', name) {
			return true
		}
	}
	return false
}

func absModule(pkg, mod string) string {
	if strings.HasPrefix(mod, ".") {
		return pkg + mod
	}
	return mod
}

func (g *pyGPU) moduleFile(mod string) *pyFile {
	p := strings.ReplaceAll(mod, ".", "/")
	if f := g.byRel[p+".py"]; f != nil {
		return f
	}
	return g.byRel[p+"/__init__.py"]
}

// resolveClass finds class name in module mod, through aliases.
func (g *pyGPU) resolveClass(mod, name string, depth int) (*pyBlock, string) {
	f := g.moduleFile(mod)
	if f == nil || depth > 4 {
		return nil, ""
	}
	for _, d := range f.defs {
		if d.kind == "class" && d.owner == nil && d.name == name {
			if depth == 0 {
				return d, ""
			}
			return d, mod + "." + name
		}
	}
	// Name = Other
	for _, l := range f.lines {
		if l.indent == 0 && l.hi-l.lo >= 3 && f.is(l.lo, 'i', name) && f.p(l.lo+1, "=") && f.ident(l.lo+2) {
			other := f.s(l.hi - 1)
			if l.hi-l.lo != 3 {
				continue
			}
			if c, v := g.resolveClass(mod, other, depth+1); c != nil {
				return c, v
			}
			// imported: from M import Orig as other / from M import other
			for i := 0; i+1 < len(f.toks); i++ {
				if !f.is(i, 'i', "from") {
					continue
				}
				j := i + 1
				var m strings.Builder
				for j < len(f.toks) && !f.is(j, 'i', "import") && f.toks[j].k != 'l' {
					m.WriteString(f.toks[j].s)
					j++
				}
				for k := j + 1; k < len(f.toks) && f.toks[k].k != 'l'; k++ {
					if f.is(k, 'i', other) {
						orig := other
						if f.is(k-1, 'i', "as") {
							orig = f.s(k - 2)
						} else if f.is(k+1, 'i', "as") {
							continue
						}
						pkg := strings.Split(mod, ".")[0]
						if c, _ := g.resolveClass(absModule(pkg, m.String()), orig, depth+1); c != nil {
							return c, absModule(pkg, m.String()) + "." + orig
						}
					}
				}
			}
		}
	}
	return nil, ""
}

// ---------------------------------------------------------------- RPC

func (g *pyGPU) rpc() []Entry {
	type site struct {
		f    *pyFile
		line int
	}
	calls := map[string][]site{}
	for _, f := range g.py {
		for i := 0; i+2 < len(f.toks); i++ {
			t := f.toks[i]
			if t.k != 'i' || f.is(i-1, 'i', "def") || !f.p(i+1, "(") {
				continue
			}
			ch := ""
			switch t.s {
			case "collective_rpc", "_collective_rpc":
				ch = "collective_rpc"
			case "call_utility", "call_utility_async":
				ch = "utility"
			default:
				continue
			}
			a := f.args(i + 1)
			if len(a) == 0 {
				continue
			}
			m, ok := f.str(a[0][0], a[0][1])
			if !ok {
				if lo, hi, has := f.kwarg(a, "method"); has {
					m, ok = f.str(lo, hi)
				}
			}
			if !ok || m == "" || m == "collective_rpc" {
				continue
			}
			calls[ch+" "+m] = append(calls[ch+" "+m], site{f, t.line})
		}
	}
	// method definitions on worker and engine-core classes
	defs := map[string][]*pyBlock{}
	for _, f := range g.py {
		for _, d := range f.defs {
			if d.kind == "def" && d.owner != nil && d.owner.kind == "class" {
				defs[d.name] = append(defs[d.name], d)
			}
		}
	}
	var out []Entry
	for _, k := range sortedKeys(calls) {
		ch, m, _ := strings.Cut(k, " ")
		sites := calls[k]
		// rank: the worker or engine-core class itself, then classes named
		// like one, then (collective_rpc only) anything under worker/
		rank := func(d *pyBlock) int {
			cls := d.owner.name
			switch {
			case strings.Contains(cls, "Client"):
				return 9
			case ch == "collective_rpc" && (cls == "Worker" || cls == "WorkerBase"), ch == "utility" && cls == "EngineCore":
				return 0
			case ch == "collective_rpc" && strings.Contains(cls, "Worker"), ch == "utility" && strings.Contains(cls, "EngineCore"):
				return 1
			case ch == "collective_rpc" && strings.Contains(d.f.rel, "/worker/"):
				return 2
			}
			return 9
		}
		var cands []*pyBlock
		for _, d := range defs[m] {
			if rank(d) < 9 {
				cands = append(cands, d)
			}
		}
		sort.Slice(cands, func(a, b int) bool {
			if ra, rb := rank(cands[a]), rank(cands[b]); ra != rb {
				return ra < rb
			}
			if cands[a].f.rel != cands[b].f.rel {
				return cands[a].f.rel < cands[b].f.rel
			}
			return cands[a].line < cands[b].line
		})
		detail := fmt.Sprintf("called at %s:%d", sites[0].f.rel, sites[0].line)
		if len(sites) > 1 {
			detail += fmt.Sprintf(" and %d more", len(sites)-1)
		}
		e := Entry{Kind: KindEngineRPC, Name: k, File: sites[0].f.rel, Line: sites[0].line, Via: ch}
		if len(cands) > 0 {
			var owners []string
			for _, c := range cands {
				if !slices.Contains(owners, c.owner.name) {
					owners = append(owners, c.owner.name)
				}
			}
			e.File, e.Line, e.EndLine = cands[0].f.rel, cands[0].line, cands[0].endLine
			detail = "defined on " + strings.Join(owners, ", ") + "; " + detail
		} else {
			detail = "no definition found; " + detail
		}
		e.Detail = detail
		out = append(out, e)
	}
	return out
}

// ---------------------------------------------------------------- loops

var loopName = regexp.MustCompile(`(busy_loop|(^|_)loop$|^loop_|_loop_)`)
var loopCond = regexp.MustCompile(`^True$|running|stop|shutdown|is_set\(\)|alive|closed|closing`)

// mainLoop reports whether the while statement on logical line li is a
// main loop of d: nested only in with and try blocks, not in a for, while
// or if (where it would be a drain, retry or wait loop).
func (f *pyFile) mainLoop(li int, d *pyBlock) bool {
	ind := f.lines[li].indent
	for k := li - 1; k >= 0 && f.lines[k].lo > d.lo; k-- {
		l := f.lines[k]
		if l.indent >= ind {
			continue
		}
		ind = l.indent
		j := l.lo
		if f.is(j, 'i', "async") {
			j++
		}
		switch f.s(j) {
		case "with", "try", "else", "except", "finally":
		default:
			return false
		}
	}
	return true
}

var bgPyName = regexp.MustCompile(`(?i)(loop|^run|worker|serve|monitor|poll|listen|watch|daemon|heartbeat|thread|^_?process_|handler)`)

func (g *pyGPU) loops(f *pyFile, targets map[string]bool) []Entry {
	var out []Entry
	seen := map[*pyBlock]bool{}
	for li, l := range f.lines {
		if !f.is(l.lo, 'i', "while") {
			continue
		}
		d := f.innermost(l.lo)
		if d == nil || d.kind != "def" || seen[d] {
			continue
		}
		cond := f.text(l.lo+1, l.hi-1)
		// the loop is the function's main statement, not a drain or retry
		// loop nested in a for, with or try
		direct := f.mainLoop(li, d)
		via := ""
		switch {
		case loopName.MatchString(d.name):
			via = "loop-function"
		case targets[d.name] && direct && loopCond.MatchString(cond):
			via = "thread-target"
		case cond == "True" && direct && bgPyName.MatchString(d.name):
			via = "while-true"
		}
		if via == "" {
			continue
		}
		seen[d] = true
		out = append(out, Entry{Kind: KindBusyLoop, Name: d.qual(), File: f.rel, Line: f.toks[l.lo].line, EndLine: d.endLine, Via: via, Detail: "while " + cond})
	}
	for _, d := range f.defs {
		if d.kind == "def" && d.owner != nil && d.owner.kind == "class" && strings.Contains(d.owner.name, "EngineCore") &&
			(d.name == "step" || strings.HasPrefix(d.name, "step_")) {
			out = append(out, Entry{Kind: KindBusyLoop, Name: d.qual(), File: f.rel, Line: d.line, EndLine: d.endLine, Via: "engine-step"})
		}
	}
	return out
}

// ---------------------------------------------------------------- Python ops, Triton, models

func (g *pyGPU) pyOps(f *pyFile) []Entry {
	var out []Entry
	jitAlias := false
	for i := 0; i+3 < len(f.toks); i++ {
		if f.is(i, 'i', "from") && f.is(i+1, 'i', "triton") && f.is(i+2, 'i', "import") {
			for k := i + 3; k < len(f.toks) && f.toks[k].k != 'l'; k++ {
				if f.is(k, 'i', "jit") {
					jitAlias = true
				}
			}
		}
	}
	for _, d := range f.defs {
		if d.kind != "def" {
			continue
		}
		jit, extra := false, []string{}
		for _, dc := range d.decos {
			lo := dc[0]
			switch {
			case f.is(lo, 'i', "triton") && f.p(lo+1, ".") && f.is(lo+2, 'i', "jit"):
				jit = true
			case jitAlias && f.is(lo, 'i', "jit"):
				jit = true
			case f.is(lo, 'i', "triton") && f.p(lo+1, ".") && f.ident(lo+2):
				extra = append(extra, f.s(lo+2))
			}
			// @torch.library.custom_op("ns::name", ...)
			if f.is(lo, 'i', "torch") && f.is(lo+2, 'i', "library") && f.is(lo+4, 'i', "custom_op") && f.p(lo+5, "(") {
				if a := f.args(lo + 5); len(a) > 0 {
					if s, ok := f.str(a[0][0], a[0][1]); ok {
						out = append(out, Entry{Kind: KindTorchOp, Name: s, File: f.rel, Line: f.toks[lo].line, EndLine: d.endLine, Via: "custom-op-decorator", Detail: "impl " + d.qual()})
					}
				}
			}
		}
		if jit {
			detail := ""
			if len(extra) > 0 {
				detail = strings.Join(extra, ", ")
			}
			out = append(out, Entry{Kind: KindTriton, Name: d.qual(), File: f.rel, Line: d.line, EndLine: d.endLine, Via: "triton-jit", Detail: detail})
		}
		// module-level wrappers of compiled ops
		if d.owner == nil {
			var ops []string
			for i := d.lo; i+4 < d.hi; i++ {
				if f.is(i, 'i', "torch") && f.p(i+1, ".") && f.is(i+2, 'i', "ops") && f.p(i+3, ".") && f.ident(i+4) && strings.HasPrefix(f.s(i+4), "_") && f.p(i+5, ".") && f.ident(i+6) {
					if inner := f.innermost(i); inner == d {
						ops = append(ops, "torch.ops."+f.s(i+4)+"."+f.s(i+6))
					}
				}
			}
			if len(ops) > 0 {
				out = append(out, Entry{Kind: KindOpWrapper, Name: d.name, File: f.rel, Line: d.line, EndLine: d.endLine, Via: "torch-ops-call", Detail: strings.Join(uniq(ops), ", ")})
			}
		}
	}
	// direct_register_custom_op(op_name="x", ...)
	for i := 0; i+1 < len(f.toks); i++ {
		if !f.is(i, 'i', "direct_register_custom_op") || !f.p(i+1, "(") || f.is(i-1, 'i', "def") {
			continue
		}
		a := f.args(i + 1)
		name, ok := "", false
		if lo, hi, has := f.kwarg(a, "op_name"); has {
			name, ok = f.str(lo, hi)
		} else if len(a) > 0 {
			name, ok = f.str(a[0][0], a[0][1])
		}
		if !ok {
			continue
		}
		detail := ""
		if lo, hi, has := f.kwarg(a, "op_func"); has {
			detail = "impl " + f.text(lo, hi)
		} else if len(a) > 1 {
			detail = "impl " + f.text(a[1][0], a[1][1])
		}
		out = append(out, Entry{Kind: KindTorchOp, Name: "vllm::" + name, File: f.rel, Line: f.toks[i].line, Via: "direct-register", Detail: detail})
	}
	return out
}

func (g *pyGPU) models(f *pyFile) []Entry {
	var out []Entry
	for _, l := range f.lines {
		if l.indent != 0 || !f.ident(l.lo) || !strings.Contains(f.s(l.lo), "MODELS") {
			continue
		}
		table := f.s(l.lo)
		j := l.lo + 1
		if f.p(j, ":") {
			for j < l.hi && !f.p(j, "=") {
				if f.p(j, "[") {
					j = f.end(j)
				}
				j++
			}
		}
		if !f.p(j, "=") || !f.p(j+1, "{") {
			continue
		}
		for _, a := range f.args(j + 1) {
			if a[1]-a[0] < 3 || f.toks[a[0]].k != 's' || !f.p(a[0]+1, ":") || !f.p(a[0]+2, "(") {
				continue
			}
			var parts []string
			for _, v := range f.args(a[0] + 2) {
				if s, ok := f.str(v[0], v[1]); ok {
					parts = append(parts, s)
				}
			}
			if len(parts) < 2 {
				continue
			}
			out = append(out, Entry{Kind: KindModel, Name: f.s(a[0]), File: f.rel, Line: f.toks[a[0]].line, Via: "registry-table", Detail: strings.Join(parts, ".") + " (" + table + ")"})
		}
	}
	for i := 2; i+2 < len(f.toks); i++ {
		if f.is(i, 'i', "register_model") && f.p(i-1, ".") && f.is(i-2, 'i', "ModelRegistry") && f.p(i+1, "(") && f.toks[i+2].k == 's' {
			out = append(out, Entry{Kind: KindModel, Name: f.s(i + 2), File: f.rel, Line: f.toks[i].line, Via: "register-model"})
		}
	}
	return out
}

// ---------------------------------------------------------------- plugins

var tomlEPSect = regexp.MustCompile(`^project\.entry-points\.["']?([\w.-]+)["']?$`)

func (g *pyGPU) plugins() []Entry {
	var out []Entry
	for _, t := range g.tomls {
		sect := ""
		for i, l := range readLines(t[0]) {
			if m := tomlSect.FindStringSubmatch(strings.TrimSpace(l)); m != nil {
				sect = m[1]
				continue
			}
			if m := tomlEPSect.FindStringSubmatch(sect); m != nil {
				if kv := tomlKV.FindStringSubmatch(strings.TrimSpace(l)); kv != nil {
					out = append(out, Entry{Kind: KindPlugin, Name: m[1] + " " + kv[1], File: t[1], Line: i + 1, Via: "pyproject-entry-point", Detail: kv[2]})
				}
			}
		}
	}
	out = append(out, g.setupEntryPoints()...)
	// module-level string constants, for plugin group names
	consts := map[string]string{}
	for _, f := range g.py {
		for _, l := range f.lines {
			if l.indent == 0 && l.hi-l.lo == 3 && f.ident(l.lo) && f.p(l.lo+1, "=") && f.toks[l.lo+2].k == 's' {
				if _, dup := consts[f.s(l.lo)]; !dup {
					consts[f.s(l.lo)] = f.toks[l.lo+2].s
				}
			}
		}
	}
	for _, f := range g.py {
		for i := 0; i+2 < len(f.toks); i++ {
			if f.is(i-1, 'i', "def") || !f.p(i+1, "(") {
				continue
			}
			var lo, hi int
			switch {
			case f.is(i, 'i', "load_plugins_by_group"):
				a := f.args(i + 1)
				if len(a) == 0 {
					continue
				}
				lo, hi = a[0][0], a[0][1]
				if l2, h2, ok := f.kwarg(a, "group"); ok {
					lo, hi = l2, h2
				}
			case f.is(i, 'i', "entry_points"):
				l2, h2, ok := f.kwarg(f.args(i+1), "group")
				if !ok {
					continue
				}
				lo, hi = l2, h2
			default:
				continue
			}
			group, ok := f.str(lo, hi)
			if !ok && hi-lo == 1 && f.ident(lo) {
				group, ok = consts[f.s(lo)]
			}
			if ok && group != "" {
				out = append(out, Entry{Kind: KindPlugin, Name: "group " + group, File: f.rel, Line: f.toks[i].line, Via: "plugin-group", Detail: "loaded by " + f.text(i, f.end(i+1)+1)})
			}
		}
		// builtin_*_plugins = {"name": factory}
		for _, l := range f.lines {
			if l.indent != 0 || !f.ident(l.lo) || !strings.HasSuffix(f.s(l.lo), "_plugins") || !f.p(l.lo+1, "=") || !f.p(l.lo+2, "{") {
				continue
			}
			for _, a := range f.args(l.lo + 2) {
				if a[1]-a[0] >= 3 && f.toks[a[0]].k == 's' && f.p(a[0]+1, ":") {
					out = append(out, Entry{Kind: KindPlugin, Name: f.s(l.lo) + " " + f.s(a[0]), File: f.rel, Line: f.toks[a[0]].line, Via: "builtin-plugin", Detail: f.text(a[0]+2, a[1])})
				}
			}
		}
	}
	return out
}

var epLine = regexp.MustCompile(`^\s*([\w.-]+)\s*=\s*([\w.:]+)`)

// setupEntryPoints lists setup.py entry_points={"group": ["name = mod:fn"]}.
func (g *pyGPU) setupEntryPoints() []Entry {
	var out []Entry
	for _, s := range g.setups {
		src, err := os.ReadFile(s[0])
		if err != nil {
			continue
		}
		f := parsePy(s[1], src)
		for i := 0; i+2 < len(f.toks); i++ {
			if !(f.is(i, 'i', "entry_points") && f.p(i+1, "=") && f.p(i+2, "{")) {
				continue
			}
			for _, a := range f.args(i + 2) {
				group, ok := f.str(a[0], a[0]+1)
				if !ok || !f.p(a[0]+1, ":") {
					continue
				}
				for k := a[0] + 2; k < a[1]; k++ {
					if f.toks[k].k == 's' {
						if m := epLine.FindStringSubmatch(f.toks[k].s); m != nil {
							out = append(out, Entry{Kind: KindPlugin, Name: group + " " + m[1], File: s[1], Line: f.toks[k].line, Via: "setup-entry-point", Detail: m[2]})
						}
					}
				}
			}
		}
	}
	return out
}

// ---------------------------------------------------------------- C++ and CUDA

var torchLib = regexp.MustCompile(`^(STABLE_)?TORCH_LIBRARY(_FRAGMENT|_IMPL|_EXPAND)?$`)

func (g *pyGPU) native() []Entry {
	type op struct {
		e     Entry
		impls []string
	}
	ops := map[string]*op{}
	var order []string
	var impls []struct{ key, impl string }
	var out []Entry
	for _, cf := range g.cfiles {
		src, err := os.ReadFile(cf[0])
		if err != nil || len(src) > 4<<20 || generatedSrc(src) {
			continue
		}
		hasLib := bytes.Contains(src, []byte("TORCH_LIBRARY"))
		hasGlobal := bytes.Contains(src, []byte("__global__"))
		if !hasLib && !hasGlobal {
			continue
		}
		toks := jlex(src)
		m := jmatch(toks)
		var lines []string
		if hasGlobal {
			lines = strings.Split(string(src), "\n")
		}
		rel := cf[1]
		for i := 0; i+1 < len(toks); i++ {
			t := toks[i]
			if t.k != 'i' {
				continue
			}
			if hasLib && torchLib.MatchString(t.s) && toks[i+1].s == "(" && m[i+1] > 0 && m[i+1]+1 < len(toks) && toks[m[i+1]+1].s == "{" {
				// skip the macro's own #define
				if i > 1 && toks[i-1].s == "define" {
					continue
				}
				args := splitTok(toks, m, i+1)
				if len(args) < 2 {
					continue
				}
				ns := libNamespace(toks, args[0], rel)
				impl := strings.HasSuffix(t.s, "_IMPL")
				dispatch := ""
				varTok := args[len(args)-1]
				if impl && len(args) >= 3 {
					dispatch = joinTok(toks, args[1][0], args[1][1])
				}
				if varTok[1]-varTok[0] != 1 {
					continue
				}
				v := toks[varTok[0]].s
				body := m[i+1] + 1
				for j := body + 1; j+3 < m[body]; j++ {
					if toks[j].s != v || toks[j+1].s != "." || toks[j+3].s != "(" {
						continue
					}
					switch toks[j+2].s {
					case "def":
						a := splitTok(toks, m, j+3)
						if len(a) == 0 {
							continue
						}
						schema, ok := concatStr(toks, a[0][0], a[0][1])
						if !ok {
							continue
						}
						name := schema
						if k := strings.Index(schema, "("); k >= 0 {
							name = schema[:k]
						}
						name = strings.TrimSpace(name)
						key := ns + "::" + name
						detail := strings.Join(strings.Fields(schema), " ")
						if len(a) > 1 {
							detail += "; impl " + joinTok(toks, a[1][0], a[1][1])
						}
						// one entry per file: CPU and CUDA builds each define their ops
						if fk := rel + "\x00" + key; ops[fk] == nil {
							ops[fk] = &op{e: Entry{Kind: KindTorchOp, Name: key, File: rel, Line: toks[j].line, Via: "torch-library", Detail: detail}}
							order = append(order, fk)
						}
					case "impl":
						a := splitTok(toks, m, j+3)
						if len(a) < 2 {
							continue
						}
						name, ok := concatStr(toks, a[0][0], a[0][1])
						if !ok {
							continue
						}
						d := dispatch
						fn := a[len(a)-1]
						if len(a) >= 3 {
							d = joinTok(toks, a[1][0], a[1][1])
						}
						impls = append(impls, struct{ key, impl string }{ns + "::" + name, d + "=" + joinTok(toks, fn[0], fn[1])})
					}
				}
				continue
			}
			if hasGlobal && t.s == "__global__" {
				name := kernelName(toks, m, i)
				if name == "" {
					continue
				}
				if inMacro(lines, t.line) {
					continue // a kernel stamped out by a macro is named by its parameter
				}
				out = append(out, Entry{Kind: KindCUDA, Name: name, File: rel, Line: t.line, Via: "cuda-global"})
			}
		}
	}
	for _, im := range impls {
		for _, fk := range order {
			if o := ops[fk]; o.e.Name == im.key {
				o.impls = append(o.impls, im.impl)
			}
		}
	}
	for _, k := range order {
		o := ops[k]
		if len(o.impls) > 0 {
			o.e.Detail += "; impl " + strings.Join(uniq(o.impls), ", ")
		}
		out = append(out, o.e)
	}
	return out
}

func splitTok(toks []jtok, m []int, open int) [][2]int {
	close := m[open]
	var out [][2]int
	lo := open + 1
	for i := lo; i < close; i++ {
		if toks[i].k == 'p' && (toks[i].s == "(" || toks[i].s == "[" || toks[i].s == "{") && m[i] > i {
			i = m[i]
			continue
		}
		if toks[i].k == 'p' && toks[i].s == "," {
			out = append(out, [2]int{lo, i})
			lo = i + 1
		}
	}
	if lo < close {
		out = append(out, [2]int{lo, close})
	}
	return out
}

func joinTok(toks []jtok, lo, hi int) string {
	var b strings.Builder
	for i := lo; i < hi; i++ {
		if toks[i].k == 's' {
			b.WriteString(`"` + toks[i].s + `"`)
			continue
		}
		b.WriteString(toks[i].s)
	}
	s := b.String()
	if len(s) > 100 {
		s = s[:100] + "..."
	}
	return s
}

// concatStr joins adjacent C string literals, ignoring preprocessor lines
// between them is not attempted: any other token fails.
func concatStr(toks []jtok, lo, hi int) (string, bool) {
	var b strings.Builder
	for i := lo; i < hi; i++ {
		if toks[i].k != 's' {
			return "", false
		}
		b.WriteString(toks[i].s)
	}
	return b.String(), hi > lo
}

// libNamespace renders a TORCH_LIBRARY namespace argument, standing in for
// TORCH_EXTENSION_NAME (set per CMake target) with the directory's
// extension: _rocm_C under rocm/, _moe_C under moe/, else _C.
func libNamespace(toks []jtok, a [2]int, rel string) string {
	ext := "_C"
	for _, s := range strings.Split(rel, "/") {
		if s == "rocm" {
			ext = "_rocm_C"
		} else if s == "moe" {
			ext = "_moe_C"
		}
	}
	var b strings.Builder
	for i := a[0]; i < a[1]; i++ {
		switch s := toks[i].s; {
		case s == "TORCH_EXTENSION_NAME":
			b.WriteString(ext)
		case s == "CONCAT" || s == "(" || s == ")" || s == ",":
		default:
			b.WriteString(s)
		}
	}
	return b.String()
}

var notKernelName = map[string]bool{"__launch_bounds__": true, "__attribute__": true, "alignas": true, "decltype": true, "__declspec": true, "C10_LAUNCH_BOUNDS_1": true, "C10_LAUNCH_BOUNDS_2": true}

// kernelName finds the function name after a __global__ qualifier: the
// identifier before the first parameter list that isn't an attribute.
func kernelName(toks []jtok, m []int, i int) string {
	for j := i + 1; j < len(toks) && j < i+60; j++ {
		t := toks[j]
		if t.k == 'p' && (t.s == ";" || t.s == "{" || t.s == "}") {
			return ""
		}
		if t.k == 'p' && t.s == "(" {
			prev := toks[j-1]
			attr := strings.HasPrefix(prev.s, "__") && strings.HasSuffix(prev.s, "__")
			if prev.k == 'i' && !notKernelName[prev.s] && !attr && j-1 > i {
				return prev.s
			}
			if m[j] > j {
				j = m[j]
			}
		}
	}
	return ""
}

// inMacro reports whether a line belongs to a #define (with continuations).
func inMacro(lines []string, ln int) bool {
	for k := ln - 1; k >= 0 && k < len(lines); k-- {
		if strings.HasPrefix(strings.TrimSpace(lines[k]), "#define") {
			return true
		}
		if k == 0 || !strings.HasSuffix(strings.TrimRight(lines[k-1], " \t\r"), "\\") {
			return false
		}
	}
	return false
}

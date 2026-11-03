package main

import (
	"bufio"
	"bytes"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// Entry is one entry point found in the code.
type Entry struct {
	Kind string `json:"kind"`
	Name string `json:"name"`
	File string `json:"file"`
	Line int    `json:"line"`
	// EndLine, for entries that are whole functions (workflows, activities,
	// polling loops), is the function's last line, so a citation anywhere in
	// the body counts as covering the entry.
	EndLine int `json:"end_line,omitempty"`
	// Via names the heuristic that found the entry, so precision can be judged
	// per heuristic.
	Via string `json:"via,omitempty"`
	// Detail adds context a name can't carry, such as a messaging verb's
	// handler or the launcher scripts of a Java main class.
	Detail string `json:"detail,omitempty"`
	// Skip, when a builder fills it in, says why the entry is deliberately not
	// modeled. The check tool reports skipped entries separately.
	Skip string `json:"skip,omitempty"`
	// Exported and Test are set on the function kinds (go-func, py-func,
	// ts-func) only: whether the name is exported, and whether it comes from
	// a test file.
	Exported *bool `json:"exported,omitempty"`
	Test     bool  `json:"test,omitempty"`
}

// Entry kinds.
const (
	KindHTTP     = "http-route"        // Go HTTP route registrations and generated servers
	KindWorkflow = "temporal-workflow" // registered or child Temporal workflows
	KindActivity = "temporal-activity" // Temporal activities
	KindCron     = "cron"              // tickers, polling loops, cron specs, scheduled infra
	KindCLI      = "cli-command"       // cobra commands, flag-based mains and their subcommands
	KindNext     = "next-route"        // Next.js app/**/route.ts handlers and pages/api
	KindTRPC     = "trpc-procedure"    // tRPC router procedures
	KindPyCLI    = "python-cli"        // Python __main__ scripts, argparse subcommands, click/typer, [project.scripts]
	KindListener = "listener"          // long-lived accept loops and servers whose handler is not a router
	KindQueue    = "queue-consumer"    // message-broker, pub/sub and event-stream consumers
	KindLambda   = "lambda-handler"    // AWS Lambda handlers named by terraform
	KindNomad    = "nomad-job"         // Nomad job files and Go job-spec builders
	KindSvcMain  = "service-main"      // flag-less long-running process mains
)

// Options tune the scan.
type Options struct {
	// IncludeTestSupport keeps mocks, fakes, e2e harnesses and fixtures, which
	// are skipped by default.
	IncludeTestSupport bool
	// Langs limits the language scanners ("go", "ts", "python", "java") and
	// plugins ("ts-frontend", "python-gpu").
	// Empty means auto-detect: every scanner runs on the files it
	// recognizes. Infrastructure files (terraform, YAML) are always scanned.
	Langs []string
	// Kinds turns on opt-in kinds (OptKinds: go-func, py-func, ts-func), for
	// logic-level scopes. They run whatever Langs says.
	Kinds []string
	// IncludeTestFuncs, with Kinds, also lists the functions of test files,
	// flagged test.
	IncludeTestFuncs bool
	// Paths restricts the result to entries in these files or directories
	// (relative to the root): a refinement scope's paths. The whole root is
	// still scanned, so registrations made outside the scope still resolve.
	Paths []string
}

// Languages the scan knows. ts-frontend and python-gpu are plugins layered
// on ts and python for VS Code style front ends and GPU serving engines;
// auto-detect turns each on only when the root carries its markers.
var Langs = []string{"go", "ts", "python", "java", "ts-frontend", "python-gpu"}

// plugin reports whether a layered plugin runs: listed explicitly, or, under
// auto-detect, found by detectPlugin.
func (o Options) plugin(name, root string) bool {
	if len(o.Langs) == 0 {
		return detectPlugin(name, root)
	}
	return o.lang(name)
}

// detectPlugin looks for a plugin's markers at the root: src/vs or
// src/vscode-dts for ts-frontend; csrc/, or a pyproject.toml or setup.py
// naming torch, for python-gpu.
func detectPlugin(name, root string) bool {
	isDir := func(p string) bool {
		st, err := os.Stat(filepath.Join(root, p))
		return err == nil && st.IsDir()
	}
	switch name {
	case "ts-frontend":
		return isDir("src/vs") || isDir("src/vscode-dts")
	case "python-gpu":
		if isDir("csrc") {
			return true
		}
		for _, f := range []string{"pyproject.toml", "setup.py"} {
			if b, err := os.ReadFile(filepath.Join(root, f)); err == nil && regexp.MustCompile(`\btorch\b`).Match(b) {
				return true
			}
		}
	}
	return false
}

func (o Options) lang(l string) bool {
	if len(o.Langs) == 0 {
		return true
	}
	for _, x := range o.Langs {
		if x == l {
			return true
		}
	}
	return false
}

var skipDirs = map[string]bool{
	"node_modules": true, "vendor": true, ".git": true, "testdata": true, "dist": true,
	"build": true, ".next": true, "__pycache__": true, ".venv": true, "venv": true, ".turbo": true,
}

// testSupport matches path segments that hold test harnesses rather than product code.
var testSupport = regexp.MustCompile(`^(mocks?|mockapi|fakes?|fake[a-z0-9]*|testutils?|testing|tests?|[a-z0-9]+test|e2e|__tests__|__mocks__|fixtures?)$`)

func secretFile(name string) bool {
	return strings.Contains(name, ".env") || strings.HasSuffix(name, ".age") || strings.HasSuffix(name, ".pem") || strings.HasSuffix(name, ".key")
}

// Scan walks root and returns every entry point the heuristics find, sorted by
// kind, file and line.
func Scan(root string, opt Options) ([]Entry, error) {
	goDirs := map[string][]string{}
	js := &javaScan{scripts: map[string][]string{}}
	var fe *tsFront
	if opt.plugin("ts-frontend", root) {
		fe = newTSFront()
	}
	var gp *pyGPU
	if opt.plugin("python-gpu", root) {
		gp = newPyGPU()
	}
	paths := cleanPaths(opt.Paths)
	var out []Entry
	var tfFiles [][2]string
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		name := d.Name()
		if d.IsDir() {
			hidden := strings.HasPrefix(name, ".") && name != ".github"
			// A front end's "testing" directory is the test-explorer feature.
			test := testSupport.MatchString(name) && !(fe != nil && name == "testing")
			if path != root && (skipDirs[name] || hidden || (!opt.IncludeTestSupport && test)) {
				return filepath.SkipDir
			}
			return nil
		}
		if secretFile(name) || !d.Type().IsRegular() {
			return nil
		}
		rel, _ := filepath.Rel(root, path)
		rel = filepath.ToSlash(rel)
		if len(opt.Kinds) > 0 && inPaths(rel, paths) {
			out = append(out, funcEntries(path, rel, name, opt)...)
		}
		if fe != nil {
			fe.add(path, rel)
		}
		if gp != nil {
			gp.add(path, rel)
		}
		switch {
		case strings.HasSuffix(name, ".go"):
			if opt.lang("go") && !strings.HasSuffix(name, "_test.go") {
				goDirs[filepath.Dir(path)] = append(goDirs[filepath.Dir(path)], path)
			}
		case isTS(name):
			if !opt.lang("ts") || testName.MatchString(name) {
				return nil
			}
			out = append(out, scanTS(path, rel)...)
		case strings.HasSuffix(name, ".py"):
			if !opt.lang("python") || strings.HasPrefix(name, "test_") || strings.HasSuffix(name, "_test.py") {
				return nil
			}
			out = append(out, scanPython(path, rel)...)
			// Under the python-gpu plugin, its scope (no examples, docs,
			// benchmarks or tools) holds for these routes too.
			if gp == nil || !gpuSkip(rel) {
				out = append(out, scanPyHTTP(path, rel, gp == nil)...)
			}
		case name == "pyproject.toml":
			if opt.lang("python") {
				out = append(out, scanPyproject(path, rel)...)
			}
		case strings.HasSuffix(name, ".java"):
			if opt.lang("java") && javaSource(rel, name, opt.IncludeTestSupport) {
				js.add(path, rel)
			}
		case opt.lang("java") && launcherScript(rel, name):
			js.addScript(path, rel)
		case strings.HasSuffix(name, ".tf"):
			out = append(out, scanTerraform(path, rel)...)
			tfFiles = append(tfFiles, [2]string{path, rel})
		case name == "vercel.json":
			out = append(out, scanVercel(path, rel)...)
		case strings.HasSuffix(name, ".nomad") || strings.HasSuffix(name, ".hcl"):
			out = append(out, scanNomad(path, rel)...)
		case strings.HasSuffix(name, ".yaml") || strings.HasSuffix(name, ".yml"):
			out = append(out, scanYAML(path, rel)...)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	out = append(out, tfLambdas(root, tfFiles, opt.IncludeTestSupport)...)
	g := &goScan{root: root, methods: map[string][]funcRef{}, closureCache: map[*ast.FuncDecl]map[string]*ast.FuncLit{}, usedLoops: map[*ast.FuncDecl]bool{}}
	dirs := make([]string, 0, len(goDirs))
	for d := range goDirs {
		dirs = append(dirs, d)
	}
	sort.Strings(dirs)
	for _, d := range dirs {
		g.parseDir(d, goDirs[d])
	}
	g.prepare()
	var goOut []Entry
	for _, p := range g.pkgs {
		goOut = append(goOut, g.scanPkg(p)...)
	}
	out = append(out, g.dropUsedLoops(goOut)...)
	if len(js.files) > 0 {
		out = append(out, js.entries()...)
	}
	if fe != nil {
		out = append(out, fe.entries()...)
	}
	if gp != nil {
		out = append(out, gp.entries()...)
	}
	out = dedupe(out)
	if len(paths) > 0 {
		kept := out[:0]
		for _, e := range out {
			if inPaths(e.File, paths) {
				kept = append(kept, e)
			}
		}
		out = kept
	}
	sort.Slice(out, func(a, b int) bool {
		x, y := out[a], out[b]
		if x.Kind != y.Kind {
			return x.Kind < y.Kind
		}
		if x.File != y.File {
			return x.File < y.File
		}
		if x.Line != y.Line {
			return x.Line < y.Line
		}
		return x.Name < y.Name
	})
	return out, nil
}

func dedupe(in []Entry) []Entry {
	seen := map[string]bool{}
	var out []Entry
	for _, e := range in {
		// One entry per name in a file: a route registered on two branches,
		// or a subcommand seen both in an argv switch and its FlagSet, is
		// one entry point.
		k := e.Kind + "\x00" + e.File + "\x00" + e.Name
		if !seen[k] {
			seen[k] = true
			out = append(out, e)
		}
	}
	return out
}

// ---------------------------------------------------------------- Go

type funcRef struct {
	decl *ast.FuncDecl
	file string // relative path
	fset *token.FileSet
}

type goFile struct {
	ast     *ast.File
	rel     string
	src     []byte
	imports map[string]string // local name -> import path
}

type goPkg struct {
	dir   string
	name  string
	files []*goFile
	funcs map[string][]funcRef // "Name" for functions, "Type.Name" and "Name" for methods
	types map[string]bool
	rel   string // directory relative to the root

	goNames map[string]bool // functions started with a go statement
	goLits  [][2]token.Pos  // extents of go func(){...} literals

	vals    map[string]ast.Expr        // package-level const and var values
	structs map[string]*ast.StructType // struct types by name
}

type goScan struct {
	root    string
	fset    *token.FileSet
	pkgs    []*goPkg
	methods map[string][]funcRef // repository-wide, by bare name

	closureCache map[*ast.FuncDecl]map[string]*ast.FuncLit
	routeHelpers map[ast.Node]routeHelper
	loopHelpers  map[ast.Node]loopHelper
	usedLoops    map[*ast.FuncDecl]bool
}

func (g *goScan) parseDir(dir string, paths []string) {
	if g.fset == nil {
		g.fset = token.NewFileSet()
	}
	sort.Strings(paths)
	byPkg := map[string]*goPkg{}
	for _, path := range paths {
		src, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		f, err := parser.ParseFile(g.fset, path, src, parser.SkipObjectResolution)
		if err != nil {
			continue
		}
		rel, _ := filepath.Rel(g.root, path)
		gf := &goFile{ast: f, rel: filepath.ToSlash(rel), src: src, imports: map[string]string{}}
		for _, im := range f.Imports {
			p, _ := strconv.Unquote(im.Path.Value)
			local := p[strings.LastIndex(p, "/")+1:]
			if im.Name != nil {
				local = im.Name.Name
			}
			gf.imports[local] = p
		}
		pkg := byPkg[f.Name.Name]
		if pkg == nil {
			relDir, _ := filepath.Rel(g.root, dir)
			pkg = &goPkg{dir: dir, name: f.Name.Name, funcs: map[string][]funcRef{}, types: map[string]bool{}, rel: filepath.ToSlash(relDir),
				vals: map[string]ast.Expr{}, structs: map[string]*ast.StructType{}}
			byPkg[f.Name.Name] = pkg
			g.pkgs = append(g.pkgs, pkg)
		}
		pkg.files = append(pkg.files, gf)
		for _, d := range f.Decls {
			switch d := d.(type) {
			case *ast.FuncDecl:
				ref := funcRef{d, gf.rel, g.fset}
				pkg.funcs[d.Name.Name] = append(pkg.funcs[d.Name.Name], ref)
				if r := recvType(d); r != "" {
					pkg.funcs[r+"."+d.Name.Name] = append(pkg.funcs[r+"."+d.Name.Name], ref)
					g.methods[d.Name.Name] = append(g.methods[d.Name.Name], ref)
				}
			case *ast.GenDecl:
				for _, s := range d.Specs {
					switch s := s.(type) {
					case *ast.TypeSpec:
						pkg.types[s.Name.Name] = true
						if st, ok := s.Type.(*ast.StructType); ok {
							pkg.structs[s.Name.Name] = st
						}
					case *ast.ValueSpec:
						for i, n := range s.Names {
							if i < len(s.Values) {
								pkg.vals[n.Name] = s.Values[i]
							}
						}
					}
				}
			}
		}
	}
}

func recvType(d *ast.FuncDecl) string {
	if d.Recv == nil || len(d.Recv.List) == 0 {
		return ""
	}
	return typeName(d.Recv.List[0].Type)
}

// typeName returns the base type name of *T, T, T[X] or pkg.T.
func typeName(e ast.Expr) string {
	switch t := e.(type) {
	case *ast.StarExpr:
		return typeName(t.X)
	case *ast.Ident:
		return t.Name
	case *ast.IndexExpr:
		return typeName(t.X)
	case *ast.IndexListExpr:
		return typeName(t.X)
	case *ast.SelectorExpr:
		return t.Sel.Name
	}
	return ""
}

func (g *goScan) line(p token.Pos) int { return g.fset.Position(p).Line }

func (g *goScan) entry(kind, name string, rel string, pos token.Pos, via string) Entry {
	return Entry{Kind: kind, Name: name, File: rel, Line: g.line(pos), Via: via}
}

// declEntry is an entry for a whole function declaration.
func (g *goScan) declEntry(kind string, ref funcRef, via string) Entry {
	e := g.entry(kind, qualName(ref.decl), ref.file, ref.decl.Pos(), via)
	e.EndLine = g.line(ref.decl.End())
	return e
}

// firstParamIs reports whether d's first parameter has type <alias>.<sel>
// where alias imports importPath.
func firstParamIs(d *ast.FuncDecl, f *goFile, importPath, sel string) bool {
	if d.Type.Params == nil || len(d.Type.Params.List) == 0 {
		return false
	}
	s, ok := d.Type.Params.List[0].Type.(*ast.SelectorExpr)
	if !ok || s.Sel.Name != sel {
		return false
	}
	x, ok := s.X.(*ast.Ident)
	return ok && f.imports[x.Name] == importPath
}

const (
	temporalWorkflow = "go.temporal.io/sdk/workflow"
	cobraPkg         = "github.com/spf13/cobra"
)

func fileOf(p *goPkg, rel string) *goFile {
	for _, f := range p.files {
		if f.rel == rel {
			return f
		}
	}
	return nil
}

func (g *goScan) scanPkg(p *goPkg) []Entry {
	g.goTargets(p)
	var out []Entry
	for _, f := range p.files {
		out = append(out, g.scanGoFile(p, f)...)
	}
	out = append(out, g.pkgEntries(p)...)
	// Exported functions named *Workflow taking a workflow.Context are workflows
	// even when the registration is out of sight (a shared worker package).
	for _, f := range p.files {
		for _, d := range f.ast.Decls {
			fd, ok := d.(*ast.FuncDecl)
			if ok && fd.Name.IsExported() && strings.HasSuffix(fd.Name.Name, "Workflow") && firstParamIs(fd, f, temporalWorkflow, "Context") {
				out = append(out, g.declEntry(KindWorkflow, funcRef{fd, f.rel, g.fset}, "workflow-signature"))
			}
		}
	}
	return out
}

func qualName(d *ast.FuncDecl) string {
	if r := recvType(d); r != "" {
		return r + "." + d.Name.Name
	}
	return d.Name.Name
}

// resolveFunc finds the declaration an expression names: F, x.M or T.M.
func (g *goScan) resolveFunc(p *goPkg, e ast.Expr) (funcRef, string, bool) {
	switch x := e.(type) {
	case *ast.Ident:
		if refs := p.funcs[x.Name]; len(refs) > 0 && refs[0].decl.Recv == nil {
			return refs[0], x.Name, true
		}
		return funcRef{}, x.Name, false
	case *ast.SelectorExpr:
		name := x.Sel.Name
		if id, ok := x.X.(*ast.Ident); ok {
			if q := g.importedPkg(p, id.Name); q != nil {
				if refs := q.funcs[name]; len(refs) > 0 && refs[0].decl.Recv == nil {
					return refs[0], name, true
				}
				return funcRef{}, exprString(e), false
			}
		}
		if refs := p.funcs[name]; len(refs) == 1 {
			return refs[0], qualName(refs[0].decl), true
		}
		if refs := g.methods[name]; len(refs) == 1 {
			return refs[0], qualName(refs[0].decl), true
		}
		return funcRef{}, exprString(e), false
	case *ast.ParenExpr:
		return g.resolveFunc(p, x.X)
	}
	return funcRef{}, exprString(e), false
}

// importedPkg finds the scanned package a local import name refers to, by
// matching the import path's suffix against package directories.
func (g *goScan) importedPkg(p *goPkg, local string) *goPkg {
	for _, f := range p.files {
		ip, ok := f.imports[local]
		if !ok {
			continue
		}
		// Module paths rarely match directories (a go.work of modules), so
		// pick the package sharing the most trailing path segments, at least
		// two, when exactly one does.
		ipSegs := strings.Split(ip, "/")
		var best *goPkg
		bestN, tie := 1, false
		for _, q := range g.pkgs {
			if q == p || q.rel == "." {
				continue
			}
			n := commonSuffix(ipSegs, strings.Split(q.rel, "/"))
			switch {
			case n > bestN:
				best, bestN, tie = q, n, false
			case n == bestN && best != nil:
				tie = true
			}
		}
		if tie {
			return nil
		}
		return best
	}
	return nil
}

// goTargets records which functions a package starts as goroutines.
func (g *goScan) goTargets(p *goPkg) {
	p.goNames = map[string]bool{}
	for _, f := range p.files {
		ast.Inspect(f.ast, func(n ast.Node) bool {
			gs, ok := n.(*ast.GoStmt)
			if !ok {
				return true
			}
			switch fn := gs.Call.Fun.(type) {
			case *ast.FuncLit:
				p.goLits = append(p.goLits, [2]token.Pos{fn.Pos(), fn.End()})
				// a goroutine literal that only calls a function starts that function
				ast.Inspect(fn.Body, func(m ast.Node) bool {
					if c, ok := m.(*ast.CallExpr); ok {
						p.goNames[lastName(c.Fun)] = true
					}
					return true
				})
			default:
				p.goNames[lastName(fn)] = true
			}
			return true
		})
	}
}

func commonSuffix(a, b []string) int {
	n := 0
	for n < len(a) && n < len(b) && a[len(a)-1-n] == b[len(b)-1-n] {
		n++
	}
	return n
}

func lastName(e ast.Expr) string {
	switch x := e.(type) {
	case *ast.Ident:
		return x.Name
	case *ast.SelectorExpr:
		return x.Sel.Name
	}
	return ""
}

// background reports whether a ticker or polling loop at pos, inside fn, runs
// as background work: in a goroutine, in main, or in a function whose name
// says it loops.
var bgName = regexp.MustCompile(`(?i)(loop|^run|watch|refresh|sweep|reconcil|flush|heartbeat|sampler|pump|monitor|renew|keep|scrape|janitor|supervis|^main$)`)

func (p *goPkg) background(fn *ast.FuncDecl, pos token.Pos, strict bool) bool {
	for _, r := range p.goLits {
		if pos >= r[0] && pos < r[1] {
			return true
		}
	}
	if fn == nil {
		return false
	}
	if p.goNames[fn.Name.Name] || fn.Name.Name == "main" {
		return true
	}
	return !strict && bgName.MatchString(fn.Name.Name)
}

var httpMethods = map[string]string{
	"Get": "GET", "Post": "POST", "Put": "PUT", "Delete": "DELETE", "Patch": "PATCH", "Head": "HEAD",
	"Options": "OPTIONS", "Connect": "CONNECT", "Trace": "TRACE",
	"GET": "GET", "POST": "POST", "PUT": "PUT", "DELETE": "DELETE", "PATCH": "PATCH", "HEAD": "HEAD", "OPTIONS": "OPTIONS",
	"Any": "ANY",
}

var genRouteComment = regexp.MustCompile(`^\s*// \((GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) (/[^)\s]*)\)`)

func (g *goScan) scanGoFile(p *goPkg, f *goFile) []Entry {
	var out []Entry
	genRoutes := false
	if strings.HasSuffix(f.rel, ".gen.go") {
		// oapi-codegen servers document every operation as "// (GET /path)" on
		// the ServerInterface; those comments are the reliable inventory.
		seen := map[string]bool{}
		sc := bufio.NewScanner(bytes.NewReader(f.src))
		sc.Buffer(make([]byte, 1<<20), 1<<20)
		for n := 1; sc.Scan(); n++ {
			if m := genRouteComment.FindStringSubmatch(sc.Text()); m != nil {
				name := m[1] + " " + m[2]
				if !seen[name] {
					seen[name] = true
					out = append(out, Entry{Kind: KindHTTP, Name: name, File: f.rel, Line: n, Via: "openapi-gen"})
				}
			}
		}
		genRoutes = len(out) > 0
	}
	consumed := map[*ast.CallExpr]bool{}
	cronFuncs := map[*ast.FuncDecl]bool{}
	ownFuncs := map[*ast.FuncDecl]bool{} // listeners and consumers, one per function
	isMain := p.name == "main"
	var visit func(n ast.Node, prefix string, fn *ast.FuncDecl) bool
	inspect := func(root ast.Node, prefix string, fn *ast.FuncDecl) {
		ast.Inspect(root, func(n ast.Node) bool { return visit(n, prefix, fn) })
	}
	cron := func(fn *ast.FuncDecl, pos token.Pos, via string) {
		if fn != nil && cronFuncs[fn] {
			return
		}
		if fn == nil {
			out = append(out, g.entry(KindCron, "(func literal)", f.rel, pos, via))
			return
		}
		cronFuncs[fn] = true
		e := g.declEntry(KindCron, funcRef{fn, f.rel, g.fset}, via)
		e.Line = g.line(pos)
		out = append(out, e)
	}
	visit = func(n ast.Node, prefix string, fn *ast.FuncDecl) bool {
		switch x := n.(type) {
		case *ast.FuncDecl:
			if x.Body != nil {
				inspect(x.Body, prefix, x)
			}
			return false
		case *ast.ForStmt:
			if acceptLoop(x.Body) {
				// An accept loop is a listener, whatever it sleeps on.
				if fn == nil {
					out = append(out, g.entry(KindListener, "(func literal)", f.rel, x.Pos(), "accept-loop"))
				} else if !ownFuncs[fn] {
					ownFuncs[fn] = true
					e := g.declEntry(KindListener, funcRef{fn, f.rel, g.fset}, "accept-loop")
					e.Line = g.line(x.Pos())
					out = append(out, e)
				}
				break
			}
			if x.Cond == nil && loopSleeps(x.Body) && p.background(fn, x.Pos(), true) {
				cron(fn, x.Pos(), "sleep-loop")
			}
		case *ast.RangeStmt:
			out = append(out, g.rangeRoutes(p, f, x, prefix, consumed)...)
		case *ast.CompositeLit:
			if s, ok := x.Type.(*ast.SelectorExpr); ok && s.Sel.Name == "Server" {
				if id, ok := s.X.(*ast.Ident); ok && f.imports[id.Name] == "net/http" {
					if h := concreteHandler(x); h != "" {
						e := g.entry(KindListener, "http.Server "+h, f.rel, x.Pos(), "http-server")
						if fn != nil {
							e.Detail = "in " + qualName(fn)
						}
						out = append(out, e)
					}
				}
			}
			if name, ok := temporalSchedule(f, x); ok && !boundAt(fn, kvExpr(x, "ID"), x.Pos()) {
				out = append(out, g.entry(KindCron, name, f.rel, x.Pos(), "temporal-schedule"))
			}
			if s, ok := x.Type.(*ast.SelectorExpr); ok && s.Sel.Name == "Command" {
				if id, ok := s.X.(*ast.Ident); ok && f.imports[id.Name] == cobraPkg {
					if use := kvString(x, "Use"); use != "" {
						out = append(out, g.entry(KindCLI, strings.Fields(use)[0], f.rel, x.Pos(), "cobra"))
					}
				}
			}
			if spec := kvString(x, "CronSchedule"); spec != "" {
				out = append(out, g.entry(KindCron, "CronSchedule "+spec, f.rel, x.Pos(), "temporal-cron"))
			}
		case *ast.SwitchStmt:
			if isMain && x.Tag != nil && !isArgSelector(x.Tag) {
				out = append(out, g.argvModes(p, fn, x)...)
			}
			if isMain && x.Tag != nil && isArgSelector(x.Tag) {
				for _, c := range x.Body.List {
					for _, e := range c.(*ast.CaseClause).List {
						if s, ok := stringLit(e); ok {
							out = append(out, g.entry(KindCLI, filepath.Base(p.dir)+" "+s, f.rel, e.Pos(), "argv-switch"))
						}
					}
				}
			}
		case *ast.CallExpr:
			if !consumed[x] {
				if es, handled := g.helperCall(p, f, fn, x, prefix); handled {
					out = append(out, es...)
					return true
				}
			}
			sel, ok := x.Fun.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if consumerMethods[sel.Sel.Name] && len(x.Args) > 0 && fn != nil {
				if id, ok := sel.X.(*ast.Ident); !ok || f.imports[id.Name] == "" {
					callback := false
					for _, a := range x.Args {
						if _, ok := a.(*ast.FuncLit); ok {
							callback = true
						}
					}
					switch {
					case callback:
						e := g.entry(KindQueue, qualName(fn)+" "+sel.Sel.Name, f.rel, x.Pos(), "subscribe-callback")
						out = append(out, e)
					case !ownFuncs[fn] && hasLoop(fn):
						ownFuncs[fn] = true
						e := g.declEntry(KindQueue, funcRef{fn, f.rel, g.fset}, "subscribe-loop")
						e.Detail = sel.Sel.Name
						out = append(out, e)
					}
				}
			}
			recv, _ := sel.X.(*ast.Ident)
			recvPkg := ""
			if recv != nil {
				recvPkg = f.imports[recv.Name]
			}
			name := sel.Sel.Name
			switch {
			case recvPkg == "time" && (name == "NewTicker" || name == "Tick"):
				if p.background(fn, x.Pos(), false) {
					cron(fn, x.Pos(), "ticker")
				}
			case recvPkg == "flag" && name == "Parse" && isMain:
				out = append(out, g.entry(KindCLI, filepath.Base(p.dir), f.rel, x.Pos(), "flag-main"))
			case recvPkg == "flag" && name == "NewFlagSet" && isMain && len(x.Args) > 0:
				if s, ok := stringLit(x.Args[0]); ok && s != "" {
					out = append(out, g.entry(KindCLI, filepath.Base(p.dir)+" "+s, f.rel, x.Pos(), "flagset"))
				}
			case name == "AddFunc" && len(x.Args) == 2:
				if s, ok := stringLit(x.Args[0]); ok && (strings.Count(s, " ") >= 4 || strings.HasPrefix(s, "@")) {
					out = append(out, g.entry(KindCron, "cron "+s, f.rel, x.Pos(), "robfig-cron"))
				}
			case name == "RegisterWorkflow" || name == "RegisterWorkflowWithOptions":
				if len(x.Args) > 0 {
					out = append(out, g.funcEntry(p, x, x.Args[0], KindWorkflow, "register-workflow"))
				}
			case name == "ExecuteChildWorkflow" && len(x.Args) > 1:
				if _, isStr := stringLit(x.Args[1]); !isStr {
					if ref, _, ok := g.resolveFunc(p, x.Args[1]); ok {
						out = append(out, g.declEntry(KindWorkflow, ref, "child-workflow"))
					}
				}
			case name == "RegisterActivityWithOptions" && len(x.Args) > 0:
				out = append(out, g.funcEntry(p, x, x.Args[0], KindActivity, "register-activity"))
			case name == "RegisterActivity" && len(x.Args) == 1:
				out = append(out, g.activityStruct(p, f, x, fn)...)
			case (name == "ExecuteActivity" || name == "ExecuteLocalActivity") && len(x.Args) > 1:
				if s, ok := stringLit(x.Args[1]); ok {
					out = append(out, g.entry(KindActivity, s, f.rel, x.Pos(), "execute-activity"))
				} else if ref, _, ok := g.resolveFunc(p, x.Args[1]); ok {
					out = append(out, g.declEntry(KindActivity, ref, "execute-activity"))
				}
			case name == "Route" && len(x.Args) == 2:
				if s, ok := stringLit(x.Args[0]); ok {
					if lit, ok := x.Args[1].(*ast.FuncLit); ok {
						inspect(lit.Body, prefix+s, fn)
						return false
					}
				}
			case name == "Methods" && len(x.Args) > 0:
				// gorilla/mux: r.HandleFunc("/p", h).Methods("GET")
				if inner, ok := sel.X.(*ast.CallExpr); ok {
					if path, ok := routePath(inner); ok && !genRoutes {
						consumed[inner] = true
						for _, a := range x.Args {
							if m, ok := stringLit(a); ok {
								out = append(out, g.entry(KindHTTP, m+" "+prefix+path, f.rel, inner.Pos(), "gorilla"))
							}
						}
					}
				}
			default:
				if genRoutes || consumed[x] {
					return true
				}
				if e, ok := g.route(p, fn, x, sel, recvPkg, prefix, f); ok {
					out = append(out, e)
				}
			}
		}
		return true
	}
	inspect(f.ast, "", nil)
	return out
}

// route recognises net/http, chi, gin, echo and httprouter registrations.
func (g *goScan) route(p *goPkg, fn *ast.FuncDecl, x *ast.CallExpr, sel *ast.SelectorExpr, recvPkg, prefix string, f *goFile) (Entry, bool) {
	name := sel.Sel.Name
	switch name {
	case "HandleFunc", "Handle":
		if len(x.Args) == 3 { // httprouter: Handle("GET", "/p", h)
			m, ok1 := g.evalStr(p, x.Args[0], nil, 0)
			pth, ok2 := g.evalStr(p, x.Args[1], nil, 0)
			if ok1 && ok2 && strings.HasPrefix(pth, "/") && isUpper(m) {
				return g.entry(KindHTTP, m+" "+prefix+pth, f.rel, x.Pos(), "httprouter"), true
			}
			return Entry{}, false
		}
		if len(x.Args) != 2 {
			return Entry{}, false
		}
		pat := g.render(p, x.Args[0], nil)
		if !strings.Contains(pat, "/") && !strings.HasPrefix(pat, "{") {
			return Entry{}, false
		}
		// A pattern made only of a parameter or a range variable is a
		// registration helper or an unexpanded table; its call sites and
		// rows are the routes.
		if !strings.Contains(pat, "/") && boundAt(fn, x.Args[0], x.Pos()) {
			return Entry{}, false
		}
		method, path := "ANY", pat
		if i := strings.Index(pat, " "); i > 0 && isUpper(pat[:i]) {
			method, path = pat[:i], strings.TrimSpace(pat[i+1:])
		}
		via := "net/http"
		if recvPkg == "http" {
			via = "net/http-default-mux"
		}
		return g.entry(KindHTTP, method+" "+prefix+path, f.rel, x.Pos(), via), true
	case "Method", "MethodFunc": // chi: r.Method("GET", "/p", h)
		if len(x.Args) == 3 {
			m, ok1 := g.evalStr(p, x.Args[0], nil, 0)
			pth, ok2 := g.evalStr(p, x.Args[1], nil, 0)
			if ok1 && ok2 && strings.HasPrefix(pth, "/") {
				return g.entry(KindHTTP, strings.ToUpper(m)+" "+prefix+pth, f.rel, x.Pos(), "chi"), true
			}
		}
	default:
		m, ok := httpMethods[name]
		if !ok || len(x.Args) < 2 || recvPkg != "" {
			return Entry{}, false
		}
		pth, ok := stringLit(x.Args[0])
		if !ok || !strings.HasPrefix(pth, "/") {
			return Entry{}, false
		}
		return g.entry(KindHTTP, m+" "+prefix+pth, f.rel, x.Pos(), "router-method"), true
	}
	return Entry{}, false
}

func routePath(c *ast.CallExpr) (string, bool) {
	sel, ok := c.Fun.(*ast.SelectorExpr)
	if !ok || (sel.Sel.Name != "HandleFunc" && sel.Sel.Name != "Handle") || len(c.Args) != 2 {
		return "", false
	}
	s, ok := stringLit(c.Args[0])
	return s, ok && strings.HasPrefix(s, "/")
}

func (g *goScan) funcEntry(p *goPkg, call *ast.CallExpr, arg ast.Expr, kind, via string) Entry {
	if ref, _, ok := g.resolveFunc(p, arg); ok {
		return g.declEntry(kind, ref, via)
	}
	return Entry{Kind: kind, Name: exprString(arg), File: relOf(g, call), Line: g.line(call.Pos()), Via: via}
}

func relOf(g *goScan, n ast.Node) string {
	rel, _ := filepath.Rel(g.root, g.fset.Position(n.Pos()).Filename)
	return filepath.ToSlash(rel)
}

// activityStruct expands RegisterActivity(x) where x is a struct: every
// exported method of its type taking a context.Context is an activity. A
// function argument is itself the activity.
func (g *goScan) activityStruct(p *goPkg, f *goFile, call *ast.CallExpr, fn *ast.FuncDecl) []Entry {
	arg := call.Args[0]
	if ref, _, ok := g.resolveFunc(p, arg); ok {
		return []Entry{g.declEntry(KindActivity, ref, "register-activity")}
	}
	t := g.exprType(p, arg, fn)
	if t == "" {
		return []Entry{{Kind: KindActivity, Name: exprString(arg) + " (unresolved struct)", File: f.rel, Line: g.line(call.Pos()), Via: "register-activity-struct"}}
	}
	var out []Entry
	owner := p
	if !p.types[t] {
		var defs []*goPkg
		for _, q := range g.pkgs {
			if q.types[t] {
				defs = append(defs, q)
			}
		}
		if len(defs) == 1 {
			owner = defs[0]
		}
	}
	for name, refs := range owner.funcs {
		if strings.Contains(name, ".") {
			continue
		}
		for _, r := range refs {
			if recvType(r.decl) == t && r.decl.Name.IsExported() && firstParamIsContext(r.decl) {
				out = append(out, g.declEntry(KindActivity, r, "register-activity-struct"))
			}
		}
	}
	return out
}

func firstParamIsContext(d *ast.FuncDecl) bool {
	if d.Type.Params == nil || len(d.Type.Params.List) == 0 {
		return false
	}
	s, ok := d.Type.Params.List[0].Type.(*ast.SelectorExpr)
	return ok && s.Sel.Name == "Context" && exprString(s.X) == "context"
}

// exprType guesses the named type of an expression: &T{}, T{}, NewT(...), or
// an identifier assigned from one of those (or declared as a parameter) in the
// enclosing function.
func (g *goScan) exprType(p *goPkg, e ast.Expr, fn *ast.FuncDecl) string {
	switch x := e.(type) {
	case *ast.UnaryExpr:
		return g.exprType(p, x.X, fn)
	case *ast.CompositeLit:
		return typeName(x.Type)
	case *ast.CallExpr:
		if ref, _, ok := g.resolveFunc(p, x.Fun); ok && ref.decl.Type.Results != nil && len(ref.decl.Type.Results.List) > 0 {
			return typeName(ref.decl.Type.Results.List[0].Type)
		}
	case *ast.Ident:
		if fn == nil {
			return ""
		}
		for _, fl := range fn.Type.Params.List {
			for _, n := range fl.Names {
				if n.Name == x.Name {
					return typeName(fl.Type)
				}
			}
		}
		found := ""
		ast.Inspect(fn.Body, func(n ast.Node) bool {
			if found != "" {
				return false
			}
			switch s := n.(type) {
			case *ast.AssignStmt:
				for i, l := range s.Lhs {
					if id, ok := l.(*ast.Ident); ok && id.Name == x.Name && i < len(s.Rhs) {
						found = g.exprType(p, s.Rhs[i], nil)
					}
				}
			case *ast.ValueSpec:
				for i, id := range s.Names {
					if id.Name == x.Name {
						if s.Type != nil {
							found = typeName(s.Type)
						} else if i < len(s.Values) {
							found = g.exprType(p, s.Values[i], nil)
						}
					}
				}
			}
			return true
		})
		return found
	}
	return ""
}

// loopSleeps reports whether a loop body (not counting nested function
// literals) waits on time.Sleep, time.After or a ticker channel.
func loopSleeps(body *ast.BlockStmt) bool {
	found := false
	ast.Inspect(body, func(n ast.Node) bool {
		if found {
			return false
		}
		switch x := n.(type) {
		case *ast.FuncLit:
			return false
		case *ast.CallExpr:
			s := exprString(x.Fun)
			if s == "time.Sleep" || s == "time.After" || s == "time.Tick" {
				found = true
			}
		case *ast.SelectorExpr:
			if x.Sel.Name == "C" && strings.Contains(strings.ToLower(exprString(x.X)), "tick") {
				found = true
			}
		}
		return true
	})
	return found
}

func isArgSelector(e ast.Expr) bool {
	s := exprString(e)
	return s == "os.Args[1]" || s == "flag.Arg(0)" || s == "args[0]"
}

func isUpper(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < 'A' || r > 'Z' {
			return false
		}
	}
	return true
}

func kvString(c *ast.CompositeLit, key string) string {
	for _, el := range c.Elts {
		kv, ok := el.(*ast.KeyValueExpr)
		if !ok {
			continue
		}
		if k, ok := kv.Key.(*ast.Ident); ok && k.Name == key {
			if s, ok := stringLit(kv.Value); ok {
				return s
			}
		}
	}
	return ""
}

func stringLit(e ast.Expr) (string, bool) {
	b, ok := e.(*ast.BasicLit)
	if !ok || b.Kind != token.STRING {
		return "", false
	}
	s, err := strconv.Unquote(b.Value)
	return s, err == nil
}

// strExpr renders a string expression: literals verbatim, concatenations
// joined, anything else as {expr}.
func strExpr(e ast.Expr) string {
	if s, ok := stringLit(e); ok {
		return s
	}
	if b, ok := e.(*ast.BinaryExpr); ok && b.Op == token.ADD {
		return strExpr(b.X) + strExpr(b.Y)
	}
	return "{" + exprString(e) + "}"
}

func exprString(e ast.Expr) string {
	switch x := e.(type) {
	case *ast.Ident:
		return x.Name
	case *ast.SelectorExpr:
		return exprString(x.X) + "." + x.Sel.Name
	case *ast.CallExpr:
		return exprString(x.Fun) + "(" + joinArgs(x.Args) + ")"
	case *ast.IndexExpr:
		return exprString(x.X) + "[" + exprString(x.Index) + "]"
	case *ast.BasicLit:
		return x.Value
	case *ast.StarExpr:
		return "*" + exprString(x.X)
	case *ast.UnaryExpr:
		return x.Op.String() + exprString(x.X)
	case *ast.ParenExpr:
		return "(" + exprString(x.X) + ")"
	case *ast.CompositeLit:
		return exprString(x.Type) + "{}"
	}
	return "?"
}

func joinArgs(args []ast.Expr) string {
	var s []string
	for _, a := range args {
		s = append(s, exprString(a))
	}
	return strings.Join(s, ", ")
}

// ---------------------------------------------------------------- TypeScript

var (
	testName     = regexp.MustCompile(`\.(test|spec|stories)\.[jt]sx?$`)
	nextExport   = regexp.MustCompile(`^export\s+(?:async\s+)?(?:function\s+|const\s+|let\s+)(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b`)
	nextReexport = regexp.MustCompile(`^export\s*\{([^}]*)\}`)
	trpcProc     = regexp.MustCompile(`^\s*([A-Za-z_$][\w$]*)\s*:\s*([A-Za-z_$][\w$]*[pP]rocedure)\b`)
	trpcFile     = regexp.MustCompile(`\brouter\(\s*\{|createTRPCRouter\(`)
)

func isTS(name string) bool {
	for _, s := range []string{".ts", ".tsx", ".js", ".mjs", ".jsx"} {
		if strings.HasSuffix(name, s) && !strings.HasSuffix(name, ".d.ts") {
			return true
		}
	}
	return false
}

func readLines(path string) []string {
	b, err := os.ReadFile(path)
	if err != nil || len(b) > 4<<20 {
		return nil
	}
	return strings.Split(string(b), "\n")
}

func scanTS(path, rel string) []Entry {
	base := filepath.Base(rel)
	stem := strings.TrimSuffix(base, filepath.Ext(base))
	segs := strings.Split(rel, "/")
	var out []Entry
	if stem == "route" {
		if url, ok := nextURL(segs[:len(segs)-1], "app"); ok {
			lines := readLines(path)
			for i, l := range lines {
				if m := nextExport.FindStringSubmatch(l); m != nil {
					out = append(out, Entry{Kind: KindNext, Name: m[1] + " " + url, File: rel, Line: i + 1, Via: "next-app-route"})
				} else if m := nextReexport.FindStringSubmatch(l); m != nil {
					for _, part := range strings.Split(m[1], ",") {
						f := strings.Fields(part)
						if len(f) > 0 && isUpper(f[len(f)-1]) && len(f[len(f)-1]) <= 7 {
							out = append(out, Entry{Kind: KindNext, Name: f[len(f)-1] + " " + url, File: rel, Line: i + 1, Via: "next-app-route"})
						}
					}
				}
			}
			if len(out) == 0 {
				out = append(out, Entry{Kind: KindNext, Name: "ANY " + url, File: rel, Line: 1, Via: "next-app-route"})
			}
			return out
		}
	}
	for i, s := range segs[:len(segs)-1] {
		if s == "pages" && i+1 < len(segs) && segs[i+1] == "api" {
			url, _ := nextURL(append(append([]string{}, segs[:len(segs)-1]...), stem), "pages")
			url = strings.TrimSuffix(url, "/index")
			return []Entry{{Kind: KindNext, Name: "ANY " + url, File: rel, Line: 1, Via: "next-pages-api"}}
		}
	}
	lines := readLines(path)
	if lines == nil || !trpcFile.MatchString(strings.Join(lines, "\n")) {
		return nil
	}
	proc := procedureConsts(lines)
	for i, l := range lines {
		if m := trpcProc.FindStringSubmatch(l); m != nil {
			out = append(out, Entry{Kind: KindTRPC, Name: stem + "." + m[1], File: rel, Line: i + 1, Via: "trpc"})
		} else if m := tsRouterKey.FindStringSubmatch(l); m != nil && proc[m[2]] {
			out = append(out, Entry{Kind: KindTRPC, Name: stem + "." + m[1], File: rel, Line: i + 1, Via: "trpc-local-procedure", Detail: "built from " + m[2]})
		}
	}
	return out
}

// nextURL turns the directory segments after the last `root` segment into a
// route path: route groups vanish and [param] becomes {param}.
func nextURL(dirs []string, root string) (string, bool) {
	at := -1
	for i, s := range dirs {
		if s == root {
			at = i
		}
	}
	if at < 0 {
		return "", false
	}
	var parts []string
	for _, s := range dirs[at+1:] {
		switch {
		case strings.HasPrefix(s, "(") && strings.HasSuffix(s, ")"), strings.HasPrefix(s, "@"):
			continue
		case strings.HasPrefix(s, "[[...") && strings.HasSuffix(s, "]]"):
			parts = append(parts, "{"+s[5:len(s)-2]+"...}")
		case strings.HasPrefix(s, "[...") && strings.HasSuffix(s, "]"):
			parts = append(parts, "{"+s[4:len(s)-1]+"...}")
		case strings.HasPrefix(s, "[") && strings.HasSuffix(s, "]"):
			parts = append(parts, "{"+s[1:len(s)-1]+"}")
		default:
			parts = append(parts, s)
		}
	}
	return "/" + strings.Join(parts, "/"), true
}

// ---------------------------------------------------------------- Python and config

var (
	pyMain    = regexp.MustCompile(`^if\s+__name__\s*==\s*['"]__main__['"]\s*:`)
	pySub     = regexp.MustCompile(`\.add_parser\(\s*['"]([\w:.-]+)['"]`)
	pyDeco    = regexp.MustCompile(`^@(?:[\w.]+\.)?(command|group)\(`)
	pyDef     = regexp.MustCompile(`^(?:async\s+)?def\s+(\w+)`)
	tomlSect  = regexp.MustCompile(`^\[(.+)\]\s*$`)
	tomlKV    = regexp.MustCompile(`^["']?([\w.-]+)["']?\s*=\s*["']([^"']+)["']`)
	tfRes     = regexp.MustCompile(`^resource\s+"([\w-]+)"\s+"([\w-]+)"`)
	tfSched   = regexp.MustCompile(`^\s*schedule(?:_expression)?\s*=\s*"([^"]+)"`)
	yamlKind  = regexp.MustCompile(`^kind:\s*CronJob\s*$`)
	yamlName  = regexp.MustCompile(`^\s{2}name:\s*["']?([\w.-]+)`)
	yamlSched = regexp.MustCompile(`^\s+-?\s*cron:\s*["']([^"']+)["']`)
)

func scanPython(path, rel string) []Entry {
	lines := readLines(path)
	stem := strings.TrimSuffix(filepath.Base(rel), ".py")
	if stem == "__main__" {
		stem = filepath.Base(filepath.Dir(rel))
	}
	var out []Entry
	for i, l := range lines {
		switch {
		case pyMain.MatchString(l):
			out = append(out, Entry{Kind: KindPyCLI, Name: stem, File: rel, Line: i + 1, Via: "py-main"})
		case pySub.MatchString(l):
			out = append(out, Entry{Kind: KindPyCLI, Name: stem + " " + pySub.FindStringSubmatch(l)[1], File: rel, Line: i + 1, Via: "argparse-subcommand"})
		case pyDeco.MatchString(l):
			for j := i + 1; j < len(lines) && j < i+8; j++ {
				if m := pyDef.FindStringSubmatch(strings.TrimSpace(lines[j])); m != nil {
					out = append(out, Entry{Kind: KindPyCLI, Name: stem + " " + m[1], File: rel, Line: i + 1, Via: "click-typer"})
					break
				}
			}
		}
	}
	return out
}

func scanPyproject(path, rel string) []Entry {
	var out []Entry
	sect := ""
	for i, l := range readLines(path) {
		if m := tomlSect.FindStringSubmatch(strings.TrimSpace(l)); m != nil {
			sect = m[1]
			continue
		}
		if sect == "project.scripts" || sect == "tool.poetry.scripts" {
			if m := tomlKV.FindStringSubmatch(strings.TrimSpace(l)); m != nil {
				out = append(out, Entry{Kind: KindPyCLI, Name: m[1], File: rel, Line: i + 1, Via: "pyproject-scripts"})
			}
		}
	}
	return out
}

func scanTerraform(path, rel string) []Entry {
	var out []Entry
	res := ""
	for i, l := range readLines(path) {
		if m := tfRes.FindStringSubmatch(l); m != nil {
			res = m[1] + "." + m[2]
		}
		if m := tfSched.FindStringSubmatch(l); m != nil && (strings.HasPrefix(m[1], "rate(") || strings.HasPrefix(m[1], "cron(") || strings.Count(m[1], " ") >= 4) {
			out = append(out, Entry{Kind: KindCron, Name: res + " " + m[1], File: rel, Line: i + 1, Via: "terraform-schedule"})
		}
	}
	return out
}

func scanYAML(path, rel string) []Entry {
	lines := readLines(path)
	var out []Entry
	for i, l := range lines {
		if yamlKind.MatchString(l) {
			name := "CronJob"
			for j := i + 1; j < len(lines) && j < i+15; j++ {
				if m := yamlName.FindStringSubmatch(lines[j]); m != nil {
					name = "CronJob " + m[1]
					break
				}
			}
			out = append(out, Entry{Kind: KindCron, Name: name, File: rel, Line: i + 1, Via: "k8s-cronjob"})
		}
		if strings.Contains(rel, ".github/workflows/") {
			if m := yamlSched.FindStringSubmatch(l); m != nil {
				out = append(out, Entry{Kind: KindCron, Name: "gha " + strings.TrimSuffix(filepath.Base(rel), filepath.Ext(rel)) + " " + m[1], File: rel, Line: i + 1, Via: "gha-schedule"})
			}
		}
	}
	return out
}

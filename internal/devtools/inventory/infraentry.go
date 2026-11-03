package main

// Entry points outside Go: tRPC procedures built from local procedure
// consts or factories, Python HTTP handlers (FastAPI decorators and
// BaseHTTPRequestHandler path switches), AWS Lambda handlers named by
// terraform, Vercel crons and Nomad job files.

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// ---------------------------------------------------------------- tRPC

var (
	tsConstDecl = regexp.MustCompile(`^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::[^=]*)?=(.*)$`)
	tsRouterKey = regexp.MustCompile(`^\s*([A-Za-z_$][\w$]*)\s*:\s*([A-Za-z_$][\w$]*)\b`)
	tsProcWord  = regexp.MustCompile(`\b[A-Za-z_$][\w$]*[pP]rocedure\b`)
	tsRouterNew = regexp.MustCompile(`^\s*(?:[\w$]+\.)?(?:router|createTRPCRouter|mergeRouters)\(`)
)

// procedureConsts finds a router file's local procedure builders: consts
// whose initializer (its first lines) starts from a *Procedure or from
// another such const, like `const read = orgProcedure.use(...)` or the
// factory `const action = (p) => adminProcedure.input(...)`.
func procedureConsts(lines []string) map[string]bool {
	type decl struct {
		name, init string
	}
	var decls []decl
	for i, l := range lines {
		m := tsConstDecl.FindStringSubmatch(l)
		if m == nil || tsRouterNew.MatchString(m[2]) {
			continue
		}
		init := m[2]
		for j := i + 1; j < len(lines) && j <= i+3 && !strings.HasSuffix(strings.TrimSpace(init), ";"); j++ {
			if tsConstDecl.MatchString(lines[j]) {
				break
			}
			init += "\n" + lines[j]
		}
		decls = append(decls, decl{m[1], init})
	}
	proc := map[string]bool{}
	for round := 0; round < 4; round++ {
		grew := false
		for _, d := range decls {
			if proc[d.name] {
				continue
			}
			hit := tsProcWord.MatchString(d.init)
			for name := range proc {
				if !hit && regexp.MustCompile(`(^|[^\w$.])`+regexp.QuoteMeta(name)+`\b`).MatchString(d.init) {
					hit = true
				}
			}
			if hit {
				proc[d.name] = true
				grew = true
			}
		}
		if !grew {
			break
		}
	}
	return proc
}

// ---------------------------------------------------------------- Python HTTP

var pyHTTPHint = []byte("HTTPRequestHandler")

// scanPyHTTP finds a Python file's HTTP routes: FastAPI decorators (when the
// python-gpu plugin, which lists them itself, is off) and the paths a
// BaseHTTPRequestHandler's do_<METHOD> methods compare self.path with.
func scanPyHTTP(path, rel string, fastapi bool) []Entry {
	src, err := os.ReadFile(path)
	if err != nil || len(src) > 4<<20 {
		return nil
	}
	handler := bytes.Contains(src, pyHTTPHint)
	fastapi = fastapi && (bytes.Contains(src, []byte("@app.")) || bytes.Contains(src, []byte("router.")))
	if !handler && !fastapi {
		return nil
	}
	f := parsePy(rel, src)
	var out []Entry
	if fastapi {
		out = append(out, (&pyGPU{}).routes(f)...)
	}
	if handler {
		out = append(out, handlerRoutes(f)...)
	}
	return out
}

// handlerRoutes reads `if self.path == "/x":` branches (an entry at the
// branch) and `if self.path != "/x": reject` guards (an entry at the
// method, which serves that one path) in do_GET, do_POST, ... methods of
// http.server request-handler classes.
func handlerRoutes(f *pyFile) []Entry {
	consts := map[string]string{}
	for _, l := range f.lines {
		if l.indent == 0 && l.hi-l.lo == 3 && f.ident(l.lo) && f.p(l.lo+1, "=") && f.toks[l.lo+2].k == 's' {
			consts[f.s(l.lo)] = f.toks[l.lo+2].s
		}
	}
	var out []Entry
	for _, c := range f.defs {
		if c.kind != "class" {
			continue
		}
		isHandler := false
		for _, b := range c.bases {
			if strings.HasSuffix(b, "HTTPRequestHandler") {
				isHandler = true
			}
		}
		if !isHandler {
			continue
		}
		for _, m := range f.defs {
			if m.owner != c || m.kind != "def" || !strings.HasPrefix(m.name, "do_") || !isUpper(m.name[3:]) {
				continue
			}
			verb := m.name[3:]
			for i := m.lo; i < m.hi; i++ {
				if !f.is(i, 'i', "path") || !f.p(i-1, ".") {
					continue
				}
				k, eq := i+2, true
				switch {
				case f.p(i+1, "=="):
				case f.p(i+1, "!") && f.p(i+2, "="):
					k, eq = i+3, false
				default:
					continue
				}
				var p string
				switch {
				case k < len(f.toks) && f.toks[k].k == 's':
					p = f.toks[k].s
				case f.ident(k) && consts[f.s(k)] != "":
					p = consts[f.s(k)]
				default:
					continue
				}
				if !strings.HasPrefix(p, "/") {
					continue
				}
				e := Entry{Kind: KindHTTP, Name: verb + " " + p, File: f.rel, Line: f.toks[i].line, Via: "http-handler-class", Detail: c.name + "." + m.name}
				if !eq {
					e.Line, e.EndLine = m.line, m.endLine
				}
				out = append(out, e)
			}
		}
	}
	return out
}

// ---------------------------------------------------------------- Terraform Lambdas

var (
	tfHandler   = regexp.MustCompile(`^\s*handler\s*=\s*"([\w./-]+)\.(\w+)"`)
	tfSource    = regexp.MustCompile(`^\s*source_(file|dir)\s*=\s*"\$\{path\.module\}/([^"]+)"`)
	tfLambdaRef = regexp.MustCompile(`aws_lambda_function\.([\w-]+)`)
)

// tfLambdas resolves each aws_lambda_function's handler ("module.function")
// to the function in the module's source (source_file / source_dir under
// path.module, or the module directory): a queue-consumer when an
// aws_lambda_event_source_mapping feeds it (an SQS queue, a Kinesis or
// DynamoDB stream), a lambda-handler otherwise.
func tfLambdas(root string, files [][2]string, testSupportOK bool) []Entry {
	byDir := map[string][][2]string{}
	for _, f := range files {
		d := filepath.Dir(f[1])
		byDir[d] = append(byDir[d], f)
	}
	dirs := make([]string, 0, len(byDir))
	for d := range byDir {
		dirs = append(dirs, d)
	}
	sort.Strings(dirs)
	var out []Entry
	for _, dir := range dirs {
		type fnRes struct{ name, mod, fn string }
		var fns []fnRes
		var sources [][2]string // kind, path
		mapped := map[string]bool{}
		for _, f := range byDir[dir] {
			res := ""
			for _, l := range readLines(f[0]) {
				if m := tfRes.FindStringSubmatch(l); m != nil {
					res = m[1] + "." + m[2]
				}
				if m := tfSource.FindStringSubmatch(l); m != nil {
					sources = append(sources, [2]string{m[1], m[2]})
				}
				switch {
				case strings.HasPrefix(res, "aws_lambda_function."):
					if m := tfHandler.FindStringSubmatch(l); m != nil {
						fns = append(fns, fnRes{strings.TrimPrefix(res, "aws_lambda_function."), m[1], m[2]})
					}
				case strings.HasPrefix(res, "aws_lambda_event_source_mapping."):
					if strings.Contains(l, "function_name") {
						if m := tfLambdaRef.FindStringSubmatch(l); m != nil {
							mapped[m[1]] = true
						}
					}
				}
			}
		}
		for _, fn := range fns {
			var cands []string
			for _, s := range sources {
				if s[0] == "file" {
					if strings.TrimSuffix(s[1], filepath.Ext(s[1])) == fn.mod || strings.TrimSuffix(filepath.Base(s[1]), filepath.Ext(s[1])) == fn.mod {
						cands = append(cands, s[1])
					}
					continue
				}
				for _, ext := range []string{".py", ".js", ".mjs", ".cjs", ".ts"} {
					cands = append(cands, filepath.Join(s[1], fn.mod+ext))
				}
			}
			for _, ext := range []string{".py", ".js", ".mjs", ".cjs", ".ts"} {
				cands = append(cands, fn.mod+ext, filepath.Join("lambda", fn.mod+ext), filepath.Join("src", fn.mod+ext))
			}
			for _, c := range cands {
				rel := filepath.ToSlash(filepath.Clean(filepath.Join(dir, c)))
				if strings.HasPrefix(rel, "../") || secretFile(filepath.Base(rel)) {
					continue
				}
				if !testSupportOK && testSupportPath(rel) {
					continue
				}
				q := regexp.QuoteMeta(fn.fn)
				re := regexp.MustCompile(`^(?:export\s+(?:async\s+)?function\s+` + q + `\b|export\s+(?:const|let)\s+` + q + `\b|(?:module\.)?exports\.` + q + `\s*=)`)
				if strings.HasSuffix(rel, ".py") {
					re = regexp.MustCompile(`^(?:async\s+)?def\s+` + q + `\s*\(`)
				}
				line := 0
				for i, l := range readLines(filepath.Join(root, rel)) {
					if re.MatchString(l) {
						line = i + 1
						break
					}
				}
				if line == 0 {
					continue
				}
				kind := KindLambda
				if mapped[fn.name] {
					kind = KindQueue
				}
				out = append(out, Entry{Kind: kind, Name: "lambda " + fn.name, File: rel, Line: line, Via: "terraform-lambda",
					Detail: "aws_lambda_function." + fn.name + " handler " + fn.mod + "." + fn.fn})
				break
			}
		}
	}
	return out
}

func testSupportPath(rel string) bool {
	for _, s := range strings.Split(filepath.Dir(rel), "/") {
		if testSupport.MatchString(s) {
			return true
		}
	}
	return false
}

// ---------------------------------------------------------------- Vercel and Nomad

// scanVercel lists vercel.json crons: each path the platform calls on its
// schedule.
func scanVercel(path, rel string) []Entry {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var doc struct {
		Crons []struct {
			Path     string `json:"path"`
			Schedule string `json:"schedule"`
		} `json:"crons"`
	}
	if json.Unmarshal(b, &doc) != nil || len(doc.Crons) == 0 {
		return nil
	}
	lines := strings.Split(string(b), "\n")
	start := 0
	for i, l := range lines {
		if strings.Contains(l, `"crons"`) {
			start = i
			break
		}
	}
	var out []Entry
	at := start
	for _, c := range doc.Crons {
		line := start + 1
		for i := at; i < len(lines); i++ {
			if strings.Contains(lines[i], `"`+c.Path+`"`) {
				line, at = i+1, i+1
				break
			}
		}
		out = append(out, Entry{Kind: KindCron, Name: "vercel " + c.Path + " " + c.Schedule, File: rel, Line: line, Via: "vercel-cron"})
	}
	return out
}

var (
	nomadJob      = regexp.MustCompile(`^job\s+"([^"]+)"\s*\{`)
	nomadPeriodic = regexp.MustCompile(`^\s*crons?\s*=\s*\[?\s*"([^"]+)"`)
)

// scanNomad lists the jobs of a Nomad job file, and the cron specs of
// periodic ones.
func scanNomad(path, rel string) []Entry {
	var out []Entry
	job := ""
	periodic := false
	for i, l := range readLines(path) {
		if m := nomadJob.FindStringSubmatch(l); m != nil {
			job, periodic = m[1], false
			out = append(out, Entry{Kind: KindNomad, Name: "job " + job, File: rel, Line: i + 1, Via: "nomad-file"})
			continue
		}
		if job == "" {
			continue
		}
		if strings.HasPrefix(strings.TrimSpace(l), "periodic ") || strings.TrimSpace(l) == "periodic {" {
			periodic = true
		}
		if m := nomadPeriodic.FindStringSubmatch(l); m != nil && periodic {
			out = append(out, Entry{Kind: KindCron, Name: "nomad " + job + " " + m[1], File: rel, Line: i + 1, Via: "nomad-periodic"})
		}
	}
	return out
}

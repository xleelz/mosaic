package main

// The exemptions lint (DESIGN §15.2): each lint exemption's citation must
// resolve, and its cited lines must plausibly support it:
//   - racy_in_code: the lines hold a read and an unconditional write;
//   - single_writer: a lease, leader or lock token;
//   - reachable_by: a CEL expression that compiles, or a note with a citation;
//   - choice_ok: random, network, time or external tokens.
//
// Citations are path:line[-end][, line...] anywhere in the value. A path that
// doesn't resolve under --code is tried against the directories the entity
// cites, then as a unique suffix of a file under the root (notes often cite
// a bare file name). Without --code, only the citations' presence and the
// CEL are checked; the line checks are counted as not verified.

import (
	"fmt"
	"io"
	"io/fs"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// exemptCiteRE matches path:line, path:line-end, path:line- and the extra
// lines of the same file ("client.ts:87, 201").
var (
	exemptCiteRE  = regexp.MustCompile(`([A-Za-z0-9_./-]*[A-Za-z0-9_-]\.[A-Za-z0-9]+):(\d+)(?:(-)(\d*))?((?:\s*,\s*\d+(?:-\d+)?(?:[^\w.:/-]|$))*)`)
	exemptExtraRE = regexp.MustCompile(`\d+(?:-\d+)?`)
)

type exemptCite struct {
	Path   string
	Ranges [][2]int // [line, end]; end 0: open (line-)
	Text   string
}

func parseExemptCites(s string) []exemptCite {
	var out []exemptCite
	for _, m := range exemptCiteRE.FindAllStringSubmatch(s, -1) {
		c := exemptCite{Path: m[1], Text: strings.TrimRight(strings.TrimSpace(m[0]), ",;)")}
		lo, _ := strconv.Atoi(m[2])
		hi := lo
		switch {
		case m[4] != "":
			hi, _ = strconv.Atoi(m[4])
		case m[3] != "":
			hi = 0 // "path:378-": open-ended
		}
		c.Ranges = append(c.Ranges, [2]int{lo, hi})
		for _, extra := range exemptExtraRE.FindAllString(m[5], -1) {
			a, b, _ := strings.Cut(extra, "-")
			x, _ := strconv.Atoi(a)
			y := x
			if b != "" {
				y, _ = strconv.Atoi(b)
			}
			c.Ranges = append(c.Ranges, [2]int{x, y})
		}
		out = append(out, c)
	}
	return out
}

// codeWords splits code or prose into lower-case words, breaking
// identifiers at camelCase and snake_case: GetItem -> get, item.
func codeWords(lines []string) map[string]bool {
	out := map[string]bool{}
	for _, l := range lines {
		var cur []rune
		flush := func() {
			if len(cur) > 0 {
				out[strings.ToLower(string(cur))] = true
				cur = cur[:0]
			}
		}
		rs := []rune(l)
		for i, r := range rs {
			if !unicode.IsLetter(r) && !unicode.IsDigit(r) {
				flush()
				continue
			}
			if unicode.IsUpper(r) && len(cur) > 0 {
				prev := cur[len(cur)-1]
				nextLower := i+1 < len(rs) && unicode.IsLower(rs[i+1])
				if unicode.IsLower(prev) || unicode.IsDigit(prev) || (unicode.IsUpper(prev) && nextLower) {
					flush()
				}
			}
			cur = append(cur, r)
		}
		flush()
	}
	return out
}

func wordSet(s string) map[string]bool {
	out := map[string]bool{}
	for _, w := range strings.Fields(s) {
		out[w] = true
	}
	return out
}

var (
	exemptReadWords   = wordSet("get gets load loads loaded read reads fetch fetches find lookup select query scan describe list peek exists has contains retrieve")
	exemptWriteWords  = wordSet("put puts set sets update updates save saves insert write writes store upsert delete remove create mark persist replace patch exec commit append incr increment decr add push")
	exemptLockWords   = wordSet("lease leases leased leader leaders leadership lock locks locked locking unlock mutex rwmutex mu election elect elected semaphore singleflight fence fenced fencing flock")
	exemptChoiceWords = wordSet(
		// random
		"rand random randomly randn randint shuffle jitter uuid nonce entropy seed sample " +
			// network
			"http https net dial grpc rpc request response fetch client socket tcp udp conn connection timeout retry remote upstream endpoint url status " +
			// time
			"time now clock deadline sleep timer ticker duration elapsed since until ttl expire expired expiry expires " +
			// external
			"external provider guest webhook api vendor customer workload callback")
	// A read without a read verb: a call's result assigned (rows, err := s.idx.OrgsFor(...)).
	exemptReadAssign = regexp.MustCompile(`\w\s*:?=\s*(?:await\s+)?[\w.]+\(`)
	exemptAssign     = regexp.MustCompile(`[^=!<>:+\-*/%&|^]=[^=]|\+\+|\+=|-=`)
)

// exemptIndex resolves exemption citations against a code root.
type exemptIndex struct {
	root  *codeRoot
	files map[string][]string // base name -> paths under the root (built on first need)
}

func (e *exemptIndex) ok(p string) bool {
	st, _ := e.root.resolve(model.Source{Path: p})
	return st == citeOK
}

// candidates are the files a cited path may name: itself under the root, the
// path under a directory the entity cites, or a unique suffix match.
func (e *exemptIndex) candidates(p string, dirs []string) []string {
	p = normPath(p)
	if e.ok(p) {
		return []string{p}
	}
	for _, d := range dirs {
		if q := path.Join(d, p); e.ok(q) {
			return []string{q}
		}
	}
	if e.files == nil {
		e.files = map[string][]string{}
		_ = filepath.WalkDir(e.root.root, func(fp string, d fs.DirEntry, err error) error {
			if err != nil {
				return nil
			}
			if d.IsDir() {
				if n := d.Name(); n == ".git" || n == "node_modules" || n == ".venv" {
					return filepath.SkipDir
				}
				return nil
			}
			rel, err := filepath.Rel(e.root.root, fp)
			if err == nil {
				rel = filepath.ToSlash(rel)
				e.files[path.Base(rel)] = append(e.files[path.Base(rel)], rel)
			}
			return nil
		})
	}
	var out []string
	for _, f := range e.files[path.Base(p)] {
		if f == p || strings.HasSuffix(f, "/"+p) {
			out = append(out, f)
		}
	}
	// Prefer the matches under a directory the entity cites.
	var near []string
	for _, f := range out {
		for _, d := range dirs {
			if d != "." && strings.HasPrefix(f, d+"/") {
				near = append(near, f)
				break
			}
		}
	}
	if len(near) > 0 {
		return near
	}
	return out
}

// lines returns the cited lines of one citation in one file, with two lines
// of context around a single line, or "" and a problem.
func (e *exemptIndex) lines(file string, c exemptCite) ([]string, string) {
	all := e.root.file(file)
	var out []string
	for _, r := range c.Ranges {
		lo, hi := r[0], r[1]
		if lo < 1 || lo > len(all) || hi > len(all) {
			return nil, fmt.Sprintf("%s: line %d past the end of %s (%d lines)", c.Text, max(lo, hi), file, len(all))
		}
		switch {
		case hi == 0:
			hi = min(lo+20, len(all))
		case hi == lo:
			lo, hi = max(1, lo-2), min(len(all), lo+2)
		case hi < lo:
			hi = lo
		}
		out = append(out, all[lo-1:min(hi, lo+80)]...)
	}
	return out, ""
}

// exemption is one claim a lint honors.
type exemption struct {
	Kind, Subject, Frag, Value string
	Dirs                       []string       // directories the entity cites
	Fallback                   []model.Source // cited lines to read when the value cites none (choice_ok)
}

type exemptionReport struct {
	*integrityReport
	Kinds      map[string][2]int // kind -> [exemptions, issues]
	Unverified int
}

func sourceDirs(srcs ...[]model.Source) []string {
	seen := map[string]bool{}
	var out []string
	for _, ss := range srcs {
		for _, s := range ss {
			if s.Path == "" || isPacked(s) {
				continue
			}
			d := path.Dir(normPath(s.Path))
			if !seen[d] {
				seen[d] = true
				out = append(out, d)
			}
		}
	}
	sort.Strings(out)
	return out
}

// collectExemptions lists every racy_in_code, single_writer and choice_ok
// attribute of interfaces and components, every error's reachable_by, and
// the interfaces' attributes.reachable_by.
func collectExemptions(doc *model.Document, origins map[string]string) []exemption {
	x := indexed(doc)
	var out []exemption
	str := func(v any) string {
		switch t := v.(type) {
		case string:
			return t
		case nil:
			return ""
		}
		return fmt.Sprint(v)
	}
	for _, c := range doc.Components {
		frag := origins[model.KindComponent+"/"+c.ID]
		dirs := sourceDirs(c.Sources)
		for _, k := range []string{"racy_in_code", "single_writer", "choice_ok"} {
			if v, ok := c.Attributes[k]; ok {
				out = append(out, exemption{Kind: k, Subject: "component " + c.ID, Frag: frag, Value: str(v), Dirs: dirs, Fallback: c.Sources})
			}
		}
	}
	for _, i := range doc.Interfaces {
		frag := origins[model.KindInterface+"/"+i.ID]
		var csrc []model.Source
		if c := x.Components[i.Component]; c != nil {
			csrc = c.Sources
		}
		dirs := sourceDirs(i.Sources, csrc)
		who := "interface " + i.ID
		for _, k := range []string{"racy_in_code", "single_writer"} {
			if v, ok := i.Attributes[k]; ok {
				out = append(out, exemption{Kind: k, Subject: who, Frag: frag, Value: str(v), Dirs: dirs})
			}
		}
		if v, ok := i.Attributes["choice_ok"]; ok {
			sites := choiceSites(&i)
			fallback := func(choice string) []model.Source {
				for _, s := range sites {
					if (choice == "" || s.step.Choice == choice) && s.step.Source != nil {
						return []model.Source{*s.step.Source}
					}
				}
				return i.Sources
			}
			switch t := v.(type) {
			case map[string]any:
				for _, ch := range sortedKeys(t) {
					out = append(out, exemption{Kind: "choice_ok", Subject: who + " choice " + ch, Frag: frag, Value: str(t[ch]), Dirs: dirs, Fallback: fallback(ch)})
				}
			default:
				out = append(out, exemption{Kind: "choice_ok", Subject: who, Frag: frag, Value: str(v), Dirs: dirs, Fallback: fallback("")})
			}
		}
		for _, e := range i.Errors {
			if e.ReachableBy != "" {
				out = append(out, exemption{Kind: "reachable_by", Subject: who + " error " + e.Code, Frag: frag, Value: e.ReachableBy, Dirs: dirs})
			}
		}
		switch t := i.Attributes["reachable_by"].(type) {
		case nil:
		case map[string]any:
			for _, code := range sortedKeys(t) {
				out = append(out, exemption{Kind: "reachable_by", Subject: who + " attributes.reachable_by." + code, Frag: frag, Value: str(t[code]), Dirs: dirs})
			}
		case []any:
			for _, code := range t {
				out = append(out, exemption{Kind: "reachable_by", Subject: who + " attributes.reachable_by " + str(code), Frag: frag, Dirs: dirs})
			}
		default:
			out = append(out, exemption{Kind: "reachable_by", Subject: who + " attributes.reachable_by", Frag: frag, Value: str(t), Dirs: dirs})
		}
	}
	return out
}

// celCompiles reports whether a reachable_by value is a CEL expression (a
// leading "=" allowed) over the behavior variables.
func celCompiles(v string) bool {
	v = strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(v), "="))
	if v == "" || v == "*" {
		return false
	}
	_, err := expr.Behavior.Compile(v)
	return err == nil
}

// lintExemptions checks every exemption. root may be nil (no --code).
func lintExemptions(doc *model.Document, origins map[string]string, root *codeRoot) *exemptionReport {
	r := &exemptionReport{integrityReport: &integrityReport{Lint: "exemptions", Unit: "exemptions with issues"}, Kinds: map[string][2]int{}}
	sc := shareCounter{}
	var idx *exemptIndex
	if root != nil {
		idx = &exemptIndex{root: root}
	}
	for _, ex := range collectExemptions(doc, origins) {
		why := checkExemption(ex, idx, &r.Unverified)
		k := r.Kinds[ex.Kind]
		k[0]++
		if why != "" {
			k[1]++
			r.Findings = append(r.Findings, integrityFinding{"exemptions (" + ex.Kind + ")", ex.Frag, ex.Subject, why})
		}
		r.Kinds[ex.Kind] = k
		sc.add(ex.Frag, why != "")
	}
	r.finish(sc)
	return r
}

// checkExemption returns why an exemption isn't supported, or "".
func checkExemption(ex exemption, idx *exemptIndex, unverified *int) string {
	val := strings.TrimSpace(ex.Value)
	if ex.Kind == "reachable_by" {
		if val == "" || val == "*" {
			return "names no CEL expression and no note with a citation; give {reachable_by: \"<cel>\"} or a note citing path:line"
		}
		if celCompiles(val) {
			return ""
		}
	}
	if val == "" {
		return "empty; give the reason with a path:line citation"
	}
	cites := parseExemptCites(val)
	if len(cites) == 0 && ex.Kind != "choice_ok" {
		if ex.Kind == "reachable_by" {
			return "neither CEL that compiles nor a note with a path:line citation"
		}
		return "no path:line citation of the code that supports it"
	}
	if idx == nil {
		*unverified++
		return ""
	}
	var lines []string
	var probs []string
	resolved := 0
	for _, c := range cites {
		files := idx.candidates(c.Path, ex.Dirs)
		if len(files) == 0 {
			probs = append(probs, c.Text+" doesn't resolve under --code")
			continue
		}
		okOne := false
		var lastProb string
		for _, f := range files {
			ls, prob := idx.lines(f, c)
			if prob != "" {
				lastProb = prob
				continue
			}
			okOne = true
			lines = append(lines, ls...)
		}
		if okOne {
			resolved++
		} else {
			probs = append(probs, lastProb)
		}
	}
	if len(cites) == 0 { // choice_ok without a citation: the choice's own cited lines
		for _, s := range ex.Fallback {
			if s.Path == "" || isPacked(s) {
				continue
			}
			c := exemptCite{Path: s.Path, Text: s.String(), Ranges: [][2]int{{s.Line, s.EndLine}}}
			if s.Line <= 0 {
				continue
			}
			if c.Ranges[0][1] < s.Line {
				c.Ranges[0][1] = s.Line
			}
			for _, f := range idx.candidates(s.Path, ex.Dirs) {
				if ls, prob := idx.lines(f, c); prob == "" {
					lines = append(lines, ls...)
					resolved++
					break
				}
			}
		}
		if resolved == 0 {
			return "cites no code, and the choice's own sources don't resolve under --code; give the reason with a path:line citation"
		}
	}
	if len(probs) > 0 && (ex.Kind != "reachable_by" || resolved == 0) {
		return strings.Join(probs, "; ")
	}
	words := codeWords(lines)
	has := func(set map[string]bool) bool {
		for w := range words {
			if set[w] {
				return true
			}
		}
		return false
	}
	switch ex.Kind {
	case "racy_in_code":
		rd, wr := has(exemptReadWords), has(exemptWriteWords)
		for _, l := range lines {
			rd = rd || exemptReadAssign.MatchString(l)
		}
		if !wr {
			for _, l := range lines {
				if exemptAssign.MatchString(l) {
					wr = true
					break
				}
			}
		}
		switch {
		case !rd && !wr:
			return "the cited lines hold neither a read nor a write"
		case !rd:
			return "the cited lines hold a write but no read"
		case !wr:
			return "the cited lines hold a read but no write"
		}
	case "single_writer":
		if !has(exemptLockWords) {
			return "the cited lines hold no lease, leader or lock token"
		}
	case "choice_ok":
		if !has(exemptChoiceWords) {
			return "the cited lines hold no random, network, time or external token"
		}
	}
	return ""
}

// print reports the issues (gated by --max-exemption-issues N when N >= 0)
// with the counts per kind, and reports whether the gate failed.
func (r *exemptionReport) print(w io.Writer, maxIssues int, code bool, quiet bool) bool {
	r.integrityReport.print(w, -1, quiet)
	over := maxIssues >= 0 && len(r.Findings) > maxIssues
	if maxIssues >= 0 {
		mark := " "
		if over {
			mark = "✗"
		}
		fmt.Fprintf(w, "%s --max-exemption-issues %d: %d issues\n", mark, maxIssues, len(r.Findings))
	}
	var parts []string
	for _, k := range []string{"racy_in_code", "single_writer", "reachable_by", "choice_ok"} {
		c := r.Kinds[k]
		parts = append(parts, fmt.Sprintf("%s %d of %d", k, c[1], c[0]))
	}
	note := ""
	if !code {
		note = fmt.Sprintf("; %d citations not checked against code (no --code)", r.Unverified)
	}
	fmt.Fprintf(w, "exemption issues by kind: %s%s\n", strings.Join(parts, ", "), note)
	return over
}

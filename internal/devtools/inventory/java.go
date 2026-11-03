package main

// Java support. Sources are lexed into tokens (comments dropped, string and
// char literals kept as opaque tokens), then a small structural parser
// recovers types (classes, interfaces, enums, records, annotation types,
// anonymous classes), their supertypes, annotations, enum constants, fields
// and methods with their token and line extents. Entry heuristics then run
// over that model with repository-wide supertype resolution.

import (
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// Java entry kinds. Airline commands reuse KindCLI.
const (
	KindVerb        = "messaging-verb"  // constants of a messaging Verb enum, with their handler
	KindVerbHandler = "verb-handler"    // IVerbHandler.doVerb implementations and handler lambdas
	KindNativeMsg   = "native-message"  // native-protocol request messages (Message.Request.execute)
	KindCQL         = "cql-statement"   // CQLStatement implementations
	KindJMX         = "jmx-operation"   // methods declared in *MBean / *MXBean interfaces
	KindScheduled   = "scheduled-task"  // scheduleWithFixedDelay / scheduleAtFixedRate / scheduleSelfRecurring sites
	KindBackground  = "background-task" // infiniteLoop threads
	KindStage       = "stage-task"      // Stage.X.execute/submit hand-offs
	KindJavaMain    = "java-main"       // public static void main(String[])
)

// ---------------------------------------------------------------- lexer

type jtok struct {
	s    string
	line int
	k    byte // 'i' identifier or keyword, 'n' number, 's' string, 'c' char, 'p' punctuation
}

var jOps2 = map[string]bool{
	"->": true, "::": true, "==": true, "!=": true, "<=": true, "&&": true, "||": true,
	"++": true, "--": true, "+=": true, "-=": true, "*=": true, "/=": true, "%=": true,
	"&=": true, "|=": true, "^=": true, "<<": true,
}

func jIdentStart(c byte) bool {
	return c == '_' || c == '$' || c >= 0x80 || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
}

func jIdentPart(c byte) bool { return jIdentStart(c) || (c >= '0' && c <= '9') }

// jlex tokenizes Java source. '>' is never merged with a following '>' or '=',
// so generic closers stay balanced.
func jlex(src []byte) []jtok {
	var out []jtok
	line, n := 1, len(src)
	for i := 0; i < n; {
		c := src[i]
		switch {
		case c == '\n':
			line++
			i++
		case c == ' ' || c == '\t' || c == '\r' || c == '\f':
			i++
		case c == '/' && i+1 < n && src[i+1] == '/':
			for i < n && src[i] != '\n' {
				i++
			}
		case c == '/' && i+1 < n && src[i+1] == '*':
			i += 2
			for i < n && !(src[i] == '*' && i+1 < n && src[i+1] == '/') {
				if src[i] == '\n' {
					line++
				}
				i++
			}
			i += 2
		case c == '"' && i+2 < n && src[i+1] == '"' && src[i+2] == '"':
			start, j := line, i+3
			for j < n && !(src[j] == '"' && j+2 < n && src[j+1] == '"' && src[j+2] == '"') {
				if src[j] == '\\' && j+1 < n && src[j+1] != '\n' {
					j++
				}
				if src[j] == '\n' {
					line++
				}
				j++
			}
			out = append(out, jtok{string(src[i+3 : min(j, n)]), start, 's'})
			i = j + 3
		case c == '"' || c == '\'':
			j := i + 1
			for j < n && src[j] != c && src[j] != '\n' {
				if src[j] == '\\' && j+1 < n && src[j+1] != '\n' {
					j++
				}
				j++
			}
			k := byte('s')
			if c == '\'' {
				k = 'c'
			}
			out = append(out, jtok{string(src[i+1 : min(j, n)]), line, k})
			i = j + 1
		case jIdentStart(c):
			j := i + 1
			for j < n && jIdentPart(src[j]) {
				j++
			}
			out = append(out, jtok{string(src[i:j]), line, 'i'})
			i = j
		case (c >= '0' && c <= '9') || (c == '.' && i+1 < n && src[i+1] >= '0' && src[i+1] <= '9'):
			j := i + 1
			hex := c == '0' && j < n && (src[j] == 'x' || src[j] == 'X')
			for j < n {
				d := src[j]
				if jIdentPart(d) || d == '.' {
					j++
				} else if (d == '+' || d == '-') && !hex && (src[j-1] == 'e' || src[j-1] == 'E') {
					j++
				} else {
					break
				}
			}
			out = append(out, jtok{string(src[i:j]), line, 'n'})
			i = j
		default:
			if i+2 < n && string(src[i:i+3]) == "..." {
				out = append(out, jtok{"...", line, 'p'})
				i += 3
			} else if i+1 < n && jOps2[string(src[i:i+2])] {
				out = append(out, jtok{string(src[i : i+2]), line, 'p'})
				i += 2
			} else {
				out = append(out, jtok{string(src[i : i+1]), line, 'p'})
				i++
			}
		}
	}
	return out
}

// jmatch pairs brackets. Unclosed openers match the end of the stream.
func jmatch(toks []jtok) []int {
	m := make([]int, len(toks))
	for i := range m {
		m[i] = -1
	}
	var st []int
	opener := map[string]string{")": "(", "]": "[", "}": "{"}
	for i, t := range toks {
		if t.k != 'p' {
			continue
		}
		switch t.s {
		case "(", "[", "{":
			st = append(st, i)
		case ")", "]", "}":
			for k := len(st) - 1; k >= 0; k-- {
				if toks[st[k]].s == opener[t.s] {
					for _, d := range st[k+1:] {
						m[d] = i
					}
					m[st[k]], m[i] = i, st[k]
					st = st[:k]
					break
				}
			}
		}
	}
	for _, k := range st {
		m[k] = len(toks)
	}
	return m
}

// ---------------------------------------------------------------- model

type jAnnot struct {
	Name     string // last segment
	Line     int
	ALo, AHi int // '(' and ')' token indices, or -1
}

type jConst struct {
	Name     string
	Line     int
	ALo, AHi int
}

type jField struct {
	Name, Type string // Type is the first identifier of the declared type
	Line       int
	Lambda     bool
}

type jMethod struct {
	Name          string
	Type          *jType
	Line, EndLine int
	Static        bool
	Ret           string // first identifier of the return type
	PLo, PHi      int    // parameter parens
	Lo, Hi        int    // body braces, -1 when abstract
}

type jType struct {
	Name, Qual, Kind string // Kind: class interface enum record annotation anon
	Line, EndLine    int
	Abstract         bool
	Supers           []string
	Annots           []jAnnot
	Methods          []*jMethod
	Fields           []*jField
	Consts           []*jConst
	Outer            *jType
	Nested           map[string]*jType
	File             *jFile
	Lo, Hi           int
	anonN            int
}

type jFile struct {
	rel, pkg string
	toks     []jtok
	match    []int
	imports  map[string]string
	wild     []string
	types    []*jType
	methods  []*jMethod
}

func (f *jFile) end(i int) int {
	if i < 0 || i >= len(f.match) || f.match[i] < 0 || f.match[i] >= len(f.toks) {
		return len(f.toks) - 1
	}
	return f.match[i]
}

func (f *jFile) s(i int) string {
	if i < 0 || i >= len(f.toks) {
		return ""
	}
	return f.toks[i].s
}

func (f *jFile) ident(i int) bool { return i >= 0 && i < len(f.toks) && f.toks[i].k == 'i' }

var jModifiers = map[string]bool{
	"public": true, "private": true, "protected": true, "static": true, "final": true, "abstract": true,
	"synchronized": true, "native": true, "default": true, "strictfp": true, "transient": true,
	"volatile": true, "sealed": true, "non": true, "-": true,
}

var jNotCalls = map[string]bool{
	"if": true, "for": true, "while": true, "switch": true, "catch": true, "synchronized": true,
	"try": true, "return": true, "new": true, "super": true, "this": true, "throw": true,
}

func parseJava(rel string, src []byte) *jFile {
	f := &jFile{rel: rel, toks: jlex(src), imports: map[string]string{}}
	f.match = jmatch(f.toks)
	f.members(nil, 0, len(f.toks), false)
	return f
}

// members parses a type body (or the compilation unit when owner is nil)
// between token indices lo and hi.
func (f *jFile) members(owner *jType, lo, hi int, enum bool) {
	i := lo
	if enum && owner != nil {
		i = f.enumConsts(owner, lo, hi)
	}
	var hdr []int
	depth := 0
	for i < hi {
		t := f.toks[i]
		if t.k == 'p' {
			switch t.s {
			case "(", "[":
				depth++
			case ")", "]":
				depth = max(depth-1, 0)
			case "{":
				if depth == 0 && !f.assignAt0(hdr) {
					f.decl(owner, hdr, i)
					hdr = nil
				} else {
					f.exprBrace(owner, hdr, i)
				}
				i = f.end(i) + 1
				continue
			case ";":
				if depth == 0 {
					f.finish(owner, hdr)
					hdr, i = nil, i+1
					continue
				}
			case "}":
				hdr, i = nil, i+1
				continue
			}
		}
		hdr = append(hdr, i)
		i++
	}
}

func (f *jFile) assignAt0(hdr []int) bool { return f.at0(hdr, "=") >= 0 }

// at0 returns the position in hdr of the first punctuation s outside
// parens and brackets, or -1.
func (f *jFile) at0(hdr []int, s string) int {
	d := 0
	for j, ti := range hdr {
		t := f.toks[ti]
		if t.k != 'p' {
			continue
		}
		if d == 0 && t.s == s {
			return j
		}
		switch t.s {
		case "(", "[":
			d++
		case ")", "]":
			d--
		}
	}
	return -1
}

func (f *jFile) stripAnnots(hdr []int) (rest []int, annots []jAnnot) {
	for j := 0; j < len(hdr); j++ {
		ti := hdr[j]
		if f.toks[ti].s == "@" && f.toks[ti].k == 'p' && j+1 < len(hdr) && f.ident(hdr[j+1]) && f.s(hdr[j+1]) != "interface" {
			a := jAnnot{Line: f.toks[ti].line, ALo: -1, AHi: -1}
			j++
			a.Name = f.s(hdr[j])
			for j+2 < len(hdr) && f.s(hdr[j+1]) == "." && f.ident(hdr[j+2]) {
				j += 2
				a.Name = f.s(hdr[j])
			}
			if j+1 < len(hdr) && f.s(hdr[j+1]) == "(" {
				a.ALo = hdr[j+1]
				a.AHi = f.end(a.ALo)
				j++
				for j+1 < len(hdr) && hdr[j+1] <= a.AHi {
					j++
				}
			}
			annots = append(annots, a)
			continue
		}
		rest = append(rest, ti)
	}
	return rest, annots
}

// skipAnnots skips annotations in the raw token stream starting at i.
func (f *jFile) skipAnnots(i, hi int) int {
	for i < hi && f.s(i) == "@" && f.ident(i+1) && f.s(i+1) != "interface" {
		i += 2
		for i+1 < hi && f.s(i) == "." && f.ident(i+1) {
			i += 2
		}
		if i < hi && f.s(i) == "(" {
			i = f.end(i) + 1
		}
	}
	return i
}

func (f *jFile) typeKw(rest []int) int {
	for j, ti := range rest {
		if f.toks[ti].k != 'i' || (j > 0 && f.s(rest[j-1]) == ".") {
			continue
		}
		switch f.toks[ti].s {
		case "class", "interface", "enum":
			if j+1 < len(rest) && f.ident(rest[j+1]) {
				return j
			}
		case "record":
			if j+2 < len(rest) && f.ident(rest[j+1]) && (f.s(rest[j+2]) == "(" || f.s(rest[j+2]) == "<") {
				return j
			}
		}
	}
	return -1
}

func (f *jFile) decl(owner *jType, hdr []int, brace int) {
	rest, annots := f.stripAnnots(hdr)
	if k := f.typeKw(rest); k >= 0 {
		t := f.newType(owner, rest, k, annots, brace)
		f.members(t, brace+1, f.end(brace), t.Kind == "enum")
		return
	}
	ctx := "init"
	if m := f.method(owner, rest, brace); m != nil {
		ctx = m.Name
	}
	f.code(owner, brace+1, f.end(brace), ctx)
}

func (f *jFile) register(owner, t *jType) {
	t.File, t.Outer, t.Nested = f, owner, map[string]*jType{}
	f.types = append(f.types, t)
	if owner != nil && t.Kind != "anon" {
		owner.Nested[t.Name] = t
	}
}

func (f *jFile) newType(owner *jType, rest []int, k int, annots []jAnnot, brace int) *jType {
	kw := f.s(rest[k])
	t := &jType{Name: f.s(rest[k+1]), Kind: kw, Line: f.toks[rest[k]].line, Annots: annots, Lo: brace, Hi: f.end(brace)}
	t.EndLine = f.toks[t.Hi].line
	if k > 0 && f.s(rest[k-1]) == "@" {
		t.Kind = "annotation"
	}
	for _, ti := range rest[:k] {
		if f.s(ti) == "abstract" {
			t.Abstract = true
		}
	}
	if t.Kind == "interface" || t.Kind == "annotation" {
		t.Abstract = true
	}
	t.Qual = t.Name
	if owner != nil {
		t.Qual = owner.Qual + "." + t.Name
	}
	// Supertypes.
	mode := ""
	for j := k + 2; j < len(rest); {
		s := f.s(rest[j])
		switch {
		case s == "<":
			j = f.skipAngles(rest, j)
		case s == "(":
			e := f.end(rest[j])
			for j < len(rest) && rest[j] <= e {
				j++
			}
		case s == "extends" || s == "implements" || s == "permits":
			mode = s
			j++
		case f.ident(rest[j]) && (mode == "extends" || mode == "implements"):
			var ref string
			ref, j = f.typeRef(rest, j)
			t.Supers = append(t.Supers, ref)
		default:
			j++
		}
	}
	f.register(owner, t)
	return t
}

func (f *jFile) skipAngles(rest []int, j int) int {
	d := 0
	for ; j < len(rest); j++ {
		switch f.s(rest[j]) {
		case "<":
			d++
		case ">":
			d--
			if d == 0 {
				return j + 1
			}
		}
	}
	return j
}

func (f *jFile) typeRef(rest []int, j int) (string, int) {
	ref := f.s(rest[j])
	j++
	for j+1 < len(rest) && f.s(rest[j]) == "." && f.ident(rest[j+1]) {
		ref += "." + f.s(rest[j+1])
		j += 2
	}
	if j < len(rest) && f.s(rest[j]) == "<" {
		j = f.skipAngles(rest, j)
	}
	return ref, j
}

// method records a method declared by rest; brace is its body or -1.
func (f *jFile) method(owner *jType, rest []int, brace int) *jMethod {
	pi := f.at0(rest, "(")
	if pi < 1 || !f.ident(rest[pi-1]) || jNotCalls[f.s(rest[pi-1])] {
		return nil
	}
	if owner != nil && owner.Kind == "annotation" {
		return nil
	}
	m := &jMethod{Name: f.s(rest[pi-1]), Type: owner, Line: f.toks[rest[pi-1]].line, PLo: rest[pi], PHi: f.end(rest[pi]), Lo: -1, Hi: -1}
	j := 0
	for j < pi-1 && jModifiers[f.s(rest[j])] {
		if f.s(rest[j]) == "static" {
			m.Static = true
		}
		j++
	}
	if j < pi-1 && f.s(rest[j]) == "<" {
		j = f.skipAngles(rest, j)
	}
	if j < pi-1 {
		m.Ret = f.s(rest[j])
	}
	if brace >= 0 {
		m.Lo, m.Hi = brace, f.end(brace)
		m.EndLine = f.toks[m.Hi].line
	} else {
		m.EndLine = f.toks[rest[len(rest)-1]].line
	}
	if owner != nil {
		owner.Methods = append(owner.Methods, m)
	}
	f.methods = append(f.methods, m)
	return m
}

// finish handles a header terminated by ';'.
func (f *jFile) finish(owner *jType, hdr []int) {
	rest, _ := f.stripAnnots(hdr)
	if len(rest) == 0 {
		return
	}
	if owner == nil {
		switch f.s(rest[0]) {
		case "package":
			var b strings.Builder
			for _, ti := range rest[1:] {
				b.WriteString(f.s(ti))
			}
			f.pkg = b.String()
		case "import":
			if len(rest) > 1 && f.s(rest[1]) == "static" {
				return
			}
			var b strings.Builder
			for _, ti := range rest[1:] {
				b.WriteString(f.s(ti))
			}
			p := b.String()
			if strings.HasSuffix(p, ".*") {
				f.wild = append(f.wild, strings.TrimSuffix(p, ".*"))
			} else {
				f.imports[p[strings.LastIndex(p, ".")+1:]] = p
			}
		}
		return
	}
	if eq := f.at0(rest, "="); eq >= 0 {
		if eq < 1 || !f.ident(rest[eq-1]) {
			return
		}
		fd := &jField{Name: f.s(rest[eq-1]), Line: f.toks[rest[eq-1]].line}
		for _, ti := range rest[:eq-1] {
			if f.ident(ti) && !jModifiers[f.s(ti)] {
				fd.Type = f.s(ti)
				break
			}
		}
		if eq+2 < len(rest) {
			a := rest[eq+1]
			fd.Lambda = (f.ident(a) && f.s(rest[eq+2]) == "->") || (f.s(a) == "(" && f.s(f.end(a)+1) == "->")
		}
		owner.Fields = append(owner.Fields, fd)
		return
	}
	f.method(owner, rest, -1)
}

// anonAt reports whether the '{' at brace opens an anonymous class body
// (new T(...) {), returning T.
func (f *jFile) anonAt(brace int) (string, bool) {
	i := brace - 1
	if i < 0 || f.s(i) != ")" {
		return "", false
	}
	k := f.match[i] - 1
	if k < 0 {
		return "", false
	}
	if f.s(k) == ">" {
		d := 0
		for ; k >= 0; k-- {
			if f.s(k) == ">" {
				d++
			} else if f.s(k) == "<" {
				if d--; d == 0 {
					break
				}
			}
		}
		k--
	}
	var segs []string
	for k >= 0 && f.ident(k) && f.s(k) != "new" {
		segs = append([]string{f.s(k)}, segs...)
		k--
		if k >= 0 && f.s(k) == "." {
			k--
			continue
		}
		break
	}
	if k >= 0 && f.s(k) == "new" && len(segs) > 0 {
		return strings.Join(segs, "."), true
	}
	return "", false
}

// newAnon registers an anonymous class body. name is the variable it is
// assigned to, if any; ctx is the enclosing method, if any.
func (f *jFile) newAnon(owner *jType, name, super string, brace int, ctx string) *jType {
	t := &jType{Kind: "anon", Abstract: false, Lo: brace, Hi: f.end(brace), Line: f.toks[brace].line}
	t.EndLine = f.toks[t.Hi].line
	if super != "" {
		t.Supers = []string{super}
	}
	base := "anon"
	if owner != nil {
		base = owner.Qual
	}
	if name == "" {
		n := 0
		if owner != nil {
			owner.anonN++
			n = owner.anonN
		}
		if ctx != "" {
			base += "." + ctx
		}
		t.Qual = base + "$" + strconv.Itoa(n)
	} else {
		t.Qual = base + "." + name
	}
	t.Name = t.Qual[strings.LastIndexAny(t.Qual, ".$")+1:]
	f.register(owner, t)
	return t
}

// anonName is the variable or field an anonymous class is assigned to.
func (f *jFile) anonName(idx []int) string {
	if eq := f.at0(idx, "="); eq >= 1 && f.ident(idx[eq-1]) {
		return f.s(idx[eq-1])
	}
	return ""
}

func (f *jFile) exprBrace(owner *jType, hdr []int, brace int) {
	if sup, ok := f.anonAt(brace); ok {
		a := f.newAnon(owner, f.anonName(hdr), sup, brace, "")
		f.members(a, brace+1, f.end(brace), false)
		return
	}
	f.code(owner, brace+1, f.end(brace), "")
}

// code walks a method or initializer body, picking up anonymous and local classes.
func (f *jFile) code(owner *jType, lo, hi int, ctx string) {
	stmt := lo
	for i := lo; i < hi; i++ {
		if f.toks[i].k != 'p' {
			continue
		}
		switch f.toks[i].s {
		case ";", "}":
			stmt = i + 1
		case "{":
			idx := make([]int, 0, i-stmt)
			for k := stmt; k < i; k++ {
				idx = append(idx, k)
			}
			if sup, ok := f.anonAt(i); ok {
				a := f.newAnon(owner, f.anonName(idx), sup, i, ctx)
				f.members(a, i+1, f.end(i), false)
				i = f.end(i)
			} else if rest, annots := f.stripAnnots(idx); f.typeKw(rest) >= 0 {
				t := f.newType(owner, rest, f.typeKw(rest), annots, i)
				f.members(t, i+1, f.end(i), t.Kind == "enum")
				i = f.end(i)
			}
			stmt = i + 1
		}
	}
}

func (f *jFile) enumConsts(owner *jType, lo, hi int) int {
	i := lo
	for i < hi {
		i = f.skipAnnots(i, hi)
		if i >= hi {
			return i
		}
		if f.s(i) == ";" {
			return i + 1
		}
		if !f.ident(i) {
			return i
		}
		c := &jConst{Name: f.s(i), Line: f.toks[i].line, ALo: -1, AHi: -1}
		i++
		if i < hi && f.s(i) == "(" {
			c.ALo, c.AHi = i, f.end(i)
			i = c.AHi + 1
		}
		if i < hi && f.s(i) == "{" {
			a := f.newAnon(owner, c.Name, owner.Name, i, "")
			f.members(a, i+1, f.end(i), false)
			i = f.end(i) + 1
		}
		owner.Consts = append(owner.Consts, c)
		if i < hi && f.s(i) == "," {
			i++
			continue
		}
		if i < hi && f.s(i) == ";" {
			return i + 1
		}
		return i
	}
	return i
}

// args splits the tokens between parens lo and hi at top-level commas.
func (f *jFile) args(lo, hi int) [][2]int {
	var out [][2]int
	start := lo + 1
	for k := lo + 1; k < hi; k++ {
		switch f.s(k) {
		case "(", "[", "{":
			k = f.end(k)
		case ",":
			out = append(out, [2]int{start, k})
			start = k + 1
		}
	}
	if start < hi {
		out = append(out, [2]int{start, hi})
	}
	return out
}

func (f *jFile) join(lo, hi int) string {
	var b strings.Builder
	for k := lo; k < hi; k++ {
		b.WriteString(f.s(k))
	}
	return b.String()
}

// ---------------------------------------------------------------- scan

type javaScan struct {
	files    []*jFile
	byFQN    map[string]*jType
	bySimple map[string][]*jType
	scripts  map[string][]string // main class FQN -> launcher scripts
}

var generatedJava = regexp.MustCompile(`(?i)(@Generated\b|@javax\.annotation\.Generated|do not edit|this (file|class) (is|was) (auto-?)?generated|autogenerated by)`)

// javaSkipTop names top-level directories whose Java sources are not
// product code; javaSkipDir names such directories at any depth.
var (
	javaSkipTop = map[string]bool{"examples": true, "samples": true, "doc": true, "docs": true}
	javaSkipDir = map[string]bool{"generated": true, "gen-java": true, "generated-sources": true}
)

func javaSource(rel, name string, testSupport bool) bool {
	if name == "package-info.java" || name == "module-info.java" {
		return false
	}
	if !testSupport && (strings.HasSuffix(name, "Test.java") || strings.HasSuffix(name, "Tests.java")) {
		return false
	}
	segs := strings.Split(rel, "/")
	if javaSkipTop[segs[0]] {
		return false
	}
	for _, seg := range segs {
		if javaSkipDir[seg] {
			return false
		}
	}
	return true
}

func (js *javaScan) add(path, rel string) {
	src, err := os.ReadFile(path)
	if err != nil {
		return
	}
	if generatedJava.Match(src[:min(len(src), 3000)]) {
		return
	}
	js.files = append(js.files, parseJava(rel, src))
}

var fqnRef = regexp.MustCompile(`\b(?:[a-z_][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_$]*\b`)

// addScript records the Java classes a launcher script (bin/*) runs.
func (js *javaScan) addScript(path, rel string) {
	for _, l := range readLines(path) {
		if strings.HasPrefix(strings.TrimSpace(l), "#") || strings.Contains(l, "kill") {
			continue
		}
		for _, m := range fqnRef.FindAllString(l, -1) {
			js.scripts[m] = append(js.scripts[m], rel)
		}
	}
}

func (js *javaScan) index() {
	js.byFQN, js.bySimple = map[string]*jType{}, map[string][]*jType{}
	for _, f := range js.files {
		for _, t := range f.types {
			if t.Kind == "anon" {
				continue
			}
			fqn := t.Qual
			if f.pkg != "" {
				fqn = f.pkg + "." + t.Qual
			}
			js.byFQN[fqn] = t
			js.bySimple[t.Name] = append(js.bySimple[t.Name], t)
		}
	}
}

// resolve finds the type a reference written in ctx (or at file level) names.
func (js *javaScan) resolve(ref string, ctx *jType, f *jFile, depth int) *jType {
	segs := strings.Split(ref, ".")
	first := segs[0]
	var base *jType
	for c := ctx; c != nil && base == nil; c = c.Outer {
		if c.Name == first && c.Kind != "anon" {
			base = c
		} else if n := c.Nested[first]; n != nil {
			base = n
		} else if depth < 3 {
			// Member types inherited from a supertype.
			for _, s := range c.Supers {
				if st := js.resolve(s, c.Outer, f, depth+1); st != nil && st.Nested[first] != nil {
					base = st.Nested[first]
					break
				}
			}
		}
	}
	if base == nil {
		for _, t := range f.types {
			if t.Outer == nil && t.Name == first {
				base = t
				break
			}
		}
	}
	if base == nil {
		if fq, ok := f.imports[first]; ok {
			if base = js.byFQN[fq]; base == nil {
				return nil // imported from outside the scanned code
			}
		}
	}
	if base == nil && f.pkg != "" {
		base = js.byFQN[f.pkg+"."+first]
	}
	for _, w := range f.wild {
		if base != nil {
			break
		}
		base = js.byFQN[w+"."+first]
	}
	if base == nil && len(segs) > 1 && first != "" && first[0] >= 'a' && first[0] <= 'z' {
		for k := len(segs); k > 1; k-- {
			if t := js.byFQN[strings.Join(segs[:k], ".")]; t != nil {
				base, segs = t, append([]string{""}, segs[k:]...)
				break
			}
		}
	}
	if base == nil {
		if c := js.bySimple[first]; len(c) == 1 {
			base = c[0]
		}
	}
	for _, s := range segs[1:] {
		if base == nil {
			return nil
		}
		base = base.Nested[s]
	}
	return base
}

// isA reports whether t is target (a qualified-in-file name such as
// "Message.Request") or transitively extends or implements it.
func (js *javaScan) isA(t *jType, target string, seen map[*jType]bool) bool {
	if t.Kind != "anon" && t.Qual == target {
		return true
	}
	if seen[t] {
		return false
	}
	seen[t] = true
	for _, s := range t.Supers {
		if r := js.resolve(s, t.Outer, t.File, 0); r != nil {
			if js.isA(r, target, seen) {
				return true
			}
		} else if s == target || strings.HasSuffix(s, "."+target) {
			return true
		}
	}
	return false
}

func (js *javaScan) is(t *jType, target string) bool { return js.isA(t, target, map[*jType]bool{}) }

func methodNamed(t *jType, names ...string) []*jMethod {
	var out []*jMethod
	for _, m := range t.Methods {
		for _, n := range names {
			if m.Name == n && m.Lo >= 0 {
				out = append(out, m)
			}
		}
	}
	return out
}

func mEntry(kind, name string, f *jFile, m *jMethod, via string) Entry {
	return Entry{Kind: kind, Name: name, File: f.rel, Line: m.Line, EndLine: m.EndLine, Via: via}
}

func (js *javaScan) entries() []Entry {
	js.index()
	var out []Entry
	codec := map[string]string{} // message class -> opcode, from enum constants naming X.codec
	for _, f := range js.files {
		for _, t := range f.types {
			for _, c := range t.Consts {
				for k := c.ALo + 1; c.ALo >= 0 && k+2 < c.AHi; k++ {
					if f.ident(k) && f.s(k+1) == "." && f.s(k+2) == "codec" {
						codec[f.s(k)] = c.Name
					}
				}
			}
		}
	}
	tools := js.cliTools()
	for _, f := range js.files {
		for _, t := range f.types {
			out = append(out, js.typeEntries(f, t, codec, tools)...)
		}
		out = append(out, js.callSites(f)...)
	}
	return out
}

func (js *javaScan) typeEntries(f *jFile, t *jType, codec map[string]string, tools map[*jType]string) []Entry {
	var out []Entry
	// Messaging verbs: enum constants carrying a handler supplier.
	if t.Kind == "enum" && js.verbEnum(f, t) {
		for _, c := range t.Consts {
			h := ""
			if c.ALo >= 0 {
				as := f.args(c.ALo, c.AHi)
				for k := len(as) - 1; k >= 0; k-- {
					a := as[k]
					if a[1]-a[0] > 3 && f.s(a[0]) == "(" && f.s(a[0]+1) == ")" && f.s(a[0]+2) == "->" {
						h = f.join(a[0]+3, a[1])
						break
					}
				}
			}
			if h == "null" {
				continue // placeholder verb with no handler
			}
			e := Entry{Kind: KindVerb, Name: c.Name, File: f.rel, Line: c.Line, Via: "verb-enum"}
			if h != "" {
				e.Detail = "handler " + h
			}
			out = append(out, e)
		}
	}
	if t.Kind != "interface" && t.Kind != "annotation" {
		if js.is(t, "IVerbHandler") {
			own := methodNamed(t, "doVerb")
			for _, m := range own {
				out = append(out, mEntry(KindVerbHandler, t.Qual+".doVerb", f, m, "doVerb"))
			}
			if len(own) == 0 && !t.Abstract && len(t.Supers) > 0 {
				out = append(out, Entry{Kind: KindVerbHandler, Name: t.Qual, File: f.rel, Line: t.Line, EndLine: t.EndLine,
					Via: "inherits-doVerb", Detail: "inherits doVerb from " + t.Supers[0]})
			}
		}
		if js.is(t, "Message.Request") {
			for _, m := range methodNamed(t, "execute") {
				name := codec[t.Name]
				if name == "" && t.Abstract {
					continue // the shared Message.Request.execute wrapper
				}
				if name == "" {
					name = t.Qual
				}
				e := mEntry(KindNativeMsg, name, f, m, "message-request")
				e.Detail = t.Qual + ".execute"
				out = append(out, e)
			}
		}
		if js.is(t, "CQLStatement") {
			own := methodNamed(t, "execute", "executeLocally")
			if !t.Abstract || len(own) > 0 {
				e := Entry{Kind: KindCQL, Name: t.Qual, File: f.rel, Line: t.Line, EndLine: t.EndLine, Via: "cqlstatement"}
				var d []string
				for _, m := range own {
					d = append(d, m.Name+" L"+strconv.Itoa(m.Line))
				}
				if len(d) == 0 && len(t.Supers) > 0 {
					d = append(d, "inherits execute from "+t.Supers[0])
				}
				e.Detail = strings.Join(d, ", ")
				out = append(out, e)
			}
		}
	}
	// Handler lambdas: IVerbHandler-typed fields and factories returning a lambda.
	for _, fd := range t.Fields {
		if fd.Lambda && fd.Type == "IVerbHandler" {
			out = append(out, Entry{Kind: KindVerbHandler, Name: t.Qual + "." + fd.Name, File: f.rel, Line: fd.Line, Via: "handler-lambda"})
		}
	}
	for _, m := range t.Methods {
		if m.Ret == "IVerbHandler" && m.Lo >= 0 && f.returnsLambda(m) {
			out = append(out, mEntry(KindVerbHandler, t.Qual+"."+m.Name, f, m, "handler-lambda"))
		}
	}
	// JMX operations.
	if t.Kind == "interface" && (strings.HasSuffix(t.Name, "MBean") || strings.HasSuffix(t.Name, "MXBean")) {
		for _, m := range t.Methods {
			if m.Static {
				continue
			}
			e := mEntry(KindJMX, t.Qual+"."+m.Name, f, m, "mbean-interface")
			e.Detail = "operation"
			n := len(f.args(m.PLo, m.PHi))
			if (n == 0 && jmxGetter.MatchString(m.Name)) || (n == 1 && strings.HasPrefix(m.Name, "set") && len(m.Name) > 3) {
				e.Detail = "attribute"
			}
			out = append(out, e)
		}
	}
	// Airline commands.
	for _, a := range t.Annots {
		if a.Name != "Command" || a.ALo < 0 {
			continue
		}
		cmd := ""
		for k := a.ALo + 1; k+2 < a.AHi; k++ {
			if f.s(k) == "name" && f.s(k+1) == "=" && f.toks[k+2].k == 's' {
				cmd = f.s(k + 2)
			}
		}
		if cmd == "" {
			continue
		}
		tool := tools[t]
		if tool == "" && strings.Contains("/"+f.rel, "/nodetool/") {
			tool = "nodetool"
		}
		out = append(out, Entry{Kind: KindCLI, Name: strings.TrimSpace(tool + " " + cmd), File: f.rel, Line: a.Line, EndLine: t.EndLine, Via: "airline"})
	}
	// main methods.
	if t.Kind != "anon" {
		for _, m := range methodNamed(t, "main") {
			if !m.Static || !f.stringArrayParam(m) {
				continue
			}
			fqn := t.Qual
			if f.pkg != "" {
				fqn = f.pkg + "." + t.Qual
			}
			e := mEntry(KindJavaMain, fqn, f, m, "main-method")
			if s := js.scripts[fqn]; len(s) > 0 {
				s = uniq(s)
				e.Detail, e.Via = strings.Join(s, ", "), "main-method+script"
			}
			out = append(out, e)
		}
	}
	return out
}

var jmxGetter = regexp.MustCompile(`^(get|is)[A-Z_]`)

func uniq(s []string) []string {
	sort.Strings(s)
	out := s[:0]
	for i, v := range s {
		if i == 0 || v != s[i-1] {
			out = append(out, v)
		}
	}
	return out
}

func (js *javaScan) verbEnum(f *jFile, t *jType) bool {
	if t.Name == "Verb" {
		return true
	}
	for _, c := range t.Consts {
		for k := c.ALo + 1; c.ALo >= 0 && k < c.AHi; k++ {
			if f.ident(k) && strings.HasSuffix(f.s(k), "VerbHandler") {
				return true
			}
		}
	}
	return false
}

// returnsLambda reports whether m returns a lambda or method reference.
func (f *jFile) returnsLambda(m *jMethod) bool {
	for k := m.Lo + 1; k+2 < m.Hi; k++ {
		if f.s(k) != "return" {
			continue
		}
		a := k + 1
		if (f.ident(a) && f.s(a+1) == "->") || (f.s(a) == "(" && f.s(f.end(a)+1) == "->") {
			return true
		}
		for j := a; j < m.Hi && f.s(j) != ";"; j++ {
			switch f.s(j) {
			case "(", "[", "{":
				j = f.end(j)
			case "::":
				return true
			}
		}
	}
	return false
}

func (f *jFile) stringArrayParam(m *jMethod) bool {
	as := f.args(m.PLo, m.PHi)
	if len(as) != 1 {
		return false
	}
	lo, hi := as[0][0], as[0][1]
	for lo < hi && (f.s(lo) == "final" || f.s(lo) == "@") {
		lo = f.skipAnnots(lo, hi)
		if f.s(lo) == "final" {
			lo++
		}
	}
	p := strings.TrimPrefix(f.join(lo, hi), "java.lang.")
	// String[] args, String... args, or the C-style String args[].
	return strings.HasPrefix(p, "String[]") || strings.HasPrefix(p, "String...") || (strings.HasPrefix(p, "String") && strings.HasSuffix(p, "[]"))
}

// cliTools maps airline command classes to the CLI (and group) that
// registers them: Cli.builder("tool") in a class with a main method, with
// withGroup("g") scoping the X.class references that follow it.
func (js *javaScan) cliTools() map[*jType]string {
	out := map[*jType]string{}
	for _, f := range js.files {
		hasMain := false
		for _, m := range f.methods {
			if m.Name == "main" && m.Static {
				hasMain = true
			}
		}
		if !hasMain {
			continue
		}
		tool := ""
		for i := 0; i+2 < len(f.toks); i++ {
			if f.s(i) == "builder" && f.s(i+1) == "(" && f.toks[i+2].k == 's' {
				for k := i - 1; k >= max(0, i-6); k-- {
					if f.s(k) == "Cli" {
						tool = f.s(i + 2)
					}
				}
			}
			if tool != "" {
				break
			}
		}
		if tool == "" {
			continue
		}
		var ctx *jType
		for _, t := range f.types {
			if t.Outer == nil {
				ctx = t
				break
			}
		}
		group := ""
		for i := 0; i+2 < len(f.toks); i++ {
			switch {
			case f.s(i) == "withGroup" && f.s(i+1) == "(" && f.toks[i+2].k == 's':
				group = f.s(i + 2)
			case f.s(i) == ";":
				group = ""
			case f.s(i) == "." && f.s(i+1) == "class" && f.ident(i-1):
				k := i - 1
				ref := f.s(k)
				for k >= 2 && f.s(k-1) == "." && f.ident(k-2) {
					k -= 2
					ref = f.s(k) + "." + ref
				}
				if t := js.resolve(ref, ctx, f, 0); t != nil {
					if _, ok := out[t]; !ok {
						out[t] = strings.TrimSpace(tool + " " + group)
					}
				}
			}
		}
	}
	return out
}

// enclosing returns a label for the innermost method (or type) around token i.
func (f *jFile) enclosing(i int) (string, *jMethod, *jType) {
	var bm *jMethod
	for _, m := range f.methods {
		if m.Lo >= 0 && m.Lo < i && i < m.Hi && (bm == nil || m.Hi-m.Lo < bm.Hi-bm.Lo) {
			bm = m
		}
	}
	var bt *jType
	for _, t := range f.types {
		if t.Lo < i && i < t.Hi && (bt == nil || t.Hi-t.Lo < bt.Hi-bt.Lo) {
			bt = t
		}
	}
	switch {
	case bm != nil && bm.Type != nil && (bt == nil || bm.Hi-bm.Lo < bt.Hi-bt.Lo):
		return bm.Type.Qual + "." + bm.Name, bm, bt
	case bt != nil:
		return bt.Qual, bm, bt
	}
	return f.rel, bm, bt
}

// firstCall names the first method called between lo and hi.
func (f *jFile) firstCall(lo, hi int) string {
	for k := lo; k+1 < hi; k++ {
		if f.ident(k) && f.s(k+1) == "(" && !jNotCalls[f.s(k)] {
			if k >= 2 && f.s(k-1) == "." && f.ident(k-2) && !jNotCalls[f.s(k-2)] {
				return f.s(k-2) + "." + f.s(k)
			}
			return f.s(k)
		}
	}
	return ""
}

// summarize names the task an argument expression denotes.
func (f *jFile) summarize(lo, hi int) string {
	if lo >= hi {
		return ""
	}
	k := lo
	if f.s(k) == "(" {
		k = f.end(k) + 1
	} else if f.ident(k) {
		k++
	}
	if k < hi && f.s(k) == "->" {
		b := k + 1
		if b < hi && f.s(b) == "{" {
			if c := f.firstCall(b+1, f.end(b)); c != "" {
				return c
			}
		} else if c := f.firstCall(b, hi); c != "" {
			return c
		}
		return "lambda"
	}
	if f.s(lo) == "new" {
		k := lo + 1
		name := ""
		for k < hi && (f.ident(k) || f.s(k) == ".") {
			name += f.s(k)
			k++
		}
		for k < hi && f.s(k) != "(" {
			k++
		}
		if e := f.end(k); e+2 < hi && f.s(e+1) == "::" {
			name += "::" + f.s(e+2)
		}
		return name
	}
	var b strings.Builder
	for k := lo; k < hi && f.s(k) != "(" && f.s(k) != "<"; k++ {
		b.WriteString(f.s(k))
	}
	return strings.TrimPrefix(b.String(), "this::")
}

// receiver renders the call chain ending at token j (the token before '.').
func (f *jFile) receiver(j int) string {
	var segs []string
	for n := 0; j >= 0 && n < 5; n++ {
		if f.s(j) == ")" {
			o := f.match[j]
			if o < 1 || !f.ident(o-1) {
				break
			}
			segs = append([]string{f.s(o-1) + "()"}, segs...)
			j = o - 2
		} else if f.ident(j) {
			segs = append([]string{f.s(j)}, segs...)
			j--
		} else {
			break
		}
		if j < 0 || f.s(j) != "." {
			break
		}
		j--
	}
	return strings.Join(segs, ".")
}

func (js *javaScan) callSites(f *jFile) []Entry {
	var out []Entry
	used := map[string]int{}
	emit := func(e Entry) {
		used[e.Kind+e.Name]++
		if n := used[e.Kind+e.Name]; n > 1 {
			e.Name += " #" + strconv.Itoa(n)
		}
		out = append(out, e)
	}
	for i := 1; i+1 < len(f.toks); i++ {
		t := f.toks[i]
		if t.k != 'i' || f.s(i+1) != "(" || f.s(i-1) != "." {
			continue
		}
		lo, hi := i+1, f.end(i+1)
		e := Entry{File: f.rel, Line: t.line}
		if l := f.toks[hi].line; l > t.line {
			e.EndLine = l
		}
		switch t.s {
		case "scheduleWithFixedDelay", "scheduleAtFixedRate", "scheduleSelfRecurring":
			recv := f.receiver(i - 2)
			label, m, typ := f.enclosing(i)
			if recv == "super" || (m != nil && m.Name == t.s) || (typ != nil && typ.Kind == "interface") {
				continue // a wrapper delegating to the real executor
			}
			as := f.args(lo, hi)
			if len(as) == 0 {
				continue
			}
			e.Kind, e.Via, e.Detail = KindScheduled, t.s, recv+"."+t.s
			e.Name = label + ": " + f.summarize(as[0][0], as[0][1])
			emit(e)
		case "infiniteLoop":
			as := f.args(lo, hi)
			if len(as) < 2 {
				continue
			}
			label, _, _ := f.enclosing(i)
			task := f.summarize(as[1][0], as[1][1])
			if f.toks[as[0][0]].k == 's' && as[0][1]-as[0][0] == 1 {
				task = f.s(as[0][0]) + " (" + task + ")"
			}
			e.Kind, e.Via, e.Detail = KindBackground, "infinite-loop", f.receiver(i-2)+".infiniteLoop"
			e.Name = label + ": " + task
			emit(e)
		case "execute", "submit", "maybeExecuteImmediately":
			stage := ""
			if f.ident(i-2) && f.s(i-3) == "." && f.s(i-4) == "Stage" {
				stage = f.s(i - 2)
			} else if f.s(i-2) == ")" && f.s(i-3) == "(" && f.s(i-4) == "executor" && f.s(i-5) == "." && f.ident(i-6) && f.s(i-7) == "." && f.s(i-8) == "Stage" {
				stage = f.s(i - 6)
			}
			if stage == "" || strings.ToUpper(stage) != stage {
				continue
			}
			as := f.args(lo, hi)
			if len(as) == 0 {
				continue
			}
			label, _, _ := f.enclosing(i)
			e.Kind, e.Via, e.Detail = KindStage, "stage", "Stage."+stage+"."+t.s
			e.Name = "Stage." + stage + " " + label + ": " + f.summarize(as[0][0], as[0][1])
			emit(e)
		}
	}
	return out
}

// launcherScript reports whether rel is a shell launcher under a bin
// directory (bin/nodetool, tools/bin/sstabledump), which may name a main class.
func launcherScript(rel, name string) bool {
	if !strings.HasPrefix(rel, "bin/") && !strings.Contains(rel, "/bin/") {
		return false
	}
	ext := ""
	if i := strings.LastIndex(name, "."); i >= 0 {
		ext = name[i:]
	}
	return ext == "" || ext == ".sh"
}

package main

// Applying timing (DESIGN §16.3).
//
// --apply-timing-to FRAGMENT (with --refinement) writes each applicable
// proposal of the timing report (refinement.go timingReport, §14.13) into
// the parent fragment: on every implements-targeted interface it finds
// there, latency_by_outcome (the proposed list) and latency_source
// {refined: <ontology>@<rev>}. The YAML is edited in place: only those two
// keys' text changes, so comments, key order and formatting elsewhere are
// kept. Block mappings get block text at the keys' column; flow mappings
// ({component: ..., name: ...}) get flow text before their closing brace.
// It prints a unified diff of the edit, and --dry-run prints only that.
//
// An interface is left alone, and reported, when:
//   - its latency_source is pinned (an operator's value; §14.3);
//   - the report says the child's timing doesn't apply (§14.3's rule);
//   - one outcome class proposes no latency_by_outcome;
//   - it already carries the proposal (a re-apply is a no-op);
//   - the fragment has no entry for it.

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"unicode/utf8"

	"go.yaml.in/yaml/v3"

	"github.com/xleelz/mosaic/internal/model"
)

// timingProposal is what --apply-timing-to writes on one interface.
type timingProposal struct {
	Interface string
	Source    model.LatencySource
	ByOutcome []model.OutcomeLatency
}

// splice replaces src[start:end] with text.
type splice struct {
	start, end int
	text       string
}

// applyTimingTo edits the fragment at path with the results' applicable
// proposals, prints what it did and the diff to w, and writes the file
// unless dryRun.
func applyTimingTo(w io.Writer, path string, results []*refinementResult, dryRun bool) error {
	var props []timingProposal
	rep, _ := timingReport(results)["refinements"].([]timingRefinement)
	for _, tr := range rep {
		for _, e := range tr.Interfaces {
			switch {
			case !e.Applies:
				fmt.Fprintf(w, "apply timing: %s skipped: %s\n", e.Interface, e.Reason)
			case len(e.LatencyByOutcome) == 0:
				fmt.Fprintf(w, "apply timing: %s skipped: one outcome class, no latency_by_outcome proposed\n", e.Interface)
			default:
				props = append(props, timingProposal{Interface: e.Interface, Source: *e.LatencySource, ByOutcome: e.LatencyByOutcome})
			}
		}
	}
	src, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	out, notes, err := applyTimingYAML(src, props)
	if err != nil {
		return fmt.Errorf("--apply-timing-to %s: %w", path, err)
	}
	for _, n := range notes {
		fmt.Fprintf(w, "apply timing: %s\n", n)
	}
	if bytes.Equal(src, out) {
		fmt.Fprintf(w, "apply timing: %s unchanged\n", path)
		return nil
	}
	io.WriteString(w, unifiedDiff(path, src, out))
	if dryRun {
		fmt.Fprintf(w, "apply timing: dry run, %s not written\n", path)
		return nil
	}
	if err := os.WriteFile(path, out, 0o644); err != nil {
		return err
	}
	fmt.Fprintf(w, "apply timing: %s written\n", path)
	return nil
}

// applyTimingYAML returns src with the proposals applied, and a note per
// interface it applied or left alone.
func applyTimingYAML(src []byte, props []timingProposal) ([]byte, []string, error) {
	var doc yaml.Node
	if err := yaml.Unmarshal(src, &doc); err != nil {
		return nil, nil, err
	}
	if len(doc.Content) == 0 || doc.Content[0].Kind != yaml.MappingNode {
		return nil, nil, fmt.Errorf("not a YAML mapping document")
	}
	root := doc.Content[0]
	if root.Style&yaml.FlowStyle != 0 {
		return nil, nil, fmt.Errorf("a flow-style (JSON) document can't be edited in place; use a YAML fragment")
	}
	ifaces := mapValue(root, "interfaces")
	e := &yamlEditor{src: src, lines: splitLines(src), order: preorder(&doc)}
	e.compact = compactSeqs(root)
	var notes []string
	var edits []splice
	for _, p := range props {
		m := findInterface(ifaces, p.Interface)
		if m == nil {
			notes = append(notes, fmt.Sprintf("%s skipped: not in this fragment", p.Interface))
			continue
		}
		if ls := mapValue(m, "latency_source"); ls != nil && ls.Kind == yaml.MappingNode && mapValue(ls, "pinned") != nil {
			notes = append(notes, fmt.Sprintf("%s skipped: its latency_source is pinned (%s)", p.Interface, mapValue(ls, "pinned").Value))
			continue
		}
		sp, err := e.edit(m, p)
		if err != nil {
			return nil, nil, fmt.Errorf("%s: %w", p.Interface, err)
		}
		if len(sp) == 0 {
			notes = append(notes, fmt.Sprintf("%s unchanged: it already has the proposal (latency_source refined %s)", p.Interface, p.Source.Refined))
			continue
		}
		notes = append(notes, fmt.Sprintf("%s: latency_by_outcome (%d entries) and latency_source refined %s", p.Interface, len(p.ByOutcome), p.Source.Refined))
		edits = append(edits, sp...)
	}
	out := applySplices(src, edits)
	// The result must still parse and carry the proposals.
	var check yaml.Node
	if err := yaml.Unmarshal(out, &check); err != nil {
		return nil, nil, fmt.Errorf("the edit doesn't parse (not written): %v", err)
	}
	for _, p := range props {
		if m := findInterface(mapValue(check.Content[0], "interfaces"), p.Interface); m != nil {
			if ls := mapValue(m, "latency_source"); ls != nil && mapValue(ls, "pinned") != nil {
				continue
			}
			if !nodeIs(mapValue(m, "latency_source"), p.Source) || !nodeIs(mapValue(m, "latency_by_outcome"), p.ByOutcome) {
				return nil, nil, fmt.Errorf("the edit doesn't read back as the proposal (not written)")
			}
		}
	}
	return out, notes, nil
}

type yamlEditor struct {
	src     []byte
	lines   []int // byte offset of each line's start, plus len(src)
	order   []*yaml.Node
	compact bool // block sequences under a key start at the key's column
}

// edit returns the splices that put p on interface mapping m.
func (e *yamlEditor) edit(m *yaml.Node, p timingProposal) ([]splice, error) {
	srcK, srcV := mapPair(m, "latency_source")
	byK, byV := mapPair(m, "latency_by_outcome")
	needSrc := srcV == nil || !nodeIs(srcV, p.Source)
	needBy := byV == nil || !nodeIs(byV, p.ByOutcome)
	if !needSrc && !needBy {
		return nil, nil
	}
	if m.Style&yaml.FlowStyle != 0 {
		return e.editFlow(m, p, srcK, byK, needSrc, needBy)
	}
	return e.editBlock(m, p, srcK, byK, needSrc, needBy), nil
}

func (e *yamlEditor) editBlock(m *yaml.Node, p timingProposal, srcK, byK *yaml.Node, needSrc, needBy bool) []splice {
	col := m.Content[0].Column - 1
	pad := strings.Repeat(" ", col)
	srcText := pad + "latency_source: " + flowSource(p.Source) + "\n"
	byText := e.blockByOutcome(pad, p.ByOutcome)
	var out []splice
	replace := func(k *yaml.Node, text string) {
		a, b := e.keyLines(m, k)
		out = append(out, splice{e.lines[a], e.lines[b], text})
	}
	insertAfter := func(k *yaml.Node, text string) {
		_, b := e.keyLines(m, k)
		out = append(out, splice{e.lines[b], e.lines[b], text})
	}
	switch {
	case srcK != nil && byK != nil:
		if needSrc {
			replace(srcK, srcText)
		}
		if needBy {
			replace(byK, byText)
		}
	case srcK != nil:
		if needSrc {
			replace(srcK, srcText+byText)
		} else {
			insertAfter(srcK, byText)
		}
	case byK != nil:
		if needBy {
			replace(byK, srcText+byText)
		} else {
			a, _ := e.keyLines(m, byK)
			out = append(out, splice{e.lines[a], e.lines[a], srcText})
		}
	default:
		anchor := m.Content[len(m.Content)-2]
		if k, _ := mapPair(m, "latency_ms"); k != nil {
			anchor = k
		}
		insertAfter(anchor, srcText+byText)
	}
	return out
}

func (e *yamlEditor) blockByOutcome(pad string, by []model.OutcomeLatency) string {
	seq := pad
	if !e.compact {
		seq += "  "
	}
	var b strings.Builder
	b.WriteString(pad + "latency_by_outcome:\n")
	for _, o := range by {
		b.WriteString(seq + "- when: " + yamlScalar(o.When, false) + "\n")
		b.WriteString(seq + "  ms: " + latencyText(o.MS, false) + "\n")
	}
	return b.String()
}

func (e *yamlEditor) editFlow(m *yaml.Node, p timingProposal, srcK, byK *yaml.Node, needSrc, needBy bool) ([]splice, error) {
	open := e.offset(m)
	if open < 0 || open >= len(e.src) || e.src[open] != '{' {
		return nil, fmt.Errorf("can't locate the flow mapping at line %d", m.Line)
	}
	srcText := "latency_source: " + flowSource(p.Source)
	byText := "latency_by_outcome: " + flowByOutcome(p.ByOutcome)
	var out []splice
	var add []string
	for _, kt := range []struct {
		k    *yaml.Node
		need bool
		text string
	}{{srcK, needSrc, srcText}, {byK, needBy, byText}} {
		switch {
		case kt.k == nil:
			add = append(add, kt.text)
		case kt.need:
			a := e.offset(kt.k)
			b := flowScan(e.src, e.offset(mapValueOf(m, kt.k)), true)
			for b > a && isSpace(e.src[b-1]) {
				b--
			}
			out = append(out, splice{a, b, kt.text})
		}
	}
	if len(add) > 0 {
		end := flowScan(e.src, open+1, false)
		if end >= len(e.src) || e.src[end] != '}' {
			return nil, fmt.Errorf("can't find the end of the flow mapping at line %d", m.Line)
		}
		at := end
		for at > open+1 && isSpace(e.src[at-1]) {
			at--
		}
		text := strings.Join(add, ", ")
		switch {
		case at == open+1: // {}
		case e.src[at-1] == ',':
			text = " " + text
		default:
			text = ", " + text
		}
		out = append(out, splice{at, at, text})
	}
	return out, nil
}

// keyLines is the line range [a, b) of block mapping m's key k and its
// value, without the blank and comment lines that end it (they belong to
// what follows).
func (e *yamlEditor) keyLines(m, k *yaml.Node) (int, int) {
	a := k.Line - 1
	next := -1
	for i := 0; i+1 < len(m.Content); i += 2 {
		if m.Content[i] == k && i+2 < len(m.Content) {
			next = m.Content[i+2].Line - 1
		}
	}
	if next < 0 {
		next = e.lineAfter(m)
	}
	col := m.Content[0].Column - 1
	b := next
	for b > a+1 {
		ln := strings.TrimRight(string(e.src[e.lines[b-1]:e.lines[b]]), "\r\n")
		t := strings.TrimLeft(ln, " \t")
		if t == "" || (strings.HasPrefix(t, "#") && len(ln)-len(t) <= col) {
			b--
			continue
		}
		break
	}
	return a, b
}

// lineAfter is the 0-based line of the first node after n's subtree, or the
// line count when none follows.
func (e *yamlEditor) lineAfter(n *yaml.Node) int {
	last := n
	for len(last.Content) > 0 {
		last = last.Content[len(last.Content)-1]
	}
	for i, x := range e.order {
		if x == last {
			for _, y := range e.order[i+1:] {
				if y.Line > last.Line {
					return y.Line - 1
				}
			}
		}
	}
	return len(e.lines) - 1
}

// offset is node n's byte offset in the source (Column counts characters).
func (e *yamlEditor) offset(n *yaml.Node) int {
	if n.Line < 1 || n.Line > len(e.lines)-1 {
		return -1
	}
	off := e.lines[n.Line-1]
	for i := 1; i < n.Column && off < len(e.src); i++ {
		_, size := utf8.DecodeRune(e.src[off:])
		off += size
	}
	return off
}

// flowScan scans flow text from p at depth 0 to the first ',' (when comma),
// '}' or ']' at that depth, skipping quoted scalars, nested collections and
// comments. It returns that byte's offset, or len(src).
func flowScan(src []byte, p int, comma bool) int {
	depth := 0
	prev := byte('{') // the last non-space byte: quotes start scalars only after an indicator
	for i := p; i < len(src); i++ {
		c := src[i]
		switch {
		case c == '\'' && strings.IndexByte("{[,:", prev) >= 0:
			for i++; i < len(src); i++ {
				if src[i] == '\'' {
					if i+1 < len(src) && src[i+1] == '\'' {
						i++
						continue
					}
					break
				}
			}
		case c == '"' && strings.IndexByte("{[,:", prev) >= 0:
			for i++; i < len(src) && src[i] != '"'; i++ {
				if src[i] == '\\' {
					i++
				}
			}
		case c == '#' && (i == 0 || isSpace(src[i-1])):
			for i < len(src) && src[i] != '\n' {
				i++
			}
			continue
		case c == '{' || c == '[':
			depth++
		case c == '}' || c == ']':
			if depth == 0 {
				return i
			}
			depth--
		case c == ',' && depth == 0 && comma:
			return i
		}
		if !isSpace(c) {
			prev = c
		}
	}
	return len(src)
}

func isSpace(c byte) bool { return c == ' ' || c == '\t' || c == '\n' || c == '\r' }

func flowSource(s model.LatencySource) string {
	return "{refined: " + yamlScalar(s.Refined, true) + "}"
}

func flowByOutcome(by []model.OutcomeLatency) string {
	parts := make([]string, len(by))
	for i, o := range by {
		parts[i] = "{when: " + yamlScalar(o.When, true) + ", ms: " + latencyText(o.MS, true) + "}"
	}
	return "[" + strings.Join(parts, ", ") + "]"
}

// latencyText renders a latency_ms value: a number, "=cel", or {min, max}.
func latencyText(l model.Latency, flow bool) string {
	switch {
	case l.Expr != "":
		return yamlScalar("="+l.Expr, flow)
	case l.Min == l.Max:
		return fmtNum(l.Min)
	}
	return "{min: " + fmtNum(l.Min) + ", max: " + fmtNum(l.Max) + "}"
}

// yamlScalar renders s as a one-line YAML string scalar, quoted when plain
// text would read as something else (in a flow collection, also when it
// holds a flow indicator).
func yamlScalar(s string, flow bool) string {
	n := &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: s}
	b, err := yaml.Marshal(n)
	t := strings.TrimSuffix(string(b), "\n")
	plain := err == nil && t != "" && t[0] != '\'' && t[0] != '"' && t[0] != '|' && t[0] != '>'
	if err != nil || strings.Contains(t, "\n") || (!plain && t[0] != '\'' && t[0] != '"') ||
		(plain && flow && strings.ContainsAny(s, ",[]{}#")) {
		n.Style = yaml.DoubleQuotedStyle
		b, _ = yaml.Marshal(n)
		t = strings.TrimSuffix(string(b), "\n")
	}
	return t
}

// nodeIs reports whether YAML node n decodes to want (compared through
// the model's JSON shape, so 31 and 31.0 or flow and block are equal).
func nodeIs(n *yaml.Node, want any) bool {
	if n == nil {
		return false
	}
	var v any
	if n.Decode(&v) != nil {
		return false
	}
	b, err := json.Marshal(v)
	if err != nil {
		return false
	}
	got := reflect.New(reflect.TypeOf(want))
	if json.Unmarshal(b, got.Interface()) != nil {
		return false
	}
	return reflect.DeepEqual(got.Elem().Interface(), want)
}

func mapPair(m *yaml.Node, key string) (*yaml.Node, *yaml.Node) {
	if m == nil || m.Kind != yaml.MappingNode {
		return nil, nil
	}
	for i := 0; i+1 < len(m.Content); i += 2 {
		if m.Content[i].Value == key {
			return m.Content[i], m.Content[i+1]
		}
	}
	return nil, nil
}

func mapValue(m *yaml.Node, key string) *yaml.Node {
	_, v := mapPair(m, key)
	return v
}

func mapValueOf(m, k *yaml.Node) *yaml.Node {
	for i := 0; i+1 < len(m.Content); i += 2 {
		if m.Content[i] == k {
			return m.Content[i+1]
		}
	}
	return nil
}

// findInterface is the interfaces entry whose id, or component.name, is id.
func findInterface(seq *yaml.Node, id string) *yaml.Node {
	if seq == nil || seq.Kind != yaml.SequenceNode {
		return nil
	}
	for _, m := range seq.Content {
		if m.Kind != yaml.MappingNode {
			continue
		}
		if v := mapValue(m, "id"); v != nil && v.Value == id {
			return m
		}
		c, n := mapValue(m, "component"), mapValue(m, "name")
		if c != nil && n != nil && c.Value+"."+n.Value == id {
			return m
		}
	}
	return nil
}

// compactSeqs reports whether the document writes a block sequence under a
// key at the key's column (sources:\n- a), judged by the first one; true
// when it has none.
func compactSeqs(n *yaml.Node) bool {
	var walk func(*yaml.Node) (bool, bool)
	walk = func(n *yaml.Node) (bool, bool) {
		if n.Kind == yaml.MappingNode {
			for i := 0; i+1 < len(n.Content); i += 2 {
				k, v := n.Content[i], n.Content[i+1]
				if v.Kind == yaml.SequenceNode && v.Style&yaml.FlowStyle == 0 && len(v.Content) > 0 && v.Content[0].Line > k.Line {
					return v.Content[0].Column-2 == k.Column, true
				}
			}
		}
		for _, c := range n.Content {
			if r, ok := walk(c); ok {
				return r, true
			}
		}
		return false, false
	}
	r, ok := walk(n)
	return r || !ok
}

func preorder(n *yaml.Node) []*yaml.Node {
	out := []*yaml.Node{n}
	for _, c := range n.Content {
		out = append(out, preorder(c)...)
	}
	return out
}

// splitLines is the byte offset of each line's start, and len(src) last.
func splitLines(src []byte) []int {
	out := []int{0}
	for i, c := range src {
		if c == '\n' && i+1 < len(src) {
			out = append(out, i+1)
		}
	}
	return append(out, len(src))
}

func applySplices(src []byte, sp []splice) []byte {
	// Sort by start; splices don't overlap.
	for i := 1; i < len(sp); i++ {
		for j := i; j > 0 && sp[j].start < sp[j-1].start; j-- {
			sp[j], sp[j-1] = sp[j-1], sp[j]
		}
	}
	var b bytes.Buffer
	at := 0
	for _, s := range sp {
		b.Write(src[at:s.start])
		b.WriteString(s.text)
		at = s.end
	}
	b.Write(src[at:])
	return b.Bytes()
}

// unifiedDiff is a unified diff (3 lines of context) from a to b, both
// labelled path.
func unifiedDiff(path string, a, b []byte) string {
	x, y := diffLines(a), diffLines(b)
	ops := lcsOps(x, y)
	const ctx = 3
	var out strings.Builder
	name := filepath.ToSlash(path)
	if filepath.IsAbs(path) {
		fmt.Fprintf(&out, "--- %s\n+++ %s\n", name, name)
	} else {
		fmt.Fprintf(&out, "--- a/%s\n+++ b/%s\n", name, name)
	}
	// Group ops into hunks.
	type op struct {
		kind byte
		ai   int
		bi   int
		text string
	}
	var list []op
	ai, bi := 0, 0
	for _, o := range ops {
		switch o {
		case '=':
			list = append(list, op{'=', ai, bi, x[ai]})
			ai++
			bi++
		case '-':
			list = append(list, op{'-', ai, bi, x[ai]})
			ai++
		case '+':
			list = append(list, op{'+', ai, bi, y[bi]})
			bi++
		}
	}
	for i := 0; i < len(list); {
		if list[i].kind == '=' {
			i++
			continue
		}
		start := max(0, i-ctx)
		end := i
		for end < len(list) {
			if list[end].kind != '=' {
				end++
				continue
			}
			run := end
			for run < len(list) && list[run].kind == '=' {
				run++
			}
			if run == len(list) || run-end > 2*ctx {
				end = min(end+ctx, len(list))
				break
			}
			end = run
		}
		h := list[start:end]
		var an, bn int
		for _, o := range h {
			if o.kind != '+' {
				an++
			}
			if o.kind != '-' {
				bn++
			}
		}
		as, bs := h[0].ai+1, h[0].bi+1
		if an == 0 {
			as--
		}
		if bn == 0 {
			bs--
		}
		fmt.Fprintf(&out, "@@ -%d,%d +%d,%d @@\n", as, an, bs, bn)
		for _, o := range h {
			t := o.text
			if !strings.HasSuffix(t, "\n") {
				t += "\n\\ No newline at end of file\n"
			}
			k := o.kind
			if k == '=' {
				k = ' '
			}
			out.WriteString(string(k) + t)
		}
		i = end
	}
	return out.String()
}

// diffLines splits b into lines, each with its newline (the last may have
// none).
func diffLines(b []byte) []string {
	l := strings.SplitAfter(string(b), "\n")
	if l[len(l)-1] == "" {
		l = l[:len(l)-1]
	}
	return l
}

// lcsOps is the edit script from x to y: '=' keep, '-' delete, '+' insert.
// The common prefix and suffix are trimmed first, so the quadratic table
// covers only the changed middle.
func lcsOps(x, y []string) []byte {
	p := 0
	for p < len(x) && p < len(y) && x[p] == y[p] {
		p++
	}
	s := 0
	for s < len(x)-p && s < len(y)-p && x[len(x)-1-s] == y[len(y)-1-s] {
		s++
	}
	mx, my := x[p:len(x)-s], y[p:len(y)-s]
	t := make([][]int, len(mx)+1)
	for i := range t {
		t[i] = make([]int, len(my)+1)
	}
	for i := len(mx) - 1; i >= 0; i-- {
		for j := len(my) - 1; j >= 0; j-- {
			if mx[i] == my[j] {
				t[i][j] = t[i+1][j+1] + 1
			} else {
				t[i][j] = max(t[i+1][j], t[i][j+1])
			}
		}
	}
	ops := bytes.Repeat([]byte{'='}, p)
	i, j := 0, 0
	for i < len(mx) || j < len(my) {
		switch {
		case i < len(mx) && j < len(my) && mx[i] == my[j]:
			ops = append(ops, '=')
			i++
			j++
		case j < len(my) && (i == len(mx) || t[i][j+1] >= t[i+1][j]):
			ops = append(ops, '+')
			j++
		default:
			ops = append(ops, '-')
			i++
		}
	}
	return append(ops, bytes.Repeat([]byte{'='}, s)...)
}

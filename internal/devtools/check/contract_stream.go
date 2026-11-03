package main

import (
	"fmt"
	"reflect"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// Stream contracts (DESIGN §13.1 item 34): an interface's yields, as the run
// scenarios' traces show them, against stream.frames and the terminator.

// yieldCall is one call of a yielding interface in a run scenario's trace.
type yieldCall struct {
	Scenario string
	Items    []any
	Err      bool // the call ended with an error
}

// collectYields runs the scenarios (those only matches, in id order) and
// returns the yields of each wanted interface, per call. It returns an empty,
// non-nil map when nothing is wanted.
func collectYields(doc *model.Document, want map[string]bool, only *regexp.Regexp) map[string][]yieldCall {
	out := map[string][]yieldCall{}
	if len(want) == 0 {
		return out
	}
	scs := append([]model.Scenario(nil), doc.Scenarios...)
	sort.Slice(scs, func(a, b int) bool { return scs[a].ID < scs[b].ID })
	for _, sc := range scs {
		if only != nil && !only.MatchString(sc.ID) {
			continue
		}
		res, err := sim.Run(doc, sim.Request{Scenario: sc.ID})
		if err != nil {
			continue
		}
		type open struct {
			iface string
			call  *yieldCall
		}
		spans := map[int]*open{}
		var order []*open
		for _, e := range res.Trace {
			switch e.Type {
			case "call.start":
				if want[e.Interface] {
					o := &open{e.Interface, &yieldCall{Scenario: sc.ID}}
					spans[e.Span] = o
					order = append(order, o)
				}
			case "yield":
				if o, ok := spans[e.Span]; ok {
					o.call.Items = append(o.call.Items, e.Output)
				}
			case "call.end":
				if o, ok := spans[e.Span]; ok && e.Error != nil {
					o.call.Err = true
				}
			}
		}
		for _, o := range order {
			out[o.iface] = append(out[o.iface], *o.call)
		}
	}
	return out
}

// frameShape is a frame's schema prepared for matching values.
type frameShape struct {
	Name   string
	Shape  *shape
	Consts []constraint // const and enum constraints, by path
}

type constraint struct {
	Path   []string // object keys from the yield's root
	Values []any
}

// constraints collects the const and enum constraints of a schema at its
// root and in its properties (through $ref and allOf).
func constraints(v any, resolve func(string) (any, bool), at []string, depth int) []constraint {
	m, ok := v.(map[string]any)
	if !ok || depth > 8 {
		return nil
	}
	if r, ok := m["$ref"].(string); ok {
		x, ok := resolve(r)
		if !ok {
			return nil
		}
		return constraints(x, resolve, at, depth+1)
	}
	var out []constraint
	p := append([]string(nil), at...)
	if c, ok := m["const"]; ok {
		out = append(out, constraint{p, []any{c}})
	}
	if e, ok := m["enum"].([]any); ok {
		out = append(out, constraint{p, e})
	}
	if ps, ok := m["properties"].(map[string]any); ok {
		for _, k := range sortedKeys(ps) {
			out = append(out, constraints(ps[k], resolve, append(p, k), depth+1)...)
		}
	}
	if all, ok := m["allOf"].([]any); ok {
		for _, x := range all {
			out = append(out, constraints(x, resolve, p, depth+1)...)
		}
	}
	return out
}

// unknown stands for a template expression whose value is only known at run
// time.
type unknown struct{}

// at returns the value at a path; ok is false when a key is absent.
func valueAt(v any, p []string) (any, bool) {
	for _, k := range p {
		if _, u := v.(unknown); u {
			return v, true
		}
		m, ok := v.(map[string]any)
		if !ok {
			return nil, false
		}
		if v, ok = m[k]; !ok {
			return nil, false
		}
	}
	return v, true
}

func sameValue(a, b any) bool {
	if _, u := a.(unknown); u {
		return true
	}
	if x, ok := num(a); ok {
		y, ok := num(b)
		return ok && x == y
	}
	return reflect.DeepEqual(a, b)
}

func num(v any) (float64, bool) {
	switch t := v.(type) {
	case int:
		return float64(t), true
	case int64:
		return float64(t), true
	case uint64:
		return float64(t), true
	case float64:
		return t, true
	}
	return 0, false
}

// meets: does the value satisfy every const and enum constraint?
func (f *frameShape) meets(v any) bool {
	for _, c := range f.Consts {
		x, ok := valueAt(v, c.Path)
		if !ok {
			return false
		}
		hit := false
		for _, want := range c.Values {
			if sameValue(x, want) {
				hit = true
				break
			}
		}
		if !hit {
			return false
		}
	}
	return true
}

func valueType(v any) string {
	switch t := v.(type) {
	case string:
		return "string"
	case bool:
		return "boolean"
	case int, int64, uint64:
		return "integer"
	case float64:
		if t == float64(int64(t)) {
			return "integer"
		}
		return "number"
	case map[string]any:
		return "object"
	case []any:
		return "array"
	case nil:
		return "null"
	}
	return ""
}

// validate lists how a value departs from a shape (missing, type, extra),
// labeled under p.
func validate(p string, v any, s *shape, depth int, out *[]confIssue) {
	if s == nil || s.Complex || depth > 8 {
		return
	}
	if _, u := v.(unknown); u {
		return
	}
	t := valueType(v)
	if t == "null" {
		if !s.Nullable && len(s.Types) > 0 {
			*out = append(*out, confIssue{"type", fmt.Sprintf("%s: contract %s, yielded null", p, typeList(s))})
		}
		return
	}
	if t != "" && len(s.Types) > 0 && !typeCompat(s.Types, map[string]bool{t: true}) {
		*out = append(*out, confIssue{"type", fmt.Sprintf("%s: contract %s, yielded %s", p, typeList(s), t)})
		return
	}
	join := func(k string) string {
		if p == "" {
			return k
		}
		return p + "." + k
	}
	switch tv := v.(type) {
	case map[string]any:
		if s.Props == nil {
			return
		}
		got := map[string]string{}
		for k := range tv {
			got[normName(k)] = k
		}
		for _, n := range sortedKeys(s.Props) {
			k, ok := got[n]
			if !ok {
				if s.Required[n] {
					*out = append(*out, confIssue{"missing", fmt.Sprintf("%s (%s, required)", join(s.Names[n]), typeList(s.Props[n]))})
				}
				continue
			}
			validate(join(s.Names[n]), tv[k], s.Props[n], depth+1, out)
		}
		if !s.Open && len(s.Props) > 0 {
			for _, n := range sortedKeys(got) {
				if _, ok := s.Props[n]; !ok {
					*out = append(*out, confIssue{"extra", fmt.Sprintf("%s (%s)", join(got[n]), valueType(tv[got[n]]))})
				}
			}
		}
	case []any:
		if s.Items != nil {
			for _, x := range tv {
				validate(p+"[]", x, s.Items, depth+1, out)
			}
		}
	}
}

// classify returns the frame a value belongs to and its validation issues,
// or nil when no frame's const and enum constraints accept it. Among the
// frames that accept it, the best fit has the fewest missing and extra
// fields, then the fewest type issues, then comes first.
func classify(frames []*frameShape, v any) (*frameShape, []confIssue) {
	var best *frameShape
	var bestIssues []confIssue
	var bestScore [2]int
	for _, f := range frames {
		if !f.meets(v) {
			continue
		}
		var is []confIssue
		validate("", v, f.Shape, 0, &is)
		score := [2]int{len(is), len(is)}
		score[0] -= kindCount(is, "type")
		score[1] = kindCount(is, "type")
		if best == nil || score[0] < bestScore[0] || (score[0] == bestScore[0] && score[1] < bestScore[1]) {
			best, bestIssues, bestScore = f, is, score
		}
	}
	return best, bestIssues
}

func kindCount(is []confIssue, kind string) int {
	n := 0
	for _, x := range is {
		if x.Kind == kind {
			n++
		}
	}
	return n
}

// staticYields returns the interface's yield templates with expressions
// replaced by unknown.
func staticYields(ifc *model.Interface) []any {
	var out []any
	walkConfSteps(ifc.Behavior, func(s model.Step) {
		if s.Yield == nil {
			return
		}
		t, err := expr.DecodeTemplate(s.Yield)
		if err != nil {
			out = append(out, unknown{})
			return
		}
		out = append(out, staticValue(t))
	})
	return out
}

func staticValue(v any) any {
	switch t := v.(type) {
	case string:
		if _, ok := expr.ExprOf(t); ok {
			return unknown{}
		}
	case map[string]any:
		m := make(map[string]any, len(t))
		for k, x := range t {
			m[k] = staticValue(x)
		}
		return m
	case []any:
		l := make([]any, len(t))
		for i, x := range t {
			l[i] = staticValue(x)
		}
		return l
	}
	return v
}

// isTerminator: is a yield the stream's terminator?
func isTerminator(st *contractStream, name string, v any) bool {
	if st.Terminator == nil {
		return false
	}
	if tn, ok := st.Terminator.(string); ok {
		for _, f := range st.Frames {
			if f.Name == tn {
				return name == tn
			}
		}
	}
	if sameValue(v, st.Terminator) {
		return true
	}
	if m, ok := v.(map[string]any); ok {
		if d, ok := m["data"]; ok && sameValue(d, st.Terminator) {
			return true
		}
	}
	return false
}

// compareStream compares the interface's yields with the contract's stream.
func compareStream(r *contractResult, c *contract, ifc *model.Interface, yields map[string][]yieldCall) {
	st := c.Stream
	resolve := func(ref string) (any, bool) { return c.file.pointer(ref) }
	var frames []*frameShape
	for _, f := range st.Frames {
		frames = append(frames, &frameShape{Name: f.Name, Shape: buildShape(f.Schema, resolve, 0), Consts: constraints(f.Schema, resolve, nil, 0)})
	}
	add := func(kind, f string, a ...any) {
		r.Issues = append(r.Issues, confIssue{kind, fmt.Sprintf(f, a...)})
	}
	// Frames the behavior can't produce at all.
	possible := map[string]bool{}
	tmpls := staticYields(ifc)
	for _, t := range tmpls {
		for _, f := range frames {
			if f.meets(t) {
				var is []confIssue
				validate("", t, f.Shape, 0, &is)
				if !hasKind(is, "type") {
					possible[f.Name] = true
				}
			}
		}
	}
	if len(tmpls) == 0 {
		add("frame-missing", "the interface has no yield step; the contract streams %d frames", len(frames))
		return
	}
	if yields == nil {
		return // the scenarios could not run
	}
	calls := yields[ifc.ID]
	yielded := map[string]bool{}
	seen := map[string]bool{} // issue dedupe
	once := func(kind, f string, a ...any) {
		msg := fmt.Sprintf(f, a...)
		if !seen[kind+"\x00"+msg] {
			seen[kind+"\x00"+msg] = true
			add(kind, "%s", msg)
		}
	}
	var orderRE *regexp.Regexp
	if st.Order != "" {
		orderRE = regexp.MustCompile("^(?:" + st.Order + ")$")
	}
	pos := map[string]int{}
	for i, f := range frames {
		pos[f.Name] = i
	}
	ran := false
	for _, call := range calls {
		ran = true
		if len(call.Items) == 0 {
			r.emptyCalls++
			continue
		}
		r.calls++
		names := make([]string, len(call.Items))
		for i, v := range call.Items {
			f, is := classify(frames, v)
			if f == nil {
				names[i] = "?"
				once("frame-extra", "yield %s matches no frame (scenario %s)", shapeSig(v), call.Scenario)
				continue
			}
			names[i] = f.Name
			yielded[f.Name] = true
			for _, x := range is {
				once(x.Kind, "frame %s %s", f.Name, x.Msg)
			}
		}
		seq := strings.Join(names, " ")
		if orderRE != nil {
			if !orderRE.MatchString(seq) {
				once("frame-order", "yields %q don't match order %q (scenario %s)", collapse(names), st.Order, call.Scenario)
			}
		} else {
			last := -1
			for _, n := range names {
				p, ok := pos[n]
				if !ok {
					continue
				}
				if p < last {
					once("frame-order", "yields %q are out of the frames' order (scenario %s)", collapse(names), call.Scenario)
					break
				}
				last = p
			}
		}
		if st.Terminator != nil {
			for i, v := range call.Items {
				if isTerminator(st, names[i], v) && i != len(call.Items)-1 {
					once("terminator", "terminator %v yielded before the end, at %d of %d (scenario %s)", st.Terminator, i+1, len(call.Items), call.Scenario)
				}
			}
			if call.Err {
				r.errCalls++
			} else if n := len(call.Items) - 1; !isTerminator(st, names[n], call.Items[n]) {
				once("terminator", "the stream ends with %s, not the terminator %v (scenario %s)", shapeSig(call.Items[n]), st.Terminator, call.Scenario)
			}
		}
	}
	if !ran {
		r.streamUnrun = true
	}
	for _, f := range frames {
		switch {
		case yielded[f.Name]:
		case possible[f.Name]:
			r.unrunFrames = append(r.unrunFrames, f.Name)
		default:
			once("frame-missing", "frame %s: no yield step can produce it, and no scenario yielded it", f.Name)
		}
	}
}

func hasKind(is []confIssue, kind string) bool {
	for _, x := range is {
		if x.Kind == kind {
			return true
		}
	}
	return false
}

// shapeSig describes a yield briefly: an object's sorted keys, else the value.
func shapeSig(v any) string {
	if m, ok := v.(map[string]any); ok {
		return "{" + strings.Join(sortedKeys(m), ",") + "}"
	}
	return short(v)
}

// collapse joins frame names, folding runs of one name into name*n.
func collapse(names []string) string {
	var out []string
	for i := 0; i < len(names); {
		j := i
		for j < len(names) && names[j] == names[i] {
			j++
		}
		if j-i > 1 {
			out = append(out, fmt.Sprintf("%s*%d", names[i], j-i))
		} else {
			out = append(out, names[i])
		}
		i = j
	}
	return strings.Join(out, " ")
}

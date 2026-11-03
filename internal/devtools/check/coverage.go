package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// invEntry is one entry of an inventory written by internal/devtools/inventory.
type invEntry struct {
	Kind    string `json:"kind"`
	Name    string `json:"name"`
	File    string `json:"file"`
	Line    int    `json:"line"`
	EndLine int    `json:"end_line,omitempty"`
	Via     string `json:"via,omitempty"`
	Skip    string `json:"skip,omitempty"`
	// Area names the owning area (the fragment file's base name without
	// .yaml) when the pipeline assigned owners from the profile's globs. It
	// takes precedence over ownership guessed from citations.
	Area string `json:"area,omitempty"`
	// Level "registered" marks a kind whose entries are declarations with no
	// behavior of their own (a service decorator): registered counts as modeled.
	Level string `json:"level,omitempty"`
}

func loadInventory(file string) ([]invEntry, error) {
	b, err := os.ReadFile(file)
	if err != nil {
		return nil, err
	}
	var wrapped struct {
		Entries []invEntry `json:"entries"`
	}
	if err := json.Unmarshal(b, &wrapped); err == nil && wrapped.Entries != nil {
		return wrapped.Entries, nil
	}
	var plain []invEntry
	if err := json.Unmarshal(b, &plain); err != nil {
		return nil, fmt.Errorf("%s: not an inventory: %w", file, err)
	}
	return plain, nil
}

// Coverage statuses, best first.
const (
	covSkipped    = "skipped"   // the inventory entry says why it is not modeled
	covLine       = "line"      // a flow-reachable entity cites the entry's lines
	covName       = "name"      // a flow-reachable interface is named after it (routes, workflows, activities) near its code
	covFile       = "file"      // a flow-reachable entity cites the file, but other lines
	covUnreached  = "unreached" // cited at its lines only by entities no flow reaches
	covUncovered  = "uncovered" // nothing cites it
	lineTolerance = 3
)

var covStatuses = []string{covLine, covName, covFile, covUnreached, covSkipped, covUncovered}

type covResult struct {
	invEntry
	Status string
	By     string // the entity that covers it
}

type span struct {
	lo, hi int
	entity string
}

// reachableEntities returns the entity keys (kind:id) that some flow reaches:
// every flow, the interfaces reachable from flow entries (and from the steps of
// multi-step scenarios) through calls, targets, emits and published topics'
// subscribers, their components, and the components flow steps name.
func reachableEntities(doc *model.Document) map[string]bool {
	ifaces := map[string]*model.Interface{}
	for k := range doc.Interfaces {
		i := &doc.Interfaces[k]
		i.Normalize()
		ifaces[i.ID] = i
	}
	subs := map[string][]string{}
	for _, i := range ifaces {
		for _, t := range i.Subscribe {
			subs[t] = append(subs[t], i.ID)
		}
	}
	out := map[string]bool{}
	var q []string
	for _, sc := range doc.Scenarios {
		for _, st := range sc.Steps {
			if st.Interface != "" {
				q = append(q, st.Interface)
			}
		}
	}
	for _, f := range doc.Flows {
		out["flow:"+f.ID] = true
		if f.Entry != nil {
			q = append(q, f.Entry.Interface)
		}
		for _, st := range f.Steps {
			if st.Component != "" {
				out["component:"+st.Component] = true
			}
		}
	}
	for len(q) > 0 {
		id := q[len(q)-1]
		q = q[:len(q)-1]
		if topic, ok := strings.CutPrefix(id, "publish:"); ok {
			q = append(q, subs[topic]...)
			continue
		}
		i, ok := ifaces[id]
		if !ok || out["interface:"+id] {
			continue
		}
		out["interface:"+id] = true
		out["component:"+i.Component] = true
		var steps []any
		b, _ := json.Marshal(i.Behavior)
		_ = json.Unmarshal(b, &steps)
		q = append(q, stepTargets(steps)...)
	}
	return out
}

// stepTargets lists the interfaces a behavior calls, targets or emits to,
// leaving out dynamic "= expr" calls.
func stepTargets(steps []any) []string {
	var out []string
	var walk func(v any)
	walk = func(v any) {
		switch v := v.(type) {
		case []any:
			for _, x := range v {
				walk(x)
			}
		case map[string]any:
			for _, k := range []string{"call", "emit"} {
				if s := str(v[k]); s != "" && !strings.HasPrefix(s, "=") {
					out = append(out, s)
				}
			}
			if s := str(v["publish"]); s != "" && !strings.HasPrefix(s, "=") {
				out = append(out, "publish:"+s)
			}
			if t, ok := v["targets"].([]any); ok {
				for _, x := range t {
					if s := str(x); s != "" {
						out = append(out, s)
					}
				}
			}
			for k, x := range v {
				if !dataKeys[k] && k != "targets" {
					walk(x)
				}
			}
		}
	}
	walk(steps)
	return out
}

var nonSlug = regexp.MustCompile(`[^a-z0-9]+`)

// routeSlug names a route the way the brief names HTTP interfaces:
// <method>-<path>, {param} becomes the param name, other characters dashes.
func routeSlug(method, p string) string {
	p = strings.NewReplacer("{", "", "}", "", "...", "").Replace(p)
	s := strings.Trim(nonSlug.ReplaceAllString(strings.ToLower(method+"-"+p), "-"), "-")
	if len(s) > 64 {
		s = strings.TrimRight(s[:64], "-")
	}
	return s
}

var camelBoundary = regexp.MustCompile(`([a-z0-9])([A-Z])`)

// funcSlug turns Type.FuncName into func-name.
func funcSlug(name string) string {
	if i := strings.LastIndex(name, "."); i >= 0 {
		name = name[i+1:]
	}
	return strings.Trim(nonSlug.ReplaceAllString(strings.ToLower(camelBoundary.ReplaceAllString(name, "$1-$2")), "-"), "-")
}

func trimKindSuffix(s string) string {
	for _, suf := range []string{"-workflow", "-activity", "-step"} {
		s = strings.TrimSuffix(s, suf)
	}
	return s
}

// area is the directory an entry is grouped under: its first two path
// segments (services/control-plane-go, apps/toolbox).
func area(file string) string {
	parts := strings.Split(file, "/")
	if len(parts) > 2 {
		parts = parts[:2]
	} else {
		parts = parts[:len(parts)-1]
	}
	if len(parts) == 0 {
		return "."
	}
	return strings.Join(parts, "/")
}

// coverage scores each inventory entry against the document's citations.
func coverage(doc *model.Document, cites []citation, inv []invEntry) []covResult {
	reach := reachableEntities(doc)
	reachSpans := map[string][]span{} // file -> spans cited by reachable entities
	otherSpans := map[string][]span{}
	reachDirs := map[string]bool{} // directories and areas reachable entities cite
	for _, c := range cites {
		f := path.Clean(normPath(c.Src.Path))
		hi := c.Src.EndLine
		if hi < c.Src.Line {
			hi = c.Src.Line
		}
		sp := span{c.Src.Line, hi, c.Entity}
		if reach[c.Entity] {
			reachSpans[f] = append(reachSpans[f], sp)
			reachDirs[path.Dir(f)] = true
			reachDirs["area:"+area(f)] = true
		} else {
			otherSpans[f] = append(otherSpans[f], sp)
		}
	}
	// Names of reachable interfaces, for route and function matching.
	var reachIfaces []named
	for _, i := range doc.Interfaces {
		if reach["interface:"+i.ID] {
			reachIfaces = append(reachIfaces, named{i.Name, i.ID})
		}
	}
	hit := newHitter(inv)
	var out []covResult
	for _, e := range inv {
		r := covResult{invEntry: e}
		f := path.Clean(e.File)
		if e.Skip != "" {
			r.Status = covSkipped
			out = append(out, r)
			continue
		}
		if by, ok := hit(reachSpans[f], e); ok {
			r.Status, r.By = covLine, by
			out = append(out, r)
			continue
		}
		// Name matches count only when reachable entities also cite code
		// near the entry: the same area for routes, the same directory for
		// functions. That keeps a generic name from matching across services.
		if want, nearKey := nameWants(e); nearKey != "" && reachDirs[nearKey] {
			if id := nameMatch(want, reachIfaces); id != "" {
				r.Status, r.By = covName, "interface:"+id
				out = append(out, r)
				continue
			}
		}
		if by, ok := hit(otherSpans[f], e); ok {
			r.Status, r.By = covUnreached, by
		} else if len(reachSpans[f]) > 0 {
			r.Status, r.By = covFile, reachSpans[f][0].entity
		} else {
			r.Status = covUncovered
		}
		out = append(out, r)
	}
	return out
}

type named struct{ name, id string }

// newHitter returns a function that finds a span covering an entry's lines.
// The tolerance never reaches a neighboring entry's line, so a citation of
// one line in a dense list (an enum of verbs) covers only that entry.
func newHitter(inv []invEntry) func([]span, invEntry) (string, bool) {
	entryLines := map[string][]int{}
	for _, e := range inv {
		f := path.Clean(e.File)
		entryLines[f] = append(entryLines[f], e.Line)
	}
	for _, ls := range entryLines {
		sort.Ints(ls)
	}
	return func(spans []span, e invEntry) (string, bool) {
		lo, hi := e.Line-lineTolerance, e.Line+lineTolerance
		if e.EndLine > e.Line {
			hi = e.EndLine + lineTolerance
		}
		for _, l := range entryLines[path.Clean(e.File)] {
			if l < e.Line && l >= lo {
				lo = l + 1
			}
			if l > e.Line && l <= hi && (e.EndLine <= e.Line || l > e.EndLine) {
				hi = l - 1
			}
		}
		for _, s := range spans {
			if s.lo > 0 && s.lo <= hi && s.hi >= lo {
				return s.entity, true
			}
		}
		return "", false
	}
}

// nameWants lists the interface names an entry may be modeled under and the
// key ("area:<area>" for routes, the directory for functions) that matching
// entities must also cite near it; nearKey is "" when names don't apply.
func nameWants(e invEntry) (want []string, nearKey string) {
	f := path.Clean(e.File)
	switch e.Kind {
	case "http-route", "next-route":
		if m, p, ok := strings.Cut(e.Name, " "); ok && !strings.HasPrefix(p, "{") {
			if m == "ANY" {
				want = append(want, "*-"+routeSlug("", p))
			} else {
				want = append(want, routeSlug(m, p))
			}
		}
		return want, "area:" + area(f)
	case "temporal-workflow", "temporal-activity", "cron":
		s := funcSlug(e.Name)
		return []string{s, trimKindSuffix(s)}, path.Dir(f)
	}
	return nil, ""
}

// nameMatch returns the id of the first interface named as one of want.
func nameMatch(want []string, ifaces []named) string {
	for _, w := range want {
		for _, n := range ifaces {
			if w == n.name || trimKindSuffix(n.name) == w ||
				(strings.HasPrefix(w, "*-") && strings.HasSuffix(n.name, w[1:])) {
				return n.id
			}
		}
	}
	return ""
}

// covered reports whether a result counts as registered (DESIGN §13.1 item 13).
func (r covResult) covered() bool { return r.Status == covLine || r.Status == covName }

type covTable struct {
	kinds       []string
	byKind      map[string]map[string]int
	areas       []string
	byArea      map[string]map[string]int // area -> kind -> uncovered count
	totals      map[string]int
	results     []covResult
	modeled     map[string]int // kind -> modeled entries, when measured (setModeled)
	substantive map[string]int // kind -> substantive entries, when measured
}

func tabulate(res []covResult) *covTable {
	t := &covTable{byKind: map[string]map[string]int{}, byArea: map[string]map[string]int{}, totals: map[string]int{}, results: res}
	for _, r := range res {
		if t.byKind[r.Kind] == nil {
			t.byKind[r.Kind] = map[string]int{}
			t.kinds = append(t.kinds, r.Kind)
		}
		t.byKind[r.Kind][r.Status]++
		t.totals[r.Status]++
		if !r.covered() && r.Status != covSkipped {
			a := area(r.File)
			if t.byArea[a] == nil {
				t.byArea[a] = map[string]int{}
				t.areas = append(t.areas, a)
			}
			t.byArea[a][r.Kind]++
			t.byArea[a][""]++
		}
	}
	sort.Strings(t.kinds)
	sort.Slice(t.areas, func(i, j int) bool {
		a, b := t.byArea[t.areas[i]][""], t.byArea[t.areas[j]][""]
		if a != b {
			return a > b
		}
		return t.areas[i] < t.areas[j]
	})
	return t
}

func pct(n, d int) string {
	if d == 0 {
		return "-"
	}
	return fmt.Sprintf("%.0f%%", 100*float64(n)/float64(d))
}

func (t *covTable) coveredOf(m map[string]int) (int, int) {
	total := 0
	for _, s := range covStatuses {
		total += m[s]
	}
	return m[covLine] + m[covName], total - m[covSkipped]
}

// markdown writes the coverage tables; topAreas bounds the directory table.
func (t *covTable) markdown(w io.Writer, topAreas int) {
	fmt.Fprintln(w, "| Kind | Entries | Covered (lines) | Covered (name) | File only | Unreached | Skipped | Uncovered | Coverage |")
	fmt.Fprintln(w, "|---|---|---|---|---|---|---|---|---|")
	row := func(name string, m map[string]int) {
		c, d := t.coveredOf(m)
		fmt.Fprintf(w, "| %s | %d | %d | %d | %d | %d | %d | %d | %s |\n", name, d+m[covSkipped], m[covLine], m[covName], m[covFile], m[covUnreached], m[covSkipped], m[covUncovered], pct(c, d))
	}
	for _, k := range t.kinds {
		row(k, t.byKind[k])
	}
	row("**all**", t.totals)
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Not covered (file only, unreached or uncovered), by directory:")
	fmt.Fprintln(w)
	fmt.Fprintln(w, "| Directory | Not covered | By kind |")
	fmt.Fprintln(w, "|---|---|---|")
	for i, a := range t.areas {
		if i == topAreas {
			break
		}
		var ks []string
		for _, k := range t.kinds {
			if n := t.byArea[a][k]; n > 0 {
				ks = append(ks, fmt.Sprintf("%s %d", k, n))
			}
		}
		fmt.Fprintf(w, "| `%s` | %d | %s |\n", a, t.byArea[a][""], strings.Join(ks, ", "))
	}
	if len(t.areas) > topAreas {
		fmt.Fprintf(w, "| (%d more) | | |\n", len(t.areas)-topAreas)
	}
}

func (t *covTable) print(w io.Writer, verbose bool) {
	for _, k := range t.kinds {
		m := t.byKind[k]
		c, d := t.coveredOf(m)
		fmt.Fprintf(w, "coverage %-18s %3d/%-3d %4s  (lines %d, name %d, file only %d, unreached %d, skipped %d, uncovered %d)",
			k, c, d, pct(c, d), m[covLine], m[covName], m[covFile], m[covUnreached], m[covSkipped], m[covUncovered])
		if t.modeled != nil {
			fmt.Fprintf(w, "  modeled %d  substantive %d", t.modeled[k], t.substantive[k])
		}
		fmt.Fprintln(w)
	}
	for i, a := range t.areas {
		if i == 10 {
			break
		}
		fmt.Fprintf(w, "  not covered in %s: %d\n", a, t.byArea[a][""])
	}
	if verbose {
		for _, r := range t.results {
			if !r.covered() && r.Status != covSkipped {
				by := ""
				if r.By != "" {
					by = " (" + r.By + ")"
				}
				fmt.Fprintf(w, "  - %s %s %q %s:%d%s\n", r.Status, r.Kind, r.Name, r.File, r.Line, by)
			}
		}
	}
	c, d := t.coveredOf(t.totals)
	fmt.Fprintf(w, "coverage: %d of %d entry points covered (%s), %d skipped, %d not covered\n", c, d, pct(c, d), t.totals[covSkipped], d-c)
}

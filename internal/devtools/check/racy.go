package main

// The racy lint (DESIGN §13.1 item 28): a behavior that reads a store row or
// a state path and later writes the same row or path unconditionally, outside
// a transact. Blind judges found compare-and-set modeled this way in a
// generated gateway-platform model (a dispatch fence, a billing transaction
// record, a close-if-open, a key-budget counter): a lost update or a double
// claim that no scenario showed, because none raced the write.

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// racyAccess is one read or write a behavior step makes.
type racyAccess struct {
	idx   int    // the step's position in behaviorPaths order
	path  string // the step path
	title string
	// table is "<component>/<table>" for a store access, "" for state.
	table string
	key   racyKey  // a store access's row key, as far as it is literal
	segs  []string // a state access's literal path under state
	op    string   // get, query, put, update, set
	as    string   // a read's variable: the call's as, or the vars a set of a state read assigns
	value string   // a state set's value source
	dyn   bool     // a state set whose path has no literal segment
	// Transitions (§13.1 item 33), for an unconditional store write: the
	// state-machine field its item sets, the roots (vars.v, input.vm) its
	// key is built from, and whether the key is a freshly generated id.
	// For a guard (an if or when testing a state field), as is the root
	// tested and value the field.
	sets     string
	keyRoots []string
	fresh    bool
}

// yields reports whether a step can let another task run: a call, a route
// call, a wait, a parallel, a channel or rendezvous step, or a sync publish.
func yields(s model.Step) bool {
	return s.Call != "" || s.Route != nil || s.Wait != nil || s.IsParallel() || s.Receive != "" || s.Put != "" ||
		s.Rendezvous != "" || (s.Publish != "" && s.Delivery == model.DeliverySync)
}

func (a racyAccess) what() string {
	if a.table != "" {
		s := a.table
		if k := a.key.String(); k != "" {
			s += " key " + k
		}
		return s
	}
	if a.dyn {
		return "state (dynamic path)"
	}
	return "state." + strings.Join(a.segs, ".")
}

func (a racyAccess) at() string {
	s := a.path
	if i := strings.Index(s, ":"); i >= 0 {
		s = s[i+1:]
	}
	if a.title != "" {
		s += " (" + oneLine(a.title, 60) + ")"
	}
	return s
}

var (
	// startsWithKey is a query's key filter: key.startsWith(<prefix>...).
	startsWithKey = regexp.MustCompile(`key\.startsWith\(\s*(.*)$`)
	leadingVar    = regexp.MustCompile(`^vars\.([A-Za-z_][A-Za-z0-9_]*)\b`)
)

// storeOnly returns the store spec of an interface that is only a store
// operation (a store and no behavior), or nil.
func storeOnly(i *model.Interface) *model.StoreSpec {
	if i == nil || i.Store == nil || len(i.Behavior) > 0 {
		return nil
	}
	return i.Store
}

// stepInput decodes a step's literal input map.
func stepInput(s model.Step) map[string]any {
	if len(s.Input) == 0 {
		return nil
	}
	var m map[string]any
	if json.Unmarshal(s.Input, &m) != nil {
		return nil
	}
	return m
}

// varsSets maps each vars.<name> a behavior sets with a literal key to its
// first template, for resolving key prefixes one level through a variable.
func varsSets(ps []stepPath) map[string]any {
	out := map[string]any{}
	for _, sp := range ps {
		for k, v := range sp.Step.Set {
			if n, ok := strings.CutPrefix(k, "vars."); ok && !strings.Contains(n, ".") {
				if _, seen := out[n]; !seen {
					out[n] = v
				}
			}
		}
	}
	return out
}

// templatePrefix is literalPrefix that also follows "= vars.v" (or a
// concatenation starting with vars.v) to the variable's set template.
func templatePrefix(t any, vars map[string]any) string {
	pfx, _ := literalPrefix(t)
	if pfx != "" {
		return pfx
	}
	if s, ok := t.(string); ok {
		if e, isCEL := strings.CutPrefix(s, "="); isCEL {
			e = strings.TrimSpace(e)
			if m := leadingVar.FindStringSubmatch(e); m != nil {
				if v, ok := vars[m[1]]; ok {
					p, _ := literalPrefix(v)
					return p
				}
			}
		}
	}
	return ""
}

// racyKey is what is literal about a store call's row key: the spec key's
// literal prefix, and the literal prefix of each input field the key is
// built from at the call site (pk, sk; a query's sk_prefix counts as sk).
type racyKey struct {
	lit   string
	parts map[string]string
	order []string
}

func (k racyKey) String() string {
	var out []string
	if k.lit != "" {
		out = append(out, k.lit+"*")
	}
	for _, f := range k.order {
		out = append(out, f+"="+k.parts[f]+"*")
	}
	return strings.Join(out, " ")
}

// compat reports whether two keys can name the same row: every literal
// prefix they both have agrees.
func (k racyKey) compat(o racyKey) bool {
	if !keyCompat(k.lit, o.lit) {
		return false
	}
	for f, p := range k.parts {
		if q, ok := o.parts[f]; ok && !keyCompat(p, q) {
			return false
		}
	}
	return true
}

var inputRefs = regexp.MustCompile(`(?:^|[^A-Za-z0-9_.])input\.([A-Za-z_][A-Za-z0-9_]*)`)

// storeKey resolves a store call's row key: the spec's key, or a query's
// key.startsWith filter; each input.<f> it uses is resolved against the
// call's input, and a variable one level through its set.
func storeKey(st *model.StoreSpec, call model.Step, vars map[string]any) racyKey {
	var src string
	switch k := st.Key.(type) {
	case nil:
		m := startsWithKey.FindStringSubmatch(st.Where)
		if m == nil {
			return racyKey{}
		}
		src = m[1]
		if lm := leadingQuote.FindStringSubmatch(src); lm != nil {
			return racyKey{lit: lm[1] + lm[2]}
		}
	case string:
		e, isCEL := strings.CutPrefix(k, "=")
		if !isCEL {
			return racyKey{lit: k}
		}
		if pfx, _ := literalPrefix(k); pfx != "" {
			return racyKey{lit: pfx}
		}
		src = e
	default:
		return racyKey{lit: fmt.Sprint(k)}
	}
	in := stepInput(call)
	key := racyKey{parts: map[string]string{}}
	for _, m := range inputRefs.FindAllStringSubmatch(src, -1) {
		f := m[1]
		name := strings.TrimSuffix(strings.TrimSuffix(f, "_prefix"), "Prefix")
		v, ok := in[f]
		if _, seen := key.parts[name]; seen || !ok {
			continue
		}
		key.parts[name] = templatePrefix(v, vars)
		key.order = append(key.order, name)
	}
	return key
}

// shallow returns a step without its nested step lists, so its CEL is only
// its own.
func shallow(s model.Step) model.Step {
	s.Then, s.Else, s.Options, s.Steps, s.Branches, s.OnItem, s.OnLate, s.Transact = nil, nil, nil, nil, nil, nil, nil, nil
	if s.OnError != nil {
		oe := *s.OnError
		oe.Steps = nil
		s.OnError = &oe
	}
	return s
}

// exclusive reports whether two step paths sit in different branches of
// one if or choice, so they never both run.
func exclusive(a, b string) bool {
	_, a, _ = strings.Cut(a, ":")
	_, b, _ = strings.Cut(b, ":")
	ta, tb := strings.Split(a, "."), strings.Split(b, ".")
	for j := 0; j < len(ta) && j < len(tb); j++ {
		if ta[j] == tb[j] {
			continue
		}
		na, _, _ := strings.Cut(ta[j], "[")
		nb, _, _ := strings.Cut(tb[j], "[")
		if na != nb && (na == "then" || na == "else") && (nb == "then" || nb == "else") {
			return true
		}
		return j > 0 && ta[j-1] == "options" && na != nb
	}
	return false
}

// rereads reports whether a state set's value reads the path it writes
// afresh (state.n = state.n + 1, omit(state.m, k)): an atomic
// read-modify-write in the simulator, unless it also uses a variable the
// earlier read set.
func rereads(wr racyAccess) bool {
	ps, _ := statePaths(wr.value)
	for _, p := range ps {
		if segsCompat(p, wr.segs) {
			return true
		}
	}
	return false
}

// yieldsBetween reports whether a yielding step runs after the read and
// before the write: at the read's step or later, before the write's, and
// on a path that runs with both.
func yieldsBetween(ys []racyAccess, rd, wr racyAccess) bool {
	for _, y := range ys {
		if y.idx >= rd.idx && y.idx < wr.idx && !exclusive(y.path, rd.path) && !exclusive(y.path, wr.path) {
			return true
		}
	}
	return false
}

func segsCompat(a, b []string) bool {
	if len(a) == 0 || len(b) == 0 {
		return false
	}
	n := min(len(a), len(b))
	return equalSegs(a[:n], b[:n])
}

func keyCompat(a, b string) bool {
	return strings.HasPrefix(a, b) || strings.HasPrefix(b, a)
}

var wordAfter = regexp.MustCompile(`^[A-Za-z0-9_]`)

// mentionsVar reports whether a CEL source reads vars.<name>.
func mentionsVar(src, name string) bool {
	if name == "" {
		return false
	}
	needle := "vars." + name
	for i := strings.Index(src, needle); i >= 0; {
		rest := src[i+len(needle):]
		if !wordAfter.MatchString(rest) && (i == 0 || !wordAfter.MatchString(src[i-1:i]) && src[i-1] != '.') {
			return true
		}
		j := strings.Index(rest, needle)
		if j < 0 {
			break
		}
		i += len(needle) + j
	}
	return false
}

// behaviorAccesses lists the store and state reads and writes of a
// behavior, in step order. Writes are only the unconditional ones (a put or
// update without if, if_absent or where, and state sets); every write,
// conditional or not, is reported to wrote, for the other-writer rule.
func behaviorAccesses(x *model.Index, i *model.Interface, fields map[string]bool, wrote func(table string, segs []string, key *racyKey)) (reads, writes, yield, guards []racyAccess, writesAny bool) {
	ps := behaviorPaths(i)
	vars := varsSets(ps)
	for n, sp := range ps {
		s := sp.Step
		if yields(s) {
			yield = append(yield, racyAccess{idx: n, path: sp.Path})
		}
		base := racyAccess{idx: n, path: sp.Path, title: s.Title}
		for _, cond := range []string{s.If, s.When} {
			for _, g := range stateGuards(cond, fields) {
				a := base
				a.op, a.as, a.value = "guard", g[0], g[1]
				guards = append(guards, a)
			}
		}
		if len(s.Transact) > 0 {
			writesAny = true
			for _, t := range s.Transact {
				if t.Op != "delete" && t.Op != "" {
					wrote(i.Component+"/"+t.Table, nil, nil)
				}
			}
		}
		if s.Call != "" && !strings.HasPrefix(s.Call, "=") {
			if t := x.Interfaces[s.Call]; storeOnly(t) != nil {
				st := t.Store
				a := base
				a.table, a.op = t.Component+"/"+st.Table, st.Op
				a.key = storeKey(st, s, vars)
				switch st.Op {
				case "get", "query":
					a.as = s.As
					reads = append(reads, a)
				case "put", "update", "incr", "delete":
					writesAny = true
					wrote(a.table, nil, &a.key)
					if (st.Op == "put" || st.Op == "update") && st.If == "" && !st.IfAbsent && st.Where == "" {
						a.sets = setsStateField(st, s, fields)
						a.keyRoots, a.fresh = keyRoots(st, s, vars)
						writes = append(writes, a)
					}
				}
			}
		}
		// State reads in this step's own CEL; a set of vars from them names
		// the read's variable.
		celStrings(asJSON(shallow(s)), "", func(src string) {
			ps, _ := statePaths(src)
			for _, p := range ps {
				a := base
				a.segs, a.op = p, "read"
				reads = append(reads, a)
			}
		})
		for k, v := range s.Set {
			if n, ok := strings.CutPrefix(k, "vars."); ok {
				src := ""
				celStrings(asJSON(v), "", func(e string) { src += e + "\n" })
				if ps, _ := statePaths(src); len(ps) > 0 {
					for _, p := range ps {
						a := base
						a.segs, a.op, a.as = p, "read", strings.SplitN(n, ".", 2)[0]
						reads = append(reads, a)
					}
				}
				continue
			}
			a := base
			a.op = "set"
			if e, ok := strings.CutPrefix(k, "="); ok {
				pfx, _ := literalPrefix("=" + e)
				rest, isState := strings.CutPrefix(pfx, "state.")
				if !isState && !(pfx == "" && strings.Contains(e, "state")) {
					continue
				}
				for _, sg := range strings.Split(rest, ".") {
					if sg != "" {
						a.segs = append(a.segs, sg)
					}
				}
				if !strings.HasSuffix(rest, ".") && len(a.segs) > 0 {
					a.segs = a.segs[:len(a.segs)-1]
				}
				a.dyn = len(a.segs) == 0
			} else if rest, ok := strings.CutPrefix(k, "state."); ok {
				a.segs = strings.Split(rest, ".")
			} else {
				continue
			}
			celStrings(asJSON(v), "", func(e string) { a.value += e + "\n" })
			writesAny = true
			wrote(i.Component+"/", a.segs, nil)
			writes = append(writes, a)
		}
	}
	return reads, writes, yield, guards, writesAny
}

// stateGuards lists the roots and state fields a condition tests:
// vars.v.status, vars.r.value.vm.phase or input.vm.status give
// [vars.v status], [vars.r phase], [input.vm status].
func stateGuards(cond string, fields map[string]bool) [][2]string {
	if cond == "" {
		return nil
	}
	var out [][2]string
	for _, m := range guardRef.FindAllStringSubmatch(cond, -1) {
		segs := strings.Split(m[3], ".")
		root := m[1] + "." + m[2]
		if f := segs[len(segs)-1]; fields[strings.ToLower(f)] && !requestRoot.MatchString(root) {
			out = append(out, [2]string{root, f})
		}
	}
	return out
}

var (
	guardRef = regexp.MustCompile(`\b(vars|input)\.([A-Za-z_][A-Za-z0-9_]*)((?:\.[A-Za-z_][A-Za-z0-9_]*)+)`)
	rootRef  = regexp.MustCompile(`\b(vars|input)\.([A-Za-z_][A-Za-z0-9_]*)`)
	freshID  = regexp.MustCompile(`\b(uuid|ulid|nanoid|random|newid|new_id)\s*\(|\bnow\b`)
	// requestRoot is a root that holds the request itself, not a copy of
	// a row: testing input.body.status is validating what the caller asks.
	requestRoot = regexp.MustCompile(`^input\.(body|query|params|headers|header|form)$`)
	// datastoreKind is a component kind that holds shared rows.
	datastoreKind = regexp.MustCompile(`(?i)data|store|db|storage|table|sql`)
	// itemField matches a CEL map literal key: 'status': or "status":.
	itemField = regexp.MustCompile(`['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*:`)
)

// setsStateField returns the state-machine field an unconditional store
// write's item sets: a literal key of the call's input (at any depth up to
// three) or the store's value, or a CEL map key, that is a state field.
func setsStateField(st *model.StoreSpec, call model.Step, fields map[string]bool) string {
	found := ""
	var walk func(v any, depth int)
	walk = func(v any, depth int) {
		if found != "" || depth > 2 {
			return
		}
		switch v := v.(type) {
		case map[string]any:
			keys := make([]string, 0, len(v))
			for k := range v {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				if fields[strings.ToLower(k)] && depth > 0 {
					found = k
					return
				}
			}
			for _, k := range keys {
				walk(v[k], depth+1)
			}
		case string:
			if e, ok := strings.CutPrefix(v, "="); ok {
				for _, m := range itemField.FindAllStringSubmatch(e, -1) {
					if fields[strings.ToLower(m[1])] {
						found = m[1]
						return
					}
				}
			}
		}
	}
	// depth 1 for the call's input keys themselves: a top-level status
	// input is the value the store writes, as an item field is.
	if in := stepInput(call); in != nil {
		walk(map[string]any{"input": in}, 0)
	}
	if found == "" {
		walk(map[string]any{"value": asJSON(st.Value)}, 0)
	}
	return found
}

// keyRoots lists the roots (vars.v, input.vm) a store call's key fields are
// built from, and whether the key is a freshly generated id: its template,
// or a variable it uses, calls uuid(), random() and the like.
func keyRoots(st *model.StoreSpec, call model.Step, vars map[string]any) ([]string, bool) {
	src := ""
	switch k := st.Key.(type) {
	case string:
		src = k
	}
	in := stepInput(call)
	var tmpls []string
	for _, m := range inputRefs.FindAllStringSubmatch(src, -1) {
		if v, ok := in[m[1]]; ok {
			celStrings(asJSON(v), "", func(e string) { tmpls = append(tmpls, e) })
		}
	}
	var roots []string
	fresh := false
	for _, t := range tmpls {
		if freshID.MatchString(t) {
			fresh = true
		}
		for _, m := range rootRef.FindAllStringSubmatch(t, -1) {
			roots = append(roots, m[1]+"."+m[2])
			if m[1] == "vars" {
				celStrings(asJSON(vars[m[2]]), "", func(e string) {
					if freshID.MatchString(e) {
						fresh = true
					}
				})
			}
		}
	}
	return uniq(roots), fresh
}

// codeCite matches a path:line citation (svc/budget.go:75, a.go:10-12).
var codeCite = regexp.MustCompile(`[A-Za-z0-9_./-]+\.[A-Za-z0-9]+:\d+`)

func componentAttrs(c *model.Component) map[string]any {
	if c == nil {
		return nil
	}
	return c.Attributes
}

// lintRacy lists the behaviors that read a store row or state path and
// later write it with an unconditional put, update or set, outside a
// transact, when the behavior can race: its component has several
// instances somewhere, or no capacity of concurrency 1, or another
// interface writes the same table or path. attributes.racy_in_code (a
// path:line citation) on the interface or component lists the finding apart,
// as racy in the code itself. attributes.single_writer on the
// interface or its component exempts it. The share is over the behaviors
// that write a store or state.
func lintRacy(doc *model.Document, origins map[string]string) *integrityReport {
	return lintRacyWith(doc, origins, nil)
}

// lintRacyWith is lintRacy with the profile's naming.state_fields: besides
// read-then-write pairs it lists unconditional status transitions (§13.1
// item 33), reported as racy (transition): an unconditional put or update
// on a table another interface also writes, whose item sets a state-machine
// field, or whose key comes from a row the behavior tested a state field of
// (a status check fencing the write on a stale copy).
func lintRacyWith(doc *model.Document, origins map[string]string, prof *lintProfile) *integrityReport {
	fields := prof.stateFields()
	x := indexed(doc)
	ids := sortedIfaces(x)
	instances := map[string]int{}
	topo := func(t map[string][]string) {
		for c, is := range t {
			instances[c] = max(instances[c], len(is))
		}
	}
	for _, f := range doc.Fixtures {
		topo(f.Topology)
	}
	for _, s := range doc.Scenarios {
		topo(s.Topology)
	}
	type writer struct {
		iface string
		segs  []string
		key   *racyKey
	}
	writers := map[string][]writer{} // table key ("comp/table", or "comp/" for state) -> writers
	type acc struct {
		reads, writes, yield, guards []racyAccess
		writesAny                    bool
	}
	all := map[string]acc{}
	for _, id := range ids {
		i := x.Interfaces[id]
		if len(i.Behavior) == 0 {
			continue
		}
		r, w, y, g, wa := behaviorAccesses(x, i, fields, func(table string, segs []string, key *racyKey) {
			writers[table] = append(writers[table], writer{id, segs, key})
		})
		all[id] = acc{r, w, y, g, wa}
	}
	otherWriter := func(id, table string, segs []string) string {
		for _, w := range writers[table] {
			if w.iface == id {
				continue
			}
			if segs == nil || w.segs == nil || segsCompat(segs, w.segs) {
				return w.iface
			}
		}
		return ""
	}
	r := &integrityReport{Lint: "racy", Unit: "store- or state-writing behaviors"}
	sc := shareCounter{}
	for _, id := range ids {
		a, ok := all[id]
		if !ok || !a.writesAny {
			continue
		}
		i := x.Interfaces[id]
		frag := origins[model.KindInterface+"/"+id]
		c := x.Components[i.Component]
		if str(i.Attributes["single_writer"]) != "" || (c != nil && str(c.Attributes["single_writer"]) != "") {
			sc.add(frag, false)
			continue
		}
		type pair struct{ rd, wr racyAccess }
		var pairs []pair
		seen := map[string]bool{}
		for _, rd := range a.reads {
			for _, wr := range a.writes {
				if wr.idx < rd.idx || (wr.idx == rd.idx && wr.op != "set") || exclusive(rd.path, wr.path) {
					continue
				}
				match := false
				switch {
				case rd.table != "":
					match = wr.table == rd.table && rd.key.compat(wr.key)
					if !match && wr.table == "" && wr.dyn && rd.as != "" && mentionsVar(wr.value, rd.as) {
						match = true // a dynamic set of a value built from the row
					}
				default:
					match = wr.table == "" && (segsCompat(rd.segs, wr.segs) || (wr.dyn && rd.as != "" && mentionsVar(wr.value, rd.as)))
				}
				if !match {
					continue
				}
				// In-process state read and written with no step between them
				// that lets another task run is atomic, as a mutex-held
				// section is: the simulator never interleaves it. So is a
				// set whose value reads the path afresh.
				if wr.table == "" && rd.table == "" && (!yieldsBetween(a.yield, rd, wr) || rereads(wr) && !mentionsVar(wr.value, rd.as)) {
					continue
				}
				k := rd.what() + "\x00" + wr.what()
				if seen[k] {
					continue
				}
				seen[k] = true
				pairs = append(pairs, pair{rd, wr})
			}
		}
		kind, why := "racy", ""
		if len(pairs) == 0 {
			// No read-then-write pair: an unconditional status transition?
			tr, how := transition(a.writes, a.guards, func(table string) bool {
				comp, _, _ := strings.Cut(table, "/")
				tc := x.Components[comp]
				return tc != nil && datastoreKind.MatchString(tc.Kind)
			})
			if how == "" {
				sc.add(frag, false)
				continue
			}
			switch {
			case instances[i.Component] > 1 && !strings.HasPrefix(tr.table, i.Component+"/"):
				why = fmt.Sprintf("%s runs %d instances", i.Component, instances[i.Component])
			default:
				for _, w := range writers[tr.table] {
					if w.iface != id && (w.key == nil || w.key.compat(tr.key)) {
						why = "another writer: " + w.iface
						break
					}
				}
			}
			if why == "" {
				sc.add(frag, false)
				continue
			}
			kind = "racy (transition)"
			pairs = append(pairs, pair{racyAccess{title: how}, tr})
		}
		// Can it race? Several instances, no capacity of 1, or another writer.
		p := pairs[0]
		switch {
		case kind != "racy":
		case instances[i.Component] > 1 && p.wr.table != "" && !strings.HasPrefix(p.wr.table, i.Component+"/"):
			// Instances race on a table another component keeps; each
			// instance's own state and tables are its own (§11.1).
			why = fmt.Sprintf("%s runs %d instances", i.Component, instances[i.Component])
		case c == nil || c.Capacity == nil || c.Capacity.Concurrency != 1:
			why = i.Component + " has no capacity of concurrency 1"
		default:
			table := p.wr.table
			if table == "" {
				table = i.Component + "/"
			}
			if o := otherWriter(id, table, p.wr.segs); o != "" {
				why = "another writer: " + o
			}
		}
		if why == "" {
			sc.add(frag, false)
			continue
		}
		// A model faithful to code that really races keeps the race: a
		// finding about the system, listed apart, not about the model.
		cite, citeWho := "", ""
		for _, at := range []struct {
			who   string
			attrs map[string]any
		}{{"interface " + id, i.Attributes}, {"component " + i.Component, componentAttrs(c)}} {
			if v, ok := at.attrs["racy_in_code"]; ok && cite == "" {
				if v := str(v); codeCite.MatchString(v) {
					cite, citeWho = v, at.who
				} else {
					r.Warnings = append(r.Warnings, fmt.Sprintf("%s: attributes.racy_in_code needs a path:line citation of the code's read and its unconditional write (got %q); not exempt", at.who, v))
				}
			}
		}
		pairWhy := fmt.Sprintf("reads %s at %s, then writes %s unconditionally (%s) at %s; %s",
			p.rd.what(), p.rd.at(), p.wr.what(), p.wr.op, p.wr.at(), why)
		if kind != "racy" {
			pairWhy = fmt.Sprintf("writes %s unconditionally (%s) at %s, %s; %s", p.wr.what(), p.wr.op, p.wr.at(), p.rd.title, why)
		}
		if cite != "" {
			sc.add(frag, false)
			r.System = append(r.System, integrityFinding{kind, frag, id, pairWhy + "; racy in code (" + citeWho + "): " + cite})
			continue
		}
		sc.add(frag, true)
		fix := "if: row.version == ..., if_absent, incr or transact"
		if kind != "racy" {
			fix = "if: row." + first(p.wr.sets, "status") + " == ... (the code's fence), if_absent or transact"
		}
		if p.wr.table == "" {
			fix = "a store write with if or if_absent, incr, transact, or attributes.single_writer with a citation"
		}
		more := ""
		if len(pairs) > 1 {
			more = fmt.Sprintf(" (and %d more read-write pairs)", len(pairs)-1)
		}
		r.Findings = append(r.Findings, integrityFinding{kind, frag, id, fmt.Sprintf("%s; fix: %s, or attributes.racy_in_code citing the code when it really races%s", pairWhy, fix, more)})
	}
	r.finish(sc)
	return r
}

// transition finds an unconditional store write that is a status
// transition: its item sets a state-machine field, or its key comes from a
// root an earlier guard tested a state field of. Only tables of datastore
// components count: a scheduler's jobs, a workflow engine's runs, a cache
// and a module's in-process registry aren't fenced rows. A put of a freshly
// generated key (a new row nobody else can name) is not one.
func transition(writes, guards []racyAccess, shared func(table string) bool) (racyAccess, string) {
	for _, wr := range writes {
		if wr.table == "" || (wr.fresh && wr.op == "put") || !shared(wr.table) {
			continue
		}
		if wr.sets != "" {
			return wr, "setting " + wr.sets + " (a status transition; code usually fences these)"
		}
		for _, g := range guards {
			if g.idx >= wr.idx || exclusive(g.path, wr.path) {
				continue
			}
			for _, k := range wr.keyRoots {
				if k == g.as {
					return wr, fmt.Sprintf("after testing %s.%s at %s (a status check fencing a write on a copy that can be stale)", g.as, g.value, g.at())
				}
			}
		}
	}
	return racyAccess{}, ""
}

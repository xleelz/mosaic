package model

import (
	"bytes"
	"encoding/json"
	"sort"
	"strings"
)

// ComputeImpact compares before and after, entity by entity, and lists the
// unchanged flows whose reach contains a changed entity.
//
// Entities are matched by kind and id and compared by canonical JSON (keys
// sorted, raw JSON re-encoded), so formatting differences don't count. A nil
// document is the empty ontology. Every list is sorted.
//
// A flow's reach is what its plan follows: the interfaces reached from the
// entry through static calls, emits, publish subscribers and declared
// dynamic targets; the configs those interfaces reference in CEL; the entry
// caller and the components providing those interfaces, with their ancestors;
// and the schemas those interfaces reference, transitively. A flow present
// and unchanged in both documents is affected when an added or modified
// entity lies in its reach in after, or a modified or removed one lies in its
// reach in before.
func ComputeImpact(before, after *Document) *Impact {
	b := newImpactSide(before)
	a := newImpactSide(after)
	imp := &Impact{FlowsAffected: []FlowImpact{}}
	sets := map[string]*ImpactSet{
		KindComponent: &imp.Components, KindInterface: &imp.Interfaces, KindLink: &imp.Links,
		KindSchema: &imp.Schemas, KindFlow: &imp.Flows, KindScenario: &imp.Scenarios,
		KindConfig: &imp.Configs, KindFixture: &imp.Fixtures,
	}
	changed := map[string]bool{} // "<kind>:<id>"
	for _, kind := range Kinds {
		set := sets[kind]
		set.Added, set.Removed, set.Modified, set.Cited = []string{}, []string{}, []string{}, []string{}
		bm, am := b.canon[kind], a.canon[kind]
		for id, bj := range bm {
			aj, ok := am[id]
			switch {
			case !ok:
				set.Removed = append(set.Removed, id)
			case sameJSON(aj, bj):
				continue
			case sameJSON(withoutCitations(aj), withoutCitations(bj)):
				// Only evidence moved: not a change to the system.
				set.Cited = append(set.Cited, id)
				continue
			case !sameJSON(aj, bj):
				set.Modified = append(set.Modified, id)
			default:
				continue
			}
			changed[kind+":"+id] = true
		}
		for id := range am {
			if _, ok := bm[id]; !ok {
				set.Added = append(set.Added, id)
				changed[kind+":"+id] = true
			}
		}
		sort.Strings(set.Added)
		sort.Strings(set.Removed)
		sort.Strings(set.Modified)
		sort.Strings(set.Cited)
	}
	if len(changed) == 0 {
		return imp
	}
	// Flows whose own definition changed are reported as flows, not as affected.
	for _, id := range sortedKeys(a.flows) {
		if changed[KindFlow+":"+id] {
			continue
		}
		if _, ok := b.flows[id]; !ok {
			continue
		}
		reasons := map[string]bool{}
		for _, side := range []*impactSide{a, b} {
			side.reach(id, func(key string) {
				if changed[key] {
					reasons[key] = true
				}
			})
		}
		if len(reasons) > 0 {
			imp.FlowsAffected = append(imp.FlowsAffected, FlowImpact{Flow: id, Reasons: sortedKeys(reasons), Basis: "static"})
		}
	}
	return imp
}

// impactSide is one document prepared for ComputeImpact: canonical entity
// JSON by kind and id, and the lookups reach needs. It never modifies the
// document it was built from.
type impactSide struct {
	*ReachIndex
	canon map[string]map[string][]byte // kind -> id -> encoded entity
}

func newImpactSide(d *Document) *impactSide {
	s := &impactSide{ReachIndex: NewReachIndex(d), canon: map[string]map[string][]byte{}}
	for _, k := range Kinds {
		s.canon[k] = map[string][]byte{}
	}
	if d == nil {
		return s
	}
	put := func(kind, id string, v any) {
		if _, dup := s.canon[kind][id]; dup {
			return // the first occurrence wins, as in NewIndex
		}
		b, err := json.Marshal(v)
		if err != nil {
			b = nil
		}
		s.canon[kind][id] = b
	}
	for _, c := range d.Components {
		put(KindComponent, c.ID, c)
	}
	for _, f := range d.Interfaces {
		f.Normalize() // f is a copy
		put(KindInterface, f.ID, f)
	}
	for _, l := range d.Links {
		put(KindLink, l.ID, l)
	}
	for _, sc := range d.Schemas {
		put(KindSchema, sc.ID, sc)
	}
	for i := range d.Flows {
		put(KindFlow, d.Flows[i].ID, d.Flows[i])
	}
	for _, sc := range d.Scenarios {
		put(KindScenario, sc.ID, sc)
	}
	for _, c := range d.Configs {
		put(KindConfig, c.ID, c)
	}
	for _, f := range d.Fixtures {
		put(KindFixture, f.ID, f)
	}
	return s
}

// ReachIndex holds the lookups that turn a flow, a scenario or a set of
// interfaces into the entities they reach: each component's parent, each
// interface's component, static call, emit and publish-subscriber targets,
// schemas and referenced configs, each schema's references, and each
// scenario's steps and fixtures. The first occurrence of a duplicated id
// wins, as in NewIndex. It never modifies the document it was built from.
type ReachIndex struct {
	parent    map[string]string     // component -> parent
	comp      map[string]string     // interface -> component
	next      map[string][]string   // interface -> interfaces it calls, emits or publishes to
	ifSch     map[string][]string   // interface -> schemas it references directly
	ifConf    map[string][]string   // interface -> configs its CEL references
	schSch    map[string][]string   // schema -> schemas it references
	flows     map[string]*FlowEntry // flow -> entry
	scenarios map[string]*Scenario  // scenario -> scenario
	extends   map[string][]string   // fixture -> fixtures it extends
}

// NewReachIndex builds the reach lookups of d. A nil d is the empty ontology.
func NewReachIndex(d *Document) *ReachIndex {
	s := &ReachIndex{parent: map[string]string{}, comp: map[string]string{}, next: map[string][]string{},
		ifSch: map[string][]string{}, ifConf: map[string][]string{}, schSch: map[string][]string{},
		flows: map[string]*FlowEntry{}, scenarios: map[string]*Scenario{}, extends: map[string][]string{}}
	if d == nil {
		return s
	}
	subs := subscribers(d.Interfaces)
	for _, c := range d.Components {
		if _, ok := s.parent[c.ID]; !ok {
			s.parent[c.ID] = c.Parent
		}
	}
	for _, f := range d.Interfaces {
		if _, ok := s.comp[f.ID]; ok {
			continue
		}
		f.Normalize() // f is a copy
		s.comp[f.ID] = f.Component
		calls, emits, publishes, _ := callTargets(&f, subs)
		s.next[f.ID] = append(append(calls, emits...), publishes...)
		if refs := interfaceConfigRefs(&f); len(refs) > 0 {
			s.ifConf[f.ID] = refs
		}
		refs := map[string]bool{}
		schemaRefsOf(f.Request, true, refs)
		schemaRefsOf(f.Response, true, refs)
		s.ifSch[f.ID] = sortedKeys(refs)
	}
	for _, sc := range d.Schemas {
		if _, ok := s.schSch[sc.ID]; ok {
			continue
		}
		refs := map[string]bool{}
		schemaRefsOf(sc.Schema, false, refs)
		s.schSch[sc.ID] = sortedKeys(refs)
	}
	for i := range d.Flows {
		f := &d.Flows[i]
		if _, ok := s.flows[f.ID]; !ok {
			s.flows[f.ID] = f.Entry
		}
	}
	for i := range d.Scenarios {
		sc := &d.Scenarios[i]
		if _, ok := s.scenarios[sc.ID]; !ok {
			s.scenarios[sc.ID] = sc
		}
	}
	for _, f := range d.Fixtures {
		if _, ok := s.extends[f.ID]; !ok {
			s.extends[f.ID] = f.Extends
		}
	}
	return s
}

// ScenarioReach calls fn once with "<kind>:<id>" for every entity a
// scenario's runs can statically reach: for a multi-step scenario the
// reach of every step (a step flow's entry, or a step interface with its
// caller), otherwise the reach of its flow; plus its fixtures and the
// fixtures they extend. It does nothing for a scenario this side lacks.
func (s *ReachIndex) ScenarioReach(scenario string, fn func(string)) {
	sc, ok := s.scenarios[scenario]
	if !ok {
		return
	}
	seen := map[string]bool{}
	once := func(k string) {
		if !seen[k] {
			seen[k] = true
			fn(k)
		}
	}
	if len(sc.Steps) == 0 {
		s.reach(sc.Flow, once)
	}
	for _, st := range sc.Steps {
		switch {
		case st.Flow != "":
			s.reach(st.Flow, once)
		case st.Interface != "":
			s.Expand(st.Caller, []string{st.Interface}, true, once)
		}
	}
	var fixture func(id string)
	fixture = func(id string) {
		k := KindFixture + ":" + id
		if seen[k] {
			return // also stops extends cycles, which Validate reports
		}
		once(k)
		for _, e := range s.extends[id] {
			fixture(e)
		}
	}
	for _, id := range sc.Fixtures {
		fixture(id)
	}
}

// FlowEntry returns the entry of a flow, or nil when the document lacks it.
func (s *ReachIndex) FlowEntry(flow string) *FlowEntry { return s.flows[flow] }

// reach calls fn with "<kind>:<id>" for every entity in the flow's static
// reach. It does nothing for a flow this side lacks.
func (s *ReachIndex) reach(flow string, fn func(string)) {
	entry, ok := s.flows[flow]
	if !ok || entry == nil {
		return
	}
	s.Expand(entry.Caller, []string{entry.Interface}, true, fn)
}

// StaticReach calls fn with "<kind>:<id>" for every entity in the flow's
// static reach: what ComputeImpact uses.
func (s *ReachIndex) StaticReach(flow string, fn func(string)) { s.reach(flow, fn) }

// Expand calls fn once with "<kind>:<id>" for every entity reached from the
// given interfaces: the interfaces themselves (unknown ones too, since a
// removed interface is a change), the caller and the components providing
// them with their ancestors, the configs their CEL references, and the
// schemas they reference, transitively. With follow, it also follows every
// static call, emit, publish subscriber and declared dynamic target.
func (s *ReachIndex) Expand(caller string, interfaces []string, follow bool, fn func(string)) {
	seenIf := map[string]bool{}
	seenComp := map[string]bool{}
	seenSch := map[string]bool{}
	seenConf := map[string]bool{}
	addComp := func(c string) {
		for c != "" && !seenComp[c] {
			seenComp[c] = true
			fn(KindComponent + ":" + c)
			c = s.parent[c]
		}
	}
	var schQueue []string
	addSchema := func(id string) {
		if !seenSch[id] {
			seenSch[id] = true
			fn(KindSchema + ":" + id)
			schQueue = append(schQueue, id)
		}
	}
	addComp(caller)
	queue := append([]string(nil), interfaces...)
	for len(queue) > 0 {
		id := queue[0]
		queue = queue[1:]
		if seenIf[id] {
			continue
		}
		seenIf[id] = true
		// An unknown target is still reported: if it was removed, it changed.
		fn(KindInterface + ":" + id)
		c, ok := s.comp[id]
		if !ok {
			continue
		}
		addComp(c)
		for _, sc := range s.ifSch[id] {
			addSchema(sc)
		}
		for _, c := range s.ifConf[id] {
			if !seenConf[c] {
				seenConf[c] = true
				fn(KindConfig + ":" + c)
			}
		}
		if follow {
			queue = append(queue, s.next[id]...)
		}
	}
	for len(schQueue) > 0 {
		id := schQueue[0]
		schQueue = schQueue[1:]
		for _, r := range s.schSch[id] {
			addSchema(r)
		}
	}
}

// schemaRefsOf collects the schema ids a schema value references: a bare id
// or "#/schemas/<id>" string (when top is true: an interface's request or
// response), and every "$ref" inside an inline schema.
func schemaRefsOf(v any, top bool, out map[string]bool) {
	switch t := v.(type) {
	case string:
		if top {
			out[strings.TrimPrefix(t, "#/schemas/")] = true
		}
	case map[string]any:
		for k, x := range t {
			if k == "$ref" {
				if r, ok := x.(string); ok {
					out[strings.TrimPrefix(r, "#/schemas/")] = true
					continue
				}
			}
			schemaRefsOf(x, false, out)
		}
	case []any:
		for _, x := range t {
			schemaRefsOf(x, false, out)
		}
	}
}

// sameJSON reports whether two encoded entities are equal as canonical JSON.
// Struct fields and maps already encode in a fixed order, so equal bytes are
// the common case; only raw JSON fields (inputs, returns) can hold the same
// object with its keys in another order, so unequal bytes are re-encoded.
func sameJSON(a, b []byte) bool {
	if bytes.Equal(a, b) {
		return true
	}
	return bytes.Equal(canonicalJSON(a), canonicalJSON(b))
}

// canonicalJSON re-encodes JSON with object keys sorted at every depth.
func canonicalJSON(b []byte) []byte {
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var x any
	if err := dec.Decode(&x); err != nil {
		return b
	}
	out, err := json.Marshal(x)
	if err != nil {
		return b
	}
	return out
}

// withoutCitations re-encodes an entity with every "source" and "sources"
// field removed, at any depth, so a change that only moves citations compares
// equal.
func withoutCitations(b []byte) []byte {
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return b
	}
	var strip func(any) any
	strip = func(v any) any {
		switch t := v.(type) {
		case map[string]any:
			out := make(map[string]any, len(t))
			for k, x := range t {
				if k == "source" || k == "sources" {
					continue
				}
				out[k] = strip(x)
			}
			return out
		case []any:
			out := make([]any, len(t))
			for i, x := range t {
				out[i] = strip(x)
			}
			return out
		}
		return v
	}
	out, err := json.Marshal(strip(v))
	if err != nil {
		return b
	}
	return out
}

// SameExceptCitations reports whether two entity specs differ only in their
// citations ("source" and "sources" fields), as after re-anchoring.
func SameExceptCitations(a, b []byte) bool {
	return sameJSON(withoutCitations(a), withoutCitations(b))
}

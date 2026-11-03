package model

import (
	"fmt"
	"sort"

	"github.com/xleelz/mosaic/internal/expr"
)

// ChoicePoint is a decision a scenario can override with choices[Key].
type ChoicePoint struct {
	Key       string   `json:"key"`
	Interface string   `json:"interface"`
	Name      string   `json:"name"`
	Options   []string `json:"options"`
	Default   string   `json:"default,omitempty"`
	Title     string   `json:"title,omitempty"`
}

// walkSteps visits every step, nested ones included: if branches, foreach
// and parallel bodies, parallel branches, choice options, on_error, on_late
// and on_item steps.
func walkSteps(steps []Step, fn func(Step)) {
	for _, s := range steps {
		fn(s)
		walkSteps(s.Then, fn)
		walkSteps(s.Else, fn)
		walkSteps(s.Steps, fn)
		for _, b := range s.Branches {
			walkSteps(b, fn)
		}
		for _, k := range sortedKeys(s.Options) {
			walkSteps(s.Options[k], fn)
		}
		if s.OnError != nil {
			walkSteps(s.OnError.Steps, fn)
		}
		walkSteps(s.OnLate, fn)
		walkSteps(s.OnItem, fn)
	}
}

// CanYield reports whether the interface's behavior has a yield step
// anywhere, nested ones included (§13.1 item 18).
func (i *Interface) CanYield() bool {
	found := false
	walkSteps(i.Behavior, func(s Step) { found = found || s.Yield != nil })
	return found
}

// ChoicePoints returns every choice point, keyed by "<interface>.<choice>".
func (x *Index) ChoicePoints() map[string]ChoicePoint {
	out := map[string]ChoicePoint{}
	for _, id := range sortedKeys(x.Interfaces) {
		f := x.Interfaces[id]
		walkSteps(f.Behavior, func(s Step) {
			if s.Choice == "" {
				return
			}
			key := f.ID + "." + s.Choice
			if _, dup := out[key]; dup {
				return
			}
			def := s.Default
			if def == "" && len(s.Options) == 1 {
				def = sortedKeys(s.Options)[0]
			}
			out[key] = ChoicePoint{Key: key, Interface: f.ID, Name: s.Choice, Options: sortedKeys(s.Options), Default: def, Title: s.Title}
		})
	}
	return out
}

// callTargets returns the interfaces a behavior can call or emit to, the
// subscribers its publish steps deliver to (subs maps a topic to its
// subscribers, as Index.Subscribers), and its dynamic call sites that list
// no targets. Steps inside parallel bodies and branches count.
func callTargets(f *Interface, subs map[string][]string) (calls, emits, publishes, dynamic []string) {
	i := 0
	walkSteps(f.Behavior, func(s Step) {
		i++
		if s.Call != "" {
			if _, isExpr := expr.ExprOf(s.Call); isExpr {
				if len(s.Targets) == 0 {
					dynamic = append(dynamic, fmt.Sprintf("%s step %d", f.ID, i))
				}
				calls = append(calls, s.Targets...)
			} else {
				calls = append(calls, s.Call)
			}
		}
		if s.Route != nil {
			calls = append(calls, s.Targets...) // §13.1 item 26
		}
		if s.Emit != "" {
			emits = append(emits, s.Emit)
		}
		if s.Publish != "" {
			publishes = append(publishes, subs[s.Publish]...)
		}
	})
	return calls, emits, publishes, dynamic
}

// StateInfo describes a stateful component reachable by a flow.
type StateInfo struct {
	Component string         `json:"component"`
	Initial   map[string]any `json:"initial,omitempty"`
	Schema    map[string]any `json:"schema,omitempty"`
}

// Plan is what a flow can reach: the controls a simulation can set.
type Plan struct {
	Flow       string        `json:"flow"`
	Entry      string        `json:"entry"`
	Caller     string        `json:"caller"`
	Interfaces []string      `json:"interfaces"`
	Components []string      `json:"components"`
	Choices    []ChoicePoint `json:"choices"`
	State      []StateInfo   `json:"state"`
	Faultable  []string      `json:"faultable"`
	Scenarios  []string      `json:"scenarios"`
	Dynamic    []string      `json:"dynamic,omitempty"`
	Unknown    []string      `json:"unknown,omitempty"` // entry or call targets that are not interfaces
}

// Plan follows a flow from its entry through every static call, emit,
// publish subscriber and declared dynamic target. Its scenarios are those
// grouped under the flow (Scenario.GroupFlow).
func (x *Index) Plan(flowID string) (*Plan, error) {
	f, ok := x.Flows[flowID]
	if !ok {
		return nil, fmt.Errorf("unknown flow %q", flowID)
	}
	if f.Entry == nil {
		return nil, fmt.Errorf("flow %q has no entry", flowID)
	}
	p := &Plan{Flow: f.ID, Entry: f.Entry.Interface, Caller: f.Entry.Caller,
		Interfaces: []string{}, Components: []string{}, Choices: []ChoicePoint{},
		State: []StateInfo{}, Faultable: []string{}, Scenarios: []string{}}
	seen := map[string]bool{}
	unknown := map[string]bool{}
	stores := map[string]bool{}
	queue := []string{f.Entry.Interface}
	comps := map[string]bool{f.Entry.Caller: true}
	for len(queue) > 0 {
		id := queue[0]
		queue = queue[1:]
		if seen[id] || unknown[id] {
			continue
		}
		iface, ok := x.Interfaces[id]
		if !ok {
			unknown[id] = true
			continue
		}
		seen[id] = true
		comps[iface.Component] = true
		if iface.Store != nil && len(iface.Behavior) == 0 {
			stores[iface.Component] = true
		}
		calls, emits, publishes, dynamic := callTargets(iface, x.Subscribers)
		p.Dynamic = append(p.Dynamic, dynamic...)
		queue = append(queue, calls...)
		queue = append(queue, emits...)
		queue = append(queue, publishes...)
	}
	p.Interfaces = sortedKeys(seen)
	p.Components = sortedKeys(comps)
	if len(unknown) > 0 {
		p.Unknown = sortedKeys(unknown)
	}
	points := x.ChoicePoints()
	for _, k := range sortedKeys(points) {
		if seen[points[k].Interface] {
			p.Choices = append(p.Choices, points[k])
		}
	}
	for _, c := range p.Components {
		comp, ok := x.Components[c]
		switch {
		case ok && comp.State != nil:
			p.State = append(p.State, StateInfo{Component: c, Initial: comp.State.Initial, Schema: comp.State.Schema})
		case stores[c]:
			// A datastore whose tables are reached through store operations
			// holds state a scenario can seed, even without a declared schema.
			p.State = append(p.State, StateInfo{Component: c})
		}
	}
	faultable := map[string]bool{}
	for _, id := range p.Interfaces {
		faultable[id] = true
		faultable[x.Interfaces[id].Component] = true
	}
	delete(faultable, f.Entry.Caller)
	p.Faultable = sortedKeys(faultable)
	for _, s := range x.Doc.Scenarios {
		if s.GroupFlow() == flowID {
			p.Scenarios = append(p.Scenarios, s.ID)
		}
	}
	sort.Strings(p.Scenarios)
	return p, nil
}

// GraphNode is a component on the architecture map.
type GraphNode struct {
	ID         string   `json:"id"`
	Name       string   `json:"name"`
	Kind       string   `json:"kind,omitempty"`
	Parent     string   `json:"parent,omitempty"`
	Layer      string   `json:"layer,omitempty"`
	Summary    string   `json:"summary,omitempty"`
	Interfaces []string `json:"interfaces"`
	Leaf       bool     `json:"leaf"`
	Stateful   bool     `json:"stateful"`
}

// GraphEdge is a relation between two components: an explicit link, or a
// call, emit or publish derived from behaviors (kind "calls", "emits" or
// "publishes"; a publish edge goes to each subscriber's component).
type GraphEdge struct {
	ID         string   `json:"id"`
	From       string   `json:"from"`
	To         string   `json:"to"`
	Kind       string   `json:"kind"`
	Label      string   `json:"label,omitempty"`
	Interfaces []string `json:"interfaces,omitempty"`
	Derived    bool     `json:"derived"`
}

// Graph is the architecture map of an ontology.
type Graph struct {
	Nodes []GraphNode `json:"nodes"`
	Edges []GraphEdge `json:"edges"`
}

// hasStore reports whether a component provides a store interface.
func (x *Index) hasStore(comp string) bool {
	for _, id := range x.ByComp[comp] {
		if x.Interfaces[id].Store != nil {
			return true
		}
	}
	return false
}

func (x *Index) componentOf(id string) (string, bool) {
	if _, ok := x.Components[id]; ok {
		return id, true
	}
	if f, ok := x.Interfaces[id]; ok {
		return f.Component, true
	}
	return "", false
}

// Graph builds the architecture map: every component, explicit links, and
// edges derived from behaviors' calls and emits and from flow entries.
func (x *Index) Graph() *Graph {
	g := &Graph{Nodes: []GraphNode{}, Edges: []GraphEdge{}}
	for _, c := range x.Doc.Components {
		name := c.Name
		if name == "" {
			name = c.ID
		}
		ifaces := append([]string{}, x.ByComp[c.ID]...)
		sort.Strings(ifaces)
		g.Nodes = append(g.Nodes, GraphNode{ID: c.ID, Name: name, Kind: c.Kind, Parent: c.Parent, Layer: c.Layer,
			Summary: c.Summary, Interfaces: ifaces, Leaf: len(x.Children[c.ID]) == 0, Stateful: c.State != nil || x.hasStore(c.ID)})
	}
	type key struct{ from, to, kind string }
	derived := map[key]map[string]bool{}
	addDerived := func(from, to, kind, iface string) {
		k := key{from, to, kind}
		if derived[k] == nil {
			derived[k] = map[string]bool{}
		}
		derived[k][iface] = true
	}
	for _, id := range sortedKeys(x.Interfaces) {
		f := x.Interfaces[id]
		calls, emits, publishes, _ := callTargets(f, x.Subscribers)
		for _, t := range calls {
			if to, ok := x.componentOf(t); ok {
				addDerived(f.Component, to, "calls", t)
			}
		}
		for _, t := range emits {
			if to, ok := x.componentOf(t); ok {
				addDerived(f.Component, to, "emits", t)
			}
		}
		for _, t := range publishes {
			if to, ok := x.componentOf(t); ok {
				addDerived(f.Component, to, "publishes", t)
			}
		}
	}
	for _, fl := range x.Doc.Flows {
		if fl.Entry == nil {
			continue
		}
		if to, ok := x.componentOf(fl.Entry.Interface); ok {
			if _, ok := x.Components[fl.Entry.Caller]; ok {
				addDerived(fl.Entry.Caller, to, "calls", fl.Entry.Interface)
			}
		}
	}
	keys := make([]key, 0, len(derived))
	for k := range derived {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(a, b int) bool {
		if keys[a].from != keys[b].from {
			return keys[a].from < keys[b].from
		}
		if keys[a].to != keys[b].to {
			return keys[a].to < keys[b].to
		}
		return keys[a].kind < keys[b].kind
	})
	for _, k := range keys {
		ifaces := sortedKeys(derived[k])
		label := ""
		if len(ifaces) == 1 {
			if f, ok := x.Interfaces[ifaces[0]]; ok {
				label = f.Name
			}
		} else {
			label = fmt.Sprintf("%d interfaces", len(ifaces))
		}
		g.Edges = append(g.Edges, GraphEdge{ID: fmt.Sprintf("%s:%s->%s", k.kind, k.from, k.to), From: k.from, To: k.to,
			Kind: k.kind, Label: label, Interfaces: ifaces, Derived: true})
	}
	for _, l := range x.Doc.Links {
		from, ok1 := x.componentOf(l.From)
		to, ok2 := x.componentOf(l.To)
		if !ok1 || !ok2 {
			continue
		}
		kind := l.Kind
		if kind == "" {
			kind = "depends_on"
		}
		e := GraphEdge{ID: "link:" + l.ID, From: from, To: to, Kind: kind, Label: l.Label}
		if _, ok := x.Interfaces[l.To]; ok {
			e.Interfaces = []string{l.To}
		}
		g.Edges = append(g.Edges, e)
	}
	return g
}

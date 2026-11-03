package model

import (
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
)

const impactBase = `
schema_version: 1
components:
  - {id: client}
  - {id: platform}
  - {id: gw, parent: platform}
  - {id: svc, parent: platform}
  - {id: worker}
  - {id: lonely}
interfaces:
  - component: gw
    name: in
    request: Req
    behavior:
      - {call: svc.read}
      - {call: "= 'worker.' + input.op", targets: [worker.run]}
  - component: svc
    name: read
    response: {type: object, properties: {item: {$ref: "#/schemas/Item"}}}
  - {component: worker, name: run}
  - {component: lonely, name: ping}
links:
  - {id: gw-svc, from: gw, to: svc}
schemas:
  - {id: Req, schema: {type: object}}
  - {id: Item, schema: {type: object, properties: {part: {$ref: Part}}}}
  - {id: Part, schema: {type: string}}
  - {id: Unused, schema: {type: string}}
flows:
  - {id: main, entry: {caller: client, interface: gw.in}}
  - {id: ping, entry: {caller: client, interface: lonely.ping}}
scenarios:
  - {id: main-ok, flow: main}
`

func parseImpactDoc(t testing.TB, src string) *Document {
	t.Helper()
	d, err := ParseDocument([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func emptySet() ImpactSet {
	return ImpactSet{Added: []string{}, Removed: []string{}, Modified: []string{}, Cited: []string{}}
}

func TestComputeImpact(t *testing.T) {
	cases := []struct {
		name    string
		old     string // replaced in impactBase
		new     string
		sets    map[string]ImpactSet
		flows   []FlowImpact
		reverse bool // compare edited -> base instead
	}{
		{name: "no change", flows: []FlowImpact{}},
		{name: "component modified", old: "{id: worker}", new: "{id: worker, summary: busy}",
			sets:  map[string]ImpactSet{"components": {Modified: []string{"worker"}}},
			flows: []FlowImpact{{Flow: "main", Reasons: []string{"component:worker"}, Basis: "static"}}}, // via a dynamic target
		{name: "parent modified", old: "{id: platform}", new: "{id: platform, layer: core}",
			sets:  map[string]ImpactSet{"components": {Modified: []string{"platform"}}},
			flows: []FlowImpact{{Flow: "main", Reasons: []string{"component:platform"}, Basis: "static"}}},
		{name: "schema modified transitively", old: "{id: Part, schema: {type: string}}", new: "{id: Part, schema: {type: integer}}",
			sets:  map[string]ImpactSet{"schemas": {Modified: []string{"Part"}}},
			flows: []FlowImpact{{Flow: "main", Reasons: []string{"schema:Part"}, Basis: "static"}}},
		{name: "unreached schema", old: "{id: Unused, schema: {type: string}}", new: "{id: Unused, schema: {type: number}}",
			sets: map[string]ImpactSet{"schemas": {Modified: []string{"Unused"}}}, flows: []FlowImpact{}},
		{name: "link and scenario do not affect flows", old: "{id: gw-svc, from: gw, to: svc}", new: "{id: gw-svc, from: gw, to: svc, label: reads}",
			sets: map[string]ImpactSet{"links": {Modified: []string{"gw-svc"}}}, flows: []FlowImpact{}},
		{name: "interface added", old: "  - {component: lonely, name: ping}\n", new: "  - {component: lonely, name: ping}\n  - {component: extra, name: x}\n",
			sets: map[string]ImpactSet{"interfaces": {Added: []string{"extra.x"}}}, flows: []FlowImpact{}},
		{name: "removed callee", old: "  - {component: worker, name: run}\n", new: "",
			sets:  map[string]ImpactSet{"interfaces": {Removed: []string{"worker.run"}}},
			flows: []FlowImpact{{Flow: "main", Reasons: []string{"interface:worker.run"}, Basis: "static"}}},
		{name: "flow modified is not affected", old: "{id: main, entry: {caller: client, interface: gw.in}}", new: "{id: main, name: Main, entry: {caller: client, interface: gw.in}}",
			sets: map[string]ImpactSet{"flows": {Modified: []string{"main"}}}, flows: []FlowImpact{}},
		{name: "flow removed", old: "  - {id: ping, entry: {caller: client, interface: lonely.ping}}\n", new: "",
			sets: map[string]ImpactSet{"flows": {Removed: []string{"ping"}}}, flows: []FlowImpact{}},
		{name: "scenario added", old: "  - {id: main-ok, flow: main}\n", new: "  - {id: main-ok, flow: main}\n  - {id: main-b, flow: main}\n",
			sets: map[string]ImpactSet{"scenarios": {Added: []string{"main-b"}}}, flows: []FlowImpact{}},
		{name: "caller modified", old: "{id: client}", new: "{id: client, kind: client}",
			sets:  map[string]ImpactSet{"components": {Modified: []string{"client"}}},
			flows: []FlowImpact{{Flow: "main", Reasons: []string{"component:client"}, Basis: "static"}, {Flow: "ping", Reasons: []string{"component:client"}, Basis: "static"}}},
		{name: "added callee and modified caller", reverse: true, old: "  - {component: worker, name: run}\n", new: "",
			sets:  map[string]ImpactSet{"interfaces": {Added: []string{"worker.run"}}},
			flows: []FlowImpact{{Flow: "main", Reasons: []string{"interface:worker.run"}, Basis: "static"}}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			edited := impactBase
			if c.old != "" {
				if !strings.Contains(edited, c.old) {
					t.Fatalf("fixture lacks %q", c.old)
				}
				edited = strings.Replace(edited, c.old, c.new, 1)
			}
			before, after := parseImpactDoc(t, impactBase), parseImpactDoc(t, edited)
			if c.reverse {
				before, after = after, before
			}
			got := ComputeImpact(before, after)
			want := map[string]ImpactSet{}
			for _, k := range Kinds {
				s := emptySet()
				if w, ok := c.sets[Plural(k)]; ok {
					if w.Added != nil {
						s.Added = w.Added
					}
					if w.Removed != nil {
						s.Removed = w.Removed
					}
					if w.Modified != nil {
						s.Modified = w.Modified
					}
				}
				want[Plural(k)] = s
			}
			gotSets := map[string]ImpactSet{"components": got.Components, "interfaces": got.Interfaces, "links": got.Links,
				"schemas": got.Schemas, "flows": got.Flows, "scenarios": got.Scenarios, "configs": got.Configs, "fixtures": got.Fixtures}
			if !reflect.DeepEqual(gotSets, want) {
				t.Errorf("sets:\n got %+v\nwant %+v", gotSets, want)
			}
			if !reflect.DeepEqual(got.FlowsAffected, c.flows) {
				t.Errorf("flows affected:\n got %+v\nwant %+v", got.FlowsAffected, c.flows)
			}
		})
	}
}

func TestComputeImpactNil(t *testing.T) {
	d := parseImpactDoc(t, impactBase)
	add := ComputeImpact(nil, d)
	if len(add.Components.Added) != 6 || len(add.Interfaces.Added) != 4 || len(add.Flows.Added) != 2 || len(add.FlowsAffected) != 0 {
		t.Errorf("nil before: %+v", add)
	}
	rm := ComputeImpact(d, nil)
	if len(rm.Schemas.Removed) != 4 || len(rm.Scenarios.Removed) != 1 || len(rm.Components.Added) != 0 {
		t.Errorf("nil after: %+v", rm)
	}
	none := ComputeImpact(nil, nil)
	if none.Components.Added == nil || none.FlowsAffected == nil {
		t.Errorf("nil lists should be empty, not null: %+v", none)
	}
}

func TestComputeImpactIgnoresFormatting(t *testing.T) {
	a := parseImpactDoc(t, impactBase+"  - {id: s2, flow: main, input: {b: 1, a: 2}}\n")
	b := parseImpactDoc(t, impactBase+"  - {id: s2, flow: main, input: {a: 2, b: 1}}\n")
	if got := ComputeImpact(a, b); len(got.Scenarios.Modified) != 0 {
		t.Errorf("key order counted as a change: %+v", got.Scenarios)
	}
	// Inputs are not modified.
	before := parseImpactDoc(t, impactBase)
	snap, _ := json.Marshal(before)
	ComputeImpact(before, parseImpactDoc(t, impactBase))
	if again, _ := json.Marshal(before); string(again) != string(snap) {
		t.Error("ComputeImpact modified its input")
	}
}

// loadLargeExample parses a large committed model: the frozen Cassandra model.
func loadLargeExample(t testing.TB) *Document {
	data, err := os.ReadFile("../../examples/cassandra/judge/cassandra-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	return parseImpactDoc(t, string(data))
}

func TestComputeImpactLargeDeterministic(t *testing.T) {
	before := loadLargeExample(t)
	after := loadLargeExample(t)
	// Touch a widely shared component: the parent of the first child.
	var target string
	for _, c := range after.Components {
		if c.Parent != "" {
			target = c.Parent
			break
		}
	}
	for i := range after.Components {
		if after.Components[i].ID == target {
			after.Components[i].Summary += " (changed)"
		}
	}
	first := ComputeImpact(before, after)
	if !reflect.DeepEqual(first.Components.Modified, []string{target}) {
		t.Fatalf("modified %v, want [%s]", first.Components.Modified, target)
	}
	for i := 0; i < 3; i++ {
		if again := ComputeImpact(before, after); !reflect.DeepEqual(first, again) {
			t.Fatal("ComputeImpact is not deterministic")
		}
	}
	t.Logf("%s: %d flows affected", target, len(first.FlowsAffected))
}

func BenchmarkComputeImpactLarge(b *testing.B) {
	before := loadLargeExample(b)
	after := loadLargeExample(b)
	for i := range after.Components {
		if after.Components[i].Parent == "" {
			after.Components[i].Summary += " (changed)"
		}
	}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		ComputeImpact(before, after)
	}
}

// TestImpactCitationOnly keeps re-anchored citations out of modified and out of
// affected flows.
func TestImpactCitationOnly(t *testing.T) {
	mk := func(line string, summary string) *Document {
		doc, err := ParseDocument([]byte(`
components:
  - {id: c, summary: "` + summary + `", sources: ["a.go:` + line + `"]}
interfaces:
  - {component: c, name: f, sources: ["a.go:` + line + `"], behavior: [{title: t, source: "a.go:` + line + `"}]}
flows:
  - {id: fl, entry: {caller: c, interface: c.f}}
`))
		if err != nil {
			t.Fatal(err)
		}
		return doc
	}
	imp := ComputeImpact(mk("10", "s"), mk("12", "s"))
	if len(imp.Components.Modified) != 0 || len(imp.Interfaces.Modified) != 0 || len(imp.FlowsAffected) != 0 {
		t.Fatalf("citation-only change counted as modified: %+v", imp)
	}
	if len(imp.Components.Cited) != 1 || len(imp.Interfaces.Cited) != 1 {
		t.Fatalf("cited = %v %v", imp.Components.Cited, imp.Interfaces.Cited)
	}
	imp = ComputeImpact(mk("10", "s"), mk("12", "changed"))
	if len(imp.Components.Modified) != 1 || len(imp.FlowsAffected) != 1 {
		t.Fatalf("real change missed: %+v", imp)
	}
}

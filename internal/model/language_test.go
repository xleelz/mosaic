package model

import (
	"encoding/json"
	"os"
	"reflect"
	"sort"
	"strings"
	"testing"
)

// langBase is a valid document that uses every §11 addition.
const langBase = `
schema_version: 1
components:
  - {id: client}
  - id: cluster
  - id: node
    parent: cluster
    capacity: {concurrency: 2, queue_limit: 0, queue_timeout_ms: 50}
  - {id: storage, parent: node, state: {schema: {type: object}, initial: {rows: {}}}}
  - {id: gossip, parent: node}
  - {id: hints}
configs:
  - {id: write-timeout-ms, type: integer, value: 2000, default: 1000, summary: write timeout, description: d, sources: ["conf/c.yaml:10"], attributes: {unit: ms}, tags: [timeouts]}
  - {id: hints-enabled, type: boolean, value: true}
  - {id: untyped}
fixtures:
  - id: base
    name: Base
    summary: the schema
    state: {storage: {rows: {k1: {v: 1}}}}
    config: {hints-enabled: false}
  - id: three-nodes
    topology: {node: [n1, n2, n3]}
    clock: {epoch: "2026-10-30T00:00:00Z"}
    config: {write-timeout-ms: 500}
    state: {"storage@n2": {rows: {k2: {v: 2}}}}
    extends: [base]
    attributes: {boundary: true}
interfaces:
  - component: node
    name: write
    latency_ms: "= 1 + size(input)"
    behavior:
      - parallel: "= ['n1', 'n2', 'n3']"
        as: replica
        index: i
        steps:
          - {call: storage.apply, input: {k: "= vars.replica"}, on: "= vars.replica", deadline_ms: 100, timeout_ms: 50}
        join: {need: 2}
        stagger_ms: 5
        timeout_ms: 2000
        as_result: acks
        on_insufficient: {code: unavailable, status: 503}
      - branches:
          - [{call: storage.apply, on: n1}]
          - [{publish: node.changed, input: {k: 1}, delivery: sync, on_error: propagate}]
        join: {need: any}
      - {parallel: [1, 2], steps: [{wait: 1}], join: {need: "= 1"}, stagger_ms: "= 2", timeout_ms: "= 10 * 2"}
      - {call: storage.apply, timeout_ms: "= 100", deadline_ms: "= 50"}
      - {emit: hints.store, after_ms: "= 1", every_ms: "= 100", count: "= 2"}
      - {publish: node.changed, input: {k: 2}, after_ms: 10, every_ms: 1000, count: 3}
      - {emit: hints.store, on: n2, after_ms: 5}
      - {return: "= vars.acks"}
  - {component: storage, name: apply}
  - {component: node, name: changed, kind: event}
  - {component: gossip, name: on-change, subscribe: [node.changed]}
  - {component: hints, name: on-change, subscribe: [node.changed, cluster-events]}
  - {component: hints, name: store}
  - {component: hints, name: replay}
flows:
  - id: write
    entry: {caller: client, interface: node.write, on: n2, deadline_ms: 3000, repeat: {count: 2, interval_ms: 10, initial_delay_ms: 5}}
  - id: replay
    entry: {caller: client, interface: hints.replay}
scenarios:
  - id: single
    flow: write
    fixtures: [three-nodes]
    topology: {gossip: [g1]}
    clock: {epoch_ms: 1000}
    config: {untyped: {a: 1}}
    state: {"storage@n3": {rows: {}}}
    faults: [{target: storage, type: unavailable, instance: n2}]
    mocks:
      - {interface: storage.apply, instance: n1, when: "input.k == 'n1'", return: {ok: true}, calls: [1]}
      - {interface: hints.store, fail: {code: down, status: 503}}
    expect: ["result.ok"]
  - id: multi
    fixtures: [three-nodes]
    steps:
      - {flow: write, input: {k: 1}, as: first, choices: {}, on: n1}
      - {flow: replay, at_ms: 10, deadline_ms: 100}
      - {interface: hints.replay, caller: client, input: {id: "= steps.first.result.value"}, as: third}
    expect: ["result.ok"]
`

func langDoc(t *testing.T) *Document {
	t.Helper()
	d, err := ParseDocument([]byte(langBase))
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func TestLanguageDecodes(t *testing.T) {
	d := langDoc(t)
	x := NewIndex(d)
	node := x.Components["node"]
	if c := node.Capacity; c == nil || c.Concurrency != 2 || c.QueueLimit == nil || *c.QueueLimit != 0 || c.QueueTimeoutMS != 50 {
		t.Errorf("capacity %+v", node.Capacity)
	}
	w := x.Interfaces["node.write"]
	if w.LatencyMS == nil || w.LatencyMS.Expr != " 1 + size(input)" {
		t.Errorf("latency %+v", w.LatencyMS)
	}
	p := w.Behavior[0]
	if !p.IsParallel() || p.As != "replica" || p.Index != "i" || len(p.Steps) != 1 || p.StaggerMS != Int(5) || p.TimeoutMS != Int(2000) ||
		p.AsResult != "acks" || p.OnInsufficient == nil || p.OnInsufficient.Code != "unavailable" || p.Join == nil {
		t.Errorf("parallel %+v", p)
	}
	if got := p.Actions(); !reflect.DeepEqual(got, []string{"parallel"}) {
		t.Errorf("actions %v", got)
	}
	if c := p.Steps[0]; c.On != "= vars.replica" || c.DeadlineMS != Int(100) {
		t.Errorf("call %+v", c)
	}
	b := w.Behavior[1]
	if len(b.Branches) != 2 || b.Join.Need != "any" || b.Branches[1][0].Delivery != DeliverySync {
		t.Errorf("branches %+v", b)
	}
	if st := w.Behavior[2]; st.StaggerMS != (IntOrExpr{Expr: " 2"}) || st.TimeoutMS.Expr != " 10 * 2" || !st.TimeoutMS.IsExpr() || st.TimeoutMS.String() != "= 10 * 2" {
		t.Errorf("templates %+v", st)
	}
	if e := w.Behavior[4]; e.AfterMS.Expr != " 1" || e.EveryMS.Expr != " 100" || e.Count.Expr != " 2" {
		t.Errorf("timer templates %+v", e)
	}
	pub := w.Behavior[5]
	if pub.Publish != "node.changed" || pub.AfterMS != Int(10) || pub.EveryMS != Int(1000) || pub.Count != Int(3) ||
		!reflect.DeepEqual(pub.Actions(), []string{"publish"}) {
		t.Errorf("publish %+v", pub)
	}
	if got := x.Subscribers["node.changed"]; !reflect.DeepEqual(got, []string{"gossip.on-change", "hints.on-change"}) {
		t.Errorf("subscribers %v", got)
	}
	e := x.Flows["write"].Entry
	if e.On != "n2" || e.DeadlineMS != Int(3000) || e.Repeat.InitialDelayMS != 5 {
		t.Errorf("entry %+v", e)
	}
	if c := x.Configs["write-timeout-ms"]; c == nil || c.Type != "integer" || c.Summary == "" || len(c.Sources) != 1 || c.Tags[0] != "timeouts" {
		t.Errorf("config %+v", c)
	}
	f := x.Fixtures["three-nodes"]
	if f == nil || !reflect.DeepEqual(f.Topology["node"], []string{"n1", "n2", "n3"}) || f.Clock.Epoch == "" || f.Extends[0] != "base" || f.Attributes["boundary"] != true {
		t.Errorf("fixture %+v", f)
	}
	s := x.Scenarios["single"]
	if s.Faults[0].Instance != "n2" || len(s.Mocks) != 2 || s.Mocks[0].Instance != "n1" || s.Clock.EpochMS != 1000 {
		t.Errorf("scenario %+v", s)
	}
	m := x.Scenarios["multi"]
	if m.Flow != "" || m.GroupFlow() != "write" || len(m.Steps) != 3 || *m.Steps[1].AtMS != 10 || m.Steps[0].On != "n1" ||
		m.Steps[2].Caller != "client" || m.Steps[2].As != "third" {
		t.Errorf("multi %+v", m)
	}
}

// TestLanguageRoundTrip encodes the document as JSON and as entities, and
// checks that both decode back to the same document.
func TestLanguageRoundTrip(t *testing.T) {
	d := langDoc(t)
	js, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	d2, err := ParseDocument(js)
	if err != nil {
		t.Fatalf("re-parse: %v\n%s", err, js)
	}
	js2, _ := json.Marshal(d2)
	if string(js) != string(js2) {
		t.Errorf("JSON round trip differs:\n%s\n%s", js, js2)
	}
	for _, want := range []string{`"latency_ms":"= 1 + size(input)"`, `"queue_limit":0`, `"configs":[`, `"fixtures":[`,
		`"branches":[[`, `"timeout_ms":"= 10 * 2"`, `"count":"= 2"`, `"stagger_ms":5`, `"join":{"need":"any"}`, `"initial_delay_ms":5`, `"at_ms":10`, `"subscribe":["node.changed"]`} {
		if !strings.Contains(string(js), want) {
			t.Errorf("encoding lacks %s", want)
		}
	}
	ents, err := d.Entities()
	if err != nil {
		t.Fatal(err)
	}
	kinds := map[string]int{}
	for _, e := range ents {
		kinds[e.Kind]++
	}
	if kinds[KindConfig] != 3 || kinds[KindFixture] != 2 {
		t.Errorf("entity kinds %v", kinds)
	}
	d3, issues := FromEntities(ents)
	if len(issues) > 0 {
		t.Fatalf("from entities: %+v", issues)
	}
	// FromEntities sorts by kind and id, so compare the entities again.
	ents3, _ := d3.Entities()
	sortEnts := func(es []Entity) {
		sort.Slice(es, func(a, b int) bool { return es[a].Kind+":"+es[a].ID < es[b].Kind+":"+es[b].ID })
	}
	sortEnts(ents)
	sortEnts(ents3)
	if !reflect.DeepEqual(ents, ents3) {
		t.Errorf("entity round trip differs")
	}
	for _, k := range []string{"config", "configs", "fixture", "fixtures"} {
		if _, ok := KindOf(k); !ok {
			t.Errorf("KindOf(%q)", k)
		}
	}
	if Plural(KindConfig) != "configs" || Plural(KindFixture) != "fixtures" {
		t.Error("plurals")
	}
}

func TestLanguageStrictDecoding(t *testing.T) {
	for kind, spec := range map[string]string{
		KindConfig:   `{"id": "x", "valu": 1}`,
		KindFixture:  `{"id": "x", "topolgy": {}}`,
		KindScenario: `{"id": "x", "mocks": [{"interface": "a.b", "retrun": 1}]}`,
	} {
		if _, _, err := DecodeEntity(kind, []byte(spec)); err == nil {
			t.Errorf("%s %s: expected an error", kind, spec)
		}
	}
	bad := []string{
		`{"id": "x", "steps": [{"flow": "f", "at": 1}]}`,
		`{"id": "x", "clock": {"epoch_s": 1}}`,
	}
	for _, spec := range bad {
		if _, _, err := DecodeEntity(KindScenario, []byte(spec)); err == nil {
			t.Errorf("%s: expected an error", spec)
		}
	}
	if _, _, err := DecodeEntity(KindComponent, []byte(`{"id": "x", "capacity": {"concurrency": 1, "slots": 2}}`)); err == nil {
		t.Error("capacity: expected an error")
	}
	var s []Step
	if err := Decode([]byte(`[{"parallel": [1], "steps": [], "join": {"needs": 1}}]`), &s); err == nil {
		t.Error("join: expected an error")
	}
	for _, bad := range []string{`{"timeout_ms": "10"}`, `{"count": true}`, `{"after_ms": "="}`} {
		var st Step
		if err := Decode([]byte(bad), &st); err == nil {
			t.Errorf("%s: expected an error", bad)
		}
	}
	if _, err := ParseDocument([]byte(`{"interfaces": [{"component": "a", "name": "b", "latency_ms": "10"}]}`)); err == nil {
		t.Error("latency string without '=': expected an error")
	}
}

func TestLanguageValidates(t *testing.T) {
	issues := Validate(langDoc(t))
	if len(issues) > 0 {
		t.Fatalf("unexpected issues:\n%s", dump(issues))
	}
}

func runLangCases(t *testing.T, cases []vcase) {
	t.Helper()
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			d := langDoc(t)
			c.mutate(t, d)
			issues := Validate(d)
			sev := c.severity
			if sev == "" {
				sev = SeverityError
			}
			for _, is := range issues {
				if is.Path == c.path && strings.Contains(is.Message, c.msg) && is.Severity == sev {
					return
				}
			}
			t.Errorf("no %s at %q containing %q; got:\n%s", sev, c.path, c.msg, dump(issues))
		})
	}
}

func iface(d *Document, id string) *Interface {
	for i := range d.Interfaces {
		if d.Interfaces[i].ID == id {
			return &d.Interfaces[i]
		}
	}
	return nil
}

func scen(d *Document, id string) *Scenario {
	for i := range d.Scenarios {
		if d.Scenarios[i].ID == id {
			return &d.Scenarios[i]
		}
	}
	return nil
}

func TestLanguageValidationCases(t *testing.T) {
	setBehavior := func(js string) func(t *testing.T, d *Document) {
		return func(t *testing.T, d *Document) { iface(d, "node.write").Behavior = steps(t, js) }
	}
	const w = "interfaces[node.write].behavior[0]"
	ptr := func(n int) *int { return &n }
	runLangCases(t, []vcase{
		// parallel
		{"parallel and branches", setBehavior(`[{"parallel": [1], "branches": [[{"wait": 1}]], "steps": [{"wait": 1}]}]`), w, "alternatives", ""},
		{"parallel without steps", setBehavior(`[{"parallel": [1]}]`), w + ".steps", "needs steps", ""},
		{"branches with steps", setBehavior(`[{"branches": [[{"wait": 1}]], "steps": [{"wait": 1}]}]`), w + ".steps", "not branches", ""},
		{"empty branches", setBehavior(`[{"branches": []}]`), w + ".branches", "at least one branch", ""},
		{"bad parallel value", setBehavior(`[{"parallel": 3, "steps": [{"wait": 1}]}]`), w + ".parallel", "list, a map or an expression", ""},
		{"bad parallel expr", setBehavior(`[{"parallel": "= [", "steps": [{"wait": 1}]}]`), w + ".parallel", "invalid expression", ""},
		{"negative need", setBehavior(`[{"parallel": [1], "steps": [{"wait": 1}], "join": {"need": -1}}]`), w + ".join.need", "must not be negative", ""},
		{"need word", setBehavior(`[{"parallel": [1], "steps": [{"wait": 1}], "join": {"need": "most"}}]`), w + ".join.need", "whole number", ""},
		{"need over branches", setBehavior(`[{"branches": [[{"wait": 1}]], "join": {"need": 2}}]`), w + ".join.need", "always fails", SeverityWarning},
		{"negative stagger", setBehavior(`[{"parallel": [1], "steps": [{"wait": 1}], "stagger_ms": -1}]`), w + ".stagger_ms", "negative", ""},
		{"bad as_result", setBehavior(`[{"parallel": [1], "steps": [{"wait": 1}], "as_result": "1x"}]`), w + ".as_result", "invalid variable", ""},
		{"same as and index", setBehavior(`[{"parallel": [1], "steps": [{"wait": 1}], "as": "i", "index": "i"}]`), w + ".index", "different", ""},
		{"insufficient without code", setBehavior(`[{"parallel": [1], "steps": [{"wait": 1}], "on_insufficient": {"status": 503}}]`), w + ".on_insufficient.code", "required", ""},
		{"join on call", setBehavior(`[{"call": "storage.apply", "join": {"need": 1}}]`), w, "go with parallel", ""},
		{"break in branch", setBehavior(`[{"foreach": [1], "steps": [{"branches": [[{"break": true}]]}]}]`), w + ".steps[0].branches[0][0].break", "inside the steps of a foreach", ""},
		{"bad call in branch", setBehavior(`[{"branches": [[{"call": "nope.x"}]]}]`), w + ".branches[0][0].call", "unknown interface", ""},
		// publish and timers
		{"bad delivery", setBehavior(`[{"publish": "node.changed", "delivery": "later"}]`), w + ".delivery", "delivery is one of", ""},
		{"delivery on emit", setBehavior(`[{"emit": "hints.store", "delivery": "sync"}]`), w + ".delivery", "goes with publish", ""},
		{"no subscriber", setBehavior(`[{"publish": "nobody-listens"}]`), w + ".publish", "no interface subscribes", SeverityWarning},
		{"bad topic", setBehavior(`[{"publish": "Not A Topic"}]`), w + ".publish", "invalid topic", ""},
		{"count without every", setBehavior(`[{"emit": "hints.store", "count": 2}]`), w + ".count", "goes with every_ms", ""},
		{"every without count", setBehavior(`[{"publish": "node.changed", "every_ms": 10}]`), w + ".count", "periodic timer", ""},
		{"timer on call", setBehavior(`[{"call": "storage.apply", "after_ms": 10}]`), w, "go with emit or publish", ""},
		{"on on wait", setBehavior(`[{"wait": 1, "on": "n1"}]`), w + ".on", "goes with call, emit or publish", ""},
		{"bad on", setBehavior(`[{"call": "storage.apply", "on": "N 1"}]`), w + ".on", "invalid instance", ""},
		{"deadline on emit", setBehavior(`[{"emit": "hints.store", "deadline_ms": 5}]`), w + ".deadline_ms", "goes with call", ""},
		{"bad timeout template", setBehavior(`[{"call": "storage.apply", "timeout_ms": "= )"}]`), w + ".timeout_ms", "invalid expression", ""},
		{"bad count template", setBehavior(`[{"emit": "hints.store", "every_ms": 5, "count": "= ("}]`), w + ".count", "invalid expression", ""},
		{"template timeout on wait", setBehavior(`[{"wait": 1, "timeout_ms": "= 5"}]`), w, "go with call", ""},
		{"negative deadline", setBehavior(`[{"call": "storage.apply", "deadline_ms": -5}]`), w + ".deadline_ms", "negative", ""},
		{"on_error mode on publish", setBehavior(`[{"publish": "node.changed", "on_error": "ignore"}]`), w + ".on_error", "propagate, continue", ""},
		// CEL text checks
		{"unknown config", setBehavior(`[{"return": "= config.nope + config['write-timeout-ms']"}]`), w + ".return", `unknown config "nope"`, SeverityWarning},
		{"wall clock literal", setBehavior(`[{"if": "now > 1730000000000", "then": [{"wait": 1}]}]`), w + ".if", "wall-clock", SeverityWarning},
		// interfaces and components
		{"bad latency expr", func(t *testing.T, d *Document) { iface(d, "node.write").LatencyMS = &Latency{Expr: "1 +"} }, "interfaces[node.write].latency_ms", "invalid expression", ""},
		{"bad subscribe", func(t *testing.T, d *Document) { iface(d, "hints.store").Subscribe = []string{"a..b"} }, "interfaces[hints.store].subscribe[0]", "invalid topic", ""},
		{"zero concurrency", func(t *testing.T, d *Document) { d.Components[2].Capacity = &CapacitySpec{} }, "components[node].capacity.concurrency", "at least 1", ""},
		{"negative queue", func(t *testing.T, d *Document) {
			d.Components[2].Capacity = &CapacitySpec{Concurrency: 1, QueueLimit: ptr(-1)}
		}, "components[node].capacity.queue_limit", "negative", ""},
		// flows
		{"entry deadline", func(t *testing.T, d *Document) { d.Flows[0].Entry.DeadlineMS = Int(-1) }, "flows[write].entry.deadline_ms", "negative", ""},
		{"initial delay", func(t *testing.T, d *Document) { d.Flows[0].Entry.Repeat.InitialDelayMS = -1 }, "flows[write].entry.repeat.initial_delay_ms", "negative", ""},
		{"entry on", func(t *testing.T, d *Document) { d.Flows[0].Entry.On = "= )" }, "flows[write].entry.on", "invalid expression", ""},
		// configs
		{"config type", func(t *testing.T, d *Document) { d.Configs[0].Type = "int" }, "configs[write-timeout-ms].type", "type is one of", ""},
		{"config value type", func(t *testing.T, d *Document) { d.Configs[1].Value = "yes" }, "configs[hints-enabled].value", "not of type boolean", SeverityWarning},
		{"config duplicate", func(t *testing.T, d *Document) { d.Configs = append(d.Configs, Config{ID: "untyped"}) }, "configs[untyped]", "duplicate config", ""},
		{"config id", func(t *testing.T, d *Document) { d.Configs[2].ID = "Bad.Id" }, "configs[Bad.Id].id", "invalid id", ""},
		// fixtures
		{"unknown extends", func(t *testing.T, d *Document) { d.Fixtures[1].Extends = []string{"nope"} }, "fixtures[three-nodes].extends[0]", "unknown fixture", ""},
		{"extends cycle", func(t *testing.T, d *Document) { d.Fixtures[0].Extends = []string{"three-nodes"} }, "fixtures[base].extends", "cycle", ""},
		{"topology component", func(t *testing.T, d *Document) { d.Fixtures[1].Topology["nope"] = []string{"x"} }, "fixtures[three-nodes].topology.nope", "unknown component", ""},
		{"topology empty", func(t *testing.T, d *Document) { d.Fixtures[1].Topology["node"] = nil }, "fixtures[three-nodes].topology.node", "at least one instance", ""},
		{"topology duplicate", func(t *testing.T, d *Document) { d.Fixtures[1].Topology["node"] = []string{"n1", "n1"} }, "fixtures[three-nodes].topology.node[1]", "listed twice", ""},
		{"topology name", func(t *testing.T, d *Document) { d.Fixtures[1].Topology["node"] = []string{"N1"} }, "fixtures[three-nodes].topology.node[0]", "invalid instance", ""},
		{"clock both", func(t *testing.T, d *Document) { d.Fixtures[1].Clock.EpochMS = 5 }, "fixtures[three-nodes].clock", "not both", ""},
		{"clock epoch", func(t *testing.T, d *Document) { d.Fixtures[1].Clock.Epoch = "yesterday" }, "fixtures[three-nodes].clock.epoch", "RFC 3339", ""},
		{"fixture config", func(t *testing.T, d *Document) { d.Fixtures[0].Config["nope"] = 1 }, "fixtures[base].config.nope", "unknown config", ""},
		{"fixture state", func(t *testing.T, d *Document) { d.Fixtures[0].State["nope@n1"] = map[string]any{} }, "fixtures[base].state.nope@n1", "unknown component", ""},
		{"fixture state instance", func(t *testing.T, d *Document) { d.Fixtures[0].State["storage@"] = map[string]any{} }, "fixtures[base].state.storage@", "invalid instance", ""},
		// scenarios
		{"unknown fixture", func(t *testing.T, d *Document) { scen(d, "single").Fixtures = []string{"nope"} }, "scenarios[single].fixtures[0]", "unknown fixture", ""},
		{"scenario topology", func(t *testing.T, d *Document) { scen(d, "single").Topology = map[string][]string{"nope": {"a"}} }, "scenarios[single].topology.nope", "unknown component", ""},
		{"state instance not in topology", func(t *testing.T, d *Document) {
			scen(d, "single").State["storage@n9"] = map[string]any{}
		}, "scenarios[single].state.storage@n9", "not one of node's instances", SeverityWarning},
		{"state instance without group", func(t *testing.T, d *Document) {
			scen(d, "single").State["hints@h1"] = map[string]any{}
		}, "scenarios[single].state.hints@h1", "no instances", SeverityWarning},
		{"fault instance", func(t *testing.T, d *Document) { scen(d, "single").Faults[0].Instance = "n7" }, "scenarios[single].faults[0].instance", "not one of node's instances", SeverityWarning},
		{"fault instance name", func(t *testing.T, d *Document) { scen(d, "single").Faults[0].Instance = "N7" }, "scenarios[single].faults[0].instance", "invalid instance", ""},
		{"flow required without steps", func(t *testing.T, d *Document) { scen(d, "single").Flow = "" }, "scenarios[single].flow", "unknown flow", ""},
		{"unknown grouping flow", func(t *testing.T, d *Document) { scen(d, "multi").Flow = "nope" }, "scenarios[multi].flow", "unknown flow", ""},
		{"input beside steps", func(t *testing.T, d *Document) { scen(d, "multi").Input = json.RawMessage(`{}`) }, "scenarios[multi].input", "on each step", ""},
		{"step flow", func(t *testing.T, d *Document) { scen(d, "multi").Steps[0].Flow = "nope" }, "scenarios[multi].steps[0].flow", "unknown flow", ""},
		{"step both", func(t *testing.T, d *Document) { scen(d, "multi").Steps[0].Interface = "hints.replay" }, "scenarios[multi].steps[0]", "not both", ""},
		{"step neither", func(t *testing.T, d *Document) { scen(d, "multi").Steps[0].Flow = "" }, "scenarios[multi].steps[0]", "names a flow or an interface", ""},
		{"step interface", func(t *testing.T, d *Document) { scen(d, "multi").Steps[2].Interface = "nope.x" }, "scenarios[multi].steps[2].interface", "unknown interface", ""},
		{"step caller missing", func(t *testing.T, d *Document) { scen(d, "multi").Steps[2].Caller = "" }, "scenarios[multi].steps[2].caller", "needs a caller", ""},
		{"step caller unknown", func(t *testing.T, d *Document) { scen(d, "multi").Steps[2].Caller = "nope" }, "scenarios[multi].steps[2].caller", "unknown component", ""},
		{"step caller with flow", func(t *testing.T, d *Document) { scen(d, "multi").Steps[0].Caller = "client" }, "scenarios[multi].steps[0].caller", "goes with interface", ""},
		{"step choices", func(t *testing.T, d *Document) {
			scen(d, "multi").Steps[0].Choices = map[string]Choice{"x.y": ChoiceOf("z")}
		}, "scenarios[multi].steps[0].choices.x.y", "unknown choice point", ""},
		{"step on", func(t *testing.T, d *Document) { scen(d, "multi").Steps[1].On = "n9" }, "scenarios[multi].steps[1].on", "no instances", SeverityWarning},
		{"step on not in group", func(t *testing.T, d *Document) { scen(d, "multi").Steps[0].On = "n9" }, "scenarios[multi].steps[0].on", "not one of node's instances", SeverityWarning},
		{"step name twice", func(t *testing.T, d *Document) { scen(d, "multi").Steps[2].As = "first" }, "scenarios[multi].steps[2].as", "used twice", ""},
		{"step input json", func(t *testing.T, d *Document) { scen(d, "multi").Steps[0].Input = json.RawMessage(`{`) }, "scenarios[multi].steps[0].input", "invalid JSON", ""},
		{"step at_ms", func(t *testing.T, d *Document) { n := -1.0; scen(d, "multi").Steps[1].AtMS = &n }, "scenarios[multi].steps[1].at_ms", "negative", ""},
		{"mock interface", func(t *testing.T, d *Document) { scen(d, "single").Mocks[0].Interface = "nope.x" }, "scenarios[single].mocks[0].interface", "unknown interface", ""},
		{"mock both", func(t *testing.T, d *Document) { scen(d, "single").Mocks[0].Fail = json.RawMessage(`{"code": "x"}`) }, "scenarios[single].mocks[0]", "not both", ""},
		{"mock neither", func(t *testing.T, d *Document) { scen(d, "single").Mocks[1].Fail = nil }, "scenarios[single].mocks[1]", "needs return or fail", ""},
		{"mock fail code", func(t *testing.T, d *Document) { scen(d, "single").Mocks[1].Fail = json.RawMessage(`{"status": 1}`) }, "scenarios[single].mocks[1].fail", "needs an object with a code", ""},
		{"mock when", func(t *testing.T, d *Document) { scen(d, "single").Mocks[0].When = "input.k ==" }, "scenarios[single].mocks[0].when", "invalid expression", ""},
		{"mock calls", func(t *testing.T, d *Document) { scen(d, "single").Mocks[0].Calls = []int{0} }, "scenarios[single].mocks[0].calls", "start at 1", ""},
		{"mock instance", func(t *testing.T, d *Document) { scen(d, "single").Mocks[0].Instance = "n8" }, "scenarios[single].mocks[0].instance", "not one of node's instances", SeverityWarning},
		{"scenario config", func(t *testing.T, d *Document) { scen(d, "single").Config["nope"] = 1 }, "scenarios[single].config.nope", "unknown config", ""},
	})
}

func TestLanguagePlanAndGraph(t *testing.T) {
	x := NewIndex(langDoc(t))
	p, err := x.Plan("write")
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"gossip.on-change", "hints.on-change", "hints.store", "node.write", "storage.apply"}
	if !reflect.DeepEqual(p.Interfaces, want) {
		t.Errorf("plan interfaces %v, want %v", p.Interfaces, want)
	}
	if !reflect.DeepEqual(p.Scenarios, []string{"multi", "single"}) {
		t.Errorf("plan scenarios %v", p.Scenarios)
	}
	edges := map[string]bool{}
	for _, e := range x.Graph().Edges {
		edges[e.ID] = true
	}
	for _, id := range []string{"calls:node->storage", "publishes:node->gossip", "publishes:node->hints", "emits:node->hints"} {
		if !edges[id] {
			t.Errorf("graph lacks edge %s; has %v", id, edges)
		}
	}
	pts := x.ChoicePoints()
	if len(pts) != 0 {
		t.Errorf("choice points %v", pts)
	}
}

func TestLanguageChoiceInsideParallel(t *testing.T) {
	d := langDoc(t)
	iface(d, "node.write").Behavior = steps(t, `[{"branches": [[{"choice": "pick", "default": "a", "options": {"a": [], "b": []}}]]}]`)
	scen(d, "single").Choices = map[string]Choice{"node.write.pick": ChoiceOf("b")}
	if issues := Validate(d); len(issues) > 0 {
		t.Fatalf("issues:\n%s", dump(issues))
	}
}

func reachOf(fn func(func(string))) []string {
	var out []string
	fn(func(k string) { out = append(out, k) })
	sort.Strings(out)
	return out
}

func TestLanguageReach(t *testing.T) {
	d := langDoc(t)
	// A config referenced by a parallel branch's call input.
	iface(d, "storage.apply").Behavior = steps(t, `[{"return": "= config['write-timeout-ms']"}]`)
	r := NewReachIndex(d)
	got := reachOf(func(fn func(string)) { r.StaticReach("write", fn) })
	for _, k := range []string{"interface:storage.apply", "interface:gossip.on-change", "interface:hints.on-change",
		"interface:hints.store", "component:gossip", "component:cluster", "config:write-timeout-ms"} {
		if !contains(got, k) {
			t.Errorf("static reach lacks %s: %v", k, got)
		}
	}
	got = reachOf(func(fn func(string)) { r.ScenarioReach("multi", fn) })
	for _, k := range []string{"interface:node.write", "interface:hints.replay", "component:client", "fixture:three-nodes", "fixture:base"} {
		if !contains(got, k) {
			t.Errorf("scenario reach lacks %s: %v", k, got)
		}
	}
	seen := map[string]bool{}
	for _, k := range got {
		if seen[k] {
			t.Errorf("scenario reach repeats %s", k)
		}
		seen[k] = true
	}

	// Impact: changing a subscriber or a config affects the publishing flow.
	before := langDoc(t)
	iface(before, "storage.apply").Behavior = steps(t, `[{"return": "= config['write-timeout-ms']"}]`)
	after := langDoc(t)
	iface(after, "storage.apply").Behavior = steps(t, `[{"return": "= config['write-timeout-ms']"}]`)
	iface(after, "gossip.on-change").Summary = "changed"
	after.Configs[0].Value = json.Number("3000")
	imp := ComputeImpact(before, after)
	if !reflect.DeepEqual(imp.Configs.Modified, []string{"write-timeout-ms"}) || !reflect.DeepEqual(imp.Interfaces.Modified, []string{"gossip.on-change"}) {
		t.Errorf("impact sets %+v %+v", imp.Configs, imp.Interfaces)
	}
	want := []FlowImpact{{Flow: "write", Reasons: []string{"config:write-timeout-ms", "interface:gossip.on-change"}, Basis: "static"}}
	if !reflect.DeepEqual(imp.FlowsAffected, want) {
		t.Errorf("flows affected %+v", imp.FlowsAffected)
	}
	after2 := langDoc(t)
	after2.Fixtures[0].Summary = "new"
	imp = ComputeImpact(langDoc(t), after2)
	if !reflect.DeepEqual(imp.Fixtures.Modified, []string{"base"}) || len(imp.FlowsAffected) != 0 {
		t.Errorf("fixture impact %+v %+v", imp.Fixtures, imp.FlowsAffected)
	}
}

func TestLanguageWorld(t *testing.T) {
	x := NewIndex(langDoc(t))
	chain, err := x.FixtureChain([]string{"three-nodes", "base"})
	if err != nil || len(chain) != 2 || chain[0].ID != "base" || chain[1].ID != "three-nodes" {
		t.Fatalf("chain %v %v", chain, err)
	}
	w, err := x.ScenarioWorld(x.Scenarios["single"])
	if err != nil {
		t.Fatal(err)
	}
	wantTopo := map[string][]string{"node": {"n1", "n2", "n3"}, "gossip": {"g1"}}
	if !reflect.DeepEqual(w.Topology, wantTopo) {
		t.Errorf("topology %v", w.Topology)
	}
	if w.EpochMS != 1000 {
		t.Errorf("epoch %d", w.EpochMS)
	}
	wantConf := map[string]any{"write-timeout-ms": int64(500), "hints-enabled": false, "untyped": map[string]any{"a": int64(1)}}
	if !reflect.DeepEqual(w.Config, wantConf) {
		t.Errorf("config %#v", w.Config)
	}
	wantState := map[string]map[string]any{
		"storage":    {"rows": map[string]any{"k1": map[string]any{"v": int64(1)}}},
		"storage@n2": {"rows": map[string]any{"k2": map[string]any{"v": int64(2)}}},
		"storage@n3": {"rows": map[string]any{}},
	}
	if !reflect.DeepEqual(w.State, wantState) {
		t.Errorf("state %#v", w.State)
	}
	w2, _ := x.ScenarioWorld(x.Scenarios["multi"])
	if ms, _ := (&Clock{Epoch: "2026-10-30T00:00:00Z"}).EpochMillis(); w2.EpochMS != ms || ms != 1793318400000 {
		t.Errorf("epoch %d %d", w2.EpochMS, ms)
	}
	if g, inst, ok := x.InstanceGroup(w.Topology, "storage"); !ok || g != "node" || len(inst) != 3 {
		t.Errorf("group of storage: %s %v %v", g, inst, ok)
	}
	if _, _, ok := x.InstanceGroup(w.Topology, "hints"); ok {
		t.Error("hints has no group")
	}
	if StateKey("a", "") != "a" || StateKey("a", "n1") != "a@n1" {
		t.Error("StateKey")
	}
	if c, i := SplitStateKey("a@n1"); c != "a" || i != "n1" {
		t.Error("SplitStateKey")
	}
	// The fixtures were not modified by building the world.
	if _, ok := x.Fixtures["base"].State["storage"]["rows"].(map[string]any)["k2"]; ok {
		t.Error("fixture state was modified")
	}
}

func TestCELScanners(t *testing.T) {
	cases := map[string][]string{
		`config.a + config["b-c"] + config['d']`:  {"a", "b-c", "d"},
		`input.config.x + myconfig.y`:             nil,
		`!('config.json' in input.files)`:         nil,
		`has(config.flag) && config . spaced > 1`: {"flag", "spaced"},
		`"config[\"x\"]" + config[ "real" ]`:      {"real"},
		`config.a + config.a`:                     {"a"},
	}
	for src, want := range cases {
		if got := ConfigRefs(src); !reflect.DeepEqual(got, want) {
			t.Errorf("ConfigRefs(%s) = %v, want %v", src, got, want)
		}
	}
	for src, want := range map[string]bool{
		`now > 1730000000000`:                  true,
		`now - 99999999999999 > 0`:             true,
		`1000000000000 < now`:                  false, // exactly 10^12 is not over it
		`now > 1730000000`:                     false,
		`input.now > 1730000000000`:            false,
		`now > int('1730000000000')`:           false,
		`vars.t + 1730000000000 > 0`:           false,
		`1730000000000000 + now * 1000`:        false, // arithmetic, not a comparison
		`(now - vars.t) < 1730000000000 && ok`: true,
		`x ? now >= 1730000000000 : false`:     true,
		`now > 0 ? 1730000000000 : 0`:          false,
		`now < 99999999999999999999u`:          true,
	} {
		if _, got := WallClockLiteral(src); got != want {
			t.Errorf("WallClockLiteral(%s) = %v, want %v", src, got, want)
		}
	}
}

// TestExamplesUnchanged checks that the example ontologies still decode and
// validate with the issue counts they had before the §11 additions.
func TestExamplesUnchanged(t *testing.T) {
	for path, want := range map[string][2]int{ // errors, warnings
		"../testdata/gateway/ontology.yaml":                {0, 0},
		"../../examples/cassandra/judge/cassandra-v1.json": {0, 0}, // frozen pre-§11 model
	} {
		b, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		d, err := ParseDocument(b)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		var got [2]int
		for _, is := range Validate(d) {
			if is.Severity == SeverityError {
				got[0]++
			} else {
				got[1]++
			}
		}
		if got != want {
			t.Errorf("%s: %d errors and %d warnings, want %v", path, got[0], got[1], want)
		}
		if len(d.Configs) != 0 || len(d.Fixtures) != 0 {
			t.Errorf("%s: unexpected configs or fixtures", path)
		}
		js, _ := json.Marshal(d)
		if strings.Contains(string(js), `"configs"`) || strings.Contains(string(js), `"fixtures"`) {
			t.Errorf("%s: encoding gained §11 keys", path)
		}
	}
}

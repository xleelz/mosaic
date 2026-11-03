package model

import (
	"encoding/json"
	"reflect"
	"testing"
)

const analysisDoc = `
components:
  - {id: client, kind: client}
  - {id: gw, name: Gateway, kind: service, layer: edge, summary: front door}
  - {id: auth, parent: gw}
  - {id: svc}
  - {id: db, kind: datastore, state: {initial: {rows: 0}, schema: {type: object}}}
  - {id: queue}
  - {id: other}
interfaces:
  - component: gw
    name: in
    behavior:
      - {call: auth.check}
      - {call: svc.read, on_error: [{call: svc.fallback}]}
      - {call: "= 'svc.' + input.op", targets: [svc.write, svc.read]}
      - {emit: queue.event}
      - title: Pick a route
        choice: route
        default: fast
        options:
          fast: [{return: 1}]
          slow: [{call: db.scan}]
  - component: auth
    name: check
    behavior:
      - choice: mode
        options: {strict: [{return: true}]}
      - choice: level
        default: "= input.level"
        options: {low: [], high: []}
  - {component: svc, name: read}
  - {component: svc, name: write, behavior: [{call: db.put}]}
  - {component: svc, name: fallback}
  - {component: db, name: put}
  - {component: db, name: scan}
  - {component: queue, name: event, behavior: [{call: client.callback}]}
  - {component: client, name: callback}
  - component: other
    name: lonely
    behavior:
      - {choice: unreached, default: a, options: {a: [], b: []}}
      - {call: db.put}
      - {call: "= 'svc.' + 'read'"}
links:
  - {id: reads, from: svc.read, to: db, kind: reads, label: SQL}
  - {id: plain, from: other, to: db.scan}
  - {id: dangling, from: other, to: nowhere}
flows:
  - {id: main, entry: {caller: client, interface: gw.in}}
  - {id: lonely, entry: {caller: client, interface: other.lonely}}
  - {id: story, steps: [{component: gw, title: t}]}
scenarios:
  - {id: z-last, flow: main}
  - {id: a-first, flow: main}
  - {id: elsewhere, flow: lonely}
`

func analysisIndex(t *testing.T) *Index {
	t.Helper()
	d, err := ParseDocument([]byte(analysisDoc))
	if err != nil {
		t.Fatal(err)
	}
	for _, is := range Validate(d) {
		if is.Severity == SeverityError && is.Path != "links[dangling].to" { // the dangling link is deliberate
			t.Fatalf("fixture error %s: %s", is.Path, is.Message)
		}
	}
	return NewIndex(d)
}

func TestChoicePoints(t *testing.T) {
	got := analysisIndex(t).ChoicePoints()
	want := map[string]ChoicePoint{
		"gw.in.route":            {Key: "gw.in.route", Interface: "gw.in", Name: "route", Options: []string{"fast", "slow"}, Default: "fast", Title: "Pick a route"},
		"auth.check.mode":        {Key: "auth.check.mode", Interface: "auth.check", Name: "mode", Options: []string{"strict"}, Default: "strict"},
		"auth.check.level":       {Key: "auth.check.level", Interface: "auth.check", Name: "level", Options: []string{"high", "low"}, Default: "= input.level"},
		"other.lonely.unreached": {Key: "other.lonely.unreached", Interface: "other.lonely", Name: "unreached", Options: []string{"a", "b"}, Default: "a"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %+v\nwant %+v", got, want)
	}
}

func TestPlan(t *testing.T) {
	x := analysisIndex(t)
	p, err := x.Plan("main")
	if err != nil {
		t.Fatal(err)
	}
	check := func(name string, got, want any) {
		t.Helper()
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s: got %v, want %v", name, got, want)
		}
	}
	check("flow", p.Flow, "main")
	check("entry", p.Entry, "gw.in")
	check("caller", p.Caller, "client")
	// Static calls, on_error calls, dynamic targets, choice branches and emits
	// (and the emit's own calls) are reachable; other.lonely is not.
	check("interfaces", p.Interfaces, []string{"auth.check", "client.callback", "db.put", "db.scan", "gw.in", "queue.event", "svc.fallback", "svc.read", "svc.write"})
	check("components", p.Components, []string{"auth", "client", "db", "gw", "queue", "svc"})
	var keys []string
	for _, c := range p.Choices {
		keys = append(keys, c.Key)
	}
	check("choices scoped to reachable interfaces", keys, []string{"auth.check.level", "auth.check.mode", "gw.in.route"})
	check("state", p.State, []StateInfo{{Component: "db", Initial: map[string]any{"rows": json.Number("0")}, Schema: map[string]any{"type": "object"}}})
	// The caller component is not faultable, but its reachable interfaces are.
	check("faultable", p.Faultable, []string{"auth", "auth.check", "client.callback", "db", "db.put", "db.scan", "gw", "gw.in", "queue", "queue.event", "svc", "svc.fallback", "svc.read", "svc.write"})
	check("scenarios", p.Scenarios, []string{"a-first", "z-last"})
	check("dynamic", len(p.Dynamic), 0)

	p, err = x.Plan("lonely")
	if err != nil {
		t.Fatal(err)
	}
	check("lonely interfaces", p.Interfaces, []string{"db.put", "other.lonely"})
	check("lonely dynamic", p.Dynamic, []string{"other.lonely step 3"})
	check("lonely choices", len(p.Choices), 1)
	check("lonely scenarios", p.Scenarios, []string{"elsewhere"})

	if _, err := x.Plan("nope"); err == nil {
		t.Error("unknown flow: expected an error")
	}
	if _, err := x.Plan("story"); err == nil {
		t.Error("flow without entry: expected an error")
	}
}

func TestGraph(t *testing.T) {
	g := analysisIndex(t).Graph()
	nodes := map[string]GraphNode{}
	for _, n := range g.Nodes {
		nodes[n.ID] = n
	}
	if len(g.Nodes) != 7 || g.Nodes[0].ID != "client" {
		t.Fatalf("nodes keep document order: %+v", g.Nodes)
	}
	if n := nodes["gw"]; n.Name != "Gateway" || n.Kind != "service" || n.Layer != "edge" || n.Summary != "front door" || n.Leaf || n.Stateful {
		t.Errorf("gw: %+v", n)
	}
	if n := nodes["auth"]; n.Name != "auth" || n.Parent != "gw" || !n.Leaf {
		t.Errorf("auth: name defaults to id and a child is a leaf: %+v", n)
	}
	if n := nodes["db"]; !n.Stateful || !n.Leaf || !reflect.DeepEqual(n.Interfaces, []string{"db.put", "db.scan"}) {
		t.Errorf("db: %+v", n)
	}
	if n := nodes["queue"]; n.Interfaces == nil {
		t.Error("interfaces encode as a list")
	}

	edges := map[string]GraphEdge{}
	for _, e := range g.Edges {
		if _, dup := edges[e.ID]; dup {
			t.Errorf("duplicate edge %s", e.ID)
		}
		edges[e.ID] = e
	}
	want := map[string]GraphEdge{
		// gw calls svc through three call sites: one edge listing each interface once.
		"calls:gw->svc":       {ID: "calls:gw->svc", From: "gw", To: "svc", Kind: "calls", Label: "3 interfaces", Interfaces: []string{"svc.fallback", "svc.read", "svc.write"}, Derived: true},
		"calls:gw->auth":      {ID: "calls:gw->auth", From: "gw", To: "auth", Kind: "calls", Label: "check", Interfaces: []string{"auth.check"}, Derived: true},
		"calls:gw->db":        {ID: "calls:gw->db", From: "gw", To: "db", Kind: "calls", Label: "scan", Interfaces: []string{"db.scan"}, Derived: true},
		"emits:gw->queue":     {ID: "emits:gw->queue", From: "gw", To: "queue", Kind: "emits", Label: "event", Interfaces: []string{"queue.event"}, Derived: true},
		"calls:queue->client": {ID: "calls:queue->client", From: "queue", To: "client", Kind: "calls", Label: "callback", Interfaces: []string{"client.callback"}, Derived: true},
		"calls:svc->db":       {ID: "calls:svc->db", From: "svc", To: "db", Kind: "calls", Label: "put", Interfaces: []string{"db.put"}, Derived: true},
		"calls:other->db":     {ID: "calls:other->db", From: "other", To: "db", Kind: "calls", Label: "put", Interfaces: []string{"db.put"}, Derived: true},
		// Flow entries are derived calls from the caller; two flows from client merge.
		"calls:client->gw":    {ID: "calls:client->gw", From: "client", To: "gw", Kind: "calls", Label: "in", Interfaces: []string{"gw.in"}, Derived: true},
		"calls:client->other": {ID: "calls:client->other", From: "client", To: "other", Kind: "calls", Label: "lonely", Interfaces: []string{"other.lonely"}, Derived: true},
		// Explicit links map interface endpoints to their components.
		"link:reads": {ID: "link:reads", From: "svc", To: "db", Kind: "reads", Label: "SQL"},
		"link:plain": {ID: "link:plain", From: "other", To: "db", Kind: "depends_on", Interfaces: []string{"db.scan"}},
	}
	if !reflect.DeepEqual(edges, want) {
		for id, e := range edges {
			if !reflect.DeepEqual(e, want[id]) {
				t.Errorf("edge %s:\n got %+v\nwant %+v", id, e, want[id])
			}
		}
		for id := range want {
			if _, ok := edges[id]; !ok {
				t.Errorf("missing edge %s", id)
			}
		}
	}
	// Derived edges are sorted by from, to, kind and come before links.
	var order []string
	for _, e := range g.Edges {
		order = append(order, e.ID)
	}
	wantOrder := []string{"calls:client->gw", "calls:client->other", "calls:gw->auth", "calls:gw->db", "emits:gw->queue", "calls:gw->svc",
		"calls:other->db", "calls:queue->client", "calls:svc->db", "link:reads", "link:plain"}
	if !reflect.DeepEqual(order, wantOrder) {
		t.Errorf("order %v", order)
	}
}

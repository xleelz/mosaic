package main

import (
	"bytes"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

const integritySkeleton = `schema_version: 1
id: integ
components:
  - {id: client}
  - {id: svc, state: {initial: {limits: {cpu: 4}}}}
  - {id: db}
  - {id: vendor, kind: external}
  - {id: gpu}
`

const integrityA = `schema_version: 1
interfaces:
  # inert: called, no behavior or store
  - {component: svc, name: liveness, sources: [{path: svc/live.go, line: 10}]}
  # a boundary stub owned by b.yaml that b never defines: an orphan
  - {component: svc, name: orphan, attributes: {boundary: true, owner: b}}
  # a boundary stub of the shared owner: never inert
  - {component: db, name: shared-stub, attributes: {boundary: true, owner: shared}}
  # third-party and latency-only leaves: stubs by design
  - {component: vendor, name: charge}
  - {component: gpu, name: kernel, latency_ms: 2}
  - component: svc
    name: handle
    behavior:
      - {call: svc.liveness}
      - {call: svc.orphan}
      - {call: db.shared-stub}
      - {call: vendor.charge}
      - {call: gpu.kernel}
      - {call: db.get, input: {id: x}}
      - if: "state.limits.cpu > 1 && state.limits.ram > 0 && has(state.knob) && state.knob"
        then: [{set: {state.seen: true}}]
      - {set: {"= 'state.sessions.' + input.id": 1}}
      - {return: "= state.seen ? state.sessions : state[input.k]"}
  - {component: db, name: get, store: {table: rows, op: get, key: "= 'ROW#' + input.id"}}
  - {component: db, name: put, store: {table: rows, op: put, key: "= 'OTHER#' + input.id", value: {a: 1}}}
  - {component: db, name: tick, store: {table: ticks, op: get, key: now}}
  # scheduling
  - {component: svc, name: sweep, behavior: [{return: {}}], sources: [{path: svc/sweep.go, line: 20}]}
  - {component: svc, name: reap, behavior: [{return: {}}], sources: [{path: svc/reap.go, line: 5}]}
  - {component: svc, name: pump, behavior: [{return: {}}], sources: [{path: svc/pump.go, line: 7}]}
  - {component: svc, name: boot, behavior: [{return: {}}], sources: [{path: svc/main.go, line: 1}]}
  - {component: svc, name: consume, behavior: [{return: {}}], sources: [{path: svc/q.go, line: 3}]}
  - {component: svc, name: loop, attributes: {schedule: every 5 s}, behavior: [{return: {}}]}
  - component: svc
    name: start
    behavior:
      - {emit: svc.pump, after_ms: 100}
      - {publish: jobs}
      - {return: {}}
  - {component: svc, name: on-job, subscribe: [jobs], behavior: [{call: svc.consume}]}
flows:
  - {id: handle, entry: {caller: client, interface: svc.handle}}
  - {id: reap, entry: {caller: client, interface: svc.reap, repeat: {count: 2, interval_ms: 10}}}
  - {id: svc-startup, entry: {caller: client, interface: svc.start}}
  - {id: sweep-once, entry: {caller: client, interface: svc.sweep}}
  - {id: run-main, entry: {caller: client, interface: svc.boot}}
scenarios:
  - id: loop
    steps: [{caller: client, interface: svc.loop}]
    expect: ["true"]
`

const integrityB = `schema_version: 1
interfaces:
  - {component: db, name: ticker, store: {table: ticks, op: put, key: "= input.k", value: {}}}
`

const integrityFixtures = `schema_version: 1
fixtures:
  - id: world
    state:
      db: {other: {k1: {}}}
`

var integrityInv = []invEntry{
	{Kind: "cron", Name: "sweep", File: "svc/sweep.go", Line: 20},
	{Kind: "cron", Name: "reap", File: "svc/reap.go", Line: 5},
	{Kind: "cron", Name: "pump", File: "svc/pump.go", Line: 7},
	{Kind: "service-main", Name: "main", File: "svc/main.go", Line: 1},
	{Kind: "queue-consumer", Name: "consume", File: "svc/q.go", Line: 3},
	{Kind: "http-route", Name: "GET /live", File: "svc/live.go", Line: 10},
}

func integrityDoc(t *testing.T) (*model.Document, map[string]string) {
	t.Helper()
	var ins []merge.Input
	for _, f := range []struct{ name, y string }{
		{"skeleton.yaml", integritySkeleton}, {"a.yaml", integrityA}, {"b.yaml", integrityB}, {"fixtures.yaml", integrityFixtures},
	} {
		d, err := model.ParseDocument([]byte(f.y))
		if err != nil {
			t.Fatalf("%s: %v", f.name, err)
		}
		ins = append(ins, merge.Input{Name: f.name, Doc: d})
	}
	res, err := merge.Merge(ins)
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Conflicts) > 0 {
		t.Fatal(res.Conflicts)
	}
	for _, is := range model.Validate(res.Doc) {
		if is.Severity == model.SeverityError {
			t.Fatalf("%s: %s", is.Path, is.Message)
		}
	}
	return res.Doc, res.Origins
}

func subjects(r *integrityReport) []string {
	var out []string
	for _, f := range r.Findings {
		out = append(out, f.Subject)
	}
	return out
}

func TestLintInert(t *testing.T) {
	doc, origins := integrityDoc(t)
	r := lintInert(doc, collectCitations(doc), integrityInv, origins)
	got := strings.Join(subjects(r), ",")
	if got != "svc.liveness,svc.orphan" {
		t.Fatalf("inert %q:\n%+v", got, r.Findings)
	}
	if r.Findings[1].Fragment != "b.yaml" || !strings.Contains(r.Findings[1].Why, "owner never defined") {
		t.Errorf("orphan %+v", r.Findings[1])
	}
	var b bytes.Buffer
	if r.print(&b, -1, false) {
		t.Error("gate off failed")
	}
	if !strings.Contains(b.String(), "! inert svc.liveness (a.yaml): no behavior or store; called by svc.handle; cites http-route GET /live") {
		t.Errorf("output:\n%s", b.String())
	}
	b.Reset()
	if !r.print(&b, 0.5, true) || !strings.Contains(b.String(), "✗ inert in b.yaml: 1 of 1") || strings.Contains(b.String(), "! inert") {
		t.Errorf("gate 0.5:\n%s", b.String())
	}
}

func TestLintUnscheduled(t *testing.T) {
	doc, origins := integrityDoc(t)
	r := lintUnscheduled(doc, collectCitations(doc), integrityInv, origins)
	// reap (repeat), pump (timer), boot (a main a flow enters) and consume
	// (an event delivery reaches it) are scheduled; sweep runs once from a
	// flow and loop only from a scenario step.
	got := strings.Join(subjects(r), ",")
	if got != "svc.loop,svc.sweep" {
		t.Fatalf("unscheduled %q:\n%+v", got, r.Findings)
	}
	if !strings.Contains(r.Findings[0].Why, "only by scenario steps") || !strings.Contains(r.Findings[1].Why, "flows with no repeat and no startup: sweep-once") {
		t.Errorf("why: %+v", r.Findings)
	}
	if f := r.Fragments[0]; f.Of != 6 || f.Hits != 2 {
		t.Errorf("share %+v", r.Fragments)
	}
	// Without an inventory only the periodic tag counts.
	if r := lintUnscheduled(doc, nil, nil, origins); strings.Join(subjects(r), ",") != "svc.loop" {
		t.Errorf("no inventory: %+v", r.Findings)
	}
}

func TestLintDataflow(t *testing.T) {
	doc, origins := integrityDoc(t)
	r := lintDataflow(doc, origins)
	// limits.cpu is initial state, seen and sessions are set (sessions
	// dynamically), ticks is written by b.yaml's store put. limits.ram and
	// knob are read and never written; rows ROW#* only has OTHER# writes.
	got := strings.Join(subjects(r), ",")
	if got != "db state.rows key ROW#*,svc state.knob,svc state.limits.ram" {
		t.Fatalf("dataflow %q:\n%+v", got, r.Findings)
	}
	if !strings.Contains(r.Findings[1].Why, "under has()") || strings.Contains(r.Findings[2].Why, "under has()") {
		t.Errorf("has() note: %+v", r.Findings)
	}
	if r.Unknown != 1 { // state[input.k]
		t.Errorf("unknown %d", r.Unknown)
	}
	var b bytes.Buffer
	if !r.print(&b, 0.1, false) || !strings.Contains(b.String(), "1 dynamic paths unknown") {
		t.Errorf("print:\n%s", b.String())
	}
}

func TestStatePaths(t *testing.T) {
	ps, unk := statePaths("state.a.b.exists(x, x) && vars.state.c && state['d'].e && state[vars.k] && has(state.f)")
	var got []string
	for _, p := range ps {
		got = append(got, strings.Join(p, "."))
	}
	if strings.Join(got, ",") != "a.b,d.e,f" || unk != 1 {
		t.Errorf("paths %q unknown %d", got, unk)
	}
}

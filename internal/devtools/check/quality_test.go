package main

import (
	"bytes"
	"regexp"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

// The skeleton defines the components; the fragment the interfaces, flows
// and scenarios, so coverage and findings map back to fragment.yaml.
const qualitySkeleton = `schema_version: 1
id: q
components:
  - {id: client}
  - {id: svc}
  - {id: db}
`

const qualityFragment = `schema_version: 1
interfaces:
  - {component: db, name: put, store: {table: rows, op: put, key: "= input.id", value: "= input"}}
  - component: db
    name: get
    errors: [{code: not_found, status: 404}]
    store: {table: rows, op: get, key: "= input.id", not_found: not_found}
  - component: svc
    name: write
    errors: [{code: bad, status: 400}]
    behavior:
      - if: "input.ok"
        then:
          - {call: db.put, input: {id: "= input.id"}}
        else:
          - {title: refuse a bad write, fail: {code: bad}}
      - {return: {ok: true}}
  - component: svc
    name: read
    errors: [{code: missing, status: 404}]
    behavior:
      - {call: db.get, input: {id: "= input.id"}, as: row, on_error: continue}
      - if: "!vars.row.ok"
        then:
          - {title: report a missing row, fail: {code: missing}}
      - {return: "= vars.row.value"}
  - component: svc
    name: maybe
    behavior:
      - if: "input.go"
        then:
          - {call: db.put, input: {id: m1}}
      - {return: {}}
  - component: svc
    name: ping
    behavior:
      - {return: {pong: true}}
flows:
  - {id: write, tags: [writes], entry: {caller: client, interface: svc.write, input: {id: r1, ok: true}}}
  - {id: write-unread, tags: [writes], entry: {caller: client, interface: svc.write, input: {id: r2, ok: true}}}
  - {id: read, entry: {caller: client, interface: svc.read, input: {id: r1}}}
  - {id: ping, entry: {caller: client, interface: svc.ping}}
  - {id: maybe, entry: {caller: client, interface: svc.maybe, input: {go: false}}}
scenarios:
  - {id: write-unchecked, flow: write, expect: ["result.ok"]}
  - {id: write-checked, flow: write, expect: ["result.ok", "'r1' in state['db'].rows"]}
  - {id: write-refused, flow: write, input: {id: r1, ok: false}, expect: ["!result.ok"]}
  - id: write-then-read
    steps:
      - {flow: write, as: w}
      - {flow: read, as: r}
    expect: ["steps.r.result.ok", "trace.exists(e, e.type == 'set')"]
  - id: read-mocked
    flow: read
    mocks: [{interface: db.get, return: {id: r1}}]
    expect: ["result.ok"]
  - {id: ping, flow: ping, expect: ["result.ok"]}
  - {id: maybe-skips, flow: maybe, expect: ["result.ok"]}
`

func qualityDoc(t *testing.T) (*model.Document, map[string]string) {
	t.Helper()
	var ins []merge.Input
	for name, y := range map[string]string{"skeleton.yaml": qualitySkeleton, "fragment.yaml": qualityFragment} {
		d, err := model.ParseDocument([]byte(y))
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		ins = append(ins, merge.Input{Name: name, Doc: d})
	}
	if ins[0].Name != "skeleton.yaml" {
		ins[0], ins[1] = ins[1], ins[0]
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

func TestBehaviorPaths(t *testing.T) {
	f := &model.Interface{ID: "a.b", Behavior: []model.Step{
		{If: "x", Then: []model.Step{{Title: "t"}}, Else: []model.Step{{Title: "e"}}},
		{Choice: "c", Options: map[string][]model.Step{"z": {{}}, "y": {{}}}},
		{Foreach: "= input", Steps: []model.Step{{}}},
		{Branches: [][]model.Step{{{}}, {{}, {}}}},
		{Call: "x.y", OnError: &model.OnError{Steps: []model.Step{{}}}},
	}}
	var got []string
	for _, p := range behaviorPaths(f) {
		got = append(got, strings.TrimPrefix(p.Path, "a.b:"))
	}
	want := "behavior[0] behavior[0].then[0] behavior[0].else[0] behavior[1] behavior[1].options.y[0] behavior[1].options.z[0] " +
		"behavior[2] behavior[2].steps[0] behavior[3] behavior[3].branches[0][0] behavior[3].branches[1][0] behavior[3].branches[1][1] " +
		"behavior[4] behavior[4].on_error[0]"
	if strings.Join(got, " ") != want {
		t.Errorf("paths:\n%s\nwant\n%s", strings.Join(got, " "), want)
	}
}

// TestBehaviorCoverageFromSet checks the report against a hand-made
// executed set, independent of the simulator.
func TestBehaviorCoverageFromSet(t *testing.T) {
	doc, origins := qualityDoc(t)
	ex := map[string]bool{}
	for _, p := range []string{"svc.write:behavior[0]", "svc.write:behavior[0].then[0]", "svc.write:behavior[1]",
		"svc.read:behavior[0]", "svc.read:behavior[1]", "svc.read:behavior[2]"} {
		ex[p] = true
	}
	r := behaviorCoverage(doc, ex, origins, 2)
	if r.Total != 12 || r.Run != 6 {
		t.Errorf("run %d of %d", r.Run, r.Total)
	}
	var gaps []string
	for _, g := range r.Gaps {
		gaps = append(gaps, g.Kind+" "+g.Path)
	}
	want := "fail svc.write:behavior[0].else[0], if-else svc.write:behavior[0].else, if-then svc.read:behavior[1].then, fail svc.read:behavior[1].then[0]"
	sortedGaps := strings.Join(gaps, ", ")
	for _, w := range strings.Split(want, ", ") {
		if !strings.Contains(sortedGaps, w) {
			t.Errorf("gaps lack %q: %s", w, sortedGaps)
		}
	}
	if len(gaps) != 5 {
		t.Errorf("gaps: %s", sortedGaps)
	}
	if len(r.Fragments) != 1 || r.Fragments[0].Fragment != "fragment.yaml" || r.Fragments[0].Complete != 0 || r.Fragments[0].Interfaces != 4 {
		t.Errorf("fragments %+v", r.Fragments)
	}
	var b bytes.Buffer
	r.print(&b, true)
	for _, s := range []string{"~ behavior svc.ping: 0/1 steps run (fragment.yaml)", "    not run: svc.ping:behavior[0]",
		"~ unexecuted if-then svc.read:behavior[1].then: if !vars.row.ok", "~ unexecuted fail svc.read:behavior[1].then[0]: report a missing row",
		"behavior coverage fragment.yaml: 6/12 steps (50.0%), 0/4 interfaces complete, 5 unexecuted fail/if branches",
		"behavior coverage: 6/12 steps (50.0%) over 2 scenarios"} {
		if !strings.Contains(b.String(), s) {
			t.Errorf("output lacks %q:\n%s", s, b.String())
		}
	}
	b.Reset()
	r.markdown(&b, 0)
	for _, s := range []string{"| `fragment.yaml` | 4 | 0 | 6 | 12 | 50.0% | 5 |", "| `svc.read` | `fragment.yaml` | 3 | 4 | 2 |", "| fail | `svc.write:behavior[0].else[0]` | refuse a bad write |"} {
		if !strings.Contains(b.String(), s) {
			t.Errorf("markdown lacks %q:\n%s", s, b.String())
		}
	}
}

func TestWritesLint(t *testing.T) {
	doc, origins := qualityDoc(t)
	fs := lintWrites(doc, origins)
	if len(fs) != 1 || fs[0].ID != "write-unread" || fs[0].Fragment != "fragment.yaml" {
		t.Errorf("findings %+v", fs)
	}
	// Writing twice through the same flow is not a read-back.
	if readsBack([]model.ScenarioStep{{Flow: "w"}, {Flow: "w"}}, "w", "svc.write") {
		t.Error("a repeated write counted as a read-back")
	}
	if !readsBack([]model.ScenarioStep{{Interface: "svc.write", Caller: "client"}, {Flow: "read"}}, "w", "svc.write") {
		t.Error("an interface step through the entry is a write")
	}
}

// TestRunQuality runs the scenarios through the simulator: the hollow lint,
// mock counts and the executed union.
func TestRunQuality(t *testing.T) {
	doc, origins := qualityDoc(t)
	var b bytes.Buffer
	r := runAll(&b, doc, origins, runOpts{Hollow: true, NoMocks: true, BehCov: true, Verbose: true})
	out := b.String()
	if r.Failed != 0 {
		t.Fatalf("failed scenarios:\n%s", out)
	}
	got := map[string]string{}
	for _, h := range r.Hollow {
		got[h.ID] = h.Kind
	}
	// write-refused fails, so it is exempt; read-mocked reaches only reads.
	want := map[string]string{"write-unchecked": "unchecked-set", "maybe-skips": "no-set", "write-unread": "writes-no-readback"}
	for id, k := range want {
		if got[id] != k {
			t.Errorf("%s: %q, want %q", id, got[id], k)
		}
	}
	if len(got) != len(want) {
		t.Errorf("hollow findings %v\n%s", got, out)
	}
	if !r.HollowFail || !r.MockFail || len(r.Mocks) != 1 || r.Mocks[0].Decl != 1 || r.Mocks[0].Called != 1 {
		t.Errorf("hollow %v mock %v mocks %+v", r.HollowFail, r.MockFail, r.Mocks)
	}
	for _, s := range []string{
		"✗ mocks: scenario read-mocked declares 1 mocks, 1 mocked calls (fragment.yaml)",
		"mocks: 1 declared in 1 scenarios, 1 mocked calls",
		"! hollow: scenario maybe-skips can reach state-writing db.put",
		"✗ hollow: scenario write-unchecked changes state",
		"hollow fragment.yaml: 1 unchecked state change, 1 writes flows without read-back; advisory: 1 no state change",
		"hollow lint: 2 failing (1 unchecked state change, 1 writes flows without read-back), 1 advisory (no state change)",
	} {
		if !strings.Contains(out, s) {
			t.Errorf("output lacks %q:\n%s", s, out)
		}
	}
	// Every scenario together runs every step except the missing-row branch.
	// (and the skipped write in svc.maybe).
	if r.Cov.Run != r.Cov.Total-2 || len(r.Cov.Gaps) != 3 {
		t.Errorf("coverage %d/%d gaps %+v\n%s", r.Cov.Run, r.Cov.Total, r.Cov.Gaps, out)
	}
	// Rule 1 alone is advisory: it never fails the check.
	if !(hollowFinding{Kind: "no-set"}).Advisory() || (hollowFinding{Kind: "unchecked-set"}).Advisory() {
		t.Error("only no-set findings are advisory")
	}
	// --scenario narrows both the runs and the coverage union.
	b.Reset()
	r = runAll(&b, doc, origins, runOpts{Only: regexp.MustCompile("^ping$"), BehCov: true})
	if r.Counted != 1 || r.Cov.Run != 1 || r.MockFail || len(r.Mocks) != 0 {
		t.Errorf("filtered: %+v\n%s", r, b.String())
	}
}

// TestHollowIgnoresIncidentalState: writes to caches, limiters and metrics
// (by kind or tag, here through a parent) are neither checked state changes
// nor state-writing reach.
func TestHollowIgnoresIncidentalState(t *testing.T) {
	doc, err := model.ParseDocument([]byte(`schema_version: 1
components:
  - {id: client}
  - {id: svc}
  - {id: caches, tags: [incidental]}
  - {id: hits, parent: caches}
  - {id: limiter, kind: limiter}
  - {id: db}
interfaces:
  - {component: hits, name: bump, behavior: [{set: {state.n: 1}}, {return: {}}]}
  - {component: limiter, name: take, behavior: [{set: {state.n: 1}}, {return: {}}]}
  - {component: db, name: put, behavior: [{set: {state.row: 1}}, {return: {}}]}
  - component: svc
    name: ping
    behavior:
      - {call: hits.bump, input: {}}
      - {call: limiter.take, input: {}}
      - {return: {}}
  - component: svc
    name: save
    behavior:
      - {call: hits.bump, input: {}}
      - {call: db.put, input: {}}
      - {return: {}}
flows:
  - {id: ping, entry: {caller: client, interface: svc.ping}}
  - {id: save, entry: {caller: client, interface: svc.save}}
scenarios:
  - {id: ping, flow: ping, expect: ["result.ok"]}
  - {id: save, flow: save, expect: ["result.ok"]}
`))
	if err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	r := runAll(&b, doc, nil, runOpts{Hollow: true})
	if r.Failed != 0 || len(r.Hollow) != 1 || r.Hollow[0].ID != "save" || r.Hollow[0].Detail != "sets db" {
		t.Errorf("findings %+v\n%s", r.Hollow, b.String())
	}
}

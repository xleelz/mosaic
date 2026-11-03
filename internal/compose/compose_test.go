package compose

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

// probe wraps an executor, counting calls and the turns in flight per role
// and per (tree, role).
type probe struct {
	inner Executor
	delay func(t Turn, info TurnInfo) time.Duration
	hook  func(ctx context.Context, t Turn) error

	mu       sync.Mutex
	calls    map[string]int
	inflight map[string]int
	max      map[string]int
}

func newProbe(inner Executor) *probe {
	return &probe{inner: inner, calls: map[string]int{}, inflight: map[string]int{}, max: map[string]int{}}
}

func (p *probe) Run(ctx context.Context, t Turn) (json.RawMessage, error) {
	info, _ := TurnInfoFrom(ctx)
	root, _, _ := strings.Cut(t.TaskID, ".")
	keys := []string{t.Role, root + "/" + t.Role}
	p.mu.Lock()
	p.calls[t.StageID]++
	for _, k := range keys {
		p.inflight[k]++
		if p.inflight[k] > p.max[k] {
			p.max[k] = p.inflight[k]
		}
	}
	p.mu.Unlock()
	defer func() {
		p.mu.Lock()
		for _, k := range keys {
			p.inflight[k]--
		}
		p.mu.Unlock()
	}()
	if p.hook != nil {
		if err := p.hook(ctx, t); err != nil {
			return nil, err
		}
	}
	if p.delay != nil {
		if err := wait(ctx, int(p.delay(t, info)/time.Millisecond)); err != nil {
			return nil, err
		}
	}
	return p.inner.Run(ctx, t)
}

func (p *probe) count(stage string) int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.calls[stage]
}

func (p *probe) maxOf(key string) int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.max[key]
}

func mustParse(t *testing.T, src string) *Template {
	t.Helper()
	tpl, err := Parse([]byte(src))
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	return tpl
}

func mustScenario(t *testing.T, src string) *Scenario {
	t.Helper()
	sc, err := ParseScenario([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	return sc
}

func newRunner(t *testing.T, ex Executor) *Runner {
	t.Helper()
	return &Runner{Store: NewStore(filepath.Join(t.TempDir(), "runs")), Executor: ex, Dir: t.TempDir()}
}

func artifact(t *testing.T, r *Runner, task, key string) any {
	t.Helper()
	raw, err := r.Store.ReadArtifact(task, key)
	if err != nil {
		t.Fatalf("artifact %s/%s: %v", task, key, err)
	}
	v, err := decodeJSON(raw)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func wantState(t *testing.T, rec *RunRecord, state string) {
	t.Helper()
	if rec.State != state {
		t.Fatalf("task %s: state %s (%s: %s), want %s", rec.ID, rec.State, rec.Reason, rec.Error, state)
	}
}

const fanTemplate = `
id: fan
produces: artifacts
roles:
  inventory: {cap: 1}
  coder: {cap: 16, cap_scope: tree}
outputs:
  results: {type: array}
stages:
  - id: inventory
    kind: agent_turn
    role: inventory
    brief: list the areas
    output: {name: areas, schema: {type: array, items: {type: string}}}
  - id: areas
    kind: fanout
    branches_from: areas
    max_branches: %d
    parallel: true
    join: %s
    output: results
    branch:
      stages:
        - id: area
          kind: agent_turn
          role: coder
          brief: "model area {{.item}} of {{json .artifacts.areas}}"
          output: {name: result, schema: {type: object, required: [area]}}
`

func items(n int) string {
	l := make([]string, n)
	for i := range l {
		l[i] = fmt.Sprintf("%q", fmt.Sprintf("a%d", i))
	}
	return "[" + strings.Join(l, ", ") + "]"
}

const areaScript = `
turns:
  - stage: inventory
    output: %s
  - stage: area
    output: "={'area': item, 'branch': branch}"
`

func TestFanoutElevenParallelJoinedInOrder(t *testing.T) {
	tpl := mustParse(t, fmt.Sprintf(fanTemplate, 64, "all"))
	p := newProbe(NewScriptExecutor(mustScenario(t, fmt.Sprintf(areaScript, items(11)))))
	// Later branches finish first.
	p.delay = func(t Turn, info TurnInfo) time.Duration {
		if t.StageID != "area" {
			return 0
		}
		return time.Duration(11-info.Branch) * 15 * time.Millisecond
	}
	// A barrier, not timing: each area turn waits until all 11 have started
	// (so all 11 are in flight at once), or fails after a generous timeout.
	var (
		barrierMu sync.Mutex
		started   int
		all       = make(chan struct{})
	)
	p.hook = func(ctx context.Context, tr Turn) error {
		if tr.StageID != "area" {
			return nil
		}
		barrierMu.Lock()
		started++
		if started == 11 {
			close(all)
		}
		barrierMu.Unlock()
		select {
		case <-all:
			return nil
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(60 * time.Second):
			return errors.New("barrier: not all 11 area turns started within 60s")
		}
	}
	r := newRunner(t, p)
	rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: "root"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
	if got := p.maxOf("coder"); got != 11 {
		t.Errorf("max coder turns in flight = %d, want 11", got)
	}
	got := artifact(t, r, "root", "results").([]any)
	if len(got) != 11 {
		t.Fatalf("join has %d entries, want 11", len(got))
	}
	for i, v := range got {
		m := v.(map[string]any)
		if m["area"] != fmt.Sprintf("a%d", i) || m["branch"] != int64(i) {
			t.Errorf("join[%d] = %v, want area a%d", i, m, i)
		}
	}
	ss := rec.Stages["areas"]
	if *ss.Count != 11 || len(ss.Branches) != 11 {
		t.Fatalf("fanout recorded %d branches", len(ss.Branches))
	}
	for _, b := range ss.Branches {
		if b.State != StateDone {
			t.Errorf("branch %d: %s", b.Index, b.State)
		}
	}
	if meta := rec.Artifacts["areas/3/result"]; meta == nil || meta.Provenance != "stage:areas/3/area" {
		t.Errorf("branch artifact meta = %+v", meta)
	}
	if meta := rec.Artifacts["results"]; meta == nil || meta.Provenance != "join:areas" {
		t.Errorf("join artifact meta = %+v", meta)
	}
}

func TestFanoutMaxBranchesFails(t *testing.T) {
	tpl := mustParse(t, fmt.Sprintf(fanTemplate, 64, "all"))
	p := newProbe(NewScriptExecutor(mustScenario(t, fmt.Sprintf(areaScript, items(70)))))
	r := newRunner(t, p)
	rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: "root"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateFailed)
	if ss := rec.Stages["areas"]; ss.State != StateFailed || ss.Reason != ReasonMaxBranches || len(ss.Branches) != 0 {
		t.Fatalf("areas = %+v, want failed max_branches with no branches", ss)
	}
	if n := p.count("area"); n != 0 {
		t.Errorf("%d branch turns dispatched, want 0", n)
	}
	tree, err := ReadTree(r.Store, "root")
	if err != nil {
		t.Fatal(err)
	}
	if rs := tree.Refusals(); len(rs) != 1 || rs[0].Reason != ReasonMaxBranches {
		t.Errorf("refusals = %+v", rs)
	}
}

func TestFanoutEmptyAndAnyJoin(t *testing.T) {
	for _, tc := range []struct {
		join  string
		n     int
		state string
	}{{"all", 0, StateDone}, {"any", 0, StateFailed}, {"'{k: 1}'", 0, StateFailed}} {
		tpl := mustParse(t, strings.Replace(fmt.Sprintf(fanTemplate, 64, tc.join), "'", "", -1))
		r := newRunner(t, NewScriptExecutor(mustScenario(t, fmt.Sprintf(areaScript, items(tc.n)))))
		rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: "root"})
		if err != nil {
			t.Fatal(err)
		}
		wantState(t, rec, tc.state)
	}

	// any: the first branch to pass decides; the others are cancelled.
	tpl := mustParse(t, fmt.Sprintf(fanTemplate, 64, "any"))
	p := newProbe(NewScriptExecutor(mustScenario(t, fmt.Sprintf(areaScript, items(4)))))
	p.delay = func(t Turn, info TurnInfo) time.Duration {
		if t.StageID == "area" && info.Branch != 2 {
			return 5 * time.Second
		}
		return 0
	}
	r := newRunner(t, p)
	rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: "root"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
	for _, b := range rec.Stages["areas"].Branches {
		want := StateCancelled
		if b.Index == 2 {
			want = StateDone
		}
		if b.State != want {
			t.Errorf("branch %d: %s, want %s", b.Index, b.State, want)
		}
	}
	if got := artifact(t, r, "root", "results").([]any); len(got) != 1 {
		t.Errorf("join = %v, want only branch 2", got)
	}
	evs, _ := r.Store.Events("root")
	cancelled := 0
	for _, e := range evs {
		if e.Type == "branch_cancelled" {
			cancelled++
		}
	}
	if cancelled != 3 {
		t.Errorf("%d branch_cancelled events, want 3", cancelled)
	}
}

const zoomTemplate = `
id: zoom
produces: artifacts
recursion: {max_depth: 3}
inputs:
  scope: {type: string}
outputs:
  model: {type: object}
roles:
  modeler: {cap: 2, cap_scope: tree}
stages:
  - id: build
    kind: agent_turn
    role: modeler
    brief: "model {{.inputs.scope}} at depth {{.tree.depth}}"
    output: {name: model, schema: {type: object}}
  - id: zoom
    kind: subworkflow
    workflow: self
    after: [build]
    inputs: {scope: "=inputs.scope + '/part'"}
    outputs: {child_model: model}
    on_fail: bottom
  - id: bottom
    kind: gate
    expr: "artifacts.failure.reason == 'recursion_budget'"
`

func TestRecursionBudgetRefusesDepthFour(t *testing.T) {
	tpl := mustParse(t, zoomTemplate)
	sc := mustScenario(t, `
turns:
  - stage: build
    output: "={'depth': depth, 'task': task}"
`)
	r := newRunner(t, NewScriptExecutor(sc))
	rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: "root",
		Inputs: map[string]json.RawMessage{"scope": json.RawMessage(`"svc"`)}})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
	tree, err := ReadTree(r.Store, "root")
	if err != nil {
		t.Fatal(err)
	}
	if tree.Tasks != 3 || tree.MaxDepth != 3 {
		t.Fatalf("tree has %d tasks, max depth %d; want 3 and 3", tree.Tasks, tree.MaxDepth)
	}
	gc, err := r.Store.Load("root.zoom.1.zoom.1")
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, gc, StateDone)
	if ss := gc.Stages["zoom"]; ss.State != StateFailed || ss.Reason != ReasonRecursionBudget || ss.RoutedTo != "bottom" {
		t.Fatalf("grandchild zoom = %+v, want failed recursion_budget routed to bottom", ss)
	}
	if r.Store.Exists("root.zoom.1.zoom.1.zoom.1") {
		t.Error("a great-grandchild was admitted")
	}
	if rs := tree.Refusals(); len(rs) != 1 || rs[0].Stage != "root.zoom.1.zoom.1:zoom" {
		t.Errorf("refusals = %+v", rs)
	}
	// The child's model flows up through the output mapping.
	m := artifact(t, r, "root", "child_model").(map[string]any)
	if m["depth"] != int64(2) || m["task"] != "root.zoom.1" {
		t.Errorf("child_model = %v", m)
	}
	if rec.Artifacts["child_model"].Provenance != "child:root.zoom.1/model" {
		t.Errorf("provenance = %s", rec.Artifacts["child_model"].Provenance)
	}
	child, _ := r.Store.Load("root.zoom.1")
	if want := filepath.Join(rec.OutDir, "root.zoom.1"); child.OutDir != want {
		t.Errorf("child out dir %s, want %s", child.OutDir, want)
	}
	if child.Inputs["scope"] == nil || string(child.Inputs["scope"]) != `"svc/part"` {
		t.Errorf("child scope = %s", child.Inputs["scope"])
	}
}

const parentTemplate = `
id: system
produces: artifacts
recursion: {max_depth: 2}
roles: {modeler: {}}
outputs:
  contract: {type: object, required: [interfaces]}
stages:
  - id: model
    kind: agent_turn
    role: modeler
    brief: model the system
    output: {name: contract, schema: {type: object, required: [interfaces]}}
`

const childTemplate = `
id: component
produces: artifacts
recursion: {max_depth: 2}
inputs:
  contract: {type: object, required: [interfaces]}
roles: {modeler: {}}
outputs:
  model: {type: object}
stages:
  - id: refine
    kind: agent_turn
    role: modeler
    brief: "refine {{json .artifacts.contract}}"
    output: {name: model, schema: {type: object}}
  - id: disagree
    kind: change_request
    target: parent
    from: model.objection
    artifact: contract
`

func runParent(t *testing.T) (*Runner, *Template) {
	t.Helper()
	parent := mustParse(t, parentTemplate)
	child := mustParse(t, childTemplate)
	sc := mustScenario(t, `
turns:
  - stage: model
    output: {interfaces: [get, put]}
  - stage: refine
    output: "={'seen': brief.contains('get'), 'objection': {'interface': 'put', 'reason': 'put is idempotent'}}"
`)
	r := newRunner(t, NewScriptExecutor(sc))
	r.Resolve = DirResolver(t.TempDir(), parent, child)
	rec, err := r.Run(context.Background(), Admission{Template: parent, ID: "sys"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
	return r, child
}

// snapshot reads every file of a task's directory except its history and
// requests, which a child may append to.
func snapshot(t *testing.T, dir string) map[string]string {
	t.Helper()
	out := map[string]string{}
	filepath.WalkDir(dir, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(dir, p)
		if d.IsDir() {
			if rel == "requests" {
				return filepath.SkipDir
			}
			return nil
		}
		if rel == "events.jsonl" {
			return nil
		}
		b, _ := os.ReadFile(p)
		out[rel] = string(b)
		return nil
	})
	return out
}

func TestDetachedChildReadsParentArtifact(t *testing.T) {
	r, child := runParent(t)
	before := snapshot(t, r.Store.RunDir("sys"))
	rec, err := r.Run(context.Background(), Admission{Template: child, Parent: "sys",
		FromParent: map[string]string{"contract": "contract"}})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
	if rec.ID != "sys.detached.1" || rec.Parent != "sys" || rec.TreeRoot != "sys" || rec.Depth != 2 {
		t.Fatalf("child = %s parent %s root %s depth %d", rec.ID, rec.Parent, rec.TreeRoot, rec.Depth)
	}
	if p := rec.Artifacts["contract"].Provenance; p != "parent:sys/contract" {
		t.Errorf("contract provenance = %s", p)
	}
	if m := artifact(t, r, rec.ID, "model").(map[string]any); m["seen"] != true {
		t.Errorf("the child's brief did not include the parent's contract: %v", m)
	}
	if !reflect.DeepEqual(before, snapshot(t, r.Store.RunDir("sys"))) {
		t.Error("the parent's run.json or artifacts changed")
	}
	tree, err := ReadTree(r.Store, rec.ID)
	if err != nil {
		t.Fatal(err)
	}
	if tree.Root.ID != "sys" || len(tree.Root.Children) != 1 || !tree.Root.Children[0].Detached {
		t.Errorf("tree = %+v", tree.Root)
	}
	// A detached grandchild would exceed max_depth 2.
	_, err = r.Run(context.Background(), Admission{Template: child, Parent: rec.ID,
		FromParent: map[string]string{"contract": "contract"}})
	var ae *AdmissionError
	if !errors.As(err, &ae) || ae.Reason != ReasonRecursionBudget {
		t.Errorf("deep detached child: err %v, want recursion_budget", err)
	}
	// A missing input is refused, naming it.
	_, err = r.Run(context.Background(), Admission{Template: child, Parent: "sys"})
	if !errors.As(err, &ae) || !strings.Contains(err.Error(), `"contract"`) {
		t.Errorf("missing input: err %v", err)
	}
}

func TestChangeRequestLeavesDoneParentUnchanged(t *testing.T) {
	r, child := runParent(t)
	before := snapshot(t, r.Store.RunDir("sys"))
	rec, err := r.Run(context.Background(), Admission{Template: child, Parent: "sys", ID: "sys.zoom",
		FromParent: map[string]string{"contract": "contract"}})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
	parent, _ := r.Store.Load("sys")
	wantState(t, parent, StateDone)
	if !reflect.DeepEqual(before, snapshot(t, r.Store.RunDir("sys"))) {
		t.Error("the change request changed the parent's run.json or artifacts")
	}
	reqs, err := r.Store.Requests("sys")
	if err != nil {
		t.Fatal(err)
	}
	if len(reqs) != 1 {
		t.Fatalf("%d requests, want 1", len(reqs))
	}
	q := reqs[0]
	if q.ID != "sys.zoom.disagree" || q.FromTask != "sys.zoom" || q.Target != (RequestTarget{Task: "sys", Artifact: "contract"}) || q.State != StatePending {
		t.Errorf("request = %+v", q)
	}
	if !strings.Contains(string(q.Body), "idempotent") {
		t.Errorf("body = %s", q.Body)
	}
	evs, _ := r.Store.Events("sys")
	found := false
	for _, e := range evs {
		if e.Type == "change_request" && e.Data["request"] == q.ID {
			found = true
		}
	}
	if !found {
		t.Error("the parent's history has no change_request event")
	}
	tree, _ := ReadTree(r.Store, "sys")
	if len(tree.Root.Requests) != 1 {
		t.Errorf("tree root requests = %d", len(tree.Root.Requests))
	}
	// A controller acts on it: a new run of the parent's workflow with the
	// request bound as an input is its own tree, linked by the input.
}

const resumeTemplate = `
id: resume
roles: {worker: {}}
stages:
  - id: first
    kind: agent_turn
    role: worker
    brief: first
    output: {name: areas, schema: {type: array}}
  - id: fan
    kind: fanout
    branches_from: areas
    output: done
    branch:
      stages:
        - id: work
          kind: agent_turn
          role: worker
          brief: "work {{.item}}"
          output: {name: out, schema: {type: string}}
  - id: last
    kind: agent_turn
    role: worker
    brief: "last {{json .artifacts.done}}"
    output: {name: final, schema: {type: array}}
`

func TestResumeAfterInterruption(t *testing.T) {
	tpl := mustParse(t, resumeTemplate)
	sc := mustScenario(t, `
turns:
  - stage: first
    output: [xa, yb, zc]
  - stage: work
    output: "=item"
  - stage: last
    output: "=[brief]"
`)
	p := newProbe(NewScriptExecutor(sc))
	ctx, cancel := context.WithCancel(context.Background())
	interruptAt := 1
	p.hook = func(c context.Context, t Turn) error {
		if t.StageID == "work" && strings.Contains(t.Brief, "yb") && interruptAt > 0 {
			interruptAt--
			cancel()
			<-c.Done()
			return c.Err()
		}
		return nil
	}
	r := newRunner(t, p)
	rec, err := r.Run(ctx, Admission{Template: tpl, ID: "job"})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v, want context.Canceled", err)
	}
	wantState(t, rec, StateInterrupted)
	stored, _ := r.Store.Load("job")
	if stored.State != StateInterrupted || stored.Stages["first"].State != StateDone || stored.Stages["fan"].State != StatePending {
		t.Fatalf("stored = %s first %s fan %s", stored.State, stored.Stages["first"].State, stored.Stages["fan"].State)
	}
	if b := stored.Stages["fan"].Branches; b[0].State != StateDone || b[1].State != StatePending {
		t.Fatalf("branches = %s %s", b[0].State, b[1].State)
	}

	rec, err = r.Run(context.Background(), Admission{Template: tpl, ID: "job"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
	if n := p.count("first"); n != 1 {
		t.Errorf("first ran %d times, want 1", n)
	}
	if n := p.count("work"); n != 4 { // x, y (interrupted), y, z
		t.Errorf("work ran %d times, want 4", n)
	}
	if got := artifact(t, r, "job", "done"); !reflect.DeepEqual(got, []any{"xa", "yb", "zc"}) {
		t.Errorf("done = %v", got)
	}
	evs, _ := r.Store.Events("job")
	resumed := false
	for _, e := range evs {
		resumed = resumed || e.Type == "resumed"
	}
	if !resumed {
		t.Error("no resumed event")
	}
}

const oracleTemplate = `
id: oracle
roles:
  oracle: {cap: 1, cap_scope: %s}
stages:
  - id: one
    kind: agent_turn
    role: oracle
    brief: one
    output: {name: a, schema: {type: object}}
  - id: two
    kind: agent_turn
    role: oracle
    brief: two
    output: {name: b, schema: {type: object}}
`

func TestCapScopeTreeLetsTwoTreesRunOracles(t *testing.T) {
	for _, tc := range []struct {
		scope         string
		total, inTree int
	}{{"tree", 2, 1}, {"workflow", 1, 1}, {"task", 2, 1}} {
		tpl := mustParse(t, fmt.Sprintf(oracleTemplate, tc.scope))
		p := newProbe(NewScriptExecutor(nil))
		p.delay = func(Turn, TurnInfo) time.Duration { return 40 * time.Millisecond }
		r := newRunner(t, p)
		var wg sync.WaitGroup
		for _, id := range []string{"t1", "t2"} {
			wg.Add(1)
			go func(id string) {
				defer wg.Done()
				rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: id})
				if err != nil {
					t.Error(err)
					return
				}
				wantState(t, rec, StateDone)
			}(id)
		}
		wg.Wait()
		if got := p.maxOf("oracle"); got != tc.total {
			t.Errorf("%s: %d oracle turns at once, want %d", tc.scope, got, tc.total)
		}
		for _, id := range []string{"t1", "t2"} {
			if got := p.maxOf(id + "/oracle"); got != tc.inTree {
				t.Errorf("%s: %d oracle turns at once in %s, want %d", tc.scope, got, id, tc.inTree)
			}
		}
	}
}

func TestMaxParallel(t *testing.T) {
	tpl := mustParse(t, fmt.Sprintf(fanTemplate, 64, "all"))
	p := newProbe(NewScriptExecutor(mustScenario(t, fmt.Sprintf(areaScript, items(8)))))
	p.delay = func(Turn, TurnInfo) time.Duration { return 20 * time.Millisecond }
	r := newRunner(t, p)
	r.MaxParallel = 3
	rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: "root"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
	if got := p.maxOf("coder"); got != 3 {
		t.Errorf("max in flight = %d, want 3", got)
	}
}

// FAE-WF-103's acceptance: 3 areas in parallel, one zoomed recursively; the
// child's mapped output lands in the root's join artifact.
func TestFanoutOfSubworkflowsAndGateOnDepth(t *testing.T) {
	tpl := mustParse(t, `
id: pipeline
produces: artifacts
recursion: {max_depth: 4, max_children_per_visit: 3}
inputs:
  scope: {type: string, default: system}
outputs:
  areas_out: {type: array}
roles: {inventory: {}, coder: {cap: 3}}
stages:
  - id: shallow
    kind: gate
    expr: tree.depth < 2
    on_fail: leaf
  - id: inventory
    kind: agent_turn
    role: inventory
    after: [shallow]
    brief: "inventory {{.inputs.scope}}"
    output: {name: areas, schema: {type: array}}
  - id: areas
    kind: fanout
    branches_from: areas
    parallel: true
    output: areas_out
    branch:
      output: result
      stages:
        - id: model
          kind: agent_turn
          role: coder
          brief: "area {{.item.name}}"
          output: {name: area_model, schema: {type: object}}
        - id: zoom
          kind: subworkflow
          workflow: self
          inputs: {scope: item.name}
          outputs: {child: areas_out}
          on_fail: plain
        - id: plain
          kind: gate
          expr: "true"
        - id: result
          kind: agent_turn
          role: coder
          inputs: [area_model]
          after: [zoom]
          brief: "result {{.item.name}}"
          output: {name: result, schema: {type: object}}
  - id: leaf
    kind: agent_turn
    role: coder
    brief: leaf
    output: {name: areas_out, schema: {type: array}}
`)
	if err := Validate(tpl, nil); err != nil {
		t.Fatal(err)
	}
	sc := mustScenario(t, `
turns:
  - stage: inventory
    output: [{name: api}, {name: store}, {name: worker}]
  - stage: model
    output: "={'area': item.name}"
  - stage: result
    output: "={'area': item.name, 'depth': depth}"
  - stage: leaf
    output: "=[{'leaf': task}]"
`)
	r := newRunner(t, NewScriptExecutor(sc))
	rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: "sim"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
	tree, _ := ReadTree(r.Store, "sim")
	if tree.Tasks != 4 || len(tree.Root.Children) != 3 {
		t.Fatalf("tree: %d tasks, %d children", tree.Tasks, len(tree.Root.Children))
	}
	for i, c := range tree.Root.Children {
		if want := fmt.Sprintf("sim.zoom.1.%d", i); c.ID != want || c.State != StateDone {
			t.Errorf("child %d = %s %s, want %s done", i, c.ID, c.State, want)
		}
	}
	// Each child's gate fails at depth 2, so it routes to leaf.
	child, _ := r.Store.Load("sim.zoom.1.1")
	if child.Stages["shallow"].RoutedTo != "leaf" || child.Stages["inventory"].State != StateSkipped {
		t.Errorf("child stages: shallow %+v inventory %+v", child.Stages["shallow"], child.Stages["inventory"])
	}
	if got := artifact(t, r, "sim", "areas/1/child"); !reflect.DeepEqual(got, []any{map[string]any{"leaf": "sim.zoom.1.1"}}) {
		t.Errorf("mapped child output = %v", got)
	}
	out := artifact(t, r, "sim", "areas_out").([]any)
	if len(out) != 3 || out[2].(map[string]any)["area"] != "worker" {
		t.Errorf("areas_out = %v", out)
	}
	var b strings.Builder
	tree.WriteText(&b)
	if !strings.Contains(b.String(), "└── sim.zoom.1.2") {
		t.Errorf("tree text:\n%s", b.String())
	}
}

func TestMaxChildrenPerVisit(t *testing.T) {
	tpl := mustParse(t, `
id: wide
recursion: {max_depth: 2, max_children_per_visit: 2}
inputs: {n: {type: integer, default: 0}}
outputs: {got: {type: array}}
roles: {r: {}}
stages:
  - id: list
    kind: agent_turn
    role: r
    brief: list
    output: {name: list, schema: {type: array}}
  - id: fan
    kind: fanout
    branches_from: list
    output: got
    branch:
      stages:
        - id: sub
          kind: subworkflow
          workflow: self
          inputs: {n: item}
          outputs: {sub_got: got}
`)
	sc := mustScenario(t, `
turns:
  - stage: list
    task: root
    output: [1, 2, 3]
  - stage: list
    output: []
`)
	r := newRunner(t, NewScriptExecutor(sc))
	rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: "root"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateFailed)
	if rec.Reason != ReasonBranchFailed {
		t.Errorf("root reason %s", rec.Reason)
	}
	b := rec.Stages["fan"].Branches
	if b[0].State != StateDone || b[1].State != StateDone || b[2].State != StateFailed {
		t.Fatalf("branches %s %s %s", b[0].State, b[1].State, b[2].State)
	}
	if b[2].Reason != ReasonRecursionBudget {
		t.Errorf("branch 2 reason %s", b[2].Reason)
	}
}

func TestCommandAndScriptedCommand(t *testing.T) {
	tpl := mustParse(t, `
id: cmd
stages:
  - id: echo
    kind: command
    argv: [sh, -c, "echo hi; exit 3"]
  - id: scripted
    kind: command
    argv: ["false"]
  - id: check
    kind: gate
    expr: artifacts.echo.exit == 3 && artifacts.echo.stdout == 'hi\n' && artifacts.scripted.stdout == 'false'
`)
	sc := mustScenario(t, `
commands:
  - stage: scripted
    output: "={'exit': 0, 'stdout': argv[0], 'stderr': ''}"
`)
	r := newRunner(t, NewScriptExecutor(sc))
	rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: "c"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
}

func TestValidationListsAllErrors(t *testing.T) {
	_, err := Parse([]byte(`
id: bad.id
recursion: {max_depth: 9}
roles: {coder: {cap_scope: galaxy}}
outputs: {missing: {type: string}}
stages:
  - id: a
    kind: agent_turn
    role: nobody
    brief: "{{.artifacts.ghost}}"
    output: {name: x, schema: {type: string}}
    colour: red
  - id: f
    kind: fanout
    branches_from: x
    max_branches: 2000
    join: some
    branch:
      stages:
        - id: g
          kind: gate
          expr: "1 +"
        - id: inner
          kind: fanout
          branches_from: x
          branch: {stages: [{id: q, kind: gate, expr: "true"}]}
  - id: s
    kind: subworkflow
    workflow: self
    on_fail: nowhere
  - kind: teleport
`))
	var ve *ValidationError
	if !errors.As(err, &ve) {
		t.Fatalf("err = %v", err)
	}
	want := []string{
		"id: must match",
		"recursion.max_depth: 9 exceeds the instance ceiling 8",
		"roles.coder.cap_scope: must be workflow, tree or task",
		"stages[0].colour: unknown field",
		"stages[1].max_branches: must be between 1 and 1024",
		"stages[1].join: must be all, any or {k: N}",
		"stages[1].branch.stages[0].expr:",
		"stages[1].branch.stages[1]: a fanout branch can't contain a fanout",
		"stages[3].kind: unknown kind teleport",
		"stages[3].id: is required",
	}
	text := ve.Error()
	for _, w := range want {
		if !strings.Contains(text, w) {
			t.Errorf("missing %q in:\n%s", w, text)
		}
	}

	// Graph errors once the structure is sound.
	_, err = Parse([]byte(`
id: graph
outputs: {missing: {type: string}}
roles: {coder: {}}
stages:
  - id: a
    kind: agent_turn
    role: nobody
    brief: "{{.artifacts.ghost}} {{.artifacts.yy}}"
    output: {name: xx, schema: {type: string}}
  - id: b
    kind: agent_turn
    role: coder
    brief: "{{.artifacts.xx}}"
    output: {name: yy, schema: {type: string}}
  - id: s
    kind: subworkflow
    workflow: self
    on_fail: nowhere
`))
	if !errors.As(err, &ve) {
		t.Fatalf("err = %v", err)
	}
	text = ve.Error()
	for _, w := range []string{
		`stages[0].role: role "nobody" is not declared`,
		`stages[0]: binding "ghost": no input or stage produces it`,
		`dependency cycle`,
		`stages[2].on_fail: no stage "nowhere"`,
		`stages[2].workflow: a template that selects itself must declare recursion`,
		`outputs.missing: no top-level stage produces "missing"`,
	} {
		if !strings.Contains(text, w) {
			t.Errorf("missing %q in:\n%s", w, text)
		}
	}
}

func TestValidateSubworkflowSignature(t *testing.T) {
	child := mustParse(t, childTemplate)
	parent := mustParse(t, `
id: caller
roles: {}
stages:
  - id: call
    kind: subworkflow
    workflow: component
    inputs: {extra: "=1"}
    outputs: {m: nonexistent}
`)
	err := Validate(parent, DirResolver(t.TempDir(), child))
	if err == nil {
		t.Fatal("want errors")
	}
	for _, w := range []string{`required input "contract"`, `declares no input "extra"`, `declares no output "nonexistent"`} {
		if !strings.Contains(err.Error(), w) {
			t.Errorf("missing %q in %v", w, err)
		}
	}
	// Mutual recursion without budgets is refused.
	a := mustParse(t, "id: a\nstages: [{id: s, kind: subworkflow, workflow: b}]")
	b := mustParse(t, "id: b\nstages: [{id: s, kind: subworkflow, workflow: a}]")
	if err := Validate(a, DirResolver(t.TempDir(), a, b)); err == nil || !strings.Contains(err.Error(), "mutual recursion") {
		t.Errorf("mutual recursion: %v", err)
	}
}

func TestRegistry(t *testing.T) {
	ex := NewScriptExecutor(nil)
	Register("test-script", ex)
	got, ok := Lookup("test-script")
	if !ok || got != Executor(ex) {
		t.Fatal("lookup failed")
	}
}

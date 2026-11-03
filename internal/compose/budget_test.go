package compose

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"
)

// recorder is a TurnObserver for executor tests.
type recorder struct {
	mu       sync.Mutex
	stats    []SessionStats
	warnings []string
}

func (r *recorder) SessionStats(s SessionStats) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.stats = append(r.stats, s)
}

func (r *recorder) Warning(msg string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.warnings = append(r.warnings, msg)
}

func result(session string, turns int, ms int64, cost float64) string {
	b, _ := json.Marshal(map[string]any{"type": "result", "subtype": "success", "is_error": false, "result": "done",
		"session_id": session, "num_turns": turns, "duration_ms": ms, "total_cost_usd": cost})
	return string(b)
}

func TestBudgetTemplateValidation(t *testing.T) {
	tpl := mustParse(t, `
id: b
roles: {r: {cap: 4}}
stages:
  - id: a
    kind: agent_turn
    role: r
    brief: x
    budget: {max_turns: 40, timeout_min: 1.5}
    output: {name: o, schema: {type: object}}
`)
	if b := tpl.Stages[0].Budget; b == nil || b.MaxTurns != 40 || b.Timeout != 90*time.Second {
		t.Fatalf("budget = %+v", b)
	}
	_, err := Parse([]byte(`
id: b
roles: {r: {cap: 4}}
stages:
  - id: a
    kind: agent_turn
    role: r
    brief: x
    budget: {max_turns: 0, timeout_min: -1, tokens: 3}
    output: {name: o, schema: {type: object}}
  - id: g
    kind: gate
    expr: "true"
    budget: {max_turns: 3}
`))
	if err == nil {
		t.Fatal("bad budgets validate")
	}
	for _, want := range []string{"budget.max_turns: must be at least 1", "budget.timeout_min: must be positive",
		"budget.tokens: unknown field", "stages[1].budget: unknown field"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("errors lack %q:\n%v", want, err)
		}
	}
}

func TestClaudeExecutorStatsAndMaxTurns(t *testing.T) {
	// Stats per attempt, a schema retry included; --max-turns when --help lists it.
	f := newFake(t, `FAKE_OUT_1={"areas": []}`, `FAKE_OUT_2={"areas": [{"id": "api"}]}`,
		"FAKE_RESULT_1="+result("s1", 7, 1200, 0.25), "FAKE_RESULT_2="+result("s2", 3, 800, 0.5),
		"FAKE_HELP=  --max-turns <n>  Maximum agentic turns", MaxTurnsFlagEnv+"=")
	rec := &recorder{}
	tr := turn(f)
	tr.MaxTurns = 5
	if _, err := f.exec.Run(WithTurnObserver(context.Background(), rec), tr); err != nil {
		t.Fatal(err)
	}
	if len(rec.stats) != 2 || len(rec.warnings) != 0 {
		t.Fatalf("stats %+v, warnings %v", rec.stats, rec.warnings)
	}
	s := rec.stats[1]
	if s.Attempt != 2 || s.SessionID != "s2" || s.NumTurns != 3 || s.DurationMS != 800 || s.CostUSD != 0.5 || s.Subtype != "success" || s.IsError {
		t.Fatalf("attempt 2 stats = %+v", s)
	}
	if !strings.Contains(strings.Join(f.argv(t, 1), " "), "--max-turns 5") {
		t.Fatalf("argv lacks --max-turns: %q", f.argv(t, 1))
	}

	// Without the flag in --help: no flag; the executor streams the events
	// and counts the turns itself (executor_claude_test.go covers the count).
	g := newFake(t, `FAKE_OUT_1={"areas": [{"id": "api"}]}`, MaxTurnsFlagEnv+"=")
	rec = &recorder{}
	tr = turn(g)
	tr.MaxTurns = 5
	if _, err := g.exec.Run(WithTurnObserver(context.Background(), rec), tr); err != nil {
		t.Fatal(err)
	}
	if argv := strings.Join(g.argv(t, 1), " "); strings.Contains(argv, "--max-turns") ||
		!strings.Contains(argv, "--output-format stream-json --verbose") || len(rec.warnings) != 0 {
		t.Fatalf("argv %q, warnings %v", argv, rec.warnings)
	}

	// The env override forces it without probing.
	h := newFake(t, `FAKE_OUT_1={"areas": [{"id": "api"}]}`, MaxTurnsFlagEnv+"=1")
	tr = turn(h)
	tr.MaxTurns = 9
	if _, err := h.exec.Run(context.Background(), tr); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(strings.Join(h.argv(t, 1), " "), "--max-turns 9") {
		t.Fatalf("argv lacks --max-turns: %q", h.argv(t, 1))
	}

	// Running out of turns is a budget failure.
	m := newFake(t, `FAKE_RESULT={"type":"result","subtype":"error_max_turns","is_error":true,"num_turns":9,"session_id":"s9"}`)
	if _, err := m.exec.Run(context.Background(), turn(m)); !errors.Is(err, ErrBudget) {
		t.Fatalf("err = %v, want ErrBudget", err)
	}
}

const budgetTemplate = `
id: budgeted
roles: {r: {cap: 4}}
stages:
  - id: slow
    kind: agent_turn
    role: r
    brief: think hard
    budget: {timeout_min: 0.005}
    output: {name: plan, schema: {type: object}}
    on_fail: handle
  - id: handle
    kind: gate
    expr: "artifacts.failure.reason == 'budget'"
`

func TestBudgetTimeoutFailsWithBudgetAndRoutes(t *testing.T) {
	f := newFake(t, "FAKE_TARGET=", "FAKE_SLEEP=20", `FAKE_OUT={}`)
	r := newRunner(t, f.exec)
	r.Dir = f.work
	start := time.Now()
	rec, err := r.Run(context.Background(), Admission{Template: mustParse(t, budgetTemplate), ID: "root"})
	if err != nil {
		t.Fatal(err)
	}
	if d := time.Since(start); d > 10*time.Second {
		t.Fatalf("the timeout did not stop the session: %s", d)
	}
	wantState(t, rec, StateDone)
	ss := rec.Stages["slow"]
	if ss.State != StateFailed || ss.Reason != ReasonBudget || ss.RoutedTo != "handle" || !strings.Contains(ss.Error, "timeout") {
		t.Fatalf("slow = %+v", ss)
	}
	if h := rec.Stages["handle"]; h.State != StateDone {
		t.Fatalf("handle = %+v", h)
	}
	m, err := r.Store.ReadTurnMeta("root", "slow")
	if err != nil || m == nil || len(m.Attempts) != 1 || m.Attempts[0].Error == "" {
		t.Fatalf("meta = %+v, %v", m, err)
	}
}

const statsTemplate = `
id: stats
roles: {r: {cap: 4}}
stages:
  - id: plan
    kind: agent_turn
    role: r
    brief: plan
    output: {name: areas, schema: {type: array}}
  - id: areas
    kind: fanout
    branches_from: areas
    output: results
    branch:
      stages:
        - id: build
          kind: agent_turn
          role: r
          brief: "build {{.item}}"
          output: {name: result, schema: {type: object}}
`

func TestStatsWrittenAndSummedInTree(t *testing.T) {
	// Every session reports 4 turns, 1000 ms and $0.25. plan's first
	// attempt writes a non-list and is retried: 2 sessions. Two branches,
	// one session each: 4 sessions in all.
	f := newFake(t, "FAKE_TARGET=", `FAKE_OUT_1={"not":"a list"}`, `FAKE_OUT_2=["a","b"]`, `FAKE_OUT={"ok":true}`,
		"FAKE_RESULT="+result("s", 4, 1000, 0.25))
	r := newRunner(t, f.exec)
	r.Dir = f.work
	rec, err := r.Run(context.Background(), Admission{Template: mustParse(t, statsTemplate), ID: "root"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)

	plan, err := r.Store.ReadTurnMeta("root", "plan")
	if err != nil || plan == nil || len(plan.Attempts) != 2 {
		t.Fatalf("plan meta = %+v, %v", plan, err)
	}
	if a := plan.Attempts[1]; a.Turn != 1 || a.Attempt != 2 || a.NumTurns != 4 || a.DurationMS != 1000 || a.CostUSD != 0.25 || a.SessionID != "s" {
		t.Fatalf("plan attempt 2 = %+v", a)
	}
	if b, err := r.Store.ReadTurnMeta("root", "areas/1/build"); err != nil || b == nil || len(b.Attempts) != 1 {
		t.Fatalf("branch meta = %+v, %v", b, err)
	}
	evs, _ := r.Store.Events("root")
	n := 0
	for _, ev := range evs {
		if ev.Type == "turn_stats" {
			n++
			if ev.Data["num_turns"] != float64(4) {
				t.Fatalf("turn_stats event = %+v", ev)
			}
		}
	}
	if n != 4 {
		t.Fatalf("%d turn_stats events, want 4", n)
	}

	tree, err := ReadTree(r.Store, "root")
	if err != nil {
		t.Fatal(err)
	}
	if err := tree.AddStats(r.Store); err != nil {
		t.Fatal(err)
	}
	want := AgentStats{Sessions: 4, NumTurns: 16, DurationMS: 4000, CostUSD: 1}
	if tree.Stats.Agent != want || tree.Root.Stats.Agent != want {
		t.Fatalf("tree %+v, root %+v, want %+v", tree.Stats.Agent, tree.Root.Stats.Agent, want)
	}
	st := tree.Root.Stats.Stages
	if len(st) != 2 || st[0].Stage != "plan" || st[1].Stage != "areas" || st[1].Branches != 2 ||
		*st[0].Agent != (AgentStats{Sessions: 2, NumTurns: 8, DurationMS: 2000, CostUSD: 0.5}) ||
		*st[1].Agent != (AgentStats{Sessions: 2, NumTurns: 8, DurationMS: 2000, CostUSD: 0.5}) {
		t.Fatalf("stages = %+v", st)
	}
	var out bytes.Buffer
	tree.WriteText(&out)
	if !strings.Contains(out.String(), "tree: wall") || !strings.Contains(out.String(), "4 session(s), 16 turn(s), agent 4s, $1.00") {
		t.Fatalf("text:\n%s", out.String())
	}
}

func TestTreeStatsWallTimeAndChildren(t *testing.T) {
	// A hand-made store: exact event times, a child task, an old run
	// without meta files, and an interrupted-then-resumed stage.
	s := NewStore(t.TempDir())
	tpl := mustParse(t, statsTemplate)
	t0 := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	at := func(sec int) time.Time { return t0.Add(time.Duration(sec) * time.Second) }
	for _, rec := range []*RunRecord{
		{ID: "root", Workflow: "stats", Template: tpl.Raw, TreeRoot: "root", Depth: 1, State: StateDone},
		{ID: "root.zoom.1", Workflow: "stats", Template: tpl.Raw, Parent: "root", TreeRoot: "root", Depth: 2, State: StateDone},
	} {
		if err := s.Save(rec); err != nil {
			t.Fatal(err)
		}
	}
	ev := func(task string, sec int, typ, stage string) {
		parent := ""
		if task != "root" {
			parent = "root"
		}
		s.AppendEvent(task, Event{Time: at(sec), Type: typ, Task: task, ParentTask: parent, TreeRoot: "root", Stage: stage})
	}
	ev("root", 0, "started", "")
	ev("root", 0, "stage_started", "plan")
	ev("root", 60, "resumed", "") // plan was interrupted at 60 s and restarted
	ev("root", 60, "stage_started", "plan")
	ev("root", 90, "stage_finished", "plan")
	ev("root", 90, "stage_started", "areas")
	ev("root", 90, "stage_started", "areas/0/build")
	ev("root", 91, "stage_started", "areas/1/build")
	ev("root", 150, "stage_finished", "areas/0/build")
	ev("root", 200, "stage_finished", "areas/1/build")
	ev("root", 200, "stage_finished", "areas")
	ev("root", 210, "finished", "")
	ev("root.zoom.1", 100, "started", "")
	ev("root.zoom.1", 100, "stage_started", "plan")
	ev("root.zoom.1", 400, "stage_finished", "plan")
	ev("root.zoom.1", 400, "finished", "")
	for _, m := range []*TurnMeta{
		{Task: "root", Stage: "plan", Attempts: []SessionStats{{Turn: 1, Attempt: 1, NumTurns: 2, DurationMS: 500, CostUSD: 0.1}, {Turn: 2, Attempt: 1, NumTurns: 3, DurationMS: 700, CostUSD: 0.2}}},
		{Task: "root", Stage: "areas/0/build", Attempts: []SessionStats{{Turn: 1, Attempt: 1, NumTurns: 10, DurationMS: 50000, CostUSD: 1.5}}},
		{Task: "root", Stage: "areas/1/build", Attempts: []SessionStats{{Turn: 1, Attempt: 1, NumTurns: 20, DurationMS: 90000, CostUSD: 2.5}}},
	} {
		if err := s.WriteTurnMeta(m); err != nil {
			t.Fatal(err)
		}
	}
	tree, err := ReadTree(s, "root")
	if err != nil {
		t.Fatal(err)
	}
	if err := tree.AddStats(s); err != nil {
		t.Fatal(err)
	}
	root := tree.Root.Stats
	if root.WallMS != 210000 {
		t.Fatalf("root wall = %d", root.WallMS)
	}
	if p := root.Stages[0]; p.Stage != "plan" || p.WallMS != 90000 || p.Agent.Sessions != 2 || p.Agent.NumTurns != 5 {
		t.Fatalf("plan = %+v %+v", p, p.Agent)
	}
	if a := root.Stages[1]; a.Stage != "areas" || a.WallMS != 110000 || a.Branches != 2 ||
		*a.Agent != (AgentStats{Sessions: 2, NumTurns: 30, DurationMS: 140000, CostUSD: 4}) {
		t.Fatalf("areas = %+v %+v", a, a.Agent)
	}
	child := tree.Root.Children[0].Stats
	if child.WallMS != 300000 || child.Agent.Sessions != 0 || child.Stages[0].Agent != nil || child.Stages[0].WallMS != 300000 {
		t.Fatalf("child = %+v", child)
	}
	if tree.Stats.WallMS != 400000 || tree.Stats.Agent.NumTurns != 35 || tree.Stats.Agent.Sessions != 4 {
		t.Fatalf("tree = %+v", tree.Stats)
	}
	var out bytes.Buffer
	tree.WriteText(&out)
	for _, want := range []string{"stats: wall 3m30s; 4 session(s), 35 turn(s)", "areas  wall    1m50s  2 session(s), 30 turn(s), agent 2m20s, $4.00  (2 branch(es))",
		"stats: wall 5m0s\n", "tree: wall 6m40s; 4 session(s)"} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("text lacks %q:\n%s", want, out.String())
		}
	}
}

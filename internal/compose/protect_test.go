package compose

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// execFunc is an Executor from a function.
type execFunc func(ctx context.Context, t Turn) (json.RawMessage, error)

func (f execFunc) Run(ctx context.Context, t Turn) (json.RawMessage, error) { return f(ctx, t) }

const scopeTemplate = `
id: scoped
produces: artifacts
roles: {r: {cap: 1}}
stages:
  - id: write
    kind: agent_turn
    role: r
    brief: write something
    output: {name: note, schema: {type: object}}
    on_fail: handle
  - id: handle
    kind: gate
    expr: "artifacts.failure.reason == 'write_scope'"
`

func TestWriteOutsideScopeFailsWithWriteScope(t *testing.T) {
	var scope []string
	r := newRunner(t, execFunc(func(ctx context.Context, tr Turn) (json.RawMessage, error) {
		scope = tr.WriteScope
		// Inside the scope: the output directory and the artifact.
		if err := os.WriteFile(filepath.Join(scope[0], "ok.txt"), []byte("fine"), 0o644); err != nil {
			return nil, err
		}
		// Outside it: the repo.
		if err := os.WriteFile(filepath.Join(tr.Dir, "stray.txt"), []byte("no"), 0o644); err != nil {
			return nil, err
		}
		return json.RawMessage(`{}`), nil
	}))
	rec, err := r.Run(context.Background(), Admission{Template: mustParse(t, scopeTemplate), ID: "root"})
	if err != nil {
		t.Fatal(err)
	}
	wantState(t, rec, StateDone)
	ss := rec.Stages["write"]
	if ss.State != StateFailed || ss.Reason != ReasonWriteScope || ss.RoutedTo != "handle" || !strings.Contains(ss.Error, "created stray.txt") {
		t.Fatalf("write = %+v", ss)
	}
	if strings.Contains(ss.Error, "ok.txt") {
		t.Fatalf("a write inside the scope was reported: %s", ss.Error)
	}
	if h := rec.Stages["handle"]; h.State != StateDone {
		t.Fatalf("handle = %+v", h)
	}
	if len(scope) != 2 || scope[0] != rec.OutDir || !strings.HasSuffix(scope[1], filepath.Join("turns", "write.json")) {
		t.Fatalf("write scope = %v", scope)
	}
}

func TestWriteInsideScopePasses(t *testing.T) {
	r := newRunner(t, execFunc(func(ctx context.Context, tr Turn) (json.RawMessage, error) {
		// The repo's .mosaic/ is not watched.
		os.MkdirAll(filepath.Join(tr.Dir, ".mosaic", "x"), 0o755)
		if err := os.WriteFile(filepath.Join(tr.WriteScope[0], "ok.txt"), []byte("fine"), 0o644); err != nil {
			return nil, err
		}
		return json.RawMessage(`{}`), nil
	}))
	rec, err := r.Run(context.Background(), Admission{Template: mustParse(t, scopeTemplate), ID: "root"})
	if err != nil {
		t.Fatal(err)
	}
	if ss := rec.Stages["write"]; ss.State != StateDone {
		t.Fatalf("write = %+v", ss)
	}
}

func TestNoWriteScopeWithoutArtifacts(t *testing.T) {
	r := newRunner(t, execFunc(func(ctx context.Context, tr Turn) (json.RawMessage, error) {
		if tr.WriteScope != nil {
			t.Errorf("write scope %v on a template without produces: artifacts", tr.WriteScope)
		}
		return json.RawMessage(`{}`), os.WriteFile(filepath.Join(tr.Dir, "free.txt"), nil, 0o644)
	}))
	rec, err := r.Run(context.Background(), Admission{Template: mustParse(t, strings.Replace(scopeTemplate, "produces: artifacts\n", "", 1)), ID: "root"})
	if err != nil {
		t.Fatal(err)
	}
	if ss := rec.Stages["write"]; ss.State != StateDone {
		t.Fatalf("write = %+v", ss)
	}
}

func TestClaudeArgsRestrictWritesToScope(t *testing.T) {
	work, out := t.TempDir(), t.TempDir()
	artifact := filepath.Join(work, ".mosaic", "turns", "s.json")
	c := &ClaudeExecutor{}
	args := c.args(Turn{
		Dir: work, Tools: []string{"Read", "Write", "Edit(docs/**)", "Bash(mosaic *)", "MultiEdit"},
		WriteScope: []string{out, artifact},
	}, false)
	got := strings.Join(args, " ")
	want := "--allowedTools=Read,Bash(mosaic *)," +
		"Write(/" + out + "/**),Edit(/" + out + "/**)," +
		"Write(/" + artifact + "),Edit(/" + artifact + ")" +
		" --add-dir=" + out
	if !strings.Contains(got, want) {
		t.Fatalf("args = %s\nwant %s", got, want)
	}
}

const capTemplate = `
id: capped
roles: {r: {cap: 1}}
stages:
  - id: a
    kind: agent_turn
    role: r
    brief: a
    output: {name: a, schema: {type: object}}
  - id: b
    kind: agent_turn
    role: r
    brief: b
    output: {name: b, schema: {type: object}}
`

// Two Runners on one store stand for two `mosaic compose` processes: their
// role cap of 1 holds across both.
func TestRoleCapSharedAcrossRunners(t *testing.T) {
	var inflight, peak, calls atomic.Int32
	ex := execFunc(func(ctx context.Context, tr Turn) (json.RawMessage, error) {
		n := inflight.Add(1)
		defer inflight.Add(-1)
		for {
			p := peak.Load()
			if n <= p || peak.CompareAndSwap(p, n) {
				break
			}
		}
		calls.Add(1)
		time.Sleep(30 * time.Millisecond)
		return json.RawMessage(`{}`), nil
	})
	root := filepath.Join(t.TempDir(), "runs")
	tpl := mustParse(t, capTemplate)
	var wg sync.WaitGroup
	for i, id := range []string{"one", "two"} {
		r := &Runner{Store: NewStore(root), Executor: ex, Dir: t.TempDir()}
		wg.Add(1)
		go func(i int, id string) {
			defer wg.Done()
			rec, err := r.Run(context.Background(), Admission{Template: tpl, ID: id})
			if err != nil {
				t.Error(err)
				return
			}
			if rec.State != StateDone {
				t.Errorf("%s: %s %s", id, rec.State, rec.Error)
			}
		}(i, id)
	}
	wg.Wait()
	if calls.Load() != 4 || peak.Load() != 1 {
		t.Fatalf("calls %d, peak in flight %d; want 4 and 1", calls.Load(), peak.Load())
	}
	var doc leaseDoc
	data, err := os.ReadFile(LeasePath(root))
	if err != nil || json.Unmarshal(data, &doc) != nil || len(doc.Leases) != 0 {
		t.Fatalf("leases left: %s (%v)", data, err)
	}
}

func TestStaleLeaseIsReclaimed(t *testing.T) {
	// A pid that has exited.
	cmd := exec.Command("true")
	if err := cmd.Run(); err != nil {
		t.Skip(err)
	}
	dead := cmd.Process.Pid
	root := filepath.Join(t.TempDir(), "runs")
	stale := leaseDoc{Leases: []*Lease{
		{ID: "dead", Key: "workflow/capped/r", Cap: 1, PID: dead, Start: "1", Task: "gone", Acquired: time.Now()},
		// This process's pid with another start time: a reused pid.
		{ID: "reused", Key: "workflow/capped/r", Cap: 1, PID: os.Getpid(), Start: "not-" + processStart(os.Getpid()), Acquired: time.Now()},
	}}
	if processStart(os.Getpid()) == "" {
		stale.Leases = stale.Leases[:1]
	}
	data, _ := json.Marshal(stale)
	if err := os.MkdirAll(filepath.Dir(root), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(LeasePath(root), data, 0o644); err != nil {
		t.Fatal(err)
	}
	r := &Runner{Store: NewStore(root), Executor: execFunc(func(ctx context.Context, tr Turn) (json.RawMessage, error) {
		return json.RawMessage(`{}`), nil
	}), Dir: t.TempDir()}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rec, err := r.Run(ctx, Admission{Template: mustParse(t, capTemplate), ID: "root"})
	if err != nil {
		t.Fatalf("the stale lease blocked the run: %v", err)
	}
	wantState(t, rec, StateDone)
}

func TestLiveLeaseBlocks(t *testing.T) {
	root := filepath.Join(t.TempDir(), "runs")
	path := LeasePath(root)
	release, err := acquireLease(context.Background(), path, "k", 1, "t", "s")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	if _, err := acquireLease(ctx, path, "k", 1, "t", "s"); err == nil {
		t.Fatal("a second lease past the cap was granted")
	}
	release()
	again, err := acquireLease(context.Background(), path, "k", 1, "t", "s")
	if err != nil {
		t.Fatal(err)
	}
	again()
}

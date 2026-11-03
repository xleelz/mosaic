package compose

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"

	"github.com/xleelz/mosaic/internal/jsonschema"
)

func (s *scope) turnInfo(visit int) TurnInfo {
	return TurnInfo{Branch: s.branch, Item: s.item, Depth: s.rc.rec.Depth, Visit: visit}
}

func (s *scope) visitOf(st *Stage) int {
	s.rc.mu.Lock()
	defer s.rc.mu.Unlock()
	return s.states[st.ID].Visit
}

func (s *scope) agentTurn(ctx context.Context, st *Stage) stageResult {
	rc := s.rc
	outPath, err := filepath.Abs(filepath.Join(rc.r.Store.RunDir(rc.rec.ID), "turns", filepath.FromSlash(s.prefix), st.ID+".json"))
	if err != nil {
		return failed(ReasonStage, "%v", err)
	}
	brief, err := s.render(st, st.Brief, map[string]any{"output_path": outPath, "stage": st.ID})
	if err != nil {
		return failed(ReasonStage, "brief: %v", err)
	}
	schema, _ := json.Marshal(st.Output.Schema)
	if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
		return failed(ReasonStage, "%v", err)
	}
	os.Remove(outPath)
	if err := os.MkdirAll(rc.rec.OutDir, 0o755); err != nil {
		return failed(ReasonStage, "%v", err)
	}
	release, err := rc.r.acquire(ctx, rc, st.Role, s.prefix+st.ID)
	if err != nil {
		if ctx.Err() != nil {
			return s.stoppedResult()
		}
		return failed(ReasonExecutor, "role cap: %v", err)
	}
	visit := s.visitOf(st)
	tr := Turn{
		TaskID: rc.rec.ID, StageID: st.ID, Role: st.Role, Brief: brief, OutputPath: outPath,
		OutputSchema: schema, Tools: st.Tools, Model: st.Model, Dir: rc.r.Dir,
	}
	// The budget's clock starts once the turn holds its caps.
	tctx := ctx
	if st.Budget != nil {
		tr.MaxTurns, tr.Timeout = st.Budget.MaxTurns, st.Budget.Timeout
		if tr.Timeout > 0 {
			var cancel context.CancelFunc
			tctx, cancel = context.WithTimeout(ctx, tr.Timeout)
			defer cancel()
		}
	}
	// Templates that produce artifacts may write only their output
	// directory and the artifact (DESIGN §16.7).
	var scope *writeScopeCheck
	if rc.tpl.Produces == "artifacts" {
		tr.WriteScope = []string{rc.rec.OutDir, outPath}
		if scope, err = newWriteScopeCheck(rc.r.Dir, tr.WriteScope, []string{rc.r.Store.Root}); err != nil {
			release()
			return failed(ReasonStage, "%v", err)
		}
	}
	obs := s.newTurnObserver(st, visit)
	raw, err := rc.r.Executor.Run(WithTurnObserver(WithTurnInfo(tctx, s.turnInfo(visit)), obs), tr)
	release()
	if scope != nil && ctx.Err() == nil {
		if verr := scope.verify(); verr != nil {
			return failed(ReasonWriteScope, "%v", verr)
		}
	}
	if err != nil {
		if ctx.Err() != nil {
			return s.stoppedResult()
		}
		if errors.Is(err, ErrWriteScope) {
			return failed(ReasonWriteScope, "%v", err)
		}
		if errors.Is(err, ErrBudget) || errors.Is(tctx.Err(), context.DeadlineExceeded) {
			if tctx.Err() != nil && !errors.Is(err, ErrBudget) {
				err = fmt.Errorf("timeout of %s exceeded: %v", tr.Timeout, err)
			}
			return failed(ReasonBudget, "%v", err)
		}
		return failed(ReasonExecutor, "%v", err)
	}
	v, err := decodeJSON(raw)
	if err != nil {
		return failed(ReasonSchema, "output %s is not JSON: %v", st.Output.Name, err)
	}
	if errs := jsonschema.Validate(st.Output.Schema, v, nil); len(errs) > 0 {
		return failed(ReasonSchema, "output %s: %v", st.Output.Name, errs)
	}
	if err := s.put(st.ID, st.Output.Name, raw, "stage:"+s.prefix+st.ID); err != nil {
		return failed(ReasonStage, "%v", err)
	}
	return stageResult{}
}

// turnObserver records an agent_turn's session stats in its meta file and
// as turn_stats events, and its warnings as warning events.
type turnObserver struct {
	s     *scope
	path  string // stage path
	visit int
	mu    sync.Mutex
	turn  int // 0 until the first attempt reports
}

func (s *scope) newTurnObserver(st *Stage, visit int) *turnObserver {
	return &turnObserver{s: s, path: s.prefix + st.ID, visit: visit}
}

func (o *turnObserver) SessionStats(st SessionStats) {
	o.mu.Lock()
	defer o.mu.Unlock()
	r, rec := o.s.rc.r, o.s.rc.rec
	m, err := r.Store.ReadTurnMeta(rec.ID, o.path)
	if err != nil || m == nil {
		m = &TurnMeta{Task: rec.ID, Stage: o.path}
	}
	if o.turn == 0 { // this turn's number: one past the meta file's last
		o.turn = 1
		for _, a := range m.Attempts {
			if a.Turn >= o.turn {
				o.turn = a.Turn + 1
			}
		}
	}
	st.Turn, st.Visit = o.turn, o.visit
	m.Attempts = append(m.Attempts, st)
	if err := r.Store.WriteTurnMeta(m); err != nil {
		r.event(rec, "warning", o.path, map[string]any{"message": fmt.Sprintf("writing turn stats: %v", err)})
	}
	var data map[string]any
	b, _ := json.Marshal(st)
	json.Unmarshal(b, &data)
	r.event(rec, "turn_stats", o.path, data)
}

func (o *turnObserver) Warning(msg string) {
	o.s.rc.r.event(o.s.rc.rec, "warning", o.path, map[string]any{"message": msg})
}

func (s *scope) gate(st *Stage) stageResult {
	ok, err := gateEnv.evalBool(st.Expr, s.activation(st.Expr, st))
	if err != nil {
		return failed(ReasonGate, "expr: %v", err)
	}
	if !ok {
		return failed(ReasonGate, "%s is false", st.Expr)
	}
	return stageResult{}
}

func (s *scope) command(ctx context.Context, st *Stage) stageResult {
	rc := s.rc
	argv := make([]string, len(st.Argv))
	for i, a := range st.Argv {
		x, err := s.render(st, a, nil)
		if err != nil {
			return failed(ReasonCommand, "argv[%d]: %v", i, err)
		}
		argv[i] = x
	}
	var res CommandResult
	scripted := false
	if cs, ok := rc.r.Executor.(CommandScripter); ok {
		r, ok, err := cs.ScriptCommand(WithTurnInfo(ctx, s.turnInfo(s.visitOf(st))), rc.rec.ID, st.ID, argv)
		if err != nil {
			return failed(ReasonCommand, "%v", err)
		}
		res, scripted = r, ok
	}
	if !scripted && !rc.r.DryCommands {
		release, err := rc.r.acquire(ctx, rc, "", s.prefix+st.ID)
		if err != nil {
			return s.stoppedResult()
		}
		cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
		cmd.Dir = rc.r.Dir
		var stdout, stderr bytes.Buffer
		cmd.Stdout, cmd.Stderr = &stdout, &stderr
		err = cmd.Run()
		release()
		if ctx.Err() != nil {
			return s.stoppedResult()
		}
		var ee *exec.ExitError
		switch {
		case errors.As(err, &ee):
			res.Exit = ee.ExitCode()
		case err != nil:
			return failed(ReasonCommand, "%v", err)
		}
		res.Stdout, res.Stderr = stdout.String(), stderr.String()
	}
	raw, _ := json.Marshal(res)
	if err := s.put(st.ID, st.CmdOutput, raw, "stage:"+s.prefix+st.ID); err != nil {
		return failed(ReasonStage, "%v", err)
	}
	return stageResult{}
}

func (s *scope) changeRequest(st *Stage) stageResult {
	rc := s.rc
	r := rc.r
	target := st.Target
	if target == "parent" {
		target = rc.rec.Parent
		if target == "" {
			return failed(ReasonChangeRequest, "task %s has no parent", rc.rec.ID)
		}
	}
	// The target must be an ancestor.
	var trec *RunRecord
	for id := rc.rec.Parent; id != ""; {
		x, err := r.Store.Load(id)
		if err != nil {
			return failed(ReasonChangeRequest, "ancestor %s: %v", id, err)
		}
		if id == target {
			trec = x
			break
		}
		id = x.Parent
	}
	if trec == nil {
		return failed(ReasonChangeRequest, "target %s is not an ancestor of %s", target, rc.rec.ID)
	}
	v, err := s.resolve(st.From, st)
	if err != nil {
		return failed(ReasonChangeRequest, "from: %v", err)
	}
	body, _ := json.Marshal(v)
	id := rc.rec.ID + "." + st.ID
	if s.branch >= 0 {
		id = fmt.Sprintf("%s.%d", id, s.branch)
	}
	req := &ChangeRequest{ID: id, FromTask: rc.rec.ID, FromStage: st.ID, Body: body, State: StatePending, Recorded: r.now(),
		Target: RequestTarget{Task: target, Artifact: st.TargetArtifact}}
	if err := r.Store.AddRequest(req); err != nil {
		return failed(ReasonChangeRequest, "%v", err)
	}
	data := map[string]any{"request": id, "from_task": rc.rec.ID, "artifact": st.TargetArtifact}
	r.Store.AppendEvent(target, Event{Time: r.now(), Type: "change_request", Task: target, ParentTask: trec.Parent, TreeRoot: trec.TreeRoot, Data: data})
	r.event(rc.rec, "change_request_sent", s.prefix+st.ID, map[string]any{"request": id, "target": target})
	rc.update(func() { s.states[st.ID].Request = id })
	return stageResult{}
}

func (s *scope) subworkflow(ctx context.Context, st *Stage) stageResult {
	rc := s.rc
	r := rc.r
	child := rc.tpl
	if st.Workflow != "self" && st.Workflow != rc.tpl.ID {
		if r.Resolve == nil {
			return failed(ReasonAdmission, "no resolver for workflow %s", st.Workflow)
		}
		c, err := r.Resolve(st.Workflow)
		if err != nil {
			return failed(ReasonAdmission, "%v", err)
		}
		child = c
	}
	visit := s.visitOf(st)
	id := fmt.Sprintf("%s.%s.%d", rc.rec.ID, st.ID, visit)
	origin := &Origin{Stage: st.ID, Visit: visit}
	if s.branch >= 0 {
		b := s.branch
		id = fmt.Sprintf("%s.%d", id, b)
		origin.Branch = &b
	}
	var crec *RunRecord
	if r.Store.Exists(id) {
		x, err := r.Store.Load(id)
		if err != nil {
			return failed(ReasonAdmission, "%v", err)
		}
		crec = x
	} else {
		inputs := map[string]json.RawMessage{}
		for _, name := range sortedKeys(st.InputMap) {
			v, err := s.resolve(st.InputMap[name], st)
			if err != nil {
				return failed(ReasonBinding, "inputs.%s: %v", name, err)
			}
			inputs[name], _ = json.Marshal(v)
		}
		x, err := r.admit(Admission{Template: child, ID: id, Inputs: inputs, Parent: rc.rec.ID}, origin, rc.rec, rc.tpl)
		if err != nil {
			var ae *AdmissionError
			if errors.As(err, &ae) {
				r.event(rc.rec, "child_refused", s.prefix+st.ID, map[string]any{"child": id, "reason": ae.Reason, "errors": ae.Errors})
				return failed(ae.Reason, "child %s refused: %v", id, ae.Errors)
			}
			return failed(ReasonAdmission, "%v", err)
		}
		crec = x
	}
	rc.update(func() {
		ss := s.states[st.ID]
		ss.Children = appendUnique(ss.Children, id)
	})
	if crec.State != StateDone {
		x, err := r.execute(ctx, crec, child)
		if ctx.Err() != nil {
			return s.stoppedResult()
		}
		if err != nil {
			return failed(ReasonChildFailed, "child %s: %v", id, err)
		}
		crec = x
	}
	if crec.State != StateDone {
		return failed(ReasonChildFailed, "child %s %s (%s): %s", id, crec.State, crec.Reason, crec.Error)
	}
	for _, art := range sortedKeys(st.OutputMap) {
		out := st.OutputMap[art]
		raw, err := r.Store.ReadArtifact(id, out)
		if err != nil {
			return failed(ReasonChildFailed, "child %s has no output %q", id, out)
		}
		if err := s.put(st.ID, art, raw, "child:"+id+"/"+out); err != nil {
			return failed(ReasonStage, "%v", err)
		}
	}
	return stageResult{}
}

// fanout runs one branch instance per list item (FAE-WF-095..097) and joins
// their outputs in branch order.
func (s *scope) fanout(ctx context.Context, st *Stage) stageResult {
	rc := s.rc
	v, err := s.resolve(st.BranchesFrom, st)
	if err != nil {
		return failed(ReasonBinding, "branches_from: %v", err)
	}
	list, ok := v.([]any)
	if !ok {
		return failed(ReasonBinding, "branches_from %s is %T, not a list", st.BranchesFrom, v)
	}
	n := len(list)
	if n > st.MaxBranches {
		return failed(ReasonMaxBranches, "%s has %d items, more than max_branches %d", st.BranchesFrom, n, st.MaxBranches)
	}
	need := n
	switch st.Join.Mode {
	case "any":
		need = 1
	case "k":
		need = st.Join.K
	}
	var (
		mu              sync.Mutex
		passed, failedN int
		decided, pass   bool
		firstFail       *BranchState
		branches        []*BranchState
		visit           int
		bctx, cancel    = context.WithCancel(ctx)
		wg              sync.WaitGroup
	)
	defer cancel()
	decide := func() {
		if decided {
			return
		}
		switch {
		case passed >= need:
			decided, pass = true, true
		case failedN > n-need:
			decided = true
		}
		if decided {
			cancel()
		}
	}
	rc.update(func() {
		ss := s.states[st.ID]
		visit = ss.Visit
		if ss.Count == nil || *ss.Count != n || len(ss.Branches) != n {
			ss.Count = &n
			ss.Branches = make([]*BranchState, n)
			for i := range ss.Branches {
				ss.Branches[i] = &BranchState{Index: i, State: StatePending, Stages: map[string]*StageState{}}
			}
		}
		branches = ss.Branches
		for _, b := range branches {
			switch b.State {
			case StateDone:
				passed++
			default:
				b.State, b.Reason, b.Error = StatePending, "", ""
				resetStages(b.Stages, st.Branch.Stages)
			}
		}
	})
	mu.Lock()
	decide()
	mu.Unlock()
	runBranch := func(i int) {
		b := branches[i]
		sub := &scope{rc: rc, stages: st.Branch.Stages, states: b.Stages, prefix: fmt.Sprintf("%s%s/%d/", s.prefix, st.ID, i),
			branch: i, item: list[i], visit: visit}
		rc.update(func() { b.State = StateRunning })
		sub.run(bctx)
		mu.Lock()
		defer mu.Unlock()
		rc.update(func() {
			switch {
			case sub.stopped && ctx.Err() != nil:
				b.State = StatePending
			case sub.stopped:
				b.State, b.Reason = StateCancelled, "join decided"
			case sub.fail != nil:
				b.State, b.Reason, b.Error = StateFailed, sub.fail.Reason, fmt.Sprintf("stage %s: %s", sub.fail.Stage, sub.fail.Error)
				failedN++
				if firstFail == nil {
					firstFail = b
				}
			default:
				b.State = StateDone
				passed++
			}
		})
		if b.State == StateCancelled {
			rc.r.event(rc.rec, "branch_cancelled", s.prefix+st.ID, map[string]any{"branch": i})
		}
		decide()
	}
	for i, b := range branches {
		if b.State == StateDone {
			continue
		}
		mu.Lock()
		stop := decided
		mu.Unlock()
		if stop || bctx.Err() != nil {
			break
		}
		if st.Parallel {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				runBranch(i)
			}(i)
		} else {
			runBranch(i)
		}
	}
	wg.Wait()
	if ctx.Err() != nil {
		return s.stoppedResult()
	}
	// Branches never started because the join was decided are cancelled.
	rc.update(func() {
		for _, b := range branches {
			if b.State == StatePending {
				b.State, b.Reason = StateCancelled, "join decided"
			}
		}
	})
	mu.Lock()
	decide()
	ok = decided && pass
	mu.Unlock()
	if !ok {
		if st.Join.Mode == "all" && firstFail != nil {
			return failed(ReasonBranchFailed, "branch %d: %s", firstFail.Index, firstFail.Error)
		}
		return failed(ReasonJoin, "join %s: %d of %d branches passed", st.Join, passed, n)
	}
	joined := []json.RawMessage{}
	rc.mu.Lock()
	for i, b := range branches {
		if b.State != StateDone {
			continue
		}
		key := fmt.Sprintf("%s%s/%d/%s", s.prefix, st.ID, i, st.Branch.Output)
		v, ok := rc.art[key]
		if !ok {
			rc.mu.Unlock()
			return failed(ReasonJoin, "branch %d did not produce %s", i, st.Branch.Output)
		}
		raw, _ := json.Marshal(v)
		joined = append(joined, raw)
	}
	rc.mu.Unlock()
	raw, _ := json.Marshal(joined)
	if err := s.put(st.ID, st.JoinOutput, raw, "join:"+s.prefix+st.ID); err != nil {
		return failed(ReasonStage, "%v", err)
	}
	return stageResult{}
}

package compose

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"text/template"
)

// scope runs one list of stages: a task's top level, or one fanout branch
// instance. A stage starts once its bindings exist and its after stages
// are done; handler stages (on_fail targets) start only when routed to.
type scope struct {
	rc     *runCtx
	stages []*Stage
	states map[string]*StageState
	prefix string // artifact key prefix: "" or "<fanout>/<index>/"
	branch int    // -1 outside a branch
	item   any
	visit  int // the fanout visit, for child ids inside a branch

	fail    *Failure // the first failure not routed to a handler
	stopped bool     // stages were stopped by ctx (interrupted or cancelled)
}

type stageResult struct {
	id     string
	state  string // done, failed, or pending when stopped by ctx
	reason string
	err    string
}

func (s *scope) run(ctx context.Context) {
	hs := handlers(s.stages)
	byID := map[string]*Stage{}
	prod := map[string][]*Stage{}
	for _, st := range s.stages {
		byID[st.ID] = st
		for _, n := range st.produced() {
			prod[n] = append(prod[n], st)
		}
	}
	results := make(chan stageResult)
	running := 0
	rc := s.rc
	for {
		// Start every ready stage; skip those that can never run.
		var start []*Stage
		rc.mu.Lock()
		progress := false
		if s.fail == nil && ctx.Err() == nil {
			for _, st := range s.stages {
				ss := s.states[st.ID]
				if ss.State != StatePending || (hs[st.ID] && ss.Routed == nil) {
					continue
				}
				ready, blocked := s.status(st, prod, byID)
				switch {
				case ready:
					now := rc.r.now()
					ss.State, ss.Started, ss.Finished = StateRunning, &now, nil
					if ss.Visit == 0 {
						ss.Visit = 1
					}
					start = append(start, st)
				case blocked != "":
					ss.State, ss.Reason, ss.Error = StateSkipped, ReasonBinding, blocked
					progress = true
				}
			}
		}
		if len(start) > 0 || progress {
			rc.save()
		}
		rc.mu.Unlock()
		for _, st := range start {
			running++
			rc.r.event(rc.rec, "stage_started", s.prefix+st.ID, nil)
			go func(st *Stage) {
				res := s.runStage(ctx, st)
				res.id = st.ID
				results <- res
			}(st)
		}
		if len(start) > 0 || progress {
			continue
		}
		if running == 0 {
			break
		}
		res := <-results
		running--
		st := byID[res.id]
		rc.update(func() {
			ss := s.states[res.id]
			now := rc.r.now()
			ss.State, ss.Reason, ss.Error, ss.Finished = res.state, res.reason, res.err, &now
			switch res.state {
			case StatePending:
				ss.Finished = nil
				s.stopped = true
			case StateCancelled:
				s.stopped = true
			case StateFailed:
				if st.OnFail != "" && st.OnFail != "fail" {
					ss.RoutedTo = st.OnFail
					if h := s.states[st.OnFail]; h != nil && h.State == StatePending {
						h.Routed = &Failure{Stage: st.ID, Reason: res.reason, Error: res.err}
					}
				} else if s.fail == nil {
					s.fail = &Failure{Stage: s.prefix + st.ID, Reason: res.reason, Error: res.err}
				}
			}
		})
		data := map[string]any{"state": res.state}
		if res.reason != "" {
			data["reason"] = res.reason
		}
		rc.r.event(rc.rec, "stage_finished", s.prefix+st.ID, data)
	}
	if ctx.Err() != nil {
		rc.mu.Lock()
		for _, st := range s.stages {
			ss := s.states[st.ID]
			if (ss.State == StatePending || ss.State == StateRunning) && !(hs[st.ID] && ss.Routed == nil) {
				s.stopped = true
			}
		}
		rc.mu.Unlock()
	}
	// Nothing runs and nothing can start: stages left waiting can't run.
	if s.fail == nil && !s.stopped {
		rc.update(func() {
			for _, st := range s.stages {
				if ss := s.states[st.ID]; ss.State == StatePending {
					ss.State = StateSkipped
					if hs[st.ID] {
						ss.Reason = "not routed"
					} else {
						ss.Reason, ss.Error = ReasonBinding, "bindings never became available"
					}
				}
			}
		})
	}
}

// status reports whether a stage can start, or why it never will. rc.mu is
// held.
func (s *scope) status(st *Stage, prod map[string][]*Stage, byID map[string]*Stage) (bool, string) {
	dead := func(state string) bool {
		return state == StateFailed || state == StateSkipped || state == StateCancelled
	}
	for _, d := range st.deps {
		if (d == "item" && s.branch >= 0) || d == "failure" {
			continue
		}
		if _, ok := s.lookup(d); ok {
			continue
		}
		ps := prod[d]
		if len(ps) == 0 {
			return false, fmt.Sprintf("binding %q is not available", d)
		}
		allDead := true
		for _, p := range ps {
			if !dead(s.states[p.ID].State) {
				allDead = false
			}
		}
		if allDead {
			return false, fmt.Sprintf("binding %q: stage %s did not produce it", d, ps[0].ID)
		}
		return false, ""
	}
	for _, a := range st.After {
		state := s.states[a].State
		if dead(state) {
			return false, fmt.Sprintf("after %s: it %s", a, state)
		}
		if state != StateDone {
			return false, ""
		}
	}
	return true, ""
}

// lookup finds an artifact visible in this scope. rc.mu is held.
func (s *scope) lookup(name string) (any, bool) {
	if s.branch >= 0 {
		if name == "item" {
			return s.item, true
		}
		if v, ok := s.rc.art[s.prefix+name]; ok {
			return v, true
		}
	}
	v, ok := s.rc.art[name]
	return v, ok
}

// visible returns every artifact visible in this scope by name. rc.mu is
// held.
func (s *scope) visible() map[string]any {
	out := map[string]any{}
	for k, v := range s.rc.art {
		if !strings.Contains(k, "/") {
			out[k] = v
		}
	}
	if s.branch >= 0 {
		for k, v := range s.rc.art {
			if rest, ok := strings.CutPrefix(k, s.prefix); ok && !strings.Contains(rest, "/") {
				out[rest] = v
			}
		}
		out["item"] = s.item
	}
	return out
}

// put records an artifact produced by a stage.
func (s *scope) put(stage, name string, raw json.RawMessage, provenance string) error {
	v, err := decodeJSON(raw)
	if err != nil {
		return err
	}
	key := s.prefix + name
	sum, err := s.rc.r.Store.WriteArtifact(s.rc.rec.ID, key, raw)
	if err != nil {
		return err
	}
	s.rc.update(func() {
		s.rc.art[key] = v
		s.rc.rec.Artifacts[key] = &ArtifactMeta{Provenance: provenance, SHA256: sum, Recorded: s.rc.r.now()}
	})
	return nil
}

// tree is the read-only tree value for gates and briefs (FAE-WF-104).
func (s *scope) tree(src string) map[string]any {
	rec := s.rc.rec
	t := map[string]any{"depth": int64(rec.Depth), "root": rec.TreeRoot, "task": rec.ID, "parent": rec.Parent}
	if strings.Contains(src, "remaining_descendants") {
		t["remaining_descendants"] = int64(s.rc.r.remainingDescendants(rec, s.rc.tpl))
	}
	return t
}

// artifactsFor is visible() plus "failure" for a routed handler. rc.mu is
// held.
func (s *scope) artifactsFor(st *Stage) map[string]any {
	arts := s.visible()
	if st != nil {
		if f := s.states[st.ID].Routed; f != nil {
			arts["failure"] = map[string]any{"stage": f.Stage, "reason": f.Reason, "error": f.Error}
		}
	}
	return arts
}

// activation is the variables of gate expressions and "=cel" references.
func (s *scope) activation(src string, st *Stage) map[string]any {
	s.rc.mu.Lock()
	defer s.rc.mu.Unlock()
	act := map[string]any{"artifacts": s.artifactsFor(st), "inputs": s.rc.inputs, "tree": s.tree(src), "item": nil}
	if s.branch >= 0 {
		act["item"] = s.item
	}
	return act
}

// resolve evaluates a reference: "name.path.0.field" or "=cel".
func (s *scope) resolve(ref string, st *Stage) (any, error) {
	if src, ok := strings.CutPrefix(ref, "="); ok {
		return gateEnv.eval(src, s.activation(src, st))
	}
	parts := strings.Split(ref, ".")
	s.rc.mu.Lock()
	arts := s.artifactsFor(st)
	v, ok := arts[parts[0]]
	s.rc.mu.Unlock()
	if !ok {
		return nil, fmt.Errorf("artifact %q is not available", parts[0])
	}
	for i, p := range parts[1:] {
		switch t := v.(type) {
		case map[string]any:
			x, ok := t[p]
			if !ok {
				return nil, fmt.Errorf("%s: no field %q", strings.Join(parts[:i+1], "."), p)
			}
			v = x
		case []any:
			n, err := strconv.Atoi(p)
			if err != nil || n < 0 || n >= len(t) {
				return nil, fmt.Errorf("%s: no index %q", strings.Join(parts[:i+1], "."), p)
			}
			v = t[n]
		default:
			return nil, fmt.Errorf("%s is not an object or list", strings.Join(parts[:i+1], "."))
		}
	}
	return v, nil
}

// render expands a brief or argv template.
func (s *scope) render(st *Stage, src string, extra map[string]any) (string, error) {
	t, err := template.New(st.ID).Option("missingkey=error").Funcs(template.FuncMap{
		"json": func(v any) (string, error) {
			b, err := json.MarshalIndent(v, "", "  ")
			return string(b), err
		},
	}).Parse(src)
	if err != nil {
		return "", err
	}
	s.rc.mu.Lock()
	data := map[string]any{
		"inputs": s.rc.inputs, "artifacts": s.artifactsFor(st), "tree": s.tree(src),
		"task": s.rc.rec.ID, "out_dir": s.rc.rec.OutDir, "branch": int64(s.branch), "item": nil,
	}
	if s.branch >= 0 {
		data["item"] = s.item
	}
	s.rc.mu.Unlock()
	for k, v := range extra {
		data[k] = v
	}
	var b strings.Builder
	if err := t.Execute(&b, data); err != nil {
		return "", err
	}
	return b.String(), nil
}

func failed(reason, format string, a ...any) stageResult {
	return stageResult{state: StateFailed, reason: reason, err: fmt.Sprintf(format, a...)}
}

// stoppedResult is the result of a stage stopped by ctx: back to pending
// when the run was interrupted, cancelled when only its branch was.
func (s *scope) stoppedResult() stageResult {
	if s.rc.rootCtx.Err() != nil {
		return stageResult{state: StatePending}
	}
	return stageResult{state: StateCancelled, reason: "cancelled"}
}

func (s *scope) runStage(ctx context.Context, st *Stage) stageResult {
	var res stageResult
	switch st.Kind {
	case KindAgentTurn:
		res = s.agentTurn(ctx, st)
	case KindFanout:
		res = s.fanout(ctx, st)
	case KindSubworkflow:
		res = s.subworkflow(ctx, st)
	case KindGate:
		res = s.gate(st)
	case KindCommand:
		res = s.command(ctx, st)
	case KindChangeRequest:
		res = s.changeRequest(st)
	default:
		res = failed(ReasonStage, "unknown stage kind %q", st.Kind)
	}
	if res.state == StateFailed && ctx.Err() != nil {
		return s.stoppedResult()
	}
	if res.state == "" {
		res.state = StateDone
	}
	return res
}

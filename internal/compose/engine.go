package compose

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/jsonschema"
)

// Runner runs templates against a store. One Runner shares role caps,
// --max-parallel and admission between every run it executes. Role caps are
// also shared with every other Runner and process using the same store,
// through its lease file (DESIGN §16.7); --max-parallel is per process.
type Runner struct {
	Store       *Store
	Executor    Executor
	Resolve     Resolver // finds templates for subworkflow stages; may be nil
	Dir         string   // repo root: turns' and commands' working directory
	MaxParallel int      // bound on concurrent turns and commands; 0 is unbounded
	DryCommands bool     // record exit 0 for unscripted commands instead of running them
	Now         func() time.Time

	mu     sync.Mutex // admission, semaphores and live runs
	sems   map[string]chan struct{}
	global chan struct{}
	live   map[string]bool
}

// Admission asks for a run: a new task, or the continuation of an existing
// task id (resume).
type Admission struct {
	Template   *Template
	ID         string                     // the task id; generated for a new root when empty
	Inputs     map[string]json.RawMessage // workflow inputs
	Parent     string                     // admits a detached child of this task
	FromParent map[string]string          // input name -> parent artifact name
}

// AdmissionError refuses an admission, listing every error.
type AdmissionError struct {
	Reason string // admission or recursion_budget
	Errors []string
}

func (e *AdmissionError) Error() string {
	return fmt.Sprintf("admission refused (%s): %s", e.Reason, strings.Join(e.Errors, "; "))
}

func (r *Runner) now() time.Time {
	if r.Now != nil {
		return r.Now().UTC()
	}
	return time.Now().UTC()
}

// Run admits a task, or resumes it when its id already exists, and runs it
// to a terminal state. It returns the final record; a failed run is not an
// error. Interruption (ctx cancelled) returns the record in state
// interrupted with ctx's error, and re-running the task id continues it.
func (r *Runner) Run(ctx context.Context, a Admission) (*RunRecord, error) {
	if a.Template == nil {
		return nil, errors.New("compose: no template")
	}
	if r.Executor == nil {
		return nil, errors.New("compose: no executor")
	}
	if a.ID != "" && r.Store.Exists(a.ID) {
		rec, err := r.Store.Load(a.ID)
		if err != nil {
			return nil, err
		}
		if rec.Workflow != a.Template.ID {
			return nil, fmt.Errorf("task %s runs workflow %s, not %s", a.ID, rec.Workflow, a.Template.ID)
		}
		if a.Parent != "" && rec.Parent != a.Parent {
			return nil, fmt.Errorf("task %s has parent %q, not %q", a.ID, rec.Parent, a.Parent)
		}
		return r.execute(ctx, rec, a.Template)
	}
	var origin *Origin
	if a.Parent != "" {
		origin = &Origin{Detached: true}
	} else if len(a.FromParent) > 0 {
		return nil, &AdmissionError{Reason: ReasonAdmission, Errors: []string{"from_parent needs a parent task"}}
	}
	rec, err := r.admit(a, origin, nil, nil)
	if err != nil {
		return nil, err
	}
	return r.execute(ctx, rec, a.Template)
}

// admit checks an admission and records the new task.
func (r *Runner) admit(a Admission, origin *Origin, parent *RunRecord, parentTpl *Template) (*RunRecord, error) {
	tpl := a.Template
	var errs []string
	inputs := map[string]json.RawMessage{}
	prov := map[string]string{}
	for k, v := range a.Inputs {
		inputs[k] = v
		prov[k] = "input:" + k
	}
	if a.Parent != "" && parent == nil {
		p, err := r.Store.Load(a.Parent)
		if err != nil {
			return nil, &AdmissionError{Reason: ReasonAdmission, Errors: []string{fmt.Sprintf("parent %s: %v", a.Parent, err)}}
		}
		parent = p
	}
	if parent != nil && parentTpl == nil {
		if t, err := Parse(parent.Template); err == nil {
			parentTpl = t
		}
	}
	for _, in := range sortedKeys(a.FromParent) {
		art := a.FromParent[in]
		if _, dup := inputs[in]; dup {
			errs = append(errs, fmt.Sprintf("input %q is given both directly and from the parent", in))
			continue
		}
		raw, err := r.Store.ReadArtifact(parent.ID, art)
		if err != nil {
			errs = append(errs, fmt.Sprintf("from_parent %s: parent %s has no artifact %q", in, parent.ID, art))
			continue
		}
		inputs[in] = raw
		prov[in] = "parent:" + parent.ID + "/" + art
	}
	errs = append(errs, checkInputs(tpl, inputs)...)
	if len(errs) > 0 {
		return nil, &AdmissionError{Reason: ReasonAdmission, Errors: errs}
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	id := a.ID
	depth, root, outDir := 1, "", ""
	if parent != nil {
		depth, root = parent.Depth+1, parent.TreeRoot
		if id == "" {
			id = r.nextDetachedID(parent.ID)
		}
		if err := r.checkBudget(parent, parentTpl, tpl, origin); err != nil {
			return nil, err
		}
		outDir = filepath.Join(parent.OutDir, id)
	} else {
		if id == "" {
			id = generateID(tpl.ID, r.now())
		}
		if !idRe.MatchString(id) {
			return nil, &AdmissionError{Reason: ReasonAdmission, Errors: []string{fmt.Sprintf("task id %q must match %s", id, idRe)}}
		}
		root = id
		outDir = filepath.Join(r.Store.RunDir(id), "out")
	}
	if r.Store.Exists(id) {
		return nil, fmt.Errorf("task %s already exists", id)
	}
	if abs, err := filepath.Abs(outDir); err == nil {
		outDir = abs
	}
	now := r.now()
	rec := &RunRecord{
		ID: id, Workflow: tpl.ID, Version: tpl.Version, TemplatePath: tpl.Source, Template: tpl.Raw,
		Inputs: inputs, FromParent: a.FromParent, Parent: a.Parent, TreeRoot: root, Depth: depth,
		Origin: origin, OutDir: outDir, State: StatePending, Created: now, Updated: now,
		Stages: map[string]*StageState{}, Artifacts: map[string]*ArtifactMeta{},
	}
	if parent != nil {
		rec.Parent = parent.ID
	}
	for _, name := range sortedKeys(inputs) {
		sum, err := r.Store.WriteArtifact(id, name, inputs[name])
		if err != nil {
			return nil, err
		}
		rec.Artifacts[name] = &ArtifactMeta{Provenance: prov[name], SHA256: sum, Recorded: now}
	}
	if err := r.Store.Save(rec); err != nil {
		return nil, err
	}
	data := map[string]any{"workflow": tpl.ID, "depth": depth}
	if origin != nil && origin.Detached {
		data["detached"] = true
	}
	r.event(rec, "admitted", "", data)
	if parent != nil {
		r.Store.AppendEvent(parent.ID, Event{Time: now, Type: "child_admitted", Task: parent.ID, ParentTask: parent.Parent,
			TreeRoot: parent.TreeRoot, Data: map[string]any{"child": id}})
	}
	return rec, nil
}

// checkInputs binds defaults and validates inputs against the signature.
func checkInputs(tpl *Template, inputs map[string]json.RawMessage) []string {
	var errs []string
	for _, name := range sortedKeys(inputs) {
		if _, ok := tpl.Inputs[name]; !ok {
			errs = append(errs, fmt.Sprintf("unknown input %q (workflow %s declares %s)", name, tpl.ID, strings.Join(sortedKeys(tpl.Inputs), ", ")))
		}
	}
	for _, name := range sortedKeys(tpl.Inputs) {
		schema := tpl.Inputs[name]
		raw, ok := inputs[name]
		if !ok {
			if d, has := schema["default"]; has {
				b, _ := json.Marshal(d)
				inputs[name] = b
				continue
			}
			errs = append(errs, fmt.Sprintf("required input %q is missing", name))
			continue
		}
		v, err := decodeJSON(raw)
		if err != nil {
			errs = append(errs, fmt.Sprintf("input %q: %v", name, err))
			continue
		}
		for _, m := range jsonschema.Validate(schema, v, nil) {
			errs = append(errs, fmt.Sprintf("input %q: %s", name, m))
		}
	}
	return errs
}

func decodeJSON(raw json.RawMessage) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return expr.Native(v), nil
}

func generateID(workflow string, now time.Time) string {
	var b [3]byte
	rand.Read(b[:])
	return fmt.Sprintf("%s-%s-%s", workflow, now.Format("20060102T150405"), hex.EncodeToString(b[:]))
}

// nextDetachedID returns "<parent>.detached.<n>" for the first free n.
func (r *Runner) nextDetachedID(parent string) string {
	for n := 1; ; n++ {
		id := fmt.Sprintf("%s.detached.%d", parent, n)
		if !r.Store.Exists(id) {
			return id
		}
	}
}

// checkBudget refuses a child that would exceed a recursion budget of its
// parent's or its own template (FAE-WF-098, -100). r.mu is held.
func (r *Runner) checkBudget(parent *RunRecord, parentTpl, childTpl *Template, origin *Origin) error {
	depth := parent.Depth + 1
	all, err := r.Store.List()
	if err != nil {
		return err
	}
	descendants, children := 0, 0
	for _, x := range all {
		if x.TreeRoot != parent.TreeRoot || x.Parent == "" {
			continue
		}
		descendants++
		if x.Parent == parent.ID && x.Origin != nil && origin != nil && !origin.Detached && !x.Origin.Detached &&
			x.Origin.Stage == origin.Stage && x.Origin.Visit == origin.Visit {
			children++
		}
	}
	var errs []string
	if depth > DepthCeiling {
		errs = append(errs, fmt.Sprintf("depth %d exceeds the instance ceiling %d", depth, DepthCeiling))
	}
	var budgets []*Template
	for _, t := range []*Template{parentTpl, childTpl} {
		if t != nil && t.Recursion != nil && (len(budgets) == 0 || budgets[0].ID != t.ID) {
			budgets = append(budgets, t)
		}
	}
	if len(budgets) == 0 && depth > NestingLimit {
		errs = append(errs, fmt.Sprintf("depth %d exceeds the nesting limit %d for templates without recursion", depth, NestingLimit))
	}
	for _, t := range budgets {
		b := t.Recursion
		if depth > b.MaxDepth {
			errs = append(errs, fmt.Sprintf("depth %d exceeds max_depth %d of workflow %s", depth, b.MaxDepth, t.ID))
		}
		if b.MaxDescendants > 0 && descendants+1 > b.MaxDescendants {
			errs = append(errs, fmt.Sprintf("descendant %d exceeds max_descendants %d of workflow %s", descendants+1, b.MaxDescendants, t.ID))
		}
		if b.MaxChildrenPerVisit > 0 && origin != nil && !origin.Detached && children+1 > b.MaxChildrenPerVisit {
			errs = append(errs, fmt.Sprintf("child %d of stage %s visit %d exceeds max_children_per_visit %d of workflow %s",
				children+1, origin.Stage, origin.Visit, b.MaxChildrenPerVisit, t.ID))
		}
	}
	if len(errs) > 0 {
		return &AdmissionError{Reason: ReasonRecursionBudget, Errors: errs}
	}
	return nil
}

// remainingDescendants is the smallest remaining max_descendants budget
// over the given templates, or -1 when none is bounded.
func (r *Runner) remainingDescendants(rec *RunRecord, tpls ...*Template) int {
	limit := -1
	for _, t := range tpls {
		if t != nil && t.Recursion != nil && t.Recursion.MaxDescendants > 0 && (limit < 0 || t.Recursion.MaxDescendants < limit) {
			limit = t.Recursion.MaxDescendants
		}
	}
	if limit < 0 {
		return -1
	}
	all, _ := r.Store.List()
	n := 0
	for _, x := range all {
		if x.TreeRoot == rec.TreeRoot && x.Parent != "" {
			n++
		}
	}
	if n > limit {
		return 0
	}
	return limit - n
}

// runCtx is one executing task.
type runCtx struct {
	r       *Runner
	rec     *RunRecord
	tpl     *Template
	rootCtx context.Context
	mu      sync.Mutex     // guards rec and art
	art     map[string]any // artifact values by key
	inputs  map[string]any
}

func (rc *runCtx) save() {
	rc.rec.Updated = rc.r.now()
	if err := rc.r.Store.Save(rc.rec); err != nil {
		panic(fmt.Sprintf("compose: saving %s: %v", rc.rec.ID, err))
	}
}

// update runs fn under the run's lock and saves the record.
func (rc *runCtx) update(fn func()) {
	rc.mu.Lock()
	defer rc.mu.Unlock()
	fn()
	rc.save()
}

func (r *Runner) event(rec *RunRecord, typ, stage string, data map[string]any) {
	r.Store.AppendEvent(rec.ID, Event{Time: r.now(), Type: typ, Task: rec.ID, ParentTask: rec.Parent, TreeRoot: rec.TreeRoot, Stage: stage, Data: data})
}

// execute runs (or continues) a task's unfinished stages.
func (r *Runner) execute(ctx context.Context, rec *RunRecord, tpl *Template) (*RunRecord, error) {
	r.mu.Lock()
	if r.live == nil {
		r.live = map[string]bool{}
	}
	if r.live[rec.ID] {
		r.mu.Unlock()
		return nil, fmt.Errorf("task %s is already running", rec.ID)
	}
	r.live[rec.ID] = true
	r.mu.Unlock()
	defer func() {
		r.mu.Lock()
		delete(r.live, rec.ID)
		r.mu.Unlock()
	}()

	rc := &runCtx{r: r, rec: rec, tpl: tpl, rootCtx: ctx, art: map[string]any{}, inputs: map[string]any{}}
	for key := range rec.Artifacts {
		raw, err := r.Store.ReadArtifact(rec.ID, key)
		if err != nil {
			return nil, fmt.Errorf("task %s: artifact %s: %v", rec.ID, key, err)
		}
		v, err := decodeJSON(raw)
		if err != nil {
			return nil, fmt.Errorf("task %s: artifact %s: %v", rec.ID, key, err)
		}
		rc.art[key] = v
	}
	for name, raw := range rec.Inputs {
		v, _ := decodeJSON(raw)
		rc.inputs[name] = v
	}
	resumed := rec.State != StatePending
	rc.update(func() {
		if rec.Stages == nil {
			rec.Stages = map[string]*StageState{}
		}
		resetStages(rec.Stages, tpl.Stages)
		rec.State, rec.Reason, rec.Error = StateRunning, "", ""
	})
	if resumed {
		r.event(rec, "resumed", "", nil)
	} else {
		r.event(rec, "started", "", nil)
	}

	top := &scope{rc: rc, stages: tpl.Stages, states: rec.Stages, branch: -1}
	top.run(ctx)

	var err error
	rc.update(func() {
		switch {
		case top.stopped && ctx.Err() != nil:
			rec.State, rec.Error = StateInterrupted, ctx.Err().Error()
			err = ctx.Err()
		case top.fail != nil:
			rec.State, rec.Reason = StateFailed, top.fail.Reason
			rec.Error = fmt.Sprintf("stage %s: %s", top.fail.Stage, top.fail.Error)
		default:
			if errs := rc.checkOutputs(); len(errs) > 0 {
				rec.State, rec.Reason, rec.Error = StateFailed, ReasonOutputs, strings.Join(errs, "; ")
			} else {
				rec.State = StateDone
			}
		}
	})
	r.event(rec, "finished", "", map[string]any{"state": rec.State, "reason": rec.Reason})
	return rec, err
}

// checkOutputs validates the workflow's declared outputs. rc.mu is held.
func (rc *runCtx) checkOutputs() []string {
	var errs []string
	for _, name := range sortedKeys(rc.tpl.Outputs) {
		v, ok := rc.art[name]
		if !ok {
			errs = append(errs, fmt.Sprintf("output %q was not produced", name))
			continue
		}
		for _, m := range jsonschema.Validate(rc.tpl.Outputs[name], v, nil) {
			errs = append(errs, fmt.Sprintf("output %q: %s", name, m))
		}
	}
	return errs
}

// resetStages makes sure every stage has a state, and returns every stage
// that isn't done to pending, so a resumed run continues it.
func resetStages(states map[string]*StageState, stages []*Stage) {
	for _, s := range stages {
		ss := states[s.ID]
		if ss == nil {
			states[s.ID] = &StageState{State: StatePending}
			continue
		}
		if ss.State == StateDone {
			continue
		}
		ss.State, ss.Reason, ss.Error, ss.RoutedTo = StatePending, "", "", ""
		ss.Started, ss.Finished, ss.Routed = nil, nil, nil
	}
}

// acquire takes the role cap (by its cap_scope) and the global bound. A
// role cap is held twice: in this process (a semaphore, so the Runner's own
// turns queue without touching the disk) and across processes (a lease in the
// store's lease file, DESIGN §16.7). The global --max-parallel bound is per
// process.
func (r *Runner) acquire(ctx context.Context, rc *runCtx, role, stage string) (func(), error) {
	var chans []chan struct{}
	var leaseKey string
	var leaseCap int
	r.mu.Lock()
	if r.sems == nil {
		r.sems = map[string]chan struct{}{}
	}
	if spec, ok := rc.tpl.Roles[role]; ok && role != "" && spec.Cap > 0 {
		var key string
		switch spec.CapScope {
		case ScopeTree:
			key = "tree/" + rc.rec.TreeRoot + "/" + role
		case ScopeTask:
			key = "task/" + rc.rec.ID + "/" + role
		default:
			key = "workflow/" + rc.tpl.ID + "/" + role
		}
		ch := r.sems[key]
		if ch == nil {
			ch = make(chan struct{}, spec.Cap)
			r.sems[key] = ch
		}
		chans = append(chans, ch)
		leaseKey, leaseCap = key, spec.Cap
	}
	var global chan struct{}
	if r.MaxParallel > 0 {
		if r.global == nil {
			r.global = make(chan struct{}, r.MaxParallel)
		}
		global = r.global
	}
	r.mu.Unlock()
	var held []func()
	release := func() {
		for i := len(held) - 1; i >= 0; i-- {
			held[i]()
		}
	}
	take := func(ch chan struct{}) error {
		select {
		case ch <- struct{}{}:
			held = append(held, func() { <-ch })
			return nil
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	for _, ch := range chans {
		if err := take(ch); err != nil {
			release()
			return nil, err
		}
	}
	if leaseKey != "" {
		free, err := acquireLease(ctx, LeasePath(r.Store.Root), leaseKey, leaseCap, rc.rec.ID, stage)
		if err != nil {
			release()
			return nil, err
		}
		held = append(held, free)
	}
	if global != nil {
		if err := take(global); err != nil {
			release()
			return nil, err
		}
	}
	return release, nil
}

// Package sim runs flows over an ontology: a deterministic, discrete-event
// interpreter of component behaviors with fake data, faults, retries,
// timeouts and choice points, plus the §11 additions: instances, parallel
// joins, deadlines, timers, capacity, publish/subscribe, config, fixtures,
// multi-step scenarios and mocks. Its work runs as cooperative tasks over
// virtual time (§13.1 item 14, sched.go). The same document, request and
// seed always produce the same trace.
package sim

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"math/rand/v2"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/jsonschema"
	"github.com/xleelz/mosaic/internal/model"
)

// Request asks for one run. Scenario values apply first; the request's own
// values overlay them.
type Request struct {
	Flow     string                    `json:"flow,omitempty"`
	Scenario string                    `json:"scenario,omitempty"`
	Seed     *int64                    `json:"seed,omitempty"`
	Input    json.RawMessage           `json:"input,omitempty"`
	Choices  map[string]model.Choice   `json:"choices,omitempty"`
	State    map[string]map[string]any `json:"state,omitempty"`
	Faults   []model.Fault             `json:"faults,omitempty"`
	Expect   []string                  `json:"expect,omitempty"`
	// Invariants must hold under every schedule (§16.2); runs check them
	// like expectations, as assertions marked Invariant.
	Invariants []string `json:"invariants,omitempty"`
	// The starting world (§11.7, §13.1): fixtures applied after the
	// scenario's, then this topology, config and clock on top. In a
	// result's effective request they hold the resolved world: every
	// fixture applied, the merged topology, the config overrides and the
	// clock's epoch.
	Fixtures []string            `json:"fixtures,omitempty"`
	Topology map[string][]string `json:"topology,omitempty"`
	Config   map[string]any      `json:"config,omitempty"`
	Clock    *model.Clock        `json:"clock,omitempty"`
	// Resolution chooses, per component path, black_box or refined
	// (§14.5), over the scenario's. A refined component is replaced by its
	// child ontology from the document's loaded Refinements before the run.
	Resolution map[string]string `json:"resolution,omitempty"`
	// Schedule, when set, drives the run's choice points and records them
	// (§15.5 schedule exploration, schedpoints.go).
	Schedule *Schedule `json:"-"`
}

// Error is a simulated error.
type Error struct {
	Code      string `json:"code"`
	Message   string `json:"message,omitempty"`
	Status    int    `json:"status,omitempty"`
	Retryable bool   `json:"retryable,omitempty"`
	Data      any    `json:"data,omitempty"`
	// Headers are the response headers a failure carries (§13.1 item 35),
	// at lower-case keys: a fail's headers.
	Headers map[string]any `json:"headers,omitempty"`
}

// Map is the error as seen by expressions.
func (e *Error) Map() map[string]any {
	if e == nil {
		return nil
	}
	m := map[string]any{"code": e.Code, "message": e.Message, "status": int64(e.Status), "retryable": e.Retryable, "data": e.Data}
	if e.Headers != nil {
		m["headers"] = deepCopy(e.Headers)
	}
	return m
}

// Outcome is the result of the entry call.
type Outcome struct {
	OK    bool   `json:"ok"`
	Value any    `json:"value,omitempty"`
	Error *Error `json:"error,omitempty"`
}

// Pass is the outcome of one pass of a repeated flow entry.
type Pass struct {
	Pass       int     `json:"pass"`
	Result     Outcome `json:"result"`
	StartMS    int64   `json:"start_ms"`
	DurationMS int64   `json:"duration_ms"`
	DurationUS *int64  `json:"duration_us,omitempty"` // §13.1 item 16, in runs with sub-ms time
	durUS      int64
	startUS    int64 // the exact start, CEL passes[i].start_us (§17 item 17)
}

// Assertion is one evaluated expectation.
type Assertion struct {
	Expr   string `json:"expr"`
	Passed bool   `json:"passed"`
	Error  string `json:"error,omitempty"`
	// Invariant marks a scenario invariant (§16.2): exploration checks it
	// under every schedule, the scenario's expect only on the default one.
	Invariant bool `json:"invariant,omitempty"`
}

// Summary describes a finished run.
type Summary struct {
	Status       string                    `json:"status"`
	Result       Outcome                   `json:"result"`
	DurationMS   int64                     `json:"duration_ms"`
	DurationUS   *int64                    `json:"duration_us,omitempty"` // §13.1 item 16, in runs with sub-ms time
	Events       int                       `json:"events"`
	Calls        map[string]int            `json:"calls"`
	Retries      int                       `json:"retries"`
	Faults       int                       `json:"faults"`
	Ctx          map[string]any            `json:"ctx"`
	State        map[string]map[string]any `json:"state"`
	InitialState map[string]map[string]any `json:"initial_state"`
	Assertions   []Assertion               `json:"assertions"`
	Passed       bool                      `json:"passed"`
	Warnings     []string                  `json:"warnings"`
	Seed         int64                     `json:"seed"`
	Abort        string                    `json:"abort,omitempty"`
	Passes       []Pass                    `json:"passes,omitempty"` // only for flows whose entry repeats
	// §11.9 additions, omitted when empty.
	CallsByInstance map[string]int `json:"calls_by_instance,omitempty"` // keyed <interface>@<instance>, named instances only
	Steps           []StepResult   `json:"steps,omitempty"`             // the steps of a multi-step scenario
	Queued          int            `json:"queued,omitempty"`            // calls that waited for capacity
	Mocks           int            `json:"mocks,omitempty"`             // mocked calls
	Executed        []string       `json:"executed,omitempty"`          // sorted behavior step paths that ran
	// Limits counts each limiter's decisions (§13.1 item 27), by full id.
	Limits map[string]LimitCount `json:"limits,omitempty"`
	// Caps reports the run's caps when one of them ended it (§13.1 item
	// 35): the event cap and the virtual-time cap, and which was hit.
	Caps *Caps `json:"caps,omitempty"`
	// Pending lists the calls that never answered (a hang with forever:
	// true, §13.1 item 35) and were still in flight when the run ended.
	Pending []PendingCall `json:"pending,omitempty"`
}

// Caps are a run's caps (§13.1 item 35): max_events, and max_virtual_ms
// (null when the run had none). Hit names the cap that ended the run:
// "max_events" or "max_virtual_ms".
type Caps struct {
	MaxEvents    int    `json:"max_events"`
	MaxVirtualMS *int64 `json:"max_virtual_ms"`
	Hit          string `json:"hit"`
}

// PendingCall is a call still in flight when the run ended, with no
// synthetic error (§13.1 item 35).
type PendingCall struct {
	Call      int    `json:"call"`
	From      string `json:"from,omitempty"`
	Interface string `json:"interface"`
	Instance  string `json:"instance,omitempty"`
	StartMS   int64  `json:"start_ms"`
	Fault     string `json:"fault,omitempty"`
}

// StepResult is the outcome of one step of a multi-step scenario (§11.7).
type StepResult struct {
	As         string  `json:"as,omitempty"`
	Flow       string  `json:"flow,omitempty"`
	Interface  string  `json:"interface"`
	On         string  `json:"on,omitempty"`
	Result     Outcome `json:"result"`
	Status     string  `json:"status"`
	StartMS    int64   `json:"start_ms"`
	DurationMS int64   `json:"duration_ms"`
	DurationUS *int64  `json:"duration_us,omitempty"` // §13.1 item 16, in runs with sub-ms time
	durUS      int64
}

// Event is one entry of the trace.
type Event struct {
	Seq        int           `json:"seq"`
	T          int64         `json:"t"`
	Type       string        `json:"type"`
	Span       int           `json:"span,omitempty"`
	Parent     int           `json:"parent,omitempty"`
	Call       int           `json:"call,omitempty"`
	Component  string        `json:"component,omitempty"`
	From       string        `json:"from,omitempty"`
	To         string        `json:"to,omitempty"`
	Interface  string        `json:"interface,omitempty"`
	Attempt    int           `json:"attempt,omitempty"`
	Async      bool          `json:"async,omitempty"`
	Input      any           `json:"input,omitempty"`
	Output     any           `json:"output,omitempty"`
	OK         *bool         `json:"ok,omitempty"`
	Error      *Error        `json:"error,omitempty"`
	DurationMS int64         `json:"duration_ms,omitempty"`
	Late       bool          `json:"late,omitempty"`
	Title      string        `json:"title,omitempty"`
	Detail     string        `json:"detail,omitempty"`
	Source     *model.Source `json:"source,omitempty"`
	Scope      string        `json:"scope,omitempty"`
	Path       string        `json:"path,omitempty"`
	Old        any           `json:"old,omitempty"`
	New        any           `json:"new,omitempty"`
	Key        string        `json:"key,omitempty"`
	Option     string        `json:"option,omitempty"`
	Origin     string        `json:"origin,omitempty"`
	Fault      string        `json:"fault,omitempty"`
	BackoffMS  int64         `json:"backoff_ms,omitempty"`
	// Jitter is set on a retry event whose wait was drawn (full or equal
	// jitter); BackoffMS is then the drawn wait.
	Jitter  string `json:"jitter,omitempty"`
	Message string `json:"message,omitempty"`
	// §13.1 item 9 additions.
	Instance string `json:"instance,omitempty"` // the instance the event happened on (the callee's, for calls)
	Mock     bool   `json:"mock,omitempty"`     // a mocked call
	WaitMS   int64  `json:"wait_ms,omitempty"`  // on queue: the wait for a capacity slot
	Topic    string `json:"topic,omitempty"`    // on publish, and on the emits of an async publish
	Branch   *int   `json:"branch,omitempty"`   // the branch index inside a parallel
	// Table is set on the set events of store operations, with Key holding
	// the row key, since Path ("state.<table>.<key>") does not escape dots.
	Table string `json:"table,omitempty"`
	// §13.1 item 16: the exact time and duration in µs, in runs whose
	// clock left whole milliseconds. T and DurationMS are floor(us/1000).
	TUS        *int64 `json:"t_us,omitempty"`
	DurationUS *int64 `json:"duration_us,omitempty"`
	// Index is a yield's item index (§13.1 item 18).
	Index *int64 `json:"index,omitempty"`
	// Headers are a call.end's response headers, at lower-case keys
	// (§13.1 item 35).
	Headers    map[string]any `json:"headers,omitempty"`
	tUS, durUS int64
}

// Result is a finished run: the effective request, summary and trace.
type Result struct {
	Request Request `json:"request"`
	Summary Summary `json:"summary"`
	Trace   []Event `json:"trace"`
}

// Limits bound a run so that every run terminates.
type Limits struct {
	MaxEvents     int
	MaxDepth      int
	MaxEmits      int
	MaxIterations int // foreach iterations in the whole run; 0 means the default
	MaxTimers     int // timer deliveries in the whole run (§11.3); 0 means the default
	// MaxForeach caps the items of every foreach and the branches of every
	// parallel (§17 item 18); 0 keeps the per-step rule (max, default
	// 100, at most 1000).
	MaxForeach int
}

// DefaultLimits are the documented budgets.
var DefaultLimits = Limits{MaxEvents: 20000, MaxDepth: 64, MaxEmits: 1000, MaxIterations: 10000, MaxTimers: model.MaxTimerCount}

// defaultHangMS is how long a hung callee holds a caller that set no timeout.
const defaultHangMS = 30000

const defaultHangUS = defaultHangMS * 1000

// RequestError is a request that cannot run (unknown flow or scenario, say).
type RequestError struct{ Msg string }

func (e *RequestError) Error() string { return e.Msg }

type abortError struct {
	msg    string
	events bool // the event cap ended the run (§13.1 item 35)
}

func (e *abortError) Error() string { return e.msg }

func abortf(format string, a ...any) error { return &abortError{msg: fmt.Sprintf(format, a...)} }

// Run runs a request against a document with the default limits.
func Run(doc *model.Document, req Request) (*Result, error) {
	return RunWithLimits(doc, req, DefaultLimits)
}

// plan is what a resolved request runs: a flow's entry, or the steps of a
// multi-step scenario, in a starting world.
type plan struct {
	flow     *model.Flow // nil for a multi-step scenario without a flow
	inputTpl any
	steps    []model.ScenarioStep
	world    *model.World
	mocks    []model.Mock
	// maxVirtualMS is the scenario's max_virtual_ms; 0 means the default.
	maxVirtualMS int64
	// costLimit is the scenario's cost_limit; 0 means the default.
	costLimit int64
	// maxEvents is the scenario's max_events (§13.1 item 35); 0 means the
	// limits' own.
	maxEvents int
	// maxIterations is the scenario's max_iterations (§15.3); 0 means the
	// limits' own.
	maxIterations int
	// maxForeach is the scenario's max_foreach (§17 item 18); 0 means the
	// limits' own.
	maxForeach int
}

// RunWithLimits runs a request against a document.
func RunWithLimits(doc *model.Document, req Request, lim Limits) (*Result, error) {
	doc, resolution, err := compose(doc, req)
	if err != nil {
		return nil, err
	}
	x := model.NewIndex(doc)
	eff, pl, err := effective(x, req)
	if err != nil {
		return nil, err
	}
	if len(resolution) > 0 {
		eff.Resolution = resolution
	}
	var entry *model.Interface
	if len(pl.steps) == 0 {
		var ok bool
		if entry, ok = x.Interfaces[pl.flow.Entry.Interface]; !ok {
			return nil, &RequestError{fmt.Sprintf("flow %q enters unknown interface %q", pl.flow.ID, pl.flow.Entry.Interface)}
		}
	}
	if issues := model.ValidateFaults(doc, eff.Faults); model.HasErrors(issues) {
		return nil, &RequestError{fmt.Sprintf("invalid fault at %s: %s", issues[0].Path, issues[0].Message)}
	}
	seed := int64(1)
	if eff.Seed != nil {
		seed = *eff.Seed
	}
	if lim.MaxIterations <= 0 {
		lim.MaxIterations = DefaultLimits.MaxIterations
	}
	if lim.MaxTimers <= 0 {
		lim.MaxTimers = DefaultLimits.MaxTimers
	}
	if pl.maxEvents > 0 {
		lim.MaxEvents = pl.maxEvents // a scenario's max_events (§13.1 item 35)
	}
	if pl.maxIterations > 0 {
		lim.MaxIterations = pl.maxIterations // a scenario's max_iterations (§15.3)
	}
	if pl.maxForeach > 0 {
		lim.MaxForeach = pl.maxForeach // a scenario's max_foreach (§17 item 18)
	}
	r := newRun(x, lim, seed, eff, pl)
	r.s.xp = req.Schedule.start(r)
	if err := r.seedLimiters(pl.world.Limiters, "limiters"); err != nil {
		return nil, err
	}
	r.snapshotLimiters()
	if err := r.evalChoices(); err != nil {
		return nil, err
	}
	initial := cloneStates(r.states)
	r.initial = initial

	var res callResult
	r.spawn(kindRoot, 0, nil, func(t *task) error {
		var err error
		if len(pl.steps) > 0 {
			res, err = r.runSteps(pl.steps)
		} else {
			res, err = r.runEntry(pl.flow, entry, pl.inputTpl)
		}
		return err
	})
	// Kill faults (§13.1 item 18) are due at their at_ms.
	for i, ft := range eff.Faults {
		if ft.Type == model.FaultKill && ft.AtMS != nil {
			i, ft := i, ft
			r.spawn(kindKill, max(r.msToUS(*ft.AtMS), 0), nil, func(t *task) error { return r.killFault(ft, i) })
		}
	}
	r.loop()
	err = r.s.failure
	if _, isReq := err.(*RequestError); isReq {
		return nil, err
	}
	if len(pl.steps) > 0 && err == nil {
		r.passes = append(r.passes, Pass{Pass: 1, Result: res.outcome(), StartMS: 0, DurationMS: msFloor(r.s.end), durUS: r.s.end})
	}
	var steps []StepResult
	for _, sr := range r.stepResults {
		if sr.Status != "" {
			steps = append(steps, sr)
		}
	}

	pending := r.pendingCalls()
	for _, pc := range pending {
		r.warn(fmt.Sprintf("call %d to %s never answered (a %s fault with forever: true); it was still pending when the run ended", pc.Call, pc.Interface, pc.Fault))
	}
	s := Summary{
		Pending: pending,
		Status:  "ok", Result: res.outcome(),
		DurationMS: msFloor(r.s.end), Events: len(r.events), Calls: map[string]int{}, Retries: r.retries,
		Faults: r.faultsHit, Ctx: deepCopy(r.ctx).(map[string]any), State: cloneStates(r.states),
		InitialState: initial, Assertions: []Assertion{}, Passed: true, Warnings: r.warnings, Seed: seed,
		Queued: r.queued, Mocks: r.mocked, Steps: steps, Limits: r.limitsSummary(),
	}
	for k, n := range r.calls {
		s.Calls[k] = n
	}
	if len(r.callsByInst) > 0 {
		s.CallsByInstance = map[string]int{}
		for k, n := range r.callsByInst {
			s.CallsByInstance[k] = n
		}
	}
	if len(r.executed) > 0 {
		s.Executed = sortedKeys(r.executed)
	}
	if len(pl.steps) == 0 && pl.flow.Entry.Repeat != nil {
		s.Passes = append([]Pass{}, r.passes...)
	}
	var ae *abortError
	switch {
	case errors.As(err, &ae):
		s.Status, s.Abort, s.Passed = "aborted", ae.msg, false
		if ae.events {
			s.Caps = r.caps("max_events")
		}
	case err != nil:
		return nil, err
	case !res.ok && res.err == nil && len(s.Pending) > 0:
		s.Status = "pending" // the entry's call never answered (§13.1 item 35)
	case !res.ok:
		s.Status = "error"
	}
	if r.s.hitLim && s.Caps == nil {
		s.Caps = r.caps("max_virtual_ms")
	}
	if s.Warnings == nil {
		s.Warnings = []string{}
	}
	if s.Status != "aborted" {
		s.Assertions = r.checks(eff, s) // expect, then invariants (invariants.go)
		for _, a := range s.Assertions {
			s.Passed = s.Passed && a.Passed
		}
	}
	r.finishUS(&s)
	return &Result{Request: eff, Summary: s, Trace: r.events}, nil
}

func (c callResult) outcome() Outcome { return Outcome{OK: c.ok, Value: c.value, Error: c.err} }

// runEntry runs a flow's entry, pass after pass when it repeats, as a
// reconciler or cron would. Each pass delivers its own emits and timers
// before the clock advances to the next.
func (r *run) runEntry(flow *model.Flow, entry *model.Interface, inputTpl any) (callResult, error) {
	input := r.fake(entry.Request)
	if inputTpl != nil {
		v, err := expr.Behavior.Template(inputTpl, r.topAct(nil, nil))
		if err != nil {
			return callResult{}, &RequestError{fmt.Sprintf("entry input: %v", err)}
		}
		input = resolveInput(deepMerge(input, v))
	}
	inst, bad, err := r.entryInstance(entry, flow.Entry.On, expr.Behavior, r.topAct(input, nil))
	if err != nil {
		return callResult{}, err
	}
	me := r.s.cur
	me.homeComp, me.homeInst = entry.Component, inst
	passes, interval := 1, int64(0)
	if rp := flow.Entry.Repeat; rp != nil {
		passes, interval = max(1, min(rp.Count, model.MaxRepeatCount)), max(r.msToUS(rp.IntervalMS), 0)
		if err := r.sleep(max(r.msToUS(rp.InitialDelayMS), 0)); err != nil {
			return callResult{}, err
		}
	}
	var res callResult
	for i := 0; i < passes && err == nil; i++ {
		if i > 0 {
			if err := r.sleep(interval); err != nil {
				return callResult{}, err
			}
		}
		// Each pass has its own lane: its emits and timers are delivered
		// after its call tree, and the next pass waits for them.
		me.lane = r.newLane()
		start := r.now
		deadline := int64(noDeadline)
		if dl := flow.Entry.DeadlineMS; !dl.IsZero() {
			d, err := r.topInt(dl, expr.Behavior, r.topAct(input, nil), "flow entry deadline_ms")
			if err != nil {
				return callResult{}, err
			}
			deadline = start + d
		}
		res, err = r.invoke(callSpec{from: flow.Entry.Caller, target: entry.ID, inst: inst, badInst: bad, input: input,
			callID: r.nextCall(), attempt: 1, depth: 1, deadline: deadline})
		if err == nil {
			r.openLane(me.lane)
			err = r.waitQuiet()
		}
		if err == nil {
			r.passes = append(r.passes, Pass{Pass: i + 1, Result: res.outcome(), StartMS: msFloor(start), DurationMS: msFloor(r.now - start), durUS: r.now - start, startUS: start})
		}
	}
	return res, err
}

func effective(x *model.Index, req Request) (Request, *plan, error) {
	eff := Request{Choices: map[string]model.Choice{}, State: map[string]map[string]any{}, Faults: []model.Fault{}, Expect: []string{}}
	pl := &plan{}
	var inputTpl any
	w := x.BaseWorld()
	over := &model.World{Topology: map[string][]string{}, Config: map[string]any{}, State: map[string]map[string]any{}}
	apply := func(what string, l model.WorldLayer) error {
		if err := w.Apply(l); err != nil {
			return &RequestError{fmt.Sprintf("%s: %v", what, err)}
		}
		// over echoes the overrides: config nulls stay in it as deletions.
		for c, inst := range l.Topology {
			over.Topology[c] = append([]string(nil), inst...)
		}
		for k, v := range l.Config {
			if model.IsAbsentMark(expr.Native(v)) {
				over.Config[k] = nil // §17 item 16: as a deletion
				continue
			}
			over.Config[k] = model.MergeValue(over.Config[k], expr.Native(v), true)
		}
		return nil
	}
	fixtures := func(ids []string) error {
		chain, err := x.FixtureChain(ids)
		if err != nil {
			return &RequestError{err.Error()}
		}
		for _, f := range chain {
			if err := apply("fixture "+f.ID, f.Layer()); err != nil {
				return err
			}
		}
		eff.Fixtures = append(eff.Fixtures, ids...)
		return nil
	}
	var sc *model.Scenario
	if req.Scenario != "" {
		var ok bool
		sc, ok = x.Scenarios[req.Scenario]
		if !ok {
			return eff, nil, &RequestError{fmt.Sprintf("unknown scenario %q", req.Scenario)}
		}
		eff.Scenario, eff.Flow, eff.Seed = sc.ID, sc.GroupFlow(), sc.Seed
		t, err := inputTemplate(sc.Input)
		if err != nil {
			return eff, nil, &RequestError{fmt.Sprintf("scenario input: %v", err)}
		}
		inputTpl = t
		for k, v := range sc.Choices {
			eff.Choices[k] = v
		}
		if err := fixtures(sc.Fixtures); err != nil {
			return eff, nil, err
		}
		if err := apply("scenario "+sc.ID, sc.Layer()); err != nil {
			return eff, nil, err
		}
		eff.Faults = append(eff.Faults, sc.Faults...)
		eff.Expect = append(eff.Expect, sc.Expect...)
		eff.Invariants = append(eff.Invariants, sc.Invariants...)
		pl.steps, pl.mocks = sc.Steps, sc.Mocks
		if sc.MaxVirtualMS != nil {
			pl.maxVirtualMS = *sc.MaxVirtualMS
		}
		if sc.CostLimit != nil {
			pl.costLimit = *sc.CostLimit
		}
		if sc.MaxEvents != nil {
			pl.maxEvents = int(max(1, min(*sc.MaxEvents, model.MaxMaxEvents)))
		}
		pl.applyCaps(sc) // max_iterations and max_cel_cost (§15.3)
	}
	for c, st := range w.State {
		eff.State[c] = st
	}
	if req.Flow != "" {
		if eff.Flow != "" && eff.Flow != req.Flow {
			return eff, nil, &RequestError{fmt.Sprintf("scenario %q runs flow %q, not %q", eff.Scenario, eff.Flow, req.Flow)}
		}
		eff.Flow = req.Flow
	}
	if len(pl.steps) == 0 && eff.Flow == "" {
		return eff, nil, &RequestError{"a flow or a scenario is required"}
	}
	if eff.Flow != "" || len(pl.steps) == 0 {
		flow, ok := x.Flows[eff.Flow]
		if !ok {
			return eff, nil, &RequestError{fmt.Sprintf("unknown flow %q", eff.Flow)}
		}
		if flow.Entry == nil && len(pl.steps) == 0 {
			return eff, nil, &RequestError{fmt.Sprintf("flow %q has no entry to simulate", flow.ID)}
		}
		pl.flow = flow
	}
	for i, st := range pl.steps {
		if err := checkStep(x, i, st); err != nil {
			return eff, nil, err
		}
	}
	if req.Seed != nil {
		eff.Seed = req.Seed
	}
	rt, err := inputTemplate(req.Input)
	if err != nil {
		return eff, nil, &RequestError{fmt.Sprintf("input: %v", err)}
	}
	if len(pl.steps) == 0 {
		ft, err := inputTemplate(pl.flow.Entry.Input)
		if err != nil {
			return eff, nil, &RequestError{fmt.Sprintf("flow entry input: %v", err)}
		}
		inputTpl = deepMerge(deepMerge(ft, inputTpl), rt)
	} else {
		inputTpl = rt
	}
	if inputTpl != nil {
		eff.Input, _ = json.Marshal(inputTpl)
	}
	pl.inputTpl = inputTpl
	if len(req.Choices) > 0 {
		// Scenario choices are checked by validation; a run's own must be
		// checked here, or a typo would silently fall back to the default.
		points := x.ChoicePoints()
		for _, k := range sortedKeys(req.Choices) {
			cp, ok := points[k]
			if !ok {
				return eff, nil, &RequestError{fmt.Sprintf("unknown choice point %q (keys are <interface>.<choice>)", k)}
			}
			c := req.Choices[k]
			if c.Seq != nil && len(c.Seq) == 0 {
				return eff, nil, &RequestError{fmt.Sprintf("choice %q: a choice list names at least one option", k)}
			}
			for _, o := range c.Options() {
				if !containsStr(cp.Options, o) {
					return eff, nil, &RequestError{fmt.Sprintf("choice %q has no option %q (options: %s)", k, o, strings.Join(cp.Options, ", "))}
				}
			}
			eff.Choices[k] = req.Choices[k]
		}
	}
	if err := fixtures(req.Fixtures); err != nil {
		return eff, nil, err
	}
	if len(req.Fixtures) > 0 {
		// Fixture state from the request goes under the request's own state.
		for c, st := range w.State {
			eff.State[c] = st
		}
	}
	if err := apply("request", model.WorldLayer{Topology: req.Topology, Clock: req.Clock, Config: req.Config}); err != nil {
		return eff, nil, err
	}
	for c, st := range req.State {
		// A null marks a deletion (§13.1 item 12), applied over the initial
		// state in newRun.
		if st == nil || model.IsAbsentMark(expr.Native(st)) { // §17 item 16
			eff.State[c] = nil
			continue
		}
		eff.State[c], _ = model.MergeValue(eff.State[c], expr.Native(st), true).(map[string]any)
	}
	w.State = eff.State
	eff.Faults = append(eff.Faults, req.Faults...)
	eff.Expect = append(eff.Expect, req.Expect...)
	eff.Invariants = append(eff.Invariants, req.Invariants...)
	if len(over.Topology) > 0 {
		eff.Topology = over.Topology
	}
	if len(over.Config) > 0 {
		eff.Config = over.Config
	}
	if w.EpochMS != 0 {
		eff.Clock = &model.Clock{EpochMS: w.EpochMS}
	}
	pl.world = w
	return eff, pl, nil
}

// checkStep refuses a scenario step that cannot run.
func checkStep(x *model.Index, i int, st model.ScenarioStep) error {
	switch {
	case (st.Cancel != "" || st.Restart != nil) && (st.Flow != "" || st.Interface != "" || (st.Cancel != "" && st.Restart != nil)):
		return &RequestError{fmt.Sprintf("step %d names more than one of a flow, an interface, cancel and restart", i)}
	case st.Kill != nil && (st.Flow != "" || st.Interface != "" || st.Cancel != "" || st.Restart != nil):
		return &RequestError{fmt.Sprintf("step %d names more than one of a flow, an interface, cancel, restart and kill", i)}
	case st.Close != nil && (st.Flow != "" || st.Interface != "" || st.Cancel != "" || st.Restart != nil || st.Kill != nil || st.Set != nil):
		return &RequestError{fmt.Sprintf("step %d names more than one of a flow, an interface, cancel, restart, kill, set and close", i)}
	case st.IsControl():
	case st.Flow != "" && st.Interface != "":
		return &RequestError{fmt.Sprintf("step %d names a flow and an interface", i)}
	case st.Flow != "":
		f, ok := x.Flows[st.Flow]
		if !ok {
			return &RequestError{fmt.Sprintf("step %d: unknown flow %q", i, st.Flow)}
		}
		if f.Entry == nil {
			return &RequestError{fmt.Sprintf("step %d: flow %q has no entry to simulate", i, st.Flow)}
		}
		if _, ok := x.Interfaces[f.Entry.Interface]; !ok {
			return &RequestError{fmt.Sprintf("step %d: flow %q enters unknown interface %q", i, st.Flow, f.Entry.Interface)}
		}
	case st.Interface != "":
		if _, ok := x.Interfaces[st.Interface]; !ok {
			return &RequestError{fmt.Sprintf("step %d: unknown interface %q", i, st.Interface)}
		}
		if st.Caller == "" {
			return &RequestError{fmt.Sprintf("step %d: an interface step needs a caller", i)}
		}
	default:
		return &RequestError{fmt.Sprintf("step %d names neither a flow nor an interface", i)}
	}
	return nil
}

// noDeadline is the deadline of a call tree without one.
const noDeadline = math.MaxInt64

type run struct {
	x         *model.Index
	lim       Limits
	rng       *rand.Rand
	gen       *jsonschema.Generator
	now       int64
	events    []Event
	spans     int
	callIDs   int
	ctx       map[string]any
	states    map[string]map[string]any
	choices   choiceSet
	faults    []model.Fault
	invoked   map[string]int
	compCalls map[string]int
	calls     map[string]int
	retries   int
	faultsHit int
	warnings  []string
	warned    map[string]bool
	emits     int
	loops     int
	passes    []Pass

	// §11 additions.
	epoch       int64
	config      map[string]any
	topology    map[string][]string
	groups      map[string]groupInfo // component -> its instance group, memoized
	callsByInst map[string]int       // <interface>@<instance>, named instances only
	instCalls   map[string]int       // <target>@<instance>: invocations, for instance-scoped faults
	timerSeq    int
	timers      int // timer deliveries so far
	busy        map[string][]*interval
	waiting     map[string][]*interval
	capWaiters  map[string][]*capWaiter
	queued      int
	mocks       []model.Mock
	mockSeen    []int
	mocked      int
	executed    map[string]bool
	random      func(int64) int64
	ids         *expr.IDs // id() and seq() state (§15.1)
	stepsNamed  map[string]any
	stepsList   []any
	stepResults []StepResult

	// §13.1 item 14: the scheduler, cancellation tokens, delivery lanes and
	// the starting states a restart goes back to.
	s          sched
	interleave bool // parallel branches run as interleaved tasks
	fine       bool // the clock has left whole milliseconds (§13.1 item 16)
	tokens     map[string]*token
	rdv        map[string]*rendezvousGen // open rendezvous generations by name (§13.1 item 17)
	lanes      []*lane
	spare      *lane // the lane of work outside any task (never delivered)
	initial    map[string]map[string]any

	// §13.1 item 18: channels, killed instances (by scope key), which
	// interfaces can yield, and the CEL cost limit.
	chans     map[string]*channel
	dead      map[string]scope
	yields    map[string]bool
	costLimit int64

	// §13.1 item 27: limiter state, waiters and counts.
	lims limiters

	// §13.1 item 35: calls held by a hang with forever: true, and the
	// fault-local invocation counts of faults with match or caller.
	pending    []*pendingCall
	faultCalls map[int]int
	sessions   map[string][]*sessionWait // the calls in flight by session key

	// §17 item 2: the blocking waits in progress (waits.go).
	conds []*condWait

	// §17 item 14: the exit signals of dead instances, with their payloads
	// (exits.go).
	exits map[string]map[string]any
}

func usesStepControls(steps []model.ScenarioStep) bool {
	for _, st := range steps {
		if st.Await != nil || st.IsControl() {
			return true
		}
	}
	return false
}

// usesTokens reports whether any behavior step of the document uses a
// cancellation token, a cancel, a restart, a rendezvous (§13.1 item 17), a
// streaming call, a channel or a kill (§13.1 item 18).
func usesTokens(doc *model.Document) bool {
	var walk func([]model.Step) bool
	walk = func(steps []model.Step) bool {
		for i := range steps {
			s := &steps[i]
			if s.Token != "" || s.Cancel != "" || s.Restart != nil || s.Rendezvous != "" ||
				s.Stream || s.Put != "" || s.Receive != "" || s.Kill != nil || s.Session != "" || s.Close != nil {
				return true
			}
			if walk(s.Then) || walk(s.Else) || walk(s.Steps) || walk(s.OnLate) || walk(s.OnItem) {
				return true
			}
			if s.OnError != nil && walk(s.OnError.Steps) {
				return true
			}
			for _, b := range s.Branches {
				if walk(b) {
					return true
				}
			}
			for _, k := range sortedKeys(s.Options) {
				if walk(s.Options[k]) {
					return true
				}
			}
		}
		return false
	}
	for i := range doc.Interfaces {
		if walk(doc.Interfaces[i].Behavior) {
			return true
		}
	}
	return false
}

// usesKills reports whether a run's faults include a kill (§13.1 item 18).
func usesKills(faults []model.Fault) bool {
	for _, f := range faults {
		if f.Type == model.FaultKill {
			return true
		}
	}
	return false
}

// newLane creates a delivery lane for a root task.
func (r *run) newLane() *lane {
	ln := &lane{}
	r.lanes = append(r.lanes, ln)
	return ln
}

func newRun(x *model.Index, lim Limits, seed int64, eff Request, pl *plan) *run {
	rng := rand.New(rand.NewPCG(uint64(seed), 0x9E3779B97F4A7C15))
	// random(n) draws from its own stream, so using it never shifts the
	// fake data and latencies drawn from rng.
	crng := rand.New(rand.NewPCG(uint64(seed), 0x2545F4914F6CDD1D))
	r := &run{
		x: x, lim: lim, rng: rng, gen: &jsonschema.Generator{Rng: rng, Resolve: x.SchemaRef()},
		ctx: map[string]any{}, states: map[string]map[string]any{}, choices: newChoiceSet(eff.Choices), faults: eff.Faults,
		invoked: map[string]int{}, compCalls: map[string]int{}, calls: map[string]int{}, warned: map[string]bool{},
		epoch: pl.world.EpochMS, config: pl.world.Config, topology: pl.world.Topology, groups: map[string]groupInfo{},
		callsByInst: map[string]int{}, instCalls: map[string]int{}, busy: map[string][]*interval{}, waiting: map[string][]*interval{},
		capWaiters: map[string][]*capWaiter{}, mocks: pl.mocks, mockSeen: make([]int, len(pl.mocks)), executed: map[string]bool{},
		random: func(n int64) int64 { return crng.Int64N(n) }, ids: expr.NewIDs(seed), stepsNamed: map[string]any{}, stepsList: []any{},
		tokens: map[string]*token{}, rdv: map[string]*rendezvousGen{},
		chans: map[string]*channel{}, dead: map[string]scope{}, exits: map[string]map[string]any{}, yields: map[string]bool{}, costLimit: pl.costLimit,
		lims: newLimiters(x.Doc),
	}
	if r.costLimit <= 0 {
		r.costLimit = expr.DefaultCostLimit
	}
	// max_virtual_ms (§13.1 item 14) bounds a run when its scenario sets
	// it. The default (an hour) bounds only scenarios with the new step
	// controls (await, cancel or restart steps): runs that use none could
	// already run for hours, and the event and timer budgets end them.
	r.s = sched{idle: make(chan struct{}), live: map[int]*task{}, limit: math.MaxInt64}
	switch {
	case pl.maxVirtualMS > 0:
		r.s.limit = pl.maxVirtualMS * 1000
	case usesStepControls(pl.steps):
		r.s.limit = model.DefaultMaxVirtualMS * 1000
	}
	// parallel branches run as interleaved tasks in runs that use the
	// §13.1 item 14 features; other runs keep the sequential branches they
	// were written against (DESIGN §13.1 item 14, engine choices).
	r.interleave = pl.maxVirtualMS > 0 || usesStepControls(pl.steps) || usesTokens(x.Doc) || usesKills(eff.Faults) ||
		model.UsesBlockingWaits(x.Doc)
	if r.config == nil {
		r.config = map[string]any{}
	}
	for _, c := range x.Doc.Components {
		if c.State != nil {
			init, ok := deepCopy(expr.Native(c.State.Initial)).(map[string]any)
			if !ok || init == nil {
				init = map[string]any{}
			}
			for _, inst := range r.instancesOf(c.ID) {
				r.states[model.StateKey(c.ID, inst)] = deepCopy(init).(map[string]any)
			}
		}
	}
	// Overrides keyed by a component apply to each of its instances; those
	// keyed <component>@<instance> then apply to that instance alone.
	keys := sortedKeys(pl.world.State)
	for _, plain := range []bool{true, false} {
		for _, k := range keys {
			c, inst := model.SplitStateKey(k)
			if (inst == "") != plain {
				continue
			}
			targets := []string{k}
			if plain {
				targets = targets[:0]
				for _, i := range r.instancesOf(c) {
					targets = append(targets, model.StateKey(c, i))
				}
			}
			if pl.world.State[k] == nil {
				continue // a null override: the initial state applies
			}
			for _, key := range targets {
				merged, _ := model.MergeValue(r.states[key], pl.world.State[k], false).(map[string]any)
				if merged == nil {
					merged = map[string]any{}
				}
				r.states[key] = merged
			}
		}
	}
	return r
}

func (r *run) nextCall() int { r.callIDs++; return r.callIDs }

// state returns the state of a component instance by its state key.
func (r *run) state(key string) map[string]any {
	s, ok := r.states[key]
	if !ok {
		s = map[string]any{}
		r.states[key] = s
	}
	return s
}

func (r *run) warn(msg string) {
	if r.warned[msg] || len(r.warnings) >= 100 {
		return
	}
	r.warned[msg] = true
	r.warnings = append(r.warnings, msg)
}

func (r *run) ev(e Event) error {
	if len(r.events) >= r.lim.MaxEvents {
		return &abortError{msg: fmt.Sprintf("event budget of %d exceeded", r.lim.MaxEvents), events: true}
	}
	e.Seq = len(r.events) + 1
	// Durations arrive in µs (§13.1 item 16) and leave as floor(us/1000).
	e.T, e.tUS = msFloor(r.now), r.now
	e.durUS, e.DurationMS = e.DurationMS, msFloor(e.DurationMS)
	e.WaitMS, e.BackoffMS = msFloor(e.WaitMS), msFloor(e.BackoffMS)
	if e.Branch == nil {
		if b := r.curBranch(); b != nil {
			bi := *b
			e.Branch = &bi
		}
	}
	if !e.Late && r.lateNow(e.tUS) {
		e.Late = true
	}
	r.events = append(r.events, e)
	if len(r.conds) > 0 {
		r.condEvent(&r.events[len(r.events)-1]) // §17 item 2, waits.go
	}
	return nil
}

func (r *run) fake(ref any) any {
	s, ok := r.x.ResolveSchema(ref)
	if !ok {
		return nil
	}
	return r.gen.Generate(s)
}

func (r *run) checkSchema(ref any, v any, what string) {
	s, ok := r.x.ResolveSchema(ref)
	if !ok {
		return
	}
	for _, m := range jsonschema.Validate(s, v, r.x.SchemaRef()) {
		r.warn(what + ": " + m)
	}
}

// topInt evaluates a millisecond number-or-template field outside any
// behavior (an entry's or a scenario step's deadline_ms), in µs. Negative
// values count as 0.
func (r *run) topInt(v model.IntOrExpr, env *expr.Env, act map[string]any, what string) (int64, error) {
	if !v.IsExpr() {
		return max(r.numUS(v), 0), nil
	}
	out, err := env.Eval(strings.TrimSpace(v.Expr), act)
	if err != nil {
		return 0, abortf("%s: %v", what, err)
	}
	n, ok := r.valueUS(out)
	if !ok {
		return 0, abortf("%s: must give a number, got %T", what, out)
	}
	return max(n, 0), nil
}

// topAct is the activation of a template evaluated outside any behavior:
// an entry input or, with steps, a scenario step's input and on.
func (r *run) topAct(input any, steps any) map[string]any {
	act := map[string]any{"input": input, "state": map[string]any{}, "ctx": r.ctx, "vars": map[string]any{}, "attempt": int64(1),
		"now": msValue(r.epoch, r.now), "now_us": r.epoch*1000 + r.now, "error": nil, "self": "", "deadline": nil, "config": r.config, expr.RandomKey: r.random,
		expr.CanceledKey: r.isCanceled, expr.ChannelLenKey: r.channelLen, expr.CostLimitKey: r.costLimit, "limiters": r.limitersValue(), expr.IDsKey: r.ids}
	if steps != nil {
		act["steps"] = steps
		act["pass"] = int64(1) // a repeated step's pass sets its own (§13.1 item 27)
	}
	return act
}

func (r *run) expectations(exprs []string, s Summary) []Assertion {
	calls := map[string]any{}
	byInst := map[string]any{}
	for id, f := range r.x.Interfaces {
		calls[id] = int64(r.calls[id])
		for _, inst := range r.instancesOf(f.Component) {
			if inst != "" {
				k := id + "@" + inst
				byInst[k] = int64(r.callsByInst[k])
			}
		}
	}
	for k, n := range r.callsByInst {
		byInst[k] = int64(n)
	}
	// A nil *Error must be CEL null, not a typed-nil (empty) map, so that
	// result.error == null holds on success as it does for vars.x.error.
	result := outcomeMap(s.Result)
	states := map[string]any{}
	for c, st := range s.State {
		states[c] = st
	}
	warnings := make([]any, len(s.Warnings))
	for i, w := range s.Warnings {
		warnings[i] = w
	}
	passes := make([]any, len(r.passes))
	for i, ps := range r.passes {
		passes[i] = map[string]any{"pass": int64(ps.Pass), "start_ms": ps.StartMS, "start_us": ps.startUS, "duration_ms": ps.DurationMS, "duration_us": ps.durUS,
			"result": outcomeMap(ps.Result)}
	}
	topology := map[string]any{}
	for c, inst := range r.topology {
		l := make([]any, len(inst))
		for i, n := range inst {
			l[i] = n
		}
		topology[c] = l
	}
	act := map[string]any{"result": result, "status": s.Status, "calls": calls, "ctx": s.Ctx, "state": states,
		"retries": int64(s.Retries), "faults": int64(s.Faults), "duration_ms": s.DurationMS, "duration_us": r.s.end, "warnings": warnings, "passes": passes,
		"config": r.config, "topology": topology, "calls_by_instance": byInst, "steps": expr.NewSteps(r.stepsNamed, r.stepsList),
		"trace": []any{}, "io": []any{}, expr.IDsKey: r.ids, expr.RandomKey: r.random, expr.CanceledKey: r.isCanceled, expr.ChannelLenKey: r.channelLen,
		expr.CostLimitKey: r.costLimit, "limiters": r.limitersValue(), "limits": r.limitsValue()}
	for _, e := range exprs {
		if strings.Contains(e, "trace") {
			act["trace"] = r.traceValue()
			break
		}
	}
	if mentionsIO(exprs) {
		act["io"] = r.ioValue()
	}
	out := []Assertion{}
	for _, e := range exprs {
		ok, err := expr.Expect.EvalBool(e, act)
		a := Assertion{Expr: e, Passed: ok && err == nil}
		if err != nil {
			a.Error = err.Error()
		}
		out = append(out, a)
	}
	return out
}

// traceValue is the trace as expectations see it (§11.8).
func (r *run) traceValue() []any {
	out := make([]any, len(r.events))
	for i, e := range r.events {
		var errv, branch, index any
		if e.Error != nil {
			errv = e.Error.Map()
		}
		if e.Branch != nil {
			branch = int64(*e.Branch)
		}
		if e.Index != nil {
			index = *e.Index
		}
		out[i] = map[string]any{"seq": int64(e.Seq), "t": e.T, "t_us": e.tUS, "duration_us": e.durUS, "type": e.Type, "interface": e.Interface, "component": e.Component,
			"instance": e.Instance, "input": e.Input, "output": e.Output, "error": errv, "late": e.Late, "title": e.Title,
			"key": e.Key, "table": e.Table, "option": e.Option, "mock": e.Mock, "topic": e.Topic, "branch": branch, "wait_ms": e.WaitMS, "index": index}
	}
	return out
}

func outcomeMap(o Outcome) map[string]any {
	var errv any
	if o.Error != nil {
		errv = o.Error.Map()
	}
	return map[string]any{"ok": o.OK, "value": o.Value, "error": errv}
}

func toError(v any) *Error {
	switch t := v.(type) {
	case map[string]any:
		e := &Error{Data: t["data"]}
		e.Code, _ = t["code"].(string)
		e.Message, _ = t["message"].(string)
		e.Retryable, _ = t["retryable"].(bool)
		if h, ok := t["headers"].(map[string]any); ok {
			e.Headers = lowerHeaders(h)
		}
		switch st := t["status"].(type) {
		case int64:
			e.Status = int(st)
		case float64:
			e.Status = int(st)
		}
		if e.Code == "" {
			e.Code = "error"
		}
		return e
	case string:
		return &Error{Code: t}
	case nil:
		return &Error{Code: "error"}
	}
	return &Error{Code: "error", Message: fmt.Sprint(v)}
}

func assign(root map[string]any, segs []string, val any) any {
	m := root
	for _, s := range segs[:len(segs)-1] {
		next, ok := m[s].(map[string]any)
		if !ok {
			next = map[string]any{}
			m[s] = next
		}
		m = next
	}
	last := segs[len(segs)-1]
	old := m[last]
	m[last] = val
	return old
}

func deepCopy(v any) any {
	switch t := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, x := range t {
			out[k] = deepCopy(x)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			out[i] = deepCopy(x)
		}
		return out
	}
	return v
}

// deepMerge overlays over on base: maps merge recursively, anything else in
// over replaces base, and a nil over keeps base.
func deepMerge(base, over any) any {
	if over == nil {
		return deepCopy(base)
	}
	bm, ok1 := base.(map[string]any)
	om, ok2 := over.(map[string]any)
	if !ok1 || !ok2 {
		return deepCopy(over)
	}
	out := deepCopy(bm).(map[string]any)
	for k, v := range om {
		out[k] = deepMerge(out[k], v)
	}
	return out
}

func cloneStates(s map[string]map[string]any) map[string]map[string]any {
	out := make(map[string]map[string]any, len(s))
	for k, v := range s {
		out[k] = deepCopy(v).(map[string]any)
	}
	return out
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func containsStr(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

func containsInt(list []int, n int) bool {
	for _, x := range list {
		if x == n {
			return true
		}
	}
	return false
}

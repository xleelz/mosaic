package sim

import (
	"fmt"
	"regexp"
	"strconv"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// runSteps runs the steps of a multi-step scenario (§11.7, §13.1 item 14)
// as a driver task. Each flow or interface step runs as its own task with
// its own delivery lane. A step with at_ms starts at that time, even while
// earlier steps or timers are still running, in every run (§17 item 9). A
// step without it starts once the previous step has ended: its call tree
// has finished and its emits and timers are delivered (at once after a
// step with await: false). Cancel and restart steps run in the driver.
// State, ctx, the clock and capacity are shared. The result is the last
// step's, once every task has finished.
func (r *run) runSteps(steps []model.ScenarioStep) (callResult, error) {
	n := len(steps)
	results := make([]*callResult, n)
	r.stepResults = make([]StepResult, n)
	r.stepsList = make([]any, n)
	recorded := make([]bool, n)
	driver := r.s.cur
	var prev *task     // the previous step's task, if it is awaited
	var prevDone *bool // whether its call tree has finished
	awaiting := -1     // the step the driver is parked for
	for i, st := range steps {
		key := st.As
		if key == "" {
			key = strconv.Itoa(i)
		}
		// An at_ms step starts on time, whatever is still running, in
		// every run (§13.1 item 14, §17 item 9); a step without it waits
		// for the previous step to end.
		if prev != nil && st.AtMS == nil {
			// The previous step ends when its emits and timers are
			// delivered, or when everything else is an idle consumer (a
			// loop blocked on a receive with no timeout never ends).
			awaiting = i - 1
			for !*prevDone && !r.quietFor(driver) {
				r.s.quiet = driver
				err := r.park(noDeadline, 0)
				if r.s.quiet == driver {
					r.s.quiet = nil
				}
				if err != nil {
					return callResult{}, err
				}
			}
			awaiting = -1
		}
		if st.AtMS != nil {
			at := r.msToUS(*st.AtMS)
			if jat := r.xpJitter(at); jat < r.now { // jat is at without a schedule (§15.5)
				if at < r.now {
					r.warn(fmt.Sprintf("step %s: at_ms %s is before the previous step ended (%s); started at %s", key, fmtMS(at), fmtMS(r.now), fmtMS(r.now)))
				}
			} else if err := r.sleepUntil(jat); err != nil {
				return callResult{}, err
			}
		}
		prev, prevDone = nil, nil
		start := r.now
		// A step's limiter seeds apply when it starts (§13.1 item 27).
		if err := r.seedLimiters(st.Limiters, fmt.Sprintf("steps[%d]", i)); err != nil {
			return callResult{}, err
		}
		if st.IsControl() {
			if err := r.controlStep(i, key, st, start); err != nil {
				return callResult{}, err
			}
			res := callResult{ok: true}
			results[i] = &res
			r.recordStep(i, st, "", "", res, start, start)
			recorded[i] = true
			continue
		}
		sp, err := r.prepareStep(i, key, st)
		if err != nil {
			return callResult{}, err
		}
		done := false    // the step has ended: its call tree, emits and timers
		reached := false // its call tree finished
		idx := i
		finish := func(res callResult, end int64) {
			results[idx] = &res
			r.recordStep(idx, st, sp.target, sp.inst, res, start, end)
			recorded[idx] = true
			done = true
			if awaiting == idx {
				r.wakeAt(driver, max(r.now, driver.parked), 0)
			}
		}
		t := r.spawn(kindRoot, start, nil, func(t *task) error {
			err := r.runStep(sp, start, finish)
			reached = err == nil
			return err
		})
		t.lane, t.choice = sp.lane, sp.choices
		t.stepLane, t.stepIdx = st.Lane, i // program order under exploration (§17 item 11)
		t.lane.choice = sp.choices
		if f, ok := r.x.Interfaces[sp.target]; ok {
			t.homeComp, t.homeInst = f.Component, sp.inst
		}
		t.onDone = append(t.onDone, func() {
			if !reached && !recorded[idx] && t.hung {
				// Its call never answered (§13.1 item 35).
				finish(callResult{pending: true, target: sp.target}, r.now)
			} else if !reached && !recorded[idx] {
				// Killed by a restart or the end of the run.
				finish(callResult{err: &Error{Code: "canceled", Message: fmt.Sprintf("step %s was canceled", sp.key)}, target: sp.target}, r.now)
			}
		})
		if st.Awaited() {
			prev, prevDone = t, &done
		}
	}
	// The run's result is the last step's, once every task has finished.
	if err := r.waitQuiet(); err != nil {
		return callResult{}, err
	}
	if res := results[n-1]; res != nil {
		return *res, nil
	}
	return callResult{}, nil
}

// stepPlan is a flow or interface step resolved when it starts.
type stepPlan struct {
	key, target, caller, inst string
	bad                       bool
	input                     any
	deadline                  int64
	choices                   choiceSet
	lane                      *lane
	repeat                    *model.Repeat
	// A repeated step's input and choices may read pass (§13.1 item 27):
	// tpl is re-evaluated over fake for each pass when it mentions pass,
	// and the choice expressions in exprChoices over base.
	tpl, fake   any
	passInput   bool
	base        choiceSet
	exprChoices map[string]model.Choice
	index       int
}

// prepareStep evaluates a step's input, instance and deadline at its start.
// Templates see the steps that have finished so far.
func (r *run) prepareStep(i int, key string, st model.ScenarioStep) (*stepPlan, error) {
	start := r.now
	caller, target, flowOn := st.Caller, st.Interface, ""
	var tpl any
	var entryDeadline model.IntOrExpr
	if st.Flow != "" {
		e := r.x.Flows[st.Flow].Entry
		caller, target, flowOn, entryDeadline = e.Caller, e.Interface, e.On, e.DeadlineMS
		t, err := inputTemplate(e.Input)
		if err != nil {
			return nil, &RequestError{fmt.Sprintf("step %s: flow entry input: %v", key, err)}
		}
		tpl = t
	}
	t, err := inputTemplate(st.Input)
	if err != nil {
		return nil, &RequestError{fmt.Sprintf("step %s: input: %v", key, err)}
	}
	tpl = deepMerge(tpl, t)
	entry := r.x.Interfaces[target]
	stepsVal := r.stepsValue()
	input := r.fake(entry.Request)
	fake := deepCopy(input)
	if tpl != nil {
		v, err := expr.Step.Template(tpl, r.topAct(nil, stepsVal))
		if err != nil {
			return nil, abortf("steps[%d].input: %v", i, err)
		}
		input = resolveInput(deepMerge(input, v))
	}
	env := expr.Step
	on := st.On
	if on == "" {
		on, env = flowOn, expr.Behavior
	}
	act := r.topAct(input, nil)
	if env == expr.Step {
		act["steps"] = stepsVal
	}
	inst, bad, err := r.entryInstance(entry, on, env, act)
	if err != nil {
		return nil, abortf("steps[%d].on: %v", i, err)
	}
	deadline := int64(noDeadline)
	for _, dl := range []model.IntOrExpr{entryDeadline, st.DeadlineMS} {
		if dl.IsZero() {
			continue
		}
		d, err := r.topInt(dl, expr.Step, r.topAct(input, stepsVal), fmt.Sprintf("steps[%d].deadline_ms", i))
		if err != nil {
			return nil, err
		}
		deadline = min(deadline, start+d)
	}
	choices := r.choices
	var exprChoices map[string]model.Choice
	if len(st.Choices) > 0 {
		plain := map[string]model.Choice{}
		for k, c := range st.Choices {
			if _, ok := expr.ExprOf(c.Option); ok && c.IsScalar() {
				if exprChoices == nil {
					exprChoices = map[string]model.Choice{}
				}
				exprChoices[k] = c
			} else {
				plain[k] = c
			}
		}
		choices = choices.with(plain)
	}
	base := choices
	if exprChoices != nil {
		over, err := r.passChoices(exprChoices, 1, fmt.Sprintf("steps[%d]", i))
		if err != nil {
			return nil, err
		}
		choices = base.with(over)
	}
	// A step repeats only as its own repeat says (§13.1 item 24): a flow
	// step makes one pass of its entry whatever the entry's repeat, since
	// scenarios step a repeating flow one pass at a time.
	rp := st.Repeat
	return &stepPlan{key: key, target: target, caller: caller, inst: inst, bad: bad, input: input, deadline: deadline,
		choices: choices, lane: r.newLane(), repeat: rp, tpl: tpl, fake: fake, passInput: rp != nil && mentionsPass(tpl),
		base: base, exprChoices: exprChoices, index: i}, nil
}

// runStep runs a step's call tree in its task, then opens its lane. The
// step ends, and finish is called, once the lane has delivered the emits
// and timers it scheduled.
func (r *run) runStep(sp *stepPlan, start int64, finish func(callResult, int64)) error {
	entry := r.x.Interfaces[sp.target]
	if err := r.ev(Event{Type: "step.start", Key: sp.key, Component: sp.caller, From: sp.caller, To: entry.Component, Interface: sp.target,
		Instance: sp.inst, Input: deepCopy(sp.input)}); err != nil {
		return err
	}
	// A repeating step (§13.1 item 24) calls its target count times, each
	// pass interval_ms after the previous pass's call tree finished, with
	// its deadline counted from the pass's start. The lane opens after the
	// first pass, so earlier passes' emits and timers are delivered as the
	// clock advances; the step ends when the last pass and every delivery
	// have finished, and its result is the last pass's.
	passes, interval := 1, int64(0)
	if rp := sp.repeat; rp != nil {
		passes, interval = max(1, min(rp.Count, model.MaxRepeatCount)), max(r.msToUS(rp.IntervalMS), 0)
		if err := r.sleep(max(r.msToUS(rp.InitialDelayMS), 0)); err != nil {
			return err
		}
	}
	var res callResult
	for i := 0; i < passes; i++ {
		if i > 0 {
			r.openLane(sp.lane)
			if err := r.sleep(interval); err != nil {
				return err
			}
		}
		deadline := sp.deadline
		if deadline != noDeadline {
			deadline += r.now - start
		}
		if i > 0 {
			if err := r.nextPass(sp, i+1); err != nil {
				return err
			}
		}
		var err error
		res, err = r.invoke(callSpec{from: sp.caller, target: sp.target, inst: sp.inst, badInst: sp.bad, input: deepCopy(sp.input),
			callID: r.nextCall(), attempt: 1, depth: 1, deadline: deadline})
		if err != nil {
			return err
		}
	}
	sp.lane.settled = func() {
		if !r.s.stopped || r.interleave {
			ok := res.ok
			if err := r.ev(Event{Type: "step.end", Key: sp.key, Component: entry.Component, From: sp.caller, To: entry.Component, Interface: sp.target,
				Instance: sp.inst, OK: &ok, Output: deepCopy(res.value), Error: res.err, DurationMS: r.now - start}); err != nil {
				r.fail(err)
			}
		}
		finish(res, r.now)
	}
	// In every run a step ends once its emits and timers are delivered, so
	// a scenario means the same whether or not the run is concurrent; only
	// at_ms and await: false overlap steps.
	r.openLane(sp.lane)
	r.settle(sp.lane)
	return nil
}

// controlStep runs a cancel, restart or kill step in the driver.
func (r *run) controlStep(i int, key string, st model.ScenarioStep, start int64) error {
	if st.Set != nil {
		return r.setStep(i, st) // §15.3, sim153.go
	}
	act := r.topAct(nil, r.stepsValue())
	if st.Cancel != "" {
		name := st.Cancel
		if src, ok := expr.ExprOf(name); ok {
			v, err := expr.Step.Eval(src, act)
			if err != nil {
				return abortf("steps[%d].cancel: %v", i, err)
			}
			s, ok := v.(string)
			if !ok || s == "" {
				return abortf("steps[%d].cancel: a token name must be a non-empty string, got %#v", i, v)
			}
			name = s
		}
		return r.cancel(name, "", "", 0)
	}
	what, comp, inst := "restart", "", ""
	if st.Kill != nil {
		what, comp, inst = "kill", st.Kill.Component, st.Kill.Instance
	} else {
		comp, inst = st.Restart.Component, st.Restart.Instance
	}
	if src, ok := expr.ExprOf(inst); ok {
		v, err := expr.Step.Eval(src, act)
		if err != nil {
			return abortf("steps[%d].%s.instance: %v", i, what, err)
		}
		s, ok := v.(string)
		if !ok {
			return abortf("steps[%d].%s.instance: must give an instance name, got %T", i, what, v)
		}
		inst = s
	}
	if st.Kill != nil {
		return r.killInstance(comp, inst, "", "", 0, fmt.Sprintf("steps[%d].kill", i))
	}
	return r.restart(st.Restart, inst, "", "", 0, fmt.Sprintf("steps[%d].restart", i))
}

// recordStep records a finished step's result for the summary, for
// expectations and for later steps' templates.
func (r *run) recordStep(i int, st model.ScenarioStep, target, inst string, res callResult, start, end int64) {
	status := "ok"
	switch {
	case res.pending:
		status = "pending"
	case !res.ok:
		status = "error"
	}
	sr := StepResult{As: st.As, Flow: st.Flow, Interface: target, On: inst, Result: res.outcome(), Status: status,
		StartMS: msFloor(start), DurationMS: msFloor(end - start), durUS: end - start}
	r.stepResults[i] = sr
	v := map[string]any{"result": outcomeMap(sr.Result), "status": status, "duration_ms": sr.DurationMS, "start_ms": sr.StartMS,
		"duration_us": end - start, "start_us": start,
		"as": st.As, "flow": st.Flow, "interface": target, "on": inst}
	r.stepsList[i] = v
	if st.As != "" {
		r.stepsNamed[st.As] = v
	}
}

// stepsValue is CEL steps: the steps finished so far, by name and position.
func (r *run) stepsValue() any {
	return expr.NewSteps(r.stepsNamed, r.stepsList)
}

// passRE finds the identifier pass in CEL source.
var passRE = regexp.MustCompile(`(?:^|[^A-Za-z0-9_.])pass(?:[^A-Za-z0-9_]|$)`)

// mentionsPass reports whether a step template reads pass (§13.1 item 27).
func mentionsPass(tpl any) bool {
	for _, src := range expr.TemplateExprs(tpl) {
		if passRE.MatchString(src) {
			return true
		}
	}
	return false
}

// passChoices evaluates a step's choice expressions for pass n: each gives
// an option name.
func (r *run) passChoices(choices map[string]model.Choice, n int, what string) (map[string]model.Choice, error) {
	act := r.topAct(nil, r.stepsValue())
	act["pass"] = int64(n)
	out := map[string]model.Choice{}
	for _, k := range sortedKeys(choices) {
		src, _ := expr.ExprOf(choices[k].Option)
		v, err := expr.Step.Eval(src, act)
		if err != nil {
			return nil, abortf("%s.choices.%s: %v", what, k, err)
		}
		o, ok := v.(string)
		if !ok {
			return nil, abortf("%s.choices.%s: must give an option name, got %T", what, k, v)
		}
		out[k] = model.ChoiceOf(o)
	}
	return out, nil
}

// nextPass prepares pass n (from 2) of a repeated step: its input and its
// choice expressions see pass (§13.1 item 27).
func (r *run) nextPass(sp *stepPlan, n int) error {
	what := fmt.Sprintf("steps[%d]", sp.index)
	if sp.passInput {
		act := r.topAct(nil, r.stepsValue())
		act["pass"] = int64(n)
		v, err := expr.Step.Template(sp.tpl, act)
		if err != nil {
			return abortf("%s.input: %v", what, err)
		}
		sp.input = resolveInput(deepMerge(sp.fake, v))
	}
	if sp.exprChoices != nil {
		over, err := r.passChoices(sp.exprChoices, n, what)
		if err != nil {
			return err
		}
		sp.choices = sp.base.with(over)
		if t := r.s.cur; t != nil {
			t.choice = sp.choices
		}
		sp.lane.choice = sp.choices
	}
	return nil
}

// evalChoices resolves the run's choice expressions (scenario choices
// written "=cel", §13.1 item 27) once, before the run starts, as pass 1.
func (r *run) evalChoices() error {
	exprs := map[string]model.Choice{}
	for k, sl := range r.choices {
		if _, ok := expr.ExprOf(sl.c.Option); ok && sl.c.IsScalar() {
			exprs[k] = sl.c
		}
	}
	if len(exprs) == 0 {
		return nil
	}
	over, err := r.passChoices(exprs, 1, "scenario")
	if err != nil {
		return &RequestError{err.Error()}
	}
	for k, c := range over {
		r.choices[k] = &choiceSlot{c: c}
	}
	return nil
}

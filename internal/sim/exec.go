package sim

import (
	"errors"
	"fmt"
	"math"
	"path"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

type callResult struct {
	ok     bool
	value  any
	err    *Error
	target string
	// pending marks a scenario step whose call never answered (a hang with
	// forever: true, §13.1 item 35): not ok, and no error.
	pending bool
	cancel  *cancelMark // set when the call was canceled (§16.4)
}

// callSpec is one invocation of an interface.
type callSpec struct {
	from      string // the calling component
	fromInst  string // the caller's instance
	fromIface string // the calling interface; "" for a scenario step or flow entry (§13.1 item 35)
	session   string // the session key the call carries (§13.1 item 35); "" for none
	target    string // the interface
	inst      string // the callee's instance
	badInst   bool   // inst is not an instance of the callee: the call fails with unknown_instance
	input     any
	parent    int
	callID    int
	attempt   int
	depth     int
	timeout   int64 // the caller's timeout_ms; 0 means none
	deadline  int64 // the absolute deadline in virtual ms; noDeadline means none
	async     bool
	stream    *stream     // a streaming caller's stream (§13.1 item 18)
	cancel    *cancelMark // marked when a token or session cancels the call (§16.4)
}

// latency returns the service time of one call: fixed, a seeded draw from
// a range, or (§11.3) a CEL expression over input, state, config and self.
func (r *run) latency(f *model.Interface, input any, inst string, deadline int64) (int64, error) {
	if f.LatencyMS == nil {
		return 1000, nil // 1 ms
	}
	if l := f.LatencyMS; l.Expr != "" {
		fr := &frame{iface: f, comp: f.Component, inst: inst, skey: model.StateKey(f.Component, inst), input: input,
			vars: map[string]any{}, deadline: deadline}
		v, err := expr.Behavior.Eval(strings.TrimSpace(l.Expr), r.act(fr, 1))
		if err != nil {
			return 0, abortf("%s.latency_ms: %v", f.ID, err)
		}
		n, ok := r.valueUS(v)
		if !ok {
			return 0, abortf("%s.latency_ms: must give milliseconds, got %T", f.ID, v)
		}
		return max(n, 0), nil
	}
	lo, hi := f.LatencyMS.Min, f.LatencyMS.Max
	if hi <= lo {
		return r.msToUS(lo), nil
	}
	if lo == math.Trunc(lo) && hi == math.Trunc(hi) {
		// Whole milliseconds draw as before, in ms.
		return (int64(lo) + r.rng.Int64N(int64(hi)-int64(lo)+1)) * 1000, nil
	}
	a, b := r.msToUS(lo), r.msToUS(hi)
	return a + r.rng.Int64N(b-a+1), nil
}

// outcomeLatency spends an interface's latency_by_outcome time (§14.13)
// once its behavior has ended with res: the first entry whose when holds
// over result, input and config gives the ms, and the trace records it with
// a latency event; when none matches, latency_ms applies. The caller's
// timeout and deadline see this time like any other service time.
func (r *run) outcomeLatency(fr *frame, res callResult) error {
	f := fr.iface
	var errv any
	if res.err != nil {
		errv = res.err.Map()
	}
	act := r.act(fr, 1)
	act["result"] = map[string]any{"ok": res.ok, "value": res.value, "error": errv}
	for i, o := range f.LatencyByOutcome {
		p := fmt.Sprintf("%s.latency_by_outcome[%d]", f.ID, i)
		ok, err := expr.Outcome.EvalBool(o.When, act)
		if err != nil {
			return abortf("%s.when: %v", p, err)
		}
		if !ok {
			continue
		}
		var lat int64
		if o.MS.Expr != "" {
			v, err := expr.Outcome.Eval(strings.TrimSpace(o.MS.Expr), act)
			if err != nil {
				return abortf("%s.ms: %v", p, err)
			}
			n, ok := r.valueUS(v)
			if !ok {
				return abortf("%s.ms: must give milliseconds, got %T", p, v)
			}
			lat = max(n, 0)
		} else {
			lat = max(r.msToUS(o.MS.Min), 0)
		}
		if err := r.ev(Event{Type: "latency", Span: fr.span, Component: fr.comp, Interface: f.ID, Key: fmt.Sprintf("latency_by_outcome[%d]", i),
			Detail: o.When, DurationMS: lat, Message: fmt.Sprintf("latency_by_outcome[%d] (%s): %s ms", i, o.When, fmtMS(lat)),
			Instance: fr.inst}); err != nil {
			return err
		}
		return r.sleep(lat)
	}
	lat, err := r.latency(f, fr.input, fr.inst, fr.deadline)
	if err != nil {
		return err
	}
	return r.sleep(lat)
}

// matchFault returns the first fault that applies to this invocation. A
// fault with an instance applies only there, and its calls count the
// invocations on that instance. A fault with match or caller (§13.1 item
// 35) applies only to the calls they accept, and its calls count those.
func (r *run) matchFault(f *model.Interface, c callSpec) (*model.Fault, error) {
	inst := c.inst
	for i := range r.faults {
		ft := &r.faults[i]
		if ft.Type == model.FaultKill {
			continue // a kill is due at its time, not per call (§13.1 item 18)
		}
		if ft.Instance != "" && ft.Instance != inst {
			continue
		}
		var n int
		switch ft.Target {
		case f.ID:
			n = r.invoked[f.ID]
		case f.Component:
			n = r.compCalls[f.Component]
		default:
			continue
		}
		if ft.Instance != "" {
			n = r.instCalls[ft.Target+"@"+inst]
		}
		if ft.Match != "" || ft.Caller != "" {
			ok, err := r.faultAccepts(ft, i, f, c)
			if err != nil || !ok {
				if err != nil {
					return nil, err
				}
				continue
			}
			if r.faultCalls == nil {
				r.faultCalls = map[int]int{}
			}
			r.faultCalls[i]++
			n = r.faultCalls[i]
		}
		if len(ft.Calls) == 0 || containsInt(ft.Calls, n) {
			return ft, nil
		}
	}
	return nil, nil
}

// faultAccepts reports whether a call passes a fault's caller and match
// (§13.1 item 35). caller is matched, as an id or a glob, against the
// calling interface, or against the caller component of a scenario step
// or flow entry. match is CEL over the call's input, with the callee's
// state, config and self.
func (r *run) faultAccepts(ft *model.Fault, i int, f *model.Interface, c callSpec) (bool, error) {
	if ft.Caller != "" {
		from := c.fromIface
		if from == "" {
			from = c.from
		}
		if ok, _ := path.Match(ft.Caller, from); !ok {
			return false, nil
		}
	}
	if ft.Match == "" {
		return true, nil
	}
	fr := &frame{iface: f, comp: f.Component, inst: c.inst, skey: model.StateKey(f.Component, c.inst), input: c.input,
		vars: map[string]any{}, deadline: c.deadline}
	ok, err := expr.Behavior.EvalBool(ft.Match, r.act(fr, c.attempt))
	if err != nil {
		return false, abortf("faults[%d].match: %v", i, err)
	}
	return ok, nil
}

// matchMock returns the outcome of the first scenario mock (§11.8) that
// replaces this call, if any.
func (r *run) matchMock(fr *frame) (*callResult, error) {
	for i := range r.mocks {
		m := &r.mocks[i]
		if m.Interface != fr.iface.ID || (m.Instance != "" && m.Instance != fr.inst) {
			continue
		}
		if m.When != "" {
			ok, err := expr.Behavior.EvalBool(m.When, r.act(fr, 1))
			if err != nil {
				return nil, abortf("mocks[%d].when: %v", i, err)
			}
			if !ok {
				continue
			}
		}
		r.mockSeen[i]++
		if len(m.Calls) > 0 && !containsInt(m.Calls, r.mockSeen[i]) {
			continue
		}
		raw, what := m.Return, "return"
		if m.Fail != nil {
			raw, what = m.Fail, "fail"
		}
		t, err := expr.DecodeTemplate(raw)
		var v any
		if err == nil {
			v, err = expr.Behavior.Template(t, r.act(fr, 1))
		}
		if err != nil {
			return nil, abortf("mocks[%d].%s: %v", i, what, err)
		}
		r.mocked++
		if m.Fail != nil {
			return &callResult{err: toError(v)}, nil
		}
		return &callResult{ok: true, value: v}, nil
	}
	return nil, nil
}

// invoke runs a call in the running task, which tracks it as a call in
// progress so that a kill of the callee's instance can unwind it (§13.1
// item 18).
func (r *run) invoke(c callSpec) (callResult, error) {
	t := r.s.cur
	if t == nil {
		return r.invokeCall(c, nil)
	}
	ac := &activeCall{inst: c.inst}
	if f, ok := r.x.Interfaces[c.target]; ok {
		ac.comp = f.Component
	}
	t.calls = append(t.calls, ac)
	res, err := r.invokeCall(c, ac)
	if n := len(t.calls); n > 0 && t.calls[n-1] == ac {
		t.calls[n-1] = nil
		t.calls = t.calls[:n-1]
	}
	return res, err
}

func (r *run) invokeCall(c callSpec, ac *activeCall) (res callResult, err error) {
	target := c.target
	if c.depth > r.lim.MaxDepth {
		return callResult{}, abortf("call depth limit of %d exceeded at %s", r.lim.MaxDepth, target)
	}
	if c.deadline != noDeadline && r.now >= c.deadline {
		// §11.3: a call that starts at or after the deadline fails at once.
		// Like timeout events, a deadline event describes the caller, whose
		// call was refused: component and instance are the caller's, To the
		// callee's component.
		e := &Error{Code: "deadline_exceeded", Message: fmt.Sprintf("%s not called: the deadline passed at %s ms", target, fmtMS(c.deadline))}
		to := ""
		if f, ok := r.x.Interfaces[target]; ok {
			to = f.Component
		}
		return callResult{err: e, target: target}, r.ev(Event{Type: "deadline", Span: c.parent, Call: c.callID, Component: c.from,
			From: c.from, To: to, Interface: target, Attempt: c.attempt, Async: c.async, Instance: c.fromInst, Error: e})
	}
	r.spans++
	span := r.spans
	f, known := r.x.Interfaces[target]
	to := ""
	if known {
		to = f.Component
		r.calls[target]++
		r.invoked[target]++
		r.compCalls[f.Component]++
		if c.inst != "" && !c.badInst {
			r.callsByInst[target+"@"+c.inst]++
			r.instCalls[target+"@"+c.inst]++
			r.instCalls[f.Component+"@"+c.inst]++
		}
	}
	start := r.now
	if err := r.ev(Event{Type: "call.start", Span: span, Parent: c.parent, Call: c.callID, Component: c.from, From: c.from, To: to,
		Interface: target, Attempt: c.attempt, Async: c.async, Input: deepCopy(c.input), Instance: c.inst}); err != nil {
		return callResult{}, err
	}
	mock := false
	end := func(res callResult, late bool) (callResult, error) {
		ok := res.ok
		res.target = target
		hdr := responseHeaders(&res)
		return res, r.ev(Event{Type: "call.end", Span: span, Parent: c.parent, Call: c.callID, Component: to, From: c.from, To: to,
			Interface: target, Attempt: c.attempt, Async: c.async, OK: &ok, Output: deepCopy(res.value), Error: res.err,
			DurationMS: r.now - start, Late: late, Instance: c.inst, Mock: mock, Headers: hdr})
	}
	if ac != nil {
		// A kill (§13.1 item 18) unwinds the task through this call: it
		// ends with killed, and the outermost call into the killed
		// instance returns peer-killed to its caller.
		defer func() {
			if !errors.Is(err, errUnwind) {
				return
			}
			cur := r.s.cur
			if _, everr := end(callResult{err: killedError(target)}, false); everr != nil {
				res, err = callResult{}, everr
				return
			}
			if cur.unwind == ac {
				cur.unwind = nil
				res, err = callResult{err: peerKilledError(ac.comp, ac.inst), target: target}, nil
			}
		}()
	}
	if !known {
		r.warn(fmt.Sprintf("call to unknown interface %q", target))
		return end(callResult{err: &Error{Code: "invalid_target", Message: fmt.Sprintf("unknown interface %q", target)}}, false)
	}
	if c.badInst {
		return end(callResult{err: &Error{Code: "unknown_instance", Message: fmt.Sprintf("%s has no instance %q", f.Component, c.inst)}}, false)
	}
	if len(r.dead) > 0 && r.isDead(f.Component, c.inst) {
		return end(callResult{err: peerKilledError(f.Component, c.inst)}, false)
	}
	r.checkSchema(f.Request, c.input, target+" request")

	skey := model.StateKey(f.Component, c.inst)
	slot, refused, err := r.acquire(f, skey, span, c)
	if err != nil {
		return callResult{}, err
	}
	if refused != nil {
		return end(callResult{err: refused}, false)
	}
	// A killed task unwinds through here: free its slot for the others.
	defer func() {
		if slot.active {
			r.release(slot)
		}
	}()
	// Limits (§13.1 item 27) are checked after capacity, before the
	// behavior; a concurrency lease they take is released when the call
	// ends, whatever the outcome.
	if len(f.Limits) > 0 {
		refused, leases, lerr := r.interfaceLimits(f, c, skey, span)
		if lerr != nil {
			return callResult{}, lerr
		}
		if len(leases) > 0 {
			defer func() {
				if rerr := r.releaseCallLeases(f, c, skey, span, leases); rerr != nil && err == nil {
					res, err = callResult{}, rerr
				}
			}()
		}
		if refused != nil {
			return end(callResult{err: refused}, false)
		}
	}
	seq := r.timerSeq

	hang := false
	ft, err := r.matchFault(f, c)
	if err != nil {
		return callResult{}, err
	}
	if ft != nil {
		r.faultsHit++
		msg := ft.Code
		if msg == "" {
			msg = ft.Message
		}
		if err := r.ev(Event{Type: "fault", Span: span, Call: c.callID, Component: f.Component, Interface: target, Fault: ft.Type, Message: msg,
			Instance: c.inst}); err != nil {
			return callResult{}, err
		}
	}
	switch {
	case ft != nil && ft.Type == "unavailable":
		e := &Error{Code: "unavailable", Status: 503, Retryable: true, Message: ft.Message}
		if ft.Code != "" {
			e.Code = ft.Code
		}
		if ft.Status != 0 {
			e.Status = ft.Status
		}
		if ft.Retryable != nil {
			e.Retryable = *ft.Retryable
		}
		if e.Message == "" {
			e.Message = f.Component + " is unavailable"
		}
		// A fault's latency_ms delays the refusal (§17 item 20).
		if ft.LatencyMS > 0 {
			if err := r.sleep(r.msToUS(ft.LatencyMS)); err != nil {
				return callResult{}, err
			}
		}
		res = callResult{err: e}
	case ft != nil && ft.Type == "error":
		lat, err := r.latency(f, c.input, c.inst, c.deadline)
		if err != nil {
			return callResult{}, err
		}
		if ft.LatencyMS > 0 {
			lat += r.msToUS(ft.LatencyMS) // the fault's own delay, as a latency fault adds (§17 item 20)
		}
		if err := r.sleep(lat); err != nil {
			return callResult{}, err
		}
		e := &Error{Code: ft.Code, Status: ft.Status, Message: ft.Message}
		if ft.Retryable != nil {
			e.Retryable = *ft.Retryable
		}
		res = callResult{err: e}
	case ft != nil && (ft.Type == "timeout" || ft.Type == model.FaultHang):
		hang = true
	default:
		// With latency_by_outcome (§14.13) the service time depends on the
		// outcome, so it is spent when the behavior ends (outcomeLatency).
		byOutcome := len(f.LatencyByOutcome) > 0
		var lat int64
		if !byOutcome {
			if lat, err = r.latency(f, c.input, c.inst, c.deadline); err != nil {
				return callResult{}, err
			}
		}
		if ft != nil && ft.Type == "latency" {
			lat += r.msToUS(ft.LatencyMS)
		}
		if err := r.sleep(lat); err != nil {
			return callResult{}, err
		}
		fr := &frame{iface: f, comp: f.Component, inst: c.inst, skey: skey, input: c.input, vars: map[string]any{}, span: span, deadline: c.deadline,
			stream: c.stream, cancel: c.cancel}
		if r.hasYield(f) {
			// streams_when (§17 item 12) can make this call plain: no
			// {items, value} wrapper, and no yield allowed.
			on, err := r.streamsWhen(fr)
			if err != nil {
				return callResult{}, err
			}
			switch {
			case !on:
				fr.plain = true
			case fr.stream == nil:
				fr.stream = &stream{}
			}
		}
		if ft != nil && ft.Type == model.FaultCrash {
			fr.crash = newCrash(ft, target)
		}
		var m *callResult
		if len(r.mocks) > 0 {
			if m, err = r.matchMock(fr); err != nil {
				return callResult{}, err
			}
		}
		if m != nil {
			res, mock = *m, true
		} else if res, err = r.execute(fr, c.depth); err != nil {
			return callResult{}, err
		} else if fr.stream != nil && !fr.stream.live && res.ok {
			res.value = collected(fr.stream, res.value)
		}
		if fr.crash != nil {
			// The steps that ran stand; the caller sees the crash (§13.1 item 25).
			res = callResult{err: fr.crash.err}
		}
		if byOutcome {
			if err := r.outcomeLatency(fr, res); err != nil {
				return callResult{}, err
			}
		}
	}
	// The effective timeout is the caller's timeout_ms, cut short by the
	// deadline (§11.3).
	timeout := c.timeout
	if c.deadline != noDeadline {
		if d := c.deadline - start; timeout <= 0 || d < timeout {
			timeout = d
		}
	}
	if ft != nil && ft.Type == model.FaultLostReply {
		// The callee's work stands but its reply is lost (§13.1 item 25):
		// with a code the caller gets that error now, else it waits out its
		// timeout, unless the callee already outlasted it (reported below).
		switch {
		case ft.Code != "":
			res = callResult{err: lostReplyError(ft, target)}
		case timeout <= 0 || r.now-start <= timeout:
			hang = true
		}
	}
	faultPayload(ft, &res) // a fault's data and headers (§15.3)
	if hang {
		limit := timeout
		if limit <= 0 && ft.Forever {
			// No timeout, no deadline: it never answers (§13.1 item 35).
			if err := r.hangForever(c, ft.Type); err != nil {
				return callResult{}, err
			}
		}
		if limit <= 0 {
			limit = defaultHangUS
		}
		if err := r.sleepUntil(start + limit); err != nil {
			return callResult{}, err
		}
		r.release(slot)
		slot.active = false
		// Timeout events describe the caller that gave up: component and
		// instance are the caller's (component always was, so traces of
		// existing models are unchanged), To the callee's component.
		if err := r.ev(Event{Type: "timeout", Span: span, Call: c.callID, Component: c.from, From: c.from, To: f.Component, Interface: target, DurationMS: limit,
			Message: f.Component + " did not respond", Instance: c.fromInst}); err != nil {
			return callResult{}, err
		}
		return end(callResult{err: &Error{Code: "timeout", Retryable: true, Message: fmt.Sprintf("%s did not respond within %s ms", target, fmtMS(limit))}}, false)
	}
	r.release(slot)
	slot.active = false
	if timeout > 0 && r.now-start > timeout {
		// The callee finished after the caller gave up: its work stands, but
		// the caller sees a timeout at start + timeout. Its plain emits are
		// delivered from its own end, not from the timeout (§13.1 item 14).
		if _, err := end(res, true); err != nil {
			return callResult{}, err
		}
		r.postpone(seq, r.now)
		r.now = start + timeout
		e := &Error{Code: "timeout", Retryable: true, Message: fmt.Sprintf("%s exceeded %s ms", target, fmtMS(timeout))}
		return callResult{err: e, target: target}, r.ev(Event{Type: "timeout", Span: span, Call: c.callID, Component: c.from, From: c.from, To: f.Component,
			Interface: target, DurationMS: timeout, Message: e.Message, Instance: c.fromInst})
	}
	return end(res, false)
}

type frame struct {
	iface    *model.Interface
	comp     string
	inst     string // the instance the behavior runs on (§11.1)
	skey     string // the state key of comp on inst
	input    any
	vars     map[string]any
	span     int
	lastErr  any
	deadline int64       // absolute virtual ms; noDeadline means none
	stream   *stream     // where yield steps send their items (§13.1 item 18)
	crash    *crashState // a crash fault on this invocation (§13.1 item 25)
	cancel   *cancelMark // the call's cancel mark: ctx.cancelled_at_ms (§16.4)
	plain    bool        // streams_when was false: a yield aborts (§17 item 12)
}

type exit struct {
	value any
	err   *Error
	ctl   string // "break" or "continue": leaves the enclosing foreach body
}

func (r *run) execute(fr *frame, depth int) (callResult, error) {
	f := fr.iface
	if len(f.Behavior) == 0 && f.Store != nil {
		return r.store(fr)
	}
	if len(f.Behavior) == 0 {
		return callResult{ok: true, value: r.fake(f.Response)}, nil
	}
	ex, err := r.steps(fr, f.Behavior, depth, f.ID+".behavior")
	if err != nil {
		return callResult{}, err
	}
	switch {
	case ex == nil || ex.ctl != "":
		return callResult{ok: true, value: r.fake(f.Response)}, nil
	case ex.err != nil:
		return callResult{err: ex.err}, nil
	}
	r.checkSchema(f.Response, ex.value, f.ID+" response")
	return callResult{ok: true, value: ex.value}, nil
}

func (r *run) act(f *frame, attempt int) map[string]any {
	var deadline any
	if f.deadline != noDeadline {
		deadline = msValue(r.epoch, f.deadline)
	}
	return map[string]any{"input": f.input, "state": r.state(f.skey), "ctx": r.ctxOf(f), "vars": f.vars,
		"attempt": int64(attempt), "now": msValue(r.epoch, r.now), "now_us": r.epoch*1000 + r.now, "error": f.lastErr,
		"self": f.inst, "deadline": deadline, "config": r.config, expr.RandomKey: r.random, expr.IDsKey: r.ids, expr.CanceledKey: r.isCanceled,
		expr.ChannelLenKey: r.channelLen, expr.CostLimitKey: r.costLimit, "limiters": r.limitersValue()}
}

// execPath turns an internal step path ("<iface>.behavior[0].then[1]")
// into the §13.1 executed form ("<iface>:behavior[0].then[1]").
func execPath(f *frame, p string) string {
	return f.iface.ID + ":" + strings.TrimPrefix(p, f.iface.ID+".")
}

func (r *run) steps(f *frame, steps []model.Step, depth int, path string) (*exit, error) {
	for i, s := range steps {
		p := fmt.Sprintf("%s[%d]", path, i)
		if s.When != "" {
			ok, err := expr.Behavior.EvalBool(s.When, r.act(f, 1))
			if err != nil {
				return nil, abortf("%s.when: %v", p, err)
			}
			if !ok {
				continue
			}
		}
		if f.crash != nil && len(s.Actions()) > 0 && !f.crash.step() {
			return &exit{err: f.crash.err}, nil // crashed before this step (§13.1 item 25)
		}
		r.executed[execPath(f, p)] = true
		if s.Title != "" || s.Detail != "" {
			if err := r.ev(Event{Type: "note", Span: f.span, Component: f.comp, Interface: f.iface.ID, Title: s.Title, Detail: s.Detail, Source: s.Source,
				Instance: f.inst}); err != nil {
				return nil, err
			}
		}
		acts := s.Actions()
		if len(acts) == 0 {
			continue
		}
		var ex *exit
		var err error
		switch acts[0] {
		case "set":
			err = r.set(f, s.Set, p)
		case "call":
			ex, err = r.call(f, s, depth, p)
		case "if":
			var cond bool
			cond, err = expr.Behavior.EvalBool(s.If, r.act(f, 1))
			if err != nil {
				return nil, abortf("%s.if: %v", p, err)
			}
			if cond {
				ex, err = r.steps(f, s.Then, depth, p+".then")
			} else {
				ex, err = r.steps(f, s.Else, depth, p+".else")
			}
		case "choice":
			ex, err = r.choice(f, s, depth, p)
		case "return":
			var t, v any
			t, err = expr.DecodeTemplate(s.Return)
			if err == nil {
				v, err = expr.Behavior.Template(t, r.act(f, 1))
			}
			if err != nil {
				return nil, abortf("%s.return: %v", p, err)
			}
			return &exit{value: v}, nil
		case "fail":
			var t, v any
			t, err = expr.DecodeTemplate(s.Fail)
			if err == nil {
				v, err = expr.Behavior.Template(t, r.act(f, 1))
			}
			if err != nil {
				return nil, abortf("%s.fail: %v", p, err)
			}
			return &exit{err: toError(v)}, nil
		case "emit":
			err = r.emit(f, s, p)
		case "publish":
			ex, err = r.publish(f, s, depth, p)
		case "parallel":
			ex, err = r.parallel(f, s, depth, p)
		case "foreach":
			ex, err = r.foreach(f, s, depth, p)
		case "break", "continue":
			return &exit{ctl: acts[0]}, nil
		case "wait":
			if bw, berr := s.BlockingWait(); berr != nil || bw != nil {
				if berr != nil {
					return nil, abortf("%s.wait: %v", p, berr)
				}
				ex, err = r.blockingWait(f, s, bw, depth, p+".wait") // §17 item 2, waits.go
				break
			}
			var ms int64
			ms, err = r.waitMS(f, s.Wait)
			if err != nil {
				return nil, abortf("%s.wait: %v", p, err)
			}
			if s.Token == "" {
				err = r.sleep(ms)
				break
			}
			var e *Error
			if e, err = r.waitBound(f, s, ms, p); err == nil && e != nil {
				f.lastErr = e.Map()
				ex, err = r.onError(f, s.OnError, e, depth, p, false)
			}
		case "signal":
			err = r.signalStep(f, s, p) // §17 item 2, waits.go
		case "close":
			var key string
			if key, err = r.sessionOf(f, s.Close.Session, p+".close.session"); err == nil {
				err = r.closeSession(key, f.comp, f.inst, f.span)
			}
		case "cancel":
			var name string
			if name, err = r.tokenOf(f, s.Cancel, p+".cancel"); err == nil {
				err = r.cancel(name, f.comp, f.inst, f.span)
			}
		case "restart":
			err = r.restartIn(f, s.Restart, p)
		case "rendezvous":
			ex, err = r.rendezvous(f, s, depth, p)
		case "yield":
			ex, err = r.yieldStep(f, s, depth, p) // flow control (§16.4)
		case "put":
			ex, err = r.put(f, s, depth, p)
		case "receive":
			ex, err = r.receive(f, s, depth, p)
		case "kill":
			err = r.killIn(f, s.Kill, p)
		case "transact":
			ex, err = r.transact(f, s, depth, p)
		case "admit":
			ex, err = r.admitStep(f, s, depth, p)
		case "charge":
			ex, err = r.chargeStep(f, s, depth, p)
		case "release":
			ex, err = r.releaseStep(f, s, depth, p)
		}
		if err != nil {
			return nil, err
		}
		if ex != nil {
			return ex, nil
		}
	}
	return nil, nil
}

// items evaluates a foreach or parallel template into items and their keys:
// list items by position, map entries by sorted key, nothing for null.
func (r *run) items(f *frame, tpl any, what, p string) (items, keys []any, err error) {
	v, err := expr.Behavior.Template(expr.Native(tpl), r.act(f, 1))
	if err != nil {
		return nil, nil, abortf("%s.%s: %v", p, what, err)
	}
	switch t := v.(type) {
	case nil:
	case []any:
		items = t
		for i := range t {
			keys = append(keys, int64(i))
		}
	case map[string]any:
		for _, k := range sortedKeys(t) {
			items, keys = append(items, t[k]), append(keys, k)
		}
	default:
		return nil, nil, abortf("%s.%s: needs a list or a map, got %T", p, what, v)
	}
	return items, keys, nil
}

// foreach runs its steps once per item, in order: list items by position, map
// entries by sorted key. vars.<as> holds the item and vars.<index> its
// position or key; both are restored when the loop ends.
func (r *run) foreach(f *frame, s model.Step, depth int, p string) (*exit, error) {
	items, keys, err := r.items(f, s.Foreach, "foreach", p)
	if err != nil {
		return nil, err
	}
	limit := r.foreachLimit(s.Max) // §17 item 18, sim17.go
	if len(items) > limit {
		r.warn(fmt.Sprintf("%s: foreach stopped after max %d of %d items", p, limit, len(items)))
		items = items[:limit]
	}
	as, index := loopNames(s)
	oldAs, hadAs := f.vars[as]
	oldIndex, hadIndex := f.vars[index]
	defer func() {
		delete(f.vars, as)
		delete(f.vars, index)
		if hadAs {
			f.vars[as] = oldAs
		}
		if hadIndex {
			f.vars[index] = oldIndex
		}
	}()
	for i, item := range items {
		r.loops++
		if r.loops > r.lim.MaxIterations {
			return nil, abortf("loop budget of %d iterations exceeded at %s (a scenario's max_iterations raises it, up to %d)", r.lim.MaxIterations, p, model.MaxMaxIterations)
		}
		f.vars[as], f.vars[index] = deepCopy(item), keys[i]
		ex, err := r.steps(f, s.Steps, depth, p+".steps")
		if err != nil || ex == nil {
			if err != nil {
				return nil, err
			}
			continue
		}
		switch ex.ctl {
		case "continue":
		case "break":
			return nil, nil
		default:
			return ex, nil
		}
	}
	return nil, nil
}

func loopNames(s model.Step) (as, index string) {
	as, index = s.As, s.Index
	if as == "" {
		as = "item"
	}
	if index == "" {
		index = "index"
	}
	return as, index
}

func (r *run) set(f *frame, set map[string]any, p string) error {
	keys := sortedKeys(set)
	vals := make([]any, len(keys))
	paths := make([]string, len(keys))
	act := r.act(f, 1)
	for i, k := range keys {
		v, err := expr.Behavior.Template(set[k], act)
		if err != nil {
			return abortf("%s.set.%s: %v", p, k, err)
		}
		vals[i], paths[i] = v, k
		if src, ok := expr.ExprOf(k); ok {
			// A dynamic path (§13.1 item 14): the key evaluates to a path.
			pv, err := expr.Behavior.Eval(src, act)
			if err != nil {
				return abortf("%s.set.%s: %v", p, k, err)
			}
			path, ok := pv.(string)
			if !ok {
				return abortf("%s.set.%s: a dynamic path must give a string, got %T", p, k, pv)
			}
			if segs, err := model.ParsePath(path); err != nil || len(segs) < 2 || segs[0].Quoted {
				return abortf("%s.set.%s: invalid path %q", p, k, path)
			}
			paths[i] = path
		}
	}
	for i := range keys {
		k := paths[i]
		segs, err := model.SplitPath(k) // ['a.b'] quotes a key with dots (behavior-language §30)
		if err != nil {
			return abortf("%s.set.%s: %v", p, k, err)
		}
		var root map[string]any
		switch segs[0] {
		case "vars":
			root = f.vars
		case "ctx":
			root = r.ctx
		case "state":
			root = r.state(f.skey)
		default:
			return abortf("%s.set.%s: unknown path root", p, k)
		}
		old := assign(root, segs[1:], deepCopy(vals[i]))
		if err := r.ev(Event{Type: "set", Span: f.span, Component: f.comp, Interface: f.iface.ID, Scope: segs[0], Path: k,
			Old: deepCopy(old), New: deepCopy(vals[i]), Instance: f.inst}); err != nil {
			return err
		}
	}
	return nil
}

func (r *run) maxAttempts(f *frame, rs *model.RetrySpec) (int, error) {
	if rs == nil {
		return 1, nil
	}
	v := expr.Native(rs.MaxAttempts)
	if src, ok := expr.ExprOf(v); ok {
		var err error
		v, err = expr.Behavior.Eval(src, r.act(f, 1))
		if err != nil {
			return 0, err
		}
	}
	n, ok := v.(int64)
	if !ok {
		if fl, isF := v.(float64); isF {
			n, ok = int64(fl), true
		}
	}
	if !ok {
		return 0, fmt.Errorf("max_attempts must be a number, got %T", v)
	}
	return int(max(1, min(n, 20))), nil
}

// retries reports whether a retry policy retries an error, before its
// when. on_status and on_codes (§13.1 item 35) retry a listed status or
// code whatever the error's retryable flag (codes counts as one of them
// then); without them, codes limits the retries to its codes, and
// otherwise the error's retryable flag decides.
func retries(rs *model.RetrySpec, e *Error) bool {
	if len(rs.OnStatus) > 0 || len(rs.OnCodes) > 0 {
		return containsInt(rs.OnStatus, e.Status) || containsStr(rs.OnCodes, e.Code) || containsStr(rs.Codes, e.Code)
	}
	if len(rs.Codes) > 0 {
		return containsStr(rs.Codes, e.Code)
	}
	return e.Retryable
}

func backoff(rs *model.RetrySpec, attempt int) int64 {
	if rs.BackoffMS <= 0 {
		return 0
	}
	mult := rs.Multiplier
	if mult <= 0 {
		mult = 1
	}
	b := float64(rs.BackoffMS) * math.Pow(mult, float64(attempt-1))
	if rs.MaxBackoffMS > 0 && b > float64(rs.MaxBackoffMS) {
		b = float64(rs.MaxBackoffMS)
	}
	return int64(b)
}

// jitter draws the wait for a computed backoff of b ms from the run's
// seeded random source, by the retry's jitter mode. "none" (the default)
// draws nothing, so runs without jitter keep their random sequence.
func (r *run) jitter(rs *model.RetrySpec, b int64) int64 {
	if b <= 0 {
		return b
	}
	switch rs.Jitter {
	case "full":
		return r.rng.Int64N(b + 1)
	case "equal":
		half := b / 2
		return half + r.rng.Int64N(b-half+1)
	}
	return b
}

// jitterMode is the retry event's jitter field: empty for no jitter.
func jitterMode(rs *model.RetrySpec) string {
	if rs.Jitter == "none" {
		return ""
	}
	return rs.Jitter
}

// intOf evaluates a millisecond number-or-template step field (§13.1) in
// the behavior environment, in µs (§13.1 item 16). Negative values count
// as 0.
func (r *run) intOf(f *frame, v model.IntOrExpr, p string) (int64, error) {
	if !v.IsExpr() {
		return max(r.numUS(v), 0), nil
	}
	out, err := expr.Behavior.Eval(strings.TrimSpace(v.Expr), r.act(f, 1))
	if err != nil {
		return 0, abortf("%s: %v", p, err)
	}
	n, ok := r.valueUS(out)
	if !ok {
		return 0, abortf("%s: must give a number, got %T", p, out)
	}
	return max(n, 0), nil
}

// countOf evaluates a count number-or-template field. Negative values count
// as 0.
func (r *run) countOf(f *frame, v model.IntOrExpr, p string) (int64, error) {
	if !v.IsExpr() {
		return max(v.N, 0), nil
	}
	out, err := expr.Behavior.Eval(strings.TrimSpace(v.Expr), r.act(f, 1))
	if err != nil {
		return 0, abortf("%s: %v", p, err)
	}
	n, ok := toInt(out)
	if !ok {
		return 0, abortf("%s: must give a number, got %T", p, out)
	}
	return max(n, 0), nil
}

func toInt(v any) (int64, bool) {
	switch t := v.(type) {
	case int64:
		return t, true
	case float64:
		return int64(t), true
	}
	return 0, false
}

func (r *run) call(f *frame, s model.Step, depth int, p string) (*exit, error) {
	inputTpl, err := expr.DecodeTemplate(s.Input)
	if err != nil {
		return nil, abortf("%s.input: %v", p, err)
	}
	attempts, err := r.maxAttempts(f, s.Retry)
	if err != nil {
		return nil, abortf("%s.retry.max_attempts: %v", p, err)
	}
	timeout, err := r.intOf(f, s.TimeoutMS, p+".timeout_ms")
	if err != nil {
		return nil, err
	}
	var tok, session string
	if s.Token != "" {
		if tok, err = r.tokenOf(f, s.Token, p+".token"); err != nil {
			return nil, err
		}
	}
	if s.Session != "" {
		if session, err = r.sessionOf(f, s.Session, p+".session"); err != nil {
			return nil, err
		}
	}
	callID := r.nextCall()
	start := r.now
	deadline := f.deadline
	if !s.DeadlineMS.IsZero() {
		d, err := r.intOf(f, s.DeadlineMS, p+".deadline_ms")
		if err != nil {
			return nil, err
		}
		deadline = min(deadline, start+d)
	}
	var res callResult
	var lastRoute *routeReq
	n := 0
	for attempt := 1; attempt <= attempts; attempt++ {
		n = attempt
		act := r.act(f, attempt)
		target := s.Call
		var rt *routeReq // a call addressed by route (§13.1 item 26)
		if s.Route != nil {
			if rt, err = r.routeRequest(s, act, p); err != nil {
				return nil, err
			}
			target = rt.match.Interface
		} else if src, ok := expr.ExprOf(s.Call); ok {
			v, err := expr.Behavior.Eval(src, act)
			if err != nil {
				return nil, abortf("%s.call: %v", p, err)
			}
			str, ok := v.(string)
			if !ok {
				return nil, abortf("%s.call: target must be a string, got %T", p, v)
			}
			target = str
		}
		var input any
		callee, known := r.x.Interfaces[target]
		if rt != nil {
			if known {
				if input, err = r.routeInput(rt, s, inputTpl, act, p); err != nil {
					return nil, err
				}
			}
		} else if s.Input != nil {
			input, err = expr.Behavior.Template(inputTpl, act)
			if err != nil {
				return nil, abortf("%s.input: %v", p, err)
			}
			if s.Fill && known {
				input = deepMerge(r.fake(callee.Request), input)
			}
		} else if known {
			input = r.fake(callee.Request)
		}
		inst, bad, err := r.targetInstance(f.comp, f.inst, target, s.On, expr.Behavior, act)
		if err != nil {
			return nil, abortf("%s.on: %v", p, err)
		}
		cs := callSpec{from: f.comp, fromInst: f.inst, fromIface: f.iface.ID, target: target, inst: inst, badInst: bad, input: input, parent: f.span,
			callID: callID, attempt: attempt, depth: depth + 1, timeout: timeout, deadline: deadline, session: session}
		lastRoute = rt
		var ex *exit
		switch {
		case rt != nil:
			rt.depth = depth // a route call may stream (§15.3)
			res, err = r.routeInvoke(f, s, rt, cs, tok, inputTpl, act, p)
			ex = rt.exit
		case s.Stream:
			res, ex, err = r.invokeStream(f, s, tok, cs, depth, p)
		case tok != "" || session != "":
			res, err = r.invokeBound(tok, cs)
		default:
			res, err = r.invoke(cs)
		}
		if err != nil {
			return nil, err
		}
		if ex != nil {
			return ex, nil
		}
		if res.ok || attempt == attempts {
			break
		}
		if !retries(s.Retry, res.err) {
			break
		}
		if s.Retry.When != "" {
			wact := r.act(f, attempt)
			wact["error"] = res.err.Map()
			ok, err := expr.Behavior.EvalBool(s.Retry.When, wact)
			if err != nil {
				return nil, abortf("%s.retry.when: %v", p, err)
			}
			if !ok {
				break
			}
		}
		b := r.retryWaitUS(s.Retry, attempt, res.err) // respect_retry_after (§15.3)
		if deadline != noDeadline && r.now+b >= deadline {
			break // the next attempt would start at or after the deadline
		}
		r.retries++
		if err := r.ev(Event{Type: "retry", Span: f.span, Call: callID, Component: f.comp, Interface: target, Attempt: attempt + 1,
			BackoffMS: b, Jitter: jitterMode(s.Retry), Message: res.err.Code, Title: s.Retry.Title, Detail: s.Retry.Detail, Source: s.Retry.Source, Instance: f.inst}); err != nil {
			return nil, err
		}
		if err := r.sleep(b); err != nil {
			return nil, err
		}
	}
	out := map[string]any{"ok": res.ok, "value": res.value, "error": nil, "attempts": int64(n), "duration_ms": msFloor(r.now - start), "duration_us": r.now - start, "target": res.target}
	if lastRoute != nil {
		out["route"] = lastRoute.summary()
	}
	r.cancelTime(out, res) // vars.<as>.cancelled_at_ms (§16.4)
	if !res.ok {
		// error stays the most recent failure: a later successful call (in
		// on_error steps, say) must not clear the error being handled.
		out["error"] = res.err.Map()
		f.lastErr = res.err.Map()
	}
	if s.As != "" {
		f.vars[s.As] = deepCopy(out)
	}
	if res.ok {
		return nil, nil
	}
	return r.onError(f, s.OnError, res.err, depth, p, false)
}

// onError handles a failed call or sync publish: on_error steps, continue,
// or propagate. A publish without on_error continues.
func (r *run) onError(f *frame, o *model.OnError, e *Error, depth int, p string, continueByDefault bool) (*exit, error) {
	switch {
	case o != nil && o.Mode == "" && o.Steps != nil:
		return r.steps(f, o.Steps, depth, p+".on_error")
	case o != nil && o.Mode == "continue":
		return nil, nil
	case o == nil && continueByDefault:
		return nil, nil
	}
	return &exit{err: e}, nil
}

func (r *run) choice(f *frame, s model.Step, depth int, p string) (*exit, error) {
	key := f.iface.ID + "." + s.Choice
	option, origin := "", ""
	if o, ok := r.curChoices().next(key); ok {
		if _, exists := s.Options[o]; exists {
			option, origin = o, "scenario"
		} else {
			r.warn(fmt.Sprintf("choice %s has no option %q; using its default", key, o))
		}
	}
	if option == "" {
		switch src, isExpr := expr.ExprOf(s.Default); {
		case isExpr:
			v, err := expr.Behavior.Eval(src, r.act(f, 1))
			if err != nil {
				return nil, abortf("%s.default: %v", p, err)
			}
			str, ok := v.(string)
			if _, exists := s.Options[str]; !ok || !exists {
				return nil, abortf("%s.default: %v is not an option of %s", p, v, key)
			}
			option, origin = str, "expression"
		case s.Default != "":
			option, origin = s.Default, "default"
		default:
			option, origin = sortedKeys(s.Options)[0], "default"
		}
	}
	if err := r.ev(Event{Type: "choice", Span: f.span, Component: f.comp, Interface: f.iface.ID, Key: key, Option: option, Origin: origin,
		Instance: f.inst}); err != nil {
		return nil, err
	}
	return r.steps(f, s.Options[option], depth, p+".options."+option)
}

// stepInput evaluates an emit's or publish's input, or fakes it from the
// request schema of iface when the step has none.
func (r *run) stepInput(f *frame, s model.Step, iface string, p string) (any, error) {
	if s.Input != nil {
		t, err := expr.DecodeTemplate(s.Input)
		var v any
		if err == nil {
			v, err = expr.Behavior.Template(t, r.act(f, 1))
		}
		if err != nil {
			return nil, abortf("%s.input: %v", p, err)
		}
		return v, nil
	}
	if callee, known := r.x.Interfaces[iface]; known {
		return r.fake(callee.Request), nil
	}
	return nil, nil
}

func (r *run) emit(f *frame, s model.Step, p string) error {
	r.emits++
	if r.emits > r.lim.MaxEmits {
		return abortf("emit budget of %d exceeded", r.lim.MaxEmits)
	}
	input, err := r.stepInput(f, s, s.Emit, p)
	if err != nil {
		return err
	}
	to := ""
	if callee, known := r.x.Interfaces[s.Emit]; known {
		to = callee.Component
	}
	inst, bad, err := r.targetInstance(f.comp, f.inst, s.Emit, s.On, expr.Behavior, r.act(f, 1))
	if err != nil {
		return abortf("%s.on: %v", p, err)
	}
	tm, err := r.timing(f, s, p)
	if err != nil {
		return err
	}
	tok, err := r.tokenOf(f, s.Token, p+".token")
	if err != nil {
		return err
	}
	if tok == "" || !r.isCanceled(tok) {
		r.schedule(tm, delivery{from: f.comp, fromInst: f.inst, fromIface: f.iface.ID, target: s.Emit, inst: inst, badInst: bad, input: input, parent: f.span, token: tok})
	}
	return r.ev(Event{Type: "emit", Span: f.span, Component: f.comp, From: f.comp, To: to, Interface: s.Emit, Input: deepCopy(input),
		Instance: f.inst})
}

// publish delivers its input to every subscriber of the topic (§11.5), in
// sorted interface id order: inline with delivery sync, else queued like
// emits (and on timers, with after_ms or every_ms).
func (r *run) publish(f *frame, s model.Step, depth int, p string) (*exit, error) {
	topic := s.Publish
	input, err := r.stepInput(f, s, topic, p)
	if err != nil {
		return nil, err
	}
	tm, err := r.timing(f, s, p)
	if err != nil {
		return nil, err
	}
	tok, err := r.tokenOf(f, s.Token, p+".token")
	if err != nil {
		return nil, err
	}
	iface := ""
	if _, ok := r.x.Interfaces[topic]; ok {
		iface = topic
	}
	if err := r.ev(Event{Type: "publish", Span: f.span, Component: f.comp, From: f.comp, Interface: iface, Topic: topic,
		Input: deepCopy(input), Instance: f.inst}); err != nil {
		return nil, err
	}
	subs := r.x.Subscribers[topic]
	act := r.act(f, 1)
	sync := s.Delivery == model.DeliverySync
	if sync && tm.timer {
		r.warn(fmt.Sprintf("%s: a publish on a timer is delivered asynchronously", p))
		sync = false
	}
	var first *Error
	for _, sub := range subs {
		inst, bad, err := r.targetInstance(f.comp, f.inst, sub, s.On, expr.Behavior, act)
		if err != nil {
			return nil, abortf("%s.on: %v", p, err)
		}
		if !sync {
			r.emits++
			if r.emits > r.lim.MaxEmits {
				return nil, abortf("emit budget of %d exceeded", r.lim.MaxEmits)
			}
			if tok == "" || !r.isCanceled(tok) {
				r.schedule(tm, delivery{from: f.comp, fromInst: f.inst, fromIface: f.iface.ID, target: sub, inst: inst, badInst: bad, input: deepCopy(input), parent: f.span, token: tok})
			}
			if err := r.ev(Event{Type: "emit", Span: f.span, Component: f.comp, From: f.comp, To: r.x.Interfaces[sub].Component, Interface: sub,
				Input: deepCopy(input), Instance: f.inst, Topic: topic}); err != nil {
				return nil, err
			}
			continue
		}
		res, err := r.invoke(callSpec{from: f.comp, fromInst: f.inst, fromIface: f.iface.ID, target: sub, inst: inst, badInst: bad, input: deepCopy(input), parent: f.span,
			callID: r.nextCall(), attempt: 1, depth: depth + 1, deadline: f.deadline})
		if err != nil {
			return nil, err
		}
		if !res.ok {
			f.lastErr = res.err.Map()
			if first == nil {
				first = res.err
			}
			if s.OnError != nil && s.OnError.Mode == "propagate" {
				break
			}
		}
	}
	if first == nil {
		return nil, nil
	}
	return r.onError(f, s.OnError, first, depth, p, true)
}

func (r *run) waitMS(f *frame, w any) (int64, error) {
	v := expr.Native(w)
	if src, ok := expr.ExprOf(v); ok {
		var err error
		if v, err = expr.Behavior.Eval(src, r.act(f, 1)); err != nil {
			return 0, err
		}
	}
	if us, ok := r.valueUS(v); ok {
		return max(us, 0), nil // in µs (§13.1 item 16)
	}
	return 0, fmt.Errorf("wait must be milliseconds, got %T", v)
}

package sim

import (
	"fmt"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Blocking waits and signals (DESIGN §17 item 2), and timers under a
// blocked call tree (§17 item 3).
//
// A blocking wait parks its task until its until condition holds, its
// signal is delivered, its token is canceled, or it times out. The
// condition is re-evaluated by the waiting task itself: the events that
// can change it (a state write on the waiting instance, a put or receive
// when until reads channel_len, a cancel when it reads canceled, a kill or
// a restart) wake it at the time they happen, and it parks again while the
// condition is false. A wait with no time limit is an idle consumer, as a
// receive is (§13.1 item 18).
//
// While every task of a root's call tree is blocked (on a channel, a wait,
// a child or a join), the root's emits and timers are delivered on time,
// instead of after the tree: a fork, an exec whose program exits on a
// timer and a blocking waitpid in one call no longer deadlock.

// condWait is a task blocked in a blocking wait.
type condWait struct {
	t        *task
	skey     string   // the waiting instance's state key
	signals  []string // the signals it waits for, if any
	until    bool     // it has an until condition
	chans    bool     // until reads channel_len
	tokens   bool     // until reads canceled
	signaled bool
	got      string         // the signal that woke it
	data     map[string]any // what that signal carried, if anything
}

// condEvent wakes the blocking waits an event may concern. It runs for
// every recorded event while a wait is blocked.
func (r *run) condEvent(e *Event) {
	for _, w := range r.conds {
		if !w.until || w.t == r.s.cur || w.t.done {
			continue
		}
		wake := false
		switch e.Type {
		case "set":
			wake = e.Scope == "state" && model.StateKey(e.Component, e.Instance) == w.skey
		case "put", "receive":
			wake = w.chans
		case "cancel":
			wake = w.tokens
		case "kill", "restart":
			wake = true
		}
		if wake {
			r.wakeAt(w.t, r.now, 0)
		}
	}
	if e.Type == "kill" {
		r.deliverSignal("kill:"+model.StateKey(e.Component, e.Instance), nil)
	}
}

// deliverSignal wakes the waits for a signal and returns how many it woke.
// A signal no wait is waiting for is lost (exit signals excepted: see
// exits.go). data, when not nil, is what the signal carries.
func (r *run) deliverSignal(name string, data map[string]any) int {
	n := 0
	for _, w := range r.conds {
		if containsStr(w.signals, name) && !w.signaled && !w.t.done && !w.t.killed {
			w.signaled = true
			w.got, w.data = name, data
			n++
			r.wakeAt(w.t, r.now, 0)
		}
	}
	return n
}

// signalStep runs a signal action.
func (r *run) signalStep(f *frame, s model.Step, p string) error {
	name, err := r.tokenOf(f, s.Signal, p+".signal")
	if err != nil {
		return err
	}
	n := r.deliverSignal(name, nil)
	return r.ev(Event{Type: "signal", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst, Key: name,
		Output: map[string]any{"woken": int64(n)}})
}

// blockingWait runs a wait step written as an object.
func (r *run) blockingWait(f *frame, s model.Step, w *model.WaitSpec, depth int, p string) (*exit, error) {
	var timeout int64
	if w.TimeoutMS.IsExpr() {
		out, err := expr.Behavior.Eval(strings.TrimSpace(w.TimeoutMS.Expr), r.act(f, 1))
		if err != nil {
			return nil, abortf("%s.timeout_ms: %v", p, err)
		}
		us, ok := r.valueUS(out)
		if !ok {
			return nil, abortf("%s.timeout_ms: must give a number, got %T", p, out)
		}
		timeout = max(us, 0)
	} else {
		timeout = max(r.numUS(w.TimeoutMS), 0)
	}
	var signals []string
	if w.Signal != "" {
		name, err := r.tokenOf(f, w.Signal, p+".signal")
		if err != nil {
			return nil, err
		}
		signals = append(signals, name)
	}
	for i, v := range w.Signals {
		name, err := r.tokenOf(f, v, fmt.Sprintf("%s.signals[%d]", p, i))
		if err != nil {
			return nil, err
		}
		if !containsStr(signals, name) {
			signals = append(signals, name)
		}
	}
	token := ""
	if s.Token != "" {
		var err error
		if token, err = r.tokenOf(f, s.Token, p+".token"); err != nil {
			return nil, err
		}
	}
	src := w.UntilSource()
	holds := func() (bool, error) {
		if src == "" {
			return false, nil
		}
		ok, err := expr.Behavior.EvalBool(src, r.act(f, 1))
		if err != nil {
			return false, abortf("%s.until: %v", p, err)
		}
		return ok, nil
	}
	start := r.now
	limit := r.waitLimit(f, timeout)
	cw := &condWait{t: r.s.cur, skey: f.skey, signals: signals, until: src != "",
		chans: strings.Contains(src, "channel_len"), tokens: strings.Contains(src, "canceled")}
	// An instance that has already exited wakes a wait on its exit at once
	// (§17 item 14), as a dead process's sentinel does.
	for _, name := range signals {
		if d, ok := r.exits[name]; ok {
			cw.signaled, cw.got, cw.data = true, name, d
			break
		}
	}
	var tw *tokenWait
	if token != "" && !r.isCanceled(token) {
		tw = r.await(token, 0)
	}
	r.conds = append(r.conds, cw)
	reason := ""
	var failure *Error
	for {
		ok, err := holds()
		if err != nil {
			r.dropCond(cw, token, tw)
			return nil, err
		}
		switch {
		case ok:
			reason = "until"
		case cw.signaled:
			reason = "signal"
		case token != "" && r.isCanceled(token):
			failure = canceledError(token)
		case r.now >= limit:
			reason = "timeout"
			failure = &Error{Code: "timeout", Retryable: true, Message: fmt.Sprintf("wait timed out after %s ms", fmtMS(r.now-start)),
				Data: map[string]any{"waited_ms": msFloor(r.now - start)}}
		}
		if reason != "" || failure != nil {
			break
		}
		if limit == noDeadline {
			err = r.parkBlockedIdle()
		} else {
			err = r.parkBlocked(limit, 0)
		}
		if err != nil {
			r.dropCond(cw, token, tw)
			return nil, err
		}
	}
	r.dropCond(cw, token, tw)
	out := map[string]any{"reason": reason, "waited_ms": msFloor(r.now - start)}
	if reason == "signal" {
		out["signal"] = cw.got
		if cw.data != nil {
			out["data"] = deepCopy(cw.data)
		}
	}
	key := strings.Join(signals, "|")
	if reason == "signal" {
		key = cw.got
	}
	if key == "" {
		key = "until"
	}
	if err := r.ev(Event{Type: "wait", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst, Key: key,
		Output: out, Error: failure, WaitMS: r.now - start}); err != nil {
		return nil, err
	}
	if w.As != "" {
		f.vars[w.As] = out
	}
	if failure == nil {
		return nil, nil
	}
	if failure.Code == "timeout" {
		mode, steps, err := w.TimeoutMode()
		if err != nil {
			return nil, abortf("%s.on_timeout: %v", p, err)
		}
		switch {
		case steps != nil:
			f.lastErr = failure.Map()
			return r.steps(f, steps, depth, p+".on_timeout")
		case mode == model.WaitTimeoutContinue:
			return nil, nil
		}
	}
	f.lastErr = failure.Map()
	return r.onError(f, s.OnError, failure, depth, p, false)
}

func (r *run) dropCond(cw *condWait, token string, tw *tokenWait) {
	if tw != nil {
		r.unawait(token, tw)
	}
	for i, x := range r.conds {
		if x == cw {
			r.conds = append(r.conds[:i:i], r.conds[i+1:]...)
			return
		}
	}
}

// parkBlocked parks the running task as blocked (§17 item 3): see
// treeBlocking.
func (r *run) parkBlocked(at int64, phase int) error {
	t := r.s.cur
	t.blocked = true
	err := r.park(at, phase)
	t.blocked = false
	return err
}

// parkBlockedIdle parks the running task as a blocked idle consumer.
func (r *run) parkBlockedIdle() error {
	t := r.s.cur
	t.blocked = true
	err := r.parkIdle()
	t.blocked = false
	return err
}

// rootOf is the root task a task works for, or nil for a lane's
// deliveries (and the work they spawn).
func rootOf(t *task) *task {
	for k := t; k != nil; k = k.parent {
		if k.kind == kindLane {
			return nil
		}
		if k.parent == nil {
			if k.kind == kindRoot {
				return k
			}
			return nil
		}
	}
	return nil
}

// treeBlocked reports whether every live task of the call tree that owns
// lane ln is blocked.
func (r *run) treeBlocked(ln *lane) bool {
	if ln == nil {
		return false
	}
	n := 0
	for _, t := range r.s.live {
		if t.lane != ln || t.kind == kindLane || rootOf(t) == nil {
			continue
		}
		if !t.blocked {
			return false
		}
		n++
	}
	return n > 0
}

// laneMayRun reports whether lane ln may deliver now: once its root's
// call tree has finished, or while that tree is blocked.
func (r *run) laneMayRun(ln *lane) bool {
	return ln.open || r.treeBlocked(ln)
}

// treeBlocking runs when task t parks blocked: if that blocks its whole
// call tree, the tree's queued emits and timers start being delivered.
func (r *run) treeBlocking(t *task) {
	ln := t.lane
	if ln == nil || ln.open || ln.task != nil || len(ln.queue) == 0 || r.s.stopped || t.kind == kindLane || rootOf(t) == nil {
		return
	}
	if r.treeBlocked(ln) {
		r.startLane(ln, r.now)
	}
}

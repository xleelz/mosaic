package sim

import (
	"fmt"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Cancellation tokens (§13.1 item 14) are run-wide names. Canceling one
// fails every call, wait or parallel bound to it that is still pending,
// at the cancel time, and drops the pending deliveries of emits and
// publishes bound to it. A call or wait bound to a token already canceled
// fails at once.

type token struct {
	canceled bool
	at       int64
	waiters  []*tokenWait
}

// tokenWait is a task waiting on something a token can cancel.
type tokenWait struct {
	t        *task
	canceled bool
	done     bool
	phase    int
	session  string // the session whose close canceled it (§13.1 item 35)
}

func (r *run) token(name string) *token {
	tk, ok := r.tokens[name]
	if !ok {
		tk = &token{}
		r.tokens[name] = tk
	}
	return tk
}

// isCanceled is CEL canceled(name).
func (r *run) isCanceled(name string) bool {
	tk, ok := r.tokens[name]
	return ok && tk.canceled
}

// tokenOf evaluates a token name: a literal or "=cel". Empty means none.
func (r *run) tokenOf(f *frame, v, p string) (string, error) {
	src, ok := expr.ExprOf(v)
	if !ok {
		return strings.TrimSpace(v), nil
	}
	out, err := expr.Behavior.Eval(src, r.act(f, 1))
	if err != nil {
		return "", abortf("%s: %v", p, err)
	}
	s, ok := out.(string)
	if !ok || s == "" {
		return "", abortf("%s: a token name must be a non-empty string, got %#v", p, out)
	}
	return s, nil
}

// await registers the running task as waiting on a token.
func (r *run) await(name string, phase int) *tokenWait {
	w := &tokenWait{t: r.s.cur, phase: phase}
	tk := r.token(name)
	tk.waiters = append(tk.waiters, w)
	return w
}

func (r *run) unawait(name string, w *tokenWait) {
	w.done = true
	tk := r.token(name)
	for i, x := range tk.waiters {
		if x == w {
			tk.waiters = append(tk.waiters[:i:i], tk.waiters[i+1:]...)
			return
		}
	}
}

func canceledError(name string) *Error {
	return &Error{Code: "canceled", Message: fmt.Sprintf("token %s was canceled", name)}
}

// cancel cancels a token now, with a cancel event from comp on inst.
func (r *run) cancel(name, comp, inst string, span int) error {
	tk := r.token(name)
	pending := 0
	if !tk.canceled {
		tk.canceled, tk.at = true, r.now
		for _, w := range tk.waiters {
			if !w.done && !w.canceled {
				w.canceled = true
				pending++
				r.wakeAt(w.t, r.now, w.phase)
			}
		}
		tk.waiters = nil
		pending += r.dropDeliveries(func(t *timer) bool { return t.token == name })
	}
	return r.ev(Event{Type: "cancel", Span: span, Component: comp, Instance: inst, Key: name,
		Output: map[string]any{"pending": int64(pending)}})
}

// dropDeliveries removes the queued deliveries that match from every lane.
func (r *run) dropDeliveries(match func(*timer) bool) int {
	n := 0
	for _, ln := range r.lanes {
		kept := ln.queue[:0]
		for _, t := range ln.queue {
			if t.late == nil && match(t) {
				n++
				continue
			}
			kept = append(kept, t)
		}
		for i := len(kept); i < len(ln.queue); i++ {
			ln.queue[i] = nil
		}
		ln.queue = kept
		r.settle(ln)
	}
	return n
}

// invokeBound runs a token-bound call: the callee runs as its own task
// while the caller waits for it or for the cancel. A canceled call fails
// at the cancel time; the callee runs on, and its later events are late.
//
// name may be empty for a call bound only to a session (§13.1 item 35):
// closing the session cancels the call in the same way. A session is never
// closed for good, so a later call carrying it runs.
func (r *run) invokeBound(name string, c callSpec) (callResult, error) {
	if name != "" && r.isCanceled(name) {
		return callResult{err: canceledError(name), target: c.target, cancel: markedAt(r.token(name).at)}, nil
	}
	c.cancel = &cancelMark{} // §16.4
	w := &tokenWait{t: r.s.cur}
	if name != "" {
		w = r.await(name, 0)
		defer r.unawait(name, w)
	}
	if c.session != "" {
		sw := r.awaitSession(c.session, w)
		defer r.unawaitSession(c.session, sw)
	}
	parent := r.s.cur
	var res callResult
	finished := false
	child := r.spawn(kindChild, r.now, parent, func(t *task) error {
		var err error
		res, err = r.invoke(c)
		return err
	})
	if f, ok := r.x.Interfaces[c.target]; ok {
		child.homeComp, child.homeInst = f.Component, c.inst
	}
	child.onDone = append(child.onDone, func() {
		finished = true
		if child.killed && !child.detached {
			res = callResult{err: deathError(child, c.target), target: c.target}
		}
		if !w.done && !w.canceled {
			r.wakeAt(parent, max(r.now, parent.parked), 0)
		}
	})
	for !finished && !w.canceled {
		if err := r.parkBlocked(noDeadline, 0); err != nil {
			child.detached = true
			return callResult{}, err
		}
	}
	if !finished {
		child.detached = true
		c.cancel.mark(r.now)
		if w.session != "" {
			return callResult{err: sessionClosedError(w.session), target: c.target, cancel: c.cancel}, nil
		}
		return callResult{err: canceledError(name), target: c.target, cancel: c.cancel}, nil
	}
	return res, nil
}

// waitBound is a token-bound wait: it ends after ms, or fails with
// canceled when the token is canceled first.
func (r *run) waitBound(f *frame, s model.Step, ms int64, p string) (*Error, error) {
	name, err := r.tokenOf(f, s.Token, p+".token")
	if err != nil {
		return nil, err
	}
	if r.isCanceled(name) {
		return canceledError(name), nil
	}
	w := r.await(name, 0)
	defer r.unawait(name, w)
	until := r.now + ms
	for r.now < until && !w.canceled {
		if err := r.parkBlocked(until, 0); err != nil {
			return nil, err
		}
	}
	if w.canceled && r.now < until {
		return canceledError(name), nil
	}
	return nil, nil
}

// restartIn runs a behavior's restart step. Without an instance it
// restarts the running instance when the component shares its group.
func (r *run) restartIn(f *frame, rs *model.Restart, p string) error {
	inst := rs.Instance
	if src, ok := expr.ExprOf(inst); ok {
		v, err := expr.Behavior.Eval(src, r.act(f, 1))
		if err != nil {
			return abortf("%s.restart.instance: %v", p, err)
		}
		s, ok := v.(string)
		if !ok {
			return abortf("%s.restart.instance: must give an instance name, got %T", p, v)
		}
		inst = s
	} else if inst == "" {
		if g, fg := r.groupOf(rs.Component), r.groupOf(f.comp); g.ok && fg.ok && g.group == fg.group {
			inst = f.inst
		}
	}
	return r.restart(rs, inst, f.comp, f.inst, f.span, p+".restart")
}

// restart restarts a component instance's group (§13.1 item 14): every
// component of the group on that instance gets back its starting-world
// state, except the components in keep; the instance's pending tasks are
// canceled and its queued deliveries dropped; a restart event records it.
func (r *run) restart(rs *model.Restart, inst, fromComp, fromInst string, span int, p string) error {
	// The group: the components whose nearest topology entry is the
	// group's, or, for a component without instances, its subtree.
	sc, err := r.scopeOf(rs.Component, inst, p)
	if err != nil {
		return err
	}
	inst = sc.inst
	member := func(comp string) bool {
		if containsStr(rs.Keep, comp) {
			return false
		}
		grp, _, ok := r.x.InstanceGroup(sc.topo, comp)
		return ok && grp == sc.root
	}
	inGroup := func(comp, i string) bool { return r.in(sc, comp, i) }
	// A restart revives a killed instance (§13.1 item 18): the kept
	// components lose their dead mark too.
	_, wasDead := r.dead[sc.key()]
	delete(r.dead, sc.key())
	var reset []any
	keys := map[string]bool{}
	for k := range r.states {
		keys[k] = true
	}
	for k := range r.initial {
		keys[k] = true
	}
	for _, k := range sortedKeys(keys) {
		c, i := model.SplitStateKey(k)
		if i != inst || !member(c) {
			continue
		}
		if init, ok := r.initial[k]; ok {
			r.states[k] = deepCopy(init).(map[string]any)
		} else {
			r.states[k] = map[string]any{}
		}
		reset = append(reset, k)
	}
	// In-process limiters (instance scope) lose their state too (§13.1
	// item 27).
	r.resetLimiters(func(c, i string) bool { return i == inst && member(c) })
	if wasDead {
		for _, k := range sortedKeys(r.states) {
			if c, i := model.SplitStateKey(k); i == inst && inGroup(c, i) {
				delete(r.states[k], "dead")
			}
		}
	}
	// Cancel the instance's tasks, but never the one restarting it or the
	// tasks it works for.
	mine := map[*task]bool{}
	for k := r.s.cur; k != nil; k = k.parent {
		mine[k] = true
	}
	var victims []*task
	for _, t := range r.s.live {
		if !mine[t] && t.homeComp != "" && inGroup(t.homeComp, t.homeInst) {
			victims = append(victims, t)
		}
	}
	sortTasks(victims)
	for _, t := range victims {
		r.kill(t)
	}
	dropped := r.dropDeliveries(func(t *timer) bool {
		f, ok := r.x.Interfaces[t.target]
		return ok && inGroup(f.Component, t.inst)
	})
	// A live instance's processes exit on a restart; a dead one's already
	// did, at its kill (§17 item 14, exits.go).
	r.forgetExits(sc)
	if !wasDead {
		r.raiseExits(sc, "restarted")
	}
	if reset == nil {
		reset = []any{}
	}
	keep := make([]any, len(rs.Keep))
	for i, k := range rs.Keep {
		keep[i] = k
	}
	return r.ev(Event{Type: "restart", Span: span, Component: rs.Component, Instance: inst, From: fromComp,
		Output: map[string]any{"reset": reset, "kept": keep, "canceled": int64(len(victims)), "dropped": int64(dropped)}})
}

func sortTasks(ts []*task) {
	for i := 1; i < len(ts); i++ {
		for j := i; j > 0 && ts[j].id < ts[j-1].id; j-- {
			ts[j], ts[j-1] = ts[j-1], ts[j]
		}
	}
}

package sim

// Hangs without release, run caps, response headers and sessions (§13.1
// item 35).

import (
	"fmt"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
)

// pendingCall is a call held by a hang with forever: true.
type pendingCall struct {
	PendingCall
	t    *task
	done bool // it ended: a kill, a restart or an unwind
}

// hangForever holds the running task in a call that never answers (a hang,
// timeout or lost_reply fault with forever: true, §13.1 item 35) when the
// caller set no timeout_ms and no deadline. The call ends only when a kill
// or a restart stops the task; a cancel of the caller's token or session
// detaches the caller and leaves the callee hanging. Like an idle consumer,
// the task doesn't hold back the end of a step or of the run, and a call
// still hanging then is reported as pending, with no synthetic error.
func (r *run) hangForever(c callSpec, fault string) error {
	t := r.s.cur
	if t == nil {
		return abortf("%s: a call outside any task cannot hang", c.target)
	}
	pc := &pendingCall{PendingCall: PendingCall{Call: c.callID, From: c.from, Interface: c.target, Instance: c.inst,
		StartMS: msFloor(r.now), Fault: fault}, t: t}
	r.pending = append(r.pending, pc)
	if t.kind == kindRoot || t.kind == kindLane {
		r.s.end = max(r.s.end, r.now)
	}
	t.idle, t.hung = true, true
	r.checkQuiet()
	var err error
	for err == nil {
		err = r.park(noDeadline, 0) // only a stop resumes it
	}
	t.idle = false
	if !r.s.stopped {
		pc.done = true
		t.hung = false
	}
	return err
}

// pendingCalls are the calls still hanging when the run ended, except
// those whose caller gave up on them (a canceled token or a closed
// session): those callers already got their error.
func (r *run) pendingCalls() []PendingCall {
	var out []PendingCall
	for _, pc := range r.pending {
		if pc.done || detached(pc.t) {
			continue
		}
		out = append(out, pc.PendingCall)
	}
	return out
}

// detached reports whether a task, or a task it works for, was given up on.
func detached(t *task) bool {
	for k := t; k != nil; k = k.parent {
		if k.detached {
			return true
		}
	}
	return false
}

// caps reports the run's caps, with the one that ended it (§13.1 item 35).
func (r *run) caps(hit string) *Caps {
	c := &Caps{MaxEvents: r.lim.MaxEvents, Hit: hit}
	if r.s.limit != noDeadline {
		ms := r.s.limit / 1000
		c.MaxVirtualMS = &ms
	}
	return c
}

// responseHeaders makes a call's result keep its response headers (§13.1
// item 35) and returns them at lower-case keys for the trace, or nil. A
// value's headers keep the keys the model wrote and gain a lower-case
// alias for each one that isn't lower case, so headers['retry-after']
// reads Retry-After. A failure's headers (a fail's headers) become its
// value's: {headers}.
func responseHeaders(res *callResult) map[string]any {
	if !res.ok {
		if res.err == nil || res.err.Headers == nil {
			return nil
		}
		if res.value == nil {
			res.value = map[string]any{"headers": deepCopy(res.err.Headers)}
		}
		return deepCopy(res.err.Headers).(map[string]any)
	}
	v, ok := res.value.(map[string]any)
	if !ok {
		return nil
	}
	h, ok := v["headers"].(map[string]any)
	if !ok {
		return nil
	}
	var alias map[string]any
	for k, x := range h {
		if l := strings.ToLower(k); l != k {
			if _, taken := h[l]; !taken {
				if alias == nil {
					alias = map[string]any{}
				}
				alias[l] = x
			}
		}
	}
	if alias != nil {
		// Copy, since the value may share maps with state.
		nh := make(map[string]any, len(h)+len(alias))
		for k, x := range h {
			nh[k] = x
		}
		for k, x := range alias {
			nh[k] = x
		}
		nv := make(map[string]any, len(v))
		for k, x := range v {
			nv[k] = x
		}
		nv["headers"] = nh
		res.value = nv
	}
	return lowerHeaders(h)
}

// lowerHeaders copies headers at lower-case keys; a key written in lower
// case wins over another spelling of it.
func lowerHeaders(h map[string]any) map[string]any {
	out := make(map[string]any, len(h))
	for _, k := range sortedKeys(h) {
		l := strings.ToLower(k)
		if _, taken := out[l]; taken && l != k {
			continue
		}
		out[l] = deepCopy(h[k])
	}
	return out
}

// Sessions (§13.1 item 35). A call that carries session: <key> is bound to
// the session while it is in flight; close: {session: <key>} cancels every
// such call, as the death of a tunnel or connection that the peer sees.
// Their callers get {code: canceled} at the close time, and the callees run
// on, their later events late, as for a canceled token. Unlike a token, a
// closed session isn't closed for good: a later call carrying the key runs.

// sessionWait ties a token waiter to a session.
type sessionWait struct{ w *tokenWait }

func (r *run) awaitSession(key string, w *tokenWait) *sessionWait {
	if r.sessions == nil {
		r.sessions = map[string][]*sessionWait{}
	}
	sw := &sessionWait{w: w}
	r.sessions[key] = append(r.sessions[key], sw)
	return sw
}

func (r *run) unawaitSession(key string, sw *sessionWait) {
	list := r.sessions[key]
	for i, x := range list {
		if x == sw {
			r.sessions[key] = append(list[:i:i], list[i+1:]...)
			break
		}
	}
	if len(r.sessions[key]) == 0 {
		delete(r.sessions, key)
	}
}

// closeSession cancels the calls in flight that carry key, with a close
// event from comp on inst (output.pending: the calls canceled).
func (r *run) closeSession(key, comp, inst string, span int) error {
	pending := 0
	for _, sw := range r.sessions[key] {
		w := sw.w
		if !w.done && !w.canceled {
			w.canceled, w.session = true, key
			pending++
			r.wakeAt(w.t, r.now, w.phase)
		}
	}
	delete(r.sessions, key)
	return r.ev(Event{Type: "close", Span: span, Component: comp, Instance: inst, Key: key,
		Output: map[string]any{"pending": int64(pending)}})
}

func sessionClosedError(key string) *Error {
	return &Error{Code: "canceled", Message: fmt.Sprintf("session %s was closed", key)}
}

// sessionOf evaluates a session key: a literal or "=cel" giving a string or
// a number. Empty means none.
func (r *run) sessionOf(f *frame, v, p string) (string, error) {
	src, ok := expr.ExprOf(v)
	if !ok {
		return strings.TrimSpace(v), nil
	}
	out, err := expr.Behavior.Eval(src, r.act(f, 1))
	if err != nil {
		return "", abortf("%s: %v", p, err)
	}
	switch t := out.(type) {
	case string:
		if t != "" {
			return t, nil
		}
	case int64, uint64, float64, bool:
		return fmt.Sprint(t), nil
	}
	return "", abortf("%s: a session key must be a non-empty string or a number, got %#v", p, out)
}

package sim

import (
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Streams (§13.1 item 18). A behavior's yield step sends one item to its
// caller while the behavior keeps running. A caller that opts in with
// stream: true runs the callee as its own task and runs its on_item steps
// for each item at the item's virtual time (or, while it is still busy
// with the previous one, when it is free), interleaved with the callee.
// The call's result is the callee's return. Without stream: true the
// items are collected and the caller gets {items, value}, unless the
// callee's streams_when (§17 item 12) is false for this call: then the
// caller gets the plain return and a yield aborts.

type stream struct {
	live   bool  // the caller consumes the items as they come
	items  []any // the items collected for a caller that doesn't stream
	queue  []streamItem
	n      int64
	caller *task
	parked bool        // the caller is waiting for an item or the end
	flow   *streamFlow // window and stall_ms (§16.4); nil means none
	up     *stream     // the stream a relay forwards into (§17 item 5)
}

type streamItem struct {
	value any
	index int64
	at    int64
	size  int64 // the frame's bytes, for window_bytes (§17 item 5)
}

// hasYield reports whether an interface's behavior can yield, so that a
// call to it that doesn't stream gets {items, value}.
func (r *run) hasYield(f *model.Interface) bool {
	if v, ok := r.yields[f.ID]; ok {
		return v
	}
	found := f.CanYield()
	r.yields[f.ID] = found
	return found
}

// streamsWhen evaluates an interface's streams_when for one call (§17 item
// 12). Without the field, a call streams whenever the behavior can yield.
func (r *run) streamsWhen(fr *frame) (bool, error) {
	f := fr.iface
	if f.StreamsWhen == "" {
		return true, nil
	}
	src, _ := strings.CutPrefix(f.StreamsWhen, "=")
	on, err := expr.Behavior.EvalBool(strings.TrimSpace(src), r.act(fr, 1))
	if err != nil {
		return false, abortf("%s.streams_when: %v", f.ID, err)
	}
	return on, nil
}

// yieldValue evaluates a yield step's item.
func (r *run) yieldValue(f *frame, s model.Step, p string) (any, error) {
	t, err := expr.DecodeTemplate(s.Yield)
	var v any
	if err == nil {
		v, err = expr.Behavior.Template(t, r.act(f, 1))
	}
	if err != nil {
		return nil, abortf("%s.yield: %v", p, err)
	}
	return v, nil
}

// yieldItem hands an evaluated item of a yield step to the frame's stream.
func (r *run) yieldItem(f *frame, v any, size int64, p string) error {
	v, hdr := frameHeaders(v) // a frame's headers (§15.3)
	var idx int64
	if st := f.stream; st != nil {
		idx = st.n
		st.n++
		if st.live {
			st.queue = append(st.queue, streamItem{value: deepCopy(v), index: idx, at: r.now, size: size})
			if st.parked {
				st.parked = false
				r.wakeAt(st.caller, r.now, 0)
			}
		} else {
			st.items = append(st.items, deepCopy(v))
		}
	} else {
		r.warn(p + ": a yield outside a call has no caller to receive it")
	}
	return r.ev(Event{Type: "yield", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst,
		Output: deepCopy(v), Index: &idx, Headers: hdr})
}

// collected wraps a finished callee's return with the items it yielded,
// for a caller that doesn't stream.
func collected(st *stream, value any) any {
	items := st.items
	if items == nil {
		items = []any{}
	}
	out := map[string]any{"items": items, "value": value}
	collectedHeaders(out, value) // result.value.headers (§15.3)
	return out
}

// invokeStream runs a streaming call: the callee runs as its own task and
// the caller runs onItem for each item it yields. A token cancels the
// wait. An exit or error in the on_item steps ends the call there: the
// callee runs on, and its later events are late.
func (r *run) invokeStream(f *frame, s model.Step, tok string, c callSpec, depth int, p string) (callResult, *exit, error) {
	if tok != "" && r.isCanceled(tok) {
		return callResult{err: canceledError(tok), target: c.target, cancel: markedAt(r.token(tok).at)}, nil, nil
	}
	parent := r.s.cur
	st := &stream{live: true, caller: parent}
	if s.Relay { // §17 item 5
		st.up = f.stream
	}
	if err := r.setupFlow(f, s, st, p); err != nil { // §16.4
		return callResult{}, nil, err
	}
	defer r.flowGone(st)
	c.stream = st
	c.cancel = &cancelMark{} // §16.4
	var res callResult
	finished := false
	child := r.spawn(kindChild, r.now, parent, func(t *task) error {
		var err error
		res, err = r.invoke(c)
		return err
	})
	if fi, ok := r.x.Interfaces[c.target]; ok {
		child.homeComp, child.homeInst = fi.Component, c.inst
	}
	child.onDone = append(child.onDone, func() {
		finished = true
		if child.killed && !child.detached {
			res = callResult{err: deathError(child, c.target), target: c.target}
		}
		if st.parked {
			st.parked = false
			r.wakeAt(parent, max(r.now, parent.parked), 0)
		}
	})
	oldItem, hadItem := f.vars["item"]
	oldIndex, hadIndex := f.vars["item_index"]
	defer func() {
		delete(f.vars, "item")
		delete(f.vars, "item_index")
		if hadItem {
			f.vars["item"] = oldItem
		}
		if hadIndex {
			f.vars["item_index"] = oldIndex
		}
	}()
	for {
		if len(st.queue) > 0 {
			it := st.queue[0]
			st.queue = st.queue[1:]
			r.flowTake(st, it.size)
			if err := r.sleepUntil(it.at); err != nil {
				child.detached = true
				return callResult{}, nil, err
			}
			f.vars["item"], f.vars["item_index"] = it.value, it.index
			ex, err := r.steps(f, s.OnItem, depth, p+".on_item")
			if err != nil || ex != nil {
				child.detached = true
				return callResult{}, ex, err
			}
			r.flowDone(st)
			continue
		}
		if e := flowStalled(st); e != nil {
			child.detached = !finished
			return callResult{err: e, target: c.target}, nil, nil
		}
		if finished {
			return res, nil, nil
		}
		var w *tokenWait
		if tok != "" {
			if r.isCanceled(tok) {
				child.detached = true
				c.cancel.mark(r.token(tok).at)
				return callResult{err: canceledError(tok), target: c.target, cancel: c.cancel}, nil, nil
			}
			w = r.await(tok, 0)
		}
		st.parked = true
		err := r.park(noDeadline, 0)
		st.parked = false
		if w != nil {
			r.unawait(tok, w)
		}
		if err != nil {
			child.detached = true
			return callResult{}, nil, err
		}
	}
}

package sim

import (
	"fmt"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Channels (§13.1 item 18) are run-wide named FIFO queues. A put adds an
// item, blocking while a bounded channel is full; a receive takes the
// oldest item, blocking until one is available. Blocked tasks resume in
// arrival order. A receive with no time limit that is still waiting when
// every other task has finished is an idle consumer: the run ends without
// it.

type channel struct {
	items []any
	cap   int64 // 0: unbounded
	recv  []*chanWaiter
	send  []*chanWaiter
}

// chanWaiter is a task blocked on a channel: a receiver, or a producer
// with the item it puts.
type chanWaiter struct {
	t     *task
	value any
	done  bool
}

func (r *run) channel(name string) *channel {
	ch, ok := r.chans[name]
	if !ok {
		ch = &channel{}
		r.chans[name] = ch
	}
	return ch
}

// channelLen is CEL channel_len(name): the items queued.
func (r *run) channelLen(name string) int64 {
	if ch, ok := r.chans[name]; ok {
		return int64(len(ch.items))
	}
	return 0
}

func dropChanWaiter(ws []*chanWaiter, w *chanWaiter) []*chanWaiter {
	for i, x := range ws {
		if x == w {
			return append(ws[:i:i], ws[i+1:]...)
		}
	}
	return ws
}

// admit moves blocked producers' items into the channel while it has room.
func (r *run) admit(ch *channel) {
	for len(ch.send) > 0 && (ch.cap == 0 || int64(len(ch.items)) < ch.cap) {
		w := ch.send[0]
		ch.send = ch.send[1:]
		ch.items = append(ch.items, w.value)
		w.done = true
		r.wakeAt(w.t, r.now, 0)
	}
}

// waitLimit is when a blocking step gives up: its timeout_ms or the
// deadline, whichever is earlier.
func (r *run) waitLimit(f *frame, timeout int64) int64 {
	limit := f.deadline
	if timeout > 0 {
		limit = min(limit, r.now+timeout)
	}
	return limit
}

func chanTimeout(op, name string, waited int64) *Error {
	return &Error{Code: "timeout", Retryable: true, Message: fmt.Sprintf("%s on channel %s timed out after %s ms", op, name, fmtMS(waited)),
		Data: map[string]any{"channel": name}}
}

// put runs a put step.
func (r *run) put(f *frame, s model.Step, depth int, p string) (*exit, error) {
	name, err := r.tokenOf(f, s.Put, p+".put")
	if err != nil {
		return nil, err
	}
	var value any
	if s.Value != nil {
		t, err := expr.DecodeTemplate(s.Value)
		if err == nil {
			value, err = expr.Behavior.Template(t, r.act(f, 1))
		}
		if err != nil {
			return nil, abortf("%s.value: %v", p, err)
		}
	}
	ch := r.channel(name)
	if !s.Capacity.IsZero() {
		n, err := r.countOf(f, s.Capacity, p+".capacity")
		if err != nil {
			return nil, err
		}
		if n < 1 {
			return nil, abortf("%s.capacity: a channel capacity is at least 1, got %d", p, n)
		}
		if ch.cap != 0 && ch.cap != n {
			r.warn(fmt.Sprintf("%s: channel %s has capacity %d; a put gave %d", p, name, ch.cap, n))
		} else {
			ch.cap = n
		}
	}
	timeout, err := r.intOf(f, s.TimeoutMS, p+".timeout_ms")
	if err != nil {
		return nil, err
	}
	start := r.now
	value = deepCopy(value)
	switch {
	case len(ch.recv) > 0:
		// A receiver is waiting: hand the item over.
		w := ch.recv[0]
		ch.recv = ch.recv[1:]
		w.value, w.done = value, true
		r.wakeAt(w.t, r.now, 0)
	case ch.cap > 0 && int64(len(ch.items)) >= ch.cap:
		w := &chanWaiter{t: r.s.cur, value: value}
		ch.send = append(ch.send, w)
		limit := r.waitLimit(f, timeout)
		for !w.done && r.now < limit {
			if err := r.parkBlocked(limit, 0); err != nil {
				ch.send = dropChanWaiter(ch.send, w)
				return nil, err
			}
		}
		if !w.done {
			ch.send = dropChanWaiter(ch.send, w)
			e := chanTimeout("put", name, r.now-start)
			if err := r.ev(Event{Type: "put", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst, Key: name,
				Input: deepCopy(value), Error: e, WaitMS: r.now - start}); err != nil {
				return nil, err
			}
			f.lastErr = e.Map()
			return r.onError(f, s.OnError, e, depth, p, false)
		}
	default:
		ch.items = append(ch.items, value)
	}
	return nil, r.ev(Event{Type: "put", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst, Key: name,
		Input: deepCopy(value), Output: map[string]any{"len": int64(len(ch.items))}, WaitMS: r.now - start})
}

// receive runs a receive step.
func (r *run) receive(f *frame, s model.Step, depth int, p string) (*exit, error) {
	name, err := r.tokenOf(f, s.Receive, p+".receive")
	if err != nil {
		return nil, err
	}
	timeout, err := r.intOf(f, s.TimeoutMS, p+".timeout_ms")
	if err != nil {
		return nil, err
	}
	ch := r.channel(name)
	start := r.now
	var value any
	if len(ch.items) > 0 {
		value = ch.items[0]
		ch.items[0] = nil
		ch.items = ch.items[1:]
		r.admit(ch)
	} else {
		w := &chanWaiter{t: r.s.cur}
		ch.recv = append(ch.recv, w)
		limit := r.waitLimit(f, timeout)
		for !w.done && r.now < limit {
			var err error
			if limit == noDeadline {
				err = r.parkBlockedIdle()
			} else {
				err = r.parkBlocked(limit, 0)
			}
			if err != nil {
				ch.recv = dropChanWaiter(ch.recv, w)
				return nil, err
			}
		}
		if !w.done {
			ch.recv = dropChanWaiter(ch.recv, w)
			e := chanTimeout("receive", name, r.now-start)
			if err := r.ev(Event{Type: "receive", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst, Key: name,
				Error: e, WaitMS: r.now - start}); err != nil {
				return nil, err
			}
			f.lastErr = e.Map()
			return r.onError(f, s.OnError, e, depth, p, false)
		}
		value = w.value
	}
	if s.As != "" {
		f.vars[s.As] = deepCopy(value)
	}
	return nil, r.ev(Event{Type: "receive", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst, Key: name,
		Output: deepCopy(value), WaitMS: r.now - start})
}

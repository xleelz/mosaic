package sim

import (
	"fmt"
	"math"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// timing is when an emit or publish is delivered (§11.3): after the
// current top-level call tree, or on a timer: after `after` ms, then
// count-1 more times every `every` ms.
type timing struct {
	timer bool
	after int64
	every int64
	count int
}

func (r *run) timing(f *frame, s model.Step, p string) (timing, error) {
	after, err := r.intOf(f, s.AfterMS, p+".after_ms")
	if err != nil {
		return timing{}, err
	}
	every, err := r.intOf(f, s.EveryMS, p+".every_ms")
	if err != nil {
		return timing{}, err
	}
	tm := timing{timer: after > 0 || every > 0, after: after, every: every, count: 1}
	if every > 0 {
		n, err := r.countOf(f, s.Count, p+".count")
		if err != nil {
			return timing{}, err
		}
		if n < 1 || n > model.MaxTimerCount {
			return timing{}, abortf("%s.count: a periodic timer needs a count between 1 and %d, got %d", p, model.MaxTimerCount, n)
		}
		tm.count = int(n)
	}
	return tm, nil
}

// delivery is an asynchronous call waiting in the queue.
type delivery struct {
	from      string
	fromInst  string
	fromIface string // the emitting interface (§13.1 item 35)
	target    string
	inst      string
	badInst   bool
	input     any
	parent    int
	token     string // a cancellation token whose cancel drops the delivery
}

// timer is a queued delivery. Plain emits are due at once (due is
// math.MinInt64), so they keep their first-in, first-out order ahead of
// timers; a plain emit made by a callee that finished after its caller's
// timeout is due at the callee's end instead (§13.1 item 14). Timers are
// delivered in time order, and in schedule order within the same time; a
// periodic timer stays queued until its last delivery.
type timer struct {
	delivery
	due     int64
	seq     int
	isTimer bool
	every   int64
	left    int
	late    *lateWork // on_late steps to run instead of a call
}

// lane holds the emits and timers of one root task (the flow entry's
// pass, or a scenario step) and delivers them one at a time, in time
// order, once the root's own call tree has finished, as the drain did
// before tasks: a lane task runs while the lane has work.
type lane struct {
	queue    []*timer
	open     bool      // the root's call tree has finished
	task     *task     // the lane's running task, if any
	sleeping bool      // the lane task is waiting for the next due time
	choice   choiceSet // the root's choices, which its deliveries see
	busy     bool      // the lane task is delivering
	// settled, when set, is called once the lane has nothing left to
	// deliver: a scenario step ends when its call tree and its emits and
	// timers are done, as before tasks.
	settled func()
}

// settle calls the lane's settled callback once nothing is queued or
// being delivered.
func (r *run) settle(ln *lane) {
	if ln.settled == nil || ln.busy || len(ln.queue) > 0 {
		return
	}
	f := ln.settled
	ln.settled = nil
	f()
}

// lateWork is a parallel step's on_late steps for one late branch (§13.1
// item 12), run at the branch's end time with vars.late set.
type lateWork struct {
	frame  *frame
	steps  []model.Step
	depth  int
	path   string
	branch int
}

// enqueue adds a delivery to the running task's lane, starting the lane
// task if the lane is open and idle, or waking it if it sleeps until a
// later time.
func (r *run) enqueue(t *timer) {
	ln := r.curLane()
	ln.queue = append(ln.queue, t)
	r.kickLane(ln, t.due)
}

func (r *run) kickLane(ln *lane, due int64) {
	if !r.laneMayRun(ln) || r.s.stopped {
		return
	}
	if ln.task == nil {
		r.startLane(ln, r.now)
		return
	}
	if ln.sleeping && ln.task.hidx >= 0 && max(due, r.now) < ln.task.at {
		r.wakeAt(ln.task, max(due, r.now), 0)
	}
}

// curLane is the lane of the running task.
func (r *run) curLane() *lane {
	if r.s.cur != nil && r.s.cur.lane != nil {
		return r.s.cur.lane
	}
	if r.spare == nil {
		r.spare = &lane{}
	}
	return r.spare
}

// openLane lets a root's deliveries run, from now.
func (r *run) openLane(ln *lane) {
	ln.open = true
	if ln.task == nil && len(ln.queue) > 0 && !r.s.stopped {
		r.startLane(ln, r.now)
	}
}

func (r *run) startLane(ln *lane, at int64) {
	ln.task = r.spawn(kindLane, at, nil, func(t *task) error { return r.drain(ln) })
	ln.task.lane, ln.task.choice = ln, ln.choice
	lt := ln.task
	lt.onDone = append(lt.onDone, func() {
		ln.busy = false
		if ln.task == lt {
			ln.task, ln.sleeping = nil, false
			if len(ln.queue) > 0 && !r.s.stopped && r.laneMayRun(ln) {
				r.startLane(ln, r.now)
			}
		}
		if r.s.stopped {
			ln.queue = nil
		}
		r.settle(ln)
	})
}

// scheduleLate queues on_late work, delivered like a timer due at at.
func (r *run) scheduleLate(at int64, w *lateWork) {
	r.timerSeq++
	r.enqueue(&timer{seq: r.timerSeq, due: at, isTimer: true, left: 1, late: w})
}

// runLate runs on_late work at its due time, the late branch's end, with
// every event it records marked late and branch set to the late branch.
// The clock then resumes at the later of where it was and where the work
// ended. Errors and returns end only the work.
func (r *run) runLate(t *timer) error {
	w := t.late
	resume := r.now
	r.now = t.due
	first := len(r.events)
	cur := r.s.cur
	prev, bi := cur.branch, w.branch
	cur.branch = &bi
	_, err := r.steps(w.frame, w.steps, w.depth, w.path)
	cur.branch = prev
	for k := first; k < len(r.events); k++ {
		r.events[k].Late = true
	}
	r.now = max(resume, r.now)
	return err
}

func (r *run) schedule(tm timing, d delivery) {
	r.timerSeq++
	t := &timer{delivery: d, seq: r.timerSeq, due: math.MinInt64}
	if tm.timer {
		t.isTimer, t.due, t.every, t.left = true, r.now+tm.after, tm.every, max(tm.count, 1)
	}
	r.enqueue(t)
}

// postpone makes the plain emits scheduled after seq by the running
// task's lane due no earlier than end: the end time of a callee that
// finished after its caller's timeout (§13.1 item 14).
func (r *run) postpone(seq int, end int64) {
	ln := r.curLane()
	for _, t := range ln.queue {
		if t.seq > seq && !t.isTimer && t.late == nil {
			t.due = max(t.due, end)
		}
	}
}

// drain is a lane task: it delivers the lane's emits and timers one at a
// time, in (due, seq) order, including those the deliveries schedule,
// until the lane is empty.
func (r *run) drain(ln *lane) error {
	me := r.s.cur
	for len(ln.queue) > 0 && r.laneMayRun(ln) {
		bi := 0
		for i, t := range ln.queue {
			if b := ln.queue[bi]; t.due < b.due || (t.due == b.due && t.seq < b.seq) {
				bi = i
			}
		}
		t := ln.queue[bi]
		if t.late == nil && t.due > r.now {
			// Wait for the due time; an earlier delivery may arrive, or a
			// cancel or restart may drop this one, so pick again after.
			ln.sleeping = true
			err := r.park(t.due, 0)
			ln.sleeping = false
			if err != nil {
				return err
			}
			continue
		}
		if r.s.xp != nil {
			bi = r.xpDelivery(ln, bi) // same-time deliveries are a choice point (§15.5)
			t = ln.queue[bi]
		}
		input := t.input
		if t.isTimer {
			r.timers++
			if r.timers > r.lim.MaxTimers {
				return abortf("timer budget of %d deliveries exceeded", r.lim.MaxTimers)
			}
			input = deepCopy(t.input)
		}
		if t.isTimer && t.left > 1 {
			t.left--
			t.due += t.every
		} else {
			ln.queue = append(ln.queue[:bi], ln.queue[bi+1:]...)
		}
		if t.late != nil {
			me.homeComp, me.homeInst = "", ""
			ln.busy = true
			if err := r.runLate(t); err != nil {
				return err
			}
			ln.busy = false
			r.settle(ln)
			continue
		}
		if f, ok := r.x.Interfaces[t.target]; ok {
			me.homeComp, me.homeInst = f.Component, t.inst
		}
		ln.busy = true
		if _, err := r.invoke(callSpec{from: t.from, fromInst: t.fromInst, fromIface: t.fromIface, target: t.target, inst: t.inst, badInst: t.badInst, input: input, parent: t.parent,
			callID: r.nextCall(), attempt: 1, depth: 1, deadline: noDeadline, async: true}); err != nil {
			return err
		}
		ln.busy = false
		r.settle(ln)
		me.homeComp, me.homeInst = "", ""
	}
	return nil
}

// interval is a span of virtual time [start, end). A call in progress, or
// a call still waiting for a slot, has end math.MaxInt64 until it is known.
type interval struct{ start, end int64 }

// slot is a capacity slot held by a call in progress.
type slot struct {
	key    string
	iv     *interval
	holder *task
	active bool
}

// capWaiter is a call waiting for a slot that a call in progress holds.
type capWaiter struct {
	t     *task
	woken bool
}

// acquire takes a capacity slot (§11.4) on the callee's instance for a
// call arriving now. A call that finds every slot busy waits for the
// earliest to free, with a queue event; past queue_limit or
// queue_timeout_ms it is refused with overloaded. A call nested inside one
// that already holds a slot on the same instance runs in that slot. When
// the busy slots belong to calls still in progress (in other tasks), the
// wait lasts until one of them releases its slot, in arrival order.
func (r *run) acquire(f *model.Interface, skey string, span int, c callSpec) (slot, *Error, error) {
	comp := r.x.Components[f.Component]
	if comp == nil || comp.Capacity == nil || r.heldBy(skey) {
		return slot{}, nil, nil
	}
	cp := comp.Capacity
	n := max(cp.Concurrency, 1)
	t := r.now
	free := r.freeAt(skey, n, t)
	if free > t {
		waiting := 0
		for _, w := range r.waiting[skey] {
			if w.start <= t && t < w.end {
				waiting++
			}
		}
		if cp.QueueLimit != nil && waiting >= *cp.QueueLimit {
			return slot{}, &Error{Code: "overloaded", Retryable: true,
				Message: fmt.Sprintf("%s: all %d slots are busy and %d calls are waiting", skey, n, waiting)}, nil
		}
		timedOutErr := &Error{Code: "overloaded", Retryable: true,
			Message: fmt.Sprintf("%s: no slot freed within queue_timeout_ms %d", skey, cp.QueueTimeoutMS)}
		if free != math.MaxInt64 {
			wait := free - t
			timedOut := cp.QueueTimeoutMS > 0 && wait > cp.QueueTimeoutMS*1000
			if timedOut {
				wait = cp.QueueTimeoutMS * 1000
			}
			r.waiting[skey] = append(r.waiting[skey], &interval{t, t + wait})
			r.queued++
			if err := r.ev(Event{Type: "queue", Span: span, Call: c.callID, Component: f.Component, From: c.from, To: f.Component,
				Interface: f.ID, Instance: c.inst, WaitMS: wait}); err != nil {
				return slot{}, nil, err
			}
			if err := r.sleepUntil(t + wait); err != nil {
				return slot{}, nil, err
			}
			if timedOut {
				return slot{}, timedOutErr, nil
			}
		} else {
			w := &interval{t, math.MaxInt64}
			r.waiting[skey] = append(r.waiting[skey], w)
			r.queued++
			limit := int64(noDeadline)
			if cp.QueueTimeoutMS > 0 {
				limit = t + cp.QueueTimeoutMS*1000
			}
			cw := &capWaiter{t: r.s.cur}
			r.capWaiters[skey] = append(r.capWaiters[skey], cw)
			for {
				err := r.park(limit, 0)
				r.dropWaiter(skey, cw)
				if err != nil {
					w.end = r.now
					r.passSlot(skey, n)
					return slot{}, nil, err
				}
				if free = r.freeAt(skey, n, r.now); free <= r.now {
					break
				}
				if r.now >= limit {
					w.end = r.now
					if err := r.queueEvent(f, span, c, t); err != nil {
						return slot{}, nil, err
					}
					return slot{}, timedOutErr, nil
				}
				if free != math.MaxInt64 {
					if err := r.sleepUntil(min(free, limit)); err != nil {
						w.end = r.now
						return slot{}, nil, err
					}
					if r.now < free {
						w.end = r.now
						if err := r.queueEvent(f, span, c, t); err != nil {
							return slot{}, nil, err
						}
						return slot{}, timedOutErr, nil
					}
					break
				}
				// Someone else took the slot: wait again, first in line.
				cw = &capWaiter{t: r.s.cur}
				r.capWaiters[skey] = append([]*capWaiter{cw}, r.capWaiters[skey]...)
			}
			w.end = r.now
			if err := r.queueEvent(f, span, c, t); err != nil {
				return slot{}, nil, err
			}
		}
	}
	cur := r.s.cur
	if cur.held == nil {
		cur.held = map[string]int{}
	}
	cur.held[skey]++
	iv := &interval{r.now, math.MaxInt64}
	r.busy[skey] = append(r.busy[skey], iv)
	return slot{key: skey, iv: iv, holder: cur, active: true}, nil, nil
}

// queueEvent records the queue event of a call that arrived at t and
// waited until now for a slot a call in progress held.
func (r *run) queueEvent(f *model.Interface, span int, c callSpec, t int64) error {
	now := r.now
	r.now = t
	err := r.ev(Event{Type: "queue", Span: span, Call: c.callID, Component: f.Component, From: c.from, To: f.Component,
		Interface: f.ID, Instance: c.inst, WaitMS: now - t})
	r.now = now
	return err
}

func (r *run) dropWaiter(key string, cw *capWaiter) {
	ws := r.capWaiters[key]
	for i, w := range ws {
		if w == cw {
			r.capWaiters[key] = append(ws[:i:i], ws[i+1:]...)
			return
		}
	}
}

// release frees a slot, recording its busy interval up to now, and wakes
// the calls waiting for it.
func (r *run) release(s slot) {
	if !s.active {
		return
	}
	s.holder.held[s.key]--
	s.iv.end = r.now
	comp := r.x.Components[strings.SplitN(s.key, "@", 2)[0]]
	n := 1
	if comp != nil && comp.Capacity != nil {
		n = max(comp.Capacity.Concurrency, 1)
	}
	r.passSlot(s.key, n)
}

// passSlot wakes, in arrival order, as many waiting calls as there are
// free slots on key now.
func (r *run) passSlot(key string, n int) {
	ws := r.capWaiters[key]
	if len(ws) == 0 {
		return
	}
	active := 0
	for _, b := range r.busy[key] {
		if b.start <= r.now && r.now < b.end {
			active++
		}
	}
	for _, w := range ws {
		if active >= n {
			break
		}
		if !w.woken {
			w.woken = true
			r.wakeAt(w.t, r.now, 0)
			active++
		}
	}
}

// freeAt is the earliest time at or after t when fewer than n recorded
// calls are busy on the instance: math.MaxInt64 when that depends on a call
// still in progress.
func (r *run) freeAt(key string, n int, t int64) int64 {
	busy := r.busy[key]
	cands := []int64{t}
	for _, b := range busy {
		if b.end > t {
			cands = append(cands, b.end)
		}
	}
	best := int64(math.MaxInt64)
	for _, c := range cands {
		if c >= best {
			continue
		}
		active := 0
		for _, b := range busy {
			if b.start <= c && c < b.end {
				active++
			}
		}
		if active < n {
			best = c
		}
	}
	return best
}

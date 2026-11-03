package sim

import (
	"container/heap"
	"errors"
	"fmt"
	"math"
	"sort"
)

// The engine is a cooperative scheduler over virtual time (§13.1 item 14).
// Every top-level unit of work is a task: the flow entry, each scenario
// step (and the driver that starts them), the delivery lane that runs a
// root's emits and timers, each parallel branch, and the callee of a call
// bound to a cancellation token. Each task runs on its own goroutine, but
// only one runs at a time: a task holds the baton until it yields, by
// advancing its clock (a callee's latency, a wait, a capacity queue, a
// timeout, a retry backoff) or by waiting for another task. The scheduler
// then resumes the task with the earliest resume time; ties go by phase
// (a parallel join is evaluated after every other task due at the same
// time), then by creation order, then by seq. r.now is the clock of the
// running task.

type taskKind int

const (
	kindRoot   taskKind = iota // the flow entry, a scenario step or the step driver
	kindLane                   // the deliveries of one root's emits and timers
	kindBranch                 // a parallel branch
	kindChild                  // the callee of a token-bound or streaming call
	kindKill                   // a kill fault, due at its at_ms (§13.1 item 18)
)

// phaseJoin orders a parallel step's join evaluation after the other tasks
// due at the same time, so that it sees every branch that ends then.
const phaseJoin = 1

type task struct {
	id     int
	kind   taskKind
	parent *task // the task that spawned a branch or a child
	wake   chan struct{}
	lane   *lane
	branch *int           // the parallel branch index its events carry
	held   map[string]int // capacity slots it holds, by state key
	choice choiceSet      // a scenario step's choices, for it and its lane
	// home is the component instance the task works for, which a restart
	// of that instance cancels: the target of a root or delivery, the
	// frame of a parallel, the callee of a child.
	homeComp, homeInst string

	detached  bool  // its waiter gave up (a canceled call): what it records from now on is late
	lateAfter int64 // a branch still running when its join completed: events after this are late
	killed    bool  // canceled by a restart, a kill or the end of the run: it unwinds
	done      bool
	onDone    []func()

	// §13.1 item 18. calls are the calls in progress in the task, outermost
	// first; unwind is the outermost one into a killed instance, which the
	// task unwinds to (its caller gets peer-killed). death is "killed" when
	// a kill stopped the task. idle marks a task parked on a receive with
	// no time limit: an idle consumer, which the end of a root's work does
	// not wait for.
	calls  []*activeCall
	via    []*activeCall // a branch's: the calls its parallel step runs within
	unwind *activeCall
	death  string
	idle   bool
	// hung marks a task held by a hang with forever: true (§13.1 item 35).
	hung bool
	// blocked marks a task parked on a channel, a wait, a child or a join
	// (§17 item 3, waits.go): while every task of a root's call tree is
	// blocked, the root's emits and timers are delivered on time.
	blocked bool

	// stepLane and stepIdx are a scenario step's lane and index, on the
	// step's own task (§17 item 11): exploration never resumes it ahead of
	// an earlier step of the same lane due at the same time.
	stepLane string
	stepIdx  int

	// The scheduler's bookkeeping.
	at, seq int64
	phase   int
	hidx    int // index in the heap, -1 when not queued
	parked  int64
}

// errKilled unwinds a killed task. It never reaches the summary.
var errKilled = errors.New("task killed")

// errUnwind unwinds a task to its outermost call into a killed instance
// (§13.1 item 18), where invoke turns it into a peer-killed result.
var errUnwind = errors.New("call into a killed instance")

// stopErr is the error a task that resumes must unwind with, if any.
func (t *task) stopErr() error {
	switch {
	case t.killed:
		return errKilled
	case t.unwind != nil:
		return errUnwind
	}
	return nil
}

type taskHeap []*task

func (h taskHeap) Len() int { return len(h) }
func (h taskHeap) Less(i, j int) bool {
	a, b := h[i], h[j]
	if a.at != b.at {
		return a.at < b.at
	}
	if a.phase != b.phase {
		return a.phase < b.phase
	}
	if a.id != b.id {
		return a.id < b.id
	}
	return a.seq < b.seq
}
func (h taskHeap) Swap(i, j int) {
	h[i], h[j] = h[j], h[i]
	h[i].hidx, h[j].hidx = i, j
}
func (h *taskHeap) Push(x any) {
	t := x.(*task)
	t.hidx = len(*h)
	*h = append(*h, t)
}
func (h *taskHeap) Pop() any {
	old := *h
	t := old[len(old)-1]
	old[len(old)-1] = nil
	*h = old[:len(old)-1]
	t.hidx = -1
	return t
}

// sched is the scheduler state of a run.
type sched struct {
	ready   taskHeap
	cur     *task
	idle    chan struct{} // signaled when no task can run
	ids     int
	seqs    int64
	live    map[int]*task
	stopped bool
	failure error // the first error that ended the run
	limit   int64 // max virtual ms
	hitLim  bool
	end     int64     // the latest final clock of a finished task
	quiet   *task     // a task waiting until it is the only one left
	xp      *Schedule // schedule exploration (§15.5, schedpoints.go); nil by default
}

// spawn creates a task that runs fn from time at. The task inherits its
// parent's lane, branch and choices.
func (r *run) spawn(kind taskKind, at int64, parent *task, fn func(t *task) error) *task {
	r.s.ids++
	t := &task{id: r.s.ids, kind: kind, parent: parent, wake: make(chan struct{}, 1), hidx: -1, lateAfter: math.MaxInt64}
	if parent != nil {
		t.lane, t.branch, t.choice, t.homeComp, t.homeInst = parent.lane, parent.branch, parent.choice, parent.homeComp, parent.homeInst
		if kind == kindBranch {
			t.via = append(append([]*activeCall{}, parent.via...), parent.calls...)
		}
	}
	r.s.live[t.id] = t
	r.push(t, at, 0)
	go func() {
		<-t.wake
		var err error
		if !t.killed {
			err = fn(t)
		}
		if err != nil && !errors.Is(err, errKilled) && !errors.Is(err, errUnwind) {
			r.fail(err)
		}
		r.finish(t)
	}()
	return t
}

func (r *run) push(t *task, at int64, phase int) {
	r.s.seqs++
	t.at, t.seq, t.phase = at, r.s.seqs, phase
	heap.Push(&r.s.ready, t)
}

// wakeAt makes a waiting task runnable at time at (no later than any
// resume time it already has).
func (r *run) wakeAt(t *task, at int64, phase int) {
	if t.done {
		return
	}
	if t.hidx >= 0 {
		if at < t.at || (at == t.at && phase < t.phase) {
			t.at, t.phase = at, phase
			heap.Fix(&r.s.ready, t.hidx)
		}
		return
	}
	r.push(t, at, phase)
}

// fail records the error that ends the run and stops the scheduler.
func (r *run) fail(err error) {
	if r.s.failure == nil {
		r.s.failure = err
	}
	r.s.stopped = true
}

// finish ends the running task and hands the baton on.
func (r *run) finish(t *task) {
	t.done = true
	// The run's duration is where its roots and lanes end, as before tasks:
	// branches that outlive their join and canceled callees don't extend it.
	if (t.kind == kindRoot || t.kind == kindLane) && (!r.s.stopped || !t.killed) {
		r.s.end = max(r.s.end, r.now)
	}
	delete(r.s.live, t.id)
	for _, f := range t.onDone {
		f()
	}
	r.checkQuiet()
	r.dispatch()
}

// dispatch resumes the next task, or tells the run loop that none can run.
func (r *run) dispatch() {
	if r.s.xp != nil {
		r.xpEnd()
	}
	if r.s.stopped || r.s.ready.Len() == 0 {
		r.s.cur = nil
		r.s.idle <- struct{}{}
		return
	}
	next := r.s.ready[0]
	if next.at > r.s.limit && !next.killed {
		r.s.hitLim = true
		r.s.stopped = true
		r.s.cur = nil
		r.s.idle <- struct{}{}
		return
	}
	if r.s.xp != nil {
		next = r.xpPick(next) // same-time ties are a choice point (§15.5)
	} else {
		heap.Pop(&r.s.ready)
	}
	r.s.cur = next
	r.now = next.at
	if r.s.xp != nil {
		r.xpBegin(next)
	}
	next.wake <- struct{}{}
}

// yield queues the running task at time at and runs the scheduler; it
// returns when the task resumes.
func (r *run) yield(at int64, phase int) error {
	t := r.s.cur
	if t == nil {
		r.now = at
		return nil
	}
	if err := t.stopErr(); err != nil {
		return err
	}
	if phase == 0 && at <= r.s.limit && (r.s.ready.Len() == 0 || !r.before(r.s.ready[0], at, t.id)) && (r.s.xp == nil || !r.xpTie(at)) {
		r.now = at // nothing else is due first: keep running
		return nil
	}
	r.push(t, at, phase)
	r.dispatch()
	<-t.wake
	return t.stopErr()
}

// before reports whether queued task q runs before a phase-0 task id at at.
func (r *run) before(q *task, at int64, id int) bool {
	if q.at != at {
		return q.at < at
	}
	if q.phase != 0 {
		return false
	}
	return q.id < id
}

// sleep advances the running task's clock by ms, letting tasks due earlier
// run first.
func (r *run) sleep(ms int64) error {
	if ms <= 0 {
		if r.s.cur != nil {
			return r.s.cur.stopErr()
		}
		return nil
	}
	return r.yield(r.now+ms, 0)
}

// sleepUntil advances the running task's clock to t (never backwards).
func (r *run) sleepUntil(t int64) error {
	return r.sleep(t - r.now)
}

// park suspends the running task until wakeAt resumes it, or until time
// at (noDeadline for no time limit).
func (r *run) park(at int64, phase int) error {
	t := r.s.cur
	if err := t.stopErr(); err != nil {
		return err
	}
	t.parked = r.now
	if t.blocked {
		r.treeBlocking(t) // §17 item 3, waits.go
	}
	if at != noDeadline {
		r.push(t, at, phase)
	}
	r.dispatch()
	<-t.wake
	return t.stopErr()
}

// waitQuiet parks the running task until every other task has finished
// or is an idle consumer.
func (r *run) waitQuiet() error {
	if r.quietFor(r.s.cur) {
		return nil
	}
	r.s.quiet = r.s.cur
	return r.park(noDeadline, 0)
}

// quietFor reports whether every live task other than q is idle.
func (r *run) quietFor(q *task) bool {
	for _, t := range r.s.live {
		if t != q && !t.idle {
			return false
		}
	}
	return true
}

// checkQuiet resumes the task waiting for quiet once it is due.
func (r *run) checkQuiet() {
	if q := r.s.quiet; q != nil && r.s.live[q.id] == q && r.quietFor(q) {
		r.s.quiet = nil
		r.wakeAt(q, max(r.s.end, q.parked), 0)
	}
}

// parkIdle parks the running task as an idle consumer (§13.1 item 18):
// a root or lane counts its work as ended here, and a task waiting for
// quiet need not wait for it.
func (r *run) parkIdle() error {
	t := r.s.cur
	if err := t.stopErr(); err != nil {
		return err
	}
	if t.kind == kindRoot || t.kind == kindLane {
		r.s.end = max(r.s.end, r.now)
	}
	t.idle = true
	r.checkQuiet()
	err := r.park(noDeadline, 0)
	t.idle = false
	return err
}

// kill cancels a task: it resumes now and unwinds.
func (r *run) kill(t *task) {
	if t.done || t.killed {
		return
	}
	t.killed = true
	r.wakeAt(t, r.now, 0)
}

// loop runs the tasks until none can run, then ends the ones left: after
// an abort, at max_virtual_ms, or (a bug) tasks waiting on nothing.
func (r *run) loop() {
	r.dispatch()
	<-r.s.idle
	if r.s.hitLim {
		r.warn(fmt.Sprintf("the run stopped at max_virtual_ms %s with work still pending", fmtMS(r.s.limit)))
		r.s.end = max(r.s.end, r.s.limit)
	} else if r.s.failure == nil {
		// Idle consumers (a receive with no time limit) may wait forever.
		n := 0
		for _, t := range r.s.live {
			if !t.idle {
				n++
			}
		}
		if n > 0 {
			r.warn(fmt.Sprintf("%d tasks were still waiting when the run ended", n))
		}
	}
	r.s.stopped = true
	for len(r.s.live) > 0 {
		ids := make([]int, 0, len(r.s.live))
		for id := range r.s.live {
			ids = append(ids, id)
		}
		sort.Ints(ids)
		t := r.s.live[ids[0]]
		t.killed = true
		if t.hidx >= 0 {
			heap.Remove(&r.s.ready, t.hidx)
		}
		r.s.cur = t
		r.now = max(t.at, t.parked)
		t.wake <- struct{}{}
		<-r.s.idle
	}
	r.s.cur = nil
}

// lateNow reports whether an event the running task records at time t is
// late: its task, or an ancestor, was given up on or outlived its join.
func (r *run) lateNow(t int64) bool {
	for k := r.s.cur; k != nil; k = k.parent {
		if k.detached || t > k.lateAfter {
			return true
		}
	}
	return false
}

// heldBy reports whether the running task (or the task it works for)
// holds a capacity slot on key, so that a nested call runs in it.
func (r *run) heldBy(key string) bool {
	for k := r.s.cur; k != nil; k = k.parent {
		if k.held[key] > 0 {
			return true
		}
	}
	return false
}

// curChoices are the choices of the running task's scenario step, or the
// run's.
func (r *run) curChoices() choiceSet {
	for k := r.s.cur; k != nil; k = k.parent {
		if k.choice != nil {
			return k.choice
		}
	}
	return r.choices
}

// curBranch is the parallel branch index of the running task.
func (r *run) curBranch() *int {
	if r.s.cur == nil {
		return nil
	}
	return r.s.cur.branch
}

package sim

import (
	"container/heap"
	"fmt"
	"iter"
	"math"
	"sort"
	"strings"
)

// Schedule exploration (DESIGN §15.5). A run given a Schedule (Request.
// Schedule) asks it at each of the simulator's choice points:
//
//   - tie: which of the tasks due at the same time, in the same phase,
//     resumes first (the scheduler's tie-break, §13.1 item 14); scenario
//     steps of one lane keep their program order (§17 item 11);
//   - delivery: which of a lane's deliveries due at the same time goes
//     first (plain emits, timers due together);
//   - branch: which parallel branch runs next, in runs whose branches run
//     one after another (sequential runs; unstaggered branches only);
//   - join: the order a fan-out join counts branches that end at the same
//     time, as a rotation of the branch indexes;
//   - jitter: an offset of a scenario step's at_ms, bounded by JitterMS.
//
// Choice 0 is always the default: a run whose decisions are all 0 records
// the same results as a run with no schedule. A run with no schedule never
// reaches this file's code past a nil check.
//
// The run also records, for partial-order reduction, a footprint of each
// stretch of work it does without yielding (a unit): the components its
// events happen in (written) or that it runs inside (read), the tokens, channels and other keys
// its events name, and whether it writes ctx. Alternatives reports which
// alternatives of a point can lead to a different result.

// Choice point kinds.
const (
	PointTie      = "tie"
	PointDelivery = "delivery"
	PointBranch   = "branch"
	PointJoin     = "join"
	PointJitter   = "jitter"
)

// Schedule drives the choice points of one run and records them.
type Schedule struct {
	// Decisions are the choices at each point, in the order the run
	// reaches them; points past the end take the default, 0.
	Decisions []int
	// JitterMS bounds the at_ms jitter of scenario steps; 0 offers none.
	// It may be fractional: offsets are in µs (§17 item 4).
	JitterMS float64

	// Points are filled in by the run.
	Points []Point
	// Diverged describes the first decision that didn't fit its point (a
	// replay against a changed model); the default was taken instead.
	Diverged string

	units    []unit
	open     *unit
	actors   map[int]string // a task's actor while it delivers or runs a branch
	stateful map[string]int
	nextID   int
}

// Point is one choice point of a run.
type Point struct {
	Kind   string `json:"kind"`
	N      int    `json:"n"`
	Choice int    `json:"choice"`
	AtMS   int64  `json:"at_ms"`
	// AtUS is the exact clock of the point (§17 item 4): points less than
	// a millisecond apart are told apart.
	AtUS  int64  `json:"at_us"`
	Label string `json:"label,omitempty"`

	cands  []string   // the actor of each alternative (tie, delivery, branch)
	tasks  []int      // tie points: the task of each alternative
	unitAt int        // the first unit recorded after the choice
	ord    *joinOrder // join points: whether the join saw a tie
}

// unit is a stretch of one task's work between two yields.
type unit struct {
	task   int
	actor  string
	ev0    int
	reads  map[string]bool
	writes map[string]bool
}

// joinOrder ranks branches that end at the same time for a join: pos[i]
// is branch i's rank. tied records that the rank decided something.
type joinOrder struct {
	pos  []int
	tied bool
}

// start resets the schedule for a new run.
func (s *Schedule) start(*run) *Schedule {
	if s == nil {
		return nil
	}
	s.Points, s.Diverged, s.units, s.open, s.actors, s.stateful, s.nextID = nil, "", nil, nil, map[int]string{}, map[string]int{}, 0
	return s
}

// choose records a point and returns its choice.
func (r *run) choose(p Point) int {
	s := r.s.xp
	i := len(s.Points)
	if i < len(s.Decisions) {
		c := s.Decisions[i]
		if c >= 0 && c < p.N {
			p.Choice = c
		} else if s.Diverged == "" {
			s.Diverged = fmt.Sprintf("decision %d is %d, but point %d (%s at %s ms) has %d alternatives", i, c, i, p.Kind, fmtMS(r.now), p.N)
		}
	}
	p.AtMS, p.AtUS = msFloor(r.now), r.now
	s.Points = append(s.Points, p)
	return p.Choice
}

func (s *Schedule) actorOf(t *task) string {
	if a, ok := s.actors[t.id]; ok {
		return a
	}
	return fmt.Sprintf("t%d", t.id)
}

// xpBegin opens a unit for the task that resumes.
func (r *run) xpBegin(t *task) {
	s := r.s.xp
	u := &unit{task: t.id, actor: s.actorOf(t), ev0: len(r.events), reads: map[string]bool{}, writes: map[string]bool{}}
	stackReads(u, t)
	s.open = u
}

// xpEnd closes the running unit, if any, and records its footprint.
func (r *run) xpEnd() {
	s := r.s.xp
	u := s.open
	if u == nil {
		return
	}
	s.open = nil
	if t := r.s.cur; t != nil && t.id == u.task {
		stackReads(u, t)
	}
	for _, e := range r.events[min(u.ev0, len(r.events)):] {
		if (e.Type == "set" && e.Scope == "vars") || strings.HasPrefix(e.Type, "step.") {
			continue // local variables; a step's own bookkeeping
		}
		if e.Type == "set" && e.Scope == "ctx" {
			seg := strings.SplitN(strings.TrimPrefix(e.Path, "ctx."), ".", 2)[0]
			u.writes["x:"+seg] = true
		}
		if e.Component != "" {
			switch r.xpStateful(e.Component) {
			case xpWhole:
				u.writes["c:"+e.Component] = true
			case xpKeyed: // §16.2: store rows, tracked per key (schedreads.go)
				u.reads["c:"+e.Component] = true
				if e.Type == "set" && e.Scope == "state" {
					u.writes[xpStateWrite(e)] = true
					continue
				}
			default:
				u.reads["c:"+e.Component] = true
			}
		}
		if e.Key != "" {
			if xpReadOnly[e.Type] {
				u.reads["k:"+e.Key] = true
			} else {
				u.writes["k:"+e.Key] = true
			}
		}
	}
	if len(u.reads) > 0 || len(u.writes) > 0 {
		u.reads["x:*"] = true // any behavior may read ctx
	}
	s.units = append(s.units, *u)
}

// xpStateful reports whether work in a component can change something
// another task sees: xpWhole when it has state, capacity or limits, or the
// run injects faults (whose matching can count calls); xpKeyed when its
// only state is store tables that nothing but the store operations
// touches, so the reduction tracks their rows (schedreads.go); xpNone
// otherwise.
func (r *run) xpStateful(comp string) int {
	s := r.s.xp
	if v, ok := s.stateful[comp]; ok {
		return v
	}
	v := xpNone
	stores := false
	for _, id := range r.x.ByComp[comp] {
		if f := r.x.Interfaces[id]; f != nil {
			if len(f.Limits) > 0 {
				v = xpWhole
			}
			stores = stores || f.Store != nil
		}
	}
	if c := r.x.Components[comp]; c == nil || c.State != nil || c.Capacity != nil || len(r.faults) > 0 {
		v = xpWhole
	}
	if v == xpNone && stores {
		v = r.xpKeyedOnly(comp)
	}
	s.stateful[comp] = v
	return v
}

// stackReads adds the components the task runs inside to a unit's reads.
func stackReads(u *unit, t *task) {
	for _, ac := range t.via {
		u.reads["c:"+ac.comp] = true
	}
	for _, ac := range t.calls {
		if ac != nil {
			u.reads["c:"+ac.comp] = true
		}
	}
	if t.homeComp != "" {
		u.reads["c:"+t.homeComp] = true
	}
}

// xpCut ends the running unit and labels the running task's next units
// with actor ("" for the task itself).
func (r *run) xpCut(actor string) {
	s := r.s.xp
	r.xpEnd()
	t := r.s.cur
	if t == nil {
		return
	}
	if actor == "" {
		delete(s.actors, t.id)
	} else {
		s.actors[t.id] = actor
	}
	r.xpBegin(t)
}

// xpTie reports whether a queued task is due at at in phase 0, so that a
// task yielding to at must let the schedule choose.
func (r *run) xpTie(at int64) bool {
	for _, q := range r.s.ready {
		if q.at == at && q.phase == 0 {
			return true
		}
	}
	return false
}

// xpPick chooses the task to resume among those due with next (the
// heap's minimum) and removes it from the heap.
func (r *run) xpPick(next *task) *task {
	var cands []*task
	for _, q := range r.s.ready {
		if q.at == next.at && q.phase == next.phase {
			cands = append(cands, q)
		}
	}
	cands = laneOrder(cands)
	if len(cands) > 1 {
		sort.Slice(cands, func(a, b int) bool {
			if cands[a].id != cands[b].id {
				return cands[a].id < cands[b].id
			}
			return cands[a].seq < cands[b].seq
		})
		s := r.s.xp
		p := Point{Kind: PointTie, N: len(cands), unitAt: len(s.units)}
		labels := make([]string, len(cands))
		for i, c := range cands {
			p.cands = append(p.cands, s.actorOf(c))
			p.tasks = append(p.tasks, c.id)
			labels[i] = p.cands[i]
		}
		p.Label = strings.Join(labels, ",")
		saved := r.now
		r.now = next.at
		next = cands[r.choose(p)]
		r.now = saved
	}
	heap.Remove(&r.s.ready, next.hidx)
	return next
}

// laneOrder drops from a tie the steps that a due step of the same lane
// precedes in program order (§17 item 11): a lane is one host thread
// issuing its steps in sequence, so only its earliest due step can go
// next. Earlier steps were spawned first, so the default choice (the
// lowest task id) is never dropped.
func laneOrder(cands []*task) []*task {
	first := map[string]int{}
	for _, c := range cands {
		if c.stepLane == "" {
			continue
		}
		if i, ok := first[c.stepLane]; !ok || c.stepIdx < i {
			first[c.stepLane] = c.stepIdx
		}
	}
	if len(first) == 0 {
		return cands
	}
	out := cands[:0:0]
	for _, c := range cands {
		if c.stepLane == "" || c.stepIdx == first[c.stepLane] {
			out = append(out, c)
		}
	}
	return out
}

// xpDelivery chooses among a lane's deliveries due with the one at bi,
// labels the lane task's work with the chosen delivery, and returns its
// index.
func (r *run) xpDelivery(ln *lane, bi int) int {
	t := ln.queue[bi]
	var idx []int
	for i, q := range ln.queue {
		if q.due == t.due && (q.late != nil || q.due <= r.now) {
			idx = append(idx, i)
		}
	}
	label := func(q *timer) string { return fmt.Sprintf("d%p/%d/%d", ln, q.seq, q.due) }
	if len(idx) > 1 {
		sort.Slice(idx, func(a, b int) bool { return ln.queue[idx[a]].seq < ln.queue[idx[b]].seq })
		s := r.s.xp
		r.xpEnd()
		p := Point{Kind: PointDelivery, N: len(idx), unitAt: len(s.units)}
		var names []string
		for _, i := range idx {
			p.cands = append(p.cands, label(ln.queue[i]))
			names = append(names, ln.queue[i].target)
		}
		p.Label = strings.Join(names, ",")
		bi = idx[r.choose(p)]
		// Reopen the lane's unit; xpCut below relabels it.
		if r.s.cur != nil {
			r.xpBegin(r.s.cur)
		}
	}
	r.xpCut(label(ln.queue[bi]))
	return bi
}

// branchOrder yields the order in which a sequential run's parallel step
// runs its n branches: index order without a schedule; with one, each
// next branch is a choice among the remaining ones (unless the branches
// are staggered), and each branch's work is labeled for the reduction.
func (r *run) branchOrder(n int, staggered bool) iter.Seq[int] {
	return func(yield func(int) bool) {
		s := r.s.xp
		if s == nil {
			for i := 0; i < n; i++ {
				if !yield(i) {
					return
				}
			}
			return
		}
		s.nextID++
		group := s.nextID
		label := func(i int) string { return fmt.Sprintf("b%d/%d", group, i) }
		left := make([]int, n)
		for i := range left {
			left[i] = i
		}
		for len(left) > 0 {
			k := 0
			if len(left) > 1 && !staggered {
				r.xpEnd()
				p := Point{Kind: PointBranch, N: len(left), unitAt: len(s.units)}
				for _, i := range left {
					p.cands = append(p.cands, label(i))
				}
				p.Label = fmt.Sprintf("%d of %d branches left", len(left), n)
				k = r.choose(p)
				if r.s.cur != nil {
					r.xpBegin(r.s.cur)
				}
			}
			i := left[k]
			left = append(left[:k], left[k+1:]...)
			r.xpCut(label(i))
			if !yield(i) {
				return
			}
		}
		r.xpCut("")
	}
}

// joinRank returns the tie order of a parallel step's join over n
// branches: nil (index order) without a schedule.
func (r *run) joinRank(n int) *joinOrder {
	s := r.s.xp
	if s == nil || n < 2 {
		return nil
	}
	o := &joinOrder{pos: make([]int, n)}
	rot := r.choose(Point{Kind: PointJoin, N: n, ord: o, Label: fmt.Sprintf("rotation of %d branches", n)})
	for i := range o.pos {
		o.pos[i] = (i - rot + n) % n
	}
	return o
}

// less orders two finished branches that end at the same time.
func (o *joinOrder) less(a, b int) bool {
	if o == nil {
		return a < b
	}
	o.tied = true
	return o.pos[a] < o.pos[b]
}

// xpJitter returns a scenario step's start time: at itself without a
// schedule, else at plus a chosen offset within ±JitterMS.
func (r *run) xpJitter(at int64) int64 {
	s := r.s.xp
	if s == nil || s.JitterMS <= 0 {
		return at
	}
	m := int64(math.Round(s.JitterMS * 1000)) // in µs: fractional jitter is honored (§17 item 4)
	alts := []int64{at}
	seen := map[int64]bool{at: true}
	for _, d := range []int64{-m, m, -m / 2, m / 2} {
		v := max(at+d, 0)
		if d != 0 && !seen[v] {
			seen[v] = true
			alts = append(alts, v)
		}
	}
	if len(alts) == 1 {
		return at
	}
	labels := make([]string, len(alts))
	for i, v := range alts {
		labels[i] = fmtMS(v)
	}
	v := alts[r.choose(Point{Kind: PointJitter, N: len(alts), Label: "at_ms " + strings.Join(labels, ",")})]
	if v%1000 != 0 {
		r.fine = true // the clock leaves whole milliseconds (§13.1 item 16)
	}
	return v
}

// Alternatives returns the alternatives of point i, other than the one
// taken, that can lead to a different result. Partial-order reduction
// skips the others: a task, delivery or branch whose next unit touches
// nothing that the work run before it (since the point) touched would
// commute with that work. Joins matter only when branches tied; jitter
// always matters. The check is conservative: it compares components, keys
// and ctx, not paths, and ignores only the trace's order.
func (s *Schedule) Alternatives(i int) []int {
	p := s.Points[i]
	var out []int
	for k := 0; k < p.N; k++ {
		if k == p.Choice {
			continue
		}
		switch p.Kind {
		case PointJitter:
			out = append(out, k)
		case PointJoin:
			if p.ord != nil && p.ord.tied {
				out = append(out, k)
			}
		default:
			if s.dependent(p, k) {
				out = append(out, k)
			}
		}
	}
	return out
}

// dependent reports whether running alternative k first could change
// the run: its next unit conflicts with a unit run before it.
func (s *Schedule) dependent(p Point, k int) bool {
	if k >= len(p.cands) {
		return true
	}
	j := -1
	for x := p.unitAt; x < len(s.units); x++ {
		if s.units[x].actor == p.cands[k] || (k < len(p.tasks) && s.units[x].task == p.tasks[k]) {
			j = x
			break
		}
	}
	if j < 0 {
		return true // it never ran: assume it matters
	}
	// A tie moves a task's whole stretch up to its next yield: the units it
	// runs back to back, whatever they're labeled (a delivery lane relabels
	// its work with the delivery it runs).
	end := j + 1
	if k < len(p.tasks) {
		for end < len(s.units) && s.units[end].task == p.tasks[k] {
			end++
		}
	}
	for _, me := range s.units[j:end] {
		for x := p.unitAt; x < j; x++ {
			if conflict(me, s.units[x]) {
				return true
			}
		}
	}
	return false
}

func conflict(a, b unit) bool {
	hit := func(w, other map[string]bool) bool {
		for k := range w {
			if other[k] {
				return true
			}
			if strings.HasPrefix(k, "x:") && other["x:*"] {
				return true
			}
			if strings.HasPrefix(k, "s:") && xpRowHit(k, other) {
				return true
			}
		}
		return false
	}
	return hit(a.writes, b.writes) || hit(a.writes, b.reads) || hit(b.writes, a.reads)
}

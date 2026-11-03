package sim

import (
	"fmt"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Branch states: pending (not yet due, or due and not yet started),
// running, finished, or skipped (a staggered branch the join no longer
// needed).
const (
	branchPending = iota
	branchRunning
	branchFinished
	branchSkipped
)

// branchResult is the outcome of one branch of a parallel step.
type branchResult struct {
	state int
	ok    bool
	value any
	err   *Error
	start int64
	end   int64
}

func (b branchResult) started() bool { return b.state == branchRunning || b.state == branchFinished }

// branch is one branch of a parallel step: its item and key (the index, or
// the map key), its steps and their path.
type branch struct {
	item, key any
	steps     []model.Step
	path      string
}

// joinOutcome is the state of a join at some time.
type joinOutcome struct {
	done     bool
	met      bool
	timedOut bool
	at       int64 // when the join completed
	received int
	failed   int
}

// evalJoin walks the finished branches in time order (by end, then index)
// up to time upTo and reports whether the join completed: met when need
// branches succeeded, failed as soon as success became impossible, or timed
// out at limit. Entries past len(results) are pending. With dues nil, n
// counts every branch, unstarted ones included, since they can still
// succeed. With dues (join.count_unstarted: false, §13.1 item 12), only
// the successes plus the branches running at time t can still meet the
// join: a branch counts once it is due (dues[k] <= t) unless it was skipped
// or has been counted as finished.
func evalJoin(results []branchResult, n, need int, start, upTo, limit int64, dues []int64, ord *joinOrder) joinOutcome {
	if need <= 0 {
		return joinOutcome{done: true, met: true, at: start}
	}
	if n < need {
		return joinOutcome{done: true, at: start}
	}
	if limit <= start {
		return joinOutcome{done: true, timedOut: true, at: start}
	}
	idx := []int{}
	for i, b := range results {
		if b.state == branchFinished {
			idx = append(idx, i)
		}
	}
	sort.SliceStable(idx, func(a, b int) bool {
		if ea, eb := results[idx[a]].end, results[idx[b]].end; ea != eb {
			return ea < eb
		}
		return ord != nil && ord.less(idx[a], idx[b]) // a schedule's tie order (§15.5)
	})
	var out joinOutcome
	counted := make([]bool, n)
	impossible := func(t int64) bool {
		if dues == nil {
			return n-out.failed < need
		}
		running := 0
		for k := 0; k < n; k++ {
			if dues[k] > t || counted[k] || (k < len(results) && results[k].state == branchSkipped) {
				continue
			}
			running++
		}
		return out.received+running < need
	}
	if dues != nil && start <= upTo && impossible(start) {
		out.done, out.at = true, start
		return out
	}
	for _, i := range idx {
		b := results[i]
		if b.end > upTo {
			break
		}
		if b.end > limit {
			break
		}
		if !b.ok && b.end >= limit {
			// A branch that fails at the join's limit failed because of it
			// (its calls inherit the deadline): the join times out rather
			// than reporting insufficient. Insufficient is only for failures
			// that make success impossible before the limit.
			continue
		}
		counted[i] = true
		if b.ok {
			out.received++
		} else {
			out.failed++
		}
		switch {
		case out.received >= need:
			out.done, out.met, out.at = true, true, b.end
			return out
		case impossible(b.end):
			out.done, out.at = true, b.end
			return out
		}
	}
	if limit != noDeadline && limit <= upTo {
		out.done, out.timedOut, out.at = true, true, limit
	}
	return out
}

// parallel runs a §11.2 parallel step: each branch is a task, started at
// its due time, concurrent with the others in virtual time and sharing
// state with them; the step waits for its join. Branches still running
// when the join completes run on, and their events after the join time are
// marked late. A token-bound parallel fails with canceled at the cancel.
func (r *run) parallel(f *frame, s model.Step, depth int, p string) (*exit, error) {
	if !r.interleave {
		return r.parallelSequential(f, s, depth, p)
	}
	start := r.now
	var bs []branch
	if s.Branches != nil {
		for i, b := range s.Branches {
			bs = append(bs, branch{key: int64(i), steps: b, path: fmt.Sprintf("%s.branches[%d]", p, i)})
		}
	} else {
		items, keys, err := r.items(f, s.Parallel, "parallel", p)
		if err != nil {
			return nil, err
		}
		for i := range items {
			bs = append(bs, branch{item: items[i], key: keys[i], steps: s.Steps, path: p + ".steps"})
		}
	}
	if len(bs) > model.MaxForeachMax {
		r.warn(fmt.Sprintf("%s: parallel stopped after %d of %d branches", p, model.MaxForeachMax, len(bs)))
		bs = bs[:model.MaxForeachMax]
	}
	n := len(bs)
	need, err := r.need(f, s.Join, n, p)
	if err != nil {
		return nil, err
	}
	as, index := loopNames(s)
	dues, staggered, err := r.dues(f, s, bs, as, index, start, p)
	if err != nil {
		return nil, err
	}
	var failDues []int64 // set when unstarted branches do not count (§13.1 item 12)
	if !s.Join.Unstarted() {
		failDues = dues
	}
	timeout, err := r.intOf(f, s.TimeoutMS, p+".timeout_ms")
	if err != nil {
		return nil, err
	}
	tok, err := r.tokenOf(f, s.Token, p+".token")
	if err != nil {
		return nil, err
	}
	limit := f.deadline
	if timeout > 0 {
		limit = min(limit, start+timeout)
	}
	if err := r.ev(Event{Type: "parallel.start", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst,
		Output: map[string]any{"branches": int64(n), "need": int64(need)}}); err != nil {
		return nil, err
	}
	results := make([]branchResult, n)
	ord := r.joinRank(n) // nil without a schedule (§15.5)
	tasks := make([]*task, n)
	me := r.s.cur
	waiting := true // the step still waits for its join
	joined := false // the join has completed
	var jat int64
	var lateWorks []func(i int)
	endEv := 0 // the seq of the parallel.end event
	var tw *tokenWait
	if tok != "" {
		if r.isCanceled(tok) {
			tw = &tokenWait{canceled: true, done: true}
		} else {
			tw = r.await(tok, phaseJoin)
			defer r.unawait(tok, tw)
		}
	}
	spawn := func(i int) {
		b := bs[i]
		results[i] = branchResult{state: branchRunning, start: dues[i]}
		bi := i
		t := r.spawn(kindBranch, dues[i], me, func(t *task) error {
			bf := &frame{iface: f.iface, comp: f.comp, inst: f.inst, skey: f.skey, input: f.input, vars: deepCopy(f.vars).(map[string]any),
				span: f.span, lastErr: f.lastErr, deadline: f.deadline, stream: f.stream, cancel: f.cancel, plain: f.plain}
			if s.Branches == nil {
				bf.vars[as], bf.vars[index] = deepCopy(b.item), b.key
			}
			ex, err := r.steps(bf, b.steps, depth, b.path)
			if err != nil {
				return err
			}
			res := branchResult{state: branchFinished, ok: true, start: dues[bi], end: r.now}
			if ex != nil {
				res.value, res.err = ex.value, ex.err
				res.ok = ex.err == nil
			}
			results[bi] = res
			return nil
		})
		t.branch = &bi
		tasks[i] = t
		t.onDone = append(t.onDone, func() {
			if results[bi].state != branchFinished {
				// Killed by a restart, a kill (or the end of the run).
				e := &Error{Code: "canceled", Message: "the branch was canceled by a restart"}
				if t.death == "killed" {
					e = &Error{Code: "killed", Message: "the branch was stopped by a kill"}
				}
				results[bi] = branchResult{state: branchFinished, start: dues[bi], end: r.now, err: e}
			}
			if waiting {
				r.wakeAt(me, max(r.now, me.parked), phaseJoin)
				return
			}
			if !joined {
				return
			}
			if endEv > 0 {
				// The trace's parallel.end shows each late branch's outcome
				// once it is known (its end_ms, ok, value and error).
				out, _ := r.events[endEv-1].Output.(map[string]any)
				if list, ok := out["results"].([]any); ok && bi < len(list) {
					b := results[bi]
					var errv any
					if b.err != nil {
						errv = b.err.Map()
					}
					if m, ok := list[bi].(map[string]any); ok {
						m["ok"], m["value"], m["error"], m["end_ms"] = b.ok, deepCopy(b.value), errv, msFloor(b.end)
						if r.fine {
							m["end_us"] = b.end
						}
					}
				}
			}
			if s.OnLate != nil && results[bi].end > jat {
				for _, lw := range lateWorks {
					lw(bi)
				}
			}
		})
	}
	defer func() { waiting = false }()
	next := 0
	var j joinOutcome
	canceled := false
	for {
		for next < n && dues[next] <= r.now {
			i := next
			next++
			// With staggering (hedging), a due branch starts only while the
			// join is unmet; without it, every branch starts. A fail-fast
			// join that failed at the branch's due time counted it as
			// running, so it starts.
			if staggered {
				if jj := evalJoin(results[:i], n, need, start, dues[i], limit, failDues, ord); jj.done &&
					(failDues == nil || jj.met || jj.timedOut || jj.at < dues[i]) {
					results[i].state = branchSkipped
					continue
				}
			}
			spawn(i)
		}
		j = evalJoin(results, n, need, start, r.now, limit, failDues, ord)
		if j.done {
			break
		}
		if tw != nil && tw.canceled {
			canceled = true
			break
		}
		running := false
		for _, b := range results {
			if b.state == branchRunning {
				running = true
			}
		}
		if !running && next >= n {
			// Every branch finished without meeting the join or making it
			// impossible; cannot happen, but fail rather than hang.
			j = joinOutcome{done: true, at: r.now, received: j.received, failed: j.failed}
			break
		}
		wake := int64(noDeadline)
		if next < n {
			wake = dues[next]
		}
		if limit != noDeadline {
			wake = min(wake, limit)
		}
		if err := r.parkBlocked(wake, phaseJoin); err != nil {
			// The step's task unwinds (a restart or a kill): the branches
			// run on, and nothing waits for them.
			for i, b := range results {
				if b.state == branchRunning {
					tasks[i].detached = true
				}
			}
			return nil, err
		}
	}
	waiting = false
	if canceled {
		j = joinOutcome{done: true, at: r.now, received: j.received, failed: j.failed}
	}
	joined, jat = true, j.at
	for i, b := range results {
		if b.state == branchRunning {
			if canceled {
				tasks[i].detached = true
			} else {
				tasks[i].lateAfter = j.at
			}
		}
	}
	list := make([]any, n)
	for i, b := range results {
		var errv, st, en any
		if b.err != nil {
			errv = b.err.Map()
		}
		var stUS, enUS any
		if b.started() {
			st, stUS = msFloor(b.start), b.start
		}
		if b.state == branchFinished {
			en, enUS = msFloor(b.end), b.end
		}
		m := map[string]any{"item": deepCopy(bs[i].item), "index": bs[i].key, "ok": b.ok, "value": b.value, "error": errv,
			"start_ms": st, "end_ms": en, "late": b.state == branchRunning || (b.state == branchFinished && b.end > j.at),
			"started": b.started()}
		if r.fine {
			m["start_us"], m["end_us"] = stUS, enUS
		}
		list[i] = m
	}
	val := map[string]any{"ok": j.met && !canceled, "received": int64(j.received), "required": int64(need), "failed": int64(j.failed),
		"duration_ms": msFloor(j.at - start), "duration_us": j.at - start, "results": list}
	jerr := joinError(s, j, need, p)
	if canceled {
		jerr = canceledError(tok)
	}
	r.now = j.at
	if s.AsResult != "" {
		f.vars[s.AsResult] = deepCopy(val)
	}
	if err := r.ev(Event{Type: "parallel.end", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst,
		Output: deepCopy(val), Error: jerr, DurationMS: j.at - start}); err != nil {
		return nil, err
	}
	endEv = len(r.events)
	if s.OnLate != nil {
		// on_late runs for each branch that finishes after the join, when
		// it finishes, as work delivered like a timer in this root's lane.
		vars := deepCopy(f.vars).(map[string]any)
		lane := me.lane
		lateWorks = append(lateWorks, func(i int) {
			b := results[i]
			var errv any
			if b.err != nil {
				errv = b.err.Map()
			}
			lv := deepCopy(vars).(map[string]any)
			lv[as], lv[index] = deepCopy(bs[i].item), bs[i].key
			lv["late"] = r.lateValue(b, errv)
			bf := &frame{iface: f.iface, comp: f.comp, inst: f.inst, skey: f.skey, input: f.input, vars: lv,
				span: f.span, deadline: noDeadline, stream: f.stream, cancel: f.cancel, plain: f.plain}
			cur := r.s.cur
			saved := cur.lane
			cur.lane = lane
			r.scheduleLate(b.end, &lateWork{frame: bf, steps: s.OnLate, depth: depth, path: p + ".on_late", branch: i})
			cur.lane = saved
		})
		for i, b := range results {
			if b.state == branchFinished && b.end > j.at {
				lateWorks[0](i)
			}
		}
	}
	if jerr != nil {
		f.lastErr = jerr.Map()
		return &exit{err: jerr}, nil
	}
	return nil, nil
}

// dues returns each branch's due time. A number staggers branch i to
// start + i*stagger_ms. A template is evaluated once per branch after the
// first, with vars.<as> and vars.<index> bound to that branch, and gives
// its delay after the previous branch, so a constant template keeps the
// i*stagger_ms spacing while a speculative branch can be the only one
// delayed (§13.1 item 12). staggered reports whether the hedging rule (a
// due branch starts only while the join is unmet) applies.
func (r *run) dues(f *frame, s model.Step, bs []branch, as, index string, start int64, p string) ([]int64, bool, error) {
	dues := make([]int64, len(bs))
	if !s.StaggerMS.IsExpr() {
		st := max(r.numUS(s.StaggerMS), 0)
		for i := range dues {
			dues[i] = start + int64(i)*st
		}
		return dues, st > 0, nil
	}
	at := start
	for i := range dues {
		if i > 0 {
			bf := *f
			bf.vars = deepCopy(f.vars).(map[string]any)
			bf.vars[as], bf.vars[index] = deepCopy(bs[i].item), bs[i].key
			d, err := r.intOf(&bf, s.StaggerMS, p+".stagger_ms")
			if err != nil {
				return nil, false, err
			}
			at += d
		}
		dues[i] = at
	}
	return dues, len(dues) > 0 && dues[len(dues)-1] > start, nil
}

// need evaluates a join rule: all (the default), any, a number or "=cel".
func (r *run) need(f *frame, j *model.JoinSpec, n int, p string) (int, error) {
	if j == nil {
		return n, nil
	}
	v := expr.Native(j.Need)
	if src, ok := expr.ExprOf(v); ok {
		var err error
		if v, err = expr.Behavior.Eval(src, r.act(f, 1)); err != nil {
			return 0, abortf("%s.join.need: %v", p, err)
		}
	}
	switch t := v.(type) {
	case nil:
		return n, nil
	case string:
		switch strings.TrimSpace(t) {
		case model.JoinAll:
			return n, nil
		case model.JoinAny:
			return 1, nil
		}
	default:
		if k, ok := toInt(v); ok {
			return int(max(k, 0)), nil
		}
	}
	return 0, abortf("%s.join.need: need is a number, %q or %q, got %v", p, model.JoinAll, model.JoinAny, v)
}

// parallelSequential is the parallel step of runs that use none of the
// §13.1 item 14 features: as before tasks, branches run one after another
// in list order, each on its own forked clock, inside the step's task, and
// each sees the state the earlier branches left. Events after the join
// completes are marked late.
func (r *run) parallelSequential(f *frame, s model.Step, depth int, p string) (*exit, error) {
	start := r.now
	var bs []branch
	if s.Branches != nil {
		for i, b := range s.Branches {
			bs = append(bs, branch{key: int64(i), steps: b, path: fmt.Sprintf("%s.branches[%d]", p, i)})
		}
	} else {
		items, keys, err := r.items(f, s.Parallel, "parallel", p)
		if err != nil {
			return nil, err
		}
		for i := range items {
			bs = append(bs, branch{item: items[i], key: keys[i], steps: s.Steps, path: p + ".steps"})
		}
	}
	if len(bs) > model.MaxForeachMax {
		r.warn(fmt.Sprintf("%s: parallel stopped after %d of %d branches", p, model.MaxForeachMax, len(bs)))
		bs = bs[:model.MaxForeachMax]
	}
	n := len(bs)
	need, err := r.need(f, s.Join, n, p)
	if err != nil {
		return nil, err
	}
	as, index := loopNames(s)
	dues, staggered, err := r.dues(f, s, bs, as, index, start, p)
	if err != nil {
		return nil, err
	}
	var failDues []int64
	if !s.Join.Unstarted() {
		failDues = dues
	}
	timeout, err := r.intOf(f, s.TimeoutMS, p+".timeout_ms")
	if err != nil {
		return nil, err
	}
	limit := f.deadline
	if timeout > 0 {
		limit = min(limit, start+timeout)
	}
	if err := r.ev(Event{Type: "parallel.start", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst,
		Output: map[string]any{"branches": int64(n), "need": int64(need)}}); err != nil {
		return nil, err
	}
	results := make([]branchResult, n)
	ord := r.joinRank(n) // nil without a schedule (§15.5)
	first := len(r.events)
	end := start
	cur := r.s.cur
	for i := range r.branchOrder(n, staggered) { // index order without a schedule (§15.5)
		b := bs[i]
		due := dues[i]
		if staggered {
			if j := evalJoin(results[:i], n, need, start, due, limit, failDues, ord); j.done &&
				(failDues == nil || j.met || j.timedOut || j.at < due) {
				results[i].state = branchSkipped
				continue
			}
		}
		r.now = due
		bf := &frame{iface: f.iface, comp: f.comp, inst: f.inst, skey: f.skey, input: f.input, vars: deepCopy(f.vars).(map[string]any),
			span: f.span, lastErr: f.lastErr, deadline: f.deadline, stream: f.stream, cancel: f.cancel, plain: f.plain}
		if s.Branches == nil {
			bf.vars[as], bf.vars[index] = deepCopy(b.item), b.key
		}
		prev, bi := cur.branch, i
		cur.branch = &bi
		ex, err := r.steps(bf, b.steps, depth, b.path)
		cur.branch = prev
		if err != nil {
			return nil, err
		}
		res := branchResult{state: branchFinished, ok: true, start: due, end: r.now}
		if ex != nil {
			res.value, res.err = ex.value, ex.err
			res.ok = ex.err == nil
		}
		results[i] = res
		end = max(end, r.now)
	}
	j := evalJoin(results, n, need, start, noDeadline, limit, failDues, ord)
	if !j.done {
		j = joinOutcome{done: true, at: end, received: j.received, failed: j.failed}
	}
	for k := first; k < len(r.events); k++ {
		if r.events[k].tUS > j.at {
			r.events[k].Late = true
		}
	}
	list := make([]any, n)
	for i, b := range results {
		var errv, st, en any
		if b.err != nil {
			errv = b.err.Map()
		}
		m := map[string]any{"item": deepCopy(bs[i].item), "index": bs[i].key, "ok": b.ok, "value": b.value, "error": errv,
			"start_ms": st, "end_ms": en, "late": b.started() && b.end > j.at, "started": b.started()}
		if b.started() {
			m["start_ms"], m["end_ms"] = msFloor(b.start), msFloor(b.end)
			if r.fine {
				m["start_us"], m["end_us"] = b.start, b.end
			}
		}
		list[i] = m
	}
	val := map[string]any{"ok": j.met, "received": int64(j.received), "required": int64(need), "failed": int64(j.failed),
		"duration_ms": msFloor(j.at - start), "duration_us": j.at - start, "results": list}
	jerr := joinError(s, j, need, p)
	r.now = j.at
	if s.AsResult != "" {
		f.vars[s.AsResult] = deepCopy(val)
	}
	if err := r.ev(Event{Type: "parallel.end", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst,
		Output: deepCopy(val), Error: jerr, DurationMS: j.at - start}); err != nil {
		return nil, err
	}
	if s.OnLate != nil {
		for i, b := range results {
			if !b.started() || b.end <= j.at {
				continue
			}
			var errv any
			if b.err != nil {
				errv = b.err.Map()
			}
			vars := deepCopy(f.vars).(map[string]any)
			vars[as], vars[index] = deepCopy(bs[i].item), bs[i].key
			vars["late"] = r.lateValue(b, errv)
			bf := &frame{iface: f.iface, comp: f.comp, inst: f.inst, skey: f.skey, input: f.input, vars: vars,
				span: f.span, deadline: noDeadline, stream: f.stream, cancel: f.cancel, plain: f.plain}
			r.scheduleLate(b.end, &lateWork{frame: bf, steps: s.OnLate, depth: depth, path: p + ".on_late", branch: i})
		}
	}
	if jerr != nil {
		f.lastErr = jerr.Map()
		return &exit{err: jerr}, nil
	}
	return nil, nil
}

// joinError is the error of a join that was not met.
func joinError(s model.Step, j joinOutcome, need int, p string) *Error {
	switch {
	case j.met:
		return nil
	case j.timedOut:
		return &Error{Code: "timeout", Retryable: true, Message: fmt.Sprintf("%s: %d of %d branches succeeded before the join timed out", p, j.received, need),
			Data: map[string]any{"received": int64(j.received), "required": int64(need)}}
	}
	e := &Error{Code: "insufficient", Retryable: true}
	if o := s.OnInsufficient; o != nil {
		e = &Error{Code: o.Code, Status: o.Status, Retryable: o.Retryable}
	}
	e.Message = fmt.Sprintf("%s: %d of %d branches succeeded and %d failed", p, j.received, need, j.failed)
	e.Data = map[string]any{"received": int64(j.received), "required": int64(need), "failed": int64(j.failed)}
	return e
}

// lateValue is vars.late for on_late work: a late branch's result.
func (r *run) lateValue(b branchResult, errv any) map[string]any {
	m := map[string]any{"ok": b.ok, "value": deepCopy(b.value), "error": errv, "start_ms": msFloor(b.start), "end_ms": msFloor(b.end)}
	if r.fine {
		m["start_us"], m["end_us"] = b.start, b.end
	}
	return m
}

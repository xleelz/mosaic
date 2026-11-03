package sim

import (
	"fmt"
	"math"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// A rendezvous (§13.1 item 17) meets tasks at a name: each arrival blocks
// until count tasks have arrived in the same generation, then all resume
// together at the last arrival plus the step's latency. Once a generation
// is full, the next arrival starts a new one.

type rendezvousGen struct {
	gen      int
	count    int
	arrivals []*arrival
	broken   int    // > 0 once a waiter timed out or was killed: the arrivals then, which all fail
	code     string // why it broke: timeout, or peer-killed (§13.1 item 18)
}

type arrival struct {
	t        *task
	value    any
	released bool
	at       int64 // the release time
	index    int
}

// rendezvous runs a rendezvous step in a behavior.
func (r *run) rendezvous(f *frame, s model.Step, depth int, p string) (*exit, error) {
	name, err := r.tokenOf(f, s.Rendezvous, p+".rendezvous")
	if err != nil {
		return nil, err
	}
	n, err := r.countOf(f, s.Count, p+".count")
	if err != nil {
		return nil, err
	}
	if n < 1 {
		return nil, abortf("%s.count: a rendezvous needs a count of at least 1, got %d", p, n)
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
	timeout, err := r.intOf(f, s.TimeoutMS, p+".timeout_ms")
	if err != nil {
		return nil, err
	}
	g := r.rdv[name]
	if g == nil || len(g.arrivals) == 0 {
		gen := 1
		if g != nil {
			gen = g.gen + 1
		}
		g = &rendezvousGen{gen: gen, count: int(n)}
		r.rdv[name] = g
	} else if int(n) != g.count {
		r.warn(fmt.Sprintf("%s: rendezvous %s expects %d arrivals; generation %d was opened for %d", p, name, n, g.gen, g.count))
	}
	me := &arrival{t: r.s.cur, value: deepCopy(value), index: len(g.arrivals)}
	g.arrivals = append(g.arrivals, me)
	gen := g.gen

	if len(g.arrivals) >= g.count {
		// The last arrival releases the generation; the next opens a new one.
		lat, err := r.stepLatency(f, s.LatencyMS, p)
		if err != nil {
			return nil, err
		}
		at := r.now + lat
		r.rdv[name] = &rendezvousGen{gen: g.gen}
		for _, a := range g.arrivals {
			a.released, a.at = true, at
			if a != me {
				r.wakeAt(a.t, at, 0)
			}
		}
		if err := r.sleepUntil(at); err != nil {
			return nil, err
		}
	} else {
		limit := f.deadline
		if timeout > 0 {
			limit = min(limit, r.now+timeout)
		}
		for !me.released && g.broken == 0 && r.now < limit {
			if err := r.parkBlocked(limit, 0); err != nil {
				if cur := r.s.cur; g.broken == 0 && (cur.unwind != nil || cur.death == "killed") {
					// A waiter whose instance was killed (§13.1 item 18)
					// breaks the generation: the others fail with
					// peer-killed.
					g.breakGen(r, name, me, "peer-killed")
				}
				g.drop(me)
				return nil, err
			}
		}
		if !me.released {
			// A timeout breaks the generation, as a broken barrier: every
			// waiter fails now with the same data, and the name starts a new
			// generation.
			if g.broken == 0 {
				g.breakGen(r, name, me, "timeout")
			}
			arrived := g.broken
			e := &Error{Code: "timeout", Retryable: true,
				Message: fmt.Sprintf("rendezvous %s: %d of %d arrived before the timeout", name, arrived, g.count),
				Data:    map[string]any{"arrived": int64(arrived), "count": int64(g.count)}}
			if g.code == "peer-killed" {
				e.Code = g.code
				e.Message = fmt.Sprintf("rendezvous %s: a waiting peer was killed", name)
			}
			if err := r.ev(Event{Type: "rendezvous", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst,
				Key: name, Error: e, Output: map[string]any{"generation": int64(gen), "arrived": int64(arrived), "count": int64(g.count)}}); err != nil {
				return nil, err
			}
			f.lastErr = e.Map()
			return r.onError(f, s.OnError, e, depth, p, false)
		}
		if r.now < me.at {
			if err := r.sleepUntil(me.at); err != nil {
				return nil, err
			}
		}
	}
	values := make([]any, len(g.arrivals))
	for i, a := range g.arrivals {
		values[i] = deepCopy(a.value)
	}
	res := map[string]any{"values": values, "index": int64(me.index), "count": int64(len(g.arrivals))}
	if s.As != "" {
		f.vars[s.As] = res
	}
	return nil, r.ev(Event{Type: "rendezvous", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst,
		Key: name, Output: map[string]any{"generation": int64(gen), "index": int64(me.index), "count": int64(len(g.arrivals))}})
}

// breakGen breaks a generation, as a broken barrier: every waiter but me
// resumes now and fails, and the name starts a new generation.
func (g *rendezvousGen) breakGen(r *run, name string, me *arrival, code string) {
	g.broken, g.code = len(g.arrivals), code
	if r.rdv[name] == g {
		r.rdv[name] = &rendezvousGen{gen: g.gen}
	}
	for _, a := range g.arrivals {
		if a != me {
			r.wakeAt(a.t, r.now, 0)
		}
	}
}

// drop removes an arrival that gave up, re-indexing the rest.
func (g *rendezvousGen) drop(a *arrival) {
	for i, x := range g.arrivals {
		if x == a {
			g.arrivals = append(g.arrivals[:i:i], g.arrivals[i+1:]...)
			break
		}
	}
	for i, x := range g.arrivals {
		x.index = i
	}
}

// stepLatency evaluates a step's latency_ms (a number, a range or "=cel")
// in µs; none is 0.
func (r *run) stepLatency(f *frame, l *model.Latency, p string) (int64, error) {
	if l == nil {
		return 0, nil
	}
	if l.Expr != "" {
		v, err := expr.Behavior.Eval(strings.TrimSpace(l.Expr), r.act(f, 1))
		if err != nil {
			return 0, abortf("%s.latency_ms: %v", p, err)
		}
		n, ok := r.valueUS(v)
		if !ok {
			return 0, abortf("%s.latency_ms: must give milliseconds, got %T", p, v)
		}
		return max(n, 0), nil
	}
	if l.Max <= l.Min {
		return r.msToUS(l.Min), nil
	}
	if l.Min == math.Trunc(l.Min) && l.Max == math.Trunc(l.Max) {
		return (int64(l.Min) + r.rng.Int64N(int64(l.Max)-int64(l.Min)+1)) * 1000, nil
	}
	a, b := r.msToUS(l.Min), r.msToUS(l.Max)
	return a + r.rng.Int64N(b-a+1), nil
}

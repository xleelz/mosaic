package sim

import (
	"regexp"

	"github.com/xleelz/mosaic/internal/model"
)

// The io expectation root (§15.1): the boundary view of a run. It holds
// one item per entry call, per call into a component of kind external or
// marked attributes.boundary, and per route call, in start order:
//
//	{seq, t, dir: in|out, kind: entry|external|route, interface, component,
//	 instance, input, output: {ok, value, error}, headers, duration_ms, duration_us}
//	 (and t_us, the exact clock of t, §17 item 17)
//
// Scenarios that assert on io, result and steps survive internal renames.
// The items are collected from the run's call events: a call.start opens
// an item (a route event opens and, for a route answered by the router
// itself, closes one) and the matching call.end fills its output.

// ioRef matches expectations that read io, so runs whose expectations
// don't pay nothing for it.
var ioRef = regexp.MustCompile(`\bio\b`)

// mentionsIO reports whether any expectation reads the io root.
func mentionsIO(exprs []string) bool {
	for _, e := range exprs {
		if ioRef.MatchString(e) {
			return true
		}
	}
	return false
}

// IsBoundaryComponent reports whether calls into a component cross the
// modeled system's boundary: kind external, or attributes.boundary.
func IsBoundaryComponent(c *model.Component) bool {
	if c == nil {
		return false
	}
	if c.Kind == "external" {
		return true
	}
	b, _ := c.Attributes["boundary"].(bool)
	return b
}

// ioItem is one boundary item while it's being collected.
type ioItem struct {
	t, dur      int64
	tUS, durUS  int64
	dir, kind   string
	iface, comp string
	inst        string
	input       any
	output      any // {ok, value, error}; nil while the call is in flight
	headers     any
	ended       bool
}

// ioValue is the io root as expectations see it.
func (r *run) ioValue() []any {
	items := r.ioItems()
	out := make([]any, len(items))
	for i, it := range items {
		var dur, durUS any
		if it.ended {
			dur, durUS = it.dur, it.durUS // durUS exact (§17 item 10)
		}
		out[i] = map[string]any{"seq": int64(i + 1), "t": it.t, "t_us": it.tUS, "dir": it.dir, "kind": it.kind, "interface": it.iface,
			"component": it.comp, "instance": it.inst, "input": it.input, "output": it.output, "headers": it.headers,
			"duration_ms": dur, "duration_us": durUS}
	}
	return out
}

// ioItems collects the boundary items from the run's events.
func (r *run) ioItems() []*ioItem {
	var items []*ioItem
	open := map[int]*ioItem{}   // by call.start span
	routed := map[int]*ioItem{} // route items still waiting for their call, by call id
	for i := range r.events {
		e := &r.events[i]
		switch e.Type {
		case "route":
			it := &ioItem{t: e.T, tUS: e.tUS, dir: "out", kind: "route", iface: e.Interface, comp: e.To, inst: e.Instance, input: e.Input}
			if e.Error != nil || e.Output != nil {
				// The router answered itself: a refusal, a redirect or no route.
				it.output, it.ended = ioOutcome(e.Error == nil, e.Output, e.Error), true
			} else {
				routed[e.Call] = it
			}
			items = append(items, it)
		case "call.start":
			if it, ok := routed[e.Call]; ok {
				delete(routed, e.Call)
				it.inst = e.Instance
				open[e.Span] = it
				continue
			}
			var it *ioItem
			switch {
			case e.Parent == 0 && !e.Async:
				it = &ioItem{dir: "in", kind: "entry"}
			case IsBoundaryComponent(r.x.Components[e.To]):
				it = &ioItem{dir: "out", kind: "external"}
			default:
				continue
			}
			it.t, it.tUS, it.iface, it.comp, it.inst, it.input = e.T, e.tUS, e.Interface, e.To, e.Instance, e.Input
			open[e.Span] = it
			items = append(items, it)
		case "call.end":
			it, ok := open[e.Span]
			if !ok {
				continue
			}
			delete(open, e.Span)
			ok2 := e.OK != nil && *e.OK
			it.output, it.dur, it.durUS, it.ended = ioOutcome(ok2, e.Output, e.Error), e.DurationMS, e.durUS, true
			if len(e.Headers) > 0 {
				it.headers = e.Headers
			}
		}
	}
	return items
}

func ioOutcome(ok bool, value any, err *Error) map[string]any {
	var errv any
	if err != nil {
		errv = err.Map()
	}
	return map[string]any{"ok": ok, "value": value, "error": errv}
}

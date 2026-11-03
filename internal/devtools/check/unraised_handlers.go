package main

// The unraised-errors lint follows handlers (DESIGN §17 item 7): a fail
// step inside the on_error steps of a receive, a put, a rendezvous, a
// wait, a publish or any other step that catches its own failure raises,
// as one in a call's on_error does, at any depth (parallel branches
// included). The handler's error in scope is what the step can fail with:
// a timeout, a stalled stream, or a sync subscriber's errors.

import "github.com/xleelz/mosaic/internal/model"

// handlers walks the on_error steps of a step the main switch doesn't
// handle (calls, routes and transacts walk their own).
func (b *behaviorRaises) handlers(s model.Step, errCtx *raiseSet) {
	if s.OnError == nil || s.OnError.Steps == nil || s.Call != "" || s.Route != nil || len(s.Transact) > 0 {
		return
	}
	errs := newRaiseSet()
	switch {
	case s.Receive != "" || s.Put != "" || s.Rendezvous != "" || s.Wait != nil:
		errs.codes["timeout"] = true
	case s.Yield != nil:
		errs.codes["stream_stalled"] = true
	case s.Publish != "":
		for _, t := range b.a.x.Subscribers[s.Publish] {
			errs.union(b.a.callee(t))
		}
	default:
		errs.union(b.inScope(errCtx))
	}
	b.steps(s.OnError.Steps, errs)
}

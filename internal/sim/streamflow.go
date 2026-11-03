package sim

import (
	"fmt"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Stream flow control (§16.4). A streaming call may declare window: N and
// stall_ms. Frames in flight are those yielded but not yet handled: queued
// for the caller, or the one whose on_item steps are running. A yield that
// finds N in flight blocks its producer until the caller finishes one. A
// producer blocked for stall_ms fails the stream with {code:
// stream_stalled}: its yield fails (the error ends its behavior, as any
// failed step without on_error), a stall event records it, and the caller,
// once it has handled the frames already in flight, gets the same error as
// the call's result. A caller that stops reading (an exit or error in
// on_item, a cancel, a kill) releases blocked producers; their later
// frames go nowhere, as before.
//
// Byte windows (§17 item 5). window_bytes bounds the bytes in flight: each
// frame counts its numeric size field when it has one, else
// bytes(json(frame)). A yield blocks while frames are in flight and its
// frame would take them past window_bytes, so a frame larger than the
// whole window still goes alone. The yield's item is evaluated before it
// waits, as a producer builds a frame before it sends it.
//
// Relays (§17 item 5). A streaming call with relay: true, made by a
// behavior that is itself streaming to its caller, links its stream to
// that outer one. A yield checks every window up the chain (each with its
// own stall_ms), so a slow final consumer blocks the original producer
// rather than letting frames pile up at the forwarding hop.

type streamFlow struct {
	window  int64 // frames in flight before a yield blocks; 0 means none
	bytes   int64 // bytes in flight before a yield blocks; 0 means none
	busyB   int64 // the size of the frame the caller is handling
	stallUS int64 // the longest a producer may block; 0 means no limit
	stallMS any   // stall_ms as written, for the error's data
	busy    bool  // the caller is running on_item for a frame
	gone    bool  // the caller stopped reading
	waiters []*task
	stalled *Error
}

// setupFlow reads a streaming call's window, window_bytes and stall_ms.
func (r *run) setupFlow(f *frame, s model.Step, st *stream, p string) error {
	if s.Window.IsZero() && s.WindowBytes.IsZero() {
		return nil
	}
	fl := &streamFlow{}
	var err error
	if !s.Window.IsZero() {
		if fl.window, err = r.countOf(f, s.Window, p+".window"); err != nil {
			return err
		}
		if fl.window < 1 {
			return abortf("%s.window: a stream window is at least 1, got %d", p, fl.window)
		}
	}
	if !s.WindowBytes.IsZero() {
		if fl.bytes, err = r.countOf(f, s.WindowBytes, p+".window_bytes"); err != nil {
			return err
		}
		if fl.bytes < 1 {
			return abortf("%s.window_bytes: a byte window is at least 1, got %d", p, fl.bytes)
		}
	}
	if !s.StallMS.IsZero() {
		if fl.stallUS, err = r.intOf(f, s.StallMS, p+".stall_ms"); err != nil {
			return err
		}
		fl.stallMS = msFloor(fl.stallUS)
		if fl.stallUS%1000 != 0 {
			fl.stallMS = float64(fl.stallUS) / 1000
		}
	}
	st.flow = fl
	return nil
}

// frameSize is a frame's size for window_bytes: its numeric size field,
// else the length of its canonical JSON.
func frameSize(v any) int64 {
	if m, ok := v.(map[string]any); ok {
		if n, ok := toInt(m["size"]); ok {
			return max(n, 0)
		}
	}
	js, err := expr.Canonical(v)
	if err != nil {
		return 0
	}
	return int64(len(js))
}

// full reports whether a frame of size bytes must wait for room.
func (fl *streamFlow) full(st *stream, size int64) bool {
	n := fl.inFlight(st)
	if fl.window > 0 && n >= fl.window {
		return true
	}
	if fl.bytes > 0 && n > 0 {
		b := fl.busyB
		for _, it := range st.queue {
			b += it.size
		}
		return b+size > fl.bytes
	}
	return false
}

func (fl *streamFlow) inFlight(st *stream) int64 {
	n := int64(len(st.queue))
	if fl.busy {
		n++
	}
	return n
}

func (r *run) wakeProducers(fl *streamFlow) {
	ws := fl.waiters
	fl.waiters = nil
	for _, t := range ws {
		r.wakeAt(t, r.now, 0)
	}
}

// flowTake marks the caller busy with the frame it took from the queue.
func (r *run) flowTake(st *stream, size int64) {
	if fl := st.flow; fl != nil {
		fl.busy, fl.busyB = true, size
	}
}

// flowDone marks the caller's frame handled and wakes blocked producers.
func (r *run) flowDone(st *stream) {
	if fl := st.flow; fl != nil {
		fl.busy, fl.busyB = false, 0
		r.wakeProducers(fl)
	}
}

// flowGone records that the caller stopped reading.
func (r *run) flowGone(st *stream) {
	if fl := st.flow; fl != nil && !fl.gone {
		fl.gone, fl.busy, fl.busyB = true, false, 0
		r.wakeProducers(fl)
	}
}

// flowStalled is the stall error once the caller has nothing left to
// handle.
func flowStalled(st *stream) *Error {
	if st.flow == nil || len(st.queue) > 0 {
		return nil
	}
	return st.flow.stalled
}

// yieldStep runs a yield step, waiting first for room in every window up
// the stream's relay chain.
func (r *run) yieldStep(f *frame, s model.Step, depth int, p string) (*exit, error) {
	if f.plain {
		return nil, abortf("%s: yield on a call whose streams_when (%s) is false", p, f.iface.StreamsWhen)
	}
	v, err := r.yieldValue(f, s, p)
	if err != nil {
		return nil, err
	}
	var size int64
	if st := f.stream; st != nil && st.live && hasFlow(st) {
		size = frameSize(v)
		e, err := r.flowWait(f, st, size)
		if err != nil {
			return nil, err
		}
		if e != nil {
			f.lastErr = e.Map()
			return r.onError(f, s.OnError, e, depth, p, false)
		}
	}
	return nil, r.yieldItem(f, v, size, p)
}

// hasFlow reports whether a stream or one it relays into has a window.
func hasFlow(st *stream) bool {
	for ; st != nil; st = st.up {
		if st.live && st.flow != nil {
			return true
		}
	}
	return false
}

// flowWait blocks the producer while a window up the relay chain is full.
// It gives the stall error when the producer stays blocked on a window for
// that window's stall_ms (counted from the yield), or when a stream in the
// chain has already stalled.
func (r *run) flowWait(f *frame, own *stream, size int64) (*Error, error) {
	start := r.now
	for {
		var fl *streamFlow
		var st *stream
		for s := own; s != nil; s = s.up {
			if !s.live || s.flow == nil {
				continue
			}
			if s.flow.stalled != nil {
				return s.flow.stalled, nil
			}
			if !s.flow.gone && s.flow.full(s, size) {
				fl, st = s.flow, s
				break
			}
		}
		if fl == nil {
			return nil, nil
		}
		limit := int64(noDeadline)
		if fl.stallUS > 0 {
			limit = start + fl.stallUS
		}
		if limit != noDeadline && r.now >= limit {
			idx := st.n
			data := map[string]any{"stall_ms": fl.stallMS, "index": idx}
			what := ""
			if fl.window > 0 {
				data["window"] = fl.window
				what = fmt.Sprintf("a window of %d frames", fl.window)
			}
			if fl.bytes > 0 {
				data["window_bytes"] = fl.bytes
				if what != "" {
					what += " and "
				}
				what += fmt.Sprintf("a window of %d bytes", fl.bytes)
			}
			fl.stalled = &Error{Code: "stream_stalled", Message: fmt.Sprintf("the producer was blocked for %s ms on a full stream (%s)", fmtMS(r.now-start), what), Data: data}
			if st.parked { // never, with a full window; kept for safety
				st.parked = false
				r.wakeAt(st.caller, r.now, 0)
			}
			return fl.stalled, r.ev(Event{Type: "stall", Span: f.span, Component: f.comp, Interface: f.iface.ID, Instance: f.inst,
				Error: fl.stalled, WaitMS: r.now - start, Index: &idx})
		}
		me := r.s.cur
		fl.waiters = append(fl.waiters, me)
		err := r.park(limit, 0)
		for i, t := range fl.waiters { // a wake by the stall limit leaves it listed
			if t == me {
				fl.waiters = append(fl.waiters[:i:i], fl.waiters[i+1:]...)
				break
			}
		}
		if err != nil {
			return nil, err
		}
	}
}

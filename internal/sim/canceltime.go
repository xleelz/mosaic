package sim

// Cancel time (§16.4). A call canceled by its token or by a session close
// keeps the time of the cancel. The callee's handler, which runs on (its
// later events late), reads it as ctx.cancelled_at_ms, so that work billed
// up to a hang-up can measure from the cancel rather than from whatever
// step the handler next reaches. The caller reads it as
// vars.<as>.cancelled_at_ms. Both are clock readings like `now` (epoch ms).
//
// The mark belongs to the canceled call's own handler frame (and the
// parallel branches inside it), not to the calls the handler makes.

type cancelMark struct {
	set bool
	at  int64 // the virtual clock (µs) at the cancel
}

func markedAt(at int64) *cancelMark { return &cancelMark{set: true, at: at} }

// mark records the cancel time once.
func (m *cancelMark) mark(at int64) {
	if m != nil && !m.set {
		m.set, m.at = true, at
	}
}

// ctxOf is the ctx a frame's CEL sees: the run-wide ctx, plus
// cancelled_at_ms in the handler of a canceled call. Writes to ctx still go
// to the run-wide map (set steps write r.ctx directly).
func (r *run) ctxOf(f *frame) map[string]any {
	if f == nil || f.cancel == nil || !f.cancel.set {
		return r.ctx
	}
	out := make(map[string]any, len(r.ctx)+1)
	for k, v := range r.ctx {
		out[k] = v
	}
	out["cancelled_at_ms"] = msValue(r.epoch, f.cancel.at)
	return out
}

// cancelTime adds cancelled_at_ms to a call step's result when the call was
// canceled.
func (r *run) cancelTime(out map[string]any, res callResult) {
	if res.cancel != nil && res.cancel.set {
		out["cancelled_at_ms"] = msValue(r.epoch, res.cancel.at)
	}
}

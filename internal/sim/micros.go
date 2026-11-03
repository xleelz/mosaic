package sim

import (
	"math"
	"strconv"

	"github.com/xleelz/mosaic/internal/model"
)

// The virtual clock counts microseconds (§13.1 item 16). Inputs are
// milliseconds, possibly fractional; integer ms outputs are floor(us/1000),
// so a run with only whole-ms inputs gives the same results as before. The
// exact *_us outputs appear only in runs whose clock left whole
// milliseconds (r.fine), which keeps such runs byte-identical too.

// msFloor converts microseconds to whole milliseconds, rounding down.
func msFloor(us int64) int64 {
	q := us / 1000
	if us%1000 < 0 {
		q--
	}
	return q
}

// msToUS converts a millisecond input to microseconds.
func (r *run) msToUS(ms float64) int64 {
	us := int64(math.Round(ms * 1000))
	if us%1000 != 0 {
		r.fine = true
	}
	return us
}

// numUS converts an IntOrExpr number of milliseconds to microseconds.
func (r *run) numUS(v model.IntOrExpr) int64 {
	if !v.IsWhole() {
		r.fine = true
	}
	return v.US()
}

// valueUS converts an evaluated millisecond value (an int or a float) to
// microseconds.
func (r *run) valueUS(v any) (int64, bool) {
	switch t := v.(type) {
	case int64:
		return t * 1000, true
	case float64:
		if math.IsNaN(t) || math.IsInf(t, 0) {
			return 0, false
		}
		return r.msToUS(t), true
	}
	return 0, false
}

// msValue is a clock reading in ms for CEL: epoch ms plus the virtual
// clock, an int when whole and a float otherwise.
// msValue is CEL's `now`: whole milliseconds, always an int, so expressions
// like `now / 1000` keep one type whatever the clock reads. The exact clock is
// `now_us` (DESIGN §13.1 item 16).
func msValue(epochMS, us int64) any {
	return epochMS + floorDiv(us, 1000)
}

func floorDiv(a, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

// fmtMS formats microseconds as milliseconds for messages.
func fmtMS(us int64) string {
	if us%1000 == 0 {
		return strconv.FormatInt(us/1000, 10)
	}
	return strconv.FormatFloat(float64(us)/1000, 'f', -1, 64)
}

func ptr(v int64) *int64 { return &v }

// finishUS fills the exact *_us outputs of a run whose clock left whole
// milliseconds.
func (r *run) finishUS(s *Summary) {
	if !r.fine {
		return
	}
	for i := range r.events {
		e := &r.events[i]
		e.TUS = ptr(e.tUS)
		if e.durUS != 0 {
			e.DurationUS = ptr(e.durUS)
		}
	}
	s.DurationUS = ptr(r.s.end)
	for i := range s.Passes {
		s.Passes[i].DurationUS = ptr(s.Passes[i].durUS)
	}
	for i := range s.Steps {
		s.Steps[i].DurationUS = ptr(s.Steps[i].durUS)
	}
}

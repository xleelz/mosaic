package sim

import (
	"fmt"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// DESIGN §17 items 18 and 21: the run's foreach cap and scenario close
// steps.

// foreachLimit is how many items a foreach (or parallel foreach) whose step
// sets max takes (§17 item 18). Without a run cap (a scenario's
// max_foreach, or Limits.MaxForeach) it is the step's max, or
// DefaultForeachMax, cut to MaxForeachMax, as before. With one, a step
// without max takes up to the cap, and a step's max is cut to it.
func (r *run) foreachLimit(max int) int {
	cap := r.lim.MaxForeach
	if cap <= 0 {
		if max <= 0 {
			max = model.DefaultForeachMax
		}
		return min(max, model.MaxForeachMax)
	}
	if max <= 0 {
		return cap
	}
	return min(max, cap)
}

// branchLimit is the most branches a parallel runs: MaxForeachMax, or the
// run's foreach cap.
func (r *run) branchLimit() int {
	if r.lim.MaxForeach > 0 {
		return r.lim.MaxForeach
	}
	return model.MaxForeachMax
}

// closeStep runs a scenario step's close (§17 item 21): the calls in
// flight that carry the session key fail with canceled, as a behavior's
// close makes them. The key is literal or "=cel" over the step variables.
func (r *run) closeStep(i int, c *model.CloseSpec) error {
	key := c.Session
	if src, ok := expr.ExprOf(key); ok {
		v, err := expr.Step.Eval(src, r.topAct(nil, r.stepsValue()))
		if err != nil {
			return abortf("steps[%d].close.session: %v", i, err)
		}
		switch t := v.(type) {
		case string:
			key = t
		case int64, uint64, float64, bool:
			key = fmt.Sprint(t)
		default:
			key = ""
		}
		if key == "" {
			return abortf("steps[%d].close.session: a session key must be a non-empty string or a number, got %#v", i, v)
		}
	}
	return r.closeSession(key, "", "", 0)
}

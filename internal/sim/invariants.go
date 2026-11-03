package sim

// checks evaluates a finished run's expectations and then its invariants
// (DESIGN §16.2) in one activation: the final state, trace, io and calls.
// Invariant results are marked, so schedule exploration can check them
// under every schedule and the expectations only on the default one.
func (r *run) checks(eff Request, s Summary) []Assertion {
	if len(eff.Invariants) == 0 {
		return r.expectations(eff.Expect, s)
	}
	all := append(append([]string{}, eff.Expect...), eff.Invariants...)
	out := r.expectations(all, s)
	for i := len(eff.Expect); i < len(out); i++ {
		out[i].Invariant = true
	}
	return out
}

package model

import (
	"github.com/xleelz/mosaic/internal/expr"
)

// DESIGN §15.3 validation: per-scenario caps and mid-run set steps.

// DefaultMaxIterations and MaxMaxIterations are a scenario's default and
// largest max_iterations, the run's loop cap (§15.3).
const (
	DefaultMaxIterations = 10_000
	MaxMaxIterations     = 1_000_000
)

// scenarioCaps checks a scenario's max_iterations and max_cel_cost.
func (v *validator) scenarioCaps(p string, s *Scenario) {
	if s.MaxIterations != nil && (*s.MaxIterations <= 0 || *s.MaxIterations > MaxMaxIterations) {
		v.errf(p+".max_iterations", "max_iterations must be between 1 and %d", MaxMaxIterations)
	}
	if s.MaxCELCost != nil {
		if *s.MaxCELCost <= 0 {
			v.errf(p+".max_cel_cost", "max_cel_cost must be positive")
		}
		if s.CostLimit != nil && *s.CostLimit != *s.MaxCELCost {
			v.errf(p+".max_cel_cost", "max_cel_cost is cost_limit's other name; give one of them")
		}
	}
	// The safety bound (behavior-language §30).
	if s.MaxCELCost != nil && *s.MaxCELCost > expr.MaxCostLimit {
		v.errf(p+".max_cel_cost", "max_cel_cost must be at most %d", int64(expr.MaxCostLimit))
	}
	if s.CostLimit != nil && *s.CostLimit > expr.MaxCostLimit {
		v.errf(p+".cost_limit", "cost_limit must be at most %d", int64(expr.MaxCostLimit))
	}
}

// setStep checks a scenario step's set (§15.3): known components and
// instances, dotted paths without empty segments, and template values.
// Values see steps.<as>, so only their JSON and textual CEL are checked.
func (v *validator) setStep(p string, st ScenarioStep, topo map[string][]string) {
	if len(st.Set) == 0 {
		v.errf(p, "set needs at least one component")
	}
	for _, k := range sortedKeys(st.Set) {
		kp := p + "." + k
		comp, inst := SplitStateKey(k)
		if _, ok := v.x.Components[comp]; !ok {
			v.errf(kp, "unknown component %q", comp)
		} else {
			v.instanceIn(kp, topo, comp, inst)
		}
		if len(st.Set[k]) == 0 {
			v.errf(kp, "set needs at least one path per component")
		}
		for _, path := range sortedKeys(st.Set[k]) {
			if _, err := ParsePath(path); err != nil {
				v.errf(kp+"."+path, "invalid state path: %v", err)
			}
			for _, src := range expr.TemplateExprs(expr.Native(st.Set[k][path])) {
				v.celText(kp+"."+path, src)
			}
		}
	}
}

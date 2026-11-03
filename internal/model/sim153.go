package model

import (
	"strings"

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
			if path == "" || strings.HasPrefix(path, ".") || strings.HasSuffix(path, ".") || strings.Contains(path, "..") {
				v.errf(kp+"."+path, "invalid state path %q", path)
			}
			for _, src := range expr.TemplateExprs(expr.Native(st.Set[k][path])) {
				v.celText(kp+"."+path, src)
			}
		}
	}
}

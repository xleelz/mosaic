package model

import (
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
)

// DESIGN §17 validation: a scenario's foreach cap (item 18) and close steps
// (item 21).

// MaxMaxForeach is the largest max_foreach a scenario, and the largest max
// a foreach step, may set (§17 item 18). Without a scenario max_foreach a
// step's max is still cut to MaxForeachMax at run time.
const MaxMaxForeach = 1_000_000

// foreachCap checks a scenario's max_foreach.
func (v *validator) foreachCap(p string, s *Scenario) {
	if s.MaxForeach != nil && (*s.MaxForeach <= 0 || *s.MaxForeach > MaxMaxForeach) {
		v.errf(p+".max_foreach", "max_foreach must be between 1 and %d", MaxMaxForeach)
	}
}

// closeStep checks a scenario step's close: a session key, literal or
// "=cel" over the step variables.
func (v *validator) closeStep(p string, c *CloseSpec) {
	if src, ok := expr.ExprOf(c.Session); ok {
		v.expr(expr.Step, p+".session", src)
		return
	}
	if strings.TrimSpace(c.Session) == "" {
		v.errf(p+".session", "a session needs a key")
	}
}

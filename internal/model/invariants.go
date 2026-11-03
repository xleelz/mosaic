package model

import (
	"fmt"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
)

// invariants checks a scenario's invariants (DESIGN §16.2): CEL in the
// expectation environment, non-empty and distinct.
func (v *validator) invariants(p string, s *Scenario) {
	seen := map[string]bool{}
	for j, e := range s.Invariants {
		ip := fmt.Sprintf("%s.invariants[%d]", p, j)
		if strings.TrimSpace(e) == "" {
			v.errf(ip, "an invariant needs an expression")
			continue
		}
		if seen[strings.TrimSpace(e)] {
			v.errf(ip, "duplicate invariant %q", e)
		}
		seen[strings.TrimSpace(e)] = true
		v.expr(expr.Expect, ip, e)
	}
}

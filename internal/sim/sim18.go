package sim

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// behavior-language §30: the cost limit scaled from the inputs' size, and
// warnings for integers beyond uint64 in the inputs.

// CostPerInputByte scales the default CEL cost limit: a run whose inputs
// take n bytes of JSON gets max(expr.DefaultCostLimit, n *
// CostPerInputByte), up to ScaledCostCap. A prompt of 8,000 tokens (about
// 32 KB) gets 640,000,000.
const CostPerInputByte = 20_000

// ScaledCostCap bounds the scaled default. A scenario's max_cel_cost or a
// run's Limits.CELCost may go higher, up to expr.MaxCostLimit.
const ScaledCostCap = 1_000_000_000

// ScaledCostLimit is the default CEL cost limit of a run whose inputs
// take n bytes of JSON.
func ScaledCostLimit(n int) int64 {
	c := int64(n) * CostPerInputByte
	return max(expr.DefaultCostLimit, min(c, ScaledCostCap))
}

// scanInputs measures the run's inputs (the request's, the scenario's,
// the flow entry's and every step's) for the scaled cost limit, and
// records a warning for each integer in them beyond uint64.
func (pl *plan) scanInputs(sc *model.Scenario, req Request) {
	type src struct {
		what string
		raw  json.RawMessage
	}
	srcs := []src{{"input", req.Input}}
	if sc != nil {
		srcs = append(srcs, src{"scenario input", sc.Input})
	}
	if pl.flow != nil {
		srcs = append(srcs, src{"flow entry input", pl.flow.Entry.Input})
	}
	for i, st := range pl.steps {
		srcs = append(srcs, src{fmt.Sprintf("steps[%d].input", i), st.Input})
	}
	for _, s := range srcs {
		pl.inputBytes += len(s.raw)
		for _, l := range expr.LossyInts(s.raw) {
			path, lit, _ := strings.Cut(l, "=")
			pl.warnings = append(pl.warnings, LossyIntMessage(s.what, path, lit))
		}
	}
}

// LossyIntMessage describes an integer beyond uint64 that became a double.
func LossyIntMessage(what, path, lit string) string {
	at := what
	if path != "" {
		at += "." + path
	}
	var f float64
	_ = json.Unmarshal([]byte(lit), &f)
	return fmt.Sprintf("%s: the integer %s is beyond uint64 (18446744073709551615), so CEL sees the double %g and digits are lost; write {$bigint: \"%s\"} to keep them as a decimal string", at, lit, f, lit)
}

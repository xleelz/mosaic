package main

// The §17 item 18 run caps: --max-events, --max-iterations and
// --max-foreach set the default caps of every scenario run; a scenario's
// own max_events, max_iterations or max_foreach still wins. --max-cel-cost
// sets the CEL cost limit of one evaluation in runs whose scenario sets no
// max_cel_cost.

import (
	"flag"
	"fmt"
	"os"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

var (
	capEvents     = flag.Int("max-events", 0, "the event cap of runs whose scenario sets no max_events (default 20000; up to 1000000)")
	capIterations = flag.Int("max-iterations", 0, "the foreach iteration budget of runs whose scenario sets no max_iterations (default 10000; up to 1000000)")
	capCELCost    = flag.Int64("max-cel-cost", 0, "the CEL cost limit of one evaluation in runs whose scenario sets no max_cel_cost (default: scales with the input size; up to 1e10)")
	capForeach    = flag.Int("max-foreach", 0, "the item cap of every foreach and parallel in runs whose scenario sets no max_foreach (default: a step's max, else 100, at most 1000; up to 1000000)")
)

// applySimLimits sets sim.DefaultLimits from the cap flags.
func applySimLimits() {
	for _, c := range []struct {
		name string
		v    int
		max  int64
		dst  *int
	}{
		{"max-events", *capEvents, model.MaxMaxEvents, &sim.DefaultLimits.MaxEvents},
		{"max-iterations", *capIterations, model.MaxMaxIterations, &sim.DefaultLimits.MaxIterations},
		{"max-foreach", *capForeach, model.MaxMaxForeach, &sim.DefaultLimits.MaxForeach},
	} {
		if c.v == 0 {
			continue
		}
		if c.v < 0 || int64(c.v) > c.max {
			fmt.Fprintf(os.Stderr, "check: --%s must be from 1 to %d\n", c.name, c.max)
			os.Exit(2)
		}
		*c.dst = c.v
	}
	if *capCELCost != 0 {
		if *capCELCost < 0 || *capCELCost > expr.MaxCostLimit {
			fmt.Fprintf(os.Stderr, "check: --max-cel-cost must be from 1 to %d\n", int64(expr.MaxCostLimit))
			os.Exit(2)
		}
		sim.DefaultLimits.CELCost = *capCELCost
	}
}

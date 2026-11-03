package sim_test

import (
	"slices"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// TestRetryJitter covers retry.jitter: draws are seeded (one seed, one
// sequence), stay in bounds, show in the retry event, and the default
// waits the computed backoff as before.
func TestRetryJitter(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: a, name: none, behavior: [{call: b.flaky, on_error: continue, retry: {max_attempts: 6, backoff_ms: 100, multiplier: 2, max_backoff_ms: 800}}]}
  - {component: a, name: explicit, behavior: [{call: b.flaky, on_error: continue, retry: {max_attempts: 6, backoff_ms: 100, multiplier: 2, max_backoff_ms: 800, jitter: none}}]}
  - {component: a, name: full, behavior: [{call: b.flaky, on_error: continue, retry: {max_attempts: 6, backoff_ms: 100, multiplier: 2, max_backoff_ms: 800, jitter: full}}]}
  - {component: a, name: equal, behavior: [{call: b.flaky, on_error: continue, retry: {max_attempts: 6, backoff_ms: 100, multiplier: 2, max_backoff_ms: 800, jitter: equal}}]}
  - {component: b, name: flaky, latency_ms: 10}
`)
	faults := []model.Fault{{Target: "b.flaky", Type: "error", Code: "e", Retryable: boolp(true)}}
	computed := []int64{100, 200, 400, 800, 800}
	waits := func(flow string, seed int64) ([]int64, []string) {
		res := run(t, doc, sim.Request{Flow: flow, Faults: faults, Seed: &seed})
		var w []int64
		var modes []string
		ends := eventsFor(res, "call.end", "b.flaky")
		starts := eventsFor(res, "call.start", "b.flaky")
		for i, e := range events(res, "retry") {
			w = append(w, e.BackoffMS)
			modes = append(modes, e.Jitter)
			if gap := starts[i+1].T - ends[i].T; gap != e.BackoffMS {
				t.Errorf("%s seed %d: attempt %d starts %d ms after the previous end, event says %d", flow, seed, i+2, gap, e.BackoffMS)
			}
		}
		return w, modes
	}
	for _, flow := range []string{"none", "explicit"} {
		w, modes := waits(flow, 7)
		eq(t, flow+" waits", w, computed)
		eq(t, flow+" jitter field", modes, []string{"", "", "", "", ""})
	}
	for _, flow := range []string{"full", "equal"} {
		a, modes := waits(flow, 42)
		b, _ := waits(flow, 42)
		eq(t, flow+" same seed, same waits", a, b)
		eq(t, flow+" jitter field", modes, []string{flow, flow, flow, flow, flow})
		varied := false
		for seed := int64(1); seed <= 50; seed++ {
			w, _ := waits(flow, seed)
			if len(w) != len(computed) {
				t.Fatalf("%s seed %d: %d retries", flow, seed, len(w))
			}
			if !slices.Equal(w, a) {
				varied = true
			}
			for i, x := range w {
				lo := int64(0)
				if flow == "equal" {
					lo = computed[i] / 2
				}
				if x < lo || x > computed[i] {
					t.Errorf("%s seed %d: wait %d = %d, want in [%d, %d]", flow, seed, i, x, lo, computed[i])
				}
			}
		}
		if !varied {
			t.Errorf("%s: 50 seeds drew the same waits", flow)
		}
	}
}

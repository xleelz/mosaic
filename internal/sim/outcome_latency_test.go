package sim_test

import (
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// outcomeDoc's b.provision is fast when the VM becomes healthy, slow when
// the deploy deadline passes, and falls back to latency_ms otherwise.
const outcomeDoc = `
interfaces:
  - component: b
    name: provision
    latency_ms: 7
    latency_by_outcome:
      - {when: "result.ok && result.value.outcome == 'healthy'", ms: 30}
      - {when: "!result.ok && result.error.code == 'deploy_timeout'", ms: "=input.wait"}
      - {when: "result.ok", ms: 999}
    behavior:
      - if: "input.mode == 'stuck'"
        then: [{fail: {code: deploy_timeout}}]
      - if: "input.mode == 'broken'"
        then: [{fail: {code: broken}}]
      - {return: {outcome: "= input.mode"}}
  - component: b
    name: plain
    latency_ms: 7
    behavior: [{return: {outcome: healthy}}]
  - {component: a, name: healthy, behavior: [{call: b.provision, input: {mode: healthy, wait: 0}, as: r}, {return: "= vars.r.value"}]}
  - {component: a, name: other, behavior: [{call: b.provision, input: {mode: degraded, wait: 0}, as: r}, {return: "= vars.r.value"}]}
  - {component: a, name: stuck, behavior: [{call: b.provision, input: {mode: stuck, wait: 2700000}, as: r, on_error: continue}, {return: "ok"}]}
  - {component: a, name: broken, behavior: [{call: b.provision, input: {mode: broken, wait: 0}, as: r, on_error: continue}, {return: "ok"}]}
  - {component: a, name: plain, behavior: [{call: b.plain, as: r}, {return: "= vars.r.value"}]}
  - component: a
    name: impatient
    behavior:
      - {call: b.provision, input: {mode: stuck, wait: 2700000}, timeout_ms: 60000, as: r, on_error: continue}
      - {return: "= vars.r.error.code"}
  - component: a
    name: patient
    behavior:
      - {call: b.provision, input: {mode: healthy, wait: 0}, timeout_ms: 60000, as: r}
      - {return: "= vars.r.value.outcome"}
`

func TestLatencyByOutcome(t *testing.T) {
	doc := build(t, outcomeDoc)
	dur := func(flow string) int64 {
		res := run(t, doc, sim.Request{Flow: flow})
		if res.Summary.Status == "aborted" {
			t.Fatalf("%s aborted: %s", flow, res.Summary.Abort)
		}
		ends := eventsFor(res, "call.end", "b.provision")
		if len(ends) == 0 {
			ends = eventsFor(res, "call.end", "b.plain")
		}
		if len(ends) != 1 {
			t.Fatalf("%s: %d call.end events", flow, len(ends))
		}
		return ends[0].DurationMS
	}
	latEvents := func(flow string) []sim.Event {
		res := run(t, doc, sim.Request{Flow: flow})
		var out []sim.Event
		for _, e := range res.Trace {
			if e.Type == "latency" {
				out = append(out, e)
			}
		}
		return out
	}

	// The first match wins: healthy also satisfies "result.ok" (999 ms).
	d := dur("healthy")
	eq(t, "healthy duration", d, int64(30))
	ev := latEvents("healthy")
	if len(ev) != 1 || ev[0].Key != "latency_by_outcome[0]" || ev[0].DurationMS != 30 || ev[0].Interface != "b.provision" {
		t.Errorf("healthy latency event: %+v", ev)
	}
	// A later entry matches; ms is CEL over input.
	d = dur("stuck")
	eq(t, "stuck duration", d, int64(2700000))
	if ev := latEvents("stuck"); len(ev) != 1 || ev[0].Key != "latency_by_outcome[1]" {
		t.Errorf("stuck latency event: %+v", ev)
	}
	d = dur("other")
	eq(t, "degraded duration (the catch-all ok entry)", d, int64(999))
	// No entry matches: latency_ms applies, and no latency event.
	d = dur("broken")
	eq(t, "broken duration (fallback)", d, int64(7))
	if ev := latEvents("broken"); len(ev) != 0 {
		t.Errorf("fallback should record no latency event: %+v", ev)
	}
	// Without the field, nothing changes.
	d = dur("plain")
	eq(t, "plain duration", d, int64(7))
	if ev := latEvents("plain"); len(ev) != 0 {
		t.Errorf("plain latency events: %+v", ev)
	}

	// The added time makes the caller's timeout fire, as latency does.
	res := run(t, doc, sim.Request{Flow: "impatient"})
	eq(t, "impatient result", okValue(t, res), "timeout")
	if to := events(res, "timeout"); len(to) != 1 || to[0].DurationMS != 60000 {
		t.Errorf("timeout events: %+v", to)
	}
	eq(t, "impatient run duration (a.impatient's own 1 ms plus the timeout)", res.Summary.DurationMS, int64(60001))
	res = run(t, doc, sim.Request{Flow: "patient"})
	eq(t, "patient result", okValue(t, res), "healthy")
	if to := events(res, "timeout"); len(to) != 0 {
		t.Errorf("fast outcome timed out: %+v", to)
	}
}

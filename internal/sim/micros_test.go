package sim_test

import (
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §13.1 item 16: microsecond time, on vLLM-sized GPU kernels.
const microDoc = `
components:
  - {id: client}
  - {id: engine, state: {initial: {log: []}}}
  - {id: gpu}
interfaces:
  - component: engine
    name: step
    latency_ms: 0
    behavior:
      - {call: gpu.attn, as: a}
      - {call: gpu.mlp, input: {tokens: 30}, as: m}
      - {return: {now: "= now", now_us: "= now_us", a: "= vars.a.duration_ms"}}
  - {component: gpu, name: attn, latency_ms: 0.005}
  - {component: gpu, name: mlp, latency_ms: "= double(input.tokens) * 0.004"}
  - component: engine
    name: fanout
    latency_ms: 0
    behavior:
      - parallel: [{r: r0, us: 0.120}, {r: r1, us: 0.005}, {r: r2, us: 0.060}]
        steps:
          - {wait: "= vars.item.us"}
          - {set: {state.log: "= state.log + [vars.item.r]"}}
        as_result: j
      - {return: "= vars.j.results.map(b, b.end_us)"}
  - component: engine
    name: timers
    latency_ms: 0
    behavior:
      - {emit: engine.tick, after_ms: 0.050, input: {n: late}}
      - {emit: engine.tick, after_ms: 0.010, input: {n: early}}
      - {emit: engine.tick, every_ms: 0.025, count: 2, input: {n: periodic}}
  - component: engine
    name: tick
    latency_ms: 0
    behavior:
      - {set: {state.log: "= state.log + [input.n + '@' + string(now_us)]"}}
flows:
  - {id: step, entry: {caller: client, interface: engine.step}}
  - {id: fanout, entry: {caller: client, interface: engine.fanout}}
  - {id: timers, entry: {caller: client, interface: engine.timers}}
scenarios:
  - id: kernels
    flow: step
    expect:
      - "result.value.now_us == 125 && result.value.now == 0"
      - "result.value.a == 0"
      - "duration_ms == 0 && duration_us == 125"
      - "trace.exists(e, e.type == 'call.end' && e.interface == 'gpu.attn' && e.duration_us == 5 && e.t == 0)"
  - id: fanout
    flow: fanout
    max_virtual_ms: 1000
    expect:
      - "state.engine.log == ['r1', 'r2', 'r0']"
      - "result.value == [120, 5, 60]"
      - "duration_us == 120"
  - id: timers
    flow: timers
    expect:
      - "state.engine.log == ['periodic@0', 'early@10', 'periodic@25', 'late@50']"
      - "duration_us == 50"
`

func TestMicrosecondTime(t *testing.T) {
	doc := langDoc(t, microDoc)
	res := passes(t, doc, sim.Request{Scenario: "kernels"})
	s := res.Summary
	if s.DurationMS != 0 || s.DurationUS == nil || *s.DurationUS != 125 {
		t.Errorf("duration %d ms, %v us", s.DurationMS, s.DurationUS)
	}
	for _, e := range res.Trace {
		if e.TUS == nil {
			t.Fatalf("event %d lacks t_us", e.Seq)
		}
		if e.Type == "call.end" && e.Interface == "gpu.mlp" && (e.DurationUS == nil || *e.DurationUS != 120 || e.DurationMS != 0) {
			t.Errorf("mlp call.end %+v", e)
		}
	}
	passes(t, doc, sim.Request{Scenario: "fanout"})
	passes(t, doc, sim.Request{Scenario: "timers"})
}

// TestWholeMSRunsHaveNoMicroFields: whole-ms runs carry no *_us outputs.
func TestWholeMSRunsHaveNoMicroFields(t *testing.T) {
	doc := langDoc(t, quorumDoc)
	res := passes(t, doc, sim.Request{Scenario: "quorum", Expect: []string{"duration_us == 2000000"}})
	if res.Summary.DurationUS != nil || res.Trace[0].TUS != nil {
		t.Error("whole-ms run has *_us outputs")
	}
}

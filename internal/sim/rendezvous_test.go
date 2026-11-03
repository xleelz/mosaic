package sim_test

import (
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §13.1 item 17: rendezvous, on vLLM's tensor-parallel all-reduce.
const rendezvousDoc = `
components:
  - {id: client}
  - {id: engine}
  - {id: gpu-worker, state: {initial: {reduced: []}}}
configs:
  - {id: tp, type: integer, value: 4}
interfaces:
  - component: engine
    name: step
    latency_ms: 0
    behavior:
      - parallel: "= ['r0', 'r1', 'r2', 'r3'].filter(r, int(r.substring(1)) < config.tp)"
        as: rank
        steps:
          - {call: gpu-worker.forward, on: "= vars.rank", input: {step: "= input.step", part: "= int(vars.rank.substring(1)) + 1"}, as: f}
          - {return: "= vars.f.value"}
        as_result: j
      - {return: "= vars.j.results.map(b, b.value)"}
  - component: gpu-worker
    name: forward
    latency_ms: "= 10.0 * double(input.part)"
    behavior:
      - rendezvous: "= 'all-reduce-' + string(input.step)"
        count: "= config.tp == 3 ? 4 : config.tp"
        value: "= input.part"
        latency_ms: 0.5
        timeout_ms: 100
        as: ar
      - {set: {state.reduced: "= state.reduced + [now_us]"}}
      - {return: {sum: "= sum(vars.ar.values)", index: "= vars.ar.index", at: "= now_us"}}
  - component: engine
    name: two-steps
    latency_ms: 0
    behavior:
      - {call: engine.step, input: {step: 1}, as: a}
      - {call: engine.step, input: {step: 1}, as: b}
      - {return: [ "= vars.a.value", "= vars.b.value"]}
flows:
  - {id: step, entry: {caller: client, interface: engine.step, input: {step: 1}}}
  - {id: two, entry: {caller: client, interface: engine.two-steps}}
scenarios:
  - id: all-reduce
    flow: step
    topology: {gpu-worker: [r0, r1, r2, r3]}
    expect:
      - "calls['gpu-worker.forward'] == 4"
      - "result.value.all(v, v.sum == 10 && v.at == 40500)"
      - "result.value.map(v, v.index) == [0, 1, 2, 3]"
      - "duration_us == 40500"
      - "trace.filter(e, e.type == 'rendezvous').size() == 4"
  - id: three-of-four
    flow: step
    topology: {gpu-worker: [r0, r1, r2, r3]}
    config: {tp: 3}
    expect:
      - "!result.ok"
      - "trace.filter(e, e.type == 'rendezvous' && e.error.code == 'timeout' && e.error.data == {'arrived': 3, 'count': 4}).size() == 3"
      - "trace.filter(e, e.type == 'rendezvous' && e.error != null).map(e, e.t) == [110, 110, 110]"
      - "size(state['gpu-worker@r0'].reduced) == 0"
  - id: generations
    flow: two
    topology: {gpu-worker: [r0, r1, r2, r3]}
    expect:
      - "result.ok"
      - "trace.filter(e, e.type == 'rendezvous').map(e, e.output.generation) == [1, 1, 1, 1, 2, 2, 2, 2]"
      - "result.value[1].all(v, v.sum == 10 && v.at == 81000)"
      - "duration_us == 81000"
`

func TestRendezvous(t *testing.T) {
	doc := langDoc(t, rendezvousDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

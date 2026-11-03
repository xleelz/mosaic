package sim_test

import (
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §16.4: cancel time. The motivating case is a hang-up billing
// rule: an LLM stream bills the time it generated for, up to the client's
// hang-up. The handler only notices the cancel at its next frame (300 ms),
// but it bills from the cancel itself (250 ms) through
// ctx.cancelled_at_ms. The caller sees the same time on
// vars.<as>.cancelled_at_ms.
const cancelTimeDoc = `
components:
  - {id: client}
  - {id: gateway, state: {initial: {frames: []}}}
  - {id: llm, state: {initial: {billed_ms: -1, noticed_at: -1}}}
  - {id: search, state: {initial: {seen: -1}}}
interfaces:
  - component: gateway
    name: chat
    latency_ms: 0
    behavior:
      - call: llm.generate
        stream: true
        token: "= 'req-' + input.id"
        as: gen
        on_error: continue
        on_item:
          - {set: {state.frames: "= state.frames + [vars.item]"}}
      - return:
          ok: "= vars.gen.ok"
          code: "= vars.gen.ok ? '' : vars.gen.error.code"
          at: "= has(vars.gen.cancelled_at_ms) ? vars.gen.cancelled_at_ms : -1"
  - component: llm
    name: generate
    latency_ms: 0
    behavior:
      - {set: {vars.start: "= now"}}
      - foreach: "= [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]"
        as: n
        steps:
          - {wait: 100}
          - if: "has(ctx.cancelled_at_ms)"
            then:
              - {set: {state.billed_ms: "= ctx.cancelled_at_ms - vars.start", state.noticed_at: "= now"}}
              - {return: {billed: "= state.billed_ms"}}
          - {yield: "= vars.n"}
      - {set: {state.billed_ms: "= now - vars.start"}}
      - {return: {billed: "= state.billed_ms"}}
  - component: gateway
    name: find
    latency_ms: 0
    behavior:
      - {call: search.run, token: find, as: r, on_error: continue}
      - {return: {code: "= vars.r.error.code", at: "= vars.r.cancelled_at_ms"}}
  - component: search
    name: run
    latency_ms: 500
    behavior:
      - {set: {state.seen: "= has(ctx.cancelled_at_ms) ? ctx.cancelled_at_ms : -2"}}
flows:
  - {id: chat, entry: {caller: client, interface: gateway.chat, input: {id: '1'}}}
  - {id: find, entry: {caller: client, interface: gateway.find}}
scenarios:
  - id: hang-up-billing
    steps:
      - {flow: chat, as: s}
      - {cancel: req-1, at_ms: 250}
    expect:
      - "steps.s.result.value == {'ok': false, 'code': 'canceled', 'at': 250}"
      - "steps.s.duration_ms == 250"
      - "state.gateway.frames == [1, 2]"
      - "state.llm.billed_ms == 250"
      - "state.llm.noticed_at == 300"
      - "trace.exists(e, e.type == 'set' && e.interface == 'llm.generate' && e.late && e.t == 300)"
  - id: no-hang-up
    flow: chat
    expect:
      - "result.value == {'ok': true, 'code': '', 'at': -1}"
      - "state.llm.billed_ms == 1000"
      - "size(state.gateway.frames) == 10"
  - id: canceled-in-latency
    steps:
      - {flow: find, as: s}
      - {cancel: find, at_ms: 200}
    expect:
      - "steps.s.result.value == {'code': 'canceled', 'at': 200}"
      - "state.search.seen == 200"
  - id: canceled-before
    steps:
      - {cancel: find, at_ms: 0}
      - {flow: find, as: s, at_ms: 40}
    expect:
      - "steps.s.result.value == {'code': 'canceled', 'at': 0}"
      - "state.search.seen == -1"
`

func TestCancelTime(t *testing.T) {
	doc := langDoc(t, cancelTimeDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

// DESIGN §16.4: stream flow control. The model yields a frame every 10 ms;
// the gateway takes render-ms to handle each. With window: 2 a slow
// gateway holds the model back; with window: 1 and stall_ms: 30 the model
// stalls and the stream fails with stream_stalled.
const streamFlowDoc = `
components:
  - {id: client}
  - {id: gateway, state: {initial: {got: []}}}
  - {id: model}
configs:
  - {id: render-ms, type: integer, value: 50}
interfaces:
  - component: gateway
    name: windowed
    latency_ms: 0
    behavior:
      - call: model.gen
        stream: true
        window: 2
        as: g
        on_item:
          - {wait: "= config['render-ms']"}
          - {set: {state.got: "= state.got + [[vars.item, now]]"}}
      - {return: "= vars.g.value"}
  - component: gateway
    name: stalling
    latency_ms: 0
    behavior:
      - call: model.gen
        stream: true
        window: 1
        stall_ms: 30
        as: g
        on_error: continue
        on_item:
          - {wait: "= config['render-ms']"}
          - {set: {state.got: "= state.got + [[vars.item, now]]"}}
      - return:
          ok: "= vars.g.ok"
          error: "= vars.g.ok ? {} : vars.g.error"
  - component: model
    name: gen
    latency_ms: 0
    behavior:
      - foreach: "= [0, 1, 2, 3, 4]"
        as: i
        steps:
          - {wait: 10}
          - {yield: "= vars.i"}
      - {return: {done: true}}
flows:
  - {id: windowed, entry: {caller: client, interface: gateway.windowed}}
  - {id: stalling, entry: {caller: client, interface: gateway.stalling}}
scenarios:
  - id: window-holds-producer
    flow: windowed
    expect:
      - "result.value == {'done': true}"
      - "trace.filter(e, e.type == 'yield').map(e, e.t) == [10, 20, 60, 110, 160]"
      - "state.gateway.got == [[0, 60], [1, 110], [2, 160], [3, 210], [4, 260]]"
      - "duration_ms == 260"
  - id: window-fast-consumer
    flow: windowed
    config: {render-ms: 5}
    expect:
      - "result.value == {'done': true}"
      - "trace.filter(e, e.type == 'yield').map(e, e.t) == [10, 20, 30, 40, 50]"
      - "duration_ms == 55"
  - id: stalled
    flow: stalling
    expect:
      - "result.value.ok == false"
      - "result.value.error.code == 'stream_stalled'"
      - "result.value.error.data == {'window': 1, 'stall_ms': 30, 'index': 1}"
      - "trace.filter(e, e.type == 'yield').map(e, e.t) == [10]"
      - "trace.exists(e, e.type == 'stall' && e.t == 50 && e.wait_ms == 30 && e.index == 1 && e.error.code == 'stream_stalled')"
      - "trace.exists(e, e.type == 'call.end' && e.interface == 'model.gen' && e.t == 50 && e.error.code == 'stream_stalled')"
      - "state.gateway.got == [[0, 60]]"
      - "duration_ms == 60"
  - id: no-stall-fast-consumer
    flow: stalling
    config: {render-ms: 5}
    expect:
      - "result.value == {'ok': true, 'error': {}}"
      - "!trace.exists(e, e.type == 'stall')"
      - "size(state.gateway.got) == 5"
`

func TestStreamFlowControl(t *testing.T) {
	doc := langDoc(t, streamFlowDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

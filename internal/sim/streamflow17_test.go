package sim_test

import (
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §17 item 5: byte windows and relays. The model yields a frame
// every 10 ms. A byte window counts each frame's size field (or its
// canonical JSON); a relay hop (proxy.relay) passes the gateway's window
// back to the model, so a slow gateway holds the model itself back, while
// without relay (proxy.buffer) the model runs ahead and frames pile up at
// the proxy.
const byteWindowDoc = `
components:
  - {id: client}
  - {id: gateway, state: {initial: {got: []}}}
  - {id: proxy}
  - {id: model}
interfaces:
  - component: gateway
    name: sized
    latency_ms: 0
    behavior:
      - call: model.sized
        stream: true
        window_bytes: 1000
        as: g
        on_item:
          - {wait: 50}
          - {set: {state.got: "= state.got + [[vars.item.i, now]]"}}
      - {return: "= vars.g.value"}
  - component: gateway
    name: json
    latency_ms: 0
    behavior:
      - call: model.json
        stream: true
        window_bytes: 20
        stall_ms: 30
        as: g
        on_error: continue
        on_item:
          - {wait: 50}
      - {return: {ok: "= vars.g.ok", error: "= vars.g.ok ? {} : vars.g.error"}}
  - component: gateway
    name: via-relay
    latency_ms: 0
    behavior:
      - call: proxy.relay
        stream: true
        window: 1
        as: g
        on_item:
          - {wait: 50}
          - {set: {state.got: "= state.got + [[vars.item, now]]"}}
      - {return: "= vars.g.value"}
  - component: gateway
    name: via-buffer
    latency_ms: 0
    behavior:
      - call: proxy.buffer
        stream: true
        window: 1
        as: g
        on_item:
          - {wait: 50}
          - {set: {state.got: "= state.got + [[vars.item, now]]"}}
      - {return: "= vars.g.value"}
  - component: proxy
    name: relay
    latency_ms: 0
    behavior:
      - call: model.gen
        stream: true
        relay: true
        as: m
        on_item: [{yield: "= vars.item"}]
      - {return: "= vars.m.value"}
  - component: proxy
    name: buffer
    latency_ms: 0
    behavior:
      - call: model.gen
        stream: true
        as: m
        on_item: [{yield: "= vars.item"}]
      - {return: "= vars.m.value"}
  - component: model
    name: gen
    latency_ms: 0
    behavior:
      - foreach: "= [0, 1, 2, 3, 4]"
        as: i
        steps:
          - {wait: 10}
          - {yield: "= vars.i"}
      - {return: {done: "= now"}}
  - component: model
    name: sized
    latency_ms: 0
    behavior:
      - foreach: "= [0, 1, 2]"
        as: i
        steps:
          - {wait: 10}
          - {yield: {i: "= vars.i", size: 600}}
      - {return: {done: "= now"}}
  - component: model
    name: json
    latency_ms: 0
    behavior:
      - foreach: "= [0, 1]"
        as: i
        steps:
          - {wait: 10}
          - {yield: {pad: "0123456789"}}
      - {return: {done: "= now"}}
flows:
  - {id: sized, entry: {caller: client, interface: gateway.sized}}
  - {id: json, entry: {caller: client, interface: gateway.json}}
  - {id: via-relay, entry: {caller: client, interface: gateway.via-relay}}
  - {id: via-buffer, entry: {caller: client, interface: gateway.via-buffer}}
scenarios:
  - id: size-field-window
    flow: sized
    expect:
      - "trace.filter(e, e.type == 'yield').map(e, e.t) == [10, 60, 110]"
      - "state.gateway.got == [[0, 60], [1, 110], [2, 160]]"
  - id: json-size-stall
    flow: json
    expect:
      - "result.value.ok == false"
      - "result.value.error.code == 'stream_stalled'"
      - "result.value.error.data == {'window_bytes': 20, 'stall_ms': 30, 'index': 1}"
      - "trace.exists(e, e.type == 'stall' && e.t == 50 && e.wait_ms == 30)"
  - id: relay-blocks-producer
    flow: via-relay
    expect:
      - "state.gateway.got.map(p, p[0]) == [0, 1, 2, 3, 4]"
      - "trace.filter(e, e.type == 'yield' && e.interface == 'model.gen').map(e, e.t) == [10, 60, 110, 160, 210]"
      - "result.value.done == 210"
  - id: no-relay-runs-ahead
    flow: via-buffer
    expect:
      - "state.gateway.got.map(p, p[0]) == [0, 1, 2, 3, 4]"
      - "trace.filter(e, e.type == 'yield' && e.interface == 'model.gen').map(e, e.t) == [10, 20, 30, 40, 50]"
      - "result.value.done == 50"
`

func TestByteWindowsAndRelay(t *testing.T) {
	doc := langDoc(t, byteWindowDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

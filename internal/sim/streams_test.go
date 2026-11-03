package sim_test

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §13.1 item 18: streams. An SSE-like chat: the model yields a
// token every 10 ms after a 20 ms prefill, and the gateway forwards each
// one to the browser as it is yielded.
const streamDoc = `
components:
  - {id: browser, state: {initial: {chunks: []}}}
  - {id: gateway, state: {initial: {sent: []}}}
  - {id: model}
configs:
  - {id: render-ms, type: integer, value: 0}
interfaces:
  - component: gateway
    name: chat
    latency_ms: 0
    behavior:
      - call: model.generate
        input: {prompt: "= input.prompt"}
        stream: true
        as: gen
        on_item:
          - {call: browser.sse, input: {chunk: "= vars.item", index: "= vars.item_index"}}
          - {set: {state.sent: "= state.sent + [{'i': vars.item_index, 't': now}]"}}
      - {return: {text: "= vars.gen.value.text", chunks: "= size(state.sent)"}}
  - component: gateway
    name: buffered
    latency_ms: 0
    behavior:
      - {call: model.generate, as: gen}
      - {return: "= vars.gen.value"}
  - component: browser
    name: sse
    latency_ms: "= config['render-ms']"
    behavior:
      - {set: {state.chunks: "= state.chunks + [input.chunk]"}}
  - component: model
    name: generate
    latency_ms: 20
    behavior:
      - foreach: "= ['Hel', 'lo', ' world']"
        as: tok
        steps:
          - {wait: 10}
          - {yield: "= vars.tok"}
      - {return: {text: Hello world}}
flows:
  - {id: chat, entry: {caller: browser, interface: gateway.chat, input: {prompt: hi}}}
  - {id: buffered, entry: {caller: browser, interface: gateway.buffered}}
scenarios:
  - id: sse
    flow: chat
    expect:
      - "result.value == {'text': 'Hello world', 'chunks': 3}"
      - "state.browser.chunks == ['Hel', 'lo', ' world']"
      - "state.gateway.sent.map(s, s.t) == [30, 40, 50]"
      - "trace.filter(e, e.type == 'yield').map(e, [e.t, e.output, e.index]) == [[30, 'Hel', 0], [40, 'lo', 1], [50, ' world', 2]]"
      - "trace.filter(e, e.type == 'call.start' && e.interface == 'browser.sse').map(e, e.t) == [30, 40, 50]"
      - "duration_ms == 50"
  - id: slow-consumer
    flow: chat
    config: {render-ms: 15}
    expect:
      - "result.ok"
      - "trace.filter(e, e.type == 'yield').map(e, e.t) == [30, 40, 50]"
      - "state.gateway.sent.map(s, s.t) == [45, 60, 75]"
      - "duration_ms == 75"
  - id: buffered
    flow: buffered
    expect:
      - "result.value == {'items': ['Hel', 'lo', ' world'], 'value': {'text': 'Hello world'}}"
      - "duration_ms == 50"
`

func TestStreams(t *testing.T) {
	doc := langDoc(t, streamDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

// Channels: a busy loop that blocks on receive until a request is put, a
// receive that times out, and a bounded channel that blocks its producer.
const channelDoc = `
components:
  - {id: client}
  - {id: api}
  - {id: engine, state: {initial: {done: []}}}
  - {id: producer, state: {initial: {put_at: []}}}
  - {id: consumer, state: {initial: {got: []}}}
interfaces:
  - component: engine
    name: loop
    latency_ms: 0
    behavior:
      - foreach: "= [1, 2, 3]"
        steps:
          - {receive: requests, as: req}
          - {wait: 5}
          - {set: {state.done: "= state.done + [{'id': vars.req.id, 't': now}]"}}
  - component: engine
    name: loop-timeout
    latency_ms: 0
    behavior:
      - receive: requests
        as: req
        timeout_ms: 30
        on_error: [{return: {stopped: "= error.code", at: "= now"}}]
      - {return: {got: "= vars.req"}}
  - component: api
    name: submit
    latency_ms: 1
    behavior:
      - {put: requests, value: {id: "= input.id"}}
      - {return: {queued: "= channel_len('requests')"}}
  - component: producer
    name: run
    latency_ms: 0
    behavior:
      - foreach: "= [1, 2, 3, 4]"
        steps:
          - {put: jobs, value: "= vars.item", capacity: 2, timeout_ms: "= input.timeout"}
          - {set: {state.put_at: "= state.put_at + [now]"}}
  - component: consumer
    name: run
    latency_ms: 0
    behavior:
      - foreach: "= [1, 2, 3, 4]"
        steps:
          - {wait: 10}
          - {receive: jobs, as: job}
          - {set: {state.got: "= state.got + [[vars.job, now]]"}}
flows:
  - {id: submit, entry: {caller: client, interface: api.submit}}
scenarios:
  - id: busy-loop
    steps:
      - {interface: engine.loop, caller: client, await: false, as: loop}
      - {interface: api.submit, caller: client, at_ms: 50, input: {id: a}}
      - {interface: api.submit, caller: client, at_ms: 100, input: {id: b}, as: b}
    expect:
      - "state.engine.done == [{'id': 'a', 't': 56}, {'id': 'b', 't': 106}]"
      - "trace.filter(e, e.type == 'receive').map(e, [e.t, e.output.id, e.wait_ms]) == [[51, 'a', 51], [101, 'b', 45]]"
      - "steps.b.result.value.queued == 0"
      - "result.ok"
      - "size(warnings) == 0"
      - "duration_ms == 106"
  - id: queued-first
    steps:
      - {interface: api.submit, caller: client, input: {id: a}, as: a}
      - {interface: api.submit, caller: client, input: {id: b}, as: b}
      - {interface: engine.loop, caller: client, at_ms: 10, await: false}
    expect:
      - "steps.a.result.value.queued == 1"
      - "steps.b.result.value.queued == 2"
      - "state.engine.done == [{'id': 'a', 't': 15}, {'id': 'b', 't': 20}]"
  - id: receive-timeout
    steps:
      - {interface: engine.loop-timeout, caller: client}
    expect:
      - "result.value == {'stopped': 'timeout', 'at': 30}"
      - "trace.exists(e, e.type == 'receive' && e.error.code == 'timeout' && e.t == 30)"
  - id: bounded
    steps:
      - {interface: consumer.run, caller: client, await: false}
      - {interface: producer.run, caller: client, input: {timeout: 0}}
    expect:
      - "state.producer.put_at == [0, 0, 10, 20]"
      - "state.consumer.got == [[1, 10], [2, 20], [3, 30], [4, 40]]"
      - "trace.filter(e, e.type == 'put').map(e, e.wait_ms) == [0, 0, 10, 10]"
      - "duration_ms == 40"
  - id: put-timeout
    steps:
      - {interface: producer.run, caller: client, input: {timeout: 5}}
    expect:
      - "result.error.code == 'timeout'"
      - "state.producer.put_at == [0, 0]"
      - "trace.exists(e, e.type == 'put' && e.error.code == 'timeout' && e.t == 5)"
`

func TestChannels(t *testing.T) {
	doc := langDoc(t, channelDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

// Kills: a worker killed mid-call (its caller gets peer-killed), a
// rendezvous with a killed peer, and a restart that revives the worker.
const killDoc = `
components:
  - {id: client}
  - {id: api}
  - {id: worker, state: {initial: {served: 0}}}
  - {id: store}
interfaces:
  - component: api
    name: handle
    latency_ms: 0
    behavior:
      - {call: worker.work, on: w1, as: r, on_error: [{return: {err: "= error.code", at: "= now"}}]}
      - {return: {ok: true, at: "= now"}}
  - component: api
    name: crash
    latency_ms: 0
    behavior:
      - {kill: {component: worker, instance: w1}}
  - component: api
    name: all-reduce
    latency_ms: 0
    behavior:
      - parallel: [w1, w2, w3]
        as: w
        steps:
          - {call: worker.reduce, on: "= vars.w", as: r, on_error: continue}
          - {return: "= vars.r.ok ? 'ok' : vars.r.error.code"}
        as_result: j
      - {return: "= vars.j.results.map(b, b.value)"}
  - component: worker
    name: work
    latency_ms: 10
    behavior:
      - {call: store.write}
      - {wait: 50}
      - {set: {state.served: "= state.served + 1"}}
      - {return: done}
  - component: worker
    name: reduce
    latency_ms: 0
    behavior:
      - {wait: "= self == 'w1' ? 5 : 1"}
      - {rendezvous: ar, count: 3, timeout_ms: 100}
  - component: store
    name: write
    latency_ms: 40
flows:
  - {id: handle, entry: {caller: client, interface: api.handle}}
  - {id: all-reduce, entry: {caller: client, interface: api.all-reduce}}
scenarios:
  - id: kill-mid-call
    flow: handle
    topology: {worker: [w1, w2]}
    faults: [{target: worker, type: kill, instance: w1, at_ms: 30}]
    expect:
      - "result.value == {'err': 'peer-killed', 'at': 30}"
      - "state['worker@w1'].dead && state['worker@w1'].served == 0"
      - "trace.exists(e, e.type == 'kill' && e.instance == 'w1' && e.t == 30 && e.output.failed == 1)"
      - "trace.exists(e, e.type == 'call.end' && e.interface == 'store.write' && e.error.code == 'killed' && e.t == 30)"
      - "trace.exists(e, e.type == 'call.end' && e.interface == 'worker.work' && e.error.code == 'killed' && e.t == 30)"
      - "duration_ms == 30"
  - id: dead-then-restart
    topology: {worker: [w1, w2]}
    steps:
      - {interface: api.crash, caller: client}
      - {flow: handle, as: dead}
      - {restart: {component: worker, instance: w1}}
      - {flow: handle, as: revived}
    expect:
      - "steps.dead.result.value.err == 'peer-killed'"
      - "steps.revived.result.value == {'ok': true, 'at': 100}"
      - "!has(state['worker@w1'].dead) && state['worker@w1'].served == 1"
      - "trace.exists(e, e.type == 'kill' && e.component == 'worker' && e.instance == 'w1')"
  - id: rendezvous-peer-killed
    flow: all-reduce
    topology: {worker: [w1, w2, w3]}
    faults: [{target: worker, type: kill, instance: w2, at_ms: 3}]
    expect:
      - "result.value == ['timeout', 'peer-killed', 'peer-killed']"
      - "trace.exists(e, e.type == 'rendezvous' && e.instance == 'w3' && e.error.code == 'peer-killed' && e.t == 3)"
      - "trace.exists(e, e.type == 'rendezvous' && e.instance == 'w1' && e.error.code == 'timeout' && e.t == 105)"
  - id: step-kill
    topology: {worker: [w1, w2]}
    steps:
      - {flow: handle, as: h, await: false}
      - {kill: {component: worker, instance: w1}, at_ms: 20}
    expect:
      - "steps.h.result.value == {'err': 'peer-killed', 'at': 20}"
`

func TestKills(t *testing.T) {
	doc := langDoc(t, killDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

// The CEL cost limit (§13.1 item 18): a prompt of 800 words, whose
// repeated words a behavior counts in O(n²), fits under the default limit
// of 10,000,000 but not under the old 1,000,000, which a scenario can set.
func TestLargePromptCostLimit(t *testing.T) {
	words := make([]string, 800)
	for i := range words {
		words[i] = fmt.Sprintf("w%d", i%400)
	}
	prompt, _ := json.Marshal(strings.Join(words, " "))
	doc := langDoc(t, `
components:
  - {id: client}
  - {id: tokenizer}
interfaces:
  - component: tokenizer
    name: encode
    latency_ms: "= 0.01 * double(size(input.prompt.split(' ')))"
    behavior:
      - {set: {vars.words: "= input.prompt.split(' ')"}}
      - return:
          tokens: "= size(vars.words)"
          repeated: "= size(vars.words.filter(w, vars.words.filter(x, x == w).size() > 1))"
flows:
  - {id: encode, entry: {caller: client, interface: tokenizer.encode}}
scenarios:
  - id: large-prompt
    flow: encode
    input: {prompt: `+string(prompt)+`}
    expect: ["result.value == {'tokens': 800, 'repeated': 800}"]
  - id: old-limit
    flow: encode
    cost_limit: 1000000
    input: {prompt: `+string(prompt)+`}
`)
	passes(t, doc, sim.Request{Scenario: "large-prompt"})
	res := run(t, doc, sim.Request{Scenario: "old-limit"})
	if res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, "cost limit") {
		t.Errorf("old limit: status %s, abort %q", res.Summary.Status, res.Summary.Abort)
	}
}

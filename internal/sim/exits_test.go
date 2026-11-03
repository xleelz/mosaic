package sim_test

import (
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §17 item 14: an instance's exit (a kill, or a restart of a live
// instance) delivers exit:<component>@<instance> to the waits on it, for
// every component of its group, carrying {component, instance, reason,
// at_us}. A wait on an instance already dead returns at once; a wait can
// name a set of signals.
const exitDoc = `
components:
  - {id: client}
  - {id: monitor}
  - {id: engine}
  - {id: worker, parent: engine}
interfaces:
  - component: monitor
    name: watch
    latency_ms: 0
    behavior:
      - wait: {signal: "= input.sig", timeout_ms: "= has(input.limit) ? input.limit : 1000", as: w, on_timeout: continue}
      - {return: "= {'reason': vars.w.reason, 'signal': has(vars.w.signal) ? vars.w.signal : '', 'data': has(vars.w.data) ? vars.w.data : {}, 'at': now}"}
  - component: monitor
    name: watch-any
    latency_ms: 0
    behavior:
      - wait: {signals: [exit:engine@e0, "= 'exit:engine@e1'"], as: w}
      - {return: "= {'signal': vars.w.signal, 'reason': vars.w.data.reason, 'at': now}"}
  - component: engine
    name: crash
    latency_ms: 0
    behavior:
      - {kill: {component: engine}}
flows:
  - {id: watch, entry: {caller: client, interface: monitor.watch}}
scenarios:
  - id: kill-wakes-monitor
    topology: {engine: [e0, e1]}
    steps:
      - {interface: monitor.watch, caller: client, input: {sig: exit:engine@e0}, as: m, await: false}
      - {interface: monitor.watch, caller: client, input: {sig: exit:worker@e0}, as: w, await: false}
      - {interface: monitor.watch, caller: client, input: {sig: exit:engine@e1, limit: 100}, as: other, await: false}
      - {kill: {component: engine, instance: e0}, at_ms: 30}
    expect:
      - "steps.m.result.value == {'reason': 'signal', 'signal': 'exit:engine@e0', 'data': {'component': 'engine', 'instance': 'e0', 'reason': 'killed', 'at_us': 30000}, 'at': 30}"
      - "steps.w.result.value.signal == 'exit:worker@e0' && steps.w.result.value.data.component == 'worker'"
      - "steps.other.result.value.reason == 'timeout'"
  - id: fault-kill-wakes-monitor
    topology: {engine: [e0]}
    flow: watch
    input: {sig: exit:engine@e0}
    faults: [{target: engine, type: kill, instance: e0, at_ms: 7}]
    expect:
      - "result.value.at == 7 && result.value.data.reason == 'killed'"
  - id: self-exit
    topology: {engine: [e0]}
    steps:
      - {interface: monitor.watch, caller: client, input: {sig: exit:engine@e0}, as: m, await: false}
      - {interface: engine.crash, caller: client, on: e0, at_ms: 12}
    expect:
      - "steps.m.result.value.at == 12"
  - id: already-dead
    topology: {engine: [e0]}
    steps:
      - {kill: {component: engine, instance: e0}}
      - {interface: monitor.watch, caller: client, input: {sig: exit:engine@e0}, as: m, at_ms: 50}
    expect:
      - "steps.m.result.value.reason == 'signal' && steps.m.result.value.at == 50 && steps.m.result.value.data.at_us == 0"
  - id: restart
    topology: {engine: [e0]}
    steps:
      - {interface: monitor.watch, caller: client, input: {sig: exit:engine@e0}, as: m, await: false}
      - {restart: {component: engine, instance: e0}, at_ms: 5}
      - {kill: {component: engine, instance: e0}, at_ms: 10}
      - {restart: {component: engine, instance: e0}, at_ms: 20}
      - {interface: monitor.watch, caller: client, input: {sig: exit:engine@e0, limit: 10}, as: after, at_ms: 30}
    expect:
      - "steps.m.result.value.data.reason == 'restarted' && steps.m.result.value.at == 5"
      - "steps.after.result.value.reason == 'timeout'"
  - id: signal-set
    topology: {engine: [e0, e1]}
    steps:
      - {interface: monitor.watch-any, caller: client, as: m, await: false}
      - {kill: {component: engine, instance: e1}, at_ms: 4}
    expect:
      - "steps.m.result.value == {'signal': 'exit:engine@e1', 'reason': 'killed', 'at': 4}"
      - "trace.exists(e, e.type == 'wait' && e.key == 'exit:engine@e1')"
`

func TestExitSignals(t *testing.T) {
	doc := langDoc(t, exitDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

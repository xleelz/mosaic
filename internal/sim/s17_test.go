package sim_test

import (
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §17 item 2: blocking waits, woken by state, channels and signals.
const blockingWaitDoc = `
components:
  - {id: client}
  - {id: proc, state: {initial: {zombies: []}}}
interfaces:
  - component: proc
    name: waitpid
    latency_ms: 0
    behavior:
      - wait: {until: "size(state.zombies) > 0", timeout_ms: 1000, as: w}
      - {return: {reason: "= vars.w.reason", at: "= now", pid: "= state.zombies[0]"}}
  - component: proc
    name: exit
    latency_ms: 0
    behavior:
      - {set: {state.zombies: "= state.zombies + [input.pid]"}}
  - component: proc
    name: sigwait
    latency_ms: 0
    behavior:
      - wait: {signal: SIGCHLD, timeout_ms: 500, as: w}
      - {return: {reason: "= vars.w.reason", signal: "= vars.w.signal", at: "= now"}}
  - component: proc
    name: raise
    latency_ms: 0
    behavior:
      - {signal: "= input.sig"}
  - component: proc
    name: patient
    latency_ms: 0
    behavior:
      - wait: {until: "size(state.zombies) > 0", timeout_ms: 100, on_timeout: continue, as: w}
      - {return: {reason: "= vars.w.reason", at: "= now"}}
  - component: proc
    name: strict
    latency_ms: 0
    behavior:
      - wait: {until: "size(state.zombies) > 0", timeout_ms: "= 40 + 10"}
      - {return: ok}
  - component: proc
    name: handled
    latency_ms: 0
    behavior:
      - wait: {signal: SIGUSR1, timeout_ms: 20, on_timeout: [{return: {timed_out: "= error.code"}}]}
      - {return: {timed_out: false}}
  - component: proc
    name: queue-two
    latency_ms: 0
    behavior:
      - wait: {until: "channel_len('q') >= 2", timeout_ms: 1000}
      - {return: {at: "= now"}}
  - component: proc
    name: push
    latency_ms: 0
    behavior:
      - {put: q, value: 1}
flows:
  - {id: waitpid, entry: {caller: client, interface: proc.waitpid}}
scenarios:
  - id: wakes-on-state
    steps:
      - {interface: proc.waitpid, caller: client, as: w, await: false}
      - {interface: proc.exit, caller: client, at_ms: 30, input: {pid: 101}}
    expect:
      - "steps.w.result.value == {'reason': 'until', 'at': 30, 'pid': 101}"
      - "trace.exists(e, e.type == 'wait' && e.output.reason == 'until' && e.wait_ms == 30)"
  - id: already-true
    state: {proc: {zombies: [7]}}
    flow: waitpid
    expect:
      - "result.value == {'reason': 'until', 'at': 0, 'pid': 7}"
  - id: wakes-on-signal
    steps:
      - {interface: proc.sigwait, caller: client, as: s, await: false}
      - {interface: proc.raise, caller: client, at_ms: 20, input: {sig: SIGTERM}}
      - {interface: proc.raise, caller: client, at_ms: 25, input: {sig: SIGCHLD}}
    expect:
      - "steps.s.result.value == {'reason': 'signal', 'signal': 'SIGCHLD', 'at': 25}"
      - "trace.filter(e, e.type == 'signal').map(e, e.output.woken) == [0, 1]"
  - id: timeout-continue
    steps:
      - {interface: proc.patient, caller: client, as: p}
    expect:
      - "steps.p.result.value == {'reason': 'timeout', 'at': 100}"
  - id: timeout-fails
    steps:
      - {interface: proc.strict, caller: client, as: s}
    expect:
      - "steps.s.status == 'error' && steps.s.result.error.code == 'timeout'"
      - "duration_ms == 50"
  - id: timeout-steps
    steps:
      - {interface: proc.handled, caller: client, as: h}
    expect:
      - "steps.h.result.value == {'timed_out': 'timeout'}"
  - id: wakes-on-channel
    steps:
      - {interface: proc.queue-two, caller: client, as: q, await: false}
      - {interface: proc.push, caller: client, at_ms: 10}
      - {interface: proc.push, caller: client, at_ms: 15.5}
    expect:
      - "steps.q.result.value == {'at': 15}"
      - "trace.exists(e, e.type == 'wait' && e.duration_us == 0 && e.t_us == 15500)"
`

func TestBlockingWait(t *testing.T) {
	doc := langDoc(t, blockingWaitDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

// DESIGN §17 item 3: the timers and emits of a blocked call tree are
// delivered on time. Before the fix, the fork's exit timer waited for the
// waitpid call to end, so the receive timed out at 1000 ms (and without a
// timeout it never returned).
const blockedTreeDoc = `
components:
  - {id: client}
  - {id: kernel, state: {initial: {zombies: [], log: []}}}
interfaces:
  - component: kernel
    name: spawn-and-waitpid
    latency_ms: 0
    behavior:
      - {emit: kernel.child-exit, input: {pid: 101}, after_ms: 50}
      - {receive: "wake:100", as: w, timeout_ms: 1000}
      - {return: {reaped: "= vars.w", at: "= now"}}
  - component: kernel
    name: spawn-and-waitpid-forever
    latency_ms: 0
    behavior:
      - {emit: kernel.child-exit, input: {pid: 102}, after_ms: 5}
      - {receive: "wake:100", as: w}
      - {return: {reaped: "= vars.w", at: "= now"}}
  - component: kernel
    name: fork-exec-wait
    latency_ms: 0
    behavior:
      - {emit: kernel.child-exit, input: {pid: 103}, after_ms: 0.25}
      - wait: {until: "size(state.zombies) > 0"}
      - {return: {reaped: "= state.zombies[0]", at_us: "= now_us"}}
  - component: kernel
    name: child-exit
    latency_ms: 0
    behavior:
      - {set: {state.zombies: "= state.zombies + [input.pid]"}}
      - {put: "wake:100", value: "= input.pid"}
  - component: kernel
    name: emit-then-sleep
    latency_ms: 0
    behavior:
      - {emit: kernel.note, input: {what: emitted}}
      - {wait: 100}
      - {set: {state.log: "= state.log + ['returned']"}}
  - component: kernel
    name: note
    latency_ms: 0
    behavior:
      - {set: {state.log: "= state.log + [input.what]"}}
flows:
  - {id: waitpid, entry: {caller: client, interface: kernel.spawn-and-waitpid}}
  - {id: forever, entry: {caller: client, interface: kernel.spawn-and-waitpid-forever}}
  - {id: wait, entry: {caller: client, interface: kernel.fork-exec-wait}}
  - {id: sleep, entry: {caller: client, interface: kernel.emit-then-sleep}}
scenarios:
  - id: receive-sees-own-timer
    flow: waitpid
    expect: ["result.value == {'reaped': 101, 'at': 50}"]
  - id: receive-forever-sees-own-timer
    flow: forever
    expect: ["result.value == {'reaped': 102, 'at': 5}"]
  - id: wait-sees-own-timer
    flow: wait
    expect: ["result.value == {'reaped': 103, 'at_us': 250}"]
  - id: running-tree-delivers-after
    flow: sleep
    expect: ["state.kernel.log == ['returned', 'emitted']"]
`

func TestTimersUnderBlockedTree(t *testing.T) {
	doc := langDoc(t, blockedTreeDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

// DESIGN §17 item 10: every duration_ms has an exact duration_us beside it
// (steps, vars, io, parallel results, the run, the trace); duration_ms
// stays whole milliseconds, rounded down.
const subMSDurationDoc = `
components:
  - {id: host}
  - {id: gpu}
interfaces:
  - {component: gpu, name: kernel, latency_ms: 0.125}
  - component: gpu
    name: launch
    latency_ms: 0
    behavior:
      - {call: gpu.kernel, as: k}
      - parallel: [1]
        steps: [{call: gpu.kernel}]
        as_result: j
      - {return: {k_ms: "= vars.k.duration_ms", k_us: "= vars.k.duration_us", j_us: "= vars.j.duration_us"}}
flows:
  - {id: launch, entry: {caller: host, interface: gpu.launch}}
scenarios:
  - id: sub-ms
    steps:
      - {flow: launch, as: l}
    expect:
      - "steps.l.duration_ms == 0 && steps.l.duration_us == 250"
      - "steps.l.result.value.k_ms == 0 && steps.l.result.value.k_us == 125 && steps.l.result.value.j_us == 125"
      - "io.exists(i, i.interface == 'gpu.launch' && i.duration_ms == 0 && i.duration_us == 250)"
      - "trace.exists(e, e.type == 'call.end' && e.interface == 'gpu.kernel' && e.duration_us == 125)"
      - "duration_ms == 0 && duration_us == 250"
`

func TestSubMillisecondDurationExact(t *testing.T) {
	doc := langDoc(t, subMSDurationDoc)
	res := passes(t, doc, sim.Request{Scenario: "sub-ms"})
	s := res.Summary
	if s.DurationMS != 0 || s.DurationUS == nil || *s.DurationUS != 250 {
		t.Errorf("summary duration %d ms, %v us", s.DurationMS, s.DurationUS)
	}
	if len(s.Steps) != 1 || s.Steps[0].DurationMS != 0 || s.Steps[0].DurationUS == nil || *s.Steps[0].DurationUS != 250 {
		t.Errorf("steps %+v", s.Steps)
	}
	for _, e := range res.Trace {
		if e.Type == "call.end" && e.Interface == "gpu.kernel" && (e.DurationMS != 0 || e.DurationUS == nil || *e.DurationUS != 125) {
			t.Errorf("kernel call.end %+v", e)
		}
	}
}

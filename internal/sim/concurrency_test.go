package sim_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §13.1 item 14: concurrency in time, on VS Code cases. The
// document uses tokens, so its runs are concurrent: steps with at_ms
// overlap, and parallel branches interleave.
const vscodeDoc = `
components:
  - {id: user}
  - id: window
  - {id: editor, parent: window, state: {initial: {version: 0, text: "", saves: []}}}
  - {id: backup, parent: window, state: {initial: {files: {}}}}
  - {id: search, state: {initial: {done: []}}}
  - {id: chat, state: {initial: {answers: {}, ran: []}}}
  - {id: pty, state: {initial: {connected: true, alive: true}}}
  - {id: ext-host, state: {initial: {log: []}}}
  - {id: keybindings, state: {initial: {context: {editorTextFocus: true, editorReadonly: false}}}}
  - {id: sessions, state: {initial: {sessions: {}}}}
interfaces:
  # Auto-save: each keystroke cancels the pending save timer and arms a new
  # one, 1000 ms later (a debounce).
  - component: editor
    name: type
    latency_ms: 0
    behavior:
      - {cancel: "= 'autosave-' + string(state.version)"}
      - {set: {state.version: "= state.version + 1", state.text: "= state.text + input.ch"}}
      - {set: {"= 'state.pending.v' + string(state.version)": "= now"}}
      - {call: backup.write, input: {uri: a.ts, text: "= state.text"}}
      - {emit: editor.save, after_ms: 1000, token: "= 'autosave-' + string(state.version)", input: {version: "= state.version"}}
  - component: editor
    name: save
    latency_ms: 5
    behavior:
      - {set: {state.saves: "= state.saves + [{'v': input.version, 'at': now}]"}}
  - component: backup
    name: write
    latency_ms: 1
    behavior:
      - {set: {"= 'state.files.' + replace(input.uri, '[.]', '_')": "= input.text"}}

  # A long-running search, bound to a token the user can cancel.
  - component: search
    name: run
    latency_ms: 0
    behavior:
      - {call: search.find, input: {q: "= input.q"}, token: "= 'search-' + input.q", as: r, on_error: continue}
      - {return: {ok: "= vars.r.ok", code: "= vars.r.ok ? '' : vars.r.error.code", canceled: "= canceled('search-' + input.q)"}}
  - component: search
    name: find
    latency_ms: 5000
    behavior:
      - {set: {state.done: "= state.done + [input.q]"}}
      - {return: {hits: 3}}

  # A tool call waits for the user's confirmation, which a later step gives.
  - component: chat
    name: invoke-tool
    latency_ms: 0
    behavior:
      - wait: 60000
        token: "= 'confirm-' + input.id"
        on_error:
          - if: "state.answers[input.id]"
            then:
              - {set: {state.ran: "= state.ran + [input.id]"}}
              - {return: {ran: true, at: "= now"}}
      - {fail: {code: not-confirmed}}
  - component: chat
    name: confirm
    latency_ms: 0
    behavior:
      - {set: {"= 'state.answers.' + input.id": "= input.approved"}}
      - {cancel: "= 'confirm-' + input.id"}

  # The pty host keeps a disconnected terminal for a grace period.
  - component: pty
    name: disconnect
    latency_ms: 0
    behavior:
      - {set: {state.connected: false}}
      - {emit: pty.grace-expired, after_ms: 5000, token: grace}
  - component: pty
    name: reconnect
    latency_ms: 0
    behavior:
      - {cancel: grace}
      - {set: {state.connected: true}}
  - component: pty
    name: grace-expired
    latency_ms: 0
    behavior:
      - {set: {state.alive: false}}

  # A window reload restarts its instance, keeping the backups.
  - component: window
    name: reload
    latency_ms: 0
    behavior:
      - {restart: {component: window, keep: [backup]}}

  # An extension host call that times out; the host still emits when done.
  - component: ext-host
    name: request
    latency_ms: 0
    behavior:
      - {call: ext-host.slow, timeout_ms: 100, on_error: continue}
  - component: ext-host
    name: slow
    latency_ms: 0
    behavior:
      - {wait: 500}
      - {emit: ext-host.notify}
  - component: ext-host
    name: notify
    latency_ms: 0
    behavior:
      - {set: {state.log: "= state.log + [now]"}}

  # when clauses are data, evaluated with eval.
  - component: keybindings
    name: resolve
    latency_ms: 0
    behavior:
      - {return: {enabled: "= eval(input.when, state.context)"}}

  # A dynamic set path keyed by session id.
  - component: sessions
    name: open
    latency_ms: 0
    behavior:
      - {set: {"= 'state.sessions.' + input.id": {open: true, at: "= now"}}}
      - {return: "= state.sessions[input.id]"}

  # Interleaved branches append to shared state in time order.
  - component: ext-host
    name: activate-all
    latency_ms: 0
    behavior:
      - parallel: [{n: slow, ms: 30}, {n: fast, ms: 10}]
        steps:
          - {wait: "= vars.item.ms"}
          - {set: {state.log: "= state.log + [vars.item.n]"}}
flows:
  - {id: type, entry: {caller: user, interface: editor.type, on: w1, input: {ch: x}}}
  - {id: search, entry: {caller: user, interface: search.run, input: {q: needle}}}
  - {id: tool, entry: {caller: user, interface: chat.invoke-tool, input: {id: t1}}}
  - {id: activate, entry: {caller: user, interface: ext-host.activate-all}}
scenarios:
  - id: auto-save-debounce
    topology: {window: [w1, w2]}
    steps:
      - {flow: type, input: {ch: a}}
      - {flow: type, at_ms: 500, input: {ch: b}}
    expect:
      - "size(state['editor@w1'].saves) == 1"
      - "state['editor@w1'].saves[0] == {'v': 2, 'at': 1506}"
      - "calls['editor.save'] == 1"
      - "trace.exists(e, e.type == 'cancel' && e.key == 'autosave-1' && e.output.pending == 1)"
      - "state['backup@w1'].files.a_ts == 'ab'"
      - "state['editor@w1'].pending == {'v1': 0, 'v2': 500}"
      - "duration_ms == 1506"
  - id: cancel-search
    steps:
      - {flow: search, as: s}
      - {cancel: search-needle, at_ms: 1000}
    expect:
      - "steps.s.result.value == {'ok': false, 'code': 'canceled', 'canceled': true}"
      - "steps.s.start_ms == 0 && steps.s.duration_ms == 1000"
      - "state.search.done == ['needle']"
      - "trace.exists(e, e.type == 'call.end' && e.interface == 'search.find' && e.late && e.t == 5000)"
      - "trace.exists(e, e.type == 'set' && e.interface == 'search.find' && e.late)"
      - "!trace.exists(e, e.type == 'call.end' && e.interface == 'search.run' && e.late)"
  - id: tool-confirmation
    steps:
      - {flow: tool, as: call, await: false}
      - {interface: chat.confirm, caller: user, at_ms: 2000, input: {id: t1, approved: true}}
    expect:
      - "steps.call.result.value == {'ran': true, 'at': 2000}"
      - "state.chat.ran == ['t1'] && state.chat.answers == {'t1': true}"
      - "duration_ms == 2000"
  - id: tool-unanswered
    max_virtual_ms: 10000
    steps:
      - {flow: tool, as: call}
    expect:
      - "steps.call.status == 'error'"
      - "warnings == ['the run stopped at max_virtual_ms 10000 with work still pending']"
  - id: pty-reconnect
    steps:
      - {interface: pty.disconnect, caller: user}
      - {interface: pty.reconnect, caller: user, at_ms: 2000}
    expect:
      - "state.pty == {'connected': true, 'alive': true}"
      - "calls['pty.grace-expired'] == 0"
      - "trace.exists(e, e.type == 'cancel' && e.key == 'grace' && e.output.pending == 1)"
  - id: pty-grace-expires
    steps:
      - {interface: pty.disconnect, caller: user}
      - {interface: pty.reconnect, caller: user, at_ms: 6000}
    expect:
      - "state.pty == {'connected': true, 'alive': false}"
      - "calls['pty.grace-expired'] == 1"
  - id: reload-window
    topology: {window: [w1, w2]}
    steps:
      - {flow: type, input: {ch: a}}
      - {interface: editor.type, caller: user, on: w2, input: {ch: z}, at_ms: 0}
      - {interface: window.reload, caller: user, on: w1, at_ms: 100}
    expect:
      - "state['editor@w1'] == {'version': 0, 'text': '', 'saves': []}"
      - "state['backup@w1'].files == {'a_ts': 'a'}"
      - "state['editor@w2'].text == 'z' && size(state['editor@w2'].saves) == 1"
      - "calls_by_instance['editor.save@w1'] == 0"
      - "trace.exists(e, e.type == 'restart' && e.instance == 'w1' && e.output.reset == ['editor@w1'] && e.output.kept == ['backup'] && e.output.dropped == 1)"
  - id: restart-step
    topology: {window: [w1, w2]}
    steps:
      - {flow: type, input: {ch: a}}
      - {restart: {component: editor, instance: w1, keep: [backup]}, at_ms: 10}
    expect:
      - "state['editor@w1'].text == '' && state['backup@w1'].files.a_ts == 'a'"
      - "calls['editor.save'] == 0"
  - id: late-emit
    steps:
      - {interface: ext-host.request, caller: user}
    expect:
      - "state['ext-host'].log == [500]"
      - "trace.exists(e, e.type == 'call.end' && e.interface == 'ext-host.slow' && e.late && e.t == 500)"
  - id: when-clause
    steps:
      - {interface: keybindings.resolve, caller: user, input: {when: "editorTextFocus && !editorReadonly"}, as: on}
      - {interface: keybindings.resolve, caller: user, input: {when: "editorTextFocus && editorReadonly"}, as: off}
    expect: ["steps.on.result.value.enabled", "!steps.off.result.value.enabled"]
  - id: dynamic-set
    steps:
      - {interface: sessions.open, caller: user, at_ms: 7, input: {id: s-1}}
    expect:
      - "state.sessions.sessions == {'s-1': {'open': true, 'at': 7}}"
      - "trace.exists(e, e.type == 'set' && e.interface == 'sessions.open')"
  - id: interleave
    flow: activate
    expect:
      - "state['ext-host'].log == ['fast', 'slow']"
      - "duration_ms == 30"
`

func TestConcurrencyVSCodeCases(t *testing.T) {
	doc := langDoc(t, vscodeDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			res := passes(t, doc, sim.Request{Scenario: sc.ID})
			again := run(t, doc, sim.Request{Scenario: sc.ID})
			a, _ := json.Marshal(res)
			b, _ := json.Marshal(again)
			if string(a) != string(b) {
				t.Error("two runs differ")
			}
		})
	}
}

// TestLateEmitTiming: an emit made by a callee that finishes after its
// caller's timeout is delivered at the callee's end, in sequential runs
// too.
func TestLateEmitTiming(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: user}
  - {id: svc, state: {initial: {log: []}}}
interfaces:
  - component: svc
    name: request
    latency_ms: 0
    behavior:
      - {call: svc.slow, timeout_ms: 100, on_error: continue}
      - {set: {state.log: "= state.log + ['caller ' + string(now)]"}}
  - component: svc
    name: slow
    latency_ms: 0
    behavior:
      - {wait: 500}
      - {emit: svc.notify}
  - component: svc
    name: notify
    latency_ms: 0
    behavior:
      - {set: {state.log: "= state.log + ['notify ' + string(now)]"}}
flows:
  - {id: request, entry: {caller: user, interface: svc.request}}
`)
	res := passes(t, doc, sim.Request{Flow: "request", Expect: []string{
		"state.svc.log == ['caller 100', 'notify 500']", "duration_ms == 500",
	}})
	if s := eventsFor(res, "call.start", "svc.notify"); len(s) != 1 || s[0].T != 500 {
		t.Errorf("notify starts %+v", s)
	}
}

// TestStepWaitsForEmitsInConcurrentRuns: one unrelated cancellation token
// makes every run of the document concurrent, but a step without at_ms
// still waits for the previous step's emits and timers, so a read-back
// step sees what they wrote. Only at_ms and await: false overlap steps.
func TestStepWaitsForEmitsInConcurrentRuns(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: user}
  - {id: files, state: {initial: {dirty: false}}}
  - {id: other}
interfaces:
  - component: files
    name: change
    latency_ms: 0
    behavior:
      - {emit: files.mark-dirty, after_ms: 50}
  - component: files
    name: mark-dirty
    latency_ms: 0
    behavior: [{set: {state.dirty: true}}]
  - component: files
    name: read
    latency_ms: 0
    behavior: [{return: {dirty: "= state.dirty"}}]
  - component: other
    name: unrelated
    latency_ms: 0
    behavior:
      - {emit: other.noop, after_ms: 10, token: t}
      - {cancel: t}
  - {component: other, name: noop, latency_ms: 0}
scenarios:
  - id: waits
    steps:
      - {interface: files.change, caller: user}
      - {interface: files.read, caller: user, as: r}
    expect: ["steps.r.result.value.dirty", "duration_ms == 50"]
  - id: at-ms-overlaps
    steps:
      - {interface: files.change, caller: user}
      - {interface: files.read, caller: user, as: r, at_ms: 0}
    expect: ["!steps.r.result.value.dirty", "state.files.dirty"]
  - id: await-false-overlaps
    steps:
      - {interface: files.change, caller: user, await: false}
      - {interface: files.read, caller: user, as: r}
    expect: ["!steps.r.result.value.dirty", "state.files.dirty"]
`)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) { passes(t, doc, sim.Request{Scenario: sc.ID}) })
	}
}

// TestSequentialRunsUnchanged:a document with no item-14 feature keeps
// sequential parallel branches (each sees the state earlier ones left).
func TestSequentialRunsUnchanged(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: user}
  - {id: host, state: {initial: {log: []}}}
interfaces:
  - component: host
    name: all
    latency_ms: 0
    behavior:
      - parallel: [{n: slow, ms: 30}, {n: fast, ms: 10}]
        steps:
          - {wait: "= vars.item.ms"}
          - {set: {state.log: "= state.log + [vars.item.n]"}}
flows:
  - {id: all, entry: {caller: user, interface: host.all}}
scenarios:
  - id: sequential
    flow: all
    expect: ["state.host.log == ['slow', 'fast']", "duration_ms == 30"]
  - id: concurrent
    flow: all
    max_virtual_ms: 60000
    expect: ["state.host.log == ['fast', 'slow']", "duration_ms == 30"]
`)
	passes(t, doc, sim.Request{Scenario: "sequential"})
	passes(t, doc, sim.Request{Scenario: "concurrent"})
}

// TestParallelDocsConcurrent runs the §11.2 test documents as concurrent
// runs (max_virtual_ms opts a scenario in): their joins, fail-fast rules,
// on_late work and timings hold with interleaved branches.
func TestParallelDocsConcurrent(t *testing.T) {
	limit := int64(600000)
	for name, src := range map[string]string{
		"quorum":    quorumDoc,
		"allreduce": allReduceDoc,
		"onlate":    onLateDoc,
		"failfast":  strings.Replace(failFastDoc, "JOIN", "join: {need: 2, count_unstarted: false}", 1),
		"waits":     strings.Replace(failFastDoc, "JOIN", "join: {need: 2}", 1),
	} {
		t.Run(name, func(t *testing.T) {
			doc := langDoc(t, src)
			for i := range doc.Scenarios {
				doc.Scenarios[i].MaxVirtualMS = &limit
			}
			for _, sc := range doc.Scenarios {
				if name == "failfast" && sc.ID != "fail-fast" || name == "waits" && sc.ID != "default-waits" {
					continue
				}
				res := run(t, doc, sim.Request{Scenario: sc.ID})
				for _, a := range res.Summary.Assertions {
					// The as_result of a branch still running at the join
					// has no outcome yet in a concurrent run.
					if !a.Passed && !strings.Contains(a.Expr, "r.late) == [false, false, true]") {
						t.Errorf("%s: failed: %s %s", sc.ID, a.Expr, a.Error)
					}
				}
			}
		})
	}
}

// TestCapacityConcurrent: concurrent branches queue for a single-threaded
// extension host in arrival order; queue_limit and queue_timeout_ms refuse.
func TestCapacityConcurrent(t *testing.T) {
	src := `
components:
  - {id: window}
  - {id: ext-host, capacity: {concurrency: 1CAP}}
interfaces:
  - component: window
    name: activate-all
    latency_ms: 0
    behavior:
      - parallel: [git, python, eslint]
        steps: [{call: ext-host.activate, input: {ext: "= vars.item"}}]
        as_result: acts
      - {return: "= vars.acts"}
  - component: ext-host
    name: activate
    latency_ms: 100
    behavior:
      - {call: ext-host.register}
  - {component: ext-host, name: register, latency_ms: 0}
flows:
  - {id: activate, entry: {caller: window, interface: window.activate-all}}
scenarios:
  - {id: s, flow: activate, max_virtual_ms: 100000}
`
	doc := langDoc(t, strings.Replace(src, "CAP", "", 1))
	res := run(t, doc, sim.Request{Scenario: "s"})
	s := res.Summary
	if !s.Result.OK || s.DurationMS != 300 || s.Queued != 2 {
		t.Fatalf("result %+v, duration %d, queued %d", s.Result, s.DurationMS, s.Queued)
	}
	var waits []int64
	for _, e := range events(res, "queue") {
		waits = append(waits, e.WaitMS)
	}
	eq(t, "waits", waits, []int64{100, 200})

	byBranch := func(res *sim.Result) map[int]sim.Event {
		out := map[int]sim.Event{}
		for _, e := range eventsFor(res, "call.end", "ext-host.activate") {
			out[*e.Branch] = e
		}
		return out
	}
	doc = langDoc(t, strings.Replace(src, "CAP", ", queue_limit: 1", 1))
	res = run(t, doc, sim.Request{Scenario: "s"})
	if e := res.Summary.Result.Error; e == nil || e.Code != "insufficient" {
		t.Fatalf("result %+v", res.Summary.Result)
	}
	if e := byBranch(res)[2]; e.Error == nil || e.Error.Code != "overloaded" || e.T != 0 {
		t.Errorf("third activation should be refused at once: %+v", e)
	}

	doc = langDoc(t, strings.Replace(src, "CAP", ", queue_timeout_ms: 150", 1))
	res = run(t, doc, sim.Request{Scenario: "s"})
	ends := byBranch(res)
	if e := ends[2]; e.Error == nil || e.Error.Code != "overloaded" || e.T != 150 {
		t.Errorf("third activation should give up at 150: %+v", e)
	}
	if e := ends[1]; e.Error != nil || e.T != 200 {
		t.Errorf("second activation should run 100-200: %+v", e)
	}
}

// TestRestartCancelsRunningWork: a restart cancels a call in progress on
// the instance, and an abort or the limit ends a run with tasks pending.
func TestRestartCancelsRunningWork(t *testing.T) {
	doc := langDoc(t, `
components:
  - {id: user}
  - {id: window}
  - {id: indexer, parent: window, state: {initial: {done: 0}}}
interfaces:
  - component: indexer
    name: index
    latency_ms: 1000
    behavior:
      - {set: {state.done: "= state.done + 1"}}
  - component: window
    name: loop
    latency_ms: 0
    behavior:
      - foreach: "= lists.range(100000)"
        max: 1000
        steps: [{set: {vars.x: "= vars.index"}}]
scenarios:
  - id: restart
    topology: {window: [w1]}
    steps:
      - {interface: indexer.index, caller: user, as: idx}
      - {restart: {component: window, instance: w1}, at_ms: 10}
    expect:
      - "steps.idx.status == 'error' && steps.idx.result.error.code == 'canceled'"
      - "state['indexer@w1'].done == 0"
      - "trace.exists(e, e.type == 'restart' && e.output.canceled == 1)"
  - id: abort
    steps:
      - {interface: indexer.index, caller: user, await: false}
      - {interface: window.loop, caller: user}
      - {interface: window.loop, caller: user}
`)
	passes(t, doc, sim.Request{Scenario: "restart"})
	res, err := sim.RunWithLimits(doc, sim.Request{Scenario: "abort"}, sim.Limits{MaxEvents: 1500, MaxDepth: 64, MaxEmits: 1000})
	if err != nil {
		t.Fatal(err)
	}
	if res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, "event budget") {
		t.Errorf("status %s abort %q", res.Summary.Status, res.Summary.Abort)
	}
}

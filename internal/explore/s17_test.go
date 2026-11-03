package explore_test

import (
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/explore"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §17 item 4: GPU-scale overlap. Two kernels on different streams
// read a shared counter, run 0.3 ms, and write it back; the second starts
// 0.4 ms after the first, so by default they never overlap. A sub-ms
// jitter (0.25 ms) overlaps them; whole-ms points could not tell these
// orderings apart.
const gpuDoc = `
id: gpu
components:
  - {id: host}
  - {id: gpu, state: {initial: {n: 0}}}
  - {id: sm}
interfaces:
  - {component: sm, name: run, latency_ms: 0.3}
  - component: gpu
    name: kernel
    latency_ms: 0
    behavior:
      - {set: {vars.n: "= state.n"}}
      - {call: sm.run}
      - {set: {state.n: "= vars.n + 1"}}
flows:
  - {id: k, entry: {caller: host, interface: gpu.kernel}}
scenarios:
  - id: streams-overlap
    tags: [race, gpu]
    max_virtual_ms: 100
    steps:
      - {interface: gpu.kernel, caller: host, at_ms: 1.1}
      - {interface: gpu.kernel, caller: host, at_ms: 1.5}
    expect: ["state.gpu.n == 2"]
`

func TestSubMillisecondJitter(t *testing.T) {
	doc := parse(t, gpuDoc)
	rep, err := explore.Explore(doc, "streams-overlap", explore.Options{Schedules: 50})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure != nil {
		t.Fatalf("without jitter the kernels never overlap: %+v", rep.Failure)
	}
	rep, err = explore.Explore(doc, "streams-overlap", explore.Options{Schedules: 50, JitterMS: 0.25})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure == nil {
		t.Fatalf("a 0.25 ms jitter should overlap the kernels: %+v", rep)
	}
	if rep.Failure.JitterMS != 0.25 {
		t.Errorf("the replay records jitter %v", rep.Failure.JitterMS)
	}
	sub := false
	for _, p := range rep.Failure.Points {
		if p.Kind == sim.PointJitter && strings.Contains(p.Label, "1.35") {
			sub = true
		}
	}
	if !sub {
		t.Errorf("expected sub-millisecond jitter alternatives: %+v", rep.Failure.Points)
	}
	got, div, err := explore.Run(doc, rep.Failure, sim.Limits{})
	if err != nil || div != "" || got.Summary.Passed {
		t.Fatalf("replay: err %v, diverged %q, passed %v", err, div, got.Summary.Passed)
	}
}

// DESIGN §17 item 11: steps in one lane keep their program order under
// exploration, even with await: false and equal start times; steps in
// different lanes are reordered as ties.
const laneDoc = `
id: lanes
components:
  - {id: host}
  - {id: gpu, state: {initial: {log: []}}}
interfaces:
  - component: gpu
    name: enqueue
    latency_ms: 0
    behavior:
      - {set: {state.log: "= state.log + [input.op]"}}
flows:
  - {id: q, entry: {caller: host, interface: gpu.enqueue}}
scenarios:
  - id: one-lane
    steps:
      - {interface: gpu.enqueue, caller: host, input: {op: copy}, await: false, lane: host}
      - {interface: gpu.enqueue, caller: host, input: {op: kernel}, await: false, lane: host}
    expect: ["state.gpu.log == ['copy', 'kernel']"]
  - id: two-lanes
    steps:
      - {interface: gpu.enqueue, caller: host, input: {op: copy}, await: false, lane: a}
      - {interface: gpu.enqueue, caller: host, input: {op: kernel}, await: false, lane: b}
    expect: ["state.gpu.log == ['copy', 'kernel']"]
  - id: no-lane
    steps:
      - {interface: gpu.enqueue, caller: host, input: {op: copy}, await: false}
      - {interface: gpu.enqueue, caller: host, input: {op: kernel}, await: false}
    expect: ["state.gpu.log == ['copy', 'kernel']"]
`

func TestLaneKeepsProgramOrder(t *testing.T) {
	doc := parse(t, laneDoc)
	rep, err := explore.Explore(doc, "one-lane", explore.Options{Schedules: 50, JitterMS: 0.5})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure != nil || !rep.Exhausted {
		t.Fatalf("one lane must keep its order: failure %+v, exhausted %v", rep.Failure, rep.Exhausted)
	}
	for _, sc := range []string{"two-lanes", "no-lane"} {
		rep, err := explore.Explore(doc, sc, explore.Options{Schedules: 50})
		if err != nil {
			t.Fatal(err)
		}
		if rep.Failure == nil || rep.DefaultFailed {
			t.Fatalf("%s: the steps should be reordered as a tie: %+v", sc, rep)
		}
		got, div, err := explore.Run(doc, rep.Failure, sim.Limits{})
		if err != nil || div != "" || got.Summary.Passed {
			t.Fatalf("%s replay: err %v, diverged %q, passed %v", sc, err, div, got.Summary.Passed)
		}
	}
}

func TestLaneValidation(t *testing.T) {
	doc := parse(t, laneDoc+`
  - id: bad-lane
    steps:
      - {interface: gpu.enqueue, caller: host, lane: "Not A Lane"}
      - {cancel: tok, lane: host}
`)
	var msgs []string
	for _, is := range model.Validate(doc) {
		msgs = append(msgs, is.Path+": "+is.Message)
	}
	all := strings.Join(msgs, "\n")
	if !strings.Contains(all, "invalid lane name") || !strings.Contains(all, "lane goes with a flow or interface step") {
		t.Fatalf("lane validation: %s", all)
	}
}

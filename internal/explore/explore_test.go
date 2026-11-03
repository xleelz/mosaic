package explore_test

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/xleelz/mosaic/internal/explore"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// Two writers bump a counter with a read, a 2 ms call and a write. The
// second starts at 2 ms, when the first resumes: the default tie-break
// resumes the first writer before the second starts (so the second reads
// 1 and the run passes), but the other order loses an update. bump-if
// fences the write with a condition on the value read, so whichever order
// runs, the counter equals the successful bumps.
const raceDoc = `
id: race
components:
  - {id: user}
  - {id: counter, state: {initial: {n: 0}}}
  - {id: db}
  - {id: audit, state: {initial: {log: []}}}
interfaces:
  - {component: db, name: slow, latency_ms: 2}
  - component: counter
    name: bump
    latency_ms: 0
    behavior:
      - {set: {vars.n: "= state.n"}}
      - {call: db.slow}
      - {set: {state.n: "= vars.n + 1"}}
  - component: counter
    name: bump-if
    latency_ms: 0
    behavior:
      - {set: {vars.n: "= state.n"}}
      - {call: db.slow}
      - if: "state.n == vars.n"
        then:
          - {set: {state.n: "= vars.n + 1"}}
          - {return: {ok: true}}
      - {fail: {code: conflict}}
  - component: audit
    name: note
    latency_ms: 0
    behavior:
      - {call: db.slow}
      - {set: {state.log: "= state.log + [input.what]"}}
scenarios:
  - id: race-lost-update
    max_virtual_ms: 1000
    steps:
      - {interface: counter.bump, caller: user}
      - {interface: counter.bump, caller: user, at_ms: 2}
    expect: ["state.counter.n == 2"]
  - id: race-jitter
    max_virtual_ms: 1000
    steps:
      - {interface: counter.bump, caller: user}
      - {interface: counter.bump, caller: user, at_ms: 3}
    expect: ["state.counter.n == 2"]
  - id: fenced-update
    max_virtual_ms: 1000
    steps:
      - {interface: counter.bump-if, caller: user, as: a}
      - {interface: counter.bump-if, caller: user, at_ms: 2, as: b}
      - {interface: counter.bump-if, caller: user, at_ms: 2, as: c}
    expect:
      - "state.counter.n == (steps.a.result.ok ? 1 : 0) + (steps.b.result.ok ? 1 : 0) + (steps.c.result.ok ? 1 : 0)"
      - "state.counter.n >= 1"
  - id: disjoint
    max_virtual_ms: 1000
    steps:
      - {interface: audit.note, caller: user, input: {what: a}}
      - {interface: counter.bump, caller: user, at_ms: 2}
    expect: ["state.counter.n == 1", "state.audit.log == ['a']"]
`

func parse(t *testing.T, src string) *model.Document {
	t.Helper()
	doc, err := model.ParseDocument([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	return doc
}

func TestRaceFoundAndReplayed(t *testing.T) {
	doc := parse(t, raceDoc)
	res, err := sim.Run(doc, sim.Request{Scenario: "race-lost-update"})
	if err != nil {
		t.Fatal(err)
	}
	if !res.Summary.Passed {
		t.Fatalf("the default schedule should pass: %+v", res.Summary.Assertions)
	}
	rep, err := explore.Explore(doc, "race-lost-update", explore.Options{Schedules: 8})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure == nil || rep.DefaultFailed {
		t.Fatalf("exploration should find the lost update in 8 schedules: %+v", rep)
	}
	if rep.Runs > 4 {
		t.Errorf("found after %d schedules; the reduction should need few", rep.Runs)
	}
	path := filepath.Join(t.TempDir(), "race.replay.json")
	if err := rep.Failure.Write(path); err != nil {
		t.Fatal(err)
	}
	rp, err := explore.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		got, div, err := explore.Run(doc, rp, sim.Limits{})
		if err != nil {
			t.Fatal(err)
		}
		if div != "" {
			t.Fatalf("replay diverged: %s", div)
		}
		if got.Summary.Passed || got.Summary.State["counter"]["n"] != int64(1) {
			t.Fatalf("the replay should lose an update: passed %v, state %v", got.Summary.Passed, got.Summary.State["counter"])
		}
	}
}

func TestJitterFindsRace(t *testing.T) {
	doc := parse(t, raceDoc)
	rep, err := explore.Explore(doc, "race-jitter", explore.Options{Schedules: 20})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure != nil {
		t.Fatalf("without jitter the writers never overlap: %+v", rep.Failure)
	}
	rep, err = explore.Explore(doc, "race-jitter", explore.Options{Schedules: 20, JitterMS: 2})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure == nil {
		t.Fatalf("jitter of 2 ms should overlap the writers: %+v", rep)
	}
	got, div, err := explore.Run(doc, rep.Failure, sim.Limits{})
	if err != nil || div != "" || got.Summary.Passed {
		t.Fatalf("replay: err %v, diverged %q, passed %v", err, div, got.Summary.Passed)
	}
}

func TestFencedPassesEverySchedule(t *testing.T) {
	doc := parse(t, raceDoc)
	rep, err := explore.Explore(doc, "fenced-update", explore.Options{Schedules: 500, JitterMS: 2})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure != nil {
		t.Fatalf("the conditional write should hold under every schedule: %+v", rep.Failure)
	}
	if !rep.Exhausted {
		t.Fatalf("the search should exhaust the schedules within 500 runs (ran %d)", rep.Runs)
	}
	if rep.Runs < 3 {
		t.Errorf("only %d schedules ran", rep.Runs)
	}
}

func TestReductionSkipsDisjointWork(t *testing.T) {
	doc := parse(t, raceDoc)
	rep, err := explore.Explore(doc, "disjoint", explore.Options{Schedules: 50})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure != nil || !rep.Exhausted {
		t.Fatalf("disjoint writers: %+v", rep)
	}
	if rep.Runs != 1 || rep.Coverage.Pruned == 0 {
		t.Errorf("work on disjoint components should commute: %d runs, %d pruned", rep.Runs, rep.Coverage.Pruned)
	}
}

// A run whose schedule takes every default matches a run without one.
func TestDefaultScheduleIdentical(t *testing.T) {
	docs := map[string]*model.Document{"race": parse(t, raceDoc)}
	if data, err := os.ReadFile("../../examples/language-demo/ontology.yaml"); err == nil {
		d, err := model.ParseDocument(data)
		if err != nil {
			t.Fatal(err)
		}
		docs["demo"] = d
	}
	for name, doc := range docs {
		for _, sc := range doc.Scenarios {
			plain, err1 := sim.Run(doc, sim.Request{Scenario: sc.ID})
			sch := &sim.Schedule{}
			with, err2 := sim.Run(doc, sim.Request{Scenario: sc.ID, Schedule: sch})
			if (err1 == nil) != (err2 == nil) {
				t.Fatalf("%s/%s: errors differ: %v vs %v", name, sc.ID, err1, err2)
			}
			if err1 != nil {
				continue
			}
			a, _ := json.Marshal(plain)
			b, _ := json.Marshal(with)
			if !bytes.Equal(a, b) {
				t.Errorf("%s/%s: a default schedule changed the run", name, sc.ID)
			}
		}
	}
}

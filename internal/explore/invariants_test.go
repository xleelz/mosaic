package explore_test

import (
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/explore"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// Two workers race for one lease (DESIGN §16.2). Each waits 2 ms on the
// database and then takes the lease; they resume at the same time, so the
// tie-break picks the winner. lock.acquire fences the write (if_absent);
// the broken worker peeks, waits, and then writes without a condition.
const lockDoc = `
id: lockrace
components:
  - {id: user}
  - {id: worker}
  - {id: db}
  - {id: lock}
interfaces:
  - {component: db, name: slow, latency_ms: 2}
  - component: lock
    name: acquire
    latency_ms: 0
    errors: [{code: taken, status: 409}]
    store: {table: leases, op: put, key: job, value: "= input", if_absent: true, conflict: taken}
  - component: lock
    name: peek
    latency_ms: 0
    store: {table: leases, op: get, key: job, default: {free: true}}
  - component: lock
    name: put
    latency_ms: 0
    store: {table: leases, op: put, key: job, value: "= input"}
  - component: worker
    name: run
    latency_ms: 0
    behavior:
      - {call: db.slow}
      - {call: lock.acquire, input: {owner: "= input.owner"}}
  - component: worker
    name: run-broken
    latency_ms: 0
    behavior:
      - {call: lock.peek, as: seen}
      - {call: db.slow}
      - if: "has(vars.seen.value.free)"
        then:
          - {call: lock.put, input: {owner: "= input.owner"}}
          - {return: {won: true}}
      - {fail: {code: taken, status: 409}}
  - component: worker
    name: look
    latency_ms: 0
    behavior:
      - {call: db.slow}
      - {call: lock.peek}
scenarios:
  - id: race-lease
    max_virtual_ms: 1000
    steps:
      - {interface: worker.run, caller: user, input: {owner: a}, at_ms: 0, as: a}
      - {interface: worker.run, caller: user, input: {owner: b}, at_ms: 0, as: b}
    invariants:
      - "exactlyOne([steps.a.result.ok, steps.b.result.ok])"
      - "state.lock.leases.job.owner == (steps.a.result.ok ? 'a' : 'b')"
    expect: ["steps.a.result.ok"]
  - id: race-lease-no-invariants
    max_virtual_ms: 1000
    steps:
      - {interface: worker.run, caller: user, input: {owner: a}, at_ms: 0, as: a}
      - {interface: worker.run, caller: user, input: {owner: b}, at_ms: 0, as: b}
    expect: ["steps.a.result.ok", "!steps.b.result.ok"]
  - id: race-lease-broken
    max_virtual_ms: 1000
    steps:
      - {interface: worker.run-broken, caller: user, input: {owner: a}, at_ms: 0, as: a}
      - {interface: worker.run-broken, caller: user, input: {owner: b}, at_ms: 2, as: b}
    invariants:
      - "exactlyOne([steps.a.result.ok, steps.b.result.ok])"
    expect: ["steps.a.result.ok"]
  - id: readers
    max_virtual_ms: 1000
    state: {lock: {leases: {job: {owner: z}}}}
    steps:
      - {interface: worker.look, caller: user, at_ms: 0, as: a}
      - {interface: worker.look, caller: user, at_ms: 0, as: b}
    expect: ["steps.a.result.ok && steps.b.result.ok"]
`

func TestInvariantHoldsWhileExpectNamesWinner(t *testing.T) {
	doc := parse(t, lockDoc)
	res, err := sim.Run(doc, sim.Request{Scenario: "race-lease"})
	if err != nil {
		t.Fatal(err)
	}
	if !res.Summary.Passed {
		t.Fatalf("the default schedule should pass: %+v", res.Summary.Assertions)
	}
	inv := 0
	for _, a := range res.Summary.Assertions {
		if a.Invariant {
			inv++
		}
	}
	if inv != 2 || len(res.Summary.Assertions) != 3 {
		t.Fatalf("want 1 expectation and 2 invariants: %+v", res.Summary.Assertions)
	}
	rep, err := explore.Explore(doc, "race-lease", explore.Options{Schedules: 50})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure != nil || !rep.Exhausted || !rep.Invariants {
		t.Fatalf("the invariants should hold under every schedule: %+v %+v", rep, rep.Failure)
	}
	if rep.Runs < 2 || rep.Coverage.Tried == 0 {
		t.Fatalf("the winner's tie should be explored: %+v", rep)
	}
	// Without invariants, the same race fails on its expect: the other
	// schedule lets b win.
	rep, err = explore.Explore(doc, "race-lease-no-invariants", explore.Options{Schedules: 50})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure == nil || rep.DefaultFailed || rep.Invariants {
		t.Fatalf("which writer wins should fail off the default schedule: %+v", rep)
	}
	// The replay of a non-default schedule of an invariant scenario is
	// held to the invariants only.
	got, div, err := explore.Run(doc, &explore.Replay{Scenario: "race-lease", Decisions: rep.Failure.Decisions}, sim.Limits{})
	if err != nil || div != "" {
		t.Fatalf("replay: %v %q", err, div)
	}
	if got.Summary.Passed {
		t.Fatalf("under the other order the expectation that a wins fails")
	}
	if bad := explore.Failures(got, &explore.Replay{Decisions: rep.Failure.Decisions}); bad != nil {
		t.Fatalf("the invariants hold under the replay: %v", bad)
	}
}

func TestBrokenFenceViolatesInvariant(t *testing.T) {
	doc := parse(t, lockDoc)
	res, err := sim.Run(doc, sim.Request{Scenario: "race-lease-broken"})
	if err != nil {
		t.Fatal(err)
	}
	if !res.Summary.Passed {
		t.Fatalf("the default schedule hides the race: %+v", res.Summary.Assertions)
	}
	rep, err := explore.Explore(doc, "race-lease-broken", explore.Options{Schedules: 20})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure == nil || rep.DefaultFailed {
		t.Fatalf("exploration should break the fence: %+v", rep)
	}
	if len(rep.Failure.Failed) != 1 || !strings.HasPrefix(rep.Failure.Failed[0], "invariant exactlyOne(") {
		t.Fatalf("the invariant should be what fails: %v", rep.Failure.Failed)
	}
	got, div, err := explore.Run(doc, rep.Failure, sim.Limits{})
	if err != nil || div != "" || explore.Failures(got, rep.Failure) == nil {
		t.Fatalf("the replay should violate the invariant: %v %q", err, div)
	}
}

func TestCoverageCounts(t *testing.T) {
	doc := parse(t, lockDoc)
	rep, err := explore.Explore(doc, "race-lease", explore.Options{Schedules: 50})
	if err != nil {
		t.Fatal(err)
	}
	c := rep.Coverage
	if c.Points == 0 || c.Alternatives != c.Tried+c.Pruned+c.Untried || c.Tried != rep.Runs-1 || c.Untried != 0 {
		t.Fatalf("coverage doesn't add up: %+v (%d runs)", c, rep.Runs)
	}
	if c.ByKind["tie"] == nil || c.ByKind["tie"].Tried == 0 {
		t.Fatalf("the tie should be tried: %s", c)
	}
	if !strings.Contains(c.String(), "choice points") {
		t.Fatalf("String: %s", c)
	}
	// A budget of one leaves the kept alternatives untried.
	rep, err = explore.Explore(doc, "race-lease", explore.Options{Schedules: 1})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Exhausted || rep.Coverage.Untried == 0 || rep.Coverage.Tried != 0 {
		t.Fatalf("one schedule: %+v", rep.Coverage)
	}
}

// Two tasks that only read a row nobody writes commute (§16.2), though the
// lock component has a store.
func TestReadsOfUnwrittenKeysCommute(t *testing.T) {
	doc := parse(t, lockDoc)
	rep, err := explore.Explore(doc, "readers", explore.Options{Schedules: 50})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Failure != nil || !rep.Exhausted {
		t.Fatalf("readers: %+v", rep)
	}
	if rep.Runs != 1 || rep.Coverage.Pruned == 0 {
		t.Fatalf("reads of an unwritten row should commute: %d runs, %+v", rep.Runs, rep.Coverage)
	}
}

func TestInvariantValidation(t *testing.T) {
	doc := parse(t, strings.Replace(lockDoc, `    expect: ["steps.a.result.ok && steps.b.result.ok"]`,
		`    expect: ["steps.a.result.ok && steps.b.result.ok"]
    invariants: ["exactlyOne(calls, 1, true)", "", "true", "true"]`, 1))
	var msgs []string
	for _, is := range model.Validate(doc) {
		if strings.Contains(is.Path, "invariants") {
			msgs = append(msgs, is.Path+": "+is.Message)
		}
	}
	if len(msgs) != 3 {
		t.Fatalf("want 3 invariant issues (bad CEL, empty, duplicate): %v", msgs)
	}
}

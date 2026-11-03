package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
	"github.com/xleelz/mosaic/pkg/api"
)

// fixtureRunData is real engine output: the retry-before-commit scenario of
// the shared gateway fixture, run and encoded the way a saved run is served.
func fixtureRunData(t *testing.T) []byte {
	t.Helper()
	src, err := os.ReadFile(examplePath)
	if err != nil {
		t.Fatal(err)
	}
	doc, err := model.ParseDocument(src)
	if err != nil {
		t.Fatal(err)
	}
	res, err := sim.Run(doc, sim.Request{Scenario: "retry-before-commit"})
	if err != nil {
		t.Fatal(err)
	}
	run := api.SimulationRun{ID: "run_fixture_retry-before-commit", Ontology: doc.ID, Revision: "1", Flow: "chat-stream",
		Scenario: "retry-before-commit", CreatedAt: time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC),
		Request: res.Request, Summary: res.Summary, Trace: res.Trace}
	data, err := json.MarshalIndent(run, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func loadRun(t *testing.T, data []byte) *api.SimulationRun {
	t.Helper()
	var run api.SimulationRun
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	if err := dec.Decode(&run); err != nil {
		t.Fatal(err)
	}
	return &run
}

// TestSummaryOfFixtureRun checks the summary of real engine output.
func TestSummaryOfFixtureRun(t *testing.T) {
	run := loadRun(t, fixtureRunData(t))
	var b bytes.Buffer
	if err := writeSummary(&b, run); err != nil {
		t.Fatal(err)
	}
	out := b.String()
	head := strings.Join([]string{
		"run: run_fixture_retry-before-commit",
		"simulated: flow chat-stream, scenario retry-before-commit, revision 1, seed 1",
		"status: ok",
		`outcome: ok {"cost_cents":2,"id":"c61a6a61-7057-4eef-adda-2f3ff9eda443","model":"test-model","partial":false,"status":"complete","tokens_out":267}`,
		"duration: 255 ms",
		"retries: 1",
		"faults: 1",
		"assertions: 3 of 3 passed",
		"  ✓ result.ok && retries == 1",
		"  ✓ calls['upstream-a.chat'] == 1 && calls['upstream-b.chat'] == 1",
		"  ✓ ctx.upstreamDials == 2 && ctx.firstAttempt == 'failed before commitment'",
		"warnings: none",
		"trace:",
		"  t=0   client → gateway.chat",
		"  t=1     note: Receive chat request",
		"  t=1     → auth.authenticate",
		"  t=2       note: Look up the API key",
		"  t=2     ← auth.authenticate ok (1 ms)",
		"",
	}, "\n")
	if !strings.HasPrefix(out, head) {
		t.Errorf("summary head:\n%s\nwant:\n%s", out[:min(len(out), len(head)+200)], head)
	}
	// The retry section: depth follows span/parent, one line per call boundary.
	section := strings.Join([]string{
		"  t=13    → dispatch.send",
		"  t=14      note: Dial the first upstream",
		"  t=14      → upstream-a.chat",
		"  t=14        fault error at upstream-a.chat: upstream_error",
		"  t=112     ← upstream-a.chat ✗ upstream_error (status 502) (98 ms)",
		"  t=112     retry upstream-a.chat attempt 2 on upstream_error: Upstream fails before commitment",
		"  t=112     → upstream-b.chat (attempt 2)",
		"  t=224     ← upstream-b.chat ok (112 ms)",
		"  t=224   ← dispatch.send ok (211 ms)",
		"",
	}, "\n")
	if !strings.Contains(out, section) {
		t.Errorf("summary lacks the retry section:\n%s", out)
	}
	for _, want := range []string{
		"  t=3       choice throttle.check.rate_limit = allowed (default)\n",
		"  t=252   emit billing.record\n",
		"  t=254 ← gateway.chat ok (254 ms)\n",
		"  t=254   → billing.record (async from gateway)\n",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("summary lacks %q", want)
		}
	}
	// set events and note details stay out of the summary.
	if strings.Contains(out, "set ctx.") || strings.Contains(out, "arrives with an API key") {
		t.Error("the summary should not show set events or note details")
	}
	// Exactly one line per call boundary.
	calls := 0
	for _, ev := range run.Trace {
		if ev.Type == "call.start" || ev.Type == "call.end" {
			calls++
		}
	}
	if got := strings.Count(out, " → ") + strings.Count(out, " ← "); got != calls {
		t.Errorf("%d call lines for %d call events", got, calls)
	}
}

func TestTraceOfFixtureRun(t *testing.T) {
	run := loadRun(t, fixtureRunData(t))
	var b bytes.Buffer
	if err := writeTrace(&b, run); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(b.String(), "\n"), "\n")
	if len(lines) != len(run.Trace) {
		t.Fatalf("%d lines for %d events", len(lines), len(run.Trace))
	}
	for i, want := range map[int]string{
		0:  "#1  t=0   client → gateway.chat",
		1:  "#2  t=1     note: Receive chat request — A simulated streaming chat request arrives with an API key and a model name.",
		2:  "#3  t=1     set ctx.committed = false",
		49: `#50 t=13        set state.free = 2 (was 3)`,
	} {
		if lines[i] != want {
			t.Errorf("line %d = %q\nwant      %q", i, lines[i], want)
		}
	}
}

func TestSummaryOfFailedRun(t *testing.T) {
	ok, notOK := true, false
	run := &api.SimulationRun{
		Ontology: "o", Revision: "draft", Flow: "checkout",
		Summary: sim.Summary{
			Status: "error", Seed: 9, DurationMS: 2050, Retries: 2, Faults: 3,
			Result:     sim.Outcome{Error: &sim.Error{Code: "unavailable", Status: 503, Message: "db is unavailable"}},
			Assertions: []sim.Assertion{{Expr: "result.ok", Passed: false}, {Expr: "retries == 2", Passed: true}, {Expr: "ctx.x.y == 1", Error: "no such key: x"}},
			Warnings:   []string{"db.query response: missing property rows"},
		},
		Trace: []sim.Event{
			{Seq: 1, T: 0, Type: "call.start", Span: 1, From: "web", To: "api", Interface: "api.checkout", Attempt: 1},
			{Seq: 2, T: 1, Type: "note", Span: 1, Detail: "detail only, hidden from the summary"},
			{Seq: 3, T: 1, Type: "call.start", Span: 2, Parent: 1, From: "api", To: "db", Interface: "db.query", Attempt: 1},
			{Seq: 4, T: 2001, Type: "call.end", Span: 2, Parent: 1, Interface: "db.query", OK: &ok, DurationMS: 2000, Late: true},
			{Seq: 5, T: 1001, Type: "timeout", Span: 2, Interface: "db.query", DurationMS: 1000, Message: "db.query exceeded 1000 ms"},
			{Seq: 6, T: 1001, Type: "retry", Span: 1, Interface: "db.query", Attempt: 2, BackoffMS: 50, Message: "timeout"},
			{Seq: 7, T: 1051, Type: "call.start", Span: 3, Parent: 1, From: "api", Interface: "db.query", Attempt: 2},
			{Seq: 8, T: 1051, Type: "fault", Span: 3, Interface: "db.query", Fault: "unavailable"},
			{Seq: 9, T: 1051, Type: "call.end", Span: 3, Parent: 1, Interface: "db.query", OK: &notOK, Error: &sim.Error{Code: "unavailable", Status: 503}},
			{Seq: 10, T: 1051, Type: "warning", Span: 1, Message: "something odd"},
			{Seq: 11, T: 2050, Type: "call.end", Span: 1, Interface: "api.checkout", OK: &notOK, Error: &sim.Error{Code: "unavailable", Status: 503, Message: "db is unavailable"}, DurationMS: 2050},
		},
	}
	var b bytes.Buffer
	if err := writeSummary(&b, run); err != nil {
		t.Fatal(err)
	}
	want := `run: (not saved)
simulated: flow checkout, revision draft, seed 9
status: error
outcome: error unavailable (status 503): db is unavailable
duration: 2050 ms
retries: 2
faults: 3
assertions: 1 of 3 passed
  ✗ result.ok
  ✓ retries == 2
  ✗ ctx.x.y == 1
      error: no such key: x
warnings: 1
  ! db.query response: missing property rows
trace:
  t=0    web → api.checkout
  t=1      → db.query
  t=2001   ← db.query ok (2000 ms, late)
  t=1001   timeout db.query after 1000 ms: db.query exceeded 1000 ms
  t=1001   retry db.query attempt 2 after 50 ms on timeout
  t=1051   → db.query (attempt 2)
  t=1051     fault unavailable at db.query
  t=1051   ← db.query ✗ unavailable (status 503) (0 ms)
  t=1051   warning: something odd
  t=2050 ← api.checkout ✗ unavailable (status 503): db is unavailable (2050 ms)
`
	if b.String() != want {
		t.Errorf("summary:\n%s\nwant:\n%s", b.String(), want)
	}
	if err := runOutcome(run); err == nil || err.Error() != "2 of 3 expectations failed" {
		t.Errorf("runOutcome = %v", err)
	}
}

func TestSummaryOfAbortedRun(t *testing.T) {
	run := &api.SimulationRun{ID: "run_7", Flow: "loop", Summary: sim.Summary{Status: "aborted", Abort: "event budget of 20000 exceeded"}}
	var b bytes.Buffer
	if err := writeSummary(&b, run); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"status: aborted: event budget of 20000 exceeded\n", "outcome: none\n", "assertions: none\n", "trace: none\n"} {
		if !strings.Contains(b.String(), want) {
			t.Errorf("summary lacks %q:\n%s", want, b.String())
		}
	}
	if err := runOutcome(run); err == nil || !strings.Contains(err.Error(), "the run aborted: event budget") {
		t.Errorf("runOutcome = %v", err)
	}
}

// TestSimGetFixtureThroughCLI serves the fixture run over HTTP and checks
// every output format end to end.
func TestSimGetFixtureThroughCLI(t *testing.T) {
	data := fixtureRunData(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/simulations/run_fixture_retry-before-commit" {
			w.WriteHeader(404)
			w.Write([]byte(`{"error":{"code":"not_found","message":"no such run"}}`))
			return
		}
		w.Write(data)
	}))
	defer srv.Close()
	out, _ := mustCLI(t, nil, 0, "--server", srv.URL, "sim", "get", "run_fixture_retry-before-commit")
	var b bytes.Buffer
	_ = writeSummary(&b, loadRun(t, data))
	if out != b.String() {
		t.Errorf("sim get differs from writeSummary")
	}
	out, _ = mustCLI(t, nil, 0, "--server", srv.URL, "sim", "get", "run_fixture_retry-before-commit", "--format", "json")
	var a, c any
	_ = json.Unmarshal([]byte(out), &a)
	_ = json.Unmarshal(data, &c)
	ja, _ := json.Marshal(a)
	jc, _ := json.Marshal(c)
	if string(ja) != string(jc) {
		t.Error("--format json does not round-trip the run")
	}
	out, _ = mustCLI(t, nil, 0, "--server", srv.URL, "sim", "get", "run_fixture_retry-before-commit", "--format", "trace")
	if strings.Count(out, "\n") != 98 {
		t.Errorf("trace has %d lines", strings.Count(out, "\n"))
	}
	_, errOut := mustCLI(t, nil, 1, "--server", srv.URL, "sim", "get", "nope")
	if errOut != "mosaic: no such run (not_found, HTTP 404)\n" {
		t.Errorf("stderr = %q", errOut)
	}
}

func TestTestReportText(t *testing.T) {
	rep := &api.TestReport{Revision: "3", Total: 4, Failed: 2, Results: []api.TestResult{
		{Scenario: "happy", Name: "Happy path", Passed: true, Status: "ok", Assertions: []sim.Assertion{{Expr: "result.ok", Passed: true}}},
		{Scenario: "sad", Name: "Sad path", Status: "error", RunID: "run_9", Assertions: []sim.Assertion{
			{Expr: "result.ok", Passed: true}, {Expr: "retries == 1", Passed: false}, {Expr: "ctx.q", Error: "no such key: q"}}},
		{Scenario: "broken", Error: `unknown flow "gone"`},
		{Scenario: "isolated", Passed: true, Status: "ok", Steps: 2, Mocks: 1, MockedCalls: 3},
	}}
	var b bytes.Buffer
	if err := writeTestReport(&b, rep); err != nil {
		t.Fatal(err)
	}
	want := `✓ happy — Happy path
✗ sad — Sad path (status error)
    ✗ retries == 1
    ✗ ctx.q
        error: no such key: q
    run: run_9
✗ broken
    error: unknown flow "gone"
✓ isolated (2 steps; 1 mocks, 3 calls mocked)
2 of 4 scenarios passed, revision 3
`
	if b.String() != want {
		t.Errorf("report:\n%s\nwant:\n%s", b.String(), want)
	}
}

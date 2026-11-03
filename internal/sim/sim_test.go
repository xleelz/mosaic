package sim_test

import (
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/jsonschema"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// simComponents is shared by every test document. (Avoid YAML 1.1 booleans
// such as y, n, on and off as keys or names.)
const simComponents = `
components:
  - {id: client}
  - {id: a, state: {initial: {x: 1, z: 2}}}
  - {id: b, state: {initial: {count: 0}}}
  - {id: c}
schemas:
  - id: Thing
    schema:
      type: object
      required: [id, qty]
      properties:
        id: {type: string, format: uuid}
        qty: {type: integer, minimum: 1, maximum: 5}
`

// build parses simComponents plus body, adds a flow named after every
// interface of component a (entered by client), and requires a valid document.
func build(t *testing.T, body string) *model.Document {
	t.Helper()
	doc, err := model.ParseDocument([]byte(simComponents + body))
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range doc.Interfaces {
		if f.Component == "a" {
			doc.Flows = append(doc.Flows, model.Flow{ID: f.Name, Entry: &model.FlowEntry{Caller: "client", Interface: f.ID}})
		}
	}
	for _, is := range model.Validate(doc) {
		if is.Severity == model.SeverityError {
			t.Fatalf("test document: %s: %s", is.Path, is.Message)
		}
	}
	return doc
}

func run(t *testing.T, doc *model.Document, req sim.Request) *sim.Result {
	t.Helper()
	res, err := sim.Run(doc, req)
	if err != nil {
		t.Fatal(err)
	}
	return res
}

func events(res *sim.Result, typ string) []sim.Event {
	var out []sim.Event
	for _, e := range res.Trace {
		if e.Type == typ {
			out = append(out, e)
		}
	}
	return out
}

func eventsFor(res *sim.Result, typ, iface string) []sim.Event {
	var out []sim.Event
	for _, e := range events(res, typ) {
		if e.Interface == iface {
			out = append(out, e)
		}
	}
	return out
}

func eq(t *testing.T, what string, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Errorf("%s: got %#v, want %#v", what, got, want)
	}
}

func okValue(t *testing.T, res *sim.Result) any {
	t.Helper()
	s := res.Summary
	if s.Status != "ok" || !s.Result.OK {
		t.Fatalf("status %s, result %+v, abort %q", s.Status, s.Result, s.Abort)
	}
	return s.Result.Value
}

func TestSetIsParallelAndSorted(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: main
    behavior:
      - set: {state.x: "= state.z", state.z: "= state.x", ctx.deep.k: "= state.x", vars.v: [1, "= state.z"]}
      - return: {x: "= state.x", z: "= state.z", deep: "= ctx.deep.k", v: "= vars.v"}
`)
	res := run(t, doc, sim.Request{Flow: "main"})
	eq(t, "value", okValue(t, res), map[string]any{"x": int64(2), "z": int64(1), "deep": int64(1), "v": []any{int64(1), int64(2)}})
	sets := events(res, "set")
	var paths []string
	for _, e := range sets {
		paths = append(paths, e.Path)
	}
	eq(t, "set order", paths, []string{"ctx.deep.k", "state.x", "state.z", "vars.v"})
	eq(t, "state.x old/new", []any{sets[1].Old, sets[1].New, sets[1].Scope}, []any{int64(1), int64(2), "state"})
	eq(t, "state.z old/new", []any{sets[2].Old, sets[2].New}, []any{int64(2), int64(1)})
	eq(t, "new ctx path has no old value", sets[0].Old, nil)
	eq(t, "final state", res.Summary.State["a"], map[string]any{"x": int64(2), "z": int64(1)})
	eq(t, "initial state", res.Summary.InitialState["a"], map[string]any{"x": int64(1), "z": int64(2)})
	eq(t, "ctx", res.Summary.Ctx, map[string]any{"deep": map[string]any{"k": int64(1)}})
}

func TestWhenIfAndNotes(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: main
    behavior:
      - {title: skipped, when: "input.flag == false", set: {ctx.skipped: true}}
      - {title: kept, detail: d, source: "k.go:3", when: "input.flag", set: {ctx.kept: true}}
      - if: "input.num > 1"
        then: [{return: big}]
        else: [{detail: small branch}, {return: small}]
`)
	res := run(t, doc, sim.Request{Flow: "main", Input: json.RawMessage(`{"flag": true, "num": 5}`)})
	eq(t, "then", okValue(t, res), "big")
	eq(t, "ctx", res.Summary.Ctx, map[string]any{"kept": true})
	notes := events(res, "note")
	if len(notes) != 1 || notes[0].Title != "kept" || notes[0].Detail != "d" || *notes[0].Source != (model.Source{Path: "k.go", Line: 3}) {
		t.Errorf("notes: %+v", notes)
	}
	res = run(t, doc, sim.Request{Flow: "main", Input: json.RawMessage(`{"flag": false, "num": 0}`)})
	eq(t, "else", okValue(t, res), "small")
	eq(t, "ctx", res.Summary.Ctx, map[string]any{"skipped": true})
	notes = events(res, "note")
	if len(notes) != 2 || notes[1].Detail != "small branch" || notes[1].Title != "" {
		t.Errorf("a detail alone gives a note: %+v", notes)
	}
}

func TestNonBooleanConditionAborts(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: a, name: badif, behavior: [{if: "input.num", then: [{return: 1}]}]}
  - {component: a, name: badwhen, behavior: [{when: "'yes'", return: 1}]}
  - {component: a, name: badretry, behavior: [{call: b.get, retry: {max_attempts: 2, codes: [e], when: "1"}}]}
  - {component: b, name: get}
`)
	for _, c := range []struct{ flow, where string }{
		{"badif", "a.badif.behavior[0].if"},
		{"badwhen", "a.badwhen.behavior[0].when"},
		{"badretry", "a.badretry.behavior[0].retry.when"},
	} {
		res := run(t, doc, sim.Request{Flow: c.flow, Input: json.RawMessage(`{"num": 3}`),
			Faults: []model.Fault{{Target: "b.get", Type: "error", Code: "e"}}})
		s := res.Summary
		if s.Status != "aborted" || !strings.Contains(s.Abort, c.where) || !strings.Contains(s.Abort, "expected a boolean") {
			t.Errorf("%s: status %s, abort %q", c.flow, s.Status, s.Abort)
		}
		if s.Passed || len(s.Assertions) != 0 {
			t.Errorf("%s: an aborted run does not pass", c.flow)
		}
	}
}

func TestChoice(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: main
    behavior:
      - choice: route
        default: fast
        options:
          fast: [{set: {ctx.route: fast}}]
          slow: [{set: {ctx.route: slow}}]
      - choice: pick
        default: "= input.mode"
        options:
          left: [{set: {ctx.pick: left}}]
          right: [{set: {ctx.pick: right}}]
      - choice: solo
        options:
          only: [{set: {ctx.solo: only}}]
      - return: "= ctx"
`)
	type pick struct{ option, origin string }
	cases := []struct {
		name    string
		mode    string
		choices map[string]string
		want    map[string]pick
		warning string
	}{
		{"defaults", "left", nil,
			map[string]pick{"a.main.route": {"fast", "default"}, "a.main.pick": {"left", "expression"}, "a.main.solo": {"only", "default"}}, ""},
		{"overrides", "left", map[string]string{"a.main.route": "slow", "a.main.pick": "right"},
			map[string]pick{"a.main.route": {"slow", "scenario"}, "a.main.pick": {"right", "scenario"}, "a.main.solo": {"only", "default"}}, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			res := run(t, doc, sim.Request{Flow: "main", Choices: model.ScalarChoices(c.choices), Input: json.RawMessage(`{"mode": "` + c.mode + `"}`)})
			v := okValue(t, res).(map[string]any)
			got := map[string]pick{}
			for _, e := range events(res, "choice") {
				got[e.Key] = pick{e.Option, e.Origin}
				if v[strings.TrimPrefix(e.Key, "a.main.")] != e.Option {
					t.Errorf("%s ran the wrong branch: ctx %v", e.Key, v)
				}
			}
			eq(t, "choices", got, c.want)
			if c.warning == "" {
				eq(t, "warnings", res.Summary.Warnings, []string{})
			} else {
				eq(t, "warnings", res.Summary.Warnings, []string{c.warning})
			}
		})
	}
	// A run's own choices are validated like a scenario's: unknown keys and
	// options are refused rather than silently ignored.
	for choices, want := range map[[2]string]string{
		{"a.main.route", "warp"}: `choice "a.main.route" has no option "warp" (options: fast, slow)`,
		{"a.main.nope", "fast"}:  `unknown choice point "a.main.nope"`,
		{"route", "fast"}:        `unknown choice point "route" (keys are <interface>.<choice>)`,
	} {
		_, err := sim.Run(doc, sim.Request{Flow: "main", Choices: map[string]model.Choice{choices[0]: model.ChoiceOf(choices[1])}})
		var re *sim.RequestError
		if !errors.As(err, &re) || !strings.Contains(err.Error(), want) {
			t.Errorf("choices %v: got %v, want a request error containing %q", choices, err, want)
		}
	}
	// A scenario in an unvalidated draft can still name a missing option: the
	// run warns and falls back to the default.
	draft := *doc
	draft.Scenarios = []model.Scenario{{ID: "warp", Flow: "main", Input: json.RawMessage(`{"mode": "right"}`), Choices: map[string]model.Choice{"a.main.route": model.ChoiceOf("warp")}}}
	res := run(t, &draft, sim.Request{Scenario: "warp"})
	eq(t, "draft warnings", res.Summary.Warnings, []string{`choice a.main.route has no option "warp"; using its default`})

	res = run(t, doc, sim.Request{Flow: "main", Input: json.RawMessage(`{"mode": "middle"}`)})
	if res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, "middle is not an option of a.main.pick") {
		t.Errorf("expression default outside the options: %+v", res.Summary)
	}
}

func TestCallResultStoredWithAs(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: main
    behavior:
      - {call: b.get, input: {q: "= input.q"}, as: r}
      - {call: c.stub}
      - return: "= vars.r"
  - {component: b, name: get, latency_ms: 7, behavior: [{return: {got: "= input.q"}}]}
  - {component: c, name: stub, response: {type: object, properties: {flag: {type: boolean}}}}
`)
	res := run(t, doc, sim.Request{Flow: "main", Input: json.RawMessage(`{"q": "hello"}`)})
	eq(t, "vars.r", okValue(t, res), map[string]any{"ok": true, "value": map[string]any{"got": "hello"}, "error": nil,
		"attempts": int64(1), "duration_ms": int64(7), "duration_us": int64(7000), "target": "b.get"})
	eq(t, "calls", res.Summary.Calls, map[string]int{"a.main": 1, "b.get": 1, "c.stub": 1})
	start := eventsFor(res, "call.start", "b.get")[0]
	eq(t, "call.start", []any{start.From, start.To, start.Input, start.Attempt, start.Async}, []any{"a", "b", map[string]any{"q": "hello"}, 1, false})
	end := eventsFor(res, "call.end", "b.get")[0]
	if end.OK == nil || !*end.OK || end.DurationMS != 7 || end.Span != start.Span || end.Parent == 0 {
		t.Errorf("call.end %+v (start %+v)", end, start)
	}
}

func TestOnError(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: propagate
    behavior:
      - {call: b.boom}
      - {set: {ctx.after: true}}
  - component: a
    name: explicit
    behavior:
      - {call: b.boom, on_error: propagate}
      - {set: {ctx.after: true}}
  - component: a
    name: cont
    behavior:
      - {call: b.boom, as: r, on_error: continue}
      - {set: {ctx.after: true}}
      - return: {ok: "= vars.r.ok", code: "= error.code", rcode: "= vars.r.error.code", status: "= vars.r.error.status"}
  - component: a
    name: handle
    behavior:
      - call: b.boom
        on_error:
          - {call: b.fine, as: fine}
          - {set: {ctx.handled: "= error.code"}}
      - return: {code: "= error.code", fine: "= vars.fine.ok"}
  - component: a
    name: recover
    behavior:
      - {call: b.boom, on_error: [{return: recovered}]}
      - {return: unreachable}
  - component: a
    name: wrap
    behavior:
      - {call: b.boom, on_error: [{fail: {code: wrapped, message: "= 'from ' + error.code"}}]}
  - {component: b, name: boom, behavior: [{fail: {code: boom, status: 500, message: m, data: {k: 1}}}]}
  - {component: b, name: fine, behavior: [{return: 1}]}
`)
	for _, flow := range []string{"propagate", "explicit"} {
		res := run(t, doc, sim.Request{Flow: flow})
		s := res.Summary
		if s.Status != "error" || s.Result.OK || s.Result.Error.Code != "boom" || s.Result.Error.Status != 500 || s.Result.Error.Message != "m" {
			t.Errorf("%s: %+v %+v", flow, s.Status, s.Result.Error)
		}
		eq(t, flow+" data", s.Result.Error.Data, map[string]any{"k": int64(1)})
		eq(t, flow+" stops", s.Ctx, map[string]any{})
	}
	res := run(t, doc, sim.Request{Flow: "cont"})
	eq(t, "continue", okValue(t, res), map[string]any{"ok": false, "code": "boom", "rcode": "boom", "status": int64(500)})
	eq(t, "continue runs the next step", res.Summary.Ctx["after"], true)

	res = run(t, doc, sim.Request{Flow: "handle"})
	eq(t, "error survives a successful call in on_error", okValue(t, res), map[string]any{"code": "boom", "fine": true})
	eq(t, "handled", res.Summary.Ctx["handled"], "boom")

	res = run(t, doc, sim.Request{Flow: "recover"})
	eq(t, "on_error can return", okValue(t, res), "recovered")

	res = run(t, doc, sim.Request{Flow: "wrap"})
	if e := res.Summary.Result.Error; e == nil || e.Code != "wrapped" || e.Message != "from boom" {
		t.Errorf("wrap: %+v", e)
	}
}

func TestFailValues(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: a, name: code_only, behavior: [{fail: "= 'just_code'"}]}
  - {component: a, name: number, behavior: [{fail: "= 42"}]}
  - {component: a, name: nothing, behavior: [{fail: "= null"}]}
  - {component: a, name: no_code, behavior: [{fail: "= {'message': 'm'}"}]}
  - {component: a, name: full, behavior: [{fail: {code: c, status: "= 409.0", retryable: true, message: m, data: [1]}}]}
`)
	cases := map[string]sim.Error{
		"code_only": {Code: "just_code"},
		"number":    {Code: "error", Message: "42"},
		"nothing":   {Code: "error"},
		"no_code":   {Code: "error", Message: "m"},
		"full":      {Code: "c", Status: 409, Retryable: true, Message: "m", Data: []any{int64(1)}},
	}
	for flow, want := range cases {
		res := run(t, doc, sim.Request{Flow: flow})
		if res.Summary.Result.Error == nil {
			t.Errorf("%s: no error", flow)
			continue
		}
		eq(t, flow, *res.Summary.Result.Error, want)
	}
}

func TestRetryConditions(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: a, name: codes_other, behavior: [{call: b.flaky, as: r, on_error: continue, retry: {max_attempts: 3, codes: [other]}}, {return: "= vars.r.attempts"}]}
  - {component: a, name: codes_e, behavior: [{call: b.flaky, as: r, on_error: continue, retry: {max_attempts: 3, codes: [other, e]}}, {return: "= vars.r.attempts"}]}
  - {component: a, name: plain, behavior: [{call: b.flaky, as: r, on_error: continue, retry: {max_attempts: 3}}, {return: "= vars.r.attempts"}]}
  - {component: a, name: when_attempt, behavior: [{call: b.flaky, as: r, on_error: continue, retry: {max_attempts: 5, when: "attempt < 2"}}, {return: "= vars.r.attempts"}]}
  - {component: a, name: when_error, behavior: [{call: b.flaky, as: r, on_error: continue, retry: {max_attempts: 3, when: "error.code == 'e'"}}, {return: "= vars.r.attempts"}]}
  - {component: a, name: expr_attempts, behavior: [{call: b.flaky, as: r, on_error: continue, retry: {max_attempts: "= input.tries"}}, {return: "= vars.r.attempts"}]}
  - {component: b, name: flaky, latency_ms: 10}
`)
	yes, no := true, false
	cases := []struct {
		flow      string
		code      string
		retryable *bool
		input     string
		attempts  int64
	}{
		{"codes_other", "e", &yes, "", 1},
		{"codes_e", "e", &no, "", 3}, // codes ignore retryable
		{"plain", "e", &yes, "", 3},
		{"plain", "e", &no, "", 1},
		{"plain", "e", nil, "", 1}, // error faults default to retryable false
		{"when_attempt", "e", &yes, "", 2},
		{"when_error", "e", &yes, "", 3},
		{"when_error", "q", &yes, "", 1},
		{"expr_attempts", "e", &yes, `{"tries": 2}`, 2},
		{"expr_attempts", "e", &yes, `{"tries": 50}`, 20}, // clamped to 20
		{"expr_attempts", "e", &yes, `{"tries": 0}`, 1},
	}
	for _, c := range cases {
		req := sim.Request{Flow: c.flow, Faults: []model.Fault{{Target: "b.flaky", Type: "error", Code: c.code, Retryable: c.retryable}}}
		if c.input != "" {
			req.Input = json.RawMessage(c.input)
		}
		res := run(t, doc, req)
		v := okValue(t, res)
		if v != c.attempts || res.Summary.Retries != int(c.attempts-1) || res.Summary.Calls["b.flaky"] != int(c.attempts) || res.Summary.Faults != int(c.attempts) {
			t.Errorf("%s %s retryable=%v: attempts %v, retries %d, calls %d, faults %d; want %d attempts",
				c.flow, c.code, c.retryable, v, res.Summary.Retries, res.Summary.Calls["b.flaky"], res.Summary.Faults, c.attempts)
		}
	}
	res := run(t, doc, sim.Request{Flow: "expr_attempts", Input: json.RawMessage(`{"tries": "x"}`)})
	if res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, "max_attempts must be a number") {
		t.Errorf("non-numeric max_attempts: %+v", res.Summary)
	}
}

func TestRetryBackoffAndEvent(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: backoff
    behavior:
      - call: b.flaky
        as: r
        on_error: continue
        retry: {max_attempts: 4, backoff_ms: 100, multiplier: 2, max_backoff_ms: 300, title: Retry it, detail: why, source: "r.go:3-4"}
      - return: "= vars.r"
  - component: a
    name: flat
    behavior:
      - {call: b.flaky, on_error: continue, retry: {max_attempts: 3, backoff_ms: 50}}
  - {component: b, name: flaky, latency_ms: 10}
`)
	faults := []model.Fault{{Target: "b.flaky", Type: "error", Code: "e", Retryable: boolp(true)}}
	res := run(t, doc, sim.Request{Flow: "backoff", Faults: faults})
	retries := events(res, "retry")
	var backoffs []int64
	var attempts []int
	for _, e := range retries {
		backoffs = append(backoffs, e.BackoffMS)
		attempts = append(attempts, e.Attempt)
		if e.Title != "Retry it" || e.Detail != "why" || e.Source == nil || *e.Source != (model.Source{Path: "r.go", Line: 3, EndLine: 4}) ||
			e.Message != "e" || e.Interface != "b.flaky" || e.Component != "a" {
			t.Errorf("retry event %+v", e)
		}
	}
	eq(t, "backoffs", backoffs, []int64{100, 200, 300})
	eq(t, "retry attempts", attempts, []int{2, 3, 4})
	starts, ends := eventsFor(res, "call.start", "b.flaky"), eventsFor(res, "call.end", "b.flaky")
	if len(starts) != 4 || len(ends) != 4 {
		t.Fatalf("%d starts, %d ends", len(starts), len(ends))
	}
	for i := 1; i < 4; i++ {
		if gap := starts[i].T - ends[i-1].T; gap != backoffs[i-1] {
			t.Errorf("attempt %d starts %d ms after the previous end, want %d", i+1, gap, backoffs[i-1])
		}
		if starts[i].Call != starts[0].Call || starts[i].Attempt != i+1 {
			t.Errorf("attempts share a call id and count up: %+v", starts[i])
		}
	}
	r := okValue(t, res).(map[string]any)
	eq(t, "attempts", r["attempts"], int64(4))
	eq(t, "duration covers latency and backoff", r["duration_ms"], int64(4*10+100+200+300))
	eq(t, "error", r["error"].(map[string]any)["code"], "e")

	res = run(t, doc, sim.Request{Flow: "flat", Faults: faults})
	backoffs = nil
	for _, e := range events(res, "retry") {
		backoffs = append(backoffs, e.BackoffMS)
	}
	eq(t, "multiplier defaults to 1", backoffs, []int64{50, 50})
}

func boolp(b bool) *bool { return &b }

func TestRetryReevaluatesTargetAndInput(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: dyn
    behavior:
      - call: "= ['b.first', 'b.second'][attempt - 1]"
        targets: [b.first, b.second]
        input: {try: "= attempt"}
        retry: {max_attempts: 2, codes: [unavailable]}
        as: r
      - return: {target: "= vars.r.target", value: "= vars.r.value"}
  - {component: b, name: first}
  - {component: b, name: second, behavior: [{return: "= input.try"}]}
`)
	res := run(t, doc, sim.Request{Flow: "dyn", Faults: []model.Fault{{Target: "b.first", Type: "unavailable"}}})
	eq(t, "value", okValue(t, res), map[string]any{"target": "b.second", "value": int64(2)})
	eq(t, "calls", []int{res.Summary.Calls["b.first"], res.Summary.Calls["b.second"]}, []int{1, 1})
	eq(t, "first input", eventsFor(res, "call.start", "b.first")[0].Input, map[string]any{"try": int64(1)})
	eq(t, "retry names the failed target", events(res, "retry")[0].Interface, "b.first")
}

func TestUnknownDynamicTarget(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: main
    behavior:
      - {call: "= 'c.' + input.which", targets: [c.real], as: r, on_error: continue}
      - return: "= vars.r.error.code"
  - {component: c, name: real}
`)
	res := run(t, doc, sim.Request{Flow: "main", Input: json.RawMessage(`{"which": "missing"}`)})
	eq(t, "code", okValue(t, res), "invalid_target")
	eq(t, "warning", res.Summary.Warnings, []string{`call to unknown interface "c.missing"`})
	if _, counted := res.Summary.Calls["c.missing"]; counted {
		t.Error("unknown targets are not counted as calls")
	}
	res = run(t, doc, sim.Request{Flow: "main", Input: json.RawMessage(`{"which": 5}`)})
	if res.Summary.Status != "aborted" {
		t.Errorf("a non-string target aborts: %+v", res.Summary)
	}
}

func TestTimeouts(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: slow
    behavior:
      - {call: b.slow, timeout_ms: 50, as: r, on_error: continue}
      - return: {code: "= vars.r.error.code", retryable: "= vars.r.error.retryable", dur: "= vars.r.duration_ms", now: "= now"}
  - component: a
    name: hang
    behavior:
      - {call: b.get, timeout_ms: 200, as: r, on_error: continue}
      - return: {code: "= vars.r.error.code", now: "= now", msg: "= vars.r.error.message"}
  - component: a
    name: hang_default
    behavior:
      - {call: b.get, as: r, on_error: continue}
      - return: {code: "= vars.r.error.code", now: "= now"}
  - component: a
    name: fast
    behavior:
      - {call: b.get, timeout_ms: 50, as: r, on_error: continue}
      - return: {code: "= vars.r.ok ? 'none' : vars.r.error.code", now: "= now"}
  - component: b
    name: slow
    latency_ms: 100
    behavior:
      - {set: {state.count: "= state.count + 1"}}
      - {return: done}
  - {component: b, name: get, latency_ms: 1}
`)
	// A late callee: the caller resumes at start + timeout, the callee's work stands.
	res := run(t, doc, sim.Request{Flow: "slow"})
	eq(t, "late", okValue(t, res), map[string]any{"code": "timeout", "retryable": true, "dur": int64(50), "now": int64(51)})
	end := eventsFor(res, "call.end", "b.slow")[0]
	if !end.Late || end.T != 101 || end.DurationMS != 100 || end.Output != "done" {
		t.Errorf("late call.end %+v", end)
	}
	to := events(res, "timeout")
	if len(to) != 1 || to[0].T != 51 || to[0].DurationMS != 50 || to[0].Component != "a" || to[0].Seq <= end.Seq {
		t.Errorf("timeout event %+v", to)
	}
	eq(t, "state persists", res.Summary.State["b"]["count"], int64(1))
	if res.Summary.DurationMS != 51+1 && res.Summary.DurationMS != 51 {
		t.Logf("duration %d", res.Summary.DurationMS)
	}

	timeoutFault := []model.Fault{{Target: "b.get", Type: "timeout"}}
	res = run(t, doc, sim.Request{Flow: "hang", Faults: timeoutFault})
	eq(t, "hang with timeout", okValue(t, res), map[string]any{"code": "timeout", "now": int64(201), "msg": "b.get did not respond within 200 ms"})
	if end := eventsFor(res, "call.end", "b.get")[0]; end.Late || end.DurationMS != 200 {
		t.Errorf("a hung call ends at the timeout and is not late: %+v", end)
	}
	if f := events(res, "fault"); len(f) != 1 || f[0].Fault != "timeout" {
		t.Errorf("fault events %+v", f)
	}
	res = run(t, doc, sim.Request{Flow: "hang_default", Faults: timeoutFault})
	eq(t, "hang without timeout", okValue(t, res), map[string]any{"code": "timeout", "now": int64(30001)})

	res = run(t, doc, sim.Request{Flow: "fast", Faults: []model.Fault{{Target: "b", Type: "latency", LatencyMS: 100}}})
	eq(t, "latency fault triggers the timeout", okValue(t, res), map[string]any{"code": "timeout", "now": int64(51)})
	if end := eventsFor(res, "call.end", "b.get")[0]; !end.Late || end.DurationMS != 101 {
		t.Errorf("call.end %+v", end)
	}
	res = run(t, doc, sim.Request{Flow: "fast", Faults: []model.Fault{{Target: "b", Type: "latency", LatencyMS: 20}}})
	if v := okValue(t, res).(map[string]any); v["code"] != "none" || v["now"] != int64(22) {
		t.Errorf("a latency fault within the timeout just delays: %v", v)
	}
}

func TestFaultSelection(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: thrice
    behavior:
      - {call: b.get, as: r1, on_error: continue}
      - {call: b.other, as: r2, on_error: continue}
      - {call: b.get, as: r3, on_error: continue}
      - return: ["= vars.r1.ok", "= vars.r2.ok", "= vars.r3.ok"]
  - component: a
    name: one
    behavior:
      - {call: b.get, as: r, on_error: continue}
      - return: {error: "= vars.r.error", dur: "= vars.r.duration_ms"}
  - {component: b, name: get, latency_ms: 4}
  - {component: b, name: other}
`)
	cases := []struct {
		name  string
		fault model.Fault
		want  []any
	}{
		{"every call", model.Fault{Target: "b", Type: "error", Code: "e"}, []any{false, false, false}},
		{"interface counting", model.Fault{Target: "b.get", Type: "error", Code: "e", Calls: []int{2}}, []any{true, true, false}},
		{"component counting", model.Fault{Target: "b", Type: "error", Code: "e", Calls: []int{2}}, []any{true, false, true}},
		{"several calls", model.Fault{Target: "b", Type: "unavailable", Calls: []int{1, 3}}, []any{false, true, false}},
		{"other target", model.Fault{Target: "c", Type: "error", Code: "e"}, []any{true, true, true}},
	}
	for _, c := range cases {
		res := run(t, doc, sim.Request{Flow: "thrice", Faults: []model.Fault{c.fault}})
		eq(t, c.name, okValue(t, res), c.want)
		hits := 0
		for _, w := range c.want {
			if w == false {
				hits++
			}
		}
		if res.Summary.Faults != hits || len(events(res, "fault")) != hits {
			t.Errorf("%s: %d faults, %d fault events, want %d", c.name, res.Summary.Faults, len(events(res, "fault")), hits)
		}
	}

	unavailable := map[string]any{"code": "unavailable", "status": int64(503), "retryable": true, "message": "b is unavailable", "data": nil}
	res := run(t, doc, sim.Request{Flow: "one", Faults: []model.Fault{{Target: "b.get", Type: "unavailable"}}})
	eq(t, "unavailable defaults, no latency", okValue(t, res), map[string]any{"error": unavailable, "dur": int64(0)})
	res = run(t, doc, sim.Request{Flow: "one", Faults: []model.Fault{{Target: "b", Type: "unavailable", Code: "down", Status: 500, Retryable: boolp(false), Message: "gone"}}})
	eq(t, "unavailable overrides", okValue(t, res).(map[string]any)["error"],
		map[string]any{"code": "down", "status": int64(500), "retryable": false, "message": "gone", "data": nil})
	res = run(t, doc, sim.Request{Flow: "one", Faults: []model.Fault{{Target: "b.get", Type: "error", Code: "teapot", Status: 418}}})
	eq(t, "error fault keeps latency", okValue(t, res), map[string]any{
		"error": map[string]any{"code": "teapot", "status": int64(418), "retryable": false, "message": "", "data": nil}, "dur": int64(4)})
	if f := events(res, "fault")[0]; f.Fault != "error" || f.Message != "teapot" || f.Interface != "b.get" || f.Component != "b" {
		t.Errorf("fault event %+v", f)
	}
	// The first matching fault wins.
	res = run(t, doc, sim.Request{Flow: "one", Faults: []model.Fault{{Target: "b.get", Type: "error", Code: "first"}, {Target: "b", Type: "error", Code: "second"}}})
	eq(t, "first fault wins", okValue(t, res).(map[string]any)["error"].(map[string]any)["code"], "first")
}

func TestEmit(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: emitter
    behavior:
      - {emit: b.sink, input: {num: 1}}
      - {emit: b.sink, input: {num: 2}}
      - {set: {ctx.order: []}}
      - {return: done}
  - component: b
    name: sink
    behavior:
      - {set: {ctx.order: "= ctx.order + [input.num]"}}
      - {emit: c.tail, input: {num: "= input.num * 10"}}
  - component: c
    name: tail
    behavior:
      - {set: {ctx.order: "= ctx.order + [input.num]"}}
  - {component: a, name: echo, behavior: [{emit: b.echo}]}
  - {component: b, name: echo, behavior: [{emit: b.echo}]}
`)
	res := run(t, doc, sim.Request{Flow: "emitter"})
	eq(t, "value", okValue(t, res), "done")
	eq(t, "FIFO delivery after the entry call", res.Summary.Ctx["order"], []any{int64(1), int64(2), int64(10), int64(20)})
	entryEnd := eventsFor(res, "call.end", "a.emitter")[0]
	for _, e := range append(eventsFor(res, "call.start", "b.sink"), eventsFor(res, "call.start", "c.tail")...) {
		if !e.Async || e.Seq < entryEnd.Seq {
			t.Errorf("async delivery %+v comes after seq %d", e, entryEnd.Seq)
		}
	}
	emits := events(res, "emit")
	if len(emits) != 4 || emits[0].To != "b" || emits[0].From != "a" || !reflect.DeepEqual(emits[0].Input, map[string]any{"num": int64(1)}) {
		t.Errorf("emit events %+v", emits)
	}
	eq(t, "calls", res.Summary.Calls, map[string]int{"a.emitter": 1, "b.sink": 2, "c.tail": 2})

	res = run(t, doc, sim.Request{Flow: "echo"})
	if res.Summary.Status != "aborted" || res.Summary.Abort != "emit budget of 1000 exceeded" {
		t.Errorf("emit budget: %s %q", res.Summary.Status, res.Summary.Abort)
	}
	res, err := sim.RunWithLimits(doc, sim.Request{Flow: "echo"}, sim.Limits{MaxEvents: 1000, MaxDepth: 8, MaxEmits: 3})
	if err != nil || res.Summary.Status != "aborted" || res.Summary.Abort != "emit budget of 3 exceeded" || len(events(res, "emit")) != 3 {
		t.Errorf("custom emit budget: %v %+v", err, res.Summary)
	}
}

func TestBudgets(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: a, name: rec, behavior: [{call: a.rec}]}
  - component: a
    name: busy
    behavior:
      - {set: {ctx.p: 1}}
      - {set: {ctx.q: 2}}
      - {set: {ctx.r: 3}}
      - {set: {ctx.s: 4}}
scenarios:
  - {id: recursive, flow: rec, expect: ["true"]}
`)
	res := run(t, doc, sim.Request{Scenario: "recursive"})
	s := res.Summary
	if s.Status != "aborted" || s.Abort != "call depth limit of 64 exceeded at a.rec" || s.Passed || len(s.Assertions) != 0 {
		t.Errorf("depth budget: %+v", s)
	}
	if n := s.Calls["a.rec"]; n != 64 {
		t.Errorf("%d nested calls ran, want 64", n)
	}
	res, err := sim.RunWithLimits(doc, sim.Request{Flow: "busy"}, sim.Limits{MaxEvents: 3, MaxDepth: 64, MaxEmits: 10})
	if err != nil || res.Summary.Status != "aborted" || res.Summary.Abort != "event budget of 3 exceeded" || len(res.Trace) != 3 {
		t.Errorf("event budget: %v %+v (%d events)", err, res.Summary, len(res.Trace))
	}
	if res := run(t, doc, sim.Request{Flow: "busy"}); res.Summary.Status != "ok" || len(res.Trace) != 6 {
		t.Errorf("default budget: %s, %d events", res.Summary.Status, len(res.Trace))
	}
}

func TestStubsAndSchemaWarnings(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: a, name: stubcall, behavior: [{call: c.thing, as: r}, {return: "= vars.r.value"}]}
  - {component: a, name: badreturn, response: Thing, behavior: [{return: {id: 5}}]}
  - {component: a, name: badreq, behavior: [{call: c.takes, input: {qty: lots}}]}
  - {component: a, name: noreturn, response: Thing, behavior: [{set: {ctx.ran: true}}]}
  - {component: a, name: nothing, behavior: [{title: just a note}]}
  - {component: a, name: withreq, request: Thing, behavior: [{return: "= input"}]}
  - {component: a, name: fill, behavior: [{call: c.takes, input: {qty: 2}, fill: true, as: r}]}
  - {component: c, name: thing, response: Thing}
  - {component: c, name: takes, request: Thing}
`)
	thing := doc.Schemas[0].Schema
	check := func(name string, v any) {
		t.Helper()
		if msgs := jsonschema.Validate(thing, v, nil); len(msgs) > 0 {
			t.Errorf("%s: %v is not a Thing: %v", name, v, msgs)
		}
	}
	res := run(t, doc, sim.Request{Flow: "stubcall"})
	check("stub", okValue(t, res))
	eq(t, "stub warnings", res.Summary.Warnings, []string{})

	res = run(t, doc, sim.Request{Flow: "badreturn"})
	okValue(t, res)
	eq(t, "response warnings", res.Summary.Warnings, []string{
		`a.badreturn response: $: missing required property "qty"`,
		"a.badreturn response: $.id: expected string, got integer",
	})
	for _, e := range res.Trace {
		if e.Type == "warning" {
			t.Error("warnings appear only in the summary")
		}
	}

	res = run(t, doc, sim.Request{Flow: "badreq"})
	eq(t, "request warnings", res.Summary.Warnings, []string{
		`c.takes request: $: missing required property "id"`,
		"c.takes request: $.qty: expected integer, got string",
	})

	res = run(t, doc, sim.Request{Flow: "noreturn"})
	check("no return gives fake data", okValue(t, res))
	res = run(t, doc, sim.Request{Flow: "nothing"})
	eq(t, "no return and no response gives null", okValue(t, res), nil)

	res = run(t, doc, sim.Request{Flow: "withreq", Input: json.RawMessage(`{"qty": 99}`)})
	v := okValue(t, res).(map[string]any)
	eq(t, "entry input overlays fake data", v["qty"], int64(99))
	if _, ok := v["id"].(string); !ok {
		t.Errorf("entry input keeps generated fields: %v", v)
	}
	eq(t, "entry input warnings", res.Summary.Warnings, []string{"a.withreq request: $.qty: 99 is above the maximum 5"})

	res = run(t, doc, sim.Request{Flow: "fill"})
	in := eventsFor(res, "call.start", "c.takes")[0].Input.(map[string]any)
	if in["qty"] != int64(2) || in["id"] == nil {
		t.Errorf("fill merges explicit input over fake data: %v", in)
	}
	eq(t, "fill warnings", res.Summary.Warnings, []string{})
}

func TestWait(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: main
    behavior:
      - {wait: 5}
      - {wait: "= input.ms"}
      - {wait: "= -3"}
      - {wait: "= 2.9"}
      - {return: "= double(now_us) / 1000.0"}
  - {component: a, name: bad, behavior: [{wait: "= 'soon'"}]}
`)
	res := run(t, doc, sim.Request{Flow: "main", Input: json.RawMessage(`{"ms": 10}`)})
	eq(t, "now", okValue(t, res), 1+5+10+0+2.9) // §13.1 item 16: a fractional wait is kept (exact time via now_us)
	if res := run(t, doc, sim.Request{Flow: "bad"}); res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, "wait must be milliseconds") {
		t.Errorf("bad wait: %+v", res.Summary)
	}
}

func TestLatencyRange(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: a, name: main, latency_ms: {min: 5, max: 9}}
  - {component: a, name: zero, latency_ms: 0}
`)
	seen := map[int64]bool{}
	for seed := int64(0); seed < 40; seed++ {
		res := run(t, doc, sim.Request{Flow: "main", Seed: &seed})
		d := res.Summary.DurationMS
		if d < 5 || d > 9 {
			t.Fatalf("seed %d: duration %d", seed, d)
		}
		seen[d] = true
	}
	if len(seen) < 3 {
		t.Errorf("latency barely varies across seeds: %v", seen)
	}
	eq(t, "zero latency", run(t, doc, sim.Request{Flow: "zero"}).Summary.DurationMS, int64(0))
}

func TestExpectations(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: a, name: simple, behavior: [{call: b.get}, {set: {ctx.done: true}}, {return: {num: 3}}]}
  - {component: a, name: failing, behavior: [{fail: {code: nope, status: 400}}]}
  - {component: b, name: get}
  - {component: b, name: unused}
scenarios:
  - id: s
    flow: simple
    expect:
      - "calls['b.get'] == 1 && calls['b.unused'] == 0 && calls['a.failing'] == 0"
      - "status == 'ok' && result.ok && result.error == null && result.value.num == 3"
      - "ctx.done && retries == 0 && faults == 0 && size(warnings) == 0 && duration_ms > 0"
      - "state['b'].count == 0 && state['a'].x == 1"
  - {id: f, flow: failing, expect: ["status == 'error' && !result.ok && result.error.code == 'nope' && result.error.status == 400"]}
`)
	res := run(t, doc, sim.Request{Scenario: "s"})
	for _, a := range res.Summary.Assertions {
		if !a.Passed {
			t.Errorf("failed: %s %s", a.Expr, a.Error)
		}
	}
	if !res.Summary.Passed || len(res.Summary.Assertions) != 4 {
		t.Errorf("summary %+v", res.Summary)
	}
	res = run(t, doc, sim.Request{Scenario: "f"})
	if !res.Summary.Passed || res.Summary.Status != "error" {
		t.Errorf("an error status can pass its expectations: %+v", res.Summary)
	}

	res = run(t, doc, sim.Request{Scenario: "s", Expect: []string{"calls['b.get'] == 2", "nope(", "result.value.missing == 1", "1 + 1"}})
	as := res.Summary.Assertions
	if len(as) != 8 || res.Summary.Passed {
		t.Fatalf("request expectations append to the scenario's: %+v", as)
	}
	eq(t, "request expect order", as[4].Expr, "calls['b.get'] == 2")
	if as[4].Passed || as[4].Error != "" {
		t.Errorf("a false expectation fails without an error: %+v", as[4])
	}
	for _, a := range as[5:] {
		if a.Passed || a.Error == "" {
			t.Errorf("an invalid expectation fails with an error: %+v", a)
		}
	}
	if !strings.Contains(as[7].Error, "expected a boolean") {
		t.Errorf("non-boolean expectation: %q", as[7].Error)
	}
}

func TestRequestErrors(t *testing.T) {
	doc := build(t, `
interfaces:
  - {component: a, name: main}
  - {component: a, name: other}
scenarios:
  - {id: s, flow: main}
`)
	doc.Flows = append(doc.Flows,
		model.Flow{ID: "story", Steps: []model.FlowStep{{Component: "a", Title: "t"}}},
		model.Flow{ID: "ghost", Entry: &model.FlowEntry{Caller: "client", Interface: "a.ghost"}})
	cases := []struct {
		name string
		req  sim.Request
		want string
	}{
		{"nothing", sim.Request{}, "a flow or a scenario is required"},
		{"unknown flow", sim.Request{Flow: "nope"}, `unknown flow "nope"`},
		{"unknown scenario", sim.Request{Scenario: "nope"}, `unknown scenario "nope"`},
		{"scenario flow mismatch", sim.Request{Scenario: "s", Flow: "other"}, `scenario "s" runs flow "main", not "other"`},
		{"flow without entry", sim.Request{Flow: "story"}, `flow "story" has no entry to simulate`},
		{"unknown entry interface", sim.Request{Flow: "ghost"}, `flow "ghost" enters unknown interface "a.ghost"`},
		{"invalid fault type", sim.Request{Flow: "main", Faults: []model.Fault{{Target: "b", Type: "explode"}}}, "invalid fault at faults[0].type"},
		{"invalid fault target", sim.Request{Flow: "main", Faults: []model.Fault{{Target: "zz", Type: "timeout"}}}, "invalid fault at faults[0].target"},
		{"error fault without code", sim.Request{Flow: "main", Faults: []model.Fault{{Target: "b", Type: "error"}}}, "an error fault needs a code"},
		{"invalid input JSON", sim.Request{Flow: "main", Input: json.RawMessage(`{"a":`)}, "input:"},
		{"failing input expression", sim.Request{Flow: "main", Input: json.RawMessage(`{"a": "= nope"}`)}, "entry input:"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			res, err := sim.Run(doc, c.req)
			var re *sim.RequestError
			if !errors.As(err, &re) || !strings.Contains(re.Error(), c.want) || res != nil {
				t.Errorf("got %v (%T), want a RequestError containing %q", err, err, c.want)
			}
		})
	}
	// Matching scenario and flow are fine.
	run(t, doc, sim.Request{Scenario: "s", Flow: "main"})
}

func TestEffectiveRequest(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: main
    behavior:
      - choice: route
        default: fast
        options: {fast: [], slow: [], mid: []}
      - return: "= input"
scenarios:
  - id: s
    flow: main
    seed: 7
    input: {nested: {q: 2}, b: 2}
    choices: {a.main.route: slow}
    state: {a: {z: 5}}
    faults: [{target: c, type: unavailable}]
    expect: ["true"]
`)
	doc.Flows[0].Entry.Input = json.RawMessage(`{"a": 1, "nested": {"p": 1, "q": 1}}`)
	seed := int64(9)
	res := run(t, doc, sim.Request{Scenario: "s", Seed: &seed, Input: json.RawMessage(`{"nested": {"r": 3}}`),
		Choices: map[string]model.Choice{"a.main.route": model.ChoiceOf("mid")}, State: map[string]map[string]any{"a": {"w": json.Number("9")}},
		Faults: []model.Fault{{Target: "b", Type: "timeout"}}, Expect: []string{"status == 'ok'"}})
	want := map[string]any{"a": int64(1), "b": int64(2), "nested": map[string]any{"p": int64(1), "q": int64(2), "r": int64(3)}}
	eq(t, "input merges flow, scenario and request", okValue(t, res), want)
	var effIn any
	if err := json.Unmarshal(res.Request.Input, &effIn); err != nil {
		t.Fatal(err)
	}
	eq(t, "effective input", effIn, map[string]any{"a": 1.0, "b": 2.0, "nested": map[string]any{"p": 1.0, "q": 2.0, "r": 3.0}})
	eq(t, "seed", res.Summary.Seed, int64(9))
	eq(t, "request choice wins", res.Request.Choices, map[string]model.Choice{"a.main.route": model.ChoiceOf("mid")})
	eq(t, "choice taken", events(res, "choice")[0].Option, "mid")
	eq(t, "state overlays", res.Summary.InitialState["a"], map[string]any{"x": int64(1), "z": int64(5), "w": int64(9)})
	eq(t, "faults append", len(res.Request.Faults), 2)
	eq(t, "expectations append", res.Request.Expect, []string{"true", "status == 'ok'"})
	eq(t, "scenario id", res.Request.Scenario, "s")
	eq(t, "flow", res.Request.Flow, "main")

	res = run(t, doc, sim.Request{Scenario: "s"})
	eq(t, "scenario seed", res.Summary.Seed, int64(7))
	res = run(t, doc, sim.Request{Flow: "main"})
	eq(t, "default seed", res.Summary.Seed, int64(1))
}

func TestDeterminismAcrossSeeds(t *testing.T) {
	doc := build(t, `
interfaces:
  - component: a
    name: main
    behavior:
      - {call: c.thing, as: r1}
      - {call: c.slow, as: r2}
      - {emit: c.thing}
      - return: {first: "= vars.r1.value", second: "= vars.r2.value"}
  - {component: c, name: thing, response: Thing, latency_ms: {min: 1, max: 100}}
  - {component: c, name: slow, response: {type: array, items: Thing}, latency_ms: {min: 1, max: 100}}
`)
	marshal := func(seed int64) string {
		res := run(t, doc, sim.Request{Flow: "main", Seed: &seed})
		b, err := json.Marshal(res)
		if err != nil {
			t.Fatal(err)
		}
		return string(b)
	}
	for _, seed := range []int64{1, 2, -5} {
		if a, b := marshal(seed), marshal(seed); a != b {
			t.Errorf("seed %d: two runs differ", seed)
		}
	}
	if marshal(1) == marshal(2) {
		t.Error("different seeds give identical runs")
	}
	// Running does not mutate the document.
	before, _ := json.Marshal(doc)
	marshal(3)
	after, _ := json.Marshal(doc)
	if string(before) != string(after) {
		t.Error("a run mutated the document")
	}
}

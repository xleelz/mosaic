package sim_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// behavior-language §30: config null versus {$absent: true}, quoted state
// path segments, integers beyond int64, and the CEL cost limit.
const s18Doc = `
configs:
  - {id: flag, type: string, value: "on"}
  - {id: opts, type: object, value: {a: 1, b: 2}}
  - {id: unset}
components:
  - {id: client}
  - id: db
    kind: store
    state: {initial: {"ORG#acme.v2": {plan: free, n: 1}, plain: {x: 1}, big: 18446744073709551615, huge: 18446744073709551616}}
  - {id: svc}
interfaces:
  - component: db
    name: read
    latency_ms: 0
    behavior:
      - {return: "= state"}
  - component: db
    name: bump
    latency_ms: 0
    behavior:
      - {set: {"state['ORG#acme.v2'].n": "= state['ORG#acme.v2'].n + 1", "state[\"k.with.dots\"]": 7}}
      - {set: {"= 'state[\"dyn.key\"].v'": 3}}
      - {return: "= state"}
  - component: svc
    name: flag
    latency_ms: 0
    behavior:
      - {return: {given: "= has(config.flag)", value: "= 'flag' in config ? config['flag'] : 'absent'", isnull: "= has(config.flag) && config.flag == null", opts: "= config.opts"}}
  - component: svc
    name: num
    latency_ms: 0
    behavior:
      - {return: {t: "= type(input.n) == uint", plus: "= input.n - 1u", s: "= string(input.n)", same: "= input.n == 18446744073709551615u"}}
  - component: svc
    name: spin
    latency_ms: 0
    behavior:
      - {return: "= input.s.split('').map(c, c + c).size()"}
flows:
  - {id: read, entry: {caller: client, interface: db.read}}
  - {id: bump, entry: {caller: client, interface: db.bump}}
  - {id: flag, entry: {caller: client, interface: svc.flag}}
  - {id: num, entry: {caller: client, interface: svc.num}}
  - {id: spin, entry: {caller: client, interface: svc.spin}}
fixtures:
  - {id: noflag, config: {flag: {$absent: true}}}
scenarios:
  - id: config-default
    flow: flag
    expect:
      - "result.value.given && result.value.value == 'on' && !result.value.isnull"
      - "!has(config.unset) && !('unset' in config)"
  - id: config-null
    flow: flag
    config: {flag: null, opts: {a: null}}
    expect:
      - "result.value.given && result.value.isnull && result.value.value == null"
      - "result.value.opts == {'a': null, 'b': 2}"
      - "has(config.flag) && config['flag'] == null"
  - id: config-absent
    flow: flag
    config: {flag: {$absent: true}, opts: {a: {$absent: true}}}
    expect:
      - "!result.value.given && result.value.value == 'absent'"
      - "result.value.opts == {'b': 2}"
  - id: config-absent-then-set
    flow: flag
    fixtures: [noflag]
    config: {flag: "off"}
    expect: ["result.value.value == 'off'"]
  - id: dotted-set
    flow: bump
    expect:
      - "result.value['ORG#acme.v2'] == {'plan': 'free', 'n': 2}"
      - "result.value['k.with.dots'] == 7 && result.value['dyn.key'] == {'v': 3}"
      - "!('ORG#acme' in result.value)"
  - id: dotted-step-set
    steps:
      - {set: {db: {"['ORG#acme.v2'].plan": pro, "plain.y": 2, "[\"a'b\"]['c.d']": 1}}}
      - {flow: read, as: r}
    expect:
      - "steps.r.result.value['ORG#acme.v2'].plan == 'pro'"
      - "steps.r.result.value.plain == {'x': 1, 'y': 2}"
      - "steps.r.result.value[\"a'b\"] == {'c.d': 1}"
  - id: uint-input
    flow: num
    input: {n: 18446744073709551615}
    expect:
      - "result.value.t && result.value.same"
      - "result.value.plus == 18446744073709551614u"
      - "result.value.s == '18446744073709551615'"
  - id: uint-state
    flow: read
    expect:
      - "type(result.value.big) == uint && result.value.big == 18446744073709551615u"
      - "type(result.value.huge) == double"
`

func TestS18Scenarios(t *testing.T) {
	doc := langDoc(t, s18Doc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) { passes(t, doc, sim.Request{Scenario: sc.ID}) })
	}
	// A set event names the path as written.
	res := run(t, doc, sim.Request{Scenario: "dotted-step-set"})
	found := false
	for _, e := range events(res, "set") {
		found = found || e.Path == "state['ORG#acme.v2'].plan"
	}
	if !found {
		t.Errorf("no set event for state['ORG#acme.v2'].plan: %v", events(res, "set"))
	}
}

// A request's config echoes a null as a value and a removal as
// {$absent: true}, at any depth.
func TestS18ConfigEcho(t *testing.T) {
	doc := langDoc(t, s18Doc)
	res := passes(t, doc, sim.Request{Flow: "flag", Fixtures: []string{"noflag"},
		Config: map[string]any{"opts": map[string]any{"a": nil, "b": map[string]any{"$absent": true}}},
		Expect: []string{"!has(config.flag)", "config.opts == {'a': null}"}})
	if !model.IsAbsentMark(res.Request.Config["flag"]) {
		t.Errorf("flag echo %v", res.Request.Config["flag"])
	}
	opts, _ := res.Request.Config["opts"].(map[string]any)
	if v, ok := opts["a"]; !ok || v != nil || !model.IsAbsentMark(opts["b"]) {
		t.Errorf("opts echo %v", opts)
	}
	// A later layer sets a key an earlier one removed.
	passes(t, doc, sim.Request{Flow: "flag", Fixtures: []string{"noflag"}, Config: map[string]any{"flag": "x"},
		Expect: []string{"config.flag == 'x'"}})
}

// An integer beyond uint64 becomes a double with a warning, in the run
// (request input) and in validation (the document).
func TestS18LossyInts(t *testing.T) {
	doc := langDoc(t, s18Doc)
	res := run(t, doc, sim.Request{Flow: "num", Input: json.RawMessage(`{"n": 18446744073709551616}`)})
	if len(res.Summary.Warnings) == 0 || !strings.Contains(res.Summary.Warnings[0], "input.n: the integer 18446744073709551616 is beyond uint64") {
		t.Errorf("warnings %v", res.Summary.Warnings)
	}
	found := false
	for _, is := range model.Validate(doc) {
		if is.Severity == model.SeverityWarning && strings.Contains(is.Path, "huge") && strings.Contains(is.Message, "beyond uint64") {
			found = true
		}
		if strings.Contains(is.Path, ".big") && strings.Contains(is.Message, "beyond uint64") {
			t.Errorf("uint64 flagged: %v", is)
		}
	}
	if !found {
		t.Error("no validation warning for the integer beyond uint64")
	}
	// An integer schema accepts a uint64.
	sdoc := langDoc(t, strings.Replace(s18Doc, "    name: num\n", "    name: num\n    request: {type: object, properties: {n: {type: integer}}}\n", 1))
	res = run(t, sdoc, sim.Request{Scenario: "uint-input"})
	for _, w := range res.Summary.Warnings {
		if strings.Contains(w, "expected") {
			t.Errorf("schema warning for a uint64: %s", w)
		}
	}
}

// Over the cost limit, the error names the expression, the limit and what
// the expression costs; the limit scales with the input's size, and
// Limits.CELCost sets it for scenarios without their own.
func TestS18CostLimit(t *testing.T) {
	doc := langDoc(t, s18Doc+`
  - id: tight
    flow: spin
    max_cel_cost: 50
    input: {s: "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"}
`)
	res, err := sim.Run(doc, sim.Request{Scenario: "tight"})
	msg := ""
	if err != nil {
		msg = err.Error()
	} else {
		msg = res.Summary.Abort
	}
	for _, want := range []string{"input.s.split('')", "CEL cost limit 50 exceeded", "; it costs ", "max_cel_cost", "actual cost limit exceeded"} {
		if !strings.Contains(msg, want) {
			t.Errorf("message %q lacks %q", msg, want)
		}
	}
	if got := sim.ScaledCostLimit(100); got != expr.DefaultCostLimit {
		t.Errorf("small input: %d", got)
	}
	if got := sim.ScaledCostLimit(32_000); got != 32_000*sim.CostPerInputByte {
		t.Errorf("32 KB input: %d", got)
	}
	if got := sim.ScaledCostLimit(1 << 30); got != sim.ScaledCostCap {
		t.Errorf("huge input: %d", got)
	}
	// Limits.CELCost applies to a scenario without its own limit.
	lim := sim.DefaultLimits
	lim.CELCost = 50
	in := json.RawMessage(`{"s": "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"}`)
	res, err = sim.RunWithLimits(doc, sim.Request{Flow: "spin", Input: in}, lim)
	if err != nil || !strings.Contains(res.Summary.Abort, "CEL cost limit 50 exceeded") {
		t.Errorf("limits: %v %q", err, res.Summary.Abort)
	}
	if v := run(t, doc, sim.Request{Flow: "spin", Input: in}).Summary.Result.Value; v != int64(52) {
		t.Errorf("default limit: %v", v)
	}
}

func TestS18Validation(t *testing.T) {
	cases := map[string]string{
		"max_cel_cost must be at most": "  - {id: c1, flow: read, max_cel_cost: 20000000000}",
		"invalid state path":           "  - {id: c2, steps: [{set: {db: {\"['open\": 1}}}]}",
	}
	for want, sc := range cases {
		doc, err := model.ParseDocument([]byte("schema_version: 1\n" + s18Doc + sc + "\n"))
		if err != nil {
			t.Fatal(err)
		}
		found := false
		for _, is := range model.Validate(doc) {
			if is.Severity == model.SeverityError && strings.Contains(is.Message, want) {
				found = true
			}
		}
		if !found {
			t.Errorf("no error containing %q", want)
		}
	}
}

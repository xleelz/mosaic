package model

import (
	"fmt"
	"strings"
	"testing"
)

// validBase is a small valid document that every validation case mutates.
const validBase = `
schema_version: 1
components:
  - {id: a}
  - id: b
    parent: a
    state: {schema: {type: object, properties: {num: {type: integer}}}, initial: {num: 0}}
  - {id: c}
schemas:
  - {id: S, schema: {type: object, properties: {num: {type: integer}}}}
  - {id: T, schema: {type: object, properties: {s: {$ref: S}}}}
interfaces:
  - component: a
    name: x
    request: S
    response: {type: object, properties: {s: {$ref: "#/schemas/S"}}}
    errors: [{code: boom, status: 500}]
    latency_ms: {min: 1, max: 5}
    behavior:
      - {title: Start, source: "a.go:1-2", set: {vars.numum: "= input.num", ctx.seen: true, state.count: 1}}
      - {call: b.yy, input: {num: "= vars.num"}, as: r, timeout_ms: 100, retry: {max_attempts: 3, backoff_ms: 10, multiplier: 2, max_backoff_ms: 50, codes: [boom], when: "error.code == 'boom'"}, on_error: continue}
      - {call: "= 'b.' + (attempt == 1 ? 'yy' : 'z')", targets: [b.yy, b.z], retry: {max_attempts: "= 2"}, on_error: [{title: Recover}, {call: b.z}]}
      - if: "vars.r.ok"
        then: [{emit: b.z, input: {num: 1}}]
        else: [{wait: "= 5"}]
      - choice: route
        default: fast
        options:
          fast: [{wait: 1}]
          slow: [{choice: inner, options: {only: []}}]
      - {when: "now > 0", fail: {code: late, status: 504}}
      - {fail: "= {'code': 'x'}"}
      - {return: {num: "= vars.num"}}
  - {component: b, name: yy, request: T}
  - {component: b, name: z}
links:
  - {id: l1, from: a, to: b.yy, kind: calls}
flows:
  - {id: f, entry: {caller: c, interface: a.x, input: {num: "= 1"}}, steps: [{component: a, title: t}]}
  - {id: narrative, steps: [{component: a, title: t}]}
scenarios:
  - id: s
    flow: f
    input: {num: 2}
    choices: {a.x.route: slow, a.x.inner: only}
    state: {b: {num: 3}}
    faults:
      - {target: b, type: unavailable}
      - {target: b.yy, type: error, code: e, calls: [1, 2]}
      - {target: b.z, type: latency, latency_ms: 5}
      - {target: b.z, type: timeout}
    expect: ["result.ok && calls['b.yy'] >= 0 && faults >= 0 && size(warnings) == 0"]
`

func baseDoc(t *testing.T) *Document {
	t.Helper()
	d, err := ParseDocument([]byte(validBase))
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func steps(t *testing.T, js string) []Step {
	t.Helper()
	var s []Step
	if err := Decode([]byte(js), &s); err != nil {
		t.Fatalf("steps %s: %v", js, err)
	}
	return s
}

func TestValidBaseHasNoIssues(t *testing.T) {
	if issues := Validate(baseDoc(t)); len(issues) > 0 {
		t.Fatalf("unexpected issues: %+v", issues)
	}
}

type vcase struct {
	name     string
	mutate   func(t *testing.T, d *Document)
	path     string // the issue path, exactly
	msg      string // a substring of the message
	severity string // defaults to error
}

func runCases(t *testing.T, cases []vcase) {
	t.Helper()
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			d := baseDoc(t)
			c.mutate(t, d)
			issues := Validate(d)
			sev := c.severity
			if sev == "" {
				sev = SeverityError
			}
			for _, is := range issues {
				if is.Path == c.path && strings.Contains(is.Message, c.msg) && is.Severity == sev {
					return
				}
			}
			t.Errorf("no %s at %q containing %q; got:\n%s", sev, c.path, c.msg, dump(issues))
		})
	}
}

func dump(issues []Issue) string {
	var b strings.Builder
	for _, is := range issues {
		fmt.Fprintf(&b, "  %s %s: %s\n", is.Severity, is.Path, is.Message)
	}
	return b.String()
}

func TestValidateStructure(t *testing.T) {
	runCases(t, []vcase{
		{"schema version", func(t *testing.T, d *Document) { d.SchemaVersion = 2 }, "schema_version", "unsupported schema version 2", ""},

		{"duplicate component", func(t *testing.T, d *Document) { d.Components = append(d.Components, Component{ID: "c"}) }, "components[c]", `duplicate component id "c"`, ""},
		{"invalid component id", func(t *testing.T, d *Document) { d.Components = append(d.Components, Component{ID: "Bad.Id"}) }, "components[Bad.Id].id", "invalid id", ""},
		{"unknown parent", func(t *testing.T, d *Document) { d.Components[2].Parent = "zz" }, "components[c].parent", `unknown component "zz"`, ""},
		{"parent cycle", func(t *testing.T, d *Document) { d.Components[0].Parent = "b" }, "components[a].parent", "parent chain forms a cycle", ""},
		{"parent cycle other member", func(t *testing.T, d *Document) { d.Components[0].Parent = "b" }, "components[b].parent", "parent chain forms a cycle", ""},
		{"self parent", func(t *testing.T, d *Document) { d.Components[2].Parent = "c" }, "components[c].parent", "cycle", ""},
		{"initial state mismatch", func(t *testing.T, d *Document) { d.Components[1].State.Initial["num"] = "three" }, "components[b].state.initial", "$.num: expected integer, got string", SeverityWarning},

		{"duplicate schema", func(t *testing.T, d *Document) {
			d.Schemas = append(d.Schemas, Schema{ID: "S", Schema: map[string]any{}})
		}, "schemas[S]", `duplicate schema id "S"`, ""},
		{"invalid schema id", func(t *testing.T, d *Document) {
			d.Schemas = append(d.Schemas, Schema{ID: "a b", Schema: map[string]any{}})
		}, "schemas[a b].id", "invalid schema id", ""},
		{"missing schema", func(t *testing.T, d *Document) { d.Schemas = append(d.Schemas, Schema{ID: "U"}) }, "schemas[U].schema", "schema is required", ""},
		{"unresolved nested ref", func(t *testing.T, d *Document) {
			d.Schemas[1].Schema["properties"].(map[string]any)["s"] = map[string]any{"$ref": "Nope"}
		}, "schemas[T].schema.properties.s", `unresolved $ref "Nope"`, ""},
		{"unresolved ref in array", func(t *testing.T, d *Document) {
			d.Schemas[1].Schema["anyOf"] = []any{map[string]any{"$ref": "S"}, map[string]any{"$ref": "#/schemas/Q"}}
		}, "schemas[T].schema.anyOf[1]", `unresolved $ref "#/schemas/Q"`, ""},

		{"interface unknown component", func(t *testing.T, d *Document) {
			d.Interfaces = append(d.Interfaces, Interface{Component: "zz", Name: "q"})
		}, "interfaces[zz.q].component", `unknown component "zz"`, ""},
		{"interface invalid name", func(t *testing.T, d *Document) {
			d.Interfaces = append(d.Interfaces, Interface{Component: "c", Name: "Get"})
		}, "interfaces[c.Get].name", `invalid name "Get"`, ""},
		{"interface id mismatch", func(t *testing.T, d *Document) {
			d.Interfaces = append(d.Interfaces, Interface{ID: "c.other", Component: "c", Name: "get"})
		}, "interfaces[c.other].id", `id must be "c.get"`, ""},
		{"interface id only component", func(t *testing.T, d *Document) {
			d.Interfaces = append(d.Interfaces, Interface{ID: "c"})
		}, "interfaces[c].name", "invalid name", ""},
		{"duplicate interface", func(t *testing.T, d *Document) {
			d.Interfaces = append(d.Interfaces, Interface{Component: "b", Name: "z"})
		}, "interfaces[b.z]", `duplicate interface id "b.z"`, ""},
		{"unknown request schema", func(t *testing.T, d *Document) { d.Interfaces[1].Request = "Nope" }, "interfaces[b.yy].request", `unknown schema "Nope"`, ""},
		{"unknown pointer schema", func(t *testing.T, d *Document) { d.Interfaces[1].Response = "#/schemas/Nope" }, "interfaces[b.yy].response", "unknown schema", ""},
		{"inline schema unresolved ref", func(t *testing.T, d *Document) {
			d.Interfaces[1].Response = map[string]any{"items": map[string]any{"$ref": "Nope"}}
		}, "interfaces[b.yy].response.items", `unresolved $ref "Nope"`, ""},
		{"schema of the wrong type", func(t *testing.T, d *Document) { d.Interfaces[1].Request = []any{} }, "interfaces[b.yy].request", "must be a schema id or an inline JSON Schema object", ""},
		{"error without code", func(t *testing.T, d *Document) {
			d.Interfaces[0].Errors = append(d.Interfaces[0].Errors, ErrorSpec{Status: 500})
		}, "interfaces[a.x].errors[1].code", "code is required", ""},
		{"latency min above max", func(t *testing.T, d *Document) { d.Interfaces[0].LatencyMS = &Latency{Min: 5, Max: 1} }, "interfaces[a.x].latency_ms", "needs 0 <= min <= max", ""},
		{"negative latency", func(t *testing.T, d *Document) { d.Interfaces[0].LatencyMS = &Latency{Min: -1, Max: -1} }, "interfaces[a.x].latency_ms", "needs 0 <= min <= max", ""},

		{"invalid link id", func(t *testing.T, d *Document) { d.Links = append(d.Links, Link{ID: "L", From: "a", To: "b"}) }, "links[L].id", "invalid id", ""},
		{"duplicate link", func(t *testing.T, d *Document) { d.Links = append(d.Links, Link{ID: "l1", From: "a", To: "b"}) }, "links[l1]", `duplicate link id "l1"`, ""},
		{"unknown link from", func(t *testing.T, d *Document) { d.Links[0].From = "zz" }, "links[l1].from", `unknown component or interface "zz"`, ""},
		{"unknown link to", func(t *testing.T, d *Document) { d.Links[0].To = "b.nope" }, "links[l1].to", `unknown component or interface "b.nope"`, ""},

		{"invalid flow id", func(t *testing.T, d *Document) { d.Flows = append(d.Flows, Flow{ID: "F", Steps: d.Flows[1].Steps}) }, "flows[F].id", "invalid id", ""},
		{"duplicate flow", func(t *testing.T, d *Document) { d.Flows = append(d.Flows, d.Flows[1]) }, "flows[narrative]", `duplicate flow id "narrative"`, ""},
		{"unknown entry caller", func(t *testing.T, d *Document) { d.Flows[0].Entry.Caller = "zz" }, "flows[f].entry.caller", `unknown component "zz"`, ""},
		{"unknown entry interface", func(t *testing.T, d *Document) { d.Flows[0].Entry.Interface = "a.nope" }, "flows[f].entry.interface", `unknown interface "a.nope"`, ""},
		{"invalid entry input", func(t *testing.T, d *Document) { d.Flows[0].Entry.Input = []byte(`{"n": "= 1 +"}`) }, "flows[f].entry.input", "invalid expression", ""},
		{"flow step unknown component", func(t *testing.T, d *Document) { d.Flows[1].Steps[0].Component = "zz" }, "flows[narrative].steps[0].component", `unknown component "zz"`, ""},
		{"flow step without title", func(t *testing.T, d *Document) { d.Flows[1].Steps[0].Title = "" }, "flows[narrative].steps[0].title", "title is required", ""},
		{"empty flow", func(t *testing.T, d *Document) { d.Flows = append(d.Flows, Flow{ID: "empty"}) }, "flows[empty]", "needs an entry to simulate or steps", ""},

		{"invalid scenario id", func(t *testing.T, d *Document) { d.Scenarios = append(d.Scenarios, Scenario{ID: "S!", Flow: "f"}) }, "scenarios[S!].id", "invalid id", ""},
		{"duplicate scenario", func(t *testing.T, d *Document) { d.Scenarios = append(d.Scenarios, Scenario{ID: "s", Flow: "f"}) }, "scenarios[s]", `duplicate scenario id "s"`, ""},
		{"scenario unknown flow", func(t *testing.T, d *Document) { d.Scenarios[0].Flow = "nope" }, "scenarios[s].flow", `unknown flow "nope"`, ""},
		{"scenario flow without entry", func(t *testing.T, d *Document) { d.Scenarios[0].Flow = "narrative" }, "scenarios[s].flow", `flow "narrative" has no entry`, ""},
		{"scenario invalid input", func(t *testing.T, d *Document) { d.Scenarios[0].Input = []byte(`["= )"]`) }, "scenarios[s].input", "invalid expression", ""},
		{"unknown choice key", func(t *testing.T, d *Document) { d.Scenarios[0].Choices["a.x.nope"] = ChoiceOf("fast") }, "scenarios[s].choices.a.x.nope", "unknown choice point", ""},
		{"choice key on unknown interface", func(t *testing.T, d *Document) { d.Scenarios[0].Choices["route"] = ChoiceOf("fast") }, "scenarios[s].choices.route", "keys are <interface>.<choice>", ""},
		{"unknown choice option", func(t *testing.T, d *Document) { d.Scenarios[0].Choices["a.x.route"] = ChoiceOf("warp") }, "scenarios[s].choices.a.x.route", `option "warp" is not one of fast, slow`, ""},
		{"unknown state component", func(t *testing.T, d *Document) { d.Scenarios[0].State["zz"] = map[string]any{} }, "scenarios[s].state.zz", `unknown component "zz"`, ""},
		{"fault unknown target", func(t *testing.T, d *Document) { d.Scenarios[0].Faults[0].Target = "zz" }, "scenarios[s].faults[0].target", `unknown component or interface "zz"`, ""},
		{"fault type", func(t *testing.T, d *Document) { d.Scenarios[0].Faults[0].Type = "explode" }, "scenarios[s].faults[0].type", "type is one of unavailable, error, latency, timeout", ""},
		{"error fault without code", func(t *testing.T, d *Document) { d.Scenarios[0].Faults[1].Code = "" }, "scenarios[s].faults[1].code", "an error fault needs a code", ""},
		{"latency fault without latency", func(t *testing.T, d *Document) { d.Scenarios[0].Faults[2].LatencyMS = 0 }, "scenarios[s].faults[2].latency_ms", "latency_ms > 0", ""},
		{"fault call zero", func(t *testing.T, d *Document) { d.Scenarios[0].Faults[1].Calls = []int{0, 2} }, "scenarios[s].faults[1].calls", "call numbers start at 1", ""},
		{"invalid expectation", func(t *testing.T, d *Document) { d.Scenarios[0].Expect = append(d.Scenarios[0].Expect, "result.ok &&") }, "scenarios[s].expect[1]", "invalid expression", ""},
		{"expectation with behavior variable", func(t *testing.T, d *Document) { d.Scenarios[0].Expect = []string{"input.n == 1"} }, "scenarios[s].expect[0]", "undeclared reference", ""},
	})
}

func TestValidateBehavior(t *testing.T) {
	set := func(js string) func(t *testing.T, d *Document) {
		return func(t *testing.T, d *Document) { d.Interfaces[2].Behavior = steps(t, js) }
	}
	const p = "interfaces[b.z].behavior"
	nested := strings.Repeat(`[{"if": "true", "then": `, 34) + `[{"return": 1}]` + strings.Repeat("}]", 34)
	runCases(t, []vcase{
		{"two actions", set(`[{"set": {"vars.a": 1}, "return": 1}]`), p + "[0]", "a step has one action; this one has set, return", ""},
		{"no action or title", set(`[{}]`), p + "[0]", "a step needs an action or a title", ""},
		{"only when", set(`[{"when": "true"}]`), p + "[0]", "a step needs an action or a title", ""},
		{"invalid when", set(`[{"title": "t", "when": "1 +"}]`), p + "[0].when", "invalid expression", ""},
		{"input without call", set(`[{"set": {"vars.a": 1}, "input": {}}]`), p + "[0].input", "input goes with call or emit", ""},
		{"fill without call", set(`[{"return": 1, "fill": true}]`), p + "[0].fill", "fill goes with call", ""},
		{"fill on emit", set(`[{"emit": "b.yy", "input": {"n": 1}, "fill": true}]`), p + "[0].fill", "fill goes with call", ""},
		{"as without call", set(`[{"emit": "b.yy", "as": "r"}]`), p + "[0]", "as, retry, on_error, timeout_ms and targets go with call", ""},
		{"retry without call", set(`[{"return": 1, "retry": {"max_attempts": 2}}]`), p + "[0]", "go with call", ""},
		{"on_error without call", set(`[{"return": 1, "on_error": "continue"}]`), p + "[0]", "go with call", ""},
		{"timeout without call", set(`[{"return": 1, "timeout_ms": 5}]`), p + "[0]", "go with call", ""},
		{"targets without call", set(`[{"return": 1, "targets": ["b.yy"]}]`), p + "[0]", "go with call", ""},
		{"then without if", set(`[{"return": 1, "then": []}]`), p + "[0]", "then and else go with if", ""},
		{"else without if", set(`[{"return": 1, "else": [{"return": 2}]}]`), p + "[0]", "then and else go with if", ""},
		{"options without choice", set(`[{"return": 1, "options": {"a": []}}]`), p + "[0]", "options and default go with choice", ""},
		{"default without choice", set(`[{"return": 1, "default": "a"}]`), p + "[0]", "options and default go with choice", ""},

		{"set root", set(`[{"set": {"input.a": 1}}]`), p + "[0].set.input.a", "must start with vars., ctx. or state.", ""},
		{"set root only", set(`[{"set": {"vars": 1}}]`), p + "[0].set.vars", "must start with vars., ctx. or state.", ""},
		{"set bad segment", set(`[{"set": {"state.a-b": 1}}]`), p + "[0].set.state.a-b", `invalid path segment "a-b"`, ""},
		{"set empty segment", set(`[{"set": {"ctx..a": 1}}]`), p + "[0].set.ctx..a", `invalid path segment ""`, ""},
		{"set invalid expression", set(`[{"set": {"vars.a": {"b": ["= 1 +"]}}}]`), p + "[0].set.vars.a", "invalid expression", ""},

		{"unknown call", set(`[{"call": "b.nope"}]`), p + "[0].call", `unknown interface "b.nope"`, ""},
		{"invalid dynamic call", set(`[{"call": "= 1 +", "targets": ["b.yy"]}]`), p + "[0].call", "invalid expression", ""},
		{"empty dynamic call", set(`[{"call": "=", "targets": ["b.yy"]}]`), p + "[0].call", "empty expression", ""},
		{"dynamic call without targets", set(`[{"call": "= 'b.yy'"}]`), p + "[0].targets", "dynamic call without targets", SeverityWarning},
		{"unknown target", set(`[{"call": "= 'b.yy'", "targets": ["b.yy", "b.q"]}]`), p + "[0].targets[1]", `unknown interface "b.q"`, ""},
		{"invalid call input", set(`[{"call": "b.yy", "input": {"a": "= input."}}]`), p + "[0].input", "invalid expression", ""},
		{"invalid as", set(`[{"call": "b.yy", "as": "my-var"}]`), p + "[0].as", `invalid variable name "my-var"`, ""},
		{"negative timeout", set(`[{"call": "b.yy", "timeout_ms": -1}]`), p + "[0].timeout_ms", "must not be negative", ""},
		{"retry without max_attempts", set(`[{"call": "b.yy", "retry": {"backoff_ms": 5}}]`), p + "[0].retry.max_attempts", "max_attempts is required", ""},
		{"retry zero attempts", set(`[{"call": "b.yy", "retry": {"max_attempts": 0}}]`), p + "[0].retry.max_attempts", "must be between 1 and 20", ""},
		{"retry too many attempts", set(`[{"call": "b.yy", "retry": {"max_attempts": 21}}]`), p + "[0].retry.max_attempts", "must be between 1 and 20", ""},
		{"retry literal string", set(`[{"call": "b.yy", "retry": {"max_attempts": "three"}}]`), p + "[0].retry.max_attempts", "a number or an expression", ""},
		{"retry fractional", set(`[{"call": "b.yy", "retry": {"max_attempts": 2.5}}]`), p + "[0].retry.max_attempts", "a whole number or an expression", ""},
		{"retry invalid expression", set(`[{"call": "b.yy", "retry": {"max_attempts": "= size("}}]`), p + "[0].retry.max_attempts", "invalid expression", ""},
		{"retry negative backoff", set(`[{"call": "b.yy", "retry": {"max_attempts": 2, "backoff_ms": -1}}]`), p + "[0].retry", "backoff values must not be negative", ""},
		{"retry negative multiplier", set(`[{"call": "b.yy", "retry": {"max_attempts": 2, "multiplier": -2}}]`), p + "[0].retry", "backoff values must not be negative", ""},
		{"retry unknown jitter", set(`[{"call": "b.yy", "retry": {"max_attempts": 2, "backoff_ms": 10, "jitter": "half"}}]`), p + "[0].retry.jitter", "jitter is none, full or equal", ""},
		{"retry invalid when", set(`[{"call": "b.yy", "retry": {"max_attempts": 2, "when": "error.code =="}}]`), p + "[0].retry.when", "invalid expression", ""},
		{"on_error mode", set(`[{"call": "b.yy", "on_error": "ignore"}]`), p + "[0].on_error", "on_error is propagate, continue or a list of steps", ""},
		{"on_error steps are checked", set(`[{"call": "b.yy", "on_error": [{"call": "b.nope"}]}]`), p + "[0].on_error[0].call", `unknown interface "b.nope"`, ""},

		{"invalid if", set(`[{"if": "vars.", "then": []}]`), p + "[0].if", "invalid expression", ""},
		{"then steps are checked", set(`[{"if": "true", "then": [{"return": "= 1 +"}]}]`), p + "[0].then[0].return", "invalid expression", ""},
		{"else steps are checked", set(`[{"if": "true", "else": [{"emit": "b.nope"}]}]`), p + "[0].else[0].emit", `unknown interface "b.nope"`, ""},

		{"choice without options", set(`[{"choice": "c"}]`), p + "[0].options", "a choice needs at least one option", ""},
		{"choice without default", set(`[{"choice": "c", "options": {"a": [], "b": []}}]`), p + "[0].default", "a choice with several options needs a default", ""},
		{"default not an option", set(`[{"choice": "c", "default": "z", "options": {"a": [], "b": []}}]`), p + "[0].default", `default "z" is not an option`, ""},
		{"invalid default expression", set(`[{"choice": "c", "default": "= (", "options": {"a": [], "b": []}}]`), p + "[0].default", "invalid expression", ""},
		{"invalid choice name", set(`[{"choice": "my-choice", "options": {"a": []}}]`), p + "[0].choice", `invalid choice name "my-choice"`, ""},
		{"invalid option name", set(`[{"choice": "c", "options": {"a b": []}}]`), p + "[0].options.a b", "invalid option name", ""},
		{"option steps are checked", set(`[{"choice": "c", "options": {"a": [{"wait": -1}]}}]`), p + "[0].options.a[0].wait", "must not be negative", ""},
		{"duplicate choice", set(`[{"choice": "c", "options": {"a": []}}, {"choice": "c", "options": {"a": []}}]`), p + "[1].choice", `choice "c" is declared twice in b.z`, ""},
		{"duplicate nested choice", set(`[{"if": "true", "then": [{"choice": "c", "options": {"a": []}}], "else": [{"choice": "c", "options": {"a": []}}]}]`), p + "[0].else[0].choice", "declared twice", ""},
		{"duplicate choice inside options", set(`[{"choice": "c", "options": {"a": [{"choice": "c", "options": {"b": []}}]}}]`), p + "[0].options.a[0].choice", "declared twice", ""},

		{"invalid return", set(`[{"return": {"a": "= ]"}}]`), p + "[0].return", "invalid expression", ""},
		{"fail without code", set(`[{"fail": {"message": "m"}}]`), p + "[0].fail", "fail needs an object with a code, or an expression", ""},
		{"fail with literal string", set(`[{"fail": "boom"}]`), p + "[0].fail", "fail needs an object with a code", ""},
		{"fail invalid expression", set(`[{"fail": {"code": "x", "message": "= 'a' +"}}]`), p + "[0].fail", "invalid expression", ""},
		{"unknown emit", set(`[{"emit": "b.nope"}]`), p + "[0].emit", `unknown interface "b.nope"`, ""},
		{"invalid emit input", set(`[{"emit": "b.yy", "input": "= ("}]`), p + "[0].input", "invalid expression", ""},
		{"negative wait", set(`[{"wait": -5}]`), p + "[0].wait", "wait must not be negative", ""},
		{"literal string wait", set(`[{"wait": "soon"}]`), p + "[0].wait", "wait is milliseconds or an expression", ""},
		{"negative fractional wait", set(`[{"wait": -1.5}]`), p + "[0].wait", "wait must not be negative", ""},
		{"invalid wait expression", set(`[{"wait": "= now +"}]`), p + "[0].wait", "invalid expression", ""},
		{"nesting depth", set(nested), p + strings.Repeat("[0].then", 33), "steps nest deeper than 32", ""},
	})
}

func TestValidateAcceptsEdgeForms(t *testing.T) {
	for name, js := range map[string]string{
		"single option without default": `[{"choice": "c", "options": {"only": [{"return": 1}]}}]`,
		"expression default":            `[{"choice": "c", "default": "= input.mode", "options": {"a": [], "b": []}}]`,
		"title only":                    `[{"title": "t"}]`,
		"detail only":                   `[{"detail": "d"}]`,
		"max attempts 20":               `[{"call": "b.yy", "retry": {"max_attempts": 20}}]`,
		"max attempts 1":                `[{"call": "b.yy", "retry": {"max_attempts": 1}}]`,
		"explicit propagate":            `[{"call": "b.yy", "on_error": "propagate"}]`,
		"fill":                          `[{"call": "b.yy", "input": {"a": 1}, "fill": true}]`,
		"wait zero":                     `[{"wait": 0}]`,
		"return null":                   `[{"return": null}]`,
		"fail expression":               `[{"fail": "= {'code': 'x'}"}]`,
		"emit without input":            `[{"emit": "b.yy"}]`,
		"emit with input":               `[{"emit": "b.yy", "input": {"n": 1}}]`,
	} {
		d := baseDoc(t)
		d.Interfaces[2].Behavior = steps(t, js)
		if issues := Validate(d); len(issues) > 0 {
			t.Errorf("%s: unexpected issues:\n%s", name, dump(issues))
		}
	}
}

func TestValidateSortsByPathAndHasErrors(t *testing.T) {
	d := baseDoc(t)
	d.Links[0].To = "zz"
	d.Components[2].Parent = "zz"
	d.Interfaces[2].Behavior = steps(t, `[{"call": "= 'b.yy'"}]`)
	issues := Validate(d)
	for i := 1; i < len(issues); i++ {
		if issues[i-1].Path > issues[i].Path {
			t.Fatalf("issues are not sorted by path:\n%s", dump(issues))
		}
	}
	if !HasErrors(issues) {
		t.Error("HasErrors is false")
	}
	if HasErrors([]Issue{{Severity: SeverityWarning}}) || HasErrors(nil) {
		t.Error("warnings alone are not errors")
	}
}

func TestValidateFaults(t *testing.T) {
	d := baseDoc(t)
	issues := ValidateFaults(d, []Fault{
		{Target: "b", Type: "unavailable"},
		{Target: "b.yy", Type: "error"},
		{Target: "nowhere", Type: "latency"},
		{Target: "b.z", Type: "timeout", Calls: []int{-1}},
	})
	want := map[string]string{
		"faults[1].code":       "an error fault needs a code",
		"faults[2].target":     "unknown component or interface",
		"faults[2].latency_ms": "latency_ms > 0",
		"faults[3].calls":      "call numbers start at 1",
	}
	if len(issues) != len(want) {
		t.Fatalf("got:\n%s", dump(issues))
	}
	for _, is := range issues {
		if !strings.Contains(is.Message, want[is.Path]) || want[is.Path] == "" {
			t.Errorf("unexpected %s: %s", is.Path, is.Message)
		}
	}
	if issues := ValidateFaults(d, nil); len(issues) != 0 {
		t.Errorf("got %v", issues)
	}
}

func TestValidOptionAndSchemaID(t *testing.T) {
	for s, want := range map[string]bool{"a": true, "Fast-1_x": true, "": false, "a b": false, "a.b": false, strings.Repeat("o", 65): false} {
		if ValidOption(s) != want {
			t.Errorf("ValidOption(%q) = %v", s, !want)
		}
	}
	for s, want := range map[string]bool{"ChatRequest": true, "v1.Thing-x_y": true, "": false, "a/b": false, "a b": false, strings.Repeat("s", 129): false} {
		if ValidSchemaID(s) != want {
			t.Errorf("ValidSchemaID(%q) = %v", s, !want)
		}
	}
}

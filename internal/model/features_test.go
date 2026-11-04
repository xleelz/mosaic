package model

import (
	"reflect"
	"strings"
	"testing"
)

func TestValidateStore(t *testing.T) {
	store := func(js string) func(t *testing.T, d *Document) {
		return func(t *testing.T, d *Document) {
			var st StoreSpec
			if err := Decode([]byte(js), &st); err != nil {
				t.Fatal(err)
			}
			d.Interfaces[2].Store = &st // b.z, a stub
			d.Interfaces[2].Errors = []ErrorSpec{{Code: "missing", Status: 404}}
		}
	}
	const p = "interfaces[b.z].store"
	runCases(t, []vcase{
		{"table", store(`{"table": "my-rows", "op": "get", "key": "k"}`), p + ".table", "table must be an identifier", ""},
		{"op", store(`{"table": "rows", "op": "scan"}`), p + ".op", "op is one of get, put, update, delete, query, incr", ""},
		{"get without key", store(`{"table": "rows", "op": "get"}`), p + ".key", "get needs a key", ""},
		{"query with key", store(`{"table": "rows", "op": "query", "key": "k"}`), p + ".key", "query reads the whole table", ""},
		{"put without value", store(`{"table": "rows", "op": "put", "key": "k"}`), p + ".value", "put needs a value", ""},
		{"get with value", store(`{"table": "rows", "op": "get", "key": "k", "value": 1}`), p + ".value", "value goes with put, update and incr", ""},
		{"incr with a string", store(`{"table": "rows", "op": "incr", "key": "k", "value": "one"}`), p + ".value", "incr adds a number or a map of numbers", ""},
		{"incr with a list", store(`{"table": "rows", "op": "incr", "key": "k", "value": [1]}`), p + ".value", "incr adds a number", ""},
		{"default on put", store(`{"table": "rows", "op": "put", "key": "k", "value": 1, "default": 2}`), p + ".default", "default goes with get", ""},
		{"not_found on put", store(`{"table": "rows", "op": "put", "key": "k", "value": 1, "not_found": "missing"}`), p + ".not_found", "not_found goes with get and update", ""},
		{"undeclared not_found", store(`{"table": "rows", "op": "get", "key": "k", "not_found": "gone"}`), p + ".not_found", `"gone" is not one of b.z's declared errors`, ""},
		{"conflict without where", store(`{"table": "rows", "op": "put", "key": "k", "value": 1, "conflict": "missing"}`), p + ".conflict", "conflict goes with a write that has a where", ""},
		{"undeclared conflict", store(`{"table": "rows", "op": "put", "key": "k", "value": 1, "where": "row == null", "conflict": "taken"}`), p + ".conflict", `"taken" is not one of`, ""},
		{"invalid key", store(`{"table": "rows", "op": "get", "key": "= input."}`), p + ".key", "invalid expression", ""},
		{"invalid value", store(`{"table": "rows", "op": "put", "key": "k", "value": {"a": "= ("}}`), p + ".value", "invalid expression", ""},
		{"invalid default", store(`{"table": "rows", "op": "get", "key": "k", "default": "= )"}`), p + ".default", "invalid expression", ""},
		{"invalid where", store(`{"table": "rows", "op": "query", "where": "row."}`), p + ".where", "invalid expression", ""},
		{"where sees only store variables", store(`{"table": "rows", "op": "query", "where": "result.ok"}`), p + ".where", "undeclared reference", ""},
		{"store beside a behavior", func(t *testing.T, d *Document) {
			d.Interfaces[0].Store = &StoreSpec{Table: "rows", Op: "query"}
		}, "interfaces[a.x].store", "the behavior runs instead of the store operation", SeverityWarning},
	})
	for name, js := range map[string]string{
		"get":             `{"table": "rows", "op": "get", "key": "= input.id", "where": "row.org == input.org", "not_found": "missing"}`,
		"get default":     `{"table": "rows", "op": "get", "key": 7, "default": {"n": 0}}`,
		"put":             `{"table": "rows", "op": "put", "key": "= input.id", "value": "= input", "where": "row == null", "conflict": "missing"}`,
		"update":          `{"table": "rows", "op": "update", "key": "k", "value": {"status": "done"}}`,
		"delete":          `{"table": "rows", "op": "delete", "key": "k"}`,
		"query":           `{"table": "rows", "op": "query", "where": "key.startsWith('a') && row.n > 1"}`,
		"incr number":     `{"table": "rows", "op": "incr", "key": "k", "value": 1}`,
		"incr map":        `{"table": "rows", "op": "incr", "key": "k", "value": {"done": "= input.n", "failed": 1}}`,
		"incr expression": `{"table": "rows", "op": "incr", "key": "k", "value": "= input.n"}`,
	} {
		d := baseDoc(t)
		store(js)(t, d)
		if issues := Validate(d); len(issues) > 0 {
			t.Errorf("%s: unexpected issues:\n%s", name, dump(issues))
		}
	}
}

func TestValidateForeachAndRepeat(t *testing.T) {
	set := func(js string) func(t *testing.T, d *Document) {
		return func(t *testing.T, d *Document) { d.Interfaces[2].Behavior = steps(t, js) }
	}
	const p = "interfaces[b.z].behavior"
	runCases(t, []vcase{
		{"literal string", set(`[{"foreach": "items", "steps": [{"wait": 1}]}]`), p + "[0].foreach", "foreach is a list or an expression", ""},
		{"number", set(`[{"foreach": 3, "steps": [{"wait": 1}]}]`), p + "[0].foreach", "foreach is a list or an expression", ""},
		{"invalid expression", set(`[{"foreach": "= input.", "steps": [{"wait": 1}]}]`), p + "[0].foreach", "invalid expression", ""},
		{"invalid literal item", set(`[{"foreach": ["= (", 2], "steps": [{"wait": 1}]}]`), p + "[0].foreach", "invalid expression", ""},
		{"invalid as", set(`[{"foreach": "= [1]", "as": "an-item", "steps": [{"wait": 1}]}]`), p + "[0].as", `invalid variable name "an-item"`, ""},
		{"invalid index", set(`[{"foreach": "= [1]", "index": "1i", "steps": [{"wait": 1}]}]`), p + "[0].index", `invalid variable name "1i"`, ""},
		{"same names", set(`[{"foreach": "= [1]", "as": "i", "index": "i", "steps": [{"wait": 1}]}]`), p + "[0].index", "different variables", ""},
		{"default names clash", set(`[{"foreach": "= [1]", "as": "index", "steps": [{"wait": 1}]}]`), p + "[0].index", "different variables", ""},
		{"max too large", set(`[{"foreach": "= [1]", "max": 1000001, "steps": [{"wait": 1}]}]`), p + "[0].max", "must be between 1 and 1000000", ""},
		{"negative max", set(`[{"foreach": "= [1]", "max": -1, "steps": [{"wait": 1}]}]`), p + "[0].max", "must be between 1 and 1000", ""},
		{"no steps", set(`[{"foreach": "= [1]"}]`), p + "[0].steps", "a foreach needs steps", ""},
		{"body is checked", set(`[{"foreach": "= [1]", "steps": [{"call": "b.nope"}]}]`), p + "[0].steps[0].call", `unknown interface "b.nope"`, ""},
		{"steps without foreach", set(`[{"return": 1, "steps": [{"wait": 1}]}]`), p + "[0]", "index, steps and max go with foreach", ""},
		{"max without foreach", set(`[{"return": 1, "max": 3}]`), p + "[0]", "index, steps and max go with foreach", ""},
		{"index without foreach", set(`[{"return": 1, "index": "i"}]`), p + "[0]", "index, steps and max go with foreach", ""},
		{"two actions", set(`[{"foreach": "= [1]", "wait": 1, "steps": [{"wait": 1}]}]`), p + "[0]", "this one has wait, foreach", ""},
		{"break outside a loop", set(`[{"break": true}]`), p + "[0].break", "break goes inside the steps of a foreach", ""},
		{"continue in if outside a loop", set(`[{"if": "true", "then": [{"continue": true}]}]`), p + "[0].then[0].continue", "continue goes inside", ""},
		{"break after a loop", set(`[{"foreach": "= [1]", "steps": [{"wait": 1}]}, {"break": true}]`), p + "[1].break", "break goes inside", ""},
		{"break with another action", set(`[{"foreach": "= [1]", "steps": [{"break": true, "return": 1}]}]`), p + "[0].steps[0]", "this one has return, break", ""},

		{"repeat zero", func(t *testing.T, d *Document) { d.Flows[0].Entry.Repeat = &Repeat{Count: 0} }, "flows[f].entry.repeat.count", "must be between 1 and 100", ""},
		{"repeat too many", func(t *testing.T, d *Document) { d.Flows[0].Entry.Repeat = &Repeat{Count: 101} }, "flows[f].entry.repeat.count", "must be between 1 and 100", ""},
		{"repeat negative interval", func(t *testing.T, d *Document) { d.Flows[0].Entry.Repeat = &Repeat{Count: 2, IntervalMS: -1} }, "flows[f].entry.repeat.interval_ms", "must not be negative", ""},
	})
	for name, js := range map[string]string{
		"expression":        `[{"foreach": "= input.items", "steps": [{"set": {"ctx.last": "= vars.item"}}]}]`,
		"literal list":      `[{"foreach": [1, "= 2"], "as": "n", "index": "i", "max": 1000, "steps": [{"wait": "= vars.n"}]}]`,
		"break, continue":   `[{"foreach": "= [1, 2]", "steps": [{"if": "vars.item == 1", "then": [{"continue": true}], "else": [{"break": true}]}]}]`,
		"break in on_error": `[{"foreach": "= [1]", "steps": [{"call": "b.yy", "on_error": [{"break": true}]}]}]`,
		"choice in a loop":  `[{"foreach": "= [1]", "steps": [{"choice": "c", "options": {"only": [{"break": true}]}}]}]`,
		"nested":            `[{"foreach": "= [1]", "steps": [{"foreach": "= [2]", "as": "j", "index": "jj", "steps": [{"continue": true}]}, {"break": true}]}]`,
	} {
		d := baseDoc(t)
		d.Interfaces[2].Behavior = steps(t, js)
		d.Flows[0].Entry.Repeat = &Repeat{Count: 100, IntervalMS: 0}
		if issues := Validate(d); len(issues) > 0 {
			t.Errorf("%s: unexpected issues:\n%s", name, dump(issues))
		}
	}
}

func TestForeachBodiesAreWalked(t *testing.T) {
	d := baseDoc(t)
	d.Interfaces[2].Behavior = steps(t, `[{"foreach": "= [1]", "steps": [{"choice": "inloop", "options": {"only": [{"call": "a.x"}]}}]}]`)
	x := NewIndex(d)
	if _, ok := x.ChoicePoints()["b.z.inloop"]; !ok {
		t.Error("a choice inside a foreach is not a choice point")
	}
	calls, _, _, _ := callTargets(x.Interfaces["b.z"], x.Subscribers)
	if !reflect.DeepEqual(calls, []string{"a.x"}) {
		t.Errorf("calls inside a foreach: got %v", calls)
	}
}

func TestPlanExcludesUnknownInterfaces(t *testing.T) {
	d, err := ParseDocument([]byte(`
components:
  - {id: client}
  - {id: svc}
  - {id: db, kind: datastore}
interfaces:
  - {component: svc, name: in, behavior: [{call: svc.gone}, {call: db.get}, {call: db.get}]}
  - {component: db, name: get, store: {table: rows, op: get, key: k}}
flows:
  - {id: main, entry: {caller: client, interface: svc.in}}
  - {id: broken, entry: {caller: client, interface: nowhere.in}}
`))
	if err != nil {
		t.Fatal(err)
	}
	x := NewIndex(d)
	p, err := x.Plan("main")
	if err != nil {
		t.Fatal(err)
	}
	check := func(name string, got, want any) {
		t.Helper()
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s: got %v, want %v", name, got, want)
		}
	}
	check("interfaces", p.Interfaces, []string{"db.get", "svc.in"})
	check("faultable", p.Faultable, []string{"db", "db.get", "svc", "svc.in"})
	check("unknown", p.Unknown, []string{"svc.gone"})
	// A datastore reached through store operations is seedable state.
	check("state", p.State, []StateInfo{{Component: "db"}})

	p, err = x.Plan("broken")
	if err != nil {
		t.Fatal(err)
	}
	check("broken interfaces", p.Interfaces, []string{})
	check("broken faultable", p.Faultable, []string{})
	check("broken unknown", p.Unknown, []string{"nowhere.in"})
	check("broken components", p.Components, []string{"client"})

	g := x.Graph()
	for _, n := range g.Nodes {
		if (n.ID == "db") != n.Stateful {
			t.Errorf("graph node %s: stateful %v", n.ID, n.Stateful)
		}
	}
}

func TestStoreAndLoopFieldsRoundTrip(t *testing.T) {
	src := `{"component":"db","name":"get","store":{"table":"rows","op":"get","key":"= input.id","default":{"n":0}},` +
		`"behavior":[{"foreach":"= [1]","as":"n","index":"i","max":5,"steps":[{"break":true},{"continue":true}]}]}`
	v, _, err := DecodeEntity(KindInterface, []byte(src))
	if err != nil {
		t.Fatal(err)
	}
	f := v.(Interface)
	if f.Store == nil || f.Store.Op != "get" || len(f.Behavior[0].Steps) != 2 || !f.Behavior[0].Steps[0].Break {
		t.Fatalf("decoded %+v", f)
	}
	var fl Flow
	if err := Decode([]byte(`{"id":"f","entry":{"caller":"c","interface":"a.x","repeat":{"count":3,"interval_ms":1000}}}`), &fl); err != nil {
		t.Fatal(err)
	}
	if *fl.Entry.Repeat != (Repeat{Count: 3, IntervalMS: 1000}) {
		t.Errorf("repeat %+v", fl.Entry.Repeat)
	}
	if err := Decode([]byte(`{"table":"rows","op":"get","bogus":1}`), &StoreSpec{}); err == nil || !strings.Contains(err.Error(), "bogus") {
		t.Errorf("unknown store field: %v", err)
	}
}

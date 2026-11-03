package main

import (
	"encoding/json"
	"errors"
	"flag"
	"io"
	"reflect"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

func boolp(b bool) *bool { return &b }

func intp(n int) *int { return &n }

func TestParseFault(t *testing.T) {
	for _, tc := range []struct {
		in   string
		want model.Fault
		err  string
	}{
		// Compact form.
		{in: "redis-ledger:unavailable", want: model.Fault{Target: "redis-ledger", Type: "unavailable"}},
		{in: "upstream-a.chat:error:upstream_error", want: model.Fault{Target: "upstream-a.chat", Type: "error", Code: "upstream_error"}},
		{in: "upstream-a.chat:error:upstream_error:502", want: model.Fault{Target: "upstream-a.chat", Type: "error", Code: "upstream_error", Status: 502}},
		{in: "upstream-a.chat:error:upstream_error:502@1", want: model.Fault{Target: "upstream-a.chat", Type: "error", Code: "upstream_error", Status: 502, Calls: []int{1}}},
		{in: "upstream-a.chat:timeout@1,3", want: model.Fault{Target: "upstream-a.chat", Type: "timeout", Calls: []int{1, 3}}},
		{in: " db:error::500 @ 2 , 4 ", want: model.Fault{Target: "db", Type: "error", Status: 500, Calls: []int{2, 4}}},
		{in: "db.query:latency:250", want: model.Fault{Target: "db.query", Type: "latency", LatencyMS: 250}},
		{in: "db.query:latency:250@2", want: model.Fault{Target: "db.query", Type: "latency", LatencyMS: 250, Calls: []int{2}}},
		{in: "worker.run:crash:2@1", want: model.Fault{Target: "worker.run", Type: "crash", AfterSteps: intp(2), Calls: []int{1}}},
		{in: "db.put:lost_reply", want: model.Fault{Target: "db.put", Type: "lost_reply"}},
		{in: "db.put:lost_reply:reset@1", want: model.Fault{Target: "db.put", Type: "lost_reply", Code: "reset", Calls: []int{1}}},
		{in: "worker.run:crash", err: "a crash fault is TARGET:crash:AFTER_STEPS"},
		{in: "worker.run:crash:-1", err: "after_steps must be a whole number"},
		{in: `{"target":"db","type":"crash"}`, err: "a crash fault needs after_steps"},
		{in: `{"target":"db","type":"error","code":"x","after_steps":1}`, err: "after_steps goes with a crash fault"},
		{in: "db", err: "want TARGET:TYPE"},
		{in: "db:error:c:500:extra", err: "want TARGET:TYPE"},
		{in: ":error", err: "missing target"},
		{in: "db:explode", err: `type must be one of unavailable, error, latency, timeout, lost_reply, crash, hang, got "explode"`},
		{in: "db:error:c:abc", err: "status must be an HTTP status code"},
		{in: "db:error:c:42", err: "status 42 is not an HTTP status code"},
		{in: "db:error@", err: "@ must be followed by call numbers"},
		{in: "db:error@0", err: "call numbers are integers from 1"},
		{in: "db:error@1,x", err: "call numbers are integers from 1"},
		{in: "db:latency", err: "needs a positive latency"},
		{in: "db:latency:soon", err: "latency must be whole milliseconds"},
		{in: "db:latency:5:503", err: "a latency fault is TARGET:latency:MS"},
		// JSON form.
		{in: `{"target":"db","type":"error","code":"deadlock","status":409,"retryable":true,"message":"m","calls":[2]}`,
			want: model.Fault{Target: "db", Type: "error", Code: "deadlock", Status: 409, Retryable: boolp(true), Message: "m", Calls: []int{2}}},
		{in: `{"target":"db.query","type":"latency","latency_ms":75}`, want: model.Fault{Target: "db.query", Type: "latency", LatencyMS: 75}},
		{in: `{"target":"db","type":"unavailable","retryable":false}`, want: model.Fault{Target: "db", Type: "unavailable", Retryable: boolp(false)}},
		{in: `{"target":"db","type":"error","colour":"red"}`, err: `unknown field "colour"`},
		{in: `{"target":"db","type":"error"`, err: "invalid fault JSON"},
		{in: `{"type":"error"}`, err: "missing target"},
		{in: `{"target":"db","type":"bogus"}`, err: "type must be one of"},
		{in: `{"target":"db","type":"error","calls":[0]}`, err: "call numbers start at 1"},
	} {
		got, err := parseFault(tc.in)
		if tc.err != "" {
			if err == nil || !strings.Contains(err.Error(), tc.err) {
				t.Errorf("parseFault(%q) error = %v, want %q", tc.in, err, tc.err)
			}
			continue
		}
		if err != nil {
			t.Errorf("parseFault(%q): %v", tc.in, err)
			continue
		}
		if !reflect.DeepEqual(got, tc.want) {
			t.Errorf("parseFault(%q) = %+v, want %+v", tc.in, got, tc.want)
		}
	}
}

func TestFaultFlagRepeats(t *testing.T) {
	var f faultFlag
	fs := flag.NewFlagSet("t", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	fs.Var(&f, "fault", "")
	if err := fs.Parse([]string{"--fault", "a:unavailable", "--fault", `{"target":"b","type":"timeout"}`}); err != nil {
		t.Fatal(err)
	}
	if len(f) != 2 || f[0].Target != "a" || f[1].Type != "timeout" {
		t.Errorf("faults = %+v", f)
	}
	if err := fs.Parse([]string{"--fault", "nope"}); err == nil {
		t.Error("expected an error")
	}
}

func TestStateFlag(t *testing.T) {
	for _, tc := range []struct {
		name string
		in   []string
		want string // JSON
		err  string
	}{
		{name: "number", in: []string{"redis-ledger.free_slots=0"}, want: `{"redis-ledger":{"free_slots":0}}`},
		{name: "nested paths merge", in: []string{"store.accounts.org.standing=suspended", "store.accounts.org.cents=20", "store.mode=strict"},
			want: `{"store":{"accounts":{"org":{"cents":20,"standing":"suspended"}},"mode":"strict"}}`},
		{name: "json values", in: []string{"c.b=true", "c.n=null", "c.f=1.5", "c.l=[1,\"x\"]", "c.o={\"k\":{\"z\":1}}", "c.s=\"quoted\""},
			want: `{"c":{"b":true,"f":1.5,"l":[1,"x"],"n":null,"o":{"k":{"z":1}},"s":"quoted"}}`},
		{name: "string fallback", in: []string{"c.s=hello world", "c.e=", "c.t=tru", "c.eq=a=b"},
			want: `{"c":{"e":"","eq":"a=b","s":"hello world","t":"tru"}}`},
		{name: "big numbers keep their text", in: []string{"c.n=12345678901234567890"}, want: `{"c":{"n":12345678901234567890}}`},
		{name: "several components", in: []string{"a.x=1", "b.y=2"}, want: `{"a":{"x":1},"b":{"y":2}}`},
		{name: "whole object without a path", in: []string{`metering={"records":3}`, "metering.extra=1"}, want: `{"metering":{"extra":1,"records":3}}`},
		{name: "later value wins", in: []string{"c.x=1", "c.x=2"}, want: `{"c":{"x":2}}`},
		{name: "no equals", in: []string{"c.x"}, err: "want COMPONENT.PATH=VALUE"},
		{name: "no component", in: []string{".x=1"}, err: "missing the component id"},
		{name: "no path and not an object", in: []string{"c=1"}, err: "VALUE must be a JSON object"},
		{name: "empty segment", in: []string{"c.a..b=1"}, err: "empty path segment"},
		{name: "trailing dot", in: []string{"c.a.=1"}, err: "empty path segment"},
		{name: "through a scalar", in: []string{"c.a=1", "c.a.b=2"}, err: "c.a is already set to a value that is not an object"},
	} {
		s := stateFlag{}
		var err error
		for _, in := range tc.in {
			if err = s.Set(in); err != nil {
				break
			}
		}
		if tc.err != "" {
			if err == nil || !strings.Contains(err.Error(), tc.err) {
				t.Errorf("%s: error = %v, want %q", tc.name, err, tc.err)
			}
			continue
		}
		if err != nil {
			t.Errorf("%s: %v", tc.name, err)
			continue
		}
		b, _ := json.Marshal(s)
		if string(b) != tc.want {
			t.Errorf("%s: state = %s, want %s", tc.name, b, tc.want)
		}
	}
}

func TestChoiceFlag(t *testing.T) {
	for _, tc := range []struct {
		in   []string
		want map[string]string
		err  string
	}{
		{in: []string{"throttle.check.rate_limit=exceeded"}, want: map[string]string{"throttle.check.rate_limit": "exceeded"}},
		{in: []string{"a.b.c=x", "d.e.f=y", "a.b.c=x"}, want: map[string]string{"a.b.c": "x", "d.e.f": "y"}},
		{in: []string{" a.b.c = x "}, want: map[string]string{"a.b.c": "x"}},
		{in: []string{"a.b.c"}, err: "want KEY=OPTION"},
		{in: []string{"=x"}, err: "want KEY=OPTION"},
		{in: []string{"a.b.c="}, err: "want KEY=OPTION"},
		{in: []string{"a.b.c=x", "a.b.c=y"}, err: "choice a.b.c is given twice (x and y)"},
	} {
		c := choiceFlag{}
		var err error
		for _, in := range tc.in {
			if err = c.Set(in); err != nil {
				break
			}
		}
		if tc.err != "" {
			if err == nil || !strings.Contains(err.Error(), tc.err) {
				t.Errorf("%v: error = %v, want %q", tc.in, err, tc.err)
			}
			continue
		}
		if err != nil || !reflect.DeepEqual(map[string]string(c), tc.want) {
			t.Errorf("%v: %v, %v", tc.in, c, err)
		}
	}
}

func TestParseInputFlag(t *testing.T) {
	yamlFile := writeFile(t, "in.yaml", "messages:\n  - role: user\n    content: hi\nstream: true\n")
	jsonFile := writeFile(t, "in.json", `{"stream": false}`)
	emptyFile := writeFile(t, "empty.yaml", "  \n")
	badFile := writeFile(t, "bad.yaml", "a: [1,\n")
	for _, tc := range []struct {
		in, want, err string
	}{
		{in: `{"stream":true}`, want: `{"stream":true}`},
		{in: ` [1, 2] `, want: `[1, 2]`},
		{in: `"text"`, want: `"text"`},
		{in: `42`, want: `42`},
		{in: "@" + yamlFile, want: `{"messages":[{"content":"hi","role":"user"}],"stream":true}`},
		{in: "@" + jsonFile, want: `{"stream": false}`},
		{in: `{stream: true}`, err: "--input: invalid JSON"},
		{in: `stream: true`, err: "pass @FILE for YAML"},
		{in: "@", err: "missing file name"},
		{in: "@/no/such/input.yaml", err: "no such file"},
		{in: "@" + emptyFile, err: "is empty"},
		{in: "@" + badFile, err: "invalid YAML"},
	} {
		got, err := parseInputFlag(tc.in)
		if tc.err != "" {
			var ie *inputError
			if err == nil || !strings.Contains(err.Error(), tc.err) || !errors.As(err, &ie) {
				t.Errorf("parseInputFlag(%q) error = %v, want an input error with %q", tc.in, err, tc.err)
			}
			continue
		}
		if err != nil || string(got) != tc.want {
			t.Errorf("parseInputFlag(%q) = %s, %v; want %s", tc.in, got, err, tc.want)
		}
	}
}

func TestSplitEntities(t *testing.T) {
	for _, tc := range []struct {
		kind, in string
		single   bool
		id       string
		n        int
		err      string
	}{
		{kind: "component", in: `{"id":"a","name":"A"}`, single: true, id: "a"},
		{kind: "interface", in: `{"component":"svc","name":"get"}`, single: true, id: "svc.get"},
		{kind: "interface", in: `{"id":"svc.other","component":"svc","name":"get"}`, single: true, id: "svc.other"},
		{kind: "link", in: `[{"id":"a"},{"id":"b"},{"id":"c"}]`, n: 3},
		{kind: "schema", in: `{"items":[{"id":"a"}]}`, n: 1},
		{kind: "component", in: `{"name":"A"}`, err: `the component has no "id"`},
		{kind: "interface", in: `{"name":"get"}`, err: `give "id" or "component" and "name"`},
		{kind: "flow", in: `[]`, err: "the entity list is empty"},
		{kind: "flow", in: `{"items":{}}`, err: `"items" must be a list`},
		{kind: "flow", in: `true`, err: "want an entity object"},
	} {
		items, single, id, err := splitEntities(tc.kind, json.RawMessage(tc.in))
		if tc.err != "" {
			if err == nil || !strings.Contains(err.Error(), tc.err) {
				t.Errorf("%s %s: error = %v, want %q", tc.kind, tc.in, err, tc.err)
			}
			continue
		}
		if err != nil || single != tc.single || id != tc.id || len(items) != tc.n {
			t.Errorf("%s %s = %d items, single %v, id %q, %v", tc.kind, tc.in, len(items), single, id, err)
		}
	}
}

func TestParseFlagsInterspersed(t *testing.T) {
	for _, tc := range []struct {
		args    []string
		pos     []string
		rev     string
		yes     bool
		wantErr string
	}{
		{args: []string{"ont", "comp", "id"}, pos: []string{"ont", "comp", "id"}},
		{args: []string{"--rev", "3", "ont", "comp"}, pos: []string{"ont", "comp"}, rev: "3"},
		{args: []string{"ont", "--rev=latest", "comp", "--yes"}, pos: []string{"ont", "comp"}, rev: "latest", yes: true},
		{args: []string{"ont", "-rev", "2", "comp"}, pos: []string{"ont", "comp"}, rev: "2"},
		{args: []string{"ont", "--", "--rev", "x"}, pos: []string{"ont", "--rev", "x"}},
		{args: []string{"ont", "--nope"}, wantErr: "flag provided but not defined: -nope"},
		{args: []string{"ont", "--rev"}, wantErr: "flag needs an argument: -rev"},
	} {
		fs := flag.NewFlagSet("t", flag.ContinueOnError)
		fs.SetOutput(io.Discard)
		rev := fs.String("rev", "", "")
		yes := fs.Bool("yes", false, "")
		pos, err := parseFlags(fs, tc.args)
		if tc.wantErr != "" {
			var ue *usageError
			if err == nil || !strings.Contains(err.Error(), tc.wantErr) || !errors.As(err, &ue) {
				t.Errorf("%v: error = %v, want a usage error with %q", tc.args, err, tc.wantErr)
			}
			continue
		}
		if err != nil || !reflect.DeepEqual(pos, tc.pos) || *rev != tc.rev || *yes != tc.yes {
			t.Errorf("%v: pos %q rev %q yes %v err %v", tc.args, pos, *rev, *yes, err)
		}
	}
	fs := flag.NewFlagSet("t", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	if _, err := parseFlags(fs, []string{"x", "--help"}); !errors.Is(err, flag.ErrHelp) {
		t.Errorf("--help: %v", err)
	}
}

func TestCheckRev(t *testing.T) {
	for _, ok := range []string{"", "draft", "latest", "1", "42"} {
		if err := checkRev("rev", ok); err != nil {
			t.Errorf("checkRev(%q): %v", ok, err)
		}
	}
	for _, bad := range []string{"0", "-1", "head", "r3", "1.5", "Draft"} {
		if err := checkRev("rev", bad); err == nil {
			t.Errorf("checkRev(%q) accepted", bad)
		}
	}
}

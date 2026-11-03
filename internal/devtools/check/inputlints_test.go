package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

func docFixture(t *testing.T, y string) (*model.Document, map[string]string) {
	t.Helper()
	d, err := model.ParseDocument([]byte(y))
	if err != nil {
		t.Fatal(err)
	}
	res, err := merge.Merge([]merge.Input{{Name: "a.yaml", Doc: d}})
	if err != nil || len(res.Conflicts) > 0 {
		t.Fatal(err, res.Conflicts)
	}
	for _, is := range model.Validate(res.Doc) {
		if is.Severity == model.SeverityError {
			t.Fatalf("%s: %s", is.Path, is.Message)
		}
	}
	return res.Doc, res.Origins
}

const unknownInputsDoc = `schema_version: 1
components:
  - {id: cli}
  - {id: tb}
schemas:
  - id: run-req
    schema:
      type: object
      properties:
        tool: {type: string}
        args:
          type: object
          properties: {path: {type: string}, mode: {type: string}}
        items: {type: array, items: {type: object, properties: {n: {type: integer}}}}
        authorization: {type: string}
        meta: {type: object}
        open: {type: object, properties: {a: {type: string}}, additionalProperties: true}
interfaces:
  - {component: tb, name: run, request: run-req, attributes: {path: /run, method: POST}, behavior: [{return: {ok: true}}]}
flows:
  - id: f
    entry: {caller: cli, interface: tb.run, input: {tool: ls, token: abc}}
scenarios:
  - id: old-shape
    flow: f
    input: {token: abc, input: {path: /}}
  - id: nested
    flow: f
    input:
      tool: ls
      args: {path: /, Mode: x}
      items: [{n: 1}, {m: 2}]
      Authorization: Bearer x
      x_org_id: o1
      meta: {anything: 1}
      open: {b: 1}
      $comment: skipped
  - id: steps
    steps:
      - {interface: tb.run, caller: cli, input: {tool: "= 'ls'", args: {$absent: true}, extra: 1}}
      - {flow: f, input: {tool: ls}}
`

func TestLintUnknownInputs(t *testing.T) {
	doc, origins := docFixture(t, unknownInputsDoc)
	r := lintUnknownInputs(doc, origins)
	var got []string
	for _, f := range r.Findings {
		got = append(got, f.Subject+": "+f.Why[:strings.Index(f.Why, ":")])
	}
	want := []string{
		"flow f entry: input.token",
		"scenario nested: input.args.Mode",
		"scenario nested: input.items[1].m",
		"scenario old-shape: input.input",
		"scenario old-shape: input.token",
		"scenario steps step 0: input.extra",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("got:\n%s\nwant:\n%s\n%+v", strings.Join(got, "\n"), strings.Join(want, "\n"), r.Findings)
	}
	for _, f := range r.Findings {
		if strings.Contains(f.Why, "input.args.Mode") && !strings.Contains(f.Why, `it declares "mode"`) {
			t.Errorf("no near-miss hint: %s", f.Why)
		}
	}
	var b bytes.Buffer
	r.print(&b, -1, true)
	if !strings.Contains(b.String(), "unknown-inputs lint: 6 of ") {
		t.Errorf("summary: %s", b.String())
	}
}

func TestParseExemptCites(t *testing.T) {
	cs := parseExemptCites("svc/a.go:12 (read), b6_handlers.go:378-, client.ts:87, 201) and x.py:5-9; not a cite: v1.2")
	if len(cs) != 4 {
		t.Fatalf("%+v", cs)
	}
	if cs[0].Path != "svc/a.go" || cs[0].Ranges[0] != [2]int{12, 12} {
		t.Errorf("0: %+v", cs[0])
	}
	if cs[1].Path != "b6_handlers.go" || cs[1].Ranges[0] != [2]int{378, 0} {
		t.Errorf("1: %+v", cs[1])
	}
	if cs[2].Path != "client.ts" || len(cs[2].Ranges) != 2 || cs[2].Ranges[1] != [2]int{201, 201} {
		t.Errorf("2: %+v", cs[2])
	}
	if cs[3].Path != "x.py" || cs[3].Ranges[0] != [2]int{5, 9} {
		t.Errorf("3: %+v", cs[3])
	}
	w := codeWords([]string{"row, err := repo.GetItem(ctx, key); mu.Lock(); HTTPClient"})
	for _, x := range []string{"get", "item", "repo", "mu", "lock", "http", "client"} {
		if !w[x] {
			t.Errorf("codeWords missing %q: %v", x, w)
		}
	}
}

const exemptionsDoc = `schema_version: 1
components:
  - id: svc
    sources: [{path: svc/main.go, line: 1}]
    attributes: {single_writer: "one leader loop (leader.go:2)"}
  - id: bad
    attributes: {single_writer: "trust me"}
interfaces:
  - component: svc
    name: bump
    sources: [{path: svc/main.go, line: 1}]
    attributes:
      racy_in_code: "svc/main.go:3 (read), main.go:4 (write)"
    errors:
      - {code: a, status: 400, reachable_by: "input.size > 10"}
      - {code: b, status: 400, reachable_by: "the decoder rejects it (main.go:5)"}
      - {code: c, status: 400, reachable_by: "the decoder rejects it"}
      - {code: d, status: 400, reachable_by: "see nowhere.go:3"}
    behavior: [{return: {}}]
  - component: svc
    name: blind
    attributes:
      racy_in_code: "svc/main.go:14"
    behavior: [{return: {}}]
  - component: svc
    name: pick
    sources: [{path: svc/main.go, line: 9}]
    attributes: {choice_ok: "the guest decides"}
    behavior:
      - {choice: outcome, options: {a: [{return: {}}], b: [{return: {}}]}, default: a, source: {path: svc/main.go, line: 9}}
  - component: svc
    name: pick2
    attributes: {choice_ok: {outcome: "config decides (svc/main.go:14)"}, reachable_by: "*"}
    behavior:
      - {choice: outcome, options: {a: [{return: {}}], b: [{return: {}}]}, default: a}
`

func TestLintExemptions(t *testing.T) {
	root := t.TempDir()
	write := func(p string, lines ...string) {
		fp := filepath.Join(root, p)
		os.MkdirAll(filepath.Dir(fp), 0o755)
		os.WriteFile(fp, []byte(strings.Join(lines, "\n")+"\n"), 0o644)
	}
	write("svc/main.go",
		"package svc", // 1
		"",
		"row := db.GetItem(key)",     // 3
		"db.PutItem(key, row.Add())", // 4
		"if err := json.Decode(body); err != nil { return 400 }",
		"", "", "",
		"resp, err := http.Get(guestURL)", // 9
		"", "", "", "",
		"x := cfg.Flag", // 14
		"", "", "", "", "")
	write("svc/leader.go", "", "if !lease.Held() { return }", "")
	doc, origins := docFixture(t, exemptionsDoc)

	r := lintExemptions(doc, origins, newCodeRoot(root))
	got := map[string]string{}
	for _, f := range r.Findings {
		got[f.Subject] = f.Why
	}
	want := map[string]string{
		"component bad":                               "no path:line citation",
		"interface svc.blind":                         "neither a read nor a write",
		"interface svc.bump error c":                  "neither CEL",
		"interface svc.bump error d":                  "doesn't resolve",
		"interface svc.pick2 choice outcome":          "no random, network, time or external token",
		"interface svc.pick2 attributes.reachable_by": "names no CEL",
	}
	for s, w := range want {
		if !strings.Contains(got[s], w) {
			t.Errorf("%s: got %q, want %q", s, got[s], w)
		}
	}
	if len(got) != len(want) {
		t.Errorf("findings: %v", got)
	}
	if r.Kinds["reachable_by"] != [2]int{5, 3} || r.Kinds["single_writer"] != [2]int{2, 1} {
		t.Errorf("kinds: %v", r.Kinds)
	}
	var b bytes.Buffer
	if !r.print(&b, 5, false, true) || !strings.Contains(b.String(), "✗ --max-exemption-issues 5: 6 issues") {
		t.Errorf("gate: %s", b.String())
	}

	// Without --code: presence and CEL only.
	r = lintExemptions(doc, origins, nil)
	if len(r.Findings) != 3 || r.Unverified == 0 {
		t.Errorf("no code: %d findings, %d unverified: %+v", len(r.Findings), r.Unverified, r.Findings)
	}
}

func TestStrictStubs(t *testing.T) {
	d := []string{`interface "x": kind: sync vs async (a.yaml vs b.yaml)`}
	if w, bad := strictStubs(&bytes.Buffer{}, d); bad || len(w) != 1 {
		t.Fatal("lenient")
	}
	*strictStubsFlag = true
	defer func() { *strictStubsFlag = false }()
	var b bytes.Buffer
	if w, bad := strictStubs(&b, d); !bad || len(w) != 0 || !strings.Contains(b.String(), "✗ stubs disagree (--strict-stubs): interface \"x\"") {
		t.Fatalf("strict: %v %v %s", w, bad, b.String())
	}
}

package main

import (
	"bytes"
	celast "cel.dev/cel-go/common/ast"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

// The defect in small: the key service stores the budget as
// limitUSD in the auth record; the authenticator returns the record's
// auth; the gateway passes it on as principal.auth; the gate reads
// limitUsd.
const seamA = `schema_version: 1
id: seams
components:
  - {id: db}
  - {id: keys}
  - {id: auth}
  - {id: gw}
  - {id: budgets}
  - {id: api, router: {}}
interfaces:
  - {component: db, name: put, store: {table: core, op: put, key: "= input.pk", value: "= input.item"}}
  - {component: db, name: get, store: {table: core, op: get, key: "= input.pk"}}
  - component: keys
    name: create
    behavior:
      - set:
          vars.budget: "= {'limitUSD': input.limit, 'period': 'daily'}"
      - set:
          vars.auth: "= merge({'org': input.org}, {'budget': vars.budget})"
      - {call: db.put, input: {pk: "= 'KEY#' + input.hash", item: {auth: "= vars.auth", org: "= input.org"}}}
  - component: auth
    name: authenticate
    behavior:
      - {call: db.get, input: {pk: "= 'KEY#' + input.hash"}, as: row}
      - return: {auth: "= vars.row.value.auth", orgId: "= vars.row.value.org"}
  - component: gw
    name: handle
    behavior:
      - {call: auth.authenticate, input: {hash: "= input.hash"}, as: a}
      - set:
          vars.principal: "= {'auth': vars.a.value.auth, 'org': vars.a.value.orgId}"
      - {call: budgets.gate, input: {principal: "= vars.principal", modelId: "= input.model"}}
      - {emit: budgets.count, input: {principal: "= vars.principal", billed_nano_usd: 1}}
  - component: budgets
    name: gate
    request: {type: object, properties: {principal: {type: object}, model_id: {type: string}}}
    behavior:
      - if: "has(input.principal.auth.budget.limitUsd) && input.principal.auth.budget.period == 'daily'"
        then: [{fail: {code: over}}]
      - return: {ok: true}
  - component: budgets
    name: count
    request: {type: object, properties: {principal: {type: object}, billed_nano_usd: {type: integer}}}
    behavior:
      # both spellings arrive in org: no finding for org
      - return: {n: "= input.principal.org"}
  # a route: headers are normalized; x_ aliases and route inputs are not findings
  - component: api
    name: list
    attributes: {method: GET, path: /v1/things}
    request: {type: object, properties: {x_org_id: {type: string}, authorization: {type: string}}}
    behavior:
      - return: {org: "= input.xOrgId + input.Authorization"}
  - component: gw
    name: list
    behavior:
      - {call: api.list, input: {X_Org_Id: o, authorization: t}}
`

const seamB = `schema_version: 1
interfaces:
  - component: gw
    name: other
    behavior:
      - {call: auth.authenticate, input: {hash: h}, as: a}
      # the authenticator returns orgId: exact, no finding
      - return: {org: "= vars.a.value.orgId"}
scenarios:
  # scenarios are not writers: this seeds the spelling the gate reads
  - id: gate
    steps: [{caller: gw, interface: budgets.gate, input: {principal: {auth: {budget: {limitUsd: 5}}}}}]
    expect: ["true"]
`

func seamFixture(t *testing.T) (*model.Document, map[string]string) {
	t.Helper()
	var ins []merge.Input
	for _, f := range []struct{ name, y string }{{"a.yaml", seamA}, {"b.yaml", seamB}} {
		d, err := model.ParseDocument([]byte(f.y))
		if err != nil {
			t.Fatalf("%s: %v", f.name, err)
		}
		ins = append(ins, merge.Input{Name: f.name, Doc: d})
	}
	res, err := merge.Merge(ins)
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

func TestLintSeamNames(t *testing.T) {
	doc, origins := seamFixture(t)
	r := lintSeamNames(doc, origins)
	var got []string
	for _, f := range r.Findings {
		got = append(got, f.Reader+":"+f.Read+"/"+f.Write+"@"+f.At)
	}
	want := []string{
		"budgets.gate:limitUsd/limitUSD@input.principal.auth.budget",
		"budgets.gate:model_id/modelId@call budgets.gate",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("findings:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	if f := r.Findings[0]; f.Writer != "keys.create" || r.Frags[f.Writer] != "a.yaml" {
		t.Errorf("writer %+v", f)
	}
	var b bytes.Buffer
	if r.print(&b, -1, false) {
		t.Error("gate off failed")
	}
	out := b.String()
	for _, w := range []string{
		"! seam-names limitUsd vs limitUSD (a.yaml): budgets.gate reads input.principal.auth.budget.limitUsd; keys.create (a.yaml) writes limitUSD",
		"! seam-names modelId vs model_id (a.yaml): gw.handle (a.yaml) calls budgets.gate with key modelId; its request schema says model_id",
		"seam-names lint: 2 fields",
	} {
		if !strings.Contains(out, w) {
			t.Errorf("missing %q in:\n%s", w, out)
		}
	}
	b.Reset()
	if !r.print(&b, 1, true) || !strings.Contains(b.String(), "✗ seam-names lint: 2 fields read under one spelling and written under another; --max-seam-names 1: above") || strings.Contains(b.String(), "! seam-names") {
		t.Errorf("gate 1:\n%s", b.String())
	}
	if r.print(&b, 2, true) {
		t.Error("gate 2 failed")
	}
}

func TestSeamShapes(t *testing.T) {
	a := &seamAnalysis{env: newSeamEnv(), sync: map[[2]*nt]uint64{}}
	a.asts = map[string]celast.Expr{}
	c := &seamCtx{a: a, writer: "w", vars: newNT(), input: newNT()}
	rows := &nt{elem: newNT()}
	rows.elem.set("Name", newNT(), "x")
	c.input.set("rows", rows, "")
	// a map macro carries the item's names into the result's items
	v := c.cel("input.rows.map(r, {'n': r.Name, 'tags': [r]})")
	if v == nil || v.elem == nil || v.elem.kid("n") == nil || v.elem.kid("tags").elem.kid("Name") == nil {
		t.Fatalf("map: %+v", v)
	}
	a.check = true
	a.found = map[string]*seamFinding{}
	c.iface = "r"
	c.cel("input.rows.filter(r, r.name != '')[0].name")
	if len(a.found) != 2 { // r.name in the filter, and [0].name
		t.Errorf("found %v", a.found)
	}
	if seamNorm("Limit_U-SD x") != "limitusdx" || !headerAlias("X_Org_Id") {
		t.Error("norm")
	}
}

// seamMergeAll gives the names, writers and item shapes of folding
// seamMerge pair by pair, including past the depth bound.
func TestSeamMergeAll(t *testing.T) {
	var show func(n *nt, d int) string
	show = func(n *nt, d int) string {
		if n == nil {
			return "-"
		}
		if d > 12 {
			return "…"
		}
		var b strings.Builder
		for _, k := range sortedKeys(n.kids) {
			b.WriteString(k + "@" + n.kids[k].src + ":" + show(n.kids[k].n, d+1) + " ")
		}
		return "{" + b.String() + "[" + show(n.elem, d+1) + "]}"
	}
	rnd := uint32(7)
	next := func(m uint32) uint32 { rnd = rnd*1664525 + 1013904223; return (rnd >> 16) % m }
	var gen func(d int) *nt
	gen = func(d int) *nt {
		n := newNT()
		if d > 9 {
			return n
		}
		for i, c := uint32(0), next(4); i < c; i++ {
			n.set(string(rune('a'+next(5))), gen(d+1), string(rune('p'+next(3))))
		}
		if next(3) == 0 {
			n.elem = gen(d + 1)
		}
		return n
	}
	for round := 0; round < 200; round++ {
		shared := gen(0)
		var xs []*nt
		for i, c := 0, int(next(6)); i < c; i++ {
			switch next(4) {
			case 0:
				xs = append(xs, nil)
			case 1:
				xs = append(xs, shared)
			default:
				xs = append(xs, gen(0))
			}
		}
		var fold *nt
		for _, x := range xs {
			fold = seamMerge(fold, x, 0)
		}
		if got, want := show(seamMergeAll(xs, 0), 0), show(fold, 0); got != want {
			t.Fatalf("round %d:\n got %s\nwant %s", round, got, want)
		}
	}
}

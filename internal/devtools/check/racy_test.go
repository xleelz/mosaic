package main

import (
	"bytes"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

const racyDoc = `schema_version: 1
id: racy
components:
  - {id: db}
  - {id: svc}
  - {id: solo, capacity: {concurrency: 1}}
  - {id: shared, capacity: {concurrency: 1}}
  - {id: leader, attributes: {single_writer: "one leader loop (svc/leader.go:10)"}}
  - {id: legacy, attributes: {racy_in_code: "it just does"}}
interfaces:
  - {component: db, name: get, store: {table: rows, op: get, key: "= input.pk + '|' + input.sk"}}
  - {component: db, name: put, store: {table: rows, op: put, key: "= input.pk + '|' + input.sk", value: "= input.item"}}
  - {component: db, name: update, store: {table: rows, op: update, key: "= input.pk + '|' + input.sk", value: "= input.item"}}
  - {component: db, name: put-new, store: {table: rows, op: put, key: "= input.pk + '|' + input.sk", value: "= input.item", if_absent: true}}
  - {component: db, name: query, store: {table: rows, op: query, where: "key.startsWith(input.pk + '|' + (has(input.sk_prefix) ? input.sk_prefix : ''))"}}
  - {component: db, name: other-put, store: {table: other, op: put, key: "= input.k", value: {}}}
  - {component: db, name: other-get, store: {table: other, op: get, key: "= input.k"}}
  - {component: db, name: solo-put, store: {table: solo_t, op: put, key: "= input.k", value: {}}}
  - {component: db, name: solo-get, store: {table: solo_t, op: get, key: "= input.k"}}
  # read then blind put of the same row: record-txn
  - component: svc
    name: record
    behavior:
      - {call: db.get, input: {pk: "= 'ORG#' + input.org", sk: "= 'TXN#' + input.id"}, as: prior, on_error: continue}
      - if: vars.prior.ok
        then: [{fail: {code: dup}}]
      - {title: write the txn, call: db.put, input: {pk: "= 'ORG#' + input.org", sk: "= 'TXN#' + input.id", item: {}}}
  # the same with if_absent: fine
  - component: svc
    name: record-cas
    behavior:
      - {call: db.get, input: {pk: "= 'ORG#' + input.org", sk: "= 'TXN#' + input.id"}, as: prior, on_error: continue}
      - {call: db.put-new, input: {pk: "= 'ORG#' + input.org", sk: "= 'TXN#' + input.id", item: {}}}
  # another row (sk differs), and a transact: fine
  - component: svc
    name: other-row
    behavior:
      - {set: {vars.pk: "= 'ORG#' + input.org"}}
      - {call: db.get, input: {pk: "= vars.pk", sk: "A#ORG"}, as: org}
      - {call: db.update, input: {pk: "= vars.pk", sk: "= 'MEMBER#' + input.user", item: {}}}
      - transact: [{table: rows, op: put, key: "= 'X'", value: {}}]
  # read in then, write in else: never both
  - component: svc
    name: branches
    behavior:
      - if: input.a
        then: [{call: db.other-get, input: {k: x}, as: o}]
        else: [{call: db.other-put, input: {k: x}}]
  # a query of the table, then a claim of one row: racy
  - component: svc
    name: claim
    behavior:
      - {call: db.query, input: {pk: "NODE#", sk_prefix: "A#"}, as: free}
      - {call: db.update, input: {pk: "= 'NODE#' + vars.free.value[0].id", sk: "A#NODE", item: {claimed: true}}}
  # capacity 1, one instance, the only writer of other: can't race
  - component: solo
    name: bump
    behavior:
      - {call: db.solo-get, input: {k: "= input.k"}, as: o}
      - {call: db.solo-put, input: {k: "= input.k"}}
  # capacity 1, but svc.branches also writes other: races
  - component: shared
    name: bump
    behavior:
      - {call: db.other-get, input: {k: "= input.k"}, as: o}
      - {call: db.other-put, input: {k: "= input.k"}}
  - component: leader
    name: tick
    behavior:
      - {call: db.get, input: {pk: L, sk: L}, as: o}
      - {call: db.put, input: {pk: L, sk: L, item: {}}}
  # state: read, a call, then a write from the stale read
  - component: svc
    name: count
    behavior:
      - {set: {vars.n: "= state.count"}}
      - {call: db.other-get, input: {k: x}, as: o}
      - {set: {state.count: "= vars.n + 1"}}
  # state: no step between that yields (atomic in the simulator)
  - component: svc
    name: count-atomic
    behavior:
      - if: state.count2 > 3
        then: [{fail: {code: full}}]
      - {set: {state.count2: "= state.count2 + 1"}}
  # state: re-read afresh at the write
  - component: svc
    name: count-fresh
    behavior:
      - {set: {vars.seen: "= state.count3"}}
      - {call: db.other-get, input: {k: x}, as: o}
      - {set: {state.count3: "= state.count3 + 1"}}
  # the code itself reads then writes unconditionally: a system finding
  - component: svc
    name: spend
    attributes: {racy_in_code: "svc/spend.go:40 reads the counter, svc/spend.go:52 puts it"}
    behavior:
      - {call: db.other-get, input: {k: s}, as: o}
      - {call: db.other-put, input: {k: s}}
  # an exemption without a citation: warned, not exempt
  - component: legacy
    name: spend
    behavior:
      - {call: db.other-get, input: {k: s}, as: o}
      - {call: db.other-put, input: {k: s}}
  # writes, never reads
  - component: svc
    name: blind
    behavior: [{set: {state.x: 1}}]
`

func racyFixture(t *testing.T) (*model.Document, map[string]string) {
	t.Helper()
	d, err := model.ParseDocument([]byte(racyDoc))
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

func TestLintRacy(t *testing.T) {
	doc, origins := racyFixture(t)
	r := lintRacy(doc, origins)
	got := strings.Join(subjects(r), ",")
	if got != "legacy.spend,shared.bump,svc.claim,svc.count,svc.record" {
		t.Fatalf("racy %q:\n%+v", got, r.Findings)
	}
	why := map[string]string{}
	for _, f := range r.Findings {
		why[f.Subject] = f.Why
	}
	for id, w := range map[string]string{
		"svc.record":  "reads db/rows key pk=ORG#* sk=TXN#* at behavior[0], then writes db/rows key pk=ORG#* sk=TXN#* unconditionally (put) at behavior[2] (write the txn); svc has no capacity of concurrency 1; fix: if: row.version == ..., if_absent, incr or transact",
		"shared.bump": "another writer: ",
		"svc.claim":   "reads db/rows key pk=NODE#* sk=A#* at behavior[0]",
		"svc.count":   "reads state.count at behavior[0], then writes state.count unconditionally (set) at behavior[2]",
	} {
		if !strings.Contains(why[id], w) {
			t.Errorf("%s: %q, want %q", id, why[id], w)
		}
	}
	// Every behavior writes a store or state; leader's is exempt but counted.
	if len(r.System) != 1 || r.System[0].Subject != "svc.spend" || !strings.Contains(r.System[0].Why, "racy in code (interface svc.spend): svc/spend.go:40") {
		t.Errorf("system %+v", r.System)
	}
	if len(r.Warnings) != 1 || !strings.Contains(r.Warnings[0], "component legacy: attributes.racy_in_code needs a path:line citation") {
		t.Errorf("warnings %v", r.Warnings)
	}
	if f := r.Fragments[0]; f.Of != 14 || f.Hits != 5 {
		t.Errorf("share %+v", r.Fragments)
	}
	var b bytes.Buffer
	if r.print(&b, 0.5, false) {
		t.Error("gate 0.5 failed")
	}
	if !strings.Contains(b.String(), "! racy in code (system finding) svc.spend (a.yaml): reads db/other") ||
		!strings.Contains(b.String(), "racy lint: 5 of 14 store- or state-writing behaviors (35.7%); 1 racy in code (system findings)") {
		t.Errorf("print:\n%s", b.String())
	}
	if !r.print(&b, 0.2, true) || !strings.Contains(b.String(), "✗ racy in a.yaml: 5 of 14") {
		t.Errorf("gate 0.2:\n%s", b.String())
	}
}

func TestRacyHelpers(t *testing.T) {
	if !exclusive("x:behavior[1].then[0]", "x:behavior[1].else[2].then[0]") ||
		!exclusive("x:behavior[1].options.a[0]", "x:behavior[1].options.b[0]") ||
		exclusive("x:behavior[1].then[0]", "x:behavior[1].then[2]") ||
		exclusive("x:behavior[1].branches[0][0]", "x:behavior[1].branches[1][0]") ||
		exclusive("x:behavior[0]", "x:behavior[3].else[0]") {
		t.Error("exclusive")
	}
	a := racyKey{parts: map[string]string{"pk": "ORG#", "sk": "TXN#"}}
	if !a.compat(racyKey{parts: map[string]string{"pk": "ORG#"}}) || a.compat(racyKey{parts: map[string]string{"pk": "ORG#", "sk": "A#"}}) ||
		!a.compat(racyKey{}) || (racyKey{lit: "A"}).compat(racyKey{lit: "B"}) {
		t.Error("compat")
	}
	if !mentionsVar("= vars.n + 1", "n") || mentionsVar("= vars.nn + 1", "n") || mentionsVar("= x.vars.n", "n") {
		t.Error("mentionsVar")
	}
}

package main

import (
	"bytes"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

func round4Fixture(t *testing.T, src string) (*model.Document, map[string]string) {
	t.Helper()
	d, err := model.ParseDocument([]byte(src))
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

const unraisedDoc = `schema_version: 1
id: unraised
components:
  - {id: db, kind: datastore}
  - {id: svc}
  - {id: lim, limiters: [{id: slots, kind: concurrency, limit: 1, lease_ms: 1000, error: {code: busy, status: 429}}]}
interfaces:
  - {component: db, name: get, store: {table: rows, op: get, key: "= input.k"}}
  - {component: db, name: put-if, store: {table: rows, op: put, key: "= input.k", value: {}, if_absent: true, conflict: exists}, errors: [{code: exists, status: 409}]}
  - component: svc
    name: upload
    errors:
      - {code: invalid_request, status: 400}
      - {code: invalid_file, status: 400}
      - {code: not_found, status: 404}
      - {code: exists, status: 409}
      - {code: internal, status: 500}
      - {code: gone, status: 410}
      - {code: noted, status: 422}
    attributes: {reachable_by: {noted: "the scanner (svc/scan.go:40)"}}
    behavior:
      - if: "!has(input.purpose)"
        then: [{fail: {code: invalid_request, status: 400}}]
      - {call: db.get, input: {k: "= input.k"}}
      - {call: db.put-if, input: {k: "= input.k"}}
      - {call: svc.helper, input: {}, on_error: continue}
  - component: svc
    name: helper
    errors: [{code: gone, status: 410}]
    behavior: [{fail: {code: gone, status: 410}}]
  - component: svc
    name: rethrow
    errors: [{code: gone, status: 410}, {code: exists, status: 409}, {code: other, status: 418}]
    behavior:
      - {call: svc.helper, input: {}, as: h, on_error: [{fail: "= error"}]}
  - component: lim
    name: admit
    errors: [{code: busy, status: 429}, {code: missing, status: 400}]
    behavior: [{admit: {limiter: slots}}]
  - component: svc
    name: stub
    errors: [{code: never}]
  - component: svc
    name: bstub
    errors: [{code: never}]
    attributes: {boundary: true, owner: other}
    behavior: [{return: {}}]
`

func TestLintUnraised(t *testing.T) {
	doc, origins := round4Fixture(t, unraisedDoc)
	r := lintUnraised(doc, origins)
	got := strings.Join(subjects(r), ",")
	// invalid_file: nothing raises it; gone: the helper's error is
	// swallowed (on_error: continue); other: rethrow re-raises only the
	// helper's; missing: no step raises it. internal (500), the stub (no
	// behavior), the boundary stub and the reachable_by error aren't listed.
	if got != "lim.admit missing,svc.rethrow exists,svc.rethrow other,svc.upload gone,svc.upload invalid_file" {
		t.Fatalf("unraised %q:\n%+v", got, r.Findings)
	}
	if f := r.Fragments[0]; f.Of != 11 || f.Hits != 5 {
		t.Errorf("share %+v", r.Fragments)
	}
	var b bytes.Buffer
	if !r.print(&b, 0.2, false) || !strings.Contains(b.String(), "! unraised-errors svc.upload invalid_file (a.yaml): declares invalid_file (400), but no fail step") {
		t.Errorf("print:\n%s", b.String())
	}
}

const transitionDoc = `schema_version: 1
id: transitions
components:
  - {id: db, kind: datastore}
  - {id: jobs, kind: scheduler}
  - {id: svc}
  - {id: solo, attributes: {single_writer: "one reconciler (svc/rec.go:10)"}}
interfaces:
  - {component: db, name: get, store: {table: rows, op: get, key: "= input.pk + '|' + input.sk"}}
  - {component: db, name: put, store: {table: rows, op: put, key: "= input.pk + '|' + input.sk", value: "= input.item"}}
  - {component: db, name: update, store: {table: rows, op: update, key: "= input.pk + '|' + input.sk", value: "= input.item"}}
  - {component: db, name: update-if, store: {table: rows, op: update, key: "= input.pk + '|' + input.sk", value: "= input.item", if: "row.status != 'terminated'"}}
  - {component: jobs, name: submit, store: {table: jobs, op: put, key: "= input.id", value: "= input.item"}}
  # stop-vm: an unconditional status write
  - component: svc
    name: stop
    behavior:
      - if: "input.vm.status == 'terminated'"
        then: [{fail: {code: conflict}}]
      - {call: db.update, input: {pk: "= 'VM#' + input.vm.id", sk: "A#VM", item: {status: stopped}}}
  # the fenced one: fine
  - component: svc
    name: stop-fenced
    behavior:
      - {call: db.update-if, input: {pk: "= 'VM#' + input.vm.id", sk: "A#VM", item: {status: stopped}}}
  # resize-disk: a status test on a loaded copy, then an unconditional write of another field
  - component: svc
    name: resize
    behavior:
      - {call: svc.load, input: {id: "= input.id"}, as: own}
      - {set: {vars.v: "= vars.own.value"}}
      - if: "vars.v.status != 'stopped'"
        then: [{fail: {code: bad}}]
      - {call: db.update, input: {pk: "= 'VM#' + vars.v.id", sk: "A#VM", item: {diskSizeGb: "= input.gb"}}}
  - component: svc
    name: load
    behavior: [{call: db.get, input: {pk: "= 'VM#' + input.id", sk: "A#VM"}, as: r}, {return: "= vars.r.value"}]
  # a new row under a fresh id: fine
  - component: svc
    name: create
    behavior:
      - {set: {vars.id: "= 'vm-' + string(now)"}}
      - {call: db.put, input: {pk: "= 'VM#' + vars.id", sk: "A#VM", item: {status: pending}}}
  # a scheduler's job table: not a fenced row
  - component: svc
    name: dispatch
    behavior: [{call: jobs.submit, input: {id: "= input.id", item: {status: pending}}}]
  # exempt
  - component: solo
    name: reconcile
    behavior: [{call: db.update, input: {pk: "= 'VM#' + input.id", sk: "A#VM", item: {phase: running}}}]
`

func TestRacyTransitions(t *testing.T) {
	doc, origins := round4Fixture(t, transitionDoc)
	r := lintRacyWith(doc, origins, &lintProfile{})
	var got []string
	for _, f := range r.Findings {
		got = append(got, f.Lint+" "+f.Subject)
	}
	if strings.Join(got, ",") != "racy (transition) svc.resize,racy (transition) svc.stop" {
		t.Fatalf("transitions %q:\n%+v", got, r.Findings)
	}
	why := map[string]string{}
	for _, f := range r.Findings {
		why[f.Subject] = f.Why
	}
	for id, w := range map[string]string{
		"svc.stop":   "writes db/rows key pk=VM#* sk=A#VM* unconditionally (update) at behavior[1], setting status (a status transition; code usually fences these); another writer: ",
		"svc.resize": "after testing vars.v.status at behavior[2]",
	} {
		if !strings.Contains(why[id], w) {
			t.Errorf("%s: %q, want %q", id, why[id], w)
		}
	}
	var b bytes.Buffer
	r.print(&b, -1, false)
	if !strings.Contains(b.String(), "! racy (transition) svc.stop (a.yaml)") || !strings.Contains(b.String(), "; 2 of them transitions") {
		t.Errorf("print:\n%s", b.String())
	}
	// naming.state_fields adds a field: the exempt reconcile stays exempt,
	// and a custom field is a transition.
	p := &lintProfile{}
	p.Naming.StateFields = []string{"diskSizeGb"}
	if f := p.stateFields(); !f["disksizegb"] || !f["status"] {
		t.Errorf("state fields %v", f)
	}
}

const choiceDoc = `schema_version: 1
id: choices
configs:
  - {id: batch-pool-enabled, type: boolean, value: true, attributes: {key: BATCH_POOL_ENABLED}}
components:
  - {id: svc}
interfaces:
  - component: svc
    name: create
    behavior:
      - {title: BATCH_EXPEDITED entitlement, choice: expedited_flag, default: "off", options: {"on": [], "off": [{fail: {code: feature_disabled}}]}}
      - {title: The org's Cedar policies decide, choice: verdict, default: allow, options: {allow: [], deny: [{fail: {code: denied}}]}}
      - {choice: batch_pool_enabled, default: "yes", options: {"yes": [], "no": []}}
      - {title: The upstream answers, choice: upstream, default: ok, options: {ok: [], timeout: [{fail: {code: timeout}}]}}
      - {title: Ask whether to save the workspace configuration, choice: save, default: save, options: {save: [], cancel: []}}
  - component: svc
    name: gated
    attributes: {choice_ok: "the flag service is another system's, answered over the network"}
    behavior:
      - {choice: org_flag, default: "on", options: {"on": [], "off": []}}
  - component: svc
    name: stub
    attributes: {boundary: true, owner: other}
    behavior:
      - {choice: org_flag, default: "on", options: {"on": [], "off": []}}
`

func TestLintChoiceForComputed(t *testing.T) {
	doc, origins := round4Fixture(t, choiceDoc)
	r := lintChoiceForComputed(doc, origins, &lintProfile{}, nil)
	got := strings.Join(subjects(r), ",")
	if got != "svc.create.batch_pool_enabled,svc.create.expedited_flag,svc.create.verdict" {
		t.Fatalf("choices %q:\n%+v", got, r.Findings)
	}
	why := map[string]string{}
	for _, f := range r.Findings {
		why[f.Subject] = f.Why
	}
	if !strings.Contains(why["svc.create.batch_pool_enabled"], `"batch_pool_enabled" names config batch-pool-enabled`) ||
		!strings.Contains(why["svc.create.verdict"], `its title says "cedar"`) {
		t.Errorf("why %v", why)
	}
	var b bytes.Buffer
	if !r.printCount(&b, 2, true) || !strings.Contains(b.String(), "✗ --max-choice-for-computed 2: 3 findings") {
		t.Errorf("gate:\n%s", b.String())
	}
	if r.printCount(&b, 3, true) {
		t.Error("gate 3 failed")
	}
	if !matchesConfigFile("services/envx/env.go", []string{"services/envx", "x/*.go"}) || matchesConfigFile("a/b.go", []string{"services/envx"}) {
		t.Error("matchesConfigFile")
	}
}

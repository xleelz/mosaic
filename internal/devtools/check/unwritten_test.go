package main

import (
	"bytes"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

// The defect in small: one table holds user profiles and orgs. The org
// writer stores deletedAt; the account deletion stores the profile's marker
// as deletion; the gateway reads profile.deletedAt, which no profile writer
// writes, though the table has the name.
const unwrittenDoc = `schema_version: 1
id: unwritten
components:
  - {id: db}
  - {id: users}
  - {id: orgs}
  - {id: gw}
  - {id: bus}
  - {id: api, router: {}}
  - {id: idp, kind: external, state: {initial: {tokens: {t1: {sub: alice}}}}}
interfaces:
  - {component: db, name: get, store: {table: core, op: get, key: "= input.pk + '|' + input.sk"}}
  - {component: db, name: put, store: {table: core, op: put, key: "= input.pk + '|' + input.sk", value: "= input.item"}}
  - {component: db, name: put-if, request: {type: object, properties: {cond: {type: string}}}, store: {table: core, op: put, key: "= input.pk + '|' + input.sk", value: "= input.item", if: "eval(input.cond, {'row': row})"}}
  - {component: db, name: query, store: {table: core, op: query, where: "key.startsWith(input.pk + '|')"}}
  - {component: db, name: blob-get, store: {table: blobs, op: get, key: "= input.id"}}
  - {component: db, name: blob-put, store: {table: blobs, op: put, key: "= input.id", value: "= input.item"}}
  - component: users
    name: mark-deleted
    behavior:
      - call: db.put
        input: {pk: "= 'USER#' + input.id", sk: "A#PROFILE", item: {id: "= input.id", email: "= input.email", deletion: {at: "= input.at"}}}
  - component: users
    name: rename
    behavior:
      # a conditional write reads the row it guards
      - call: db.put-if
        input: {pk: "= 'USER#' + input.id", sk: "A#PROFILE", item: {id: "= input.id", email: "= input.email"}, cond: "row == null || !has(row.lockedAt)"}
  - component: orgs
    name: delete
    behavior:
      - call: db.put
        input: {pk: "= 'ORG#' + input.id", sk: "A#ORG", item: {id: "= input.id", deletedAt: "= input.at"}}
      - {emit: bus.org-deleted, input: {orgId: "= input.id", at: "= input.at"}}
  - component: gw
    name: auth
    behavior:
      - call: db.get
        input: {pk: "= 'USER#' + input.owner", sk: "A#PROFILE"}
        as: prof
        on_error: continue
      - if: "vars.prof.ok && has(vars.prof.value.deletedAt) && vars.prof.value.email != ''"
        then: [{fail: {code: account_deleted, status: 403}}]
      - call: db.get
        input: {pk: "= 'ORG#' + input.org", sk: "A#ORG"}
        as: org
      # written by orgs.delete: not a finding
      - if: "has(vars.org.value.deletedAt)"
        then: [{fail: {code: org_deleted, status: 403}}]
      - call: orgs.describe
        input: {id: "= input.org"}
        as: d
      # an optional read with a fallback: not a finding
      - return: {name: "= vars.d.value.name", tier: "= vars.d.value.tier", plan: "= has(vars.org.value.plan) ? vars.org.value.plan : 'free'"}
  - component: orgs
    name: describe
    response: {type: object, properties: {name: {type: string}, tier: {type: string}}}
    behavior:
      - return: {name: "= input.id"}
  - component: bus
    name: org-deleted
    behavior:
      - return: {org: "= input.orgId", reason: "= input.reason"}
  - component: gw
    name: list-org-keys
    behavior:
      - call: db.query
        input: {pk: "= 'ORG#' + input.org"}
        as: rows
      - return: {live: "= vars.rows.value.filter(r, !has(r.revokedAt)).map(r, r.id)"}
  # unknown shapes: a blob is stored from a request body (open), a map
  # with dynamic keys is read with a literal one
  - component: api
    name: put-blob
    attributes: {method: PUT, path: /v1/blobs}
    behavior:
      - call: db.blob-put
        input: {id: "= input.id", item: "= input.body"}
  - component: gw
    name: read-blob
    behavior:
      - call: db.blob-get
        input: {id: "= input.id"}
        as: b
      - set:
          "=vars.m[input.k]": 1
      # a shape the reader builds itself is not a seam
      - set:
          vars.own: {a: 1}
      # a dynamic key reads an unknown row
      - call: db.get
        input: {pk: "= input.pk", sk: "= input.sk"}
        as: any
      - return: {x: "= vars.b.value.anything", y: "= vars.m.fixed", z: "= vars.own.b", w: "= vars.any.value.whatever"}
  # a write under a dynamic key is in no partition: it doesn't mask deletedAt
  - component: api
    name: raw-put
    attributes: {method: PUT, path: /v1/raw}
    behavior:
      - call: db.put
        input: {pk: "= input.pk", sk: "= input.sk", item: {deletedAt: "= input.at", lockedAt: "= input.at"}}
  # the world writes an external system's state
  - component: idp
    name: verify
    behavior:
      - set:
          vars.tok: "= state.tokens[input.token]"
      - return: {sub: "= vars.tok.sub", aud: "= vars.tok.aud"}
fixtures:
  - id: base
    state:
      db:
        core:
          "ORG#o1|K#k1": {id: k1, name: first}
`

func unwrittenFixture(t *testing.T) (*model.Document, map[string]string) {
	t.Helper()
	d, err := model.ParseDocument([]byte(unwrittenDoc))
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

func TestLintUnwrittenFields(t *testing.T) {
	doc, origins := unwrittenFixture(t)
	r := lintUnwrittenFields(doc, origins)
	var got []string
	for _, f := range r.Findings {
		got = append(got, f.Reader+":"+f.At+"."+f.Field+"~"+f.Closest)
	}
	want := []string{
		"bus.org-deleted:input.reason~",              // an event field no emit sends
		"gw.auth:vars.d.value.tier~",                 // declared by the response schema, never returned
		"gw.auth:vars.prof.value.deletedAt~deletion", // the profile marker is deletion
		"gw.list-org-keys:r.revokedAt~deletedAt",     // org rows: a fixture and orgs.delete
		"users.rename:row.lockedAt~",                 // a condition string over the row
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("findings:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	var del unwrittenFinding
	for _, f := range r.Findings {
		if f.Field == "deletedAt" {
			del = f
		}
	}
	if strings.Join(del.Writers, ",") != "users.mark-deleted" || strings.Join(del.Written, ",") != "deletion,email,id" {
		t.Errorf("deletedAt finding %+v", del)
	}
	var b bytes.Buffer
	if r.print(&b, -1, false) {
		t.Error("gate off failed")
	}
	out := b.String()
	for _, w := range []string{
		"! unwritten-fields deletedAt (a.yaml): gw.auth reads vars.prof.value.deletedAt; no writer writes it; closest written: deletion. Written: deletion, email, id, by users.mark-deleted",
		"  unwritten-fields in a.yaml: 5",
		"unwritten-fields lint: 5 fields read that no writer writes",
	} {
		if !strings.Contains(out, w) {
			t.Errorf("missing %q in:\n%s", w, out)
		}
	}
	if strings.Contains(out, "gate:") {
		t.Errorf("gate line without a gate:\n%s", out)
	}
	b.Reset()
	if !r.print(&b, 4, true) || !strings.Contains(b.String(), "✗ unwritten-fields gate: 5, --max-unwritten-fields 4") || strings.Contains(b.String(), "! unwritten") {
		t.Errorf("gate 4:\n%s", b.String())
	}
	b.Reset()
	if r.print(&b, 9, true) || !strings.Contains(b.String(), "--max-unwritten-fields can go down to 5") {
		t.Errorf("gate 9:\n%s", b.String())
	}
}

func TestPatMeet(t *testing.T) {
	w := patWild
	for _, c := range []struct {
		p, q string
		want bool
	}{
		{"USER#" + w + "|A#PROFILE", "USER#u1|A#PROFILE", true},
		{"USER#" + w + "|A#PROFILE", "ORG#" + w + "|A#ORG", false},
		{w + "|A#PROFILE", "USER#" + w, true},
		{"ORG#" + w + "|", "ORG#o1|K#k1", false},
		{"ORG#" + w + "|" + w, "ORG#o1|K#k1", true},
		{w, "", true},
		{"a", "b", false},
	} {
		if got := patMeet(c.p, c.q); got != c.want {
			t.Errorf("patMeet(%q, %q) = %v", patShow(c.p), patShow(c.q), got)
		}
	}
}

func TestClosestName(t *testing.T) {
	if got := closestName("deletedAt", []string{"defaultOrganizationId", "deletion", "email"}); got != "deletion" {
		t.Errorf("got %q", got)
	}
	if got := closestName("tier", []string{"name"}); got != "" {
		t.Errorf("got %q", got)
	}
}

// The profile gate has no template default: unset, findings are recorded
// without gating.
func TestUnwrittenProfileGate(t *testing.T) {
	n := 0
	for _, d := range profileGateDefs {
		if d.key == "max_unwritten_fields" {
			n++
			if d.flag != "max-unwritten-fields" || d.def != "" || d.needs != "" {
				t.Errorf("gate %+v", d)
			}
		}
	}
	if n != 1 {
		t.Errorf("max_unwritten_fields registered %d times", n)
	}
	lints := map[string]bool{}
	*maxUnwritten = 3
	defer func() { *maxUnwritten = -1 }()
	round4Implied(lints)
	if !lints["unwritten-fields"] {
		t.Error("--max-unwritten-fields doesn't imply the lint")
	}
}

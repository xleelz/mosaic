package main

import (
	"bytes"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

// DESIGN §15.1: internal-assertions and clock-ids.
const blackboxDoc = `schema_version: 1
id: bb
components:
  - {id: cli}
  - {id: api, state: {initial: {n: 0}}}
  - {id: core, state: {initial: {cache: {}}}}
  - {id: db}
  - {id: pay, kind: external}
  - {id: mail, attributes: {boundary: true}, state: {initial: {sent: 0}}}
interfaces:
  - component: db
    name: rows
    store: {key: id}
  - component: core
    name: price
    behavior:
      - {return: {amount: 1}}
  - component: pay
    name: charge
    behavior:
      - {return: {id: "= 'ch-' + string(now)"}}
  - component: mail
    name: send
    behavior:
      - {return: {}}
  - component: api
    name: order
    behavior:
      - {call: core.price, as: p}
      - {call: pay.charge}
      - set:
          state.last_id: "= now"
          state.created_at: "= string(timestamp(int(now / 1000)))"
          state.n: "= state.n + 1"
      - {return: {order_id: "= id('order', input.sku)", token: "= sha256(string(now_us))", at: "= now"}}
flows:
  - {id: order, entry: {caller: cli, interface: api.order, input: {sku: "= 'sku-' + string(now)"}}}
scenarios:
  - id: s1
    flow: order
    expect:
      - "result.ok"
      - "io.exists(i, i.interface == 'pay.charge')"
      - "calls['api.order'] == 1"
      - "calls['core.price'] == 1"
      - "trace.exists(e, e.interface == 'core.price')"
      - "state.api.n == 1"
      - "state['core'].cache == {}"
      - "size(state.db) == 0"
      - "state['mail@m1'].sent == 0"
`

func blackboxModel(t *testing.T) *model.Document {
	t.Helper()
	doc, err := model.ParseDocument([]byte(blackboxDoc))
	if err != nil {
		t.Fatal(err)
	}
	return doc
}

func TestInternalAssertionsLint(t *testing.T) {
	r := lintInternalAssertions(blackboxModel(t), map[string]string{"scenario/s1": "a"})
	got := map[string]string{}
	for _, f := range r.Findings {
		got[f.Subject] = f.Why
	}
	want := map[string]string{
		"s1.expect[3]": "interface core.price",
		"s1.expect[4]": "interface core.price",
		"s1.expect[5]": "state of api",
		"s1.expect[6]": "state of core",
	}
	if len(got) != len(want) {
		t.Errorf("findings %v, want %v", got, want)
	}
	for k, v := range want {
		if got[k] != v {
			t.Errorf("%s: got %q, want %q", k, got[k], v)
		}
	}
	if len(r.Fragments) != 1 || r.Fragments[0].Hits != 4 || r.Fragments[0].Of != 9 {
		t.Fatalf("shares %+v", r.Fragments)
	}
	var b bytes.Buffer
	if !r.print(&b, 0.4, true) {
		t.Errorf("4 of 9 should be above 0.4: %s", b.String())
	}
	if !strings.Contains(b.String(), "internal-assertions lint: 4 of 9 expectations (44.4%); --max-internal-assertions 0.40: 1 fragments above") {
		t.Errorf("output: %s", b.String())
	}
	if r.print(&b, 0.5, true) {
		t.Errorf("4 of 9 isn't above 0.5")
	}
}

func TestClockIDsLint(t *testing.T) {
	r := lintClockIDs(blackboxModel(t), map[string]string{})
	got := []string{}
	for _, f := range r.Findings {
		got = append(got, f.Subject)
	}
	want := []string{
		"api.order:behavior[2].set.state.last_id",
		"api.order:behavior[3].return.token",
		"order:entry.input.sku",
		"pay.charge:behavior[0].return.id",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Errorf("findings:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	// created_at and at read now as timestamps; they're counted, not flagged.
	if len(r.Fragments) != 1 || r.Fragments[0].Hits != 4 || r.Fragments[0].Of != 6 {
		t.Errorf("shares %+v", r.Fragments)
	}
	for _, c := range []struct {
		field, tpl string
		want       bool
	}{
		{"id", "'aud-' + string(now)", true},
		{"nonce", "now % 1000", true},
		{"request_id", "now", true},
		{"requestId", "now", true},
		{"createdAt", "string(timestamp(int(now / 1000)))", false},
		{"ttl", "now / 1000 + 60", false},
		{"id", "id('req', input.k)", false},
		{"known", "now", false},
		{"id", "input.now", false},
		{"at", "string(timestamp('1970-01-01T00:00:00Z') + duration(string(now) + 'ms'))", false},
		{"suffix", "string(now).substring(5)", true},
	} {
		if got := clockID(c.field, c.tpl); got != c.want {
			t.Errorf("clockID(%q, %q) = %v", c.field, c.tpl, got)
		}
	}
}

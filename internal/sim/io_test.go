package sim_test

import (
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §15.1: the io root holds the entry call, calls into external or
// attributes.boundary components, and route calls, and nothing internal.
const ioDoc = `
components:
  - {id: cli}
  - {id: api}
  - {id: core}
  - {id: pay, kind: external}
  - {id: mail, attributes: {boundary: true}}
  - id: edge
    router: {hosts: [edge.test]}
interfaces:
  - component: api
    name: order
    behavior:
      - {call: core.price, input: {sku: "= input.sku"}, as: p}
      - {call: pay.charge, input: {amount: "= vars.p.value.amount"}, as: c}
      - {call: mail.send, input: {to: "= input.to"}, as: m, on_error: continue}
      - call: {host: edge.test, path: /ping}
        as: r
      - {return: {order_id: "= id('order', input.sku)", charge: "= vars.c.value.id", n1: "= seq('o')", n2: "= seq('o')"}}
  - component: core
    name: price
    behavior:
      - {return: {amount: 42}}
  - component: pay
    name: charge
    behavior:
      - {return: {id: "= id('charge', input.amount)", headers: {x-trace: t1}}}
  - component: mail
    name: send
    behavior:
      - {fail: {code: bounced}}
  - component: edge
    name: ping
    attributes: {method: GET, path: /ping}
    behavior:
      - {return: {status: 200}}
flows:
  - {id: order, entry: {caller: cli, interface: api.order, input: {sku: s1, to: a@b}}}
scenarios:
  - id: order-io
    flow: order
    seed: 7
    expect:
      - "size(io) == 4"
      - "io[0].kind == 'entry' && io[0].dir == 'in' && io[0].interface == 'api.order' && io[0].input.sku == 's1'"
      - "io[0].output.ok && io[0].output.value.order_id == id('order', 's1')"
      - "io[1].kind == 'external' && io[1].dir == 'out' && io[1].interface == 'pay.charge' && io[1].input.amount == 42"
      - "io[1].output.value.id == id('charge', 42)"
      - "io[2].interface == 'mail.send' && !io[2].output.ok && io[2].output.error.code == 'bounced'"
      - "io[3].kind == 'route' && io[3].interface == 'edge.ping' && io[3].input.path == '/ping' && io[3].output.value.status == 200"
      - "!io.exists(i, i.interface == 'core.price')"
      - "io.all(i, i.seq >= 1 && i.duration_ms >= 0)"
      - "result.value.n1 == 1 && result.value.n2 == 2"
      - "io[1].headers['x-trace'] == 't1' && io[0].headers == null"
`

func TestIORoot(t *testing.T) {
	doc, err := model.ParseDocument([]byte(ioDoc))
	if err != nil {
		t.Fatal(err)
	}
	for _, is := range model.Validate(doc) {
		if is.Severity == model.SeverityError {
			t.Fatalf("test document: %s: %s", is.Path, is.Message)
		}
	}
	res, err := sim.Run(doc, sim.Request{Scenario: "order-io"})
	if err != nil {
		t.Fatal(err)
	}
	if res.Summary.Abort != "" {
		t.Fatalf("abort: %s", res.Summary.Abort)
	}
	if len(res.Summary.Assertions) != 11 {
		t.Fatalf("want 11 assertions, got %d", len(res.Summary.Assertions))
	}
	for _, a := range res.Summary.Assertions {
		if !a.Passed {
			t.Errorf("%s: failed %s", a.Expr, a.Error)
		}
	}
	// The same seed gives the same ids however the timing changes; another
	// seed gives others.
	slow := *doc
	slow.Interfaces = append([]model.Interface(nil), doc.Interfaces...)
	for i := range slow.Interfaces {
		if slow.Interfaces[i].ID == "core.price" {
			slow.Interfaces[i].LatencyMS = &model.Latency{Min: 250, Max: 250}
		}
	}
	id1 := res.Summary.Result.Value.(map[string]any)["order_id"]
	res2, err := sim.Run(&slow, sim.Request{Scenario: "order-io"})
	if err != nil {
		t.Fatal(err)
	}
	if res2.Summary.DurationMS == res.Summary.DurationMS {
		t.Fatalf("latency change didn't change the run's timing")
	}
	eq(t, "order id under other timing", res2.Summary.Result.Value.(map[string]any)["order_id"], id1)
	seed := int64(8)
	res3, err := sim.Run(doc, sim.Request{Scenario: "order-io", Seed: &seed})
	if err != nil {
		t.Fatal(err)
	}
	if res3.Summary.Result.Value.(map[string]any)["order_id"] == id1 {
		t.Errorf("another seed gave the same id %v", id1)
	}
}

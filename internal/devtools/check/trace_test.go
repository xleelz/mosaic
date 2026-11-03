package main

import (
	"bytes"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

const traceDoc = `schema_version: 1
id: tr
components:
  - {id: client}
  - {id: coord}
  - {id: node, capacity: {concurrency: 1}}
  - {id: bus}
interfaces:
  - {component: node, name: write, latency_ms: 5, behavior: [{set: {state.n: 1}}, {return: {ok: true}}]}
  - {component: node, name: on-written, subscribe: [bus.written], behavior: [{return: {}}]}
  - {component: bus, name: written, kind: event}
  - {component: node, name: read, behavior: [{return: "= state"}]}
  - component: coord
    name: put
    behavior:
      - parallel: [n1, n1, n3]   # the second write to n1 queues (capacity 1)
        as: replica
        steps:
          - {call: node.write, input: {}, on: "= vars.replica"}
        join: {need: 2}
        as_result: acks
      - {publish: bus.written, input: {}, delivery: sync}
      - {return: "= vars.acks.received"}
flows:
  - {id: put, entry: {caller: client, interface: coord.put}}
  - {id: read, entry: {caller: client, interface: node.read}}
scenarios:
  - id: put-then-read
    topology: {node: [n1, n2, n3]}
    steps:
      - {flow: put, as: put}
      - {flow: read, as: read, on: n2}
    mocks: [{interface: node.write, instance: n3, return: {ok: true}}]
    expect: ["steps.put.result.ok"]
`

func TestPrintTraceNewEvents(t *testing.T) {
	doc, err := model.ParseDocument([]byte(traceDoc))
	if err != nil {
		t.Fatal(err)
	}
	res, err := sim.Run(doc, sim.Request{Scenario: "put-then-read"})
	if err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	printTrace(&b, res.Trace)
	out := b.String()
	if !res.Summary.Passed {
		t.Fatalf("scenario failed: %s %v\n%s", res.Summary.Abort, res.Summary.Assertions, out)
	}
	for _, s := range []string{
		"▶ step put",
		"⫚ parallel 3 branches, need 2",
		"┆ branch 0",
		"┆ branch 2",
		"→ node.write@n1",
		"← node.write@n3 5ms (mock)",
		"⧗ queue node.write@n1 waited 5ms",
		"⫛ join 2/2 succeeded",
		"⇉ publish bus.written",
		"■ step put",
		"▶ step read",
		"= state.n on node@n1",
	} {
		if !strings.Contains(out, s) {
			t.Errorf("trace lacks %q:\n%s", s, out)
		}
	}
	// Branch bodies are indented under their branch header.
	lines := strings.Split(out, "\n")
	for i, l := range lines {
		if strings.Contains(l, "┆ branch 0") {
			hdr := len(l) - len(strings.TrimLeft(l, " "))
			next := lines[i+1]
			if ind := len(next) - len(strings.TrimLeft(next[11:], " ")) - 11; ind <= hdr-11 {
				t.Errorf("branch body not indented:\n%s\n%s", l, next)
			}
		}
	}
}

// §13.1 item 18: yield, put, receive and kill events.
func TestPrintTraceStreamsChannelsKills(t *testing.T) {
	doc, err := model.ParseDocument([]byte(`schema_version: 1
components:
  - {id: client}
  - {id: worker}
interfaces:
  - component: worker
    name: gen
    latency_ms: 0
    behavior:
      - {yield: tok}
      - {put: jobs, value: 1}
      - {receive: jobs, as: j}
      - {kill: {component: worker}}
flows:
  - {id: gen, entry: {caller: client, interface: worker.gen}}
`))
	if err != nil {
		t.Fatal(err)
	}
	res, err := sim.Run(doc, sim.Request{Flow: "gen"})
	if err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	printTrace(&b, res.Trace)
	out := b.String()
	for _, s := range []string{`↟ yield #0 "tok"`, "⇥ put jobs", "⇤ receive jobs", "✖ kill worker", "← worker.gen 0ms error killed"} {
		if !strings.Contains(out, s) {
			t.Errorf("trace lacks %q:\n%s", s, out)
		}
	}
}

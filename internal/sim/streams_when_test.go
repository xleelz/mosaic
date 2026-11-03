package sim_test

import (
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §17 item 12: streams_when. vLLM's chat route sends SSE frames
// only when the request says stream: true; otherwise it returns one plain
// response. api.chat yields only on the streaming path; api.leaky yields
// on both, so its plain calls abort.
const streamsWhenDoc = `
components:
  - {id: client}
  - {id: api}
interfaces:
  - component: api
    name: chat
    latency_ms: 0
    streams_when: "= input.stream == true"
    behavior:
      - if: "input.stream == true"
        then:
          - {yield: {delta: Hel}}
          - {yield: {delta: lo}}
      - {return: {text: Hello}}
  - component: api
    name: leaky
    latency_ms: 0
    streams_when: "= input.stream"
    behavior:
      - {yield: {delta: x}}
      - {return: {text: x}}
  - component: api
    name: always
    latency_ms: 0
    behavior:
      - {yield: {delta: x}}
      - {return: {text: x}}
  - component: client
    name: plain
    latency_ms: 0
    behavior:
      - {call: api.chat, input: {stream: false}, as: r}
      - {return: "= vars.r.value"}
  - component: client
    name: buffered
    latency_ms: 0
    behavior:
      - {call: api.chat, input: {stream: true}, as: r}
      - {return: "= vars.r.value"}
  - component: client
    name: live
    latency_ms: 0
    behavior:
      - {set: {vars.got: []}}
      - call: api.chat
        input: {stream: true}
        stream: true
        as: r
        on_item: [{set: {vars.got: "= vars.got + [vars.item.delta]"}}]
      - {return: {got: "= vars.got", value: "= vars.r.value"}}
  - component: client
    name: live-plain
    latency_ms: 0
    behavior:
      - call: api.chat
        input: {stream: false}
        stream: true
        as: r
        on_item: [{fail: {code: unexpected}}]
      - {return: "= vars.r.value"}
  - component: client
    name: leaky
    latency_ms: 0
    behavior:
      - {call: api.leaky, input: {stream: false}, as: r}
      - {return: "= vars.r.value"}
  - component: client
    name: not-bool
    latency_ms: 0
    behavior:
      - {call: api.leaky, input: {stream: 1}, as: r}
      - {return: "= vars.r.value"}
  - component: client
    name: always
    latency_ms: 0
    behavior:
      - {call: api.always, input: {stream: false}, as: r}
      - {return: "= vars.r.value"}
flows:
  - {id: plain, entry: {caller: client, interface: client.plain}}
  - {id: buffered, entry: {caller: client, interface: client.buffered}}
  - {id: live, entry: {caller: client, interface: client.live}}
  - {id: live-plain, entry: {caller: client, interface: client.live-plain}}
  - {id: leaky, entry: {caller: client, interface: client.leaky}}
  - {id: not-bool, entry: {caller: client, interface: client.not-bool}}
  - {id: always, entry: {caller: client, interface: client.always}}
scenarios:
  - {id: plain, flow: plain, expect: ["result.value == {'text': 'Hello'}"]}
  - id: buffered
    flow: buffered
    expect: ["result.value == {'items': [{'delta': 'Hel'}, {'delta': 'lo'}], 'value': {'text': 'Hello'}}"]
  - {id: live, flow: live, expect: ["result.value == {'got': ['Hel', 'lo'], 'value': {'text': 'Hello'}}"]}
  - {id: live-plain, flow: live-plain, expect: ["result.value == {'text': 'Hello'}"]}
  - id: always
    flow: always
    expect: ["result.value == {'items': [{'delta': 'x'}], 'value': {'text': 'x'}}"]
`

func TestStreamsWhen(t *testing.T) {
	doc := langDoc(t, streamsWhenDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
	for flow, want := range map[string]string{
		"leaky":    "api.leaky.behavior[0]: yield on a call whose streams_when (= input.stream) is false",
		"not-bool": "api.leaky.streams_when",
	} {
		res := run(t, doc, sim.Request{Flow: flow})
		if res.Summary.Status != "aborted" || !strings.Contains(res.Summary.Abort, want) {
			t.Errorf("%s: want an abort with %q, got %s %q", flow, want, res.Summary.Status, res.Summary.Abort)
		}
	}
}

func TestStreamsWhenValidation(t *testing.T) {
	for _, c := range []struct{ iface, msg string }{
		{`{component: api, name: x, streams_when: "input.stream", behavior: [{yield: 1}]}`, `must be an "=cel" expression`},
		{`{component: api, name: x, streams_when: "= input.stream &&", behavior: [{yield: 1}]}`, "invalid expression"},
		{`{component: api, name: x, streams_when: "= input.stream", behavior: [{return: 1}]}`, "needs a behavior that can yield"},
	} {
		doc, err := model.ParseDocument([]byte("schema_version: 1\ncomponents: [{id: api}]\ninterfaces:\n  - " + c.iface + "\n"))
		if err != nil {
			t.Fatal(err)
		}
		found := false
		for _, is := range model.Validate(doc) {
			if is.Severity == model.SeverityError && is.Path == "interfaces[api.x].streams_when" && strings.Contains(is.Message, c.msg) {
				found = true
			}
		}
		if !found {
			t.Errorf("%s: want %q, got %v", c.iface, c.msg, model.Validate(doc))
		}
	}
	// A nested yield counts.
	doc, err := model.ParseDocument([]byte(`schema_version: 1
components: [{id: api}]
interfaces:
  - component: api
    name: x
    streams_when: "= input.stream"
    behavior: [{if: "true", then: [{foreach: "= [1]", steps: [{yield: 1}]}]}]
`))
	if err != nil {
		t.Fatal(err)
	}
	for _, is := range model.Validate(doc) {
		if is.Severity == model.SeverityError {
			t.Errorf("nested yield: %s: %s", is.Path, is.Message)
		}
	}
}

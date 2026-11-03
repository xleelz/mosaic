package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

// A tRPC view, an SSE chat stream and an event body, as the prep would write
// them from the code.
const contractFileSrc = `
contracts:
  - id: models.list
    match: {interface: "web.models-*"}
    sources: [src/server/routers/models.ts:12-40]
    request:
      type: object
      required: [orgId]
      properties: {orgId: {type: string}, cursor: {type: string}}
    response:
      type: object
      properties:
        items:
          type: array
          items: {$ref: "#/defs/Model"}
        total: {type: integer}
    errors:
      - {code: UNAUTHORIZED, status: 401}
      - {code: NOT_FOUND, status: 404}
      - {code: TOO_MANY_REQUESTS}
  - id: chat.sse
    match: {route: {method: POST, path: /v1/chat/completions}}
    sources: [src/server/sse.ts:5-80]
    response:
      type: object
      properties: {status: {const: 200}, body: {type: object, properties: {id: {type: string}}}}
    stream:
      frames:
        - name: chunk
          schema:
            type: object
            required: [object, choices]
            properties:
              object: {const: chat.completion.chunk}
              choices: {type: array}
        - name: usage
          schema:
            type: object
            required: [object, usage]
            properties:
              object: {const: chat.completion.chunk}
              choices: {type: array}
              usage: {type: object, properties: {total_tokens: {type: integer}}}
        - name: done
          schema: {const: "[DONE]"}
      terminator: done
      order: "chunk( chunk)*( usage)? done"
  - id: event.signup
    match: {attributes: {event: user_signed_up}}
    request: {type: object, properties: {distinct_id: {type: string}, plan: {type: string}}}
  - id: gone
    match: {interface: web.nothing}
    sources: [src/gone.ts]
defs:
  Model:
    type: object
    required: [id, modality, updatedAt]
    properties:
      id: {type: string}
      modality: {type: string}
      updatedAt: {type: string}
`

const contractModel = `
schema_version: 1
components:
  - {id: web}
  - {id: gw}
  - {id: client}
interfaces:
  - component: web
    name: models-list
    kind: trpc
    request:
      type: object
      required: [org_id]
      properties: {org_id: {type: string}, cursor: {type: string}}
    response:
      type: object
      properties:
        items: {type: array, items: {type: object, properties: {id: {type: string}, updatedAt: {type: integer}}}}
        total: {type: integer}
    errors:
      - {code: UNAUTHORIZED, status: 401}
      - {code: TOO_MANY_REQUESTS, status: 429}
      - {code: CONFLICT, status: 409}
  - component: gw
    name: chat
    kind: http
    attributes: {method: POST, path: /v1/chat/completions}
    request: {type: object, properties: {body: {type: object}}}
    response:
      type: object
      properties: {status: {type: integer, const: 200}, body: {type: object, properties: {id: {type: string}}}}
    behavior:
      - foreach: "= ['a', 'b']"
        as: tok
        steps:
          - yield: "= {'object': 'chat.completion.chunk', 'choices': [{'delta': {'content': vars.tok}}]}"
      - yield: "= {'object': 'chat.completion.chunk', 'choices': [], 'usage': {'total_tokens': 'seven'}}"
      - return: {status: 200, body: {id: c1}}
  - component: web
    name: track-signup
    kind: event
    attributes: {event: user_signed_up}
    request: {type: object, properties: {distinct_id: {type: string}, plan: {type: string}}}
  - component: client
    name: send
    behavior:
      - {call: gw.chat, as: r}
flows:
  - {id: chat, entry: {caller: client, interface: client.send}}
scenarios:
  - {id: chat-stream, flow: chat, expect: ["result.ok"]}
`

func TestContracts(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "contracts.yaml")
	if err := os.WriteFile(p, []byte(contractFileSrc), 0o644); err != nil {
		t.Fatal(err)
	}
	doc, err := model.ParseDocument([]byte(contractModel))
	if err != nil {
		t.Fatal(err)
	}
	for _, is := range model.Validate(doc) {
		if is.Severity == model.SeverityError {
			t.Fatalf("test document: %s: %s", is.Path, is.Message)
		}
	}
	var b bytes.Buffer
	over, err := runContracts(&b, doc, []string{"contracts.yaml"}, contractOpts{Code: dir, Max: 2, Run: true})
	if err != nil {
		t.Fatal(err)
	}
	out := b.String()
	if !over {
		t.Error("gate should fail above 2 issues")
	}
	for _, want := range []string{
		"✗ contract models.list -> web.models-list",
		"missing: response body.items[].modality (string)",                  // a missing response field
		"type: response body.items[].updatedAt: spec string, model integer", // a wrong type
		"error-missing: error status 404 (NOT_FOUND)",                       // a missing error
		"error-extra: error status 409 (CONFLICT)",
		"✗ contract chat.sse -> gw.chat",
		"terminator: the stream ends with {choices,object,usage}, not the terminator done (scenario chat-stream)",
		"frame-order: yields \"chunk*2 usage\" don't match order",
		"type: frame usage usage.total_tokens: contract integer, yielded string",
		"~ contract chat.sse -> gw.chat: frames no scenario yielded: done",
		"! contract event.signup cites no sources",
		"✗ contract unmodeled: gone matches no interface (interface web.nothing)",
		"contracts: 4 contracts in 1 files, 3 interfaces compared (1 clean), 1 unmodeled",
		"1 streamed calls read, 1 frames no scenario yielded",
		"✗ contracts: 8 issues, above --max-contract-issues 2",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in\n%s", want, out)
		}
	}
	for _, bad := range []string{
		"org_id",            // orgId = org_id
		"TOO_MANY_REQUESTS", // matched by code
		"event.signup ->",   // clean
		"frame-missing:",    // the expression templates could yield [DONE]
	} {
		if strings.Contains(out, bad) {
			t.Errorf("unexpected %q in\n%s", bad, out)
		}
	}
}

// A literal [DONE] the behavior never yields is frame-missing; a stream
// contract on an interface that never yields is frame-missing too.
func TestContractFrameMissing(t *testing.T) {
	ifc := &model.Interface{ID: "gw.chat", Behavior: []model.Step{{Yield: []byte(`{"object":"chunk"}`)}}}
	c := &contract{ID: "c", file: &oaDoc{Root: map[string]any{}}, Stream: &contractStream{
		Frames:     []contractFrame{{Name: "chunk", Schema: map[string]any{"properties": map[string]any{"object": map[string]any{"const": "chunk"}}}}, {Name: "done", Schema: map[string]any{"const": "[DONE]"}}},
		Terminator: "done",
	}}
	r := &contractResult{}
	compareStream(r, c, ifc, map[string][]yieldCall{"gw.chat": {{Scenario: "s", Items: []any{map[string]any{"object": "chunk"}, "[DONE]"}}}})
	if len(r.Issues) != 0 {
		t.Errorf("a stream ending in the terminator: %v", r.Issues)
	}
	r = &contractResult{}
	compareStream(r, c, ifc, map[string][]yieldCall{})
	if len(r.Issues) != 1 || r.Issues[0].Kind != "frame-missing" || !strings.Contains(r.Issues[0].Msg, "frame done") {
		t.Errorf("want frame done missing: %v", r.Issues)
	}
	if !r.streamUnrun || len(r.unrunFrames) != 1 || r.unrunFrames[0] != "chunk" {
		t.Errorf("unrun: %v %v", r.streamUnrun, r.unrunFrames)
	}
	r = &contractResult{}
	compareStream(r, c, &model.Interface{ID: "gw.chat"}, nil)
	if len(r.Issues) != 1 || !strings.Contains(r.Issues[0].Msg, "no yield step") {
		t.Errorf("want no yield step: %v", r.Issues)
	}
}

package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

const confSpec = `
openapi: 3.1.0
security: [{apiKey: []}]
components:
  parameters:
    OrgId: {name: orgId, in: path, required: true, schema: {type: string}}
  schemas:
    Org:
      type: object
      required: [id, name]
      properties:
        id: {type: string}
        name: {type: string}
        plan: {type: [string, "null"]}
        seats: {type: integer}
    Named:
      allOf:
        - {$ref: "#/components/schemas/Org"}
        - {type: object, properties: {extra: {type: boolean}}}
    Either:
      oneOf:
        - {type: string}
        - {type: object, properties: {a: {type: string}}}
paths:
  /v1/orgs/{orgId}:
    parameters:
      - {$ref: "#/components/parameters/OrgId"}
    get:
      operationId: getOrg
      parameters:
        - {name: verbose, in: query, schema: {type: boolean}}
      responses:
        "200":
          content: {application/json: {schema: {$ref: "#/components/schemas/Org"}}}
        "401": {description: no}
        "404": {description: no}
    patch:
      operationId: updateOrg
      requestBody:
        required: true
        content: {application/json: {schema: {type: object, required: [name, billingEmail], properties: {name: {type: string}, billingEmail: {type: string}}}}}
      responses:
        "200":
          content: {application/json: {schema: {$ref: "#/components/schemas/Named"}}}
  /v1/things:
    get:
      operationId: listThings
      responses:
        "200":
          content: {application/json: {schema: {$ref: "#/components/schemas/Either"}}}
  /v1/unmodeled:
    post:
      operationId: nobody
      responses: {"204": {description: ok}}
`

func confDoc() *model.Document {
	obj := func(req []any, props map[string]any) map[string]any {
		m := map[string]any{"type": "object", "properties": props}
		if req != nil {
			m["required"] = req
		}
		return m
	}
	str := map[string]any{"type": "string"}
	return &model.Document{
		Schemas: []model.Schema{{ID: "OrgView", Schema: obj(nil, map[string]any{
			"id": str, "name": str, "plan": str, "seats": map[string]any{"type": "string"}, "legacy": str,
		})}},
		Interfaces: []model.Interface{
			{ID: "orgs.get-v1-orgs-orgid", Component: "orgs", Name: "get-v1-orgs-orgid", Kind: "http",
				Attributes: map[string]any{"method": "GET", "path": "/v1/orgs/{org_id}"},
				Request: obj([]any{"org_id", "authorization", "x_org_id"}, map[string]any{
					"org_id": str, "authorization": str, "x_org_id": str,
				}),
				Response: obj(nil, map[string]any{"status": map[string]any{"type": "integer", "const": 200.0}, "body": "OrgView"}),
				Errors:   []model.ErrorSpec{{Code: "NOT_FOUND", Status: 404}, {Code: "BOOM", Status: 500}, {Code: "CONFLICT", Status: 409}},
			},
			// Matched by name only; a flattened body, name optional.
			{ID: "orgs.patch-v1-orgs-orgid", Component: "orgs", Name: "patch-v1-orgs-orgid", Kind: "http",
				Request:  obj([]any{"org_id"}, map[string]any{"org_id": str, "name": str, "billing_email": str}),
				Behavior: []model.Step{{If: "!has(input.billing_email)", Then: []model.Step{{Fail: []byte(`{"code":"BAD_REQUEST","status":400}`)}}}},
				Response: obj(nil, map[string]any{"status": map[string]any{"type": "integer", "const": 201.0},
					"body": obj(nil, map[string]any{"id": str, "name": str, "plan": str, "seats": map[string]any{"type": "number"}, "extra": map[string]any{"type": "boolean"}})}),
			},
			{ID: "orgs.get-v1-things", Component: "orgs", Name: "get-v1-things", Kind: "http",
				Response: obj(nil, map[string]any{"body": map[string]any{"type": "object"}})},
			{ID: "orgs.get-v1-gone", Component: "orgs", Name: "get-v1-gone", Kind: "http",
				Attributes: map[string]any{"method": "GET", "path": "/v1/gone"}},
			{ID: "other.get-v1-elsewhere", Component: "other", Name: "get-v1-elsewhere", Kind: "http",
				Attributes: map[string]any{"method": "GET", "path": "/v1/elsewhere"}},
			{ID: "cli.orgs-get", Component: "cli", Name: "orgs-get", Kind: "cli-command",
				Attributes: map[string]any{"method": "GET", "path": "/v1/orgs/{orgId}", "calls": "orgs.get-v1-orgs-orgid"}},
		},
	}
}

func TestConformance(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "openapi.yaml")
	if err := os.WriteFile(p, []byte(confSpec), 0o644); err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	over, err := runConformance(&b, confDoc(), []string{"openapi.yaml"}, dir, 3, false)
	if err != nil {
		t.Fatal(err)
	}
	out := b.String()
	if !over {
		t.Error("gate should fail above 3 issues")
	}
	for _, want := range []string{
		"getOrg GET /v1/orgs/{orgId} -> orgs.get-v1-orgs-orgid",
		"missing: request query verbose (boolean)",
		"required: request x_org_id: an undeclared header, model required",
		"type: response body.seats: spec integer, model string",
		"extra: response body.legacy (string)",
		"error-missing: error status 401",
		"error-extra: error status 409 (CONFLICT)",
		"1 undeclared 500s, 1 required fields the behavior enforces",
		"updateOrg PATCH /v1/orgs/{orgId} -> orgs.patch-v1-orgs-orgid",
		"required: request body.name: spec required, model optional",
		"status: success status: spec [200], model [201]",
		"unmodeled: nobody POST /v1/unmodeled",
		"orphan route: orgs.get-v1-gone: GET /v1/gone matches no operation",
		"skipped: complex 1",
		"route interfaces on other components 1, client wrappers 1",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in\n%s", want, out)
		}
	}
	for _, bad := range []string{
		"authorization",                          // the security scheme's header
		"body.plan",                              // nullable string vs string
		"body.seats: spec integer, model number", // integer and number are compatible
		"billing",                                // billingEmail = billing_email; required enforced by the behavior
		"status 500",                             // the generic internal error
		"body.extra",                             // allOf merged
		"other.get-v1-elsewhere",
		"cli.orgs-get",
	} {
		if strings.Contains(out, bad) {
			t.Errorf("unexpected %q in\n%s", bad, out)
		}
	}
}

func TestBuildShapeOneOfNull(t *testing.T) {
	s := buildShape(map[string]any{"oneOf": []any{map[string]any{"type": "integer"}, map[string]any{"type": "null"}}}, nil, 0)
	if !s.Nullable || !s.Types["integer"] || s.Complex {
		t.Errorf("%+v", s)
	}
}

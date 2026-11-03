package model

import (
	"encoding/json"
	"testing"
)

// An error declaration's reachable_by (§13.1 item 33) decodes, validates
// and round-trips.
func TestErrorReachableByRoundTrip(t *testing.T) {
	doc, err := ParseDocument([]byte(`schema_version: 1
components: [{id: db}]
interfaces:
  - component: db
    name: g
    errors:
      - {code: conflict, status: 409, reachable_by: "input.version != state.version"}
      - {code: busy, status: 503, retryable: true, reachable_by: "only under load; not modeled"}
`))
	if err != nil {
		t.Fatal(err)
	}
	if issues := Validate(doc); HasErrors(issues) {
		t.Fatalf("issues: %+v", issues)
	}
	errs := doc.Interfaces[0].Errors
	if errs[0].ReachableBy != "input.version != state.version" || errs[1].ReachableBy != "only under load; not modeled" {
		t.Fatalf("decoded %+v", errs)
	}
	b, err := json.Marshal(errs[1])
	if err != nil {
		t.Fatal(err)
	}
	var back ErrorSpec
	if err := Decode(b, &back); err != nil || back != errs[1] {
		t.Fatalf("round trip: %s -> %+v (%v)", b, back, err)
	}
	if b, _ := json.Marshal(ErrorSpec{Code: "x"}); string(b) != `{"code":"x"}` {
		t.Errorf("an error without reachable_by encodes as %s", b)
	}
}

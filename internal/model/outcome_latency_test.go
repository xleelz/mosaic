package model_test

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

const outcomeLatencyDoc = `schema_version: 1
id: vm
components:
  - {id: wf}
configs:
  - {id: deploy-deadline-ms, default: 2700000}
interfaces:
  - component: wf
    name: run
    latency_ms: 50
    latency_by_outcome:
      - {when: "result.ok && result.value.outcome == 'healthy'", ms: 4000}
      - {when: "!result.ok && result.error.code == 'deploy_timeout'", ms: "=config['deploy-deadline-ms']"}
      - {when: "result.ok && input.fast", ms: 0.5}
`

func TestLatencyByOutcomeRoundTrip(t *testing.T) {
	d, err := model.ParseDocument([]byte(outcomeLatencyDoc))
	if err != nil {
		t.Fatal(err)
	}
	if errs := errorsOf(model.Validate(d)); len(errs) > 0 {
		t.Fatalf("validate: %v", errs)
	}
	want := []model.OutcomeLatency{
		{When: "result.ok && result.value.outcome == 'healthy'", MS: model.Latency{Min: 4000, Max: 4000}},
		{When: "!result.ok && result.error.code == 'deploy_timeout'", MS: model.Latency{Expr: "config['deploy-deadline-ms']"}},
		{When: "result.ok && input.fast", MS: model.Latency{Min: 0.5, Max: 0.5}},
	}
	if got := d.Interfaces[0].LatencyByOutcome; !reflect.DeepEqual(got, want) {
		t.Fatalf("parsed: %#v", got)
	}
	b, err := json.Marshal(d.Interfaces[0].LatencyByOutcome)
	if err != nil {
		t.Fatal(err)
	}
	const enc = `[{"when":"result.ok && result.value.outcome == 'healthy'","ms":4000},` +
		`{"when":"!result.ok && result.error.code == 'deploy_timeout'","ms":"=config['deploy-deadline-ms']"},` +
		`{"when":"result.ok && input.fast","ms":0.5}]`
	if got := strings.ReplaceAll(string(b), `\u0026`, "&"); got != enc {
		t.Errorf("encoded:\n%s\nwant\n%s", b, enc)
	}
	full, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	d2, err := model.ParseDocument(full)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(d2.Interfaces[0].LatencyByOutcome, want) {
		t.Errorf("round trip: %#v", d2.Interfaces[0].LatencyByOutcome)
	}
}

func TestLatencyByOutcomeValidation(t *testing.T) {
	cases := []struct {
		entry, path, msg string
	}{
		{`{when: "", ms: 5}`, "interfaces[wf.run].latency_by_outcome[0].when", "when is required"},
		{`{when: "result.ok &&", ms: 5}`, "interfaces[wf.run].latency_by_outcome[0].when", "invalid expression"},
		{`{when: "state.x == 1", ms: 5}`, "interfaces[wf.run].latency_by_outcome[0].when", "invalid expression"}, // only result, input, config
		{`{when: "result.ok", ms: {min: 1, max: 9}}`, "interfaces[wf.run].latency_by_outcome[0].ms", "not a range"},
		{`{when: "result.ok", ms: -1}`, "interfaces[wf.run].latency_by_outcome[0].ms", "ms >= 0"},
		{`{when: "result.ok", ms: "=vars.x"}`, "interfaces[wf.run].latency_by_outcome[0].ms", "invalid expression"},
	}
	for _, c := range cases {
		src := `schema_version: 1
components: [{id: wf}]
interfaces:
  - {component: wf, name: run, latency_by_outcome: [` + c.entry + `]}
`
		d, err := model.ParseDocument([]byte(src))
		if err != nil {
			t.Errorf("%s: parse: %v", c.entry, err)
			continue
		}
		if is := model.Validate(d); !hasIssue(is, c.path, c.msg) {
			t.Errorf("%s: want %s %q, got %v", c.entry, c.path, c.msg, is)
		}
	}
	// ms must be milliseconds or "=cel".
	if _, err := model.ParseDocument([]byte(`schema_version: 1
components: [{id: wf}]
interfaces:
  - {component: wf, name: run, latency_by_outcome: [{when: "result.ok", ms: "slow"}]}
`)); err == nil {
		t.Error(`ms: "slow" parsed`)
	}
}

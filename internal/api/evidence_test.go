package api_test

import (
	"encoding/json"
	"strings"
	"testing"

	wire "github.com/xleelz/mosaic/pkg/api"
)

func sampleEvidence(steps int) wire.Evidence {
	return wire.Evidence{
		BuiltBy: "generated",
		Source:  &wire.EvidenceSource{Repo: "o/r", Commit: "abc"},
		Blind:   &wire.EvidenceBlind{Benchmark: "round", StepsPassed: steps, StepsTotal: 10, CasesPassed: 1, CasesTotal: 2, OraclePassed: 3, OracleTotal: 4, MeasuredAt: "2026-11-05"},
		Mechanisms: &wire.EvidenceMechanisms{Items: []wire.EvidenceMechanism{
			{ID: "a.sweep", Area: "a", Kind: "sweep", Name: "Sweep", Citations: []string{"a.go:1"}, Interfaces: []string{"a.run"}, Fidelity: "modeled", GateStatus: "ok"},
			{ID: "a.cache", Area: "a", Kind: "cache", Name: "Cache", Fidelity: "absent"},
		}},
	}
}

func cutRevision(t *testing.T, base, msg string) {
	t.Helper()
	call(t, "POST", base+"/revisions", wire.CreateRevision{Message: msg, AllowEmpty: true}, 201)
}

func TestEvidence(t *testing.T) {
	id := "evidence-api"
	newOntology(t, id, true)
	base := "/v1/ontologies/" + id
	path := base + "/evidence"

	// Nothing anywhere, and nowhere to put it yet.
	call(t, "GET", path, nil, 404)
	if e := errCode(t, call(t, "PUT", path, sampleEvidence(1), 404)); e.Code != "not_found" {
		t.Fatalf("put with no revisions: %+v", e)
	}
	call(t, "GET", "/v1/ontologies/no-such-ontology/evidence", nil, 404)

	cutRevision(t, base, "one")
	cutRevision(t, base, "two")
	cutRevision(t, base, "three")
	call(t, "GET", path+"?rev=1", nil, 404)
	call(t, "GET", path+"?rev=latest", nil, 404)

	// Stored on r2, in the shape of types.ts.
	put := decode[wire.Evidence](t, call(t, "PUT", path+"?rev=2", sampleEvidence(5), 200))
	if put.Revision != 2 || put.Blind.MeasuredOnRevision != 2 || put.Mechanisms.MeasuredOnRevision != 2 {
		t.Fatalf("put = %+v", put)
	}
	raw := string(call(t, "GET", path+"?rev=2", nil, 200))
	var shape map[string]any
	if err := json.Unmarshal([]byte(raw), &shape); err != nil {
		t.Fatal(err)
	}
	if shape["revision"] != float64(2) || shape["built_by"] != "generated" {
		t.Fatalf("shape = %s", raw)
	}
	items := shape["mechanisms"].(map[string]any)["items"].([]any)
	absent := items[1].(map[string]any)
	if ifs, ok := absent["interfaces"].([]any); !ok || len(ifs) != 0 {
		t.Fatalf("an absent mechanism must have interfaces: []: %s", raw)
	}
	if _, ok := absent["gate_status"]; ok {
		t.Fatalf("gate_status should be omitted when unset: %s", raw)
	}

	// Earlier: none. Later: inherited, with the viewed revision. Draft: inherited, revision 0.
	call(t, "GET", path+"?rev=1", nil, 404)
	for _, c := range []struct {
		sel  string
		want int
	}{{"3", 3}, {"r3", 3}, {"latest", 3}, {"draft", 0}, {"", 0}} {
		q := path
		if c.sel != "" {
			q += "?rev=" + c.sel
		}
		ev := decode[wire.Evidence](t, call(t, "GET", q, nil, 200))
		if ev.Revision != c.want || ev.Blind.MeasuredOnRevision != 2 || ev.Mechanisms.MeasuredOnRevision != 2 || ev.Blind.StepsPassed != 5 {
			t.Fatalf("rev %q = %+v", c.sel, ev)
		}
	}

	// r3 gets its own, naming an older blind; r2 is unchanged, and a PUT with no rev is the latest.
	own := sampleEvidence(7)
	own.Revision = 99 // ignored
	own.Blind.MeasuredOnRevision = 1
	got := decode[wire.Evidence](t, call(t, "PUT", path, own, 200))
	if got.Revision != 3 || got.Blind.MeasuredOnRevision != 1 || got.Mechanisms.MeasuredOnRevision != 3 {
		t.Fatalf("put latest = %+v", got)
	}
	if ev := decode[wire.Evidence](t, call(t, "GET", path+"?rev=2", nil, 200)); ev.Blind.StepsPassed != 5 {
		t.Fatalf("r2 changed: %+v", ev)
	}
	if ev := decode[wire.Evidence](t, call(t, "GET", path+"?rev=3", nil, 200)); ev.Blind.StepsPassed != 7 {
		t.Fatalf("r3 = %+v", ev)
	}
	// A PUT replaces the whole record.
	call(t, "PUT", path+"?rev=3", `{"built_by":"handwritten"}`, 200)
	if ev := decode[wire.Evidence](t, call(t, "GET", path+"?rev=3", nil, 200)); ev.Blind != nil || ev.Mechanisms != nil || ev.BuiltBy != "handwritten" {
		t.Fatalf("after replace: %+v", ev)
	}

	// Refusals.
	if e := errCode(t, call(t, "PUT", path+"?rev=draft", sampleEvidence(1), 400)); !strings.Contains(e.Message, "draft") {
		t.Fatalf("draft: %+v", e)
	}
	call(t, "PUT", path+"?rev=9", sampleEvidence(1), 404)
	call(t, "GET", path+"?rev=9", nil, 404)
	call(t, "GET", path+"?rev=nope", nil, 400)
	call(t, "PUT", path+"?rev=1", `{"unknown":1}`, 400)
	call(t, "PUT", path+"?rev=1", ``, 400)
	mutate := func(f func(*wire.Evidence)) wire.Evidence {
		e := sampleEvidence(1)
		f(&e)
		return e
	}
	for _, c := range []struct {
		name string
		body any
		path string
	}{
		{"empty", `{}`, ""},
		{"built_by", mutate(func(e *wire.Evidence) { e.BuiltBy = "magic" }), "built_by"},
		{"future blind", mutate(func(e *wire.Evidence) { e.Blind.MeasuredOnRevision = 2 }), "blind.measured_on_revision"},
		{"future list", mutate(func(e *wire.Evidence) { e.Mechanisms.MeasuredOnRevision = 2 }), "mechanisms.measured_on_revision"},
		{"passed over total", mutate(func(e *wire.Evidence) { e.Blind.StepsPassed = 11 }), "blind.steps_passed"},
		{"negative", mutate(func(e *wire.Evidence) { e.Blind.OraclePassed = -1 }), "blind.oracle_passed"},
		{"measures nothing", mutate(func(e *wire.Evidence) { e.Blind = &wire.EvidenceBlind{} }), "blind"},
		{"measured_at", mutate(func(e *wire.Evidence) { e.Blind.MeasuredAt = "last week" }), "blind.measured_at"},
		{"no items", mutate(func(e *wire.Evidence) { e.Mechanisms.Items = nil }), "mechanisms.items"},
		{"fidelity", mutate(func(e *wire.Evidence) { e.Mechanisms.Items[0].Fidelity = "great" }), "mechanisms.items[0].fidelity"},
		{"gate", mutate(func(e *wire.Evidence) { e.Mechanisms.Items[0].GateStatus = "reached" }), "mechanisms.items[0].gate_status"},
		{"no id", mutate(func(e *wire.Evidence) { e.Mechanisms.Items[1].ID = "" }), "mechanisms.items[1].id"},
		{"no area", mutate(func(e *wire.Evidence) { e.Mechanisms.Items[1].Area = "" }), "mechanisms.items[1].area"},
		{"duplicate", mutate(func(e *wire.Evidence) { e.Mechanisms.Items[1].ID = "a.sweep" }), "mechanisms.items[1].id"},
		{"absent with interfaces", mutate(func(e *wire.Evidence) { e.Mechanisms.Items[1].Interfaces = []string{"a.run"} }), "mechanisms.items[1].interfaces"},
	} {
		e := errCode(t, call(t, "PUT", path+"?rev=1", c.body, 422))
		if e.Code != "invalid" || len(e.Issues) == 0 || e.Issues[0].Path != c.path {
			t.Errorf("%s: %+v", c.name, e)
		}
	}
	call(t, "GET", path+"?rev=1", nil, 404) // nothing was stored

	// Other routes under {kind} still answer as before.
	call(t, "GET", base+"/components", nil, 200)
	call(t, "POST", path, `{}`, 404)

	// Dropping the ontology drops its evidence: a new one with this id has none.
	call(t, "DELETE", base, nil, 204)
	newOntology(t, id, true)
	cutRevision(t, base, "again")
	call(t, "GET", path, nil, 404)
	call(t, "GET", path+"?rev=1", nil, 404)
}

func TestTestResults(t *testing.T) {
	id := "test-results-api"
	newOntology(t, id, true)
	base := "/v1/ontologies/" + id
	results := base + "/test-results"

	call(t, "GET", results, nil, 404)
	call(t, "GET", "/v1/ontologies/no-such-ontology/test-results", nil, 404)
	call(t, "GET", results+"?rev=1", nil, 404)
	cutRevision(t, base, "one")
	cutRevision(t, base, "two")
	call(t, "GET", results+"?rev=1", nil, 404)

	// Without saving traces, it is still recorded, and under this revision only.
	rep := decode[wire.TestReport](t, call(t, "POST", base+"/test?rev=1&save=false", nil, 200))
	if rep.Total == 0 {
		t.Fatalf("the example has no scenarios: %+v", rep)
	}
	body := call(t, "GET", results+"?rev=1", nil, 200)
	got := decode[wire.StoredTestReport](t, body)
	if got.RanAt.IsZero() || got.Revision != "1" || got.Total != rep.Total || got.Failed != rep.Failed || got.Passed != rep.Passed || len(got.Results) != len(rep.Results) {
		t.Fatalf("stored = %+v, ran = %+v", got, rep)
	}
	if got.Results[0].Scenario != rep.Results[0].Scenario || got.Results[0].RunID != "" {
		t.Fatalf("stored result = %+v", got.Results[0])
	}
	if len(got.Results[0].Assertions) != len(rep.Results[0].Assertions) {
		t.Fatalf("assertions lost: %+v", got.Results[0])
	}
	if strings.Contains(string(body), `"trace"`) {
		t.Fatalf("a stored report must not hold traces: %s", body)
	}
	call(t, "GET", results+"?rev=2", nil, 404) // not inherited
	call(t, "GET", results, nil, 404)          // the draft hasn't run

	// Saving traces records too, and the newest report replaces the last.
	rep2 := decode[wire.TestReport](t, call(t, "POST", base+"/test?rev=1", nil, 200))
	got2 := decode[wire.StoredTestReport](t, call(t, "GET", results+"?rev=1", nil, 200))
	if got2.Results[0].RunID == "" || got2.Results[0].RunID != rep2.Results[0].RunID || got2.RanAt.Before(got.RanAt) {
		t.Fatalf("second report = %+v, first ran at %s", got2, got.RanAt)
	}
	call(t, "GET", results+"?rev=latest", nil, 404) // r2 never ran

	// The draft is its own slot.
	call(t, "POST", base+"/test?save=false", nil, 200)
	if d := decode[wire.StoredTestReport](t, call(t, "GET", results+"?rev=draft", nil, 200)); d.Revision != "draft" {
		t.Fatalf("draft report = %+v", d)
	}
	call(t, "GET", results, nil, 200)

	// Dropping the ontology drops its reports.
	call(t, "DELETE", base, nil, 204)
	newOntology(t, id, true)
	call(t, "GET", results, nil, 404)
}

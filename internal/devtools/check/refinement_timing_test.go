package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

// vmParent's deployer.provision is one black box with one latency; vmChild
// refines it: healthy VMs answer in seconds, degraded ones a little later,
// and a VM that never becomes healthy waits out the 45-minute deadline.
const vmParent = `schema_version: 1
id: relay
level: service
components:
  - {id: client}
  - {id: api}
  - {id: deployer}
interfaces:
  - component: deployer
    name: provision
    latency_ms: 500
    errors: [{code: deploy_timeout, status: 504}]
    behavior:
      - if: "input.vm == 'stuck'"
        then: [{fail: {code: deploy_timeout, status: 504}}]
      - {return: {outcome: "= input.vm == 'slow' ? 'degraded' : 'healthy'"}}
  - component: api
    name: deploy
    behavior:
      - {call: deployer.provision, input: {vm: "= input.vm"}, as: r, on_error: continue}
      - {return: "= vars.r.ok ? vars.r.value.outcome : vars.r.error.code"}
flows:
  - {id: deploy, entry: {caller: client, interface: api.deploy}}
scenarios:
  - {id: a-healthy, flow: deploy, input: {vm: a}, expect: ["result.value == 'healthy'"]}
  - {id: b-healthy, flow: deploy, input: {vm: b}, expect: ["result.value == 'healthy'"]}
  - {id: c-healthy, flow: deploy, input: {vm: c}, expect: ["result.value == 'healthy'"]}
  - {id: degraded, flow: deploy, input: {vm: slow}, expect: ["result.value == 'degraded'"]}
  - {id: stuck, flow: deploy, input: {vm: stuck}, expect: ["result.value == 'deploy_timeout'"]}
`

const vmChild = `schema_version: 1
id: vm-provisioning
level: logic
refines: {ontology: relay, component: deployer}
components:
  - {id: workflow}
  - {id: cloud}
interfaces:
  - component: workflow
    name: run
    implements: deployer.provision
    latency_ms: 0
    errors: [{code: deploy_timeout, status: 504}]
    behavior:
      - {call: cloud.create, input: {vm: "= input.vm"}, as: c}
      - if: "input.vm == 'stuck'"
        then: [{wait: 2700000}, {fail: {code: deploy_timeout, status: 504}}]
      - if: "input.vm == 'slow'"
        then: [{wait: 9000}, {return: {outcome: degraded}}]
      - {wait: "= input.vm == 'a' ? 2000 : (input.vm == 'b' ? 3000 : 7000)"}
      - {return: {outcome: healthy}}
  - {component: cloud, name: create, latency_ms: 1000}
`

func TestRefinementTimingByOutcome(t *testing.T) {
	dir := t.TempDir()
	cf := filepath.Join(dir, "child.yaml")
	if err := os.WriteFile(cf, []byte(vmChild), 0o644); err != nil {
		t.Fatal(err)
	}
	p, err := model.ParseDocument([]byte(vmParent))
	if err != nil {
		t.Fatal(err)
	}
	tf := filepath.Join(dir, "timing.json")
	var b bytes.Buffer
	if _, err := runRefinements(&b, p, []string{cf}, refinementOpts{Max: -1, ApplyTiming: tf}); err != nil {
		t.Fatal(err)
	}
	out := b.String()
	if !strings.Contains(out, "5 scenarios, 5 equal, 0 differ") {
		t.Errorf("report:\n%s", out)
	}
	// Per-class medians next to the parent's latency: ok samples are 3000,
	// 4000, 8000 (healthy) and 10000 (degraded).
	want := "timing by outcome deployer.provision: parent 500 ms; child median ok 6000 ms (n=4), " +
		"error deploy_timeout 2701000 ms (n=1), outcome=degraded 10000 ms (n=1), outcome=healthy 4000 ms (n=3)"
	if !strings.Contains(out, want) {
		t.Errorf("output lacks\n  %s\n%s", want, out)
	}

	raw, err := os.ReadFile(tf)
	if err != nil {
		t.Fatal(err)
	}
	var rep struct {
		Refinements []struct {
			Interfaces []struct {
				Interface        string                 `json:"interface"`
				Outcomes         []outcomeClass         `json:"outcomes"`
				LatencyByOutcome []model.OutcomeLatency `json:"latency_by_outcome"`
				LatencySource    *model.LatencySource   `json:"latency_source"`
				Applies          bool                   `json:"applies"`
			} `json:"interfaces"`
		} `json:"refinements"`
	}
	if err := json.Unmarshal(raw, &rep); err != nil {
		t.Fatal(err)
	}
	e := rep.Refinements[0].Interfaces[0]
	if !e.Applies || e.LatencySource == nil || e.LatencySource.Refined != "vm-provisioning@local" {
		t.Errorf("entry:\n%s", raw)
	}
	type cls struct {
		Class         string
		N             int
		Min, Med, Max float64
	}
	var got []cls
	for _, c := range e.Outcomes {
		got = append(got, cls{c.Class, c.Count, c.MinMS, c.MedianMS, c.MaxMS})
	}
	wantCls := []cls{
		{"ok", 4, 3000, 6000, 10000},
		{"error deploy_timeout", 1, 2701000, 2701000, 2701000},
		{"outcome=degraded", 1, 10000, 10000, 10000},
		{"outcome=healthy", 3, 3000, 4000, 8000},
	}
	if len(got) != len(wantCls) {
		t.Fatalf("classes: %+v", got)
	}
	for i := range got {
		if got[i] != wantCls[i] {
			t.Errorf("class %d: got %+v, want %+v", i, got[i], wantCls[i])
		}
	}
	// The proposal: most specific first, the median per class.
	var order []string
	var ms []float64
	for _, o := range e.LatencyByOutcome {
		order = append(order, o.When)
		ms = append(ms, o.MS.Min)
	}
	if len(ms) != 4 || ms[0] != 10000 || ms[1] != 4000 || ms[2] != 2701000 || ms[3] != 6000 || order[3] != "result.ok" ||
		!strings.Contains(order[2], "deploy_timeout") {
		t.Fatalf("proposal: %v %v", order, ms)
	}

	// Applied to the black box, the proposal reproduces each outcome's
	// child timing: its when expressions read results the way the
	// simulator evaluates them.
	for i := range p.Interfaces {
		if p.Interfaces[i].ID == "deployer.provision" || p.Interfaces[i].Name == "provision" {
			p.Interfaces[i].LatencyByOutcome = e.LatencyByOutcome
		}
	}
	if errs := model.Validate(p); len(errorsOnly(errs)) > 0 {
		t.Fatalf("applied proposal doesn't validate: %v", errorsOnly(errs))
	}
	c, err := loadRefinement(cf)
	if err != nil {
		t.Fatal(err)
	}
	r, err := checkRefinement(p, c, refinementOpts{})
	if err != nil {
		t.Fatal(err)
	}
	for _, s := range r.Scenarios {
		switch s.ID {
		case "stuck", "degraded":
			if s.ParentMS != s.ChildMS {
				t.Errorf("%s: parent %d ms, child %d ms after applying", s.ID, s.ParentMS, s.ChildMS)
			}
		default: // healthy: the class median
			if s.ParentMS != 4000 {
				t.Errorf("%s: parent %d ms after applying, want 4000", s.ID, s.ParentMS)
			}
		}
	}
}

func errorsOnly(is []model.Issue) []model.Issue {
	var out []model.Issue
	for _, i := range is {
		if i.Severity == model.SeverityError {
			out = append(out, i)
		}
	}
	return out
}

func TestOutcomeClassesWithoutVariety(t *testing.T) {
	cs := outcomeClasses([]timingSample{{MS: 5, OK: true}, {MS: 7, OK: true}})
	if len(cs) != 1 || cs[0].Class != "ok" || cs[0].MedianMS != 6 {
		t.Errorf("classes: %+v", cs)
	}
	if p := proposeByOutcome(cs); p != nil {
		t.Errorf("one class proposes %v", p)
	}
	// A discriminator every ok sample shares adds nothing to ok.
	cs = outcomeClasses([]timingSample{{MS: 5, OK: true, Field: "outcome", Value: "settled"}, {MS: 7, OK: true, Field: "outcome", Value: "settled"}})
	if len(cs) != 2 {
		t.Errorf("classes: %+v", cs)
	}
	if p := proposeByOutcome(cs); p != nil {
		t.Errorf("a shared discriminator proposes %v", p)
	}
}

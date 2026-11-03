package main

import (
	"bytes"
	"regexp"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

const stepsDoc = `schema_version: 1
id: st
components:
  - {id: client}
  - {id: svc}
interfaces:
  - {component: svc, name: get, latency_ms: 3, behavior: [{return: {n: 1, s: "é"}}]}
  - {component: svc, name: big, behavior: [{return: "= input.s"}]}
  - {component: svc, name: bad, behavior: [{fail: {code: nope, message: no}}]}
flows:
  - {id: get, entry: {caller: client, interface: svc.get}}
scenarios:
  - id: multi
    steps:
      - {flow: get, as: g}
      - {interface: svc.bad, caller: client}
      - {interface: svc.big, caller: client, as: big, input: {s: "` + "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" + `"}}
  - id: single
    flow: get
`

// TestStepsFlag: --steps prints each step's as, target, status and result
// (DESIGN §17 item 15), truncated unless --steps-full.
func TestStepsFlag(t *testing.T) {
	doc, err := model.ParseDocument([]byte(stepsDoc))
	if err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	runAll(&b, doc, nil, runOpts{Only: regexp.MustCompile("^multi$"), Quiet: true, Steps: true})
	out := b.String()
	for _, want := range []string{
		"    steps: 3\n",
		"      [0] g: flow get status=ok t=0+3ms value {\"n\":1,\"s\":\"é\"}\n",
		"      [1] -: svc.bad status=error t=3+1ms error {\"code\":\"nope\"",
		"      [2] big: svc.big status=ok t=4+1ms value \"xxxx",
		"… (222 bytes; --steps-full)\n",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("output lacks %q:\n%s", want, out)
		}
	}
	b.Reset()
	runAll(&b, doc, nil, runOpts{Only: regexp.MustCompile("^multi$"), Quiet: true, Steps: true, StepsFull: true})
	if strings.Contains(b.String(), "--steps-full") || !strings.Contains(b.String(), strings.Repeat("x", 220)+"\"\n") {
		t.Errorf("--steps-full truncated:\n%s", b.String())
	}
	b.Reset()
	runAll(&b, doc, nil, runOpts{Only: regexp.MustCompile("^single$"), Quiet: true, Steps: true})
	if want := "    result: status=ok value {\"n\":1,\"s\":\"é\"}\n"; !strings.Contains(b.String(), want) {
		t.Errorf("output lacks %q:\n%s", want, b.String())
	}
	b.Reset()
	runAll(&b, doc, nil, runOpts{Only: regexp.MustCompile("^multi$"), Quiet: true})
	if strings.Contains(b.String(), "steps:") {
		t.Errorf("steps printed without --steps:\n%s", b.String())
	}
}

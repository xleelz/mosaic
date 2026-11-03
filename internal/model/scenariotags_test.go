package model_test

import (
	"regexp"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

// DESIGN §17 item 1: scenario tags.
func TestScenarioTags(t *testing.T) {
	src := `schema_version: 1
components: [{id: a}]
interfaces: [{component: a, name: f}]
flows: [{id: f, entry: {caller: a, interface: a.f}}]
scenarios:
  - {id: plain, flow: f}
  - {id: writer, flow: f, tags: [race, gpu]}
  - {id: bad, flow: f, tags: ["", "two words", "a,b", race, race]}
`
	doc, err := model.ParseDocument([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, is := range model.Validate(doc) {
		got = append(got, string(is.Severity)+" "+is.Path+": "+is.Message)
	}
	all := strings.Join(got, "\n")
	for _, want := range []string{
		"scenarios[bad].tags[0]: a tag needs a name",
		`scenarios[bad].tags[1]: tag "two words" has a space or a comma`,
		`scenarios[bad].tags[2]: tag "a,b" has a space or a comma`,
		`scenarios[bad].tags[4]: duplicate tag "race"`,
	} {
		if !strings.Contains(all, want) {
			t.Errorf("missing issue %q in:\n%s", want, all)
		}
	}
	if strings.Contains(all, "scenarios[writer]") || strings.Contains(all, "scenarios[plain]") {
		t.Errorf("unexpected issues:\n%s", all)
	}
	re := regexp.MustCompile("race|concurr")
	if !doc.Scenarios[1].MatchesIDOrTag(re) || doc.Scenarios[0].MatchesIDOrTag(re) {
		t.Errorf("the gate's regex should select by tag")
	}
	if !doc.Scenarios[1].HasTag("gpu") || doc.Scenarios[1].HasTag("gp") {
		t.Errorf("HasTag")
	}
}

// DESIGN §17 item 2: validating blocking waits and signals.
func TestBlockingWaitValidation(t *testing.T) {
	src := `schema_version: 1
components: [{id: a}]
interfaces:
  - component: a
    name: f
    behavior:
      - wait: {timeout_ms: 5}
      - wait: {until: "state.", signal: "= 1 +"}
      - wait: {until: "true", on_timeout: later}
      - wait: {until: "true", as: "bad-name", nosuch: 1}
      - wait: {signal: SIGCHLD, on_timeout: [{return: 1}], as: w, timeout_ms: -1}
      - {signal: ""}
      - {signal: "= 'SIG' + 'TERM'"}
`
	doc, err := model.ParseDocument([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, is := range model.Validate(doc) {
		if is.Severity == model.SeverityError {
			got = append(got, is.Path+": "+is.Message)
		}
	}
	all := strings.Join(got, "\n")
	p := "interfaces[a.f].behavior"
	for _, want := range []string{
		p + "[0].wait: a blocking wait needs until, signal or both",
		p + "[1].wait.until: invalid expression",
		p + "[1].wait.signal: invalid expression",
		p + "[2].wait.on_timeout: on_timeout is",
		p + "[3].wait: a blocking wait is {until, signal, signals, timeout_ms, on_timeout, as}",
		p + "[4].wait.timeout_ms: timeout_ms must not be negative",
		p + "[5]",
	} {
		if !strings.Contains(all, want) {
			t.Errorf("missing %q in:\n%s", want, all)
		}
	}
	if strings.Contains(all, p+"[6]") {
		t.Errorf("a signal expression is valid:\n%s", all)
	}
}

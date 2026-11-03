package main

import (
	"bytes"
	"regexp"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/explore"
	"github.com/xleelz/mosaic/internal/model"
)

// DESIGN §17 item 1, §16.1: --scenario-tag, and the gate's --explore
// 'race|concurr' selecting scenarios by tag as well as by id.
func TestScenarioTagSelection(t *testing.T) {
	doc, err := model.ParseDocument([]byte(`schema_version: 1
components: [{id: a, state: {initial: {n: 0}}}]
interfaces: [{component: a, name: f, behavior: [{set: {state.n: "= state.n + 1"}}]}]
flows: [{id: f, entry: {caller: a, interface: a.f}}]
scenarios:
  - {id: plain, flow: f}
  - {id: writers, flow: f, tags: [race]}
  - {id: pool, flow: f, tags: [concurrency, slow]}
  - {id: race-by-id, flow: f}
  - {id: slow-one, flow: f, tags: [slow]}
`))
	if err != nil {
		t.Fatal(err)
	}
	ids, counts := selectByTags(doc, nil, []string{"slow", "race"})
	if strings.Join(ids, ",") != "pool,slow-one,writers" || counts["slow"] != 2 || counts["race"] != 1 {
		t.Errorf("selectByTags: %v %v", ids, counts)
	}
	ids, _ = selectByTags(doc, regexp.MustCompile("^p"), []string{"slow"})
	if strings.Join(ids, ",") != "pool" {
		t.Errorf("--scenario and --scenario-tag intersect: %v", ids)
	}
	*scenarioTag = "slow, race"
	defer func() { *scenarioTag = "" }()
	var out bytes.Buffer
	re := scenarioTagFilter(&out, doc, nil)
	if !re.MatchString("pool") || re.MatchString("plain") || re.MatchString("poo") || !strings.Contains(out.String(), "3 scenarios selected (slow 2, race 1)") {
		t.Errorf("filter %v, output %q", re, out.String())
	}
	*scenarioTag = "nosuch"
	if re := scenarioTagFilter(&out, doc, nil); re.MatchString("plain") || re.MatchString("") {
		t.Errorf("an unused tag selects nothing: %v", re)
	}

	out.Reset()
	exploreAll(&out, doc, regexp.MustCompile("race|concurr"), explore.Options{Schedules: 2}, t.TempDir(), false)
	s := out.String()
	for _, id := range []string{"writers", "pool", "race-by-id"} {
		if !strings.Contains(s, "explore "+id+":") {
			t.Errorf("explore should select %s:\n%s", id, s)
		}
	}
	if strings.Contains(s, "explore plain:") || !strings.Contains(s, "explore: 3 scenarios") {
		t.Errorf("explore selected too much:\n%s", s)
	}
}

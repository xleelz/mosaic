package model

import (
	"fmt"
	"regexp"
	"strings"
)

// Scenario tags (DESIGN §17 item 1) label scenarios: race, concurrency,
// slow and the like. Exploration selects scenarios on them (by id or tag,
// §16.1), and so do check's --scenario-tag, its filters and its reports.

// scenarioTags checks a scenario's tags: non-empty, without spaces or
// commas (a --scenario-tag list separator), and distinct.
func (v *validator) scenarioTags(p string, s *Scenario) {
	seen := map[string]bool{}
	for j, t := range s.Tags {
		tp := fmt.Sprintf("%s.tags[%d]", p, j)
		switch {
		case strings.TrimSpace(t) == "":
			v.errf(tp, "a tag needs a name")
		case strings.ContainsAny(t, " \t\n,"):
			v.errf(tp, "tag %q has a space or a comma", t)
		case seen[t]:
			v.warnf(tp, "duplicate tag %q", t)
		}
		seen[t] = true
	}
}

// HasTag reports whether the scenario carries tag t.
func (s *Scenario) HasTag(t string) bool {
	for _, x := range s.Tags {
		if x == t {
			return true
		}
	}
	return false
}

// MatchesIDOrTag reports whether re matches the scenario's id or one of its
// tags: how exploration selects scenarios (§16.1, §17 item 1).
func (s *Scenario) MatchesIDOrTag(re *regexp.Regexp) bool {
	if re.MatchString(s.ID) {
		return true
	}
	for _, t := range s.Tags {
		if re.MatchString(t) {
			return true
		}
	}
	return false
}

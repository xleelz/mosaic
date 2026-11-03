package main

// Scenario tags (DESIGN §17 item 1):
//
//	--scenario-tag TAG[,TAG...]
//
// runs only the scenarios carrying one of the tags (and matching
// --scenario, when given): the scenario runs, and the failure, contract
// and refinement checks that follow --scenario. --explore selects on tags
// too, matching its regex against a scenario's id or any of its tags, so
// the gate's --explore 'race|concurr' picks up scenarios tagged race or
// concurrency (§16.1). The check prints how many scenarios each tag
// selected.

import (
	"flag"
	"fmt"
	"io"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

var scenarioTag = flag.String("scenario-tag", "", "run only scenarios carrying one of these `TAGS` (comma-separated; DESIGN §17 item 1)")

// scenarioTagFilter narrows only (the --scenario regex, or nil) to the
// scenarios carrying a --scenario-tag tag. It returns only unchanged
// without the flag.
func scenarioTagFilter(w io.Writer, doc *model.Document, only *regexp.Regexp) *regexp.Regexp {
	tags := splitTags(*scenarioTag)
	if len(tags) == 0 {
		return only
	}
	ids, counts := selectByTags(doc, only, tags)
	parts := make([]string, len(tags))
	for i, t := range tags {
		parts[i] = fmt.Sprintf("%s %d", t, counts[t])
	}
	fmt.Fprintf(w, "scenario tags: %d scenarios selected (%s)\n", len(ids), strings.Join(parts, ", "))
	quoted := make([]string, len(ids))
	for i, id := range ids {
		quoted[i] = regexp.QuoteMeta(id)
	}
	if len(quoted) == 0 {
		return regexp.MustCompile(`$.^`) // matches nothing
	}
	return regexp.MustCompile("^(?:" + strings.Join(quoted, "|") + ")$")
}

func splitTags(s string) []string {
	var out []string
	seen := map[string]bool{}
	for _, t := range strings.Split(s, ",") {
		if t = strings.TrimSpace(t); t != "" && !seen[t] {
			seen[t] = true
			out = append(out, t)
		}
	}
	return out
}

// selectByTags returns the ids, in order, of the scenarios matching only
// (nil: all) that carry one of tags, and how many carry each tag.
func selectByTags(doc *model.Document, only *regexp.Regexp, tags []string) ([]string, map[string]int) {
	counts := map[string]int{}
	var ids []string
	for i := range doc.Scenarios {
		sc := &doc.Scenarios[i]
		if only != nil && !only.MatchString(sc.ID) {
			continue
		}
		hit := false
		for _, t := range tags {
			if sc.HasTag(t) {
				counts[t]++
				hit = true
			}
		}
		if hit {
			ids = append(ids, sc.ID)
		}
	}
	sort.Strings(ids)
	return ids, counts
}

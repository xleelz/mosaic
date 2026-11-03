package main

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"github.com/xleelz/mosaic/internal/sim"
)

// printTrace writes a run's trace compactly: one line per event, indented by
// call depth, so a reviewer can follow the path a scenario takes. Events
// inside a parallel step are indented one more level per open parallel, under
// a "branch N" header each time the branch changes. Calls show their instance
// (iface@n2), and mocked calls are marked.
func printTrace(w io.Writer, tr []sim.Event) {
	depth := map[int]int{} // span -> depth
	type par struct {
		branch int // the branch whose header was printed last, -1 for none
	}
	var pars []*par
	for _, e := range tr {
		d := 0
		if e.Parent != 0 {
			d = depth[e.Parent] + 1
		}
		if e.Type == "call.start" {
			depth[e.Span] = d
		} else if dd, ok := depth[e.Span]; ok {
			d = dd
		}
		if e.Type == "parallel.end" && len(pars) > 0 {
			pars = pars[:len(pars)-1]
		}
		extra := len(pars)
		if extra > 0 && e.Branch != nil {
			// Events carry their innermost branch; a nested parallel.start
			// still belongs to the enclosing parallel's branch.
			top := pars[len(pars)-1]
			if *e.Branch != top.branch {
				top.branch = *e.Branch
				fmt.Fprintf(w, "    %7s%s┆ branch %d\n", "", strings.Repeat("  ", d+extra), top.branch)
			}
		}
		ind := strings.Repeat("  ", d+1+extra)
		at := func(iface string) string {
			if e.Instance != "" {
				return iface + "@" + e.Instance
			}
			return iface
		}
		var line string
		switch e.Type {
		case "call.start":
			line = fmt.Sprintf("→ %s", at(e.Interface))
			if e.Attempt > 1 {
				line += fmt.Sprintf(" (attempt %d)", e.Attempt)
			}
			if e.Async {
				line += " (async)"
			}
		case "call.end":
			line = fmt.Sprintf("← %s %dms", at(e.Interface), e.DurationMS)
			if e.Error != nil {
				line += fmt.Sprintf(" error %s", e.Error.Code)
			}
		case "note":
			line = "· " + e.Title
		case "set":
			line = fmt.Sprintf("= %s", e.Path)
			if e.Key != "" {
				line += "[" + e.Key + "]"
			}
			if e.Scope == "state" && e.Component != "" {
				line += " on " + at(e.Component)
			}
		case "choice":
			line = fmt.Sprintf("? %s = %s", e.Key, e.Option)
		case "fault":
			line = fmt.Sprintf("! fault %s on %s", e.Fault, at(e.Interface))
		case "retry":
			line = fmt.Sprintf("↻ retry %s after %dms", e.Interface, e.BackoffMS)
		case "timeout":
			line = fmt.Sprintf("⏱ timeout %s", e.Interface)
		case "deadline":
			line = fmt.Sprintf("⏱ deadline passed, %s refused", at(e.Interface))
		case "emit":
			line = fmt.Sprintf("⇢ emit %s", at(e.Interface))
		case "queue":
			line = fmt.Sprintf("⧗ queue %s waited %dms", at(e.Interface), e.WaitMS)
		case "publish":
			line = fmt.Sprintf("⇉ publish %s", e.Topic)
			if e.Instance != "" {
				line += " on " + e.Instance
			}
		case "parallel.start":
			line = "⫚ parallel"
			if m, ok := e.Output.(map[string]any); ok {
				line += fmt.Sprintf(" %v branches, need %v", m["branches"], m["need"])
			}
			pars = append(pars, &par{branch: -1})
		case "parallel.end":
			line = "⫛ join"
			if m, ok := e.Output.(map[string]any); ok {
				line += fmt.Sprintf(" %v/%v succeeded", m["received"], m["required"])
				if v, ok := m["duration_ms"]; ok {
					line += fmt.Sprintf(" in %vms", v)
				}
			}
			if e.Error != nil {
				line += fmt.Sprintf(" error %s", e.Error.Code)
			}
		case "step.start":
			line = fmt.Sprintf("▶ step %s", e.Key)
			if e.Interface != "" {
				line += " " + at(e.Interface)
			}
		case "step.end":
			line = fmt.Sprintf("■ step %s", e.Key)
			if e.DurationMS > 0 {
				line += fmt.Sprintf(" %dms", e.DurationMS)
			}
			if e.Error != nil {
				line += fmt.Sprintf(" error %s", e.Error.Code)
			}
		case "yield":
			line = "↟ yield"
			if e.Index != nil {
				line += fmt.Sprintf(" #%d", *e.Index)
			}
			line += fmt.Sprintf(" %s", short(e.Output))
		case "put", "receive":
			arrow := "⇥ put"
			if e.Type == "receive" {
				arrow = "⇤ receive"
			}
			line = fmt.Sprintf("%s %s", arrow, e.Key)
			if e.WaitMS > 0 {
				line += fmt.Sprintf(" waited %dms", e.WaitMS)
			}
			if e.Error != nil {
				line += fmt.Sprintf(" error %s", e.Error.Code)
			}
		case "kill":
			line = "✖ kill " + at(e.Component)
			if m, ok := e.Output.(map[string]any); ok {
				line += fmt.Sprintf(" (%v calls failed, %v tasks stopped)", m["failed"], m["stopped"])
			}
		default:
			line = e.Type + " " + e.Message
		}
		if e.Mock {
			line += " (mock)"
		}
		if e.Late {
			line += " (late)"
		}
		fmt.Fprintf(w, "    %5dms%s%s\n", e.T, ind, line)
	}
}

// short renders a value on one line, cut to 60 characters.
func short(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return fmt.Sprint(v)
	}
	if s := string(b); len(s) > 60 {
		return s[:57] + "..."
	}
	return string(b)
}

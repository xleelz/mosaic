package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"strings"

	"github.com/xleelz/mosaic/internal/sim"
	"github.com/xleelz/mosaic/pkg/api"
)

const (
	passMark = "✓"
	failMark = "✗"
)

// compact renders v as one-line JSON without HTML escaping, cut to max runes
// (0 means no limit).
func compact(v any, max int) string {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return fmt.Sprint(v)
	}
	s := strings.TrimSpace(buf.String())
	if r := []rune(s); max > 0 && len(r) > max {
		s = string(r[:max]) + "…"
	}
	return s
}

func describeError(e *sim.Error) string {
	if e == nil {
		return "error"
	}
	s := e.Code
	if s == "" {
		s = "error"
	}
	if e.Status != 0 {
		s += " (status " + strconv.Itoa(e.Status) + ")"
	}
	if e.Message != "" {
		s += ": " + e.Message
	}
	return s
}

// writeSummary prints a run for a reader: its identity, status, outcome,
// counters, assertions, warnings and a compact trace.
func writeSummary(w io.Writer, run *api.SimulationRun) error {
	var b strings.Builder
	s := run.Summary
	id := run.ID
	if id == "" {
		id = "(not saved)"
	}
	fmt.Fprintf(&b, "run: %s\n", id)
	what := "flow " + run.Flow
	if run.Scenario != "" {
		what += ", scenario " + run.Scenario
	}
	if run.Revision != "" {
		what += ", revision " + run.Revision
	}
	what += fmt.Sprintf(", seed %d", s.Seed)
	fmt.Fprintf(&b, "simulated: %s\n", what)
	status := s.Status
	if s.Abort != "" {
		status += ": " + s.Abort
	}
	fmt.Fprintf(&b, "status: %s\n", status)
	switch {
	case s.Result.OK && s.Result.Value != nil:
		fmt.Fprintf(&b, "outcome: ok %s\n", compact(s.Result.Value, 400))
	case s.Result.OK:
		fmt.Fprintf(&b, "outcome: ok\n")
	case s.Status == "aborted" && s.Result.Error == nil:
		fmt.Fprintf(&b, "outcome: none\n")
	default:
		fmt.Fprintf(&b, "outcome: error %s\n", describeError(s.Result.Error))
	}
	fmt.Fprintf(&b, "duration: %d ms\n", s.DurationMS)
	fmt.Fprintf(&b, "retries: %d\n", s.Retries)
	fmt.Fprintf(&b, "faults: %d\n", s.Faults)
	if s.Queued > 0 {
		fmt.Fprintf(&b, "queued: %d\n", s.Queued)
	}
	if s.Mocks > 0 {
		fmt.Fprintf(&b, "mocked calls: %d\n", s.Mocks)
	}
	if len(s.Steps) > 0 {
		fmt.Fprintf(&b, "steps: %d\n", len(s.Steps))
		for i, st := range s.Steps {
			fmt.Fprintf(&b, "  %s\n", stepLine(i, st))
		}
	}
	if len(s.Assertions) == 0 {
		fmt.Fprintf(&b, "assertions: none\n")
	} else {
		passed := 0
		for _, a := range s.Assertions {
			if a.Passed {
				passed++
			}
		}
		fmt.Fprintf(&b, "assertions: %d of %d passed\n", passed, len(s.Assertions))
		writeAssertions(&b, s.Assertions, "  ")
	}
	if len(s.Warnings) == 0 {
		fmt.Fprintf(&b, "warnings: none\n")
	} else {
		fmt.Fprintf(&b, "warnings: %d\n", len(s.Warnings))
		for _, wn := range s.Warnings {
			fmt.Fprintf(&b, "  ! %s\n", wn)
		}
	}
	if len(run.Trace) == 0 {
		fmt.Fprintf(&b, "trace: none\n")
	} else {
		fmt.Fprintf(&b, "trace:\n")
		tw := traceWidth(run.Trace)
		depth := spanDepths(run.Trace)
		for _, ev := range run.Trace {
			line, ok := summaryLine(ev)
			if !ok {
				continue
			}
			fmt.Fprintf(&b, "  t=%-*d %s%s\n", tw, ev.T, strings.Repeat("  ", indent(ev, depth)), line)
		}
	}
	_, err := io.WriteString(w, b.String())
	return err
}

// stepLine describes one step of a multi-step scenario.
func stepLine(i int, st sim.StepResult) string {
	name := st.As
	if name == "" {
		name = strconv.Itoa(i)
	}
	what := st.Interface
	if st.Flow != "" {
		what = "flow " + st.Flow
	}
	if st.On != "" {
		what += " on " + st.On
	}
	out := "ok"
	if !st.Result.OK {
		out = failMark + " " + describeError(st.Result.Error)
	}
	return fmt.Sprintf("[%s] %s at t=%d: %s (%d ms)", name, what, st.StartMS, out, st.DurationMS)
}

func writeAssertions(b *strings.Builder, as []sim.Assertion, pad string) {
	for _, a := range as {
		mark := passMark
		if !a.Passed {
			mark = failMark
		}
		fmt.Fprintf(b, "%s%s %s\n", pad, mark, a.Expr)
		if a.Error != "" {
			fmt.Fprintf(b, "%s    error: %s\n", pad, a.Error)
		}
	}
}

// writeTrace prints every event on its own line.
func writeTrace(w io.Writer, run *api.SimulationRun) error {
	var b strings.Builder
	tw := traceWidth(run.Trace)
	sw := len(strconv.Itoa(len(run.Trace)))
	depth := spanDepths(run.Trace)
	for _, ev := range run.Trace {
		fmt.Fprintf(&b, "#%-*d t=%-*d %s%s\n", sw, ev.Seq, tw, ev.T, strings.Repeat("  ", indent(ev, depth)), traceLine(ev))
	}
	_, err := io.WriteString(w, b.String())
	return err
}

func traceWidth(trace []sim.Event) int {
	var max int64
	for _, ev := range trace {
		if ev.T > max {
			max = ev.T
		}
	}
	return len(strconv.FormatInt(max, 10))
}

// spanDepths gives each call span its depth: the entry call is 0 and a
// call's span is one deeper than its parent's.
func spanDepths(trace []sim.Event) map[int]int {
	depth := map[int]int{}
	for _, ev := range trace {
		if ev.Type != "call.start" || ev.Span == 0 {
			continue
		}
		if _, seen := depth[ev.Span]; seen {
			continue
		}
		d := 0
		if ev.Parent != 0 {
			d = depth[ev.Parent] + 1
		}
		depth[ev.Span] = d
	}
	return depth
}

// indent is the nesting of an event: call boundaries and timeouts sit at
// their call's depth; everything else happens inside its span.
func indent(ev sim.Event, depth map[int]int) int {
	d, ok := depth[ev.Span]
	if !ok {
		return 0
	}
	switch ev.Type {
	case "call.start", "call.end", "timeout":
		return d
	}
	// Retries carry the caller's span, so they sit beside the calls they repeat.
	return d + 1
}

// summaryLine renders the events the summary shows; others are skipped.
func summaryLine(ev sim.Event) (string, bool) {
	switch ev.Type {
	case "call.start", "call.end", "retry", "fault", "timeout", "choice", "emit", "warning",
		"queue", "publish", "parallel.start", "parallel.end", "step.start", "step.end", "deadline":
		return eventLine(ev), true
	case "note":
		if ev.Title == "" {
			return "", false
		}
		return "note: " + ev.Title, true
	}
	return "", false
}

// traceLine renders any event, set and detail-only notes included.
func traceLine(ev sim.Event) string {
	switch ev.Type {
	case "note":
		s := "note:"
		if ev.Title != "" {
			s += " " + ev.Title
		}
		if ev.Detail != "" {
			if ev.Title != "" {
				s += " —"
			}
			s += " " + ev.Detail
		}
		if ev.Source != nil && ev.Source.Path != "" {
			s += " [" + ev.Source.String() + "]"
		}
		return s
	case "set":
		s := "set " + ev.Path + " = " + compact(ev.New, 200)
		if ev.Old != nil {
			s += " (was " + compact(ev.Old, 200) + ")"
		}
		return s
	}
	return eventLine(ev)
}

// onInstance names an interface on an instance (§11.1): "iface@n2", or just
// the interface on the unnamed instance.
func onInstance(iface, instance string) string {
	if instance == "" {
		return iface
	}
	return iface + "@" + instance
}

func eventLine(ev sim.Event) string {
	switch ev.Type {
	case "call.start":
		s := "→ " + onInstance(ev.Interface, ev.Instance)
		if ev.Parent == 0 && ev.From != "" {
			s = ev.From + " → " + onInstance(ev.Interface, ev.Instance)
		}
		var tags []string
		if ev.Mock {
			tags = append(tags, "mock")
		}
		if ev.Attempt > 1 {
			tags = append(tags, "attempt "+strconv.Itoa(ev.Attempt))
		}
		if ev.Async {
			tags = append(tags, "async from "+ev.From)
		}
		if len(tags) > 0 {
			s += " (" + strings.Join(tags, ", ") + ")"
		}
		return s
	case "call.end":
		s := "← " + onInstance(ev.Interface, ev.Instance)
		if ev.OK != nil && *ev.OK {
			s += " ok"
		} else {
			s += " " + failMark + " " + describeError(ev.Error)
		}
		s += fmt.Sprintf(" (%d ms", ev.DurationMS)
		if ev.Late {
			s += ", late"
		}
		return s + ")"
	case "retry":
		s := fmt.Sprintf("retry %s attempt %d", ev.Interface, ev.Attempt)
		if ev.BackoffMS > 0 {
			s += fmt.Sprintf(" after %d ms", ev.BackoffMS)
		}
		if ev.Message != "" {
			s += " on " + ev.Message
		}
		if ev.Title != "" {
			s += ": " + ev.Title
		}
		return s
	case "fault":
		s := "fault " + ev.Fault + " at " + ev.Interface
		if ev.Message != "" {
			s += ": " + ev.Message
		}
		return s
	case "timeout":
		s := fmt.Sprintf("timeout %s after %d ms", ev.Interface, ev.DurationMS)
		if ev.Message != "" {
			s += ": " + ev.Message
		}
		return s
	case "queue":
		return fmt.Sprintf("queue %s waited %d ms", onInstance(ev.Interface, ev.Instance), ev.WaitMS)
	case "publish":
		s := "publish " + ev.Topic
		if ev.Instance != "" {
			s += " on " + ev.Instance
		}
		return s
	case "parallel.start":
		s := "parallel"
		if m, ok := ev.Output.(map[string]any); ok {
			s += fmt.Sprintf(" %v branches, need %v", m["branches"], m["need"])
		}
		return s
	case "parallel.end":
		s := "parallel joined"
		if ev.Error != nil {
			s = "parallel " + failMark + " " + describeError(ev.Error)
		} else if m, ok := ev.Output.(map[string]any); ok {
			s += fmt.Sprintf(": %v of %v succeeded", m["received"], m["required"])
		}
		return s
	case "step.start":
		s := "step " + ev.Key
		if ev.Interface != "" {
			s += ": " + onInstance(ev.Interface, ev.Instance)
		}
		return s
	case "step.end":
		s := "step " + ev.Key + " done"
		if ev.Error != nil {
			s += " " + failMark + " " + describeError(ev.Error)
		}
		return s
	case "deadline":
		s := "deadline passed before " + onInstance(ev.Interface, ev.Instance)
		if ev.Message != "" {
			s += ": " + ev.Message
		}
		return s
	case "choice":
		s := "choice " + ev.Key + " = " + ev.Option
		if ev.Origin != "" {
			s += " (" + ev.Origin + ")"
		}
		return s
	case "emit":
		return "emit " + ev.Interface
	case "warning":
		return "warning: " + ev.Message
	case "note":
		return "note: " + ev.Title
	}
	// Unknown event types still get a line.
	s := ev.Type
	if ev.Interface != "" {
		s += " " + ev.Interface
	}
	if ev.Message != "" {
		s += ": " + ev.Message
	}
	return s
}

// writeTestReport prints ✓/✗ per scenario with failing assertions.
func writeTestReport(w io.Writer, rep *api.TestReport) error {
	var b strings.Builder
	passed := 0
	for _, r := range rep.Results {
		mark := passMark
		if r.Passed {
			passed++
		} else {
			mark = failMark
		}
		line := mark + " " + r.Scenario
		if r.Name != "" {
			line += " — " + r.Name
		}
		var notes []string
		if r.Steps > 0 {
			notes = append(notes, fmt.Sprintf("%d steps", r.Steps))
		}
		if r.Mocks > 0 {
			notes = append(notes, fmt.Sprintf("%d mocks, %d calls mocked", r.Mocks, r.MockedCalls))
		}
		if !r.Passed && r.Status != "" {
			notes = append(notes, "status "+r.Status)
		}
		if len(notes) > 0 {
			line += " (" + strings.Join(notes, "; ") + ")"
		}
		fmt.Fprintln(&b, line)
		if r.Passed {
			continue
		}
		var failing []sim.Assertion
		for _, a := range r.Assertions {
			if !a.Passed {
				failing = append(failing, a)
			}
		}
		writeAssertions(&b, failing, "    ")
		if r.Abort != "" {
			fmt.Fprintf(&b, "    aborted: %s\n", r.Abort)
		}
		if r.Error != "" {
			fmt.Fprintf(&b, "    error: %s\n", r.Error)
		}
		if r.RunID != "" {
			fmt.Fprintf(&b, "    run: %s\n", r.RunID)
		}
	}
	total := rep.Total
	if total == 0 {
		total = len(rep.Results)
	}
	rev := ""
	if rep.Revision != "" {
		rev = ", revision " + rep.Revision
	}
	fmt.Fprintf(&b, "%d of %d scenarios passed%s\n", passed, total, rev)
	_, err := io.WriteString(w, b.String())
	return err
}

// writeVersion prints GET /v1/system/version for people.
func writeVersion(w io.Writer, v *api.SystemVersion) {
	commit := shortSHA(v.Commit)
	if commit == "" {
		commit = "unknown commit"
	}
	if v.Dirty {
		commit += " (built with local changes)"
	}
	fmt.Fprintf(w, "mosaicd %s at %s\n", v.Version, commit)
	if v.SourceDir != "" {
		fmt.Fprintf(w, "source   %s", v.SourceDir)
		if v.Branch != "" {
			fmt.Fprintf(w, " on %s", v.Branch)
			if v.Upstream != "" {
				fmt.Fprintf(w, ", tracking %s", v.Upstream)
			}
		}
		fmt.Fprintln(w)
	}
	u := v.Update
	if u.LatestCommit != "" {
		fmt.Fprintf(w, "upstream %s %s (%d behind, %d ahead)\n", shortSHA(u.LatestCommit), u.LatestSubject, u.Behind, u.Ahead)
	}
	if u.CheckedAt != nil {
		fmt.Fprintf(w, "checked  %s\n", u.CheckedAt.Local().Format("2006-01-02 15:04:05"))
	}
	if u.Available {
		fmt.Fprintf(w, "update   available: %d new commit%s; run mosaic update --yes\n", u.Behind, plural(u.Behind))
	} else {
		fmt.Fprintf(w, "update   not available: %s\n", u.Reason)
	}
}

func shortSHA(sha string) string {
	if len(sha) > 7 {
		return sha[:7]
	}
	return sha
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

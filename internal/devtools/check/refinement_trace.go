package main

// §15.4 additions to the refinement check: expectation flips, and
// --refinement-trace's side-by-side traces.

import (
	"bytes"
	"fmt"
	"io"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// refTrace is one scenario's two runs, for --refinement-trace.
type refTrace struct {
	Scenario          string
	BlackBox, Refined []sim.Event
}

// expectFlips compares the scenario's own expectation outcomes across the
// black-box and refined runs: each expectation that passes in one and fails
// in the other is a difference of kind "expect".
func expectFlips(bb, rf *sim.Result) []refDiff {
	var out []refDiff
	verdict := func(a sim.Assertion) string {
		if a.Passed {
			return "pass"
		}
		if a.Error != "" {
			return "fail (" + clip(a.Error) + ")"
		}
		return "fail"
	}
	refined := map[string][]sim.Assertion{} // by expression, in order
	for _, a := range rf.Summary.Assertions {
		refined[a.Expr] = append(refined[a.Expr], a)
	}
	for _, a := range bb.Summary.Assertions {
		list := refined[a.Expr]
		if len(list) == 0 {
			out = append(out, refDiff{"expect", fmt.Sprintf("expect %s: parent %s, child not evaluated", clip(a.Expr), verdict(a))})
			continue
		}
		b := list[0]
		refined[a.Expr] = list[1:]
		if a.Passed != b.Passed {
			out = append(out, refDiff{"expect", fmt.Sprintf("expect %s: parent %s, child %s", clip(a.Expr), verdict(a), verdict(b))})
		}
	}
	return out
}

// traceMiss says why --refinement-trace's scenario has no traces.
func traceMiss(parent *model.Document, o refinementOpts, owned map[string]bool, comp string) string {
	var sc *model.Scenario
	for i := range parent.Scenarios {
		if parent.Scenarios[i].ID == o.Trace {
			sc = &parent.Scenarios[i]
		}
	}
	switch {
	case sc == nil:
		return fmt.Sprintf("no scenario %q in the parent", o.Trace)
	case o.Only != nil && !o.Only.MatchString(o.Trace):
		return fmt.Sprintf("scenario %q is outside --scenario", o.Trace)
	}
	bb, err := sim.Run(parent, sim.Request{Scenario: o.Trace})
	switch {
	case err != nil:
		return fmt.Sprintf("scenario %q didn't run black box: %v", o.Trace, err)
	case !crosses(bb.Trace, owned):
		return fmt.Sprintf("scenario %q doesn't cross %s", o.Trace, comp)
	}
	return fmt.Sprintf("scenario %q wasn't compared", o.Trace)
}

// printTrace prints --refinement-trace's side-by-side traces.
func (r *refinementResult) printTrace(w io.Writer) {
	switch {
	case r.trace != nil:
		fmt.Fprintf(w, "refinement trace %s: %s black box | %s refined by %s\n", r.trace.Scenario, r.Component, r.Component, r.Child)
		sideBySide(w, traceLines(r.trace.BlackBox), traceLines(r.trace.Refined), traceColumn)
	case r.traceNote != "":
		fmt.Fprintf(w, "refinement trace: %s\n", r.traceNote)
	}
}

// traceColumn is the width of each side, in runes.
const traceColumn = 72

func traceLines(tr []sim.Event) []string {
	var b bytes.Buffer
	printTrace(&b, tr)
	lines := strings.Split(strings.TrimRight(b.String(), "\n"), "\n")
	for i, l := range lines {
		lines[i] = strings.TrimPrefix(l, "    ") // printTrace's margin
	}
	return lines
}

var reMS = regexp.MustCompile(`\d+ms\b`)

// traceKey is a trace line without its timings, so the same step lines up
// across the runs when only its durations differ.
func traceKey(line string) string {
	return strings.TrimSpace(reMS.ReplaceAllString(line, "ms"))
}

// sideBySide prints two line lists in two columns, aligned on their longest
// common subsequence of timing-free lines (diff -y style): "│" joins lines
// both runs have, "<" marks a black-box-only line and ">" a refined-only one.
// The common head and tail are matched first; a middle too long to align is
// zipped line by line, "≠" marking the lines that differ.
func sideBySide(w io.Writer, left, right []string, width int) {
	fmt.Fprintf(w, "  %s │ %s\n", tracePad("black box", width), "refined")
	row := func(l, mark, r string) {
		fmt.Fprintf(w, "  %s %s %s\n", tracePad(l, width), mark, strings.TrimRight(traceCut(r, width), " "))
	}
	n, m := len(left), len(right)
	lk, rk := make([]string, n), make([]string, m)
	for i := range left {
		lk[i] = traceKey(left[i])
	}
	for j := range right {
		rk[j] = traceKey(right[j])
	}
	head := 0
	for head < n && head < m && lk[head] == rk[head] {
		head++
	}
	tail := 0
	for tail < n-head && tail < m-head && lk[n-1-tail] == rk[m-1-tail] {
		tail++
	}
	for k := 0; k < head; k++ {
		row(left[k], "│", right[k])
	}
	alignMiddle(left[head:n-tail], right[head:m-tail], lk[head:n-tail], rk[head:m-tail], row)
	for k := tail; k > 0; k-- {
		row(left[n-k], "│", right[m-k])
	}
}

// maxAlignWork bounds the comparisons aligning a trace middle; beyond it
// the middle is zipped.
const maxAlignWork = 400_000_000

// alignMiddle prints the lines between the common head and tail.
func alignMiddle(left, right, lk, rk []string, row func(l, mark, r string)) {
	n, m := len(left), len(right)
	if n*m > maxAlignWork {
		for i := 0; i < max(n, m); i++ {
			var l, r, kl, kr string
			if i < n {
				l, kl = left[i], lk[i]
			}
			if i < m {
				r, kr = right[i], rk[i]
			}
			mark := "│"
			if kl != kr {
				mark = "≠"
			}
			row(l, mark, r)
		}
		return
	}
	i, j := 0, 0
	for _, op := range hirschberg(lk, rk, nil) {
		switch op {
		case alignBoth:
			row(left[i], "│", right[j])
			i, j = i+1, j+1
		case alignLeft:
			row(left[i], "<", "")
			i++
		case alignRight:
			row("", ">", right[j])
			j++
		}
	}
}

// Alignment steps.
const (
	alignBoth  = iota // a line both sides share
	alignLeft         // a black-box-only line
	alignRight        // a refined-only line
)

// hirschberg appends to ops a longest-common-subsequence alignment of a and
// b, in linear space (Hirschberg's algorithm).
func hirschberg(a, b []string, ops []byte) []byte {
	switch {
	case len(a) == 0:
		for range b {
			ops = append(ops, alignRight)
		}
		return ops
	case len(b) == 0:
		for range a {
			ops = append(ops, alignLeft)
		}
		return ops
	case len(a) == 1:
		for j := range b {
			if b[j] == a[0] {
				for range j {
					ops = append(ops, alignRight)
				}
				ops = append(ops, alignBoth)
				for range b[j+1:] {
					ops = append(ops, alignRight)
				}
				return ops
			}
		}
		ops = append(ops, alignLeft)
		for range b {
			ops = append(ops, alignRight)
		}
		return ops
	}
	mid := len(a) / 2
	fwd := lcsRow(a[:mid], b, false)
	bwd := lcsRow(a[mid:], b, true)
	best, k := int32(-1), 0
	for j := 0; j <= len(b); j++ {
		if v := fwd[j] + bwd[len(b)-j]; v > best {
			best, k = v, j
		}
	}
	ops = hirschberg(a[:mid], b[:k], ops)
	return hirschberg(a[mid:], b[k:], ops)
}

// lcsRow returns, for each j, the LCS length of a and b[:j]; reversed, of
// a and b's last j lines, both read backwards.
func lcsRow(a, b []string, reversed bool) []int32 {
	at := func(s []string, i int) string {
		if reversed {
			return s[len(s)-1-i]
		}
		return s[i]
	}
	prev, cur := make([]int32, len(b)+1), make([]int32, len(b)+1)
	for i := range a {
		x := at(a, i)
		for j := range b {
			if x == at(b, j) {
				cur[j+1] = prev[j] + 1
			} else {
				cur[j+1] = max(prev[j+1], cur[j])
			}
		}
		prev, cur = cur, prev
	}
	return prev
}

// traceCut shortens s to width runes, marking a cut with "…".
func traceCut(s string, width int) string {
	if utf8.RuneCountInString(s) <= width {
		return s
	}
	r := []rune(s)
	return string(r[:width-1]) + "…"
}

// tracePad cuts s to width runes and pads it with spaces.
func tracePad(s string, width int) string {
	s = traceCut(s, width)
	return s + strings.Repeat(" ", width-utf8.RuneCountInString(s))
}

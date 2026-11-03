package main

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"unicode/utf8"

	"github.com/xleelz/mosaic/internal/sim"
)

// stepsWidth is how many bytes of a result's JSON --steps prints, unless
// --steps-full.
const stepsWidth = 200

// printSteps writes a run's step results (DESIGN §17 item 15, --steps):
// one line per scenario step with its as name (or "-"), its flow or
// interface, its instance, status, start and duration, then its result
// value (or error) as compact JSON with sorted map keys. A scenario
// without steps prints its result. Unless full, the JSON is cut at
// stepsWidth bytes, with the full size noted.
func printSteps(w io.Writer, s *sim.Summary, full bool) {
	if len(s.Steps) == 0 {
		fmt.Fprintf(w, "    result: status=%s %s\n", s.Status, outcomeJSON(s.Result, full))
		return
	}
	fmt.Fprintf(w, "    steps: %d\n", len(s.Steps))
	for i, st := range s.Steps {
		as := st.As
		if as == "" {
			as = "-"
		}
		what := st.Interface
		if st.Flow != "" {
			what = "flow " + st.Flow
		}
		if st.On != "" {
			what += " on " + st.On
		}
		fmt.Fprintf(w, "      [%d] %s: %s status=%s t=%d+%dms %s\n", i, as, what, st.Status, st.StartMS, st.DurationMS, outcomeJSON(st.Result, full))
	}
}

// outcomeJSON renders an outcome as "value <json>" or "error <json>".
func outcomeJSON(o sim.Outcome, full bool) string {
	kind, v := "value", any(o.Value)
	if o.Error != nil {
		kind, v = "error", o.Error
	} else if !o.OK && o.Value == nil {
		return "(no result)"
	}
	b, err := json.Marshal(v)
	if err != nil {
		b = []byte(fmt.Sprintf("%q", err.Error()))
	}
	return kind + " " + truncJSON(string(b), full)
}

// truncJSON cuts s at stepsWidth bytes (on a rune boundary) unless full.
func truncJSON(s string, full bool) string {
	if full || len(s) <= stepsWidth {
		return s
	}
	cut := stepsWidth
	for cut > 0 && !utf8.RuneStart(s[cut]) {
		cut--
	}
	var b strings.Builder
	b.WriteString(s[:cut])
	fmt.Fprintf(&b, "… (%d bytes; --steps-full)", len(s))
	return b.String()
}

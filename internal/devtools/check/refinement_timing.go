package main

// Timing per outcome (DESIGN §14.13 "Timing reports").
//
// Each of the child's boundary calls (the shell's call to an implementing
// interface) is a sample with its outcome. Samples group into classes:
//   - ok: every successful call;
//   - error <code>: each error code;
//   - <field>=<value>: each value of a response discriminator, the first
//     string field among outcome, status and state of a successful call's
//     value. These overlap ok: they are its more specific cases.
//
// Each class records its count and its min, median and max ms. The proposed
// latency_by_outcome lists the median per class, most specific first
// (discriminator values, then error codes, then ok), as entries whose when
// reads result the way the simulator evaluates them.

import (
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// discriminatorFields are the response fields that name an outcome, in the
// order the first present one is taken.
var discriminatorFields = []string{"outcome", "status", "state"}

// timingSample is one boundary call: its duration and outcome.
type timingSample struct {
	MS       float64
	OK       bool
	Code     string // the error code when not ok
	Field    string // the response discriminator's field, when there is one
	Value    string // and its value
	HasError bool   // not ok with an error (a pending call has none)
}

func sampleOf(e sim.Event) timingSample {
	s := timingSample{MS: float64(e.DurationMS)}
	if e.OK != nil && *e.OK {
		s.OK = true
		if m, ok := e.Output.(map[string]any); ok {
			for _, f := range discriminatorFields {
				if v, ok := m[f].(string); ok && v != "" {
					s.Field, s.Value = f, v
					break
				}
			}
		}
		return s
	}
	if e.Error != nil {
		s.HasError, s.Code = true, e.Error.Code
	}
	return s
}

// outcomeClass is one class's measurement in the --apply-timing report.
type outcomeClass struct {
	Class    string  `json:"class"`
	When     string  `json:"when"`
	Count    int     `json:"count"`
	MinMS    float64 `json:"min_ms"`
	MedianMS float64 `json:"median_ms"`
	MaxMS    float64 `json:"max_ms"`
	rank     int     // 0 discriminator, 1 error code, 2 ok
}

func celString(s string) string { return strconv.Quote(s) }

// outcomeClasses groups samples by outcome class, ordered ok, error codes,
// discriminator values (each group by name).
func outcomeClasses(samples []timingSample) []outcomeClass {
	type acc struct {
		c  outcomeClass
		ms []float64
	}
	byKey := map[string]*acc{}
	add := func(key, label, when string, rank int, ms float64) {
		a := byKey[key]
		if a == nil {
			a = &acc{c: outcomeClass{Class: label, When: when, rank: rank}}
			byKey[key] = a
		}
		a.ms = append(a.ms, ms)
	}
	for _, s := range samples {
		switch {
		case s.OK:
			add("2", "ok", "result.ok", 2, s.MS)
			if s.Field != "" {
				when := fmt.Sprintf("result.ok && type(result.value) == map && %s in result.value && result.value.%s == %s",
					celString(s.Field), s.Field, celString(s.Value))
				add("0"+s.Field+"="+s.Value, s.Field+"="+s.Value, when, 0, s.MS)
			}
		case s.HasError && s.Code != "":
			add("1"+s.Code, "error "+s.Code, "!result.ok && result.error.code == "+celString(s.Code), 1, s.MS)
		case s.HasError:
			add("1", "error", "!result.ok && result.error != null", 1, s.MS)
		}
	}
	out := make([]outcomeClass, 0, len(byKey))
	for _, a := range byKey {
		sort.Float64s(a.ms)
		n := len(a.ms)
		a.c.Count, a.c.MinMS, a.c.MaxMS = n, a.ms[0], a.ms[n-1]
		if n%2 == 1 {
			a.c.MedianMS = a.ms[n/2]
		} else {
			a.c.MedianMS = (a.ms[n/2-1] + a.ms[n/2]) / 2
		}
		out = append(out, a.c)
	}
	sort.Slice(out, func(i, j int) bool {
		ri, rj := 2-out[i].rank, 2-out[j].rank // ok first for reading
		if ri != rj {
			return ri < rj
		}
		return out[i].Class < out[j].Class
	})
	return out
}

// proposeByOutcome is the latency_by_outcome the classes suggest: the median
// per class, most specific first. A discriminator value every ok sample has
// says no more than ok, and is left out; one class alone proposes nothing:
// the interface's single latency already says it.
func proposeByOutcome(classes []outcomeClass) []model.OutcomeLatency {
	okN := 0
	for _, c := range classes {
		if c.rank == 2 {
			okN = c.Count
		}
	}
	var cs []outcomeClass
	for _, c := range classes {
		if c.rank == 0 && c.Count == okN {
			continue
		}
		cs = append(cs, c)
	}
	if len(cs) < 2 {
		return nil
	}
	sort.SliceStable(cs, func(i, j int) bool { return cs[i].rank < cs[j].rank })
	out := make([]model.OutcomeLatency, len(cs))
	for i, c := range cs {
		out[i] = model.OutcomeLatency{When: c.When, MS: model.Latency{Min: c.MedianMS, Max: c.MedianMS}}
	}
	return out
}

// fmtLatency renders a latency_ms value for the text report.
func fmtLatency(l *model.Latency) string {
	switch {
	case l == nil:
		return "unset (1 ms)"
	case l.Expr != "":
		return "=" + l.Expr
	case l.Min == l.Max:
		return fmtNum(l.Min) + " ms"
	}
	return fmtNum(l.Min) + "-" + fmtNum(l.Max) + " ms"
}

func fmtNum(v float64) string { return strconv.FormatFloat(v, 'f', -1, 64) }

// printOutcomeTiming prints, per implemented interface the scenarios
// called, the child's median per outcome class next to the parent's
// latency.
func (r *refinementResult) printOutcomeTiming(w io.Writer) {
	for _, p := range r.Pairs {
		s := r.samples[p.Parent]
		if len(s) == 0 {
			continue
		}
		parent := fmtLatency(r.parentLat[p.Parent])
		if n := len(r.parentBy[p.Parent]); n > 0 {
			parent += fmt.Sprintf(" (+%d latency_by_outcome entries)", n)
		}
		var parts []string
		for _, c := range outcomeClasses(s) {
			parts = append(parts, fmt.Sprintf("%s %s ms (n=%d)", c.Class, fmtNum(c.MedianMS), c.Count))
		}
		fmt.Fprintf(w, "  timing by outcome %s: parent %s; child median %s\n", p.Parent, parent, strings.Join(parts, ", "))
	}
}

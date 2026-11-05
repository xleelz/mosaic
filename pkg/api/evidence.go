package api

import (
	"fmt"
	"time"

	"github.com/xleelz/mosaic/internal/model"
)

// Evidence is GET and PUT /v1/ontologies/{id}/evidence: how far to trust a
// model. It is stored per revision and later revisions inherit it, so each
// figure's MeasuredOnRevision can be older than Revision, the one viewed (0
// when that is the draft). The server sets Revision; a PUT's value is ignored.
type Evidence struct {
	Revision int `json:"revision"`
	// BuiltBy is "generated" (agents, from source) or "handwritten".
	BuiltBy    string              `json:"built_by,omitempty"`
	Source     *EvidenceSource     `json:"source,omitempty"`
	Blind      *EvidenceBlind      `json:"blind,omitempty"`
	Mechanisms *EvidenceMechanisms `json:"mechanisms,omitempty"`
}

// EvidenceSource names the code the model was built from.
type EvidenceSource struct {
	Repo   string `json:"repo,omitempty"`
	Commit string `json:"commit,omitempty"`
}

// EvidenceBlind is the last blind measure: fresh agents, on cases and tests
// the builders never saw. A MeasuredOnRevision of 0 in a PUT means the
// revision it is stored on.
type EvidenceBlind struct {
	MeasuredOnRevision   int    `json:"measured_on_revision"`
	MeasuredAt           string `json:"measured_at,omitempty"`
	Benchmark            string `json:"benchmark,omitempty"`
	StepsPassed          int    `json:"steps_passed"`
	StepsTotal           int    `json:"steps_total"`
	CasesPassed          int    `json:"cases_passed"`
	CasesTotal           int    `json:"cases_total"`
	OraclePassed         int    `json:"oracle_passed"`
	OracleTotal          int    `json:"oracle_total"`
	OracleUntranslatable int    `json:"oracle_untranslatable,omitempty"`
}

// EvidenceMechanisms is the mechanism list. A MeasuredOnRevision of 0 in a PUT
// means the revision it is stored on.
type EvidenceMechanisms struct {
	MeasuredOnRevision int                 `json:"measured_on_revision"`
	Items              []EvidenceMechanism `json:"items"`
}

// EvidenceMechanism is one mechanism enumerated from the code. Fidelity is
// modeled, partial, shell or absent. GateStatus is what `check
// --mechanism-e2e` measured: ok, weak, shell, uncovered, missing or skipped.
type EvidenceMechanism struct {
	ID         string   `json:"id"`
	Area       string   `json:"area"`
	Kind       string   `json:"kind"`
	Name       string   `json:"name"`
	Trigger    string   `json:"trigger,omitempty"`
	Observable string   `json:"observable,omitempty"`
	Citations  []string `json:"citations"`
	Interfaces []string `json:"interfaces"`
	Fidelity   string   `json:"fidelity"`
	Note       string   `json:"note,omitempty"`
	GateStatus string   `json:"gate_status,omitempty"`
}

var (
	builtByValues       = map[string]bool{"generated": true, "handwritten": true}
	mechanismFidelities = map[string]bool{"modeled": true, "partial": true, "shell": true, "absent": true}
	mechanismGates      = map[string]bool{"ok": true, "weak": true, "shell": true, "uncovered": true, "missing": true, "skipped": true}
)

// Validate lists what is wrong with evidence stored on revision rev; rev 0
// means not yet stored, and skips the check that a measure isn't from a later
// revision. It doesn't look interfaces up in the model: a list can name one
// that no longer exists, which is what gate status "missing" reports.
func (e *Evidence) Validate(rev int) []model.Issue {
	var out []model.Issue
	add := func(path, format string, a ...any) {
		out = append(out, model.Issue{Path: path, Message: fmt.Sprintf(format, a...), Severity: model.SeverityError})
	}
	measured := func(path string, n int) {
		switch {
		case n < 0:
			add(path, "must not be negative")
		case rev > 0 && n > rev:
			add(path, "%d is later than revision %d, which this is stored on", n, rev)
		}
	}
	if e.BuiltBy == "" && e.Source == nil && e.Blind == nil && e.Mechanisms == nil {
		add("", "evidence is empty: give at least one of built_by, source, blind or mechanisms")
	}
	if e.BuiltBy != "" && !builtByValues[e.BuiltBy] {
		add("built_by", "must be generated or handwritten, got %q", e.BuiltBy)
	}
	if b := e.Blind; b != nil {
		measured("blind.measured_on_revision", b.MeasuredOnRevision)
		if b.MeasuredAt != "" && !validMeasuredAt(b.MeasuredAt) {
			add("blind.measured_at", "must be an RFC 3339 time or a YYYY-MM-DD date, got %q", b.MeasuredAt)
		}
		for _, c := range []struct {
			name          string
			passed, total int
		}{{"steps", b.StepsPassed, b.StepsTotal}, {"cases", b.CasesPassed, b.CasesTotal}, {"oracle", b.OraclePassed, b.OracleTotal}} {
			if c.passed < 0 || c.total < 0 || c.passed > c.total {
				add("blind."+c.name+"_passed", "%d of %d: passed must be between 0 and the total", c.passed, c.total)
			}
		}
		if b.OracleUntranslatable < 0 {
			add("blind.oracle_untranslatable", "must not be negative")
		}
		if b.StepsTotal <= 0 && b.CasesTotal <= 0 && b.OracleTotal <= 0 {
			add("blind", "measures nothing: steps_total, cases_total and oracle_total are all 0")
		}
	}
	if m := e.Mechanisms; m != nil {
		measured("mechanisms.measured_on_revision", m.MeasuredOnRevision)
		if len(m.Items) == 0 {
			add("mechanisms.items", "must not be empty: leave mechanisms out when there is no list")
		}
		seen := make(map[string]bool, len(m.Items))
		for i := range m.Items {
			it, path := &m.Items[i], fmt.Sprintf("mechanisms.items[%d]", i)
			for _, f := range []struct{ name, v string }{{"id", it.ID}, {"area", it.Area}, {"kind", it.Kind}, {"name", it.Name}} {
				if f.v == "" {
					add(path+"."+f.name, "is required")
				}
			}
			if it.ID != "" && seen[it.ID] {
				add(path+".id", "duplicate id %q", it.ID)
			}
			seen[it.ID] = true
			if !mechanismFidelities[it.Fidelity] {
				add(path+".fidelity", "must be modeled, partial, shell or absent, got %q", it.Fidelity)
			}
			if it.Fidelity == "absent" && len(it.Interfaces) > 0 {
				add(path+".interfaces", "an absent mechanism lists no interfaces")
			}
			if it.GateStatus != "" && !mechanismGates[it.GateStatus] {
				add(path+".gate_status", "must be ok, weak, shell, uncovered, missing or skipped, got %q", it.GateStatus)
			}
		}
	}
	return out
}

func validMeasuredAt(s string) bool {
	if _, err := time.Parse(time.RFC3339, s); err == nil {
		return true
	}
	_, err := time.Parse(time.DateOnly, s)
	return err == nil
}

// Normalize fills what a stored document always has: measures default to rev,
// the revision it is stored on, and lists are never null.
func (e *Evidence) Normalize(rev int) {
	e.Revision = rev
	if e.Blind != nil && e.Blind.MeasuredOnRevision == 0 {
		e.Blind.MeasuredOnRevision = rev
	}
	if m := e.Mechanisms; m != nil {
		if m.MeasuredOnRevision == 0 {
			m.MeasuredOnRevision = rev
		}
		for i := range m.Items {
			if m.Items[i].Citations == nil {
				m.Items[i].Citations = []string{}
			}
			if m.Items[i].Interfaces == nil {
				m.Items[i].Interfaces = []string{}
			}
		}
	}
}

// StoredTestReport is GET /v1/ontologies/{id}/test-results: the latest report
// POST /test recorded for a revision, and when it ran.
type StoredTestReport struct {
	TestReport
	RanAt time.Time `json:"ran_at"`
}

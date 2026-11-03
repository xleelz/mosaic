package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"go.yaml.in/yaml/v3"

	"github.com/xleelz/mosaic/internal/model"
)

// Feature lists (DESIGN §13.1 item 19). The profile names the system's
// user-visible features, each with an owning area. The owner models a feature
// as a flow tagged feature:<id> that some run scenario runs, or skips it in
// skips/<area>.features.json (next to the profile) with a valid reason.

type feature struct {
	ID      string   `yaml:"id"`
	Summary string   `yaml:"summary"`
	Sources []string `yaml:"sources"`
	Owner   string   `yaml:"owner"`
}

// featureSkip is one entry of skips/<area>.features.json, or of
// skips/<area>.failures.json, where role names the side of a two-sided
// failure (DESIGN §13.1 item 30).
type featureSkip struct {
	ID        string `json:"id"`
	Reason    string `json:"reason"`
	CoveredBy string `json:"covered_by,omitempty"`
	Role      string `json:"role,omitempty"`
}

// loadFeatures reads the profile's features and every skips/*.features.json
// next to it, keyed by area (the file name before .features.json).
func loadFeatures(profile string) ([]feature, map[string][]featureSkip, error) {
	b, err := os.ReadFile(profile)
	if err != nil {
		return nil, nil, err
	}
	var p struct {
		Features []feature `yaml:"features"`
	}
	if err := yaml.Unmarshal(b, &p); err != nil {
		return nil, nil, fmt.Errorf("%s: %w", profile, err)
	}
	skips := map[string][]featureSkip{}
	files, _ := filepath.Glob(filepath.Join(filepath.Dir(profile), "skips", "*.features.json"))
	for _, f := range files {
		b, err := os.ReadFile(f)
		if err != nil {
			return nil, nil, err
		}
		var s []featureSkip
		if err := json.Unmarshal(b, &s); err != nil {
			return nil, nil, fmt.Errorf("%s: %w", f, err)
		}
		skips[strings.TrimSuffix(filepath.Base(f), ".features.json")] = s
	}
	return p.Features, skips, nil
}

// Reasons a skip can't be accepted (assign_inventory.py applies the same
// rules to inventory skips, DESIGN §13.1 item 15).
var (
	rejectReasons = []string{"not modeled", "not modelled", "out of scope", "too large", "todo"}
	saysCoveredBy = regexp.MustCompile(`(?i)\bcovered by\b`)
)

// skipProblem says why a skip is invalid, or returns "".
func skipProblem(s featureSkip, doc *model.Document) string {
	r := strings.TrimSpace(s.Reason)
	if r == "" {
		return "no reason"
	}
	low := strings.ToLower(r)
	for _, p := range rejectReasons {
		if strings.HasPrefix(low, p) {
			return "rejected reason " + fmt.Sprintf("%q", p)
		}
	}
	if s.CoveredBy != "" {
		if !entityExists(doc, s.CoveredBy) {
			return "covered_by " + s.CoveredBy + " names no entity"
		}
	} else if saysCoveredBy.MatchString(r) {
		return `says "covered by" without covered_by`
	}
	return ""
}

// entityExists resolves "<kind>:<id>", "<kind>/<id>", or a bare interface,
// component or flow id.
func entityExists(doc *model.Document, ref string) bool {
	ids := map[string]bool{}
	add := func(kind, id string) { ids[kind+":"+id] = true }
	for _, x := range doc.Components {
		add(model.KindComponent, x.ID)
	}
	for _, x := range doc.Interfaces {
		add(model.KindInterface, x.ID)
	}
	for _, x := range doc.Flows {
		add(model.KindFlow, x.ID)
	}
	for _, x := range doc.Scenarios {
		add(model.KindScenario, x.ID)
	}
	for _, x := range doc.Links {
		add(model.KindLink, x.ID)
	}
	for _, x := range doc.Schemas {
		add(model.KindSchema, x.ID)
	}
	ref = strings.TrimSpace(ref)
	if ids[ref] {
		return true
	}
	if k, id, ok := strings.Cut(ref, "/"); ok && ids[k+":"+id] {
		return true
	}
	for _, k := range []string{model.KindInterface, model.KindComponent, model.KindFlow} {
		if ids[k+":"+ref] {
			return true
		}
	}
	return false
}

// Feature statuses.
const (
	featCovered = "covered"
	featSkipped = "skipped"
	featMissing = "missing"
	featAbsent  = "absent" // would be missing, but its owner's fragment isn't in this merge
)

type featResult struct {
	feature
	Status string
	Detail string // the flow that covers it, the skip reason, or why it is missing
}

type featReport struct {
	Results []featResult
	// Unknown lists the feature:<id> tags on flows naming no profile feature.
	Unknown []string
	// Ignored lists the skips of features the file's area doesn't own, or of
	// unknown features.
	Ignored []string
}

// featureCoverage scores each feature. ran holds the flows some run scenario
// runs (its flow, or a step's flow). present holds the base names of the -f
// files (nil means every area): a feature that isn't covered or skipped, and
// whose owner has no fragment in this merge, is absent rather than missing,
// so an area-local run doesn't fail on other areas' features.
func featureCoverage(doc *model.Document, feats []feature, skips map[string][]featureSkip, ran, present map[string]bool) *featReport {
	r := &featReport{}
	known := map[string]*feature{}
	for i := range feats {
		known[feats[i].ID] = &feats[i]
	}
	tagged := map[string][]string{} // feature id -> flows tagged with it
	for _, f := range doc.Flows {
		for _, t := range f.Tags {
			id, ok := strings.CutPrefix(t, "feature:")
			if !ok {
				continue
			}
			if known[id] == nil {
				r.Unknown = append(r.Unknown, fmt.Sprintf("flow %s: %s", f.ID, t))
			}
			tagged[id] = append(tagged[id], f.ID)
		}
	}
	skipOf := map[string]featureSkip{}
	skipProb := map[string]string{}
	areas := make([]string, 0, len(skips))
	for a := range skips {
		areas = append(areas, a)
	}
	sort.Strings(areas)
	for _, a := range areas {
		for _, s := range skips[a] {
			f := known[s.ID]
			switch {
			case f == nil:
				r.Ignored = append(r.Ignored, fmt.Sprintf("skips/%s.features.json: %s is not a profile feature", a, s.ID))
			case f.Owner != "" && f.Owner != a:
				r.Ignored = append(r.Ignored, fmt.Sprintf("skips/%s.features.json: %s belongs to %s", a, s.ID, f.Owner))
			default:
				if p := skipProblem(s, doc); p != "" {
					skipProb[s.ID] = p
				} else {
					skipOf[s.ID] = s
				}
			}
		}
	}
	for _, f := range feats {
		res := featResult{feature: f, Status: featMissing}
		var run, idle []string
		for _, fl := range tagged[f.ID] {
			if ran[fl] {
				run = append(run, fl)
			} else {
				idle = append(idle, fl)
			}
		}
		s, skipped := skipOf[f.ID]
		switch {
		case len(run) > 0:
			res.Status, res.Detail = featCovered, "flow "+strings.Join(run, ", ")
		case skipped:
			res.Status, res.Detail = featSkipped, s.Reason
			if s.CoveredBy != "" {
				res.Detail += " (covered by " + s.CoveredBy + ")"
			}
		case len(idle) > 0:
			res.Detail = "no run scenario runs flow " + strings.Join(idle, ", ")
		case skipProb[f.ID] != "":
			res.Detail = "invalid skip: " + skipProb[f.ID]
		default:
			res.Detail = "no flow tagged feature:" + f.ID
		}
		if res.Status == featMissing && present != nil && f.Owner != "" && !present[f.Owner] {
			res.Status = featAbsent
		}
		r.Results = append(r.Results, res)
	}
	sort.Strings(r.Unknown)
	return r
}

// counts returns covered, skipped, missing and absent, over every feature
// or, with one, over the features of one owner.
func (r *featReport) counts(owner ...string) (c, s, m, a int) {
	for _, x := range r.Results {
		if len(owner) > 0 && x.Owner != owner[0] {
			continue
		}
		switch x.Status {
		case featCovered:
			c++
		case featSkipped:
			s++
		case featAbsent:
			a++
		default:
			m++
		}
	}
	return
}

// print writes one line per owning area, every missing feature, and the
// totals; verbose also lists the covered and skipped ones. It reports
// whether any feature is missing.
func (r *featReport) print(w io.Writer, verbose bool) bool {
	owners := map[string]bool{}
	for _, x := range r.Results {
		owners[x.Owner] = true
	}
	names := make([]string, 0, len(owners))
	for o := range owners {
		names = append(names, o)
	}
	sort.Strings(names)
	for _, o := range names {
		c, s, m, a := r.counts(o)
		label := o
		if label == "" {
			label = "(no owner)"
		}
		if a > 0 {
			fmt.Fprintf(w, "  features of %s: %d covered, %d skipped, %d not in this merge\n", label, c, s, a)
			continue
		}
		fmt.Fprintf(w, "  features of %s: %d covered, %d skipped, %d missing\n", label, c, s, m)
	}
	for _, x := range r.Results {
		if x.Status == featMissing {
			fmt.Fprintf(w, "✗ feature %s (%s) missing: %s\n", x.ID, first(x.Owner, "no owner"), x.Detail)
		} else if verbose && x.Status != featAbsent {
			fmt.Fprintf(w, "  feature %s (%s) %s: %s\n", x.ID, first(x.Owner, "no owner"), x.Status, x.Detail)
		}
	}
	for _, u := range r.Unknown {
		fmt.Fprintf(w, "! unknown feature tag on %s\n", u)
	}
	for _, s := range r.Ignored {
		fmt.Fprintf(w, "! feature skip ignored: %s\n", s)
	}
	c, s, m, a := r.counts()
	absent := ""
	if a > 0 {
		absent = fmt.Sprintf(", %d owned by areas not in this merge", a)
	}
	fmt.Fprintf(w, "features: %d of %d covered, %d skipped, %d missing%s\n", c, len(r.Results), s, m, absent)
	return m > 0
}

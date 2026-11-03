package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/impact"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// commitMeta is a history step's commit.json.
type commitMeta struct {
	SHA          string   `json:"sha"`
	Parent       string   `json:"parent,omitempty"`
	Subject      string   `json:"subject,omitempty"`
	Author       string   `json:"author,omitempty"`
	Date         string   `json:"date,omitempty"` // RFC 3339
	URL          string   `json:"url,omitempty"`
	Repo         string   `json:"repo,omitempty"`
	RemovedAreas []string `json:"removed_areas,omitempty"` // areas the commit deletes from the model
	Files        []string `json:"files,omitempty"`         // paths changed relative to the parent
}

// step is one version of the ontology: the base, or the model at a commit.
type step struct {
	Name     string            // "<NN>-<sha12>", or "base"
	Meta     commitMeta        // empty for the base
	Changed  []string          // areas with a new version at this step
	Removed  []string          // areas dropped at this step
	Versions map[string]string // area -> fragment file in effect

	Doc       *model.Document
	Conflicts []string
	Errors    []string
	Warnings  int
	Passed    int
	Failed    int
	Failures  []string
	Ran       bool          // scenarios were run (or reused from an identical step)
	Impact    *model.Impact // against the previous step; nil for the base
}

func (s *step) ok() bool { return len(s.Conflicts) == 0 && len(s.Errors) == 0 && s.Failed == 0 }

// buildOptions say where the fragments are and what to check.
type buildOptions struct {
	Base, History string
	Areas         []string // merge order; the rest follow alphabetically, with skeleton first
	ID            string   // id of every merged document (default: the skeleton's)
	Scenarios     bool     // run every scenario of every step
}

var stepDirRE = regexp.MustCompile(`^([0-9]+)-([0-9a-fA-F]{4,40})$`)

// stepDirs lists the history's step directories in numeric order.
func stepDirs(history string) ([]string, error) {
	ents, err := os.ReadDir(history)
	if err != nil {
		return nil, err
	}
	type d struct {
		n    int
		name string
	}
	var ds []d
	for _, e := range ents {
		if !e.IsDir() {
			continue
		}
		m := stepDirRE.FindStringSubmatch(e.Name())
		if m == nil {
			continue
		}
		n, _ := strconv.Atoi(m[1])
		ds = append(ds, d{n, e.Name()})
	}
	sort.Slice(ds, func(a, b int) bool {
		if ds[a].n != ds[b].n {
			return ds[a].n < ds[b].n
		}
		return ds[a].name < ds[b].name
	})
	var out []string
	for i, x := range ds {
		if i > 0 && ds[i-1].n == x.n {
			return nil, fmt.Errorf("two history steps numbered %d: %s and %s", x.n, ds[i-1].name, x.name)
		}
		out = append(out, x.name)
	}
	return out, nil
}

// fragments maps area names to fragment files in dir: <area>.yaml, .yml or .json.
func fragments(dir string) (map[string]string, error) {
	out := map[string]string{}
	ents, err := os.ReadDir(dir)
	if os.IsNotExist(err) {
		return out, nil
	}
	if err != nil {
		return nil, err
	}
	for _, e := range ents {
		ext := filepath.Ext(e.Name())
		if e.IsDir() || (ext != ".yaml" && ext != ".yml" && ext != ".json") {
			continue
		}
		area := strings.TrimSuffix(e.Name(), ext)
		if prev, dup := out[area]; dup {
			return nil, fmt.Errorf("area %s has two files: %s and %s", area, prev, e.Name())
		}
		out[area] = filepath.Join(dir, e.Name())
	}
	return out, nil
}

// builder assembles steps, parsing each fragment file once.
type builder struct {
	opts   buildOptions
	parsed map[string]*model.Document
}

func (b *builder) load(path string) (*model.Document, error) {
	if d, ok := b.parsed[path]; ok {
		return d, nil
	}
	in, err := merge.Load([]string{path})
	if err != nil {
		return nil, err
	}
	b.parsed[path] = in[0].Doc
	return in[0].Doc, nil
}

// order is the merge order of the areas in versions.
func (b *builder) order(versions map[string]string) []string {
	var out []string
	seen := map[string]bool{}
	add := func(a string) {
		if _, ok := versions[a]; ok && !seen[a] {
			seen[a] = true
			out = append(out, a)
		}
	}
	add("skeleton")
	for _, a := range b.opts.Areas {
		add(a)
	}
	var rest []string
	for a := range versions {
		rest = append(rest, a)
	}
	sort.Strings(rest)
	for _, a := range rest {
		add(a)
	}
	return out
}

// build returns the base step and one step per commit, merged, validated,
// tested when asked, and compared with the step before.
func build(opts buildOptions) (*step, []*step, error) {
	b := &builder{opts: opts, parsed: map[string]*model.Document{}}
	versions, err := fragments(filepath.Join(opts.Base, "fragments"))
	if err != nil {
		return nil, nil, err
	}
	skel := filepath.Join(opts.Base, "skeleton.yaml")
	if _, err := os.Stat(skel); err == nil {
		if _, dup := versions["skeleton"]; dup {
			return nil, nil, fmt.Errorf("both %s and fragments/skeleton exist", skel)
		}
		versions["skeleton"] = skel
	}
	if len(versions) == 0 {
		return nil, nil, fmt.Errorf("%s holds no skeleton.yaml or fragments/*.yaml", opts.Base)
	}
	base := &step{Name: "base", Versions: versions}
	for a := range versions {
		base.Changed = append(base.Changed, a)
	}
	sort.Strings(base.Changed)
	if err := b.assemble(base, nil); err != nil {
		return nil, nil, err
	}
	dirs, err := stepDirs(opts.History)
	if err != nil {
		return nil, nil, err
	}
	var steps []*step
	prev := base
	for _, name := range dirs {
		dir := filepath.Join(opts.History, name)
		s := &step{Name: name, Versions: map[string]string{}}
		data, err := os.ReadFile(filepath.Join(dir, "commit.json"))
		if err != nil {
			return nil, nil, err
		}
		if err := model.Decode(data, &s.Meta); err != nil {
			return nil, nil, fmt.Errorf("%s/commit.json: %w", name, err)
		}
		if m := stepDirRE.FindStringSubmatch(name); !strings.HasPrefix(strings.ToLower(s.Meta.SHA), strings.ToLower(m[2])) {
			return nil, nil, fmt.Errorf("%s/commit.json: sha %q doesn't match the directory name", name, s.Meta.SHA)
		}
		for a, p := range prev.Versions {
			s.Versions[a] = p
		}
		for _, a := range s.Meta.RemovedAreas {
			if _, ok := s.Versions[a]; !ok {
				return nil, nil, fmt.Errorf("%s/commit.json: removed area %q isn't in the model", name, a)
			}
			delete(s.Versions, a)
			s.Removed = append(s.Removed, a)
		}
		frags, err := fragments(filepath.Join(dir, "fragments"))
		if err != nil {
			return nil, nil, err
		}
		for a, p := range frags {
			s.Versions[a] = p
			s.Changed = append(s.Changed, a)
		}
		sort.Strings(s.Changed)
		sort.Strings(s.Removed)
		if err := b.assemble(s, prev); err != nil {
			return nil, nil, err
		}
		steps = append(steps, s)
		prev = s
	}
	return base, steps, nil
}

// assemble merges, validates and tests one step and compares it with prev.
func (b *builder) assemble(s, prev *step) error {
	var inputs []merge.Input
	for _, a := range b.order(s.Versions) {
		d, err := b.load(s.Versions[a])
		if err != nil {
			return err
		}
		inputs = append(inputs, merge.Input{Name: s.Versions[a], Doc: d})
	}
	res, err := merge.Merge(inputs)
	if err != nil {
		return err
	}
	doc := res.Doc
	if b.opts.ID != "" {
		doc.ID = b.opts.ID
	}
	if doc.Source != nil {
		src := *doc.Source // don't write through to the parsed skeleton
		doc.Source = &src
	}
	if s.Meta.SHA != "" {
		if doc.Source == nil {
			doc.Source = &model.DocSource{}
		}
		doc.Source.SHA = s.Meta.SHA
		if s.Meta.Repo != "" {
			doc.Source.Repo = s.Meta.Repo
		}
		doc.Source.URL = s.Meta.URL
	}
	s.Doc = doc
	s.Conflicts = res.Conflicts
	for _, is := range append(res.Issues, model.Validate(doc)...) {
		if is.Severity == model.SeverityError {
			s.Errors = append(s.Errors, is.Path+": "+is.Message)
		} else {
			s.Warnings++
		}
	}
	if prev != nil {
		s.Impact = impact.Compute(prev.Doc, doc)
	}
	switch {
	case !b.opts.Scenarios || len(s.Errors) > 0:
	case prev != nil && prev.Ran && len(s.Changed) == 0 && len(s.Removed) == 0:
		// Same fragments as the step before: the same results.
		s.Ran, s.Passed, s.Failed, s.Failures = true, prev.Passed, prev.Failed, prev.Failures
	default:
		s.Ran = true
		s.Passed, s.Failed, s.Failures = runScenarios(doc)
	}
	return nil
}

// runScenarios runs every scenario, as the check tool does.
func runScenarios(doc *model.Document) (passed, failed int, failures []string) {
	ids := make([]string, 0, len(doc.Scenarios))
	for _, sc := range doc.Scenarios {
		ids = append(ids, sc.ID)
	}
	sort.Strings(ids)
	for _, id := range ids {
		res, err := sim.Run(doc, sim.Request{Scenario: id})
		switch {
		case err != nil:
			failed++
			failures = append(failures, fmt.Sprintf("%s: %v", id, err))
		case !res.Summary.Passed:
			failed++
			failures = append(failures, fmt.Sprintf("%s: status %s %s", id, res.Summary.Status, res.Summary.Abort))
		default:
			passed++
		}
	}
	return passed, failed, failures
}

// ---- output ----

type summaryRow struct {
	Step      string         `json:"step"`
	File      string         `json:"file"`
	Commit    commitMeta     `json:"commit"`
	Changed   []string       `json:"areas_changed"`
	Removed   []string       `json:"areas_removed,omitempty"`
	Counts    map[string]int `json:"counts"`
	Conflicts []string       `json:"conflicts,omitempty"`
	Errors    []string       `json:"errors,omitempty"`
	Warnings  int            `json:"warnings"`
	Scenarios *scenarioSum   `json:"scenarios,omitempty"`
	Impact    *model.Impact  `json:"impact,omitempty"`
}

type scenarioSum struct {
	Passed   int      `json:"passed"`
	Failed   int      `json:"failed"`
	Failures []string `json:"failures,omitempty"`
}

func counts(d *model.Document) map[string]int {
	return map[string]int{model.KindComponent: len(d.Components), model.KindInterface: len(d.Interfaces),
		model.KindLink: len(d.Links), model.KindSchema: len(d.Schemas), model.KindFlow: len(d.Flows), model.KindScenario: len(d.Scenarios)}
}

func row(s *step) summaryRow {
	r := summaryRow{Step: s.Name, File: s.Name + ".json", Commit: s.Meta, Changed: s.Changed, Removed: s.Removed,
		Counts: counts(s.Doc), Conflicts: s.Conflicts, Errors: s.Errors, Warnings: s.Warnings, Impact: s.Impact}
	if r.Changed == nil {
		r.Changed = []string{}
	}
	if s.Ran {
		r.Scenarios = &scenarioSum{s.Passed, s.Failed, s.Failures}
	}
	return r
}

// writeOutputs writes every merged document, summary.json and summary.md,
// and returns the markdown table.
func writeOutputs(out string, base *step, steps []*step) (string, error) {
	if err := os.MkdirAll(out, 0o755); err != nil {
		return "", err
	}
	rows := []summaryRow{}
	for _, s := range append([]*step{base}, steps...) {
		b, err := json.MarshalIndent(s.Doc, "", "  ")
		if err != nil {
			return "", err
		}
		if err := os.WriteFile(filepath.Join(out, s.Name+".json"), append(b, '\n'), 0o644); err != nil {
			return "", err
		}
		rows = append(rows, row(s))
	}
	b, _ := json.MarshalIndent(rows, "", "  ")
	if err := os.WriteFile(filepath.Join(out, "summary.json"), append(b, '\n'), 0o644); err != nil {
		return "", err
	}
	md := table(base, steps)
	return md, os.WriteFile(filepath.Join(out, "summary.md"), []byte(md), 0o644)
}

// table is the markdown summary: one row per step.
func table(base *step, steps []*step) string {
	var b strings.Builder
	b.WriteString("| step | commit | areas changed | components | interfaces | links | schemas | flows | scenarios | checks | impact vs previous |\n")
	b.WriteString("|---|---|---|---|---|---|---|---|---|---|---|\n")
	for _, s := range append([]*step{base}, steps...) {
		c := counts(s.Doc)
		subject := s.Meta.Subject
		if len(subject) > 48 {
			subject = subject[:45] + "..."
		}
		commit := "(base)"
		if s.Meta.SHA != "" {
			commit = short(s.Meta.SHA) + " " + subject
		}
		areas := strings.Join(s.Changed, ", ")
		if len(s.Removed) > 0 {
			areas += " (removed " + strings.Join(s.Removed, ", ") + ")"
		}
		if areas == "" {
			areas = "none"
		}
		fmt.Fprintf(&b, "| %s | %s | %s | %d | %d | %d | %d | %d | %d | %s | %s |\n",
			s.Name, strings.ReplaceAll(commit, "|", "\\|"), areas, c[model.KindComponent], c[model.KindInterface], c[model.KindLink],
			c[model.KindSchema], c[model.KindFlow], c[model.KindScenario], checks(s), impactText(s.Impact))
	}
	return b.String()
}

func checks(s *step) string {
	var parts []string
	if n := len(s.Conflicts); n > 0 {
		parts = append(parts, fmt.Sprintf("%d conflicts", n))
	}
	if n := len(s.Errors); n > 0 {
		parts = append(parts, fmt.Sprintf("%d errors", n))
	}
	if s.Ran {
		parts = append(parts, fmt.Sprintf("%d/%d passed", s.Passed, s.Passed+s.Failed))
	} else if len(s.Errors) == 0 && len(s.Conflicts) == 0 {
		parts = append(parts, "valid")
	}
	return strings.Join(parts, ", ")
}

// impactText is "components +1 ~2, interfaces -1; 3 flows affected".
func impactText(imp *model.Impact) string {
	if imp == nil {
		return "-"
	}
	var parts []string
	for _, k := range []struct {
		name string
		set  model.ImpactSet
	}{{"components", imp.Components}, {"interfaces", imp.Interfaces}, {"links", imp.Links},
		{"schemas", imp.Schemas}, {"flows", imp.Flows}, {"scenarios", imp.Scenarios}} {
		var p []string
		if n := len(k.set.Added); n > 0 {
			p = append(p, fmt.Sprintf("+%d", n))
		}
		if n := len(k.set.Modified); n > 0 {
			p = append(p, fmt.Sprintf("~%d", n))
		}
		if n := len(k.set.Removed); n > 0 {
			p = append(p, fmt.Sprintf("-%d", n))
		}
		if len(p) > 0 {
			parts = append(parts, k.name+" "+strings.Join(p, " "))
		}
	}
	if len(parts) == 0 {
		return "no change"
	}
	s := strings.Join(parts, ", ")
	if n := len(imp.FlowsAffected); n > 0 {
		s += fmt.Sprintf("; %d flows affected", n)
	}
	return s
}

func short(sha string) string {
	if len(sha) > 12 {
		return sha[:12]
	}
	return sha
}

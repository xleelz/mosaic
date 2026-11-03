package main

// --extract-contract COMPONENT (DESIGN §14.3 "Hand-off down"; SMOKE.md item
// 6) writes the compose pipeline's contract input for one component of the
// -f parent (ontology-pipeline.yaml, inputs.contract):
//   - parent: {task, ontology, document};
//   - component, and interfaces: exactly that component's interfaces;
//   - scenarios: the parent scenarios whose black-box run calls one of those
//     interfaces, found by running every scenario as --refinement does
//     (never by reading the scenarios), sorted; --max-scenarios N keeps the
//     first N;
//   - latency_ms: per interface, the durations observed on the calls into it
//     from outside the component, in latency_ms's shape.
// --scope-out FILE writes the pipeline's scope input: {repo, component,
// paths, name}, the paths being the files the component and its interfaces
// cite. Sibling components citing the same files are listed as a hint: the
// child's scope will cover them too.

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

type extractOpts struct {
	Component    string
	Out          string // -o
	ScopeOut     string // --scope-out
	Repo         string // --repo
	ParentTask   string // --parent-task
	ParentDoc    string // --parent-document, else the first -f path
	MaxScenarios int    // --max-scenarios; 0 means all
}

type contractParent struct {
	Task     string `json:"task"`
	Ontology string `json:"ontology"`
	Document string `json:"document"`
}

type contractInput struct {
	Parent     contractParent            `json:"parent"`
	Component  string                    `json:"component"`
	Interfaces []string                  `json:"interfaces"`
	Scenarios  []string                  `json:"scenarios"`
	LatencyMS  map[string]*model.Latency `json:"latency_ms"`
}

type scopeInput struct {
	Repo      string   `json:"repo"`
	Component string   `json:"component"`
	Paths     []string `json:"paths"`
	Name      string   `json:"name"`
}

// componentInterfaces lists a component's interface ids, sorted.
func componentInterfaces(doc *model.Document, comp string) []string {
	var out []string
	for i := range doc.Interfaces {
		f := doc.Interfaces[i]
		f.Normalize()
		if f.Component == comp {
			out = append(out, ifaceIDOf(&f))
		}
	}
	sort.Strings(out)
	return out
}

// citedFiles maps each component to the files it and its interfaces cite.
func citedFiles(doc *model.Document) map[string]map[string]bool {
	owner := map[string]string{}
	for i := range doc.Interfaces {
		f := doc.Interfaces[i]
		f.Normalize()
		owner["interface:"+ifaceIDOf(&f)] = f.Component
	}
	out := map[string]map[string]bool{}
	for _, c := range collectCitations(doc) {
		comp := ""
		switch {
		case strings.HasPrefix(c.Entity, "component:"):
			comp = strings.TrimPrefix(c.Entity, "component:")
		case strings.HasPrefix(c.Entity, "interface:"):
			comp = owner[c.Entity]
		}
		if comp == "" || c.Src.Path == "" {
			continue
		}
		p := filepath.ToSlash(filepath.Clean(model.ParseSource(c.Src.Path).Path))
		if out[comp] == nil {
			out[comp] = map[string]bool{}
		}
		out[comp][p] = true
	}
	return out
}

// extractContract computes the contract input (and scope) for a component.
func extractContract(w io.Writer, doc *model.Document, inputs []string, o extractOpts) error {
	comp := o.Component
	var ids []string
	found := false
	for i := range doc.Components {
		ids = append(ids, doc.Components[i].ID)
		if doc.Components[i].ID == comp {
			found = true
		}
	}
	if !found {
		var near []string
		for _, id := range ids {
			if strings.Contains(id, comp) || strings.Contains(comp, id) {
				near = append(near, id)
			}
		}
		sort.Strings(near)
		msg := fmt.Sprintf("--extract-contract: the parent has no component %q", comp)
		if len(near) > 0 {
			msg += " (did you mean " + strings.Join(near, ", ") + "?)"
		}
		return fmt.Errorf("%s", msg)
	}
	ifaces := componentInterfaces(doc, comp)
	if len(ifaces) == 0 {
		return fmt.Errorf("--extract-contract: the component %q has no interfaces", comp)
	}
	owned := map[string]bool{}
	for _, id := range ifaces {
		owned[id] = true
	}
	outside := func(e sim.Event) (string, bool) { return e.Interface, owned[e.Interface] && !internalTo(e.From, comp) }

	scs := append([]model.Scenario(nil), doc.Scenarios...)
	sort.Slice(scs, func(a, b int) bool { return scs[a].ID < scs[b].ID })
	var crossing []string
	failed := 0
	samples := map[string][]float64{}
	for i := range scs {
		res, err := sim.Run(doc, sim.Request{Scenario: scs[i].ID})
		if err != nil {
			failed++
			continue
		}
		if !crosses(res.Trace, owned) {
			continue
		}
		crossing = append(crossing, scs[i].ID)
		_, per := boundaryTiming(res.Trace, outside)
		for k, v := range per {
			samples[k] = append(samples[k], v...)
		}
	}
	found = len(crossing) > 0
	total := len(crossing)
	if o.MaxScenarios > 0 && len(crossing) > o.MaxScenarios {
		crossing = crossing[:o.MaxScenarios]
	}

	docPath := o.ParentDoc
	if docPath == "" && len(inputs) > 0 {
		docPath = inputs[0]
	}
	if abs, err := filepath.Abs(docPath); err == nil {
		docPath = abs
	}
	c := contractInput{
		Parent:     contractParent{Task: o.ParentTask, Ontology: doc.ID, Document: docPath},
		Component:  comp,
		Interfaces: ifaces,
		Scenarios:  crossing,
		LatencyMS:  map[string]*model.Latency{},
	}
	if c.Scenarios == nil {
		c.Scenarios = []string{}
	}
	var unobserved []string
	for _, id := range ifaces {
		s := samples[id]
		if len(s) == 0 {
			unobserved = append(unobserved, id)
			continue
		}
		lo, hi := s[0], s[0]
		for _, v := range s {
			lo, hi = min(lo, v), max(hi, v)
		}
		c.LatencyMS[id] = &model.Latency{Min: lo, Max: hi}
	}
	if err := writeJSON(o.Out, c); err != nil {
		return err
	}
	kept := ""
	if len(crossing) < total {
		kept = fmt.Sprintf(" (kept %d, --max-scenarios)", len(crossing))
	}
	fmt.Fprintf(w, "contract %s: %d interfaces, %d crossing scenarios%s, latency observed for %d\n",
		comp, len(ifaces), total, kept, len(c.LatencyMS))
	if failed > 0 {
		fmt.Fprintf(w, "  ! %d scenarios didn't run black box (not considered)\n", failed)
	}
	if len(unobserved) > 0 {
		fmt.Fprintf(w, "  ! no scenario calls %s: no latency_ms\n", strings.Join(unobserved, ", "))
	}
	if !found {
		fmt.Fprintf(w, "  ! no scenario's run crosses %s\n", comp)
	}

	files := citedFiles(doc)
	paths := sortedKeys(files[comp])
	// Siblings sharing the cited files: a hint that the scope covers them.
	type share struct {
		comp  string
		files []string
	}
	var shares []share
	for other, fs := range files {
		if other == comp {
			continue
		}
		var common []string
		for _, p := range paths {
			if fs[p] {
				common = append(common, p)
			}
		}
		if len(common) > 0 {
			shares = append(shares, share{other, common})
		}
	}
	sort.Slice(shares, func(a, b int) bool {
		if len(shares[a].files) != len(shares[b].files) {
			return len(shares[a].files) > len(shares[b].files)
		}
		return shares[a].comp < shares[b].comp
	})
	fmt.Fprintf(w, "  scope: %d cited files\n", len(paths))
	for _, s := range shares {
		fmt.Fprintf(w, "  hint: %s also cites %s\n", s.comp, strings.Join(s.files, ", "))
	}
	if o.ScopeOut != "" {
		if len(paths) == 0 {
			return fmt.Errorf("--scope-out: %s and its interfaces cite no files", comp)
		}
		sc := scopeInput{Repo: o.Repo, Component: comp, Paths: paths, Name: doc.ID + "-" + comp}
		if err := writeJSON(o.ScopeOut, sc); err != nil {
			return err
		}
		fmt.Fprintf(w, "scope written to %s\n", o.ScopeOut)
	}
	fmt.Fprintf(w, "contract written to %s\n", o.Out)
	return nil
}

func writeJSON(path string, v any) error {
	b, err := json.MarshalIndent(v, "", " ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0o644)
}

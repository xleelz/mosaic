package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

func cmdEvidencePut(e *env, c *command, args []string) error {
	fs := e.flags(c)
	file := fileFlag(fs, "evidence `FILE`, YAML or JSON (required); - reads stdin")
	rev := fs.String("rev", "", "revision `R`: latest or a number (default: latest)")
	format := formatFlag(fs, "json", "output `FORMAT`: json or text")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if *file == "" {
		return usageErrorf("missing -f FILE")
	}
	if err := checkRev("rev", *rev); err != nil {
		return err
	}
	if err := oneOf("format", *format, "json", "text"); err != nil {
		return err
	}
	raw, err := readInput(*file)
	if err != nil {
		return err
	}
	var in api.Evidence
	if err := model.Decode(raw, &in); err != nil {
		return inputErrorf("%s: %v", *file, err)
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	out, err := cl.PutEvidence(e.ctx, pos[0], *rev, in)
	if err != nil {
		return err
	}
	return writeEvidence(e.stdout, out, *format)
}

func cmdEvidenceGet(e *env, c *command, args []string) error {
	fs := e.flags(c)
	rev := revFlag(fs)
	format := formatFlag(fs, "json", "output `FORMAT`: json or text")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if err := checkRev("rev", *rev); err != nil {
		return err
	}
	if err := oneOf("format", *format, "json", "text"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	out, err := cl.GetEvidence(e.ctx, pos[0], *rev)
	if err != nil {
		return err
	}
	return writeEvidence(e.stdout, out, *format)
}

func writeEvidence(w io.Writer, ev *api.Evidence, format string) error {
	if format == "json" {
		return printJSON(w, ev)
	}
	var b strings.Builder
	if ev.Revision == 0 {
		b.WriteString("evidence for the draft\n")
	} else {
		fmt.Fprintf(&b, "evidence for revision %d\n", ev.Revision)
	}
	if ev.BuiltBy != "" {
		fmt.Fprintf(&b, "built by: %s\n", ev.BuiltBy)
	}
	if ev.Source != nil {
		fmt.Fprintf(&b, "source: %s @ %s\n", ev.Source.Repo, ev.Source.Commit)
	}
	if bl := ev.Blind; bl != nil {
		fmt.Fprintf(&b, "blind: measured on revision %d", bl.MeasuredOnRevision)
		if bl.Benchmark != "" {
			fmt.Fprintf(&b, " by %s", bl.Benchmark)
		}
		if bl.MeasuredAt != "" {
			fmt.Fprintf(&b, " at %s", bl.MeasuredAt)
		}
		fmt.Fprintf(&b, ": steps %d/%d, cases %d/%d, oracle %d/%d", bl.StepsPassed, bl.StepsTotal, bl.CasesPassed, bl.CasesTotal, bl.OraclePassed, bl.OracleTotal)
		if bl.OracleUntranslatable > 0 {
			fmt.Fprintf(&b, " (%d untranslatable)", bl.OracleUntranslatable)
		}
		b.WriteString("\n")
	} else {
		b.WriteString("blind: not benchmarked\n")
	}
	if m := ev.Mechanisms; m != nil {
		n := map[string]int{}
		for _, it := range m.Items {
			n[it.Fidelity]++
		}
		fmt.Fprintf(&b, "mechanisms: measured on revision %d: %d: %d modeled, %d partial, %d shell, %d absent\n",
			m.MeasuredOnRevision, len(m.Items), n["modeled"], n["partial"], n["shell"], n["absent"])
	} else {
		b.WriteString("mechanisms: no list\n")
	}
	_, err := io.WriteString(w, b.String())
	return err
}

func cmdEvidenceBuild(e *env, c *command, args []string) error {
	fs := e.flags(c)
	dir := fs.String("mechanisms", "", "`DIR` of <area>.json mechanism lists (required)")
	gate := fs.String("mechanisms-json", "", "`FILE`: check's gate JSON, gate_status per mechanism id")
	blind := fs.String("blind", "", "`FILE`: the blind measure, YAML or JSON (required)")
	builtBy := fs.String("built-by", "", "`B`: generated or handwritten")
	repo := fs.String("source-repo", "", "`R`: the code's repository")
	commit := fs.String("source-commit", "", "`SHA`: the code's commit")
	out := fs.String("o", "", "write to `FILE` instead of stdout")
	fs.StringVar(out, "output", "", "same as -o")
	if _, err := e.parse(fs, args, 0, 0, ""); err != nil {
		return err
	}
	if *dir == "" {
		return usageErrorf("missing --mechanisms DIR")
	}
	if *blind == "" {
		return usageErrorf("missing --blind FILE")
	}
	items, areas, err := loadMechanismLists(e.stderr, *dir)
	if err != nil {
		return err
	}
	withGate := 0
	if *gate != "" {
		if withGate, err = applyGate(e.stderr, items, *gate); err != nil {
			return err
		}
	}
	raw, err := readInput(*blind)
	if err != nil {
		return err
	}
	ev := api.Evidence{BuiltBy: *builtBy, Blind: &api.EvidenceBlind{}, Mechanisms: &api.EvidenceMechanisms{Items: items}}
	if err := model.Decode(raw, ev.Blind); err != nil {
		return inputErrorf("%s: %v", *blind, err)
	}
	if *repo != "" || *commit != "" {
		ev.Source = &api.EvidenceSource{Repo: *repo, Commit: *commit}
	}
	if issues := ev.Validate(0); len(issues) > 0 {
		return &exitError{code: exitRefused, msg: "the evidence does not validate", issues: issues}
	}
	var buf strings.Builder
	if err := printJSON(&buf, &ev); err != nil {
		return err
	}
	if *out == "" {
		if _, err := io.WriteString(e.stdout, buf.String()); err != nil {
			return err
		}
	} else if err := os.WriteFile(*out, []byte(buf.String()), 0o644); err != nil {
		return inputErrorf("%v", err)
	}
	fmt.Fprintf(e.stderr, "built evidence: %d mechanisms in %d areas, %d with a gate status\n", len(items), areas, withGate)
	return nil
}

// loadMechanismLists reads DIR/*.json in name order, by the rules of check's
// loader: the file name is the area, and the first of a duplicate id is kept.
// It returns the mechanisms, never nil lists, and how many areas held any.
func loadMechanismLists(warn io.Writer, dir string) ([]api.EvidenceMechanism, int, error) {
	if fi, err := os.Stat(dir); err != nil || !fi.IsDir() {
		return nil, 0, inputErrorf("--mechanisms %s is not a directory", dir)
	}
	files, err := filepath.Glob(filepath.Join(dir, "*.json"))
	if err != nil {
		return nil, 0, inputErrorf("%v", err)
	}
	if len(files) == 0 {
		return nil, 0, inputErrorf("--mechanisms %s has no <area>.json lists", dir)
	}
	sort.Strings(files)
	var items []api.EvidenceMechanism
	areas := 0
	seen := map[string]string{}
	for _, f := range files {
		raw, err := readInput(f)
		if err != nil {
			return nil, 0, err
		}
		var list struct {
			Area       string                  `json:"area"`
			Mechanisms []api.EvidenceMechanism `json:"mechanisms"`
		}
		if err := model.Decode(raw, &list); err != nil {
			return nil, 0, inputErrorf("%s: %v", f, err)
		}
		base := filepath.Base(f)
		area := strings.TrimSuffix(base, ".json")
		if list.Area != "" && list.Area != area {
			fmt.Fprintf(warn, "warning: %s says area %q; the file name wins\n", base, list.Area)
		}
		if len(list.Mechanisms) > 0 {
			areas++
		}
		for _, m := range list.Mechanisms {
			if prev, dup := seen[m.ID]; dup {
				fmt.Fprintf(warn, "warning: %s: duplicate id %s, first in %s; the first is kept\n", base, m.ID, prev)
				continue
			}
			seen[m.ID] = base
			m.Area = area
			if m.Citations == nil {
				m.Citations = []string{}
			}
			if m.Interfaces == nil {
				m.Interfaces = []string{}
			}
			items = append(items, m)
		}
	}
	return items, areas, nil
}

// applyGate sets each item's gate_status from check's JSON and returns how many
// it set. An id the lists don't have means the gate ran on other lists.
func applyGate(warn io.Writer, items []api.EvidenceMechanism, file string) (int, error) {
	raw, err := readInput(file)
	if err != nil {
		return 0, err
	}
	statuses, err := parseGate(raw)
	if err != nil {
		return 0, inputErrorf("%s: %v", file, err)
	}
	set, unmeasured := 0, 0
	for i := range items {
		if st, ok := statuses[items[i].ID]; ok {
			delete(statuses, items[i].ID)
			if st == "reached" || st == "absent" {
				unmeasured++ // check's "not measured here": no gate result to show
				continue
			}
			items[i].GateStatus = st
			set++
		}
	}
	if unmeasured > 0 {
		fmt.Fprintf(warn, "warning: %s: %d mechanisms are reached or absent, which the gate didn't measure; they get no gate_status\n", file, unmeasured)
	}
	if len(statuses) > 0 {
		ids := make([]string, 0, len(statuses))
		for id := range statuses {
			ids = append(ids, id)
		}
		sort.Strings(ids)
		return 0, inputErrorf("%s names %d mechanisms the lists don't have, such as %s", file, len(ids), ids[0])
	}
	return set, nil
}

// parseGate reads gate_status per mechanism id. The statuses are a map of id
// to a status or to an object holding gate_status, or a list of objects with id
// and gate_status, either at the top level or under "mechanisms".
func parseGate(raw json.RawMessage) (map[string]string, error) {
	var top any
	if err := json.Unmarshal(raw, &top); err != nil {
		return nil, err
	}
	if m, ok := top.(map[string]any); ok {
		if inner, ok := m["mechanisms"]; ok {
			top = inner
		}
	}
	out := map[string]string{}
	status := func(id string, v any) error {
		if obj, ok := v.(map[string]any); ok {
			v = obj["gate_status"]
		}
		st, ok := v.(string)
		if !ok || st == "" {
			return fmt.Errorf("mechanism %q has no gate_status", id)
		}
		out[id] = st
		return nil
	}
	switch v := top.(type) {
	case map[string]any:
		for id, x := range v {
			if err := status(id, x); err != nil {
				return nil, err
			}
		}
	case []any:
		for i, x := range v {
			obj, _ := x.(map[string]any)
			id, _ := obj["id"].(string)
			if id == "" {
				return nil, fmt.Errorf("entry %d has no id", i)
			}
			if err := status(id, x); err != nil {
				return nil, err
			}
		}
	default:
		return nil, fmt.Errorf("want gate_status per mechanism id")
	}
	return out, nil
}

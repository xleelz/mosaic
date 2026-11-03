package merge

import (
	"fmt"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

func parse(t *testing.T, name, y string) Input {
	t.Helper()
	d, err := model.ParseDocument([]byte("schema_version: 1\n" + y))
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	return Input{name, d}
}

func TestMergeConfigsAndFixtures(t *testing.T) {
	a := parse(t, "a.yaml", `
configs:
  - {id: same, type: integer, value: 5, summary: one wording}
  - {id: clash, type: integer, value: 1}
  - {id: owned-later, type: integer, value: 7, attributes: {boundary: true, owner: b}}
  - {id: owned-here, type: integer, value: 10}
fixtures:
  - {id: world, topology: {node: [n1, n2]}}
  - {id: shared, topology: {node: [n1]}, config: {clash: 1}}
`)
	b := parse(t, "b.yaml", `
configs:
  - {id: same, type: integer, value: 5, summary: other wording}
  - {id: clash, type: integer, value: 2}
  - {id: owned-later, type: integer, value: 8}
  - {id: owned-here, attributes: {boundary: true}}
fixtures:
  - {id: world, topology: {node: [n1, n2, n3]}}
  - {id: shared, topology: {node: [n1]}, config: {clash: 2}, attributes: {boundary: true}}
`)
	res, err := Merge([]Input{a, b})
	if err != nil {
		t.Fatal(err)
	}
	conf := strings.Join(res.Conflicts, "\n")
	if len(res.Conflicts) != 2 ||
		!strings.Contains(conf, `config "clash" is defined differently in a.yaml and b.yaml: value: 1 vs 2`) ||
		!strings.Contains(conf, `fixture "world" is defined differently in a.yaml and b.yaml: topology:`) {
		t.Errorf("conflicts:\n%s", conf)
	}
	// The owner wins over a reference, whichever comes first.
	x := model.NewIndex(res.Doc)
	if v := x.Configs["owned-later"].Value; fmt.Sprint(v) != "8" {
		t.Errorf("owned-later = %v, want the owner's 8", v)
	}
	if x.Configs["owned-here"].Value == nil || res.Origins["config/owned-here"] != "a.yaml" || res.Origins["config/owned-later"] != "b.yaml" {
		t.Errorf("origins %v", res.Origins)
	}
	diffs := strings.Join(res.OwnerDiffs, "\n")
	for _, s := range []string{`config "owned-later": value: 8 vs 7 (b.yaml vs a.yaml)`, `fixture "shared": config: {"clash":1} vs {"clash":2} (a.yaml vs b.yaml)`} {
		if !strings.Contains(diffs, s) {
			t.Errorf("owner diffs lack %q:\n%s", s, diffs)
		}
	}
	// A reference naming only the id isn't a difference; prose never is, and
	// duplicates differing only in prose merge.
	if strings.Contains(diffs, "owned-here") || strings.Contains(diffs, `"same"`) {
		t.Errorf("spurious owner diffs:\n%s", diffs)
	}
	if len(res.Refs) != 3 || res.Refs["fixture/shared"][0] != "b.yaml" {
		t.Errorf("refs %v", res.Refs)
	}
	if res.Stubs != 0 {
		t.Errorf("stubs left %d", res.Stubs)
	}
}

func TestMergeReferencesWithoutOwner(t *testing.T) {
	a := parse(t, "a.yaml", "configs:\n  - {id: c, value: 1, attributes: {boundary: true}}\n")
	b := parse(t, "b.yaml", "configs:\n  - {id: c, value: 2, attributes: {boundary: true}}\n")
	res, err := Merge([]Input{a, b})
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Conflicts) != 0 || len(res.Disagreements) != 1 || res.Stubs != 1 || len(res.StubFiles) != 0 {
		t.Errorf("conflicts %v disagreements %v stubs %d stubfiles %v", res.Conflicts, res.Disagreements, res.Stubs, res.StubFiles)
	}
	if v := res.Doc.Configs[0].Value; v == nil {
		t.Error("the first reference must be kept")
	}
}

// TestMergeKeepsHierarchyMetadata: level, refines and imports (§14.11)
// survive a merge of fragments.
func TestMergeKeepsHierarchyMetadata(t *testing.T) {
	a := parse(t, "a.yaml", `
id: engine-logic
components: [{id: scheduler}]
`)
	b := parse(t, "b.yaml", `
level: service
refines: {ontology: shop, component: engine}
imports: [{ontology: redis, as: cache}]
components: [{id: worker}]
`)
	c := parse(t, "c.yaml", `
level: logic
imports: [{ontology: redis, as: cache}, {ontology: tcp}]
`)
	res, err := Merge([]Input{a, b, c})
	if err != nil {
		t.Fatal(err)
	}
	d := res.Doc
	if d.Level != "service" || d.Refines == nil || d.Refines.Component != "engine" || len(d.Imports) != 2 || d.Imports[1].Ontology != "tcp" {
		t.Errorf("metadata lost: level %q refines %+v imports %+v", d.Level, d.Refines, d.Imports)
	}
}

package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

// stageFixture writes three fragments and their last-good copies: a and b
// each gain a component whose parent is new in the other (a change that
// needs both working copies), and c is unchanged.
func stageFixture(t *testing.T) (dir, a, b, c string) {
	t.Helper()
	root := t.TempDir()
	dir = filepath.Join(root, "stage")
	write := func(p, s string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(s), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	a = filepath.Join(root, "fragments", "a.yaml")
	b = filepath.Join(root, "fragments", "b.yaml")
	c = filepath.Join(root, "fragments", "c.yaml")
	st := merge.Stage{Dir: dir}
	write(st.Path(a), "schema_version: 1\ncomponents:\n  - {id: a}\n")
	write(st.Path(b), "schema_version: 1\ncomponents:\n  - {id: b}\n")
	write(st.Path(c), "schema_version: 1\ncomponents:\n  - {id: c}\n")
	write(a, "schema_version: 1\ncomponents:\n  - {id: a}\n  - {id: a2, parent: b2}\n  - {id: a3}\n")
	write(b, "schema_version: 1\ncomponents:\n  - {id: b}\n  - {id: b2}\n  - {id: b3, parent: a3}\n")
	write(c, "schema_version: 1\ncomponents:\n  - {id: c}\n")
	return dir, a, b, c
}

// stageRun merges and validates a staged load as main does, and returns the
// failures to attribute.
func stageRun(t *testing.T, l *jointLoad) stageFailures {
	t.Helper()
	res, err := merge.Merge(l.Inputs)
	if err != nil {
		t.Fatal(err)
	}
	issues := append(res.Issues, model.ValidateWithImports(res.Doc)...)
	var errs []model.Issue
	for _, is := range issues {
		if is.Severity == model.SeverityError {
			errs = append(errs, is)
		}
	}
	return stageFailures{Conflicts: res.Conflicts, Issues: errs, Origins: res.Origins, Doc: res.Doc}
}

func TestStageListFlag(t *testing.T) {
	var s stageList
	_ = s.Set("x.yaml, y.yaml")
	_ = s.Set("z.yaml")
	if strings.Join(s, "|") != "x.yaml|y.yaml|z.yaml" {
		t.Fatalf("stage list = %q", s)
	}
}

func TestStageSingleDeadlocksJointPasses(t *testing.T) {
	dir, a, b, c := stageFixture(t)
	paths := []string{a, b, c}

	// Staging a alone: b's last-good copy lacks b2.
	l, err := loadJoint(dir, paths, []string{a})
	if err != nil {
		t.Fatal(err)
	}
	if !l.From[0].Staged || !l.From[1].LastGood || !l.From[1].Stale || l.From[2].Stale {
		t.Fatalf("from: %+v", l.From)
	}
	sf := stageRun(t, l)
	if len(sf.Issues) == 0 {
		t.Fatal("staging a alone should fail on b2")
	}
	r := attribute(l, sf)
	if len(r.ByFragment[a]) == 0 || len(r.ByFragment[b]) != 0 {
		t.Fatalf("attribution: %+v", r.ByFragment)
	}
	if len(r.Suggest[b]) == 0 || len(r.Suggest[c]) != 0 {
		t.Fatalf("suggest: %+v", r.Suggest)
	}
	var out bytes.Buffer
	r.print(&out, l)
	for _, want := range []string{
		"✗ stage: " + a + " failed",
		"staged " + a + " (working copy): 1 failing",
		"components[a2].parent",
		"~ suggest staging " + b + " too",
		"~ try: --stage " + a + "," + b,
	} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("report lacks %q:\n%s", want, out.String())
		}
	}

	// The joint stage passes, and --accept records both, not c.
	l, err = loadJoint(dir, paths, []string{a, b})
	if err != nil {
		t.Fatal(err)
	}
	if sf := stageRun(t, l); len(sf.Issues) > 0 || len(sf.Conflicts) > 0 {
		t.Fatalf("joint stage failed: %+v", sf.Issues)
	}
	dsts, err := l.accept()
	if err != nil || len(dsts) != 2 {
		t.Fatalf("accept: %v %v", dsts, err)
	}
	st := merge.Stage{Dir: dir}
	for _, p := range []string{a, b} {
		got, _ := os.ReadFile(st.Path(p))
		want, _ := os.ReadFile(p)
		if !bytes.Equal(got, want) {
			t.Errorf("%s not recorded", p)
		}
	}
}

func TestStageFinishFailedRecordsNothing(t *testing.T) {
	dir, a, b, c := stageFixture(t)
	l, err := loadJoint(dir, []string{a, b, c}, []string{a, b})
	if err != nil {
		t.Fatal(err)
	}
	old, oldAccept := stagedLoad, *acceptFlag
	defer func() { stagedLoad, *acceptFlag = old, oldAccept }()
	stagedLoad, *acceptFlag = l, true
	before, _ := os.ReadFile(merge.Stage{Dir: dir}.Path(a))
	var out bytes.Buffer
	stageFinish(&out, false, stageFailures{})
	after, _ := os.ReadFile(merge.Stage{Dir: dir}.Path(a))
	if !bytes.Equal(before, after) {
		t.Fatal("a failed joint stage recorded a last-good copy")
	}
	if !strings.Contains(out.String(), "no last-good copy changed") || !strings.Contains(out.String(), "gate findings") {
		t.Fatalf("report:\n%s", out.String())
	}
	out.Reset()
	stageFinish(&out, true, stageFailures{})
	if !strings.Contains(out.String(), "recorded as last-good") {
		t.Fatalf("report:\n%s", out.String())
	}
}

func TestStageAttributesStalePeerFailures(t *testing.T) {
	dir, a, b, c := stageFixture(t)
	l, err := loadJoint(dir, []string{a, b, c}, []string{a})
	if err != nil {
		t.Fatal(err)
	}
	// A failing scenario and an issue in b's last-good copy are b's, and b is stale.
	sf := stageFailures{
		Issues:    []model.Issue{{Path: "components[b].summary", Message: "bad", Severity: model.SeverityError}},
		Scenarios: []string{"s1"},
		Origins:   map[string]string{"component/b": b, "scenario/s1": c},
	}
	r := attribute(l, sf)
	var out bytes.Buffer
	r.print(&out, l)
	for _, want := range []string{
		"stale peer " + b + " (last-good copy; its working copy differs): 1 failing",
		"peer " + c + " (last-good copy): 1 failing",
		"✗ scenario s1",
	} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("report lacks %q:\n%s", want, out.String())
		}
	}
	if _, err := loadJoint(dir, []string{a}, []string{b}); err == nil {
		t.Fatal("staging a fragment outside -f should fail")
	}
}

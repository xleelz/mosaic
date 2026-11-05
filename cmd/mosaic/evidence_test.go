package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/pkg/api"
)

const (
	testBlind = `{"benchmark":"round 1","steps_passed":3,"steps_total":10,"cases_passed":1,"cases_total":2,"oracle_passed":4,"oracle_total":8}`
	testAreaA = `{"area":"a","mechanisms":[
		{"id":"a.sweep","kind":"sweep","name":"Sweep","trigger":"tick","observable":"gone","citations":["a.go:1"],"interfaces":["a.run"],"fidelity":"modeled"},
		{"id":"a.cache","kind":"cache","name":"Cache","citations":[],"interfaces":[],"fidelity":"absent"}]}`
	testAreaB = `{"area":"other","mechanisms":[
		{"id":"b.retry","kind":"retry","name":"Retry","interfaces":["b.call"],"fidelity":"partial","note":"no backoff"},
		{"id":"a.sweep","kind":"sweep","name":"Duplicate","citations":[],"interfaces":[],"fidelity":"absent"}]}`
)

func writeFiles(t *testing.T, files map[string]string) string {
	t.Helper()
	dir := t.TempDir()
	for name, content := range files {
		p := filepath.Join(dir, name)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return dir
}

func TestEvidenceBuild(t *testing.T) {
	dir := writeFiles(t, map[string]string{
		"lists/a.json":       testAreaA,
		"lists/b.json":       testAreaB,
		"lists/skips/a.json": `[{"not":"a list"}]`,
		"blind.json":         testBlind,
		"gate.json":          `{"a.sweep":"ok","b.retry":"reached"}`,
	})
	lists, blind := filepath.Join(dir, "lists"), filepath.Join(dir, "blind.json")
	out := filepath.Join(dir, "evidence.json")

	_, errOut := mustCLI(t, nil, 0, "evidence", "build", "--mechanisms", lists, "--mechanisms-json", filepath.Join(dir, "gate.json"),
		"--blind", blind, "--built-by", "generated", "--source-repo", "o/r", "--source-commit", "abc", "-o", out)
	for _, want := range []string{`says area "other"`, "duplicate id a.sweep", "1 mechanisms are reached or absent", "3 mechanisms in 2 areas, 1 with a gate status"} {
		if !strings.Contains(errOut, want) {
			t.Errorf("stderr lacks %q:\n%s", want, errOut)
		}
	}
	b, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	ev := decode[api.Evidence](t, string(b))
	if ev.BuiltBy != "generated" || ev.Source == nil || ev.Source.Commit != "abc" || ev.Blind == nil || ev.Blind.StepsTotal != 10 || ev.Mechanisms == nil {
		t.Fatalf("evidence = %+v", ev)
	}
	items := ev.Mechanisms.Items
	if len(items) != 3 || items[0].ID != "a.sweep" || items[0].Area != "a" || items[0].GateStatus != "ok" || items[0].Name != "Sweep" {
		t.Fatalf("items = %+v", items)
	}
	if r := items[2]; r.ID != "b.retry" || r.Area != "b" || r.GateStatus != "" || r.Citations == nil || r.Note != "no backoff" {
		t.Fatalf("file name is the area, unmeasured has no status, citations aren't null: %+v", r)
	}
	if !strings.Contains(string(b), `"citations": []`) {
		t.Errorf("citations should be written as []:\n%s", b)
	}

	// Stdout without -o; the gate's other shapes.
	for _, gate := range []string{
		`{"mechanisms":[{"id":"a.sweep","gate_status":"weak"}]}`,
		`[{"id":"a.sweep","gate_status":"weak"}]`,
		`{"mechanisms":{"a.sweep":{"gate_status":"weak"}}}`,
	} {
		g := writeFiles(t, map[string]string{"g.json": gate})
		stdout, _ := mustCLI(t, nil, 0, "evidence", "build", "--mechanisms", lists, "--mechanisms-json", filepath.Join(g, "g.json"), "--blind", blind)
		if got := decode[api.Evidence](t, stdout).Mechanisms.Items[0].GateStatus; got != "weak" {
			t.Errorf("gate %s: status %q", gate, got)
		}
	}

	refusals := []struct {
		name string
		code int
		args []string
		want string
	}{
		{"no dir", 2, []string{"--blind", blind}, "missing --mechanisms"},
		{"no blind", 2, []string{"--mechanisms", lists}, "missing --blind"},
		{"not a dir", 2, []string{"--mechanisms", blind, "--blind", blind}, "not a directory"},
		{"empty dir", 2, []string{"--mechanisms", t.TempDir(), "--blind", blind}, "no <area>.json"},
		{"bad built-by", 1, []string{"--mechanisms", lists, "--blind", blind, "--built-by", "magic"}, "built_by"},
	}
	for _, r := range refusals {
		_, errOut := mustCLI(t, nil, r.code, append([]string{"evidence", "build"}, r.args...)...)
		if !strings.Contains(errOut, r.want) {
			t.Errorf("%s: stderr lacks %q:\n%s", r.name, r.want, errOut)
		}
	}

	bad := writeFiles(t, map[string]string{
		"stale.json":      `{"gone.mech":"ok"}`,
		"status.json":     `{"a.sweep":"great"}`,
		"none.json":       `{"a.sweep":{"other":1}}`,
		"fidelity/a.json": `{"mechanisms":[{"id":"x","kind":"loop","name":"X","fidelity":"great"}]}`,
		"typo/a.json":     `{"mechanisms":[{"id":"x","kind":"loop","name":"X","fidelity":"modeled","fidelty":"x"}]}`,
		"blind.json":      `{"steps_passed":5,"steps_total":1}`,
	})
	for _, c := range []struct {
		code int
		args []string
		want string
	}{
		{2, []string{"--mechanisms", lists, "--blind", blind, "--mechanisms-json", filepath.Join(bad, "stale.json")}, "gone.mech"},
		{1, []string{"--mechanisms", lists, "--blind", blind, "--mechanisms-json", filepath.Join(bad, "status.json")}, "gate_status"},
		{2, []string{"--mechanisms", lists, "--blind", blind, "--mechanisms-json", filepath.Join(bad, "none.json")}, "no gate_status"},
		{1, []string{"--mechanisms", filepath.Join(bad, "fidelity"), "--blind", blind}, "fidelity"},
		{2, []string{"--mechanisms", filepath.Join(bad, "typo"), "--blind", blind}, "fidelty"},
		{1, []string{"--mechanisms", lists, "--blind", filepath.Join(bad, "blind.json")}, "steps_passed"},
	} {
		_, errOut := mustCLI(t, nil, c.code, append([]string{"evidence", "build"}, c.args...)...)
		if !strings.Contains(errOut, c.want) {
			t.Errorf("%v: stderr lacks %q:\n%s", c.args, c.want, errOut)
		}
	}
}

func TestEvidencePutGet(t *testing.T) {
	f := newFake(t)
	mustCLI(t, f, 0, "ontology", "create", exampleOnt, "--name", "G")
	mustCLI(t, f, 0, "apply", exampleOnt, "-f", examplePath, "-m", "one")
	dir := writeFiles(t, map[string]string{
		"e.json":    `{"built_by":"generated","blind":` + testBlind + `,"mechanisms":{"items":[{"id":"a.x","area":"a","kind":"loop","name":"X","fidelity":"absent"}]}}`,
		"e.yaml":    "built_by: handwritten\n",
		"typo.json": `{"built_bye":"x"}`,
		"bad.json":  `{"built_by":"magic"}`,
	})

	if _, errOut, code := cli(t, f, "evidence", "get", exampleOnt); code != 1 || !strings.Contains(errOut, "no evidence") {
		t.Fatalf("none stored: exit %d: %s", code, errOut)
	}
	stdout, _ := mustCLI(t, f, 0, "evidence", "put", exampleOnt, "-f", filepath.Join(dir, "e.json"))
	ev := decode[api.Evidence](t, stdout)
	if ev.Revision != 1 || ev.Blind.MeasuredOnRevision != 1 || ev.Mechanisms.MeasuredOnRevision != 1 {
		t.Fatalf("put = %+v", ev)
	}
	if got := f.log[len(f.log)-1]; !strings.HasPrefix(got, "PUT /v1/ontologies/"+exampleOnt+"/evidence") || strings.Contains(got, "rev=") {
		t.Fatalf("put with no --rev sent %s", got)
	}

	stdout, _ = mustCLI(t, f, 0, "evidence", "get", exampleOnt)
	if ev := decode[api.Evidence](t, stdout); ev.Revision != 0 || ev.Blind.MeasuredOnRevision != 1 {
		t.Fatalf("get on the draft = %+v", ev)
	}
	stdout, _ = mustCLI(t, f, 0, "evidence", "get", exampleOnt, "--rev", "1", "--format", "text")
	for _, want := range []string{"evidence for revision 1", "built by: generated", "measured on revision 1 by round 1", "steps 3/10", "1: 0 modeled, 0 partial, 0 shell, 1 absent"} {
		if !strings.Contains(stdout, want) {
			t.Errorf("text lacks %q:\n%s", want, stdout)
		}
	}

	// YAML input, an explicit revision, and text with nothing measured.
	stdout, _ = mustCLI(t, f, 0, "evidence", "put", exampleOnt, "-f", filepath.Join(dir, "e.yaml"), "--rev", "1", "--format", "text")
	for _, want := range []string{"built by: handwritten", "blind: not benchmarked", "mechanisms: no list"} {
		if !strings.Contains(stdout, want) {
			t.Errorf("text lacks %q:\n%s", want, stdout)
		}
	}

	// A file that fails strict decoding never reaches the server; a refusal lists its issues.
	mustCLI(t, f, 2, "evidence", "put", exampleOnt, "-f", filepath.Join(dir, "typo.json"))
	if _, errOut := mustCLI(t, f, 1, "evidence", "put", exampleOnt, "-f", filepath.Join(dir, "bad.json")); !strings.Contains(errOut, "built_by: must be") {
		t.Errorf("issues not listed: %s", errOut)
	}
	mustCLI(t, f, 1, "evidence", "put", exampleOnt, "-f", filepath.Join(dir, "e.json"), "--rev", "draft")
	mustCLI(t, f, 2, "evidence", "put", exampleOnt)
	mustCLI(t, f, 2, "evidence", "put", exampleOnt, "-f", filepath.Join(dir, "e.json"), "--format", "yaml")
	mustCLI(t, f, 2, "evidence", "get", exampleOnt, "--rev", "x")
	mustCLI(t, f, 2, "evidence", "get", exampleOnt, "--format", "yaml")
}

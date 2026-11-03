package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const (
	refineParent = "../../internal/model/testdata/refine/parent.yaml"
	refineChild  = "../../internal/model/testdata/refine/child.yaml"
)

// TestValidateFiles covers mosaic validate -f: no server (an unreachable
// one is set to prove it), merged fragments, conflicts and --refine pairs.
func TestValidateFiles(t *testing.T) {
	dir := t.TempDir()
	write := func(name, body string) string {
		p := filepath.Join(dir, name)
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
		return p
	}
	a := write("a.yaml", "components: [{id: a}, {id: b}]\ninterfaces: [{component: a, name: x, behavior: [{call: b.y}]}]\n")
	b := write("b.yaml", "interfaces: [{component: b, name: y, behavior: [{return: {}}]}]\n")
	conflict := write("c.yaml", "components: [{id: a, description: other}]\n")
	bad := write("bad.yaml", "components: [{id: a}]\ninterfaces: [{component: a, name: x, behavior: [{call: a.x, retry: {max_attempts: 2, jitter: half}}]}]\n")
	wrongImpl := write("wrong.yaml", "id: engine-logic\nrefines: {ontology: shop, component: engine}\ncomponents: [{id: s}]\n"+
		"interfaces: [{component: s, name: go, implements: engine.missing, behavior: [{return: {}}]}]\n")
	off := []string{"--server", "http://127.0.0.1:1"}
	run := func(want int, args ...string) (fileValidation, string) {
		out, errOut := mustCLI(t, nil, want, append(off, args...)...)
		return decode[fileValidation](t, out), errOut
	}

	// Two fragments merge into one valid document; either alone is not.
	v, _ := run(0, "validate", "-f", a, "--file", b)
	if !v.Valid || len(v.Files) != 2 || len(v.Issues) != 0 {
		t.Errorf("merged fragments: %+v", v)
	}
	v, _ = run(1, "validate", "-f", a)
	if v.Valid || len(v.Issues) == 0 {
		t.Errorf("a alone: %+v", v)
	}
	v, errOut := run(1, "validate", "-f", a, "-f", b, "-f", conflict)
	if v.Valid || !strings.Contains(errOut, "conflict: ") {
		t.Errorf("conflict: %+v\n%s", v, errOut)
	}
	_, errOut = run(1, "validate", "-f", bad)
	if !strings.Contains(errOut, "jitter is none, full or equal") {
		t.Errorf("bad jitter: %s", errOut)
	}

	// A refinement pair.
	v, _ = run(0, "validate", "-f", refineParent, "--refine", "engine="+refineChild)
	if !v.Valid || len(v.Refinements) != 1 || !v.Refinements[0].Valid || v.Refinements[0].Component != "engine" {
		t.Errorf("refinement: %+v", v)
	}
	v, errOut = run(1, "validate", "-f", refineParent, "--refine", "gateway="+refineChild)
	if v.Valid || v.Refinements[0].Valid || !strings.Contains(errOut, `the child refines "engine", not "gateway"`) {
		t.Errorf("wrong component: %+v\n%s", v, errOut)
	}
	v, errOut = run(1, "validate", "-f", refineParent, "--refine", "engine="+wrongImpl)
	if v.Valid || !strings.Contains(errOut, wrongImpl+": ") || !strings.Contains(errOut, `unknown parent interface "engine.missing"`) {
		t.Errorf("unknown implements target: %+v\n%s", v, errOut)
	}

	// Usage errors.
	for _, c := range []struct {
		args []string
		want string
	}{
		{[]string{"validate", "o", "-f", a}, "not both"},
		{[]string{"validate", "-f", a, "--rev", "1"}, "--rev needs <ont>"},
		{[]string{"validate", "o", "--refine", "engine=" + refineChild}, "--refine needs -f"},
		{[]string{"validate", "-f", refineParent, "--refine", "engine"}, "COMPONENT=CHILD_FILE"},
		{[]string{"validate"}, "missing <ont>"},
	} {
		_, errOut := mustCLI(t, nil, 2, append(off, c.args...)...)
		if !strings.Contains(errOut, c.want) {
			t.Errorf("%v: %s", c.args, errOut)
		}
	}
}

package merge

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestStageLoadAndAccept(t *testing.T) {
	dir := t.TempDir()
	write := func(p, s string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(s), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	a := filepath.Join(dir, "frag", "a.yaml")
	b := filepath.Join(dir, "frag", "b.yaml")
	write(a, "schema_version: 1\nconfigs:\n  - {id: a, type: integer, value: 1}\n")
	write(b, "schema_version: 1\nconfigs:\n  - {id: b, type: integer, value: 1}\n")
	st := Stage{Dir: filepath.Join(dir, ".mosaic", "stage")}

	// No last-good yet: both working copies.
	l, err := st.LoadStaged([]string{a, b}, a)
	if err != nil {
		t.Fatal(err)
	}
	if l.From[0].LastGood || l.From[1].LastGood || !l.From[0].Staged {
		t.Fatalf("from: %+v", l.From)
	}
	if _, err := st.Accept(l); err != nil {
		t.Fatal(err)
	}
	l, _ = st.LoadStaged([]string{a, b}, b)
	if _, err := st.Accept(l); err != nil {
		t.Fatal(err)
	}

	// b breaks: staging a reads b's last-good copy and still parses.
	write(b, "schema_version: 1\nconfigs: [ {id: b\n")
	l, err = st.LoadStaged([]string{a, b}, a)
	if err != nil {
		t.Fatalf("a blocked by broken b: %v", err)
	}
	if !l.From[1].LastGood || l.Inputs[1].Name != b || len(l.Inputs[1].Doc.Configs) != 1 {
		t.Fatalf("b not from last-good: %+v", l.From)
	}
	// Staging b itself fails on its working copy.
	_, err = st.LoadStaged([]string{a, b}, b)
	var pe *ParseError
	if !errors.As(err, &pe) || pe.Path != b {
		t.Fatalf("staging broken b: %v", err)
	}
	if _, err := st.LoadStaged([]string{a}, b); err == nil {
		t.Fatal("staging a fragment outside -f should fail")
	}
}

func TestStagePath(t *testing.T) {
	st := Stage{Dir: ".mosaic/stage"}
	if got := st.Path("examples/x/fragments/a.yaml"); got != filepath.Join(".mosaic/stage", "examples/x/fragments/a.yaml") {
		t.Fatalf("relative: %s", got)
	}
	if got := st.Path("/nonexistent-root/a.yaml"); got != filepath.Join(".mosaic/stage", "_abs", "nonexistent-root/a.yaml") {
		t.Fatalf("absolute outside wd: %s", got)
	}
}

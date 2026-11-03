package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func lines(prefix string, n int) string {
	var b strings.Builder
	for i := 1; i <= n; i++ {
		fmt.Fprintf(&b, "%s%d\n", prefix, i)
	}
	return b.String()
}

// testRepo makes a repository with two commits and returns it with their shas.
//
//	a.go:   3 lines inserted at the top, line 10 replaced by two lines,
//	        lines 15-16 deleted;
//	b.go:   unchanged;
//	old.go: renamed to new.go with a line inserted at the top;
//	gone.go: deleted.
func testRepo(t *testing.T) (string, string, string) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not installed")
	}
	dir := t.TempDir()
	gitc := func(args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"}, args...)...)
		cmd.Env = append(os.Environ(), "GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_NOSYSTEM=1")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	write := func(name, body string) {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	gitc("init", "-q")
	write("a.go", lines("a", 20))
	write("b.go", lines("b", 10))
	write("old.go", lines("package old // line ", 30))
	write("gone.go", lines("g", 5))
	gitc("add", ".")
	gitc("commit", "-q", "-m", "one")
	from := gitc("rev-parse", "HEAD")

	a := strings.Split(strings.TrimSuffix(lines("a", 20), "\n"), "\n")
	var na []string
	na = append(na, "n1", "n2", "n3")
	for i, l := range a {
		switch i + 1 {
		case 10:
			na = append(na, "X", "Y")
		case 15, 16:
		default:
			na = append(na, l)
		}
	}
	write("a.go", strings.Join(na, "\n")+"\n")
	gitc("mv", "old.go", "new.go")
	write("new.go", "// header\n"+lines("package old // line ", 30))
	gitc("rm", "-q", "gone.go")
	gitc("add", ".")
	gitc("commit", "-q", "-m", "two")
	return dir, from, gitc("rev-parse", "HEAD")
}

func TestReanchorLineMapping(t *testing.T) {
	dir, from, to := testRepo(t)
	ch, err := loadChanges(dir, from, to)
	if err != nil {
		t.Fatal(err)
	}
	cases := []struct{ in, want, status string }{
		{"a.go:5", "a.go:8", "shifted"},
		{"a.go:2-4", "a.go:5-7", "shifted"},
		{"a.go:1", "a.go:4", "shifted"},
		{"a.go:9-11", "a.go:12-15", "edited"},
		{"a.go:10", "a.go:13", "edited"},
		{"a.go:15-16", "a.go:19", "stale"},
		{"a.go:12-20", "a.go:16-22", "edited"},
		{"a.go:17", "a.go:19", "shifted"},
		{"b.go:3", "b.go:3", "unchanged"},
		{"old.go:4-5", "new.go:5-6", "renamed,shifted"},
		{"old.go", "new.go", "renamed"},
		{"gone.go:2", "gone.go:2", "file_deleted"},
		{"a.go:5, b.go:3", "a.go:8, b.go:3", "shifted"},
		{"a.go:5:7", "a.go:5:7", ""}, // line:column is not a citation
	}
	for _, c := range cases {
		var got []string
		out := ch.rewriteText(c.in, func(a anchored) { got = append(got, strings.Join(a.Statuses, ",")) })
		if out != c.want {
			t.Errorf("%s -> %s, want %s", c.in, out, c.want)
		}
		if c.status != "" && (len(got) == 0 || got[0] != c.status) {
			t.Errorf("%s: statuses %v, want %s first", c.in, got, c.status)
		}
	}
}

const yamlDoc = `# A fragment. Comments and layout survive.
schema_version: 1
source: {repo: test, sha: FROM}
components:
  - id: a
    summary: see a.go:5 in the description, which is not a citation
    sources: [a.go:5, "a.go:2-4", old.go]   # inline comment
    attributes: {path: a.go:5}
interfaces:
  - component: a
    name: x
    sources:
      - {path: a.go, line: 5, end_line: 6}
      - {path: a.go, line: 5, sha: deadbeef}
      - gone.go:2
    behavior:
      - call: b.y
        source: 'a.go:15-16'
        input: {source: a.go:5}
`

func TestReanchorYAML(t *testing.T) {
	dir, from, to := testRepo(t)
	path := filepath.Join(t.TempDir(), "doc.yaml")
	os.WriteFile(path, []byte(strings.Replace(yamlDoc, "FROM", from, 1)), 0o644)
	r, out, err := run(dir, from[:10], "HEAD", path)
	if err != nil {
		t.Fatal(err)
	}
	want := strings.Replace(yamlDoc, "FROM", to, 1)
	for _, rep := range [][2]string{
		{`[a.go:5, "a.go:2-4", old.go]`, `[a.go:8, "a.go:5-7", new.go]`},
		{"{path: a.go, line: 5, end_line: 6}", "{path: a.go, line: 8, end_line: 9}"},
		{"source: 'a.go:15-16'", "source: 'a.go:19'"},
	} {
		want = strings.Replace(want, rep[0], rep[1], 1)
	}
	if string(out) != want {
		t.Errorf("got:\n%s\nwant:\n%s", out, want)
	}
	if len(r.problems) > 0 {
		t.Errorf("problems: %v", r.problems)
	}
	c := r.counts()
	if c[stShifted] != 3 || c[stRenamed] != 1 || c[stStale] != 1 || c[stFileDeleted] != 1 || c[stPinned] != 1 {
		t.Errorf("counts %v", c)
	}
}

func TestReanchorJSON(t *testing.T) {
	dir, from, to := testRepo(t)
	path := filepath.Join(t.TempDir(), "doc.json")
	doc := `{"schema_version": 1, "source": {"sha": "` + from + `"},
	  "components": [{"id": "a", "sources": [{"path": "old.go", "line": 4, "end_line": 5}, "a.go:9-11"],
	    "attributes": {"sources": ["a.go:5"]}, "zeta": 1.50}]}`
	os.WriteFile(path, []byte(doc), 0o644)
	_, out, err := run(dir, from, to, path)
	if err != nil {
		t.Fatal(err)
	}
	want := `{
  "schema_version": 1,
  "source": {
    "sha": "` + to + `"
  },
  "components": [
    {
      "id": "a",
      "sources": [
        {
          "path": "new.go",
          "line": 5,
          "end_line": 6
        },
        "a.go:12-15"
      ],
      "attributes": {
        "sources": [
          "a.go:5"
        ]
      },
      "zeta": 1.50
    }
  ]
}
`
	if string(out) != want {
		t.Errorf("got:\n%s\nwant:\n%s", out, want)
	}
	if !json.Valid(out) {
		t.Error("invalid JSON")
	}
}

func TestParseDiff(t *testing.T) {
	ch, err := parseDiff([]byte(`diff --git a/x y.go b/x y.go
index 1..2 100644
--- a/x y.go
+++ b/x y.go
@@ -3 +3,2 @@ func
-old
+new
+new2
@@ -0,0 +1 @@
diff --git a/bin.dat b/bin.dat
deleted file mode 100644
Binary files a/bin.dat and /dev/null differ
`))
	if err != nil {
		t.Fatal(err)
	}
	if fc := ch["x y.go"]; fc == nil || fc.newPath != "x y.go" || len(fc.hunks) != 2 || fc.hunks[0] != (hunk{3, 1, 3, 2}) {
		t.Errorf("x y.go: %+v", ch["x y.go"])
	}
	if fc := ch["bin.dat"]; fc == nil || !fc.deleted {
		t.Errorf("bin.dat: %+v", ch["bin.dat"])
	}
	if _, err := git(".", "checkout", "x"); err == nil {
		t.Error("git checkout should be refused")
	}
}

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

const applyFragment = `# Parent fragment.
schema_version: 1
id: parent
interfaces:
# The workflow's run.
- component: wf
  name: run
  summary: 'runs: until settled'   # trailing comment
  sources:
  - a.go:1
  latency_ms: 5
  behavior:
  - return: {ok: true}

  # Pinned by an operator.
- component: wf
  name: pinned
  latency_source: {pinned: measured in prod}
  behavior:
  - return: {}
- {component: wf, name: flow, summary: "a, b", behavior: [{return: {}}]}
- component: wf
  name: last
  behavior:
  - return: |
      # not a comment
      text
# Trailing comment.
`

func applyProps(ifaces ...string) []timingProposal {
	var out []timingProposal
	for _, id := range ifaces {
		out = append(out, timingProposal{Interface: id, Source: model.LatencySource{Refined: "child@abc123"},
			ByOutcome: []model.OutcomeLatency{
				{When: `result.ok && type(result.value) == map && "outcome" in result.value && result.value.outcome == "settled:failed"`, MS: model.Latency{Min: 2702024, Max: 2702024}},
				{When: "result.ok", MS: model.Latency{Min: 31, Max: 31}},
			}})
	}
	return out
}

func TestApplyTimingKeepsCommentsAndOrder(t *testing.T) {
	out, notes, err := applyTimingYAML([]byte(applyFragment), applyProps("wf.run", "wf.last"))
	if err != nil {
		t.Fatal(err, notes)
	}
	got := string(out)
	want := `- component: wf
  name: run
  summary: 'runs: until settled'   # trailing comment
  sources:
  - a.go:1
  latency_ms: 5
  latency_source: {refined: child@abc123}
  latency_by_outcome:
  - when: result.ok && type(result.value) == map && "outcome" in result.value && result.value.outcome == "settled:failed"
    ms: 2702024
  - when: result.ok
    ms: 31
  behavior:
  - return: {ok: true}

  # Pinned by an operator.
`
	if !strings.Contains(got, want) {
		t.Fatalf("wf.run not edited in place:\n%s", got)
	}
	wantLast := `  - return: |
      # not a comment
      text
  latency_source: {refined: child@abc123}
  latency_by_outcome:
`
	if !strings.Contains(got, wantLast) || !strings.HasSuffix(got, "    ms: 31\n# Trailing comment.\n") {
		t.Fatalf("wf.last not appended after its literal block:\n%s", got)
	}
	// Everything but the inserted lines is unchanged.
	var rest []string
	skip := 0
	for _, ln := range strings.SplitAfter(got, "\n") {
		if skip > 0 {
			skip--
			continue
		}
		if strings.HasPrefix(ln, "  latency_source: {refined") {
			skip = 5
			continue
		}
		rest = append(rest, ln)
	}
	if strings.Join(rest, "") != applyFragment {
		t.Fatalf("other text changed:\n%s", strings.Join(rest, ""))
	}
	doc, err := model.ParseDocument(out)
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range doc.Interfaces {
		if f.Name == "run" && (f.LatencySource == nil || len(f.LatencyByOutcome) != 2 || f.LatencyByOutcome[0].MS.Min != 2702024) {
			t.Fatalf("wf.run reads back as %+v %+v", f.LatencySource, f.LatencyByOutcome)
		}
	}
}

func TestApplyTimingSkipsPinned(t *testing.T) {
	out, notes, err := applyTimingYAML([]byte(applyFragment), applyProps("wf.pinned"))
	if err != nil {
		t.Fatal(err)
	}
	if string(out) != applyFragment {
		t.Fatalf("pinned interface edited:\n%s", out)
	}
	if len(notes) != 1 || !strings.Contains(notes[0], "pinned (measured in prod)") {
		t.Fatalf("notes = %q", notes)
	}
}

func TestApplyTimingReapplyIsNoop(t *testing.T) {
	props := applyProps("wf.run", "wf.flow", "wf.last")
	once, _, err := applyTimingYAML([]byte(applyFragment), props)
	if err != nil {
		t.Fatal(err)
	}
	twice, notes, err := applyTimingYAML(once, props)
	if err != nil {
		t.Fatal(err)
	}
	if string(twice) != string(once) {
		t.Fatalf("re-apply changed the file:\n%s", unifiedDiff("f.yaml", once, twice))
	}
	for _, n := range notes {
		if !strings.Contains(n, "unchanged") {
			t.Fatalf("note %q", n)
		}
	}
	// A changed proposal replaces the old one in place, in both styles.
	props[0].ByOutcome = props[0].ByOutcome[1:]
	props[1].Source.Refined = "child@def456"
	third, _, err := applyTimingYAML(once, props)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(third), "child@abc123}, latency_by") || !strings.Contains(string(third), "{refined: child@def456}") {
		t.Fatalf("flow source not replaced:\n%s", third)
	}
	if d := unifiedDiff("f.yaml", once, third); strings.Count(d, "\n-") != 3 || strings.Count(d, "\n+") != 2 {
		t.Fatalf("replacement diff:\n%s", d)
	}
}

func TestApplyTimingFlowStyle(t *testing.T) {
	out, _, err := applyTimingYAML([]byte(applyFragment), applyProps("wf.flow"))
	if err != nil {
		t.Fatal(err)
	}
	want := `- {component: wf, name: flow, summary: "a, b", behavior: [{return: {}}], latency_source: {refined: child@abc123}, latency_by_outcome: [{when: result.ok && type(result.value) == map && "outcome" in result.value && result.value.outcome == "settled:failed", ms: 2702024}, {when: result.ok, ms: 31}]}
`
	if !strings.Contains(string(out), want) {
		t.Fatalf("flow entry:\n%s", out)
	}
	if strings.Replace(string(out), want, "- {component: wf, name: flow, summary: \"a, b\", behavior: [{return: {}}]}\n", 1) != applyFragment {
		t.Fatal("other text changed")
	}
}

func TestApplyTimingToFileDiffAndDryRun(t *testing.T) {
	p := filepath.Join(t.TempDir(), "frag.yaml")
	if err := os.WriteFile(p, []byte(applyFragment), 0o644); err != nil {
		t.Fatal(err)
	}
	src := []byte(applyFragment)
	out, _, err := applyTimingYAML(src, applyProps("wf.run"))
	if err != nil {
		t.Fatal(err)
	}
	d := unifiedDiff(p, src, out)
	if !strings.Contains(d, "@@ -9,6 +9,12 @@\n   sources:\n   - a.go:1\n   latency_ms: 5\n+  latency_source: {refined: child@abc123}\n") {
		t.Fatalf("diff:\n%s", d)
	}
	if strings.Count(d, "\n+") != 6+1 { // six lines and the +++ header
		t.Fatalf("diff:\n%s", d)
	}
	// The file edit itself: no proposals (empty results) leaves it unchanged.
	var b strings.Builder
	if err := applyTimingTo(&b, p, nil, true); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(b.String(), "unchanged") {
		t.Fatal(b.String())
	}
}

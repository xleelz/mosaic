package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestCountGateAndRatchet(t *testing.T) {
	r := &integrityReport{Lint: "clock-ids", Fragments: []fragShare{{Fragment: "a.yaml", Hits: 2, Of: 5}, {Fragment: "b.yaml", Hits: 1, Of: 3}}}
	var b bytes.Buffer
	if !countGate(&b, r, "max-clock-ids", 2) {
		t.Fatalf("3 findings above 2 should fail: %s", b.String())
	}
	b.Reset()
	if countGate(&b, r, "max-clock-ids", 5) {
		t.Fatalf("3 findings within 5 should pass")
	}
	if !strings.Contains(b.String(), "can go down to 3") {
		t.Fatalf("want a ratchet hint, got %q", b.String())
	}
	b.Reset()
	if countGate(&b, r, "max-clock-ids", -1) || b.Len() != 0 {
		t.Fatalf("no gate below 0: %q", b.String())
	}
}

func TestShareRatchetRoundsUp(t *testing.T) {
	r := &integrityReport{Lint: "internal-assertions", Fragments: []fragShare{{Fragment: "a.yaml", Hits: 165, Of: 335}}}
	var b bytes.Buffer
	shareRatchet(&b, r, "max-internal-assertions", 0.6)
	if !strings.Contains(b.String(), "can go down to 0.493") {
		t.Fatalf("want 0.493 (165/335 rounded up), got %q", b.String())
	}
}

func TestExploreGate(t *testing.T) {
	re, rec, max := *exploreRE, exploreRecordOnly, *maxExploreFailures
	defer func() { *exploreRE, exploreRecordOnly, *maxExploreFailures = re, rec, max }()
	*exploreRE = "race"
	var b bytes.Buffer
	exploreRecordOnly, *maxExploreFailures = false, -1
	if exploreGate(&b, 2) != 2 {
		t.Fatal("without a gate every failure counts")
	}
	exploreRecordOnly = true
	if exploreGate(&b, 2) != 0 || !strings.Contains(b.String(), "recorded, not gated") {
		t.Fatalf("record-only: %q", b.String())
	}
	exploreRecordOnly, *maxExploreFailures = false, 2
	if exploreGate(&b, 2) != 0 || exploreGate(&b, 3) != 3 {
		t.Fatal("--max-explore-failures 2: 2 pass, 3 fail")
	}
}

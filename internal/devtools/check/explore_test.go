package main

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/explore"
	"github.com/xleelz/mosaic/internal/model"
)

// DESIGN §15.5: --explore writes a failing scenario's replay, and removes
// the stale replay of one that passes every schedule now, unless
// --keep-replays.
func TestExploreRemovesStaleReplays(t *testing.T) {
	doc, err := model.ParseDocument([]byte(`schema_version: 1
components: [{id: a, state: {initial: {n: 0}}}]
interfaces: [{component: a, name: f, behavior: [{set: {state.n: "= state.n + 1"}}]}]
flows: [{id: f, entry: {caller: a, interface: a.f}}]
scenarios:
  - {id: race-fixed, flow: f, expect: ["state['a'].n == 1"]}
  - {id: race-broken, flow: f, expect: ["state['a'].n == 2"]}
`))
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	stale := filepath.Join(dir, "race-fixed.replay.json")
	old := &explore.Replay{Version: 1, Scenario: "race-fixed", Decisions: []int{1}, Failed: []string{"state['a'].n == 1"}}
	write := func() {
		if err := old.Write(stale); err != nil {
			t.Fatal(err)
		}
	}
	exists := func(p string) bool { _, err := os.Stat(p); return err == nil }
	re := regexp.MustCompile("^race")
	o := explore.Options{Schedules: 2}

	write()
	var out bytes.Buffer
	if failed := exploreAll(&out, doc, re, o, dir, true); failed != 1 {
		t.Fatalf("one scenario fails, got %d:\n%s", failed, out.String())
	}
	if !exists(stale) || !strings.Contains(out.String(), "stale replay kept (--keep-replays): "+stale) {
		t.Fatalf("--keep-replays should keep %s:\n%s", stale, out.String())
	}
	if !exists(filepath.Join(dir, "race-broken.replay.json")) {
		t.Fatalf("the failing scenario's replay was not written:\n%s", out.String())
	}

	out.Reset()
	exploreAll(&out, doc, re, o, dir, false)
	if exists(stale) || !strings.Contains(out.String(), "removed stale replay (passes every schedule now): "+stale) {
		t.Fatalf("the passing scenario's replay should be removed:\n%s", out.String())
	}
	if !exists(filepath.Join(dir, "race-broken.replay.json")) {
		t.Fatalf("the failing scenario's replay must stay:\n%s", out.String())
	}
	// Nothing to remove: no line.
	out.Reset()
	exploreAll(&out, doc, re, o, dir, false)
	if strings.Contains(out.String(), "stale replay") {
		t.Fatalf("no stale replay left, yet:\n%s", out.String())
	}
}

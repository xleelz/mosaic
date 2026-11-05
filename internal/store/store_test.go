package store_test

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/exec"
	"reflect"
	"sort"
	"strings"
	"sync"
	"testing"

	"github.com/xleelz/mosaic/internal/doltserver"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/store"
	"github.com/xleelz/mosaic/pkg/api"
)

var (
	st  *store.Store
	srv *doltserver.Server
)

func TestMain(m *testing.M) {
	if _, err := exec.LookPath("dolt"); err != nil {
		fmt.Println("skipping: dolt binary not found")
		os.Exit(0)
	}
	os.Exit(runMain(m))
}

func runMain(m *testing.M) int {
	dir, err := os.MkdirTemp("", "mosaic-store-test-")
	if err != nil {
		log.Fatal(err)
	}
	defer os.RemoveAll(dir)
	ctx := context.Background()
	srv, err = doltserver.Start(ctx, doltserver.Options{Bin: "dolt", DataDir: dir})
	if err != nil {
		log.Fatal(err)
	}
	defer srv.Stop()
	st, err = store.Open(ctx, srv.DB)
	if err != nil {
		log.Print(err)
		return 1
	}
	// Opening again is a no-op.
	if _, err := store.Open(ctx, srv.DB); err != nil {
		log.Print(err)
		return 1
	}
	return m.Run()
}

func comp(id, name string) json.RawMessage {
	return json.RawMessage(fmt.Sprintf(`{"id":%q,"name":%q,"kind":"service"}`, id, name))
}

func ids(t *testing.T, id string, r store.Rev) map[string]string {
	t.Helper()
	es, err := st.Entities(context.Background(), id, r, model.KindComponent)
	if err != nil {
		t.Fatal(err)
	}
	out := map[string]string{}
	for _, e := range es {
		var c model.Component
		if err := json.Unmarshal(e.Spec, &c); err != nil {
			t.Fatal(err)
		}
		out[c.ID] = c.Name
	}
	return out
}

// TestConcurrentDraftsAreIsolated edits two ontologies' drafts at the same
// time, revises one of them mid-stream, and checks that the revision holds
// only its own ontology's edits while the other draft stays dirty.
func TestConcurrentDraftsAreIsolated(t *testing.T) {
	ctx := context.Background()
	for _, id := range []string{"iso-a", "iso-b"} {
		if _, err := st.CreateOntology(ctx, api.CreateOntology{ID: id, Name: id}); err != nil {
			t.Fatal(err)
		}
	}
	const n = 12
	var wg sync.WaitGroup
	errs := make(chan error, 4*n)
	write := func(ont, prefix string, from, to int) {
		defer wg.Done()
		for i := from; i < to; i++ {
			if _, err := st.Upsert(ctx, ont, model.KindComponent, []json.RawMessage{comp(fmt.Sprintf("%s-%d", prefix, i), ont)}, "", false); err != nil {
				errs <- fmt.Errorf("%s: %w", ont, err)
				return
			}
		}
		// Both drafts also hold a component with the same id and different names.
		if _, err := st.Upsert(ctx, ont, model.KindComponent, []json.RawMessage{comp("shared", "from "+ont)}, "shared", false); err != nil {
			errs <- err
		}
	}
	wg.Add(2)
	go write("iso-a", "a", 0, n)
	go write("iso-b", "b", 0, n)
	wg.Wait()

	// Revise A while B keeps writing.
	wg.Add(1)
	go write("iso-b", "b", n, 2*n)
	rev, err := st.CreateRevision(ctx, "iso-a", api.CreateRevision{Message: "only A", Author: "Tester"})
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Fatal(err)
	}
	if err != nil {
		t.Fatal(err)
	}
	if rev.Number != 1 || rev.Author != "Tester <mosaic@localhost>" {
		t.Fatalf("revision = %+v", rev)
	}

	inRev := ids(t, "iso-a", store.Rev{N: 1})
	if len(inRev) != n+1 || inRev["shared"] != "from iso-a" {
		t.Fatalf("A's revision holds %d components (shared=%q): %v", len(inRev), inRev["shared"], inRev)
	}
	for c := range inRev {
		if strings.HasPrefix(c, "b-") {
			t.Fatalf("A's revision contains B's component %s", c)
		}
	}
	dA, err := st.GetOntology(ctx, "iso-a")
	if err != nil {
		t.Fatal(err)
	}
	dB, err := st.GetOntology(ctx, "iso-b")
	if err != nil {
		t.Fatal(err)
	}
	if dA.DraftDirty || dA.LatestRevision != 1 {
		t.Fatalf("A after revision = %+v", dA)
	}
	if !dB.DraftDirty || dB.RevisionCount != 0 || dB.Counts["component"] != 2*n+1 {
		t.Fatalf("B after A's revision = %+v", dB)
	}
	draftB := ids(t, "iso-b", store.Draft)
	if draftB["shared"] != "from iso-b" {
		t.Fatalf("B's shared component = %q", draftB["shared"])
	}
	for c := range draftB {
		if strings.HasPrefix(c, "a-") {
			t.Fatalf("B's draft contains A's component %s", c)
		}
	}
	// B has nothing at "latest", and its diff from the base lists only its own.
	if _, err := st.ResolveRev(ctx, "iso-b", "latest"); !isCode(err, store.CodeNotFound) {
		t.Fatalf("B latest: %v", err)
	}
	diff, err := st.Diff(ctx, "iso-b", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if diff.From != "base" || len(diff.Changes) != 2*n+1 {
		t.Fatalf("B diff from %s: %d changes", diff.From, len(diff.Changes))
	}
	// main holds only the registry tables.
	tables := showTables(t, "mosaic")
	if !reflect.DeepEqual(tables, []string{"commits", "evidence", "ontologies", "simulation_runs", "test_reports"}) {
		t.Fatalf("main tables = %v", tables)
	}
	if tables := showTables(t, "mosaic/ont/iso-a"); !reflect.DeepEqual(tables, []string{"entities", "meta"}) {
		t.Fatalf("ontology branch tables = %v", tables)
	}
}

func showTables(t *testing.T, db string) []string {
	t.Helper()
	rows, err := srv.DB.Query("SHOW TABLES FROM `" + db + "`")
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var s string
		if err := rows.Scan(&s); err != nil {
			t.Fatal(err)
		}
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}

func isCode(err error, code string) bool {
	e, ok := err.(*store.Error)
	return ok && e.Code == code
}

func TestRevisionNumbering(t *testing.T) {
	ctx := context.Background()
	id := "numbering"
	if _, err := st.CreateOntology(ctx, api.CreateOntology{ID: id}); err != nil {
		t.Fatal(err)
	}
	// Ten revisions, so "r10" sorts after "r9" numerically.
	for i := 1; i <= 10; i++ {
		if _, err := st.Upsert(ctx, id, model.KindComponent, []json.RawMessage{comp("c", fmt.Sprintf("v%d", i))}, "", false); err != nil {
			t.Fatal(err)
		}
		rev, err := st.CreateRevision(ctx, id, api.CreateRevision{})
		if err != nil {
			t.Fatal(err)
		}
		if rev.Number != i || rev.Author != store.DefaultAuthor || rev.Message != fmt.Sprintf("Revision %d", i) {
			t.Fatalf("revision %d = %+v", i, rev)
		}
	}
	revs, err := st.Revisions(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	for i, r := range revs {
		if r.Number != i+1 {
			t.Fatalf("revisions out of order: %+v", revs)
		}
	}
	latest, err := st.ResolveRev(ctx, id, "latest")
	if err != nil || latest.N != 10 {
		t.Fatalf("latest = %v, %v", latest, err)
	}
	if got := ids(t, id, store.Rev{N: 3})["c"]; got != "v3" {
		t.Fatalf("c at r3 = %q", got)
	}
	// An ontology whose id is a prefix of another's sees only its own tags.
	if _, err := st.CreateOntology(ctx, api.CreateOntology{ID: "numb"}); err != nil {
		t.Fatal(err)
	}
	if revs, _ := st.Revisions(ctx, "numb"); len(revs) != 0 {
		t.Fatalf("numb sees %d revisions", len(revs))
	}
	if d, _ := st.GetOntology(ctx, "numbering"); d.RevisionCount != 10 {
		t.Fatalf("numbering has %d revisions", d.RevisionCount)
	}
}

func TestMergePatch(t *testing.T) {
	var target, patch any
	_ = json.Unmarshal([]byte(`{"a":"b","c":{"d":"e","f":"g"},"l":[1,2]}`), &target)
	_ = json.Unmarshal([]byte(`{"a":"z","c":{"f":null},"l":[3],"n":{"x":null,"y":1}}`), &patch)
	got, _ := json.Marshal(store.MergePatch(target, patch))
	if want := `{"a":"z","c":{"d":"e"},"l":[3],"n":{"y":1}}`; string(got) != want {
		t.Fatalf("merge patch = %s, want %s", got, want)
	}
	if got := store.MergePatch(target, "x"); got != "x" {
		t.Fatalf("scalar patch = %v", got)
	}
}

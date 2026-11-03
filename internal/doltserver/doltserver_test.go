package doltserver_test

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"testing"
	"time"

	"github.com/xleelz/mosaic/internal/doltserver"
	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/store"
	"github.com/xleelz/mosaic/pkg/api"
)

func TestMain(m *testing.M) {
	if _, err := exec.LookPath("dolt"); err != nil {
		os.Stdout.WriteString("skipping: dolt binary not found\n")
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func start(t *testing.T, dir string) *doltserver.Server {
	t.Helper()
	s, err := doltserver.Start(context.Background(), doltserver.Options{Bin: "dolt", DataDir: dir})
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// stop stops the child and checks that its process is gone.
func stop(t *testing.T, s *doltserver.Server, pid int) {
	t.Helper()
	if err := s.Stop(); err != nil {
		t.Fatal(err)
	}
	select {
	case <-s.Exited():
	case <-time.After(15 * time.Second):
		t.Fatal("dolt did not exit")
	}
	if err := syscall.Kill(pid, 0); err == nil {
		t.Fatalf("dolt process %d still exists", pid)
	}
}

// TestRestartKeepsData starts a server, writes through the store, restarts
// it on the same data dir, and finds the registry, revisions, the draft and
// the uncommitted runs intact.
func TestRestartKeepsData(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	s := start(t, dir)
	if _, err := os.Stat(filepath.Join(dir, "dolt")); err != nil {
		t.Fatal("data dir not created:", err)
	}
	pid := s.Pid()
	st, err := store.Open(ctx, s.DB)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.CreateOntology(ctx, api.CreateOntology{ID: "keep", Name: "Keep"}); err != nil {
		t.Fatal(err)
	}
	spec := json.RawMessage(`{"id":"svc","name":"Service"}`)
	if _, err := st.Upsert(ctx, "keep", model.KindComponent, []json.RawMessage{spec}, "", false); err != nil {
		t.Fatal(err)
	}
	if _, err := st.CreateRevision(ctx, "keep", api.CreateRevision{Message: "one"}); err != nil {
		t.Fatal(err)
	}
	if _, err := st.Upsert(ctx, "keep", model.KindComponent, []json.RawMessage{json.RawMessage(`{"id":"db","name":"DB"}`)}, "", false); err != nil {
		t.Fatal(err)
	}
	run := &api.SimulationRun{ID: "run_test_1", Ontology: "keep", Revision: "1", Flow: "f", CreatedAt: time.Now().UTC().Truncate(time.Microsecond)}
	if err := st.SaveRun(ctx, run); err != nil {
		t.Fatal(err)
	}
	stop(t, s, pid)

	s = start(t, dir)
	defer s.Stop()
	if v := s.Version(ctx); v == "" || v == "unknown" {
		t.Fatalf("version = %q", v)
	}
	st, err = store.Open(ctx, s.DB)
	if err != nil {
		t.Fatal(err)
	}
	d, err := st.GetOntology(ctx, "keep")
	if err != nil {
		t.Fatal(err)
	}
	if d.Name != "Keep" || d.LatestRevision != 1 || !d.DraftDirty || d.Counts["component"] != 2 {
		t.Fatalf("after restart = %+v", d)
	}
	got, err := st.GetRun(ctx, "run_test_1")
	if err != nil || got.Ontology != "keep" {
		t.Fatalf("run after restart: %+v, %v", got, err)
	}
}

func TestConnectToDSN(t *testing.T) {
	ctx := context.Background()
	s := start(t, t.TempDir())
	defer s.Stop()
	c, err := doltserver.Start(ctx, doltserver.Options{DSN: s.DSN})
	if err != nil {
		t.Fatal(err)
	}
	if c.Pid() != 0 || c.Exited() != nil {
		t.Fatal("a DSN connection has no child")
	}
	if err := c.DB.PingContext(ctx); err != nil {
		t.Fatal(err)
	}
	if err := c.Stop(); err != nil {
		t.Fatal(err)
	}
	// The original server is unaffected.
	if err := s.DB.PingContext(ctx); err != nil {
		t.Fatal(err)
	}
}

func TestStartFailsFast(t *testing.T) {
	_, err := doltserver.Start(context.Background(), doltserver.Options{Bin: "/nonexistent/dolt", DataDir: t.TempDir()})
	if err == nil {
		t.Fatal("expected an error for a missing binary")
	}
}

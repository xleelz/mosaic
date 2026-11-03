package api_test

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime/debug"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/api"
	"github.com/xleelz/mosaic/internal/selfupdate"
	wire "github.com/xleelz/mosaic/pkg/api"
)

// gitFixture makes a bare remote and a checkout of it that is behind by
// `behind` commits.
func gitFixture(t *testing.T, behind int) string {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not found")
	}
	dir := t.TempDir()
	home := t.TempDir()
	run := func(d string, args ...string) {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", d, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"}, args...)...)
		cmd.Env = append(os.Environ(), "GIT_CONFIG_NOSYSTEM=1", "HOME="+home)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	remote, pusher, src := filepath.Join(dir, "r.git"), filepath.Join(dir, "p"), filepath.Join(dir, "src")
	run(dir, "init", "--quiet", "--bare", "--initial-branch=main", remote)
	run(dir, "clone", "--quiet", remote, pusher)
	commit := func(msg string) {
		if err := os.WriteFile(filepath.Join(pusher, "f.txt"), []byte(msg), 0o644); err != nil {
			t.Fatal(err)
		}
		run(pusher, "add", "f.txt")
		run(pusher, "commit", "--quiet", "-m", msg)
		run(pusher, "push", "--quiet", "origin", "HEAD:main")
	}
	commit("first")
	run(dir, "clone", "--quiet", remote, src)
	for i := 0; i < behind; i++ {
		commit("next")
	}
	return src
}

type systemServer struct {
	h         http.Handler
	restarted int
}

func newSystemServer(t *testing.T, src, token string, supervised bool) *systemServer {
	s := &systemServer{}
	u := selfupdate.New(selfupdate.Options{SourceDir: src, Version: "test", Supervised: supervised,
		BuildInfo: func() (*debug.BuildInfo, bool) { return nil, false }})
	s.h = api.New(api.Config{Version: "test", Token: token, Logger: log.New(io.Discard, "", 0),
		Updater: u, OnRestart: func() { s.restarted++ }})
	return s
}

func (s *systemServer) do(method, path, remote string, hdr map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, nil)
	req.RemoteAddr = remote
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	s.h.ServeHTTP(rec, req)
	return rec
}

const loopback = "127.0.0.1:50000"

func TestSystemVersionAndUpdate(t *testing.T) {
	src := gitFixture(t, 1)
	s := newSystemServer(t, src, "", true)

	rec := s.do("GET", "/v1/system/version?refresh=1", loopback, nil)
	if rec.Code != 200 {
		t.Fatalf("version: %d %s", rec.Code, rec.Body)
	}
	var v wire.SystemVersion
	if err := json.Unmarshal(rec.Body.Bytes(), &v); err != nil {
		t.Fatal(err)
	}
	if !v.Update.Available || v.Update.Behind != 1 || v.SourceDir != src || v.Version != "test" {
		t.Fatalf("version = %+v", v)
	}

	// Not from loopback: 403, nothing changes.
	if rec := s.do("POST", "/v1/system/update", "192.0.2.7:4000", nil); rec.Code != 403 {
		t.Fatalf("non-loopback update: %d %s", rec.Code, rec.Body)
	}
	// From loopback but a foreign page's origin: 403.
	if rec := s.do("POST", "/v1/system/update", loopback, map[string]string{"Origin": "http://evil.example"}); rec.Code != 403 {
		t.Fatalf("foreign origin: %d %s", rec.Code, rec.Body)
	}
	if s.restarted != 0 {
		t.Fatal("a refused update asked for a restart")
	}

	rec = s.do("POST", "/v1/system/update", loopback, map[string]string{"Origin": "http://localhost:3000"})
	if rec.Code != 200 {
		t.Fatalf("update: %d %s", rec.Code, rec.Body)
	}
	var res wire.SystemUpdate
	if err := json.Unmarshal(rec.Body.Bytes(), &res); err != nil {
		t.Fatal(err)
	}
	if !res.Restarting || res.From == res.UpdatedTo || res.UpdatedTo != v.Update.LatestCommit || s.restarted != 1 {
		t.Fatalf("update = %+v (restarted %d)", res, s.restarted)
	}
	// Restarting: a second update is refused.
	if rec := s.do("POST", "/v1/system/update", loopback, nil); rec.Code != 409 {
		t.Fatalf("second update: %d %s", rec.Code, rec.Body)
	}
}

func TestSystemUpdateRefused(t *testing.T) {
	// Up to date: 409 with the reason.
	s := newSystemServer(t, gitFixture(t, 0), "", true)
	rec := s.do("POST", "/v1/system/update", loopback, nil)
	if rec.Code != 409 || !strings.Contains(rec.Body.String(), "up to date") {
		t.Fatalf("up to date: %d %s", rec.Code, rec.Body)
	}
	// No source dir: version answers, update refuses.
	s = newSystemServer(t, "", "", true)
	if rec := s.do("GET", "/v1/system/version", loopback, nil); rec.Code != 200 || !strings.Contains(rec.Body.String(), "--source-dir") {
		t.Fatalf("no source dir version: %d %s", rec.Code, rec.Body)
	}
	if rec := s.do("POST", "/v1/system/update", loopback, nil); rec.Code != 409 {
		t.Fatalf("no source dir update: %d %s", rec.Code, rec.Body)
	}
	if s.restarted != 0 {
		t.Fatal("a refused update asked for a restart")
	}
}

func TestSystemUpdateNeedsToken(t *testing.T) {
	src := gitFixture(t, 1)
	s := newSystemServer(t, src, "s3cret", false)
	if rec := s.do("POST", "/v1/system/update", loopback, nil); rec.Code != 401 {
		t.Fatalf("without token: %d %s", rec.Code, rec.Body)
	}
	rec := s.do("POST", "/v1/system/update", loopback, map[string]string{"Authorization": "Bearer s3cret"})
	if rec.Code != 200 {
		t.Fatalf("with token: %d %s", rec.Code, rec.Body)
	}
	var res wire.SystemUpdate
	if err := json.Unmarshal(rec.Body.Bytes(), &res); err != nil {
		t.Fatal(err)
	}
	// Unsupervised: updated, not restarting.
	if res.Restarting || s.restarted != 0 || res.Note == "" {
		t.Fatalf("unsupervised update = %+v", res)
	}
}

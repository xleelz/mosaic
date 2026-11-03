package api_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/xleelz/mosaic/internal/api"
	"github.com/xleelz/mosaic/internal/model"
	wire "github.com/xleelz/mosaic/pkg/api"
)

const (
	srcRepo   = "acme/shop"
	srcSHA    = "0123456789abcdef0123456789abcdef01234567"
	citeRepo  = "acme/lib"
	citeSHA   = "fedcba9876543210fedcba9876543210fedcba98"
	fakeToken = "ghp_TESTTOKEN_never_leak_0123456789"
)

// fakeGitHub serves raw.githubusercontent.com-style paths and records requests.
type fakeGitHub struct {
	mu    sync.Mutex
	hits  map[string]int
	auth  []string
	files map[string]string // "/repo/sha/path" -> content
	codes map[string]int    // "/repo/sha/path" -> status
}

func (g *fakeGitHub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	g.mu.Lock()
	g.hits[r.URL.Path]++
	g.auth = append(g.auth, r.Header.Get("Authorization"))
	code, hasCode := g.codes[r.URL.Path]
	body, ok := g.files[r.URL.Path]
	g.mu.Unlock()
	switch {
	case hasCode:
		w.WriteHeader(code)
		fmt.Fprintf(w, "status %d", code)
	case ok:
		_, _ = w.Write([]byte(body))
	default:
		http.NotFound(w, r)
	}
}

type sourceEnv struct {
	gh      *fakeGitHub
	base    string
	logs    *bytes.Buffer
	dataDir string
}

func newSourceEnv(t *testing.T, token string) *sourceEnv {
	t.Helper()
	gh := &fakeGitHub{hits: map[string]int{}, files: map[string]string{}, codes: map[string]int{}}
	fake := httptest.NewServer(gh)
	t.Cleanup(fake.Close)
	e := &sourceEnv{gh: gh, logs: &bytes.Buffer{}, dataDir: t.TempDir()}
	h := api.New(api.Config{Store: st, Version: "test", Logger: log.New(e.logs, "", 0),
		DataDir: e.dataDir, GitHubRawURL: fake.URL,
		GitHubToken: func(context.Context) string { return token }})
	ts := httptest.NewServer(h)
	t.Cleanup(ts.Close)
	e.base = ts.URL
	return e
}

var sourceOntOnce sync.Once

// sourceOntology loads the example with a source and one citation in
// another repo, once for every test.
func sourceOntology(t *testing.T) string {
	t.Helper()
	const id = "srcview"
	sourceOntOnce.Do(func() {
		call(t, "POST", "/v1/ontologies", wire.CreateOntology{ID: id, Name: "source viewer"}, 201)
		var doc model.Document
		if err := json.Unmarshal(exampleJSON(t), &doc); err != nil {
			t.Fatal(err)
		}
		doc.Source = &model.DocSource{Repo: srcRepo, SHA: srcSHA}
		doc.Components[0].Sources = append(doc.Components[0].Sources,
			model.Source{Repo: citeRepo, SHA: citeSHA, Path: "lib.go", Line: 3})
		call(t, "PUT", "/v1/ontologies/"+id+"/document", doc, 200)
	})
	return id
}

func (e *sourceEnv) get(t *testing.T, ont, query string, want int) []byte {
	t.Helper()
	return callURL(t, e.base, nil, "GET", "/v1/ontologies/"+ont+"/source?"+query, nil, want)
}

func errMessage(t *testing.T, b []byte) string {
	t.Helper()
	return decode[wire.ErrorBody](t, b).Error.Message
}

func TestSourceFetchAndCache(t *testing.T) {
	ont := sourceOntology(t)
	e := newSourceEnv(t, fakeToken)
	key := "/" + srcRepo + "/" + srcSHA + "/cmd/main.go"
	e.gh.files[key] = "package main\n"

	f := decode[wire.SourceFile](t, e.get(t, ont, "path=cmd/main.go", 200))
	if f.Content != "package main\n" || f.Repo != srcRepo || f.SHA != srcSHA || f.Path != "cmd/main.go" ||
		f.LanguageHint != "go" || f.Size != 13 || f.URL != "https://github.com/"+srcRepo+"/blob/"+srcSHA+"/cmd/main.go" {
		t.Fatalf("file: %+v", f)
	}
	if got := e.gh.auth[0]; got != "Bearer "+fakeToken {
		t.Fatalf("Authorization to GitHub = %q", got)
	}
	cached := filepath.Join(e.dataDir, "source-cache", "acme", "shop", srcSHA, "cmd", "main.go")
	if b, err := os.ReadFile(cached); err != nil || string(b) != "package main\n" {
		t.Fatalf("cache file: %q %v", b, err)
	}
	// A second request is served from the cache.
	e.get(t, ont, "path=cmd/main.go&rev=draft", 200)
	if e.gh.hits[key] != 1 {
		t.Fatalf("GitHub hits = %d, want 1", e.gh.hits[key])
	}
	// A citation's repo@sha is allowed, and so is a citation's repo with
	// the document's sha filled in when it matches a citation.
	e.gh.files["/"+citeRepo+"/"+citeSHA+"/lib.go"] = "package lib\n"
	f = decode[wire.SourceFile](t, e.get(t, ont, "path=lib.go&repo="+citeRepo+"&sha="+citeSHA, 200))
	if f.Repo != citeRepo || f.Content != "package lib\n" {
		t.Fatalf("citation file: %+v", f)
	}
}

func TestSourceAllowlist(t *testing.T) {
	ont := sourceOntology(t)
	e := newSourceEnv(t, fakeToken)
	for _, q := range []string{
		"path=a.go&repo=evil/repo",                      // another repo at the document's sha
		"path=a.go&sha=" + strings.Repeat("a", 40),      // the document's repo at another sha
		"path=a.go&repo=" + citeRepo,                    // a citation's repo with the document's sha
		"path=a.go&repo=" + srcRepo + "&sha=" + citeSHA, // mixed pair
		"path=a.go&repo=evil/repo&sha=" + citeSHA,       // a citation's sha with another repo
	} {
		msg := errMessage(t, e.get(t, ont, q, 403))
		if !strings.Contains(msg, "neither the document's source nor on one of its citations") {
			t.Errorf("%s: %s", q, msg)
		}
	}
	e.get(t, ont, "path=a.go&repo=http://x/y", 400)
	e.get(t, ont, "path=a.go&sha=main", 400)
	if n := len(e.gh.auth); n != 0 {
		t.Fatalf("refused requests reached GitHub %d times", n)
	}
	e.get(t, "nope", "path=a.go", 404)
}

func TestSourcePathValidation(t *testing.T) {
	ont := sourceOntology(t)
	e := newSourceEnv(t, fakeToken)
	for _, p := range []string{"", "/etc/passwd", "../x.go", "a/../../x.go", "a/..", "a//b.go", "./a.go", "a\\b.go", "a%00.go"} {
		e.get(t, ont, "path="+strings.ReplaceAll(p, "/", "%2F"), 400)
	}
	if n := len(e.gh.auth); n != 0 {
		t.Fatalf("invalid paths reached GitHub %d times", n)
	}
}

func TestSourceSecretDenylist(t *testing.T) {
	refused := []string{".env", ".env.local", "config/.ENV.prod", "tls/server.pem", "k.key", "x.age",
		"store.jks", "c.p12", "credentials", "credentials.json", "aws/Credentials.yaml", ".netrc",
		"client_secret.json", "gcp/my-secrets.json", "id_rsa", "home/.ssh/id_rsa.pub"}
	allowed := []string{"env.go", "main.go", "keys.go", "secret.go", "secrets.yaml", "README.md", "pkg/netrc.go", "environment.py"}
	for _, p := range refused {
		if !api.IsSecretPath(p) {
			t.Errorf("IsSecretPath(%q) = false", p)
		}
	}
	for _, p := range allowed {
		if api.IsSecretPath(p) {
			t.Errorf("IsSecretPath(%q) = true", p)
		}
	}
	if len(api.SecretFilePatterns) != 10 {
		t.Errorf("SecretFilePatterns has %d entries", len(api.SecretFilePatterns))
	}
	ont := sourceOntology(t)
	e := newSourceEnv(t, fakeToken)
	for _, p := range refused {
		e.get(t, ont, "path="+p, 403)
	}
	if n := len(e.gh.auth); n != 0 {
		t.Fatalf("secret paths reached GitHub %d times", n)
	}
}

func TestSourceUpstreamErrors(t *testing.T) {
	ont := sourceOntology(t)
	e := newSourceEnv(t, fakeToken)
	pre := "/" + srcRepo + "/" + srcSHA + "/"
	e.gh.codes[pre+"private.go"] = 401
	e.gh.codes[pre+"forbidden.go"] = 403
	e.gh.codes[pre+"flaky.go"] = 500
	e.gh.files[pre+"big.go"] = strings.Repeat("x", api.MaxSourceBytes+1)
	e.gh.files[pre+"edge.go"] = strings.Repeat("x", api.MaxSourceBytes)

	if msg := errMessage(t, e.get(t, ont, "path=missing.go", 404)); msg != "file not found at that commit" {
		t.Errorf("404: %q", msg)
	}
	for _, p := range []string{"private.go", "forbidden.go"} {
		if msg := errMessage(t, e.get(t, ont, "path="+p, 502)); !strings.Contains(msg, "private repo: set GITHUB_TOKEN or run gh auth login for mosaicd") {
			t.Errorf("%s: %q", p, msg)
		}
	}
	e.get(t, ont, "path=flaky.go", 502)
	e.get(t, ont, "path=big.go", 413)
	e.get(t, ont, "path=edge.go", 200)
	// Errors are not cached.
	e.get(t, ont, "path=missing.go", 404)
	if e.gh.hits[pre+"missing.go"] != 2 {
		t.Errorf("missing.go hits = %d", e.gh.hits[pre+"missing.go"])
	}
	if _, err := os.Stat(filepath.Join(e.dataDir, "source-cache", "acme", "shop", srcSHA, "big.go")); err == nil {
		t.Error("an oversized file was cached")
	}

	// Without a token, a 404 may be a private repo: say so.
	e2 := newSourceEnv(t, "")
	if msg := errMessage(t, e2.get(t, ont, "path=missing.go", 404)); !strings.Contains(msg, "gh auth login") {
		t.Errorf("404 without a token: %q", msg)
	}
	if got := e2.gh.auth[0]; got != "" {
		t.Errorf("sent Authorization %q without a token", got)
	}
}

func TestSourceTokenNeverLeaks(t *testing.T) {
	ont := sourceOntology(t)
	e := newSourceEnv(t, fakeToken)
	pre := "/" + srcRepo + "/" + srcSHA + "/"
	e.gh.files[pre+"ok.go"] = "package ok\n"
	e.gh.codes[pre+"private.go"] = 401
	var bodies []byte
	for _, q := range []string{"path=ok.go", "path=private.go", "path=missing.go", "path=.env", "path=../x"} {
		resp, err := http.Get(e.base + "/v1/ontologies/" + ont + "/source?" + q)
		if err != nil {
			t.Fatal(err)
		}
		var buf bytes.Buffer
		_, _ = buf.ReadFrom(resp.Body)
		resp.Body.Close()
		for k, vs := range resp.Header {
			bodies = append(bodies, []byte(k+": "+strings.Join(vs, ",")+"\n")...)
		}
		bodies = append(bodies, buf.Bytes()...)
	}
	for _, a := range e.gh.auth {
		if a != "Bearer "+fakeToken {
			t.Errorf("GitHub got Authorization %q", a)
		}
	}
	if bytes.Contains(bodies, []byte(fakeToken)) || bytes.Contains(bodies, []byte("TESTTOKEN")) {
		t.Fatal("the token appears in a response")
	}
	if strings.Contains(e.logs.String(), "TESTTOKEN") {
		t.Fatalf("the token appears in the log:\n%s", e.logs)
	}
	if e.logs.Len() == 0 {
		t.Fatal("expected request log lines")
	}
}

func TestSourceRedirectDropsToken(t *testing.T) {
	ont := sourceOntology(t)
	var gotAuth []string
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = append(gotAuth, r.Header.Get("Authorization"))
		_, _ = w.Write([]byte("elsewhere\n"))
	}))
	defer other.Close()
	redirect := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, other.URL+"/x", http.StatusFound)
	}))
	defer redirect.Close()
	h := api.New(api.Config{Store: st, Version: "test", Logger: log.New(&bytes.Buffer{}, "", 0),
		GitHubRawURL: redirect.URL, GitHubToken: func(context.Context) string { return fakeToken }})
	ts := httptest.NewServer(h)
	defer ts.Close()
	f := decode[wire.SourceFile](t, callURL(t, ts.URL, nil, "GET", "/v1/ontologies/"+ont+"/source?path=moved.go", nil, 200))
	if f.Content != "elsewhere\n" {
		t.Fatalf("content %q", f.Content)
	}
	if len(gotAuth) != 1 || gotAuth[0] != "" {
		t.Fatalf("redirect target got Authorization %q", gotAuth)
	}
}

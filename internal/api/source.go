package api

// GET /v1/ontologies/{id}/source (docs/DESIGN.md §6): one file of the code an
// ontology was derived from, fetched from raw.githubusercontent.com at the
// document's commit and cached under <data-dir>/source-cache. It is not an
// open proxy: the repo and commit must be the document's source or appear on
// one of its citations, the path is relative and checked, and secret-looking
// files are refused. The GitHub token never leaves mosaicd except to GitHub.

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	wire "github.com/xleelz/mosaic/pkg/api"
)

// SecretFilePatterns are the base names (path.Match globs, matched
// case-insensitively) that GET /ontologies/{id}/source refuses with 403.
var SecretFilePatterns = []string{
	".env*",
	"*.pem",
	"*.key",
	"*.age",
	"*.jks",
	"*.p12",
	"credentials*",
	".netrc",
	"*secret*.json",
	"id_rsa*",
}

const (
	// MaxSourceBytes bounds a fetched file; larger ones answer 413.
	MaxSourceBytes = 2 << 20
	// DefaultGitHubRawURL is where files are fetched from.
	DefaultGitHubRawURL = "https://raw.githubusercontent.com"
	sourceFetchTimeout  = 20 * time.Second
	ghTokenTimeout      = 5 * time.Second
	tokenHint           = "set GITHUB_TOKEN or run gh auth login for mosaicd"
)

// tokenHosts are the only hosts the GitHub token is sent to (plus an
// injected Config.GitHubRawURL's host).
var tokenHosts = map[string]bool{"raw.githubusercontent.com": true, "api.github.com": true}

var (
	repoRE = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	shaRE  = regexp.MustCompile(`^[0-9a-fA-F]{7,64}$`)
)

// IsSecretPath reports whether p's base name matches SecretFilePatterns.
func IsSecretPath(p string) bool {
	base := strings.ToLower(path.Base(p))
	for _, pat := range SecretFilePatterns {
		if ok, _ := path.Match(pat, base); ok {
			return true
		}
	}
	return false
}

// checkSourcePath refuses anything but a clean relative path.
func checkSourcePath(p string) error {
	switch {
	case p == "":
		return badRequest("path is required")
	case strings.ContainsRune(p, 0):
		return badRequest("path must not contain NUL")
	case strings.HasPrefix(p, "/"):
		return badRequest("path must be relative to the repo root (no leading /)")
	case strings.Contains(p, "\\"):
		return badRequest("path must use / separators")
	}
	for _, seg := range strings.Split(p, "/") {
		if seg == ".." {
			return badRequest("path must not contain ..")
		}
		if seg == "" || seg == "." {
			return badRequest("path must be clean (no empty or . segments)")
		}
	}
	return nil
}

// languageByExt maps file extensions (and some base names) to language_hint.
var languageByExt = map[string]string{
	".go": "go", ".py": "python", ".pyi": "python",
	".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hh": "cpp", ".hpp": "cpp", ".hxx": "cpp",
	".cu": "cuda", ".cuh": "cuda",
	".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "jsx",
	".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "tsx",
	".rs": "rust", ".java": "java", ".yaml": "yaml", ".yml": "yaml", ".json": "json",
	".md": "markdown", ".markdown": "markdown", ".sql": "sql",
	".sh": "shell", ".bash": "shell", ".zsh": "shell",
	".tf": "hcl", ".tfvars": "hcl", ".hcl": "hcl", ".proto": "protobuf",
}

func languageHint(p string) string {
	base := strings.ToLower(path.Base(p))
	if base == "dockerfile" || strings.HasPrefix(base, "dockerfile.") || strings.HasSuffix(base, ".dockerfile") {
		return "dockerfile"
	}
	return languageByExt[path.Ext(base)]
}

// sourceFetcher fetches and caches files.
type sourceFetcher struct {
	base      string
	sendToken bool // the base host may receive the token
	cacheDir  string
	client    *http.Client
	token     func(context.Context) string
}

func newSourceFetcher(cfg Config) *sourceFetcher {
	f := &sourceFetcher{base: strings.TrimRight(cfg.GitHubRawURL, "/"), token: cfg.GitHubToken}
	injected := f.base != ""
	if !injected {
		f.base = DefaultGitHubRawURL
	}
	if u, err := url.Parse(f.base); err == nil {
		f.sendToken = injected || tokenHosts[u.Hostname()]
	}
	if cfg.DataDir != "" {
		f.cacheDir = filepath.Join(cfg.DataDir, "source-cache")
	}
	if f.token == nil {
		f.token = (&ghToken{}).get
	}
	baseHost := ""
	if u, err := url.Parse(f.base); err == nil {
		baseHost = u.Host
	}
	f.client = &http.Client{
		Timeout: sourceFetchTimeout,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 5 {
				return errors.New("too many redirects")
			}
			// Never carry the token to a host it isn't meant for.
			if !tokenHosts[req.URL.Hostname()] && req.URL.Host != baseHost {
				req.Header.Del("Authorization")
			}
			return nil
		},
	}
	return f
}

// ghToken reads the token once: $GITHUB_TOKEN, $GH_TOKEN, else `gh auth token`.
type ghToken struct {
	once sync.Once
	tok  string
}

func (g *ghToken) get(ctx context.Context) string {
	g.once.Do(func() { g.tok = readGitHubToken(ctx, os.Getenv, exec.LookPath) })
	return g.tok
}

func readGitHubToken(ctx context.Context, getenv func(string) string, lookPath func(string) (string, error)) string {
	for _, k := range []string{"GITHUB_TOKEN", "GH_TOKEN"} {
		if v := strings.TrimSpace(getenv(k)); v != "" {
			return v
		}
	}
	gh, err := lookPath("gh")
	if err != nil {
		return ""
	}
	// Detached from the request: the result is cached for the process.
	cctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), ghTokenTimeout)
	defer cancel()
	out, err := exec.CommandContext(cctx, gh, "auth", "token").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// sourceError is a refusal with its HTTP status.
type sourceError struct {
	status int
	code   string
	msg    string
}

func (e *sourceError) Error() string { return e.msg }

func (f *sourceFetcher) cachePath(repo, sha, p string) string {
	if f.cacheDir == "" {
		return ""
	}
	return filepath.Join(f.cacheDir, filepath.FromSlash(repo), sha, filepath.FromSlash(p))
}

// get returns the file's bytes from the cache or GitHub.
func (f *sourceFetcher) get(ctx context.Context, repo, sha, p string) ([]byte, error) {
	cp := f.cachePath(repo, sha, p)
	if cp != "" {
		if b, err := os.ReadFile(cp); err == nil {
			return b, nil
		}
	}
	segs := strings.Split(p, "/")
	for i, s := range segs {
		segs[i] = url.PathEscape(s)
	}
	u := f.base + "/" + repo + "/" + sha + "/" + strings.Join(segs, "/")
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	tok := ""
	if f.sendToken {
		tok = f.token(ctx)
	}
	if tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	resp, err := f.client.Do(req)
	if err != nil {
		return nil, &sourceError{http.StatusBadGateway, "upstream", fmt.Sprintf("fetch %s@%s %s from GitHub failed: %v", repo, shortSHA(sha), p, unwrapURLErr(err))}
	}
	defer resp.Body.Close()
	switch {
	case resp.StatusCode == http.StatusNotFound:
		msg := "file not found at that commit"
		if tok == "" {
			// raw.githubusercontent.com answers 404 for private repos too.
			msg += " (if the repo is private: " + tokenHint + ")"
		}
		return nil, &sourceError{http.StatusNotFound, "not_found", msg}
	case resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden:
		return nil, &sourceError{http.StatusBadGateway, "upstream", fmt.Sprintf("GitHub answered %d: private repo: %s", resp.StatusCode, tokenHint)}
	case resp.StatusCode != http.StatusOK:
		return nil, &sourceError{http.StatusBadGateway, "upstream", fmt.Sprintf("GitHub answered %d", resp.StatusCode)}
	}
	tooBig := &sourceError{http.StatusRequestEntityTooLarge, "too_large", fmt.Sprintf("%s is larger than %d bytes", p, MaxSourceBytes)}
	if resp.ContentLength > MaxSourceBytes {
		return nil, tooBig
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, MaxSourceBytes+1))
	if err != nil {
		return nil, &sourceError{http.StatusBadGateway, "upstream", fmt.Sprintf("reading %s from GitHub: %v", p, err)}
	}
	if len(b) > MaxSourceBytes {
		return nil, tooBig
	}
	if cp != "" {
		_ = writeAtomic(cp, b) // the cache is best effort
	}
	return b, nil
}

func unwrapURLErr(err error) error {
	var ue *url.Error
	if errors.As(err, &ue) {
		return ue.Err
	}
	return err
}

// writeAtomic writes b to p through a temporary file and a rename.
func writeAtomic(p string, b []byte) error {
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(p), ".tmp-*")
	if err != nil {
		return err
	}
	_, werr := tmp.Write(b)
	cerr := tmp.Close()
	if werr == nil {
		werr = cerr
	}
	if werr == nil {
		werr = os.Rename(tmp.Name(), p)
	}
	if werr != nil {
		_ = os.Remove(tmp.Name())
	}
	return werr
}

func shortSHA(s string) string {
	if len(s) > 7 {
		return s[:7]
	}
	return s
}

// sourcePairs collects every repo@sha the document names: its source and each
// citation's, a citation's missing half taken from the document's source.
func sourcePairs(doc *model.Document) map[[2]string]bool {
	var repo, sha string
	if doc.Source != nil {
		repo, sha = doc.Source.Repo, doc.Source.SHA
	}
	out := map[[2]string]bool{}
	if repo != "" && sha != "" {
		out[[2]string{repo, sha}] = true
	}
	srcType := reflect.TypeOf(model.Source{})
	seen := map[uintptr]bool{}
	var walk func(v reflect.Value)
	walk = func(v reflect.Value) {
		switch v.Kind() {
		case reflect.Pointer:
			if v.IsNil() || seen[v.Pointer()] {
				return
			}
			seen[v.Pointer()] = true
			walk(v.Elem())
		case reflect.Interface:
			if !v.IsNil() {
				walk(v.Elem())
			}
		case reflect.Struct:
			if v.Type() == srcType {
				s := v.Interface().(model.Source)
				r, h := s.Repo, s.SHA
				if r == "" {
					r = repo
				}
				if h == "" {
					h = sha
				}
				if r != "" && h != "" {
					out[[2]string{r, h}] = true
				}
				return
			}
			for i := 0; i < v.NumField(); i++ {
				if v.Type().Field(i).IsExported() {
					walk(v.Field(i))
				}
			}
		case reflect.Slice, reflect.Array:
			for i := 0; i < v.Len(); i++ {
				walk(v.Index(i))
			}
		case reflect.Map:
			it := v.MapRange()
			for it.Next() {
				walk(it.Value())
			}
		}
	}
	walk(reflect.ValueOf(doc))
	return out
}

func (s *Server) sourceRoutes(m *http.ServeMux) {
	m.HandleFunc("GET /v1/ontologies/{id}/source", s.getSource)
}

func (s *Server) getSource(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	p := q.Get("path")
	if err := checkSourcePath(p); err != nil {
		s.fail(w, r, err)
		return
	}
	if IsSecretPath(p) {
		writeError(w, http.StatusForbidden, "forbidden", "refusing to serve "+path.Base(p)+": it looks like a secret file", nil)
		return
	}
	doc, _, _, err := s.document(r)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	repo, sha := q.Get("repo"), q.Get("sha")
	if doc.Source != nil {
		if repo == "" {
			repo = doc.Source.Repo
		}
		if sha == "" {
			sha = doc.Source.SHA
		}
	}
	if repo == "" || sha == "" {
		s.fail(w, r, badRequest("the document has no source repo and sha; pass repo and sha from a citation"))
		return
	}
	if !repoRE.MatchString(repo) {
		s.fail(w, r, badRequest("repo must be owner/name, got %q", repo))
		return
	}
	if !shaRE.MatchString(sha) {
		s.fail(w, r, badRequest("sha must be a commit hash, got %q", sha))
		return
	}
	if !sourcePairs(doc)[[2]string{repo, sha}] {
		writeError(w, http.StatusForbidden, "forbidden", fmt.Sprintf("%s@%s is neither the document's source nor on one of its citations", repo, shortSHA(sha)), nil)
		return
	}
	b, err := s.source.get(r.Context(), repo, sha, p)
	if err != nil {
		var se *sourceError
		if errors.As(err, &se) {
			if se.status == http.StatusBadGateway {
				s.cfg.Logger.Printf("source %s@%s %s: %s", repo, shortSHA(sha), p, se.msg)
			}
			writeError(w, se.status, se.code, se.msg, nil)
			return
		}
		s.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, wire.SourceFile{
		Repo: repo, SHA: sha, Path: p, Content: string(b), LanguageHint: languageHint(p), Size: len(b),
		URL: "https://github.com/" + repo + "/blob/" + sha + "/" + p,
	})
}

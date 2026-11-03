package api

import (
	"context"
	"errors"
	"testing"
)

func TestReadGitHubToken(t *testing.T) {
	env := map[string]string{}
	getenv := func(k string) string { return env[k] }
	noGH := func(string) (string, error) { return "", errors.New("not found") }
	ctx := context.Background()
	if got := readGitHubToken(ctx, getenv, noGH); got != "" {
		t.Fatalf("no token: %q", got)
	}
	env["GH_TOKEN"] = "gh-tok"
	if got := readGitHubToken(ctx, getenv, noGH); got != "gh-tok" {
		t.Fatalf("GH_TOKEN: %q", got)
	}
	env["GITHUB_TOKEN"] = " gh-first \n"
	if got := readGitHubToken(ctx, getenv, noGH); got != "gh-first" {
		t.Fatalf("GITHUB_TOKEN wins: %q", got)
	}
	// gh is run (without a shell) only when the environment has no token.
	delete(env, "GITHUB_TOKEN")
	delete(env, "GH_TOKEN")
	fake := func(string) (string, error) { return "/bin/echo", nil }
	if got := readGitHubToken(ctx, getenv, fake); got != "auth token" {
		t.Fatalf("gh fallback: %q", got)
	}
}

func TestSourceFetcherTokenHosts(t *testing.T) {
	if f := newSourceFetcher(Config{}); !f.sendToken || f.base != DefaultGitHubRawURL {
		t.Fatalf("default: %+v", f)
	}
	if f := newSourceFetcher(Config{GitHubRawURL: "http://127.0.0.1:1/"}); !f.sendToken || f.base != "http://127.0.0.1:1" {
		t.Fatalf("injected: %+v", f)
	}
}

func TestLanguageHint(t *testing.T) {
	for p, want := range map[string]string{
		"a/b.go": "go", "x.py": "python", "k.cu": "cuda", "k.cuh": "cuda", "a.cc": "cpp", "a.h": "c",
		"a.tsx": "tsx", "a.ts": "typescript", "lib.rs": "rust", "A.java": "java", "c.yml": "yaml",
		"d.json": "json", "README.md": "markdown", "q.sql": "sql", "run.sh": "shell", "main.tf": "hcl",
		"api.proto": "protobuf", "Dockerfile": "dockerfile", "docker/Dockerfile.cpu": "dockerfile", "LICENSE": "",
	} {
		if got := languageHint(p); got != want {
			t.Errorf("languageHint(%q) = %q, want %q", p, got, want)
		}
	}
}

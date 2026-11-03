package main

import (
	"bytes"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

const (
	exampleOnt  = "gateway"
	examplePath = "../../internal/testdata/gateway/ontology.yaml"
)

func TestMain(m *testing.M) {
	// Keep the developer's MOSAIC_SERVER and MOSAIC_TOKEN out of the tests.
	getenv = func(string) string { return "" }
	os.Exit(m.Run())
}

// cli runs the CLI against f (when not nil) and returns stdout, stderr and the exit code.
func cli(t *testing.T, f *fakeServer, args ...string) (string, string, int) {
	t.Helper()
	if f != nil {
		args = append([]string{"--server", f.URL()}, args...)
	}
	var out, errb bytes.Buffer
	code := run(args, &out, &errb)
	return out.String(), errb.String(), code
}

// mustCLI runs the CLI and fails unless it exits with want.
func mustCLI(t *testing.T, f *fakeServer, want int, args ...string) (string, string) {
	t.Helper()
	out, errOut, code := cli(t, f, args...)
	if code != want {
		t.Fatalf("mosaic %s: exit %d, want %d\nstdout:\n%s\nstderr:\n%s", strings.Join(args, " "), code, want, out, errOut)
	}
	return out, errOut
}

func decode[T any](t *testing.T, s string) T {
	t.Helper()
	var v T
	if err := json.Unmarshal([]byte(s), &v); err != nil {
		t.Fatalf("output is not the expected JSON: %v\n%s", err, s)
	}
	return v
}

func closedPortURL(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := l.Addr().String()
	l.Close()
	return "http://" + addr
}

func writeFile(t *testing.T, name, content string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

func withExample(t *testing.T) *fakeServer {
	t.Helper()
	f := newFake(t)
	f.load(exampleOnt, examplePath)
	return f
}

func TestHelpAndUsage(t *testing.T) {
	out, _ := mustCLI(t, nil, 0, "help")
	for _, want := range []string{"mosaic sim run <ont>", "mosaic test <ont>", "exit codes", "MOSAIC_SERVER"} {
		if !strings.Contains(out, want) {
			t.Errorf("help lacks %q", want)
		}
	}
	if out2, _ := mustCLI(t, nil, 0, "--help"); out2 != out {
		t.Error("--help differs from help")
	}
	out, _ = mustCLI(t, nil, 0, "sim", "run", "--help")
	for _, want := range []string{"usage: mosaic sim run", "--fault TARGET:TYPE", "--choice KEY=OPTION", "--no-save"} {
		if !strings.Contains(out, want) {
			t.Errorf("sim run --help lacks %q:\n%s", want, out)
		}
	}
	if out2, _ := mustCLI(t, nil, 0, "help", "sim", "run"); out2 != out {
		t.Error("help sim run differs from sim run --help")
	}
	out, _ = mustCLI(t, nil, 0, "ontology", "--help")
	if !strings.Contains(out, "mosaic ontology delete <ont> --yes") {
		t.Errorf("group help:\n%s", out)
	}
	mustCLI(t, nil, 0, "help", "revision")
	mustCLI(t, nil, 0, "put", "-h")

	for _, tc := range []struct {
		args []string
		want string
	}{
		{nil, "usage: mosaic"},
		{[]string{"frobnicate"}, `unknown command "frobnicate"`},
		{[]string{"ontology"}, "ontology needs a subcommand"},
		{[]string{"ontology", "rename"}, `unknown ontology command "rename"`},
		{[]string{"help", "nope"}, `unknown command "nope"`},
		{[]string{"--bogus", "health"}, "flag provided but not defined: -bogus"},
		{[]string{"health", "extra"}, `unexpected argument "extra"`},
		{[]string{"ontology", "get"}, "missing <ont>"},
		{[]string{"get", "o"}, "missing <ont> <kind>"},
		{[]string{"get", "o", "widgets"}, `unknown kind "widgets"`},
		{[]string{"--server", "localhost:7878", "health"}, "--server must be an http(s) URL"},
		{[]string{"validate", "o", "--rev", "head"}, "--rev must be draft, latest or a revision number"},
		{[]string{"diff", "o", "--from", "0"}, "--from must be draft, latest or a revision number"},
		{[]string{"doc", "export", "o", "--format", "xml"}, "--format must be json or yaml"},
		{[]string{"doc", "import", "o"}, "missing -f FILE"},
		{[]string{"apply", "o", "-f", "x.yaml"}, "missing -m MSG"},
		{[]string{"put", "o", "component"}, "missing -f FILE or --json JSON"},
		{[]string{"put", "o", "component", "-f", "a", "--json", "{}"}, "not both"},
		{[]string{"ontology", "create", "o"}, "--name is required"},
		{[]string{"ontology", "create", "Bad.Id", "--name", "x"}, "is not a slug"},
		{[]string{"ontology", "update", "o"}, "nothing to update"},
		{[]string{"ontology", "delete", "o"}, "without --yes"},
		{[]string{"revision", "get", "o", "two"}, "revision number must be a positive integer"},
		{[]string{"revision", "create", "o"}, "missing -m MSG"},
		{[]string{"sim", "run", "o"}, "give --flow F or --scenario S"},
		{[]string{"sim", "run", "o", "--flow", "f", "--format", "yaml"}, "--format must be summary or trace or json"},
		{[]string{"sim", "run", "o", "--flow", "f", "--seed", "x"}, `want an integer, got "x"`},
		{[]string{"sim", "run", "o", "--flow", "f", "--fault", "db"}, "want TARGET:TYPE"},
		{[]string{"sim", "run", "o", "--flow", "f", "--choice", "nokey"}, "want KEY=OPTION"},
		{[]string{"sim", "run", "o", "--flow", "f", "--state", "novalue"}, "want COMPONENT.PATH=VALUE"},
		{[]string{"sim", "run", "o", "--flow", "f", "--input", "{oops"}, "--input: invalid JSON"},
		{[]string{"sim", "run", "o", "--flow", "f", "--input", "@/does/not/exist.yaml"}, "no such file"},
		{[]string{"sim", "list", "o", "--limit", "-1"}, "--limit must not be negative"},
		{[]string{"test", "o", "--format", "summary"}, "--format must be text or json"},
		{[]string{"update"}, "without --yes"},
		{[]string{"version", "--format", "yaml"}, "--format must be text or json"},
		{[]string{"version", "extra"}, `unexpected argument "extra"`},
	} {
		// Usage errors are detected before any request: point at a closed port.
		args := append([]string{"--server", "http://127.0.0.1:9"}, tc.args...)
		if tc.args == nil {
			args = nil
		}
		out, errOut, code := cli(t, nil, args...)
		if code != 2 {
			t.Errorf("mosaic %s: exit %d, want 2\nstderr: %s", strings.Join(tc.args, " "), code, errOut)
			continue
		}
		if !strings.Contains(errOut, tc.want) {
			t.Errorf("mosaic %s: stderr lacks %q:\n%s", strings.Join(tc.args, " "), tc.want, errOut)
		}
		if !strings.HasPrefix(errOut, "mosaic: ") && tc.args != nil {
			t.Errorf("mosaic %s: stderr does not start with \"mosaic: \": %q", strings.Join(tc.args, " "), errOut)
		}
		if out != "" {
			t.Errorf("mosaic %s: usage error printed to stdout: %s", strings.Join(tc.args, " "), out)
		}
	}
}

func TestUnreachableExit3(t *testing.T) {
	url := closedPortURL(t)
	for _, args := range [][]string{
		{"health"},
		{"ontology", "list"},
		{"sim", "run", "o", "--scenario", "s"},
		{"test", "o"},
	} {
		out, errOut, code := cli(t, nil, append([]string{"--server", url}, args...)...)
		if code != 3 {
			t.Errorf("mosaic %s: exit %d, want 3 (%s)", strings.Join(args, " "), code, errOut)
		}
		if !strings.HasPrefix(errOut, "mosaic: cannot reach mosaicd at "+url) || out != "" {
			t.Errorf("mosaic %s: stdout %q stderr %q", strings.Join(args, " "), out, errOut)
		}
	}
	// --server after the command and MOSAIC_SERVER both work.
	if _, _, code := cli(t, nil, "health", "--server", url); code != 3 {
		t.Errorf("--server after the command: exit %d", code)
	}
	getenv = func(k string) string {
		if k == "MOSAIC_SERVER" {
			return url
		}
		return ""
	}
	defer func() { getenv = func(string) string { return "" } }()
	if _, _, code := cli(t, nil, "health"); code != 3 {
		t.Errorf("MOSAIC_SERVER: exit %d", code)
	}
}

func TestHealthAndToken(t *testing.T) {
	f := newFake(t)
	out, _ := mustCLI(t, f, 0, "health")
	if h := decode[api.Health](t, out); h.Status != "ok" {
		t.Errorf("health = %+v", h)
	}
	if !strings.HasPrefix(out, "{\n  \"status\": \"ok\"") {
		t.Errorf("output is not indented JSON:\n%s", out)
	}

	f.setToken("s3cret")
	_, errOut := mustCLI(t, f, 1, "health")
	if !strings.Contains(errOut, "mosaic: a valid bearer token is required (unauthorized, HTTP 401)") {
		t.Errorf("stderr = %q", errOut)
	}
	mustCLI(t, f, 0, "--token", "s3cret", "health")
	mustCLI(t, f, 0, "health", "--token", "s3cret")
	getenv = func(k string) string {
		if k == "MOSAIC_TOKEN" {
			return "s3cret"
		}
		return ""
	}
	defer func() { getenv = func(string) string { return "" } }()
	mustCLI(t, f, 0, "health")
}

func TestTimeout(t *testing.T) {
	f := newFake(t)
	mustCLI(t, f, 0, "--timeout", "10m", "health")
	mustCLI(t, f, 0, "health", "--timeout", "90s")
	if _, errOut := mustCLI(t, f, 2, "health", "--timeout", "0s"); !strings.Contains(errOut, "--timeout must be a positive duration") {
		t.Errorf("--timeout 0s: stderr = %q", errOut)
	}
	if _, _, code := cli(t, f, "health", "--timeout", "soon"); code != 2 {
		t.Errorf("--timeout soon: exit %d, want 2", code)
	}
	getenv = func(k string) string {
		if k == "MOSAIC_TIMEOUT" {
			return "nope"
		}
		return ""
	}
	defer func() { getenv = func(string) string { return "" } }()
	if _, errOut, code := cli(t, f, "health"); code != 2 || !strings.Contains(errOut, "MOSAIC_TIMEOUT must be a positive duration") {
		t.Errorf("MOSAIC_TIMEOUT=nope: exit %d, stderr %q", code, errOut)
	}
}

func TestOntologyCommands(t *testing.T) {
	f := newFake(t)
	out, _ := mustCLI(t, f, 0, "ontology", "list")
	if strings.TrimSpace(out) != "[]" {
		t.Errorf("empty list = %s", out)
	}
	out, _ = mustCLI(t, f, 0, "ontology", "create", "shop", "--name", "Shop", "--description", "A shop")
	if d := decode[api.OntologyDetail](t, out); d.ID != "shop" || d.Name != "Shop" || d.Description != "A shop" {
		t.Errorf("created = %+v", d)
	}
	_, errOut := mustCLI(t, f, 1, "ontology", "create", "shop", "--name", "Shop")
	if !strings.Contains(errOut, `ontology "shop" already exists (conflict, HTTP 409)`) {
		t.Errorf("stderr = %q", errOut)
	}
	out, _ = mustCLI(t, f, 0, "ontology", "list")
	if l := decode[[]api.OntologySummary](t, out); len(l) != 1 || l[0].ID != "shop" {
		t.Errorf("list = %+v", l)
	}
	out, _ = mustCLI(t, f, 0, "ontology", "update", "shop", "--name", "Shop 2")
	if d := decode[api.OntologyDetail](t, out); d.Name != "Shop 2" || d.Description != "A shop" {
		t.Errorf("updated = %+v", d)
	}
	if !strings.Contains(f.raw(), `"name":"Shop 2"`) || strings.Contains(f.raw(), "description") {
		t.Errorf("PATCH body = %s", f.raw())
	}
	mustCLI(t, f, 0, "ontology", "update", "shop", "--description", "")
	if f.raw() != `{"description":""}` {
		t.Errorf("an explicit empty description must be sent: %s", f.raw())
	}
	out, _ = mustCLI(t, f, 0, "ontology", "get", "shop")
	if d := decode[api.OntologyDetail](t, out); d.Counts["component"] != 0 || d.Name != "Shop 2" {
		t.Errorf("detail = %+v", d)
	}
	out, _ = mustCLI(t, f, 0, "ontology", "delete", "shop", "--yes")
	if strings.ReplaceAll(out, " ", "") != "{\n\"deleted\":true,\n\"id\":\"shop\"\n}\n" {
		t.Errorf("delete output = %q", out)
	}
	_, errOut = mustCLI(t, f, 1, "ontology", "get", "shop")
	if !strings.Contains(errOut, `mosaic: ontology "shop" not found (not_found, HTTP 404)`) {
		t.Errorf("stderr = %q", errOut)
	}
}

func TestDocImportExport(t *testing.T) {
	f := newFake(t)
	mustCLI(t, f, 0, "ontology", "create", exampleOnt, "--name", "Gateway")
	out, errOut := mustCLI(t, f, 0, "doc", "import", exampleOnt, "-f", examplePath)
	res := decode[api.PutDocumentResult](t, out)
	if !res.Valid || res.Counts["component"] != 20 || res.Counts["scenario"] != 14 || errOut != "" {
		t.Errorf("import = %+v, stderr %q", res, errOut)
	}
	if f.lastRequest() != "PUT /v1/ontologies/gateway/document" {
		t.Errorf("request = %s", f.lastRequest())
	}

	out, _ = mustCLI(t, f, 0, "doc", "export", exampleOnt)
	doc, err := model.ParseDocument([]byte(out))
	if err != nil {
		t.Fatalf("export does not parse: %v", err)
	}
	if len(doc.Interfaces) != 20 || len(doc.Scenarios) != 14 {
		t.Errorf("exported %d interfaces, %d scenarios", len(doc.Interfaces), len(doc.Scenarios))
	}
	if strings.Contains(out, `\u0026`) || !strings.Contains(out, "&&") {
		t.Error("CEL expressions should not be HTML-escaped")
	}

	yamlPath := filepath.Join(t.TempDir(), "doc.yaml")
	out, _ = mustCLI(t, f, 0, "doc", "export", exampleOnt, "--format", "yaml", "-o", yamlPath, "--rev", "draft")
	if out != "" {
		t.Errorf("export -o printed %q", out)
	}
	if f.lastRequest() != "GET /v1/ontologies/gateway/document?rev=draft" {
		t.Errorf("request = %s", f.lastRequest())
	}
	data, err := os.ReadFile(yamlPath)
	if err != nil {
		t.Fatal(err)
	}
	if strings.HasPrefix(strings.TrimSpace(string(data)), "{") {
		t.Fatal("expected YAML, got JSON")
	}
	ydoc, err := model.ParseDocument(data)
	if err != nil || len(ydoc.Components) != 20 {
		t.Fatalf("YAML export: %v", err)
	}

	// Re-importing the export is lossless enough to stay valid.
	out, _ = mustCLI(t, f, 0, "doc", "import", exampleOnt, "--file", yamlPath)
	if !decode[api.PutDocumentResult](t, out).Valid {
		t.Error("re-import of the YAML export is invalid")
	}

	// An invalid document still replaces the draft: exit 0, issues on stderr.
	bad := writeFile(t, "bad.yaml", "components:\n  - id: a\n    parent: ghost\n")
	out, errOut = mustCLI(t, f, 0, "doc", "import", exampleOnt, "-f", bad)
	if decode[api.PutDocumentResult](t, out).Valid {
		t.Error("expected an invalid result")
	}
	if !strings.Contains(errOut, "was replaced but does not validate") || !strings.Contains(errOut, "components") {
		t.Errorf("stderr = %q", errOut)
	}

	// A strictly-invalid document is refused by the server: exit 1.
	unknown := writeFile(t, "unknown.json", `{"schema_version":1,"widgets":[]}`)
	_, errOut = mustCLI(t, f, 1, "doc", "import", exampleOnt, "-f", unknown)
	if !strings.Contains(errOut, "(bad_request, HTTP 400)") {
		t.Errorf("stderr = %q", errOut)
	}
	// Local input errors are usage errors.
	_, errOut = mustCLI(t, f, 2, "doc", "import", exampleOnt, "-f", "/no/such/file.yaml")
	if !strings.Contains(errOut, "no such file") {
		t.Errorf("stderr = %q", errOut)
	}
	badYAML := writeFile(t, "broken.yaml", "components: [\n")
	_, errOut = mustCLI(t, f, 2, "doc", "import", exampleOnt, "-f", badYAML)
	if !strings.Contains(errOut, "invalid YAML") {
		t.Errorf("stderr = %q", errOut)
	}
	_, errOut = mustCLI(t, f, 1, "doc", "export", "nope")
	if !strings.Contains(errOut, `ontology "nope" not found`) {
		t.Errorf("stderr = %q", errOut)
	}
}

func TestApply(t *testing.T) {
	f := newFake(t)
	mustCLI(t, f, 0, "ontology", "create", exampleOnt, "--name", "Gateway")
	out, _ := mustCLI(t, f, 0, "apply", exampleOnt, "-f", examplePath, "-m", "Model the gateway", "--author", "agent")
	type applyOut struct {
		Import   api.PutDocumentResult `json:"import"`
		Revision *api.Revision         `json:"revision"`
	}
	res := decode[applyOut](t, out)
	if !res.Import.Valid || res.Revision == nil || res.Revision.Number != 1 || res.Revision.Author != "agent" || res.Revision.Message != "Model the gateway" {
		t.Errorf("apply = %+v", res)
	}
	reqs := f.requests()
	if got := reqs[len(reqs)-2:]; got[0] != "PUT /v1/ontologies/gateway/document" || got[1] != "POST /v1/ontologies/gateway/revisions" {
		t.Errorf("requests = %v", got)
	}

	// Unchanged: the server refuses the revision with 409.
	_, errOut := mustCLI(t, f, 1, "apply", exampleOnt, "-f", examplePath, "-m", "again")
	if !strings.Contains(errOut, "unchanged") || !strings.Contains(errOut, "conflict, HTTP 409") {
		t.Errorf("stderr = %q", errOut)
	}

	// Invalid: no revision, issues listed one per line on stderr.
	bad := writeFile(t, "bad.json", `{"schema_version":1,"components":[{"id":"a","parent":"ghost"}],
		"links":[{"id":"l","from":"a","to":"nowhere"}]}`)
	n := len(f.requests())
	out, errOut = mustCLI(t, f, 1, "apply", exampleOnt, "-f", bad, "-m", "broken")
	if len(f.requests()) != n+1 {
		t.Errorf("an invalid apply must not create a revision: %v", f.requests()[n:])
	}
	if !strings.Contains(out, `"valid": false`) || !strings.Contains(out, `"revision": null`) {
		t.Errorf("stdout = %s", out)
	}
	lines := strings.Split(strings.TrimSpace(errOut), "\n")
	if !strings.HasPrefix(lines[0], "mosaic: the document is invalid") || len(lines) < 3 {
		t.Fatalf("stderr = %q", errOut)
	}
	for _, l := range lines[1:] {
		if !strings.HasPrefix(l, "  error   ") || !strings.Contains(l, ": ") {
			t.Errorf("issue line %q", l)
		}
	}
	if !strings.Contains(errOut, "components[a].parent") && !strings.Contains(errOut, "components[0].parent") {
		t.Errorf("stderr lacks the parent issue path: %q", errOut)
	}
}

func TestEntityCommands(t *testing.T) {
	f := withExample(t)
	const ont = exampleOnt

	// One entity: PUT /{kind}/{id}.
	out, _ := mustCLI(t, f, 0, "put", ont, "component", "--json", `{"id":"cache","name":"Cache","kind":"datastore"}`)
	if r := decode[api.UpsertResult](t, out); r.Kind != "component" || len(r.IDs) != 1 || r.IDs[0] != "cache" {
		t.Errorf("put = %+v", r)
	}
	if f.lastRequest() != "PUT /v1/ontologies/gateway/components/cache" {
		t.Errorf("request = %s", f.lastRequest())
	}
	// An interface's id comes from component + "." + name.
	mustCLI(t, f, 0, "put", ont, "interfaces", "--json", `{"component":"cache","name":"get","kind":"rpc"}`)
	if f.lastRequest() != "PUT /v1/ontologies/gateway/interfaces/cache.get" {
		t.Errorf("request = %s", f.lastRequest())
	}
	// A list and {"items": [...]}: PUT /{kind}.
	out, _ = mustCLI(t, f, 0, "put", ont, "link", "--json", `[{"id":"l1","from":"cache","to":"gateway"},{"id":"l2","from":"cache","to":"catalog"}]`)
	if r := decode[api.UpsertResult](t, out); len(r.IDs) != 2 {
		t.Errorf("put list = %+v", r)
	}
	if f.lastRequest() != "PUT /v1/ontologies/gateway/links" || !strings.HasPrefix(f.raw(), `{"items":[`) {
		t.Errorf("request = %s %s", f.lastRequest(), f.raw())
	}
	yamlItems := writeFile(t, "items.yaml", "items:\n  - id: s1\n    schema: {type: string}\n  - id: s2\n    schema: {type: integer}\n")
	out, _ = mustCLI(t, f, 0, "put", ont, "schemas", "-f", yamlItems)
	if r := decode[api.UpsertResult](t, out); len(r.IDs) != 2 || r.IDs[1] != "s2" {
		t.Errorf("put items = %+v", r)
	}
	// A YAML file with one entity, read from stdin.
	stdin = strings.NewReader("id: cache2\nname: Cache 2\n")
	defer func() { stdin = os.Stdin }()
	mustCLI(t, f, 0, "put", ont, "components", "-f", "-")
	if f.lastRequest() != "PUT /v1/ontologies/gateway/components/cache2" {
		t.Errorf("request = %s", f.lastRequest())
	}

	// get: one entity, and a list (singular and plural kinds).
	out, _ = mustCLI(t, f, 0, "get", ont, "component", "cache")
	if c := decode[model.Component](t, out); c.Name != "Cache" || c.Kind != "datastore" {
		t.Errorf("get = %+v", c)
	}
	out, _ = mustCLI(t, f, 0, "get", ont, "links")
	if l := decode[[]model.Link](t, out); len(l) != 3 {
		t.Errorf("links = %+v", l)
	}
	out, _ = mustCLI(t, f, 0, "get", ont, "flow", "--rev", "1")
	if f.lastRequest() != "GET /v1/ontologies/gateway/flows?rev=1" || len(decode[[]model.Flow](t, out)) != 1 {
		t.Errorf("request = %s", f.lastRequest())
	}
	// Flags may follow positionals or precede them.
	mustCLI(t, f, 0, "get", "--rev", "draft", ont, "interface", "cache.get")
	if f.lastRequest() != "GET /v1/ontologies/gateway/interfaces/cache.get?rev=draft" {
		t.Errorf("request = %s", f.lastRequest())
	}

	// patch: a JSON merge patch; null removes a field.
	out, _ = mustCLI(t, f, 0, "patch", ont, "component", "cache", "--json", `{"summary":"Hot keys","kind":null}`)
	if r := decode[api.UpsertResult](t, out); r.IDs[0] != "cache" {
		t.Errorf("patch = %+v", r)
	}
	out, _ = mustCLI(t, f, 0, "get", ont, "components", "cache")
	if c := decode[model.Component](t, out); c.Summary != "Hot keys" || c.Kind != "" || c.Name != "Cache" {
		t.Errorf("patched = %+v", c)
	}

	// delete.
	out, _ = mustCLI(t, f, 0, "delete", ont, "links", "l2")
	if d := decode[map[string]any](t, out); d["kind"] != "link" || d["id"] != "l2" || d["deleted"] != true {
		t.Errorf("delete = %v", d)
	}
	_, errOut := mustCLI(t, f, 1, "delete", ont, "links", "l2")
	if !strings.Contains(errOut, `link "l2" not found (not_found, HTTP 404)`) {
		t.Errorf("stderr = %q", errOut)
	}
	_, errOut = mustCLI(t, f, 1, "get", ont, "component", "ghost")
	if !strings.Contains(errOut, "not_found") {
		t.Errorf("stderr = %q", errOut)
	}
	// The server refuses specs that do not decode.
	_, errOut = mustCLI(t, f, 1, "put", ont, "component", "--json", `{"id":"x","colour":"red"}`)
	if !strings.Contains(errOut, "colour") || !strings.Contains(errOut, "bad_request") {
		t.Errorf("stderr = %q", errOut)
	}
	// Local input problems are usage errors.
	for _, tc := range []struct{ args []string }{
		{[]string{"put", ont, "component", "--json", `{"name":"no id"}`}},
		{[]string{"put", ont, "interface", "--json", `{"name":"no component"}`}},
		{[]string{"put", ont, "component", "--json", `[]`}},
		{[]string{"put", ont, "component", "--json", `{"items":[]}`}},
		{[]string{"put", ont, "component", "--json", `"just a string"`}},
		{[]string{"patch", ont, "component", "cache", "--json", `[1]`}},
	} {
		if _, errOut, code := cli(t, f, tc.args...); code != 2 || !strings.HasPrefix(errOut, "mosaic: ") {
			t.Errorf("mosaic %s: exit %d, stderr %q", strings.Join(tc.args, " "), code, errOut)
		}
	}
}

func TestValidate(t *testing.T) {
	f := withExample(t)
	out, _ := mustCLI(t, f, 0, "validate", exampleOnt)
	if v := decode[api.Validation](t, out); !v.Valid || v.Revision != "draft" || v.Issues == nil {
		t.Errorf("validate = %+v", v)
	}
	if f.lastRequest() != "POST /v1/ontologies/gateway/validate" {
		t.Errorf("request = %s", f.lastRequest())
	}
	mustCLI(t, f, 0, "put", exampleOnt, "link", "--json", `{"id":"dangling","from":"catalog","to":"nowhere"}`)
	out, errOut := mustCLI(t, f, 1, "validate", exampleOnt)
	if v := decode[api.Validation](t, out); v.Valid || len(v.Issues) == 0 {
		t.Errorf("validate = %+v", v)
	}
	if !strings.HasPrefix(errOut, "mosaic: draft of gateway is invalid") || !strings.Contains(errOut, "\n  error   links[") {
		t.Errorf("stderr = %q", errOut)
	}
	// The latest revision is still valid.
	out, _ = mustCLI(t, f, 0, "validate", exampleOnt, "--rev", "latest")
	if v := decode[api.Validation](t, out); !v.Valid || v.Revision != "1" {
		t.Errorf("validate latest = %+v", v)
	}
}

func TestRevisionCommands(t *testing.T) {
	f := withExample(t)
	out, _ := mustCLI(t, f, 0, "revision", "list", exampleOnt)
	if revs := decode[[]api.Revision](t, out); len(revs) != 1 || revs[0].Number != 1 {
		t.Errorf("revisions = %+v", revs)
	}
	_, errOut := mustCLI(t, f, 1, "revision", "create", exampleOnt, "-m", "nothing")
	if !strings.Contains(errOut, "conflict") {
		t.Errorf("stderr = %q", errOut)
	}
	mustCLI(t, f, 0, "put", exampleOnt, "component", "--json", `{"id":"cache","parent":"ghost"}`)
	_, errOut = mustCLI(t, f, 1, "revision", "create", exampleOnt, "-m", "broken")
	if !strings.Contains(errOut, "the draft does not validate (invalid, HTTP 422)") || !strings.Contains(errOut, "  error   components[") {
		t.Errorf("stderr = %q", errOut)
	}
	mustCLI(t, f, 0, "patch", exampleOnt, "component", "cache", "--json", `{"parent":null}`)
	out, _ = mustCLI(t, f, 0, "revision", "create", exampleOnt, "--message", "Add cache", "--author", "bot")
	if r := decode[api.Revision](t, out); r.Number != 2 || r.Message != "Add cache" || r.Author != "bot" {
		t.Errorf("revision = %+v", r)
	}
	out, _ = mustCLI(t, f, 0, "revision", "get", exampleOnt, "2")
	if r := decode[api.Revision](t, out); r.Number != 2 {
		t.Errorf("revision = %+v", r)
	}
	_, errOut = mustCLI(t, f, 1, "revision", "get", exampleOnt, "9")
	if !strings.Contains(errOut, "revision 9 not found") {
		t.Errorf("stderr = %q", errOut)
	}
}

func TestDiffGraphPlan(t *testing.T) {
	f := withExample(t)
	mustCLI(t, f, 0, "put", exampleOnt, "component", "--json", `{"id":"cache"}`)
	out, _ := mustCLI(t, f, 0, "diff", exampleOnt)
	if f.lastRequest() != "GET /v1/ontologies/gateway/diff?from=latest&to=draft" {
		t.Errorf("request = %s", f.lastRequest())
	}
	d := decode[api.Diff](t, out)
	if d.From != "1" || d.To != "draft" || len(d.Changes) != 1 || d.Changes[0].ID != "cache" || d.Changes[0].Change != "added" {
		t.Errorf("diff = %+v", d)
	}
	out, _ = mustCLI(t, f, 0, "diff", exampleOnt, "--from", "1", "--to", "1")
	if d := decode[api.Diff](t, out); d.Changes == nil || len(d.Changes) != 0 {
		t.Errorf("empty diff = %+v", d)
	}

	out, _ = mustCLI(t, f, 0, "graph", exampleOnt, "--rev", "1")
	g := decode[model.Graph](t, out)
	if len(g.Nodes) != 20 || len(g.Edges) == 0 {
		t.Errorf("graph has %d nodes, %d edges", len(g.Nodes), len(g.Edges))
	}
	out, _ = mustCLI(t, f, 0, "plan", exampleOnt, "chat-stream")
	p := decode[model.Plan](t, out)
	if p.Entry != "gateway.chat" || len(p.Choices) != 3 || len(p.Scenarios) != 14 {
		t.Errorf("plan = %+v", p)
	}
	_, errOut := mustCLI(t, f, 1, "plan", exampleOnt, "nope")
	if !strings.Contains(errOut, `unknown flow "nope"`) {
		t.Errorf("stderr = %q", errOut)
	}
}

func TestSimRun(t *testing.T) {
	f := withExample(t)

	// A scenario, summary format (the default).
	out, errOut := mustCLI(t, f, 0, "sim", "run", exampleOnt, "--scenario", "retry-before-commit")
	for _, want := range []string{
		"run: run_1\n",
		"simulated: flow chat-stream, scenario retry-before-commit, revision draft, seed 1\n",
		"status: ok\n",
		"outcome: ok {",
		"retries: 1\n",
		"faults: 1\n",
		"assertions: 3 of 3 passed\n",
		"  ✓ result.ok && retries == 1\n",
		"warnings: none\n",
		"client → gateway.chat\n",
		"fault error at upstream-a.chat: upstream_error",
		"retry upstream-a.chat attempt 2 on upstream_error: Upstream fails before commitment",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("summary lacks %q:\n%s", want, out)
		}
	}
	if errOut != "" {
		t.Errorf("stderr = %q", errOut)
	}

	// Overrides layered on a flow: choices, nested state, compact and JSON
	// faults, input from a YAML file, an expectation that fails: exit 1.
	input := writeFile(t, "input.yaml", "stream: false\n")
	out, errOut = mustCLI(t, f, 1, "sim", "run", exampleOnt, "--flow", "chat-stream", "--rev", "latest", "--seed", "42",
		"--choice", "policy.authorize.decision=allow",
		"--state", "ledger.free=0",
		"--state", "account-store.orgs.org-test.standing=active",
		"--state", "account-store.orgs.org-test.balance_cents=100",
		"--fault", "ledger:unavailable@1",
		"--fault", `{"target":"upstream-a.chat","type":"error","code":"upstream_error","status":502,"retryable":true,"calls":[1]}`,
		"--input", "@"+input,
		"--expect", "result.ok",
		"--expect", "retries == 7",
		"--no-save")
	req := f.sim()
	if req == nil || req.Rev != "latest" || *req.Seed != 42 || req.Save == nil || *req.Save {
		t.Fatalf("request = %+v", req)
	}
	if req.Choices["policy.authorize.decision"].Option != "allow" {
		t.Errorf("choices = %v", req.Choices)
	}
	st, _ := json.Marshal(req.State)
	if string(st) != `{"account-store":{"orgs":{"org-test":{"balance_cents":100,"standing":"active"}}},"ledger":{"free":0}}` {
		t.Errorf("state = %s", st)
	}
	if len(req.Faults) != 2 || req.Faults[0].Target != "ledger" || req.Faults[0].Type != "unavailable" || req.Faults[0].Calls[0] != 1 ||
		req.Faults[1].Status != 502 || *req.Faults[1].Retryable != true {
		t.Errorf("faults = %+v", req.Faults)
	}
	if string(req.Input) != `{"stream":false}` || len(req.Expect) != 2 {
		t.Errorf("input = %s, expect = %v", req.Input, req.Expect)
	}
	if !strings.Contains(out, "run: (not saved)") || !strings.Contains(out, "assertions: 1 of 2 passed") || !strings.Contains(out, "  ✗ retries == 7\n") {
		t.Errorf("summary:\n%s", out)
	}
	if errOut != "mosaic: 1 of 2 expectations failed\n" {
		t.Errorf("stderr = %q", errOut)
	}

	// JSON and trace formats.
	out, _ = mustCLI(t, f, 0, "sim", "run", exampleOnt, "--scenario", "happy-path", "--format", "json")
	run := decode[api.SimulationRun](t, out)
	if run.ID != "run_2" || run.Summary.Status != "ok" || len(run.Trace) == 0 || run.Scenario != "happy-path" {
		t.Errorf("run = %+v", run.Summary)
	}
	out, _ = mustCLI(t, f, 0, "sim", "run", exampleOnt, "--scenario", "happy-path", "--format", "trace")
	lines := strings.Split(strings.TrimSpace(out), "\n")
	if len(lines) != len(run.Trace) {
		t.Errorf("trace has %d lines for %d events", len(lines), len(run.Trace))
	}
	if !strings.HasPrefix(lines[0], "#1 ") || !strings.Contains(out, "set ctx.phase = ") {
		t.Errorf("trace:\n%s", out)
	}

	// An unknown scenario is a refusal.
	_, errOut = mustCLI(t, f, 1, "sim", "run", exampleOnt, "--scenario", "nope")
	if !strings.Contains(errOut, `unknown scenario "nope" (bad_request, HTTP 400)`) {
		t.Errorf("stderr = %q", errOut)
	}

	// sim list and sim get.
	out, _ = mustCLI(t, f, 0, "sim", "list", exampleOnt, "--limit", "2")
	if f.lastRequest() != "GET /v1/ontologies/gateway/simulations?limit=2" {
		t.Errorf("request = %s", f.lastRequest())
	}
	runs := decode[[]api.SimulationRun](t, out)
	if len(runs) != 2 || runs[0].ID != "run_3" || runs[1].ID != "run_2" || runs[0].Trace != nil {
		t.Errorf("runs = %+v", runs)
	}
	out, _ = mustCLI(t, f, 0, "sim", "get", "run_1")
	if f.lastRequest() != "GET /v1/simulations/run_1" || !strings.Contains(out, "scenario retry-before-commit") {
		t.Errorf("sim get:\n%s", out)
	}
	out, _ = mustCLI(t, f, 0, "sim", "get", "run_1", "--format", "json")
	if decode[api.SimulationRun](t, out).Summary.Retries != 1 {
		t.Error("sim get --format json")
	}
	_, errOut = mustCLI(t, f, 1, "sim", "get", "run_99")
	if !strings.Contains(errOut, "not_found") {
		t.Errorf("stderr = %q", errOut)
	}
}

func TestTestCommand(t *testing.T) {
	f := withExample(t)
	out, _ := mustCLI(t, f, 0, "test", exampleOnt)
	if !strings.Contains(out, "✓ happy-path — Successful stream\n") || !strings.HasSuffix(out, "14 of 14 scenarios passed, revision draft\n") {
		t.Errorf("text report:\n%s", out)
	}
	if strings.Contains(out, "✗") {
		t.Errorf("unexpected failure:\n%s", out)
	}
	out, _ = mustCLI(t, f, 0, "test", exampleOnt, "--format", "json", "--rev", "1")
	if r := decode[api.TestReport](t, out); !r.Passed || r.Total != 14 || r.Revision != "1" {
		t.Errorf("report = %+v", r)
	}

	mustCLI(t, f, 0, "put", exampleOnt, "scenario", "--json",
		`{"id":"wrong","flow":"chat-stream","name":"Wrong expectation","expect":["retries == 3","result.ok","nosuch.field == 1"]}`)
	out, errOut := mustCLI(t, f, 1, "test", exampleOnt)
	if !strings.Contains(out, "✗ wrong — Wrong expectation (status ok)\n    ✗ retries == 3\n") {
		t.Errorf("text report:\n%s", out)
	}
	if strings.Contains(out, "✗ result.ok") {
		t.Error("passing assertions of a failing scenario should not be listed")
	}
	if !strings.Contains(out, "✗ nosuch.field == 1\n        error: ") {
		t.Errorf("assertion errors should be shown:\n%s", out)
	}
	if !strings.HasSuffix(out, "14 of 15 scenarios passed, revision draft\n") || errOut != "mosaic: 1 of 15 scenarios failed\n" {
		t.Errorf("stdout tail / stderr: %q", errOut)
	}
	out, _ = mustCLI(t, f, 1, "test", exampleOnt, "--format", "json")
	if r := decode[api.TestReport](t, out); r.Passed || r.Failed != 1 {
		t.Errorf("report = %+v", r)
	}
}

func TestSimRunWorldFlags(t *testing.T) {
	f := withExample(t)
	// The example has no fixture "three", so the run is refused, but the
	// request carries every world flag.
	mustCLI(t, f, 1, "sim", "run", exampleOnt, "--flow", "chat-stream", "--no-save",
		"--fixture", "base", "--fixture", "three",
		"--topology", "node=n1, n2,n3", "--topology", "cache=c1",
		"--config", "timeout-ms=500", "--config", "mode=fast", "--config", `limits={"a":1}`,
		"--clock-epoch", "2026-10-30T00:00:00Z")
	req := f.sim()
	if req == nil {
		t.Fatal("no request")
	}
	if !reflect.DeepEqual(req.Fixtures, []string{"base", "three"}) {
		t.Errorf("fixtures = %v", req.Fixtures)
	}
	if !reflect.DeepEqual(req.Topology, map[string][]string{"node": {"n1", "n2", "n3"}, "cache": {"c1"}}) {
		t.Errorf("topology = %v", req.Topology)
	}
	cfg, _ := json.Marshal(req.Config)
	if string(cfg) != `{"limits":{"a":1},"mode":"fast","timeout-ms":500}` {
		t.Errorf("config = %s", cfg)
	}
	if req.Clock == nil || req.Clock.Epoch != "2026-10-30T00:00:00Z" {
		t.Errorf("clock = %+v", req.Clock)
	}
	mustCLI(t, f, 1, "sim", "run", exampleOnt, "--flow", "chat-stream", "--no-save", "--clock-epoch", "1700000000000", "--fixture", "x")
	if req := f.sim(); req.Clock == nil || req.Clock.EpochMS != 1700000000000 {
		t.Errorf("clock ms = %+v", req.Clock)
	}
	// Usage errors exit 2.
	mustCLI(t, f, 2, "sim", "run", exampleOnt, "--flow", "chat-stream", "--topology", "node")
	mustCLI(t, f, 2, "sim", "run", exampleOnt, "--flow", "chat-stream", "--topology", "node=a,,b")
	mustCLI(t, f, 2, "sim", "run", exampleOnt, "--flow", "chat-stream", "--config", "=1")
	mustCLI(t, f, 2, "sim", "run", exampleOnt, "--flow", "chat-stream", "--clock-epoch", "yesterday")
}

func TestConfigAndFixtureCommands(t *testing.T) {
	f := withExample(t)
	const ont = exampleOnt
	out, _ := mustCLI(t, f, 0, "put", ont, "config", "--json", `{"id":"timeout-ms","type":"integer","value":500,"default":1000}`)
	if r := decode[api.UpsertResult](t, out); r.Kind != "config" || r.IDs[0] != "timeout-ms" {
		t.Errorf("put config = %+v", r)
	}
	if f.lastRequest() != "PUT /v1/ontologies/gateway/configs/timeout-ms" {
		t.Errorf("request = %s", f.lastRequest())
	}
	fx := writeFile(t, "fx.yaml", "id: three\ntopology: {node: [n1, n2, n3]}\nconfig: {timeout-ms: 200}\nclock: {epoch: \"2026-10-30T00:00:00Z\"}\n")
	mustCLI(t, f, 0, "put", ont, "fixtures", "-f", fx)
	if f.lastRequest() != "PUT /v1/ontologies/gateway/fixtures/three" {
		t.Errorf("request = %s", f.lastRequest())
	}
	out, _ = mustCLI(t, f, 0, "get", ont, "fixture", "three")
	if got := decode[model.Fixture](t, out); len(got.Topology["node"]) != 3 || got.Clock == nil {
		t.Errorf("get fixture = %+v", got)
	}
	out, _ = mustCLI(t, f, 0, "get", ont, "configs")
	if !strings.Contains(out, `"timeout-ms"`) {
		t.Errorf("get configs:\n%s", out)
	}
	mustCLI(t, f, 0, "delete", ont, "config", "timeout-ms")
	mustCLI(t, f, 1, "get", ont, "config", "timeout-ms")
}

func TestVersionAndUpdate(t *testing.T) {
	f := newFake(t)
	out, _ := mustCLI(t, f, 0, "version")
	for _, want := range []string{"mosaicd fake at 1111111", "on main, tracking origin/main", "upstream 2222222 web: a new page (2 behind, 0 ahead)", "available: 2 new commits"} {
		if !strings.Contains(out, want) {
			t.Errorf("version lacks %q:\n%s", want, out)
		}
	}
	mustCLI(t, f, 0, "version", "--refresh")
	if got := f.lastRequest(); got != "GET /v1/system/version?refresh=1" {
		t.Errorf("--refresh sent %s", got)
	}
	v := decode[api.SystemVersion](t, func() string { o, _ := mustCLI(t, f, 0, "version", "--format", "json"); return o }())
	if v.Update.Behind != 2 || !v.Update.Available {
		t.Errorf("version json = %+v", v)
	}

	out, _ = mustCLI(t, f, 0, "update", "--yes")
	res := decode[api.SystemUpdate](t, out)
	if res.UpdatedTo != "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" || !res.Restarting {
		t.Errorf("update = %+v", res)
	}
	if got := f.lastRequest(); got != "POST /v1/system/update" {
		t.Errorf("update sent %s", got)
	}
	// Refused: exit 1 with the reason.
	if _, errOut := mustCLI(t, f, 1, "update", "--yes"); !strings.Contains(errOut, "up to date") {
		t.Errorf("refused update stderr: %s", errOut)
	}
	if out, _ := mustCLI(t, f, 0, "version"); !strings.Contains(out, "not available: up to date") {
		t.Errorf("version after update:\n%s", out)
	}
}

func TestSource(t *testing.T) {
	f := newFake(t)
	ont := "shop"
	mustCLI(t, f, 0, "ontology", "create", ont, "--name", "Shop")
	if out, _ := mustCLI(t, f, 0, "source", ont, "main.go"); out != "package main\n" {
		t.Errorf("source = %q", out)
	}
	out, _ := mustCLI(t, f, 0, "source", ont, "main.go", "--rev", "2", "--repo", "acme/lib", "--sha", "abc1234", "--format", "json")
	if got := f.lastRequest(); got != "GET /v1/ontologies/shop/source?path=main.go&repo=acme%2Flib&rev=2&sha=abc1234" {
		t.Errorf("sent %s", got)
	}
	if sf := decode[api.SourceFile](t, out); sf.Repo != "acme/lib" || sf.LanguageHint != "go" {
		t.Errorf("json = %+v", sf)
	}
	if _, errOut := mustCLI(t, f, 1, "source", ont, "nope.go"); !strings.Contains(errOut, "file not found at that commit") {
		t.Errorf("missing stderr: %s", errOut)
	}
	mustCLI(t, f, 2, "source", ont)
}

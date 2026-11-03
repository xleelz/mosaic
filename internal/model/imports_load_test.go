package model_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

// kvSubstrate names its configs without a prefix and reads them both ways.
const kvSubstrate = `id: kv
configs:
  - {id: delay-ms, type: integer, value: 5, default: 5}
  - {id: limit, type: integer, value: 3, default: 3}
  - {id: tables, type: object, value: {}, default: {}}
fixtures:
  - {id: slow, config: {delay-ms: 50}}
components: [{id: store}]
interfaces:
  - component: store
    name: get
    latency_ms: "= config['delay-ms']"
    behavior:
      - if: "!(input.t in config['tables'])"
        then: [{fail: {code: no_table, status: 400}}]
      - {return: {limit: "= config.limit", delay: "= config[\"delay-ms\"]"}}
`

func writeFiles(t *testing.T, files map[string]string) string {
	t.Helper()
	dir := t.TempDir()
	for name, body := range files {
		p := filepath.Join(dir, name)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return dir
}

// TestImportDirectory: an import naming a directory resolves to its single
// ontology document (§15.6).
func TestImportDirectory(t *testing.T) {
	dir := writeFiles(t, map[string]string{
		"subs/kv/kv.yaml":          kvSubstrate,
		"subs/kv/scenarios.yaml":   "id: kv-scenarios\n",
		"subs/one/whatever.json":   `{"id": "one"}`,
		"subs/named/ontology.yaml": "id: named\n",
		"subs/named/other.yaml":    "id: other\n",
		"subs/two/a.yaml":          "id: a\n",
		"subs/two/b.yaml":          "id: b\n",
	})
	d := &model.Document{Imports: []model.ImportRef{{Ontology: "subs/kv"}, {Ontology: "subs/one/"}, {Ontology: "subs/named"}}}
	if err := model.LoadImportFiles(d, dir, os.ReadFile); err != nil {
		t.Fatal(err)
	}
	for ref, id := range map[string]string{"subs/kv": "kv", "subs/one/": "one", "subs/named": "named"} {
		if got := d.ImportDocs[ref]; got == nil || got.ID != id {
			t.Errorf("%s: got %+v, want %s", ref, got, id)
		}
	}
	d = &model.Document{Imports: []model.ImportRef{{Ontology: "subs/two"}}}
	if err := model.LoadImportFiles(d, dir, os.ReadFile); err == nil || !strings.Contains(err.Error(), "2 documents") {
		t.Errorf("an ambiguous directory: %v", err)
	}
}

// TestImportPrefixesConfigs: an import's configs and fixtures take the as:
// prefix, references inside it follow, and a config the importer declares
// under the original id still overrides it (§15.6).
func TestImportPrefixesConfigs(t *testing.T) {
	kv := parseImportDoc(t, kvSubstrate)
	app := parseImportDoc(t, `id: app
imports: [{ontology: kv, as: cache}]
configs:
  - {id: tables, type: object, value: {t1: {}}, default: {}}
  - {id: cache/limit, type: integer, value: 9, default: 9}
  - {id: limit, type: string, value: mine, default: mine}
components: [{id: app}]
interfaces:
  - {component: app, name: read, behavior: [{call: cache/store.get, input: {t: t1}, as: r}, {return: "= vars.r.value"}]}
`)
	app.ImportDocs = map[string]*model.Document{"kv": kv}
	m, err := model.MergeImports(app, app.ImportDocs)
	if err != nil {
		t.Fatal(err)
	}
	x := model.NewIndex(m)
	if x.Configs["cache/delay-ms"] == nil || x.Configs["delay-ms"] != nil {
		t.Errorf("config not prefixed: %v", m.Configs)
	}
	if x.Configs["cache/tables"] != nil {
		t.Error("a config the importer declares was prefixed instead of overridden")
	}
	if c := x.Configs["cache/limit"]; c == nil || string(mustJSON(t, c.Value)) != "9" {
		t.Errorf("the importer's cache/limit doesn't win: %+v", c)
	}
	if fx := x.Fixtures["cache/slow"]; fx == nil || fx.Config["cache/delay-ms"] == nil {
		t.Errorf("fixture config keys not prefixed: %+v", fx)
	}
	b := string(mustJSON(t, x.Interfaces["cache/store.get"]))
	for _, want := range []string{`config['cache/delay-ms']`, `config['tables']`, `config['cache/limit']`} {
		if !strings.Contains(b, want) {
			t.Errorf("reference %s missing: %s", want, b)
		}
	}
	if strings.Contains(b, "config.limit") || strings.Contains(b, `config[\"delay-ms\"]`) {
		t.Errorf("a reference was not rewritten: %s", b)
	}
	if errs := errorsOf(model.ValidateWithImports(app)); len(errs) > 0 {
		t.Errorf("issues: %v", errs)
	}
}

func mustJSON(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

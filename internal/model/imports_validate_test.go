package model_test

import (
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

func parseImportDoc(t *testing.T, src string) *model.Document {
	t.Helper()
	d, err := model.ParseDocument([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	return d
}

// TestValidateWithImports: validation follows imports (§15.4). An error
// inside an imported document is reported under the import's alias; a
// reference into an import resolves, and a wrong one is an error.
func TestValidateWithImports(t *testing.T) {
	kv := parseImportDoc(t, `
id: kv
components: [{id: store}]
schemas: [{id: Row, schema: {type: object}}]
interfaces:
  - {component: store, name: get, response: Row, behavior: [{return: {v: 1}}]}
  - {component: store, name: put, behavior: [{call: store.missing}]}
`)
	d := parseImportDoc(t, `
id: app
imports: [{ontology: kv, as: cache}]
components: [{id: app}]
interfaces:
  - {component: app, name: read, response: cache.Row, behavior: [{call: cache/store.get}]}
  - {component: app, name: bad, behavior: [{call: cache/store.nope}]}
`)
	d.ImportDocs = map[string]*model.Document{"kv": kv}
	var aliased, bad, other []string
	for _, is := range errorsOf(model.ValidateWithImports(d)) {
		switch {
		case strings.HasPrefix(is.Path, "cache: interfaces[store.put]"):
			aliased = append(aliased, is.Path)
		case strings.HasPrefix(is.Path, "interfaces[app.bad]") && strings.Contains(is.Message, "cache/store.nope"):
			bad = append(bad, is.Path)
		default:
			other = append(other, is.Path+": "+is.Message)
		}
	}
	if len(aliased) != 1 {
		t.Errorf("the import's error is not reported under its alias once: %v", aliased)
	}
	if len(bad) != 1 {
		t.Errorf("the wrong reference into the import is not reported: %v", bad)
	}
	if len(other) > 0 {
		t.Errorf("unexpected issues: %v", other)
	}

	// Without as:, the ontology reference is the alias.
	d.Imports[0].As = ""
	d.Interfaces = d.Interfaces[:0]
	found := false
	for _, is := range errorsOf(model.ValidateWithImports(d)) {
		if strings.HasPrefix(is.Path, "kv: interfaces[store.put]") {
			found = true
		}
	}
	if !found {
		t.Error("the import's error is not reported under its ontology reference")
	}

	// An import that isn't loaded can't be followed.
	d.ImportDocs = nil
	errs := errorsOf(model.ValidateWithImports(d))
	if len(errs) == 0 || errs[0].Path != "imports[0].ontology" {
		t.Errorf("an unloaded import is not an error: %v", errs)
	}
}

// TestValidateWithImportsNested: an import's own imports are followed, and
// their issues carry both aliases.
func TestValidateWithImportsNested(t *testing.T) {
	inner := parseImportDoc(t, `
id: inner
components: [{id: disk}]
interfaces:
  - {component: disk, name: read, behavior: [{call: disk.gone}]}
`)
	mid := parseImportDoc(t, `
id: mid
imports: [{ontology: inner, as: fs}]
components: [{id: db}]
interfaces:
  - {component: db, name: get, behavior: [{call: fs/disk.read}]}
`)
	mid.ImportDocs = map[string]*model.Document{"inner": inner}
	d := parseImportDoc(t, `
id: app
imports: [{ontology: mid, as: data}]
components: [{id: app}]
interfaces:
  - {component: app, name: run, behavior: [{call: data/db.get}]}
`)
	d.ImportDocs = map[string]*model.Document{"mid": mid}
	errs := errorsOf(model.ValidateWithImports(d))
	if len(errs) != 1 || !strings.HasPrefix(errs[0].Path, "data: fs: interfaces[disk.read]") {
		t.Errorf("nested import issue: %v", errs)
	}
}

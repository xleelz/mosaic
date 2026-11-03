package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestValidateFilesFollowsImports: mosaic validate -f follows imports, on a
// -f document and on a --refine child, and reports errors inside an imported
// document under the import's alias instead of skipping them (§15.4).
func TestValidateFilesFollowsImports(t *testing.T) {
	dir := t.TempDir()
	write := func(name, body string) string {
		p := filepath.Join(dir, name)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
		return p
	}
	write("sub/kv.yaml", "id: kv\ncomponents: [{id: store}]\n"+
		"interfaces: [{component: store, name: get, behavior: [{return: {v: 1}}]}]\n")
	write("sub/broken.yaml", "id: broken\ncomponents: [{id: store}]\n"+
		"interfaces: [{component: store, name: get, behavior: [{call: store.gone}]}]\n")
	good := write("app.yaml", "id: app\nimports: [{ontology: sub/kv.yaml, as: cache}]\ncomponents: [{id: app}]\n"+
		"interfaces: [{component: app, name: read, behavior: [{call: cache/store.get}]}]\n")
	wrongRef := write("wrong.yaml", "id: app\nimports: [{ontology: sub/kv.yaml, as: cache}]\ncomponents: [{id: app}]\n"+
		"interfaces: [{component: app, name: read, behavior: [{call: cache/store.nope}]}]\n")
	broken := write("broken-app.yaml", "id: app\nimports: [{ontology: sub/broken.yaml, as: db}]\ncomponents: [{id: app}]\n"+
		"interfaces: [{component: app, name: read, behavior: [{call: db/store.get}]}]\n")
	child := write("child.yaml", "id: engine-logic\nrefines: {ontology: shop, component: engine}\n"+
		"imports: [{ontology: sub/broken.yaml, as: db}]\ncomponents: [{id: s}]\n"+
		"interfaces: [{component: s, name: go, implements: engine.run, behavior: [{call: db/store.get}, {return: {text: x}}]}]\n")
	off := []string{"--server", "http://127.0.0.1:1"}
	run := func(want int, args ...string) (fileValidation, string) {
		out, errOut := mustCLI(t, nil, want, append(off, args...)...)
		return decode[fileValidation](t, out), errOut
	}

	if v, errOut := run(0, "validate", "-f", good); !v.Valid {
		t.Errorf("a resolved import: %+v\n%s", v, errOut)
	}
	if _, errOut := run(1, "validate", "-f", wrongRef); !strings.Contains(errOut, `cache/store.nope`) {
		t.Errorf("a wrong reference into an import: %s", errOut)
	}
	if _, errOut := run(1, "validate", "-f", broken); !strings.Contains(errOut, "db: interfaces[store.get]") {
		t.Errorf("an error inside an import is not under its alias: %s", errOut)
	}
	v, errOut := run(1, "validate", "-f", refineParent, "--refine", "engine="+child)
	if v.Valid || len(v.Refinements) != 1 || v.Refinements[0].Valid ||
		!strings.Contains(errOut, child+": db: interfaces[store.get]") || !strings.Contains(errOut, `store.gone`) {
		t.Errorf("an error inside a child's import: %+v\n%s", v, errOut)
	}

	// A directory import, its configs under the prefix.
	write("subs/kv/kv.yaml", "id: kv\nconfigs: [{id: delay-ms, type: integer, value: 5, default: 5}]\ncomponents: [{id: store}]\n"+
		"interfaces: [{component: store, name: get, latency_ms: \"= config['delay-ms']\", behavior: [{return: {v: 1}}]}]\n")
	write("subs/kv/scenarios.yaml", "id: kv-scenarios\n")
	dirApp := write("dir-app.yaml", "id: app\nimports: [{ontology: subs/kv, as: cache}]\n"+
		"configs: [{id: cache/delay-ms, type: integer, value: 9, default: 9}]\ncomponents: [{id: app}]\n"+
		"interfaces: [{component: app, name: read, behavior: [{call: cache/store.get}]}]\n")
	if v, errOut := run(0, "validate", "-f", dirApp); !v.Valid {
		t.Errorf("a directory import with a prefixed config override: %+v\n%s", v, errOut)
	}
}

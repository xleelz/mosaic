package model

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Import resolution and config prefixing for substrate imports (§15.6).

// resolveImportPath turns an import's ontology reference into a document
// file: the path relative to dir (the importing document's directory), else
// relative to the working directory. A directory resolves to its single
// ontology document: ontology.{yaml,yml,json}, else <dir name>.{yaml,yml,
// json}, else the only .yaml, .yml or .json file in it. ok is false when
// nothing matches (a store id, for a store-backed loader).
func resolveImportPath(ref, dir string) (string, bool, error) {
	cands := []string{ref}
	if !filepath.IsAbs(ref) {
		cands = []string{filepath.Join(dir, ref), ref}
	}
	for _, p := range cands {
		st, err := os.Stat(p)
		if err != nil {
			if errors.Is(err, fs.ErrNotExist) {
				continue
			}
			return "", false, err
		}
		if !st.IsDir() {
			return p, true, nil
		}
		f, err := ontologyInDir(p)
		if err != nil {
			return "", false, fmt.Errorf("import %q: %w", ref, err)
		}
		return f, true, nil
	}
	return "", false, nil
}

func ontologyInDir(dir string) (string, error) {
	base := filepath.Base(filepath.Clean(dir))
	for _, name := range []string{"ontology", base} {
		for _, ext := range []string{".yaml", ".yml", ".json"} {
			p := filepath.Join(dir, name+ext)
			if st, err := os.Stat(p); err == nil && !st.IsDir() {
				return p, nil
			}
		}
	}
	ents, err := os.ReadDir(dir)
	if err != nil {
		return "", err
	}
	var docs []string
	for _, e := range ents {
		switch strings.ToLower(filepath.Ext(e.Name())) {
		case ".yaml", ".yml", ".json":
			if !e.IsDir() {
				docs = append(docs, e.Name())
			}
		}
	}
	switch len(docs) {
	case 1:
		return filepath.Join(dir, docs[0]), nil
	case 0:
		return "", fmt.Errorf("directory %s holds no ontology document", dir)
	}
	sort.Strings(docs)
	return "", fmt.Errorf("directory %s holds %d documents (%s): name one, or call it ontology.yaml", dir, len(docs), strings.Join(docs, ", "))
}

var reConfigDot = regexp.MustCompile(`\bconfig\.([A-Za-z_][A-Za-z0-9_]*)`)

// prefixImportConfigs renames an import's configs under "<as>/" (§15.6) and
// rewrites the references to them inside the import: config['<id>'] (and
// "<id>", and config.<id>) in its expressions, and its fixtures' config
// keys. The importing document (out) overrides an imported config by
// declaring "<as>/<id>"; failing that, a config it declares under the
// import's own id keeps that id, so the local value overrides the import's
// as before. src is a clone the caller owns.
func prefixImportConfigs(src, out *Document, as string) (*Document, error) {
	if as == "" || len(src.Configs) == 0 {
		return src, nil
	}
	local := map[string]bool{}
	for _, c := range out.Configs {
		local[c.ID] = true
	}
	ren := map[string]string{}
	for _, c := range src.Configs {
		if n := as + "/" + c.ID; local[n] || !local[c.ID] {
			ren[c.ID] = n
		}
	}
	if len(ren) == 0 {
		return src, nil
	}
	b, err := json.Marshal(src)
	if err != nil {
		return nil, err
	}
	text := string(b)
	ids := make([]string, 0, len(ren))
	for id := range ren {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(a, b int) bool { return len(ids[a]) > len(ids[b]) })
	var pairs []string
	for _, id := range ids {
		n := ren[id]
		pairs = append(pairs, "config['"+id+"']", "config['"+n+"']", `config[\"`+id+`\"]`, `config[\"`+n+`\"]`)
	}
	text = strings.NewReplacer(pairs...).Replace(text)
	text = reConfigDot.ReplaceAllStringFunc(text, func(m string) string {
		if n, ok := ren[m[len("config."):]]; ok {
			return "config['" + n + "']"
		}
		return m
	})
	var res Document
	if err := Decode([]byte(text), &res); err != nil {
		return nil, err
	}
	for i := range res.Interfaces {
		res.Interfaces[i].Normalize()
	}
	for i := range res.Configs {
		if n, ok := ren[res.Configs[i].ID]; ok {
			res.Configs[i].ID = n
		}
	}
	for i := range res.Fixtures {
		f := &res.Fixtures[i]
		if f.Config == nil {
			continue
		}
		m := map[string]any{}
		for k, v := range f.Config {
			if n, ok := ren[k]; ok {
				k = n
			}
			m[k] = v
		}
		f.Config = m
	}
	res.EnsureSlices()
	res.Refinements, res.ImportDocs = src.Refinements, src.ImportDocs
	return &res, nil
}

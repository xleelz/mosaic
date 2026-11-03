package model

import (
	"fmt"
	"strings"
)

// ValidateWithImports validates d and follows its imports (§15.4):
//   - each loaded import is validated on its own, recursively, and its
//     issues are reported under the import's alias: "<as>: <path>", or the
//     ontology reference when the import gives no as;
//   - d is validated with its loaded imports merged in, so references into an
//     import ("<as>/<component>", "<as>.<schema>") resolve. Issues located
//     inside an imported entity belong to the import and are not repeated
//     (nor are the merge's prefixed ids, which the composer allows, issues).
//
// An import that is not loaded is an error at "imports[i]": it can't be
// followed. Without imports, this is Validate(d).
func ValidateWithImports(d *Document) []Issue {
	return validateWithImports(d, 0)
}

func validateWithImports(d *Document, depth int) []Issue {
	if len(d.Imports) == 0 {
		return Validate(d)
	}
	if depth > 16 {
		return []Issue{{Path: "imports", Message: "imports nest too deep", Severity: SeverityError}}
	}
	var out, missing []Issue
	for i, im := range d.Imports {
		sub := d.ImportDocs[im.Ontology]
		if sub == nil {
			if im.Ontology != "" {
				missing = append(missing, Issue{Path: fmt.Sprintf("imports[%d].ontology", i), Severity: SeverityError,
					Message: fmt.Sprintf("import %q is not loaded: it names no readable document file or stored ontology", im.Ontology)})
			}
			continue
		}
		alias := im.As
		if alias == "" {
			alias = im.Ontology
		}
		for _, is := range validateWithImports(sub, depth+1) {
			is.Path = strings.TrimSuffix(alias+": "+is.Path, ": ")
			out = append(out, is)
		}
	}
	if len(missing) > 0 {
		// The merge needs every import: validate the document on its own.
		return append(append(missing, Validate(d)...), out...)
	}
	merged, err := MergeImports(d, d.ImportDocs)
	if err != nil {
		return append(append([]Issue{{Path: "imports", Message: err.Error(), Severity: SeverityError}}, Validate(d)...), out...)
	}
	own := entityPaths(d)
	var mine []Issue
	for _, is := range Validate(merged) {
		if head, ok := entityHead(is.Path); ok && !own[head] {
			continue // inside an imported entity: the import's own issue
		}
		mine = append(mine, is)
	}
	return append(mine, out...)
}

// entityPaths lists "<kinds>[<id>]" for each entity of d.
func entityPaths(d *Document) map[string]bool {
	out := map[string]bool{}
	for _, c := range d.Components {
		out["components["+c.ID+"]"] = true
	}
	for i := range d.Interfaces {
		f := &d.Interfaces[i]
		id := f.ID
		if id == "" {
			id = f.Component + "." + f.Name
		}
		out["interfaces["+id+"]"] = true
	}
	for _, l := range d.Links {
		out["links["+l.ID+"]"] = true
	}
	for _, s := range d.Schemas {
		out["schemas["+s.ID+"]"] = true
	}
	for _, c := range d.Configs {
		out["configs["+c.ID+"]"] = true
	}
	for _, f := range d.Fixtures {
		out["fixtures["+f.ID+"]"] = true
	}
	return out
}

// entityHead returns an issue path's leading "<kinds>[<id>]" for the kinds
// an import merges, and whether it has one.
func entityHead(path string) (string, bool) {
	for _, k := range []string{"components[", "interfaces[", "links[", "schemas[", "configs[", "fixtures["} {
		if strings.HasPrefix(path, k) {
			if j := strings.Index(path, "]"); j > 0 {
				return path[:j+1], true
			}
		}
	}
	return "", false
}

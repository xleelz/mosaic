package merge

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/xleelz/mosaic/internal/model"
)

// LoadImports loads the imports each input names, by path relative to that
// input's file (model.LoadImportFiles), into the merged document's
// ImportDocs, so validation can follow them and a run can merge them
// (§14.11, §15.6). An import that names no file stays unloaded; validation
// reports it.
func LoadImports(inputs []Input, doc *model.Document) error {
	for _, in := range inputs {
		if in.Doc == nil || len(in.Doc.Imports) == 0 {
			continue
		}
		if err := model.LoadImportFiles(in.Doc, filepath.Dir(in.Name), os.ReadFile); err != nil {
			return fmt.Errorf("%s: %w", in.Name, err)
		}
		for k, sub := range in.Doc.ImportDocs {
			if doc.ImportDocs == nil {
				doc.ImportDocs = map[string]*model.Document{}
			}
			if doc.ImportDocs[k] == nil {
				doc.ImportDocs[k] = sub
			}
		}
	}
	return nil
}

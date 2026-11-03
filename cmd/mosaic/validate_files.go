package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

// fileValidation is the output of mosaic validate -f.
type fileValidation struct {
	Files       []string               `json:"files"`
	Valid       bool                   `json:"valid"`
	Issues      []model.Issue          `json:"issues"`
	Refinements []refinementValidation `json:"refinements,omitempty"`
}

// refinementValidation is one --refine pair: the child validated on its own
// and against the merged parent.
type refinementValidation struct {
	Component string        `json:"component"`
	File      string        `json:"file"`
	Valid     bool          `json:"valid"`
	Issues    []model.Issue `json:"issues"`
}

// validateFiles validates local documents with no server: the -f files
// merged as the check tool merges them, then each --refine child.
func validateFiles(e *env, files, refines []string) error {
	type pair struct{ comp, file string }
	var pairs []pair
	for _, r := range refines {
		comp, file, ok := strings.Cut(r, "=")
		comp, file = strings.TrimSpace(comp), strings.TrimSpace(file)
		if !ok || comp == "" || file == "" {
			return usageErrorf("--refine wants COMPONENT=CHILD_FILE, got %q", r)
		}
		pairs = append(pairs, pair{comp, file})
	}
	inputs, err := merge.Load(files)
	if err != nil {
		var pe *merge.ParseError
		if errors.As(err, &pe) {
			return inputErrorf("%s: %v", pe.Path, pe.Err)
		}
		return inputErrorf("%v", err)
	}
	res, err := merge.Merge(inputs)
	if err != nil {
		return inputErrorf("%v", err)
	}
	out := fileValidation{Files: files, Issues: []model.Issue{}}
	for _, c := range res.Conflicts {
		out.Issues = append(out.Issues, model.Issue{Message: "conflict: " + c, Severity: model.SeverityError})
	}
	out.Issues = append(out.Issues, res.Issues...)
	if err := merge.LoadImports(inputs, res.Doc); err != nil {
		return inputErrorf("%v", err)
	}
	out.Issues = append(out.Issues, model.ValidateWithImports(res.Doc)...)
	errs := errorIssues(out.Issues)
	for _, p := range pairs {
		rv := refinementValidation{Component: p.comp, File: p.file, Issues: []model.Issue{}}
		child, err := loadChild(p.file)
		if err != nil {
			return err
		}
		if child.Refines != nil && child.Refines.Component != p.comp {
			rv.Issues = append(rv.Issues, model.Issue{Path: "refines.component", Severity: model.SeverityError,
				Message: fmt.Sprintf("the child refines %q, not %q", child.Refines.Component, p.comp)})
		}
		rv.Issues = append(rv.Issues, model.ValidateWithImports(child)...)
		rv.Issues = append(rv.Issues, model.ValidateRefinement(res.Doc, child)...)
		cerrs := errorIssues(rv.Issues)
		rv.Valid = len(cerrs) == 0
		for _, is := range cerrs {
			is.Path = strings.TrimSuffix(p.file+": "+is.Path, ": ")
			errs = append(errs, is)
		}
		out.Refinements = append(out.Refinements, rv)
	}
	out.Valid = len(errs) == 0
	if err := printJSON(e.stdout, out); err != nil {
		return err
	}
	if !out.Valid {
		return &exitError{code: exitRefused, issues: errs, msg: fmt.Sprintf("%s is invalid (%d errors):", strings.Join(files, ", "), len(errs))}
	}
	return nil
}

// loadChild parses a refinement child and loads the imports it names by
// path, relative to its directory (§14.11).
func loadChild(path string) (*model.Document, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, inputErrorf("%v", err)
	}
	d, err := model.ParseDocument(data)
	if err != nil {
		return nil, inputErrorf("%s: %v", path, err)
	}
	if err := model.LoadImportFiles(d, filepath.Dir(path), os.ReadFile); err != nil {
		return nil, inputErrorf("%s: %v", path, err)
	}
	return d, nil
}

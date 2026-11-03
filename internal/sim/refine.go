package sim

import (
	"fmt"

	"github.com/xleelz/mosaic/internal/model"
)

// compose prepares the document a run uses (§14.5, §14.11): its loaded
// imports merged, and each component the resolution refines replaced by its
// child ontology. The resolution is the scenario's with the request's on
// top. A document without imports or refined components runs as is.
func compose(doc *model.Document, req Request) (*model.Document, map[string]string, error) {
	res := map[string]string{}
	if req.Scenario != "" {
		for i := range doc.Scenarios {
			if doc.Scenarios[i].ID == req.Scenario {
				for k, v := range doc.Scenarios[i].Resolution {
					res[k] = v
				}
				break
			}
		}
	}
	for k, v := range req.Resolution {
		res[k] = v
	}
	if len(res) == 0 {
		res = nil
	}
	if !model.HasRefined(res) && len(doc.ImportDocs) == 0 {
		for k, v := range res {
			if v != model.ResolutionBlackBox && v != model.ResolutionRefined {
				return nil, nil, &RequestError{fmt.Sprintf("resolution of %q must be black_box or refined, got %q", k, v)}
			}
		}
		return doc, res, nil
	}
	out, err := model.ComposeRefinements(doc, model.CollectRefinements(doc), res)
	if err != nil {
		return nil, nil, &RequestError{err.Error()}
	}
	return out, res, nil
}

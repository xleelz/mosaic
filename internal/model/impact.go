package model

// ImpactSet lists entity ids that were added, removed or modified between two
// documents.
type ImpactSet struct {
	Added    []string `json:"added"`
	Removed  []string `json:"removed"`
	Modified []string `json:"modified"`
	Cited    []string `json:"cited"` // only citations changed (e.g. re-anchored lines); not counted as modified
}

// FlowImpact is a flow whose own definition is unchanged but whose reach (the
// interfaces and components it calls) contains changed entities.
type FlowImpact struct {
	Flow    string   `json:"flow"`
	Reasons []string `json:"reasons"` // changed entities inside the flow's reach, as "<kind>:<id>"
	// Basis is how the reach was found: "traces" (the interfaces the flow's
	// scenarios call when simulated, see internal/impact) or "static" (every
	// call, emit and declared dynamic target, for a flow with no scenarios).
	Basis string `json:"basis"`
}

// Impact is what changed between two versions of an ontology, and which flows
// that touches. It is the basis of the per-commit before/after views.
type Impact struct {
	Components    ImpactSet    `json:"components"`
	Interfaces    ImpactSet    `json:"interfaces"`
	Links         ImpactSet    `json:"links"`
	Schemas       ImpactSet    `json:"schemas"`
	Flows         ImpactSet    `json:"flows"` // flow entities themselves
	Scenarios     ImpactSet    `json:"scenarios"`
	Configs       ImpactSet    `json:"configs"`        // §11.6
	Fixtures      ImpactSet    `json:"fixtures"`       // §11.7
	FlowsAffected []FlowImpact `json:"flows_affected"` // unchanged flows that reach changed entities
}

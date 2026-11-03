package main

import (
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

// TestReachFollowsPublish makes subscribers of a published topic, and the
// interfaces of multi-step scenario steps, reachable for coverage.
func TestReachFollowsPublish(t *testing.T) {
	doc, err := model.ParseDocument([]byte(`
schema_version: 1
components: [{id: a}, {id: b}, {id: c}]
interfaces:
  - {component: a, name: go, behavior: [{publish: changed, delivery: sync}]}
  - {component: b, name: on-changed, subscribe: [changed]}
  - {component: c, name: poke}
flows: [{id: f, entry: {caller: a, interface: a.go}}]
scenarios:
  - id: s
    steps: [{flow: f}, {interface: c.poke, caller: a}]
`))
	if err != nil {
		t.Fatal(err)
	}
	r := reachableEntities(doc)
	for _, k := range []string{"interface:b.on-changed", "component:b", "interface:c.poke"} {
		if !r[k] {
			t.Errorf("%s not reachable", k)
		}
	}
}

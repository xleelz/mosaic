package sim_test

import (
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §17 item 6: in a store update value {$null: true} sets a field to
// JSON null, {$absent: true} removes it, and a literal null (or an
// expression giving null) changes nothing. The same holds inside a
// transact's update.
const updateNullDoc = `
components:
  - {id: client}
  - {id: db, state: {initial: {rows: {a: {x: 1, y: 2, z: 3, w: 4, meta: {k: 1, j: 2}}}}}}
interfaces:
  - component: db
    name: patch
    store:
      table: rows
      op: update
      key: "= input.id"
      value: {x: {$null: true}, y: {$absent: true}, z: null, w: "= null", meta: {k: {$null: true}}}
  - component: db
    name: tx
    latency_ms: 0
    behavior:
      - transact:
          - {table: rows, op: update, key: a, value: {x: {$null: true}, y: null}}
flows:
  - {id: patch, entry: {caller: client, interface: db.patch, input: {id: a}}}
  - {id: tx, entry: {caller: client, interface: db.tx}}
scenarios:
  - id: null-markers
    flow: patch
    expect:
      - "state.db.rows.a == {'x': null, 'z': 3, 'w': 4, 'meta': {'k': null, 'j': 2}}"
  - id: null-in-transact
    flow: tx
    expect:
      - "state.db.rows.a.x == null"
      - "state.db.rows.a.y == 2"
`

func TestUpdateNullMarkers(t *testing.T) {
	doc := langDoc(t, updateNullDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

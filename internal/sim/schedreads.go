package sim

import (
	"encoding/json"
	"regexp"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// Read footprints for partial-order reduction (DESIGN §16.2): reads of
// keys that no other task writes commute.
//
//   - Events whose key is only looked up (a latency_by_outcome entry, a
//     choice point, a route pattern) read the key; they no longer count
//     as writes, so two tasks that both take latency_by_outcome[0] or the
//     same route commute.
//   - A component whose only state is its store tables (no declared
//     state, capacity or limits, no faults in the run, and no behavior or
//     store template that mentions state) is tracked per row: a get reads
//     its row, a query reads its table, and a write writes its row. Work
//     that reads rows nobody writes commutes with other work in the
//     component.

// Kinds of component footprint.
const (
	xpNone  = iota // nothing another task can see
	xpWhole        // any work in it may write it
	xpKeyed        // store rows, tracked per key
)

// xpReadOnly lists the event types whose Key is only looked up.
var xpReadOnly = map[string]bool{"latency": true, "choice": true, "route": true}

var stateWord = regexp.MustCompile(`\bstate\b`)

// xpKeyedOnly returns xpKeyed when nothing but store operations can
// touch the component's state, else xpWhole.
func (r *run) xpKeyedOnly(comp string) int {
	for _, id := range r.x.ByComp[comp] {
		f := r.x.Interfaces[id]
		if f == nil {
			continue
		}
		b, err := json.Marshal([]any{f.Behavior, f.Store, f.LatencyMS})
		if err != nil || stateWord.Match(b) {
			return xpWhole
		}
	}
	return xpKeyed
}

// xpRowKey names a row (or, with key "*", a whole table) of an instance's
// store.
func xpRowKey(skey, table, key string) string {
	return "s:" + skey + "|" + table + "|" + key
}

// xpStateWrite is the footprint of a state set event in a keyed
// component: its row, or the whole instance state when the event names
// no row.
func xpStateWrite(e Event) string {
	skey := model.StateKey(e.Component, e.Instance)
	if e.Table == "" || e.Key == "" {
		return "s:" + skey + "|*"
	}
	return xpRowKey(skey, e.Table, e.Key)
}

// xpStoreRead records that a store operation looked up a row (key "*":
// the whole table) of the frame's instance.
func (r *run) xpStoreRead(fr *frame, table, key string) {
	s := r.s.xp
	if s == nil || s.open == nil {
		return
	}
	s.open.reads[xpRowKey(fr.skey, table, key)] = true
}

// xpRowHit reports whether row footprint k overlaps a row footprint in
// other: the same row, or a wildcard ("…|*") covering the other.
func xpRowHit(k string, other map[string]bool) bool {
	for o := range other {
		if !strings.HasPrefix(o, "s:") {
			continue
		}
		if o == k || covers(o, k) || covers(k, o) {
			return true
		}
	}
	return false
}

func covers(wild, k string) bool {
	p, ok := strings.CutSuffix(wild, "*")
	return ok && strings.HasPrefix(k, p)
}

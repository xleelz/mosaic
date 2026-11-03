package model

import (
	"sort"

	"github.com/xleelz/mosaic/internal/expr"
)

// Explicit null in updates (§17 item 6). In a store update value,
// {$null: true} sets a field to JSON null and {$absent: true} removes it.
// A literal null keeps meaning "no change" (§13.1 item 24), which is
// rarely what a model means, so validation warns on one and suggests the
// markers.

// updateNulls warns on each literal null in a store update's value.
func (v *validator) updateNulls(p string, st *StoreSpec) {
	if st.Op != "update" || st.Value == nil {
		return
	}
	var walk func(path string, x any)
	walk = func(path string, x any) {
		m, ok := x.(map[string]any)
		if !ok {
			return
		}
		keys := make([]string, 0, len(m))
		for k := range m {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			if m[k] == nil {
				v.warnf(path+"."+k, "a literal null in an update value changes nothing; write {$null: true} to set null, or {$absent: true} to remove the field")
				continue
			}
			walk(path+"."+k, m[k])
		}
	}
	walk(p+".value", expr.Native(st.Value))
}

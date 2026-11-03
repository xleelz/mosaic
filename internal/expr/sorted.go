package expr

import (
	"fmt"
	"reflect"
	"sort"

	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/common/types/ref"
	"cel.dev/cel-go/common/types/traits"
)

// adapter converts native values to CEL values whose maps iterate in
// sorted key order. cel-go iterates Go maps in Go's random order, so
// without it a comprehension over a map (state.rows.map(k, ...), say) could
// give a different list on every run, and runs must be deterministic.
// Maps built inside an expression (literals, transformMap results) still
// iterate in cel-go's order.
var adapter types.Adapter = sortedAdapter{}

type sortedAdapter struct{}

func (a sortedAdapter) NativeToValue(v any) ref.Val {
	switch t := v.(type) {
	case map[string]any:
		return &sortedMap{Mapper: types.NewStringInterfaceMap(a, t), m: t}
	case []any:
		return types.NewDynamicList(a, t)
	case BigInt: // §15.3: expressions see the decimal string
		return types.String(t)
	}
	return types.DefaultTypeAdapter.NativeToValue(v)
}

// sortedMap is a map[string]any whose iterator yields its keys in order.
type sortedMap struct {
	traits.Mapper
	m map[string]any
}

func (s *sortedMap) Iterator() traits.Iterator {
	keys := make([]string, 0, len(s.m))
	for k := range s.m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return &keyIterator{keys: keys}
}

type keyIterator struct {
	keys []string
	i    int
}

func (it *keyIterator) HasNext() ref.Val { return types.Bool(it.i < len(it.keys)) }

func (it *keyIterator) Next() ref.Val {
	if it.i >= len(it.keys) {
		return nil
	}
	it.i++
	return types.String(it.keys[it.i-1])
}

func (it *keyIterator) ConvertToNative(reflect.Type) (any, error) {
	return nil, fmt.Errorf("type conversion on iterators not supported")
}
func (it *keyIterator) ConvertToType(ref.Type) ref.Val { return types.NewErr("no such overload") }
func (it *keyIterator) Equal(ref.Val) ref.Val          { return types.NewErr("no such overload") }
func (it *keyIterator) Type() ref.Type                 { return types.IteratorType }
func (it *keyIterator) Value() any                     { return nil }

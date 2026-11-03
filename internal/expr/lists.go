package expr

import (
	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/common/types/ref"
	"cel.dev/cel-go/common/types/traits"
)

// List search (§17 item 13): list.indexOf(x) and list.lastIndexOf(x) give
// the index of the first or last element equal to x (CEL equality, so 1
// matches 1.0), or -1 when there is none. They share their names with the
// string library's indexOf, told apart by the receiver. Each costs 1 plus
// one per element (listCost), so a search over a long list counts toward
// max_cel_cost like the comprehension it replaces. Pure, so the eval
// sandbox gets them too.
func listHelpers() []cel.EnvOption {
	lst := cel.ListType(cel.DynType)
	return []cel.EnvOption{
		cel.Function("indexOf",
			cel.MemberOverload("list_index_of_dyn", []*cel.Type{lst, cel.DynType}, cel.IntType,
				cel.BinaryBinding(func(l, x ref.Val) ref.Val { return listIndex(l, x, false) }))),
		cel.Function("lastIndexOf",
			cel.MemberOverload("list_last_index_of_dyn", []*cel.Type{lst, cel.DynType}, cel.IntType,
				cel.BinaryBinding(func(l, x ref.Val) ref.Val { return listIndex(l, x, true) }))),
	}
}

func listIndex(lv, x ref.Val, last bool) ref.Val {
	l, ok := lv.(traits.Lister)
	if !ok {
		return types.NewErr("indexOf needs a list")
	}
	n := int64(l.Size().(types.Int))
	for k := range n {
		i := k
		if last {
			i = n - 1 - k
		}
		if l.Get(types.Int(i)).Equal(x) == types.True {
			return types.Int(i)
		}
	}
	return types.Int(-1)
}

// listCost is the cost of a list search: 1 plus one per element. ok is
// false for anything else, the string indexOf included.
func listCost(function string, args []ref.Val) (uint64, bool) {
	if (function != "indexOf" && function != "lastIndexOf") || len(args) == 0 {
		return 0, false
	}
	l, ok := args[0].(traits.Lister)
	if !ok {
		return 0, false
	}
	return 1 + uint64(l.Size().(types.Int)), true
}

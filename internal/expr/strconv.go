package expr

import "cel.dev/cel-go/cel"

// stringHelpers adds string(map) and string(list) (§17 item 19): the value
// as canonical JSON, keys sorted and no spaces, the text json(x) gives, so
// string({'b': 1, 'a': [1, 'x']}) is `{"a":[1,"x"],"b":1}`. CEL has no
// string conversion for either; scalars keep their own. Both are pure, so
// the eval sandbox gets them too.
func stringHelpers() []cel.EnvOption {
	return []cel.EnvOption{
		cel.Function("string",
			cel.Overload("string_map_json", []*cel.Type{cel.MapType(cel.DynType, cel.DynType)}, cel.StringType, cel.UnaryBinding(jsonImpl)),
			cel.Overload("string_list_json", []*cel.Type{cel.ListType(cel.DynType)}, cel.StringType, cel.UnaryBinding(jsonImpl))),
	}
}

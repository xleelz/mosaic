package expr

import (
	"fmt"
	"math/rand/v2"
	"regexp"
	"sort"
	"strings"
	"sync"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/common/types/ref"
	"cel.dev/cel-go/common/types/traits"
	"cel.dev/cel-go/ext"
)

// maxOmitKeys is the most keys one omit(map, key...) call takes.
const maxOmitKeys = 8

// helpers declares the §11.8 CEL helpers every environment gets:
// sum(list), merge(map, map), omit(map, key...) and random(n), plus the
// §13.1 item 14 additions: replace(s, regex, repl), canceled(name) and
// eval(expr, vars) (matches(s, regex) is CEL's own), and the §13.1 item
// 18 channel_len(name), the §13.1 item 23 byte helpers (bytes.go) and the
// §13.1 item 35 IP and CIDR helpers (ip.go). The two-variable comprehension macros come from
// ext.TwoVarComprehensions. The sandbox that eval runs in gets every
// helper except the run-bound ones (random, canceled, channel_len and eval
// itself).
func helpers() []cel.EnvOption { return helperOpts(false) }

func helperOpts(sandbox bool) []cel.EnvOption {
	omit := []cel.FunctionOpt{}
	for n := 1; n <= maxOmitKeys; n++ {
		args := []*cel.Type{cel.MapType(cel.DynType, cel.DynType)}
		for range n {
			args = append(args, cel.DynType)
		}
		omit = append(omit, cel.Overload("omit_map_"+string(rune('0'+n)), args, cel.DynType, cel.FunctionBinding(omitImpl)))
	}
	opts := []cel.EnvOption{
		cel.Function("replace",
			cel.Overload("replace_regex_string_string_string", []*cel.Type{cel.StringType, cel.StringType, cel.StringType}, cel.StringType,
				cel.FunctionBinding(replaceImpl))),
		cel.Function("sum",
			cel.Overload("sum_list", []*cel.Type{cel.ListType(cel.DynType)}, cel.DynType, cel.UnaryBinding(sumImpl))),
		cel.Function("merge",
			cel.Overload("merge_map_map", []*cel.Type{cel.MapType(cel.DynType, cel.DynType), cel.MapType(cel.DynType, cel.DynType)},
				cel.DynType, cel.BinaryBinding(mergeImpl))),
		cel.Function("omit", omit...),
	}
	opts = append(opts, byteHelpers()...)
	opts = append(opts, ipHelpers()...)
	opts = append(opts, jsonHelpers()...)   // §15.3, json.go
	opts = append(opts, listHelpers()...)   // §17 item 13, lists.go
	opts = append(opts, clockHelpers()...)  // §17 item 17, clock.go
	opts = append(opts, stringHelpers()...) // §17 item 19, strconv.go
	opts = append(opts, quantMacros())      // §16.2, quant.go
	if sandbox {
		return opts
	}
	opts = append(opts, idHelpers()...) // §15.1, ids.go
	return append(opts,
		cel.Function("random",
			cel.Overload("random_int", []*cel.Type{cel.IntType}, cel.IntType, cel.LateFunctionBinding())),
		cel.Function("canceled",
			cel.Overload("canceled_string", []*cel.Type{cel.StringType}, cel.BoolType, cel.LateFunctionBinding())),
		cel.Function("channel_len",
			cel.Overload("channel_len_string", []*cel.Type{cel.StringType}, cel.IntType, cel.LateFunctionBinding())),
		cel.Function("eval",
			cel.Overload("eval_string_map", []*cel.Type{cel.StringType, cel.MapType(cel.StringType, cel.DynType)}, cel.DynType,
				cel.LateFunctionBinding())),
	)
}

// regexps caches compiled replace patterns.
var regexps sync.Map

// replaceImpl replaces every match of an RE2 pattern; repl may refer to
// groups as $1 or ${name}.
func replaceImpl(args ...ref.Val) ref.Val {
	if len(args) != 3 {
		return types.NewErr("replace needs a string, a regex and a replacement")
	}
	s, ok1 := args[0].(types.String)
	pat, ok2 := args[1].(types.String)
	repl, ok3 := args[2].(types.String)
	if !ok1 || !ok2 || !ok3 {
		return types.NewErr("replace needs three strings")
	}
	var re *regexp.Regexp
	if v, ok := regexps.Load(string(pat)); ok {
		re = v.(*regexp.Regexp)
	} else {
		var err error
		if re, err = regexp.Compile(string(pat)); err != nil {
			return types.NewErr("replace: invalid regex %q: %v", string(pat), err)
		}
		regexps.Store(string(pat), re)
	}
	return types.String(re.ReplaceAllString(string(s), string(repl)))
}

// sandbox is the environment eval(expr, vars) runs in: the CEL standard
// library and the pure helpers, with no variables declared. Its programs
// are parsed but not checked, so identifiers resolve at run time from the
// vars map alone and nothing of the run is reachable.
var (
	sandboxOnce sync.Once
	sandboxEnv  *cel.Env
	sandboxMu   sync.Mutex
	sandboxProg = map[progKey]cel.Program{}
)

func evalImpl(src, vars ref.Val, limit int64) ref.Val {
	s, ok := src.(types.String)
	if !ok {
		return types.NewErr("eval needs an expression string")
	}
	m, ok := ToNative(vars).(map[string]any)
	if !ok {
		return types.NewErr("eval needs a map of variables")
	}
	p, err := sandboxProgram(strings.TrimSpace(string(s)), limit)
	if err != nil {
		return types.NewErr("eval %q: %v", string(s), err)
	}
	out, _, err := p.Eval(m)
	if err != nil {
		return types.NewErr("eval %q: %v", string(s), err)
	}
	return adapter.NativeToValue(ToNative(out))
}

func sandboxProgram(src string, limit int64) (cel.Program, error) {
	sandboxOnce.Do(func() {
		opts := []cel.EnvOption{
			cel.CrossTypeNumericComparisons(true),
			ext.Strings(), ext.Math(), ext.Lists(), ext.Encoders(),
			ext.TwoVarComprehensions(),
			cel.CustomTypeAdapter(adapter),
		}
		env, err := cel.NewEnv(append(opts, helperOpts(true)...)...)
		if err != nil {
			panic(err)
		}
		sandboxEnv = env
	})
	sandboxMu.Lock()
	defer sandboxMu.Unlock()
	k := progKey{src, limit}
	if p, ok := sandboxProg[k]; ok {
		return p, nil
	}
	if src == "" {
		return nil, fmt.Errorf("empty expression")
	}
	ast, iss := sandboxEnv.Parse(wrapConversions(src))
	if iss != nil && iss.Err() != nil {
		return nil, fmt.Errorf("%s", strings.ReplaceAll(iss.Err().Error(), "\n", " "))
	}
	p, err := sandboxEnv.Program(ast, cel.CostLimit(uint64(limit)), costOptions())
	if err != nil {
		return nil, err
	}
	if len(sandboxProg) < 4096 {
		sandboxProg[k] = p
	}
	return p, nil
}

// sumImpl adds a list of numbers: an int when every item is an int, else a
// double. The empty list sums to 0.
func sumImpl(v ref.Val) ref.Val {
	l, ok := v.(traits.Lister)
	if !ok {
		return types.NewErr("sum needs a list")
	}
	var i int64
	var f float64
	isFloat := false
	it := l.Iterator()
	for it.HasNext() == types.True {
		switch t := it.Next().(type) {
		case types.Int:
			i += int64(t)
		case types.Uint:
			i += int64(t)
		case types.Double:
			f += float64(t)
			isFloat = true
		default:
			return types.NewErr("sum: %v is not a number", t.Type())
		}
	}
	if isFloat {
		return types.Double(f + float64(i))
	}
	return types.Int(i)
}

// mergeImpl deep-merges b over a: maps merge key by key, the right side
// winning; any other value of b replaces.
func mergeImpl(a, b ref.Val) ref.Val {
	am, ok1 := ToNative(a).(map[string]any)
	bm, ok2 := ToNative(b).(map[string]any)
	if !ok1 || !ok2 {
		return types.NewErr("merge needs two maps")
	}
	return adapter.NativeToValue(mergeMaps(am, bm))
}

func mergeMaps(a, b map[string]any) map[string]any {
	out := make(map[string]any, len(a)+len(b))
	for k, v := range a {
		out[k] = v
	}
	for _, k := range sortedKeys(b) {
		bv := b[k]
		if bm, ok := bv.(map[string]any); ok {
			if am, ok := out[k].(map[string]any); ok {
				out[k] = mergeMaps(am, bm)
				continue
			}
		}
		out[k] = bv
	}
	return out
}

// omitImpl returns the map without the given keys. A key argument that is
// a list omits every key in it.
func omitImpl(args ...ref.Val) ref.Val {
	if len(args) == 0 {
		return types.NewErr("omit needs a map")
	}
	m, ok := ToNative(args[0]).(map[string]any)
	if !ok {
		return types.NewErr("omit needs a map")
	}
	// ToNative keys maps by fmt.Sprint, so non-string keys match the same way.
	drop := func(k any) { delete(m, fmt.Sprint(k)) }
	for _, a := range args[1:] {
		switch t := ToNative(a).(type) {
		case []any:
			for _, k := range t {
				drop(k)
			}
		default:
			drop(t)
		}
	}
	return adapter.NativeToValue(m)
}

// activation wraps act with the late-bound random(n), drawing from the
// func(int64) int64 under RandomKey, or else from a fixed seed.
func activation(act map[string]any) any {
	draw, _ := act[RandomKey].(func(int64) int64)
	if draw == nil {
		var rng *rand.Rand
		draw = func(n int64) int64 {
			if rng == nil {
				rng = rand.New(rand.NewPCG(1, 2))
			}
			return rng.Int64N(n)
		}
	}
	isCanceled, _ := act[CanceledKey].(func(string) bool)
	chanLen, _ := act[ChannelLenKey].(func(string) int64)
	limit := CostLimit(act)
	late := map[string]cel.LateBoundFunction{
		"channel_len": func(_ string, args ...ref.Val) ref.Val {
			if len(args) != 1 {
				return types.NewErr("channel_len needs one argument")
			}
			name, ok := args[0].(types.String)
			if !ok {
				return types.NewErr("channel_len(name) needs a string")
			}
			if chanLen == nil {
				return types.Int(0)
			}
			return types.Int(chanLen(string(name)))
		},
		"eval": func(_ string, args ...ref.Val) ref.Val {
			if len(args) != 2 {
				return types.NewErr("eval needs an expression and a map of variables")
			}
			return evalImpl(args[0], args[1], limit)
		},
		"canceled": func(_ string, args ...ref.Val) ref.Val {
			if len(args) != 1 {
				return types.NewErr("canceled needs one argument")
			}
			name, ok := args[0].(types.String)
			if !ok {
				return types.NewErr("canceled(name) needs a string")
			}
			return types.Bool(isCanceled != nil && isCanceled(string(name)))
		},
		"random": func(_ string, args ...ref.Val) ref.Val {
			if len(args) != 1 {
				return types.NewErr("random needs one argument")
			}
			n, ok := args[0].(types.Int)
			if !ok || n <= 0 {
				return types.NewErr("random(n) needs a positive int n")
			}
			return types.Int(draw(int64(n)))
		},
	}
	for k, f := range idBindings(act) {
		late[k] = f
	}
	fa, err := cel.FunctionVars(act, late)
	if err != nil {
		return act
	}
	return fa
}

// NewSteps builds the CEL value of `steps` in multi-step scenarios: a map
// that answers both steps.<as> (by name) and steps[i] (by position).
func NewSteps(named map[string]any, list []any) any {
	m := make(map[ref.Val]ref.Val, len(named)+len(list))
	a := adapter
	keys := make([]string, 0, len(named))
	for k := range named {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		m[types.String(k)] = a.NativeToValue(named[k])
	}
	for i, v := range list {
		if v == nil {
			continue // a step that hasn't finished
		}
		m[types.Int(i)] = a.NativeToValue(v)
	}
	return types.NewRefValMap(a, m)
}

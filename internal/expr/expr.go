// Package expr evaluates the CEL expressions and templates that behaviors,
// scenarios and expectations are written in. CEL is total and side-effect
// free, so evaluation always terminates; a cost limit bounds its work.
package expr

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/common/types/ref"
	"cel.dev/cel-go/common/types/traits"
	"cel.dev/cel-go/ext"
)

// Variables available to behavior expressions. self, deadline and config
// are the §11 additions: the instance the behavior runs on, the absolute
// deadline in ms (null if none) and the effective config values.
// now_us (§13.1 item 16) is the clock in integer microseconds; now stays
// in ms, a float when it isn't whole. limiters (§13.1 item 27) is the
// limiter state by full limiter id, then key.
var BehaviorVars = []string{"input", "state", "ctx", "vars", "attempt", "now", "error", "self", "deadline", "config", "now_us", "limiters"}

// Variables available to a store's where condition: the behavior variables
// plus the row under test (null when absent) and its key.
var StoreVars = append(append([]string{}, BehaviorVars...), "row", "key")

// Variables available to the templates of multi-step scenario steps (§11.7):
// the behavior variables plus steps, the results of earlier steps by name
// (steps.<as>) and by position (steps[i]), and pass, the 1-based pass of a
// repeated step (§13.1 item 27).
var StepVars = append(append([]string{}, BehaviorVars...), "steps", "pass")

// Variables available to an interface's latency_by_outcome entries
// (§14.13): the call's result ({ok, value, error}), its input and config.
var OutcomeVars = []string{"result", "input", "config"}

// Variables available to scenario expectations, with the §13.1 additions
// (config, topology, calls_by_instance, steps and trace), and the limiter
// state and the summary's limit counts (§13.1 item 27).
var ExpectVars = []string{"result", "status", "calls", "ctx", "state", "retries", "faults", "duration_ms", "warnings", "passes",
	"config", "topology", "calls_by_instance", "steps", "trace", "duration_us", "limiters", "limits",
	"io"} // §15.1: the boundary view of a run

// RandomKey is the activation key that carries a run's random source: a
// func(n int64) int64 giving an int in [0, n). CEL random(n) calls it, so a
// run seeds it once and every evaluation draws deterministically from it.
// Without it, random(n) draws from a fixed seed, which is still
// deterministic.
const RandomKey = "__random"

// CanceledKey is the activation key that carries a run's cancellation
// tokens (§13.1 item 14): a func(name string) bool that CEL canceled(name)
// calls. Without it, canceled(name) is false.
const CanceledKey = "__canceled"

// ChannelLenKey is the activation key that carries a run's channels
// (§13.1 item 18): a func(name string) int64 that CEL channel_len(name)
// calls. Without it, channel_len(name) is 0.
const ChannelLenKey = "__channel_len"

// CostLimitKey is the activation key that carries a run's CEL cost limit
// (an int64, §13.1 item 18: Scenario.cost_limit). Without it, or when it is
// not positive, DefaultCostLimit applies. eval(expr, vars) runs under the
// same limit.
const CostLimitKey = "__cost_limit"

// DefaultCostLimit bounds the work of one evaluation. It was 1,000,000
// before §13.1 item 18, which prompts of about 500 tokens exceeded.
const DefaultCostLimit = 10_000_000

// MaxCostLimit is the safety bound on any cost limit: a scenario's
// cost_limit or max_cel_cost, a run's limits and the limit scaled from
// the input's size (behavior-language §30).
const MaxCostLimit = 10_000_000_000

// costProbeFactor is how far past the limit an over-limit expression is
// re-run to measure what it needs, for the error message.
const costProbeFactor = 20

// Env compiles and caches programs for one set of variables.
type Env struct {
	env   *cel.Env
	mu    sync.Mutex
	asts  map[string]*cel.Ast
	cache map[progKey]cel.Program
}

// progKey caches a program by its source and cost limit.
type progKey struct {
	src   string
	limit int64
}

// Behavior is the environment for behavior steps, templates and retry conditions.
var Behavior = mustEnv(BehaviorVars)

// Store is the environment for a store operation's where condition.
var Store = mustEnv(StoreVars)

// Outcome is the environment for latency_by_outcome's when and ms (§14.13).
var Outcome = mustEnv(OutcomeVars)

// Expect is the environment for scenario expectations.
var Expect = mustEnv(ExpectVars)

// Step is the environment for the templates of multi-step scenario steps.
var Step = mustEnv(StepVars)

func mustEnv(vars []string) *Env {
	opts := []cel.EnvOption{
		cel.CrossTypeNumericComparisons(true),
		ext.Strings(), ext.Math(), ext.Lists(), ext.Encoders(),
		ext.TwoVarComprehensions(),
		cel.CustomTypeAdapter(adapter),
	}
	opts = append(opts, helpers()...)
	for _, v := range vars {
		opts = append(opts, cel.Variable(v, cel.DynType))
	}
	env, err := cel.NewEnv(opts...)
	if err != nil {
		panic(err)
	}
	return &Env{env: env, asts: map[string]*cel.Ast{}, cache: map[progKey]cel.Program{}}
}

// Compile parses and checks src, caching the program, with the default
// cost limit.
func (e *Env) Compile(src string) (cel.Program, error) {
	return e.compile(src, DefaultCostLimit)
}

func (e *Env) compile(src string, limit int64) (cel.Program, error) {
	src = strings.TrimSpace(src)
	e.mu.Lock()
	defer e.mu.Unlock()
	k := progKey{src, limit}
	if p, ok := e.cache[k]; ok {
		return p, nil
	}
	if src == "" {
		return nil, fmt.Errorf("empty expression")
	}
	ast, ok := e.asts[src]
	if !ok {
		var iss *cel.Issues
		ast, iss = e.env.Compile(wrapConversions(src))
		if iss != nil && iss.Err() != nil {
			return nil, fmt.Errorf("%s", strings.ReplaceAll(iss.Err().Error(), "\n", " "))
		}
		e.asts[src] = ast
	}
	p, err := e.env.Program(ast, cel.EvalOptions(cel.OptOptimize), cel.CostLimit(uint64(limit)), costOptions())
	if err != nil {
		return nil, err
	}
	e.cache[k] = p
	return p, nil
}

// CostLimit is the cost limit an activation carries (CostLimitKey), or
// DefaultCostLimit.
func CostLimit(act map[string]any) int64 {
	if n, ok := act[CostLimitKey].(int64); ok && n > 0 {
		return n
	}
	return DefaultCostLimit
}

// Eval evaluates src and returns a native Go value.
func (e *Env) Eval(src string, act map[string]any) (any, error) {
	p, err := e.compile(src, CostLimit(act))
	if err != nil {
		return nil, err
	}
	out, _, err := p.Eval(activation(act))
	if err != nil {
		if IsCostLimit(err) {
			return nil, e.costError(src, act, err)
		}
		return nil, fmt.Errorf("%s: %w", src, err)
	}
	return ToNative(out), nil
}

// IsCostLimit reports whether err is CEL's cost limit error.
func IsCostLimit(err error) bool {
	return err != nil && strings.Contains(err.Error(), "cost limit exceeded")
}

// costError reports an expression over its cost limit (behavior-language
// §30): the limit, and what the expression costs, measured by running it
// again under a limit costProbeFactor times higher (with random() and the
// id helpers detached, so the run's sequences don't move). The message
// keeps CEL's "actual cost limit exceeded" text.
func (e *Env) costError(src string, act map[string]any, err error) error {
	limit := CostLimit(act)
	need := ""
	if probe := min(limit*costProbeFactor, MaxCostLimit); probe > limit {
		pa := make(map[string]any, len(act))
		for k, v := range act {
			pa[k] = v
		}
		pa[CostLimitKey] = probe
		pa[RandomKey] = func(int64) int64 { return 0 }
		pa[IDsKey] = NewIDs(0)
		if p, cerr := e.compile(src, probe); cerr == nil {
			_, det, perr := p.Eval(activation(pa))
			switch {
			case perr == nil && det != nil && det.ActualCost() != nil:
				need = fmt.Sprintf("; it costs %d", *det.ActualCost())
			case IsCostLimit(perr):
				need = fmt.Sprintf("; it costs more than %d", probe)
			}
		}
	}
	return fmt.Errorf("%s: CEL cost limit %d exceeded%s (raise it with the scenario's max_cel_cost, up to %d): %w",
		src, limit, need, int64(MaxCostLimit), err)
}

// EvalBool evaluates src and requires a boolean.
func (e *Env) EvalBool(src string, act map[string]any) (bool, error) {
	v, err := e.Eval(src, act)
	if err != nil {
		return false, err
	}
	b, ok := v.(bool)
	if !ok {
		return false, fmt.Errorf("%s: expected a boolean, got %T", src, v)
	}
	return b, nil
}

// ExprOf reports whether v is an expression string ("=..."), returning its source.
func ExprOf(v any) (string, bool) {
	s, ok := v.(string)
	if !ok {
		return "", false
	}
	src, ok := strings.CutPrefix(s, "=")
	return strings.TrimSpace(src), ok
}

// Template evaluates a template: expression strings are evaluated, other
// strings and scalars are literals, and maps and lists recurse.
func (e *Env) Template(v any, act map[string]any) (any, error) {
	switch t := v.(type) {
	case string:
		if src, ok := ExprOf(t); ok {
			return e.Eval(src, act)
		}
		return t, nil
	case map[string]any:
		out := make(map[string]any, len(t))
		for _, k := range sortedKeys(t) {
			r, err := e.Template(t[k], act)
			if err != nil {
				return nil, err
			}
			out[k] = r
		}
		return out, nil
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			r, err := e.Template(x, act)
			if err != nil {
				return nil, err
			}
			out[i] = r
		}
		return out, nil
	}
	return Native(v), nil
}

// TemplateExprs returns every expression in a template, for validation.
func TemplateExprs(v any) []string {
	var out []string
	var walk func(any)
	walk = func(v any) {
		switch t := v.(type) {
		case string:
			if src, ok := ExprOf(t); ok {
				out = append(out, src)
			}
		case map[string]any:
			for _, k := range sortedKeys(t) {
				walk(t[k])
			}
		case []any:
			for _, x := range t {
				walk(x)
			}
		}
	}
	walk(v)
	return out
}

// DecodeTemplate decodes a raw JSON template, keeping whole numbers as int64.
func DecodeTemplate(raw json.RawMessage) (any, error) {
	if len(raw) == 0 {
		return nil, nil
	}
	var v any
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.UseNumber()
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return Native(v), nil
}

// Native normalizes decoded JSON for evaluation: json.Number becomes int64
// when it is a whole number and float64 otherwise; Go ints become int64.
func Native(v any) any {
	switch t := v.(type) {
	case json.Number:
		if !strings.ContainsAny(string(t), ".eE") {
			if n, err := strconv.ParseInt(string(t), 10, 64); err == nil {
				return n
			}
			// Beyond int64 (behavior-language §30): up to 2^64-1 a whole
			// number is a uint64 (CEL uint); past that, a double, which
			// validation and runs warn about (LossyInt).
			if n, err := strconv.ParseUint(string(t), 10, 64); err == nil {
				return n
			}
		}
		f, _ := t.Float64()
		return f
	case int:
		return int64(t)
	case int32:
		return int64(t)
	case float32:
		return float64(t)
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, x := range t {
			out[k] = Native(x)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			out[i] = Native(x)
		}
		return out
	case map[string]map[string]any:
		out := make(map[string]any, len(t))
		for k, x := range t {
			out[k] = Native(x)
		}
		return out
	}
	return v
}

// ToNative converts a CEL value to plain Go: nil, bool, int64, float64,
// string, []any and map[string]any; a uint beyond int64 stays a uint64.
func ToNative(v ref.Val) any {
	switch v.Type() {
	case types.NullType:
		return nil
	case types.BoolType:
		return bool(v.(types.Bool))
	case types.IntType:
		return int64(v.(types.Int))
	case types.UintType:
		if u := uint64(v.(types.Uint)); u > math.MaxInt64 {
			return u // behavior-language §30: kept, not wrapped
		}
		return int64(v.(types.Uint))
	case types.DoubleType:
		return float64(v.(types.Double))
	case types.StringType:
		return string(v.(types.String))
	case types.BytesType:
		return string(v.(types.Bytes))
	case types.TimestampType:
		if t, ok := v.Value().(time.Time); ok {
			return t.UTC().Format(time.RFC3339Nano)
		}
	case types.DurationType:
		if d, ok := v.Value().(time.Duration); ok {
			return d.String()
		}
	}
	if m, ok := v.(traits.Mapper); ok {
		out := map[string]any{}
		it := m.Iterator()
		for it.HasNext() == types.True {
			k := it.Next()
			out[fmt.Sprint(ToNative(k))] = ToNative(m.Get(k))
		}
		return out
	}
	if l, ok := v.(traits.Lister); ok {
		out := []any{}
		it := l.Iterator()
		for it.HasNext() == types.True {
			out = append(out, ToNative(it.Next()))
		}
		return out
	}
	return Native(v.Value())
}

func sortedKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

package compose

import (
	"fmt"
	"sync"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/ext"

	"github.com/xleelz/mosaic/internal/expr"
)

// celEnv compiles and caches CEL programs over a fixed set of variables.
type celEnv struct {
	env   *cel.Env
	mu    sync.Mutex
	progs map[string]cel.Program
}

func newCELEnv(vars ...string) *celEnv {
	opts := []cel.EnvOption{
		cel.CrossTypeNumericComparisons(true),
		ext.Strings(), ext.Math(), ext.Lists(), ext.Encoders(),
	}
	for _, v := range vars {
		opts = append(opts, cel.Variable(v, cel.DynType))
	}
	env, err := cel.NewEnv(opts...)
	if err != nil {
		panic(err)
	}
	return &celEnv{env: env, progs: map[string]cel.Program{}}
}

// gateEnv evaluates gate expressions and "=cel" input mappings.
var gateEnv = newCELEnv("artifacts", "inputs", "tree", "item")

// scriptEnv evaluates "=cel" outputs in script scenarios.
var scriptEnv = newCELEnv("task", "stage", "role", "brief", "call", "item", "branch", "depth", "argv")

func (e *celEnv) compile(src string) (cel.Program, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if p, ok := e.progs[src]; ok {
		return p, nil
	}
	ast, iss := e.env.Compile(src)
	if iss != nil && iss.Err() != nil {
		return nil, iss.Err()
	}
	p, err := e.env.Program(ast, cel.CostLimit(expr.DefaultCostLimit))
	if err != nil {
		return nil, err
	}
	e.progs[src] = p
	return p, nil
}

func (e *celEnv) eval(src string, act map[string]any) (any, error) {
	p, err := e.compile(src)
	if err != nil {
		return nil, err
	}
	for k, v := range act {
		act[k] = expr.Native(v)
	}
	out, _, err := p.Eval(act)
	if err != nil {
		return nil, err
	}
	return expr.ToNative(out), nil
}

func (e *celEnv) evalBool(src string, act map[string]any) (bool, error) {
	v, err := e.eval(src, act)
	if err != nil {
		return false, err
	}
	b, ok := v.(bool)
	if !ok {
		return false, fmt.Errorf("expression %q gave %T, want bool", src, v)
	}
	return b, nil
}

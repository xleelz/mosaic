package compose

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"math/rand/v2"
	"os"
	"path"
	"strings"
	"sync"
	"time"

	"sigs.k8s.io/yaml"

	"github.com/xleelz/mosaic/internal/jsonschema"
)

// Scenario scripts a run for the script executor and simulate.
//
//	id: sim                     # the root task id (simulate)
//	inputs: {scope: {...}}      # the root's inputs
//	turns:                      # agent_turn outputs, first match wins
//	  - stage: inventory        # matches the stage id (required)
//	    role: inventory         # optional: matches the role
//	    task: "sim.*"           # optional: a glob over the task id
//	    branch: 2               # optional: matches the fanout branch index
//	    output: {...}           # the artifact; a string "=cel" is evaluated over
//	                            #   task, stage, role, brief, call, item, branch, depth
//	    fail: "message"         # optional: the turn fails with this error
//	    delay_ms: 20            # optional: the turn takes this long
//	commands:                   # command stage results, same matching
//	  - stage: test
//	    output: {exit: 0, stdout: "ok", stderr: ""}
//	detached:                   # detached children admitted after the root (simulate)
//	  - parent: sim
//	    from_parent: {contract: contract}
//	    inputs: {...}
//
// A turn no rule matches gets a value generated from its output schema.
type Scenario struct {
	ID       string                     `json:"id,omitempty"`
	Inputs   map[string]json.RawMessage `json:"inputs,omitempty"`
	Turns    []*ScriptRule              `json:"turns,omitempty"`
	Commands []*ScriptRule              `json:"commands,omitempty"`
	Detached []*DetachedSpec            `json:"detached,omitempty"`
}

// ScriptRule is one scripted turn or command result.
type ScriptRule struct {
	Stage   string          `json:"stage"`
	Role    string          `json:"role,omitempty"`
	Task    string          `json:"task,omitempty"`
	Branch  *int            `json:"branch,omitempty"`
	Output  json.RawMessage `json:"output,omitempty"`
	Fail    string          `json:"fail,omitempty"`
	DelayMS int             `json:"delay_ms,omitempty"`
}

// DetachedSpec is a detached child that simulate admits after the root.
type DetachedSpec struct {
	Parent     string                     `json:"parent"`
	ID         string                     `json:"id,omitempty"`
	Template   string                     `json:"template,omitempty"` // a template id; default the root's
	Inputs     map[string]json.RawMessage `json:"inputs,omitempty"`
	FromParent map[string]string          `json:"from_parent,omitempty"`
}

// LoadScenario reads a scenario file (YAML or JSON).
func LoadScenario(file string) (*Scenario, error) {
	data, err := os.ReadFile(file)
	if err != nil {
		return nil, err
	}
	return ParseScenario(data)
}

// ParseScenario parses a scenario (YAML or JSON).
func ParseScenario(data []byte) (*Scenario, error) {
	js, err := yaml.YAMLToJSON(data)
	if err != nil {
		return nil, fmt.Errorf("scenario: %v", err)
	}
	dec := json.NewDecoder(bytes.NewReader(js))
	dec.DisallowUnknownFields()
	var sc Scenario
	if err := dec.Decode(&sc); err != nil {
		return nil, fmt.Errorf("scenario: %v", err)
	}
	for i, r := range append(append([]*ScriptRule{}, sc.Turns...), sc.Commands...) {
		if r.Stage == "" {
			return nil, fmt.Errorf("scenario: rule %d has no stage", i)
		}
		if r.Task != "" {
			if _, err := path.Match(r.Task, ""); err != nil {
				return nil, fmt.Errorf("scenario: rule %d: task glob %q: %v", i, r.Task, err)
			}
		}
	}
	return &sc, nil
}

// ScriptExecutor is the deterministic executor for tests and simulate.
type ScriptExecutor struct {
	Scenario *Scenario

	mu    sync.Mutex
	calls map[*ScriptRule]int
	turns []Turn
}

// NewScriptExecutor returns an executor scripted by sc.
func NewScriptExecutor(sc *Scenario) *ScriptExecutor {
	if sc == nil {
		sc = &Scenario{}
	}
	return &ScriptExecutor{Scenario: sc, calls: map[*ScriptRule]int{}}
}

// Turns returns the turns run so far, in order.
func (e *ScriptExecutor) Turns() []Turn {
	e.mu.Lock()
	defer e.mu.Unlock()
	return append([]Turn{}, e.turns...)
}

func (e *ScriptExecutor) match(rules []*ScriptRule, task, stage, role string, info TurnInfo) (*ScriptRule, int) {
	e.mu.Lock()
	defer e.mu.Unlock()
	for _, r := range rules {
		if r.Stage != stage || (r.Role != "" && r.Role != role) || (r.Branch != nil && *r.Branch != info.Branch) {
			continue
		}
		if r.Task != "" {
			if ok, _ := path.Match(r.Task, task); !ok {
				continue
			}
		}
		n := e.calls[r]
		e.calls[r] = n + 1
		return r, n
	}
	return nil, 0
}

func (e *ScriptExecutor) value(r *ScriptRule, vars map[string]any) (json.RawMessage, error) {
	var s string
	if json.Unmarshal(r.Output, &s) == nil && strings.HasPrefix(s, "=") {
		v, err := scriptEnv.eval(s[1:], vars)
		if err != nil {
			return nil, fmt.Errorf("script output for %s: %v", r.Stage, err)
		}
		return json.Marshal(v)
	}
	if len(r.Output) == 0 {
		return json.RawMessage("null"), nil
	}
	return r.Output, nil
}

func wait(ctx context.Context, ms int) error {
	if ms <= 0 {
		return ctx.Err()
	}
	t := time.NewTimer(time.Duration(ms) * time.Millisecond)
	defer t.Stop()
	select {
	case <-t.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Run returns the scripted output of a turn, validated against its schema,
// and writes it to the turn's output path as an agent would.
func (e *ScriptExecutor) Run(ctx context.Context, t Turn) (json.RawMessage, error) {
	info, ok := TurnInfoFrom(ctx)
	if !ok {
		info = TurnInfo{Branch: -1}
	}
	e.mu.Lock()
	e.turns = append(e.turns, t)
	e.mu.Unlock()
	var schema map[string]any
	if len(t.OutputSchema) > 0 {
		v, err := decodeJSON(t.OutputSchema)
		if err != nil {
			return nil, fmt.Errorf("output schema: %v", err)
		}
		schema, _ = v.(map[string]any)
	}
	r, call := e.match(e.Scenario.Turns, t.TaskID, t.StageID, t.Role, info)
	var out json.RawMessage
	if r == nil {
		h := fnv.New64a()
		fmt.Fprintf(h, "%s/%s/%d", t.TaskID, t.StageID, info.Branch)
		g := &jsonschema.Generator{Rng: rand.New(rand.NewPCG(h.Sum64(), 0))}
		out, _ = json.Marshal(g.Generate(schema))
	} else {
		if err := wait(ctx, r.DelayMS); err != nil {
			return nil, err
		}
		if r.Fail != "" {
			return nil, fmt.Errorf("%s", r.Fail)
		}
		vars := map[string]any{"task": t.TaskID, "stage": t.StageID, "role": t.Role, "brief": t.Brief, "call": int64(call),
			"item": info.Item, "branch": int64(info.Branch), "depth": int64(info.Depth), "argv": []any{}}
		v, err := e.value(r, vars)
		if err != nil {
			return nil, err
		}
		out = v
	}
	if schema != nil {
		v, err := decodeJSON(out)
		if err != nil {
			return nil, err
		}
		if errs := jsonschema.Validate(schema, v, nil); len(errs) > 0 {
			return nil, fmt.Errorf("scripted output for %s does not match its schema: %v", t.StageID, errs)
		}
	}
	if t.OutputPath != "" {
		if err := os.WriteFile(t.OutputPath, append(append([]byte{}, out...), '\n'), 0o644); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// ScriptCommand returns a scripted command result, if a rule matches.
func (e *ScriptExecutor) ScriptCommand(ctx context.Context, task, stage string, argv []string) (CommandResult, bool, error) {
	info, ok := TurnInfoFrom(ctx)
	if !ok {
		info = TurnInfo{Branch: -1}
	}
	r, call := e.match(e.Scenario.Commands, task, stage, "", info)
	if r == nil {
		return CommandResult{}, false, nil
	}
	if err := wait(ctx, r.DelayMS); err != nil {
		return CommandResult{}, false, err
	}
	if r.Fail != "" {
		return CommandResult{}, false, fmt.Errorf("%s", r.Fail)
	}
	args := make([]any, len(argv))
	for i, a := range argv {
		args[i] = a
	}
	raw, err := e.value(r, map[string]any{"task": task, "stage": stage, "role": "", "brief": "", "call": int64(call),
		"item": info.Item, "branch": int64(info.Branch), "depth": int64(info.Depth), "argv": args})
	if err != nil {
		return CommandResult{}, false, err
	}
	var res CommandResult
	if err := json.Unmarshal(raw, &res); err != nil {
		return CommandResult{}, false, fmt.Errorf("scripted command %s: %v", stage, err)
	}
	return res, true, nil
}

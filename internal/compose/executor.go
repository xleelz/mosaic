package compose

import (
	"context"
	"encoding/json"
	"errors"
	"sort"
	"sync"
	"time"
)

// Turn is one agent_turn stage visit handed to an executor.
type Turn struct {
	TaskID, StageID, Role string
	Brief                 string // rendered brief
	OutputPath            string // where the agent must write the output artifact (JSON)
	OutputSchema          json.RawMessage
	Tools                 []string
	Model                 string
	Dir                   string // working directory (repo root)
	// WriteScope, when set, lists the only absolute paths (directories or
	// files) the agent may write: the run's output directory and OutputPath,
	// for templates that produce artifacts (DESIGN §16.7). Executors restrict
	// the agent's write permission to them; the engine also verifies after
	// the turn that nothing else in Dir changed.
	WriteScope []string
	// The stage's budget (DESIGN §14.13); zero means unbounded. The engine
	// also cancels the turn's context at Timeout.
	MaxTurns int
	Timeout  time.Duration
}

// ErrWriteScope marks a turn that wrote outside its write scope. The engine
// fails such a turn with reason write_scope.
var ErrWriteScope = errors.New("write outside the write scope")

// ErrBudget marks a turn that ran out of its budget (timeout or max
// turns). The engine fails such a turn with reason budget.
var ErrBudget = errors.New("budget exhausted")

// SessionStats is one agent session (one attempt of a turn), as reported by
// the claude executor and written to turns/<stage path>.meta.json.
type SessionStats struct {
	Turn       int     `json:"turn"`    // the stage's turn (invocation) number, from 1
	Attempt    int     `json:"attempt"` // the attempt within the turn, from 1
	Visit      int     `json:"visit,omitempty"`
	SessionID  string  `json:"session_id,omitempty"`
	Subtype    string  `json:"subtype,omitempty"`
	IsError    bool    `json:"is_error,omitempty"`
	NumTurns   int     `json:"num_turns"`
	DurationMS int64   `json:"duration_ms"`
	CostUSD    float64 `json:"total_cost_usd"`
	WallMS     int64   `json:"wall_ms"`         // measured by the executor
	Error      string  `json:"error,omitempty"` // why the attempt failed, if it did
}

// TurnObserver receives what an executor learns about a turn besides its
// artifact. The engine attaches one to the turn's context; executors that
// have nothing to report (script) ignore it.
type TurnObserver interface {
	SessionStats(s SessionStats) // once per attempt
	Warning(msg string)
}

type turnObserverKey struct{}

// WithTurnObserver returns ctx carrying o.
func WithTurnObserver(ctx context.Context, o TurnObserver) context.Context {
	return context.WithValue(ctx, turnObserverKey{}, o)
}

// TurnObserverFrom returns the observer attached to ctx, if any.
func TurnObserverFrom(ctx context.Context) (TurnObserver, bool) {
	o, ok := ctx.Value(turnObserverKey{}).(TurnObserver)
	return o, ok
}

// Executor runs agent turns. The script executor (tests and simulate) and
// the claude executor implement it; a fae executor can replace both.
type Executor interface {
	Run(ctx context.Context, t Turn) (json.RawMessage, error) // returns the validated artifact
}

var (
	registryMu sync.RWMutex
	registry   = map[string]Executor{}
)

// Register makes an executor available by name (for --executor). A second
// registration under the same name replaces the first.
func Register(name string, e Executor) {
	registryMu.Lock()
	defer registryMu.Unlock()
	registry[name] = e
}

// Lookup returns the executor registered under name.
func Lookup(name string) (Executor, bool) {
	registryMu.RLock()
	defer registryMu.RUnlock()
	e, ok := registry[name]
	return e, ok
}

// Executors lists the registered executor names, sorted.
func Executors() []string {
	registryMu.RLock()
	defer registryMu.RUnlock()
	out := make([]string, 0, len(registry))
	for n := range registry {
		out = append(out, n)
	}
	sort.Strings(out)
	return out
}

// TurnInfo is extra context the engine attaches to a turn's context. The
// Turn struct is the executor contract; TurnInfo is optional detail that
// deterministic executors (script) use to vary outputs per branch or depth.
type TurnInfo struct {
	Branch int // -1 outside a fanout branch
	Item   any // the branch item, nil outside a branch
	Depth  int // the run's depth in its tree (root 1)
	Visit  int
}

type turnInfoKey struct{}

// WithTurnInfo returns ctx carrying info.
func WithTurnInfo(ctx context.Context, info TurnInfo) context.Context {
	return context.WithValue(ctx, turnInfoKey{}, info)
}

// TurnInfoFrom returns the TurnInfo attached to ctx, if any.
func TurnInfoFrom(ctx context.Context) (TurnInfo, bool) {
	info, ok := ctx.Value(turnInfoKey{}).(TurnInfo)
	return info, ok
}

// CommandResult is the artifact a command stage produces.
type CommandResult struct {
	Exit   int    `json:"exit"`
	Stdout string `json:"stdout"`
	Stderr string `json:"stderr"`
}

// CommandScripter is implemented by executors that can script command
// stages (the script executor). ok is false when no scripted value applies,
// and the engine then runs the command (or, in dry mode, records exit 0).
type CommandScripter interface {
	ScriptCommand(ctx context.Context, taskID, stageID string, argv []string) (res CommandResult, ok bool, err error)
}

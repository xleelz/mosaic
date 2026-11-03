// Package model defines the mosaic ontology: its entities, the document that
// carries a whole ontology, strict decoding, and validation. It performs no I/O.
package model

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// SchemaVersion is the document schema version this package reads and writes.
const SchemaVersion = 1

// Entity kinds stored in an ontology.
const (
	KindComponent = "component"
	KindInterface = "interface"
	KindLink      = "link"
	KindSchema    = "schema"
	KindFlow      = "flow"
	KindScenario  = "scenario"
	KindConfig    = "config"  // §11.6
	KindFixture   = "fixture" // §11.7
)

// Kinds lists every entity kind in document order. The §11 kinds come last
// so that the order of the original kinds, and everything sorted by it, is
// unchanged.
var Kinds = []string{KindComponent, KindInterface, KindLink, KindSchema, KindFlow, KindScenario, KindConfig, KindFixture}

var plurals = map[string]string{
	KindComponent: "components", KindInterface: "interfaces", KindLink: "links",
	KindSchema: "schemas", KindFlow: "flows", KindScenario: "scenarios",
	KindConfig: "configs", KindFixture: "fixtures",
}

// Plural returns the API collection name of a kind.
func Plural(kind string) string { return plurals[kind] }

// KindOf maps a collection name ("components") or a kind ("component") to its kind.
func KindOf(name string) (string, bool) {
	for k, p := range plurals {
		if name == k || name == p {
			return k, true
		}
	}
	return "", false
}

var (
	slugRE  = regexp.MustCompile(`^[a-z0-9][a-z0-9_-]{0,63}$`)
	identRE = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)
)

// ValidID reports whether s is a slug: [a-z0-9] then [a-z0-9_-], at most 64 characters.
func ValidID(s string) bool { return slugRE.MatchString(s) }

// ValidIdent reports whether s is a variable or path segment name.
func ValidIdent(s string) bool { return identRE.MatchString(s) }

// Source points at code that justifies an entity. It decodes from an object or
// from a "path", "path:line" or "path:line-end" string.
type Source struct {
	Repo    string `json:"repo,omitempty"`
	Path    string `json:"path"`
	Line    int    `json:"line,omitempty"`
	EndLine int    `json:"end_line,omitempty"`
	SHA     string `json:"sha,omitempty"`
}

// ParseSource parses "path", "path:line" or "path:line-end".
func ParseSource(s string) Source {
	out := Source{Path: s}
	if i := strings.LastIndex(s, ":"); i > 0 {
		lo, hi, _ := strings.Cut(s[i+1:], "-")
		if n, err := strconv.Atoi(lo); err == nil && n > 0 {
			out = Source{Path: s[:i], Line: n}
			if m, err := strconv.Atoi(hi); err == nil && m >= n {
				out.EndLine = m
			}
		}
	}
	return out
}

func (s Source) String() string {
	switch {
	case s.Line > 0 && s.EndLine > 0:
		return fmt.Sprintf("%s:%d-%d", s.Path, s.Line, s.EndLine)
	case s.Line > 0:
		return fmt.Sprintf("%s:%d", s.Path, s.Line)
	}
	return s.Path
}

func (s *Source) UnmarshalJSON(b []byte) error {
	var str string
	if json.Unmarshal(b, &str) == nil {
		*s = ParseSource(str)
		return nil
	}
	type plain Source
	var p plain
	if err := Decode(b, &p); err != nil {
		return err
	}
	*s = Source(p)
	return nil
}

// StateSpec declares a component's simulated state.
type StateSpec struct {
	Schema  map[string]any `json:"schema,omitempty"`
	Initial map[string]any `json:"initial,omitempty"`
}

// Component is a unit of the system: a service, module, function, datastore and so on.
type Component struct {
	ID          string         `json:"id"`
	Name        string         `json:"name,omitempty"`
	Kind        string         `json:"kind,omitempty"`
	Parent      string         `json:"parent,omitempty"`
	Layer       string         `json:"layer,omitempty"`
	Summary     string         `json:"summary,omitempty"`
	Description string         `json:"description,omitempty"`
	Sources     []Source       `json:"sources,omitempty"`
	Tags        []string       `json:"tags,omitempty"`
	Attributes  map[string]any `json:"attributes,omitempty"`
	State       *StateSpec     `json:"state,omitempty"`
	// Capacity bounds the calls each instance serves at once (§11.4).
	Capacity *CapacitySpec `json:"capacity,omitempty"`
	// Router answers route calls addressed to the component (§13.1 item 26).
	Router *RouterSpec `json:"router,omitempty"`
	// Limiters are the component's back-pressure limiters (§13.1 item 27).
	Limiters []LimiterSpec `json:"limiters,omitempty"`
	// RefinedBy lists the child ontologies that refine the component
	// (§14.3, §14.11).
	RefinedBy []OntologyRef `json:"refined_by,omitempty"`
}

// CapacitySpec bounds the calls one instance of a component serves at once
// (§11.4): thread pools, stages, connection pools, GPU streams, worker slots.
type CapacitySpec struct {
	// Concurrency is the number of calls served at once (at least 1).
	Concurrency int `json:"concurrency"`
	// QueueLimit bounds the calls waiting for a slot; past it a call fails
	// with {code: overloaded, retryable: true}. Nil means unbounded; 0 means
	// a call that finds every slot busy fails at once.
	QueueLimit *int `json:"queue_limit,omitempty"`
	// QueueTimeoutMS bounds the wait for a slot; 0 means no bound.
	QueueTimeoutMS int64 `json:"queue_timeout_ms,omitempty"`
}

// ErrorSpec declares an error an interface can return.
type ErrorSpec struct {
	Code      string `json:"code"`
	Status    int    `json:"status,omitempty"`
	Retryable bool   `json:"retryable,omitempty"`
	Summary   string `json:"summary,omitempty"`
	// ReachableBy (§13.1 items 33 and 35) says how the error is raised:
	// CEL or a note. The unraised-errors lint reads it; the engine ignores it.
	ReachableBy string `json:"reachable_by,omitempty"`
}

// Latency is a simulated service time: a fixed number of milliseconds, a
// uniform range, or (§11.3) a CEL expression evaluated per call over input,
// state, config and self. It decodes from a number, from {"min", "max"} or
// from an "=cel" string, and encodes back to the same form.
type Latency struct {
	// Min and Max are milliseconds, fractional for sub-millisecond
	// latencies (§13.1 item 16: 0.005 is 5 µs).
	Min float64 `json:"min"`
	Max float64 `json:"max"`
	// Expr is the CEL source of an "=cel" latency, without the leading "=".
	// When it is set, Min and Max are 0 and unused.
	Expr string `json:"-"`
}

func (l Latency) MarshalJSON() ([]byte, error) {
	if l.Expr != "" {
		return json.Marshal("=" + l.Expr)
	}
	if l.Min == l.Max {
		return json.Marshal(l.Min)
	}
	type plain Latency
	return json.Marshal(plain(l))
}

func (l *Latency) UnmarshalJSON(b []byte) error {
	var str string
	if json.Unmarshal(b, &str) == nil {
		src, ok := strings.CutPrefix(str, "=")
		if !ok || strings.TrimSpace(src) == "" {
			return fmt.Errorf(`latency_ms must be milliseconds, {min, max} or an "=cel" expression`)
		}
		*l = Latency{Expr: src}
		return nil
	}
	var n json.Number
	if err := json.Unmarshal(b, &n); err == nil {
		v, err := strconv.ParseFloat(string(n), 64)
		if err != nil || math.IsInf(v, 0) {
			return fmt.Errorf("latency_ms must be a number of milliseconds")
		}
		*l = Latency{Min: v, Max: v}
		return nil
	}
	type plain Latency
	var p plain
	if err := Decode(b, &p); err != nil {
		return err
	}
	*l = Latency(p)
	return nil
}

// Interface is something a component provides: an endpoint, method, function,
// topic or queue. Its ID is "<component>.<name>".
type Interface struct {
	ID          string         `json:"id,omitempty"`
	Component   string         `json:"component"`
	Name        string         `json:"name"`
	Kind        string         `json:"kind,omitempty"`
	Summary     string         `json:"summary,omitempty"`
	Description string         `json:"description,omitempty"`
	Sources     []Source       `json:"sources,omitempty"`
	Attributes  map[string]any `json:"attributes,omitempty"`
	Request     any            `json:"request,omitempty"`
	Response    any            `json:"response,omitempty"`
	Errors      []ErrorSpec    `json:"errors,omitempty"`
	LatencyMS   *Latency       `json:"latency_ms,omitempty"`
	Behavior    []Step         `json:"behavior,omitempty"`
	Store       *StoreSpec     `json:"store,omitempty"`
	// Subscribe lists the topics this interface receives (§11.5). A topic is
	// a slug, conventionally the id of an event-kind interface.
	Subscribe []string `json:"subscribe,omitempty"`
	// Limits are checked at call entry, after capacity and before the
	// behavior, all or nothing (§13.1 item 27).
	Limits []LimitRef `json:"limits,omitempty"`
	// Implements names the parent interface ("<parent component>.<interface>")
	// that this boundary interface of a refinement implements (§14.3, §14.11).
	Implements string `json:"implements,omitempty"`
	// LatencySource records where latency_ms comes from (§14.3).
	LatencySource *LatencySource `json:"latency_source,omitempty"`
	// LatencyByOutcome gives the service time per outcome (§14.13). After
	// the behavior ends, the entries are tried in order over result, input
	// and config; the first match's ms is the call's latency, and latency_ms
	// applies when none matches. With entries, the whole service time is
	// spent when the behavior ends, not before it.
	LatencyByOutcome []OutcomeLatency `json:"latency_by_outcome,omitempty"`
	// StreamsWhen decides per call whether a behavior that can yield
	// streams (§17 item 12): an "=cel" boolean over input, config and the
	// behavior's other variables, evaluated when the call starts. When it
	// is false the caller gets the plain return, not {items, value}, and a
	// yield reached on that call aborts the run. Absent, every call of an
	// interface that can yield streams. Only an interface that can yield
	// may set it.
	StreamsWhen string `json:"streams_when,omitempty"`
}

// OutcomeLatency is one latency_by_outcome entry (§14.13): When is CEL over
// result ({ok, value, error}), input and config; MS is milliseconds or an
// "=cel" expression over the same variables.
type OutcomeLatency struct {
	When string  `json:"when"`
	MS   Latency `json:"ms"`
}

// StoreSpec is a declarative datastore operation. An interface with a store
// and no behavior performs the operation on its component's state instead of
// returning fake data. Rows live in state.<table>, keyed by string id.
type StoreSpec struct {
	Table    string `json:"table"`
	Op       string `json:"op"`
	Key      any    `json:"key,omitempty"`       // template: the row id
	Value    any    `json:"value,omitempty"`     // template: the row (put), a patch (update) or deltas (incr)
	Where    string `json:"where,omitempty"`     // CEL over row and key: a filter (get, query) or a condition (writes)
	Default  any    `json:"default,omitempty"`   // template: what a get miss returns instead of failing
	NotFound string `json:"not_found,omitempty"` // declared error code for a miss
	Conflict string `json:"conflict,omitempty"`  // declared error code for a failed write condition
	// Conditional writes (§13.1 item 25). If is CEL over row (null when
	// absent), key and the behavior variables; IfAbsent (put only) requires
	// that no row exists. A write whose condition fails changes nothing and
	// fails with Conflict, or else condition_failed (status 412).
	If       string `json:"if,omitempty"`
	IfAbsent bool   `json:"if_absent,omitempty"`
}

// StoreWriteOps lists the store operations that change a row, the only
// ones a transact step (§13.1 item 25) takes.
var StoreWriteOps = []string{"put", "update", "delete", "incr"}

// StoreOps lists the supported store operations.
var StoreOps = []string{"get", "put", "update", "delete", "query", "incr"}

// Loop and repetition bounds.
const (
	DefaultForeachMax = 100  // iterations a foreach runs when it sets no max
	MaxForeachMax     = 1000 // the largest max a foreach may set
	MaxRepeatCount    = 100  // the most passes a flow entry may repeat
	MaxTimerCount     = 1000 // the most deliveries a periodic timer may ask for (the per-run timer budget, §11.3)
)

// Publish delivery modes (§11.5).
const (
	DeliverySync  = "sync"
	DeliveryAsync = "async" // the default
)

// Deliveries lists the publish delivery modes.
var Deliveries = []string{DeliverySync, DeliveryAsync}

// Join rule keywords for JoinSpec.Need (§11.2).
const (
	JoinAll = "all" // the default
	JoinAny = "any"
)

// Normalize fills ID from Component and Name, or Component and Name from ID.
func (i *Interface) Normalize() {
	switch {
	case i.Component != "" && i.Name != "":
		if i.ID == "" {
			i.ID = i.Component + "." + i.Name
		}
	case i.ID != "":
		if c, n, ok := strings.Cut(i.ID, "."); ok && i.Component == "" && i.Name == "" {
			i.Component, i.Name = c, n
		}
	}
}

// RetrySpec is a call's retry policy.
type RetrySpec struct {
	MaxAttempts  any     `json:"max_attempts,omitempty"`
	BackoffMS    int64   `json:"backoff_ms,omitempty"`
	Multiplier   float64 `json:"multiplier,omitempty"`
	MaxBackoffMS int64   `json:"max_backoff_ms,omitempty"`
	// Jitter randomizes each wait (AWS-style): "none" (the default) waits
	// the computed backoff, "full" a uniform draw in [0, backoff], "equal"
	// backoff/2 plus a uniform draw in [0, backoff/2]. Draws come from the
	// run's seeded random source.
	Jitter string   `json:"jitter,omitempty"`
	Codes  []string `json:"codes,omitempty"`
	// OnStatus and OnCodes (§13.1 item 35) retry a failure whose status or
	// code is listed, whatever its retryable flag: alternatives to
	// retryable, for a client that retries on 429, 503 and 408.
	OnStatus []int    `json:"on_status,omitempty"`
	OnCodes  []string `json:"on_codes,omitempty"`
	// RespectRetryAfter (§15.3) makes the next attempt wait for the
	// error's headers['retry-after'] (seconds) or data.retry_after_ms,
	// capped by MaxBackoffMS, instead of the backoff.
	RespectRetryAfter bool    `json:"respect_retry_after,omitempty"`
	When              string  `json:"when,omitempty"`
	Title             string  `json:"title,omitempty"`
	Detail            string  `json:"detail,omitempty"`
	Source            *Source `json:"source,omitempty"`
}

// OnError is a call's error handling: "propagate", "continue", or steps.
type OnError struct {
	Mode  string
	Steps []Step
}

func (o OnError) MarshalJSON() ([]byte, error) {
	if o.Mode != "" {
		return json.Marshal(o.Mode)
	}
	return json.Marshal(o.Steps)
}

func (o *OnError) UnmarshalJSON(b []byte) error {
	var s string
	if json.Unmarshal(b, &s) == nil {
		*o = OnError{Mode: s}
		return nil
	}
	var steps []Step
	if err := Decode(b, &steps); err != nil {
		return fmt.Errorf("on_error must be \"propagate\", \"continue\" or a list of steps: %w", err)
	}
	*o = OnError{Steps: steps}
	return nil
}

// Step is one instruction of a behavior. It carries at most one action.
type Step struct {
	Title  string  `json:"title,omitempty"`
	Detail string  `json:"detail,omitempty"`
	Source *Source `json:"source,omitempty"`
	When   string  `json:"when,omitempty"`

	Set map[string]any `json:"set,omitempty"`

	Call      string          `json:"call,omitempty"`
	Route     *RouteCall      `json:"-"` // call written as a route object (§13.1 item 26); Call is then empty
	Input     json.RawMessage `json:"input,omitempty"`
	Fill      bool            `json:"fill,omitempty"`
	As        string          `json:"as,omitempty"`
	TimeoutMS IntOrExpr       `json:"timeout_ms,omitzero"`
	Retry     *RetrySpec      `json:"retry,omitempty"`
	OnError   *OnError        `json:"on_error,omitempty"`
	Targets   []string        `json:"targets,omitempty"`

	If   string `json:"if,omitempty"`
	Then []Step `json:"then,omitempty"`
	Else []Step `json:"else,omitempty"`

	Choice  string            `json:"choice,omitempty"`
	Options map[string][]Step `json:"options,omitempty"`
	Default string            `json:"default,omitempty"`

	Return json.RawMessage `json:"return,omitempty"`
	Fail   json.RawMessage `json:"fail,omitempty"`
	Emit   string          `json:"emit,omitempty"`
	Wait   any             `json:"wait,omitempty"`

	Foreach any    `json:"foreach,omitempty"` // a literal list or "=cel" (a list or a map)
	Index   string `json:"index,omitempty"`
	Steps   []Step `json:"steps,omitempty"`
	Max     int    `json:"max,omitempty"`

	Break    bool `json:"break,omitempty"`
	Continue bool `json:"continue,omitempty"`

	// parallel (§11.2): run branches concurrently in virtual time and join.
	// Parallel is a literal list or map, or "=cel" (a list, or a map in key
	// order); each item runs Steps with vars.<As> (default "item") and
	// vars.<Index> (default "index"). Branches is the alternative form: a
	// fixed list of step lists. Exactly one of the two is set. TimeoutMS
	// bounds the join as a whole.
	Parallel       any        `json:"parallel,omitempty"`
	Branches       [][]Step   `json:"branches,omitempty"`
	Join           *JoinSpec  `json:"join,omitempty"`
	StaggerMS      IntOrExpr  `json:"stagger_ms,omitzero"`
	AsResult       string     `json:"as_result,omitempty"`
	OnInsufficient *ErrorSpec `json:"on_insufficient,omitempty"` // default {code: insufficient, retryable: true}
	// OnLate (§13.1 item 12) runs once for each branch that finishes after
	// the join completed, at that branch's end time, as async work
	// delivered like a timer, with vars.late set to the branch result.
	OnLate []Step `json:"on_late,omitempty"`

	// publish (§11.5): deliver Input to every subscriber of the topic.
	// Delivery is "sync" or "async" (the default, like emit). OnError applies
	// to sync delivery: subscriber errors fail the publisher only with
	// on_error: propagate.
	Publish  string `json:"publish,omitempty"`
	Delivery string `json:"delivery,omitempty"`

	// On targets an instance (§11.1) for call, emit and publish: an
	// instance name or "=cel".
	On string `json:"on,omitempty"`
	// Timers (§11.3) for emit and publish: AfterMS delays the first
	// delivery; EveryMS with Count makes it periodic (Count deliveries,
	// EveryMS apart).
	AfterMS IntOrExpr `json:"after_ms,omitzero"`
	EveryMS IntOrExpr `json:"every_ms,omitzero"`
	Count   IntOrExpr `json:"count,omitzero"`
	// The numeric fields of a step (timeout_ms, stagger_ms, after_ms,
	// every_ms, count, deadline_ms) are IntOrExpr: a number or an "=cel"
	// template evaluated when the step runs (§13.1).
	//
	// DeadlineMS (§11.3) for call: a deadline relative to the call's start,
	// inherited by nested calls and branches; the earlier deadline wins.
	DeadlineMS IntOrExpr `json:"deadline_ms,omitzero"`

	// Cancellation (§13.1 item 14). Token ties a call, wait or parallel
	// (and, as an engine addition, the pending deliveries of an emit or
	// publish) to a run-wide cancellation token: a name or "=cel". Cancel
	// is an action that cancels the named token.
	Token  string `json:"token,omitempty"`
	Cancel string `json:"cancel,omitempty"`
	// Restart is an action that restarts a component instance's group.
	Restart *Restart `json:"restart,omitempty"`

	// Rendezvous (§13.1 item 17) is an action that meets other tasks at a
	// name (or "=cel"): it waits until Count tasks have arrived in the same
	// generation, then all resume at the last arrival plus LatencyMS, with
	// vars.<As> = {values, index, count}. Value is this arrival's template;
	// TimeoutMS bounds the wait.
	Rendezvous string          `json:"rendezvous,omitempty"`
	Value      json.RawMessage `json:"value,omitempty"`
	LatencyMS  *Latency        `json:"latency_ms,omitempty"`

	// Streams (§13.1 item 18). Yield is an action that sends one item (a
	// template) to the caller while the behavior keeps running. A call
	// with Stream runs OnItem for each item as it is yielded, with
	// vars.item and vars.item_index; without Stream, the caller gets
	// {items, value} when the callee returns.
	Yield  json.RawMessage `json:"yield,omitempty"`
	Stream bool            `json:"stream,omitempty"`
	OnItem []Step          `json:"on_item,omitempty"`
	// Stream flow control (§16.4; streamflow.go): Window frames in flight
	// before the producer blocks, StallMS the longest it may block.
	Window  IntOrExpr `json:"window,omitzero"`
	StallMS IntOrExpr `json:"stall_ms,omitzero"`
	// Byte windows and relays (§17 item 5; streamflow.go): WindowBytes
	// bounds the bytes in flight (each frame's size field, else
	// bytes(json(frame))). Relay on a streaming call made by a behavior
	// that is itself streamed to its caller applies the outer windows to
	// the inner producer, so back pressure crosses the forwarding hop.
	WindowBytes IntOrExpr `json:"window_bytes,omitzero"`
	Relay       bool      `json:"relay,omitempty"`
	// Channels (§13.1 item 18). Put is an action that adds Value to a
	// run-wide FIFO channel (a name or "=cel"), blocking while the channel
	// holds Capacity items (no bound when zero). Receive is an action that
	// blocks until an item is available and sets vars.<As> to it. Both
	// take timeout_ms and on_error.
	Put      string    `json:"put,omitempty"`
	Receive  string    `json:"receive,omitempty"`
	Capacity IntOrExpr `json:"capacity,omitzero"`
	// Kill is an action that terminates a component instance (§13.1 item
	// 18) until a restart revives it.
	Kill *Kill `json:"kill,omitempty"`
	// Transact (§13.1 item 25) is an action that applies store writes to
	// the running instance's state all or nothing: if any write's
	// condition fails, none is applied and the step fails like a call
	// (as and on_error apply).
	Transact []StoreSpec `json:"transact,omitempty"`
	// Limiters (§13.1 item 27). Admit decides one limiter or several, all
	// or nothing; Charge consumes after the fact; Release frees a lease.
	Admit   *AdmitSpec   `json:"admit,omitempty"`
	Charge  *ChargeSpec  `json:"charge,omitempty"`
	Release *ReleaseSpec `json:"release,omitempty"`
	// Sessions (§13.1 item 35). Session is a call option: a key (a literal
	// or "=cel") the call carries while it is in flight. Close is an action
	// that cancels every call in flight carrying its session key; their
	// callers get {code: canceled}.
	Session string     `json:"session,omitempty"`
	Close   *CloseSpec `json:"close,omitempty"`
	// Signal (§17 item 2, waitspec.go) is an action that delivers a named
	// signal (a name or "=cel"): it wakes the blocking waits waiting for it.
	Signal string `json:"signal,omitempty"`
}

// CloseSpec is a close action (§13.1 item 35): the death of a tunnel or
// connection that the peer sees. Session is a literal key or "=cel".
type CloseSpec struct {
	Session string `json:"session"`
}

// Kill terminates a component instance (§13.1 item 18): its running tasks
// stop, its pending calls fail with killed, its callers get peer-killed,
// and its state is marked dead: true until a restart. Component names a
// component of the instance group; Instance is an instance name or "=cel"
// (empty for a component without instances, or, in a behavior, the
// running instance).
type Kill struct {
	Component string `json:"component"`
	Instance  string `json:"instance,omitempty"`
}

// Restart resets the state of every component in an instance group to its
// starting-world state, except the components in Keep, and cancels the
// instance's pending tasks and timers (§13.1 item 14). Component names a
// component of the group; Instance is an instance name or "=cel" (empty for
// a component without instances, or, in a behavior, the running instance).
type Restart struct {
	Component string   `json:"component"`
	Instance  string   `json:"instance,omitempty"`
	Keep      []string `json:"keep,omitempty"`
}

// JoinSpec is a parallel step's join rule (§11.2).
type JoinSpec struct {
	// Need is how many branches must succeed: a whole number (json.Number
	// after strict decoding, int64 after expr.Native), "all" (the default
	// when nil), "any" (one), or an "=cel" expression giving a number.
	Need any `json:"need,omitempty"`
	// CountUnstarted (§13.1 item 12; nil means true) says whether a
	// staggered branch that has not started yet counts toward the
	// successes still possible. With false, the join fails as soon as need
	// exceeds the successes plus the running branches.
	CountUnstarted *bool `json:"count_unstarted,omitempty"`
}

// Unstarted reports whether unstarted branches count toward possible
// successes: CountUnstarted, true by default.
func (j *JoinSpec) Unstarted() bool { return j == nil || j.CountUnstarted == nil || *j.CountUnstarted }

// IsParallel reports whether the step is a parallel step, in either form.
func (s Step) IsParallel() bool { return s.Parallel != nil || s.Branches != nil }

// Actions lists the action keys a step carries.
func (s Step) Actions() []string {
	var a []string
	if s.Set != nil {
		a = append(a, "set")
	}
	if s.Call != "" || s.Route != nil {
		a = append(a, "call")
	}
	if s.If != "" {
		a = append(a, "if")
	}
	if s.Choice != "" {
		a = append(a, "choice")
	}
	if s.Return != nil {
		a = append(a, "return")
	}
	if s.Fail != nil {
		a = append(a, "fail")
	}
	if s.Emit != "" {
		a = append(a, "emit")
	}
	if s.Wait != nil {
		a = append(a, "wait")
	}
	if s.Signal != "" {
		a = append(a, "signal")
	}
	if s.Foreach != nil {
		a = append(a, "foreach")
	}
	if s.IsParallel() {
		a = append(a, "parallel")
	}
	if s.Publish != "" {
		a = append(a, "publish")
	}
	if s.Break {
		a = append(a, "break")
	}
	if s.Continue {
		a = append(a, "continue")
	}
	if s.Cancel != "" {
		a = append(a, "cancel")
	}
	if s.Restart != nil {
		a = append(a, "restart")
	}
	if s.Rendezvous != "" {
		a = append(a, "rendezvous")
	}
	if s.Yield != nil {
		a = append(a, "yield")
	}
	if s.Put != "" {
		a = append(a, "put")
	}
	if s.Receive != "" {
		a = append(a, "receive")
	}
	if s.Kill != nil {
		a = append(a, "kill")
	}
	if s.Transact != nil {
		a = append(a, "transact")
	}
	if s.Admit != nil {
		a = append(a, "admit")
	}
	if s.Charge != nil {
		a = append(a, "charge")
	}
	if s.Release != nil {
		a = append(a, "release")
	}
	if s.Close != nil {
		a = append(a, "close")
	}
	return a
}

// Link is an explicit architectural relation between components or interfaces.
type Link struct {
	ID         string         `json:"id"`
	From       string         `json:"from"`
	To         string         `json:"to"`
	Kind       string         `json:"kind,omitempty"`
	Label      string         `json:"label,omitempty"`
	Protocol   string         `json:"protocol,omitempty"`
	Summary    string         `json:"summary,omitempty"`
	Sources    []Source       `json:"sources,omitempty"`
	Attributes map[string]any `json:"attributes,omitempty"`
}

// Schema is a named JSON Schema that interfaces and other schemas can reference.
type Schema struct {
	ID      string         `json:"id"`
	Summary string         `json:"summary,omitempty"`
	Schema  map[string]any `json:"schema"`
}

// FlowEntry is where a flow starts: a caller invoking an interface.
type FlowEntry struct {
	Caller    string          `json:"caller"`
	Interface string          `json:"interface"`
	Input     json.RawMessage `json:"input,omitempty"`
	Repeat    *Repeat         `json:"repeat,omitempty"`
	// On names the instance the entry runs on (§11.1): an instance name or
	// "=cel". Without it the entry runs on the first instance of the entry
	// component's group.
	On string `json:"on,omitempty"`
	// DeadlineMS is a deadline relative to the entry's start (§11.3): a
	// number or an "=cel" template evaluated in the behavior environment
	// when each pass starts (§13.1), so it can read config.
	DeadlineMS IntOrExpr `json:"deadline_ms,omitzero"`
}

// Repeat runs a flow's entry several times, as a reconciler or cron would:
// Count passes, with the virtual clock advanced IntervalMS between passes.
// State, ctx and the clock carry across passes.
type Repeat struct {
	Count      int     `json:"count"`
	IntervalMS float64 `json:"interval_ms,omitempty"`
	// InitialDelayMS advances the clock before the first pass (§11.3).
	// Both may be fractional (§13.1 item 16).
	InitialDelayMS float64 `json:"initial_delay_ms,omitempty"`
}

// FlowStep is a narrative step of a flow, for explanation and the trace-level view.
type FlowStep struct {
	Component string  `json:"component"`
	Title     string  `json:"title"`
	Detail    string  `json:"detail,omitempty"`
	Source    *Source `json:"source,omitempty"`
}

// Flow is a user or system workflow.
type Flow struct {
	ID          string     `json:"id"`
	Name        string     `json:"name,omitempty"`
	Description string     `json:"description,omitempty"`
	Entry       *FlowEntry `json:"entry,omitempty"`
	Steps       []FlowStep `json:"steps,omitempty"`
	Sources     []Source   `json:"sources,omitempty"`
	Tags        []string   `json:"tags,omitempty"`
}

// Fault is an injected failure applied when a call reaches its target.
type Fault struct {
	Target    string  `json:"target"`
	Type      string  `json:"type"`
	Code      string  `json:"code,omitempty"`
	Status    int     `json:"status,omitempty"`
	Message   string  `json:"message,omitempty"`
	Retryable *bool   `json:"retryable,omitempty"`
	LatencyMS float64 `json:"latency_ms,omitempty"` // may be fractional (§13.1 item 16)
	Calls     []int   `json:"calls,omitempty"`
	// Instance limits the fault to one instance (§11.1); empty means every instance.
	Instance string `json:"instance,omitempty"`
	// AtMS is when a kill fault (§13.1 item 18) terminates the target
	// component's instance, in virtual ms.
	AtMS *float64 `json:"at_ms,omitempty"`
	// AfterSteps is where a crash fault (§13.1 item 25) stops the callee:
	// after this many of its behavior's steps (a store operation counts as
	// one step). Required for crash, and only for crash.
	AfterSteps *int `json:"after_steps,omitempty"`
	// Match (§13.1 item 35) is CEL over the call's input (and the callee's
	// state, config and self): the fault applies only to calls for which it
	// is true. Caller is an interface id or a glob ("billing.*") the
	// calling interface must match; a scenario step or flow entry, which
	// has no calling interface, matches by its caller component. With
	// either, calls counts the invocations that match.
	Match  string `json:"match,omitempty"`
	Caller string `json:"caller,omitempty"`
	// Forever (§13.1 item 35), on a hang, timeout or lost_reply fault,
	// never answers: the call ends only through the caller's timeout_ms, a
	// deadline, a cancel or a kill, and otherwise stays pending until the
	// run ends.
	Forever bool `json:"forever,omitempty"`
	// Data and Headers (§15.3) are the failure's payload: they appear on
	// error.data and error.headers (at lower-case keys).
	Data    any            `json:"data,omitempty"`
	Headers map[string]any `json:"headers,omitempty"`
}

// FaultTypes lists the supported per-call fault types. lost_reply and
// crash (§13.1 item 25) apply effects and still fail the caller.
var FaultTypes = []string{"unavailable", "error", "latency", "timeout", FaultLostReply, FaultCrash, FaultHang}

// FaultHang is the fault type of a callee that never answers (§13.1 item
// 35): timeout's other name, which takes forever: true.
const FaultHang = "hang"

// Crash-after-effect fault types (§13.1 item 25).
const (
	FaultLostReply = "lost_reply" // the callee runs to the end; its reply never reaches the caller
	FaultCrash     = "crash"      // the callee stops after after_steps steps; the caller gets crashed
)

// FaultKill is the fault type that terminates an instance at at_ms
// (§13.1 item 18) rather than affecting calls.
const FaultKill = "kill"

// Scenario is a configured run of a flow with expected outcomes. With Steps
// (§11.7) it is a sequence of entry calls instead, and Flow is optional.
//
// State keys are "<component>" or "<component>@<instance>" (§11.1). The
// starting world is the fixtures, in order, then the scenario's own
// Topology, Clock, Config and State; see Index.ScenarioWorld.
type Scenario struct {
	ID          string                    `json:"id"`
	Flow        string                    `json:"flow,omitempty"`
	Name        string                    `json:"name,omitempty"`
	Description string                    `json:"description,omitempty"`
	Seed        *int64                    `json:"seed,omitempty"`
	Input       json.RawMessage           `json:"input,omitempty"`
	Choices     map[string]Choice         `json:"choices,omitempty"`
	State       map[string]map[string]any `json:"state,omitempty"`
	Faults      []Fault                   `json:"faults,omitempty"`
	Expect      []string                  `json:"expect,omitempty"`
	// Invariants hold under every schedule exploration tries (§16.2):
	// CEL over the final state, trace, io and calls, like expect. With
	// invariants, --explore checks expect only on the default schedule.
	Invariants []string `json:"invariants,omitempty"`
	// Tags label the scenario (§17 item 1, scenariotags.go): exploration
	// selects on them, as do check's --scenario-tag and the reports.
	Tags []string `json:"tags,omitempty"`

	Fixtures []string            `json:"fixtures,omitempty"`
	Topology map[string][]string `json:"topology,omitempty"`
	Clock    *Clock              `json:"clock,omitempty"`
	Config   map[string]any      `json:"config,omitempty"`
	Steps    []ScenarioStep      `json:"steps,omitempty"`
	Mocks    []Mock              `json:"mocks,omitempty"`
	// MaxVirtualMS ends a run whose tasks or timers are still pending at
	// this virtual time, with a warning (§13.1 item 14). Nil means
	// DefaultMaxVirtualMS.
	MaxVirtualMS *int64 `json:"max_virtual_ms,omitempty"`
	// MaxEvents caps the trace of this scenario's runs (§13.1 item 35):
	// past it the run aborts. Nil means DefaultMaxEvents; at most
	// MaxMaxEvents.
	MaxEvents *int64 `json:"max_events,omitempty"`
	// CostLimit bounds the CEL work of one evaluation in this scenario's
	// runs (§13.1 item 18). Nil means expr.DefaultCostLimit (10,000,000).
	CostLimit *int64 `json:"cost_limit,omitempty"`
	// MaxIterations is the run's loop cap (§15.3): foreach iterations in
	// the whole run. Nil means DefaultMaxIterations; at most
	// MaxMaxIterations. MaxCELCost is cost_limit's other name.
	MaxIterations *int64 `json:"max_iterations,omitempty"`
	MaxCELCost    *int64 `json:"max_cel_cost,omitempty"`
	// Limiters seeds limiter state (§13.1 item 27), over the fixtures'.
	Limiters LimiterSeeds `json:"limiters,omitempty"`
	// Resolution chooses, per component path, black_box (the default) or
	// refined: the component replaced by its child ontology (§14.5, §14.11).
	Resolution map[string]string `json:"resolution,omitempty"`
}

// DefaultMaxVirtualMS is the virtual time a run stops at by default (one
// hour, §13.1 item 14).
const DefaultMaxVirtualMS = 3_600_000

// DefaultMaxEvents and MaxMaxEvents are a scenario's default and largest
// max_events (§13.1 item 35).
const (
	DefaultMaxEvents = 20_000
	MaxMaxEvents     = 1_000_000
)

// GroupFlow is the flow a scenario is grouped under: Flow, or else the flow
// of its first step (§11.7). It is "" when neither names a flow.
func (s *Scenario) GroupFlow() string {
	if s.Flow != "" || len(s.Steps) == 0 {
		return s.Flow
	}
	return s.Steps[0].Flow
}

// ScenarioStep is one entry call of a multi-step scenario (§11.7): a flow's
// entry (with Input merged over the entry input), or an interface called by
// Caller. Templates in Input and On see steps.<as> and steps[i].
type ScenarioStep struct {
	Flow      string            `json:"flow,omitempty"`
	Interface string            `json:"interface,omitempty"`
	Caller    string            `json:"caller,omitempty"`
	Input     json.RawMessage   `json:"input,omitempty"`
	On        string            `json:"on,omitempty"` // an instance name or "=cel"
	Choices   map[string]Choice `json:"choices,omitempty"`
	// Repeat runs the step's call several times (§13.1 item 24), like a
	// flow entry's repeat. A flow step does not inherit its entry's repeat:
	// without its own it makes one pass.
	Repeat *Repeat `json:"repeat,omitempty"`
	// DeadlineMS is a deadline relative to the step's start: a number or
	// an "=cel" template evaluated when the step starts (§13.1).
	DeadlineMS IntOrExpr `json:"deadline_ms,omitzero"`
	// AtMS is the absolute virtual time the step starts at, even while
	// earlier steps or timers are still running (§13.1 item 14). Nil means
	// when the previous step's own call tree has finished.
	AtMS *float64 `json:"at_ms,omitempty"` // may be fractional (§13.1 item 16)
	As   string   `json:"as,omitempty"`
	// Await false starts the step and moves straight on to the next one
	// (§13.1 item 14). Nil means true.
	Await *bool `json:"await,omitempty"`
	// Lane names a host thread that issues this step (§17 item 11): steps
	// in the same lane keep their program order under exploration, even
	// with await: false and equal start times. Steps in different lanes,
	// or in none (the default), are reordered as ties.
	Lane string `json:"lane,omitempty"`
	// Cancel and Restart make the step a cancel or a restart instead of a
	// call (§13.1 item 14); such a step names no flow or interface.
	Cancel  string   `json:"cancel,omitempty"`
	Restart *Restart `json:"restart,omitempty"`
	// Kill terminates an instance (§13.1 item 18); such a step names no
	// flow or interface either.
	Kill *Kill `json:"kill,omitempty"`
	// Limiters seeds limiter state when the step starts (§13.1 item 27).
	Limiters LimiterSeeds `json:"limiters,omitempty"`
	// Set changes component state during the run (§15.3), keyed
	// "<component>[@instance]", then by a dotted path in that state; the
	// values are templates. Such a step names no flow or interface.
	Set map[string]map[string]any `json:"set,omitempty"`
}

// IsControl reports whether the step is a cancel, restart, kill or set
// step rather than a call.
func (s ScenarioStep) IsControl() bool {
	return s.Cancel != "" || s.Restart != nil || s.Kill != nil || s.Set != nil
}

// Awaited reports whether the next step waits for this one: Await, true by
// default.
func (s ScenarioStep) Awaited() bool { return s.Await == nil || *s.Await }

// Mock replaces matching calls of an interface with a fixed outcome (§11.8).
// Exactly one of Return and Fail is set; both are templates like a step's
// return and fail. When is CEL over input; Calls lists the 1-based matching
// invocations affected (all when empty).
type Mock struct {
	Interface string          `json:"interface"`
	Instance  string          `json:"instance,omitempty"`
	When      string          `json:"when,omitempty"`
	Return    json.RawMessage `json:"return,omitempty"`
	Fail      json.RawMessage `json:"fail,omitempty"`
	Calls     []int           `json:"calls,omitempty"`
}

// DocSource records what an ontology was derived from.
type DocSource struct {
	Repo string `json:"repo,omitempty"`
	SHA  string `json:"sha,omitempty"`
	URL  string `json:"url,omitempty"`
}

// Document is a whole ontology.
type Document struct {
	SchemaVersion int         `json:"schema_version"`
	ID            string      `json:"id,omitempty"`
	Name          string      `json:"name,omitempty"`
	Description   string      `json:"description,omitempty"`
	Source        *DocSource  `json:"source,omitempty"`
	Components    []Component `json:"components"`
	Interfaces    []Interface `json:"interfaces"`
	Links         []Link      `json:"links"`
	Schemas       []Schema    `json:"schemas"`
	Flows         []Flow      `json:"flows"`
	Scenarios     []Scenario  `json:"scenarios"`
	// The §11 kinds are omitted when empty, so a document that uses none of
	// them encodes exactly as before.
	Configs  []Config  `json:"configs,omitempty"`
	Fixtures []Fixture `json:"fixtures,omitempty"`

	// The §14 hierarchy fields, omitted when empty.
	// Level is one of Levels; empty means LevelSystem.
	Level string `json:"level,omitempty"`
	// Refines names the parent component this document refines.
	Refines *RefinesRef `json:"refines,omitempty"`
	// Imports are substrate ontologies merged in, under their as: prefix.
	Imports []ImportRef `json:"imports,omitempty"`

	// Refinements are loaded child documents keyed by component path, and
	// ImportDocs loaded imports keyed by their ontology reference. A loader
	// fills them; they are never encoded. A run composes them (§14.11).
	Refinements map[string]*Document `json:"-"`
	ImportDocs  map[string]*Document `json:"-"`
}

// Decode strictly decodes JSON: unknown fields are errors, numbers keep their
// text (json.Number), and trailing data is refused.
func Decode(b []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err := dec.Decode(v); err != nil {
		return err
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return errors.New("unexpected data after the JSON value")
	}
	return nil
}

// Entity is one stored entity: its kind, id and JSON spec.
type Entity struct {
	Kind string          `json:"kind"`
	ID   string          `json:"id"`
	Spec json.RawMessage `json:"spec"`
}

// DecodeEntity strictly decodes the spec of an entity of the given kind and
// returns the typed value and its ID.
func DecodeEntity(kind string, spec []byte) (any, string, error) {
	switch kind {
	case KindComponent:
		var v Component
		err := Decode(spec, &v)
		return v, v.ID, err
	case KindInterface:
		var v Interface
		err := Decode(spec, &v)
		v.Normalize()
		return v, v.ID, err
	case KindLink:
		var v Link
		err := Decode(spec, &v)
		return v, v.ID, err
	case KindSchema:
		var v Schema
		err := Decode(spec, &v)
		return v, v.ID, err
	case KindFlow:
		var v Flow
		err := Decode(spec, &v)
		return v, v.ID, err
	case KindScenario:
		var v Scenario
		err := Decode(spec, &v)
		return v, v.ID, err
	case KindConfig:
		var v Config
		err := Decode(spec, &v)
		return v, v.ID, err
	case KindFixture:
		var v Fixture
		err := Decode(spec, &v)
		return v, v.ID, err
	}
	return nil, "", fmt.Errorf("unknown kind %q", kind)
}

// Entities flattens a document into stored entities, sorted by kind order and id.
func (d *Document) Entities() ([]Entity, error) {
	var out []Entity
	add := func(kind, id string, v any) error {
		b, err := json.Marshal(v)
		if err != nil {
			return err
		}
		out = append(out, Entity{Kind: kind, ID: id, Spec: b})
		return nil
	}
	for _, c := range d.Components {
		if err := add(KindComponent, c.ID, c); err != nil {
			return nil, err
		}
	}
	for _, i := range d.Interfaces {
		i.Normalize()
		if err := add(KindInterface, i.ID, i); err != nil {
			return nil, err
		}
	}
	for _, l := range d.Links {
		if err := add(KindLink, l.ID, l); err != nil {
			return nil, err
		}
	}
	for _, s := range d.Schemas {
		if err := add(KindSchema, s.ID, s); err != nil {
			return nil, err
		}
	}
	for _, f := range d.Flows {
		if err := add(KindFlow, f.ID, f); err != nil {
			return nil, err
		}
	}
	for _, s := range d.Scenarios {
		if err := add(KindScenario, s.ID, s); err != nil {
			return nil, err
		}
	}
	for _, c := range d.Configs {
		if err := add(KindConfig, c.ID, c); err != nil {
			return nil, err
		}
	}
	for _, f := range d.Fixtures {
		if err := add(KindFixture, f.ID, f); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// FromEntities assembles a document from stored entities. Entities whose
// spec does not decode are reported, not dropped silently.
func FromEntities(entities []Entity) (*Document, []Issue) {
	d := &Document{SchemaVersion: SchemaVersion}
	var issues []Issue
	entities = append([]Entity(nil), entities...) // sort a copy, not the caller's slice
	sort.SliceStable(entities, func(a, b int) bool {
		if entities[a].Kind != entities[b].Kind {
			return kindOrder(entities[a].Kind) < kindOrder(entities[b].Kind)
		}
		return entities[a].ID < entities[b].ID
	})
	for _, e := range entities {
		v, _, err := DecodeEntity(e.Kind, e.Spec)
		if err != nil {
			issues = append(issues, Issue{Path: Plural(e.Kind) + "[" + e.ID + "]", Message: "does not decode: " + err.Error(), Severity: SeverityError})
			continue
		}
		switch t := v.(type) {
		case Component:
			d.Components = append(d.Components, t)
		case Interface:
			d.Interfaces = append(d.Interfaces, t)
		case Link:
			d.Links = append(d.Links, t)
		case Schema:
			d.Schemas = append(d.Schemas, t)
		case Flow:
			d.Flows = append(d.Flows, t)
		case Scenario:
			d.Scenarios = append(d.Scenarios, t)
		case Config:
			d.Configs = append(d.Configs, t)
		case Fixture:
			d.Fixtures = append(d.Fixtures, t)
		}
	}
	d.EnsureSlices()
	return d, issues
}

// EnsureSlices replaces nil slices so the document encodes [] rather than null.
func (d *Document) EnsureSlices() {
	if d.Components == nil {
		d.Components = []Component{}
	}
	if d.Interfaces == nil {
		d.Interfaces = []Interface{}
	}
	if d.Links == nil {
		d.Links = []Link{}
	}
	if d.Schemas == nil {
		d.Schemas = []Schema{}
	}
	if d.Flows == nil {
		d.Flows = []Flow{}
	}
	if d.Scenarios == nil {
		d.Scenarios = []Scenario{}
	}
	if d.Configs == nil {
		d.Configs = []Config{}
	}
	if d.Fixtures == nil {
		d.Fixtures = []Fixture{}
	}
}

func kindOrder(k string) int {
	for i, x := range Kinds {
		if x == k {
			return i
		}
	}
	return len(Kinds)
}

// Index gives lookups over a document.
type Index struct {
	Doc        *Document
	Components map[string]*Component
	Interfaces map[string]*Interface
	Schemas    map[string]*Schema
	Flows      map[string]*Flow
	Scenarios  map[string]*Scenario
	Configs    map[string]*Config
	Fixtures   map[string]*Fixture
	Children   map[string][]string
	ByComp     map[string][]string
	// Subscribers maps a topic to the interfaces subscribing to it, sorted
	// by interface id (the §11.5 delivery order).
	Subscribers map[string][]string
}

// NewIndex builds an index. Duplicate IDs keep the first occurrence; Validate reports them.
func NewIndex(d *Document) *Index {
	x := &Index{
		Doc: d, Components: map[string]*Component{}, Interfaces: map[string]*Interface{},
		Schemas: map[string]*Schema{}, Flows: map[string]*Flow{}, Scenarios: map[string]*Scenario{},
		Configs: map[string]*Config{}, Fixtures: map[string]*Fixture{},
		Children: map[string][]string{}, ByComp: map[string][]string{},
	}
	for i := range d.Components {
		c := &d.Components[i]
		if _, dup := x.Components[c.ID]; !dup {
			x.Components[c.ID] = c
		}
	}
	for _, c := range d.Components {
		if c.Parent != "" {
			x.Children[c.Parent] = append(x.Children[c.Parent], c.ID)
		}
	}
	for i := range d.Interfaces {
		f := &d.Interfaces[i]
		f.Normalize()
		if _, dup := x.Interfaces[f.ID]; !dup {
			x.Interfaces[f.ID] = f
			x.ByComp[f.Component] = append(x.ByComp[f.Component], f.ID)
		}
	}
	for i := range d.Schemas {
		s := &d.Schemas[i]
		if _, dup := x.Schemas[s.ID]; !dup {
			x.Schemas[s.ID] = s
		}
	}
	for i := range d.Flows {
		f := &d.Flows[i]
		if _, dup := x.Flows[f.ID]; !dup {
			x.Flows[f.ID] = f
		}
	}
	for i := range d.Scenarios {
		s := &d.Scenarios[i]
		if _, dup := x.Scenarios[s.ID]; !dup {
			x.Scenarios[s.ID] = s
		}
	}
	for i := range d.Configs {
		c := &d.Configs[i]
		if _, dup := x.Configs[c.ID]; !dup {
			x.Configs[c.ID] = c
		}
	}
	for i := range d.Fixtures {
		f := &d.Fixtures[i]
		if _, dup := x.Fixtures[f.ID]; !dup {
			x.Fixtures[f.ID] = f
		}
	}
	x.Subscribers = subscribers(d.Interfaces)
	return x
}

// subscribers maps each topic to the ids of the interfaces subscribing to
// it, sorted and without duplicates. The first occurrence of a duplicated
// interface id wins, as in NewIndex.
func subscribers(ifaces []Interface) map[string][]string {
	out := map[string][]string{}
	seen := map[string]bool{}
	for _, f := range ifaces {
		f.Normalize() // f is a copy
		if seen[f.ID] {
			continue
		}
		seen[f.ID] = true
		for _, t := range f.Subscribe {
			if !contains(out[t], f.ID) {
				out[t] = append(out[t], f.ID)
			}
		}
	}
	for _, ids := range out {
		sort.Strings(ids)
	}
	return out
}

// ResolveSchema resolves a schema reference: a schema ID, "#/schemas/<id>", an
// object with "$ref", or an inline schema object.
func (x *Index) ResolveSchema(ref any) (map[string]any, bool) {
	for depth := 0; depth < 16; depth++ {
		switch t := ref.(type) {
		case nil:
			return nil, false
		case string:
			s, ok := x.Schemas[strings.TrimPrefix(t, "#/schemas/")]
			if !ok {
				return nil, false
			}
			ref = s.Schema
			continue
		case map[string]any:
			if r, ok := t["$ref"].(string); ok && len(t) == 1 {
				ref = r
				continue
			}
			return t, true
		default:
			return nil, false
		}
	}
	return nil, false
}

// SchemaRef returns a resolver for "$ref" values inside schemas.
func (x *Index) SchemaRef() func(string) (map[string]any, bool) {
	return func(ref string) (map[string]any, bool) { return x.ResolveSchema(ref) }
}

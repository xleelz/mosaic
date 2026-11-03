package model

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/expr"
)

// Config is a named setting of the modelled system (§11.6): a deployed
// value next to the code default, so that differences stay visible. CEL
// sees the effective values as the map `config`, keyed by id.
type Config struct {
	ID          string         `json:"id"`
	Type        string         `json:"type,omitempty"`    // one of ConfigTypes; empty means untyped
	Value       any            `json:"value,omitempty"`   // the deployed value
	Default     any            `json:"default,omitempty"` // the code default
	Summary     string         `json:"summary,omitempty"`
	Description string         `json:"description,omitempty"`
	Sources     []Source       `json:"sources,omitempty"`
	Attributes  map[string]any `json:"attributes,omitempty"`
	Tags        []string       `json:"tags,omitempty"`
}

// ConfigTypes lists the allowed config types (the JSON Schema type names).
var ConfigTypes = []string{"string", "integer", "number", "boolean", "object", "array"}

// Effective is the value CEL sees before overrides: Value, or Default when
// Value is unset.
func (c *Config) Effective() any {
	if c.Value != nil {
		return c.Value
	}
	return c.Default
}

// Clock sets the epoch the virtual clock starts from (§11.3): `now` is
// epoch_ms + virtual ms. Epoch is an RFC 3339 time; EpochMS is milliseconds
// since the Unix epoch. At most one of them is set (Validate checks it);
// when both are, Epoch wins.
type Clock struct {
	Epoch   string `json:"epoch,omitempty"`
	EpochMS int64  `json:"epoch_ms,omitempty"`
}

// EpochMillis returns the clock's epoch in milliseconds since the Unix epoch.
func (c *Clock) EpochMillis() (int64, error) {
	if c == nil {
		return 0, nil
	}
	if c.Epoch != "" {
		t, err := time.Parse(time.RFC3339Nano, c.Epoch)
		if err != nil {
			return 0, fmt.Errorf("epoch must be an RFC 3339 time such as 2026-10-30T00:00:00Z: %v", err)
		}
		return t.UnixMilli(), nil
	}
	return c.EpochMS, nil
}

// Fixture is a named, shared starting world (§11.7). Extends names fixtures
// applied first, in order. State keys are "<component>" or
// "<component>@<instance>"; topology keys are components.
type Fixture struct {
	ID       string                    `json:"id"`
	Name     string                    `json:"name,omitempty"`
	Summary  string                    `json:"summary,omitempty"`
	Topology map[string][]string       `json:"topology,omitempty"`
	Clock    *Clock                    `json:"clock,omitempty"`
	Config   map[string]any            `json:"config,omitempty"`
	State    map[string]map[string]any `json:"state,omitempty"`
	Extends  []string                  `json:"extends,omitempty"`
	// Attributes carries free-form metadata, such as {boundary: true} for a
	// reference copy that defers to the owning fixture when merging (§13.1).
	Attributes map[string]any `json:"attributes,omitempty"`
	// Limiters seeds limiter state (§13.1 item 27).
	Limiters LimiterSeeds `json:"limiters,omitempty"`
}

// WorldLayer is one source of starting-world settings: a fixture, a
// scenario or a run request.
type WorldLayer struct {
	Topology map[string][]string
	Clock    *Clock
	Config   map[string]any
	State    map[string]map[string]any
	Limiters LimiterSeeds // §13.1 item 27
}

// Layer returns the fixture's own settings, without what it extends.
func (f *Fixture) Layer() WorldLayer {
	return WorldLayer{Topology: f.Topology, Clock: f.Clock, Config: f.Config, State: f.State, Limiters: f.Limiters}
}

// Layer returns the scenario's own settings, without its fixtures.
func (s *Scenario) Layer() WorldLayer {
	return WorldLayer{Topology: s.Topology, Clock: s.Clock, Config: s.Config, State: s.State, Limiters: s.Limiters}
}

// World is the starting world of a run: the topology, the clock's epoch,
// the effective config values and the state overrides (applied over each
// component's initial state by the simulator).
type World struct {
	Topology map[string][]string
	EpochMS  int64
	Config   map[string]any
	State    map[string]map[string]any
	// Limiters are the limiter seeds (§13.1 item 27), merged key by key.
	Limiters LimiterSeeds
}

// BaseWorld is the world before any fixture: no topology, epoch 0, and each
// config's effective value.
func (x *Index) BaseWorld() *World {
	w := &World{Topology: map[string][]string{}, Config: map[string]any{}, State: map[string]map[string]any{}}
	for id, c := range x.Configs {
		if v := c.Effective(); v != nil {
			w.Config[id] = expr.Native(v)
		}
	}
	return w
}

// Apply layers l over w: topology entries replace earlier ones, a clock
// replaces the epoch, and config and state are deep-merged (maps merge key
// by key; any other value replaces). Values are normalized with
// expr.Native (whole numbers become int64). l is not modified.
//
// A null deletes its key when the value it merges over has it (§13.1 item
// 12; see MergeValue). In config the key is removed at once. In state the
// deletion stays as a Deleted marker or a null, since the component's
// initial state is merged later (the simulator deletes the key from it
// with MergeValue); a null for a whole state key drops the earlier
// overrides of that key.
func (w *World) Apply(l WorldLayer) error {
	for c, inst := range l.Topology {
		w.Topology[c] = append([]string(nil), inst...)
	}
	if l.Clock != nil {
		ms, err := l.Clock.EpochMillis()
		if err != nil {
			return err
		}
		w.EpochMS = ms
	}
	for k, v := range l.Config {
		nv := expr.Native(v)
		if _, has := w.Config[k]; has && nv == nil {
			delete(w.Config, k)
			continue
		}
		w.Config[k] = MergeValue(w.Config[k], nv, false)
	}
	for k, v := range l.State {
		cur, _ := MergeValue(w.State[k], expr.Native(v), true).(map[string]any)
		w.State[k] = cur
	}
	w.Limiters = mergeLimiterSeeds(w.Limiters, l.Limiters)
	return nil
}

// FixtureChain returns the fixtures to apply for ids, in application order:
// each fixture after what it extends, depth first. A fixture reached twice
// is applied once, at its first position, so a shared base does not
// overwrite later layers. Unknown ids and extends cycles are errors.
func (x *Index) FixtureChain(ids []string) ([]*Fixture, error) {
	var out []*Fixture
	done := map[string]bool{}
	active := map[string]bool{}
	var visit func(id string, path []string) error
	visit = func(id string, path []string) error {
		if done[id] {
			return nil
		}
		if active[id] {
			return fmt.Errorf("fixture extends form a cycle: %s", strings.Join(append(path, id), " -> "))
		}
		f, ok := x.Fixtures[id]
		if !ok {
			return fmt.Errorf("unknown fixture %q", id)
		}
		active[id] = true
		for _, e := range f.Extends {
			if err := visit(e, append(path, id)); err != nil {
				return err
			}
		}
		active[id] = false
		done[id] = true
		out = append(out, f)
		return nil
	}
	for _, id := range ids {
		if err := visit(id, nil); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// ScenarioWorld builds a scenario's starting world: the base world, then its
// fixture chain, then its own settings. A run request's overrides go on top
// with World.Apply.
func (x *Index) ScenarioWorld(s *Scenario) (*World, error) {
	w := x.BaseWorld()
	chain, err := x.FixtureChain(s.Fixtures)
	if err != nil {
		return nil, err
	}
	for _, f := range chain {
		if err := w.Apply(f.Layer()); err != nil {
			return nil, fmt.Errorf("fixture %s: %w", f.ID, err)
		}
	}
	if err := w.Apply(s.Layer()); err != nil {
		return nil, err
	}
	return w, nil
}

// InstanceGroup returns the component whose topology entry governs comp:
// comp itself or its nearest ancestor with an entry (§11.1), and that
// group's instances. ok is false when comp has no group, so it has one
// unnamed instance ("").
func (x *Index) InstanceGroup(topology map[string][]string, comp string) (group string, instances []string, ok bool) {
	seen := map[string]bool{}
	for c := comp; c != "" && !seen[c]; {
		seen[c] = true
		if inst, has := topology[c]; has {
			return c, inst, true
		}
		p, known := x.Components[c]
		if !known {
			break
		}
		c = p.Parent
	}
	return "", nil, false
}

// StateKey is the key of a component instance's state: "<component>" for
// the unnamed instance, else "<component>@<instance>" (§11.1).
func StateKey(component, instance string) string {
	if instance == "" {
		return component
	}
	return component + "@" + instance
}

// SplitStateKey splits a state key into its component and instance.
func SplitStateKey(key string) (component, instance string) {
	c, i, _ := strings.Cut(key, "@")
	return c, i
}

// Deleted marks, in a merged override, a key that a null deleted (§13.1
// item 12) so that a later merge (over a component's initial state)
// deletes it too. It encodes as null.
var Deleted any = deletedMarker{}

type deletedMarker struct{}

func (deletedMarker) MarshalJSON() ([]byte, error) { return []byte("null"), nil }

// MergeValue deep-merges over onto base: maps merge key by key, and any
// other value replaces. A null in an over map deletes the key when base has
// it (§13.1 item 12); for a key base lacks, the null stays a value, as it
// always did, so a row the override introduces keeps its null fields.
// With mark, the deletion is recorded as Deleted instead, for an override
// that is itself merged later; without it, Deleted markers in over delete
// their keys and never reach the result. The result shares nothing with
// over.
func MergeValue(base, over any, mark bool) any {
	om, ok := asMap(over)
	if !ok {
		return deepCopy(over)
	}
	bm, _ := asMap(base)
	out := make(map[string]any, len(bm)+len(om))
	for k, v := range bm {
		out[k] = v
	}
	keys := make([]string, 0, len(om))
	for k := range om {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		ov := om[k]
		bv, has := bm[k]
		switch {
		case ov == Deleted && !mark:
			delete(out, k)
		case ov == nil && has && bv != Deleted:
			if mark {
				out[k] = Deleted
			} else {
				delete(out, k)
			}
		case ov == nil && has: // deleted by an earlier layer
			if !mark {
				delete(out, k)
			}
		default:
			out[k] = MergeValue(bv, ov, mark)
		}
	}
	return out
}

func asMap(v any) (map[string]any, bool) {
	switch t := v.(type) {
	case map[string]any:
		return t, true
	}
	return nil, false
}

func deepCopy(v any) any {
	switch t := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, x := range t {
			out[k] = deepCopy(x)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			out[i] = deepCopy(x)
		}
		return out
	}
	return v
}

// IntOrExpr is a whole number or an "=cel" template (§13.1): timeout_ms,
// deadline_ms, after_ms, every_ms, stagger_ms and count on behavior steps.
// A template is evaluated in the behavior environment when its step runs.
// It decodes from a JSON integer or an "=..." string and encodes back to
// the same form. The zero value is the number 0 (unset, with omitzero).
type IntOrExpr struct {
	N    int64  // the number, when Expr is empty: whole milliseconds (floored) for a duration
	Expr string // the CEL source of a template, without the leading "="
	// Micro is the sub-millisecond part of a fractional duration in µs
	// (0 to 999), so the value is N ms + Micro µs (§13.1 item 16).
	Micro int64
}

// US returns a number's value in microseconds, reading it as milliseconds.
func (v IntOrExpr) US() int64 { return v.N*1000 + v.Micro }

// IsWhole reports whether a number has no fractional part.
func (v IntOrExpr) IsWhole() bool { return v.Micro == 0 }

// Int returns the IntOrExpr holding n.
func Int(n int64) IntOrExpr { return IntOrExpr{N: n} }

// IsZero reports whether v is the number 0, the unset value.
func (v IntOrExpr) IsZero() bool { return v.Expr == "" && v.N == 0 && v.Micro == 0 }

// IsExpr reports whether v is a template.
func (v IntOrExpr) IsExpr() bool { return v.Expr != "" }

func (v IntOrExpr) String() string {
	if v.Expr != "" {
		return "=" + v.Expr
	}
	if v.Micro != 0 {
		return strconv.FormatFloat(float64(v.US())/1000, 'f', -1, 64)
	}
	return strconv.FormatInt(v.N, 10)
}

func (v IntOrExpr) MarshalJSON() ([]byte, error) {
	if v.Expr != "" {
		return json.Marshal("=" + v.Expr)
	}
	if v.Micro != 0 {
		return json.Marshal(float64(v.US()) / 1000)
	}
	return json.Marshal(v.N)
}

func (v *IntOrExpr) UnmarshalJSON(b []byte) error {
	var s string
	if json.Unmarshal(b, &s) == nil {
		src, ok := strings.CutPrefix(s, "=")
		if !ok || strings.TrimSpace(src) == "" {
			return fmt.Errorf(`want a whole number or an "=cel" template, got %q`, s)
		}
		*v = IntOrExpr{Expr: src}
		return nil
	}
	var n json.Number
	if err := json.Unmarshal(b, &n); err != nil {
		return fmt.Errorf(`want a whole number or an "=cel" template`)
	}
	i, err := strconv.ParseInt(string(n), 10, 64)
	if err == nil {
		*v = IntOrExpr{N: i}
		return nil
	}
	// A fractional number of milliseconds, kept to the microsecond.
	f, ferr := strconv.ParseFloat(string(n), 64)
	if ferr != nil || math.IsInf(f, 0) || math.Abs(f) > 1e15 {
		return fmt.Errorf("want a number, got %s", n)
	}
	us := int64(math.Round(f * 1000))
	ms := us / 1000
	if us%1000 < 0 {
		ms--
	}
	*v = IntOrExpr{N: ms, Micro: us - ms*1000}
	return nil
}

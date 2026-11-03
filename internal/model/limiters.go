package model

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
)

// Back pressure: limiters (§13.1 item 27). A component declares limiters;
// an interface applies them at call entry with limits, and a behavior
// decides, charges and releases mid-flight with the admit, charge and
// release steps. The engine keeps every limiter's state in virtual time.

// Limiter kinds.
const (
	LimiterTokenBucket   = "token_bucket"
	LimiterFixedWindow   = "fixed_window"
	LimiterSlidingWindow = "sliding_window"
	LimiterConcurrency   = "concurrency"
)

// LimiterKinds lists the limiter kinds.
var LimiterKinds = []string{LimiterTokenBucket, LimiterFixedWindow, LimiterSlidingWindow, LimiterConcurrency}

// Limiter scopes, backend error modes and on_limit modes.
const (
	ScopeInstance = "instance" // the default: each instance has its own state
	ScopeShared   = "shared"   // one state per key across every instance (Redis)

	BackendFailOpen   = "fail_open"
	BackendFailClosed = "fail_closed"
	BackendPropagate  = "propagate" // the default

	OnLimitReject = "reject" // the default
	OnLimitWait   = "wait"
)

// LimiterSpec is one limiter a component declares (§13.1 item 27). Its full
// id is "<component>.<id>". Numeric fields are numbers or "=cel" templates
// evaluated per decision, in the behavior environment of the frame that
// applies the limiter.
type LimiterSpec struct {
	ID   string `json:"id"`
	Kind string `json:"kind"`
	// Key is the limiter key: "=cel" over input, ctx, config, vars and
	// self, or a literal. Empty means one global key.
	Key string `json:"key,omitempty"`
	// Limit is an int, "=cel", or null for unlimited. It is required:
	// write null for an unlimited limiter.
	Limit json.RawMessage `json:"limit,omitempty"`
	// PeriodMS is required for the bucket and window kinds; LeaseMS for
	// concurrency. Burst defaults to limit; Floor (token buckets charged
	// after the fact) defaults to 0; IdleTTLMS 0 keeps idle keys forever.
	PeriodMS  IntOrExpr `json:"period_ms,omitzero"`
	Burst     IntOrExpr `json:"burst,omitzero"`
	LeaseMS   IntOrExpr `json:"lease_ms,omitzero"`
	Floor     IntOrExpr `json:"floor,omitzero"`
	IdleTTLMS IntOrExpr `json:"idle_ttl_ms,omitzero"`
	// Cost is a number or "=cel"; nil means 1.
	Cost  any    `json:"cost,omitempty"`
	Scope string `json:"scope,omitempty"`
	// Backend is an interface each decision calls first (shared scope only).
	Backend        string `json:"backend,omitempty"`
	OnBackendError string `json:"on_backend_error,omitempty"`
	OnLimit        string `json:"on_limit,omitempty"`
	// MaxWaitMS bounds an on_limit: wait; 0 means no bound.
	MaxWaitMS IntOrExpr `json:"max_wait_ms,omitzero"`
	// Enforce is a bool or "=cel"; nil means true. When false a decision
	// that would reject is traced as shadow and admitted.
	Enforce any `json:"enforce,omitempty"`
	// Error replaces the default {code: rate_limited, status: 429,
	// retryable: true}.
	Error *LimiterError `json:"error,omitempty"`

	Summary string   `json:"summary,omitempty"`
	Sources []Source `json:"sources,omitempty"`
}

// LimiterError is the error a full limiter fails with. Message may be an
// "=cel" template, evaluated with error set to the error (data included).
type LimiterError struct {
	Code      string `json:"code,omitempty"`
	Status    int    `json:"status,omitempty"`
	Message   string `json:"message,omitempty"`
	Retryable *bool  `json:"retryable,omitempty"`
}

// Default limiter error.
const (
	DefaultLimitCode   = "rate_limited"
	DefaultLimitStatus = 429
)

// ErrorCode is the code the limiter fails with.
func (l *LimiterSpec) ErrorCode() string {
	if l.Error != nil && l.Error.Code != "" {
		return l.Error.Code
	}
	return DefaultLimitCode
}

// ScopeOf is the limiter's scope, instance by default.
func (l *LimiterSpec) ScopeOf() string {
	if l.Scope == "" {
		return ScopeInstance
	}
	return l.Scope
}

// LimitRef applies a limiter: a bare id names a limiter of the applying
// interface's (or behavior's) component, a full id "<component>.<id>" any.
// Key and Cost override the limiter's own; Gate checks without consuming.
// It decodes from a string or an object.
type LimitRef struct {
	Limiter string `json:"limiter"`
	Key     string `json:"key,omitempty"`
	Cost    any    `json:"cost,omitempty"`
	Gate    bool   `json:"gate,omitempty"`
}

func (l *LimitRef) UnmarshalJSON(b []byte) error {
	b = bytes.TrimSpace(b)
	if len(b) > 0 && b[0] == '"' {
		*l = LimitRef{}
		return json.Unmarshal(b, &l.Limiter)
	}
	type plain LimitRef
	var p plain
	if err := Decode(b, &p); err != nil {
		return fmt.Errorf("a limit is a limiter id or {limiter, key, cost, gate}: %w", err)
	}
	*l = LimitRef(p)
	return nil
}

func (l LimitRef) MarshalJSON() ([]byte, error) {
	if l.Key == "" && l.Cost == nil && !l.Gate {
		return json.Marshal(l.Limiter)
	}
	type plain LimitRef
	return json.Marshal(plain(l))
}

// AdmitSpec is an admit step: decide one limiter or several, all or
// nothing. As and OnError may be given here or on the step.
type AdmitSpec struct {
	Limiter  string     `json:"limiter,omitempty"`
	Limiters []LimitRef `json:"limiters,omitempty"`
	Key      string     `json:"key,omitempty"`
	Cost     any        `json:"cost,omitempty"`
	Gate     bool       `json:"gate,omitempty"`
	As       string     `json:"as,omitempty"`
	OnError  *OnError   `json:"on_error,omitempty"`
}

// Refs lists the limits an admit decides: Limiter, or each of Limiters
// with the admit's key, cost and gate as defaults.
func (a *AdmitSpec) Refs() []LimitRef {
	if a.Limiter != "" {
		return []LimitRef{{Limiter: a.Limiter, Key: a.Key, Cost: a.Cost, Gate: a.Gate}}
	}
	out := make([]LimitRef, len(a.Limiters))
	for i, r := range a.Limiters {
		if r.Key == "" {
			r.Key = a.Key
		}
		if r.Cost == nil {
			r.Cost = a.Cost
		}
		r.Gate = r.Gate || a.Gate
		out[i] = r
	}
	return out
}

// ChargeSpec is a charge step: consume after the fact, down to floor.
type ChargeSpec struct {
	Limiter string `json:"limiter"`
	Key     string `json:"key,omitempty"`
	Cost    any    `json:"cost,omitempty"`
}

// ReleaseSpec is a release step: free a concurrency lease. Lease is a
// template giving the lease id (from vars.<as>.lease of the admit); without
// it the key's oldest lease is freed. A missing lease is a no-op.
type ReleaseSpec struct {
	Limiter string `json:"limiter"`
	Key     string `json:"key,omitempty"`
	Lease   any    `json:"lease,omitempty"`
}

// LimiterSeeds seed limiter state: full limiter id ("<component>.<id>",
// or "<component>@<instance>.<id>" for one instance's state), then key,
// then {tokens, count, leases, updated_ms}.
type LimiterSeeds map[string]map[string]map[string]any

// SplitLimiterID splits a full limiter id "<component>[@<instance>].<id>".
func SplitLimiterID(full string) (comp, inst, id string, ok bool) {
	left, id, ok := strings.Cut(full, ".")
	if !ok || id == "" || left == "" {
		return "", "", "", false
	}
	comp, inst = SplitStateKey(left)
	return comp, inst, id, true
}

// Limiter finds a limiter by full id, or by bare id in component comp.
func (x *Index) Limiter(comp, ref string) (*LimiterSpec, string, bool) {
	c, id := comp, ref
	if lc, _, lid, ok := SplitLimiterID(ref); ok {
		c, id = lc, lid
	}
	cc, ok := x.Components[c]
	if !ok {
		return nil, "", false
	}
	for i := range cc.Limiters {
		if cc.Limiters[i].ID == id {
			return &cc.Limiters[i], c + "." + id, true
		}
	}
	return nil, "", false
}

// mergeLimiterSeeds layers over onto base, key by key: a key's fields
// merge, and a null key or limiter drops the earlier seed.
func mergeLimiterSeeds(base, over LimiterSeeds) LimiterSeeds {
	if len(over) == 0 {
		return base
	}
	if base == nil {
		base = LimiterSeeds{}
	}
	for lim, keys := range over {
		if keys == nil {
			delete(base, lim)
			continue
		}
		cur := base[lim]
		if cur == nil {
			cur = map[string]map[string]any{}
			base[lim] = cur
		}
		for k, v := range keys {
			if v == nil {
				delete(cur, k)
				continue
			}
			m, _ := MergeValue(cur[k], expr.Native(v), false).(map[string]any)
			cur[k] = m
		}
	}
	return base
}

// validLimiterField lists the fields a seed may set.
var limiterSeedFields = map[string]bool{"tokens": true, "count": true, "leases": true, "updated_ms": true}

// limiters checks a component's limiter declarations.
func (v *validator) limiters(p string, c Component) {
	seen := map[string]bool{}
	for i := range c.Limiters {
		l := &c.Limiters[i]
		lp := fmt.Sprintf("%s.limiters[%d]", p, i)
		if !ValidID(l.ID) {
			v.errf(lp+".id", "invalid limiter id %q: use [a-z0-9][a-z0-9_-]{0,63}", l.ID)
		}
		if seen[l.ID] {
			v.errf(lp+".id", "duplicate limiter id %q", l.ID)
		}
		seen[l.ID] = true
		if !contains(LimiterKinds, l.Kind) {
			v.errf(lp+".kind", "kind is one of %s", strings.Join(LimiterKinds, ", "))
		}
		v.limiterKey(lp+".key", l.Key)
		switch t, err := expr.DecodeTemplate(l.Limit); {
		case err != nil:
			v.errf(lp+".limit", "invalid JSON: %v", err)
		case len(l.Limit) == 0:
			v.errf(lp+".limit", "limit is required: a number, an expression, or null for unlimited")
		default:
			v.limiterNum(lp+".limit", t)
		}
		window := l.Kind == LimiterTokenBucket || l.Kind == LimiterFixedWindow || l.Kind == LimiterSlidingWindow
		switch {
		case window && l.PeriodMS.IsZero():
			v.errf(lp+".period_ms", "%s needs period_ms", l.Kind)
		case !window && !l.PeriodMS.IsZero() && l.Kind != "":
			v.errf(lp+".period_ms", "period_ms goes with token_bucket, fixed_window and sliding_window")
		}
		if !l.PeriodMS.IsExpr() && !l.PeriodMS.IsZero() && l.PeriodMS.US() <= 0 {
			v.errf(lp+".period_ms", "period_ms must be positive")
		}
		v.intOrExpr(lp+".period_ms", l.PeriodMS)
		switch {
		case l.Kind == LimiterConcurrency && l.LeaseMS.IsZero():
			v.errf(lp+".lease_ms", "concurrency needs lease_ms")
		case l.Kind != LimiterConcurrency && !l.LeaseMS.IsZero():
			v.errf(lp+".lease_ms", "lease_ms goes with concurrency")
		}
		v.intOrExpr(lp+".lease_ms", l.LeaseMS)
		if l.Kind != LimiterTokenBucket && !l.Burst.IsZero() {
			v.errf(lp+".burst", "burst goes with token_bucket")
		}
		v.intOrExpr(lp+".burst", l.Burst)
		if l.Kind != LimiterTokenBucket && !l.Floor.IsZero() {
			v.errf(lp+".floor", "floor goes with token_bucket")
		}
		if l.Floor.IsExpr() {
			v.expr(expr.Behavior, lp+".floor", strings.TrimSpace(l.Floor.Expr))
		} else if l.Floor.N > 0 {
			v.errf(lp+".floor", "floor must not be positive")
		}
		v.intOrExpr(lp+".idle_ttl_ms", l.IdleTTLMS)
		v.limiterNum(lp+".cost", expr.Native(l.Cost))
		switch l.Scope {
		case "", ScopeInstance, ScopeShared:
		default:
			v.errf(lp+".scope", "scope is %s or %s", ScopeInstance, ScopeShared)
		}
		if l.Backend != "" {
			if l.ScopeOf() != ScopeShared {
				v.errf(lp+".backend", "backend goes with scope: shared")
			}
			v.interfaceRef(lp+".backend", l.Backend)
		}
		switch l.OnBackendError {
		case "", BackendFailOpen, BackendFailClosed, BackendPropagate:
			if l.OnBackendError != "" && l.Backend == "" {
				v.errf(lp+".on_backend_error", "on_backend_error goes with backend")
			}
		default:
			v.errf(lp+".on_backend_error", "on_backend_error is %s, %s or %s", BackendFailOpen, BackendFailClosed, BackendPropagate)
		}
		switch l.OnLimit {
		case "", OnLimitReject, OnLimitWait:
		default:
			v.errf(lp+".on_limit", "on_limit is %s or %s", OnLimitReject, OnLimitWait)
		}
		if l.OnLimit != OnLimitWait && !l.MaxWaitMS.IsZero() {
			v.errf(lp+".max_wait_ms", "max_wait_ms goes with on_limit: wait")
		}
		v.intOrExpr(lp+".max_wait_ms", l.MaxWaitMS)
		switch e := expr.Native(l.Enforce).(type) {
		case nil, bool:
		case string:
			if src, ok := expr.ExprOf(e); ok {
				v.expr(expr.Behavior, lp+".enforce", src)
			} else {
				v.errf(lp+".enforce", "enforce is a bool or an expression")
			}
		default:
			v.errf(lp+".enforce", "enforce is a bool or an expression")
		}
		if e := l.Error; e != nil {
			if src, ok := expr.ExprOf(e.Message); ok {
				v.expr(expr.Behavior, lp+".error.message", src)
			}
		}
	}
}

// limiterKey checks a key: "=cel" or a literal.
func (v *validator) limiterKey(p, key string) {
	if src, ok := expr.ExprOf(key); ok {
		v.expr(expr.Behavior, p, src)
	}
}

// limiterNum checks a number-or-expression field (limit, cost).
func (v *validator) limiterNum(p string, t any) {
	switch n := t.(type) {
	case nil:
	case int64:
		if n < 0 {
			v.errf(p, "must not be negative")
		}
	case float64:
		if n < 0 {
			v.errf(p, "must not be negative")
		}
	case string:
		if src, ok := expr.ExprOf(n); ok {
			v.expr(expr.Behavior, p, src)
		} else {
			v.errf(p, "a number or an expression")
		}
	default:
		v.errf(p, "a number or an expression")
	}
}

// limitRef checks one applied limit of interface or behavior f and returns
// the limiter, if it resolves. The limiter's error must be one of f's
// declared errors.
func (v *validator) limitRef(f *Interface, p string, ref LimitRef) *LimiterSpec {
	if ref.Limiter == "" {
		v.errf(p+".limiter", "a limit names a limiter")
		return nil
	}
	l, full, ok := v.x.Limiter(f.Component, ref.Limiter)
	if !ok {
		v.errf(p+".limiter", "unknown limiter %q (a bare id names a limiter of %s, a full id is <component>.<id>)", ref.Limiter, f.Component)
		return nil
	}
	v.limiterKey(p+".key", ref.Key)
	v.limiterNum(p+".cost", expr.Native(ref.Cost))
	code := l.ErrorCode()
	declared := false
	for _, e := range f.Errors {
		declared = declared || e.Code == code
	}
	if !declared {
		v.errf(p+".limiter", "%s fails with %q, which is not one of %s's declared errors", full, code, f.ID)
	}
	return l
}

// interfaceLimits checks an interface's limits.
func (v *validator) interfaceLimits(f *Interface, p string) {
	for i, ref := range f.Limits {
		v.limitRef(f, fmt.Sprintf("%s.limits[%d]", p, i), ref)
	}
}

// limiterStep checks an admit, charge or release step.
func (v *validator) limiterStep(f *Interface, p, act string, s Step, depth int, choices map[string]bool) {
	switch act {
	case "admit":
		a := s.Admit
		ap := p + ".admit"
		switch {
		case a.Limiter != "" && a.Limiters != nil:
			v.errf(ap, "set limiter or limiters, not both")
		case a.Limiter == "" && len(a.Limiters) == 0:
			v.errf(ap, "admit names a limiter or limiters")
		}
		for i, ref := range a.Refs() {
			q := ap + ".limiter"
			if a.Limiter == "" {
				q = fmt.Sprintf("%s.limiters[%d]", ap, i)
			}
			v.limitRef(f, q, ref)
		}
		as, onErr := a.As, a.OnError
		if as != "" && s.As != "" || onErr != nil && s.OnError != nil {
			v.errf(ap, "give as and on_error on the admit or on the step, not both")
		}
		if as == "" {
			as = s.As
		}
		if onErr == nil {
			onErr = s.OnError
		}
		if as != "" && !ValidIdent(as) {
			v.errf(ap+".as", "invalid variable name %q", as)
		}
		if o := onErr; o != nil {
			switch {
			case o.Mode != "" && o.Mode != "propagate" && o.Mode != "continue":
				v.errf(p+".on_error", "on_error is propagate, continue or a list of steps")
			case o.Mode == "":
				v.steps(f, p+".on_error", o.Steps, depth+1, choices)
			}
		}
	case "charge":
		c := s.Charge
		cp := p + ".charge"
		if l := v.limitRef(f, cp, LimitRef{Limiter: c.Limiter, Key: c.Key, Cost: c.Cost}); l != nil && l.Kind == LimiterConcurrency {
			v.errf(cp+".limiter", "charge goes with token_bucket, fixed_window and sliding_window; release frees a concurrency lease")
		}
	case "release":
		rl := s.Release
		rp := p + ".release"
		if l := v.limitRef(f, rp, LimitRef{Limiter: rl.Limiter, Key: rl.Key}); l != nil && l.Kind != LimiterConcurrency {
			v.errf(rp+".limiter", "release goes with a concurrency limiter")
		}
		v.template(rp+".lease", expr.Native(rl.Lease))
	}
}

// limiterSeeds checks the limiters: seeds of a fixture, scenario or step.
func (v *validator) limiterSeeds(p string, seeds LimiterSeeds) {
	for _, full := range sortedKeys(seeds) {
		sp := p + ".limiters." + full
		comp, inst, id, ok := SplitLimiterID(full)
		if !ok {
			v.errf(sp, "a seed names a limiter as <component>.<id> or <component>@<instance>.<id>")
			continue
		}
		l, _, ok := v.x.Limiter(comp, comp+"."+id)
		if !ok {
			v.errf(sp, "unknown limiter %q", full)
			continue
		}
		if inst != "" {
			if !ValidID(inst) {
				v.errf(sp, "invalid instance name %q", inst)
			}
			if l.ScopeOf() == ScopeShared {
				v.errf(sp, "%s.%s is shared: seed it as %s.%s", comp, id, comp, id)
			}
		}
		for _, k := range sortedKeys(seeds[full]) {
			for _, field := range sortedKeys(seeds[full][k]) {
				if !limiterSeedFields[field] {
					v.errf(sp+"."+k+"."+field, "a seed sets tokens, count, leases or updated_ms")
				}
			}
		}
	}
}

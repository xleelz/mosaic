package sim

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Back pressure: limiters (§13.1 item 27). The engine keeps each limiter's
// state per store (the limiter's full id, "<component>.<id>" when shared,
// "<component>@<instance>.<id>" per instance) and key, in virtual time.
// Every decision emits a limit event; the summary counts them per limiter.

// limState is one key of one limiter store.
type limState struct {
	kind    string
	fresh   bool    // never decided: a token bucket starts full
	tokens  float64 // token_bucket
	count   float64 // fixed_window: the count of the window holding wat
	wat     int64   // fixed_window: a time (virtual µs) in the counted window
	log     []limEntry
	leases  []limLease
	updated int64 // virtual µs of the last touch
}

type limEntry struct {
	t    int64
	cost float64
}

// limLease is a concurrency lease. exp is when it expires (virtual µs);
// unknownExp marks a seeded lease whose expiry the first decision sets.
type limLease struct {
	id      string
	at, exp int64
}

const unknownExp = math.MinInt64

func (s *limState) clone() *limState {
	c := *s
	c.log = append([]limEntry(nil), s.log...)
	c.leases = append([]limLease(nil), s.leases...)
	return &c
}

// limStats are the summary counts of one limiter.
type limStats struct{ admitted, rejected, shadow, waited int }

// LimitCount is a limiter's line in the summary's limits.
type LimitCount struct {
	Admitted int `json:"admitted"`
	Rejected int `json:"rejected"`
	Shadow   int `json:"shadow"`
	Waited   int `json:"waited"`
}

// limWaiter is a task blocked on a full limiter with on_limit: wait.
type limWaiter struct{ t *task }

// limiters is the engine's limiter bookkeeping.
type limiters struct {
	on      bool // the document declares limiters
	stores  map[string]map[string]*limState
	initial map[string]map[string]*limState // the seeded starting state, for restarts
	stats   map[string]*limStats
	waits   map[string][]*limWaiter // by store and key
	leases  int
	ver     int
	cache   map[string]any
	cacheAt int
}

func newLimiters(doc *model.Document) limiters {
	l := limiters{stores: map[string]map[string]*limState{}, stats: map[string]*limStats{}, waits: map[string][]*limWaiter{}, cacheAt: -1}
	for i := range doc.Components {
		if len(doc.Components[i].Limiters) > 0 {
			l.on = true
		}
	}
	return l
}

var emptyLimiters = map[string]any{}

// limitersValue is CEL limiters: the stored state of every limiter key, as
// of its last touch (updated_ms).
func (r *run) limitersValue() any {
	l := &r.lims
	if !l.on {
		return emptyLimiters
	}
	if l.cacheAt == l.ver && l.cache != nil {
		return l.cache
	}
	out := map[string]any{}
	for store, keys := range l.stores {
		m := map[string]any{}
		for k, s := range keys {
			m[k] = r.limStateValue(s)
		}
		out[store] = m
	}
	l.cache, l.cacheAt = out, l.ver
	return out
}

func (r *run) limStateValue(s *limState) map[string]any {
	v := map[string]any{"updated_ms": msValue(r.epoch, s.updated)}
	switch s.kind {
	case model.LimiterTokenBucket:
		v["tokens"] = num(s.tokens)
	case model.LimiterFixedWindow:
		v["count"] = num(s.count)
	case model.LimiterSlidingWindow:
		v["count"] = num(logSum(s.log))
	case model.LimiterConcurrency:
		ls := make([]any, len(s.leases))
		for i, le := range s.leases {
			var exp any
			if le.exp != unknownExp && le.exp != math.MaxInt64 {
				exp = msValue(r.epoch, le.exp)
			}
			ls[i] = map[string]any{"id": le.id, "acquired_ms": msValue(r.epoch, le.at), "expires_ms": exp}
		}
		v["leases"], v["count"] = ls, int64(len(s.leases))
	}
	return v
}

// limitsValue is CEL limits: the summary's counts.
func (r *run) limitsValue() map[string]any {
	out := map[string]any{}
	for id, s := range r.lims.stats {
		out[id] = map[string]any{"admitted": int64(s.admitted), "rejected": int64(s.rejected), "shadow": int64(s.shadow), "waited": int64(s.waited)}
	}
	return out
}

func (r *run) limitsSummary() map[string]LimitCount {
	if len(r.lims.stats) == 0 {
		return nil
	}
	out := map[string]LimitCount{}
	for id, s := range r.lims.stats {
		out[id] = LimitCount{Admitted: s.admitted, Rejected: s.rejected, Shadow: s.shadow, Waited: s.waited}
	}
	return out
}

func (r *run) limStat(full string) *limStats {
	s := r.lims.stats[full]
	if s == nil {
		s = &limStats{}
		r.lims.stats[full] = s
	}
	return s
}

// num is a number for CEL and the trace: an int when whole.
func num(f float64) any {
	if f == math.Trunc(f) && math.Abs(f) < 1e15 {
		return int64(f)
	}
	return f
}

func logSum(log []limEntry) float64 {
	n := 0.0
	for _, e := range log {
		n += e.cost
	}
	return n
}

// storeKey is the state store of limiter spec of component comp, applied
// on instance inst of the frame's component.
func (r *run) limStore(spec *model.LimiterSpec, comp, frameComp, frameInst string) string {
	if spec.ScopeOf() == model.ScopeShared {
		return comp + "." + spec.ID
	}
	inst := ""
	switch g := r.groupOf(comp); {
	case comp == frameComp:
		inst = frameInst
	case !g.ok:
	case containsStr(g.instances, frameInst):
		inst = frameInst
	default:
		inst = g.instances[0]
	}
	return model.StateKey(comp, inst) + "." + spec.ID
}

// seedLimiters applies limiter seeds (§13.1 item 27): a seed keyed by a
// component's limiter applies to each of its instances (instance scope),
// one keyed <component>@<instance>.<id> to that instance alone.
func (r *run) seedLimiters(seeds model.LimiterSeeds, what string) error {
	if len(seeds) == 0 {
		return nil
	}
	ids := sortedKeys(seeds)
	for _, plain := range []bool{true, false} {
		for _, full := range ids {
			comp, inst, id, ok := model.SplitLimiterID(full)
			if !ok || (inst == "") != plain {
				continue
			}
			spec, _, found := r.x.Limiter(comp, comp+"."+id)
			if !found {
				return &RequestError{fmt.Sprintf("%s: unknown limiter %q", what, full)}
			}
			var stores []string
			switch {
			case spec.ScopeOf() == model.ScopeShared:
				stores = []string{comp + "." + id}
			case inst != "":
				stores = []string{model.StateKey(comp, inst) + "." + id}
			default:
				for _, i := range r.instancesOf(comp) {
					stores = append(stores, model.StateKey(comp, i)+"."+id)
				}
			}
			for _, k := range sortedKeys(seeds[full]) {
				for _, store := range stores {
					if err := r.seedKey(spec, store, k, seeds[full][k], what); err != nil {
						return err
					}
				}
			}
		}
	}
	r.lims.ver++
	return nil
}

func (r *run) seedKey(spec *model.LimiterSpec, store, key string, seed map[string]any, what string) error {
	keys := r.lims.stores[store]
	if keys == nil {
		keys = map[string]*limState{}
		r.lims.stores[store] = keys
	}
	if seed == nil {
		delete(keys, key)
		return nil
	}
	seed, _ = expr.Native(seed).(map[string]any)
	s := keys[key]
	if s == nil {
		s = &limState{kind: spec.Kind, fresh: true}
		keys[key] = s
	}
	at := r.now
	if v, ok := seed["updated_ms"]; ok && v != nil {
		ms, ok := toFloat(v)
		if !ok {
			return &RequestError{fmt.Sprintf("%s: limiters %s[%q].updated_ms must be a number", what, store, key)}
		}
		at = int64(math.Round((ms - float64(r.epoch)) * 1000))
	}
	bad := func(field string) error {
		return &RequestError{fmt.Sprintf("%s: limiters %s[%q].%s must be a number", what, store, key, field)}
	}
	s.updated = at
	if v, ok := seed["tokens"]; ok {
		n, ok := toFloat(v)
		if !ok {
			return bad("tokens")
		}
		s.tokens, s.fresh = n, false
	}
	count, hasCount := seed["count"]
	if hasCount {
		n, ok := toFloat(count)
		if !ok {
			return bad("count")
		}
		s.fresh = false
		switch spec.Kind {
		case model.LimiterFixedWindow:
			s.count, s.wat = n, at
		case model.LimiterSlidingWindow:
			s.log = nil
			if n > 0 {
				s.log = []limEntry{{t: at, cost: n}}
			}
		case model.LimiterConcurrency:
			if _, has := seed["leases"]; !has {
				s.leases = seedLeases(store, key, int(n), at)
			}
		}
	}
	if v, ok := seed["leases"]; ok {
		s.fresh = false
		switch t := v.(type) {
		case int64:
			s.leases = seedLeases(store, key, int(t), at)
		case []any:
			s.leases = nil
			for i, x := range t {
				le := limLease{id: fmt.Sprintf("%s/%s#seed-%d", store, key, i+1), at: at, exp: unknownExp}
				switch y := x.(type) {
				case string:
					le.id = y
				case map[string]any:
					if id, ok := y["id"].(string); ok {
						le.id = id
					}
					if ms, ok := toFloat(y["acquired_ms"]); ok {
						le.at = int64(math.Round((ms - float64(r.epoch)) * 1000))
					}
					if ms, ok := toFloat(y["expires_ms"]); ok {
						le.exp = int64(math.Round((ms - float64(r.epoch)) * 1000))
					}
				default:
					return &RequestError{fmt.Sprintf("%s: limiters %s[%q].leases holds lease ids or {id, acquired_ms, expires_ms}", what, store, key)}
				}
				s.leases = append(s.leases, le)
			}
		default:
			return &RequestError{fmt.Sprintf("%s: limiters %s[%q].leases is a count or a list", what, store, key)}
		}
	}
	return nil
}

func seedLeases(store, key string, n int, at int64) []limLease {
	var out []limLease
	for i := 0; i < n; i++ {
		out = append(out, limLease{id: fmt.Sprintf("%s/%s#seed-%d", store, key, i+1), at: at, exp: unknownExp})
	}
	return out
}

// snapshotLimiters records the starting limiter state, which a restart
// goes back to.
func (r *run) snapshotLimiters() {
	r.lims.initial = map[string]map[string]*limState{}
	for store, keys := range r.lims.stores {
		m := map[string]*limState{}
		for k, s := range keys {
			m[k] = s.clone()
		}
		r.lims.initial[store] = m
	}
}

// resetLimiters puts the instance-scoped limiter stores that reset reports
// (by component and instance) back to their starting state: in-process
// limiters are memory a restart loses. Shared stores (Redis) keep theirs.
func (r *run) resetLimiters(reset func(comp, inst string) bool) {
	if !r.lims.on {
		return
	}
	stores := map[string]bool{}
	for s := range r.lims.stores {
		stores[s] = true
	}
	for s := range r.lims.initial {
		stores[s] = true
	}
	for _, store := range sortedKeys(stores) {
		comp, inst, id, ok := model.SplitLimiterID(store)
		if !ok {
			continue
		}
		if spec, _, found := r.x.Limiter(comp, comp+"."+id); !found || spec.ScopeOf() == model.ScopeShared {
			continue
		}
		if !reset(comp, inst) {
			continue
		}
		keys := map[string]*limState{}
		for k, s := range r.lims.initial[store] {
			keys[k] = s.clone()
		}
		r.lims.stores[store] = keys
	}
	r.lims.ver++
}

// limCheck is one limit resolved for a decision.
type limCheck struct {
	spec      *model.LimiterSpec
	full      string // <component>.<id>
	store     string
	key       string
	cost      float64
	gate      bool
	unlimited bool
	limit     float64
	period    int64 // µs
	burst     float64
	floor     float64
	lease     int64 // µs
	ttl       int64 // µs; 0 keeps idle keys
	enforce   bool
	wait      bool
	maxWait   int64 // µs; 0 means no bound

	decision string
	rolled   bool // would admit, but another limit of the group rejected
	leaseID  string
	backend  *Error
}

func (c *limCheck) qkey() string { return c.store + "\x00" + c.key }

// resolve evaluates a limit in frame f: its limiter, key, cost and the
// limiter's numeric fields, all per decision.
func (r *run) resolveLimit(f *frame, ref model.LimitRef, p string) (*limCheck, error) {
	spec, full, ok := r.x.Limiter(f.comp, ref.Limiter)
	if !ok {
		return nil, abortf("%s: unknown limiter %q", p, ref.Limiter)
	}
	comp := strings.SplitN(full, ".", 2)[0]
	act := r.act(f, 1)
	c := &limCheck{spec: spec, full: full, store: r.limStore(spec, comp, f.comp, f.inst), gate: ref.Gate, enforce: true,
		wait: spec.OnLimit == model.OnLimitWait}
	keySrc := ref.Key
	if keySrc == "" {
		keySrc = spec.Key
	}
	if src, ok := expr.ExprOf(keySrc); ok {
		v, err := expr.Behavior.Eval(src, act)
		if err != nil {
			return nil, abortf("%s: %s.key: %v", p, full, err)
		}
		c.key = keyString(v)
	} else {
		c.key = keySrc
	}
	costV := ref.Cost
	if costV == nil {
		costV = spec.Cost
	}
	cost, null, err := r.limNumber(costV, act)
	if err != nil {
		return nil, abortf("%s: %s.cost: %v", p, full, err)
	}
	c.cost = 1
	if costV != nil && !null {
		c.cost = cost
	}
	t, err := expr.DecodeTemplate(spec.Limit)
	if err != nil {
		return nil, abortf("%s: %s.limit: %v", p, full, err)
	}
	limit, null, err := r.limNumber(t, act)
	if err != nil {
		return nil, abortf("%s: %s.limit: %v", p, full, err)
	}
	c.limit, c.unlimited = limit, null
	if c.period, err = r.intOf(f, spec.PeriodMS, fmt.Sprintf("%s: %s.period_ms", p, full)); err != nil {
		return nil, err
	}
	if c.lease, err = r.intOf(f, spec.LeaseMS, fmt.Sprintf("%s: %s.lease_ms", p, full)); err != nil {
		return nil, err
	}
	if c.ttl, err = r.intOf(f, spec.IdleTTLMS, fmt.Sprintf("%s: %s.idle_ttl_ms", p, full)); err != nil {
		return nil, err
	}
	if c.maxWait, err = r.intOf(f, spec.MaxWaitMS, fmt.Sprintf("%s: %s.max_wait_ms", p, full)); err != nil {
		return nil, err
	}
	c.burst = c.limit
	if !spec.Burst.IsZero() {
		b, err := r.limCount(f, spec.Burst, act)
		if err != nil {
			return nil, abortf("%s: %s.burst: %v", p, full, err)
		}
		c.burst = b
	}
	if !spec.Floor.IsZero() {
		fl, err := r.limCount(f, spec.Floor, act)
		if err != nil {
			return nil, abortf("%s: %s.floor: %v", p, full, err)
		}
		c.floor = fl
	}
	switch e := expr.Native(spec.Enforce).(type) {
	case bool:
		c.enforce = e
	case string:
		src, _ := expr.ExprOf(e)
		b, err := expr.Behavior.EvalBool(src, act)
		if err != nil {
			return nil, abortf("%s: %s.enforce: %v", p, full, err)
		}
		c.enforce = b
	}
	return c, nil
}

// keyString turns an evaluated key into a string: null is the global key.
func keyString(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return t
	case int64:
		return strconv.FormatInt(t, 10)
	case uint64:
		return strconv.FormatUint(t, 10)
	case float64:
		return strconv.FormatFloat(t, 'f', -1, 64)
	case bool:
		return strconv.FormatBool(t)
	}
	return fmt.Sprint(v)
}

// limNumber evaluates a number-or-expression field; null reports a null.
func (r *run) limNumber(v any, act map[string]any) (float64, bool, error) {
	v = expr.Native(v)
	if src, ok := expr.ExprOf(v); ok {
		var err error
		if v, err = expr.Behavior.Eval(src, act); err != nil {
			return 0, false, err
		}
	}
	if v == nil {
		return 0, true, nil
	}
	n, ok := toFloat(v)
	if !ok {
		return 0, false, fmt.Errorf("must give a number or null, got %T", v)
	}
	return n, false, nil
}

// limCount evaluates a count field (burst, floor), negatives allowed.
func (r *run) limCount(f *frame, v model.IntOrExpr, act map[string]any) (float64, error) {
	if !v.IsExpr() {
		return float64(v.US()) / 1000, nil
	}
	out, err := expr.Behavior.Eval(strings.TrimSpace(v.Expr), act)
	if err != nil {
		return 0, err
	}
	n, ok := toFloat(out)
	if !ok {
		return 0, fmt.Errorf("must give a number, got %T", out)
	}
	return n, nil
}

// state returns the key's state brought up to now: an idle key past its
// TTL is forgotten, a bucket refills, a fixed window rolls over, a sliding
// window's log and expired leases are pruned.
func (r *run) limState(c *limCheck) *limState {
	keys := r.lims.stores[c.store]
	if keys == nil {
		keys = map[string]*limState{}
		r.lims.stores[c.store] = keys
	}
	s := keys[c.key]
	now := r.now
	if s == nil || (c.ttl > 0 && !s.fresh && now-s.updated >= c.ttl) {
		s = &limState{kind: c.spec.Kind, fresh: true, updated: now}
		keys[c.key] = s
	}
	s.kind = c.spec.Kind
	r.lims.ver++
	switch c.spec.Kind {
	case model.LimiterTokenBucket:
		switch {
		case s.fresh:
			s.tokens = c.burst
		case !c.unlimited && c.limit > 0 && c.period > 0 && now > s.updated && s.tokens < c.burst:
			s.tokens = math.Min(c.burst, s.tokens+float64(now-s.updated)*c.limit/float64(c.period))
		}
	case model.LimiterFixedWindow:
		if s.fresh {
			s.count, s.wat = 0, now
		} else if c.period > 0 && r.window(s.wat, c.period) != r.window(now, c.period) {
			s.count, s.wat = 0, now
		}
	case model.LimiterSlidingWindow:
		if c.period > 0 {
			keep := s.log[:0]
			for _, e := range s.log {
				if e.t > now-c.period {
					keep = append(keep, e)
				}
			}
			s.log = keep
		}
	case model.LimiterConcurrency:
		keep := s.leases[:0]
		for _, le := range s.leases {
			if le.exp == unknownExp {
				le.exp = expiry(le.at, c.lease)
			}
			if le.exp > now {
				keep = append(keep, le)
			}
		}
		s.leases = keep
	}
	s.fresh = false
	s.updated = now
	return s
}

func expiry(at, lease int64) int64 {
	if lease <= 0 {
		return math.MaxInt64
	}
	return at + lease
}

// window is the index of the epoch-aligned window holding virtual time t.
func (r *run) window(t, period int64) int64 {
	return floorDiv(r.epoch*1000+t, period)
}

// level is what the limiter counts now: tokens, or the count or leases.
func level(c *limCheck, s *limState) float64 {
	switch c.spec.Kind {
	case model.LimiterTokenBucket:
		return s.tokens
	case model.LimiterFixedWindow:
		return s.count
	case model.LimiterSlidingWindow:
		return logSum(s.log)
	}
	return float64(len(s.leases))
}

// passes reports whether the limit admits now, without consuming.
func passes(c *limCheck, s *limState) bool {
	n := level(c, s)
	switch {
	case c.spec.Kind == model.LimiterTokenBucket && c.gate:
		return n > 0
	case c.spec.Kind == model.LimiterTokenBucket:
		return n >= c.cost
	case c.gate:
		return n < c.limit
	case c.spec.Kind == model.LimiterConcurrency:
		return n+1 <= c.limit
	}
	return n+c.cost <= c.limit
}

// waitFor is how long until the limit would admit this cost, if nothing
// else consumed: ok is false when it never will (a limit of 0, a cost above
// the limit or burst) or, for concurrency, when no lease expires (a
// release must come first: known is false).
func (r *run) waitFor(c *limCheck, s *limState) (us int64, known, ok bool) {
	now := r.now
	switch c.spec.Kind {
	case model.LimiterTokenBucket:
		need := c.cost
		if c.gate {
			need = math.Nextafter(0, 1)
		}
		if c.limit <= 0 || c.period <= 0 || need > c.burst {
			return 0, true, false
		}
		return int64(math.Ceil((need - s.tokens) * float64(c.period) / c.limit)), true, true
	case model.LimiterFixedWindow:
		if c.limit <= 0 || c.cost > c.limit || c.period <= 0 {
			return 0, true, false
		}
		next := (r.window(now, c.period)+1)*c.period - r.epoch*1000
		return next - now, true, true
	case model.LimiterSlidingWindow:
		if c.limit <= 0 || c.cost > c.limit {
			return 0, true, false
		}
		n := logSum(s.log)
		cost := c.cost
		if c.gate {
			cost = 0
		}
		for _, e := range sortedLog(s.log) {
			if n+cost <= c.limit && (!c.gate || n < c.limit) {
				break
			}
			n -= e.cost
			if n+cost <= c.limit && (!c.gate || n < c.limit) {
				return e.t + c.period - now, true, true
			}
		}
		return 0, true, true
	}
	if c.limit < 1 {
		return 0, true, false
	}
	exp := int64(math.MaxInt64)
	for _, le := range s.leases {
		exp = min(exp, le.exp)
	}
	if exp == math.MaxInt64 {
		return 0, false, true
	}
	return exp - now, true, true
}

func sortedLog(log []limEntry) []limEntry {
	out := append([]limEntry(nil), log...)
	sort.SliceStable(out, func(i, j int) bool { return out[i].t < out[j].t })
	return out
}

// report is the output of a decision: remaining and retry_after_ms (for a
// cost of 1), after it.
func (r *run) report(c *limCheck, s *limState) (remaining, retry any) {
	if c.unlimited || s == nil {
		return nil, nil
	}
	n := level(c, s)
	if c.spec.Kind == model.LimiterTokenBucket {
		remaining = int64(math.Floor(n))
	} else {
		remaining = num(c.limit - n)
	}
	one := *c
	one.cost, one.gate = 1, false
	if passes(&one, s) {
		return remaining, int64(0)
	}
	us, known, ok := r.waitFor(&one, s)
	if !known || !ok {
		return remaining, nil
	}
	return remaining, (max(us, 0) + 999) / 1000
}

// consume takes the cost (or a lease) from the key.
func (r *run) consume(c *limCheck, s *limState, floor bool) {
	r.lims.ver++
	switch c.spec.Kind {
	case model.LimiterTokenBucket:
		s.tokens -= c.cost
		if floor {
			s.tokens = math.Max(s.tokens, math.Min(c.floor, s.tokens+c.cost))
		}
	case model.LimiterFixedWindow:
		s.count += c.cost
	case model.LimiterSlidingWindow:
		s.log = append(s.log, limEntry{t: r.now, cost: c.cost})
	case model.LimiterConcurrency:
		r.lims.leases++
		c.leaseID = fmt.Sprintf("%s#%d", c.full, r.lims.leases)
		s.leases = append(s.leases, limLease{id: c.leaseID, at: r.now, exp: expiry(r.now, c.lease)})
	}
}

// limEvent emits a limit event and counts the decision.
func (r *run) limEvent(f *frame, c *limCheck, s *limState, from string, call int) error {
	st := r.limStat(c.full)
	switch c.decision {
	case "admit", "unlimited", "fail_open":
		if !c.rolled {
			st.admitted++
		}
	case "reject", "fail_closed":
		st.rejected++
	case "shadow":
		st.shadow++
	}
	remaining, retry := r.report(c, s)
	var limit any
	if !c.unlimited {
		limit = num(c.limit)
	}
	out := map[string]any{"decision": c.decision, "remaining": remaining, "retry_after_ms": retry, "limit": limit}
	if c.rolled {
		out["rolled_back"] = true
	}
	if c.leaseID != "" {
		out["lease"] = c.leaseID
	}
	return r.ev(Event{Type: "limit", Span: f.span, Call: call, Component: f.comp, From: from, Interface: f.iface.ID, Key: c.full,
		Input: map[string]any{"key": c.key, "cost": num(c.cost), "gate": c.gate}, Output: out, Instance: f.inst})
}

// limError is the error of a rejecting limit, with data {limiter, key,
// limit, remaining, retry_after_ms}.
func (r *run) limError(f *frame, c *limCheck, s *limState, p string) (*Error, error) {
	remaining, retry := r.report(c, s)
	var limit any
	if !c.unlimited {
		limit = num(c.limit)
	}
	e := &Error{Code: model.DefaultLimitCode, Status: model.DefaultLimitStatus, Retryable: true,
		Data: map[string]any{"limiter": c.full, "key": c.key, "limit": limit, "remaining": remaining, "retry_after_ms": retry}}
	msg := ""
	if le := c.spec.Error; le != nil {
		if le.Code != "" {
			e.Code = le.Code
		}
		if le.Status != 0 {
			e.Status = le.Status
		}
		if le.Retryable != nil {
			e.Retryable = *le.Retryable
		}
		msg = le.Message
	}
	if src, ok := expr.ExprOf(msg); ok {
		act := r.act(f, 1)
		act["error"] = e.Map()
		v, err := expr.Behavior.Eval(src, act)
		if err != nil {
			return nil, abortf("%s: %s.error.message: %v", p, c.full, err)
		}
		msg = fmt.Sprint(v)
	}
	if msg == "" {
		msg = fmt.Sprintf("%s: limit reached for key %q", c.full, c.key)
		if c.decision == "fail_closed" {
			msg = fmt.Sprintf("%s: the limiter backend failed (fail_closed)", c.full)
		}
	}
	e.Message = msg
	return e, nil
}

// backendCall makes a limiter's backend call (shared scope): a normal call,
// so latency, faults, kills and the trace apply. Its result is ignored; its
// error is returned.
func (r *run) backendCall(f *frame, c *limCheck, op string, depth int) (*Error, error) {
	b := c.spec.Backend
	if b == "" {
		return nil, nil
	}
	inst, bad, err := r.targetInstance(f.comp, f.inst, b, "", expr.Behavior, nil)
	if err != nil {
		return nil, err
	}
	input := map[string]any{"limiter": c.full, "key": c.key, "op": op, "cost": num(c.cost)}
	res, err := r.invoke(callSpec{from: f.comp, fromInst: f.inst, fromIface: f.iface.ID, target: b, inst: inst, badInst: bad, input: input, parent: f.span,
		callID: r.nextCall(), attempt: 1, depth: depth + 1, deadline: f.deadline})
	if err != nil {
		return nil, err
	}
	if res.ok {
		return nil, nil
	}
	return res.err, nil
}

// limGroup is the outcome of deciding several limits together.
type limGroup struct {
	ok     bool
	err    *Error // the first rejection's error, or a propagated backend error
	checks []*limCheck
	states []*limState
}

// admitLimits decides refs in frame f, all or nothing (§13.1 item 27):
// each limit is decided (after its backend call, if any); costs are taken
// only when all admit. A rejecting limit with on_limit: wait blocks the
// task in virtual time, first come first served per key, until the group
// would pass or max_wait_ms runs out. from is the caller of an interface's
// limits (empty for an admit step).
func (r *run) admitLimits(f *frame, refs []model.LimitRef, from string, call, depth int, p string) (*limGroup, error) {
	var w *limWaiter
	wq := ""
	var waitStart int64
	deadline := int64(noDeadline)
	var waited *limCheck
	leave := func() {
		if w != nil {
			r.dropLimWaiter(wq, w)
			w = nil
		}
	}
	for {
		checks := make([]*limCheck, len(refs))
		for i, ref := range refs {
			c, err := r.resolveLimit(f, ref, p)
			if err != nil {
				leave()
				return nil, err
			}
			checks[i] = c
		}
		op := "admit"
		for _, c := range checks {
			if c.unlimited || c.spec.Backend == "" {
				continue
			}
			if c.gate {
				op = "gate"
			}
			be, err := r.backendCall(f, c, op, depth)
			if err != nil {
				leave()
				return nil, err
			}
			if be == nil {
				continue
			}
			switch c.spec.OnBackendError {
			case model.BackendFailOpen:
				c.decision = "fail_open"
			case model.BackendFailClosed:
				c.decision = "fail_closed"
			default:
				leave()
				return &limGroup{err: be, checks: checks}, nil
			}
		}
		states := make([]*limState, len(checks))
		var reject *limCheck
		for i, c := range checks {
			if c.decision == "fail_closed" {
				if reject == nil {
					reject = c
				}
				continue
			}
			if c.decision != "" || c.unlimited {
				if c.decision == "" {
					c.decision = "unlimited"
				}
				continue
			}
			s := r.limState(c)
			states[i] = s
			ok := passes(c, s)
			if ok && c.wait && c.enforce {
				// First come, first served: a waiter ahead holds the key.
				if q := r.lims.waits[c.qkey()]; len(q) > 0 && q[0] != w {
					ok = false
				}
			}
			switch {
			case ok:
				c.decision = "admit"
			case !c.enforce:
				c.decision = "shadow"
			default:
				c.decision = "reject"
				if reject == nil {
					reject = c
				}
			}
		}
		if reject != nil && reject.decision == "reject" && reject.wait && r.s.cur != nil {
			s := r.limState(reject)
			us, known, ok := r.waitFor(reject, s)
			if q := r.lims.waits[reject.qkey()]; len(q) > 0 && q[0] != w {
				known, ok = false, true // behind other waiters: woken in turn
			}
			if ok {
				if w == nil {
					waitStart = r.now
					if reject.maxWait > 0 {
						deadline = r.now + reject.maxWait
					}
					waited = reject
					r.limStat(reject.full).waited++
					reject.decision = "wait"
					if err := r.limEvent(f, reject, s, from, call); err != nil {
						return nil, err
					}
					reject.decision = "reject"
				}
				if w == nil || wq != reject.qkey() {
					leave()
					w, wq = &limWaiter{t: r.s.cur}, reject.qkey()
					r.lims.waits[wq] = append(r.lims.waits[wq], w)
				}
				if r.now < deadline {
					var err error
					head := r.lims.waits[wq][0] == w
					if head && known {
						err = r.sleepUntil(min(r.now+max(us, 1), deadline))
					} else {
						err = r.park(deadline, 0)
					}
					if err != nil {
						leave()
						return nil, err
					}
					continue
				}
			}
		}
		if waited != nil {
			t := r.now
			r.now = waitStart
			err := r.ev(Event{Type: "queue", Span: f.span, Call: call, Component: f.comp, From: from, To: f.comp, Interface: f.iface.ID,
				Instance: f.inst, Key: waited.full, WaitMS: t - waitStart})
			r.now = t
			if err != nil {
				leave()
				return nil, err
			}
		}
		leave()
		g := &limGroup{ok: reject == nil, checks: checks, states: states}
		for i, c := range checks {
			if c.decision != "admit" {
				continue
			}
			if reject != nil {
				c.rolled = true
			} else if !c.gate {
				r.consume(c, states[i], false)
			}
		}
		for i, c := range checks {
			if err := r.limEvent(f, c, states[i], from, call); err != nil {
				return nil, err
			}
		}
		if reject != nil {
			var s *limState
			for i, c := range checks {
				if c == reject {
					s = states[i]
				}
			}
			e, err := r.limError(f, reject, s, p)
			if err != nil {
				return nil, err
			}
			g.err = e
		}
		return g, nil
	}
}

// dropLimWaiter removes a waiter from its key's queue and wakes the next
// in line.
func (r *run) dropLimWaiter(q string, w *limWaiter) {
	ws := r.lims.waits[q]
	for i, x := range ws {
		if x == w {
			ws = append(ws[:i:i], ws[i+1:]...)
			break
		}
	}
	if len(ws) == 0 {
		delete(r.lims.waits, q)
		return
	}
	r.lims.waits[q] = ws
	r.wakeAt(ws[0].t, r.now, 0)
}

// wakeLimWaiter wakes the first waiter on a key, after a lease frees.
func (r *run) wakeLimWaiter(q string) {
	if ws := r.lims.waits[q]; len(ws) > 0 {
		r.wakeAt(ws[0].t, r.now, 0)
	}
}

// releaseLease frees a lease: the given id, or (empty) the key's oldest.
// It reports whether a lease was freed.
func (r *run) releaseLease(c *limCheck, id string) bool {
	s := r.lims.stores[c.store][c.key]
	if s == nil {
		return false
	}
	for i, le := range s.leases {
		if id == "" || le.id == id {
			s.leases = append(s.leases[:i:i], s.leases[i+1:]...)
			r.lims.ver++
			r.wakeLimWaiter(c.qkey())
			return true
		}
	}
	return false
}

// interfaceLimits applies an interface's limits at call entry (§13.1 item
// 27). It returns the rejection, if any, and the leases to release when the
// call ends.
func (r *run) interfaceLimits(f *model.Interface, c callSpec, skey string, span int) (*Error, []*limCheck, error) {
	fr := &frame{iface: f, comp: f.Component, inst: c.inst, skey: skey, input: c.input, vars: map[string]any{}, span: span, deadline: c.deadline}
	g, err := r.admitLimits(fr, f.Limits, c.from, c.callID, c.depth, f.ID+".limits")
	if err != nil {
		return nil, nil, err
	}
	if !g.ok {
		return g.err, nil, nil
	}
	var leases []*limCheck
	for _, ck := range g.checks {
		if ck.leaseID != "" {
			leases = append(leases, ck)
		}
	}
	return nil, leases, nil
}

// releaseCallLeases frees the leases an interface's limits took, when the
// call ends whatever its outcome.
func (r *run) releaseCallLeases(f *model.Interface, c callSpec, skey string, span int, leases []*limCheck) error {
	fr := &frame{iface: f, comp: f.Component, inst: c.inst, skey: skey, input: c.input, vars: map[string]any{}, span: span, deadline: c.deadline}
	for _, ck := range leases {
		if !r.releaseLease(ck, ck.leaseID) {
			continue
		}
		ck.decision = "release"
		if err := r.limEvent(fr, ck, r.lims.stores[ck.store][ck.key], c.from, c.callID); err != nil {
			return err
		}
	}
	return nil
}

// admitStep runs an admit step: vars.<as> = {ok, decision, limiter, key,
// remaining, retry_after_ms, lease, decisions, error}; a rejection fails
// the step with the limiter's error, and on_error works as for a call.
func (r *run) admitStep(f *frame, s model.Step, depth int, p string) (*exit, error) {
	a := s.Admit
	as, onErr := a.As, a.OnError
	if as == "" {
		as = s.As
	}
	if onErr == nil {
		onErr = s.OnError
	}
	g, err := r.admitLimits(f, a.Refs(), "", 0, depth, p+".admit")
	if err != nil {
		return nil, err
	}
	decisions := make([]any, len(g.checks))
	var lead map[string]any
	for i, c := range g.checks {
		var st *limState
		if i < len(g.states) {
			st = g.states[i]
		}
		remaining, retry := r.report(c, st)
		var lease any
		if c.leaseID != "" {
			lease = c.leaseID
		}
		d := map[string]any{"ok": c.decision != "reject" && c.decision != "fail_closed" && !c.rolled, "decision": c.decision,
			"limiter": c.full, "key": c.key, "remaining": remaining, "retry_after_ms": retry, "lease": lease}
		decisions[i] = d
		if lead == nil && (g.ok || c.decision == "reject" || c.decision == "fail_closed") {
			lead = d
		}
	}
	out := map[string]any{"ok": g.ok, "decision": nil, "limiter": nil, "key": nil, "remaining": nil, "retry_after_ms": nil, "lease": nil,
		"decisions": decisions, "error": nil}
	if lead != nil {
		for _, k := range []string{"decision", "limiter", "key", "remaining", "retry_after_ms", "lease"} {
			out[k] = lead[k]
		}
	}
	if g.ok {
		// The first lease taken, whichever limit took it.
		for _, d := range decisions {
			if l := d.(map[string]any)["lease"]; l != nil {
				out["lease"] = l
				break
			}
		}
	} else {
		out["ok"] = false
		out["error"] = g.err.Map()
		f.lastErr = g.err.Map()
	}
	if as != "" {
		f.vars[as] = deepCopy(out)
	}
	if g.ok {
		return nil, nil
	}
	return r.onError(f, onErr, g.err, depth, p, false)
}

// chargeStep consumes after the fact, down to floor; it never fails on the
// limit, but a propagated backend error fails the step.
func (r *run) chargeStep(f *frame, s model.Step, depth int, p string) (*exit, error) {
	ch := s.Charge
	c, err := r.resolveLimit(f, model.LimitRef{Limiter: ch.Limiter, Key: ch.Key, Cost: ch.Cost}, p+".charge")
	if err != nil {
		return nil, err
	}
	if c.unlimited {
		return nil, nil
	}
	be, err := r.backendCall(f, c, "charge", depth)
	if err != nil {
		return nil, err
	}
	var st *limState
	switch {
	case be != nil && (c.spec.OnBackendError == model.BackendFailOpen || c.spec.OnBackendError == model.BackendFailClosed):
		c.decision = c.spec.OnBackendError // nothing charged
	case be != nil:
		f.lastErr = be.Map()
		return &exit{err: be}, nil
	default:
		st = r.limState(c)
		r.consume(c, st, true)
		c.decision = "charge"
	}
	return nil, r.limEvent(f, c, st, "", 0)
}

// releaseStep frees a concurrency lease; a missing lease is a no-op.
func (r *run) releaseStep(f *frame, s model.Step, depth int, p string) (*exit, error) {
	rl := s.Release
	c, err := r.resolveLimit(f, model.LimitRef{Limiter: rl.Limiter, Key: rl.Key}, p+".release")
	if err != nil {
		return nil, err
	}
	id := ""
	if rl.Lease != nil {
		v, err := expr.Behavior.Template(expr.Native(rl.Lease), r.act(f, 1))
		if err != nil {
			return nil, abortf("%s.release.lease: %v", p, err)
		}
		if v == nil {
			return nil, nil // no lease to free
		}
		id = keyString(v)
	}
	be, err := r.backendCall(f, c, "release", depth)
	if err != nil {
		return nil, err
	}
	if be != nil && c.spec.OnBackendError != model.BackendFailOpen && c.spec.OnBackendError != model.BackendFailClosed {
		f.lastErr = be.Map()
		return &exit{err: be}, nil
	}
	if be != nil || !r.releaseLease(c, id) {
		return nil, nil
	}
	c.decision, c.leaseID = "release", id
	return nil, r.limEvent(f, c, r.lims.stores[c.store][c.key], "", 0)
}

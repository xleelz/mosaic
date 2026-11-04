package model

import (
	"fmt"
	"path"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/jsonschema"
)

// Issue severities.
const (
	SeverityError   = "error"
	SeverityWarning = "warning"
)

// Issue is one validation finding, located by a document path.
type Issue struct {
	Path     string `json:"path"`
	Message  string `json:"message"`
	Severity string `json:"severity"`
}

// HasErrors reports whether any issue is an error.
func HasErrors(issues []Issue) bool {
	for _, i := range issues {
		if i.Severity == SeverityError {
			return true
		}
	}
	return false
}

const maxStepDepth = 32

// Validate checks a whole document and returns every issue found.
func Validate(d *Document) []Issue {
	v := &validator{x: NewIndex(d)}
	v.run()
	sort.SliceStable(v.issues, func(a, b int) bool { return v.issues[a].Path < v.issues[b].Path })
	return v.issues
}

type validator struct {
	x      *Index
	issues []Issue
	loops  int // foreach bodies enclosing the steps being checked
}

func (v *validator) errf(path, format string, a ...any) {
	v.issues = append(v.issues, Issue{Path: path, Message: fmt.Sprintf(format, a...), Severity: SeverityError})
}

func (v *validator) warnf(path, format string, a ...any) {
	v.issues = append(v.issues, Issue{Path: path, Message: fmt.Sprintf(format, a...), Severity: SeverityWarning})
}

func (v *validator) expr(env *expr.Env, path, src string) {
	if _, err := env.Compile(src); err != nil {
		v.errf(path, "invalid expression %q: %v", src, err)
	}
	v.celText(path, src)
}

// celText runs the textual checks every CEL expression gets: config.<id>
// references must name known configs (§11.6), and wall-clock literals must
// not be compared with now (§11.3). Both are warnings.
func (v *validator) celText(path, src string) {
	for _, id := range ConfigRefs(src) {
		if _, ok := v.x.Configs[id]; !ok {
			v.warnf(path, "unknown config %q", id)
		}
	}
	if lit, ok := WallClockLiteral(src); ok {
		v.warnf(path, "the literal %s looks like a wall-clock time compared with now; derive timestamps from now (and set the scenario's clock) instead", lit)
	}
}

// onTarget checks an instance target: an instance name or "=cel".
func (v *validator) onTarget(path, on string) {
	if on == "" {
		return
	}
	if src, ok := expr.ExprOf(on); ok {
		v.expr(expr.Behavior, path, src)
	} else if !ValidID(on) {
		v.errf(path, "invalid instance name %q: use [a-z0-9][a-z0-9_-]{0,63} or an expression", on)
	}
}

func (v *validator) nonNegative(path string, n int64) {
	if n < 0 {
		v.errf(path, "must not be negative")
	}
}

// nonNegativeMS checks a millisecond field that may be fractional.
func (v *validator) nonNegativeMS(path string, n float64) {
	if n < 0 {
		v.errf(path, "must not be negative")
	}
}

// intOrExpr checks a number-or-template field (§13.1): a template must
// compile in the behavior environment, a number must not be negative.
func (v *validator) intOrExpr(path string, n IntOrExpr) {
	if n.IsExpr() {
		v.expr(expr.Behavior, path, strings.TrimSpace(n.Expr))
		return
	}
	v.nonNegative(path, n.N)
}

func (v *validator) template(path string, t any) {
	for _, src := range expr.TemplateExprs(t) {
		v.expr(expr.Behavior, path, src)
	}
}

func (v *validator) rawTemplate(path string, raw []byte) {
	t, err := expr.DecodeTemplate(raw)
	if err != nil {
		v.errf(path, "invalid JSON: %v", err)
		return
	}
	v.template(path, t)
}

func (v *validator) run() {
	d := v.x.Doc
	if d.SchemaVersion != 0 && d.SchemaVersion != SchemaVersion {
		v.errf("schema_version", "unsupported schema version %d (want %d)", d.SchemaVersion, SchemaVersion)
	}
	v.components()
	v.schemas()
	v.interfaces()
	v.links()
	v.flows()
	v.configs()
	v.fixtures()
	v.scenarios()
	v.hierarchy()
}

func (v *validator) unique(kind, id, path string, seen map[string]bool) {
	if seen[id] {
		v.errf(path, "duplicate %s id %q", kind, id)
	}
	seen[id] = true
}

func (v *validator) components() {
	seen := map[string]bool{}
	for _, c := range v.x.Doc.Components {
		p := "components[" + c.ID + "]"
		if !ValidPathID(c.ID) {
			v.errf(p+".id", "invalid id %q: use [a-z0-9][a-z0-9_-]{0,63}", c.ID)
		}
		v.unique(KindComponent, c.ID, p, seen)
		if c.Parent != "" {
			if _, ok := v.x.Components[c.Parent]; !ok {
				v.errf(p+".parent", "unknown component %q", c.Parent)
			}
		}
		v.router(p, c)
		v.limiters(p, c)
		if cp := c.Capacity; cp != nil {
			if cp.Concurrency < 1 {
				v.errf(p+".capacity.concurrency", "concurrency must be at least 1")
			}
			if cp.QueueLimit != nil && *cp.QueueLimit < 0 {
				v.errf(p+".capacity.queue_limit", "must not be negative")
			}
			v.nonNegative(p+".capacity.queue_timeout_ms", cp.QueueTimeoutMS)
		}
		if c.State != nil && c.State.Schema != nil && c.State.Initial != nil {
			for _, m := range jsonschema.Validate(c.State.Schema, expr.Native(c.State.Initial), v.x.SchemaRef()) {
				v.warnf(p+".state.initial", "%s", m)
			}
		}
	}
	for _, c := range v.x.Doc.Components {
		visited := map[string]bool{c.ID: true}
		for cur := c.Parent; cur != ""; {
			if visited[cur] {
				v.errf("components["+c.ID+"].parent", "parent chain forms a cycle through %q", cur)
				break
			}
			visited[cur] = true
			next, ok := v.x.Components[cur]
			if !ok {
				break
			}
			cur = next.Parent
		}
	}
}

func (v *validator) schemaRefs(path string, s any) {
	var walk func(string, any)
	walk = func(p string, s any) {
		switch t := s.(type) {
		case map[string]any:
			if r, ok := t["$ref"].(string); ok {
				if _, ok := v.x.ResolveSchema(r); !ok {
					v.errf(p, "unresolved $ref %q", r)
				}
			}
			for _, k := range sortedKeys(t) {
				walk(p+"."+k, t[k])
			}
		case []any:
			for i, x := range t {
				walk(fmt.Sprintf("%s[%d]", p, i), x)
			}
		}
	}
	walk(path, s)
}

func (v *validator) schemas() {
	seen := map[string]bool{}
	for _, s := range v.x.Doc.Schemas {
		p := "schemas[" + s.ID + "]"
		if !ValidSchemaID(s.ID) {
			v.errf(p+".id", "invalid schema id %q: use letters, digits, '_', '-' and '.'", s.ID)
		}
		v.unique(KindSchema, s.ID, p, seen)
		if s.Schema == nil {
			v.errf(p+".schema", "schema is required")
		}
		v.schemaRefs(p+".schema", s.Schema)
	}
}

// ValidSchemaID allows the capitalised names schemas usually have.
func ValidSchemaID(s string) bool {
	if s == "" || len(s) > 128 {
		return false
	}
	for _, r := range s {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '_' || r == '-' || r == '.') {
			return false
		}
	}
	return true
}

func (v *validator) schemaRef(path string, ref any) {
	if ref == nil {
		return
	}
	switch t := ref.(type) {
	case string:
		if _, ok := v.x.ResolveSchema(t); !ok {
			v.errf(path, "unknown schema %q", t)
		}
	case map[string]any:
		v.schemaRefs(path, t)
	default:
		v.errf(path, "must be a schema id or an inline JSON Schema object")
	}
}

func (v *validator) interfaces() {
	seen := map[string]bool{}
	for i := range v.x.Doc.Interfaces {
		f := &v.x.Doc.Interfaces[i]
		f.Normalize()
		p := "interfaces[" + f.ID + "]"
		if _, ok := v.x.Components[f.Component]; !ok {
			v.errf(p+".component", "unknown component %q", f.Component)
		}
		if !ValidID(f.Name) {
			v.errf(p+".name", "invalid name %q: use [a-z0-9][a-z0-9_-]{0,63}", f.Name)
		}
		if f.ID != f.Component+"."+f.Name {
			v.errf(p+".id", "id must be %q", f.Component+"."+f.Name)
		}
		v.unique(KindInterface, f.ID, p, seen)
		v.schemaRef(p+".request", f.Request)
		v.schemaRef(p+".response", f.Response)
		for j, e := range f.Errors {
			if e.Code == "" {
				v.errf(fmt.Sprintf("%s.errors[%d].code", p, j), "code is required")
			}
		}
		if l := f.LatencyMS; l != nil && l.Expr != "" {
			v.expr(expr.Behavior, p+".latency_ms", strings.TrimSpace(l.Expr))
		} else if l != nil && (l.Min < 0 || l.Max < l.Min) {
			v.errf(p+".latency_ms", "needs 0 <= min <= max")
		}
		for j, o := range f.LatencyByOutcome {
			q := fmt.Sprintf("%s.latency_by_outcome[%d]", p, j)
			if strings.TrimSpace(o.When) == "" {
				v.errf(q+".when", "when is required")
			} else {
				v.expr(expr.Outcome, q+".when", o.When)
			}
			switch {
			case o.MS.Expr != "":
				v.expr(expr.Outcome, q+".ms", strings.TrimSpace(o.MS.Expr))
			case o.MS.Min != o.MS.Max:
				v.errf(q+".ms", `must be milliseconds or an "=cel" expression, not a range`)
			case o.MS.Min < 0:
				v.errf(q+".ms", "needs ms >= 0")
			}
		}
		if w := f.StreamsWhen; w != "" {
			if src, ok := strings.CutPrefix(w, "="); !ok || strings.TrimSpace(src) == "" {
				v.errf(p+".streams_when", `streams_when must be an "=cel" expression, got %q`, w)
			} else {
				v.expr(expr.Behavior, p+".streams_when", strings.TrimSpace(src))
			}
			if !f.CanYield() {
				v.errf(p+".streams_when", "streams_when needs a behavior that can yield")
			}
		}
		for j, t := range f.Subscribe {
			if !ValidTopic(t) {
				v.errf(fmt.Sprintf("%s.subscribe[%d]", p, j), "invalid topic %q: use a slug or an interface id", t)
			}
		}
		v.interfaceLimits(f, p)
		names := map[string]bool{}
		v.steps(f, p+".behavior", f.Behavior, 0, names)
		if f.Store != nil {
			v.store(f, p+".store")
		}
	}
}

// storeError checks a store's error reference: an explicit code must be a
// declared error of the interface.
func (v *validator) storeError(f *Interface, path, code string) {
	if code == "" {
		return
	}
	for _, e := range f.Errors {
		if e.Code == code {
			return
		}
	}
	v.errf(path, "%q is not one of %s's declared errors", code, f.ID)
}

func (v *validator) store(f *Interface, p string) {
	if len(f.Behavior) > 0 {
		v.warnf(p, "the behavior runs instead of the store operation; drop one of them")
	}
	v.storeSpec(f, p, f.Store)
}

// storeSpec checks a store operation: an interface's store or one write of
// a transact step (§13.1 item 25), whose codes are f's declared errors.
func (v *validator) storeSpec(f *Interface, p string, st *StoreSpec) {
	if !ValidIdent(st.Table) {
		v.errf(p+".table", "table must be an identifier, got %q", st.Table)
	}
	if !contains(StoreOps, st.Op) {
		v.errf(p+".op", "op is one of %s", strings.Join(StoreOps, ", "))
		return
	}
	switch {
	case st.Op == "query" && st.Key != nil:
		v.errf(p+".key", "query reads the whole table and takes no key")
	case st.Op != "query" && st.Key == nil:
		v.errf(p+".key", "%s needs a key", st.Op)
	}
	switch st.Op {
	case "put", "update", "incr":
		if st.Value == nil {
			v.errf(p+".value", "%s needs a value", st.Op)
		}
	default:
		if st.Value != nil {
			v.errf(p+".value", "value goes with put, update and incr")
		}
	}
	v.updateNulls(p, st) // §17 item 6
	if st.Op == "incr" && st.Value != nil {
		switch t := expr.Native(st.Value).(type) {
		case int64, float64:
		case string:
			if _, ok := expr.ExprOf(t); !ok {
				v.errf(p+".value", "incr adds a number or a map of numbers")
			}
		case map[string]any:
		default:
			v.errf(p+".value", "incr adds a number or a map of numbers")
		}
	}
	if st.Default != nil && st.Op != "get" {
		v.errf(p+".default", "default goes with get")
	}
	if st.NotFound != "" && st.Op != "get" && st.Op != "update" {
		v.errf(p+".not_found", "not_found goes with get and update")
	}
	if st.Conflict != "" && ((st.Where == "" && st.If == "" && !st.IfAbsent) || st.Op == "get" || st.Op == "query") {
		v.errf(p+".conflict", "conflict goes with a write that has a where, if or if_absent condition")
	}
	if st.If != "" {
		if !contains(StoreWriteOps, st.Op) {
			v.errf(p+".if", "if goes with put, update, delete and incr")
		}
		v.expr(expr.Store, p+".if", st.If)
	}
	if st.IfAbsent && st.Op != "put" {
		v.errf(p+".if_absent", "if_absent goes with put")
	}
	v.storeError(f, p+".not_found", st.NotFound)
	v.storeError(f, p+".conflict", st.Conflict)
	v.template(p+".key", expr.Native(st.Key))
	v.template(p+".value", expr.Native(st.Value))
	v.template(p+".default", expr.Native(st.Default))
	if st.Where != "" {
		v.expr(expr.Store, p+".where", st.Where)
	}
}

func (v *validator) interfaceRef(path, id string) {
	if _, ok := v.x.Interfaces[id]; !ok {
		v.errf(path, "unknown interface %q", id)
	}
}

func (v *validator) steps(f *Interface, path string, steps []Step, depth int, choices map[string]bool) {
	if depth > maxStepDepth {
		v.errf(path, "steps nest deeper than %d", maxStepDepth)
		return
	}
	for i, s := range steps {
		p := fmt.Sprintf("%s[%d]", path, i)
		acts := s.Actions()
		if len(acts) > 1 {
			v.errf(p, "a step has one action; this one has %s", strings.Join(acts, ", "))
		}
		if len(acts) == 0 && s.Title == "" && s.Detail == "" {
			v.errf(p, "a step needs an action or a title")
		}
		if s.When != "" {
			v.expr(expr.Behavior, p+".when", s.When)
		}
		act := ""
		if len(acts) == 1 {
			act = acts[0]
		}
		if act != "call" && act != "emit" && act != "publish" && s.Input != nil {
			// The wording predates publish; it is kept so that existing
			// documents produce exactly the same issues.
			v.errf(p+".input", "input goes with call or emit")
		}
		if act != "call" && s.Fill {
			v.errf(p+".fill", "fill goes with call")
		}
		// as also names a foreach or parallel item; on_error also applies
		// to a publish; timeout_ms also bounds a parallel join.
		// on_error also handles a canceled wait (§13.1 item 14).
		// A rendezvous (§13.1 item 17) takes as, on_error and timeout_ms.
		// A put or receive (§13.1 item 18) takes on_error and timeout_ms;
		// a receive also takes as.
		rdv := act == "rendezvous" || act == "receive"
		ch := rdv || act == "put"
		// A transact (§13.1 item 25) takes as and on_error.
		// An admit (§13.1 item 27) takes as and on_error too.
		tx := act == "transact" || act == "admit"
		if act != "call" && ((s.As != "" && act != "foreach" && act != "parallel" && !rdv && !tx) || s.Retry != nil ||
			(s.OnError != nil && act != "publish" && act != "wait" && !ch && !tx) || (!s.TimeoutMS.IsZero() && act != "parallel" && !ch) || len(s.Targets) > 0) {
			v.errf(p, "as, retry, on_error, timeout_ms and targets go with call")
		}
		if act != "call" && (s.Stream || s.OnItem != nil) {
			v.errf(p, "stream and on_item go with call")
		}
		v.streamFlow(p, s) // §16.4
		if act != "put" && !s.Capacity.IsZero() {
			v.errf(p+".capacity", "capacity goes with put")
		}
		if act != "foreach" && (s.Max != 0 || ((s.Index != "" || s.Steps != nil) && act != "parallel")) {
			v.errf(p, "index, steps and max go with foreach")
		}
		if act != "parallel" && (s.Join != nil || !s.StaggerMS.IsZero() || s.AsResult != "" || s.OnInsufficient != nil || s.OnLate != nil) {
			v.errf(p, "join, stagger_ms, as_result, on_insufficient and on_late go with parallel")
		}
		if act != "publish" && s.Delivery != "" {
			v.errf(p+".delivery", "delivery goes with publish")
		}
		if act != "call" && act != "emit" && act != "publish" && s.On != "" {
			v.errf(p+".on", "on goes with call, emit or publish")
		}
		if act != "rendezvous" && ((s.Value != nil && act != "put") || s.LatencyMS != nil) {
			v.errf(p, "value and latency_ms go with rendezvous")
		}
		if act != "emit" && act != "publish" && (!s.AfterMS.IsZero() || !s.EveryMS.IsZero() || (!s.Count.IsZero() && act != "rendezvous")) {
			v.errf(p, "after_ms, every_ms and count go with emit or publish")
		}
		if act != "call" && !s.DeadlineMS.IsZero() {
			v.errf(p+".deadline_ms", "deadline_ms goes with call")
		}
		if act == "call" || act == "emit" || act == "publish" {
			v.onTarget(p+".on", s.On)
		}
		if s.Session != "" {
			if act == "call" && s.Stream {
				v.errf(p+".session", "session does not go with stream")
			} else if act == "call" {
				v.sessionKey(p+".session", s.Session)
			} else {
				v.errf(p+".session", "session goes with call")
			}
		}
		if s.Token != "" {
			switch act {
			case "call", "wait", "parallel", "emit", "publish":
				v.tokenName(p+".token", s.Token)
			default:
				v.errf(p+".token", "token goes with call, wait, parallel, emit or publish")
			}
		}
		if act != "if" && (s.Then != nil || s.Else != nil) {
			v.errf(p, "then and else go with if")
		}
		if act != "choice" && (s.Options != nil || s.Default != "") {
			v.errf(p, "options and default go with choice")
		}
		switch act {
		case "set":
			for _, k := range sortedKeys(s.Set) {
				if src, ok := expr.ExprOf(k); ok {
					// A dynamic path (§13.1 item 14), checked when it runs.
					v.expr(expr.Behavior, p+".set."+k, src)
				} else if err := checkPath(k); err != nil {
					v.errf(p+".set."+k, "%v", err)
				}
				v.template(p+".set."+k, s.Set[k])
			}
		case "cancel":
			v.tokenName(p+".cancel", s.Cancel)
		case "signal": // §17 item 2
			v.tokenName(p+".signal", s.Signal)
		case "close":
			v.sessionKey(p+".close.session", s.Close.Session)
		case "restart":
			v.restart(p+".restart", s.Restart, nil, expr.Behavior)
		case "rendezvous":
			v.rendezvous(f, p, s, depth, choices)
		case "yield":
			v.rawTemplate(p+".yield", s.Yield)
		case "put", "receive":
			v.channel(f, p, act, s, depth, choices)
		case "kill":
			v.kill(p+".kill", s.Kill, nil, expr.Behavior)
		case "transact":
			v.transact(f, p, s, depth, choices)
		case "admit", "charge", "release":
			v.limiterStep(f, p, act, s, depth, choices)
		case "call":
			v.call(f, p, s, depth, choices)
		case "if":
			v.expr(expr.Behavior, p+".if", s.If)
			v.steps(f, p+".then", s.Then, depth+1, choices)
			v.steps(f, p+".else", s.Else, depth+1, choices)
		case "choice":
			v.choice(f, p, s, depth, choices)
		case "return":
			v.rawTemplate(p+".return", s.Return)
		case "fail":
			t, err := expr.DecodeTemplate(s.Fail)
			if err != nil {
				v.errf(p+".fail", "invalid JSON: %v", err)
				break
			}
			if _, isExpr := expr.ExprOf(t); !isExpr {
				m, ok := t.(map[string]any)
				if !ok || m["code"] == nil {
					v.errf(p+".fail", "fail needs an object with a code, or an expression")
				}
			}
			v.template(p+".fail", t)
		case "emit":
			v.interfaceRef(p+".emit", s.Emit)
			v.rawTemplate(p+".input", s.Input)
			v.timer(p, s)
		case "publish":
			v.publish(f, p, s, depth, choices)
		case "foreach":
			v.foreach(f, p, s, depth, choices)
		case "parallel":
			v.parallel(f, p, s, depth, choices)
		case "break", "continue":
			if v.loops == 0 {
				v.errf(p+"."+act, "%s goes inside the steps of a foreach", act)
			}
		case "wait":
			switch w := expr.Native(s.Wait).(type) {
			case int64:
				if w < 0 {
					v.errf(p+".wait", "wait must not be negative")
				}
			case float64: // fractional milliseconds (§13.1 item 16)
				if w < 0 {
					v.errf(p+".wait", "wait must not be negative")
				}
			case string:
				if src, ok := expr.ExprOf(w); ok {
					v.expr(expr.Behavior, p+".wait", src)
				} else {
					v.errf(p+".wait", "wait is milliseconds or an expression")
				}
			case map[string]any: // a blocking wait (§17 item 2)
				v.waitSpec(f, p+".wait", s, depth, choices)
			default:
				v.errf(p+".wait", "wait is whole milliseconds or an expression")
			}
			if o := s.OnError; o != nil {
				switch {
				case o.Mode != "" && o.Mode != "propagate" && o.Mode != "continue":
					v.errf(p+".on_error", "on_error is propagate, continue or a list of steps")
				case o.Mode == "":
					v.steps(f, p+".on_error", o.Steps, depth+1, choices)
				}
			}
		}
	}
}

// tokenName checks a cancellation token name: a literal name or "=cel".
func (v *validator) tokenName(p, name string) {
	if src, ok := expr.ExprOf(name); ok {
		v.expr(expr.Behavior, p, src)
		return
	}
	if strings.TrimSpace(name) == "" {
		v.errf(p, "a token needs a name")
	}
}

// sessionKey checks a session key (§13.1 item 35): a literal or "=cel".
func (v *validator) sessionKey(p, key string) {
	if src, ok := expr.ExprOf(key); ok {
		v.expr(expr.Behavior, p, src)
		return
	}
	if strings.TrimSpace(key) == "" {
		v.errf(p, "a session needs a key")
	}
}

// restart checks a restart action (§13.1 item 14). topo is the scenario's
// topology for a scenario step, nil in a behavior; env checks an instance
// expression.
func (v *validator) restart(p string, r *Restart, topo map[string][]string, env *expr.Env) {
	if _, ok := v.x.Components[r.Component]; !ok {
		v.errf(p+".component", "unknown component %q", r.Component)
	}
	if src, ok := expr.ExprOf(r.Instance); ok {
		if env != nil {
			v.expr(env, p+".instance", src)
		} else {
			v.celText(p+".instance", src)
		}
	} else if r.Instance != "" {
		if !ValidID(r.Instance) {
			v.errf(p+".instance", "invalid instance name %q", r.Instance)
		} else if topo != nil {
			v.instanceIn(p+".instance", topo, r.Component, r.Instance)
		}
	}
	for j, k := range r.Keep {
		if _, ok := v.x.Components[k]; !ok {
			v.errf(fmt.Sprintf("%s.keep[%d]", p, j), "unknown component %q", k)
		}
	}
}

func (v *validator) call(f *Interface, p string, s Step, depth int, choices map[string]bool) {
	if s.Route != nil {
		v.route(p, s)
	} else if src, ok := expr.ExprOf(s.Call); ok {
		v.expr(expr.Behavior, p+".call", src)
		if len(s.Targets) == 0 {
			v.warnf(p+".targets", "a dynamic call without targets cannot be followed by plans and graphs")
		}
	} else {
		v.interfaceRef(p+".call", s.Call)
	}
	for j, t := range s.Targets {
		v.interfaceRef(fmt.Sprintf("%s.targets[%d]", p, j), t)
	}
	v.rawTemplate(p+".input", s.Input)
	if s.As != "" && !ValidIdent(s.As) {
		v.errf(p+".as", "invalid variable name %q", s.As)
	}
	// A negative timeout_ms keeps its original message ("must not be
	// negative"), which intOrExpr also uses.
	v.intOrExpr(p+".timeout_ms", s.TimeoutMS)
	v.intOrExpr(p+".deadline_ms", s.DeadlineMS)
	if s.OnItem != nil {
		if !s.Stream {
			v.errf(p+".on_item", "on_item needs stream: true")
		}
		v.steps(f, p+".on_item", s.OnItem, depth+1, choices)
	}
	if r := s.Retry; r != nil {
		rp := p + ".retry"
		switch m := expr.Native(r.MaxAttempts).(type) {
		case nil:
			v.errf(rp+".max_attempts", "max_attempts is required")
		case int64:
			if m < 1 || m > 20 {
				v.errf(rp+".max_attempts", "must be between 1 and 20")
			}
		case string:
			if src, ok := expr.ExprOf(m); ok {
				v.expr(expr.Behavior, rp+".max_attempts", src)
			} else {
				v.errf(rp+".max_attempts", "a number or an expression")
			}
		default:
			v.errf(rp+".max_attempts", "a whole number or an expression")
		}
		if r.BackoffMS < 0 || r.MaxBackoffMS < 0 || r.Multiplier < 0 {
			v.errf(rp, "backoff values must not be negative")
		}
		switch r.Jitter {
		case "", "none", "full", "equal":
		default:
			v.errf(rp+".jitter", "jitter is none, full or equal, got %q", r.Jitter)
		}
		if r.When != "" {
			v.expr(expr.Behavior, rp+".when", r.When)
		}
		for _, st := range r.OnStatus {
			if st < 100 || st > 599 {
				v.errf(rp+".on_status", "a status is between 100 and 599, got %d", st)
			}
		}
		for _, c := range r.OnCodes {
			if strings.TrimSpace(c) == "" {
				v.errf(rp+".on_codes", "a code must not be empty")
			}
		}
	}
	if o := s.OnError; o != nil {
		switch {
		case o.Mode != "" && o.Mode != "propagate" && o.Mode != "continue":
			v.errf(p+".on_error", "on_error is propagate, continue or a list of steps")
		case o.Mode == "":
			v.steps(f, p+".on_error", o.Steps, depth+1, choices)
		}
	}
}

// timer checks the §11.3 timer fields of an emit or publish.
func (v *validator) timer(p string, s Step) {
	v.intOrExpr(p+".after_ms", s.AfterMS)
	v.intOrExpr(p+".every_ms", s.EveryMS)
	switch {
	case s.EveryMS.IsZero() && !s.Count.IsZero():
		v.errf(p+".count", "count goes with every_ms")
	case s.EveryMS.IsZero():
	case s.Count.IsExpr():
		v.intOrExpr(p+".count", s.Count)
	case s.Count.N < 1 || s.Count.N > MaxTimerCount || !s.Count.IsWhole():
		// A template count is checked when the step runs.
		v.errf(p+".count", "a periodic timer needs a count between 1 and %d", MaxTimerCount)
	}
}

func (v *validator) publish(f *Interface, p string, s Step, depth int, choices map[string]bool) {
	if !ValidTopic(s.Publish) {
		v.errf(p+".publish", "invalid topic %q: use a slug or an interface id", s.Publish)
	} else if len(v.x.Subscribers[s.Publish]) == 0 && !importableAlone(v.x.Doc) {
		v.warnf(p+".publish", "no interface subscribes to %q", s.Publish)
	}
	if s.Delivery != "" && !contains(Deliveries, s.Delivery) {
		v.errf(p+".delivery", "delivery is one of %s", strings.Join(Deliveries, ", "))
	}
	v.rawTemplate(p+".input", s.Input)
	v.timer(p, s)
	if o := s.OnError; o != nil {
		switch {
		case o.Mode != "" && o.Mode != "propagate" && o.Mode != "continue":
			v.errf(p+".on_error", "on_error is propagate, continue or a list of steps")
		case o.Mode == "":
			v.steps(f, p+".on_error", o.Steps, depth+1, choices)
		}
	}
}

// parallel checks a §11.2 parallel step. Its branches are not loop bodies:
// break and continue inside them do not reach an enclosing foreach.
func (v *validator) parallel(f *Interface, p string, s Step, depth int, choices map[string]bool) {
	branches := -1 // the number of branches, when it is known statically
	switch {
	case s.Parallel != nil && s.Branches != nil:
		v.errf(p, "parallel and branches are alternatives; set one of them")
	case s.Branches != nil:
		branches = len(s.Branches)
		if len(s.Branches) == 0 {
			v.errf(p+".branches", "branches needs at least one branch")
		}
		if s.Steps != nil {
			v.errf(p+".steps", "steps goes with parallel, not branches (each branch lists its own steps)")
		}
	default:
		switch t := expr.Native(s.Parallel).(type) {
		case string:
			if src, ok := expr.ExprOf(t); ok {
				v.expr(expr.Behavior, p+".parallel", src)
			} else {
				v.errf(p+".parallel", "parallel is a list, a map or an expression")
			}
		case []any:
			branches = len(t)
			v.template(p+".parallel", t)
		case map[string]any:
			branches = len(t)
			v.template(p+".parallel", t)
		default:
			v.errf(p+".parallel", "parallel is a list, a map or an expression")
		}
		if len(s.Steps) == 0 {
			v.errf(p+".steps", "a parallel needs steps")
		}
	}
	as, index := s.As, s.Index
	if as == "" {
		as = "item"
	}
	if index == "" {
		index = "index"
	}
	if !ValidIdent(as) {
		v.errf(p+".as", "invalid variable name %q", as)
	}
	if !ValidIdent(index) {
		v.errf(p+".index", "invalid variable name %q", index)
	}
	if as == index {
		v.errf(p+".index", "index and as must name different variables")
	}
	if s.AsResult != "" && !ValidIdent(s.AsResult) {
		v.errf(p+".as_result", "invalid variable name %q", s.AsResult)
	}
	if s.Join != nil {
		switch n := expr.Native(s.Join.Need).(type) {
		case nil:
		case int64:
			if n < 0 {
				v.errf(p+".join.need", "need must not be negative")
			} else if branches >= 0 && n > int64(branches) {
				v.warnf(p+".join.need", "need %d is more than the %d branches, so the join always fails", n, branches)
			}
		case string:
			if src, ok := expr.ExprOf(n); ok {
				v.expr(expr.Behavior, p+".join.need", src)
			} else if n != JoinAll && n != JoinAny {
				v.errf(p+".join.need", "need is a whole number, %q, %q or an expression", JoinAll, JoinAny)
			}
		default:
			v.errf(p+".join.need", "need is a whole number, %q, %q or an expression", JoinAll, JoinAny)
		}
	}
	if !s.Join.Unstarted() && s.StaggerMS.IsZero() {
		v.warnf(p+".join.count_unstarted", "count_unstarted: false has no effect without stagger_ms")
	}
	v.intOrExpr(p+".stagger_ms", s.StaggerMS)
	v.intOrExpr(p+".timeout_ms", s.TimeoutMS)
	if e := s.OnInsufficient; e != nil && e.Code == "" {
		v.errf(p+".on_insufficient.code", "code is required")
	}
	loops := v.loops
	v.loops = 0
	if s.Branches != nil {
		for j, b := range s.Branches {
			v.steps(f, fmt.Sprintf("%s.branches[%d]", p, j), b, depth+1, choices)
		}
	} else {
		v.steps(f, p+".steps", s.Steps, depth+1, choices)
	}
	if s.OnLate != nil {
		v.steps(f, p+".on_late", s.OnLate, depth+1, choices)
	}
	v.loops = loops
}

// ValidTopic reports whether s can name a publish topic: a slug, or an
// interface id ("<component>.<name>"), which is the usual convention. §11.5
// calls a topic "any slug" yet names interface ids, which hold a dot; both
// are accepted.
func ValidTopic(s string) bool {
	s = unprefixTopic(s) // an imported document's topic (§17 item 8)
	if ValidID(s) {
		return true
	}
	c, n, ok := strings.Cut(s, ".")
	return ok && ValidID(c) && ValidID(n)
}

func (v *validator) foreach(f *Interface, p string, s Step, depth int, choices map[string]bool) {
	switch t := expr.Native(s.Foreach).(type) {
	case string:
		if src, ok := expr.ExprOf(t); ok {
			v.expr(expr.Behavior, p+".foreach", src)
		} else {
			v.errf(p+".foreach", "foreach is a list or an expression")
		}
	case []any:
		v.template(p+".foreach", t)
	default:
		v.errf(p+".foreach", "foreach is a list or an expression")
	}
	as, index := s.As, s.Index
	if as == "" {
		as = "item"
	}
	if index == "" {
		index = "index"
	}
	if !ValidIdent(as) {
		v.errf(p+".as", "invalid variable name %q", as)
	}
	if !ValidIdent(index) {
		v.errf(p+".index", "invalid variable name %q", index)
	}
	if as == index {
		v.errf(p+".index", "index and as must name different variables")
	}
	if s.Max < 0 || s.Max > MaxMaxForeach { // §17 item 18: cut to the run's foreach cap
		v.errf(p+".max", "must be between 1 and %d", MaxMaxForeach)
	}
	if len(s.Steps) == 0 {
		v.errf(p+".steps", "a foreach needs steps")
	}
	v.loops++
	v.steps(f, p+".steps", s.Steps, depth+1, choices)
	v.loops--
}

func (v *validator) choice(f *Interface, p string, s Step, depth int, choices map[string]bool) {
	if !ValidIdent(s.Choice) {
		v.errf(p+".choice", "invalid choice name %q", s.Choice)
	}
	if choices[s.Choice] {
		v.errf(p+".choice", "choice %q is declared twice in %s", s.Choice, f.ID)
	}
	choices[s.Choice] = true
	if len(s.Options) == 0 {
		v.errf(p+".options", "a choice needs at least one option")
	}
	for _, name := range sortedKeys(s.Options) {
		if !ValidOption(name) {
			v.errf(p+".options."+name, "invalid option name")
		}
		v.steps(f, p+".options."+name, s.Options[name], depth+1, choices)
	}
	switch {
	case s.Default == "" && len(s.Options) > 1:
		v.errf(p+".default", "a choice with several options needs a default")
	case s.Default != "":
		if src, ok := expr.ExprOf(s.Default); ok {
			v.expr(expr.Behavior, p+".default", src)
		} else if _, ok := s.Options[s.Default]; !ok {
			v.errf(p+".default", "default %q is not an option", s.Default)
		}
	}
}

// ValidOption reports whether s is a choice option name.
func ValidOption(s string) bool {
	if s == "" || len(s) > 64 {
		return false
	}
	for _, r := range s {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '_' || r == '-') {
			return false
		}
	}
	return true
}

// Path roots that set may assign.
var pathRoots = map[string]bool{"vars": true, "ctx": true, "state": true}

func checkPath(path string) error {
	segs := strings.Split(path, ".")
	if len(segs) < 2 || !pathRoots[segs[0]] {
		return fmt.Errorf("path %q must start with vars., ctx. or state.", path)
	}
	for _, s := range segs[1:] {
		if !ValidIdent(s) {
			return fmt.Errorf("invalid path segment %q in %q", s, path)
		}
	}
	return nil
}

func (v *validator) endpoint(path, id string) {
	if _, ok := v.x.Components[id]; ok {
		return
	}
	if _, ok := v.x.Interfaces[id]; ok {
		return
	}
	v.errf(path, "unknown component or interface %q", id)
}

func (v *validator) links() {
	seen := map[string]bool{}
	for _, l := range v.x.Doc.Links {
		p := "links[" + l.ID + "]"
		if !ValidPathID(l.ID) {
			v.errf(p+".id", "invalid id %q", l.ID)
		}
		v.unique(KindLink, l.ID, p, seen)
		v.endpoint(p+".from", l.From)
		v.endpoint(p+".to", l.To)
	}
}

func (v *validator) flows() {
	seen := map[string]bool{}
	for _, f := range v.x.Doc.Flows {
		p := "flows[" + f.ID + "]"
		if !ValidID(f.ID) {
			v.errf(p+".id", "invalid id %q", f.ID)
		}
		v.unique(KindFlow, f.ID, p, seen)
		if e := f.Entry; e != nil {
			if _, ok := v.x.Components[e.Caller]; !ok {
				v.errf(p+".entry.caller", "unknown component %q", e.Caller)
			}
			v.interfaceRef(p+".entry.interface", e.Interface)
			v.rawTemplate(p+".entry.input", e.Input)
			v.onTarget(p+".entry.on", e.On)
			v.intOrExpr(p+".entry.deadline_ms", e.DeadlineMS)
			v.repeat(p+".entry.repeat", e.Repeat)
		}
		for i, s := range f.Steps {
			sp := fmt.Sprintf("%s.steps[%d]", p, i)
			if _, ok := v.x.Components[s.Component]; !ok {
				v.errf(sp+".component", "unknown component %q", s.Component)
			}
			if s.Title == "" {
				v.errf(sp+".title", "title is required")
			}
		}
		if f.Entry == nil && len(f.Steps) == 0 {
			v.errf(p, "a flow needs an entry to simulate or steps to narrate")
		}
	}
}

func (v *validator) scenarios() {
	points := v.x.ChoicePoints()
	seen := map[string]bool{}
	for i := range v.x.Doc.Scenarios {
		s := &v.x.Doc.Scenarios[i]
		p := "scenarios[" + s.ID + "]"
		if !ValidID(s.ID) {
			v.errf(p+".id", "invalid id %q", s.ID)
		}
		v.unique(KindScenario, s.ID, p, seen)
		v.resolution(p, s.Resolution)
		if len(s.Steps) == 0 {
			if f, ok := v.x.Flows[s.Flow]; !ok {
				v.errf(p+".flow", "unknown flow %q", s.Flow)
			} else if f.Entry == nil {
				v.errf(p+".flow", "flow %q has no entry to simulate", s.Flow)
			}
		} else {
			// With steps the flow only groups the scenario (§11.7).
			if _, ok := v.x.Flows[s.Flow]; s.Flow != "" && !ok {
				v.errf(p+".flow", "unknown flow %q", s.Flow)
			}
			// §11.7 gives each step its own input; a scenario-level input
			// has no defined meaning beside steps, so it is refused.
			if s.Input != nil {
				v.errf(p+".input", "with steps, set input on each step")
			}
		}
		v.rawTemplate(p+".input", s.Input)
		v.choices(p+".choices", s.Choices, points)
		for j, id := range s.Fixtures {
			if _, ok := v.x.Fixtures[id]; !ok {
				v.errf(fmt.Sprintf("%s.fixtures[%d]", p, j), "unknown fixture %q", id)
			}
		}
		v.worldLayer(p, s.Layer())
		// The scenario's topology: its fixtures', then its own. A run
		// request can still replace it, so instance mismatches are warnings.
		topo := map[string][]string{}
		if chain, err := v.x.FixtureChain(s.Fixtures); err == nil {
			for _, f := range chain {
				for c, inst := range f.Topology {
					topo[c] = inst
				}
			}
		}
		for c, inst := range s.Topology {
			topo[c] = inst
		}
		for _, k := range sortedKeys(s.State) {
			if c, inst := SplitStateKey(k); inst != "" {
				v.instanceIn(p+".state."+k, topo, c, inst)
			}
		}
		if s.MaxVirtualMS != nil && *s.MaxVirtualMS <= 0 {
			v.errf(p+".max_virtual_ms", "max_virtual_ms must be positive")
		}
		if s.MaxEvents != nil && (*s.MaxEvents <= 0 || *s.MaxEvents > MaxMaxEvents) {
			v.errf(p+".max_events", "max_events must be between 1 and %d", MaxMaxEvents)
		}
		if s.CostLimit != nil && *s.CostLimit <= 0 {
			v.errf(p+".cost_limit", "cost_limit must be positive")
		}
		v.scenarioCaps(p, s) // §15.3, sim153.go
		v.foreachCap(p, s)   // §17 item 18, sim17.go
		stepNames := map[string]bool{}
		for j, st := range s.Steps {
			v.scenarioStep(fmt.Sprintf("%s.steps[%d]", p, j), st, points, topo, stepNames)
		}
		for j, ft := range s.Faults {
			fp := fmt.Sprintf("%s.faults[%d]", p, j)
			v.fault(fp, ft)
			if c, ok := v.x.componentOf(ft.Target); ok {
				v.instanceIn(fp+".instance", topo, c, ft.Instance)
			}
		}
		for j, m := range s.Mocks {
			v.mock(fmt.Sprintf("%s.mocks[%d]", p, j), m, topo)
		}
		for j, e := range s.Expect {
			v.expr(expr.Expect, fmt.Sprintf("%s.expect[%d]", p, j), e)
			v.expectHeaders(fmt.Sprintf("%s.expect[%d]", p, j), s, e)
		}
		v.invariants(p, s)   // §16.2, invariants.go
		v.scenarioTags(p, s) // §17 item 1, scenariotags.go
	}
}

func (v *validator) choices(p string, choices map[string]Choice, points map[string]ChoicePoint) {
	for _, k := range sortedKeys(choices) {
		cp, ok := points[k]
		if !ok {
			v.errf(p+"."+k, "unknown choice point %q (keys are <interface>.<choice>)", k)
			continue
		}
		c := choices[k]
		if src, ok := expr.ExprOf(c.Option); ok && c.IsScalar() {
			// A step's choice may be an expression, evaluated per pass
			// (§13.1 item 27); the run checks the option it gives.
			v.celText(p+"."+k, src)
			continue
		}
		if c.Seq != nil && len(c.Seq) == 0 {
			v.errf(p+"."+k, "a choice list names at least one option")
		}
		for _, o := range c.Options() {
			if !contains(cp.Options, o) {
				v.errf(p+"."+k, "option %q is not one of %s", o, strings.Join(cp.Options, ", "))
			}
		}
	}
}

// repeat checks a flow entry's or scenario step's repeat (§13.1 item 24).
func (v *validator) repeat(p string, r *Repeat) {
	if r == nil {
		return
	}
	if r.Count < 1 || r.Count > MaxRepeatCount {
		v.errf(p+".count", "must be between 1 and %d", MaxRepeatCount)
	}
	if r.IntervalMS < 0 {
		v.errf(p+".interval_ms", "must not be negative")
	}
	v.nonNegativeMS(p+".initial_delay_ms", r.InitialDelayMS)
}

// worldLayer checks the starting-world settings of a fixture or scenario.
func (v *validator) worldLayer(p string, l WorldLayer) {
	for _, c := range sortedKeys(l.Topology) {
		tp := p + ".topology." + c
		if _, ok := v.x.Components[c]; !ok {
			v.errf(tp, "unknown component %q", c)
		}
		if len(l.Topology[c]) == 0 {
			v.errf(tp, "a topology entry names at least one instance")
		}
		names := map[string]bool{}
		for j, inst := range l.Topology[c] {
			if !ValidID(inst) {
				v.errf(fmt.Sprintf("%s[%d]", tp, j), "invalid instance name %q: use [a-z0-9][a-z0-9_-]{0,63}", inst)
			}
			if names[inst] {
				v.errf(fmt.Sprintf("%s[%d]", tp, j), "instance %q is listed twice", inst)
			}
			names[inst] = true
		}
	}
	if c := l.Clock; c != nil {
		if c.Epoch != "" && c.EpochMS != 0 {
			v.errf(p+".clock", "set epoch or epoch_ms, not both")
		}
		if _, err := c.EpochMillis(); err != nil {
			v.errf(p+".clock.epoch", "%v", err)
		}
		v.nonNegative(p+".clock.epoch_ms", c.EpochMS)
	}
	for _, k := range sortedKeys(l.Config) {
		if _, ok := v.x.Configs[k]; !ok {
			v.errf(p+".config."+k, "unknown config %q", k)
		}
	}
	v.limiterSeeds(p, l.Limiters)
	for _, k := range sortedKeys(l.State) {
		c, inst := SplitStateKey(k)
		if _, ok := v.x.Components[c]; !ok {
			v.errf(p+".state."+k, "unknown component %q", c)
		}
		if strings.Contains(k, "@") && !ValidID(inst) {
			v.errf(p+".state."+k, "invalid instance name %q (keys are <component> or <component>@<instance>)", inst)
		}
	}
}

// instanceIn warns when a literal instance name cannot be one of comp's
// instances in the given topology.
func (v *validator) instanceIn(p string, topo map[string][]string, comp, inst string) {
	if inst == "" {
		return
	}
	if _, isExpr := expr.ExprOf(inst); isExpr || !ValidID(inst) {
		return
	}
	if _, ok := v.x.Components[comp]; !ok {
		return
	}
	group, list, ok := v.x.InstanceGroup(topo, comp)
	switch {
	case !ok:
		v.warnf(p, "%s has no instances in the scenario's topology, so instance %q does not exist", comp, inst)
	case !contains(list, inst):
		v.warnf(p, "instance %q is not one of %s's instances (%s)", inst, group, strings.Join(list, ", "))
	}
}

func (v *validator) scenarioStep(p string, st ScenarioStep, points map[string]ChoicePoint, topo map[string][]string, names map[string]bool) {
	comp := ""
	n := 0
	for _, set := range []bool{st.Flow != "", st.Interface != "", st.Cancel != "", st.Restart != nil, st.Kill != nil, st.Set != nil, st.Close != nil} {
		if set {
			n++
		}
	}
	switch {
	case st.IsControl() && n > 1 && st.Close != nil:
		v.errf(p, "a step names one of a flow, an interface, cancel, restart, kill, set or close")
	case st.IsControl() && n > 1 && st.Set != nil:
		v.errf(p, "a step names one of a flow, an interface, cancel, restart, kill or set")
	case st.IsControl() && n > 1 && st.Kill != nil:
		v.errf(p, "a step names one of a flow, an interface, cancel, restart or kill")
	case st.IsControl() && n > 1:
		v.errf(p, "a step names one of a flow, an interface, cancel or restart")
	case st.IsControl():
		if st.Caller != "" || st.Input != nil || st.On != "" || len(st.Choices) > 0 || !st.DeadlineMS.IsZero() {
			v.errf(p, "caller, input, on, choices and deadline_ms go with a flow or interface step")
		}
		if st.Repeat != nil {
			v.errf(p+".repeat", "repeat goes with a flow or interface step")
		}
		if st.Lane != "" {
			v.errf(p+".lane", "lane goes with a flow or interface step")
		}
		switch {
		case st.Cancel != "":
			if src, ok := expr.ExprOf(st.Cancel); ok {
				v.celText(p+".cancel", src)
			}
		case st.Kill != nil:
			v.kill(p+".kill", st.Kill, topo, nil)
		case st.Set != nil:
			v.setStep(p+".set", st, topo) // §15.3, sim153.go
		case st.Close != nil:
			v.closeStep(p+".close", st.Close) // §17 item 21, sim17.go
		default:
			v.restart(p+".restart", st.Restart, topo, nil)
		}
	case st.Flow != "" && st.Interface != "":
		v.errf(p, "a step names a flow or an interface, not both")
	case st.Flow != "":
		if f, ok := v.x.Flows[st.Flow]; !ok {
			v.errf(p+".flow", "unknown flow %q", st.Flow)
		} else if f.Entry == nil {
			v.errf(p+".flow", "flow %q has no entry to simulate", st.Flow)
		} else if iface, ok := v.x.Interfaces[f.Entry.Interface]; ok {
			comp = iface.Component
		}
		if st.Caller != "" {
			v.errf(p+".caller", "caller goes with interface; a flow step uses its entry's caller")
		}
	case st.Interface != "":
		if iface, ok := v.x.Interfaces[st.Interface]; !ok {
			v.errf(p+".interface", "unknown interface %q", st.Interface)
		} else {
			comp = iface.Component
		}
		if st.Caller == "" {
			v.errf(p+".caller", "an interface step needs a caller")
		} else if _, ok := v.x.Components[st.Caller]; !ok {
			v.errf(p+".caller", "unknown component %q", st.Caller)
		}
	default:
		v.errf(p, "a step names a flow or an interface")
	}
	// Step templates also see steps.<as>, which no expr environment declares
	// yet, so only their JSON is checked here, plus the textual CEL checks.
	if t, err := expr.DecodeTemplate(st.Input); err != nil {
		v.errf(p+".input", "invalid JSON: %v", err)
	} else {
		for _, src := range expr.TemplateExprs(t) {
			v.celText(p+".input", src)
		}
	}
	if src, ok := expr.ExprOf(st.On); ok {
		v.celText(p+".on", src)
	} else if st.On != "" {
		if !ValidID(st.On) {
			v.errf(p+".on", "invalid instance name %q: use [a-z0-9][a-z0-9_-]{0,63} or an expression", st.On)
		} else if comp != "" {
			v.instanceIn(p+".on", topo, comp, st.On)
		}
	}
	v.choices(p+".choices", st.Choices, points)
	v.limiterSeeds(p, st.Limiters)
	if !st.IsControl() {
		v.repeat(p+".repeat", st.Repeat)
	}
	v.intOrExpr(p+".deadline_ms", st.DeadlineMS)
	if st.AtMS != nil {
		v.nonNegativeMS(p+".at_ms", *st.AtMS)
	}
	if st.Lane != "" && !st.IsControl() && !ValidID(st.Lane) {
		v.errf(p+".lane", "invalid lane name %q: use [a-z0-9][a-z0-9_-]{0,63}", st.Lane)
	}
	if st.As != "" {
		if !ValidIdent(st.As) {
			v.errf(p+".as", "invalid step name %q", st.As)
		}
		if names[st.As] {
			v.errf(p+".as", "step name %q is used twice", st.As)
		}
		names[st.As] = true
	}
}

func (v *validator) mock(p string, m Mock, topo map[string][]string) {
	iface, ok := v.x.Interfaces[m.Interface]
	if !ok {
		v.errf(p+".interface", "unknown interface %q", m.Interface)
	}
	if m.Instance != "" {
		if !ValidID(m.Instance) {
			v.errf(p+".instance", "invalid instance name %q", m.Instance)
		} else if ok {
			v.instanceIn(p+".instance", topo, iface.Component, m.Instance)
		}
	}
	if m.When != "" {
		v.expr(expr.Behavior, p+".when", m.When)
	}
	switch {
	case m.Return != nil && m.Fail != nil:
		v.errf(p, "a mock returns or fails, not both")
	case m.Return == nil && m.Fail == nil:
		v.errf(p, "a mock needs return or fail")
	case m.Return != nil:
		v.rawTemplate(p+".return", m.Return)
	default:
		t, err := expr.DecodeTemplate(m.Fail)
		if err != nil {
			v.errf(p+".fail", "invalid JSON: %v", err)
			break
		}
		if _, isExpr := expr.ExprOf(t); !isExpr {
			if mm, ok := t.(map[string]any); !ok || mm["code"] == nil {
				v.errf(p+".fail", "fail needs an object with a code, or an expression")
			}
		}
		v.template(p+".fail", t)
	}
	for _, n := range m.Calls {
		if n < 1 {
			v.errf(p+".calls", "call numbers start at 1")
		}
	}
}

func (v *validator) configs() {
	seen := map[string]bool{}
	for _, c := range v.x.Doc.Configs {
		p := "configs[" + c.ID + "]"
		if !ValidPathID(c.ID) { // "<as>/<id>" names an imported config (§15.6)
			v.errf(p+".id", "invalid id %q: use [a-z0-9][a-z0-9_-]{0,63}, or <import as>/<id>", c.ID)
		}
		v.unique(KindConfig, c.ID, p, seen)
		if c.Type == "" {
			continue
		}
		if !contains(ConfigTypes, c.Type) {
			v.errf(p+".type", "type is one of %s", strings.Join(ConfigTypes, ", "))
			continue
		}
		for _, f := range []struct {
			name string
			val  any
		}{{"value", c.Value}, {"default", c.Default}} {
			if f.val != nil && !hasType(expr.Native(f.val), c.Type) {
				v.warnf(p+"."+f.name, "%s is not of type %s", f.name, c.Type)
			}
		}
	}
}

// hasType reports whether a native JSON value has a JSON Schema type.
func hasType(val any, typ string) bool {
	switch val.(type) {
	case string:
		return typ == "string"
	case bool:
		return typ == "boolean"
	case int64:
		return typ == "integer" || typ == "number"
	case float64:
		return typ == "number"
	case map[string]any:
		return typ == "object"
	case []any:
		return typ == "array"
	}
	return false
}

func (v *validator) fixtures() {
	seen := map[string]bool{}
	for i := range v.x.Doc.Fixtures {
		f := &v.x.Doc.Fixtures[i]
		p := "fixtures[" + f.ID + "]"
		if !ValidID(f.ID) {
			v.errf(p+".id", "invalid id %q: use [a-z0-9][a-z0-9_-]{0,63}", f.ID)
		}
		v.unique(KindFixture, f.ID, p, seen)
		for j, e := range f.Extends {
			if _, ok := v.x.Fixtures[e]; !ok {
				v.errf(fmt.Sprintf("%s.extends[%d]", p, j), "unknown fixture %q", e)
			}
		}
		// Instances in state keys are not checked against the topology
		// here: a base fixture often seeds state for instances that a
		// fixture extending it names.
		v.worldLayer(p, f.Layer())
	}
	// Cycles: report each fixture whose extends chain runs into a cycle.
	for _, f := range v.x.Doc.Fixtures {
		if _, err := v.x.FixtureChain([]string{f.ID}); err != nil && strings.Contains(err.Error(), "cycle") {
			v.errf("fixtures["+f.ID+"].extends", "%v", err)
		}
	}
}

func (v *validator) fault(p string, f Fault) {
	v.endpoint(p+".target", f.Target)
	if f.Instance != "" && !ValidID(f.Instance) {
		v.errf(p+".instance", "invalid instance name %q", f.Instance)
	}
	if f.Type == FaultKill {
		switch {
		case f.AtMS == nil:
			v.errf(p+".at_ms", "a kill fault needs at_ms")
		case *f.AtMS < 0:
			v.errf(p+".at_ms", "at_ms must not be negative")
		}
		if len(f.Calls) > 0 || f.Code != "" || f.LatencyMS != 0 {
			v.errf(p, "calls, code and latency_ms do not go with a kill fault")
		}
		if f.Match != "" || f.Caller != "" {
			v.errf(p, "match and caller do not go with a kill fault")
		}
	} else if !contains(FaultTypes, f.Type) {
		v.errf(p+".type", "type is one of %s", strings.Join(FaultTypes, ", "))
	} else if f.AtMS != nil {
		v.errf(p+".at_ms", "at_ms goes with a kill fault")
	}
	if f.Type == "error" && f.Code == "" {
		v.errf(p+".code", "an error fault needs a code")
	}
	if f.Type == "latency" && f.LatencyMS <= 0 {
		v.errf(p+".latency_ms", "a latency fault needs latency_ms > 0")
	}
	switch {
	case f.Type == FaultCrash && f.AfterSteps == nil:
		v.errf(p+".after_steps", "a crash fault needs after_steps")
	case f.Type == FaultCrash && *f.AfterSteps < 0:
		v.errf(p+".after_steps", "after_steps must not be negative")
	case f.Type != FaultCrash && f.AfterSteps != nil:
		v.errf(p+".after_steps", "after_steps goes with a crash fault")
	}
	for _, n := range f.Calls {
		if n < 1 {
			v.errf(p+".calls", "call numbers start at 1")
		}
	}
	// §13.1 item 35: match and caller narrow the calls a fault applies to;
	// forever makes a hang never answer.
	if f.Match != "" {
		v.expr(expr.Behavior, p+".match", f.Match)
	}
	if f.Caller != "" {
		if _, err := path.Match(f.Caller, ""); err != nil || strings.TrimSpace(f.Caller) != f.Caller {
			v.errf(p+".caller", "caller is an interface id or a glob, got %q", f.Caller)
		} else if !strings.ContainsAny(f.Caller, "*?[") {
			if _, ok := v.x.Interfaces[f.Caller]; !ok {
				if _, ok := v.x.Components[f.Caller]; !ok {
					v.warnf(p+".caller", "no interface or component %q calls anything", f.Caller)
				}
			}
		}
	}
	if f.Forever && f.Type != FaultHang && f.Type != "timeout" && f.Type != FaultLostReply {
		v.errf(p+".forever", "forever goes with a hang, timeout or lost_reply fault")
	}
	if f.Forever && f.Type == FaultLostReply && f.Code != "" {
		v.errf(p+".forever", "a lost_reply fault with a code answers with it; forever goes without code")
	}
}

// ValidateFaults checks faults supplied outside a scenario, such as in a run request.
func ValidateFaults(d *Document, faults []Fault) []Issue {
	v := &validator{x: NewIndex(d)}
	for i, f := range faults {
		v.fault(fmt.Sprintf("faults[%d]", i), f)
	}
	return v.issues
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// rendezvous checks a rendezvous step (§13.1 item 17).
func (v *validator) rendezvous(f *Interface, p string, s Step, depth int, choices map[string]bool) {
	v.tokenName(p+".rendezvous", s.Rendezvous)
	switch {
	case s.Count.IsExpr():
		v.intOrExpr(p+".count", s.Count)
	case s.Count.N < 1 || !s.Count.IsWhole():
		v.errf(p+".count", "a rendezvous needs a count of at least 1")
	}
	v.rawTemplate(p+".value", s.Value)
	if s.As != "" && !ValidIdent(s.As) {
		v.errf(p+".as", "invalid variable name %q", s.As)
	}
	v.intOrExpr(p+".timeout_ms", s.TimeoutMS)
	if l := s.LatencyMS; l != nil && l.Expr != "" {
		v.expr(expr.Behavior, p+".latency_ms", strings.TrimSpace(l.Expr))
	} else if l != nil && (l.Min < 0 || l.Max < l.Min) {
		v.errf(p+".latency_ms", "latency_ms needs 0 <= min <= max")
	}
	if o := s.OnError; o != nil {
		switch {
		case o.Mode != "" && o.Mode != "propagate" && o.Mode != "continue":
			v.errf(p+".on_error", "on_error is propagate, continue or a list of steps")
		case o.Mode == "":
			v.steps(f, p+".on_error", o.Steps, depth+1, choices)
		}
	}
}

// channel checks a put or receive step (§13.1 item 18).
func (v *validator) channel(f *Interface, p, act string, s Step, depth int, choices map[string]bool) {
	if act == "put" {
		v.tokenName(p+".put", s.Put)
		v.rawTemplate(p+".value", s.Value)
		switch {
		case s.Capacity.IsExpr():
			v.intOrExpr(p+".capacity", s.Capacity)
		case !s.Capacity.IsZero() && (s.Capacity.N < 1 || !s.Capacity.IsWhole()):
			v.errf(p+".capacity", "a channel capacity is a whole number of at least 1")
		}
	} else {
		v.tokenName(p+".receive", s.Receive)
		if s.As != "" && !ValidIdent(s.As) {
			v.errf(p+".as", "invalid variable name %q", s.As)
		}
	}
	v.intOrExpr(p+".timeout_ms", s.TimeoutMS)
	if o := s.OnError; o != nil {
		switch {
		case o.Mode != "" && o.Mode != "propagate" && o.Mode != "continue":
			v.errf(p+".on_error", "on_error is propagate, continue or a list of steps")
		case o.Mode == "":
			v.steps(f, p+".on_error", o.Steps, depth+1, choices)
		}
	}
}

// transact checks a transact step (§13.1 item 25): one or more store
// writes, with as and on_error as for a call.
func (v *validator) transact(f *Interface, p string, s Step, depth int, choices map[string]bool) {
	if len(s.Transact) == 0 {
		v.errf(p+".transact", "transact needs at least one store write")
	}
	for i := range s.Transact {
		q := fmt.Sprintf("%s.transact[%d]", p, i)
		st := &s.Transact[i]
		if st.Op != "" && !contains(StoreWriteOps, st.Op) {
			v.errf(q+".op", "a transact write is one of %s", strings.Join(StoreWriteOps, ", "))
			continue
		}
		v.storeSpec(f, q, st)
	}
	if s.As != "" && !ValidIdent(s.As) {
		v.errf(p+".as", "invalid variable name %q", s.As)
	}
	if o := s.OnError; o != nil {
		switch {
		case o.Mode != "" && o.Mode != "propagate" && o.Mode != "continue":
			v.errf(p+".on_error", "on_error is propagate, continue or a list of steps")
		case o.Mode == "":
			v.steps(f, p+".on_error", o.Steps, depth+1, choices)
		}
	}
}

// kill checks a kill action (§13.1 item 18), as restart does.
func (v *validator) kill(p string, k *Kill, topo map[string][]string, env *expr.Env) {
	v.restart(p, &Restart{Component: k.Component, Instance: k.Instance}, topo, env)
}

package sim

import (
	"encoding/base64"
	"fmt"
	"math"
	"math/big"
	"strconv"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// DESIGN §15.3: simulator additions. Streams on route calls live in
// routes.go and exec.go; this file holds the rest.

// retryWaitUS is the wait in µs before the next attempt of a call: the
// backoff, jittered, or with retry.respect_retry_after the failure's
// headers['retry-after'] (seconds) or data.retry_after_ms, capped by
// max_backoff_ms. A failure that gives neither falls back to the backoff.
func (r *run) retryWaitUS(rs *model.RetrySpec, attempt int, e *Error) int64 {
	if rs.RespectRetryAfter {
		if ms, ok := retryAfterMS(e); ok {
			if rs.MaxBackoffMS > 0 && ms > float64(rs.MaxBackoffMS) {
				ms = float64(rs.MaxBackoffMS)
			}
			return r.msToUS(max(ms, 0))
		}
	}
	return r.jitter(rs, backoff(rs, attempt)) * 1000
}

// retryAfterMS reads a failure's retry-after header (delta seconds, maybe
// fractional) or its data.retry_after_ms, in ms.
func retryAfterMS(e *Error) (float64, bool) {
	if e == nil {
		return 0, false
	}
	for k, v := range e.Headers {
		if strings.EqualFold(k, "retry-after") {
			if s, ok := seconds(v); ok {
				return s * 1000, true
			}
		}
	}
	if d, ok := e.Data.(map[string]any); ok {
		if f, ok := toFloat(d["retry_after_ms"]); ok {
			return f, true
		}
		if s, ok := d["retry_after_ms"].(string); ok {
			if f, err := strconv.ParseFloat(strings.TrimSpace(s), 64); err == nil {
				return f, true
			}
		}
	}
	return 0, false
}

func seconds(v any) (float64, bool) {
	if f, ok := toFloat(v); ok {
		return f, true
	}
	if l, ok := v.([]any); ok && len(l) > 0 {
		return seconds(l[0])
	}
	s, ok := v.(string)
	if !ok {
		return 0, false
	}
	f, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
	if err != nil || math.IsNaN(f) || math.IsInf(f, 0) {
		return 0, false // an HTTP date isn't modeled; the backoff applies
	}
	return f, true
}

// faultPayload puts a fault's data and headers (§15.3) on the error it
// makes: unavailable, error, crash and a lost_reply with a code.
func faultPayload(ft *model.Fault, res *callResult) {
	if ft == nil || res.err == nil || (ft.Data == nil && ft.Headers == nil) {
		return
	}
	switch ft.Type {
	case "unavailable", "error", model.FaultCrash, model.FaultLostReply:
	default:
		return
	}
	e := *res.err
	if ft.Data != nil {
		e.Data = deepCopy(expr.Native(ft.Data))
	}
	if ft.Headers != nil {
		e.Headers = lowerHeaders(expr.Native(ft.Headers).(map[string]any))
	}
	res.err = &e
}

// updateRow merges a store update's value over its row (§15.3): a field
// set to {$absent: true}, at any depth, is removed from the row, and one
// set to {$null: true} becomes JSON null (§17 item 6). A literal null
// changes nothing (§13.1 item 24).
func updateRow(row, val any) any {
	return stripAbsent(deepMerge(row, markAbsent(val)))
}

func markAbsent(v any) any {
	switch t := v.(type) {
	case map[string]any:
		if b, ok := t["$absent"].(bool); ok && b && len(t) == 1 {
			return absentMark{}
		}
		if b, ok := t["$null"].(bool); ok && b && len(t) == 1 { // §17 item 6
			return nullMark{}
		}
		out := make(map[string]any, len(t))
		for k, x := range t {
			out[k] = markAbsent(x)
		}
		return out
	}
	return v
}

func stripAbsent(v any) any {
	switch t := v.(type) {
	case absentMark, nullMark:
		return nil
	case map[string]any:
		for k, x := range t {
			if _, ok := x.(absentMark); ok {
				delete(t, k)
			} else if _, ok := x.(nullMark); ok {
				t[k] = nil
			} else {
				t[k] = stripAbsent(x)
			}
		}
	}
	return v
}

// applyCaps reads a scenario's max_iterations and max_cel_cost (§15.3)
// into the plan.
func (pl *plan) applyCaps(sc *model.Scenario) {
	if sc.MaxIterations != nil {
		pl.maxIterations = int(max(1, min(*sc.MaxIterations, model.MaxMaxIterations)))
	}
	if sc.MaxForeach != nil {
		pl.maxForeach = int(max(1, min(*sc.MaxForeach, model.MaxMaxForeach))) // §17 item 18
	}
	if sc.MaxCELCost != nil && sc.CostLimit == nil {
		pl.costLimit = *sc.MaxCELCost
	}
}

// setStep runs a scenario step's set (§15.3): it changes component state
// at the step's time, as an outside actor would (a node coming back, a job
// placed by a scheduler), with a set event per path.
func (r *run) setStep(i int, st model.ScenarioStep) error {
	act := r.topAct(nil, r.stepsValue())
	for _, k := range sortedKeys(st.Set) {
		comp, inst := model.SplitStateKey(k)
		if _, ok := r.x.Components[comp]; !ok {
			return abortf("steps[%d].set: unknown component %q", i, comp)
		}
		if src, ok := expr.ExprOf(inst); ok {
			v, err := expr.Step.Eval(src, act)
			if err != nil {
				return abortf("steps[%d].set.%s: %v", i, k, err)
			}
			s, ok := v.(string)
			if !ok {
				return abortf("steps[%d].set.%s: must give an instance name, got %T", i, k, v)
			}
			inst = s
		}
		state := r.state(model.StateKey(comp, inst))
		paths := st.Set[k]
		for _, path := range sortedKeys(paths) {
			p := fmt.Sprintf("steps[%d].set.%s.%s", i, k, path)
			segs := strings.Split(path, ".")
			if containsStr(segs, "") {
				return abortf("%s: invalid state path %q", p, path)
			}
			v, err := expr.Step.Template(expr.Native(paths[path]), act)
			if err != nil {
				return abortf("%s: %v", p, err)
			}
			v = resolveInput(markInput(v))
			old := assign(state, segs, deepCopy(v))
			if err := r.ev(Event{Type: "set", Component: comp, Instance: inst, Scope: "state", Path: "state." + path,
				Old: deepCopy(old), New: deepCopy(v), Message: "scenario step set"}); err != nil {
				return err
			}
		}
	}
	return nil
}

// frameHeaders gives a streamed frame (a yield) its headers (§15.3): a
// frame that carries headers keeps them, with a lower-case alias for each
// key that isn't lower case, and the yield event gets them at lower-case
// keys.
func frameHeaders(v any) (any, map[string]any) {
	res := callResult{ok: true, value: v}
	h := responseHeaders(&res)
	return res.value, h
}

// collectedHeaders lifts a collected stream's return headers to the top
// of {items, value}, so result.value.headers reads them (§15.3).
func collectedHeaders(out map[string]any, value any) {
	if m, ok := value.(map[string]any); ok {
		if h, ok := m["headers"].(map[string]any); ok {
			out["headers"] = deepCopy(h)
		}
	}
}

// valueMark reads the §15.3 input markers: {"$bytes": "<base64>"} gives
// raw bytes (invalid UTF-8 included), and {"$bigint": "<decimal>"} an
// integer beyond int64, carried as its decimal string with an int marker
// (expr.BigInt). A marker whose text doesn't parse stays a plain map.
func valueMark(m map[string]any) (any, bool) {
	if s, ok := m["$bytes"].(string); ok {
		b, err := base64.StdEncoding.DecodeString(s)
		if err != nil {
			b, err = base64.RawStdEncoding.DecodeString(s)
		}
		if err == nil {
			return b, true
		}
	}
	if s, ok := m["$bigint"].(string); ok {
		if n, ok := new(big.Int).SetString(strings.TrimSpace(s), 10); ok {
			return expr.BigInt(n.String()), true
		}
	}
	return nil, false
}

package model

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
)

// Blocking waits (DESIGN §17 item 2). A behavior step's wait is either a
// duration (milliseconds or "=cel") or an object:
//
//	wait: {until: "<cel>", signal: <name or "=cel">, signals: [<name or "=cel">, ...],
//	       timeout_ms, on_timeout, as}
//
// The task blocks until the until condition holds or one of the named
// signals (signal and signals together) is delivered: a signal action; a
// kill of a component instance, which delivers
// "kill:<component>[@<instance>]"; or the exit of an instance (§17 item
// 14), which delivers "exit:<component>[@<instance>]" for every component
// of the killed or restarted group, carrying {component, instance, reason,
// at_us}. A wait on the exit of an instance that is already dead returns
// at once, as a wait on a process sentinel does. The condition is re-evaluated
// whenever the waiting instance's state, a channel or a cancellation token
// changes, or an instance is killed or restarted. Past timeout_ms (or the
// deadline) the wait times out: on_timeout "fail" (the default) fails the
// step with {code: timeout}, which on_error handles; "continue" goes on;
// a list of steps runs them. vars.<as> is {reason: until | signal |
// timeout, signal?, data?, waited_ms}: signal is the signal that woke the
// wait, data what it carried (an exit signal's payload).
type WaitSpec struct {
	Until     string          `json:"until,omitempty"`
	Signal    string          `json:"signal,omitempty"`
	Signals   []string        `json:"signals,omitempty"`
	TimeoutMS IntOrExpr       `json:"timeout_ms,omitzero"`
	OnTimeout json.RawMessage `json:"on_timeout,omitempty"`
	As        string          `json:"as,omitempty"`
}

// The on_timeout modes of a blocking wait.
const (
	WaitTimeoutFail     = "fail"
	WaitTimeoutContinue = "continue"
)

// UntilSource is the CEL source of until, without a leading "=".
func (w *WaitSpec) UntilSource() string {
	s := strings.TrimSpace(w.Until)
	if src, ok := expr.ExprOf(s); ok {
		return src
	}
	return s
}

// TimeoutMode returns on_timeout as a mode ("fail" or "continue") or a list
// of steps.
func (w *WaitSpec) TimeoutMode() (string, []Step, error) {
	if len(w.OnTimeout) == 0 {
		return WaitTimeoutFail, nil, nil
	}
	var mode string
	if err := json.Unmarshal(w.OnTimeout, &mode); err == nil {
		if mode != WaitTimeoutFail && mode != WaitTimeoutContinue {
			return "", nil, fmt.Errorf("on_timeout is \"fail\", \"continue\" or a list of steps, got %q", mode)
		}
		return mode, nil, nil
	}
	var steps []Step
	if err := Decode(w.OnTimeout, &steps); err != nil {
		return "", nil, fmt.Errorf("on_timeout is \"fail\", \"continue\" or a list of steps: %w", err)
	}
	return "", steps, nil
}

// BlockingWait returns a step's wait object, or nil when the wait is a
// duration (or absent).
func (s Step) BlockingWait() (*WaitSpec, error) {
	if s.Wait == nil {
		return nil, nil
	}
	m, ok := s.Wait.(map[string]any)
	if !ok {
		return nil, nil
	}
	b, err := json.Marshal(m)
	if err != nil {
		return nil, err
	}
	var w WaitSpec
	if err := Decode(b, &w); err != nil {
		return nil, err
	}
	return &w, nil
}

// waitSpec validates a blocking wait (§17 item 2).
func (v *validator) waitSpec(f *Interface, p string, s Step, depth int, choices map[string]bool) {
	w, err := s.BlockingWait()
	if err != nil {
		v.errf(p, "a blocking wait is {until, signal, signals, timeout_ms, on_timeout, as}: %v", err)
		return
	}
	if strings.TrimSpace(w.Until) == "" && strings.TrimSpace(w.Signal) == "" && len(w.Signals) == 0 {
		v.errf(p, "a blocking wait needs until, signal or both")
	}
	if w.Until != "" {
		v.expr(expr.Behavior, p+".until", w.UntilSource())
	}
	if w.Signal != "" {
		v.tokenName(p+".signal", w.Signal)
	}
	for i, n := range w.Signals {
		v.tokenName(fmt.Sprintf("%s.signals[%d]", p, i), n)
	}
	if w.TimeoutMS.IsExpr() {
		v.expr(expr.Behavior, p+".timeout_ms", w.TimeoutMS.Expr)
	} else if w.TimeoutMS.N < 0 || w.TimeoutMS.Micro < 0 {
		v.errf(p+".timeout_ms", "timeout_ms must not be negative")
	}
	if w.As != "" && !ValidIdent(w.As) {
		v.errf(p+".as", "invalid variable name %q", w.As)
	}
	_, steps, err := w.TimeoutMode()
	if err != nil {
		v.errf(p+".on_timeout", "%v", err)
	} else if steps != nil {
		v.steps(f, p+".on_timeout", steps, depth+1, choices)
	}
}

// UsesBlockingWaits reports whether any behavior step of the document is a
// blocking wait or a signal action (§17 item 2); either opts a run into
// concurrency, as a receive does.
func UsesBlockingWaits(doc *Document) bool {
	var walk func([]Step) bool
	walk = func(steps []Step) bool {
		for i := range steps {
			s := &steps[i]
			if s.Signal != "" {
				return true
			}
			if _, ok := s.Wait.(map[string]any); ok {
				return true
			}
			if walk(s.Then) || walk(s.Else) || walk(s.Steps) || walk(s.OnLate) || walk(s.OnItem) {
				return true
			}
			if s.OnError != nil && walk(s.OnError.Steps) {
				return true
			}
			for _, b := range s.Branches {
				if walk(b) {
					return true
				}
			}
			for _, o := range s.Options {
				if walk(o) {
					return true
				}
			}
		}
		return false
	}
	for i := range doc.Interfaces {
		if walk(doc.Interfaces[i].Behavior) {
			return true
		}
	}
	return false
}

package sim

import (
	"fmt"

	"github.com/xleelz/mosaic/internal/model"
)

// transact runs a transact step (§13.1 item 25): its store writes are
// evaluated in order against a staged copy of the running instance's
// tables, so a later write sees the earlier ones. If every write passes,
// all are committed (one set event each); if any fails its condition or
// misses its row, nothing is applied and the step fails like a call, with
// the failed write's code and data {index, table, key, row}.
func (r *run) transact(f *frame, s model.Step, depth int, p string) (*exit, error) {
	state := r.state(f.skey)
	staged := map[string]map[string]any{}
	lookup := func(name string) (map[string]any, error) {
		if t, ok := staged[name]; ok {
			return t, nil
		}
		t := map[string]any{}
		switch cur := state[name].(type) {
		case nil:
		case map[string]any:
			for k, v := range cur {
				t[k] = v
			}
		default:
			return nil, abortf("%s.transact: state.%s is a %T, not a table of rows", p, name, cur)
		}
		staged[name] = t
		return t, nil
	}
	var changes []storeChange
	values := []any{}
	var fail *Error
	for i := range s.Transact {
		st := &s.Transact[i]
		q := fmt.Sprintf("%s.transact[%d]", p, i)
		v, ch, e, err := r.storeOp(f, st, q, lookup)
		if err != nil {
			return nil, err
		}
		if e != nil {
			data, _ := e.Data.(map[string]any)
			if data == nil {
				data = map[string]any{"table": st.Table}
			}
			data["index"] = int64(i)
			e.Data = data
			e.Message = fmt.Sprintf("transaction canceled: write %d: %s", i, e.Message)
			fail = e
			break
		}
		if ch != nil {
			t := staged[ch.table]
			if ch.del {
				delete(t, ch.key)
			} else {
				t[ch.key] = deepCopy(ch.next)
			}
			changes = append(changes, *ch)
		}
		values = append(values, v)
	}
	out := map[string]any{"ok": fail == nil, "value": nil, "error": nil}
	if fail == nil {
		if err := r.commitStore(f, changes); err != nil {
			return nil, err
		}
		out["value"] = values
	} else {
		out["error"] = fail.Map()
		f.lastErr = fail.Map()
	}
	if s.As != "" {
		f.vars[s.As] = deepCopy(out)
	}
	if fail == nil {
		return nil, nil
	}
	return r.onError(f, s.OnError, fail, depth, p, false)
}

// crashState is a crash fault (§13.1 item 25) on one invocation: the
// callee runs left more steps, then stops; the caller gets err whether or
// not the behavior reached that step.
type crashState struct {
	left    int
	crashed bool
	err     *Error
}

func newCrash(ft *model.Fault, target string) *crashState {
	e := &Error{Code: "crashed", Status: 500, Retryable: true, Message: ft.Message}
	if ft.Code != "" {
		e.Code = ft.Code
	}
	if ft.Status != 0 {
		e.Status = ft.Status
	}
	if ft.Retryable != nil {
		e.Retryable = *ft.Retryable
	}
	if e.Message == "" {
		e.Message = fmt.Sprintf("%s crashed after %d steps", target, *ft.AfterSteps)
	}
	return &crashState{left: *ft.AfterSteps, err: e}
}

// step reports whether the callee may run one more step, counting it.
func (c *crashState) step() bool {
	if c.crashed || c.left <= 0 {
		c.crashed = true
		return false
	}
	c.left--
	return true
}

// lostReplyError is the error a lost_reply fault with a code returns at the
// callee's end; without a code, the caller waits for its timeout instead.
func lostReplyError(ft *model.Fault, target string) *Error {
	e := &Error{Code: ft.Code, Status: ft.Status, Retryable: true, Message: ft.Message}
	if ft.Retryable != nil {
		e.Retryable = *ft.Retryable
	}
	if e.Message == "" {
		e.Message = target + " completed but its reply was lost"
	}
	return e
}

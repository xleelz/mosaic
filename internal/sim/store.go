package sim

import (
	"fmt"
	"math"
	"strconv"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// store performs an interface's declarative store operation on its
// component instance's state (§11.1: stores keep their tables per
// instance). Rows live in state.<table>, a map keyed by string id, so a
// value written by one call can be read back by a later one in the same run.
func (r *run) store(fr *frame) (callResult, error) {
	f := fr.iface
	if fr.crash != nil && !fr.crash.step() {
		// A crash fault before the operation (§13.1 item 25): nothing applied.
		return callResult{}, nil
	}
	state := r.state(fr.skey)
	tables := func(name string) (map[string]any, error) {
		switch t := state[name].(type) {
		case nil:
			return nil, nil
		case map[string]any:
			return t, nil
		default:
			return nil, abortf("%s.store: state.%s is a %T, not a table of rows", f.ID, name, t)
		}
	}
	value, ch, fail, err := r.storeOp(fr, f.Store, f.ID+".store", tables)
	if err != nil || fail != nil {
		return callResult{err: fail}, err
	}
	if ch != nil {
		if err := r.commitStore(fr, []storeChange{*ch}); err != nil {
			return callResult{}, err
		}
	}
	return callResult{ok: true, value: value}, nil
}

// storeChange is a row write that an operation decided on, applied by
// commitStore.
type storeChange struct {
	table, key string
	old, next  any
	del        bool
}

// storeOp evaluates one store operation against the tables that lookup
// returns, without changing them: it returns the operation's value, the row
// change a write makes, or the declared failure when a condition fails or a
// row is missing. Conditions see row (null when absent) and key.
func (r *run) storeOp(fr *frame, st *model.StoreSpec, p string, lookup func(string) (map[string]any, error)) (any, *storeChange, *Error, error) {
	f := fr.iface
	table, err := lookup(st.Table)
	if err != nil {
		return nil, nil, nil, err
	}
	cond := func(what, src, key string, row any) (bool, error) {
		act := r.act(fr, 1)
		act["row"], act["key"] = row, key
		ok, err := expr.Store.EvalBool(src, act)
		if err != nil {
			return false, abortf("%s.%s: %v", p, what, err)
		}
		return ok, nil
	}
	where := func(key string, row any) (bool, error) {
		if st.Where == "" {
			return true, nil
		}
		return cond("where", st.Where, key, row)
	}

	if st.Op == "query" {
		r.xpStoreRead(fr, st.Table, "*") // §16.2 read footprint (schedreads.go)
		rows := []any{}
		for _, k := range sortedKeys(table) {
			ok, err := where(k, table[k])
			if err != nil {
				return nil, nil, nil, err
			}
			if ok {
				rows = append(rows, deepCopy(table[k]))
			}
		}
		return rows, nil, nil, nil
	}

	kv, err := expr.Behavior.Template(expr.Native(st.Key), r.act(fr, 1))
	if err != nil {
		return nil, nil, nil, abortf("%s.key: %v", p, err)
	}
	var key string
	switch t := kv.(type) {
	case string:
		key = t
	case int64:
		key = strconv.FormatInt(t, 10)
	case uint64: // beyond int64 (behavior-language §30)
		key = strconv.FormatUint(t, 10)
	case float64:
		if t == math.Trunc(t) && math.Abs(t) < 1<<53 {
			key = strconv.FormatInt(int64(t), 10)
		}
	}
	if key == "" {
		return nil, nil, nil, abortf("%s.key: needs a non-empty string or a whole number, got %#v", p, kv)
	}
	r.xpStoreRead(fr, st.Table, key)
	row, exists := table[key]
	notFound := r.storeError(f, st.NotFound, "not_found", 404, fmt.Sprintf("%s %q not found", st.Table, key))

	if st.Op == "get" {
		if exists {
			ok, err := where(key, row)
			if err != nil {
				return nil, nil, nil, err
			}
			if ok {
				return deepCopy(row), nil, nil, nil
			}
		}
		if st.Default == nil {
			return nil, nil, notFound, nil
		}
		v, err := expr.Behavior.Template(expr.Native(st.Default), r.act(fr, 1))
		if err != nil {
			return nil, nil, nil, abortf("%s.default: %v", p, err)
		}
		return v, nil, nil, nil
	}

	// Writes. update needs an existing row; the others see null when absent.
	if st.Op == "update" && !exists {
		return nil, nil, notFound, nil
	}
	if ok, err := where(key, row); err != nil {
		return nil, nil, nil, err
	} else if !ok {
		return nil, nil, r.storeError(f, st.Conflict, "conflict", 409, fmt.Sprintf("%s %q failed its condition", st.Table, key)), nil
	}
	// Conditional writes (§13.1 item 25).
	failed := st.IfAbsent && exists
	if !failed && st.If != "" {
		ok, err := cond("if", st.If, key, row)
		if err != nil {
			return nil, nil, nil, err
		}
		failed = !ok
	}
	if failed {
		e := r.storeError(f, st.Conflict, "condition_failed", 412, fmt.Sprintf("%s %q failed its write condition", st.Table, key))
		e.Data = map[string]any{"table": st.Table, "key": key, "row": deepCopy(row)}
		return nil, nil, e, nil
	}
	var val any
	if st.Value != nil {
		if val, err = expr.Behavior.Template(expr.Native(st.Value), r.act(fr, 1)); err != nil {
			return nil, nil, nil, abortf("%s.value: %v", p, err)
		}
	}
	var next any
	switch st.Op {
	case "put":
		next = val
	case "update":
		next = updateRow(row, val) // {$absent: true} removes a field (§15.3)
	case "incr":
		if next, err = increment(row, val); err != nil {
			return nil, nil, nil, abortf("%s.value: %v", p, err)
		}
	}
	ch := &storeChange{table: st.Table, key: key, old: deepCopy(row), next: deepCopy(next), del: st.Op == "delete"}
	if ch.del {
		return deepCopy(row), ch, nil, nil
	}
	return deepCopy(next), ch, nil, nil
}

// commitStore applies row changes to the frame's instance state in order,
// with a set event for each.
func (r *run) commitStore(fr *frame, changes []storeChange) error {
	state := r.state(fr.skey)
	for _, ch := range changes {
		table, _ := state[ch.table].(map[string]any)
		if table == nil {
			table = map[string]any{}
			state[ch.table] = table
		}
		if ch.del {
			delete(table, ch.key)
		} else {
			table[ch.key] = deepCopy(ch.next)
		}
		if err := r.ev(Event{Type: "set", Span: fr.span, Component: fr.iface.Component, Interface: fr.iface.ID, Scope: "state",
			Path: "state." + ch.table + "." + ch.key, Old: ch.old, New: deepCopy(ch.next), Instance: fr.inst, Table: ch.table, Key: ch.key}); err != nil {
			return err
		}
	}
	return nil
}

// storeError builds a store failure from a declared error: the named code, or
// else a declared error with the fallback code, or else a plain error.
func (r *run) storeError(f *model.Interface, code, fallback string, status int, msg string) *Error {
	want := code
	if want == "" {
		want = fallback
	}
	for _, e := range f.Errors {
		if e.Code == want {
			return &Error{Code: e.Code, Status: e.Status, Retryable: e.Retryable, Message: msg}
		}
	}
	return &Error{Code: want, Status: status, Message: msg}
}

// increment adds deltas to a row: a number to a numeric row, or a map of
// numbers field by field. Absent rows and fields count as 0.
func increment(row, delta any) (any, error) {
	if dm, ok := delta.(map[string]any); ok {
		out := map[string]any{}
		switch t := row.(type) {
		case nil:
		case map[string]any:
			out = deepCopy(t).(map[string]any)
		default:
			return nil, fmt.Errorf("cannot add a map of deltas to a %T row", row)
		}
		for _, k := range sortedKeys(dm) {
			n, err := addNumbers(out[k], dm[k])
			if err != nil {
				return nil, fmt.Errorf("field %s: %v", k, err)
			}
			out[k] = n
		}
		return out, nil
	}
	return addNumbers(row, delta)
}

func addNumbers(a, b any) (any, error) {
	if a == nil {
		a = int64(0)
	}
	ai, aInt := a.(int64)
	bi, bInt := b.(int64)
	if aInt && bInt {
		return ai + bi, nil
	}
	af, ok1 := toFloat(a)
	bf, ok2 := toFloat(b)
	if !ok1 || !ok2 {
		return nil, fmt.Errorf("cannot add %T to %T", b, a)
	}
	return af + bf, nil
}

func toFloat(v any) (float64, bool) {
	switch t := v.(type) {
	case int64:
		return float64(t), true
	case uint64:
		return float64(t), true
	case float64:
		return t, true
	}
	return 0, false
}

package sim

import (
	"encoding/json"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Absent inputs and explicit nulls (§13.1 item 24). In a scenario's, a
// step's, a request's or a flow entry's input, {"$absent": true} removes
// the key from the input, faked value and all, and {"$null": true} sets a
// real JSON null. A literal null keeps its old meaning (no override: the
// faked value when the schema declares the key, else null), which models
// already rely on. Templates are marked when decoded, so the markers
// survive merging (a later layer's $absent removes an earlier layer's
// value) and evaluation, and are resolved last.

// absentMark is {"$absent": true} in an input template: the key is removed.
type absentMark struct{}

func (absentMark) MarshalJSON() ([]byte, error) { return []byte(`{"$absent":true}`), nil }

// nullMark is {"$null": true} in an input template: a real null.
type nullMark struct{}

func (nullMark) MarshalJSON() ([]byte, error) { return []byte(`{"$null":true}`), nil }

// inputTemplate decodes an input template and marks its absent keys and
// explicit nulls.
func inputTemplate(raw json.RawMessage) (any, error) {
	t, err := expr.DecodeTemplate(raw)
	if err != nil {
		return nil, err
	}
	return markInput(t), nil
}

func markInput(v any) any {
	switch t := v.(type) {
	case map[string]any:
		if len(t) == 1 {
			if b, ok := t["$null"].(bool); ok && b {
				return nullMark{}
			}
			if b, ok := t["$absent"].(bool); ok && b {
				return absentMark{}
			}
			if v, ok := valueMark(t); ok { // {$bytes} and {$bigint} (§15.3)
				return v
			}
		}
		out := make(map[string]any, len(t))
		for k, x := range t {
			out[k] = markInput(x)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			out[i] = markInput(x)
		}
		return out
	}
	return v
}

// resolveInput removes absent keys and turns explicit nulls into nil in an
// evaluated input.
func resolveInput(v any) any {
	switch t := v.(type) {
	case absentMark, nullMark:
		return nil
	case map[string]any:
		for k, x := range t {
			if _, ok := x.(absentMark); ok {
				delete(t, k)
			} else {
				t[k] = resolveInput(x)
			}
		}
		return t
	case []any:
		for i, x := range t {
			t[i] = resolveInput(x)
		}
		return t
	}
	return v
}

// choiceSet is the choices a task sees (§13.1 item 24). Each choice point
// counts its own evaluations, from 1, so a list or call-keyed choice picks
// per call; a step that overrides a choice starts its own count, and the
// choices it inherits keep counting across the run.
type choiceSet map[string]*choiceSlot

type choiceSlot struct {
	c model.Choice
	n int
}

func newChoiceSet(m map[string]model.Choice) choiceSet {
	s := make(choiceSet, len(m))
	for k, c := range m {
		s[k] = &choiceSlot{c: c}
	}
	return s
}

// with is the set with over's choices in place of its own.
func (s choiceSet) with(over map[string]model.Choice) choiceSet {
	out := make(choiceSet, len(s)+len(over))
	for k, sl := range s {
		out[k] = sl
	}
	for k, c := range over {
		out[k] = &choiceSlot{c: c}
	}
	return out
}

// next counts an evaluation of the choice point key and returns the
// option set for it, if any.
func (s choiceSet) next(key string) (string, bool) {
	sl, ok := s[key]
	if !ok {
		return "", false
	}
	sl.n++
	return sl.c.At(sl.n)
}

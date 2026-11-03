package model

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
)

// Choice is a scenario's or request's pick for one choice point (§13.1
// item 24). In JSON it is one of:
//
//   - "opt": every evaluation of the choice point takes opt (the original
//     scalar form);
//   - ["a", "b", "c"]: the n-th evaluation in the run takes the n-th
//     option, and the last repeats once the list runs out;
//   - {"2": "b", "5": "c"}: the listed evaluations (1-based) take the
//     given options and the others fall back to the behavior's default.
//
// Exactly one of Option, Seq and Calls is set.
type Choice struct {
	Option string
	Seq    []string
	Calls  map[int]string
}

// ChoiceOf is the scalar form of a choice.
func ChoiceOf(option string) Choice { return Choice{Option: option} }

// ScalarChoices turns option names into scalar choices.
func ScalarChoices(m map[string]string) map[string]Choice {
	if m == nil {
		return nil
	}
	out := make(map[string]Choice, len(m))
	for k, v := range m {
		out[k] = ChoiceOf(v)
	}
	return out
}

// IsScalar reports whether the choice is the scalar form.
func (c Choice) IsScalar() bool { return c.Seq == nil && c.Calls == nil }

// At is the option for the n-th (1-based) evaluation of the choice point,
// and whether the choice sets one for it.
func (c Choice) At(n int) (string, bool) {
	switch {
	case c.Seq != nil:
		if len(c.Seq) == 0 {
			return "", false
		}
		return c.Seq[min(max(n, 1), len(c.Seq))-1], true
	case c.Calls != nil:
		o, ok := c.Calls[n]
		return o, ok
	}
	return c.Option, true
}

// Options lists the options the choice names, in order, for validation.
func (c Choice) Options() []string {
	switch {
	case c.Seq != nil:
		return c.Seq
	case c.Calls != nil:
		keys := make([]int, 0, len(c.Calls))
		for k := range c.Calls {
			keys = append(keys, k)
		}
		sort.Ints(keys)
		out := make([]string, len(keys))
		for i, k := range keys {
			out[i] = c.Calls[k]
		}
		return out
	}
	return []string{c.Option}
}

// String is the scalar option, or the JSON of the list or map form.
func (c Choice) String() string {
	if c.IsScalar() {
		return c.Option
	}
	b, _ := json.Marshal(c)
	return string(b)
}

func (c Choice) MarshalJSON() ([]byte, error) {
	switch {
	case c.Seq != nil:
		return json.Marshal(c.Seq)
	case c.Calls != nil:
		m := make(map[string]string, len(c.Calls))
		for k, v := range c.Calls {
			m[strconv.Itoa(k)] = v
		}
		return json.Marshal(m)
	}
	return json.Marshal(c.Option)
}

func (c *Choice) UnmarshalJSON(b []byte) error {
	*c = Choice{}
	switch b = bytes.TrimSpace(b); {
	case len(b) > 0 && b[0] == '[':
		var seq []string
		if err := json.Unmarshal(b, &seq); err != nil {
			return fmt.Errorf("a choice list holds option names: %v", err)
		}
		if len(seq) == 0 {
			return fmt.Errorf("a choice list names at least one option")
		}
		c.Seq = seq
	case len(b) > 0 && b[0] == '{':
		var m map[string]string
		if err := json.Unmarshal(b, &m); err != nil {
			return fmt.Errorf("a choice map holds option names by call: %v", err)
		}
		c.Calls = make(map[int]string, len(m))
		for k, v := range m {
			n, err := strconv.Atoi(k)
			if err != nil || n < 1 {
				return fmt.Errorf("choice map key %q is not a call number (1, 2, ...)", k)
			}
			c.Calls[n] = v
		}
	default:
		return json.Unmarshal(b, &c.Option)
	}
	return nil
}

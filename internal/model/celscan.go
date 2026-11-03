package model

import (
	"encoding/json"
	"regexp"
	"strconv"
	"strings"
)

// These scanners read CEL source as text, with string literals set aside,
// so they stay independent of the CEL parser. They back warnings and reach,
// not evaluation.

var (
	configDotRE    = regexp.MustCompile(`(?:^|[^A-Za-z0-9_.])config\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)`)
	configOpenRE   = regexp.MustCompile(`(?:^|[^A-Za-z0-9_.])config\s*\[\s*$`)
	closeBracketRE = regexp.MustCompile(`^\s*\]`)
	nowRE          = regexp.MustCompile(`(?:^|[^A-Za-z0-9_.])now(?:[^A-Za-z0-9_]|$)`)
	bigIntRE       = regexp.MustCompile(`(?:^|[^A-Za-z0-9_.])([0-9]{13,})(?:[^0-9A-Za-z_.]|u|$)`)
	clauseSepRE    = regexp.MustCompile(`&&|\|\||[?:,;]`)
	comparisonRE   = regexp.MustCompile(`<=|>=|==|!=|<|>`)
)

// celLiteral is a string literal of a CEL expression: its text and where
// its empty placeholder ("") sits in the code returned by splitLiterals.
type celLiteral struct {
	text string
	at   int
}

// splitLiterals returns src with every string literal replaced by "", and
// the literals. It handles single, double and triple quotes and backslash
// escapes; it is lenient with unterminated literals.
func splitLiterals(src string) (string, []celLiteral) {
	var code strings.Builder
	var lits []celLiteral
	for i := 0; i < len(src); {
		c := src[i]
		if c != '"' && c != '\'' {
			code.WriteByte(c)
			i++
			continue
		}
		q := string(c)
		if strings.HasPrefix(src[i:], q+q+q) {
			q = q + q + q
		}
		j := i + len(q)
		var text strings.Builder
		for j < len(src) && !strings.HasPrefix(src[j:], q) {
			if src[j] == '\\' && j+1 < len(src) {
				text.WriteByte(src[j+1])
				j += 2
				continue
			}
			text.WriteByte(src[j])
			j++
		}
		lits = append(lits, celLiteral{text: text.String(), at: code.Len()})
		code.WriteString(`""`)
		i = j + len(q)
	}
	return code.String(), lits
}

// ConfigRefs returns the config ids a CEL expression references as
// config.<id> or config["<id>"], in order of appearance, without duplicates.
// Ids containing '-' can only be referenced with the index form.
func ConfigRefs(src string) []string {
	var out []string
	seen := map[string]bool{}
	add := func(id string) {
		if id != "" && !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	code, lits := splitLiterals(src)
	for _, m := range configDotRE.FindAllStringSubmatch(code, -1) {
		add(m[1])
	}
	for _, l := range lits {
		if configOpenRE.MatchString(code[:l.at]) && closeBracketRE.MatchString(code[l.at+2:]) {
			add(l.text)
		}
	}
	return out
}

// epochLiteralLimit is 10^12 ms (2001-09-09): an integer literal above it in
// an expression that reads `now` is almost certainly a wall-clock time.
const epochLiteralLimit = 1_000_000_000_000

// WallClockLiteral reports whether a CEL expression compares `now` with an
// integer literal over 10^12 (§11.3): a timestamp invented by the model
// instead of derived from now. It returns the first such literal.
//
// The check is textual. The expression is cut into clauses at &&, ||, ?, :,
// ',' and ';', and each clause into operands at comparison operators; it
// fires when `now` and such a literal are on the two sides of one
// comparison, or together in one operand of a comparison, as in
// `now > 1730000000000`, `(now - x) < 1730000000000` or
// `now - 1730000000000 > 0`.
// Following §11.3 literally ("compared with now"), arithmetic such as
// `1730000000000000 + now * 1000` does not fire.
func WallClockLiteral(src string) (string, bool) {
	code, _ := splitLiterals(src)
	if !nowRE.MatchString(code) {
		return "", false
	}
	for _, clause := range clauseSepRE.Split(code, -1) {
		ops := comparisonRE.Split(clause, -1)
		if len(ops) > 1 {
			for _, op := range ops { // now - 1730000000000 > 0
				if lit, ok := bigLiteral(op); ok && nowRE.MatchString(op) {
					return lit, true
				}
			}
		}
		for i := 0; i+1 < len(ops); i++ {
			a, b := ops[i], ops[i+1]
			if lit, ok := bigLiteral(b); ok && nowRE.MatchString(a) {
				return lit, true
			}
			if lit, ok := bigLiteral(a); ok && nowRE.MatchString(b) {
				return lit, true
			}
		}
	}
	return "", false
}

// bigLiteral returns the first integer literal over 10^12 in code.
func bigLiteral(code string) (string, bool) {
	for _, m := range bigIntRE.FindAllStringSubmatch(code, -1) {
		n, err := strconv.ParseUint(m[1], 10, 64)
		if err != nil || n > epochLiteralLimit { // a parse error here is an overflow: larger still
			return m[1], true
		}
	}
	return "", false
}

// celKeys are the fields whose string value is always CEL, without "=".
var celKeys = map[string]bool{"when": true, "if": true, "where": true}

// celStrings calls fn with the CEL source of every expression in an encoded
// value: strings under celKeys, and any other string starting with "=".
func celStrings(v any, key string, fn func(string)) {
	switch t := v.(type) {
	case string:
		if celKeys[key] {
			fn(t)
		} else if src, ok := strings.CutPrefix(t, "="); ok {
			fn(src)
		}
	case map[string]any:
		for _, k := range sortedKeys(t) {
			celStrings(t[k], k, fn)
		}
	case []any:
		for _, x := range t {
			celStrings(x, key, fn)
		}
	}
}

// interfaceConfigRefs returns the sorted config ids an interface's CEL
// references: its behavior, store, latency and streams_when expressions.
func interfaceConfigRefs(f *Interface) []string {
	b, err := json.Marshal(struct {
		Behavior  []Step           `json:"behavior,omitempty"`
		Store     *StoreSpec       `json:"store,omitempty"`
		LatencyMS *Latency         `json:"latency_ms,omitempty"`
		ByOutcome []OutcomeLatency `json:"latency_by_outcome,omitempty"`
		Streams   string           `json:"streams_when,omitempty"`
	}{f.Behavior, f.Store, f.LatencyMS, f.LatencyByOutcome, f.StreamsWhen})
	if err != nil {
		return nil
	}
	var v any
	if json.Unmarshal(b, &v) != nil {
		return nil
	}
	refs := map[string]bool{}
	celStrings(v, "", func(src string) {
		for _, id := range ConfigRefs(src) {
			refs[id] = true
		}
	})
	if len(refs) == 0 {
		return nil
	}
	return sortedKeys(refs)
}

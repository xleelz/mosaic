package expr

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"strconv"
	"strings"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/common/types/ref"
)

// The §15.3 CEL helpers: json(x) encodes canonically (sorted keys, no
// spaces), jsonParse(s) decodes, and hex(b) gives the lower-case hex of
// bytes or of a string's UTF-8 bytes. bytes(s) is CEL's own conversion.
// All are pure, so the eval sandbox gets them too.
func jsonHelpers() []cel.EnvOption {
	str, byt, dyn := cel.StringType, cel.BytesType, cel.DynType
	return []cel.EnvOption{
		cel.Function("json",
			cel.Overload("json_dyn", []*cel.Type{dyn}, str, cel.UnaryBinding(jsonImpl))),
		cel.Function("jsonParse",
			cel.Overload("jsonParse_string", []*cel.Type{str}, dyn, cel.UnaryBinding(jsonParseImpl)),
			cel.Overload("jsonParse_bytes", []*cel.Type{byt}, dyn, cel.UnaryBinding(jsonParseImpl))),
		cel.Function("hex",
			cel.Overload("hex_bytes", []*cel.Type{byt}, str, cel.UnaryBinding(hexImpl)),
			cel.Overload("hex_string", []*cel.Type{str}, str, cel.UnaryBinding(hexImpl))),
	}
}

func init() {
	// Their run-time cost grows with the string or bytes they read.
	for _, f := range []string{"jsonParse", "hex"} {
		sizedFuncs[f] = true
	}
}

// Canonical encodes v as canonical JSON: map keys sorted, no spaces, and
// no HTML escaping.
func Canonical(v any) (string, error) {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return "", err
	}
	return strings.TrimSuffix(b.String(), "\n"), nil
}

func jsonImpl(v ref.Val) ref.Val {
	s, err := Canonical(ToNative(v))
	if err != nil {
		return types.NewErr("json: %v", err)
	}
	return types.String(s)
}

func jsonParseImpl(v ref.Val) ref.Val {
	b, ok := rawBytes(v)
	if !ok {
		return types.NewErr("jsonParse needs a string")
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var out any
	if err := dec.Decode(&out); err != nil {
		return types.NewErr("jsonParse: %v", err)
	}
	if dec.More() {
		return types.NewErr("jsonParse: trailing data after the JSON value")
	}
	return adapter.NativeToValue(Native(out))
}

func hexImpl(v ref.Val) ref.Val {
	b, ok := rawBytes(v)
	if !ok {
		return types.NewErr("hex needs bytes or a string")
	}
	return types.String(hex.EncodeToString(b))
}

// BigInt is an integer beyond int64 (§15.3), from the input marker
// {"$bigint": "<decimal>"}. Expressions see its decimal string; schema
// checks count it as an integer; JSON writes the marker back, so it
// survives a round trip.
type BigInt string

func (b BigInt) MarshalJSON() ([]byte, error) {
	return json.Marshal(map[string]string{"$bigint": string(b)})
}

// LossyInts lists the whole-number literals in raw JSON that fit neither
// int64 nor uint64 (behavior-language §30): Native turns them into
// doubles, which lose digits. Raw that doesn't decode gives nil.
func LossyInts(raw []byte) []string {
	if !hasLongDigits(raw) {
		return nil
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if dec.Decode(&v) != nil {
		return nil
	}
	var out []string
	WalkLossyInts(v, "", func(path, lit string) { out = append(out, path+"="+lit) })
	return out
}

// hasLongDigits reports whether raw holds a run of 19 or more digits, the
// shortest text an integer beyond int64 can have.
func hasLongDigits(raw []byte) bool {
	run := 0
	for _, c := range raw {
		if c >= '0' && c <= '9' {
			run++
			if run >= 19 {
				return true
			}
		} else {
			run = 0
		}
	}
	return false
}

// WalkLossyInts calls f with the path and text of every json.Number in v
// that is a whole-number literal beyond both int64 and uint64. Paths are
// dotted; list items are [i], or [<id>] for a map with a string id.
func WalkLossyInts(v any, path string, f func(path, lit string)) {
	switch t := v.(type) {
	case json.Number:
		s := string(t)
		if strings.ContainsAny(s, ".eE") {
			return
		}
		if _, err := strconv.ParseInt(s, 10, 64); err == nil {
			return
		}
		if _, err := strconv.ParseUint(s, 10, 64); err == nil {
			return
		}
		f(path, s)
	case map[string]any:
		for k, x := range t {
			p := k
			if path != "" {
				p = path + "." + k
			}
			WalkLossyInts(x, p, f)
		}
	case []any:
		for i, x := range t {
			idx := strconv.Itoa(i)
			if m, ok := x.(map[string]any); ok {
				if id, ok := m["id"].(string); ok && id != "" {
					idx = id
				}
			}
			WalkLossyInts(x, path+"["+idx+"]", f)
		}
	}
}

// SchemaView prepares a native value for a JSON Schema check: a uint64
// (a whole number beyond int64, behavior-language §30) is an integer, so
// it is passed as a BigInt. Values without one are returned as they are.
func SchemaView(v any) any {
	if !hasUint(v) {
		return v
	}
	return toSchemaView(v)
}

func hasUint(v any) bool {
	switch t := v.(type) {
	case uint64:
		return true
	case map[string]any:
		for _, x := range t {
			if hasUint(x) {
				return true
			}
		}
	case []any:
		for _, x := range t {
			if hasUint(x) {
				return true
			}
		}
	}
	return false
}

func toSchemaView(v any) any {
	switch t := v.(type) {
	case uint64:
		return BigInt(strconv.FormatUint(t, 10))
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, x := range t {
			out[k] = toSchemaView(x)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			out[i] = toSchemaView(x)
		}
		return out
	}
	return v
}

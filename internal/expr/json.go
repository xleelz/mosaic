package expr

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
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

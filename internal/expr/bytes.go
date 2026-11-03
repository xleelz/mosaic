package expr

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"hash/fnv"
	"math"
	"strconv"
	"unicode/utf8"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/common/types/ref"
)

// byteHelpers declares the §13.1 item 23 helpers: hashing, HMAC, byte
// lengths and slices, base64 on strings, FNV-1a and logarithms. All are
// pure and deterministic, so the eval sandbox gets them too.
func byteHelpers() []cel.EnvOption {
	str, byt, dbl, in := cel.StringType, cel.BytesType, cel.DoubleType, cel.IntType
	return []cel.EnvOption{
		cel.Function("sha256",
			cel.Overload("sha256_string", []*cel.Type{str}, str, cel.UnaryBinding(sha256Impl))),
		cel.Function("sha256Bytes",
			cel.Overload("sha256Bytes_bytes", []*cel.Type{byt}, str, cel.UnaryBinding(sha256Impl)),
			cel.Overload("sha256Bytes_string", []*cel.Type{str}, str, cel.UnaryBinding(sha256Impl))),
		cel.Function("hmacSha256",
			cel.Overload("hmacSha256_string_string", []*cel.Type{str, str}, str, cel.BinaryBinding(hmacHex)),
			cel.Overload("hmacSha256_bytes_string", []*cel.Type{byt, str}, str, cel.BinaryBinding(hmacHex))),
		cel.Function("hmacSha256Base64",
			cel.Overload("hmacSha256Base64_string_string", []*cel.Type{str, str}, str, cel.BinaryBinding(hmacB64)),
			cel.Overload("hmacSha256Base64_bytes_string", []*cel.Type{byt, str}, str, cel.BinaryBinding(hmacB64))),
		cel.Function("byteLen",
			cel.Overload("byteLen_string", []*cel.Type{str}, in, cel.UnaryBinding(byteLenImpl)),
			cel.Overload("byteLen_bytes", []*cel.Type{byt}, in, cel.UnaryBinding(byteLenImpl))),
		cel.Function("substrBytes",
			cel.Overload("substrBytes_string_int_int", []*cel.Type{str, in, in}, str, cel.FunctionBinding(substrBytesImpl))),
		cel.Function("base64Encode",
			cel.Overload("base64Encode_string", []*cel.Type{str}, str, cel.UnaryBinding(base64EncodeImpl)),
			cel.Overload("base64Encode_bytes", []*cel.Type{byt}, str, cel.UnaryBinding(base64EncodeImpl))),
		cel.Function("base64Decode",
			cel.Overload("base64Decode_string", []*cel.Type{str}, str, cel.UnaryBinding(base64DecodeImpl))),
		cel.Function("fnv64a",
			cel.Overload("fnv64a_string", []*cel.Type{str}, cel.DynType, cel.UnaryBinding(fnv64aImpl))),
		cel.Function("log2",
			cel.Overload("log2_double", []*cel.Type{dbl}, dbl, cel.UnaryBinding(logImpl(math.Log2))),
			cel.Overload("log2_int", []*cel.Type{in}, dbl, cel.UnaryBinding(logImpl(math.Log2)))),
		cel.Function("ln",
			cel.Overload("ln_double", []*cel.Type{dbl}, dbl, cel.UnaryBinding(logImpl(math.Log))),
			cel.Overload("ln_int", []*cel.Type{in}, dbl, cel.UnaryBinding(logImpl(math.Log)))),
	}
}

// sizedFuncs are the helpers whose run-time cost grows with their input:
// 1 plus one per 10 bytes of the string and bytes arguments (CEL's own
// string rate). The other helpers cost 1 per call, a function's default.
var sizedFuncs = map[string]bool{
	"sha256": true, "sha256Bytes": true, "hmacSha256": true, "hmacSha256Base64": true,
	"substrBytes": true, "base64Encode": true, "base64Decode": true, "fnv64a": true,
}

// sizedCost charges the sized helpers by function name rather than
// overload id, since eval's sandbox parses without checking and so its
// calls carry no overload id.
type sizedCost struct{}

func (sizedCost) CallCost(function, _ string, args []ref.Val, _ ref.Val) *uint64 {
	if c, ok := listCost(function, args); ok {
		return &c
	}
	if !sizedFuncs[function] {
		return nil
	}
	var n uint64
	for _, a := range args {
		if b, ok := rawBytes(a); ok {
			n += uint64(len(b))
		}
	}
	c := 1 + (n+9)/10
	return &c
}

// costOptions is the program option that applies sizedCost.
func costOptions() cel.ProgramOption { return cel.CostTracking(sizedCost{}) }

// rawBytes gives the bytes of a string or bytes value.
func rawBytes(v ref.Val) ([]byte, bool) {
	switch t := v.(type) {
	case types.String:
		return []byte(t), true
	case types.Bytes:
		return []byte(t), true
	}
	return nil, false
}

func sha256Impl(v ref.Val) ref.Val {
	b, ok := rawBytes(v)
	if !ok {
		return types.NewErr("sha256 needs a string or bytes")
	}
	sum := sha256.Sum256(b)
	return types.String(hex.EncodeToString(sum[:]))
}

func hmacSum(key, msg ref.Val) ([]byte, ref.Val) {
	k, ok1 := rawBytes(key)
	m, ok2 := rawBytes(msg)
	if !ok1 || !ok2 {
		return nil, types.NewErr("hmacSha256 needs a key and a message")
	}
	h := hmac.New(sha256.New, k)
	h.Write(m)
	return h.Sum(nil), nil
}

func hmacHex(key, msg ref.Val) ref.Val {
	sum, err := hmacSum(key, msg)
	if err != nil {
		return err
	}
	return types.String(hex.EncodeToString(sum))
}

func hmacB64(key, msg ref.Val) ref.Val {
	sum, err := hmacSum(key, msg)
	if err != nil {
		return err
	}
	return types.String(base64.StdEncoding.EncodeToString(sum))
}

func byteLenImpl(v ref.Val) ref.Val {
	b, ok := rawBytes(v)
	if !ok {
		return types.NewErr("byteLen needs a string or bytes")
	}
	return types.Int(len(b))
}

// substrBytesImpl is Go's s[start:end] on the UTF-8 bytes of s. A cut
// inside a character keeps the partial bytes as they are, as Go does; the
// result may then not be valid UTF-8. Bounds outside 0 <= start <= end <=
// byteLen(s) are an error.
func substrBytesImpl(args ...ref.Val) ref.Val {
	if len(args) != 3 {
		return types.NewErr("substrBytes needs a string, a start and an end")
	}
	s, ok1 := args[0].(types.String)
	start, ok2 := args[1].(types.Int)
	end, ok3 := args[2].(types.Int)
	if !ok1 || !ok2 || !ok3 {
		return types.NewErr("substrBytes needs a string and two ints")
	}
	if start < 0 || end < start || int(end) > len(s) {
		return types.NewErr("substrBytes: range [%d:%d] out of bounds for %d bytes", start, end, len(s))
	}
	return s[start:end]
}

func base64EncodeImpl(v ref.Val) ref.Val {
	b, ok := rawBytes(v)
	if !ok {
		return types.NewErr("base64Encode needs a string or bytes")
	}
	return types.String(base64.StdEncoding.EncodeToString(b))
}

// base64DecodeImpl decodes standard base64, padded or not, to a string.
// The decoded bytes must be UTF-8; base64.decode(s) gives bytes.
func base64DecodeImpl(v ref.Val) ref.Val {
	s, ok := v.(types.String)
	if !ok {
		return types.NewErr("base64Decode needs a string")
	}
	b, err := base64.StdEncoding.DecodeString(string(s))
	if err != nil {
		b, err = base64.RawStdEncoding.DecodeString(string(s))
	}
	if err != nil {
		return types.NewErr("base64Decode: %v", err)
	}
	if !utf8.Valid(b) {
		return types.NewErr("base64Decode: the decoded bytes are not UTF-8 (use base64.decode for bytes)")
	}
	return types.String(b)
}

// fnv64aImpl is the 64-bit FNV-1a hash of the UTF-8 bytes of s: a uint
// when it fits in an int, else its decimal string, so that it survives
// conversion to JSON. uint(fnv64a(s)) is a uint either way.
func fnv64aImpl(v ref.Val) ref.Val {
	s, ok := v.(types.String)
	if !ok {
		return types.NewErr("fnv64a needs a string")
	}
	h := fnv.New64a()
	h.Write([]byte(s))
	n := h.Sum64()
	if n > math.MaxInt64 {
		return types.String(strconv.FormatUint(n, 10))
	}
	return types.Uint(n)
}

func logImpl(f func(float64) float64) func(ref.Val) ref.Val {
	return func(v ref.Val) ref.Val {
		switch t := v.(type) {
		case types.Double:
			return types.Double(f(float64(t)))
		case types.Int:
			return types.Double(f(float64(t)))
		}
		return types.NewErr("log needs a number")
	}
}

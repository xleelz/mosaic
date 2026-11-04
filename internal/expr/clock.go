package expr

import (
	"time"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/common/types/ref"
)

// The §17 item 17 clock helpers: timestampUS(us) and timestampMS(ms) turn
// epoch microseconds (now_us) or milliseconds (now) into a CEL timestamp,
// keeping the sub-second part that timestamp(int(now / 1000)) drops. A
// timestamp prints in RFC 3339 with fractional seconds only when they are
// not zero (string(timestampUS(now_us)) is "2026-01-01T00:00:00.000250Z").
// Both are pure, so the eval sandbox gets them too.
func clockHelpers() []cel.EnvOption {
	return []cel.EnvOption{
		cel.Function("timestampUS",
			cel.Overload("timestampUS_int", []*cel.Type{cel.IntType}, cel.TimestampType, cel.UnaryBinding(func(v ref.Val) ref.Val {
				return types.Timestamp{Time: time.UnixMicro(int64(v.(types.Int))).UTC()}
			}))),
		cel.Function("timestampMS",
			cel.Overload("timestampMS_int", []*cel.Type{cel.IntType}, cel.TimestampType, cel.UnaryBinding(func(v ref.Val) ref.Val {
				return types.Timestamp{Time: time.UnixMilli(int64(v.(types.Int))).UTC()}
			}))),
	}
}

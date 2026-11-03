package expr

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sync"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/common/types/ref"
)

// IDsKey is the activation key that carries a run's id state (§15.1): an
// *IDs that CEL id(prefix, key...) and seq(name) read. A run creates one
// from its seed, so ids never come from the clock. Without it, id and seq
// use a fixed seed of 1 and a counter local to the evaluation.
const IDsKey = "__ids"

// maxIDKeys is the most keys one id(prefix, key...) call takes.
const maxIDKeys = 8

// IDs is a run's id state: the seed id() hashes, and seq()'s counters.
type IDs struct {
	seed int64
	mu   sync.Mutex
	seqs map[string]int64
}

// NewIDs returns the id state of a run with the given seed.
func NewIDs(seed int64) *IDs { return &IDs{seed: seed, seqs: map[string]int64{}} }

// ID returns a UUID-shaped id (version 8, RFC 9562 variant) that depends
// only on the seed, the prefix and the keys: the same seed and keys give
// the same id however the run's timing changes. Keys are hashed by their
// canonical JSON (sorted map keys), so 1 and "1" differ.
func (s *IDs) ID(prefix string, keys ...any) (string, error) {
	enc, err := json.Marshal(keys)
	if err != nil {
		return "", fmt.Errorf("id: keys can't be encoded: %v", err)
	}
	h := sha256.New()
	var seed [8]byte
	binary.BigEndian.PutUint64(seed[:], uint64(s.seed))
	h.Write([]byte("mosaic.id\x00"))
	h.Write(seed[:])
	h.Write([]byte(prefix))
	h.Write([]byte{0})
	h.Write(enc)
	sum := h.Sum(nil)
	b := sum[:16]
	b[6] = b[6]&0x0f | 0x80 // version 8: custom
	b[8] = b[8]&0x3f | 0x80 // RFC 9562 variant
	x := hex.EncodeToString(b)
	return x[0:8] + "-" + x[8:12] + "-" + x[12:16] + "-" + x[16:20] + "-" + x[20:32], nil
}

// Seq returns the next value of the run's counter name: 1, 2, 3 and so on.
func (s *IDs) Seq(name string) int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.seqs[name]++
	return s.seqs[name]
}

// idHelpers declares id(prefix, key...) and seq(name). Both are run-bound
// (late-bound to the activation's *IDs), so the eval sandbox lacks them.
func idHelpers() []cel.EnvOption {
	ids := []cel.FunctionOpt{}
	for n := 0; n <= maxIDKeys; n++ {
		args := []*cel.Type{cel.StringType}
		for range n {
			args = append(args, cel.DynType)
		}
		ids = append(ids, cel.Overload(fmt.Sprintf("id_string_%d", n), args, cel.StringType, cel.LateFunctionBinding()))
	}
	return []cel.EnvOption{
		cel.Function("id", ids...),
		cel.Function("seq", cel.Overload("seq_string", []*cel.Type{cel.StringType}, cel.IntType, cel.LateFunctionBinding())),
	}
}

// idBindings returns the late bindings of id and seq over the activation's
// *IDs, or over a fresh one with seed 1.
func idBindings(act map[string]any) map[string]cel.LateBoundFunction {
	ids, _ := act[IDsKey].(*IDs)
	if ids == nil {
		ids = NewIDs(1)
	}
	return map[string]cel.LateBoundFunction{
		"id": func(_ string, args ...ref.Val) ref.Val {
			if len(args) < 1 {
				return types.NewErr("id needs a prefix")
			}
			prefix, ok := args[0].(types.String)
			if !ok {
				return types.NewErr("id(prefix, key...) needs a string prefix")
			}
			keys := make([]any, len(args)-1)
			for i, a := range args[1:] {
				keys[i] = ToNative(a)
			}
			s, err := ids.ID(string(prefix), keys...)
			if err != nil {
				return types.NewErr("%v", err)
			}
			return types.String(s)
		},
		"seq": func(_ string, args ...ref.Val) ref.Val {
			if len(args) != 1 {
				return types.NewErr("seq needs one argument")
			}
			name, ok := args[0].(types.String)
			if !ok {
				return types.NewErr("seq(name) needs a string")
			}
			return types.Int(ids.Seq(string(name)))
		},
	}
}

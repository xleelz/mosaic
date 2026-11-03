package main

// Timing read back as state (T2; DESIGN §14.4: timing never fails the
// cross-level check).
//
// A refined run spends different virtual time from its black-box run, so
// any state a behavior stamps from ctx.now (a createdAt, a last_resync_ms, a
// deadline of now + ttl, an id like audit-<now>-ok) or a measured duration
// differs between the two even when the models agree. compareState walks
// both values of one state key and splits the differences into boundary
// differences and timing:
//
//   - Structure must match: the same object keys, array lengths and JSON
//     types. Two object keys pair when they are equal, or when they differ
//     only in clock tokens (below) and pair one to one; such a key pair is
//     timing. Any other key, length or type difference is a boundary
//     difference.
//   - A differing number is timing when it is time-like, that is its key
//     names time (…_ms, …Ms, …_us, …_at, …At, …time, timestamp, deadline,
//     expires, until, elapsed, duration, latency, since, ts) or it lies in
//     the virtual clock's window in both runs, and the two values are no
//     further apart than the bound.
//   - A differing string is timing when both split into the same text
//     around clock tokens (RFC 3339 timestamps, and 10- or 13-digit numbers
//     in the clock window, in seconds or milliseconds), and each differing
//     token pair is within the bound.
//   - The clock window runs from the run's epoch to a year past its end;
//     it applies only when the epoch is a real date (not the default 0).
//   - The bound is the longer run's virtual duration plus 1 ms: two reads of
//     the same clock, or two durations measured in it, can't differ by
//     more. It's in seconds for values in seconds.
//
// A state key whose differences are all timing is reported under timing,
// not as a boundary difference.

import (
	"encoding/json"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/xleelz/mosaic/internal/sim"
)

// leafDiff is one differing place in two JSON values.
type leafDiff struct {
	Path       string
	A, B       any
	Structural bool // keys, length or type differ
	NoA, NoB   bool // the key is absent from the parent's or the child's
}

// clockSpan is what a run's clock can produce: its epoch and duration (ms).
type clockSpan struct {
	EpochMS, DurMS int64
}

func spanOf(r *sim.Result) clockSpan {
	s := clockSpan{DurMS: r.Summary.DurationMS}
	if r.Request.Clock != nil {
		s.EpochMS, _ = r.Request.Clock.EpochMillis()
	}
	return s
}

var (
	reTimeName  = regexp.MustCompile(`(?:_ms|Ms|MS|_us|Us|_at|At|[tT]ime|[tT]imestamp|[dD]eadline|[eE]xpires?|[uU]ntil|[eE]lapsed|[dD]uration|[lL]atency|[sS]ince|^ts)$`)
	reClockTok  = regexp.MustCompile(`\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})|\b\d{13}\b|\b\d{10}\b`)
	yearMS      = float64(366 * 24 * 3600 * 1000)
	realEpochMS = int64(100_000_000_000) // 1973: below it the epoch is a default
)

// timeMask compares two runs' values with their clocks.
type timeMask struct {
	a, b   clockSpan
	diffs  []leafDiff // boundary differences
	timing []leafDiff // timing differences
}

func (m *timeMask) bound() float64 { return float64(max(m.a.DurMS, m.b.DurMS)) + 1 }

// inClock says whether n could be a read of the run's clock: "ms" or "s",
// or "" when it can't.
func inClock(n float64, s clockSpan) string {
	if s.EpochMS < realEpochMS {
		return ""
	}
	lo, hi := float64(s.EpochMS), float64(s.EpochMS)+float64(s.DurMS)+yearMS
	switch {
	case n >= lo && n <= hi:
		return "ms"
	case n >= math.Floor(lo/1000) && n <= math.Ceil(hi/1000):
		return "s"
	}
	return ""
}

// numsTiming: two differing numbers at a key.
func (m *timeMask) numsTiming(key string, a, b float64) bool {
	ua, ub := inClock(a, m.a), inClock(b, m.b)
	if ua == "s" && ub == "s" {
		return math.Abs(a-b) <= math.Ceil(m.bound()/1000)
	}
	clock := ua == "ms" && ub == "ms"
	if !clock && !reTimeName.MatchString(key) {
		return false
	}
	return math.Abs(a-b) <= m.bound()
}

// tokTiming: two differing clock tokens.
func (m *timeMask) tokTiming(x, y string) bool {
	if tx, err := time.Parse(time.RFC3339Nano, x); err == nil {
		ty, err := time.Parse(time.RFC3339Nano, y)
		return err == nil && math.Abs(float64(tx.Sub(ty).Milliseconds())) <= m.bound()
	}
	a, errA := strconv.ParseFloat(x, 64)
	b, errB := strconv.ParseFloat(y, 64)
	if errA != nil || errB != nil || len(x) != len(y) {
		return false
	}
	ua, ub := inClock(a, m.a), inClock(b, m.b)
	if ua == "" || ua != ub {
		return false
	}
	if ua == "s" {
		return math.Abs(a-b) <= math.Ceil(m.bound()/1000)
	}
	return math.Abs(a-b) <= m.bound()
}

// stringsTiming: two strings that differ only in clock tokens within the
// bound.
func (m *timeMask) stringsTiming(x, y string) bool {
	ix, iy := reClockTok.FindAllStringIndex(x, -1), reClockTok.FindAllStringIndex(y, -1)
	if len(ix) == 0 || len(ix) != len(iy) {
		return false
	}
	px, py := 0, 0
	for k := range ix {
		if x[px:ix[k][0]] != y[py:iy[k][0]] {
			return false
		}
		tx, ty := x[ix[k][0]:ix[k][1]], y[iy[k][0]:iy[k][1]]
		if tx != ty && !m.tokTiming(tx, ty) {
			return false
		}
		px, py = ix[k][1], iy[k][1]
	}
	return x[px:] == y[py:]
}

// clockKey is a key with its clock tokens blanked, for pairing keys.
func clockKey(k string) string { return reClockTok.ReplaceAllString(k, "\x00") }

func (m *timeMask) walk(path string, a, b any) {
	switch av := a.(type) {
	case map[string]any:
		bv, ok := b.(map[string]any)
		if !ok {
			m.diffs = append(m.diffs, leafDiff{Path: path, A: a, B: b, Structural: true})
			return
		}
		m.walkMap(path, av, bv)
	case []any:
		bv, ok := b.([]any)
		if !ok || len(av) != len(bv) {
			m.diffs = append(m.diffs, leafDiff{Path: path, A: a, B: b, Structural: true})
			return
		}
		for i := range av {
			m.walk(fmt.Sprintf("%s[%d]", path, i), av[i], bv[i])
		}
	default:
		if canonJSON(a) == canonJSON(b) {
			return
		}
		d := leafDiff{Path: path, A: a, B: b}
		key := path
		if i := strings.LastIndexAny(key, ".]"); i >= 0 {
			key = key[i+1:]
		}
		x, okX := a.(float64)
		y, okY := b.(float64)
		sx, okSX := a.(string)
		sy, okSY := b.(string)
		switch {
		case okX && okY && m.numsTiming(key, x, y), okSX && okSY && m.stringsTiming(sx, sy):
			m.timing = append(m.timing, d)
		default:
			d.Structural = jsonKind(a) != jsonKind(b)
			m.diffs = append(m.diffs, d)
		}
	}
}

// walkMap pairs keys exactly, then the rest by their clock-blanked form
// when it pairs them one to one and they differ only in timing.
func (m *timeMask) walkMap(path string, av, bv map[string]any) {
	onlyA, onlyB := map[string][]string{}, map[string][]string{}
	keys := map[string]bool{}
	for k := range av {
		keys[k] = true
	}
	for k := range bv {
		keys[k] = true
	}
	paired := map[string]string{} // a key -> b key
	for _, k := range sortedKeys(keys) {
		_, okA := av[k]
		_, okB := bv[k]
		switch {
		case okA && okB:
			paired[k] = k
		case okA:
			onlyA[clockKey(k)] = append(onlyA[clockKey(k)], k)
		default:
			onlyB[clockKey(k)] = append(onlyB[clockKey(k)], k)
		}
	}
	for ck, as := range onlyA {
		if bs := onlyB[ck]; len(as) == 1 && len(bs) == 1 && m.stringsTiming(as[0], bs[0]) {
			paired[as[0]] = bs[0]
			m.timing = append(m.timing, leafDiff{Path: path + "." + as[0] + " (key)", A: as[0], B: bs[0]})
			delete(onlyA, ck)
			delete(onlyB, ck)
		}
	}
	for _, ka := range sortedKeys(keys) {
		if kb, ok := paired[ka]; ok {
			m.walk(path+"."+ka, av[ka], bv[kb])
		}
	}
	for _, ks := range onlyA {
		for _, k := range ks {
			m.diffs = append(m.diffs, leafDiff{Path: path + "." + k, A: av[k], Structural: true, NoB: true})
		}
	}
	for _, ks := range onlyB {
		for _, k := range ks {
			m.diffs = append(m.diffs, leafDiff{Path: path + "." + k, B: bv[k], Structural: true, NoA: true})
		}
	}
}

func sortDiffs(ds []leafDiff) {
	sort.SliceStable(ds, func(i, j int) bool { return ds[i].Path < ds[j].Path })
}

func jsonKind(v any) string {
	switch v.(type) {
	case nil:
		return "null"
	case bool:
		return "bool"
	case string:
		return "string"
	case float64:
		return "number"
	case map[string]any:
		return "object"
	case []any:
		return "array"
	}
	return fmt.Sprintf("%T", v)
}

// stateCompare is one state key's comparison.
type stateCompare struct {
	Diffs  []leafDiff // boundary differences
	Timing []leafDiff // timing differences, masked
}

// compareState compares one state key's values, masking timing.
func compareState(a, b any, sa, sb clockSpan) stateCompare {
	m := &timeMask{a: sa, b: sb}
	m.walk("", normJSON(a), normJSON(b))
	sortDiffs(m.diffs)
	sortDiffs(m.timing)
	return stateCompare{Diffs: m.diffs, Timing: m.timing}
}

// normJSON round-trips a value through JSON so maps, slices and numbers have
// one representation (numbers float64).
func normJSON(v any) any {
	b, err := json.Marshal(v)
	if err != nil {
		return v
	}
	var out any
	if json.Unmarshal(b, &out) != nil {
		return v
	}
	return out
}

func leafPath(p string) string {
	if p == "" {
		return "(root)"
	}
	return strings.TrimPrefix(p, ".")
}

// describeLeaves renders up to n differing places.
func describeLeaves(ds []leafDiff, n int) string {
	var parts []string
	for i, d := range ds {
		if i == n {
			parts = append(parts, "+"+strconv.Itoa(len(ds)-n)+" more")
			break
		}
		a, b := "absent", "absent"
		if !d.NoA {
			a = clip(canonJSON(d.A))
		}
		if !d.NoB {
			b = clip(canonJSON(d.B))
		}
		parts = append(parts, fmt.Sprintf("%s: parent %s, child %s", leafPath(d.Path), a, b))
	}
	return strings.Join(parts, "; ")
}

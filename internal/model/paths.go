package model

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
)

// State paths with quoted segments (behavior-language §30). A path is
// segments joined by dots; a segment may instead be written in brackets
// with single or double quotes, ['ORG#acme.v2'] or ["ORG#acme.v2"], so a
// key that holds dots (or any other character) can be named. A backslash
// escapes the quote or a backslash inside the brackets. A bracketed
// segment follows the previous one directly (state['a.b'].c) or starts the
// path (['a.b'].c, in a scenario set step).

// PathSeg is one segment of a state path. Quoted is true for a bracketed
// segment, whose text may be anything but empty.
type PathSeg struct {
	Key    string
	Quoted bool
}

// ParsePath splits a path into its segments. Without brackets it is
// strings.Split(path, "."). Empty segments are errors.
func ParsePath(path string) ([]PathSeg, error) {
	if !strings.Contains(path, "[") {
		parts := strings.Split(path, ".")
		out := make([]PathSeg, len(parts))
		for i, p := range parts {
			if p == "" {
				return nil, fmt.Errorf("invalid path segment \"\" in %q", path)
			}
			out[i] = PathSeg{Key: p}
		}
		return out, nil
	}
	var out []PathSeg
	i, n := 0, len(path)
	for i < n {
		if path[i] == '[' {
			if i+1 >= n || (path[i+1] != '\'' && path[i+1] != '"') {
				return nil, fmt.Errorf("invalid path %q: a bracket holds a quoted key, ['...'] or [\"...\"]", path)
			}
			q := path[i+1]
			var b strings.Builder
			j := i + 2
			closed := false
			for j < n {
				c := path[j]
				if c == '\\' && j+1 < n && (path[j+1] == q || path[j+1] == '\\') {
					b.WriteByte(path[j+1])
					j += 2
					continue
				}
				if c == q {
					closed = true
					break
				}
				b.WriteByte(c)
				j++
			}
			if !closed || j+1 >= n || path[j+1] != ']' {
				return nil, fmt.Errorf("invalid path %q: unterminated quoted key", path)
			}
			if b.Len() == 0 {
				return nil, fmt.Errorf("invalid path %q: empty quoted key", path)
			}
			out = append(out, PathSeg{Key: b.String(), Quoted: true})
			i = j + 2
		} else {
			j := i
			for j < n && path[j] != '.' && path[j] != '[' {
				j++
			}
			if j == i {
				return nil, fmt.Errorf("invalid path segment \"\" in %q", path)
			}
			out = append(out, PathSeg{Key: path[i:j]})
			i = j
		}
		// After a segment: the end, a dot and another segment, or a bracket.
		if i < n {
			switch path[i] {
			case '.':
				i++
				if i >= n {
					return nil, fmt.Errorf("invalid path segment \"\" in %q", path)
				}
			case '[':
			default:
				return nil, fmt.Errorf("invalid path %q: expected . or [ after a quoted key", path)
			}
		}
	}
	return out, nil
}

// SplitPath is ParsePath without the quoting flags.
func SplitPath(path string) ([]string, error) {
	segs, err := ParsePath(path)
	if err != nil {
		return nil, err
	}
	out := make([]string, len(segs))
	for i, s := range segs {
		out[i] = s.Key
	}
	return out, nil
}

// lossyInts warns about every whole number in the document beyond both
// int64 and uint64 (behavior-language §30): CEL sees it as a double, which
// loses digits. Numbers up to 2^64-1 are kept as uint64.
func (v *validator) lossyInts() {
	b, err := json.Marshal(v.x.Doc)
	if err != nil || len(expr.LossyInts(b)) == 0 {
		return
	}
	var doc any
	if err := Decode(b, &doc); err != nil {
		return
	}
	expr.WalkLossyInts(doc, "", func(path, lit string) {
		var f float64
		_ = json.Unmarshal([]byte(lit), &f)
		v.warnf(path, "the integer %s is beyond uint64 (18446744073709551615), so CEL sees the double %g and digits are lost; write {$bigint: \"%s\"} in an input to keep them as a decimal string, or a smaller number", lit, f, lit)
	})
}

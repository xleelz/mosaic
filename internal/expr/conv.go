package expr

import "strings"

// conversions are the type conversion functions that cel-go (v0.33) fails to
// dispatch when their argument is a map index with a constant key on a dyn
// value: string(input['x']) gives "no such overload: string(int)", while
// string(input.x) and string(dyn(input['x'])) work.
var conversions = []string{"string", "double", "int", "uint", "bytes", "bool"}

// wrapConversions works around that bug by rewriting each conversion call's
// argument to dyn(...), which is the identity at run time. It skips string
// literals and member calls (x.string(...)), and leaves the source unchanged
// when the parentheses don't balance (the compiler then reports the error).
func wrapConversions(src string) string {
	if !strings.Contains(src, "(") {
		return src
	}
	var b strings.Builder
	n := len(src)
	for i := 0; i < n; {
		c := src[i]
		if c == '"' || c == '\'' {
			j := skipString(src, i)
			b.WriteString(src[i:j])
			i = j
			continue
		}
		if isIdentStart(c) && (i == 0 || (!isIdentChar(src[i-1]) && src[i-1] != '.')) {
			j := i
			for j < n && isIdentChar(src[j]) {
				j++
			}
			name := src[i:j]
			k := j
			for k < n && (src[k] == ' ' || src[k] == '\t') {
				k++
			}
			if k < n && src[k] == '(' && isConversion(name) {
				end := matchParen(src, k)
				if end < 0 {
					return src
				}
				inner := src[k+1 : end]
				if strings.TrimSpace(inner) == "" {
					b.WriteString(src[i : end+1])
				} else {
					b.WriteString(name + "(dyn(" + wrapConversions(inner) + "))")
				}
				i = end + 1
				continue
			}
			b.WriteString(name)
			i = j
			continue
		}
		b.WriteByte(c)
		i++
	}
	return b.String()
}

func isConversion(name string) bool {
	for _, c := range conversions {
		if name == c {
			return true
		}
	}
	return false
}

func isIdentStart(c byte) bool {
	return c == '_' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
}

func isIdentChar(c byte) bool { return isIdentStart(c) || (c >= '0' && c <= '9') }

// skipString returns the index just past the string literal starting at i,
// handling triple quotes and backslash escapes. Raw-string prefixes (r'...')
// are fine: the prefix is copied as an identifier and the literal follows.
func skipString(s string, i int) int {
	q := s[i]
	if strings.HasPrefix(s[i:], string([]byte{q, q, q})) {
		if end := strings.Index(s[i+3:], string([]byte{q, q, q})); end >= 0 {
			return i + 3 + end + 3
		}
		return len(s)
	}
	for j := i + 1; j < len(s); j++ {
		switch s[j] {
		case '\\':
			j++
		case q:
			return j + 1
		}
	}
	return len(s)
}

// matchParen returns the index of the ')' closing the '(' at i, or -1.
func matchParen(s string, i int) int {
	depth := 0
	for j := i; j < len(s); j++ {
		switch c := s[j]; {
		case c == '"' || c == '\'':
			j = skipString(s, j) - 1
		case c == '(':
			depth++
		case c == ')':
			depth--
			if depth == 0 {
				return j
			}
		}
	}
	return -1
}

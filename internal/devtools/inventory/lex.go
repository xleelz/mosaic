package main

// Lexers for the plugin scanners. Each drops comments and keeps string
// literals as opaque tokens, so a pattern in a comment or a string never
// matches. TypeScript and Python reuse jtok and jmatch from the Java support;
// C++, CUDA and Rust sources go through jlex directly.

import "strings"

// tsRegexPrev lists the keywords after which a '/' starts a regular
// expression rather than a division.
var tsRegexPrev = map[string]bool{
	"return": true, "typeof": true, "case": true, "do": true, "else": true, "in": true,
	"of": true, "new": true, "delete": true, "void": true, "throw": true, "instanceof": true,
	"yield": true, "await": true,
}

// tslex tokenizes TypeScript or JavaScript. Template literals become one
// 't' token holding their raw text (substitutions included); regular
// expression literals become one 'r' token.
func tslex(src []byte) []jtok {
	var out []jtok
	line, n := 1, len(src)
	regexOK := func() bool {
		if len(out) == 0 {
			return true
		}
		p := out[len(out)-1]
		switch p.k {
		case 'n', 's', 't', 'r':
			return false
		case 'i':
			return tsRegexPrev[p.s]
		}
		return p.s != ")" && p.s != "]" && p.s != "}"
	}
	for i := 0; i < n; {
		c := src[i]
		switch {
		case c == '\n':
			line++
			i++
		case c == ' ' || c == '\t' || c == '\r' || c == '\f':
			i++
		case c == '/' && i+1 < n && src[i+1] == '/':
			for i < n && src[i] != '\n' {
				i++
			}
		case c == '/' && i+1 < n && src[i+1] == '*':
			i += 2
			for i < n && !(src[i] == '*' && i+1 < n && src[i+1] == '/') {
				if src[i] == '\n' {
					line++
				}
				i++
			}
			i += 2
		case c == '`':
			start := line
			j := tsTemplateEnd(src, i+1, &line)
			out = append(out, jtok{string(src[i+1 : min(j, n)]), start, 't'})
			i = j + 1
		case c == '"' || c == '\'':
			j := i + 1
			for j < n && src[j] != c && src[j] != '\n' {
				if src[j] == '\\' && j+1 < n {
					if src[j+1] == '\n' {
						line++
					}
					j++
				}
				j++
			}
			out = append(out, jtok{string(src[i+1 : min(j, n)]), line, 's'})
			i = j + 1
			if j < n && src[j] == '\n' {
				i = j // unterminated (a Rust lifetime): keep the newline
			}
		case c == '/' && regexOK():
			j, cls := i+1, false
			for j < n && src[j] != '\n' {
				if src[j] == '\\' {
					j += 2
					continue
				}
				if src[j] == '[' {
					cls = true
				} else if src[j] == ']' {
					cls = false
				} else if src[j] == '/' && !cls {
					break
				}
				j++
			}
			j++
			for j < n && jIdentPart(src[j]) {
				j++
			}
			out = append(out, jtok{string(src[i:min(j, n)]), line, 'r'})
			i = j
		case jIdentStart(c):
			j := i + 1
			for j < n && jIdentPart(src[j]) {
				j++
			}
			out = append(out, jtok{string(src[i:j]), line, 'i'})
			i = j
		case c >= '0' && c <= '9':
			j := i + 1
			for j < n && (jIdentPart(src[j]) || src[j] == '.') {
				j++
			}
			out = append(out, jtok{string(src[i:j]), line, 'n'})
			i = j
		default:
			if i+2 < n && string(src[i:i+3]) == "..." {
				out = append(out, jtok{"...", line, 'p'})
				i += 3
			} else if i+1 < n && (string(src[i:i+2]) == "=>" || string(src[i:i+2]) == "?." || string(src[i:i+2]) == "==" || string(src[i:i+2]) == "!=" || string(src[i:i+2]) == "&&" || string(src[i:i+2]) == "||" || string(src[i:i+2]) == "??") {
				out = append(out, jtok{string(src[i : i+2]), line, 'p'})
				i += 2
			} else {
				out = append(out, jtok{string(src[i : i+1]), line, 'p'})
				i++
			}
		}
	}
	return out
}

// tsTemplateEnd returns the index of the backtick closing a template literal
// whose body starts at i, skipping ${...} substitutions (which may hold
// strings, comments and nested templates).
func tsTemplateEnd(src []byte, i int, line *int) int {
	n := len(src)
	for i < n {
		switch c := src[i]; {
		case c == '\\':
			i += 2
			continue
		case c == '\n':
			*line++
		case c == '`':
			return i
		case c == '$' && i+1 < n && src[i+1] == '{':
			depth := 1
			i += 2
			for i < n && depth > 0 {
				switch d := src[i]; {
				case d == '\n':
					*line++
				case d == '{':
					depth++
				case d == '}':
					depth--
				case d == '`':
					i = tsTemplateEnd(src, i+1, line)
				case d == '"' || d == '\'':
					j := i + 1
					for j < n && src[j] != d && src[j] != '\n' {
						if src[j] == '\\' {
							j++
						}
						j++
					}
					i = j
				}
				i++
			}
			continue
		}
		i++
	}
	return n
}

// pyTok is a Python token with the column it starts at, so logical lines
// carry their indentation.
type pyTok struct {
	jtok
	col int // column of the token's first byte
}

// pylex tokenizes Python. Comments are dropped; strings (with any r/b/f/u
// prefix, triple-quoted or not) become 's' tokens; the end of each logical
// line (outside brackets) is an 'l' token.
func pylex(src []byte) []pyTok {
	var out []pyTok
	line, n, depth, lineStart := 1, len(src), 0, 0
	emit := func(s string, ln int, k byte, at int) {
		out = append(out, pyTok{jtok{s, ln, k}, at - lineStart})
	}
	endLine := func() {
		if depth == 0 && len(out) > 0 && out[len(out)-1].k != 'l' {
			out = append(out, pyTok{jtok{"", line, 'l'}, 0})
		}
	}
	for i := 0; i < n; {
		c := src[i]
		switch {
		case c == '\n':
			endLine()
			line++
			i++
			lineStart = i
		case c == '\\' && i+1 < n && src[i+1] == '\n':
			line++
			i += 2
			lineStart = i
		case c == ' ' || c == '\t' || c == '\r' || c == '\f':
			i++
		case c == '#':
			for i < n && src[i] != '\n' {
				i++
			}
		case c == '"' || c == '\'' || (pyStrPrefix(src, i) > 0):
			p := pyStrPrefix(src, i)
			if c == '"' || c == '\'' {
				p = 0
			}
			q := i + p
			quote := src[q]
			start, col := line, i-lineStart
			triple := q+2 < n && src[q+1] == quote && src[q+2] == quote
			var j int
			if triple {
				j = q + 3
				for j < n && !(src[j] == quote && j+2 < n && src[j+1] == quote && src[j+2] == quote) {
					if src[j] == '\\' {
						j++
					} else if src[j] == '\n' {
						line++
						lineStart = j + 1
					}
					j++
				}
				out = append(out, pyTok{jtok{string(src[q+3 : min(j, n)]), start, 's'}, col})
				i = j + 3
			} else {
				j = q + 1
				for j < n && src[j] != quote && src[j] != '\n' {
					if src[j] == '\\' {
						j++
					}
					j++
				}
				out = append(out, pyTok{jtok{string(src[q+1 : min(j, n)]), start, 's'}, col})
				i = j + 1
				if j < n && src[j] == '\n' {
					i = j // unterminated: keep the newline
				}
			}
			if i > n {
				i = n
			}
		case jIdentStart(c):
			j := i + 1
			for j < n && jIdentPart(src[j]) {
				j++
			}
			emit(string(src[i:j]), line, 'i', i)
			i = j
		case c >= '0' && c <= '9':
			j := i + 1
			for j < n && (jIdentPart(src[j]) || src[j] == '.') {
				j++
			}
			emit(string(src[i:j]), line, 'n', i)
			i = j
		default:
			switch c {
			case '(', '[', '{':
				depth++
			case ')', ']', '}':
				if depth > 0 {
					depth--
				}
			}
			if i+1 < n && (string(src[i:i+2]) == "->" || string(src[i:i+2]) == "**" || string(src[i:i+2]) == "==") {
				emit(string(src[i:i+2]), line, 'p', i)
				i += 2
			} else {
				emit(string(src[i:i+1]), line, 'p', i)
				i++
			}
		}
	}
	endLine()
	return out
}

// pyStrPrefix returns the length of a string prefix (r, b, f, u, rb, br, fr,
// rf in any case) at i that is immediately followed by a quote, or 0.
func pyStrPrefix(src []byte, i int) int {
	if i > 0 && jIdentPart(src[i-1]) {
		return 0
	}
	for p := 1; p <= 2 && i+p < len(src); p++ {
		ok := true
		for _, b := range src[i : i+p] {
			if !strings.ContainsRune("rRbBfFuU", rune(b)) {
				ok = false
			}
		}
		if !ok {
			return 0
		}
		if src[i+p] == '"' || src[i+p] == '\'' {
			return p
		}
	}
	return 0
}

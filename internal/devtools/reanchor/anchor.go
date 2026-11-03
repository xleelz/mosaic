package main

import (
	"regexp"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// Citation statuses. A citation can be renamed and shifted or edited at once.
const (
	stUnchanged   = "unchanged"
	stShifted     = "shifted"      // same lines, new numbers
	stEdited      = "edited"       // some cited lines were changed, or lines were inserted inside the range
	stRenamed     = "renamed"      // the file moved
	stStale       = "stale"        // every cited line was deleted; the citation points where they were
	stFileDeleted = "file_deleted" // the file was deleted; the citation is left as it was
	stPinned      = "pinned"       // an object citation whose sha names another commit: left alone
)

var statusOrder = []string{stUnchanged, stShifted, stEdited, stRenamed, stStale, stFileDeleted, stPinned}

// anchored is the fate of one citation.
type anchored struct {
	Old      model.Source
	New      model.Source
	Statuses []string
}

func (a anchored) has(s string) bool {
	for _, x := range a.Statuses {
		if x == s {
			return true
		}
	}
	return false
}

// reanchor maps a citation from the old commit to the new one.
func (ch changes) reanchor(src model.Source) anchored {
	out := anchored{Old: src, New: src}
	fc, ok := ch[src.Path]
	if !ok {
		out.Statuses = []string{stUnchanged}
		return out
	}
	if fc.deleted {
		out.Statuses = []string{stFileDeleted}
		return out
	}
	var st []string
	if fc.newPath != "" && fc.newPath != src.Path {
		out.New.Path = fc.newPath
		st = append(st, stRenamed)
	}
	if src.Line > 0 {
		lo, hi := src.Line, src.Line
		if src.EndLine > src.Line {
			hi = src.EndLine
		}
		newLo, newHi, survived, firstDeleted := 0, 0, false, 0
		for l := lo; l <= hi; l++ {
			n, fate, h := fc.mapLine(l)
			if fate == lineDeleted {
				if firstDeleted == 0 {
					firstDeleted = n
				}
				continue
			}
			if fate == lineEdited && hi > lo && l == hi && l == h.os+h.oc-1 {
				n = h.ns + h.nc - 1 // the range ends at the end of a replacement: keep all of it
			}
			if !survived || n < newLo {
				newLo = n
			}
			if !survived || n > newHi {
				newHi = n
			}
			survived = true
		}
		switch {
		case !survived:
			out.New.Line, out.New.EndLine = max(firstDeleted, 1), 0
			st = append(st, stStale)
		default:
			out.New.Line = newLo
			out.New.EndLine = 0
			if src.EndLine > 0 {
				out.New.EndLine = newHi
			}
			if fc.touches(lo, hi) {
				st = append(st, stEdited)
			} else if newLo != lo {
				st = append(st, stShifted)
			}
		}
	}
	if len(st) == 0 {
		st = []string{stUnchanged}
	}
	out.Statuses = st
	return out
}

// tokenRE finds "path:line" and "path:line-end" tokens. Paths are runs of
// [A-Za-z0-9_./@+~-]; ':' is not a path character, so a match never starts
// inside a path.
var tokenRE = regexp.MustCompile(`[A-Za-z0-9_./@+~-]+:[0-9]+(?:-[0-9]+)?`)

func isTokenTail(c byte) bool {
	return c >= '0' && c <= '9' || c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c == '_' || c == '.' || c == ':' || c == '-' || c == '/'
}

// rewriteText rewrites the citations in a citation string: every path:line
// token (a packed string can hold several), or the whole string when it is a
// bare path. It calls note for each citation it maps.
func (ch changes) rewriteText(s string, note func(anchored)) string {
	locs := tokenRE.FindAllStringIndex(s, -1)
	var b strings.Builder
	last, found := 0, false
	for _, loc := range locs {
		if loc[1] < len(s) && isTokenTail(s[loc[1]]) {
			continue // "a.go:12:5", "host:80.x" and the like are not citations
		}
		tok := s[loc[0]:loc[1]]
		src := model.ParseSource(tok)
		if src.Line == 0 {
			continue
		}
		if i := strings.LastIndex(tok, "-"); i > strings.LastIndex(tok, ":") && src.EndLine == 0 {
			continue // "x:9-3": an end before the start is not a range
		}
		found = true
		a := ch.reanchor(src)
		note(a)
		b.WriteString(s[last:loc[0]])
		b.WriteString(a.New.String())
		last = loc[1]
	}
	if !found {
		p := strings.TrimSpace(s)
		if p == "" || strings.ContainsAny(p, " \t,") {
			return s
		}
		a := ch.reanchor(model.Source{Path: p})
		note(a)
		return strings.Replace(s, p, a.New.Path, 1)
	}
	b.WriteString(s[last:])
	return b.String()
}

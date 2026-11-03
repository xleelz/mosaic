package main

import (
	"bufio"
	"bytes"
	"fmt"
	"os/exec"
	"strconv"
	"strings"
)

// hunk is one "@@ -os,oc +ns,nc @@" header of a zero-context diff. oc == 0
// is an insertion after old line os; nc == 0 is a deletion after new line ns.
type hunk struct{ os, oc, ns, nc int }

// fileChange is what happened to one path between the two commits.
type fileChange struct {
	newPath string
	deleted bool
	hunks   []hunk // in old-line order
}

// changes maps the old path of every changed file to its change. A path that
// isn't in it is unchanged.
type changes map[string]*fileChange

// git runs a read-only git subcommand against repo.
func git(repo string, args ...string) ([]byte, error) {
	switch args[0] {
	case "diff", "show", "rev-parse", "log":
	default:
		return nil, fmt.Errorf("refusing to run git %s: only diff, show, rev-parse and log are allowed", args[0])
	}
	full := append([]string{"-C", repo, "-c", "core.quotePath=false"}, args...)
	cmd := exec.Command("git", full...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("git %s: %v: %s", strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return out, nil
}

// resolve turns a revision into a full commit sha.
func resolve(repo, rev string) (string, error) {
	out, err := git(repo, "rev-parse", "--verify", "--end-of-options", rev+"^{commit}")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(out)), nil
}

// loadChanges reads the zero-context diff between two commits, with renames.
func loadChanges(repo, from, to string) (changes, error) {
	out, err := git(repo, "diff", "-M", "--unified=0", "--no-color", "--no-ext-diff", "--no-textconv", from, to, "--")
	if err != nil {
		return nil, err
	}
	return parseDiff(out)
}

// parseDiff parses `git diff -M --unified=0` output.
func parseDiff(out []byte) (changes, error) {
	ch := changes{}
	var cur *fileChange
	var oldPath string
	flush := func() {
		if cur != nil && oldPath != "" {
			ch[oldPath] = cur
		}
		cur, oldPath = nil, ""
	}
	sc := bufio.NewScanner(bytes.NewReader(out))
	sc.Buffer(make([]byte, 1<<20), 1<<30)
	for sc.Scan() {
		line := sc.Text()
		switch {
		case strings.HasPrefix(line, "diff --git "):
			flush()
			cur = &fileChange{}
			// "a/P b/P" when the path is unchanged; renames are named below.
			rest := strings.TrimPrefix(line, "diff --git ")
			if n := len(rest); n%2 == 1 {
				half := (n - 1) / 2
				a, b := rest[:half], rest[half+1:]
				if strings.HasPrefix(a, "a/") && strings.HasPrefix(b, "b/") && a[2:] == b[2:] {
					oldPath, cur.newPath = a[2:], b[2:]
				}
			}
		case cur == nil:
		case strings.HasPrefix(line, "rename from "):
			oldPath = strings.TrimPrefix(line, "rename from ")
		case strings.HasPrefix(line, "rename to "):
			cur.newPath = strings.TrimPrefix(line, "rename to ")
		case strings.HasPrefix(line, "deleted file mode"):
			cur.deleted = true
		case strings.HasPrefix(line, "--- "):
			if p := strings.TrimPrefix(line, "--- "); strings.HasPrefix(p, "a/") {
				oldPath = p[2:]
			}
		case strings.HasPrefix(line, "+++ "):
			p := strings.TrimPrefix(line, "+++ ")
			if p == "/dev/null" {
				cur.deleted = true
			} else if strings.HasPrefix(p, "b/") {
				cur.newPath = p[2:]
			}
		case strings.HasPrefix(line, "@@ "):
			h, err := parseHunk(line)
			if err != nil {
				return nil, err
			}
			cur.hunks = append(cur.hunks, h)
		}
	}
	flush()
	return ch, sc.Err()
}

// parseHunk parses "@@ -os[,oc] +ns[,nc] @@ ...".
func parseHunk(line string) (hunk, error) {
	f := strings.Fields(line)
	if len(f) < 3 || !strings.HasPrefix(f[1], "-") || !strings.HasPrefix(f[2], "+") {
		return hunk{}, fmt.Errorf("bad hunk header %q", line)
	}
	span := func(s string) (int, int, error) {
		a, b, found := strings.Cut(s[1:], ",")
		start, err := strconv.Atoi(a)
		if err != nil {
			return 0, 0, err
		}
		count := 1
		if found {
			if count, err = strconv.Atoi(b); err != nil {
				return 0, 0, err
			}
		}
		return start, count, nil
	}
	os, oc, err := span(f[1])
	if err != nil {
		return hunk{}, fmt.Errorf("bad hunk header %q", line)
	}
	ns, nc, err := span(f[2])
	if err != nil {
		return hunk{}, fmt.Errorf("bad hunk header %q", line)
	}
	return hunk{os, oc, ns, nc}, nil
}

// Line fates.
const (
	lineKept    = iota // the line survives, perhaps shifted
	lineEdited         // the line was replaced: mapped into its replacement
	lineDeleted        // the line was deleted with nothing in its place
)

// mapLine maps old line l to the new file. For a deleted line it returns the
// line that now follows the deletion. h is the hunk that touched the line.
func (fc *fileChange) mapLine(l int) (int, int, hunk) {
	delta := 0
	for _, h := range fc.hunks {
		if h.oc == 0 {
			if l <= h.os {
				break
			}
			delta += h.nc
			continue
		}
		if l < h.os {
			break
		}
		if l <= h.os+h.oc-1 {
			if h.nc == 0 {
				return h.ns + 1, lineDeleted, h
			}
			return h.ns + min(l-h.os, h.nc-1), lineEdited, h
		}
		delta += h.nc - h.oc
	}
	return l + delta, lineKept, hunk{}
}

// touches reports whether any hunk changes old lines lo..hi, or inserts
// lines between them.
func (fc *fileChange) touches(lo, hi int) bool {
	for _, h := range fc.hunks {
		if h.oc == 0 {
			if h.os >= lo && h.os < hi {
				return true
			}
			continue
		}
		if h.os <= hi && h.os+h.oc-1 >= lo {
			return true
		}
	}
	return false
}

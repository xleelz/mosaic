package compose

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// The write scope (DESIGN §16.7). For templates that produce artifacts, an
// agent turn may write only the run's output directory and its artifact
// path. Executors restrict the agent's permissions to them (Turn.WriteScope);
// the engine also snapshots the repo before the turn and compares after it,
// so a write by any route (a shell command, say) fails the turn with reason
// write_scope.
//
// The snapshot skips .mosaic/ and .git/ at the repo root, the run store, and
// the scope itself. It compares each entry's type, size, mode and mtime.

type fileStamp struct {
	mode  fs.FileMode
	size  int64
	mtime int64
}

type repoSnapshot struct {
	root  string
	files map[string]fileStamp // by slash path relative to root
}

// snapshotRepo records every file, symlink and directory under root, except
// the excluded paths (absolute) and everything below them.
func snapshotRepo(root string, exclude []string) (*repoSnapshot, error) {
	root, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	skip := map[string]bool{filepath.Join(root, ".mosaic"): true, filepath.Join(root, ".git"): true}
	for _, e := range exclude {
		if a, err := filepath.Abs(e); err == nil {
			skip[a] = true
		}
	}
	snap := &repoSnapshot{root: root, files: map[string]fileStamp{}}
	err = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			if path == root {
				return err
			}
			return nil // vanished or unreadable: not ours to judge
		}
		if path == root {
			return nil
		}
		if skip[path] {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return nil
		}
		rel, _ := filepath.Rel(root, path)
		st := fileStamp{mode: info.Mode()}
		if !d.IsDir() { // a directory's mtime moves with its entries
			st.size, st.mtime = info.Size(), info.ModTime().UnixNano()
		}
		snap.files[filepath.ToSlash(rel)] = st
		return nil
	})
	if err != nil {
		return nil, err
	}
	return snap, nil
}

// changes lists the paths created, modified or removed since s, sorted, as
// "created x", "modified y" or "removed z".
func (s *repoSnapshot) changes(after *repoSnapshot) []string {
	var out []string
	for p, st := range after.files {
		old, ok := s.files[p]
		switch {
		case !ok:
			out = append(out, "created "+p)
		case old != st:
			out = append(out, "modified "+p)
		}
	}
	for p := range s.files {
		if _, ok := after.files[p]; !ok {
			out = append(out, "removed "+p)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		pi, pj := out[i][strings.IndexByte(out[i], ' ')+1:], out[j][strings.IndexByte(out[j], ' ')+1:]
		return pi < pj
	})
	return out
}

// writeScopeCheck snapshots the repo before a turn; its verify method
// reports what the turn changed outside the scope.
type writeScopeCheck struct {
	dir     string
	scope   []string
	exclude []string
	before  *repoSnapshot
}

// The scope paths are excluded from the snapshot, besides exclude.
func newWriteScopeCheck(dir string, scope, exclude []string) (*writeScopeCheck, error) {
	exclude = append(append([]string{}, scope...), exclude...)
	if dir == "" {
		wd, err := os.Getwd()
		if err != nil {
			return nil, err
		}
		dir = wd
	}
	before, err := snapshotRepo(dir, exclude)
	if err != nil {
		return nil, fmt.Errorf("write scope: snapshot of %s: %w", dir, err)
	}
	return &writeScopeCheck{dir: dir, scope: scope, exclude: exclude, before: before}, nil
}

// verify returns an error naming the changes outside the scope, or nil.
func (c *writeScopeCheck) verify() error {
	after, err := snapshotRepo(c.dir, c.exclude)
	if err != nil {
		return fmt.Errorf("write scope: snapshot of %s: %w", c.dir, err)
	}
	ch := c.before.changes(after)
	if len(ch) == 0 {
		return nil
	}
	const show = 10
	more := ""
	if len(ch) > show {
		more = fmt.Sprintf(" (and %d more)", len(ch)-show)
		ch = ch[:show]
	}
	return fmt.Errorf("%w: the turn %s%s in %s; it may write only %s", ErrWriteScope, strings.Join(ch, ", "), more, c.before.root, strings.Join(c.scope, " and "))
}

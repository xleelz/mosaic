package merge

// Staging (DESIGN §15.2): check --stage <fragment> validates and runs one
// fragment against the other fragments as they last passed. Each fragment's
// last-good copy lives in a snapshot directory (.mosaic/stage/ by default),
// at the fragment's path relative to the working directory, so a broken
// fragment fails its own staging and never blocks the others.

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// DefaultStageDir is the last-good snapshot directory, under the working
// directory (gitignored with the rest of .mosaic/).
const DefaultStageDir = ".mosaic/stage"

// Stage is a last-good snapshot directory.
type Stage struct {
	Dir string
}

// Path is where the last-good copy of a fragment lives: its path relative
// to the working directory under Dir, or, for a fragment outside it, its
// absolute path under Dir/_abs.
func (s Stage) Path(fragment string) string {
	abs, err := filepath.Abs(fragment)
	if err != nil {
		abs = filepath.Clean(fragment)
	}
	if wd, err := os.Getwd(); err == nil {
		if rel, err := filepath.Rel(wd, abs); err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return filepath.Join(s.Dir, rel)
		}
	}
	return filepath.Join(s.Dir, "_abs", strings.TrimPrefix(filepath.ToSlash(abs), "/"))
}

// StagedInput is where one input of a staged merge came from.
type StagedInput struct {
	Path     string // the -f path (the input's name)
	Staged   bool   // the fragment under staging: its working copy
	LastGood bool   // read from the snapshot; false: the working copy (no last-good yet)
}

// StagedLoad is the inputs of a staged merge and the staged fragment's bytes,
// which Accept records when the run passes.
type StagedLoad struct {
	Inputs  []Input
	From    []StagedInput
	Staged  string
	Content []byte
}

// LoadStaged reads the fragments for staging staged: its working copy, and
// each other path's last-good copy, or its working copy when it has none.
// Inputs keep their -f paths as names, so reports and origins don't change.
// staged must be one of paths.
func (s Stage) LoadStaged(paths []string, staged string) (*StagedLoad, error) {
	idx := -1
	for i, p := range paths {
		if samePath(p, staged) {
			idx = i
		}
	}
	if idx < 0 {
		return nil, fmt.Errorf("--stage %s is not one of the -f files", staged)
	}
	out := &StagedLoad{Staged: paths[idx]}
	for i, p := range paths {
		from := StagedInput{Path: p, Staged: i == idx}
		var data []byte
		var err error
		if i != idx {
			if data, err = os.ReadFile(s.Path(p)); err == nil {
				from.LastGood = true
			} else if !os.IsNotExist(err) {
				return nil, err
			}
		}
		if !from.LastGood {
			if data, err = os.ReadFile(p); err != nil {
				return nil, err
			}
		}
		if i == idx {
			out.Content = data
		}
		doc, err := model.ParseDocument(data)
		if err != nil {
			name := p
			if from.LastGood {
				name = p + " (last-good " + s.Path(p) + ")"
			}
			return nil, &ParseError{name, err}
		}
		out.Inputs = append(out.Inputs, Input{p, doc})
		out.From = append(out.From, from)
	}
	return out, nil
}

// Accept records the staged fragment's bytes, as they were loaded and run,
// as its last-good copy, and returns the snapshot path.
func (s Stage) Accept(l *StagedLoad) (string, error) {
	dst := s.Path(l.Staged)
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return "", err
	}
	tmp := dst + ".tmp"
	if err := os.WriteFile(tmp, l.Content, 0o644); err != nil {
		return "", err
	}
	return dst, os.Rename(tmp, dst)
}

func samePath(a, b string) bool {
	if filepath.Clean(a) == filepath.Clean(b) {
		return true
	}
	aa, err1 := filepath.Abs(a)
	bb, err2 := filepath.Abs(b)
	return err1 == nil && err2 == nil && aa == bb
}

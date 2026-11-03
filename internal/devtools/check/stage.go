package main

// Merge strictness and staging (DESIGN §15.2), kept apart from main.go:
// --strict-stubs, and --stage <fragment> with --accept over the last-good
// snapshot in .mosaic/stage/.

import (
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/xleelz/mosaic/internal/devtools/merge"
)

var (
	strictStubsFlag = flag.Bool("strict-stubs", false, "make stub-vs-stub disagreements (\"stubs disagree\") errors, naming both definitions")
	stageFlag       = flag.String("stage", "", "validate and run this -f fragment against the other -f fragments as they last passed (their last-good copies in --stage-dir, else their working copies)")
	acceptFlag      = flag.Bool("accept", false, "with --stage, record the staged fragment as last-good when the run passes")
	stageDirFlag    = flag.String("stage-dir", merge.DefaultStageDir, "with --stage, the last-good snapshot directory")
)

// stagedLoad is the staged merge's load, when --stage is given.
var stagedLoad *merge.StagedLoad

// loadInputs loads the -f files, or, under --stage, the staged fragment's
// working copy and the others' last-good copies.
func loadInputs(w io.Writer, paths []string) ([]merge.Input, error) {
	if *acceptFlag && *stageFlag == "" {
		fmt.Fprintln(os.Stderr, "check: --accept needs --stage")
		os.Exit(2)
	}
	if *stageFlag == "" {
		return merge.Load(paths)
	}
	st := merge.Stage{Dir: *stageDirFlag}
	l, err := st.LoadStaged(paths, *stageFlag)
	if err != nil {
		return nil, err
	}
	stagedLoad = l
	good, work := 0, 0
	for _, f := range l.From {
		switch {
		case f.Staged:
		case f.LastGood:
			good++
		default:
			work++
			fmt.Fprintf(w, "~ stage: %s has no last-good copy; using its working copy\n", f.Path)
		}
	}
	fmt.Fprintf(w, "stage: %s against %d last-good and %d working-copy fragments (%s)\n", l.Staged, good, work, *stageDirFlag)
	return l.Inputs, nil
}

// strictStubs prints the stub-vs-stub disagreements as errors under
// --strict-stubs and reports whether there were any. Without the flag it
// returns the disagreements for the warning report; with it, none.
func strictStubs(w io.Writer, disagreements []string) (warn []string, bad bool) {
	if !*strictStubsFlag {
		return disagreements, false
	}
	for _, d := range disagreements {
		fmt.Fprintf(w, "✗ stubs disagree (--strict-stubs): %s\n", d)
	}
	return nil, len(disagreements) > 0
}

// stageFinish reports the staged run and, under --accept, records a passing
// fragment as last-good.
func stageFinish(w io.Writer, passed bool) {
	if stagedLoad == nil {
		return
	}
	switch {
	case !passed:
		fmt.Fprintf(w, "✗ stage: %s failed; its last-good copy is unchanged\n", stagedLoad.Staged)
	case *acceptFlag:
		dst, err := merge.Stage{Dir: *stageDirFlag}.Accept(stagedLoad)
		if err != nil {
			fail(err)
		}
		fmt.Fprintf(w, "stage: %s passed; recorded as last-good (%s)\n", stagedLoad.Staged, dst)
	default:
		fmt.Fprintf(w, "stage: %s passed (not recorded; --accept records it)\n", stagedLoad.Staged)
	}
}

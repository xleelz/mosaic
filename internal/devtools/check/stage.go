package main

// Merge strictness and staging (DESIGN §15.2), kept apart from main.go:
// --strict-stubs, and --stage <fragment>[,<fragment>...] (repeatable) with
// --accept over the last-good snapshot in .mosaic/stage/.
//
// A joint stage runs several fragments' working copies together against
// everyone else's last-good copies, for changes that depend on each other
// (A's new copy needs B's, and B's needs A's). --accept records all of them,
// and only when the run passes. A failed run names, per staged fragment, the
// items of its own that failed, lists apart the failures in the non-staged
// last-good copies (stale peers), and suggests the stale peers whose working
// copy changes something a failure names.

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/devtools/merge"
	"github.com/xleelz/mosaic/internal/model"
)

// stageList is the repeatable, comma-separated --stage flag.
type stageList []string

func (s *stageList) String() string { return strings.Join(*s, ",") }
func (s *stageList) Set(v string) error {
	for _, p := range strings.Split(v, ",") {
		if p = strings.TrimSpace(p); p != "" {
			*s = append(*s, p)
		}
	}
	return nil
}

var (
	stageFlags      stageList
	strictStubsFlag = flag.Bool("strict-stubs", false, "make stub-vs-stub disagreements (\"stubs disagree\") errors, naming both definitions")
	acceptFlag      = flag.Bool("accept", false, "with --stage, record every staged fragment as last-good, only when the run passes")
	stageDirFlag    = flag.String("stage-dir", merge.DefaultStageDir, "with --stage, the last-good snapshot directory")
)

func init() {
	flag.Var(&stageFlags, "stage", "validate and run these -f fragments' working copies (repeatable, or comma-separated: a joint stage) against the other -f fragments as they last passed (their last-good copies in --stage-dir, else their working copies)")
}

// stagedFrom is where one input of a staged merge came from.
type stagedFrom struct {
	Path     string          // the -f path (the input's name)
	Staged   bool            // under staging: its working copy
	LastGood bool            // read from the snapshot; false: the working copy
	Stale    bool            // a last-good peer whose working copy differs
	Content  []byte          // the bytes loaded (what --accept records for a staged fragment)
	Work     *model.Document // a stale peer's working copy, when it parses
	WorkErr  error           // a stale peer's working copy's parse error
	Good     *model.Document // the document loaded
}

// jointLoad is a staged merge's inputs and where each came from.
type jointLoad struct {
	Dir    string
	Inputs []merge.Input
	From   []stagedFrom
}

// staged lists the staged fragments' -f paths.
func (l *jointLoad) staged() []string {
	var out []string
	for _, f := range l.From {
		if f.Staged {
			out = append(out, f.Path)
		}
	}
	return out
}

// loadJoint reads the fragments for staging every path in staged: their
// working copies, and each other path's last-good copy in dir, or its
// working copy when it has none. Each staged path must be one of paths.
func loadJoint(dir string, paths, staged []string) (*jointLoad, error) {
	st := merge.Stage{Dir: dir}
	isStaged := make([]bool, len(paths))
	for _, s := range staged {
		found := false
		for i, p := range paths {
			if samePathCheck(p, s) {
				isStaged[i], found = true, true
			}
		}
		if !found {
			return nil, fmt.Errorf("--stage %s is not one of the -f files", s)
		}
	}
	l := &jointLoad{Dir: dir}
	for i, p := range paths {
		from := stagedFrom{Path: p, Staged: isStaged[i]}
		var data []byte
		var err error
		if !from.Staged {
			if data, err = os.ReadFile(st.Path(p)); err == nil {
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
		from.Content = data
		doc, err := model.ParseDocument(data)
		if err != nil {
			name := p
			if from.LastGood {
				name = p + " (last-good " + st.Path(p) + ")"
			}
			return nil, &merge.ParseError{Path: name, Err: err}
		}
		from.Good = doc
		if from.LastGood {
			if work, err := os.ReadFile(p); err == nil && !bytes.Equal(work, data) {
				from.Stale = true
				from.Work, from.WorkErr = model.ParseDocument(work)
			}
		}
		l.Inputs = append(l.Inputs, merge.Input{Name: p, Doc: doc})
		l.From = append(l.From, from)
	}
	return l, nil
}

// accept records every staged fragment's bytes, as they were loaded and run,
// as its last-good copy: all are written aside first, then renamed into
// place, so a write failure records none. It returns the snapshot paths.
func (l *jointLoad) accept() ([]string, error) {
	st := merge.Stage{Dir: l.Dir}
	var dsts, tmps []string
	for _, f := range l.From {
		if !f.Staged {
			continue
		}
		dst := st.Path(f.Path)
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return nil, err
		}
		tmp := dst + ".tmp"
		if err := os.WriteFile(tmp, f.Content, 0o644); err != nil {
			for _, t := range tmps {
				os.Remove(t)
			}
			return nil, err
		}
		dsts, tmps = append(dsts, dst), append(tmps, tmp)
	}
	for i := range dsts {
		if err := os.Rename(tmps[i], dsts[i]); err != nil {
			return dsts[:i], err
		}
	}
	return dsts, nil
}

func samePathCheck(a, b string) bool {
	if filepath.Clean(a) == filepath.Clean(b) {
		return true
	}
	aa, err1 := filepath.Abs(a)
	bb, err2 := filepath.Abs(b)
	return err1 == nil && err2 == nil && aa == bb
}

// stagedLoad is the staged merge's load, when --stage is given.
var stagedLoad *jointLoad

// loadInputs loads the -f files, or, under --stage, the staged fragments'
// working copies and the others' last-good copies.
func loadInputs(w io.Writer, paths []string) ([]merge.Input, error) {
	if *acceptFlag && len(stageFlags) == 0 {
		fmt.Fprintln(os.Stderr, "check: --accept needs --stage")
		os.Exit(2)
	}
	if len(stageFlags) == 0 {
		return merge.Load(paths)
	}
	l, err := loadJoint(*stageDirFlag, paths, stageFlags)
	if err != nil {
		return nil, err
	}
	stagedLoad = l
	good, work, stale := 0, 0, 0
	for _, f := range l.From {
		switch {
		case f.Staged:
		case f.LastGood:
			good++
			if f.Stale {
				stale++
			}
		default:
			work++
			fmt.Fprintf(w, "~ stage: %s has no last-good copy; using its working copy\n", f.Path)
		}
	}
	fmt.Fprintf(w, "stage: %s against %d last-good (%d stale: working copy differs) and %d working-copy fragments (%s)\n",
		strings.Join(l.staged(), ", "), good, stale, work, l.Dir)
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

// stageFailures is what a staged run's failure report attributes: the merge
// conflicts, validation issues and failing scenarios, with the merged
// document and origins to find each item's fragment.
type stageFailures struct {
	Conflicts []string
	Issues    []model.Issue
	Scenarios []string // failing scenario ids
	Origins   map[string]string
	Doc       *model.Document
}

// stageItem is one attributed failure.
type stageItem struct {
	Text string
	Key  string   // "<kind>/<id>" of the failing item, when known
	Refs []string // ids the failure names (quoted ids; a scenario's strings)
}

// stageReport groups a failed staged run's items by fragment.
type stageReport struct {
	ByFragment   map[string][]stageItem // -f path -> its items
	Unattributed []stageItem
	Suggest      map[string][]string // stale peer -> what its working copy changes that failures involve: "<kind> <id>" (a failing item) or "\"<id>\"" (an id a failure names)
}

var (
	issueEntity = regexp.MustCompile(`^(components|interfaces|links|schemas|flows|scenarios|configs|fixtures)\[([^\]]+)\]`)
	quotedID    = regexp.MustCompile(`"([^"\s]+)"`)
)

var pluralKind = map[string]string{
	"components": model.KindComponent, "interfaces": model.KindInterface, "links": model.KindLink,
	"schemas": model.KindSchema, "flows": model.KindFlow, "scenarios": model.KindScenario,
	"configs": model.KindConfig, "fixtures": model.KindFixture,
}

func quotedIDs(s string) []string {
	var out []string
	for _, m := range quotedID.FindAllStringSubmatch(s, -1) {
		out = append(out, m[1])
	}
	return out
}

// stringsOf collects every string value in v's JSON form.
func stringsOf(v any) []string {
	b, err := json.Marshal(v)
	if err != nil {
		return nil
	}
	var x any
	if json.Unmarshal(b, &x) != nil {
		return nil
	}
	var out []string
	var walk func(any)
	walk = func(x any) {
		switch t := x.(type) {
		case string:
			out = append(out, t)
		case []any:
			for _, e := range t {
				walk(e)
			}
		case map[string]any:
			for _, e := range t {
				walk(e)
			}
		}
	}
	walk(x)
	return out
}

// specs maps "<kind>/<id>" to the entity's JSON spec.
func specs(d *model.Document) map[string]string {
	out := map[string]string{}
	if d == nil {
		return out
	}
	ents, err := d.Entities()
	if err != nil {
		return out
	}
	for _, e := range ents {
		out[e.Kind+"/"+e.ID] = string(e.Spec)
	}
	return out
}

// changed lists a stale peer's entity keys whose working copy differs from
// its last-good copy (added, removed or changed), and the ids among them.
func changed(f stagedFrom) (keys, ids map[string]bool) {
	keys, ids = map[string]bool{}, map[string]bool{}
	good, work := specs(f.Good), specs(f.Work)
	mark := func(k string) {
		keys[k] = true
		if i := strings.IndexByte(k, '/'); i >= 0 {
			ids[k[i+1:]] = true
		}
	}
	for k, v := range good {
		if work[k] != v {
			mark(k)
		}
	}
	for k := range work {
		if _, ok := good[k]; !ok {
			mark(k)
		}
	}
	return keys, ids
}

// attribute groups a failed staged run's items by fragment and suggests the
// stale peers whose working copy changes an item that fails or an id a
// failure names.
func attribute(l *jointLoad, sf stageFailures) *stageReport {
	r := &stageReport{ByFragment: map[string][]stageItem{}, Suggest: map[string][]string{}}
	add := func(frag string, it stageItem) {
		if frag == "" {
			r.Unattributed = append(r.Unattributed, it)
			return
		}
		r.ByFragment[frag] = append(r.ByFragment[frag], it)
	}
	for _, c := range sf.Conflicts {
		it := stageItem{Text: "conflict: " + c, Refs: quotedIDs(c)}
		var staged, peers []string
		for _, f := range l.From {
			if strings.Contains(c, f.Path) {
				if f.Staged {
					staged = append(staged, f.Path)
				} else {
					peers = append(peers, f.Path)
				}
			}
		}
		switch {
		case len(staged) > 0:
			for _, p := range staged {
				add(p, it)
			}
		case len(peers) > 0:
			for _, p := range peers {
				add(p, it)
			}
		default:
			add("", it)
		}
	}
	for _, is := range sf.Issues {
		if is.Severity != model.SeverityError {
			continue
		}
		it := stageItem{Text: is.Path + ": " + is.Message, Refs: quotedIDs(is.Message)}
		frag := ""
		if m := issueEntity.FindStringSubmatch(is.Path); m != nil {
			it.Key = pluralKind[m[1]] + "/" + m[2]
			frag = sf.Origins[it.Key]
		}
		add(frag, it)
	}
	for _, id := range sf.Scenarios {
		it := stageItem{Text: "scenario " + id, Key: model.KindScenario + "/" + id}
		if sf.Doc != nil {
			for i := range sf.Doc.Scenarios {
				if sf.Doc.Scenarios[i].ID == id {
					it.Refs = append(it.Refs, stringsOf(sf.Doc.Scenarios[i])...)
				}
			}
		}
		add(sf.Origins[it.Key], it)
	}

	// Suggestions: a stale peer whose working copy changes the failing item
	// or an id some failure names.
	for _, f := range l.From {
		if !f.Stale || f.Work == nil {
			continue
		}
		keys, ids := changed(f)
		seen := map[string]bool{}
		note := func(why string) {
			if !seen[why] {
				seen[why] = true
				r.Suggest[f.Path] = append(r.Suggest[f.Path], why)
			}
		}
		check := func(it stageItem) {
			if it.Key != "" && keys[it.Key] {
				note(strings.Replace(it.Key, "/", " ", 1))
			}
			for _, ref := range it.Refs {
				if ids[ref] && !strings.HasSuffix(it.Key, "/"+ref) {
					note(fmt.Sprintf("%q", ref))
				}
			}
		}
		for _, items := range r.ByFragment {
			for _, it := range items {
				check(it)
			}
		}
		for _, it := range r.Unattributed {
			check(it)
		}
		sort.Strings(r.Suggest[f.Path])
	}
	return r
}

// print writes the failure report: the staged fragments' items, then the
// stale peers' and other non-staged fragments', then the suggestions.
func (r *stageReport) print(w io.Writer, l *jointLoad) {
	staged := l.staged()
	fmt.Fprintf(w, "✗ stage: %s failed; no last-good copy changed\n", strings.Join(staged, ", "))
	attributed := 0
	for _, f := range l.From {
		items := r.ByFragment[f.Path]
		if len(items) == 0 {
			continue
		}
		attributed += len(items)
		var label string
		switch {
		case f.Staged:
			label = "staged " + f.Path + " (working copy)"
		case f.Stale:
			label = "stale peer " + f.Path + " (last-good copy; its working copy differs)"
		case f.LastGood:
			label = "peer " + f.Path + " (last-good copy)"
		default:
			label = "peer " + f.Path + " (working copy; no last-good)"
		}
		fmt.Fprintf(w, "  %s: %d failing\n", label, len(items))
		printItems(w, items)
	}
	if len(r.Unattributed) > 0 {
		fmt.Fprintf(w, "  no fragment (imports or document-wide): %d failing\n", len(r.Unattributed))
		printItems(w, r.Unattributed)
	}
	if attributed == 0 && len(r.Unattributed) == 0 {
		fmt.Fprintln(w, "  the failures above are gate findings (citations, coverage, lints), not attributed to a fragment")
	}
	var peers []string
	for p := range r.Suggest {
		peers = append(peers, p)
	}
	sort.Strings(peers)
	for _, p := range peers {
		whys := r.Suggest[p]
		more := ""
		if len(whys) > stageShowReasons {
			more = fmt.Sprintf(" and %d more", len(whys)-stageShowReasons)
			whys = whys[:stageShowReasons]
		}
		fmt.Fprintf(w, "  ~ suggest staging %s too: its working copy changes %s%s, which failures involve\n", p, strings.Join(whys, ", "), more)
	}
	if len(peers) > 0 {
		fmt.Fprintf(w, "  ~ try: --stage %s\n", strings.Join(append(append([]string(nil), staged...), peers...), ","))
	}
}

// The failure report lists this many items per fragment, and this many
// reasons per suggested peer; every failure is printed in full above it.
const (
	stageShowItems   = 10
	stageShowReasons = 3
)

func printItems(w io.Writer, items []stageItem) {
	for i, it := range items {
		if i == stageShowItems {
			fmt.Fprintf(w, "    ... and %d more (printed above)\n", len(items)-i)
			break
		}
		fmt.Fprintf(w, "    ✗ %s\n", it.Text)
	}
}

// stageFinish reports the staged run and, under --accept, records every
// staged fragment as last-good when the run passed. A failed run is
// attributed per fragment (stageReport).
func stageFinish(w io.Writer, passed bool, sf stageFailures) {
	if stagedLoad == nil {
		return
	}
	names := strings.Join(stagedLoad.staged(), ", ")
	switch {
	case !passed:
		attribute(stagedLoad, sf).print(w, stagedLoad)
	case *acceptFlag:
		dsts, err := stagedLoad.accept()
		if err != nil {
			fail(err)
		}
		fmt.Fprintf(w, "stage: %s passed; recorded as last-good (%s)\n", names, strings.Join(dsts, ", "))
	default:
		fmt.Fprintf(w, "stage: %s passed (not recorded; --accept records it)\n", names)
	}
}

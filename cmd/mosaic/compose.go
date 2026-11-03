package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"strings"

	"sigs.k8s.io/yaml"

	"github.com/xleelz/mosaic/internal/compose"
)

// composeCommands are the local workflow emulator's commands (DESIGN §14.11).
func composeCommands() []*command {
	return []*command{
		{name: "compose validate", synopsis: "compose validate <template> [--format text|json]", run: cmdComposeValidate,
			help: `Check a workflow template, listing every error with its path. Subworkflow templates are
resolved by id from the template's directory. Exits 1 when invalid.`},
		{name: "compose simulate", synopsis: "compose simulate <template> --scenario FILE [--runs DIR] [--format text|json]", run: cmdComposeSimulate,
			help: `Run a template with the script executor: turn outputs, command results, list widths and
detached children come from the scenario file. Commands are not executed. Prints the run tree
with change requests and budget refusals. Runs go to a temporary store unless --runs is given.
Exits 1 when the root run does not finish done.`},
		{name: "compose run", synopsis: "compose run <template> [--input name=@file]... [--id T] [--parent T] [--from-parent in=artifact]... [--executor claude|script] [--max-parallel N]", run: cmdComposeRun,
			help: `Admit and run a task, or continue it: re-running an existing task id resumes its unfinished
stages (interrupt with Ctrl-C at any time). --parent admits a detached child of an existing
task in any state; --from-parent binds a parent artifact as an input. --input takes a JSON or
YAML file (name=@file) or a literal (JSON, else a string). Prints the run tree. Exits 1 when
the run does not finish done.`},
		{name: "compose tree", synopsis: "compose tree <task> [--stats] [--runs DIR] [--format text|json]", run: cmdComposeTree,
			help: `Print the run tree containing a task: states, depths, change requests and budget refusals.
--stats adds each stage's wall time (from the events) and its agent sessions' turns, duration
and cost (from turns/*.meta.json), per run and for the tree; fanout branches roll up under
their stage. Runs without meta files show wall time only.`},
		{name: "compose requests", synopsis: "compose requests <task> [--runs DIR]", run: cmdComposeRequests,
			help: "List the change requests addressed to a task, as JSON."},
	}
}

// composeList is a repeatable string flag.
type composeList []string

func (l *composeList) String() string     { return strings.Join(*l, ",") }
func (l *composeList) Set(s string) error { *l = append(*l, s); return nil }

type composeFlags struct {
	runs, dir, format string
}

func (f *composeFlags) register(fs *flag.FlagSet) {
	fs.StringVar(&f.dir, "dir", "", "repo root `DIR`, the working directory of turns and commands (default: current directory)")
	fs.StringVar(&f.runs, "runs", "", "run store `DIR` (default: <dir>/"+compose.DefaultRoot+")")
	fs.StringVar(&f.format, "format", "text", "output `FORMAT`: text or json")
}

func (f *composeFlags) resolve() error {
	if f.format != "text" && f.format != "json" {
		return usageErrorf("--format must be text or json")
	}
	if f.dir == "" {
		wd, err := os.Getwd()
		if err != nil {
			return err
		}
		f.dir = wd
	}
	if f.runs == "" {
		f.runs = filepath.Join(f.dir, compose.DefaultRoot)
	}
	return nil
}

// loadComposeTemplate parses and validates a template, resolving
// subworkflows from its directory.
func loadComposeTemplate(path string) (*compose.Template, compose.Resolver, error) {
	tpl, err := compose.LoadFile(path)
	var ve *compose.ValidationError
	if errors.As(err, &ve) {
		return nil, nil, &exitError{code: exitRefused, msg: ve.Error()}
	}
	if err != nil {
		return nil, nil, inputErrorf("%v", err)
	}
	resolve := compose.DirResolver(filepath.Dir(path), tpl)
	if err := compose.Validate(tpl, resolve); err != nil {
		return nil, nil, &exitError{code: exitRefused, msg: err.Error()}
	}
	return tpl, resolve, nil
}

func cmdComposeValidate(e *env, c *command, args []string) error {
	fs := e.flags(c)
	format := fs.String("format", "text", "output `FORMAT`: text or json")
	pos, err := e.parse(fs, args, 1, 1, "<template>")
	if err != nil {
		return err
	}
	tpl, err := compose.LoadFile(pos[0])
	var ve *compose.ValidationError
	if err != nil && !errors.As(err, &ve) {
		return inputErrorf("%v", err)
	}
	if ve == nil {
		if verr := compose.Validate(tpl, compose.DirResolver(filepath.Dir(pos[0]), tpl)); verr != nil {
			errors.As(verr, &ve)
		}
	}
	var errs []compose.Error
	if ve != nil {
		errs = ve.Errors
	}
	if *format == "json" {
		if errs == nil {
			errs = []compose.Error{}
		}
		if err := printJSON(e.stdout, map[string]any{"template": pos[0], "valid": len(errs) == 0, "errors": errs}); err != nil {
			return err
		}
	} else if len(errs) == 0 {
		fmt.Fprintf(e.stdout, "%s: valid (workflow %s, %d stages)\n", pos[0], tpl.ID, len(tpl.Stages))
	} else {
		fmt.Fprintf(e.stdout, "%s: %d error(s)\n", pos[0], len(errs))
		for _, x := range errs {
			fmt.Fprintf(e.stdout, "  %s\n", x)
		}
	}
	if len(errs) > 0 {
		return &exitError{code: exitRefused}
	}
	return nil
}

func cmdComposeSimulate(e *env, c *command, args []string) error {
	fs := e.flags(c)
	var cf composeFlags
	cf.register(fs)
	scenario := fs.String("scenario", "", "scenario `FILE` (YAML or JSON)")
	maxPar := fs.Int("max-parallel", 0, "bound on concurrent turns `N` (0: unbounded)")
	pos, err := e.parse(fs, args, 1, 1, "<template>")
	if err != nil {
		return err
	}
	if *scenario == "" {
		return usageErrorf("--scenario is required")
	}
	tempStore := cf.runs == ""
	if err := cf.resolve(); err != nil {
		return err
	}
	if tempStore {
		dir, err := os.MkdirTemp("", "mosaic-compose-sim-*")
		if err != nil {
			return err
		}
		defer os.RemoveAll(dir)
		cf.runs = dir
	}
	tpl, resolve, err := loadComposeTemplate(pos[0])
	if err != nil {
		return err
	}
	sc, err := compose.LoadScenario(*scenario)
	if err != nil {
		return inputErrorf("%v", err)
	}
	r := &compose.Runner{Store: compose.NewStore(cf.runs), Executor: compose.NewScriptExecutor(sc), Resolve: resolve,
		Dir: cf.dir, MaxParallel: *maxPar, DryCommands: true}
	id := sc.ID
	if id == "" {
		id = "sim"
	}
	root, err := r.Run(e.ctx, compose.Admission{Template: tpl, ID: id, Inputs: sc.Inputs})
	if err != nil {
		return composeRunError(err)
	}
	for i, d := range sc.Detached {
		dt := tpl
		if d.Template != "" {
			if dt, err = resolve(d.Template); err != nil {
				return inputErrorf("detached[%d]: %v", i, err)
			}
		}
		if _, err := r.Run(e.ctx, compose.Admission{Template: dt, ID: d.ID, Inputs: d.Inputs, Parent: d.Parent, FromParent: d.FromParent}); err != nil {
			var ae *compose.AdmissionError
			if !errors.As(err, &ae) {
				return composeRunError(err)
			}
			fmt.Fprintf(e.stderr, "detached[%d] refused: %v\n", i, err)
		}
	}
	if err := composePrintTree(e, r.Store, root.ID, cf.format); err != nil {
		return err
	}
	if root.State != compose.StateDone {
		return &exitError{code: exitRefused, msg: fmt.Sprintf("root %s %s (%s): %s", root.ID, root.State, root.Reason, root.Error)}
	}
	return nil
}

func cmdComposeRun(e *env, c *command, args []string) error {
	fs := e.flags(c)
	var cf composeFlags
	cf.register(fs)
	var inputs, fromParent composeList
	fs.Var(&inputs, "input", "workflow input `name=@file` or name=value (repeatable)")
	fs.Var(&fromParent, "from-parent", "bind a parent artifact as an input: `in=artifact` (repeatable)")
	id := fs.String("id", "", "task `ID`: resumes it when it exists (default: generated)")
	parent := fs.String("parent", "", "admit a detached child of task `T`")
	executor := fs.String("executor", "claude", "executor `NAME`: claude or script")
	scenario := fs.String("scenario", "", "scenario `FILE` for the script executor")
	maxPar := fs.Int("max-parallel", 4, "bound on concurrent turns and commands `N` (0: unbounded)")
	pos, err := e.parse(fs, args, 1, 1, "<template>")
	if err != nil {
		return err
	}
	if err := cf.resolve(); err != nil {
		return err
	}
	tpl, resolve, err := loadComposeTemplate(pos[0])
	if err != nil {
		return err
	}
	in := map[string]json.RawMessage{}
	for _, s := range inputs {
		name, val, ok := strings.Cut(s, "=")
		if !ok || name == "" {
			return usageErrorf("--input %q: want name=@file or name=value", s)
		}
		raw, err := composeInputValue(val)
		if err != nil {
			return inputErrorf("--input %s: %v", name, err)
		}
		in[name] = raw
	}
	fp := map[string]string{}
	for _, s := range fromParent {
		name, art, ok := strings.Cut(s, "=")
		if !ok || name == "" || art == "" {
			return usageErrorf("--from-parent %q: want in=artifact", s)
		}
		fp[name] = art
	}
	if len(fp) > 0 && *parent == "" {
		return usageErrorf("--from-parent needs --parent")
	}
	var ex compose.Executor
	if *executor == "script" {
		sc := &compose.Scenario{}
		if *scenario != "" {
			if sc, err = compose.LoadScenario(*scenario); err != nil {
				return inputErrorf("%v", err)
			}
		}
		ex = compose.NewScriptExecutor(sc)
	} else {
		var ok bool
		if ex, ok = compose.Lookup(*executor); !ok {
			return usageErrorf("unknown executor %q (registered: %s, script)", *executor, strings.Join(compose.Executors(), ", "))
		}
	}
	ctx, stop := signal.NotifyContext(e.ctx, os.Interrupt)
	defer stop()
	r := &compose.Runner{Store: compose.NewStore(cf.runs), Executor: ex, Resolve: resolve, Dir: cf.dir, MaxParallel: *maxPar}
	rec, err := r.Run(ctx, compose.Admission{Template: tpl, ID: *id, Inputs: in, Parent: *parent, FromParent: fp})
	if err != nil && !errors.Is(err, context.Canceled) {
		return composeRunError(err)
	}
	if cf.format == "json" {
		if err := printJSON(e.stdout, rec); err != nil {
			return err
		}
	} else if err := composePrintTree(e, r.Store, rec.ID, "text"); err != nil {
		return err
	}
	switch rec.State {
	case compose.StateDone:
		return nil
	case compose.StateInterrupted:
		return &exitError{code: exitRefused, msg: fmt.Sprintf("task %s interrupted; run again with --id %s to continue", rec.ID, rec.ID)}
	}
	return &exitError{code: exitRefused, msg: fmt.Sprintf("task %s %s (%s): %s", rec.ID, rec.State, rec.Reason, rec.Error)}
}

func composeInputValue(val string) (json.RawMessage, error) {
	if file, ok := strings.CutPrefix(val, "@"); ok {
		data, err := os.ReadFile(file)
		if err != nil {
			return nil, err
		}
		js, err := yaml.YAMLToJSON(data)
		if err != nil {
			return nil, err
		}
		return js, nil
	}
	if json.Valid([]byte(val)) {
		return json.RawMessage(val), nil
	}
	return json.Marshal(val)
}

func composeRunError(err error) error {
	var ae *compose.AdmissionError
	if errors.As(err, &ae) {
		msg := "admission refused (" + ae.Reason + "):"
		for _, x := range ae.Errors {
			msg += "\n  " + x
		}
		return &exitError{code: exitRefused, msg: msg}
	}
	return err
}

func composePrintTree(e *env, store *compose.Store, task, format string, stats ...bool) error {
	tree, err := compose.ReadTree(store, task)
	if err != nil {
		if errors.Is(err, compose.ErrNotFound) {
			return &exitError{code: exitRefused, msg: err.Error()}
		}
		return err
	}
	if len(stats) > 0 && stats[0] {
		if err := tree.AddStats(store); err != nil {
			return err
		}
	}
	if format == "json" {
		return printJSON(e.stdout, tree)
	}
	tree.WriteText(e.stdout)
	return nil
}

func cmdComposeTree(e *env, c *command, args []string) error {
	fs := e.flags(c)
	var cf composeFlags
	cf.register(fs)
	stats := fs.Bool("stats", false, "add wall time and agent stats per stage, run and tree")
	pos, err := e.parse(fs, args, 1, 1, "<task>")
	if err != nil {
		return err
	}
	if err := cf.resolve(); err != nil {
		return err
	}
	return composePrintTree(e, compose.NewStore(cf.runs), pos[0], cf.format, *stats)
}

func cmdComposeRequests(e *env, c *command, args []string) error {
	fs := e.flags(c)
	var cf composeFlags
	cf.register(fs)
	pos, err := e.parse(fs, args, 1, 1, "<task>")
	if err != nil {
		return err
	}
	if err := cf.resolve(); err != nil {
		return err
	}
	store := compose.NewStore(cf.runs)
	if !store.Exists(pos[0]) {
		return &exitError{code: exitRefused, msg: fmt.Sprintf("no such task: %s", pos[0])}
	}
	reqs, err := store.Requests(pos[0])
	if err != nil {
		return err
	}
	if reqs == nil {
		reqs = []*compose.ChangeRequest{}
	}
	return printJSON(e.stdout, reqs)
}

// Command inventory lists a codebase's entry points heuristically, so that an
// ontology's coverage of them can be measured with the check tool's
// --inventory flag.
//
//	go run ./internal/devtools/inventory --code DIR [--out inventory.json] [--include-test-support] [--lang auto|go,ts,python,java,ts-frontend,python-gpu]
//	    [--kinds go-func,py-func,ts-func [--include-test-funcs]] [--paths FILE|DIR,...]
//
// Heuristics (each entry records the one that found it in "via"):
//
//   - Go HTTP routes: net/http HandleFunc/Handle (including Go 1.22 "METHOD /path"
//     patterns), chi/gin/echo r.Get("/p", h) style calls, chi Route prefixes,
//     gorilla .Methods, httprouter, and oapi-codegen "// (GET /path)" comments
//     in *.gen.go files.
//
//   - Temporal: RegisterWorkflow[WithOptions], ExecuteChildWorkflow, exported
//     *Workflow functions taking workflow.Context; RegisterActivity (functions,
//     or every exported context-taking method of a registered struct) and
//     ExecuteActivity references.
//
//   - Crons: time.NewTicker/time.Tick, unconditional for-loops that sleep,
//     robfig AddFunc, Temporal CronSchedule, terraform schedule expressions,
//     Kubernetes CronJobs and GitHub Actions schedules.
//
//   - CLI: cobra.Command literals, flag.Parse in package main, flag.NewFlagSet
//     and switch os.Args[1] subcommands.
//
//   - TS: Next.js app/**/route.ts exported handlers, pages/api files, tRPC
//     procedures.
//
//   - Python: __main__ guards, argparse add_parser, click/typer commands and
//     pyproject scripts.
//
//   - Java (token-level parse with comments stripped; supertypes resolved
//     across the repository): messaging Verb enum constants and their
//     handlers, IVerbHandler.doVerb implementations and handler lambdas,
//     native-protocol Message.Request.execute, CQLStatement implementations,
//     airline @Command classes (named after the Cli.builder that registers
//     them), *MBean/*MXBean interface methods, scheduleWithFixedDelay /
//     scheduleAtFixedRate / scheduleSelfRecurring call sites, infiniteLoop
//     threads, Stage.X.execute/submit hand-offs and static main methods
//     (with the bin/ scripts that launch them). *Test.java, examples, docs
//     and generated sources are skipped.
//
//   - ts-frontend plugin (VS Code style front ends; tsfront.go): Action2,
//     CommandsRegistry, keybinding-rule and editor commands (ids resolved
//     through string constants), workbench and editor contributions,
//     extension points, createDecorator services with their registerSingleton
//     implementations, registerChannel IPC channels, extHost.protocol.ts RPC
//     shapes and @extHostNamedCustomer classes, vscode.d.ts namespace
//     functions, built-in extensions' package.json commands and activation
//     events, process main files and clap subcommands of a Rust cli/.
//
//   - python-gpu plugin (Python serving engines with C++/CUDA/Triton;
//     pygpu.go): FastAPI routes, CLISubcommand classes, the engine classes'
//     public API, collective_rpc / call_utility targets, busy and step loops,
//     TORCH_LIBRARY op schemas, Python-registered ops and wrappers of
//     torch.ops._C*, CUDA __global__ kernels, @triton.jit kernels, model
//     registry tables and plugin entry points and groups.
//
// Opt-in kinds, for logic-level scopes (funcs.go; --kinds): go-func (go/ast:
// top-level functions and methods, named Type.Method), py-func (module-level
// functions and class methods, named Class.method) and ts-func (top-level
// functions, const arrow functions and class methods). Each spans the
// declaration (line to end_line) and carries "exported"; functions of test
// files are listed, flagged "test", only with --include-test-funcs.
//
// --paths keeps only the entries in the given files or directories (relative
// to --code), such as a refinement scope's paths; the rest of the root is
// still scanned so cross-file registrations resolve.
//
// --lang limits the language scanners; the default, auto, runs each on the
// files it recognizes, and turns a plugin on only when the root carries its
// markers (src/vs for ts-frontend; csrc/ or a torch build for python-gpu).
//
// Tests, vendored code and, unless asked, test-support directories (mocks,
// fakes, e2e, fixtures) are skipped. Secret files are never opened.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
)

// Inventory is the file format the check tool reads.
type Inventory struct {
	Root    string         `json:"root"`
	Counts  map[string]int `json:"counts"`
	Entries []Entry        `json:"entries"`
}

func main() {
	code := flag.String("code", "", "code root to scan (required)")
	out := flag.String("out", "", "write the inventory as JSON (default: stdout)")
	ts := flag.Bool("include-test-support", false, "keep mocks, fakes, e2e harnesses and fixtures")
	lang := flag.String("lang", "auto", "auto, or a comma-separated subset of "+strings.Join(Langs, ","))
	kinds := flag.String("kinds", "", "opt-in kinds, comma-separated: "+strings.Join(OptKinds, ","))
	testFuncs := flag.Bool("include-test-funcs", false, "with --kinds, also list test files' functions, flagged test")
	paths := flag.String("paths", "", "comma-separated files or directories (relative to --code) to keep entries from")
	flag.Parse()
	if *code == "" {
		fmt.Fprintln(os.Stderr, "usage: inventory --code DIR [--out inventory.json] [--lang auto|"+strings.Join(Langs, ",")+"]")
		os.Exit(2)
	}
	opt := Options{IncludeTestSupport: *ts, IncludeTestFuncs: *testFuncs}
	for _, k := range strings.Split(*kinds, ",") {
		if k = strings.TrimSpace(k); k == "" {
			continue
		}
		if !slices.Contains(OptKinds, k) {
			fmt.Fprintf(os.Stderr, "inventory: unknown --kinds %q (want %s)\n", k, strings.Join(OptKinds, ","))
			os.Exit(2)
		}
		opt.Kinds = append(opt.Kinds, k)
	}
	for _, p := range strings.Split(*paths, ",") {
		if p = strings.TrimSpace(p); p != "" {
			opt.Paths = append(opt.Paths, p)
		}
	}
	if *lang != "auto" && *lang != "" {
		for _, l := range strings.Split(*lang, ",") {
			l = strings.TrimSpace(l)
			if !slices.Contains(Langs, l) {
				fmt.Fprintf(os.Stderr, "inventory: unknown --lang %q (want auto or %s)\n", l, strings.Join(Langs, ","))
				os.Exit(2)
			}
			opt.Langs = append(opt.Langs, l)
		}
	}
	entries, err := Scan(*code, opt)
	if err != nil {
		fmt.Fprintln(os.Stderr, "inventory:", err)
		os.Exit(2)
	}
	inv := Inventory{Root: filepath.Clean(*code), Counts: map[string]int{}, Entries: entries}
	for _, e := range entries {
		inv.Counts[e.Kind]++
	}
	b, _ := json.MarshalIndent(inv, "", "  ")
	b = append(b, '\n')
	if *out == "" {
		os.Stdout.Write(b)
		return
	}
	if err := os.WriteFile(*out, b, 0o644); err != nil {
		fmt.Fprintln(os.Stderr, "inventory:", err)
		os.Exit(2)
	}
	names := make([]string, 0, len(inv.Counts))
	for k := range inv.Counts {
		names = append(names, k)
	}
	sort.Strings(names)
	fmt.Printf("inventory: %d entries\n", len(entries))
	for _, k := range names {
		fmt.Printf("  %-18s %d\n", k, inv.Counts[k])
	}
}

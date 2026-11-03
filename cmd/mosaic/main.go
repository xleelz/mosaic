// Command mosaic is the agent CLI of mosaicd (docs/DESIGN.md §7). It prints
// indented JSON by default so agents can parse it.
//
// Exit codes: 0 success; 1 refusal, validation failure or failed test;
// 2 usage error; 3 server unreachable.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/client"
)

const defaultServer = "http://127.0.0.1:7878"

// Exit codes.
const (
	exitOK          = 0
	exitRefused     = 1
	exitUsage       = 2
	exitUnreachable = 3
)

// getenv is replaced by tests.
var getenv = os.Getenv

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

// env is the state shared by one invocation.
type env struct {
	ctx            context.Context
	stdout, stderr io.Writer
	server, token  string
	fs             *flag.FlagSet // the running command's flags, for --help
}

// command is one CLI command. Group commands ("ontology list") have a
// two-word name.
type command struct {
	name     string
	synopsis string // after "mosaic "
	help     string
	run      func(e *env, c *command, args []string) error
}

// Errors that pick an exit code.

type usageError struct{ msg string }

func (e *usageError) Error() string { return e.msg }

func usageErrorf(format string, a ...any) error { return &usageError{fmt.Sprintf(format, a...)} }

// inputError is bad local input (a missing file, invalid YAML): exit 2.
type inputError struct{ msg string }

func (e *inputError) Error() string { return e.msg }

func inputErrorf(format string, a ...any) error { return &inputError{fmt.Sprintf(format, a...)} }

// exitError ends a command whose output is already printed with a code, an
// optional message and issues.
type exitError struct {
	code   int
	msg    string
	issues []model.Issue
}

func (e *exitError) Error() string { return e.msg }

func run(args []string, stdout, stderr io.Writer) int {
	e := &env{ctx: context.Background(), stdout: stdout, stderr: stderr, server: getenv("MOSAIC_SERVER"), token: getenv("MOSAIC_TOKEN")}
	if e.server == "" {
		e.server = defaultServer
	}
	gfs := flag.NewFlagSet("mosaic", flag.ContinueOnError)
	gfs.SetOutput(io.Discard)
	gfs.StringVar(&e.server, "server", e.server, "")
	gfs.StringVar(&e.token, "token", e.token, "")
	if err := gfs.Parse(args); err != nil {
		if err == flag.ErrHelp {
			writeMainUsage(stdout)
			return exitOK
		}
		fmt.Fprintf(stderr, "mosaic: %v\nRun 'mosaic help' for usage.\n", err)
		return exitUsage
	}
	rest := gfs.Args()
	if len(rest) == 0 {
		writeMainUsage(stderr)
		return exitUsage
	}
	if rest[0] == "help" {
		return e.help(rest[1:])
	}
	c, group, n := lookup(rest)
	if c == nil {
		if group != "" {
			if n < len(rest) && !isHelpArg(rest[n]) {
				fmt.Fprintf(stderr, "mosaic: unknown %s command %q\n", group, rest[n])
			} else if n < len(rest) {
				writeGroupUsage(stdout, group)
				return exitOK
			} else {
				fmt.Fprintf(stderr, "mosaic: %s needs a subcommand\n", group)
			}
			writeGroupUsage(stderr, group)
			return exitUsage
		}
		fmt.Fprintf(stderr, "mosaic: unknown command %q\nRun 'mosaic help' for usage.\n", rest[0])
		return exitUsage
	}
	return e.exit(c, c.run(e, c, rest[n:]))
}

func isHelpArg(s string) bool { return s == "-h" || s == "-help" || s == "--help" }

// lookup finds the command named by args. It returns the command and the
// number of words its name used, or the group name when args name a group
// but no known subcommand.
func lookup(args []string) (*command, string, int) {
	if len(args) >= 2 {
		for _, c := range commands {
			if c.name == args[0]+" "+args[1] {
				return c, "", 2
			}
		}
	}
	for _, c := range commands {
		if c.name == args[0] {
			return c, "", 1
		}
	}
	for _, c := range commands {
		if g, _, ok := strings.Cut(c.name, " "); ok && g == args[0] {
			return nil, g, 1
		}
	}
	return nil, "", 0
}

func (e *env) help(args []string) int {
	if len(args) == 0 {
		writeMainUsage(e.stdout)
		return exitOK
	}
	c, group, n := lookup(args)
	switch {
	case c != nil && n == len(args):
		// Running the command with --help registers its flags and prints them.
		return e.exit(c, c.run(e, c, []string{"--help"}))
	case group != "" && n == len(args):
		writeGroupUsage(e.stdout, group)
		return exitOK
	}
	fmt.Fprintf(e.stderr, "mosaic: unknown command %q\nRun 'mosaic help' for usage.\n", strings.Join(args, " "))
	return exitUsage
}

// flags returns the flag set of a command. Every command also accepts the
// global --server and --token.
func (e *env) flags(c *command) *flag.FlagSet {
	fs := flag.NewFlagSet("mosaic "+c.name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	fs.StringVar(&e.server, "server", e.server, "mosaicd `URL` (env MOSAIC_SERVER, default "+defaultServer+")")
	fs.StringVar(&e.token, "token", e.token, "bearer token `T` (env MOSAIC_TOKEN)")
	e.fs = fs
	return fs
}

// parse parses a command's flags and checks its positional argument count.
func (e *env) parse(fs *flag.FlagSet, args []string, min, max int, names string) ([]string, error) {
	pos, err := parseFlags(fs, args)
	if err != nil {
		return nil, err
	}
	switch {
	case len(pos) < min:
		return nil, usageErrorf("missing %s", names)
	case max >= 0 && len(pos) > max:
		return nil, usageErrorf("unexpected argument %q", pos[max])
	}
	return pos, nil
}

// client returns a client for the configured server.
func (e *env) client() (*client.Client, error) {
	u, err := url.Parse(e.server)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return nil, usageErrorf("--server must be an http(s) URL such as %s, got %q", defaultServer, e.server)
	}
	return client.New(e.server, e.token, client.WithUserAgent("mosaic-cli")), nil
}

// exit prints err and returns the exit code for it.
func (e *env) exit(c *command, err error) int {
	if err == nil {
		return exitOK
	}
	var (
		ue *usageError
		ie *inputError
		xe *exitError
		ae *client.APIError
	)
	switch {
	case errors.Is(err, flag.ErrHelp):
		writeCommandHelp(e.stdout, c, e.fs)
		return exitOK
	case errors.As(err, &ue):
		fmt.Fprintf(e.stderr, "mosaic: %s\nusage: mosaic %s\nRun 'mosaic %s --help' for details.\n", ue.msg, c.synopsis, c.name)
		return exitUsage
	case errors.As(err, &ie):
		fmt.Fprintf(e.stderr, "mosaic: %s\n", ie.msg)
		return exitUsage
	case errors.As(err, &xe):
		if xe.msg != "" {
			fmt.Fprintf(e.stderr, "mosaic: %s\n", xe.msg)
		}
		writeIssues(e.stderr, xe.issues)
		return xe.code
	case client.IsUnreachable(err):
		fmt.Fprintf(e.stderr, "mosaic: %v\n", err)
		return exitUnreachable
	case errors.As(err, &ae):
		fmt.Fprintf(e.stderr, "mosaic: %v\n", ae)
		writeIssues(e.stderr, ae.Issues)
		return exitRefused
	}
	fmt.Fprintf(e.stderr, "mosaic: %v\n", err)
	return exitRefused
}

// writeIssues lists issues one per line: "  error  path: message".
func writeIssues(w io.Writer, issues []model.Issue) {
	for _, is := range issues {
		sev := is.Severity
		if sev == "" {
			sev = model.SeverityError
		}
		if is.Path == "" {
			fmt.Fprintf(w, "  %-7s %s\n", sev, is.Message)
		} else {
			fmt.Fprintf(w, "  %-7s %s: %s\n", sev, is.Path, is.Message)
		}
	}
}

func errorIssues(issues []model.Issue) []model.Issue {
	var out []model.Issue
	for _, is := range issues {
		if is.Severity != model.SeverityWarning {
			out = append(out, is)
		}
	}
	return out
}

// printJSON writes v as indented JSON without HTML escaping, so CEL such as
// "a && b" stays readable.
func printJSON(w io.Writer, v any) error {
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	enc.SetEscapeHTML(false)
	return enc.Encode(v)
}

// Usage text.

func writeMainUsage(w io.Writer) {
	fmt.Fprint(w, `mosaic is the CLI of mosaicd, the mosaic ontology store and simulator.

usage: mosaic [--server URL] [--token T] <command> [arguments]

commands:
`)
	for _, c := range commands {
		fmt.Fprintf(w, "  mosaic %s\n", c.synopsis)
	}
	fmt.Fprint(w, `
<kind> is component, interface, link, schema, flow, scenario, config or fixture (singular or plural).
R is draft, latest or a revision number. FILE may be YAML or JSON; "-" reads stdin.
Output is indented JSON unless a --format says otherwise.

global flags (also accepted after the command):
  --server URL   mosaicd URL (env MOSAIC_SERVER, default `+defaultServer+`)
  --token T      bearer token (env MOSAIC_TOKEN)

exit codes: 0 success; 1 refusal, validation failure or failed test; 2 usage error;
3 server unreachable.

Run 'mosaic help <command>' or 'mosaic <command> --help' for details.
`)
}

func writeGroupUsage(w io.Writer, group string) {
	fmt.Fprintf(w, "usage:\n")
	for _, c := range commands {
		if g, _, ok := strings.Cut(c.name, " "); ok && g == group {
			fmt.Fprintf(w, "  mosaic %s\n", c.synopsis)
		}
	}
	fmt.Fprintf(w, "Run 'mosaic %s <subcommand> --help' for details.\n", group)
}

func writeCommandHelp(w io.Writer, c *command, fs *flag.FlagSet) {
	fmt.Fprintf(w, "usage: mosaic %s\n\n%s\n", c.synopsis, strings.TrimSpace(c.help))
	if fs == nil {
		return
	}
	fmt.Fprintf(w, "\nflags:\n")
	fs.VisitAll(func(f *flag.Flag) {
		name, usage := flag.UnquoteUsage(f)
		dash := "--"
		if len(f.Name) == 1 {
			dash = "-"
		}
		line := "  " + dash + f.Name
		if name != "" {
			line += " " + name
		}
		if len(line) < 26 {
			fmt.Fprintf(w, "%-26s%s\n", line, usage)
		} else {
			fmt.Fprintf(w, "%s\n%26s%s\n", line, "", usage)
		}
	})
}

package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	"sigs.k8s.io/yaml"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
	"github.com/xleelz/mosaic/pkg/client"
)

var commands []*command

func init() {
	commands = []*command{
		{name: "health", synopsis: "health", run: cmdHealth,
			help: "Check that mosaicd is up. Prints {status, version, dolt}."},
		{name: "version", synopsis: "version [--refresh] [--format text|json]", run: cmdVersion,
			help: `Show the running mosaicd's version and commit, its checkout's branch and upstream, and
whether an update is available (behind, ahead, the latest upstream commit) or why not.
--refresh fetches the upstream now (at most every 30 s); otherwise mosaicd fetches at
most every 10 minutes.`},
		{name: "update", synopsis: "update --yes", run: cmdUpdate,
			help: `Fast-forward mosaicd's checkout (its --source-dir) to its upstream. Under
scripts/serve.sh, mosaicd then exits and the supervisor rebuilds and restarts mosaicd and
the web UI; otherwise restart them yourself. Refused (exit 1, with the reason) unless the
worktree has no local changes, the branch is behind its upstream and not ahead of it,
and self-update isn't disabled. Only accepted from a loopback address. --yes is required.`},
		{name: "ontology list", synopsis: "ontology list", run: cmdOntologyList,
			help: "List ontologies with their latest revision."},
		{name: "ontology get", synopsis: "ontology get <ont>", run: cmdOntologyGet,
			help: "Show an ontology's summary with draft entity counts and whether the draft has unrevisioned changes."},
		{name: "ontology create", synopsis: "ontology create <ont> --name N [--description D]", run: cmdOntologyCreate,
			help: "Create an empty ontology. <ont> is a slug: [a-z0-9] then [a-z0-9_-], at most 64 characters."},
		{name: "ontology update", synopsis: "ontology update <ont> [--name N] [--description D]", run: cmdOntologyUpdate,
			help: "Rename an ontology or change its description."},
		{name: "ontology delete", synopsis: "ontology delete <ont> --yes", run: cmdOntologyDelete,
			help: "Drop an ontology with all its revisions. --yes is required."},
		{name: "doc export", synopsis: "doc export <ont> [--rev R] [--format json|yaml] [-o FILE]", run: cmdDocExport,
			help: "Export a whole ontology document (the draft by default) as JSON or YAML, to stdout or FILE."},
		{name: "doc import", synopsis: "doc import <ont> -f FILE", run: cmdDocImport,
			help: `Replace the draft with a document (YAML or JSON). The draft is replaced even when it
does not validate; the printed result lists the issues to fix, and they are repeated on stderr.`},
		{name: "apply", synopsis: "apply <ont> -f FILE -m MSG [--author A] [--source-sha SHA --repo PATH] [--allow-empty]", run: cmdApply,
			help: `Replace the draft with a document, then create a revision if it is valid.
Prints {"import": {counts, valid, issues}, "revision": {...}}. When the document is
invalid, the draft is still replaced, no revision is created, the issues are listed on
stderr and the exit code is 1.

--source-sha names the code commit the revision models; its metadata is read from the
git repository at --repo (read-only). --allow-empty records a revision even when the
document changes nothing, so every commit can have a revision.`},
		{name: "get", synopsis: "get <ont> <kind> [<id>] [--rev R]", run: cmdGet,
			help: `Print one entity's spec, or a JSON array of every entity of a kind. Every kind works the
same way, including config and fixture: mosaic get demo configs, mosaic get demo fixture base.`},
		{name: "put", synopsis: "put <ont> <kind> (-f FILE | --json JSON)", run: cmdPut,
			help: `Upsert entities into the draft. The input is one entity (its id comes from "id", or for
an interface from component + "." + name), a JSON array of entities, or {"items": [...]}.
Prints {kind, ids, issues}: the issues are the draft's validation issues after the write.`},
		{name: "patch", synopsis: "patch <ont> <kind> <id> (-f FILE | --json JSON)", run: cmdPatch,
			help: "Apply a JSON merge patch (RFC 7396) to one draft entity: null removes a field."},
		{name: "delete", synopsis: "delete <ont> <kind> <id>", run: cmdDelete,
			help: "Delete one entity from the draft."},
		{name: "validate", synopsis: "validate (<ont> [--rev R] | -f FILE... [--refine COMPONENT=CHILD]...)", run: cmdValidate,
			help: `Validate the draft (or a revision). Prints {revision, valid, issues}; exits 1 when invalid.

With -f (repeatable) it validates local files instead, with no server: the documents are
merged as the check tool merges them (conflicts are errors) and the merge is validated.
--refine COMPONENT=CHILD (repeatable) also validates a child file that refines COMPONENT
of the merged parent: the child on its own and the pair (model.ValidateRefinement).
Prints {files, valid, issues, refinements}; exits 1 when anything is invalid.`},
		{name: "revision list", synopsis: "revision list <ont>", run: cmdRevisionList,
			help: "List an ontology's revisions."},
		{name: "revision get", synopsis: "revision get <ont> <n>", run: cmdRevisionGet,
			help: "Show one revision's metadata."},
		{name: "revision create", synopsis: "revision create <ont> -m MSG [--author A] [--source-sha SHA --repo PATH] [--allow-empty]", run: cmdRevisionCreate,
			help: `Validate the draft and record it as the next revision. Refused (exit 1) when the draft
is invalid, with its issues, or unchanged since the latest revision (unless --allow-empty).

--source-sha names the code commit the revision models; its parent, subject, author and
date are read from the git repository at --repo (read-only).`},
		{name: "commits import", synopsis: "commits import <ont> --repo PATH --range A..B [--first-parent] [--url-template T]", run: cmdCommitsImport,
			help: `Read commits from a local git repository and record their metadata (sha, parent,
subject, author, date and the paths changed against the first parent) in the ontology.
Git is only read (log, diff, show, rev-parse); the repository is never modified.
Importing again updates existing commits. Prints the ontology's commits, oldest first.`},
		{name: "commits list", synopsis: "commits list <ont> [--format json|text]", run: cmdCommitsList,
			help: "List the ontology's commits, oldest first, each with the revision modelling it and whether that revision changed the model."},
		{name: "commits show", synopsis: "commits show <ont> <sha> [--format text|json]", run: cmdCommitsShow,
			help: `Show a commit (a prefix of 7 or more characters is enough): its files, the revisions
before and after it, and the impact: components added, removed and modified, and the flows
the commit created, modified or affected.`},
		{name: "diff", synopsis: "diff <ont> [--from R] [--to R]", run: cmdDiff,
			help: "List entity changes between two revisions or the draft. Defaults: --from latest --to draft."},
		{name: "graph", synopsis: "graph <ont> [--rev R]", run: cmdGraph,
			help: "Print the architecture map: components plus explicit and derived edges."},
		{name: "source", synopsis: "source <ont> <path> [--rev R] [--repo X --sha S] [--format text|json]", run: cmdSource,
			help: `Print a file of the code the ontology cites, as mosaicd fetches it from GitHub at the
document's source commit (cached under <data-dir>/source-cache). --repo and --sha pick a
citation's repo and commit instead; they must be the document's source or appear on one
of its citations. For private repos, mosaicd needs GITHUB_TOKEN or gh auth login.`},
		{name: "plan", synopsis: "plan <ont> <flow> [--rev R]", run: cmdPlan,
			help: `Show what a flow can reach: interfaces, components, choice points (keys for --choice),
stateful components (for --state), fault targets (for --fault) and its scenarios.`},
		{name: "sim run", synopsis: "sim run <ont> (--flow F | --scenario S) [--rev R] [--seed N] [--input JSON|@FILE]\n" +
			"               [--choice KEY=OPTION]... [--state COMPONENT.PATH=VALUE]...\n" +
			"               [--fault TARGET:TYPE[:CODE[:STATUS]][@N,M] | --fault JSON]...\n" +
			"               [--fixture ID]... [--topology COMP=A,B,C]... [--config ID=VALUE]...\n" +
			"               [--clock-epoch TIME|MS] [--resolution COMP=refined|black_box]... [--expect CEL]...\n" +
			"               [--no-save] [--format summary|trace|json]", run: cmdSimRun,
			help: `Simulate a flow, or a scenario with request overrides layered on top.

  --choice throttle.check.rate_limit=limited      pick an option at a choice point
  --state redis-ledger.free_slots=0               override state (VALUE is JSON, else a string)
  --state admission-store.accounts.org_demo.standing=suspended
  --fault upstream-a.chat:error:upstream_error:502@1   fail the 1st invocation
  --fault redis-ledger:unavailable                fail every invocation
  --fault upstream-a.chat:timeout@1,2             hang the 1st and 2nd invocations
  --fault db.query:latency:250                    add 250 ms to every invocation
  --fault '{"target":"db","type":"error","code":"deadlock","retryable":true}'
  --fault '{"target":"commit-log.add","type":"unavailable","instance":"n2"}'
  --fixture three-node-rf3                        apply a fixture (after the scenario's)
  --topology cassandra-node=n1,n2,n3              name instances (replaces the entry)
  --state token-metadata@n1.ring='["n1","n2"]'    per-instance state is COMPONENT@INSTANCE
  --config write-request-timeout-ms=500           override a config value
  --clock-epoch 2026-10-30T00:00:00Z              set now's epoch (or milliseconds)
  --resolution engine=refined                     run a component as its child ontology (§14.5)

The starting world is the scenario's fixtures, then the scenario's own settings, then the
request's --fixture, --topology, --config, --clock-epoch and --state, in that order.

--format summary (default) prints the status, outcome, assertions, warnings and a compact
trace indented by call depth; trace prints every event on one line; json prints the run.
Exits 1 when an expectation fails or the run aborts.`},
		{name: "sim list", synopsis: "sim list <ont> [--limit N]", run: cmdSimList,
			help: "List stored runs, newest first, without traces."},
		{name: "sim get", synopsis: "sim get <run-id> [--format summary|trace|json]", run: cmdSimGet,
			help: "Show a stored run."},
		{name: "test", synopsis: "test <ont> [--rev R] [--format text|json]", run: cmdTest,
			help: `Run every scenario's expectations. Prints ✓/✗ per scenario, with its step count for
multi-step scenarios and its mock count (mocks declared, calls mocked) when it uses mocks;
exits 1 if any fails.`},
	}
	commands = append(commands, composeCommands()...)
}

func cmdVersion(e *env, c *command, args []string) error {
	fs := e.flags(c)
	refresh := fs.Bool("refresh", false, "fetch the upstream now")
	format := fs.String("format", "text", "output `F`ormat: text or json")
	if _, err := e.parse(fs, args, 0, 0, ""); err != nil {
		return err
	}
	if *format != "text" && *format != "json" {
		return usageErrorf("--format must be text or json, got %q", *format)
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	v, err := cl.SystemVersion(e.ctx, *refresh)
	if err != nil {
		return err
	}
	if *format == "json" {
		return printJSON(e.stdout, v)
	}
	writeVersion(e.stdout, v)
	return nil
}

func cmdUpdate(e *env, c *command, args []string) error {
	fs := e.flags(c)
	yes := fs.Bool("yes", false, "confirm the update")
	if _, err := e.parse(fs, args, 0, 0, ""); err != nil {
		return err
	}
	if !*yes {
		return usageErrorf("refusing to update mosaicd's checkout without --yes (see mosaic version)")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	res, err := cl.SystemUpdate(e.ctx)
	if err != nil {
		return err
	}
	return printJSON(e.stdout, res)
}

func cmdSource(e *env, c *command, args []string) error {
	fs := e.flags(c)
	rev := revFlag(fs)
	repo := fs.String("repo", "", "a citation's `repo` (owner/name)")
	sha := fs.String("sha", "", "a citation's commit `sha`")
	format := fs.String("format", "text", "output `F`ormat: text (the file) or json")
	pos, err := e.parse(fs, args, 2, 2, "<ont> <path>")
	if err != nil {
		return err
	}
	if *format != "text" && *format != "json" {
		return usageErrorf("--format must be text or json, got %q", *format)
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	f, err := cl.Source(e.ctx, pos[0], pos[1], client.SourceOptions{Rev: *rev, Repo: *repo, SHA: *sha})
	if err != nil {
		return err
	}
	if *format == "json" {
		return printJSON(e.stdout, f)
	}
	_, err = io.WriteString(e.stdout, f.Content)
	return err
}

// Shared flag helpers.

func revFlag(fs *flag.FlagSet) *string {
	return fs.String("rev", "", "revision `R`: draft, latest or a number (default: the server's, the draft)")
}

func kindArg(s string) (string, error) {
	k, ok := model.KindOf(s)
	if !ok {
		return "", usageErrorf("unknown kind %q: want component, interface, link, schema, flow, scenario, config or fixture (singular or plural)", s)
	}
	return k, nil
}

func oneOf(flagName, v string, allowed ...string) error {
	for _, a := range allowed {
		if v == a {
			return nil
		}
	}
	return usageErrorf("--%s must be %s, got %q", flagName, strings.Join(allowed, " or "), v)
}

func cmdHealth(e *env, c *command, args []string) error {
	fs := e.flags(c)
	if _, err := e.parse(fs, args, 0, 0, ""); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	h, err := cl.Health(e.ctx)
	if err != nil {
		return err
	}
	return printJSON(e.stdout, h)
}

// Ontologies.

func cmdOntologyList(e *env, c *command, args []string) error {
	fs := e.flags(c)
	if _, err := e.parse(fs, args, 0, 0, ""); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	list, err := cl.ListOntologies(e.ctx)
	if err != nil {
		return err
	}
	return printJSON(e.stdout, list)
}

func cmdOntologyGet(e *env, c *command, args []string) error {
	fs := e.flags(c)
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	d, err := cl.GetOntology(e.ctx, pos[0])
	if err != nil {
		return err
	}
	return printJSON(e.stdout, d)
}

func cmdOntologyCreate(e *env, c *command, args []string) error {
	fs := e.flags(c)
	name := fs.String("name", "", "display `name` (required)")
	desc := fs.String("description", "", "`description`")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if strings.TrimSpace(*name) == "" {
		return usageErrorf("--name is required")
	}
	if !model.ValidID(pos[0]) {
		return usageErrorf("ontology id %q is not a slug: [a-z0-9] then [a-z0-9_-], at most 64 characters", pos[0])
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	d, err := cl.CreateOntology(e.ctx, api.CreateOntology{ID: pos[0], Name: *name, Description: *desc})
	if err != nil {
		return err
	}
	return printJSON(e.stdout, d)
}

func cmdOntologyUpdate(e *env, c *command, args []string) error {
	fs := e.flags(c)
	name := fs.String("name", "", "new display `name`")
	desc := fs.String("description", "", "new `description`")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	var req api.UpdateOntology
	fs.Visit(func(f *flag.Flag) {
		switch f.Name {
		case "name":
			req.Name = name
		case "description":
			req.Description = desc
		}
	})
	if req.Name == nil && req.Description == nil {
		return usageErrorf("nothing to update: give --name and/or --description")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	d, err := cl.UpdateOntology(e.ctx, pos[0], req)
	if err != nil {
		return err
	}
	return printJSON(e.stdout, d)
}

func cmdOntologyDelete(e *env, c *command, args []string) error {
	fs := e.flags(c)
	yes := fs.Bool("yes", false, "confirm the deletion")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if !*yes {
		return usageErrorf("refusing to delete ontology %q and all its revisions without --yes", pos[0])
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	if err := cl.DeleteOntology(e.ctx, pos[0]); err != nil {
		return err
	}
	return printJSON(e.stdout, map[string]any{"id": pos[0], "deleted": true})
}

// Documents.

func fileFlag(fs *flag.FlagSet, usage string) *string {
	p := fs.String("f", "", usage)
	fs.StringVar(p, "file", "", "same as -f")
	return p
}

func messageFlag(fs *flag.FlagSet) *string {
	p := fs.String("m", "", "revision `message` (required)")
	fs.StringVar(p, "message", "", "same as -m")
	return p
}

func cmdDocExport(e *env, c *command, args []string) error {
	fs := e.flags(c)
	rev := revFlag(fs)
	format := fs.String("format", "json", "output `FORMAT`: json or yaml")
	out := fs.String("o", "", "write to `FILE` instead of stdout")
	fs.StringVar(out, "output", "", "same as -o")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if err := checkRev("rev", *rev); err != nil {
		return err
	}
	if err := oneOf("format", *format, "json", "yaml"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	doc, err := cl.GetDocument(e.ctx, pos[0], *rev)
	if err != nil {
		return err
	}
	var buf strings.Builder
	if err := printJSON(&buf, doc); err != nil {
		return err
	}
	data := []byte(buf.String())
	if *format == "yaml" {
		if data, err = yaml.JSONToYAML(data); err != nil {
			return fmt.Errorf("convert to YAML: %w", err)
		}
	}
	if *out == "" {
		_, err = e.stdout.Write(data)
		return err
	}
	if err := os.WriteFile(*out, data, 0o644); err != nil {
		return inputErrorf("%v", err)
	}
	return nil
}

func cmdDocImport(e *env, c *command, args []string) error {
	fs := e.flags(c)
	file := fileFlag(fs, "document `FILE` (YAML or JSON; - for stdin)")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if *file == "" {
		return usageErrorf("missing -f FILE")
	}
	doc, err := readInput(*file)
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	res, err := cl.PutDocument(e.ctx, pos[0], doc)
	if err != nil {
		return err
	}
	if err := printJSON(e.stdout, res); err != nil {
		return err
	}
	if !res.Valid {
		fmt.Fprintf(e.stderr, "mosaic: the draft of %s was replaced but does not validate:\n", pos[0])
		writeIssues(e.stderr, errorIssues(res.Issues))
	}
	return nil
}

func cmdApply(e *env, c *command, args []string) error {
	fs := e.flags(c)
	file := fileFlag(fs, "document `FILE` (YAML or JSON; - for stdin)")
	msg := messageFlag(fs)
	author := fs.String("author", "", "revision `author`")
	sf := addSourceFlags(fs)
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	switch {
	case *file == "":
		return usageErrorf("missing -f FILE")
	case strings.TrimSpace(*msg) == "":
		return usageErrorf("missing -m MSG")
	}
	src, err := sf.source(e)
	if err != nil {
		return err
	}
	doc, err := readInput(*file)
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	res, err := cl.PutDocument(e.ctx, pos[0], doc)
	if err != nil {
		return err
	}
	if !res.Valid {
		if err := printJSON(e.stdout, map[string]any{"import": res, "revision": nil}); err != nil {
			return err
		}
		return &exitError{code: exitRefused, issues: errorIssues(res.Issues),
			msg: fmt.Sprintf("the document is invalid; the draft of %s was replaced but no revision was created:", pos[0])}
	}
	rev, err := cl.CreateRevision(e.ctx, pos[0], api.CreateRevision{Message: *msg, Author: *author, Source: src, AllowEmpty: *sf.allowEmpty})
	if err != nil {
		return err
	}
	return printJSON(e.stdout, map[string]any{"import": res, "revision": rev})
}

// Entities.

func cmdGet(e *env, c *command, args []string) error {
	fs := e.flags(c)
	rev := revFlag(fs)
	pos, err := e.parse(fs, args, 2, 3, "<ont> <kind>")
	if err != nil {
		return err
	}
	if err := checkRev("rev", *rev); err != nil {
		return err
	}
	kind, err := kindArg(pos[1])
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	if len(pos) == 3 {
		spec, err := cl.GetEntity(e.ctx, pos[0], kind, pos[2], *rev)
		if err != nil {
			return err
		}
		return printJSON(e.stdout, spec)
	}
	items, err := cl.ListEntities(e.ctx, pos[0], kind, *rev)
	if err != nil {
		return err
	}
	return printJSON(e.stdout, items)
}

func cmdPut(e *env, c *command, args []string) error {
	fs := e.flags(c)
	file := fileFlag(fs, "entity `FILE` (YAML or JSON; - for stdin)")
	inline := fs.String("json", "", "entity `JSON`")
	pos, err := e.parse(fs, args, 2, 2, "<ont> <kind>")
	if err != nil {
		return err
	}
	kind, err := kindArg(pos[1])
	if err != nil {
		return err
	}
	spec, err := specSource(*file, *inline)
	if err != nil {
		return err
	}
	items, single, id, err := splitEntities(kind, spec)
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	var res *api.UpsertResult
	if single {
		res, err = cl.PutEntity(e.ctx, pos[0], kind, id, spec)
	} else {
		res, err = cl.UpsertEntities(e.ctx, pos[0], kind, items)
	}
	if err != nil {
		return err
	}
	return printJSON(e.stdout, res)
}

// splitEntities classifies put input: one entity object (single, with its
// id), a JSON array, or {"items": [...]}.
func splitEntities(kind string, spec json.RawMessage) (items []json.RawMessage, single bool, id string, err error) {
	trimmed := strings.TrimSpace(string(spec))
	if strings.HasPrefix(trimmed, "[") {
		if err := json.Unmarshal(spec, &items); err != nil {
			return nil, false, "", inputErrorf("invalid entity list: %v", err)
		}
		if len(items) == 0 {
			return nil, false, "", inputErrorf("the entity list is empty")
		}
		return items, false, "", nil
	}
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(spec, &obj); err != nil {
		return nil, false, "", inputErrorf("want an entity object, a JSON array or {\"items\": [...]}: %v", err)
	}
	if raw, ok := obj["items"]; ok && len(obj) == 1 {
		var wrapped api.Items
		if err := json.Unmarshal(raw, &wrapped.Items); err != nil {
			return nil, false, "", inputErrorf("\"items\" must be a list of entities: %v", err)
		}
		if len(wrapped.Items) == 0 {
			return nil, false, "", inputErrorf("\"items\" is empty")
		}
		return wrapped.Items, false, "", nil
	}
	str := func(k string) string {
		var s string
		if raw, ok := obj[k]; ok {
			_ = json.Unmarshal(raw, &s)
		}
		return s
	}
	id = str("id")
	if id == "" && kind == model.KindInterface {
		if comp, name := str("component"), str("name"); comp != "" && name != "" {
			id = comp + "." + name
		}
	}
	if id == "" {
		if kind == model.KindInterface {
			return nil, false, "", inputErrorf("the interface has no id: give \"id\" or \"component\" and \"name\"")
		}
		return nil, false, "", inputErrorf("the %s has no \"id\"", kind)
	}
	return nil, true, id, nil
}

func cmdPatch(e *env, c *command, args []string) error {
	fs := e.flags(c)
	file := fileFlag(fs, "merge patch `FILE` (YAML or JSON; - for stdin)")
	inline := fs.String("json", "", "merge patch `JSON`")
	pos, err := e.parse(fs, args, 3, 3, "<ont> <kind> <id>")
	if err != nil {
		return err
	}
	kind, err := kindArg(pos[1])
	if err != nil {
		return err
	}
	patch, err := specSource(*file, *inline)
	if err != nil {
		return err
	}
	if !strings.HasPrefix(strings.TrimSpace(string(patch)), "{") {
		return inputErrorf("a merge patch must be a JSON object")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	res, err := cl.PatchEntity(e.ctx, pos[0], kind, pos[2], patch)
	if err != nil {
		return err
	}
	return printJSON(e.stdout, res)
}

func cmdDelete(e *env, c *command, args []string) error {
	fs := e.flags(c)
	pos, err := e.parse(fs, args, 3, 3, "<ont> <kind> <id>")
	if err != nil {
		return err
	}
	kind, err := kindArg(pos[1])
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	if err := cl.DeleteEntity(e.ctx, pos[0], kind, pos[2]); err != nil {
		return err
	}
	return printJSON(e.stdout, map[string]any{"kind": kind, "id": pos[2], "deleted": true})
}

// Validation and revisions.

func cmdValidate(e *env, c *command, args []string) error {
	fs := e.flags(c)
	rev := revFlag(fs)
	var files, refines stringList
	fs.Var(&files, "f", "validate a local ontology `FILE` instead of a server's (repeatable; merged in order)")
	fs.Var(&files, "file", "same as -f")
	fs.Var(&refines, "refine", "with -f, also validate a refinement: `COMPONENT=CHILD_FILE` (repeatable)")
	pos, err := parseFlags(fs, args)
	if err != nil {
		return err
	}
	if len(files) > 0 {
		switch {
		case len(pos) > 0:
			return usageErrorf("give either <ont> or -f, not both")
		case *rev != "":
			return usageErrorf("--rev needs <ont>, not -f")
		}
		return validateFiles(e, files, refines)
	}
	switch {
	case len(refines) > 0:
		return usageErrorf("--refine needs -f")
	case len(pos) == 0:
		return usageErrorf("missing <ont>")
	case len(pos) > 1:
		return usageErrorf("unexpected argument %q", pos[1])
	}
	if err := checkRev("rev", *rev); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	v, err := cl.Validate(e.ctx, pos[0], *rev)
	if err != nil {
		return err
	}
	if v.Issues == nil {
		v.Issues = []model.Issue{}
	}
	if err := printJSON(e.stdout, v); err != nil {
		return err
	}
	if !v.Valid {
		which := v.Revision
		if which == "" {
			which = "the draft"
		} else if which != "draft" {
			which = "revision " + which
		}
		errs := errorIssues(v.Issues)
		return &exitError{code: exitRefused, issues: errs, msg: fmt.Sprintf("%s of %s is invalid (%d errors):", which, pos[0], len(errs))}
	}
	return nil
}

func cmdRevisionList(e *env, c *command, args []string) error {
	fs := e.flags(c)
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	revs, err := cl.ListRevisions(e.ctx, pos[0])
	if err != nil {
		return err
	}
	return printJSON(e.stdout, revs)
}

func cmdRevisionGet(e *env, c *command, args []string) error {
	fs := e.flags(c)
	pos, err := e.parse(fs, args, 2, 2, "<ont> <n>")
	if err != nil {
		return err
	}
	n, err := strconv.Atoi(pos[1])
	if err != nil || n < 1 {
		return usageErrorf("revision number must be a positive integer, got %q", pos[1])
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	rev, err := cl.GetRevision(e.ctx, pos[0], n)
	if err != nil {
		return err
	}
	return printJSON(e.stdout, rev)
}

func cmdRevisionCreate(e *env, c *command, args []string) error {
	fs := e.flags(c)
	msg := messageFlag(fs)
	author := fs.String("author", "", "revision `author`")
	sf := addSourceFlags(fs)
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if strings.TrimSpace(*msg) == "" {
		return usageErrorf("missing -m MSG")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	src, err := sf.source(e)
	if err != nil {
		return err
	}
	rev, err := cl.CreateRevision(e.ctx, pos[0], api.CreateRevision{Message: *msg, Author: *author, Source: src, AllowEmpty: *sf.allowEmpty})
	if err != nil {
		return err
	}
	return printJSON(e.stdout, rev)
}

func cmdDiff(e *env, c *command, args []string) error {
	fs := e.flags(c)
	from := fs.String("from", api.RevLatest, "base revision `R`")
	to := fs.String("to", api.RevDraft, "target revision `R`")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if err := checkRev("from", *from); err != nil {
		return err
	}
	if err := checkRev("to", *to); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	d, err := cl.Diff(e.ctx, pos[0], *from, *to)
	if err != nil {
		return err
	}
	if d.Changes == nil {
		d.Changes = []api.Change{}
	}
	return printJSON(e.stdout, d)
}

func cmdGraph(e *env, c *command, args []string) error {
	fs := e.flags(c)
	rev := revFlag(fs)
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if err := checkRev("rev", *rev); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	g, err := cl.Graph(e.ctx, pos[0], *rev)
	if err != nil {
		return err
	}
	return printJSON(e.stdout, g)
}

func cmdPlan(e *env, c *command, args []string) error {
	fs := e.flags(c)
	rev := revFlag(fs)
	pos, err := e.parse(fs, args, 2, 2, "<ont> <flow>")
	if err != nil {
		return err
	}
	if err := checkRev("rev", *rev); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	p, err := cl.Plan(e.ctx, pos[0], pos[1], *rev)
	if err != nil {
		return err
	}
	return printJSON(e.stdout, p)
}

// Simulations and tests.

func formatFlag(fs *flag.FlagSet, def, usage string) *string {
	return fs.String("format", def, usage)
}

func cmdSimRun(e *env, c *command, args []string) error {
	fs := e.flags(c)
	flow := fs.String("flow", "", "`F`: the flow id to run")
	scenario := fs.String("scenario", "", "`S`: the scenario id to run (its flow, input, choices, state, faults and expectations)")
	rev := revFlag(fs)
	var seed int64Flag
	fs.Var(&seed, "seed", "random seed `N` (default: the scenario's, else 1)")
	input := fs.String("input", "", "entry input: inline `JSON` or @FILE (YAML or JSON), merged over the flow's")
	choices := choiceFlag{}
	fs.Var(choices, "choice", "choose an option: `KEY=OPTION` (repeatable)")
	state := stateFlag{}
	fs.Var(state, "state", "override state: `COMPONENT.PATH=VALUE`, VALUE as JSON else a string (repeatable)")
	var faults faultFlag
	fs.Var(&faults, "fault", "inject a fault: `TARGET:TYPE[:CODE[:STATUS]][@N,M]` or JSON (repeatable)")
	var expect stringList
	fs.Var(&expect, "expect", "add an expectation: a `CEL` expression (repeatable)")
	var fixtures stringList
	fs.Var(&fixtures, "fixture", "apply a fixture `ID` after the scenario's (repeatable, in order)")
	topology := topologyFlag{}
	fs.Var(topology, "topology", "name a component's instances: `COMP=A,B,C` (repeatable)")
	config := configFlag{}
	fs.Var(config, "config", "override a config: `ID=VALUE`, VALUE as JSON else a string (repeatable)")
	clockEpoch := fs.String("clock-epoch", "", "the clock's epoch: an RFC 3339 `TIME` or milliseconds")
	resolution := resolutionFlag{}
	fs.Var(resolution, "resolution", "run a component black box or refined: `COMPONENT=refined|black_box` (repeatable)")
	noSave := fs.Bool("no-save", false, "do not store the run")
	format := formatFlag(fs, "summary", "output `FORMAT`: summary, trace or json")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if *flow == "" && *scenario == "" {
		return usageErrorf("give --flow F or --scenario S")
	}
	if err := checkRev("rev", *rev); err != nil {
		return err
	}
	if err := oneOf("format", *format, "summary", "trace", "json"); err != nil {
		return err
	}
	req := api.SimulationRequest{Rev: *rev}
	req.Flow, req.Scenario = *flow, *scenario
	if seed.set {
		req.Seed = &seed.v
	}
	if *input != "" {
		if req.Input, err = parseInputFlag(*input); err != nil {
			return err
		}
	}
	if len(choices) > 0 {
		req.Choices = model.ScalarChoices(choices)
	}
	if len(state) > 0 {
		req.State = state
	}
	req.Faults = faults
	req.Expect = expect
	req.Fixtures = fixtures
	if len(topology) > 0 {
		req.Topology = topology
	}
	if len(config) > 0 {
		req.Config = config
	}
	if len(resolution) > 0 {
		req.Resolution = resolution
	}
	if *clockEpoch != "" {
		if req.Clock, err = parseClockEpoch(*clockEpoch); err != nil {
			return err
		}
	}
	if *noSave {
		f := false
		req.Save = &f
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	run, err := cl.RunSimulation(e.ctx, pos[0], req)
	if err != nil {
		return err
	}
	if err := writeRun(e.stdout, run, *format); err != nil {
		return err
	}
	return runOutcome(run)
}

// runOutcome turns failed expectations or an aborted run into exit code 1.
func runOutcome(run *api.SimulationRun) error {
	s := run.Summary
	if s.Status == "aborted" {
		return &exitError{code: exitRefused, msg: "the run aborted: " + s.Abort}
	}
	failed := 0
	for _, a := range s.Assertions {
		if !a.Passed {
			failed++
		}
	}
	if failed > 0 {
		return &exitError{code: exitRefused, msg: fmt.Sprintf("%d of %d expectations failed", failed, len(s.Assertions))}
	}
	if !s.Passed && len(s.Assertions) > 0 {
		return &exitError{code: exitRefused, msg: "the run did not pass"}
	}
	return nil
}

func writeRun(w io.Writer, run *api.SimulationRun, format string) error {
	switch format {
	case "json":
		return printJSON(w, run)
	case "trace":
		return writeTrace(w, run)
	}
	return writeSummary(w, run)
}

func cmdSimList(e *env, c *command, args []string) error {
	fs := e.flags(c)
	limit := fs.Int("limit", 0, "at most `N` runs (default: the server's)")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if *limit < 0 {
		return usageErrorf("--limit must not be negative")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	runs, err := cl.ListRuns(e.ctx, pos[0], *limit)
	if err != nil {
		return err
	}
	return printJSON(e.stdout, runs)
}

func cmdSimGet(e *env, c *command, args []string) error {
	fs := e.flags(c)
	format := formatFlag(fs, "summary", "output `FORMAT`: summary, trace or json")
	pos, err := e.parse(fs, args, 1, 1, "<run-id>")
	if err != nil {
		return err
	}
	if err := oneOf("format", *format, "summary", "trace", "json"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	run, err := cl.GetRun(e.ctx, pos[0])
	if err != nil {
		return err
	}
	return writeRun(e.stdout, run, *format)
}

func cmdTest(e *env, c *command, args []string) error {
	fs := e.flags(c)
	rev := revFlag(fs)
	format := formatFlag(fs, "text", "output `FORMAT`: text or json")
	pos, err := e.parse(fs, args, 1, 1, "<ont>")
	if err != nil {
		return err
	}
	if err := checkRev("rev", *rev); err != nil {
		return err
	}
	if err := oneOf("format", *format, "text", "json"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	rep, err := cl.Test(e.ctx, pos[0], *rev)
	if err != nil {
		return err
	}
	if *format == "json" {
		err = printJSON(e.stdout, rep)
	} else {
		err = writeTestReport(e.stdout, rep)
	}
	if err != nil {
		return err
	}
	if !rep.Passed {
		failed := rep.Failed
		if failed == 0 {
			for _, r := range rep.Results {
				if !r.Passed {
					failed++
				}
			}
		}
		return &exitError{code: exitRefused, msg: fmt.Sprintf("%d of %d scenarios failed", failed, rep.Total)}
	}
	return nil
}

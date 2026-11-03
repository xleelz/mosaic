---
name: mosaic-ontology
description: Create, read, update, validate, diff, export and version mosaic ontologies (versioned models of a software system made of components, interfaces, links, schemas, flows and scenarios) through the `mosaic` CLI. Use this whenever the user wants to model a codebase or service in mosaic, build an ontology from a repo, add or change components, interfaces, schemas or links, fix `mosaic validate` issues, cut a revision, compare revisions, or import or export an ontology document. It also applies to vaguer requests like "map this service into mosaic" or "update the model after this refactor". To write behaviors or scenarios, or to run simulations, also load mosaic-simulation.
---

# Mosaic ontologies

A mosaic ontology is a versioned model of a software system: **components** (a hierarchy of
services, modules, functions and datastores), the **interfaces** they provide (with request and
response schemas and optional simulated behavior), **links**, reusable **schemas**, **flows**
(entry points to simulate) and **scenarios** (configured runs with expectations). You operate it
only through the `mosaic` CLI, which talks to `mosaicd`.

## Draft and revisions

Each ontology has one mutable **draft** and immutable, numbered **revisions** (1, 2, 3 and so on).
Every write edits the draft, and the draft may be invalid while you work. A revision validates the
draft and freezes it; creating one fails with exit 1 when the draft has errors (HTTP 422) or is
unchanged since the last revision (409). Reads take `--rev draft|latest|N`.
(Storage detail you rarely need: all ontologies live in one Dolt database, each on its own branch
`ont/<id>`, with revision tags `ont/<id>/r<N>`.)

## Core loop

1. **Look before you write.** `mosaic ontology get <ont>` gives draft counts and `draft_dirty`.
   Use `mosaic doc export <ont> --format yaml -o current.yaml` to see the whole model, or
   `mosaic get <ont> <kind> [<id>]` for one entity.
2. **Edit the draft.** For a new model or a broad change, edit the YAML document and load it with
   `mosaic doc import <ont> -f FILE`. For targeted changes, use the entity commands:
   - `mosaic put <ont> <kind> -f entity.yaml` upserts one entity, a list, or `{"items": [...]}`.
     An upsert replaces the whole entity, so send the complete spec.
   - `mosaic patch <ont> <kind> <id> --json '{"summary": "..."}'` applies a JSON merge patch:
     objects merge, `null` deletes a key, and **lists are replaced whole**. To change one
     behavior step, patch the full `behavior` list or `put` the interface.
   - `mosaic delete <ont> <kind> <id>`. Delete or repoint everything that references the
     entity (children's `parent`, calls, links, scenarios), or validation fails.
3. **Validate.** `mosaic validate <ont>` returns `{valid, issues: [{path, message, severity}]}`.
   Paths name the entity by id and walk into it, for example
   `interfaces[checkout.place-order].behavior[3].retry.max_attempts` or
   `scenarios[out-of-stock].choices.checkout.place-order.fraud_screen`. Fix every `error`; also fix
   `warning`s, which flag real gaps (a state that doesn't match its schema, or a dynamic call
   without `targets`). Local files validate without a server: `mosaic validate -f a.yaml -f
   b.yaml` (repeatable; merged as `check` merges fragments) prints `{files, valid, issues}`, and
   `--refine <component>=<child.yaml>` also validates a refinement child against the merged parent.
4. **Check behavior** if the change touches behaviors or scenarios: `mosaic test <ont>` (see
   mosaic-simulation).
5. **Cut a revision.** `mosaic revision create <ont> -m "what changed and why"`. As a shortcut,
   `mosaic apply <ont> -f FILE -m MSG` imports a whole document and creates a revision if it is
   valid; if it isn't, the draft is still replaced and you get the issues.
6. **Review.** `mosaic diff <ont>` shows entity changes from latest to draft (use
   `--from R --to R` for other pairs). Each change is `added`, `removed` or `modified`, with
   `before` and `after`.

Output is indented JSON by default; parse it rather than scraping text. Exit codes: 0 success;
1 refusal, invalid, or failed test; 2 usage error; 3 server unreachable (start `mosaicd`, or check
`--server`/`MOSAIC_SERVER`). The full command reference is in
[references/cli.md](references/cli.md).

Documents are decoded **strictly**. A misspelled or unknown field (`behaviour`, `retry.on`) or a
wrong type rejects the whole document or entity before validation even runs. The exact fields and
types for every kind are in [references/document-format.md](references/document-format.md).

## Modeling conventions

Building or updating an ontology from a code repo? Read
[references/modeling-codebases.md](references/modeling-codebases.md) first. The essentials:

- **Ids are slugs**: `[a-z0-9]` then `[a-z0-9_-]`, at most 64 characters, no dots
  (`pool-admission`, `upstream-a`). Schema ids may also use capitals and dots (`ChatRequest`).
- **Interface id = `<component>.<name>`** (`throttle.check`). Give `component` and `name` and let
  the id derive. A **choice key = `<interface id>.<choice>`** (`throttle.check.rate_limit`).
- **Component hierarchy**: a top-level service or system, with `parent` children down to the
  smallest units worth simulating separately (a gate, a store, a dispatcher). Leaves (components no
  one names as `parent`) carry the interesting behavior. Don't model every function. Model each
  unit whose outcome changes the flow, or that you'd want to fault, branch on, or count.
- **Interfaces get request and response schemas.** Put shared shapes in `schemas` and reference
  them by id. Add `examples` (and `default`/`enum`) so fake data looks real: ids that match state
  keys, plausible amounts and model names. Fake data drives every stub and entry input.
- **Cite sources on everything**: `sources: [path/to/file.go:120]` on components, interfaces,
  links and flows, and `source: path:line` on narrated steps. Use `path`, `path:line` or
  `path:line-end`, relative to the repo in the document's `source.repo`.
- **`errors`** document an interface's error contract (`code`, `status`, `retryable`). The engine
  doesn't enforce them, so keep them consistent with the behavior's `fail` steps.
- Variable-like names are identifiers, not slugs: `as` names, `choice` names and `set` path
  segments must match `[A-Za-z_][A-Za-z0-9_]*` (`rate_limit`, `ctx.httpStatus`; never
  `ctx.http-status`).

## Config, fixtures and instances

> Requires mosaic with DESIGN §11 (in progress).

Two more kinds, **config** (a deployed configuration value, with its code default) and
**fixture** (a named starting world: topology, clock, config and seed state), and **instances**
(several copies of the same code, named in a fixture's `topology`, with per-instance state keyed
`<component>@<instance>`). Read deployed values into `config` entities instead of literals, seed
shared data once in fixtures, and model peers as instances, not as one component per copy or a
`to` field. How and why: [references/modeling-codebases.md](references/modeling-codebases.md#config-fixtures-and-instances);
fields: [references/document-format.md](references/document-format.md#additions-for-systems-with-many-parts).
Building a whole repo with several agents? Load mosaic-generate.

## YAML pitfalls

The YAML parser follows YAML 1.2: only `true` and `false` are booleans, so words like `on`,
`off`, `yes` and `no` stay strings. A few things still change type or meaning silently:

- **Quote every string that starts with `=`** (a CEL template: `"= input.api_key"`) and every
  CEL expression in `if`, `when` and `expect`. An unquoted `!(...)` is read as a YAML tag and your
  expression is corrupted.
- Quote strings containing `: ` (`name: "Redis unavailable: local fallback"`) and, inside
  `{...}` flow mappings, strings containing commas (`title: "Screen, reserve and charge"`).
- Quote numeric-looking strings you mean as text: `1.10` becomes the number 1.1, and `~` or
  `null` become null.
- Use single quotes for string literals inside CEL: `"ctx.phase == 'complete'"`.

## When you're done

Report the revision number you created, a summary of `mosaic diff`, and any validation warnings
you left on purpose.

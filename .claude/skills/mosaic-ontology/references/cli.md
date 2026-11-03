# `mosaic` CLI reference

These commands are specified in docs/DESIGN.md §7. The output shapes come from the wire types in
`pkg/api`.

## Contents

- [Global behavior](#global-behavior)
- [Ontologies](#ontologies)
- [Documents](#documents)
- [Entities](#entities)
- [Validation, revisions and diffs](#validation-revisions-and-diffs)
- [Graph and plan](#graph-and-plan)
- [Simulation and tests](#simulation-and-tests)
- [Errors](#errors)

## Global behavior

- Server: `--server URL` or `MOSAIC_SERVER` (default `http://127.0.0.1:7878`). Token: `--token T`
  or `MOSAIC_TOKEN`, needed only when `mosaicd` was started with one. Timeout: `--timeout D` or
  `MOSAIC_TIMEOUT` (default `60s`) per request; raise it (`--timeout 10m`) for `mosaic test` on an
  ontology with thousands of scenarios.
- Output is indented JSON by default, ready for `jq`. `--format text` (or `summary`/`trace` where
  listed) prints a human summary.
- Exit codes: **0** success; **1** refusal, validation failure, or failed test; **2** usage error;
  **3** server unreachable.
- `<kind>` accepts singular or plural: `component(s)`, `interface(s)`, `link(s)`, `schema(s)`,
  `flow(s)`, `scenario(s)`, `config(s)`, `fixture(s)`.
- `R` (for `--rev`, `--from`, `--to`) is `draft`, `latest` or a revision number.
- `-f FILE` accepts YAML or JSON.

## Ontologies

```
mosaic health                                   # {status, version, dolt}
mosaic ontology list                            # {ontologies: [{id, name, description, created_at, updated_at, latest_revision, revision_count}]}
mosaic ontology get <ont>                       # the summary plus {counts: {component: N, ...}, draft_dirty}
mosaic ontology create <ont> --name N [--description D]
mosaic ontology update <ont> [--name N] [--description D]
mosaic ontology delete <ont> --yes              # drops the ontology, its revisions and its draft; irreversible
```

`<ont>` is a slug. `draft_dirty: true` means the draft has changes that aren't in a revision yet.

## Documents

```
mosaic doc export <ont> [--rev R] [--format json|yaml] [-o FILE]
mosaic doc import <ont> -f FILE                 # replace the draft: {counts, valid, issues}
mosaic apply <ont> -f FILE -m MSG [--author A]  # import, then create a revision if valid
```

- `doc import` replaces the **whole** draft. Entities missing from the file are removed. The draft
  is replaced even when it doesn't validate; `issues` says what to fix. A file that fails strict
  decoding (an unknown field or wrong type) is refused, and the draft is left unchanged.
- `apply` exits 1 if the document is invalid. The draft has still been replaced, so fix it and run
  `mosaic revision create`, or re-apply.
- The safe way to edit a whole document: `doc export --format yaml -o f.yaml`, edit, `doc import`,
  `validate`.

## Entities

```
mosaic get <ont> <kind> [<id>] [--rev R]        # a list as {items: [...]}, or one entity spec
mosaic put <ont> <kind> (-f FILE | --json JSON) # upsert one entity, a list, or {"items": [...]}: {kind, ids, issues}
mosaic patch <ont> <kind> <id> (-f FILE | --json JSON)   # JSON merge patch
mosaic delete <ont> <kind> <id>
```

- `put` replaces each entity whole. An interface may be sent with `component` and `name` only;
  its id is derived.
- `patch` follows RFC 7386: objects merge recursively, `null` removes a key, and arrays (such as
  `behavior`, `sources` and `expect`) are replaced entirely.
- Writes return the validation `issues` they cause, but a write never fails because the draft
  became invalid. Run `mosaic validate` before cutting a revision.

Examples:

```bash
mosaic put shop interface --json '{"component":"payments","name":"refund","kind":"http","request":"RefundRequest"}'
mosaic patch shop component inventory --json '{"state":{"initial":{"available":10}}}'
mosaic get shop interfaces checkout.place-order --rev latest
```

## Validation, revisions and diffs

```
mosaic validate <ont> [--rev R]                 # {revision, valid, issues: [{path, message, severity}]}; exit 1 if invalid
mosaic revision list <ont>                      # {revisions: [{number, hash, message, author, created_at}]}
mosaic revision get <ont> <n>
mosaic revision create <ont> -m MSG [--author A]   # exit 1: invalid draft (422) or no changes (409)
mosaic diff <ont> [--from R] [--to R]           # defaults: latest to draft
```

A diff is `{from, to, changes: [{kind, id, change: added|removed|modified, before?, after?}]}`.
To compare two revisions: `mosaic diff shop --from 3 --to 4`.

## Graph and plan

```
mosaic graph <ont> [--rev R]       # {nodes: [{id, name, kind, parent, layer, summary, interfaces, leaf, stateful}], edges: [...]}
mosaic plan <ont> <flow> [--rev R] # what a flow can reach, and the controls a simulation can set
```

Graph edges are `{id, from, to, kind, label, interfaces, derived}`. Edges derived from behavior
calls and emits have kind `calls` or `emits`; links appear as `link:<id>`.

A plan is `{flow, entry, caller, interfaces, components, choices: [{key, interface, name, options,
default, title}], state: [{component, initial, schema}], faultable, scenarios, dynamic?}`. Use it
to find valid choice keys, fault targets and state to override. `dynamic` lists dynamic call sites
with no `targets`, which the plan can't follow.

## Simulation and tests

```
mosaic sim run <ont> (--flow F | --scenario S) [--rev R] [--seed N] [--input JSON|@FILE]
               [--choice KEY=OPTION]... [--state COMPONENT.PATH=VALUE]...
               [--fault TARGET:TYPE[:CODE[:STATUS]][@N,M] | --fault JSON]...
               [--fixture ID]... [--topology COMP=A,B,C]... [--config ID=VALUE]...
               [--clock-epoch TIME|MS] [--expect CEL]... [--no-save] [--format summary|trace|json]
mosaic sim list <ont> [--limit N]
mosaic sim get <run-id> [--format summary|trace|json]
mosaic test <ont> [--rev R] [--format text|json]
```

- `--scenario S` loads the scenario; every other flag overlays it. Choices and state merge, while
  faults and expectations are appended. `--flow` with `--scenario` must name the scenario's flow.
- `--choice throttle.check.rate_limit=exceeded`. The key is `<interface>.<choice>`.
- `--state inventory.available=0` or `--state authentication.keys={}`. The first segment is the
  component; VALUE is parsed as JSON and falls back to a string.
- `--fault payments:unavailable`, `--fault payments.charge:error:gateway_error:502@1,2` (affect
  invocations 1 and 2), `--fault upstream-a.chat:timeout`, `--fault cache:latency:500` (adds 500 ms). For `retryable`, `message` or
  `latency_ms`, use JSON:
  `--fault '{"target":"cache","type":"latency","latency_ms":500}'`.
- `--state 'gossiper@n2.version=3'` overrides one instance's state (§11.1).
- `--fixture three-node-rf3` applies a fixture after the scenario's (repeatable, in order);
  `--topology cassandra-node=n1,n2,n3` names a component's instances (replacing that entry);
  `--config write-request-timeout-ms=500` overrides a config (VALUE is JSON, else a string);
  `--clock-epoch 2026-10-30T00:00:00Z` (or milliseconds) sets `now`'s epoch. Faults take an
  `instance` in the JSON form.
- `--input '{"quantity": 2}'` or `--input @input.json` deep-merges over the flow and scenario input.
- `--expect "result.ok"` adds an assertion; a failed assertion makes the exit code 1.
- `--no-save` skips storing the run. The simulation runs against the draft unless you pass `--rev`.
- `test --format text` notes a scenario's step count and its mocks (declared, calls mocked); the
  JSON results carry `steps`, `mocks` and `mocked_calls`.
- `sim run` and `sim get` default to `--format summary`, and `test` defaults to `--format text`. These
  are for humans, so **pass `--format json` when you need to parse the result**. A run that aborts
  also exits 1.
- `--format summary` prints the outcome, the assertions and a one-line-per-call trace. `json`
  prints the full run: `{id, ontology, revision, flow, scenario, created_at, request, summary,
  trace}`.
- `test` runs every scenario's expectations and returns `{revision, passed, total, failed,
  results: [{scenario, name, passed, status, assertions, abort?, error?, run_id?}]}`. It exits 1
  if any scenario fails.

How to read summaries and traces is covered in mosaic-simulation.

## Errors

Non-2xx responses are `{"error": {"code", "message", "issues"}}`, with code `bad_request`,
`not_found`, `conflict` (409: for example, a revision with nothing to commit), `invalid` (422,
with `issues`), `unauthorized` or `internal`. The CLI prints this body and exits 1, or 3 when the
server can't be reached.

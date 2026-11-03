# Mosaic v0: ontology store and simulator

Mosaic's first milestone is the foundation for pillar 1: a versioned ontology store, a simulator
that runs flows at message level, an agent CLI with skills, and a web UI.

```
┌──────────────┐   HTTP/JSON    ┌─────────────────────────────────────────────┐
│ mosaic (CLI) │──────────────▶│ mosaicd                                     │
│ agent skills │               │  api ─▶ store (Dolt) ─▶ dolt sql-server     │
├──────────────┤               │   └──▶ model (validate) ─▶ sim (engine)     │
│ web (Next.js)│──────────────▶│                                             │
└──────────────┘               └─────────────────────────────────────────────┘
```

## 1. Storage

- `mosaicd` supervises a `dolt sql-server` child (or connects to one with `--dolt-dsn`).
- Everything lives in one Dolt database, `mosaic`, with **one branch per ontology**:

| Branch | Contents |
|---|---|
| `main` | The registry: `ontologies` (the index) and `simulation_runs` (results; runs are never committed) |
| `ontology-base` | Two empty tables, `entities(kind, id, spec JSON)` and `meta(k, v JSON)`; every ontology branch starts here |
| `ont/<id>` | One ontology. It contains only that ontology's rows. Connections reach it as the database `mosaic/ont/<id>` |

- The **draft** is the ontology branch's working set. Working sets are per branch, so drafts are
  isolated from each other. Entity writes edit the draft and may leave it invalid.
- A **revision** validates the draft and records a commit on `ont/<id>` tagged `ont/<id>/r<N>`.
  Revisions are immutable and numbered 1, 2, 3 and so on. Reads take `rev=draft|latest|N`
  (`AS OF 'ont/<id>/rN'`). Diffs use `dolt_diff`. Deleting an ontology deletes its branch, its tags
  and its registry row.
- One database means one backup and one Dolt remote for everything. For pillar 2, a draft ontology
  becomes a branch off `ont/<id>`; for pillar 3, candidates are branches off the draft.

## 2. Meta-model (document `schema_version: 1`)

IDs are slugs: `[a-z0-9]` then `[a-z0-9_-]`, 1 to 64 characters, with no dots. An interface's id is
`<component>.<name>`, and a choice key is `<interface id>.<choice>`.

| Kind | Fields |
|---|---|
| **component** | `id`, `name`, `kind` (service, module, function, datastore, queue, external, client and so on), `parent`, `layer`, `summary`, `description`, `sources`, `tags`, `attributes`, `state {schema, initial}` |
| **interface** | `component`, `name`, `kind` (http, rpc, function, event, queue, stream, sql and so on), `summary`, `description`, `sources`, `attributes`, `request`, `response` (inline JSON Schema or a schema id), `errors [{code, status, retryable, summary}]`, `latency_ms` (a number or `{min, max}`), `behavior [step]`, `store {table, op, key, value, where, default, not_found, conflict}` |
| **link** | `id`, `from`, `to` (a component or interface id), `kind` (calls, reads, writes, publishes, subscribes, depends_on, deploys, other), `label`, `protocol`, `summary`, `sources`, `attributes` |
| **schema** | `id`, `schema` (JSON Schema; see §4) |
| **flow** | `id`, `name`, `description`, `entry {caller, interface, input, repeat {count, interval_ms}}`, `steps [{component, title, detail, source}]` (narrative), `sources`, `tags` |
| **scenario** | `id`, `flow`, `name`, `description`, `seed`, `input`, `choices {key: option}`, `state {component: partial state}`, `faults [fault]`, `expect [cel]` |

Two more kinds, **config** and **fixture**, and the fields for instances, concurrency, time,
capacity, events, multi-step scenarios and mocks are specified in §11.

`sources` is a list of `{repo, path, line, end_line, sha}`. A component is a leaf when no other
component names it as `parent`; leaves are the smallest components that can be simulated.

## 3. Behavior language

A behavior is how a component handles one of its interfaces. It is an ordered list of steps.
An interface without a behavior or a `store` is a **stub**: it returns fake data generated from its response schema.

Each step has at most one action, plus optional narrative fields: `title`, `detail`, `source`.
When a step with a `title` or `detail` runs, the trace gets a `note`. `when: <cel>` skips the step if false.

| Action | Form | Meaning |
|---|---|---|
| (none) | `title`, `detail` | Narrative note only |
| `set` | `{path: template}` | Assign `vars.*`, `ctx.*` or `state.*`. All right-hand sides are evaluated first, then assigned in sorted path order |
| `call` | `call: <interface id or "=cel">`, `input`, `fill`, `as`, `timeout_ms`, `retry`, `on_error`, `targets` | Synchronous call (§5) |
| `if` | `if: <cel>`, `then: [steps]`, `else: [steps]` | Branch |
| `choice` | `choice: <name>`, `options: {name: [steps]}`, `default: <name or "=cel">` | A named decision point that a scenario can override with `choices: {"<iface>.<name>": option}` |
| `return` | `return: template` | Succeed with a value |
| `fail` | `fail: {code, message, status, retryable, data}` | Fail with an error |
| `emit` | `emit: <interface id>`, `input` | Asynchronous message, delivered after the current top-level call tree finishes |
| `wait` | `wait: <ms or "=cel">` | Advance the virtual clock |
| `foreach` | `foreach: <list or "=cel">`, `as`, `index`, `max`, `steps: [steps]` | A bounded loop: run `steps` once per item, in order |
| `break`, `continue` | `break: true`, `continue: true` | Leave the innermost `foreach`, or go to its next item. Only inside a `foreach` |

**Loops.** `foreach` evaluates its template once. A list runs in order, with `vars.<as>` (default
`item`) holding the item and `vars.<index>` (default `index`) its 0-based position. A map runs in
sorted key order, with `vars.<index>` holding the key. `null` runs nothing; any other value aborts
the run. `max` (default 100, at most 1,000) caps the items: the rest are skipped with a warning.
Iterations are sequential. `return` and `fail` inside the loop end the behavior. When the loop
ends, `vars.<as>` and `vars.<index>` get back the values they had before it.

**Datastores.** An interface with `store` and no behavior performs a declarative operation on its
component's state instead of returning fake data. Rows live in `state.<table>`, a map keyed by
string id (an integer key becomes its decimal string). Scenarios and requests seed tables
through `state` overrides, such as `state: {dynamodb: {vms: {vm-1: {status: running}}}}`.
`key`, `value` and `default` are templates over the request (`input`); `where` is CEL that also sees
`row` (the stored row, `null` when absent) and `key`.

| `op` | Needs | Returns | On a miss |
|---|---|---|---|
| `get` | `key` | A copy of the row. A row failing `where` counts as a miss | `default` when set, else the `not_found` error |
| `put` | `key`, `value` | The row: `value` replaces it | Inserts |
| `update` | `key`, `value` | The row with `value` deep-merged over it | The `not_found` error |
| `delete` | `key` | The removed row | `null` |
| `query` | (no key) | A list of the rows passing `where`, in key order | `[]` |
| `incr` | `key`, `value` | The row after adding `value`: a number, or a map of field deltas | Starts from 0 |

On writes, `where` is a condition: when it is false, the operation fails with the `conflict` error
and changes nothing (`where: "row == null"` is a create-if-absent). `not_found` and `conflict` name
declared errors; without them the interface's declared `not_found` or `conflict` error is used,
or else `{code: not_found, status: 404}` or `{code: conflict, status: 409}`. Every write records a
`set` event on `state.<table>.<key>`. Latency and faults apply as for any call. A store beside a
behavior is ignored, with a validation warning. Store results are not checked against the response
schema.

**Templates.** A string that starts with `=` is a CEL expression; any other value is a literal.
Maps and lists are evaluated recursively. `if`, `when` and `expect` are always CEL.

**CEL variables:** `input` (the request), `state` (this component's state), `ctx` (shared by the
whole run), `vars` (local to the behavior), `attempt` (1-based, inside a call's retry), `now`
(virtual milliseconds) and `error`: the most recent call error. Later successful calls don't clear it,
and inside `on_error` it is the error being handled.

**Ending a behavior.** Without `return` or `fail`, a behavior returns fake data from its response
schema, or null if it has none.

## 4. Fake data and schemas

The supported JSON Schema subset is `type`, `properties`, `required`, `items`, `enum`, `const`,
`format` (uuid, email, date-time, date, uri), `minimum`/`maximum`, `minLength`/`maxLength`,
`minItems`/`maxItems`, `default`, `examples`, `oneOf`/`anyOf` (the first branch), `allOf` (merged) and `$ref`
(a schema id, or `#/schemas/<id>`), plus `x-fake` as a hint.

Generation is deterministic for a given seed. It prefers `const`, then `default`, then
an `examples` entry picked by the seeded RNG, then `enum`, then a value from `format` or the property name, then a random value
within the bounds. Object keys are processed in sorted order.

The engine checks returned values and entry inputs against their schemas. A mismatch is reported
as a **warning**, not an error.

## 5. Simulation semantics

- The simulation is deterministic and discrete-event, with a virtual clock in ms. Its work runs as
  cooperative tasks over virtual time (§13.1 item 14).
  A run is identified by its ontology revision, flow, scenario overrides and seed. The same inputs
  always produce the same trace.
- **Calls.** The engine checks faults, adds the callee's latency, then runs its behavior (or its
  stub). A callee's duration is its latency plus the time of its nested calls.
- **Results.** `as: x` stores `{ok, value, error, attempts, duration_ms, target}` in `vars.x`.
  `on_error` is `propagate` (the default; the error ends the caller with the same error),
  `continue`, or a list of steps to run before continuing.
- **Timeouts.** If the callee takes longer than `timeout_ms`, the caller gets
  `{code: "timeout", retryable: true}` at start + `timeout_ms`. The callee's state changes still
  happen and are marked late, because a timeout doesn't roll back work. The caller's clock resumes
  at start + `timeout_ms`, so trace times can step backwards after a late `call.end`; order by `seq`.
- **Retries.** `retry: {max_attempts (≤20, or "=cel"), backoff_ms, multiplier, max_backoff_ms, codes: [codes], when: cel, title, detail, source}`.
  An error is retried when attempts remain, its code is in `codes` (or it is `retryable` when
  `codes` is absent), and `when` is true. The target and input are re-evaluated with the new `attempt`,
  so a retry can go to another target. A retry's `title`, `detail` and `source`
  narrate the retry event.
- **Faults** apply when a call reaches its target. A fault is
  `{target: component or interface, type: unavailable|error|latency|timeout|lost_reply|crash, code, status, message, retryable, latency_ms, after_steps, calls: [n]}` (lost_reply and crash: §13.1 item 25).
  `calls` lists the 1-based invocations of the target that are affected (each attempt counts as an
  invocation); without it, every invocation is affected.
  `unavailable` returns `{code: unavailable, status: 503, retryable: true}`. `error` faults default to
  `retryable: false`, so a retry without `codes` needs `retryable: true` on the fault.
- **Repetition.** A flow whose entry has `repeat: {count (1 to 100), interval_ms}` runs the entry
  `count` times, as a reconciler or cron would. Each pass delivers its emits, then the clock
  advances `interval_ms` before the next pass. State, `ctx` and the clock carry across passes, and
  every pass gets the same input. The summary's `passes` lists `{pass, result, start_ms, duration_ms}`.
  `result` and `status` describe the last pass.
- **Budgets:** 20,000 events, call depth 64, 1,000 emits and 10,000 `foreach` iterations.
  Exceeding one gives status `aborted`.
- **Trace events:** `call.start`, `call.end`, `note`, `set`, `choice`, `fault`, `retry`,
  `timeout` and `emit`. Each carries `seq`, `t`, `span` and `component`. Warnings appear only in the
  summary.
- **Summary:** `status`, `result`, `duration_ms`, per-interface `calls`, `retries`, `faults`,
  final `ctx`, the final `state` of every stateful or touched component, `initial_state`,
  `assertions` and `warnings`, plus `passes` when the entry repeats.
- **Expectations.** A scenario's `expect` is a list of CEL expressions over `result`, `status`,
  `calls`, `ctx`, `state`, `retries`, `faults`, `warnings`, `duration_ms` and `passes` (one
  entry per pass, `{pass, result, start_ms, duration_ms}`; a single entry without `repeat`). Expectations turn scenarios into
  executable acceptance criteria, and `POST /test` runs them all.
- **Requests** are refused with a request error (the run doesn't start) for an unknown flow or
  scenario, a scenario run under a different flow, an invalid fault, a bad input template, or a
  `choices` key that is not a choice point or names a missing option.
- **Plans** follow the entry through static calls, emits and declared dynamic targets. Entry and
  call targets that are not interfaces are listed in `unknown`, not as reachable or faultable.
  Components reached through store operations appear in `state` even without a declared schema.

## 6. HTTP API (`/v1`, JSON)

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness check |
| `GET, POST /ontologies` | List; create `{id, name, description}` |
| `GET, PATCH, DELETE /ontologies/{id}` | Summary with draft counts; rename; drop |
| `GET, PUT /ontologies/{id}/document?rev=` | Export a whole document; replace the draft with one |
| `GET, POST, PUT /ontologies/{id}/{kind}?rev=` | List; create one; upsert many `{items}` |
| `GET, PUT, PATCH, DELETE /ontologies/{id}/{kind}/{eid}?rev=` | Read; upsert; merge-patch; delete |
| `GET, POST /ontologies/{id}/revisions` | List; create `{message, author}` (422 when invalid, 409 when unchanged) |
| `GET /ontologies/{id}/revisions/{n}` | Revision metadata |
| `GET /ontologies/{id}/diff?from=&to=` | Entity changes between revisions or the draft |
| `POST /ontologies/{id}/validate?rev=` | `{valid, issues [{path, message, severity}]}` |
| `GET /ontologies/{id}/flows/{flow}/plan?rev=` | Reachable interfaces, choice points, stateful components and fault targets |
| `GET, POST /ontologies/{id}/simulations` | List runs; run `{rev, flow, scenario, seed, input, choices, state, faults, expect, fixtures, topology, config, clock, save}` |
| `GET /simulations/{run}` | A run with its trace |
| `POST /ontologies/{id}/test?rev=` | Run every scenario's expectations |
| `GET /system/version?refresh=` | The running build and whether its checkout can be updated |
| `POST /system/update` | Fast-forward the checkout to its upstream, then restart when supervised (§8) |

Server details:
- POST `/simulations` returns 201 when the run is saved and 200 with `save: false`.
- POST `/test` accepts `?save=false`.
- With no revisions, a diff starts from `"base"`, the empty ontology.
- Entity writes, including PATCH, return `{kind, ids, issues}`.
- A plan for a flow with no entry returns 422.
- PUT `/{kind}` also accepts a bare array.
- `counts` is keyed by singular kind.
- A run's `fixtures` apply after the scenario's, then its `topology`, `config`, `clock` and `state` (§11.7).
- A run of a multi-step scenario without a `flow` is listed under its first step's flow.
- Each `/test` result adds `steps` (multi-step scenarios), `mocks` (declared) and `mocked_calls`.
- `/system/version` returns `{version, commit, dirty, branch, upstream, source_dir, update:
  {available, reason?, behind, ahead, latest_commit, latest_subject, checked_at}}`. `commit` and
  `dirty` describe the running build (`vcs.revision` and `vcs.modified` from the build info, else
  `git rev-parse HEAD` in `--source-dir`). `behind` counts `HEAD..@{u}` and `ahead` counts
  `@{u}..HEAD`. mosaicd runs `git fetch` of the branch's upstream at most every 10 minutes and
  caches the result; `?refresh=1` forces a fetch, at most once per 30 s. When `available` is false,
  `reason` says why: no `--source-dir`, not a git checkout, a detached HEAD or no upstream, the
  fetch failed (with git's error), disabled by `--no-self-update`, local changes to tracked files,
  diverged (ahead > 0), already up to date, or the checkout moved past the running build (restart
  to run it).
- `POST /system/update` is accepted only from a loopback remote address, with the bearer token
  when one is set, and with no `Origin` header or an allowed CORS origin (403 otherwise). It
  answers 409 with the reason unless an update is available. It runs `git fetch`, then
  `git merge --ff-only @{u}`, and returns `{updated_to, from, restarting, note}`; a failing git
  command returns 500 with git's stderr and leaves the tree as it was. It never builds: see §8.
  Git runs without a shell, with fixed arguments and timeouts.

YAML input is parsed as YAML 1.2: only `true` and `false` are booleans.

`{kind}` is one of `components`, `interfaces`, `links`, `schemas`, `flows`, `scenarios`, `configs` or
`fixtures`.
Errors have the form `{"error": {"code", "message", "issues"}}`. `mosaicd` binds to loopback.
An optional bearer token (`--token`, `MOSAIC_TOKEN`) is required on every request when set.

`GET /ontologies/{id}/graph?rev=` returns the architecture map: components plus explicit and
derived edges (`model.Graph`). Wire types live in `pkg/api`; TypeScript mirrors them in `web/`.

## 7. CLI (`mosaic`)

The CLI calls `mosaicd` through `pkg/client`. Data is printed as indented JSON by default, so agents
can parse it. The exceptions are `sim run` and `sim get`, which default to `--format summary`, and
`test`, which defaults to `--format text`; pass `--format json` to parse them. The server comes from `--server`
or `MOSAIC_SERVER` (default `http://127.0.0.1:7878`), the token from `--token` or `MOSAIC_TOKEN`, and
the per-request timeout from `--timeout` or `MOSAIC_TIMEOUT` (a Go duration, default `60s`).
Exit codes: 0 success; 1 refusal, validation failure or failed test; 2 usage error; 3 server
unreachable.

```
mosaic health
mosaic ontology list | get <ont> | create <ont> --name N [--description D]
mosaic ontology update <ont> [--name N] [--description D] | delete <ont> --yes
mosaic doc export <ont> [--rev R] [--format json|yaml] [-o FILE]
mosaic doc import <ont> -f FILE                 # replace the draft (YAML or JSON)
mosaic apply <ont> -f FILE -m MSG [--author A]  # import, then create a revision if valid
mosaic get <ont> <kind> [<id>] [--rev R]
mosaic put <ont> <kind> (-f FILE | --json JSON) # upsert one entity, a list, or {"items": [...]}
mosaic patch <ont> <kind> <id> (-f FILE | --json JSON)   # JSON merge patch
mosaic delete <ont> <kind> <id>
mosaic validate <ont> [--rev R]
mosaic revision list <ont> | get <ont> <n> | create <ont> -m MSG [--author A]
mosaic diff <ont> [--from R] [--to R]           # defaults: latest to draft
mosaic graph <ont> [--rev R]
mosaic plan <ont> <flow> [--rev R]
mosaic sim run <ont> (--flow F | --scenario S) [--rev R] [--seed N] [--input JSON|@FILE]
               [--choice KEY=OPTION]... [--state COMPONENT.PATH=VALUE]...
               [--fault TARGET:TYPE[:CODE[:STATUS]][@N,M] | --fault COMPONENT:kill:AT_MS[:INSTANCE] | --fault JSON]...
               [--fixture ID]... [--topology COMP=A,B,C]... [--config ID=VALUE]...
               [--clock-epoch TIME|MS] [--expect CEL]... [--no-save] [--format summary|trace|json]
mosaic sim list <ont> [--limit N]
mosaic sim get <run-id> [--format summary|trace|json]
mosaic test <ont> [--rev R] [--format text|json]
mosaic version [--refresh] [--format text|json]
mosaic update --yes
```

`<kind>` accepts singular or plural names, so configs and fixtures use the generic entity
commands (`mosaic get <ont> configs`, `mosaic put <ont> fixture -f F`). In `--state` and
`--config`, VALUE is parsed as JSON and falls back to a string; `--state` keys may be
`COMPONENT@INSTANCE`. `--clock-epoch` takes an RFC 3339 time or milliseconds. `test` notes each
scenario's step count and its mocks (declared, and calls mocked). `R` is `draft`, `latest` or a
revision number. `sim run --format summary` prints the outcome, assertions and a
one-line-per-call trace, with `@instance` on calls and lines for queue waits, publishes,
parallel joins, scenario steps and deadlines.

## 8. `mosaicd`

```
mosaicd [--addr 127.0.0.1:7878] [--data-dir ~/.mosaic] [--dolt-bin dolt] [--dolt-port 0]
        [--dolt-dsn DSN] [--token T] [--cors-origin http://localhost:3000]
        [--source-dir DIR] [--no-self-update]
```

With no `--dolt-dsn`, it initializes `<data-dir>/dolt` and supervises
`dolt sql-server -H 127.0.0.1 -P <port>` (a free port when 0). It waits for readiness, and on
SIGINT or SIGTERM it stops the child before exiting.

**Self-update.** `--source-dir` names the mosaic checkout mosaicd was built from; without it (for
example, a `go install` binary) updates are reported as unavailable. `--no-self-update` refuses
every update. `scripts/serve.sh` is the supervisor: it builds `bin/mosaic` and `bin/mosaicd`,
starts mosaicd with `--source-dir <checkout>` and `MOSAIC_SUPERVISED=1`, then the web UI
(`pnpm build` and `pnpm start`, or `pnpm dev` with `--dev`) with `MOSAIC_SERVER` set, and
prefixes each process's log lines. After a successful `POST /system/update`, a supervised mosaicd
shuts down gracefully, letting in-flight responses finish, and exits with code 75 (EX_TEMPFAIL).
The supervisor then rebuilds both binaries, stops the UI, runs `pnpm install --frozen-lockfile`
if the lockfile changed and `pnpm build` in production mode, and starts both again. Any other
exit of either process, or Ctrl-C, stops both (each runs in its own process group). Unsupervised,
mosaicd updates the checkout, answers `restarting: false` with a note to restart by hand, and
keeps running.

## 9. Repository layout

| Path | Contents |
|---|---|
| `internal/model` | Entities, documents, strict decoding, validation, plans and graphs (pure) |
| `internal/expr` | CEL environments and templates (pure) |
| `internal/jsonschema` | Fake data and checks (pure) |
| `internal/sim` | The simulation engine (pure) |
| `internal/store`, `internal/doltserver` | Dolt persistence and the server child |
| `internal/api`, `cmd/mosaicd` | The HTTP server |
| `pkg/api`, `pkg/client`, `cmd/mosaic` | Wire types, Go client, CLI |
| `web/` | Next.js UI (`web/fixtures` has API-shaped fixtures from the engine) |
| `.claude/skills/` | Agent skills for ontology CRUD and simulation |
| `examples/envoy` | The worked example: one HTTP request through the Envoy proxy (v1.36.2), cited to Envoy's source |
| `internal/testdata/gateway` | A synthetic inference gateway as an ontology, the test suite's acceptance fixture |

## 10. Commits and per-commit revisions

Each ontology revision can name the code commit it models (`source: {repo, sha, parent, subject,
author, date, url}`). Commits are imported as metadata, with the paths each one changed. The CLI
reads git locally (`mosaic commits import --repo PATH --range A..B --first-parent`), and the
server never touches a repository.

| Method and path | Purpose |
|---|---|
| `POST /ontologies/{id}/commits` | Upsert commit metadata (`ImportCommits`) |
| `GET /ontologies/{id}/commits` | Commits, oldest first, each linked to the revision whose `source.sha` matches, with `changed` set when that revision differs from the previous one |
| `GET /ontologies/{id}/commits/{sha}` | `CommitDetail`: the revisions before and after, entity changes, and `model.Impact` |
| `GET /ontologies/{id}/impact?from=&to=` | `model.Impact` between any two revisions |

`model.ComputeImpact(before, after)` lists added, removed and modified entities by kind (an entity
whose only change is its citations is listed as `cited`, not modified). It also lists **affected
flows**: flows present and unchanged in both documents whose reach contains a changed entity. A
flow's reach is a set of interfaces, the caller and the components providing those interfaces
with their ancestors, and the schemas the interfaces reference, transitively.

`internal/impact.Compute` (used by `CommitDetail`, the impact endpoint and the history devtool)
takes the entity sets from `model.ComputeImpact` and recomputes affected flows on the **traces**
basis. A flow's reach uses the interfaces its scenarios actually call when simulated: every
`call.start` in the traces, including async calls delivered from emits. The scenarios run against
the before and after documents separately, and the flow is affected when a changed entity is in
either reach, so a removed interface counts through the before trace. A flow with no runnable
scenarios in a document falls back to its **static** reach there: every call, emit and declared
dynamic target on every branch. Static reach overstates a lot. For example, a transport with a
dozen dynamic route targets puts every flow through it in reach of everything. Each
`FlowImpact` records its `basis`: `traces`, or `static` when either side fell back. Exercised
reach is computed lazily per flow, in parallel, and cached per document. The store keys its cache
by ontology, revision number and revision hash, since revisions are immutable. A draft, or a
document with no key, is keyed by content hash. A revision can be created with `allow_empty`
when a commit changes no modeled code, so every commit has a revision to compare.

The UI has a **Commits** view. Selecting a commit shows the architecture before and after, with
added, removed and modified components marked, and the flows the commit created, modified or
affected, with a diff.

## 11. Language additions for systems with many parts (still `schema_version: 1`)

The Cassandra benchmark (`examples/cassandra/RESULTS.md`) found the gaps these additions close.
None of them is specific to one system. Every addition is optional, and a document that uses none
of them behaves exactly as before. Before it was accepted, each one was checked against at least
three different kinds of system (§11.10).

### 11.1 Instances and topology

A component can have **instances**: several copies of the same code, such as nodes, brokers,
pods, editor windows or GPU workers. A **topology** names them:

```yaml
topology: {cassandra-node: [n1, n2, n3]}   # in a fixture, a scenario or a run request
```

- **Groups.** A topology entry names a component, and it applies to that component's whole
  subtree. A component belongs to the instance group of its nearest ancestor that has a topology
  entry, or of itself. A component with no group has exactly one, unnamed, instance (`""`).
- **`self`** is a CEL variable holding the instance the current behavior runs on (`""` without a
  group). A flow's entry runs on the first instance of the entry component's group, or on the
  instance named by `entry.on`, or by the step's `on` in a multi-step scenario.
- **Targeting.** A `call`, `emit` or `publish` step can take `on: <instance or "=cel">`.
  Without `on`:
  - a callee in the caller's group runs on the caller's instance;
  - a callee in another group runs on that group's first instance, with a warning when the group
    has more than one instance;
  - a callee with no group runs on its single instance.

  An `on` naming an unknown instance fails the call with `{code: unknown_instance}`.
- **State is per instance.** A component's state lives at `state[<component>@<instance>]`, or at
  `state[<component>]` for the unnamed instance. A behavior's `state` variable is its own
  instance's state. Overrides in fixtures, scenarios and requests use the same keys
  (`state: {"gossiper@n2": {...}}`). Stores keep their tables per instance.
- **Faults** take an optional `instance`. Without one, a fault applies to every instance.
- **The trace.** Events carry `instance`. The summary's `calls` counts per interface, as before,
  and adds `calls_by_instance` keyed `<interface>@<instance>`.

### 11.2 Concurrency: `parallel` with a join rule

```yaml
- parallel: "= vars.replicas"   # a list, or a map in key order; or `branches: [[steps], ...]`
  as: replica                    # vars.replica in each branch (and `index`)
  steps: [...]                   # the branch body
  join: {need: "= vars.block_for"}   # an int or "=cel"; or `all` (default) or `any`
  stagger_ms: 0                  # branch i is due at i*stagger_ms (hedging); a due branch starts only while the join is unmet
  timeout_ms: 2000               # optional, for the join as a whole
  as_result: acks                # optional: vars.acks
  on_insufficient: {code: unavailable, status: 503}   # optional; the default is {code: insufficient, retryable: true}
```

- **Semantics.**
  - Branches are **concurrent in virtual time**. Each one starts at the step's start time (plus
    any stagger) on its own forked clock.
  - A branch **succeeds** when its steps finish without failing, and **fails** when a step fails
    or an error propagates.
  - The join is satisfied when `need` branches have succeeded. The step then completes at the
    finish time of the `need`-th success.
  - It fails with `on_insufficient` as soon as success is impossible. The error data is
    `{received, required, failed}`.
  - It fails with `{code: timeout, retryable: true, data: {received, required}}` at
    start + `timeout_ms`, or at the request deadline (§11.3), whichever is earlier.
- **Branches still run after the join completes.** Branches that are still running (or are due
  and unstarted, without staggering) run to completion. Their trace events after the join time
  are marked `late`, as with call timeouts today.
- **State is not interleaved between branches.** Branches run in list order. Each one sees the
  state the earlier branches left, and its events carry their true virtual times, so the trace
  is ordered by `seq`, not `t`. The model doesn't express interleaving of shared state between
  concurrent branches.
- **The result.** `as_result` holds `{ok, received, required, failed, duration_ms, results:
  [{item, index, ok, value, error, start_ms, end_ms, late}]}`, where `value` is the branch's last
  `return` (a `return` inside a branch ends only the branch). The clock resumes at the join's
  completion time. `foreach` keeps its sequential semantics.

### 11.3 Time: one clock, deadlines, timers, latency

- **One clock.** `now` is `epoch_ms + virtual ms`. `epoch_ms` comes from the fixture, scenario or
  request (`clock: {epoch: "2026-10-30T00:00:00Z"}` or `{epoch_ms: N}`), and is 0 by default, so
  existing models are unchanged. Every timestamp a model stores or compares must derive from
  `now`. Behaviors must never invent wall-clock literals. A validation warning flags numeric
  literals over 10^12 that are compared with `now`.
- **Deadlines.** A flow `entry`, a scenario step or a `call` can set `deadline_ms`, relative to
  when it starts. The deadline is inherited by every nested call and branch, and the earlier
  deadline wins. A call's effective timeout is `min(timeout_ms, deadline - now)`. A call that
  starts at or after the deadline fails at once with `{code: deadline_exceeded, retryable:
  false}`. CEL `deadline` is the absolute deadline in ms (`null` if none). Retries stop when the
  next attempt would start after the deadline.
- **Timers.**
  - `emit` and `publish` take `after_ms` (a delay) and `every_ms` with `count` (periodic). Timers
    are delivered in time order after the current top-level call tree, as emits are today.
    Within the same time they are delivered in schedule order.
  - `entry.repeat` takes `initial_delay_ms`.
  - Each run has a budget of 1,000 timer deliveries.
- **Latency as an expression.** `latency_ms` can be `"=cel"`, evaluated over `input`, `state`,
  `config` and `self`. For example, prefill time grows with the number of tokens.

### 11.4 Capacity

`capacity: {concurrency: N}` on a component means each instance serves at most N calls at once.
This models thread pools, stages, connection pools, GPU streams and worker slots.
- A call that arrives while all slots are busy waits until the earliest slot frees, in arrival
  order, and the trace gets a `queue` event with the wait.
- `queue_limit: M` bounds the waiting calls. Past it, the call fails with
  `{code: overloaded, retryable: true}`. `queue_timeout_ms` bounds the wait.
- Busy intervals are tracked per instance in virtual time, so capacity interacts with `parallel`
  branches and timers.

### 11.5 Events with subscribers

An interface can declare `subscribe: [<topic>, ...]`. A topic is any slug, conventionally the id
of an `event`-kind interface.
- `publish: <topic>` with `input` delivers the input to every subscriber, in sorted interface id
  order, on the publisher's instance unless `on` is given.
- `delivery: sync` runs the subscribers inline, like JavaScript and VS Code emitters. Their errors
  are recorded and don't fail the publisher unless `on_error: propagate`.
- `delivery: async` (the default) queues them, like `emit`.
- Static reach and plans include the subscribers.

### 11.6 Config

A new entity kind, **config**:

```yaml
configs:
  - {id: write-request-timeout-ms, type: integer, value: 2000, default: 2000, summary: ..., sources: [conf/cassandra.yaml:1330, src/.../Config.java:120]}
```

- `value` is the deployed value, and `default` the code default. Both are kept so that
  differences stay visible.
- CEL `config` is a map from id to value. Fixtures, scenarios and requests override it with
  `config: {id: value}`.
- Validation warns about `config.<id>` references to unknown ids.
- The UI lists configs with their deployed and default values.

### 11.7 Fixtures and multi-step scenarios

A new entity kind, **fixture**, is a named, shared starting world:

```yaml
fixtures:
  - id: three-node-rf3
    topology: {cassandra-node: [n1, n2, n3]}
    clock: {epoch: "2026-10-30T00:00:00Z"}
    config: {hinted-handoff-enabled: true}
    state: {"token-metadata@n1": {...}, keyspace: {tables: {...}}}
    extends: [base-schema]       # applied first, in order
```

A scenario lists `fixtures: [ids]`, applied in order. Then its own `topology`, `clock`, `config`
and `state` apply on top. Deep merge is used for state and config. Topology entries replace
earlier ones.

A scenario can have **steps** instead of a single entry call:

```yaml
scenarios:
  - id: prepare-then-execute
    fixtures: [three-node-rf3]
    steps:
      - {flow: native-prepare, input: {...}, as: prep}
      - {flow: native-execute, at_ms: 10, input: {id: "= steps.prep.result.value.id"}, on: n1}
      - {interface: gossiper.gossip-task-run, caller: operator, on: n2}
    expect: ["steps.prep.result.ok", "result.ok"]
```

- **Each step** names a `flow` (its entry, with the step's `input` merged over the entry input)
  or an `interface` with a `caller`. It can also set `input`, `on`, `choices`, `deadline_ms` and
  `at_ms`. `at_ms` is the absolute virtual time at which the step starts; by default a step
  starts when the previous step and its timers have finished.
- **State, ctx, clock, timers and capacity carry over** between steps.
- **Expectations and step templates** see `steps.<as>` (or `steps[i]`) as
  `{result, status, duration_ms, start_ms}`. `result` and `status` are those of the last step.
- The scenario's `flow` may be omitted with steps. It then defaults to the first step's flow, for
  grouping.

### 11.8 Assertions on the trace, mocks and CEL helpers

- **The trace in expectations.** Expectations see `trace`: a list of `{seq, t, type, interface,
  component, instance, input, output, error, late, title, key, option}` events. Ordinary CEL
  macros query it. For example:
  `trace.exists(e, e.type == 'call.start' && e.interface == 'commit-log.add' && e.instance == 'n2')`.
- **Mocks, a last resort.** A scenario can list `mocks: [{interface, instance, when: <cel over
  input>, return: <template> | fail: {...}, calls: [n]}]`. A matching call returns the mock
  instead of running the behavior, and the trace marks it `mock`. Mocks are for isolating one
  fragment. The check tool reports how many each scenario uses, and the generation pipeline
  forbids them in merged-model scenarios.
- **CEL helpers.** In every environment:
  - the two-variable comprehension macros (`transformMap`, `transformList`, `all`/`exists` with
    two variables);
  - `sum(list)`, `merge(map, map)` (a deep merge, the right side winning) and `omit(map, key...)`;
  - `random(n)`, which is seeded per run and deterministic, giving an int in `[0, n)`.

### 11.9 What the summary adds

- `calls_by_instance`.
- `steps`: the step results of a multi-step scenario.
- `queued`, a count of queue waits.
- `mocks`, a count of mocked calls.
- `executed`: the sorted set of **behavior step paths** that ran, such as
  `storage-proxy.mutate:behavior[3].then[0]`. This is for the behavior coverage tooling (§12).

### 11.10 Generality check

Each addition was written down only after it could model the same behavior in three unlike
systems:

| Addition | Cassandra | VS Code (front end) | vLLM (GPU serving) |
|---|---|---|---|
| instances | nodes n1–n3 | windows, extension hosts, webviews | API server, engine core, GPU workers per rank |
| parallel + join | QUORUM writes, speculative reads | `Promise.all` across extension activations; first-provider-wins completion | tensor-parallel all-reduce (`all`), worker RPC fan-out |
| deadlines | request timeouts | cancellation tokens with timeouts | request deadline and abort |
| timers | gossip every 1s, hint dispatch every 10s | debounced saves, file watcher polling | the scheduler step loop |
| capacity | stages, thread pools | the extension host's single thread (`concurrency: 1`) | max running sequences, GPU stream slots |
| publish/subscribe | endpoint state subscribers | `Emitter`/`Event` (sync) | engine output streams |
| config | `cassandra.yaml` | settings with workspace overrides | engine args (`max_num_seqs`, `gpu_memory_utilization`) |
| latency expressions | compaction by bytes | layout by line count | prefill by tokens, decode by batch size |
| fixtures + steps | write then read; PREPARE then EXECUTE | open file → edit → save | add request → n scheduler steps → output |

## 12. Model quality tooling

The tooling targets the failure the benchmarks found: scenarios that pass while the model is
wrong.

- **Behavior coverage.** `check --behavior-coverage` takes the union of every scenario's
  `executed` set and reports, per interface, the behavior steps no scenario runs. It reports
  totals per fragment, and lists the unexecuted `fail` and `if` branches.
- **Hollow-scenario lint.** A scenario none of whose expectations mentions `state` or `trace` is
  flagged when:
  - its run records `set` events on component state (state changed, but nothing checks it); this
    fails the check; or
  - *(advisory)* its run's result is ok and records no state `set`, though its flow can reach a
    state-writing interface: a `store` with op `put`, `update`, `delete` or `incr`, or a behavior
    that sets `state.*`. Store reads (`get`, `query`) don't count, and refusals and errors are
    exempt. This is a warning only. Sampled on the Cassandra and gateway-platform models, about 3 in 10
    of its hits were real; the rest were no-op or read paths that change nothing by design
    (`examples/*/quality-baseline.md`).

  State on **incidental** components doesn't count for either rule. A component is incidental when
  it, or an ancestor, has kind `cache`, `limiter` or `metrics`, or a tag of the same name or
  `incidental`. Writes there are bookkeeping, not effects to assert. A run that touches only
  incidental state counts as changing nothing.

  The lint is opt-in (`--lint hollow`) and is required in the pipeline's verify step. Its gate is
  the unchecked-state rule and the `writes` rule below; the advisory rule only warns.
- **Effects across steps.** The pipeline asks each write flow to have at least one multi-step
  scenario that writes and then reads the effect back.
- **Mocks** are counted, and refused under `--no-mocks`.

## 13. Generation pipeline

`docs/PIPELINE.md` and the `mosaic-generate` skill describe one repeatable way to build an
ontology from any repository. A per-repo **profile** (`examples/<repo>/profile.yaml`) holds what
differs between repos:

- the snapshot (repo, sha, path);
- the inventory kinds and their language plugins;
- the area split, with owned paths and overrides;
- naming rules;
- the error convention;
- the deployed config sources;
- the shared fixtures;
- the test oracle (which test directories to mine, and how to run nothing);
- independence rules.

The stages are the same for every repo:

1. **Inventory.** Entry points by language plugin, measured for precision and recall.
2. **Skeleton and contracts.** Deployables and modules, fixed ids, shared shapes, the error
   convention, owners.
3. **Fixtures.** The shared worlds (topology, config, seed state), owned by the coordinator, and
   written before fan-out.
4. **Fan-out.** One agent per area, under the generic brief plus the profile.
5. **Reconciliation.** A merged check, then a contract-fix round run by the coordinator's
   decisions.
6. **Test oracle.** Agents translate a sample of the repo's own tests into scenarios against the
   merged model. A failure is a model bug or a recorded simulator gap.
7. **Judging.** Independent judges verify a benchmark of well-known behaviors against the code
   first, then score the model (pass, partial, fail, missing, sim-gap), with root causes.
8. **Results.** Scorecards, model fixes, and simulator gaps feeding mosaic's roadmap.

### 13.1 Clarifications (binding)

1. **Durations can be templates.** `timeout_ms`, `deadline_ms`, `after_ms`, `every_ms`,
   `stagger_ms`, `count` and `join.need` take either a number or a `"=cel"` template. A template is
   evaluated in the behavior environment when its step runs, so it can read `config`.
2. **What expectations see.** Besides the variables in §5, expectations see `config` (the
   effective values), `topology`, `calls_by_instance`, `steps` and `trace`. They don't see `self`
   or `deadline`, which belong to behaviors.
3. **`at_ms` in the past.** A scenario step whose `at_ms` falls before the previous step has
   finished starts when that step finishes, and the run records a warning. *Superseded by item 14:*
   in every run, an `at_ms` step starts on time even while earlier steps run, and `await: false`
   moves straight on. Without either, a step waits for the previous one's emits and timers. For
   concurrency inside a step, use `parallel`.
4. **Merging configs and fixtures.** Each id has one owner. Identical duplicates merge silently.
   Differing duplicates are a merge error, except for a duplicate marked
   `attributes: {boundary: true}`, which is a reference and defers to the owner. In the pipeline,
   the coordinator owns `fixtures.yaml` and configs belong to the area that reads them.
5. **The check tool's flags.** `--behavior-coverage`, `--lint hollow`, `--no-mocks`,
   `--scenario` and `--trace`.
6. **Run flags.** `mosaic sim run` and `POST /simulations` take `fixtures`, `topology`, `config`
   and `clock`.
7. **Write flows.** A flow tagged `writes` must have at least one multi-step scenario that reads
   its effect back. The check tool reports violations under `--lint hollow`.
8. **The test oracle.** It reads the repo's tests; it never runs them.
9. **Engine output names**, which the server, web and devtools code against:
   - **Event:**
     - new fields: `instance` (string), `mock` (bool), `wait_ms` (int, on `queue`), `topic`
       (string, on `publish`), `branch` (int, the branch index inside a `parallel`);
     - new types: `queue` (a call waited for capacity), `publish` (with `topic`, followed by
       subscriber calls or emits), `parallel.start` (with `output: {branches, need}`) and
       `parallel.end` (with `output` set to the `as_result` value, and `error` when the join
       failed), `step.start` and `step.end` (multi-step scenarios, with `key` set to the step's
       `as` or index), and `deadline` (a call refused because the deadline passed).
   - **Summary:** `calls_by_instance` (map), `steps` (a list of `{as, flow, interface, on, result,
     status, start_ms, duration_ms}`), `queued` (int), `mocks` (int), `executed` (a sorted list of
     step paths formatted `<interface id>:behavior[i].then[j].steps[k]...`, using the field names
     `then`, `else`, `options.<name>`, `steps`, `branches[b]` and `on_error`).
10. **Engine choices made during implementation (binding):**
    - **Instance counts.** `calls_by_instance` lists named instances only.
    - **Capacity.** A capacity queue timeout fails with `overloaded`.
    - **Parallel branches.** Each `parallel` branch gets a copy of `vars`, and a branch result
      also carries `started`.
    - **Deadlines.** Retries stop when the next attempt would start at or after the deadline.
    - **Instanced state.** A plain state key (with no `@instance`) for a component that belongs
      to an instance group applies to every instance.
    - **Scenario steps.** A scenario step ignores its flow's `entry.repeat`.
    - **Timers.** A sync `publish` fired from a timer is delivered async, with a warning.
    - **Map order.** Maps iterate in sorted key order everywhere the engine controls the order.
      Maps built inside an expression (`transformMap`) keep CEL's order, so models must not
      depend on that order.
11. **Event conventions (binding):**
    - `timeout` and `deadline` events describe the **caller**: their `component` and `instance`
      are the caller's, and `to` is the callee. `call.*` events describe the callee.
    - Store `set` events carry `table` and `key` (the raw row key). `path` stays for backward
      compatibility, but it's ambiguous when a key contains dots.
    - A parallel join reports `timeout` (not `on_insufficient`) whenever its branches failed
      because of the join's `timeout_ms` or the inherited deadline.
12. **Additions from the Cassandra round 2 gaps (binding):**
    - **Fail-fast joins.** `join.count_unstarted` (bool, default `true`). When it's `false`, a
      branch that hasn't started yet (it's still waiting on its `stagger_ms`) doesn't count
      toward possible successes. The join then fails with `on_insufficient` as soon as
      `need > succeeded + running`. A pending staggered branch that never starts is skipped.
      This is how quorum reads fail at once on replica failures while a speculative request is
      still unsent. A branch counts as running from its due time, so the check also applies at
      the step's start. Since `i*stagger_ms` would delay every branch after the first, a
      `stagger_ms` template is evaluated once per branch after the first, with that branch's
      `vars.<as>` and `vars.<index>`, and gives its delay after the previous branch: a constant
      keeps the `i*stagger_ms` spacing, and `"= vars.it.speculative ? 2500 : 0"` delays only the
      speculative branch.
    - **Late replies.** `parallel` takes `on_late: [steps]`. The steps run once for each branch
      that finishes after the join completed, at that branch's end time, as async work delivered
      like a timer. They see `vars.<as>` (the item), `vars.<index>` and `vars.late` (the branch
      result `{ok, value, error, start_ms, end_ms}`). Their effects are marked `late`.
      Clarifications: they run at the branch's end time even when the clock has moved past it
      (the clock then resumes where it was), carry `branch`, have no deadline, count toward the
      timer budget, and an error or `return` ends only that run. With `branches`, `vars.<as>`
      is null and `vars.<index>` is the branch index.
    - **Past `at_ms`.** A scenario step whose `at_ms` is earlier than the previous step's end
      records the warning `step <n>: at_ms <t> is before the previous step ended (<e>); started at
      <e>`, as item 3 already requires.
    - **Deleting keys.** A `null` value in fixture, scenario or request `state` or `config`
      overrides deletes that key (after the deep merge, in application order). Clarifications:
      the null deletes a key that the earlier layers, the config's value or the component's
      initial state set; for a key nothing set, it stays a null value, as before, so a row an
      override introduces can hold null fields. A null for a whole state key
      (`state: {svc: null}`) drops the earlier overrides of it, so the initial state applies.
      Under the deep merge `{}` changes nothing, so it can't clear a map: null the map's keys, or
      null the map in one layer and set `{}` in a later one.
    - **The check tool** gains `--state`, which prints each run scenario's final state.
13. **Coverage levels (binding).** Entry-point coverage reports two levels.
    - **registered:** some reachable component or interface cites the entry. This is today's
      `line`/`name` status.
    - **modeled:** an interface that cites the entry (or is named for it) has a behavior or a
      `store`, **and** at least one scenario's trace calls it.

    `check --inventory` prints both levels per kind and per area. `--min-modeled R` fails when
    modeled / (entries − skipped) is below R. The pipeline gate is `--min-modeled 0.5` per area.
    A file that defines no interface with a behavior or a `store` (a skeleton, a fixtures file)
    is reported as exempt and doesn't fail the gate.
    Registration-only coverage is honest for registries, but it isn't evidence that the behavior
    is modeled.
14. **Concurrency in time (binding; from the VS Code benchmark).** The engine becomes a
    cooperative scheduler over virtual time:
    - **Tasks.** Every top-level unit is a task: the entry call, each scenario step, each timer
      or emit delivery, and each `parallel` branch.
    - **Yielding.** A task yields when it advances virtual time: a callee's latency, a `wait`, a
      call blocked on capacity, or the time until a `timeout_ms` or deadline fires.
    - **Ordering.** The scheduler always resumes the task with the earliest resume time. Ties go
      by creation order, then by `seq`, so runs stay deterministic.
    - **Shared state.** State, ctx and stores are shared and read live, so concurrent tasks
      interleave their effects in time order.
    - **Backward compatibility.** A document that uses none of the features below produces the
      same results as before, apart from `parallel` branches, which now interleave instead of
      running one after another. The existing tests and the three example models must still
      pass.
    - **Scenario steps.**
      - A step with `at_ms` starts at that time, even while earlier steps or timers are still
        running.
      - A step without `at_ms` starts when the previous step has ended: its call tree has
        finished and its emits and timers are delivered. This holds in every run (see "Steps
        in concurrent runs").
      - `await: false` on a step starts it and moves straight on to the next step.
      - The run ends when no tasks or timers remain, or after `max_virtual_ms` (default 3,600,000)
        with a warning.
    - **Cancellation.**
      - `token: <name>` on a call, `wait` or `parallel` ties it to a cancellation token.
      - A `cancel: <name>` step (in a behavior or a scenario step) cancels it. Every call or wait
        bound to the token that's still pending fails with `{code: canceled}` at the cancel time,
        and its callee's later effects are marked `late`.
      - The CEL `canceled(name)` reads a token.
      - Tokens are run-wide names; use `= vars.x` templates to make them unique.
    - **Restarting an instance.** A `restart: {component, instance, keep: [component, ...]}` step
      (in a scenario step or a behavior) resets the state of every component in that instance
      group to its fixture/scenario initial state, except the components in `keep`. It also
      cancels the instance's pending tasks and timers, and emits a `restart` event.
    - **Emit timing.** An emit made by a callee that finishes after its caller's timeout is
      delivered at the callee's own end time, not at the timeout.
    - **Expressions as data.**
      - The CEL helper `eval(expr, vars)` evaluates a CEL source string against the map `vars`,
        sandboxed: no access to the run's variables, and the same cost limit. VS Code `when`
        clauses, policies and feature flags held as data use it.
      - `replace(s, regex, repl)` and `matches(s, regex)` (re2) round out the string helpers.
    - **Dynamic `set` paths.** A `set` key that starts with `=` is evaluated to a path string,
      e.g. `"= 'state.sessions.' + vars.id"`.
    - **Engine choices and deviations (binding).**
      - **Concurrent and sequential runs.** A run is *concurrent* when its document uses
        `token`, `cancel` or `restart` in a behavior, or its scenario has a step with `await`,
        a `cancel` or `restart` step, or `max_virtual_ms`. Only concurrent runs interleave
        `parallel` branches and overlap steps as described above. Every other run keeps the
        pre-item-14 results: branches run one after another on forked clocks, and a step
        ends (and the next starts) once its emits and timers are delivered, with the
        item 3 warning for a past `at_ms`. *Deviation:* universal interleaving changed the
        outcome of 6 `cassandra.json` scenarios that read a late branch's effects at the join
        time (a hint written at 2,023 ms seen by the 50 ms join), and waiting only for the
        call tree failed about 40 `vscode.json` and `cassandra.json` step scenarios that rely
        on the previous step's emits and timers. Setting `max_virtual_ms` opts a scenario in.
      - **Steps in concurrent runs.** A step ends as it does in a sequential run: once its call
        tree has finished and its emits and timers are delivered. The driver also moves on
        when every other task is an idle consumer (blocked on a `receive` with no timeout,
        like a server loop started by an emit), because such a loop never ends by itself. Its result, `step.end` and
        `duration_ms` are recorded then. A scenario therefore means the same in both modes,
        and a token added anywhere in the document can't change it. Only `at_ms` (start on
        time, whatever is still running) and `await: false` (go straight on) overlap steps.
        *Revision (2026-10-31):* concurrent runs used to end a step with its own call tree.
        When a VS Code area added one cancel token, that flipped the whole document to
        concurrent and broke 21 read-back scenarios in other areas. Step templates see only the
        steps that have finished (`steps[i]` is absent until then). The run's result is the
        last step's, after every task has finished.
      - **`max_virtual_ms`** applies when the scenario sets it; the default (3,600,000)
        applies only to scenarios with `await`, `cancel` or `restart` steps, since runs
        without them could already last hours and are bounded by the budgets. Tasks
        cut off by the limit end with `{code: canceled}`.
      - **Lanes.** The emits and timers of one root (the entry's pass, or a step) are
        delivered one at a time in `(due, schedule order)`, after the root's call tree, as the
        drain did; lanes of different roots interleave.
      - **Timeouts stay inline.** A callee that outlives `timeout_ms` or a deadline still runs to
        its end inside the caller's task, and the caller's clock steps back (§5). Only a
        token-bound call runs its callee as its own task: on cancel the caller resumes at the
        cancel time and the callee runs on, its later events marked `late`.
      - **Tokens.** `token` also goes on `emit` and `publish`: a cancel drops their pending
        deliveries. A call or wait bound to a token that is already canceled fails at once.
        A canceled `wait` fails with `{code: canceled}` and takes `on_error`. A `cancel` event
        (`key` = the token, `output.pending` = calls, waits and deliveries canceled) records each
        cancel. Scenario steps `{cancel: name}` and `{restart: {...}}` name no flow or interface.
      - **Restart.** Without `instance`, a behavior restarts its own instance when the component
        is in its group, and a scenario step the group's first instance. Components with no
        group restart their subtree. Touched keys with no starting state become `{}`. Tasks
        whose root call runs on the instance, other than the restarting task and its
        ancestors, are canceled (a canceled step or branch fails with `canceled`). The event's
        `output` is `{reset, kept, canceled, dropped}`.
      - **Parallel in concurrent runs.** A branch still running at the join appears in
        `as_result` with `ok: false`, `end_ms: null` and `late: true`; the trace's `parallel.end`
        output is completed with its outcome when it finishes. A token-bound `parallel` fails with
        `canceled` and its running branches' later events are late. The join is evaluated after
        every other task due at the same time, so it sees each branch that ends then.
      - **Capacity.** A call that finds every slot held by calls still in progress waits until one
        is released, in arrival order. Its `queue` event is recorded when the wait ends, at the
        arrival time.
      - **Run duration** counts the roots and lanes, not branches that outlive their join or
        canceled callees, as before.
      - **`eval`** parses its source with the CEL standard library and the pure helpers (not
        `random`, `canceled` or `eval`), and resolves identifiers from `vars` alone: an
        unknown one is an error. A dynamic `set` path splits on `.` into non-empty segments
        under `vars`, `ctx` or `state`.
15. **Quality tooling additions (binding).**
    - **`--lint trivial`.** Lists flow-reachable interfaces that cite an inventory entry but whose
      behavior is trivial: only `return`, or at most two `set` steps with no call, `if`,
      `choice`, `fail`, `emit`, `publish` or store. It reports a share per fragment.
      **`--max-trivial R`** fails when a fragment's share is above R.
    - **Substantive modeled.** The modeled report adds `substantive` (modeled entries whose
      interface isn't trivial) per kind and fragment. **`--min-substantive R`** gates on it.
    - **Skip validation.** A skip entry may name `covered_by: <entity key>`. `assign_inventory.py`
      rejects skips whose `covered_by` doesn't exist in the merged fragments, and skips whose
      reason says "covered by" without the field.
    - **Generated worlds.** `assign_inventory.py --worlds` writes `worlds.yaml` from the profile's
      `fixtures.worlds` (a `full-<id>` for each) plus every `<area>-seed`, so it can't go stale.
    - **Oracle in the build (pipeline stage 4b).** Before hand-off, each area agent gets 3 sampled
      tests from its own paths (`sample_tests.py --area <id>`), translates them into scenarios in
      its own fragment, and must make them pass, or record each one as untranslatable or a
      sim-gap. The end-of-pipeline oracle draws a **different** seeded sample.
    - **Shared data has one owner.** The profile gains `shared_data: [{datum, owner, readers}]`
      (for example, the text of an open document belongs to editor's text model). Other areas
      read through the owner's interfaces and never keep a copy.
16. **Microsecond time (binding; from vLLM).** The virtual clock counts **microseconds**
    internally.
    - **Inputs:** every `*_ms` input (latency, `wait`, `timeout_ms`, `deadline_ms`, `after_ms`,
      `every_ms`, `stagger_ms`, `at_ms`, `interval_ms`, fault `latency_ms`) accepts fractional
      numbers. A `latency_ms` template may return a float (`0.005` is 5 µs).
    - **Outputs:** existing integer ms fields keep their names and become `floor(us / 1000)`.
      So a document with only whole-ms inputs produces byte-identical results. New fields carry
      the exact values: `t_us` and `duration_us` on events, `duration_us` on the summary, steps
      and passes, and `start_us`/`end_us` on branch results.
    - **CEL:** `now` stays in whole ms, always an integer (rounded down), so its type never
      changes. `now_us` is the exact integer microsecond clock. Expectations can use `duration_us`.
    - **Web:** traces show sub-millisecond durations.
    - **Engine choices (binding).** Fractional inputs are rounded to the nearest µs. The `*_us`
      outputs (`t_us`, `duration_us`, `start_us`/`end_us`) appear only in runs whose clock leaves
      whole milliseconds, so whole-ms runs stay byte-identical; expectations and the trace seen by
      CEL always have `duration_us`, `t_us` and `steps[i].duration_us`. A whole-ms `{min, max}`
      latency draws in ms as before; a fractional one draws in µs. `count`, `max_attempts`,
      `backoff_ms`, `queue_timeout_ms` and `max_virtual_ms` stay whole. Templates such as `wait`
      and `latency_ms` that return a float keep its fraction (they were truncated to ms before).
17. **Rendezvous (binding; from vLLM's collectives).** A step can meet other tasks:
    `rendezvous: <name or "=cel">`, `count: <n or "=cel">`, `value: <template>`, `as: <var>`,
    `timeout_ms`.
    - **Waiting:** a task that reaches the step blocks until `count` tasks have arrived at the same
      name in the same generation.
    - **Release:** all of them then resume together, at the latest arrival time plus the step's
      latency (`latency_ms` on the step, which may be a template). Each one gets
      `vars.<as> = {values: [each arrival's value, in arrival order], index: <its own arrival
      index>, count}`.
    - **Generations:** a name is reusable. Once `count` tasks have arrived, the next arrival
      starts a new generation.
    - **Timeout:** past `timeout_ms` or the deadline, waiters fail with
      `{code: timeout, data: {arrived, count}}`.
    - **Reach:** the step opts the run into concurrency (item 14). Coverage and reach treat it as
      a plain step.

    This models collectives (an all-reduce where every rank calls in once), barriers and
    consensus rounds without the N × N fan-out.
    - **Engine choices (binding).** A timeout breaks the generation, like a broken barrier: the
      first waiter to time out fails every waiter of that generation at once, each with the same
      `{arrived, count}` (`arrived` counts the waiters), and the name starts a new generation.
      The count comes from the generation's first arrival, and a different count warns. The last
      arrival's step supplies the latency. A failed rendezvous takes `on_error`, as a call does.
      Each waiter records a `rendezvous` event (`key` = the name, `output` = `{generation, index,
      count}`, `error` on timeout) when it resumes.
18. **Streams, channels and kills (binding; from vLLM and VS Code).**
    - **Streaming responses.**
      - A behavior step `yield: <template>` sends one item to the caller while the callee keeps
        running.
      - A caller opts in with `stream: true` on the `call`, and handles items with
        `on_item: [steps]`. The steps see `vars.item` (the yielded value) and `vars.item_index`,
        and run at each yield's virtual time, interleaved with the callee in the cooperative
        scheduler.
      - The call's final result is the callee's `return`. The summary records each yield as a
        `yield` event with its item.
      - Without `stream: true`, the yields are collected, and the caller gets `{items: [...],
        value: <return>}` when the callee finishes.
      - Opting in to streaming opts the run into concurrency.
    - **Channels (blocking receive).**
      - `put: <channel or "=cel">` with `value: <template>` adds an item to a named run-wide FIFO
        channel. `capacity` (optional) makes it block when full.
      - `receive: <channel>` with `as: <var>` and `timeout_ms` blocks the task until an item is
        available. With a timeout, it fails with `{code: timeout}`.
      - A behavior can't rendezvous with itself on a channel, so a put and a receive must be in
        different tasks.
      - The CEL `channel_len(name)` reads the queue length.
      - This models busy loops waiting on input queues, worker pools and producer/consumer
        pipelines, without polling.
    - **Killing instances.**
      - A fault `{type: kill, instance: <i>, at_ms: <t>}` (or a step `kill: {component, instance}`)
        terminates an instance at virtual time t. All of its running tasks stop, their pending
        calls fail with `{code: killed}`, callers waiting on them get `{code: peer-killed}`,
        rendezvous and channel waits involving it fail, and its state is marked `dead: true`.
      - A later `restart` (item 14) revives it.
      - Kill events appear in the trace as `kill`.
    - **CEL cost limit.** The limit per evaluation is 10,000,000 by default (it was 1,000,000,
      which prompts of about 500 tokens exceeded). `Scenario.cost_limit` sets it per run; `eval`
      uses the same limit.
    - **Engine choices (binding).**
      - **Streams.** A streaming call runs its callee as a child task. A caller still busy with an
        item's `on_item` steps handles the next one when it is free. An exit or error in `on_item`
        ends the call: the callee runs on, and its later events are `late`. `timeout_ms` is
        checked when the callee ends, as for other calls. A callee whose behavior contains a
        `yield` (anywhere) always gives a non-streaming caller `{items, value}`. A `yield` event
        has `output` = the item and a new `index` field. Only `stream: true` (not `yield`) opts a
        run into concurrency.
      - **Channels.** `capacity` is set by the first put that gives one; a different one warns.
        Blocked producers and receivers resume in arrival order. A timeout fails with
        `{code: timeout, retryable: true, data: {channel}}` and takes `on_error`. A receive with
        no timeout and no deadline that is still waiting when every other task has finished is
        an **idle consumer**: roots stop waiting for it, the run ends without a warning, and
        its scenario step ends `canceled`. `put` events carry `key`, `input`, `output.len` and
        `wait_ms`; `receive` events `key`, `output` and `wait_ms`.
      - **Kills.** A kill fault needs `target` (a component, or an interface for its component)
        and `at_ms`; `instance` defaults to the group's first instance. Each task in a call into
        the instance unwinds to its outermost such call: every call it abandons (the callee's
        own calls included) ends with `{code: killed}`, and that call returns
        `{code: peer-killed, retryable: true}` to its caller. `parallel` branches running inside
        such a call stop (a stopped branch fails with `killed`). Later calls to the instance fail
        at once with `peer-killed`. A rendezvous waiter that is killed breaks its generation:
        the others fail with `peer-killed` and `data: {arrived, count}`. `dead: true` goes on the
        named component's state; `restart` clears it, kept components included. The `kill`
        event's `output` is `{failed, stopped, dropped}`. Kill steps and faults opt a run into
        concurrency.
19. **Test-weighted coverage and feature lists (binding; from the oracle results).**
    - **Test-weighted coverage.**
      - `check --tests FILE` reads a JSON list of the repo's test files with the code under test:
        `[{test, targets: [<file or symbol>], area}]`, produced by the new
        `.claude/skills/mosaic-generate/scripts/test_targets.py`, which reads imports and
        constructor calls heuristically.
      - It reports **test reach**: the share of test files whose targets are cited by an
        interface that some scenario's trace executes, per area and in total.
      - `--min-test-reach R` gates on it.
    - **Feature lists.**
      - The profile gains `features: [{id, summary, sources: [docs or config keys], owner}]`: the
        system's user-visible features, from docs, config flags and CLI options.
      - The coordinator writes them before fan-out.
      - Each area must model each owned feature (a flow tagged `feature:<id>`) or skip it with a
        valid reason in `skips/<area>.features.json`.
      - `check --features profile.yaml` reports covered, skipped and missing features, and
        `--strict-features` fails on missing ones.
20. **Model-integrity lints (binding; from a gateway-platform build, round 2).** Passing scenarios
    hid three defects in one model: a liveness check was a bodiless stub, nothing scheduled a
    cleanup sweep, and a gate read a field that nothing wrote.
    `check --lint` gains three lints for these, in `internal/devtools/check/integrity.go`. Each
    prints its findings and a share per fragment. **`--max-inert`, `--max-unscheduled` and
    `--max-dataflow R`** imply their lint and fail when a fragment's share is above R.
    - **`inert`.** Lists an owned interface (not `attributes.boundary`, not owner `shared`) with no
      behavior and no `store`, when a flow enters it, another behavior calls, emits or publishes
      to it, or it cites an unskipped inventory entry (with `--inventory`).
      - A boundary stub with an area owner that is still a stub after the merge is an **orphan**:
        the owner never defined it. It counts against the owner's fragment when that fragment is
        in the merge, or when the merge is a single document.
      - Stubs by design aren't listed: interfaces with `latency_ms` (a kernel that only takes
        time), and interfaces of components of kind `external` or with `attributes.external`.
      - An interface is also skipped when it is reached only as a dynamic call's declared
        `targets` (a dispatcher's list) and no entry cites it except entries of level
        `registered`. Orphans are never skipped this way.
      - The share is over the owned interfaces that are called or cite an entry.
    - **`unscheduled`.** Lists an owned interface whose own `sources` cite the first line of an
      unskipped entry of a scheduled kind, or that has `attributes.schedule`,
      `attributes.periodic: true` or `attributes.tags: [periodic]`, when nothing schedules it.
      A name match also counts if the interface cites the entry's file.
      - The scheduled kinds are `cron`, `listener`, `queue-consumer` and `service-main`, plus
        their names in other repos: `scheduled-task`, `background-task`, `busy-loop` and
        `process-main`.
      - **Scheduled** means reached through calls, emits and publishes from one of these: an
        `emit` or `publish` with `after_ms` or `every_ms`, a flow entry with `repeat`, or a
        startup flow. A startup flow's id or a tag has the token `startup`, `boot`, `bootstrap`,
        `launch`, `start`, `init` or `main`, or the flow is tagged `periodic` or `scheduled`.
      - Listeners, queue consumers and process or service mains are also scheduled when any flow
        or any event delivery reaches them.
      - An entry counts as scheduled when any interface citing it is scheduled. The other
        interfaces citing it are parts of the same work, such as a loop's shutdown branch.
      - Each finding says what does reach the interface: flows that run it once, only scenario
        steps, or nothing.
    - **`dataflow`.** Read-never-written state. Paths are per component, because a behavior's
      `state` is its own component's state.
      - A **read** is a literal `state.a.b` or `state['a'].b` in any CEL of a behavior (templates,
        `if`, `when`, `foreach`, `parallel`, dynamic `set` keys and store `where`). A store `get`
        or `query` reads its table, with the key's literal prefix (`= 'NODE#' + id` reads
        `NODE#*`).
      - A **write** is a `set` of `state.…`. A dynamic key's literal prefix counts:
        `= 'state.sessions.' + id` writes `state.sessions`. A store `put`, `update` or `incr`
        writes its table and key prefix. Fixture state and the component's `state.initial` count
        as writes, down to the leaves of literal maps.
      - A read is reported when no write's path is a prefix of it, or extends it, and, for a
        store key prefix, no write's key agrees with it. The finding names the readers. It notes
        when only scenarios seed the path, and when every read sits under `has()` (an optional
        knob whose branch runs only when a scenario seeds it).
      - References with no literal segment (`state[vars.k]`), and dynamic `set` keys with no
        literal `state.` prefix, are counted as unknown and never flagged. A component with an
        unknown write is skipped.
      - Row fields read through variables aren't tracked (`vars.rows.map(n, n.memoryMb)`).
        Those need a world seed check by hand.
      - The share is over the distinct read paths and tables, attributed to the first reader's
        fragment.
21. **Contract conformance against an API spec (binding; from a gateway-platform build, round 2).**
    One model had a header as required where the code had it optional, and nothing compared
    the model's contracts to the published spec. `check --openapi FILE` (repeatable) does.
    - **Matching.** Each operation's implementation is an interface whose `attributes.method` and
      `attributes.path` name the route (path parameter names are ignored; `ANY` matches every
      method), or else one named `<method>-<path slug>` on any component. Client wrappers (kind
      `cli-command`, or `attributes.calls`) never implement. When several servers serve one route,
      the one a client wrapper's `calls` names wins, then the service (the nearest `service`
      ancestor) that implements the spec's unambiguous operations.
    - **Request.** Path, query and header parameters, at the request's top level or (query) under
      `query`, and the body under `body` (or flattened at the top level). Presence, required versus
      optional, and types are compared; names match case- and separator-insensitively (`orgId` =
      `org_id`). A model-optional field whose behavior fails under `!has(input.X)` or
      `input.X == null` counts as required. `authorization` is the security scheme's header.
      Other `x_*` headers the spec doesn't declare are counted, not reported, unless the model
      makes one required.
    - **Response.** The 2xx JSON schema against the envelope's `body` (or the whole response when
      it has neither `status` nor `body`): properties and types, and the success status when the
      envelope pins one.
    - **Errors.** Each spec 4xx/5xx status must be declared by the interface, raised by its `fail`
      steps, or reachable through its calls; each status the interface declares must be in the
      spec, except a 500 the spec doesn't list (the generic internal error).
    - **Schemas.** `$ref`, `allOf` (merged) and object `oneOf`/`anyOf` (union of properties,
      required in every variant) are resolved; `integer` and `number` are compatible; nullable
      fields compare by their non-null type. A `oneOf` of unlike types, or a reference outside the
      document, is skipped and counted as complex. An untyped side (`{}` or an object without
      properties) is counted as not compared, not reported field by field.
    - **Report.** Per operation and interface: `missing`, `extra`, `required`, `type`, `status`,
      `error-missing` and `error-extra`; operations no interface implements (`unmodeled`); route
      interfaces matching no operation on a component that implements one (`orphan`). Extra
      request fields that come from a request schema shared by several interfaces are one issue
      per operation. Totals by kind; `--max-conformance-issues N` fails above N.
22. **The failure matrix (binding; from a gateway-platform build, round 2).**
    - **Why.** Feature lists (item 19) count what users rely on, but a model can cover every
      feature on its happy path and never say what happens when a shared dependency fails: redis
      down, the scheduler unreachable, a client disconnecting mid-stream, a node dying, a lease
      lost, an upstream provider erroring. Those paths are where gateways and schedulers differ.
    - **Profile.** The profile gains `failures: [{id, summary, sources, owner, on}]`, written by
      the coordinator in stage 2 next to `features`. `on` names the shared component or edge that
      fails (a component id, an edge such as `client disconnect`, or an upstream); `owner` is the
      area whose behavior handles it. A failure without `on` is warned about.
    - **Covered.** The owner models each failure as a flow tagged `failure:<id>` that some run
      scenario runs **while injecting the failure**: the scenario has a fault (a `kill` fault
      included), a `cancel`, `restart` or `kill` step, a mock with `fail`, or seeded `state`
      (a lease already held, a key already gone). A tagged flow that only runs fault-free is
      missing, with that reason.
    - **Skipped.** Or the owner lists it in `skips/<area>.failures.json`
      (`[{id, reason, covered_by?}]`, next to the profile) under the feature skip rules: not "not
      modeled", "out of scope", "too large" or "todo", and a "covered by" reason names an entity
      in `covered_by`.
    - **Check.** `check --failures profile.yaml` reports covered, skipped and missing failures per
      owner, unknown `failure:` tags and ignored skips; `--strict-failures` exits 1 on missing
      ones. Failures whose owner has no fragment in the merge are reported apart, so an area-local
      run doesn't fail on them. With `--scenario`, only the matching scenarios count.
23. **CEL crypto and byte helpers (binding).**
    - **Why.** One build's API-key hashing, webhook signatures, sticky routing and log tails
      could only be modeled symbolically or worked around.
    - **Helpers.** Every environment, and eval's sandbox, gets these pure, deterministic helpers:
      - `sha256(s)`, `sha256Bytes(b)`: lowercase hex of the SHA-256 of the UTF-8 bytes.
      - `hmacSha256(key, msg)`: lowercase hex HMAC-SHA256; `hmacSha256Base64(key, msg)` gives
        standard padded base64. `key` may be a string or bytes.
      - `byteLen(s)`: the UTF-8 byte length (CEL's `size(s)` counts code points).
      - `substrBytes(s, start, end)`: Go's `s[start:end]` on the bytes. A cut inside a character
        keeps the partial bytes, as Go does, so the result may not be valid UTF-8. Bounds outside
        `0 <= start <= end <= byteLen(s)` are an error.
      - `base64Encode(s or b)`: standard padded base64. `base64Decode(s)`: accepts padded or
        unpadded standard base64 and returns a string; it fails when the bytes are not UTF-8
        (`base64.decode(s)` from the encoders extension returns bytes).
      - `fnv64a(s)`: 64-bit FNV-1a of the bytes, a uint when it is at most 2^63-1, else its
        decimal string (so it survives JSON). `uint(fnv64a(s)) % n` is a uint either way.
      - `log2(x)`, `ln(x)`: doubles, for an int or a double `x` (`ln(0)` is `-Inf`).
    - **Cost.** Each call counts against the cost limit (item 18): the hashing, HMAC, base64,
      `substrBytes` and `fnv64a` calls cost 1 plus 1 per 10 bytes of their string arguments, the
      rest 1.
24. **Absent inputs, per-call choices and `repeat` in steps (binding).** Three scenario mechanics
    that test suites need and the language could not express.
    - **Absent inputs.**
      - Fake data fills every declared request field, optional ones too, so a scenario could not
        send a request without a field.
      - In an entry, scenario, step or request input, `{$absent: true}` removes the key, its fake
        value included; `{$null: true}` sets a real JSON null. Both work at any depth.
      - Inputs are marked when decoded, so the markers survive merging (a later layer may set a
        removed key again, or remove an earlier layer's value) and evaluation (an expression that
        yields null still sets null). They are resolved after the merge over fake data. The
        effective request echoes them.
      - Why a marker and not a literal `null`: the merged models already write literal nulls to
        mean "present and null" (Python `None`; a Go model's `input.Redirect == null`), and
        reading a removed key in CEL is an error, so giving `null` the meaning of absent broke
        a gateway-platform model's shard scenarios and Cassandra's `cql-delete-columns*`. An `absent: [paths]` list was rejected because
        it needs a path syntax for keys that hold dots and sits apart from the value it removes. A
        literal `null` keeps its meaning: no override (the fake value when the schema declares the
        key, else null).
      - Behavior `call`, `emit` and `publish` inputs are unchanged: without `fill` they hold only
        the keys they write.
    - **Per-call choices.**
      - A choice in a scenario, step or request (`model.Choice`) is a string, as before, or a list
        or a map. A list gives the n-th evaluation of the choice point its n-th option and repeats
        its last. A map `{"<n>": option}` sets the listed evaluations (1-based) and leaves the
        others to the behavior's default.
      - Evaluations are counted per choice point across the run, over every call and instance. A
        step's own `choices` entry starts a fresh count for that step; the entries it inherits
        from the scenario keep the run's count.
      - Validation and request checks verify every option a list or map names. The scalar form,
        its JSON and `--choice` are unchanged.
    - **`repeat` in steps.**
      - A scenario step takes `repeat: {count, interval_ms, initial_delay_ms}`, as a flow entry
        does (count 1 to 100). The step calls its target `count` times, each pass `interval_ms`
        after the previous pass's call tree finished, with `deadline_ms` counted from the pass's
        start. Its lane opens after the first pass, so earlier passes' emits and timers are
        delivered as the clock advances; the step ends when the last pass and every delivery have
        finished, and its result is the last pass's. Control steps refuse `repeat`.
      - A flow step still ignores the flow's `entry.repeat` and makes one pass. Honoring it
        changed five Cassandra scenarios (three `hb-*`, `rs-ttl-cleanup-then-list` and
        `wp-sync-then-lagging-write`) and the language demo's `gpu-add-then-step`, all of which
        step a repeating flow one pass at a time on purpose.
25. **Conditional writes, transactions and crash-after-effect (binding).** Areas modeled
    compare-and-set with "read then put" or with faults, and one build's serving area added an ad
    hoc put-if-unchanged interface. Temporal's lost start reply (P3d) and activity redelivery after
    a worker crash (P4a) had no fault to express them.
    - **Conditional writes.** A store write (`put`, `update`, `delete`, `incr`) takes
      `if: "<cel>"`, over `row` (`null` when absent), `key` and the behavior variables; `put` also
      takes `if_absent: true`. When the condition fails nothing changes, and the call fails with
      the declared error named by `conflict`, else a declared `condition_failed`, else
      `{code: condition_failed, status: 412}`, with `data: {table, key, row}`, as DynamoDB's
      `ConditionalCheckFailed`. `where` keeps its meaning as a write condition (code `conflict`).
    - **Transactions.** A behavior step `transact: [<store write>, ...]` applies writes to the
      running instance's tables all or nothing. Writes are evaluated in order on a staged copy
      (a later write's `row` sees an earlier one's effect; `state` is the pre-transaction state).
      If all pass, all commit, with one `set` event each; if any fails its condition or misses
      its row, none is applied and the step fails with that write's error, `data.index` naming
      it. `as` gets `{ok, value: [results], error}` and `on_error` works as for a call (default
      `propagate`). Only write ops are allowed; codes must be declared errors of the interface
      running the behavior.
    - **`lost_reply` fault.** The callee runs to the end and everything it did stands, but the
      reply is dropped: without `code` the caller waits its `timeout_ms` (or 30000 ms) and gets
      `timeout` (unless the callee already outlasted the timeout, which is reported as before);
      with `code` the caller gets that error (`status`, `message`; `retryable` true unless set)
      when the callee ends.
    - **`crash` fault.** `after_steps: N` (required, from 0) stops the callee before its
      (N+1)th step: steps count when they have an action and pass their `when`, at any nesting
      depth of the callee's own task (`parallel` branches and timers are not counted), and a
      store interface's operation counts as one step. The caller gets
      `{code: crashed, status: 500, retryable: true}` (overridable), even if the behavior ended
      within N steps. Compact flag form `TARGET:crash:N[@calls]`.
    - **Partial effects on retry.** Nothing rolls back. A retry or redelivery is a new invocation
      (new call number, so `calls: [1]` limits the fault to the first attempt) that reads all
      state the failed attempt wrote; its emits, timers and nested calls stand. This is
      at-least-once delivery: a model shows idempotency with `if_absent`/`if` writes or a state
      check, and a model without it shows the duplicate effect in `state` and the trace.
26. **Request-level addressing: routes and redirects (binding).** Calls addressed interfaces
    by id, so a client could not send `GET /v1/x` to a host and let the server's router pick the
    handler, and a Go test of a mux that cleans `/v1/vms/..` and answers 307 to `/v1`, followed
    by Go's client, could not be expressed.
    - **Route calls.** A call step's `call` may be an object:
      `{host | component, method, path, headers, body, follow_redirects, max_redirects}`.
      `host`, `component`, `method` (default `GET`) and `path` are literals or `"=cel"`;
      `headers` and `body` are templates. Exactly one of `host` and `component` is given, or
      `path` is an absolute URL whose host addresses the call. `path` may carry a query.
      `as`, `retry`, `on_error`, `timeout_ms`, `deadline_ms`, `on`, `token`, `input`, `fill`
      and `targets` work as for an id call; `stream` does not. Each attempt resolves the route
      again. Id calls are unchanged.
    - **Routers.** A component's routes are the interfaces of the component **and its
      descendants** whose `attributes.path` starts with `/` (the usual form:
      `{method: GET, path: "/v1/vms/{id}"}`; a Go `"GET /path"` pattern is accepted too).
      `attributes.method` is a method, a list, or `ANY`/`*`/absent for any method; `GET` also
      answers `HEAD`. Patterns take `{name}` or `:name` (one segment), `{name...}` (the rest,
      maybe empty), `{$}`, and a trailing `/` (a subtree). The most specific match wins:
      segment by segment, literal over parameter over rest, then an explicit method over any,
      then the lower interface id. `component.router` declares `hosts` (exact names or
      `*.suffix`; a port is ignored), `fallback` (an interface for unmatched requests),
      `not_found` and `method_not_allowed` (error codes, defaults `not_found` with status 404 and
      `method_not_allowed` with status 405 when the path matches only under other methods), and
      `clean_path: <3xx>` (a path with `.`/`..` segments or repeated slashes is answered with
      that status and `location` set to the cleaned path, as Go's ServeMux does). An unknown
      host fails with `unknown_host`, an unknown dynamic component with `invalid_target`.
    - **Input.** The matched interface's input is built from the request, then the step's
      `input` is merged over it (and, with `fill`, it is merged over a fake request): each
      header at its lower-case key with `-` as `_` (`X-Org-Id` -> `x_org_id`), `query` (first
      value of each key), `body`, each path parameter at its name (or its snake_case form when
      only that is a request property, as `{resourceSize}` -> `resource_size`), and
      `request: {method, path, host, headers, pattern}`.
    - **Redirects.** With `follow_redirects: true`, a successful response whose `status` is 3xx
      and whose `headers` carry `location` (any case) is followed: the location resolves
      against the current URL; 301/302/303 turn a non-GET/HEAD request into a bodiless `GET`;
      a hop to another host drops `authorization` and `cookie`. Past `max_redirects` (default
      10) the call fails with `too_many_redirects`. Each hop is a new call number in the same
      attempt; `on` applies while the hops stay on the first component.
    - **Trace and result.** Every hop emits a `route` event before its call (`interface` the
      match, `key` the pattern, `input: {method, path, query, host}`, `output` a router-made
      redirect, `error` a 404/405/unknown host), so a followed redirect shows both hops.
      `vars.<as>` gains `route: {method, path, query, host, component, interface, pattern,
      redirects: [{status, location, method, path, interface}]}` for the last attempt, and
      `target` is the final interface.
    - **Static analysis.** Plans and graphs follow a route call through its `targets`;
      validation suggests the target of a literal route call that has none, checks literal
      components and router fallbacks, and warns on a literal host no router serves.
27. **Back pressure: limiters (binding; from a gateway-platform blind round).**
    - **Why.** One build's areas hand-rolled every limiter, each its own way:
      - Redis token buckets with several dimensions, shared by all gateway tasks, consumed at
        admission and charged after the response;
      - a sorted-set window of in-flight requests with leases;
      - in-process `rate.Limiter` buckets (`stale_tracker.go`, `nebula_cert_issue.go`);
      - a per-IP hourly cap (YC checkout);
      - non-blocking upload slots.

      The billing area couldn't key one by client IP at all. `capacity` (§11.4) only queues
      calls per instance, with no key, rate or window. A limiter is one generic construct: what
      is counted, per what key, over what time, shared how, and what happens when it's full.
      The key is any CEL, so a client IP is just another input (`= input.x_peer_ip`), as are an
      org, an API key, a dimension or a host.
    - **Declaration.** A component declares `limiters: [{id, kind, ...}]`, with ids unique in the
      component and the full id `<component>.<id>`. Fields:
      - `kind`:
        - `token_bucket`: holds up to `burst` tokens (default `limit`), refills `limit` tokens per
          `period_ms` continuously, and admits when the tokens cover the cost;
        - `fixed_window`: counts in windows of `period_ms` aligned to the epoch, and admits while
          `count + cost <= limit`;
        - `sliding_window`: counts the admissions of the last `period_ms` (a log);
        - `concurrency`: at most `limit` leases held per key. A lease is released by `release`,
          or expires after `lease_ms` (a stale member, as in a Redis sorted set).
      - `key`: CEL over `input`, `ctx`, `config`, `vars` and `self`. The default `""` means one
        global key. The same limiter keyed differently is two declarations.
      - `limit`: an int or CEL, evaluated per admission, so a policy can come from state or
        config. `null` means unlimited: nothing is counted and the decision is `unlimited`.
        `0` admits nothing; a model whose code reads 0 as unlimited writes
        `= x > 0 ? x : null`.
      - `period_ms`, `burst`, `lease_ms`: ints or CEL.
      - `floor`: the lowest a token bucket can go when charged after the fact (default 0;
        a gateway might floor at `-burst`).
      - `idle_ttl_ms`: a key untouched this long is forgotten, and returns full.
      - `cost`: CEL, default 1.
      - `scope`:
        - `instance` (default): each instance of the component has its own state;
        - `shared`: one state per key across all instances, the Redis case.
      - `backend`: an interface id, for `shared` only. Each decision first makes a call to it,
        with input `{limiter, key, op, cost}`, so its latency, faults, kills and trace apply. The
        engine keeps the state; the call's result is ignored. When the call fails,
        `on_backend_error` decides:
        - `fail_open` (admit, decision `fail_open`);
        - `fail_closed` (reject with the limiter's error, decision `fail_closed`);
        - `propagate` (the default; the backend's error is the caller's).
      - `on_limit`: what a full limiter does:
        - `reject` (the default);
        - `wait`: block the caller in virtual time until the admission would pass, up to
          `max_wait_ms` (then reject). Waits are served first come, first served per key, and the
          trace gets a `queue` event as for capacity.
      - `enforce`: a bool or CEL (default true). When false the decision is made, counted and
        traced as `shadow`, and the call is admitted.
      - `error`: `{code, status, message, retryable}`, default
        `{code: rate_limited, status: 429, retryable: true}`. Its `data` carries `{limiter, key,
        limit, remaining, retry_after_ms}`, and a template can read them (`retry_after_ms` is the
        wait until a cost-1 admission would pass; for `concurrency`, until the oldest lease
        expires, or null).
    - **Applying a limiter declaratively.** An interface takes `limits: [<limiter> | {limiter,
      key, cost, gate}]`, where a bare id names a limiter of the interface's own component and a
      full id names any.
      - The limits are checked at call entry, before the behavior, after `capacity`. All of them
        are decided first; tokens are consumed only if all admit. This is the all-or-nothing of a
        multi-dimension Lua script.
      - The first that rejects fails the call with its error. The error must be a declared error
        of the interface (validation enforces it).
      - A `concurrency` lease taken this way is released when the call ends, whatever the outcome.
      - `gate: true` checks without consuming: a token bucket admits while tokens are above 0, the
        other kinds while under the limit. This is a gateway's gate on dimensions whose cost is
        known only after the response.
    - **Behavior steps.**
      - `admit: {limiter | limiters: [...], key, cost, gate, as, on_error}` decides mid-behavior.
        Several limiters are all or nothing, as above. `vars.<as>` is `{ok, decision, limiter,
        key, remaining, retry_after_ms, lease}`, and a rejection fails the step with the limiter's
        error (`on_error` works as for a call). A `concurrency` lease taken by `admit` is held
        until `release` or until `lease_ms`, even past the behavior's end, as with a Redis
        ZADD/ZREM pair.
      - `charge: {limiter, key, cost}` consumes after the fact, down to `floor`, and never fails
        on the limit (backend errors still apply). This is a gateway's post-response token charge.
      - `release: {limiter, key, lease}` frees a lease. A missing lease is a no-op.
    - **State, seeding and assertions.**
      - CEL gets a root `limiters`:
        - `limiters['<component>.<id>']['<key>']` for shared state;
        - `limiters['<component>@<instance>.<id>']['<key>']` for instance state.

        Each value is `{tokens, count, leases, updated_ms}`, with the fields its kind uses.
      - Scenarios, steps and fixtures take `limiters:` with the same keys, to seed state, for
        example a bucket already empty or an IP already at its hourly cap. A seeded limiter counts
        as injected state for the failure matrix (item 22).
      - `state` is unchanged.
    - **Trace and summary.**
      - Every decision emits a `limit` event: `interface` the caller, `key` the limiter's full id,
        `input: {key, cost, gate}`, `output: {decision, remaining, retry_after_ms, limit}`, where
        the decision is `admit`, `reject`, `wait`, `shadow`, `unlimited`, `fail_open` or
        `fail_closed`, and `instance`.
      - `charge` and `release` emit `limit` events with decision `charge` and `release`.
      - The summary gains `limits: {<full id>: {admitted, rejected, shadow, waited}}`.
    - **Many clients.** A step's `repeat` passes expose `pass` (1-based) to the step's input and
      choice expressions, so one step can stand for many callers
      (`x_peer_ip: "= '10.0.0.' + string(pass % 3)"`). With `await: false` and `at_ms`, callers
      overlap in time.
    - **Validation.**
      - Kinds and fields: `period_ms` is required for the window and bucket kinds, `lease_ms` for
        `concurrency`, and `backend` only with `scope: shared`.
      - Limiter references resolve, and errors are declared on every interface that applies the
        limiter.
      - CEL compiles, and seeds name declared limiters.
    - **Relation to `capacity`.** `capacity` stays the per-instance pool of slots with a queue (a
      thread pool or a GPU stream). A limiter has a key, a rate or window, sharing and shadow
      mode. A per-key concurrency cap with no queue is a `concurrency` limiter, not a capacity.
    - **Engine choices (binding).**
      - `key` is a literal string or `"=cel"`. `limit` must be written; `null` means unlimited.
      - With `enforce` false, only a would-reject becomes `shadow`, and it consumes nothing.
      - In a group, a limit that would have admitted when another rejects gets an event with
        `rolled_back: true`, and isn't counted.
      - A wait never starts when admission is impossible (`limit` 0, or a cost above `limit` or
        `burst`).
      - On `charge` and `release`, a backend error skips the operation, or fails the step under
        `propagate`. `release` without a lease frees the key's oldest lease. `charge` on a
        `concurrency` limiter, and `release` on any other kind, are validation errors.
      - A restart resets `instance` limiters; `shared` ones survive.
      - The `limiters` root shows each key's state as of its last touch.
      - Step choices may be `"=cel"`, which is how `pass` reaches them. An error `message` may be
        `"=cel"` over `error`.
28. **The `racy` lint: read-then-write on shared state (binding; from a gateway-platform blind round).**
    Blind judges found compare-and-set modeled as a read followed by an unconditional write, even
    though `if`, `if_absent`, `incr` and `transact` (item 25) exist. Examples were a dispatch
    fence, a billing transaction record, a close-if-open and a key-budget counter.
    Lost updates and double claims were invisible, because no scenario raced the write.
    - **Finding.** `check --lint racy` lists a behavior that reads a store row (`get`, `query`)
      or a `state` path, and later in the same behavior writes the same table and key prefix (or
      the same state path) with a `put` or `update` that has no `if`/`if_absent`, outside a
      `transact`. A `set` whose value expression reads the read's variable counts as a write of
      that path.
    - **Only when it can race.** It's a finding only when the behavior can run concurrently with
      itself or another writer of that key:
      - the component has more than one instance in some fixture or topology;
      - or it has no `capacity` of concurrency 1;
      - or another interface also writes the table.
    - **Exemptions.** An interface or component with `attributes.single_writer: "<reason, with
      citation>"` (a leader-only loop, a per-key actor) is exempt.
    - **Gate.** `--max-racy R` fails a fragment whose share of store-writing behaviors above R is
      racy.
    - **Report.** Each finding names the read step, the write step, the table and key prefix, and
      the fix: `if: row.version == ...`, `if_absent`, `incr` or `transact`.
29. **The `seam-names` lint: one field, two spellings (binding; from a gateway-platform blind round).**
    A key service wrote `limitUSD` and a budget gate read `limitUsd`. Every gate
    passed, because each side was consistent with itself.
    - **Names compared.** `check --lint seam-names` collects the field names used at each seam:
      - **store tables:** the literal keys of `put`, `update`, `transact` items, fixture and
        initial rows (writes), and the member names selected from that table's rows anywhere a
        behavior reads them (`vars.<as>.value.X`, `row.X`, `where` and `if`), both reads;
      - **interface calls:** the literal keys of each call's `input` against the callee's
        request schema properties, and the names read from `vars.<as>.value` against the callee's
        response schema;
      - **events and topics:** emitted or published input keys against the subscriber's request
        schema.
    - **Finding.** A read name that has no exact match but matches a write name after
      normalizing (lower case, without `_`, `-` and spaces), or a call key that matches a schema
      property only after normalizing. The finding names both spellings, the writer, the reader
      and their fragments.
    - **Not findings.** Route inputs, which normalize headers by design (item 26), and
      `x_*` header aliases.
    - **Gate.** `--max-seam-names N` fails above N findings in total.
30. **Two-sided failures (binding; from a gateway-platform blind round).** The `cli-idempotent-retry`
    failure was covered by the CLI's retry, while the control plane ignored the idempotency key.
    The failure was counted as covered, though only one side of the seam was modeled.
    - **Profile.** A `failures` entry may give `sides: [{owner, role, summary}]` instead of one
      `owner`, for example `[{owner: cli, role: client-retry}, {owner: control-plane,
      role: server-dedupe}]`.
    - **Coverage.** Each side's owner tags a flow `failure:<id>:<role>`, run under injection as
      in item 22. The failure is covered only when every side is covered, or validly skipped in
      that owner's `skips/<area>.failures.json` with `{id, role, reason}`.
    - **Report.** `check --failures` reports each side. An entry with a single `owner` keeps
      today's meaning.
31. **Blind measurement every round (binding; from a gateway-platform blind round).** That build's
    round 2 scored 38 of 45 and 33 of 35 on cases the builders had fixed against. A blind benchmark and
    a fresh oracle sample then scored 10 of 40 and 6 of 37.
    - **Rule.** Every build or fix round ends with a measure no builder saw. A new benchmark
      (`BENCHMARK<n>.md`) is written by a separate agent before the round starts. A fresh oracle
      sample (`oracle<n>/sample.json`) is drawn with `--exclude-sample` over every earlier sample.
      Both are scored by fresh judges and oracle agents. The scores reported for a round are the
      blind ones. Re-scores of seen cases are reported apart, as regression checks.
    - **Unit-weighted sampling.** The oracle sample is weighted toward tests in the same
      directory as code an area owns (unit tests), at the share the repo has. `sample_tests.py`
      gains `--unit-share F` (default: the share of such tests among all mapped tests), because
      the blind sample showed that areas modeled the request path but not the unit-level rules
      (rounding, job specs, startup checks).
32. **Choices for items 28–30 (binding).**
    - **`racy`.**
      - Keys are compared per input field (`pk`, `sk`), so different rows that share a
        partition key don't match.
      - These don't count:
        - reads and writes in exclusive branches (`then`/`else`, choices);
        - a state read and write with no step between them that yields;
        - a write whose value re-reads its own path.
      - A store `where` on a write counts as a condition. More instances count only for tables on
        another component.
      - **`attributes.racy_in_code: "<path:line of the read and of the unconditional write>"`**
        exempts a finding whose race is the system's own. Such findings are listed apart as
        system findings. A value without a `path:line` is warned about and doesn't exempt.
    - **`seam-names`.** Names are followed across interfaces, and each behavior's own `vars` are
      skipped.
    - **Two-sided failures.** A mix of covered and validly skipped sides counts as covered.
33. **Lints from the round-4 blind measure (binding).** Every gate passed, while the blind
    benchmark found three classes of error that no lint looked for.
    - **`unraised-errors`.** An owned interface declares an error, but no `fail` step, store
      `conflict`, `transact` or limiter `error` in its behavior (nor in an interface it
      `propagate`s from) can produce it. It is the "declared but dead" validation:
      - batch's `invalid_file`;
      - compute's cloud-init and pod admission checks;
      - metadata lengths;
      - embeddings validation.

      Not listed:
      - boundary stubs;
      - errors marked `{reachable_by: "<cel or note>"}`;
      - interfaces with no behavior (`inert` covers those);
      - the generic `internal` and 500 codes.

      The finding names the error and the interface's cited lines, so the owner can find the
      check in the code. `--max-unraised R` fails a fragment above share R of declared errors.
    - **`racy` gains unconditional status transitions.** An unconditional `update` or `put`
      (no `if`, `if_absent`, `where` or `transact`) on a shared table whose item sets a
      state-machine field is a finding, even when the behavior doesn't read the row first. The
      fields are `status`, `state`, `phase` and `lifecycle`, plus any listed in the profile's
      `naming.state_fields`. Code nearly always fences these writes, and the read is often in the
      caller (`vm-lifecycle.stop-vm` resurrected a terminated VM). `single_writer` and
      `racy_in_code` exempt it as before. Reported as `racy (transition)`.
    - **`choice-for-computed`.**
      - **Finding:** a `choice` point on an owned, non-boundary interface whose cited code
        decides the branch from config, a flag, stored state or a policy engine, so the model
        should compute it. Examples are batch's gate flag, the Cedar verdict and the fabric gate.
      - **Heuristic:** the choice's interface cites lines that read config or a flag (as
        identified by the profile's `config_sources`), or the choice's options name config or
        flag ids.
      - **Exemption:** `attributes.choice_ok: "<reason>"`, for nondeterminism the code really
        has: network outcomes, randomness, timing, or external verdicts the model doesn't own.
      - **Gate:** `--max-choice-for-computed N` fails above N findings.
34. **Contract conformance beyond OpenAPI (binding).** Response fields outside the control plane's
    OpenAPI document were dropped:
    - the tRPC views (`modality`, `updatedAt`);
    - SSE frames (`[DONE]`, the usage frames);
    - the PostHog event body.

    `check --contract FILE` (repeatable) compares interfaces against a contract file written
    from the code in the repo's prep.
    - **File:** `contracts: [{id, match, request, response, errors, stream, sources}]`.
      - `match` is `{interface}` (an id or a glob), `{route: {method, path}}` or
        `{attributes: {...}}`.
      - `request` and `response` are JSON Schemas, matched as in item 21. The response is
        compared against `body` when the envelope has one.
      - `errors` is a list of `{code, status}`.
      - `stream` is `{frames: [{name, schema}], terminator, order: "<regex over frame names>"}`
        for a yielding interface. Its yields are compared against the frames in order, and the
        terminator must be the last yield.
      - `sources` cites the code each contract came from.
    - **Report and gate.** The issue kinds of item 21, plus `frame-missing`, `frame-extra`,
      `frame-order` and `terminator`. `--max-contract-issues N` fails above N.
    - **Pipeline.** The prep stage extracts contracts the spec doesn't cover (zod and tRPC
      routers, SSE emitters, event schemas) into `contracts/*.yaml`, citing the code.
35. **Simulator additions from the round-4 blind measure (binding).**
    - **IP and CIDR helpers in CEL.**
      - `ip(s)` normalizes an address (an IPv4-mapped v6 becomes v4) and errors on an invalid
        one;
      - `inCidr(ip, cidr)` and `inAnyCidr(ip, [cidrs])`;
      - `ipFamily(ip)` is 4 or 6;
      - `ipIsLoopback`, `ipIsPrivate`, `ipIsLinkLocal`, `ipIsMulticast` and `ipIsUnspecified`,
        as Go's `net/netip` defines them.

      For ipRanges, netguard policies and client-IP keys.
    - **Run caps per scenario.** A scenario takes `max_events` (default 20,000, up to 1,000,000)
      next to the existing `max_virtual_ms`. The summary reports both caps when one is hit. The
      skill docs name both, because judges thought the caps were fixed.
    - **Response headers.**
      - Every result value of a route call and an interface call keeps `headers` (lower-case
        keys) when the response declares or sets them.
      - Expectations read `steps.<as>.result.value.headers['retry-after']`.
      - The trace's `call.end` events carry `headers`.
      - Validation warns when an expectation reads a header the response schema doesn't
        declare.
    - **Fault matching.** A fault takes `match: "<cel>"` over the call's `input`, and
      `caller: "<interface id or glob>"`. It applies only to calls that match both, next to
      `calls` and `instance`. For example: fail only the embeddings request with 1,025 items, or
      fail the spend read only from the auto-recharge pass.
    - **Hang without release.** A `hang` fault with `forever: true` never answers. The call ends
      only through the caller's `timeout_ms`, a deadline, a cancel, or a kill of either side. A
      caller with none of these waits until the run ends, and the run reports the call as
      pending, with no synthetic 5xx.
    - **Cancel on session close.** A behavior step `close: {session: "<cel key>"}` cancels every
      call in flight that carries `session: <same key>` in its call options. Their callers get
      `{code: cancelled}`. This models a tunnel or connection whose death the peer sees.
    - **Retry on status.** A call's `retry` takes `on_status: [<int>...]` and
      `on_codes: [...]`, as alternatives to `retryable`. A client that retries on 429, 503 and
      408 regardless of the error's `retryable` flag says so.
36. **Choices for items 33–35 (binding).**
    - **`unraised-errors`.** These aren't findings:
      - errors passed through from the caller (`fail: "= input.error"`);
      - codes returned as data;
      - a status that matches a raised error with another code;
      - shared error tables, which are counted apart;
      - catch-all exception types;
      - duplicates.

      `reachable_by` is read from the error, or else from `attributes.reachable_by`.
      `--profile` (default: the `--features` file) gives `naming.state_fields` and
      `config_sources`.
    - **`racy (transition)`.**
      - A write keyed off a row whose status was tested earlier in the behavior counts.
      - Scheduler, workflow, cache and in-process tables are skipped, as are new rows under fresh
        ids and status tests on the request body.
    - **`choice-for-computed`.** Dialogs, quick picks, DNS and network outcomes, and "flag" or
      "feature" in a title aren't findings.
    - **Contracts.**
      - A request or response with a `body` property is an envelope.
      - Errors match by status, or by code when no status is given. Leaving `errors` out skips
        the check.
      - A yield goes to the frame whose `const`s it fits best.
      - `order` is an anchored regex over the frame names, joined by spaces.
      - `terminator` is a frame name or a literal (also matched as `data`), checked only on calls
        that end without an error.
      - A frame no scenario yields is counted as not compared. `orphan` isn't reported.
      - Stream yields are read by re-running the scenarios.
    - **Simulator.**
      - The cancel code is `canceled`, as cancel tokens use. A closed session can be reused.
      - Mixed-case header keys are kept, and gain lower-case aliases.
      - `caller` falls back to the caller component for steps and entries.
      - With `match` or `caller`, `calls` counts only the matching calls.
      - `ipIsLinkLocal` covers unicast and multicast.
      - A run that a cap ends reports `caps: {max_events, max_virtual_ms, hit}`.
      - A forever hang leaves the call in the summary's `pending` list, with a warning, and gives
        the step or run status `pending`.

## 14. Hierarchical, recursive ontologies (direction; binding where marked)

### 14.1 Goal

Mosaic should represent every layer of abstraction of a system:
- **zoomed out:** the interactions among services;
- **zoomed in:** one component's parts and logic, down to exact bytes and tokens (GPU engines),
  OS system calls and a modeled machine.

A flat model can't do this. Five rounds on a gateway platform showed it: the system-level model chased
unit-level rules (formats, rounding, ids) with diminishing returns, and about 20% of the repo's
tests were untranslatable, because they check byte layouts, codecs or OS behavior. The answer is a
hierarchy grown recursively:
- **Black boxes first.** A component is first a black box: its contract.
- **Zooming in.** An operator can zoom into a component. That launches the same generation
  pipeline at the component's scope, which discovers, clarifies and rectifies the component's
  parts, logic and I/O as a child ontology.
- **Recursion.** Children can be refined in turn, down to the runtime and machine levels.

### 14.2 Levels

The levels are a label, not a fixed ladder; a component can skip levels.

| Level | Typical contents |
|---|---|
| `system` | services, deployments and the substrates between them |
| `service` | handlers, modules, stores and workers |
| `logic` | control flow, data transforms, exact bytes, codecs; for GPU engines, tokens, scheduler steps, KV blocks and batches |
| `runtime` | threads and goroutines, locks and channels, sockets, files, system calls |
| `machine` | CPU and GPU memory, PCIe and NVLink, kernels, devices |

Each document declares `level`.

### 14.3 Contracts and refinements (binding)

- **Separate linked documents.** A refinement is its own versioned ontology document, with its own
  revisions, owners and pipeline runs:
  - the child declares `refines: {ontology, component, revision}`;
  - the parent's component records `refined_by: [{ontology, revision}]`.

  Documents are composed by reference at simulation time, never copied.
- **The contract.** The parent component's interfaces (requests, responses, errors, timing,
  resources, and the scenarios that cross its boundary) are the contract. The child's boundary
  interfaces declare `implements: <parent interface id>`, and their schemas must conform (item 21's
  comparison, both ways).
- **Hand-off down.** The child pipeline receives:
  - the component's code scope;
  - the contract;
  - the parent's scenarios projected onto the component, as acceptance tests. Calls into the
    component become entry steps, and the parent's observed boundary outputs become expectations.
- **Rectifying up.** A child that finds the contract wrong files a change request against the
  parent: a breaking change, routed to the parent's owners (as in fix rounds). A child never
  silently disagrees with its parent.
- **Timing: the child replaces the parent when it may be the higher fidelity** (user decision,
  2026-11-01). A child's measured boundary latency (a distribution or a `"=cel"` over input)
  replaces the parent's `latency_ms` for that component, when:
  - the child is at a deeper level;
  - and its boundary scenarios pass.

  The parent records the provenance: `latency_source: {refined: <ontology>@<rev>}`. An operator
  may pin the parent's value with a reason.

### 14.4 Cross-level conformance (binding)

`check --refinement <child>` runs the parent's scenarios with the component swapped for its child
model. Outcomes at the boundary must match exactly:
- results and error codes;
- external calls and their order where asserted;
- state the parent reads back.

**Timing.** Timing differences don't fail the check. They update the parent's timing by 14.3's
rule and are reported.

**Why this matters.** Two independently built models at different resolutions must agree. Unlike
structural gates, this agreement is evidence about truth.

### 14.5 Mixed-resolution simulation

A run chooses, per component, `black_box` (its contract and latency) or `refined` (its child
ontology, recursively):
- the default is `black_box`;
- child entities are namespaced under the component's path;
- zoomed-out runs stay fast, and a zoomed-in run pays only for what it opens.

### 14.6 Substrate library

Shared substrates are modeled once, as importable ontologies (`imports: [{ontology, revision}]`):
- DynamoDB (conditional writes and transactions), Redis, Temporal, Nomad;
- TCP and TLS;
- Linux processes, file descriptors and system calls;
- CUDA streams and device memory.

Repos import them rather than inventing their own: one build's areas made four incompatible
conditional-write sets before the coordinator unified them.

### 14.7 When to refine

A component is a refinement candidate when:
- an operator zooms in;
- or its tests stop fitting its level: untranslatable tests (byte layout, codecs, OS behavior),
  repeated blind findings below the level, or unit-test failures the level can't express.

The candidate's untranslatable tests become the child's oracle sample.

### 14.8 Concurrency exploration

Hand-scheduled races (`at_ms`) miss the interleavings nobody wrote, so the engine gains
systematic, bounded schedule exploration: partial-order reduction over the simulator's
scheduling points, or emitting Promela for SPIN.

For Go components refined to the `runtime` level, Gomela (Go to Promela, bounded model checking)
gives an independent model of the real code's concurrency to check the child against.

### 14.9 The recursive workflow

- **On fae.** The pipeline at any scope is a fae workflow, and zooming in starts a child run of the
  same template, parameterized by scope and linked to its parent (user request, 2026-11-01). What
  fae supports today, and what it lacks, is in `requirements/fae-hierarchical-workflows.md`.
- **Until then.** Until fae supports it, a local emulator runs the same stages with the same
  inputs and outputs, so mosaic's side can be built and tested now and moved onto fae unchanged.

### 14.10 First milestone

Once the hierarchy is built: declare the existing vLLM ontology a refinement of a gateway platform's
serving engine, and run `check --refinement` and mixed-resolution simulation across them. This exercises
the contract hand-off, timing replacement and cross-level conformance on two models that already
exist.

### 14.11 Binding details for the first build

**Model (`internal/model`).**
- **Document fields:**
  - `level` (one of 14.2's labels; default `system`);
  - `refines: {ontology, component, revision?}`;
  - `imports: [{ontology, revision?, as?}]`.
- **Component field:** `refined_by: [{ontology, revision?}]`.
- **Interface fields:**
  - `implements: "<parent component>.<interface>"` (on a refinement's boundary interfaces);
  - `latency_source: {refined: "<ontology>@<rev>"} | {pinned: "<reason>"}`.
- **Validation.**
  - A document with `refines` must give `implements` on each boundary interface it exposes.
  - `implements` targets resolve when the parent is loaded alongside (`-f parent.yaml`).
  - `imports` resolve by path or store id. Imported entities keep their ids, under the `as:`
    prefix when one is given.

**Composition (`internal/model` or `internal/sim`).**
- **Loading.** The composer loads a parent and its refinements: with `-f` documents and
  `--refine <component>=<child file>`, or through the store by `refined_by`.
- **Resolution.** A run chooses each component's resolution with
  `resolution: {<component>: black_box|refined}` (request and scenario field; default
  `black_box`).
- **Rewiring when refined:**
  - calls to the component's interfaces go to the child's `implements` interfaces;
  - child components are namespaced `<component>/<child id>`;
  - the child's own boundary stubs resolve to the parent's entities of the same id when present.

**Check (`internal/devtools/check`).** `--refinement <child file>` (repeatable, with the parent
given by `-f`) runs the parent's scenarios that cross the refined component twice, black box and
refined:
- **Must match exactly:**
  - the final `result` (ok, error code and status);
  - the calls the parent asserts to other components;
  - the parent state its expectations read.
- **Timing doesn't fail the check.** It's reported as `timing: parent <x> ms, child <y> ms`, and
  `--apply-timing` writes the child's measured latency into a report the parent's owner applies
  (14.3).
- **Report:** `refinement <component> <- <child>: N scenarios, M equal, K differ` with each
  difference, plus schema conformance of each `implements` pair (item 21's comparison).
- `--max-refinement-diffs N` fails the gate above N differences.

**The compose emulator (`internal/compose`, `mosaic compose`).** It implements
`requirements/fae-hierarchical-workflows.md`'s semantics locally, with the same names.
- **Templates (YAML):**
  - `id`, `version`, `inputs` and `outputs` (JSON Schemas), `produces: artifacts`;
  - `recursion: {max_depth, max_descendants, max_children_per_visit}`;
  - `roles: {<role>: {cap, cap_scope: workflow|tree|task}}`;
  - `stages` (in order; a stage runs when its bindings exist).
- **Stage kinds:**
  - **`agent_turn`:** role; a `brief` template over `inputs.*` and `artifacts.*`; input bindings;
    `output: {name, schema}`; optional `tools` and `model`.
  - **`fanout`:** `branches_from: <list artifact>`, `max_branches`, `parallel`,
    `join: all|any|{k}`, and `branch: {stages}`. The item is bound as `item`, and branch outputs
    are joined in order.
  - **`subworkflow`:** `workflow` (an id, or `self`), `inputs` mapping and `outputs` mapping.
  - **`gate`:** `expr` (CEL over `artifacts`, `inputs` and `tree`) and `on_fail: fail|stage id`.
  - **`command`:** an `argv` vector run in the repo; it produces `{exit, stdout, stderr}`.
  - **`change_request`:** `target: parent|<task>` and `from: <artifact>`.
- **Run store.** `.mosaic/compose/runs/<task-id>/` holds:
  - `run.json`: template, inputs, parent, tree root, depth, stage states;
  - `artifacts/<name>.json`;
  - `out/` (the run's output directory; a child's sits under the parent's, by task id);
  - `requests/` (change requests addressed to this run).

  Task ids follow fae: a root id given or generated; children
  `<parent>.<stage>.<visit>[.<branch>]`.
- **Executors:**
  - `script` (deterministic, for tests and `simulate`): outputs come from a scenario file keyed
    by stage and role;
  - `claude`: runs `claude -p <rendered brief> --output-format json` in the repo, with the
    template's allowed tools. The agent must write the declared output artifact as JSON to a path
    given in the brief. The executor validates it against the schema, and retries once on a schema
    failure.

  The executor is an interface, so a fae executor can replace both.
- **CLI:**
  - `mosaic compose validate <template>`;
  - `simulate <template> --scenario <file>` (script executor; prints the tree);
  - `run <template> [--input name=@file]... [--parent <task>] [--from-parent in=artifact]...
    [--executor claude|script] [--max-parallel N]` (resumable: re-running a task id continues its
    unfinished stages);
  - `tree <task>`;
  - `requests <task>`.
- **What the emulator doesn't do:** fae's kernel floors, leases and authority model. It's for
  development only.

### 14.12 Choices made in the first build (binding)

- **Composition.**
  - A refined component keeps its interface ids. Each becomes a shell with an explicit 0 ms
    latency, which calls the implementing child interface and returns its value; errors pass
    through unchanged. Parent faults, mocks and `calls[...]` keep working.
  - Child components are `<component>/<child id>`, and share the component's instances.
  - A boundary interface is one that no child behavior calls.
  - `/` is allowed in component and link ids.
- **Imports.** Imported components take the `<as>/` prefix, and schemas the `<as>.` prefix. Local
  entities win over imported ones, unless the local one is a boundary stub.
- **Merges** keep the first non-empty `level` and `refines`, and list each import once. The store
  doesn't persist document-level hierarchy fields yet (next step, for linked documents in the
  store).
- **The refinement check.**
  - The black box is the parent as it stands. A scenario crosses the component when its run calls
    one of the component's interfaces.
  - Compared exactly: the run's and each step's status and result; the call counts of interfaces
    the expectations name, and their order where an expectation reads `.seq` or `.t`; and the
    state the expectations read. The refined component's own state isn't compared.
  - Child timing is the shell's call to the implementing interface.
- **Compose.**
  - Depth counts from 1 at the root.
  - A stage named in some `on_fail` is a handler: it runs only when a failure is routed to it, and
    sees that failure as `artifacts.failure`.
  - A stage's dependencies are its declared bindings, the artifacts its brief or expressions
    mention, and `after:`.
  - Caps are shared across processes on the host through a lease file (§16.7).
  - The artifact-only write scope is enforced (§16.7).
  - The `claude` executor runs with `--permission-mode dontAsk`, and always allows `Write` for the
    artifact.

### 14.13 Timing per outcome, and run budgets (binding)

The live VM-provisioning run showed that one latency number per interface is wrong. The child's
`vm-provision-workflow.run` takes seconds when the VM becomes healthy, and the full 45-minute
deploy deadline when it never does.

- **Latency per outcome.**
  - An interface may declare `latency_by_outcome: [{when: "<cel>", ms: <number | "=cel">}]`.
  - **Evaluation:** the entries are evaluated after the behavior ends, in order, over `result`
    (`{ok, value, error}`), `input` and `config`. The first match adds its `ms` before the call
    returns. If none matches, `latency_ms` applies as before. Without the field, nothing changes.
  - **Traces:** they show the matched entry.
- **Timing reports.**
  - **The report.** `check --refinement --apply-timing` groups the child's measured boundary
    latency by outcome class: `ok`, each `error.code`, and, when the response has a discriminator
    (a string field named `outcome`, `status` or `state`), each value of it. For each class it
    records the count and the min, median and max. It proposes a `latency_by_outcome` list (median
    `ms` per class, most specific first) in the `latency_source` shape of §14.3.
  - **Its readout.** The check prints the per-class medians next to the parent's latency.
- **Budgets for compose turns.**
  - An `agent_turn` may declare `budget: {max_turns, timeout_min}`. The executor enforces it: it
    passes `--max-turns` to `claude` where supported, and cancels at the timeout. Running out of
    budget fails the turn with reason `budget`, which `on_fail` can route.
  - The `claude` executor records each session's `num_turns`, `duration_ms`, `total_cost_usd` and
    `session_id`, in `turns/<stage>.meta.json` and as an event. `mosaic compose tree --stats` sums
    them per stage and per run.

## 15. Fixes from the hierarchy smoke tests and review rounds (binding)

### 15.1 Black-box assertions and stable ids

- **The `io` root.** Expectations gain a root `io`, the boundary view of a run:
  `[{seq, t, dir: in|out, kind: entry|external|route, interface, component, instance, input,
  output: {ok, value, error}, headers, duration_ms}]`, one item per entry call, per call into a
  component of kind `external` or with `attributes.boundary`, and per route call.
- **Why.** Scenarios that assert on `io`, `result` and `steps.*` survive internal renames. Trace
  assertions on internal interface ids keep working.
- **The `internal-assertions` lint.** `check --lint internal-assertions` counts the expectations
  that name a non-boundary interface or a state path inside a component that isn't a store. It's
  advisory, and `--max-internal-assertions R` gates it.
- **Stable ids.** The CEL helper `id(prefix, key...)` returns a deterministic UUID-shaped id from
  the run seed, the prefix and the keys, and never from the clock. `seq(name)` returns a per-run
  counter.
  - Behaviors that mint ids from `now` should move to these. The `clock-ids` lint
    (`check --lint clock-ids`) flags `now` used inside an id-shaped expression.

### 15.2 Merge strictness, staging, input and exemption lints

- **Strict stubs.** `check --strict-stubs` makes "stubs disagree" an error, naming both
  definitions.
- **Staging.** `check --stage <fragment>` validates and runs one fragment against the other
  fragments as they last passed. It writes and reads a last-good snapshot, `.mosaic/stage/`, so a
  broken fragment fails its own staging and never blocks the others. `--accept` records it as
  last-good when it passes.
- **The `unknown-inputs` lint.** It flags scenario, step and entry input keys that the target's
  request schema doesn't declare, at any depth (route-header aliases and `x_*` excepted). It
  catches requests that fake defaults would silently complete.
- **The `exemptions` lint.** Each exemption's citation must resolve, and its cited lines must
  plausibly support it:
  - `racy_in_code`: the lines hold a read and an unconditional write;
  - `single_writer`: a lease, leader or lock token;
  - `reachable_by`: a CEL expression that compiles, or a note with a citation;
  - `choice_ok`: random, network, time or external tokens.

  Unsupported exemptions are reported, and `--max-exemption-issues N` gates them.
- **Generator order.** The script `scripts/regen.py <workspace>` reruns every area generator,
  owners before copy-based generators, until a pass changes nothing (at most 3 passes), and
  reports what changed.

### 15.3 Simulator and CEL additions

- **Streams on routes.** A route call may target a yielding interface, with `stream: true` on the
  call. Frames reach the caller as for interface streams. The contract stream check reads them.
- **Nested headers.** Response headers are visible at `result.value.headers`, and on each streamed
  frame.
- **`retry.respect_retry_after: true`.** The next attempt waits for the error's
  `headers['retry-after']` (seconds) or `data.retry_after_ms`, capped by `max_backoff_ms`.
- **Removing fields.** A store `update` value may set a field to `{$absent: true}`, which removes
  it from the row.
- **Fault payloads.** A fault may carry `data` and `headers`. They appear on `error.data` and
  `error.headers`.
- **Per-scenario caps.** A scenario takes `max_iterations` (the loop cap, default 10,000, up to
  1,000,000) and `max_cel_cost`.
- **External state mid-run.** A step `set: {"<component>[@instance]": {<path>: value}}` with
  `at_ms` changes component state during the run, for example a node coming back, or a job placed
  by an outside scheduler.
- **CEL helpers:**
  - `json(x)` encodes canonically, with sorted keys and no spaces;
  - `jsonParse(s)` decodes;
  - `bytes(s)` and `hex(b)`.
- **Input markers:**
  - `{$bytes: "<base64>"}` gives raw bytes, including invalid UTF-8;
  - `{$bigint: "<decimal>"}` gives an integer beyond int64, carried as a decimal string with an
    `int` marker.

### 15.4 Hierarchy completeness

- **Persistence.** The store and API persist the document-level `level`, `refines` and `imports`,
  and `refined_by`. `mosaic sim run --resolution` works on stored documents with refinements,
  loaded by `refined_by`.
- **Following imports.** Validation follows imports. Errors inside an imported document are
  reported under the import's alias, instead of being skipped.
- **Refinement check additions.** `--refinement-trace <scenario>` prints the black-box and refined
  traces side by side. The check also compares each crossing scenario's own expectation outcomes,
  pass or fail, across both runs, and reports any that flip.

### 15.5 Schedule exploration

- **The flag.** `check --explore <scenario regex> --schedules N` reruns each matching scenario
  under N schedules. They come from systematic perturbation of the simulator's choice points: the
  tie-break order of same-time deliveries, the order of `parallel` branches and fan-out joins, and
  bounded `at_ms` jitter (`--jitter-ms`).
- **The search.** A partial-order reduction skips equivalent schedules where it can.
- **What fails.** A scenario fails if any schedule fails its expectations. The failing schedule
  is written as a replay file that `--replay <file>` reproduces exactly.
- **Gomela.** For Go components refined to `runtime`, the pipeline may also run Gomela (Go to
  Promela/SPIN) as an independent oracle, when it's installed. The wrapper is
  `scripts/gomela.sh`; it's optional and documented.

### 15.6 Substrate library

`substrates/` holds importable, versioned ontologies of shared infrastructure (§14.6), each with
scenarios. It starts with:
- **`nomad`:** jobs, evaluations, placement after a configurable boot delay, allocation health,
  node loss, and job stop/deregister;
- **`dynamodb`:** tables, conditional writes (the `<table>-*-if` set), transactions and GSIs.

Repos import them (`imports: [{ontology: substrates/nomad, as: nomad}]`) instead of inventing
their own.

### 15.7 Pipeline

- **Light profile.** The light profile drops stages, not just cases: no separate benchmark stage
  (its cases come from the skeleton turn), reconcile and merge in one turn, and no refix. The
  target is 15 stages or fewer.
- **Staging.** Briefs require `check --stage` before an area reports done.
- **Turn limits.** `budget.max_turns` falls back to a turn count the executor enforces, by
  streaming the session's events (`--output-format stream-json`), when the CLI lacks
  `--max-turns`.

### 15.8 Choices made in the build (binding)

- **`io`:** entry interfaces count as boundary items. The `clock-ids` lint ignores
  `duration(string(now)+'ms')` (a timestamp idiom, not an id).
- **Staging:** last-good copies live in `.mosaic/stage/<path>`, relative to the repo root. A
  fragment with no last-good copy falls back to its working copy, with a notice. Without `--code`,
  the `exemptions` lint checks only that citations exist and CEL compiles.
- **Exploration:**
  - the choice points are same-time task ties and deliveries, sequential `parallel` branch order,
    join tie order, and ±M ms `at_ms` jitter;
  - without a schedule, output is byte-identical;
  - the search goes fewest deviations first, and prunes reorderings whose next work touches
    disjoint stateful components, keys or ctx.
- **§15.3:**
  - `max_cel_cost` is another name for `cost_limit` (giving both, different, is an error);
  - fault `data` and `headers` don't apply to `timeout` and `hang`;
  - each frame's headers are its own;
  - `{$bigint}` becomes a plain string once it passes through CEL.
- **Persistence:** `level`, `refines` and `imports` live in the per-ontology `meta` table.
  `Store.Link` loads imports and `refined_by` children for simulate and test.
- **Imports:**
  - every `-f` document's imports load relative to its file;
  - a directory resolves to `ontology.*`, else `<dir>.*`, else its only document;
  - imported configs become `<as>/<id>`, with references inside the import rewritten. A local
    config under the original id still overrides.
- **Light profile:** 15 stages. The executor enforces `budget.max_turns` by counting main-session
  assistant messages in `--output-format stream-json --verbose`, when `--max-turns` is missing.

## 16. Closing the remaining gaps (binding)

### 16.1 The new checks in the gate

- **The full gate.** The full gate (`docs/PIPELINE.md`) and the compose templates' `check` stage
  add:
  - `--strict-stubs`;
  - `--lint ...,unknown-inputs,exemptions,internal-assertions,clock-ids`, with
    `--max-exemption-issues`, `--max-internal-assertions` and a `clock-ids` threshold;
  - `--explore '<race|concurr>' --schedules 20` on scenarios tagged `race` or `concurrency` (by
    id or `tags`).
- **Thresholds.**
  - Each repo's profile sets its thresholds (`profile.yaml` `gates:`), starting at today's
    measured value. They may only go down. The pipeline ratchets them as fixes land.
  - Repos without a `gates:` entry use the template defaults: 0 exemption issues, 0.5 internal
    assertions, and 0 clock ids for new models.

### 16.2 Invariants for exploration

- **Declaring them.** A scenario may declare `invariants: [<cel>]`, evaluated over the final
  `state`, `trace`, `io` and `calls`. The engine supplies helpers such as
  `exactlyOne(list, pred)`.
- **How exploration uses them.** `--explore` checks the invariants under every schedule. When a
  scenario has invariants, its `expect` is checked only on the default schedule, so
  "which writer wins" stays a default-schedule expectation and stops being a false alarm.
- **Without invariants**, `expect` is checked under every schedule, as today.

**The search.** It gains a coverage report: choice points seen, alternatives tried and pruned.
Commutation pruning also covers reads of keys that no other task writes.

### 16.3 Applying timing

`check --refinement <child> --apply-timing-to <parent fragment>` writes the proposed
`latency_by_outcome` and `latency_source: {refined: <ontology>@<rev>}` into the parent's
interfaces. It edits the YAML in place, keeping comments and order, and prints a diff. It refuses
to edit an interface whose `latency_source` is `pinned`.

### 16.4 Simulator

- **Cancel time.** A cancelled call's handler sees `ctx.cancelled_at_ms` (and
  `vars.<as>.cancelled_at_ms` on the caller's side).
- **Stream flow control.** A stream may declare `window: N` (frames in flight before the producer
  blocks) and `stall_ms` (the consumer's read timeout). A producer that blocks longer than
  `stall_ms` fails the stream with `{code: stream_stalled}`.

### 16.5 Substrates

The library adds `redis` (strings, hashes, sorted sets, TTL, Lua-script atomicity as a
transaction, pub/sub), `temporal` (workflows, activities, timers, retries, continue-as-new,
heartbeats, redelivery after worker crash), `tcp-tls` (connections, handshakes, half-close, idle
and read timeouts, resets), `linux` (processes, file descriptors, signals, the syscalls needed for
the runtime level: open, read, write, close, connect, accept, epoll waits, futex, nanosleep) and
`cuda` (devices, streams, events, memcpy H2D/D2H, kernel launches with occupancy and a cost
model, OOM). Each comes with scenarios and an import example.

### 16.6 The web UI

The UI shows the hierarchy:
- a component with `refined_by` opens its child ontology inline (zoom);
- a simulation can pick a resolution per component;
- the compose run tree for a task is browsable, with stage states, stats, change requests and
  artifacts;
- exploration results show failing schedules, and replay them.

### 16.7 Compose protections

The emulator gains two protections:
- **Write scope:** for `produces: artifacts`, writes outside the run's output directory are
  refused. Agents get the permission to write only there.
- **Caps across processes:** role caps are shared by all `mosaic compose` processes on the host,
  through a lease file under the run store root, with stale-lease recovery.

## 17. Gaps found by the runtime and machine substrates (binding)

Building `tcp-tls`, `linux` and `cuda` (§16.5) exposed these:

1. **Scenario `tags`.** Scenarios take `tags: [<string>]`. The gate's exploration selects on them
   (§16.1), and so do `--scenario-tag`, filters and reports.
2. **Blocking waits.** A behavior step `wait: {until: "<cel>", timeout_ms, on_timeout}` blocks the
   task until the condition holds. It's re-evaluated whenever the component's state, a channel or
   a signal it names changes, so a blocked `waitpid`, `futex` or `epoll_wait` is modeled directly,
   instead of through channel doorbells. `signal: <name>` wakes on a delivered signal (a `kill`
   step, or a `signal` action).
3. **Timers under a blocked call tree.** Timers and emits scheduled by a call tree that is blocked
   (waiting on a child, a channel or a `wait`) are delivered on time. The fork, exec and blocking
   `waitpid` in one call must not deadlock. This is an engine bug fix.
4. **Microseconds end to end.** Every scheduling point, `at_ms` jitter and the exploration choice
   points use the microsecond clock (§13.1 item 16). Fractional `at_ms` and `jitter_ms` are
   honored, so exploration sees GPU-scale overlap.
5. **Byte windows.** A stream may declare `window_bytes` (summed over each frame's
   `bytes(json(frame))`, or a frame's `size` field when present) alongside `window` in frames. A
   window applies across forwarding hops when a component relays a stream (`relay: true` on the
   forwarding call), so back pressure reaches the original producer.
6. **Explicit null in updates.** In a store `update` or `merge` value, `{$null: true}` sets a field
   to JSON null, and `{$absent: true}` removes it (§15.3). A literal `null` keeps meaning "no
   change" (§13.1 item 24). Validation warns on a literal `null` in an update value, suggesting
   the markers.
7. **The `unraised-errors` lint follows handlers.** It counts `fail` steps inside `receive`
   `on_error`, `catch`-style handlers and `parallel` branch handlers as raising.
8. **Imported topics are prefixed.** Topics published or subscribed inside an imported document
   take its `as:` prefix (`<as>/<topic>`), as components do (§15.8). Importers subscribe to
   `<as>/<topic>`. A no-subscriber warning for a topic in an imported document is suppressed when
   that document is checked alone (`-f` on the substrate itself).
9. **`at_ms` overlap matches the docs.** A step with `at_ms` starts at that time even while
   earlier steps are still running (§13.1 item 14). Fix the engine or the skill docs so they agree,
   choosing the behavior the docs describe unless existing models depend on the other. Report any
   model whose scenario results change.

### 17.1 Choices made in the build (binding)

- **Overlap (item 9).** A step with `at_ms` starts at that time, even while earlier steps run.
  This supersedes the step-completion wording in §13.1 item 14 for steps with `at_ms`. Steps
  without `at_ms` still wait for the previous step's emits and timers.
- **Timers under blocked calls (item 3).** Fixing this changed the traces, not the results, of 7
  scenarios:
  - one gateway-platform CLI scenario (a destructive tool the client confirms);
  - vLLM `serving-api-cli-serve-modes` and `serving-api-launchers`;
  - VS Code `main-process-onboarding-tryout-*` (four).
- **Kills and waits.** A kill delivers the signal `kill:<component>[@<instance>]` to waits.
- **Yields and windows.** A yield evaluates its frame before waiting for room in a window.
- **Substrates checked alone.** The no-subscriber warning is skipped for a document that declares
  a `level` and has no imports: a substrate checked alone.
- **`cuda` device timelines** run on scheduled timers, so `--explore` sees GPU-level choice
  points (36 across the substrate's scenarios; a cross-stream race is caught).

10. **Microsecond step durations.** Every place that reports `duration_ms` for steps, calls,
    `io` items and runs also reports `duration_us`, an integer holding the exact microsecond
    duration. `duration_ms` stays an integer of whole milliseconds, rounded down.
    - **Why not a fractional `duration_ms`.** It was built and rejected. It would be an int when
      whole and a double otherwise, and CEL refuses mixed int and double arithmetic, so vLLM fell
      from 990 to 869 passing scenarios. A field whose type depends on its value is a broken
      interface. This follows §13.1 item 16's `*_us` convention.
11. **Lanes keep program order under exploration.** A step may declare `lane: <name>` (default:
    none). Steps in the same lane keep their order under `--explore`, even with `await: false`
    and equal start times. They model one host thread issuing calls in sequence. Only steps in
    different lanes, or with no lane, are reordered as ties.
12. **Conditional streaming: `streams_when`.** An interface whose behavior can yield may set
    `streams_when: "=<cel>"`, a boolean over `input`, `config` and the behavior's variables,
    evaluated once when each call starts. When it is false, a caller that doesn't stream gets the
    plain return, not `{items, value}`, and a `yield` reached on that call aborts the run. One
    route can then model both of vLLM's chat responses: SSE frames with `stream: true`, one JSON
    body without. Absent, every call streams, as before. Validation requires the `=` form, a
    valid expression, and a `yield` somewhere in the behavior.
13. **List search in CEL.** `list.indexOf(x)` and `list.lastIndexOf(x)` give the first or last
    index of an element equal to `x` (CEL equality: `1` matches `1.0`), or -1. Each costs 1
    plus one per element against `max_cel_cost`. The string library's `indexOf` keeps working;
    the receiver picks the overload. Both are pure, so `eval` gets them too.
14. **Exit signals.** When an instance group stops, the simulator delivers the built-in signal
    `exit:<component>[@<instance>]` for every component of the group on that instance, in
    component order, with `data: {component, instance, reason, at_us}`. A blocking `wait` on it
    wakes. This models a monitor blocked on process sentinels, such as vLLM's engine-core
    monitor in `multiprocessing.connection.wait`.
    - **Reasons.** `killed` comes from a kill fault, a kill step, or a behavior's kill of its
      own instance, which models a process exiting on its own. `restarted` comes from a
      restart of a live instance. A restart of a dead instance raises nothing, because the
      instance already exited at its kill.
    - **Remembered while dead.** Other signals are lost when nobody waits for them. An exit is
      kept while the instance stays dead, so a wait that starts later returns at once, as a dead
      process's sentinel does. A restart forgets it.
    - **Signal sets.** A wait may name `signals: [...]` (each a name or `=cel`) beside or
      instead of `signal`, and wakes on any of them. `vars.<as>` gains `data` (what the waking
      signal carried), and `signal` names the one that woke it. The `wait` event's `key` is that
      signal, or the names joined by `|` when no signal woke it.
    - A run that waits on no `exit:` signal is unchanged: vLLM's 1021 scenarios give identical
      output.
15. **The check tool prints step results.** `--steps` prints, for each run scenario, one line per
    step: its index, `as` name (`-` if none), flow or interface (`on <instance>`), status, start
    and duration in ms, and `value <json>` or `error <json>`. A scenario without steps prints its
    `result`. The JSON is compact with sorted keys, and is cut at 200 bytes with the full size
    noted. `--steps-full` prints it whole. The lines come before `--trace` and `--state` output.

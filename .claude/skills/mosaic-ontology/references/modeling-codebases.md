# Modeling a codebase as a mosaic ontology

The goal is a model that is **true to the code at message level** and **useful to simulate**:
every gate, store, retry and fallback that changes a request's outcome is present, each claim
cites the line that proves it, and fake data looks like real traffic. The reference model is
`internal/testdata/gateway/ontology.yaml` (20 components, one flow and 14 scenarios). The snippets
below come from a fuller model of the same kind of gateway, so some names differ from it.

## Contents

- [Process](#process)
- [Components: how deep to go](#components-how-deep-to-go)
- [Interfaces and schemas](#interfaces-and-schemas)
- [State](#state)
- [Sources](#sources)
- [Naming](#naming)
- [Updating an existing ontology](#updating-an-existing-ontology)
- [Config, fixtures and instances](#config-fixtures-and-instances) (requires DESIGN §11)

## Process

1. **Scope one path.** Pick a user-visible flow (a request type, a job, a webhook) and find its
   entry point in code: a route registration, a handler, a consumer loop. A focused, accurate
   flow beats a shallow map of everything.
2. **Trace the call path** from the entry, reading each function the request passes through.
   Note each decision (refusals, branches, retries, fallbacks), each external dependency (a DB,
   cache, queue or third-party API) and each piece of state that a decision reads.
3. **Draft the components** (below), then one interface per entry point or callable unit that the
   path crosses.
4. **Write schemas** for the payloads that cross those interfaces, with `examples`.
5. **Write behaviors** for the components whose logic matters, and leave dependencies whose
   internals don't matter as stubs. See mosaic-simulation.
6. **Add a flow**, plus one **scenario per distinct outcome** you found in step 2, each with
   expectations.
7. `mosaic doc import`, `mosaic validate`, `mosaic test`, iterate, then `mosaic revision create`.

## Components: how deep to go

Use the hierarchy to mirror how the code is organized, and use leaves for the units the
simulation needs:

```yaml
- id: inference-gateway          # the deployable service
  kind: service
  layer: inference
  sources: [gateway/main.go]
- id: throttle                   # a gate inside it: its own leaf because it can refuse
  kind: module
  parent: inference-gateway
  sources: [gateway/throttle.go:274]
- id: redis-ledger               # a dependency: a separate component so it can be faulted
  kind: datastore
  layer: data
  attributes: {technology: redis}
```

Split a unit into its own component when any of these holds:

- it can **refuse or fail** the request (auth, rate limit, balance, policy, validation);
- you'd want to **inject a fault** into it (a datastore, cache, queue or remote service);
- it holds **state** that changes outcomes (counters, budgets, capacity, a catalog);
- it is a **boundary** that changes semantics, such as a commit point after which retries stop;
- you want to **count calls** to it in expectations.

Don't split pure helpers, logging, metrics or plumbing. Use `kind: client` for the flow's caller
(for example `sdk-client`) and `kind: external` for third parties you only stub. Peers that behave
identically (pool replicas) are separate components under one parent, which lets a fault hit one
of them.

## Interfaces and schemas

- One interface per operation, named after what the code calls it: `authenticate`, `check`,
  `read-account`, `chat`. Set `kind` (http, rpc, function, sql, queue, stream, event) and put
  transport detail in `attributes` (`{method: POST, path: /v1/chat/completions}`).
- `request` and `response` take a schema id for shapes that are shared or cross a service
  boundary, and an inline schema for small internal payloads:
  `request: {type: object, required: [api_key], properties: {api_key: {type: string}}}`.
- Translate structs and protobufs field by field, keeping wire names. Mark `required` what the
  code requires, and add `enum` for closed sets and `minimum`/`maximum` for real bounds.
- **Add `examples` wherever a value is looked up or compared.** Fake entry data must hit the
  happy path by default. For example, `api_key: {type: string, examples: [key_demo]}` matches the
  `key_demo` entry in `authentication`'s state. Use one example when an exact value matters,
  because several examples are picked at random per seed. Use `default` for flags such as
  `stream: {type: boolean, default: true}`.
- Declare `errors` from the code's error returns and status mappings: `{code: rate_limit_error,
  status: 429}`, plus `retryable: true` where the caller retries. Keep them in sync with the
  behavior's `fail` steps.
- `latency_ms`: give remote dependencies realistic ranges (`{min: 40, max: 120}` for an upstream
  model, `{min: 1, max: 3}` for a store). In-process functions can omit it (1 ms).

## State

Give a component `state` when a decision depends on data: accounts, keys, quotas, capacity
counters, catalogs and configuration. Seed `initial` so the default run is the happy path, and
let scenarios override it to reach the other branches:

```yaml
- id: admission-store
  kind: datastore
  state:
    initial:
      accounts:
        org_demo: {available_cents: 100, standing: eligible}
```

`set` paths are static identifiers, so behaviors can update `state.free_slots` but can't write
`state.accounts[input.org_id]`. Keep state that behaviors mutate flat, as counters and flags, and
use nested maps for data they only read.

## Sources

Every component, interface, link and flow gets `sources`, and every narrated step a `source`,
pointing at the line that justifies it: the handler, the guard clause, the retry loop or the
status mapping. Set the document's `source: {repo, sha}` to the commit you read, so `path:line`
stays meaningful. Use `path:line-end` for a block. If you couldn't find code for a claim, say so
in `description` instead of inventing a citation.

## Naming

| Thing | Form | Example |
|---|---|---|
| component, link, flow, scenario id | slug | `pool-admission`, `retry-before-commit` |
| interface name | slug | `require-balance` |
| interface id | `<component>.<name>` | `account-admission.require-balance` |
| schema id | PascalCase is conventional | `ChatRequest`, `UpstreamResponse` |
| choice name, `as` name, `set` segments | identifier | `rate_limit`, `vars.principal`, `ctx.httpStatus` |
| choice key (scenarios) | `<interface id>.<choice>` | `throttle.check.rate_limit` |
| option names | short verbs or states | `allowed`/`exceeded`, `allow`/`deny`, `completes`/`breaks` |

Hyphenated ids need bracket access in CEL: `calls['upstream-a.chat']`,
`state['pool-admission'].held`.

## Updating an existing ontology

1. `mosaic doc export <ont> --rev latest --format yaml -o before.yaml`, and read the
   `source.sha` it was built from.
2. Diff the repo from that sha to the new one, and map each changed file to the entities whose
   `sources` cite it. Grep the export for the path.
3. Update those entities, refresh line numbers in `sources`, and set `source.sha` to the new
   commit.
4. Add scenarios for new outcomes. Keep the existing scenarios passing, or update their
   expectations deliberately and say why in the revision message.
5. `mosaic validate`, `mosaic test`, then check `mosaic diff` to confirm that only the intended
   entities changed, and `mosaic revision create -m "Sync with <sha>: ..."`.

## Config, fixtures and instances

> Requires mosaic with DESIGN §11 (in progress). Field reference:
> [document-format.md](document-format.md#additions-for-systems-with-many-parts).

These three remove the most common reasons a model that passes its own scenarios is wrong about
the system.

**Config: model the deployed value, cite both.** Code defaults aren't always what runs.
Before you model a timeout, limit, mode or feature flag, look it up in the deployment (a config
file, Helm values, Terraform, environment defaults in the config loader) and in the code default.
Create one `config` entity per value, with `value` (deployed), `default` (code) and both lines in
`sources`, and read it from behaviors as `config['<id>']`:

```yaml
- if: "!config['hinted-handoff-enabled']"
  then: [{return: {hinted: false}}]
- call: replica.apply
  timeout_ms: "= config['write-request-timeout-ms']"   # durations take templates too
```

A scenario that tests the other mode overrides it (`config: {hinted-handoff-enabled: false}`)
instead of needing a second model.

**Fixtures: one shared world, not one per scenario.** When several flows read the same data
(a schema, a tenant, a cluster, a model catalog), seed it once in a fixture and list it in every
scenario: `fixtures: [base-schema]`. Use the fixture's names in your schemas' `examples`, so fake
entry inputs land in the seeded world by default. Make lookups of unknown keys fail with the
code's real error, so a scenario pointing at the wrong world fails instead of skipping quietly.
(In an 11-agent build, one area seeded `ks1.*` and another wrote `shop.users`. Writes to the
unknown table were skipped, and every scenario still passed.)

**Instances: model the code once, run it many times.** When several copies of the same code
talk to each other (database nodes, brokers, editor windows and extension hosts, GPU workers per
rank), don't make one component per copy and don't put a `to` address in requests. Model the
code once under one parent, and declare the copies as a topology in a fixture:

```yaml
components:
  - {id: gpu-worker, kind: service}                 # the instance group's root
  - {id: model-runner, kind: module, parent: gpu-worker}
fixtures:
  - {id: tp4, topology: {gpu-worker: [rank0, rank1, rank2, rank3]}}
```

Every component under `gpu-worker` now runs on each rank, with its own state. Behaviors address
a peer with `on:` and know where they run from `self` (see mosaic-simulation, behavior-language
§13). Use separate components only for peers whose **code** differs (a primary and a read
replica that run different logic).

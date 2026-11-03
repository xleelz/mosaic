# Ontology document format (`schema_version: 1`)

Every field of every kind, with its type and validation rules, taken from `internal/model`.
Decoding is strict: an unknown field or a wrong type rejects the document or entity before
validation runs. `?` marks an optional field.

## Contents

- [Document](#document)
- [Common types](#common-types): slug, identifier, source, template, schema reference
- [component](#component)
- [interface](#interface)
- [link](#link)
- [schema](#schema) and the supported JSON Schema subset
- [flow](#flow)
- [scenario](#scenario) and [fault](#fault)
- [Validation issues](#validation-issues)
- [Additions for systems with many parts](#additions-for-systems-with-many-parts): config, fixture, instances and topology, new fields (requires DESIGN §11)

## Document

```yaml
schema_version: 1          # int; 0 or absent means 1; anything else is an error
id: shop-checkout          # string?, the ontology id
name: Shop checkout        # string?
description: ...           # string?
source: {repo: org/shop, sha: 4f2c9e1, url: https://...}   # all optional: where it was derived from
components: []             # the six entity lists; each may be empty or omitted
interfaces: []
links: []
schemas: []
flows: []
scenarios: []
```

`mosaic doc import` and `mosaic apply` take this whole document as YAML or JSON. `mosaic put`
takes the entity objects below (one, a list, or `{"items": [...]}`), in JSON or YAML.

## Common types

| Type | Rule |
|---|---|
| slug | `^[a-z0-9][a-z0-9_-]{0,63}$`. Used for component, link, flow and scenario ids and interface names. No dots and no capitals. |
| identifier | `^[A-Za-z_][A-Za-z0-9_]*$`. Used for `as` names, `choice` names and each `set` path segment after the root. No hyphens. |
| option name | Letters, digits, `_` and `-`, 1 to 64 characters. Used for a choice's option names. |
| schema id | Letters, digits, `_`, `-` and `.`, 1 to 128 characters. Capitals are fine: `ChatRequest`. |
| source | `{repo?, path, line?, end_line?, sha?}`, or the string `"path"`, `"path:line"` or `"path:line-end"`. `sources` takes a list; step, retry and flow-step `source` takes one. |
| template | Any JSON value. Strings beginning with `=` are CEL; maps and lists are evaluated recursively. See mosaic-simulation. |
| schema reference | A schema id (`ChatRequest`), `"#/schemas/<id>"`, `{$ref: <id>}`, or an inline JSON Schema object. |

## component

| Field | Type | Notes |
|---|---|---|
| `id` | slug | Required and unique. |
| `name` | string? | Display name (the graph falls back to `id`). |
| `kind` | string? | Free text. Conventional values: service, module, function, datastore, queue, external, client, pool, engine. |
| `parent` | component id? | Must exist; the parent chain must not cycle. A component no one names as `parent` is a leaf. |
| `layer` | string? | Free-text grouping such as clients, api, data or billing, used by the map. |
| `summary` | string? | One line. |
| `description` | string? | Longer prose. |
| `sources` | [source]? | |
| `tags` | [string]? | |
| `attributes` | map? | Free-form, for example `{technology: redis}`. |
| `state` | `{schema?, initial?}`? | Simulated state. `initial` is a map; `schema` is a JSON Schema. When both are set, `initial` is checked against `schema` and mismatches are **warnings**. Declaring `state` makes the component stateful for plans and the map. |

## interface

| Field | Type | Notes |
|---|---|---|
| `component` | component id | Required and must exist. |
| `name` | slug | Required. |
| `id` | string? | Derived as `<component>.<name>`. If you give it, it must equal that. If you give only `id`, the component and name are split from it at the first dot. |
| `kind` | string? | Free text: http, rpc, function, event, queue, stream, sql and so on. |
| `summary`, `description` | string? | |
| `sources` | [source]? | |
| `attributes` | map? | For example `{method: POST, path: /v1/chat/completions}`. |
| `request` | schema reference? | Generates fake input when a caller sends none, and checks every call's input (a mismatch is a run warning). |
| `response` | schema reference? | Generates the stub's output and the output of a behavior that ends without `return`, and checks explicit returns. |
| `errors` | `[{code, status?, retryable?, summary?}]`? | `code` is required. Mostly documentation; a `store` uses its `not_found` and `conflict` errors (or the codes it names). |
| `latency_ms` | int, or `{min, max}`? | Simulated service time. A range draws a seeded uniform value. Needs `0 <= min <= max`. When absent, the latency is 1 ms. |
| `behavior` | [step]? | When absent (and there is no `store`), the interface is a stub. See mosaic-simulation's behavior-language reference. |
| `store` | `{table, op, key?, value?, where?, default?, not_found?, conflict?}`? | A declarative datastore operation on the component's `state.<table>` (rows keyed by id), so a value written in one call can be read back later in the run. `op` is `get`, `put`, `update`, `delete`, `query` or `incr`. Without a behavior, the interface performs it instead of returning fake data; beside a behavior it is ignored with a warning. See behavior-language §10. |

## link

An explicit architectural relation, used for the map and not for simulation. Calls and emits in
behaviors already produce derived edges, so add links only for relations that behaviors don't
show: offline writes, deployment, or reads outside the modeled flows.

| Field | Type | Notes |
|---|---|---|
| `id` | slug | Required and unique. |
| `from`, `to` | component or interface id | Both must exist. |
| `kind` | string? | calls, reads, writes, publishes, subscribes, depends_on, deploys or other. The map treats an empty kind as `depends_on`. |
| `label`, `protocol`, `summary` | string? | |
| `sources` | [source]? | |
| `attributes` | map? | |

## schema

| Field | Type | Notes |
|---|---|---|
| `id` | schema id | Required and unique. |
| `summary` | string? | |
| `schema` | object | Required. Every `$ref` inside it must resolve. |

The supported JSON Schema subset is `type` (a string, or a list where the first non-null entry is
used; `object` and `array` are inferred from `properties` and `items`), `properties`, `required`,
`items`, `enum`, `const`, `format` (uuid, email, date-time, date, uri), `minimum`/`maximum`,
`minLength`/`maxLength`, `minItems`/`maxItems`, `default`, `examples`, `oneOf`/`anyOf` (generation
uses the first branch), `allOf` (generated objects are merged), `$ref` and the `x-fake` hint
(uuid, email, date-time, date, url, name, id, sentence).

**How fake values are chosen** (deterministic for a seed), in this order:

1. `const`
2. `default`
3. one of `examples`, picked by the seeded RNG. List a single example when you need one exact value.
4. one of `enum`
5. the `format` or `x-fake`, then the property name: `*email*` gives an email, `*_at` a
   date-time, `name`/`*_name` a person name, `id`/`*_id` gives `<prefix>_<hex>`,
   `*key*`/`*token*`/`*secret*` gives `key_<hex>`, `*model*` gives `model-<word>`, and
   `*message*`/`*content*`/`*prompt*`/`*text*`/`*description*` give a sentence
6. a random value within the bounds. Integers default to 0..1000, but names containing
   count/attempt use 1..10, cents/amount use 1..10000 and token uses 1..4096. Arrays get
   `minItems` (default 1) up to at most `minItems`+4 items. Booleans are random.

Object properties are generated in sorted key order, all of them, not only the `required` ones.
Generation stops at depth 8.

## flow

| Field | Type | Notes |
|---|---|---|
| `id` | slug | Required and unique. |
| `name`, `description` | string? | |
| `entry` | `{caller, interface, input?, repeat?}`? | `caller` is a component, `interface` an interface id, and `input` a template merged over fake request data. Only flows with an `entry` can be simulated. `repeat: {count, interval_ms?}` (count 1 to 100) runs the entry `count` times with the clock advanced `interval_ms` between passes, for reconcilers and crons; state carries across passes. |
| `steps` | `[{component, title, detail?, source?}]`? | A narrative walkthrough; `title` is required. A flow needs an `entry` or `steps`. |
| `sources` | [source]? | |
| `tags` | [string]? | |

## scenario

| Field | Type | Notes |
|---|---|---|
| `id` | slug | Required and unique. |
| `flow` | flow id | Must exist and have an `entry`. |
| `name`, `description` | string? | |
| `seed` | int? | The default is 1. |
| `input` | template? | Deep-merged over the flow's `entry.input`, which is merged over fake request data. Maps merge; scalars and lists replace. |
| `choices` | `{"<iface>.<choice>": option}`? | Each key must be a known choice point, and each value one of its options. |
| `state` | `{component: partial state}`? | The component must exist. Deep-merged over its `state.initial`. |
| `faults` | [fault]? | |
| `expect` | [CEL string]? | Each must compile in the expectation environment (`result`, `status`, `calls`, `ctx`, `state`, `retries`, `faults`, `duration_ms`, `warnings`). |

### fault

| Field | Type | Notes |
|---|---|---|
| `target` | component or interface id | Required. A component target hits all of its interfaces. |
| `type` | `unavailable` \| `error` \| `latency` \| `timeout` | Required. |
| `code` | string? | Required for `error`. For `unavailable` it overrides the code `unavailable`. |
| `status` | int? | |
| `message` | string? | |
| `retryable` | bool? | `error` faults default to **false**; `unavailable` defaults to true. |
| `latency_ms` | int? | Required and greater than 0 for `latency`. |
| `calls` | [int]? | The 1-based invocations of the target to affect (each retry attempt counts). When absent, every invocation is affected. |

## Validation issues

`mosaic validate` returns `{revision, valid, issues: [{path, message, severity}]}`. `valid` is
false when any issue has severity `error`. Paths look like
`components[auth].parent`, `interfaces[a.b].behavior[2].then[0].fail`,
`interfaces[a.b].behavior[4].options.deny[1]`, `flows[f].entry.interface`,
`scenarios[s].faults[0].code` and `scenarios[s].expect[1]`.

Common errors and fixes:

| Message | Fix |
|---|---|
| `invalid id "Foo.Bar": use [a-z0-9][a-z0-9_-]{0,63}` | Lowercase slug, with no dots. |
| `unknown component "x"` / `unknown interface "x.y"` | Fix the typo, or create the entity. Interface ids are `component.name`. |
| `id must be "c.n"` | Remove `id`, or make it match `component.name`. |
| `a step has one action; this one has call, set` | Split it into two steps. |
| `a step needs an action or a title` | Add an action, or a `title`/`detail` for a note. |
| `as, retry, on_error, timeout_ms and targets go with call` | Move them onto the call step. |
| `path "phase" must start with vars., ctx. or state.` | Write `ctx.phase`. |
| `a choice with several options needs a default` | Add `default: <option>` or `default: "=cel"`. |
| `unknown choice point "k" (keys are <interface>.<choice>)` | Use the full key, for example `throttle.check.rate_limit`. |
| `invalid expression "...": undeclared reference to 'vars'` | Expectations can't see `vars`; store what you need in `ctx`. |
| `an error fault needs a code` | Add `code`. |
| `max_attempts is required` / `must be between 1 and 20` | Set `retry.max_attempts`. |
| warning `a dynamic call without targets cannot be followed by plans and graphs` | Add `targets: [every interface the expression can produce]`. |

## Additions for systems with many parts

> Requires mosaic with DESIGN §11 (in progress). Every field below is optional, and a document
> that uses none of them behaves exactly as before. Semantics are in mosaic-simulation's
> `references/behavior-language.md`, sections 13 to 22.

The document gains two entity lists:

```yaml
configs: []                # deployed configuration values (config)
fixtures: []               # named, shared starting worlds (fixture)
```

### config

One entity per deployed configuration value a behavior reads: a timeout, a limit, a mode, a
feature flag. Keeping both values makes the difference between the code default and what really
runs visible.

| Field | Type | Notes |
|---|---|---|
| `id` | slug | Required and unique. Conventionally the config key in kebab-case with a unit suffix: `write-request-timeout-ms`. |
| `type` | string? | The JSON type of the value: `integer`, `number`, `boolean`, `string`, `object`, `array`. |
| `value` | any | The **deployed** value: what the deployment's config file sets, or the default when it sets nothing. |
| `default` | any? | The **code** default. |
| `summary`, `description` | string? | Say where `value` and `default` differ, and why. |
| `sources` | [source]? | Cite both: the deployed config line and the code that defines the default (`conf/app.yaml:1330`, `src/.../Config.java:120`). |
| `attributes`, `tags` | map?, [string]? | For example `{key: write_request_timeout}`, the original config key. |

```yaml
configs:
  - {id: write-request-timeout-ms, type: integer, value: 2000, default: 2000, summary: Coordinator write timeout, sources: [conf/cassandra.yaml:1330, src/java/org/apache/cassandra/config/Config.java:120]}
  - {id: max-num-seqs, type: integer, value: 128, default: 256, summary: "Deployed lower than the code default", sources: [deploy/values.yaml:42, vllm/engine/arg_utils.py:310]}
```

Behaviors, latency expressions and templates read it as CEL `config`, a map from id to value:
`config['write-request-timeout-ms']` (bracket access, since ids have hyphens). Fixtures, scenarios
and run requests override values with `config: {<id>: value}`. Validation warns about references
to unknown config ids.

### fixture

A named starting world that many scenarios share: the instances, the clock, config overrides and
seed state. Write fixtures once, before scenarios, so every scenario tests against the same world.

| Field | Type | Notes |
|---|---|---|
| `id` | slug | Required and unique. Name it after the world: `base-schema`, `three-node-rf3`, `two-windows-one-dirty`. |
| `name`, `summary` | string? | |
| `extends` | [fixture id]? | Applied first, in order. |
| `topology` | `{component: [instance, ...]}`? | Instance names per instance group (below). |
| `clock` | `{epoch: "<RFC 3339>"}` or `{epoch_ms: int}`? | The epoch that `now` starts from. |
| `config` | `{config id: value}`? | Overrides of config values. |
| `state` | `{component or component@instance: partial state}`? | Seed state. |

```yaml
fixtures:
  - id: base-schema
    state: {schema: {keyspaces: {shop: {rf: 3, tables: {users: {}, orders: {}}}}}}
  - id: three-node-rf3
    extends: [base-schema]
    topology: {cassandra-node: [n1, n2, n3]}
    clock: {epoch: "2026-10-30T00:00:00Z"}
    config: {hinted-handoff-enabled: true}
    state: {"gossiper@n1": {endpoints: {n2: {alive: true}, n3: {alive: true}}}}
```

**Merge order** for a scenario: its fixtures in order (each one's `extends` first), then the
scenario's own `topology`, `clock`, `config` and `state`. State and config deep-merge; a topology
entry replaces an earlier entry for the same component.

### Instances and topology

A **topology** maps a component to instance names: `{cassandra-node: [n1, n2, n3]}`. It applies to
that component's whole subtree: a component belongs to the instance group of its nearest ancestor
with a topology entry (or of itself). A component in no group has one unnamed instance (`""`).
Topology appears in fixtures, scenarios and run requests, not on the component.

- **State is per instance**, keyed `<component>@<instance>` in overrides (`"gossiper@n2"`) and in
  results. The unnamed instance keeps the plain key `<component>`.
- **Instance names** are short identifiers you choose (`n1`, `w1`, `rank0`). They are names, not
  addresses: don't also put endpoints in requests to say where a call goes. Use `on:` (see
  behavior-language §13).

### New fields on existing kinds

| Kind | Field | Type | Notes |
|---|---|---|---|
| component | `capacity` | `{concurrency: int, queue_limit?: int, queue_timeout_ms?: int}`? | Each instance serves at most `concurrency` calls at once; the rest queue (behavior-language §17). |
| interface | `subscribe` | [topic]? | Topics this interface receives from `publish` steps. A topic is a slug, conventionally an `event`-kind interface id (§18). |
| interface | `latency_ms` | int, `{min, max}`, or `"=cel"` | The expression sees `input`, `state`, `config` and `self`. |
| flow `entry` | `on` | instance? | The instance the entry runs on (default: the group's first). |
| flow `entry` | `deadline_ms` | int or `"=cel"`? | A deadline relative to the entry's start, inherited by every nested call (§15). |
| flow `entry.repeat` | `initial_delay_ms` | int? | The wait before the first pass. |
| scenario | `fixtures` | [fixture id]? | Applied in order before the scenario's own overrides. |
| scenario | `topology`, `clock`, `config` | as in fixture | Applied on top of the fixtures. |
| scenario | `steps` | [step]? | A multi-step scenario instead of a single entry call (§19). `flow` may then be omitted. |
| scenario | `mocks` | [mock]? | A last resort for isolating one fragment (§21). Refused by `--no-mocks` and in generated models. |
| fault | `instance` | instance? | Hit only this instance; without it, every instance. |

A scenario step is
`{flow | interface, caller?, input?, on?, choices?, deadline_ms?, at_ms?, as?}`, and a mock is
`{interface, instance?, when?, return | fail, calls?}`.

**Durations are templates.** `timeout_ms`, `deadline_ms`, `after_ms`, `every_ms`, `stagger_ms`,
`count` and `join.need` take a number or `"=cel"` (`timeout_ms: "= config['write-request-timeout-ms']"`).

**Tag write flows.** A flow that writes state carries `tags: [writes]`, and must have a
multi-step scenario that reads its effect back (`--lint hollow` reports it otherwise).

**Merging configs and fixtures across documents.** Each id has one owner. Identical duplicates
merge silently; differing duplicates are a merge error, unless the duplicate is marked
`attributes: {boundary: true}`, which makes it a reference that defers to the owner.

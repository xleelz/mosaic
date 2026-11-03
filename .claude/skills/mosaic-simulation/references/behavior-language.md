# Behavior language reference

These are the exact semantics, taken from `internal/model/validate.go` and `internal/sim/sim.go`.
The worked example to read alongside it is the Envoy proxy model, `examples/envoy/ontology.yaml`.
The snippets here come from a model of an LLM inference gateway (its test-fixture form is
`internal/testdata/gateway/ontology.yaml`) or are verified against the engine.

## Contents

1. [Steps](#1-steps)
2. [Templates and CEL](#2-templates-and-cel)
3. [CEL variables](#3-cel-variables)
4. [set](#4-set)
5. [call](#5-call): input, fill, as, timeout_ms, retry, on_error, targets and dynamic calls
6. [if and choice](#6-if-and-choice)
7. [return, fail, emit and wait](#7-return-fail-emit-and-wait)
8. [What a call does at run time](#8-what-a-call-does-at-run-time): latency, faults, timeouts and stubs
9. [Run setup and budgets](#9-run-setup-and-budgets)
10. [store: datastores that hold rows](#10-store-datastores-that-hold-rows)
11. [foreach, break and continue](#11-foreach-break-and-continue)
12. [Repeated entries: reconcilers and crons](#12-repeated-entries-reconcilers-and-crons)

Additions for systems with many parts (requires DESIGN §11, in progress):

13. [Instances: self and on](#13-instances-self-and-on)
14. [parallel with a join](#14-parallel-with-a-join)
15. [Time: one clock and deadlines](#15-time-one-clock-and-deadlines)
16. [Timers](#16-timers)
17. [Capacity](#17-capacity)
18. [Publish and subscribe](#18-publish-and-subscribe)
19. [Config and latency expressions](#19-config-and-latency-expressions)
20. [Multi-step scenarios](#20-multi-step-scenarios)
21. [Assertions on the trace, and mocks](#21-assertions-on-the-trace-and-mocks)
22. [CEL helpers](#22-cel-helpers)
23. [Streams, channels and kills](#23-streams-channels-and-kills)
24. [Route calls and redirects](#24-route-calls-and-redirects)
25. [Back pressure: limiters](#25-back-pressure-limiters)
26. [Run caps, headers, fault matching, hangs, sessions and retry on status](#26-run-caps-headers-fault-matching-hangs-sessions-and-retry-on-status)
27. [Route streams, frame headers, retry-after, fault payloads, caps, set steps, JSON and markers](#27-route-streams-frame-headers-retry-after-fault-payloads-caps-set-steps-json-and-markers)
28. [Cancel time and stream flow control](#28-cancel-time-and-stream-flow-control)

## 1. Steps

A behavior is `behavior: [step, ...]` on an interface. It runs when that interface is called.

| Key | Meaning |
|---|---|
| `title`, `detail` | Narrative. If either is set and the step runs, the trace gets a `note` event before the action. |
| `source` | One source (`"path:line"` or an object), attached to the note. |
| `when` | CEL boolean. When false, the whole step is skipped, note included. |
| one action | `set`, `call`, `if`, `choice`, `return`, `fail`, `emit`, `wait`, `foreach`, `break`, `continue` or `transact` (§10). At most one per step. |

A step with no action needs a `title` or `detail`; it is then a narrative note. Validation rejects
action-specific keys on the wrong action (`input`/`fill` belong only with `call`/`emit`;
`as`/`retry`/`on_error`/`timeout_ms`/`targets` only with `call`; `then`/`else` only with `if`;
`options`/`default` only with `choice`; `index`/`steps`/`max` only with `foreach`, which also
takes `as`). Steps can nest up to 32 levels.

Narrate the steps a reader should see in the trace: gates, decisions, commit points and refusals.
Cite the code line in `source`. A narrated action keeps everything on one step:

```yaml
- title: Request refused
  detail: An enforced rate limit refuses with Retry-After. No upstream is contacted.
  source: gateway/throttle.go:329
  fail: {code: rate_limit_error, status: 429, message: organization rate limit exceeded, data: {retry_after_s: 1}}
```

## 2. Templates and CEL

- **Templates** (in `set` values, `input`, `return`, `fail`, flow and scenario `input`): a string
  beginning with `=` is a CEL expression, and its result can be any type. Any other value is a
  literal. Maps and lists are evaluated recursively:
  `input: {org_id: "= vars.principal.value.org_id", action: inference.invoke}`.
- **Always-CEL fields** take no `=`: `if`, `when`, `retry.when`, `expect`.
- **Either form**: `call`, `choice default`, `retry.max_attempts` and `wait` are literals unless
  they start with `=`.
- CEL is the standard language plus the strings, math, lists and encoders extensions, with
  cross-type numeric comparisons (`1 < 1.5` works, but `1 + 1.5` is an error: convert with
  `double()` or `int()`). Useful forms: `has(input.x)`, `'k' in map`, `size(list)`, `string(n)`,
  `cond ? a : b`, `list.join(', ')`, `s.startsWith('x')`, `s.contains('x')`.
- Whole YAML numbers are ints, so `5 / 2 == 2`. Accessing a missing key (`input.nope`) is a
  runtime error that **aborts the run**. Guard with `has(...)` or `in`.
- Quote every expression in YAML, and use single quotes for CEL strings inside:
  `if: "!(input.org_id in state.accounts)"`.

## 3. CEL variables

| Variable | Value |
|---|---|
| `input` | This interface's request: the caller's evaluated input, or fake request data. |
| `state` | This component's state map, live; `set state.x` updates it. Initialized from `state.initial` merged with scenario and run overrides. A component with no declared state starts with `{}`. |
| `ctx` | One map shared by the whole run: every component and the async deliveries. Use it to record facts for expectations. |
| `vars` | Local to this behavior invocation. Holds `as` results and `set vars.*`. |
| `attempt` | 1-based. Inside a call's evaluation of `call`/`input`, it is the current attempt. In `retry.when`, it is the attempt that just failed. Everywhere else it is 1. |
| `now` | Virtual time in milliseconds. |
| `error` | `{code, message, status, retryable, data}` of the **most recent failed call in this behavior**, or `null`. Later successful calls don't clear it. Inside `on_error` steps it is the error being handled. In `retry.when` it is the current attempt's error. A behavior's own `fail` doesn't set it. |

A store's `where` also sees `row` (the stored row, or `null`) and `key` (§10). Expectations use a
different set of variables; see the SKILL.md or reading-results.md.

## 4. set

```yaml
- set:
    ctx.slots: one acquired
    state.held: "= state.held + 1"
    state.local_free_slots: "= ctx.admissionMode == 'degraded local' ? state.local_free_slots - 1 : state.local_free_slots"
```

- Each key is a path: `vars.`, `ctx.` or `state.` followed by one or more identifier segments
  (`[A-Za-z_][A-Za-z0-9_]*`). Paths are static, so you can't index by a runtime value.
- **Parallel assignment**: every right-hand side is evaluated against the same snapshot first,
  then the paths are assigned in sorted order, so a value never sees another assignment in the
  same `set`. To compute from a just-assigned value, use a second `set` step.
- Missing intermediate maps are created. Each assignment emits a `set` event with `scope`, `path`,
  `old` and `new`.

## 5. call

```yaml
- call: upstream-dispatch.dispatch     # an interface id, or "= <cel string>"
  input: {targets: "= vars.plan.value.targets", body: "= input"}
  fill: false                          # true: deep-merge input over fake request data
  as: upstream                         # vars.upstream = {ok, value, error, attempts, duration_ms, target}
  timeout_ms: 30000
  retry: {...}
  on_error: propagate                  # or continue, or a list of steps
  targets: [...]                       # for dynamic calls
```

- **`input`**: a template, re-evaluated on every attempt. When absent, the callee gets fake data
  from its `request` schema. With `fill: true`, the evaluated input is deep-merged over fake request
  data (your values win), which is handy when a schema has many required fields. `fill` does
  nothing without `input`, and the engine ignores it on `emit`.
- **`as: x`** stores `{ok, value, error, attempts, duration_ms, target}` in `vars.x`, whether the
  call succeeded or not. `duration_ms` covers all attempts and backoff. `target` is the interface
  that answered last.
- **`timeout_ms`**: when the callee takes longer, the caller gets
  `{code: timeout, retryable: true}` at start + `timeout_ms`. The callee's work still happens (its
  state changes stand) and its `call.end` is marked `late: true`. With no `timeout_ms`, a hung
  callee (a `timeout` fault) holds the caller for 30000 ms and then times out.
- **`retry`**:

  | Field | Meaning |
  |---|---|
  | `max_attempts` | Required. A whole number from 1 to 20, or `"=cel"` (clamped to 1 to 20 at run time). It includes the first attempt. |
  | `backoff_ms` | The wait before the next attempt. 0 or absent means none. |
  | `multiplier` | Backoff after attempt n is `backoff_ms * multiplier^(n-1)`. A missing or zero value means 1. |
  | `max_backoff_ms` | A cap on each backoff. |
  | `jitter` | `none` (default): wait the computed backoff. `full`: a uniform draw in [0, backoff]. `equal`: backoff/2 plus a uniform draw in [0, backoff/2]. Draws come from the run's seeded random source (same seed, same waits); the `retry` event's `backoff_ms` is the drawn wait and its `jitter` names the mode. |
  | `codes` | Retry only these error codes. When absent, retry only errors with `retryable: true`. |
  | `on_status` | Retry a failure whose `status` is listed (`[429, 503, 408]`), **whatever its `retryable` flag** (§26). |
  | `on_codes` | Retry a failure whose `code` is listed, whatever its `retryable` flag (§26). |
  | `when` | CEL. It must also be true to retry; it sees `error` (this failure) and `attempt` (the failed attempt). |
  | `title`, `detail`, `source` | Narrate each `retry` event. |

  An attempt is retried only when attempts remain, the code matches (or the error is retryable),
  and `when` holds. With `on_status` or `on_codes`, the error must match one of them (or
  `codes`) instead, and `retryable` is ignored. Each retry adds one to the summary's `retries` and emits a `retry` event
  carrying the upcoming attempt number, `backoff_ms` and the failed code.
- **`on_error`** (after the retries are exhausted):
  - `propagate` (the default): this behavior fails immediately with the callee's error, with the
    same code, status and data.
  - `continue`: carry on with the next step. Check `vars.x.ok` and `vars.x.error`.
  - A list of steps: they run with `error` set to this failure. If they `return` or `fail`, the
    behavior ends there; otherwise execution resumes after the call step.
- **Dynamic calls**: `call: "= input.targets[attempt - 1] + '.chat'"` is evaluated on every
  attempt, so retries can move to another target. The expression must produce a string. An unknown
  interface produces a warning and the non-retryable error `invalid_target`. Always list
  `targets: [upstream-a.chat, upstream-b.chat]`. Validation checks that they exist, and plans and
  graphs follow them (without them you get a validation warning and the plan can't follow the
  call).
- **Route calls**: `call` can also be a request object, `{host or component, method, path, ...}`,
  that the callee's router resolves to an interface. See
  [§24](#24-route-calls-and-redirects).

## 6. if and choice

```yaml
- if: "vars.account.value.available_cents < state.balance_floor_cents"
  then: [ ... ]
  else: [ ... ]          # optional
```

A choice is a named decision that scenarios can override. Use it for outcomes the model doesn't
compute, such as a policy engine's verdict or a stream that breaks.

```yaml
- choice: decision                 # identifier, unique within the interface
  default: allow                   # an option name, or "= cel" that returns an option name
  options:
    allow:
      - return: {allowed: true}
    deny:
      - fail: {code: authorization_denial, status: 403}
```

- Its key is `<interface id>.<choice>`, here `authorization.authorize.decision`. A scenario sets
  `choices: {authorization.authorize.decision: deny}`, and a run sets
  `--choice authorization.authorize.decision=deny`.
- The option is resolved in this order: the scenario or run override, then the `default`
  expression or name, then (with a single option) that option. `default` is required when there
  are several options.
- An expression default makes the choice **state-driven but overridable**:
  `default: "= state.mode == 'degraded' ? 'db_only' : 'cache_first'"`. It must return an existing
  option name, or the run aborts.
- A run override that names a missing option produces a warning and falls back to the default.
  Scenarios are validated, so this only happens with `--choice`.
- **Per-call choices** (§13.1 item 24). A scenario's, step's or request's choice may be a list or a
  map instead of one option. A list is consumed one entry per evaluation of the choice point, and
  its last entry repeats: `choices: {replica.read.outcome: [timeout, timeout, ok]}` times out
  twice, then succeeds. A map keyed by evaluation number (from 1) sets only those evaluations,
  and the others use the `default`: `choices: {replica.read.outcome: {"2": timeout}}`. The count
  is of evaluations in the run, across every call and instance. A step's own `choices` entry
  starts a fresh count for that step; inherited scenario entries keep counting across steps.
  `--choice` takes one option only.
- The trace's `choice` event records `key`, `option` and `origin` (`scenario`, `expression` or
  `default`).
- After a choice, execution continues with the next step unless the option returned or failed.

## 7. return, fail, emit and wait

- **`return: <template>`** ends the behavior successfully with the value. The value is checked
  against the `response` schema (mismatches are warnings).
- **`fail: {code, message?, status?, retryable?, data?}`** ends it with an error. Values may be
  templates: `message: "= 'no pool member answered: ' + error.code"`. `fail` may also be one
  expression producing such a map: `fail: "= {'code': 'lookup_failed', 'status': 503}"`. A
  literal must be an object with a `code`.
- **Falling off the end** (no `return` or `fail`) returns fake data from the `response` schema, or
  null without one.
- **`emit: <interface id>`** with optional `input` (otherwise fake request data) queues an async
  message. The message is delivered after the current top-level call tree (the entry call)
  finishes, in FIFO order; messages emitted by those deliveries join the queue. Deliveries run even
  if the entry call failed. Their results never change `result`, but they do change `ctx`, `state`,
  `calls` and `duration_ms`. In the trace, the emit shows as an `emit` event, and the delivery as
  `call.start`/`call.end` with `async: true`.
- **`wait: <ms>`** or `wait: "= cel"` advances the virtual clock: `wait: "= input.response.tokens_out / 10"`.
  A negative literal is invalid, and a negative computed value counts as 0.

## 8. What a call does at run time

For each attempt, in order:

1. The request is checked against the callee's `request` schema (mismatches are warnings).
2. **Faults** are checked. Every interface and component keeps an invocation counter, and every
   attempt and async delivery counts. The first fault (in list order) whose `target` is the
   interface or its component, and whose `calls` include the current count (or that has no
   `calls`), applies. `match: "<cel over input>"` and `caller: <interface id or glob>` narrow a
   fault to some calls, and its `calls` then count only those (§26). It records a `fault` event and adds one to `faults`.
   - `unavailable`: fails immediately, with no latency:
     `{code: unavailable, status: 503, retryable: true}`. `code`, `status`, `message` and
     `retryable` override these.
   - `error`: adds the callee's latency, then fails with `{code, status, message}`, where
     `retryable` is **false unless set**.
   - `latency`: adds `latency_ms` on top of the normal latency, then runs normally. Combine it with
     the caller's `timeout_ms` to get late completions.
   - `timeout` (or its other name, `hang`): the callee never answers. The caller waits its
     `timeout_ms` (or 30000 ms) and gets a `timeout` error. The behavior doesn't run. With
     **`forever: true`** there is no 30000 ms release: a caller with no `timeout_ms` and no
     deadline waits until the run ends, and the call is reported **pending** (§26).
   - `lost_reply` (crash after effect, §13.1 item 25): the callee runs **to the end, and its writes,
     emits and nested calls stand**, but its reply never arrives. Without `code` the caller waits
     its `timeout_ms` (or 30000 ms) and gets a `timeout` error, as for a Temporal start that
     committed but timed out. With `code` (and optional `status`, `message`) the caller gets that
     error at the callee's end instead, `retryable` **true unless set**. Compact form:
     `--fault db.put:lost_reply[:CODE[:STATUS]][@N]`.
   - `crash` (§13.1 item 25): the callee runs only its first `after_steps` steps (required, from
     0), then stops; the caller gets `{code: crashed, status: 500, retryable: true}` (`code`,
     `status`, `message` and `retryable` override). Steps count when they have an action and
     their `when` passes, at any nesting depth of the callee's own behavior (not inside `parallel`
     branches); a `store` interface's operation counts as one step, so `after_steps: 0` applies
     nothing and `1` applies the write and then crashes. When the behavior ends within
     `after_steps`, the reply is still lost. Compact form: `--fault worker.run:crash:2@1`.
   - **A retry sees the first attempt's partial effects.** Nothing rolls back: a retry is a new
     invocation that reads the state the crashed or lost attempt wrote, and its emits, timers and
     nested calls stand (at-least-once delivery). Model idempotency explicitly, with `if_absent` or
     `if` on the writes (§10) or a check of `state` first. Limit the fault to the first attempt
     with `calls: [1]` so the redelivery succeeds.
3. Otherwise the latency is added (`latency_ms`, 1 ms by default), then the behavior runs, or the
   stub returns fake response data.
4. If the elapsed time exceeds `timeout_ms`, the callee's `call.end` is recorded with
   `late: true`, the clock returns to start + `timeout_ms`, and the caller gets a `timeout` error.
   Trace times can therefore step backwards here.

Calls to the flow's entry interface go through the same path, so it can be faulted too.

## 9. Run setup and budgets

- **Input**: fake data from the entry interface's `request` schema, deep-merged with the flow's
  `entry.input`, then the scenario's `input`, then the run's `--input`. Maps merge and other values
  replace.
- **Absent and null inputs** (§13.1 item 24). Fake data fills every declared field, optional ones
  too. In an entry, scenario, step or `--input` input, `{$absent: true}` removes the key, faked
  value and all, so a behavior sees `has(input.tag) == false`: `input: {tag: {$absent: true}}`.
  `{$null: true}` sets a real JSON `null`. A literal `null` keeps its old meaning (no override:
  the fake value if the schema declares the key, else `null`). A later layer can set a removed
  key again, and its own `$absent` removes an earlier layer's value. Nested keys work too:
  `{meta: {b: {$absent: true}}}`. These markers apply to entry inputs only, not to a behavior's
  `call` or `emit` input (there an unset key is simply not written).
- **State**: each component's `state.initial`, deep-merged with the scenario's `state`, then the
  run's `--state`.
- **Choices** are overlaid (the run wins). **Faults** and **expectations** are concatenated
  (scenario first). **Seed**: the run's value, else the scenario's, else 1.
- **Budgets**: 20,000 events, call depth 64, 1,000 emits and 10,000 `foreach` iterations.
  Exceeding one, or any runtime CEL error, makes the status `aborted`, and `abort` names the cause.
- **Run caps are per scenario, not fixed.** **`max_events: N`** on a scenario raises (or lowers)
  the event budget, default 20,000, up to 1,000,000: a load test of 200 requests does not need
  to shrink to 65. **`max_virtual_ms: N`** stops a run at virtual time N with a warning (default
  3,600,000 for scenarios with `await`, `cancel` or `restart` steps, otherwise none). When either
  cap ends a run, the summary's `caps: {max_events, max_virtual_ms, hit}` reports both (§26).
- **CEL cost limit**: each evaluation may cost at most 10,000,000 (it was 1,000,000, which
  prompts of about 500 tokens exceeded). A scenario can set its own: `cost_limit: 50000000`.
  An expression over the limit aborts the run with `operation cancelled: actual cost limit exceeded`.
- An unknown flow or scenario, a scenario run with a different `--flow`, an invalid fault, a bad
  entry input template, or a `--choice` whose key is not a choice point or whose option doesn't
  exist is a request error: the run doesn't start.
- `mosaic plan` lists entry and call targets that are not interfaces under `unknown`; they are
  neither reachable nor faultable.

## 10. store: datastores that hold rows

A stub returns fresh fake data on every call, so a row written by one call can't be read back by
another. Give the datastore's interfaces a `store` instead of a behavior:

```yaml
- component: dynamodb
  name: vms-get
  errors: [{code: vm_not_found, status: 404}]
  store: {table: vms, op: get, key: "= input.id", where: "row.org_id == input.org_id", not_found: vm_not_found}
- {component: dynamodb, name: vms-put, store: {table: vms, op: put, key: "= input.id", value: "= input"}}
```

- Rows live in the owning component's `state.<table>`, a map from string id to row. An integer key
  becomes its decimal string; an empty or non-scalar key aborts the run.
- `key`, `value` and `default` are templates over `input`, `state`, `ctx` and `now`. `where` is CEL
  over the same variables plus `row` (`null` when absent) and `key`.

| `op` | Needs | Returns | On a miss |
|---|---|---|---|
| `get` | `key` | A copy of the row. A row failing `where` counts as a miss. | `default` when set, else the not-found error |
| `put` | `key`, `value` | The row: `value` replaces it | Inserts |
| `update` | `key`, `value` | The row with `value` deep-merged over it (maps merge, other values replace) | The not-found error |
| `delete` | `key` | The removed row | `null` |
| `query` | no `key` | A list of the rows passing `where`, sorted by key | `[]` |
| `incr` | `key`, `value` | The row after adding `value`: a number to a numeric row, or a map of deltas field by field | Absent rows and fields start at 0 |

- On writes, `where` is a **condition**: when false, nothing changes and the call fails with the
  conflict error. `where: "row == null"` is create-if-absent; `where: "row.version == input.version"`
  is optimistic concurrency.
- The not-found error is the declared error named by `not_found`, else a declared error with code
  `not_found`, else `{code: not_found, status: 404}`. The conflict error works the same way with
  `conflict` and `{code: conflict, status: 409}`. Status and `retryable` come from the declaration.
- Every write records a `set` event on `state.<table>.<key>` (with `old` and `new`), so the trace
  and `state` show what changed. Reads record nothing beyond the call.
- Latency and faults apply first, as for any call. A store beside a behavior is ignored (the
  validator warns). Store results are not checked against the `response` schema.
- **Seed** rows like any state: `state: {dynamodb: {vms: {vm-1: {id: vm-1, org_id: o1, status: running}}}}`
  in a scenario, or `--state dynamodb.vms='{"vm-1": {...}}'`. Assert on them with
  `state.dynamodb.vms['vm-1'].status == 'running'`.
- Validation: `table` is an identifier; `key` is required except for `query`, which refuses one;
  `value` goes only with `put`, `update` and `incr` (and is required there); `default` only with
  `get`; `not_found` only with `get` and `update`; `conflict` only on a write with `where`, `if`
  or `if_absent`; named codes must be declared errors.

### Conditional writes (§13.1 item 25)

Like DynamoDB's `ConditionExpression`, a write can carry a condition checked against the current
row:

```yaml
store: {table: config, op: update, key: "= input.id", value: {v: "= input.v + 1"}, if: "row.v == input.v", conflict: stale}
store: {table: runs, op: put, key: "= input.id", value: "= input", if_absent: true}
```

- `if` is CEL over `row` (`null` when absent), `key` and the behavior variables; it goes with
  `put`, `update`, `delete` and `incr`. `if_absent: true` goes with `put` and requires that no
  row exists.
- When the condition fails, nothing changes and the call fails with the declared error named by
  `conflict`, else a declared `condition_failed`, else `{code: condition_failed, status: 412}`
  (not retryable unless declared so). `error.data` is `{table, key, row}`, the row that failed.
- `where` still works as a write condition (code `conflict`); `if` is the explicit form. Prefer it
  over "read then put" or a fault to model compare-and-set.

### transact: all-or-nothing writes

```yaml
- transact:
    - {table: accounts, op: update, key: "= input.from", value: {bal: "= state.accounts[input.from].bal - input.amt"}, if: "row.bal >= input.amt"}
    - {table: accounts, op: incr, key: "= input.to", value: {bal: "= input.amt"}}
    - {table: ledger, op: put, key: "= input.id", value: "= input", if_absent: true}
  as: tx
  on_error: continue
```

- A behavior step whose writes (`put`, `update`, `delete`, `incr`, each with the store fields
  above) apply to the **running instance's** state. They are evaluated in order against a staged
  copy, so a later write's `row` sees an earlier one; `state` in templates is the state before the
  transaction.
- If every write passes, all commit, with one `set` event each. If any fails its condition or
  misses its row (`update`), **none** is applied, and the step fails with that write's error,
  whose `data.index` names the write (like `TransactionCanceledException`).
- `as` stores `{ok, value: [each write's result], error}`; `on_error` works as for a call
  (default `propagate`). Codes named in the writes must be declared errors of the interface
  running the behavior.

## 11. foreach, break and continue

```yaml
- foreach: "= input.hooks"   # a list, a map (e.g. "= state.webhooks") or a literal list
  as: hook        # vars.hook holds the item (default: item)
  index: i        # vars.i holds the 0-based position, or the key for a map (default: index)
  max: 20         # default 100, at most 1000
  steps:
    - {if: "vars.hook == 'muted'", then: [{continue: true}]}
    - {call: webhook-sender.deliver, input: {url: "= vars.hook"}, as: sent, on_error: continue}
    - {if: "!vars.sent.ok", then: [{break: true}]}
```

- The template is evaluated once, before the first iteration. Lists run in order; maps run in
  **sorted key order** with the key in the index variable. `null` runs nothing; any other value
  aborts the run. (Iterating a map with CEL macros like `map.map(k, ...)` is not ordered, so loop
  over the map itself when order matters.)
- More than `max` items: the first `max` run and the run gets a warning. To process a batch on
  purpose, slice the list instead: `"= input.items.slice(0, 10)"`.
- Iterations are sequential and share the behavior's `vars`, `state` and `ctx`. `return` and `fail`
  inside the body end the behavior. `break` leaves the innermost loop and `continue` goes to its
  next item; both are only valid inside a `foreach` body (including nested `if`, `choice` and
  `on_error` steps). When the loop ends, the `as` and `index` variables get back their earlier
  values.
- A choice inside a loop has one key, so one override applies to every iteration; an expression
  `default` can depend on `vars.item`.

## 12. Repeated entries: reconcilers and crons

```yaml
flows:
  - id: vm-reconcile
    entry: {caller: scheduler, interface: reconciler.tick, repeat: {count: 3, interval_ms: 30000}}
```

- The entry runs `count` times (1 to 100). Each pass delivers its emits, then the clock advances
  `interval_ms` before the next pass. State, `ctx` and the clock carry over; every pass gets the
  same input, so behaviors tell passes apart through `state` and `now`.
- Expectations see `passes`: `[{pass, result, start_ms, duration_ms}]`, for example
  `passes[0].result.error.code == 'unavailable' && passes[2].result.ok`. `result` and `status` are
  the last pass's; `state` is the final state. The summary's `passes` appears only when the entry
  repeats.
- Budgets count across all passes, so a long repeat can hit the event budget.

---

# Additions for systems with many parts

> Requires mosaic with DESIGN §11 (in progress). Every addition is optional; a model that uses
> none of them behaves exactly as described above. Recipes: [recipes.md](recipes.md), sections
> 15 to 24. Entity fields: mosaic-ontology's `references/document-format.md`, "Additions for
> systems with many parts".

## 13. Instances: `self` and `on`

A **topology** (in a fixture, scenario or run request) names the instances of a component's
subtree: `topology: {cassandra-node: [n1, n2, n3]}`. A component belongs to the group of its
nearest ancestor with a topology entry, or of itself; a component in no group has one unnamed
instance, `""`.

- **`self`** (CEL) is the instance the current behavior runs on, or `""` outside a group.
- **Where the entry runs:** the first instance of the entry component's group, or `entry.on`, or
  a scenario step's `on`.
- **`on: <instance or "=cel">`** on a `call`, `emit` or `publish` picks the callee's instance.
  Without `on`:
  - a callee in the **caller's group** runs on the **caller's instance** (in-process calls stay
    local);
  - a callee in **another group** runs on that group's **first** instance, with a warning when
    the group has several (say which one with `on`);
  - a callee in no group runs on its single instance.
- An `on` naming an unknown instance fails the call with `{code: unknown_instance}`.
- **State is per instance.** The `state` variable is this instance's state. Overrides and the
  summary key it as `<component>@<instance>` (`state['gossiper@n2']`), or `<component>` for the
  unnamed instance. Store tables are per instance, so each replica's rows stay separate.
- **Faults** take `instance`, which limits them to one instance; without it they hit every one.
  `calls` still counts invocations of the target across instances.
- The trace's events carry `instance`, and the summary adds `calls_by_instance`, keyed
  `<interface>@<instance>`.

```yaml
- call: mutation-verb-handler.do-verb
  on: "= vars.replica"                 # an instance name, not an address in the request
  input: {mutation: "= input.mutation"}
- if: "vars.replica == self"           # the local branch
  then: [{call: keyspace.apply, input: {mutation: "= input.mutation"}}]
```

Don't put `to`, `endpoint` or `host` fields in a request to say where a call goes. That was the
workaround before instances existed, and it can't hold per-replica state.

## 14. parallel with a join

```yaml
- parallel: "= vars.replicas"     # a list (or a map, in key order); or branches: [[steps], [steps]]
  as: replica                     # vars.replica in each branch; vars.index its position
  steps:                          # the body of each branch
    - {call: replica.write, on: "= vars.replica", input: "= input"}
  join: {need: "= vars.block_for"}   # an int or "=cel"; `all` (the default) or `any`
  stagger_ms: 0                   # branch i is due at i * stagger_ms; it starts only if the join is still unmet
  timeout_ms: 2000                # for the join as a whole
  as_result: acks                 # vars.acks
  on_insufficient: {code: unavailable, status: 503}   # default {code: insufficient, retryable: true}
```

- **Concurrent in virtual time.** Every branch starts at the step's start time (plus its stagger)
  on its own clock. A branch succeeds when its steps finish without failing; it fails when a step
  fails or an error propagates out of it. A `return` inside a branch ends only that branch, and
  becomes its `value`.
- **The join** is met when `need` branches have succeeded. The step completes at the finish time
  of the `need`-th success, and the clock resumes there.
- **Failing fast.** As soon as `need` successes become impossible, the step fails with
  `on_insufficient`, with `data: {received, required, failed}`.
- **Timeout.** At start + `timeout_ms`, or at the request deadline (§15) if earlier, the step
  fails with `{code: timeout, retryable: true, data: {received, required}}`.
- **Branches run to completion.** Branches still running when the join completes, and due ones
  without a stagger, still run. Their events after the join time are marked `late`, as with call
  timeouts. Their state changes stand.
- **Staggering (hedging).** With `stagger_ms`, branch *i* is due at *i* × `stagger_ms`, and it
  starts only if the join is still unmet then. `join: {need: 1}` with `stagger_ms: 50` is a hedged
  or speculative request: the second copy is sent only if the first hasn't answered in 50 ms.
- **State isn't interleaved.** Branches execute in list order, each seeing the state the earlier
  ones left, while their events carry their true virtual times. Read a trace with parallel steps
  in `seq` order, not `t`. Races on shared state between branches can't be expressed.
- **The result** (`as_result`): `{ok, received, required, failed, duration_ms, results: [{item,
  index, ok, value, error, start_ms, end_ms, late}]}`.
- `foreach` keeps its sequential semantics. Use `parallel` when the code sends concurrently and
  waits; use `foreach` when it really loops one at a time.

| Code pattern | Join |
|---|---|
| wait for all (`Promise.all`, `allOf`, an all-reduce, a barrier) | `join: {need: all}` |
| wait for k of n (quorum, `blockFor`) | `join: {need: "= vars.block_for"}` |
| first success wins (`Promise.any`, first provider, hedging) | `join: {need: any}` or `{need: 1}`, with `stagger_ms` for hedging |

## 15. Time: one clock and deadlines

- **One clock.** `now` is `epoch_ms` + virtual ms. The epoch comes from a fixture, scenario or
  request (`clock: {epoch: "2026-10-30T00:00:00Z"}` or `{epoch_ms: N}`), and is 0 by default.
  Every timestamp a model stores or compares must derive from `now`: write
  `state.down_since: "= now"`, never a literal. Validation warns about numeric literals over
  10^12 compared with `now`.
- **Deadlines.** `deadline_ms` on a flow `entry`, a scenario step or a `call` is relative to its
  start. Nested calls and branches inherit it, and the earlier deadline wins.
  - A call's effective timeout is `min(timeout_ms, deadline - now)`.
  - A call that starts at or after the deadline fails at once with
    `{code: deadline_exceeded, retryable: false}`.
  - Retries stop when the next attempt would start after the deadline.
  - CEL `deadline` is the absolute deadline in ms, or `null` when none applies.

```yaml
- call: replica-set.read
  deadline_ms: "= config['read-request-timeout-ms']"   # every nested hop shares this budget
  as: read
```

**Durations are templates.** `timeout_ms`, `deadline_ms`, `after_ms`, `every_ms`, `stagger_ms`,
`count` and `join.need` take a number or a `"=cel"` template, evaluated in the behavior
environment when the step runs. Read deployed values from `config` rather than writing numbers,
so a scenario's `config` override changes them too.

Use `timeout_ms` for a per-call limit, and `deadline_ms` for a budget that starts with the
request (request timeouts, cancellation tokens with a timeout, an abort after N seconds).

## 16. Timers

- `emit` and `publish` take **`after_ms`** (deliver once, after a delay) or **`every_ms`** with
  **`count`** (deliver periodically, `count` times).
- Timers are delivered in time order after the current top-level call tree finishes, as emits
  are. Timers due at the same time are delivered in the order they were scheduled.
- `entry.repeat` takes **`initial_delay_ms`** before the first pass.
- Each run has a budget of 1,000 timer deliveries.

```yaml
- emit: gossiper.gossip-task-run     # a periodic task, scheduled at startup
  every_ms: "= config['gossip-interval-ms']"
  count: 5
- emit: editor.autosave              # a debounce: deliver once, after the configured delay
  after_ms: "= config['files-auto-save-delay-ms']"
```

A debounce that is reset by later events is modeled by recording the latest schedule time in
state and making the delivered handler return early when a newer one exists.

## 17. Capacity

`capacity: {concurrency: N, queue_limit: M, queue_timeout_ms: T}` on a component means each of its
instances serves at most N calls at once. `concurrency` is required; `queue_limit` is optional
(0 means no waiting at all), and `queue_timeout_ms` 0 means no bound.

- A call that arrives while every slot is busy waits, in arrival order, until the earliest slot
  frees. The trace gets a `queue` event with the wait, and the summary counts `queued`.
- Past `queue_limit` waiting calls, a call fails with `{code: overloaded, retryable: true}`.
  `queue_timeout_ms` bounds the wait.
- Busy intervals are tracked per instance in virtual time, so capacity interacts with `parallel`
  branches, timers and multi-step scenarios.

Use it for thread pools, stages, connection pools, a single-threaded event loop
(`concurrency: 1`), GPU stream slots and a scheduler's maximum running sequences.

## 18. Publish and subscribe

- An interface receives a topic by declaring `subscribe: [<topic>, ...]`. A topic is a slug,
  conventionally the id of an `event`-kind interface.
- **`publish: <topic>`** with `input` delivers the input to every subscriber, in sorted interface
  id order, on the publisher's instance unless `on` is given.
- **`delivery: sync`** runs subscribers inline, like a JavaScript or VS Code `Emitter`. Their
  errors are recorded and don't fail the publisher unless `on_error: propagate`.
- **`delivery: async`** (the default) queues them like `emit`, and `after_ms`/`every_ms` apply.
- Plans and static reach include the subscribers.

```yaml
# the source
- publish: endpoint-state.on-change
  input: {endpoint: "= input.endpoint", status: down}
  delivery: sync
# a subscriber
- component: hints-dispatcher
  name: on-endpoint-change
  subscribe: [endpoint-state.on-change]
  behavior: [...]
```

## 19. Config and latency expressions

- CEL **`config`** maps config ids to their values: the config entities' `value`, then fixture,
  scenario and request overrides. Use bracket access for hyphenated ids:
  `config['hinted-handoff-enabled']`.
- **`latency_ms: "=cel"`** computes service time per call from `input`, `state`, `config` and
  `self`: `latency_ms: "= 5 + input.prompt_tokens / 50"`.

## 20. Multi-step scenarios

A scenario can run a sequence of entry calls that share one world:

```yaml
- id: write-then-read
  fixtures: [three-node-rf3]
  steps:
    - {flow: cql-insert, as: w, input: {query: "INSERT INTO shop.users (id, name) VALUES (42, 'Ada')"}}
    - {flow: cql-select, as: r, at_ms: 10, on: n2, input: {query: "SELECT name FROM shop.users WHERE id = 42"}}
  expect:
    - "steps.w.result.ok"
    - "steps.r.result.ok && steps.r.result.value.rows[0].name == 'Ada'"
```

- A step names a `flow` (its entry, with the step's `input` merged over the entry input) or an
  `interface` with a `caller`. It may set `input`, `on`, `choices`, `deadline_ms`, `at_ms`,
  `repeat` and `as`.
- **A flow step makes one pass**, even when the flow's `entry.repeat` is set: scenarios step a
  repeating flow one pass at a time. To repeat a step, give it its own **`repeat: {count,
  interval_ms, initial_delay_ms}`** (§13.1 item 24): it calls its target `count` times, each pass
  `interval_ms` after the previous pass's call tree finished, with `deadline_ms` counted from each
  pass's start. Earlier passes' emits and timers are delivered as the clock advances (unlike
  `entry.repeat`, a pass doesn't wait for them); the step ends when the last pass and every
  delivery have finished, and its result is the last pass's.
- **`at_ms`** is the absolute virtual time the step starts. By default (no `at_ms`) a step starts
  when the previous step has ended: its call tree finished and its emits and timers delivered, or
  everything left is a loop idling on a `receive`. A step with `at_ms` starts at that time, even
  while earlier steps or timers are still running (an `at_ms` already in the past starts at once,
  with a warning). `await: false` starts a step and moves straight on to the next. Those two are
  the only ways steps overlap; for concurrency inside a step, use `parallel`. A step run with
  `await: false` records its result only when it ends, so a later step can read
  `steps.<as>.result` only after that (DESIGN §13.1 item 14).
- **`lane: <name>`** marks steps one host thread issues in sequence (DESIGN §17 item 11). Under
  `--explore`, steps of one lane keep their program order, even with `await: false` and equal
  start times; steps in different lanes, or in none, are reordered as ties. Use it for a host
  issuing async work (`await: false`) to several streams or queues.
- **State, `ctx`, the clock, timers and capacity carry over** between steps.
- Step templates and expectations see **`steps.<as>`** (or `steps[i]`):
  `{result, status, duration_ms, start_ms}`. Every `duration_ms` (steps, `vars.<as>`, `io`,
  `passes`, parallel results, the run's) is whole ms rounded down; `duration_us` beside it is
  the exact integer µs (DESIGN §17 item 10). A later step's input can use an earlier result:
  `input: {id: "= steps.prep.result.value.id"}`. `result` and `status` are the last step's.
- The scenario's `flow` may be omitted; it defaults to the first step's flow, for grouping.
- The summary adds `steps`, the step results.

Tag every flow that writes state `writes` (`tags: [writes]`). Such a flow must have at least one
multi-step scenario that reads its effect back through the system's own read path; the check
tool reports violations under `--lint hollow`. It is the cheapest proof that writes land.

## 21. Assertions on the trace, and mocks

**What expectations see.** Besides the variables of the SKILL.md (`result`, `status`, `calls`,
`ctx`, `state`, `retries`, `faults`, `duration_ms`, `warnings`, `passes`), expectations see
`config` (the effective values), `topology`, `calls_by_instance` (`calls_by_instance['commit-log.add@n2']`),
`steps` and `trace`. They don't see `self` or `deadline`, which belong to behaviors.

**The trace in expectations.** Expectations see `trace`, a list of `{seq, t, type, interface,
component, instance, input, output, error, late, title, key, option}` events. Query it with CEL
macros:

```yaml
expect:
  # the mutation reached n2's commit log
  - "trace.exists(e, e.type == 'call.start' && e.interface == 'commit-log.add' && e.instance == 'n2')"
  # no hint was written
  - "!trace.exists(e, e.type == 'call.start' && e.interface == 'hints-service.write')"
  # exactly two replicas acknowledged before the join
  - "trace.filter(e, e.type == 'call.end' && e.interface == 'mutation-verb-handler.do-verb' && !e.late).size() == 2"
  # the commit log append happened before the memtable update
  - "trace.filter(e, e.type == 'call.start' && e.interface == 'commit-log.add')[0].seq < trace.filter(e, e.type == 'call.start' && e.interface == 'memtable.put')[0].seq"
```

Prefer `trace` over `ctx` bookkeeping when the fact is "this was called, where, in what order":
it needs no extra `set` steps in behaviors.

**Mocks: a last resort.** `mocks: [{interface, instance, when, return | fail, calls}]` on a
scenario makes matching calls return the mock instead of running the behavior; `when` is CEL over
`input`, and `calls` lists the matching invocations affected. The trace marks them `mock`, and the
summary counts `mocks`. Mocks isolate one fragment while you debug it. They hide seams: a mocked
answer never checks the owner's real contract. The check tool counts them, refuses them under
`--no-mocks`, and the generation pipeline forbids them in merged-model, oracle and judge
scenarios. Drive the branch through the real component's state or a fixture instead.

## 22. CEL helpers

Available in every environment (behaviors, templates, `where`, expectations):

| Helper | Example |
|---|---|
| two-variable comprehensions: `transformMap`, `transformList`, `all`/`exists` with two variables | `vars.cells.transformMapEntry(i, c, {c.column: c.value})` builds a map from a list (`transformMap(i, v, filter, transform)` keeps list indexes as keys) |
| `sum(list)` | `sum(vars.acks.results.map(r, r.ok ? 1 : 0))` |
| `merge(map, map)`: deep merge, right side wins | `merge(state.row, input.columns)` |
| `omit(map, key...)` | `omit(state.endpoints, input.endpoint)` |
| `random(n)`: seeded per run, deterministic, an int in `[0, n)` | `random(100)` for a random back-off from 0 to 99 ms |
| `channel_len(name)`: the items queued on a channel (§23) | `channel_len('requests') > 8` to shed load |
| `sha256(s)`, `sha256Bytes(b)`: lowercase hex | `sha256(input.api_key) in state.key_hashes` |
| `hmacSha256(key, msg)`, `hmacSha256Base64(key, msg)`: lowercase hex, or standard base64 | `'v0=' + hmacSha256(config.slack_secret, 'v0:' + input.ts + ':' + input.body)` |
| `byteLen(s)`: UTF-8 bytes (`size(s)` counts code points) | `byteLen(input.body) > config.max_body_bytes` |
| `substrBytes(s, start, end)`: Go's `s[start:end]` on bytes; a cut inside a character keeps the partial bytes; out of bounds is an error | `substrBytes(vars.log, math.greatest(0, byteLen(vars.log) - 4096), byteLen(vars.log))` for a log tail |
| `base64Encode(s or b)`, `base64Decode(s)`: standard base64; decode returns a string and fails on non-UTF-8 (`base64.decode` gives bytes) | `base64Decode(input.token).split(':')[0]` |
| `fnv64a(s)`: FNV-1a 64; a uint, or a decimal string above 2^63-1 | `uint(fnv64a(input.session)) % 4u` for sticky routing |
| `log2(x)`, `ln(x)`: doubles, for an int or double | `int(log2(input.size))` for a size bucket |
| `list.indexOf(x)`, `list.lastIndexOf(x)`: the first or last index of an element equal to `x` (CEL equality), or -1; strings keep their own `indexOf` | `state.queue.indexOf(input.request_id)` for a queue position |
| `ip(s)`: the normalized address (an IPv4-mapped IPv6 becomes IPv4, `2001:DB8::1` becomes `2001:db8::1`); an invalid address is an error | `ip(input.x_forwarded_for.split(',')[0].trim())` for a client-IP key |
| `inCidr(ip, cidr)`, `inAnyCidr(ip, [cidrs])`: the prefix is masked; families never cross; an invalid address or prefix is an error | `inAnyCidr(input.peer, config.trusted_proxies)` |
| `ipFamily(ip)`: 4 or 6 | `ipFamily(input.peer) == 6` |
| `ipIsLoopback`, `ipIsPrivate`, `ipIsLinkLocal`, `ipIsMulticast`, `ipIsUnspecified`: Go's `net/netip` predicates (`ipIsLinkLocal` is link-local unicast or multicast) | `ipIsLoopback(h) \|\| ipIsPrivate(h) \|\| ipIsLinkLocal(h)` for an SSRF netguard |

The hashing, HMAC, base64, `substrBytes` and `fnv64a` helpers cost 1 plus 1 per 10 bytes of input
against the cost limit; the list `indexOf` and `lastIndexOf` cost 1 plus 1 per element; the others
cost 1.

## 23. Streams, channels and kills

These model streamed responses (SSE, token streams, VS Code progress), busy loops waiting on
queues (vLLM's engine core, worker pools, producer/consumer pipelines) and crashing processes.
Each opts the run into the concurrent scheduler: work runs as tasks that interleave in virtual
time, and shared state is read live.

**Streams.** A behavior step `yield: <template>` sends one item to its caller and keeps running.
A caller opts in with `stream: true` and handles each item with `on_item` steps, which see
`vars.item` and `vars.item_index` and run at the item's virtual time, interleaved with the
callee (or, if the previous item's steps are still running, as soon as they finish):

```yaml
- component: gateway
  name: chat
  behavior:
    - call: model.generate
      stream: true
      as: gen                        # vars.gen.value is the callee's return
      on_item:
        - {call: browser.sse, input: {chunk: "= vars.item", index: "= vars.item_index"}}
    - {return: "= vars.gen.value"}
- component: model
  name: generate
  latency_ms: 20                     # prefill
  behavior:
    - foreach: "= input.tokens"
      steps:
        - {wait: 10}                 # one decode step
        - {yield: "= vars.item"}
    - {return: {finish_reason: stop}}
```

- Without `stream: true`, the yields are collected: the caller's `value` is
  `{items: [...], value: <return>}` (for any callee whose behavior contains a `yield`).
- **`streams_when: "=<cel>"`** on the callee interface decides per call (DESIGN §17 item 12).
  It is a boolean over `input`, `config` and `vars`, evaluated when the call starts. When it is
  false, the caller gets the plain return (`result.value.text`, not `result.value.value.text`),
  and a `yield` reached on that call aborts the run, so guard the yields with the same condition.
  Absent, every call streams. Only an interface whose behavior has a `yield` may set it:

  ```yaml
  - component: api-server
    name: chat-completions
    streams_when: "= input.stream == true"     # SSE only when the request asks
    behavior:
      - if: "input.stream == true"
        then: [{yield: {delta: Hel}}, {yield: {delta: lo}}]
      - {return: {text: Hello}}
  ```
- A `return`, `fail` or propagated error in `on_item` ends the call there; the callee runs on and
  its later events are `late`. `on_item` needs `stream: true`; both go only on `call`.
- `token`, `timeout_ms`, `deadline_ms` and `retry` work as on any call. The timeout is checked
  when the callee finishes, as for other calls.
- Each yield is a `yield` trace event: `output` is the item, `index` its position.

**Channels.** Run-wide named FIFO queues:

```yaml
- {put: requests, value: "= input", capacity: 64, timeout_ms: 100}   # blocks while 64 are queued
- {receive: requests, as: req, timeout_ms: 5000, on_error: [{return: idle}]}
```

- `put: <name or "=cel">` adds `value`. With `capacity`, a put on a full channel blocks until a
  receive makes room (producers resume in arrival order). Without it the channel is unbounded.
- `receive: <name or "=cel">` takes the oldest item into `vars.<as>`, blocking until one is put.
- Past `timeout_ms` or the deadline, either fails with `{code: timeout, data: {channel}}`, which
  `on_error` handles as for a call.
- A put and a receive must be in different tasks (a scenario step with `await: false`, an emit,
  a timer or a parallel branch): a behavior can't hand an item to itself.
- A receive with no timeout that is still waiting when every other task has finished is an
  **idle consumer**: the run ends without it and without a warning. Its scenario step (if it is
  one) ends `canceled`.
- `put` events carry `key` (the channel), `input` (the item), `output.len` and `wait_ms`;
  `receive` events carry `key`, `output` (the item) and `wait_ms`.

A busy loop is a step started with `await: false` whose behavior loops over `receive`:

```yaml
steps:
  - {interface: engine-core.run-busy-loop, caller: engine, await: false}
  - {interface: api-server.add-request, caller: client, at_ms: 50, input: {id: a}}
```

**Kills.** A fault `{target: <component>, type: kill, instance: <i>, at_ms: <t>}`, a behavior
step `kill: {component, instance}` or a scenario step `{kill: {component, instance}}` terminates
an instance (instance defaults as for `restart`):

- Every call into the instance that is in progress stops. The task running it unwinds: each call
  it abandons ends with `{code: killed}` (call.end), and the caller of the outermost one gets
  `{code: peer-killed, retryable: true}`, which `on_error` and `retry` handle as usual.
- Parallel branches running inside such a call stop; queued deliveries to the instance are
  dropped; other waiters of a rendezvous that a killed task was waiting in fail with
  `peer-killed`.
- Later calls to the dead instance fail at once with `peer-killed`.
- The killed component's state gets `dead: true`. A later `restart` of the instance revives it
  (resetting its state, so `dead` goes away).
- The trace records a `kill` event (`output: {failed, stopped, dropped}`).

**Blocking waits and signals.** (DESIGN §17 items 2 and 14.) A `wait` written as an object blocks
the task until a condition holds or a signal arrives:

```yaml
- wait: {until: "= state.ready", signal: <name or "=cel">, signals: [<name or "=cel">, ...],
         timeout_ms: 500, on_timeout: fail, as: w}
```

- It needs `until`, a signal (`signal`, `signals` or both: the wait wakes on any of them) or both.
- `on_timeout` is `fail` (the default, `{code: timeout}`), `continue` or a list of steps.
- `vars.<as>` is `{reason: until | signal | timeout, signal?, data?, waited_ms}`: `signal` names
  the signal that woke it and `data` is what that signal carried.
- A `signal: <name>` action delivers a signal to the waits parked on it now. A signal nobody waits
  for is lost.
- A kill delivers `kill:<component>[@<instance>]` (no data).

**Exit signals.** When an instance group stops, the simulator delivers
`exit:<component>[@<instance>]` for **every component of the group** on that instance, carrying
`data: {component, instance, reason, at_us}`. Use it for a monitor that blocks on process
sentinels (`multiprocessing.connection.wait`, a watchdog thread, `waitpid`):

- `reason: killed` comes from a kill fault, a kill step, or a behavior's `kill` of its own
  instance, which models a process exiting on its own.
- `reason: restarted` comes from a `restart` of a live instance. A restart of a dead instance
  raises nothing, because it already exited at its kill.
- An exit is remembered while the instance stays dead, so a wait that starts after the kill
  returns at once (`waited_ms: 0`), as a dead process's sentinel does. A restart forgets it.
- Nothing changes for a run that never waits on `exit:` signals.

```yaml
- component: engine-core-client
  name: monitor-engine-cores
  behavior:
    - wait: {signals: ["exit:engine-core@dp0", "exit:engine-core@dp1"], as: died}
    - {set: {state.engine_dead: true, state.died: "= vars.died.data"}}
    - {call: engine-core-client.shutdown}
# scenario: start the monitor with await: false, then kill an instance
steps:
  - {interface: engine-core-client.monitor-engine-cores, caller: client, await: false, as: mon}
  - {kill: {component: engine-core, instance: dp1}, at_ms: 40}
expect:
  - "steps.mon.result.ok && state['engine-core-client'].died.reason == 'killed'"
```

## 24. Route calls and redirects

(DESIGN §13.1 item 26.) Use a route call when the code under test sends an HTTP request and the
server's router picks the handler, for example when a path is cleaned, a route has parameters, or
the client follows a redirect. Id calls are unchanged.

```yaml
components:
  - id: control-plane
    router:
      hosts: [api.gateway.test]        # exact names or "*.suffix"; a port is ignored
      clean_path: 307                    # answer /v1/vms/.. with 307, location /v1 (Go's ServeMux)
      not_found: no_such_route           # code of an unmatched request (status 404); default not_found
      # method_not_allowed: ...          # code when only other methods match (status 405)
      # fallback: gateway.proxy          # an interface that takes unmatched requests instead
  - {id: cp-vms, parent: control-plane}  # routes come from the component and its descendants
interfaces:
  - component: cp-vms
    name: get-vm
    attributes: {method: GET, path: "/v1/vms/{vmId}"}
  - component: cli
    name: debug-exchange
    behavior:
      - call:
          component: control-plane       # or host: api.gateway.test, or an absolute URL as path
          method: GET                    # default GET; literals or "=cel"
          path: /v1/vms/..               # may carry ?query
          headers: {Authorization: "= input.token"}   # template
          body: {...}                    # template
          follow_redirects: true
          max_redirects: 10              # the default
        targets: [cp-root.get-v1]        # so plans and graphs can follow it
        as: r
```

- **Matching.** A route is an interface whose `attributes.path` starts with `/` (or is a Go
  `"GET /path"` pattern). `attributes.method` is a method, a list, or `ANY`, `*` or absent for any;
  `GET` also answers `HEAD`. Patterns take `{name}` and `:name` (one segment), `{name...}` (the
  rest, maybe empty), `{$}`, and a trailing `/` for a subtree. The most specific pattern wins
  (literal segments over parameters over rest, then an explicit method over `ANY`), then the lower
  interface id. A path that matches only under other methods gives 405.
- **Errors.** No route: the call fails with `{code: <not_found>, status: 404}` (or goes to the
  `fallback`). No router serves the host: `unknown_host`. These are ordinary call failures, so
  `retry` and `on_error` apply.
- **The callee's input** is built from the request, then the step's `input` is merged over it:
  each header at its lower-case key with `-` as `_` (`X-Org-Id` becomes `input.x_org_id`),
  `query` (first value per key), `body`, each path parameter by name (or in snake_case when only
  that is a request property: `{resourceSize}` fills `resource_size`), and
  `request: {method, path, host, headers, pattern}`. This matches the route interfaces a
  control-plane model typically has, whose requests are `{authorization, x_org_id, id, query, body}`.
- **Redirects.** With `follow_redirects`, a successful response with a 3xx `status` and a
  `headers.location` (any case) is followed against the current URL. 301, 302 and 303 turn a
  request other than GET or HEAD into a GET without a body; 307 and 308 keep both. A hop to
  another host drops `authorization` and `cookie`. Past `max_redirects` the call fails with
  `too_many_redirects`. Without `follow_redirects` the caller gets the 3xx response as the value.
- **Trace.** Each hop emits a `route` event before its call: `interface` is the match, `key` the
  pattern, `input` `{method, path, query, host}`, `output` a router-made redirect and `error` a
  404, 405 or unknown host. So `trace.filter(e, e.type == 'route').map(e, e.input.path)` lists
  every hop, `['/v1/vms/..', '/v1']` above. Each hop has its own call number.
- **Result.** `vars.r` also has `route: {method, path, query, host, component, interface, pattern,
  redirects: [{status, location, method, path, interface}]}` for the last attempt. `target` is the
  final interface (empty for a router-made redirect or a 404).

## 25. Back pressure: limiters

(DESIGN §13.1 item 27.) A limiter is what is counted, per what key, over what time, shared how,
and what happens when it's full: Redis token buckets, in-flight windows with leases, per-IP
hourly caps, in-process `rate.Limiter`s. Use it instead of hand-rolled counters in `state`. Use
`capacity` (§17) only for a per-instance pool of slots with a queue.

```yaml
components:
  - id: gateway
    limiters:
      - {id: per_ip, kind: fixed_window, key: "= input.x_peer_ip", limit: 5, period_ms: 3600000}
      - id: org_tokens                     # a Redis bucket every gateway task shares
        kind: token_bucket
        key: "= input.x_org_id"
        limit: "= config['org-rpm'] > 0 ? config['org-rpm'] : null"   # null: unlimited
        period_ms: 60000
        floor: -100                        # charge may go below 0, down to this
        scope: shared                      # default instance: per-instance state
        backend: redis.eval                # each decision calls it first: latency, faults, trace
        on_backend_error: fail_open        # or fail_closed, or propagate (the default)
      - {id: inflight, kind: concurrency, key: "= input.x_org_id", limit: 2, lease_ms: 30000}
      - {id: uploads, kind: concurrency, limit: 4, lease_ms: 60000, on_limit: wait, max_wait_ms: 500}
interfaces:
  - component: gateway
    name: chat
    errors: [{code: rate_limited, status: 429}]   # every applying interface declares the error
    limits: [per_ip, inflight, {limiter: org_tokens, gate: true}]   # at entry, all or nothing
    behavior:
      - {call: upstream.complete, as: r}
      - {charge: {limiter: org_tokens, cost: "= vars.r.value.tokens"}}   # after the response
      - {return: "= vars.r.value"}
  - component: gateway
    name: upload
    errors: [{code: rate_limited}]
    behavior:
      - {admit: {limiter: uploads, as: slot}}        # or limiters: [...], all or nothing
      - {call: storage.put}
      - {release: {limiter: uploads, lease: "= vars.slot.lease"}}
```

- **Kinds.** `token_bucket` holds `burst` (default `limit`) tokens and refills `limit` per
  `period_ms` continuously; `fixed_window` counts in epoch-aligned windows of `period_ms`;
  `sliding_window` counts the last `period_ms`; `concurrency` holds at most `limit` leases, each
  expiring after `lease_ms`. `limit`, `cost` (default 1), `period_ms`, `burst`, `lease_ms`,
  `floor`, `idle_ttl_ms` and `enforce` take numbers or `"=cel"` (over input, ctx, config, vars,
  self, state), evaluated per decision. `limit: null` is unlimited; `0` admits nothing.
- **`key`** is `"=cel"` (or a literal); the default `""` is one global key. A bare limiter id
  names one of the applying interface's own component; `<component>.<id>` names any.
- **`limits`** on an interface are checked at call entry, after capacity and before the behavior.
  Every limit is decided first; costs are taken only if all admit; the first rejection fails the
  call with its error. A `concurrency` lease taken there is released when the call ends.
  `gate: true` checks without consuming (a bucket admits while tokens > 0).
- **Steps.** `admit` sets `vars.<as>` to `{ok, decision, limiter, key, remaining,
  retry_after_ms, lease, decisions, error}`; a rejection fails the step (`on_error` as for a
  call; `as`/`on_error` go on the admit or on the step). Its lease is held until `release` or
  `lease_ms`, past the behavior's end. `charge` consumes after the fact, down to `floor`, and
  never fails on the limit. `release` frees `lease` (or, without it, the key's oldest); a missing
  lease is a no-op.
- **Full.** `on_limit: reject` (default) fails with `error` (default `{code: rate_limited, status:
  429, retryable: true}`; `message` may be `"=cel"` over `error`). `data` is `{limiter, key, limit,
  remaining, retry_after_ms}`. `on_limit: wait` blocks in virtual time, first come first served
  per key, until the admission passes (a release wakes it), up to `max_wait_ms`, then rejects; the
  trace gets `wait`, then `queue` (`wait_ms`), then the final decision. `enforce: false` admits and
  records `shadow`.
- **State.** CEL `limiters['<component>.<id>']['<key>']` (shared) or
  `limiters['<component>@<instance>.<id>']['<key>']` (instance scope; `<component>.<id>` for a
  component without instances) is `{tokens}`, `{count}` or `{leases, count}`, plus `updated_ms`,
  as of the key's last touch. A restart resets instance-scope limiters; shared ones survive.
- **Seeds.** Fixtures, scenarios and scenario steps take `limiters: {<full id>: {<key>: {tokens,
  count, leases, updated_ms}}}`, e.g. an IP already at its cap:
  `limiters: {gateway.per_ip: {10.0.0.8: {count: 5}}}`. A step's seed applies when it starts.
- **Trace and summary.** Each decision emits a `limit` event (`interface` the applying interface,
  `from` the caller, `key` the full id, `input {key, cost, gate}`, `output {decision, remaining,
  retry_after_ms, limit}`). Decisions: `admit`, `reject`, `wait`, `shadow`, `unlimited`,
  `fail_open`, `fail_closed`, plus `charge` and `release`. A limit that would admit but whose group
  rejected shows `rolled_back: true`. The summary's `limits: {<full id>: {admitted, rejected,
  shadow, waited}}` is also the expectation variable `limits`.
- **Many clients.** A scenario step's `repeat` exposes `pass` (1-based) to its input and to step
  `choices` written as `"=cel"`, so one step stands for many callers:

```yaml
scenarios:
  - id: per-ip-cap
    steps:
      - interface: gateway.get
        caller: client
        repeat: {count: 7}
        input: {x_peer_ip: "= pass <= 6 ? '10.0.0.1' : '10.0.0.2'"}
        choices: {gateway.get.route: "= pass % 2 == 0 ? 'b' : 'a'"}   # optional
        as: burst
    expect:
      - "steps.burst.result.ok"                                       # the 7th, from .2
      - "limits['gateway.per_ip'].rejected == 1"
      - "trace.filter(e, e.type == 'limit' && e.output.decision == 'reject').map(e, e.input.key) == ['10.0.0.1']"
      - "limiters['gateway.per_ip']['10.0.0.1'].count == 5"
```

With `await: false` and `at_ms`, callers overlap in time (concurrency limits, waits).

## 26. Run caps, headers, fault matching, hangs, sessions and retry on status

DESIGN §13.1 item 35.

### Run caps: `max_events` and `max_virtual_ms`

Both are scenario fields, next to `expect`:

```yaml
- id: burst-of-200
  max_events: 200000       # default 20,000; 1 to 1,000,000
  max_virtual_ms: 120000   # stop at 2 virtual minutes, with a warning
  steps: [...]
```

- Past `max_events` the run aborts (`abort: "event budget of N exceeded"`); past
  `max_virtual_ms` it stops with the warning `the run stopped at max_virtual_ms N with work still
  pending`, and tasks cut off end `canceled`.
- Either way the summary gains `caps: {max_events, max_virtual_ms, hit}`, where
  `max_virtual_ms` is null when the run had none and `hit` is `max_events` or `max_virtual_ms`.
- Setting `max_virtual_ms` also makes the run concurrent (§20, DESIGN §13.1 item 14).

### Response headers

A result keeps the `headers` its response declares (in the `response` schema) or its behavior
sets, for id calls and route calls alike:

```yaml
behavior:
  - return: {status: 429, headers: {Retry-After: "30"}}           # a response
  - fail: {code: rate_limited, status: 429, headers: {Retry-After: "30"}}   # or a failure
```

- Keys are read in lower case: `steps.b.result.value.headers['retry-after']` or
  `vars.r.value.headers['retry-after']`. A value keeps the keys the model wrote and gains a
  lower-case alias for each one that isn't lower case.
- A failure's headers are on its error, `error.headers`, and on its value, so
  `result.value.headers['retry-after']` reads a 429's `Retry-After` whether the model returned
  or failed it.
- The trace's `call.end` events carry `headers`, at lower-case keys.
- Validation warns when an expectation reads `result.value.headers[...]` (or `steps.<as>...`,
  `steps[i]...`) for a header the interface's response schema doesn't declare. A `headers`
  object without `properties` declares every header.

### Fault matching: `match` and `caller`

```yaml
faults:
  # Fail only the embeddings request with more than 1,024 items.
  - {target: embeddings.create, type: error, code: too_many_inputs, status: 400, match: "size(input.input) > 1024"}
  # Fail the spend read only when the auto-recharge pass makes it.
  - {target: billing-store.get-spend, type: unavailable, caller: "billing.auto-recharge*"}
```

- `match` is CEL over the call's `input` (with the callee's `state`, `config` and `self`).
- `caller` is an interface id or a glob (`*`, `?`, `[...]`) matched against the calling
  interface. A scenario step's or flow entry's call has no calling interface and matches by
  its caller component (`caller: client`).
- They combine with `instance` and `calls`. With `match` or `caller`, `calls: [2]` means the
  second call **that matches**, not the target's second call.
- A kill fault takes neither.

### Hang without release: `forever: true`

```yaml
faults: [{target: provider.stream, type: hang, forever: true}]
```

- `hang` is `timeout`'s other name; `forever` goes on `hang`, `timeout` or a `lost_reply`
  without `code`.
- The call never answers. It ends only through the caller's `timeout_ms`, a deadline, a
  cancel (a token or a closed session) or a kill of either side.
- A caller with none of these waits until the run ends. It does not hold back the next step.
- The run then reports the call as pending: summary `pending: [{call, from, interface,
  instance, start_ms, fault}]`, a warning, no `call.end` and no synthetic 5xx. A step whose
  call is pending ends with `status: pending` and a result `{ok: false, error: null}`. The run's
  status is `pending` when the entry call is.

### Sessions: `session` and `close`

A call carries a session key while it is in flight. A `close` step cancels every call in flight
with that key, as the death of a tunnel or connection that the peer sees:

```yaml
# node-agent.open-stream
- {call: workload.serve, session: "= input.tunnel_id", as: r, on_error: continue}
# node-agent.tunnel-lost
- close: {session: "= input.tunnel_id"}
```

- `session` and `close.session` are a literal or `"=cel"` (a string or a number).
- The callers get `{code: canceled}` (the same code as a canceled token, item 14) at the close
  time; the callees run on, and their later events are `late`.
- A closed session isn't closed for good: a later call carrying the key runs.
- Each close records a `close` event: `key` is the session, `output.pending` the calls canceled.
- `session` doesn't go with `stream`. Using either makes the run concurrent.

### Retry on status: `on_status` and `on_codes`

```yaml
- call: upstream.chat
  retry: {max_attempts: 4, backoff_ms: 500, on_status: [429, 503, 408]}
```

- A client that retries on given statuses or codes whatever the error's `retryable` flag says
  so with `on_status` or `on_codes`.
- An error is retried when its status is in `on_status`, its code in `on_codes`, or its code in
  `codes`. `when` must still hold. Without them, the old rule applies.
- A timeout has no status: list `timeout` in `on_codes`.

## 27. Route streams, frame headers, retry-after, fault payloads, caps, set steps, JSON and markers

DESIGN §15.3.

### Streams on route calls

A route call may target a yielding interface with `stream: true`, as an id call does (§23):

```yaml
- call: {host: llm.test, method: POST, path: /v1/chat/completions}
  stream: true
  as: r
  on_item:
    - {set: {vars.chunks: "= vars.chunks + [vars.item.data]"}}
```

- Each frame runs `on_item` with `vars.item` and `vars.item_index` at its virtual time; the
  call's result is the callee's return. A `return` or `fail` inside `on_item` ends the call there.
- Redirects, `retry`, `token` and `timeout_ms` work as for any route call; `session` still
  doesn't go with `stream`.
- The trace's `yield` events sit under the route's `call.start` span, so the contract stream
  check reads them as for an id call.

### Nested headers

- A frame that carries `headers` (`yield: {data: a, headers: {Content-Type: text/event-stream}}`)
  keeps them, with a lower-case alias for each key, so `vars.item.headers['content-type']`
  reads it. The `yield` event carries `headers` at lower-case keys.
- A call that doesn't stream gets `{items, value}`; when the return carries `headers`, they are
  also at `result.value.headers`, next to `items`.

### `retry.respect_retry_after: true`

```yaml
retry: {max_attempts: 3, backoff_ms: 100, max_backoff_ms: 5000, respect_retry_after: true}
```

- The next attempt waits for the failure's `headers['retry-after']` (seconds, maybe
  fractional) or else its `data.retry_after_ms`, capped by `max_backoff_ms`. Jitter doesn't
  apply to it.
- A failure with neither (or an HTTP-date `Retry-After`) waits the normal backoff.
- The `retry` event's `backoff_ms` is the wait taken.

### Removing fields in a store `update`

```yaml
store: {table: vms, op: update, key: "= input.id", value: {lease: {$absent: true}, meta: {lock: {$absent: true}}}}
```

`{$absent: true}` as a value, at any depth, removes that field from the row. Other fields merge
as before.

### Fault payloads: `data` and `headers`

```yaml
faults: [{target: upstream.chat, type: error, code: rate_limited, status: 429, retryable: true,
          headers: {Retry-After: "2"}, data: {retry_after_ms: 2000}}]
```

- They appear on `error.data` and `error.headers` (lower-case keys, and so on
  `result.value.headers`) for `unavailable`, `error`, `crash` and a `lost_reply` with `code`.
- A `timeout`/`hang` fault's error is made by the caller giving up, so it carries neither.

### Per-scenario caps: `max_iterations` and `max_cel_cost`

```yaml
- id: decode-800-steps
  max_iterations: 200000   # foreach iterations in the whole run; default 10,000, up to 1,000,000
  max_cel_cost: 50000000   # cost_limit's other name; default 10,000,000
```

- Past `max_iterations` the run aborts (`loop budget of N iterations exceeded at <path>`). Each
  `foreach` still stops at its own `max` (default 100, up to 1,000), so a decode loop of S steps
  over a batch of B requests needs S×B under `max_iterations`.
- Give `max_cel_cost` or `cost_limit`, not both with different values.

### External state mid-run: `set` steps

```yaml
steps:
  - {flow: wait-for-node, as: w, await: false}
  - {set: {"nodes@n2": {status: ready, "allocs.job-1": {state: running}}}, at_ms: 5000}
```

- Keys are `<component>` or `<component>@<instance>` (the instance may be `"=cel"`); paths are
  dotted, inside that state; values are templates that see `steps`.
- It's a control step, like `cancel` or `kill`: it names no flow or interface, and makes the run
  concurrent. With `at_ms` it lands while earlier steps still run: a node coming back, or a job
  placed by an outside scheduler. Each path records a `set` event.

### CEL helpers: `json`, `jsonParse`, `bytes` and `hex`

- `json(x)` encodes canonically: sorted keys, no spaces, no HTML escaping
  (`json({'b': 1, 'a': 2}) == '{"a":2,"b":1}'`).
- `jsonParse(s)` decodes a string or bytes; whole numbers are ints. Trailing data is an error.
- `bytes(s)` is CEL's conversion; `hex(b)` is the lower-case hex of bytes or of a string's
  UTF-8 bytes (`hex(bytes('hi')) == '6869'`).
- All are pure, so `eval(expr, vars)` gets them too.

### Input markers: `{$bytes}` and `{$bigint}`

In a scenario, step, entry or request input, like `{$absent}`:

```yaml
input: {blob: {$bytes: "/wA="}, id: {$bigint: "123456789012345678901234567890"}}
```

- `{$bytes: "<base64>"}` gives raw bytes, invalid UTF-8 included: CEL sees `bytes`
  (`size(input.blob) == 2`, `hex(input.blob) == 'ff00'`), and a `string` schema accepts it.
- `{$bigint: "<decimal>"}` gives an integer beyond int64. CEL sees its decimal string; an
  `integer` schema accepts it; JSON writes the marker back.

## 28. Cancel time and stream flow control

DESIGN §16.4.

### Cancel time

A call canceled by its `token` or by a session `close` keeps the cancel's time:

- The callee's handler, which runs on after the cancel (its later events `late`), reads
  `ctx.cancelled_at_ms`. It is absent until the cancel, so guard it with `has(...)`.
- The caller reads `vars.<as>.cancelled_at_ms`. A call bound to a token already canceled gets the
  token's cancel time.
- Both are clock readings like `now`. The mark is the canceled call's handler's own (its
  `parallel` branches included), not that of the calls the handler makes.

A hang-up billing rule bills up to the hang-up, not up to the frame where the handler notices it:

```yaml
- component: llm
  name: generate
  behavior:
    - {set: {vars.start: "= now"}}
    - foreach: "= input.tokens"
      steps:
        - {wait: 100}
        - if: "has(ctx.cancelled_at_ms)"           # noticed at the next frame
          then:
            - {set: {state.billed_ms: "= ctx.cancelled_at_ms - vars.start"}}   # billed from the cancel
            - {return: {billed: "= state.billed_ms"}}
        - {yield: "= vars.item"}
```

### Stream flow control

A streaming call may bound its frames in flight:

```yaml
- call: model.generate
  stream: true
  window: 4          # frames in flight before the producer's yield blocks
  stall_ms: 500      # the longest the producer may stay blocked
  as: gen
  on_error: [{return: {error: "= error.code"}}]     # stream_stalled
  on_item: [{call: browser.sse, input: {chunk: "= vars.item"}}]
```

- **In flight** means yielded but not yet handled: queued for the caller, or the frame whose
  `on_item` steps are running. A yield that finds `window` in flight blocks until the caller
  finishes one.
- **A stall.** A producer blocked for `stall_ms` fails the stream with `{code: stream_stalled,
  data: {window, stall_ms, index}}`, where `index` is the frame it couldn't send:
  - its `yield` fails, which ends its behavior like any failed step;
  - a `stall` trace event records it (`wait_ms`, `index`, `error`);
  - the caller first handles the frames already in flight, then gets the error as the call's
    result (`on_error` applies).
- **A caller that stops reading** releases blocked producers: an exit or error in `on_item`, a
  cancel, or a kill. Their later frames go nowhere.
- **Validation.** Both take a number or `"= cel"`, and go only with `stream: true`. `window` is
  a whole number of at least 1. `stall_ms` must be positive and needs a `window`. Without a
  window, a producer never blocks.

## What the summary adds

`calls_by_instance`; `steps` (multi-step results); `queued` (queue waits); `mocks` (mocked
calls); and `executed`, the sorted set of behavior step paths that ran
(`storage-proxy.mutate:behavior[3].then[0]`), which the check tool's `--behavior-coverage` unions
across scenarios. The trace gains `queue` events (a capacity wait), marks mocked calls `mock`, and carries
`instance` on events and `late` on events after a join or timeout. §23 adds `yield`, `put`,
`receive` and `kill` events. §25 adds `limit` events and the summary's `limits`. §26 adds `close`
events, `headers` on `call.end`, and the summary's `caps` and `pending`. §27 adds `headers` on `yield`
events and `set` events from scenario `set` steps.

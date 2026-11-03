---
name: mosaic-simulation
description: Write mosaic behaviors and scenarios, then run and debug simulations with `mosaic plan`, `mosaic sim run` and `mosaic test`. Use this whenever the user wants to simulate a flow through a mosaic ontology; model retries, timeouts, fallbacks, refusals, queues or fault injection; model concurrent fan-out (quorum, hedging, all-reduce), instances, deadlines, timers, capacity or publish/subscribe; add or fix scenarios and expectations; or explain a run's summary or trace, including aborted runs, failed assertions and warnings. It also applies to questions like "what happens if Redis is down", "does the retry go to the other backend" or "turn these outcomes into acceptance tests" against a mosaic model. Pair it with mosaic-ontology for creating and versioning the ontology itself.
---

# Mosaic simulation

Mosaic runs a flow's entry call through component **behaviors** on a deterministic virtual clock.
Fake data comes from schemas. Choices, state, faults, retries and timeouts decide the path, and
**scenarios** turn each outcome into an executable acceptance test. The same revision, scenario
and seed always produce the same trace, so a failing run is reproducible.

## Workflow

1. **Survey the controls.** `mosaic plan <ont> <flow>` lists the reachable interfaces, the choice
   points (keys, options and defaults), the stateful components with their initial state, the
   valid fault targets and the existing scenarios. Read it before writing scenarios, so you never
   guess a key.
2. **Write or adjust behaviors** on interfaces. Leave interfaces whose internals don't matter as
   stubs (no `behavior`); they return fake data from their `response` schema.
3. **Explore** with ad hoc runs: `mosaic sim run <ont> --flow F --format summary`, adding
   `--choice`, `--state`, `--fault`, `--input` and `--expect` until each outcome happens for the
   right reason. Use `--no-save` for throwaway runs.
4. **Capture each outcome as a scenario** with `expect` (see below), then run
   `mosaic test <ont>`. Every scenario should pass **with no warnings**.
5. Cut a revision (mosaic-ontology) once the tests pass.

## Behavior language in brief

A behavior is a list of steps. Each step has at most **one action** (`set`, `call`, `if`,
`choice`, `return`, `fail`, `emit`, `wait`, `foreach`, `break` or `continue`), plus optional narrative `title`, `detail` and
`source` (a `note` in the trace) and a `when: <cel>` guard. **Templates**: a string starting with
`=` is CEL, and anything else is literal. `if`, `when`, retry `when` and `expect` are always CEL.
CEL sees `input`, `state` (this component's), `ctx` (shared by the run), `vars` (local), `attempt`,
`now` and `error`.

The rules that most often trip agents:

- **`error` is sticky.** It is the most recent failed call in this behavior. A later successful
  call doesn't clear it, and it is `null` until something fails. Inside `on_error` it is the error
  being handled; in `retry.when` it is the attempt that just failed. Test a specific call with
  `vars.x.ok` (from `as: x`) instead of `error == null`.
- **`set` is a parallel assignment.** All right-hand sides are evaluated first, then assigned in
  sorted path order, so `{vars.a: "= vars.b", vars.b: "= vars.a"}` swaps. Paths start with
  `vars.`, `ctx.` or `state.`.
- **The default `on_error` is `propagate`**: the caller fails with the callee's exact error.
  `continue` carries on (check `vars.x.ok`). A list of steps runs a handler; unless it ends in
  `return` or `fail`, execution continues after the call.
- **Retry needs `max_attempts`** (1 to 20, or `"=cel"`). Without `codes`, only errors with
  `retryable: true` are retried, and `error` faults default to `retryable: false`. Use `codes`,
  never `on:`, which YAML turns into `true`. A client that retries on statuses or codes whatever
  `retryable` says uses `retry: {on_status: [429, 503, 408]}` or `on_codes: [...]`. For
  AWS-style jitter set `retry.jitter: full` (each wait uniform in [0, backoff]) or `equal`
  (backoff/2 plus uniform [0, backoff/2]); draws use the run's seed, and the `retry` event's
  `backoff_ms` is the drawn wait. The default `none` waits the computed backoff.
- **Run caps are per scenario, not fixed.** `max_events: N` (default 20,000, up to 1,000,000)
  and `max_virtual_ms: N` go on the scenario. Raise them for a load test instead of shrinking
  it; the summary's `caps` says which one ended a run.
- **To leave a request field out, write `{$absent: true}`**, since fake data fills every
  declared field (`{$null: true}` sends a JSON null). See "Scenarios and expectations".
- **Fault kinds:**
  - `unavailable`, `error` (`code`, `status`), `latency` and `timeout`;
  - `lost_reply`: the callee's write lands, and the answer is lost;
  - `crash` with `after_steps`: the callee stops partway, its effects so far kept;
  - `hang` with `forever: true`: it never answers.

  A `kill` fault, or a `kill` / `restart` / `cancel` step, stops a process. Target a fault with
  `instance`, `calls`, `match` (CEL over the input) or `caller`. Ask whether one of these
  expresses a failure before calling it a simulator gap.
- **Dynamic calls** (`call: "= ..."`) re-evaluate the target and input on every attempt, so a
  retry can go to the next replica. Always list `targets` so plans and graphs can follow them.
- **`emit` is fire-and-forget**: it is delivered after the whole entry call finishes, even if the
  entry call failed, and its outcome never changes `result`.
- **Ending without `return` or `fail`** returns fake data from the `response` schema (or null).
- **Datastores hold rows** when their interfaces declare `store: {table, op, key, value, where}`
  instead of a behavior: a `put` in one call is read back by a later `get`. Seed rows through
  `state: {<component>: {<table>: {<id>: row}}}`.
- **`foreach`** loops are bounded (`max`, default 100) and sequential; reconcilers and crons use
  `entry.repeat: {count, interval_ms}` on the flow, and expectations read `passes[i].result`.

The full semantics of every step, call option and CEL variable are in
[references/behavior-language.md](references/behavior-language.md).

## Systems with many parts

> Requires mosaic with DESIGN §11 (in progress).

- **Instances**: copies of the same code (nodes, windows, GPU ranks) come from a fixture's
  `topology`. `self` is the current instance; `on:` on `call`, `emit` or `publish` picks the
  callee's. State is per instance (`state['gossiper@n2']`). Never put `to` addresses in requests.
- **`parallel` with `join: {need: all | k | any}`** for concurrent fan-out: quorum (k of n),
  hedging (`stagger_ms`, need 1), all-reduce (all). Not a sequential `foreach`.
- **Time**: `now` starts at the fixture's `clock` epoch; `deadline_ms` on an entry, step or call
  is a budget every nested hop shares; timers are `after_ms` or `every_ms` + `count` on `emit` and
  `publish`. Durations and `join.need` take `"=cel"`, so read them from config:
  `timeout_ms: "= config['write-request-timeout-ms']"`.
- **`capacity: {concurrency}`** on a component queues calls past N (pools, stages, a single JS
  thread, batch slots); overflow fails `overloaded`.
- **Limiters** (`limiters:` on a component; `limits:` on an interface; `admit`, `charge`,
  `release` steps) model rate limits and back pressure: token buckets, fixed and sliding
  windows, concurrency leases, keyed by any CEL (`key: "= input.x_peer_ip"`), per instance or
  `shared`, with `on_limit: wait`, shadow mode and backend calls. Assert `limits['<comp>.<id>']`
  counts and `limiters[...]` state; a repeated step's input reads `pass`. Not `state` counters.
- **`publish`/`subscribe`** for listeners, `delivery: sync` for inline emitters.
- **`config['<id>']`** reads deployed values; `latency_ms: "=cel"` computes service time.
- **Multi-step scenarios** (`steps: [{flow, input, on, at_ms, await, as}]`) share one world; a
  step starts after the previous one's emits and timers finish, and overlaps only with `at_ms` or
  `await: false`; assert `steps.<as>.result`. A flow tagged `writes` needs one that reads its effect back.
- **Expectations also see** `config`, `topology`, `calls_by_instance`, `steps` and `trace`:
  assert which instance got which call, in what order. (`self` and `deadline` are behavior-only.)
- **Runs** take `fixtures`, `topology`, `config` and `clock` (`mosaic sim run --fixture ID
  --topology comp=a,b,c --config id=value --clock-epoch TIME`, `POST /simulations`).
- **Mocks** are a last resort for isolating one fragment; generated models forbid them.
- **CEL helpers**: `transformMap`/`transformList`, `sum`, `merge`, `omit`, seeded `random(n)`,
  hashes and bytes, and IP/CIDR: `ip(s)`, `inCidr(ip, cidr)`, `inAnyCidr(ip, [cidrs])`,
  `ipFamily`, `ipIsLoopback`/`Private`/`LinkLocal`/`Multicast`/`Unspecified`.
- **Response headers**: `return`/`fail` with `headers: {...}`; read
  `steps.<as>.result.value.headers['retry-after']` (lower case); `call.end` carries `headers`.
- **Fault `match: "<cel over input>"` and `caller: <interface id or glob>`** fail only some calls
  of a target (the 1,025-item request, the read from the recharge pass).
- **`hang` with `forever: true`** never answers: only `timeout_ms`, a deadline, a cancel or a kill
  ends the call; otherwise it is reported `pending` at the end of the run.
- **Sessions**: `session: <key>` on a call, and a `close: {session: <key>}` step cancels the calls
  in flight carrying it (`{code: canceled}`), like a dropped tunnel.
- **Route streams**: a route call takes `stream: true` and `on_item`, as an id call does.
- **Cancel time**: a canceled call's handler reads `ctx.cancelled_at_ms`, and the caller `vars.<as>.cancelled_at_ms`, so a hang-up bills from the cancel (`references/behavior-language.md` §28).
- **Stream flow control**: `window: N` and `stall_ms` on a `stream: true` call; a producer blocked past `stall_ms` fails the stream with `{code: stream_stalled}` (§28).
- **Frame headers**: a yielded frame's `headers` read as `vars.item.headers['content-type']`; a collected stream's return headers are at `result.value.headers`.
- **`retry.respect_retry_after: true`** waits for the error's `retry-after` header or `data.retry_after_ms`, capped by `max_backoff_ms`.
- **Store `update` value `{$absent: true}`** removes that field from the row.
- **Faults take `data` and `headers`**, which land on `error.data` and `error.headers`.
- **`max_iterations`** (the run's foreach total, default 10,000, up to 1,000,000) and **`max_cel_cost`** go on the scenario; raise them for long decode loops.
- **A `set: {"<comp>[@inst]": {<path>: value}}` step with `at_ms`** changes state mid-run (a node returns, a scheduler places a job).
- **CEL `json(x)`** (canonical), **`jsonParse(s)`**, **`bytes(s)`** and **`hex(b)`**.
- **`streams_when: "= input.stream == true"`** on an interface that yields: a plain call (false) returns the bare value instead of `{items, value}`; a yield on it aborts (§23).
- **CEL `list.indexOf(x)` / `list.lastIndexOf(x)`**: an int, -1 when absent (§22).
- **Input markers `{$bytes: "<base64>"}`** (raw bytes) and **`{$bigint: "<decimal>"}`** (beyond int64).

Semantics: [references/behavior-language.md](references/behavior-language.md) §13–27 (§26:
run caps, headers, fault matching, hangs, sessions and retry on status; §27: the §15.3 items above). Recipes
from a distributed database, a front-end editor and a GPU serving engine:
[references/recipes.md](references/recipes.md) §15–24.

## Scenarios and expectations

```yaml
- id: retry-before-commit
  flow: chat-stream
  name: First upstream fails before commitment
  faults:
    - {target: upstream-a.chat, type: error, code: upstream_error, status: 502, retryable: true, calls: [1]}
  expect:
    - "result.ok && retries == 1"
    - "calls['upstream-a.chat'] == 1 && calls['upstream-b.chat'] == 1"
    - "ctx.upstreamDials == 2 && ctx.firstAttempt == 'failed before commitment'"
```

Drive each branch with the mechanism that matches reality. Use **input** for request data
(an invalid key or an oversized prompt), **state** for stored data (a low balance, a full pool),
**choices** for decisions the model doesn't compute (a policy verdict, a stream that breaks), and
**faults** for infrastructure failure (a store down, an upstream erroring or hanging).

Fake data fills every declared request field, optional and required ones alike. To send a
request **without** a field, write `{$absent: true}` for it in a scenario, step or entry input, at
any depth: `input: {body: {endpoint: {$absent: true}}}`. This also removes a key that a `flow:`
step would otherwise inherit from the flow's default input. `{$null: true}` sends a real JSON null.

Expectations are CEL over: `result` (`{ok, value, error}`, where `error` is
`{code, message, status, retryable, data}` or null), `status` (`ok`, `error`, `aborted` or `pending`), `calls`
(every interface id mapped to a count, 0 if never called), `ctx`, `state` (keyed by component),
`retries`, `faults` (fault hits), `duration_ms`, `warnings` (a list of strings) and `passes`
(`[{pass, result, start_ms, duration_ms}]`, one entry per pass of a repeated entry). `vars` is
**not** available, so copy what you want to assert into `ctx`. Use brackets for hyphenated keys:
`calls['upstream-a.chat']`, `state['pool-admission'].held`. Guard error access with
`!result.ok && result.error.code == '...'`. Assert the **cause** as well as the outcome: for
example, that downstream calls didn't happen (`calls['throttle.check'] == 0`), that state was
restored, or how many retries ran.

### Black-box assertions and stable ids

Prefer `io`, `result` and `steps` over assertions on internal interfaces or internal state.
They survive internal renames; `trace`, `calls['<internal>.x']` and `state.<internal>` don't.
`io` is the boundary view of a run, one item per entry call, per call into a component of kind
`external` or with `attributes.boundary`, and per route call:
`{seq, t, dir: in|out, kind: entry|external|route, interface, component, instance, input,
output: {ok, value, error}, headers, duration_ms}`. For example:
`io.exists(i, i.kind == 'external' && i.interface == 'stripe.charge' && i.input.amount == 42)`.
Store state is fine to assert on. `check --lint internal-assertions` reports the share of
expectations that reach inside, and `--max-internal-assertions R` gates it.

Mint ids with `id(prefix, key...)`, never from `now`. It returns a UUID-shaped id that depends
only on the run seed, the prefix and the keys, so expectations can recompute it
(`result.value.order_id == id('order', 's1')`) and it doesn't move when timing changes. For ids
that must differ on each call, add a counter: `id('req', seq('req'))`, where `seq(name)` counts
1, 2, 3… per run. `check --lint clock-ids` flags ids built from `now`, such as
`'req-' + string(now)`.

### Race scenarios: invariants and schedule exploration

`check --explore '<regex>' --schedules N [--jitter-ms M]` reruns matching scenarios under other
schedules: other orders of same-time tasks and deliveries, of `parallel` branches and joins, and
jittered `at_ms`. Under every schedule it checks the scenario's **`invariants: [<cel>]`**, which
see the same final `state`, `trace`, `io`, `calls` and `steps` as `expect`. When a scenario has
invariants, its `expect` is checked **only on the default schedule**. Without invariants, `expect`
is checked under every schedule.

So write a race as two claims:
- **Exactly one wins** is an invariant. It must hold whatever the order.
- **Which one wins** is an `expect`. It holds only for the default order.

```yaml
- id: race-two-acquirers
  steps:
    - {interface: worker.run, caller: user, input: {owner: a}, at_ms: 0, as: a}
    - {interface: worker.run, caller: user, input: {owner: b}, at_ms: 0, as: b}
  invariants:
    - "exactlyOne([steps.a.result.ok, steps.b.result.ok])"
    - "state.lock.leases.job.owner == (steps.a.result.ok ? 'a' : 'b')"
  expect: ["steps.a.result.ok"]       # the default tie-break lets a in first
```

Counting helpers, each in three forms: `exactlyOne(list, x, pred)`, `exactlyOne(list, pred)`
(the element is `it`) and `exactlyOne(boolList)`. `atMostOne` and `atLeastOne` work the same
way. Example: `atMostOne(io, it.interface == 'stripe.charge' && it.output.ok)`.

A failing schedule is written to `.mosaic/replay/<scenario>.replay.json`, and `--replay <file>`
reruns it. Each search also prints its coverage: the choice points seen, and how many
alternatives were tried, pruned as equivalent, or left untried once the budget ran out. Many
untried alternatives mean you should raise `--schedules`. A pruned alternative only reordered
work on disjoint components, keys or ctx, or reads of keys that no other task writes.

## Reading results

`sim run --format summary` gives the outcome, the assertions and one line per call. The JSON
`summary` has `status`, `result`, `duration_ms`, `calls`, `retries`, `faults`, `ctx`, `state`,
`initial_state`, `assertions`, `passed`, `warnings`, `seed` and `abort`. Use `--format trace`, or
`mosaic sim get <run-id> --format trace`, to follow the events.

- **`status: aborted`**: the run hit a budget or a runtime CEL error. `abort` names the exact
  step, for example `db.read.behavior[0].set.ctx.shard: input.shard: no such key: shard`. No
  expectations are evaluated, and the scenario fails. `event budget of 20000 exceeded` in a
  finite run means: set `max_events` on the scenario (`caps` reports both caps).
- **`status: pending`** / `pending: [...]`: a `hang` with `forever: true` never answered.
- **Warnings**: an input or return that doesn't match its schema, a call to an unknown interface,
  a `foreach` that hit its `max`, or a scenario choice naming a missing option (a run's own
  `--choice` with an unknown key or option is refused before the run starts). Fix them; they usually point at a real modeling bug.
- **`passed: true` with `status: error`** is normal for refusal scenarios. `passed` is about the
  expectations, not success.

More on traces, event fields and a debugging checklist:
[references/reading-results.md](references/reading-results.md).

## References

- [references/behavior-language.md](references/behavior-language.md): every step type, call
  option, retry rule, timeout and fault semantics, CEL variables and functions, and execution order.
- [references/recipes.md](references/recipes.md): proven patterns, including auth and refusal
  gates, retry before commit, fallback on outage, timeouts, async metering, and state-, choice- and
  fault-driven branches; then quorum, hedging, all-reduce, deadlines, timers, capacity,
  publish/subscribe, write-then-read and trace assertions (§15–24, DESIGN §11).
- [references/reading-results.md](references/reading-results.md): the summary, trace events,
  test reports and debugging.
- [references/minimal-example.yaml](references/minimal-example.yaml): a complete, verified
  5-component ontology (stub, retry with backoff and timeout, choice, state refusal, on_error
  cleanup, emit, and 6 passing scenarios). Copy it as a starting point.
- CLI flags: see mosaic-ontology's `references/cli.md`, section "Simulation and tests".

# Modeling recipes

These are proven patterns. The worked example to read alongside them is the Envoy proxy model,
`examples/envoy/ontology.yaml`, whose 22 scenarios pass with no warnings: its router retries
through `retry.when`, its local rate limit is a limiter, and its hosts are instances. Unless
marked otherwise, the snippets below come from a model of an LLM inference gateway; its
test-fixture form, with shorter names, is `internal/testdata/gateway/ontology.yaml`. Snippets
marked *(verified)* were checked against the engine separately. Each recipe gives the behavior,
then the scenario that exercises it.

## Contents

1. [Choosing the branch mechanism](#1-choosing-the-branch-mechanism)
2. [Auth and refusal gates](#2-auth-and-refusal-gates)
3. [Fail-closed dependency](#3-fail-closed-dependency)
4. [Retry before commit, over dynamic targets](#4-retry-before-commit-over-dynamic-targets)
5. [Fallback on dependency outage](#5-fallback-on-dependency-outage)
6. [Timeouts](#6-timeouts)
7. [Cleanup on failure](#7-cleanup-on-failure)
8. [Failure after commit](#8-failure-after-commit)
9. [Async metering and queues](#9-async-metering-and-queues)
10. [Retry only some failures](#10-retry-only-some-failures)
11. [Recording facts for expectations](#11-recording-facts-for-expectations)
12. [A datastore that remembers](#12-a-datastore-that-remembers)
13. [Fan-out and sweeps](#13-fan-out-and-sweeps)
14. [Reconciler converging over ticks](#14-reconciler-converging-over-ticks)

For systems with many parts (requires DESIGN §11, in progress): sections 15 to 24 below cover
parallel/join (quorum, hedging, all-reduce), deadlines, timers, capacity, publish/subscribe,
multi-step scenarios and trace assertions, with examples from a distributed database, a front-end
editor and a GPU serving engine. Sections 25 to 27 cover streamed responses, busy loops on
channels and killed instances (DESIGN §13.1 item 18).

## 1. Choosing the branch mechanism

| The branch depends on... | Model it with | Scenario lever |
|---|---|---|
| request data (a bad key, an oversized prompt, a missing field) | `if` on `input` | `input:` |
| stored data (a balance, a budget, capacity, a catalog row) | `if` on `state` with seeded `state.initial` | `state:` |
| a decision computed outside the model (a policy engine, an ML verdict, a client disconnect) | `choice` | `choices:` |
| infrastructure failing (a store down, errors, hangs, slowness) | nothing in the behavior: handle the error with `retry`/`on_error` | `faults:` |
| state by default, but sometimes forced | `choice` with `default: "= cel"` | `state:` or `choices:` |

Prefer the mechanism that matches the real cause. A balance check written as a `choice` hides the
threshold the code enforces; a datastore outage written as a `choice` never exercises the
caller's error handling.

## 2. Auth and refusal gates

The input is checked against seeded state; the gate succeeds with a value or fails with the real
error code. Upstream gates fail fast, so later stages are never called.

```yaml
- component: authentication
  name: authenticate
  request: {type: object, required: [api_key], properties: {api_key: {type: string}}}
  response: Principal
  errors: [{code: authentication_failure, status: 401}]
  behavior:
    - if: "input.api_key in state.keys"
      then:
        - set: {ctx.credential: valid}
        - return: "= state.keys[input.api_key]"
    - set: {ctx.credential: invalid, ctx.httpStatus: 401, ctx.phase: refused, ctx.upstreamDials: 0}
    - title: Request refused
      source: gateway/auth.go
      fail: {code: authentication_failure, status: 401, message: invalid API key}
```

The happy path works because the entry schema's `api_key` has `examples: [key_demo]`, which
matches `state.keys.key_demo`. The caller uses the default `on_error: propagate`, so the 401
becomes the request's result. A choice-driven gate (rate limit, policy) looks the same, with
`choice: rate_limit`, `default: allowed` and an `exceeded` option that fails.

```yaml
- id: invalid-api-key
  flow: chat-stream
  input: {api_key: key_unknown}
  expect:
    - "!result.ok && result.error.status == 401 && result.error.code == 'authentication_failure'"
    - "calls['throttle.check'] == 0 && ctx.upstreamDials == 0"
- id: rate-limited
  flow: chat-stream
  choices: {throttle.check.rate_limit: exceeded}
  expect: ["result.error.status == 429 && calls['account-admission.require-balance'] == 0"]
```

## 3. Fail-closed dependency

The gate refuses with its own error when its store fails, instead of passing the store's error up.

```yaml
- call: admission-store.read-account
  input: {org_id: "= input.org_id"}
  as: account
  on_error:
    - set: {ctx.httpStatus: 500, ctx.errorCode: internal, ctx.phase: refused}
    - title: Request refused
      detail: The account-admission store failed. requireBalance refuses with 500; it does not fail open.
      source: gateway/admission.go:118
      fail: {code: internal, status: 500, message: account admission store failed}
- if: "vars.account.value.available_cents < state.balance_floor_cents"
  then:
    - fail: {code: insufficient_balance, status: 402}
```

```yaml
- id: admission-store-unavailable
  flow: chat-stream
  faults: [{target: admission-store, type: unavailable}]
  expect: ["result.error.status == 500 && calls['request-parser.parse'] == 0 && faults == 1"]
- id: below-balance-floor
  flow: chat-stream
  state: {admission-store: {accounts: {org_demo: {available_cents: 20, standing: eligible}}}}
  expect: ["result.error.code == 'insufficient_balance' && ctx.availableCents == 20"]
```

## 4. Retry before commit, over dynamic targets

The target is computed per attempt, so each retry dials the next member of the plan. `when` stops
retries once the response has committed.

```yaml
- call: "= input.targets[attempt - 1] + '.chat'"
  targets: [upstream-a.chat, upstream-b.chat]
  input: {model: "= input.backend_ref", messages: "= input.body.messages", stream: true}
  timeout_ms: 30000
  retry:
    max_attempts: "= size(input.targets)"
    codes: [upstream_error, unavailable, timeout]
    when: "!ctx.committed"
    title: First member fails before commitment
    source: gateway/completions.go:545
  as: response
- set: {ctx.upstreamDials: "= vars.response.attempts"}
- return: "= vars.response.value"
```

`max_attempts: "= size(input.targets)"` keeps `targets[attempt - 1]` in range. `codes` makes
retries independent of each fault's `retryable`.

```yaml
- id: retry-before-commit
  flow: chat-stream
  faults: [{target: upstream-a.chat, type: error, code: upstream_error, status: 502, retryable: true, calls: [1]}]
  expect:
    - "result.ok && retries == 1 && calls['upstream-a.chat'] == 1 && calls['upstream-b.chat'] == 1"
- id: all-members-fail
  flow: chat-stream
  faults:
    - {target: upstream-a, type: error, code: upstream_error, status: 502, retryable: true}
    - {target: upstream-b, type: error, code: upstream_error, status: 502, retryable: true}
  expect: ["result.error.code == 'upstream_error' && retries == 1"]
```

For a fixed target with backoff (verified, from minimal-example.yaml):
`retry: {max_attempts: 3, backoff_ms: 100, multiplier: 2, codes: [gateway_error, unavailable, timeout]}`
waits 100 ms and then 200 ms.

## 5. Fallback on dependency outage

Use `on_error: continue`, then branch on `vars.x.ok`. Don't test `error`, because it stays set
after later successful calls.

```yaml
- call: redis-ledger.acquire
  input: {pool: "= input.pool"}
  as: ledger
  on_error: continue
- if: "vars.ledger.ok"
  then:
    - title: Acquire a concurrency slot
      set: {ctx.admissionMode: shared fleet, vars.granted: "= vars.ledger.value.granted"}
  else:
    - title: Acquire a concurrency slot
      detail: Redis cannot supply the exact fleet counter. Online requests fall back to a per-task local cap.
      source: gateway/pools.go:484
      set: {ctx.admissionMode: degraded local, vars.granted: "= state.local_free_slots > 0"}
```

```yaml
- id: redis-unavailable-local-fallback
  flow: chat-stream
  name: "Redis unavailable: local fallback"
  faults: [{target: redis-ledger, type: unavailable}]
  expect: ["result.ok && ctx.admissionMode == 'degraded local'"]
```

A guarded fallback call *(verified)*. It skips the database when the cache answered, and reads it
when the cache missed, failed or was too slow:

```yaml
- call: cache.read
  input: {id: "= input.id"}
  timeout_ms: 50
  as: cached
  on_error: continue
- when: "!vars.cached.ok"
  title: Cache miss or slow, read the database
  call: db.read
  input: {id: "= input.id"}
  as: row
```

## 6. Timeouts

Set `timeout_ms` on the caller's call step; it is the caller's patience, not the callee's speed.

- A **hang**: `{target: upstream-a.chat, type: timeout}`. The callee never answers, and the caller
  gets `timeout` at start + `timeout_ms` (30000 ms if unset). The timeout is retryable, so include
  `timeout` in `codes` to retry it.
- **Slowness** *(verified)*: `{target: cache, type: latency, latency_ms: 100}` with
  `timeout_ms: 50`. The callee finishes (its state changes stand, and its `call.end` has
  `late: true`), but the caller already saw `timeout`. This is how you model double-execution
  risk.

```yaml
- id: upstream-timeout-retry
  flow: chat-stream
  faults: [{target: upstream-a.chat, type: timeout}]
  expect: ["result.ok && retries == 1 && calls['upstream-b.chat'] == 1", "duration_ms >= 30000"]
```

Use `calls: [1]` to make only the first invocation hang, which is the usual "transient" case.

## 7. Cleanup on failure

Give `on_error` a list of steps that undoes earlier work, then fails with the caller's own error.

```yaml
- call: upstream-dispatch.dispatch
  input: {targets: "= vars.plan.value.targets", body: "= input"}
  as: upstream
  on_error:
    - call: pool-admission.release
    - set: {ctx.httpStatus: 502, ctx.errorCode: upstream_error, ctx.phase: failed}
    - fail: {code: upstream_error, status: 502, message: "= 'no pool member answered: ' + error.code"}
```

The nested `release` call succeeds, but `error` is still the dispatch error. Assert that the
cleanup happened: `"state['pool-admission'].held == 0 && state['redis-ledger'].free_slots == 3"`.

## 8. Failure after commit

Once a response is committed it must not be retried. Set a commit flag that retry `when`
conditions read, and model the post-commit failure as a choice whose handler returns a partial
result.

```yaml
# response-relay.deliver
- set: {ctx.committed: true, ctx.httpStatus: 200, ctx.phase: streaming}
- choice: stream
  default: completes
  options:
    completes:
      - wait: "= input.response.tokens_out / 10"
      - return: {delivered: true, tokens_out: "= input.response.tokens_out"}
    breaks:
      - wait: 15
      - fail: {code: stream_interrupted, status: 200, message: the upstream stream failed after the response committed}
# caller
- call: response-relay.deliver
  input: {response: "= vars.upstream.value"}
  on_error:
    - set: {ctx.phase: stream interrupted, ctx.usageAccepted: false, ctx.retryAllowed: false}
    - call: pool-admission.release
    - return: {id: "= vars.upstream.value.id", model: "= input.model", status: interrupted, partial: true, tokens_out: 0}
```

Scenario: `choices: {response-relay.deliver.stream: breaks}`, with expectations
`result.ok && result.value.partial == true`, `retries == 0`, `calls['usage-relay.rate'] == 0`.

## 9. Async metering and queues

Use `emit` for work that happens off the request path. It is delivered after the entry call
finishes, and its outcome never changes `result`.

```yaml
- emit: metering.record
  input:
    org_id: "= vars.principal.value.org_id"
    tokens_out: "= vars.upstream.value.tokens_out"
    cost_cents: "= vars.usage.value.cost_cents"
# metering.record (kind: queue)
- title: Enqueue aggregate usage
  source: gateway/completions.go:480
  set: {ctx.metering: queued, state.records: "= state.records + 1"}
```

Assert the delivery through its effects: `state['metering'].records == 1`. Place the `emit` where
the code enqueues, usually after the commit point. An emit that runs before a failure is still
delivered, just like a message the real code already sent. To model a consumer that fails, fault
the queue interface; the request still succeeds.

## 10. Retry only some failures

*(verified)* Retry server errors but not client errors, with capped exponential backoff:

```yaml
retry: {max_attempts: 4, backoff_ms: 100, multiplier: 3, max_backoff_ms: 250, when: "error.status >= 500"}
```

Without `codes`, the error must also be `retryable`, so fault it with `retryable: true`. Faults can
script a sequence: `{target: db, type: error, code: db_error, status: 500, retryable: true, calls: [1, 2]}`
followed by `{target: db, type: error, code: bad_query, status: 400}`. The first fault in list
order that matches wins, so attempts 1 and 2 retry (backoff 100 ms, then 250 ms) and attempt 3
stops.

## 11. Recording facts for expectations

Expectations can't see `vars`, and `result` only shows the entry call. Write the facts you want to
assert into `ctx` as the behavior runs (`ctx.phase`, `ctx.httpStatus`, `ctx.upstreamDials`,
`ctx.admissionMode`). Every scenario can then assert *why* it ended where it did, not only that it
did. Keep the ctx keys consistent across components, so each refusal sets the same
`ctx.httpStatus`/`ctx.errorCode`/`ctx.phase` trio.

## 12. A datastore that remembers

*(verified)* Shared datastore stubs return fake rows. Give them `store` so a create is visible to
a later read, and seed the rows that drive branches:

```yaml
# dynamodb (kind: datastore)
- {component: dynamodb, name: vms-put, store: {table: vms, op: put, key: "= input.id", value: "= input", where: "row == null"}}
- component: dynamodb
  name: vms-get
  errors: [{code: vm_not_found, status: 404}]
  store: {table: vms, op: get, key: "= input.id", not_found: vm_not_found}
# scenario: the VM already exists, so the create conflicts
state: {dynamodb: {vms: {vm-1: {id: vm-1, status: running}}}}
expect: ["!result.ok && result.error.code == 'conflict'", "state.dynamodb.vms['vm-1'].status == 'running'"]
```

When the merge tool combines duplicate boundary stubs, a `store` in either copy survives the
union, so declare it on one fragment and keep the others plain.

## 13. Fan-out and sweeps

*(verified)* Deliver to every subscriber, or sweep every row of a table in key order:

```yaml
- foreach: "= vars.subs.value"            # from a store query
  as: sub
  steps:
    - {call: webhook-sender.deliver, input: {url: "= vars.sub.url"}, as: sent, on_error: continue}
    - {when: "!vars.sent.ok", set: {ctx.failed: "= (has(ctx.failed) ? ctx.failed : []) + [vars.sub.url]"}}
```

Assert the count with `calls['webhook-sender.deliver'] == 3` and the failures with `ctx.failed`.

## 14. Reconciler converging over ticks

*(verified)* A reconciler that fails while a dependency is down and converges once it is back:

```yaml
flows:
  - {id: reconcile, entry: {caller: scheduler, interface: reconciler.tick, repeat: {count: 3, interval_ms: 30000}}}
scenarios:
  - id: recovers-on-second-tick
    flow: reconcile
    faults: [{target: compute.ensure, type: unavailable, calls: [1]}]
    expect:
      - "!passes[0].result.ok && passes[1].result.ok && passes[2].result.ok"
      - "passes[1].start_ms >= 30000 && state.reconciler.converged"
```

---

# Recipes for systems with many parts

> Requires mosaic with DESIGN §11 (in progress). These snippets follow DESIGN §11 and haven't
> been run against the engine yet; check them with the check tool before you copy one. Semantics:
> [behavior-language.md](behavior-language.md), sections 13 to 22.

The same few patterns recur in very different systems. Each recipe below shows one, from three
domains: a **distributed database** (Cassandra-like nodes `n1`–`n3`), a **front-end editor**
(VS Code-like windows, extension hosts and providers), and a **GPU serving engine** (vLLM-like
API server, scheduler and tensor-parallel workers `rank0`–`rank3`).

15. [Choosing the concurrency construct](#15-choosing-the-concurrency-construct)
16. [Quorum: wait for k of n, or time out](#16-quorum-wait-for-k-of-n-or-time-out)
17. [Hedging: speculative and first-wins requests](#17-hedging-speculative-and-first-wins-requests)
18. [All-reduce and barriers](#18-all-reduce-and-barriers)
19. [Deadlines that span hops](#19-deadlines-that-span-hops)
20. [Timers: periodic tasks and debounces](#20-timers-periodic-tasks-and-debounces)
21. [Capacity: pools, single threads and batch slots](#21-capacity-pools-single-threads-and-batch-slots)
22. [Publish and subscribe](#22-publish-and-subscribe)
23. [Multi-step scenarios: write then read](#23-multi-step-scenarios-write-then-read)
24. [Proving the path with trace assertions (and when to mock)](#24-proving-the-path-with-trace-assertions-and-when-to-mock)
25. [Streamed responses (SSE, token streams)](#25-streamed-responses-sse-token-streams)
26. [Busy loops, worker pools and bounded queues](#26-busy-loops-worker-pools-and-bounded-queues)
27. [Killing an instance mid-call](#27-killing-an-instance-mid-call)

## 15. Choosing the concurrency construct

| The code... | Model it with |
|---|---|
| sends to several peers at once and waits for all, k, or the first | `parallel` with `join: {need: all \| k \| any}` |
| loops over items one after another | `foreach` |
| runs a copy of itself on several machines, processes or windows | instances in a fixture's `topology`, and `on:` |
| schedules work later or periodically | `emit`/`publish` with `after_ms` or `every_ms` + `count` |
| bounds how much runs at once (pool, stage, event loop, batch size) | `capacity` on the component |
| notifies listeners | `publish` + `subscribe`, `delivery: sync` for inline emitters |
| has a request-wide time budget | `deadline_ms` on the entry, step or call |
| streams a response (SSE, async generator, progress callbacks) | `yield` in the callee, `stream: true` + `on_item` on the call |
| loops forever on a queue, or hands work between threads | `put` / `receive` on a channel, the loop in an `await: false` step |
| crashes or is OOM-killed | a `kill` fault or step, then `restart` |

A `foreach` standing in for concurrent sends gets the timing wrong: two hung replicas cost two
timeouts in a row (4,082 ms instead of 2,000 ms in the Cassandra benchmark), and a speculative
request can never fire for a slow replica.

## 16. Quorum: wait for k of n, or time out

**Distributed database.** A QUORUM write sends to every live replica and acknowledges after
`block_for` acks. It refuses before sending anything when too few replicas are alive, and times
out after the write timeout otherwise.

```yaml
- component: storage-proxy
  name: mutate
  behavior:
    - call: failure-detector.live-replicas        # liveness is membership's state, read through its interface
      input: {token: "= input.mutation.token"}
      as: fd
    - set:
        vars.block_for: "= input.consistency == 'ALL' ? 3 : (input.consistency == 'ONE' ? 1 : 2)"
    - if: "size(vars.fd.value.live) < vars.block_for"
      then:
        - title: Unavailable before any mutation is sent
          fail: {code: unavailable, status: 4096, data: {required: "= vars.block_for", alive: "= size(vars.fd.value.live)"}}
    - call: write-response-handler.await
      input: {replicas: "= vars.fd.value.live", block_for: "= vars.block_for", mutation: "= input.mutation"}
      on_error:                                   # the join's timeout becomes the protocol error
        - when: "error.code == 'timeout'"
          fail: {code: write-timeout, status: 4352, data: "= error.data"}
        - fail: "= error"
- component: write-response-handler
  name: await
  behavior:
    - parallel: "= input.replicas"
      as: replica
      steps:
        - call: mutation-verb-handler.do-verb
          on: "= vars.replica"                     # the local replica is just another instance
          input: {mutation: "= input.mutation"}
      join: {need: "= input.block_for"}
      timeout_ms: "= config['write-request-timeout-ms']"
      as_result: acks
      on_insufficient: {code: write-failure, status: 5376}
    - return: {applied: true, acks: "= vars.acks.received"}
```

The join's timeout error carries `data: {received, required}`, which is what the code reports to
the client. A `parallel` step takes no `on_error`, so the translation to the protocol error
happens in the caller of the interface that holds the join, as above.

```yaml
- id: quorum-write-two-silent
  fixtures: [three-node-rf3]
  faults:
    - {target: mutation-verb-handler.do-verb, type: timeout, instance: n2}
    - {target: mutation-verb-handler.do-verb, type: timeout, instance: n3}
  expect:
    - "!result.ok && result.error.code == 'write-timeout' && result.error.data.received == 1"
    - "duration_ms < 2100"                                   # one timeout, not two
```

**Editor.** `Promise.all` over extension activations is `join: {need: all}` with an
`on_insufficient` that matches the rejection; **GPU serving** worker RPC fan-out that tolerates
no failure is the same with `need: all`.

## 17. Hedging: speculative and first-wins requests

**Distributed database.** A read at ONE asks one replica; if it hasn't answered within the
table's speculative threshold, the coordinator asks another, and takes the first answer.

```yaml
- parallel: "= vars.ranked_replicas"         # closest first
  as: replica
  stagger_ms: "= config['speculative-retry-threshold-ms']"   # table default 99p, as a configured threshold
  join: {need: 1}
  timeout_ms: "= config['read-request-timeout-ms']"
  steps:
    - {call: read-verb-handler.do-verb, on: "= vars.replica", input: {read_command: "= input.read_command"}}
  as_result: reads
- return: "= vars.reads.results.filter(r, r.ok)[0].value"
```

With `stagger_ms`, the second branch starts only if the first hasn't succeeded by the threshold, so a
fast replica means one request and a slow one means two. Assert which happened:
`calls_by_instance['read-verb-handler.do-verb@n2'] == 1`, or
`trace.filter(e, e.type == 'call.start' && e.interface == 'read-verb-handler.do-verb').size() == 2`.

**Editor.** Completion providers queried at once, where the first non-empty answer wins:
`parallel` over the providers with `join: {need: any}` and no stagger. **GPU serving.** A router
that hedges a request to a second replica after a delay is the same as the database read.

## 18. All-reduce and barriers

**GPU serving.** In tensor parallelism, every rank computes its shard, and the step completes
only when all ranks have finished the all-reduce. One slow rank delays everyone; one failed rank
fails the step.

```yaml
- component: model-executor
  name: execute-model
  behavior:
    - parallel: ["rank0", "rank1", "rank2", "rank3"]
      as: rank
      steps:
        - {call: model-runner.forward, on: "= vars.rank", input: {batch: "= input.batch"}}
      join: {need: all}
      on_insufficient: {code: worker-failed, status: 500}
      as_result: shards
    - return: {tokens: "= vars.shards.results[0].value.tokens", step_ms: "= vars.shards.duration_ms"}
- component: model-runner
  name: forward
  latency_ms: "= 4 + size(input.batch) * 2"     # decode time grows with batch size
```

```yaml
- id: one-slow-rank-delays-the-step
  fixtures: [tp4]
  faults: [{target: model-runner.forward, type: latency, latency_ms: 40, instance: rank2}]
  expect: ["result.ok", "duration_ms >= 40"]
```

**Distributed database.** Waiting for every replica (consistency ALL, or a repair session's
Merkle trees from all replicas) is the same `need: all`.

## 19. Deadlines that span hops

**Editor.** A command runs with a cancellation token that times out after a configured delay. Every provider
call it makes shares that budget; a call that would start after the deadline is refused.

```yaml
flows:
  - id: format-document
    entry: {caller: user, interface: editor.format-document}
interfaces:
  - component: editor
    name: format-document
    behavior:
      - call: extension-host.provide-formatting-edits
        deadline_ms: "= config['editor-format-timeout-ms']"   # 750 ms; nested calls inherit it
        as: edits
        on_error: [{return: {applied: false, reason: "= error.code"}}]   # deadline_exceeded or timeout: keep the text
      - return: {applied: true, edits: "= vars.edits.value"}
```

`deadline` in CEL gives the absolute deadline, so a behavior can decide not to start optional
work: `when: "deadline == null || deadline - now > 100"`. **Database:** the request timeout,
counted from when the coordinator received the request, not per hop. **GPU serving:** a
request's abort deadline, inherited by scheduling and every decode step.

## 20. Timers: periodic tasks and debounces

**Distributed database.** Gossip runs every second; hint dispatch polls every 10 seconds. Schedule
them from a startup entry, or model the task as a flow with `entry.repeat`:

```yaml
- component: gossiper
  name: start
  behavior:
    - emit: gossiper.gossip-task-run
      every_ms: "= config['gossip-interval-ms']"
      count: 10
```

**Editor.** Auto-save after a delay: each edit schedules a save, and the save handler skips
itself when a newer edit happened after it was scheduled.

```yaml
- component: editor
  name: on-edit
  behavior:
    - set: {state.last_edit_ms: "= now", state.dirty: true}
    - emit: editor.autosave
      after_ms: "= config['files-auto-save-delay-ms']"
      input: {scheduled_at: "= now"}
- component: editor
  name: autosave
  behavior:
    - if: "state.last_edit_ms > input.scheduled_at"
      then: [{return: {saved: false, reason: superseded}}]
    - call: file-service.write
    - set: {state.dirty: false}
```

**GPU serving.** The engine core's step loop: a flow whose entry is `engine-core.step` with
`repeat: {count: 8, interval_ms: 0}`, or a timer with `every_ms`.

## 21. Capacity: pools, single threads and batch slots

```yaml
- {id: mutation-stage, kind: module, parent: write-path, capacity: {concurrency: 32, queue_limit: 1024}}   # database stage
- {id: extension-host, kind: service, capacity: {concurrency: 1}}                                      # editor: one JS thread
- {id: scheduler, kind: module, parent: engine-core, capacity: {concurrency: 128, queue_timeout_ms: 30000}}   # GPU: max-num-seqs
```

A call that finds every slot busy waits (a `queue` event, counted in `queued`); past
`queue_limit` it fails with `{code: overloaded, retryable: true}`. Drive a full pool with a
`parallel` fan-out that exceeds the concurrency, or with timers that land while earlier work is
still running; busy slots carry over between the steps of a multi-step scenario.

```yaml
# editor: hover and completions requested together; the extension host has one thread
- component: editor
  name: on-cursor-idle
  behavior:
    - parallel: "= ['hover', 'completions']"
      as: kind
      steps: [{call: extension-host.provide, input: {kind: "= vars.kind"}}]
      join: {need: all}
      as_result: provided
- id: extension-host-serializes-providers
  flow: cursor-idle
  fixtures: [one-window]
  expect:
    - "result.ok"
    - "trace.exists(e, e.type == 'queue' && e.component == 'extension-host')"   # the second request waited
```

## 22. Publish and subscribe

**Editor.** `onDidChangeTextDocument` is a synchronous `Emitter`: listeners run inline, in
order, and a listener's exception doesn't break the edit.

```yaml
- component: text-model
  name: apply-edits
  behavior:
    - set: {state.version: "= state.version + 1"}
    - publish: text-model.on-did-change
      input: {version: "= state.version"}
      delivery: sync
- {component: diagnostics, name: on-document-change, subscribe: [text-model.on-did-change], behavior: [...]}
- {component: outline, name: on-document-change, subscribe: [text-model.on-did-change], behavior: [...]}
```

**Distributed database.** Endpoint state changes (a node marked down) notify the hints service
and the storage service: `publish` from the failure detector, with async delivery. **GPU
serving.** An engine's output stream delivered to the API server's per-request consumer: async
`publish` per decode step.

## 23. Multi-step scenarios: write then read

The cheapest proof that a write lands is to read it back through the system's own read path,
in the same world. A flow tagged `writes` must have one; `--lint hollow` reports it otherwise.

```yaml
flows:
  - {id: cql-insert, tags: [writes], entry: {caller: cql-client, interface: transport.query-message}}
```

```yaml
# database
- id: insert-then-select-at-quorum
  fixtures: [three-node-rf3]
  steps:
    - {flow: cql-insert, as: w, input: {query: "INSERT INTO shop.users (id, name) VALUES (42, 'Ada')", consistency: QUORUM}}
    - {flow: cql-select, as: r, on: n3, input: {query: "SELECT name FROM shop.users WHERE id = 42", consistency: QUORUM}}
  expect: ["steps.w.result.ok", "steps.r.result.value.rows[0].name == 'Ada'"]
# editor
- id: open-edit-save
  fixtures: [one-window]
  steps:
    - {flow: open-file, as: open, input: {uri: "file:///work/a.ts"}}
    - {flow: type-text, as: edit, input: {uri: "file:///work/a.ts", text: "x"}}
    - {flow: save-file, as: save, input: {uri: "file:///work/a.ts"}}
  expect: ["steps.save.result.ok", "state['file-service'].files['file:///work/a.ts'].content.endsWith('x')"]
# GPU serving
- id: add-request-then-steps
  fixtures: [tp4]
  steps:
    - {flow: add-request, as: add, input: {request_id: req-1, prompt_tokens: 512, max_tokens: 4}}
    - {flow: engine-step, as: s1}
    - {flow: engine-step, as: s2}
  expect: ["steps.s2.result.ok", "state.scheduler.requests['req-1'].generated == 2"]
```

A later step can use an earlier result: `input: {statement_id: "= steps.prep.result.value.id"}`
(PREPARE then EXECUTE).

## 24. Proving the path with trace assertions (and when to mock)

A scenario that checks only `result.ok` passes even when the write went nowhere. Assert on
`state` (per instance) or on `trace`:

```yaml
expect:
  # the hint went to the down replica's queue on the coordinator, not to the replica
  - "state['hints-service@n1'].queues['n3'].size() == 1"
  # commit log before memtable, on the same replica
  - "trace.filter(e, e.type == 'call.start' && e.instance == 'n2' && e.interface in ['commit-log.add', 'memtable.put']).map(e, e.interface) == ['commit-log.add', 'memtable.put']"
  # no rank ran a second forward pass
  - "trace.filter(e, e.type == 'call.start' && e.interface == 'model-runner.forward' && e.instance == 'rank0').size() == 1"
```

**Mocks** replace a call's answer for one scenario:

```yaml
mocks:
  - {interface: schema.get-table, when: "input.table == 'users'", return: {exists: true, columns: [id, name]}}
```

Use one only while isolating a single fragment, before its neighbor exists. Delete it once the
real owner's interface is merged: a mock never checks the owner's contract, so it hides exactly
the seams a merged model must prove. The check tool refuses them under `--no-mocks`, which every
generation-pipeline gate uses.

## 25. Streamed responses (SSE, token streams)

*(verified, `internal/sim/streams_test.go`)* **GPU serving.** The engine yields a token per decode
step; the API server forwards each one as an SSE chunk the moment it is produced:

```yaml
- component: gateway
  name: chat
  latency_ms: 0
  behavior:
    - call: model.generate
      input: {prompt: "= input.prompt"}
      stream: true
      as: gen
      on_item:
        - {call: browser.sse, input: {chunk: "= vars.item", index: "= vars.item_index"}}
    - {return: {text: "= vars.gen.value.text"}}
- component: model
  name: generate
  latency_ms: 20                      # prefill
  behavior:
    - foreach: "= ['Hel', 'lo', ' world']"
      as: tok
      steps:
        - {wait: 10}                  # decode step
        - {yield: "= vars.tok"}
    - {return: {text: Hello world}}
```

```yaml
- id: sse
  flow: chat
  expect:
    - "trace.filter(e, e.type == 'call.start' && e.interface == 'browser.sse').map(e, e.t) == [30, 40, 50]"
    - "trace.filter(e, e.type == 'yield').map(e, e.index) == [0, 1, 2]"
```

A slow consumer (say `browser.sse` takes 15 ms) falls behind: the yields stay at 30, 40 and 50,
and the chunks are handled at 30, 45 and 60. A caller without `stream: true` gets
`{items: ['Hel', 'lo', ' world'], value: {text: 'Hello world'}}` at 50.

**Front-end editor.** VS Code's `withProgress` and streamed chat responses are the same shape:
the provider `yield`s progress reports and the workbench's `on_item` updates the view.

## 26. Busy loops, worker pools and bounded queues

*(verified)* **GPU serving.** vLLM's engine core busy-loops: it blocks on its input queue until
the API server puts a request, processes it, and blocks again. Start the loop as a step that
isn't awaited, then drive requests at their times:

```yaml
- component: engine
  name: loop
  latency_ms: 0
  behavior:
    - foreach: "= [1, 2, 3]"           # bound the loop; a receive with no timeout may wait forever
      steps:
        - {receive: requests, as: req}
        - {wait: 5}
        - {set: {state.done: "= state.done + [{'id': vars.req.id, 't': now}]"}}
- component: api
  name: submit
  latency_ms: 1
  behavior:
    - {put: requests, value: {id: "= input.id"}}
    - {return: {queued: "= channel_len('requests')"}}
```

```yaml
- id: busy-loop
  steps:
    - {interface: engine.loop, caller: client, await: false, as: loop}
    - {interface: api.submit, caller: client, at_ms: 50, input: {id: a}}
    - {interface: api.submit, caller: client, at_ms: 100, input: {id: b}}
  expect:
    - "state.engine.done == [{'id': 'a', 't': 56}, {'id': 'b', 't': 106}]"
```

The loop's third receive never gets an item: it is an idle consumer, so the run ends at 106 ms
without a warning (the loop step itself ends `canceled`). To model an engine that shuts down when
idle, give the receive a `timeout_ms` and an `on_error` that returns.

**Backpressure.** `capacity` bounds a channel; a producer that finds it full blocks until a
consumer takes an item. With `capacity: 2` and a consumer taking one item every 10 ms, puts of
four items land at 0, 0, 10 and 20 ms, and the trace's `put` events show `wait_ms` 10 for the
last two. A `timeout_ms` on the put turns a stuck pipeline into a `timeout` error.

**Worker pools.** Several consumers (`parallel` branches, or one step per worker) receiving from
the same channel share its items first come, first served.

## 27. Killing an instance mid-call

*(verified)* A worker that crashes while serving: the caller sees `peer-killed`; the abandoned
calls end `killed`; the worker's state is marked dead until a restart revives it.

```yaml
- component: api
  name: handle
  behavior:
    - {call: worker.work, on: w1, as: r, on_error: [{return: {err: "= error.code", at: "= now"}}]}
    - {return: {ok: true}}
```

```yaml
- id: kill-mid-call
  flow: handle
  topology: {worker: [w1, w2]}
  faults: [{target: worker, type: kill, instance: w1, at_ms: 30}]
  expect:
    - "result.value == {'err': 'peer-killed', 'at': 30}"
    - "state['worker@w1'].dead"
    - "trace.exists(e, e.type == 'call.end' && e.interface == 'store.write' && e.error.code == 'killed')"
- id: dead-then-restart
  topology: {worker: [w1, w2]}
  steps:
    - {kill: {component: worker, instance: w1}}
    - {flow: handle, as: dead}                     # fails at once: peer-killed
    - {restart: {component: worker, instance: w1}}
    - {flow: handle, as: revived}                  # served again
  expect: ["steps.dead.result.value.err == 'peer-killed'", "steps.revived.result.value.ok"]
```

In collectives, a rank killed while waiting in a `rendezvous` makes the other waiters fail with
`peer-killed` at once instead of waiting for the timeout. Use `retry` with `codes: [peer-killed]`
and an `on` template to fail over to another instance.

## Helpers that remove bookkeeping

```yaml
- set:
    vars.by_column: "= input.cells.transformMapEntry(i, c, {c.column: c.value})"   # map from a list
    vars.acks: "= sum(vars.res.results.map(r, r.ok ? 1 : 0))"
    state.row: "= merge(state.row, vars.by_column)"                          # deep merge, right wins
    state.endpoints: "= omit(state.endpoints, input.endpoint)"               # delete a key
- wait: "= random(100)"                                                     # LWT contention back-off, 0-99 ms, seeded
```

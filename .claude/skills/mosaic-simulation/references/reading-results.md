# Reading results and debugging runs

The shapes below come from `internal/sim` and `pkg/api`. The examples are real engine output for
the gateway test fixture (`internal/testdata/gateway/ontology.yaml`); write its runs with
`go run ./internal/devtools/fixtures -in internal/testdata/gateway/ontology.yaml -out /tmp/fx`.
The worked example's runs are tracked in `web/fixtures/envoy/runs/*.json` (from
`examples/envoy/ontology.yaml`), and `web/fixtures/language-demo/runs/*.json` and
`web/fixtures/shop/runs/*.json` are real engine output too.

## Contents

- [Run](#run)
- [Summary](#summary)
- [Trace events](#trace-events)
- [Following a trace](#following-a-trace)
- [Test reports](#test-reports)
- [Step results from the check tool](#step-results-from-the-check-tool)
- [Debugging checklist](#debugging-checklist)
- [Runs with instances, parallel steps and multi-step scenarios](#runs-with-instances-parallel-steps-and-multi-step-scenarios)

## Run

`mosaic sim run --format json` and `mosaic sim get <id> --format json` return
`{id, ontology, revision, flow, scenario, created_at, request, summary, trace}`. `request` is the
**effective** request after merging the scenario with your flags: the final `input`, `choices`,
`state`, `faults` and `expect`. Check it first when a run doesn't do what you expected.

## Summary

| Field | Meaning |
|---|---|
| `status` | `ok` (the entry call succeeded), `error` (the entry call failed: normal for refusal scenarios), `aborted` (a budget or runtime CEL error) or `pending` (the entry call never answered: a `hang` with `forever: true`) |
| `result` | `{ok, value?, error?}` from the entry call; `error` is `{code, message, status, retryable, data}` |
| `duration_ms` | The virtual clock at the end, **including async deliveries** |
| `events` | The number of trace events |
| `calls` | `{interface id: count}` for interfaces that were called. Each attempt and each async delivery counts. |
| `retries`, `faults` | Total retry events, and total fault hits |
| `ctx` | The final shared context |
| `state` | The final state of every stateful component, plus `{}` for each component whose behavior ran |
| `initial_state` | The state at the start, after scenario and run overrides. Diff it against `state` to see what changed. |
| `assertions` | `[{expr, passed, error?}]`. `error` holds a CEL evaluation error, such as a missing key. |
| `passed` | Every assertion passed and the run didn't abort. A run with no expectations passes unless it aborted. |
| `warnings` | Deduplicated messages (at most 100) |
| `seed` | The seed used (1 by default) |
| `abort` | Why the run aborted |
| `caps` | Only when a cap ended the run: `{max_events, max_virtual_ms, hit}`. Both caps are per scenario: `max_events` (default 20,000, up to 1,000,000) and `max_virtual_ms`. Raise the one in `hit`. |
| `pending` | Calls that never answered (a `hang` with `forever: true`) and were still in flight at the end: `[{call, from, interface, instance, start_ms, fault}]` |
| `passes` | Only for a flow whose `entry.repeat` is set: `[{pass, result, start_ms, duration_ms}]`, one per pass. `result` and `status` then describe the last pass. |

A real refusal summary (from `invalid-api-key.json`, abridged):

```json
{"status": "error",
 "result": {"ok": false, "error": {"code": "unauthenticated", "message": "unknown API key", "status": 401}},
 "calls": {"auth.authenticate": 1, "gateway.chat": 1},
 "assertions": [{"expr": "calls['throttle.check'] == 0 && ctx.upstreamDials == 0", "passed": true}],
 "passed": true, "warnings": []}
```

In expectations, `calls` contains **every** interface of the ontology (0 if never called), so
`calls['throttle.check'] == 0` works even though `throttle.check` is absent from the summary's
`calls`.

## Trace events

Every event has `seq`, `t` (virtual ms) and `type`. Most have `span` (one invocation),
`component` and `interface`. Every attempt of one call step shares the same `call` number.

| Type | Key fields | Meaning |
|---|---|---|
| `call.start` | `from`, `to`, `interface`, `attempt`, `parent` (the caller's span), `async`, `input` | An invocation begins; `component` is the caller |
| `call.end` | `ok`, `output`, `error`, `duration_ms`, `late`, `headers` | An invocation ends; `component` is the callee. `late: true` means the caller had already timed out. `headers` are the response headers (lower-case keys), when it has any. |
| `close` | `key` (the session), `output.pending` | A `close` step canceled the calls in flight carrying the session |
| `stall` | `index`, `wait_ms`, `error` (`stream_stalled`) | A streaming producer stayed blocked on a full `window` for `stall_ms` (§16.4) |
| `note` | `title`, `detail`, `source` | A narrated step ran |
| `set` | `scope` (vars, ctx or state), `path`, `old`, `new` | One assignment |
| `choice` | `key`, `option`, `origin` (scenario, expression or default) | A choice point resolved |
| `fault` | `fault` (the type), `message` (the code or message) | A fault matched this invocation |
| `retry` | `attempt` (the **next** attempt), `backoff_ms`, `message` (the failed code), `title`, `detail`, `source` | The caller retries; `interface` is the target that failed |
| `timeout` | `duration_ms` (the limit), `message` | The caller stopped waiting |
| `emit` | `from`, `to`, `interface`, `input` | An async message was queued (delivered later as `call.start` with `async: true`) |
| `limit` | `interface` (the applying one), `from`, `key` (the limiter's full id), `input {key, cost, gate}`, `output {decision, remaining, retry_after_ms, limit}`, `instance` | A limiter decided (behavior-language §25); a waiting decision is followed by a `queue` event with `wait_ms` |

DESIGN.md also lists a `warning` event type, but the engine reports warnings only in
`summary.warnings`, never in the trace.

A retry, as it appears in `retry-before-commit.json`:

```json
{"seq": 63, "t": 14,  "type": "fault",    "component": "upstream-a", "interface": "upstream-a.chat", "fault": "error", "message": "upstream_error"}
{"seq": 64, "t": 112, "type": "call.end", "component": "upstream-a", "interface": "upstream-a.chat", "attempt": 1, "ok": false,
 "error": {"code": "upstream_error", "status": 502, "retryable": true}, "duration_ms": 98}
{"seq": 65, "t": 112, "type": "retry",    "component": "dispatch", "interface": "upstream-a.chat", "attempt": 2,
 "title": "Upstream fails before commitment", "message": "upstream_error"}
{"seq": 67, "t": 224, "type": "call.end", "component": "upstream-b", "interface": "upstream-b.chat", "attempt": 2, "ok": true, "duration_ms": 112}
```

## Following a trace

- Start from `result`, then search the trace for the first `call.end` with `ok: false`. Its
  `error` is the root cause; later failures usually just propagate it.
- `choice` events show which branch ran and why (`origin`). If a scenario's override seems
  ignored, check the key against `mosaic plan` and look for an `origin: scenario` event.
- `set` events with `scope: ctx` show the story the behaviors recorded. `note` events give the
  narrative with source lines.
- A `timeout` event can carry a smaller `t` than the late `call.end` before it, because the clock
  returns to start + `timeout_ms`.
- `--format summary` prints one line per call, which is the quickest way to check the call order
  and the attempts.

## Test reports

`mosaic test <ont>` returns `{revision, passed, total, failed, results: [...]}`. Each result is
`{scenario, name, passed, status, assertions, abort?, error?, run_id?}`: `abort` for aborted
runs, and `error` when the scenario couldn't run at all (a request error). Open a failing run with
`mosaic sim get <run_id> --format trace`, or rerun the scenario with
`mosaic sim run <ont> --scenario <id> --format summary`.

## Step results from the check tool

`go run ./internal/devtools/check -f ... --scenario '^<id>$' --steps` prints what each scenario
step returned, so you don't need a server to see it (DESIGN §17 item 15). It prints one line per
step, before the `--trace` and `--state` output when those are also given:

```
✓ scenario multi
    steps: 3
      [0] g: flow get status=ok t=0+3ms value {"n":1,"s":"é"}
      [1] -: svc.bad status=error t=3+1ms error {"code":"nope","message":"no"}
      [2] big: svc.big status=ok t=4+1ms value "xxxxxxxx…xxxx… (222 bytes; --steps-full)
```

- Each line shows the step's index, its `as` name (`-` when it has none), its flow or interface
  (with `on <instance>`), its status, start and duration in ms, then `value <json>` or
  `error <json>`.
- The JSON is compact, with sorted keys. It is cut at 200 bytes, and the cut is marked
  `… (N bytes; --steps-full)`. Add `--steps-full` to print it in full.
- A scenario without `steps` prints one line, `result: status=<status> value|error <json>`.

## Debugging checklist

**Aborted** (`status: aborted`; `abort` gives the step path):

| `abort` looks like | Cause and fix |
|---|---|
| `x.y.behavior[0].set.ctx.shard: input.shard: no such key: shard` | A field is missing. Add it to the caller's `input` (or use `fill: true`), give the request schema the property, or guard with `has(input.shard)`. |
| `...set.ctx.a: vars.x.value: no such key: x` | The call has no `as: x`, or this step runs on a path where the call was skipped (`when`, another branch). |
| `...: found no matching overload for '_+_' applied to '(int, double)'` (or `no such overload`) | Mixed int and double arithmetic, or an operator applied to incompatible types. Use `double()`/`int()`/`string()`. Validation catches this only when the operands are literals. |
| `...if: 1: expected a boolean, got int64` | An `if`/`when` expression didn't produce a bool. Validation doesn't catch this. |
| `...default: zz is not an option of c.a.k` | An expression default returned an unknown option. |
| `...call: ['c.b'][attempt]: index out of bounds: 1` | A dynamic target indexed past the list. Tie `max_attempts` to `size(list)`. |
| `...call: target must be a string, got int64` | A dynamic call expression produced a non-string. |
| `event budget of 20000 exceeded`, `call depth limit of 64 exceeded at ...`, `emit budget of 1000 exceeded` | Unbounded recursion, or an emit loop. Add a termination condition on `state` or `ctx`. A long but finite run (a load test of many requests) instead needs a higher **`max_events`** on the scenario (up to 1,000,000); `caps` in the summary says which cap was hit. |

**Warnings** (fix them all; `mosaic test` should be warning-free):

| Warning | Fix |
|---|---|
| `a.b request: $.id: expected string, got integer` | The caller's `input` disagrees with the callee's `request` schema. Fix whichever is wrong. |
| `a.b request: $: missing required property "shard"` | Pass the property, use `fill: true`, or drop it from `required`. |
| `a.b response: $.status: x is not one of the allowed values` | The behavior's `return` doesn't match the `response` schema. |
| `call to unknown interface "x.y"` | A dynamic call target expression built an id that doesn't exist. |
| `choice k has no option "x"; using its default` | A typo in `--choice`. Check `mosaic plan`. |

**A failed assertion with no abort**:

1. Read the assertion's `error`. `no such key` means the expectation referenced a ctx key, state
   component or interface id that doesn't exist, or read `result.error` on a successful run.
2. Compare `request` (what actually ran) with what you intended: were the choices, state and
   faults applied?
3. Check `initial_state` against `state` to see whether state changed as expected.
4. Look for an earlier failure: a gate that refused before the step you're asserting on.
5. Change one lever at a time with `sim run --no-save` until the run matches, then fix the
   scenario or the behavior. Decide which one is wrong by reading the cited source line, not by
   making the test pass.

## Runs with instances, parallel steps and multi-step scenarios

> Requires mosaic with DESIGN §11 (in progress).

- **Order by `seq`, not `t`.** Parallel branches run in list order but carry their own virtual
  times, so `t` jumps back and forth. Events after a join completed are marked `late`.
- **`instance`** on each event says where it ran. A call landing on the wrong instance usually
  means a missing `on:` (a callee in another group defaults to its first instance, with a
  warning) or a fixture whose topology names different instances.
- **The summary adds** `calls_by_instance` (`<interface>@<instance>`), `steps` (one result per
  scenario step), `queued` (capacity waits; each has a `queue` event), `mocks` (mocked calls) and
  `executed` (behavior step paths, for `--behavior-coverage`).
- **State keys** are `<component>@<instance>` for instance groups. Diff `initial_state` and `state`
  per instance to see which replica a write reached.
- A warning about a step's **`at_ms` in the past** means it started late: by the time the driver
  reached it, the clock had passed its `at_ms`. A step without `at_ms` starts after the previous
  step's emits and timers finish; steps overlap only through `at_ms` or `await: false`.
- **`deadline_exceeded`** means a call started after the inherited deadline; **`timeout`** with
  `data.received`/`required` comes from a join; **`overloaded`** from a full queue;
  **`rate_limited`** (status 429, `data: {limiter, key, limit, remaining, retry_after_ms}`) from a
  full limiter: check `limits` in the summary and the `limit` events for the key that filled;
  **`unknown_instance`** from an `on:` naming an instance the topology doesn't have.

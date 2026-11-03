# Judge 3: engine lifecycle (L3-1 to L3-8)

Model: `examples/vllm/vllm.json` (merged). World: `full-tp1-llama-8b`. Code: vLLM v0.32.0.
Scenarios: `judge3/scenarios/L3-*.yaml` (ids `bench-l3-*`, lowercase because check rejects upper-case ids).
Run: `go run ./internal/devtools/check -f examples/vllm/vllm.json -f examples/vllm/judge3/scenarios/L3-N.yaml --no-mocks --steps`.

**Steps passed: 13 / 30.** Cases: 1 pass, 0 partial, 0 sim-gap, 3 missing, 4 fail. **Expectations corrected: 7.**

## 1. Cases

| ID | Step | Verified expectation (correction) | Score | Root cause | Evidence |
|---|---|---|---|---|---|
| L3-1 | a | Without dev mode the 4 routes 404; with it, startup logs the SECURITY WARNING (`routers.py:40-47`, `serve/__init__.py:44-47`) | partial | model: route registration and the warning aren't modeled; each route checks `config['vllm-server-dev-mode']` | `bench-l3-1a` passes (404s) |
| | b | `/sleep?level=1` aborts the running request, offloads weights, discards KV, reply `{status: sleeping, level: 1}`, gauge `weights_offloaded` (`core.py:974-995,2088-2092`) | **fail** | model: the deferred sleep (`engine-core-proc.notify-idle-state-callbacks`) only calls `finish-pause`, never `executor.sleep` (code `core.py:986-995`); idle callbacks never fire once the last batch drains | `bench-l3-1b` fails: no `executor.sleep` call, weights never offloaded |
| | c | Queued while asleep; `wake_up?tags=weights` -> sleeping/["weights"]; plain wake -> awake/null; request runs | pass | (warning: `post-wake-up` schema has `tags maxItems: 0`) | `bench-l3-1c` |
| | d | **Corrected:** `level=3` gives **400** (validation handler, `param: query.level`), not 422 (`exception_handling/register.py:29`, `handlers/validation.py:149-198`). `level=2` discards weights, gauge `discard_all` | partial | model: 400 with `param: "level"` and an invented message; level 2 right | `bench-l3-1d` fails on `param` only |
| L3-2 | a | `pause?mode=keep` -> paused, `is_paused` true, PAUSED_ALL, no abort. **Corrected:** default `clear_cache=true` is not ignored for keep: once idle `_finish_pause(True)` resets the prefix cache with `reset_running_requests=True`, preempting the frozen requests (`core.py:898-919`, `scheduler.py:2850-2866`) | partial | model: `finish-pause` never runs unless new input wakes the loop, so no preemption | `bench-l3-2a` fails on preemption |
| | b | Request sent during pause queues; `/resume` -> resumed; both finish normally | **fail** | model: kept stream's output sits in the collector, step cancelled, 4 tasks still waiting at end of run | `bench-l3-2b` status error |
| | c | `pause?mode=wait` returns only after the in-flight request finishes (`core.py:1573-1578,2098-2103`) | **fail** | model: `engine-core-proc.pause-scheduler` returns `pending: true` immediately; `/pause` replies at 197 ms, request finishes at 303 ms | `bench-l3-2c` |
| L3-3 | a | **Corrected:** labels print in declaration order: `vllm:request_success_total{model_name="llama-8b",engine="0",finished_reason="length"} 1.0` (`loggers.py:497,808-819`); other reasons at 0 from startup | partial | model: one unlabeled `request_success` counter, no zero series at init, no `GET /metrics` route (edit: route over `prometheus-registry.collect` plus labeled counters) | `bench-l3-3a` fails label/startup checks, counter checks pass |
| | b | Gauges running/waiting/kv_cache_usage_perc, TTFT/e2e histograms count 1, sleep gauge `awake`=1 set at init (`loggers.py:528-620,931,961`) | missing | model: no gauges or histograms written; sleep gauge only on sleep/wake | `bench-l3-3b` fails 4 checks |
| | c | `--disable-log-stats`: no StatLoggerManager, no `vllm:*` series; confirmed no others registered in the default deployment (lazy-only: tool parser, websocket, sleep metrics) (`async_llm.py:150,196-205`) | partial | model: registry stays empty (right), but the `/metrics` route and HTTP instrumentator aren't modeled | `bench-l3-3c` passes |
| L3-4 | a | **Corrected:** message prints `max_position_embeddings=131072.0` (float, `derived *= scaling_factor`) and ends with the `VLLM_ALLOW_LONG_MAX_MODEL_LEN must be used with extreme caution` text (`model.py:2585-2665`) | partial | model: right refusal and place (`engine-args.create-engine-config`), message prints int and drops text; contract: `api-server-entry.build-async-engine-client` forwards only model/tp/pp/dp, so `vllm serve --max-model-len 200000` starts | `bench-l3-4a`, `bench-l3-4a-cli` fail |
| | b | Env override -> warning, `/v1/models` reports 200000 | partial | world/contract: `/v1/models` returns the world's `config['max-model-len']`, not the validated value | `bench-l3-4b` passes (outcome) |
| | c | `128k`=128000, `128K`=131072, `1.5K` rejected (`argparse_utils.py:41-93`) | missing | model: no human-readable parser; `"128K"` is a schema warning and dropped | `bench-l3-4c` |
| | d | `-1` -> 131072, then fit-to-memory (`kv_cache_utils.py:2414-2483,2635-2636`); full length fits on 80 GB | partial | model: no fit-to-memory step (`gpu-worker-impl.update-max-model-len` never called); `auto` not parsed | `bench-l3-4d` passes (outcome) |
| L3-5 | a | API SIGTERM handler logs, `engine_client.shutdown(timeout)` drain/abort, then `server.should_exit` (`launcher.py:251-283`) | missing | model: no API-server signal handler entity; `server_should_exit` stays false | `bench-l3-5a` fails |
| | b | Drain: request finishes normally. **Corrected:** a client added during drain gets an ABORT output, so HTTP 200 with `finish_reason: "abort"` (`core.py:1708-1717,2122-2125`) | pass | | `bench-l3-5b` |
| | c | Request outlives deadline -> force kill of the process tree (`v1/utils.py:633-658`, `engine/utils.py:335-348`) | pass | (5 s timeout instead of 30 s, budget) | `bench-l3-5c` (kill at 5007 ms) |
| | d | **Corrected:** with timeout 0 a still-alive core is force-killed at once after SIGTERM; the core's `aborting in-flight requests` log and `abort` outputs happen only if it wins that race (`engine/utils.py:47-67`, `v1/utils.py:624-658`) | pass | | `bench-l3-5d` (kill ~7 ms after SIGTERM) |
| L3-6 | a | Dump, fatal-error log, ENGINE_CORE_DEAD, no recovery; same under `step_with_batch_queue` (`core.py:562-575,726,771,1508-1514,1771-1781`) | pass | | `bench-l3-6` |
| | b | Non-stream 500 with EngineDeadError text; stream error chunk then `[DONE]` | pass | | `bench-l3-6` |
| | c | `/health` 503; new request 500 in preflight, never reaches `add-request` | pass | | `bench-l3-6` |
| | d | Keep-alive: server stays up; without it watchdog sets should_exit | pass | | `bench-l3-6`, `bench-l3-6d-no-keepalive` |
| L3-7 | a | 503 with the fixed QueueOverflowError text, in the API process (`async_llm.py:343-360`, `exceptions.py:156-168`) | **fail** | model: path right (preflight -> check-admission -> error response, no engine call) but message is `queue full: 4 unfinished, max 4` | `bench-l3-7a` |
| | b | `n: 2` counts 2 | pass | | `bench-l3-7b` |
| | c | Stream over limit gets a real 503 | pass | | `bench-l3-7c` |
| | d | `admission_rejections_total` +1 per rejection, `/health` 200, in-flight finish `length` | pass | | `bench-l3-7d` (4 concurrent `await: false` requests) |
| L3-8 | a | **Corrected:** Llama-3.1 defaults temperature 0.6, top_p 0.9, max_tokens 16; warning text is ``...overridden by the model's `generation_config.json`: `{...}`. If this is not intended, please relaunch vLLM instance with `--generation-config vllm`.`` (`model.py:1892-1899`) | partial | model: right values reach add-request but `model-config.get-diff-sampling-param` is a stub (schema examples); warning not modeled | `bench-l3-8a` fails on warning |
| | b | 3 prompts / 2 params -> error before any add | pass | | `bench-l3-8b` |
| | c | `enqueue` returns ids without stepping; `wait_for_completion` returns sorted outputs | pass | | `bench-l3-8c` |
| | d | Default `LLM` -> `Stat logging disabled`; with stats on, snapshot includes `vllm:request_success` (`llm.py:226-227`, `llm_engine.py:444-446`) | **fail** | model/world: `llm-engine` starts `log_stats: true`; `LLM.__init__` not modeled; snapshot returns only a count | `bench-l3-8d-default`, `bench-l3-8d-enabled` fail |

Case scores (worst step): L3-1 fail, L3-2 fail, L3-3 missing, L3-4 missing, L3-5 missing, L3-6 pass, L3-7 fail, L3-8 fail.

World note: on `full-tp1-llama-8b`, `LLM.generate` returns `[]` unless `state: {engine-core-proc: {client_kind: sync}}` is seeded; nothing on the `LLM` path selects the sync client (L3-8 scenarios seed it).

## 2. Wrong claims in the model

1. `engine-core-proc.pause-scheduler` claims "the utility reply waits for it" but returns `pending: true` at once; `/sleep` and `/pause?mode=wait` reply before the pause completes (code `core.py:2098-2103`).
2. `engine-core-proc.notify-idle-state-callbacks` only calls `finish-pause`; the code's deferred sleep then calls `model_executor.sleep(level)` (`core.py:986-995`). A sleep with work in flight never offloads weights. Idle callbacks also don't fire when the last batch drains.
3. `async-llm.check-admission` returns its own message strings; the code uses the fixed `QueueOverflowError` / `MaxQueuedTokensError` texts (`vllm/exceptions.py:161-182`).
4. `stat-logger-manager.record` (cites `loggers.py:1138-1330`) writes only `generation_tokens` and an unlabeled `request_success`; drops labels, gauges and histograms. `vllm:engine_sleep_state` isn't initialized to `awake` (`loggers.py:616-617`).
5. `api-server-entry.build-async-engine-client` claims the CLI engine args go to `create_engine_config`, but forwards only model, tp, pp, dp (drops `max_model_len`).
6. `llm-engine` initial `log_stats: true` is wrong for a plain `LLM()` (`llm.py:226-227`).
7. `model-config.get-and-verify-max-len` message prints an int and drops text (L3-4a).
8. `llm.wait-for-completion` takes a `num_requests` argument the code doesn't have (`llm.py:549-572`); `llm.run-engine` stops after that many finish, the code loops on `has_unfinished_requests()` (`offline.py:610`). `llm.enqueue` ignores `sampling_params`.
9. `dev-sleep-router.post-sleep` validation error has `param: level` and an invented message; `post-wake-up`'s `tags maxItems: 0` contradicts `api_router.py:46`.
10. Probable: after `AsyncLLM.shutdown`, in-flight `generate` calls get `engine-dead-error` 500; the code only marks dead, closes sockets and cancels output tasks (`async_llm.py:296-308`, `core_client.py:520-551`).
11. Minor: `async-llm.output-handler` gates recording on `config['disable-log-stats']` rather than the logger manager existing (`async_llm.py:150,897`); `async-llm.sleep` / `pause-generation` skip `renderer.clear_mm_cache_async()` (`async_llm.py:975-976,1155-1156`).

Citation checks: about 30 in-group citations hand-checked (pause-scheduler 2088-2095, has-requests 2803-2811, reset-prefix-cache 2850-2874, executor 383-405, cu-mem-allocator `sleep_mode_backend.py:127-137`, handle-shutdown 1640-1658, check-health 1091-1092, busy loop 1508-1514, admission, loggers 47/847-859) resolve and match. Global `--cite-sample 10 --seed 34`: 10/10 resolve and support their claims (item 9, `torch-bindings.hisparse-resolve-residency`, cites the CUDA kernel rather than the op registration: weak but not wrong).

## 3. Builder findings

- Docstring "clear_cache ignored for keep" (`pause_generation`): **refuted** by the code (`core.py:914-919`); the model's `finish-pause` preempts correctly when it runs.
- `max-model-len` config summary "llama3 RoPE is not rescaled": **confirmed** for the value, but the derived length is a float (131072.0).
- `disable-log-stats` summary "LLM overrides it to true": **confirmed**, but contradicted by `llm-engine`'s initial state.
- `launcher.terminate-if-errored` ASSUMPTION (output handler not otherwise stopped): **confirmed** (`async_llm.py:1298-1309`).

## 4. Simulator gaps

None blocked a step; every non-pass is model, world, contract or benchmark. Practical limits:
- L3-5c: a 30 s drain at the assumed ~30 ms/token exceeds the event/iteration budgets; run with a 5 s timeout. L3-2 needed `max_iterations: 1000000`, `max_events` >= 600000.
- `check --trace` has no scenario filter (about 1M lines), so path evidence was asserted through `trace` in `expect`.

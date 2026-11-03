# Judge 2: execution and parallelism (`execution-parallel`, P1–P5)

Blind re-measurement of `examples/vllm/vllm.json` against vLLM v0.32.0
(`/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`). Scenarios: `judge2/scenarios/P1.yaml` … `P5.yaml`, run with
`go run ./internal/devtools/check -f examples/vllm/vllm.json -f examples/vllm/judge2/scenarios/<CASE>.yaml --no-mocks --scenario '^bench-' --trace`.

**Result: steps 8 / 16 pass. Cases: 1 pass (P2), 2 partial (P4, P5), 1 missing (P3), 1 fail (P1).**
I corrected 4 expectations: P1(a), P1(d), P2(b) and P4(b).

Deployed-world facts that drive the corrections:
- The V2 model runner (`vllm/v1/worker/gpu/model_runner.py`) is the default for Llama (`vllm/config/vllm.py:703-739`). Methods `ngram` and `eagle3` are both supported (`vllm.py:2914-2953`).
- `method: ngram` turns async scheduling **off**, because it is not in `EagleModelTypes`/`NgramGPUTypes` (`vllm.py:1595-1608`). EAGLE keeps it on.
- On V2, `ngram` runs the GPU `NgramGPUSpeculator` (`gpu/spec_decode/__init__.py`, `use_ngram()`). With only `prompt_lookup_max: 4` given, `prompt_lookup_min` resolves to 4 (`config/speculative.py:1201-1207`).

## 1. Cases

| ID | Step | Verified expectation (corrected?) | Score | Root cause | Evidence |
|---|---|---|---|---|---|
| P1 | a | **Corrected.** The speculator finds the longest n-gram (n in [4,4]), right-most occurrence, and always writes **exactly K=5 drafts** (`ngram/speculator.py:56-84, 113-148`). On V2 the drafts stay **GPU-resident** (`req_states.draft_tokens`, `model_runner.py:2240-2254`). With sync scheduling and no structured output, `take_draft_token_ids` hands the scheduler **`[-1]*5` placeholders** (`gpu/spec_decode/utils.py:84-91`). So the next `SchedulerOutput` carries 5 placeholders, not the draft ids. | **fail** | model | A direct `ngram-gpu-speculator.propose` call with token rows computes `[60..64]` correctly (right-most match). But `gpu-model-runner.sample-tokens` calls `propose` without the context tokens, so the drafts come from a choice (800+k). `gpu-model-runner.take-draft-token-ids` returns those real draft values, not -1, and the expectation `steps.take…== [[-1]*5]` fails. |
| P1 | b | `update_draft_token_ids` sets `spec_token_ids`. Then `schedule` gives `num_new_tokens = num_tokens_with_spec - num_computed` = 1+5, and `allocate_slots(…, num_lookahead_tokens=0 for ngram)` reserves KV for all 6 (`scheduler.py:701-781, 861-876`; `vllm.py:615-641`). | pass | — | `s2.num_scheduled_tokens == {p1: 6}`, 5 spec tokens scheduled, `kv-cache-manager.allocate-slots` called with 6 |
| P1 | c | One target forward. The rejection sampler accepts a prefix plus 1 bonus or recovered token, so a step emits 1–6 tokens (`model_runner.py:1640-1652`). | partial | model / simulator | The path matches: `wr-spec-decode-step`, then one `rejection-sampler.sample` and one `propose`. But acceptance is a 2-option choice (`accept_all` or `reject_first`), so only 1 or 6 tokens can come out, never an accepted prefix of 1–4. The bonus token is `random()`. |
| P1 | d | **Corrected.** With no match, the code still proposes 5 drafts, each the **last sampled token**. They are verified as ordinary rejectable drafts, so the step is still a spec-decode step (`speculator.py:141-148`). | partial | model | A direct call with token rows returns `[8,8,8,8,8]` (pass). Inside a step, though, no-match is the choice `match: none`, which returns **`[]`**. That contradicts the code, and the model's own `wr-spec-ngram-no-match` asserts `[[]]`. |
| P2 | a | `_update_request_with_output` appends tokens one by one and `check_stop` hits `num_output_tokens >= max_tokens`. It trims the rest (`del new_token_ids[num_new:]`) and finishes `length` (`scheduler.py:2493-2510`, `sched/utils.py:114-119`). | pass | — | `u3` for `req-len`: `new_token_ids == [107,108,109]` (1+6+3 = 10), `finish_reason == 'length'` |
| P2 | b | **Corrected wording.** A stop **token id** or EOS inside the accepted run trims the later tokens and finishes `stop` with `stop_reason` = that id (`utils.py:104-112`). Stop **strings** are matched by the detokenizer in the front-end, not here. | pass | benchmark | `req-stop` accepts `[301,302,303]` with stop id 302, giving `[301,302]` and `finish_reason == 'stop'` |
| P2 | c | Rejected drafts roll back `num_computed_tokens` by the rejected count, and the blocks stay with the request to be overwritten next step (`scheduler.py:2110-2127`). Finished requests free their blocks. | pass | — | `req-rej` accepts 2 of 5: computed 14 goes to 11, a "Roll back the rejected draft tokens" note, and `req_to_blocks['req-rej']` has 2 blocks (= ceil(17/16)). `req-len` and `req-stop` are freed. |
| P3 | a | At T=0 the target is greedy: a draft is accepted iff it equals the argmax, and the bonus is the argmax, so the output equals non-spec greedy output (`rejection_sampler.py:407+`; `draft_sample_method` defaults to `greedy`, `speculative.py:600`). | sim-gap | simulator (+model) | The path is right: EAGLE3 → `wr-spec-decode-step` → one `rejection-sampler.sample`. The model holds no logits, acceptance is a choice, and the bonus is `random()`, so equality with greedy output can't be asserted. The behavior also never branches greedy vs. random even though its summary says it does. |
| P3 | b | `rejection_sample_method` defaults to `standard`, probabilistic rejection, which preserves the target distribution (`speculative.py:529`). | sim-gap | simulator | Mosaic has no value-level distributions to test |
| P3 | c | `make_spec_decoding_stats(num_draft_tokens, num_accepted_tokens)` goes into `SchedulerStats.spec_decoding_stats` (`scheduler.py:2128-2134`). It feeds the counters `vllm:spec_decode_num_draft_tokens` and `vllm:spec_decode_num_accepted_tokens` (exported with `_total`, `v1/spec_decode/metrics.py:229-231`). | **missing** | model | No interface models spec-decode stats or metrics. `scheduler.update-from-output` has no `spec_decoding_stats`, and the stat loggers only count requests and generation tokens. |
| P4 | a | `VllmConfig.__post_init__` → `ModelConfig.verify_with_parallel_config` raises `ValueError("Total number of attention heads (32) must be divisible by tensor parallel size (3).")` (`config/model.py:1544-1550`, `vllm.py:1452`). No AsyncLLM is built and no worker starts. | pass | — | `bench-p4-a-tp3-config`: value-error from `model-config.verify-with-parallel-config`, and 0 calls to `async-llm.from-vllm-config` and `init-device` |
| P4 | b | **Corrected.** With the backend unset, `ParallelConfig.__post_init__` raises `ValueError("World size (8) is larger than the number of available GPUs (4) in this node…")` (`config/parallel.py:1047-1057`). This happens during config creation, before any executor. It is not an executor placement or Ray placement-group failure. | pass | benchmark | `bench-p4-b-tp8-config`: that message, from `parallel-config.post-init`, with no executor |
| P4 | c | `run_server` binds the socket (`setup_server`, bind only), then `build_async_engine_client` calls `create_engine_config`, which raises. `serve_http` (listen) is never reached (`api_server/entry.py:53-83, 165-200`; `launcher.py:335-348`). | partial | contract | Through `serving-api-cli-serve` the server never serves (`launcher.serve-http` = 0), but for the wrong reason. `api-server-entry.build-async-engine-client` passes only `{model}` (+fill) to `engine-args.create-engine-config` and drops the CLI engine args. So TP 3 / TP 8 pass validation, AsyncLLM and the engine core start, and the run fails with a `runtime-error` in `multiproc-executor.init-executor`, because the fixture has no rank1/rank2. Fix: forward `AsyncEngineArgs.from_cli_args(args)`, or `config['tensor-parallel-size']`, `pipeline-parallel-size` and the rest, into create-engine-config. |
| P5 | a | Stage 0 does a non-blocking `isend_tensor_dict` and returns None (`gpu_worker.py:1338-1356`). The stage-1 rank waits in `irecv_tensor_dict` and, once dead, never answers. | pass | — | rank0 and rank1 (TP pair, stage 0) both return null, there is a `put pp-hidden:1` from rank0, and no successful receive on rank2. rank2's step ends `peer-killed`. |
| P5 | b | The `MultiprocWorkerMonitor` thread wakes on the dead process's sentinel. It sets `is_failed`, shuts down and fires the failure callback, which puts EXECUTOR_FAILED on the engine input queue (`multiproc_executor.py:299-333`, `core.py:1149-1151`). | partial | simulator | The logic is right (`multiproc-executor.monitor-workers` → `shutdown` → `executor-fail-callback`), but the scenario has to call `monitor-workers` by hand with `died_rank`. The `kill` of `gpu-worker-impl@rank2` doesn't wake anything. |
| P5 | c | The busy loop raises `RuntimeError("Executor failed.")` (`core.py:1701-1702`) and `_send_engine_dead` sends ENGINE_CORE_DEAD. The client raises `EngineDeadError` and the output handler propagates it to every in-flight request. `EngineDeadError` (a `VLLMServerError`) maps to 500, and `terminate_if_errored` sets `server.should_exit` unless `VLLM_KEEP_ALIVE_ON_ENGINE_DEATH` is set (`vllm_error.py:28-65`, `error_response.py:65-69`, `launcher.py:327-333`). Clarification: `/health` answers 503, and a stream that already sent 200 gets an error chunk instead. | pass | — | `loop` fails with 'Executor failed.', and the trace shows `send-engine-dead` → `async-llm.output-handler` → `output-processor.propagate-error`. The in-flight queue `chatcmpl-inflight-0` raises `engine-dead-error`, a new chat gets 500, and `launcher.server_should_exit == true`. |

## 2. Wrong claims in the model

1. **`gpu-model-runner.take-draft-token-ids` returns the real drafts** (`state.draft_tokens`). The cited code (`model_runner.py:2282-2283` → `spec_decode/utils.py:84-91`) returns `[-1]*num_draft_tokens` placeholders unless the batch has structured-output requests. V2 keeps the drafts GPU-resident, and the scheduler only ever sees -1s. Affected: `wr-spec-eagle3-verify-and-propose`, `wr-spec-decode-gpu-resident-drafts` (step `d`) and `wr-spec-ngram-no-match`.
2. **`ngram-gpu-speculator.propose` choice `match: none` returns no drafts (`[]`).** The code always writes K drafts, filling invalid slots with the last sampled token (`ngram/speculator.py:141-148`). The model's own computed branch even says so. Also, `gpu-model-runner.sample-tokens` never passes the token rows, `num_sampled` or `last_sampled` to `propose` (`model_runner.py:2241-2255` passes them), so the computed branch is unreachable from a step.
3. **`api-server-entry.build-async-engine-client` calls `create-engine-config` with only `{model}`.** The code builds `AsyncEngineArgs.from_cli_args(args)` (`entry.py:53-66`), so every `vllm serve` engine-arg check (TP/heads, world size vs. GPUs, …) is bypassed on the serve path, while the executor still reads `config['tensor-parallel-size']`.
4. **`rejection-sampler.sample`'s summary claims** greedy rows accept iff the draft equals the argmax and random rows use min(1, p/q). The behavior has no greedy/random branch and only the outcomes "all accepted" or "first rejected", so partial acceptance, which is the common case, can't be produced.
5. **Spec-decode stats are dropped.** `scheduler.update-from-output` rolls back rejected drafts (`scheduler.py:2110-2127`) but omits the `make_spec_decoding_stats` call in the same block (2128-2134). No metric is modeled.
6. **World gap.** The config `async-scheduling` is independent of `speculative-method`. The code forces it to `false` for `ngram` (`vllm.py:1595-1608`); the model keeps `true` unless a scenario overrides it.
7. **Minor.** The model's PP hand-off key `pp-hidden:<pp_rank>` ignores the TP rank. With TP2×PP2, both stage-0 TP ranks `put` to the same key, and either stage-1 rank may consume either one. In the code, each TP rank sends to its counterpart in the next stage.

Citations checked against the code (13): the following match.
- `gpu-worker-impl.execute-model` (gpu_worker.py:1300-1360)
- `ngram-gpu-speculator.propose` computed branch (speculator.py:20-148, 216-270)
- `scheduler.update-from-output` roll-back (scheduler.py:2110-2127)
- `scheduler.update-draft-token-ids` (2550-2569)
- `multiproc-executor.monitor-workers` (299-333)
- `engine-core-proc.executor-fail-callback` (core.py:1149-1151)
- `engine-core-proc.handle-executor-failed` (1701-1702)
- `model-config.verify-with-parallel-config` (model.py:1532-1575)
- `parallel-config.post-init` world-size check (parallel.py:1047-1057)
- the `use-v2-model-runner` config (vllm.py:703-739)
- the `prompt-lookup-*` configs (speculative.py:1195-1207)

These are wrong or incomplete: `gpu-model-runner.take-draft-token-ids`, the `propose` call in `gpu-model-runner.sample-tokens` (model_runner.py:2224-2253), and `api-server-entry.build-async-engine-client` (entry.py:53-83). The random `--cite-sample 12 --seed 515` reported 6144/6144 citations resolving. Its sample landed outside this group (kernels and bindings) and needed no further review.

Coverage of entry points: speculative decoding (`wr-spec-decode-step`), PP (`wr-pipeline-parallel-step`), config validation (`config-create-engine-config`) and worker death (`multiproc-executor.monitor-workers`, `engine-core-busy-loop`) are each modeled by an entity with real behavior, not one that only cites nearby lines. Spec-decode metrics are the exception: no entity models them.

## 3. Builder "docs versus code" findings

The merged model records no docs-versus-code finding for speculative decoding, TP/PP or worker death. This judge found these docs-versus-code differences:
- **P4(b):** the failure comes from ParallelConfig, not Ray or the executor.
- **P1(a/d):** V2 placeholders, and drafts are always K.
- **P2(b):** stop strings are matched in the detokenizer.

## 4. Simulator gaps

| Gap | Exposed by |
|---|---|
| No value-level model of logits or distributions: greedy-equivalence and distribution-preservation of rejection sampling can't be asserted | P3(a), P3(b), and in part P1(c) |
| A `kill` doesn't notify watchers. Mosaic has no process-sentinel or on-death hook that wakes a monitor task, so worker-death detection must be driven by calling the monitor by hand | P5(b) |

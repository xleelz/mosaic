# Blind judge: `scheduling-kv` (vLLM 0.32, benchmark 5)

**Cases 0 / 8 pass. Steps 12 / 37 pass** (Q5-1 4/5, Q5-2 0/4, Q5-3 0/5, Q5-4 0/4, Q5-5 0/5, Q5-6 3/5, Q5-7 1/4, Q5-8 4/5).
Step tally: 12 pass, 9 partial, 0 sim-gap, 10 missing, 6 fail.
Scenarios are in `judge5/scenarios/Q5-{1..8}.yaml`. A failing `expect` there is the verified outcome the model does not reproduce; none was weakened to pass.

## 1. Cases

Code paths are relative to the vLLM 0.32.0 root.

| Case | Case score | Step scores | Root cause | Evidence |
|---|---|---|---|---|
| Q5-1 speculative accounting | **partial** | a partial, b pass, c pass, d pass, e pass | **model**: `_spec_decode_step_blocks` and `reserved_blocks` are absent, so the "1 block" margin of (a) does not exist (`scheduler.py:347-357,1241-1251`) | `bench-q5-1-*`: `prompt_lookup_min` 3, 4 tokens and 3 drafts, lookahead 0; 400 + 7792 = 8192 with prefill drafts dropped; rollback to 34 computed, stats `[1, 0, 0]`; FP8 e2e gives `max_tokens` 2, clamp to 1, no drafts, `length`, 2 completion tokens; an empty draft is a plain decode with null stats |
| Q5-2 grammar and bitmask | **fail** | a partial, b missing, c fail, d partial | **model**: `scheduler.update-draft-token-ids` never validates; no bitmask rows, fill loop, rollback or `update_draft_token_ids_in_output` | `bench-q5-2-*`: (a) ids `[X, Y]` and drafts `[3, 0]` are right, but no 4096 x 4008 allocation and no 5 rows. (c) sync keeps `[t1, t2, t3]` and schedules 4, not 2; the async method does not exist. (d) `FINISHED_ERROR`, `finish_reason: error` and `generation-error` are right; `resumable` false and the log text are absent |
| Q5-3 pooling | **fail** | a missing, b fail, c fail, d partial, e fail | **model**: scheduler has no pooling path. **contract**: `async-llm.encode` sends `sampling_params` with no `pooling_params` and an e2e embedding never reaches the scheduler. **benchmark**: (e) corrected | `bench-q5-3-*`: (a) chunks 8192, 8192, 3616 and silent first steps are right, but a pooler output never finishes the request. (b) step 16 schedules 8191, ending at 131071 of 131072. (c) hit is 16000, not 19984, from a 1000-block cap. (d) resolved limits and one-step prefill are right; the pooling warning is absent. (e) the 400 refusal is right; `token_embed` still reads the cache |
| Q5-4 CPU offload | **missing** | a missing, b partial, c partial, d partial | **model**: `kv_offloading_size` is not resolved; `OffloadingConnector` falls into the `not-modeled` branch of `kv-connector-base-v1.get-num-new-matched-tokens` | `bench-q5-4-*`: (a) no resolved `KVTransferConfig`; only spec sizing works (4096 chunks). (b) `SimpleCPUOffloadConnector` reproduces the async hit of 992 and remainder of 8, but the deployed connector recomputes everything and no fetch-stage gauge exists. (c) queries 1000, hits 0 are right; external and by-source families are absent. (d) the outcome is right via the scheduler override only |
| Q5-5 residency metrics | **missing** | a missing, b missing, c missing, d missing, e missing | **model** and **world**: `vllm/v1/core/kv_cache_metrics.py` is uncited; no `kv-cache-metrics` or `kv-cache-metrics-sample` config id, so the scenario can't name the flag | `bench-q5-5-*`: only the 21-boundary `kv_cache_residency` bucket family exists (`bench-q5-5-a-buckets` passes). No histogram, collector, eviction event, sample-rate bound or collector reset |
| Q5-6 LoRA in the prefix cache | **fail** | a pass, b partial, c pass, d fail, e pass | **contract**: `openai-serving-models.load-lora-adapter` drops `load_inplace` before `async-llm.add-lora`. **model**: same-path warning absent | `bench-q5-6-*`: e2e model `sql` gets id 1, R2 hits 96; block keys carry name and path; v2 path hits 0; base model hits 0; reload after unload gets id 2 and hits 96. API in-place reload calls `load-adapter` once, so the worker keeps the old weights. Called directly, the worker manager is right |
| Q5-7 MoE capacity | **fail** | a partial, b missing, c pass, d fail | **model**: `kv-cache-utils.get-kv-cache-configs` checks profiled memory and applies the override afterwards (code applies it first, `kv_cache_utils.py:2611-2647`); capacity log and override log absent | `bench-q5-7-*`: 32768 bytes per layer per block, 1 MiB per block, 20000 blocks; rank1's lower memory sets the pool and both ranks' `initialize_from_config`. Override 1000 starts up instead of failing |
| Q5-8 watermark | **missing** | a pass, b pass, c pass, d pass, e missing | **model**: `watermark` bound `ge=0.0, lt=1.0` not enforced on any path | `bench-q5-8-*`: 157 free admits and 156 refuses, which pins 100 blocks; 150 free refuses, and admits with no watermark; one free block serves A's decode with no preemption; `has_scheduled_reqs` false skips it at 120 free; default 0 |

### Expectations verified against the code

Corrected:
- **Q5-3 (e)**: `POST /pooling` does accept `task`, but on the `--runner pooling` server of this case (pooling task `embed`) `token_embed` is refused with 400 `Try switching the model's pooling_task via --pooler-config.task token_embed. (parameter=task)` (`entrypoints/pooling/pooling/serving.py:77-89`). `skip_reading_prefix_cache` true (`pooling_params.py:126-134`) applies on a server started with that task.

Refined, score unaffected:
- **Q5-2 (d)**: confirmed the HTTP mapping: `finish_reason: "error"` raises `GenerationError("Internal server error")`, a 500 (`entrypoints/generate/base/serving.py:200-207`, `v1/engine/__init__.py:62`).
- **Q5-4 (b)**: the stage is `in_progress` once the request is held (`scheduler.py:1339`), after `waiting_to_start` at lookup (`scheduler.py:1083`). The 992-token hit (62 full blocks: 999 // 16, remainder 8) was traced on the simple connector; `OffloadingConnector._lookup` itself was not traced for chunk granularity.
- **Q5-8 (b)**: with the default `scheduler_reserve_full_isl` the refusal comes from the full-sequence check (`kv_cache_manager.py:522-540`), before the cited `:574-579`. Same arithmetic.

Confirmed as written, including the "judge: confirm" items: Q5-2 (c) EAGLE3 path (`v1/engine/core.py:801`); Q5-3 (b) `max_output_tokens=0` (`entrypoints/pooling/base/protocol.py:175-195`) and (c) the `num_tokens - 1` cap applies to pooling (`kv_cache_manager.py:295`); Q5-4 (c) host source (`v1/kv_offload/cpu/manager.py:201`); Q5-5 (d) (`block_pool.py:855-860`); Q5-7 (d) estimate 15984, the largest length with `cdiv(len, 16) <= 999` (`kv_cache_utils.py:2369-2395`).

Q5-6 (a-c, e) drive the scheduler with a literal `lora_request`, because `bench-q5-6-a-e2e` already proves the API-to-hash path for model `sql`.

## 2. Wrong claims in the model

1. `full-attention-manager.find-longest-cache-hit` caps a hit at 1000 blocks (`math.least([..., 1000])`, also `max: 1000`). The code has no such limit (`single_type_kv_cache_manager.py:784`). Every prefix hit above 16000 tokens is understated.
2. `scheduler.schedule` always clamps to `max-model-len - computed - 1`. The code subtracts `num_sampled_tokens_per_step`, which is 0 for pooling (`scheduler.py:150-159,713-720`). A max-length embedding never completes in the model.
3. `kv-cache-utils.get-kv-cache-configs` runs the memory check on profiled memory, then overrides. The code rewrites `available_memory` to the override first (`kv_cache_utils.py:2611-2647`), so a too-small override must fail startup.
4. `openai-serving-models.load-lora-adapter` omits `load_inplace` from the `lora_request` (`entrypoints/openai/models/serving.py:184-190` passes it), so an in-place reload never reaches the worker.
5. `scheduler.update-draft-token-ids` stores drafts unvalidated. The code calls `validate_tokens` (`scheduler.py:2565-2567`).
6. `scheduler.update-from-output` has no pooler branch (`scheduler.py:2170-2173` stops pooling on output), and `scheduler.add-request` reads `skip_reading_prefix_cache` only from sampling params (`v1/request.py:314-324` also reads pooling params).
7. `async-llm.encode` adds the request with `sampling_params: {max_tokens: 1, n: 1}` and no pooling params, so its description as the pooling counterpart of `generate` holds only for validation.
8. `structured-outputs-worker.apply-grammar-bitmask` passes `num_rows = size(structured_output_request_ids)`. The code's row count is `bitmask.shape[0]`, one per draft plus a bonus row (`v1/worker/gpu/structured_outputs.py:137-138`, `v1/structured_output/__init__.py:394-446`). Two requests give 2 in the model and 5 in the code.

### Citation spot check

`check --cite-sample 12 --seed 5`: all 11193 citations resolve; the sampled claims match their code, except that `moe-torch-bindings.moe-align-block-size` cites a nearby kernel (`csrc/moe/moe_align_sum_kernels.cu:387`), not the op registration (outside this group).

Read next to the code for this group's flows, and accurate: `kv-cache-manager.allocate-slots` watermark (`kv_cache_manager.py:509-516,573-579`); `scheduler.schedule` admission and draft steps (`scheduler.py:861-876,1271`); `scheduler.make-spec-decoding-stats` (`scheduler.py:2961-2978`); `spec-decoding-stats.observe-draft` (`spec_decode/metrics.py:18-49`); `scheduler.update-draft-token-ids` prefill branch (`scheduler.py:2560-2564`); `kv-cache-utils.request-block-hasher` LoRA keys (`kv_cache_utils.py:584-596`); `lru-cache-worker-lora-manager.add-adapter` (`lora/worker_manager.py:291-327`); the load path's id reuse (`entrypoints/openai/models/serving.py:176-181`); `generate-base-serving.raise-if-error` (`entrypoints/generate/base/serving.py:200-207`).

### Entry-point coverage

Not modeled by any entity, and uncited: `vllm/v1/core/kv_cache_metrics.py`, `vllm/distributed/kv_transfer/kv_connector/v1/offloading/scheduler.py`, `offloading/connector.py`, `get_kv_cache_capacity` and `update_kv_cache_capacity`, `Scheduler.update_draft_token_ids_in_output`, `StructuredOutputManager.grammar_bitmask` and `validate_tokens`. `scheduler.get-grammar-bitmask` models the call around `grammar_bitmask`, not its rows.

## 3. Builder findings

No "docs versus code" finding surfaced in the merged model's entities for this group, so none is confirmed or refuted. The builders' notes are off-limits under the blind rules.

## 4. Simulator gaps

None. No step scored sim-gap; every non-pass above is a model, contract or world cause. Tooling friction only: failed `expect` lines don't print the evaluated values, so Q5-3 (c)'s 16000 had to be found by bisecting with extra expectations.

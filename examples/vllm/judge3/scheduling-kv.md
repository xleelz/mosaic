# Judge 3: scheduling and the KV cache (`scheduling-kv`, Q3-1 to Q3-8)

The model was run as `examples/vllm/vllm.json`, with each case's scenarios in `judge3/scenarios/Q3-<n>.yaml`.
There were no mocks and no model edits. Code: vLLM v0.32.0 at `/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`.

**Result: 1/8 cases pass, 17/32 steps pass.**
- Q3-1: missing.
- Q3-2: pass.
- Q3-3: partial.
- Q3-4: fail.
- Q3-5: partial.
- Q3-6: partial.
- Q3-7: missing.
- Q3-8: missing.

## World correction that applies to the whole group

The benchmark states that the default engine args are `max_num_batched_tokens 2048, max_num_seqs 128`. That is
wrong for the deployed world. `vllm serve` with `UsageContext.OPENAI_API_SERVER` on a GPU with at least 70 GiB that
is not an A100 (the fixture's H100 80GB) resolves `max_num_batched_tokens=8192` and `max_num_seqs=1024`
(`vllm/engine/arg_utils.py:2933-2942,3112-3127`). 2048 and 128 are only the bare `SchedulerConfig` defaults. The
model's world (`max-num-batched-tokens` 8192, `max-num-seqs` 1024) is right. The benchmark's numbers in Q3-1, Q3-2,
Q3-3 and Q3-5 therefore hold only under an explicit `--max-num-batched-tokens 2048`. Every scenario passes that as
`config` (a real engine arg). Scenario `bench-q3-1-c-deployed` shows the deployed behavior: the lone 3000-token
prompt prefills in one step.

## 1. Cases

| ID | Verified expectation (corrected?) | Score | Steps | Root cause | Evidence |
|---|---|---|---|---|---|
| Q3-1 | (a) to (c) confirmed under `--max-num-batched-tokens 2048`: 512+512 tokens in step 1 (`scheduler.py:1155-1156`), 512 each in steps 2 to 5 (`:708-709`), 440+440 in step 6. A lone request is not capped because the threshold is zeroed when running+waiting ≤ 1 (`:640-649`), so it gets 2048 then 952. (d) confirmed: the adaptive floor is `max(512, 2048//2)` = 1024 (`:650-655`, `config/scheduler.py:86`). **Corrected world:** at the deployed 8192, (c) is 3000 in one step and (d) gives each request 3000 in step 1. | **missing** | a pass, b pass, c pass, d missing | model: there is no `long-prefill-token-threshold-adaptive` config, and `scheduler.schedule` "Long-prefill cap" (`scheduler.py:640-645`) leaves out the adaptive floor at `:650-655`. A scenario that names the config is refused (`unknown config`). | `bench-q3-1-a-b`, `bench-q3-1-c`, `bench-q3-1-c-deployed` pass |
| Q3-2 | (a) and (b) confirmed: W1 needs 550 blocks against 499 free, the full-ISL gate refuses it (`kv_cache_manager.py:522-539`), and the waiting loop `break`s, so W2 is not admitted. (c) **corrected**: the flag is `--no-scheduler-reserve-full-isl` (`arg_utils.py:1761`). W1 is admitted with a 2047-token chunk, and its 4th chunk can't get blocks, so it preempts itself as `running[-1]` (`scheduler.py:797-848`). Its prefill KV is *not* discarded: its 383 full blocks stay cached. Re-admission still needs 511 blocks, because cached hits with ref_cnt 0 count as blocks to allocate, and only 499 are free. W1 (and W2 behind it) therefore waits until A frees blocks. (d) confirmed: the watermark is `int(0.1*1000)`=100 blocks and applies only to WAITING/PREEMPTED requests while `self.running` is non-empty (`kv_cache_manager.py:208,509-516`). It also applies inside the full-ISL check. A running request's own chunk or decode allocation is exempt. | **pass** | a pass, b pass, c pass, d pass | none (benchmark: (c) wording, and the default budget) | `bench-q3-2-ab`: 499 free, W1 refused by the full-ISL note, no `allocate-slots` call for W2. `bench-q3-2-c`: W1 is admitted at 2047 and appears in `preempted_req_ids` at s8, its state resets to 0, and s9 doesn't re-admit it. `bench-q3-2-d` and the control: A's 900 blocks are admitted on an idle engine, W2 is held with 99 free, and W2 is admitted when the watermark is 0. |
| Q3-3 | (a), (b) and (d) confirmed (`scheduler.py:776-848,899`; `block_pool.py:793-802`; `stats.py:146-151,576-577`). (c) **corrected nuance**: under async scheduling, a preempted request that still has undelivered in-flight output is deferred until that stale output drains (`scheduler.py:934-938,1596-1606`). In the busy loop it drains before the next schedule, so C is still admitted before W, with 96 hits. C recomputes `num_tokens-96`: 4, or 5 if the in-flight token is appended on delivery. The scenario uses a 100-token C (6 hashed blocks plus a 4-token partial block), which matches the case's block layout. | **partial** | a pass, b pass, c pass, d partial | model: the `vllm:num_preemptions` Prometheus counter is not modeled (IterationStats PREEMPTED events, `loggers.py:1259`). The SchedulerStats preempted-prefix branch is right. The stale-output deferral is not modeled, but it doesn't change this case's outcome. | `bench-q3-3`: C is preempted, `{a:1,b:1}` are scheduled, and the waiting pass is skipped (note). A's new block is C's freed 7th block. After B finishes, C (4 tokens) is admitted ahead of W (16). `prefix_cache_stats.preempted_hits` is 96 and `hits` is 0. |
| Q3-4 | All confirmed (`sampling_params.py:622-629`, `request.py:314-325`, `kv_cache_manager.py:249-256,286-287`, `completion/protocol.py:373-375,552-557`). A skipped lookup also records no prefix-cache stats at all (`kv_cache_manager.py:253-256`). | **fail** | a fail, b pass, c fail, d fail | model: `scheduler.add-request` never derives `skip_reading_prefix_cache` from `prompt_logprobs`, and `scheduler.schedule` never passes it to `get-computed-blocks`. The request therefore hits 96 instead of 0 and adds 100 queries. Serving doesn't map echo+logprobs to `prompt_logprobs`, and doesn't reject `prompt_logprobs` with `stream`: it returns 200 SSE and reaches the engine. | `bench-q3-4-a` fails (r1 scheduled 4, not 100), `-b` passes, `-c` fails (no `prompt_logprobs` on the engine request), `-d` fails (status ok, `async-llm.generate` called) |
| Q3-5 | All confirmed (`scheduler.py:1314-1318`, `kv_cache_manager.py:253-262`, `block_pool.py:877-888`, `loggers.py:1150-1172`). | **partial** | a to d partial | model: the SchedulerStats values are exactly right: queries +100/+0, then +100/+96, nothing for the held request, which counts as waiting; usage is 0.007, and 0.0 with 6 cached blocks. The Prometheus side (`vllm:prefix_cache_queries`/`hits`, `vllm:kv_cache_usage_perc`, `vllm:num_requests_waiting`) is not modeled: `stat-logger-manager.record` only increments `vllm:generation_tokens` and `vllm:request_success`. | `bench-q3-5` passes on `scheduler.make-stats` |
| Q3-6 | All confirmed (`routers.py:40-43`, `dev/cache/api_router.py:20-44`, `block_pool.py:837-856`, `scheduler.py:2850-2875`). **Confirmed (d):** these preemptions *are* counted in `vllm:num_preemptions`, because `_preempt_request` records a PREEMPTED event (`scheduler.py:1609-1610`, `stats.py:576-577`) and is called with `drop_stale_output=True`. | **partial** | a pass, b pass, c pass, d partial | model: `scheduler.reset-prefix-cache` doesn't drop stale in-flight output, doesn't clear `prev_step_scheduled_req_ids` (`scheduler.py:2860-2866`), and has no preemption counter. (c) has no warning log text, only a note. | `bench-q3-6-a` 404. `-b` `{success:true}` and the next identical prompt computes 100. `-c` `{success:false}`, 6 blocks stay cached, the request keeps decoding. `-d` preempts b then a, the reset succeeds, both resume with 0 hits (`preempted_requests` 2). |
| Q3-7 | All confirmed (`scheduler.py:889-897,904-910,938-949,1393-1395`). (d): SchedulerStats is `num_waiting_reqs = waiting - deferred` = 0 and `num_skipped_waiting_reqs` = 1 (`scheduler.py:2944-2948`). The gauges are total 1, `capacity` 0, `deferred` 1 (`loggers.py:1150-1160`). | **missing** | a pass, b pass, c pass, d missing | model: there is no `deferred_waiting` set and no `num_skipped_waiting_reqs`. `scheduler.make-stats` returns `num_waiting_reqs` 1 and has no reason split. | `bench-q3-7-abc` passes: s2 `{a:1,c:40,d:40}`; B is held through s3 and s4 (D keeps it out after A finishes) and admitted at s5. `bench-q3-7-d` fails. |
| Q3-8 | All confirmed (`encoder_cache_manager.py:340-361`, `scheduler.py:271-274,1866-1941`). | **missing** | a to d missing | model: `scheduler.schedule` has no encoder-input scheduling (`_try_schedule_encoder_inputs`), requests carry no mm features, and nothing computes the encoder budget or cache size. `encoder-cache-manager.*` exists but no flow calls it. | `bench-q3-8-b` fails: P1 gets 2048, not 1608, and `can-allocate` is never called. `bench-q3-8-unit` passes: the standalone manager refuses image 3 with 448 left. |

**3 expectations were corrected:** Q3-1 (the default budget), Q3-2 (c), and Q3-3 (c) under async. Q3-6 (d) and
Q3-7 (d) were "judge: confirm" items, and both are confirmed.

## 2. Wrong claims in the model

1. `scheduler.make-stats` cites `scheduler.py:2915-2959` but returns `num_waiting_reqs: size(state.waiting)`, with no
   `num_skipped_waiting_reqs`. The code subtracts `deferred_waiting` (`:2944-2948`).
2. Prompt logprobs never bypass the cache. `kv-cache-manager.get-computed-blocks` declares `skip_reading_prefix_cache`
   (citing `kv_cache_manager.py:286-287`), but nothing sets it: `scheduler.add-request` and `scheduler.schedule`
   ignore `sampling_params.prompt_logprobs` (`sampling_params.py:622-629`). `kv-cache-manager.record-prefix-cache-stats`
   (citing `kv_cache_manager.py:253-262`) records stats for requests that skipped the lookup, which the code refuses
   (`:254-255`).
3. `scheduler.schedule` cites `scheduler.py:591-1556` as the whole step, but it leaves out three things:
   - encoder-input scheduling and the encoder compute budget (`:729-747,1153-1167`, `_try_schedule_encoder_inputs`);
   - the adaptive long-prefill floor (`:650-655`);
   - the async stale-output deferral and the `kv_holding_waiting` queue (`:925-938`).
4. `engine-core.reset-prefix-cache` drops `reset_connector`, so `?reset_external=true` never reaches
   `scheduler.reset_connector_cache` (`core.py:871-876`, `scheduler.py:2876-2877`).
5. `scheduler.preempt-request` (citing `scheduler.py:1571-1614`) leaves out `encoder_cache_manager.free`, the
   stale-output bookkeeping and the PREEMPTED event.
6. Outside the group, from the random citation sample (seed 4417): `gpu-worker-impl.determine-available-memory`
   claims "bytes one KV block takes across all layers" but cites `gpu_worker.py:837-838`, which is
   `get_kv_cache_spec`.

I also checked these citations, and they are faithful:
- `allocate-slots`: full ISL (`:522-540`) and watermark (`:509-516`);
- `block-pool.free-blocks`: front and back ordering (`block_pool.py:793-802`);
- `block-pool.reset-prefix-cache` (`:837-845`);
- `block-pool.get-usage` (`:877-888`);
- the running-loop preemption and the skip of the waiting pass (`scheduler.py:776-848,899`);
- the max_loras skip (`:940-951`);
- `scheduler.reset-prefix-cache` preempting in reverse order (`:2850-2866`).

## 3. Builder findings in this group

- **Confirmed:** "`max-num-batched-tokens` deployed 8192 differs from the SchedulerConfig default 2048" and
  "`max-num-seqs` deployed 1024 differs from the default 128" (`arg_utils.py:2933-2942`). This refutes the benchmark's
  world premise.
- **Confirmed:** "long_prefill_token_threshold is ignored when only one request is eligible" (`scheduler.py:640-649`).
- **Confirmed:** `scheduler_reserve_full_isl` defaults to true and checks the whole prompt
  (`config/scheduler.py:190`).
- **Confirmed:** the watermark applies only when some request is already scheduled (`kv_cache_manager.py:509-516`).

## 4. Simulator gaps

None found. Every non-pass comes from the model: missing entities or wiring (the adaptive config, prompt-logprobs
skip, deferred stats, encoder scheduling, Prometheus export). Mosaic could express all of them with the existing
step language, config and state.

# Judge 2: scheduling and the KV cache (`scheduling-kv`, Q1–Q8)

Blind re-measurement of `examples/vllm/vllm.json` against vLLM v0.32.0 code
(`/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`). Scenarios: `judge2/scenarios/Q1.yaml` … `Q8.yaml`,
run with `go run ./internal/devtools/check -f examples/vllm/vllm.json -f examples/vllm/judge2/scenarios/<Q>.yaml --no-mocks -v --trace`.

**Result: 6 pass, 1 partial, 1 missing (cases); 21 / 24 steps pass.**

## Deployed configuration (verified before scoring)

The fixture's `vllm serve` on one H100 80GB with no overrides does not run with the
`SchedulerConfig` class defaults that the benchmark assumes. `EngineArgs.get_batch_defaults` picks
`max_num_batched_tokens = 8192` and `max_num_seqs = 1024` for `UsageContext.OPENAI_API_SERVER` on a GPU
with at least 70 GiB that isn't an A100 (`vllm/engine/arg_utils.py:2932-2941`, applied at `:3112-3127`).
The defaults of 2048 and 128 apply only to the bare `SchedulerConfig`. The model's configs (`max-num-batched-tokens` 8192
and `max-num-seqs` 1024) match the code. Q1 and Q2 are corrected for this. Their original arithmetic is
also run with explicit `--max-num-batched-tokens 2048` (and `--max-num-seqs 128`) overrides.

## 1. Cases

| ID | Verified expectation (corrected?) | Score | Root cause | Evidence |
|---|---|---|---|---|
| Q1 | **Corrected.** (a) In the deployed world (budget 8192), step 1 schedules the 10 decodes (running pass first, 1 token each) and then **all 6000** prompt tokens (6010 ≤ 8192). The first token comes from step 1, and `num_computed_tokens` reaches 6000 after one step. With `--max-num-batched-tokens 2048`, the original arithmetic holds: (b) 2038 / 2038 / 1924. (c) Partial chunks sample nothing, and the first token comes from step 3. (d) `num_computed_tokens` reads 2038, 4076 and 6000. Code: `scheduler.py:657-858` (running first), `:1125-1169` (chunk to the budget), `:1616-1648` (advance computed). | **pass** (a–d) | benchmark (deployed budget). A contract defect sits beside this case; see wrong claim W2 | `bench-q1-deployed`, `bench-q1-budget-2048` (scheduler level), `bench-q1-engine-step-2048-tokens` (end to end through `engine-core.step` → `executor.execute-model` → `scheduler.update-from-output`: chunks [2038, 2038, 1924], no output for `big` in steps 1–2, one token in step 3) |
| Q2 | **Corrected.** (a) Deployed (8192 / 1024): step 1 admits all 200 prompts (4000 tokens), and (b) none wait. With 2048 / 128: 102 full prefills plus an 8-token chunk of the 103rd, with 97 waiting. (c) Step 2 finishes the chunk (12 tokens) and admits 25 more, reaching 128 running. After that, `num_running >= max_num_active_reqs` stops admission (`scheduler.py:920-924`). | **pass** (a–c) | benchmark (deployed limits) | `bench-q2-deployed`, `bench-q2-budget-2048-seqs-128` (the note "max_num_seqs requests already running" is in the trace) |
| Q3 | Confirmed. With `--no-enable-chunked-prefill` and an explicit 2048 < `max_model_len` 8192, `SchedulerConfig.verify_max_model_len` raises a `ValueError` (`config/scheduler.py:314-326`) inside `create_engine_config`, before any engine core or API server exists. If the budget isn't set explicitly, EngineArgs raises it to `max_model_len` instead (`arg_utils.py:3135-3144`). | **pass** | — | `bench-q3-create-engine-config` and `bench-q3-vllm-serve` (`console-scripts.vllm` fails at `scheduler-config.verify-max-model-len`, and `engine-core.init` is never called). A control run with chunked prefill on is accepted. |
| Q4 | Confirmed. (a) FCFS victim = `running[-1]`. When that is the requester, it is preempted and not scheduled (`scheduler.py:795-848`), and no waiting request is admitted in that step (`:900`). (b) `_preempt_request` frees the blocks, sets the status to `PREEMPTED` and `num_computed_tokens` to 0, and calls `prepend_request` (deque `appendleft`) (`:1571-1614`, `request_queue.py:92-94`). (c) The request resumes as a prefill over `num_tokens` (prompt plus output), shortened by prefix hits. (d) `num_preemptions` increases by 1, and the output is not duplicated. | **pass** (a–d) | — | `bench-q4-preempt-last` (allocation order A then B; B self-preempted; waiting = [B, C]; B's cached blocks appended to the free tail in reverse), `bench-q4-resume-recompute` (hit 496, schedules 1 token, the next output is `[2018]`, 18 output tokens in total), `bench-q4-resume-cache-off` (recomputes all 497) |
| Q5 | Confirmed. (a) The victim is `max(running, key=(priority, arrival_time))`. (b) If the victim was scheduled earlier in this step, its tokens and blocks are returned (`scheduler.py:803-820`). (c) The requester then allocates. | **pass** (a–c) | — | `bench-q5-priority-victim` (allocate-slots order a, b, b; preempted [a]; b gets block 63; total 1; the "Give back" note), `bench-q5-priority-tie-arrival` |
| Q6 | Confirmed. (a) `PriorityRequestQueue` is a heap on `Request.__lt__` = (priority, arrival_time, request_id) (`request.py:357-367`). (b) The waiting pass never preempts; when allocation fails it just stops (`scheduler.py:1275-1282`). (c) The waiting request is admitted first once blocks free. | **pass** (a–c) | — | `bench-q6-priority-arrival-waits` (peek returns p0, allocation fails, no `preempt-request` calls; after a finish, admission order is [p0, wait-c]) |
| Q7 | Confirmed. (a) Only full blocks are hashed. Each hash chains the parent hash, the tokens and extra keys (LoRA, multimodal, `cache_salt`) (`kv_cache_utils.py:625-657, 976-995`). (b) A 40-token prompt gets a 32-token hit. (c) The hit is capped at `num_tokens - 1` (`kv_cache_manager.py:289-300`), so a 48-token prompt also hits 32 and recomputes 16. | **partial** (a partial; b, c pass) | model: the block hash has no extra keys (W1) | `bench-q7-prefix-hits` (hits [0, 32, 0, 32], `max_length` 47, 5 cached hashes) |
| Q8 | Confirmed. (a) A different `cache_salt` gives no sharing: the salt is an extra key of the first block, and the chain carries it on (`kv_cache_utils.py:647-650`). (b) A different LoRA gives no sharing (`:578-595`). (c) `free_blocks` prepends uncached blocks and appends cached ones, freeing a request's blocks tail first (`single_type_kv_cache_manager.py:588-589`, `block_pool.py:774-803`). `get_new_blocks` pops from the head and evicts the hash (`:666-689, 729-745`). | **missing** (a, b missing; c pass) | model: no `cache_salt` and no LoRA in the request or the hasher | `bench-q8-lru-eviction` passes: r2 gets [4, 5, 6, 7, 3], evicting r1's tail block 3 (1 evicted hash), and r1's prompt then still hits blocks 1 and 2. `bench-q8-cache-salt-isolation` and `bench-q8-lora-isolation` assert the code's outcome and **fail**: the model hits 32 tokens across salts and adapters. |

Steps: Q1 4/4, Q2 3/3, Q3 1/1, Q4 4/4, Q5 3/3, Q6 3/3, Q7 2/3, Q8 1/3 = **21 / 24**.
Expectations corrected: **2 cases (Q1, Q2; 7 steps)**, both for the deployed batch limits.

## 2. Wrong claims in the model

- **W1. The block hash drops extra keys.** `kv-cache-utils.request-block-hasher` describes itself as a
  "Stand-in for sha256 over (parent hash, block tokens, extra keys)". It cites
  `kv_cache_utils.py:954-998`, where `generate_block_hash_extra_keys` adds LoRA name and path,
  multimodal hashes and `cache_salt` (`:625-657`). The stand-in hashes segment keys and output tokens only.
  `SchedKvRequest` has no `cache_salt` or `lora_request`, and nothing in any fragment mentions
  `cache_salt`. So tenants and adapters share KV blocks in the model but not in the code (Q8a and Q8b fail
  in the run).
- **W2. Contract seam: `SchedulerOutput.scheduled_new_reqs` carries no prompt length or `prefill_token_ids`.**
  The scheduler emits `{req_id, prompt_token_ids, block_ids, num_computed_tokens, sampling_params}`. The code's
  `NewRequestData.from_request(req, ..., req._all_token_ids)` (V2 runner, `scheduler.py:1418-1428`; `sched/output.py:54-81`) carries the prefill tokens.
  For a prompt given as `prompt_segments` (the scheduler area's own long-prompt device, used by its
  fixtures), `prompt_token_ids` is null, and the worker-runner falls back to `prefill_len = num_computed + scheduled`
  (`worker-runner` add-request, "A prompt given as segments …"). So the first 2038-token chunk of a 6000-token prompt is
  treated as final. It samples a token, and the natural-length EOS then finishes the request after step 2
  (`bench-q1-segments-seam` fails). A resumed request under the V2 runner is also given `prefill_len =`
  the prompt only, not prompt plus output. With real token ids, the end-to-end path is correct.
- **W3. `engine-args.create-engine-config` hard-codes `policy: fcfs`** in its call to `scheduler-config.post-init`.
  The code passes `policy=self.scheduling_policy` (`arg_utils.py:2617-2630`). The scheduler reads the
  `scheduling-policy` config directly, so scheduling decisions are unaffected, but `--scheduling-policy priority` never
  reaches the modeled SchedulerConfig.

Citations checked (12, all accurate): `scheduler.py:795-802, 813-820, 842-848, 920-924, 1158-1167, 1275-1282, 1616-1648, 2616-2647`;
`block_pool.py:687-689, 793-803`; `kv_cache_manager.py:522-540, 573-579`; `kv_cache_utils.py:976-995`. The last one is cited correctly, but the
behavior that cites it omits the extra keys the cited lines compute (W1). `--cite-sample 12 --seed 3107` drew 2 citations in this
group (`scheduler.py:1584-1586`, `:813-820`), and both are accurate. Every covered entry point (`schedule`, `add_request`, `_preempt_request`,
`update_from_output`, `finish_requests`, `allocate_slots`, `get_computed_blocks`, `free_blocks`, `get_new_blocks`, the request queues)
is modeled by an entity with behavior, not just a citation.

## 3. Builder findings ("docs versus code")

- `max-num-seqs` deployed 1024, not 128, and `max-num-batched-tokens` deployed 8192, not 2048 (H100, OPENAI_API_SERVER): **confirmed**
  (`arg_utils.py:2932-2941`). The builders' note that an A100 gets 256 / 2048 is also confirmed (`:2943-2951`).
- `async-scheduling` resolves from None to True: **confirmed** (`config/vllm.py:1585-1644`).
- `use_v2_model_runner` true, with resumed requests sent as new requests: **confirmed** (`scheduler.py:1418-1428`). The data those requests carry is incomplete, though (W2).
- `scheduler_reserve_full_isl` defaults to on, and admission checks the whole prompt: **confirmed** (`kv_cache_manager.py:522-540`).

## 4. Simulator gaps

None blocked a case. Every scored step was driven with fixtures, state, config and steps.
- Tooling (not the simulator): `devtools/check` can't print a step's result value. To see why an
  end-to-end run differed (W2), I had to run a private `mosaicd` and use `mosaic sim run --format json`.
- Not exercised: the end-to-end Q1 run used `async-scheduling: false` (`engine-core.step`). The deployed async path
  (`step_with_batch_queue`) lags outputs by one step and wasn't scored end to end. Scheduler-level Q1 and Q2 ran with the deployed async setting.

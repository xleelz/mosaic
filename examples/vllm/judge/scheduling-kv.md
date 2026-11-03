# Judge: scheduling-kv (K1–K8)

Model: `examples/vllm/vllm.json` (merged). Code: vLLM v0.32.0 at `/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`.
Scenarios: `judge/scenarios/K1.yaml` … `K8.yaml` (14 scenarios, no mocks, no model edits). Run:

```sh
go run ./internal/devtools/check -f examples/vllm/vllm.json $(for f in examples/vllm/judge/scenarios/K*.yaml; do echo -f $f; done) --no-mocks -v --scenario '^bench-k'
```

Result: 13 pass, 1 fails on purpose (`bench-k7-no-hashing`, which records a model defect).

The scenarios drive the scheduler seams that engine-core calls (`scheduler-add-request`,
`scheduler-schedule`, `scheduler-update-from-output`, `scheduler-make-stats`) on the merged worlds
(`full-tp1-llama-8b`, `full-small-batch-limits`, `full-prefix-caching-off`). They interleave
schedule/update as the async engine loop does. Small KV pools come from `config:
{num-gpu-blocks-override: N}` plus the matching `block-pool.num_gpu_blocks` state, which is what the
override produces at startup (`kv_cache_utils.py:1230`).

## Deployed configuration (verified)

| setting | benchmark says | code / deployment |
|---|---|---|
| max_num_batched_tokens | 2048 | **8192**. `vllm serve` (OPENAI_API_SERVER) on an 80 GiB H100 (`device_memory >= 70 GiB`, not A100): `vllm/engine/arg_utils.py:2933-2941`, applied at 3112-3121. 2048 is only the class default (`config/scheduler.py:41`) |
| max_num_seqs | 128 | **1024** (same table, `arg_utils.py:2938-2941`, applied 3123-3127) |
| async scheduling | (unstated) | **on**: `config/vllm.py:1585-1644` resolves None to True. AsyncScheduler is used |
| scheduler_reserve_full_isl | (unstated) | true (`config/scheduler.py:190`). Admission checks that the whole prompt fits |
| model runner | (unstated) | V2 (`config/vllm.py:703-738`). Resumed requests go out in `scheduled_new_reqs` (`scheduler.py:1418-1420`) |

## 1. Cases

| ID | Verified expectation (corrected?) | Score | Root cause | Evidence |
|---|---|---|---|---|
| K1 | Confirmed. A request added between steps is admitted in the next `schedule()`, which handles RUNNING requests first (`scheduler.py:657-858`) and then WAITING ones (911-1371). A request that stops in `update_from_output` is freed and removed from `running` right away (`scheduler.py:2224-2230, 2293-2296`). The next step reports it in `finished_req_ids`. | **pass** | – | `bench-k1`: s2 = {r1: 1 (cached req), r2: 7 (new req)}. r1's EOS in u2 frees it (`kv-cache-manager.free` [r1]). s3 = {r2: 1} with `finished_req_ids == [r1]`. allocate-slots order and status: r1/WAITING/5, r1/RUNNING/1, r2/WAITING/7, r2/RUNNING/1 |
| K2 | **Corrected.** The deployed budget is 8192, so a 5000-token prompt prefills in **one** step (313 blocks). With `--max-num-batched-tokens 2048` the prompt is chunked, and RUNNING requests are served first. That includes decodes and the in-progress chunk itself, in running order, not "decodes" as a class. A running decode takes 1 token, so the chunks are 2047, 2047, 906 (`scheduler.py:657-721, 1125-1169`). Partial chunks emit no output. | **pass** | benchmark (budget) | `bench-k2-deployed-budget`: {long: 5000}. `bench-k2-chunked-2048`: s1–s3 = {dec 1, long 2047 / 2047 / 906}. allocate-slots order is dec before long in every step, with long WAITING then RUNNING. u1 and u2 have no output for long; u3 delivers its first token |
| K3 | Confirmed, with the value corrected to 1024 deployed. The waiting pass stops when `len(running) >= max_num_active_reqs` (= max_num_seqs, `scheduler.py:129-136, 920-924`). The others stay WAITING and are admitted once a slot frees. | **pass** | benchmark (value 128 → 1024) | `bench-k3` on `full-small-batch-limits` (max_num_seqs 2): r3 waits two steps, although the budget was not the limit (8 of 64 tokens). The "max_num_seqs requests already running" note fires twice. r3's first prefix lookup happens only in s3, after r1 finished |
| K4 | Confirmed. The hit comes from `get_computed_blocks` → `find_longest_cache_hit`, capped at num_tokens−1 (`kv_cache_manager.py:263-300`). Blocks are cached when they are allocated (`kv_cache_manager.py:607-616`), so a request admitted later in the **same** step already hits them. If the second prompt is exactly the 512 cached tokens, the hit is 496, not 512. | **pass** | – | `bench-k4`: r2 has num_computed_tokens 512 and schedules 60 tokens. Its block_ids[0:32] are r1's, and its 4 new blocks are fresh. Prefix stats show 512 hits. allocate-slots gets new_computed_blocks=32 and num_new_computed_tokens=512. `bench-k4-same-step` and `bench-k4-prompt-equals-prefix` (496) also pass |
| K5 | Confirmed and refined. When `allocate_slots` fails for a RUNNING request, FCFS preempts `running[-1]` (the last admitted; it can be the request itself) and loops until the request fits (`scheduler.py:776-848`). `_preempt_request` frees the blocks, sets num_computed_tokens=0 and status PREEMPTED, and prepends the request to waiting (1571-1614). No WAITING request is admitted in a step that preempted (899). There is no swap. On resume, the victim's full blocks that survived in the prefix cache are reused, so only the remainder is recomputed. | **pass** | – | `bench-k5` (8 usable blocks): s3 preempts r2 (`preempt-request` [r2]), r1 gets one block and the waiting pass is skipped. After r1 finishes, s4 resumes r2 with num_computed_tokens **48**: its tail block (hash @64) was evicted when r1 took a block, and 3 cached blocks survived. It schedules 17 tokens and makes no swap calls |
| K6 | **Corrected (refined).** n tokens hold ceil(n/16) blocks. On finish, blocks are freed in reverse order (`single_type_kv_cache_manager.py:581-589`). Only **full, hashed** blocks stay in the prefix cache, appended to the LRU tail and evictable. The partial last block has no hash: it goes to the **front** of the free queue for LIFO reuse and is not cached (`block_pool.py:774-803`). | **pass** | benchmark (partial block isn't cached) | `bench-k6`: a 40-token request gets [1,2,3] and a 1000-token one gets 63 blocks. After both finish, KV usage is 0, free_front=[3], free_tail is 62 cached blocks (65 first), and 'doc-k6@40' was never cached. A later request reuses blocks 1 and 2 (32 tokens) and gets the LIFO block 66 |
| K7 | Confirmed. With prefix caching off, `get_computed_blocks` returns no hit (`kv_cache_manager.py:288-289`). Code path: no block hasher is built (`v1/engine/core.py:231-238`), `cache_blocks` is a no-op (`kv_cache_manager.py:782-792`), and freed blocks are LIFO-reused (`block_pool.py:793-795`). | **partial** | **model** | `bench-k7` passes: r2 computes all 572 tokens, both lookups return 0, there are no get-cached-block or touch calls, and r2 is given r1's freed physical blocks 39…4 (LIFO). `bench-k7-no-hashing` **fails**: the model still hashes every prompt block (`scheduler.add-request` → `kv-cache-utils.request-block-hasher`), and its async path in `scheduler.update-from-output` calls `full-attention-manager.cache-blocks` directly. That bypasses the `enable_caching` guard, so `block-pool.cached` and `block_hash` fill up while caching is off. No lookup reads them, so the outcome is right but the state and path are wrong. The fix is to guard both calls on `config['enable-prefix-caching']` |
| K8 | Confirmed and refined. WAITING order is `Request.__lt__` (priority, arrival_time, request_id) on a heap (`request.py:357-367`, `request_queue.py:132-157`). The victim is `max(running, key=(priority, arrival_time))` (`scheduler.py:795-799`), wherever it sits in `running`. If the victim was already scheduled this step, its tokens are returned (813-820). Preemption is triggered **only** by a RUNNING request that fails to allocate. A newly arrived high-priority request never preempts (the only preemption sites are 836 and 2860). If the victim is the requester itself, the running pass ends (842-848), so later running requests wait a step. | **pass** | – | `bench-k8-admission`: hi (prio 0, later arrival) is admitted before lo through `priority-request-queue.peek-request`. `bench-k8-preempt` (running order mid, lo, hi): lo is preempted, not hi (which FCFS would pick), and s5 = {mid 1, hi 1}. `bench-k8-self-preempt`: lo preempts itself, s3 schedules 0 tokens, and the "Preempted itself" note fires |

## 2. Wrong claims in the model

1. **The prefix cache fills while it is disabled** (K7). `scheduler.update-from-output` ("Async - cache
   the blocks the new tokens completed", citing `async_scheduler.py:73-77`) calls
   `full-attention-manager.cache-blocks` directly. The code calls `KVCacheManager.cache_blocks`,
   which returns at once unless `enable_caching` is set (`kv_cache_manager.py:782-792`). The guard
   exists on the `allocate-slots` path (`interfaces_kv.yaml:469`) but not on the async path.
2. **Block hashes are computed with prefix caching off** (K7). `scheduler.add-request` ("Hash the prompt's
   full blocks", citing `kv_cache_utils.py:954-998`) always calls `kv-cache-utils.request-block-hasher`. In
   code, `request_block_hasher` is `None` unless prefix caching or a KV connector is on
   (`v1/engine/core.py:231-238`), so `Request.block_hashes` stays empty. The same applies to the rehash
   in `update-from-output` ("Hash newly full blocks").
3. No other wrong claim was found in the behaviors I read against the code: `scheduler.schedule` (all
   23 narrated steps), `kv-cache-manager.allocate-slots`, `get-computed-blocks`, `free`,
   `block-pool` free ordering, `scheduler.preempt-request` and `free-request`. The model's numbers
   (block ids, LIFO/LRU order, eviction of the victim's tail block, the 48-token resume) matched my
   hand computation from the code in every scenario.

Citation spot-check: `check --cite-sample 10 --seed 708` resolved 10/10, all accurate (none in this area).
5417/5417 citations resolve. I also checked 14 citations in this area by hand: scheduler.py 640-645,
657-659, 667-681, 776-845, 795-802, 842-848, 899-919, 920-924, 960-968, 1158-1167, 1275-1282,
1343-1371 and 1616-1648, plus kv_cache_manager.py 289-300 and 607-616. All are accurate. The two
wrong claims above are wrong by omission: the cited lines are right, but the guard is missing.

Entry-point coverage: the scheduler seams (`add-request`, `schedule`, `update-from-output`,
`finish-requests`, `make-stats`, `kv-cache-manager.*`, `block-pool.*`) are modeled by behaviors, not
just cited.

## 3. Builder "docs versus code" findings (notes/scheduler-kv.md §7)

| Finding | Verdict |
|---|---|
| Priority preemption happens only when a RUNNING request can't get blocks; the waiting loop never preempts | **Confirmed**: the only `_preempt_request` calls are at `scheduler.py:836` (running loop) and 2860 (reset_prefix_cache) |
| Any preemption in a step skips all waiting admissions | **Confirmed** (`scheduler.py:899`) |
| A fully cached prompt still recomputes its last block (hit capped at num_tokens−1) | **Confirmed** (`kv_cache_manager.py:289-300`). `bench-k4-prompt-equals-prefix` gives 496 of 512 |
| A preempted request restarts at num_computed_tokens=0 but reuses its own cached full blocks | **Confirmed** (`scheduler.py:1593`, then a prefix lookup on re-admission at 960). `bench-k5` resumes at 48 |
| `vllm serve` on an H100 uses 1024 / 8192, not 256 / 2048 | **Confirmed** (`arg_utils.py:2933-2941`) |
| Async scheduling is on by default | **Confirmed** (`config/vllm.py:1585-1644`) |

## 4. Simulator gaps

None was exposed by K1–K8. Each case was expressible with steps, config and state. One
limitation: the cases drive the scheduler seams directly rather than the engine-core busy loop,
because overlapping async steps (step N+1 scheduled before step N's output) are written as ordered
steps rather than as concurrent work. That is enough for the scheduler's decisions. The
engine-lifecycle group covers the loop itself.

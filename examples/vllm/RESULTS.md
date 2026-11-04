# vLLM 0.32 benchmark results

Can mosaic map a low-level GPU serving system (vllm-project/vllm at v0.32.0, the V1 engine)
correctly from code alone? This is the fourth repository, and the first built with every
pipeline improvement from the VS Code results:
- the in-build oracle (stage 4b);
- the `--lint trivial`, `--min-substantive` and `--max-trivial` gates;
- `covered_by` skip validation;
- generated worlds;
- `shared_data` owners;
- the engine additions made for it: microsecond time, `rendezvous`, the cooperative scheduler and
  cancellation tokens.

## The build

- **Setup:** 9 area agents (serving-api, engine-core, scheduler-kv, worker-runner, attention,
  distributed, models-layers, kernels-ops, config-platform) and one reconciliation round with 14
  binding decisions (`RECONCILE.md`).
- **Merged model** (`vllm.json`): 390 components, 1,727 interfaces, 164 flows and 894 scenarios.
- **The gate passed (`quality-gate.txt`):**

  | Check | Result |
  |---|---|
  | validation errors | 0 |
  | scenarios | 894 / 894 pass |
  | merge warnings | 0 |
  | hollow-lint failures | 0 |
  | mocks | 0 |
  | citations resolving | 5,417 / 5,417 |
  | behavior coverage | 96.4% |
  | entry points modeled | 90%, all substantive |
  | trivial entry interfaces | 1.4% |

- **In-build oracle:** each area translated 3 of its own tests before hand-off. Most pass, and the
  rest are recorded as untranslatable (kernel numerics, metrics metadata).
- **Engine work driven by this build** (DESIGN §13.1 items 16–17):
  - **Microsecond time:** a kernel is 5–120 µs, which all rounded to 0 ms before.
  - **`rendezvous`:** collectives are N calls, not N × N.
  - **CEL `now`:** always an integer, so its type is stable.
- **Fixture mistakes caught by the build:**
  - **Batch limits:** `vllm serve` on an H100 resolves to 1024 / 8192, not the class defaults of
    128 / 2048.
  - **KV blocks:** 28,488, not 2,000.
  - **Weights:** they were double-counted.
  - **Prompts:** a 64-token prompt cap.

## The test oracle (stage 6)

36 tests were sampled from vLLM's `tests/`, disjoint from the in-build samples.

| Verdict | Count |
|---|---|
| pass | 2 |
| model-bug | 17 |
| untranslatable (tensor numerics, kernel output, storage/bytecode internals, examples/tools scripts) | 17 |
| sim-gap / test-mismatch | 0 |

Of the 19 translatable tests, **2 pass (11%)**. VS Code was at 15%, despite far weaker gates
(24% trivial).

**The model bugs are mostly whole features never modeled, not thin behaviors:**
- KV connectors and offload (NIXL remote prefill, MoRIIO, SimpleCPUOffload, external computed
  tokens);
- hybrid and Mamba KV managers;
- pipeline-parallel sampling on non-last ranks;
- EPLB;
- structured outputs (regex and structural tags);
- data-parallel clients;
- multimodal and `prompt_embeds` chat parts;
- score and embedding paths;
- quantization and NVFP4 detection.

The new gates did their job inside what was modeled. But the inventory under-represents feature
breadth: scheduler-kv, the heart of vLLM, had 8 inventory entries.

## The benchmark (stage 7)

28 cases, written before the build and hidden from the builders. Four judges verified each
expectation against the code, then scored the model starting from the merged worlds.

| Group | Pass | Partial | Fail |
|---|---|---|---|
| Serving (V1–V8) | 5 | 1 | 2 |
| Scheduling and KV cache (K1–K8) | 7 | 1 | 0 |
| Execution and parallelism (X1–X6) | 3 | 3 | 0 |
| Engine lifecycle (E1–E6) | 3 | 1 | 2 |
| **Total (28)** | **18 (64%)** | **6** | **4** |

No case was missing, and none was a sim-gap.

**17 of 28 expectations were corrected against the code (61%):**
- the deployed batch limits (1024 / 8192);
- async scheduling is on by default (`step_with_batch_queue`, outputs one step late);
- the V2 runner returns None from `execute_model`, and `sample_tokens` produces the output;
- every TP rank samples, and only rank0 replies;
- prefill runs PIECEWISE CUDA graphs up to 512 tokens;
- the TP1 executor is in-process, while offline `LLM` uses a background engine process;
- the 400 error is `BadRequestError`, and a dead engine gives 503;
- only full hashed blocks stay cached;
- `n>1` fans out in `AsyncLLM.add_request` and shares only full prompt blocks.

### Cross-repo comparison

| | Cassandra r1 | Cassandra r2 | VS Code | vLLM |
|---|---|---|---|---|
| Benchmark pass | 30/44 (68%) | 37/44 (84%) | 14/40 (35%) | 18/28 (64%) |
| Oracle pass (translatable) | — | — | 5/33 (15%) | 2/19 (11%) |
| Trivial entry interfaces | — | 15.5% | 23.8% | **1.4%** |
| Substantive modeled | — | 87% | 63% | **90%** |
| Expectations corrected | 20/44 | (re-verified) | 20/40 | 17/28 |

Where an area was modeled in depth, the model matches the code well: scheduling and KV scores 7
of 8, with all 24 checked citations accurate and every builder finding confirmed. The failures
are concentrated in two kinds of place:
- paths the builders summarized: sampling params dropped on the chat route, `n>1` merging, the
  offline output order, output-rank-only replies, spec-decode verification;
- features never modeled at all (the oracle).

## What's wrong in the model (to fix)

| # | Area | Wrong claim |
|---|---|---|
| 1 | serving-api | The chat route passes only `max_tokens`, `n` and `temperature`: `stop`, `top_p`, `seed` and the stream flags are dropped (V7). A missing temperature defaults to 1.0 instead of the model's generation_config (0.6 / 0.9) |
| 2 | worker-runner, kernels-ops | `sampler.sample` returns a random token for every sampling type, so greedy isn't deterministic (V6). Stop strings spanning token boundaries are missed |
| 3 | engine-core | With `n>1`, children get separate collectors that never merge, so generate never finishes (E6). Offline outputs return internal ids and only the last step's tokens, are never sorted, and drop per-prompt params (E5). Executor shutdown only sets a flag (E4) |
| 4 | engine-core, worker-runner | `collective_rpc` waits for every rank, while the code reads only the output rank (`multiproc_executor.py:425-427`) (X2, X5) |
| 5 | scheduler-kv, worker-runner | The `max_model_len` capacity check is missing (`kv_cache_utils.py:2638-2647`), so it starts where the code raises (X3). Spec tokens are never scheduled or rolled back (X6). Prefix caching off still hashes and caches (K7) |
| 6 | all | Unmodeled features from the oracle (above) |

## Simulator gaps (ranked)

1. **Streaming responses:** a call can't yield values over time (V2, async generators everywhere).
2. **Blocking receive:** blocking on a queue or channel `get()` across tasks is missing, so busy
   loops are polls (E2).
3. **Process kill mid-call:** SIGKILL, and a worker crash during a step (E4, X5). `restart`
   covers only part of it.
4. **CEL cost limit:** prompts over about 500 tokens hit the cost limit (X4). Raise it or make it
   configurable per run.
5. **Value-level semantics:** no logits or tensor values, so greedy determinism and spec-decode
   output equality are choices (V6, X6). This is mostly out of scope by design. The model can
   still keep deterministic placeholders.
6. **Emit ordering:** an emit is delivered after the call tree, so loops started during startup
   appear late in traces (E1).
7. **From the build:**
   - `foreach` caps (1,000 per loop);
   - `entry.repeat` ignored inside steps;
   - null configs vanish.

## Pipeline lessons

1. **The new gates work.** Trivial behaviors went from 24% (VS Code) to 1.4%, and substantive
   modeling from 63% to 90%. The scheduling group scored 7 of 8.
2. **Gates measure the inventory, not the system.** The oracle still found mostly unmodeled
   features, and the entry-point inventory can't see them. Next steps:
   - add **test-weighted coverage** (the share of test files whose code under test is reached by
     a scenario);
   - add a **feature list** in the profile (from docs/config flags) that areas must each model or
     skip.
3. **Expectation corrections stay high (54–61%).** A benchmark written from docs is unreliable
   for fast-moving code (async scheduling, V2 runner and usage-context defaults all changed
   recently). Verifying each expectation against the code before scoring remains essential.

## Round 2 (fix round, `FIXES.md`)

The 9 areas fixed the wrong claims above and modeled the missing features. They used the new
engine primitives (DESIGN §13.1 item 18: streams, channels, kills) and the new gates (item 19:
`--tests`, `--features`). Every item in "What's wrong in the model" is fixed.

**The gate (`quality-gate.txt`) passes.**

| Check | Round 1 | Round 2 |
|---|---|---|
| Scenarios | 894 / 894 | 990 / 990 |
| Components / interfaces / flows | 390 / 1,727 / 164 | 418 / 1,807 / 187 |
| Citations resolving | 5,417 | 5,927 |
| Behavior coverage | 96.4% | 96.4% |
| Entry points modeled (substantive) | 90% | 90% |
| Trivial entry interfaces | 1.4% | 1.4% |
| Test files reached (`--tests`) | — (gate added this round) | **79%** (1,300 / 1,647) |
| Features (`--features`) | — | **28 / 28** |

**Scores.**

| | Round 1 | Round 2 |
|---|---|---|
| Benchmark (28 cases) | 18 pass (64%) | 27 pass, plus E6 (see below) |
| Oracle (19 translatable tests) | 2 pass (11%) | **19 pass** |

The re-score has three caveats:
- **The re-scorers weren't blind.** They re-scored after seeing the fixes, so this is less
  independent than round 1. They could edit only result paths and calls, never the asserted values.
  Their per-case reasons are in `judge/round2.md` and `oracle/round2.md`.
- **Drift is common.** The fix round reshaped interfaces, so 12 oracle and 5 judge scenarios
  needed only their call or result path adapted. For example, `generate` now streams, and
  non-streaming callers read the last of `items`. E2's idle check changed from "12 loop
  iterations" to "loop parked on an empty input channel", because the busy loop now blocks on
  `receive`.
- **Three expectations were wrong, and the code proved them wrong:**
  - **E6:** with the default CUMULATIVE kind, the parent stream returns only the current child,
    not all n (`parallel_sampling.py:117-121`). E6 passes now that one step's outputs merge
    before the consumer reads, but it holds only when both children finish in the same step.
  - **CPU-offload oracle:** the test asserts only that repeats give the same output
    (`test_integration.py:100-102`). An async CPU load parks the request
    (`scheduler.py:1320-1341`).
  - **DP-allowlist oracle:** the test calls `create_dp_placement_groups` directly
    (`test_dp_placement_node_allowlist.py:40-57`), not through engine-config creation.

**What the fix round surfaced.**
- **Making `generate` stream, as the code does, broke 28 scenarios across 3 areas.** That was the
  change working as intended: every caller that relied on the wrong, non-streaming shape surfaced
  at once. Each was routed to its owner and updated. A breaking change that makes an interface
  match the code is a finding, not a cost to avoid.
- **A busy loop that blocks on a channel exposed a missing world precondition:** probe scenarios
  ran on a fixture where the model was never loaded.
- **Wrong scenarios, not just wrong models:** pooling on a decoder-only Llama reports only embed
  tasks without `convert: classify`, and the Responses API's `max_output_tokens: 16` ends
  `incomplete`.

### Cross-repo comparison (updated)

| | Cassandra r2 | VS Code | vLLM r1 | vLLM r2 |
|---|---|---|---|---|
| Benchmark pass | 37/44 (84%) | 14/40 (35%) | 18/28 (64%) | 27–28/28 |
| Oracle pass (translatable) | — | 5/33 (15%) | 2/19 (11%) | 19/19 |
| Test files reached | — | — | — | 79% |

### Still open

- **Simulator gaps 5–7 above** (value-level semantics, emit ordering, `foreach` caps, `repeat` in
  steps, null configs).
- **Derived configs:** `fuse_act_quant` can't be written at run time.
- **21% of test files unreached:** mostly kernels, compile passes and multimodal processors.
- **A fresh, blind oracle sample** (disjoint from rounds 1 and 2), to measure the fix round
  without the re-scorers' bias.

## Round 3 (fix round, `FIXES3.md`) and the first blind measure

**The build.** 434 components, 1,853 interfaces, 197 flows, 1,021 scenarios, all passing; the full
gate passes. Debt: racy 0 of 299 store-writing behaviors (8 real races in vLLM, each cited
`racy_in_code`), unknown-inputs 0, clock-ids 0, unraised-errors 0, internal assertions 10.7%
(249 of 2,334). Exploration: 5 of 5 race/concurrency scenarios pass 20 schedules each. The
cross-level findings from the vLLM-under-gateway refinement are fixed: EOS ends requests,
request validation, and streaming only when the request asks (`streams_when`, DESIGN §17.12).

**The blind measure** (`BENCHMARK2.md`, `oracle2/`, `judge2/`; fresh agents that never saw the
builders' notes or earlier measures):

| Measure | Result |
|---|---|
| Benchmark, by step | **65 of 105** (62%): serving 13/37, scheduling-kv 21/24, execution-parallel 8/16, engine-lifecycle 23/28 |
| Benchmark, by case | 11 pass, 4 partial, 6 missing, 11 fail, of 32 |
| Test oracle | **2 of 36 pass**; 24 model bugs, 10 untranslatable (2 of the 26 translatable) |
| Expectations the judges corrected | 14 (serving 3, scheduling-kv 7 steps in Q1–Q2, execution 4, lifecycle 4) |

Round 2's 27–28/28 and 19/19 were measured on cases the builders had fixed against. The blind
numbers are the real baseline, as they were for the gateway platform.

**What's wrong.** Mostly coverage: pieces of vLLM the tests and the benchmark reach that the model
doesn't have. Then wrong behavior in what is modeled.

- *Serving:* completions forward only max_tokens and output_kind (stop, ignore_eos, min_tokens and
  the default 16 are lost); stop strings have no cross-token match, hold-back or
  include_stop_str_in_output; structured outputs aren't wired from serving; `llm.chat` takes one
  conversation; `/v1/completions` drops `n` and rejects a string prompt; `/health` is 200 during
  startup; routes answer before uvicorn serves; offline beam search, the inkling parser and Cohere
  role mapping are missing.
- *Scheduling and KV:* the block hasher omits LoRA, cache_salt and multimodal keys; the scheduler
  output lacks prompt length, so segmented prompts sample mid-prefill; `policy: fcfs` is
  hard-coded; Mamba/EAGLE cache hits only on the block grid; the encoder cache and CPU-offload
  sizing are missing.
- *Execution:* `take-draft-token-ids` returns real drafts (the code gives -1 placeholders); ngram
  no-match returns `[]` (the code proposes 5 copies of the last token); the serve path drops CLI
  engine args before `create-engine-config`; `batch-sharder.shard-sampler-inputs` is hollow.
- *Lifecycle and LoRA:* no LoRARequest reaches a request, and there is no max_loras gate; an
  aborted parent stays in parent_requests; no grammar-waiting status.
- *Distributed, config, attention, models:* the KV output aggregator drops worker metadata; the NIXL
  pull connector reads expired blocks; MoRIIO Mamba truncation, the OffloadingConnector,
  RoutedExpertsBuffer, `needs_dp_coordinator`/`is_moe`, MultiModalConfig,
  `ModelConfig.compute_hash`, the MLA KV spec, per-kind backend overrides, the SM90 sparse builder,
  VideoMediaIO.merge_kwargs and the multimodal processor cache are missing.

**Simulator and tooling gaps.** A kill doesn't wake a process monitor (P5, L3); `check` can't
print step results; no logits or distributions (P3); a 131k-token prompt exceeds the CEL cost
budget (S7b ran scaled). The first two are in progress.

**Measure review.** Judge V2, V5 (stale result path after `streams_when`) and X4 (relied on an
asynchronous busy-loop quirk) are scenarios to adapt, not regressions:
`reconcile/round3/coordinator-x4.md`.

**Next round.** Coverage over cleanup. Each area gets its oracle2 and judge2 findings, plus the list
of code paths the repo's tests exercise that the model doesn't reach. The 10 untranslatable tests
(numerics, tensors, hash bytes, FX graphs) belong in refinements, not the system model.

## Round 4 (coverage, `FIXES4.md`) and its blind measure

**The build.** 584 components, 2,340 interfaces, 259 flows, 1,334 scenarios (was 1,021), all
passing; full gate exit 0; internal-assertions gate 0.253 -> 0.218. Each area worked down
`coverage_gaps.py`'s ranking of the functions its code defines that tests call and the model
didn't cite. Function-level reach by code owner, before -> after: worker-runner 43->55%, attention
45->52%, engine-core 34->49%, kernels-ops ->38%, scheduler-kv 15->37%, config-platform 23->35%,
serving-api 17->29%, distributed 12->19%, models-layers 4->7% (per-model numerics left to
refinements). Earlier measures re-run: judge2 31 -> 53 of 58 scenarios, oracle2 3 -> 10 of 20.

**The blind measure** (`BENCHMARK3.md`, `judge3/`, `oracle3/`; fresh agents, new cases and tests).

| Measure | Round 3 (BENCHMARK2, oracle2) | Round 4 (BENCHMARK3, oracle3) |
|---|---|---|
| Test oracle | 2 / 36 (2 of 26 translatable) | **6 / 36** (6 of 28 translatable); 22 model bugs, 8 untranslatable |
| Benchmark, steps | 65 / 105 (62%) | 65 / 154 (42%): serving 27/60 sub-steps, scheduling-kv 17/32, execution 8/32, lifecycle 13/30 |
| Benchmark, whole cases | 11 / 32 | 3 / 32 (Q3-2, P3-6, L3-6) |
| Expectations corrected | 14 | 25 (serving 11, lifecycle 7, execution 4, scheduling 3) |

**Reading.** The oracle tripled on a fresh sample: coverage moved what tests exercise. The
benchmark fell, but BENCHMARK3 was written to avoid every behavior BENCHMARK and BENCHMARK2 covered,
so it probes newer ground (Prometheus metrics, sleep/wake, pause, DP+MoE, tool-choice defaults,
streamed validation, encoder scheduling), much of it outside the tests the coverage round followed.
The serving judge counted verified sub-steps (60) where the writer counted 33 steps, so its
denominator is not comparable; whole-case counts are the safer comparison and they dropped. Both
measures agree the model now has the code the tests touch and still lacks much that users touch.

**Wrong claims to fix** (judge3, oracle3, by owner):
- *serving-api:* a defaulted `tool_choice=auto` is dropped (200, not 400); streamed validation
  errors send a role chunk then 500; `/tokenize` applies the max_model_len check; logit_bias, stop
  and allowed-id checks, online beam search, the multimodal limits seam and `/metrics` are missing;
  `llm.add-completion-requests` aborts on `[[]]` and drops multi_modal_data; Cohere errors skip the
  message body; the DeepSeekV3 parser ignores `thinking`.
- *engine-core:* a deferred sleep never calls `executor.sleep`; `pause-scheduler` replies before
  the pause completes; the 503 text and `request_success` labels, gauges and histograms;
  `get-kv-cache-group-metadata` missing; the step skips the mm-cache invalidate; external_launcher
  starts rank 0 only; no MIN memory all-reduce; no VllmConfig reducer; offline LLM keeps stepping
  after the engine dies; the batch queue size ignores PP; DP/MoE (ep_size, is_moe, per-rank queues,
  coordinator).
- *scheduler-kv:* `make-stats` ignores deferred requests; prompt_logprobs don't skip the prefix
  cache; `schedule` omits encoder scheduling; adaptive long-prefill config; the P2P tier manager.
- *worker-runner:* NONE profiling returns 0.5 GiB; no graph pool id; no cudagraph-mode fallback;
  `get-supported-tasks` ignores the model's pooler.
- *attention:* `get-kv-cache-spec` ignores kv-cache-dtype (fp8 gets no extra blocks); decode/prefill
  batch reordering; indexer backends in `describe`; two cudagraph-support branches.
- *models-layers, kernels-ops, config-platform:* MoE LoRA format validation, TurboQuant presets,
  expert counts, mxint4 activation; NVFP4 and per-block FP8 fusion patterns; draft hf overrides.

**Worlds and tooling.** No MoE, VLM or FP8-checkpoint world; derived config isn't recomputed on an
override; a 30 s drain exceeds the event budget; Python float repr (0.0 prints as 0).

**Next.** A round that follows the blind findings and adds the missing worlds (MoE, VLM, FP8
checkpoint) so these behaviors can be driven at all.

## Round 5 (precision and new worlds, `FIXES5.md`) and its blind measure

**The build.** 618 components, 2,464 interfaces, 269 flows, 1,573 scenarios, all passing; full gate
exit 0 (citations 9,925/9,925; hollow, seam-names, racy, unknown-inputs and exemptions at 0; explore
17/17); internal-assertions gate 0.218 -> 0.217. Four new worlds: MoE (Mixtral 8x7B, TP 2 with EP),
vision-language (Qwen2-VL 7B), FP8 checkpoint, FP8 checkpoint with an FP8 KV cache; each serves a
chat request end to end. Each area fixed its round-4 wrong claims with regressions and swept its
error paths (about 650 `fail`s checked, about 180 messages corrected word for word). Round-5 unit
tests: 57/57 after the merge.

Earlier measures, round 4 -> round 5: judge3 48 -> 92 / 113, oracle3 10 -> 21 / 29, judge 38 -> 33 / 43,
judge2 53 -> 52 / 58, oracle 19 -> 18, build-oracle r3 37 -> 36, r4 50 -> 49. Each drop is answered in
`reconcile/round5/measure-notes.md` as an expectation wrong about the code, with citations (for
example `capture_model` runs twice per rank because CUDA-graph memory is profiled first,
`gpu_worker.py:700-704`; the blind serving and execution judges found the same).

**The blind measure** (`BENCHMARK4.md`, `judge4/`, `oracle4/`; fresh agents, new cases and tests).

| Measure | Round 4 (BENCHMARK3, oracle3) | Round 5 (BENCHMARK4, oracle4) |
|---|---|---|
| Test oracle | 6 / 36 (6 of 28 translatable) | **7 / 36** (7 of 27); 20 model bugs, 9 untranslatable |
| Benchmark, steps | 65 / 154 (42%) | **38 / 136 (28%)**: serving 9/37, scheduling-kv 13/31, execution 8/35, lifecycle 8/33 |
| Benchmark, whole cases | 3 / 32 | 2 / 32 (Q4-1, Q4-5) |
| Expectations corrected | 25 | 12 (serving 3, execution 4, scheduling 4 plus the preamble's world, lifecycle 0) |

The serving oracle agent split one sampled file into 16 method rows; it is counted as one entry
(a model bug), so the oracle stays at 36 tests.

**Reading.** Precision raised every measure the areas fixed against (judge3 nearly doubled), and
the new worlds let MoE, VL and FP8 behavior run at all. The blind measure did not follow: the
oracle moved by one test and benchmark steps fell from 42% to 28%. As in the other repos' latest rounds,
the blind misses are **absent mechanisms**, not wrong details: pooling and scoring endpoints,
offline logprobs, bad-words masking, EPLB rearrangement, warmup and autotune, request histograms,
the startup handshake, multi-API-server mode, the Marlin FP8 path, and whole model families
(EmbeddingGemma2, Qwen3-VL). Precision fixes what a measure names; the remaining distance is
coverage of what no measure has named yet.

**Wrong claims to fix** (judge4, oracle4, by owner):
- *serving-api:* the error mapper passes status-bearing errors through (404 image URL: wrong type,
  no param); `/invocations` routes by field presence and drops quotes; an over-long text prompt
  reports the full count, not "at least N"; scoring ignores `items`, `data_1`/`data_2`, list
  `text_1`, `truncate_prompt_tokens`, `max_tokens_per_doc`, counts texts not tokens, 500 on a long
  prompt; SageMaker pooling and rerank routing; pooling ignores the task and its refusals;
  `llm.encode` checks the raw runner and never checks `pooling_params` length; the renderer's
  post-expansion truncation; `/server_info?config_format=yaml` is a 400 and its key filter.
- *engine-core:* arrival stamped after rendering (TTFT, e2e) and ITL on the API clock; 10 request
  histograms; HELLO/READY and `VLLM_ENGINE_READY_TIMEOUT_S`; `run_multi_api_server`; the
  processor cache's `shm` type; DELTA logprobs `[]` not null; prompt parsing (TypeError for an
  encoder/decoder prompt); text bad words via `update_from_tokenizer`; the startup error's
  "Failed core proc(s)".
- *worker-runner:* top-k and prompt logprobs never returned (with scheduler-kv and engine-core);
  the bad-words mask; mamba `prepare_attn` positions; collective RPC waits on every rank (300 s
  timeout instead of the immediate RuntimeError).
- *scheduler-kv:* `defer_block_free` under async scheduling with a kv_consumer; block stride
  alignment and the BLHNC layout; KV events default to zmq; the batched-DP-MoE 256 default and
  `all2all_backend`; the stop check's `min_tokens` and repetition detection.
- *models-layers:* kernel warmup and FlashInfer autotune, deferred-MoE config; Qwen-VL Triton warmup
  and Qwen3-VL; EmbeddingGemma2; `default_seq_pooling_type` and `attn_type`.
- *config-platform:* `--runner auto` to pooling; pooling type from the registry default (BERT is
  encoder_only, CLS, prefix caching and chunked prefill off); head size from `head_dim` 0.
- *kernels-ops:* the FP8 Marlin path on pre-Hopper GPUs; the torch-compile decorator's
  `do_not_compile` and per-module compiled flag.
- *attention:* local-attention virtual batches and the ChunkedLocalAttention builder; the
  FLASHINFER_MLA error prefix and its startup refusal.
- *distributed:* EPLB rearrangement and its communicator; the MoRIIO config's timeout check.

**Worlds and simulator.** No Qwen3-30B-A3B world, no two-GPU VL world, no knobs for Ray, seed,
EPLB or expert placement, no `api-server-count`; a config can't be unset; integers beyond int64
arrive as strings; 8k-token prompts need `max_cel_cost` raised.

## Files

- **Contracts and build:** `profile.yaml`, `skeleton.yaml`, `fixtures.yaml`, `worlds.yaml`,
  `BRIEF.md`, `RECONCILE.md`, `reconcile-notes.md`, `fragments/`, `notes/`, `skips/`, `gen/`,
  `build-oracle/`.
- **The merged model and gate:** `vllm.json`, `quality-gate.txt`.
- **The oracle:** `oracle/`.
- **The benchmark:** `BENCHMARK.md` and `judge/`.

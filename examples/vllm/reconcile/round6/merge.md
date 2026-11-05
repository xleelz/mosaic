# vLLM fix round 6: merge

All nine areas' working fragments were merged, put through the full gate, and accepted together with a joint stage (`--stage` for each, `--accept`) into `.mosaic/stage/examples/vllm/fragments/`. `vllm.json` was rebuilt from skeleton, fixtures, the nine fragments and `worlds.yaml`. `worlds.yaml` was regenerated: a new dense TP 2 world, and the Qwen3 seed in the VL world.

## Gate

The full gate (`docs/PIPELINE.md`, `--profile examples/vllm/profile.yaml`, `--code ~/.cache/mosaic-bench/vllm-0.32.0`, `--lint ...,unwritten-fields`) exits 0:

- 659 components, 2,645 interfaces, 276 flows, 1,805 scenarios: all pass. 0 mocks.
- Citations: 11,193 of 11,193 resolve. Two `--cite-sample 15` rounds (seeds 61 and 62) showed no unsupported claim. One weak title: `weight-cache-daemon.handle-get-state` is titled with its CEL condition.
- Hollow: 0 failing. Racy: 0 of 541; the 10 system findings are cited racy-in-code. Seam names: 0. Unknown inputs: 0. Exemption issues: 0. Clock ids: 0. Unwritten fields: 0.
- Internal assertions: the highest fragment is worker-runner at 20.4% (90 of 442).
- Modeled 1,756 of 1,937 entry points (91%). Trivial: 2.0%. Test reach: 90%; the lowest area is models-layers at 84%. Features: 28 of 28.
- Explore: 17 scenarios, all pass every schedule.

**Ratchet:** `max_internal_assertions` went from 0.217 to 0.204. No threshold was raised. `min_test_reach` stays 0.690, though the measured value is 0.84.

## The multimodal move

Decided by the code: **moved**. `AsyncLLM.__init__` builds the renderer in the API process (`v1/engine/async_llm.py:158`). The renderer builds `mm_processor` and the sender cache there (`renderers/base.py:192-199`), and `_process_multimodal` runs `mm_processor.apply` there (`:894-932`). The LRU receiver is the engine's (`v1/engine/core.py:193`, `:1098-1099`); the shm receiver is the worker's (`v1/worker/worker_base.py:331`).

- `multi-modal-registry` and its children (processor, processing info, media connector, sender caches, factories) are now under `api-server`; `lru-key-replicated-receiver-cache` is under `engine-core`.
- The feared 32 failures were one cause: engine-core's `on: rank0` on the receiver factory call, plus 4 `@rank0` state keys. They were routed; no scenario was weakened.
- **The chat path now runs the processor.** New `base-renderer.process-multimodal`: `online-renderer.render-chat` calls it after tokenizing, expands each image placeholder to its feature tokens, then applies `process-singleton` (post-expansion truncation). `usage` counts the expansion and `multimodal_tokens`. A repeated image reaches the sender cache and crosses without data.
- **ASSUMPTION:** a data URL carries no pixels here, so `media-stand-in-image-width` x `-height` (1120 x 560) stand for a fetched image's size; 800 tokens follow from the real `smart_resize`. A video keeps its template stand-in; only image placeholders expand.

**Breaking, with callers:** `component` parents above (callers using `@rank0` state keys: routed in engine-core and models-layers); `fetch-image` returns `width` and `height`; `render-messages` returns `mm_items` and `mm_counts`; every VL chat's `prompt_tokens` grows by the expansion (no measure regressed).

## Cross-area fixes

- **Collective RPC fail-fast** (engine-core `33-executor.yaml`): engine-core owns it, `vllm/v1/executor/**`. With an output rank the join needs only that rank (`multiproc_executor.py:429-431`), so rank 0's failure surfaces at once. judge4 P4-2 d passes. `engine-core-r6-collective-rpc-output-rank-fails-fast`.
- **`_normalize_arch`** (models-layers `core-registry.yaml`, `registry.py:1297-1321`): `Qwen2ForSequenceClassification` resolves to `Qwen2ForCausalLM`. worker-runner's `get-supported-tasks` now reads the resolved runner and convert (`gpu_model_runner.py:3161-3164`). oracle4 classification passes.
- **`MultiModalBudget`** (models-layers `multi-modal-budget.init`, `.get-dummy-encoder-profile-inputs`; worker-runner `encoder-runner.profile-encoder-cache`; new config `skip-mm-profiling`): `profile_run` builds the budget (32768 tokens) and runs the tower on 1 video item. judge4 P4-7 c passes.
- **Qwen3 warmup:** the VL world seeds Qwen3-VL's weights as well, so the runner's seeded model can run. oracle4 `qwen_vl_triton_warmup` passes.
- **Mamba under deferred free** (scheduler-kv): `kv-cache-manager.pop-blocks-for-free` walks every manager (`kv_cache_coordinator.py:424-427`), with new `mamba-manager.pop-blocks-for-free`.
- **FP8 no-kernel ValueError** (models-layers): each kernel's reason line, in `_POSSIBLE_FP8_KERNELS` order (`kernels/linear/__init__.py:641-650`, `:718-724`).
- **Generate-runner refusal** (config-platform, `model.py:713-717`): now in place. Registry rows report `is_text_generation` for multimodal generators, and `is_hybrid` / `is_attention_free` from each class's interfaces, which also clears the last 2 unwritten fields.
- **DP MoE EP group** (distributed): `ensure-model-parallel-initialized` builds the groups for a MoE checkpoint in a world seeded without a TP group (`parallel_state.py:2383-2390`). A DP 2 run now reaches the DP collective.
- **`clear_all_graphs`** (kernels-ops `breakable-cuda-graph-wrapper.clear-all-graphs`; worker-runner `cuda-graph-manager.release`, `cudagraph_utils.py:961-962`).
- **`api-server-count`** (serving-api): `serve-subcommand.cmd` reads config-platform's value when no flag is given.
- **Dense TP 2 world** (`fixtures.yaml`, `profile.yaml`): `tp2-llama-8b`, with `fixture-smoke-tp2-llama-8b`.
- **Hasher** (scheduler-kv): one-token segments skip the quadratic `starts`, so a 1600-token prompt stays under the CEL limit.

Every other item on the leftovers list is answered with a citation in `measure-notes.md` ("merge (round 6)"). The generated `reconcile/coverage-*` and `coverage.json` files were removed; they were untracked.

## Measures

Each measure ran unedited against `vllm.json`. "Round 5" is the round-5 model (HEAD `vllm.json`), re-run the same way.

| Measure | Round 5 (scenarios) | Round 6 merge (scenarios) | Whole cases, round 5 -> 6 |
|---|---|---|---|
| judge | 33/43 | 33/43 | 19 -> 19 of 28 |
| judge2 | 52/58 | 53/58 | 27 -> 28 of 32 |
| judge3 | 92/113 | 93/113 | 17 -> 18 of 32 |
| judge4 | 70/148 | 128/148 | 2 -> 19 of 32 |
| oracle | 18/19 | 18/19 | 2 -> 2 of 3 |
| oracle2 | 10/20 | 10/20 | 1 -> 1 of 8 |
| oracle3 | 21/29 | 22/29 | 3 -> 3 of 9 |
| oracle4 | 13/38 | 35/38 | 1 -> 6 of 8 |
| build-oracle round 3 | 36/37 | 36/37 | 8 -> 8 of 9 |
| build-oracle round 4 | 49/50 | 49/50 | 8 -> 8 of 9 |
| build-oracle round 5 | 57/57 | 57/57 | 9 -> 9 of 9 |

**Newly failing against round 5: none.** The merge itself took judge4 from 124 to 128 and oracle4 from 33 to 35, with no loss. `BENCHMARK5.md`, `oracle5/` and `judge5/` were neither read nor run.

These counts aren't a blind score: judge4 and oracle4 were this round's fix list, so round 5's blind figures (28% of steps, 7 of 36) are the ones to compare with the next blind measure.

## Open

- **VL encoder path:** the chat path now has `mm_hashes` and `mm_placeholders`, but the engine request doesn't carry them as `mm_features`, and engine-core doesn't size the encoder cache at startup. judge3 P3-8 a-c and Q3-8b still fail.
- **judge4 still failing, no area fix yet:** L4-5 a-c (the `--model` flag and `--served-model-name`), P4-1 b, c and P4-5 abc (worker log lines and the spawn note). Not on the leftovers list.
- **Streaming chat** doesn't report `multimodal_tokens`; the full response does.
- **Stand-ins:** the fetched image size, and video placeholders.
- **Stub:** attention's copy of config `attention-backend` differs from the owner's in its `key` attribute (a warning; it predates this round).

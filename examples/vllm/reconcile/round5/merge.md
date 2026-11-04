# vLLM fix round 5: merge

All nine areas' working fragments were merged, put through the full gate, and staged together into
`.mosaic/stage/examples/vllm/fragments/`. `vllm.json` was rebuilt from skeleton, fixtures, the nine
fragments and `worlds.yaml`. `worlds.yaml` wasn't regenerated: no area variant changed at merge.

## Gate

The full gate (`docs/PIPELINE.md`, `--profile examples/vllm/profile.yaml`, `--code ~/.cache/mosaic-bench/vllm-0.32.0`) exits 0:

- 618 components, 2,464 interfaces, 269 flows, 1,573 scenarios: all pass. 0 mocks.
- Citations: 9,925 of 9,925 resolve. Two `--cite-sample 15` rounds (seeds 51 and 52) showed no unsupported claim. Two claims have weak titles: serving-api's `rl-online-router.post-weight-checker` is titled "fail", and `cohere-renderer.role-to-melody` is titled "return".
- Hollow: 0 failing. Racy: 0 of 480; the 10 system findings are cited racy-in-code. Seam names: 0. Unknown inputs: 0. Exemption issues: 0. Clock ids: 0.
- Internal assertions: 10.0% overall. The highest fragment is worker-runner at 21.6% (86 of 398).
- Modeled 1,753 of 1,936 entry points (91%). Trivial: 2.0%. Test reach: 90%; the lowest area is models-layers at 83%. Features: 28 of 28.
- Explore: 17 scenarios, all pass every schedule.

**Ratchet:** `max_internal_assertions` went from 0.218 to 0.217. No threshold was raised.

## Cross-area fixes

- **Seam names** (serving-api `build.py`): `validate_json_request` read both `content-type` and `Content-Type`. It now reads only the schema's `Content-Type`. That clears all 30 findings.
- **Hollow** (serving-api): the three multimodal-refusal scenarios now assert the `multi-modal-registry.create-processor` call. Engine-core's `engine-core-startup-bad-stat-plugin` now asserts that the reducer was registered.
- **Mixtral EP dispatch/combine** (models-layers `core-moe.yaml`; worker-runner `60-round4.yaml`):
  - `mixtral-for-causal-lm.init` picks the MoE kernel's prepare/finalize through `all2all-utils.maybe-make-prepare-finalize` (`oracle/unquantized.py:517-526`). It passes `all2all_backend`, and passes `dp_rank`/`tp_rank` split by TP.
  - `routed-experts.forward-modular` calls distributed's `group-coordinator.dispatch` before the experts and `.combine` after them, when the choice is `MoEPrepareAndFinalizeNaiveDPEP` (`naive_dp_ep.py:181-187`, `210-245`). The DP chunk sizes come from `forward-context.get-forward-context`, which now returns `dp_metadata`.
  - In the default MoE world (TP 2, EP, DP 1) there is no dispatch, as the code has it.
  - Regression: `models-moe-dp2-ep-forward-dispatch-combine`.
- **Engine-core** (`gen/engine-core/parts`):
  - **mp reducer:** new serving-api `transformers-config-utils.maybe-register-config-serialize-by-value` (`transformers_utils/config.py:1105-1177`). `async-llm.init` calls it first (`async_llm.py:131-132`).
  - **Group metadata:** new scheduler-kv `kv-cache-manager.get-group-block-sizes` gives the DCP-scaled block size for attention specs and the unscaled one for Mamba. New `engine-core.get-kv-cache-group-metadata` uses it (`core.py:481-506`).
  - **External launcher:** new `executor-with-external-launcher`. It models one engine per torchrun rank, running in lockstep. `determine_available_memory` takes the MIN of every rank's budget (`uniproc_executor.py:161-207`). Init, collective RPC, execute and sample are routed to it.
  - Regressions: `engine-core-r5-external-launcher-min-memory`, `engine-core-r5-kv-cache-group-metadata`.
- **config-platform:** owns `model-is-multimodal` (`model.py:1981-1982`). The models-layers, serving-api and worker-runner copies are now references to it. Serving-api's `serve-subcommand.cmd` takes `max_model_len` as an integer or a CLI string, so bench-l3-4c's schema warning is gone.
- **Fixtures (coordinator item):** config-platform-seed's `hf-hub.generation_configs` rows moved into `fixtures.yaml`:
  - Llama-3.1-8B and -70B under `tp1-llama-8b`;
  - the FP8 checkpoint under `fp8-llama-3-8b`;
  - Mixtral under `moe-mixtral-8x7b-tp2-ep`.

  fixtures.yaml's internal assertions are at 18.8%, with no hollow scenario.
- **Multimodal path after serving-api's processor change:** decided by the code, so the model is unchanged. Judge3 S3-4 a/b, build-oracle r3 video and oracle mixed-image force multimodality on Llama, or name a repo missing from the hub. All four pass in `full-vl-qwen2-vl-7b`. The expectations are logged in `measure-notes.md` ("merge").
- **VL chat:** a text chat and an image chat in `full-vl-qwen2-vl-7b` both return 200 with `finish_reason: length`. The forward goes to `qwen2-vl-for-conditional-generation`. The scheduler schedules no encoder inputs yet, so `embed-multimodal` never runs (see Open).

## Measures

Each measure ran unedited against `vllm.json`. "Round 4" is the round-4 model (HEAD `vllm.json`), re-run the same way. The round-4 figures recorded in `reconcile/round4/measure-notes.md` and `RESULTS.md` agree with these: judge 38/43, judge2 53/58, oracle 19/19, oracle2 10/20, build-oracle r3 37/37 and r4 50/50, oracle3 6/36 at blind time.

| Measure | Round 4 (scenarios) | Round 5 merge (scenarios) | Whole cases, round 4 -> 5 |
|---|---|---|---|
| judge | 38/43 | 33/43 | 23 -> 19 of 28 |
| judge2 | 53/58 | 52/58 | 28 -> 27 of 32 |
| judge3 | 48/113 | 92/113 | 7 -> 17 of 32 |
| oracle | 19/19 | 18/19 | 3 -> 2 of 3 |
| oracle2 | 10/20 | 10/20 | 1 -> 1 of 8 |
| oracle3 | 10/29 | 21/29 | 0 -> 3 of 9 |
| build-oracle round 3 | 37/37 | 36/37 | 9 -> 8 of 9 |
| build-oracle round 4 | 50/50 | 49/50 | 9 -> 8 of 9 |
| build-oracle round 5 | 3/10 (round-4 model) | 57/57 | 0 -> 9 of 9 |

The merge's own edits moved oracle3 from 19/29 to 21/29 (the mp reducer and the group metadata). No measure lost a scenario through them.

The losses against round 4 are expectations that are wrong about the code, or that need another world. Each one has a note with citations in `measure-notes.md`:
- judge E1 x2 and E3: the code calls them twice (profiling), or in a different order (the mid-step abort queue);
- judge V6: the event budget;
- judge X5-crash: a race in the code;
- judge2 L2: the code prints GiB;
- oracle mixed image and build-oracle r3 video: these need the VL world;
- build-oracle r4 cohere envelope: serving-api's note;
- judge3 Q3-2c and Q3-3 (scheduler-kv), P3-6 (worker-runner) and L3-5d (engine-core): the areas' notes.

## Open

- **VL encoder path:** engine-core must size the encoder cache at startup (`scheduler.init-encoder-cache`), so that the scheduler schedules encoder inputs and worker-runner calls `embed-multimodal`. This blocks judge3 P3-8 a-c and Q3-8b.
- **DP instance groups across engine-core, scheduler-kv and worker-runner:** judge3 P3-2a and P3-3c.
- **Others:**
  - serving-api: P3-2d (the X-data-parallel-rank header) and S3-6ab;
  - kernels-ops' requests to models-layers: the FlashInfer SSU ImportError and the routed-experts padding helpers;
  - worker-runner's EPLB call to `mixtral-for-causal-lm.set-eplb-state`;
  - Mixtral weight sizing under DP + EP: the load counts every expert per rank, so the DP-2 load runs out of memory.
- **Gates:** `min_test_reach` (0.690) could rise to the measured 0.829. It was left alone, per the rule that no threshold goes up.

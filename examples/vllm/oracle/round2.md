# vLLM oracle, round 2 re-score

This round re-ran the round-1 oracle scenarios against the model after the fix round. Only the oracle `.yaml` files were edited. The fragments, skeleton, fixtures and worlds were not touched.

How each group runs now:
- gpu: 989 passed, 0 failed.
- scheduling-exec: 994 passed, 0 failed.
- serving-engine: 996 passed, 1 failed.

How to read the Cause column:
- **(a) drift:** the harness drifted, so only the calls, paths, config or seeded state were adapted.
- **(b) mistranslation:** the scenario asserted something the test doesn't, so it was fixed to match the test.
- **(c) model bug:** the model disagrees with the test and the code.
- **fixed:** the scenario was already passing before this round, with no edit.

| # | Test | Scenario | R1 | R2 | Cause |
|---|---|---|---|---|---|
| 1 | tests/v1/kv_connector/unit/test_nixl_connector.py:254 | oracle-distributed-nixl-basic-interface | model-bug | pass | (a) drift. `local_block_ids` is now one list per KV group (nixl/metadata.py:243), and the test reads `local_block_ids[0]` (test :285). The expect now indexes `[0]`. |
| 2 | tests/models/multimodal/pooling/test_colqwen3_5.py:111 | oracle-models-layers-colqwen3-5-token-embed | untranslatable | pass (control flow) | (a) drift. The `encode-request` stub became the real tiling path (pooling/offline.py:120-134), which calls `llm-engine.add-request`. The scenario seeds `engine-core-proc.client_kind: sync`, because offline LLM uses a SyncMPClient. The check that there is 1 output (test :57) passes. The shape and L2-norm checks (test :59-71) are numerics and stay untranslatable. |
| 3 | tests/v1/structured_output/test_backend_outlines.py:52 | oracle-scheduler-kv-outlines-unsupported-regex | model-bug | pass | (a) drift. The new `structured-outputs-backend` config is set to `outlines`, which gates the outlines validator. All 11 regexes from the test (test :26-50) are driven through `backend-outlines.validate-regex-is-buildable`. |
| 4 | tests/v1/core/prefix_cache/test_hybrid_prefix_cache_hit_rate.py:1 | oracle-scheduler-kv-hybrid-prefix-cache-hit-rate | model-bug | pass | (a) drift. The attention and mamba KV groups are seeded, and the steps use the new `scheduler-schedule-hybrid` flow. The expectations are unchanged. |
| 5 | tests/v1/simple_kv_offload/test_integration.py:150 | oracle-scheduler-kv-simple-cpu-offload-reload | model-bug | pass | (b) mistranslation. The test only asserts that at least 5 of 10 repeats match the cold output (test :100-102), and a failed reset is only printed (test :94-95). It asserts nothing about step 2 or `num_scheduled_tokens`. An async CPU load parks the request in WAITING_FOR_REMOTE_KVS (scheduler.py:1320-1341), so scheduler-kv was right. The scenario now runs cold run, store, reset, then the repeat through load-then-compute, and asserts it finishes. |
| 6 | tests/v1/core/test_single_type_kv_cache_manager.py:38 | oracle-scheduler-kv-external-computed-blocks-free-pool | model-bug | pass | fixed |
| 7 | tests/v1/worker/test_gpu_model_runner_v2.py:28 | oracle-worker-runner-non-last-pp-rank-sample-feedback | model-bug | model-bug | (a) drift fixed: trace `component` is the caller, so the scenario now matches `interface == 'pp-handler.receive'`. The scenario passes for the non-PCP path. (c) The test's headline claim is still not modeled: `receive` and `postprocess_num_computed_tokens` must get `pcp_manager.global_batch` (test :58-62, gpu/model_runner.py:2109-2114), and worker-runner has no PCPManager. |
| 8 | tests/v1/worker/test_gpu_model_runner_v2_eplb.py:117 | oracle-worker-runner-load-model-registers-moe-eplb | model-bug | pass | (a) drift. The new `enable-eplb` config is set to true (test :72-77). |
| 9 | tests/v1/attention/test_cuda_backend_probe_errors.py:44 | oracle-attention-probe-environment-failure | model-bug | pass | fixed |
| 10 | tests/parser/cohere/test_structural_tags.py:163 | oracle-serving-api-cohere-structural-tag-not-modified | model-bug | pass | fixed |
| 11 | tests/entrypoints/pooling/scoring/test_bi_encoder_online.py:1 | oracle-serving-api-bi-encoder-score-one-pair | model-bug | pass | fixed |
| 12 | tests/entrypoints/pooling/basic/test_tiling_engine.py:32 | oracle-serving-api-tiling-engine-basic | model-bug | pass | (a) drift. The run goes through run-tiling-engine, then add-request ×2, then step. The scenario seeds `engine-core-proc.client_kind: sync`, as serving-api's own offline scenarios do (serving-api.yaml:13568). |
| 13 | tests/entrypoints/multimodal/openai/chat_completion/test_chat_completion_with_mixed_image_embeds.py:1 | oracle-serving-api-chat-mixed-image-and-prompt-embeds | model-bug | pass | (a) drift. The scenario adds the test's server args as the new configs `enable-prompt-embeds`, `enable-mm-embeds`, `model-is-multimodal` and `limit-mm-per-prompt` (test :24, :33-48). The check that the outputs are equal (test :146) is numerics and stays untranslated. |
| 14 | tests/v1/engine/test_wake_up_contract.py:1 | oracle-engine-core-dp-wake-up-requires-all-engines-awake | model-bug | pass | (a) drift. The new `call-utility-all-async` fans out per DP rank. The scenario's topology is now `[dp0, dp1]` with `data-parallel-size: 2`, and it asserts one wake_up per engine, in order (test :28-31). |
| 15 | tests/v1/engine/test_init_error_messaging.py:9 | oracle-engine-core-kv-cache-oom-no-memory | pass | pass | — |
| 16 | tests/v1/engine/test_dp_placement_node_allowlist.py:67 | oracle-engine-core-allowlist-confines-dp-to-listed-nodes | model-bug | model-bug | (c) engine-core. Only the env config `vllm-ray-dp-placement-node-ips` was added. `CoreEngineActorManager.create_dp_placement_groups` and its allowlist filter (v1/engine/utils.py:642, :669-683) are still missing, so the trace has no placement groups. |
| 17 | tests/config/test_config_generation.py:7 | oracle-config-platform-cuda-empty-vs-unset-configs | pass | pass | — |
| 18 | tests/config/test_modelopt_mixed_nvfp4.py:22 | oracle-config-platform-modelopt-mixed-detects-nvfp4 | model-bug | pass | fixed |
| 19 | tests/test_envs.py:19 | oracle-config-platform-object-storage-shm-default-name | model-bug | pass | fixed |

## Totals

| | Round 1 | Round 2 |
|---|---|---|
| pass | 2 | 17 |
| model-bug | 16 | 2 |
| untranslatable (with a scenario) | 1 | 0 |
| sim-gap | 0 | 0 |

Of the 11 scenarios that failed at the start of round 2:
- 9 were harness drift.
- 1 was a mistranslation: the cpu-offload step-2 check.
- 1 is a real model bug: the allowlist scenario.

The PP-feedback scenario now passes but keeps a model-bug verdict, because the PCP global-batch claim isn't modeled.

## Remaining model bugs

- **engine-core:** model `CoreEngineActorManager.create_dp_placement_groups`, filtering nodes by `VLLM_RAY_DP_PLACEMENT_NODE_IPS` (vllm/v1/engine/utils.py:642-683).
- **worker-runner:** add a PCPManager. On a non-last PP rank, `sample_tokens` must pass `pcp_manager.global_batch` to `pp_handler.receive` and `postprocess_num_computed_tokens` (vllm/v1/worker/gpu/model_runner.py:2109-2114).

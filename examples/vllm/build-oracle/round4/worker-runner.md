# Round-4 in-build oracle: worker-runner

Tests from `build-oracle/round4/worker-runner.json`; scenarios in `worker-runner.yaml` (run merged). 6 of 6 pass.

| # | Test | Scenario | Verdict | Model |
|---|---|---|---|---|
| 1 | tests/v1/worker/test_gpu_target_dependent_ar_speculator.py:365 `test_run_model_unpacks_tuple_return_for_mtp` | `-r4-1` (+ sibling `-r4-1b`) | pass | `target-dependent-ar-speculator.run-model` (speculator.py:367-430); the drafter's tuple return is speculator state |
| 2 | tests/v1/cudagraph/test_cudagraph_manager.py:181 `test_capture_query_length_covers_replay_batches` | `-r4-2` (all 4 params) | pass | `cuda-graph-manager.prepare-inputs-to-capture` (cudagraph_utils.py:786-858) |
| 3 | tests/v1/worker/test_attn_utils.py:135 `test_attention_checks_preserve_global_and_target_scoped_support` | `-r4-3` | pass | `attn-utils.get-attn-cg-support`, `get-query-lens-mismatch-unsupported-backend` (attn_utils.py:313-359) |
| 4 | tests/v1/worker/test_kv_cache_allocation_scope.py:32 `test_mrv2_kv_pool_only_wraps_backing_allocation` | `-r4-4`, `-r4-4b` (hisparse False/True) | pass | `attn-utils.init-kv-cache` allocates in the pool, binds outside (attn_utils.py:396-443) |
| 5 | tests/v1/worker/test_late_interaction_runner.py:297 `test_prune_configs_no_rejected_fallback` | `-r4-5` (+ sibling `-r4-5b`) | pass | `flash-maxsim.prune-configs` (_common.py:52-85) |
| 6 | tests/v1/worker/test_gpu_pcp_manager.py:363 `test_decode_sharding_allows_ranks_with_no_owned_request` | `-r4-6` | pass | `pcp-manager.get-rank-segments` (pcp_manager.py:197-306) |

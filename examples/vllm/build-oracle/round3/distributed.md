# Round-3 unit tests: distributed

Source: `build-oracle/round3/distributed.json`. Scenarios: `build-oracle/round3/distributed.yaml`, run with the merged model.

| # | Test | Scenario | Verdict | Notes |
|---|---|---|---|---|
| 1 | `tests/v1/kv_connector/unit/test_moriio_unmap.py:31` test_exact_match_unmap_clears_both_tables | `r3-distributed-1-moriio-exact-unmap` | pass | New `moriio-connector-scheduler.map-request-id` / `unmap-request-id` over two store tables (moriio_connector.py:709-742), including the transfer-id fallback and the miss path. |
| 2 | `tests/v1/kv_connector/unit/offloading_connector/test_canonical_mapping.py:404` test_opaque_fallback_places_page_whole | `r3-distributed-2-opaque-fallback-mapping` | pass | New `canonical-mapping.opaque-fallback-mapping` (canonical_mapping.py:334-348). `_verify_tiling` is checked by the scenario: the four ranks' runs tile the canonical page. |
| 3 | `tests/v1/ec_connector/unit/cpu/scheduler/test_embedding_cache.py:77` test_get_missing_returns_none | `r3-distributed-3-embedding-cache-get-missing` | pass | New `ec-embedding-cache` (embedding_cache.py:48-111): `get` returns None on a miss; `alloc` with its assertions. |
| 4 | `tests/distributed/test_weight_transfer_m2n.py:143` test_rank_four_rejected | `r3-distributed-4-m2n-rank-four-rejected` | pass | New `m2n-common.check-transferable` (m2n_common.py:257-268). |
| 5 | `tests/distributed/test_symm_mem_allreduce.py:127` test_dp_with_symm_mem_allreduce | none | untranslatable | The test builds a real `LLMEngine` with DP=2 and TP=2 on 4 GPUs and asserts only that construction doesn't raise. That is engine-core's data-parallel startup path plus per-group communicator construction on real devices. The model has no data-parallel engine startup, and "no exception during CUDA/NCCL setup" is below the model's level. |
| 6 | `tests/distributed/test_dcp_a2a.py:192` test_dominant_rank | none | untranslatable | The code under test is `vllm/v1/attention/ops/dcp.py::_lse_weighted_combine`, which the attention area owns. The assertion is numeric tensor closeness (an LSE-weighted softmax combine). |

Passing: 4 of 6. Untranslatable: 2.

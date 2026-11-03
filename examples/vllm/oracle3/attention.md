# Oracle round 3: attention

| Test | Behavior | Scenario | Verdict | At fault / missing | Evidence |
|---|---|---|---|---|---|
| tests/v1/attention/test_batch_reordering.py:176 `test_reorder_batch_to_split_decodes_and_prefills` | The batch is reordered in place into decode, short_extend, long_extend, prefill regions with minimal swaps; it returns whether anything moved (`vllm/v1/attention/backends/utils.py:905-982`) | `oracle-attention-reorder-batch-to-split-decodes-and-prefills` (commented out in the yaml: check refuses unknown interfaces) | model-bug (missing) | attention: no interface for `reorder_batch_to_split_decodes_and_prefills` | Only `attention-backend-utils.split-decodes-and-prefills` exists, and it assumes a decode-first batch. The v2 runner's `sortBy` in `gpu-model-runner.execute-model` is a different ordering |
| tests/v1/attention/test_glm5next_indexer_block_sizes.py:26 `test_glm5next_indexer_kernel_block_sizes` | GLM-5.3-Flash indexer kernel block sizes are `index_kpool * get_paged_mqa_page_sizes()`: (32, 64), or (64,) on SM120, the same on ROCm; with or without a spec (`indexer.py:296-306`, `utils/deep_gemm.py:33-36`) | `oracle-attention-glm5next-indexer-kernel-block-sizes` | model-bug (missing) | attention: `attention-backend.describe` has no indexer backends | `DEEPSEEK_V32_INDEXER` fails with key-error. Kernel block sizes don't depend on the platform or kpool anywhere |
| tests/v1/attention/test_deepseek_v4_rocm_adaptive.py:54 `test_deepseek_v4_rocm_adaptive_builders_support_varlen_full_graphs` | The DeepSeek V4 ROCm AITER sparse MLA and SWA builders report ALWAYS under adaptive verification, and otherwise UNIFORM_BATCH from their parents (`models/deepseek_v4/amd/rocm.py:471-484, 552-565`) | `oracle-attention-deepseek-v4-rocm-adaptive-builders-cg-support`, `oracle-attention-deepseek-v4-rocm-fixed-builders-cg-support` | model-bug | attention: `attention-metadata-builder.get-cudagraph-support` | `ROCM_FLASHMLA_SPARSE_DSV4` returns NEVER in both configs. The cg_support table lacks it, and there is no adaptive branch. The `DEEPSEEK_SPARSE_SWA` fixed case returns UNIFORM_BATCH correctly |

Verdicts: 0 pass, 3 model-bug.

## Fix requests

**attention**
1. Add `attention-backend-utils.reorder-batch-to-split-decodes-and-prefills`. The input is req_ids, num_scheduled_tokens, num_computed_tokens, num_prompt_tokens and decode_threshold, and the output is `{modified, req_ids}`. It runs the 4-region classification and the swap loop of `vllm/v1/attention/backends/utils.py:905-982`. Then uncomment the scenario.
2. Give `attention-backend.describe` the MLA indexer backends: `DEEPSEEK_V32_INDEXER` ([64] on CUDA, [1, MultipleOf(16)] on ROCm, `indexer.py:283-285`), plus a GLM-5 next indexer whose sizes are `index_kpool * page sizes`. The page sizes are (32, 64), or (64,) on an SM120 device (`indexer.py:296-306`).
3. In `get-cudagraph-support`, add `ROCM_FLASHMLA_SPARSE_DSV4` (parent UNIFORM_BATCH) and a branch: `config['enable-adaptive-verification']` returns ALWAYS for the DSv4 ROCm AITER MLA and SWA builders (`deepseek_v4/amd/rocm.py:471-484, 552-565`). The source path is owned by models-layers.

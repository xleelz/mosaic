# Oracle 5: attention

Run: all sub-scenarios in `attention.yaml`, `check --no-mocks --lint hollow`: validation 0 errors, hollow lint 0 failing.

| Test | Behavior | Scenario id | Verdict | Entity at fault or missing feature | Evidence |
|---|---|---|---|---|---|
| `tests/v1/attention/test_sparse_mla_kv_cache_layout.py:60` | Sparse MLA spec alignment, block padding and JIT warm-up stride agree for each backend, dtype, SM family and layout (`vllm/v1/worker/utils.py:476-486`, `flashmla_sparse.py:168-175`, `flashinfer_mla_sparse.py:75-79`, `sparse_utils.py:44-47`, `mla_attention.py:735-757`, `kv_cache_utils.py:1520-1551`). | `oracle-attention-mla-spec-* (6); oracle-attention-mla-chain-* (18)` | model-bug | Missing: `customize_attention_spec` and each backend's `customize_spec`; `mla-attention.get-kv-cache-spec` returns no `block_stride_alignment` | All 6 spec sub-scenarios fail on the alignment (expected 36864, 18432, 1152, MultipleOf(64), 656, 352). All 18 chain sub-scenarios pass when the alignment is given as input: layout supported, bytes per block and block count as computed from the code, warm-up registered at the physical stride only for flat caches, and alignment 1 keeps the unpadded size. So the padding and warm-up logic are right but not connected to a spec. Not translated: `index_spec.block_stride_alignment is None`, and the tensor fill and row view. |
| `tests/v1/attention/test_rocm_paged_mxfp4_indexer_plan.py:68` | plan_prefill_chunks splits each chunk into its requests with chunk-local offsets, width, context lengths, gather flag and first request (`rocm_paged_mxfp4_indexer.py:156-202`). | `oracle-attention-rocm-mxfp4-chunks-split-into-requests` | model-bug | Missing: `plan_prefill_chunks` and `RocmMxfp4IndexerMetadataBuilder` | The component `rocm-paged-mxfp4-indexer` has one interface, `topk`, which ignores the plan inputs. Worked through by hand, the code gives the test's values. The test is ROCm-only by module skip, not stale. `row_ends`/`block_ends` are also not modeled; only list-valued plan fields are asserted. |
| `tests/v1/attention/test_rocm_glm5next_sparse.py:52` | fit_kpool_indices_to_aiter keeps the live tail and as much history as fits in topk columns, padding with -1 (`rocm_aiter_mla_sparse.py:130-161`, used at `:1167`). | `oracle-attention-rocm-fit-kpool-preserves-tail` | model-bug | `rocm-aiter-mla-sparse-impl.forward-mqa`; missing `fit_kpool_indices_to_aiter` | forward-mqa goes straight to `sparse-utils.triton-convert-req-index-to-global-index`, with no fit step, and no entity mentions it. Hand check of the reference rule gives the test's rows. Judgment call: this is a Triton kernel, which could be read as below the model, but the test asserts integer index rows and the model does compute its sibling at this level (`mla-indexer.compute-kpool-tail-slot-mapping`). |

Count check: sample entries 3, rows 3.

## Fix requests

### attention

- **Backend spec customization.** Add `customize_attention_spec` (`worker/utils.py:476`) and `customize_spec` for FLASHMLA_SPARSE and FLASHINFER_MLA_SPARSE, and return `block_stride_alignment` so `kv-cache-utils.get-kv-cache-config-from-groups` and `mla-attention.bind-kv-cache` get it from the spec rather than from their input.
- **ROCm MXFP4 indexer planning.** Add `plan_prefill_chunks` (`rocm_paged_mxfp4_indexer.py:156`), with `split_prefill_chunks` and `plan_gather_launches` from the same file, on `rocm-paged-mxfp4-indexer`.
- **k-pool fit.** Add `fit_kpool_indices_to_aiter` (`rocm_aiter_mla_sparse.py:130`) as a step of `rocm-aiter-mla-sparse-impl.forward-mqa` (`:1167`).

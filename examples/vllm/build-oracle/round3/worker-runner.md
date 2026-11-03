# Round-3 in-build oracle: worker-runner

Tests from `build-oracle/round3/worker-runner.json`; scenarios in `worker-runner.yaml` (run merged).

| # | Test | Scenario | Verdict | Cause |
|---|---|---|---|---|
| 1 | tests/v1/worker/test_jit_warmup_migration.py:16 `test_compute_slot_mapping_warmup_matches_runtime_specializations` | none | untranslatable | It asserts that `ComputeSlotMappingKernel.dispatch` and `get_warmup_keys` produce the same Triton `CompileKey`, including `block_table_stride` normalized to 16. Compile-key specialization is below the model's level; the kernel is a `kind: kernel` stub (`block-table.compute-slot-mapping-kernel`). |
| 2 | tests/v1/spec_decode/test_ngram_gpu.py:185 `test_picks_longest_match_among_2_3_4_grams` | `oracle-build-worker-runner-r3-2` (also `-r3-2b`: the right-most match among equal lengths) | pass | `ngram-gpu-speculator.propose` now computes the scan and finalize kernels' result: highest score n·(L+1)+pos+1, then the k following tokens, falling back to the last sampled token. |
| 3 | tests/device_allocator/test_alloc_conf.py:99 `test_alloc_conf_from_env_precedence` | `oracle-build-worker-runner-r3-3` | pass | New `alloc-conf.alloc-conf-from-env` (precedence ALLOC > CUDA > HIP) and `current-alloc-conf` (live wins over env). |
| 4 | tests/v1/spec_decode/test_dflash2.py:194 `test_candidate_model_decoder_layer_cls` | none | untranslatable | It checks which decoder-layer class `DFlash2Qwen3Model` / `LiLiCorr` builds (`vllm/model_executor/models/qwen3_dflash2.py`, `lilicorr.py`). That is models-layers' model-construction code; the worker sees only the speculator. |
| 5 | tests/v1/sample/test_diffusion_gemma_reads.py:355 `test_mask_rows_to_allowed_masks_only_constrained_rows` | none | untranslatable | Tensor-level equality of masked logits (sentinel values, renormalized softmax) in the DiffusionGemma sampler (`vllm/model_executor/models/diffusion_gemma_sampler.py`, models-layers' code). The model holds no logit values. |
| 6 | tests/v1/spec_decode/test_dflash_lookahead.py:98 `test_dflash_prefill_reserves_lookahead_blocks` | `oracle-build-worker-runner-r3-6` | see the run | DFlash reserves num_speculative_tokens + 1 lookahead slots (vllm/config/vllm.py:631-634), so a 16-token prefill takes 2 blocks. The scheduler is scheduler-kv's (`scheduler-add-request`, `scheduler-schedule`). |

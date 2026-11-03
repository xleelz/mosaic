# Round-4 unit tests: config-platform

Scenarios: `build-oracle/round4/config-platform.yaml`, translated by hand (config-platform has no generator).

| # | Test | Scenario | Verdict | Notes |
|---|---|---|---|---|
| 1 | tests/config/test_speculative_draft_max_position_embeddings.py:80 `test_eagle_draft_inherits_target_max_model_len` (eagle, eagle3) | r4-config-platform-1-eagle-draft-inherits-target-max-model-len | pass | Through `engine-args.create-engine-config`: the EAGLE3 draft's 2048 is raised to the target's 131072 (speculative.py:1393-1400, 1677-1709) and the INFO log is in `ctx.spec_override_log`. |
| 2 | tests/test_config.py:3740 `test_dual_key_gumbel_rejects_non_autoregressive_speculation` | r4-config-platform-2-dual-key-gumbel-rejects-ngram | pass | Model fixed: new `vllm-config.check-supports-watermarking` (vllm.py:1275-1371), also called from `vllm-config.post-init` (vllm.py:1446). |
| 3 | tests/config/test_multimodal_config.py:55 `test_mm_encoder_attn_backend_hash_updates` | r4-config-platform-3-mm-encoder-attn-backend-hash-updates | pass | Model fixed: new `multimodal-config.init` and `.compute-hash` (multimodal.py:497-555, 672-693). Hashes are sha256 over canonical JSON, equal/unequal where vLLM's are. |
| 4 | tests/test_config.py:1899 `test_dflash_allows_async_scheduling` | r4-config-platform-4-dflash-allows-async-scheduling | pass | Model fixed: new `vllm-config.resolve-async-scheduling` (vllm.py:1545-1644); `scheduler_config.async_scheduling` is now resolved. The test's tmp-path checkpoints are seeded as hf-hub rows. |
| 5 | tests/test_config.py:531 `test_hisparse_rejects_disabled_full_isl_reservation` | r4-config-platform-5-hisparse-rejects-disabled-full-isl | pass | Model fixed: new `vllm-config.check-hisparse` (vllm.py:1800-1835) and `hisparse-config.init`. The test builds VllmConfig without a model; through EngineArgs the model is Llama, but the full-ISL check comes before the index_topk check, so the outcome is the same. |
| 6 | tests/test_envs.py:336 `TestEnvListWithChoices.test_empty_string_returns_default` | r4-config-platform-6-env-list-empty-string-returns-default | pass | Model fixed: new `envs.env-list-with-choices` (envs.py:444-496); `patch.dict(os.environ)` is the scenario's `envs.environ` state. |

**Result: 6 of 6 pass.**

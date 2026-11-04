# Round-5 unit tests: config-platform

Scenarios: `build-oracle/round5/config-platform.yaml`, translated by hand (config-platform has no generator).

| # | Test | Scenario | Verdict | Notes |
|---|---|---|---|---|
| 1 | tests/test_config.py:2964 `test_is_chunked_prefill_supported` | r5-config-platform-1-is-chunked-prefill-supported | pass (6 of 13 rows) | Model fixed: `model-config.is-chunked-prefill-supported` now takes the pooler's seq/tok pooling types and returns the debug reason the test greps for (model.py:2174-2218); `model-config.post-init` gives CLS-pooling models `encoder_only` (model.py:2155-2163). Rows translated: Qwen3-0.6B, whisper-small, e5-small, clip-vit, mamba-130m, Qwen3-Next. The registry facts (attention type, default pooling type) are seeded on hf-hub rows and the registry's pooling runner is given as `runner: pooling`, because the model's registry stand-in (models-layers) doesn't carry them. The other rows repeat the same branches with other checkpoints. |
| 2 | tests/test_config.py:3202 `test_vllm_config_defaults` | r5-config-platform-2-vllm-config-defaults | pass (partial) | Model fixed: `vllm-config.post-init` now resolves `cudagraph_mode`, `use_inductor_graph_partition` and the CUDA-determinable pass flags per level (vllm.py:247-330). Not translated: `fuse_norm_quant` and `fuse_rope_kvcache_cat_mla`, which depend on the kernel config's IR-op priority lists and the compilation splitting ops (kernel.py:31-35, compilation.py:1278), which the model doesn't resolve; the `None`-model rows (VllmConfig without a ModelConfig) can't be built through EngineArgs. |
| 3 | tests/config/test_config_utils.py:196 `test_get_attr_docs_includes_inherited_fields` | none | untranslatable | `get_attr_docs` parses Python class source (AST) for attribute docstrings across a dataclass MRO: introspection below the model's level. |
| 4 | tests/test_config.py:3653 `test_dual_key_gumbel_warns_that_configured_alpha_is_unused` | r5-config-platform-4-dual-key-gumbel-alpha-warning | pass | Already modeled in `vllm-config.check-supports-watermarking` (vllm.py:1335-1344). |
| 5 | tests/config/test_multimodal_config.py:50 `test_mm_hasher_algorithm_invalid` | r5-config-platform-5-mm-hasher-algorithm-invalid | pass | The message is now pydantic's literal_error text (multimodal.py:293, 372). |
| 6 | tests/config/test_multimodal_config.py:591 `test_auto_mm_processor_device_needs_a_device_capable_transport` | r5-config-platform-6-auto-mm-device-needs-transport | pass | Already modeled in `vllm-config.resolve-mm-processor-device` (vllm.py:2826-2837). |

**Result: 5 of 6 pass (two of them partial translations), 1 untranslatable.**

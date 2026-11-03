# Oracle round 3: models-layers

Run: `go run ./internal/devtools/check -f examples/vllm/vllm.json -f examples/vllm/oracle3/models-layers.yaml --no-mocks --lint hollow -v`
(1 passed, 2 failed; hollow lint clean).

| Test | Behavior | Scenario | Verdict | At fault / missing | Evidence |
|---|---|---|---|---|---|
| tests/model_executor/layers/test_fused_shared_expert.py:314 `test_determine_expert_counts_fuse_shared_experts_override` | `determine_expert_counts(8, 0, 2, fuse)` gives 2 fused shared experts when fusing, else 0 | none | model-bug | models-layers: no FusedMoE construction / `determine_expert_counts` | `vllm/model_executor/layers/fused_moe/layer.py:72-85`, called at `:249`; no interface reads `n_shared_experts` with a fuse flag |
| tests/model_executor/layers/test_conv.py:18 `test_conv2d_patch_embedding_correctness` | Conv2dLayer.forward_native matches nn.Conv2d; `enable_linear` set for kernel==stride | none | untranslatable | tensor equality (`assert_close`) | `vllm/model_executor/layers/conv.py:77-81, 145-151`. Advisory: Conv layers are absent from the model, so even the `enable_linear` dispatch cannot be driven |
| tests/lora/test_lora_manager.py:55 `test_reject_fused_moe_lora_before_registration` | A fused 3D MoE LoRA on a 2D FusedMoEWithLoRA is refused with guidance and never cached | oracle-models-layers-reject-fused-moe-lora-before-registration | model-bug | models-layers: `lru-cache-lora-model-manager.add-adapter` (and `lru-cache-worker-lora-manager.load-adapter`) | Code: `_add_adapter` calls `_validate_moe_lora_format` before caching (`vllm/lora/model_manager.py:412-415, 1252-1272`; worker path `vllm/lora/worker_manager.py:155-156`). Model: add-adapter returns `was_added: true` and registers 7; no `enable_mixed_moe_lora_format` config, no `is_3d_lora_weight` request field, no MoE-wrapper state; load-adapter's step titled "module-format validation" only returns |
| tests/lora/test_lora_weights.py:43 `test_moe_packing_uses_stored_scaling` | `pack_moe` / `pack_moe_stacked` keep each LoRA's stored (rsLoRA) scaling | none | untranslatable | per-tensor weight packing | `vllm/lora/lora_weights.py:163-300`; LoRA weight objects are below the model's level |
| tests/models/language/pooling_mteb_test/test_gte.py:141 `test_embed_models_mteb` | GTE embeddings reach the reference MTEB score | none | untranslatable | model accuracy | MTEB score comparison against HF |
| tests/quantization/test_turboquant.py:87 `TestTurboQuantConfig::test_preset_parses` | Each of the four TQ presets builds a TurboQuantConfig | oracle-models-layers-preset-parses (passes) | model-bug | models-layers: TurboQuantConfig.from_cache_dtype / TQ_PRESETS missing | Scenario passes only through `kv-quant-mode.get-kv-quant-mode`, which maps any `turboquant_*` string (so an unknown preset is accepted too). Code: `vllm/model_executor/layers/quantization/turboquant/config.py:20-41, 216-235`; consumer `vllm/v1/attention/backends/turboquant_attn.py:150-153` (slot_size_aligned) |
| tests/models/test_terratorch.py:26 `test_inference` | `LLM.encode(prompt, pooling_task="plugin")` on a Terratorch pooling model returns an output (no NaN) | oracle-models-layers-terratorch-inference | model-bug | worker-runner: `gpu-model-runner.get-supported-tasks` | Model derives pooling tasks from `convert` only (embed/token_embed or classify/token_classify); code returns `model.pooler.get_supported_tasks()` (`vllm/v1/worker/gpu_model_runner.py:3151-3156`), and Terratorch's IdentityPooler supports `{"plugin"}` (`vllm/model_executor/layers/pooler/special.py:153-155`, `vllm/model_executor/models/terratorch.py:266`). Trace: `engine-core.add-request` fails value-error "Unsupported pooling task", the engine dies, and `llm.encode` still returns ok after 256 empty steps (51 s) without 1 output. NaN check untranslatable |

Verdicts: pass 0, model-bug 4, untranslatable 3, sim-gap 0, test-mismatch 0.

Secondary observation (engine-core, unverified against a test): after ENGINE_CORE_DEAD the trace marks
`async-mp-client` dead, but the offline `LLM` path polls `sync-mp-client.get-output` and keeps stepping
(256 iterations) and returns ok instead of raising EngineDeadError.

## Fix requests

### models-layers
1. Model `determine_expert_counts` (`fused_moe/layer.py:72-85`) inside FusedMoE construction:
   `global = num_experts + num_redundant_experts`, `logical = num_experts`,
   `num_fused_shared = n_shared_experts if n_shared_experts is not None and fuse_shared_experts else 0`,
   with the fuse flag from `resolve_layer_fused_shared_expert` / `aiter-ops.is-fusion-moe-shared-experts-enabled`.
2. Add `_validate_moe_lora_format` to `lru-cache-lora-model-manager.add-adapter` (before registering) and to
   `lru-cache-worker-lora-manager.load-adapter`: an `enable-mixed-moe-lora-format` config, an
   `is_3d_lora_weight` field on the LoRA request/adapter, and per-module wrapper kind (2D FusedMoEWithLoRA vs
   FusedMoE3DWithLoRA) in state; fail `value-error` with the code's message naming the module, and register nothing.
3. Model `TurboQuantConfig.from_cache_dtype` with the TQ_PRESETS table (key/value bits, norm_correction,
   derived packed and slot sizes) and its "Unknown TurboQuant cache dtype" ValueError; have the TurboQuant
   backend's `customize_spec` use its `slot_size_aligned`.
4. Model the MoE experts backend capability checks (`_supports_activation`, `_supports_quant_scheme`,
   `_supports_parallel_config`), at least for TrtLlmMxint4ExpertsMonolithic (`experts/trtllm_mxint4_moe.py:61-80`:
   SILU and SWIGLUOAI only). (Exposed by the kernels-ops sample.)

### worker-runner
1. `gpu-model-runner.get-supported-tasks`: for the V1 runner, return the model pooler's tasks
   (`gpu_model_runner.py:3151-3156`), so a Terratorch / IdentityPooler model supports `plugin`
   (seedable per model, e.g. from the model-registry architecture or a `pooler_tasks` state).

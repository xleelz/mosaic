# Oracle: config-platform (vLLM fix round 3, blind)

| Test | Behavior | Scenario | Verdict | Entity at fault / missing | Evidence |
|---|---|---|---|---|---|
| tests/test_config.py:3454 `test_needs_dp_coordination` | `VllmConfig.needs_dp_coordinator` is true iff DP > 1 and (model is MoE or LB is internal) | oracle-config-platform-needs-dp-coordination-dp2-internal-lb, oracle-config-platform-needs-dp-coordination-dp1 (both fail) | model-bug (missing) | `VllmConfig.needs_dp_coordinator` (vllm/config/vllm.py:843-862); `ModelConfig.is_moe` | `engine-args.create-engine-config` -> `vllm-config.post-init` returns `ConfigVllmConfig`, which has no `needs_dp_coordinator`, no `is_moe` and no `data_parallel_external_lb`; both runs fail on the missing field. No DP coordinator anywhere in the model |
| tests/config/test_multimodal_config.py:71 `test_language_model_only_affects_model_hash` | `ModelConfig.compute_hash` changes with `language_model_only`, so LM-only and full deployments do not share a compile cache | none | model-bug (missing) | `ModelConfig.compute_hash` / `language_model_only` | No compute_hash anywhere; `vllm-backend.call` builds the compile cache dir as `'rank_0_0/' + prefix`, ignoring the config hash its own title cites (backends.py:1070). The hash value is below the model; the cache-key effect is not |
| tests/config/test_multimodal_config.py:544 `test_fold_mm_processor_device` | `MultiModalConfig.fold_mm_processor_device` folds the `--mm-processor-device` flag into `mm_processor_kwargs` ("auto"/None leave nothing, "gpu" means the platform accelerator, an explicit kwargs device wins) | none | model-bug (missing) | `MultiModalConfig` (vllm/config/multimodal.py) as a whole | No multimodal-config component, interface or schema; `mm_processor_kwargs`, `mm_processor_device` and `_resolve_mm_processor_device` are absent |

## Fix requests (owning area: config-platform)

1. **VllmConfig.needs_dp_coordinator**: expose it on the resolved config (`vllm/config/vllm.py:843-862`)
   together with `model_config.is_moe` and `parallel_config.data_parallel_external_lb`, and let
   engine-core start the DP coordinator from it.
2. **MultiModalConfig**: add the component with `fold_mm_processor_device`, `get_mm_processor_device_type`
   and `VllmConfig._resolve_mm_processor_device` (EC role and IPC transport decide `auto`).
3. **ModelConfig.compute_hash**: model the factors that enter the compile-cache key (including
   `language_model_only`) and have `vllm-backend.call` derive the cache dir from them (owner of
   that half: kernels-ops).

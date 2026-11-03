# Round-3 in-build oracle: kernels-ops

| Test | Scenario | Verdict | Reason |
|---|---|---|---|
| tests/kernels/quantization/test_scaled_mm_kernel_selection.py:81 test_fp8_linear_backend_override | none | untranslatable | The code under test is `init_fp8_linear_kernel` / `_get_linear_backend` in `vllm/model_executor/kernels/linear` (models-layers). Kernels-ops has no linear-kernel selection to drive. The test also patches `current_platform` and `is_supported`. Belongs to models-layers. |
| tests/kernels/moe/test_flashinfer_moe.py:60 test_flashinfer_swigluoai_params_are_forwarded | none | untranslatable | It checks the kwargs that `FlashInferExperts.apply` (`vllm/model_executor/layers/fused_moe/experts/flashinfer_cutlass_moe.py`, models-layers) forwards to a monkeypatched FlashInfer function. These are argument plumbing in another area's code. Belongs to models-layers. |
| tests/compile/passes/test_rope_kvcache_fusion.py:462 test_rope_static_qquant_kvcache_fusion | oracle-r3-kernels-ops-rope-static-qquant-kvcache-fusion | pass | The model now has `rope-kv-cache-fusion-pass.call` and the `fuse-rope-kvcache` / `rope-kvcache-fusion-max-token-num` configs. matched_count, static quant remaining and the negative control are translated. Op counts in the FX graph and numerics are below the model's level. |
| tests/kernels/core/test_cpu_activation.py:44 test_cpu_act_and_mul | oracle-r3-kernels-ops-cpu-act-and-mul | pass (partial) | Added host-side behaviors to the CPU `silu_and_mul`, `gelu_and_mul` and `gelu_tanh_and_mul` ops (output shape, float-only dispatch). `assert_close` against `forward_native` is untranslatable (no tensor values). |
| tests/kernels/moe/test_moe_kernel_oracle.py:26 test_make_kernel_delegates | none | untranslatable | A mock-delegation test of `UnquantizedMoEKernelOracle.make_kernel` (`vllm/model_executor/layers/fused_moe/oracle/unquantized.py`, models-layers). It asserts call arguments on a `patch`. |
| tests/kernels/attention/test_amx_mla.py:318 test_amx_mla_impl_forward_mqa_matches_reference | none | untranslatable | Numeric equality of the CPU AMX MLA attention impl (attention area) against a per-head reference. |

Result: 2 pass, 4 untranslatable (3 of them test models-layers code, 1 is numeric).

# Oracle round 3: kernels-ops

Run: `go run ./internal/devtools/check -f examples/vllm/vllm.json -f examples/vllm/oracle3/kernels-ops.yaml --no-mocks --lint hollow -v`
(2 passed, 2 failed; hollow lint clean).

| Test | Behavior | Scenario | Verdict | At fault / missing | Evidence |
|---|---|---|---|---|---|
| tests/kernels/helion/test_helion_available.py:23 `test_helion_kernel_compilation_smoke` | A test-local Helion kernel compiles and adds two tensors | none | untranslatable | third-party compiler + tensor equality | Uses `helion.kernel` directly; no vLLM code under test |
| tests/kernels/core/test_vit_fp8_quant.py:44 `test_quantize_contiguous` | Output shape is (seq, heads, round_up(head_dim,16)), FP8, zero-padded | oracle-kernels-ops-quantize-contiguous | pass | none | `qkv-padded-fp8-quant.quantize-fp8-pad-head-dim-triton` returns 80/80/128 for 72/80/128 (`vllm/kernels/triton/qkv_padded_fp8_quant.py:110`); FP8 values and zero padding untranslatable |
| tests/kernels/attention/test_cutlass_mla_decode.py:67 `test_cutlass_mla_decode` | SM100 CUTLASS MLA decode matches a torch reference | none | untranslatable | kernel numerics (cosine diff) | |
| tests/kernels/attention/test_cache.py:60 `test_reshape_and_cache` | Each token lands at block slot//bs, offset slot%bs | none | untranslatable | kernel memory layout (opcheck, assert_close on cache) | `torch-bindings.reshape-and-cache` is a latency model by design (profile) |
| tests/kernels/moe/test_marlin_vs_trtllm_mxint4.py:84 `test_trtllm_mxint4_activation_supports_vllm_gated_silu` | TrtLlmMxint4 experts accept SILU and SWIGLUOAI, reject RELU2_NO_MUL | none | model-bug | models-layers: no MoE experts backends / `_supports_activation` | `vllm/model_executor/layers/fused_moe/experts/trtllm_mxint4_moe.py:69-73` |
| tests/compile/passes/test_silu_mul_quant_fusion.py:273 `test_fusion_silu_and_mul_quant` | ActivationQuantFusionPass matches exactly once and the graph then holds the fused op instead of silu_and_mul + quant | oracle-kernels-ops-fusion-silu-and-mul-quant-fp8-static (pass), -block (fail), -nvfp4 (fail) | model-bug | kernels-ops: `activation-quant-fusion-pass.call` | Model only rewrites `silu_and_mul+static_fp8_quant`. Code also registers SiluMulNvfp4QuantPattern -> `_C::silu_and_mul_nvfp4_quant` when the op exists, and on CUDA SiluMulBlockQuantPattern for kFp8Dynamic128Sym/64Sym -> `_C::silu_and_mul_per_block_quant` (`vllm/compilation/passes/fusion/act_quant_fusion.py:36-44, 277-307`). Model returns `replaced: 0` and `ctx.fused` unset for those |
| tests/kernels/fla/test_fused_sigmoid_gating_delta_rule.py:25 `test_fused_sigmoid_gating_delta_rule_update_non_spec` | Fused sigmoid-gating delta-rule update matches the recurrent reference | none | untranslatable | Triton kernel numerics | |

Verdicts: pass 1, model-bug 2, untranslatable 4, sim-gap 0, test-mismatch 0.

## Fix requests

### kernels-ops
1. `activation-quant-fusion-pass.call`: register the NVFP4 pattern (when `silu_and_mul_nvfp4_quant` is available,
   CUDA) and, on CUDA, the per-group FP8 block-quant patterns (group 128 and 64, transposed/e8m0/TMA variants)
   with fused op `_C::silu_and_mul_per_block_quant`; keep `replaced` as the match count.

### models-layers
1. Model the MoE experts backend capability checks, starting with TrtLlmMxint4ExpertsMonolithic
   `_supports_activation` = {SILU, SWIGLUOAI} (`experts/trtllm_mxint4_moe.py:69-73`).

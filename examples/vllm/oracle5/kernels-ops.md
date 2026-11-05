# Oracle: kernels-ops

Tests read from vLLM v0.32.0 and never run. Scenarios: `oracle5/kernels-ops.yaml`.
Check result: 14 scenarios, 4 passed, 10 failed. Validation has 0 errors and the hollow lint 0 failures.

Verdicts: **0 pass, 4 model-bug, 3 untranslatable, 0 test-mismatch, 0 sim-gap.**
Count check: 7 entries in the sample, 7 rows below.

| Test | Behavior | Scenario id | Verdict | Entity at fault | Evidence |
|---|---|---|---|---|---|
| `tests/kernels/helion/test_rms_norm_per_block_quant.py:83` `test_config_picker_exact_match` | `pick_config` returns the tuned key that exactly matches the input's (hidden_size, group_size, num_tokens). | `oracle-kernels-ops-config-picker-exact-match` | model-bug | `helion-kernel-wrapper.call` | Aborts at `helion-kernel-wrapper.call.behavior[4]`: `vars.cfg.keys.map(k, k.intermediate): no such key: intermediate`. Registration through the real path succeeds first. Code: `vllm/kernels/helion/ops/rms_norm_per_block_quant.py:103-152`. |
| `tests/kernels/quantization/test_quant_op_schema.py:35` `test_per_tensor_quant_static_schema` | `opcheck` proves the static `rocm_aiter_per_tensor_quant` op honors its registered schema, with no aliasing of a non-mutable input. | `oracle-kernels-ops-per-tensor-quant-static-schema` | untranslatable | none | The schema and aliasing checks on tensor storage are below the model. The control-flow part passes: `is_dynamic` is false, the shape is [128, 4096], and the op is reached. Code: `vllm/_aiter_ops.py:1265-1276`, `:2954-2959`, `:3544-3555`. |
| `tests/compile/dynamic_shapes/test_dynamic_shapes_compilation.py:112` `test_dynamic_shapes_compilation` | Each shapes type, AOT and bytecode-hook combination compiles and generates output matching eager. | `oracle-kernels-ops-dynamic-shapes-*` (8, nested below) | model-bug | `support-torch-compile.call`, `cuda-graph-manager.run-pw-graph`, `gpu-model-runner.execute-model`, and the missing shapes-type config | See the sub-results below. |
| `tests/kernels/quantization/test_cutlass_w4a8.py:229` `test_cutlass_w4a8` | The W4A8 kernel's output matches the `torch._scaled_mm` reference on each shape. | `oracle-kernels-ops-cutlass-w4a8` | untranslatable | none | The only assertion is `assert_close` on GEMM output. The control-flow part passes: 12 of 12 shapes reach `torch-bindings.cutlass-w4a8-mm`. The helper's `schedule` argument is never passed to the op. Code: `vllm/_custom_ops.py:1362-1382`. |
| `tests/kernels/moe/test_cpu_fused_moe.py:237` `test_cpu_fused_moe` | The CPU fused MoE's output matches the reference after the weights are prepacked. | `oracle-kernels-ops-cpu-fused-moe` | untranslatable | none | The only assertion is `assert_close`. The control-flow part passes: the trace shows prepack, prepack, then `cpu-fused-moe`. Four of the batch and dimension combinations were driven; the model does not branch on activation, bias or ISA. Code: `vllm/_custom_ops.py:4467-4510`. |
| `tests/kernels/quantization/test_rocm_mxfp8_linear.py:52` `test_rocm_mxfp8_linear_matches_dequant_reference` | The native CDNA4 kernel returns (num_tokens, n), finite and within 5e-3 of the reference, on the V4.1 attention shapes. | `oracle-kernels-ops-rocm-mxfp8-linear-matches-dequant-reference` | model-bug | missing `RocmDotScaledMxfp8LinearKernel`; nearest is `model-opt-linear-method.apply` | All 32 shape checks fail with `no such key: out_shape`, and the kernel is never called. Code: `vllm/model_executor/kernels/linear/mxfp8/rocm_native.py:223`, and `vllm/model_executor/kernels/linear/__init__.py:565`. The finite and relative-error checks are numeric and not translated. |
| `tests/kernels/moe/test_count_expert_num_tokens.py:124` `test_compute_expert_num_tokens` | `count_expert_num_tokens` gives exact per-expert counts on each EP rank, with and without an expert map. | `oracle-kernels-ops-compute-expert-num-tokens` | model-bug | missing `fused-moe-utils.count-expert-num-tokens` | `fused-moe-utils` has only `swiglu-limit-func`. Code: `vllm/model_executor/layers/fused_moe/utils.py:199`, caller `deep_gemm_utils.py:538`. An unknown interface fails validation, so the scenario drives an EP-sharded generate and asserts the call appears. That driver is arbitrary, and the failure shows only that the interface is absent. |

## `test_dynamic_shapes_compilation` sub-results

| Sub-scenario (`oracle-kernels-ops-dynamic-shapes-`) | Result | Failing expectation |
|---|---|---|
| `backed-aot0-hook1` | fail | The engine path never enters `support-torch-compile.call` |
| `backed-aot1-hook0` | fail | same |
| `unbacked-aot0-hook0` | fail | same |
| `unbacked-aot1-hook1` | fail | same |
| `size-oblivious-aot0-hook1` | fail | same |
| `size-oblivious-aot1-hook0` | fail | same |
| `eager-baseline` | pass | none |
| `type-settable` | fail | No config exposes `dynamic_shapes_config.type` |

In the six failing cases, every other expectation passes: warm-up and generate succeed, and direct calls to
`support-torch-compile.call` take the right AOT or JIT first-call path and the right second-call path.
The two `gpt2` model cases were not driven separately, because the fixture worlds have no such model.
Logprob closeness to eager is numeric and not translated. Unbacked and size-oblivious cases differ from
backed in the scenarios only by name and their AOT and hook settings, because the model can't express the type.

## Fix requests

### kernels-ops

1. **`helion-kernel-wrapper.call` is specific to one op.** It always runs the `silu_mul_fp8` picker, builds an
   `{intermediate, numtokens}` key and calls `silu-mul-fp8.silu-mul-fp8`, whatever `op_name` says. Dispatch on the
   registered kernel's picker, and model `pick_config` for `rms_norm_per_block_quant`: closest hidden_size, then
   closest group_size, then the smallest num_tokens at or above the input, else the largest; no keys returns None.
   Its CaseKey string is sorted compact JSON (`vllm/kernels/helion/case_key.py:47`). Also add `hidden_size` and
   `group_size` to the request. Code: `vllm/kernels/helion/ops/rms_norm_per_block_quant.py:103-152`,
   `:203`, and `vllm/kernels/helion/register.py:176-214`.
2. **`dynamic_shapes_config.type` is missing.** Add a config for it (`backed`, `unbacked`, `backed_size_oblivious`) and
   have `support-torch-compile.call` branch on it. Code: `vllm/config/compilation.py:322,346`,
   `vllm/compilation/decorators.py:442` (`mark_unbacked` against `mark_dynamic`), `:544`, and `:663`
   (the `backed_size_oblivious` patch). It also belongs in the backend's recorded factors: `vllm/compilation/backends.py:1020`.

### worker-runner

3. **The runner's forward bypasses `@support_torch_compile`.** `cuda-graph-manager.run-pw-graph` calls
   `<arch>.forward` directly, and warm-up and generate under `compilation-mode: 3` never reach
   `support-torch-compile.call`, so nothing compiles. In the code, `run_pw_graph` and the eager branch call the
   model object (`vllm/v1/worker/gpu/cudagraph_utils.py:571-576`, `vllm/v1/worker/gpu/model_runner.py:2034-2044`),
   whose class is decorated (`vllm/model_executor/models/llama.py:337`); its `__call__` compiles on first use
   (`vllm/compilation/decorators.py:524-624`). Route the model call through `support-torch-compile.call`.

### models-layers

4. **`RocmDotScaledMxfp8LinearKernel` is missing.** Add it, with `is_supported` (ROCm and `supports_mx`),
   `process_weights_after_loading` (32x32 block-scale compaction, or dequantize to BF16 when K % 128 != 0), and
   `apply_weights` (block32 GEMM, BF16 linear, or `dot_scaled`), returning `(*x.shape[:-1], N)`. It comes first in the
   ROCm MXFP8 kernel list, ahead of emulation. Code: `vllm/model_executor/kernels/linear/mxfp8/rocm_native.py:223`,
   `vllm/model_executor/kernels/linear/__init__.py:565`.
5. **`count_expert_num_tokens` is missing.** Add it to `fused-moe-utils`: a signed-dtype assert, an optional `expert_map`,
   -1 entries excluded, and a result of length `num_local_experts`. Wire the deep-GEMM caller when `expert_tokens_meta` is
   absent. Code: `vllm/model_executor/layers/fused_moe/utils.py:168-235`, `deep_gemm_utils.py:534-540`.

## Notes

- `area_at_fault` in the JSON holds one area per row. The dynamic-shapes row names `kernels-ops`, and its summary also
  names `worker-runner`, which owns fix 3.
- `test_compute_expert_num_tokens` uses `assert_close`, but with `atol=0, rtol=0` on integer counts. It is scored
  model-bug because the rule is expressible in CEL and the interface is absent. A reader who treats any Triton kernel
  output as numerics would score it untranslatable.

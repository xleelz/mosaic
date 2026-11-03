# Oracle: kernels-ops (vLLM fix round 3, blind)

No test in this sample asserts control flow, scheduling, state or timing at the model's level, so `kernels-ops.yaml` carries no scenarios (`scenarios: []`; check: validation 0 errors).

| Test | Behavior | Scenario | Verdict | Entity at fault / missing | Evidence |
|---|---|---|---|---|---|
| tests/kernels/helion/test_benchmark_script.py:28 `test_check_correctness_runs_once_without_mutating_benchmark_inputs` | `check_correctness` deep-copies inputs, runs kernel and baseline once each, leaves the benchmark inputs unmutated (tools/benchmark_helion_kernels.py:322-360) | none | untranslatable | - | Code under test is in `tools/`, which profile.yaml excludes from the model; the assertion is tensor aliasing/deepcopy semantics |
| tests/kernels/helion/test_register.py:962 `TestTorchCompileHOP.test_compiled_graph_contains_helion_hop` | torch.compile of a `HelionKernelWrapper` call emits a `helion_kernel_wrapper_mutation` HOP node in the FX graph (vllm/kernels/helion/register.py) | none | untranslatable | - | Asserts FX graph node targets and eager/compiled numeric equality; `helion-kernel-wrapper.call` exists but graph lowering is below the model |
| tests/kernels/test_engram.py:257 `test_engram_hash_cache_replay` | `NgramHashState` n-gram hashes and the per-slot token-history cache stay correct across CUDA-graph replays, dead tokens and fully padded steps (vllm/models/deepseek_v41/common/engram.py:423, 520) | none | untranslatable | - | Exact hash values and per-slot device-cache contents of one kernel; Engram is not in the model and its granularity is kernel memory |
| tests/kernels/quantization/test_rocm_skinny_gemms.py:251 `test_rocm_wvsplitkrc_large_k` | `wvSplitKrc` on gfx950 with large K matches `F.linear` (vllm/_custom_ops.py:2133, csrc/rocm/skinny_gemms.cu) | none | untranslatable | - | `assert_close` numerics only; `rocm-torch-bindings.wv-split-krc` exists |

Verdicts: pass 0, model-bug 0, test-mismatch 0, sim-gap 0, untranslatable 4.

## Fix requests

None for kernels-ops from this sample.

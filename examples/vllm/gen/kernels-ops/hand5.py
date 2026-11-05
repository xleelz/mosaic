"""Fix round 6 (mechanism coverage): the round-5 measure's kernels-ops findings and the kernel-selection
and compile mechanisms the coverage report lists.

- @support_torch_compile per module (oracle4 fix request): do_not_compile, compiled and the AOT function
  belong to each decorated module; the IGNORE_COMPILE_KEY lookup follows the MRO (hand2/hand3 hold the
  interfaces; the scenarios are here).
- _C::marlin_gemm host dispatch: the FP8 weight-only (W8A16) Marlin GEMM that pre-Hopper GPUs fall back to,
  with its dtype, shape and capability checks (csrc/quantization/marlin/marlin.cu).
- Breakable CUDA graphs (VLLM_USE_BREAKABLE_CUDAGRAPH): capture with eager breaks at attention ops, replay.
- Kernel and quantization choices: DeepGEMM's scale-format oracle, the Triton kernel override registry,
  the AITER MoE sorting dispatch policy and top-k softmax, the MoE all2all backend package probes.
- Compile caching: the compiler choice (make_compiler) and the adaptors' initialize_cache.

Exports COMPONENTS, CONFIGS, FLOWS and SCENARIOS for build.py; overrides hand2.I / OP_BEHAVIORS entries."""
from common import src
from hand import cfg, comp, BK, CI, CG, DC, ENVS, MON
from hand2 import I, OP_BEHAVIORS, iface, count  # noqa: F401
from hand3 import COMPONENT_PATCHES

ERR = lambda *codes: [{"code": c, "status": 0, "retryable": False} for c in codes]
MAR = "csrc/quantization/marlin/marlin.cu"
MARH = "csrc/quantization/marlin/marlin.cuh"
REP = "csrc/quantization/marlin/gptq_marlin_repack.cu"
CP = "vllm/_custom_ops.py"
BCG = "vllm/compilation/breakable_cudagraph.py"
DG = "vllm/utils/deep_gemm.py"
DISP = "vllm/triton_utils/dispatcher.py"
AIT = "vllm/_aiter_ops.py"
IU = "vllm/utils/import_utils.py"
IFACE_PLAT = "vllm/platforms/interface.py"

COMPONENTS = []
CONFIGS = []
FLOWS = []
SCENARIOS = []
FX = ["tp1-llama-8b"]
FP8W = ["full-fp8-llama-3-8b"]


def started(i):
    return f"trace.exists(e, e.type == 'call.start' && e.interface == '{i}')"


# ====================================================================== @support_torch_compile per module
STF = "kernels-ops-support-torch-compile"
RUN = {"num_layers": 1, "num_tokens": 32, "runtime_mode": "NONE"}
CNT = lambda a: {"interface": "compilation-counter.clone", "caller": "gpu-worker", "as": a}
SCENARIOS += [
    {"id": "kernels-ops-r6-decorator-per-module-jit", "name": "Two @support_torch_compile modules each compile once; an @ignore_torch_compile subclass between them runs eager",
     "description": "oracle4 fix request (test_decorator.py::test_ignore_torch_compile_decorator): do_not_compile is decided per module in the decorated __init__ "
                    "(decorators.py:399-406) and __call__ honours it (:528); every module starts with compiled = False (:415) and its own wrapper and VllmBackend.",
     "fixtures": ["full-tp1-llama-8b"], "config": {"vllm-use-aot-compile": False, "vllm-disable-compile-cache": True},
     "steps": [{"interface": "support-torch-compile.decorate", "caller": "gpu-worker", "as": "da", "input": {"cls": "Backbone", "forward_params": [{"name": "x", "annotation": "torch.Tensor"}]}},
               {"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "ia", "input": {"cls": "Backbone"}},
               CNT("c0"), {"flow": STF, "as": "ra", "input": RUN}, {"flow": STF, "as": "ra2", "input": RUN}, CNT("c1"),
               {"interface": "support-torch-compile.ignore-torch-compile", "caller": "gpu-worker", "as": "ig", "input": {"cls": "DraftHead"}},
               {"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "ib", "input": {"cls": "DraftHead", "bases": ["Backbone"]}},
               {"flow": STF, "as": "rb", "input": RUN}, CNT("c2"),
               {"interface": "support-torch-compile.decorate", "caller": "gpu-worker", "as": "dc", "input": {"cls": "EagleHead", "forward_params": [{"name": "x", "annotation": "torch.Tensor"}]}},
               {"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "ic", "input": {"cls": "EagleHead", "bases": ["DraftHead", "Backbone"]}},
               {"flow": STF, "as": "rc", "input": RUN}, CNT("c3")],
     "expect": ["!steps.ia.result.value.do_not_compile && steps.ib.result.value.do_not_compile && !steps.ic.result.value.do_not_compile",
                "steps.ra.result.value.path == 'jit-compiled' && steps.ra2.result.value.path == 'compiled' && steps.rb.result.value.path == 'eager' && steps.rc.result.value.path == 'jit-compiled'",
                "steps.c1.result.value.counters.num_graphs_seen - steps.c0.result.value.counters.num_graphs_seen == 1",
                "steps.c2.result.value.counters.num_graphs_seen == steps.c1.result.value.counters.num_graphs_seen",
                "steps.c3.result.value.counters.num_graphs_seen - steps.c2.result.value.counters.num_graphs_seen == 1",
                "state['support-torch-compile@rank0'].compiled['Backbone'] && state['support-torch-compile@rank0'].compiled['EagleHead'] && !('DraftHead' in state['support-torch-compile@rank0'].compiled)",
                "state['vllm-backend@rank0'].called['Backbone'] && state['vllm-backend@rank0'].called['EagleHead'] && !('DraftHead' in state['vllm-backend@rank0'].called)"]},
    {"id": "kernels-ops-r6-decorator-ignore-inherited", "name": "A subclass of an @ignore_torch_compile class that is not re-decorated inherits the ignore (getattr walks the MRO)",
     "description": "_should_ignore_torch_compile is getattr(cls, IGNORE_COMPILE_KEY, False) (decorators.py:80-82): the nearest class in the MRO that set the key decides.",
     "fixtures": FX,
     "steps": [{"interface": "support-torch-compile.decorate", "caller": "gpu-worker", "as": "d", "input": {"cls": "Base", "forward_params": [{"name": "x", "annotation": "torch.Tensor"}]}},
               {"interface": "support-torch-compile.ignore-torch-compile", "caller": "gpu-worker", "as": "ig", "input": {"cls": "Mid"}},
               {"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "leaf", "input": {"cls": "Leaf", "bases": ["Mid", "Base"]}},
               {"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "base", "input": {"cls": "Base"}},
               {"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "off", "input": {"cls": "Gated", "enable_if": False}}],
     "expect": ["steps.leaf.result.value.do_not_compile && !steps.base.result.value.do_not_compile && steps.off.result.value.do_not_compile",
                "state['support-torch-compile@rank0'].modules['Leaf'].do_not_compile && state['support-torch-compile@rank0'].current == 'Gated'"]},
    {"id": "kernels-ops-r6-decorator-skip-compiled", "name": "forward_context.skip_compiled bypasses the compiled model of a module that would compile",
     "fixtures": FX, "config": {"vllm-use-aot-compile": False},
     "steps": [{"flow": STF, "as": "skip", "input": dict(RUN, skip_compiled=True)}, CNT("c")],
     "expect": ["steps.skip.result.ok && steps.skip.result.value.path == 'skip-compiled' && steps.skip.result.value.module == 'LlamaModel'",
                "steps.c.result.value.counters.num_graphs_seen == 0",
                "!('LlamaModel' in state['support-torch-compile@rank0'].compiled) && state['support-torch-compile@rank0'].num_compiles == 0"]},
    {"id": "kernels-ops-r6-decorator-aot-per-module", "name": "AOT: two decorated modules save two artifacts (the hash includes each forward's qualname)",
     "description": "decorators.py:557-581: factors + _model_hash_key(self.forward) pick the AOT directory, so a second model (e.g. an EAGLE head) gets its own artifact.",
     "fixtures": FX,
     "steps": [{"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "i1", "input": {"cls": "LlamaModel"}},
               {"flow": STF, "as": "a", "input": RUN},
               {"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "i2", "input": {"cls": "EagleLlamaModel"}},
               {"flow": STF, "as": "b", "input": RUN},
               {"flow": STF, "as": "a2", "input": dict(RUN, module="LlamaModel")}],
     "expect": ["steps.a.result.value.path == 'aot-compiled' && steps.b.result.value.path == 'aot-compiled' && steps.a2.result.value.path == 'aot'",
                "size(state['torch-compile-cache@rank0'].aot) == 2 && state['support-torch-compile@rank0'].num_compiles == 2"]},
]

# ====================================================================== _C::marlin_gemm host dispatch
MARLIN_REQ = {"type": "object", "required": ["m", "n", "k"], "properties": {
    "m": {"type": "integer", "minimum": 0, "examples": [16], "description": "size_m (rows of a)"},
    "n": {"type": "integer", "minimum": 1, "examples": [6144], "description": "size_n (padded output features)"},
    "k": {"type": "integer", "minimum": 1, "examples": [4096], "description": "size_k (padded input features)"},
    "dtype_bytes": {"type": "integer", "enum": [1, 2, 4], "default": 1, "examples": [1], "description": "weight element size in bytes, for the latency (1: 8-bit weights)"},
    "a_dtype": {"type": "string", "enum": ["float16", "bfloat16", "float8_e4m3fn", "int8"], "default": "bfloat16"},
    "b_type": {"type": ["string", "null"], "default": None, "examples": ["float8_e4m3fn", "uint4b8"],
               "description": "the vllm ScalarType of b_q_weight (b_type_id); null: float8_e4m3fn for 1-byte weights, else uint4b8 (GPTQ 4-bit)"},
    "b_scales_dtype": {"type": ["string", "null"], "default": None, "description": "null: the activation dtype for 16-bit a, bfloat16 otherwise"},
    "has_a_scales": {"type": "boolean", "default": False}, "has_c": {"type": "boolean", "default": False},
    "has_global_scale": {"type": "boolean", "default": False}, "has_zp": {"type": "boolean", "default": False},
    "num_groups": {"type": "integer", "default": 1, "description": "b_scales.size(0): 1 for per-channel scales"}}}
MARLIN_RESP = {"type": "object", "properties": {"kernel": {"type": "string"}, "a_type": {"type": "string"}, "b_type": {"type": "string"},
                                                "c_type": {"type": "string"}, "group_size": {"type": "integer"}, "stages": {"type": "integer"}, "launched": {"type": "boolean"}}}
D = lambda f, dflt: f"(has(input.{f}) && input.{f} != null ? input.{f} : {dflt})"
WB = "(has(input.dtype_bytes) ? double(input.dtype_bytes) : 1.0)"
OP_BEHAVIORS["torch-bindings.marlin-gemm"] = {
    "latency_ms": "= (double(config['kernel-launch-overhead-us']) + math.greatest(2.0 * double(input.m) * double(input.n) * double(input.k) / (double(config['gpu-bf16-dense-tflops']) * 1000000.0), "
                  "double(input.n) * double(input.k) * " + WB + " / (double(config['gpu-hbm-bandwidth-gbps']) * 1000.0))) / 1000.0",
    "request": MARLIN_REQ, "response": MARLIN_RESP, "errors": ERR("runtime-error"),
    "behavior": [
        {"set": {"vars.a": "= " + D("a_dtype", "'bfloat16'"),
                 "vars.b": "= " + D("b_type", "(has(input.dtype_bytes) && input.dtype_bytes != 1 ? 'uint4b8' : 'float8_e4m3fn')"),
                 "vars.a16": "= " + D("a_dtype", "'bfloat16'") + " in ['float16', 'bfloat16']",
                 "vars.as": "= " + D("has_a_scales", "false"), "vars.zp": "= " + D("has_zp", "false"),
                 "vars.gs": "= " + D("has_global_scale", "false"), "vars.ng": "= " + D("num_groups", "1")}},
        {"set": {"vars.s": "= " + D("b_scales_dtype", "(vars.a16 ? vars.a : 'bfloat16')")},
         "title": "c and scale types follow a for 16-bit activations, else b_scales' dtype", "source": src(MAR, "auto c_scalar_type = a.scalar_type();")},
        {"if": "!vars.a16 && !(vars.s in ['float16', 'bfloat16']) && !" + D("has_c", "false"), "title": "8-bit a with non-16-bit scales (W4A8-FP4) needs an explicit c",
         "source": src(MAR, 'STD_TORCH_CHECK(c_or_none.has_value(), "c must be passed for W4A8-FP4");'),
         "then": [{"fail": {"code": "runtime-error", "message": "c must be passed for W4A8-FP4"}}]},
        {"if": "vars.b == 'float4_e2m1f' && !(vars.s in ['float8_e4m3fn', 'float8_e8m0fnu'])", "title": "FP4 weights need FP8 (NVFP4) or E8M0 (MXFP4) scales",
         "source": src(MAR, '"When b_type = float4_e2m1f, b_scale scalar type must be",'),
         "then": [{"fail": {"code": "runtime-error", "message": "When b_type = float4_e2m1f, b_scale scalar type must befloat8_e4m3fn (for NVFP4) or float8_e8m0fnu (for MXFP4)."}}]},
        {"if": "input.k % 16 != 0", "title": "size_k divisible by tile_size (16)", "source": src(MAR, "size_k % MARLIN_NAMESPACE_NAME::tile_size == 0, \"size_k = \", size_k,"),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'size_k = ' + string(input.k) + ' is not divisible by tile_size = 16'"}}]},
        {"if": "vars.as && vars.a16", "title": "a_scales only for 8-bit activations", "source": src(MAR, '"a_scales can only be used for 8bit activation.");'),
         "then": [{"fail": {"code": "runtime-error", "message": "a_scales can only be used for 8bit activation."}}]},
        {"if": "!vars.as && !vars.a16", "title": "8-bit activations need a_scales", "source": src(MAR, '"the a_scales parameter must be passed for 8bit activation.");'),
         "then": [{"fail": {"code": "runtime-error", "message": "the a_scales parameter must be passed for 8bit activation."}}]},
        {"if": "input.m == 0", "title": "size_m == 0: return the empty output without launching", "source": src(MAR, "if (size_m == 0) return c;"),
         "then": [{"return": {"kernel": "", "a_type": "= vars.a", "b_type": "= vars.b", "c_type": "= vars.a16 ? vars.a : vars.s", "group_size": -1, "stages": 0, "launched": False}}]},
        {"if": "vars.ng > 1 && input.k % vars.ng != 0", "title": "Grouped scales: size_k divisible by the number of groups", "source": src(MAR, "size_k % num_groups == 0, \"size_k = \", size_k,"),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'size_k = ' + string(input.k) + ', is not divisible by b_scales.size(0) = ' + string(vars.ng)"}}]},
        {"if": "vars.gs != (vars.b == 'float4_e2m1f' && vars.s == 'float8_e4m3fn')", "title": "global_scale exactly for NVFP4",
         "source": src(MAR, '"global_scale can only be used for nvfp4 format.");'),
         "then": [{"fail": {"code": "runtime-error", "message": "= vars.gs ? 'global_scale can only be used for nvfp4 format.' : 'the global_scale parameter must be passed for nvfp4 format.'"}}]},
        {"if": "vars.zp && !(vars.b in ['uint4', 'uint8'])", "title": "Zero points only with u4 / u8 weights", "source": src(MAR, '"b_type must be u4 or u8 when has_zp = True. Got = ", b_type.str());'),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'b_type must be u4 or u8 when has_zp = True. Got = ' + vars.b"}}]},
        {"if": "!vars.zp && !(vars.b in ['uint4b8', 'uint8b128', 'int4', 'int8', 'float8_e4m3fn', 'float4_e2m1f'])",
         "title": "Without zero points: GPTQ (u4b8, u8b128), int4/int8, FP8 or FP4 weights", "source": src(MAR, "STD_TORCH_CHECK(b_type == vllm::kU4B8 || b_type == vllm::kU8B128 ||"),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'b_type must be uint4b8, uint8b128, int4, int8, float8_e4m3fn or float4_e2m1f when has_zp = False. Got = ' + vars.b"}}]},
        {"if": "input.n % 64 != 0", "title": "size_n divisible by min_thread_n (64)", "source": src(MAR, "STD_TORCH_CHECK(size_n % MARLIN_NAMESPACE_NAME::min_thread_n == 0,"),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'size_n = ' + string(input.n) + ', is not divisible by min_thread_n = 64'"}}]},
        {"set": {"vars.cap": "= state.device_capability.major * 10 + state.device_capability.minor"},
         "title": "marlin_mm: compute capability of the device (cudaDeviceGetAttribute)", "source": src(MAR, "STD_TORCH_CHECK(major_capability * 10 + minor_capability >= 75,")},
        {"if": "vars.cap < 75", "title": "Marlin needs Turing or newer", "source": src(MAR, '"marlin kernel only support Turing or newer GPUs.");'),
         "then": [{"fail": {"code": "runtime-error", "message": "marlin kernel only support Turing or newer GPUs."}}]},
        {"if": "vars.cap == 75 && !(vars.a in ['float16', 'int8'])", "title": "SM75: 2 stages, FP16 or INT8 activations only",
         "source": src(MAR, '"Turing only support FP16 or INT8 activation.");'),
         "then": [{"fail": {"code": "runtime-error", "message": "Turing only support FP16 or INT8 activation."}}]},
        {"if": "vars.a == 'float8_e4m3fn' && vars.cap < 89", "title": "FP8 activations (W4A8/W8A8-FP8) need SM89+", "source": src(MAR, '"FP8 only support Ada Lovelace or newer GPUs.");'),
         "then": [{"fail": {"code": "runtime-error", "message": "FP8 only support Ada Lovelace or newer GPUs."}}]},
        {"if": "vars.a == 'float8_e4m3fn' && vars.cap != 89 && state.device_capability.major != 12", "title": "FP8 activations only on SM89 or SM12x",
         "source": src(MAR, '"Marlin W4A8-FP8 only support SM89 or SM12x device (It is slower than "'),
         "then": [{"fail": {"code": "runtime-error", "message": "Marlin W4A8-FP8 only support SM89 or SM12x device (It is slower than Marlin W4A16 on other devices)."}}]},
        {"title": "Pick the Marlin template instance for (a, b, c, s) types and the thread config, then launch", "source": src(MAR, "auto kernel = get_marlin_kernel("),
         "return": {"kernel": "Marlin", "a_type": "= vars.a", "b_type": "= vars.b", "c_type": "= vars.a16 ? vars.a : vars.s",
                    "group_size": "= vars.ng > 1 ? input.k / vars.ng : -1", "stages": "= vars.cap == 75 ? 2 : 4", "launched": True}},
    ]}
I["custom-ops.marlin-gemm"] = {
    "component": "custom-ops", "name": "marlin-gemm", "kind": "function", "latency_ms": 0,
    "summary": "marlin_gemm(a, c, b_q_weight, ..., b_q_type, size_m, size_n, size_k, ...) -> torch.ops._C.marlin_gemm with b_q_type.id",
    "sources": [], "request": MARLIN_REQ, "response": MARLIN_RESP, "errors": ERR("runtime-error"),
    "behavior": [{"call": "torch-bindings.marlin-gemm", "input": "= input", "as": "r", "title": "torch.ops._C.marlin_gemm(a, c, b_q_weight, ..., b_q_type.id, size_m, size_n, size_k, ...)",
                  "source": src(CP, "return torch.ops._C.marlin_gemm(")},
                 {"return": "= vars.r.value"}]}

REPACK_REQ = {"type": "object", "required": ["k", "n", "num_bits"], "properties": {
    "k": {"type": "integer", "examples": [4096]}, "n": {"type": "integer", "examples": [6144]},
    "num_bits": {"type": "integer", "examples": [8], "description": "4 (GPTQ int4) or 8 (int8 / FP8 weights)"},
    "is_a_8bit": {"type": "boolean", "default": False}}}
I["custom-ops.gptq-marlin-repack"] = {  # request set below
    "component": "custom-ops", "name": "gptq-marlin-repack", "kind": "function", "latency_ms": 0,
    "summary": "gptq_marlin_repack(b_q_weight, size_k, size_n, num_bits, is_a_8bit) -> torch.ops._C.gptq_marlin_repack",
    "sources": [], "request": "REPACK", "errors": ERR("runtime-error"),
    "behavior": [{"call": "torch-bindings.gptq-marlin-repack", "input": "= input", "as": "r", "title": "torch.ops._C.gptq_marlin_repack(b_q_weight, size_k, size_n, num_bits, is_a_8bit)",
                  "source": src(CP, "    return torch.ops._C.gptq_marlin_repack(")},
                 {"return": "= vars.r.value"}]}
OP_BEHAVIORS["torch-bindings.gptq-marlin-repack"] = {
    "latency_ms": "= (double(config['kernel-launch-overhead-us']) + 2.0 * double(input.n) * double(input.k) * double(input.num_bits) / 8.0 / (double(config['gpu-hbm-bandwidth-gbps']) * 1000.0)) / 1000.0",
    "request": REPACK_REQ, "response": {"type": "object", "properties": {"repacked_rows": {"type": "integer"}, "repacked_cols": {"type": "integer"}}},
    "errors": ERR("runtime-error"),
    "behavior": [
        {"if": "input.k % 16 != 0", "title": "size_k divisible by tile_k_size (16)", "source": src(REP, "STD_TORCH_CHECK(size_k % marlin::tile_k_size == 0, \"size_k = \", size_k,"),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'size_k = ' + string(input.k) + ' is not divisible by tile_k_size = 16'"}}]},
        {"if": "input.n % 64 != 0", "title": "size_n divisible by tile_n_size (64)", "source": src(REP, "STD_TORCH_CHECK(size_n % marlin::tile_n_size == 0, \"size_n = \", size_n,"),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'size_n = ' + string(input.n) + ' is not divisible by tile_n_size = 64'"}}]},
        {"if": "input.num_bits != 4 && input.num_bits != 8", "title": "4 or 8 bits", "source": src(REP, "STD_TORCH_CHECK(num_bits == 4 || num_bits == 8,"),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'num_bits must be 4 or 8. Got = ' + string(input.num_bits)"}}]},
        {"title": "Launch gptq_marlin_repack_kernel: output [size_k / 16, size_n * 16 / pack_factor] int32", "source": src(REP, "{size_k / marlin::tile_size, size_n * marlin::tile_size / pack_factor},"),
         "return": {"repacked_rows": "= input.k / 16", "repacked_cols": "= input.n * 16 / (32 / input.num_bits)"}},
    ]}

I["custom-ops.gptq-marlin-repack"]["request"] = REPACK_REQ
A100 = {"torch-bindings": {"device_capability": {"major": 8, "minor": 0}}}
MG = lambda a, **kw: {"interface": "custom-ops.marlin-gemm", "caller": "gpu-worker", "as": a, "input": dict({"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1, "a_dtype": "bfloat16", "b_type": "float8_e4m3fn"}, **kw)}
SCENARIOS += [
    {"id": "kernels-ops-r6-marlin-fp8-weight-only-a100", "name": "FP8 checkpoint on an A100: no CUTLASS FP8 (SM80), the weight-only FP8 Marlin GEMM runs with BF16 activations",
     "description": "judge4 P4-3(c), the kernels-ops half: cutlass_scaled_mm_supports_fp8(80) is false (scaled_mm_entry.cu:145-159) and _C::cutlass_scaled_mm on SM80 is INT8 only; "
                    "the Marlin path (marlin_utils_fp8.py:86-101 -> marlin_utils.py:458 -> _C::marlin_gemm) repacks the FP8 weight with num_bits 8 and runs a W8A16 GEMM, "
                    "which needs only SM75+ (marlin.cu:287-301). The fallback choice itself is models-layers' (kernels/linear/__init__.py).",
     "fixtures": FP8W, "state": A100,
     "steps": [{"interface": "custom-ops.cutlass-scaled-mm-supports-fp8", "caller": "gpu-worker", "as": "sup", "input": {"cuda_device_capability": 80}},
               {"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "cutlass", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1}},
               {"interface": "custom-ops.gptq-marlin-repack", "caller": "gpu-worker", "as": "rep", "input": {"k": 4096, "n": 6144, "num_bits": 8}},
               MG("mm"), MG("decode", m=1)],
     "expect": ["!steps.sup.result.value.supported", "!steps.cutlass.result.ok && steps.cutlass.result.error.code == 'runtime-error'",
                "steps.rep.result.ok && steps.rep.result.value.repacked_rows == 256 && steps.rep.result.value.repacked_cols == 24576",
                "steps.mm.result.ok && steps.mm.result.value.kernel == 'Marlin' && steps.mm.result.value.b_type == 'float8_e4m3fn' && steps.mm.result.value.c_type == 'bfloat16' && steps.mm.result.value.stages == 4",
                "steps.decode.result.ok && steps.decode.duration_us > 0 && steps.decode.duration_us < steps.mm.duration_us + 1"]},
    {"id": "kernels-ops-r6-marlin-capability-checks", "name": "Marlin refuses FP8 activations before Ada, BF16 activations on Turing, and anything before Turing",
     "fixtures": FP8W, "state": A100,
     "steps": [MG("w8a8", a_dtype="float8_e4m3fn", has_a_scales=True)],
     "expect": ["!steps.w8a8.result.ok && steps.w8a8.result.error.code == 'runtime-error' && steps.w8a8.result.error.message == 'FP8 only support Ada Lovelace or newer GPUs.'"]},
    {"id": "kernels-ops-r6-marlin-turing", "name": "On SM75 Marlin runs FP16 activations with 2 stages and refuses BF16",
     "fixtures": FP8W, "state": {"torch-bindings": {"device_capability": {"major": 7, "minor": 5}}},
     "steps": [MG("fp16", a_dtype="float16"), MG("bf16")],
     "expect": ["steps.fp16.result.ok && steps.fp16.result.value.stages == 2",
                "!steps.bf16.result.ok && steps.bf16.result.error.message == 'Turing only support FP16 or INT8 activation.'"]},
    {"id": "kernels-ops-r6-marlin-volta", "name": "On SM70 Marlin is refused outright",
     "fixtures": FP8W, "state": {"torch-bindings": {"device_capability": {"major": 7, "minor": 0}}},
     "steps": [MG("v100", a_dtype="float16")],
     "expect": ["!steps.v100.result.ok && steps.v100.result.error.message == 'marlin kernel only support Turing or newer GPUs.'"]},
    {"id": "kernels-ops-r6-marlin-fp8-act-sm89", "name": "W4A8-FP8 Marlin runs on an L40S (SM89) but not on an H100 (SM90)",
     "fixtures": FP8W, "state": {"torch-bindings": {"device_capability": {"major": 8, "minor": 9}}},
     "steps": [MG("l40s", a_dtype="float8_e4m3fn", has_a_scales=True, b_type="uint4b8", b_scales_dtype="bfloat16", num_groups=32)],
     "expect": ["steps.l40s.result.ok && steps.l40s.result.value.a_type == 'float8_e4m3fn' && steps.l40s.result.value.group_size == 128"]},
    {"id": "kernels-ops-r6-marlin-fp8-act-sm90-refused", "name": "W4A8-FP8 Marlin on SM90 is refused (slower than W4A16 there)",
     "fixtures": FP8W,
     "steps": [MG("h100", a_dtype="float8_e4m3fn", has_a_scales=True, b_type="uint4b8", b_scales_dtype="bfloat16")],
     "expect": ["!steps.h100.result.ok && steps.h100.result.error.message == 'Marlin W4A8-FP8 only support SM89 or SM12x device (It is slower than Marlin W4A16 on other devices).'"]},
    {"id": "kernels-ops-r6-marlin-shape-checks", "name": "Marlin shape and argument checks, in the code's order",
     "fixtures": FP8W, "state": A100,
     "steps": [MG("k", k=4104), MG("ascale", has_a_scales=True), MG("noascale", a_dtype="int8"), MG("n", n=6150),
               MG("groups", num_groups=3), MG("zp", has_zp=True), MG("btype", b_type="float16"), MG("empty", m=0),
               MG("fp4", b_type="float4_e2m1f", b_scales_dtype="bfloat16"), MG("nvfp4", b_type="float4_e2m1f", b_scales_dtype="float8_e4m3fn"),
               MG("w4a8fp4", a_dtype="float8_e4m3fn", has_a_scales=True, b_scales_dtype="float8_e8m0fnu", b_type="float4_e2m1f"),
               {"interface": "custom-ops.gptq-marlin-repack", "caller": "gpu-worker", "as": "rep3", "input": {"k": 4096, "n": 6144, "num_bits": 3}},
               {"interface": "custom-ops.gptq-marlin-repack", "caller": "gpu-worker", "as": "repk", "input": {"k": 4100, "n": 6144, "num_bits": 8}},
               {"interface": "custom-ops.gptq-marlin-repack", "caller": "gpu-worker", "as": "repn", "input": {"k": 4096, "n": 100, "num_bits": 8}}],
     "expect": ["steps.k.result.error.message == 'size_k = 4104 is not divisible by tile_size = 16'",
                "steps.ascale.result.error.message == 'a_scales can only be used for 8bit activation.'",
                "steps.noascale.result.error.message == 'the a_scales parameter must be passed for 8bit activation.'",
                "steps.n.result.error.message == 'size_n = 6150, is not divisible by min_thread_n = 64'",
                "steps.groups.result.error.message == 'size_k = 4096, is not divisible by b_scales.size(0) = 3'",
                "steps.zp.result.error.message == 'b_type must be u4 or u8 when has_zp = True. Got = float8_e4m3fn'",
                "steps.btype.result.error.message == 'b_type must be uint4b8, uint8b128, int4, int8, float8_e4m3fn or float4_e2m1f when has_zp = False. Got = float16'",
                "steps.empty.result.ok && !steps.empty.result.value.launched",
                "steps.fp4.result.error.message.startsWith('When b_type = float4_e2m1f')",
                "steps.nvfp4.result.error.message == 'the global_scale parameter must be passed for nvfp4 format.'",
                "steps.w4a8fp4.result.error.message == 'c must be passed for W4A8-FP4'",
                "steps.rep3.result.error.message == 'num_bits must be 4 or 8. Got = 3'",
                "steps.repk.result.error.message == 'size_k = 4100 is not divisible by tile_k_size = 16'",
                "steps.repn.result.error.message == 'size_n = 100 is not divisible by tile_n_size = 64'"]},
]

# ====================================================================== breakable CUDA graphs
CONFIGS.append(cfg("vllm-use-breakable-cudagraph", "boolean", False, False,
                   "VLLM_USE_BREAKABLE_CUDAGRAPH: capture the whole forward in one BreakableCUDAGraphCapture, ending the stream capture at each "
                   "@eager_break_during_capture op (attention, KV-cache writes) and running it eagerly, instead of FX graph splitting.",
                   [src(ENVS, "VLLM_USE_BREAKABLE_CUDAGRAPH: bool = False"), src(ENVS, '"VLLM_USE_BREAKABLE_CUDAGRAPH": lambda: (', span=2), src(BCG, "return bool(envs.VLLM_USE_BREAKABLE_CUDAGRAPH)")],
                   "VLLM_USE_BREAKABLE_CUDAGRAPH", env=True))
COMPONENTS.append(comp("breakable-cuda-graph-wrapper", "BreakableCUDAGraphWrapper", "module",
                       "Drop-in for CUDAGraphWrapper: per batch descriptor, captures the forward once in a BreakableCUDAGraphCapture and replays its segments.",
                       [src(BCG, "class BreakableCUDAGraphWrapper:")], parent="compilation",
                       state={"schema": {"type": "object", "properties": {"entries": {"type": "object", "description": "batch descriptor -> {num_graphs, num_eager_breaks, segments, input_addresses}"}, "cleared_generation": {"type": "integer", "description": "bumped by clear_all_graphs: entries of an earlier generation no longer match"}}},
                              "initial": {"entries": {}, "cleared_generation": 0}}, capacity={"concurrency": 1}))
COMPONENTS.append(comp("breakable-cuda-graph-capture", "BreakableCUDAGraphCapture", "module",
                       "The thread-local stream-capture context: a list of segments, each a captured CUDA graph or an eager op recorded for replay.",
                       [src(BCG, "class BreakableCUDAGraphCapture:")], parent="compilation",
                       state={"schema": {"type": "object", "properties": {
                           "active": {"type": "boolean", "description": "BreakableCUDAGraphCapture._tls.active is set"},
                           "capturing": {"type": "boolean"}, "num_graphs": {"type": "integer"}, "num_eager_breaks": {"type": "integer"},
                           "segments": {"type": "array", "items": {"type": "string"}}}},
                           "initial": {"active": False, "capturing": False, "num_graphs": 0, "num_eager_breaks": 0, "segments": []}}, capacity={"concurrency": 1}))

END_SEG = [{"if": "state.capturing", "title": "_end_segment: capture_end, append graph.replay, num_graphs += 1", "source": src(BCG, "self._current_graph.capture_end()"),
            "then": [{"set": {"state.segments": "= state.segments + ['graph']", "state.num_graphs": "= state.num_graphs + 1", "state.capturing": False}}]}]
BREAK_REQ = {"type": "object", "properties": {"op": {"type": "string", "default": "unified_attention_with_output", "examples": ["unified_attention_with_output"]},
                                              "runtime_mode": {"type": ["string", "null"], "default": None, "enum": ["NONE", "PIECEWISE", "FULL", None],
                                                               "description": "the forward context's cudagraph_runtime_mode; null: no forward context"}}}
iface("breakable-cuda-graph-capture", "eager-break", kind="function", latency_ms=0,
      summary="@eager_break_during_capture: inside an active capture (and not FULL mode) end the segment, run the op eagerly, record it, and begin a new segment; otherwise run the op.",
      sources=[src(BCG, "def eager_break_during_capture(fn: F) -> F:", span=53), src(BCG, "    def add_eager(self, fn: Callable[[], Any]) -> Any:", span=13)],
      request=BREAK_REQ, response={"type": "object", "properties": {"path": {"type": "string"}}},
      behavior=[
          {"if": "!config['vllm-use-breakable-cudagraph']", "title": "Breakable graphs off: the decorator returns the op unchanged", "source": src(BCG, "    if not is_breakable_cudagraph_enabled():"),
           "then": [{"return": {"path": "undecorated"}}]},
          {"if": "!state.active || !state.capturing", "title": "No capture (or between segments): run the op", "source": src(BCG, "        if capture is None:"),
           "then": [{"return": {"path": "direct"}}]},
          {"if": "has(input.runtime_mode) && input.runtime_mode == 'FULL'", "title": "FULL mode: the op is captured into the single graph", "source": src(BCG, "            if mode == CUDAGraphMode.FULL:"),
           "then": [{"return": {"path": "captured"}}]},
      ] + END_SEG + [
          {"set": {"state.segments": "= state.segments + ['eager:' + (has(input.op) ? input.op : 'unified_attention_with_output')]", "state.num_eager_breaks": "= state.num_eager_breaks + 1"},
           "title": "add_eager: run fn now on the capture stream, record it for replay (weak-ref arguments)", "source": src(BCG, "        self._num_eager_breaks += 1")},
          {"set": {"state.capturing": True}, "title": "_begin_segment: a new CUDAGraph.capture_begin(pool)", "source": src(BCG, "        self._capturing = True")},
          {"return": {"path": "eager-break"}},
      ])
iface("breakable-cuda-graph-capture", "capture", kind="function", latency_ms="= config['cudagraph-capture-overhead-ms']",
      summary="with BreakableCUDAGraphCapture(pool): set the thread-local capture, begin a segment, run the forward (each break-point op splits the capture), end the last segment.",
      sources=[src(BCG, "    def __enter__(self) -> BreakableCUDAGraphCapture:", span=12), src(BCG, "    def _begin_segment(self) -> None:", span=18)],
      request={"type": "object", "properties": {"break_ops": {"type": "integer", "examples": [32], "description": "break-point op calls in the forward (one attention per layer)"},
                                                "runtime_mode": {"type": "string", "default": "PIECEWISE"}}},
      response={"type": "object", "properties": {"num_graphs": {"type": "integer"}, "num_eager_breaks": {"type": "integer"}, "num_segments": {"type": "integer"}}},
      errors=ERR("runtime-error"),
      behavior=[
          {"if": "state.active", "title": "Only one capture per thread", "source": src(BCG, 'raise RuntimeError("Nested BreakableCUDAGraphCapture is not supported.")'),
           "then": [{"fail": {"code": "runtime-error", "message": "Nested BreakableCUDAGraphCapture is not supported."}}]},
          {"set": {"state.active": True, "state.capturing": True, "state.segments": [], "state.num_graphs": 0, "state.num_eager_breaks": 0},
           "title": "_tls.active = self; _begin_segment()", "source": src(BCG, "        BreakableCUDAGraphCapture._tls.active = self")},
          {"foreach": "= [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79].slice(0, input.break_ops)",
           "as": "i", "max": 80, "title": "output = self.runnable(*args): the forward reaches each break-point op in turn", "source": src(BCG, "            output = self.runnable(*args, **kwargs)"),
           "steps": [{"call": "breakable-cuda-graph-capture.eager-break", "input": {"runtime_mode": "= input.runtime_mode"}}]},
      ] + END_SEG + [
          {"set": {"state.active": False}, "title": "__exit__: _end_segment(), then clear the thread-local", "source": src(BCG, "            BreakableCUDAGraphCapture._tls.active = None")},
          {"return": {"num_graphs": "= state.num_graphs", "num_eager_breaks": "= state.num_eager_breaks", "num_segments": "= size(state.segments)"}},
      ])
iface("breakable-cuda-graph-wrapper", "clear-all-graphs", kind="function", latency_ms=0,
      summary="BreakableCUDAGraphWrapper.clear_all_graphs: clear every instance's captured entries, so the next use of a batch descriptor captures again.",
      sources=[src(BCG, "    def clear_all_graphs(cls) -> None:", span=3), src(BCG, "    def clear_graphs(self) -> None:", span=2)],
      response={"type": "object", "properties": {"cleared": {"type": "boolean"}}},
      behavior=[
          {"set": {"state.cleared_generation": "= seq('breakable-graph-clear')"}, "title": "self.entries.clear(): every captured descriptor is forgotten (a new generation, so the single-threaded capture path needs no second writer of the entries)", "source": src(BCG, "    def clear_graphs(self) -> None:", span=2)},
          {"return": {"cleared": True}},
      ])
iface("breakable-cuda-graph-wrapper", "call", kind="function", latency_ms=0,
      summary="BreakableCUDAGraphWrapper.__call__: eager without a forward context or in NONE / another wrapper's mode; else capture once per batch descriptor and replay afterwards.",
      sources=[src(BCG, "    def __call__(self, *args: Any, **kwargs: Any) -> Any:", span=25), src(BCG, "    def _capture(", span=46), src(BCG, "    def _replay(", span=18)],
      request={"type": "object", "properties": {
          "num_tokens": {"type": "integer", "examples": [16]}, "uniform_decode": {"type": "boolean", "default": True},
          "runtime_mode": {"type": "string", "enum": ["NONE", "PIECEWISE", "FULL"], "examples": ["PIECEWISE"]},
          "wrapper_runtime_mode": {"type": ["string", "null"], "default": None, "description": "the wrapper's runtime_mode; null matches any non-NONE mode"},
          "forward_context": {"type": "boolean", "default": True}, "debug": {"type": "boolean", "default": False},
          "input_addresses": {"type": "array", "items": {"type": "integer"}, "examples": [[140000000]]},
          "num_layers": {"type": "integer", "examples": [32], "description": "one break-point attention op per layer"}}},
      response={"type": "object", "properties": {"path": {"type": "string"}, "num_graphs": {"type": "integer"}, "num_eager_breaks": {"type": "integer"}}},
      errors=ERR("runtime-error", "assertion-error"),
      behavior=[
          {"if": "has(input.forward_context) && !input.forward_context", "title": "No forward context: run the model eagerly", "source": src(BCG, "        if not is_forward_context_available():", start=310),
           "then": [{"return": {"path": "eager"}}]},
          {"if": "input.runtime_mode == 'NONE' || (has(input.wrapper_runtime_mode) && input.wrapper_runtime_mode != null && input.runtime_mode != input.wrapper_runtime_mode)",
           "title": "Mode NONE, or a mode another wrapper handles: eager", "source": src(BCG, "        if cudagraph_runtime_mode == CUDAGraphMode.NONE or ("),
           "then": [{"return": {"path": "eager"}}]},
          {"set": {"vars.key": "= string(input.num_tokens) + (has(input.uniform_decode) && !input.uniform_decode ? '' : '-uniform') + (state.cleared_generation == 0 ? '' : '-gen' + string(state.cleared_generation))"},
           "title": "entries keyed by the BatchDescriptor", "source": src(BCG, "        entry = self.entries.get(batch_descriptor)")},
          {"if": "!(vars.key in state.entries)", "title": "First use of this descriptor: _capture", "source": src(BCG, "            return self._capture(entry, args, kwargs)"),
           "then": [
               {"call": "compilation-monitor.validate-cudagraph-capturing-enabled", "input": {}, "title": "validate_cudagraph_capturing_enabled()", "source": src(BCG, "        validate_cudagraph_capturing_enabled()", start=360)},
               {"call": "breakable-cuda-graph-capture.capture", "input": {"break_ops": "= input.num_layers", "runtime_mode": "= input.runtime_mode"}, "as": "cap",
                "title": "with capture_pool(...), BreakableCUDAGraphCapture(pool=pool) as capture: output = self.runnable(...)", "source": src(BCG, "            BreakableCUDAGraphCapture(pool=pool) as capture,")},
               {"set": {"= 'state.entries.' + vars.key": "= {'num_graphs': vars.cap.value.num_graphs, 'num_eager_breaks': vars.cap.value.num_eager_breaks, 'segments': vars.cap.value.num_segments, 'input_addresses': has(input.input_addresses) ? input.input_addresses : []}"},
                "title": "entry.capture = capture; entry.output = weak_ref_tensors(output)", "source": src(BCG, "        entry.capture = capture")},
               {"return": {"path": "capture", "num_graphs": "= vars.cap.value.num_graphs", "num_eager_breaks": "= vars.cap.value.num_eager_breaks"}}]},
          {"set": {"vars.e": "= state.entries[vars.key]"}},
          {"if": "has(input.debug) && input.debug && has(input.input_addresses) && input.input_addresses != vars.e.input_addresses",
           "title": "DEBUG: input addresses must not move between capture and replay", "source": src(BCG, '"Input tensor addresses changed between capture and replay "'),
           "then": [{"fail": {"code": "assertion-error", "message": "= 'Input tensor addresses changed between capture and replay for BatchDescriptor(num_tokens=' + string(input.num_tokens) + '). Expected ' + string(vars.e.input_addresses) + ', got ' + string(input.input_addresses) + '.'"}}]},
          {"title": "capture.replay(): every segment in order (graph replays and the recorded eager ops)", "source": src(BCG, "        for r in self.segments:"),
           "wait": "= double(vars.e.segments) * double(config['kernel-launch-overhead-us']) / 1000.0"},
          {"return": {"path": "replay", "num_graphs": "= vars.e.num_graphs", "num_eager_breaks": "= vars.e.num_eager_breaks"}},
      ])
BGF = "kernels-ops-breakable-cuda-graph"
FLOWS.append({"id": BGF, "name": "Breakable CUDA graph capture and replay", "tags": ["writes", "feature:cuda-graphs"],
              "description": "With VLLM_USE_BREAKABLE_CUDAGRAPH the model runner wraps the model in BreakableCUDAGraphWrapper (gpu_model_runner.py): a new batch descriptor "
                             "captures the whole forward, splitting the stream capture at each attention op; later steps replay the segments.",
              "entry": {"caller": "gpu-worker", "interface": "breakable-cuda-graph-wrapper.call",
                        "input": {"num_tokens": 16, "uniform_decode": True, "runtime_mode": "PIECEWISE", "forward_context": True, "debug": False, "input_addresses": [140000000], "num_layers": 32}},
              "sources": [src(BCG, "    def __call__(self, *args: Any, **kwargs: Any) -> Any:", start=310)]})
BGR = "kernels-ops-breakable-cuda-graph-replay"
FLOWS.append({"id": BGR, "name": "Breakable CUDA graph replay during serving", "tags": ["feature:cuda-graphs"],
              "description": "A serving step whose batch descriptor was captured replays the recorded segments (graph replays and eager attention) through the same wrapper.",
              "entry": dict(FLOWS[-1]["entry"]), "sources": [src(BCG, "        entry.capture.replay()")]})
BCFG = {"vllm-use-breakable-cudagraph": True}
SCENARIOS += [
    {"id": "kernels-ops-r6-breakable-capture-then-replay", "name": "Llama-8B decode batch of 16: capture splits at the 32 attention ops (33 graphs, 32 eager breaks), the next step replays",
     "flow": BGF, "fixtures": FX, "config": BCFG, "steps": [{"flow": BGF, "as": "cap"}, {"flow": BGR, "as": "rep"}],
     "expect": ["steps.cap.result.value.path == 'capture' && steps.cap.result.value.num_graphs == 33 && steps.cap.result.value.num_eager_breaks == 32",
                "steps.rep.result.value.path == 'replay' && steps.rep.result.value.num_graphs == 33",
                "state['breakable-cuda-graph-wrapper@rank0'].entries['16-uniform'].segments == 65 && !state['breakable-cuda-graph-capture@rank0'].active"]},
    {"id": "kernels-ops-r6-breakable-full-mode", "name": "FULL runtime mode: break-point ops are captured inline, one graph",
     "flow": BGF, "fixtures": FX, "config": BCFG, "input": {"runtime_mode": "FULL"},
     "expect": ["result.ok && result.value.path == 'capture' && result.value.num_graphs == 1 && result.value.num_eager_breaks == 0",
                "state['breakable-cuda-graph-wrapper@rank0'].entries['16-uniform'].segments == 1"]},
    {"id": "kernels-ops-r6-breakable-eager-modes", "name": "No forward context, mode NONE, or a mode the wrapper is not for: eager, nothing captured",
     "flow": BGF, "fixtures": FX, "config": BCFG,
     "steps": [{"flow": BGF, "as": "noctx", "input": {"forward_context": False}}, {"flow": BGF, "as": "none", "input": {"runtime_mode": "NONE"}},
               {"flow": BGF, "as": "other", "input": {"runtime_mode": "FULL", "wrapper_runtime_mode": "PIECEWISE"}}],
     "expect": ["steps.noctx.result.value.path == 'eager' && steps.none.result.value.path == 'eager' && steps.other.result.value.path == 'eager'",
                "size(state['breakable-cuda-graph-wrapper@rank0'].entries) == 0"]},
    {"id": "kernels-ops-r6-breakable-capture-disabled", "name": "Capture after the capture phase ended is refused by the compilation monitor",
     "flow": BGF, "fixtures": FX, "config": BCFG, "state": {"compilation-monitor": {"cudagraph_capturing_enabled": False}},
     "expect": ["!result.ok && result.error.code == 'runtime-error' && result.error.message == 'CUDA graph capturing detected at an inappropriate time. This operation is currently disabled.'",
                "size(state['breakable-cuda-graph-wrapper@rank0'].entries) == 0"]},
    {"id": "kernels-ops-r6-breakable-nested", "name": "A capture while another is active on the thread is refused",
     "fixtures": FX, "config": BCFG, "state": {"breakable-cuda-graph-capture": {"active": True}},
     "steps": [{"interface": "breakable-cuda-graph-capture.capture", "caller": "gpu-worker", "as": "n", "input": {"break_ops": 2}}],
     "expect": ["!steps.n.result.ok && steps.n.result.error.message == 'Nested BreakableCUDAGraphCapture is not supported.'"]},
    {"id": "kernels-ops-r6-breakable-off", "name": "With VLLM_USE_BREAKABLE_CUDAGRAPH unset the decorated op is the plain op; outside a capture it runs directly",
     "fixtures": FX,
     "steps": [{"interface": "breakable-cuda-graph-capture.eager-break", "caller": "gpu-worker", "as": "off", "input": {"runtime_mode": "PIECEWISE"}}],
     "expect": ["steps.off.result.value.path == 'undecorated'"]},
    {"id": "kernels-ops-r6-breakable-direct-and-debug", "name": "Outside a capture the op runs directly; in DEBUG a replay with moved inputs fails the address check",
     "flow": BGF, "fixtures": FX, "config": BCFG,
     "steps": [{"interface": "breakable-cuda-graph-capture.eager-break", "caller": "gpu-worker", "as": "direct", "input": {"runtime_mode": "PIECEWISE"}},
               {"flow": BGF, "as": "cap", "input": {"num_layers": 2}}, {"flow": BGF, "as": "moved", "input": {"num_layers": 2, "debug": True, "input_addresses": [150000000]}}],
     "expect": ["steps.direct.result.value.path == 'direct' && steps.cap.result.value.num_graphs == 3",
                "!steps.moved.result.ok && steps.moved.result.error.message == 'Input tensor addresses changed between capture and replay for BatchDescriptor(num_tokens=16). Expected [140000000], got [150000000].'",
                "state['breakable-cuda-graph-wrapper@rank0'].entries['16-uniform'].num_eager_breaks == 2"]},
]

# ====================================================================== DeepGEMM scale-format oracle (quantization dispatch)
COMPONENT_PATCHES["deep-gemm-utils"] = {"oracle_cache": None}
PROBE = {"type": "object", "properties": {
    "installed": {"type": "array", "items": {"type": "string"}, "default": ["deep_gemm"]},
    "device_capability": {"type": "integer", "default": 90},
    "fp8_gemm_nt_found": {"type": "boolean", "default": True, "description": "_lazy_init resolved deep_gemm.fp8_gemm_nt"}}}
iface("deep-gemm-utils", "quant-scale-fmt-from-oracle", kind="function", latency_ms=0,
      summary="DeepGemmQuantScaleFMT.from_oracle: the cached block-FP8 scale format: FLOAT32 without E8M0; UE8M0 (packed int32) on the Blackwell families SM100/SM120; FLOAT32_CEIL_UE8M0 otherwise (Hopper).",
      sources=[src(DG, "class DeepGemmQuantScaleFMT(Enum):", span=52)],
      request=PROBE, response={"type": "object", "properties": {"fmt": {"type": "string"}, "cached": {"type": "boolean"}}},
      behavior=[
          {"if": "state.oracle_cache != null", "title": "The decision is made once per process", "source": src(DG, '        cached = getattr(cls, "_oracle_cache", None)', nth=2),
           "then": [{"return": {"fmt": "= state.oracle_cache", "cached": True}}]},
          {"call": "deep-gemm-utils.is-deep-gemm-supported", "input": {"installed": "= has(input.installed) ? input.installed : ['deep_gemm']", "device_capability": "= has(input.device_capability) ? input.device_capability : 90"},
           "as": "s", "title": "_lazy_init(); init_oracle_cache()", "source": src(DG, "            cls.init_oracle_cache()")},
          {"if": "!(config['vllm-use-deep-gemm-e8m0'] && vars.s.value.supported && (!has(input.fp8_gemm_nt_found) || input.fp8_gemm_nt_found))",
           "title": "use_e8m0 = VLLM_USE_DEEP_GEMM_E8M0 and is_deep_gemm_supported() and fp8_gemm_nt resolved; else FLOAT32", "source": src(DG, "        if not use_e8m0:"),
           "then": [{"set": {"state.oracle_cache": "FLOAT32"}}, {"return": {"fmt": "FLOAT32", "cached": False}}]},
          {"set": {"vars.cap": "= has(input.device_capability) ? input.device_capability : 90"}},
          {"set": {"state.oracle_cache": "= (vars.cap / 10 == 10 || vars.cap / 10 == 12) ? 'UE8M0' : 'FLOAT32_CEIL_UE8M0'"},
           "title": "is_device_capability_family(100) or (120): capability // 10 matches", "source": src(DG, "                current_platform.is_device_capability_family(100)")},
          {"return": {"fmt": "= state.oracle_cache", "cached": False}},
      ])
SCENARIOS += [
    {"id": "kernels-ops-r6-deep-gemm-scale-fmt", "name": "DeepGEMM scale format: Hopper ceils FP32 scales to UE8M0, the answer is cached for the process",
     "fixtures": FX,
     "steps": [{"interface": "deep-gemm-utils.quant-scale-fmt-from-oracle", "caller": "gpu-worker", "as": "h100", "input": {"installed": ["deep_gemm"], "device_capability": 90}},
               {"interface": "deep-gemm-utils.quant-scale-fmt-from-oracle", "caller": "gpu-worker", "as": "again", "input": {"installed": ["deep_gemm"], "device_capability": 100}}],
     "expect": ["steps.h100.result.value.fmt == 'FLOAT32_CEIL_UE8M0' && !steps.h100.result.value.cached",
                "steps.again.result.value.fmt == 'FLOAT32_CEIL_UE8M0' && steps.again.result.value.cached", "state['deep-gemm-utils@rank0'].oracle_cache == 'FLOAT32_CEIL_UE8M0'"]},
    {"id": "kernels-ops-r6-deep-gemm-scale-fmt-blackwell", "name": "DeepGEMM scale format on a B200 packs UE8M0; without DeepGEMM or with E8M0 off it is FLOAT32",
     "fixtures": FX,
     "steps": [{"interface": "deep-gemm-utils.quant-scale-fmt-from-oracle", "caller": "gpu-worker", "as": "b200", "input": {"installed": ["vllm.third_party.deep_gemm"], "device_capability": 100}}],
     "expect": ["steps.b200.result.value.fmt == 'UE8M0'", "state['deep-gemm-utils@rank0'].oracle_cache == 'UE8M0'"]},
    {"id": "kernels-ops-r6-deep-gemm-scale-fmt-float32", "name": "No DeepGEMM package (or VLLM_USE_DEEP_GEMM_E8M0=0): FLOAT32 scales",
     "fixtures": FX,
     "steps": [{"interface": "deep-gemm-utils.quant-scale-fmt-from-oracle", "caller": "gpu-worker", "as": "none", "input": {"installed": [], "device_capability": 90}}],
     "expect": ["steps.none.result.value.fmt == 'FLOAT32'", "state['deep-gemm-utils@rank0'].oracle_cache == 'FLOAT32'"]},
]

# ====================================================================== Triton kernel override registry (platform kernel choice)
COMPONENTS.append(comp("triton-kernel-dispatcher", "Triton kernel overrides", "module",
                       "vllm/triton_utils/dispatcher.py: platforms register replacements for named Triton kernels; every holder of the kernel is rebound to a KernelOverride that routes launches to the replacement.",
                       [src(DISP, "def register_kernels(overrides: Mapping[str, Callable[..., Any]]) -> None:")], parent="kernels-ops",
                       state={"schema": {"type": "object", "properties": {"registry": {"type": "object", "description": "kernel name -> {impl, arg_names, forward_by_name}"}}}, "initial": {"registry": {}}},
                       capacity={"concurrency": 1}))
iface("triton-kernel-dispatcher", "register-kernels", kind="function", latency_ms=0,
      summary="register_kernels(overrides): resolve each fully qualified kernel name, wrap it in a KernelOverride, rebind every module attribute and JIT warmup owner holding it, then the defining attribute.",
      sources=[src(DISP, "def register_kernels(overrides: Mapping[str, Callable[..., Any]]) -> None:", span=28), src(DISP, "def _resolve_kernel(name: str) -> tuple[Any, str]:", span=11)],
      request={"type": "object", "required": ["overrides"], "properties": {"overrides": {"type": "array", "items": {"type": "object", "properties": {
          "name": {"type": "string", "examples": ["vllm.v1.sample.rejection_sampler.expand_kernel"]}, "impl": {"type": "string", "examples": ["expand_kernel_impl"]},
          "kernel_params": {"type": "array", "items": {"type": "string"}}, "impl_params": {"type": "array", "items": {"type": "string"}},
          "found": {"type": "boolean", "default": True, "description": "the module (or class) defines the attribute"}}}}}},
      response={"type": "object", "properties": {"registered": {"type": "array", "items": {"type": "string"}}, "overwritten": {"type": "array", "items": {"type": "string"}}}},
      errors=ERR("value-error"),
      behavior=[
          {"set": {"vars.over": "= input.overrides.filter(o, o.name.replace('.', '__') in state.registry).map(o, o.name)"},
           "title": "An already registered name is overwritten with a warning", "source": src(DISP, 'logger.warning("Kernel %s is already registered. Overwriting.", name)')},
          {"foreach": "= input.overrides", "as": "o", "title": "_resolve_kernel(name): the module (or class) must hold the attribute", "source": src(DISP, "        host, attr = _resolve_kernel(name)"),
           "steps": [{"if": "has(vars.o.found) && !vars.o.found", "source": src(DISP, "raise ValueError(f\"Kernel {name!r} not found for override\")"),
                      "then": [{"fail": {"code": "value-error", "message": "= \"Kernel '\" + vars.o.name + \"' not found for override\""}}]}]},
          {"foreach": "= input.overrides", "as": "o", "title": "KernelOverride(original, impl): keep the kernel's arg names; forward by keyword when the impl's parameters match",
           "source": src(DISP, "            tuple(inspect.signature(impl).parameters) == self.arg_names"),
           "steps": [{"set": {"= 'state.registry.' + vars.o.name.replace('.', '__')": "= {'name': vars.o.name, 'impl': vars.o.impl, 'arg_names': vars.o.kernel_params, 'forward_by_name': vars.o.impl_params == vars.o.kernel_params}"}}]},
          {"title": "_rebind_kernels then setattr(host, attr, wrapper): every holder now launches the override", "source": src(DISP, "    _rebind_kernels([(original, wrapper) for *_, original, wrapper in resolved])"),
           "return": {"registered": "= input.overrides.map(o, o.name)", "overwritten": "= vars.over"}},
      ])
iface("triton-kernel-dispatcher", "launch", kind="function", latency_ms=0,
      summary="kernel[grid](...) on a Triton kernel: the original Triton kernel when no override is registered, else KernelOverride._launch: positional, by keyword, or keyword arguments reordered into the kernel's parameter order.",
      sources=[src(DISP, "    def _launch(self, *args: Any, **kwargs: Any) -> Any:", span=12)],
      request={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}, "positional": {"type": "boolean", "default": False},
                                                                      "kwargs": {"type": "array", "items": {"type": "string"}, "default": []}}},
      response={"type": "object", "properties": {"runs": {"type": "string"}, "binding": {"type": "string"}}},
      errors=ERR("runtime-error"),
      behavior=[
          {"set": {"vars.k": "= input.name.replace('.', '__')"}},
          {"if": "!(vars.k in state.registry)", "title": "No override: the Triton JIT kernel launches", "then": [{"return": {"runs": "triton", "binding": "native"}}]},
          {"set": {"vars.o": "= state.registry[vars.k]"}},
          {"if": "has(input.positional) && input.positional", "title": "Positional launch arguments go straight to impl", "source": src(DISP, "        if args:", start=60),
           "then": [{"return": {"runs": "= vars.o.impl", "binding": "positional"}}]},
          {"if": "vars.o.forward_by_name", "title": "Same parameter names: forward by keyword", "source": src(DISP, "        if self._forward_by_name:"),
           "then": [{"return": {"runs": "= vars.o.impl", "binding": "keyword"}}]},
          {"set": {"vars.bad": "= (has(input.kwargs) ? input.kwargs : []).filter(n, !(n in vars.o.arg_names))"}},
          {"if": "size(vars.bad) > 0", "title": "A launch keyword the kernel does not declare", "source": src(DISP, 'f"Override for {self.__name__!r} received unexpected launch "'),
           "then": [{"fail": {"code": "runtime-error", "message": "= \"Override for '\" + vars.o.impl + \"' received unexpected launch arguments: ['\" + vars.bad.join(\"', '\") + \"']\""}}]},
          {"return": {"runs": "= vars.o.impl", "binding": "reordered"}, "title": "Keyword arguments reordered into the kernel's parameter order", "source": src(DISP, "        return self._impl(*(kwargs[name] for name in self.arg_names if name in kwargs))")},
      ])
KN = "vllm.v1.sample.rejection_sampler.expand_kernel"
OV = {"name": KN, "impl": "expand_kernel_xpu", "kernel_params": ["output_ptr", "input_ptr", "cu_num_tokens_ptr", "replace_from", "replace_to", "MAX_NUM_TOKENS"],
      "impl_params": ["out", "inp", "cu_num_tokens", "replace_from", "replace_to", "max_num_tokens"]}
TKF = "kernels-ops-triton-kernel-override"
FLOWS.append({"id": TKF, "name": "Platform Triton kernel overrides", "tags": ["writes"],
              "description": "An out-of-tree platform registers replacements for named Triton kernels at startup; later launches of those kernels run the replacement.",
              "entry": {"caller": "gpu-worker", "interface": "triton-kernel-dispatcher.register-kernels", "input": {"overrides": [OV]}},
              "sources": [src(DISP, "def register_kernels(overrides: Mapping[str, Callable[..., Any]]) -> None:")]})
SCENARIOS += [
    {"id": "kernels-ops-r6-triton-override-launch", "name": "A registered override takes the expand kernel's launches; keyword launches are reordered; an unknown keyword fails",
     "flow": TKF, "fixtures": FX,
     "steps": [{"interface": "triton-kernel-dispatcher.launch", "caller": "gpu-worker", "as": "before", "input": {"name": KN, "kwargs": ["output_ptr"]}},
               {"flow": TKF, "as": "reg"},
               {"interface": "triton-kernel-dispatcher.launch", "caller": "gpu-worker", "as": "kw", "input": {"name": KN, "kwargs": ["output_ptr", "input_ptr", "MAX_NUM_TOKENS"]}},
               {"interface": "triton-kernel-dispatcher.launch", "caller": "gpu-worker", "as": "pos", "input": {"name": KN, "positional": True}},
               {"interface": "triton-kernel-dispatcher.launch", "caller": "gpu-worker", "as": "bad", "input": {"name": KN, "kwargs": ["output_ptr", "BLOCK"]}},
               {"flow": TKF, "as": "again"}],
     "expect": ["steps.before.result.value.runs == 'triton'",
                "steps.kw.result.value.runs == 'expand_kernel_xpu' && steps.kw.result.value.binding == 'reordered' && steps.pos.result.value.binding == 'positional'",
                "!steps.bad.result.ok && steps.bad.result.error.message == \"Override for 'expand_kernel_xpu' received unexpected launch arguments: ['BLOCK']\"",
                "steps.reg.result.value.overwritten == [] && steps.again.result.value.overwritten == ['" + KN + "']",
                "state['triton-kernel-dispatcher@rank0'].registry['vllm__v1__sample__rejection_sampler__expand_kernel'].impl == 'expand_kernel_xpu'"]},
    {"id": "kernels-ops-r6-triton-override-by-name", "name": "An override with the kernel's own parameter names is called by keyword; an unknown kernel name is a ValueError",
     "flow": TKF, "fixtures": FX,
     "steps": [{"flow": TKF, "as": "reg", "input": {"overrides": [dict(OV, impl="expand_same", impl_params=OV["kernel_params"])]}},
               {"interface": "triton-kernel-dispatcher.launch", "caller": "gpu-worker", "as": "kw", "input": {"name": KN, "kwargs": ["output_ptr", "BLOCK"]}},
               {"flow": TKF, "as": "missing", "input": {"overrides": [dict(OV, name="vllm.v1.sample.rejection_sampler.no_such_kernel", found=False)]}}],
     "expect": ["steps.kw.result.value.binding == 'keyword'",
                "!steps.missing.result.ok && steps.missing.result.error.code == 'value-error' && steps.missing.result.error.message == \"Kernel 'vllm.v1.sample.rejection_sampler.no_such_kernel' not found for override\"",
                "state['triton-kernel-dispatcher@rank0'].registry['vllm__v1__sample__rejection_sampler__expand_kernel'].forward_by_name"]},
]

# ====================================================================== AITER MoE: sorting dispatch policy and top-k softmax
CONFIGS.append(cfg("vllm-rocm-aiter-moe-dispatch-policy", "integer", 0, 0,
                   "VLLM_ROCM_AITER_MOE_DISPATCH_POLICY: the AITER fused-MoE sorting dispatch policy, read once by rocm_aiter_ops.get_moe_dispatch_policy (and by refresh_env_variables).",
                   [src(ENVS, "VLLM_ROCM_AITER_MOE_DISPATCH_POLICY: int = 0"), src(ENVS, '"VLLM_ROCM_AITER_MOE_DISPATCH_POLICY": lambda: int(', span=1)],
                   "VLLM_ROCM_AITER_MOE_DISPATCH_POLICY", env=True))
COMPONENT_PATCHES["aiter-ops"]["moe_dispatch_policy"] = None
iface("aiter-ops", "get-moe-dispatch-policy", kind="function", latency_ms=0,
      summary="rocm_aiter_ops.get_moe_dispatch_policy (@if_aiter_supported): None off supported ROCm, else the cached VLLM_ROCM_AITER_MOE_DISPATCH_POLICY that AiterExperts passes as moe_sorting_dispatch_policy.",
      sources=[src(AIT, "    def get_moe_dispatch_policy(cls) -> int:", span=7)],
      response={"type": "object", "properties": {"policy": {"type": ["integer", "null"]}, "cached": {"type": "boolean"}}},
      behavior=[
          {"call": "aiter-ops.is-aiter-found-and-supported", "input": {}, "as": "s", "title": "if_aiter_supported", "source": src(AIT, "        if is_aiter_found_and_supported():")},
          {"if": "!vars.s.value.supported", "then": [{"return": {"policy": None, "cached": False}}]},
          {"if": "state.moe_dispatch_policy != null", "title": "Read once per process", "source": src(AIT, "        if cls._MOE_DISPATCH_POLICY is None:"),
           "then": [{"return": {"policy": "= state.moe_dispatch_policy", "cached": True}}]},
          {"set": {"state.moe_dispatch_policy": "= config['vllm-rocm-aiter-moe-dispatch-policy']"}, "source": src(AIT, "            cls._MOE_DISPATCH_POLICY = envs.VLLM_ROCM_AITER_MOE_DISPATCH_POLICY", nth=1)},
          {"return": {"policy": "= state.moe_dispatch_policy", "cached": False}},
      ])
iface("aiter-ops", "topk-softmax", kind="function", latency_ms=0, request="KernelsOpsMoeShape",
      summary="rocm_aiter_ops.topk_softmax: torch.ops.vllm.rocm_aiter_topk_softmax writes topk_weights / topk_indices in place (aiter.topk_softmax, with optional fused shared experts).",
      sources=[src(AIT, "    def topk_softmax(", span=19)],
      response={"type": "object", "properties": {"op": {"type": "string"}}},
      behavior=[{"call": "aiter-ops.rocm-aiter-topk-softmax", "input": "= input", "title": "torch.ops.vllm.rocm_aiter_topk_softmax(...)", "source": src(AIT, "        torch.ops.vllm.rocm_aiter_topk_softmax(")},
                {"return": {"op": "vllm::rocm_aiter_topk_softmax"}}])
MI300 = {"aiter-ops": {"aiter_found": True, "gcn_arch": "gfx942"}}
SCENARIOS += [
    {"id": "kernels-ops-r6-aiter-moe-dispatch-policy", "name": "On an MI300X with AITER the MoE sorting dispatch policy is read once from the env; on CUDA it is None",
     "fixtures": FX, "config": {"vllm-target-device": "rocm", "vllm-rocm-aiter-moe-dispatch-policy": 1}, "state": MI300,
     "steps": [{"interface": "aiter-ops.get-moe-dispatch-policy", "caller": "gpu-worker", "as": "p"},
               {"interface": "aiter-ops.get-moe-dispatch-policy", "caller": "gpu-worker", "as": "p2"},
               {"interface": "aiter-ops.topk-softmax", "caller": "gpu-worker", "as": "tk", "input": {"num_tokens": 16, "num_experts": 8, "topk": 2, "k": 4096, "n": 14336, "dtype_bytes": 2}}],
     "expect": ["steps.p.result.value.policy == 1 && !steps.p.result.value.cached && steps.p2.result.value.cached",
                "steps.tk.result.ok && steps.tk.result.value.op == 'vllm::rocm_aiter_topk_softmax'", "state['aiter-ops@rank0'].moe_dispatch_policy == 1"]},
    {"id": "kernels-ops-r6-aiter-moe-dispatch-policy-cuda", "name": "Off ROCm the @if_aiter_supported gate returns None",
     "fixtures": FX, "steps": [{"interface": "aiter-ops.get-moe-dispatch-policy", "caller": "gpu-worker", "as": "p"}],
     "expect": ["steps.p.result.ok && steps.p.result.value.policy == null"]},
]

# ====================================================================== MoE all2all backend package probes
PROBES = {"deep_ep_v2": "def has_deep_ep_v2() -> bool:", "nixl_ep": "def has_nixl_ep() -> bool:", "mori": "def has_mori() -> bool:"}
hm = I["import-utils.has-module"]
hm["summary"] += " Also the MoE all2all backends' packages: nixl_ep, mori, and deep_ep v2 (ElasticBuffer); and the triton_kernels API generation."
hm["sources"] = hm["sources"] + [src(IU, PROBES["deep_ep_v2"], span=8), src(IU, PROBES["nixl_ep"], span=2), src(IU, PROBES["mori"], span=2)]
hm["request"]["properties"]["probe"]["enum"] = hm["request"]["properties"]["probe"]["enum"] + ["deep_ep_v2", "nixl_ep", "mori"]
hm["request"]["properties"]["deep_ep_v2_reason"] = {"type": ["string", "null"], "default": None,
                                                    "description": "deep_ep_v2_unavailable_reason(): null when deep_ep has ElasticBuffer and a new-enough NCCL"}
hm["behavior"] = [
    {"if": "input.probe == 'nixl_ep' || input.probe == 'mori'", "title": "has_nixl_ep / has_mori: _has_module(name)", "source": src(IU, 'return _has_module("nixl_ep")'),
     "then": [{"return": {"available": "= input.probe in input.installed"}}]},
    {"if": "input.probe == 'deep_ep_v2'", "title": "has_deep_ep_v2: deep_ep v2 API with no unavailability reason (the reason is logged when deep_ep itself is installed)",
     "source": src(IU, "    return reason is None", start=500),
     "then": [{"if": "has(input.deep_ep_v2_reason) && input.deep_ep_v2_reason != null && 'deep_ep' in input.installed",
               "source": src(IU, 'logger.info_once("deepep_v2 backend will not be available: %s", reason)'),
               "then": [{"set": {"ctx.log": "= 'deepep_v2 backend will not be available: ' + input.deep_ep_v2_reason"}}]},
              {"return": {"available": "= 'deep_ep' in input.installed && (!has(input.deep_ep_v2_reason) || input.deep_ep_v2_reason == null)"}}]},
] + hm["behavior"]
SCENARIOS += [
    {"id": "kernels-ops-r6-moe-backend-probes", "name": "MoE all2all backend probes: nixl_ep and mori by package; deep_ep v2 needs deep_ep without an unavailability reason",
     "fixtures": FX,
     "steps": [{"interface": "import-utils.has-module", "caller": "gpu-worker", "as": "nixl", "input": {"probe": "nixl_ep", "installed": ["nixl_ep"]}},
               {"interface": "import-utils.has-module", "caller": "gpu-worker", "as": "mori", "input": {"probe": "mori", "installed": []}},
               {"interface": "import-utils.has-module", "caller": "gpu-worker", "as": "v2", "input": {"probe": "deep_ep_v2", "installed": ["deep_ep"]}},
               {"interface": "import-utils.has-module", "caller": "gpu-worker", "as": "v2old", "input": {"probe": "deep_ep_v2", "installed": ["deep_ep"], "deep_ep_v2_reason": "NCCL too old"}}],
     "expect": ["steps.nixl.result.value.available && !steps.mori.result.value.available",
                "steps.v2.result.value.available && !steps.v2old.result.value.available"]},
]

# ====================================================================== compile caching: compiler choice and the adaptors' cache dirs
CONFIGS.append(cfg("vllm-use-standalone-compile", "boolean", True, True,
                   "VLLM_USE_STANDALONE_COMPILE: with the inductor backend, compile through torch._inductor.standalone_compile (InductorStandaloneAdaptor) when torch has it; else InductorAdaptor.",
                   [src(ENVS, "VLLM_USE_STANDALONE_COMPILE: bool = True"), src(ENVS, '"VLLM_USE_STANDALONE_COMPILE": lambda: (', span=2), src(BK, "if envs.VLLM_USE_STANDALONE_COMPILE and hasattr(")],
                   "VLLM_USE_STANDALONE_COMPILE", env=True))
COMPONENT_PATCHES["compiler-manager"] = {"compiler": "inductor_standalone"}
COMPONENT_PATCHES["inductor-standalone-adaptor"] = {"cache_dir": ""}
COMPONENTS.append(comp("inductor-adaptor", "InductorAdaptor", "module",
                       "The Inductor compiler for torch without standalone_compile (or VLLM_USE_STANDALONE_COMPILE=0): redirects Inductor's and Triton's caches under the vLLM cache dir.",
                       [src(CI, "class InductorAdaptor(CompilerInterface):")], parent="compilation",
                       state={"schema": {"type": "object", "properties": {"cache_dir": {"type": "string"}, "base_cache_dir": {"type": "string"},
                                                                          "env": {"type": "object", "description": "TORCHINDUCTOR_CACHE_DIR / TRITON_CACHE_DIR this process sets"},
                                                                          "last_triton_cache_dir": {"type": ["string", "null"]}}},
                              "initial": {"cache_dir": "", "base_cache_dir": "", "env": {}, "last_triton_cache_dir": None}}, capacity={"concurrency": 1}))
iface("compiler-manager", "make-compiler", kind="function", latency_ms=0,
      summary="make_compiler(compilation_config) in CompilerManager.__init__: inductor backend -> InductorStandaloneAdaptor when VLLM_USE_STANDALONE_COMPILE and torch has standalone_compile, else InductorAdaptor; eager -> EagerAdaptor.",
      sources=[src(BK, "def make_compiler(compilation_config: CompilationConfig) -> CompilerInterface:", span=25)],
      request={"type": "object", "properties": {"backend": {"type": "string", "default": "inductor", "enum": ["inductor", "eager"]},
                                                "torch_has_standalone_compile": {"type": "boolean", "default": True, "description": "hasattr(torch._inductor, 'standalone_compile') (torch 2.8+)"}}},
      response={"type": "object", "properties": {"compiler": {"type": "string"}}},
      errors=ERR("assertion-error"),
      behavior=[
          {"if": "(!has(input.backend) || input.backend == 'inductor') && config['vllm-use-standalone-compile'] && (!has(input.torch_has_standalone_compile) || input.torch_has_standalone_compile)",
           "title": "InductorStandaloneAdaptor(compile_cache_save_format)", "source": src(BK, "            return InductorStandaloneAdaptor("),
           "then": [{"set": {"state.compiler": "inductor_standalone"}}, {"return": {"compiler": "inductor_standalone"}}]},
          {"if": "!has(input.backend) || input.backend == 'inductor'", "title": "InductorAdaptor", "source": src(BK, "            return InductorAdaptor()"),
           "then": [{"set": {"state.compiler": "inductor"}}, {"return": {"compiler": "inductor"}}]},
          {"set": {"state.compiler": "eager"}, "title": "EagerAdaptor", "source": src(BK, "        return EagerAdaptor()")},
          {"return": {"compiler": "eager"}},
      ])
iface("inductor-standalone-adaptor", "initialize-cache", kind="function", latency_ms=0,
      summary="InductorStandaloneAdaptor.initialize_cache: remember the cache dir; artifacts are saved under it by compile().",
      sources=[src(CI, "    def initialize_cache(", nth=2, span=3)],
      request={"type": "object", "properties": {"cache_dir": {"type": "string"}, "disable_cache": {"type": "boolean", "default": False}, "prefix": {"type": "string", "default": ""}}},
      behavior=[{"set": {"state.cache_dir": "= input.cache_dir"}, "title": "self.cache_dir = cache_dir", "source": src(CI, "        self.cache_dir = cache_dir", nth=1)},
                {"return": {"cache_dir": "= state.cache_dir"}}])
iface("inductor-adaptor", "initialize-cache", kind="function", latency_ms=0,
      summary="InductorAdaptor.initialize_cache: base dir = cache_dir minus the prefix; unless the cache is disabled, point TORCHINDUCTOR_CACHE_DIR at <base>/inductor_cache and TRITON_CACHE_DIR at <base>/triton_cache, keeping a caller's own TRITON_CACHE_DIR.",
      sources=[src(CI, "    def initialize_cache(", nth=3, span=22)],
      request={"type": "object", "properties": {"cache_dir": {"type": "string", "examples": ["~/.cache/vllm/torch_compile_cache/h/rank_0_0/backbone"]},
                                                "disable_cache": {"type": "boolean", "default": False}, "prefix": {"type": "string", "default": "backbone"},
                                                "triton_cache_dir_env": {"type": ["string", "null"], "default": None, "description": "TRITON_CACHE_DIR in the environment before the call"}}},
      response={"type": "object", "properties": {"inductor_cache": {"type": ["string", "null"]}, "triton_cache": {"type": ["string", "null"]}}},
      behavior=[
          {"set": {"vars.p": "= has(input.prefix) ? input.prefix : ''"}},
          {"set": {"state.cache_dir": "= input.cache_dir",
                   "state.base_cache_dir": "= vars.p != '' && input.cache_dir.endsWith(vars.p) ? input.cache_dir.substring(0, size(input.cache_dir) - size(vars.p)) : input.cache_dir"},
           "title": "base_cache_dir = cache_dir[:-len(prefix)]: all prefixes of one model share Inductor and Triton caches", "source": src(CI, "self.base_cache_dir = cache_dir[: -len(prefix)] if prefix else cache_dir")},
          {"if": "has(input.disable_cache) && input.disable_cache", "title": "Cache disabled: leave Inductor's and Triton's dirs alone", "source": src(CI, "        if disable_cache:", start=455),
           "then": [{"return": {"inductor_cache": None, "triton_cache": None}}]},
          {"set": {"state.env.TORCHINDUCTOR_CACHE_DIR": "= state.base_cache_dir + 'inductor_cache'"}, "source": src(CI, 'os.environ["TORCHINDUCTOR_CACHE_DIR"] = inductor_cache', start=455)},
          {"set": {"vars.t": "= has(input.triton_cache_dir_env) ? input.triton_cache_dir_env : null"}},
          {"if": "vars.t == null || vars.t == state.last_triton_cache_dir", "title": "No caller-set TRITON_CACHE_DIR (or one an earlier adaptor set): model-local triton_cache",
           "source": src(CI, "if triton_cache is None or triton_cache == _last_inductor_triton_cache_dir:"),
           "then": [{"set": {"vars.t": "= state.base_cache_dir + 'triton_cache'"}}, {"set": {"state.last_triton_cache_dir": "= vars.t"}}]},
          {"set": {"state.env.TRITON_CACHE_DIR": "= vars.t"}, "source": src(CI, 'os.environ["TRITON_CACHE_DIR"] = triton_cache')},
          {"return": {"inductor_cache": "= state.env.TORCHINDUCTOR_CACHE_DIR", "triton_cache": "= vars.t"}},
      ])
# CompilerManager.initialize_cache ends by initializing the compiler's own cache (backends.py:214-216)
cmi = I["compiler-manager.initialize-cache"]
cmi["request"]["properties"]["prefix"] = {"type": "string", "default": "backbone"}
cmi["behavior"] = cmi["behavior"] + [
    {"title": "self.compiler.initialize_cache(cache_dir, disable_cache, prefix)", "source": src(BK, "        self.compiler.initialize_cache("),
     "call": "= state.compiler == 'inductor' ? 'inductor-adaptor.initialize-cache' : 'inductor-standalone-adaptor.initialize-cache'",
     "targets": ["inductor-adaptor.initialize-cache", "inductor-standalone-adaptor.initialize-cache"],
     "input": {"cache_dir": "= input.cache_dir", "disable_cache": "= input.disable_cache", "prefix": "= has(input.prefix) ? input.prefix : 'backbone'"}}]
CD = "~/.cache/vllm/torch_compile_cache/h1/rank_0_0/backbone"
SCENARIOS += [
    {"id": "kernels-ops-r6-compiler-choice-and-cache-dirs", "name": "make_compiler picks the standalone adaptor by default; with VLLM_USE_STANDALONE_COMPILE=0 InductorAdaptor moves Inductor and Triton caches under the model's dir",
     "fixtures": FX, "config": {"vllm-use-standalone-compile": False},
     "steps": [{"interface": "compiler-manager.make-compiler", "caller": "gpu-worker", "as": "mk"},
               {"interface": "compiler-manager.initialize-cache", "caller": "gpu-worker", "as": "init", "input": {"cache_dir": CD, "disable_cache": False, "prefix": "backbone"}},
               {"interface": "inductor-adaptor.initialize-cache", "caller": "gpu-worker", "as": "eagle",
                "input": {"cache_dir": "~/.cache/vllm/torch_compile_cache/h1/rank_0_0/eagle_head", "prefix": "eagle_head", "triton_cache_dir_env": "~/.cache/vllm/torch_compile_cache/h1/rank_0_0/triton_cache"}},
               {"interface": "inductor-adaptor.initialize-cache", "caller": "gpu-worker", "as": "user", "input": {"cache_dir": CD, "prefix": "backbone", "triton_cache_dir_env": "/scratch/triton"}}],
     "expect": ["steps.mk.result.value.compiler == 'inductor'",
                "state['inductor-adaptor@rank0'].base_cache_dir == '~/.cache/vllm/torch_compile_cache/h1/rank_0_0/'",
                "steps.eagle.result.value.triton_cache == '~/.cache/vllm/torch_compile_cache/h1/rank_0_0/triton_cache'",
                "steps.user.result.value.triton_cache == '/scratch/triton' && state['inductor-adaptor@rank0'].env.TORCHINDUCTOR_CACHE_DIR == '~/.cache/vllm/torch_compile_cache/h1/rank_0_0/inductor_cache'"]},
    {"id": "kernels-ops-r6-compiler-choice-default", "name": "Deployed: InductorStandaloneAdaptor; the eager backend uses EagerAdaptor; a disabled cache leaves Inductor's dirs alone",
     "fixtures": FX,
     "steps": [{"interface": "compiler-manager.make-compiler", "caller": "gpu-worker", "as": "eager", "input": {"backend": "eager"}},
               {"interface": "compiler-manager.make-compiler", "caller": "gpu-worker", "as": "old", "input": {"torch_has_standalone_compile": False}},
               {"interface": "compiler-manager.make-compiler", "caller": "gpu-worker", "as": "mk"},
               {"interface": "compiler-manager.initialize-cache", "caller": "gpu-worker", "as": "init", "input": {"cache_dir": CD, "disable_cache": False}},
               {"interface": "inductor-adaptor.initialize-cache", "caller": "gpu-worker", "as": "off", "input": {"cache_dir": CD, "disable_cache": True}}],
     "expect": ["steps.eager.result.value.compiler == 'eager' && steps.old.result.value.compiler == 'inductor' && steps.mk.result.value.compiler == 'inductor_standalone'",
                "state['inductor-standalone-adaptor@rank0'].cache_dir == '" + CD + "'",
                "steps.off.result.value.inductor_cache == null && size(state['inductor-adaptor@rank0'].env) == 0"]},
]

# deep-gemm-utils now holds the scale-format cache: one thread per GPU worker calls it
COMPONENT_CAPACITY = ["deep-gemm-utils"]

"""Fix round 5 (precision): the round-4 blind findings, the error-path sweep, and the kernels the
MoE and FP8 worlds drive (routing, expert alignment, FP8 quant and scaled GEMM with their
capability checks).

Overrides entries of hand2.I / hand2.OP_BEHAVIORS and exports CONFIGS and SCENARIOS for build.py."""
from common import findline, src
from hand import cfg, AQF, CP, RQF
from hand2 import I, OP_BEHAVIORS, iface  # noqa: F401
from hand3 import COMPONENT_PATCHES

ERR = lambda *codes: [{"code": c, "status": 0, "retryable": False} for c in codes]
SMM = "csrc/quantization/w8a8/cutlass/scaled_mm_entry.cu"
SMH = "csrc/quantization/w8a8/cutlass/c3x/scaled_mm_helper.hpp"
C2X = "csrc/quantization/w8a8/cutlass/scaled_mm_c2x.cu"
TKS = "csrc/moe/topk_softmax_kernels.cu"
MAS = "csrc/moe/moe_align_sum_kernels.cu"
ACTQ = "csrc/quantization/activation_kernels.cu"
FP8C = "csrc/quantization/w8a8/fp8/common.cu"
TU_H = "csrc/torch_utils.h"
CMN = "csrc/cutlass_extensions/common.hpp"
CUDA_PLAT = "vllm/platforms/cuda.py"


def chk(cond):
    """STD_TORCH_CHECK(cond) with no message: torch's default text (torch/headeronly/util/Exception.h)."""
    return f"Expected {cond} to be true, but got false."


# The device the _C ops run on, as cudaDeviceGetAttribute reports it (the fixtures' H100: 9.0).
COMPONENT_PATCHES["torch-bindings"] = {"device_capability": {"major": 9, "minor": 0}}

CONFIGS = [
    cfg("vllm-cuda-version", "integer", 13000, 13000,
        "CUDA_VERSION the _C extension was compiled with (the release wheels and the Docker image build with CUDA 13.0.x); "
        "the CUTLASS capability queries compare against it.",
        ["docker/Dockerfile:25", src(SMM, "#if defined CUDA_VERSION", nth=1)], "CUDA_VERSION"),
]
SCENARIOS = []

# ====================================================================== fusion passes (oracle3 fix request 1)
# Pattern names used by the model's graph_patterns: "<producer>+<quant>".
ACT_STATIC = {"silu_and_mul+static_fp8_quant": "_C::silu_and_mul_quant"}
ACT_NVFP4 = {"silu_and_mul+nvfp4_quant": "_C::silu_and_mul_nvfp4_quant"}
ACT_BLOCK = {p: "_C::silu_and_mul_per_block_quant" for p in
             ["silu_and_mul+per_block_fp8_quant", "silu_and_mul+group128_fp8_quant", "silu_and_mul+group64_fp8_quant"]}


def cel_map(d):
    return "{" + ", ".join(f"'{k}': '{v}'" for k, v in d.items()) + "}"


def apply_patterns(reg_expr):
    return [
        {"set": {"vars.matched": "= input.graph_patterns.filter(p, p in " + reg_expr + ")"}},
        {"set": {"vars.fused": "= vars.matched.map(p, " + reg_expr + "[p])"}},
        {"if": "size(vars.fused) > 0", "then": [{"set": {"ctx.fused": "= (has(ctx.fused) ? ctx.fused : []) + vars.fused"}}]},
    ]


I["activation-quant-fusion-pass.call"].update(
    summary="ActivationQuantFusionPass: silu_and_mul + static FP8 quant always; on CUDA also + NVFP4 quant (when _C.silu_and_mul_nvfp4_quant exists) "
            "and + per-group FP8 quant (group 128 and 64, 16 layout variants) into _C::silu_and_mul_per_block_quant; replaced counts the matches.",
    sources=[src(AQF, "class ActivationQuantFusionPass", span=37), src(AQF, "FUSED_OPS: dict[QuantKey, OpOverload] = {", span=13)],
    request={"type": "object", "properties": {"graph_patterns": {"type": "array", "items": {"type": "string"}}}},
    response={"type": "object", "properties": {"replaced": {"type": "integer"}, "patterns_registered": {"type": "integer"}, "fused_ops": {"type": "array", "items": {"type": "string"}}}},
    behavior=[
        {"set": {"vars.cuda": "= config['vllm-target-device'] == 'cuda'"}, "title": "current_platform.is_cuda()", "source": src(AQF, "if current_platform.is_cuda():", nth=1)},
        {"title": "register(SiluMulFp8StaticQuantPattern()) always", "source": src(AQF, "self.register(SiluMulFp8StaticQuantPattern())"),
         "set": {"vars.reg": "= " + cel_map(ACT_STATIC)}},
        {"if": "vars.cuda", "title": "CUDA: silu_and_mul_nvfp4_quant is built (non-ROCm _C), so SiluMulNvfp4QuantPattern registers; "
                                    "then SiluMulBlockQuantPattern for kFp8Dynamic128Sym/64Sym x transposed x e8m0 x TMA-aligned",
         "source": src(AQF, "silu_and_mul_nvfp4_quant_supported = current_platform.is_cuda() and hasattr("),
         "then": [{"set": {"vars.reg": "= " + cel_map({**ACT_STATIC, **ACT_NVFP4, **ACT_BLOCK})},
                   "source": src(AQF, "SiluMulBlockQuantPattern(", nth=2), "title": "the 16 block-quant patterns all replace with silu_and_mul_per_block_quant"}]},
    ] + apply_patterns("vars.reg") + [
        {"return": {"replaced": "= size(vars.matched)", "patterns_registered": "= vars.cuda ? 18 : 1", "fused_ops": "= vars.fused"},
         "title": "self.matched_count = self.pm_pass.apply(graph)", "source": src("vllm/compilation/passes/vllm_inductor_pass.py", "self.matched_count = self.pm_pass.apply(graph)")},
    ])

RMS_BASE = {"rms_norm+static_fp8_quant": "_C::rms_norm_static_fp8_quant",
            "fused_add_rms_norm+static_fp8_quant": "_C::fused_add_rms_norm_static_fp8_quant",
            "rms_norm+dynamic_per_token_fp8_quant": "_C::rms_norm_dynamic_per_token_quant",
            "fused_add_rms_norm+dynamic_per_token_fp8_quant": "_C::rms_norm_dynamic_per_token_quant"}
RMS_BLOCK = {p: "_C::rms_norm_per_block_quant" for p in
             ["rms_norm+per_block_fp8_quant", "fused_add_rms_norm+per_block_fp8_quant",
              "rms_norm+group128_fp8_quant", "fused_add_rms_norm+group128_fp8_quant",
              "rms_norm+group64_fp8_quant", "fused_add_rms_norm+group64_fp8_quant"]}
RMS_NVFP4 = {"fused_add_rms_norm+nvfp4_quant": "vllm::flashinfer_fused_add_rms_norm_nvfp4_quant"}
I["rms-norm-quant-fusion-pass.call"].update(
    summary="RMSNormQuantFusionPass: for epsilon 1e-5 and 1e-6, (fused_add_)rms_norm + static FP8 and + dynamic per-token FP8 quant; "
            "+ per-group FP8 quant (group 128/64) when _C.rms_norm_per_block_quant exists (CUDA and ROCm builds); "
            "fused_add + NVFP4 via FlashInfer's add_rmsnorm_fp4quant on CUDA with SM100+.",
    sources=[src(RQF, "class RMSNormQuantFusionPass", span=66), src(RQF, "FUSED_OPS: dict[FusedRMSQuantKey, OpOverload] = {", span=20),
             src(RQF, "_FLASHINFER_NVFP4_RMS_QUANT_OP: OpOverload | None = None", span=21)],
    request={"type": "object", "properties": {
        "graph_patterns": {"type": "array", "items": {"type": "string"}},
        "flashinfer_add_rmsnorm_fp4quant": {"type": "boolean", "default": True,
                                            "description": "flashinfer is installed and exports add_rmsnorm_fp4quant (torch has float4_e2m1fn_x2)"}}},
    response={"type": "object", "properties": {"replaced": {"type": "integer"}, "patterns_registered": {"type": "integer"}, "fused_ops": {"type": "array", "items": {"type": "string"}}}},
    behavior=[
        {"set": {"vars.dev": "= config['vllm-target-device']"}},
        {"set": {"vars.block": "= vars.dev == 'cuda' || vars.dev == 'rocm'"},
         "title": "hasattr(torch.ops._C, 'rms_norm_per_block_quant'): defined in csrc/torch_bindings.cpp outside the CUDA-only block",
         "source": src(RQF, 'if hasattr(torch.ops._C, "rms_norm_per_block_quant"):')},
        {"set": {"vars.nvfp4": False}},
        {"if": "vars.dev == 'cuda' && (!has(input.flashinfer_add_rmsnorm_fp4quant) || input.flashinfer_add_rmsnorm_fp4quant)",
         "title": "CUDA with FlashInfer's add_rmsnorm_fp4quant: the NVFP4 patterns need has_device_capability(100)",
         "source": src(RQF, "current_platform.has_device_capability(100)"),
         "then": [{"call": "cuda-platform.get-device-capability", "input": {}, "as": "dc"},
                  {"set": {"vars.nvfp4": "= vars.dc.value != null && vars.dc.value.as_int >= 100"}}]},
        {"set": {"vars.reg": "= vars.block ? (vars.nvfp4 ? " + cel_map({**RMS_BASE, **RMS_BLOCK, **RMS_NVFP4}) + " : " + cel_map({**RMS_BASE, **RMS_BLOCK}) + ") : " + cel_map(RMS_BASE)},
         "title": "Fused-add patterns first, then plain; static, dynamic per-token, then the group patterns", "source": src(RQF, "# Fuse fused_add_rms_norm + static fp8 quant")},
    ] + apply_patterns("vars.reg") + [
        {"return": {"replaced": "= size(vars.matched)", "patterns_registered": "= 2 * (4 + (vars.block ? 16 : 0) + (vars.nvfp4 ? 2 : 0))", "fused_ops": "= vars.fused"},
         "title": "self.matched_count = self.patterns.apply(graph)", "source": src(RQF, "self.matched_count = self.patterns.apply(graph)")},
    ])

PGF = "kernels-ops-post-grad-pass-manager"
SCENARIOS += [
    {"id": "kernels-ops-act-quant-fusion-patterns-cuda", "name": "fuse_act_quant on CUDA: static FP8, NVFP4 and per-group FP8 activation quant all fuse; replaced counts the matches",
     "description": "oracle3 kernels-ops fix request 1 (test_silu_mul_quant_fusion.py::test_fusion_silu_and_mul_quant): ActivationQuantFusionPass registers the NVFP4 "
                    "and block-quant patterns on CUDA (act_quant_fusion.py:36-44, 285-307).",
     "fixtures": ["tp1-llama-8b"], "config": {"fuse-act-quant": True},
     "steps": [{"interface": "activation-quant-fusion-pass.call", "caller": "gpu-worker", "as": "all",
                "input": {"graph_patterns": ["silu_and_mul+static_fp8_quant", "silu_and_mul+nvfp4_quant", "silu_and_mul+group64_fp8_quant", "gelu_and_mul+static_fp8_quant"]}}],
     "expect": ["steps.all.result.ok && steps.all.result.value.replaced == 3 && steps.all.result.value.patterns_registered == 18",
                "steps.all.result.value.fused_ops == ['_C::silu_and_mul_quant', '_C::silu_and_mul_nvfp4_quant', '_C::silu_and_mul_per_block_quant']"]},
    {"id": "kernels-ops-act-quant-fusion-patterns-rocm", "name": "fuse_act_quant on ROCm: only the static FP8 pattern is registered, so block and NVFP4 quant stay unfused",
     "fixtures": ["tp1-llama-8b"], "config": {"vllm-target-device": "rocm"},
     "steps": [{"interface": "activation-quant-fusion-pass.call", "caller": "gpu-worker", "as": "r",
                "input": {"graph_patterns": ["silu_and_mul+per_block_fp8_quant", "silu_and_mul+nvfp4_quant"]}}],
     "expect": ["steps.r.result.ok && steps.r.result.value.replaced == 0 && steps.r.result.value.patterns_registered == 1 && steps.r.result.value.fused_ops == []"]},
    {"id": "kernels-ops-rms-quant-fusion-patterns", "name": "fuse_norm_quant: dynamic per-token and per-group FP8 fuse on H100; NVFP4 add+norm needs SM100",
     "description": "RMSNormQuantFusionPass (rms_quant_fusion.py:772-838): per-token and group patterns register on CUDA; the FlashInfer NVFP4 pattern only with has_device_capability(100).",
     "fixtures": ["full-tp1-llama-8b"], "config": {"fuse-norm-quant": True},
     "steps": [{"interface": "rms-norm-quant-fusion-pass.call", "caller": "gpu-worker", "as": "h100",
                "input": {"graph_patterns": ["fused_add_rms_norm+dynamic_per_token_fp8_quant", "rms_norm+group128_fp8_quant", "fused_add_rms_norm+nvfp4_quant"]}},
],
     "expect": ["steps.h100.result.ok && steps.h100.result.value.replaced == 2 && steps.h100.result.value.patterns_registered == 40",
                "steps.h100.result.value.fused_ops == ['_C::rms_norm_dynamic_per_token_quant', '_C::rms_norm_per_block_quant']"]},
    {"id": "kernels-ops-rms-quant-fusion-nvfp4-sm100", "name": "fuse_norm_quant on a B200 with FlashInfer: fused_add_rms_norm + NVFP4 quant fuses into FlashInfer's add_rmsnorm_fp4quant",
     "fixtures": ["full-tp1-llama-8b"], "config": {"fuse-norm-quant": True}, "state": {"cuda-platform": {"device_capability": {"major": 10, "minor": 0}}},
     "steps": [{"interface": "rms-norm-quant-fusion-pass.call", "caller": "gpu-worker", "as": "b200", "input": {"graph_patterns": ["fused_add_rms_norm+nvfp4_quant"]}},
               {"interface": "rms-norm-quant-fusion-pass.call", "caller": "gpu-worker", "as": "nofi", "input": {"graph_patterns": ["fused_add_rms_norm+nvfp4_quant"], "flashinfer_add_rmsnorm_fp4quant": False}}],
     "expect": ["steps.b200.result.ok && steps.b200.result.value.fused_ops == ['vllm::flashinfer_fused_add_rms_norm_nvfp4_quant'] && steps.b200.result.value.patterns_registered == 44",
                "steps.nofi.result.value.replaced == 0 && steps.nofi.result.value.patterns_registered == 40"]},
    {"id": "kernels-ops-post-grad-pass-manager-fp8-block-model", "name": "A block-FP8 graph with fuse_norm_quant and fuse_act_quant on: both group-quant fusions land, in pass order",
     "flow": PGF, "fixtures": ["tp1-llama-8b"], "config": {"fuse-norm-quant": True, "fuse-act-quant": True},
     "input": {"graph_patterns": ["rms_norm+group128_fp8_quant", "silu_and_mul+group128_fp8_quant"]},
     "expect": ["result.ok && ctx.fused == ['_C::rms_norm_per_block_quant', '_C::silu_and_mul_per_block_quant']"]},
]

# ====================================================================== CUTLASS scaled GEMM: capability queries and host dispatch
CAPQ = {"type": "object", "required": ["cuda_device_capability"], "properties": {
    "cuda_device_capability": {"type": "integer", "examples": [90], "description": "major * 10 + minor (current_platform.get_device_capability().to_int())"}}}
for op, needle, expr, title in [
    ("cutlass-scaled-mm-supports-fp8", "bool cutlass_scaled_mm_supports_fp8(int64_t cuda_device_capability) {",
     "input.cuda_device_capability >= 90 ? config['vllm-cuda-version'] >= 12000 : (input.cuda_device_capability >= 89 ? config['vllm-cuda-version'] >= 12040 : false)",
     "SM90+: CUDA >= 12.0; SM89: CUDA >= 12.4; older: False"),
    ("cutlass-scaled-mm-supports-block-fp8", "bool cutlass_scaled_mm_supports_block_fp8(int64_t cuda_device_capability) {",
     "input.cuda_device_capability >= 100 ? config['vllm-cuda-version'] >= 12080 : (input.cuda_device_capability >= 90 ? config['vllm-cuda-version'] >= 12000 : false)",
     "SM100+: CUDA >= 12.8; SM90: CUDA >= 12.0; older: False"),
    ("cutlass-group-gemm-supported", "bool cutlass_group_gemm_supported(int64_t cuda_device_capability) {",
     "(input.cuda_device_capability >= 100 && input.cuda_device_capability < 120) ? config['vllm-cuda-version'] >= 12080 : "
     "((input.cuda_device_capability >= 90 && input.cuda_device_capability < 100) ? config['vllm-cuda-version'] >= 12030 : false)",
     "Grouped FP8 (MoE) GEMM: SM100-119 with CUDA >= 12.8, SM90-99 with CUDA >= 12.3; SM120 and older: False"),
]:
    OP_BEHAVIORS[f"torch-bindings.{op}"] = {
        "request": CAPQ, "response": {"type": "object", "properties": {"supported": {"type": "boolean"}}},
        "behavior": [{"return": {"supported": "= " + expr}, "title": title, "source": src(SMM, needle, span=14)}]}
    wrapper = op.replace("cutlass-", "", 0)
    I[f"custom-ops.{op}"] = {"component": "custom-ops", "name": op, "kind": "function", "latency_ms": 0,
                             "summary": f"{op.replace('-', '_')}(cuda_device_capability) -> torch.ops._C.{op.replace('-', '_')}",
                             "sources": [], "request": CAPQ, "response": {"type": "object", "properties": {"supported": {"type": "boolean"}}},
                             "behavior": [{"call": f"torch-bindings.{op}", "input": {"cuda_device_capability": "= input.cuda_device_capability"}, "as": "r",
                                           "title": f"torch.ops._C.{op.replace('-', '_')}", "source": src(CP, f"torch.ops._C.{op.replace('-', '_')}(cuda_device_capability)")},
                                          {"return": {"supported": "= vars.r.value.supported"}}]}

MM_REQ = {"type": "object", "properties": {
    "m": {"type": "integer", "examples": [16]}, "n": {"type": "integer", "examples": [4096]}, "k": {"type": "integer", "examples": [4096]},
    "dtype_bytes": {"type": "integer", "examples": [1], "description": "A/B element size: 1 for FP8 or INT8"},
    "a_dtype": {"type": ["string", "null"], "default": None, "examples": ["float8_e4m3fn", "int8"], "description": "null: float8_e4m3fn for 1-byte elements, bfloat16 for 2"},
    "out_dtype": {"type": "string", "default": "bfloat16", "examples": ["bfloat16", "float16"]},
    "scales": {"type": "string", "enum": ["per_tensor", "per_token_channel", "blockwise"], "default": "per_tensor",
               "description": "per_tensor / per_token_channel: a_scales numel 1 or M and b_scales numel 1 or N; blockwise: [M, K/128] and [K/128, N/128]"},
    "a_scale_cols": {"type": ["integer", "null"], "default": None, "description": "blockwise a_scales.size(1); null: ceil(K/128)"},
    "has_bias": {"type": "boolean", "default": False},
    "b_column_major": {"type": "boolean", "default": True, "description": "b.stride(0) == 1 (the weight is stored transposed)"},
    "ndim": {"type": "integer", "default": 2}}}
MMD = "= has(input.%s) ? input.%s : %s"
OP_BEHAVIORS["torch-bindings.cutlass-scaled-mm"] = {
    "request": MM_REQ,
    "response": {"type": "object", "properties": {"kernel": {"type": "string"}, "version_num": {"type": "integer"}}},
    "errors": ERR("runtime-error"),
    "behavior": [
        {"set": {"vars.ndim": MMD % ("ndim", "ndim", "2"), "vars.colmaj": MMD % ("b_column_major", "b_column_major", "true"),
                 "vars.a_dtype": "= has(input.a_dtype) && input.a_dtype != null ? input.a_dtype : (input.dtype_bytes == 1 ? 'float8_e4m3fn' : (input.dtype_bytes == 2 ? 'bfloat16' : 'float32'))",
                 "vars.scales": MMD % ("scales", "scales", "'per_tensor'"), "vars.bias": MMD % ("has_bias", "has_bias", "false")}},
        {"if": "vars.ndim != 2", "title": "Conformality: a, b and c are 2-D", "source": src(SMM, "STD_TORCH_CHECK(a.dim() == 2 && b.dim() == 2 && c.dim() == 2);"),
         "then": [{"fail": {"code": "runtime-error", "message": chk("a.dim() == 2 && b.dim() == 2 && c.dim() == 2")}}]},
        {"if": "!vars.colmaj", "title": "b must be column-major", "source": src(SMM, "STD_TORCH_CHECK(b.stride(0) == 1);                      // Column-major"),
         "then": [{"fail": {"code": "runtime-error", "message": chk("b.stride(0) == 1")}}]},
        {"if": "input.n % 16 != 0 || input.k % 16 != 0", "title": "16-byte alignment: c.stride(0) = N and b.stride(1) = K", "source": src(SMM, "STD_TORCH_CHECK(c.stride(0) % 16 == 0 &&"),
         "then": [{"fail": {"code": "runtime-error", "message": chk("c.stride(0) % 16 == 0 && b.stride(1) % 16 == 0")}}]},
        {"title": "get_sm_version_num(): cudaDeviceGetAttribute major * 10 + minor of device 0 (the CUDA runtime, not NVML)",
         "source": src(CMN, "int32_t version_num = major_capability * 10 + minor_capability;"),
         "set": {"vars.v": "= state.device_capability.major * 10 + state.device_capability.minor"}},
        {"if": "vars.v < 75", "title": "No compiled kernel for this capability", "source": src(SMM, '"No compiled cutlass_scaled_mm for a compute capability less than "'),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'NotImplementedError: No compiled cutlass_scaled_mm for a compute capability less than CUDA device capability: ' + string(vars.v)",
                            }, "title": "STD_TORCH_CHECK_NOT_IMPLEMENTED is STD_TORCH_CHECK with a 'NotImplementedError: ' prefix (a RuntimeError in Python)",
                   "source": src(TU_H, '  STD_TORCH_CHECK(cond, "NotImplementedError: ", __VA_ARGS__)')}]},
        {"set": {"vars.arch": "= vars.v >= 120 ? 'sm120' : (vars.v >= 100 ? 'sm100' : (vars.v >= 90 ? 'sm90' : (vars.v == 89 ? 'sm89' : (vars.v >= 80 ? 'sm80' : 'sm75'))))"},
         "title": "SM120+, SM100-119, SM90-99 (CUTLASS 3.x), SM89, SM80+, SM75+ (CUTLASS 2.x)", "source": src(SMM, "if (version_num >= 120) {")},
        {"if": "vars.arch == 'sm75' || vars.arch == 'sm80'", "title": "Turing / Ampere kernels are INT8 only", "source": src(C2X, "STD_TORCH_CHECK(a.scalar_type() == torch::headeronly::ScalarType::Char);"),
         "then": [{"if": "vars.a_dtype != 'int8'", "then": [{"fail": {"code": "runtime-error", "message": chk("a.scalar_type() == torch::headeronly::ScalarType::Char")}}]},
                  {"return": {"kernel": "= 'cutlass_scaled_mm_' + vars.arch + '_int8'", "version_num": "= vars.v"}}]},
        {"if": "vars.arch == 'sm89'", "title": "Ada: INT8 or FP8 e4m3", "source": src(C2X, "if (a.scalar_type() == torch::headeronly::ScalarType::Char) {", nth=1),
         "then": [{"if": "vars.a_dtype != 'int8' && vars.a_dtype != 'float8_e4m3fn'",
                   "then": [{"fail": {"code": "runtime-error", "message": chk("a.scalar_type() == torch::headeronly::ScalarType::Float8_e4m3fn")}}]},
                  {"return": {"kernel": "= vars.a_dtype == 'int8' ? 'cutlass_scaled_mm_sm89_int8' : 'cutlass_scaled_mm_sm89_fp8'", "version_num": "= vars.v"}}]},
        {"if": "vars.scales == 'blockwise'", "title": "Blockwise scales: a [M, K/128], b [K/128, N/128], no bias", "source": src(SMH, '"a_scale_group_shape must be [1, 128]."'),
         "then": [{"if": "has(input.a_scale_cols) && input.a_scale_cols != null && input.a_scale_cols != (input.k + 127) / 128",
                   "then": [{"fail": {"code": "runtime-error", "message": "a_scale_group_shape must be [1, 128]."}}]},
                  {"if": "vars.bias", "source": src(SMH, 'STD_TORCH_CHECK(!bias, "Bias not yet supported blockwise scaled_mm");'),
                   "then": [{"fail": {"code": "runtime-error", "message": "Bias not yet supported blockwise scaled_mm"}}]},
                  {"return": {"kernel": "= 'cutlass_scaled_mm_blockwise_' + vars.arch + '_fp8'", "version_num": "= vars.v"}}]},
        {"if": "vars.a_dtype == 'float8_e4m3fn'", "title": "Per-tensor / per-token / per-channel scales: FP8 e4m3", "source": src(SMH, "fp8_func(c, a, b, a_scales, b_scales, bias);"),
         "then": [{"return": {"kernel": "= 'cutlass_scaled_mm_' + vars.arch + '_fp8'", "version_num": "= vars.v"}}]},
        {"if": "vars.a_dtype != 'int8'", "title": "Otherwise INT8", "source": src(SMH, "STD_TORCH_CHECK(a.scalar_type() == torch::headeronly::ScalarType::Char);"),
         "then": [{"fail": {"code": "runtime-error", "message": chk("a.scalar_type() == torch::headeronly::ScalarType::Char")}}]},
        {"if": "vars.arch != 'sm90'", "title": "SM100 and SM120 pass no INT8 kernel", "source": src(SMH, '"Int8 not supported on SM", version_num,'),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'Int8 not supported on SM' + string(vars.v) + '. Use FP8 quantization instead, or run on older arch (SM < 100).'"}}]},
        {"return": {"kernel": "cutlass_scaled_mm_sm90_int8", "version_num": "= vars.v"}},
    ]}

SMM_START = findline(CP, "def cutlass_scaled_mm(")
I["custom-ops.cutlass-scaled-mm"] = {
    "component": "custom-ops", "name": "cutlass-scaled-mm", "kind": "function", "latency_ms": 0,
    "summary": "cutlass_scaled_mm: CUTLASS scaled GEMM when B's dims are multiples of 16 on CUDA, Triton scaled_mm otherwise (ROCm always).",
    "sources": [src(CP, "def cutlass_scaled_mm(", span=47)],
    "request": {"type": "object", "properties": {**MM_REQ["properties"], "bias_numel": {"type": ["integer", "null"], "default": None, "description": "null: N"},
                                                 "bias_dtype": {"type": ["string", "null"], "default": None, "description": "null: out_dtype"}}},
    "response": {"type": "object", "properties": {"backend": {"type": "string"}, "kernel": {"type": "string"}}},
    "errors": ERR("assertion-error", "runtime-error"),
    "behavior": [
        {"set": {"vars.out": MMD % ("out_dtype", "out_dtype", "'bfloat16'"), "vars.bias": MMD % ("has_bias", "has_bias", "false")}},
        {"if": "!(vars.out in ['bfloat16', 'float16'])", "title": "Output dtype must be bf16 or fp16 (a bare assert: empty message)",
         "source": src(CP, "assert out_dtype is torch.bfloat16 or out_dtype is torch.float16", start=SMM_START),
         "then": [{"fail": {"code": "assertion-error", "message": ""}}]},
        {"if": "vars.bias && ((has(input.bias_numel) && input.bias_numel != null && input.bias_numel != input.n) || (has(input.bias_dtype) && input.bias_dtype != null && input.bias_dtype != vars.out))",
         "title": "A bias has N elements and the output dtype", "source": src(CP, "assert bias is None or bias.numel() == b.shape[1] and bias.dtype == out_dtype", start=SMM_START),
         "then": [{"fail": {"code": "assertion-error", "message": ""}}]},
        {"if": "config['vllm-target-device'] == 'rocm' || input.k % 16 != 0 || input.n % 16 != 0", "title": "ROCm or B not 16-aligned: Triton scaled_mm",
         "source": src(CP, "if current_platform.is_rocm() or not cutlass_compatible_b:", start=SMM_START),
         "then": [{"set": {"ctx.scaled_mm_backend": "triton"}, "title": "triton_scaled_mm (compressed-tensors, models-layers) computes the GEMM",
                   "source": src(CP, "out = triton_scaled_mm(a, b, scale_a, scale_b, out_dtype, bias)", start=SMM_START)},
                  {"return": {"backend": "triton", "kernel": "triton_scaled_mm"}}]},
        {"title": "torch.ops._C.cutlass_scaled_mm(out, a, b, scale_a, scale_b, bias)", "source": src(CP, "torch.ops._C.cutlass_scaled_mm(out, a, b, scale_a, scale_b, bias)", start=SMM_START),
         "call": "torch-bindings.cutlass-scaled-mm", "as": "mm",
         "input": {"m": "= input.m", "n": "= input.n", "k": "= input.k", "dtype_bytes": "= input.dtype_bytes", "out_dtype": "= vars.out", "has_bias": "= vars.bias",
                   "a_dtype": "= has(input.a_dtype) && input.a_dtype != null ? input.a_dtype : (input.dtype_bytes == 1 ? 'float8_e4m3fn' : 'bfloat16')",
                   "scales": MMD % ("scales", "scales", "'per_tensor'"), "a_scale_cols": "= has(input.a_scale_cols) ? input.a_scale_cols : null"}},
        {"return": {"backend": "cutlass", "kernel": "= vars.mm.value.kernel"}},
    ]}

# ====================================================================== FP8 quant: scaled_fp8_quant and static_scaled_fp8_quant
F8_START = findline(CP, "def scaled_fp8_quant(")
F8_REQ = {"type": "object", "properties": {
    "num_tokens": {"type": "integer", "examples": [16]}, "hidden_size": {"type": "integer", "examples": [4096]}, "dtype_bytes": {"type": "integer", "examples": [2]},
    "has_scale": {"type": "boolean", "default": False}, "use_per_token_if_dynamic": {"type": "boolean", "default": False}, "has_scale_ub": {"type": "boolean", "default": False},
    "num_token_padding": {"type": ["integer", "null"], "default": None, "description": "null: None (0 is falsy for the padding but is not None for the output assert)"},
    "has_output": {"type": "boolean", "default": False}, "output_dtype": {"type": ["string", "null"], "default": None, "description": "a caller-provided output's dtype; null: the platform FP8 dtype"},
    "ndim": {"type": "integer", "examples": [2]},
    "scale_shape": {"type": "array", "items": {"type": "integer"}, "default": [1], "description": "static scale shape: [] or [1] per-tensor, [n] 1-D, [a, b] 2-D groups"},
    "group_shape": {"type": ["array", "null"], "items": {"type": "integer"}, "default": None}}}
I["custom-ops.scaled-fp8-quant"] = {
    "component": "custom-ops", "name": "scaled-fp8-quant", "kind": "function", "latency_ms": 0,
    "summary": "scaled_fp8_quant: static (any scale shape, with group_shape), dynamic per-tensor or dynamic per-token FP8 quantization into the platform FP8 dtype.",
    "sources": [src(CP, "def scaled_fp8_quant(", span=68)],
    "request": F8_REQ,
    "response": {"type": "object", "properties": {"rows": {"type": "integer"}, "cols": {"type": "integer"}, "scale_shape": {"type": "array", "items": {"type": "integer"}},
                                                  "kernel": {"type": "string"}, "out_dtype": {"type": "string"}, "group_m": {"type": "integer"}, "group_n": {"type": "integer"}}},
    "errors": ERR("assertion-error", "runtime-error"),
    "behavior": [
        {"if": "input.ndim != 2", "title": "Input must be 2D [M, N] (a bare assert: empty message)", "source": src(CP, "assert input.ndim == 2", start=F8_START),
         "then": [{"fail": {"code": "assertion-error", "message": ""}}]},
        {"set": {"vars.fp8": "= config['vllm-target-device'] == 'rocm' ? 'float8_e4m3fnuz' : 'float8_e4m3fn'",
                 "vars.pad": "= has(input.num_token_padding) && input.num_token_padding != null ? input.num_token_padding : null"},
         "title": "out_dtype = current_platform.fp8_dtype() (e4m3fnuz on ROCm MI300)", "source": src(CP, "out_dtype: torch.dtype = current_platform.fp8_dtype()", start=F8_START)},
        {"set": {"vars.rows": "= vars.pad != null && vars.pad > input.num_tokens ? vars.pad : input.num_tokens"},
         "title": "if num_token_padding: rows = max(num_token_padding, M)", "source": src(CP, "shape = (max(num_token_padding, input.shape[0]), shape[1])", start=F8_START)},
        {"if": "has(input.has_output) && input.has_output", "title": "A caller-provided output: no padding argument at all, and the FP8 dtype",
         "source": src(CP, 'assert num_token_padding is None, "padding not supported if output passed in"', start=F8_START),
         "then": [{"if": "vars.pad != null", "then": [{"fail": {"code": "assertion-error", "message": "padding not supported if output passed in"}}]},
                  {"if": "has(input.output_dtype) && input.output_dtype != null && input.output_dtype != vars.fp8",
                   "source": src(CP, "assert output.dtype == out_dtype", start=F8_START),
                   "then": [{"fail": {"code": "assertion-error", "message": ""}}]}]},
        {"if": "has(input.has_scale) && input.has_scale", "title": "Scale given: static quantization with the optional group_shape", "source": src(CP, "torch.ops._C.static_scaled_fp8_quant(output, input, scale, group_shape)", start=F8_START),
         "then": [{"call": "torch-bindings.static-scaled-fp8-quant", "as": "st",
                   "input": {"num_tokens": "= vars.rows", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes",
                             "scale_shape": "= has(input.scale_shape) ? input.scale_shape : [1]", "group_shape": "= has(input.group_shape) ? input.group_shape : null"}},
                  {"return": {"rows": "= vars.rows", "cols": "= input.hidden_size", "scale_shape": "= has(input.scale_shape) ? input.scale_shape : [1]",
                              "kernel": "static_scaled_fp8_quant", "out_dtype": "= vars.fp8", "group_m": "= vars.st.value.group_m", "group_n": "= vars.st.value.group_n"}}]},
        {"if": "has(input.use_per_token_if_dynamic) && input.use_per_token_if_dynamic", "title": "Dynamic per-token: one scale per output row (bounded by scale_ub)",
         "source": src(CP, "torch.ops._C.dynamic_per_token_scaled_fp8_quant(", start=F8_START),
         "then": [{"call": "torch-bindings.dynamic-per-token-scaled-fp8-quant", "input": {"num_tokens": "= vars.rows", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}},
                  {"set": {"ctx.scale_ub_applied": "= has(input.has_scale_ub) && input.has_scale_ub"}},
                  {"return": {"rows": "= vars.rows", "cols": "= input.hidden_size", "scale_shape": ["= vars.rows", 1], "kernel": "dynamic_per_token_scaled_fp8_quant",
                              "out_dtype": "= vars.fp8", "group_m": 1, "group_n": "= input.hidden_size"}}]},
        {"title": "Dynamic per-tensor: one scale", "source": src(CP, "torch.ops._C.dynamic_scaled_fp8_quant(output, input, scale)", start=F8_START),
         "call": "torch-bindings.dynamic-scaled-fp8-quant", "input": {"num_tokens": "= vars.rows", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}},
        {"return": {"rows": "= vars.rows", "cols": "= input.hidden_size", "scale_shape": [1], "kernel": "dynamic_scaled_fp8_quant", "out_dtype": "= vars.fp8",
                    "group_m": "= vars.rows", "group_n": "= input.hidden_size"}},
    ]}

ST_START = findline(FP8C, "void static_scaled_fp8_quant(")
OP_BEHAVIORS["torch-bindings.static-scaled-fp8-quant"] = {
    "request": {"type": "object", "properties": {
        "num_tokens": {"type": "integer", "examples": [16]}, "hidden_size": {"type": "integer", "examples": [4096]}, "dtype_bytes": {"type": "integer", "examples": [2]},
        "scale_shape": {"type": "array", "items": {"type": "integer"}, "default": [1]}, "group_shape": {"type": ["array", "null"], "items": {"type": "integer"}, "default": None}}},
    "response": {"type": "object", "properties": {"group_m": {"type": "integer"}, "group_n": {"type": "integer"}}},
    "errors": ERR("runtime-error"),
    "behavior": [
        {"set": {"vars.s": "= has(input.scale_shape) ? input.scale_shape : [1]", "vars.g": "= has(input.group_shape) ? input.group_shape : null",
                 "vars.M": "= input.num_tokens", "vars.N": "= input.hidden_size"}},
        {"set": {"vars.numel": "= size(vars.s) == 0 ? 1 : (size(vars.s) == 1 ? vars.s[0] : vars.s[0] * vars.s[1])"}},
        {"if": "size(vars.s) == 0 || vars.numel == 1", "title": "Per-tensor: one scale", "source": src(FP8C, "if (scale.dim() == 0 || scale.numel() == 1) {", start=ST_START),
         "then": [{"return": {"group_m": "= vars.M", "group_n": "= vars.N"}}]},
        {"if": "vars.g != null && size(vars.g) != 2", "title": "group_shape has two elements", "source": src(FP8C, '"group_shape must have exactly 2 elements, got ",', start=ST_START),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'group_shape must have exactly 2 elements, got ' + string(size(vars.g))"}}]},
        {"if": "size(vars.s) == 1", "title": "1-D scale: needs an explicit group_shape, which must match its length and leave one scale dim at 1",
         "source": src(FP8C, "} else if (scale.dim() == 1) {", start=ST_START),
         "then": [
             {"if": "vars.g == null", "source": src(FP8C, "opt_group_shape.has_value(),", start=ST_START),
              "then": [{"fail": {"code": "runtime-error", "message": "1D scale requires explicit group_shape to disambiguate per-channel vs per-token quantization. Use group_shape=(-1, 1) for per-channel or group_shape=(1, -1) for per-token."}}]},
             {"set": {"vars.gm": "= vars.g[0] == -1 ? vars.M : vars.g[0]", "vars.gn": "= vars.g[1] == -1 ? vars.N : vars.g[1]"}},
             {"set": {"vars.em": "= vars.M / vars.gm", "vars.en": "= vars.N / vars.gn"}},
             {"if": "vars.numel != vars.em * vars.en", "source": src(FP8C, 'STD_TORCH_CHECK(scale_len == expected_scale_numel, "1D scale length (",', start=ST_START),
              "then": [{"fail": {"code": "runtime-error", "message": "= '1D scale length (' + string(vars.numel) + ') does not match expected size (' + string(vars.em * vars.en) + ') for group_shape (' + string(vars.g[0]) + ', ' + string(vars.g[1]) + ') with input shape (' + string(vars.M) + ', ' + string(vars.N) + ')'"}}]},
             {"if": "vars.em != 1 && vars.en != 1", "source": src(FP8C, '"1D scale can only be used when one of the scale dimensions is 1. "', start=ST_START),
              "then": [{"fail": {"code": "runtime-error", "message": "1D scale can only be used when one of the scale dimensions is 1. For 2D group scaling, use a 2D scale tensor."}}]},
             {"return": {"group_m": "= vars.gm", "group_n": "= vars.gn"}}]},
        {"if": "vars.M % vars.s[0] != 0", "title": "2-D scale: its dims divide the input", "source": src(FP8C, 'STD_TORCH_CHECK(num_tokens % scale_size_0 == 0, "num_tokens (", num_tokens,', start=ST_START),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'num_tokens (' + string(vars.M) + ') must be divisible by scale.size(0) (' + string(vars.s[0]) + ')'"}}]},
        {"if": "vars.N % vars.s[1] != 0", "source": src(FP8C, 'STD_TORCH_CHECK(hidden_size % scale_size_1 == 0, "hidden_size (",', start=ST_START),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'hidden_size (' + string(vars.N) + ') must be divisible by scale.size(1) (' + string(vars.s[1]) + ')'"}}]},
        {"set": {"vars.igm": "= vars.M / vars.s[0]", "vars.ign": "= vars.N / vars.s[1]"}, "title": "Group shape inferred from the scale", "source": src(FP8C, "int inferred_group_m = num_tokens / scale_size_0;", start=ST_START)},
        {"if": "vars.g != null", "then": [
            {"set": {"vars.gm": "= vars.g[0] == -1 ? vars.M : vars.g[0]", "vars.gn": "= vars.g[1] == -1 ? vars.N : vars.g[1]"}},
            {"if": "vars.gm != vars.igm || vars.gn != vars.ign", "title": "An explicit group_shape must match the inferred one", "source": src(FP8C, '"Explicit group_shape (", opt_group_m, ", ", opt_group_n,', start=ST_START),
             "then": [{"fail": {"code": "runtime-error", "message": "= 'Explicit group_shape (' + string(vars.g[0]) + ', ' + string(vars.g[1]) + ') does not match inferred group shape (' + string(vars.igm) + ', ' + string(vars.ign) + ') from 2D scale tensor shape (' + string(vars.s[0]) + ', ' + string(vars.s[1]) + ')'"}}]}]},
        {"return": {"group_m": "= vars.igm", "group_n": "= vars.ign"}},
    ]}

# silu_and_mul_quant host checks (round-5 unit test 6)
OP_BEHAVIORS["torch-bindings.silu-and-mul-quant"] = {
    "request": {"type": "object", "properties": {
        "num_tokens": {"type": "integer", "examples": [16]}, "hidden_size": {"type": "integer", "examples": [28672], "description": "input.size(-1) = 2 * d"},
        "dtype_bytes": {"type": "integer", "examples": [2]}, "input_dtype": {"type": ["string", "null"], "default": None, "description": "null: bfloat16 for 2 bytes, float32 for 4"},
        "out_dtype": {"type": "string", "default": "float8_e4m3fn"}}},
    "response": {"type": "object", "properties": {"out_shape": {"type": "array", "items": {"type": "integer"}}, "out_dtype": {"type": "string"}}},
    "errors": ERR("runtime-error"),
    "behavior": [
        {"set": {"vars.out": "= has(input.out_dtype) ? input.out_dtype : 'float8_e4m3fn'",
                 "vars.idt": "= has(input.input_dtype) && input.input_dtype != null ? input.input_dtype : (input.dtype_bytes == 2 ? 'bfloat16' : (input.dtype_bytes == 4 ? 'float32' : 'float8_e4m3fn'))"}},
        {"if": "!(vars.out in ['float8_e4m3fn', 'float8_e4m3fnuz'])", "title": "Output is FP8 e4m3 (fn or fnuz)", "source": src(ACTQ, "out.scalar_type() == torch::headeronly::ScalarType::Float8_e4m3fn ||"),
         "then": [{"fail": {"code": "runtime-error", "message": chk("out.scalar_type() == torch::headeronly::ScalarType::Float8_e4m3fn || out.scalar_type() == torch::headeronly::ScalarType::Float8_e4m3fnuz")}}]},
        {"if": "!(vars.idt in ['float16', 'bfloat16'])", "title": "Input is FP16 or BF16", "source": src(ACTQ, '"Input must be FP16 or BF16");'),
         "then": [{"fail": {"code": "runtime-error", "message": "Input must be FP16 or BF16"}}]},
        {"if": "input.hidden_size % 2 != 0", "title": "The gate and up halves have equal width", "source": src(ACTQ, "STD_TORCH_CHECK(input.size(-1) % 2 == 0);", start=findline(ACTQ, "void silu_and_mul_quant(")),
         "then": [{"fail": {"code": "runtime-error", "message": chk("input.size(-1) % 2 == 0")}}]},
        {"return": {"out_shape": ["= input.num_tokens", "= input.hidden_size / 2"], "out_dtype": "= vars.out"},
         "title": "LAUNCH_ACTIVATION_GATE_KERNEL(silu_kernel): out[..., d] = fp8(silu(x[..., :d]) * x[..., d:] / scale)",
         "source": src(ACTQ, "LAUNCH_ACTIVATION_GATE_KERNEL(vllm::silu_kernel);", start=findline(ACTQ, "void silu_and_mul_quant("))},
    ]}

# ====================================================================== MoE routing and expert alignment (MoE world)
MOE_REQ = {"type": "object", "properties": {
    "num_tokens": {"type": "integer", "examples": [16]}, "num_experts": {"type": "integer", "examples": [8]}, "topk": {"type": "integer", "examples": [2]},
    "n": {"type": "integer", "examples": [14336]}, "k": {"type": "integer", "examples": [4096]},
    "dtype_bytes": {"type": "integer", "examples": [4], "description": "gating_output element size: 4 float32, 2 bfloat16/float16"},
    "gating_dtype": {"type": ["string", "null"], "default": None, "description": "Float, Half or BFloat16; null: from dtype_bytes (2 is BFloat16)"},
    "topk_ids_dtype": {"type": "string", "enum": ["int32", "uint32", "int64", "int16"], "default": "int32"},
    "bias": {"type": ["object", "null"], "default": None, "description": "e_score_correction_bias: {dtype, ndim, numel, contiguous}"},
    "is_padding": {"type": ["object", "null"], "default": None, "description": "{dtype, ndim, numel, contiguous}"}}}


def topk_behavior(fn, sf):
    start = findline(TKS, f"void {fn}(")
    return [
        {"set": {"vars.E": "= input.num_experts", "vars.T": "= input.num_tokens",
                 "vars.gd": "= has(input.gating_dtype) && input.gating_dtype != null ? input.gating_dtype : (input.dtype_bytes == 4 ? 'Float' : (input.dtype_bytes == 2 ? 'BFloat16' : 'Double'))"}},
        {"set": {"vars.pow2": "= vars.E != 0 && [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024].exists(p, p == vars.E)"},
         "title": "is_pow_2 = num_experts & (num_experts - 1) == 0", "source": src(TKS, "const bool is_pow_2 = (num_experts != 0) && ((num_experts & (num_experts - 1)) == 0);", start=start)},
        {"set": {"vars.ws": "= (!vars.pow2 || vars.E > 256) ? vars.T * vars.E : 0"}, "title": "A float workspace of num_tokens * num_experts unless a power of two <= 256",
         "source": src(TKS, "const int64_t workspace_size = needs_workspace ? num_tokens * num_experts : 0;", start=start)},
        {"if": "!(vars.gd in ['Float', 'Half', 'BFloat16'])", "title": "Gating logits are float32, float16 or bfloat16", "source": src(TKS, '"Unsupported gating_output data type: ", gating_output.scalar_type());', start=start),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'Unsupported gating_output data type: ' + vars.gd"}}]},
        {"if": "has(input.bias) && input.bias != null", "title": "An e_score_correction_bias is float32, 1-D, one per expert, contiguous", "source": src(TKS, '"bias tensor must be float32");'),
         "then": [
             {"if": "input.bias.dtype != 'float32'", "then": [{"fail": {"code": "runtime-error", "message": "bias tensor must be float32"}}]},
             {"if": "input.bias.ndim != 1", "then": [{"fail": {"code": "runtime-error", "message": "bias tensor must be 1D"}}]},
             {"if": "input.bias.numel != vars.E", "source": src(TKS, '"bias size mismatch, expected: ", num_experts);'),
              "then": [{"fail": {"code": "runtime-error", "message": "= 'bias size mismatch, expected: ' + string(vars.E)"}}]},
             {"if": "has(input.bias.contiguous) && !input.bias.contiguous", "then": [{"fail": {"code": "runtime-error", "message": "bias tensor must be contiguous"}}]}]},
        {"if": "has(input.is_padding) && input.is_padding != null", "title": "is_padding is bool, 1-D, one per token, contiguous", "source": src(TKS, '"is_padding tensor must be bool");'),
         "then": [
             {"if": "input.is_padding.dtype != 'bool'", "then": [{"fail": {"code": "runtime-error", "message": "is_padding tensor must be bool"}}]},
             {"if": "input.is_padding.ndim != 1", "then": [{"fail": {"code": "runtime-error", "message": "is_padding tensor must be 1D"}}]},
             {"if": "input.is_padding.numel != vars.T", "source": src(TKS, '"is_padding size mismatch, expected: ", num_tokens);'),
              "then": [{"fail": {"code": "runtime-error", "message": "= 'is_padding size mismatch, expected: ' + string(vars.T)"}}]},
             {"if": "has(input.is_padding.contiguous) && !input.is_padding.contiguous", "then": [{"fail": {"code": "runtime-error", "message": "is_padding tensor must be contiguous"}}]}]},
        {"if": "has(input.topk_ids_dtype) && !(input.topk_ids_dtype in ['int32', 'uint32', 'int64'])", "title": "topk_indices are int32, uint32 or int64",
         "source": src(TKS, "STD_TORCH_CHECK(topk_indices.scalar_type() == torch::headeronly::ScalarType::Long);"),
         "then": [{"fail": {"code": "runtime-error", "message": chk("topk_indices.scalar_type() == torch::headeronly::ScalarType::Long")}}]},
        {"if": "vars.pow2 && vars.E <= 512", "title": "Power of two up to 512: the fused warp-per-row topkGating kernel (16-byte loads)", "source": src(TKS, "LAUNCH_TOPK(512, WARPS_PER_TB, BYTES_PER_LDG_POWER_OF_2);"),
         "then": [{"return": {"kernel": "topkGating", "bytes_per_ldg": 16, "workspace_size": "= vars.ws", "scoring": sf}}]},
        {"if": "config['vllm-target-device'] != 'rocm' && vars.E in [192, 320, 384, 448, 576]", "title": "CUDA: multiples of 64 also fuse (4-byte loads for 16-bit logits, else 8)",
         "source": src(TKS, "LAUNCH_TOPK(192, WARPS_PER_TB, BYTES_PER_LDG_MULTIPLE_64);"),
         "then": [{"return": {"kernel": "topkGating", "bytes_per_ldg": "= vars.gd == 'Float' ? 8 : 4", "workspace_size": "= vars.ws", "scoring": sf}}]},
        {"title": "Otherwise softmax (or sigmoid) into the workspace, then moeTopK, 256 threads per token", "source": src(TKS, "moeTopK<TPB><<<num_tokens, TPB, 0, stream>>>("),
         "return": {"kernel": "moeSoftmax+moeTopK" if sf == "softmax" else "moeSigmoid+moeTopK", "bytes_per_ldg": 0, "workspace_size": "= vars.ws", "scoring": sf}},
    ]


TOPK_RESP = {"type": "object", "properties": {"kernel": {"type": "string"}, "bytes_per_ldg": {"type": "integer"}, "workspace_size": {"type": "integer"}, "scoring": {"type": "string"}}}
OP_BEHAVIORS["moe-torch-bindings.topk-softmax"] = {"request": MOE_REQ, "response": TOPK_RESP, "errors": ERR("runtime-error"), "behavior": topk_behavior("topk_softmax", "softmax")}
OP_BEHAVIORS["moe-torch-bindings.topk-sigmoid"] = {"request": MOE_REQ, "response": TOPK_RESP, "errors": ERR("runtime-error"), "behavior": topk_behavior("topk_sigmoid", "sigmoid")}
for w, op in [("topk-softmax", "topk_softmax"), ("topk-sigmoid", "topk_sigmoid")]:
    I[f"custom-ops.{w}"] = {"component": "custom-ops", "name": w, "kind": "function", "latency_ms": 0,
                            "summary": f"{op}: writes topk_weights / topk_ids / token_expert_indices in place through torch.ops._moe_C.{op}.",
                            "sources": [], "request": MOE_REQ, "response": TOPK_RESP, "errors": ERR("runtime-error"),
                            "behavior": [{"call": f"moe-torch-bindings.{w}", "input": "= input", "as": "r", "title": f"torch.ops._moe_C.{op}(...)",
                                          "source": src(CP, f"torch.ops._moe_C.{op}(")},
                                         {"return": "= vars.r.value"}]}

ALIGN_REQ = {"type": "object", "properties": {
    "num_tokens": {"type": "integer", "examples": [16]}, "num_experts": {"type": "integer", "examples": [8]}, "topk": {"type": "integer", "examples": [2]},
    "block_size": {"type": "integer", "default": 16}, "has_expert_map": {"type": "boolean", "default": False},
    "scatter_idx": {"type": ["object", "null"], "default": None, "description": "{dtype, numel, contiguous, same_device}"},
    "n": {"type": "integer"}, "k": {"type": "integer"}, "dtype_bytes": {"type": "integer"}}}
ALIGN_RESP = {"type": "object", "properties": {"kernel": {"type": "string"}, "padded_num_experts": {"type": "integer"}, "threads": {"type": "integer"},
                                               "max_num_tokens_padded": {"type": "integer"}}}
AL_START = findline(MAS, "void moe_align_block_size(torch::stable::Tensor topk_ids, int64_t num_experts,")
OP_BEHAVIORS["moe-torch-bindings.moe-align-block-size"] = {
    "request": ALIGN_REQ, "response": ALIGN_RESP, "errors": ERR("runtime-error"),
    "behavior": [
        {"set": {"vars.W": "= config['vllm-target-device'] == 'rocm' ? 64 : 32", "vars.numel": "= input.num_tokens * input.topk",
                 "vars.E": "= input.num_experts", "vars.bs": "= has(input.block_size) ? input.block_size : 16"},
         "title": "WARP_SIZE: 32 on CUDA, 64 on ROCm", "source": src(MAS, "int64_t padded_num_experts =", start=AL_START)},
        {"if": "has(input.scatter_idx) && input.scatter_idx != null", "title": "scatter_idx: int32, contiguous, on the device, one per top-k slot", "source": src(MAS, '"scatter_idx must be int32");', start=AL_START),
         "then": [{"if": "input.scatter_idx.dtype != 'int32'", "then": [{"fail": {"code": "runtime-error", "message": "scatter_idx must be int32"}}]},
                  {"if": "input.scatter_idx.numel != vars.numel || (has(input.scatter_idx.contiguous) && !input.scatter_idx.contiguous) || (has(input.scatter_idx.same_device) && !input.scatter_idx.same_device)",
                   "source": src(MAS, '"scatter_idx must be contiguous, on the same device, and "', start=AL_START),
                   "then": [{"fail": {"code": "runtime-error", "message": "scatter_idx must be contiguous, on the same device, and match topk_ids.numel()"}}]}]},
        {"set": {"vars.pe": "= ((vars.E + vars.W - 1) / vars.W) * vars.W"}, "title": "padded_num_experts rounds num_experts up to a warp", "source": src(MAS, "((num_experts + WARP_SIZE - 1) / WARP_SIZE) * WARP_SIZE;", start=AL_START)},
        {"if": "vars.pe >= 1024", "title": "BlockScan uses 1024 threads, one per expert", "source": src(MAS, '"padded_num_experts must be less than 1024");', start=AL_START),
         "then": [{"fail": {"code": "runtime-error", "message": "padded_num_experts must be less than 1024"}}]},
        {"set": {"vars.maxpad": "= vars.numel + vars.E * (vars.bs - 1)"},
         "title": "The caller sizes sorted_token_ids for the worst case: numel + num_experts * (block_size - 1) (fused_moe/moe_align_block_size.py, models-layers)"},
        {"if": "vars.numel < 1024 && vars.E <= 64", "title": "Small batch, few experts: one block, 256 fill threads + max(E, warp) counting threads",
         "source": src(MAS, "(topk_ids.numel() < 1024) && (num_experts <= 64);", start=AL_START),
         "then": [{"return": {"kernel": "moe_align_block_size_small_batch_expert_kernel", "padded_num_experts": "= vars.pe",
                              "threads": "= 256 + (vars.E > vars.W ? vars.E : vars.W)", "max_num_tokens_padded": "= vars.maxpad"}}]},
        {"title": "Otherwise two 1024-thread blocks: count + align, and fill sorted_token_ids", "source": src(MAS, "align_kernel<<<2, threads, shared_mem_size, stream>>>(", start=AL_START),
         "return": {"kernel": "moe_align_block_size_kernel", "padded_num_experts": "= vars.pe", "threads": 1024, "max_num_tokens_padded": "= vars.maxpad"}},
    ]}
MA_START = findline(CP, "def moe_align_block_size(")
I["custom-ops.moe-align-block-size"] = {
    "component": "custom-ops", "name": "moe-align-block-size", "kind": "function", "latency_ms": 0,
    "summary": "moe_align_block_size: torch.ops._moe_C.moe_align_block_size sorts the top-k slots by expert, padded per expert to block_size; XPU takes no scatter_idx.",
    "sources": [], "request": ALIGN_REQ, "response": ALIGN_RESP, "errors": ERR("not-implemented-error", "runtime-error"),
    "behavior": [
        {"if": "config['vllm-target-device'] == 'xpu' && has(input.scatter_idx) && input.scatter_idx != null", "title": "XPU's kernel has no scatter_idx",
         "source": src(CP, 'raise NotImplementedError("scatter_idx is not supported on XPU")', start=MA_START),
         "then": [{"fail": {"code": "not-implemented-error", "message": "scatter_idx is not supported on XPU"}}]},
        {"call": "moe-torch-bindings.moe-align-block-size", "input": "= input", "as": "r", "title": "torch.ops._moe_C.moe_align_block_size(...)",
         "source": src(CP, "torch.ops._moe_C.moe_align_block_size(", start=MA_START, nth=2)},
        {"return": "= vars.r.value"},
    ]}

# ====================================================================== scenarios: the FP8 and MoE worlds, and the error paths
FP8W = ["full-fp8-llama-3-8b"]
MOEW = ["full-moe-mixtral-8x7b-tp2-ep"]
A100 = {"torch-bindings": {"device_capability": {"major": 8, "minor": 0}}}
L40S = {"torch-bindings": {"device_capability": {"major": 8, "minor": 9}}}
V100 = {"torch-bindings": {"device_capability": {"major": 7, "minor": 0}}}
B200 = {"torch-bindings": {"device_capability": {"major": 10, "minor": 0}}}
SCENARIOS += [
    {"id": "kernels-ops-fp8-world-capability-queries", "name": "FP8 world on H100: CUTLASS FP8, block-FP8 and grouped FP8 GEMMs are all supported; an A100 supports none",
     "description": "Fp8LinearMethod's kernel choice asks cutlass_scaled_mm_supports_fp8 / _block_fp8 / cutlass_group_gemm_supported with the device capability "
                    "(scaled_mm_entry.cu:139-189); the _C build is CUDA 13.0.",
     "fixtures": FP8W,
     "steps": [{"interface": "custom-ops.cutlass-scaled-mm-supports-fp8", "caller": "gpu-worker", "as": "fp8", "input": {"cuda_device_capability": 90}},
               {"interface": "custom-ops.cutlass-scaled-mm-supports-block-fp8", "caller": "gpu-worker", "as": "blk", "input": {"cuda_device_capability": 90}},
               {"interface": "custom-ops.cutlass-group-gemm-supported", "caller": "gpu-worker", "as": "grp", "input": {"cuda_device_capability": 90}},
               {"interface": "custom-ops.cutlass-scaled-mm-supports-fp8", "caller": "gpu-worker", "as": "a100", "input": {"cuda_device_capability": 80}},
               {"interface": "custom-ops.cutlass-scaled-mm-supports-fp8", "caller": "gpu-worker", "as": "ada", "input": {"cuda_device_capability": 89}},
               {"interface": "custom-ops.cutlass-group-gemm-supported", "caller": "gpu-worker", "as": "sm120", "input": {"cuda_device_capability": 120}}],
     "expect": ["steps.fp8.result.value.supported && steps.blk.result.value.supported && steps.grp.result.value.supported",
                "!steps.a100.result.value.supported && steps.ada.result.value.supported && !steps.sm120.result.value.supported"]},
    {"id": "kernels-ops-fp8-world-cuda-12-1-build", "name": "A _C built with CUDA 12.1: SM89 FP8 needs 12.4 and grouped FP8 needs 12.3, so both are off; SM90 FP8 stays on",
     "fixtures": FP8W, "config": {"vllm-cuda-version": 12010},
     "steps": [{"interface": "custom-ops.cutlass-scaled-mm-supports-fp8", "caller": "gpu-worker", "as": "ada", "input": {"cuda_device_capability": 89}},
               {"interface": "custom-ops.cutlass-scaled-mm-supports-fp8", "caller": "gpu-worker", "as": "h100", "input": {"cuda_device_capability": 90}},
               {"interface": "custom-ops.cutlass-group-gemm-supported", "caller": "gpu-worker", "as": "grp", "input": {"cuda_device_capability": 90}}],
     "expect": ["!steps.ada.result.value.supported && steps.h100.result.value.supported && !steps.grp.result.value.supported"]},
    {"id": "kernels-ops-fp8-world-static-linear", "name": "FP8 world, one QKV projection of a 16-token decode: static per-tensor activation quant, then the SM90 CUTLASS FP8 GEMM",
     "description": "neuralmagic/Meta-Llama-3-8B-Instruct-FP8-KV has activation_scheme static, so Fp8LinearMethod quantizes with the checkpoint's input_scale "
                    "(scaled_fp8_quant with a scale) and calls cutlass_scaled_mm (N = 4096 + 2 * 1024 = 6144 for QKV); on H100 that is cutlass_scaled_mm_sm90_fp8.",
     "fixtures": FP8W,
     "steps": [{"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "q", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2, "has_scale": True, "scale_shape": [1]}},
               {"interface": "custom-ops.cutlass-scaled-mm", "caller": "gpu-worker", "as": "mm", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1, "out_dtype": "bfloat16"}}],
     "expect": ["steps.q.result.ok && steps.q.result.value.kernel == 'static_scaled_fp8_quant' && steps.q.result.value.out_dtype == 'float8_e4m3fn' && steps.q.result.value.group_m == 16 && steps.q.result.value.group_n == 4096",
                "steps.mm.result.ok && steps.mm.result.value.backend == 'cutlass' && steps.mm.result.value.kernel == 'cutlass_scaled_mm_sm90_fp8'"]},
    {"id": "kernels-ops-fp8-world-gemm-sm89", "name": "The FP8 GEMM on an L40S (SM89): the CUTLASS 2.x Ada FP8 kernel",
     "fixtures": FP8W, "state": L40S,
     "steps": [{"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "ada", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1}}],
     "expect": ["steps.ada.result.ok && steps.ada.result.value.kernel == 'cutlass_scaled_mm_sm89_fp8' && steps.ada.result.value.version_num == 89"]},
    {"id": "kernels-ops-fp8-world-gemm-sm100", "name": "On a B200 (SM100) FP8 runs the CUTLASS 3.x SM100 kernel; INT8 has no SM100 kernel",
     "fixtures": FP8W, "state": B200,
     "steps": [{"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "b200", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1}},
               {"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "i8sm100", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1, "a_dtype": "int8"}}],
     "expect": ["steps.b200.result.value.kernel == 'cutlass_scaled_mm_sm100_fp8'",
                "!steps.i8sm100.result.ok && steps.i8sm100.result.error.message == 'Int8 not supported on SM100. Use FP8 quantization instead, or run on older arch (SM < 100).'"]},
    {"id": "kernels-ops-fp8-world-gemm-sm80", "name": "On an A100 (SM80) the CUTLASS kernels are INT8 only: an FP8 GEMM fails the dtype check",
     "fixtures": FP8W, "state": A100,
     "steps": [{"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "a100", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1}},
               {"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "a100i8", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1, "a_dtype": "int8"}}],
     "expect": ["!steps.a100.result.ok && steps.a100.result.error.code == 'runtime-error' && steps.a100.result.error.message == 'Expected a.scalar_type() == torch::headeronly::ScalarType::Char to be true, but got false.'",
                "steps.a100i8.result.value.kernel == 'cutlass_scaled_mm_sm80_int8'"]},
    {"id": "kernels-ops-fp8-world-gemm-sm70", "name": "On a V100 (SM70) no cutlass_scaled_mm kernel is compiled: a RuntimeError with the NotImplementedError prefix",
     "fixtures": FP8W, "state": V100,
     "steps": [{"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "v100", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1}}],
     "expect": ["!steps.v100.result.ok && steps.v100.result.error.code == 'runtime-error' && steps.v100.result.error.message == 'NotImplementedError: No compiled cutlass_scaled_mm for a compute capability less than CUDA device capability: 70'"]},
    {"id": "kernels-ops-fp8-world-blockwise-and-int8", "name": "Blockwise FP8 scales need [1, 128] activation groups and no bias; INT8 has no SM100 kernel",
     "fixtures": FP8W,
     "steps": [{"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "blk", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1, "scales": "blockwise"}},
               {"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "badgrp", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1, "scales": "blockwise", "a_scale_cols": 64}},
               {"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "bias", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1, "scales": "blockwise", "has_bias": True}},
               {"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "i8sm90", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 1, "a_dtype": "int8"}},
               {"interface": "torch-bindings.cutlass-scaled-mm", "caller": "gpu-worker", "as": "bf16", "input": {"m": 16, "n": 6144, "k": 4096, "dtype_bytes": 2, "a_dtype": "bfloat16"}}],
     "expect": ["steps.blk.result.value.kernel == 'cutlass_scaled_mm_blockwise_sm90_fp8'",
                "!steps.badgrp.result.ok && steps.badgrp.result.error.message == 'a_scale_group_shape must be [1, 128].'",
                "!steps.bias.result.ok && steps.bias.result.error.message == 'Bias not yet supported blockwise scaled_mm'",
                "steps.i8sm90.result.value.kernel == 'cutlass_scaled_mm_sm90_int8'",
                "!steps.bf16.result.ok && steps.bf16.result.error.message.contains('ScalarType::Char')"]},
    {"id": "kernels-ops-scaled-fp8-quant-static-groups", "name": "static_scaled_fp8_quant scale shapes: per-channel 1-D with (-1, 1), 2-D (1, 128) groups, and each refusal",
     "fixtures": FP8W,
     "steps": [{"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "chan", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2, "has_scale": True, "scale_shape": [4096], "group_shape": [-1, 1]}},
               {"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "grp", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2, "has_scale": True, "scale_shape": [16, 32]}},
               {"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "nogs", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2, "has_scale": True, "scale_shape": [4096]}},
               {"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "len", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2, "has_scale": True, "scale_shape": [100], "group_shape": [-1, 1]}},
               {"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "div", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2, "has_scale": True, "scale_shape": [3, 32]}},
               {"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "mismatch", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2, "has_scale": True, "scale_shape": [16, 32], "group_shape": [1, 64]}}],
     "expect": ["steps.chan.result.value.group_m == 16 && steps.chan.result.value.group_n == 1",
                "steps.grp.result.value.group_m == 1 && steps.grp.result.value.group_n == 128",
                "!steps.nogs.result.ok && steps.nogs.result.error.message.startsWith('1D scale requires explicit group_shape')",
                "!steps.len.result.ok && steps.len.result.error.message == '1D scale length (100) does not match expected size (4096) for group_shape (-1, 1) with input shape (16, 4096)'",
                "!steps.div.result.ok && steps.div.result.error.message == 'num_tokens (16) must be divisible by scale.size(0) (3)'",
                "!steps.mismatch.result.ok && steps.mismatch.result.error.message == 'Explicit group_shape (1, 64) does not match inferred group shape (1, 128) from 2D scale tensor shape (16, 32)'"]},
    {"id": "kernels-ops-scaled-fp8-quant-output-asserts", "name": "scaled_fp8_quant with a caller-provided output: num_token_padding=0 is still refused (it is not None), and the output must be FP8",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "zero", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2, "has_output": True, "num_token_padding": 0}},
               {"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "dt", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2, "has_output": True, "output_dtype": "bfloat16"}},
],
     "expect": ["!steps.zero.result.ok && steps.zero.result.error.message == 'padding not supported if output passed in'",
                "!steps.dt.result.ok && steps.dt.result.error.code == 'assertion-error' && steps.dt.result.error.message == ''"]},
    {"id": "kernels-ops-scaled-fp8-quant-rocm-fnuz", "name": "On ROCm the FP8 output dtype is float8_e4m3fnuz, so an e4m3fn output buffer fails the dtype assert",
     "fixtures": ["tp1-llama-8b"], "config": {"vllm-target-device": "rocm"},
     "steps": [{"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "q", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2}},
               {"interface": "custom-ops.scaled-fp8-quant", "caller": "gpu-worker", "as": "fn", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "ndim": 2, "has_output": True, "output_dtype": "float8_e4m3fn"}}],
     "expect": ["steps.q.result.ok && steps.q.result.value.out_dtype == 'float8_e4m3fnuz'", "!steps.fn.result.ok && steps.fn.result.error.code == 'assertion-error'"]},
    {"id": "kernels-ops-moe-world-routing", "name": "MoE world: Mixtral's 8 experts route through the fused topkGating kernel; other expert counts take the workspace path or the multiple-of-64 kernels",
     "description": "topk_softmax (csrc/moe/topk_softmax_kernels.cu:822-860): power-of-two experts <= 512 use topkGating, CUDA also fuses 192/320/384/448/576; "
                    "anything else runs moeSoftmax into a num_tokens * num_experts workspace, then moeTopK.",
     "fixtures": MOEW,
     "steps": [{"interface": "custom-ops.topk-softmax", "caller": "gpu-worker", "as": "mixtral", "input": {"num_tokens": 16, "num_experts": 8, "topk": 2, "dtype_bytes": 4}},
               {"interface": "custom-ops.topk-softmax", "caller": "gpu-worker", "as": "e60", "input": {"num_tokens": 16, "num_experts": 60, "topk": 4, "dtype_bytes": 2}},
               {"interface": "custom-ops.topk-softmax", "caller": "gpu-worker", "as": "e384", "input": {"num_tokens": 16, "num_experts": 384, "topk": 8, "dtype_bytes": 2}},
               {"interface": "custom-ops.topk-sigmoid", "caller": "gpu-worker", "as": "e512", "input": {"num_tokens": 4, "num_experts": 512, "topk": 8, "dtype_bytes": 4}},
               {"interface": "custom-ops.topk-softmax", "caller": "gpu-worker", "as": "fp64", "input": {"num_tokens": 16, "num_experts": 8, "topk": 2, "dtype_bytes": 4, "gating_dtype": "Double"}},
               {"interface": "custom-ops.topk-softmax", "caller": "gpu-worker", "as": "bias", "input": {"num_tokens": 16, "num_experts": 8, "topk": 2, "dtype_bytes": 4, "bias": {"dtype": "float32", "ndim": 1, "numel": 16}}}],
     "expect": ["steps.mixtral.result.ok && steps.mixtral.result.value.kernel == 'topkGating' && steps.mixtral.result.value.workspace_size == 0",
                "steps.e60.result.value.kernel == 'moeSoftmax+moeTopK' && steps.e60.result.value.workspace_size == 960",
                "steps.e384.result.value.kernel == 'topkGating' && steps.e384.result.value.bytes_per_ldg == 4 && steps.e384.result.value.workspace_size == 6144",
                "steps.e512.result.value.kernel == 'topkGating' && steps.e512.result.value.scoring == 'sigmoid' && steps.e512.result.value.workspace_size == 2048",
                "!steps.fp64.result.ok && steps.fp64.result.error.message == 'Unsupported gating_output data type: Double'",
                "!steps.bias.result.ok && steps.bias.result.error.message == 'bias size mismatch, expected: 8'"]},
    {"id": "kernels-ops-moe-world-align", "name": "MoE world: a decode batch aligns in the single-block small-batch kernel, a 2048-token prefill in the two-block kernel; 1000 experts overflow BlockScan",
     "description": "moe_align_block_size (csrc/moe/moe_align_sum_kernels.cu:673-768): small_batch_expert_mode when topk_ids.numel() < 1024 and num_experts <= 64; "
                    "padded_num_experts must stay below 1024. Under EP the global expert ids map through expert_map.",
     "fixtures": MOEW,
     "steps": [{"interface": "custom-ops.moe-align-block-size", "caller": "gpu-worker", "as": "decode", "input": {"num_tokens": 16, "num_experts": 8, "topk": 2, "block_size": 16, "has_expert_map": True}},
               {"interface": "custom-ops.moe-align-block-size", "caller": "gpu-worker", "as": "prefill", "input": {"num_tokens": 2048, "num_experts": 8, "topk": 2, "block_size": 64}},
               {"interface": "custom-ops.moe-align-block-size", "caller": "gpu-worker", "as": "huge", "input": {"num_tokens": 16, "num_experts": 1000, "topk": 8}},
               {"interface": "custom-ops.moe-align-block-size", "caller": "gpu-worker", "as": "scatter", "input": {"num_tokens": 16, "num_experts": 8, "topk": 2, "scatter_idx": {"dtype": "int64", "numel": 32}}},
],
     "expect": ["steps.decode.result.ok && steps.decode.result.value.kernel == 'moe_align_block_size_small_batch_expert_kernel' && steps.decode.result.value.threads == 288 && steps.decode.result.value.max_num_tokens_padded == 152",
                "steps.prefill.result.value.kernel == 'moe_align_block_size_kernel' && steps.prefill.result.value.padded_num_experts == 32",
                "!steps.huge.result.ok && steps.huge.result.error.message == 'padded_num_experts must be less than 1024'",
                "!steps.scatter.result.ok && steps.scatter.result.error.message == 'scatter_idx must be int32'",
                ]},
    {"id": "kernels-ops-moe-align-xpu-scatter", "name": "On XPU moe_align_block_size refuses a scatter_idx before reaching the op",
     "fixtures": ["tp1-llama-8b"], "config": {"vllm-target-device": "xpu"},
     "steps": [{"interface": "custom-ops.moe-align-block-size", "caller": "gpu-worker", "as": "xpu", "input": {"num_tokens": 16, "num_experts": 8, "topk": 2, "scatter_idx": {"dtype": "int32", "numel": 32}}},
               {"interface": "custom-ops.moe-align-block-size", "caller": "gpu-worker", "as": "plain", "input": {"num_tokens": 16, "num_experts": 8, "topk": 2}}],
     "expect": ["!steps.xpu.result.ok && steps.xpu.result.error.code == 'not-implemented-error' && steps.xpu.result.error.message == 'scatter_idx is not supported on XPU'",
                "steps.plain.result.ok"]},
    {"id": "kernels-ops-moe-world-mixtral-forward", "name": "MoE world end to end: Mixtral's forward on rank0 routes with topkGating and aligns in the small-batch kernel",
     "fixtures": MOEW, "state": {"platforms": {"host": {"nvml_gpu_count": 2, "device_count": 2}}},
     "steps": [{"flow": "wr-load-model", "as": "load"},
               {"flow": "wr-load-model", "as": "load1", "on": "rank1"},
               {"flow": "models-mixtral-forward", "as": "fwd", "on": "rank0", "await": False},
               {"flow": "models-mixtral-forward", "as": "fwd1", "on": "rank1"}],
     "expect": ["steps.load.result.ok && steps.load1.result.ok && steps.fwd.result.ok && steps.fwd1.result.ok",
                "trace.exists(e, e.type == 'call.end' && e.interface == 'moe-torch-bindings.topk-softmax' && e.output.kernel == 'topkGating')",
                "trace.exists(e, e.type == 'call.end' && e.interface == 'moe-torch-bindings.moe-align-block-size' && e.output.kernel == 'moe_align_block_size_small_batch_expert_kernel')"]},
    {"id": "kernels-ops-silu-and-mul-quant-host-checks", "name": "silu_and_mul_quant: FP8 out of half width; FP32 input and odd widths are refused",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "torch-bindings.silu-and-mul-quant", "caller": "gpu-worker", "as": "ok", "input": {"num_tokens": 86, "hidden_size": 1562, "dtype_bytes": 2}},
               {"interface": "torch-bindings.silu-and-mul-quant", "caller": "gpu-worker", "as": "f32", "input": {"num_tokens": 86, "hidden_size": 1562, "dtype_bytes": 4}},
               {"interface": "torch-bindings.silu-and-mul-quant", "caller": "gpu-worker", "as": "odd", "input": {"num_tokens": 86, "hidden_size": 1561, "dtype_bytes": 2}},
               {"interface": "torch-bindings.silu-and-mul-quant", "caller": "gpu-worker", "as": "bf16out", "input": {"num_tokens": 86, "hidden_size": 1562, "dtype_bytes": 2, "out_dtype": "bfloat16"}}],
     "expect": ["steps.ok.result.value.out_shape == [86, 781] && steps.ok.result.value.out_dtype == 'float8_e4m3fn'",
                "!steps.f32.result.ok && steps.f32.result.error.message == 'Input must be FP16 or BF16'",
                "!steps.odd.result.ok && steps.odd.result.error.message == 'Expected input.size(-1) % 2 == 0 to be true, but got false.'",
                "!steps.bf16out.result.ok && steps.bf16out.result.error.code == 'runtime-error'"]},
]

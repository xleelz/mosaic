"""Write skips/models-layers.json from the uncovered owned entries (JSON list parsed from the check's -v output).

Only two kinds of skip are written:
- architecture-specific code (the hardware-isolated vllm/models/<arch>/ packages and per-architecture
  modules in model_executor/models) is covered by the model registry, whose rows resolve those modules;
- platform-only ops and kernels (ROCm/AITER, XPU, CPU) for platforms other than the modeled CUDA one.
Everything else that is uncovered stays unskipped: it is genuinely not modeled and counts as such.
"""
import collections, json, sys

unc = json.load(open(sys.argv[1]))
ARCH_FILES = ("vllm/model_executor/models/bailing_moe_v3.py", "vllm/model_executor/models/deepseek_v2.py",
              "vllm/model_executor/models/qwen3_dflash2.py", "vllm/model_executor/models/cohere_compass.py",
              "vllm/model_executor/models/deepencoder.py", "vllm/model_executor/models/diffusion_gemma_sampler.py",
              "vllm/model_executor/models/gemma4.py", "vllm/model_executor/models/qwen3_vl.py",
              "vllm/model_executor/models/transformers/moe.py")
PLATFORM = [
    ("vllm/lora/ops/xpu_ops/", "platform-only: Intel XPU LoRA bgmv ops (vllm/lora/ops/xpu_ops); the modeled platform is CUDA"),
    ("vllm/model_executor/kernels/linear/mixed_precision/rdna_hybrid_w4a16.py", "platform-only: AMD RDNA W4A16 kernel (ROCm)"),
    ("vllm/model_executor/kernels/linear/mxfp4/aiter.py", "platform-only: ROCm AITER MXFP4 GEMM"),
    ("vllm/model_executor/kernels/mhc/aiter.py", "platform-only: ROCm AITER mHC ops"),
    ("vllm/model_executor/kernels/linear/mxfp8/rocm_", "platform-only: ROCm MXFP8 GEMM kernels"),
    ("vllm/model_executor/kernels/linear/scaled_mm/rocm.py", "platform-only: ROCm per-tensor scaled-mm"),
    ("vllm/model_executor/layers/fused_moe/router/bf16x3_router_gemm_rocm.py", "platform-only: ROCm bf16x3 router GEMM"),
    ("vllm/model_executor/layers/fused_moe/router/rocm_fp32_router_gemm.py", "platform-only: ROCm fp32 router GEMM"),
    ("vllm/model_executor/layers/mamba/ops/cpu/", "platform-only: CPU backend GDN attention op"),
    ("vllm/model_executor/layers/fused_moe/experts/cpu_moe.py", "platform-only: CPU backend MoE weight preparation"),
]
NAMED_PLATFORM = {
    "vllm::rocm_bf16x3_router_gemm_dispatch": "platform-only: ROCm bf16x3 router GEMM dispatch op (GateLinear tier 4)",
    "vllm::rocm_unquantized_gemm": "platform-only: ROCm skinny/unquantized GEMM op",
    "dispatch_cpu_unquantized_gemm": "platform-only: CPU backend unquantized GEMM dispatch",
}
out = []
for e in unc:
    rec = {"kind": e["kind"], "name": e["name"], "file": e["file"], "line": e["line"]}
    f = e["file"]
    if f.startswith("vllm/models/") or f in ARCH_FILES:
        pkg = "/".join(f.split("/")[:3]) if f.startswith("vllm/models/") else f
        rec["reason"] = (f"architecture-specific code of {pkg}: a model module the registry resolves "
                         "(model-registry state rows; forward modeled in depth only for Llama and Mixtral)")
        rec["covered_by"] = "component:model-registry"
    elif e["name"] in NAMED_PLATFORM:
        rec["reason"] = NAMED_PLATFORM[e["name"]]
    else:
        for pre, r in PLATFORM:
            if f.startswith(pre):
                rec["reason"] = r
                break
        else:
            continue
    out.append(rec)
json.dump(out, open(sys.argv[2], "w"), indent=1)
print(len(out), "skips;", len(unc) - len(out), "left unskipped (not modeled)")
print(collections.Counter("covered_by" in o for o in out))

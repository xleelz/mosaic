"""Op, kernel and wrapper interfaces generated from the inventory and the code.

Every torch-op entry becomes an interface of kind `kernel` on the component of
its registration file, with a latency expression of its shape class and
sources citing the registration, the host function it binds, and the
__global__ kernels that function launches. Every torch-op-wrapper entry becomes
an interface that calls the op(s) it wraps, citing the torch.ops call lines.
"""
import os
import re

from common import CODE, findline, lines, load_json, slug

mine = load_json("mine.json")
analysis = load_json("analysis.json")

# ---------------------------------------------------------------- components
BINDING_COMPONENTS = {
    "csrc/torch_bindings.cpp": ("torch-bindings", "Torch op library _C (CUDA build)",
        "The STABLE_TORCH_LIBRARY fragments of the CUDA/ROCm `_C` extension: the `_C`, `_C_cache_ops`, `_C_cuda_utils` and `_C_custom_ar` namespaces."),
    "csrc/quantization/fp4/mxfp4_experts_quant.cu": ("torch-bindings", None, None),
    "csrc/moe/torch_bindings.cpp": ("moe-torch-bindings", "Torch op library _moe_C",
        "The `_moe_C` extension: MoE routing (top-k, align, permute) and MoE GEMM ops."),
    "csrc/cpu/torch_bindings.cpp": ("cpu-torch-bindings", "Torch op library _C (CPU build)",
        "The `_C` extension built for the CPU platform (VLLM_TARGET_DEVICE=cpu): same op names as the CUDA build where they overlap, plus CPU-only ops."),
    "csrc/rocm/torch_bindings.cpp": ("rocm-torch-bindings", "Torch op library _rocm_C",
        "ROCm-only ops: skinny GEMMs, RDNA3 GPTQ GEMMs and the ROCm paged attention."),
    "csrc/rocm/quickreduce/torch_bindings.cpp": ("quickreduce-torch-bindings", "Torch op library quick reduce",
        "ROCm quick all-reduce ops, registered under CONCAT(TORCH_EXTENSION_NAME, _custom_ar)."),
    "csrc/flashkda_registration.cpp": ("flashkda-registration", "Torch op library _flashkda_C",
        "FlashKDA (Kimi delta attention) ops."),
    "vllm/_aiter_ops.py": ("aiter-ops", "ROCm AITER custom ops",
        "torch.ops.vllm.rocm_aiter_* custom ops registered by rocm_aiter_ops.register_ops_once, wrapping the aiter library."),
    "vllm/_xpu_ops.py": ("xpu-ops", "XPU custom ops",
        "torch.ops.vllm.xpu_* custom ops registered by xpu_ops.register_ops_once, wrapping vllm-xpu-kernels."),
    "vllm/_custom_ops.py": ("custom-ops", None, None),
    "vllm/utils/flashinfer.py": ("flashinfer", "FlashInfer custom ops",
        "torch.ops.vllm.* custom ops in vllm/utils/flashinfer.py that wrap FlashInfer GEMM, quantize and concat kernels."),
    "vllm/compilation/passes/fusion/allreduce_rms_fusion.py": ("allreduce-rms-fusion", "AllReduce+RMSNorm fusion module",
        "Fusion pass module; registers the FlashInfer TRT-LLM fused all-reduce+norm op it rewrites patterns into."),
    "vllm/compilation/passes/fusion/mla_rope_kvcache_cat_fusion.py": ("mla-rope-kvcache-cat-fusion", "MLA RoPE+KV-cache fusion module",
        "Fusion pass module; registers the fused MLA rope + KV cache update op."),
    "vllm/compilation/passes/fusion/qk_norm_rope_kvcache_fusion.py": ("qk-norm-rope-kvcache-fusion", "QK-norm+RoPE+KV-cache fusion module",
        "Fusion pass module; registers the fused QK-norm, rope and KV cache update ops."),
    "vllm/compilation/passes/fusion/rms_quant_fusion.py": ("rms-quant-fusion", "RMSNorm+quant fusion module",
        "Fusion pass module; registers the FlashInfer fused add+RMSNorm+NVFP4 quant op."),
    "vllm/compilation/passes/fusion/rope_kvcache_fusion.py": ("rope-kvcache-fusion", "RoPE+KV-cache fusion module",
        "Fusion pass module; registers the fused rope + KV cache update op."),
}

WRAPPER_COMPONENTS = {
    "vllm/_custom_ops.py": "custom-ops",
    "vllm/_xpu_ops.py": "xpu-ops",
    "vllm/kernels/helion/ops/silu_mul_fp8.py": "silu-mul-fp8",
    "vllm/kernels/vllm_c.py": "vllm-c",
    "vllm/utils/cpu_triton_utils.py": "cpu-triton-utils",
    "vllm/utils/torch_utils.py": "torch-utils",
}

# ---------------------------------------------------------------- shape classes
SCHEMAS = {
    "KernelsOpsTokenShape": {
        "summary": "Token-major activation shape: elementwise, norm, activation, quantization, rope and cache-write kernels.",
        "schema": {"type": "object", "properties": {
            "num_tokens": {"type": "integer", "minimum": 0, "examples": [16]},
            "hidden_size": {"type": "integer", "minimum": 1, "examples": [4096]},
            "dtype_bytes": {"type": "integer", "enum": [1, 2, 4], "examples": [2]},
        }},
    },
    "KernelsOpsGemmShape": {
        "summary": "GEMM shape: [m, k] x [k, n]; dtype_bytes is the weight element size (1 for FP8/INT8, 2 for BF16).",
        "schema": {"type": "object", "properties": {
            "m": {"type": "integer", "minimum": 0, "examples": [16]},
            "n": {"type": "integer", "minimum": 1, "examples": [4096]},
            "k": {"type": "integer", "minimum": 1, "examples": [4096]},
            "dtype_bytes": {"type": "integer", "enum": [1, 2, 4], "examples": [2]},
        }},
    },
    "KernelsOpsMoeShape": {
        "summary": "Mixture-of-experts shape: routed tokens, experts, top-k and the expert GEMM [k -> n].",
        "schema": {"type": "object", "properties": {
            "num_tokens": {"type": "integer", "minimum": 0, "examples": [16]},
            "num_experts": {"type": "integer", "minimum": 1, "examples": [8]},
            "topk": {"type": "integer", "minimum": 1, "examples": [2]},
            "n": {"type": "integer", "minimum": 1, "examples": [14336]},
            "k": {"type": "integer", "minimum": 1, "examples": [4096]},
            "dtype_bytes": {"type": "integer", "enum": [1, 2, 4], "examples": [2]},
        }},
    },
    "KernelsOpsAttentionShape": {
        "summary": "Attention shape over a paged KV cache: sequences, context length and heads.",
        "schema": {"type": "object", "properties": {
            "num_seqs": {"type": "integer", "minimum": 0, "examples": [16]},
            "seq_len": {"type": "integer", "minimum": 0, "examples": [1024]},
            "num_heads": {"type": "integer", "minimum": 1, "examples": [32]},
            "num_kv_heads": {"type": "integer", "minimum": 1, "examples": [8]},
            "head_dim": {"type": "integer", "minimum": 1, "examples": [128]},
            "dtype_bytes": {"type": "integer", "enum": [1, 2, 4], "examples": [2]},
        }},
    },
    "KernelsOpsBlockCopyShape": {
        "summary": "KV block copy between devices: number of blocks and bytes per block.",
        "schema": {"type": "object", "properties": {
            "num_blocks": {"type": "integer", "minimum": 0, "examples": [4]},
            "block_bytes": {"type": "integer", "minimum": 1, "examples": [2097152]},
        }},
    },
    "KernelsOpsCollectiveShape": {
        "summary": "One rank's side of a collective: the bytes it contributes and the group size.",
        "schema": {"type": "object", "properties": {
            "num_bytes": {"type": "integer", "minimum": 0, "examples": [131072]},
            "world_size": {"type": "integer", "minimum": 1, "examples": [4]},
        }},
    },
    "KernelsOpsQuery": {
        "summary": "A capability query or setup call with no tensor work.",
        "schema": {"type": "object", "properties": {
            "device": {"type": "integer", "minimum": 0, "examples": [0]},
        }},
    },
}

LAUNCH = "double(config['kernel-launch-overhead-us'])"
BW = "double(config['gpu-hbm-bandwidth-gbps'])"
TF = "double(config['gpu-bf16-dense-tflops'])"


def us_to_ms(expr):
    return f"= ({LAUNCH} + {expr}) / 1000.0"


LATENCY = {
    # read the input (and a residual or weight row) and write the output: ~3 passes over [T, H]
    "token": us_to_ms(f"3.0 * double(input.num_tokens) * double(input.hidden_size) * double(input.dtype_bytes) / ({BW} * 1000.0)"),
    # roofline: the larger of tensor-core time and weight-read time
    "gemm": us_to_ms(
        f"math.greatest(2.0 * double(input.m) * double(input.n) * double(input.k) / ({TF} * (input.dtype_bytes == 1 ? 2.0 : 1.0) * 1000000.0), "
        f"double(input.n) * double(input.k) * double(input.dtype_bytes) / ({BW} * 1000.0))"),
    # expert GEMM: flops of every routed token copy; weights of every touched expert
    "moe": us_to_ms(
        f"math.greatest(2.0 * double(input.num_tokens) * double(input.topk) * double(input.n) * double(input.k) / ({TF} * (input.dtype_bytes == 1 ? 2.0 : 1.0) * 1000000.0), "
        f"double(math.least(input.num_experts, input.num_tokens * input.topk)) * double(input.n) * double(input.k) * double(input.dtype_bytes) / ({BW} * 1000.0))"),
    # routing: one pass over the [T, E] router logits plus the [T, topk] ids
    "routing": us_to_ms(f"2.0 * double(input.num_tokens) * double(input.num_experts + input.topk) * 4.0 / ({BW} * 1000.0)"),
    # attention over the paged KV cache: read K and V of every context token once
    "attention": us_to_ms(
        f"2.0 * double(input.num_seqs) * double(input.seq_len) * double(input.num_kv_heads) * double(input.head_dim) * double(input.dtype_bytes) / ({BW} * 1000.0)"),
    # block copies cross PCIe (GPU<->CPU swap)
    "blockcopy": us_to_ms("double(input.num_blocks) * double(input.block_bytes) / (double(config['gpu-pcie-bandwidth-gbps']) * 1000.0)"),
    # ring all-reduce volume 2 (w-1)/w per rank over NVLink
    "collective": us_to_ms(
        "2.0 * double(input.world_size - 1) / double(input.world_size) * double(input.num_bytes) / (double(config['gpu-nvlink-bandwidth-gbps']) * 1000.0)"),
    # weight re-layout at load time: one read and one write of the [k, n] weight
    "weightprep": us_to_ms(f"2.0 * double(input.n) * double(input.k) * double(input.dtype_bytes) / ({BW} * 1000.0)"),
    "query": 0,
}

CLASS_SCHEMA = {
    "token": "KernelsOpsTokenShape", "gemm": "KernelsOpsGemmShape", "moe": "KernelsOpsMoeShape",
    "routing": "KernelsOpsMoeShape", "attention": "KernelsOpsAttentionShape",
    "blockcopy": "KernelsOpsBlockCopyShape", "collective": "KernelsOpsCollectiveShape",
    "weightprep": "KernelsOpsGemmShape", "query": "KernelsOpsQuery",
}

CLASS_DESC = {
    "token": "memory-bound over [num_tokens, hidden_size]",
    "gemm": "GEMM roofline (tensor-core time vs weight read)",
    "moe": "expert GEMM roofline over routed tokens",
    "routing": "memory-bound over the [num_tokens, num_experts] router logits",
    "attention": "memory-bound read of the K/V context",
    "blockcopy": "PCIe-bound block copy",
    "collective": "NVLink-bound ring volume",
    "weightprep": "memory-bound weight re-layout (load time)",
    "query": "no device work (host query or setup); 0 ms",
}

RULES = [
    ("query", r"(supported|supports|^is_|has_isa|has_amx|workspace_size$|^meta_size|get_device_attribute|get_max_shared|workspace|qr_max_size|dispose|^init_|^release_|^join_shm|qr_destroy|get_handle|open_handles|register_buffer|register_graph|get_graph_buffer|allocate_shared|open_mem_handle|free_shared|^create_onednn|weak_ref|view_from_cpu|machete_supported_schedules|get_scheduler_metadata|cpu_memory_env|^get_workspace)"),
    ("collective", r"(all_reduce|allreduce|reduce_scatter|all_gather|^shm_|send_tensor|recv_tensor)"),
    ("blockcopy", r"(swap_blocks)"),
    ("weightprep", r"(repack|prepack|weight_pack$|packed_scale_zp|^convert_weight_packed$|pack_scale|encode_and_reorder|preprocess|convert_scale|gptq_shuffle|linear_prepack)"),
    ("moe", r"(moe.*(mm|gemm)|fused_moe|fused_experts|experts_cpu|moe_mm|group_mm|moe_wna16|asm_moe|dynamic_4bit_int_moe|cpu_fused_moe)"),
    ("gemm", r"(mm|gemm|matmul|linear|bmm|llmm|wvsplit|router_gemm)"),
    ("attention", r"(attention|attn_with|mla_decode|mla_extend|decode_attention|extend_attention|paged_attention|mqa_logits|flash_mla|sparse_attn|attn_wrapper|^fwd$)"),
    ("routing", r"(topk|top_k|align_block|moe_sum|moe_permute|moe_unpermute|prepare_scatter|shuffle_rows|grouped_topk)"),
]


CLASS_OVERRIDES = {
    "_C::get_cutlass_moe_mm_data": "routing",
    "_C::get_cutlass_moe_mm_problem_sizes_from_expert_offsets": "routing",
    "_C::get_cutlass_batched_moe_mm_data": "routing",
    "_C::fused_kimi_k3_mla_decode_q_concat_kv_cache_insert": "token",
    "_C::fused_kimi_k3_mla_decode_q_concat_kv_cache_fp8_insert": "token",
    "_C::fused_kimi_k3_mla_decode_q_concat_ds_mla_insert": "token",
    "_C::top_k_per_row_prefill": "token",
    "_C::top_k_per_row_decode": "token",
    "_C::persistent_topk": "token",
    "_C::cooperative_topk": "token",
    "_C::topk_transform_512_cpu": "token",
    "vllm::xpu_topk_topp_sampler": "token",
    "_C::weight_packed_linear": "gemm",
    "_C::per_token_group_fp8_quant_packed": "token",
    "_C::moe_align_block_size": "routing",
}


def classify(opname):
    if opname in CLASS_OVERRIDES:
        return CLASS_OVERRIDES[opname]
    n = opname.split("::")[-1].lower()
    for cls, pat in RULES:
        if re.search(pat, n):
            return cls
    return "token"


# kernel -> op names, fixing or completing the automatic mapping
KERNEL_OVERRIDES = {
    ("csrc/cache_kernels.cu", "cp_gather_cache_page"): ["_C_cache_ops::cp_gather_cache"],
    ("csrc/concat_mla_q.cuh", "ConcatMLAQKernel"): ["_C_cache_ops::concat_mla_q"],
    ("csrc/cooperative_topk.cuh", "cooperative_topk_cs2"): ["_C::cooperative_topk"],
    ("csrc/cooperative_topk.cuh", "cooperative_topk_cs4"): ["_C::cooperative_topk"],
    ("csrc/cooperative_topk.cuh", "cooperative_topk_cs8"): ["_C::cooperative_topk"],
    ("csrc/cooperative_topk.cuh", "cooperative_topk_cs16"): ["_C::cooperative_topk"],
    ("csrc/dsv3_fused_a_gemm.cu", "fused_a_gemm_kernel"): ["_C::dsv3_fused_a_gemm"],
    ("csrc/fp32_router_gemm.cu", "fp32_router_gemm_kernel"): ["_C::fp32_router_gemm"],
    ("csrc/fused_deepseek_v4_qnorm_rope_kv_insert_kernel.cu", "fusedDeepseekV4QNormRopeKVRopeQuantInsertKernel"): ["_C::fused_deepseek_v4_qnorm_rope_kv_rope_quant_insert", "_C::fused_deepseek_v4_kv_rope_insert"],
    ("csrc/fused_deepseek_v4_qnorm_rope_kv_insert_kernel.cu", "fusedDeepseekV4QNormRopeKVRopeQuantInsertKernelReducedGrid"): ["_C::fused_deepseek_v4_qnorm_rope_kv_rope_quant_insert"],
    ("csrc/fused_deepseek_v4_qnorm_rope_kv_insert_kernel.cu", "fusedDeepseekV4FullCacheKernel"): ["_C::fused_deepseek_v4_qnorm_rope_kv_rope_full_cache_bf16_insert", "_C::fused_deepseek_v4_qnorm_rope_kv_rope_full_cache_fp8_insert"],
    ("csrc/fused_minimax_m3_qknorm_rope_kv_insert_kernel.cu", "fusedMiniMaxM3QNormRopeKVInsertKernel"): ["_C::fused_minimax_m3_qknorm_rope_kv_insert"],
    ("csrc/fused_qknorm_rope_kernel.cu", "fusedQKNormRopeKernel"): ["_C::fused_qk_norm_rope"],
    ("csrc/fused_qknorm_rope_kernel.cu", "fusedQKNormRopeKernelNTokenHeads"): ["_C::fused_qk_norm_rope"],
    ("csrc/kimi_k3/attn_res_kernel.cu", "attn_res_fwd_online_v2_kernel"): ["_C::kimi_k3_attn_res"],
    ("csrc/kimi_k3/fused_kda_chunk_kernel_rocm.cu", "kda_group_scan"): ["_C::fused_kda_chunk"],
    ("csrc/kimi_k3/fused_kda_decode_kernel.cu", "kda_decode_fusion_many_heads_kernel"): ["_C::fused_kda_decode"],
    ("csrc/kimi_k3/fused_kda_decode_kernel_rocm.cu", "kda_decode_fusion_kernel"): ["_C::fused_kda_decode"],
    ("csrc/moe/grouped_topk_kernels.cu", "grouped_topk_fused_kernel"): ["_moe_C::grouped_topk"],
    ("csrc/moe/grouped_topk_kernels.cu", "grouped_topk_fused_small_expert_count_kernel"): ["_moe_C::grouped_topk"],
    ("csrc/moe/grouped_topk_kernels.cu", "single_group_topk_block_kernel"): ["_moe_C::grouped_topk"],
    ("csrc/moe/grouped_topk_kernels.cu", "single_group_topk_warp_kernel"): ["_moe_C::grouped_topk"],
    ("csrc/moe/marlin_moe_wna16/kernel.h", "Marlin"): ["_moe_C::moe_wna16_marlin_gemm"],
    ("csrc/moe/marlin_moe_wna16/marlin_template.h", "Marlin"): ["_moe_C::moe_wna16_marlin_gemm"],
    ("csrc/moe/moe_align_sum_kernels.cu", "moe_sum_vec_kernel"): ["_moe_C::moe_sum"],
    ("csrc/moe/moe_align_sum_kernels.cu", "moe_sum_vec_dynamic_kernel"): ["_moe_C::moe_sum"],
    ("csrc/moe/moe_align_sum_kernels.cu", "moe_sum_scalar_kernel"): ["_moe_C::moe_sum"],
    ("csrc/moe/topk_softmax_kernels.cu", "topkGating"): ["_moe_C::topk_softmax", "_moe_C::topk_sigmoid"],
    ("csrc/moe/topk_softplus_sqrt_kernels.cu", "topkGatingSoftplusSqrt"): ["_moe_C::topk_softplus_sqrt"],
    ("csrc/persistent_topk.cuh", "persistent_topk_kernel"): ["_C::persistent_topk"],
    ("csrc/persistent_topk.cuh", "FilteredTopKUnifiedKernel"): ["_C::persistent_topk"],
    ("csrc/sampled_topk.cuh", "sampled_topk_kernel"): ["_C::persistent_topk"],
    ("csrc/quantization/fp4/nvfp4_quant_kernels.cu", "cvt_fp16_to_fp4"): ["_C::scaled_fp4_quant", "_C::scaled_fp4_quant.out"],
    ("csrc/quantization/fp4/nvfp4_quant_kernels.cu", "cvt_fp16_to_fp4_sf_major"): ["_C::scaled_fp4_quant", "_C::scaled_fp4_quant.out"],
    ("csrc/quantization/gptq/q_gemm.cu", "gemm_half_q_half_gptq_4bit_kernel"): ["_C::gptq_gemm"],
    ("csrc/quantization/gptq/q_gemm.cu", "gemm_half_q_half_gptq_2bit_kernel"): ["_C::gptq_gemm"],
    ("csrc/quantization/gptq/q_gemm.cu", "gemm_half_q_half_gptq_3bit_kernel"): ["_C::gptq_gemm"],
    ("csrc/quantization/gptq/q_gemm.cu", "gemm_half_q_half_gptq_8bit_kernel"): ["_C::gptq_gemm"],
    ("csrc/quantization/machete/machete_prepack_kernel.cuh", "prepack_B_kernel"): ["_C::machete_prepack_B"],
    ("csrc/quantization/marlin/kernel.h", "Marlin"): ["_C::marlin_gemm"],
    ("csrc/quantization/marlin/marlin_template.h", "Marlin"): ["_C::marlin_gemm"],
    ("csrc/quantization/w8a8/fp8/per_token_group_quant.cu", "per_token_group_quant_8bit_register_kernel"): ["_C::per_token_group_fp8_quant"],
    ("csrc/quantization/w8a8/cutlass/moe/get_group_starts.cuh", "get_group_gemm_starts"): ["_C::cutlass_moe_mm"],
    ("csrc/quantization/cutlass_w4a8/get_group_starts.cuh", "get_group_gemm_starts"): ["_C::cutlass_w4a8_moe_mm"],
    ("csrc/rocm/attention.cu", "paged_attention_ll4mi_QKV_mfma16_kernel"): ["_rocm_C::paged_attention"],
    ("csrc/rocm/attention.cu", "paged_attention_ll4mi_QKV_mfma4_kernel"): ["_rocm_C::paged_attention"],
    ("csrc/rocm/attention.cu", "paged_attention_ll4mi_reduce_kernel"): ["_rocm_C::paged_attention"],
    ("csrc/rocm/q_gemm_rdna3_wmma.cu", "gemm_q4_wmma_kernel_16x16_1w"): ["_rocm_C::gptq_gemm_rdna3_wmma"],
    ("csrc/rocm/q_gemm_rdna3_wmma.cu", "gemm_q4_wmma_kernel_32x16_2w"): ["_rocm_C::gptq_gemm_rdna3_wmma"],
    ("csrc/rocm/quickreduce/quick_reduce.h", "allreduce_prototype_twoshot"): ["_rocm_C_custom_ar::qr_all_reduce"],
    ("csrc/rocm/skinny_gemms.cu", "wvSplitK_hf_sml_"): ["_rocm_C::wvSplitK"],
    ("csrc/rocm/skinny_gemms.cu", "wvSplitK_hf_"): ["_rocm_C::wvSplitK"],
    ("csrc/rocm/skinny_gemms.cu", "wvSplitK_hf_big_"): ["_rocm_C::wvSplitK"],
    ("csrc/rocm/skinny_gemms.cu", "wvSplitKrc_"): ["_rocm_C::wvSplitKrc"],
    ("csrc/rocm/skinny_gemms.cu", "wvSplitKQ_hf_sml_"): ["_rocm_C::wvSplitKQ"],
    ("csrc/rocm/skinny_gemms.cu", "wvSplitKQ_hf_"): ["_rocm_C::wvSplitKQ"],
    ("csrc/rocm/skinny_gemms_int4.cu", "wvSplitK_int4_hf_sml_"): ["_rocm_C::wvSplitK_int4_g"],
    ("csrc/rocm/skinny_gemms_int4.cu", "wvSplitK_int4_hf_"): ["_rocm_C::wvSplitK_int4_g"],
    ("csrc/vocab_parallel_embedding_kernels.cu", "vocab_parallel_embedding_kernel"): ["_C::vocab_parallel_embedding"],
    ("csrc/quantization/fp4/nvfp4_experts_quant.cu", "cvt_fp16_to_fp4"): ["_C::scaled_fp4_experts_quant", "_C::silu_and_mul_scaled_fp4_experts_quant"],
    ("csrc/activation_kernels.cu", "act_and_mul_kernel"): ["_C::silu_and_mul", "_C::mul_and_silu", "_C::silu_and_mul_with_clamp", "_C::gelu_and_mul", "_C::gelu_tanh_and_mul"],
    ("csrc/activation_kernels.cu", "activation_kernel"): ["_C::gelu_new", "_C::gelu_fast", "_C::gelu_quick", "_C::relu_squared"],
}


def op_key_files():
    """op name (ns::name) -> list of (entry) for torch-op entries."""
    out = {}
    for e in mine:
        if e["kind"] == "torch-op":
            out.setdefault(e["name"], []).append(e)
    return out


OPS_BY_NAME = op_key_files()


def is_cpu_binding(f):
    return f.startswith("csrc/cpu/")


def is_rocm_binding(f):
    return f.startswith("csrc/rocm/")


def kernel_map():
    """(op name, binding file) -> [kernel entries]."""
    res = {}
    for k in analysis["kernels"]:
        key = (k["file"], k["name"])
        if key in KERNEL_OVERRIDES:
            names = KERNEL_OVERRIDES[key]
            opkeys = []
            for nm in names:
                for e in OPS_BY_NAME.get(nm, []):
                    opkeys.append(e["name"] + "@" + e["file"])
        else:
            opkeys = k["ops"]
        kept = []
        for ok in opkeys:
            nm, f = ok.split("@")
            if is_cpu_binding(f):
                continue
            if k["file"].startswith("csrc/rocm/") != is_rocm_binding(f):
                continue
            kept.append(ok)
        if not kept:
            raise SystemExit(f"kernel {key} maps to no op")
        for ok in sorted(set(kept)):
            res.setdefault(ok, []).append(k)
    return res


KMAP = kernel_map()


def impl_sources(opkey, binding_file):
    """Citations of the host functions an op's impl registrations bind."""
    defs = analysis["ops"].get(opkey, {})
    out = []
    cpu = is_cpu_binding(binding_file)
    rocm = is_rocm_binding(binding_file)
    for key, cands in defs.items():
        good = []
        for f, ln in cands:
            if f in ("csrc/ops.h", "csrc/torch_bindings.cpp", "csrc/cpu/torch_bindings.cpp", "csrc/moe/torch_bindings.cpp", "csrc/rocm/torch_bindings.cpp"):
                continue
            if cpu != f.startswith("csrc/cpu/"):
                continue
            if not rocm and f.startswith("csrc/rocm/"):
                continue
            good.append(f"{f}:{ln}")
        if good:
            out.append(good[0])
    return sorted(set(out))


# ---------------------------------------------------------------- op interfaces
def op_component(e):
    return BINDING_COMPONENTS[e["file"]][0]


def op_iface_name(e):
    nm = e["name"].split("::", 1)[1]
    return slug(nm)


def schema_short(detail):
    return detail.split("; impl ")[0].strip() if detail else ""


def registration_source(e):
    f, ln = e["file"], e["line"]
    end = e.get("end_line")
    if f.endswith(".cpp") or f.endswith(".cu"):
        # the ops.def( ... ) statement: cite the def line through its closing ');'
        ls = lines(f)
        j = ln
        while j <= len(ls) and ");" not in ls[j - 1] and j < ln + 14:
            j += 1
        if j > ln:
            return f"{f}:{ln}-{j}"
        return f"{f}:{ln}"
    if end and end > ln:
        return f"{f}:{ln}-{end}"
    # python direct registration: cite the direct_register_custom_op( ... ) call
    ls = lines(f)
    j = ln
    while j <= len(ls) and not ls[j - 1].rstrip().endswith(")") and j < ln + 10:
        j += 1
    return f"{f}:{ln}-{j}" if j > ln else f"{f}:{ln}"


def build_op_interfaces():
    ifaces = {}
    for e in mine:
        if e["kind"] != "torch-op":
            continue
        comp = op_component(e)
        name = op_iface_name(e)
        iid = f"{comp}.{name}"
        opkey = e["name"] + "@" + e["file"]
        cls = classify(e["name"])
        sources = [registration_source(e)]
        impls = impl_sources(opkey, e["file"])
        sources += impls[:2]
        kernels = KMAP.get(opkey, [])
        for k in kernels:
            sources.append(f"{k['file']}:{k['line']}")
        detail = e.get("detail", "")
        desc = []
        if e["via"] == "torch-library":
            desc.append(f"Registered as `{e['name']}`: `{schema_short(detail)[:300]}`.")
            if "; impl " in detail:
                desc.append("Dispatch: " + detail.split("; impl ", 1)[1][:200] + ".")
        else:
            desc.append(f"Registered as the custom op `{e['name']}` ({detail}).")
        if kernels:
            desc.append("Launches " + ", ".join(f"`{k['name']}` ({k['file']}:{k['line']})" for k in kernels) + ".")
        desc.append("Latency model: " + CLASS_DESC[cls] + "; the kernel body is not simulated.")
        if iid in ifaces:
            raise SystemExit(f"duplicate op interface {iid}")
        ifaces[iid] = {
            "component": comp, "name": name, "kind": "kernel",
            "summary": f"torch op {e['name']}",
            "description": " ".join(desc),
            "sources": sources,
            "attributes": {"op": e["name"], "latency_model": cls,
                           "kernels": [k["name"] for k in kernels]},
            "request": CLASS_SCHEMA[cls],
            "latency_ms": LATENCY[cls],
            "_entry": e, "_class": cls,
        }
    return ifaces


OP_IFACES = build_op_interfaces()

# op name -> interface ids (CUDA build first)
OPNAME_TO_IFACES = {}
for iid, f in OP_IFACES.items():
    OPNAME_TO_IFACES.setdefault(f["attributes"]["op"], []).append(iid)

# ---------------------------------------------------------------- external / boundary ops
EXTERNAL = {
    # torch.ops namespace -> external component (no code in the repo; sources cite the call site)
    "_xpu_C": "vllm-xpu-kernels",
    "_qutlass_C": "qutlass",
}
XPU_C_OPS = {"gemma_rms_norm", "fused_add_gemma_rms_norm", "layer_norm", "fused_add_layer_norm",
             "nemotron_layer_norm", "fused_add_nemotron_layer_norm", "per_token_group_quant_mxfp4",
             "get_xpu_view_from_cpu_tensor"}
DISTRIBUTED_OPS = {"custom_all_gather", "custom_reduce_scatter", "mnnvl_lamport_all_gather",
                   "mnnvl_lamport_reduce_scatter", "mnnvl_multimem_reduce_scatter"}

EXTRA_IFACES = {}   # external and boundary op interfaces created on demand


def resolve_target(call, wrapper_file, call_line):
    """torch.ops.<ns>.<op> -> (interface id or dynamic spec)."""
    ns, op = call.replace("torch.ops.", "").split(".", 1)
    if ns in EXTERNAL or (ns == "_C" and op in XPU_C_OPS and wrapper_file in ("vllm/_xpu_ops.py", "vllm/utils/torch_utils.py")):
        comp = EXTERNAL.get(ns, "vllm-xpu-kernels")
        iid = f"{comp}.{slug(op)}"
        if iid not in EXTRA_IFACES:
            cls = classify(op)
            EXTRA_IFACES[iid] = {
                "component": comp, "name": slug(op), "kind": "kernel",
                "summary": f"external op torch.ops.{ns}.{op}",
                "description": f"Provided by the {comp} package, not by this repository; cited at its call site. Latency model: {CLASS_DESC[cls]}.",
                "sources": [f"{wrapper_file}:{call_line}"],
                "attributes": {"op": f"{ns}::{op}", "external": True, "latency_model": cls},
                "request": CLASS_SCHEMA[cls], "latency_ms": LATENCY[cls],
            }
        return iid
    if ns == "_C_custom_ar" and op in DISTRIBUTED_OPS:
        iid = f"custom-all-gather-reduce-scatter-ops.{slug(op)}"
        if iid not in EXTRA_IFACES:
            EXTRA_IFACES[iid] = {
                "component": "custom-all-gather-reduce-scatter-ops", "name": slug(op), "kind": "kernel",
                "summary": f"torch op _C_custom_ar::{op} (owned by distributed)",
                "sources": [f"csrc/custom_all_gather_reduce_scatter_ops.cpp:{findline('csrc/custom_all_gather_reduce_scatter_ops.cpp', op + '(')}"],
                "attributes": {"boundary": True, "owner": "distributed", "op": f"_C_custom_ar::{op}"},
                # contract copied from the owner's fragment (schema DistKernelLaunch, inlined)
                "kind": "kernel",
                "request": {"type": "object", "required": ["bytes", "world_size"], "properties": {
                    "bytes": {"type": "integer", "examples": [1048576]}, "world_size": {"type": "integer", "examples": [4]},
                    "num_collectives": {"type": "integer", "default": 1}}},
                "response": {"type": "object", "properties": {"algorithm": {"type": "string"}}},
                "errors": [{"code": "runtime-error", "status": 0, "retryable": False}],
            }
        return iid
    if ns == "_C_custom_ar" and op.startswith("qr_") or op == "init_custom_qr":
        return f"quickreduce-torch-bindings.{slug(op)}"
    key = {"_moe_C": "_moe_C", "_rocm_C": "_rocm_C", "_C_cache_ops": "_C_cache_ops",
           "_C_cuda_utils": "_C_cuda_utils", "_C_custom_ar": "_C_custom_ar", "_C": "_C"}[ns]
    cands = OPNAME_TO_IFACES.get(f"{key}::{op}", [])
    cuda = [c for c in cands if not c.startswith("cpu-torch-bindings.")]
    cpu = [c for c in cands if c.startswith("cpu-torch-bindings.")]
    if cuda and cpu:
        return {"dynamic": True, "cuda": cuda[0], "cpu": cpu[0]}
    if cuda:
        return cuda[0]
    if cpu:
        return cpu[0]
    raise SystemExit(f"cannot resolve {call} from {wrapper_file}:{call_line}")


def wrapper_name(e):
    return slug(e["name"].lstrip("_"))


def call_lines(e):
    """(call, line) for each torch.ops.* call in the wrapper's span."""
    out = []
    f, a, b = e["file"], e["line"], e.get("end_line") or e["line"]
    ls = lines(f)
    calls = [c.strip() for c in e["detail"].split(",")]
    for c in calls:
        hit = None
        for i in range(a - 1, min(b, len(ls))):
            if re.search(re.escape(c) + r"\b", ls[i]):
                hit = i + 1
                break
        if hit is None:
            # the call may wrap: `torch.ops._C.x(` split over lines
            short = c.split(".")[-1]
            for i in range(a - 1, min(b, len(ls))):
                if short + "(" in ls[i] or (short in ls[i] and "torch.ops" in ls[i - 1]):
                    hit = i + 1
                    break
        if hit is None:
            raise SystemExit(f"call {c} not found in {f}:{a}-{b}")
        out.append((c, hit))
    return out


def call_step(target, call, line, wrapper_file):
    step = {"title": f"Call {call}", "source": f"{wrapper_file}:{line}"}
    if isinstance(target, dict):
        step["detail"] = ("torch.ops._C resolves to whichever _C extension was built: "
                          "csrc/torch_bindings.cpp for CUDA/ROCm, csrc/cpu/torch_bindings.cpp for the CPU build.")
        step["call"] = (f"= (config['vllm-target-device'] == 'cpu' ? '{target['cpu']}' : '{target['cuda']}')")
        step["targets"] = [target["cuda"], target["cpu"]]
    else:
        step["call"] = target
    if isinstance(target, str) and target.startswith("custom-all-gather-reduce-scatter-ops."):
        step["input"] = {"bytes": "= input.num_bytes", "world_size": "= input.world_size"}
        return step
    step["input"] = "= input"
    step["fill"] = True
    return step


def build_wrapper_interfaces():
    ifaces = {}
    for e in mine:
        if e["kind"] != "torch-op-wrapper":
            continue
        comp = WRAPPER_COMPONENTS[e["file"]]
        name = wrapper_name(e)
        iid = f"{comp}.{name}"
        cl = call_lines(e)
        targets = [resolve_target(c, e["file"], ln) for c, ln in cl]
        first = targets[0]
        tid = first["cuda"] if isinstance(first, dict) else first
        tdef = OP_IFACES.get(tid) or EXTRA_IFACES.get(tid)
        req = tdef["request"] if tdef else "KernelsOpsTokenShape"
        if tid.startswith("custom-all-gather-reduce-scatter-ops."):
            req = "KernelsOpsCollectiveShape"
        behavior = [call_step(t, c, ln, e["file"]) for t, (c, ln) in zip(targets, cl)]
        if len(behavior) > 1:
            behavior = None  # multi-op wrappers are written by hand (hand.py)
        if iid in ifaces:
            raise SystemExit(f"duplicate wrapper {iid}")
        ifaces[iid] = {
            "component": comp, "name": name, "kind": "function",
            "summary": f"Python wrapper {e['name']} -> {e['detail']}",
            "sources": [f"{e['file']}:{e['line']}-{e.get('end_line') or e['line']}"],
            "request": req,
            "latency_ms": 0,
            "behavior": behavior,
            "_entry": e, "_targets": targets, "_calls": cl,
        }
    return ifaces


WRAPPER_IFACES = build_wrapper_interfaces()


def entries(kind):
    return [e for e in mine if e["kind"] == kind]

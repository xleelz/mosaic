"""Core attention entities: schemas, configs, boundary stubs, backend selection, FlashAttention,
Triton attention, merge, DCP, ViT wrappers, the MLA prefill gate and the CPU MLA cache write."""
from lib import (C, Cfn, Cinv, Cln, LAT_ATTN, LAT_META, SHAPE, cls, fn, helper, inv, kernel,
                 launch, ln, mark, note, op_kernel)

FA = "vllm/v1/attention/backends/flash_attn.py"
FAU = "vllm/v1/attention/backends/fa_utils.py"
FAI = "vllm/vllm_flash_attn/flash_attn_interface.py"
SEL = "vllm/v1/attention/selector.py"
BK = "vllm/v1/attention/backend.py"
TA = "vllm/v1/attention/backends/triton_attn.py"
TUA = "vllm/v1/attention/ops/triton_unified_attention.py"
TAH = "vllm/v1/attention/ops/triton_attention_helpers.py"
TRC = "vllm/v1/attention/ops/triton_reshape_and_cache_flash.py"
TPA = "vllm/v1/attention/ops/triton_prefill_attention.py"
MAS = "vllm/v1/attention/ops/merge_attn_states.py"
TMAS = "vllm/v1/attention/ops/triton_merge_attn_states.py"
MASCU = "csrc/attention/merge_attn_states.cu"
I4 = "vllm/v1/attention/ops/int4_per_token_head.py"
DCP = "vllm/v1/attention/ops/dcp.py"
A2A = "csrc/attention/dcp_utils/dcp_direct_a2a_lse_reduce.cu"
QG = "csrc/attention/dcp_utils/dcp_direct_q_gather.cu"
KVG = "csrc/attention/dcp_utils/dcp_direct_kv_gather.cu"
DCOM = "csrc/attention/dcp_utils/dcp_direct_common.cuh"
VIT = "vllm/v1/attention/ops/vit_attn_wrappers.py"
MLAP = "vllm/v1/attention/backends/mla/prefill/base.py"
MLAPFA = "vllm/v1/attention/backends/mla/prefill/flash_attn.py"
CPUMLA = "vllm/v1/attention/backends/mla/cpu_mla.py"
CPUA = "vllm/v1/attention/backends/cpu_attn.py"
CFG_ATT = "vllm/config/attention.py"
ARGS = "vllm/engine/arg_utils.py"

I = lambda t: {"type": "integer", "default": t}
B = lambda t: {"type": "boolean", "default": t}
S = lambda t, **kw: {"type": "string", "default": t, **kw}
KV_DTYPES = ["auto", "float16", "bfloat16", "fp8", "fp8_e4m3", "fp8_e5m2", "fp8_inc", "fp8_ds_mla",
             "nvfp4_ds_mla", "turboquant_k8v4", "turboquant_4bit_nc", "turboquant_k3v4_nc",
             "turboquant_3bit_nc", "ultraquant_4bit", "int4_per_token_head", "int8_per_token_head",
             "fp8_per_token_head", "nvfp4", "nvfp4_4over6"]
# is_quantized_kv_cache (kv_cache_interface.py:91-116): every get_kv_quant_mode result but NONE.
QUANT = ("(input.kv_cache_dtype.startsWith('fp8') || input.kv_cache_dtype.endsWith('per_token_head')"
         " || input.kv_cache_dtype.startsWith('nvfp4') || input.kv_cache_dtype.startsWith('turboquant_') || input.kv_cache_dtype == 'ultraquant_4bit')")
# flash_attn_supports_kv_cache_dtype (fa_utils.py:282-312): never fp8_e5m2; FA3 on SM90, FA4 on SM90 with head 512
# (or no head given), or FA4 on SM100. MAJOR, VER and HEAD are replaced by the caller's expressions.
FA_KV_OK = ("(input.kv_cache_dtype != 'fp8_e5m2' && ((MAJOR == 9 && (VER == 3 || (VER == 4 && (HEAD == null || HEAD == 512))))"
            " || (VER == 4 && MAJOR == 10)))")


def err(code, summary):
    return {"code": code, "status": 0, "retryable": False, "summary": summary}


def schemas():
    shape_props = {
        "num_tokens": I(16), "num_seqs": I(2), "num_heads": I(32), "num_kv_heads": I(8),
        "head_size": I(128), "kv_tokens": I(64), "max_query_len": I(8),
    }
    common_md = {
        "num_reqs": {"type": "integer", "examples": [2]},
        "num_actual_tokens": {"type": "integer", "examples": [24]},
        "max_query_len": {"type": "integer", "examples": [16]},
        "max_seq_len": {"type": "integer", "examples": [40]},
        "query_lens": {"type": "array", "items": {"type": "integer"}, "examples": [[16, 8]]},
        "seq_lens": {"type": "array", "items": {"type": "integer"}, "examples": [[40, 24]]},
        "block_table": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}},
                        "examples": [[[0, 1, 2], [3, 4]]], "description": "per-request KV block ids (block_ids) from the SchedulerOutput; owned by scheduler-kv"},
        "slot_mapping": {"type": "array", "items": {"type": "integer"}, "examples": [[32, 33]]},
        "causal": {"type": "boolean", "default": True},
        "causal_is_tensor": {"type": "boolean", "default": False},
        "causal_tensor_dtype": {"type": "string", "default": "int32"},
        "common_prefix_len": I(0),
        "has_cpu_seq_lens_upper_bound": B(False),
        "decode_query_threshold": I(1),
    }
    return [
        {"id": "AttnKernelShape", "summary": "The batch shape a kernel launch sees (drives its latency).",
         "schema": {"type": "object", "properties": shape_props}},
        {"id": "AttnKernelResult", "schema": {"type": "object", "properties": {"launched": {"type": "boolean", "const": True}}}},
        {"id": "AttnSelectorRequest", "summary": "Arguments of get_attn_backend.",
         "schema": {"type": "object", "required": ["head_size", "dtype"], "properties": {
             "head_size": {"type": "integer", "examples": [128]},
             "dtype": {"type": "string", "enum": ["float16", "bfloat16", "float32"], "default": "bfloat16"},
             "kv_cache_dtype": {"type": ["string", "null"], "default": "auto"},
             "use_mla": B(False), "has_sink": B(False), "use_sparse": B(False), "use_mm_prefix": B(False),
             "attn_type": S("decoder", enum=["decoder", "encoder", "encoder_only", "encoder_decoder"]),
             "has_sliding_window": B(False), "num_heads": I(32)}}},
        {"id": "AttnBackendSelection", "schema": {"type": "object", "properties": {
            "backend_cls_path": {"type": "string", "examples": ["vllm.v1.attention.backends.flash_attn.FlashAttentionBackend"]},
            "cached": {"type": "boolean"}}}},
        {"id": "AttnValidateRequest", "summary": "AttentionBackend.validate_configuration arguments plus the backend and the resolved FA version.",
         "schema": {"type": "object", "required": ["backend"], "properties": {
             "backend": S("FLASH_ATTN"),
             "head_size": I(128), "dtype": S("bfloat16"), "kv_cache_dtype": {"type": ["string", "null"], "default": "auto"},
             "block_size": {"type": ["integer", "null"], "default": None},
             "use_mla": B(False), "has_sink": B(False), "use_sparse": B(False), "use_mm_prefix": B(False),
             "use_per_head_quant_scales": B(False),
             "device_capability": {"type": "object", "properties": {"major": I(9), "minor": I(0)}},
             "attn_type": S("decoder"), "has_sliding_window": B(False), "use_rswa": B(False), "use_non_causal": B(False),
             "use_batch_invariant": B(False), "use_kv_connector": B(False), "use_pcp": B(False), "use_dcp": B(False),
             "fa_version": {"type": ["integer", "null"], "default": 3},
             "fa4_supported": B(True)}}},
        {"id": "AttnInvalidReasons", "schema": {"type": "object", "properties": {
            "invalid_reasons": {"type": "array", "items": {"type": "string"}}}}},
        {"id": "AttnFaVersionRequest", "summary": "get_flash_attn_version arguments plus the platform facts it reads.",
         "schema": {"type": "object", "properties": {
             "platform": S("cuda", enum=["cuda", "rocm", "xpu"]),
             "device_capability_major": I(9),
             "supported_versions": {"type": "array", "items": {"type": "integer"}, "default": [2, 3, 4]},
             "requires_alibi": B(False), "head_size": {"type": ["integer", "null"], "default": None},
             "head_size_v": {"type": ["integer", "null"], "default": None}, "has_sinks": B(False),
             "batch_invariant": B(False)}}},
        {"id": "AttnCommonMetadata", "summary": "CommonAttentionMetadata as the GPU model runner passes it to build().",
         "schema": {"type": "object", "required": ["num_reqs", "num_actual_tokens", "max_query_len", "max_seq_len", "query_lens", "seq_lens", "block_table", "slot_mapping"], "properties": common_md}},
        {"id": "AttnFlashBuildRequest", "summary": "build(common_prefix_len, common_attn_metadata, fast_build=False); the other fields are builder state from VllmConfig, with the code's defaults.",
         "schema": {"type": "object", "required": ["common"], "properties": {
            "common": {"$ref": "AttnCommonMetadata"},
            "fast_build": B(False), "fa_version": I(3), "use_full_cuda_graph": B(True),
            "max_cudagraph_size": I(512), "dcp_world_size": I(1), "batch_invariant": B(False),
            "sliding_window_configs": {"type": "integer", "default": 1, "description": "distinct sliding-window configs across layers"}}}},
        {"id": "AttnFlashMetadata", "summary": "FlashAttentionMetadata (the fields the impl reads).",
         "schema": {"type": "object", "properties": {
             "num_actual_tokens": {"type": "integer"}, "num_reqs": {"type": "integer"},
             "max_query_len": {"type": "integer"}, "max_seq_len": {"type": "integer"},
             "seq_lens": {"type": "array", "items": {"type": "integer"}},
             "block_table": {"type": "array"}, "slot_mapping": {"type": "array"},
             "causal": {"type": "boolean"}, "causal_is_tensor": {"type": "boolean"},
             "has_scheduler_metadata": {"type": "boolean"}, "max_num_splits": {"type": "integer"},
             "max_dcp_context_kv_len": {"type": "integer"}, "num_decode_reqs": {"type": "integer"},
             "num_prefill_reqs": {"type": "integer"}}}},
        {"id": "AttnForwardRequest", "summary": "AttentionImpl.forward arguments (shapes and the flags the impl branches on).",
         "schema": {"type": "object", "properties": {
             "layer_name": S("model.layers.0.self_attn.attn"),
             "attn_type": S("decoder", enum=["decoder", "encoder", "encoder_only", "encoder_decoder"]),
             "num_tokens": I(24), "num_heads": I(32), "num_kv_heads": I(8), "head_size": I(128),
             "kv_cache_dtype": S("auto"), "fa_version": I(3), "dcp_world_size": I(1), "device_capability_major": I(9),
             "has_output_scale": B(False), "has_output_block_scale": B(False),
             "has_alibi": B(False), "has_sinks": B(False), "profiling_run": B(False),
             "kv_quant_mode": S("none", enum=["none", "fp8_per_tensor", "int8_per_token_head", "fp8_per_token_head", "int4_per_token_head"]),
             "metadata": {"type": ["object", "null"]}}}},
        {"id": "AttnKvUpdateRequest", "schema": {"type": "object", "properties": {
            "attn_type": S("decoder"), "num_tokens": I(24), "num_kv_heads": I(8), "head_size": I(128),
            "kv_cache_dtype": S("auto"), "kv_quant_mode": S("none"),
            "slot_mapping": {"type": "array", "items": {"type": "integer"}, "examples": [[32, 33, 34]]},
            "device_capability_major": I(9), "device_capability_minor": I(0)}}},
        {"id": "AttnMergeRequest", "schema": {"type": "object", "properties": {
            "platform": S("cuda", enum=["cuda", "rocm", "cpu", "xpu"]), "cdna_version": I(3),
            "dtype": S("bfloat16"), "output_dtype": S("bfloat16"), "head_size": I(128), "num_tokens": I(24),
            "num_heads": I(32), "has_output_scale": B(False),
            "prefill_tokens_with_context": {"type": ["integer", "null"], "default": None},
            "head_strides_match": B(True), "prefix_head_stride": I(128), "suffix_head_stride": I(128)}}},
    ]


def configs():
    return [
        {"id": "attention-backend", "type": "string", "value": None, "default": None,
         "summary": "attention_backend / AttentionConfig.backend: unset, so the platform picks by priority (FLASH_ATTN first on SM90)",
         "sources": [C(CFG_ATT, ln(CFG_ATT, r"^\s+backend: AttentionBackendEnum")), C(ARGS, ln(ARGS, r"attention_backend: AttentionBackendEnum"))],
         "attributes": {"key": "attention_backend"}},
        {"id": "flash-attn-version", "type": "integer", "value": None, "default": None,
         "summary": "AttentionConfig.flash_attn_version: unset, so get_flash_attn_version picks by compute capability",
         "sources": [C(CFG_ATT, ln(CFG_ATT, r"flash_attn_version: Literal")), C(FAU, ln(FAU, r"attention_config.flash_attn_version is not None"))],
         "attributes": {"key": "flash_attn_version"}},
        {"id": "flash-attn-max-num-splits-for-cuda-graph", "type": "integer", "value": 32, "default": 32,
         "summary": "upper bound on FA3 split-KV splits when full CUDA graphs are captured",
         "sources": [C(CFG_ATT, ln(CFG_ATT, r"flash_attn_max_num_splits_for_cuda_graph: int")), C(FA, ln(FA, r"self.attention_config.flash_attn_max_num_splits_for_cuda_graph"))],
         "attributes": {"key": "flash_attn_max_num_splits_for_cuda_graph"}},
        {"id": "kv-cache-dtype", "type": "string", "value": "auto", "default": "auto",
         "summary": "kv_cache_dtype / CacheConfig.cache_dtype (attention backends read it; no other fragment defines it)",
         "sources": [Cln("vllm/config/cache.py", r"cache_dtype: CacheDType = \"auto\""), C(ARGS, ln(ARGS, r"kv_cache_dtype: CacheDType"))],
         "attributes": {"key": "cache_dtype"}},
        {"id": "decode-context-parallel-size", "type": "integer", "value": 1, "default": 1,
         "summary": "decode_context_parallel_size: FA takes the DCP path when > 1",
         "sources": [Cln("vllm/config/parallel.py", r"decode_context_parallel_size: int = Field"), C(ARGS, ln(ARGS, r"decode_context_parallel_size: int"))],
         "attributes": {"key": "decode_context_parallel_size"}},
        {"id": "dcp-comm-backend", "type": "string", "value": "ag_rs", "default": None,
         "summary": "dcp_comm_backend: unset in code, VllmConfig fills ag_rs via set_dcp_defaults; a2a selects dcp_a2a_lse_reduce",
         "sources": [Cln("vllm/config/parallel.py", r"dcp_comm_backend: DCPCommBackend \| None = None"), Cln("vllm/config/parallel.py", r"comm_backend: DCPCommBackend = \"ag_rs\"")],
         "attributes": {"key": "dcp_comm_backend"}},
        {"id": "attn-kernel-launch-us", "type": "number", "value": 5, "default": 5,
         "summary": "LABELED ASSUMPTION: fixed cost of one attention kernel launch in microseconds (the code gives no number)",
         "sources": [C(TUA, ln(TUA, r"kernel_unified_attention\[grid\]"))], "attributes": {"key": "assumption:attn_kernel_launch_us", "assumption": True}},
        {"id": "attn-us-per-query-token", "type": "number", "value": 0.05, "default": 0.05,
         "summary": "LABELED ASSUMPTION: per-layer attention cost per query token in microseconds (Llama-8B head shape, H100-class GPU)",
         "sources": [C(TUA, ln(TUA, r"total_num_q_blocks = q.shape\[0\] // BLOCK_Q"))], "attributes": {"key": "assumption:attn_us_per_query_token", "assumption": True}},
        {"id": "attn-us-per-kv-token", "type": "number", "value": 0.002, "default": 0.002,
         "summary": "LABELED ASSUMPTION: per-layer cost per KV-cache token read in microseconds (4 KiB of K+V per token per layer at ~3 TB/s)",
         "sources": [C(TUA, ln(TUA, r"num_seqs = len\(seqused_k\)"))], "attributes": {"key": "assumption:attn_us_per_kv_token", "assumption": True}},
    ]


def boundary_components():
    return [
        {"id": "cuda-platform", "name": "CudaPlatform", "kind": "module",
         "summary": "Boundary stub: the CUDA platform (owned by config-platform).",
         "sources": [C("vllm/platforms/cuda.py", ln("vllm/platforms/cuda.py", r"def get_attn_backend_cls"))],
         "attributes": {"boundary": True, "owner": "config-platform"}},
        {"id": "custom-ops", "name": "_custom_ops", "kind": "module",
         "summary": "Boundary stub: torch custom-op wrappers (owned by kernels-ops).",
         "sources": ["vllm/_custom_ops.py"], "attributes": {"boundary": True, "owner": "kernels-ops"}},
        {"id": "group-coordinator", "name": "GroupCoordinator", "kind": "module",
         "summary": "Boundary stub: a process group's collectives (owned by distributed).",
         "sources": [C("vllm/distributed/parallel_state.py", ln("vllm/distributed/parallel_state.py", r"^class GroupCoordinator"))],
         "attributes": {"boundary": True, "owner": "distributed"}},
    ]


def boundary_interfaces():
    out = []
    out.append({"component": "cuda-platform", "name": "get-attn-backend-cls", "kind": "function",
                "summary": "Boundary stub: CudaPlatform.get_attn_backend_cls validates the selected or prioritized backends and returns the class path.",
                "sources": [Cfn("vllm/platforms/cuda.py", "get_attn_backend_cls")],
                "attributes": {"boundary": True, "owner": "config-platform"},
                "request": {"type": "object", "properties": {
                    "selected_backend": {"type": ["string", "null"]}, "attn_selector_config": {"type": "object"},
                    "num_heads": {"type": ["integer", "null"]}}},
                "response": {"type": "object", "properties": {"backend_cls_path": {"type": "string", "examples": ["vllm.v1.attention.backends.flash_attn.FlashAttentionBackend"]}}},
                "errors": [err("value-error", "no valid backend, or the selected backend is invalid")]})
    tok = {"type": "object", "properties": {"num_tokens": {"type": "integer", "minimum": 0}, "hidden_size": {"type": "integer", "minimum": 1},
                                             "dtype_bytes": {"type": "integer"}}}
    att = {"type": "object", "properties": {k: {"type": "integer"} for k in ("num_seqs", "seq_len", "num_heads", "num_kv_heads", "head_dim", "dtype_bytes")}}
    for name, pyname, summary, req in [
        ("merge-attn-states", "merge_attn_states", "Boundary stub: _custom_ops.merge_attn_states -> torch.ops._C.merge_attn_states (copied from kernels-ops).", tok),
        ("reshape-and-cache-flash", "reshape_and_cache_flash", "Boundary stub: _custom_ops.reshape_and_cache_flash -> torch.ops._C_cache_ops.reshape_and_cache_flash (copied from kernels-ops).", tok),
        ("hadacore-transform", "hadacore_transform", "Boundary stub: _custom_ops.hadacore_transform (copied from kernels-ops).", tok),
        ("mla-decode-kvcache-cpu", "mla_decode_kvcache_cpu", "Boundary stub: _custom_ops.mla_decode_kvcache_cpu -> torch.ops._C.mla_decode_kvcache (copied from kernels-ops).", att),
    ]:
        out.append({"component": "custom-ops", "name": name, "kind": "function", "summary": summary,
                    "sources": [Cfn("vllm/_custom_ops.py", pyname)],
                    "attributes": {"boundary": True, "owner": "kernels-ops"},
                    "request": req, "latency_ms": 0})
    dres = {"type": "object", "properties": {"backend": {"type": "string", "examples": ["custom-allreduce"]}, "algorithm": {"type": "string"},
                                              "bytes": {"type": "integer"}, "world_size": {"type": "integer"}, "num_tokens": {"type": "integer"},
                                              "hidden_size": {"type": "integer"}}}
    for name, pyname in [("all-gather", "all_gather"), ("reduce-scatter", "reduce_scatter")]:
        out.append({"component": "group-coordinator", "name": name, "kind": "function",
                    "summary": f"Boundary stub: GroupCoordinator.{pyname} over the DCP group (copied from distributed).",
                    "sources": [Cfn("vllm/distributed/parallel_state.py", pyname, ln("vllm/distributed/parallel_state.py", r"^class GroupCoordinator"))],
                    "attributes": {"boundary": True, "owner": "distributed"},
                    "request": {"type": "object", "required": ["num_tokens", "world_size"], "properties": {"num_tokens": {"type": "integer"}, "world_size": {"type": "integer"}, "dim": {"type": "integer"}, "group_name": {"type": "string", "examples": ["dcp:0"]}, "ranks": {"type": "array", "items": {"type": "string"}}}},
                    "response": dres, "errors": [{"code": "assertion-error", "status": 0, "retryable": False}]})
    return out


# ---------------------------------------------------------------- components

def comp(id_, name, f, summary, parent="gpu-worker", a=None, b=None, kind="module", **kw):
    srcs = [C(f, a, b)] if a else [f]
    d = {"id": id_, "name": name, "kind": kind, "parent": parent, "layer": "attention", "summary": summary, "sources": srcs}
    d.update(kw)
    return d


def components():
    out = []
    a, b = fn(SEL, "get_attn_backend")
    out.append(comp("selector", "attention selector (selector.py)", SEL,
                    "Picks the attention backend class for a layer, memoized per selector config.", a=a, b=fn(SEL, "_cached_get_attn_backend")[1],
                    state={"schema": {"type": "object", "properties": {"cached_backends": {"type": "object"}}},
                           "initial": {"cached_backends": {}}},
                    tags=["cache"],
                    attributes={"racy_in_code": "vllm/v1/attention/selector.py:203-225 (functools.cache: the lookup and the store of _cached_get_attn_backend are not locked; two first calls with one config both get the class from the platform and store it, the same value either way)"}))
    a, b = cls(BK, "AttentionBackend")
    ALL_T = ["decoder", "encoder", "encoder_only", "encoder_decoder"]

    def row(name, **kw):
        r = {"name": name, "dtypes": ["float16", "bfloat16"], "kv_cache_dtypes": ["auto", "float16", "bfloat16"], "kv_none_ok": True,
             "kv_prefix": "", "head_size_rule": "list", "head_sizes": [], "min_capability": 0, "max_capability": 1000,
             "capability_majors": [], "sink_rule": "never", "mm_prefix_rule": "never", "per_head_quant_rule": "never",
             "block_multiple": 16, "is_mla": False, "is_sparse": False, "sliding_window": False, "batch_invariance": False,
             "attn_types": ["decoder"], "pcp": False, "dcp": False, "combination_rule": "none", "rswa": False, "non_causal": False}
        r.update(kw)
        return r
    FP8 = ["auto", "float16", "bfloat16", "fp8", "fp8_e4m3"]
    fa_row = row("FLASH_ATTN", kv_cache_dtypes=FP8, head_size_rule="fa", min_capability=80, sink_rule="fa", mm_prefix_rule="fa4",
                 per_head_quant_rule="fa3", sliding_window=True, batch_invariance=True, attn_types=ALL_T, dcp=True, combination_rule="fa", rswa=True, non_causal=True)
    tr_row = row("TRITON_ATTN", dtypes=["float16", "bfloat16", "float32"],
                 kv_cache_dtypes=FP8 + ["fp8_e5m2", "int4_per_token_head", "int8_per_token_head", "fp8_per_token_head"],
                 head_size_rule="min32", sink_rule="always", mm_prefix_rule="always", sliding_window=True, batch_invariance=True, attn_types=ALL_T, rswa=True, non_causal=True)
    fi_row = row("FLASHINFER", kv_cache_dtypes=FP8 + ["fp8_e5m2", "nvfp4", "nvfp4_4over6"], head_sizes=[64, 128, 256, 512],
                 min_capability=80, max_capability=121, sliding_window=True, non_causal=True)
    flex_row = row("FLEX_ATTENTION", dtypes=["float16", "bfloat16", "float32"], mm_prefix_rule="always", sliding_window=True,
                   batch_invariance=True, attn_types=["decoder", "encoder_only"], rswa=True, non_causal=True)
    tq_row = row("TURBOQUANT", kv_cache_dtypes=[], kv_none_ok=False, kv_prefix="turboquant_", head_size_rule="positive")
    mla = dict(is_mla=True, head_sizes=[320, 512, 576])
    backends = {
        "FLASH_ATTN": fa_row, "TRITON_ATTN": tr_row, "FLASHINFER": fi_row, "FLEX_ATTENTION": flex_row, "TURBOQUANT": tq_row,
        "TRITON_FLASH_ATTN": dict(fa_row, name="TRITON_FLASH_ATTN"), "TRITON_FLASHINFER": dict(fi_row, name="TRITON_FLASHINFER"),
        "FLASH_ATTN_MLA": row("FLASH_ATTN_MLA", capability_majors=[9], batch_invariance=True, **mla),
        "FLASHMLA": row("FLASHMLA", kv_cache_dtypes=FP8, capability_majors=[9, 10], block_multiple=64, **mla),
        "FLASHINFER_MLA": row("FLASHINFER_MLA", kv_cache_dtypes=FP8, capability_majors=[10], block_multiple=32, non_causal=True, **mla),
        "TRITON_MLA": row("TRITON_MLA", kv_cache_dtypes=FP8, is_mla=True, head_sizes=[], batch_invariance=True, non_causal=True),
        "CUTLASS_MLA": row("CUTLASS_MLA", kv_cache_dtypes=FP8, capability_majors=[10], block_multiple=128, **mla),
    }
    out.append(comp("attention-backend", "AttentionBackend", BK,
                    "Base class of attention backends: capability checks and validate_configuration. State holds the class-level capabilities of every backend in the CUDA priority lists (dense and MLA).",
                    a=a, b=b,
                    state={"schema": {"type": "object", "properties": {"backends": {"type": "object"}}},
                           "initial": {"backends": backends}}))
    out.append(comp("fa-utils", "fa_utils.py", FAU, "FlashAttention version resolution and capability helpers.", a=1, b=len(__import__('lib').lines(FAU))))
    a, b = cls(FA, "FlashAttentionMetadataBuilder")
    out.append(comp("flash-attention-metadata-builder", "FlashAttentionMetadataBuilder", FA,
                    "Builds FlashAttentionMetadata per step; precomputes FA3 AOT scheduler metadata and pins split counts under full CUDA graphs.", a=a, b=b))
    a, b = cls(FA, "FlashAttentionImpl")
    out.append(comp("flash-attention-impl", "FlashAttentionImpl", FA,
                    "FlashAttention forward (paged varlen), KV cache write, encoder and DCP paths.", a=a, b=b))
    out.append(comp("flash-attn-interface", "flash_attn_interface.py", FAI,
                    "vLLM's FlashAttention Python interface: dispatches to the FA2/FA3/FA4 kernels.", a=1, b=747))
    out.append(comp("merge-attn-states", "merge_attn_states.py", MAS,
                    "Merges prefix/suffix partial attention outputs by LSE; picks the CUDA op, a torch fallback or Triton.", a=1, b=195))
    out.append(comp("triton-merge-attn-states", "triton_merge_attn_states.py", TMAS,
                    "Triton implementation of the LSE merge.", a=1, b=len(__import__('lib').lines(TMAS))))
    a, b = cls(TA, "TritonAttentionMetadataBuilder")
    out.append(comp("triton-attention-metadata-builder", "TritonAttentionMetadataBuilder", TA,
                    "Builds TritonAttentionMetadata; carries the 2D/3D (segmented softmax) threshold.", a=a, b=b))
    a, b = cls(TA, "TritonAttentionImpl")
    out.append(comp("triton-attention-impl", "TritonAttentionImpl", TA,
                    "Triton attention forward and KV cache write (fp8 per-tensor and per-token-head quant).", a=a, b=b))
    out.append(comp("triton-unified-attention", "triton_unified_attention.py", TUA,
                    "unified_attention: one Triton kernel for prefill and decode over the paged KV cache; 3D segmented softmax for small decode batches.", a=1, b=1202))
    out.append(comp("triton-reshape-and-cache-flash", "triton_reshape_and_cache_flash.py", TRC,
                    "Triton writers of new K/V into the paged KV cache.", a=1, b=613))
    out.append(comp("triton-prefill-attention", "triton_prefill_attention.py", TPA,
                    "context_attention_fwd: non-paged Triton prefill attention (encoder / ViT).", a=1, b=299))
    out.append(comp("int4-per-token-head", "int4_per_token_head.py", I4,
                    "INT4 per-token-head KV cache: RHT rotation, packing writer and packed attention.", a=1, b=1167))
    a, b = cls(MLAP, "MLAPrefillBackend")
    out.append(comp("mla-prefill-backend", "MLAPrefillBackend", MLAP,
                    "Base of MLA prefill backends; capability gates such as supports_quant_output.", a=a, b=b))
    a, b = cls(MLAPFA, "FlashAttnPrefillBackend")
    out.append(comp("flash-attn-prefill-backend", "FlashAttnPrefillBackend", MLAPFA,
                    "FlashAttention MLA prefill backend; fused FP8 output on FA4 + SM100/SM110.", a=a, b=b))
    a, b = cls(CPUMLA, "CPUMLAImpl")
    out.append(comp("cpu-mla-impl", "CPUMLAImpl", CPUMLA,
                    "CPU MLA impl: inline latent KV cache write and CPU decode. State: the latent KV rows written per slot (simulated tensor contents; block bookkeeping stays with scheduler-kv).",
                    a=a, b=b,
                    state={"schema": {"type": "object", "properties": {"latent_rows": {"type": "object"}, "num_slots": {"type": "integer"}}},
                           "initial": {"latent_rows": {}, "num_slots": 64}}))
    out.append(comp("cpu-attn", "cpu_attn.py", CPUA, "CPU attention backend: ISA selection for the C++ kernels.",
                    a=fn(CPUA, "_riscv_supports_rvv")[0], b=fn(CPUA, "_get_attn_isa")[1]))
    out.append(comp("dcp", "dcp.py", DCP, "Decode-context-parallel combine ops: LSE all-gather + correction + reduce-scatter, or packed all-to-all.", a=1, b=1652))
    a, b = cls(DCP, "MLADCPManager")
    out.append(comp("mla-dcp-manager", "MLADCPManager", DCP, "Chooses the DCP combine (direct symmetric-memory A2A, NCCL A2A, AG+RS) and runs the direct q/kv gathers.", a=a, b=b))
    out.append(comp("direct-dcp-a2a-workspace", "DirectDCPA2AWorkspace", DCP, "Symmetric-memory workspace for the direct DCP A2A LSE reduce.", a=cls(DCP, "DirectDCPA2AWorkspace")[0], b=cls(DCP, "DirectDCPA2AWorkspace")[1]))
    out.append(comp("direct-dcp-q-gather-workspace", "DirectDCPQGatherWorkspace", DCP, "Multimem workspace for the direct DCP query gather.", a=cls(DCP, "DirectDCPQGatherWorkspace")[0], b=cls(DCP, "DirectDCPQGatherWorkspace")[1]))
    out.append(comp("direct-dcp-kv-gather-workspace", "DirectDCPKVGatherWorkspace", DCP, "Multimem workspace for the direct DCP KV gather.", a=cls(DCP, "DirectDCPKVGatherWorkspace")[0], b=cls(DCP, "DirectDCPKVGatherWorkspace")[1]))
    out.append(comp("dcp-direct-a2a-lse-reduce", "dcp_direct_a2a_lse_reduce.cu", A2A, "CUDA op _C::direct_dcp_a2a_lse_reduce and its kernels.", a=1, b=381))
    out.append(comp("dcp-direct-q-gather", "dcp_direct_q_gather.cu", QG, "CUDA op _C::direct_dcp_q_gather and its multimem kernel.", a=1, b=197))
    out.append(comp("dcp-direct-kv-gather", "dcp_direct_kv_gather.cu", KVG, "CUDA op _C::direct_dcp_kv_gather and its kernels.", a=1, b=209))
    out.append(comp("vit-attn-wrappers", "vit_attn_wrappers.py", VIT, "ViT / multimodal-encoder attention entry points, each behind a torch custom op.", a=1, b=464))
    return out


# ---------------------------------------------------------------- interfaces

def iface(component, name, summary, sources, behavior, request=None, response=None, errors=None, kind="function", **kw):
    d = {"component": component, "name": name, "kind": kind, "summary": summary, "sources": sources}
    if request:
        d["request"] = request
    if response:
        d["response"] = response
    if errors:
        d["errors"] = errors
    d["behavior"] = behavior
    d.update(kw)
    return d


def selection_interfaces():
    out = []
    a, b = fn(SEL, "get_attn_backend")
    ca, cb = fn(SEL, "_cached_get_attn_backend")
    # functools.cache keys on (backend, the whole AttentionSelectorConfig, num_heads, the run's cache dtype).
    key = ("= 'h' + string(input.head_size) + '_' + input.dtype + '_' + (input.kv_cache_dtype == null ? 'none' : input.kv_cache_dtype)"
           " + (input.use_mla ? '_mla' : '') + (input.use_sparse ? '_sparse' : '') + (input.has_sink ? '_sink' : '') + (input.use_mm_prefix ? '_mm' : '')"
           " + (input.has_sliding_window ? '_sw' : '') + '_' + input.attn_type + '_n' + string(input.num_heads) + '_b' + (vars.backend == null ? 'auto' : vars.backend)"
           " + (vars.use_dcp ? '_dcp' : '') + '_run' + config['kv-cache-dtype']")
    out.append(iface(
        "selector", "get-attn-backend",
        "get_attn_backend: validate the KV cache dtype, build the AttentionSelectorConfig from VllmConfig and ask the platform for the backend class (functools.cache memoizes per config).",
        [C(SEL, a, b), C(SEL, ca, cb), C(SEL, *cls(SEL, "AttentionSelectorConfig"))],
        [
            {"if": "input.kv_cache_dtype != null && !(input.kv_cache_dtype in " + str(KV_DTYPES).replace('"', "'") + ")",
             "then": [{"title": "Invalid kv_cache_dtype", "source": C(SEL, ln(SEL, r"assert kv_cache_dtype in valid_cache_dtypes")),
                       "fail": {"code": "assertion-error", "message": "= 'Invalid kv_cache_dtype: ' + input.kv_cache_dtype + \". Valid values are: (" + ", ".join(repr(x) for x in KV_DTYPES) + ")\""}}]},
            {"title": "Build the AttentionSelectorConfig", "detail": "block_size is passed only when the user set it (the fixtures don't, so None); use_dcp reads decode_context_parallel_size.",
             "source": C(SEL, ln(SEL, r"attn_selector_config = AttentionSelectorConfig\("), ln(SEL, r"use_rswa=\(") + 3),
             "set": {"vars.backend": "= 'attention-backend' in config ? config['attention-backend'] : null",
                     "vars.use_dcp": "= config['decode-context-parallel-size'] > 1"}},
            {"title": "A per-KV-group override (AttentionConfig.backend_per_kind, keyed by the layer's KVCacheSpecKind) takes precedence over the global backend",
             "source": C(SEL, ln(SEL, r"if attention_config\.backend_per_kind:"), ln(SEL, r"backend = attention_config\.backend_per_kind\.get\(kind\.value, backend\)")),
             "if": "'attention-backend-per-kind' in config && size(config['attention-backend-per-kind']) > 0",
             "then": [{"call": "selector.get-attn-spec-kind", "input": {"use_mla": "= input.use_mla", "has_sliding_window": "= input.has_sliding_window", "attn_type": "= input.attn_type"}, "as": "kind"},
                      {"title": "Kinds not in the map fall back to the global backend", "source": C(SEL, ln(SEL, r"backend = attention_config\.backend_per_kind\.get\(kind\.value, backend\)")),
                       "set": {"vars.backend": "= vars.kind.value.kind in config['attention-backend-per-kind'] ? dyn(config['attention-backend-per-kind'][vars.kind.value.kind]) : dyn(vars.backend)"}}]},
            {"set": {"vars.key": key}},
            {"if": "vars.key in state.cached_backends",
             "then": [{"title": "functools.cache hit: the platform is not consulted again", "source": C(SEL, ln(SEL, r"^@cache"), ca),
                       "return": {"backend_cls_path": "= state.cached_backends[vars.key]", "cached": True}}]},
            {"title": "Ask the platform for the backend class", "source": C(SEL, ln(SEL, r"attention_cls = current_platform.get_attn_backend_cls")),
             "call": "cuda-platform.get-attn-backend-cls",
             "input": {"selected_backend": "= vars.backend", "num_heads": "= input.num_heads",
                       "attn_selector_config": {"head_size": "= input.head_size", "dtype": "= input.dtype", "kv_cache_dtype": "= input.kv_cache_dtype",
                                                "block_size": None, "use_mla": "= input.use_mla", "has_sink": "= input.has_sink",
                                                "use_sparse": "= input.use_sparse", "attn_type": "= input.attn_type",
                                                "has_sliding_window": "= input.has_sliding_window", "use_dcp": "= vars.use_dcp"}},
             "as": "cls"},
            {"if": "!has(vars.cls.value.backend_cls_path) || vars.cls.value.backend_cls_path == ''",
             "then": [{"title": "No backend class for this platform", "source": C(SEL, ln(SEL, r"Invalid attention backend for")),
                       "fail": {"code": "value-error", "message": "Invalid attention backend for cuda"}}]},
            {"title": "Memoize and resolve the class by qualname", "source": C(SEL, ln(SEL, r"backend = resolve_obj_by_qualname")),
             "set": {"= 'state.cached_backends.' + vars.key": "= vars.cls.value.backend_cls_path"}},
            {"return": {"backend_cls_path": "= vars.cls.value.backend_cls_path", "cached": False}},
        ],
        request="AttnSelectorRequest", response="AttnBackendSelection",
        errors=[err("assertion-error", "kv_cache_dtype is not a CacheDType"), err("value-error", "the platform returned no backend class")]))

    # validate_configuration
    va, vb = fn(BK, "validate_configuration")
    row = "state.backends[input.backend]"

    def chk(cond, reason, pat):
        return {"if": cond, "then": [{"title": reason, "source": C(BK, ln(BK, pat, va)),
                                      "set": {"vars.reasons": f"= vars.reasons + ['{reason}']"}}]}
    cap = "(input.device_capability.major * 10 + input.device_capability.minor)"
    head_ok = (f"({row}.head_size_rule == 'fa' ? (input.head_size % 8 == 0 && (input.head_size <= 256 || (input.fa4_supported && input.head_size <= 512)))"
               f" : ({row}.head_size_rule == 'min32' ? input.head_size >= 32 : ({row}.head_size_rule == 'positive' ? input.head_size > 0"
               f" : (size({row}.head_sizes) == 0 || input.head_size in {row}.head_sizes))))")
    sink_ok = f"({row}.sink_rule == 'always' || (input.fa_version != null && input.fa_version >= 3))"
    mm_ok = f"({row}.mm_prefix_rule == 'always' || input.fa4_supported)"
    phq_ok = f"({row}.per_head_quant_rule == 'fa3' && input.fa_version != null && input.fa_version >= 3)"
    fakv = FA_KV_OK.replace("MAJOR", "input.device_capability.major").replace("VER", "input.fa_version").replace("HEAD", "input.head_size")
    # supports_kv_cache_dtype asks flash_attn_supports_kv_cache_dtype without a head size; supports_combination passes it.
    fakv_nohead = FA_KV_OK.replace("MAJOR", "input.device_capability.major").replace("VER", "input.fa_version").replace("(HEAD == null || HEAD == 512)", "true")
    kv_ok = (f"(input.kv_cache_dtype == null ? {row}.kv_none_ok : ((input.kv_cache_dtype in {row}.kv_cache_dtypes || ({row}.kv_prefix != '' && input.kv_cache_dtype.startsWith({row}.kv_prefix)))"
             f" && ({row}.name != 'FLASH_ATTN' || !{QUANT} || {fakv_nohead})))")
    beh = [
        {"if": "!(input.backend in state.backends)",
         "then": [{"title": "Unknown backend name", "detail": "AttentionBackendEnum has no such member among the modeled backends (the CUDA priority lists).",
                   "source": Cln("vllm/v1/attention/backends/registry.py", r"^class AttentionBackendEnum"),
                   "fail": {"code": "key-error", "message": "= input.backend"}}]},
        {"title": "Check each capability of the backend class", "source": C(BK, va, vb), "set": {"vars.reasons": []}},
        chk(f"!{head_ok}", "head_size not supported", r"head_size not supported"),
        chk(f"!(input.dtype in {row}.dtypes)", "dtype not supported", r"\"dtype not supported\""),
        chk(f"!{kv_ok}", "kv_cache_dtype not supported", r"kv_cache_dtype not supported"),
        chk(f"input.block_size != null && input.block_size % {row}.block_multiple != 0", "block_size not supported", r"block_size not supported"),
        chk(f"input.use_mm_prefix && !{mm_ok}", "partial multimodal token full attention not supported", r"partial multimodal token full attention"),
        chk(f"input.use_mla && !{row}.is_mla", "MLA not supported", r"\"MLA not supported\""),
        chk(f"!input.use_mla && {row}.is_mla", "non-MLA not supported", r"\"non-MLA not supported\""),
        chk(f"input.has_sink && !{sink_ok}", "attention sinks not supported", r"attention sinks not supported"),
        chk(f"input.use_sparse && !{row}.is_sparse", "sparse not supported", r"\"sparse not supported\""),
        chk(f"!input.use_sparse && {row}.is_sparse", "non-sparse not supported", r"\"non-sparse not supported\""),
        chk(f"input.use_per_head_quant_scales && !{phq_ok}", "per-head quant scales not supported", r"per-head quant scales not supported"),
        chk(f"{cap} < {row}.min_capability || {cap} > {row}.max_capability || (size({row}.capability_majors) > 0 && !(input.device_capability.major in {row}.capability_majors))", "compute capability not supported", r"compute capability not supported"),
        {"if": f"!(input.attn_type in {row}.attn_types)",
         "then": [{"title": "attention type not supported", "source": C(BK, ln(BK, r"attention type \{attn_type\} not supported", va)),
                   "set": {"vars.reasons": "= vars.reasons + ['attention type ' + input.attn_type + ' not supported']"}}]},
        chk(f"input.has_sliding_window && !{row}.sliding_window", "sliding window not supported", r"sliding window not supported"),
        chk(f"input.use_rswa && !{row}.rswa", "R-SWA not supported", r"\"R-SWA not supported\""),
        chk(f"input.use_non_causal && !{row}.non_causal", "non-causal attention not supported", r"\"non-causal attention not supported\""),
        chk(f"input.use_batch_invariant && !{row}.batch_invariance", "batch invariance not supported", r"batch invariance not supported"),
        chk(f"input.use_pcp && !{row}.pcp", "PCP not supported", r"PCP not supported"),
        chk(f"input.use_dcp && !{row}.dcp", "DCP not supported", r"DCP not supported"),
        {"if": f"{row}.combination_rule == 'fa'",
         "then": [{"title": "FlashAttention's supports_combination returns the first reason it finds", "source": Cfn(FA, "supports_combination"),
                   "set": {"vars.comb": "= (input.has_sink && " + cap + " < 90) ? 'sink not supported on compute capability < 9.0'"
                           " : ((input.use_mm_prefix && input.kv_cache_dtype != null && " + QUANT + " && " + cap + " == 90) ? 'SM90 FP8 KV with mm_prefix requires Triton'"
                           " : ((input.kv_cache_dtype != null && " + QUANT + " && !" + fakv + ") ? 'FP8 KV cache requires FA3 on SM90, FA4 with head_size=512 on SM90, or FA4 on SM100'"
                           " : ((input.use_mm_prefix && input.fa_version != 4) ? 'mm_prefix (PrefixLM bidirectional attention) requires FlashAttention v4, which does not resolve for this head_size' : '')))"}},
                  {"if": "vars.comb != ''",
                   "then": [{"title": "The combination reason is appended last", "source": C(BK, ln(BK, r"if combination_reason is not None:", va), ln(BK, r"invalid_reasons\.append\(combination_reason\)", va)),
                             "set": {"vars.reasons": "= vars.reasons + [vars.comb]"}}]}]},
        {"return": {"invalid_reasons": "= vars.reasons"}},
    ]
    out.append(iface("attention-backend", "validate-configuration",
                     "AttentionBackend.validate_configuration: the list of reasons a backend can't serve this layer (empty means valid); the platform calls it per candidate.",
                     [C(BK, va, vb), Cfn(FA, "supports_combination")], beh,
                     request="AttnValidateRequest", response="AttnInvalidReasons",
                     errors=[err("key-error", "no such backend")]))

    # get_flash_attn_version
    ga, gb = fn(FAU, "get_flash_attn_version")
    sup = "input.supported_versions"
    beh = [
        {"if": "input.platform == 'xpu'", "then": [{"title": "XPU always uses FA2", "source": C(FAU, ln(FAU, r"if current_platform.is_xpu\(\):", ga)), "return": {"fa_version": 2}}]},
        {"if": "input.platform == 'rocm'", "then": [{"title": "ROCm doesn't use vllm_flash_attn", "source": C(FAU, ln(FAU, r"if current_platform.is_rocm\(\):", ga)), "return": {"fa_version": None}}]},
        {"title": "Default by compute capability: FA3 on Hopper, FA4 on Blackwell, else FA2",
         "source": C(FAU, ln(FAU, r"if device_capability.major == 9 and is_fa_version_supported\(3\)"), ln(FAU, r"fa_version = 2", ga)),
         "set": {"vars.v": f"= input.device_capability_major == 9 && 3 in {sup} ? 3 : (input.device_capability_major == 10 && 4 in {sup} ? 4 : 2)"}},
        {"when": "'flash-attn-version' in config && config['flash-attn-version'] != null", "title": "attention_config.flash_attn_version overrides",
         "source": C(FAU, ln(FAU, r"fa_version = vllm_config.attention_config.flash_attn_version")), "set": {"vars.v": "= config['flash-attn-version']"}},
        {"if": "input.device_capability_major >= 10 && vars.v == 3",
         "then": [{"title": "FA3 can't run on Blackwell", "source": C(FAU, ln(FAU, r"Cannot use FA version 3 on Blackwell")),
                   "set": {"vars.v": f"= 4 in {sup} ? 4 : 2"}}]},
        {"if": "input.requires_alibi && (vars.v == 3 || vars.v == 4)",
         "then": [{"title": "ALiBi needs FA2", "source": C(FAU, ln(FAU, r"Cannot use FA version 3 with ALiBi")), "set": {"vars.v": 2}}]},
        {"if": f"vars.v == 3 && input.device_capability_major == 9 && 4 in {sup} && ((input.head_size != null && input.head_size > 256) || (input.has_sinks && input.head_size != null && input.head_size_v != null && input.head_size != input.head_size_v))",
         "then": [{"title": "Upgrade FA3 -> FA4 for shapes FA3 can't serve on SM90", "source": C(FAU, ln(FAU, r"upgrading FlashAttention 3 -> 4")), "set": {"vars.v": 4}}]},
        {"if": "input.batch_invariant && vars.v == 4",
         "then": [{"title": "Batch invariance can't use FA4", "source": C(FAU, ln(FAU, r"Cannot use FA version 4 with batch invariance")), "set": {"vars.v": 2}}]},
        {"if": "vars.v == 4 && input.device_capability_major >= 10 && input.head_size != null && input.head_size > 128 && !((input.head_size == 256 && (input.head_size_v == null || input.head_size_v == 256)) || (input.head_size == 192 && input.head_size_v == 128))",
         "then": [{"title": "FA4 on Blackwell is limited by TMEM", "source": C(FAU, ln(FAU, r"FA4 on Blackwell does not support head_size")), "set": {"vars.v": 2}}]},
        {"if": f"!(vars.v in {sup})",
         "then": [{"title": "Chosen version unsupported: the assertion is caught and None is returned",
                   "source": C(FAU, ln(FAU, r"except \(ImportError, AssertionError\):", ga)), "return": {"fa_version": None}}]},
        {"return": {"fa_version": "= vars.v"}},
    ]
    out.append(iface("fa-utils", "get-flash-attn-version",
                     "get_flash_attn_version: pick FA2/3/4 from the platform, compute capability, config override and the layer's needs.",
                     [C(FAU, ga, gb)], beh, request="AttnFaVersionRequest",
                     response={"type": "object", "properties": {"fa_version": {"type": ["integer", "null"]}}}))
    return out

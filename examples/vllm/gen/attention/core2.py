"""FlashAttention, FA interface, merge, Triton attention, int4, DCP, ViT, MLA prefill gate, CPU MLA."""
from core import (A2A, B, CPUA, CPUMLA, DCOM, DCP, FA, FAI, I, I4, KVG, MAS, MASCU, MLAP, MLAPFA, QG, QUANT,
                  S, TA, TAH, TMAS, TPA, TRC, TUA, VIT, err, iface)
from lib import (C, Cfn, Cinv, Cln, LAT_ATTN, LAT_META, SHAPE, fn, helper, kernel, launch, ln, mark, note,
                 op_kernel)

MD = "input.common"
SHAPE_FROM_FWD = {
    "num_tokens": "= input.num_tokens", "num_heads": "= input.num_heads", "num_kv_heads": "= input.num_kv_heads",
    "head_size": "= input.head_size",
    "num_seqs": "= has(input.metadata) && input.metadata != null && has(input.metadata.num_reqs) ? input.metadata.num_reqs : 1",
    "kv_tokens": "= has(input.metadata) && input.metadata != null && has(input.metadata.seq_lens) ? sum(input.metadata.seq_lens) : input.num_tokens",
    "max_query_len": "= has(input.metadata) && input.metadata != null && has(input.metadata.max_query_len) ? input.metadata.max_query_len : input.num_tokens",
}


def fa_interfaces():
    out = []
    # ---- FlashAttentionMetadataBuilder.build
    ba, bb = fn(FA, "build", ln(FA, r"^class FlashAttentionMetadataBuilder"))
    ga, gb = fn(FA, "_get_scheduler_metadata")
    beh = [
        {"title": "AOT scheduling only on FA3, not for spec-decode fast builds or batch invariance",
         "detail": "aot_schedule is fixed at __init__ as get_flash_attn_version() == 3.",
         "source": C(FA, ln(FA, r"aot_schedule = \(", ba), ln(FA, r"aot_schedule = \(", ba) + 2),
         "set": {"vars.aot": "= input.fa_version == 3 && !input.fast_build && !input.batch_invariant"}},
        {"if": "vars.aot && input.sliding_window_configs > 1",
         "then": [{"title": "Layers disagree on the sliding window: AOT scheduling is turned off", "source": C(FA, ln(FA, r"elif len\(sliding_window_configs\) > 1:", ba)),
                   "set": {"vars.aot": False}}]},
        {"title": "Split count: pinned to flash_attn_max_num_splits_for_cuda_graph when the batch fits a full CUDA graph, else 0 (FA3 heuristics)",
         "source": C(FA, ln(FA, r"max_num_splits = 0  # 0 means use FA3", ba), ln(FA, r"max_num_splits = self.max_num_splits", ba)),
         "set": {"vars.splits": f"= input.use_full_cuda_graph && input.fa_version == 3 && {MD}.num_actual_tokens <= input.max_cudagraph_size ? config['flash-attn-max-num-splits-for-cuda-graph'] : 0"}},
        {"if": "input.batch_invariant", "then": [{"title": "Batch invariance forces one split", "source": C(FA, ln(FA, r"if envs.VLLM_BATCH_INVARIANT:", ba) + 1), "set": {"vars.splits": 1}}]},
        {"set": {"vars.dcp_ctx": 0, "vars.ndec": 0, "vars.npre": 0, "vars.sched": False}},
        {"if": "input.dcp_world_size > 1",
         "then": [
             {"title": "DCP: per-rank context lengths and the decode/extend split",
              "source": C(FA, ln(FA, r"if self.dcp_world_size > 1:", ba), ln(FA, r"if skip_dcp_context_attention:", ba)),
              "set": {"vars.ndec": f"= {MD}.max_query_len <= 1 ? {MD}.num_reqs : (!{MD}.has_cpu_seq_lens_upper_bound ? 0 : {MD}.query_lens.filter(q, q <= {MD}.decode_query_threshold).size())",
                      "vars.npre": f"= {MD}.max_query_len <= 1 ? 0 : (!{MD}.has_cpu_seq_lens_upper_bound ? {MD}.num_reqs : {MD}.query_lens.filter(q, q > {MD}.decode_query_threshold).size())"}},
             {"if": f"{MD}.has_cpu_seq_lens_upper_bound && sum({MD}.seq_lens) == sum({MD}.query_lens)",
              "then": [{"title": "No request has context: skip DCP context attention", "source": C(FA, ln(FA, r"if skip_dcp_context_attention:", ba), ln(FA, r"if skip_dcp_context_attention:", ba) + 2),
                        "set": {"vars.dcp_ctx": 0}}],
              "else": [{"title": "Max per-rank context = ceil(L / (N*I)) * I, then AOT metadata for the non-causal context pass",
                        "source": C(FA, ln(FA, r"num_partitions = self.dcp_world_size \* self.cp_kv_cache_interleave_size", ba), ln(FA, r"max_num_splits=max_num_splits,", ln(FA, r"num_partitions = self.dcp_world_size", ba))),
                        "set": {"vars.dcp_ctx": f"= ({MD}.max_seq_len + input.dcp_world_size - 1) / input.dcp_world_size"}},
                       {"when": "vars.aot", "call": "flash-attn-interface.get-scheduler-metadata", "source": C(FA, ln(FA, r"return get_scheduler_metadata\(", ga)),
                        "title": "FA3 AOT scheduler metadata (DCP context)",
                        "input": {"shape": {"num_tokens": f"= {MD}.num_actual_tokens", "num_seqs": f"= {MD}.num_reqs", "kv_tokens": "= vars.dcp_ctx"}, "causal": False}},
                       {"set": {"vars.sched": "= vars.aot"}}]}],
         "else": [
             {"when": "vars.aot", "title": "FA3 AOT scheduler metadata for this batch", "source": C(FA, ln(FA, r"return get_scheduler_metadata\(", ga)),
              "call": "flash-attn-interface.get-scheduler-metadata",
              "input": {"shape": {"num_tokens": f"= {MD}.num_actual_tokens", "num_seqs": f"= {MD}.num_reqs", "kv_tokens": f"= sum({MD}.seq_lens)",
                                  "max_query_len": f"= {MD}.max_query_len"}, "causal": f"= {MD}.causal"}},
             {"set": {"vars.sched": "= vars.aot"}}]},
        {"if": f"{MD}.causal_is_tensor && {MD}.causal_tensor_dtype != 'int32'",
         "then": [{"title": "Per-request causal tensor must be int32", "source": C(FA, ln(FA, r"if isinstance\(causal, torch.Tensor\) and causal.dtype", ba)),
                   "fail": {"code": "value-error", "message": "= 'Per-request causal tensor must be int32, got torch.' + " + MD + ".causal_tensor_dtype + '. Casting here would allocate a fresh tensor each build() and break FULL CUDA graph replay; allocate the buffer as int32.'"}}]},
        {"title": "FlashAttentionMetadata", "source": C(FA, ln(FA, r"attn_metadata = FlashAttentionMetadata\(", ba)),
         "return": {"num_actual_tokens": f"= {MD}.num_actual_tokens", "num_reqs": f"= {MD}.num_reqs",
                    "max_query_len": f"= {MD}.max_query_len", "max_seq_len": f"= {MD}.max_seq_len",
                    "seq_lens": f"= {MD}.seq_lens", "block_table": f"= {MD}.block_table", "slot_mapping": f"= {MD}.slot_mapping",
                    "causal": f"= {MD}.causal", "causal_is_tensor": f"= {MD}.causal_is_tensor",
                    "has_scheduler_metadata": "= vars.sched", "max_num_splits": "= vars.splits",
                    "max_dcp_context_kv_len": "= vars.dcp_ctx", "num_decode_reqs": "= vars.ndec", "num_prefill_reqs": "= vars.npre"}},
    ]
    out.append(iface("flash-attention-metadata-builder", "build",
                     "FlashAttentionMetadataBuilder.build: turn the runner's CommonAttentionMetadata into FlashAttentionMetadata; the block table passes through from the SchedulerOutput.",
                     [C(FA, ba, bb), C(FA, ga, gb)], beh, request="AttnFlashBuildRequest", response="AttnFlashMetadata",
                     errors=[err("value-error", "per-request causal tensor is not int32")]))

    # ---- FlashAttentionImpl.forward
    fa_, fb_ = fn(FA, "forward", ln(FA, r"^class FlashAttentionImpl"))
    ea, eb = fn(FA, "_forward_encoder_attention")
    varlen = "flash-attn-interface.flash-attn-varlen-func"
    beh = [
        {"if": "input.has_output_scale || input.has_output_block_scale",
         "then": [{"title": "Fused output quantization unsupported", "source": C(FA, ln(FA, r"if output_scale is not None or output_block_scale is not None:", fa_)),
                   "fail": {"code": "not-implemented-error", "message": "fused output quantization is not yet supported for FlashAttentionImpl"}}]},
        {"if": "input.profiling_run",
         "then": [{"title": "Profiling run (attn_metadata is None): the output is zero-filled, no kernel runs", "source": C(FA, ln(FA, r"if attn_metadata is None:", fa_), ln(FA, r"if attn_metadata is None:", fa_) + 2),
                   "return": {"path": "profiling", "num_tokens": 0}}]},
        {"set": {"vars.shape": SHAPE_FROM_FWD}},
        {"if": "input.attn_type == 'encoder_only' || input.attn_type == 'encoder'",
         "then": [
             {"if": f"{QUANT}", "then": [{"title": "Quantized KV is not supported for encoder attention", "source": C(FA, ln(FA, r"if is_quantized_kv_cache\(self.kv_cache_dtype\):", ea)),
                                          "fail": {"code": "not-implemented-error", "message": "quantization is not supported for encoder attention"}}]},
             {"title": "Encoder attention: bidirectional varlen over the batch's own Q/K/V, no KV cache", "source": C(FA, ln(FA, r"flash_attn_varlen_func\(", ea)),
              "call": varlen, "input": {"shape": "= vars.shape", "fa_version": "= input.fa_version", "paged": False, "causal": False,
                                        "has_alibi": "= input.has_alibi", "has_sinks": "= input.has_sinks"}, "as": "fa"},
             {"return": {"path": "encoder", "num_tokens": "= input.num_tokens", "fa_version": "= vars.fa.value.fa_version"}}]},
        {"if": "input.dcp_world_size > 1",
         "then": [{"title": "Decode context parallel: context attention per rank, LSE combine, then merge with the new tokens' attention",
                   "source": C(FA, ln(FA, r"if self.dcp_world_size > 1:", fa_)),
                   "call": "flash-attention-impl.forward-with-dcp", "input": "= input", "as": "dcp"},
                  {"return": {"path": "dcp", "num_tokens": "= input.num_tokens", "via": "= has(vars.dcp.value.via) ? vars.dcp.value.via : 'none'"}}]},
        {"set": {"vars.qkv": f"= {QUANT}"}},
        {"if": "vars.qkv",
         "then": [{"title": "Quantized KV: the cache is viewed as the platform's fp8 dtype (the attention layer already quantized the queries)",
                   "source": C(FA, ln(FA, r"if is_quantized_kv_cache\(self\.kv_cache_dtype\):", fa_), ln(FA, r"value_cache = value_cache\.view\(current_platform\.fp8_dtype\(\)\)", fa_))}]},
        {"title": "k/v descales are the layer's _k_scale/_v_scale expanded to (num_seqs, num_kv_heads); q_descale only when the impl takes quantized queries (not FA4's SM90 fp8-KV dequant path)",
         "source": C(FA, ln(FA, r"descale_shape = \(", fa_), ln(FA, r"v_descale = layer\._v_scale\.expand\(descale_shape\)", fa_)),
         "set": {"vars.q_descale": "= !(input.fa_version == 4 && input.device_capability_major == 9 && input.kv_cache_dtype in ['fp8', 'fp8_e4m3'])"}},
        {"if": "input.metadata.causal_is_tensor && input.fa_version != 4",
         "then": [{"title": "Per-sequence causal needs FA4", "source": C(FA, ln(FA, r"if self.vllm_flash_attn_version != 4:", fa_)),
                   "fail": {"code": "not-implemented-error", "message": "= 'Per-sequence causal requires FA4. Current version: FA' + string(input.fa_version)"}}]},
        {"title": "Paged varlen FlashAttention over the KV cache (through the FA4 dense-kernel wrapper, which forwards to flash_attn_varlen_func)",
         "source": C(FA, ln(FA, r"_FA4_DENSE_ATTENTION_KERNEL\(", fa_)),
         "call": varlen, "input": {"shape": "= vars.shape", "fa_version": "= input.fa_version", "paged": True,
                                   "causal": "= input.metadata.causal", "has_scheduler_metadata": "= input.metadata.has_scheduler_metadata",
                                   "has_descale": True, "num_splits": "= input.metadata.max_num_splits",
                                   "has_alibi": "= input.has_alibi", "has_sinks": "= input.has_sinks"}, "as": "fa"},
        {"return": {"path": "paged", "num_tokens": "= input.num_tokens", "fa_version": "= vars.fa.value.fa_version", "kv_cache_dtype": "= input.kv_cache_dtype",
                    "kv_cache_view": "= vars.qkv ? 'fp8' : 'model'", "q_descale": "= vars.q_descale"}},
    ]
    out.append(iface("flash-attention-impl", "forward",
                     "FlashAttentionImpl.forward: profiling, encoder, DCP and paged-decoder paths over the KV cache the block table addresses.",
                     [C(FA, fa_, fb_), C(FA, ea, eb)], beh, request="AttnForwardRequest",
                     response={"type": "object", "properties": {"path": {"type": "string"}, "num_tokens": {"type": "integer"}}},
                     errors=[err("not-implemented-error", "fused output quant, encoder quant KV, or per-seq causal without FA4")]))

    # ---- _forward_with_dcp
    da, db = fn(FA, "_forward_with_dcp")
    beh = [
        {"if": "input.metadata.max_dcp_context_kv_len == 0",
         "then": [{"title": "No context on any rank: plain varlen over the new tokens", "source": C(FA, ln(FA, r"if attn_metadata.max_dcp_context_kv_len == 0:", da)),
                   "call": varlen, "input": {"shape": SHAPE_FROM_FWD, "fa_version": "= input.fa_version", "paged": False, "causal": "= input.metadata.causal", "return_lse": True}},
                  {"return": {"path": "dcp-no-context", "via": "none"}}]},
        {"title": "All-gather the query heads across the DCP group", "source": C(FA, ln(FA, r"query_across_dcp = get_dcp_group\(\).all_gather", da)),
         "call": "group-coordinator.all-gather", "input": {"num_tokens": "= input.num_tokens", "world_size": "= input.dcp_world_size", "group_name": "dcp:0", "ranks": "= lists.range(input.dcp_world_size).map(r, 'rank' + string(r))", "dim": 1}},
        {"title": "Context attention over this rank's KV shard (non-causal), returning LSE", "source": C(FA, ln(FA, r"context_attn_out, context_lse = flash_attn_varlen_func\(", da)),
         "call": varlen, "input": {"shape": SHAPE_FROM_FWD, "fa_version": "= input.fa_version", "paged": True, "causal": False, "return_lse": True,
                                   "has_scheduler_metadata": "= input.metadata.has_scheduler_metadata"}},
        {"if": "config['dcp-comm-backend'] == 'a2a'",
         "then": [{"title": "dcp_combine = dcp_a2a_lse_reduce (dcp_comm_backend a2a)", "source": C(FA, ln(FA, r"self.dcp_combine = dcp_a2a_lse_reduce if dcp_a2a else cp_lse_ag_out_rs")),
                   "call": "dcp.dcp-a2a-lse-reduce", "input": {"world_size": "= input.dcp_world_size", "num_heads": "= input.num_heads * input.dcp_world_size", "shape": SHAPE_FROM_FWD}, "as": "comb"}],
         "else": [{"title": "dcp_combine = cp_lse_ag_out_rs (default ag_rs)", "source": C(FA, ln(FA, r"context_attn_out_cor, context_lse_cor = self.dcp_combine\(", da)),
                   "call": "dcp.cp-lse-ag-out-rs", "input": {"world_size": "= input.dcp_world_size", "shape": SHAPE_FROM_FWD}, "as": "comb"}]},
        {"title": "Causal attention of the new tokens over themselves, returning LSE", "source": C(FA, ln(FA, r"query_attn_out, query_lse = flash_attn_varlen_func\(", da)),
         "call": varlen, "input": {"shape": SHAPE_FROM_FWD, "fa_version": "= input.fa_version", "paged": False, "causal": True, "return_lse": True}},
        {"title": "Merge context and query partial outputs by LSE", "source": C(FA, ln(FA, r"        merge_attn_states\(", da)),
         "call": "merge-attn-states.merge-attn-states", "input": {"platform": "cuda", "dtype": "bfloat16", "output_dtype": "bfloat16",
                                                                   "head_size": "= input.head_size", "num_tokens": "= input.num_tokens", "num_heads": "= input.num_heads"}, "fill": True},
        {"return": {"path": "dcp", "via": "= vars.comb.value.via"}},
    ]
    out.append(iface("flash-attention-impl", "forward-with-dcp",
                     "FlashAttentionImpl._forward_with_dcp: decode-context-parallel attention (query all-gather, per-shard context attention, LSE combine, merge).",
                     [C(FA, da, db)], beh, request="AttnForwardRequest"))

    # ---- do_kv_cache_update
    ka, kb = fn(FA, "do_kv_cache_update", ln(FA, r"^class FlashAttentionImpl"))
    beh = [
        {"if": "input.attn_type == 'encoder_only' || input.attn_type == 'encoder'",
         "then": [{"title": "Encoder attention keeps no KV cache", "source": C(FA, ln(FA, r"if self.attn_type in \(AttentionType.ENCODER_ONLY, AttentionType.ENCODER\):", ka)),
                   "return": {"written_tokens": 0}}]},
        {"title": "The op is given the impl's kv_cache_dtype (CacheConfig.cache_dtype) and the layer's _k_scale/_v_scale: an fp8 cache stores each K/V element as one scaled fp8 byte, otherwise in the model dtype",
         "source": C(FA, ln(FA, r"            self\.kv_cache_dtype,", ka), ln(FA, r"            layer\._v_scale,", ka)),
         "set": {"vars.fp8": "= input.kv_cache_dtype.startsWith('fp8')"}},
        {"title": "Scatter the new K/V into the paged cache at slot_mapping (reshape_and_cache_flash; padded slots are skipped by the op)",
         "source": C(FA, ln(FA, r"reshape_and_cache_flash\(", ka)),
         "call": "custom-ops.reshape-and-cache-flash", "input": {"num_tokens": "= size(input.slot_mapping)", "hidden_size": "= 2 * input.num_kv_heads * input.head_size", "dtype_bytes": 2}},
        {"return": {"written_tokens": "= input.slot_mapping.filter(s, s >= 0).size()", "kv_cache_dtype": "= input.kv_cache_dtype",
                    "cache_bytes_per_element": "= vars.fp8 ? 1 : 2", "scaled": "= vars.fp8"}},
    ]
    out.append(iface("flash-attention-impl", "do-kv-cache-update",
                     "FlashAttentionImpl.do_kv_cache_update: write this step's K/V into the KV cache blocks the scheduler assigned (via slot_mapping).",
                     [C(FA, ka, kb)], beh, request="AttnKvUpdateRequest",
                     response={"type": "object", "properties": {"written_tokens": {"type": "integer"}, "kv_cache_dtype": {"type": "string"},
                                                                "cache_bytes_per_element": {"type": "integer"}, "scaled": {"type": "boolean"}}}))
    return out


def fa_interface_module():
    out = []
    va, vb = fn(FAI, "flash_attn_varlen_func")
    sa, sb = fn(FAI, "get_scheduler_metadata")
    spa, spb = fn(FAI, "sparse_attn_func")
    sva, svb = fn(FAI, "sparse_attn_varlen_func")
    for n in ("flash_attn_varlen_func", "get_scheduler_metadata", "sparse_attn_func", "sparse_attn_varlen_func"):
        mark(FAI, n)
    k = "flash-attn-interface."
    out.append(op_kernel("flash-attn-interface", "vllm-fa2-varlen-fwd", C(FAI, ln(FAI, r"torch.ops._vllm_fa2_C.varlen_fwd\(")), "FA2 varlen forward kernel (_vllm_fa2_C.varlen_fwd).", "_vllm_fa2_C::varlen_fwd"))
    out.append(op_kernel("flash-attn-interface", "vllm-fa3-fwd", C(FAI, ln(FAI, r"torch.ops._vllm_fa3_C.fwd\(")), "FA3 (Hopper) forward kernel (_vllm_fa3_C.fwd).", "_vllm_fa3_C::fwd"))
    out.append(op_kernel("flash-attn-interface", "flash-attn-cute-fwd", C(FAI, ln(FAI, r"out, softmax_lse, _, _ = _flash_attn_fwd\(")), "FA4 CuTe-DSL forward (_flash_attn_fwd).", "flash_attn.cute._flash_attn_fwd", lang="cute-dsl"))
    out.append(op_kernel("flash-attn-interface", "vllm-fa3-get-scheduler-metadata", C(FAI, ln(FAI, r"torch.ops._vllm_fa3_C.get_scheduler_metadata\(")), "FA3 AOT tile-scheduler metadata kernel.", "_vllm_fa3_C::get_scheduler_metadata", lat=LAT_META))
    out.append(op_kernel("flash-attn-interface", "vllm-fa2-fwd-sparse", C(FAI, ln(FAI, r"torch.ops._vllm_fa2_C.fwd_sparse\(")), "FA2 block-sparse forward (_vllm_fa2_C.fwd_sparse).", "_vllm_fa2_C::fwd_sparse"))
    out.append(op_kernel("flash-attn-interface", "vllm-fa2-varlen-fwd-sparse", C(FAI, ln(FAI, r"torch.ops._vllm_fa2_C.varlen_fwd_sparse\(")), "FA2 varlen block-sparse forward (_vllm_fa2_C.varlen_fwd_sparse).", "_vllm_fa2_C::varlen_fwd_sparse"))
    fa2 = ln(FAI, r"if fa_version == 2:", va)
    beh = [
        {"if": "input.fa_version == 2",
         "then": [
             {"if": "input.has_scheduler_metadata && input.has_descale", "then": [{"title": "FA2 refuses scheduler metadata with descales", "source": C(FAI, ln(FAI, r"FA2 does not support scheduler_metadata", va) - 1),
                                                                                   "fail": {"code": "not-implemented-error", "message": "FA2 does not support scheduler_metadata, q_descale, k_descale, v_descale"}}]},
             {"if": "input.has_sinks", "then": [{"title": "FA2 has no sinks", "source": C(FAI, ln(FAI, r"FA2 does not support s_aux", va)),
                                                 "fail": {"code": "not-implemented-error", "message": "FA2 does not support s_aux"}}]},
             {"if": "input.num_splits > 1", "then": [{"title": "FA2 has no split-KV", "source": C(FAI, ln(FAI, r"FA2 does not support num_splits > 1", va)),
                                                     "fail": {"code": "not-implemented-error", "message": "FA2 does not support num_splits > 1"}}]},
             {"title": "Launch the FA2 varlen kernel", "source": C(FAI, ln(FAI, r"torch.ops._vllm_fa2_C.varlen_fwd\(", va)), "call": k + "vllm-fa2-varlen-fwd", "input": SHAPE, "fill": True},
             {"return": {"fa_version": 2, "lse": "= input.return_lse"}}]},
        {"if": "input.fa_version == 3",
         "then": [
             {"if": "input.has_alibi", "then": [{"title": "Alibi is not supported in FA3", "source": C(FAI, ln(FAI, r"Alibi is not supported in FA3", va)),
                                                 "fail": {"code": "assertion-error", "message": "Alibi is not supported in FA3"}}]},
             {"title": "Launch the FA3 kernel (uses the AOT scheduler metadata when given)", "source": C(FAI, ln(FAI, r"torch.ops._vllm_fa3_C.fwd\(", va)), "call": k + "vllm-fa3-fwd", "input": SHAPE, "fill": True},
             {"return": {"fa_version": 3, "lse": "= input.return_lse"}}]},
        {"if": "input.fa_version == 4",
         "then": [
             {"if": "input.has_alibi", "then": [{"title": "Alibi is not supported in FA4", "source": C(FAI, ln(FAI, r"Alibi is not supported in FA4", va)),
                                                 "fail": {"code": "assertion-error", "message": "Alibi is not supported in FA4"}}]},
             {"title": "Launch the FA4 CuTe kernel", "source": C(FAI, ln(FAI, r"out, softmax_lse, _, _ = _flash_attn_fwd\(", va)), "call": k + "flash-attn-cute-fwd", "input": SHAPE, "fill": True},
             {"return": {"fa_version": 4, "lse": "= input.return_lse"}}]},
        {"title": "Unsupported FA version", "source": C(FAI, ln(FAI, r"raise ValueError\(f\"Unsupported FA version: \{fa_version\}\"\)", va)),
         "fail": {"code": "value-error", "message": "= 'Unsupported FA version: ' + string(input.fa_version)"}},
    ]
    req = {"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "fa_version": I(3), "paged": B(True), "causal": B(True),
                                             "has_scheduler_metadata": B(False), "has_descale": B(False), "num_splits": I(0),
                                             "has_alibi": B(False), "has_sinks": B(False), "return_lse": B(False)}}
    out.append(iface("flash-attn-interface", "flash-attn-varlen-func",
                     "flash_attn_varlen_func: validate the arguments for the requested FA version and launch the FA2, FA3 or FA4 kernel.",
                     [C(FAI, va, vb)], beh, request=req,
                     response={"type": "object", "properties": {"fa_version": {"type": "integer"}, "lse": {"type": "boolean"}}},
                     errors=[err("not-implemented-error", "an option the chosen FA version lacks"), err("assertion-error", "ALiBi on FA3/FA4"),
                             err("value-error", "unknown FA version")]))
    out.append(iface("flash-attn-interface", "get-scheduler-metadata",
                     "get_scheduler_metadata (FA3 only): precompute the tile scheduler's metadata for a batch.",
                     [C(FAI, sa, sb)],
                     [{"title": "Precompute FA3 tile-scheduler metadata", "source": C(FAI, ln(FAI, r"torch.ops._vllm_fa3_C.get_scheduler_metadata\(", sa)),
                       "call": k + "vllm-fa3-get-scheduler-metadata", "input": SHAPE, "fill": True},
                      {"return": {"scheduler_metadata": True}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "causal": B(True)}},
                     response={"type": "object", "properties": {"scheduler_metadata": {"type": "boolean"}}}))
    for nm, (a, b), opk, summ in [("sparse-attn-func", (spa, spb), "vllm-fa2-fwd-sparse", "sparse_attn_func: FA2 block-sparse attention (vertical + slash patterns)"),
                                  ("sparse-attn-varlen-func", (sva, svb), "vllm-fa2-varlen-fwd-sparse", "sparse_attn_varlen_func: FA2 varlen block-sparse attention")]:
        out.append(iface("flash-attn-interface", nm, summ + "; softmax_scale defaults to head_size^-0.5.",
                         [C(FAI, a, b)],
                         [{"if": "input.softmax_scale == null", "then": [{"title": "Default softmax scale", "source": C(FAI, ln(FAI, r"softmax_scale = q.shape\[-1\] \*\* \(-0.5\)", a)),
                                                                           "set": {"vars.scale": "= 1.0 / math.sqrt(double(input.shape.head_size))"}}],
                           "else": [{"set": {"vars.scale": "= input.softmax_scale"}}]},
                          {"title": "Launch the FA2 sparse kernel", "source": C(FAI, ln(FAI, r"torch.ops._vllm_fa2_C\.", a)), "call": k + opk, "input": SHAPE, "fill": True},
                          {"return": {"softmax_scale": "= vars.scale", "lse": "= input.return_softmax_lse"}}],
                         request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "softmax_scale": {"type": ["number", "null"], "default": None},
                                                                   "return_softmax_lse": B(False)}},
                         response={"type": "object", "properties": {"softmax_scale": {"type": "number"}, "lse": {"type": "boolean"}}}))
    return out


def merge_interfaces():
    out = []
    ma, mb = fn(MAS, "merge_attn_states")
    ta, tb = fn(MAS, "_merge_attn_states_torch")
    mark(MASCU, "merge_attn_states_kernel")
    beh = [
        {"if": "!input.head_strides_match",
         "then": [{"title": "Prefix and suffix outputs must share head strides", "source": C(MAS, ln(MAS, r"assert prefix_output.stride\(1\) == suffix_output.stride\(1\)", ma)),
                   "fail": {"code": "assertion-error", "message": "= 'merge_attn_states requires prefix_output and suffix_output to have matching head strides, got ' + string(input.prefix_head_stride) + ' and ' + string(input.suffix_head_stride)"}}]},
        {"if": "!(input.output_dtype in ['float32', 'float16', 'bfloat16']) && !input.has_output_scale",
         "then": [{"title": "A quantized output needs output_scale", "source": C(MAS, ln(MAS, r"if output.dtype not in \(torch.float32, torch.half, torch.bfloat16\):", ma)),
                   "fail": {"code": "assertion-error", "message": "= 'output_scale is required when output is torch.' + input.output_dtype"}}]},
        {"set": {"vars.platform_ok": "= input.platform == 'cuda' || (input.platform == 'rocm' && input.cdna_version >= 3)",
                 "vars.dtype_ok": "= input.dtype in ['float32', 'float16', 'bfloat16']",
                 "vars.head_ok": "= input.dtype == 'float32' ? input.head_size % 4 == 0 : input.head_size % 8 == 0"}},
        {"if": "vars.platform_ok && vars.dtype_ok && vars.head_ok",
         "then": [{"title": "CUDA op _C::merge_attn_states", "source": C(MAS, ln(MAS, r"return merge_attn_states\(", ma)),
                   "call": "custom-ops.merge-attn-states", "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= input.num_heads * input.head_size", "dtype_bytes": 2}},
                  {"title": "merge_attn_states_launcher launches merge_attn_states_kernel (one thread per packed head chunk)", "source": Cinv(MASCU, "merge_attn_states_kernel")},
                  {"return": {"impl": "cuda"}}]},
        {"if": "input.platform == 'cpu'",
         "then": [{"title": "CPU: torch LSE merge", "source": C(MAS, ta, tb),
                   "set": {"vars.merged": "= input.prefill_tokens_with_context == null ? input.num_tokens : input.prefill_tokens_with_context"}},
                  {"return": {"impl": "torch", "merged_tokens": "= vars.merged"}}]},
        {"title": "Otherwise the Triton kernel", "source": C(MAS, ln(MAS, r"from vllm.v1.attention.ops.triton_merge_attn_states import", ma)),
         "call": "triton-merge-attn-states.merge-attn-states", "input": "= input"},
        {"return": {"impl": "triton"}},
    ]
    out.append(iface("merge-attn-states", "merge-attn-states",
                     "merge_attn_states: combine prefix (KV cache) and suffix (new tokens) partial outputs by log-sum-exp; CUDA op when platform, dtype and head size allow, torch on CPU, else Triton.",
                     [C(MAS, ma, mb)], beh, request="AttnMergeRequest",
                     response={"type": "object", "properties": {"impl": {"type": "string"}, "merged_tokens": {"type": "integer"}}},
                     errors=[err("assertion-error", "mismatched head strides, or quantized output without a scale")]))
    out.append(kernel("triton-merge-attn-states", "merge-attn-states-kernel", TMAS, "merge_attn_states_kernel", "Triton LSE merge kernel, grid (num_tokens, num_heads)."))
    a, b = fn(TMAS, "merge_attn_states")
    out.append(iface("triton-merge-attn-states", "merge-attn-states",
                     "Triton merge_attn_states: tokens past prefill_tokens_with_context copy the suffix; the rest are LSE-weighted.",
                     [C(TMAS, a, b)],
                     [{"if": "input.prefill_tokens_with_context == null", "then": [{"title": "Every token has context", "source": C(TMAS, ln(TMAS, r"if prefill_tokens_with_context is None:", a)),
                                                                                     "set": {"vars.ctx": "= input.num_tokens"}}],
                       "else": [{"set": {"vars.ctx": "= input.prefill_tokens_with_context"}}]},
                      {"title": "Launch merge_attn_states_kernel over (num_tokens, num_heads)", "source": C(TMAS, ln(TMAS, r"merge_attn_states_kernel\[", a)),
                       "call": "triton-merge-attn-states.merge-attn-states-kernel",
                       "input": {"num_tokens": "= input.num_tokens", "num_heads": "= input.num_heads", "head_size": "= input.head_size"}, "fill": True},
                      {"return": {"merged_tokens": "= vars.ctx"}}],
                     request="AttnMergeRequest", response={"type": "object", "properties": {"merged_tokens": {"type": "integer"}}}))
    return out


HELPERS = [
    ("resolve_seq_and_query_len", "resolve_seq_and_query_len: find this program's sequence and its query length"),
    ("find_seq_idx", "find_seq_idx: binary search of query_start_loc"),
    ("init_softmax_M", "init_softmax_M: initial running max (sink-aware)"),
    ("compute_tile_loop_bounds", "compute_tile_loop_bounds: KV tile range (causal, sliding window, segment)"),
    ("cdiv_fn", "cdiv_fn: ceiling division"),
    ("compute_kv_seq_mask", "compute_kv_seq_mask: causal / window / mm-prefix / R-SWA mask"),
    ("apply_softcap", "apply_softcap: tanh soft-capping of scores"),
    ("apply_alibi_to_score", "apply_alibi_to_score: ALiBi bias"),
    ("load_qq_bias_tile", "load_qq_bias_tile: query-query bias tile"),
    ("softmax_step", "softmax_step: online softmax update"),
    ("store_segm_reduce_scalars", "store_segm_reduce_scalars: per-segment max/expsum for the 3D path"),
]


def triton_interfaces():
    out = []
    # kernels
    out.append(kernel("triton-unified-attention", "kernel-unified-attention", TUA, "kernel_unified_attention",
                      "kernel_unified_attention: paged attention for any mix of prefill and decode; 2D grid (q blocks, kv heads) or 3D with softmax segments."))
    out.append(kernel("triton-unified-attention", "reduce-segments", TUA, "reduce_segments", "reduce_segments: combine the 3D path's per-segment partial softmax results.", lat=LAT_META))
    out.append(kernel("triton-reshape-and-cache-flash", "reshape-and-cache-kernel-flash", TRC, "reshape_and_cache_kernel_flash", "Triton KV cache writer (one program per token; negative slots skipped)."))
    out.append(kernel("triton-reshape-and-cache-flash", "reshape-cache-per-token-head", TRC, "_reshape_cache_per_token_head", "Per-token-head quantizing KV writer (INT8/FP8 + fp32 scale per head)."))
    out.append(kernel("triton-reshape-and-cache-flash", "reshape-and-cache-kernel-flash-diffkv", TRC, "reshape_and_cache_kernel_flash_diffkv", "KV writer for caches whose K and V head sizes differ."))
    out.append(kernel("triton-prefill-attention", "fwd-kernel", TPA, "_fwd_kernel", "context_attention_fwd kernel: non-paged prefill attention with optional sliding window and sinks."))
    out.append(kernel("int4-per-token-head", "reshape-cache-int4-kernel", I4, "_reshape_cache_int4_kernel", "INT4 packing KV writer (per token, per KV head)."))
    out.append(kernel("int4-per-token-head", "attn-packed", I4, "_attn_packed", "Packed INT4 paged attention (2D or 3D segments)."))
    out.append(kernel("int4-per-token-head", "hadamard-mma-kernel", I4, "_hadamard_mma_kernel", "Triton MMA Walsh-Hadamard transform.", lat=LAT_META))

    # metadata builder
    ba, bb = fn(TA, "build", ln(TA, r"^class TritonAttentionMetadataBuilder"))
    ia = ln(TA, r"self.seq_threshold_3D = MIN_LAUNCH_GRID_SIZE_2D // self.num_heads_kv")
    beh = [
        {"title": "seq_threshold_3D = MIN_LAUNCH_GRID_SIZE_2D (128) // num_kv_heads, snapped to the nearest CUDA-graph capture size",
         "source": C(TA, ia, ln(TA, r"key=lambda x: abs\(x - self.seq_threshold_3D\)")),
         "set": {"vars.t": "= 128 / input.num_kv_heads"}},
        {"if": "input.cudagraph_capture_sizes.size() > 0",
         "then": [{"set": {"vars.dmin": "= math.least(input.cudagraph_capture_sizes.map(x, x > vars.t ? x - vars.t : vars.t - x))"}},
                  {"set": {"vars.t": "= input.cudagraph_capture_sizes.filter(x, (x > vars.t ? x - vars.t : vars.t - x) == vars.dmin)[0]"}}]},
        {"title": "TritonAttentionMetadata with the 3D threshold and 16 softmax segments", "source": C(TA, ln(TA, r"attn_metadata = TritonAttentionMetadata\(", ba)),
         "return": {"num_actual_tokens": f"= {MD}.num_actual_tokens", "num_reqs": f"= {MD}.num_reqs", "max_query_len": f"= {MD}.max_query_len",
                    "max_seq_len": f"= {MD}.max_seq_len", "seq_lens": f"= {MD}.seq_lens", "block_table": f"= {MD}.block_table",
                    "slot_mapping": f"= {MD}.slot_mapping", "causal": f"= {MD}.causal", "seq_threshold_3D": "= vars.t", "num_par_softmax_segments": 16}},
    ]
    out.append(iface("triton-attention-metadata-builder", "build",
                     "TritonAttentionMetadataBuilder.build: pass the batch through and attach the 2D/3D decision inputs.",
                     [C(TA, ba, bb), C(TA, ia)], beh,
                     request={"type": "object", "properties": {"common": {"$ref": "AttnCommonMetadata"}, "num_kv_heads": I(8),
                                                               "cudagraph_capture_sizes": {"type": "array", "items": {"type": "integer"}, "default": [1, 2, 4, 8, 16, 24, 32]}}},
                     response={"type": "object", "properties": {"seq_threshold_3D": {"type": "integer"}, "num_par_softmax_segments": {"type": "integer"}}}))

    # unified_attention
    ua, ub = fn(TUA, "unified_attention")
    beh = [
        {"if": "input.kv_quant_mode == 'int4_per_token_head'",
         "then": [{"title": "INT4 per-token-head cache: dispatch to the packed INT4 kernel", "source": C(TUA, ln(TUA, r"if kv_quant_mode == KVQuantMode.INT4_PER_TOKEN_HEAD:", ua)),
                   "call": "int4-per-token-head.unified-attention-int4", "input": "= input"},
                  {"return": {"kernel": "int4", "use_3d": False}}]},
        {"set": {"vars.use_3d": "= input.has_segm_buffers && input.max_seqlen_q <= 1 && input.num_seqs <= input.seq_threshold_3D && !input.batch_invariant"}},
        {"title": "3D (segmented softmax) only for pure decode batches no larger than seq_threshold_3D, never under batch invariance",
         "source": C(TUA, ln(TUA, r"use_3d = not \(", ua), ln(TUA, r"or is_batch_invariant", ua) + 1)},
        helper(TUA, "_cast_kv_tile", "the kernel inlines _cast_kv_tile (dequantize FP8 / per-token-head KV tiles)"),
        helper(TUA, "_load_q_td", "the kernel inlines _load_q_td (tensor-descriptor query loads when use_td)"),
        helper(TUA, "_load_kv_tile_td", "the kernel inlines _load_kv_tile_td (tensor-descriptor KV tile loads)"),
        helper(TUA, "_store_output_td", "the kernel inlines _store_output_td (tensor-descriptor output stores)"),
        *[helper(TAH, n, "the kernel inlines " + t) for n, t in HELPERS],
        {"title": "Launch kernel_unified_attention (grid: q blocks x kv heads, x segments when 3D)", "source": C(TUA, ln(TUA, r"kernel_unified_attention\[grid\]\(", ua)),
         "call": "triton-unified-attention.kernel-unified-attention", "input": SHAPE, "fill": True},
        {"if": "vars.use_3d",
         "then": [{"title": "Reduce the softmax segments", "source": C(TUA, ln(TUA, r"reduce_segments\[\(q.shape\[0\], num_query_heads\)\]\(", ua)),
                   "call": "triton-unified-attention.reduce-segments", "input": SHAPE, "fill": True}]},
        {"return": {"kernel": "unified", "use_3d": "= vars.use_3d"}},
    ]
    ureq = {"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "kv_quant_mode": S("none"), "max_seqlen_q": I(1),
                                              "num_seqs": I(2), "seq_threshold_3D": I(16), "has_segm_buffers": B(True), "batch_invariant": B(False)}}
    out.append(iface("triton-unified-attention", "unified-attention",
                     "unified_attention: choose the INT4 packed path, or the unified kernel in 2D (prefill/mixed/large decode) or 3D segmented-softmax mode (small decode batches).",
                     [C(TUA, ua, ub)], beh, request=ureq,
                     response={"type": "object", "properties": {"kernel": {"type": "string"}, "use_3d": {"type": "boolean"}}}))

    # TritonAttentionImpl.forward
    fa_, fb_ = fn(TA, "forward", ln(TA, r"^class TritonAttentionImpl"))
    ea, eb = fn(TA, "_forward_encoder_attention")
    beh = [
        {"if": "input.has_output_block_scale",
         "then": [{"title": "Fused block-scale output quant unsupported", "source": C(TA, ln(TA, r"if output_block_scale is not None:", fa_)),
                   "fail": {"code": "not-implemented-error", "message": "fused block_scale output quantization is not yet supported for TritonAttentionImpl"}}]},
        {"if": "input.profiling_run",
         "then": [{"title": "Profiling run (attn_metadata is None)", "source": C(TA, ln(TA, r"if attn_metadata is None:", fa_)), "return": {"path": "profiling", "num_tokens": 0}}]},
        {"set": {"vars.shape": SHAPE_FROM_FWD}},
        {"if": "input.attn_type == 'encoder_only' || input.attn_type == 'encoder'",
         "then": [{"if": f"{QUANT}", "then": [{"title": "Quantized KV unsupported for encoder attention", "source": C(TA, ln(TA, r"if is_quantized_kv_cache\(self.kv_cache_dtype\):", ea)),
                                                "fail": {"code": "not-implemented-error", "message": "quantized KV cache is not supported for encoder attention"}}]},
                  {"title": "Encoder: bidirectional context_attention_fwd, no KV cache", "source": C(TA, ln(TA, r"context_attention_fwd\(", ea)),
                   "call": "triton-prefill-attention.context-attention-fwd", "input": {"shape": "= vars.shape", "is_causal": False}},
                  {"return": {"path": "encoder", "num_tokens": "= input.num_tokens"}}]},
        {"title": "Paged unified attention over the KV cache", "source": C(TA, ln(TA, r"unified_attention\(", fa_)),
         "call": "triton-unified-attention.unified-attention",
         "input": {"shape": "= vars.shape", "kv_quant_mode": "= input.kv_quant_mode", "max_seqlen_q": "= input.metadata.max_query_len",
                   "num_seqs": "= input.metadata.num_reqs", "seq_threshold_3D": "= input.metadata.seq_threshold_3D", "has_segm_buffers": True},
         "as": "ua"},
        {"return": {"path": "= vars.ua.value.kernel == 'int4' ? 'paged-int4' : (vars.ua.value.use_3d ? 'paged-3d' : 'paged-2d')", "num_tokens": "= input.num_tokens"}},
    ]
    out.append(iface("triton-attention-impl", "forward",
                     "TritonAttentionImpl.forward: profiling, encoder (context_attention_fwd) and paged (unified_attention) paths.",
                     [C(TA, fa_, fb_), C(TA, ea, eb)], beh, request="AttnForwardRequest",
                     response={"type": "object", "properties": {"path": {"type": "string"}, "num_tokens": {"type": "integer"}}},
                     errors=[err("not-implemented-error", "block-scale output quant, or quantized KV for encoder attention")]))

    # do_kv_cache_update
    ka, kb = fn(TA, "do_kv_cache_update", ln(TA, r"^class TritonAttentionImpl"))
    beh = [
        {"if": "input.attn_type == 'encoder_only' || input.attn_type == 'encoder'",
         "then": [{"title": "Encoder attention keeps no KV cache", "source": C(TA, ln(TA, r"if self.attn_type in \(AttentionType.ENCODER_ONLY, AttentionType.ENCODER\):", ka)), "return": {"path": "none"}}]},
        {"if": "input.kv_quant_mode.endsWith('per_token_head')",
         "then": [{"title": "Per-token-head quantized cache writer", "source": C(TA, ln(TA, r"triton_reshape_and_cache_flash_per_token_head_quant\(", ka)),
                   "call": "triton-reshape-and-cache-flash.triton-reshape-and-cache-flash-per-token-head-quant", "input": "= input", "as": "w"},
                  {"return": {"path": "per-token-head", "writer": "= vars.w.value.path"}}]},
        {"title": "Plain / FP8 per-tensor writer", "source": C(TA, ln(TA, r"triton_reshape_and_cache_flash\(", ka)),
         "call": "triton-reshape-and-cache-flash.triton-reshape-and-cache-flash", "input": "= input"},
        {"return": {"path": "flash"}},
    ]
    out.append(iface("triton-attention-impl", "do-kv-cache-update",
                     "TritonAttentionImpl.do_kv_cache_update: write the step's K/V into the KV cache via the Triton writers.",
                     [C(TA, ka, kb)], beh, request="AttnKvUpdateRequest", response={"type": "object", "properties": {"path": {"type": "string"}}}))

    # triton_reshape_and_cache_flash
    ra, rb = fn(TRC, "triton_reshape_and_cache_flash")
    beh = [
        {"if": "!(input.kv_cache_dtype in ['auto', 'float16', 'bfloat16', 'float32', 'half', 'float'] || " + QUANT + ") || (input.kv_cache_dtype.startsWith('fp8') && input.device_capability_major * 10 + input.device_capability_minor < 89) || (input.kv_cache_dtype == 'bfloat16' && input.device_capability_major < 8)",
         "then": [{"title": "FP8 KV cache needs native fp8e4nv (SM89+)", "source": C(TRC, ln(TRC, r"assert _is_supported_kv_cache_dtype\(kv_cache_dtype\)", ra)),
                   "fail": {"code": "assertion-error", "message": "= 'Triton reshape-and-cache cannot store kv_cache_dtype=' + input.kv_cache_dtype + ' on this device: an FP8 KV cache needs native fp8e4nv (SM89+). Use --kv-cache-dtype bfloat16 (or float16 on SM75).'"}}]},
        {"title": "TILE_SIZE heuristic: <= 2048, capped at 512 below SM90", "source": C(TRC, ln(TRC, r"TILE_SIZE = min\(2048", ra), ln(TRC, r"TILE_SIZE = min\(512, TILE_SIZE\)", ra)),
         "set": {"vars.tile": "= input.device_capability_major < 9 ? 512 : 2048"}},
        {"title": "Launch reshape_and_cache_kernel_flash, one program per slot_mapping entry", "source": C(TRC, ln(TRC, r"reshape_and_cache_kernel_flash\[grid\]\(", ra)),
         "call": "triton-reshape-and-cache-flash.reshape-and-cache-kernel-flash",
         "input": {"num_tokens": "= size(input.slot_mapping)", "num_kv_heads": "= input.num_kv_heads", "head_size": "= input.head_size", "kv_tokens": 0}, "fill": True},
        {"return": {"written_tokens": "= input.slot_mapping.filter(s, s >= 0).size()", "tile_size": "= vars.tile"}},
    ]
    out.append(iface("triton-reshape-and-cache-flash", "triton-reshape-and-cache-flash",
                     "triton_reshape_and_cache_flash: check the KV dtype is storable, then scatter K/V to slot_mapping (padding slots < 0 are skipped in the kernel).",
                     [C(TRC, ra, rb)], beh, request="AttnKvUpdateRequest",
                     response={"type": "object", "properties": {"written_tokens": {"type": "integer"}, "tile_size": {"type": "integer"}}},
                     errors=[err("assertion-error", "FP8 KV cache below SM89")]))
    pa, pb = fn(TRC, "triton_reshape_and_cache_flash_per_token_head_quant")
    beh = [
        {"if": "input.kv_quant_mode == 'int4_per_token_head'",
         "then": [{"title": "INT4: RHT-rotate and pack", "source": C(TRC, ln(TRC, r"if kv_quant_mode == KVQuantMode.INT4_PER_TOKEN_HEAD:", pa)),
                   "call": "int4-per-token-head.reshape-and-cache-int4", "input": "= input"},
                  {"return": {"path": "int4"}}]},
        {"title": "INT8/FP8 per-token-head quantizing writer, grid (num_tokens, num_kv_heads)", "source": C(TRC, ln(TRC, r"_reshape_cache_per_token_head\[", pa)),
         "call": "triton-reshape-and-cache-flash.reshape-cache-per-token-head",
         "input": {"num_tokens": "= size(input.slot_mapping)", "num_kv_heads": "= input.num_kv_heads", "head_size": "= input.head_size", "kv_tokens": 0}, "fill": True},
        {"return": {"path": "= input.kv_quant_mode"}},
    ]
    out.append(iface("triton-reshape-and-cache-flash", "triton-reshape-and-cache-flash-per-token-head-quant",
                     "triton_reshape_and_cache_flash_per_token_head_quant: INT4 goes to the packed writer, INT8/FP8 to the per-head quantizing kernel.",
                     [C(TRC, pa, pb)], beh, request="AttnKvUpdateRequest", response={"type": "object", "properties": {"path": {"type": "string"}}}))
    da, db = fn(TRC, "triton_reshape_and_cache_flash_diffkv")
    out.append(iface("triton-reshape-and-cache-flash", "triton-reshape-and-cache-flash-diffkv",
                     "triton_reshape_and_cache_flash_diffkv: KV writer for a combined cache with different K and V head sizes.",
                     [C(TRC, da, db)],
                     [{"title": "Launch reshape_and_cache_kernel_flash_diffkv", "source": C(TRC, ln(TRC, r"reshape_and_cache_kernel_flash_diffkv\[grid\]\(", da)),
                       "call": "triton-reshape-and-cache-flash.reshape-and-cache-kernel-flash-diffkv",
                       "input": {"num_tokens": "= size(input.slot_mapping)", "kv_tokens": 0}, "fill": True},
                      {"if": "input.slot_mapping.exists(s, s < 0)", "then": [{"title": "Padding slots (< 0) return early inside the kernel", "source": C(TRC, ln(TRC, r"if slot_idx < 0:", ln(TRC, r"def reshape_and_cache_kernel_flash_diffkv"))),
                                                                              "set": {"vars.skipped": "= input.slot_mapping.filter(s, s < 0).size()"}}],
                       "else": [{"set": {"vars.skipped": 0}}]},
                      {"return": {"written_tokens": "= size(input.slot_mapping) - vars.skipped"}}],
                     request="AttnKvUpdateRequest", response={"type": "object", "properties": {"written_tokens": {"type": "integer"}}}))

    # context_attention_fwd (triton_prefill_attention)
    ca, cb = fn(TPA, "context_attention_fwd")
    out.append(iface("triton-prefill-attention", "context-attention-fwd",
                     "context_attention_fwd: non-paged prefill attention; tile 32 for head dims >= 512; grid (batch, heads, q blocks).",
                     [C(TPA, ca, cb)],
                     [{"if": "input.shape.head_size >= 512", "then": [{"title": "Large head dims use BLOCK <= 32", "source": C(TPA, ln(TPA, r"if Lk >= 512:", ca)), "set": {"vars.block": 32}}],
                       "else": [{"set": {"vars.block": 64}}]},
                      {"title": "Launch _fwd_kernel", "source": C(TPA, ln(TPA, r"_fwd_kernel\[grid\]\(", ca)),
                       "call": "triton-prefill-attention.fwd-kernel", "input": SHAPE, "fill": True},
                      {"return": {"block": "= vars.block", "causal": "= input.is_causal"}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "is_causal": B(True)}},
                     response={"type": "object", "properties": {"block": {"type": "integer"}, "causal": {"type": "boolean"}}}))

    # int4
    ra, rb = fn(I4, "reshape_and_cache_int4")
    rka, rkb = fn(I4, "_run_reshape_kernel")
    out.append(iface("int4-per-token-head", "reshape-and-cache-int4",
                     "reshape_and_cache_int4: randomized Hadamard rotation of K and V, then the packing writer.",
                     [C(I4, ra, rb), C(I4, rka, rkb)],
                     [{"title": "Rotate K and V (single_rht -> fast_hadamard_transform)", "source": C(I4, ln(I4, r"key = single_rht\(key.float\(\)\)", ra)),
                       "call": "int4-per-token-head.fast-hadamard-transform", "input": {"d": "= input.head_size", "dtype": "float32", "is_cuda": True}},
                      helper(I4, "pack_int4_nibbles", "the writer inlines pack_int4_nibbles"),
                      {"title": "Launch _reshape_cache_int4_kernel over (num_tokens, num_kv_heads)", "source": C(I4, ln(I4, r"kernel\[\(num_tokens, num_kv_heads\)\]\(", rka)),
                       "call": "int4-per-token-head.reshape-cache-int4-kernel",
                       "input": {"num_tokens": "= size(input.slot_mapping)", "num_kv_heads": "= input.num_kv_heads", "head_size": "= input.head_size", "kv_tokens": 0}, "fill": True},
                      {"return": {"path": "int4"}}],
                     request="AttnKvUpdateRequest", response={"type": "object", "properties": {"path": {"type": "string"}}}))
    ua, ub = fn(I4, "unified_attention_int4")
    la, lb = fn(I4, "_launch_packed_attn")
    out.append(iface("int4-per-token-head", "unified-attention-int4",
                     "unified_attention_int4: rotate Q, scale softmax by the RHT norm, run the packed kernel (2D or 3D) and reduce segments.",
                     [C(I4, ua, ub), C(I4, la, lb)],
                     [{"title": "Rotate Q with the same RHT", "source": C(I4, ln(I4, r"q = single_rht\(q.float\(\)\)", ua)),
                       "call": "int4-per-token-head.fast-hadamard-transform", "input": {"d": "= has(input.shape) ? input.shape.head_size : 128", "dtype": "float32", "is_cuda": True}},
                      {"set": {"vars.use_3d": "= has(input.max_seqlen_q) && input.max_seqlen_q <= 1 && has(input.num_seqs) && has(input.seq_threshold_3D) && input.num_seqs <= input.seq_threshold_3D"}},
                      helper(I4, "unpack_int4_nibbles", "_attn_packed inlines unpack_int4_nibbles"),
                      {"title": "Launch _attn_packed", "source": C(I4, ln(I4, r"_attn_packed\[grid\]\(", la)),
                       "call": "int4-per-token-head.attn-packed", "input": SHAPE, "fill": True},
                      {"if": "vars.use_3d", "then": [{"title": "Reduce segments (shared reduce_segments kernel)", "source": C(I4, ln(I4, r"reduce_segments\[\(q.shape\[0\], num_query_heads\)\]", la)),
                                                      "call": "triton-unified-attention.reduce-segments", "input": SHAPE, "fill": True}]},
                      {"return": {"use_3d": "= vars.use_3d"}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "max_seqlen_q": I(1), "num_seqs": I(2), "seq_threshold_3D": I(16)}},
                     response={"type": "object", "properties": {"use_3d": {"type": "boolean"}}}))
    ha, hb = fn(I4, "fast_hadamard_transform")
    th_a, th_b = fn(I4, "_triton_hadamard_transform")
    out.append(iface("int4-per-token-head", "fast-hadamard-transform",
                     "fast_hadamard_transform: three tiers: Hadacore CUDA op, Triton MMA kernel, PyTorch butterfly.",
                     [C(I4, ha, hb), C(I4, th_a, th_b)],
                     [{"if": "input.hadacore_available && input.d <= 32768",
                       "then": [{"title": "Tier 1: Hadacore", "source": C(I4, ln(I4, r"if _hadacore_available\(\) and 0 < d <= \(1 << 15\):", ha)),
                                 "call": "custom-ops.hadacore-transform", "input": {"num_tokens": 1, "hidden_size": "= input.d", "dtype_bytes": 2}},
                                {"return": {"tier": "hadacore"}}]},
                      {"if": "input.is_cuda && input.d >= 16 && input.dtype in ['float16', 'bfloat16', 'float32']",
                       "then": [{"title": "Tier 2: Triton MMA Hadamard", "source": C(I4, ln(I4, r"_hadamard_mma_kernel\[grid\]\(", th_a)),
                                 "call": "int4-per-token-head.hadamard-mma-kernel", "input": {"head_size": "= input.d", "kv_tokens": 0}, "fill": True},
                                {"return": {"tier": "triton"}}]},
                      {"title": "Tier 3: PyTorch butterfly", "source": C(I4, ln(I4, r"# Tier 3", ha)), "return": {"tier": "torch"}}],
                     request={"type": "object", "properties": {"d": I(128), "dtype": S("float32"), "is_cuda": B(True), "hadacore_available": B(True)}},
                     response={"type": "object", "properties": {"tier": {"type": "string"}}}))
    return out

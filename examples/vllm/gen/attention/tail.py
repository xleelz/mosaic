"""Backends beyond the default CUDA path: Triton MLA decode, TurboQuant, UltraQuant, DeepSeek sparse-MLA
metadata, FlashInfer metadata, diff-KV unified attention, FlashMLA FP8 wrappers."""
from core import B, I, S, err, iface, comp
from lib import (C, Cfn, Cinv, LAT_ATTN, LAT_META, SHAPE, cls, fn, helper, kernel, launch, ln, mark, note,
                 op_kernel)

TDA = "vllm/v1/attention/ops/triton_decode_attention.py"
TMLA = "vllm/v1/attention/backends/mla/triton_mla.py"
TQ = "vllm/v1/attention/backends/turboquant_attn.py"
TQS = "vllm/v1/attention/ops/triton_turboquant_store.py"
TQD = "vllm/v1/attention/ops/triton_turboquant_decode.py"
SOAS = "vllm/v1/attention/ops/turboquant_soa/triton_turboquant_store.py"
SOAD = "vllm/v1/attention/ops/turboquant_soa/triton_turboquant_decode.py"
SOAU = "vllm/v1/attention/ops/turboquant_soa/triton_turboquant_unified_attention.py"
UQ = "vllm/v1/attention/backends/ultraquant_attn.py"
UQS = "vllm/v1/attention/ops/ultraquant/triton_store.py"
UQD = "vllm/v1/attention/ops/ultraquant/triton_dequant.py"
UQU = "vllm/v1/attention/ops/ultraquant/triton_unified_attention.py"
IDX = "vllm/v1/attention/backends/mla/indexer.py"
SWA = "vllm/v1/attention/backends/mla/sparse_swa.py"
SPU = "vllm/v1/attention/backends/mla/sparse_utils.py"
CMP = "vllm/v1/attention/backends/mla/compressor_utils.py"
OMD = "vllm/v1/attention/ops/metadata.py"
OCM = "vllm/v1/attention/ops/common.py"
SM90 = "vllm/v1/attention/backends/mla/flashinfer_mla_sparse_sm90.py"
FI = "vllm/v1/attention/backends/flashinfer.py"
DKV = "vllm/v1/attention/ops/triton_unified_attention_diffkv.py"
FMLA = "vllm/v1/attention/ops/flashmla.py"
TUA = "vllm/v1/attention/ops/triton_unified_attention.py"
TAH = "vllm/v1/attention/ops/triton_attention_helpers.py"


def tail_components():
    from lib import lines
    out = []
    for id_, name, f, summary, clsname in [
        ("triton-mla-impl", "TritonMLAImpl", TMLA, "Triton MLA decode (forward_mqa) over the latent KV cache.", "TritonMLAImpl"),
        ("turboquant-attention-impl", "TurboQuantAttentionImpl", TQ, "TurboQuant KV-cache attention: quantizing store, decode and continuation prefill.", "TurboQuantAttentionImpl"),
        ("ultraquant-attention-impl", "UltraQuantAttentionImpl", UQ, "UltraQuant (FP4 + UE8M0) KV-cache attention.", "UltraQuantAttentionImpl"),
        ("deepseek-v32-indexer-metadata-builder", "DeepseekV32IndexerMetadataBuilder", IDX, "Metadata for the DeepSeek sparse-attention lightning indexer (decode and prefill chunks).", "DeepseekV32IndexerMetadataBuilder"),
        ("kpool-tail-metadata-builder", "KpoolTailMetadataBuilder", IDX, "Slot mapping for the compressed K-pool tail.", "KpoolTailMetadataBuilder"),
        ("deepseek-sparse-swa-metadata-builder", "DeepseekSparseSWAMetadataBuilder", SWA, "Sliding-window (+ sparse) MLA metadata: SWA indices, lengths and image visibility.", "DeepseekSparseSWAMetadataBuilder"),
        ("flashinfer-mla-sparse-sm90-state", "_SM90State", SM90, "Per-step plan state of the FlashInfer sparse MLA SM90 backend.", "_SM90State"),
        ("flashinfer-metadata-builder", "FlashInferMetadataBuilder", FI, "Builds FlashInfer paged-KV metadata.", "FlashInferMetadataBuilder"),
    ]:
        a, b = cls(f, clsname)
        out.append(comp(id_, name, f, summary, a=a, b=b))
        if id_ == "flashinfer-mla-sparse-sm90-state":
            # The plan is a cache of the last planned row lengths (reused while it still bounds them).
            out[-1].update({"tags": ["cache"],
                            "state": {"schema": {"type": "object", "properties": {"planned_num_tokens": {"type": "integer"}, "planned_lens": {"type": "array"}}},
                                      "initial": {"planned_num_tokens": -1, "planned_lens": []}},
                            "attributes": {"racy_in_code": f"{SM90}:{fn(SM90, 'plan')[0]}-{fn(SM90, 'plan')[1]} "
                                                           "(plan reads _planned_num_tokens and writes it unconditionally, unlocked; one builder plans per step on the model runner thread)"}})
    for id_, name, f, summary in [
        ("triton-decode-attention", "triton_decode_attention.py", TDA, "Two-stage Triton split-KV decode attention (MLA and TurboQuant use it)."),
        ("triton-turboquant-store", "triton_turboquant_store.py", TQS, "TurboQuant quantizing KV store kernels."),
        ("triton-turboquant-decode", "triton_turboquant_decode.py", TQD, "TurboQuant decode attention and full-dequant kernels."),
        ("turboquant-soa-store", "turboquant_soa/triton_turboquant_store.py", SOAS, "TurboQuant structure-of-arrays store (FlyDSL layout)."),
        ("turboquant-soa-decode", "turboquant_soa/triton_turboquant_decode.py", SOAD, "TurboQuant SoA decode / dequant kernels."),
        ("turboquant-soa-unified-attention", "turboquant_soa/triton_turboquant_unified_attention.py", SOAU, "TurboQuant SoA unified attention (2D / 3D)."),
        ("ultraquant-triton-store", "ultraquant/triton_store.py", UQS, "UltraQuant store: rotate K, pack FP4 + UE8M0 scales."),
        ("ultraquant-triton-dequant", "ultraquant/triton_dequant.py", UQD, "UltraQuant full KV dequant for continuation prefill."),
        ("ultraquant-triton-unified-attention", "ultraquant/triton_unified_attention.py", UQU, "UltraQuant unified attention (2D / 3D)."),
        ("mla-indexer", "backends/mla/indexer.py", IDX, "Module functions of the sparse-attention indexer (prefill chunk metadata, K-pool tail slots)."),
        ("sparse-utils", "backends/mla/sparse_utils.py", SPU, "Sparse MLA index remapping and safe lengths."),
        ("compressor-utils", "backends/mla/compressor_utils.py", CMP, "Compressed-KV slot mapping."),
        ("attention-ops-metadata", "ops/metadata.py", OMD, "Token-to-request maps and indexer decode metadata kernels."),
        ("attention-ops-common", "ops/common.py", OCM, "Pack/unpack ragged sequences for the sparse indexer."),
        ("flashinfer-backend-ops", "backends/flashinfer.py (module functions)", FI, "FlashInfer module-level helpers (TRT-LLM FP8 KV dequant)."),
        ("triton-unified-attention-diffkv", "triton_unified_attention_diffkv.py", DKV, "Unified attention for caches with different K and V head sizes."),
        ("flashmla", "ops/flashmla.py", FMLA, "FlashMLA Python interface (dense FP8 decode wrappers)."),
    ]:
        out.append(comp(id_, name, f, summary, a=1, b=len(lines(f))))
    return out


def _fwdshape():
    return {"num_tokens": "= input.num_tokens", "num_seqs": "= input.num_seqs", "kv_tokens": "= input.kv_tokens"}


BREQ = {"type": "object", "properties": {"num_tokens": I(4), "num_seqs": I(4), "kv_tokens": I(4096), "num_heads": I(16), "num_kv_heads": I(1),
                                         "head_size": I(576), "shape": {"$ref": "AttnKernelShape"}}}


def tail_interfaces():
    out = []
    # ---------------- Triton decode attention (MLA)
    out.append(kernel("triton-decode-attention", "fwd-kernel-stage1", TDA, "_fwd_kernel_stage1", "Split-KV stage 1 (one KV head per query head)."))
    out.append(kernel("triton-decode-attention", "fwd-grouped-kernel-stage1", TDA, "_fwd_grouped_kernel_stage1", "Split-KV stage 1 for grouped heads (GQA / MLA)."))
    out.append(kernel("triton-decode-attention", "fwd-kernel-stage2", TDA, "_fwd_kernel_stage2", "Stage 2: softmax-reduce the KV splits.", lat=LAT_META))
    da, db = fn(TDA, "decode_attention_fwd")
    na, nb = fn(TDA, "decode_attention_fwd_normal")
    ga, gb = fn(TDA, "decode_attention_fwd_grouped")
    beh = [
        {"if": "input.kv_group_num == 1",
         "then": [{"title": "One KV head per query head: _decode_att_m_fwd", "source": C(TDA, ln(TDA, r"_fwd_kernel_stage1\[grid\]\(")),
                   "call": "triton-decode-attention.fwd-kernel-stage1", "input": SHAPE, "fill": True},
                  {"set": {"vars.mode": "normal"}}],
         "else": [{"title": "Grouped heads: _decode_grouped_att_m_fwd", "source": C(TDA, ln(TDA, r"_fwd_grouped_kernel_stage1\[grid\]\(")),
                   "call": "triton-decode-attention.fwd-grouped-kernel-stage1", "input": SHAPE, "fill": True},
                  {"set": {"vars.mode": "grouped"}}]},
        {"when": "input.logit_cap > 0", **helper(TDA, "tanh", "stage 1 inlines tanh for logit soft-capping")},
        {"title": "_decode_softmax_reducev_fwd: reduce the KV splits", "source": C(TDA, ln(TDA, r"_fwd_kernel_stage2\[grid\]\(")),
         "call": "triton-decode-attention.fwd-kernel-stage2", "input": SHAPE, "fill": True},
        {"return": {"mode": "= vars.mode"}},
    ]
    out.append(iface("triton-decode-attention", "decode-attention-fwd",
                     "decode_attention_fwd: two-stage split-KV decode; the grouped kernel when several query heads share a KV head.",
                     [C(TDA, da, db), C(TDA, na, nb), C(TDA, ga, gb)], beh,
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "kv_group_num": I(16), "logit_cap": {"type": "number", "default": 0}}},
                     response={"type": "object", "properties": {"mode": {"type": "string"}}}))
    ma, mb = fn(TMLA, "forward_mqa")
    out.append(iface("triton-mla-impl", "forward-mqa",
                     "TritonMLAImpl.forward_mqa: MLA decode over the latent cache with decode_attention_fwd (all query heads share the single latent KV head).",
                     [C(TMLA, ma, mb)],
                     [{"title": "decode_attention_fwd over the latent cache", "source": C(TMLA, ln(TMLA, r"decode_attention_fwd\(", ma)),
                       "call": "triton-decode-attention.decode-attention-fwd",
                       "input": {"shape": {"num_tokens": "= input.num_tokens", "num_seqs": "= input.num_seqs", "kv_tokens": "= input.kv_tokens", "num_heads": "= input.num_heads", "num_kv_heads": 1, "head_size": 576},
                                 "kv_group_num": "= input.num_heads", "logit_cap": 0}, "as": "d"},
                      {"return": {"mode": "= vars.d.value.mode"}}],
                     request=BREQ, response={"type": "object", "properties": {"mode": {"type": "string"}}}))

    # ---------------- TurboQuant
    out.append(kernel("triton-turboquant-store", "tq-fused-store-fp8", TQS, "_tq_fused_store_fp8", "Fused TurboQuant store with FP8 keys."))
    out.append(kernel("triton-turboquant-store", "tq-fused-store-mse", TQS, "_tq_fused_store_mse", "Fused TurboQuant store with MSE-quantized keys."))
    sa, sb = fn(TQS, "triton_turboquant_store")
    out.append(iface("triton-turboquant-store", "triton-turboquant-store",
                     "triton_turboquant_store: FP8-key layouts use the fp8 fused store, the others the MSE fused store.",
                     [C(TQS, sa, sb)],
                     [{"if": "input.key_fp8",
                       "then": [{"title": "_tq_fused_store_fp8", "source": C(TQS, ln(TQS, r"_tq_fused_store_fp8\[grid\]\(", sa)), "call": "triton-turboquant-store.tq-fused-store-fp8", "input": SHAPE, "fill": True}],
                       "else": [{"title": "_tq_fused_store_mse", "source": C(TQS, ln(TQS, r"_tq_fused_store_mse\[grid\]\(", sa)), "call": "triton-turboquant-store.tq-fused-store-mse", "input": SHAPE, "fill": True}]},
                      helper(TQS, "_store_quantized_value", "both fused stores inline _store_quantized_value"),
                      {"return": {"store": "= input.key_fp8 ? 'fp8' : 'mse'"}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "key_fp8": B(False)}},
                     response={"type": "object", "properties": {"store": {"type": "string"}}}))
    out.append(kernel("turboquant-soa-store", "tq-fused-store-fp8", SOAS, "_tq_fused_store_fp8", "SoA fused store with FP8 keys."))
    out.append(kernel("turboquant-soa-store", "tq-fused-store-mse", SOAS, "_tq_fused_store_mse", "SoA fused store with MSE keys."))
    sa, sb = fn(SOAS, "triton_turboquant_store")
    out.append(iface("turboquant-soa-store", "triton-turboquant-store",
                     "SoA triton_turboquant_store (used when FlyDSL is available): fp8 or MSE fused store into the SoA layout.",
                     [C(SOAS, sa, sb)],
                     [{"if": "input.key_fp8",
                       "then": [{"title": "_tq_fused_store_fp8 (SoA)", "source": C(SOAS, ln(SOAS, r"_tq_fused_store_fp8\[grid\]\(", sa)), "call": "turboquant-soa-store.tq-fused-store-fp8", "input": SHAPE, "fill": True}],
                       "else": [{"title": "_tq_fused_store_mse (SoA)", "source": C(SOAS, ln(SOAS, r"_tq_fused_store_mse\[grid\]\(", sa)), "call": "turboquant-soa-store.tq-fused-store-mse", "input": SHAPE, "fill": True}]},
                      helper(SOAS, "_store_quantized_value", "both SoA fused stores inline _store_quantized_value"),
                      {"return": {"store": "= input.key_fp8 ? 'soa-fp8' : 'soa-mse'"}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "key_fp8": B(False)}},
                     response={"type": "object", "properties": {"store": {"type": "string"}}}))
    out.append(kernel("triton-turboquant-decode", "tq-decode-stage1", TQD, "_tq_decode_stage1", "TurboQuant decode stage 1 over the quantized cache."))
    out.append(kernel("triton-turboquant-decode", "tq-full-dequant-kv", TQD, "_tq_full_dequant_kv", "Dequantize the whole cached K/V for continuation prefill."))
    out.append(kernel("turboquant-soa-decode", "tq-full-dequant-kv", SOAD, "_tq_full_dequant_kv", "SoA full dequant for continuation prefill."))
    ta, tb = fn(TQD, "triton_turboquant_decode_attention")
    out.append(iface("triton-turboquant-decode", "triton-turboquant-decode-attention",
                     "triton_turboquant_decode_attention: stage 1 over the quantized cache, then the shared split-KV reduce (_fwd_kernel_stage2).",
                     [C(TQD, ta, tb)],
                     [{"title": "_tq_decode_stage1", "source": C(TQD, ln(TQD, r"_tq_decode_stage1\[grid\]\(", ta)), "call": "triton-turboquant-decode.tq-decode-stage1", "input": SHAPE, "fill": True},
                      {"title": "_fwd_kernel_stage2 (from triton_decode_attention)", "source": C(TQD, ln(TQD, r"_fwd_kernel_stage2\[grid2\]\(", ta)), "call": "triton-decode-attention.fwd-kernel-stage2", "input": SHAPE, "fill": True},
                      {"return": {"decoded": True}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}}))
    for k, inv_ in [("tq-find-seq-idx", "_find_seq_idx"), ("tq-fuse-q-rotation", "_tq_fuse_q_rotation"), ("tq-load-k-tile", "_tq_load_k_tile"), ("tq-load-v-tile", "_tq_load_v_tile")]:
        mark(SOAU, inv_)
    out.append(kernel("turboquant-soa-unified-attention", "kernel-tq-unified-attention-2d", SOAU, "kernel_tq_unified_attention_2d", "TurboQuant SoA unified attention, 2D grid."))
    out.append(kernel("turboquant-soa-unified-attention", "kernel-tq-unified-attention-3d", SOAU, "kernel_tq_unified_attention_3d", "TurboQuant SoA unified attention, 3D (KV-split) grid."))
    ua, ub = fn(SOAU, "triton_turboquant_unified_attention")
    wa, wb = fn(SOAU, "triton_turboquant_decode_attention_soa")
    out.append(iface("turboquant-soa-unified-attention", "triton-turboquant-decode-attention-soa",
                     "triton_turboquant_decode_attention_soa -> triton_turboquant_unified_attention: 2D for prefill-like batches or short contexts, 3D split-KV + reduce for long decode.",
                     [C(SOAU, wa, wb), C(SOAU, ua, ub)],
                     [{"set": {"vars.use_3d": "= !input.force_2d && !input.is_prefill_like && input.max_seq_len_hint >= 1024"}},
                      {"title": "use_3d = not force_2d and not prefill-like and max_seq_len_hint >= 1024", "source": C(SOAU, ln(SOAU, r"use_3d = \(not force_2d\)", ua))},
                      helper(SOAU, "_find_seq_idx", "the kernels inline _find_seq_idx"),
                      helper(SOAU, "_tq_fuse_q_rotation", "the kernels inline _tq_fuse_q_rotation"),
                      helper(SOAU, "_tq_load_k_tile", "the kernels inline _tq_load_k_tile (dequantize K tiles)"),
                      helper(SOAU, "_tq_load_v_tile", "the kernels inline _tq_load_v_tile (dequantize V tiles)"),
                      {"if": "!vars.use_3d",
                       "then": [{"title": "kernel_tq_unified_attention_2d", "source": C(SOAU, ln(SOAU, r"kernel_tq_unified_attention_2d\[", ua)), "call": "turboquant-soa-unified-attention.kernel-tq-unified-attention-2d", "input": SHAPE, "fill": True}],
                       "else": [{"title": "kernel_tq_unified_attention_3d", "source": C(SOAU, ln(SOAU, r"kernel_tq_unified_attention_3d\[", ua)), "call": "turboquant-soa-unified-attention.kernel-tq-unified-attention-3d", "input": SHAPE, "fill": True},
                                {"title": "reduce_segments", "source": C(SOAU, ln(SOAU, r"reduce_segments\[", ua)), "call": "triton-unified-attention.reduce-segments", "input": SHAPE, "fill": True}]},
                      {"return": {"use_3d": "= vars.use_3d"}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "force_2d": B(False), "is_prefill_like": B(False), "max_seq_len_hint": I(4096)}},
                     response={"type": "object", "properties": {"use_3d": {"type": "boolean"}}}))
    # TurboQuant impl
    sa, sb = fn(TQ, "_store_kv")
    ka, kb = fn(TQ, "do_kv_cache_update", cls(TQ, "TurboQuantAttentionImpl")[0])
    out.append(iface("turboquant-attention-impl", "do-kv-cache-update",
                     "TurboQuantAttentionImpl.do_kv_cache_update -> _store_kv: SoA store when FlyDSL is in use, else the Triton store.",
                     [C(TQ, ka, kb), C(TQ, sa, sb)],
                     [{"if": "input.num_tokens <= 0", "then": [{"title": "Nothing to store", "source": C(TQ, ln(TQ, r"if N <= 0:", ka)), "return": {"store": "none"}}]},
                      {"if": "input.use_flydsl",
                       "then": [{"title": "SoA store (FlyDSL layout)", "source": C(TQ, ln(TQ, r"soa_store\(", sa)), "call": "turboquant-soa-store.triton-turboquant-store",
                                 "input": {"shape": {"num_tokens": "= input.num_tokens", "kv_tokens": 0}, "key_fp8": "= input.key_fp8"}, "as": "s"}],
                       "else": [{"title": "Triton store", "source": C(TQ, ln(TQ, r"triton_turboquant_store\(", sa)), "call": "triton-turboquant-store.triton-turboquant-store",
                                 "input": {"shape": {"num_tokens": "= input.num_tokens", "kv_tokens": 0}, "key_fp8": "= input.key_fp8"}, "as": "s"}]},
                      {"return": {"store": "= vars.s.value.store"}}],
                     request={"type": "object", "properties": {"num_tokens": I(8), "use_flydsl": B(False), "key_fp8": B(False)}},
                     response={"type": "object", "properties": {"store": {"type": "string"}}}))
    fa_, fb_ = fn(TQ, "forward", cls(TQ, "TurboQuantAttentionImpl")[0])
    dca, dcb = fn(TQ, "_decode_attention")
    cpa, cpb = fn(TQ, "_continuation_prefill")
    beh = [
        {"if": "input.metadata_missing", "then": [{"title": "Profiling run", "source": C(TQ, ln(TQ, r"if attn_metadata is None:", fa_)), "return": {"path": "profiling"}}]},
        {"if": "!input.is_prefill",
         "then": [{"title": "Pure decode batch: _decode_attention", "source": C(TQ, ln(TQ, r"if not attn_metadata.is_prefill:", fa_)), "set": {"vars.path": "decode"}},
                  {"if": "input.use_flydsl",
                   "then": [{"title": "FlyDSL not eligible here: SoA unified decode", "source": C(TQ, ln(TQ, r"return self._dispatch_decode_soa\(", dca)),
                             "call": "turboquant-soa-unified-attention.triton-turboquant-decode-attention-soa",
                             "input": {"shape": {"num_tokens": "= input.num_tokens", "num_seqs": "= input.num_seqs", "kv_tokens": "= input.kv_tokens"},
                                       "force_2d": False, "is_prefill_like": False, "max_seq_len_hint": "= input.max_seq_len"}, "as": "soa"},
                            {"set": {"vars.use_3d": "= vars.soa.value.use_3d"}}],
                   "else": [{"title": "Triton TurboQuant decode", "source": C(TQ, ln(TQ, r"result = triton_turboquant_decode_attention\(", dca)),
                             "call": "triton-turboquant-decode.triton-turboquant-decode-attention",
                             "input": {"shape": {"num_tokens": "= input.num_tokens", "num_seqs": "= input.num_seqs", "kv_tokens": "= input.kv_tokens"}}}]}],
         "else": [{"title": "Prefill: requests with cached context beyond the decode threshold dequantize the cache (_continuation_prefill)",
                   "source": C(TQ, ln(TQ, r"out = self._continuation_prefill\(")), "set": {"vars.path": "continuation-prefill"}},
                  {"if": "input.use_flydsl",
                   "then": [{"title": "SoA full dequant", "source": C(TQ, ln(TQ, r"soa_dequant\[grid\]\(", cpa)), "call": "turboquant-soa-decode.tq-full-dequant-kv",
                             "input": {"num_tokens": "= input.num_tokens", "kv_tokens": "= input.kv_tokens"}, "fill": True}],
                   "else": [{"title": "Triton full dequant", "source": C(TQ, ln(TQ, r"_tq_full_dequant_kv\[grid\]\(", cpa)), "call": "triton-turboquant-decode.tq-full-dequant-kv",
                             "input": {"num_tokens": "= input.num_tokens", "kv_tokens": "= input.kv_tokens"}, "fill": True}]}]},
        {"return": {"path": "= vars.path", "use_3d": "= has(vars.use_3d) ? vars.use_3d : false", "soa": "= input.use_flydsl"}},
    ]
    out.append(iface("turboquant-attention-impl", "forward",
                     "TurboQuantAttentionImpl.forward: decode batches read the quantized cache directly; prefill requests with long cached context dequantize it first.",
                     [C(TQ, fa_, fb_), C(TQ, dca, dcb), C(TQ, cpa, cpb)], beh,
                     request={"type": "object", "properties": {"metadata_missing": B(False), "is_prefill": B(False), "use_flydsl": B(False),
                                                               "num_tokens": I(4), "num_seqs": I(4), "kv_tokens": I(4096), "max_seq_len": I(1024)}},
                     response={"type": "object", "properties": {"path": {"type": "string"}}}))

    # ---------------- UltraQuant
    out.append(kernel("ultraquant-triton-store", "ultraquant-store-kernel", UQS, "_ultraquant_store_kernel", "UltraQuant store kernel (rotate, FP4 pack, UE8M0 scales)."))
    out.append(kernel("ultraquant-triton-dequant", "ultraquant-full-dequant-kv-kernel", UQD, "_ultraquant_full_dequant_kv", "UltraQuant full dequant kernel."))
    out.append(kernel("ultraquant-triton-unified-attention", "kernel-ultraquant-unified-attention-2d", UQU, "kernel_ultraquant_unified_attention_2d", "UltraQuant unified attention, 2D."))
    out.append(kernel("ultraquant-triton-unified-attention", "kernel-ultraquant-unified-attention-3d", UQU, "kernel_ultraquant_unified_attention_3d", "UltraQuant unified attention, 3D split-KV."))
    sa, sb = fn(UQS, "ultraquant_store")
    out.append(iface("ultraquant-triton-store", "ultraquant-store", "ultraquant_store: launch the store kernel over the new tokens.", [C(UQS, sa, sb)],
                     [{"title": "_ultraquant_store_kernel", "source": C(UQS, ln(UQS, r"_ultraquant_store_kernel\[", sa)), "call": "ultraquant-triton-store.ultraquant-store-kernel", "input": SHAPE, "fill": True},
                      {"return": {"stored": True}}], request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}}))
    qa, qb = fn(UQD, "ultraquant_full_dequant_kv")
    out.append(iface("ultraquant-triton-dequant", "ultraquant-full-dequant-kv", "ultraquant_full_dequant_kv: dequantize the cached K/V.", [C(UQD, qa, qb)],
                     [{"title": "_ultraquant_full_dequant_kv", "source": C(UQD, ln(UQD, r"_ultraquant_full_dequant_kv\[", qa)), "call": "ultraquant-triton-dequant.ultraquant-full-dequant-kv-kernel", "input": SHAPE, "fill": True},
                      {"return": {"dequantized": True}}], request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}}))
    va, vb = fn(UQU, "ultraquant_unified_attention")
    beh = [
        {"if": "input.num_heads % input.num_kv_heads != 0",
         "then": [{"title": "Hq must be a multiple of Hk", "source": C(UQU, ln(UQU, r"if Hq % Hk != 0:", va)), "fail": {"code": "value-error", "message": "= 'Hq=' + string(input.num_heads) + ' must be a multiple of Hk=' + string(input.num_kv_heads)"}}]},
        {"set": {"vars.use_3d": "= !input.force_2d && !input.is_prefill_like && input.max_seq_len_hint >= 1024"}},
        {"title": "use_3d = not force_2d and not prefill-like and max_seq_len_hint >= 1024", "source": C(UQU, ln(UQU, r"use_3d = \(not force_2d\)", va))},
        *[helper(UQU, n, "the kernels inline " + n) for n in ("_ultraquant_slot_addrs", "_ultraquant_qk", "_ultraquant_load_k_packed", "_ultraquant_pv", "_ultraquant_load_v_tile", "_ultraquant_fp4_decode_arith")],
        {"if": "!vars.use_3d",
         "then": [{"title": "kernel_ultraquant_unified_attention_2d", "source": C(UQU, ln(UQU, r"kernel_ultraquant_unified_attention_2d\[", va)), "call": "ultraquant-triton-unified-attention.kernel-ultraquant-unified-attention-2d", "input": SHAPE, "fill": True}],
         "else": [{"title": "kernel_ultraquant_unified_attention_3d", "source": C(UQU, ln(UQU, r"kernel_ultraquant_unified_attention_3d\[", va)), "call": "ultraquant-triton-unified-attention.kernel-ultraquant-unified-attention-3d", "input": SHAPE, "fill": True},
                  {"title": "reduce_segments", "source": C(UQU, ln(UQU, r"reduce_segments\[", va)), "call": "triton-unified-attention.reduce-segments", "input": SHAPE, "fill": True}]},
        {"return": {"use_3d": "= vars.use_3d"}},
    ]
    out.append(iface("ultraquant-triton-unified-attention", "ultraquant-unified-attention",
                     "ultraquant_unified_attention: validate head grouping, then 2D, or 3D split-KV + reduce for long-context decode.",
                     [C(UQU, va, vb)], beh,
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "num_heads": I(32), "num_kv_heads": I(8), "force_2d": B(False), "is_prefill_like": B(False), "max_seq_len_hint": I(4096)}},
                     response={"type": "object", "properties": {"use_3d": {"type": "boolean"}}}, errors=[err("value-error", "Hq not a multiple of Hk")]))
    sk_a, sk_b = fn(UQ, "_store_kv")
    de_a, de_b = fn(UQ, "_decode_attention")
    cp_a, cp_b = fn(UQ, "_ultraquant_continuation_prefill")
    out.append(iface("ultraquant-attention-impl", "store-kv", "UltraQuantAttentionImpl._store_kv: ultraquant_store into the paged cache.", [C(UQ, sk_a, sk_b)],
                     [{"title": "ultraquant_store", "source": C(UQ, ln(UQ, r"ultraquant_store\(", sk_a)), "call": "ultraquant-triton-store.ultraquant-store",
                       "input": {"shape": {"num_tokens": "= input.num_tokens", "kv_tokens": 0}}}, {"return": {"stored": True}}],
                     request={"type": "object", "properties": {"num_tokens": I(8)}}))
    out.append(iface("ultraquant-attention-impl", "decode-attention",
                     "UltraQuantAttentionImpl._decode_attention: FlyDSL decode when eligible (ROCm), else ultraquant_unified_attention.",
                     [C(UQ, de_a, de_b)],
                     [{"if": "input.flydsl_eligible",
                       "then": [{"title": "FlyDSL decode (ROCm; not modeled further)", "source": C(UQ, ln(UQ, r"return flydsl_ultraquant_decode_attention\(", de_a)), "return": {"impl": "flydsl"}}]},
                      {"title": "ultraquant_unified_attention", "source": C(UQ, ln(UQ, r"return ultraquant_unified_attention\(", de_a)),
                       "call": "ultraquant-triton-unified-attention.ultraquant-unified-attention",
                       "input": {"shape": {"num_tokens": "= input.num_tokens", "num_seqs": "= input.num_seqs", "kv_tokens": "= input.kv_tokens"},
                                 "num_heads": 32, "num_kv_heads": 8, "force_2d": False, "is_prefill_like": False, "max_seq_len_hint": "= input.max_seq_len"}, "as": "u"},
                      {"return": {"impl": "triton", "use_3d": "= vars.u.value.use_3d"}}],
                     request={"type": "object", "properties": {"flydsl_eligible": B(False), "num_tokens": I(4), "num_seqs": I(4), "kv_tokens": I(4096), "max_seq_len": I(4096)}},
                     response={"type": "object", "properties": {"impl": {"type": "string"}, "use_3d": {"type": "boolean"}}}))
    out.append(iface("ultraquant-attention-impl", "continuation-prefill",
                     "UltraQuantAttentionImpl._ultraquant_continuation_prefill: dequantize the cached context before prefill attention.",
                     [C(UQ, cp_a, cp_b)],
                     [{"title": "ultraquant_full_dequant_kv", "source": C(UQ, ln(UQ, r"ultraquant_full_dequant_kv\(", cp_a + 5)), "call": "ultraquant-triton-dequant.ultraquant-full-dequant-kv",
                       "input": {"shape": {"num_tokens": "= input.num_tokens", "kv_tokens": "= input.kv_tokens"}}},
                      {"return": {"dequantized": True}}],
                     request={"type": "object", "properties": {"num_tokens": I(64), "kv_tokens": I(4096)}}))

    # ---------------- DeepSeek sparse MLA metadata
    out.append(kernel("mla-indexer", "prepare-uniform-decode-kernel", IDX, "PrepareUniformDecodeKernel.kernel", "Uniform-decode indexer metadata kernel.", lat=LAT_META))
    out.append(kernel("mla-indexer", "build-prefill-chunk-metadata-kernel", IDX, "BuildPrefillChunkMetadataKernel.kernel", "Prefill-chunk indexer metadata kernel.", lat=LAT_META))
    out.append(kernel("mla-indexer", "kpool-tail-slot-mapping-kernel", IDX, "_kpool_tail_slot_mapping_kernel", "K-pool tail slot mapping kernel.", lat=LAT_META))
    out.append(kernel("attention-ops-metadata", "indexer-decode-metadata-kernel", OMD, "_indexer_decode_metadata_kernel", "Varlen indexer decode metadata kernel.", lat=LAT_META))
    out.append(kernel("attention-ops-metadata", "token-request-mapping-kernel", OMD, "_token_request_mapping_kernel", "Token -> request index kernel.", lat=LAT_META))
    ba, bb = fn(IDX, "build", cls(IDX, "DeepseekV32IndexerMetadataBuilder")[0])
    pda, pdb = fn(IDX, "_prepare_decode_tensors")
    pca, pcb = fn(IDX, "build_prefill_chunk_metadata")
    out.append(iface("mla-indexer", "build-prefill-chunk-metadata", "build_prefill_chunk_metadata: per-chunk indexer metadata for prefill requests.",
                     [C(IDX, pca, pcb)],
                     [{"title": "_BUILD_PREFILL_CHUNK_METADATA_KERNEL", "source": C(IDX, ln(IDX, r"_BUILD_PREFILL_CHUNK_METADATA_KERNEL\(", pca)),
                       "call": "mla-indexer.build-prefill-chunk-metadata-kernel", "input": SHAPE, "fill": True}, {"return": {"chunks": 1}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}}))
    out.append(iface("deepseek-v32-indexer-metadata-builder", "prepare-decode-tensors",
                     "DeepseekV32IndexerMetadataBuilder._prepare_decode_tensors: uniform-decode metadata for backends without varlen decode.",
                     [C(IDX, pda, pdb)],
                     [{"title": "_PREPARE_UNIFORM_DECODE_KERNEL", "source": C(IDX, ln(IDX, r"_PREPARE_UNIFORM_DECODE_KERNEL\(", pda)),
                       "call": "mla-indexer.prepare-uniform-decode-kernel", "input": SHAPE, "fill": True}, {"return": {"prepared": True}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}}))
    beh = [
        {"if": "input.num_tokens == 0", "then": [{"title": "Empty batch", "source": C(IDX, ln(IDX, r"if num_tokens == 0:", ba)), "return": {"prefill": False, "decode": False}}]},
        {"if": "input.num_prefills > 0",
         "then": [{"title": "Prefill chunks", "source": C(IDX, ln(IDX, r"metadata = build_prefill_chunk_metadata\(", ba)),
                   "call": "mla-indexer.build-prefill-chunk-metadata", "input": {"shape": {"num_tokens": "= input.num_tokens", "num_seqs": "= input.num_prefills", "kv_tokens": 0}}}]},
        {"if": "input.num_decodes > 0",
         "then": [{"if": "input.supports_varlen",
                   "then": [{"title": "Varlen decode metadata", "source": C(IDX, ln(IDX, r"_indexer_decode_metadata_kernel\[\(grid,\)\]\(", ba)),
                             "call": "attention-ops-metadata.indexer-decode-metadata-kernel", "input": {"num_seqs": "= input.num_decodes", "kv_tokens": 0}, "fill": True}],
                   "else": [{"title": "Uniform decode tensors", "source": C(IDX, ln(IDX, r"self._prepare_decode_tensors\(", ba)),
                             "call": "deepseek-v32-indexer-metadata-builder.prepare-decode-tensors", "input": {"shape": {"num_seqs": "= input.num_decodes", "kv_tokens": 0}}}]}]},
        {"return": {"prefill": "= input.num_prefills > 0", "decode": "= input.num_decodes > 0"}},
    ]
    out.append(iface("deepseek-v32-indexer-metadata-builder", "build",
                     "DeepseekV32IndexerMetadataBuilder.build: empty batches return early; prefill chunk metadata; decode metadata (varlen kernel or uniform tensors).",
                     [C(IDX, ba, bb)], beh,
                     request={"type": "object", "properties": {"num_tokens": I(24), "num_prefills": I(1), "num_decodes": I(2), "supports_varlen": B(True)}},
                     response={"type": "object", "properties": {"prefill": {"type": "boolean"}, "decode": {"type": "boolean"}}}))
    ka, kb = fn(IDX, "compute_kpool_tail_slot_mapping")
    slots = "= input.requests.map(r, r.positions.map(p, r.own_block == 0 ? -1 : r.own_block * input.kpool + p % input.kpool))"
    out.append(iface("mla-indexer", "compute-kpool-tail-slot-mapping",
                     "compute_kpool_tail_slot_mapping: every token maps to its request's one circular tail block, slot = own_block * kpool + pos % kpool; requests on the null block get -1 (Triton kernel on CUDA, torch fallback otherwise).",
                     [C(IDX, ka, kb), Cinv(IDX, "_kpool_tail_slot_mapping_kernel")],
                     [{"if": "input.is_cuda && size(input.requests) > 0",
                       "then": [{"title": "_kpool_tail_slot_mapping_kernel, one program per request plus the padding tail", "source": C(IDX, ln(IDX, r"_kpool_tail_slot_mapping_kernel\[grid\]\(", ka)),
                                 "call": "mla-indexer.kpool-tail-slot-mapping-kernel", "input": {"num_seqs": "= size(input.requests)", "kv_tokens": 0}, "fill": True},
                                {"set": {"vars.path": "triton"}}],
                       "else": [{"title": "Torch fallback (CPU tensors)", "source": C(IDX, ln(IDX, r"slots = own_block \* kpool \+ torch.remainder\(pos, kpool\)", ka)),
                                 "set": {"vars.path": "torch"}}]},
                      {"title": "slot = own_block * kpool + pos % kpool, or -1 on the null block", "source": C(IDX, ln(IDX, r"out\[:num_actual_tokens\] = torch.where\(own_block != 0, slots, -1\)", ka)),
                       "return": {"mapped": True, "path": "= vars.path", "slots": slots}}],
                     request={"type": "object", "properties": {"kpool": I(4), "is_cuda": B(True),
                                                               "requests": {"type": "array", "default": [{"own_block": 5, "positions": [8, 9]}],
                                                                            "items": {"type": "object", "properties": {"own_block": {"type": "integer"}, "positions": {"type": "array", "items": {"type": "integer"}}}}}}},
                     response={"type": "object", "properties": {"mapped": {"type": "boolean"}, "path": {"type": "string"}, "slots": {"type": "array"}}}))
    kba, kbb = fn(IDX, "build", cls(IDX, "KpoolTailMetadataBuilder")[0])
    out.append(iface("kpool-tail-metadata-builder", "build", "KpoolTailMetadataBuilder.build: recompute the tail slot mapping when positions are given.", [C(IDX, kba, kbb)],
                     [{"if": "input.has_positions",
                       "then": [{"title": "compute_kpool_tail_slot_mapping", "source": C(IDX, ln(IDX, r"slot_mapping = compute_kpool_tail_slot_mapping\(", kba)),
                                 "call": "mla-indexer.compute-kpool-tail-slot-mapping", "input": {"kpool": 4, "is_cuda": True, "requests": [{"own_block": 5, "positions": "= lists.range(input.num_tokens)"}]}}]},
                      {"return": {"recomputed": "= input.has_positions"}}],
                     request={"type": "object", "properties": {"has_positions": B(True), "num_tokens": I(24)}},
                     response={"type": "object", "properties": {"recomputed": {"type": "boolean"}}}))
    # sparse SWA
    out.append(kernel("deepseek-sparse-swa-metadata-builder", "compute-swa-indices-and-lens-kernel", SWA, "_compute_swa_indices_and_lens_kernel", "SWA indices and lengths kernel.", lat=LAT_META))
    out.append(kernel("deepseek-sparse-swa-metadata-builder", "compute-dspark-noncausal-swa-indices-kernel", SWA, "ComputeDSparkNoncausalSWAIndicesKernel.kernel", "DSpark non-causal SWA indices kernel.", lat=LAT_META))
    out.append(kernel("deepseek-sparse-swa-metadata-builder", "compute-image-visibility-kernel", SWA, "_compute_image_visibility_kernel", "Bidirectional image-token visibility kernel.", lat=LAT_META))
    out.append(kernel("deepseek-sparse-swa-metadata-builder", "compute-prefill-metadata-kernel", SWA, "ComputePrefillMetadataKernel.kernel", "DeepSeek-V4 prefill metadata kernel.", lat=LAT_META))
    sba, sbb = fn(SWA, "build", cls(SWA, "DeepseekSparseSWAMetadataBuilder")[0])
    iva, ivb = fn(SWA, "_build_image_visibility")
    v4a, v4b = fn(SWA, "_build_deepseek_v4_metadata")
    beh = [
        {"if": "input.num_decode_tokens > 0",
         "then": [{"if": "input.non_causal",
                   "then": [{"title": "DSpark non-causal decode indices", "source": C(SWA, ln(SWA, r"_COMPUTE_DSPARK_NONCAUSAL_SWA_INDICES_KERNEL\(", sba)),
                             "call": "deepseek-sparse-swa-metadata-builder.compute-dspark-noncausal-swa-indices-kernel", "input": {"num_tokens": "= input.num_decode_tokens", "kv_tokens": 0}, "fill": True}],
                   "else": [{"title": "Causal SWA decode indices and lengths", "source": C(SWA, ln(SWA, r"_COMPUTE_SWA_INDICES_AND_LENS_KERNEL\(", sba)),
                             "call": "deepseek-sparse-swa-metadata-builder.compute-swa-indices-and-lens-kernel", "input": {"num_tokens": "= input.num_decode_tokens", "kv_tokens": 0}, "fill": True}]}]},
        {"if": "input.has_image_ranges && input.num_prefill_tokens > 0",
         "then": [{"title": "Image visibility for prefill tokens", "source": C(SWA, ln(SWA, r"_compute_image_visibility_kernel\[", iva)),
                   "call": "deepseek-sparse-swa-metadata-builder.compute-image-visibility-kernel", "input": {"num_tokens": "= input.num_prefill_tokens", "kv_tokens": 0}, "fill": True}]},
        {"if": "input.num_prefill_tokens > 0",
         "then": [{"title": "Prefill SWA indices and lengths", "source": C(SWA, ln(SWA, r"_COMPUTE_SWA_INDICES_AND_LENS_KERNEL\(", sba, 2)),
                   "call": "deepseek-sparse-swa-metadata-builder.compute-swa-indices-and-lens-kernel", "input": {"num_tokens": "= input.num_prefill_tokens", "kv_tokens": 0}, "fill": True}]},
        {"title": "DeepSeek-V4 fields: ComputePrefillMetadataKernel", "source": C(SWA, ln(SWA, r"_COMPUTE_PREFILL_METADATA_KERNEL\(", v4a)),
         "call": "deepseek-sparse-swa-metadata-builder.compute-prefill-metadata-kernel", "input": {"num_tokens": "= input.num_prefill_tokens", "kv_tokens": 0}, "fill": True},
        {"return": {"decode": "= input.num_decode_tokens > 0", "prefill": "= input.num_prefill_tokens > 0"}},
    ]
    out.append(iface("deepseek-sparse-swa-metadata-builder", "build",
                     "DeepseekSparseSWAMetadataBuilder.build: decode SWA indices (DSpark non-causal or causal), image visibility, prefill SWA indices and the V4 prefill metadata.",
                     [C(SWA, sba, sbb), C(SWA, iva, ivb), C(SWA, v4a, v4b)], beh,
                     request={"type": "object", "properties": {"num_decode_tokens": I(4), "num_prefill_tokens": I(16), "non_causal": B(False), "has_image_ranges": B(False)}},
                     response={"type": "object", "properties": {"decode": {"type": "boolean"}, "prefill": {"type": "boolean"}}}))
    # sparse utils, compressor, metadata, common
    out.append(kernel("sparse-utils", "sparse-mla-index-remap-kernel", SPU, "ConvertReqIndexToGlobalIndexKernel.sparse_mla_index_remap_kernel", "Request-local -> global KV slot remap of top-k indices.", lat=LAT_META))
    out.append(kernel("sparse-utils", "sparse-mla-prepare-safe-lengths-kernel", SPU, "sparse_mla_prepare_safe_lengths_kernel", "Dummy slots and nonzero lengths for empty queries.", lat=LAT_META))
    ca, cb = fn(SPU, "triton_convert_req_index_to_global_index")
    out.append(iface("sparse-utils", "triton-convert-req-index-to-global-index", "triton_convert_req_index_to_global_index: map top-k request-local indices to global KV slots via the block table.",
                     [C(SPU, ca, cb)],
                     [{"title": "_CONVERT_REQ_INDEX_TO_GLOBAL_INDEX_KERNEL", "source": C(SPU, ln(SPU, r"_CONVERT_REQ_INDEX_TO_GLOBAL_INDEX_KERNEL\(", ca)),
                       "call": "sparse-utils.sparse-mla-index-remap-kernel", "input": SHAPE, "fill": True}, {"return": {"remapped": True}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}}))
    pa, pb = fn(SPU, "prepare_sparse_mla_safe_lengths")
    out.append(iface("sparse-utils", "prepare-sparse-mla-safe-lengths", "prepare_sparse_mla_safe_lengths: launch only when there are tokens.", [C(SPU, pa, pb)],
                     [{"if": "input.num_tokens > 0",
                       "then": [{"title": "sparse_mla_prepare_safe_lengths_kernel", "source": C(SPU, ln(SPU, r"sparse_mla_prepare_safe_lengths_kernel\[", pa)),
                                 "call": "sparse-utils.sparse-mla-prepare-safe-lengths-kernel", "input": {"num_tokens": "= input.num_tokens", "kv_tokens": 0}, "fill": True}]},
                      {"return": {"launched": "= input.num_tokens > 0"}}],
                     request={"type": "object", "properties": {"num_tokens": I(8)}}, response={"type": "object", "properties": {"launched": {"type": "boolean"}}}))
    out.append(kernel("compressor-utils", "compressed-slot-mapping-kernel", CMP, "CompressedSlotMappingKernel.kernel", "Compressed-KV slot mapping kernel.", lat=LAT_META))
    ga, gb = fn(CMP, "get_compressed_slot_mapping")
    out.append(iface("compressor-utils", "get-compressed-slot-mapping", "get_compressed_slot_mapping: slots for the compressed KV entries of this step.", [C(CMP, ga, gb)],
                     [{"title": "_COMPRESSED_SLOT_MAPPING_KERNEL", "source": C(CMP, ln(CMP, r"_COMPRESSED_SLOT_MAPPING_KERNEL\(", ga)),
                       "call": "compressor-utils.compressed-slot-mapping-kernel", "input": SHAPE, "fill": True}, {"return": {"mapped": True}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}}))
    ta, tb = fn(OMD, "compute_token_to_req_indices")
    out.append(iface("attention-ops-metadata", "compute-token-to-req-indices", "compute_token_to_req_indices: one program per 256 tokens maps each token to its request.", [C(OMD, ta, tb)],
                     [helper(OMD, "_token_request", "the kernel inlines _token_request (binary search of query_start_loc)"),
                      {"title": "_token_request_mapping_kernel", "source": C(OMD, ln(OMD, r"_token_request_mapping_kernel\[", ta)),
                       "call": "attention-ops-metadata.token-request-mapping-kernel", "input": SHAPE, "fill": True}, {"return": {"mapped": True}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}}))
    out.append(kernel("attention-ops-common", "pack-seq-triton-kernel", OCM, "PackSeqTritonKernel.kernel", "Pack ragged sequences into a padded batch.", lat=LAT_META))
    out.append(kernel("attention-ops-common", "unpack-seq-triton-kernel", OCM, "UnpackSeqTritonKernel.kernel", "Unpack a padded batch to ragged sequences.", lat=LAT_META))
    for nm, py, kk, pat in [("pack-seq-triton", "pack_seq_triton", "pack-seq-triton-kernel", r"_PACK_SEQ_TRITON_KERNEL\("),
                            ("unpack-seq-triton", "unpack_seq_triton", "unpack-seq-triton-kernel", r"_UNPACK_SEQ_TRITON_KERNEL\(")]:
        a, b = fn(OCM, py)
        out.append(iface("attention-ops-common", nm, f"{py}: Triton (un)packing of ragged sequences for the sparse indexer.", [C(OCM, a, b)],
                         [{"title": pat.replace("\\(", "").replace("\\", ""), "source": C(OCM, ln(OCM, pat, a)), "call": f"attention-ops-common.{kk}", "input": SHAPE, "fill": True},
                          {"return": {"done": True}}], request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}}))
    # SM90 sparse state
    out.append(kernel("flashinfer-mla-sparse-sm90-state", "pack-topk-indices", SM90, "_pack_topk_indices", "Pack top-k slots for the SM90 sparse kernel.", lat=LAT_META))
    out.append(kernel("flashinfer-mla-sparse-sm90-state", "clamp-work-kv-end", SM90, "_clamp_work_kv_end", "Clamp each work item's KV end to the request length.", lat=LAT_META))
    pa, pb = fn(SM90, "pack_indices")
    out.append(iface("flashinfer-mla-sparse-sm90-state", "pack-indices", "_SM90State.pack_indices: pack the top-k slots before forward_mqa.", [C(SM90, pa, pb)],
                     [{"title": "_pack_topk_indices", "source": C(SM90, ln(SM90, r"_pack_topk_indices\[", pa)), "call": "flashinfer-mla-sparse-sm90-state.pack-topk-indices", "input": SHAPE, "fill": True},
                      {"return": {"packed": True}}], request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}}))
    import round4
    out.append(round4.sm90_plan_interface())
    # FlashInfer
    out.append(kernel("flashinfer-metadata-builder", "copy-page-indices-kernel", FI, "_copy_page_indices_kernel", "Copy each request's block ids into the flattened paged_kv_indices.", lat=LAT_META))
    out.append(kernel("flashinfer-backend-ops", "trtllm-prefill-attn-kvfp8-dequant-kernel", FI, "_trtllm_prefill_attn_kvfp8_dequant", "Dequantize the FP8 KV pages a TRT-LLM prefill touches into a BF16 mock cache."))
    ka, kb = fn(FI, "_compute_flashinfer_kv_metadata")
    out.append(iface("flashinfer-metadata-builder", "compute-flashinfer-kv-metadata",
                     "FlashInferMetadataBuilder._compute_flashinfer_kv_metadata: flatten the block table into paged_kv_indices (one program per request).",
                     [C(FI, ka, kb)],
                     [{"title": "_copy_page_indices_kernel over the requests", "source": C(FI, ln(FI, r"_copy_page_indices_kernel\[\(num_reqs,\)\]\(", ka)),
                       "call": "flashinfer-metadata-builder.copy-page-indices-kernel", "input": {"num_seqs": "= size(input.block_table)", "kv_tokens": 0}, "fill": True},
                      {"return": {"paged_kv_indices": "= input.block_table.map(r, r).size() > 0 ? input.block_table[0] : []", "num_pages": "= sum(input.block_table.map(r, size(r)))"}}],
                     request={"type": "object", "properties": {"block_table": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}, "examples": [[[0, 1, 2], [3, 4]]]}}},
                     response={"type": "object", "properties": {"num_pages": {"type": "integer"}}}))
    da, db = fn(FI, "trtllm_prefill_attn_kvfp8_dequant")
    out.append(iface("flashinfer-backend-ops", "trtllm-prefill-attn-kvfp8-dequant",
                     "trtllm_prefill_attn_kvfp8_dequant: TRT-LLM prefill can't take BF16 Q with FP8 KV, so the touched pages are dequantized into a mock BF16 cache.",
                     [C(FI, da, db), C(FI, ln(FI, r"attn_metadata.q_data_type_prefill != FP8_DTYPE"), ln(FI, r"and self.kv_cache_dtype.startswith\(\"fp8\"\)"))],
                     [{"if": "input.q_fp8 || !input.kv_cache_dtype.startsWith('fp8')",
                       "then": [{"title": "FP8 queries (or a non-FP8 cache) need no dequant", "source": C(FI, ln(FI, r"attn_metadata.q_data_type_prefill != FP8_DTYPE")), "return": {"dequantized": False}}]},
                      {"title": "_trtllm_prefill_attn_kvfp8_dequant", "source": C(FI, ln(FI, r"_trtllm_prefill_attn_kvfp8_dequant\[grid\]\(", da)),
                       "call": "flashinfer-backend-ops.trtllm-prefill-attn-kvfp8-dequant-kernel", "input": SHAPE, "fill": True},
                      {"return": {"dequantized": True}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "q_fp8": B(False), "kv_cache_dtype": S("fp8")}},
                     response={"type": "object", "properties": {"dequantized": {"type": "boolean"}}}))
    # diff-KV unified attention
    out.append(kernel("triton-unified-attention-diffkv", "kernel-unified-attention-diffkv", DKV, "kernel_unified_attention_diffkv", "Unified attention with different K/V head sizes."))
    out.append(kernel("triton-unified-attention-diffkv", "kernel-reduce-segments-diffkv", DKV, "kernel_reduce_segments_diffkv", "Segment reduce for the diff-KV 3D path.", lat=LAT_META))
    ua, ub = fn(DKV, "unified_attention_diffkv")
    out.append(iface("triton-unified-attention-diffkv", "unified-attention-diffkv",
                     "unified_attention_diffkv: like unified_attention, 3D only for small pure-decode batches (or spec-3D), never under batch invariance.",
                     [C(DKV, ua, ub)],
                     [{"set": {"vars.use_3d": "= input.has_segm_buffers && (input.max_seqlen_q <= 1 || input.spec_3d) && input.num_seqs <= input.seq_threshold_3D && !input.batch_invariant"}},
                      {"title": "use_3d rule", "source": C(DKV, ln(DKV, r"use_3d = not \(", ua), ln(DKV, r"or is_batch_invariant", ua))},
                      {"title": "kernel_unified_attention_diffkv", "source": C(DKV, ln(DKV, r"kernel_unified_attention_diffkv\[grid\]\(", ua)), "call": "triton-unified-attention-diffkv.kernel-unified-attention-diffkv", "input": SHAPE, "fill": True},
                      {"if": "vars.use_3d", "then": [{"title": "kernel_reduce_segments_diffkv", "source": C(DKV, ln(DKV, r"kernel_reduce_segments_diffkv\[", ua)), "call": "triton-unified-attention-diffkv.kernel-reduce-segments-diffkv", "input": SHAPE, "fill": True}]},
                      {"return": {"use_3d": "= vars.use_3d"}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "has_segm_buffers": B(True), "max_seqlen_q": I(1), "spec_3d": B(False),
                                                               "num_seqs": I(2), "seq_threshold_3D": I(16), "batch_invariant": B(False)}},
                     response={"type": "object", "properties": {"use_3d": {"type": "boolean"}}}))
    # FlashMLA FP8 wrappers
    mark(FMLA, "get_mla_metadata_dense_fp8")
    mark(FMLA, "flash_mla_with_kvcache_fp8")
    out.append(op_kernel("flashmla", "get-mla-decoding-metadata-dense-fp8", C(FMLA, ln(FMLA, r"torch.ops._flashmla_extension_C.get_mla_decoding_metadata_dense_fp8\(")), "FlashMLA dense FP8 tile-scheduler metadata op.", "_flashmla_extension_C::get_mla_decoding_metadata_dense_fp8", lat=LAT_META))
    out.append(op_kernel("flashmla", "fwd-kvcache-mla-fp8", C(FMLA, ln(FMLA, r"torch.ops._flashmla_extension_C.fwd_kvcache_mla_fp8\(")), "FlashMLA dense FP8 decode kernel.", "_flashmla_extension_C::fwd_kvcache_mla_fp8"))
    unavailable = [{"if": "!input.flashmla_available",
                    "then": [{"title": "FlashMLA extension not built", "source": Cfn(FMLA, "_raise_flashmla_unavailable"),
                              "fail": {"code": "runtime-error", "message": "vllm._flashmla_C is not available, likely was not compiled due to insufficient nvcc version or a supported arch was not in the list of target arches to compile for."}}]}]
    a, b = fn(FMLA, "get_mla_metadata_dense_fp8")
    out.append(iface("flashmla", "get-mla-metadata-dense-fp8", "get_mla_metadata_dense_fp8: FlashMLA FP8 scheduling metadata, or RuntimeError when the extension is missing.", [C(FMLA, a, b)],
                     unavailable + [{"title": "get_mla_decoding_metadata_dense_fp8", "source": C(FMLA, ln(FMLA, r"get_mla_decoding_metadata_dense_fp8\(", a)), "call": "flashmla.get-mla-decoding-metadata-dense-fp8", "input": SHAPE, "fill": True},
                                    {"return": {"tile_scheduler_metadata": True}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "flashmla_available": B(True)}},
                     errors=[err("runtime-error", "FlashMLA unavailable")]))
    a, b = fn(FMLA, "flash_mla_with_kvcache_fp8")
    out.append(iface("flashmla", "flash-mla-with-kvcache-fp8", "flash_mla_with_kvcache_fp8: FlashMLA dense FP8 decode; softmax_scale defaults to head_dim^-0.5.", [C(FMLA, a, b)],
                     unavailable + [{"if": "input.softmax_scale == null", "then": [{"title": "Default softmax scale", "source": C(FMLA, ln(FMLA, r"softmax_scale = q.shape\[-1\] \*\* \(-0.5\)", a)),
                                                                                    "set": {"vars.scale": "= 1.0 / math.sqrt(576.0)"}}],
                                     "else": [{"set": {"vars.scale": "= input.softmax_scale"}}]},
                                    {"title": "fwd_kvcache_mla_fp8", "source": C(FMLA, ln(FMLA, r"fwd_kvcache_mla_fp8\(", a)), "call": "flashmla.fwd-kvcache-mla-fp8", "input": SHAPE, "fill": True},
                                    {"return": {"softmax_scale": "= vars.scale"}}],
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "flashmla_available": B(True), "softmax_scale": {"type": ["number", "null"], "default": None}}},
                     errors=[err("runtime-error", "FlashMLA unavailable")]))
    return out

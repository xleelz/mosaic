"""Round-4, second pass: the owner-grouped coverage list (code attention owns, from every area's tests).

FlashAttentionImpl.__init__ (the encoder sliding-window FA2 fallback kernels-ops asked for), the backends
utils (decode/prefill split, DCP local lengths, per-layer parameters, KV-cache layout negotiation that
worker-runner calls), the metadata-builder base hooks, the MLAAttentionImpl base methods, backend class
descriptors, the ROCm AITER MLA and sparse-MLA forward routing, HiSparse group caches, UltraQuant slot size,
and the test-hit ROCm kernels that were skipped."""
from core import B, FA_KV_OK, I, QUANT, S, comp, err, iface
from lib import C, Cfn, Cinv, cls, fn, kernel, ln, mark, LAT_META
from round4 import A, ARR_I, Cm, FX, Lin, m, obj, step

BK = "vllm/v1/attention/backend.py"
FA = "vllm/v1/attention/backends/flash_attn.py"
FAU = "vllm/v1/attention/backends/fa_utils.py"
UT = "vllm/v1/attention/backends/utils.py"
CC = "vllm/config/cache.py"
TA = "vllm/v1/attention/backends/triton_attn.py"
FI = "vllm/v1/attention/backends/flashinfer.py"
FIMS = "vllm/v1/attention/backends/mla/flashinfer_mla_sparse.py"
FMS = "vllm/v1/attention/backends/mla/flashmla_sparse.py"
RAM = "vllm/v1/attention/backends/mla/rocm_aiter_mla.py"
RAMSB = "vllm/v1/attention/backends/mla/rocm_aiter_mla_sparse.py"
RAMS = "vllm/v1/attention/ops/rocm_aiter_mla_sparse.py"
IG = "vllm/v1/attention/backends/mla/index_group.py"
UQF = "vllm/v1/attention/ops/ultraquant/format.py"
MX = "vllm/v1/attention/ops/rocm_paged_mxfp4_indexer.py"
SEG = "vllm/v1/attention/ops/segmented_attention.py"

ENUM_ORDER = ["LBHNC", "LBNHC", "LHBNC", "BLHNC", "BLNHC", "BHLNC"]
DEFAULT_PREF = ["LBNHC", "LBHNC", "BLNHC", "BLHNC", "BHLNC", "LHBNC"]


def q(lst):
    return str(lst).replace('"', "'")


def components():
    out = []
    out.append(comp("attention-backend-utils", "v1/attention/backends/utils.py", UT,
                    "Backend helpers: decode/prefill split, DCP-local sequence lengths, FlashInfer per-layer parameters, KV-cache layout negotiation.",
                    a=fn(UT, "get_supported_kv_cache_layouts")[0], b=fn(UT, "record_kv_cache_layout")[1]))
    a = cls(BK, "MLAAttentionImpl")[0]
    out.append(comp("mla-attention-impl", "MLAAttentionImpl", BK, "Base of the MLA impls: forward_mqa (abstract), forward_mha and the default latent KV-cache write.", a=a, b=a))
    a, b = cls(RAM, "AiterMLAImpl")
    out.append(comp("aiter-mla-impl", "AiterMLAImpl", RAM, "ROCm AITER MLA impl: decode routed to Gluon, segmented DCP verify, or the asm persistent decode. ROCm-only.", a=a, b=a))
    a = cls(RAMSB, "ROCMAiterMLASparseImpl")[0]
    out.append(comp("rocm-aiter-mla-sparse-impl", "ROCMAiterMLASparseImpl", RAMSB, "ROCm sparse MLA impl (DeepSeek V3.2): AITER sparse MLA, the AITER asm decode with head buckets, or the ragged Triton path. ROCm-only.", a=a, b=a))
    out.append(comp("ultraquant-format", "ops/ultraquant/format.py", UQF, "UltraQuant KV slot byte layout (FP4 codes + UE8M0 group scales).", a=fn(UQF, "slot_size")[0], b=fn(UQF, "slot_size")[1]))
    out.append(comp("rocm-paged-mxfp4-indexer", "ops/rocm_paged_mxfp4_indexer.py", MX, "ROCm MXFP4 paged indexer top-k. ROCm-only.", a=fn(MX, "_topk")[0], b=fn(MX, "_topk")[1]))
    out.append(comp("segmented-attention", "ops/segmented_attention.py", SEG, "ROCm segmented (split-KV) attention launcher: stage kernel, then a reduce over the splits. ROCm-only.",
                    a=fn(SEG, "_launch_segmented_attention")[0], b=fn(SEG, "_launch_segmented_attention")[1]))
    return out


def fa_init():
    ia, ib = m(FA, "FlashAttentionImpl", "__init__")
    hda, hdb = fn(FAU, "uses_fa4_hd256_kernel")
    beh = [
        {"title": "Sliding window as (left, right): encoder-only layers see both sides, decoders only the past; none is (-1, -1)",
         "source": C(FA, ln(FA, r"if sliding_window is None:", ia), ln(FA, r"self\.sliding_window = \(sliding_window - 1, 0\)", ia)),
         "set": {"vars.sw": "= input.sliding_window <= 0 ? [-1, -1] : (input.attn_type == 'encoder_only' ? [input.sliding_window - 1, input.sliding_window - 1] : [input.sliding_window - 1, 0])",
                 "vars.uses_kv_cache": "= !(input.attn_type in ['encoder', 'encoder_only'])"}},
        {"title": "get_flash_attn_version (FA4 hd256 allowed)", "source": C(FA, ln(FA, r"self\.vllm_flash_attn_version = get_flash_attn_version\(", ia)),
         "call": "fa-utils.get-flash-attn-version",
         "input": {"device_capability_major": "= input.device_capability_major", "requires_alibi": "= input.has_alibi", "head_size": "= input.head_size",
                   "has_sinks": "= input.has_sinks"}, "as": "v"},
        {"title": "uses_fa4_hd256_kernel: FA4 with head 256 (and V 256) on SM100/SM110", "source": C(FAU, hda, hdb),
         "set": {"vars.ver": "= vars.v.value.fa_version", "vars.hd256": "= vars.v.value.fa_version == 4 && input.head_size == 256 && input.device_capability_major in [10, 11]"}},
        {"if": "vars.hd256 && !vars.uses_kv_cache && input.sliding_window > 0",
         "then": [{"title": "FA4's hd256 kernel needs seqused_k for local attention: encoder inputs with a window fall back to FA2",
                   "source": C(FA, ln(FA, r"if self\.fa4_hd256 and not uses_kv_cache and sliding_window is not None:", ia), ln(FA, r"self\.fa4_hd256 = False", ia)),
                   "set": {"vars.ver": 2, "vars.hd256": False}}]},
        {"if": QUANT + " && !" + FA_KV_OK.replace("MAJOR", "input.device_capability_major").replace("VER", "vars.v.value.fa_version").replace("HEAD", "input.head_size"),
         "then": [{"title": "A quantized KV cache this FA version can't read", "source": C(FA, ln(FA, r"if is_quantized_kv_cache\(", ia), ln(FA, r"\" kv-cache on this device\.\"", ia)),
                   "fail": {"code": "not-implemented-error", "message": "= 'FlashAttention does not support ' + input.kv_cache_dtype + ' kv-cache on this device.'"}}]},
        {"title": "Soft cap 0 means none; queries per KV head", "source": C(FA, ln(FA, r"if logits_soft_cap is None:", ia), ln(FA, r"self\.num_queries_per_kv = self\.num_heads // self\.num_kv_heads", ia)),
         "return": {"sliding_window": "= vars.sw", "fa_version": "= vars.ver", "fa4_hd256": "= vars.hd256", "uses_kv_cache": "= vars.uses_kv_cache",
                    "logits_soft_cap": "= input.logits_soft_cap", "num_queries_per_kv": "= input.num_heads / input.num_kv_heads"}},
    ]
    return iface("flash-attention-impl", "init", "FlashAttentionImpl.__init__: the window tuple per attention type, the FA version (an encoder layer with a window falls back from FA4's hd256 kernel to FA2), and the quantized-KV support check.",
                 [C(FA, ia, ib), C(FAU, hda, hdb)], beh,
                 request=obj({"num_heads": I(32), "num_kv_heads": I(8), "head_size": I(128), "sliding_window": I(0), "attn_type": S("decoder"),
                              "kv_cache_dtype": S("auto"), "logits_soft_cap": {"type": "number", "default": 0}, "has_alibi": B(False), "has_sinks": B(False),
                              "device_capability_major": I(9)}),
                 response=obj({"fa_version": {"type": ["integer", "null"]}, "sliding_window": ARR_I}),
                 errors=[err("not-implemented-error", "unsupported quantized KV cache")])


def utils_interfaces():
    out = []
    sa, sb = fn(UT, "split_decodes_and_prefills")
    ql = "lists.range(input.num_reqs).map(i, input.query_start_loc_cpu[i + 1] - input.query_start_loc_cpu[i])"
    beh = [
        {"if": "input.max_query_len <= input.decode_threshold && (!input.require_uniform || input.decode_threshold <= 1) && input.treat_short_extends_as_decodes",
         "then": [{"title": "Every request is a decode", "source": C(UT, ln(UT, r"max_query_len <= decode_threshold", sa), ln(UT, r"return num_reqs, 0, num_tokens, 0", sa)),
                   "return": {"num_decodes": "= input.num_reqs", "num_prefills": 0, "num_decode_tokens": "= input.num_actual_tokens", "num_prefill_tokens": 0}}]},
        {"set": {"vars.q": "= " + ql}},
        {"if": "vars.q[0] > input.decode_threshold",
         "then": [{"title": "The batch is reordered decode-first: a prefill first means no decodes", "source": C(UT, ln(UT, r"if query_lens\[0\]\.item\(\) > decode_threshold:", sa)),
                   "return": {"num_decodes": 0, "num_prefills": "= input.num_reqs", "num_decode_tokens": 0, "num_prefill_tokens": "= input.num_actual_tokens"}}]},
        {"if": "input.require_uniform",
         "then": [{"if": "input.treat_short_extends_as_decodes && vars.q.all(x, x == vars.q[0] || x == 0)",
                   "then": [{"title": "A padded uniform batch (zero-length padding rows) is all decodes", "source": C(UT, ln(UT, r"if treat_short_extends_as_decodes and torch\.all\(", sa)),
                             "return": {"num_decodes": "= input.num_reqs", "num_prefills": 0, "num_decode_tokens": "= input.num_actual_tokens", "num_prefill_tokens": 0}}]},
                  {"set": {"vars.p": "= vars.q.map(x, x != vars.q[0] && x != 0)"}}],
         "else": [{"title": "A prefill is any query longer than the threshold", "source": C(UT, ln(UT, r"is_prefill = query_lens > decode_threshold", sa)),
                   "set": {"vars.p": "= vars.q.map(x, x > input.decode_threshold)"}}]},
        {"if": "!input.treat_short_extends_as_decodes",
         "then": [{"title": "Short extends still prefilling count as prefills", "source": C(UT, ln(UT, r"is_prefill \|= common_attn_metadata\.is_prefilling", sa)),
                   "set": {"vars.p": "= lists.range(input.num_reqs).map(i, vars.p[i] || input.is_prefilling[i])"}}]},
        {"if": "!vars.p.exists(x, x)",
         "then": [{"title": "No prefill", "source": C(UT, ln(UT, r"if not torch\.any\(is_prefill\):", sa)),
                   "return": {"num_decodes": "= input.num_reqs", "num_prefills": 0, "num_decode_tokens": "= input.num_actual_tokens", "num_prefill_tokens": 0}}]},
        {"title": "The first prefill splits the batch", "source": C(UT, ln(UT, r"first_prefill = is_prefill\.int\(\)\.argmax", sa), sb),
         "set": {"vars.f": "= vars.p.indexOf(true)"}},
        {"return": {"num_decodes": "= vars.f", "num_prefills": "= input.num_reqs - vars.f", "num_decode_tokens": "= input.query_start_loc_cpu[vars.f]",
                    "num_prefill_tokens": "= input.num_actual_tokens - input.query_start_loc_cpu[vars.f]"}},
    ]
    out.append(iface("attention-backend-utils", "split-decodes-and-prefills", "split_decodes_and_prefills: on a decode-first batch, where decodes end (by threshold, uniformity and still-prefilling short extends).",
                     [C(UT, sa, sb)], beh,
                     request=obj({"query_start_loc_cpu": A([0, 1, 2, 7]), "num_reqs": I(3), "num_actual_tokens": I(7), "max_query_len": I(5), "decode_threshold": I(1),
                                  "require_uniform": B(False), "treat_short_extends_as_decodes": B(True), "is_prefilling": {"type": "array", "items": {"type": "boolean"}, "default": []}}),
                     response=obj({"num_decodes": {"type": "integer"}, "num_prefills": {"type": "integer"}, "num_decode_tokens": {"type": "integer"}, "num_prefill_tokens": {"type": "integer"}})))
    da, db = fn(UT, "get_dcp_local_seq_lens")
    bse = "(s / vars.I / input.dcp_size * vars.I)"
    loc = lambda r: f"({bse} + math.least(math.greatest(s - {bse} * input.dcp_size - {r} * vars.I, 0), vars.I))"
    beh = [
        {"set": {"vars.I": "= input.cp_kv_cache_interleave_size"}},
        {"if": "input.dcp_rank < 0",
         "then": [{"title": "No rank: one column per DCP rank", "source": C(UT, ln(UT, r"if dcp_rank is None:", da), ln(UT, r"seq_lens_tiled = seq_lens_i32\.unsqueeze\(-1\)", da)),
                   "return": {"local_seq_lens": "= input.seq_lens.map(s, lists.range(input.dcp_size).map(r, " + loc("r") + "))"}}]},
        {"title": "Round-robin interleave: whole interleaves per rank, plus this rank's share of the remainder", "source": C(UT, ln(UT, r"base = \(", da), db),
         "return": {"local_seq_lens": "= input.seq_lens.map(s, " + loc("input.dcp_rank") + ")"}},
    ]
    out.append(iface("attention-backend-utils", "get-dcp-local-seq-lens", "get_dcp_local_seq_lens: the KV tokens each DCP rank holds of each sequence under round-robin interleaving (dcp_rank -1 means every rank).",
                     [C(UT, da, db)], beh,
                     request=obj({"seq_lens": A([10, 3]), "dcp_size": I(2), "dcp_rank": I(-1), "cp_kv_cache_interleave_size": I(1)}),
                     response=obj({"local_seq_lens": {"type": "array"}})))
    pa, pb = fn(UT, "get_per_layer_parameters")
    beh = [
        {"if": "input.layers.exists(l, has(l.impl_matches) && !l.impl_matches)",
         "then": [{"title": "Every layer's impl must be (a variant of) the backend's impl class", "source": C(UT, ln(UT, r"assert impl is not None", pa)),
                   "fail": {"code": "assertion-error", "message": ""}}]},
        {"title": "window_left from the impl's sliding window (or -1), the soft cap, the scale, and whether it has sinks", "source": C(UT, ln(UT, r"window_size = getattr\(impl, \"sliding_window\", None\)", pa), pb),
         "return": {"params": "= input.layers.map(l, {'name': l.name, 'window_left': has(l.sliding_window) && size(l.sliding_window) > 0 ? l.sliding_window[0] : -1, "
                              "'logits_soft_cap': has(l.logits_soft_cap) ? l.logits_soft_cap : null, 'sm_scale': l.scale, 'has_sinks': has(l.has_sinks) && l.has_sinks})"}},
    ]
    out.append(iface("attention-backend-utils", "get-per-layer-parameters", "get_per_layer_parameters: each FlashInfer layer's PerLayerParameters (window_left, logits_soft_cap, sm_scale, has_sinks) for plan().",
                     [C(UT, pa, pb), C(UT, *cls(UT, "PerLayerParameters"))], beh,
                     request=obj({"layers": {"type": "array", "items": {"type": "object"}, "default": [{"name": "model.layers.0.self_attn.attn", "sliding_window": [], "scale": 0.088}]}}),
                     response=obj({"params": {"type": "array"}}), errors=[err("assertion-error", "impl class mismatch")]))
    ga, gb = fn(UT, "get_supported_kv_cache_layouts")
    prio = "size(vars.d.filter(x, x[0] == l))"
    beh = [
        {"title": "Backends that declare their layouts (most preferred first); none declaring means the default preference (LBNHC first)",
         "source": C(UT, ln(UT, r"supported_layouts_lists: list\[Sequence\[KVCacheLayout\]\] = \[", ga), ln(UT, r"\] or \[_DEFAULT_LAYOUT_PREFERENCE\]", ga)),
         "set": {"vars.d": "= size(input.backend_layouts.filter(x, size(x) > 0)) > 0 ? input.backend_layouts.filter(x, size(x) > 0) : [" + q(DEFAULT_PREF) + "]"}},
        {"if": "vars.d.all(x, x == vars.d[0])",
         "then": [{"title": "Identical declarations keep their order", "source": C(UT, ln(UT, r"if all\(layouts == first for layouts in supported_layouts_lists\[1:\]\):", ga)),
                   "return": {"layouts": "= vars.d[0]"}}]},
        {"title": "The layouts everyone supports, ranked by how many backends put each first (ties in enum order)",
         "source": C(UT, ln(UT, r"priorities: dict\[KVCacheLayout, int\] = defaultdict\(int\)", ga), ln(UT, r"reverse=True,", ga)),
         "set": {"vars.c": "= lists.range(size(vars.d) + 1).map(i, size(vars.d) - i).map(p, " + q(ENUM_ORDER) + ".filter(l, vars.d.all(x, l in x) && " + prio + " == p)).flatten()"}},
        {"if": "size(vars.c) == 0",
         "then": [{"title": "An empty intersection is a hard error", "source": C(UT, ln(UT, r"if not candidates:", ga), gb),
                   "fail": {"code": "value-error", "message": "= 'No KV cache layout satisfies every supported set: [' + vars.d.map(s, '[' + s.map(x, \"'\" + x + \"'\").join(', ') + ']').join(', ') + '].'"}}]},
        {"return": {"layouts": "= vars.c"}},
    ]
    out.append(iface("attention-backend-utils", "get-supported-kv-cache-layouts", "get_supported_kv_cache_layouts: the KV-cache layouts every backend of the worker supports, most preferred first; ValueError when none.",
                     [C(UT, ga, gb), Lin(BK, r"def supported_kv_cache_layouts\(cls\)"), Cm(FI, "FlashInferBackend", "supported_kv_cache_layouts")], beh,
                     request=obj({"backend_layouts": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}, "default": [],
                                                      "description": "each backend's supported_kv_cache_layouts(); [] for a backend that returns None"}}),
                     response=obj({"layouts": {"type": "array", "items": {"type": "string"}, "examples": [["LBNHC", "LBHNC"]]}}),
                     errors=[err("value-error", "no common layout")]))
    ra, rb = fn(UT, "record_kv_cache_layout")
    la, lb = fn(CC, "_layout_from_name")
    beh = [
        {"title": "Legacy names: NHD is LBNHC, HND is LBHNC", "source": C(CC, ln(CC, r"^_LAYOUT_COMPAT_ALIASES = \{"), ln(CC, r"^_LAYOUT_COMPAT_ALIASES = \{") + 3),
         "set": {"vars.l": "= input.kv_cache_layout == 'NHD' ? 'LBNHC' : (input.kv_cache_layout == 'HND' ? 'LBHNC' : input.kv_cache_layout)"}},
        {"if": "!(vars.l in " + q(ENUM_ORDER) + ")",
         "then": [{"title": "Unknown layout name", "source": C(CC, la, lb), "fail": {"code": "value-error", "message": "= \"Unknown KV cache layout '\" + vars.l + \"'. Valid layouts: " + "[" + ", ".join("'" + x + "'" for x in ENUM_ORDER) + "]" + "\""}}]},
        {"if": "input.existing_layout != '' && input.existing_layout != vars.l",
         "then": [{"title": "A layout already resolved can't change", "source": C(UT, ln(UT, r"if existing is not None and existing != layout\.name:", ra)),
                   "fail": {"code": "value-error", "message": "= 'KV cache layout is already resolved to ' + input.existing_layout + '; cannot change it to ' + vars.l + '.'"}}]},
        {"title": "cache_config.kv_cache_layout takes the canonical name", "source": C(UT, ln(UT, r"cache_config\.kv_cache_layout = layout\.name", ra)),
         "return": {"ok": True, "kv_cache_layout": "= vars.l"}},
    ]
    out.append(iface("attention-backend-utils", "record-kv-cache-layout", "record_kv_cache_layout: adopt the engine core's layout in this process (legacy NHD/HND accepted); a different already-resolved layout is a ValueError.",
                     [C(UT, ra, rb), C(CC, la, lb)], beh,
                     request=obj({"kv_cache_layout": {"type": "string", "examples": ["NHD"]}, "existing_layout": S("", description="cache_config.kv_cache_layout before the call ('' = None)")}),
                     response=obj({"ok": {"type": "boolean", "examples": [True]}, "kv_cache_layout": {"type": "string"}}),
                     errors=[err("value-error", "unknown or conflicting layout")]))
    return out


def builder_base_interfaces():
    out = []
    ca, cb = m(BK, "AttentionMetadataBuilder", "build_for_cudagraph_capture")
    out.append(iface("attention-metadata-builder", "build-for-cudagraph-capture", "AttentionMetadataBuilder.build_for_cudagraph_capture: by default just build(common_prefix_len=0) (FlashAttention keeps the default).",
                     [C(BK, ca, cb)],
                     [{"if": "input.backend != 'FLASH_ATTN'",
                       "then": [{"title": "Other builders aren't simulated here", "source": C(BK, ca, cb), "fail": {"code": "not-implemented-error", "message": "= 'build of ' + input.backend + ' is not modeled'"}}]},
                      {"title": "self.build(common_prefix_len=0, common_attn_metadata)", "source": C(BK, ln(BK, r"return self\.build\(", ca), cb),
                       "call": "flash-attention-metadata-builder.build", "input": {"common": "= input.common", "fast_build": False}, "as": "b"},
                      {"return": {"num_actual_tokens": "= vars.b.value.num_actual_tokens", "max_num_splits": "= vars.b.value.max_num_splits"}}],
                     request=obj({"backend": S("FLASH_ATTN"), "common": {"$ref": "AttnCommonMetadata"}}),
                     response=obj({"num_actual_tokens": {"type": "integer"}}), errors=[err("not-implemented-error", "builder not modeled")]))
    va, vb = m(BK, "AttentionMetadataBuilder", "get_varlen_cudagraph_max_query_len")
    fa_, fb_ = m(FI, "FlashInferMetadataBuilder", "get_varlen_cudagraph_max_query_len")
    sa, sb = fn(FIMS, "get_varlen_cudagraph_max_query_len")
    mdq = "(input.num_speculative_tokens > 0 ? 1 + input.num_speculative_tokens : 1)"
    beh = [
        {"if": "input.backend == 'FLASHINFER_MLA_SPARSE'",
         "then": [{"title": "Sparse FlashInfer MLA decodes on device request boundaries: the widest decode", "source": C(FIMS, sa, sb), "return": {"max_query_len": "= " + mdq}}]},
        {"if": "input.backend == 'FLASHINFER'",
         "then": [{"call": "attention-metadata-builder.get-cudagraph-support", "input": {"backend": "FLASHINFER", "all_specs_trtllm": "= input.all_specs_trtllm"}, "as": "s"},
                  {"title": "FlashInfer: only past the UNIFORM_BATCH gate, and only with trtllm-gen varlen decode", "source": C(FI, fa_, fb_),
                   "return": {"max_query_len": "= vars.s.value.support == 'UNIFORM_BATCH' && input.trtllm_gen_varlen ? dyn(" + mdq + ") : dyn(null)"}}]},
        {"title": "Base: no variable-length replay (ALWAYS builders replay anything)", "source": C(BK, va, vb), "return": {"max_query_len": None}},
    ]
    out.append(iface("attention-metadata-builder", "get-varlen-cudagraph-max-query-len", "get_varlen_cudagraph_max_query_len: the longest per-request query a FULL graph of the builder can replay (None by default).",
                     [C(BK, va, vb), C(FI, fa_, fb_), C(FIMS, sa, sb), Cfn(BK, "max_decode_query_len")], beh,
                     request=obj({"backend": S("FLASH_ATTN"), "num_speculative_tokens": I(0), "all_specs_trtllm": B(True), "trtllm_gen_varlen": B(True)}),
                     response=obj({"max_query_len": {"type": ["integer", "null"]}})))
    ua, ub = m(BK, "AttentionMetadataBuilder", "update_draft_decode_metadata")
    fua, fub = m(FA, "FlashAttentionMetadataBuilder", "update_draft_decode_metadata")
    tua, tub = m(TA, "TritonAttentionMetadataBuilder", "update_draft_decode_metadata")
    beh = [
        {"if": "input.backend == 'TRITON_ATTN'",
         "then": [{"title": "Triton: nothing to refresh", "source": C(TA, tua, tub), "return": {"refreshed": False}}]},
        {"if": "input.backend == 'FLASH_ATTN'",
         "then": [{"if": "!input.has_scheduler_metadata",
                   "then": [{"title": "No AOT scheduler metadata: nothing to refresh", "source": C(FA, ln(FA, r"if metadata\.scheduler_metadata is None:", fua)), "return": {"refreshed": False}}]},
                  {"if": "input.dcp_world_size != 1",
                   "then": [{"title": "Draft refresh needs DCP 1", "source": C(FA, ln(FA, r"assert self\.dcp_world_size == 1", fua)),
                             "fail": {"code": "assertion-error", "message": ""}}]},
                  {"title": "Recompute the AOT scheduler metadata in place (capture-safe)", "source": C(FA, fua, fub), "return": {"refreshed": True}}]},
        {"title": "Base: builders that don't support draft refresh", "source": C(BK, ua, ub), "fail": {"code": "not-implemented-error", "message": ""}},
    ]
    out.append(iface("attention-metadata-builder", "update-draft-decode-metadata", "update_draft_decode_metadata: refresh draft-decode metadata in place inside a speculator's graph (FA recomputes AOT scheduling, Triton has nothing to do, the base raises).",
                     [C(BK, ua, ub), C(FA, fua, fub), C(TA, tua, tub)], beh,
                     request=obj({"backend": S("FLASH_ATTN"), "has_scheduler_metadata": B(True), "dcp_world_size": I(1)}),
                     response=obj({"refreshed": {"type": "boolean"}}), errors=[err("not-implemented-error", "unsupported"), err("assertion-error", "DCP")]))
    return out


def mla_impl_interfaces():
    out = []
    fa_, fb_ = m(BK, "MLAAttentionImpl", "forward_mqa")
    beh = [
        {"if": "input.backend == 'FLASHINFER_MLA'",
         "then": [{"call": "flashinfer-mla-impl.forward-mqa", "input": {"num_decode_tokens": "= input.num_decode_tokens", "query_heads": "= input.num_heads"}, "as": "o"},
                  {"return": {"impl": "FlashInferMLAImpl", "output_shape": "= vars.o.value.output_shape"}}]},
        {"if": "input.backend == 'TRITON_MLA'",
         "then": [{"call": "triton-mla-impl.forward-mqa", "input": {"num_tokens": "= input.num_decode_tokens", "num_seqs": "= input.num_decode_tokens", "num_heads": "= input.num_heads"}},
                  {"return": {"impl": "TritonMLAImpl", "output_shape": "= [input.num_decode_tokens, input.num_heads, 512]"}}]},
        {"if": "input.backend == 'ROCM_AITER_MLA'",
         "then": [{"call": "aiter-mla-impl.forward-mqa", "input": {"num_heads": "= input.num_heads", "num_tokens": "= input.num_decode_tokens"}, "as": "o"},
                  {"return": {"impl": "AiterMLAImpl", "output_shape": "= [input.num_decode_tokens, input.num_heads, 512]"}}]},
        {"if": "input.backend == ''",
         "then": [{"title": "Abstract on the base class", "source": C(BK, fa_, fb_), "fail": {"code": "not-implemented-error", "message": ""}}]},
        {"title": "Another concrete backend's forward_mqa (not simulated by this model)", "source": C(BK, fa_, fb_),
         "return": {"impl": "= input.backend", "output_shape": "= [input.num_decode_tokens, input.num_heads, 512]"}},
    ]
    out.append(iface("mla-attention-impl", "forward-mqa", "MLAAttentionImpl.forward_mqa: abstract; each MLA backend's impl overrides it (dispatched by the selected backend).",
                     [C(BK, fa_, fb_)], beh, request=obj({"backend": S("FLASHINFER_MLA"), "num_decode_tokens": I(2), "num_heads": I(16)}),
                     response=obj({"impl": {"type": "string"}}), errors=[err("not-implemented-error", "abstract")]))
    ha, hb = m(BK, "MLAAttentionImpl", "forward_mha")
    out.append(iface("mla-attention-impl", "forward-mha", "MLAAttentionImpl.forward_mha: MHA-style prefill; the base raises, and the MLA common impl (models-layers), AITER and AMX override it.",
                     [C(BK, ha, hb), Cm(RAM, "AiterMLAImpl", "forward_mha")],
                     [{"if": "!(input.backend in ['MLA_COMMON', 'ROCM_AITER_MLA', 'AMX_MLA'])",
                       "then": [{"title": "Not overridden", "source": C(BK, ln(BK, r"raise NotImplementedError", ha), hb), "fail": {"code": "not-implemented-error", "message": ""}}]},
                      {"title": "The override runs the prefill", "source": Cm(RAM, "AiterMLAImpl", "forward_mha"), "return": {"impl": "= input.backend"}}],
                     request=obj({"backend": S("MLA_COMMON")}), response=obj({"impl": {"type": "string"}}), errors=[err("not-implemented-error", "not overridden")]))
    ka, kb = m(BK, "MLAAttentionImpl", "do_kv_cache_update")
    out.append(iface("mla-attention-impl", "do-kv-cache-update", "MLAAttentionImpl.do_kv_cache_update: write the latent and RoPE rows with concat_and_cache_mla; an empty cache (profiling) writes nothing. CPU MLA overrides it.",
                     [C(BK, ka, kb)],
                     [{"if": "input.backend == 'CPU_MLA'",
                       "then": [{"call": "cpu-mla-impl.do-kv-cache-update", "input": {"slot_mapping": "= input.slot_mapping"}, "as": "c"},
                                {"return": {"written": "= vars.c.value.written"}}]},
                      {"if": "input.cache_numel == 0",
                       "then": [{"title": "No cache yet: nothing to write", "source": C(BK, ln(BK, r"if kv_cache\.numel\(\) == 0:", ka)), "return": {"written": 0}}]},
                      {"title": "ops.concat_and_cache_mla over the flattened slot mapping", "source": C(BK, ln(BK, r"ops\.concat_and_cache_mla\(", ka), kb),
                       "call": "custom-ops.concat-and-cache-mla", "input": {"num_tokens": "= size(input.slot_mapping)", "hidden_size": 576, "dtype_bytes": 2}},
                      {"return": {"written": "= size(input.slot_mapping.filter(s, s >= 0))"}}],
                     request=obj({"backend": S("FLASHMLA"), "cache_numel": I(1), "slot_mapping": A([0, 1, -1])}), response=obj({"written": {"type": "integer"}})))
    return out


def concat_stub():
    return {"component": "custom-ops", "name": "concat-and-cache-mla", "kind": "function",
            "summary": "Boundary stub: _custom_ops.concat_and_cache_mla -> torch.ops._C_cache_ops.concat_and_cache_mla (copied from kernels-ops).",
            "sources": [Cfn("vllm/_custom_ops.py", "concat_and_cache_mla")], "attributes": {"boundary": True, "owner": "kernels-ops"},
            "request": {"type": "object", "properties": {"num_tokens": {"type": "integer", "minimum": 0}, "hidden_size": {"type": "integer", "minimum": 1}, "dtype_bytes": {"type": "integer"}}},
            "latency_ms": 0}


def describe_interface():
    rows = {
        "FLASH_ATTN": {"name": "FLASH_ATTN", "builder": "FlashAttentionMetadataBuilder", "impl": "FlashAttentionImpl", "kernel_block_sizes": ["MultipleOf(16)"], "layouts": None},
        "TRITON_ATTN": {"name": "TRITON_ATTN", "builder": "TritonAttentionMetadataBuilder", "impl": "TritonAttentionImpl", "kernel_block_sizes": ["MultipleOf(16)"], "layouts": None},
        "FLASHINFER_MLA_SPARSE": {"name": "FLASHINFER_MLA_SPARSE", "builder": "FlashInferMLASparseTRTLLMMetadataBuilder", "impl": "FlashInferMLASparseImpl", "kernel_block_sizes": ["MultipleOf(32)"], "layouts": None},
        "FLASHMLA_SPARSE": {"name": "FLASHMLA_SPARSE", "builder": "FlashMLASparseMetadataBuilder", "impl": "FlashMLASparseImpl", "kernel_block_sizes": ["MultipleOf(64)"], "layouts": None},
        "ROCM_AITER_MLA_SPARSE": {"name": "ROCM_AITER_MLA_SPARSE", "builder": "ROCMAiterMLASparseMetadataBuilder", "impl": "ROCMAiterMLASparseImpl", "kernel_block_sizes": [1, "MultipleOf(16)"],
                                  "layouts": ["LBNHC", "LBHNC", "BLHNC"]},
    }
    srcs = [Cm(FA, "FlashAttentionBackend", "get_name"), C(TA, *cls(TA, "TritonAttentionBackend")), Cm(FIMS, "_FlashInferMLASparseBackendBase", "get_builder_cls"),
            C(RAMSB, *cls(RAMSB, "ROCMAiterMLASparseBackend")), C(BK, *cls(BK, "MultipleOf"))]
    import json
    table = json.dumps(rows).replace("null", "null").replace('"', "'")
    IDX = "vllm/v1/attention/backends/mla/indexer.py"
    DG = "vllm/utils/deep_gemm.py"
    pga, pgb = fn(DG, "get_paged_mqa_page_sizes")
    dsa, dsb = m(IDX, "DeepseekV32IndexerBackend", "get_supported_kernel_block_sizes")
    gla, glb = m(IDX, "Glm5NextIndexerBackend", "get_supported_kernel_block_sizes")
    kta, ktb = cls(IDX, "KpoolTailBackend")
    pages = "(input.device_capability_family == 120 ? [64] : [32, 64])"
    beh = [
        {"if": "input.backend in ['DEEPSEEK_V32_INDEXER', 'DeepseekV32IndexerBackend', 'Glm5NextIndexerBackend', 'KPOOL_TAIL', 'KpoolTailBackend']",
         "then": [
             {"if": "input.backend in ['KPOOL_TAIL', 'KpoolTailBackend']",
              "then": [{"title": "KpoolTailBackend: storage-only GLM-5.3-Flash kpool tail cache, BLHNC layout, any block size", "source": C(IDX, kta, ktb),
                        "return": {"name": "KPOOL_TAIL", "builder": "KpoolTailMetadataBuilder", "impl": "", "kernel_block_sizes": ["MultipleOf(1)"], "layouts": ["BLHNC"]}}]},
             {"if": "input.backend == 'Glm5NextIndexerBackend'",
              "then": [{"if": "input.kv_cache_spec != null",
                        "then": [{"title": "With a spec (the worker's get_kv_cache_spec): index_kpool is the spec's tokens_per_state", "source": C(IDX, ln(IDX, r"if kv_cache_spec is not None:", gla), ln(IDX, r"index_kpool = int\(kv_cache_spec\.tokens_per_state\)", gla)),
                                  "set": {"vars.kpool": "= int(input.kv_cache_spec.tokens_per_state)"}}],
                        "else": [{"title": "Without one (platform block-size selection): hf_text_config.index_kpool of the current config", "source": C(IDX, ln(IDX, r"model_config = get_current_vllm_config\(\)\.model_config", gla), ln(IDX, r"index_kpool = model_config\.hf_text_config\.index_kpool", gla)),
                                  "set": {"vars.kpool": "= input.index_kpool"}}]},
                       {"title": "index_kpool times each DeepGEMM paged-MQA page size: (32, 64), only 64 on SM120 (the same on ROCm)", "source": C(DG, pga, pgb),
                        "return": {"name": "DEEPSEEK_V32_INDEXER", "builder": "DeepseekV32IndexerMetadataBuilder", "impl": "",
                                   "kernel_block_sizes": "= " + pages + ".map(n, vars.kpool * n)", "layouts": None}}]},
             {"title": "DeepseekV32IndexerBackend: [1, MultipleOf(16)] on ROCm, else [64]", "source": C(IDX, dsa, dsb),
              "return": {"name": "DEEPSEEK_V32_INDEXER", "builder": "DeepseekV32IndexerMetadataBuilder", "impl": "",
                         "kernel_block_sizes": "= input.is_rocm ? [dyn(1), dyn('MultipleOf(16)')] : [dyn(64)]", "layouts": None}}]},
        {"if": "!(input.backend in " + table + ")",
         "then": [{"title": "Not a described backend class", "source": C(BK, *cls(BK, "AttentionBackend")[:1]), "fail": {"code": "key-error", "message": "= \"'\" + input.backend + \"'\""}}]},
        {"title": "The class's static descriptors: get_name, get_builder_cls, get_impl_cls, kernel block sizes (ints, or MultipleOf(n): any multiple of n), supported KV layouts",
         "source": srcs[0], "set": {"vars.r": "= " + table + "[input.backend]"}},
        {"return": {"name": "= vars.r.name", "builder": "= vars.r.builder", "impl": "= vars.r.impl", "kernel_block_sizes": "= vars.r.kernel_block_sizes", "layouts": "= vars.r.layouts"}},
    ]
    # the FlashMLA sparse + FlashInfer sparse SM90 descriptors are cited by their supports-combination interfaces
    return iface("attention-backend", "describe", "AttentionBackend class descriptors for the modeled backends (by get_name, or by class name where two classes share one): name, builder and impl classes, kernel block sizes and KV layouts, including the MLA indexer backends.",
                 srcs + [C(IDX, dsa, dsb), C(IDX, gla, glb), C(DG, pga, pgb)], beh,
                 request=obj({"backend": S("FLASH_ATTN"), "is_rocm": B(False), "device_capability_family": I(90),
                              "kv_cache_spec": {"type": ["object", "null"], "default": None}, "index_kpool": {"type": ["integer", "null"], "default": None}}),
                 response=obj({"name": {"type": "string"}, "builder": {"type": "string"}, "impl": {"type": "string"}}), errors=[err("key-error", "unknown backend")])


def rocm_impl_interfaces():
    out = []
    fa_, fb_ = m(RAM, "AiterMLAImpl", "forward_mqa")
    beh = [
        {"if": "!input.has_decode || input.cache_numel == 0",
         "then": [{"title": "forward_mqa needs decode metadata and a cache", "source": C(RAM, ln(RAM, r"assert kv_c_and_k_pe_cache\.numel\(\) > 0", fa_), ln(RAM, r"assert attn_metadata\.decode is not None", fa_)),
                   "fail": {"code": "assertion-error", "message": ""}}]},
        {"if": "input.use_gluon_decode",
         "then": [{"title": "Small-head single-token decode on the Gluon kernel", "source": C(RAM, ln(RAM, r"if decode\.use_gluon_decode:", fa_), ln(RAM, r"return o, None", fa_)),
                   "return": {"path": "gluon-decode", "heads": "= input.num_heads", "returns_lse": False}}]},
        {"if": "input.use_gluon_verify",
         "then": [{"if": "input.num_reqs * input.qlen != input.num_tokens",
                   "then": [{"title": "The flattened verify block must be num_reqs x qlen rows", "source": C(RAM, ln(RAM, r"if num_reqs \* qlen != B:", fa_)),
                             "fail": {"code": "value-error", "message": "= 'verify block ' + string(input.num_tokens) + ' rows is not a multiple of qlen ' + string(input.qlen)"}}]},
                  {"title": "Multi-token verify on Gluon's 4-D MTP entry", "source": C(RAM, ln(RAM, r"if decode\.use_gluon_verify:", fa_)),
                   "return": {"path": "gluon-verify", "heads": "= input.num_heads", "returns_lse": False}}]},
        {"if": "input.dcp_route == 'segmented'",
         "then": [{"title": "DCP verify on segmented MLA", "source": C(RAM, ln(RAM, r"if dcp_route is _DCPDecodeRoute\.SEGMENTED:", fa_)),
                   "return": {"path": "segmented", "heads": "= input.num_heads", "returns_lse": True}}]},
        {"title": "asm persistent decode: heads padded to the next multiple of 16 (cprr pads to a native 16/32/64/128), LSE returned under DCP",
         "source": C(RAM, ln(RAM, r"if self\.dcp_world_size > 1:", fa_), fb_),
         "return": {"path": "= input.dcp_route == 'cprr' ? 'asm-cprr' : 'asm'",
                    "heads": "= input.dcp_route == 'cprr' ? [16, 32, 64, 128].filter(h, h >= input.num_heads)[0] : ((input.num_heads + 15) / 16) * 16",
                    "returns_lse": "= input.dcp_world_size > 1"}},
    ]
    out.append(iface("aiter-mla-impl", "forward-mqa", "AiterMLAImpl.forward_mqa: decode on Gluon (the builder's use_gluon_decode / use_gluon_verify), on segmented MLA for DCP verify, or on the padded asm decode (cprr under DCP).",
                     [C(RAM, fa_, fb_), Cm(RAM, "AiterMLAHelper", "get_actual_mla_num_heads")], beh,
                     request=obj({"has_decode": B(True), "cache_numel": I(1), "use_gluon_decode": B(False), "use_gluon_verify": B(False), "dcp_route": S("plain", enum=["plain", "segmented", "cprr"]),
                                  "num_heads": I(16), "num_reqs": I(2), "qlen": I(1), "num_tokens": I(2), "dcp_world_size": I(1)}),
                     response=obj({"path": {"type": "string"}, "heads": {"type": "integer"}}), errors=[err("assertion-error", "no decode metadata"), err("value-error", "bad verify block")]))
    qa, qb = m(RAMSB, "ROCMAiterMLASparseImpl", "forward_mqa")
    la, lb = m(RAMSB, "ROCMAiterMLASparseImpl", "_forward_mla")
    tri = "(!input.kv_cache_dtype.startsWith('fp8') && input.head_size == input.kv_lora_rank && (input.num_prefills > 0 || input.num_decodes > 0))"
    heads = "((input.num_heads + 15) / 16 * 16)"
    beh = [
        {"title": "Top-k slots converted to global indices; an fp8 cache quantizes the query", "source": C(RAMSB, ln(RAMSB, r"fp8_attention = self\.kv_cache_dtype\.startswith\(\"fp8\"\)", qa), ln(RAMSB, r"q = q\.view\(original_q_shape\)", qa)),
         "call": "sparse-utils.triton-convert-req-index-to-global-index", "input": {"shape": {"num_tokens": "= input.num_tokens"}}},
        {"if": "input.use_aiter_sparse_mla",
         "then": [{"title": "AITER's sparse MLA kernel", "source": C(RAMSB, ln(RAMSB, r"if self\.use_aiter_sparse_mla:", qa)), "return": {"path": "aiter-sparse", "heads": "= input.num_heads", "lse": False}}]},
        {"title": "_forward_mla: sinks need an LSE; fallbacks for shapes the AITER return-LSE kernels lack",
         "source": C(RAMSB, ln(RAMSB, r"triton_sink_fallback = \(", la), ln(RAMSB, r"triton_prefill_fallback = \(", la) + 5),
         "set": {"vars.sinkfb": f"= input.has_sinks && (input.q_dtype == 'float16' || (input.q_dtype == 'bfloat16' && ({heads} > 128 || (input.on_gfx942 && {heads} > 32 && {heads} <= 64))))",
                 "vars.longfb": "= !input.has_sinks && input.on_gfx942 && input.kv_dtype == 'bfloat16' && input.num_decodes == 0 && input.num_prefills > 0 && input.prefill_max_seq_len > input.topk_tokens"}},
        {"if": f"vars.sinkfb || vars.longfb || {tri}",
         "then": [{"title": "The ragged Triton path: split-KV decode when all tokens decode and the split count is > 1, else the ragged prefill", "source": Cfn(RAMSB, "_use_rocm_sparse_triton"),
                   "return": {"path": "= input.num_decode_tokens == input.num_tokens && input.decode_num_splits > 1 ? 'triton-decode' : 'triton-prefill'", "heads": "= input.num_heads", "lse": False}}]},
        {"if": "input.has_sinks",
         "then": [{"if": "!(input.q_dtype == input.kv_dtype && input.q_dtype in ['bfloat16', 'fp8'])",
                   "then": [{"title": "Sinks need BF16 or FP8 for both query and KV", "source": C(RAMSB, ln(RAMSB, r"ROCm AITER MLA attention sinks require query and KV to", la)),
                             "fail": {"code": "value-error", "message": "= 'ROCm AITER MLA attention sinks require query and KV to both use BF16 or both use FP8, got query=torch.' + (input.q_dtype == 'fp8' ? (input.on_gfx942 ? 'float8_e4m3fnuz' : 'float8_e4m3fn') : input.q_dtype) + ', KV=torch.' + (input.kv_dtype == 'fp8' ? (input.on_gfx942 ? 'float8_e4m3fnuz' : 'float8_e4m3fn') : input.kv_dtype)"}}]},
                  {"set": {"vars.buckets": "= input.q_dtype == 'bfloat16' ? [16, 32, 64, 128] : [16, 128]"}},
                  {"if": f"input.on_mi3xx && size(vars.buckets.filter(h, h >= {heads})) == 0",
                   "then": [{"title": "At most 128 padded heads with sinks", "source": C(RAMSB, ln(RAMSB, r"ROCm AITER MLA attention sinks support at most 128", la)),
                             "fail": {"code": "value-error", "message": "= 'ROCm AITER MLA attention sinks support at most 128 padded local ' + (input.q_dtype == 'bfloat16' ? 'BF16' : 'FP8') + ' heads; increase tensor_parallel_size'"}}]},
                  {"title": "Pad the query to the next head bucket the return-LSE kernel has", "source": C(RAMSB, ln(RAMSB, r"supported_heads = next\(", la)),
                   "return": {"path": "asm-lse", "heads": f"= input.on_mi3xx ? vars.buckets.filter(h, h >= {heads})[0] : {heads}", "lse": True}}]},
        {"title": "AITER asm decode at the padded head count", "source": C(RAMSB, la, lb), "return": {"path": "asm", "heads": "= " + heads, "lse": False}},
    ]
    out.append(iface("rocm-aiter-mla-sparse-impl", "forward-mqa", "ROCMAiterMLASparseImpl.forward_mqa / _forward_mla: AITER sparse MLA, the ragged Triton fallbacks (rope-free BF16, sink shapes without an LSE kernel, long BF16 prefills on gfx942), or the asm decode padded to a head bucket.",
                     [C(RAMSB, qa, qb), C(RAMSB, la, lb), Cfn(RAMSB, "_use_rocm_sparse_triton"), Cfn(RAMSB, "_is_long_bf16_prefill")], beh,
                     request=obj({"num_tokens": I(4), "num_heads": I(16), "kv_cache_dtype": S("auto"), "use_aiter_sparse_mla": B(False), "has_sinks": B(False),
                                  "q_dtype": S("bfloat16"), "kv_dtype": S("bfloat16"), "on_gfx942": B(False), "on_mi3xx": B(True), "head_size": I(576), "kv_lora_rank": I(512),
                                  "num_prefills": I(0), "num_decodes": I(4), "num_decode_tokens": I(4), "decode_num_splits": I(1), "prefill_max_seq_len": I(0), "topk_tokens": I(2048)}),
                     response=obj({"path": {"type": "string"}, "heads": {"type": "integer"}}), errors=[err("value-error", "unsupported sink shape")]))
    # HiSparse group cache (on the index-group builder's state)
    ca, cb = m(IG, "HiSparseMLAIndexGroup", "cache")
    out.append(iface("sparse-mla-index-group-builder", "cache", "HiSparseMLAIndexGroup.cache: the host-backed cache handle of a layer in a HiSparse group (a plain group has none).",
                     [C(IG, ca, cb), Cm(IG, "HiSparseMLAIndexGroup", "register_layer")],
                     [{"if": "!(input.group in state.groups) || !state.groups[input.group].hisparse",
                       "then": [{"title": "Only HiSparse groups keep per-layer caches", "source": C(IG, cls(IG, "HiSparseMLAIndexGroup")[0], cls(IG, "HiSparseMLAIndexGroup")[0]),
                                 "fail": {"code": "attribute-error", "message": "= input.group in state.groups ? \"'SparseMLAIndexGroup' object has no attribute 'cache'\" : \"'\" + input.group + \"'\""}}]},
                      {"if": "input.layer_index >= state.groups[input.group].num_layers",
                       "then": [{"title": "One cache per registered layer", "source": C(IG, ca, cb), "fail": {"code": "index-error", "message": "list index out of range"}}]},
                      {"return": {"cache": "= input.group + ':' + string(input.layer_index)", "is_index_group_leader": "= input.layer_index == 0"}}],
                     request=obj({"group": S("g0"), "layer_index": I(0)}), response=obj({"cache": {"type": "string"}}),
                     errors=[err("attribute-error", "not a HiSparse group"), err("index-error", "no such layer")]))
    # UltraQuant slot size
    za, zb = fn(UQF, "slot_size")
    out.append(iface("ultraquant-format", "slot-size", "UltraQuant slot_size: bytes per (token, head) slot = K and V FP4 codes (head_dim / 2 each) + one E8M0 scale byte per 32-element group for each.",
                     [C(UQF, za, zb), Cfn(UQF, "k_codes_bytes"), Cfn(UQF, "n_groups"), Lin(UQF, r"^GROUP_SIZE: int = ")],
                     [{"if": "input.head_dim % 2 != 0",
                       "then": [{"title": "Codes pack two per byte", "source": Cfn(UQF, "k_codes_bytes"), "fail": {"code": "value-error", "message": "= 'head_dim must be even, got ' + string(input.head_dim)"}}]},
                      {"if": "input.head_dim % input.group_size != 0",
                       "then": [{"title": "Groups must tile the head", "source": Cfn(UQF, "n_groups"), "fail": {"code": "value-error", "message": "head_dim must be a multiple of group_size"}}]},
                      {"title": "codes + scales for K and V", "source": C(UQF, za, zb), "return": {"slot_bytes": "= 2 * (input.head_dim / 2 + input.head_dim / input.group_size)"}}],
                     request=obj({"head_dim": I(128), "group_size": I(32)}), response=obj({"slot_bytes": {"type": "integer"}}), errors=[err("value-error", "bad head_dim")]))
    return out


def rocm_kernel_interfaces():
    """The test-hit skips: ROCm kernels and their launchers (unskipped)."""
    out = []
    g1 = kernel("rocm-aiter-mla-sparse-ops", "cp-gather-indexer-quant-cache-kernel", RAMS, "_cp_gather_indexer_quant_cache_kernel", "Gather FP8 indexer K and scales from the paged cache (generic ROCm).", lat=LAT_META)
    g2 = kernel("rocm-aiter-mla-sparse-ops", "cp-gather-indexer-quant-cache-gfx950-kernel", RAMS, "_cp_gather_indexer_quant_cache_gfx950_kernel", "The same gather, gfx950 build.", lat=LAT_META)
    out += [g1, g2]
    ga, gb = fn(RAMS, "cp_gather_indexer_k_quant_cache_triton")
    out.append(iface("rocm-aiter-mla-sparse-ops", "cp-gather-indexer-k-quant-cache-triton", "cp_gather_indexer_k_quant_cache_triton: gather each token's FP8 indexer key and scale; cache layout NORMAL for block 1 else SHUFFLE; the gfx950 kernel on gfx950.",
                     [C(RAMS, ga, gb)],
                     [{"title": "Layout: given, else NORMAL for block_size 1 and SHUFFLE otherwise", "source": C(RAMS, ln(RAMS, r"if cache_layout is None:", ga), ln(RAMS, r"layout = cache_layout", ga)),
                       "set": {"vars.layout": "= input.cache_layout != '' ? input.cache_layout : (input.block_size == 1 ? 'NORMAL' : 'SHUFFLE')"}},
                      {"if": "input.on_gfx950",
                       "then": [{"title": "gfx950 kernel", "source": C(RAMS, ln(RAMS, r"_cp_gather_indexer_quant_cache_gfx950_kernel\[grid\]", ga)),
                                 "call": "rocm-aiter-mla-sparse-ops.cp-gather-indexer-quant-cache-gfx950-kernel", "input": {"num_tokens": "= input.num_tokens"}}],
                       "else": [{"title": "generic kernel", "source": C(RAMS, ln(RAMS, r"_cp_gather_indexer_quant_cache_kernel\[grid\]", ga)),
                                 "call": "rocm-aiter-mla-sparse-ops.cp-gather-indexer-quant-cache-kernel", "input": {"num_tokens": "= input.num_tokens"}}]},
                      {"return": {"layout": "= vars.layout", "grid": "= [input.num_tokens]", "gfx950": "= input.on_gfx950"}}],
                     request=obj({"num_tokens": I(8), "block_size": I(64), "cache_layout": S(""), "on_gfx950": B(False)}),
                     response=obj({"layout": {"type": "string"}})))
    p = kernel("rocm-aiter-mla-sparse-ops", "sparse-attn-decode-ragged-bf16-partial-kernel", RAMS, "_sparse_attn_decode_ragged_bf16_partial_kernel", "Split-KV partial attention per (query, split, head block).")
    r = kernel("rocm-aiter-mla-sparse-ops", "sparse-attn-decode-reduce-kernel", RAMS, "_sparse_attn_decode_reduce_kernel", "Merge the splits' partial outputs by LSE per (query, head).", lat=LAT_META)
    out += [p, r]
    da, db = fn(RAMS, "_rocm_sparse_attn_decode_ragged_bf16_triton")
    out.append(iface("rocm-aiter-mla-sparse-ops", "rocm-sparse-attn-decode-ragged-bf16-triton", "_rocm_sparse_attn_decode_ragged_bf16_triton: split-KV ragged decode: the partial kernel over (queries, splits, head blocks), then the reduce over (queries, heads).",
                     [C(RAMS, da, db)],
                     [{"if": "input.indptr_len != input.num_queries + 1",
                       "then": [{"title": "indptr has one entry per query plus one", "source": C(RAMS, ln(RAMS, r"assert indptr\.numel\(\) == num_queries \+ 1", da)),
                                 "fail": {"code": "assertion-error", "message": "bad indptr"}}]},
                      {"title": "Partial kernel", "source": C(RAMS, ln(RAMS, r"_sparse_attn_decode_ragged_bf16_partial_kernel\[", da)),
                       "call": "rocm-aiter-mla-sparse-ops.sparse-attn-decode-ragged-bf16-partial-kernel", "input": {"num_tokens": "= input.num_queries", "num_heads": "= input.num_heads"}},
                      {"title": "Reduce kernel", "source": C(RAMS, ln(RAMS, r"_sparse_attn_decode_reduce_kernel\[\(num_queries, num_heads\)\]", da)),
                       "call": "rocm-aiter-mla-sparse-ops.sparse-attn-decode-reduce-kernel", "input": {"num_tokens": "= input.num_queries", "num_heads": "= input.num_heads"}},
                      {"return": {"partial_grid": "= [input.num_queries, input.num_splits, (input.num_heads + 15) / 16]", "reduce_grid": "= [input.num_queries, input.num_heads]"}}],
                     request=obj({"num_queries": I(4), "num_heads": I(16), "num_splits": I(4), "indptr_len": I(5)}),
                     response=obj({"partial_grid": ARR_I}), errors=[err("assertion-error", "bad indptr")]))
    k = kernel("rocm-aiter-mla-sparse-ops", "mxfp8-wo-a-bmm-kernel", RAMS, "_mxfp8_wo_a_bmm_kernel", "Grouped MXFP8 wo_a GEMM tile.")
    out.append(k)
    mark(RAMS, "vllm::rocm_dsv41_mxfp8_wo_a_bmm")
    ia, ib = fn(RAMS, "_rocm_mxfp8_wo_a_bmm_impl")
    ca, cb = fn(RAMS, "_mxfp8_wo_a_bmm_config")
    out.append(iface("rocm-aiter-mla-sparse-ops", "rocm-dsv41-mxfp8-wo-a-bmm", "torch op vllm::rocm_dsv41_mxfp8_wo_a_bmm (opaque so the token-count tile choice isn't frozen at trace time): grouped MXFP8 wo_a, [T, G*R] bf16 out; nothing launched for 0 tokens.",
                     [Cinv(RAMS, "vllm::rocm_dsv41_mxfp8_wo_a_bmm"), C(RAMS, ia, ib), C(RAMS, ca, cb)],
                     [{"if": "input.num_tokens == 0",
                       "then": [{"title": "No tokens: the empty output", "source": C(RAMS, ln(RAMS, r"if num_tokens == 0:", ia)), "return": {"out_shape": "= [0, input.n_groups * input.o_lora_rank]", "launched": False}}]},
                      {"title": "Tile config from the token count, then the kernel", "source": C(RAMS, ln(RAMS, r"_mxfp8_wo_a_bmm_kernel\[grid\]\(", ia)),
                       "call": "rocm-aiter-mla-sparse-ops.mxfp8-wo-a-bmm-kernel", "input": {"num_tokens": "= input.num_tokens"}},
                      {"return": {"out_shape": "= [input.num_tokens, input.n_groups * input.o_lora_rank]", "launched": True}}],
                     request=obj({"num_tokens": I(4), "n_groups": I(8), "o_lora_rank": I(1024)}), response=obj({"out_shape": ARR_I}),
                     attributes={"op": "vllm::rocm_dsv41_mxfp8_wo_a_bmm"}))
    mark(MX, "_topk")
    ta, tb = fn(MX, "_topk")
    out.append(iface("rocm-paged-mxfp4-indexer", "topk", "_topk: per-row top-k over [0, length); aiter's kernel for k >= 2048 or >= 128 rows (when the row is wide enough), else vLLM's top_k_per_row_decode op; nothing for 0 rows.",
                     [Cinv(MX, "_topk")],
                     [{"if": "input.rows == 0", "then": [{"title": "No rows", "source": C(MX, ln(MX, r"if rows == 0:", ta)), "return": {"impl": "none"}}]},
                      {"if": "input.width >= input.k && (input.k >= 2048 || input.rows >= 128)",
                       "then": [{"title": "aiter top-k", "source": C(MX, ln(MX, r"_aiter_topk\(\)\(", ta)), "return": {"impl": "aiter"}}]},
                      {"title": "torch.ops._C.top_k_per_row_decode", "source": C(MX, ln(MX, r"torch\.ops\._C\.top_k_per_row_decode\(", ta)), "return": {"impl": "top_k_per_row_decode"}}],
                     request=obj({"rows": I(4), "width": I(4096), "k": I(512)}), response=obj({"impl": {"type": "string"}})))
    s1 = kernel("segmented-attention", "segmented-attention-stage", SEG, "_segmented_attention_stage", "Per-split partial attention over a KV segment.")
    s2 = kernel("segmented-attention", "segmented-attention-reduce", SEG, "_segmented_attention_reduce", "Merge the splits by LSE.", lat=LAT_META)
    out += [s1, s2]
    la, lb = fn(SEG, "_launch_segmented_attention")
    out.append(iface("segmented-attention", "launch-segmented-attention", "_launch_segmented_attention: the stage kernel, then the reduce only when the config splits the KV (splits > 1); compile_only warms the kernels up instead.",
                     [C(SEG, la, lb)],
                     [{"title": "Stage kernel (or its warm-up)", "source": C(SEG, ln(SEG, r"_segmented_attention_stage\[stage_grid\]", la)),
                       "call": "segmented-attention.segmented-attention-stage", "input": {"num_tokens": "= input.batch", "num_heads": "= input.hq"}},
                      {"if": "input.splits > 1",
                       "then": [{"title": "Reduce over the splits", "source": C(SEG, ln(SEG, r"if splits > 1:", la), ln(SEG, r"_segmented_attention_reduce\[reduce_grid\]", la)),
                                 "call": "segmented-attention.segmented-attention-reduce", "input": {"num_tokens": "= input.batch", "num_heads": "= input.hq"}},
                                {"return": {"reduced": True, "warmup_only": "= input.compile_only"}}]},
                      {"return": {"reduced": False, "warmup_only": "= input.compile_only"}}],
                     request=obj({"batch": I(2), "hq": I(32), "splits": I(4), "compile_only": B(False)}), response=obj({"reduced": {"type": "boolean"}})))
    return out


def interfaces():
    return ([fa_init()] + utils_interfaces() + builder_base_interfaces() + mla_impl_interfaces() + [concat_stub(), describe_interface()]
            + rocm_impl_interfaces() + rocm_kernel_interfaces())


def scenarios():
    S = []
    S.append({"id": "attention-fa-impl-init", "name": "FlashAttentionImpl.__init__: windows per type; encoder-only hd256 on SM100 with a window falls back to FA2; decoder keeps FA4; fp8 on Ampere refused", "fixtures": FX,
              "steps": [step("flash-attention-impl.init", {"head_size": 256, "sliding_window": 512, "attn_type": "encoder_only", "device_capability_major": 10}, "enc"),
                        step("flash-attention-impl.init", {"head_size": 256, "sliding_window": 512, "attn_type": "decoder", "device_capability_major": 10}, "dec"),
                        step("flash-attention-impl.init", {"head_size": 256, "attn_type": "encoder_only", "device_capability_major": 10}, "nowin"),
                        step("flash-attention-impl.init", {}, "llama"),
                        step("flash-attention-impl.init", {"kv_cache_dtype": "fp8", "device_capability_major": 8}, "fp8")],
              "expect": ["steps.enc.result.value.fa_version == 2 && !steps.enc.result.value.fa4_hd256 && steps.enc.result.value.sliding_window == [511, 511]",
                         "steps.dec.result.value.fa_version == 4 && steps.dec.result.value.fa4_hd256 && steps.dec.result.value.sliding_window == [511, 0]",
                         "steps.nowin.result.value.fa_version == 4 && steps.nowin.result.value.sliding_window == [-1, -1]",
                         "steps.llama.result.value.fa_version == 3 && steps.llama.result.value.num_queries_per_kv == 4",
                         "!steps.fp8.result.ok && steps.fp8.result.error.code == 'not-implemented-error'"]})
    sp = lambda a, **kw: step("attention-backend-utils.split-decodes-and-prefills", kw, a)
    S.append({"id": "attention-split-decodes-prefills", "name": "split_decodes_and_prefills: all decodes, prefill-first, a mixed split, uniform padding, and short extends still prefilling", "fixtures": FX,
              "steps": [sp("dec", max_query_len=1, query_start_loc_cpu=[0, 1, 2, 3], num_actual_tokens=3),
                        sp("pre", query_start_loc_cpu=[0, 5, 6, 7], max_query_len=5),
                        sp("mix", query_start_loc_cpu=[0, 1, 2, 7], max_query_len=5),
                        sp("uni", query_start_loc_cpu=[0, 3, 6, 6], num_actual_tokens=6, max_query_len=3, decode_threshold=3, require_uniform=True),
                        sp("uni2", query_start_loc_cpu=[0, 3, 6, 8], num_actual_tokens=8, max_query_len=3, decode_threshold=3, require_uniform=True),
                        sp("ext", query_start_loc_cpu=[0, 1, 3, 4], num_actual_tokens=4, max_query_len=2, decode_threshold=2, treat_short_extends_as_decodes=False, is_prefilling=[False, True, False]),
                        sp("none", query_start_loc_cpu=[0, 1, 3, 5], num_actual_tokens=5, max_query_len=2, decode_threshold=2, treat_short_extends_as_decodes=False, is_prefilling=[False, False, False])],
              "expect": ["steps.dec.result.value.num_decodes == 3 && steps.pre.result.value.num_prefills == 3 && steps.pre.result.value.num_decodes == 0",
                         "steps.mix.result.value.num_decodes == 2 && steps.mix.result.value.num_prefill_tokens == 5 && steps.mix.result.value.num_decode_tokens == 2",
                         "steps.uni.result.value.num_decodes == 3 && steps.uni2.result.value.num_decodes == 2 && steps.uni2.result.value.num_prefills == 1",
                         "steps.ext.result.value.num_decodes == 1 && steps.ext.result.value.num_prefills == 2 && steps.none.result.value.num_prefills == 0"]})
    S.append({"id": "attention-dcp-local-seq-lens", "name": "DCP local lengths: every rank, one rank, and an interleave of 4", "fixtures": FX,
              "steps": [step("attention-backend-utils.get-dcp-local-seq-lens", {"seq_lens": [10, 3], "dcp_size": 2}, "all"),
                        step("attention-backend-utils.get-dcp-local-seq-lens", {"seq_lens": [10, 3], "dcp_size": 2, "dcp_rank": 1}, "r1"),
                        step("attention-backend-utils.get-dcp-local-seq-lens", {"seq_lens": [10], "dcp_size": 2, "cp_kv_cache_interleave_size": 4}, "il")],
              "expect": ["steps.all.result.value.local_seq_lens == [[5, 5], [2, 1]]", "steps.r1.result.value.local_seq_lens == [5, 1]",
                         "steps.il.result.value.local_seq_lens == [[6, 4]]"]})
    S.append({"id": "attention-per-layer-params-and-layouts", "name": "FlashInfer per-layer parameters; KV layout negotiation and recording", "fixtures": FX,
              "steps": [step("attention-backend-utils.get-per-layer-parameters", {"layers": [{"name": "l0", "sliding_window": [4095, 0], "scale": 0.08, "logits_soft_cap": 30.0, "has_sinks": True},
                                                                                       {"name": "l1", "scale": 0.08}]}, "pl"),
                        step("attention-backend-utils.get-per-layer-parameters", {"layers": [{"name": "l0", "scale": 0.08, "impl_matches": False}]}, "plbad"),
                        step("attention-backend-utils.get-supported-kv-cache-layouts", {}, "dflt"),
                        step("attention-backend-utils.get-supported-kv-cache-layouts", {"backend_layouts": [["LBHNC", "BLHNC"], []]}, "fi"),
                        step("attention-backend-utils.get-supported-kv-cache-layouts", {"backend_layouts": [["LBHNC", "BLHNC"], ["LBNHC", "LBHNC", "BLHNC"]]}, "mix"),
                        step("attention-backend-utils.get-supported-kv-cache-layouts", {"backend_layouts": [["LBHNC"], ["LBNHC"]]}, "none"),
                        step("attention-backend-utils.record-kv-cache-layout", {"kv_cache_layout": "HND"}, "rec"),
                        step("attention-backend-utils.record-kv-cache-layout", {"kv_cache_layout": "NHD", "existing_layout": "LBHNC"}, "clash"),
                        step("attention-backend-utils.record-kv-cache-layout", {"kv_cache_layout": "XYZ"}, "bad")],
              "expect": ["steps.pl.result.value.params[0].window_left == 4095 && steps.pl.result.value.params[0].has_sinks && steps.pl.result.value.params[1].window_left == -1",
                         "!steps.plbad.result.ok && steps.dflt.result.value.layouts[0] == 'LBNHC' && steps.fi.result.value.layouts == ['LBHNC', 'BLHNC']",
                         "steps.mix.result.value.layouts == ['LBHNC', 'BLHNC'] && !steps.none.result.ok && steps.none.result.error.code == 'value-error'",
                         "steps.rec.result.value.kv_cache_layout == 'LBHNC' && !steps.clash.result.ok && !steps.bad.result.ok"]})
    from scen import COMMON
    S.append({"id": "attention-builder-base-hooks", "name": "Builder base hooks: CUDA-graph capture build, varlen replay bound, draft-decode refresh", "fixtures": FX,
              "steps": [step("attention-metadata-builder.build-for-cudagraph-capture", {"common": COMMON}, "cap"),
                        step("attention-metadata-builder.build-for-cudagraph-capture", {"backend": "TRITON_ATTN", "common": COMMON}, "capt"),
                        step("attention-metadata-builder.get-varlen-cudagraph-max-query-len", {}, "v0"),
                        step("attention-metadata-builder.get-varlen-cudagraph-max-query-len", {"backend": "FLASHINFER_MLA_SPARSE", "num_speculative_tokens": 3}, "v1"),
                        step("attention-metadata-builder.get-varlen-cudagraph-max-query-len", {"backend": "FLASHINFER", "num_speculative_tokens": 2}, "v2"),
                        step("attention-metadata-builder.get-varlen-cudagraph-max-query-len", {"backend": "FLASHINFER", "all_specs_trtllm": False}, "v3"),
                        step("attention-metadata-builder.update-draft-decode-metadata", {}, "u0"),
                        step("attention-metadata-builder.update-draft-decode-metadata", {"has_scheduler_metadata": False}, "u1"),
                        step("attention-metadata-builder.update-draft-decode-metadata", {"dcp_world_size": 2}, "u2"),
                        step("attention-metadata-builder.update-draft-decode-metadata", {"backend": "TRITON_ATTN"}, "u3"),
                        step("attention-metadata-builder.update-draft-decode-metadata", {"backend": "FLASHMLA"}, "u4")],
              "expect": ["steps.cap.result.value.num_actual_tokens == 17 && !steps.capt.result.ok",
                         "steps.v0.result.value.max_query_len == null && steps.v1.result.value.max_query_len == 4 && steps.v2.result.value.max_query_len == 3 && steps.v3.result.value.max_query_len == null",
                         "steps.u0.result.value.refreshed && !steps.u1.result.value.refreshed && !steps.u2.result.ok && !steps.u3.result.value.refreshed",
                         "!steps.u4.result.ok && steps.u4.result.error.code == 'not-implemented-error'"]})
    S.append({"id": "attention-mla-impl-base", "name": "MLAAttentionImpl base methods: forward_mqa dispatch, forward_mha overrides, the default latent cache write", "fixtures": FX,
              "steps": [step("mla-attention-impl.forward-mqa", {}, "fi"), step("mla-attention-impl.forward-mqa", {"backend": "TRITON_MLA", "num_decode_tokens": 4}, "tr"),
                        step("mla-attention-impl.forward-mqa", {"backend": "ROCM_AITER_MLA"}, "ai"), step("mla-attention-impl.forward-mqa", {"backend": "CUTLASS_MLA"}, "cu"),
                        step("mla-attention-impl.forward-mqa", {"backend": ""}, "abs"),
                        step("mla-attention-impl.forward-mha", {}, "mha"), step("mla-attention-impl.forward-mha", {"backend": "FLASHMLA"}, "mha0"),
                        step("mla-attention-impl.do-kv-cache-update", {}, "kv"), step("mla-attention-impl.do-kv-cache-update", {"cache_numel": 0}, "kv0"),
                        step("mla-attention-impl.do-kv-cache-update", {"backend": "CPU_MLA", "slot_mapping": [0, 1, 2]}, "cpu")],
              "expect": ["steps.fi.result.value.impl == 'FlashInferMLAImpl' && steps.tr.result.value.impl == 'TritonMLAImpl' && steps.ai.result.value.impl == 'AiterMLAImpl'",
                         "steps.cu.result.value.impl == 'CUTLASS_MLA' && !steps.abs.result.ok && steps.mha.result.ok && !steps.mha0.result.ok",
                         "steps.kv.result.value.written == 2 && steps.kv0.result.value.written == 0 && steps.cpu.result.ok",
                         "state['cpu-mla-impl@rank0'].latent_rows['2'].token == 2"]})
    S.append({"id": "attention-backend-describe-and-hisparse", "name": "Backend class descriptors; HiSparse group caches; UltraQuant slot size", "fixtures": FX,
              "steps": [step("attention-backend.describe", {}, "fa"), step("attention-backend.describe", {"backend": "ROCM_AITER_MLA_SPARSE"}, "rs"),
                        step("attention-backend.describe", {"backend": "NOPE"}, "bad"),
                        step("sparse-mla-index-group-builder.init", {"logical_rows": 8}, "i"),
                        step("sparse-mla-index-group-builder.register-layer", {"is_index_producing_layer": True, "hisparse": True}, "h0"),
                        step("sparse-mla-index-group-builder.cache", {"group": "g0", "layer_index": 0}, "c0"),
                        step("sparse-mla-index-group-builder.cache", {"group": "g0", "layer_index": 3}, "c3"),
                        step("sparse-mla-index-group-builder.register-layer", {"is_index_producing_layer": True}, "p0"),
                        step("sparse-mla-index-group-builder.cache", {"group": "g1", "layer_index": 0}, "cp"),
                        step("ultraquant-format.slot-size", {}, "uq"), step("ultraquant-format.slot-size", {"head_dim": 127}, "odd"),
                        step("ultraquant-format.slot-size", {"head_dim": 48}, "grp")],
              "expect": ["steps.fa.result.value.impl == 'FlashAttentionImpl' && steps.rs.result.value.layouts == ['LBNHC', 'LBHNC', 'BLHNC'] && !steps.bad.result.ok",
                         "steps.c0.result.value.is_index_group_leader && steps.c3.result.error.code == 'index-error' && steps.cp.result.error.code == 'attribute-error'",
                         "steps.uq.result.value.slot_bytes == 136 && !steps.odd.result.ok && !steps.grp.result.ok",
                         "state['sparse-mla-index-group-builder@rank0'].groups.g0.hisparse"]})
    ai = lambda a, **kw: step("aiter-mla-impl.forward-mqa", kw, a)
    rs = lambda a, **kw: step("rocm-aiter-mla-sparse-impl.forward-mqa", kw, a)
    S.append({"id": "attention-rocm-mla-forward-routing", "name": "ROCm MLA forward routing: Gluon decode and verify, segmented DCP, asm (padded, cprr); sparse MLA's AITER, Triton and head-bucket paths", "fixtures": FX,
              "steps": [ai("gd", use_gluon_decode=True, num_heads=8), ai("gv", use_gluon_verify=True, num_reqs=2, qlen=4, num_tokens=8),
                        ai("gvbad", use_gluon_verify=True, num_reqs=2, qlen=4, num_tokens=7), ai("seg", dcp_route="segmented", dcp_world_size=2),
                        ai("asm", num_heads=24), ai("cprr", num_heads=96, dcp_route="cprr", dcp_world_size=2), ai("nodec", has_decode=False),
                        rs("aiter", use_aiter_sparse_mla=True), rs("tri", head_size=512, decode_num_splits=4), rs("trip", head_size=512, num_decode_tokens=2),
                        rs("sasm", num_heads=20), rs("sink", has_sinks=True, num_heads=40), rs("sinkfp16", has_sinks=True, q_dtype="float16", kv_dtype="float16"),
                        rs("sinkbad", has_sinks=True, q_dtype="fp8", kv_dtype="bfloat16"), rs("sinkbig", has_sinks=True, q_dtype="fp8", kv_dtype="fp8", num_heads=136),
                        rs("long", on_gfx942=True, num_decodes=0, num_prefills=1, num_decode_tokens=0, prefill_max_seq_len=4096, kv_cache_dtype="fp8_e4m3")],
              "expect": ["steps.gd.result.value.path == 'gluon-decode' && steps.gv.result.value.path == 'gluon-verify' && !steps.gvbad.result.ok",
                         "steps.seg.result.value.path == 'segmented' && steps.seg.result.value.returns_lse && steps.asm.result.value.heads == 32 && steps.cprr.result.value.heads == 128",
                         "!steps.nodec.result.ok && steps.aiter.result.value.path == 'aiter-sparse' && steps.tri.result.value.path == 'triton-decode' && steps.trip.result.value.path == 'triton-prefill'",
                         "steps.sasm.result.value.path == 'asm' && steps.sasm.result.value.heads == 32 && steps.sink.result.value.path == 'asm-lse' && steps.sink.result.value.heads == 64",
                         "steps.sinkfp16.result.value.path == 'triton-prefill' && !steps.sinkbad.result.ok && !steps.sinkbig.result.ok && steps.long.result.value.path == 'triton-prefill'"]})
    S.append({"id": "attention-rocm-skipped-kernels", "name": "Formerly skipped ROCm kernels: indexer-cache gathers, split-KV decode + reduce, MXFP8 wo_a op, MXFP4 top-k, segmented attention", "fixtures": FX,
              "steps": [step("rocm-aiter-mla-sparse-ops.cp-gather-indexer-k-quant-cache-triton", {}, "g"),
                        step("rocm-aiter-mla-sparse-ops.cp-gather-indexer-k-quant-cache-triton", {"block_size": 1, "on_gfx950": True}, "g950"),
                        step("rocm-aiter-mla-sparse-ops.rocm-sparse-attn-decode-ragged-bf16-triton", {}, "d"),
                        step("rocm-aiter-mla-sparse-ops.rocm-sparse-attn-decode-ragged-bf16-triton", {"indptr_len": 3}, "dbad"),
                        step("rocm-aiter-mla-sparse-ops.rocm-dsv41-mxfp8-wo-a-bmm", {}, "w"), step("rocm-aiter-mla-sparse-ops.rocm-dsv41-mxfp8-wo-a-bmm", {"num_tokens": 0}, "w0"),
                        step("rocm-paged-mxfp4-indexer.topk", {}, "t"), step("rocm-paged-mxfp4-indexer.topk", {"rows": 128}, "ta"),
                        step("rocm-paged-mxfp4-indexer.topk", {"rows": 0}, "t0"),
                        step("segmented-attention.launch-segmented-attention", {}, "s"), step("segmented-attention.launch-segmented-attention", {"splits": 1, "compile_only": True}, "s1")],
              "expect": ["steps.g.result.value.layout == 'SHUFFLE' && steps.g950.result.value.layout == 'NORMAL' && steps.g950.result.value.gfx950",
                         "steps.d.result.value.partial_grid == [4, 4, 1] && !steps.dbad.result.ok",
                         "steps.w.result.value.out_shape == [4, 8192] && steps.w.result.value.launched && !steps.w0.result.value.launched",
                         "steps.t.result.value.impl == 'top_k_per_row_decode' && steps.ta.result.value.impl == 'aiter' && steps.t0.result.value.impl == 'none'",
                         "steps.s.result.value.reduced && !steps.s1.result.value.reduced && steps.s1.result.value.warmup_only"]})
    return S

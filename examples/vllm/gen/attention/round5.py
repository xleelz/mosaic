"""Round-5 additions (precision): the decode/prefill batch reordering, TokenspeedMLAImpl.forward_mqa's kernel
contract, MLA prefill backend availability (the AITER one asks rocm_aiter_ops), the oracle3 regressions (indexer
kernel block sizes, DeepSeek V4 ROCm CUDA-graph support), the FP8 KV cache through FlashAttention in the FP8 world,
the vision encoder's attention in the VL world, Mixtral's per-rank attention in the MoE world, the error-path sweep
regressions, and the build-oracle round-5 scenarios."""
from core import B, I, S, comp, err, iface
from lib import C, Cfn, cls, fn, ln, LAT_META
from round4 import A, ARR_I, Cm, FX, Lin, m, obj, step, PREFILL_CAPS

UT = "vllm/v1/attention/backends/utils.py"
TS = "vllm/v1/attention/backends/mla/tokenspeed_mla.py"
PAF = "vllm/v1/attention/backends/mla/prefill/aiter_flash_attn.py"
PBASE = "vllm/v1/attention/backends/mla/prefill/base.py"
PFA = "vllm/v1/attention/backends/mla/prefill/flash_attn.py"
AOPS = "vllm/_aiter_ops.py"
FA = "vllm/v1/attention/backends/flash_attn.py"

W = ["full-tp1-llama-8b"]
W_FP8 = ["full-fp8-llama-3-8b"]
W_FP8KV = ["full-fp8-llama-3-8b-kv-fp8"]
W_VL = ["full-vl-qwen2-vl-7b"]
W_MOE = ["full-moe-mixtral-8x7b-tp2-ep"]


def components():
    out = []
    a, b = cls(TS, "TokenspeedMLAImpl")
    out.append(comp("tokenspeed-mla-impl", "TokenspeedMLAImpl", TS,
                    "TokenSpeed MLA decode (SM100): FP8 query and FP8 KV only; reshapes the query per request and calls tokenspeed_mla_decode with the DCP rank and interleave.",
                    a=a, b=b))
    out.append(comp("tokenspeed-mla-kernels", "tokenspeed_mla (package)", TS,
                    "The external tokenspeed_mla package's decode kernel (an optional dependency, imported inside forward_mqa).",
                    a=ln(TS, r"from tokenspeed_mla import tokenspeed_mla_decode"), b=ln(TS, r"from tokenspeed_mla import tokenspeed_mla_decode"),
                    attributes={"external_package": "tokenspeed_mla"}))
    out.append({"id": "aiter-ops", "name": "ROCm AITER ops", "kind": "module",
                "summary": "Boundary stub: rocm_aiter_ops (owned by kernels-ops).",
                "sources": [C(AOPS, ln(AOPS, r"^class rocm_aiter_ops"))], "attributes": {"boundary": True, "owner": "kernels-ops"}})
    return out


def boundary_interfaces():
    a, b = fn(AOPS, "is_enabled")
    return [{"component": "aiter-ops", "name": "is-enabled", "kind": "function",
             "summary": "Boundary stub: rocm_aiter_ops.is_enabled (None when AITER is unsupported here, else the cached VLLM_ROCM_USE_AITER flag).",
             "sources": [C(AOPS, a, b)], "attributes": {"boundary": True, "owner": "kernels-ops"},
             "response": {"type": "object", "properties": {"enabled": {"type": ["boolean", "null"]}}}, "latency_ms": 0}]


def reorder_interface():
    ra, rb = fn(UT, "reorder_batch_to_split_decodes_and_prefills")
    n = "size(input.req_ids)"
    beh = [
        {"title": "Each request's scheduled tokens, in batch order", "source": C(UT, ln(UT, r"num_scheduled_tokens = \[", ra), ln(UT, r"num_prompt_tokens_np = input_batch\.num_prompt_tokens", ra)),
         "set": {"vars.s": "= input.req_ids.map(r, input.num_scheduled_tokens[r])"}},
        {"title": "Four exclusive regions: no context yet is a prefill (3); context and above the threshold a long extend (2); at or below it, still prefilling a short extend (1), done a decode (0)",
         "source": C(UT, ln(UT, r"has_context = num_computed_tokens_np > 0", ra), ln(UT, r"req_regions\[is_pure_prefill\] = 3", ra)),
         "set": {"vars.reg": f"= lists.range({n}).map(i, input.num_computed_tokens[i] <= 0 ? 3 : (vars.s[i] > input.decode_threshold ? 2"
                             " : (input.num_computed_tokens[i] >= input.num_prompt_tokens[i] ? 0 : 1)))"}},
        {"set": {"vars.c": "= [0, 1, 2, 3].map(g, vars.reg.filter(x, x == g).size())"}},
        {"title": "The target is decode, short extend, long extend, prefill, each region as large as its count",
         "source": C(UT, ln(UT, r"target_regions = np\.repeat\(", ra), ln(UT, r"\)\.astype\(np\.int32\)", ra)),
         "set": {"vars.tgt": f"= lists.range({n}).map(i, i < vars.c[0] ? 0 : (i < vars.c[0] + vars.c[1] ? 1 : (i < vars.c[0] + vars.c[1] + vars.c[2] ? 2 : 3)))"}},
        {"title": "Only the requests whose region differs from the target move", "source": C(UT, ln(UT, r"needs_swap = req_regions != target_regions", ra)),
         "set": {"vars.sw": f"= lists.range({n}).filter(i, vars.reg[i] != vars.tgt[i])"}},
        {"if": "size(vars.sw) == 0",
         "then": [{"title": "Already in order: nothing changes", "source": C(UT, ln(UT, r"if not needs_swap\.any\(\):", ra), ln(UT, r"return False", ra)),
                   "return": {"modified": False, "req_ids": "= input.req_ids"}}]},
        {"title": "The moving requests, stably sorted by region, fill the moving positions in order",
         "source": C(UT, ln(UT, r"orig_indices = np\.where\(needs_swap\)\[0\]", ra), ln(UT, r"src_dest_map = \{int\(src\): int\(dst\)", ra)),
         "set": {"vars.src": "= vars.sw.filter(i, vars.reg[i] == 0) + vars.sw.filter(i, vars.reg[i] == 1) + vars.sw.filter(i, vars.reg[i] == 2) + vars.sw.filter(i, vars.reg[i] == 3)"}},
        {"title": "input_batch.swap_states follows each cycle of the move map in place, which leaves every moving request at its destination",
         "source": C(UT, ln(UT, r"for src in src_dest_map:", ra), rb),
         "return": {"modified": True,
                    "req_ids": f"= lists.range({n}).map(p, p in vars.sw ? input.req_ids[vars.src[vars.sw.indexOf(p)]] : input.req_ids[p])"}},
    ]
    return iface("attention-backend-utils", "reorder-batch-to-split-decodes-and-prefills",
                 "reorder_batch_to_split_decodes_and_prefills: reorder the input batch in place into decode, short extend, long extend and prefill regions with the fewest moves; True when anything moved. The builders' reorder_batch hook (the model runner's _may_reorder_batch, worker-runner) calls it.",
                 [C(UT, ra, rb)], beh,
                 request=obj({"req_ids": {"type": "array", "items": {"type": "string"}}, "num_scheduled_tokens": {"type": "object"},
                              "num_computed_tokens": ARR_I, "num_prompt_tokens": ARR_I, "decode_threshold": I(1)},
                             required=["req_ids", "num_scheduled_tokens", "num_computed_tokens", "num_prompt_tokens"]),
                 response=obj({"modified": {"type": "boolean"}, "req_ids": {"type": "array", "items": {"type": "string"}}}))


def tokenspeed_interfaces():
    out = []
    fa_, fb_ = m(TS, "TokenspeedMLAImpl", "forward_mqa")
    beh = [
        {"if": "!input.kv_cache_nonempty || !input.has_decode_metadata",
         "then": [{"title": "The KV cache must be non-empty and the decode metadata present (bare asserts)",
                   "source": C(TS, ln(TS, r"assert kv_c_and_k_pe_cache\.numel\(\) > 0", fa_), ln(TS, r"assert attn_metadata\.decode is not None", fa_)),
                   "fail": {"code": "assertion-error", "message": ""}}]},
        {"if": "input.q_dtype != 'float8_e4m3fn'",
         "then": [{"title": "The kernel is specialized for FP8 Q and FP8 KV: the upstream concat+quant must have run",
                   "source": C(TS, ln(TS, r"assert q\.dtype == torch\.float8_e4m3fn, \(", fa_), ln(TS, r"q_scale=\{layer\._q_scale_float\}, k_scale=\{layer\._k_scale_float\}\.", fa_) + 1),
                   "fail": {"code": "assertion-error",
                            "message": "= 'TokenspeedMLAImpl expected FP8 query (supports_quant_query_input=True), got torch.' + input.q_dtype + '. Pipeline isinstance(q, tuple)=' + (input.q_is_tuple ? 'True' : 'False') + ', q_scale=' + input.q_scale_repr + ', k_scale=' + input.k_scale_repr + '.'"}}]},
        {"if": "input.num_decode_tokens % input.num_decodes != 0",
         "then": [{"title": "Uneven query length per request (a reordering bug): warn once and give each token its own row",
                   "source": C(TS, ln(TS, r"if num_decode_tokens % num_decodes != 0:", fa_), ln(TS, r"q = q\.unsqueeze\(1\)", fa_)),
                   "set": {"vars.qshape": "= [input.num_decode_tokens, 1, input.num_heads, input.kv_lora_rank + input.qk_rope_head_dim]"}}],
         "else": [{"title": "Query viewed as (num_decodes, q_len per request, num_heads, head_dim)", "source": C(TS, ln(TS, r"q = q\.view\(num_decodes, -1, q\.shape\[-2\], q\.shape\[-1\]\)", fa_)),
                   "set": {"vars.qshape": "= [input.num_decodes, input.num_decode_tokens / input.num_decodes, input.num_heads, input.kv_lora_rank + input.qk_rope_head_dim]"}}]},
        {"title": "FP8 KV is mandatory: softmax_scale = scale * q_scale * k_scale and output_scale = k_scale, computed once",
         "source": C(TS, ln(TS, r"if self\.softmax_scale is None:", fa_), ln(TS, r"self\.output_scale = layer\._k_scale_float", fa_)),
         "set": {"vars.sm": "= input.softmax_scale != null ? input.softmax_scale : input.scale * input.q_scale * input.k_scale",
                 "vars.os": "= input.softmax_scale != null ? input.output_scale : input.k_scale"}},
        {"title": "tokenspeed_mla_decode on the cached workspace: block tables and seq lens from the decode metadata, the DCP world, rank and interleave (read at call time, since NIXL may set it later), causal_seqs only under DCP (None otherwise: pass_causal_seqs false)",
         "source": C(TS, ln(TS, r"workspace = _get_workspace\(", fa_), ln(TS, r"min_split_kv=self\._min_split_kv,", fa_)),
         "call": "tokenspeed-mla-kernels.tokenspeed-mla-decode",
         "input": {"query_shape": "= vars.qshape", "workspace_buffer": "workspace", "kv_lora_rank": "= input.kv_lora_rank", "qk_rope_head_dim": "= input.qk_rope_head_dim",
                   "block_tables": "= input.block_table", "seq_lens": "= input.seq_lens", "max_seq_len": "= input.max_seq_len",
                   "softmax_scale": "= vars.sm", "output_scale": "= vars.os", "enable_pdl": False, "return_lse": "= input.need_to_return_lse_for_decode",
                   "causal_mask": "= input.causal", "pass_causal_seqs": "= input.dcp_world_size > 1", "causal_seqs": "= input.dcp_world_size > 1 ? input.dcp_tot_seq_lens : []",
                   "cp_world": "= input.dcp_world_size", "cp_rank": "= input.dcp_rank", "cp_interleave_size": "= input.cp_kv_cache_interleave_size",
                   "min_split_kv": "= input.min_split_kv", "num_tokens": "= input.num_decode_tokens", "kv_tokens": "= sum(input.seq_lens)"},
         "as": "k"},
        {"title": "Outputs flattened to (tokens, heads, kv_lora_rank); the LSE to (tokens, heads) when returned",
         "source": C(TS, ln(TS, r"if return_lse:", fa_), fb_),
         "return": {"out_shape": "= [input.num_decode_tokens, input.num_heads, input.kv_lora_rank]",
                    "lse_shape": "= input.need_to_return_lse_for_decode ? dyn([input.num_decode_tokens, input.num_heads]) : dyn(null)"}},
    ]
    out.append(iface("tokenspeed-mla-impl", "forward-mqa",
                     "TokenspeedMLAImpl.forward_mqa: check the FP8 query, reshape it per request, derive the FP8 softmax and output scales once, and call tokenspeed_mla_decode with the DCP layout.",
                     [C(TS, fa_, fb_), Cfn(TS, "_get_workspace")], beh,
                     request=obj({"num_decodes": I(2), "num_decode_tokens": I(2), "num_heads": I(128), "kv_lora_rank": I(512), "qk_rope_head_dim": I(64),
                                  "q_dtype": S("float8_e4m3fn"), "q_is_tuple": B(False), "kv_cache_nonempty": B(True), "has_decode_metadata": B(True),
                                  "causal": B(True), "dcp_world_size": I(1), "dcp_rank": I(0), "cp_kv_cache_interleave_size": I(1), "min_split_kv": I(1),
                                  "need_to_return_lse_for_decode": B(True), "scale": {"type": "number", "default": 1.0},
                                  "softmax_scale": {"type": ["number", "null"], "default": None}, "output_scale": {"type": ["number", "null"], "default": None},
                                  "q_scale": {"type": "number", "default": 1.0}, "k_scale": {"type": "number", "default": 1.0},
                                  "q_scale_repr": S("1.0"), "k_scale_repr": S("1.0"),
                                  "block_table": {"type": "array", "default": [[0], [0]]}, "seq_lens": A([16, 24]), "dcp_tot_seq_lens": A([16, 24]), "max_seq_len": I(24)}),
                     response=obj({"out_shape": ARR_I, "lse_shape": {"type": ["array", "null"]}}),
                     errors=[err("assertion-error", "empty cache, no decode metadata, or a non-FP8 query")]))
    out.append({"component": "tokenspeed-mla-kernels", "name": "tokenspeed-mla-decode", "kind": "kernel",
                "summary": "tokenspeed_mla.tokenspeed_mla_decode: the external FP8 MLA decode kernel (its body is not simulated).",
                "sources": [C(TS, ln(TS, r"kernel_out = tokenspeed_mla_decode\("), ln(TS, r"min_split_kv=self\._min_split_kv,"))],
                "attributes": {"op": "tokenspeed_mla.tokenspeed_mla_decode", "language": "cuda"},
                "request": obj({"query_shape": ARR_I, "workspace_buffer": S("workspace"), "kv_lora_rank": I(512), "qk_rope_head_dim": I(64),
                                "block_tables": {"type": "array"}, "seq_lens": ARR_I, "max_seq_len": I(0), "softmax_scale": {"type": "number"},
                                "output_scale": {"type": "number"}, "enable_pdl": B(False), "return_lse": B(True), "causal_mask": B(True),
                                "pass_causal_seqs": B(False), "causal_seqs": ARR_I, "cp_world": I(1), "cp_rank": I(0), "cp_interleave_size": I(1),
                                "min_split_kv": I(1), "num_tokens": I(1), "kv_tokens": I(0)}),
                "response": obj({"ok": {"type": "boolean"}}),
                "latency_ms": ("= ((double(config['attn-kernel-launch-us']) + double(input.num_tokens) * double(config['attn-us-per-query-token'])"
                               " + double(input.kv_tokens) * double(config['attn-us-per-kv-token'])) / 1000.0)")})
    return out


def prefill_available_interface():
    aa, ab = m(PAF, "AiterFlashAttnPrefillBackend", "is_available")
    ba, bb = m(PBASE, "MLAPrefillBackend", "is_available")
    table = {k: v["available"] for k, v in PREFILL_CAPS.items()}
    table.update({"CPU_SDPA_MLA": True})
    tq = str(table).replace("True", "true").replace("False", "false")
    beh = [
        {"if": "input.backend == 'ROCM_AITER_FA'",
         "then": [{"title": "AiterFlashAttnPrefillBackend.is_available returns rocm_aiter_ops.is_enabled() as is (None when AITER is unsupported, which is falsy)",
                   "source": C(PAF, aa, ab), "call": "aiter-ops.is-enabled", "input": {}, "as": "e"},
                  {"return": {"available": "= vars.e.value.enabled == true", "value": "= vars.e.value.enabled"}}]},
        {"if": "!(input.backend in " + tq + ")",
         "then": [{"title": "Not a modeled MLA prefill backend class", "source": C(PBASE, *cls(PBASE, "MLAPrefillBackend")[:1]),
                   "fail": {"code": "key-error", "message": "= \"'\" + input.backend + \"'\""}}]},
        {"title": "Other backends: the import probe of their package (vllm_flash_attn and flashinfer ship with the CUDA wheel; tokenspeed_mla is an optional extra); the base class is always available",
         "source": C(PBASE, ba, bb),
         "return": {"available": "= " + tq + "[input.backend]", "value": "= " + tq + "[input.backend]"}},
    ]
    return iface("mla-prefill-backend", "is-available",
                 "MLAPrefillBackend.is_available per backend class: AITER asks rocm_aiter_ops.is_enabled(); the others probe their package.",
                 [C(PAF, aa, ab), C(PBASE, ba, bb), Cm(PFA, "FlashAttnPrefillBackend", "is_available")], beh,
                 request=obj({"backend": S("FLASH_ATTN")}),
                 response=obj({"available": {"type": "boolean"}, "value": {"type": ["boolean", "null"]}}),
                 errors=[err("key-error", "not a modeled MLA prefill backend")])


def interfaces():
    return boundary_interfaces() + [reorder_interface()] + tokenspeed_interfaces() + [prefill_available_interface()]


def _ro(a, sched, comp_, prompt, thr=1):
    ids = [f"r{i}" for i in range(len(comp_))]
    return step("attention-backend-utils.reorder-batch-to-split-decodes-and-prefills",
                {"req_ids": ids, "num_scheduled_tokens": dict(zip(ids, sched)), "num_computed_tokens": comp_, "num_prompt_tokens": prompt, "decode_threshold": thr}, a)


def scenarios():
    S_ = []
    # oracle3 #1: the reorder (test_batch_reordering.py cases), plus a threshold > 1 and an all-prefill batch.
    S_.append({"id": "attention-r5-reorder-batch-split", "name": "reorder_batch_to_split_decodes_and_prefills: mixed decodes and long extends, already ordered, four regions, threshold 4, all prefills",
               "fixtures": FX,
               "steps": [_ro("mixed", [100, 1, 200, 1], [100, 10, 200, 20], [100, 10, 200, 20]),
                         _ro("ordered", [1, 1, 100, 200], [10, 20, 100, 0], [10, 20, 100, 200]),
                         _ro("fourway", [100, 1, 1, 10], [0, 50, 100, 50], [100, 100, 100, 100]),
                         _ro("thr4", [3, 8, 2], [0, 40, 30], [10, 40, 30], 4),
                         _ro("pre", [5, 6], [0, 0], [5, 6])],
               "expect": ["steps.mixed.result.value.modified && steps.mixed.result.value.req_ids == ['r3', 'r1', 'r2', 'r0']",
                          "!steps.ordered.result.value.modified && steps.ordered.result.value.req_ids == ['r0', 'r1', 'r2', 'r3']",
                          "steps.fourway.result.value.modified && steps.fourway.result.value.req_ids == ['r2', 'r1', 'r3', 'r0']",
                          "steps.thr4.result.value.req_ids == ['r2', 'r1', 'r0']",
                          "!steps.pre.result.value.modified"]})
    # oracle3 #2: indexer kernel block sizes by class.
    d = lambda a, **kw: step("attention-backend.describe", kw, a)
    S_.append({"id": "attention-r5-indexer-kernel-block-sizes", "name": "Indexer backends: DeepSeek V3.2 [64] on CUDA and [1, MultipleOf(16)] on ROCm; the GLM-5 indexer is index_kpool x (32, 64), only 64 on SM120, with or without a spec; the kpool tail takes any block",
               "fixtures": FX,
               "steps": [d("ds", backend="DEEPSEEK_V32_INDEXER"), d("dsr", backend="DeepseekV32IndexerBackend", is_rocm=True),
                         d("glm", backend="Glm5NextIndexerBackend", kv_cache_spec={"tokens_per_state": 4}),
                         d("glm_cfg", backend="Glm5NextIndexerBackend", index_kpool=4),
                         d("glm120", backend="Glm5NextIndexerBackend", index_kpool=4, device_capability_family=120),
                         d("glm_rocm", backend="Glm5NextIndexerBackend", index_kpool=4, is_rocm=True),
                         d("tail", backend="KPOOL_TAIL"), d("bad", backend="NOPE")],
               "expect": ["steps.ds.result.value.kernel_block_sizes == [64] && steps.ds.result.value.name == 'DEEPSEEK_V32_INDEXER'",
                          "steps.dsr.result.value.kernel_block_sizes == [1, 'MultipleOf(16)']",
                          "steps.glm.result.value.kernel_block_sizes == [128, 256] && steps.glm.result.value.name == 'DEEPSEEK_V32_INDEXER'",
                          "steps.glm_cfg.result.value.kernel_block_sizes == [128, 256] && steps.glm120.result.value.kernel_block_sizes == [256]",
                          "steps.glm_rocm.result.value.kernel_block_sizes == [128, 256]",
                          "steps.tail.result.value.layouts == ['BLHNC'] && steps.tail.result.value.kernel_block_sizes == ['MultipleOf(1)']",
                          "!steps.bad.result.ok && steps.bad.result.error.code == 'key-error' && steps.bad.result.error.message == \"'NOPE'\""]})
    # oracle3 #3: DeepSeek V4 ROCm builders.
    cg = lambda a, **kw: step("attention-metadata-builder.get-cudagraph-support", kw, a)
    for adaptive in (True, False):
        want = "ALWAYS" if adaptive else "UNIFORM_BATCH"
        S_.append({"id": f"attention-r5-dsv4-rocm-cg-{'adaptive' if adaptive else 'fixed'}",
                   "name": f"DeepSeek V4 ROCm AITER sparse-MLA and SWA builders: {want} {'with' if adaptive else 'without'} adaptive verification; the CUDA SWA builder stays UNIFORM_BATCH",
                   "fixtures": FX, "config": {"enable-adaptive-verification": adaptive},
                   "steps": [cg("mla", backend="ROCM_FLASHMLA_SPARSE_DSV4"), cg("swa", backend="DEEPSEEK_SPARSE_SWA", is_rocm=True),
                             cg("cuda_swa", backend="DEEPSEEK_SPARSE_SWA"), cg("fi", backend="FLASHINFER_MLA_SPARSE_DSV4")],
                   "expect": [f"steps.mla.result.value.support == '{want}' && steps.swa.result.value.support == '{want}'",
                              "steps.cuda_swa.result.value.support == 'UNIFORM_BATCH' && steps.fi.result.value.support == 'ALWAYS'"]})
    S_.append({"id": "attention-r5-fa-cg-support-follows-fa-version", "name": "FlashAttention's builder support is fixed by get_flash_attn_version(): FA2 (attention_config.flash_attn_version 2) gives UNIFORM_BATCH, the H100 default FA3 ALWAYS",
               "fixtures": FX, "config": {"flash-attn-version": 2},
               "steps": [cg("fa2", backend="FLASH_ATTN"), cg("pinned3", backend="FLASH_ATTN", fa_version=3)],
               "expect": ["steps.fa2.result.value.support == 'UNIFORM_BATCH' && steps.pinned3.result.value.support == 'ALWAYS'",
                          "trace.exists(e, e.type == 'call.end' && e.interface == 'fa-utils.get-flash-attn-version' && e.output.fa_version == 2)"]})
    # FP8 worlds: the KV cache dtype reaches the FlashAttention impl.
    fwd = "flash-attention-impl.forward"
    upd = "flash-attention-impl.do-kv-cache-update"
    chat = {"flow": "serving-api-chat-completion", "as": "chat", "input": {"body": {"model": "llama-3-8b-fp8", "max_tokens": 2}}}
    S_.append({"id": "attention-r5-fp8-kv-world-forward", "name": "FP8 world with --kv-cache-dtype fp8: FlashAttention (FA3 on the H100) writes 1-byte scaled K/V and reads the cache as fp8 with k/v and q descales",
               "fixtures": W_FP8KV, "steps": [chat],
               "expect": ["steps.chat.result.ok",
                          f"trace.exists(e, e.type == 'call.end' && e.interface == '{upd}' && e.output.kv_cache_dtype == 'fp8' && e.output.cache_bytes_per_element == 1 && e.output.scaled)",
                          f"trace.exists(e, e.type == 'call.end' && e.interface == '{fwd}' && e.output.path == 'paged' && e.output.kv_cache_view == 'fp8' && e.output.q_descale && e.output.fa_version == 3)"]})
    S_.append({"id": "attention-r5-fp8-checkpoint-auto-kv", "name": "FP8 checkpoint with kv_cache_dtype auto: the KV cache stays in the model dtype (bf16, 2 bytes), the cache isn't viewed as fp8",
               "fixtures": W_FP8, "steps": [chat],
               "expect": ["steps.chat.result.ok",
                          f"trace.exists(e, e.type == 'call.end' && e.interface == '{upd}' && e.output.kv_cache_dtype == 'auto' && e.output.cache_bytes_per_element == 2 && !e.output.scaled)",
                          f"trace.exists(e, e.type == 'call.end' && e.interface == '{fwd}' && e.output.kv_cache_view == 'model')",
                          f"!trace.exists(e, e.type == 'note' && e.title.startsWith('Quantized KV: the cache is viewed'))"]})
    fi = lambda a, **kw: step("flash-attention-impl.init", kw, a)
    v = lambda a, **kw: step("attention-backend.validate-configuration", dict({"backend": "FLASH_ATTN"}, **kw), a)
    S_.append({"id": "attention-r5-fp8-kv-impl-and-selection", "name": "FP8 KV on FlashAttention: FA3 on SM90 accepts fp8; fp8_e5m2 is refused, and any quantized dtype on Ampere (FA2), with the exact message (init checks only flash_attn_supports_kv_cache_dtype, so nvfp4 passes on SM90); selection rejects e5m2 and SM90 FP8 with a multimodal prefix",
               "fixtures": W_FP8KV,
               "steps": [fi("fp8", kv_cache_dtype="fp8"), fi("e5m2", kv_cache_dtype="fp8_e5m2"), fi("nvfp4", kv_cache_dtype="nvfp4"), fi("nvfp4_a100", kv_cache_dtype="nvfp4", device_capability_major=8),
                         fi("fa4_512", kv_cache_dtype="fp8", head_size=512, device_capability_major=9),
                         v("ok", kv_cache_dtype="fp8"), v("e5m2v", kv_cache_dtype="fp8_e5m2"),
                         v("mm", kv_cache_dtype="fp8", use_mm_prefix=True, fa4_supported=True, fa_version=4, head_size=128)],
               "expect": ["steps.fp8.result.ok && steps.fp8.result.value.fa_version == 3",
                          "!steps.e5m2.result.ok && steps.e5m2.result.error.code == 'not-implemented-error' && steps.e5m2.result.error.message == 'FlashAttention does not support fp8_e5m2 kv-cache on this device.'",
                          "steps.nvfp4.result.ok && !steps.nvfp4_a100.result.ok && steps.nvfp4_a100.result.error.message == 'FlashAttention does not support nvfp4 kv-cache on this device.'",
                          "steps.fa4_512.result.ok && steps.fa4_512.result.value.fa_version == 4",
                          "steps.ok.result.value.invalid_reasons == []",
                          "steps.e5m2v.result.value.invalid_reasons == ['kv_cache_dtype not supported', 'FP8 KV cache requires FA3 on SM90, FA4 with head_size=512 on SM90, or FA4 on SM100']",
                          "steps.mm.result.value.invalid_reasons == ['SM90 FP8 KV with mm_prefix requires Triton']"]})
    # VL world: Qwen2-VL's vision tower attention (16 heads of 80, bidirectional, no KV cache).
    S_.append({"id": "attention-r5-vl-vision-encoder-attention", "name": "VL world: Qwen2-VL's vision blocks run encoder attention through the ViT FlashAttention wrapper (16 heads of 80, one image of 1024 patches, bidirectional, FA3 on the H100); an encoder FlashAttention layer refuses a quantized KV dtype",
               "fixtures": W_VL,
               "steps": [step("vit-attn-wrappers.vit-flash-attn-wrapper", {"shape": {"num_tokens": 1024, "num_seqs": 1, "num_heads": 16, "num_kv_heads": 16, "head_size": 80, "kv_tokens": 1024, "max_query_len": 1024}}, "vit"),
                         step(fwd, {"attn_type": "encoder_only", "num_tokens": 1024, "num_heads": 16, "num_kv_heads": 16, "head_size": 80}, "enc"),
                         step(fwd, {"attn_type": "encoder_only", "num_tokens": 16, "num_heads": 16, "num_kv_heads": 16, "head_size": 80, "kv_cache_dtype": "fp8"}, "encq")],
               "expect": ["steps.vit.result.ok",
                          "trace.exists(e, e.type == 'call.start' && e.interface == 'vit-attn-wrappers.flash-attn-maxseqlen-wrapper')",
                          "steps.enc.result.value.path == 'encoder' && steps.enc.result.value.fa_version == 3",
                          "!steps.encq.result.ok && steps.encq.result.error.message == 'quantization is not supported for encoder attention'",
                          "config['model-is-multimodal']"]})
    # MoE world: Mixtral's attention per TP rank.
    S_.append({"id": "attention-r5-moe-mixtral-per-rank-attention", "name": "MoE world: each of Mixtral's two TP ranks builds FlashAttention with 16 query heads over 4 KV heads (GQA 4), FA3, sliding window off; the builder supports full CUDA graphs",
               "fixtures": W_MOE,
               "steps": [step("flash-attention-impl.init", {"num_heads": 16, "num_kv_heads": 4, "head_size": 128}, "impl"),
                         cg("cg", backend="FLASH_ATTN")],
               "expect": ["steps.impl.result.value.num_queries_per_kv == 4 && steps.impl.result.value.fa_version == 3 && steps.impl.result.value.sliding_window == [-1, -1]",
                          "steps.cg.result.value.support == 'ALWAYS'", "config['tensor-parallel-size'] == 2"]})
    # Error-path sweep regressions: exact messages.
    S_.append({"id": "attention-r5-error-messages-sweep", "name": "Error messages word for word: the selector's invalid KV dtype, the causal-tensor dtype, merge strides, Triton reshape-and-cache, an unknown TurboQuant preset, enum registration",
               "fixtures": FX,
               "steps": [step("selector.get-attn-backend", {"head_size": 128, "dtype": "bfloat16", "kv_cache_dtype": "fp4", "attn_type": "decoder", "num_heads": 32}, "kv"),
                         step("flash-attention-metadata-builder.build", {"common": {"num_reqs": 1, "num_actual_tokens": 1, "max_query_len": 1, "max_seq_len": 1, "query_lens": [1], "seq_lens": [1],
                                                                                   "block_table": [[0]], "slot_mapping": [0], "causal": True, "causal_is_tensor": True, "causal_tensor_dtype": "int64"}}, "causal"),
                         step("merge-attn-states.merge-attn-states", {"head_strides_match": False, "prefix_head_stride": 128, "suffix_head_stride": 256}, "merge"),
                         step("merge-attn-states.merge-attn-states", {"output_dtype": "float8_e4m3fn"}, "mscale"),
                         step("triton-reshape-and-cache-flash.triton-reshape-and-cache-flash", {"kv_cache_dtype": "fp8", "device_capability_major": 8, "device_capability_minor": 0}, "trc"),
                         step("triton-reshape-and-cache-flash.triton-reshape-and-cache-flash", {"kv_cache_dtype": "fp8", "device_capability_major": 8, "device_capability_minor": 9}, "trc89"),
                         step("kv-quant-mode.get-kv-quant-mode", {"kv_cache_dtype": "turboquant_2bit"}, "tq"),
                         step("attention-backend-enum.register", {"name": "FLASH_ATTN", "value": "my.module.Backend"}, "dup")],
               "expect": ["!steps.kv.result.ok && steps.kv.result.error.message.startsWith('Invalid kv_cache_dtype: fp4. Valid values are: (\\'auto\\', \\'float16\\'') && steps.kv.result.error.message.endsWith(\"'nvfp4_4over6')\")",
                          "steps.causal.result.error.message == 'Per-request causal tensor must be int32, got torch.int64. Casting here would allocate a fresh tensor each build() and break FULL CUDA graph replay; allocate the buffer as int32.'",
                          "steps.merge.result.error.message == 'merge_attn_states requires prefix_output and suffix_output to have matching head strides, got 128 and 256'",
                          "steps.mscale.result.error.message == 'output_scale is required when output is torch.float8_e4m3fn'",
                          "steps.trc.result.error.message == 'Triton reshape-and-cache cannot store kv_cache_dtype=fp8 on this device: an FP8 KV cache needs native fp8e4nv (SM89+). Use --kv-cache-dtype bfloat16 (or float16 on SM75).'",
                          "steps.trc89.result.ok",
                          "!steps.tq.result.ok && steps.tq.result.error.code == 'key-error' && steps.tq.result.error.message == \"'TURBOQUANT_2BIT'\"",
                          "!steps.dup.result.ok && steps.dup.result.error.message == \"Backend FLASH_ATTN already exists in AttentionBackendEnum. Use register_backend(AttentionBackendEnum.FLASH_ATTN, 'my.module.Backend') to override.\""]})
    return S_


def oracle_doc():
    """build-oracle/round5/attention.yaml: the translated round-5 unit tests."""
    sc = []
    sp = lambda a, qsl, thr, uni, **kw: step("attention-backend-utils.split-decodes-and-prefills",
                                             dict({"query_start_loc_cpu": qsl, "num_reqs": len(qsl) - 1, "num_actual_tokens": qsl[-1],
                                                   "max_query_len": max(qsl[i + 1] - qsl[i] for i in range(len(qsl) - 1)), "decode_threshold": thr, "require_uniform": uni}, **kw), a)
    sc.append({"id": "oracle5-attention-split-uniform-all-ones", "name": "tests/v1/attention/test_attention_splitting.py:231 test_split_decodes_and_prefills_uniform_all_ones",
               "description": "query_lens [1, 1, 1], decode_threshold 1, require_uniform: every request is a decode (3, 0, 3, 0).",
               "fixtures": W, "steps": [sp("s", [0, 1, 2, 3], 1, True)],
               "expect": ["steps.s.result.value == {'num_decodes': 3, 'num_prefills': 0, 'num_decode_tokens': 3, 'num_prefill_tokens': 0}"]})
    sc.append({"id": "oracle5-attention-split-uniform-all-prefills", "name": "tests/v1/attention/test_attention_splitting.py:264 test_split_decodes_and_prefills_uniform_all_prefills",
               "description": "query_lens [4, 5, 6, 7], decode_threshold 3, require_uniform: the first request is above the threshold, so there are no decodes (0, 4, 0, 22).",
               "fixtures": W, "steps": [sp("s", [0, 4, 9, 15, 22], 3, True)],
               "expect": ["steps.s.result.value == {'num_decodes': 0, 'num_prefills': 4, 'num_decode_tokens': 0, 'num_prefill_tokens': 22}"]})
    steps, exp = [], []
    k = 0
    for min_split in (1, 8):
        for il in (1, 16, 896):
            for causal, tpd, dcp, rank in ((True, 1, 2, 1), (False, 3, 1, 0)):
                a = f"c{k}"
                ndt = 2 * tpd
                steps.append(step("tokenspeed-mla-impl.forward-mqa", {"num_decodes": 2, "num_decode_tokens": ndt, "num_heads": 128, "causal": causal, "dcp_world_size": dcp,
                                                                       "dcp_rank": rank, "cp_kv_cache_interleave_size": il, "min_split_kv": min_split,
                                                                       "seq_lens": [16, 24], "dcp_tot_seq_lens": [16, 24], "max_seq_len": 24,
                                                                       "q_scale": 2.0, "k_scale": 3.0, "softmax_scale": 1.0, "output_scale": 1.0}, a))
                kin = f"trace.filter(e, e.type == 'call.start' && e.interface == 'tokenspeed-mla-kernels.tokenspeed-mla-decode')[{k}].input"
                exp.append(f"steps.{a}.result.value.out_shape == [{ndt}, 128, 512] && steps.{a}.result.value.lse_shape == [{ndt}, 128]")
                exp.append(f"{kin}.workspace_buffer == 'workspace' && {kin}.min_split_kv == {min_split} && {kin}.query_shape == [2, {tpd}, 128, 576]"
                           f" && {kin}.seq_lens == [16, 24] && {kin}.causal_mask == {'true' if causal else 'false'} && {kin}.return_lse"
                           f" && {kin}.cp_world == {dcp} && {kin}.cp_rank == {rank} && {kin}.cp_interleave_size == {il}" +
                           (f" && {kin}.pass_causal_seqs && {kin}.causal_seqs == [16, 24]" if dcp > 1 else f" && !{kin}.pass_causal_seqs"))
                k += 1
    sc.append({"id": "oracle5-attention-tokenspeed-mla-decode-contract", "name": "tests/v1/attention/test_mla_backends.py:1099 test_tokenspeed_mla_decode_contract",
               "description": "All 12 parametrizations (causal-DCP rank 1 of 2 with one token per decode, non-causal 3 tokens per decode without DCP; interleave 1, 16, 896; min_split_kv 1, 8): "
                              "forward_mqa returns (tokens, 128, 512) and an LSE of (tokens, 128), and calls tokenspeed_mla_decode with the cached workspace, min_split_kv, the per-request query "
                              "shape, the decode seq lens, causal_seqs only under DCP, causal_mask, return_lse, and the DCP world, rank and interleave read at call time. "
                              "The softmax and output scales are already set on the impl (the test sets them to 1.0). Block-table equality is a tensor check below the model's level.",
               "fixtures": W, "steps": steps, "expect": exp})
    aiter_state = lambda en: {"aiter-ops": {"aiter_found": True, "gcn_arch": "gfx942", "flags": {"_AITER_ENABLED": en}}}
    for en in (False, True):
        sc.append({"id": f"oracle5-attention-aiter-prefill-is-available-{'enabled' if en else 'disabled'}",
                   "name": "tests/v1/attention/test_mla_prefill_selector.py:556 test_is_available_delegates_to_rocm_aiter_ops" + (" (is_enabled True)" if en else " (is_enabled False)"),
                   "description": "AiterFlashAttnPrefillBackend.is_available returns rocm_aiter_ops.is_enabled(). The test patches is_enabled; the scenario sets AITER's enabled flag on a ROCm MI300 (gfx942) with aiter installed instead.",
                   "fixtures": W, "config": {"vllm-target-device": "rocm"}, "state": aiter_state(en),
                   "steps": [step("mla-prefill-backend.is-available", {"backend": "ROCM_AITER_FA"}, "a")],
                   "expect": [("" if en else "!") + "steps.a.result.value.available",
                              "trace.exists(e, e.type == 'call.end' && e.interface == 'aiter-ops.is-enabled' && e.output.enabled == " + ("true" if en else "false") + ")"]})
    return {"schema_version": 1, "id": "vllm", "scenarios": sc}

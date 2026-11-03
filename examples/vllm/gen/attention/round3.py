"""Round-3 additions: FlashInfer MLA decode, the K-pool tail slot arithmetic, the indexer's TP
row-sharding gate and the GDN speculative-row routing, with the build-oracle round-3 scenarios."""
from core import B, I, S, comp, err, iface
from lib import C, Cfn, cls, fn, ln, op_kernel

FIMLA = "vllm/v1/attention/backends/mla/flashinfer_mla.py"
IDX = "vllm/v1/attention/backends/mla/indexer.py"
GDN = "vllm/v1/attention/backends/gdn_attn.py"


def components():
    out = []
    a, b = cls(FIMLA, "FlashInferMLAImpl")
    out.append(comp("flashinfer-mla-impl", "FlashInferMLAImpl", FIMLA, "FlashInfer MLA decode (trtllm-gen or cute-dsl kernels).", a=a, b=b))
    a, b = cls(GDN, "GDNAttentionMetadataBuilder")
    out.append(comp("gdn-attention-metadata-builder", "GDNAttentionMetadataBuilder", GDN,
                    "Gated-DeltaNet (linear attention) metadata: routes speculative rows and picks the recurrent-state slots.", a=a, b=b))
    return out


def interfaces():
    out = []
    # ---- FlashInfer MLA forward_mqa
    out.append(op_kernel("flashinfer-mla-impl", "trtllm-batch-decode-with-kv-cache-mla", C(FIMLA, ln(FIMLA, r"kernel_out = trtllm_batch_decode_with_kv_cache_mla\(")),
                         "FlashInfer MLA decode kernel (trtllm-gen, or cute-dsl when backend='cute-dsl').", "flashinfer.trtllm_batch_decode_with_kv_cache_mla"))
    sa, sb = fn(FIMLA, "_trtllm_gen_mla_decode_supports_num_heads")
    ma, mb = fn(FIMLA, "forward_mqa")
    heads = "input.query_heads"
    tile = f"({heads} <= 8 ? 8 : ({heads} <= 32 ? 16 : 64))"
    beh = [
        {"if": "!input.has_decode", "then": [{"title": "forward_mqa needs decode metadata", "source": C(FIMLA, ln(FIMLA, r"assert attn_metadata.decode is not None", ma)),
                                               "fail": {"code": "assertion-error", "message": "attn_metadata.decode is None"}}]},
        {"title": "The kernel runs over the query's own head count (q.shape[-2]), which after a DCP query gather is larger than impl.num_heads",
         "source": C(FIMLA, ln(FIMLA, r"runtime_num_heads = q.shape\[-2\]", ma)), "set": {"vars.heads": f"= {heads}"}},
        {"if": "input.dcp_world_size > 1",
         "then": [{"title": "DCP: the native cute-dsl DCP API", "source": C(FIMLA, ln(FIMLA, r'decode_backend = "cute-dsl"', ma)), "set": {"vars.backend": "cute-dsl"}}],
         "else": [{"title": "trtllm-gen tiles Q heads in CTAs of min(heads, tile); a head count it can't tile falls back to cute-dsl",
                   "source": C(FIMLA, sa, sb),
                   "set": {"vars.backend": f"= {heads} % ({heads} < {tile} ? {heads} : {tile}) == 0 ? 'auto' : 'cute-dsl'"}}]},
        {"title": "trtllm_batch_decode_with_kv_cache_mla", "source": C(FIMLA, ln(FIMLA, r"kernel_out = trtllm_batch_decode_with_kv_cache_mla\(", ma)),
         "call": "flashinfer-mla-impl.trtllm-batch-decode-with-kv-cache-mla",
         "input": {"num_tokens": "= input.num_decode_tokens", "num_seqs": "= input.num_decodes", "num_heads": "= vars.heads", "head_size": 576, "kv_tokens": "= input.num_decodes"}},
        {"title": "Output flattened to [tokens, heads, kv_lora_rank]; LSE only when DCP needs it", "source": C(FIMLA, ln(FIMLA, r"o = o.view\(-1, o.shape\[-2\], o.shape\[-1\]\)", ma)),
         "return": {"backend": "= vars.backend", "output_shape": "= [input.num_decode_tokens, vars.heads, input.kv_lora_rank]",
                    "lse_shape": "= input.return_lse ? dyn([input.num_decode_tokens, vars.heads]) : dyn(null)"}},
    ]
    out.append(iface("flashinfer-mla-impl", "forward-mqa",
                     "FlashInferMLAImpl.forward_mqa: pick the decode backend from the query's head count (cute-dsl under DCP or when trtllm-gen can't tile the heads) and run the kernel.",
                     [C(FIMLA, ma, mb), C(FIMLA, sa, sb)], beh,
                     request={"type": "object", "properties": {"has_decode": B(True), "query_heads": I(16), "dcp_world_size": I(1), "num_decode_tokens": I(2),
                                                               "num_decodes": I(2), "kv_lora_rank": I(512), "return_lse": B(False)}},
                     response={"type": "object", "properties": {"backend": {"type": "string"}, "output_shape": {"type": "array"}, "lse_shape": {"type": ["array", "null"]}}},
                     errors=[err("assertion-error", "no decode metadata")]))

    # ---- TP prefill row-sharding gate
    ga, gb = fn(IDX, "tp_prefill_row_sharding_supported")
    out.append(iface("mla-indexer", "tp-prefill-row-sharding-supported",
                     "tp_prefill_row_sharding_supported: shard replicated indexer prefill rows across TP ranks only on CUDA, without DCP/PCP, with TP > 1, with PyNCCL and without NCCL symmetric memory or batch invariance, and never when mixed batches run inside FULL CUDA graphs.",
                     [C(IDX, ga, gb)],
                     [{"set": {"vars.mixed": "= input.cudagraph_mode == 'FULL_AND_PIECEWISE' ? 'PIECEWISE' : (input.cudagraph_mode == 'FULL_DECODE_ONLY' ? 'NONE' : input.cudagraph_mode)"}},
                      {"title": "CUDAGraphMode.mixed_mode(): the mode mixed (prefill+decode) batches run in", "source": Cfn("vllm/config/compilation.py", "mixed_mode")},
                      {"if": "input.platform == 'cuda' && input.dcp_world_size == 1 && !input.use_pcp && input.tp_size > 1 && !input.disable_pynccl && !input.use_nccl_symm_mem && !input.batch_invariant && vars.mixed != 'FULL'",
                       "then": [{"title": "Supported", "source": C(IDX, ln(IDX, r"return \(", ga), gb), "return": {"supported": True}}],
                       "else": [{"title": "Outside the safety envelope", "source": C(IDX, ln(IDX, r"return \(", ga), gb), "return": {"supported": False}}]}],
                     request={"type": "object", "properties": {"platform": S("cuda"), "dcp_world_size": I(1), "use_pcp": B(False), "tp_size": I(4),
                                                               "disable_pynccl": B(False), "use_nccl_symm_mem": B(False), "batch_invariant": B(False),
                                                               "cudagraph_mode": S("PIECEWISE", enum=["NONE", "PIECEWISE", "FULL", "FULL_DECODE_ONLY", "FULL_AND_PIECEWISE"])}},
                     response={"type": "object", "properties": {"supported": {"type": "boolean"}}}))

    # ---- GDN speculative routing
    ba, bb = fn(GDN, "build", cls(GDN, "GDNAttentionMetadataBuilder")[0])
    rows = "input.block_table"
    beh = [
        {"if": "!input.use_spec_decode || input.num_decode_draft_tokens == null",
         "then": [{"title": "No speculative config: no spec metadata", "source": C(GDN, ln(GDN, r"if not self.use_spec_decode or num_decode_draft_tokens_cpu is None:", ba)),
                   "set": {"vars.spec": 0}}],
         "else": [{"title": "Every row with num_decode_draft_tokens >= 0 is speculative, zero drafts included",
                   "source": C(GDN, ln(GDN, r"spec_sequence_masks_cpu = num_decode_draft_tokens_cpu >= 0", ba), ln(GDN, r"num_spec_decodes = spec_sequence_masks_cpu.sum\(\).item\(\)", ba)),
                   "set": {"vars.spec": "= input.num_decode_draft_tokens.filter(d, d >= 0).size()"}}]},
        {"if": "vars.spec == 0",
         "then": [{"title": "Plain path: state at block_table[:, 0]; the accepted-token counts are dropped",
                   "source": C(GDN, ln(GDN, r"non_spec_state_indices_tensor = block_table_tensor\[:, 0\]", ba)),
                   "return": {"num_spec_decodes": 0, "num_decodes": "= input.query_lens.filter(q, q == 1).size()",
                              "num_accepted_tokens": None, "spec_state_indices": None, "non_spec_state_indices": f"= {rows}.map(r, r[0])"}}]},
        {"set": {"vars.ns": "= lists.range(size(input.query_lens)).filter(i, !(i < size(input.num_decode_draft_tokens) && input.num_decode_draft_tokens[i] >= 0))",
                 "vars.sr": "= lists.range(size(input.query_lens)).filter(i, i < size(input.num_decode_draft_tokens) && input.num_decode_draft_tokens[i] >= 0)"}},
        {"set": {"vars.dec": "= vars.ns.filter(i, input.query_lens[i] == 1).size()", "vars.pre": "= vars.ns.filter(i, input.query_lens[i] != 1).size()"}},
        {"title": "Decodes and spec decodes are exclusive: non-spec decodes count as prefills",
         "source": C(GDN, ln(GDN, r"if num_decodes > 0 and num_spec_decodes > 0:", ba)),
         "when": "vars.dec > 0", "set": {"vars.pre": "= vars.pre + vars.dec", "vars.dec": 0}},
        {"title": "Spec rows read their state from block_table[:, :num_spec + 1] at column num_accepted_tokens - 1",
         "source": C(GDN, ln(GDN, r"spec_state_indices_tensor = block_table_tensor\[", ba), ln(GDN, r"spec_state_indices_tensor = block_table_tensor\[", ba) + 2),
         "return": {"num_spec_decodes": "= vars.spec", "num_decodes": "= vars.dec",
                    "num_accepted_tokens": "= vars.sr.map(i, input.num_accepted_tokens[i])",
                    "spec_state_indices": f"= vars.sr.map(i, {rows}[i].slice(0, input.num_spec + 1))",
                    "non_spec_state_indices": "= vars.pre == 0 ? dyn(null) : dyn(vars.ns.map(i, input.block_table[i][0]))"}},
    ]
    out.append(iface("gdn-attention-metadata-builder", "build",
                     "GDNAttentionMetadataBuilder.build: which rows take the speculative path (num_decode_draft_tokens >= 0) and which recurrent-state slots they read.",
                     [C(GDN, ba, bb), C(GDN, *cls(GDN, "GDNAttentionMetadata"))], beh,
                     request={"type": "object", "properties": {"use_spec_decode": B(True), "num_spec": I(3),
                                                               "num_decode_draft_tokens": {"type": ["array", "null"], "items": {"type": "integer"}, "default": [0, 0]},
                                                               "query_lens": {"type": "array", "items": {"type": "integer"}, "default": [1, 1]},
                                                               "num_accepted_tokens": {"type": "array", "items": {"type": "integer"}, "default": [1, 1]},
                                                               "block_table": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}, "default": [[0, 1, 2, 3], [4, 5, 6, 7]]}}},
                     response={"type": "object", "properties": {"num_spec_decodes": {"type": "integer"}, "num_decodes": {"type": "integer"}}}))
    return out


def flows():
    return [
        {"id": "attn-flashinfer-mla-decode", "name": "FlashInfer MLA decode", "entry": {"caller": "gpu-worker", "interface": "flashinfer-mla-impl.forward-mqa",
                                                                                          "input": {"has_decode": True, "query_heads": 16, "dcp_world_size": 1, "num_decode_tokens": 2, "num_decodes": 2, "kv_lora_rank": 512, "return_lse": False}},
         "sources": [Cfn(FIMLA, "forward_mqa")]},
        {"id": "attn-indexer-row-shard-gate", "name": "Indexer TP row-sharding gate", "entry": {"caller": "gpu-worker", "interface": "mla-indexer.tp-prefill-row-sharding-supported",
                                                                                                "input": {"platform": "cuda", "tp_size": 4, "cudagraph_mode": "PIECEWISE"}},
         "sources": [Cfn(IDX, "tp_prefill_row_sharding_supported")]},
        {"id": "attn-gdn-build-metadata", "name": "GDN metadata: speculative row routing", "entry": {"caller": "gpu-worker", "interface": "gdn-attention-metadata-builder.build",
                                                                                                      "input": {"use_spec_decode": True, "num_spec": 3}},
         "sources": [Cfn(GDN, "build", cls(GDN, "GDNAttentionMetadataBuilder")[0])]},
    ]


FX = ["tp1-llama-8b", "attention-seed"]


def scenarios():
    """Fragment scenarios for the branches the round-3 oracle doesn't run."""
    return [
        {"id": "attention-flashinfer-mla-decode-tileable", "name": "16 query heads tile for trtllm-gen: auto backend", "flow": "attn-flashinfer-mla-decode", "fixtures": FX,
         "expect": ["result.value.backend == 'auto' && result.value.output_shape == [2, 16, 512] && result.value.lse_shape == null"]},
        {"id": "attention-flashinfer-mla-decode-dcp", "name": "Under DCP the cute-dsl backend serves the gathered heads, with LSE", "flow": "attn-flashinfer-mla-decode", "fixtures": FX,
         "input": {"dcp_world_size": 2, "query_heads": 32, "return_lse": True},
         "expect": ["result.value.backend == 'cute-dsl' && result.value.lse_shape == [2, 32]"]},
        {"id": "attention-flashinfer-mla-decode-no-metadata", "name": "No decode metadata", "flow": "attn-flashinfer-mla-decode", "fixtures": FX,
         "input": {"has_decode": False}, "expect": ["!result.ok && result.error.code == 'assertion-error'"]},
        {"id": "attention-gdn-plain-and-mixed", "name": "No spec config: plain decode path; mixed batch keeps non-spec prefill rows",
         "fixtures": FX,
         "steps": [{"flow": "attn-gdn-build-metadata", "input": {"use_spec_decode": False}, "as": "plain"},
                   {"flow": "attn-gdn-build-metadata", "input": {"num_decode_draft_tokens": [2, -1, -1], "query_lens": [3, 1, 7], "num_accepted_tokens": [2, 1, 1],
                                                                 "block_table": [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]]}, "as": "mixed"}],
         "expect": ["steps.plain.result.value.num_spec_decodes == 0 && steps.plain.result.value.num_decodes == 2 && steps.plain.result.value.non_spec_state_indices == [0, 4]",
                    "steps.mixed.result.value.num_spec_decodes == 1 && steps.mixed.result.value.num_decodes == 0 && steps.mixed.result.value.non_spec_state_indices == [4, 8]"]},
        {"id": "attention-kpool-tail-null-block-and-fallback", "name": "Null-block requests map to -1; non-CUDA tensors take the torch fallback", "fixtures": FX,
         "steps": [{"interface": "mla-indexer.compute-kpool-tail-slot-mapping", "caller": "gpu-worker", "as": "n",
                    "input": {"kpool": 4, "is_cuda": False, "requests": [{"own_block": 0, "positions": [3, 4]}, {"own_block": 7, "positions": [9]}]}}],
         "expect": ["steps.n.result.value.slots == [[-1, -1], [29]] && steps.n.result.value.path == 'torch'"]},
    ]


def oracle_doc():
    """build-oracle/round3/attention.yaml: the translated round-3 unit tests."""
    w = ["full-tp1-llama-8b"]
    sc = []
    sc.append({
        "id": "oracle3-attention-flashinfer-mla-gathered-heads",
        "name": "tests/v1/attention/test_flashinfer_mla_dcp.py:42 test_flashinfer_mla_forward_uses_gathered_head_count",
        "description": "impl.num_heads is 6, but the DCP-gathered query has 24 heads: forward_mqa sizes the kernel from q.shape[-2]; 24 isn't divisible by trtllm-gen's 16-head tile, so backend='cute-dsl'; output (2, 24, 512), lse (2, 24).",
        "fixtures": w,
        "steps": [{"interface": "flashinfer-mla-impl.forward-mqa", "caller": "gpu-worker", "as": "fwd",
                   "input": {"has_decode": True, "query_heads": 24, "dcp_world_size": 1, "num_decode_tokens": 2, "num_decodes": 2, "kv_lora_rank": 512, "return_lse": True}}],
        "expect": ["steps.fwd.result.value.backend == 'cute-dsl'", "steps.fwd.result.value.output_shape == [2, 24, 512]", "steps.fwd.result.value.lse_shape == [2, 24]"]})
    sc.append({
        "id": "oracle3-attention-kpool-tail-circular-isolation",
        "name": "tests/v1/attention/test_kpool_tail_slot_mapping.py:391 test_interleaved_decode_pollution_legacy_vs_circular (the circular mapping's part)",
        "description": "KPOOL=4. A (tail block 5) decodes positions 8..11, B (tail block 9) 8..13 interleaved: the circular mapping own_block * kpool + pos % kpool keeps A's boundary pool [8..11] in A's ring (slots 20..23), disjoint from B's (36..39). The legacy mapping and the pooled-value comparison are test-only code (see the .md).",
        "fixtures": w,
        "steps": [{"interface": "mla-indexer.compute-kpool-tail-slot-mapping", "caller": "gpu-worker", "as": "map",
                   "input": {"kpool": 4, "is_cuda": True, "requests": [{"own_block": 5, "positions": [8, 9, 10, 11]}, {"own_block": 9, "positions": [8, 9, 10, 11, 12, 13]}]}}],
        "expect": ["steps.map.result.value.slots[0] == [20, 21, 22, 23]",
                   "steps.map.result.value.slots[1].all(s, s >= 36 && s <= 39)",
                   "!steps.map.result.value.slots[0].exists(s, s in steps.map.result.value.slots[1])"]})
    gate = lambda as_, inp: {"interface": "mla-indexer.tp-prefill-row-sharding-supported", "caller": "gpu-worker", "as": as_,
                             "input": dict({"platform": "cuda", "dcp_world_size": 1, "use_pcp": False, "tp_size": 4, "disable_pynccl": False,
                                            "use_nccl_symm_mem": False, "batch_invariant": False, "cudagraph_mode": "PIECEWISE"}, **inp)}
    sc.append({
        "id": "oracle3-attention-row-sharding-gate",
        "name": "tests/v1/attention/test_indexer_tp_row_shard.py:108 test_row_sharding_gate_rejects_unsupported_configurations",
        "fixtures": w,
        "steps": [gate("ok", {}), gate("tp1", {"tp_size": 1}), gate("dcp", {"dcp_world_size": 2}), gate("pcp", {"use_pcp": True}),
                  gate("nopynccl", {"disable_pynccl": True}), gate("symm", {"use_nccl_symm_mem": True}), gate("bi", {"batch_invariant": True}),
                  gate("full", {"cudagraph_mode": "FULL"}), gate("fap", {"cudagraph_mode": "FULL_AND_PIECEWISE"})],
        "expect": ["steps.ok.result.value.supported",
                   "[steps.tp1, steps.dcp, steps.pcp].all(s, !s.result.value.supported)",
                   "[steps.nopynccl, steps.symm, steps.bi].all(s, !s.result.value.supported)",
                   "!steps.full.result.value.supported", "steps.fap.result.value.supported"]})
    sc.append({
        "id": "oracle3-attention-gdn-zero-draft-spec-rows",
        "name": "tests/v1/attention/test_gdn_zero_draft_spec_rows.py:170 test_zero_draft_batch_still_applies_the_accepted_token_offset (gdn_none)",
        "description": "Two decode rows with zero drafts (num_decode_draft_tokens = [0, 0]) and accepted [3, 1] stay on the speculative path: num_spec_decodes 2, num_decodes 0, accepted counts kept, no non-spec state indices; row 0 reads column 2 (a different block from column 0), row 1 reads column 0. The kimi_kda_align case differs only in state shape and cache mode, which the model doesn't carry.",
        "fixtures": w,
        "steps": [{"interface": "gdn-attention-metadata-builder.build", "caller": "gpu-worker", "as": "meta",
                   "input": {"use_spec_decode": True, "num_spec": 3, "num_decode_draft_tokens": [0, 0], "query_lens": [1, 1], "num_accepted_tokens": [3, 1],
                             "block_table": [[0, 1, 2, 3], [4, 5, 6, 7]]}}],
        "expect": ["steps.meta.result.value.num_spec_decodes == 2 && steps.meta.result.value.num_decodes == 0",
                   "steps.meta.result.value.num_accepted_tokens == [3, 1]",
                   "steps.meta.result.value.non_spec_state_indices == null",
                   "[0, 1].all(r, (steps.meta.result.value.spec_state_indices[r][[3, 1][r] - 1] != steps.meta.result.value.spec_state_indices[r][0]) == ([3, 1][r] > 1))"]})
    return {"schema_version": 1, "id": "vllm", "scenarios": sc}

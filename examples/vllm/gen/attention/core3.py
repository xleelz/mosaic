"""DCP combine ops and direct CUDA ops, ViT wrappers, MLA prefill gate, CPU MLA, CPU attention ISA."""
from core import (A2A, B, CPUA, CPUMLA, DCOM, DCP, FAI, I, KVG, MLAP, MLAPFA, QG, S, TPA, VIT, err, iface)
from lib import (C, Cfn, Cinv, Cln, LAT_ATTN, LAT_META, SHAPE, cls, fn, helper, kernel, launch, ln, mark,
                 note)

DSHAPE = "= has(input.shape) ? input.shape : {}"


def dcp_interfaces():
    out = []
    out.append(kernel("dcp", "correct-attn-cp-out-kernel", DCP, "CorrectAttnCPOutKernel.kernel",
                      "CorrectAttnCPOutKernel: rescale this rank's partial output by the all-gathered LSEs.", lat=LAT_META))
    out.append(kernel("dcp", "dcp-a2a-pack-send-kernel", DCP, "_dcp_a2a_pack_send_kernel",
                      "Pack partial output + LSE per destination rank into the all-to-all send buffer.", lat=LAT_META))
    out.append(kernel("dcp", "dcp-a2a-unpack-combine-kernel", DCP, "_dcp_a2a_unpack_combine_kernel",
                      "Unpack the received partials and combine them with exact LSE weighting.", lat=LAT_META))
    # cp_lse_ag_out_rs
    ra, rb = fn(DCP, "cp_lse_ag_out_rs")
    ca, cb = fn(DCP, "_cp_lse_common")
    xa, xb = fn(DCP, "correct_attn_out")
    beh = [
        {"if": "input.world_size == 1",
         "then": [{"title": "Single rank: nothing to combine", "source": C(DCP, ln(DCP, r"if cp_group.world_size == 1:", ca)), "return": {"combined": False}}]},
        {"title": "Mask empty shards, then all-gather every rank's LSE", "source": C(DCP, ln(DCP, r"lses = cp_group.all_gather\(cp_attn_lse, dim=0\)", ca)),
         "call": "group-coordinator.all-gather", "input": {"num_tokens": "= has(input.shape) && has(input.shape.num_tokens) ? input.shape.num_tokens : 1", "world_size": "= input.world_size", "group_name": "dcp:0", "ranks": "= lists.range(input.world_size).map(r, 'rank' + string(r))", "dim": 0}},
        {"title": "Correct the local output with the gathered LSEs", "source": C(DCP, ln(DCP, r"_CORRECT_ATTN_CP_OUT_KERNEL\(", xa)),
         "call": "dcp.correct-attn-cp-out-kernel", "input": DSHAPE, "fill": True},
        {"title": "Reduce-scatter the corrected outputs over heads", "source": C(DCP, ln(DCP, r"out = cp_group.reduce_scatter\(out, dim=1\)", ra)),
         "call": "group-coordinator.reduce-scatter", "input": {"num_tokens": "= has(input.shape) && has(input.shape.num_tokens) ? input.shape.num_tokens : 1", "world_size": "= input.world_size", "group_name": "dcp:0", "ranks": "= lists.range(input.world_size).map(r, 'rank' + string(r))", "dim": 1}},
        {"return": {"combined": True, "via": "ag_rs"}},
    ]
    out.append(iface("dcp", "cp-lse-ag-out-rs",
                     "cp_lse_ag_out_rs: all-gather LSEs, correct the partial output, reduce-scatter it over heads.",
                     [C(DCP, ra, rb), C(DCP, ca, cb), C(DCP, xa, xb)], beh,
                     request={"type": "object", "properties": {"world_size": I(2), "shape": {"$ref": "AttnKernelShape"}}},
                     response={"type": "object", "properties": {"combined": {"type": "boolean"}, "via": {"type": "string"}}}))
    aa, ab = fn(DCP, "dcp_a2a_lse_reduce")
    pa, pb = fn(DCP, "_dcp_a2a_pack_send")
    ua, ub = fn(DCP, "_dcp_a2a_unpack_combine")
    beh = [
        {"if": "input.world_size == 1",
         "then": [{"title": "Single rank: return the partials unchanged", "source": C(DCP, ln(DCP, r"if world_size == 1:", aa)), "return": {"combined": False}}]},
        {"if": "input.num_heads % input.world_size != 0",
         "then": [{"title": "Heads must split evenly across DCP ranks", "source": C(DCP, ln(DCP, r"if H % world_size != 0:", aa)),
                   "fail": {"code": "value-error", "message": "= 'H=' + string(input.num_heads) + ' must be divisible by DCP world size ' + string(input.world_size) + '.'"}}]},
        {"title": "Pack output + LSE per destination", "source": C(DCP, ln(DCP, r"_dcp_a2a_pack_send_kernel\[grid\]\(", pa)),
         "call": "dcp.dcp-a2a-pack-send-kernel", "input": DSHAPE, "fill": True},
        {"title": "One all_to_all_single over the DCP device group, then wait", "source": C(DCP, ln(DCP, r"work = dist.all_to_all_single\(", aa)),
         "detail": "torch.distributed directly, not a GroupCoordinator method; modeled as a narrative step."},
        {"title": "Unpack and combine", "source": C(DCP, ln(DCP, r"_dcp_a2a_unpack_combine_kernel\[grid\]\(", ua)),
         "call": "dcp.dcp-a2a-unpack-combine-kernel", "input": DSHAPE, "fill": True},
        {"return": {"combined": True, "via": "a2a"}},
    ]
    out.append(iface("dcp", "dcp-a2a-lse-reduce",
                     "dcp_a2a_lse_reduce: pack partial outputs and LSEs, one all-to-all, unpack and combine with exact LSE weights.",
                     [C(DCP, aa, ab), C(DCP, pa, pb), C(DCP, ua, ub)], beh,
                     request={"type": "object", "properties": {"world_size": I(2), "num_heads": I(64), "shape": {"$ref": "AttnKernelShape"}}},
                     response={"type": "object", "properties": {"combined": {"type": "boolean"}, "via": {"type": "string"}}},
                     errors=[err("value-error", "heads not divisible by the DCP world size")]))

    # direct CUDA ops
    mark(A2A, "_C::direct_dcp_a2a_lse_reduce")
    a, b = fn_cu(A2A, "void direct_dcp_a2a_lse_reduce(")
    beh = [
        {"if": "input.world_size <= 1", "then": [{"title": "world_size must be greater than 1", "source": C(A2A, ln(A2A, r"world_size must be greater than 1")),
                                                  "fail": {"code": "runtime-error", "message": "world_size must be greater than 1"}}]},
        {"if": "input.num_tokens <= 0 || input.num_tokens > input.max_num_tokens",
         "then": [{"title": "num_tokens must fit the symmetric workspace", "source": C(A2A, ln(A2A, r"STD_TORCH_CHECK\(num_tokens > 0 && num_tokens <= max_num_tokens")),
                   "fail": {"code": "runtime-error", "message": "num_tokens out of range for the direct DCP workspace"}}]},
        {"title": "increment_epoch_kernel bumps the exchange epoch", "source": Cinv(DCOM, "increment_epoch_kernel")},
        {"title": "dispatch_output_lse_kernel writes each head slice to its owner's symmetric buffer", "source": Cinv(A2A, "dispatch_output_lse_kernel")},
        {"title": "signal_kernel raises this rank's arrival flag on every peer", "source": Cinv(A2A, "signal_kernel")},
        {"title": "wait_lse_combine_kernel waits for all peers and LSE-combines the received slices", "source": Cinv(A2A, "wait_lse_combine_kernel")},
        {"return": {"combined": True, "via": "direct"}},
    ]
    mark(DCOM, "increment_epoch_kernel")
    for n in ("dispatch_output_lse_kernel", "signal_kernel", "wait_lse_combine_kernel"):
        mark(A2A, n)
    out.append(iface("dcp-direct-a2a-lse-reduce", "direct-dcp-a2a-lse-reduce",
                     "Torch op _C::direct_dcp_a2a_lse_reduce (CUDA): symmetric-memory all-to-all LSE reduce in four kernel launches.",
                     [Cinv(A2A, "_C::direct_dcp_a2a_lse_reduce"), C(A2A, a, b)], beh, kind="kernel",
                     request={"type": "object", "properties": {"world_size": I(2), "num_tokens": I(8), "max_num_tokens": I(512), "kv_tokens": I(0), "num_heads": I(64), "head_size": I(512)}},
                     response={"type": "object", "properties": {"combined": {"type": "boolean"}, "via": {"type": "string"}}},
                     errors=[err("runtime-error", "STD_TORCH_CHECK failed")], latency_ms=LAT_META))
    mark(QG, "_C::direct_dcp_q_gather")
    mark(QG, "direct_dcp_q_gather_multimem_kernel")
    a, b = fn_cu(QG, "void direct_dcp_q_gather(")
    out.append(iface("dcp-direct-q-gather", "direct-dcp-q-gather",
                     "Torch op _C::direct_dcp_q_gather (CUDA): multimem broadcast of each rank's query heads.",
                     [Cinv(QG, "_C::direct_dcp_q_gather"), C(QG, a, b)],
                     [{"if": "input.world_size <= 1", "then": [{"title": "world_size must be greater than 1", "source": C(QG, ln(QG, r"world_size must be greater than 1")),
                                                                "fail": {"code": "runtime-error", "message": "world_size must be greater than 1"}}]},
                      {"title": "increment_epoch_kernel, then direct_dcp_q_gather_multimem_kernel", "source": Cinv(QG, "direct_dcp_q_gather_multimem_kernel")},
                      {"return": {"gathered": True}}], kind="kernel",
                     request={"type": "object", "properties": {"world_size": I(2), "num_tokens": I(8), "kv_tokens": I(0)}},
                     response={"type": "object", "properties": {"gathered": {"type": "boolean"}}},
                     errors=[err("runtime-error", "STD_TORCH_CHECK failed")], latency_ms=LAT_META))
    mark(KVG, "_C::direct_dcp_kv_gather")
    mark(KVG, "direct_dcp_kv_gather_multimem_kernel")
    mark(KVG, "materialize_kv_gather_kernel")
    a, b = fn_cu(KVG, "void direct_dcp_kv_gather(")
    out.append(iface("dcp-direct-kv-gather", "direct-dcp-kv-gather",
                     "Torch op _C::direct_dcp_kv_gather (CUDA): multimem gather of every rank's chunked-context KV, then materialize it contiguously.",
                     [Cinv(KVG, "_C::direct_dcp_kv_gather"), C(KVG, a, b)],
                     [{"if": "input.num_tokens * input.world_size > input.max_gathered_tokens",
                       "then": [{"title": "Gathered tokens exceed the workspace", "source": C(KVG, ln(KVG, r"STD_TORCH_CHECK\(num_tokens \* world_size <= max_gathered_tokens")),
                                 "fail": {"code": "runtime-error", "message": "num_tokens * world_size exceeds max_gathered_tokens"}}]},
                      {"title": "direct_dcp_kv_gather_multimem_kernel broadcasts the local KV rows", "source": Cinv(KVG, "direct_dcp_kv_gather_multimem_kernel")},
                      {"title": "materialize_kv_gather_kernel copies the received rows into gathered_kv", "source": Cinv(KVG, "materialize_kv_gather_kernel")},
                      {"return": {"gathered_tokens": "= input.num_tokens * input.world_size"}}], kind="kernel",
                     request={"type": "object", "properties": {"world_size": I(2), "num_tokens": I(8), "max_gathered_tokens": I(4096), "kv_tokens": I(0)}},
                     response={"type": "object", "properties": {"gathered_tokens": {"type": "integer"}}},
                     errors=[err("runtime-error", "STD_TORCH_CHECK failed")], latency_ms=LAT_META))

    # workspaces
    la, lb = fn(DCP, "lse_reduce", cls(DCP, "DirectDCPA2AWorkspace")[0])
    out.append(iface("direct-dcp-a2a-workspace", "lse-reduce",
                     "DirectDCPA2AWorkspace.lse_reduce: call the direct A2A op on this micro-batch's buffers.",
                     [C(DCP, la, lb)],
                     [{"title": "torch.ops._C.direct_dcp_a2a_lse_reduce", "source": C(DCP, ln(DCP, r"torch.ops._C.direct_dcp_a2a_lse_reduce\(", la)),
                       "call": "dcp-direct-a2a-lse-reduce.direct-dcp-a2a-lse-reduce", "input": "= input", "fill": True, "as": "r"},
                      {"return": "= vars.r.value"}],
                     request={"type": "object", "properties": {"world_size": I(2), "num_tokens": I(8), "max_num_tokens": I(512)}}))
    ga, gb = fn(DCP, "gather", cls(DCP, "DirectDCPQGatherWorkspace")[0])
    out.append(iface("direct-dcp-q-gather-workspace", "gather",
                     "DirectDCPQGatherWorkspace.gather: check the micro-batch slot and head count, then the direct q-gather op.",
                     [C(DCP, ga, gb)],
                     [{"if": "input.local_heads != input.heads_per_rank",
                       "then": [{"title": "Wrong number of local query heads", "source": C(DCP, ln(DCP, r"DCP q-gather expected", ga)),
                                 "fail": {"code": "value-error", "message": "= 'DCP q-gather expected ' + string(input.heads_per_rank) + ' local query heads, got ' + string(input.local_heads)"}}]},
                      {"title": "torch.ops._C.direct_dcp_q_gather", "source": C(DCP, ln(DCP, r"torch.ops._C.direct_dcp_q_gather\(", ga)),
                       "call": "dcp-direct-q-gather.direct-dcp-q-gather", "input": {"world_size": "= input.world_size", "num_tokens": "= input.num_tokens"}, "fill": True},
                      {"return": {"gathered": True}}],
                     request={"type": "object", "properties": {"world_size": I(2), "num_tokens": I(8), "local_heads": I(64), "heads_per_rank": I(64)}},
                     errors=[err("value-error", "head count mismatch")]))
    ka, kb = fn(DCP, "gather", cls(DCP, "DirectDCPKVGatherWorkspace")[0])
    out.append(iface("direct-dcp-kv-gather-workspace", "gather",
                     "DirectDCPKVGatherWorkspace.gather: the direct kv-gather op on this micro-batch's buffers.",
                     [C(DCP, ka, kb)],
                     [{"title": "torch.ops._C.direct_dcp_kv_gather", "source": C(DCP, ln(DCP, r"torch.ops._C.direct_dcp_kv_gather\(", ka)),
                       "call": "dcp-direct-kv-gather.direct-dcp-kv-gather", "input": "= input", "fill": True, "as": "r"},
                      {"return": "= vars.r.value"}],
                     request={"type": "object", "properties": {"world_size": I(2), "num_tokens": I(8), "max_gathered_tokens": I(4096)}}))

    # MLADCPManager
    wa, wb = fn(DCP, "_direct_workspace_combine")
    beh = [
        {"if": "input.use_direct_workspace && input.num_tokens <= input.max_num_tokens",
         "then": [{"title": "Fits the symmetric-memory workspace: direct A2A", "source": C(DCP, ln(DCP, r"if partial_output.shape\[0\] <= direct_workspace.max_num_tokens:", wa)),
                   "call": "direct-dcp-a2a-workspace.lse-reduce", "input": {"world_size": "= input.world_size", "num_tokens": "= input.num_tokens", "max_num_tokens": "= input.max_num_tokens"}, "as": "r"},
                  {"return": "= vars.r.value"}]},
        {"if": "input.use_a2a",
         "then": [{"title": "Too many tokens for the workspace (or no workspace): NCCL all-to-all combine", "source": C(DCP, ln(DCP, r"return dcp_a2a_lse_reduce\(", wa)),
                   "call": "dcp.dcp-a2a-lse-reduce", "input": {"world_size": "= input.world_size", "num_heads": "= input.num_heads", "shape": {"num_tokens": "= input.num_tokens"}}, "as": "r"},
                  {"return": "= vars.r.value"}]},
        {"title": "ag_rs: all-gather LSE, correct, reduce-scatter", "source": C(DCP, ln(DCP, r"else cp_lse_ag_out_rs", fn(DCP, "_init_combine")[0])),
         "call": "dcp.cp-lse-ag-out-rs", "input": {"world_size": "= input.world_size", "shape": {"num_tokens": "= input.num_tokens"}}, "as": "r"},
        {"return": "= vars.r.value"},
    ]
    ia, ib = fn(DCP, "_init_combine")
    out.append(iface("mla-dcp-manager", "combine",
                     "MLADCPManager combine (chosen in _init_combine): direct symmetric-memory A2A when the batch fits, else NCCL A2A, else all-gather + reduce-scatter.",
                     [C(DCP, ia, ib), C(DCP, wa, wb)], beh,
                     request={"type": "object", "properties": {"use_direct_workspace": B(True), "use_a2a": B(True), "num_tokens": I(8),
                                                               "max_num_tokens": I(512), "world_size": I(2), "num_heads": I(64)}},
                     response={"type": "object", "properties": {"combined": {"type": "boolean"}, "via": {"type": "string"}}}))
    qa, qb = fn(DCP, "_direct_workspace_query_gather")
    out.append(iface("mla-dcp-manager", "gather-query",
                     "MLADCPManager query gather: direct multimem gather when the batch fits the workspace, else GroupCoordinator.all_gather.",
                     [C(DCP, qa, qb), Cfn(DCP, "_gather_query")],
                     [{"if": "input.use_direct_workspace && input.num_tokens <= input.max_num_tokens",
                       "then": [{"title": "Direct q-gather", "source": C(DCP, ln(DCP, r"return direct_workspace.gather\(query\)", qa)),
                                 "call": "direct-dcp-q-gather-workspace.gather", "input": {"world_size": "= input.world_size", "num_tokens": "= input.num_tokens"}, "fill": True},
                                {"return": {"via": "direct"}}]},
                      {"title": "Fallback all-gather of query heads", "source": C(DCP, ln(DCP, r"query = self.group.all_gather\(query, dim=1\)")),
                       "call": "group-coordinator.all-gather", "input": {"num_tokens": "= input.num_tokens", "world_size": "= input.world_size", "group_name": "dcp:0", "ranks": "= lists.range(input.world_size).map(r, 'rank' + string(r))", "dim": 1}},
                      {"return": {"via": "all_gather"}}],
                     request={"type": "object", "properties": {"use_direct_workspace": B(True), "num_tokens": I(8), "max_num_tokens": I(512), "world_size": I(2)}},
                     response={"type": "object", "properties": {"via": {"type": "string"}}}))
    kga, kgb = fn(DCP, "kv_gather")
    out.append(iface("mla-dcp-manager", "kv-gather",
                     "MLADCPManager.kv_gather: the direct kv-gather workspace when init_kv_gather found one, else torch all_gather_into_tensor.",
                     [C(DCP, kga, kgb), Cfn(DCP, "init_kv_gather")],
                     [{"if": "input.use_direct_workspace",
                       "then": [{"title": "Direct symmetric-memory KV gather", "source": C(DCP, ln(DCP, r"self._kv_gather = direct_workspace.gather")),
                                 "call": "direct-dcp-kv-gather-workspace.gather", "input": {"world_size": "= input.world_size", "num_tokens": "= input.num_tokens", "max_gathered_tokens": "= input.max_gathered_tokens"}, "as": "r"},
                                {"return": "= vars.r.value"}]},
                      {"title": "torch.distributed.all_gather_into_tensor on the device group", "source": C(DCP, ln(DCP, r"torch.distributed.all_gather_into_tensor,")),
                       "return": {"gathered_tokens": "= input.num_tokens * input.world_size"}}],
                     request={"type": "object", "properties": {"use_direct_workspace": B(True), "num_tokens": I(8), "max_gathered_tokens": I(4096), "world_size": I(2)}},
                     response={"type": "object", "properties": {"gathered_tokens": {"type": "integer"}}}))
    return out


def fn_cu(f, sig):
    a = ln(f, __import__("re").escape(sig))
    # the function body ends at the first line that is exactly "}" after the signature
    from lib import lines
    for i, l in enumerate(lines(f), 1):
        if i > a and l.rstrip() == "}":
            return a, i
    return a, a


VIT_REQ = {
    "vit-flash-attn-wrapper": {"shape": {"$ref": "AttnKernelShape"}, "is_rocm_aiter": B(False), "fa_version": I(3)},
    "vit-triton-attn-wrapper": {"shape": {"$ref": "AttnKernelShape"}},
    "vit-torch-sdpa-wrapper": {"num_seqs": I(2), "seq_lens": {"type": "array", "items": {"type": "integer"}, "default": [256, 256]}},
    "vit-flashinfer-wrapper": {"is_reshaped": B(True)},
}


def vit_interfaces():
    out = []
    FAV = "flash-attn-interface.flash-attn-varlen-func"
    for n in ("flash_attn_maxseqlen_wrapper", "triton_attn_wrapper", "torch_sdpa_wrapper", "flashinfer_wrapper"):
        mark(VIT, "vllm::" + n)
    a, b = fn(VIT, "flash_attn_maxseqlen_wrapper")
    out.append(iface("vit-attn-wrappers", "flash-attn-maxseqlen-wrapper",
                     "Custom op vllm::flash_attn_maxseqlen_wrapper: bidirectional varlen attention over the encoder sequence (aiter on ROCm, else vLLM FA with the resolved version).",
                     [Cinv(VIT, "vllm::flash_attn_maxseqlen_wrapper"), C(VIT, a, b)],
                     [{"if": "input.is_rocm_aiter",
                       "then": [{"title": "ROCm aiter flash_attn_varlen_func", "source": C(VIT, ln(VIT, r"from aiter import flash_attn_varlen_func", a)),
                                 "return": {"impl": "aiter"}}]},
                      {"title": "vLLM FlashAttention, non-causal, cu_seqlens built from the batch when absent", "source": C(VIT, ln(VIT, r"output = flash_attn_varlen_func\(", a)),
                       "call": FAV, "input": {"shape": "= input.shape", "fa_version": "= input.fa_version", "paged": False, "causal": False}},
                      {"return": {"impl": "vllm_fa"}}], kind="kernel",
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}, "is_rocm_aiter": B(False), "fa_version": I(3)}},
                     response={"type": "object", "properties": {"impl": {"type": "string"}}}))
    a, b = fn(VIT, "triton_attn_wrapper")
    out.append(iface("vit-attn-wrappers", "triton-attn-wrapper",
                     "Custom op vllm::triton_attn_wrapper: encoder attention through context_attention_fwd (non-causal).",
                     [Cinv(VIT, "vllm::triton_attn_wrapper"), C(VIT, a, b)],
                     [{"title": "context_attention_fwd, is_causal=False", "source": C(VIT, ln(VIT, r"context_attention_fwd\(", a)),
                       "call": "triton-prefill-attention.context-attention-fwd", "input": {"shape": "= input.shape", "is_causal": False}},
                      {"return": {"impl": "triton"}}], kind="kernel",
                     request={"type": "object", "properties": {"shape": {"$ref": "AttnKernelShape"}}},
                     response={"type": "object", "properties": {"impl": {"type": "string"}}}))
    a, b = fn(VIT, "torch_sdpa_wrapper")
    out.append(iface("vit-attn-wrappers", "torch-sdpa-wrapper",
                     "Custom op vllm::torch_sdpa_wrapper: one SDPA call, or one per sequence when cu_seqlens splits the batch.",
                     [Cinv(VIT, "vllm::torch_sdpa_wrapper"), C(VIT, a, b)],
                     [{"if": "input.num_seqs == 0",
                       "then": [{"title": "No cu_seqlens: one SDPA over the batch", "source": C(VIT, ln(VIT, r"if cu_seqlens is None:", a)),
                                 "return": {"impl": "sdpa", "calls": 1}}]},
                      {"title": "Split by cu_seqlens and run SDPA per sequence", "source": C(VIT, ln(VIT, r"for q_i, k_i, v_i in zip", a)),
                       "foreach": "= input.seq_lens", "as": "seq", "steps": [{"set": {"vars.n": "= (has(vars.n) ? vars.n : 0) + 1"}}]},
                      {"return": {"impl": "sdpa", "calls": "= vars.n"}}], kind="kernel",
                     request={"type": "object", "properties": {"num_seqs": I(2), "seq_lens": {"type": "array", "items": {"type": "integer"}, "default": [256, 256]}}},
                     response={"type": "object", "properties": {"impl": {"type": "string"}, "calls": {"type": "integer"}}}))
    a, b = fn(VIT, "flashinfer_wrapper")
    out.append(iface("vit-attn-wrappers", "flashinfer-wrapper",
                     "Custom op vllm::flashinfer_wrapper: FlashInfer cuDNN batch prefill over the encoder sequence.",
                     [Cinv(VIT, "vllm::flashinfer_wrapper"), C(VIT, a, b)],
                     [{"if": "input.is_reshaped",
                       "then": [{"title": "Flatten (b, s) for cuDNN", "source": C(VIT, ln(VIT, r"if is_reshaped:", a)), "set": {"vars.flat": True}}],
                       "else": [{"set": {"vars.flat": False}}]},
                      {"title": "cudnn_batch_prefill_with_kv_cache", "source": C(VIT, ln(VIT, r"output, _ = cudnn_batch_prefill_with_kv_cache\(", a)),
                       "return": {"impl": "flashinfer_cudnn", "flattened": "= vars.flat"}}], kind="kernel",
                     request={"type": "object", "properties": {"is_reshaped": B(True)}},
                     response={"type": "object", "properties": {"impl": {"type": "string"}, "flattened": {"type": "boolean"}}}))
    for py, op, nm in [("vit_flash_attn_wrapper", "flash-attn-maxseqlen-wrapper", "vit-flash-attn-wrapper"),
                       ("vit_triton_attn_wrapper", "triton-attn-wrapper", "vit-triton-attn-wrapper"),
                       ("vit_torch_sdpa_wrapper", "torch-sdpa-wrapper", "vit-torch-sdpa-wrapper"),
                       ("vit_flashinfer_wrapper", "flashinfer-wrapper", "vit-flashinfer-wrapper")]:
        a, b = fn(VIT, py)
        out.append(iface("vit-attn-wrappers", nm, f"{py}: call torch.ops.vllm.{op.replace('-', '_')} (an opaque op for torch.compile).",
                         [C(VIT, a, b)],
                         [{"title": f"torch.ops.vllm.{op.replace('-', '_')}", "source": C(VIT, ln(VIT, r"return torch.ops.vllm\.", a)),
                           "call": f"vit-attn-wrappers.{op}", "input": "= input", "as": "r"},
                          {"return": "= vars.r.value"}],
                         request={"type": "object", "properties": VIT_REQ[nm]}))
    return out


def mla_prefill_interfaces():
    out = []
    a, b = fn(MLAP, "supports_quant_output")
    fa, fb = fn(MLAPFA, "supports_quant_output")
    out.append(iface("mla-prefill-backend", "supports-quant-output",
                     "MLAPrefillBackend.supports_quant_output: the base default opts every backend out; FlashAttnPrefillBackend overrides it.",
                     [C(MLAP, a, b)],
                     [{"if": "input.backend == 'FLASH_ATTN'",
                       "then": [{"title": "FlashAttnPrefillBackend overrides the gate", "source": C(MLAPFA, fa, fb),
                                 "call": "flash-attn-prefill-backend.supports-quant-output", "input": "= input", "as": "r"},
                                {"return": "= vars.r.value"}]},
                      {"title": "Base default: not supported", "source": C(MLAP, ln(MLAP, r"return False", a)), "return": {"supported": False}}],
                     request={"type": "object", "required": ["quant_key"], "properties": {
                         "backend": S("DUMMY"),
                         "quant_key": {"type": ["string", "null"], "enum": ["kFp8StaticTensorSym", "kFp8Dynamic128Sym", "kNvfp4Dynamic", None], "default": None},
                         "fa_version": {"type": ["integer", "null"], "default": 4}, "is_vllm_fa": B(True),
                         "device_capability_major": {"type": ["integer", "null"], "default": 10}}},
                     response={"type": "object", "properties": {"supported": {"type": "boolean"}}}))
    out.append(iface("flash-attn-prefill-backend", "supports-quant-output",
                     "FlashAttnPrefillBackend.supports_quant_output: fused FP8 output only on FA4 + vLLM-FA + SM100/SM110 with static per-tensor FP8.",
                     [C(MLAPFA, fa, fb)],
                     [{"if": "input.fa_version == 4 && input.is_vllm_fa && input.device_capability_major != null && (input.device_capability_major == 10 || input.device_capability_major == 11) && input.quant_key == 'kFp8StaticTensorSym'",
                       "then": [{"title": "FA4 fused FP8 output", "source": C(MLAPFA, ln(MLAPFA, r"self.vllm_flash_attn_version == 4", fa), ln(MLAPFA, r"and quant_key == kFp8StaticTensorSym", fa)), "return": {"supported": True}}]},
                      {"return": {"supported": False}}],
                     request={"type": "object", "properties": {"quant_key": {"type": ["string", "null"]}, "fa_version": {"type": ["integer", "null"]},
                                                               "is_vllm_fa": {"type": "boolean"}, "device_capability_major": {"type": ["integer", "null"]}}},
                     response={"type": "object", "properties": {"supported": {"type": "boolean"}}}))
    return out


def cpu_interfaces():
    out = []
    ua, ub = fn(CPUMLA, "do_kv_cache_update")
    beh = [
        {"if": "input.num_slots == 0",
         "then": [{"title": "Empty cache tensor: nothing to write", "source": C(CPUMLA, ln(CPUMLA, r"if kv_cache.numel\(\) == 0:", ua)), "return": {"written": 0}}]},
        {"title": "Only valid slots are written; padding slots (-1) set by the scheduler are skipped",
         "source": C(CPUMLA, ln(CPUMLA, r"valid_mask = slots >= 0", ua), ln(CPUMLA, r"k_pe_sq = k_pe_sq\[valid_mask\]", ua)),
         "set": {"vars.valid": "= input.slot_mapping.filter(s, s >= 0)"}},
        {"title": "flat[slots, :kv_lora_rank] = kv_c_normed; flat[slots, kv_lora_rank:] = k_pe",
         "source": C(CPUMLA, ln(CPUMLA, r"flat\[slots, :kv_lora_rank\] = ", ua), ln(CPUMLA, r"flat\[slots, kv_lora_rank:\] = ", ua)),
         "foreach": "= input.slot_mapping", "as": "slot", "index": "tok",
         "steps": [{"when": "vars.slot >= 0", "call": "cpu-mla-impl.write-latent-row",
                    "input": {"slot": "= vars.slot", "token": "= vars.tok", "kv_c_width": "= input.kv_lora_rank", "k_pe_width": "= input.pe_dim"}}]},
        {"return": {"written": "= size(vars.valid)"}},
    ]
    wa = ln(CPUMLA, r"flat\[slots, :kv_lora_rank\] = ", ua)
    out.append({"component": "cpu-mla-impl", "name": "write-latent-row", "kind": "function",
                "summary": "One row of the latent KV cache tensor (flat[slot] = kv_c_normed | k_pe), keyed by slot.",
                "sources": [C(CPUMLA, wa, wa + 1)],
                "request": {"type": "object", "required": ["slot", "token"], "properties": {"slot": {"type": "integer"}, "token": {"type": "integer"},
                                                                                          "kv_c_width": {"type": "integer"}, "k_pe_width": {"type": "integer"}}},
                "latency_ms": 0,
                "store": {"table": "latent_rows", "op": "put", "key": "= input.slot", "value": "= omit(input, 'slot')"}})
    out.append(iface("cpu-mla-impl", "do-kv-cache-update",
                     "CPUMLAImpl.do_kv_cache_update: write each token's latent KV (kv_c_normed | k_pe) into its slot row; negative slots are padding.",
                     [C(CPUMLA, ua, ub)], beh,
                     request={"type": "object", "required": ["slot_mapping"], "properties": {
                         "slot_mapping": {"type": "array", "items": {"type": "integer"}, "examples": [[0, 1, 2, 3, 4, 5, 6, -1]]},
                         "kv_lora_rank": I(512), "pe_dim": I(64), "num_slots": I(64)}},
                     response={"type": "object", "properties": {"written": {"type": "integer"}}}))
    fa, fb = fn(CPUMLA, "forward_mqa")
    beh = [
        {"if": "!input.has_decode",
         "then": [{"title": "forward_mqa needs decode metadata", "source": C(CPUMLA, ln(CPUMLA, r"assert attn_metadata.decode is not None", fa)),
                   "fail": {"code": "assertion-error", "message": "attn_metadata.decode is None"}}]},
        {"title": "Read the latent rows the block table addresses (block_size slots per block, up to seq_len)",
         "source": C(CPUMLA, ln(CPUMLA, r"block_table = attn_metadata.decode.block_table.to\(torch.int32\)", fa), ln(CPUMLA, r"seq_lens = attn_metadata.decode.seq_lens.to\(torch.int32\)", fa)),
         "set": {"vars.slots": "= input.block_table.map(b, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15].map(o, b * 16 + o)).flatten().slice(0, input.seq_len)"}},
        {"set": {"vars.read": "= vars.slots.filter(s, string(s) in state.latent_rows)",
                 "vars.missing": "= vars.slots.filter(s, !(string(s) in state.latent_rows))"}},
        {"title": "mla_decode_kvcache_cpu over (q, kv cache, block_table, seq_lens)", "source": C(CPUMLA, ln(CPUMLA, r"ops.mla_decode_kvcache_cpu\(", fa)),
         "call": "custom-ops.mla-decode-kvcache-cpu", "input": {"num_seqs": 1, "seq_len": "= input.seq_len", "num_heads": 16, "num_kv_heads": 1, "head_dim": 576, "dtype_bytes": 4}},
        {"return": {"rows_read": "= size(vars.read)", "rows_unwritten": "= size(vars.missing)", "lse": None}},
    ]
    out.append(iface("cpu-mla-impl", "forward-mqa",
                     "CPUMLAImpl.forward_mqa: CPU decode over the latent cache rows addressed by the block table (LSE is not returned: DCP is off).",
                     [C(CPUMLA, fa, fb)], beh,
                     request={"type": "object", "properties": {"has_decode": B(True),
                                                               "block_table": {"type": "array", "items": {"type": "integer"}, "examples": [[0]]},
                                                               "seq_len": {"type": "integer", "examples": [7]}}},
                     response={"type": "object", "properties": {"rows_read": {"type": "integer"}, "rows_unwritten": {"type": "integer"}}},
                     errors=[err("assertion-error", "no decode metadata")]))
    # cpu_attn ISA
    ra, rb = fn(CPUA, "_riscv_supports_rvv")
    ga, gb = fn(CPUA, "_get_attn_isa")
    mark(CPUA, "_riscv_supports_rvv")
    out.append(iface("cpu-attn", "riscv-supports-rvv",
                     "_riscv_supports_rvv: trust the C++ build (torch.ops._C.cpu_attn_has_isa('rvv')), else look for zvl128b/zvl256b in /proc/cpuinfo.",
                     [C(CPUA, ra, rb)],
                     [{"if": "input.compiled_rvv",
                       "then": [{"title": "torch.ops._C.cpu_attn_has_isa('rvv')", "source": C(CPUA, ln(CPUA, r"if torch.ops._C.cpu_attn_has_isa\(\"rvv\"\):", ra)), "return": {"rvv": True}}]},
                      {"if": "!has(input.cpuinfo) || input.cpuinfo == null",
                       "then": [{"title": "No /proc/cpuinfo", "source": C(CPUA, ln(CPUA, r"except OSError:", ra)), "return": {"rvv": False}}]},
                      {"title": "zvl128b or zvl256b advertised", "source": C(CPUA, ln(CPUA, r"return any\(f\"zvl\{n\}b\" in cpuinfo", ra)),
                       "return": {"rvv": "= input.cpuinfo.contains('zvl128b') || input.cpuinfo.contains('zvl256b')"}}],
                     request={"type": "object", "properties": {"compiled_rvv": B(False), "cpuinfo": {"type": ["string", "null"], "default": None}}},
                     response={"type": "object", "properties": {"rvv": {"type": "boolean"}}}))
    out.append(iface("cpu-attn", "get-attn-isa",
                     "_get_attn_isa: choose the CPU attention kernel ISA (amx, neon, rvv, vxe, vsx, vec, vec16).",
                     [C(CPUA, ga, gb)],
                     [{"if": "input.fp8_kv && !input.amx && !input.avx512",
                       "then": [{"title": "FP8 KV on CPU needs AVX-512 or AMX", "source": C(CPUA, ln(CPUA, r"FP8 KV cache on CPU requires", ga)),
                                 "fail": {"code": "not-implemented-error", "message": "FP8 KV cache on CPU requires x86 with AVX-512 or AMX."}}]},
                      {"if": "input.amx && input.dtype == 'bfloat16' && input.block_size % 32 == 0", "then": [{"title": "AMX", "source": C(CPUA, ln(CPUA, r"return \"amx\"", ga)), "return": {"isa": "amx"}}]},
                      {"if": "input.arch == 'arm'", "then": [{"return": {"isa": "neon"}}]},
                      {"if": "input.block_size % 32 == 0",
                       "then": [{"if": "input.arch == 'riscv'",
                                 "then": [{"title": "RISC-V: check RVV support", "source": C(CPUA, ln(CPUA, r"if supports_riscv and _riscv_supports_rvv\(\):", ga)),
                                           "call": "cpu-attn.riscv-supports-rvv", "input": {"compiled_rvv": False, "cpuinfo": "= has(input.cpuinfo) ? input.cpuinfo : null"}, "as": "rvv"},
                                          {"if": "vars.rvv.value.rvv", "then": [{"return": {"isa": "rvv"}}]}]},
                                {"return": {"isa": "= input.arch == 's390x' ? 'vxe' : (input.arch == 'powerpc' ? 'vsx' : 'vec')"}}]},
                      {"return": {"isa": "vec16"}}],
                     request={"type": "object", "properties": {"fp8_kv": B(False), "amx": B(False), "avx512": B(True), "dtype": S("bfloat16"),
                                                               "block_size": I(32), "arch": S("x86"), "cpuinfo": {"type": ["string", "null"], "default": None}}},
                     response={"type": "object", "properties": {"isa": {"type": "string"}}},
                     errors=[err("not-implemented-error", "FP8 KV without AVX-512/AMX")]))
    return out

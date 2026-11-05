"""Round-6 additions (mechanism coverage): chunked local attention (make_local_attention_virtual_batches, the
ChunkedLocalAttention layer and the builder subclass it creates around the selected backend), and the oracle4
regression for it."""
from core import B, I, S, comp, err, iface
from lib import C, Cfn, cls, fn, ln
from round4 import A, ARR_I, ARR_II, FX, obj, step
from round4 import m as m_

UT = "vllm/v1/attention/backends/utils.py"
CLA = "vllm/model_executor/layers/attention/chunked_local_attention.py"
EOA = "vllm/model_executor/layers/attention/encoder_only_attention.py"
XA = "vllm/model_executor/layers/attention/cross_attention.py"
BK = "vllm/v1/attention/backend.py"
FA = "vllm/v1/attention/backends/flash_attn.py"

W = ["full-tp1-llama-8b"]

# The modeled backends' metadata builder classes (get_builder_cls), by backend class name.
BUILDERS = {"FlashAttentionBackend": "FlashAttentionMetadataBuilder", "TritonAttentionBackend": "TritonAttentionMetadataBuilder",
            "FlashInferBackend": "FlashInferMetadataBuilder", "FlexAttentionBackend": "FlexAttentionMetadataBuilder"}


def components():
    a, b = cls(CLA, "ChunkedLocalAttention")
    return [
        comp("chunked-local-attention", "ChunkedLocalAttention", CLA,
             "ChunkedLocalAttention (Llama 4's RoPE layers with attention_chunk_size): an Attention layer whose backend is the selected backend "
             "subclassed with ChunkedLocalAttentionBuilder; its KV cache spec is ChunkedLocalAttentionSpec. Its file is under "
             "model_executor/layers (models-layers' path); oracle4 assigns the builder and the virtual batches to attention.",
             a=a, b=b),
        comp("chunked-local-attention-builder", "ChunkedLocalAttentionBuilder", CLA,
             "create_chunked_local_attention_backend's builder subclass: splits each request into chunk-local virtual batches before the "
             "underlying builder's build, maps every later block table the same way, and never supports CUDA graphs.",
             a=fn(CLA, "create_chunked_local_attention_backend")[0], b=fn(CLA, "create_chunked_local_attention_backend")[1]),
        comp("encoder-only-attention", "EncoderOnlyAttention", EOA,
             "EncoderOnlyAttention (BERT, ModernBERT, BERT with RoPE: the pooling models' bidirectional layers): selects a backend for ENCODER_ONLY, "
             "wraps its builder so every build is non-causal, and keeps no KV cache (get_kv_cache_spec is None). Under model_executor/layers (models-layers' path).",
             a=cls(EOA, "EncoderOnlyAttention")[0], b=cls(EOA, "EncoderOnlyAttention")[1]),
        comp("encoder-only-attention-builder", "EncoderOnlyAttentionBuilder", EOA,
             "create_encoder_only_attention_backend's builder subclass: a shallow copy of the common metadata with causal = False, then the underlying build.",
             a=fn(EOA, "create_encoder_only_attention_backend")[0], b=fn(EOA, "create_encoder_only_attention_backend")[1]),
        comp("cross-attention", "CrossAttention", XA,
             "CrossAttention (encoder-decoder models such as Whisper): decoder queries over the encoder's K/V, selected for ENCODER_DECODER, cached under "
             "CrossAttentionSpec. Under model_executor/layers (models-layers' path).",
             a=cls(XA, "CrossAttention")[0], b=cls(XA, "CrossAttention")[1]),
        comp("cross-attention-builder", "CrossAttentionBuilder and CrossAttentionImpl", XA,
             "create_cross_attention_backend's builder and impl subclasses: non-causal metadata over the encoder lengths with its own slot mapping "
             "(only for requests whose encoder K/V isn't cached yet), and a forward that writes K/V through that slot mapping first.",
             a=fn(XA, "create_cross_attention_backend")[0], b=fn(XA, "create_cross_attention_backend")[1]),
    ]


def _vb_behavior():
    a, b = fn(UT, "make_local_attention_virtual_batches")
    L = lambda pat: ln(UT, pat, a)
    s = "vars.s"
    q = "vars.q"
    Cc = "input.attn_chunk_size"
    beh = [
        {"title": "Query lengths from query_start_loc_cpu (the model's CommonAttentionMetadata may carry them as query_lens), seq_lens copied to the host, the block table",
         "source": C(UT, L(r"query_start_loc_np = common_attn_metadata\.query_start_loc_cpu"), L(r"actual_batch_size = seq_lens_np\.shape\[0\]")),
         "set": {"vars.qsl": "= has(input.common.query_start_loc_cpu) && size(input.common.query_start_loc_cpu) > 0 ? input.common.query_start_loc_cpu : [0] + lists.range(size(input.common.query_lens)).map(i, sum(input.common.query_lens.slice(0, i + 1)))",
                 "vars.s": "= input.common.seq_lens", "vars.bt": "= input.common.block_table"}},
        {"set": {"vars.n": "= size(vars.s)", "vars.q": "= lists.range(size(vars.s)).map(i, vars.qsl[i + 1] - vars.qsl[i])"}},
        {"title": "Query tokens that fall in each request's first (possibly partial) chunk; tokens in its last chunk (attn_chunk_size + seq_len % -attn_chunk_size, so a full chunk when the length divides); local blocks = 1 + cdiv(rest, chunk)",
         "source": C(UT, L(r"q_tokens_in_first_block = np\.minimum\("), L(r"local_blocks = 1 \+ cdiv\(")),
         "set": {"vars.qf": f"= lists.range(vars.n).map(i, math.least({Cc} - (({s}[i] - {q}[i]) % {Cc}), {q}[i]))",
                 "vars.tl": f"= lists.range(vars.n).map(i, {s}[i] % {Cc} == 0 ? {Cc} : {s}[i] % {Cc})"}},
        {"set": {"vars.lb": f"= lists.range(vars.n).map(i, 1 + ({q}[i] - vars.qf[i] + {Cc} - 1) / {Cc})"}},
        {"title": "One virtual batch per (request, local block), in batch order (the batched arange and its reverse)",
         "source": C(UT, L(r"cu_num_blocks = np\.cumsum\(local_blocks\)"), L(r"rarange = np\.repeat\(local_blocks, local_blocks\) - arange - 1")),
         "set": {"vars.vb": "= lists.range(vars.n).map(i, lists.range(vars.lb[i]).map(j, [i, j])).flatten()"}},
        {"title": "Virtual query lengths: the first block takes the first-chunk tokens, each later block min(remaining - chunk * (k - 1), chunk); cumulated into query_start_loc",
         "source": C(UT, L(r"seqlens_q_local = np\.repeat\(q_seqlens - q_tokens_in_first_block"), L(r"cu_seqlens_q_local\[0\] = 0")),
         "set": {"vars.ql": f"= vars.vb.map(p, p[1] == 0 ? vars.qf[p[0]] : math.least({q}[p[0]] - vars.qf[p[0]] - {Cc} * (p[1] - 1), {Cc}))"}},
        {"title": "Virtual key lengths: a full chunk for every block but each request's last, which keeps tokens_in_last_block; each block's absolute key start",
         "source": C(UT, L(r"seqlens_k_local = np\.full\("), L(r"rarange \* attn_chunk_size \+ np\.repeat\(tokens_in_last_block") + 1),
         "set": {"vars.kl": f"= vars.vb.map(p, p[1] == vars.lb[p[0]] - 1 ? vars.tl[p[0]] : {Cc})",
                 "vars.ks": f"= vars.vb.map(p, {s}[p[0]] - ((vars.lb[p[0]] - p[1] - 1) * {Cc} + vars.tl[p[0]]))"}},
        {"if": "input.block_size == 0",
         "then": [{"title": "block_size defaults to 0: numpy's floor division by zero only warns, then the chunk-size check divides the Python ints by zero",
                   "source": C(UT, L(r"block_starts = k_seqstarts_absolute // block_size"), L(r"assert attn_chunk_size % block_size == 0")),
                   "fail": {"code": "zero-division-error", "message": "integer modulo by zero"}}]},
        {"if": f"{Cc} % input.block_size != 0",
         "then": [{"title": "The chunk must be a whole number of KV blocks",
                   "source": C(UT, L(r"assert attn_chunk_size % block_size == 0"), L(r"f\"attn_chunk_size \{attn_chunk_size\} is not divisible by block_size")),
                   "fail": {"code": "assertion-error", "message": f"= 'attn_chunk_size ' + string({Cc}) + ' is not divisible by block_size ' + string(input.block_size)"}}]},
        {"title": "pages_per_local_batch = chunk // block_size pages per virtual batch, from the block holding its first key; indices clipped to the block table's last column",
         "source": C(UT, L(r"pages_per_local_batch = attn_chunk_size // block_size"), L(r"block_indices = block_indices\.reshape\(-1\)\.clip")),
         "set": {"vars.pp": f"= {Cc} / input.block_size", "vars.ncols": "= size(vars.bt) > 0 ? size(vars.bt[0]) : 0"}},
        {"set": {"vars.bi": "= lists.range(size(vars.vb)).map(v, lists.range(vars.pp).map(k, math.least(vars.ks[v] / input.block_size + k, vars.ncols - 1))).flatten()",
                 "vars.bj": "= lists.range(size(vars.vb)).map(v, lists.range(vars.pp).map(k, vars.vb[v][0])).flatten()"}},
        {"title": "make_block_table gathers block_table[batch_indices, block_indices] viewed as (virtual_batches, pages); it is kept for update_block_table",
         "source": C(UT, L(r"batch_indices = np\.repeat\("), L(r"block_table_local = make_block_table\(block_table\)")),
         "set": {"vars.btl": "= lists.range(size(vars.vb)).map(v, lists.range(vars.pp).map(k, vars.bt[vars.bj[v * vars.pp + k]][vars.bi[v * vars.pp + k]]))"}},
        {"title": "The new CommonAttentionMetadata: one request per virtual batch, the same tokens and slot mapping, causal, seq_lens_cpu_upper_bound = the virtual key lengths",
         "source": C(UT, L(r"query_start_loc_cpu = torch\.from_numpy\(cu_seqlens_q_local\)"), b),
         "return": {"common": {"query_start_loc_cpu": "= [0] + lists.range(size(vars.ql)).map(i, sum(vars.ql.slice(0, i + 1)))",
                               "query_lens": "= vars.ql", "seq_lens": "= vars.kl", "seq_lens_cpu_upper_bound": "= vars.kl",
                               "has_cpu_seq_lens_upper_bound": True,
                               "num_reqs": "= size(vars.kl)",
                               "num_actual_tokens": "= has(input.common.num_actual_tokens) && input.common.num_actual_tokens != null ? input.common.num_actual_tokens : sum(vars.q)",
                               "max_query_len": "= math.greatest(vars.ql)", "max_seq_len": "= math.greatest(vars.kl)",
                               "block_table": "= vars.btl",
                               "slot_mapping": "= has(input.common.slot_mapping) ? input.common.slot_mapping : []", "causal": True},
                    "make_block_table": {"virtual_batches": "= size(vars.vb)", "pages_per_local_batch": "= vars.pp",
                                         "batch_indices": "= vars.bj", "block_indices": "= vars.bi"}}},
    ]
    return a, b, beh


COMMON_IN = obj({"query_start_loc_cpu": A([]), "query_lens": A([]), "seq_lens": ARR_I, "block_table": ARR_II,
                 "num_actual_tokens": {"type": ["integer", "null"], "default": None}, "slot_mapping": A([])},
                required=["seq_lens", "block_table"],
                description="CommonAttentionMetadata: query_start_loc_cpu (or query_lens, as the model's runner passes it), seq_lens, block_table_tensor rows, num_actual_tokens, slot_mapping")
VB_OUT = obj({"common": {"type": "object"},
              "make_block_table": obj({"virtual_batches": {"type": "integer"}, "pages_per_local_batch": {"type": "integer"},
                                       "batch_indices": ARR_I, "block_indices": ARR_I})})


def interfaces():
    out = []
    a, b, beh = _vb_behavior()
    out.append(iface("attention-backend-utils", "make-local-attention-virtual-batches",
                     "make_local_attention_virtual_batches: split each request into chunk-local virtual batches (query and key lengths at most "
                     "attn_chunk_size, total query tokens kept) and build their local block table of attn_chunk_size // block_size pages each; "
                     "returns the new CommonAttentionMetadata and the gather (make_block_table) that update_block_table reuses.",
                     [C(UT, a, b)], beh,
                     request=obj({"attn_chunk_size": I(8192), "block_size": I(0), "common": COMMON_IN}, required=["attn_chunk_size", "common"]),
                     response=VB_OUT,
                     errors=[err("assertion-error", "attn_chunk_size is not divisible by block_size"),
                             err("zero-division-error", "block_size left at its default 0")]))

    # create_chunked_local_attention_backend
    ca, cb = fn(CLA, "create_chunked_local_attention_backend")
    sa, sb = fn(BK, "subclass_attention_backend")
    bmap = str(BUILDERS).replace('"', "'")
    out.append(iface("chunked-local-attention-builder", "create-backend",
                     "create_chunked_local_attention_backend (lru_cache per underlying class and chunk size): subclass the backend as "
                     "ChunkedLocalAttention_<chunk>_<Backend> whose get_builder_cls returns ChunkedLocalAttentionBuilder, a subclass of the backend's own builder.",
                     [C(CLA, ca, cb), C(BK, sa, sb)],
                     [{"title": "The class name prefix carries the chunk size", "source": C(CLA, ln(CLA, r"prefix = f\"ChunkedLocalAttention_", ca)),
                       "set": {"vars.cls": "= input.underlying_backend_cls_path.split('.')[size(input.underlying_backend_cls_path.split('.')) - 1]"}},
                      {"if": f"!(vars.cls in {bmap})",
                       "then": [{"title": "Another backend's builder: its class name is not tabulated in the model", "source": C(CLA, ln(CLA, r"underlying_builder = underlying_attn_backend\.get_builder_cls\(\)", ca)),
                                 "set": {"vars.ub": "= vars.cls.replace('Backend', 'MetadataBuilder')"}}],
                       "else": [{"title": "underlying_attn_backend.get_builder_cls()", "source": C(CLA, ln(CLA, r"underlying_builder = underlying_attn_backend\.get_builder_cls\(\)", ca)),
                                 "set": {"vars.ub": f"= {bmap}[vars.cls]"}}]},
                      {"title": "subclass_attention_backend: type(prefix + backend name, (backend,), {'get_builder_cls': lambda: ChunkedLocalAttentionBuilder})",
                       "source": C(CLA, ln(CLA, r"attn_backend = subclass_attention_backend\(", ca), cb),
                       "return": {"name": "= 'ChunkedLocalAttention_' + string(input.attention_chunk_size) + '_' + vars.cls",
                                  "base": "= vars.cls", "builder_cls": "ChunkedLocalAttentionBuilder", "builder_base": "= vars.ub",
                                  "attention_chunk_size": "= input.attention_chunk_size", "cudagraph_support": "NEVER"}}],
                     request=obj({"underlying_backend_cls_path": S("vllm.v1.attention.backends.flash_attn.FlashAttentionBackend"), "attention_chunk_size": I(8192)}),
                     response=obj({"name": {"type": "string"}, "base": {"type": "string"}, "builder_cls": {"type": "string"}, "builder_base": {"type": "string"},
                                   "attention_chunk_size": {"type": "integer"}, "cudagraph_support": {"type": "string"}})))

    # ChunkedLocalAttention.__init__
    ia, ib = fn(CLA, "__init__", cls(CLA, "ChunkedLocalAttention")[0])
    out.append(iface("chunked-local-attention", "init",
                     "ChunkedLocalAttention.__init__: select the underlying backend from the head size, the default dtype and the cache dtype alone "
                     "(no sliding window, sink or MLA flags), wrap it with create_chunked_local_attention_backend, then initialize the Attention layer with that backend.",
                     [C(CLA, ia, ib)],
                     [{"title": "kv_cache_dtype is the cache config's cache_dtype, or auto without one; dtype is torch.get_default_dtype()",
                       "source": C(CLA, ln(CLA, r"self\.attention_chunk_size = attention_chunk_size", ia), ln(CLA, r"kv_cache_dtype = \"auto\"", ia)),
                       "set": {"vars.kv": "= input.has_cache_config ? config['kv-cache-dtype'] : 'auto'"}},
                      {"title": "get_attn_backend(head_size, dtype, kv_cache_dtype): every other selector argument at its default",
                       "source": C(CLA, ln(CLA, r"underlying_attn_backend = get_attn_backend\(head_size, dtype, kv_cache_dtype\)", ia)),
                       "call": "selector.get-attn-backend",
                       "input": {"head_size": "= input.head_size", "dtype": "= input.dtype", "kv_cache_dtype": "= vars.kv", "num_heads": "= input.num_heads"}, "as": "sel"},
                      {"title": "create_chunked_local_attention_backend(underlying, attention_chunk_size)",
                       "source": C(CLA, ln(CLA, r"attn_backend = create_chunked_local_attention_backend\(", ia), ln(CLA, r"underlying_attn_backend, attention_chunk_size", ia)),
                       "call": "chunked-local-attention-builder.create-backend",
                       "input": {"underlying_backend_cls_path": "= vars.sel.value.backend_cls_path", "attention_chunk_size": "= input.attention_chunk_size"}, "as": "be"},
                      {"title": "Attention.__init__ with attn_backend set, so the layer does not select again; its KV spec is ChunkedLocalAttentionSpec(attention_chunk_size)",
                       "source": C(CLA, ln(CLA, r"super\(\).__init__\(", ia), fn(CLA, "get_kv_cache_spec")[1]),
                       "return": {"backend": "= vars.be.value.name", "underlying_backend_cls_path": "= vars.sel.value.backend_cls_path",
                                  "kv_cache_dtype": "= vars.kv", "kv_cache_spec": "ChunkedLocalAttentionSpec", "attention_chunk_size": "= input.attention_chunk_size"}}],
                     request=obj({"num_heads": I(40), "head_size": I(128), "attention_chunk_size": I(8192), "dtype": S("bfloat16"), "has_cache_config": B(True)}),
                     response=obj({"backend": {"type": "string"}, "underlying_backend_cls_path": {"type": "string"}, "kv_cache_dtype": {"type": "string"},
                                   "kv_cache_spec": {"type": "string"}, "attention_chunk_size": {"type": "integer"}})))

    # ChunkedLocalAttentionBuilder.build / update_block_table / get_cudagraph_support
    ba = ln(CLA, r"def build\(")
    bb = ln(CLA, r"return metadata", ba)
    out.append(iface("chunked-local-attention-builder", "build",
                     "ChunkedLocalAttentionBuilder.build: make the virtual batches with the KV spec's block size, run the underlying builder's build on them, "
                     "and keep the block-table gather on the metadata.",
                     [C(CLA, ba, bb)],
                     [{"title": "make_local_attention_virtual_batches(attention_chunk_size, common_attn_metadata, kv_cache_spec.block_size)",
                       "source": C(CLA, ln(CLA, r"cm, make_virtual_batches_block_table = make_local_attention_virtual_batches\(", ba), ln(CLA, r"self\.kv_cache_spec\.block_size,", ba)),
                       "call": "attention-backend-utils.make-local-attention-virtual-batches",
                       "input": {"attn_chunk_size": "= input.attention_chunk_size", "block_size": "= input.block_size", "common": "= input.common"}, "as": "vb"},
                      {"if": "input.underlying_builder != 'FlashAttentionMetadataBuilder'",
                       "then": [{"title": "super().build on another builder: the model only simulates FlashAttention's build",
                                 "source": C(CLA, ln(CLA, r"metadata = super\(\)\.build\(common_prefix_len, cm, fast_build\)", ba)),
                                 "return": {"metadata": "= {'num_reqs': vars.vb.value.common.num_reqs, 'num_actual_tokens': vars.vb.value.common.num_actual_tokens, 'max_query_len': vars.vb.value.common.max_query_len, 'max_seq_len': vars.vb.value.common.max_seq_len, 'seq_lens': vars.vb.value.common.seq_lens, 'block_table': vars.vb.value.common.block_table, 'slot_mapping': vars.vb.value.common.slot_mapping, 'causal': true}",
                                            "virtual": "= vars.vb.value.common", "make_virtual_batches_block_table": "= vars.vb.value.make_block_table"}}]},
                      {"title": "super().build(common_prefix_len, cm, fast_build): FlashAttention's builder on the virtual batches",
                       "source": C(CLA, ln(CLA, r"metadata = super\(\)\.build\(common_prefix_len, cm, fast_build\)", ba)),
                       "call": "flash-attention-metadata-builder.build",
                       "input": {"common": "= merge(vars.vb.value.common, {'common_prefix_len': input.common_prefix_len})", "fast_build": "= input.fast_build"}, "as": "md"},
                      {"title": "metadata.make_virtual_batches_block_table = the gather", "source": C(CLA, ln(CLA, r"metadata\.make_virtual_batches_block_table = ", ba), bb),
                       "return": {"metadata": "= vars.md.value", "virtual": "= vars.vb.value.common", "make_virtual_batches_block_table": "= vars.vb.value.make_block_table"}}],
                     request=obj({"attention_chunk_size": I(8192), "block_size": I(16), "common": COMMON_IN, "common_prefix_len": I(0), "fast_build": B(False),
                                  "underlying_builder": S("FlashAttentionMetadataBuilder")}, required=["common"]),
                     response=obj({"metadata": {"type": "object"}, "virtual": {"type": "object"}, "make_virtual_batches_block_table": {"type": "object"}}),
                     errors=[err("assertion-error", "attn_chunk_size is not divisible by block_size")]))
    ua = ln(CLA, r"def update_block_table\(")
    ub = ln(CLA, r"return super\(\)\.update_block_table\(metadata, blk_table, slot_mapping\)", ua)
    out.append(iface("chunked-local-attention-builder", "update-block-table",
                     "ChunkedLocalAttentionBuilder.update_block_table: map another KV group's block table through the saved gather, then the underlying "
                     "builder's update_block_table (FlashAttention: a copy of the metadata with the new table and slot mapping).",
                     [C(CLA, ua, ub), C(FA, *fn(FA, "update_block_table"))],
                     [{"title": "blk_table = metadata.make_virtual_batches_block_table(blk_table)", "source": C(CLA, ln(CLA, r"blk_table = metadata\.make_virtual_batches_block_table\(blk_table\)", ua)),
                       "set": {"vars.g": "= input.make_virtual_batches_block_table"}},
                      {"title": "FlashAttentionMetadataBuilder.update_block_table: copy.copy(metadata) with the new block table and slot mapping",
                       "source": C(FA, *fn(FA, "update_block_table")),
                       "return": {"block_table": "= lists.range(vars.g.virtual_batches).map(v, lists.range(vars.g.pages_per_local_batch).map(k, input.block_table[vars.g.batch_indices[v * vars.g.pages_per_local_batch + k]][vars.g.block_indices[v * vars.g.pages_per_local_batch + k]]))",
                                  "slot_mapping": "= input.slot_mapping"}}],
                     request=obj({"make_virtual_batches_block_table": VB_OUT["properties"]["make_block_table"], "block_table": ARR_II, "slot_mapping": ARR_I},
                                 required=["make_virtual_batches_block_table", "block_table"]),
                     response=obj({"block_table": ARR_II, "slot_mapping": ARR_I})))
    ga = ln(CLA, r"def get_cudagraph_support\(")
    out.append(iface("chunked-local-attention-builder", "get-cudagraph-support",
                     "ChunkedLocalAttentionBuilder.get_cudagraph_support: always NEVER, overriding whatever the underlying builder reports.",
                     [C(CLA, ga, ln(CLA, r"return AttentionCGSupport\.NEVER", ga))],
                     [{"title": "Explicit override: chunked local attention never runs under CUDA graphs", "source": C(CLA, ln(CLA, r"return AttentionCGSupport\.NEVER", ga)),
                       "return": {"support": "NEVER", "level": 0}}],
                     request=obj({"underlying_builder": S("FlashAttentionMetadataBuilder")}),
                     response=obj({"support": {"type": "string"}, "level": {"type": "integer"}})))
    out += encoder_only_interfaces() + cross_interfaces() + block_size_interfaces() + mamba_interfaces() + [triton_impl_init()]
    return out


TR = "vllm/v1/attention/backends/triton_attn.py"


def triton_impl_init():
    ia, ib = m_(TR, "TritonAttentionImpl", "__init__")
    L = lambda pat: ln(TR, pat, ia)
    cap = "(string(input.device_capability_major) + '.' + string(input.device_capability_minor))"
    capi = "(input.device_capability_major * 10 + input.device_capability_minor)"
    beh = [
        {"title": "Sliding window as (left, right): encoder and encoder-only layers see both sides (W - 1 each), decoders only the past; none is (-1, -1)",
         "source": C(TR, L(r"if sliding_window is None:"), L(r"self\.sliding_window = \(sliding_window - 1, 0\)")),
         "set": {"vars.sw": "= input.sliding_window == null ? [-1, -1] : (input.attn_type in ['encoder', 'encoder_only'] ? [input.sliding_window - 1, input.sliding_window - 1] : [input.sliding_window - 1, 0])"}},
        {"if": f"input.platform == 'cuda' && input.kv_cache_dtype.startsWith('fp8') && {capi} < 89",
         "then": [{"title": "CUDA: an FP8 KV cache needs native fp8e4nv (SM89+); the suggestion is float16 below SM80, else bfloat16",
                   "source": C(TR, L(r'if self\.kv_cache_dtype\.startswith\("fp8"\) and not \('), L(r'f"requires SM89\+\. Re-run with --kv-cache-dtype \{suggested\}\."') + 1),
                   "fail": {"code": "value-error", "message": f"= 'FP8 KV cache is not supported by the Triton attention backend on ' + input.device_name + ' (compute capability ' + {cap} + '); native FP8 (fp8e4nv) requires SM89+. Re-run with --kv-cache-dtype ' + ({capi} < 80 ? 'float16' : 'bfloat16') + '.'"}}]},
        {"if": f"input.platform == 'cuda' && input.kv_cache_dtype == 'bfloat16' && {capi} < 80",
         "then": [{"title": "CUDA: a bfloat16 KV cache needs SM80+",
                   "source": C(TR, L(r'if self\.kv_cache_dtype == "bfloat16" and not \('), L(r'f"--kv-cache-dtype float16\."') + 1),
                   "fail": {"code": "value-error", "message": f"= 'bfloat16 KV cache is not supported on ' + input.device_name + ' (compute capability ' + {cap} + '); bfloat16 requires SM80+. Re-run with --kv-cache-dtype float16.'"}}]},
        {"if": "input.sinks_heads != null && input.sinks_heads != input.num_heads",
         "then": [{"title": "Sinks need one value per head",
                   "source": C(TR, L(r"assert sinks\.shape\[0\] == num_heads, \("), L(r'f"num_heads: \{num_heads\}\."')),
                   "fail": {"code": "assertion-error", "message": "= 'Sinks must have the same number of heads as the number of heads in the layer. Sinks shape: torch.Size([' + string(input.sinks_heads) + ']), num_heads: ' + string(input.num_heads) + '.'"}}]},
        {"title": "Soft cap None is 0 (none); queries per KV head; the KV quant mode of the cache dtype",
         "source": C(TR, L(r"if logits_soft_cap is None:"), L(r"self\._is_per_token_head_quant = ")),
         "call": "kv-quant-mode.get-kv-quant-mode", "input": {"kv_cache_dtype": "= input.kv_cache_dtype"}, "as": "qm"},
        {"return": {"sliding_window": "= vars.sw", "logits_soft_cap": "= input.logits_soft_cap == null ? 0.0 : input.logits_soft_cap",
                    "num_queries_per_kv": "= input.num_heads / input.num_kv_heads", "kv_quant_mode": "= vars.qm.value.kv_quant_mode",
                    "supports_quant_query_input": "= input.platform == 'cuda'"}},
    ]
    return iface("triton-attention-impl", "init",
                 "TritonAttentionImpl.__init__: the sliding-window tuple (bidirectional for encoder and encoder-only layers), the CUDA capability checks for FP8 and "
                 "bfloat16 KV caches with their exact messages, the sinks shape check, and the KV quant mode.",
                 [C(TR, ia, ib)], beh,
                 request=obj({"num_heads": I(32), "num_kv_heads": I(8), "head_size": I(128), "sliding_window": {"type": ["integer", "null"], "default": None},
                              "attn_type": S("decoder"), "kv_cache_dtype": S("auto"), "logits_soft_cap": {"type": ["number", "null"], "default": None},
                              "sinks_heads": {"type": ["integer", "null"], "default": None}, "platform": S("cuda"),
                              "device_capability_major": I(9), "device_capability_minor": I(0), "device_name": S("NVIDIA H100 80GB HBM3")}),
                 response=obj({"sliding_window": ARR_I, "logits_soft_cap": {"type": "number"}, "num_queries_per_kv": {"type": "integer"},
                               "kv_quant_mode": {"type": "string"}, "supports_quant_query_input": {"type": "boolean"}}),
                 errors=[err("value-error", "FP8 KV below SM89 or bfloat16 KV below SM80 on CUDA"), err("assertion-error", "sinks shape")])


SEL = "vllm/v1/attention/selector.py"


def mamba_interfaces():
    out = []
    ga, gb = fn(SEL, "get_mamba_attn_backend")
    ca, cb = fn(SEL, "_cached_get_mamba_attn_backend")
    out.append(iface("selector", "get-mamba-attn-backend",
                     "get_mamba_attn_backend(mamba_type): the mamba-family layer's backend class (Mamba1/2, short conv, linear, GDN) from MambaAttentionBackendEnum "
                     "(override-aware), refused under VLLM_BATCH_INVARIANT since no mamba backend supports batch invariance (functools.cache per type).",
                     [C(SEL, ga, gb), C(SEL, ca, cb)],
                     [{"title": "mamba_type is a MambaAttentionBackendEnum member (the layer passes one; the bare assert can't fail here)",
                       "source": C(SEL, ln(SEL, r"assert mamba_type and isinstance\(mamba_type, MambaAttentionBackendEnum\)", ca))},
                      {"title": "mamba_type.get_class(): the registered override, else the enum's class path", "source": C(SEL, ln(SEL, r"mamba_attn_backend = mamba_type\.get_class\(\)", ca)),
                       "call": "mamba-attention-backend-enum.get-class", "input": {"name": "= input.mamba_type"}, "as": "c"},
                      {"if": "config['vllm-batch-invariant']",
                       "then": [{"title": "Batch-invariant mode needs supports_batch_invariance(), which no mamba backend overrides (AttentionBackend's default is False)",
                                 "source": C(SEL, ln(SEL, r"if envs\.VLLM_BATCH_INVARIANT and not mamba_attn_backend\.supports_batch_invariance\(\):", ca), ln(SEL, r'f"\{mamba_attn_backend\.get_name\(\)\}\."', ca) + 1),
                                 "fail": {"code": "runtime-error", "message": "= 'VLLM batch_invariant mode is not supported for ' + vars.c.value.class_name + '.'"}}]},
                      {"return": {"backend_cls_path": "= vars.c.value.path", "name": "= vars.c.value.class_name"}}],
                     request=obj({"mamba_type": S("MAMBA2")}),
                     response=obj({"backend_cls_path": {"type": "string"}, "name": {"type": ["string", "null"]}}),
                     errors=[err("runtime-error", "VLLM_BATCH_INVARIANT with a mamba backend"),
                             err("import-error", "the class can't be imported")]))
    ma, mb = fn(UT, "mamba_get_block_table_tensor")
    out.append(iface("attention-backend-utils", "mamba-get-block-table-tensor",
                     "mamba_get_block_table_tensor: under mamba_cache_mode 'none' the block table already holds 1 + num_speculative_blocks state blocks per request; "
                     "under 'align' (prefix caching of mamba state) gather, per request, the 1 + num_speculative_blocks blocks starting at (seq_len - 1) // block_size (0 for empty rows).",
                     [C(UT, ma, mb)],
                     [{"if": "input.mamba_cache_mode == 'none'",
                       "then": [{"title": "mode none: the table is returned as is", "source": C(UT, ln(UT, r'if mamba_cache_mode == "none":', ma), ln(UT, r"return block_table", ma)),
                                 "return": {"block_table": "= input.block_table"}}]},
                      {"if": "!input.is_mamba_spec",
                       "then": [{"title": "The KV cache spec must be a MambaSpec (bare assert)", "source": C(UT, ln(UT, r"assert isinstance\(kv_cache_spec, MambaSpec\)", ma)),
                                 "fail": {"code": "assertion-error", "message": ""}}]},
                      {"title": "start = max((seq_len - 1) // block_size, 0); gather start + 0 .. num_speculative_blocks from each row",
                       "source": C(UT, ln(UT, r"start_indices = \(seq_lens - 1\) // kv_cache_spec\.block_size", ma), mb),
                       "return": {"block_table": "= lists.range(size(input.seq_lens)).map(r, lists.range(1 + input.num_speculative_blocks).map(k, input.block_table[r][math.greatest(input.seq_lens[r] > 0 ? (input.seq_lens[r] - 1) / input.block_size : 0, 0) + k]))"}}],
                     request=obj({"block_table": ARR_II, "seq_lens": ARR_I, "mamba_cache_mode": {"type": "string", "enum": ["none", "align", "all"], "default": "none"},
                                  "block_size": I(16), "num_speculative_blocks": I(0), "is_mamba_spec": B(True)}, required=["block_table", "seq_lens"]),
                     response=obj({"block_table": ARR_II}), errors=[err("assertion-error", "the spec is not a MambaSpec")]))
    return out


FAU = "vllm/v1/attention/backends/fa_utils.py"


def block_size_interfaces():
    out = []
    sa, sb = fn(BK, "supports_block_size")
    row = "state.backends[input.backend]"
    unknown = {"if": "!(input.backend in state.backends)",
               "then": [{"title": "Not a modeled backend class", "source": C("vllm/v1/attention/backends/registry.py", ln("vllm/v1/attention/backends/registry.py", r"^class AttentionBackendEnum")),
                         "fail": {"code": "key-error", "message": "= input.backend"}}]}
    out.append(iface("attention-backend", "supports-block-size",
                     "AttentionBackend.supports_block_size: None is always fine; otherwise the block size must be a multiple of one of the kernel's block sizes "
                     "(a fixed kernel size too, since hybrid blocks split a framework block into kernel blocks).",
                     [C(BK, sa, sb)],
                     [unknown,
                      {"if": "input.block_size == null",
                       "then": [{"title": "No block size requested", "source": C(BK, ln(BK, r"if block_size is None:", sa)), "return": {"supported": True}}]},
                      {"title": "block_size % kernel size (MultipleOf(n) counts as n) == 0 for some kernel size",
                       "source": C(BK, ln(BK, r"supported_kernel_block_sizes = cls\.get_supported_kernel_block_sizes\(\)", sa), sb),
                       "return": {"supported": f"= input.block_size % {row}.block_multiple == 0"}}],
                     request=obj({"backend": S("FLASH_ATTN"), "block_size": {"type": ["integer", "null"], "default": None}}),
                     response=obj({"supported": {"type": "boolean"}}), errors=[err("key-error", "no such backend")]))
    pa, pb = fn(BK, "get_preferred_block_size")
    fpa, fpb = fn(FA, "get_preferred_block_size")
    s9a, s9b = fn(FA, "_get_sm90_fa4_fp8_kv_block_size")
    hda, hdb = fn(FA, "_get_fa4_hd256_block_size")
    beh = [
        unknown,
        {"if": "input.backend == 'FLASH_ATTN'",
         "then": [
             {"title": "FlashAttention asks get_flash_attn_version for the model's head size (the current VllmConfig)", "source": C(FA, ln(FA, r"and get_flash_attn_version\(head_size=head_size\) == 4", s9a)),
              "call": "fa-utils.get-flash-attn-version", "input": {"head_size": "= input.head_size", "device_capability_major": "= input.device_capability_major"}, "as": "fav"},
             {"if": "input.device_capability_major == 9 && (input.kv_cache_dtype == 'fp8' || input.kv_cache_dtype == 'fp8_e4m3') && input.head_size == 512 && vars.fav.value.fa_version == 4",
              "then": [{"title": "SM90 FP8-KV dequant kernel (FA4, head 512): a 64-token TMA page, at least", "source": C(FA, s9a, s9b),
                        "return": {"block_size": "= math.greatest(input.default_block_size, 64)"}}]},
             {"if": "input.head_size == 256 && input.device_capability_major in [10, 11] && vars.fav.value.fa_version == 4",
              "then": [{"title": "FA4's dedicated hd256 kernel (SM100/SM110): FA4_HD256_PAGE_SIZE = 128, at least", "source": C(FA, hda, hdb),
                        "detail": "uses_fa4_hd256_kernel: head size 256 (V 256 too) on compute capability 10.x or 11.x; FA4_HD256_PAGE_SIZE in fa_utils.py",
                        "return": {"block_size": "= math.greatest(input.default_block_size, 128)"}}]}]},
        {"title": "AttentionBackend.get_preferred_block_size: the default when the kernel accepts it, else the smallest kernel size",
         "source": C(BK, pa, pb),
         "return": {"block_size": f"= input.default_block_size % {row}.block_multiple == 0 ? input.default_block_size : {row}.block_multiple"}},
    ]
    out.append(iface("attention-backend", "get-preferred-block-size",
                     "get_preferred_block_size(default_block_size): FlashAttention raises the default to 64 for SM90 FP8 KV with FA4 at head 512 and to 128 for FA4's hd256 kernel "
                     "on Blackwell; otherwise the base rule keeps the default when supported, else takes the smallest kernel block size (FlashMLA 64, CUTLASS MLA 128). "
                     "The platform's update_block_size_for_backend (config-platform) applies it when --block-size isn't given.",
                     [C(BK, pa, pb), C(FA, fpa, fpb), C(FA, s9a, s9b), C(FA, hda, hdb), C(FAU, ln(FAU, r"^FA4_HD256_PAGE_SIZE = 128"))], beh,
                     request=obj({"backend": S("FLASH_ATTN"), "default_block_size": I(16), "head_size": I(128), "kv_cache_dtype": S("auto"), "device_capability_major": I(9)}),
                     response=obj({"block_size": {"type": "integer"}}), errors=[err("key-error", "no such backend")]))
    return out


def _cls_name(path_expr):
    return f"{path_expr}.split('.')[size({path_expr}.split('.')) - 1]"


def encoder_only_interfaces():
    out = []
    ca, cb = fn(EOA, "create_encoder_only_attention_backend")
    bmap = str(BUILDERS).replace('"', "'")
    out.append(iface("encoder-only-attention-builder", "create-backend",
                     "create_encoder_only_attention_backend (lru_cache per underlying class): EncoderOnlyAttention_<Backend>, whose builder is EncoderOnlyAttentionBuilder over the backend's own builder.",
                     [C(EOA, ca, cb)],
                     [{"title": "prefix EncoderOnlyAttention_; underlying_attn_backend.get_builder_cls()", "source": C(EOA, ln(EOA, r'prefix = "EncoderOnlyAttention_"', ca), ln(EOA, r"underlying_builder = ", ca)),
                       "set": {"vars.cls": "= " + _cls_name("input.underlying_backend_cls_path")}},
                      {"title": "subclass_attention_backend(name_prefix, backend, EncoderOnlyAttentionBuilder)", "source": C(EOA, ln(EOA, r"attn_backend = subclass_attention_backend\(", ca), cb),
                       "return": {"name": "= 'EncoderOnlyAttention_' + vars.cls", "base": "= vars.cls", "builder_cls": "EncoderOnlyAttentionBuilder",
                                  "builder_base": f"= vars.cls in {bmap} ? {bmap}[vars.cls] : vars.cls.replace('Backend', 'MetadataBuilder')"}}],
                     request=obj({"underlying_backend_cls_path": S("vllm.v1.attention.backends.flash_attn.FlashAttentionBackend")}),
                     response=obj({"name": {"type": "string"}, "base": {"type": "string"}, "builder_cls": {"type": "string"}, "builder_base": {"type": "string"}})))
    ia, ib = fn(EOA, "__init__", cls(EOA, "EncoderOnlyAttention")[0])
    out.append(iface("encoder-only-attention", "init",
                     "EncoderOnlyAttention.__init__: get_attn_backend(head_size, default dtype, cache dtype, attn_type=ENCODER_ONLY), wrap it, refuse any other attn_type, "
                     "then Attention.__init__ with that backend and ENCODER_ONLY; the layer has no KV cache spec.",
                     [C(EOA, ia, ib), Cfn(EOA, "get_kv_cache_spec")],
                     [{"title": "kv_cache_dtype from the cache config, or auto", "source": C(EOA, ln(EOA, r"dtype = torch\.get_default_dtype\(\)", ia), ln(EOA, r'kv_cache_dtype = "auto"', ia)),
                       "set": {"vars.kv": "= input.has_cache_config ? config['kv-cache-dtype'] : 'auto'"}},
                      {"title": "get_attn_backend(head_size, dtype, kv_cache_dtype, attn_type=AttentionType.ENCODER_ONLY): backends without encoder-only support are skipped",
                       "source": C(EOA, ln(EOA, r"underlying_attn_backend = get_attn_backend\(", ia), ln(EOA, r"attn_type=AttentionType\.ENCODER_ONLY,", ia)),
                       "call": "selector.get-attn-backend",
                       "input": {"head_size": "= input.head_size", "dtype": "= input.dtype", "kv_cache_dtype": "= vars.kv", "attn_type": "encoder_only", "num_heads": "= input.num_heads"}, "as": "sel"},
                      {"title": "create_encoder_only_attention_backend(underlying)", "source": C(EOA, ln(EOA, r"attn_backend = create_encoder_only_attention_backend\(", ia)),
                       "call": "encoder-only-attention-builder.create-backend", "input": {"underlying_backend_cls_path": "= vars.sel.value.backend_cls_path"}, "as": "be"},
                      {"if": "input.attn_type != null && input.attn_type != 'encoder_only'",
                       "then": [{"title": "An explicit attn_type must be ENCODER_ONLY", "source": C(EOA, ln(EOA, r"if attn_type is not None:", ia), ln(EOA, r'"EncoderOnlyAttention only supports AttentionType\.ENCODER_ONLY"', ia)),
                                 "fail": {"code": "assertion-error", "message": "EncoderOnlyAttention only supports AttentionType.ENCODER_ONLY"}}]},
                      {"title": "Attention.__init__(attn_backend=..., attn_type=ENCODER_ONLY); get_kv_cache_spec returns None (no KV cache)",
                       "source": C(EOA, ln(EOA, r"super\(\).__init__\(", ia), fn(EOA, "get_kv_cache_spec")[1]),
                       "return": {"backend": "= vars.be.value.name", "underlying_backend_cls_path": "= vars.sel.value.backend_cls_path", "attn_type": "encoder_only",
                                  "kv_cache_dtype": "= vars.kv", "kv_cache_spec": None}}],
                     request=obj({"num_heads": I(12), "head_size": I(64), "dtype": S("bfloat16"), "has_cache_config": B(True),
                                  "attn_type": {"type": ["string", "null"], "default": None}}),
                     response=obj({"backend": {"type": "string"}, "underlying_backend_cls_path": {"type": "string"}, "attn_type": {"type": "string"},
                                   "kv_cache_dtype": {"type": "string"}, "kv_cache_spec": {"type": ["string", "null"]}}),
                     errors=[err("assertion-error", "attn_type other than ENCODER_ONLY")]))
    ba = ln(EOA, r"def build\(")
    bb = ln(EOA, r"common_prefix_len, new_common_attn_metadata, fast_build", ba) + 1
    out.append(iface("encoder-only-attention-builder", "build",
                     "EncoderOnlyAttentionBuilder.build: copy the common metadata with causal = False and run the underlying builder (FlashAttention's) on it.",
                     [C(EOA, ba, bb)],
                     [{"title": "new_common_attn_metadata = copy(common_attn_metadata); causal = False",
                       "source": C(EOA, ln(EOA, r"new_common_attn_metadata = copy\(common_attn_metadata\)", ba), ln(EOA, r"new_common_attn_metadata\.causal = False", ba)),
                       "set": {"vars.cm": "= merge(input.common, {'causal': false})"}},
                      {"title": "super().build(common_prefix_len, new_common_attn_metadata, fast_build)", "source": C(EOA, ln(EOA, r"return super\(\)\.build\(", ba), bb),
                       "call": "flash-attention-metadata-builder.build", "input": {"common": "= vars.cm", "fast_build": "= input.fast_build"}, "as": "md"},
                      {"return": {"metadata": "= vars.md.value"}}],
                     request=obj({"common": {"$ref": "AttnCommonMetadata"}, "fast_build": B(False)}, required=["common"]),
                     response=obj({"metadata": {"type": "object"}})))
    return out


def cross_interfaces():
    out = []
    sa, sb = fn(XA, "_get_cross_slot_mapping")
    out.append(iface("cross-attention-builder", "get-cross-slot-mapping",
                     "_get_cross_slot_mapping: for each request with a non-zero encoder length, the slots of its first cdiv(len, block_size) blocks, token by token; concatenated (empty when none).",
                     [C(XA, sa, sb)],
                     [{"title": "Only requests with a non-zero encoder length (np.nonzero)", "source": C(XA, ln(XA, r"active_indices = np\.nonzero\(encoder_seq_lens\)\[0\]", sa)),
                       "set": {"vars.act": "= lists.range(size(input.encoder_seq_lens)).filter(r, input.encoder_seq_lens[r] > 0)"}},
                      {"title": "slot = block_table[r][i // block_size] * block_size + i % block_size for every encoder token i; torch.cat, or an empty int64 tensor",
                       "source": C(XA, ln(XA, r"for req_index in active_indices:", sa), sb),
                       "return": {"slot_mapping": "= vars.act.map(r, lists.range(input.encoder_seq_lens[r]).map(i, input.block_table[r][i / input.block_size] * input.block_size + i % input.block_size)).flatten()"}}],
                     request=obj({"encoder_seq_lens": ARR_I, "block_table": ARR_II, "block_size": I(16)}, required=["encoder_seq_lens", "block_table"]),
                     response=obj({"slot_mapping": ARR_I})))
    ca, cb = fn(XA, "create_cross_attention_backend")
    bmap = str(BUILDERS).replace('"', "'")
    out.append(iface("cross-attention-builder", "create-backend",
                     "create_cross_attention_backend (lru_cache per underlying class): CrossAttention_<Backend> overriding get_builder_cls (CrossAttentionBuilder), "
                     "get_impl_cls (CrossAttentionImpl) and forward_includes_kv_cache_update = True, so the runner doesn't write K/V separately.",
                     [C(XA, ca, cb)],
                     [{"title": "prefix CrossAttention_; the underlying builder and impl classes", "source": C(XA, ln(XA, r'prefix = "CrossAttention_"', ca), ln(XA, r"underlying_impl = ", ca)),
                       "set": {"vars.cls": "= " + _cls_name("input.underlying_backend_cls_path")}},
                      {"title": "subclass_attention_backend_with_overrides", "source": C(XA, ln(XA, r"attn_backend = subclass_attention_backend_with_overrides\(", ca), cb),
                       "return": {"name": "= 'CrossAttention_' + vars.cls", "base": "= vars.cls", "builder_cls": "CrossAttentionBuilder", "impl_cls": "CrossAttentionImpl",
                                  "builder_base": f"= vars.cls in {bmap} ? {bmap}[vars.cls] : vars.cls.replace('Backend', 'MetadataBuilder')",
                                  "forward_includes_kv_cache_update": True}}],
                     request=obj({"underlying_backend_cls_path": S("vllm.v1.attention.backends.flash_attn.FlashAttentionBackend")}),
                     response=obj({"name": {"type": "string"}, "base": {"type": "string"}, "builder_cls": {"type": "string"}, "impl_cls": {"type": "string"},
                                   "builder_base": {"type": "string"}, "forward_includes_kv_cache_update": {"type": "boolean"}})))
    ia, ib = fn(XA, "__init__", cls(XA, "CrossAttention")[0])
    out.append(iface("cross-attention", "init",
                     "CrossAttention.__init__: refuse any attn_type but ENCODER_DECODER, get_attn_backend(head_size, default dtype, cache dtype, attn_type=ENCODER_DECODER), "
                     "wrap it, then Attention.__init__; the KV cache spec is CrossAttentionSpec.",
                     [C(XA, ia, ib), Cfn(XA, "get_kv_cache_spec")],
                     [{"title": "kv_cache_dtype from the cache config, or auto", "source": C(XA, ln(XA, r"dtype = torch\.get_default_dtype\(\)", ia), ln(XA, r'kv_cache_dtype = "auto"', ia)),
                       "set": {"vars.kv": "= input.has_cache_config ? config['kv-cache-dtype'] : 'auto'"}},
                      {"if": "input.attn_type != null && input.attn_type != 'encoder_decoder'",
                       "then": [{"title": "An explicit attn_type must be ENCODER_DECODER (checked before selection)", "source": C(XA, ln(XA, r"if attn_type is not None:", ia), ln(XA, r'"CrossAttention only supports AttentionType\.ENCODER_DECODER"', ia)),
                                 "fail": {"code": "assertion-error", "message": "CrossAttention only supports AttentionType.ENCODER_DECODER"}}]},
                      {"title": "get_attn_backend(head_size, dtype, kv_cache_dtype, attn_type=AttentionType.ENCODER_DECODER)",
                       "source": C(XA, ln(XA, r"underlying_attn_backend = get_attn_backend\(", ia), ln(XA, r"attn_type=AttentionType\.ENCODER_DECODER,", ia)),
                       "call": "selector.get-attn-backend",
                       "input": {"head_size": "= input.head_size", "dtype": "= input.dtype", "kv_cache_dtype": "= vars.kv", "attn_type": "encoder_decoder", "num_heads": "= input.num_heads"}, "as": "sel"},
                      {"title": "create_cross_attention_backend(underlying)", "source": C(XA, ln(XA, r"attn_backend = create_cross_attention_backend\(", ia)),
                       "call": "cross-attention-builder.create-backend", "input": {"underlying_backend_cls_path": "= vars.sel.value.backend_cls_path"}, "as": "be"},
                      {"title": "Attention.__init__(attn_backend=..., attn_type=ENCODER_DECODER); CrossAttentionSpec(block_size, num_kv_heads, head_size, dtype, kv_quant_mode)",
                       "source": C(XA, ln(XA, r"super\(\).__init__\(", ia), fn(XA, "get_kv_cache_spec")[1]),
                       "return": {"backend": "= vars.be.value.name", "underlying_backend_cls_path": "= vars.sel.value.backend_cls_path", "attn_type": "encoder_decoder",
                                  "kv_cache_dtype": "= vars.kv", "kv_cache_spec": "CrossAttentionSpec"}}],
                     request=obj({"num_heads": I(20), "head_size": I(64), "dtype": S("bfloat16"), "has_cache_config": B(True),
                                  "attn_type": {"type": ["string", "null"], "default": None}}),
                     response=obj({"backend": {"type": "string"}, "underlying_backend_cls_path": {"type": "string"}, "attn_type": {"type": "string"},
                                   "kv_cache_dtype": {"type": "string"}, "kv_cache_spec": {"type": "string"}}),
                     errors=[err("assertion-error", "attn_type other than ENCODER_DECODER")]))
    ba = ln(XA, r"def build\(")
    bb = ln(XA, r"return attn_metadata", ba)
    L = lambda pat: ln(XA, pat, ba)
    beh = [
        {"set": {"vars.qsl": "= has(input.common.query_start_loc_cpu) && size(input.common.query_start_loc_cpu) > 0 ? input.common.query_start_loc_cpu : [0] + lists.range(size(input.common.query_lens)).map(i, sum(input.common.query_lens.slice(0, i + 1)))"}},
        {"if": "input.encoder_seq_lens_cpu == null",
         "then": [{"title": "encoder_seq_lens_cpu must be set (bare assert)", "source": C(XA, L(r"assert new_metadata\.encoder_seq_lens_cpu is not None")),
                   "fail": {"code": "assertion-error", "message": ""}}]},
        {"title": "Non-causal; max_seq_len = the longest encoder input", "source": C(XA, L(r"new_metadata = copy\(common_attn_metadata\)"), L(r"new_metadata\.max_seq_len = max_encoder_len")),
         "set": {"vars.maxenc": "= math.greatest(input.encoder_seq_lens_cpu)"}},
        {"if": "input.common.seq_lens_cpu_upper_bound == null",
         "then": [{"title": "seq_lens_cpu_upper_bound must be set (bare assert)", "source": C(XA, L(r"assert common_attn_metadata\.seq_lens_cpu_upper_bound is not None")),
                   "fail": {"code": "assertion-error", "message": ""}}]},
        {"title": "Computed tokens = upper bound - query length: any > 0 is a decode step whose cross K/V is already cached",
         "source": C(XA, L(r"query_lens_cpu = \("), L(r"num_cache_decodes = \(num_computed_tokens_cpu > 0\)")),
         "set": {"vars.nc": "= lists.range(size(input.encoder_seq_lens_cpu)).map(r, input.common.seq_lens_cpu_upper_bound[r] - (vars.qsl[r + 1] - vars.qsl[r]))"}},
        {"title": "Those requests get encoder length 0, so no slots are computed for them (reshape_and_cache is skipped)",
         "source": C(XA, L(r"if num_cache_decodes > 0:"), L(r"num_tokens > 0, 0, new_metadata\.encoder_seq_lens_cpu") + 1),
         "set": {"vars.enc": "= lists.range(size(input.encoder_seq_lens_cpu)).map(r, vars.nc[r] > 0 ? 0 : input.encoder_seq_lens_cpu[r])"}},
        {"title": "seq_lens and seq_lens_cpu_upper_bound become the original encoder lengths (the keys every decoder token attends to)",
         "source": C(XA, L(r"new_metadata\.seq_lens = common_attn_metadata\.encoder_seq_lens"), L(r"common_attn_metadata\.encoder_seq_lens_cpu$")),
         "set": {"vars.cm": "= merge(input.common, {'causal': false, 'max_seq_len': vars.maxenc, 'seq_lens': input.encoder_seq_lens_cpu, 'seq_lens_cpu_upper_bound': input.encoder_seq_lens_cpu})"}},
        {"title": "_get_cross_slot_mapping over the zeroed encoder lengths", "source": C(XA, L(r"slot_mapping = _get_cross_slot_mapping\("), L(r"self\.device,") + 1),
         "call": "cross-attention-builder.get-cross-slot-mapping",
         "input": {"encoder_seq_lens": "= vars.enc", "block_table": "= input.common.block_table", "block_size": "= input.block_size"}, "as": "sm"},
        {"title": "super().build on the new metadata", "source": C(XA, L(r"attn_metadata = super\(\)\.build\(common_prefix_len, new_metadata, fast_build\)")),
         "call": "flash-attention-metadata-builder.build", "input": {"common": "= vars.cm", "fast_build": "= input.fast_build"}, "as": "md"},
        {"title": "attn_metadata.slot_mapping = the cross slot mapping", "source": C(XA, L(r"attn_metadata\.slot_mapping = slot_mapping"), bb),
         "return": {"metadata": "= merge(vars.md.value, {'slot_mapping': vars.sm.value.slot_mapping})", "encoder_seq_lens_cpu": "= vars.enc"}},
    ]
    out.append(iface("cross-attention-builder", "build",
                     "CrossAttentionBuilder.build: non-causal metadata whose keys are the encoder outputs (seq_lens = encoder lengths), with a slot mapping only for requests "
                     "whose cross K/V isn't cached yet (prefill steps); decode steps attend the cached cross K/V.",
                     [C(XA, ba, bb)], beh,
                     request=obj({"common": obj({"query_start_loc_cpu": A([]), "query_lens": A([]), "seq_lens": ARR_I, "block_table": ARR_II,
                                                 "seq_lens_cpu_upper_bound": {"type": ["array", "null"], "items": {"type": "integer"}, "default": None},
                                                 "num_reqs": I(1), "num_actual_tokens": I(1), "max_query_len": I(1), "max_seq_len": I(1), "slot_mapping": A([])},
                                                required=["seq_lens", "block_table"]),
                                  "encoder_seq_lens_cpu": {"type": ["array", "null"], "items": {"type": "integer"}, "default": None},
                                  "block_size": I(16), "fast_build": B(False)}, required=["common"]),
                     response=obj({"metadata": {"type": "object"}, "encoder_seq_lens_cpu": ARR_I}),
                     errors=[err("assertion-error", "encoder_seq_lens_cpu or seq_lens_cpu_upper_bound missing")]))
    fa_ = ln(XA, r"def forward\(")
    fb_ = ln(XA, r"output_block_scale,\n?", ln(XA, r"return super\(\)\.forward\(", fa_)) + 1
    out.append(iface("cross-attention-builder", "impl-forward",
                     "CrossAttentionImpl.forward: write the encoder K/V into the cache through the builder's cross slot mapping (unless the layer shares another's cache, "
                     "or K/V is None on decode steps), then the underlying impl's forward.",
                     [C(XA, fa_, fb_)],
                     [{"if": "input.has_metadata && !input.kv_sharing && input.has_key_value",
                       "then": [{"title": "do_kv_cache_update with attn_metadata.slot_mapping (the cross one, not BlockTable's)",
                                 "source": C(XA, ln(XA, r"not underlying_attn_backend\.forward_includes_kv_cache_update", fa_), ln(XA, r"attn_metadata\.slot_mapping,", fa_) + 1),
                                 "call": "flash-attention-impl.do-kv-cache-update",
                                 "input": {"attn_type": "encoder_decoder", "num_tokens": "= size(input.slot_mapping)", "num_kv_heads": "= input.num_kv_heads", "head_size": "= input.head_size",
                                           "slot_mapping": "= input.slot_mapping"}, "as": "upd"}]},
                      {"title": "super().forward", "source": C(XA, ln(XA, r"return super\(\)\.forward\(", fa_), fb_),
                       "call": "flash-attention-impl.forward",
                       "input": {"attn_type": "encoder_decoder", "num_tokens": "= input.num_tokens", "num_heads": "= input.num_heads", "num_kv_heads": "= input.num_kv_heads",
                                 "head_size": "= input.head_size", "metadata": "= input.metadata"}, "as": "fw"},
                      {"return": {"kv_written": "= input.has_metadata && !input.kv_sharing && input.has_key_value", "forward": "= vars.fw.value"}}],
                     request=obj({"num_tokens": I(1), "num_heads": I(20), "num_kv_heads": I(20), "head_size": I(64), "has_metadata": B(True), "kv_sharing": B(False),
                                  "has_key_value": B(True), "slot_mapping": A([]), "metadata": {"type": ["object", "null"], "default": None}}),
                     response=obj({"kv_written": {"type": "boolean"}, "forward": {"type": "object"}})))
    return out


# test_chunked_local_attention.py cases: (query_lens, seq_lens, chunk, block, q, k, table)
CASES = [
    ([4, 10, 5], [6, 17, 9], 4, 2, [2, 2, 1, 4, 4, 1, 4, 1], [4, 2, 4, 4, 4, 1, 4, 1],
     [[0, 1], [2, 3], [11, 12], [13, 14], [15, 16], [17, 17], [20, 21], [22, 23]]),
    ([8], [12], 4, 2, [4, 4], [4, 4], [[2, 3], [4, 5]]),
    ([7], [10], 4, 2, [1, 4, 2], [4, 4, 2], [[0, 1], [2, 3], [4, 4]]),
    ([4], [6], 10, 2, [4], [6], [[0, 1, 2, 2, 2]]),
    ([6, 6], [8, 8], 4, 4, [2, 4, 2, 4], [4, 4, 4, 4], [[0], [1], [2], [3]]),
    ([1], [5], 4, 2, [1], [1], [[2, 2]]),
]


def _arange_table(seq_lens, block):
    """create_common_attn_metadata(arange_block_indices=True): (batches, cdiv(max_seq_len, block)) filled with 0.. in row order."""
    ncols = -(-max(seq_lens) // block)
    return [[r * ncols + c for c in range(ncols)] for r in range(len(seq_lens))]


def scenarios():
    S_ = []
    steps, exp = [], []
    for k, (ql, sl, ch, bs, q, kk, tbl) in enumerate(CASES):
        qsl = [0]
        for x in ql:
            qsl.append(qsl[-1] + x)
        a = f"c{k}"
        steps.append(step("attention-backend-utils.make-local-attention-virtual-batches",
                          {"attn_chunk_size": ch, "block_size": bs,
                           "common": {"query_start_loc_cpu": qsl, "seq_lens": sl, "block_table": _arange_table(sl, bs), "num_actual_tokens": sum(ql)}}, a))
        r = f"steps.{a}.result.value.common"
        exp.append(f"steps.{a}.result.ok && {r}.query_lens == {q} && {r}.seq_lens_cpu_upper_bound == {kk} && {r}.block_table == {tbl}")
        exp.append(f"{r}.query_lens.all(x, x <= {ch}) && {r}.seq_lens_cpu_upper_bound.all(x, x <= {ch}) && sum({r}.query_lens) == {sum(ql)} && {r}.num_reqs == {len(q)}")
    S_.append({"id": "attention-r6-local-attention-virtual-batches", "name": "make_local_attention_virtual_batches on the six test_chunked_local_attention cases: virtual q/k lengths within the chunk, total query tokens kept, chunk // block pages per row clipped to the last column",
               "fixtures": FX, "steps": steps, "expect": exp})
    base = {"query_start_loc_cpu": [0, 4], "seq_lens": [6], "block_table": [[0, 1, 2]]}
    S_.append({"id": "attention-r6-local-attention-block-size-errors", "name": "make_local_attention_virtual_batches: a chunk that is not a whole number of blocks fails the assertion with its message; the default block_size 0 divides by zero",
               "fixtures": FX,
               "steps": [step("attention-backend-utils.make-local-attention-virtual-batches", {"attn_chunk_size": 6, "block_size": 4, "common": base}, "nd"),
                         step("attention-backend-utils.make-local-attention-virtual-batches", {"attn_chunk_size": 4, "common": base}, "z")],
               "expect": ["!steps.nd.result.ok && steps.nd.result.error.code == 'assertion-error' && steps.nd.result.error.message == 'attn_chunk_size 6 is not divisible by block_size 4'",
                          "!steps.z.result.ok && steps.z.result.error.code == 'zero-division-error' && steps.z.result.error.message == 'integer modulo by zero'"]})
    # The layer and its builder end to end on the H100 world: Llama 4's chunk of 8192 over FlashAttention.
    common = {"query_lens": [8200, 1], "seq_lens": [8200, 16390], "block_table": [list(range(0, 1025)), list(range(1000, 2025))],
              "num_actual_tokens": 8201, "slot_mapping": list(range(8201))}
    S_.append({"id": "attention-r6-chunked-local-attention-layer-and-builder",
               "name": "ChunkedLocalAttention (chunk 8192, block 16) on the H100: selects FlashAttention with only head size, dtype and cache dtype, wraps it as ChunkedLocalAttention_8192_FlashAttentionBackend; build splits an 8200-token prefill into 8192 + 8 and a decode at 16390 into its last chunk of 6, runs FlashAttention's build on 3 virtual requests, never captures CUDA graphs, and maps a later block table through the same gather",
               "fixtures": FX,
               "steps": [step("chunked-local-attention.init", {"num_heads": 40, "head_size": 128, "attention_chunk_size": 8192}, "init"),
                         step("chunked-local-attention-builder.build", {"attention_chunk_size": 8192, "block_size": 16, "common": common}, "b"),
                         step("chunked-local-attention-builder.get-cudagraph-support", {}, "cg"),
                         {"interface": "chunked-local-attention-builder.update-block-table", "caller": "gpu-worker",
                          "input": {"make_virtual_batches_block_table": "= steps.b.result.value.make_virtual_batches_block_table",
                                    "block_table": [list(range(5000, 6025)), list(range(7000, 8025))], "slot_mapping": [1, 2]}, "as": "u"}],
               "expect": ["steps.init.result.value.backend == 'ChunkedLocalAttention_8192_FlashAttentionBackend' && steps.init.result.value.kv_cache_spec == 'ChunkedLocalAttentionSpec'",
                          "trace.exists(e, e.type == 'call.end' && e.interface == 'chunked-local-attention-builder.create-backend' && e.output.builder_base == 'FlashAttentionMetadataBuilder')",
                          "trace.exists(e, e.type == 'call.start' && e.interface == 'selector.get-attn-backend' && !e.input.has_sliding_window && !e.input.use_mla && e.input.kv_cache_dtype == 'auto')",
                          "steps.b.result.value.virtual.query_lens == [8192, 8, 1] && steps.b.result.value.virtual.seq_lens == [8192, 8, 6]",
                          "steps.b.result.value.virtual.block_table[0][0] == 0 && steps.b.result.value.virtual.block_table[1][0] == 512 && steps.b.result.value.virtual.block_table[2][0] == 2024 && size(steps.b.result.value.virtual.block_table[0]) == 512",
                          "steps.b.result.value.metadata.num_reqs == 3 && steps.b.result.value.metadata.max_query_len == 8192",
                          "trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attention-metadata-builder.build' && e.input.common.num_reqs == 3)",
                          "steps.cg.result.value.support == 'NEVER'",
                          "steps.u.result.value.block_table[1][0] == 5512 && steps.u.result.value.block_table[2][0] == 8024 && steps.u.result.value.slot_mapping == [1, 2]"]})
    # Encoder-only attention (BERT-style pooling models): selection for ENCODER_ONLY, a non-causal build, the encoder forward, no KV cache.
    enc_common = {"num_reqs": 2, "num_actual_tokens": 12, "max_query_len": 7, "max_seq_len": 7, "query_lens": [5, 7], "seq_lens": [5, 7],
                  "block_table": [[0], [0]], "slot_mapping": list(range(12))}
    S_.append({"id": "attention-r6-encoder-only-attention-bert",
               "name": "EncoderOnlyAttention for a BERT-style pooling model (12 heads of 64): selected for ENCODER_ONLY (FlashAttention, FA3), wrapped as EncoderOnlyAttention_FlashAttentionBackend with no KV cache spec; build makes the metadata non-causal; the impl runs the bidirectional encoder path; an explicit decoder attn_type is refused",
               "fixtures": FX,
               "steps": [step("encoder-only-attention.init", {"num_heads": 12, "head_size": 64}, "init"),
                         step("encoder-only-attention-builder.build", {"common": enc_common}, "b"),
                         {"interface": "flash-attention-impl.forward", "caller": "gpu-worker", "as": "fw",
                          "input": {"attn_type": "encoder_only", "num_tokens": 12, "num_heads": 12, "num_kv_heads": 12, "head_size": 64, "metadata": "= steps.b.result.value.metadata"}},
                         step("encoder-only-attention.init", {"num_heads": 12, "head_size": 64, "attn_type": "decoder"}, "bad")],
               "expect": ["steps.init.result.value.backend == 'EncoderOnlyAttention_FlashAttentionBackend' && steps.init.result.value.kv_cache_spec == null",
                          "trace.exists(e, e.type == 'call.start' && e.interface == 'selector.get-attn-backend' && e.input.attn_type == 'encoder_only' && e.input.head_size == 64)",
                          "trace.exists(e, e.type == 'call.end' && e.interface == 'encoder-only-attention-builder.create-backend' && e.output.builder_base == 'FlashAttentionMetadataBuilder')",
                          "!steps.b.result.value.metadata.causal && steps.b.result.value.metadata.num_reqs == 2",
                          "steps.fw.result.ok && steps.fw.result.value.path == 'encoder'",
                          "!steps.bad.result.ok && steps.bad.result.error.code == 'assertion-error' && steps.bad.result.error.message == 'EncoderOnlyAttention only supports AttentionType.ENCODER_ONLY'"]})
    S_.append({"id": "attention-r6-encoder-only-selection-skips-decoder-only-backends",
               "name": "Encoder-only selection: FlashAttention, Triton and FlexAttention accept ENCODER_ONLY; FlashInfer refuses it with the enum-formatted reason, so --attention-backend FLASHINFER fails an encoder-only layer",
               "fixtures": FX, "config": {"attention-backend": "FLASHINFER"},
               "steps": [step("attention-backend.validate-configuration", {"backend": "FLASH_ATTN", "attn_type": "encoder_only", "head_size": 64}, "fa"),
                         step("attention-backend.validate-configuration", {"backend": "TRITON_ATTN", "attn_type": "encoder_only", "head_size": 64}, "tr"),
                         step("attention-backend.validate-configuration", {"backend": "FLEX_ATTENTION", "attn_type": "encoder_only", "head_size": 64}, "fx"),
                         step("attention-backend.validate-configuration", {"backend": "FLASHINFER", "attn_type": "encoder_only", "head_size": 64}, "fi"),
                         step("encoder-only-attention.init", {"num_heads": 12, "head_size": 64}, "init")],
               "expect": ["steps.fa.result.value.invalid_reasons == [] && steps.tr.result.value.invalid_reasons == [] && steps.fx.result.value.invalid_reasons == []",
                          "steps.fi.result.value.invalid_reasons == ['attention type AttentionType.ENCODER_ONLY not supported']",
                          "!steps.init.result.ok && steps.init.result.error.code == 'value-error' && steps.init.result.error.message.contains('attention type AttentionType.ENCODER_ONLY not supported')"]})
    # Cross attention (Whisper-style encoder-decoder): slot mapping only for prefill requests; decode attends cached cross K/V.
    x_common = {"num_reqs": 2, "num_actual_tokens": 5, "max_query_len": 4, "max_seq_len": 10, "query_lens": [4, 1], "seq_lens": [4, 10],
                "seq_lens_cpu_upper_bound": [4, 10], "block_table": [[3, 7], [5, 9]], "slot_mapping": list(range(5))}
    S_.append({"id": "attention-r6-cross-attention-whisper",
               "name": "CrossAttention (20 heads of 64): selected for ENCODER_DECODER, wrapped as CrossAttention_FlashAttentionBackend with its own impl; a prefill request (encoder 20 tokens, block 16) gets 20 cross slots over its first two blocks, a decode request (already cached) none; seq_lens become the encoder lengths and the metadata is non-causal; the impl writes K/V through that slot mapping before attending",
               "fixtures": FX,
               "steps": [step("cross-attention.init", {"num_heads": 20, "head_size": 64}, "init"),
                         step("cross-attention-builder.build", {"common": x_common, "encoder_seq_lens_cpu": [20, 20], "block_size": 16}, "b"),
                         {"interface": "cross-attention-builder.impl-forward", "caller": "gpu-worker", "as": "fw",
                          "input": {"num_tokens": 5, "slot_mapping": "= steps.b.result.value.metadata.slot_mapping", "metadata": "= steps.b.result.value.metadata"}},
                         step("cross-attention.init", {"num_heads": 20, "head_size": 64, "attn_type": "encoder_only"}, "bad"),
                         step("cross-attention-builder.build", {"common": x_common}, "noenc")],
               "expect": ["steps.init.result.value.backend == 'CrossAttention_FlashAttentionBackend' && steps.init.result.value.kv_cache_spec == 'CrossAttentionSpec'",
                          "trace.exists(e, e.type == 'call.end' && e.interface == 'cross-attention-builder.create-backend' && e.output.impl_cls == 'CrossAttentionImpl' && e.output.forward_includes_kv_cache_update)",
                          "steps.b.result.value.encoder_seq_lens_cpu == [20, 0]",
                          "steps.b.result.value.metadata.slot_mapping == [48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 112, 113, 114, 115]",
                          "!steps.b.result.value.metadata.causal && steps.b.result.value.metadata.seq_lens == [20, 20] && steps.b.result.value.metadata.max_seq_len == 20",
                          "steps.fw.result.value.kv_written && trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attention-impl.do-kv-cache-update' && e.input.num_tokens == 20)",
                          "!steps.bad.result.ok && steps.bad.result.error.message == 'CrossAttention only supports AttentionType.ENCODER_DECODER'",
                          "!trace.exists(e, e.type == 'call.start' && e.interface == 'selector.get-attn-backend' && e.input.attn_type == 'encoder_only')",
                          "!steps.noenc.result.ok && steps.noenc.result.error.code == 'assertion-error'"]})
    pb = lambda a, **kw: step("attention-backend.get-preferred-block-size", kw, a)
    sb = lambda a, **kw: step("attention-backend.supports-block-size", kw, a)
    S_.append({"id": "attention-r6-preferred-block-size",
               "name": "Preferred KV block sizes from the default 16: FlashAttention keeps 16 on the H100, takes 64 for FP8 KV at head 512 (FA4 on SM90) and 128 for FA4's hd256 kernel on SM100; FlashMLA needs 64 and CUTLASS MLA 128; supports_block_size: None always, 8 not for FlashAttention, 128 for FlashMLA",
               "fixtures": FX,
               "steps": [pb("fa"), pb("fa_fp8_512", head_size=512, kv_cache_dtype="fp8"), pb("fa_hd256_sm100", head_size=256, device_capability_major=10),
                         pb("fa_hd256_sm90", head_size=256), pb("flashmla", backend="FLASHMLA"), pb("cutlass", backend="CUTLASS_MLA"), pb("big", default_block_size=32),
                         sb("none", block_size=None), sb("eight", block_size=8), sb("mla128", backend="FLASHMLA", block_size=128), pb("bad", backend="NOPE")],
               "expect": ["steps.fa.result.value.block_size == 16 && steps.big.result.value.block_size == 32",
                          "steps.fa_fp8_512.result.value.block_size == 64",
                          "steps.fa_hd256_sm100.result.value.block_size == 128 && steps.fa_hd256_sm90.result.value.block_size == 16",
                          "steps.flashmla.result.value.block_size == 64 && steps.cutlass.result.value.block_size == 128",
                          "steps.none.result.value.supported && !steps.eight.result.value.supported && steps.mla128.result.value.supported",
                          "!steps.bad.result.ok && steps.bad.result.error.code == 'key-error'"]})
    S_.append({"id": "attention-r6-mamba-backend-and-block-table",
               "name": "Mamba-family layers: get_mamba_attn_backend resolves MAMBA2 to Mamba2AttentionBackend and GDN_ATTN to GDNAttentionBackend; mamba_get_block_table_tensor keeps the table under mode none and gathers the current state block (plus speculative ones) under align",
               "fixtures": FX,
               "steps": [step("selector.get-mamba-attn-backend", {"mamba_type": "MAMBA2"}, "m2"), step("selector.get-mamba-attn-backend", {"mamba_type": "GDN_ATTN"}, "gdn"),
                         step("attention-backend-utils.mamba-get-block-table-tensor", {"block_table": [[4], [9]], "seq_lens": [40, 7]}, "none"),
                         step("attention-backend-utils.mamba-get-block-table-tensor", {"block_table": [[1, 2, 3, 4], [5, 6, 7, 8]], "seq_lens": [40, 0], "mamba_cache_mode": "align", "num_speculative_blocks": 1}, "align")],
               "expect": ["steps.m2.result.value.backend_cls_path == 'vllm.v1.attention.backends.mamba2_attn.Mamba2AttentionBackend' && steps.m2.result.value.name == 'MAMBA2_ATTN'",
                          "steps.gdn.result.value.name == 'GDN_ATTN'",
                          "steps.none.result.value.block_table == [[4], [9]]",
                          "steps.align.result.value.block_table == [[3, 4], [5, 6]]"]})
    S_.append({"id": "attention-r6-mamba-batch-invariant-refused",
               "name": "VLLM_BATCH_INVARIANT=1: a mamba layer's backend lookup raises RuntimeError naming the backend (no mamba backend supports batch invariance)",
               "fixtures": FX, "config": {"vllm-batch-invariant": True},
               "steps": [step("selector.get-mamba-attn-backend", {"mamba_type": "MAMBA2"}, "m2")],
               "expect": ["!steps.m2.result.ok && steps.m2.result.error.code == 'runtime-error' && steps.m2.result.error.message == 'VLLM batch_invariant mode is not supported for MAMBA2_ATTN.'"]})
    S_.append({"id": "attention-r6-wrapper-other-builders-and-refusals",
               "name": "The wrapper backends over Triton and an untabulated backend: ChunkedLocalAttention_4096_TritonAttentionBackend extends TritonAttentionMetadataBuilder and still splits the batch; supports_block_size of an unknown backend is a KeyError; align mode needs a MambaSpec",
               "fixtures": FX,
               "steps": [step("chunked-local-attention-builder.create-backend", {"underlying_backend_cls_path": "vllm.v1.attention.backends.triton_attn.TritonAttentionBackend", "attention_chunk_size": 4096}, "tr"),
                         step("chunked-local-attention-builder.create-backend", {"underlying_backend_cls_path": "vllm.v1.attention.backends.foo.FooBackend", "attention_chunk_size": 4096}, "foo"),
                         step("chunked-local-attention-builder.build", {"attention_chunk_size": 4, "block_size": 2, "underlying_builder": "TritonAttentionMetadataBuilder",
                                                                         "common": {"query_lens": [4], "seq_lens": [6], "block_table": [[0, 1, 2]]}}, "trb"),
                         step("attention-backend.supports-block-size", {"backend": "NOPE", "block_size": 16}, "bad"),
                         step("attention-backend-utils.mamba-get-block-table-tensor", {"block_table": [[1, 2]], "seq_lens": [3], "mamba_cache_mode": "align", "is_mamba_spec": False}, "notmamba")],
               "expect": ["steps.tr.result.value.name == 'ChunkedLocalAttention_4096_TritonAttentionBackend' && steps.tr.result.value.builder_base == 'TritonAttentionMetadataBuilder'",
                          "steps.foo.result.value.builder_base == 'FooMetadataBuilder'",
                          "steps.trb.result.value.virtual.query_lens == [2, 2] && steps.trb.result.value.metadata.num_reqs == 2 && !trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attention-metadata-builder.build')",
                          "!steps.bad.result.ok && steps.bad.result.error.code == 'key-error'",
                          "!steps.notmamba.result.ok && steps.notmamba.result.error.code == 'assertion-error'"]})
    ti = lambda a, **kw: step("triton-attention-impl.init", kw, a)
    S_.append({"id": "attention-r6-triton-impl-init",
               "name": "TritonAttentionImpl.__init__: EmbeddingGemma2-style encoder-only sliding layer (window 513) is (512, 512), a decoder's (512, 0), none (-1, -1); FP8 KV on an A100 and bfloat16 KV on a T4 are refused with the suggested dtype; FP8 on the H100 runs per-tensor",
               "fixtures": FX,
               "steps": [ti("enc", attn_type="encoder_only", sliding_window=513), ti("dec", sliding_window=513), ti("none"),
                         ti("a100", kv_cache_dtype="fp8", device_capability_major=8, device_name="NVIDIA A100-SXM4-80GB"),
                         ti("t4", kv_cache_dtype="bfloat16", device_capability_major=7, device_capability_minor=5, device_name="Tesla T4"),
                         ti("t4fp8", kv_cache_dtype="fp8", device_capability_major=7, device_capability_minor=5, device_name="Tesla T4"),
                         ti("h100fp8", kv_cache_dtype="fp8"), ti("sinks", sinks_heads=16)],
               "expect": ["steps.enc.result.value.sliding_window == [512, 512] && steps.dec.result.value.sliding_window == [512, 0] && steps.none.result.value.sliding_window == [-1, -1]",
                          "steps.a100.result.error.message == 'FP8 KV cache is not supported by the Triton attention backend on NVIDIA A100-SXM4-80GB (compute capability 8.0); native FP8 (fp8e4nv) requires SM89+. Re-run with --kv-cache-dtype bfloat16.'",
                          "steps.t4.result.error.message == 'bfloat16 KV cache is not supported on Tesla T4 (compute capability 7.5); bfloat16 requires SM80+. Re-run with --kv-cache-dtype float16.'",
                          "steps.t4fp8.result.error.message.endsWith('Re-run with --kv-cache-dtype float16.')",
                          "steps.h100fp8.result.ok && steps.h100fp8.result.value.kv_quant_mode == 'fp8_per_tensor' && steps.none.result.value.num_queries_per_kv == 4",
                          "!steps.sinks.result.ok && steps.sinks.result.error.message == 'Sinks must have the same number of heads as the number of heads in the layer. Sinks shape: torch.Size([16]), num_heads: 32.'"]})
    return S_


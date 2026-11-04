"""Round-4 additions (coverage): KV-cache specs and layouts, CommonAttentionMetadata, the backend
registries, the MLA prefill selector, MLAAttention's spec and workspace, the FlashInfer sparse-MLA SM90
builder, sparse-MLA index groups, the ROCm AITER MLA routing predicates and page-index expansion, and the
per-kind backend override in the selector. Also the build-oracle round-4 scenarios."""
import ast

from core import B, I, S, comp, err, iface
from lib import C, Cfn, Cinv, cls, fn, kernel, ln, lines, mark, LAT_META, ROOT

SEL = "vllm/v1/attention/selector.py"
BK = "vllm/v1/attention/backend.py"
REG = "vllm/v1/attention/backends/registry.py"
PREG = "vllm/v1/attention/backends/mla/prefill/registry.py"
PSEL = "vllm/v1/attention/backends/mla/prefill/selector.py"
PBASE = "vllm/v1/attention/backends/mla/prefill/base.py"
KVI = "vllm/v1/kv_cache_interface.py"
KVL = "vllm/v1/kv_cache_layout.py"
MLAA = "vllm/model_executor/layers/attention/mla_attention.py"
SM90 = "vllm/v1/attention/backends/mla/flashinfer_mla_sparse_sm90.py"
FIMS = "vllm/v1/attention/backends/mla/flashinfer_mla_sparse.py"
FMS = "vllm/v1/attention/backends/mla/flashmla_sparse.py"
IG = "vllm/v1/attention/backends/mla/index_group.py"
RAM = "vllm/v1/attention/backends/mla/rocm_aiter_mla.py"
RAMS = "vllm/v1/attention/ops/rocm_aiter_mla_sparse.py"
FA = "vllm/v1/attention/backends/flash_attn.py"
TA = "vllm/v1/attention/backends/triton_attn.py"
FI = "vllm/v1/attention/backends/flashinfer.py"
CFG_ATT = "vllm/config/attention.py"
MD = "vllm/v1/attention/ops/metadata.py"

FX = ["tp1-llama-8b", "attention-seed"]
W = ["full-tp1-llama-8b"]
ARR_I = {"type": "array", "items": {"type": "integer"}}
ARR_II = {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}}


def A(d):
    return {"type": "array", "items": {"type": "integer"}, "default": d}


def obj(props, **kw):
    d = {"type": "object", "properties": props}
    d.update(kw)
    return d


def m(f, cls_name, meth):
    """Line span of a method inside a class."""
    a = cls(f, cls_name)[0]
    return fn(f, meth, a)


def Cm(f, cls_name, meth):
    a, b = m(f, cls_name, meth)
    return C(f, a, b)


def Lin(f, pat, after=1):
    return C(f, ln(f, pat, after))


# ---------------------------------------------------------------- registry class table

def _class_get_name(path):
    """The constant get_name() of the class a registry path names, looked up by AST; None if unresolved."""
    mod, _, clsname = path.rpartition(".")
    f = mod.replace(".", "/") + ".py"
    try:
        src = "\n".join(lines(f))
    except FileNotFoundError:
        return None
    tree = ast.parse(src)
    classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}

    def look(name, depth=0):
        c = classes.get(name)
        if c is None or depth > 3:
            return None
        for n in c.body:
            if isinstance(n, ast.FunctionDef) and n.name == "get_name":
                for r in ast.walk(n):
                    if isinstance(r, ast.Return) and isinstance(r.value, ast.Constant) and isinstance(r.value.value, str):
                        return r.value.value
        for b in c.bases:
            if isinstance(b, ast.Name):
                got = look(b.id, depth + 1)
                if got:
                    return got
        return None
    return look(clsname)


def _enum_members(f, enum_cls):
    """{NAME: path or None} of an Enum class, from its string (or None) class attributes."""
    tree = ast.parse("\n".join(lines(f)))
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == enum_cls:
            out = {}
            for s in n.body:
                if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
                    v = s.value
                    if isinstance(v, ast.Constant) and (v.value is None or isinstance(v.value, str)):
                        out[s.targets[0].id] = v.value or ""  # None (CUSTOM) kept as "": both refuse in get_path
                    elif isinstance(v, ast.JoinedStr) or isinstance(v, ast.BinOp):
                        pass
            return out
    raise SystemExit(f"enum not found {enum_cls}")


def _registry_classes(members, extra=None):
    out = {}
    for name, path in members.items():
        if not path:
            continue
        got = _class_get_name(path)
        out[path] = {"name": got}
        if extra is not None:
            # MLAPrefillBackend's class defaults: any capability, fp16/bf16, available, any MLA dims.
            out[path].update({"capability_majors": [], "dtypes": ["float16", "bfloat16"], "available": True, "mla_dimensions": []})
            out[path].update(extra.get(name, {}))
    return out


PREFILL_CAPS = {
    # MLAPrefillBackend subclasses: supports_compute_capability, supported_dtypes, is_available (on the
    # CUDA deployment: vllm_flash_attn and flashinfer ship with the wheel; tokenspeed_mla is an extra
    # package, so not installed), supported_mla_dimensions as [nope, rope, v].
    "FLASH_ATTN": {"capability_majors": [], "dtypes": ["float16", "bfloat16"], "available": True,
                   "mla_dimensions": [[128, 64, 128], [192, 64, 256], [64, 64, 128], [256, 0, 256]]},
    "FLASHINFER": {"capability_majors": [10], "dtypes": ["float16", "bfloat16"], "available": True, "mla_dimensions": [[128, 64, 128]]},
    "TRTLLM_RAGGED": {"capability_majors": [10], "dtypes": ["float16", "bfloat16"], "available": True,
                      "mla_dimensions": [[128, 64, 128], [192, 64, 256]]},
    "TOKENSPEED_MLA": {"capability_majors": [10], "dtypes": ["float16", "bfloat16"], "available": False, "mla_dimensions": [[128, 64, 128]]},
    "ROCM_AITER_FA": {"capability_majors": [-1], "dtypes": ["float16", "bfloat16"], "available": False, "mla_dimensions": []},
}


# ---------------------------------------------------------------- components

def components():
    out = []
    out.append(comp("kv-quant-mode", "KVQuantMode", KVI,
                    "KVQuantMode and get_kv_quant_mode (kv_cache_interface.py): the KV-cache quantization mode of a kv_cache_dtype string, which backends and kernels dispatch on.",
                    a=cls(KVI, "KVQuantMode")[0], b=fn(KVI, "is_quantized_kv_cache")[1]))
    a, b = cls(BK, "CommonAttentionMetadata")
    out.append(comp("common-attention-metadata", "CommonAttentionMetadata", BK,
                    "Per-batch attention metadata shared across layers and backends: batch size, query lengths, computed tokens, token->request map, unpadding.",
                    a=a, b=b))
    out.append(comp("attention-impl-base", "AttentionImplBase", BK, "Base of every attention impl: __new__ binds the DCP/PCP world sizes and ranks.",
                    a=cls(BK, "AttentionImplBase")[0], b=cls(BK, "AttentionImplBase")[0]))
    cg = {"FLASH_ATTN": "dynamic", "FLASHINFER": "dynamic", "TRITON_ATTN": "ALWAYS", "ROCM_ATTN": "ALWAYS", "FLEX_ATTENTION": "ALWAYS",
          "FLASHINFER_MLA": "ALWAYS", "FLASHMLA": "UNIFORM_BATCH", "TRITON_MLA": "UNIFORM_BATCH", "FLASH_ATTN_MLA": "UNIFORM_BATCH",
          "FLASHINFER_MLA_SPARSE": "UNIFORM_BATCH", "FLASHMLA_SPARSE": "UNIFORM_BATCH", "FLASH_ATTN_MLA_SPARSE": "UNIFORM_BATCH",
          "TOKENSPEED_MLA": "UNIFORM_BATCH", "TURBOQUANT": "UNIFORM_BATCH", "ROCM_AITER_FA": "UNIFORM_BATCH", "ROCM_AITER_MLA": "UNIFORM_BATCH",
          "ROCM_AITER_MLA_SPARSE": "UNIFORM_BATCH", "B12X": "UNIFORM_BATCH", "GDN_ATTN": "UNIFORM_BATCH", "MAMBA": "UNIFORM_BATCH",
          "SHORT_CONV_ATTN": "UNIFORM_BATCH", "DEEPSEEK_SPARSE_SWA": "UNIFORM_BATCH", "HPC_ATTN": "UNIFORM_SINGLE_TOKEN_DECODE",
          "LINEAR_ATTN": "UNIFORM_SINGLE_TOKEN_DECODE", "XPU_MLA_SPARSE": "NEVER",
          # DeepSeek V4 (models-layers' files): the ROCm AITER sparse-MLA builder inherits DeepseekV4SparseMLAMetadataBuilder's
          # UNIFORM_BATCH (sparse_mla.py:125); the FlashInfer varlen builder is ALWAYS (nvidia/flashinfer_sparse.py:186).
          "ROCM_FLASHMLA_SPARSE_DSV4": "UNIFORM_BATCH", "FLASHINFER_MLA_SPARSE_DSV4": "ALWAYS"}
    out.append(comp("attention-metadata-builder", "AttentionMetadataBuilder", BK,
                    "Base of the metadata builders: the class-level CUDA-graph support (state: each builder class's _cudagraph_support).",
                    a=cls(BK, "AttentionMetadataBuilder")[0], b=cls(BK, "AttentionMetadataBuilder")[0],
                    state={"schema": obj({"cg_support": {"type": "object"}}), "initial": {"cg_support": cg}}))
    # registries
    am = _enum_members(REG, "AttentionBackendEnum")
    mm = _enum_members(REG, "MambaAttentionBackendEnum")
    pm = _enum_members(PREG, "MLAPrefillBackendEnum")
    racy = lambda f, chk, wr: (f"{f}:{ln(f, chk)} checks the member map and {f}:{ln(f, wr)} inserts into it, unlocked "
                                "(registration runs at import or plugin-load time, normally on one thread)")
    for cid, name, f, members, classes, summ in [
        ("attention-backend-enum", "AttentionBackendEnum", REG, am, _registry_classes(am),
         "The attention backend registry: enum members (name -> class path), runtime overrides (_ATTN_OVERRIDES) and the importable classes' get_name()."),
        ("mamba-attention-backend-enum", "MambaAttentionBackendEnum", REG, mm, _registry_classes(mm),
         "The mamba attention backend registry (_MAMBA_ATTN_OVERRIDES)."),
        ("mla-prefill-backend-enum", "MLAPrefillBackendEnum", PREG, pm, _registry_classes(pm, PREFILL_CAPS),
         "The MLA prefill backend registry (_MLA_PREFILL_OVERRIDES); class rows carry each prefill backend's capability gates."),
    ]:
        a, b = cls(f, name)
        out.append(comp(cid, name, f, summ, a=a, b=a,
                        state={"schema": obj({"members": {"type": "object"}, "overrides": {"type": "object"}, "classes": {"type": "object"}}),
                               "initial": {"members": members, "overrides": {}, "classes": classes}},
                        attributes={"racy_in_code": racy(f, r"if name in cls\._member_map_:", r"cls\._member_map_\[name\] = member")}))
    out.append(comp("mla-prefill-selector", "prefill/selector.py", PSEL, "Selects the MLA prefill backend: an explicit AttentionConfig.mla_prefill_backend, else the platform's priority list.",
                    a=fn(PSEL, "get_mla_prefill_backend")[0], b=fn(PSEL, "_auto_select_mla_prefill_backend")[1]))
    out.append(comp("mla-attention", "MLAAttention", MLAA, "The MLA attention layer (models-layers' file): its KV-cache spec, KV-cache binding and chunked-prefill workspace size.",
                    a=cls(MLAA, "MLAAttention")[0], b=cls(MLAA, "MLAAttention")[0]))
    a, b = cls(SM90, "FlashInferMLASparseSM90Builder")
    out.append(comp("flashinfer-mla-sparse-sm90-builder", "FlashInferMLASparseSM90Builder", SM90,
                    "SM90 FlashInfer sparse-MLA metadata builder: per-row KV lengths and the host-side plan of the rows routed to MQA.", a=a, b=b))
    out.append(comp("flashinfer-mla-sparse-backend", "FlashInferMLASparseTRTLLMBackend", FIMS,
                    "FlashInfer sparse MLA backend (TRT-LLM gen, SM100): class capabilities and supports_combination.",
                    a=cls(FIMS, "FlashInferMLASparseTRTLLMBackend")[0], b=cls(FIMS, "FlashInferMLASparseTRTLLMBackend")[1]))
    out.append(comp("flashmla-sparse-backend", "FlashMLASparseBackend", FMS, "FlashMLA sparse backend (SM90/SM100): class capabilities and supports_combination.",
                    a=cls(FMS, "FlashMLASparseBackend")[0], b=cls(FMS, "FlashMLASparseBackend")[1]))
    a, b = cls(IG, "SparseMLAIndexGroupBuilder")
    out.append(comp("sparse-mla-index-group-builder", "SparseMLAIndexGroupBuilder", IG,
                    "Assigns sparse-MLA layers to the index-producing layer's group, and converts each group's top-k indices once (state: the groups).",
                    a=a, b=b,
                    state={"schema": obj({"groups": {"type": "object"}, "current_group": {"type": ["string", "null"]}, "num_groups": {"type": "integer"},
                                          "max_decode_rows": {"type": "integer"}, "logical_rows": {"type": "integer"}}),
                           "initial": {"groups": {}, "current_group": None, "num_groups": 0, "max_decode_rows": 0, "logical_rows": 0}},
                    attributes={"racy_in_code": f"{IG}:{ln(IG, r'if is_index_producing_layer or self.current_group is None:')} reads current_group and "
                                                f"{IG}:{ln(IG, r'self.current_group = group_cls\(')} assigns it unlocked; layers register during model construction on one thread"}))
    out.append(comp("rocm-aiter-mla", "rocm_aiter_mla.py", RAM, "ROCm AITER MLA backend module: decode-route predicates and the page-index expansion kernel.",
                    a=fn(RAM, "_segmented_dcp_verify_supported")[0], b=fn(RAM, "_select_dcp_decode_route")[1]))
    out.append(comp("aiter-mla-helper", "AiterMLAHelper", RAM, "AITER MLA head padding and the Gluon-vs-asm decode routing predicates.",
                    a=cls(RAM, "AiterMLAHelper")[0], b=cls(RAM, "AiterMLAHelper")[1]))
    out.append(comp("rocm-aiter-mla-sparse-ops", "ops/rocm_aiter_mla_sparse.py", RAMS, "ROCm sparse-MLA ops: per-sequence context lengths and the ragged Triton prefill.",
                    a=fn(RAMS, "_per_sequence_context_lens")[0], b=fn(RAMS, "_per_sequence_context_lens")[1]))
    for c in out:
        if c["id"] in ("rocm-aiter-mla", "aiter-mla-helper", "rocm-aiter-mla-sparse-ops"):
            c["summary"] += " ROCm-only: the fixtures deploy on CUDA, so only scenarios reach it."
    return out


# ---------------------------------------------------------------- interfaces

def configs():
    return [
        {"id": "attention-backend-per-kind", "type": "object", "value": {}, "default": {},
         "summary": "AttentionConfig.backend_per_kind: per-KV-cache-group backend overrides keyed by KVCacheSpecKind value (full_attention, mla_attention, sliding_window, ...); empty unless set",
         "sources": [Lin(CFG_ATT, r"backend_per_kind: dict\[str, AttentionBackendEnum\]"), Cfn(CFG_ATT, "validate_backend_per_kind_before")],
         "attributes": {"key": "backend_per_kind"}},
        {"id": "vllm-rocm-aiter-mla-asm-padding", "type": "string", "value": "auto", "default": "auto",
         "summary": "VLLM_ROCM_AITER_MLA_ASM_PADDING: small-head AITER MLA decode kernel choice (auto | gluon | asm)",
         "sources": [Lin("vllm/envs.py", r"VLLM_ROCM_AITER_MLA_ASM_PADDING: Literal"), Cfn(RAM, "_aiter_mla_small_head_mode")],
         "attributes": {"key": "VLLM_ROCM_AITER_MLA_ASM_PADDING", "boundary": True, "owner": "config-platform"}},
        {"id": "cp-kv-cache-interleave-size", "type": "integer", "value": 1, "default": 1,
         "summary": "cp_kv_cache_interleave_size: tokens per DCP/PCP round-robin interleave (aligns the MLA chunked-context workspace under DCP)",
         "sources": [Lin("vllm/config/parallel.py", r"cp_kv_cache_interleave_size: int = ")],
         "attributes": {"key": "cp_kv_cache_interleave_size", "boundary": True, "owner": "config-platform"}},
    ]


def selector_kind():
    a, b = fn(SEL, "get_attn_spec_kind")
    beh = [
        {"if": "input.attn_type == 'encoder_only'", "then": [{"title": "Encoder-only layers", "source": Lin(SEL, r"return KVCacheSpecKind.ENCODER_ONLY_ATTENTION"), "return": {"kind": "encoder_only_attention"}}]},
        {"if": "input.attn_type == 'encoder_decoder'", "then": [{"title": "Cross-attention layers", "source": Lin(SEL, r"return KVCacheSpecKind.CROSS_ATTENTION"), "return": {"kind": "cross_attention"}}]},
        {"if": "input.use_mla", "then": [{"title": "MLA, with or without a sliding window", "source": C(SEL, ln(SEL, r"if use_mla:", a), ln(SEL, r"return KVCacheSpecKind.MLA_ATTENTION")),
                                          "return": {"kind": "= input.has_sliding_window ? 'sliding_window_mla' : 'mla_attention'"}}]},
        {"title": "Dense: sliding window or full (sinks don't change the kind)", "source": C(SEL, ln(SEL, r"if has_sliding_window:", ln(SEL, r"return KVCacheSpecKind.MLA_ATTENTION")), b),
         "return": {"kind": "= input.has_sliding_window ? 'sliding_window' : 'full_attention'"}},
    ]
    return iface("selector", "get-attn-spec-kind", "get_attn_spec_kind: the KV-cache group kind (KVCacheSpecKind value) a layer maps to, from its MLA, sliding-window and attention-type signals.",
                 [C(SEL, a, b), C(KVI, cls(KVI, "KVCacheSpecKind")[0], cls(KVI, "KVCacheSpecKind")[1]), C(BK, *cls(BK, "AttentionType"))], beh,
                 request=obj({"use_mla": B(False), "has_sliding_window": B(False), "attn_type": S("decoder", enum=["decoder", "encoder", "encoder_only", "encoder_decoder"])}),
                 response=obj({"kind": {"type": "string"}}))


QM = ("(D == 'int4_per_token_head' ? 'int4_per_token_head' : (D == 'int8_per_token_head' ? 'int8_per_token_head' : (D == 'fp8_per_token_head' ? 'fp8_per_token_head'"
      " : (D == 'nvfp4_ds_mla' ? 'nvfp4_ds_mla' : (D.startsWith('nvfp4') ? 'nvfp4' : (D.startsWith('turboquant_') ? D : (D == 'ultraquant_4bit' ? 'ultraquant_4bit'"
      " : (D.startsWith('fp8') ? 'fp8_per_tensor' : 'none'))))))))")


def kv_spec_interfaces():
    out = []
    # get_kv_quant_mode + KVQuantMode properties
    ga, gb = fn(KVI, "get_kv_quant_mode")
    ka, kb = cls(KVI, "KVQuantMode")
    beh = [
        {"if": "input.kv_cache_dtype.startsWith('turboquant_') && !(input.kv_cache_dtype in ['turboquant_k8v4', 'turboquant_4bit_nc', 'turboquant_k3v4_nc', 'turboquant_3bit_nc'])",
         "then": [{"title": "turboquant_* is looked up by name (KVQuantMode[...upper()]): an unknown preset raises KeyError",
                   "source": C(KVI, ln(KVI, r"return KVQuantMode\[kv_cache_dtype\.upper\(\)\]", ga)),
                   "fail": {"code": "key-error", "message": "= \"'\" + input.kv_cache_dtype.upperAscii() + \"'\""}}]},
        {"title": "Map the kv_cache_dtype string to a KVQuantMode (nvfp4_ds_mla before the nvfp4 prefix; turboquant_* by name; any other fp8* is per-tensor)",
         "source": C(KVI, ga, gb), "set": {"vars.mode": "= " + QM.replace("D", "input.kv_cache_dtype")}},
        {"title": "The mode's family properties", "source": C(KVI, ln(KVI, r"def is_per_token_head", ka), kb),
         "return": {"kv_quant_mode": "= vars.mode", "is_quantized": "= vars.mode != 'none'",
                    "is_per_token_head": "= vars.mode in ['int8_per_token_head', 'fp8_per_token_head', 'int4_per_token_head']",
                    "is_nvfp4": "= vars.mode == 'nvfp4'", "is_turboquant": "= vars.mode.startsWith('turboquant_')", "is_ultraquant": "= vars.mode == 'ultraquant_4bit'"}},
    ]
    out.append(iface("kv-quant-mode", "get-kv-quant-mode", "get_kv_quant_mode / is_quantized_kv_cache: the KVQuantMode of a kv_cache_dtype string, and its family flags.",
                     [C(KVI, ga, gb), C(KVI, ka, kb), Cfn(KVI, "is_quantized_kv_cache"), Cm(BK, "AttentionImpl", "kv_quant_mode")], beh,
                     request=obj({"kv_cache_dtype": S("auto")}),
                     response=obj({"kv_quant_mode": {"type": "string"}, "is_quantized": {"type": "boolean"}}),
                     errors=[err("key-error", "an unknown turboquant_* preset")]))
    return out


def metadata_interfaces():
    out = []
    md = obj({"query_start_loc": A([0, 3, 4, 6]), "seq_lens": A([10, 5, 2]), "num_actual_tokens": I(6)})
    out.append(iface("common-attention-metadata", "batch-size", "CommonAttentionMetadata.batch_size / naive_query_lens / compute_num_computed_tokens: rows, per-row query lengths (query_start_loc differences) and computed tokens (seq_lens - query lengths).",
                     [Cm(BK, "CommonAttentionMetadata", "batch_size"), Cm(BK, "CommonAttentionMetadata", "naive_query_lens"), Cm(BK, "CommonAttentionMetadata", "compute_num_computed_tokens")],
                     [{"title": "Query lengths: neighbouring query_start_loc entries", "source": Cm(BK, "CommonAttentionMetadata", "naive_query_lens"),
                       "set": {"vars.q": "= lists.range(size(input.query_start_loc) - 1).map(i, input.query_start_loc[i + 1] - input.query_start_loc[i])"}},
                      {"set": {"vars.ns": "= size(input.seq_lens)", "vars.nq": "= size(input.query_start_loc) - 1"}},
                      {"if": "vars.nq != vars.ns && vars.nq != 1 && vars.ns != 1",
                       "then": [{"title": "seq_lens - query_lens: torch can't broadcast tensors of different lengths", "source": C(BK, ln(BK, r"self\._num_computed_tokens_cache = self\.seq_lens - query_lens")),
                                 "fail": {"code": "runtime-error", "message": "= 'The size of tensor a (' + string(vars.ns) + ') must match the size of tensor b (' + string(vars.nq) + ') at non-singleton dimension 0'"}}]},
                      {"title": "batch_size is seq_lens.shape[0]; computed tokens are seq_lens - query lengths (a length-1 side broadcasts)", "source": Cm(BK, "CommonAttentionMetadata", "compute_num_computed_tokens"),
                       "return": {"batch_size": "= vars.ns", "query_lens": "= vars.q",
                                  "num_computed_tokens": "= lists.range(math.greatest(vars.ns, vars.nq)).map(i, input.seq_lens[vars.ns == 1 ? 0 : i] - vars.q[vars.nq == 1 ? 0 : i])"}}],
                     request=md, response=obj({"batch_size": {"type": "integer"}, "query_lens": ARR_I, "num_computed_tokens": ARR_I}),
                     errors=[err("runtime-error", "seq_lens and query_start_loc disagree on the batch size")]))
    ta, tb = m(BK, "CommonAttentionMetadata", "token_to_req_indices")
    beh = [
        {"set": {"vars.mapped": "= input.query_start_loc_cpu[size(input.query_start_loc_cpu) - 1]",
                 "vars.n": "= input.num_actual_tokens"}},
        {"set": {"vars.out": "= vars.mapped > vars.n ? vars.mapped : vars.n"}},
        {"if": "input.buffer_size < vars.out",
         "then": [{"title": "The buffer must hold max(mapped, actual) tokens", "source": Lin(BK, r"assert buffer.shape\[0\] >= num_output_tokens"),
                   "fail": {"code": "assertion-error", "message": ""}}]},
        {"title": "compute_token_to_req_indices on the device query_start_loc: tokens past the mapped count map to 0", "source": Cfn(MD, "compute_token_to_req_indices"),
         "call": "attention-ops-metadata.token-request-mapping-kernel", "input": {"num_tokens": "= vars.out", "num_seqs": "= size(input.query_start_loc) - 1"}},
        {"title": "Cached on the metadata and sliced to num_actual_tokens", "source": C(BK, ln(BK, r"self\._token_to_req_indices_cache = compute_token_to_req_indices", ta), tb),
         "return": {"token_to_req": "= lists.range(vars.n).map(t, t >= vars.mapped ? 0 : size(input.query_start_loc.slice(1, size(input.query_start_loc)).filter(e, e <= t)))"}},
    ]
    out.append(iface("common-attention-metadata", "token-to-req-indices", "CommonAttentionMetadata.token_to_req_indices: the request index of each of the first num_actual_tokens tokens, from the device query_start_loc (padding tokens map to 0).",
                     [C(BK, ta, tb)], beh,
                     request=obj({"query_start_loc": A([0, 3, 4, 6]), "query_start_loc_cpu": A([0, 3, 4, 6]), "num_actual_tokens": I(6), "buffer_size": I(8192)}),
                     response=obj({"token_to_req": ARR_I}), errors=[err("assertion-error", "buffer too small")]))
    ua, ub = m(BK, "CommonAttentionMetadata", "unpadded")
    out.append(iface("common-attention-metadata", "unpadded", "CommonAttentionMetadata.unpadded: slice the per-request tensors to the real requests and the slot mapping to the real tokens (CUDA-graph padding removed).",
                     [C(BK, ua, ub)],
                     [{"if": "input.num_actual_reqs > size(input.seq_lens) || input.num_actual_tokens > size(input.slot_mapping)",
                       "then": [{"title": "Slicing never grows: an over-long cut keeps every row", "source": C(BK, ua, ub), "set": {"vars.clamped": True}}],
                       "else": [{"set": {"vars.clamped": False}}]},
                      {"title": "Per-request fields cut to num_actual_reqs, slot_mapping to num_actual_tokens", "source": C(BK, ln(BK, r"query_start_loc=self\.query_start_loc\[: num_actual_reqs \+ 1\]", ua), ub),
                       "return": {"num_reqs": "= input.num_actual_reqs", "num_actual_tokens": "= input.num_actual_tokens",
                                  "query_start_loc": "= input.query_start_loc.slice(0, math.least(input.num_actual_reqs + 1, size(input.query_start_loc)))",
                                  "seq_lens": "= input.seq_lens.slice(0, math.least(input.num_actual_reqs, size(input.seq_lens)))",
                                  "slot_mapping": "= input.slot_mapping.slice(0, math.least(input.num_actual_tokens, size(input.slot_mapping)))",
                                  "clamped": "= vars.clamped"}}],
                     request=obj({"query_start_loc": A([0, 1, 2, 2, 2]), "seq_lens": A([7, 9, 0, 0]), "slot_mapping": A([6, 24, -1, -1]),
                                  "num_actual_reqs": I(2), "num_actual_tokens": I(2)}),
                     response=obj({"num_reqs": {"type": "integer"}, "seq_lens": ARR_I, "slot_mapping": ARR_I})))
    # AttentionImplBase.__new__
    na, nb = m(BK, "AttentionImplBase", "__new__")
    beh = [
        {"title": "Replicated drafts run at DCP=1 inside a DCP target: the group is consulted only when the config enables DCP (or there is no config)",
         "source": C(BK, ln(BK, r"config = get_current_vllm_config_or_none\(\)", na), ln(BK, r"config is None or config\.parallel_config\.decode_context_parallel_size > 1", na)),
         "set": {"vars.enabled": "= !input.has_vllm_config || int(config['decode-context-parallel-size']) > 1"}},
        {"if": "vars.enabled && input.dcp_group_initialized",
         "then": [{"title": "get_dcp_world_size_and_rank: the DCP group's size and rank", "source": Cfn("vllm/distributed/parallel_state.py", "get_dcp_world_size_and_rank"),
                   "set": {"vars.dcp": "= input.dcp_world_size", "vars.dcp_rank": "= input.dcp_rank"}}],
         "else": [{"title": "Disabled or uninitialized (unit tests): (1, 0)", "source": Lin("vllm/distributed/parallel_state.py", r"if not enabled or _DCP is None:"),
                   "set": {"vars.dcp": 1, "vars.dcp_rank": 0}}]},
        {"if": "input.pcp_group_initialized",
         "then": [{"title": "The PCP group's size and rank", "source": C(BK, ln(BK, r"self\.pcp_world_size = get_pcp_group\(\)\.world_size", na)),
                   "set": {"vars.pcp": "= input.pcp_world_size", "vars.pcp_rank": "= input.pcp_rank"}}],
         "else": [{"title": "get_pcp_group asserts when there is no PCP group: (1, 0)", "source": C(BK, ln(BK, r"except AssertionError:", na)),
                   "set": {"vars.pcp": 1, "vars.pcp_rank": 0}}]},
        {"title": "Decode returns the LSE only under DCP, when the impl can", "source": C(BK, ln(BK, r"self\.need_to_return_lse_for_decode = \(", na), nb),
         "return": {"dcp_world_size": "= vars.dcp", "dcp_rank": "= vars.dcp_rank", "pcp_world_size": "= vars.pcp", "pcp_rank": "= vars.pcp_rank",
                    "total_cp_world_size": "= vars.dcp", "total_cp_rank": "= vars.dcp_rank",
                    "need_to_return_lse_for_decode": "= vars.dcp > 1 && input.can_return_lse_for_decode"}},
    ]
    out.append(iface("attention-impl-base", "new", "AttentionImplBase.__new__: every impl binds the DCP and PCP world sizes and ranks at construction, and whether decode returns its LSE.",
                     [C(BK, na, nb)], beh,
                     request=obj({"has_vllm_config": B(True), "dcp_group_initialized": B(False), "dcp_world_size": I(1), "dcp_rank": I(0),
                                  "pcp_group_initialized": B(False), "pcp_world_size": I(1), "pcp_rank": I(0), "can_return_lse_for_decode": B(True)}),
                     response=obj({"dcp_world_size": {"type": "integer"}, "need_to_return_lse_for_decode": {"type": "boolean"}})))
    # get_cudagraph_support
    ga, gb = m(BK, "AttentionMetadataBuilder", "get_cudagraph_support")
    fa_, fb_ = m(FA, "FlashAttentionMetadataBuilder", "get_cudagraph_support")
    fia, fib = m(FI, "FlashInferMetadataBuilder", "get_cudagraph_support")
    ea, eb = cls(BK, "AttentionCGSupport")
    lvl = "{'NEVER': 0, 'UNIFORM_SINGLE_TOKEN_DECODE': 1, 'UNIFORM_BATCH': 2, 'ALWAYS': 3}"
    V4R = "vllm/models/deepseek_v4/amd/rocm.py"
    SSWA = "vllm/v1/attention/backends/mla/sparse_swa.py"
    r1a, r1b = m(V4R, "DeepseekV4ROCMAiterMLASparseMetadataBuilder", "get_cudagraph_support")
    r2a, r2b = m(V4R, "DeepseekV4ROCMAiterSparseSWAMetadataBuilder", "get_cudagraph_support")
    swa_a, swa_b = m(SSWA, "DeepseekSparseSWABackend", "get_builder_cls")
    beh = [
        {"if": "(input.backend == 'ROCM_FLASHMLA_SPARSE_DSV4' || (input.backend == 'DEEPSEEK_SPARSE_SWA' && input.is_rocm)) && config['enable-adaptive-verification']",
         "then": [{"title": "DeepSeek V4's ROCm AITER sparse-MLA and SWA builders (DEEPSEEK_SPARSE_SWA's builder on ROCm): adaptive verification replays varlen FULL decode graphs, so ALWAYS",
                   "source": C(V4R, r1a, r1b), "detail": "Without speculative_config.enable_adaptive_verification both fall back to their parents' UNIFORM_BATCH.",
                   "set": {"vars.s": "ALWAYS"}}],
         "else": [{"if": "input.backend == 'FLASH_ATTN'",
         "then": [{"if": "input.fa_version == null",
                   "then": [{"title": "_cudagraph_support is fixed at class definition by get_flash_attn_version()", "source": C(FA, ln(FA, r"_cudagraph_support = \(") + 2),
                             "call": "fa-utils.get-flash-attn-version", "input": {}, "as": "v"},
                            {"set": {"vars.fa": "= vars.v.value.fa_version"}}],
                   "else": [{"set": {"vars.fa": "= input.fa_version"}}]},
                  {"title": "FlashAttention: ALWAYS with FA3 (AOT scheduling), else UNIFORM_BATCH", "source": C(FA, ln(FA, r"_cudagraph_support = \("), ln(FA, r"_cudagraph_support = \(") + 4),
                   "set": {"vars.s": "= vars.fa == 3 ? 'ALWAYS' : 'UNIFORM_BATCH'"}}],
         "else": [{"if": "input.backend == 'FLASHINFER'",
                   "then": [{"if": "int(config['decode-context-parallel-size']) > 1",
                             "then": [{"title": "FlashInfer under DCP: XQA has no LSE and trtllm-gen can't graph varlen", "source": C(FI, ln(FI, r"if vllm_config\.parallel_config\.decode_context_parallel_size > 1:", fia)),
                                       "set": {"vars.s": "UNIFORM_SINGLE_TOKEN_DECODE"}}],
                             "else": [{"title": "Uniform batches when every attention spec runs on TRT-LLM (or XQA) and the layer is causal or the arch is XQA", "source": C(FI, fia, fib),
                                       "set": {"vars.s": "= input.all_specs_trtllm && (!input.use_non_causal || input.is_xqa_arch) ? 'UNIFORM_BATCH' : 'UNIFORM_SINGLE_TOKEN_DECODE'"}}]}],
                   "else": [{"title": "The builder class's _cudagraph_support; a builder that sets none inherits NEVER", "source": C(BK, ga, gb),
                             "set": {"vars.s": "= input.backend in state.cg_support ? state.cg_support[input.backend] : 'NEVER'"}}]}]}]},
        {"title": "AttentionCGSupport levels: ALWAYS 3 > UNIFORM_BATCH 2 > UNIFORM_SINGLE_TOKEN_DECODE 1 > NEVER 0", "source": C(BK, ea, eb),
         "return": {"support": "= vars.s", "level": "= " + lvl + "[vars.s]"}},
    ]
    out.append(iface("attention-metadata-builder", "get-cudagraph-support", "AttentionMetadataBuilder.get_cudagraph_support: the CUDA-graph support level of a backend's builder (FlashAttention and FlashInfer decide at run time).",
                     [C(BK, ga, gb), C(FA, fa_, fb_), C(FI, fia, fib), C(BK, ea, eb), Lin(TA, r"_cudagraph_support: ClassVar\[AttentionCGSupport\] = AttentionCGSupport\.ALWAYS"),
                      C(V4R, r1a, r1b), C(V4R, r2a, r2b), C(SSWA, swa_a, swa_b)], beh,
                     request=obj({"backend": S("FLASH_ATTN"), "fa_version": {"type": ["integer", "null"], "default": None}, "all_specs_trtllm": B(True), "use_non_causal": B(False),
                                  "is_xqa_arch": B(True), "is_rocm": B(False)}),
                     response=obj({"support": {"type": "string"}, "level": {"type": "integer"}})))
    return out


RESERVED = ["register", "get_path", "get_class", "is_overridden", "clear_override", "name", "value", "mro"]


def registry_interfaces():
    out = []
    for cid, f, enum_cls, label, reg_fn, reg_name in [
        ("attention-backend-enum", REG, "AttentionBackendEnum", "attention backend", "register_backend", "register-backend"),
        ("mamba-attention-backend-enum", REG, "MambaAttentionBackendEnum", "attention backend", "register_backend", "register-backend"),
        ("mla-prefill-backend-enum", PREG, "MLAPrefillBackendEnum", "MLA prefill backend", "register_mla_prefill_backend", "register-mla-prefill-backend"),
    ]:
        ca = cls(f, enum_cls)[0]
        meta = "_AttentionBackendEnumMeta" if f == REG else "_MLAPrefillBackendEnumMeta"
        gi_a, gi_b = m(f, meta, "__getitem__")
        ra, rb = fn(f, "register", ca)
        pa, pb = fn(f, "get_path", ca)
        ka, kb = fn(f, "get_class", ca)
        ia, ib = fn(f, "is_overridden", ca)
        xa, xb = fn(f, "clear_override", ca)
        unknown = ("= \"Unknown " + label + ": '\" + input.name + \"'. Valid options are: \" + state.members.map(k, k).join(', ')")
        out.append(iface(cid, "getitem", f"{enum_cls}[name] (the metaclass __getitem__): the member, or a ValueError listing the valid names. AttentionConfig's validators index it with the upper-cased string.",
                         [C(f, gi_a, gi_b)],
                         [{"if": "!(input.name in state.members)",
                           "then": [{"title": "Unknown name", "source": C(f, ln(f, r"except KeyError:", gi_a), gi_b), "fail": {"code": "value-error", "message": unknown}}]},
                          {"title": "The enum member", "source": C(f, ln(f, r"return super\(\)\.__getitem__\(name\)", gi_a)),
                           "return": {"name": "= input.name", "value": "= state.members[input.name]"}}],
                         request=obj({"name": S("FLASH_ATTN")}), response=obj({"name": {"type": "string"}, "value": {"type": ["string", "null"]}}),
                         errors=[err("value-error", "unknown member name")]))
        out.append(iface(cid, "register", f"{enum_cls}.register: add a member at run time; refuses an existing name and a non-identifier or reserved name.",
                         [C(f, ra, rb)],
                         [{"if": "input.name in state.members",
                           "then": [{"title": "The name already exists", "source": C(f, ln(f, r"if name in cls\._member_map_:", ra)),
                                     "fail": {"code": "value-error", "message": (("= 'Backend ' + input.name + ' already exists in " + enum_cls + ". Use register_backend(" + enum_cls + ".' + input.name + \", '\" + input.value + \"') to override.\"")
                                                                            if f == REG else ("= 'MLA prefill backend ' + input.name + ' already exists in " + enum_cls + ". Use register_mla_prefill_backend(" + enum_cls + ".' + input.name + \", '\" + input.value + \"') to override.\""))}}]},
                          {"if": "!input.name.matches('^[A-Za-z_][A-Za-z0-9_]*$') || input.name in " + str(RESERVED).replace('"', "'"),
                           "then": [{"title": "Not an identifier, or an attribute of the enum class", "source": C(f, ln(f, r"if not name\.isidentifier\(\) or hasattr\(cls, name\):", ra)),
                                     "fail": {"code": "value-error", "message": "= 'Invalid or reserved backend name: ' + input.name"}}]},
                          {"title": "Create the member and add it to the member and value maps", "source": C(f, ln(f, r"member = object\.__new__\(cls\)", ra), ln(f, r"cls\._member_names_\.append\(name\)", ra)),
                           "set": {"= 'state.members.' + input.name": "= input.value"}},
                          {"return": {"name": "= input.name", "value": "= input.value"}}],
                         request=obj({"name": S("CUSTOM_MLA"), "value": S("")}), response=obj({"name": {"type": "string"}}),
                         errors=[err("value-error", "existing, invalid or reserved name")]))
        out.append(iface(cid, "get-path", f"{enum_cls}.get_path: the override if registered, else the member's default path; an unregistered placeholder (CUSTOM) refuses.",
                         [C(f, pa, pb)],
                         [{"if": "!(input.name in state.members)",
                           "then": [{"title": "Not a member", "source": C(f, ca, ca), "fail": {"code": "key-error", "message": "= \"'\" + input.name + \"'\""}}]},
                          {"title": "The override wins over the default path", "source": C(f, ln(f, r"path = _\w+_OVERRIDES\.get\(self, self\.value\)", pa)),
                           "set": {"vars.path": "= input.name in state.overrides ? state.overrides[input.name] : state.members[input.name]"}},
                          {"if": "vars.path == null || vars.path == ''",
                           "then": [{"title": "Must be registered before use", "source": C(f, ln(f, r"if not path:", pa)),
                                     "fail": {"code": "value-error", "message": (("= 'Backend ' + input.name + ' must be registered before use. Use register_backend(Backend.' + input.name + \", 'your.module.YourClass')\"")
                                                                            if f == REG else ("= 'MLA prefill backend ' + input.name + ' must be registered before use. Use register_mla_prefill_backend(" + enum_cls + ".' + input.name + \", 'your.module.YourClass')\""))}}]},
                          {"return": {"path": "= input.include_classname ? vars.path : vars.path.substring(0, vars.path.lastIndexOf('.'))"}}],
                         request=obj({"name": S("FLASH_ATTN"), "include_classname": B(True)}), response=obj({"path": {"type": "string"}}),
                         errors=[err("key-error", "not a member"), err("value-error", "unregistered placeholder")]))
        out.append(iface(cid, "get-class", f"{enum_cls}.get_class: resolve_obj_by_qualname of get_path(); a path nothing can import is an ImportError.",
                         [C(f, ka, kb), Cfn("vllm/utils/import_utils.py", "resolve_obj_by_qualname")],
                         [{"title": "get_path", "source": C(f, ln(f, r"return resolve_obj_by_qualname\(self\.get_path\(\)\)", ka)),
                           "call": f"{cid}.get-path", "input": {"name": "= input.name", "include_classname": True}, "as": "p"},
                          {"if": "!(vars.p.value.path in state.classes)",
                           "then": [{"title": "importlib can't import the module or find the class", "source": Cfn("vllm/utils/import_utils.py", "resolve_obj_by_qualname"),
                                     "detail": "ModuleNotFoundError (an ImportError) for a missing module; the scenarios only use missing modules.",
                                     "fail": {"code": "import-error", "message": "= \"No module named '\" + vars.p.value.path.substring(0, vars.p.value.path.lastIndexOf('.')) + \"'\""}}]},
                          {"return": {"path": "= vars.p.value.path", "class_name": "= state.classes[vars.p.value.path].name", "cls": "= state.classes[vars.p.value.path]"}}],
                         request=obj({"name": S("FLASH_ATTN")}), response=obj({"path": {"type": "string"}, "class_name": {"type": ["string", "null"]}}),
                         errors=[err("import-error", "the class can't be imported")]))
        out.append(iface(cid, "is-overridden", f"{enum_cls}.is_overridden / clear_override: whether the member has a registered override; clear=true drops it, reverting to the default path.",
                         [C(f, ia, ib), C(f, xa, xb)],
                         [{"set": {"vars.was": "= input.name in state.overrides"}},
                          {"if": "input.clear",
                           "then": [{"title": "clear_override pops the override (no error when absent)", "source": C(f, ln(f, r"_\w+_OVERRIDES\.pop\(self, None\)", xa)),
                                     "set": {"state.overrides": "= omit(state.overrides, input.name)"}}]},
                          {"title": "is_overridden: membership of the override map", "source": C(f, ln(f, r"return self in _\w+_OVERRIDES", ia)),
                           "return": {"overridden": "= vars.was && !input.clear"}}],
                         request=obj({"name": S("FLASH_ATTN"), "clear": B(False)}), response=obj({"overridden": {"type": "boolean"}})))
        # module-level register function
        rfa, rfb = fn(f, reg_fn)
        is_mamba = cid == "mamba-attention-backend-enum"
        beh = [
            {"if": "input.is_new",
             "then": [{"title": "A string backend name registers a new member (an empty path until the decorator or class_path sets one)",
                       "source": C(f, ln(f, r"if isinstance\(backend, str\):", rfa)),
                       "call": f"{cid}.register", "input": {"name": "= input.backend", "value": "= input.has_class_path ? input.class_path : ''"}}],
             "else": [{"if": "!(input.backend in state.members)",
                       "then": [{"title": "An enum member is expected", "source": C(f, rfa, rfa), "fail": {"code": "key-error", "message": "= \"'\" + input.backend + \"'\""}}]}]},
            {"if": "input.has_class_path",
             "then": [{"title": "Direct registration: the override is the given class path, and a no-op decorator is returned",
                       "source": C(f, ln(f, r"if class_path is not None:", rfa), ln(f, r"return lambda x: x", rfa)),
                       "set": {"= 'state.overrides.' + input.backend": "= input.class_path"}},
                      {"return": {"backend": "= input.backend", "decorator": False, "path": "= input.class_path"}}]},
            {"if": "input.decorated_class != ''",
             "then": [{"title": "Decorator form: the override is the decorated class's module.qualname", "source": C(f, ln(f, r"def decorator\(cls: type\) -> type:", rfa), ln(f, r"return cls", rfa)),
                       "set": {"= 'state.overrides.' + input.backend": "= input.decorated_class"}},
                      {"return": {"backend": "= input.backend", "decorator": True, "path": "= input.decorated_class"}}]},
            {"return": {"backend": "= input.backend", "decorator": True, "path": None}},
        ]
        out.append(iface(cid, reg_name, f"{reg_fn}{' (is_mamba=True)' if is_mamba else ''}: override an existing member or register a new one by name, directly (class_path) or as a class decorator.",
                         [C(f, rfa, rfb)], beh,
                         request=obj({"backend": S("CUSTOM"), "is_new": B(False), "has_class_path": B(False), "class_path": S(""), "decorated_class": S("")}),
                         response=obj({"backend": {"type": "string"}, "decorator": {"type": "boolean"}, "path": {"type": ["string", "null"]}}),
                         errors=[err("value-error", "the new name exists or is invalid"), err("key-error", "not a member")]))
    # MLAPrefillBackend.validate_configuration
    va, vb = m(PBASE, "MLAPrefillBackend", "validate_configuration")
    cls_row = "input.backend_cls"
    beh = [
        {"set": {"vars.r": []}},
        {"if": f"!input.has_device_capability || (size({cls_row}.capability_majors) > 0 && !(input.device_capability.major in {cls_row}.capability_majors))",
         "then": [{"title": "Compute capability not supported (or unknown)", "source": C(PBASE, ln(PBASE, r"if not cls\.supports_compute_capability\(device_capability\):", va), ln(PBASE, r"f\"\{device_capability\.minor\} not supported\"", va)),
                   "set": {"vars.r": "= vars.r + [input.has_device_capability ? 'compute capability ' + string(input.device_capability.major) + '.' + string(input.device_capability.minor) + ' not supported' : 'device capability not available']"}}]},
        {"if": f"!(input.dtype in {cls_row}.dtypes)",
         "then": [{"title": "dtype not supported", "source": C(PBASE, ln(PBASE, r"if not cls\.supports_dtype\(selector_config\.dtype\):", va)),
                   "set": {"vars.r": "= vars.r + ['dtype ' + input.dtype + ' not supported']"}}]},
        {"if": f"!{cls_row}.available",
         "then": [{"title": "Dependencies missing", "source": C(PBASE, ln(PBASE, r"if not cls\.is_available\(\):", va)),
                   "set": {"vars.r": "= vars.r + ['required dependencies not available']"}}]},
        {"if": f"size({cls_row}.mla_dimensions) > 0 && !(input.mla_dimensions in {cls_row}.mla_dimensions)",
         "then": [{"title": "MLA dimensions not supported", "source": C(PBASE, ln(PBASE, r"if not cls\.supports_mla_dimensions\(mla_dimensions\):", va), vb - 1),
                   "set": {"vars.r": "= vars.r + ['Model does not have supported MLA dimensions']"}}]},
        {"return": {"invalid_reasons": "= vars.r"}},
    ]
    out.append(iface("mla-prefill-backend", "validate-configuration", "MLAPrefillBackend.validate_configuration: the reasons a prefill backend class can't serve this device, dtype and MLA head layout.",
                     [C(PBASE, va, vb), Cm(PBASE, "MLAPrefillBackend", "supports_mla_dimensions")], beh,
                     request=obj({"backend_cls": obj({"name": {"type": ["string", "null"]}, "capability_majors": ARR_I, "dtypes": {"type": "array"}, "available": {"type": "boolean"},
                                                       "mla_dimensions": {"type": "array"}}, default={"name": "FLASH_ATTN", "capability_majors": [], "dtypes": ["float16", "bfloat16"],
                                                                                                       "available": True, "mla_dimensions": []}),
                                  "has_device_capability": B(True), "device_capability": obj({"major": I(9), "minor": I(0)}), "dtype": S("bfloat16"),
                                  "mla_dimensions": A([128, 64, 128])}),
                     response=obj({"invalid_reasons": {"type": "array", "items": {"type": "string"}}})))
    # get_mla_prefill_backend
    sa, sb = fn(PSEL, "get_mla_prefill_backend")
    aa, ab = fn(PSEL, "_auto_select_mla_prefill_backend")
    beh = [
        {"title": "MLAPrefillSelectorConfig: the model dtype and its (qk_nope, qk_rope, v) head dims; defaults without a model config",
         "source": C(PSEL, ln(PSEL, r"model_config = vllm_config\.model_config if vllm_config is not None else None", sa), ln(PSEL, r"if current_platform\.is_cpu\(\):", sa) - 1),
         "set": {"vars.dims": "= input.has_model_config ? input.mla_dimensions : [0, 0, 0]", "vars.dtype": "= input.has_model_config ? input.dtype : 'float32'"}},
        {"if": "!input.is_cpu && input.mla_prefill_backend != ''",
         "then": [{"title": "Explicit AttentionConfig.mla_prefill_backend: load the class", "source": C(PSEL, ln(PSEL, r"backend_cls = selected_backend\.get_class\(\)", sa)),
                   "call": "mla-prefill-backend-enum.get-class", "input": {"name": "= input.mla_prefill_backend"}, "as": "cls",
                   "on_error": [{"if": "error.code == 'import-error'",
                                 "then": [{"title": "An ImportError becomes the only reason", "source": C(PSEL, ln(PSEL, r"invalid_reasons = \[\"ImportError\"\]", sa)),
                                           "fail": {"code": "value-error", "message": "= 'Selected MLA prefill backend ' + input.mla_prefill_backend + ' is not valid for this configuration. Reason: [\\'ImportError\\']'"}}],
                                 "else": [{"fail": "= {'code': error.code, 'status': error.status, 'message': error.message}"}]}]},
                  {"title": "Validate it on this device", "source": C(PSEL, ln(PSEL, r"invalid_reasons = backend_cls\.validate_configuration\(", sa)),
                   "call": "mla-prefill-backend.validate-configuration",
                   "input": {"backend_cls": "= vars.cls.value.cls", "has_device_capability": True, "device_capability": "= input.device_capability",
                             "dtype": "= vars.dtype", "mla_dimensions": "= vars.dims"}, "as": "v"},
                  {"if": "size(vars.v.value.invalid_reasons) > 0",
                   "then": [{"title": "The selected backend is invalid", "source": C(PSEL, ln(PSEL, r"if invalid_reasons:", sa)),
                             "fail": {"code": "value-error", "message": "= 'Selected MLA prefill backend ' + input.mla_prefill_backend + ' is not valid for this configuration. Reason: [' + vars.v.value.invalid_reasons.map(r, \"'\" + r + \"'\").join(', ') + ']'"}}]},
                  {"return": {"backend": "= vars.cls.value.class_name", "auto": False}}]},
        {"if": "input.is_cpu",
         "then": [{"title": "CPU: current_platform is CpuPlatform, so its priority list (ZEN_CPU, CPU) answers", "source": C(PSEL, aa, ab),
                   "call": "cpu-platform.get-mla-prefill-backend-cls", "input": {"dtype": "= vars.dtype", "mla_dimensions": "= vars.dims"}, "as": "auto"}],
         "else": [{"title": "Nothing selected: the platform's priority list (functools.cache per selector config)", "source": C(PSEL, aa, ab),
                   "call": "cuda-platform.get-mla-prefill-backend-cls", "input": {"dtype": "= vars.dtype", "mla_dimensions": "= vars.dims"}, "as": "auto"}]},
        {"return": {"backend": "= has(vars.auto.value.backend) ? vars.auto.value.backend : null", "auto": True}},
    ]
    out.append(iface("mla-prefill-selector", "get-mla-prefill-backend", "get_mla_prefill_backend: an explicit mla_prefill_backend is loaded and validated (ValueError when invalid); otherwise, and always on CPU, the platform auto-selects.",
                     [C(PSEL, sa, sb), C(PSEL, aa, ab)], beh,
                     request=obj({"has_model_config": B(True), "dtype": S("bfloat16"), "mla_dimensions": A([128, 64, 128]), "is_cpu": B(False),
                                  "mla_prefill_backend": S(""), "device_capability": obj({"major": I(9), "minor": I(0)})}),
                     response=obj({"backend": {"type": ["string", "null"]}, "auto": {"type": "boolean"}}),
                     errors=[err("value-error", "the selected backend is invalid")]))
    return out


def boundary_components():
    return []


def boundary_interfaces():
    return [{"component": "cuda-platform", "name": "get-mla-prefill-backend-cls", "kind": "function",
             "summary": "Boundary stub: Platform.get_mla_prefill_backend_cls walks the capability's priority list (FLASH_ATTN on SM90; TRTLLM_RAGGED or FLASH_ATTN first on SM100) and returns the first valid class.",
             "sources": [Cfn("vllm/platforms/interface.py", "get_mla_prefill_backend_cls")],
             "attributes": {"boundary": True, "owner": "config-platform"},
             "request": obj({"dtype": {"type": "string"}, "mla_dimensions": ARR_I}),
             "response": obj({"backend": {"type": "string", "examples": ["FLASH_ATTN"]}}),
             "errors": [err("value-error", "no valid MLA prefill backend")]},
            {"component": "cpu-platform", "name": "get-mla-prefill-backend-cls", "kind": "function",
             "summary": "Boundary stub: CpuPlatform.get_mla_prefill_backend_cls returns the first of ZEN_CPU, CPU that imports and is available.",
             "sources": ["vllm/platforms/cpu.py:182-194"],
             "attributes": {"boundary": True, "owner": "config-platform"},
             "request": obj({"dtype": {"type": "string"}, "mla_dimensions": ARR_I}),
             "response": obj({"backend": {"type": "string", "examples": ["CPU"]}, "class_name": {"type": ["string", "null"]}}),
             "errors": [err("value-error", "no valid CPU MLA prefill backend")]}]


def layer_interfaces():
    out = []
    # MLAAttention.get_kv_cache_spec
    ga, gb = m(MLAA, "MLAAttention", "get_kv_cache_spec")
    beh = [
        {"title": "kv_cache_dtype_str_to_dtype: 'auto' is the model dtype; fp8, ds_mla, nvfp4 and per-token-head caches are stored as uint8",
         "source": Cfn("vllm/utils/torch_utils.py", "kv_cache_dtype_str_to_dtype"),
         "set": {"vars.dt": "= input.kv_cache_dtype == 'auto' ? input.model_dtype_bytes : (input.kv_cache_dtype in ['bfloat16', 'float16', 'half'] ? 2 : (input.kv_cache_dtype in ['float', 'float32'] ? 4 : 1))"}},
        {"title": "get_kv_quant_mode of the layer's cache dtype", "source": C(MLAA, ln(MLAA, r"kv_quant_mode=get_kv_quant_mode\(self\.kv_cache_dtype\)", ga)),
         "call": "kv-quant-mode.get-kv-quant-mode", "input": {"kv_cache_dtype": "= input.kv_cache_dtype"}, "as": "q"},
        {"title": "ds_mla layouts pack NoPE + RoPE + scales into one opaque blob per token: 656 B (fp8) or 352 B (nvfp4)",
         "source": C(MLAA, ln(MLAA, r"state_content_bytes=\{\"fp8_ds_mla\": 656, \"nvfp4_ds_mla\": 352\}\.get\(", ga)),
         "set": {"vars.blob": "= input.kv_cache_dtype == 'fp8_ds_mla' ? dyn(656) : (input.kv_cache_dtype == 'nvfp4_ds_mla' ? dyn(352) : dyn(null))",
                 "vars.cls": "= input.sliding_window > 0 ? 'sliding_window_mla' : 'mla_attention'"}},
        {"title": "One latent KV head, never sharded across TP; a SlidingWindowMLASpec when the layer has a window, else an MLAAttentionSpec",
         "source": C(MLAA, ln(MLAA, r"if self\.sliding_window is not None:", ga), gb), "set": {"vars.content": "= vars.blob != null ? vars.blob : input.head_size * vars.dt"}},
        {"title": "AttentionSpec.page_size_bytes for that spec: 1 head slot x block_size states x the packed blob (ds_mla) or head_size latent bytes (MLA has no separate V)",
         "source": C(KVI, *m(KVI, "AttentionSpec", "unpadded_page_size_bytes")), "set": {"vars.page": "= int(config['block-size']) * vars.content"}},
        {"return": {"spec_class": "= vars.cls", "block_size": "= int(config['block-size'])", "num_kv_heads": 1, "max_tp_shards": 1, "head_size": "= input.head_size",
                    "cache_dtype_str": "= input.kv_cache_dtype", "kv_quant_mode": "= vars.q.value.kv_quant_mode", "page_size_bytes": "= vars.page",
                    "sliding_window": "= input.sliding_window > 0 ? dyn(input.sliding_window) : dyn(null)",
                    "is_index_group_leader": "= vars.cls == 'mla_attention' && input.has_indexer",
                    "non_causal_multi_token_decode": "= vars.cls == 'mla_attention' && input.non_causal_multi_token_decode"}},
    ]
    out.append(iface("mla-attention", "get-kv-cache-spec", "MLAAttention.get_kv_cache_spec: an MLA spec with one latent head (head_size 576 for DeepSeek), the layer's cache dtype string, its KVQuantMode, and the ds_mla page sizes.",
                     [C(MLAA, ga, gb)], beh,
                     request=obj({"kv_cache_dtype": S("auto"), "head_size": I(576), "model_dtype_bytes": I(2), "sliding_window": I(0),
                                  "has_indexer": B(False), "non_causal_multi_token_decode": B(False)}),
                     response=obj({"cache_dtype_str": {"type": "string"}, "kv_quant_mode": {"type": "string"}, "page_size_bytes": {"type": "integer"}})))
    ba, bb = m(MLAA, "MLAAttention", "bind_kv_cache")
    ua, ub = m(MLAA, "MLAAttention", "_uses_flat_kv_cache")
    beh = [
        {"title": "The [B, 1, N, C] cache is squeezed to [B, N, C]; the flat layouts are FLASHINFER_MLA_SPARSE and FLASHMLA_SPARSE without a ds_mla dtype",
         "source": C(MLAA, ua, ub),
         "set": {"vars.flat": "= input.backend == 'FLASHINFER_MLA_SPARSE' || (input.backend == 'FLASHMLA_SPARSE' && !(input.kv_cache_dtype in ['fp8_ds_mla', 'nvfp4_ds_mla']))"}},
        {"if": "input.enable_jit_warmup && vars.flat",
         "then": [{"if": "input.block_stride % input.row_width != 0",
                   "then": [{"title": "The block stride must be whole rows", "source": C(MLAA, ln(MLAA, r"assert self\.kv_cache\.stride\(0\) % row_width == 0", ba)),
                             "fail": {"code": "assertion-error", "message": ""}}]},
                  {"title": "Register a JIT warm-up of the index-convert kernel at this block stride", "source": C(MLAA, ln(MLAA, r"_CONVERT_REQ_INDEX_TO_GLOBAL_INDEX_KERNEL\.register_warmup\(", ba), bb),
                   "return": {"flat": True, "warmup_block_stride_rows": "= input.block_stride / input.row_width"}}]},
        {"return": {"flat": "= vars.flat", "warmup_block_stride_rows": None}},
    ]
    out.append(iface("mla-attention", "bind-kv-cache", "MLAAttention.bind_kv_cache: keep the squeezed cache; with JIT warm-up on and a flat sparse layout, register the convert kernel's warm-up at the cache's block stride.",
                     [C(MLAA, ba, bb), C(MLAA, ua, ub)], beh,
                     request=obj({"backend": S("FLASHMLA_SPARSE"), "kv_cache_dtype": S("auto"), "enable_jit_warmup": B(False), "block_stride": I(36864), "row_width": I(576)}),
                     response=obj({"flat": {"type": "boolean"}, "warmup_block_stride_rows": {"type": ["integer", "null"]}}),
                     errors=[err("assertion-error", "block stride not a whole number of rows")]))
    wa, wb = m(MLAA, "MLAAttention", "chunked_prefill_workspace_size")
    da, db = fn(MLAA, "determine_chunked_prefill_workspace_size")
    aa, ab = fn(MLAA, "align_mla_chunked_context_workspace_size")
    beh = [
        {"title": "Eight full-length requests or four pages per sequence, capped at 64K tokens", "source": C(MLAA, da, db),
         "set": {"vars.w": "= math.least(math.greatest(8 * int(config['max-model-len']), 4 * int(config['max-num-seqs']) * int(config['block-size'])), 65536)",
                 "vars.a": "= int(config['block-size'])"}},
        {"if": "int(config['decode-context-parallel-size']) > 1",
         "then": [{"title": "Under DCP the alignment is lcm(block_size, dcp x interleave)", "source": C(MLAA, ln(MLAA, r"if parallel_config\.decode_context_parallel_size > 1:", aa), ab - 1),
                   "set": {"vars.a": "= lists.range(int(config['block-size'])).map(i, (i + 1) * int(config['decode-context-parallel-size']) * int(config['cp-kv-cache-interleave-size'])).filter(x, x % int(config['block-size']) == 0)[0]"}}]},
        {"title": "round_up(max(size, alignment), alignment); memoized on the layer", "source": C(MLAA, wa, wb),
         "return": {"workspace_tokens": "= ((math.greatest(vars.w, vars.a) + vars.a - 1) / vars.a) * vars.a", "alignment": "= vars.a"}},
    ]
    out.append(iface("mla-attention", "chunked-prefill-workspace-size", "MLAAttention.chunked_prefill_workspace_size: tokens of the chunked-context prefill workspace, aligned to the block size (and to DCP x interleave under DCP).",
                     [C(MLAA, wa, wb), C(MLAA, da, db), C(MLAA, aa, ab)], beh, request=obj({}),
                     response=obj({"workspace_tokens": {"type": "integer"}})))
    return out


def sparse_interfaces():
    out = []
    # FlashInferMLASparseSM90Builder.build + _kv_lens_host
    ba, bb = m(SM90, "FlashInferMLASparseSM90Builder", "build")
    ka, kb = m(SM90, "FlashInferMLASparseSM90Builder", "_kv_lens_host")
    ra, rb = m(SM90, "FlashInferMLASparseSM90Builder", "_row_contexts")
    ctx = "lists.range(size(input.query_start_loc_cpu) - 1).map(r, lists.range(input.query_start_loc_cpu[r + 1] - input.query_start_loc_cpu[r]).map(j, SL[r] - (input.query_start_loc_cpu[r + 1] - input.query_start_loc_cpu[r]) + 1 + j)).flatten()"
    beh = [
        {"title": "The common sparse metadata (req ids, top-k buffer access)", "source": C(SM90, ln(SM90, r"metadata = super\(\)\.build\(common_prefix_len, common_attn_metadata, fast_build\)", ba)),
         "set": {"vars.rows": "= input.query_start_loc_cpu[size(input.query_start_loc_cpu) - 1]"}},
        {"if": "vars.rows == 0",
         "then": [{"set": {"vars.lens": [], "vars.exact": True}}],
         "else": [{"if": "!input.has_seq_lens_cpu_upper_bound",
                   "then": [{"title": "Exact lengths: row j of request i attends seq_len - q_len + j + 1; past index_topk only topk + ctx % kpool are valid",
                             "source": C(SM90, ln(SM90, r"if sl_host is None:", ka), ln(SM90, r"return num_rows, lens\.to\(torch\.int32\), True", ka)),
                             "set": {"vars.ctx": "= " + ctx.replace("SL", "input.seq_lens"), "vars.exact": True}},
                            {"set": {"vars.lens": "= vars.ctx.map(c, c <= input.index_topk ? c : input.index_topk + c % input.index_kpool)"}}],
                   "else": [{"if": "input.adaptive_verification",
                             "then": [{"title": "Adaptive verification: bound every row by the longest request", "source": C(SM90, ln(SM90, r"if self\._adaptive_verification:", ka), ln(SM90, r"ctx = torch\.full", ka)),
                                       "set": {"vars.ctx": "= lists.range(vars.rows).map(i, math.greatest(input.seq_lens_cpu_upper_bound))"}}],
                             "else": [{"title": "Upper bounds from the CPU seq_lens bound (sync-free)", "source": C(SM90, ra, rb),
                                       "set": {"vars.ctx": "= " + ctx.replace("SL", "input.seq_lens_cpu_upper_bound")}}]},
                            {"title": "Clamped to the largest valid count; the plan clamps on device", "source": C(SM90, ln(SM90, r"return num_rows, torch\.clamp\(ctx, max=state\.max_valid\), False", ka)),
                             "set": {"vars.lens": "= vars.ctx.map(c, math.least(c, math.least(input.index_topk + input.index_kpool - 1, input.topk_width)))", "vars.exact": False}}]}]},
        {"if": "input.num_prefills > 0 && input.use_sparse_mha",
         "then": [{"title": "MHA prefills leave q before forward_mqa: plan only the decode prefix", "source": C(SM90, ln(SM90, r"if metadata\.num_prefills > 0 and self\._attention_layer\._use_sparse_mha\(", ba), ln(SM90, r"kv_lens = kv_lens\[:num_rows\]", ba)),
                   "set": {"vars.rows": "= input.num_decode_tokens", "vars.lens": "= vars.lens.slice(0, input.num_decode_tokens)"}}]},
        {"title": "Plan host-side, outside any CUDA graph capture", "source": C(SM90, ln(SM90, r"if exact:", ba), ln(SM90, r"metadata\.state = self\.state", ba)),
         "call": "flashinfer-mla-sparse-sm90-state.plan", "input": {"num_tokens": "= vars.rows", "kv_lens": "= vars.lens", "has_device_layout": "= !vars.exact"}, "as": "plan"},
        {"return": {"num_rows": "= vars.rows", "kv_lens": "= vars.lens", "exact": "= vars.exact", "replanned": "= vars.plan.value.replanned"}},
    ]
    out.append(iface("flashinfer-mla-sparse-sm90-builder", "build", "FlashInferMLASparseSM90Builder.build: per-row KV lengths (exact, or sync-free upper bounds), trimmed to the decode rows when prefills go to sparse MHA, then the SM90 state's plan.",
                     [C(SM90, ba, bb), C(SM90, ka, kb), C(SM90, ra, rb)], beh,
                     request=obj({"query_start_loc_cpu": A([0, 1, 6]), "seq_lens": A([1402, 5]), "has_seq_lens_cpu_upper_bound": B(True),
                                  "seq_lens_cpu_upper_bound": A([1402, 5]), "adaptive_verification": B(False), "num_prefills": I(1),
                                  "num_decode_tokens": I(1), "use_sparse_mha": B(False), "index_topk": I(2048), "index_kpool": I(1), "topk_width": I(2048)}),
                     response=obj({"num_rows": {"type": "integer"}, "kv_lens": ARR_I, "exact": {"type": "boolean"}})))
    # supports_combination of the two sparse-MLA backends
    sa, sb = m(FIMS, "FlashInferMLASparseTRTLLMBackend", "supports_combination")
    beh = [
        {"if": "input.pcp_size > 1 && input.dcp_size > 1",
         "then": [{"title": "No combined PCP + DCP", "source": C(FIMS, ln(FIMS, r"parallel_config\.prefill_context_parallel_size > 1", sa)),
                   "return": {"reason": "FLASHINFER_MLA_SPARSE does not support combined PCP+DCP"}}]},
        {"if": "input.kv_cache_dtype == 'fp8_ds_mla'",
         "then": [{"title": "No fp8_ds_mla on SM10", "source": C(FIMS, ln(FIMS, r"if kv_cache_dtype == \"fp8_ds_mla\":", sa)),
                   "return": {"reason": "FLASHINFER_MLA_SPARSE SM10 does not support fp8_ds_mla kv-cache dtype"}}]},
        {"if": "input.qk_rope_head_dim == 0 && (input.qk_nope_head_dim != 256 || input.kv_lora_rank != 512)",
         "then": [{"title": "Native no-rope MLA ships one shape", "source": C(FIMS, ln(FIMS, r"if qk_rope_head_dim == 0:", sa)),
                   "return": {"reason": "FlashInfer native no-rope MLA requires qk_nope_head_dim=256 and kv_lora_rank=512"}}]},
        {"if": "input.qk_rope_head_dim != 0 && !(input.qk_nope_head_dim in [128, 192])",
         "then": [{"title": "The SM10 kernel needs qk_nope_head_dim 128 or 192", "source": C(FIMS, ln(FIMS, r"elif qk_nope_head_dim not in \[128, 192\]:", sa)),
                   "return": {"reason": "FlashInfer MLA Sparse kernel requires qk_nope_head_dim in [128, 192]"}}]},
        {"if": "!input.has_index_topk",
         "then": [{"title": "Sparse models carry index_topk", "source": C(FIMS, ln(FIMS, r"if not hasattr\(hf_text_config, \"index_topk\"\):", sa)),
                   "return": {"reason": "FlashInfer MLA Sparse requires model with index_topk config"}}]},
        {"title": "Valid", "source": C(FIMS, sb, sb), "return": {"reason": None}},
    ]
    req = obj({"kv_cache_dtype": S("auto"), "pcp_size": I(1), "dcp_size": I(1), "qk_nope_head_dim": I(128), "qk_rope_head_dim": I(64),
               "kv_lora_rank": I(512), "has_index_topk": B(True), "head_size": I(576), "device_capability_major": I(10), "has_model_config": B(True)})
    out.append(iface("flashinfer-mla-sparse-backend", "supports-combination", "FlashInferMLASparseTRTLLMBackend.supports_combination: no PCP+DCP, no fp8_ds_mla, the TRT-LLM head layouts, and a sparse (index_topk) model; None means valid. get_name is FLASHINFER_MLA_SPARSE (also for SM120), kernel blocks of MultipleOf(32), impl FlashInferMLASparseImpl.",
                     [C(FIMS, sa, sb), Cm(FIMS, "_FlashInferMLASparseBackendBase", "get_name"), Cm(FIMS, "FlashInferMLASparseTRTLLMBackend", "get_impl_cls"),
                      Cm(FIMS, "FlashInferMLASparseTRTLLMBackend", "get_supported_kernel_block_sizes"), Cm(FIMS, "FlashInferMLASparseSM120Backend", "get_name"),
                      Cm(FIMS, "FlashInferMLASparseSM120Backend", "get_impl_cls")], beh,
                     request=req, response=obj({"reason": {"type": ["string", "null"]}})))
    fa_, fb_ = m(FMS, "FlashMLASparseBackend", "supports_combination")
    beh = [
        {"if": "input.head_size == 512",
         "then": [{"if": "input.kv_cache_dtype in ['auto', 'bfloat16', 'float16', 'fp8_ds_mla'] && input.device_capability_major == 9",
                   "then": [{"if": "input.has_model_config && input.qk_rope_head_dim != 0",
                             "then": [{"title": "head_size 512 is only for rope-free (NoPE) models", "source": C(FMS, ln(FMS, r"if getattr\(hf_text_config, \"qk_rope_head_dim\", 64\) != 0:", fa_)),
                                       "return": {"reason": "FLASHMLA_SPARSE supports head_size 512 only for rope-free (NoPE) models"}}]}],
                   "else": [{"title": "head_size 512 needs a bf16 or fp8_ds_mla cache on SM90", "source": C(FMS, ln(FMS, r"\"FLASHMLA_SPARSE supports head_size 512 only with bf16 or \"", fa_)),
                             "return": {"reason": "= 'FLASHMLA_SPARSE supports head_size 512 only with bf16 or fp8_ds_mla kv-cache on SM90 (NoPE), got kv_cache_dtype=' + input.kv_cache_dtype"}}]}]},
        {"if": "input.kv_cache_dtype == 'nvfp4_ds_mla' && input.device_capability_major != 10",
         "then": [{"title": "nvfp4_ds_mla only on SM100", "source": C(FMS, ln(FMS, r"if kv_cache_dtype == \"nvfp4_ds_mla\" and device_capability\.major != 10:", fa_)),
                   "return": {"reason": "FLASHMLA_SPARSE only supports the nvfp4_ds_mla kv-cache dtype on SM100 (Blackwell)"}}]},
        {"title": "Valid", "source": C(FMS, fb_, fb_), "return": {"reason": None}},
    ]
    out.append(iface("flashmla-sparse-backend", "supports-combination", "FlashMLASparseBackend.supports_combination: head 512 only for NoPE models with a bf16 or fp8_ds_mla cache on SM90; nvfp4_ds_mla only on SM100. get_name FLASHMLA_SPARSE, head sizes [576, 512], SM90/SM100.",
                     [C(FMS, fa_, fb_), Cm(FMS, "FlashMLASparseBackend", "get_name"), Cm(FMS, "FlashMLASparseBackend", "get_impl_cls"),
                      Cm(FMS, "FlashMLASparseBackend", "get_supported_kernel_block_sizes"), Cm(FMS, "FlashMLASparseBackend", "supports_compute_capability")], beh,
                     request=req, response=obj({"reason": {"type": ["string", "null"]}})))
    # Sparse MLA index groups
    ia, ib = m(IG, "SparseMLAIndexGroupBuilder", "__init__")
    out.append(iface("sparse-mla-index-group-builder", "init", "SparseMLAIndexGroupBuilder.__init__: the logical top-k buffer and the decode-row workspace bound (min(max_num_batched_tokens, max_num_seqs x max decode query len) in the models).",
                     [C(IG, ia, ib), Cfn(IG, "get_sparse_mla_index_group_max_rows")],
                     [{"title": "max_decode_rows defaults to the logical buffer's rows", "source": C(IG, ia, ib),
                       "set": {"state.logical_rows": "= input.logical_rows", "state.max_decode_rows": "= input.max_decode_rows > 0 ? input.max_decode_rows : input.logical_rows",
                               "state.current_group": None, "state.groups": {}, "state.num_groups": 0}},
                      {"return": {"max_decode_rows": "= state.max_decode_rows"}}],
                     request=obj({"logical_rows": I(8192), "max_decode_rows": I(0)}), response=obj({"max_decode_rows": {"type": "integer"}})))
    ra_, rb_ = m(IG, "SparseMLAIndexGroupBuilder", "register_layer")
    beh = [
        {"if": "input.is_index_producing_layer || state.current_group == null",
         "then": [{"title": "An index-producing layer (or the first layer) opens a new group with a workspace of max_decode_rows + 1 rows",
                   "source": C(IG, ln(IG, r"if is_index_producing_layer or self\.current_group is None:", ra_), ln(IG, r"has_indexer=is_index_producing_layer,", ra_)),
                   "set": {"vars.g": "= 'g' + string(state.num_groups)"}},
                  {"set": {"= 'state.groups.' + vars.g": "= {'num_layers': 0, 'has_indexer': input.is_index_producing_layer, 'workspace_rows': state.max_decode_rows + 1, 'hisparse': input.hisparse}",
                           "state.num_groups": "= state.num_groups + 1", "state.current_group": "= vars.g"}}]},
        {"title": "SparseMLAIndexGroup.register_layer: the next layer index in the group", "source": Cm(IG, "SparseMLAIndexGroup", "register_layer"),
         "set": {"vars.cur": "= state.current_group"}},
        {"set": {"vars.idx": "= state.groups[vars.cur].num_layers"}},
        {"set": {"= 'state.groups.' + vars.cur + '.num_layers'": "= vars.idx + 1"}},
        {"return": {"group": "= vars.cur", "layer_index": "= vars.idx"}},
    ]
    out.append(iface("sparse-mla-index-group-builder", "register-layer", "SparseMLAIndexGroupBuilder.register_layer: the layers after an index-producing layer join its group (HiSparse groups when hisparse is configured); returns the group and the layer's index in it.",
                     [C(IG, ra_, rb_), Cm(IG, "SparseMLAIndexGroup", "register_layer")], beh,
                     request=obj({"is_index_producing_layer": B(True), "hisparse": B(False)}), response=obj({"group": {"type": "string"}, "layer_index": {"type": "integer"}})))
    ca_, cb_ = m(IG, "SparseMLAIndexGroup", "_convert_once")
    xa, xb = m(IG, "SparseMLAIndexGroup", "convert_logical_to_physical_topk")
    beh = [
        {"if": "!(input.group in state.groups)",
         "then": [{"title": "No such group", "source": C(IG, xa, xa), "fail": {"code": "key-error", "message": "= \"'\" + input.group + \"'\""}}]},
        {"set": {"vars.g": "= state.groups[input.group]"}},
        {"if": "input.num_tokens > vars.g.workspace_rows",
         "then": [{"title": "A prefill-sized batch exceeds the shared workspace: every layer converts its own indices",
                   "source": C(IG, ln(IG, r"if num_tokens > self\.physical_topk_indices\.shape\[0\]:", ca_), ln(IG, r"return_valid_counts=return_valid_counts,", ca_)),
                   "call": "sparse-utils.triton-convert-req-index-to-global-index", "input": {"shape": {"num_tokens": "= input.num_tokens"}}},
                  {"return": {"path": "per-layer", "converted": True, "valid_counts": "= input.return_valid_counts"}}]},
        {"if": "input.layer_index == 0",
         "then": [{"title": "The group's first layer converts once on the side stream (after the indexer's event, or the compute stream in piecewise graphs)",
                   "source": C(IG, ln(IG, r"if layer_index == 0:", ca_), ln(IG, r"self\.physical_topk_ready\.record\(self\.side_stream\)", ca_)),
                   "call": "sparse-utils.triton-convert-req-index-to-global-index", "input": {"shape": {"num_tokens": "= input.num_tokens"}}},
                  {"return": {"path": "shared", "converted": True, "valid_counts": "= input.return_valid_counts", "waited_on": "= vars.g.has_indexer && !input.in_piecewise_cudagraph ? 'logical_topk_ready' : 'compute_stream'"}}]},
        {"title": "Later layers wait for physical_topk_ready and reuse the shared buffer", "source": C(IG, ln(IG, r"compute_stream\.wait_event\(self\.physical_topk_ready\)", ca_), cb_),
         "return": {"path": "shared", "converted": False, "valid_counts": "= input.return_valid_counts"}},
    ]
    out.append(iface("sparse-mla-index-group-builder", "convert-logical-to-physical-topk", "SparseMLAIndexGroup.convert_logical_to_physical_topk: one top-k index conversion shared by the group's layers, unless the batch has more rows than the workspace (then each layer converts).",
                     [C(IG, xa, xb), C(IG, ca_, cb_)], beh,
                     request=obj({"group": S("g0"), "layer_index": I(0), "num_tokens": I(2), "return_valid_counts": B(False), "in_piecewise_cudagraph": B(False)}),
                     response=obj({"path": {"type": "string"}, "converted": {"type": "boolean"}}), errors=[err("key-error", "unknown group")]))
    return out


def sm90_plan_interface():
    """Replaces round-1's shape-only _SM90State.plan (breaking: callers send num_tokens and kv_lens)."""
    pla, plb = fn(SM90, "plan")
    pa, pb = fn(SM90, "_plan")
    ca, cb = fn(SM90, "_clamp_kv_end")
    beh = [
        {"if": "input.capturing",
         "then": [{"title": "Planning inside CUDA graph capture is refused", "source": C(SM90, ln(SM90, r"if torch\.cuda\.is_current_stream_capturing\(\):", pla)),
                   "fail": {"code": "runtime-error", "message": "FlashInferMLASparseSM90 plan() called inside CUDA graph capture; lengths must be planned host-side before capture."}}]},
        {"if": "!input.has_device_layout",
         "then": [{"title": "Exact lengths: plan them as given, every call", "source": C(SM90, ln(SM90, r"if cam is None or req_id_per_token is None:", pla), ln(SM90, r"self\._planned_num_tokens = -1", pla)),
                   "set": {"state.planned_num_tokens": -1, "state.planned_lens": "= input.kv_lens"}},
                  {"return": {"num_tokens": "= input.num_tokens", "planned_lens": "= input.kv_lens", "replanned": True, "clamped": False}}]},
        {"set": {"vars.prev": "= state.planned_lens"}},
        {"title": "_PLAN_SLACK: planned bounds may exceed the real lengths by up to 32", "source": C(SM90, ln(SM90, r"^_PLAN_SLACK = ")), "set": {"vars.slack": "= input.plan_slack"}},
        {"if": f"input.num_tokens != state.planned_num_tokens || size(vars.prev) != size(input.kv_lens) || lists.range(size(input.kv_lens)).exists(i, vars.prev[i] < input.kv_lens[i] || vars.prev[i] > input.kv_lens[i] + input.plan_slack)",
         "then": [{"title": "Upper bounds no longer fit the plan: replan with the bounds + slack, clamped to max_valid", "source": C(SM90, pa, pb),
                   "set": {"vars.lens": "= input.kv_lens.map(k, math.least(k + input.plan_slack, input.max_valid))", "vars.re": True}},
                  {"set": {"state.planned_num_tokens": "= input.num_tokens", "state.planned_lens": "= vars.lens"}}],
         "else": [{"title": "The plan still bounds every row: reuse it", "source": C(SM90, ln(SM90, r"planned = self\._lens_cpu\[:num_tokens\]", pla)),
                   "set": {"vars.lens": "= vars.prev", "vars.re": False}}]},
        {"title": "_clamp_work_kv_end: each work item's KV end clamped on device to the exact count", "source": C(SM90, ln(SM90, r"_clamp_work_kv_end\[", ca)),
         "call": "flashinfer-mla-sparse-sm90-state.clamp-work-kv-end", "input": {"num_tokens": "= input.num_tokens"}},
        {"return": {"num_tokens": "= input.num_tokens", "planned_lens": "= vars.lens", "replanned": "= vars.re", "clamped": True}},
    ]
    return iface("flashinfer-mla-sparse-sm90-state", "plan",
                 "_SM90State.plan: plan per-row KV lengths. Exact lengths are planned every call; upper bounds (device batch layout) reuse the last plan while it still bounds every row within the slack, and each call clamps the work items' KV ends on device.",
                 [C(SM90, pla, plb), C(SM90, pa, pb), C(SM90, ca, cb)], beh,
                 request=obj({"num_tokens": I(4), "kv_lens": A([8, 5, 3, 1]), "has_device_layout": B(True), "capturing": B(False),
                              "plan_slack": I(32), "max_valid": I(2048)}),
                 response=obj({"num_tokens": {"type": "integer"}, "planned_lens": ARR_I, "replanned": {"type": "boolean"}}),
                 errors=[err("runtime-error", "inside CUDA graph capture")])


def rocm_interfaces():
    out = []
    da, db = m(RAM, "AiterMLAHelper", "use_gluon_decode")
    va, vb = m(RAM, "AiterMLAHelper", "use_gluon_verify")
    bnd = Cfn(RAM, "_gluon_kv_cache_in_bounds")
    inb = "(input.kv_cache_bytes == null || input.kv_cache_bytes <= 2147483648)"
    q = {"title": "is_quantized_kv_cache", "call": "kv-quant-mode.get-kv-quant-mode", "input": {"kv_cache_dtype": "= input.kv_cache_dtype"}, "as": "q"}
    beh = [
        {"if": "input.num_heads >= 16 || input.max_qo_len != 1",
         "then": [{"title": "Only small-head (< 16) single-token decode can take Gluon", "source": C(RAM, ln(RAM, r"if num_heads >= m or max_qo_len != 1:", da)), "return": {"use_gluon": False}}]},
        dict(q, source=C(RAM, ln(RAM, r"if is_quantized_kv_cache\(kv_cache_dtype\):", da))),
        {"if": "vars.q.value.is_quantized",
         "then": [{"title": "Gluon's fp8 regime asserts batch_size == 1: never for a quantized cache, whatever the mode", "source": C(RAM, ln(RAM, r"if is_quantized_kv_cache\(kv_cache_dtype\):", da)), "return": {"use_gluon": False}}]},
        {"if": "config['vllm-rocm-aiter-mla-asm-padding'] == 'asm' || !input.gluon_build_available",
         "then": [{"title": "Forced asm, or no gfx950 Gluon build", "source": C(RAM, ln(RAM, r"mode = _aiter_mla_small_head_mode\(\)", da), ln(RAM, r"if not _gluon_mla_decode_supported\(\):", da)), "return": {"use_gluon": False}}]},
        {"if": "config['vllm-rocm-aiter-mla-asm-padding'] != 'gluon' && 16 % input.num_heads != 0",
         "then": [{"title": "auto: non-divisor head counts take the padded asm decode", "source": C(RAM, ln(RAM, r"if mode != \"gluon\" and m % num_heads != 0:", da)), "return": {"use_gluon": False}}]},
        {"title": "Last: the 2 GiB cache bound Gluon keeps its masked loads under", "source": bnd, "return": {"use_gluon": "= " + inb}},
    ]
    out.append(iface("aiter-mla-helper", "use-gluon-decode", "AiterMLAHelper.use_gluon_decode: a small-head single-token decode uses the Gluon kernel on gfx950 unless the cache is quantized, the mode forces asm, the head count doesn't divide 16 (auto), or the cache passes 2 GiB.",
                     [C(RAM, da, db), bnd, Cfn(RAM, "_gluon_mla_decode_supported"), Cfn(RAM, "_aiter_mla_small_head_mode")], beh,
                     request=obj({"num_heads": I(8), "max_qo_len": I(1), "kv_cache_dtype": S("auto"), "kv_cache_bytes": {"type": ["integer", "null"], "default": None},
                                  "gluon_build_available": B(False)}),
                     response=obj({"use_gluon": {"type": "boolean"}})))
    beh = [
        {"if": "!input.causal",
         "then": [{"title": "Gluon masks causally: a non-causal block takes the padded asm decode", "source": C(RAM, ln(RAM, r"if not causal:", va)), "return": {"use_gluon": False}}]},
        {"if": "input.max_qo_len <= 1 || input.dcp_world_size > 1",
         "then": [{"title": "Single-token, or DCP verify (served by segmented MLA)", "source": C(RAM, ln(RAM, r"if max_qo_len <= 1 or dcp_world_size > 1:", va)), "return": {"use_gluon": False}}]},
        dict(q, source=C(RAM, ln(RAM, r"if is_quantized_kv_cache\(kv_cache_dtype\):", va))),
        {"if": "vars.q.value.is_quantized || input.num_heads >= 16",
         "then": [{"title": "fp8 has an asm q-row fold; >= 16 heads always asm", "source": C(RAM, ln(RAM, r"if is_quantized_kv_cache\(kv_cache_dtype\):", va), ln(RAM, r"if num_heads >= AiterMLAHelper\._AITER_MIN_MLA_HEADS:", va)), "return": {"use_gluon": False}}]},
        {"if": "!input.gluon_build_available || config['vllm-rocm-aiter-mla-asm-padding'] == 'asm'",
         "then": [{"title": "Same arch and mode gating as decode", "source": C(RAM, ln(RAM, r"if not _gluon_mla_decode_supported\(\):", va), ln(RAM, r"if _aiter_mla_small_head_mode\(\) == \"asm\":", va)), "return": {"use_gluon": False}}]},
        {"title": "Gluon MTP verify, within the cache bound", "source": bnd, "return": {"use_gluon": "= " + inb}},
    ]
    out.append(iface("aiter-mla-helper", "use-gluon-verify", "AiterMLAHelper.use_gluon_verify: a causal small-head multi-token verify flattens onto Gluon's MTP entry; never under DCP, fp8, >= 16 heads, without a gfx950 build or with asm forced.",
                     [C(RAM, va, vb), bnd], beh,
                     request=obj({"num_heads": I(8), "max_qo_len": I(4), "kv_cache_dtype": S("auto"), "dcp_world_size": I(1), "causal": B(True),
                                  "kv_cache_bytes": {"type": ["integer", "null"], "default": None}, "gluon_build_available": B(False)}),
                     response=obj({"use_gluon": {"type": "boolean"}})))
    sa, sb = fn(RAM, "_segmented_dcp_verify_supported")
    ra, rb = fn(RAM, "_select_dcp_decode_route")
    beh = [
        {"if": "!input.causal || input.max_qo_len <= 1",
         "then": [{"title": "Plain: single-token or non-causal", "source": C(RAM, ln(RAM, r"if not causal or max_qo_len <= 1:", ra)), "return": {"route": "plain"}}]},
        {"if": "input.asm_selected && input.max_qo_len >= 3",
         "then": [{"title": "cprr: the round-robin asm decode, for qlen >= 3", "source": C(RAM, ln(RAM, r"if asm_selected and max_qo_len >= _MIN_CPRR_QLEN:", ra)), "return": {"route": "cprr"}}]},
        {"if": "input.dcp_world_size > 1 && input.cp_interleave == 1 && input.segmented_available",
         "then": [{"title": "Segmented: needs DCP, interleave 1 and AITER's segmented decode", "source": C(RAM, sa, sb), "return": {"route": "segmented"}}]},
        {"title": "No route for a DCP multi-token verify", "source": C(RAM, ln(RAM, r"raise RuntimeError\(", ra), rb),
         "fail": {"code": "runtime-error", "message": "ROCM_AITER_MLA DCP multi-token verify requires either segmented MLA or the round-robin asm decode."}},
    ]
    out.append(iface("rocm-aiter-mla", "select-dcp-decode-route", "_select_dcp_decode_route with _segmented_dcp_verify_supported: plain, cprr (asm, qlen >= 3) or segmented (DCP, interleave 1); otherwise a RuntimeError.",
                     [C(RAM, ra, rb), C(RAM, sa, sb)], beh,
                     request=obj({"causal": B(True), "max_qo_len": I(2), "asm_selected": B(False), "dcp_world_size": I(8), "cp_interleave": I(1), "segmented_available": B(True)}),
                     response=obj({"route": {"type": "string"}}), errors=[err("runtime-error", "no DCP verify route")]))
    # _expand_page_indices_kernel (inventory entry, previously skipped)
    mark(RAM, "_expand_page_indices_kernel")
    cu = "input.cu_num_tokens"
    beh = [
        {"title": "Grid: one program per (request, 1024-token chunk), sized from the block-table width", "source": C(RAM, ln(RAM, r"max_tokens_per_req = block_table_tensor\.shape\[1\] \* self\.kernel_block_size"), ln(RAM, r"num_chunks = max\(1, cdiv\(max_tokens_per_req, 1024\)\)")),
         "set": {"vars.chunks": "= math.greatest(1, (size(input.block_table[0]) * input.kernel_block_size + 1023) / 1024)",
                 "vars.own": f"= lists.range(input.out_len).map(p, lists.range(size({cu}) - 1).filter(r, {cu}[r] <= p && p < {cu}[r + 1]))"}},
        {"title": "Token t of request r maps to block_table[r][t / K] * K + t % K; programs past a short request's end return, leaving -1",
         "source": Cinv(RAM, "_expand_page_indices_kernel"),
         "return": {"num_chunks": "= vars.chunks",
                    "page_indices": f"= lists.range(input.out_len).map(p, size(vars.own[p]) == 0 ? -1 : input.block_table[vars.own[p][0]][(p - {cu}[vars.own[p][0]]) / input.kernel_block_size] * input.kernel_block_size + (p - {cu}[vars.own[p][0]]) % input.kernel_block_size)"}},
    ]
    out.append(iface("rocm-aiter-mla", "expand-page-indices-kernel", "_expand_page_indices_kernel: expand each request's block-table entries into per-token flat page indices for AITER's page_size=1 MLA decode.",
                     [Cinv(RAM, "_expand_page_indices_kernel")], beh,
                     request=obj({"block_table": {"type": "array", "items": ARR_I, "default": [[3, 7]]}, "cu_num_tokens": A([0, 5]),
                                  "kernel_block_size": I(4), "out_len": I(5)}),
                     response=obj({"page_indices": ARR_I, "num_chunks": {"type": "integer"}}), attributes={"kernel": "_expand_page_indices_kernel", "language": "triton"}))
    # rocm_aiter_mla_sparse ops
    pa, pb = fn(RAMS, "_per_sequence_context_lens")
    out.append(iface("rocm-aiter-mla-sparse-ops", "per-sequence-context-lens", "_per_sequence_context_lens: AITER takes one length per sequence; a (B, next_n) table gives its last column, and anything else is returned unchanged (the same tensor).",
                     [C(RAMS, pa, pb)],
                     [{"if": "size(input.shape) == 2 && input.shape[1] > 1",
                       "then": [{"title": "The last column of the per-row table, made contiguous", "source": C(RAMS, ln(RAMS, r"if context_lens\.dim\(\) == 2 and context_lens\.shape\[1\] > 1:", pa), ln(RAMS, r"return context_lens\[:, -1\]\.contiguous\(\)", pa)),
                                 "return": {"same_tensor": False, "shape": "= [input.shape[0]]", "values": "= input.rows.map(r, r[size(r) - 1])"}}]},
                      {"title": "Per-sequence input passes through as the same object", "source": C(RAMS, pb, pb),
                       "return": {"same_tensor": True, "shape": "= input.shape", "values": "= input.rows.map(r, r[size(r) - 1])"}}],
                     request=obj({"shape": A([4]), "rows": {"type": "array", "items": ARR_I, "default": [[1], [2], [3], [4]]}}),
                     response=obj({"same_tensor": {"type": "boolean"}, "shape": ARR_I})))
    mark(RAMS, "_sparse_kv_row_offset")
    out.append(iface("rocm-aiter-mla-sparse-ops", "sparse-kv-row-offset", "_sparse_kv_row_offset: a global token slot fits int32 but its element offset may not, so the offset is computed in int64.",
                     [Cinv(RAMS, "_sparse_kv_row_offset")],
                     [{"title": "slot.to(int64) * stride", "source": Cinv(RAMS, "_sparse_kv_row_offset"),
                       "return": {"offset": "= input.slot * input.stride", "exceeds_int32": "= input.slot * input.stride > 2147483647"}}],
                     request=obj({"slot": I(5000000), "stride": I(512)}), response=obj({"offset": {"type": "integer"}}),
                     attributes={"kernel": "_sparse_kv_row_offset", "language": "triton"}))
    k = kernel("rocm-aiter-mla-sparse-ops", "sparse-attn-prefill-ragged-kernel", RAMS, "_sparse_attn_prefill_ragged_kernel",
               "ROCm Triton sparse-MLA ragged prefill: each query attends over its selected KV slots (row offsets in int64).")
    out.append(k)
    la, lb = fn(RAMS, "_rocm_sparse_attn_prefill_ragged_triton")
    va2, vb2 = fn(RAMS, "_validate_sparse_dims")
    beh = [
        {"if": "input.indptr_len != input.num_queries + 1",
         "then": [{"title": "indptr has one entry per query plus one", "source": C(RAMS, ln(RAMS, r"assert indptr\.numel\(\) == num_queries \+ 1, \(", la)),
                   "fail": {"code": "assertion-error", "message": "= 'expected indptr shape [' + string(input.num_queries + 1) + '], got torch.Size([' + string(input.indptr_len) + '])'"}}]},
        {"title": "_validate_sparse_dims checks in order: a positive head_dim, a positive NoPE dimension, a non-negative RoPE dimension, then head_dim = NoPE + RoPE", "source": C(RAMS, va2, vb2),
         "set": {"vars.op": "_rocm_sparse_attn_prefill_ragged_triton",
                 "vars.bad": "= input.head_dim <= 0 ? 'expected a positive head_dim, got ' + string(input.head_dim) : (input.nope_head_dim <= 0 ? 'expected a positive NoPE dimension, got ' + string(input.nope_head_dim)"
                             " : (input.rope_head_dim < 0 ? 'expected a non-negative RoPE dimension, got ' + string(input.rope_head_dim)"
                             " : (input.head_dim != input.nope_head_dim + input.rope_head_dim ? 'expected head_dim=' + string(input.nope_head_dim + input.rope_head_dim) + ', got ' + string(input.head_dim) : '')))"}},
        {"if": "vars.bad != ''",
         "then": [{"title": "The first failing dimension check", "source": C(RAMS, va2, vb2),
                   "fail": {"code": "assertion-error", "message": "= vars.op + ' ' + vars.bad"}}]},
        {"title": "Launch over (queries, heads / 16); BLOCK_K 16 for heads >= 256 dims, else 32. The kernel reads each KV row at _sparse_kv_row_offset(slot, stride) (int64)",
         "source": C(RAMS, ln(RAMS, r"_sparse_attn_prefill_ragged_kernel\[\(num_queries, triton\.cdiv\(num_heads, block_h\)\)\]\(", la)),
         "call": "rocm-aiter-mla-sparse-ops.sparse-attn-prefill-ragged-kernel", "input": {"num_tokens": "= input.num_queries", "num_heads": "= input.num_heads", "head_size": "= input.head_dim"}},
        {"return": {"grid": "= [input.num_queries, (input.num_heads + 15) / 16]", "block_k": "= input.head_dim >= 256 ? 16 : 32"}},
    ]
    out.append(iface("rocm-aiter-mla-sparse-ops", "rocm-sparse-attn-prefill-ragged-triton", "_rocm_sparse_attn_prefill_ragged_triton: validate the ragged indptr and the NoPE/RoPE split, then launch the sparse prefill kernel.",
                     [C(RAMS, la, lb), C(RAMS, va2, vb2)], beh,
                     request=obj({"num_queries": I(4), "num_heads": I(16), "head_dim": I(576), "nope_head_dim": I(512), "rope_head_dim": I(64), "indptr_len": I(5)}),
                     response=obj({"grid": ARR_I, "block_k": {"type": "integer"}}), errors=[err("assertion-error", "malformed indptr or head dims")]))
    return out


def interfaces():
    return (kv_spec_interfaces() + metadata_interfaces() + registry_interfaces() + boundary_interfaces() + layer_interfaces()
            + sparse_interfaces() + rocm_interfaces() + [selector_kind()])


# ---------------------------------------------------------------- flows and scenarios

def step(iface_, inp, as_, caller="gpu-worker"):
    return {"interface": iface_, "caller": caller, "input": inp, "as": as_}


def flows():
    return [
        {"id": "attn-mla-kv-cache-spec", "name": "MLA layer KV-cache spec", "entry": {"caller": "gpu-worker", "interface": "mla-attention.get-kv-cache-spec", "input": {"kv_cache_dtype": "auto"}},
         "sources": [Cm(MLAA, "MLAAttention", "get_kv_cache_spec")]},
        {"id": "attn-mla-prefill-select", "name": "MLA prefill backend selection", "entry": {"caller": "gpu-worker", "interface": "mla-prefill-selector.get-mla-prefill-backend", "input": {}},
         "sources": [Cfn(PSEL, "get_mla_prefill_backend")]},
        {"id": "attn-register-backend", "name": "Register or override an attention backend", "tags": ["writes"],
         "entry": {"caller": "gpu-worker", "interface": "attention-backend-enum.register-backend", "input": {"backend": "CUSTOM", "has_class_path": True, "class_path": "my.module.MyCustomBackend"}},
         "sources": [Cfn(REG, "register_backend")]},
        {"id": "attn-sm90-sparse-build", "name": "FlashInfer sparse MLA SM90 metadata build", "entry": {"caller": "gpu-worker", "interface": "flashinfer-mla-sparse-sm90-builder.build", "input": {}},
         "sources": [Cm(SM90, "FlashInferMLASparseSM90Builder", "build")]},
    ]


def _cg(as_, backend, **kw):
    return step("attention-metadata-builder.get-cudagraph-support", dict({"backend": backend}, **kw), as_)


def scenarios():
    S = []
    S.append({"id": "attention-kv-quant-mode-table", "name": "kv_cache_dtype strings map to KVQuantMode (ds_mla before the nvfp4 prefix; any other fp8 is per-tensor)", "fixtures": FX,
              "steps": [step("kv-quant-mode.get-kv-quant-mode", {"kv_cache_dtype": d}, a) for a, d in
                        [("auto", "auto"), ("fp8", "fp8_e5m2"), ("dsmla", "fp8_ds_mla"), ("nvds", "nvfp4_ds_mla"), ("nv", "nvfp4_4over6"), ("tq", "turboquant_k8v4"),
                         ("i4", "int4_per_token_head"), ("i8", "int8_per_token_head"), ("f8h", "fp8_per_token_head"), ("uq", "ultraquant_4bit")]],
              "expect": ["steps.auto.result.value.kv_quant_mode == 'none' && !steps.auto.result.value.is_quantized",
                         "steps.fp8.result.value.kv_quant_mode == 'fp8_per_tensor' && steps.dsmla.result.value.kv_quant_mode == 'fp8_per_tensor'",
                         "steps.nvds.result.value.kv_quant_mode == 'nvfp4_ds_mla' && !steps.nvds.result.value.is_nvfp4 && steps.nv.result.value.is_nvfp4",
                         "steps.tq.result.value.kv_quant_mode == 'turboquant_k8v4' && steps.tq.result.value.is_turboquant",
                         "[steps.i4, steps.i8, steps.f8h].all(s, s.result.value.is_per_token_head) && steps.uq.result.value.is_ultraquant"]})
    S.append({"id": "attention-common-metadata", "name": "CommonAttentionMetadata: batch size, query lengths, computed tokens, token->request map, unpadding", "fixtures": FX,
              "steps": [step("common-attention-metadata.batch-size", {"query_start_loc": [0, 3, 4, 6], "seq_lens": [10, 5, 2]}, "b"),
                        step("common-attention-metadata.batch-size", {"query_start_loc": [0, 3, 4], "seq_lens": [10, 5, 2]}, "bad"),
                        step("common-attention-metadata.batch-size", {"query_start_loc": [0, 3], "seq_lens": [10, 5]}, "bcast"),
                        step("common-attention-metadata.token-to-req-indices", {"query_start_loc": [0, 3, 4, 6], "query_start_loc_cpu": [0, 3, 4, 6], "num_actual_tokens": 8, "buffer_size": 8}, "t"),
                        step("common-attention-metadata.token-to-req-indices", {"query_start_loc_cpu": [0, 3, 4, 6], "num_actual_tokens": 8, "buffer_size": 4}, "small"),
                        step("common-attention-metadata.unpadded", {"query_start_loc": [0, 1, 2, 2, 2], "seq_lens": [7, 9, 0, 0], "slot_mapping": [6, 24, -1, -1], "num_actual_reqs": 2, "num_actual_tokens": 2}, "u"),
                        step("common-attention-metadata.unpadded", {"seq_lens": [7], "slot_mapping": [6], "num_actual_reqs": 4, "num_actual_tokens": 4}, "u2")],
              "expect": ["steps.b.result.value.batch_size == 3 && steps.b.result.value.query_lens == [3, 1, 2] && steps.b.result.value.num_computed_tokens == [7, 4, 0]",
                         "!steps.bad.result.ok && steps.bad.result.error.code == 'runtime-error' && steps.bad.result.error.message == 'The size of tensor a (3) must match the size of tensor b (2) at non-singleton dimension 0'",
                         "steps.bcast.result.value.num_computed_tokens == [7, 2]",
                         "steps.t.result.value.token_to_req == [0, 0, 0, 1, 2, 2, 0, 0]",
                         "!steps.small.result.ok && steps.small.result.error.code == 'assertion-error'",
                         "steps.u.result.value.seq_lens == [7, 9] && steps.u.result.value.slot_mapping == [6, 24] && steps.u.result.value.query_start_loc == [0, 1, 2]",
                         "steps.u2.result.value.clamped && steps.u2.result.value.seq_lens == [7]"]})
    S.append({"id": "attention-impl-base-cp-ranks", "name": "Impl construction: DCP ranks only when the config enables DCP; no PCP group means (1, 0)", "fixtures": FX,
              "steps": [step("attention-impl-base.new", {"dcp_group_initialized": True, "dcp_world_size": 4, "dcp_rank": 2}, "off"),
                        step("attention-impl-base.new", {"has_vllm_config": False, "dcp_group_initialized": True, "dcp_world_size": 4, "dcp_rank": 2,
                                                         "pcp_group_initialized": True, "pcp_world_size": 2, "pcp_rank": 1}, "noconf")],
              "expect": ["steps.off.result.value.dcp_world_size == 1 && !steps.off.result.value.need_to_return_lse_for_decode && steps.off.result.value.pcp_world_size == 1",
                         "steps.noconf.result.value.dcp_world_size == 4 && steps.noconf.result.value.dcp_rank == 2 && steps.noconf.result.value.need_to_return_lse_for_decode && steps.noconf.result.value.pcp_rank == 1"]})
    S.append({"id": "attention-impl-base-dcp-enabled", "name": "With DCP=2 configured, the impl takes the DCP group's size and rank", "fixtures": FX,
              "config": {"decode-context-parallel-size": 2},
              "steps": [step("attention-impl-base.new", {"dcp_group_initialized": True, "dcp_world_size": 2, "dcp_rank": 1, "can_return_lse_for_decode": False}, "d"),
                        step("attention-impl-base.new", {"dcp_group_initialized": False}, "u")],
              "expect": ["steps.d.result.value.dcp_world_size == 2 && steps.d.result.value.total_cp_rank == 1 && !steps.d.result.value.need_to_return_lse_for_decode",
                         "steps.u.result.value.dcp_world_size == 1"]})
    S.append({"id": "attention-cudagraph-support", "name": "CUDA-graph support per builder: FA3 ALWAYS, FA2 UNIFORM_BATCH, Triton ALWAYS, FlashInfer by spec, unknown NEVER", "fixtures": FX,
              "steps": [_cg("fa3", "FLASH_ATTN"), _cg("fa2", "FLASH_ATTN", fa_version=2), _cg("tr", "TRITON_ATTN"), _cg("fi", "FLASHINFER"),
                        _cg("fi_nc", "FLASHINFER", use_non_causal=True, is_xqa_arch=False), _cg("mla", "FLASHMLA"), _cg("other", "SOME_PLUGIN")],
              "expect": ["steps.fa3.result.value.support == 'ALWAYS' && steps.fa3.result.value.level == 3 && steps.fa2.result.value.support == 'UNIFORM_BATCH'",
                         "steps.tr.result.value.support == 'ALWAYS' && steps.fi.result.value.support == 'UNIFORM_BATCH' && steps.fi_nc.result.value.support == 'UNIFORM_SINGLE_TOKEN_DECODE'",
                         "steps.mla.result.value.level == 2 && steps.other.result.value.support == 'NEVER' && steps.other.result.value.level == 0"]})
    S.append({"id": "attention-cudagraph-support-flashinfer-dcp", "name": "FlashInfer under DCP graphs only single-token decodes", "fixtures": ["tp4-llama-70b", "attention-seed"],
              "config": {"decode-context-parallel-size": 2}, "steps": [_cg("fi", "FLASHINFER")],
              "expect": ["steps.fi.result.value.support == 'UNIFORM_SINGLE_TOKEN_DECODE'"]})
    S.append({"id": "attention-backend-registry-lookup", "name": "Registry lookups: names, paths without the class, classes, an unknown name, the unregistered CUSTOM placeholder", "fixtures": FX,
              "steps": [step("attention-backend-enum.getitem", {"name": "FLASH_ATTN"}, "g"), step("attention-backend-enum.getitem", {"name": "NOPE"}, "bad"),
                        step("attention-backend-enum.get-path", {"name": "TRITON_ATTN", "include_classname": False}, "mod"),
                        step("attention-backend-enum.get-class", {"name": "FLASHINFER_MLA_SPARSE"}, "c"),
                        step("attention-backend-enum.get-path", {"name": "CUSTOM"}, "custom"), step("attention-backend-enum.get-path", {"name": "NOPE"}, "nope"),
                        step("mamba-attention-backend-enum.get-class", {"name": "MAMBA2"}, "m"), step("mamba-attention-backend-enum.getitem", {"name": "MAMBA3"}, "m3")],
              "expect": ["steps.g.result.value.value == 'vllm.v1.attention.backends.flash_attn.FlashAttentionBackend'",
                         "!steps.bad.result.ok && steps.bad.result.error.code == 'value-error' && steps.bad.result.error.message.startsWith(\"Unknown attention backend: 'NOPE'\")",
                         "steps.mod.result.value.path == 'vllm.v1.attention.backends.triton_attn'",
                         "steps.c.result.value.class_name == 'FLASHINFER_MLA_SPARSE'",
                         "!steps.custom.result.ok && steps.custom.result.error.code == 'value-error' && !steps.nope.result.ok && steps.nope.result.error.code == 'key-error'",
                         "steps.m.result.value.class_name == 'MAMBA2_ATTN' && !steps.m3.result.ok"]})
    S.append({"id": "attention-backend-register-then-read", "name": "register_backend: a direct override, then a new name; get_class reads them back; clear_override reverts", "fixtures": FX,
              "state": {"attention-backend-enum": {"classes": {"my.module.MyCustomBackend": {"name": "MY_CUSTOM"}}}},
              "steps": [{"flow": "attn-register-backend", "as": "reg"},
                        step("attention-backend-enum.get-class", {"name": "CUSTOM"}, "cls"),
                        step("attention-backend-enum.is-overridden", {"name": "CUSTOM"}, "ov"),
                        step("attention-backend-enum.register-backend", {"backend": "CUSTOM_MLA", "is_new": True, "decorated_class": "pkg.mla.CustomMLA"}, "new"),
                        step("attention-backend-enum.get-path", {"name": "CUSTOM_MLA"}, "newp"),
                        step("attention-backend-enum.register", {"name": "CUSTOM_MLA", "value": "x.Y"}, "dup"),
                        step("attention-backend-enum.register", {"name": "get_class", "value": "x.Y"}, "res"),
                        step("attention-backend-enum.register-backend", {"backend": "FLASH_ATTN"}, "deco"),
                        step("attention-backend-enum.register-backend", {"backend": "NOPE"}, "nm"),
                        step("attention-backend-enum.is-overridden", {"name": "CUSTOM", "clear": True}, "clr"),
                        step("attention-backend-enum.get-path", {"name": "CUSTOM"}, "after"),
                        step("mamba-attention-backend-enum.register-backend", {"backend": "MY_SSM", "is_new": True, "has_class_path": True, "class_path": "pkg.ssm.Backend"}, "mb"),
                        step("mamba-attention-backend-enum.get-path", {"name": "MY_SSM"}, "mbp")],
              "expect": ["!steps.reg.result.value.decorator && steps.cls.result.value.class_name == 'MY_CUSTOM' && steps.ov.result.value.overridden",
                         "steps.new.result.value.decorator && steps.newp.result.value.path == 'pkg.mla.CustomMLA'",
                         "!steps.dup.result.ok && steps.dup.result.error.message.contains('already exists') && !steps.res.result.ok && steps.res.result.error.message.startsWith('Invalid or reserved')",
                         "steps.deco.result.value.decorator && steps.deco.result.value.path == null && !steps.nm.result.ok",
                         "!steps.clr.result.value.overridden && !steps.after.result.ok && steps.after.result.error.code == 'value-error'",
                         "steps.mbp.result.value.path == 'pkg.ssm.Backend'",
                         "'CUSTOM_MLA' in state['attention-backend-enum@rank0'].members && !('CUSTOM' in state['attention-backend-enum@rank0'].overrides)"]})
    S.append({"id": "attention-registry-branches", "name": "Mamba and MLA-prefill registries: duplicate, reserved and unknown names, decorator overrides, an unimportable override, clearing",
              "fixtures": FX,
              "steps": [step("mamba-attention-backend-enum.register", {"name": "MAMBA2", "value": "x.Y"}, "mdup"),
                        step("mamba-attention-backend-enum.register", {"name": "9bad", "value": "x.Y"}, "mbad"),
                        step("mamba-attention-backend-enum.get-path", {"name": "NOPE"}, "mnope"),
                        step("mamba-attention-backend-enum.get-path", {"name": "CUSTOM"}, "mcust"),
                        step("mamba-attention-backend-enum.register-backend", {"backend": "LINEAR", "decorated_class": "pkg.lin.MyLinear"}, "mdeco"),
                        step("mamba-attention-backend-enum.register-backend", {"backend": "NOPE"}, "mnm"),
                        step("mamba-attention-backend-enum.get-class", {"name": "LINEAR"}, "mcls"),
                        step("mamba-attention-backend-enum.is-overridden", {"name": "LINEAR", "clear": True}, "mclr"),
                        step("mla-prefill-backend-enum.getitem", {"name": "flash_attn"}, "pbad"),
                        step("mla-prefill-backend-enum.register", {"name": "FLASHINFER", "value": "x.Y"}, "pdup"),
                        step("mla-prefill-backend-enum.register", {"name": "register", "value": "x.Y"}, "pres"),
                        step("mla-prefill-backend-enum.get-path", {"name": "NOPE"}, "pnope"),
                        step("mla-prefill-backend-enum.register-mla-prefill-backend", {"backend": "FLASH_ATTN", "decorated_class": "pkg.fa.MyPrefill"}, "pdeco"),
                        step("mla-prefill-backend-enum.register-mla-prefill-backend", {"backend": "NOPE"}, "pnm"),
                        step("mla-prefill-backend-enum.is-overridden", {"name": "FLASH_ATTN", "clear": True}, "pclr"),
                        step("mla-prefill-backend-enum.is-overridden", {"name": "FLASH_ATTN"}, "pafter")],
              "expect": ["[steps.mdup, steps.mbad, steps.pdup, steps.pres, steps.pbad].all(s, !s.result.ok && s.result.error.code == 'value-error')",
                         "!steps.mnope.result.ok && steps.mnope.result.error.code == 'key-error' && !steps.mcust.result.ok && steps.mcust.result.error.code == 'value-error'",
                         "steps.mdeco.result.value.path == 'pkg.lin.MyLinear' && !steps.mnm.result.ok && !steps.mcls.result.ok && steps.mcls.result.error.code == 'import-error'",
                         "!steps.mclr.result.value.overridden && !steps.pnope.result.ok && steps.pdeco.result.value.decorator && !steps.pnm.result.ok",
                         "!steps.pclr.result.value.overridden && !steps.pafter.result.value.overridden",
                         "!('LINEAR' in state['mamba-attention-backend-enum@rank0'].overrides) && !('FLASH_ATTN' in state['mla-prefill-backend-enum@rank0'].overrides)"]})
    S.append({"id": "attention-misc-branches", "name": "Unimportable attention override; prefill-sized index-group batch; single-token verify; the indexer's row-sharding gate", "fixtures": FX,
              "steps": [step("attention-backend-enum.register-backend", {"backend": "FLEX_ATTENTION", "has_class_path": True, "class_path": "gone.module.Flex"}, "ov"),
                        step("attention-backend-enum.get-class", {"name": "FLEX_ATTENTION"}, "gone"),
                        step("sparse-mla-index-group-builder.init", {"logical_rows": 4, "max_decode_rows": 2}, "i"),
                        step("sparse-mla-index-group-builder.register-layer", {"is_index_producing_layer": False}, "l0"),
                        step("sparse-mla-index-group-builder.convert-logical-to-physical-topk", {"group": "g0", "layer_index": 0, "num_tokens": 4}, "fb"),
                        step("aiter-mla-helper.use-gluon-verify", {"num_heads": 5, "max_qo_len": 1, "gluon_build_available": True}, "v1"),
                        {"flow": "attn-indexer-row-shard-gate", "as": "gate"},
                        {"flow": "attn-indexer-row-shard-gate", "input": {"cudagraph_mode": "FULL"}, "as": "full"}],
              "expect": ["!steps.gone.result.ok && steps.gone.result.error.code == 'import-error'",
                         "steps.l0.result.value.group == 'g0' && steps.fb.result.value.path == 'per-layer'",
                         "!steps.v1.result.value.use_gluon && steps.gate.result.value.supported && !steps.full.result.value.supported",
                         "state['attention-backend-enum@rank0'].overrides['FLEX_ATTENTION'] == 'gone.module.Flex' && !state['sparse-mla-index-group-builder@rank0'].groups.g0.has_indexer"]})
    S.append({"id": "attention-mla-prefill-select", "name": "MLA prefill selection: explicit FLASH_ATTN on SM90, explicit FLASHINFER refused on SM90, unknown class, auto", "fixtures": FX,
              "steps": [{"flow": "attn-mla-prefill-select", "input": {"mla_prefill_backend": "FLASH_ATTN"}, "as": "fa"},
                        {"flow": "attn-mla-prefill-select", "input": {"mla_prefill_backend": "FLASHINFER"}, "as": "fi"},
                        step("mla-prefill-backend-enum.register-mla-prefill-backend", {"backend": "MISSING", "is_new": True, "has_class_path": True, "class_path": "missing.module.Backend"}, "reg"),
                        {"flow": "attn-mla-prefill-select", "input": {"mla_prefill_backend": "MISSING"}, "as": "zen"},
                        {"flow": "attn-mla-prefill-select", "input": {"mla_prefill_backend": "CUSTOM"}, "as": "cust"},
                        {"flow": "attn-mla-prefill-select", "input": {"mla_prefill_backend": "FLASH_ATTN", "mla_dimensions": [192, 128, 128], "dtype": "float32"}, "as": "dims"},
                        {"flow": "attn-mla-prefill-select", "input": {}, "as": "auto"},
                        {"flow": "attn-mla-prefill-select", "input": {"is_cpu": True, "mla_prefill_backend": "FLASHINFER", "has_model_config": False}, "as": "cpu"}],
              "expect": ["steps.fa.result.value.backend == 'FLASH_ATTN' && !steps.fa.result.value.auto",
                         "!steps.fi.result.ok && steps.fi.result.error.code == 'value-error' && steps.fi.result.error.message.contains('compute capability 9.0 not supported')",
                         "!steps.zen.result.ok && steps.zen.result.error.message.endsWith(\"['ImportError']\") && !steps.cust.result.ok",
                         "!steps.dims.result.ok && steps.dims.result.error.message.contains('dtype float32 not supported') && steps.dims.result.error.message.contains('MLA dimensions')",
                         "steps.auto.result.value.auto && steps.cpu.result.value.auto",
                         "state['mla-prefill-backend-enum@rank0'].overrides['MISSING'] == 'missing.module.Backend'"]})
    S.append({"id": "attention-mla-prefill-validate-no-capability", "name": "No device capability, and a backend with missing dependencies", "fixtures": FX,
              "steps": [step("mla-prefill-backend.validate-configuration", {"has_device_capability": False,
                                                                            "backend_cls": {"name": "TOKENSPEED_MLA", "capability_majors": [10], "dtypes": ["float16", "bfloat16"], "available": False, "mla_dimensions": [[128, 64, 128]]}}, "v")],
              "expect": ["steps.v.result.value.invalid_reasons == ['device capability not available', 'required dependencies not available']"]})
    S.append({"id": "attention-mla-kv-cache-spec-dtypes", "name": "MLA spec per cache dtype: auto (bf16 latent rows), fp8 per-tensor, the 656-byte fp8_ds_mla blob, a sliding-window MLA layer", "fixtures": FX,
              "config": {"block-size": 64},
              "steps": [{"flow": "attn-mla-kv-cache-spec", "as": "auto"},
                        {"flow": "attn-mla-kv-cache-spec", "input": {"kv_cache_dtype": "fp8"}, "as": "fp8"},
                        {"flow": "attn-mla-kv-cache-spec", "input": {"kv_cache_dtype": "fp8_ds_mla", "has_indexer": True}, "as": "ds"},
                        {"flow": "attn-mla-kv-cache-spec", "input": {"kv_cache_dtype": "nvfp4_ds_mla"}, "as": "nv"},
                        {"flow": "attn-mla-kv-cache-spec", "input": {"sliding_window": 128, "has_indexer": True}, "as": "sw"}],
              "expect": ["steps.auto.result.value.kv_quant_mode == 'none' && steps.auto.result.value.page_size_bytes == 64 * 576 * 2 && steps.auto.result.value.num_kv_heads == 1",
                         "steps.fp8.result.value.kv_quant_mode == 'fp8_per_tensor' && steps.fp8.result.value.page_size_bytes == 64 * 576",
                         "steps.ds.result.value.cache_dtype_str == 'fp8_ds_mla' && steps.ds.result.value.page_size_bytes == 64 * 656 && steps.ds.result.value.is_index_group_leader",
                         "steps.nv.result.value.kv_quant_mode == 'nvfp4_ds_mla' && steps.nv.result.value.page_size_bytes == 64 * 352",
                         "steps.sw.result.value.spec_class == 'sliding_window_mla' && steps.sw.result.value.sliding_window == 128 && !steps.sw.result.value.is_index_group_leader"]})
    S.append({"id": "attention-mla-bind-and-workspace", "name": "bind_kv_cache warm-up on flat sparse layouts; the chunked-prefill workspace (64K cap)", "fixtures": FX,
              "steps": [step("mla-attention.bind-kv-cache", {"backend": "FLASHMLA_SPARSE", "kv_cache_dtype": "auto", "enable_jit_warmup": True, "block_stride": 36864, "row_width": 576}, "flat"),
                        step("mla-attention.bind-kv-cache", {"backend": "FLASHMLA_SPARSE", "kv_cache_dtype": "fp8_ds_mla", "enable_jit_warmup": True}, "ds"),
                        step("mla-attention.bind-kv-cache", {"backend": "FLASHINFER_MLA_SPARSE", "enable_jit_warmup": True, "block_stride": 1000, "row_width": 576}, "odd"),
                        step("mla-attention.chunked-prefill-workspace-size", {}, "w")],
              "expect": ["steps.flat.result.value.flat && steps.flat.result.value.warmup_block_stride_rows == 64",
                         "!steps.ds.result.value.flat && steps.ds.result.value.warmup_block_stride_rows == null",
                         "!steps.odd.result.ok && steps.odd.result.error.code == 'assertion-error'",
                         "steps.w.result.value.workspace_tokens == 65536"]})
    S.append({"id": "attention-mla-workspace-small-dcp", "name": "Short context under DCP=3 x interleave 1: 4 pages per sequence, aligned to lcm(16, 3)", "fixtures": FX,
              "config": {"decode-context-parallel-size": 3, "max-model-len": 100, "max-num-seqs": 2},
              "steps": [step("mla-attention.chunked-prefill-workspace-size", {}, "w")],
              "expect": ["steps.w.result.value.alignment == 48 && steps.w.result.value.workspace_tokens == 816"]})
    S.append({"id": "attention-sm90-sparse-build-paths", "name": "SM90 sparse build: exact lengths without a CPU bound, adaptive verification bounds, and a plan reused while it still bounds every row",
              "fixtures": FX,
              "steps": [{"flow": "attn-sm90-sparse-build", "input": {"query_start_loc_cpu": [0, 2, 5], "seq_lens": [3000, 4], "has_seq_lens_cpu_upper_bound": False,
                                                                      "num_prefills": 0, "index_topk": 2048, "index_kpool": 4}, "as": "exact"},
                        {"flow": "attn-sm90-sparse-build", "input": {"query_start_loc_cpu": [0]}, "as": "empty"},
                        {"flow": "attn-sm90-sparse-build", "input": {"query_start_loc_cpu": [0, 2, 4], "seq_lens_cpu_upper_bound": [10, 30], "adaptive_verification": True, "num_prefills": 0}, "as": "adapt"},
                        {"flow": "attn-sm90-sparse-build", "input": {"query_start_loc_cpu": [0, 2, 4], "seq_lens_cpu_upper_bound": [40, 60], "num_prefills": 0}, "as": "reuse"},
                        {"flow": "attn-sm90-sparse-build", "input": {"query_start_loc_cpu": [0, 2, 4], "seq_lens_cpu_upper_bound": [400, 600], "num_prefills": 0}, "as": "grow"},
                        step("flashinfer-mla-sparse-sm90-state.plan", {"capturing": True}, "cap")],
              "expect": ["steps.exact.result.value.exact && steps.exact.result.value.kv_lens == [2048 + 2999 % 4, 2048 + 3000 % 4, 2, 3, 4]",
                         "!steps.adapt.result.value.exact && steps.adapt.result.value.kv_lens == [30, 30, 30, 30] && steps.adapt.result.value.replanned",
                         "steps.reuse.result.value.kv_lens == [39, 40, 59, 60] && !steps.reuse.result.value.replanned && steps.grow.result.value.replanned",
                         "steps.empty.result.value.num_rows == 0",
                         "!steps.cap.result.ok && steps.cap.result.error.code == 'runtime-error'",
                         "state['flashinfer-mla-sparse-sm90-state@rank0'].planned_num_tokens == 4"]})
    mq = lambda as_, nd, mha: {"flow": "attn-sm90-sparse-build", "as": as_,
                               "input": {"query_start_loc_cpu": [0, 1, 6] if nd else [0, 5], "seq_lens_cpu_upper_bound": [1402, 5] if nd else [5],
                                         "num_prefills": 1, "num_decode_tokens": nd, "use_sparse_mha": mha}}
    S.append({"id": "attention-sm90-builder-plans-mqa-rows", "name": "MHA-routed prefill rows are left out of the SM90 plan; without MHA every row is planned (test_builder_plans_only_rows_dispatched_to_mqa)",
              "fixtures": FX, "steps": [mq("a", 1, False), mq("b", 1, True), mq("c", 0, False), mq("d", 0, True)],
              "expect": ["steps.a.result.value.num_rows == 6 && steps.a.result.value.kv_lens == [1402, 1, 2, 3, 4, 5]",
                         "steps.b.result.value.num_rows == 1 && steps.b.result.value.kv_lens == [1402]",
                         "steps.c.result.value.num_rows == 5 && steps.c.result.value.kv_lens == [1, 2, 3, 4, 5]",
                         "steps.d.result.value.num_rows == 0 && steps.d.result.value.kv_lens == []"]})
    S.append({"id": "attention-sparse-backend-combinations", "name": "Sparse-MLA backend combination rules (FlashInfer TRT-LLM and FlashMLA)", "fixtures": FX,
              "steps": [step("flashinfer-mla-sparse-backend.supports-combination", {}, "ok"),
                        step("flashinfer-mla-sparse-backend.supports-combination", {"pcp_size": 2, "dcp_size": 2}, "cp"),
                        step("flashinfer-mla-sparse-backend.supports-combination", {"kv_cache_dtype": "fp8_ds_mla"}, "ds"),
                        step("flashinfer-mla-sparse-backend.supports-combination", {"qk_rope_head_dim": 0, "qk_nope_head_dim": 192}, "nope"),
                        step("flashinfer-mla-sparse-backend.supports-combination", {"qk_nope_head_dim": 64}, "dims"),
                        step("flashinfer-mla-sparse-backend.supports-combination", {"has_index_topk": False}, "dense"),
                        step("flashmla-sparse-backend.supports-combination", {"device_capability_major": 9}, "fm"),
                        step("flashmla-sparse-backend.supports-combination", {"head_size": 512, "device_capability_major": 9, "qk_rope_head_dim": 0}, "glm"),
                        step("flashmla-sparse-backend.supports-combination", {"head_size": 512, "device_capability_major": 9, "qk_rope_head_dim": 64}, "rope512"),
                        step("flashmla-sparse-backend.supports-combination", {"head_size": 512, "device_capability_major": 10}, "sm100"),
                        step("flashmla-sparse-backend.supports-combination", {"kv_cache_dtype": "nvfp4_ds_mla", "device_capability_major": 9}, "nv")],
              "expect": ["steps.ok.result.value.reason == null && steps.fm.result.value.reason == null && steps.glm.result.value.reason == null",
                         "steps.cp.result.value.reason.contains('PCP+DCP') && steps.ds.result.value.reason.contains('fp8_ds_mla')",
                         "steps.nope.result.value.reason.contains('no-rope') && steps.dims.result.value.reason.contains('[128, 192]') && steps.dense.result.value.reason.contains('index_topk')",
                         "steps.rope512.result.value.reason.contains('rope-free') && steps.sm100.result.value.reason.contains('on SM90') && steps.nv.result.value.reason.contains('SM100')"]})
    S.append({"id": "attention-index-group-shared-convert", "name": "Index groups: a decode-sized batch converts once for the group; a new indexer layer opens a second group", "fixtures": FX,
              "steps": [step("sparse-mla-index-group-builder.init", {"logical_rows": 8, "max_decode_rows": 2}, "i"),
                        step("sparse-mla-index-group-builder.register-layer", {"is_index_producing_layer": True}, "l0"),
                        step("sparse-mla-index-group-builder.register-layer", {"is_index_producing_layer": False}, "l1"),
                        step("sparse-mla-index-group-builder.register-layer", {"is_index_producing_layer": True}, "l2"),
                        step("sparse-mla-index-group-builder.convert-logical-to-physical-topk", {"group": "g0", "layer_index": 0, "num_tokens": 2, "return_valid_counts": True}, "c0"),
                        step("sparse-mla-index-group-builder.convert-logical-to-physical-topk", {"group": "g0", "layer_index": 1, "num_tokens": 2}, "c1"),
                        step("sparse-mla-index-group-builder.convert-logical-to-physical-topk", {"group": "g9", "layer_index": 0, "num_tokens": 2}, "bad")],
              "expect": ["steps.l0.result.value.group == 'g0' && steps.l1.result.value.group == 'g0' && steps.l1.result.value.layer_index == 1 && steps.l2.result.value.group == 'g1'",
                         "steps.c0.result.value.converted && steps.c0.result.value.path == 'shared' && steps.c0.result.value.waited_on == 'logical_topk_ready'",
                         "!steps.c1.result.value.converted && steps.c1.result.value.path == 'shared'",
                         "!steps.bad.result.ok && steps.bad.result.error.code == 'key-error'",
                         "state['sparse-mla-index-group-builder@rank0'].groups.g0.num_layers == 2 && state['sparse-mla-index-group-builder@rank0'].groups.g0.workspace_rows == 3"]})
    S.append({"id": "attention-rocm-gluon-routing", "name": "AITER MLA Gluon routing: bf16 divisor heads keep Gluon on gfx950; fp8, non-divisors, asm mode, 2 GiB caches and DCP don't", "fixtures": FX,
              "steps": [step("aiter-mla-helper.use-gluon-decode", {"num_heads": 8, "gluon_build_available": True}, "d8"),
                        step("aiter-mla-helper.use-gluon-decode", {"num_heads": 8, "kv_cache_dtype": "fp8", "gluon_build_available": True}, "dfp8"),
                        step("aiter-mla-helper.use-gluon-decode", {"num_heads": 6, "gluon_build_available": True}, "d6"),
                        step("aiter-mla-helper.use-gluon-decode", {"num_heads": 16, "gluon_build_available": True}, "d16"),
                        step("aiter-mla-helper.use-gluon-decode", {"num_heads": 8, "gluon_build_available": False}, "dnob"),
                        step("aiter-mla-helper.use-gluon-decode", {"num_heads": 8, "gluon_build_available": True, "kv_cache_bytes": 4294967296}, "dbig"),
                        step("aiter-mla-helper.use-gluon-verify", {"num_heads": 5, "max_qo_len": 4, "gluon_build_available": True}, "v5"),
                        step("aiter-mla-helper.use-gluon-verify", {"num_heads": 5, "max_qo_len": 4, "causal": False, "gluon_build_available": True}, "vnc"),
                        step("aiter-mla-helper.use-gluon-verify", {"num_heads": 5, "max_qo_len": 4, "kv_cache_dtype": "fp8_e4m3", "gluon_build_available": True}, "vfp8"),
                        step("aiter-mla-helper.use-gluon-verify", {"num_heads": 5, "max_qo_len": 4, "gluon_build_available": False}, "vnob")],
              "expect": ["steps.d8.result.value.use_gluon && steps.v5.result.value.use_gluon",
                         "[steps.dfp8, steps.d6, steps.d16, steps.dnob, steps.dbig].all(s, !s.result.value.use_gluon)",
                         "[steps.vnc, steps.vfp8, steps.vnob].all(s, !s.result.value.use_gluon)"]})
    S.append({"id": "attention-rocm-gluon-asm-mode", "name": "VLLM_ROCM_AITER_MLA_ASM_PADDING=asm forces the asm decode; gluon mode keeps a non-divisor head count on Gluon", "fixtures": FX,
              "config": {"vllm-rocm-aiter-mla-asm-padding": "asm"},
              "steps": [step("aiter-mla-helper.use-gluon-decode", {"num_heads": 8, "gluon_build_available": True}, "d"),
                        step("aiter-mla-helper.use-gluon-verify", {"num_heads": 8, "max_qo_len": 4, "gluon_build_available": True}, "v")],
              "expect": ["!steps.d.result.value.use_gluon && !steps.v.result.value.use_gluon"]})
    S.append({"id": "attention-rocm-gluon-mode-gluon", "name": "gluon mode: a 6-head decode stays on Gluon", "fixtures": FX,
              "config": {"vllm-rocm-aiter-mla-asm-padding": "gluon"},
              "steps": [step("aiter-mla-helper.use-gluon-decode", {"num_heads": 6, "gluon_build_available": True}, "d")],
              "expect": ["steps.d.result.value.use_gluon"]})
    S.append({"id": "attention-rocm-dcp-route-and-pages", "name": "DCP decode routes; page-index expansion of a ragged batch; per-sequence context lengths; the int64 row offset; the ragged prefill launch",
              "fixtures": FX,
              "steps": [step("rocm-aiter-mla.select-dcp-decode-route", {"max_qo_len": 1}, "plain"),
                        step("rocm-aiter-mla.select-dcp-decode-route", {"max_qo_len": 4, "asm_selected": True}, "cprr"),
                        step("rocm-aiter-mla.select-dcp-decode-route", {"max_qo_len": 2, "asm_selected": True}, "seg"),
                        step("rocm-aiter-mla.select-dcp-decode-route", {"max_qo_len": 2, "cp_interleave": 4}, "none"),
                        step("rocm-aiter-mla.expand-page-indices-kernel", {"block_table": [[3, 7], [5, 0], [9, 9]], "cu_num_tokens": [0, 5, 5, 7], "kernel_block_size": 4, "out_len": 8}, "pg"),
                        step("rocm-aiter-mla-sparse-ops.per-sequence-context-lens", {"shape": [4, 3], "rows": [[8190, 8191, 8192], [1498, 1499, 1500], [2998, 2999, 3000], [698, 699, 700]]}, "tbl"),
                        step("rocm-aiter-mla-sparse-ops.sparse-kv-row-offset", {"slot": 5000000, "stride": 512}, "off"),
                        step("rocm-aiter-mla-sparse-ops.rocm-sparse-attn-prefill-ragged-triton", {}, "pf"),
                        step("rocm-aiter-mla-sparse-ops.rocm-sparse-attn-prefill-ragged-triton", {"indptr_len": 4}, "pfi"),
                        step("rocm-aiter-mla-sparse-ops.rocm-sparse-attn-prefill-ragged-triton", {"head_dim": 512}, "pfd")],
              "expect": ["steps.plain.result.value.route == 'plain' && steps.cprr.result.value.route == 'cprr' && steps.seg.result.value.route == 'segmented'",
                         "!steps.none.result.ok && steps.none.result.error.code == 'runtime-error'",
                         "steps.pg.result.value.page_indices == [12, 13, 14, 15, 28, 36, 37, -1] && steps.pg.result.value.num_chunks == 1",
                         "!steps.tbl.result.value.same_tensor && steps.tbl.result.value.values == [8192, 1500, 3000, 700]",
                         "steps.off.result.value.offset == 2560000000 && steps.off.result.value.exceeds_int32",
                         "steps.pf.result.value.grid == [4, 1] && steps.pf.result.value.block_k == 16",
                         "!steps.pfi.result.ok && !steps.pfd.result.ok && steps.pfd.result.error.code == 'assertion-error'"]})
    S.append({"id": "attention-selector-backend-per-kind", "name": "backend_per_kind: each decoder layer's kind picks its backend; kinds not in the map fall back to the global backend",
              "fixtures": FX,
              "config": {"attention-backend-per-kind": {"mla_attention": "FLASHINFER_MLA", "sliding_window": "FLEX_ATTENTION"}},
              "steps": [step("selector.get-attn-backend", {"head_size": 128, "dtype": "bfloat16", "kv_cache_dtype": "auto", "has_sliding_window": False}, "full"),
                        step("selector.get-attn-backend", {"head_size": 128, "dtype": "bfloat16", "kv_cache_dtype": "auto", "has_sliding_window": True}, "sw"),
                        step("selector.get-attn-spec-kind", {"use_mla": True, "has_sliding_window": True}, "k1"),
                        step("selector.get-attn-spec-kind", {"attn_type": "encoder_only"}, "k2"),
                        step("selector.get-attn-spec-kind", {"attn_type": "encoder_decoder"}, "k3")],
              # The platform call's argument is the point: the backend handed to the platform per kind.
              "expect": ["steps.full.result.ok && steps.sw.result.ok && !steps.sw.result.value.cached",
                         "trace.exists(e, e.type == 'call.start' && e.interface == 'cuda-platform.get-attn-backend-cls' && e.input.attn_selector_config.has_sliding_window && e.input.selected_backend == 'FLEX_ATTENTION')",
                         "trace.exists(e, e.type == 'call.start' && e.interface == 'cuda-platform.get-attn-backend-cls' && !e.input.attn_selector_config.has_sliding_window && e.input.selected_backend == null)",
                         "steps.k1.result.value.kind == 'sliding_window_mla' && steps.k2.result.value.kind == 'encoder_only_attention' && steps.k3.result.value.kind == 'cross_attention'"]})
    return S


def oracle_doc():
    """build-oracle/round4/attention.yaml: the translated round-4 unit tests."""
    sc = []
    sc.append({
        "id": "oracle4-attention-per-sequence-context-lens-unchanged",
        "name": "tests/v1/attention/test_rocm_paged_mqa_context_lens.py:30 test_per_sequence_input_is_unchanged",
        "description": "context_lens shaped (4,) and (4, 1) are already one length per sequence: _per_sequence_context_lens returns the same tensor object.",
        "fixtures": W,
        "steps": [step("rocm-aiter-mla-sparse-ops.per-sequence-context-lens", {"shape": [4], "rows": [[1], [2], [3], [4]]}, "flat"),
                  step("rocm-aiter-mla-sparse-ops.per-sequence-context-lens", {"shape": [4, 1], "rows": [[1], [2], [3], [4]]}, "col")],
        "expect": ["steps.flat.result.value.same_tensor && steps.flat.result.value.shape == [4]",
                   "steps.col.result.value.same_tensor && steps.col.result.value.shape == [4, 1]"]})
    path = "tests.v1.attention.test_mla_prefill_registry.CustomMLAPrefillBackend"
    sc.append({
        "id": "oracle4-attention-register-mla-prefill-string-direct",
        "name": "tests/v1/attention/test_mla_prefill_registry.py:197 test_register_mla_prefill_backend_with_string_name_direct",
        "description": "register_mla_prefill_backend('STRING_DIRECT', <CustomMLAPrefillBackend path>) creates the member and its override; the member is overridden and get_class().get_name() is CUSTOM; clear_override removes the override. The test module's class is importable, so the scenario adds it to the registry's importable classes.",
        "fixtures": W,
        "state": {"mla-prefill-backend-enum": {"classes": {path: {"name": "CUSTOM"}}}},
        "steps": [step("mla-prefill-backend-enum.register-mla-prefill-backend", {"backend": "STRING_DIRECT", "is_new": True, "has_class_path": True, "class_path": path}, "reg"),
                  step("mla-prefill-backend-enum.getitem", {"name": "STRING_DIRECT"}, "member"),
                  step("mla-prefill-backend-enum.is-overridden", {"name": "STRING_DIRECT"}, "ov"),
                  step("mla-prefill-backend-enum.get-class", {"name": "STRING_DIRECT"}, "cls"),
                  step("mla-prefill-backend-enum.is-overridden", {"name": "STRING_DIRECT", "clear": True}, "clr"),
                  step("mla-prefill-backend-enum.is-overridden", {"name": "STRING_DIRECT"}, "after")],
        "expect": ["steps.reg.result.ok && steps.member.result.value.name == 'STRING_DIRECT'",
                   "steps.ov.result.value.overridden", "steps.cls.result.value.class_name == 'CUSTOM'",
                   "!steps.after.result.value.overridden",
                   "!('STRING_DIRECT' in state['mla-prefill-backend-enum@rank0'].overrides)"]})
    steps, asv = [], []
    for d in ["fp8", "fp8_e4m3", "fp8_e5m2", "auto", "bfloat16"]:
        for h in [8, 16, 32, 96]:
            for q in [2, 3, 8]:
                a = f"v_{d}_{h}_{q}"
                steps.append(step("aiter-mla-helper.use-gluon-verify", {"num_heads": h, "max_qo_len": q, "kv_cache_dtype": d, "dcp_world_size": 8, "gluon_build_available": True}, a))
                asv.append(a)
    sc.append({
        "id": "oracle4-attention-dcp-multitoken-verify-never-gluon",
        "name": "tests/v1/attention/test_rocm_aiter_mla_fp8_decode_routing.py:90 test_dcp_multitoken_verify_never_uses_gluon",
        "description": "With Gluon available (gfx950 pinned, mode auto), no DCP=8 multi-token verify uses Gluon, for every dtype, head count and query length the test sweeps.",
        "fixtures": W, "config": {"vllm-rocm-aiter-mla-asm-padding": "auto"},
        "steps": steps,
        "expect": ["[" + ", ".join(f"steps.{a}" for a in asv) + "].all(s, s.result.ok && !s.result.value.use_gluon)"]})
    sc.append({
        "id": "oracle4-attention-index-group-prefill-fallback",
        "name": "tests/v1/attention/test_sparse_mla_backends.py:1977 test_sparse_mla_index_group_falls_back_for_prefill_sized_batch",
        "description": "A builder over 4 logical rows with max_decode_rows=2 has a 3-row workspace. The leader and the follower land in one group, and a 4-row batch is too large for the shared workspace, so each layer converts its own indices: two convert calls, equal results.",
        "fixtures": W,
        "steps": [step("sparse-mla-index-group-builder.init", {"logical_rows": 4, "max_decode_rows": 2}, "init"),
                  step("sparse-mla-index-group-builder.register-layer", {"is_index_producing_layer": True}, "leader"),
                  step("sparse-mla-index-group-builder.register-layer", {"is_index_producing_layer": False}, "follower"),
                  step("sparse-mla-index-group-builder.convert-logical-to-physical-topk", {"group": "g0", "layer_index": 0, "num_tokens": 4}, "lc"),
                  step("sparse-mla-index-group-builder.convert-logical-to-physical-topk", {"group": "g0", "layer_index": 1, "num_tokens": 4}, "fc")],
        "expect": ["steps.follower.result.value.group == steps.leader.result.value.group",
                   "steps.lc.result.value.converted && steps.fc.result.value.converted",
                   "steps.lc.result.value.path == 'per-layer' && steps.fc.result.value.path == 'per-layer'",
                   "state['sparse-mla-index-group-builder@rank0'].groups.g0.workspace_rows == 3"]})
    sc.append({
        "id": "oracle4-attention-mla-prefill-string-parses",
        "name": "tests/v1/attention/test_mla_prefill_selector.py:600 test_valid_string_parses_to_enum",
        "description": "AttentionConfig's mla_prefill_backend validator (config-platform's) parses a string with MLAPrefillBackendEnum[value.upper()]; FLASH_ATTN resolves to the FLASH_ATTN member, and an unknown name is a ValueError (the sibling test).",
        "fixtures": W,
        "steps": [step("mla-prefill-backend-enum.getitem", {"name": "FLASH_ATTN"}, "fa"), step("mla-prefill-backend-enum.getitem", {"name": "NONEXISTENT"}, "bad")],
        "expect": ["steps.fa.result.value.name == 'FLASH_ATTN' && steps.fa.result.value.value == 'vllm.v1.attention.backends.mla.prefill.flash_attn.FlashAttnPrefillBackend'",
                   "!steps.bad.result.ok && steps.bad.result.error.message.startsWith('Unknown MLA prefill backend')"]})
    return {"schema_version": 1, "id": "vllm", "scenarios": sc}

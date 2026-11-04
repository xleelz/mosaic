"""Flows and scenarios of the attention fragment."""
from core import FA, SEL, BK, FAU, TA, TUA, MAS, DCP, VIT, CPUMLA, CPUA, MLAP
from lib import C, Cfn, ln, fn

FX = ["tp1-llama-8b", "attention-seed"]
CALLED = "trace.exists(e, e.type == 'call.start' && e.interface == '{}')"
NOT_CALLED = "!trace.exists(e, e.type == 'call.start' && e.interface == '{}')"


KEEP_INTERNAL = False  # round 3: kernel-launch checks go through results, not the trace


def called(i):
    return CALLED.format(i) if KEEP_INTERNAL else None


def not_called(i):
    return NOT_CALLED.format(i) if KEEP_INTERNAL else None


def keep(expr):
    """An internal (trace or state) assertion kept on purpose: the internal path is the test's point."""
    return expr


def err(code):
    return f"!result.ok && result.error.code == '{code}'"


MD_DECODE = {"num_actual_tokens": 4, "num_reqs": 4, "max_query_len": 1, "max_seq_len": 120,
             "seq_lens": [100, 120, 80, 64], "block_table": [[0, 1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12, 13, 14], [15, 16, 17, 18, 19], [20, 21, 22, 23]],
             "slot_mapping": [99, 135, 271, 383], "causal": True, "causal_is_tensor": False, "has_scheduler_metadata": True,
             "max_num_splits": 32, "max_dcp_context_kv_len": 0, "num_decode_reqs": 0, "num_prefill_reqs": 0, "seq_threshold_3D": 16}
MD_PREFILL = {"num_actual_tokens": 17, "num_reqs": 2, "max_query_len": 16, "max_seq_len": 41, "seq_lens": [16, 41],
              "block_table": [[0], [1, 2, 3]], "slot_mapping": list(range(0, 16)) + [56],
              "causal": True, "causal_is_tensor": False, "has_scheduler_metadata": True, "max_num_splits": 32,
              "max_dcp_context_kv_len": 0, "num_decode_reqs": 0, "num_prefill_reqs": 0, "seq_threshold_3D": 16}
COMMON = {"num_reqs": 2, "num_actual_tokens": 17, "max_query_len": 16, "max_seq_len": 41, "query_lens": [16, 1],
          "seq_lens": [16, 41], "block_table": [[0], [1, 2, 3]], "slot_mapping": list(range(0, 16)) + [56],
          "causal": True, "causal_is_tensor": False, "causal_tensor_dtype": "int32", "common_prefix_len": 0,
          "has_cpu_seq_lens_upper_bound": True, "decode_query_threshold": 1}
FWD = {"attn_type": "decoder", "num_tokens": 4, "num_heads": 32, "num_kv_heads": 8, "head_size": 128, "kv_cache_dtype": "auto",
       "fa_version": 3, "dcp_world_size": 1, "has_output_scale": False, "has_output_block_scale": False,
       "has_alibi": False, "has_sinks": False, "kv_quant_mode": "none", "metadata": MD_DECODE}
VAL = {"backend": "FLASH_ATTN", "head_size": 128, "dtype": "bfloat16", "kv_cache_dtype": "auto", "block_size": None,
       "use_mla": False, "has_sink": False, "use_sparse": False, "use_mm_prefix": False, "use_per_head_quant_scales": False,
       "device_capability": {"major": 9, "minor": 0}, "attn_type": "decoder", "has_sliding_window": False, "use_rswa": False,
       "use_non_causal": False, "use_batch_invariant": False, "use_kv_connector": False, "use_pcp": False, "use_dcp": False,
       "fa_version": 3, "fa4_supported": True}


def flow(id_, name, iface, inp, sources, caller="gpu-worker", tags=None, desc=None):
    d = {"id": id_, "name": name, "entry": {"caller": caller, "interface": iface, "input": inp}, "sources": sources}
    if desc:
        d["description"] = desc
    if tags:
        d["tags"] = tags
    return d


def sc(id_, flow_, name, expect, inp=None, steps=None, config=None, faults=None):
    d = {"id": id_, "name": name, "fixtures": ["tp4-llama-70b", "attention-seed"] if "dcp" in id_ else FX}
    if flow_:
        d["flow"] = flow_
    if config:
        d["config"] = config
    if inp is not None:
        d["input"] = inp
    if steps:
        d["steps"] = steps
    if faults:
        d["faults"] = faults
    d["expect"] = [e for e in expect if e is not None]
    return d


def step(iface, inp, as_, caller="gpu-worker"):
    return {"interface": iface, "caller": caller, "input": inp, "as": as_}


def on_ranks(st, as_, n=4):
    """The same step on every TP rank at once: distributed's collectives meet at a rendezvous of
    tensor-parallel-size callers, so one rank alone would wait for its peers."""
    out = []
    for r in range(n):
        d = dict(st)
        d.update({"on": f"rank{r}", "await": False, "as": f"{as_}{r}"})
        out.append(d)
    return out


def flows_and_scenarios():
    F, S = [], []
    # 1 selection
    F.append(flow("attn-select-backend", "Select the attention backend for a layer", "selector.get-attn-backend",
                  {"head_size": 128, "dtype": "bfloat16", "kv_cache_dtype": "auto", "use_mla": False, "has_sink": False, "use_sparse": False,
                   "use_mm_prefix": False, "attn_type": "decoder", "has_sliding_window": False, "num_heads": 32},
                  [Cfn(SEL, "get_attn_backend")]))
    S += [
        sc("attention-select-backend-flash-attn", "attn-select-backend", "Llama-8B layer on CUDA: the platform returns FlashAttention",
           ["result.ok && result.value.backend_cls_path.endsWith('FlashAttentionBackend') && !result.value.cached",
            "calls['cuda-platform.get-attn-backend-cls'] == 1",
            "trace.exists(e, e.type == 'call.start' && e.interface == 'cuda-platform.get-attn-backend-cls' && (!has(e.input.selected_backend) || e.input.selected_backend == null) && (!has(e.input.attn_selector_config.block_size) || e.input.attn_selector_config.block_size == null))"]),
        sc("attention-select-backend-cache-hit", "attn-select-backend", "Second layer with the same config hits functools.cache",
           ["steps.first.result.ok && !steps.first.result.value.cached", "steps.second.result.value.cached",
            "calls['cuda-platform.get-attn-backend-cls'] == 1"],
           steps=[{"flow": "attn-select-backend", "as": "first"}, {"flow": "attn-select-backend", "as": "second"}]),
        sc("attention-select-backend-invalid-kv-dtype", "attn-select-backend", "Unknown kv_cache_dtype fails the assertion before the platform is asked",
           [err("assertion-error"), "calls['cuda-platform.get-attn-backend-cls'] == 0", not_called("cuda-platform.get-attn-backend-cls")],
           inp={"kv_cache_dtype": "int3"}),
        sc("attention-select-backend-forced-triton", "attn-select-backend", "--attention-backend TRITON_ATTN is passed to the platform as the selected backend",
           ["result.ok", "trace.exists(e, e.type == 'call.start' && e.interface == 'cuda-platform.get-attn-backend-cls' && e.input.selected_backend == 'TRITON_ATTN')"],
           config={"attention-backend": "TRITON_ATTN"}),
        sc("attention-select-backend-platform-refuses", "attn-select-backend", "The platform raises ValueError (no valid backend): it propagates",
           [err("value-error")],
           faults=[{"target": "cuda-platform.get-attn-backend-cls", "type": "error", "code": "value-error", "status": 0}]),
    ]
    # 2 validate
    F.append(flow("attn-validate-backend", "Validate a backend for a layer configuration", "attention-backend.validate-configuration", VAL,
                  [Cfn(BK, "validate_configuration")], caller="cuda-platform"))
    S += [
        sc("attention-validate-backend-fa-llama-ok", "attn-validate-backend", "FlashAttention serves Llama-8B on SM90 with FA3",
           ["result.ok && size(result.value.invalid_reasons) == 0", "trace.exists(e, e.type == 'call.end' && e.interface == 'attention-backend.validate-configuration')"]),
        sc("attention-validate-backend-fa2-fp8-sink-ampere", "attn-validate-backend", "SM80 + FA2: FP8 KV and sinks are rejected",
           ["result.ok", "'kv_cache_dtype not supported' in result.value.invalid_reasons", "'attention sinks not supported' in result.value.invalid_reasons",
            "'sink not supported on compute capability < 9.0' in result.value.invalid_reasons",
            "!result.value.invalid_reasons.exists(r, r.startsWith('FP8 KV cache requires FA3'))",
            "trace.exists(e, e.type == 'call.start' && e.interface == 'attention-backend.validate-configuration')"],
           inp={"device_capability": {"major": 8, "minor": 0}, "fa_version": 2, "kv_cache_dtype": "fp8", "has_sink": True, "fa4_supported": False}),
        sc("attention-validate-backend-fa-fp8-combination", "attn-validate-backend", "FlashAttention combination: FP8 KV on SM90 FA2 gets the FP8 reason; fp8_e5m2 always; FA4 head 512 on SM90 is fine; SM90 FP8 with an mm prefix needs Triton",
           ["result.ok", "result.value.invalid_reasons == ['kv_cache_dtype not supported', 'FP8 KV cache requires FA3 on SM90, FA4 with head_size=512 on SM90, or FA4 on SM100']"],
           inp={"device_capability": {"major": 9, "minor": 0}, "fa_version": 2, "kv_cache_dtype": "fp8"}),
        sc("attention-validate-backend-fa-capability-and-shape", "attn-validate-backend", "FlashAttention: head 100, block 8, Turing, mm-prefix without FA4, MLA, per-head scales on FA2",
           ["result.ok", "['head_size not supported', 'block_size not supported', 'compute capability not supported', 'partial multimodal token full attention not supported', 'MLA not supported', 'per-head quant scales not supported'].all(r, r in result.value.invalid_reasons)",
            "trace.exists(e, e.type == 'call.end' && e.interface == 'attention-backend.validate-configuration')"],
           inp={"head_size": 100, "block_size": 8, "device_capability": {"major": 7, "minor": 5}, "use_mm_prefix": True, "fa4_supported": False,
                "use_mla": True, "use_per_head_quant_scales": True, "fa_version": 2}),
        sc("attention-validate-backend-triton-limits", "attn-validate-backend", "Triton attention: head 16, float64, sparse, DCP and PCP rejected",
           ["result.ok", "['head_size not supported', 'dtype not supported', 'sparse not supported', 'DCP not supported', 'PCP not supported', 'kv_cache_dtype not supported'].all(r, r in result.value.invalid_reasons)",
            "trace.exists(e, e.type == 'call.end' && e.interface == 'attention-backend.validate-configuration')"],
           inp={"backend": "TRITON_ATTN", "head_size": 16, "dtype": "float64", "use_sparse": True, "use_dcp": True, "use_pcp": True, "kv_cache_dtype": "nvfp4"}),
        sc("attention-validate-backend-triton-int4-ok", "attn-validate-backend", "Triton accepts an INT4 per-token-head KV cache and sinks",
           ["result.ok && size(result.value.invalid_reasons) == 0", "trace.exists(e, e.type == 'call.end' && e.interface == 'attention-backend.validate-configuration')"],
           inp={"backend": "TRITON_ATTN", "kv_cache_dtype": "int4_per_token_head", "has_sink": True}),
        sc("attention-validate-backend-unknown", "attn-validate-backend", "A backend name outside the modeled classes fails like an enum lookup",
           [err("key-error"), "trace.exists(e, e.type == 'call.start' && e.interface == 'attention-backend.validate-configuration')"], inp={"backend": "NO_SUCH_BACKEND"}),
        sc("attention-validate-backend-other-classes", None, "FlashInfer, FlexAttention, TurboQuant and the MLA classes apply their own capability checks",
           ["steps.fi.result.ok && size(steps.fi.result.value.invalid_reasons) == 0",
            "'non-MLA not supported' in steps.mla_dense.result.value.invalid_reasons && 'head_size not supported' in steps.mla_dense.result.value.invalid_reasons",
            "size(steps.tmla.result.value.invalid_reasons) == 0",
            "'compute capability not supported' in steps.cutlass.result.value.invalid_reasons",
            "'kv_cache_dtype not supported' in steps.tq.result.value.invalid_reasons && size(steps.tq2.result.value.invalid_reasons) == 0",
            "'attention type encoder not supported' in steps.flex.result.value.invalid_reasons",
            "['sliding window not supported', 'batch invariance not supported'].all(r, r in steps.fmla.result.value.invalid_reasons)",
            "trace.exists(e, e.type == 'call.end' && e.interface == 'attention-backend.validate-configuration')"],
           steps=[{"flow": "attn-validate-backend", "input": {"backend": "FLASHINFER", "device_capability": {"major": 10, "minor": 0}, "fa_version": 4}, "as": "fi"},
                  {"flow": "attn-validate-backend", "input": {"backend": "FLASHMLA"}, "as": "mla_dense"},
                  {"flow": "attn-validate-backend", "input": {"backend": "TRITON_MLA", "use_mla": True, "head_size": 576}, "as": "tmla"},
                  {"flow": "attn-validate-backend", "input": {"backend": "CUTLASS_MLA", "use_mla": True, "head_size": 576}, "as": "cutlass"},
                  {"flow": "attn-validate-backend", "input": {"backend": "TURBOQUANT"}, "as": "tq"},
                  {"flow": "attn-validate-backend", "input": {"backend": "TURBOQUANT", "kv_cache_dtype": "turboquant_k8v4"}, "as": "tq2"},
                  {"flow": "attn-validate-backend", "input": {"backend": "FLEX_ATTENTION", "attn_type": "encoder"}, "as": "flex"},
                  {"flow": "attn-validate-backend", "input": {"backend": "FLASH_ATTN_MLA", "use_mla": True, "head_size": 576, "has_sliding_window": True, "use_batch_invariant": False}, "as": "fmla0"},
                  {"flow": "attn-validate-backend", "input": {"backend": "FLASHINFER_MLA", "use_mla": True, "head_size": 576, "has_sliding_window": True, "use_batch_invariant": True}, "as": "fmla"}]),
    ]
    # 3 fa version
    F.append(flow("attn-fa-version", "Resolve the FlashAttention version", "fa-utils.get-flash-attn-version",
                  {"platform": "cuda", "device_capability_major": 9, "supported_versions": [2, 3, 4], "requires_alibi": False,
                   "head_size": 128, "head_size_v": None, "has_sinks": False, "batch_invariant": False},
                  [Cfn(FAU, "get_flash_attn_version")]))
    fv = "trace.exists(e, e.type == 'call.end' && e.interface == 'fa-utils.get-flash-attn-version')"
    S += [
        sc("attention-fa-version-hopper", "attn-fa-version", "Hopper defaults to FA3", ["result.value.fa_version == 3", fv]),
        sc("attention-fa-version-ampere", "attn-fa-version", "Ampere falls back to FA2", ["result.value.fa_version == 2", fv], inp={"device_capability_major": 8}),
        sc("attention-fa-version-blackwell", "attn-fa-version", "Blackwell prefers FA4", ["result.value.fa_version == 4", fv], inp={"device_capability_major": 10}),
        sc("attention-fa-version-config-override", "attn-fa-version", "flash_attn_version=2 overrides the Hopper default", ["result.value.fa_version == 2", fv],
           config={"flash-attn-version": 2}),
        sc("attention-fa-version-fa3-on-blackwell", "attn-fa-version", "Requesting FA3 on Blackwell moves to FA4", ["result.value.fa_version == 4", fv],
           inp={"device_capability_major": 10}, config={"flash-attn-version": 3}),
        sc("attention-fa-version-alibi", "attn-fa-version", "ALiBi layers need FA2", ["result.value.fa_version == 2", fv], inp={"requires_alibi": True}),
        sc("attention-fa-version-hd512-upgrade", "attn-fa-version", "head_size 512 on SM90 upgrades FA3 to FA4", ["result.value.fa_version == 4", fv], inp={"head_size": 512}),
        sc("attention-fa-version-batch-invariant", "attn-fa-version", "Batch invariance can't use FA4", ["result.value.fa_version == 2", fv],
           inp={"device_capability_major": 10, "batch_invariant": True}),
        sc("attention-fa-version-tmem-limit", "attn-fa-version", "FA4 on Blackwell with head 192/192 falls back to FA2 (TMEM)", ["result.value.fa_version == 2", fv],
           inp={"device_capability_major": 10, "head_size": 192, "head_size_v": 192}),
        sc("attention-fa-version-xpu-rocm", None, "XPU is always FA2; ROCm returns None",
           ["steps.x.result.value.fa_version == 2", "!has(steps.r.result.value.fa_version) || steps.r.result.value.fa_version == null", fv],
           steps=[{"flow": "attn-fa-version", "input": {"platform": "xpu"}, "as": "x"}, {"flow": "attn-fa-version", "input": {"platform": "rocm"}, "as": "r"}]),
        sc("attention-fa-version-unsupported", "attn-fa-version", "A forced version the build lacks yields None (assertion caught)", ["!has(result.value.fa_version) || result.value.fa_version == null", fv],
           inp={"supported_versions": [2]}, config={"flash-attn-version": 3}),
    ]
    # 4 FA build
    F.append(flow("attn-flash-build-metadata", "Build FlashAttention metadata for a step", "flash-attention-metadata-builder.build",
                  {"common": COMMON, "fast_build": False, "fa_version": 3, "use_full_cuda_graph": True, "max_cudagraph_size": 512,
                   "dcp_world_size": 1, "batch_invariant": False, "sliding_window_configs": 1},
                  [Cfn(FA, "build", ln(FA, r"^class FlashAttentionMetadataBuilder"))]))
    gsm = "flash-attn-interface.get-scheduler-metadata"
    S += [
        sc("attention-flash-build-metadata-fa3-aot", "attn-flash-build-metadata", "FA3: AOT scheduler metadata and pinned splits for a graph-sized batch",
           ["result.ok && result.value.has_scheduler_metadata && result.value.max_num_splits == 32", "result.value.block_table == [[0], [1, 2, 3]]",
            called(gsm), "calls['flash-attn-interface.vllm-fa3-get-scheduler-metadata'] == 1"]),
        sc("attention-flash-build-metadata-fa2", "attn-flash-build-metadata", "FA2: no AOT scheduling, kernel-chosen splits",
           ["result.ok && !result.value.has_scheduler_metadata && result.value.max_num_splits == 0", not_called(gsm)], inp={"fa_version": 2}),
        sc("attention-flash-build-metadata-fast-build", "attn-flash-build-metadata", "Spec-decode fast builds skip AOT scheduling",
           ["result.ok && !result.value.has_scheduler_metadata", not_called(gsm)], inp={"fast_build": True}),
        sc("attention-flash-build-metadata-batch-invariant", "attn-flash-build-metadata", "Batch invariance: one split and no AOT",
           ["result.value.max_num_splits == 1 && !result.value.has_scheduler_metadata", not_called(gsm)], inp={"batch_invariant": True}),
        sc("attention-flash-build-metadata-beyond-graph", "attn-flash-build-metadata", "A batch above the largest CUDA graph lets FA3 choose splits",
           ["result.value.max_num_splits == 0 && result.value.has_scheduler_metadata", called(gsm)], inp={"max_cudagraph_size": 8}),
        sc("attention-flash-build-metadata-mixed-windows", "attn-flash-build-metadata", "Layers with different sliding windows turn AOT off",
           ["!result.value.has_scheduler_metadata", not_called(gsm)], inp={"sliding_window_configs": 2}),
        sc("attention-flash-build-metadata-dcp", "attn-flash-build-metadata", "DCP=2: per-rank context bound ceil(41/2)=21 and non-causal AOT metadata",
           ["result.value.max_dcp_context_kv_len == 21 && result.value.num_decode_reqs == 1 && result.value.num_prefill_reqs == 1",
            "trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attn-interface.get-scheduler-metadata' && e.input.causal == false)"],
           inp={"dcp_world_size": 2, "common": {"has_cpu_seq_lens_upper_bound": True}}),
        sc("attention-flash-build-metadata-dcp-no-cpu-bound", "attn-flash-build-metadata", "DCP=2 without CPU sequence-length bounds: every request counts as an extend (split_dcp_context_queries)",
           ["result.value.num_decode_reqs == 0 && result.value.num_prefill_reqs == 2 && result.value.max_dcp_context_kv_len == 21", called(gsm)],
           inp={"dcp_world_size": 2, "common": {"has_cpu_seq_lens_upper_bound": False}}),
        sc("attention-flash-build-metadata-dcp-no-context", "attn-flash-build-metadata", "DCP=2 with no cached context skips context attention",
           ["result.value.max_dcp_context_kv_len == 0 && !result.value.has_scheduler_metadata", not_called(gsm)],
           inp={"dcp_world_size": 2, "common": {"query_lens": [16, 1], "seq_lens": [16, 1], "max_seq_len": 16, "has_cpu_seq_lens_upper_bound": True}}),
        sc("attention-flash-build-metadata-defaults", None, "A caller passing only common_attn_metadata gets the code's defaults (FA3 AOT, 32 graph splits)",
           ["steps.d.result.value.has_scheduler_metadata && steps.d.result.value.max_num_splits == 32", called(gsm)],
           steps=[step("flash-attention-metadata-builder.build", {"common": {k: COMMON[k] for k in ("num_reqs", "num_actual_tokens", "max_query_len", "max_seq_len", "query_lens", "seq_lens", "block_table", "slot_mapping")}}, "d")]),
        sc("attention-flash-build-metadata-causal-dtype", "attn-flash-build-metadata", "An int64 per-request causal tensor is refused",
           [err("value-error"), "result.error.message.contains('must be int32')", called("flash-attention-metadata-builder.build")],
           inp={"common": {"causal_is_tensor": True, "causal_tensor_dtype": "int64"}}),
    ]
    # 5 FA forward
    F.append(flow("attn-flash-forward", "FlashAttention forward for one layer", "flash-attention-impl.forward", FWD,
                  [Cfn(FA, "forward", ln(FA, r"^class FlashAttentionImpl"))]))
    vf = "flash-attn-interface.flash-attn-varlen-func"
    S += [
        sc("attention-flash-forward-decode-fa3", "attn-flash-forward", "Decode batch of 4 on FA3 reads the paged KV cache",
           ["result.ok && result.value.path == 'paged' && result.value.fa_version == 3",
            "trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attn-interface.flash-attn-varlen-func' && e.input.paged && e.input.shape.kv_tokens == 364)"]),
        sc("attention-flash-forward-prefill-fa2", "attn-flash-forward", "Prefill on FA2 (no splits, no AOT metadata)",
           ["result.ok && result.value.path == 'paged' && result.value.fa_version == 2"],
           inp={"fa_version": 2, "num_tokens": 17, "metadata": dict(MD_PREFILL, has_scheduler_metadata=False, max_num_splits=0)}),
        sc("attention-flash-forward-fa4", "attn-flash-forward", "Blackwell FA4 uses the CuTe kernel", ["result.ok && result.value.fa_version == 4"],
           inp={"fa_version": 4}),
        sc("attention-flash-forward-profiling", "attn-flash-forward", "Profiling run without metadata zero-fills the output",
           ["result.ok && result.value.path == 'profiling'", not_called(vf)], inp={"profiling_run": True}),
        sc("attention-flash-forward-output-scale", "attn-flash-forward", "Fused output quantization is refused", [err("not-implemented-error"), not_called(vf)],
           inp={"has_output_scale": True}),
        sc("attention-flash-forward-encoder", "attn-flash-forward", "Encoder attention is bidirectional and skips the KV cache",
           ["result.value.path == 'encoder'", "trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attn-interface.flash-attn-varlen-func' && !e.input.causal && !e.input.paged)"],
           inp={"attn_type": "encoder_only"}),
        sc("attention-flash-forward-encoder-fp8", "attn-flash-forward", "Encoder attention with an FP8 KV cache is refused", [err("not-implemented-error"), not_called(vf)],
           inp={"attn_type": "encoder", "kv_cache_dtype": "fp8"}),
        sc("attention-flash-forward-fa2-splits", "attn-flash-forward", "FA2 can't take num_splits > 1 (graph-pinned splits)",
           [err("not-implemented-error"), "result.error.message == 'FA2 does not support num_splits > 1'", not_called("flash-attn-interface.vllm-fa2-varlen-fwd")],
           inp={"fa_version": 2, "metadata": dict(MD_DECODE, has_scheduler_metadata=False)}),
        sc("attention-flash-forward-fa2-sched-meta", "attn-flash-forward", "FA2 refuses scheduler metadata together with descales",
           [err("not-implemented-error"), "result.error.message.startsWith('FA2 does not support scheduler_metadata')", called(vf)], inp={"fa_version": 2}),
        sc("attention-flash-forward-fa2-sinks", "attn-flash-forward", "FA2 has no attention sinks", [err("not-implemented-error"), "result.error.message == 'FA2 does not support s_aux'", called(vf)],
           inp={"fa_version": 2, "has_sinks": True, "metadata": dict(MD_DECODE, has_scheduler_metadata=False, max_num_splits=0)}),
        sc("attention-flash-forward-alibi-fa3-fa4", None, "ALiBi is asserted away on FA3 and FA4",
           ["!steps.f3.result.ok && steps.f3.result.error.code == 'assertion-error'", "!steps.f4.result.ok && steps.f4.result.error.code == 'assertion-error'", called(vf)],
           steps=[{"flow": "attn-flash-forward", "input": {"has_alibi": True}, "as": "f3"}, {"flow": "attn-flash-forward", "input": {"has_alibi": True, "fa_version": 4}, "as": "f4"}]),
        sc("attention-flash-forward-bad-version", "attn-flash-forward", "An unknown FA version is a ValueError", [err("value-error"), called(vf)], inp={"fa_version": 5}),
        sc("attention-flash-forward-per-seq-causal", "attn-flash-forward", "Per-sequence causal tensors need FA4", [err("not-implemented-error"), not_called(vf)],
           inp={"metadata": dict(MD_DECODE, causal_is_tensor=True)}),
        sc("attention-flash-forward-dcp-ag-rs", None, "DCP=2 (ag_rs) on all four TP ranks: query all-gather, context attention, LSE all-gather + reduce-scatter, merge",
           ["[0, 1, 2, 3].all(i, steps['r' + string(i)].result.value.path == 'dcp')", called("group-coordinator.all-gather"), called("dcp.cp-lse-ag-out-rs"), called("group-coordinator.reduce-scatter"),
            called("merge-attn-states.merge-attn-states"), "calls['flash-attn-interface.flash-attn-varlen-func'] == 8",
            "trace.filter(e, e.type == 'call.start' && e.interface == 'dcp.cp-lse-ag-out-rs')[0].seq < trace.filter(e, e.type == 'call.start' && e.interface == 'merge-attn-states.merge-attn-states')[0].seq"],
           steps=on_ranks({"flow": "attn-flash-forward", "input": {"dcp_world_size": 2, "metadata": dict(MD_DECODE, max_dcp_context_kv_len=60)}}, "r")),
        sc("attention-flash-forward-dcp-a2a", None, "DCP with dcp_comm_backend=a2a on all four TP ranks combines with one all-to-all",
           ["[0, 1, 2, 3].all(i, steps['r' + string(i)].result.value.path == 'dcp' && steps['r' + string(i)].result.value.via == 'a2a')", called("dcp.dcp-a2a-lse-reduce"), called("dcp.dcp-a2a-pack-send-kernel"), not_called("dcp.cp-lse-ag-out-rs")],
           steps=on_ranks({"flow": "attn-flash-forward", "input": {"dcp_world_size": 2, "metadata": dict(MD_DECODE, max_dcp_context_kv_len=60)}}, "r"), config={"dcp-comm-backend": "a2a"}),
        sc("attention-flash-forward-dcp-no-context", "attn-flash-forward", "DCP batch with no context: one plain varlen call, no collectives",
           ["result.value.path == 'dcp'", "calls['flash-attn-interface.flash-attn-varlen-func'] == 1", not_called("group-coordinator.all-gather")],
           inp={"dcp_world_size": 2}),
    ]
    # 6 FA kv update
    F.append(flow("attn-flash-kv-cache-update", "Write a step's K/V into the KV cache (FlashAttention)", "flash-attention-impl.do-kv-cache-update",
                  {"attn_type": "decoder", "num_tokens": 4, "num_kv_heads": 8, "head_size": 128, "kv_cache_dtype": "auto", "kv_quant_mode": "none",
                   "slot_mapping": [99, 135, 271, -1], "device_capability_major": 9},
                  [Cfn(FA, "do_kv_cache_update", ln(FA, r"^class FlashAttentionImpl"))]))
    S += [
        sc("attention-flash-kv-cache-update-decoder", "attn-flash-kv-cache-update", "Decoder layer: reshape_and_cache_flash writes 3 real slots, the padded one is skipped",
           ["result.value.written_tokens == 3", "trace.exists(e, e.type == 'call.start' && e.interface == 'custom-ops.reshape-and-cache-flash' && e.input.num_tokens == 4)"]),
        sc("attention-flash-kv-cache-update-encoder", "attn-flash-kv-cache-update", "Encoder layers keep no KV cache",
           ["result.value.written_tokens == 0", not_called("custom-ops.reshape-and-cache-flash")], inp={"attn_type": "encoder_only"}),
    ]
    # 7 triton forward
    tfwd = dict(FWD, fa_version=None)
    F.append(flow("attn-triton-forward", "Triton attention forward for one layer", "triton-attention-impl.forward", tfwd,
                  [Cfn(TA, "forward", ln(TA, r"^class TritonAttentionImpl"))]))
    S += [
        sc("attention-triton-forward-small-decode-3d", "attn-triton-forward", "4 decode requests <= threshold 16: 3D segmented softmax + reduce",
           ["result.value.path == 'paged-3d'", called("triton-unified-attention.kernel-unified-attention"), called("triton-unified-attention.reduce-segments")]),
        sc("attention-triton-forward-prefill-2d", "attn-triton-forward", "A prefill batch uses the 2D kernel only",
           ["result.value.path == 'paged-2d'", not_called("triton-unified-attention.reduce-segments")], inp={"num_tokens": 17, "metadata": MD_PREFILL}),
        sc("attention-triton-forward-large-decode-2d", "attn-triton-forward", "A decode batch above seq_threshold_3D uses 2D",
           ["result.value.path == 'paged-2d'", not_called("triton-unified-attention.reduce-segments")], inp={"metadata": dict(MD_DECODE, num_reqs=64)}),
        sc("attention-triton-forward-int4", "attn-triton-forward", "INT4 per-token-head cache dispatches to the packed kernel with Q rotation",
           ["result.ok && result.value.path == 'paged-int4'", called("int4-per-token-head.unified-attention-int4"), called("int4-per-token-head.attn-packed"), called("custom-ops.hadacore-transform"),
            not_called("triton-unified-attention.kernel-unified-attention")], inp={"kv_quant_mode": "int4_per_token_head", "kv_cache_dtype": "int4_per_token_head"}),
        sc("attention-triton-forward-encoder", "attn-triton-forward", "Encoder attention runs context_attention_fwd, not the paged kernel",
           ["result.value.path == 'encoder'", called("triton-prefill-attention.fwd-kernel"), not_called("triton-unified-attention.unified-attention")], inp={"attn_type": "encoder"}),
        sc("attention-triton-forward-refusals", None, "Block-scale output and FP8 encoder attention are refused; a profiling run does nothing",
           ["!steps.bs.result.ok && steps.bs.result.error.code == 'not-implemented-error'", "!steps.enc.result.ok && steps.enc.result.error.code == 'not-implemented-error'",
            "steps.prof.result.value.path == 'profiling'", not_called("triton-unified-attention.unified-attention")],
           steps=[{"flow": "attn-triton-forward", "input": {"has_output_block_scale": True}, "as": "bs"},
                  {"flow": "attn-triton-forward", "input": {"attn_type": "encoder", "kv_cache_dtype": "fp8"}, "as": "enc"},
                  {"flow": "attn-triton-forward", "input": {"profiling_run": True}, "as": "prof"}]),
        sc("attention-triton-forward-build-then-run", None, "Build Triton metadata (threshold 128//8=16 snapped to capture size 16), then a 4-request decode uses 3D",
           ["steps.b.result.value.seq_threshold_3D == 16", "steps.f.result.value.path == 'paged-3d'", called("triton-unified-attention.reduce-segments")],
           steps=[step("triton-attention-metadata-builder.build", {"common": COMMON, "num_kv_heads": 8, "cudagraph_capture_sizes": [1, 2, 4, 8, 16, 24, 32]}, "b"),
                  {"flow": "attn-triton-forward", "input": {"metadata": dict(MD_DECODE, seq_threshold_3D="= steps.b.result.value.seq_threshold_3D")}, "as": "f"}]),
        sc("attention-triton-build-threshold", None, "MQA (1 KV head): 128 snaps to the nearest capture size; eager mode keeps 128//8",
           ["steps.mqa.result.value.seq_threshold_3D == 32", "steps.eager.result.value.seq_threshold_3D == 16", called("triton-attention-metadata-builder.build")],
           steps=[step("triton-attention-metadata-builder.build", {"common": COMMON, "num_kv_heads": 1, "cudagraph_capture_sizes": [1, 2, 4, 8, 16, 24, 32]}, "mqa"),
                  step("triton-attention-metadata-builder.build", {"common": COMMON, "num_kv_heads": 8, "cudagraph_capture_sizes": []}, "eager")]),
    ]
    # 8 triton kv update
    F.append(flow("attn-triton-kv-cache-update", "Write a step's K/V into the KV cache (Triton)", "triton-attention-impl.do-kv-cache-update",
                  {"attn_type": "decoder", "num_tokens": 4, "num_kv_heads": 8, "head_size": 128, "kv_cache_dtype": "auto", "kv_quant_mode": "none",
                   "slot_mapping": [99, 135, 271, -1], "device_capability_major": 9},
                  [Cfn(TA, "do_kv_cache_update", ln(TA, r"^class TritonAttentionImpl"))]))
    S += [
        sc("attention-triton-kv-cache-update-flash", "attn-triton-kv-cache-update", "bf16 cache: reshape_and_cache_kernel_flash, 3 slots written",
           ["result.value.path == 'flash'", called("triton-reshape-and-cache-flash.reshape-and-cache-kernel-flash"),
            "trace.exists(e, e.type == 'call.end' && e.interface == 'triton-reshape-and-cache-flash.triton-reshape-and-cache-flash' && e.output.written_tokens == 3 && e.output.tile_size == 2048)"]),
        sc("attention-triton-kv-cache-update-int8-pth", "attn-triton-kv-cache-update", "INT8 per-token-head cache: quantizing writer",
           ["result.value.path == 'per-token-head' && result.value.writer == 'int8_per_token_head'"], inp={"kv_quant_mode": "int8_per_token_head"}),
        sc("attention-triton-kv-cache-update-int4", "attn-triton-kv-cache-update", "INT4 cache: RHT via Hadacore then the packing writer",
           ["result.value.path == 'per-token-head' && result.value.writer == 'int4'", called("custom-ops.hadacore-transform")], inp={"kv_quant_mode": "int4_per_token_head"}),
        sc("attention-triton-kv-cache-update-encoder", "attn-triton-kv-cache-update", "Encoder layers write nothing",
           ["result.value.path == 'none'", not_called("triton-reshape-and-cache-flash.triton-reshape-and-cache-flash")], inp={"attn_type": "encoder"}),
        sc("attention-triton-kv-cache-update-fp8-ampere", "attn-triton-kv-cache-update", "FP8 KV on SM80 can't be stored by the Triton writer (tile capped at 512 below SM90)",
           ["!steps.fp8.result.ok && steps.fp8.result.error.code == 'assertion-error'", "steps.bf16.result.ok",
            "trace.exists(e, e.type == 'call.end' && e.interface == 'triton-reshape-and-cache-flash.triton-reshape-and-cache-flash' && e.output.tile_size == 512)"],
           steps=[{"flow": "attn-triton-kv-cache-update", "input": {"kv_cache_dtype": "fp8", "device_capability_major": 8}, "as": "fp8"},
                  {"flow": "attn-triton-kv-cache-update", "input": {"device_capability_major": 8}, "as": "bf16"}]),
        sc("attention-triton-kv-cache-update-diffkv", None, "Diff-KV writer skips padding slots",
           ["steps.d.result.value.written_tokens == 3", called("triton-reshape-and-cache-flash.reshape-and-cache-kernel-flash-diffkv"),
            "steps.d2.result.value.written_tokens == 2"],
           steps=[step("triton-reshape-and-cache-flash.triton-reshape-and-cache-flash-diffkv", {"slot_mapping": [1, 2, 3, -1]}, "d"),
                  step("triton-reshape-and-cache-flash.triton-reshape-and-cache-flash-diffkv", {"slot_mapping": [4, 5]}, "d2")]),
        sc("attention-hadamard-tiers", None, "fast_hadamard_transform: Triton MMA without Hadacore, butterfly on CPU",
           ["steps.t.result.value.tier == 'triton'", "steps.c.result.value.tier == 'torch'", called("int4-per-token-head.hadamard-mma-kernel")],
           steps=[step("int4-per-token-head.fast-hadamard-transform", {"d": 128, "hadacore_available": False, "is_cuda": True, "dtype": "bfloat16"}, "t"),
                  step("int4-per-token-head.fast-hadamard-transform", {"d": 128, "hadacore_available": False, "is_cuda": False, "dtype": "float32"}, "c")]),
    ]
    # 9 merge
    F.append(flow("attn-merge-states", "Merge prefix and suffix attention states", "merge-attn-states.merge-attn-states",
                  {"platform": "cuda", "cdna_version": 3, "dtype": "bfloat16", "output_dtype": "bfloat16", "head_size": 128, "num_tokens": 24,
                   "num_heads": 32, "has_output_scale": False, "prefill_tokens_with_context": None, "head_strides_match": True},
                  [Cfn(MAS, "merge_attn_states")]))
    S += [
        sc("attention-merge-states-cuda", "attn-merge-states", "CUDA bf16 head 128: the _C op", ["result.value.impl == 'cuda'", called("custom-ops.merge-attn-states")]),
        sc("attention-merge-states-rocm-cdna2", "attn-merge-states", "ROCm CDNA2 falls back to Triton",
           ["result.value.impl == 'triton'", called("triton-merge-attn-states.merge-attn-states-kernel"), not_called("custom-ops.merge-attn-states")],
           inp={"platform": "rocm", "cdna_version": 2}),
        sc("attention-merge-states-odd-head", "attn-merge-states", "bf16 head size 100 isn't a multiple of 8: Triton, with partial context",
           ["result.value.impl == 'triton'", "trace.exists(e, e.type == 'call.end' && e.interface == 'triton-merge-attn-states.merge-attn-states' && e.output.merged_tokens == 10)"],
           inp={"head_size": 100, "prefill_tokens_with_context": 10}),
        sc("attention-merge-states-cpu", "attn-merge-states", "CPU uses the torch merge", ["result.value.impl == 'torch' && result.value.merged_tokens == 24", not_called("custom-ops.merge-attn-states")],
           inp={"platform": "cpu"}),
        sc("attention-merge-states-refusals", None, "FP8 output without a scale, and mismatched head strides, are refused",
           ["!steps.s.result.ok && steps.s.result.error.code == 'assertion-error'", "!steps.h.result.ok && steps.h.result.error.code == 'assertion-error'", not_called("custom-ops.merge-attn-states")],
           steps=[{"flow": "attn-merge-states", "input": {"output_dtype": "float8_e4m3fn"}, "as": "s"}, {"flow": "attn-merge-states", "input": {"head_strides_match": False}, "as": "h"}]),
    ]
    # 10 DCP combine
    F.append(flow("attn-dcp-combine", "Combine partial attention across decode-context-parallel ranks (MLA)", "mla-dcp-manager.combine",
                  {"use_direct_workspace": True, "use_a2a": True, "num_tokens": 8, "max_num_tokens": 512, "world_size": 2, "num_heads": 64},
                  [Cfn(DCP, "_init_combine"), Cfn(DCP, "_direct_workspace_combine")]))
    S += [
        sc("attention-dcp-combine-direct", "attn-dcp-combine", "Batch fits the symmetric workspace: direct A2A op (4 kernels)",
           ["result.value.via == 'direct'", called("dcp-direct-a2a-lse-reduce.direct-dcp-a2a-lse-reduce"), not_called("dcp.dcp-a2a-lse-reduce")]),
        sc("attention-dcp-combine-overflow", "attn-dcp-combine", "Too many tokens for the workspace: NCCL all-to-all",
           ["result.value.via == 'a2a'", called("dcp.dcp-a2a-unpack-combine-kernel"), not_called("dcp-direct-a2a-lse-reduce.direct-dcp-a2a-lse-reduce")], inp={"num_tokens": 1024}),
        sc("attention-dcp-combine-ag-rs", None, "ag_rs backend on all four TP ranks: all-gather LSE, correct, reduce-scatter",
           ["[0, 1, 2, 3].all(i, steps['r' + string(i)].result.value.via == 'ag_rs')", called("dcp.correct-attn-cp-out-kernel"), called("group-coordinator.reduce-scatter")],
           steps=on_ranks({"flow": "attn-dcp-combine", "input": {"use_direct_workspace": False, "use_a2a": False}}, "r")),
        sc("attention-dcp-combine-single-rank", None, "World size 1 returns the partials; ag_rs likewise",
           ["steps.a.result.value.combined == false", "steps.g.result.value.combined == false", not_called("dcp.dcp-a2a-pack-send-kernel"), not_called("group-coordinator.all-gather")],
           steps=[{"flow": "attn-dcp-combine", "input": {"use_direct_workspace": False, "world_size": 1}, "as": "a"},
                  {"flow": "attn-dcp-combine", "input": {"use_direct_workspace": False, "use_a2a": False, "world_size": 1}, "as": "g"}]),
        sc("attention-dcp-combine-bad-heads", "attn-dcp-combine", "Heads not divisible by the DCP size", [err("value-error"), not_called("dcp.dcp-a2a-pack-send-kernel")],
           inp={"use_direct_workspace": False, "num_heads": 63}),
        sc("attention-dcp-combine-direct-check", "attn-dcp-combine", "The CUDA op rejects world_size 1", [err("runtime-error"), called("dcp-direct-a2a-lse-reduce.direct-dcp-a2a-lse-reduce")],
           inp={"world_size": 1}),
        sc("attention-dcp-gathers", None, "Query gather (direct and fallback) and KV gather (direct and torch)",
           ["steps.q1.result.value.via == 'direct'", "[0, 1, 2, 3].all(i, steps['q2r' + string(i)].result.value.via == 'all_gather')", "steps.k1.result.value.gathered_tokens == 16",
            "steps.k2.result.value.gathered_tokens == 16", called("dcp-direct-q-gather.direct-dcp-q-gather"), called("dcp-direct-kv-gather.direct-dcp-kv-gather")],
           steps=[step("mla-dcp-manager.gather-query", {"use_direct_workspace": True, "num_tokens": 8, "max_num_tokens": 512, "world_size": 2}, "q1"),
                  step("mla-dcp-manager.kv-gather", {"use_direct_workspace": True, "num_tokens": 8, "max_gathered_tokens": 4096, "world_size": 2}, "k1"),
                  step("mla-dcp-manager.kv-gather", {"use_direct_workspace": False, "num_tokens": 8, "max_gathered_tokens": 4096, "world_size": 2}, "k2"),
                  *on_ranks(step("mla-dcp-manager.gather-query", {"use_direct_workspace": True, "num_tokens": 4096, "max_num_tokens": 512, "world_size": 2}, "q2"), "q2r")]),
        sc("attention-dcp-gather-refusals", None, "Wrong local head count; KV gather beyond the workspace; q-gather on one rank",
           ["!steps.h.result.ok && steps.h.result.error.code == 'value-error'", "!steps.o.result.ok && steps.o.result.error.code == 'runtime-error'",
            "!steps.w.result.ok && steps.w.result.error.code == 'runtime-error'", "!steps.z.result.ok && steps.z.result.error.code == 'runtime-error'", called("dcp-direct-kv-gather.direct-dcp-kv-gather")],
           steps=[step("direct-dcp-q-gather-workspace.gather", {"world_size": 2, "num_tokens": 8, "local_heads": 32, "heads_per_rank": 64}, "h"),
                  step("direct-dcp-kv-gather-workspace.gather", {"world_size": 2, "num_tokens": 4096, "max_gathered_tokens": 4096}, "o"),
                  step("direct-dcp-q-gather-workspace.gather", {"world_size": 1, "num_tokens": 8, "local_heads": 64, "heads_per_rank": 64}, "w"),
                  step("dcp-direct-a2a-lse-reduce.direct-dcp-a2a-lse-reduce", {"world_size": 2, "num_tokens": 0, "max_num_tokens": 512}, "z")]),
    ]
    # 11 ViT
    F.append(flow("attn-vit-attention", "Multimodal encoder (ViT) attention through custom ops", "vit-attn-wrappers.vit-flash-attn-wrapper",
                  {"shape": {"num_tokens": 1024, "num_seqs": 1, "num_heads": 16, "num_kv_heads": 16, "head_size": 80, "kv_tokens": 1024}, "is_rocm_aiter": False, "fa_version": 3},
                  [Cfn(VIT, "vit_flash_attn_wrapper")]))
    S += [
        sc("attention-vit-flash", "attn-vit-attention", "ViT on CUDA: the opaque op runs non-causal FA varlen",
           ["result.value.impl == 'vllm_fa'", "trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attn-interface.flash-attn-varlen-func' && !e.input.causal)",
            called("flash-attn-interface.vllm-fa3-fwd")]),
        sc("attention-vit-aiter", "attn-vit-attention", "ROCm aiter path skips vLLM FA", ["result.value.impl == 'aiter'", not_called("flash-attn-interface.flash-attn-varlen-func")],
           inp={"is_rocm_aiter": True}),
        sc("attention-vit-other-wrappers", None, "Triton, SDPA (batched and per sequence) and FlashInfer cuDNN wrappers",
           ["steps.t.result.value.impl == 'triton'", "steps.s1.result.value.calls == 1", "steps.s3.result.value.calls == 3",
            "steps.fi.result.value.impl == 'flashinfer_cudnn' && steps.fi.result.value.flattened", "steps.fi2.result.value.flattened == false",
            called("triton-prefill-attention.fwd-kernel")],
           steps=[step("vit-attn-wrappers.vit-triton-attn-wrapper", {"shape": {"num_tokens": 1024, "head_size": 80}}, "t"),
                  step("vit-attn-wrappers.vit-torch-sdpa-wrapper", {"num_seqs": 0}, "s1"),
                  step("vit-attn-wrappers.vit-torch-sdpa-wrapper", {"num_seqs": 3, "seq_lens": [256, 256, 512]}, "s3"),
                  step("vit-attn-wrappers.vit-flashinfer-wrapper", {"is_reshaped": True}, "fi"),
                  step("vit-attn-wrappers.vit-flashinfer-wrapper", {"is_reshaped": False}, "fi2")]),
        sc("attention-vit-large-head", None, "context_attention_fwd narrows the tile for head dims >= 512",
           ["steps.big.result.value.block == 32", "steps.small.result.value.block == 64", called("triton-prefill-attention.fwd-kernel")],
           steps=[step("triton-prefill-attention.context-attention-fwd", {"shape": {"head_size": 512}, "is_causal": False}, "big"),
                  step("triton-prefill-attention.context-attention-fwd", {"shape": {"head_size": 80}, "is_causal": False}, "small")]),
    ]
    # 12 MLA prefill quant output (oracle 1)
    F.append(flow("attn-mla-prefill-quant-output", "MLA prefill: can the backend write quantized output directly?", "mla-prefill-backend.supports-quant-output",
                  {"backend": "FLASH_ATTN", "quant_key": "kFp8StaticTensorSym", "fa_version": 4, "is_vllm_fa": True, "device_capability_major": 10},
                  [Cfn(MLAP, "supports_quant_output")]))
    q = lambda k, as_: step("mla-prefill-backend.supports-quant-output", {"backend": "DUMMY", "quant_key": k}, as_)
    S += [
        sc("oracle-build-attention-1", None, "test_base_backend_never_supports_quant_output: the base default opts out for every quant key",
           ["!steps.k1.result.value.supported && !steps.k2.result.value.supported && !steps.k3.result.value.supported && !steps.k4.result.value.supported",
            "calls['mla-prefill-backend.supports-quant-output'] == 4", not_called("flash-attn-prefill-backend.supports-quant-output")],
           steps=[q("kFp8StaticTensorSym", "k1"), q("kFp8Dynamic128Sym", "k2"), q("kNvfp4Dynamic", "k3"), q(None, "k4")]),
        sc("attention-mla-prefill-quant-output-fa4-sm100", "attn-mla-prefill-quant-output", "FA4 + vLLM-FA + SM100 + static FP8: fused",
           ["result.value.supported", called("flash-attn-prefill-backend.supports-quant-output")]),
        sc("attention-mla-prefill-quant-output-fa4-sm90", "attn-mla-prefill-quant-output", "FA4 on SM90 is not fused",
           ["!result.value.supported", called("flash-attn-prefill-backend.supports-quant-output")], inp={"device_capability_major": 9}),
    ]
    # 13 CPU MLA (oracle 3) write then read
    F.append(flow("attn-cpu-mla-kv-write", "CPU MLA: write latent KV into the cache", "cpu-mla-impl.do-kv-cache-update",
                  {"slot_mapping": [0, 1, 2, 3, 4, 5, 6, -1], "kv_lora_rank": 512, "pe_dim": 64, "num_slots": 64},
                  [Cfn(CPUMLA, "do_kv_cache_update")], tags=["writes"]))
    F.append(flow("attn-cpu-mla-decode", "CPU MLA: decode over the latent cache", "cpu-mla-impl.forward-mqa",
                  {"has_decode": True, "block_table": [0], "seq_len": 7}, [Cfn(CPUMLA, "forward_mqa")]))
    rows = "state['cpu-mla-impl@rank0'].latent_rows"
    S += [
        sc("oracle-build-attention-3", "attn-cpu-mla-kv-write", "test_kv_cache_cpu_write: 7 valid slots written in order; the -1 padding slot stays untouched",
           ["result.ok && result.value.written == 7", f"size({rows}) == 7",
            f"[0, 1, 2, 3, 4, 5, 6].all(i, {rows}[string(i)].token == i && {rows}[string(i)].kv_c_width == 512 && {rows}[string(i)].k_pe_width == 64)",
            f"!('7' in {rows}) && !('-1' in {rows})"]),
        sc("attention-cpu-mla-write-then-decode", None, "Write 7 latent rows, then decode a 7-token sequence in block 0 reads all of them",
           ["steps.w.result.value.written == 7", "steps.d.result.value.rows_read == 7 && steps.d.result.value.rows_unwritten == 0",
            called("custom-ops.mla-decode-kvcache-cpu"), f"size({rows}) == 7"],
           steps=[{"flow": "attn-cpu-mla-kv-write", "as": "w"}, {"flow": "attn-cpu-mla-decode", "as": "d"}]),
        sc("attention-cpu-mla-decode-before-write", None, "Decode over 8 tokens after writing 7: the padding slot's row was never written",
           ["steps.d.result.value.rows_read == 7 && steps.d.result.value.rows_unwritten == 1", f"!('7' in {rows})"],
           steps=[{"flow": "attn-cpu-mla-kv-write", "as": "w"}, {"flow": "attn-cpu-mla-decode", "input": {"seq_len": 8}, "as": "d"}]),
        sc("attention-cpu-mla-edge-cases", None, "An empty cache tensor writes nothing; decode without decode metadata fails",
           ["steps.e.result.value.written == 0", "!steps.n.result.ok && steps.n.result.error.code == 'assertion-error'", f"size({rows}) == 0"],
           steps=[{"flow": "attn-cpu-mla-kv-write", "input": {"num_slots": 0}, "as": "e"}, {"flow": "attn-cpu-mla-decode", "input": {"has_decode": False}, "as": "n"}]),
    ]
    # 14 CPU ISA
    F.append(flow("attn-cpu-isa", "CPU attention: pick the kernel ISA", "cpu-attn.get-attn-isa",
                  {"fp8_kv": False, "amx": False, "avx512": True, "dtype": "bfloat16", "block_size": 32, "arch": "x86", "cpuinfo": None},
                  [Cfn(CPUA, "_get_attn_isa")]))
    isa = "trace.exists(e, e.type == 'call.end' && e.interface == 'cpu-attn.get-attn-isa')"
    S += [
        sc("attention-cpu-isa-vec", "attn-cpu-isa", "x86 with AVX-512, no AMX, block 32: vec", ["result.value.isa == 'vec'", isa]),
        sc("attention-cpu-isa-amx", "attn-cpu-isa", "AMX + bf16 + block 32: amx", ["result.value.isa == 'amx'", isa], inp={"amx": True}),
        sc("attention-cpu-isa-arm-vec16", None, "ARM: neon; x86 block 16: vec16; s390x: vxe; POWER: vsx",
           ["steps.a.result.value.isa == 'neon'", "steps.v.result.value.isa == 'vec16'", "steps.z.result.value.isa == 'vxe'", "steps.p.result.value.isa == 'vsx'", isa],
           steps=[{"flow": "attn-cpu-isa", "input": {"arch": "arm"}, "as": "a"}, {"flow": "attn-cpu-isa", "input": {"block_size": 16}, "as": "v"},
                  {"flow": "attn-cpu-isa", "input": {"arch": "s390x"}, "as": "z"}, {"flow": "attn-cpu-isa", "input": {"arch": "powerpc"}, "as": "p"}]),
        sc("attention-cpu-isa-riscv", None, "RISC-V: rvv when cpuinfo advertises zvl256b, else vec",
           ["steps.r.result.value.isa == 'rvv'", "steps.n.result.value.isa == 'vec'", called("cpu-attn.riscv-supports-rvv")],
           steps=[{"flow": "attn-cpu-isa", "input": {"arch": "riscv", "cpuinfo": "isa : rv64imafdcv_zvl256b"}, "as": "r"},
                  {"flow": "attn-cpu-isa", "input": {"arch": "riscv", "cpuinfo": "isa : rv64imafdc"}, "as": "n"}]),
        sc("attention-cpu-isa-fp8-refused", "attn-cpu-isa", "FP8 KV without AVX-512 or AMX", [err("not-implemented-error"), isa], inp={"fp8_kv": True, "avx512": False}),
        sc("attention-cpu-rvv-probe", None, "_riscv_supports_rvv trusts the compiled ISA probe, and returns False without /proc/cpuinfo",
           ["steps.c.result.value.rvv", "!steps.n.result.value.rvv", called("cpu-attn.riscv-supports-rvv")],
           steps=[step("cpu-attn.riscv-supports-rvv", {"compiled_rvv": True}, "c"), step("cpu-attn.riscv-supports-rvv", {"compiled_rvv": False}, "n")]),
    ]
    return F, S


def tail_flows_and_scenarios():
    F, S = [], []
    F.append(flow("attn-triton-mla-decode", "Triton MLA decode over the latent cache", "triton-mla-impl.forward-mqa",
                  {"num_tokens": 4, "num_seqs": 4, "kv_tokens": 4096, "num_heads": 16, "num_kv_heads": 1, "head_size": 576},
                  [Cfn("vllm/v1/attention/backends/mla/triton_mla.py", "forward_mqa")]))
    S += [
        sc("attention-triton-mla-decode-grouped", "attn-triton-mla-decode", "16 query heads share the latent KV head: grouped stage 1, then the reduce",
           ["result.value.mode == 'grouped'", called("triton-decode-attention.fwd-grouped-kernel-stage1"), called("triton-decode-attention.fwd-kernel-stage2")]),
        sc("attention-triton-decode-normal-softcap", None, "One KV head per query head with logit soft-capping: the non-grouped stage 1",
           ["steps.n.result.value.mode == 'normal'", called("triton-decode-attention.fwd-kernel-stage1")],
           steps=[step("triton-decode-attention.decode-attention-fwd", {"kv_group_num": 1, "logit_cap": 30.0}, "n")]),
    ]
    F.append(flow("attn-turboquant", "TurboQuant attention forward", "turboquant-attention-impl.forward",
                  {"metadata_missing": False, "is_prefill": False, "use_flydsl": False, "num_tokens": 4, "num_seqs": 4, "kv_tokens": 4096, "max_seq_len": 1024},
                  [Cfn("vllm/v1/attention/backends/turboquant_attn.py", "forward", ln("vllm/v1/attention/backends/turboquant_attn.py", r"^class TurboQuantAttentionImpl"))]))
    S += [
        sc("attention-turboquant-decode", "attn-turboquant", "Decode batch: Triton TurboQuant stage 1 + shared reduce",
           ["result.value.path == 'decode' && !result.value.soa", called("triton-turboquant-decode.tq-decode-stage1"), called("triton-decode-attention.fwd-kernel-stage2")]),
        sc("attention-turboquant-decode-soa", "attn-turboquant", "FlyDSL build: SoA unified decode, 3D for a 4096-token context",
           ["result.value.path == 'decode' && result.value.soa && result.value.use_3d", called("turboquant-soa-unified-attention.kernel-tq-unified-attention-3d"), called("triton-unified-attention.reduce-segments")],
           inp={"use_flydsl": True, "max_seq_len": 4096}),
        sc("attention-turboquant-decode-soa-short", "attn-turboquant", "FlyDSL build, short context: SoA 2D kernel",
           ["result.value.path == 'decode' && result.value.soa && !result.value.use_3d"], inp={"use_flydsl": True, "max_seq_len": 512}),
        sc("attention-turboquant-continuation", None, "Prefill with cached context dequantizes the cache (Triton and SoA); profiling does nothing",
           ["steps.t.result.value.path == 'continuation-prefill'", "steps.s.result.value.path == 'continuation-prefill'", "steps.p.result.value.path == 'profiling'",
            called("triton-turboquant-decode.tq-full-dequant-kv"), called("turboquant-soa-decode.tq-full-dequant-kv")],
           steps=[{"flow": "attn-turboquant", "input": {"is_prefill": True}, "as": "t"}, {"flow": "attn-turboquant", "input": {"is_prefill": True, "use_flydsl": True}, "as": "s"},
                  {"flow": "attn-turboquant", "input": {"metadata_missing": True}, "as": "p"}]),
        sc("attention-turboquant-store", None, "Stores: Triton FP8-key, SoA MSE-key, Triton MSE, SoA FP8 and an empty batch",
           ["steps.a.result.value.store == 'fp8'", "steps.b.result.value.store == 'soa-mse'", "steps.c.result.value.store == 'mse'", "steps.d.result.value.store == 'soa-fp8'",
            "steps.e.result.value.store == 'none'", called("triton-turboquant-store.tq-fused-store-fp8"), called("turboquant-soa-store.tq-fused-store-mse")],
           steps=[step("turboquant-attention-impl.do-kv-cache-update", {"num_tokens": 8, "use_flydsl": False, "key_fp8": True}, "a"),
                  step("turboquant-attention-impl.do-kv-cache-update", {"num_tokens": 8, "use_flydsl": True, "key_fp8": False}, "b"),
                  step("turboquant-attention-impl.do-kv-cache-update", {"num_tokens": 8, "use_flydsl": False, "key_fp8": False}, "c"),
                  step("turboquant-attention-impl.do-kv-cache-update", {"num_tokens": 8, "use_flydsl": True, "key_fp8": True}, "d"),
                  step("turboquant-attention-impl.do-kv-cache-update", {"num_tokens": 0}, "e")]),
    ]
    F.append(flow("attn-ultraquant", "UltraQuant decode attention", "ultraquant-attention-impl.decode-attention",
                  {"flydsl_eligible": False, "num_tokens": 4, "num_seqs": 4, "kv_tokens": 4096, "max_seq_len": 4096},
                  [Cfn("vllm/v1/attention/backends/ultraquant_attn.py", "_decode_attention")]))
    S += [
        sc("attention-ultraquant-decode-3d", "attn-ultraquant", "Long-context decode: 3D split-KV + reduce",
           ["result.value.impl == 'triton' && result.value.use_3d", called("ultraquant-triton-unified-attention.kernel-ultraquant-unified-attention-3d")]),
        sc("attention-ultraquant-decode-2d", "attn-ultraquant", "Short context: 2D", ["!result.value.use_3d", called("ultraquant-triton-unified-attention.kernel-ultraquant-unified-attention-2d")],
           inp={"max_seq_len": 512}),
        sc("attention-ultraquant-flydsl", "attn-ultraquant", "FlyDSL-eligible ROCm decode", ["result.value.impl == 'flydsl'", not_called("ultraquant-triton-unified-attention.ultraquant-unified-attention")],
           inp={"flydsl_eligible": True}),
        sc("attention-ultraquant-store-and-dequant", None, "Store, continuation dequant, and a head-grouping error",
           ["steps.s.result.ok && steps.c.result.ok", "!steps.e.result.ok && steps.e.result.error.code == 'value-error'",
            called("ultraquant-triton-store.ultraquant-store-kernel"), called("ultraquant-triton-dequant.ultraquant-full-dequant-kv-kernel")],
           steps=[step("ultraquant-attention-impl.store-kv", {"num_tokens": 8}, "s"), step("ultraquant-attention-impl.continuation-prefill", {"num_tokens": 64, "kv_tokens": 4096}, "c"),
                  step("ultraquant-triton-unified-attention.ultraquant-unified-attention", {"num_heads": 30, "num_kv_heads": 8}, "e")]),
    ]
    F.append(flow("attn-sparse-mla-metadata", "DeepSeek sparse-MLA indexer metadata", "deepseek-v32-indexer-metadata-builder.build",
                  {"num_tokens": 24, "num_prefills": 1, "num_decodes": 2, "supports_varlen": True},
                  [Cfn("vllm/v1/attention/backends/mla/indexer.py", "build", ln("vllm/v1/attention/backends/mla/indexer.py", r"^class DeepseekV32IndexerMetadataBuilder"))]))
    S += [
        sc("attention-sparse-mla-metadata-mixed", "attn-sparse-mla-metadata", "Mixed batch: prefill chunk metadata and varlen decode metadata",
           ["result.value.prefill && result.value.decode", called("mla-indexer.build-prefill-chunk-metadata-kernel"), called("attention-ops-metadata.indexer-decode-metadata-kernel")]),
        sc("attention-sparse-mla-metadata-uniform", "attn-sparse-mla-metadata", "Decode-only, backend without varlen: uniform decode tensors",
           ["result.value.decode && !result.value.prefill", called("mla-indexer.prepare-uniform-decode-kernel"), not_called("mla-indexer.build-prefill-chunk-metadata-kernel")],
           inp={"num_prefills": 0, "supports_varlen": False}),
        sc("attention-sparse-mla-metadata-empty", "attn-sparse-mla-metadata", "Empty batch returns early", ["!result.value.prefill && !result.value.decode", not_called("mla-indexer.build-prefill-chunk-metadata")],
           inp={"num_tokens": 0}),
        sc("attention-sparse-mla-swa-and-kpool", None, "SWA metadata (causal + images, DSpark non-causal) and the K-pool tail",
           ["steps.c.result.value.decode && steps.c.result.value.prefill", "steps.n.result.ok", "steps.k.result.value.recomputed", "!steps.k0.result.value.recomputed",
            called("deepseek-sparse-swa-metadata-builder.compute-image-visibility-kernel"), called("deepseek-sparse-swa-metadata-builder.compute-dspark-noncausal-swa-indices-kernel"),
            called("mla-indexer.kpool-tail-slot-mapping-kernel")],
           steps=[step("deepseek-sparse-swa-metadata-builder.build", {"num_decode_tokens": 4, "num_prefill_tokens": 16, "non_causal": False, "has_image_ranges": True}, "c"),
                  step("deepseek-sparse-swa-metadata-builder.build", {"num_decode_tokens": 4, "num_prefill_tokens": 0, "non_causal": True, "has_image_ranges": False}, "n"),
                  step("kpool-tail-metadata-builder.build", {"has_positions": True, "num_tokens": 24}, "k"),
                  step("kpool-tail-metadata-builder.build", {"has_positions": False, "num_tokens": 24}, "k0")]),
        sc("attention-sparse-mla-index-helpers", None, "Index remap, safe lengths, compressed slots, token->request map, pack/unpack, SM90 plan",
           ["steps.s0.result.value.launched == false && steps.s8.result.value.launched", called("sparse-utils.sparse-mla-index-remap-kernel"),
            called("compressor-utils.compressed-slot-mapping-kernel"), called("attention-ops-metadata.token-request-mapping-kernel"),
            called("attention-ops-common.pack-seq-triton-kernel"), called("attention-ops-common.unpack-seq-triton-kernel"),
            called("flashinfer-mla-sparse-sm90-state.pack-topk-indices"), called("flashinfer-mla-sparse-sm90-state.clamp-work-kv-end")],
           steps=[step("sparse-utils.triton-convert-req-index-to-global-index", {}, "r"), step("sparse-utils.prepare-sparse-mla-safe-lengths", {"num_tokens": 0}, "s0"),
                  step("sparse-utils.prepare-sparse-mla-safe-lengths", {"num_tokens": 8}, "s8"), step("compressor-utils.get-compressed-slot-mapping", {}, "c"),
                  step("attention-ops-metadata.compute-token-to-req-indices", {}, "t"), step("attention-ops-common.pack-seq-triton", {}, "p"),
                  step("attention-ops-common.unpack-seq-triton", {}, "u"), step("flashinfer-mla-sparse-sm90-state.plan", {}, "pl"),
                  step("flashinfer-mla-sparse-sm90-state.pack-indices", {}, "pk")]),
    ]
    F.append(flow("attn-flashinfer-metadata", "FlashInfer paged-KV metadata", "flashinfer-metadata-builder.compute-flashinfer-kv-metadata",
                  {"block_table": [[0, 1, 2], [3, 4]]}, [Cfn("vllm/v1/attention/backends/flashinfer.py", "_compute_flashinfer_kv_metadata")]))
    S += [
        sc("attention-flashinfer-metadata-pages", "attn-flashinfer-metadata", "Two requests with 3 and 2 blocks: 5 pages copied by one program per request",
           ["result.value.num_pages == 5", "trace.exists(e, e.type == 'call.start' && e.interface == 'flashinfer-metadata-builder.copy-page-indices-kernel' && e.input.num_seqs == 2)"]),
        sc("attention-flashinfer-trtllm-dequant", None, "TRT-LLM prefill: BF16 Q with an FP8 cache dequantizes; FP8 Q does not",
           ["steps.d.result.value.dequantized", "!steps.n.result.value.dequantized", "calls['flashinfer-backend-ops.trtllm-prefill-attn-kvfp8-dequant-kernel'] == 1"],
           steps=[step("flashinfer-backend-ops.trtllm-prefill-attn-kvfp8-dequant", {"q_fp8": False, "kv_cache_dtype": "fp8"}, "d"),
                  step("flashinfer-backend-ops.trtllm-prefill-attn-kvfp8-dequant", {"q_fp8": True, "kv_cache_dtype": "fp8"}, "n")]),
        sc("attention-flashmla-fp8", None, "FlashMLA FP8: metadata + decode when built; RuntimeError when the extension is missing",
           ["steps.m.result.ok && steps.d.result.ok", "steps.d.result.value.softmax_scale > 0.0416 && steps.d.result.value.softmax_scale < 0.0417",
            "steps.d2.result.value.softmax_scale == 0.1", "!steps.u.result.ok && steps.u.result.error.code == 'runtime-error'", "!steps.u2.result.ok",
            called("flashmla.fwd-kvcache-mla-fp8")],
           steps=[step("flashmla.get-mla-metadata-dense-fp8", {"flashmla_available": True}, "m"), step("flashmla.flash-mla-with-kvcache-fp8", {"flashmla_available": True}, "d"),
                  step("flashmla.flash-mla-with-kvcache-fp8", {"flashmla_available": True, "softmax_scale": 0.1}, "d2"),
                  step("flashmla.get-mla-metadata-dense-fp8", {"flashmla_available": False}, "u"), step("flashmla.flash-mla-with-kvcache-fp8", {"flashmla_available": False}, "u2")]),
        sc("attention-diffkv-unified", None, "Diff-KV unified attention: 3D + reduce for small decode, 2D for prefill",
           ["steps.d.result.value.use_3d", "!steps.p.result.value.use_3d", "calls['triton-unified-attention-diffkv.kernel-reduce-segments-diffkv'] == 1"],
           steps=[step("triton-unified-attention-diffkv.unified-attention-diffkv", {"max_seqlen_q": 1, "num_seqs": 4}, "d"),
                  step("triton-unified-attention-diffkv.unified-attention-diffkv", {"max_seqlen_q": 16, "num_seqs": 2}, "p")]),
        sc("attention-fa-sparse-wrappers", None, "FA2 block-sparse wrappers: default scale head_size^-0.5 and an explicit scale",
           ["steps.a.result.value.softmax_scale > 0.088 && steps.a.result.value.softmax_scale < 0.089", "steps.b.result.value.softmax_scale == 0.5", "steps.c.result.value.softmax_scale == 0.25", "steps.d.result.value.softmax_scale == 0.125",
            called("flash-attn-interface.vllm-fa2-fwd-sparse"), called("flash-attn-interface.vllm-fa2-varlen-fwd-sparse")],
           steps=[step("flash-attn-interface.sparse-attn-func", {"shape": {"head_size": 128}, "softmax_scale": None}, "a"),
                  step("flash-attn-interface.sparse-attn-varlen-func", {"shape": {"head_size": 128}, "softmax_scale": 0.5}, "b"),
                  step("flash-attn-interface.sparse-attn-func", {"shape": {"head_size": 64}, "softmax_scale": 0.25}, "c"),
                  step("flash-attn-interface.sparse-attn-varlen-func", {"shape": {"head_size": 64}}, "d")]),
    ]
    return F, S

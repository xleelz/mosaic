"""Fix round 5 (precision): configs, world variants, flows and scenarios for core-r5.yaml and the
round-5 fixes in the older core files. Also patches the shared request schemas (new optional fields)."""
from scenarios import cfg, sc, step

MOE = "moe-mixtral-8x7b-tp2-ep"
VL = "vl-qwen2-vl-7b"
FP8 = "fp8-llama-3-8b"
FP8KV = "fp8-llama-3-8b-kv-fp8"
MIXTRAL = "mistralai/Mixtral-8x7B-Instruct-v0.1"
QWEN = "Qwen/Qwen2-VL-7B-Instruct"
NM_FP8 = "neuralmagic/Meta-Llama-3-8B-Instruct-FP8-KV"
MIXTRAL_HF = {"architectures": ["MixtralForCausalLM"], "hidden_size": 4096, "intermediate_size": 14336,
              "max_position_embeddings": 32768, "num_attention_heads": 32, "num_experts_per_tok": 2,
              "num_hidden_layers": 32, "num_key_value_heads": 8, "num_local_experts": 8, "torch_dtype": "bfloat16",
              "vocab_size": 32000, "weights_bytes": 93405585408}
QWEN_HF = {"architectures": ["Qwen2VLForConditionalGeneration"], "num_hidden_layers": 28, "num_attention_heads": 28,
           "num_key_value_heads": 4, "hidden_size": 3584, "vocab_size": 152064, "max_position_embeddings": 32768,
           "weights_bytes": 16582751232}
NM_HF = {"architectures": ["LlamaForCausalLM"], "num_hidden_layers": 32, "num_attention_heads": 32, "num_key_value_heads": 8,
         "hidden_size": 4096, "vocab_size": 128256, "max_position_embeddings": 8192, "weights_bytes": 9081200640}
EXPERTS = "model.layers.0.block_sparse_moe.experts"


def env(c):
    c["attributes"]["env"] = True
    return c


def configs():
    return [
        cfg("enable-mixed-moe-lora-format", "boolean", False, False,
            "enable_mixed_moe_lora_format (--enable-mixed-moe-lora-format): MoE models load 3D (fused) LoRA adapters through the universal 2D wrapper when the request sets is_3d_lora_weight. Deployed = default.",
            ["vllm/config/lora.py:73", "vllm/engine/arg_utils.py:686"], "enable_mixed_moe_lora_format"),
        cfg("model-is-multimodal", "boolean", False, False,
            "ModelConfig.is_multimodal_model: multimodal_config is not None, which ModelConfig builds when the registry says the architecture supports multimodal inputs (Llama-3.1: text-only; the VL world sets it). multi-modal-registry.create-processor derives the same from the registry table when the caller doesn't pass it.",
            ["vllm/config/model.py:1981-1982", "vllm/config/model.py:817-868"], "is_multimodal_model", owner="config-platform"),
        cfg("kv-cache-dtype", "string", "auto", "auto",
            "kv_cache_dtype / CacheConfig.cache_dtype (reference copy): the attention layer's fp8_e5m2 check and the KV scale processing read it.",
            ["vllm/config/cache.py:122", "vllm/engine/arg_utils.py:500"], "cache_dtype", owner="attention"),
        cfg("prefill-context-parallel-size", "integer", 1, 1, "prefill_context_parallel_size (reference copy): FusedMoEParallelConfig flattens TP across it.",
            ["vllm/config/parallel.py:143"], "prefill_context_parallel_size", owner="distributed"),
        env(cfg("vllm-image-fetch-timeout-s", "integer", 5, 5, "VLLM_IMAGE_FETCH_TIMEOUT for image and asset downloads (reference copy): seconds MediaConnector.fetch_image waits.",
                 ["vllm/envs.py:73", "vllm/envs.py:973"], "VLLM_IMAGE_FETCH_TIMEOUT", owner="config-platform")),
    ]


def variants():
    """models-layers' share of the round-5 model-type worlds: the world's own model is the loaded one
    (as load_model leaves it), and the seed's Llama-3.1-8B is not."""
    mixtral_cfg = {"hidden_size": 4096, "num_heads": 32, "num_kv_heads": 8, "head_dim": 128, "intermediate_size": 14336,
                   "num_layers": 32, "vocab_size": 32000, "num_experts": 8, "top_k": 2, "bytes_per_weight": 2,
                   "ep_size": 2, "moe_tp": 1, "enable_eplb": False, "num_physical_experts": 8,
                   "num_redundant_experts": 0, "num_local_physical_experts": 4}
    mixtral = lambda rank: {"loaded": True, "model": MIXTRAL, "tp_size": 2, "quant": "unquantized", "rope": "RotaryEmbedding",
                            "weights_bytes_per_rank": 46702792704, "eplb_registered": False,
                            "cfg": dict(mixtral_cfg, ep_rank=rank)}
    qwen = {"loaded": True, "model": QWEN, "tp_size": 1, "quant": "unquantized", "rope": "MRotaryEmbedding",
            "weights_bytes_per_rank": 16582751232,
            "cfg": {"hidden_size": 3584, "num_heads": 28, "num_kv_heads": 4, "head_dim": 128, "intermediate_size": 18944,
                    "num_layers": 28, "vocab_size": 152064, "bytes_per_weight": 2.0, "mrope_section": [16, 24, 24],
                    "image_token_id": 151655, "video_token_id": 151656,
                    "vision": {"patch_size": 14, "temporal_patch_size": 2, "spatial_merge_size": 2, "embed_dim": 1280,
                               "depth": 32, "num_heads": 16, "mlp_ratio": 4, "out_hidden_size": 3584}}}
    nm = {"loaded": True, "model": NM_FP8, "tp_size": 1, "quant": "fp8", "rope": "RotaryEmbedding",
          "weights_bytes_per_rank": 9081200640,
          "cfg": {"hidden_size": 4096, "num_heads": 32, "num_kv_heads": 8, "head_dim": 128, "intermediate_size": 14336,
                  "num_layers": 32, "vocab_size": 128256, "bytes_per_weight": 1.0}}
    return [
        {"id": "models-layers-" + MOE, "attributes": {"variant_of": MOE},
         "summary": "models-layers in the Mixtral world: Mixtral-8x7B loaded on rank0 and rank1 (TP 2 + EP: 4 whole experts per rank), its expert layers wrapped by the 2D FusedMoEWithLoRA when LoRA is on; Llama is not loaded.",
         "state": {"llama-for-causal-lm": {"loaded": False},
                   "mixtral-for-causal-lm@rank0": mixtral(0), "mixtral-for-causal-lm@rank1": mixtral(1),
                   "lru-cache-lora-model-manager": {"is_moe": True, "modules": {EXPERTS: "FusedMoEWithLoRA"}}}},
        {"id": "models-layers-" + VL, "attributes": {"variant_of": VL},
         "summary": "models-layers in the Qwen2-VL world: Qwen2-VL-7B loaded on rank0 (vision tower + Qwen2 language model with M-RoPE); Llama is not loaded.",
         "state": {"llama-for-causal-lm": {"loaded": False}, "qwen2-vl-for-conditional-generation": qwen}},
        {"id": "models-layers-" + FP8, "attributes": {"variant_of": FP8},
         "summary": "models-layers in the FP8 world: the FP8 checkpoint loaded on rank0 (Fp8LinearMethod layers, Fp8KVCacheMethod attention with the checkpoint's k/v scales).",
         "state": {"llama-for-causal-lm": nm,
                   "attention-layer": {"kv_quant_method": "Fp8KVCacheMethod",
                                       "kv_scales": {"q_scale": "checkpoint", "k_scale": "checkpoint", "v_scale": "checkpoint", "prob_scale": 1.0, "source": "checkpoint"}}}},
        {"id": "models-layers-" + FP8KV, "attributes": {"variant_of": FP8KV}, "extends": ["models-layers-" + FP8],
         "summary": "models-layers in the FP8 world with --kv-cache-dtype fp8: as models-layers-fp8-llama-3-8b."},
    ]


def flows():
    def f(id_, name, iface, src, inp=None, tags=None):
        d = {"id": id_, "name": name, "entry": {"caller": "gpu-worker", "interface": iface}, "sources": src}
        if inp is not None:
            d["entry"]["input"] = inp
        if tags:
            d["tags"] = tags
        return d
    return [
        f("models-qwen2-vl-encode", "Run the Qwen2-VL vision encoder on a batch's images (embed_multimodal)",
          "qwen2-vl-for-conditional-generation.embed-multimodal", ["vllm/model_executor/models/qwen2_vl.py:1550-1573"],
          {"mm_kwargs": [{"modality": "image", "kind": "pixel_values", "grid_thw": [1, 28, 28]}]}),
        f("models-qwen2-vl-forward", "Qwen2-VL forward on merged embeddings", "qwen2-vl-for-conditional-generation.forward",
          ["vllm/model_executor/models/qwen2_vl.py:1811-1844"], {"num_tokens": 256, "num_reqs": 1, "inputs_embeds": True}),
        f("models-qwen2-vl-mrope", "M-RoPE positions for a Qwen2-VL prompt", "qwen2-vl-for-conditional-generation.get-mrope-input-positions",
          ["vllm/model_executor/models/qwen2_vl.py:1354-1392"],
          {"num_input_tokens": 9, "mm_features": [{"offset": 2, "modality": "image", "grid_thw": [1, 4, 4]}]}),
        f("models-mm-fetch-image", "Fetch an image_url (MediaConnector.fetch_image)", "media-connector.fetch-image",
          ["vllm/multimodal/media/connector.py:494-518"],
          {"image_url": "https://vllm-public-assets.s3.us-west-2.amazonaws.com/vision_model_images/stop_sign.jpg"}),
    ]


def W(world):
    """The merged world plus models-layers' variant of it (until worlds.yaml is regenerated with the variant)."""
    return ["full-" + world, "models-layers-" + world]


def ist(iface, as_, inp=None, on=None):
    return step(iface=iface, as_=as_, inp=inp, on=on)


def ld(as_, model, hf, on=None):
    return ist("base-model-loader.load-model", as_, {"loader": "default-model-loader", "model": model, "hf_config": hf}, on)


def lora_files(name, lora_modules=None, extra_cfg=None, mts=None):
    cfgj = {"r": 8, "lora_alpha": 16, "bias": "none"}
    cfgj.update(extra_cfg or {})
    files = {f"/adapters/{name}/adapter_config.json": {"json": cfgj}}
    idx = {}
    if lora_modules is not None:
        idx["lora_modules"] = lora_modules
    if mts is not None:
        idx["modules_to_save"] = mts
    files[f"/adapters/{name}/adapter_model.safetensors"] = {"size": 1048576, "json": idx}
    return files


def addl(as_, name, lid, **kw):
    inp = {"lora_name": name, "lora_int_id": lid, "lora_path": f"/adapters/{name}"}
    inp.update(kw)
    return ist("lru-cache-worker-lora-manager.add-adapter", as_, inp)


def _mixtral_dp2(rank):
    """Mixtral as DP 2 x TP 1 + EP loads it: whole attention per rank, 4 of 8 experts, and the naive DP/EP prepare/finalize."""
    return {"loaded": True, "model": MIXTRAL, "tp_size": 1, "quant": "unquantized", "rope": "RotaryEmbedding",
            "weights_bytes_per_rank": 46702792704, "eplb_registered": False,
            "cfg": {"hidden_size": 4096, "num_heads": 32, "num_kv_heads": 8, "head_dim": 128, "intermediate_size": 14336,
                    "num_layers": 32, "vocab_size": 32000, "num_experts": 8, "top_k": 2, "bytes_per_weight": 2,
                    "ep_size": 2, "ep_rank": rank, "moe_tp": 1, "enable_eplb": False, "num_physical_experts": 8,
                    "num_redundant_experts": 0, "num_local_physical_experts": 4, "prepare_finalize": "MoEPrepareAndFinalizeNaiveDPEP"}}


def scenario_list():
    L = []
    # ---------------------------------------------------------------- P3-3(a): the MoE parallel layout
    L += [
        sc("models-moe-dp4-ep-flattens-tp", fixtures=["full-tp4-llama-70b"], config={"tensor-parallel-size": 1, "data-parallel-size": 4, "enable-expert-parallel": True},
           steps=[ist("mixtral-for-causal-lm.init", "ep", {"quant": "unquantized", "hf_config": MIXTRAL_HF})],
           expect=["steps.ep.result.ok && state['mixtral-for-causal-lm@rank0'].cfg.ep_size == 4 && state['mixtral-for-causal-lm@rank0'].cfg.moe_tp == 1",
                   "state['mixtral-for-causal-lm@rank0'].cfg.num_local_physical_experts == 2",
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'fused-moe-parallel-config.make' && e.output.use_ep && e.output.ep_size == 4)"]),
        sc("models-moe-dp4-no-ep-shards-over-all-devices", fixtures=["full-tp4-llama-70b"], config={"tensor-parallel-size": 1, "data-parallel-size": 4, "enable-expert-parallel": False},
           steps=[ist("mixtral-for-causal-lm.init", "noep", {"quant": "unquantized", "hf_config": MIXTRAL_HF})],
           expect=["steps.noep.result.ok && state['mixtral-for-causal-lm@rank0'].cfg.ep_size == 1 && state['mixtral-for-causal-lm@rank0'].cfg.moe_tp == 4",
                   "state['mixtral-for-causal-lm@rank0'].cfg.num_local_physical_experts == 8"]),
        sc("models-moe-parallel-config-make", fixtures=["full-tp1-llama-8b"],
           steps=[ist("fused-moe-parallel-config.make", "tp1", {"tp_size": 1, "dp_size": 1, "pcp_size": 1, "enable_expert_parallel": True}),
                  ist("fused-moe-parallel-config.make", "dp2tp2", {"tp_size": 2, "dp_size": 2, "pcp_size": 1, "tp_rank": 1, "dp_rank": 1, "enable_expert_parallel": True}),
                  ist("fused-moe-parallel-config.make", "dp2tp2noep", {"tp_size": 2, "dp_size": 2, "pcp_size": 1, "tp_rank": 1, "dp_rank": 1})],
           # 1 device: no EP even when enabled; DP2 x TP2 + EP: 4 devices, rank 1*2+1 = 3
           expect=["!steps.tp1.result.value.use_ep && steps.tp1.result.value.ep_size == 1 && steps.tp1.result.value.tp_size == 1",
                   "steps.dp2tp2.result.value.use_ep && steps.dp2tp2.result.value.ep_size == 4 && steps.dp2tp2.result.value.ep_rank == 3 && steps.dp2tp2.result.value.tp_size == 1",
                   "steps.dp2tp2noep.result.value.tp_size == 4 && steps.dp2tp2noep.result.value.tp_rank == 3 && steps.dp2tp2noep.result.value.ep_size == 1"]),
        # The MoE world: wr-style loads on both ranks give each rank 4 whole experts
        sc("models-moe-world-load-both-ranks", fixtures=W(MOE),
           steps=[ld("l0", MIXTRAL, {"architectures": ["MixtralForCausalLM"]}, "rank0"),
                  ld("l1", MIXTRAL, {"architectures": ["MixtralForCausalLM"]}, "rank1")],
           expect=["steps.l0.result.ok && steps.l0.result.value.component == 'mixtral-for-causal-lm' && steps.l1.result.ok",
                   "state['mixtral-for-causal-lm@rank0'].cfg.ep_size == 2 && state['mixtral-for-causal-lm@rank0'].cfg.ep_rank == 0 && state['mixtral-for-causal-lm@rank1'].cfg.ep_rank == 1",
                   "state['mixtral-for-causal-lm@rank1'].cfg.num_local_physical_experts == 4 && state['mixtral-for-causal-lm@rank1'].cfg.moe_tp == 1",
                   "steps.l0.result.value.weights_bytes_per_rank == 46702792704"]),
        sc("models-moe-world-forward-seeded", fixtures=W(MOE),
           # TP 2: both ranks forward together (the all-reduces meet), and the seed's Llama is not loaded
           steps=[step(iface="mixtral-for-causal-lm.forward", as_="fwd", inp={"num_tokens": 16, "num_reqs": 1}, on="rank0", nowait=True),
                  step(iface="mixtral-for-causal-lm.forward", as_="fwd1", inp={"num_tokens": 16, "num_reqs": 1}, on="rank1"),
                  ist("llama-for-causal-lm.forward", "llama", {"num_tokens": 16, "num_reqs": 1}, "rank0")],
           expect=["steps.fwd.result.ok && steps.fwd.result.value.num_layers == 32",
                   "!steps.llama.result.ok && steps.llama.result.error.code == 'attribute-error'"]),
        # DP 2 + EP: the unquantized MoE kernel's prepare/finalize is the naive AllGather+ReduceScatter one, so each
        # rank's routed experts dispatch over distributed's EP group (AgRs all_gatherv 3 + 5 -> 8 rows) and combine back
        sc("models-moe-dp2-ep-forward-dispatch-combine", fixtures=W(MOE),
           config={"data-parallel-size": 2, "tensor-parallel-size": 1},
           state={"parallel-state@rank0": {"mp_initialized": False, "world_initialized": True, "world_size": 2, "groups": {}},
                  "parallel-state@rank1": {"mp_initialized": False, "world_initialized": True, "world_size": 2, "groups": {}},
                  "mixtral-for-causal-lm@rank0": _mixtral_dp2(0), "mixtral-for-causal-lm@rank1": _mixtral_dp2(1),
                  # the runner's set_forward_context: DP ranks batch 3 and 5 tokens
                  "forward-context@rank0": {"previous": [], "current": {"cudagraph_runtime_mode": "NONE", "batch_descriptor": None, "num_tokens": 3, "dp_metadata": {"num_tokens_across_dp_cpu": [3, 5]}}},
                  "forward-context@rank1": {"previous": [], "current": {"cudagraph_runtime_mode": "NONE", "batch_descriptor": None, "num_tokens": 5, "dp_metadata": {"num_tokens_across_dp_cpu": [3, 5]}}}},
           steps=[ist("parallel-state.initialize-model-parallel", "pg0", {"tensor_model_parallel_size": 1, "pipeline_model_parallel_size": 1, "is_moe": True}, "rank0"),
                  ist("parallel-state.initialize-model-parallel", "pg1", {"tensor_model_parallel_size": 1, "pipeline_model_parallel_size": 1, "is_moe": True}, "rank1"),
                  step(iface="mixtral-for-causal-lm.forward", as_="f0", inp={"num_tokens": 3, "num_reqs": 1}, on="rank0", nowait=True),
                  step(iface="mixtral-for-causal-lm.forward", as_="f1", inp={"num_tokens": 5, "num_reqs": 1}, on="rank1"),
                  ist("mixtral-for-causal-lm.init", "i1", {"quant": "unquantized", "hf_config": MIXTRAL_HF}, "rank1")],
           expect=["steps.f0.result.ok && steps.f1.result.ok",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'group-coordinator.dispatch').size() == 2 && trace.filter(e, e.type == 'call.start' && e.interface == 'group-coordinator.combine').size() == 2",
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'group-coordinator.dispatch' && e.output.num_tokens == 8 && e.output.manager == 'AgRsAll2AllManager')",
                   "steps.i1.result.ok && state['mixtral-for-causal-lm@rank1'].cfg.prepare_finalize == 'MoEPrepareAndFinalizeNaiveDPEP' && state['mixtral-for-causal-lm@rank1'].cfg.ep_rank == 1 && state['mixtral-for-causal-lm@rank1'].cfg.ep_size == 2"]),
    ]
    # ---------------------------------------------------------------- oracle3: expert counts, mxint4, TurboQuant
    L += [
        sc("models-moe-determine-expert-counts", fixtures=["full-tp1-llama-8b"],
           steps=[ist("fused-moe-layer.determine-expert-counts", "fuse", {"num_experts": 8, "num_redundant_experts": 0, "n_shared_experts": 2, "fuse_shared_experts": True}),
                  ist("fused-moe-layer.determine-expert-counts", "nofuse", {"num_experts": 8, "num_redundant_experts": 0, "n_shared_experts": 2, "fuse_shared_experts": False}),
                  ist("fused-moe-layer.determine-expert-counts", "none", {"num_experts": 8, "num_redundant_experts": 4, "fuse_shared_experts": True})],
           expect=["steps.fuse.result.value.num_fused_shared_experts == 2 && steps.nofuse.result.value.num_fused_shared_experts == 0",
                   "steps.none.result.value.num_fused_shared_experts == 0 && steps.none.result.value.global_num_experts == 12 && steps.none.result.value.logical_num_experts == 8"]),
        sc("models-mxint4-experts-capabilities", fixtures=["full-tp1-llama-8b"],
           steps=[ist("trtllm-mxint4-experts.is-supported-config", "silu", {"activation": "silu"}),
                  ist("trtllm-mxint4-experts.is-supported-config", "oai", {"activation": "swigluoai"}),
                  ist("trtllm-mxint4-experts.is-supported-config", "gelu", {"activation": "gelu"}),
                  ist("trtllm-mxint4-experts.is-supported-config", "eplb", {"activation": "silu", "enable_eplb": True}),
                  ist("trtllm-mxint4-experts.is-supported-config", "fp8", {"activation": "silu", "weight_key": "kFp8StaticTensorSym"}),
                  ist("trtllm-mxint4-experts.is-supported-config", "hopper", {"activation": "silu", "device_capability_family": 90, "device_name": "NVIDIA H100 80GB HBM3"})],
           expect=["steps.silu.result.value.supported && steps.oai.result.value.supported",
                   "!steps.gelu.result.value.supported && steps.gelu.result.value.reason == 'kernel does not support MoEActivation.GELU activation'",
                   "!steps.eplb.result.value.supported && steps.eplb.result.value.reason.startsWith('kernel does not support parallel config')",
                   "steps.fp8.result.value.reason == 'kernel does not support quantization scheme kFp8StaticTensorSymxNone'",
                   "steps.hopper.result.value.reason == 'kernel does not support current device NVIDIA H100 80GB HBM3'"]),
        sc("models-turboquant-presets", fixtures=["full-tp1-llama-8b"],
           steps=[ist("turbo-quant-config.from-cache-dtype", "k8v4", {"cache_dtype": "turboquant_k8v4"}),
                  ist("turbo-quant-config.from-cache-dtype", "b4", {"cache_dtype": "turboquant_4bit_nc"}),
                  ist("turbo-quant-config.from-cache-dtype", "k3v4", {"cache_dtype": "turboquant_k3v4_nc"}),
                  ist("turbo-quant-config.from-cache-dtype", "b3", {"cache_dtype": "turboquant_3bit_nc"}),
                  ist("turbo-quant-config.from-cache-dtype", "bad", {"cache_dtype": "turboquant_invalid"})],
           # head_dim 128: k8v4 key 128 + value 64+4 = 196; 4bit: 66 + 68 = 134; k3v4: 50 + 68 = 118; 3bit: 50 + 52 = 102
           expect=["steps.k8v4.result.value.key_fp8 && steps.k8v4.result.value.slot_size == 196 && steps.k8v4.result.value.slot_size_aligned == 196 && !steps.k8v4.result.value.norm_correction",
                   "steps.b4.result.value.slot_size == 134 && steps.b4.result.value.norm_correction && steps.b4.result.value.n_centroids == 16",
                   "steps.k3v4.result.value.key_packed_size == 50 && steps.k3v4.result.value.slot_size_aligned == 118",
                   "steps.b3.result.value.value_packed_size == 52 && steps.b3.result.value.slot_size == 102 && steps.b3.result.value.n_centroids == 8",
                   "!steps.bad.result.ok && steps.bad.result.error.code == 'value-error' && steps.bad.result.error.message == \"Unknown TurboQuant cache dtype: 'turboquant_invalid'. Valid presets: turboquant_k8v4, turboquant_4bit_nc, turboquant_k3v4_nc, turboquant_3bit_nc\""]),
    ]
    # ---------------------------------------------------------------- oracle3: MoE LoRA format validation
    fused = {EXPERTS: {"lora_a_is_tensor": True}}
    per_expert = {EXPERTS: {"lora_a_is_tensor": False}}
    L += [
        sc("models-lora-reject-fused-moe-before-registration", fixtures=W(MOE),
           state={"local-disk": {"files": lora_files("moe3d", fused)}},
           steps=[addl("add", "moe3d", 7), addl("decl", "moe3d", 7, is_3d_lora_weight=True),
                  ist("lru-cache-lora-model-manager.list-adapters", "ls", {})],
           expect=["!steps.add.result.ok && steps.add.result.error.code == 'value-error'",
                   "steps.add.result.error.message == \"LoRA adapter 7 contains fused 3D MoE weights for 'model.layers.0.block_sparse_moe.experts', but the model uses a 2D MoE LoRA wrapper. Start the engine with enable_mixed_moe_lora_format=True (--enable-mixed-moe-lora-format) and set is_3d_lora_weight=True on the LoRA request.\"",
                   # declared 3D without the engine flag is still refused, and nothing was cached
                   "!steps.decl.result.ok && steps.decl.result.error.message.contains('is_3d_lora_weight=True')",
                   "!(7 in steps.ls.result.value.registered)"]),
        sc("models-lora-mixed-moe-format-accepts-declared-3d", fixtures=W(MOE), config={"enable-mixed-moe-lora-format": True},
           state={"local-disk": {"files": lora_files("moe3d", fused)}},
           steps=[addl("undeclared", "moe3d", 7), addl("declared", "moe3d", 7, is_3d_lora_weight=True),
                  ist("lru-cache-lora-model-manager.list-adapters", "ls", {})],
           expect=["!steps.undeclared.result.ok && steps.undeclared.result.error.message.contains('enable_mixed_moe_lora_format=True')",
                   "steps.declared.result.ok && 7 in steps.ls.result.value.registered && state['lru-cache-lora-model-manager@rank0'].registered == [7]"]),
        sc("models-lora-moe-per-expert-and-dense-allowed", fixtures=W(MOE),
           state={"local-disk": {"files": dict(lora_files("moe2d", per_expert), **lora_files("attn", {"model.layers.0.self_attn.qkv_proj": {"lora_a_is_tensor": True}}))}},
           config={"max-loras": 2},
           steps=[addl("per_expert", "moe2d", 1), addl("dense", "attn", 2), ist("lru-cache-lora-model-manager.list-adapters", "ls", {})],
           expect=["steps.per_expert.result.ok && steps.dense.result.ok && steps.ls.result.value.registered == [1, 2] && state['lru-cache-lora-model-manager@rank0'].registered == [1, 2]"]),
        sc("models-lora-llama-has-no-moe-wrapper", fixtures=["full-tp1-llama-8b"],
           state={"local-disk": {"files": lora_files("moe3d", fused)}},
           steps=[addl("add", "moe3d", 7)],
           # a dense model has no FusedMoEWithLoRA module, so the check finds nothing to refuse
           expect=["steps.add.result.ok && steps.add.result.value.loaded && 7 in state['lru-cache-lora-model-manager@rank0'].registered"]),
    ]
    # ---------------------------------------------------------------- P3-7(c, d): KV-cache quantization on attention layers
    L += [
        sc("models-kv-fp8-unquantized-checkpoint-default-scales", fixtures=["full-tp1-llama-8b"], config={"kv-cache-dtype": "fp8"},
           steps=[ld("load", "meta-llama/Llama-3.1-8B-Instruct", {"architectures": ["LlamaForCausalLM"]})],
           expect=["steps.load.result.ok && steps.load.result.value.kv_quant_method == 'none'",
                   "steps.load.result.value.kv_scales.k_scale == 1.0 && steps.load.result.value.kv_scales.v_scale == 1.0",
                   "trace.exists(e, e.type == 'note' && e.title.contains('1.0') && e.title.contains('set_default_quant_scales'))",
                   "!trace.exists(e, e.type == 'call.start' && e.interface == 'base-kv-cache-method.process-weights-after-loading')"]),
        sc("models-kv-fp8-e5m2-refused-for-fp8-checkpoint", fixtures=W(FP8), config={"kv-cache-dtype": "fp8_e5m2"},
           steps=[ld("load", NM_FP8, {"architectures": ["LlamaForCausalLM"]})],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'value-error' && steps.load.result.error.message == 'fp8_e5m2 kv-cache is not supported with fp8 checkpoints.'",
                   # raised while the attention layers are built, before any weights are allocated
                   "!trace.exists(e, e.type == 'call.start' && e.interface == 'gpu-memory.allocate')"]),
        sc("models-kv-fp8-checkpoint-scales", fixtures=W(FP8KV),
           steps=[ld("load", NM_FP8, {"architectures": ["LlamaForCausalLM"]})],
           expect=["steps.load.result.ok && steps.load.result.value.quant == 'fp8' && steps.load.result.value.kv_quant_method == 'Fp8KVCacheMethod'",
                   "steps.load.result.value.kv_scales.k_scale == 'checkpoint' && steps.load.result.value.kv_scales.source == 'checkpoint'",
                   "state['attention-layer@rank0'].kv_quant_method == 'Fp8KVCacheMethod'",
                   "steps.load.result.value.kv_scales.warnings == ['Checkpoint does not provide a q scaling factor. Setting it to k_scale. This only matters for FP8 Attention backends (flash-attn or flashinfer).']"]),
        sc("models-kv-fp8-checkpoint-auto-cache", fixtures=W(FP8),
           steps=[ld("load", NM_FP8, {"architectures": ["LlamaForCausalLM"]})],
           expect=["steps.load.result.ok && steps.load.result.value.kv_quant_method == 'Fp8KVCacheMethod' && size(steps.load.result.value.kv_scales.warnings) == 0",
                   "state['gpu-memory@rank0'].weights_bytes == 9081200640"]),
        sc("models-kv-scales-missing-warns", fixtures=["full-tp1-llama-8b"],
           steps=[ist("base-kv-cache-method.process-weights-after-loading", "none", {"kv_cache_dtype": "fp8", "checkpoint_scales": {}}),
                  ist("base-kv-cache-method.process-weights-after-loading", "one", {"kv_cache_dtype": "fp8_e4m3", "checkpoint_scales": {"k_scale": 0.5, "q_scale": 0.25}}),
                  ist("base-kv-cache-method.process-weights-after-loading", "e5m2", {"kv_cache_dtype": "fp8_e5m2", "checkpoint_scales": {"q_scale": 1.0}})],
           expect=["steps.none.result.value.k_scale == 1.0 && size(steps.none.result.value.warnings) == 2",
                   "steps.none.result.value.warnings[1].startsWith('Using KV cache scaling factor 1.0 for fp8_e4m3.')",
                   "steps.one.result.value.k_scale == 0.5 && steps.one.result.value.v_scale == 0.5 && steps.one.result.value.q_scale == 0.25 && size(steps.one.result.value.warnings) == 0",
                   "steps.e5m2.result.value.k_scale == 1.0 && size(steps.e5m2.result.value.warnings) == 0"]),
        # --quantization fp8 on an unquantized checkpoint is online fp8_per_tensor: no KV method, so fp8_e5m2 is fine
        sc("models-quant-fp8-online-fallback", fixtures=["full-tp1-llama-8b"], config={"quantization": "fp8", "kv-cache-dtype": "fp8_e5m2"},
           steps=[ld("load", "meta-llama/Llama-3.1-8B-Instruct", {"architectures": ["LlamaForCausalLM"]})],
           expect=["steps.load.result.ok && steps.load.result.value.quant == 'fp8_per_tensor' && steps.load.result.value.kv_quant_method == 'none'",
                   "trace.exists(e, e.type == 'note' && e.title.startsWith('--quantization fp8 is deprecated for online quantization'))"]),
    ]
    # ---------------------------------------------------------------- Qwen2-VL
    L += [
        sc("models-qwen2-vl-load", fixtures=["full-" + VL],
           steps=[ld("load", QWEN, {"architectures": ["Qwen2VLForConditionalGeneration"]})],
           expect=["steps.load.result.ok && steps.load.result.value.component == 'qwen2-vl-for-conditional-generation' && steps.load.result.value.model_cls == 'Qwen2VLForConditionalGeneration'",
                   "state['qwen2-vl-for-conditional-generation@rank0'].rope == 'MRotaryEmbedding' && state['qwen2-vl-for-conditional-generation@rank0'].cfg.vision.depth == 32",
                   "state['gpu-memory@rank0'].weights_bytes == 16582751232"]),
        sc("models-qwen2-vl-encode-and-merge", fixtures=W(VL),
           steps=[ist("qwen2-vl-for-conditional-generation.embed-multimodal", "enc",
                      {"mm_kwargs": [{"modality": "image", "kind": "pixel_values", "grid_thw": [1, 34, 46]},
                                     {"modality": "image", "kind": "pixel_values", "grid_thw": [1, 4, 4]},
                                     {"modality": "video", "kind": "pixel_values", "grid_thw": [2, 8, 8]}]}),
                  ist("qwen2-vl-for-conditional-generation.embed-input-ids", "ok", {"num_tokens": 450, "mm_embeds": [391, 4, 32], "num_placeholders": 427}),
                  ist("qwen2-vl-for-conditional-generation.embed-input-ids", "bad", {"num_tokens": 450, "mm_embeds": [391, 4], "num_placeholders": 427}),
                  ist("qwen2-vl-for-conditional-generation.forward", "fwd", {"num_tokens": 450, "num_reqs": 1, "inputs_embeds": True}),
                  ist("qwen2-vl-for-conditional-generation.compute-logits", "lg", {"num_tokens": 1})],
           expect=["steps.enc.result.value.embeddings.map(e, e.num_tokens) == [391, 4, 32] && steps.enc.result.value.num_tokens == 427",
                   # one vision-tower run per modality
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'qwen2-vision-transformer.forward').size() == 2",
                   "steps.ok.result.ok && steps.ok.result.value.merged == 427",
                   "!steps.bad.result.ok && steps.bad.result.error.message == 'Attempted to assign 391 + 4 = 395 multimodal tokens to 427 placeholders'",
                   "steps.fwd.result.ok && steps.fwd.result.value.num_layers == 28 && steps.lg.result.value.vocab_size == 152064",
                   "trace.exists(e, e.type == 'call.start' && e.interface == 'm-rotary-embedding.triton-mrope')",
                   "!trace.exists(e, e.type == 'call.start' && e.interface == 'vocab-parallel-embedding.forward' && e.input.num_tokens == 450 && trace.exists(f, f.type == 'call.start' && f.interface == 'qwen2-model.forward' && f.seq < e.seq))"]),
        sc("models-qwen2-vl-encoder-refusals", fixtures=W(VL),
           steps=[ist("qwen2-vl-for-conditional-generation.embed-multimodal", "none", {"mm_kwargs": []}),
                  ist("qwen2-vl-for-conditional-generation.embed-multimodal", "audio", {"mm_kwargs": [{"modality": "audio", "grid_thw": [1, 2, 2]}]}),
                  ist("qwen2-vl-for-conditional-generation.embed-multimodal", "emb", {"mm_kwargs": [{"modality": "image", "kind": "embeds", "grid_thw": [1, 4, 4]}]}),
                  ist("qwen2-vl-for-conditional-generation.get-placeholder-str", "ph", {"modality": "image"}),
                  ist("qwen2-vl-for-conditional-generation.get-placeholder-str", "ph_audio", {"modality": "audio"})],
           expect=["steps.none.result.ok && size(steps.none.result.value.embeddings) == 0",
                   "!steps.audio.result.ok && steps.audio.result.error.message == 'Unsupported modality: audio'",
                   "steps.emb.result.value.num_tokens == 4 && !trace.exists(e, e.type == 'call.start' && e.interface == 'qwen2-vision-transformer.forward')",
                   "steps.ph.result.value.placeholder == '<|vision_start|><|image_pad|><|vision_end|>'",
                   "!steps.ph_audio.result.ok && steps.ph_audio.result.error.message == 'Only image or video modality is supported'"]),
        sc("models-qwen2-vl-not-loaded", fixtures=["full-tp1-llama-8b"],
           steps=[ist("qwen2-vl-for-conditional-generation.forward", "fwd", {"num_tokens": 16})],
           expect=["!steps.fwd.result.ok && steps.fwd.result.error.code == 'attribute-error'"]),
        sc("models-qwen2-vl-mrope-positions", fixtures=W(VL),
           steps=[step("models-qwen2-vl-mrope", as_="img"),
                  ist("qwen2-vl-for-conditional-generation.get-mrope-input-positions", "vid",
                      {"num_input_tokens": 6, "mm_features": [{"offset": 1, "modality": "video", "grid_thw": [2, 2, 4], "second_per_grid_ts": 2.0}]}),
                  ist("qwen2-vl-for-conditional-generation.get-mrope-input-positions", "bad",
                      {"num_input_tokens": 6, "mm_features": [{"offset": 1, "modality": "image", "grid_thw": [2, 2, 2]}]})],
           # 2 text, a 1 x 2 x 2 image grid at 2, then 3 text: t = 0 1 2 2 2 2 4 5 6; h = 0 1 2 2 3 3 4 5 6; w = 0 1 2 3 2 3 4 5 6
           expect=["steps.img.result.value.positions == [[0, 1, 2, 2, 2, 2, 4, 5, 6], [0, 1, 2, 2, 3, 3, 4, 5, 6], [0, 1, 2, 3, 2, 3, 4, 5, 6]]",
                   "steps.img.result.value.mrope_position_delta == -2",
                   # video: t_factor 2.0, grid 2 x 1 x 2 at offset 1 -> t 1 1 3 3, then text 4
                   "steps.vid.result.value.positions[0] == [0, 1, 1, 3, 3, 4] && steps.vid.result.value.positions[2] == [0, 1, 2, 1, 2, 4]",
                   "!steps.bad.result.ok && steps.bad.result.error.message == 'Image must have 1 frame, got 2'"]),
        sc("models-qwen2-vl-image-token-count", fixtures=["full-" + VL],
           steps=[ist("qwen2-vl-processing-info.get-num-image-tokens", "vga", {"image_width": 640, "image_height": 480}),
                  ist("qwen2-vl-processing-info.get-num-image-tokens", "tiny", {"image_width": 20, "image_height": 20}),
                  ist("qwen2-vl-processing-info.get-num-image-tokens", "huge", {"image_width": 8192, "image_height": 8192}),
                  ist("qwen2-vl-processing-info.get-num-image-tokens", "thin", {"image_width": 4020, "image_height": 20}),
                  ist("qwen2-vl-processing-info.get-supported-mm-limits", "lim", {})],
           # 640x480 -> 644x476 (23 x 28, 17 x 28): grid 34 x 46, 391 tokens; 20x20 -> 56x56 (min pixels): 4 tokens; 8192^2 -> 3584^2 (max pixels): 16384 tokens
           expect=["steps.vga.result.value.resized_width == 644 && steps.vga.result.value.resized_height == 476 && steps.vga.result.value.grid_thw == [1, 34, 46] && steps.vga.result.value.num_tokens == 391",
                   "steps.tiny.result.value.resized_width == 56 && steps.tiny.result.value.num_tokens == 4",
                   "steps.huge.result.value.resized_width == 3584 && steps.huge.result.value.num_tokens == 16384",
                   "!steps.thin.result.ok && steps.thin.result.error.message.startsWith('absolute aspect ratio must be smaller than 200, got 201')",
                   "steps.lim.result.value.image == null && steps.lim.result.value.video == null"]),
        sc("models-mm-create-processor-text-only-served-name", fixtures=["full-tp1-llama-8b"],
           steps=[ist("multi-modal-registry.create-processor", "llama", {"model": "meta-llama/Llama-3.1-8B-Instruct", "architectures": ["LlamaForCausalLM"], "served_model_name": "llama-8b"}),
                  ist("multi-modal-registry.create-processor", "flag", {"model": QWEN, "architectures": ["Qwen2VLForConditionalGeneration"], "is_multimodal_model": False}),
                  ist("multi-modal-registry.create-processor", "qwen", {"model": QWEN, "architectures": ["Qwen2VLForConditionalGeneration"], "served_model_name": "qwen2-vl-7b"})],
           expect=["!steps.llama.result.ok && steps.llama.result.error.message == 'llama-8b is not a multimodal model'",
                   "!steps.flag.result.ok && steps.flag.result.error.message == 'Qwen/Qwen2-VL-7B-Instruct is not a multimodal model'",
                   "steps.qwen.result.ok && steps.qwen.result.value.info == 'Qwen2VLProcessingInfo'",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'model-loader-utils.get-model-architecture').size() == 3"]),
    ]
    # ---------------------------------------------------------------- media fetching
    url = "https://vllm-public-assets.s3.us-west-2.amazonaws.com/vision_model_images/stop_sign.jpg"
    L += [
        sc("models-mm-fetch-image-urls", fixtures=["full-" + VL],
           state={"remote-media-host": {"urls": {"https://example.com/cat.png": {"size": 4096, "content_type": "image/png"}}}},
           steps=[step("models-mm-fetch-image", as_="s3"),
                  ist("media-connector.fetch-image", "web", {"image_url": "https://example.com/cat.png"}),
                  ist("media-connector.fetch-image", "missing", {"image_url": "https://example.com/missing.jpg"}),
                  ist("media-connector.fetch-image", "s3missing", {"image_url": "https://vllm-public-assets.s3.us-west-2.amazonaws.com/nope.jpg"}),
                  ist("media-connector.fetch-image", "data", {"image_url": "data:image/jpeg;base64,/9j/4AAQ"}),
                  ist("media-connector.fetch-image", "nocomma", {"image_url": "data:image/jpeg;base64"}),
                  ist("media-connector.fetch-image", "plain", {"image_url": "data:text/plain,hello"}),
                  ist("media-connector.fetch-image", "domain", {"image_url": "https://example.com/cat.png", "allowed_media_domains": ["upload.wikimedia.org"]}),
                  ist("media-connector.fetch-image", "file", {"image_url": "file:///tmp/a.jpg"}),
                  ist("media-connector.fetch-image", "ftp", {"image_url": "ftp://example.com/a.jpg"})],
           expect=["steps.s3.result.ok && steps.s3.result.value.bytes == 59248 && steps.s3.result.value.media_type == 'image/jpeg'",
                   "steps.web.result.ok && steps.web.result.value.media_type == 'image/png'",
                   "!steps.missing.result.ok && steps.missing.result.error.code == 'vllm-unprocessable-entity-error' && steps.missing.result.error.status == 422 && steps.missing.result.error.message == 'Failed to fetch media from URL: HTTP 404 error'",
                   "!steps.s3missing.result.ok && steps.s3missing.result.error.status == 422",
                   "steps.data.result.ok && steps.data.result.value.source == 'data' && steps.data.result.value.media_type == 'image/jpeg'",
                   "!steps.nocomma.result.ok && steps.nocomma.result.error.message == \"Invalid data URL 'data:image/jpeg;base64': missing ',' separator.\"",
                   "!steps.plain.result.ok && steps.plain.result.error.code == 'not-implemented-error' && steps.plain.result.error.message == 'Only base64 data URLs are supported for now.'",
                   "!steps.domain.result.ok && steps.domain.result.error.message == \"The URL must be from one of the allowed domains: ['upload.wikimedia.org']. Input URL domain: example.com\"",
                   "!steps.file.result.ok && steps.file.result.error.code == 'runtime-error' && steps.file.result.error.message == 'Cannot load local files without `--allowed-local-media-path`.'",
                   "!steps.ftp.result.ok && steps.ftp.result.error.message == 'The URL must be either a HTTP, data or file URL.'",
                   "io.exists(i, i.interface == 'vllm-public-assets-s3.get-object')"]),
    ]
    # ---------------------------------------------------------------- round-5 unit tests (build-oracle/round5)
    L += [
        sc("models-cohere-asr-audio-token-estimate", fixtures=["full-tp1-llama-8b"],
           steps=[ist("cohere-asr-for-conditional-generation.get-num-audio-tokens", f"d{int(d)}",
                      {"audio_duration_s": d, "preprocessor": {"window_stride": 0.01, "sample_rate": 16000}, "encoder": {"subsampling_factor": 8}})
                  for d in (1.0, 10.0, 30.0)],
           expect=["steps.d1.result.value.num_tokens == 13 && steps.d10.result.value.num_tokens == 125 && steps.d30.result.value.num_tokens == 375"]),
        sc("models-quant-find-matching-patterns", fixtures=["full-tp1-llama-8b"],
           steps=[ist("quant-config-utils.find-matching-patterns", p, {"layer_name": "model.layers.0.self_attn.qkv_proj", "patterns": pats,
                                                                          "fused_mapping": {"qkv_proj": ["q_proj", "k_proj", "v_proj"]}})
                  for p, pats in (("direct", ["re:.*qkv_proj.*"]), ("shards", ["re:.*\\.[qkv]_proj$"]),
                                  ("each", ["re:.*\\.q_proj$", "re:.*\\.k_proj$", "re:.*\\.v_proj$"]), ("none", ["model.layers.1.mlp"]))]
                 + [ist("quant-config-utils.find-matching-patterns", "fn", {"layer_name": "model.layers.0.mlp.experts", "patterns": ["*mlp.experts*"], "use_fnmatch": True}),
                    ist("quant-config-utils.find-matching-patterns", "nofn", {"layer_name": "model.layers.0.mlp.experts", "patterns": ["*mlp.experts*"]})],
           expect=["steps.direct.result.value.matches == [['re:.*qkv_proj.*']]",
                   "size(steps.shards.result.value.matches) == 3 && steps.shards.result.value.matches.all(m, size(m) == 1)",
                   "steps.each.result.value.matches == [['re:.*\\\\.q_proj$'], ['re:.*\\\\.k_proj$'], ['re:.*\\\\.v_proj$']]",
                   "steps.none.result.value.matches == [[], [], []]",
                   "steps.fn.result.value.matches == [['*mlp.experts*']] && steps.nofn.result.value.matches == [[]]"]),
        sc("models-quant-online-overlay-needs-normalized-args", fixtures=["full-tp1-llama-8b"],
           steps=[ist("weight-utils.get-quant-config", "raw", {"quantization": "compressed-tensors", "hf_quant_config": {"quant_method": "compressed-tensors", "format": "pack-quantized", "config_groups": {}},
                                                                "online_args": {"linear": "mxfp8"}, "online_args_type": "dict"}),
                  ist("weight-utils.get-quant-config", "args", {"quantization": "compressed-tensors", "hf_quant_config": {"quant_method": "compressed-tensors", "format": "pack-quantized", "config_groups": {}},
                                                                 "online_args": {"moe": {"activation": "mxfp8"}}})],
           expect=["!steps.raw.result.ok && steps.raw.result.error.code == 'assertion-error'",
                   "steps.args.result.ok && steps.args.result.value.config_cls == 'CompressedTensorsConfig' && steps.args.result.value.online_composed"]),
        sc("models-lora-native-classifier-modules-to-save", fixtures=["full-tp1-llama-8b"], config={"max-lora-rank": 8},
           state={"lru-cache-lora-model-manager": {"classification_head": {"module": "score", "max_lora_cls_labels": 1, "input_size": 1024}},
                  "local-disk": {"files": dict(lora_files("native", {}, {"modules_to_save": ["score"]}, {"score": {"weight_shape": [1, 1024], "bias_shape": None}}),
                                               **lora_files("wide", {}, {"modules_to_save": ["score"]}, {"score": {"weight_shape": [2, 1024]}}),
                                               **lora_files("other", {}, {"modules_to_save": ["classifier"]}, {"classifier": {"weight_shape": [1, 1024]}}))}},
           steps=[addl("native", "native", 1), addl("wide", "wide", 2), addl("other", "other", 3)],
           expect=["steps.native.result.ok && steps.native.result.value.loaded && state['lru-cache-lora-model-manager@rank0'].registered == [1]",
                   "!steps.wide.result.ok && steps.wide.result.error.message == \"Full module 'score' for 'score' has an incompatible weight shape: expected (1..1, 1024), received (2, 1024).\"",
                   "!steps.other.result.ok && steps.other.result.error.message == \"Full module 'classifier' does not match the model's classification head 'score'.\""]),
        sc("models-lora-modules-to-save-without-head", fixtures=["full-tp1-llama-8b"],
           state={"local-disk": {"files": lora_files("native", {}, {"modules_to_save": ["score"]}, {"score": {"weight_shape": [1, 4096]}})}},
           steps=[addl("add", "native", 1)],
           expect=["!steps.add.result.ok && steps.add.result.error.message == \"Cannot load full module 'score': the model does not expose a unique ClassificationHeadWithLoRA.\""]),
    ]
    # ---------------------------------------------------------------- kernels-ops round-5 tests (their build oracle)
    L += [
        sc("models-flashinfer-ssu-import-error", fixtures=["full-tp1-llama-8b"],
           steps=[ist("flashinfer-ssu-backend.init", "missing", {"flashinfer_mamba_available": False}), ist("flashinfer-ssu-backend.init", "ok", {})],
           expect=["!steps.missing.result.ok && steps.missing.result.error.code == 'import-error' && steps.missing.result.error.message.startsWith('FlashInfer is required')",
                   "steps.missing.result.error.message == 'FlashInfer is required for the flashinfer Mamba SSU backend. Please install flashinfer (>= 0.6.4): pip install flashinfer-python'",
                   "steps.ok.result.ok"]),
        sc("models-routed-experts-padding-narrow", fixtures=["full-tp1-llama-8b"],
           steps=[ist("routed-experts.get-hidden-dim", "hd", {"shard_dim": 0, "ndim": 2}),
                  ist("routed-experts.get-hidden-dim", "hd3", {"shard_dim": 1, "ndim": 3}),
                  ist("routed-experts.get-hidden-dim", "hd1", {"shard_dim": 0, "ndim": 1}),
                  ist("routed-experts.get-hidden-dim", "bad", {"shard_dim": 0, "ndim": 3}),
                  ist("routed-experts.narrow-expert-data-for-padding", "w2t", {"expert_shape": [1024, 3072], "loaded_shape": [1024, 2688], "hidden_dim": 1}),
                  ist("routed-experts.narrow-expert-data-for-padding", "full3d", {"expert_shape": [8, 3072, 1024], "loaded_shape": [8, 2688, 1024], "hidden_dim": 1}),
                  ist("routed-experts.narrow-expert-data-for-padding", "scale", {"expert_shape": [3072], "loaded_shape": [2688], "hidden_dim": 0}),
                  ist("routed-experts.narrow-expert-data-for-padding", "shard", {"expert_shape": [3072, 3072], "loaded_shape": [2880, 2688], "hidden_dim": 1, "shard_dim": 0})],
           expect=["steps.hd.result.value.hidden_dim == 1 && steps.hd3.result.value.hidden_dim == 2 && steps.hd1.result.value.hidden_dim == 0",
                   "!steps.bad.result.ok && steps.bad.result.error.message == 'shard_dim=0 is not a valid data dimension for a 3D tensor (expected 1 or 2)'",
                   "steps.w2t.result.value.shape == [1024, 2688] && steps.full3d.result.value.shape == [8, 2688, 1024] && steps.scale.result.value.shape == [2688]",
                   "steps.shard.result.value.shape == [2880, 2688]"]),
    ]
    return L


def patch(doc):
    """Add the round-5 optional fields to the shared request schemas (non-breaking)."""
    add = {
        "ModelsHfConfig": {"vision_config": {"type": ["object", "null"], "default": None},
                           "rope_scaling": {"type": ["object", "null"], "default": None},
                           "kv_scales": {"type": ["object", "null"], "default": None,
                                         "description": "per-tensor k/v/q scales an FP8-KV checkpoint stores (a world may give their values)"},
                           "image_token_id": {"type": "integer", "examples": [151655]},
                           "video_token_id": {"type": "integer", "examples": [151656]},
                           "model_type": {"type": "string", "examples": ["qwen2_vl"]}},
        "ModelsForwardRequest": {"inputs_embeds": {"type": "boolean", "default": False,
                                                   "description": "the runner passes merged multimodal inputs_embeds instead of input_ids (Qwen2-VL)"},
                                 "positions_ndim": {"type": "integer", "default": 1, "description": "2 for M-RoPE (3, N) positions"}},
        "ModelsLoRARequest": {"is_3d_lora_weight": {"type": "boolean", "default": False}},
        "ModelsLoadedModel": {"kv_quant_method": {"type": "string"}, "kv_scales": {"type": "object"}},
    }
    for s in doc["schemas"]:
        if s["id"] in add:
            s["schema"].setdefault("properties", {}).update(add[s["id"]])


def extra():
    return {"configs": configs(), "flows": flows(), "scenarios": scenario_list(), "fixtures": variants()}

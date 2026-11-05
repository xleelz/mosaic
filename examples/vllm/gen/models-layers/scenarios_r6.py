"""Fix round 6 (mechanism coverage): configs, schema additions, flows and regression scenarios for
core-r6.yaml (kernel warmup and FlashInfer autotune, Qwen-VL warmup and Qwen3-VL, EmbeddingGemma2,
the pooler, the shm processor cache, MoE expert placement) and the round-6 edits in older files."""
from scenarios import cfg, sc, step
from scenarios_r5 import env

MOE_W = ["full-moe-mixtral-8x7b-tp2-ep"]
VL_W = ["full-vl-qwen2-vl-7b"]
TP1 = ["full-tp1-llama-8b"]
MIXTRAL = "mistralai/Mixtral-8x7B-Instruct-v0.1"
MIXTRAL_HF = {"architectures": ["MixtralForCausalLM"], "hidden_size": 4096, "intermediate_size": 14336,
              "max_position_embeddings": 32768, "num_attention_heads": 32, "num_experts_per_tok": 2,
              "num_hidden_layers": 32, "num_key_value_heads": 8, "num_local_experts": 8, "torch_dtype": "bfloat16",
              "vocab_size": 32000, "weights_bytes": 93405585408}
QWEN3 = "Qwen/Qwen3-VL-8B-Instruct"
QWEN3_HF = {"architectures": ["Qwen3VLForConditionalGeneration"], "model_type": "qwen3_vl", "num_hidden_layers": 36,
            "num_attention_heads": 32, "num_key_value_heads": 8, "hidden_size": 4096, "vocab_size": 151936,
            "max_position_embeddings": 262144, "torch_dtype": "bfloat16", "weights_bytes": 17534340096,
            "image_token_id": 151655, "video_token_id": 151656,
            "text_config": {"num_hidden_layers": 36, "num_attention_heads": 32, "num_key_value_heads": 8, "hidden_size": 4096,
                            "intermediate_size": 12288, "head_dim": 128, "vocab_size": 151936},
            "vision_config": {"hidden_size": 1152, "num_heads": 16, "depth": 27, "patch_size": 16, "spatial_merge_size": 2,
                              "temporal_patch_size": 2, "num_position_embeddings": 2304, "out_hidden_size": 4096,
                              "intermediate_size": 4304, "deepstack_visual_indexes": [8, 16, 24]}}
EG2 = "google/embeddinggemma-2"
EG2_HF = {"architectures": ["EmbeddingGemma2Model"], "model_type": "embedding_gemma2", "num_hidden_layers": 4,
          "num_attention_heads": 8, "num_key_value_heads": 1, "hidden_size": 1152, "vocab_size": 262144,
          "max_position_embeddings": 8192, "torch_dtype": "bfloat16", "weights_bytes": 600000000,
          "text_config": {"sliding_window": 512, "layer_types": ["sliding_attention", "sliding_attention", "sliding_attention", "full_attention"]}}
QWEN3_RUNNER = {"name": QWEN3, "architecture": "Qwen3VLForConditionalGeneration", "num_hidden_layers": 36, "num_kv_heads": 8,
                "num_attention_heads": 32, "head_size": 128, "dtype_bytes": 2, "torch_dtype": "bfloat16", "vocab_size": 151936,
                "hidden_size": 4096, "max_position_embeddings": 262144, "weights_bytes": 17500000000, "eos_token_id": 151645,
                "is_hybrid": False, "uses_mrope": True, "uses_prompt_embeds": False}


def ist(iface, as_, inp=None, on=None, nowait=False):
    return step(iface=iface, as_=as_, inp=inp, on=on, nowait=nowait)


def configs():
    return [
        cfg("enable-flashinfer-autotune", "boolean", None, None,
            "kernel_config.enable_flashinfer_autotune (--kernel-config): None until the optimization level resolves it (False at -O0, True at -O1..-O3; the default -O2 gives True). Deployed = default.",
            ["vllm/config/kernel.py:279-280", "vllm/config/vllm.py:264-330", "vllm/config/vllm.py:1781-1785"], "enable_flashinfer_autotune"),
        cfg("optimization-level", "integer", 2, 2, "-O / optimization_level (reference copy): resolves enable_flashinfer_autotune.",
            ["vllm/config/vllm.py:427"], "optimization_level", owner="config-platform"),
        cfg("attention-backend", "string", None, None, "attention_backend (reference copy): EmbeddingGemma2 picks TRITON_ATTN when it is unset.",
            ["vllm/config/attention.py:40"], "backend", owner="attention"),
        cfg("api-server-count", "integer", None, None, "--api-server-count (reference copy): ParallelConfig._api_process_count; more than one API process turns the IPC processor caches off.",
            ["vllm/config/parallel.py:443"], "api_server_count", owner="config-platform"),
        env(cfg("vllm-media-fetch-max-retries", "integer", 3, 3, "VLLM_MEDIA_FETCH_MAX_RETRIES (reference copy): attempts _retry/_async_retry make for a media download (at least 1).",
            ["vllm/envs.py:79", "vllm/envs.py:999-1001"], "VLLM_MEDIA_FETCH_MAX_RETRIES", owner="config-platform")),
        cfg("media-stand-in-image-width", "integer", 1120, 1120, "ASSUMPTION: the width of a fetched image. The code decodes it with PIL (ImageMediaIO.load_bytes); the simulation has no pixels, so a media reference stands for an image of this size.",
            ["vllm/multimodal/media/image.py:79-90"], "media_stand_in_image_width"),
        cfg("media-stand-in-image-height", "integer", 560, 560, "ASSUMPTION: the height of a fetched image, as for media-stand-in-image-width.",
            ["vllm/multimodal/media/image.py:79-90"], "media_stand_in_image_height"),
        cfg("skip-mm-profiling", "boolean", False, False, "MultiModalConfig.skip_mm_profiling (--skip-mm-profiling): skip the encoder tower's memory profile at startup.",
            ["vllm/config/multimodal.py:423"], "skip_mm_profiling"),
        cfg("mm-hasher-algorithm", "string", "blake3", "blake3",
            "MultiModalConfig.mm_hasher_algorithm (--mm-hasher-algorithm): blake3, sha256 or sha512 for the multimodal item hashes. Deployed = default.",
            ["vllm/config/multimodal.py:372", "vllm/multimodal/hasher.py:47-70"], "mm_hasher_algorithm"),
        cfg("mm-encoder-tp-mode", "string", "weights", "weights", "MultiModalConfig.mm_encoder_tp_mode (reference copy): weights shards the tower across TP; data runs a whole tower per rank on a balanced share of the items.",
            ["vllm/config/multimodal.py:385"], "mm_encoder_tp_mode", owner="config-platform"),
        cfg("expert-placement-strategy", "string", "linear", "linear",
            "ParallelConfig.expert_placement_strategy (--expert-placement-strategy): linear (contiguous experts per EP rank) or round_robin (strided; only for models with expert groups and no redundant experts or EPLB). Deployed = default.",
            ["vllm/config/parallel.py:209", "vllm/engine/arg_utils.py:470"], "expert_placement_strategy"),
        cfg("mm-shm-cache-max-object-size-mb", "integer", 128, 128,
            "mm_shm_cache_max_object_size_mb (reference copy): the largest serialized item the shm processor cache stores.",
            ["vllm/config/multimodal.py:375"], "mm_shm_cache_max_object_size_mb", owner="config-platform"),
    ]


def patch(doc):
    """Add the round-6 optional fields to the shared schemas (non-breaking)."""
    add = {
        "ModelsHfConfig": {"text_config": {"type": ["object", "null"], "default": None, "description": "nested text model config (Qwen3-VL, EmbeddingGemma2)"},
                           "sliding_window": {"type": ["integer", "null"], "default": None},
                           "layer_types": {"type": ["array", "null"], "default": None},
                           "head_dim": {"type": ["integer", "null"], "default": None},
                           "is_causal": {"type": "boolean", "default": True},
                           "num_labels": {"type": "integer", "examples": [2]}},
        "ModelsLoadedModel": {"online_quant_summary": {"type": ["string", "null"]}, "layers": {"type": "array", "items": {"type": "object"},
                                         "description": "per decoder layer: layer_type, attn_type, per_layer_sliding_window and the attention impl's (left, right) window (models whose init reports them)"}},
        "ModelsModelInfo": {"default_seq_pooling_type": {"type": "string"}, "default_tok_pooling_type": {"type": "string"},
                            "attn_type": {"type": "string"}},
        "ModelsResolvedClass": {"default_seq_pooling_type": {"type": "string"}, "default_tok_pooling_type": {"type": "string"},
                                "attn_type": {"type": "string"}},
    }
    for s in doc["schemas"]:
        if s["id"] in add:
            s["schema"].setdefault("properties", {}).update(add[s["id"]])


def flows():
    def f(id_, name, iface, src, inp=None, tags=None):
        d = {"id": id_, "name": name, "entry": {"caller": "gpu-worker", "interface": iface}, "sources": src}
        if inp is not None:
            d["entry"]["input"] = inp
        if tags:
            d["tags"] = tags
        return d
    return [
        f("models-kernel-warmup", "Kernel warmup after the compile-size dummy runs (Worker.compile_or_warm_up_model)", "kernel-warmup.kernel-warmup",
          ["vllm/model_executor/warmup/kernel_warmup.py:162-290", "vllm/v1/worker/gpu_worker.py:949-950"], {}),
        f("models-qwen-vl-triton-warmup", "Qwen-VL Triton warmup (vision position/rotary kernels and M-RoPE)", "qwen-vl-triton-warmup.qwen-vl-triton-warmup",
          ["vllm/model_executor/warmup/qwen_vl_triton_warmup.py:110-116"], {"architecture": "Qwen3VLForConditionalGeneration"}),
        f("models-pooler-forward", "The pooling model's pooler on a batch (DispatchPooler.forward)", "dispatch-pooler.forward",
          ["vllm/model_executor/layers/pooler/special.py:91-146"],
          {"requests": [{"task": "embed", "prompt_len": 12}], "seq_pooling_type": "CLS", "hidden_size": 768}),
        f("models-shm-cache-put", "P0 stores a processed item in the shared-memory processor cache", "shm-object-store-sender-cache.get-and-update",
          ["vllm/multimodal/cache/shm.py:112-170"], {"mm_hash": "img-a", "size_bytes": 1048576}, ["writes"]),
    ]


def scenario_list():
    L = []
    # ---------------------------------------------------------------- kernel warmup and autotune (oracle4)
    L += [
        sc("models-r6-autotune-token-counts-deferred-moe", fixtures=TP1,
           # test_flashinfer_autotune_warmup.py: limits 128, 128, 64 (disabled), -1 (unbounded) -> (8192, 128)
           steps=[ist("kernel-warmup.flashinfer-autotune-token-counts", "tc", {"max_num_batched_tokens": 8192, "moe_configs": [
               {"use_deferred_moe_finalize": True, "defer_moe_finalize_max_num_tokens": 128},
               {"use_deferred_moe_finalize": True, "defer_moe_finalize_max_num_tokens": 128},
               {"use_deferred_moe_finalize": False, "defer_moe_finalize_max_num_tokens": 64},
               {"use_deferred_moe_finalize": True, "defer_moe_finalize_max_num_tokens": -1}]}),
                  ist("kernel-warmup.flashinfer-autotune-token-counts", "cap", {"max_num_batched_tokens": 64, "moe_configs": [
                      {"use_deferred_moe_finalize": True, "defer_moe_finalize_max_num_tokens": 128}]})],
           expect=["steps.tc.result.value.token_counts == [8192, 128]",
                   "steps.cap.result.value.token_counts == [64]"]),
        sc("models-r6-deferred-moe-finalize-config", fixtures=TP1,
           steps=[ist("fused-moe-config.defer-moe-finalize", "tp2", {"requested": True, "max_num_tokens": 128, "tp_size": 2}),
                  ist("fused-moe-config.defer-moe-finalize", "ep", {"requested": True, "max_num_tokens": 128, "tp_size": 2, "ep_size": 2}),
                  ist("fused-moe-config.defer-moe-finalize", "lower", {"requested": True, "max_num_tokens": 256, "current_max_num_tokens": 128, "tp_size": 2}),
                  ist("fused-moe-config.defer-moe-finalize", "pad", {"requested": True, "tp_size": 2, "hidden_dim": 3072, "hidden_dim_unpadded": 2880}),
                  ist("fused-moe-config.should-defer-moe-finalize", "inside", {"num_tokens": 128, "use_deferred_moe_finalize": True, "defer_moe_finalize_max_num_tokens": 128}),
                  ist("fused-moe-config.should-defer-moe-finalize", "over", {"num_tokens": 129, "use_deferred_moe_finalize": True, "defer_moe_finalize_max_num_tokens": 128}),
                  ist("fused-moe-config.should-defer-moe-finalize", "empty", {"num_tokens": 0, "use_deferred_moe_finalize": True})],
           expect=["steps.tp2.result.value.use_deferred_moe_finalize && steps.tp2.result.value.defer_moe_finalize_max_num_tokens == 128",
                   "!steps.ep.result.value.use_deferred_moe_finalize",
                   "steps.lower.result.value.defer_moe_finalize_max_num_tokens == 128",
                   "!steps.pad.result.value.use_deferred_moe_finalize",
                   "steps.inside.result.value.defer && !steps.over.result.value.defer && !steps.empty.result.value.defer"]),
        # The Mixtral world: both TP ranks warm up together; Mixtral never defers, so one 8192-token profile run
        sc("models-r6-kernel-warmup-autotune-mixtral", fixtures=MOE_W,
           steps=[ist("kernel-warmup.kernel-warmup", "w0", {}, "rank0", nowait=True),
                  ist("kernel-warmup.kernel-warmup", "w1", {}, "rank1")],
           expect=["steps.w0.result.ok && steps.w1.result.ok && steps.w0.result.value.autotuned",
                   "steps.w0.result.value.token_counts == [8192]",
                   "trace.exists(e, e.type == 'call.start' && e.interface == 'gpu-model-runner.dummy-run' && e.input.num_tokens == 8192 && e.input.is_profile)",
                   "!trace.exists(e, e.type == 'call.start' && e.interface == 'gpu-model-runner.dummy-run' && e.input.num_tokens == 128)"]),
        # A deferring model (seeded per-layer requests) on TP 2 without EP: the 128 limit adds a second pass
        sc("models-r6-kernel-warmup-autotune-deferred-layers", fixtures=MOE_W,
           config={"enable-expert-parallel": False},
           state={"mixtral-for-causal-lm@rank0": {"cfg": {"ep_size": 1, "moe_tp": 2, "defer_moe_finalize_requests": [{"max_num_tokens": 128}, {"max_num_tokens": 128}, {"requested": False, "max_num_tokens": 64}, {"max_num_tokens": -1}]}},
                  "mixtral-for-causal-lm@rank1": {"cfg": {"ep_size": 1, "moe_tp": 2, "defer_moe_finalize_requests": [{"max_num_tokens": 128}, {"max_num_tokens": 128}, {"requested": False, "max_num_tokens": 64}, {"max_num_tokens": -1}]}}},
           steps=[ist("kernel-warmup.kernel-warmup", "w0", {}, "rank0", nowait=True),
                  ist("kernel-warmup.kernel-warmup", "w1", {}, "rank1")],
           expect=["steps.w0.result.ok && steps.w0.result.value.token_counts == [8192, 128]",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'gpu-model-runner.dummy-run' && e.instance == 'rank0').map(e, e.input.num_tokens) == [8192, 128]"]),
        sc("models-r6-kernel-warmup-autotune-disabled-o0", fixtures=TP1, config={"optimization-level": 0},
           steps=[ist("kernel-warmup.kernel-warmup", "w")],
           expect=["steps.w.result.ok && !steps.w.result.value.autotuned && steps.w.result.value.autotune_skipped == 'Skipping FlashInfer autotune because it is disabled.'",
                   "!trace.exists(e, e.type == 'call.start' && e.interface == 'gpu-model-runner.dummy-run')"]),
        sc("models-r6-kernel-warmup-autotune-pre-hopper", fixtures=TP1,
           state={"cuda-platform": {"device_capability": {"major": 8, "minor": 0}}},
           steps=[ist("kernel-warmup.kernel-warmup", "w")],
           expect=["steps.w.result.ok && !steps.w.result.value.autotuned && steps.w.result.value.autotune_skipped == 'device capability below 9.0'",
                   "!trace.exists(e, e.type == 'call.start' && e.interface == 'gpu-model-runner.dummy-run')"]),
        sc("models-r6-kernel-warmup-process-local-only", fixtures=TP1,
           steps=[ist("kernel-warmup.kernel-warmup", "w", {"process_local_only": True})],
           expect=["steps.w.result.ok && steps.w.result.value.autotune_skipped == 'process_local_only'",
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'qwen-vl-triton-warmup.qwen-vl-triton-warmup' && e.output.vision_grids == [])"]),
    ]
    # ---------------------------------------------------------------- Qwen-VL warmup and Qwen3-VL (oracle4)
    L += [
        sc("models-r6-qwen-vl-warmup-qwen3-vl-grids", fixtures=VL_W,
           state={"gpu-model-runner": {"model": QWEN3_RUNNER}},
           steps=[ist("kernel-warmup.kernel-warmup", "w", {"process_local_only": True})],
           expect=["steps.w.result.ok",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'qwen3-vision-transformer.fast-pos-embed-interpolate').map(e, e.input.grid_thw[0]) == [[1, 16, 16], [1, 16, 2], [1, 2, 16], [1, 2, 2]]",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'qwen3-vision-attention.apply-rotary-emb').map(e, e.input.num_tokens) == [256, 32, 32, 4]",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'm-rotary-embedding.forward-cuda').map(e, e.input.num_tokens) == [1, 2, 16]",
                   "!trace.exists(e, e.type == 'call.start' && e.interface == 'qwen3-vision-transformer.forward')"]),
        sc("models-r6-qwen-vl-warmup-cpu-offloaded-tower", fixtures=VL_W,
           state={"qwen3-vl-for-conditional-generation": {"cfg": {"vision": {"device": "cpu", "hidden_size": 1152, "num_heads": 16, "spatial_merge_size": 2, "num_position_embeddings": 2304}}}},
           steps=[ist("qwen-vl-triton-warmup.qwen-vl-triton-warmup", "w", {"architecture": "Qwen3VLForConditionalGeneration"})],
           expect=["steps.w.result.ok && steps.w.result.value.vision_grids == [] && steps.w.result.value.mrope_token_counts == [1, 2, 16]",
                   "!trace.exists(e, e.type == 'call.start' && e.interface == 'qwen3-vision-transformer.fast-pos-embed-interpolate')"]),
        sc("models-r6-qwen-vl-warmup-qwen2-vl-mrope-only", fixtures=VL_W,
           steps=[ist("qwen-vl-triton-warmup.qwen-vl-triton-warmup", "w", {"architecture": "Qwen2VLForConditionalGeneration"}),
                  ist("qwen-vl-triton-warmup.qwen-vl-triton-warmup", "llama", {"architecture": "LlamaForCausalLM"})],
           expect=["steps.w.result.value.vision_grids == [] && steps.w.result.value.mrope_token_counts == [1, 2, 16]",
                   "steps.llama.result.value.mrope_token_counts == []",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'm-rotary-embedding.forward-cuda').size() == 3"]),
        sc("models-r6-qwen3-vl-load-encode-forward", fixtures=VL_W,
           state={"hf-hub": {"models": {QWEN3: QWEN3_HF}}},
           steps=[ist("base-model-loader.load-model", "ld", {"loader": "default-model-loader", "model": QWEN3, "hf_config": {"architectures": ["Qwen3VLForConditionalGeneration"]}}),
                  ist("qwen3-vl-for-conditional-generation.embed-multimodal", "enc", {"mm_kwargs": [{"modality": "image", "grid_thw": [1, 32, 48]}]}),
                  ist("qwen3-vl-for-conditional-generation.forward", "fwd", {"num_tokens": 400, "num_reqs": 1, "inputs_embeds": True}),
                  ist("qwen3-vl-for-conditional-generation.compute-logits", "lg", {"num_tokens": 1}),
                  ist("qwen3-vl-processing-info.get-num-image-tokens", "tok", {"image_width": 1536, "image_height": 1024})],
           expect=["state['qwen3-vl-for-conditional-generation@rank0'].loaded",
                   "steps.ld.result.ok && steps.ld.result.value.component == 'qwen3-vl-for-conditional-generation' && steps.ld.result.value.model_cls == 'Qwen3VLForConditionalGeneration'",
                   "steps.enc.result.value.num_tokens == 384 && steps.enc.result.value.embeddings[0].deepstack_levels == 3",
                   "steps.fwd.result.ok && steps.fwd.result.value.num_layers == 36",
                   "steps.lg.result.ok",
                   "steps.tok.result.value.grid_thw == [1, 64, 96] && steps.tok.result.value.num_tokens == 1536"]),
        sc("models-r6-qwen3-vl-placeholder", fixtures=VL_W,
           steps=[ist("qwen3-vl-for-conditional-generation.get-placeholder-str", "img", {"modality": "image"}),
                  ist("qwen3-vl-for-conditional-generation.get-placeholder-str", "aud", {"modality": "audio"})],
           expect=["steps.img.result.value.placeholder == '<|vision_start|><|image_pad|><|vision_end|>'",
                   "!steps.aud.result.ok && steps.aud.result.error.message == 'Only image or video modality is supported'"]),
    ]
    # ---------------------------------------------------------------- EmbeddingGemma2 (oracle4)
    L += [
        sc("models-r6-embedding-gemma2-sliding-window-offset", fixtures=TP1,
           config={"model": EG2, "runner": "pooling", "max-model-len": 8192},
           state={"hf-hub": {"models": {EG2: EG2_HF}}},
           steps=[ist("model-loader.get-model", "load", {"model": EG2, "hf_config": {"architectures": ["EmbeddingGemma2Model"]}})],
           expect=["steps.load.result.ok && steps.load.result.value.component == 'embedding-gemma2-model'",
                   "steps.load.result.value.layers.map(l, l.sliding_window) == [[512, 512], [512, 512], [512, 512], [-1, -1]]",
                   "steps.load.result.value.layers.all(l, l.attn_type == 'encoder_only') && steps.load.result.value.layers[0].per_layer_sliding_window == 513",
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'dispatch-pooler.for-embedding' && e.output.supported_tasks == ['token_embed', 'embed'] && e.output.seq_pooling_type == 'MEAN')"]),
        sc("models-r6-embedding-gemma2-flash-attn-backend", fixtures=TP1,
           config={"attention-backend": "FLASH_ATTN"},
           state={"hf-hub": {"models": {EG2: EG2_HF}}},
           steps=[ist("model-loader.get-model", "load", {"model": EG2, "hf_config": {"architectures": ["EmbeddingGemma2Model"]}})],
           expect=["steps.load.result.ok && steps.load.result.value.layers[0].sliding_window == [512, 512]",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'flash-attention-impl.init').size() == 4"]),
        sc("models-r6-attention-layer-window-rule", fixtures=TP1,
           steps=[ist("attention-layer.init", "dec", {"num_heads": 32, "head_size": 128, "per_layer_sliding_window": 4096, "backend": "TRITON_ATTN"}),
                  ist("attention-layer.init", "none", {"num_heads": 32, "head_size": 128, "backend": "TRITON_ATTN"}),
                  ist("attention-layer.init", "cache", {"num_heads": 32, "head_size": 128, "cache_sliding_window": 1024, "attn_type": "encoder", "backend": "TRITON_ATTN"})],
           expect=["steps.dec.result.value.impl_sliding_window == [4095, 0]",
                   "steps.none.result.value.impl_sliding_window == [-1, -1] && steps.none.result.value.sliding_window == null",
                   "steps.cache.result.value.impl_sliding_window == [1023, 1023]"]),
        sc("models-r6-embedding-gemma2-placeholder", fixtures=TP1,
           steps=[ist("embedding-gemma2-model.get-placeholder-str", "a", {"modality": "audio"}),
                  ist("embedding-gemma2-model.get-placeholder-str", "x", {"modality": "point_cloud"})],
           expect=["steps.a.result.value.placeholder == '<|audio|>'",
                   "!steps.x.result.ok && steps.x.result.error.message == 'Unsupported modality: point_cloud'"]),
    ]
    # ---------------------------------------------------------------- BERT-family embedding models (oracle4 BAAI, coverage)
    BGE = {"architectures": ["BertModel"], "model_type": "bert", "num_hidden_layers": 12, "num_attention_heads": 12, "num_key_value_heads": 12,
           "hidden_size": 768, "intermediate_size": 3072, "vocab_size": 30522, "max_position_embeddings": 512, "torch_dtype": "float32", "weights_bytes": 438000000}
    L += [
        sc("models-r6-bert-embedding-load-and-pool", fixtures=TP1, config={"runner": "pooling", "tensor-parallel-size": 1},
           state={"hf-hub": {"models": {"BAAI/bge-base-en": BGE}}},
           steps=[ist("model-loader.get-model", "load", {"model": "BAAI/bge-base-en", "hf_config": BGE}),
                  ist("bert-embedding-model.forward", "fwd", {"num_tokens": 64, "num_reqs": 2}),
                  ist("dispatch-pooler.forward", "pool", {"requests": [{"task": "embed", "prompt_len": 40}, {"task": "embed", "prompt_len": 24}], "seq_pooling_type": "CLS", "hidden_size": 768})],
           expect=["steps.load.result.ok && steps.load.result.value.component == 'bert-embedding-model' && steps.load.result.value.model_cls == 'BertEmbeddingModel'",
                   "size(steps.load.result.value.layers) == 12 && steps.load.result.value.layers.all(l, l.attn_type == 'encoder_only' && l.sliding_window == [-1, -1])",
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'dispatch-pooler.for-embedding' && e.output.seq_pooling_type == 'CLS')",
                   "steps.fwd.result.ok && steps.fwd.result.value.num_layers == 12",
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'sequence-pooling-method.forward' && e.output.token_indices == [0, 40])"]),
        # judge4 P4-8: Attention.__init__ selects the backend, so a refused one fails the model build
        sc("models-r6-bert-encoder-only-refuses-flashinfer", fixtures=TP1, config={"runner": "pooling", "attention-backend": "FLASHINFER"},
           state={"hf-hub": {"models": {"BAAI/bge-base-en": BGE}}},
           steps=[ist("model-loader.get-model", "load", {"model": "BAAI/bge-base-en", "hf_config": BGE})],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'value-error'",
                   "trace.exists(e, e.type == 'call.start' && e.interface == 'selector.get-attn-backend' && e.input.attn_type == 'encoder_only')"]),
        sc("models-r6-bert-embedding-needs-pooling-runner", fixtures=TP1, config={"runner": "generate"},
           state={"hf-hub": {"models": {"BAAI/bge-base-en": BGE}}},
           steps=[ist("model-loader.get-model", "load", {"model": "BAAI/bge-base-en", "hf_config": BGE})],
           expect=["trace.exists(e, e.type == 'call.end' && e.interface == 'bert-embedding-model.init' && e.error != null)",
                   "!steps.load.result.ok && steps.load.result.error.code == 'assertion-error'"]),
    ]
    # ---------------------------------------------------------------- _ModelInfo pooling defaults (oracle4)
    L += [
        sc("models-r6-model-info-pooling-defaults", fixtures=TP1,
           steps=[ist("model-registry.inspect-model-cls", "bert", {"architectures": ["BertModel"]}),
                  ist("model-registry.inspect-model-cls", "xlmr", {"architectures": ["XLMRobertaModel"]}),
                  ist("model-registry.inspect-model-cls", "eg2", {"architectures": ["EmbeddingGemma2Model"]}),
                  ist("model-registry.inspect-model-cls", "qcls", {"architectures": ["GPT2ForSequenceClassification"]}),
                  ist("model-registry.inspect-model-cls", "btok", {"architectures": ["BertForTokenClassification"]}),
                  ist("model-registry.inspect-model-cls", "llama", {"architectures": ["LlamaForCausalLM"]})],
           expect=["'BertModel' in state['model-registry@rank0'].modelinfo_cache",
                   "steps.bert.result.value.architecture == 'BertEmbeddingModel' && steps.bert.result.value.default_seq_pooling_type == 'CLS' && steps.bert.result.value.attn_type == 'decoder'",
                   "steps.xlmr.result.value.architecture == 'RobertaEmbeddingModel' && steps.xlmr.result.value.default_seq_pooling_type == 'CLS'",
                   "steps.eg2.result.value.default_seq_pooling_type == 'MEAN' && steps.eg2.result.value.default_tok_pooling_type == 'ALL'",
                   "steps.qcls.result.value.default_seq_pooling_type == 'LAST' && steps.qcls.result.value.is_pooling_model",
                   "steps.btok.result.value.attn_type == 'encoder_only' && steps.btok.result.value.default_seq_pooling_type == 'LAST'",
                   "steps.llama.result.value.default_seq_pooling_type == 'LAST' && steps.llama.result.value.attn_type == 'decoder' && !steps.llama.result.value.is_pooling_model"]),
    ]
    # ---------------------------------------------------------------- the pooler
    L += [
        sc("models-r6-pooler-embed-matryoshka-normalize", fixtures=TP1,
           steps=[ist("dispatch-pooler.forward", "p", {"requests": [{"task": "embed", "prompt_len": 12, "dimensions": 256, "use_activation": True},
                                                                       {"task": "embed", "prompt_len": 7, "use_activation": False},
                                                                       {"task": "token_embed", "prompt_len": 5}],
                                                          "seq_pooling_type": "CLS", "hidden_size": 768})],
           expect=["steps.p.result.ok && size(steps.p.result.value.outputs) == 3",
                   "steps.p.result.value.outputs[0].dim == 256 && steps.p.result.value.outputs[0].normalized && steps.p.result.value.outputs[1].dim == 768 && !steps.p.result.value.outputs[1].normalized",
                   "steps.p.result.value.outputs[2].num_vectors == 5",
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'sequence-pooling-method.forward' && e.output.token_indices == [0, 12])"]),
        sc("models-r6-pooler-partial-prefill-refused", fixtures=TP1,
           steps=[ist("sequence-pooling-method.forward", "cls", {"pooling_type": "CLS", "prompt_lens": [600, 10], "num_scheduled_tokens": [512, 10]}),
                  ist("sequence-pooling-method.forward", "mean", {"pooling_type": "MEAN", "prompt_lens": [600], "num_scheduled_tokens": [512]}),
                  ist("sequence-pooling-method.forward", "last", {"pooling_type": "LAST", "prompt_lens": [600, 10], "num_scheduled_tokens": [512, 10]})],
           expect=["!steps.cls.result.ok && steps.cls.result.error.message == 'partial prefill is not supported with CLS pooling'",
                   "!steps.mean.result.ok && steps.mean.result.error.message == 'partial prefill is not supported with MEAN pooling'",
                   "steps.last.result.ok && steps.last.result.value.token_indices == [511, 521]"]),
        sc("models-r6-pooler-unsupported-task-and-type", fixtures=TP1,
           steps=[ist("dispatch-pooler.forward", "cls", {"requests": [{"task": "classify", "prompt_len": 4}]}),
                  ist("dispatch-pooler.for-embedding", "bad", {"seq_pooling_type": "MAX"}),
                  ist("embedding-pooler-head.forward", "len", {"num_pooled": 2, "use_activation": [True]})],
           expect=["!steps.cls.result.ok && steps.cls.result.error.message == \"Unsupported task: 'classify' Supported tasks: {'token_embed', 'embed'}\"",
                   "!steps.bad.result.ok && steps.bad.result.error.message == \"Unknown sequence pooling type: 'MAX'\"",
                   "!steps.len.result.ok && steps.len.result.error.message == 'pooled_data length (2) does not match pooling_params length (1)'"]),
    ]
    # ---------------------------------------------------------------- shm processor cache (judge4 L4-8 c)
    L += [
        sc("models-r6-shm-processor-cache-factories", fixtures=VL_W, config={"mm-processor-cache-type": "shm"},
           steps=[ist("multi-modal-cache-factories.processor-cache-from-config", "p0"),
                  ist("multi-modal-cache-factories.engine-receiver-cache-from-config", "ec"),
                  ist("multi-modal-cache-factories.worker-receiver-cache-from-config", "wk"),
                  ist("multi-modal-cache-factories.worker-receiver-cache-from-config", "nolock", {"has_shared_worker_lock": False})],
           expect=["steps.p0.result.ok && steps.p0.result.value.component == 'shm-object-store-sender-cache' && steps.p0.result.value.cache_type == 'shm'",
                   "steps.ec.result.value.component == null",
                   "steps.wk.result.value.component == 'shm-object-store-receiver-cache'",
                   "!steps.nolock.result.ok && steps.nolock.result.error.message == \"Missing `shared_worker_lock` argument from executor. This argument is needed for mm_processor_cache_type='shm'.\""]),
        sc("models-r6-shm-processor-cache-api-servers", fixtures=VL_W, config={"mm-processor-cache-type": "shm", "api-server-count": 2},
           steps=[ist("multi-modal-cache-factories.processor-cache-from-config", "p0"),
                  ist("multi-modal-cache-factories.worker-receiver-cache-from-config", "wk")],
           expect=["steps.p0.result.value.cache_type == 'processor_only' && steps.p0.result.value.component == 'multi-modal-processor-only-cache'",
                   "steps.wk.result.value.component == null"]),
        sc("models-r6-shm-sender-cache-put-hit-evict", fixtures=VL_W, config={"mm-processor-cache-gb": 0.003, "mm-shm-cache-max-object-size-mb": 2},
           steps=[ist("shm-object-store-sender-cache.get-and-update", "a", {"mm_hash": "img-a", "size_bytes": 1048576}),
                  ist("shm-object-store-sender-cache.get-and-update", "b", {"mm_hash": "img-b", "size_bytes": 1048576}),
                  ist("shm-object-store-sender-cache.get-and-update", "a2", {"mm_hash": "img-a", "size_bytes": 1048576}),
                  ist("shm-object-store-sender-cache.get-and-update", "c", {"mm_hash": "img-c", "size_bytes": 2097152}),
                  ist("shm-object-store-sender-cache.get-and-update", "big", {"mm_hash": "img-big", "size_bytes": 4194304}),
                  ist("shm-object-store-sender-cache.is-cached", "chk", {"mm_hashes": ["img-a", "img-b", "img-c", "img-big"]}),
                  ist("shm-object-store-receiver-cache.get-and-update", "rx", {"mm_hash": "img-c", "kind": "address"})],
           # 3 MiB buffer: a, b stored; a hits; c (2 MiB) frees a then b in FIFO order; a 4 MiB item is over the 2 MiB object cap
           expect=["state['shm-object-store-sender-cache'].hits == 1 && state['shm-object-store-sender-cache'].order == ['img-b', 'img-c']",
                   "steps.a.result.value.kind == 'address' && !steps.a.result.value.hit && steps.a.result.value.monotonic_id == 0",
                   "steps.a2.result.value.hit && steps.a2.result.value.address == steps.a.result.value.address",
                   "steps.c.result.value.kind == 'address' && steps.c.result.value.monotonic_id == 2",
                   "steps.big.result.value.kind == 'item' && steps.big.result.value.warning == 'mm_input img-big too large to cache; raise --mm-shm-cache-max-object-size-mb. (Serialized object size (4194304 bytes) exceeds max object size (2097152 bytes))'",
                   "steps.chk.result.value.cached == [false, true, true, false]",
                   "steps.rx.result.value.from_shm"]),
    ]
    # ---------------------------------------------------------------- the processor in the API process (judge4 S4-7, Q4-4 c)
    L += [
        sc("models-r6-processor-image-sizes-and-placeholders", fixtures=VL_W,
           steps=[ist("base-multi-modal-processor.apply", "p", {"model": "Qwen/Qwen2-VL-7B-Instruct", "architectures": ["Qwen2VLForConditionalGeneration"],
                                                                "prompt_token_ids": [151644, 151655, 872, 151655, 151653], "mm_counts": {"image": 2},
                                                                "mm_items": [{"modality": "image", "width": 1120, "height": 560}, {"modality": "image", "width": 896, "height": 504}]})],
           expect=["steps.p.result.ok && steps.p.result.value.mm_placeholders.image == [{'offset': 1, 'length': 800}, {'offset': 802, 'length': 576}]",
                   "steps.p.result.value.num_prompt_tokens == 3 + 800 + 576 && steps.p.result.value.placeholders.image == 1376",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'qwen2-vl-processing-info.get-num-image-tokens').size() == 2"]),
        sc("models-r6-processor-uuid-identity", fixtures=VL_W,
           steps=[ist("base-multi-modal-processor.apply", "u", {"model": "Qwen/Qwen2-VL-7B-Instruct", "architectures": ["Qwen2VLForConditionalGeneration"],
                                                                "prompt_token_ids": [1, 2], "mm_counts": {"image": 1}, "mm_uuids": {"image": ["img-1"]}}),
                  ist("base-multi-modal-processor.apply", "k", {"model": "Qwen/Qwen2-VL-7B-Instruct", "architectures": ["Qwen2VLForConditionalGeneration"],
                                                                "prompt_token_ids": [1, 2], "mm_counts": {"image": 1}, "mm_uuids": {"image": ["img-1"]},
                                                                "mm_processor_kwargs": {"max_pixels": 802816}})],
           expect=["trace.filter(e, e.type == 'call.start' && e.interface == 'lru-key-replicated-sender-cache.get-and-update')[0].input.mm_hash == 'img-1'",
                   "steps.u.result.value.mm_hashes.image == ['img-1']",
                   "steps.k.result.value.mm_hashes.image[0] != 'img-1'"]),
        sc("models-r6-processor-shm-cache-path", fixtures=VL_W, config={"mm-processor-cache-type": "shm"},
           steps=[ist("base-multi-modal-processor.apply", "a", {"model": "Qwen/Qwen2-VL-7B-Instruct", "architectures": ["Qwen2VLForConditionalGeneration"],
                                                                "prompt_token_ids": [151655], "mm_counts": {"image": 1}, "mm_uuids": {"image": ["img-s"]}}),
                  ist("base-multi-modal-processor.apply", "b", {"model": "Qwen/Qwen2-VL-7B-Instruct", "architectures": ["Qwen2VLForConditionalGeneration"],
                                                                "prompt_token_ids": [151655], "mm_counts": {"image": 1}, "mm_uuids": {"image": ["img-s"]}})],
           expect=["steps.a.result.ok && steps.b.result.ok",
                   "trace.filter(e, e.type == 'call.end' && e.interface == 'shm-object-store-sender-cache.get-and-update').map(e, e.output.hit) == [false, true]",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'base-multi-modal-processor.apply-hf-processor-main').map(e, e.input.num_items) == [1, 0]"]),
    ]
    # ---------------------------------------------------------------- ViT data mode and backend (judge4 P4-7 b, d), online quant (P4-4 b)
    L += [
        sc("models-r6-vit-load-balance-greedy", fixtures=VL_W,
           steps=[ist("vision-utils.get-load-balance-assignment", "doc", {"sizes": [1000, 100, 200, 50], "num_gpus": 2}),
                  ist("vision-utils.get-load-balance-assignment", "none", {"sizes": [], "num_gpus": 2})],
           expect=["steps.doc.result.value.shuffle_indices == [0, 2, 1, 3] && steps.doc.result.value.gpu_sample_counts == [1, 3] && steps.doc.result.value.gpu_loads == [1000, 350]",
                   "steps.none.result.value.gpu_sample_counts == [0, 0]"]),
        sc("models-r6-vit-data-mode-sharded-tower", fixtures=VL_W, config={"tensor-parallel-size": 2, "mm-encoder-tp-mode": "data"},
           # rank0's share of the balanced split: 4000 patches on its own tower (rank1 takes 1000 + 1000), then the all-gather
           steps=[step(iface="qwen2-vl-for-conditional-generation.embed-multimodal", as_="e0", on="rank0", nowait=True,
                       inp={"mm_kwargs": [{"modality": "image", "kind": "pixel_values", "grid_thw": [1, 40, 100]}, {"modality": "image", "kind": "pixel_values", "grid_thw": [1, 20, 50]}, {"modality": "image", "kind": "pixel_values", "grid_thw": [1, 25, 40]}]})],
           state={"qwen2-vl-for-conditional-generation@rank0": {"loaded": True, "cfg": {"hidden_size": 3584, "vision": {"patch_size": 14, "temporal_patch_size": 2, "spatial_merge_size": 2, "embed_dim": 1280, "depth": 32, "num_heads": 16, "mlp_ratio": 4, "out_hidden_size": 3584}}}},
           expect=["trace.filter(e, e.type == 'call.start' && e.interface == 'qwen2-vision-transformer.forward' && e.input.tp == 1).map(e, e.input.grid_thw) == [[[1, 40, 100]]]",
                   "trace.exists(e, e.type == 'call.start' && e.interface == 'tensor-model-parallel.all-gather' && e.input.num_tokens == 1000)"]),
        sc("models-r6-vit-backend-selection", fixtures=VL_W,
           steps=[ist("vision-utils.get-vit-attn-backend", "fa", {"head_size": 80}),
                  ist("vision-utils.get-vit-attn-backend", "odd", {"head_size": 90}),
                  ist("qwen2-vl-for-conditional-generation.embed-multimodal", "enc", {"mm_kwargs": [{"modality": "image", "kind": "pixel_values", "grid_thw": [1, 20, 50]}]})],
           expect=["steps.fa.result.value.backend == 'FLASH_ATTN' && steps.odd.result.value.backend == 'TRITON_ATTN'",
                   "steps.enc.result.ok && trace.exists(e, e.type == 'call.start' && e.interface == 'vit-attn-wrappers.vit-flash-attn-wrapper')"]),
        sc("models-r6-online-quant-layer-summary", fixtures=TP1,
           steps=[ist("online-quantization-config.quantized-layer-summary", "s", {"num_layers": 32, "quant_key": "fp8_per_tensor_static"})],
           expect=["steps.s.result.value.summary == 'Quantizing 128 layers of types: mlp.down_proj: 32 (from linear: fp8_per_tensor_static); mlp.gate_up_proj: 32 (from linear: fp8_per_tensor_static); self_attn.o_proj: 32 (from linear: fp8_per_tensor_static); self_attn.qkv_proj: 32 (from linear: fp8_per_tensor_static)'"]),
    ]
    # ---------------------------------------------------------------- FP8 kernel selection (judge4 P4-3 b, c)
    NM = "neuralmagic/Meta-Llama-3-8B-Instruct-FP8-KV"
    NMH = {"architectures": ["LlamaForCausalLM"], "hidden_size": 4096, "max_position_embeddings": 8192, "num_attention_heads": 32, "num_hidden_layers": 32, "num_key_value_heads": 8, "torch_dtype": "bfloat16", "vocab_size": 128256, "weights_bytes": 9081200640,
           "quantization_config": {"quant_method": "fp8", "activation_scheme": "static", "kv_cache_scheme": "static", "ignored_layers": ["lm_head"]}}
    A100 = {"cuda-platform": {"device_capability": {"major": 8, "minor": 0}}, "torch-bindings": {"device_capability": {"major": 8, "minor": 0}}}
    L += [
        sc("models-r6-fp8-kernel-by-capability", fixtures=TP1,
           steps=[ist("fp8-linear-method.select-kernel", "h100", {}), ist("fp8-linear-method.select-kernel", "h100b", {"block": True})],
           expect=["steps.h100.result.value.class_name == 'CutlassFP8ScaledMMLinearKernel'",
                   "steps.h100b.result.value.class_name == 'CutlassFp8BlockScaledMMKernel'"]),
        sc("models-r6-fp8-kernel-a100-marlin", fixtures=["full-fp8-llama-3-8b"], state=A100,
           steps=[ist("fp8-linear-method.select-kernel", "pt", {}), ist("fp8-linear-method.select-kernel", "bl", {"block": True}),
                  ist("model-loader.get-model", "load", {"model": NM, "hf_config": NMH}),
                  ist("llama-for-causal-lm.forward", "fwd", {"num_tokens": 16, "num_reqs": 16})],
           expect=["steps.pt.result.value.kernel == 'marlin' && steps.bl.result.value.kernel == 'marlin'",
                   "steps.load.result.ok && trace.exists(e, e.type == 'call.start' && e.interface == 'custom-ops.gptq-marlin-repack' && e.input.num_bits == 8)",
                   "steps.fwd.result.ok && calls['torch-bindings.marlin-gemm'] > 0 && calls['cutlass-fp8-scaled-mm-linear-kernel.apply-scaled-mm'] == 0"]),
        sc("models-r6-normalize-arch-sequence-classification", fixtures=TP1,
           steps=[ist("model-registry.resolve-model-cls", "seq", {"architectures": ["Qwen2ForSequenceClassification"]}),
                  ist("model-registry.resolve-model-cls", "none", {"architectures": ["NoSuchThingForSequenceClassification"]})],
           expect=["steps.seq.result.ok && steps.seq.result.value.arch == 'Qwen2ForCausalLM' && steps.seq.result.value.requested == 'Qwen2ForSequenceClassification'",
                   "!steps.none.result.ok && steps.none.result.error.message.contains('are not supported for now')"]),
        sc("models-r6-multi-modal-budget-qwen2-vl", fixtures=["full-vl-qwen2-vl-7b"],
           steps=[ist("multi-modal-budget.init", "b", {"model": "Qwen/Qwen2-VL-7B-Instruct", "architectures": ["Qwen2VLForConditionalGeneration"]}),
                  ist("multi-modal-budget.get-dummy-encoder-profile-inputs", "d", {"budget": {"encoder_compute_budget": 32768, "encoder_cache_size": 32768, "mm_max_toks_per_item": {"image": 16384, "video": 32768}, "mm_max_items_per_batch": {"image": 2, "video": 1}}})],
           expect=["steps.b.result.value.mm_max_toks_per_item == {'image': 16384, 'video': 32768} && steps.b.result.value.encoder_cache_size == 32768 && trace.exists(e, e.type == 'call.end' && e.interface == 'encoder-cache-manager.compute-mm-encoder-budget' && e.output.encoder_compute_budget == 32768)",
                   "steps.d.result.value.modality == 'video' && size(steps.d.result.value.items) == 1 && steps.d.result.value.items[0].grid_thw == [2, 256, 256]"]),
        sc("models-r6-fp8-kernel-no-kernel-reasons", fixtures=TP1,
           state={"cuda-platform": {"device_capability": {"major": 7, "minor": 0}}, "torch-bindings": {"device_capability": {"major": 7, "minor": 0}}},
           steps=[ist("fp8-linear-method.select-kernel", "pt", {})],
           expect=["!steps.pt.result.ok && steps.pt.result.error.message.contains('Reasons: \\nFlashInferFP8ScaledMMLinearKernel ') && steps.pt.result.error.message.contains('\\nCutlassFP8ScaledMMLinearKernel CUTLASS FP8 kernels not available.') && steps.pt.result.error.message.contains('\\nMarlinFP8ScaledMMLinearKernel FP8 Marlin requires compute capability 7.5 or higher.')"]),
        sc("models-r6-fp8-kernel-below-sm75-refused", fixtures=TP1,
           state={"cuda-platform": {"device_capability": {"major": 7, "minor": 0}}, "torch-bindings": {"device_capability": {"major": 7, "minor": 0}}},
           steps=[ist("fp8-linear-method.select-kernel", "pt", {}), ist("fp8-linear-method.select-kernel", "bl", {"block": True}),
                  ist("fp8-linear-method.apply", "tb", {"quant": "fp8_block", "num_tokens": 16, "in_features": 4096, "out_features": 4096})],
           expect=["!steps.pt.result.ok && steps.pt.result.error.code == 'value-error' && steps.pt.result.error.message.startsWith('Failed to find a kernel that can implement the ScaledMM linear layer. Reasons: ')", "steps.bl.result.value.kernel == 'triton_block'",
                   "steps.tb.result.ok && calls['scaled-mm-triton.w8a8-triton-block-scaled-mm-func'] == 1"]),
    ]
    # ---------------------------------------------------------------- media fetch retries (judge4 S4-6 d)
    L += [
        sc("models-r6-media-fetch-retries-with-backoff", fixtures=VL_W,
           state={"remote-media-host": {"urls": {"https://slow.example.com/a.jpg": {"size": 1000, "content_type": "image/jpeg"}}}},
           faults=[{"target": "remote-media-host.get", "type": "hang", "forever": True}],
           steps=[ist("media-connector.fetch-image", "f", {"image_url": "https://slow.example.com/a.jpg"})],
           # 3 attempts at 5, 20 and 80 s with 1 and 4 s sleeps: about 110 s, then the timeout propagates
           expect=["!steps.f.result.ok && steps.f.result.error.code == 'timeout'",
                   "calls['remote-media-host.get'] == 3",
                   "steps.f.duration_ms >= 110000 && steps.f.duration_ms < 111000"]),
        sc("models-r6-media-fetch-5xx-retried-then-ok", fixtures=VL_W,
           state={"remote-media-host": {"urls": {"https://flaky.example.com/a.jpg": {"size": 1000, "content_type": "image/png"}}}},
           faults=[{"target": "remote-media-host.get", "type": "error", "code": "service-unavailable", "status": 503, "retryable": True, "calls": [1]}],
           steps=[ist("media-connector.fetch-image", "f", {"image_url": "https://flaky.example.com/a.jpg"})],
           expect=["steps.f.result.ok && steps.f.result.value.media_type == 'image/png'",
                   "calls['remote-media-host.get'] == 2"]),
        sc("models-r6-media-fetch-404-not-retried", fixtures=VL_W,
           steps=[ist("media-connector.fetch-image", "f", {"image_url": "https://example.com/missing.jpg"})],
           expect=["!steps.f.result.ok && steps.f.result.error.status == 422 && steps.f.result.error.message == 'Failed to fetch media from URL: HTTP 404 error'",
                   "calls['remote-media-host.get'] == 1"]),
    ]
    # ---------------------------------------------------------------- MoE placement and EPLB checks (judge4 P4-5 e, P4-6 c)
    L += [
        sc("models-r6-mixtral-eplb-uneven-experts-refused", fixtures=MOE_W,
           config={"enable-eplb": True, "num-redundant-experts": 1},
           steps=[ist("mixtral-for-causal-lm.init", "m", {"quant": "unquantized", "hf_config": MIXTRAL_HF}, "rank0"),
                  ist("mixtral-for-causal-lm.forward", "fwd", {"num_tokens": 4, "num_reqs": 1}, "rank0")],
           expect=["trace.exists(e, e.type == 'call.end' && e.interface == 'fused-moe-layer.determine-expert-counts' && e.output.global_num_experts == 9)",
                   "!steps.m.result.ok && steps.m.result.error.code == 'value-error' && steps.m.result.error.message == 'EPLB currently only supports even distribution of experts across ranks. Got 9 experts and 2 EP ranks.'"]),
        sc("models-r6-mixtral-redundant-without-eplb-refused", fixtures=MOE_W,
           config={"enable-eplb": False, "num-redundant-experts": 2},
           steps=[ist("mixtral-for-causal-lm.init", "m", {"quant": "unquantized", "hf_config": MIXTRAL_HF}, "rank0")],
           expect=["trace.exists(e, e.type == 'call.end' && e.interface == 'fused-moe-layer.determine-expert-counts' && e.output.global_num_experts == 10)",
                   "!steps.m.result.ok && steps.m.result.error.code == 'assertion-error' && steps.m.result.error.message == 'Redundant experts are only supported with EPLB.'"]),
        sc("models-r6-mixtral-round-robin-falls-back-linear", fixtures=MOE_W,
           config={"expert-placement-strategy": "round_robin"},
           steps=[ist("mixtral-for-causal-lm.init", "m", {"quant": "unquantized", "hf_config": MIXTRAL_HF}, "rank0"),
                  ist("expert-map-manager.determine-expert-placement-strategy", "grp", {"expert_placement_strategy": "round_robin", "num_expert_group": 8}),
                  ist("expert-map-manager.determine-expert-placement-strategy", "a2a", {"expert_placement_strategy": "round_robin", "num_expert_group": 8, "use_all2all_kernels": True, "all2all_backend": "deepep_high_throughput"})],
           expect=["state['mixtral-for-causal-lm@rank0'].cfg.expert_placement_strategy == 'linear'",
                   "steps.m.result.ok && steps.m.result.value.expert_placement_strategy == 'linear' && steps.m.result.value.placement_warning == 'Round-robin expert placement is only supported for models with multiple expert groups and no redundant experts. Falling back to linear expert placement.'",
                   "steps.grp.result.value.strategy == 'round_robin' && steps.grp.result.value.warning == null",
                   "steps.a2a.result.value.strategy == 'linear' && steps.a2a.result.value.warning == \"Round-robin expert placement currently only supports the DeepEP low-latency or NIXL EP backend, but 'deepep_high_throughput' was configured. Falling back to linear expert placement.\""]),
        # DP 2 x TP 1 + EP: each rank holds the whole attention and 4 of 8 experts, so Mixtral fits on an 80 GB GPU
        sc("models-r6-mixtral-dp2-ep-weights-per-rank", fixtures=MOE_W,
           config={"data-parallel-size": 2, "tensor-parallel-size": 1},
           steps=[ist("base-model-loader.load-model", "l0", {"loader": "default-model-loader", "model": MIXTRAL, "hf_config": {"architectures": ["MixtralForCausalLM"]}}, "rank0")],
           expect=["steps.l0.result.ok && steps.l0.result.value.weights_bytes_per_rank == 48308428800",
                   "trace.exists(e, e.type == 'call.start' && e.interface == 'gpu-memory.allocate' && e.input.kind == 'weights' && e.input.bytes == 48308428800)"]),
    ]
    return L


def extra():
    return {"configs": configs(), "flows": flows(), "scenarios": scenario_list()}

"""Configs, schemas, boundary stubs, flows and scenarios for the models-layers fragment."""

LLAMA8 = {
    "architectures": ["LlamaForCausalLM"], "num_hidden_layers": 32, "num_attention_heads": 32,
    "num_key_value_heads": 8, "hidden_size": 4096, "vocab_size": 128256,
    "max_position_embeddings": 131072, "torch_dtype": "bfloat16", "weights_bytes": 16060522496,
}
LLAMA70 = dict(LLAMA8, num_hidden_layers=80, num_attention_heads=64, hidden_size=8192, weights_bytes=141107412992)
MIXTRAL = {
    "architectures": ["MixtralForCausalLM"], "num_hidden_layers": 32, "num_attention_heads": 32,
    "num_key_value_heads": 8, "hidden_size": 4096, "intermediate_size": 14336, "vocab_size": 32000,
    "max_position_embeddings": 32768, "torch_dtype": "bfloat16", "weights_bytes": 93405585408,
    "num_local_experts": 8, "num_experts_per_tok": 2,
}
M8 = "meta-llama/Llama-3.1-8B-Instruct"
M70 = "meta-llama/Llama-3.1-70B-Instruct"
MIX = "mistralai/Mixtral-8x7B-Instruct-v0.1"
MIX_STATE = {"hf-hub": {"models": {MIX: MIXTRAL}}}
FP8 = "neuralmagic/Llama-3.1-8B-Instruct-FP8-block"
FP8_HF = dict(LLAMA8, weights_bytes=8030261248,
              quantization_config={"quant_method": "fp8", "activation_scheme": "dynamic", "weight_block_size": [128, 128]})
ADAPTER = {"local-disk": {"files": {"/adapters/sql-lora/adapter_config.json": {"json": {"r": 8, "lora_alpha": 16, "bias": "none"}},
                                    "/adapters/chat-lora/adapter_config.json": {"json": {"r": 16, "lora_alpha": 32, "bias": "none"}},
                                    "/adapters/big-lora/adapter_config.json": {"json": {"r": 64, "lora_alpha": 128, "bias": "none"}},
                                    "/adapters/bias-lora/adapter_config.json": {"json": {"r": 8, "lora_alpha": 16, "bias": "all"}}}}}


def lora(i, name):
    return {"lora_name": name, "lora_int_id": i, "lora_path": f"/adapters/{name}"}


def cfg(id_, typ, value, default, summary, sources, key, owner=None):
    c = {"id": id_, "type": typ, "value": value, "default": default, "summary": summary, "sources": sources,
         "attributes": {"key": key}}
    if owner:
        c["attributes"].update({"boundary": True, "owner": owner})
    return c


def configs():
    return [
        cfg("load-format", "string", "auto", "auto",
            "load_format: the weight loader (auto picks hf or mistral by file names). Deployed = default.",
            ["vllm/config/load.py:30", "vllm/engine/arg_utils.py:497"], "load_format"),
        cfg("quantization", "string", None, None,
            "quantization: unset, so ModelConfig takes the checkpoint's quant_method (none for the fixture models). Deployed = default.",
            ["vllm/config/model.py:260", "vllm/engine/arg_utils.py:622"], "quantization", owner="config-platform"),
        cfg("model-impl", "string", "auto", "auto",
            "model_impl: auto prefers the vLLM class and falls back to the Transformers backend. Deployed = default.",
            ["vllm/config/model.py:394", "vllm/engine/arg_utils.py:790"], "model_impl", owner="config-platform"),
        cfg("model-loader-extra-config", "object", {}, {},
            "model_loader_extra_config: loader options (ipc_cache reads fallback, default true). Deployed = default.",
            ["vllm/config/load.py:30-62", "vllm/model_executor/model_loader/weight_cache/ipc_loader.py:100-104"],
            "model_loader_extra_config"),
        cfg("max-loras", "integer", 1, 1, "max_loras: GPU LoRA slots per batch. Deployed = default (LoRA itself is off unless --enable-lora).",
            ["vllm/config/lora.py:35", "vllm/engine/arg_utils.py:677"], "max_loras"),
        cfg("max-cpu-loras", "integer", None, None,
            "max_cpu_loras: CPU adapter cache capacity; unset (None), which LoRAConfig resolves to max_loras, so the cache follows --max-loras. Deployed = default.",
            ["vllm/config/lora.py:42", "vllm/config/lora.py:120-121"], "max_cpu_loras"),
        cfg("max-lora-rank", "integer", 16, 16, "max_lora_rank: adapters with a higher rank are refused. Deployed = default.",
            ["vllm/config/lora.py:33", "vllm/engine/arg_utils.py:678"], "max_lora_rank"),
        {"id": "gpu-hbm-bandwidth-gbps", "type": "integer", "value": 3350,
         "summary": "ASSUMPTION: HBM bandwidth of the fixture's 80 GB GPU, taken as an H100 SXM (3.35 TB/s peak). Memory-bound kernels divide bytes moved by it.",
         "sources": ["vllm/v1/metrics/perf.py:651"],
         "attributes": {"key": "gpu_hbm_bandwidth_gbps", "assumption": True, "boundary": True, "owner": "kernels-ops"}},
        cfg("gpu-dense-bf16-tflops", "number", 989, 989,
            "ASSUMPTION for latency only: dense BF16 tensor-core peak of an H100 SXM (989 TFLOPS), matching kernels-ops' H100 bandwidth assumption; FP8 kernels use twice this. The code holds no number.",
            ["vllm/v1/metrics/perf.py:648-651"], "assumption:bf16_tflops"),
        cfg("enable-expert-parallel", "boolean", False, False, "enable_expert_parallel: MoE experts are split over the TP x DP ranks instead of TP-sharded (reference copy).",
            ["vllm/config/parallel.py:189", "vllm/engine/arg_utils.py:548"], "enable_expert_parallel", owner="config-platform"),
        cfg("enable-eplb", "boolean", False, False, "enable_eplb: expert-parallel load balancing (requires EP; reference copy).",
            ["vllm/config/parallel.py:205", "vllm/engine/arg_utils.py:570"], "enable_eplb", owner="config-platform"),
        cfg("num-redundant-experts", "integer", 0, 0, "eplb_config.num_redundant_experts: extra physical expert replicas; read by the MoE layers when sizing physical experts. Deployed = default 0.",
            ["vllm/config/parallel.py:76", "vllm/config/parallel.py:581-588"], "num_redundant_experts"),
        cfg("limit-mm-per-prompt", "object", {}, {}, "limit_mm_per_prompt: per-modality item limit; an unset modality allows 999. Read by the multimodal processing info. Deployed = default.",
            ["vllm/config/multimodal.py:307", "vllm/config/multimodal.py:695-708"], "limit_mm_per_prompt"),
        cfg("enable-mm-embeds", "boolean", False, False, "enable_mm_embeds: accept precomputed `<modality>_embeds` inputs. Deployed = default.",
            ["vllm/config/multimodal.py:326", "vllm/multimodal/processing/context.py:644-649"], "enable_mm_embeds"),
        cfg("vllm-batch-invariant", "boolean", False, False, "VLLM_BATCH_INVARIANT: batch-invariant kernels (reference copy).",
            ["vllm/envs.py:636"], "VLLM_BATCH_INVARIANT", owner="config-platform"),
        cfg("vllm-lora-enable-dual-stream", "boolean", False, False,
            "VLLM_LORA_ENABLE_DUAL_STREAM: overlap LoRA with the base GEMM on a second stream (reference copy).",
            ["vllm/envs.py:2259-2260"], "VLLM_LORA_ENABLE_DUAL_STREAM", owner="config-platform"),
    ]


def schemas():
    i, s, b, o = {"type": "integer"}, {"type": "string"}, {"type": "boolean"}, {"type": "object"}
    hf = {"type": "object", "required": ["architectures", "num_hidden_layers", "num_attention_heads",
                                         "num_key_value_heads", "hidden_size", "vocab_size", "weights_bytes"],
          "properties": {
              "architectures": {"type": "array", "items": {"type": "string", "examples": ["LlamaForCausalLM"]},
                                "minItems": 1, "maxItems": 1},
              "num_hidden_layers": {"type": "integer", "examples": [32]},
              "num_attention_heads": {"type": "integer", "examples": [32]},
              "num_key_value_heads": {"type": "integer", "examples": [8]},
              "hidden_size": {"type": "integer", "examples": [4096]},
              "vocab_size": {"type": "integer", "examples": [128256]},
              "max_position_embeddings": {"type": "integer", "examples": [131072]},
              "torch_dtype": {"type": "string", "examples": ["bfloat16"]},
              "weights_bytes": {"type": "integer", "examples": [16060522496]},
              "hidden_act": {"type": "string", "default": "silu"},
              "intermediate_size": {"type": ["integer", "null"], "default": None},
              "num_local_experts": {"type": ["integer", "null"], "default": None},
              "num_experts_per_tok": {"type": ["integer", "null"], "default": None},
              "quantization_config": {"type": ["object", "null"], "default": None},
              "rope_parameters": {"type": ["object", "null"], "default": None}}}
    return [
        {"id": "ModelsHfConfig", "summary": "The HF config.json fields the loader and model __init__ read (the fixture's hf-hub rows).", "schema": hf},
        {"id": "ModelsGetModelRequest", "schema": {"type": "object", "required": ["model", "hf_config"], "properties": {
            "model": {"type": "string", "examples": [M8]}, "hf_config": {"$ref": "ModelsHfConfig"}}}},
        {"id": "ModelsLoadedModel", "schema": {"type": "object", "properties": {
            "model": s, "arch": s, "model_cls": s, "component": s, "quant": s, "loader": s, "weights_bytes_per_rank": i}}},
        {"id": "ModelsResolvedClass", "schema": {"type": "object", "properties": {
            "arch": s, "requested": s, "module": s, "class_name": s, "table": s, "component": s,
            "is_pooling": b, "is_text_generation": b}}},
        {"id": "ModelsModelInfo", "schema": {"type": "object", "properties": {
            "architecture": s, "is_text_generation_model": b, "is_pooling_model": b, "module": s}}},
        {"id": "ModelsForwardRequest", "summary": "One model forward: the step's flattened token count (num_tokens) and request count.",
         "schema": {"type": "object", "required": ["num_tokens"], "properties": {
             "num_tokens": {"type": "integer", "examples": [16]}, "num_reqs": {"type": "integer", "examples": [16]},
             "is_profile": {"type": "boolean", "default": False},
             "attn_metadata": {"type": "object", "default": {}, "description": "the forward context's attention metadata (AttnCommonMetadata fields: block_table, seq_lens, query_lens, slot_mapping, num_actual_tokens, ...)"}}}},
        {"id": "ModelsForwardResult", "schema": {"type": "object", "properties": {
            "num_tokens": i, "hidden_size": i, "num_layers": i, "owner_ms": i}}},
        {"id": "ModelsLogitsRequest", "schema": {"type": "object", "required": ["num_tokens"], "properties": {
            "num_tokens": {"type": "integer", "examples": [16]}}}},
        {"id": "ModelsLogitsResult", "schema": {"type": "object", "properties": {"num_tokens": i, "vocab_size": i, "owner_ms": i}}},
        {"id": "ModelsLayerInput", "schema": {"type": "object", "required": ["num_tokens", "cfg", "tp", "quant", "layer_repeat"],
                                              "properties": {"num_tokens": i, "cfg": o, "tp": i, "quant": s, "layer_repeat": i}}},
        {"id": "ModelsLinearInput", "summary": "Per-rank GEMM shape of one linear layer; layer_repeat is how many decoder layers the call stands for.",
         "schema": {"type": "object", "required": ["num_tokens", "in_features", "out_features", "bytes_per_weight", "layer_repeat", "quant", "tp"],
                    "properties": {"num_tokens": i, "in_features": i, "out_features": i, "bytes_per_weight": {"type": "number"},
                                   "layer_repeat": i, "quant": s, "tp": i, "reduce_results": {"type": "boolean", "default": True},
                                   "gather_output": {"type": "boolean", "default": False}}}},
        {"id": "ModelsMoeInput", "schema": {"type": "object", "required": ["num_tokens", "hidden_size", "intermediate_size", "num_experts", "top_k", "tp"],
                                            "properties": {"num_tokens": i, "hidden_size": i, "intermediate_size": i, "num_experts": i,
                                                           "top_k": i, "tp": i, "bytes_per_weight": i, "layer_repeat": i,
                                                           "scoring_func": {"type": "string", "examples": ["softmax"]}, "shared_experts": {"type": "boolean", "default": False}}}},
        {"id": "ModelsLoRARequest", "schema": {"type": "object", "required": ["lora_name", "lora_int_id", "lora_path"], "properties": {
            "lora_name": {"type": "string", "examples": ["sql-lora"]}, "lora_int_id": {"type": "integer", "examples": [1]},
            "lora_path": {"type": "string", "examples": ["/adapters/sql-lora"]}, "load_inplace": {"type": "boolean", "default": False}}}},
        {"id": "ModelsLoRALinearInput", "schema": {"type": "object", "required": ["num_tokens", "in_features", "out_features", "rank", "any_lora"],
                                                   "properties": {"num_tokens": {"type": "integer", "examples": [16]},
                                                                  "in_features": {"type": "integer", "examples": [4096]},
                                                                  "out_features": {"type": "integer", "examples": [6144]},
                                                                  "rank": {"type": "integer", "examples": [8]},
                                                                  "num_slices": {"type": "integer", "examples": [3]},
                                                                  "any_lora": {"type": "boolean", "default": True}}}},
        {"id": "ModelsWeightCacheMessage", "schema": {"type": "object", "required": ["cmd"], "properties": {
            "cmd": {"type": "string", "examples": ["get_memory"]},
            "cache_config": {"type": ["object", "null"], "default": None},
            "peer_is_owner": {"type": "boolean", "default": True}}}},
        {"id": "ModelsWeightCacheReply", "schema": {"type": "object", "properties": {
            "status": s, "message": s, "memory_bytes": i, "fields": {"type": "array", "items": s}}}},
    ]


def boundaries():
    comps = [
        {"id": "tensor-model-parallel", "name": "communication_op (tensor_model_parallel_* helpers)", "kind": "module", "layer": "distributed", "parent": "gpu-worker",
         "summary": "The helpers model code calls (tensor_model_parallel_all_reduce/all_gather/reduce_scatter): each fetches the TP GroupCoordinator and delegates to it.",
         "sources": ["vllm/distributed/communication_op.py:12-28"], "attributes": {"boundary": True, "owner": "distributed"}},
        {"id": "custom-ops", "name": "Custom op wrappers (_custom_ops.py)", "kind": "module",
         "summary": "Boundary reference: torch custom-op wrappers, owned by kernels-ops.",
         "sources": ["vllm/_custom_ops.py:21"], "attributes": {"boundary": True, "owner": "kernels-ops"}},
        {"id": "flash-attention-impl", "name": "FlashAttentionImpl", "kind": "module", "parent": "gpu-worker", "layer": "attention",
         "summary": "FlashAttention forward (paged varlen), KV cache write, encoder and DCP paths.",
         "sources": ["vllm/v1/attention/backends/flash_attn.py:1052-1709"], "attributes": {"boundary": True, "owner": "attention"}},
    ]
    I = {"type": "integer"}
    dist_req = {"type": "object", "required": ["num_tokens"], "properties": {
        "num_tokens": {"type": "integer", "minimum": 1, "examples": [128]}, "hidden_size": {"type": "integer", "default": 4096},
        "dtype": {"type": "string", "default": "bfloat16"}, "dim": {"type": "integer", "default": -1},
        "num_collectives": {"type": "integer", "default": 1, "minimum": 1}, "layer": {"type": "integer"}}}
    dist_resp = {"type": "object", "properties": {"algorithm": {"type": "string"}, "backend": {"type": "string"}, "bytes": I,
                                                  "hidden_size": I, "num_tokens": I, "world_size": I}}
    tok = {"type": "object", "properties": {"num_tokens": I, "hidden_size": I, "dtype_bytes": I}}
    moe = {"type": "object", "properties": {"num_tokens": I, "num_experts": I, "topk": I, "k": I, "n": I, "dtype_bytes": I}}
    mm = {"type": "object", "properties": {"m": I, "n": I, "k": I, "dtype_bytes": I, "out_dtype": {"type": "string"},
                                           "has_bias": {"type": "boolean", "default": False}}}

    def stub(comp, name, kind, req, owner, summary, src, **kw):
        d = {"component": comp, "name": name, "kind": kind, "summary": summary, "sources": [src], "request": req,
             "attributes": {"boundary": True, "owner": owner}}
        d.update(kw)
        return d
    ae = [{"code": "assertion-error", "status": 0, "retryable": False}]
    ifaces = [
        stub("tensor-model-parallel", "all-reduce", "function", dist_req, "distributed",
             "tensor_model_parallel_all_reduce: sum across the TP group; each rank calls it once per collective and the ranks meet at a rendezvous keyed by `layer` (here the collective's index in the forward: 0 embedding, 1 o_proj, 2 down_proj/MoE).",
             "vllm/distributed/communication_op.py:12-14", response=dist_resp,
             errors=ae + [{"code": "dist-backend-error", "status": 0, "retryable": False}]),
        stub("tensor-model-parallel", "all-gather", "function", dist_req, "distributed",
             "tensor_model_parallel_all_gather: concatenate shards across the TP group.",
             "vllm/distributed/communication_op.py:17-22", response=dist_resp, errors=ae),
        stub("custom-ops", "rotary-embedding", "function", tok, "kernels-ops",
             "ops.rotary_embedding: in-place neox/gptj rotary on q and k.", "vllm/_custom_ops.py:210-235"),
        stub("custom-ops", "topk-softmax", "function", moe, "kernels-ops",
             "ops.topk_softmax: fused softmax + top-k over router logits.", "vllm/_custom_ops.py:2300-2320"),
        stub("custom-ops", "topk-sigmoid", "function", moe, "kernels-ops",
             "ops.topk_sigmoid: fused sigmoid + top-k over router logits.", "vllm/_custom_ops.py:2320-2335"),
        stub("custom-ops", "moe-align-block-size", "function", moe, "kernels-ops",
             "ops.moe_align_block_size: sort token slots by expert, padded to the GEMM block.", "vllm/_custom_ops.py:2163-2180"),
        stub("custom-ops", "moe-sum", "function", moe, "kernels-ops",
             "ops.moe_sum: sum the top-k expert outputs per token.", "vllm/_custom_ops.py:2154-2161"),
        stub("custom-ops", "cutlass-scaled-mm", "function", mm, "kernels-ops",
             "ops.cutlass_scaled_mm: FP8/INT8 GEMM with activation and weight scales.", "vllm/_custom_ops.py:790-820", errors=ae),
        stub("flash-attention-impl", "forward", "function",
             {"type": "object", "properties": {"num_tokens": I, "num_heads": I, "num_kv_heads": I, "head_size": I,
                                               "attn_type": {"type": "string", "default": "decoder"},
                                               "layer_name": {"type": "string", "default": "model.layers.0.self_attn.attn"},
                                               "metadata": {"type": ["object", "null"]}}}, "attention",
             "FlashAttentionImpl.forward: paged attention over the KV cache for this layer.", "vllm/v1/attention/backends/flash_attn.py:1052-1709",
             response={"type": "object", "properties": {"num_tokens": I, "path": {"type": "string"}}},
             errors=[{"code": "not-implemented-error", "status": 0, "retryable": False}]),
        stub("flash-attention-impl", "do-kv-cache-update", "function",
             {"type": "object", "properties": {"num_tokens": I, "num_kv_heads": I, "head_size": I,
                                               "attn_type": {"type": "string", "default": "decoder"},
                                               "slot_mapping": {"type": "array", "items": I}}}, "attention",
             "FlashAttentionImpl.do_kv_cache_update: write this step's K/V into the paged cache slots.", "vllm/v1/attention/backends/flash_attn.py:1052-1709",
             response={"type": "object", "properties": {"written_tokens": I}}),
        {"component": "hf-hub", "name": "download-config", "kind": "http",
         "summary": "Fetch a model's config.json (shared infrastructure). Rows of `models` are keyed by repo id.",
         "sources": ["vllm/transformers_utils/config.py:816-860"], "attributes": {"boundary": True, "owner": "shared"},
         "request": {"type": "object", "required": ["model"], "properties": {"model": {"type": "string", "examples": [M8]}}},
         "response": {"type": "object", "properties": {"architectures": {"type": "array", "items": {"type": "string"}}, "num_attention_heads": I,
                                                       "num_key_value_heads": I, "max_position_embeddings": I}},
         "errors": [{"code": "not_found", "status": 404, "retryable": False}],
         "store": {"table": "models", "op": "get", "key": "= input.model", "not_found": "not_found"}},
        {"component": "hf-hub", "name": "download-weights", "kind": "http",
         "summary": "snapshot_download of a model's weight files (shared infrastructure); an unknown repo fails.",
         "request": {"type": "object", "required": ["model"], "properties": {"model": {"type": "string", "examples": [M8]}}},
         "errors": [{"code": "repository-not-found-error", "status": 0, "retryable": False}],
         "store": {"table": "models", "op": "get", "key": "= input.model", "not_found": "repository-not-found-error"},
         "attributes": {"boundary": True, "owner": "shared"}},
        {"component": "gpu-memory", "name": "allocate", "kind": "io",
         "summary": "Allocates device memory for one pool (kv_cache, cudagraph, weights, runtime); fails like torch.OutOfMemoryError when it does not fit.",
         "sources": ["vllm/v1/worker/gpu/attn_utils.py:396-455"], "latency_ms": 0,
         "errors": [{"code": "out-of-memory-error", "status": 0, "retryable": False}],
         "request": {"type": "object", "required": ["kind", "bytes"], "properties": {
             "kind": {"type": "string", "enum": ["kv_cache", "cudagraph", "weights", "runtime"]}, "bytes": I}},
         "response": {"type": "object", "properties": {"kind": {"type": "string"}, "bytes": I, "free_bytes": I}},
         "attributes": {"boundary": True, "owner": "worker-runner"}},
        {"component": "local-disk", "name": "read-file", "kind": "io",
         "summary": "Read a file from local disk (shared infrastructure); a missing file is FileNotFoundError.",
         "request": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
         "errors": [{"code": "file-not-found-error", "status": 0, "retryable": False}],
         "store": {"table": "files", "op": "get", "key": "= input.path", "not_found": "file-not-found-error"},
         "attributes": {"boundary": True, "owner": "shared"}},
    ]
    return comps, ifaces


def flows():
    def f(id_, name, iface, src, inp=None, tags=None, **kw):
        d = {"id": id_, "name": name, "entry": {"caller": "gpu-worker", "interface": iface}, "sources": src}
        if inp is not None:
            d["entry"]["input"] = inp
        if tags:
            d["tags"] = tags
        d["entry"].update(kw)
        return d
    return [
        f("models-get-model", "Load the model on a rank (get_model)", "model-loader.get-model",
          ["vllm/model_executor/model_loader/__init__.py:131-143"], {"model": M8, "hf_config": LLAMA8}, ["writes"]),
        f("models-llama-forward", "Llama forward pass", "llama-for-causal-lm.forward",
          ["vllm/model_executor/models/llama.py:534-544"], {"num_tokens": 16, "num_reqs": 16}),
        f("models-llama-compute-logits", "Llama logits", "llama-for-causal-lm.compute-logits",
          ["vllm/model_executor/models/llama.py:546-551"], {"num_tokens": 16}),
        f("models-mixtral-forward", "Mixtral (MoE) forward pass", "mixtral-for-causal-lm.forward",
          ["vllm/model_executor/models/mixtral.py:467-477"], {"num_tokens": 16, "num_reqs": 16}),
        f("models-registry-resolve", "Resolve an architecture to a model class", "model-registry.resolve-model-cls",
          ["vllm/model_executor/models/registry.py:1376-1428"], {"architectures": ["LlamaForCausalLM"]}),
        f("models-registry-inspect", "Inspect a model class (cached _ModelInfo)", "model-registry.inspect-model-cls",
          ["vllm/model_executor/models/registry.py:1323-1374"], {"architectures": ["LlamaForCausalLM"]}, ["writes"]),
        f("models-registry-register", "Register an out-of-tree model", "model-registry.register-model",
          ["vllm/model_executor/models/registry.py:1132-1175"],
          {"model_arch": "MyLlamaForCausalLM", "model_cls": "my_plugin.models:MyLlamaForCausalLM"}, ["writes"]),
        f("models-registry-subprocess-main", "python -m vllm.model_executor.models.registry", "model-registry-subprocess.run",
          ["vllm/model_executor/models/registry.py:1594-1595"], {"model_arch": "LlamaForCausalLM"}),
        f("models-lora-add-adapter", "Add a LoRA adapter on a worker", "lru-cache-worker-lora-manager.add-adapter",
          ["vllm/lora/worker_manager.py:289-325"], lora(1, "sql-lora"), ["writes", "feature:lora"]),
        f("models-lora-set-active-adapters", "Activate the step's LoRA adapters", "lru-cache-worker-lora-manager.set-active-adapters",
          ["vllm/lora/worker_manager.py:195-198"], {"requests": [lora(1, "sql-lora")]}, ["writes"]),
        f("models-lora-list-adapters", "List loaded LoRA adapters", "lru-cache-worker-lora-manager.list-adapters",
          ["vllm/lora/worker_manager.py:241-242"]),
        f("models-lora-linear", "Linear layer with LoRA (Punica shrink/expand)", "base-linear-layer-with-lora.apply",
          ["vllm/lora/layers/base_linear.py:198-212"],
          {"num_tokens": 16, "in_features": 4096, "out_features": 6144, "rank": 8, "num_slices": 3, "any_lora": True}, ["feature:lora"]),
        f("models-weight-cache-serve", "Weight cache daemon serve loop", "weight-cache-daemon.serve-forever",
          ["vllm/model_executor/model_loader/weight_cache/daemon.py:366-386"], {"cmd": "get_memory"}, ["writes"],
          repeat={"count": 3, "interval_ms": 10}),
        f("models-quant-config", "Build the quantization config", "weight-utils.get-quant-config",
          ["vllm/model_executor/model_loader/weight_utils.py:192-395"],
          {"quantization": "fp8", "hf_quant_config": {"quant_method": "fp8", "activation_scheme": "dynamic", "weight_block_size": [128, 128]}}, ["feature:quantization"]),
        f("models-multimodal-process", "Process a multimodal prompt (MULTIMODAL_REGISTRY processor)", "base-multi-modal-processor.apply",
          ["vllm/multimodal/processing/processor.py:1811-1847"],
          {"model": "Qwen/Qwen2-VL-7B-Instruct", "architectures": ["Qwen2VLForConditionalGeneration"], "prompt_token_ids": [151644, 872, 151652, 151655, 151653], "mm_counts": {"image": 1}}),
        f("models-eplb-register", "EPLB registers the MoE model's layers (EplbState.add_model -> set_eplb_state)", "mixtral-for-causal-lm.set-eplb-state",
          ["vllm/model_executor/models/interfaces.py:1039-1072"],
          {"logical_to_physical_map": [[0, 8], [1, 9], [2], [3], [4], [5], [6], [7]], "logical_replica_count": [2, 2, 1, 1, 1, 1, 1, 1]},
          ["writes", "feature:expert-parallel"]),
    ]


def sc(id_, flow=None, fixtures=("tp1-llama-8b",), **kw):
    d = {"id": id_}
    if flow:
        d["flow"] = flow
    d["fixtures"] = list(fixtures)
    d.update(kw)
    return d


def step(flow=None, iface=None, as_=None, inp=None, on=None, choices=None, nowait=False, at=None):
    d = {}
    if nowait:
        d["await"] = False
    if at is not None:
        d["at_ms"] = at
    if flow:
        d["flow"] = flow
    if iface:
        d["interface"], d["caller"] = iface, "gpu-worker"
    if as_:
        d["as"] = as_
    if inp is not None:
        d["input"] = inp
    if on:
        d["on"] = on
    if choices:
        d["choices"] = choices
    return d


LOAD = step("models-get-model", as_="load")
FWD = step("models-llama-forward", as_="fwd")
NOT_LOADED = "!steps.fwd.result.ok && steps.fwd.result.error.code == 'attribute-error'"
FAIL_TRACE = "trace.exists(e, e.type == 'call.end' && e.interface == 'model-loader.get-model' && e.error != null)"
OK_TRACE = "trace.exists(e, e.type == 'call.end' && e.interface == 'model-loader.get-model' && e.error == null)"
RANKS = ["rank0", "rank1", "rank2", "rank3"]


def load_all(model, hf):
    return [step("models-get-model", as_=f"load_{r}", inp={"model": model, "hf_config": hf}, on=r) for r in RANKS]


def on_all(flow=None, iface=None, as_="x", inp=None, at=100000):
    """The same call on every TP rank at once: collectives meet at a rendezvous."""
    return [step(flow, iface, as_=f"{as_}_{r}", inp=inp, on=r, nowait=(r != RANKS[-1]), at=at) for r in RANKS]


def scenario_list():
    L = []
    # ------------------------------------------------------------------ registry
    L += [
        sc("models-registry-resolve-llama", "models-registry-resolve",
           expect=["result.ok && result.value.module == 'llama' && result.value.class_name == 'LlamaForCausalLM'",
                   "result.value.component == 'llama-for-causal-lm' && result.value.table == 'text_generation'",
                   "calls['model-registry.load-model-cls'] == 1 && calls['model-registry.try-resolve-transformers'] == 0"]),
        sc("models-registry-resolve-first-registered", "models-registry-resolve",
           input={"architectures": ["NotARealArchitecture", "MixtralForCausalLM"]},
           expect=["result.ok && result.value.arch == 'MixtralForCausalLM' && result.value.component == 'mixtral-for-causal-lm'",
                   "calls['model-registry.try-resolve-transformers'] == 0"]),
        sc("models-registry-resolve-empty", "models-registry-resolve", input={"architectures": []},
           expect=["!result.ok && result.error.code == 'value-error' && result.error.message == 'No model architectures are specified'"]),
        sc("models-registry-resolve-removed", "models-registry-resolve", input={"architectures": ["MotifForCausalLM"]},
           expect=["!result.ok && result.error.code == 'value-error' && result.error.message.contains('until v0.10.2')",
                   "calls['model-registry.raise-for-unsupported'] == 1"]),
        sc("models-registry-resolve-out-of-tree", "models-registry-resolve", input={"architectures": ["BartModel"]},
           expect=["!result.ok && result.error.message.contains('bart-plugin')"]),
        sc("models-registry-resolve-unknown", "models-registry-resolve", input={"architectures": ["NotARealArchitecture"]},
           expect=["!result.ok && result.error.code == 'value-error' && result.error.message.contains('are not supported for now')",
                   "calls['model-registry.try-resolve-transformers'] == 1"]),
        sc("models-registry-resolve-transformers-fallback", "models-registry-resolve", input={"architectures": ["NotARealArchitecture"]},
           choices={"model-registry.try-resolve-transformers.transformers_class": "compatible"},
           expect=["result.ok && result.value.arch == 'TransformersForCausalLM' && result.value.table == 'transformers_backend'",
                   "result.value.component == 'auto-weights-loader'"]),
        sc("models-registry-resolve-transformers-impl", "models-registry-resolve",
           input={"architectures": ["NotARealArchitecture"], "model_impl": "transformers"},
           expect=["!result.ok && result.error.message.contains('Cannot find model module')"]),
        sc("models-registry-resolve-transformers-backend-entry", "models-registry-resolve",
           input={"architectures": ["TransformersForCausalLM"], "model_impl": "transformers"},
           expect=["result.ok && result.value.arch == 'TransformersForCausalLM' && calls['model-registry.load-model-cls'] == 0"]),
        sc("models-registry-resolve-failed-import", fixtures=("tp1-llama-8b",),
           steps=[step(iface="model-registry.raise-for-unsupported", as_="r", inp={"architectures": ["LlamaForCausalLM"]})],
           expect=["!steps.r.result.ok && steps.r.result.error.message.contains('failed to be inspected')"]),
        sc("models-registry-inspect-cache", "models-registry-inspect",
           steps=[step("models-registry-inspect", as_="first"), step("models-registry-inspect", as_="second")],
           expect=["steps.first.result.ok && steps.second.result.ok && steps.second.result.value.architecture == 'LlamaForCausalLM'",
                   "calls['model-registry-subprocess.run-in-subprocess'] == 1",
                   "'LlamaForCausalLM' in state['model-registry@rank0'].modelinfo_cache && ctx.modelinfo_source == 'cache'"]),
        sc("models-registry-inspect-subprocess-fails", "models-registry-inspect",
           faults=[{"target": "model-registry-subprocess.run", "type": "error", "code": "called-process-error"}],
           expect=["!result.ok && result.error.code == 'runtime-error' && result.error.message.contains('Error raised in subprocess')",
                   "size(state['model-registry@rank0'].modelinfo_cache) == 0"]),
        sc("models-registry-inspect-unsupported", "models-registry-inspect", input={"architectures": ["NotARealArchitecture"]},
           expect=["!result.ok && result.error.code == 'value-error' && calls['model-registry-subprocess.run-in-subprocess'] == 0"]),
        sc("models-registry-inspect-empty", "models-registry-inspect", input={"architectures": []},
           expect=["!result.ok && result.error.message == 'No model architectures are specified'"]),
        sc("models-registry-register-then-resolve", "models-registry-register",
           steps=[step("models-registry-register", as_="reg"),
                  step("models-registry-resolve", as_="res", inp={"architectures": ["MyLlamaForCausalLM"]})],
           expect=["steps.reg.result.ok && !steps.reg.result.value.overwritten",
                   "steps.res.result.ok && steps.res.result.value.module == 'my_plugin.models' && steps.res.result.value.table == 'plugin'",
                   "state['model-registry@rank0'].models['MyLlamaForCausalLM'].class_name == 'MyLlamaForCausalLM'"]),
        sc("models-registry-register-overwrite", "models-registry-register",
           input={"model_arch": "LlamaForCausalLM", "model_cls": "my_plugin.models:PatchedLlama"},
           expect=["result.ok && result.value.overwritten",
                   "state['model-registry@rank0'].models['LlamaForCausalLM'].class_name == 'PatchedLlama'"]),
        sc("models-registry-register-bad-format", "models-registry-register", input={"model_cls": "my_plugin.models.MyLlama"},
           expect=["!result.ok && result.error.code == 'value-error' && !('MyLlamaForCausalLM' in state['model-registry@rank0'].models)"]),
        sc("models-registry-subprocess-main-run", "models-registry-subprocess-main",
           expect=["result.ok && result.value.architecture == 'LlamaForCausalLM' && result.value.is_text_generation_model",
                   "calls['model-registry.load-model-cls'] == 1 && duration_ms >= 1500"]),
    ]
    # ------------------------------------------------------------------ loading
    L += [
        sc("models-get-model-llama-then-forward", "models-get-model",
           steps=[LOAD, step("models-llama-forward", as_="fwd")],
           expect=["steps.load.result.ok && steps.load.result.value.component == 'llama-for-causal-lm' && steps.load.result.value.quant == 'unquantized'",
                   "steps.fwd.result.ok && steps.fwd.result.value.num_layers == 32 && steps.fwd.result.value.hidden_size == 4096",
                   "io.filter(i, i.interface == 'hf-hub.download-weights').size() == 1",
                   # the read-back reaches the weights init and load_weights wrote (state)
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'llama-for-causal-lm.forward' && e.error == null)",
                   "calls['tensor-model-parallel.all-reduce'] == 0"]),
        sc("models-get-model-unknown-format", "models-get-model", config={"load-format": "zip"},
           steps=[LOAD, FWD],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'value-error' && steps.load.result.error.message.contains('zip')",
                   NOT_LOADED, "io.filter(i, i.interface == 'hf-hub.download-weights').size() == 0"]),
        sc("models-get-model-dummy", "models-get-model", config={"load-format": "dummy"},
           steps=[LOAD, FWD],
           expect=["steps.load.result.ok && steps.load.result.value.loader == 'dummy-model-loader'",
                   "steps.fwd.result.ok && io.filter(i, i.interface == 'hf-hub.download-weights').size() == 0", OK_TRACE]),
        sc("models-get-model-repo-missing", "models-get-model",
           steps=[step("models-get-model", as_="load", inp={"model": "meta-llama/Not-A-Real-Model"}), FWD],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'repository-not-found-error'", NOT_LOADED, FAIL_TRACE]),
        sc("models-get-model-no-weight-files", "models-get-model",
           state={"hf-hub": {"models": {M8: {"weights_bytes": 0}}}}, steps=[LOAD, FWD],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'runtime-error' && steps.load.result.error.message.contains('Cannot find any model weights')",
                   NOT_LOADED, FAIL_TRACE]),
        sc("models-get-model-missing-weights", "models-get-model",
           state={"hf-hub": {"models": {M8: {"missing_params": ["lm_head.weight"]}}}},
           expect=["!result.ok && result.error.code == 'value-error' && result.error.message.contains('lm_head.weight')", FAIL_TRACE]),
        sc("models-get-model-unexpected-tensor", "models-get-model",
           steps=[step(iface="auto-weights-loader.load-weights", as_="awl", inp={"model": M8, "weights_bytes": 1, "unexpected_names": ["model.layers.0.mlp.extra"]})],
           expect=["!steps.awl.result.ok && steps.awl.result.error.message.contains('model.layers.0.mlp.extra')"]),
        sc("models-get-model-tp4-70b", "models-get-model", fixtures=("tp4-llama-70b",),
           steps=load_all(M70, LLAMA70) + on_all("models-llama-forward", as_="fwd"),
           expect=["steps.load_rank0.result.ok && steps.load_rank3.result.ok",
                   "steps.load_rank0.result.value.weights_bytes_per_rank == 35276853248 && steps.load_rank3.result.value.weights_bytes_per_rank == 35276853248",
                   "steps.fwd_rank3.result.ok && steps.fwd_rank0.result.ok",
                   "calls_by_instance['tensor-model-parallel.all-reduce@rank3'] == 3 && calls['tensor-model-parallel.all-reduce'] == 12"]),
        sc("models-get-model-heads-not-divisible", "models-get-model", fixtures=("tp1-llama-8b",),
           topology={"gpu-worker": ["rank0", "rank1", "rank2"]}, config={"tensor-parallel-size": 3},
           steps=[LOAD, FWD],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'assertion-error'", NOT_LOADED,
                   "io.filter(i, i.interface == 'hf-hub.download-weights').size() == 0"]),
        sc("models-get-model-non-silu", "models-get-model",
           steps=[step("models-get-model", as_="load", inp={"hf_config": {"hidden_act": "gelu"}}), FWD],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'value-error' && steps.load.result.error.message.contains('Only silu')", NOT_LOADED]),
        sc("models-get-model-fp8-block-then-forward", "models-get-model",
           state={"hf-hub": {"models": {FP8: FP8_HF}}},
           steps=[step("models-get-model", as_="load", inp={"model": FP8, "hf_config": FP8_HF}), step("models-llama-forward", as_="fwd")],
           expect=["steps.load.result.ok && steps.load.result.value.quant == 'fp8_block'",
                   "ctx.fp8_weights_processed == 'block'",
                   # the kernel choice is the point of this case (internal by design)
                   "steps.fwd.result.ok && calls['scaled-mm-triton.w8a8-triton-block-scaled-mm-func'] == 4 && calls['unquantized-linear-method.apply'] == 0"]),
        sc("models-get-model-fp8-cutlass", "models-get-model",
           state={"hf-hub": {"models": {FP8: dict(FP8_HF, quantization_config={"quant_method": "fp8", "activation_scheme": "static"})}}},
           steps=[step("models-get-model", as_="load", inp={"model": FP8, "hf_config": dict(FP8_HF, quantization_config={"quant_method": "fp8", "activation_scheme": "static"})}),
                  step("models-llama-forward", as_="fwd")],
           expect=["steps.load.result.value.quant == 'fp8' && ctx.fp8_weights_processed == 'per_tensor'",
                   "steps.fwd.result.ok && calls['custom-ops.cutlass-scaled-mm'] == 4",
                   OK_TRACE]),
        sc("models-get-model-fp8-static-block-refused", "models-get-model",
           steps=[step("models-get-model", as_="load", inp={"model": FP8, "hf_config": dict(FP8_HF, quantization_config={"quant_method": "fp8", "activation_scheme": "static", "weight_block_size": [128, 128]})}), FWD],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'value-error' && steps.load.result.error.message.contains('dynamic activation scheme')", NOT_LOADED]),
        sc("models-get-model-invalid-quantization", "models-get-model", config={"quantization": "int3"}, steps=[LOAD, FWD],
           expect=["!steps.load.result.ok && steps.load.result.error.message == 'Invalid quantization method: int3'", NOT_LOADED]),
        sc("models-get-model-ipc-cache", "models-get-model", config={"load-format": "ipc_cache"}, steps=[LOAD, FWD],
           expect=["steps.load.result.ok && steps.load.result.value.loader == 'ipc-model-loader' && ctx.ipc_fallback == 'none'",
                   "steps.fwd.result.ok && io.filter(i, i.interface == 'hf-hub.download-weights').size() == 0", OK_TRACE]),
        sc("models-get-model-ipc-mismatch-fallback", "models-get-model", config={"load-format": "ipc_cache"},
           state={"weight-cache-daemon": {"cache_key": {"model": M70}}}, steps=[LOAD, FWD],
           expect=["steps.load.result.ok && steps.load.result.value.loader == 'default-model-loader' && ctx.ipc_fallback == 'mismatch'",
                   "steps.fwd.result.ok && io.filter(i, i.interface == 'hf-hub.download-weights').size() == 1", OK_TRACE]),
        sc("models-get-model-ipc-unavailable-no-fallback", "models-get-model",
           config={"load-format": "ipc_cache", "model-loader-extra-config": {"fallback": False}},
           faults=[{"target": "weight-cache-daemon.handle-connection", "type": "unavailable"}], steps=[LOAD, FWD],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'weight-cache-unavailable-error'", NOT_LOADED]),
        sc("models-get-model-ipc-unavailable-fallback", "models-get-model", config={"load-format": "ipc_cache"},
           faults=[{"target": "weight-cache-daemon.handle-connection", "type": "unavailable"}],
           steps=[LOAD, FWD],
           expect=["steps.load.result.ok && ctx.ipc_fallback == 'unavailable' && steps.fwd.result.ok", OK_TRACE]),
        sc("models-get-model-ipc-mismatch-no-fallback", "models-get-model",
           config={"load-format": "ipc_cache", "model-loader-extra-config": {"fallback": False}},
           state={"weight-cache-daemon": {"cache_key": {"tp_size": 4}}}, steps=[LOAD, FWD],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'cache-config-mismatch-error'", NOT_LOADED]),
        sc("models-get-model-transformers-backend", "models-get-model",
           input={"hf_config": {"architectures": ["NotARealArchitecture"]}},
           choices={"model-registry.try-resolve-transformers.transformers_class": "compatible"},
           expect=["result.ok && result.value.model_cls == 'TransformersForCausalLM' && result.value.component == 'auto-weights-loader'",
                   "trace.filter(e, e.type == 'call.end' && e.interface == 'model-registry.resolve-model-cls' && e.output.arch == 'TransformersForCausalLM').size() == 1"]),
        sc("models-get-model-arch-cache", "models-get-model",
           steps=[LOAD, step("models-get-model", as_="again")],
           expect=["steps.again.result.ok",
                   # the second load hits _MODEL_ARCH_BY_HASH: the registry is resolved once
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'model-registry.resolve-model-cls').size() == 1"]),
        sc("models-download-model", "models-get-model",
           steps=[step(iface="default-model-loader.download-model", as_="dl", inp={"model": M8})],
           expect=["steps.dl.result.ok && steps.dl.result.value.weights_bytes == 16060522496 && calls['hf-hub.download-weights'] == 1"]),
    ]
    # ------------------------------------------------------------------ forward
    L += [
        sc("models-llama-forward-not-loaded", "models-llama-forward",
           expect=["!result.ok && result.error.code == 'attribute-error'"]),
        sc("models-llama-compute-logits-not-loaded", "models-llama-compute-logits",
           expect=["!result.ok && result.error.code == 'attribute-error'"]),
        sc("models-llama-prefill-slower-than-decode", "models-llama-forward",
           steps=[LOAD, step("models-llama-forward", as_="prefill", inp={"num_tokens": 2048, "num_reqs": 1}),
                  step("models-llama-forward", as_="decode", inp={"num_tokens": 1, "num_reqs": 1})],
           expect=["steps.prefill.result.ok && steps.decode.result.ok",
                   "steps.prefill.duration_ms > steps.decode.duration_ms + 15",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'flash-attention-impl.forward').size() == 2"]),
        sc("models-llama-compute-logits-tp1", "models-llama-compute-logits",
           steps=[LOAD, step("models-llama-compute-logits", as_="lg")],
           expect=["steps.lg.result.ok && steps.lg.result.value.vocab_size == 128256",
                   "steps.lg.result.value.owner_ms == 0", OK_TRACE]),
        sc("models-llama-compute-logits-tp4", "models-llama-compute-logits", fixtures=("tp4-llama-70b",),
           steps=load_all(M70, LLAMA70) + on_all("models-llama-compute-logits", as_="lg"),
           expect=["steps.lg_rank0.result.ok && steps.lg_rank3.result.ok && calls['tensor-model-parallel.all-gather'] == 4",
                   OK_TRACE]),
        sc("models-llama-forward-batch-invariant", "models-llama-forward", config={"vllm-batch-invariant": True},
           steps=[LOAD, step("models-llama-forward", as_="fwd")],
           expect=["steps.fwd.result.ok && calls['batch-invariant.linear-batch-invariant'] == 4",
                   "calls['batch-invariant.rms-norm-batch-invariant'] == 3", OK_TRACE]),
        sc("models-mixtral-forward-tp4", "models-mixtral-forward", fixtures=("tp4-llama-70b",), state=MIX_STATE,
           steps=load_all(MIX, MIXTRAL) + on_all("models-mixtral-forward", as_="fwd"),
           expect=["steps.load_rank0.result.value.component == 'mixtral-for-causal-lm' && steps.fwd_rank0.result.ok",
                   "calls['custom-ops.topk-softmax'] == 4 && calls['custom-ops.moe-align-block-size'] == 4",
                   "calls['tensor-model-parallel.all-reduce'] == 12 && ctx.router_gemm == 'replicated_linear'"]),
        sc("models-mixtral-forward-single-token", "models-mixtral-forward", fixtures=("tp4-llama-70b",), state=MIX_STATE,
           steps=load_all(MIX, MIXTRAL) + on_all("models-mixtral-forward", as_="fwd", inp={"num_tokens": 1, "num_reqs": 1}),
           expect=["steps.fwd_rank0.result.ok && calls['custom-ops.moe-align-block-size'] == 0",
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'mixtral-for-causal-lm.forward' && e.error == null)"]),
        sc("models-mixtral-compute-logits", "models-mixtral-forward", fixtures=("tp4-llama-70b",), state=MIX_STATE,
           steps=load_all(MIX, MIXTRAL) + on_all(iface="mixtral-for-causal-lm.compute-logits", as_="lg", inp={"num_tokens": 4}),
           expect=["steps.lg_rank0.result.ok && steps.lg_rank0.result.value.vocab_size == 32000 && calls['tensor-model-parallel.all-gather'] == 4",
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'model-loader.get-model' && e.error == null)"]),
        sc("models-get-model-kv-heads-not-divisible", "models-get-model", fixtures=("tp1-llama-8b",),
           topology={"gpu-worker": ["rank0", "rank1", "rank2"]}, config={"tensor-parallel-size": 3},
           steps=[step("models-get-model", as_="load", inp={"hf_config": {"num_attention_heads": 48}}), FWD],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'assertion-error' && steps.load.result.error.message.contains('KV heads')", NOT_LOADED]),
        sc("models-lora-disk-error", "models-lora-add-adapter", state=ADAPTER,
           faults=[{"target": "local-disk.read-file", "type": "error", "code": "permission-error"}],
           steps=[step("models-lora-add-adapter", as_="add"), step("models-lora-list-adapters", as_="ls")],
           expect=["!steps.add.result.ok && steps.add.result.error.code == 'permission-error'", "steps.ls.result.value.registered == []"]),
        sc("models-mixtral-forward-not-loaded", "models-mixtral-forward",
           expect=["!result.ok && result.error.code == 'attribute-error'"]),
        sc("models-mixtral-tp3-refused", "models-get-model", fixtures=("tp1-llama-8b",), state=MIX_STATE,
           topology={"gpu-worker": ["rank0", "rank1", "rank2"]}, config={"tensor-parallel-size": 3},
           steps=[step("models-get-model", as_="load", inp={"model": MIX, "hf_config": MIXTRAL}), step("models-mixtral-forward", as_="fwd")],
           expect=["!steps.load.result.ok && steps.load.result.error.code == 'assertion-error'", NOT_LOADED]),
        sc("models-moe-shared-experts-sigmoid", "models-mixtral-forward",
           steps=[step(iface="moe-runner.forward", as_="moe", inp={"num_tokens": 64, "hidden_size": 7168, "intermediate_size": 2048, "num_experts": 256,
                                                                   "top_k": 8, "tp": 1, "bytes_per_weight": 1, "layer_repeat": 1,
                                                                   "scoring_func": "sigmoid", "shared_experts": True})],
           expect=["steps.moe.result.ok && calls['moe-runner.moe-forward-shared'] == 1 && calls['custom-ops.topk-sigmoid'] == 1",
                   "ctx.moe_shared_experts_ran && calls['tensor-model-parallel.all-reduce'] == 0"]),
        sc("models-moe-unsupported-scoring", "models-mixtral-forward",
           steps=[step(iface="fused-top-k-router.select-experts", as_="r", inp={"num_tokens": 4, "num_experts": 8, "top_k": 2, "scoring_func": "relu"})],
           expect=["!steps.r.result.ok && steps.r.result.error.message == 'Unsupported scoring function: relu'"]),
        sc("models-moe-activation-variants", "models-mixtral-forward",
           steps=[step(iface="fused-moe-activation.apply-moe-activation", as_="clamp",
                       inp={"activation": "silu", "num_tokens": 8, "d": 128, "clamp_limit": 7.0, "has_expert_map": True}),
                  step(iface="fused-moe-activation.apply-moe-activation", as_="clamp2",
                       inp={"activation": "silu", "num_tokens": 8, "d": 128, "clamp_limit": 7.0}),
                  step(iface="fused-moe-activation.apply-moe-activation", as_="step",
                       inp={"activation": "swiglustep", "num_tokens": 8, "d": 128}),
                  step(iface="fused-moe-activation.apply-moe-activation", as_="masked",
                       inp={"activation": "silu", "num_tokens": 8, "d": 128, "masked": True}),
                  step(iface="fused-moe-activation.apply-moe-activation", as_="gelu",
                       inp={"activation": "gelu", "num_tokens": 8, "d": 128})],
           expect=["steps.clamp.result.value.activation == 'silu_with_clamp' && ctx.swiglu_kernel == 'pad_aware'",
                   "calls['fused-moe-utils.swiglu-limit-func'] == 1 && steps.clamp2.result.ok",
                   "steps.step.result.value.activation == 'swiglustep' && calls['layers-activation.swiglustep-and-mul-triton'] == 1",
                   "steps.masked.result.value.masked && steps.gelu.result.value.activation == 'gelu'"]),
        sc("models-moe-activation-unsupported", "models-mixtral-forward",
           steps=[step(iface="fused-moe-activation.apply-moe-activation", as_="bad", inp={"activation": "tanh", "num_tokens": 8, "d": 128}),
                  step(iface="fused-moe-activation.apply-moe-activation", as_="badmask",
                       inp={"activation": "relu2_no_mul", "num_tokens": 8, "d": 128, "masked": True})],
           expect=["!steps.bad.result.ok && steps.bad.result.error.message == 'Unsupported FusedMoe activation: tanh'",
                   "!steps.badmask.result.ok && steps.badmask.result.error.code == 'not-implemented-error'"]),
        sc("models-fused-experts-op", "models-mixtral-forward",
           steps=[step(iface="fused-moe.fused-experts", as_="fe", inp={"num_tokens": 32, "hidden_size": 4096, "intermediate_size": 14336,
                                                                     "num_experts": 8, "top_k": 2, "tp": 1, "bytes_per_weight": 2, "layer_repeat": 1})],
           expect=["steps.fe.result.ok && calls['fused-moe.invoke-fused-moe-triton-kernel'] == 2 && calls['fused-moe-activation.apply-moe-activation'] == 1"]),
        sc("models-gate-linear-fp32-tier", "models-mixtral-forward",
           steps=[step(iface="gate-linear.forward", as_="g", inp={"num_tokens": 8, "hidden_size": 4096, "num_experts": 8},
                       choices={"gate-linear.forward.tier": "fp32_router_gemm"}),
                  step(iface="gate-linear.forward", as_="g2", inp={"num_tokens": 8, "hidden_size": 4096, "num_experts": 8},
                       choices={"gate-linear.forward.tier": "ll_bf16"})],
           expect=["steps.g.result.ok && steps.g2.result.ok && ctx.router_gemm == 'll_bf16_gemm'",
                   "trace.exists(e, e.type == 'choice' && e.option == 'fp32_router_gemm')"]),
        sc("models-column-parallel-gather", "models-llama-forward", fixtures=("tp4-llama-70b",),
           steps=on_all(iface="column-parallel-linear.forward", as_="c", at=0,
                        inp={"num_tokens": 8, "in_features": 8192, "out_features": 2048, "bytes_per_weight": 2, "layer_repeat": 1,
                             "quant": "unquantized", "tp": 4, "gather_output": True}),
           expect=["steps.c_rank0.result.ok && steps.c_rank3.result.ok && calls['tensor-model-parallel.all-gather'] == 4"]),
        sc("models-qkv-weight-loader-bad-shard", "models-get-model",
           steps=[step(iface="qkv-parallel-linear.weight-loader", as_="w", inp={"num_heads": 64, "num_kv_heads": 8, "head_dim": 128, "tp_size": 16, "shard_id": "k"}),
                  step(iface="qkv-parallel-linear.weight-loader", as_="bad", inp={"num_heads": 64, "num_kv_heads": 8, "head_dim": 128, "tp_size": 16, "shard_id": "o"})],
           expect=["steps.w.result.value.shard_rows == 128 && steps.w.result.value.kv_replicas == 2",
                   "!steps.bad.result.ok && steps.bad.result.error.code == 'value-error'"]),
        sc("models-rope-variants", "models-get-model",
           steps=[step(iface="rotary-embedding.get-rope", as_="l3", inp={"head_size": 128, "max_position": 131072,
                                                                       "rope_parameters": {"rope_type": "llama3", "factor": 8.0, "low_freq_factor": 1.0, "high_freq_factor": 4.0, "original_max_position_embeddings": 8192}}),
                  step(iface="rotary-embedding.get-rope", as_="l3again", inp={"head_size": 128, "max_position": 131072,
                                                                            "rope_parameters": {"rope_type": "llama3", "factor": 8.0}}),
                  step(iface="rotary-embedding.get-rope", as_="mr", inp={"head_size": 128, "max_position": 128000,
                                                                       "rope_parameters": {"rope_type": "default", "mrope_section": [16, 24, 24]}}),
                  step(iface="m-rotary-embedding.forward-cuda", as_="mrf", inp={"num_tokens": 256, "positions_ndim": 2}),
                  step(iface="m-rotary-embedding.forward-cuda", as_="mrt", inp={"num_tokens": 256, "positions_ndim": 1}),
                  step(iface="rotary-embedding.forward-cuda", as_="fi", inp={"num_tokens": 16, "num_heads": 32, "num_kv_heads": 8, "head_size": 128, "use_flashinfer": True})],
           expect=["steps.l3.result.value.cls == 'Llama3RotaryEmbedding' && !steps.l3.result.value.cached && steps.l3again.result.value.cached",
                   "steps.mr.result.value.cls == 'MRotaryEmbedding' && steps.mrf.result.value.path == 'triton_mrope' && steps.mrt.result.value.path == 'apply_rotary_emb'",
                   "ctx.rope_impl == 'flashinfer' && calls['custom-ops.rotary-embedding'] == 0",
                   "size(state['rotary-embedding@rank0'].rope_cache) == 2"]),
        sc("models-rope-refusals", "models-get-model",
           steps=[step(iface="rotary-embedding.get-rope", as_="unk", inp={"head_size": 128, "max_position": 4096, "rope_parameters": {"rope_type": "spiral"}}),
                  step(iface="rotary-embedding.get-rope", as_="prf", inp={"head_size": 128, "max_position": 4096, "rope_parameters": {"partial_rotary_factor": 1.5}}),
                  step(iface="rotary-embedding.get-rope", as_="l3", inp={"head_size": 128, "max_position": 4096, "rope_parameters": {"rope_type": "llama3"}})],
           expect=["!steps.unk.result.ok && steps.unk.result.error.message == 'Unknown RoPE scaling type spiral'",
                   "!steps.prf.result.ok && steps.prf.result.error.message.contains('must be between 0.0 and 1.0')",
                   "!steps.l3.result.ok && steps.l3.result.error.code == 'key-error' && size(state['rotary-embedding@rank0'].rope_cache) == 0"]),
        sc("models-fp8-quant-fallback-paths", "models-get-model",
           steps=[step(iface="fp8-utils.per-token-group-quant-fp8", as_="nc", inp={"num_tokens": 16, "hidden_size": 4096, "group_size": 128, "contiguous": False}),
                  step(iface="fp8-utils.per-token-group-quant-fp8", as_="cm", inp={"num_tokens": 16, "hidden_size": 4096, "group_size": 128, "contiguous": False, "column_major_scales": True})],
           expect=["steps.nc.result.value.path == 'triton' && steps.cm.result.value.path == 'triton_colmajor'"]),
        sc("models-fp8-get-quant-method", "models-quant-config",
           steps=[step(iface="fp8-config.get-quant-method", as_="lin", inp={"layer_kind": "linear", "prefix": "model.layers.0.self_attn.qkv_proj"}),
                  step(iface="fp8-config.get-quant-method", as_="ign", inp={"layer_kind": "linear", "prefix": "lm_head", "ignored_layers": ["lm_head"]}),
                  step(iface="fp8-config.get-quant-method", as_="moe", inp={"layer_kind": "routed_experts", "prefix": "model.layers.0.mlp.experts"}),
                  step(iface="fp8-config.get-quant-method", as_="att", inp={"layer_kind": "attention", "prefix": "model.layers.0.self_attn.attn"}),
                  step(iface="fp8-config.get-quant-method", as_="oth", inp={"layer_kind": "other", "prefix": "model.norm"})],
           expect=["steps.lin.result.value.quant_method == 'Fp8LinearMethod' && steps.ign.result.value.quant_method == 'UnquantizedLinearMethod'",
                   "steps.moe.result.value.quant_method == 'Fp8MoEMethod' && steps.att.result.value.quant_method == 'Fp8KVCacheMethod'",
                   "steps.oth.result.value.quant_method == 'none'"]),
    ]
    # ------------------------------------------------------------------ quant config
    L += [
        sc("models-quant-config-fp8-block", "models-quant-config",
           expect=["result.ok && result.value.method == 'fp8_block' && calls['fp8-config.from-config'] == 1"]),
        sc("models-quant-config-unset", "models-quant-config", input={"quantization": ""},
           expect=["!result.ok && result.error.message == 'Model quantization method is not specified in the config.'"]),
        sc("models-quant-config-online-shorthand", "models-quant-config",
           steps=[step(iface="weight-utils.get-quant-config", as_="q", inp={"quantization": "fp8_per_tensor"})],
           expect=["steps.q.result.ok && steps.q.result.value.config_cls == 'OnlineQuantizationConfig' && calls['fp8-config.from-config'] == 0"]),
        sc("models-quant-config-no-file", "models-quant-config",
           steps=[step(iface="weight-utils.get-quant-config", as_="q", inp={"quantization": "awq"})],
           expect=["!steps.q.result.ok && steps.q.result.error.message == 'Cannot find the config file for awq'"]),
        sc("models-quant-config-other-method", "models-quant-config",
           input={"quantization": "compressed-tensors", "hf_quant_config": {"quant_method": "compressed-tensors"}},
           expect=["result.ok && result.value.config_cls == 'CompressedTensorsConfig' && calls['fp8-config.from-config'] == 0"]),
        sc("models-quant-config-fp8-refusals", "models-quant-config",
           steps=[step(iface="fp8-config.from-config", as_="online", inp={"quant_method": "int8", "activation_scheme": "dynamic"}),
                  step(iface="fp8-config.from-config", as_="scheme", inp={"quant_method": "fp8", "activation_scheme": "per_token"}),
                  step(iface="fp8-config.from-config", as_="dims", inp={"quant_method": "fp8", "activation_scheme": "dynamic", "weight_block_size": [128]})],
           expect=["!steps.online.result.ok && steps.online.result.error.message.contains('fp8_per_tensor')",
                   "!steps.scheme.result.ok && steps.scheme.result.error.message == 'Unsupported activation scheme per_token'",
                   "!steps.dims.result.ok && steps.dims.result.error.message.contains('must have 2 dimensions')"]),
    ]
    # ------------------------------------------------------------------ LoRA
    L += [
        sc("models-lora-add-then-list", "models-lora-add-adapter", state=ADAPTER,
           steps=[step("models-lora-add-adapter", as_="add"), step("models-lora-list-adapters", as_="ls")],
           expect=["steps.add.result.ok && steps.add.result.value.loaded",
                   "steps.ls.result.value.registered == [1] && steps.ls.result.value.active == [1]",
                   "steps.ls.result.value.slots == [1]"]),
        sc("models-lora-add-existing-touches", "models-lora-add-adapter", state=ADAPTER,
           steps=[step("models-lora-add-adapter", as_="a1"), step("models-lora-add-adapter", as_="a2"), step("models-lora-list-adapters", as_="ls")],
           expect=["steps.a2.result.ok && steps.a2.result.value.loaded",
                   "steps.ls.result.value.registered == [1] && steps.ls.result.value.active == [1]"]),
        sc("models-lora-load-inplace", "models-lora-add-adapter", state=ADAPTER,
           steps=[step("models-lora-add-adapter", as_="a1"),
                  step("models-lora-add-adapter", as_="a2", inp={"load_inplace": True}), step("models-lora-list-adapters", as_="ls")],
           # the in-place reload re-reads the adapter (the reload path is this case's point)
           expect=["calls['peft-helper.from-local-dir'] == 2",
                   "steps.ls.result.value.registered == [1] && steps.ls.result.value.slots == [1]"]),
        sc("models-lora-not-found", "models-lora-add-adapter", state=ADAPTER, input=lora(7, "missing-lora"),
           expect=["!result.ok && result.error.code == 'lora-adapter-not-found-error'"]),
        sc("models-lora-rank-too-high", "models-lora-add-adapter", state=ADAPTER, input=lora(3, "big-lora"),
           expect=["!result.ok && result.error.code == 'value-error' && result.error.message == 'LoRA rank 64 is greater than max_lora_rank 16.'"]),
        sc("models-lora-bias-refused", "models-lora-add-adapter", state=ADAPTER, input=lora(4, "bias-lora"),
           expect=["!result.ok && result.error.message == 'Adapter bias is not supported.'"]),
        sc("models-lora-cpu-cache-evicts-oldest", "models-lora-add-adapter", state=ADAPTER,
           steps=[step("models-lora-add-adapter", as_="a1"), step("models-lora-add-adapter", as_="a2", inp=lora(2, "chat-lora")),
                  step("models-lora-list-adapters", as_="ls")],
           expect=["steps.a2.result.ok && steps.ls.result.value.registered == [2]",
                   "steps.ls.result.value.active == [2] && steps.ls.result.value.slots == [2]"]),
        sc("models-lora-gpu-slots-lru", "models-lora-add-adapter", state=ADAPTER, config={"max-cpu-loras": 2},
           steps=[step("models-lora-add-adapter", as_="a1"), step("models-lora-add-adapter", as_="a2", inp=lora(2, "chat-lora")),
                  step("models-lora-list-adapters", as_="ls")],
           expect=["steps.ls.result.value.registered == [1, 2] && steps.ls.result.value.active == [2]",
                   "steps.ls.result.value.slots == [2]"]),
        sc("models-lora-set-active-two", "models-lora-set-active-adapters", state=ADAPTER, config={"max-loras": 2, "max-cpu-loras": 2},
           steps=[step("models-lora-set-active-adapters", as_="set", inp={"requests": [lora(1, "sql-lora"), lora(2, "chat-lora")]}),
                  step("models-lora-list-adapters", as_="ls")],
           expect=["steps.set.result.ok && steps.ls.result.value.active == [1, 2]",
                   "steps.ls.result.value.slots == [1, 2]"]),
        sc("models-lora-set-active-too-many", "models-lora-set-active-adapters", state=ADAPTER,
           input={"requests": [lora(1, "sql-lora"), lora(2, "chat-lora")]},
           expect=["!result.ok && result.error.code == 'runtime-error' && result.error.message.contains('GPU LoRA slots (1)')"]),
        sc("models-lora-no-free-slot", "models-lora-add-adapter", state=dict(ADAPTER, **{"lru-cache-lora-model-manager": {"slots": [9], "active": []}}),
           steps=[step("models-lora-add-adapter", as_="add"), step("models-lora-list-adapters", as_="ls")],
           expect=["!steps.add.result.ok && steps.add.result.error.message == 'No free lora slots'",
                   "steps.ls.result.value.registered == [1] && steps.ls.result.value.active == []"]),
        sc("models-lora-remove-missing", "models-lora-list-adapters",
           steps=[step(iface="lru-cache-lora-model-manager.remove-adapter", as_="rm", inp={"adapter_id": 5}), step("models-lora-list-adapters", as_="ls")],
           expect=["steps.rm.result.ok && !steps.rm.result.value.removed && steps.ls.result.value.registered == []"]),
        sc("models-lora-linear-sync", "models-lora-linear",
           expect=["result.ok && result.value.path == 'sync'",
                   "trace.exists(e, e.type == 'call.start' && e.interface == 'lora-shrink-op.lora-shrink') && calls['lora-expand-op.lora-expand'] == 1"]),
        sc("models-lora-linear-no-lora-tokens", "models-lora-linear", input={"any_lora": False},
           expect=["result.ok && calls['lora-shrink-op.lora-shrink'] == 1",
                   "!trace.exists(e, e.type == 'note' && e.title == 'Triton kernel _lora_shrink_kernel')"]),
        sc("models-lora-linear-dual-stream", "models-lora-linear", config={"vllm-lora-enable-dual-stream": True},
           expect=["result.ok && result.value.path == 'async' && calls['base-linear-layer-with-lora.lora-linear-async'] == 1",
                   "trace.exists(e, e.type == 'call.end' && e.interface == 'base-linear-layer-with-lora.apply' && e.output.path == 'async')"]),
    ]
    # ------------------------------------------------------------------ weight cache daemon
    L += [
        sc("models-weight-cache-serve-loop", "models-weight-cache-serve",
           expect=["passes.size() == 3 && passes.all(p, p.result.ok && p.result.value.memory_bytes == 16060522496)",
                   "calls['weight-cache-daemon.handle-connection'] == 3"]),
        sc("models-weight-cache-release-then-get-state", "models-weight-cache-serve",
           steps=[step(iface="weight-cache-daemon.serve-forever", as_="rel", inp={"cmd": "release"}),
                  step(iface="weight-cache-daemon.serve-forever", as_="st", inp={"cmd": "get_state", "cache_config": {"model": M8, "tp_size": 1}}),
                  step(iface="weight-cache-daemon.serve-forever", as_="mem", inp={"cmd": "get_memory"})],
           expect=["steps.rel.result.value.status == 'ok' && !state['weight-cache-daemon@rank0'].weights_held",
                   "steps.st.result.value.message == 'Weights were released' && steps.mem.result.value.memory_bytes == 0"]),
        sc("models-weight-cache-get-state-variants", "models-weight-cache-serve",
           steps=[step(iface="weight-cache-daemon.serve-forever", as_="ok", inp={"cmd": "get_state", "cache_config": {"model": M8, "tp_size": 1}}),
                  step(iface="weight-cache-daemon.serve-forever", as_="mm", inp={"cmd": "get_state", "cache_config": {"model": M8, "tp_size": 2}}),
                  step(iface="weight-cache-daemon.handle-get-state", as_="nocfg", inp={"cmd": "get_state"}),
                  step(iface="weight-cache-daemon.handle-connection", as_="unk", inp={"cmd": "reload"}),
                  step(iface="weight-cache-daemon.serve-forever", as_="peer", inp={"cmd": "get_memory", "peer_is_owner": False})],
           expect=["steps.ok.result.value.status == 'ok' && steps.mm.result.value.status == 'mismatch' && steps.mm.result.value.fields == ['tp_size']",
                   "steps.nocfg.result.value.message == 'Missing cache_config' && steps.unk.result.value.message == 'Unknown command reload'",
                   "steps.peer.result.value.status == 'error' && ctx.daemon_last_status == 'mismatch'"]),
    ]
    # ------------------------------------------------------------------ in-build oracle
    L += [
        sc("oracle-build-models-layers-1", "models-registry-inspect",
           description="tests/models/language/pooling/test_jina_reranker_v3.py::test_offline, the part at model level: "
                       "vllm_runner(runner='pooling') must resolve jina-reranker-v3's JinaForRanking to a pooling model class. "
                       "Score values and embedding size are untranslatable (numerics).",
           steps=[step("models-registry-inspect", as_="info", inp={"architectures": ["JinaForRanking"]}),
                  step("models-registry-resolve", as_="cls", inp={"architectures": ["JinaForRanking"]})],
           expect=["steps.info.result.ok && steps.info.result.value.is_pooling_model && !steps.info.result.value.is_text_generation_model",
                   "steps.cls.result.value.module == 'jina' && steps.cls.result.value.class_name == 'JinaForRanking'",
                   "'JinaForRanking' in state['model-registry@rank0'].modelinfo_cache"]),
        sc("oracle-build-models-layers-2", "models-registry-inspect",
           description="tests/models/language/pooling_mteb_test/test_nomic.py::test_embed_models_mteb, the part at model level: "
                       "NomicBertModel resolves to bert_with_rope.NomicBertModel, an embedding (pooling) model. MTEB scores, "
                       "pooler type and attn type checks are untranslatable or belong to ModelConfig.",
           steps=[step("models-registry-inspect", as_="info", inp={"architectures": ["NomicBertModel"]}),
                  step("models-registry-resolve", as_="cls", inp={"architectures": ["NomicBertModel"]})],
           expect=["steps.info.result.ok && steps.info.result.value.is_pooling_model",
                   "steps.cls.result.value.module == 'bert_with_rope' && steps.cls.result.value.table == 'embedding'",
                   "'NomicBertModel' in state['model-registry@rank0'].modelinfo_cache"]),
    ]
    def em(ep, rank, e, strat="round_robin", as_=None):
        return step(iface="expert-map-manager.determine-expert-map", as_=as_ or f"e{e}_r{rank}",
                    inp={"ep_size": ep, "ep_rank": rank, "global_num_experts": e, "expert_placement_strategy": strat})
    L += [
        sc("oracle-build-models-layers-4", "models-mixtral-forward",
           description="tests/distributed/test_expert_placement.py::test_expert_placement_various_sizes (assigned by decision 14): "
                       "round_robin placement for divisible and non-divisible expert counts on 2 and 4 EP ranks.",
           steps=[em(4, r, 18) for r in range(4)] + [em(2, r, 9) for r in range(2)] + [em(4, 1, 8), em(4, 0, 33)],
           expect=["steps.e18_r0.result.value.local_num_experts == 5 && steps.e18_r1.result.value.local_num_experts == 5 && steps.e18_r2.result.value.local_num_experts == 4 && steps.e18_r3.result.value.local_num_experts == 4",
                   "steps.e18_r1.result.value.expert_map[1] == 0 && steps.e18_r1.result.value.expert_map[5] == 1 && steps.e18_r1.result.value.expert_map[17] == 4 && steps.e18_r1.result.value.expert_map[0] == -1",
                   "steps.e18_r3.result.value.expert_map.filter(x, x >= 0) == [0, 1, 2, 3] && size(steps.e18_r3.result.value.expert_map) == 18",
                   "steps.e9_r0.result.value.local_num_experts == 5 && steps.e9_r1.result.value.local_num_experts == 4 && steps.e9_r1.result.value.expert_map[7] == 3",
                   "steps.e8_r1.result.value.expert_map == [-1, 0, -1, -1, -1, 1, -1, -1] && steps.e33_r0.result.value.local_num_experts == 9"]),
        sc("models-expert-map-linear-and-refusals", "models-mixtral-forward",
           steps=[em(4, 1, 10, "linear", "lin"), em(1, 0, 8, "linear", "one"), em(2, 0, 8, "random", "bad")],
           expect=["steps.lin.result.value.local_num_experts == 3 && steps.lin.result.value.expert_map == [-1, -1, -1, 0, 1, 2, -1, -1, -1, -1]",
                   "steps.one.result.value.local_num_experts == 8 && steps.one.result.value.expert_map == null",
                   "!steps.bad.result.ok && steps.bad.result.error.message == 'Unsupported expert placement strategy random'"]),
        sc("models-seed-profile-run", "models-llama-forward", fixtures=("tp1-llama-8b", "models-layers-seed"),
           input={"num_tokens": 2048, "num_reqs": 0, "is_profile": True},
           expect=["result.ok && calls['flash-attention-impl.do-kv-cache-update'] == 0",
                   "trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attention-impl.forward' && e.input.profiling_run)"]),
        sc("models-seed-runner-metadata", "models-llama-forward", fixtures=("tp1-llama-8b", "models-layers-seed"),
           input={"num_tokens": 3, "num_reqs": 2, "attn_metadata": {"num_actual_tokens": 3, "num_reqs": 2, "max_query_len": 2, "max_seq_len": 40,
                                                                    "query_lens": [2, 1], "seq_lens": [40, 24], "block_table": [[0, 1, 2], [3, 4]],
                                                                    "slot_mapping": [38, 39, 71]}},
           expect=["result.ok",
                   "trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attention-impl.do-kv-cache-update' && e.input.slot_mapping == [38, 39, 71])",
                   "trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attention-impl.forward' && e.input.metadata.block_table == [[0, 1, 2], [3, 4]])"]),
        sc("models-seed-forward", "models-llama-forward", fixtures=("tp1-llama-8b", "models-layers-seed"),
           expect=["result.ok && result.value.num_layers == 32 && calls['model-loader.get-model'] == 0",
                   "trace.exists(e, e.type == 'call.start' && e.interface == 'flash-attention-impl.forward')"]),
    ]
    EP = {"enable-expert-parallel": True, "enable-eplb": True, "num-redundant-experts": 4}
    L2P = {"logical_to_physical_map": [[0, 8], [1, 9], [2, 10], [3, 11], [4], [5], [6], [7]],
           "logical_replica_count": [2, 2, 2, 2, 1, 1, 1, 1]}
    eplb_set = [step(iface="mixtral-for-causal-lm.set-eplb-state", as_=f"eplb_{r}", inp=L2P, on=r) for r in RANKS]
    NV = "nvidia/Llama-3.1-8B-Instruct-FP4"
    NV_HF = dict(LLAMA8, weights_bytes=5700000000, quantization_config={"quant_method": "modelopt", "quantization": {"quant_algo": "NVFP4"}})
    def ov(as_, cfg):
        return step(iface="model-opt-quant-config-base.override-quantization-method", as_=as_, inp={"hf_quant_cfg": cfg})
    L += [
        sc("models-eplb-register-then-forward", "models-eplb-register", fixtures=("tp4-llama-70b",), state=MIX_STATE, config=EP,
           steps=load_all(MIX, MIXTRAL) + eplb_set + on_all("models-mixtral-forward", as_="fwd"),
           expect=["steps.eplb_rank0.result.value.registered_layers == 32 && state['mixtral-for-causal-lm@rank0'].eplb_registered",
                   "state['mixtral-for-causal-lm@rank0'].cfg.num_physical_experts == 12 && state['mixtral-for-causal-lm@rank0'].cfg.num_local_physical_experts == 3 && state['mixtral-for-causal-lm@rank0'].cfg.moe_tp == 1",
                   "steps.fwd_rank3.result.ok && calls['fused-top-k-router.eplb-map-to-physical-and-record'] == 4",
                   "state['fused-top-k-router@rank2'].eplb.recorded_slots == 32 && ctx.moe_local_experts == 3",
                   "calls['expert-map-manager.determine-expert-map'] == 4"]),
        sc("models-eplb-disabled-noop", "models-eplb-register", fixtures=("tp4-llama-70b",), state=MIX_STATE,
           config={"enable-expert-parallel": True},
           steps=load_all(MIX, MIXTRAL) + eplb_set + on_all("models-mixtral-forward", as_="fwd"),
           expect=["steps.eplb_rank0.result.value.registered_layers == 0 && !state['mixtral-for-causal-lm@rank0'].eplb_registered",
                   "steps.fwd_rank0.result.ok && calls['fused-top-k-router.eplb-map-to-physical-and-record'] == 0",
                   "!has(state['fused-top-k-router@rank0'].eplb) && state['mixtral-for-causal-lm@rank0'].cfg.ep_size == 4"]),
        sc("models-eplb-not-loaded", "models-eplb-register",
           expect=["!result.ok && result.error.code == 'attribute-error' && calls['fused-top-k-router.set-eplb-layer-state'] == 0"]),
        sc("models-eplb-missing-map", "models-eplb-register", fixtures=("tp4-llama-70b",), state=MIX_STATE, config=EP,
           steps=load_all(MIX, MIXTRAL) + [step(iface="mixtral-for-causal-lm.set-eplb-state", as_=f"e_{r}", inp={"logical_to_physical_map": [], "logical_replica_count": []}, on=r) for r in RANKS]
                 + on_all("models-mixtral-forward", as_="fwd"),
           expect=["!steps.fwd_rank0.result.ok && steps.fwd_rank0.result.error.message == 'EPLB requires logical_to_physical_map != None'",
                   "state['fused-top-k-router@rank0'].eplb.recorded_slots == 0"]),
        sc("models-eplb-update-physical-experts", "models-eplb-register", fixtures=("tp4-llama-70b",), state=MIX_STATE, config=EP,
           steps=load_all(MIX, MIXTRAL)
                 + [step(iface="mixtral-for-causal-lm.update-physical-experts-metadata", as_="up", inp={"num_physical_experts": 12, "num_local_physical_experts": 3}),
                    step(iface="mixtral-for-causal-lm.update-physical-experts-metadata", as_="bad", inp={"num_physical_experts": 16, "num_local_physical_experts": 4})],
           expect=["steps.up.result.ok && steps.up.result.value.local_num_experts == 3 && state['mixtral-for-causal-lm@rank0'].cfg.num_redundant_experts == 4",
                   "!steps.bad.result.ok && steps.bad.result.error.code == 'assertion-error'"]),
        sc("models-quant-modelopt-detection", "models-quant-config",
           steps=[ov("nv", {"quant_method": "modelopt", "quantization": {"quant_algo": "NVFP4"}}),
                  ov("fp8", {"quant_method": "modelopt", "quant_algo": "fp8"}),
                  ov("mx", {"quant_method": "modelopt", "quantization": {"quant_algo": "MXFP8"}}),
                  ov("mixed", {"quant_method": "modelopt", "quantization": {"quant_algo": "MIXED_PRECISION"}}),
                  ov("other", {"quant_method": "fp8", "activation_scheme": "dynamic"}),
                  ov("unk", {"quant_method": "modelopt", "quant_algo": "INT4_AWQ"})],
           expect=["steps.nv.result.value.quantization == 'modelopt_fp4' && steps.fp8.result.value.quantization == 'modelopt'",
                   "steps.mx.result.value.quantization == 'modelopt_mxfp8' && steps.mixed.result.value.quantization == 'modelopt_mixed'",
                   "steps.other.result.value.quantization == null && steps.unk.result.value.quantization == null && steps.unk.result.value.quant_algo == 'INT4_AWQ'"]),
        sc("models-get-model-nvfp4-then-forward", "models-get-model", state={"hf-hub": {"models": {NV: NV_HF}}},
           steps=[step("models-get-model", as_="load", inp={"model": NV, "hf_config": NV_HF}), step("models-llama-forward", as_="fwd")],
           expect=["steps.load.result.ok && steps.load.result.value.quant == 'modelopt_fp4'",
                   "ctx.modelopt_linear_bytes_per_weight == 0.5",
                   "steps.fwd.result.ok && calls['model-opt-linear-method.apply'] == 4 && calls['fp8-linear-method.apply'] == 0"]),
        sc("models-lora-pin-protects-from-eviction", "models-lora-add-adapter", state=ADAPTER, config={"max-cpu-loras": 2, "max-loras": 2},
           steps=[step("models-lora-add-adapter", as_="a1"),
                  step(iface="lru-cache-worker-lora-manager.pin-adapter", as_="pin", inp={"lora_int_id": 1}),
                  step("models-lora-add-adapter", as_="a2", inp=lora(2, "chat-lora")),
                  step("models-lora-add-adapter", as_="a3", inp=lora(3, "sql-lora")),
                  step("models-lora-list-adapters", as_="ls")],
           expect=["steps.pin.result.ok && steps.a3.result.ok",
                   "steps.ls.result.value.registered == [1, 3] && steps.ls.result.value.pinned == [1]",
                   "steps.ls.result.value.active == [1, 3]"]),
        sc("models-lora-pinned-gpu-slot", "models-lora-add-adapter", state=ADAPTER, config={"max-cpu-loras": 2},
           steps=[step("models-lora-add-adapter", as_="a1"),
                  step(iface="lru-cache-worker-lora-manager.pin-adapter", as_="pin", inp={"lora_int_id": 1}),
                  step("models-lora-add-adapter", as_="a2", inp=lora(2, "chat-lora")), step("models-lora-list-adapters", as_="ls")],
           expect=["!steps.a2.result.ok && steps.a2.result.error.code == 'runtime-error'",
                   "steps.ls.result.value.active == [1]"]),
        sc("models-lora-all-pinned", "models-lora-add-adapter", state=ADAPTER,
           steps=[step("models-lora-add-adapter", as_="a1"),
                  step(iface="lru-cache-worker-lora-manager.pin-adapter", as_="pin", inp={"lora_int_id": 1}),
                  step("models-lora-add-adapter", as_="a2", inp=lora(2, "chat-lora")),
                  step("models-lora-list-adapters", as_="ls")],
           expect=["!steps.a2.result.ok && steps.a2.result.error.message == 'All items are pinned, cannot remove oldest from the cache.'",
                   "steps.ls.result.value.registered == [1] && steps.ls.result.value.pinned == [1]"]),
        sc("models-lora-pin-unregistered-and-remove", "models-lora-add-adapter", state=ADAPTER,
           steps=[step(iface="lru-cache-worker-lora-manager.pin-adapter", as_="pin", inp={"lora_int_id": 9}),
                  step("models-lora-add-adapter", as_="a1"),
                  step(iface="lru-cache-worker-lora-manager.remove-adapter", as_="rm", inp={"lora_int_id": 1}),
                  step("models-lora-list-adapters", as_="ls")],
           expect=["!steps.pin.result.ok && steps.pin.result.error.message == 'Pinning failed. LoRA 9 is not registered.'",
                   "steps.rm.result.value.removed && steps.ls.result.value.registered == [] && steps.ls.result.value.slots == [null]"]),
    ]
    QW = {"model": "Qwen/Qwen2-VL-7B-Instruct", "architectures": ["Qwen2VLForConditionalGeneration"]}
    def mmp(as_, **kw):
        return step("models-multimodal-process", as_=as_, inp=kw)
    L += [
        sc("models-multimodal-qwen2-vl", "models-multimodal-process",
           expect=["result.ok && result.value.num_prompt_tokens == 261 && result.value.placeholders.image == 256",
                   "result.value.placeholders.size() == 1",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'model-registry.resolve-model-cls').size() == 1"]),
        sc("models-multimodal-limits", "models-multimodal-process", config={"limit-mm-per-prompt": {"image": 2}},
           steps=[mmp("two", mm_counts={"image": 2, "video": 1}), mmp("three", mm_counts={"image": 3}),
                  mmp("llava_video", model="llava-hf/llava-1.5-7b-hf", architectures=["LlavaForConditionalGeneration"], mm_counts={"video": 1})],
           expect=["steps.two.result.ok && steps.two.result.value.placeholders.video == 1024",
                   "!steps.three.result.ok && steps.three.result.error.message == 'At most 2 image(s) may be provided in one prompt. Set `--limit-mm-per-prompt` to increase this limit.'",
                   "!steps.llava_video.result.ok && steps.llava_video.result.error.message == 'At most 0 video(s) may be provided in one prompt.'",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'model-registry.resolve-model-cls').size() == 2"]),
        sc("models-multimodal-refusals", "models-multimodal-process",
           steps=[mmp("text", model="meta-llama/Llama-3.1-8B-Instruct", architectures=["LlamaForCausalLM"]),
                  mmp("noproc", model="google/paligemma-3b-mix-224", architectures=["PaliGemmaForConditionalGeneration"]),
                  mmp("badkey", mm_counts={"hologram": 1}),
                  mmp("embeds", embeds=True)],
           expect=["!steps.text.result.ok && steps.text.result.error.message == 'meta-llama/Llama-3.1-8B-Instruct is not a multimodal model'",
                   "!steps.noproc.result.ok && steps.noproc.result.error.message.contains('has no registered multimodal processor')",
                   "!steps.badkey.result.ok && steps.badkey.result.error.message == 'Unsupported modality: hologram'",
                   "!steps.embeds.result.ok && steps.embeds.result.error.message.contains('--enable-mm-embeds')",
                   "trace.filter(e, e.type == 'call.start' && e.interface == 'model-registry.resolve-model-cls').size() == 3"]),
        sc("models-multimodal-embeds-enabled", "models-multimodal-process", config={"enable-mm-embeds": True}, input={"embeds": True},
           expect=["result.ok && result.value.placeholders.image == 256 ", "trace.exists(e, e.type == 'call.end' && e.interface == 'model-registry.resolve-model-cls')"]),
    ]
    def pv(as_, shapes, sizes):
        return step(iface="phi3v-image-pixel-inputs.validate", as_=as_, inp={"pixel_values": shapes, "image_sizes": sizes})
    def mr(as_, toks, feats):
        return step(iface="ernie45-vl-moe-for-conditional-generation.get-mrope-input-positions", as_=as_,
                    inp={"input_tokens": toks, "mm_features": feats, "spatial_conv_size": 2, "temporal_conv_size": 2})
    L += [
        sc("models-tensor-schema-validation", "models-multimodal-process",
           steps=[pv("ok", [[16, 3, 32, 32], [32, 3, 32, 32], [64, 3, 32, 32]], [3, 2]), pv("empty", [], [0, 2]),
                  pv("chan", [[16, 4, 32, 32]], [1, 2]), pv("bn", [[16, 3, 32, 32], [16, 3, 32, 32]], [3, 2])],
           expect=["steps.ok.result.ok && steps.ok.result.value.bn == 3",
                   "!steps.empty.result.ok && steps.empty.result.error.message == 'pixel_values is an empty sequence'",
                   "!steps.chan.result.ok && steps.chan.result.error.message.contains('expected 3, got 4')",
                   "!steps.bn.result.ok && steps.bn.result.error.message.contains('expected')"]),
        sc("models-ernie-mrope-positions", "models-multimodal-process",
           steps=[mr("text", [11, 12, 13, 14, 15], []),
                  mr("mixed", [10, 20, 21, 22, 23, 30, 31, 40, 41, 50, 51],
                     [{"modality": "video", "offset": 7, "length": 2, "grid_thw": [2, 4, 2]}, {"modality": "image", "offset": 1, "length": 4, "grid_thw": [1, 4, 4]}]),
                  mr("audio", [1, 2, 3], [{"modality": "audio", "offset": 1, "length": 1, "grid_thw": [1, 2, 2]}])],
           expect=["steps.text.result.value.positions == [[0, 1, 2, 3, 4], [0, 1, 2, 3, 4], [0, 1, 2, 3, 4]] && steps.text.result.value.delta == 0",
                   "steps.mixed.result.value.positions == [[0, 1, 1, 1, 1, 3, 4, 5, 5, 7, 8], [0, 1, 1, 2, 2, 3, 4, 5, 6, 7, 8], [0, 1, 2, 1, 2, 3, 4, 5, 5, 7, 8]]",
                   "!steps.audio.result.ok && steps.audio.result.error.message == 'Unsupported modality: audio'"]),
    ]
    return L


def seed():
    return {"id": "models-layers-seed",
            "summary": "models-layers' share of the merged worlds: Llama-3.1-8B already loaded on every rank (as load_model leaves it), plus the hub and disk entries the area's scenarios use (Mixtral, an FP8 block checkpoint, LoRA adapters).",
            "state": {
                "llama-for-causal-lm": {"loaded": True, "model": M8, "tp_size": 1, "quant": "unquantized", "rope": "RotaryEmbedding",
                                        "weights_bytes_per_rank": 16060522496,
                                        "cfg": {"hidden_size": 4096, "num_heads": 32, "num_kv_heads": 8, "head_dim": 128, "intermediate_size": 14336,
                                                "num_layers": 32, "vocab_size": 128256, "bytes_per_weight": 2}},
                "hf-hub": {"models": {MIX: MIXTRAL, FP8: FP8_HF}},
                "local-disk": ADAPTER["local-disk"]}}


# Scenarios whose expectations read the effect back through steps.* only; hollow-lint
# wants the trace named: assert the read-back call itself completed.
READBACK = {
    "lru-cache-worker-lora-manager.list-adapters": ["models-lora-add-existing-touches", "models-lora-add-then-list", "models-lora-all-pinned",
        "models-lora-cpu-cache-evicts-oldest", "models-lora-gpu-slots-lru", "models-lora-load-inplace", "models-lora-no-free-slot",
        "models-lora-pin-protects-from-eviction", "models-lora-pin-unregistered-and-remove", "models-lora-pinned-gpu-slot",
        "models-lora-set-active-two"],
    "llama-for-causal-lm.forward": ["models-get-model-fp8-block-then-forward", "models-get-model-fp8-static-block-refused",
        "models-get-model-heads-not-divisible", "models-get-model-invalid-quantization", "models-get-model-kv-heads-not-divisible",
        "models-get-model-non-silu", "models-get-model-nvfp4-then-forward", "models-get-model-tp4-70b"],
    "mixtral-for-causal-lm.forward": ["models-mixtral-forward-tp4", "models-mixtral-tp3-refused"],
}


def with_readback(L):
    for iface, ids in READBACK.items():
        for sc_ in L:
            if sc_["id"] in ids:
                sc_["expect"] = sc_["expect"] + [f"trace.exists(e, e.type == 'call.end' && e.interface == '{iface}')"]
    return L


def extra():
    comps, ifaces = boundaries()
    return {"components": comps, "interfaces": ifaces, "schemas": schemas(), "configs": configs(),
            "flows": flows(), "scenarios": with_readback(scenario_list()), "fixtures": [seed()]}

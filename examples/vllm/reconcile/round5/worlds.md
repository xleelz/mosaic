# Round 5: model-type worlds

The coordinator added four worlds to `fixtures.yaml` and the profile, so `worlds.yaml` now has their
`full-*` versions. Each has a smoke scenario, `fixture-smoke-<world>`, and all four pass in the merged check.

| World | Deployment |
|---|---|
| `moe-mixtral-8x7b-tp2-ep` | 2 x H100 (rank0, rank1), `mistralai/Mixtral-8x7B-Instruct-v0.1` as `mixtral-8x7b`, TP 2, `--enable-expert-parallel`, max_model_len 32768 |
| `vl-qwen2-vl-7b` | 1 x H100, `Qwen/Qwen2-VL-7B-Instruct` as `qwen2-vl-7b`, multimodal defaults, `model-is-multimodal: true`, the stop_sign.jpg asset in `vllm-public-assets-s3` |
| `fp8-llama-3-8b` | 1 x H100, `neuralmagic/Meta-Llama-3-8B-Instruct-FP8-KV` (quant_method fp8, static) as `llama-3-8b-fp8`, kv_cache_dtype auto, max_model_len 8192 |
| `fp8-llama-3-8b-kv-fp8` | `fp8-llama-3-8b` with `kv-cache-dtype: fp8` |

Each world seeds `gpu-model-runner.model` (and `max_model_len`) with its checkpoint, so `wr-load-model`
loads that model. The worlds put their own models in `hf-hub.models`.

## Gaps for the owning areas

The coordinator left these alone, because fixing them means editing a fragment.

### config-platform
- **The MoE world's host is overridden.** `config-platform-seed` sets `platforms.host` to one GPU, and
  it merges after the world. So in `full-moe-mixtral-8x7b-tp2-ep`, TP 2 fails ParallelConfig's device
  check (World size larger than the GPUs on this node). Add a `variant_of: moe-mixtral-8x7b-tp2-ep` fixture
  with `device_count: 2, nvml_gpu_count: 2`, as `engine-core-tp4-llama-70b-host` does for tp4. Until
  then, the smoke scenario sets the host itself.
- **The flow ignores `config['model']`.** The `config-create-engine-config` entry hard-codes
  `model: meta-llama/Llama-3.1-8B-Instruct`, so every world but tp1 has to pass
  `input: {model: "= config['model']"}`. Read the config instead (arg_utils.py:474).
- **`ConfigEngineArgs` has no `kv_cache_dtype`** (arg_utils.py:500, cache.py:122), so the resolved
  `cache_config` doesn't show the fp8 KV variant.
- **The ModelConfig result exposes only `is_moe`.** It lacks `num_experts` and
  `num_experts_per_tok` (model.py:1686-1690), and `vision_config` details beyond whether
  `multimodal_config` is set.

### models-layers
- **The merged worlds always start with Llama loaded.** `models-layers-seed` sets
  `llama-for-causal-lm` to loaded with Llama-3.1-8B in every merged world, including the MoE, VL and FP8
  worlds. Add `variant_of` fixtures, or leave the loaded model to `wr-load-model`.
- **Qwen2-VL has no model component.** `initialize-model` resolves `Qwen2VLForConditionalGeneration`
  but builds no component, so there's no vision encoder and no M-RoPE forward
  (vllm/model_executor/models/qwen2_vl.py).
- **Nobody defines `model-is-multimodal`.** serving-api's boundary reference names models-layers as
  the owner, but no fragment defines it, and nothing derives it from the checkpoint
  (model.py:1981-1982). The VL world sets it by hand.
- **Remote images can't be fetched.** `MediaConnector.fetch_image` / http `image_url` fetching isn't
  modeled; `media-connector` only merges kwargs. VL scenarios have to send `data:` URLs.

### worker-runner
- **The forward always runs Llama.** The forward calls are hard-wired to `llama-for-causal-lm.forward`
  (the eager path at model_runner.py:2043-2044, and `cuda-graph-manager.run-pw-graph`). A chat request
  in the Mixtral world forwards through Llama on both ranks. Dispatch on the loaded architecture
  instead (`mixtral-for-causal-lm.forward` exists).
- **The KV page size ignores fp8.** `attn-utils.get-kv-cache-spec` computes the full-attention page size
  from the model's `dtype_bytes` and ignores `config['kv-cache-dtype']`. So `--kv-cache-dtype fp8`
  doesn't halve the page size or double the blocks (only the MLA path reads it).
- **The seed numbers are Llama-3.1-8B's.** `worker-runner-seed` gives 28,488 blocks and
  bytes_per_block 2097152 in every merged world. They're wrong for these worlds until
  `wr-determine-available-memory` runs.

### scheduler-kv
- **The encoder cache is never sized.** `encoder-cache-manager` starts with `cache_size: 0` in every
  world. The VL world should create it from
  `compute_mm_encoder_budget`: max(encoder_cache_size = max_num_batched_tokens, the largest
  item's tokens) (scheduler.py:303-304, encoder_cache_manager.py:356-361).
- **No config ids exist** for `max_num_encoder_input_tokens` or `encoder_cache_size`.
- **The block pool is Llama-sized.** `scheduler-kv-seed` gives `num_gpu_blocks: 28488`, the
  Llama-3.1-8B figure.

### serving-api
- **The renderer and tokenizer are Llama-3.1's in every world.** The chat template and word-level
  tokenizer are Llama-3.1 stand-ins whatever the served model is, so Qwen2-VL and Mixtral prompts
  are counted with Llama's special tokens.

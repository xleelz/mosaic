# Oracle 4: models-layers

Model: `examples/vllm/vllm.json` + scenarios in `oracle4/models-layers.yaml`. Code: vLLM v0.32.0
snapshot (5df63a72). The tests were read, never run. Paths below are relative to the snapshot.

| Test | Behavior | Scenario | Verdict | At fault / missing | Evidence |
|---|---|---|---|---|---|
| `tests/models/inkling/test_mm_towers.py:68` test_rmsnorm_gelu | The fused Inkling `rmsnorm_gelu` Triton kernel matches a PyTorch RMSNorm(+GELU) reference to within a few bf16 ulps (`vllm/models/inkling/nvidia/ops/mm_towers.py`) | (none) | untranslatable | kernel numerics | Only asserts elementwise tensor closeness (ulp tolerance). Below the model's level: kernels are latency models. |
| `tests/model_executor/test_flashinfer_autotune_warmup.py:55` test_flashinfer_autotune_token_counts_include_deferred_moe_limits | `_flashinfer_autotune_token_counts` returns `(max_num_batched_tokens, *enabled deferred-MoE finalize limits > 0, capped, de-duplicated)` = `(8192, 128)`, and FlashInfer autotune does one profile dummy run per count (`vllm/model_executor/warmup/kernel_warmup.py:314-339`, `:342-374`, called from `kernel_warmup` `:262-267`, which `gpu_worker.py:949` calls) | `oracle-models-layers-flashinfer-autotune-deferred-moe` | model-bug | models-layers: `kernel_warmup` / `flashinfer_autotune` missing; no deferred-MoE fields on `fused-moe-config` | Both TP ranks run `gpu-worker-impl.compile-or-warm-up-model` on the Mixtral world with max-num-batched-tokens 8192. The only `gpu-model-runner.dummy-run` is the compile-size run (8192, no `is_profile`). No 128-token autotune pass. No model entity cites `vllm/model_executor/warmup/**`, and `defer_moe_finalize_max_num_tokens` / `use_deferred_moe_finalize` appear nowhere. The test patches `MoERunner` with a fake; the scenario drives the real MoE world instead. |
| `tests/models/multimodal/pooling/test_embedding_gemma2.py:59` test_structure | EmbeddingGemma2's sliding layers are ENCODER_ONLY attention built with `per_layer_sliding_window = config.sliding_window + 1` (`_WINDOW_OFFSET`, `vllm/model_executor/models/embedding_gemma2.py:83,146-157`), so the impl's window is `(W-1, W-1) = (512, 512)` (`triton_attn.py:479-484`; the backend defaults to TRITON_ATTN, `models/config.py:293-305`) | `oracle-models-layers-embedding-gemma2-structure` | model-bug | models-layers: no EmbeddingGemma2 model (attention layers, window offset); `model-loader.get-model` returns no per-layer structure; attention has no `triton-attention-impl.init` | `model-loader.get-model` with an EmbeddingGemma2Model checkpoint loads without error, but the result has no layers or attention windows. `flash-attention-impl.init` has the right `(W-1, W-1)` encoder-only formula, but nothing builds the layers with W+1. The checkpoint path comes from `EG2_MODEL_PATH`, so the repo id `google/embeddinggemma-2` is a placeholder. |
| `tests/models/language/pooling/test_classification.py:24` test_models | `vllm_runner(model)` leaves `--runner auto`. `ModelConfig._get_default_runner_type` resolves `Qwen2ForSequenceClassification` to `pooling` (`vllm/config/model.py:1270-1316`), and `LLM.classify` returns one output per prompt (`vllm/entrypoints/pooling/offline.py:137-175`). The logits closeness to HF is numeric and not translated | `oracle-models-layers-classification-models` | model-bug | config-platform: `model-config.post-init` (runner auto never resolves to pooling); serving-api: `llm.encode` checks raw `config['runner']`, not the resolved runner_type | `create-engine-config` with runner auto gives `model_config.runner_type == 'generate'` (`vars.runner_type = input.runner == 'pooling' ? 'pooling' : 'generate'`). `llm.classify` then fails `value-error` "LLM.encode() is only supported for pooling models", but the code runs it. |
| `tests/model_executor/test_qwen_vl_triton_warmup.py:13` test_vision_warmup_calls_only_position_and_rotary_paths | `qwen_vl_triton_warmup -> _warm_vision` warms `fast_pos_embed_interpolate` and `apply_rotary_emb` of each Qwen3-VL vision tower on 4 grids ((1,16,16),(1,16,2),(1,2,16),(1,2,2) for merge 2). It never runs the tower forward, and it skips towers whose weights are on another device (`vllm/model_executor/warmup/qwen_vl_triton_warmup.py:21-60,111-117`; called from `kernel_warmup.py:195`) | `oracle-models-layers-qwen-vl-vision-warmup` | model-bug | models-layers: qwen_vl_triton_warmup missing; no Qwen3-VL architecture | `compile-or-warm-up-model` has no kernel-warmup step. With a Qwen3VLForConditionalGeneration runner the dummy run dispatches to `llama-for-causal-lm.forward`, which fails `attribute-error` (not loaded), because Qwen3-VL isn't modeled. There are no pos-embed or rotary warm calls. The test's FakeVisual/FakeAttention subclasses are mocks; the scenario uses the runner's model state instead. |
| `tests/models/language/pooling/test_multi_vector_retrieval.py:17` test_embed_models | BAAI/bge-m3 with `--runner pooling` and `PoolerConfig(task='token_embed')`: `LLM.encode(prompts, pooling_task='token_embed')` returns one per-token embedding output per prompt (`offline.py:137-175`, `conftest.py:1335-1337`). Closeness to HF is numeric | `oracle-models-layers-multi-vector-token-embed` | pass | — | 8 prompts give `num_outputs == 8` with `pooling_task == 'token_embed'`, through `llm.run-tiling-engine` and `llm-engine.add-request` with PoolingParams(task). `llm.supported_tasks` is seeded (the model doesn't derive it from the architecture). |
| `tests/models/language/pooling_mteb_test/test_baai.py:109` test_embed_models_mteb[BAAI/bge-base-en] | The config assertions of `mteb_test_embed_models` (`mteb_embed_utils.py:189-210`): the architecture is BertModel, seq_pooling_type CLS (BertEmbeddingModel `@default_pooling_type(seq_pooling_type="CLS")`, `bert.py:450`, applied at `config/model.py:782-785`), attn_type `encoder_only` (`model.py:2156-2162`), and neither prefix caching nor chunked prefill is supported (`model.py:2175-2185,2221-2232`). The MTEB score is numeric | `oracle-models-layers-baai-embed-mteb-config` | model-bug | config-platform: `model-config.post-init` reads `seq_pooling_type` and `attn_type` from the HF config.json instead of the registry's `_ModelInfo.default_seq_pooling_type` / `attn_type`; models-layers: `ModelsModelInfo` lacks `default_seq_pooling_type`, `default_tok_pooling_type` and `attn_type` | The architecture check passes. The model gives attn_type `decoder`, seq_pooling_type null, prefix caching supported (so `cache_config.enable_prefix_caching` defaults true) and chunked prefill supported. The code gives encoder_only, CLS, false, false. |

Counts: pass 1, model-bug 5, untranslatable 1, sim-gap 0, test-mismatch 0.

## Fix requests

### models-layers
1. **Kernel warmup** (`vllm/model_executor/warmup/kernel_warmup.py:162-290`). Add `kernel-warmup` with
   `flashinfer-autotune`. It runs when `kernel_config.enable_flashinfer_autotune` is not False,
   FlashInfer is present and the GPU is SM90 or newer. Token counts are `[max_num_batched_tokens] +
   [min(max, limit) for each MoE layer with use_deferred_moe_finalize and limit > 0]`, de-duplicated
   in order. Each count gets one `gpu-model-runner.dummy-run(num_tokens, skip_eplb, is_profile=true,
   randomize_inputs=true[, skip_attn])` inside `autotune(buckets, round_up=True)`. Add
   `use_deferred_moe_finalize` and `defer_moe_finalize_max_num_tokens` to `fused-moe-config`.
   worker-runner then calls it from `gpu-worker-impl.compile-or-warm-up-model` after the
   compile-size dummy runs (`gpu_worker.py:949`).
2. **Qwen-VL Triton warmup** (`vllm/model_executor/warmup/qwen_vl_triton_warmup.py`). Model `_warm_vision`
   and `_warm_mrope`, plus a Qwen3-VL architecture (or a vision-tower entity) whose
   `fast-pos-embed-interpolate` and `apply-rotary-emb` it calls once per grid. Skip it when the
   tower's weights are on another device.
3. **EmbeddingGemma2** (`vllm/model_executor/models/embedding_gemma2.py:83-157`). Add a model whose
   sliding layers build ENCODER_ONLY attention with `sliding_window + 1`, and expose the per-layer
   window, so `get-model` (or an attention-layer init) reports `(512, 512)`. attention also needs a
   `triton-attention-impl.init` with the same window rule (`triton_attn.py:479-484`).
4. **`ModelsModelInfo`** (`registry.py:860-900`). Add `default_seq_pooling_type`,
   `default_tok_pooling_type` and `attn_type`, and register BertModel -> BertEmbeddingModel (CLS)
   and XLMRobertaModel -> RobertaEmbeddingModel.

### config-platform
1. **`model-config.post-init` runner resolution** (`vllm/config/model.py:1270-1316`). `--runner auto` must
   resolve to pooling for a sentence-transformers checkpoint, for a registered pooling architecture,
   or for the `*ForSequenceClassification` / `*Model` suffix defaults. Today auto always becomes
   generate.
2. **`model-config.post-init` pooler config and attn_type** (`model.py:762-791, 2156-2166`). Take
   `seq_pooling_type` from the user's PoolerConfig, then sentence-transformers, then the registry's
   `default_seq_pooling_type`, not from config.json. attn_type is `encoder_only` when the model's
   default seq pooling is CLS or `hf_config.is_causal` is false.
3. **`engine-args.set-default-chunked-prefill-and-prefix-caching-args`**. Pass `seq_pooling_type` and
   `tok_pooling_type` to both `is-*-supported` calls. `model-config.is-prefix-caching-supported`
   should also refuse pooling decoders with MEAN/CLS seq pooling or STEP token pooling
   (`model.py:2233-2252`), as `is-chunked-prefill-supported` already does. This was seen while
   reading and isn't asserted by any sampled test.

### serving-api
1. **`llm.encode`** (`vllm/entrypoints/pooling/offline.py:137-175`). Check the resolved
   `model_config.runner_type`, not the raw `config['runner']` option. Also refuse classify and
   token_classify when they aren't in `supported_tasks`.

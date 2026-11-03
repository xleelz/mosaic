# Oracle: serving-api, engine-core, config-platform

Scenarios: `oracle/serving-engine.yaml`, run with
`go run ./internal/devtools/check -f examples/vllm/vllm.json -f examples/vllm/oracle/serving-engine.yaml --no-mocks --lint hollow -v`
(10 scenarios: 2 pass, 8 fail; hollow lint clean for this file). Code citations are against
vllm v0.32.0 (5df63a72).

| Test | Behavior | Scenario | Verdict | At fault / missing | Evidence |
|---|---|---|---|---|---|
| `tests/parser/cohere/test_structural_tags.py:163` (`test_structured_outputs_structural_tag_not_modified`) | `CohereCommandParser.adjust_request` leaves a request that already has `structured_outputs.structural_tag` unchanged (`vllm/parser/cohere_command.py:504-518`), called from `OnlineRenderer` render-chat (`vllm/renderers/online_renderer.py:847-854`) | `oracle-serving-api-cohere-structural-tag-not-modified` | model-bug | serving-api: `openai-serving-chat.create-chat-completion`, `online-renderer.render-chat`, `ServingChatCompletionRequest` | The run is ok, but `async-llm.generate` gets `sampling_params` of only `{max_tokens, n, temperature}`. The chat path drops `structured_outputs` (and `response_format` and `tools`), and there is no tool/reasoning parser step (`adjust_request`) or `--tool-call-parser` config. The pass-through can't be observed |
| `tests/entrypoints/pooling/scoring/test_bi_encoder_online.py:1` (file; `test_score_api_queries_str_1_documents_str_1`) | A bi-encoder embedding model answers `/score {queries, documents}` with an id and one score per pair. `BiEncoderIOProcessor` encodes queries and documents with the `embed` task, then takes the cosine per pair (`vllm/entrypoints/pooling/scoring/io_processor.py:216-357`) | `oracle-serving-api-bi-encoder-score-one-pair` | model-bug | serving-api: `serving-scores.post-score` / `pooling-base-serving.serve` | The route always sends pooling task `score`, one per `body.input` item, so an embed-only model gets 400 `vllm-validation-error` from `async-llm.encode` ("doesn't support this pooling task"). It ignores `queries`/`documents` and never pairs outputs. The HF score comparison is numeric and not translated |
| `tests/entrypoints/pooling/basic/test_tiling_engine.py:32` (`test_tiling_engine_basic`) | `LLM.encode` of 2 prompts with `max_num_seqs=2` returns 2 outputs, through `_run_tiling_engine`, which adds at most `max_num_seqs*2` requests to the LLMEngine and steps it until all finish (`vllm/entrypoints/pooling/offline.py:62-133, 396-480`) | `oracle-serving-api-tiling-engine-basic` | model-bug | serving-api: `llm.encode` calls the boundary stub `llm-engine.encode-request` (no behavior; engine-core never implemented it) | The count matches (`num_outputs == 2`, `request_counter == 2`), but `calls['llm-engine.add-request'] == 0` and `calls['llm-engine.step'] == 0`. The trace never reaches the engine, so there's no tiling, no ordering and no abort-on-exception path. It reproduces the outcome without taking the code's path |
| `tests/entrypoints/multimodal/openai/chat_completion/test_chat_completion_with_mixed_image_embeds.py:1` (file; `test_text_content_and_prompt_embeds_match_with_image_url`) | With `--enable-prompt-embeds --enable-mm-embeds`, a chat message that mixes an `image_url` part with a `prompt_embeds` part is accepted and answered like its text twin (`vllm/renderers/chat_utils.py:1062-1076`, placeholder splice in `vllm/renderers/hf.py:106-150`) | `oracle-serving-api-chat-mixed-image-and-prompt-embeds` | model-bug | serving-api: `ServingChatCompletionRequest.messages[].content` (string only), `hf-renderer.render-messages`; no `enable-prompt-embeds` / `enable-mm-embeds` configs | The run aborts: `hf-renderer.render-messages` concatenates `m.content` as a string ("no such overload"), with schema warnings "content: expected string, got array". The model has no content parts, multimodal data or prompt embeds in chat. The test's core assertion (identical greedy text) is model numerics and untranslatable |
| `tests/v1/engine/test_wake_up_contract.py:1` (file; `test_dp_wake_up_requires_all_engines_awake`) | `DPLBAsyncMPClient.wake_up_async` sends one `wake_up` utility call per core engine, in order, and returns `all(results)` (`vllm/v1/engine/core_client.py:1352-1353, 1262-1269`) | `oracle-engine-core-dp-wake-up-requires-all-engines-awake` | model-bug | engine-core: `async-llm.wake-up` → `async-mp-client.call-utility-async` (single engine); no DP client | Result `true` matches, but there is 1 `wake_up` utility call, not 2. The simulator warns that `engine-core-proc.process-input-sockets` runs only on engine-0. The model has no `DPAsyncMPClient` / `DPLBAsyncMPClient` and no `call_utility_all_async`, so the `[True, False] -> False` cases can't be expressed |
| `tests/v1/engine/test_init_error_messaging.py:9` (`test_kv_cache_oom_no_memory`) | `check_enough_kv_cache_memory(config, spec, 0)` raises ValueError "No available memory for the cache blocks" (`vllm/v1/core/kv_cache_utils.py:1104-1137, 1003-1017`) | `oracle-engine-core-kv-cache-oom-no-memory` | pass | — | `kv-cache-utils.get-kv-cache-configs` with `available_memory [0]` fails `value-error` with that message. `block-pool.init` is not called and the pool keeps 28,488 blocks. The check is folded into `get-kv-cache-configs` (the null-block reservation isn't modeled, but that doesn't matter at 0 bytes) |
| `tests/v1/engine/test_dp_placement_node_allowlist.py:67` (`test_allowlist_confines_dp_to_listed_nodes`) | With `VLLM_RAY_DP_PLACEMENT_NODE_IPS=10.0.0.1,10.0.0.3`, `CoreEngineActorManager.create_dp_placement_groups` makes 16 placement groups pinned only to .1 (master) and .3 (`vllm/v1/engine/utils.py:492, 642-700`; `vllm/envs.py:189, 1549`) | `oracle-engine-core-allowlist-confines-dp-to-listed-nodes` | model-bug | engine-core: `CoreEngineActorManager` / `create_dp_placement_groups` missing; config-platform: env `VLLM_RAY_DP_PLACEMENT_NODE_IPS` missing | `create-engine-config` with DP 16 over Ray resolves, but no placement-group call appears in the trace. Ray DP engine launch isn't modeled at all |
| `tests/config/test_config_generation.py:7` (`test_cuda_empty_vs_unset_configs`) | `CUDA_VISIBLE_DEVICES=""` yields the same VllmConfig as an untouched environment, because platform detection and batch defaults use NVML (`vllm/platforms/__init__.py:57-84`, `vllm/platforms/cuda.py:745`) | `oracle-config-platform-cuda-empty-vs-unset-configs` | pass | — | With torch's `device_count 0` (NVML still sees the H100), the trace takes `cuda-platform-plugin` (nvmlDeviceGetCount > 0) and gives CudaPlatform, 131072 / 16 / 1024 / 8192 / uni / gpu_worker. These are the same values as the model's default-world scenario. The test's DeepSeek-V2-Lite is replaced by the world's Llama |
| `tests/config/test_modelopt_mixed_nvfp4.py:22` (`test_detects_nvfp4_alongside_another_algorithm`) | `_modelopt_mixed_has_nvfp4` is true when any layer's `quant_algo` is NVFP4. `ModelConfig.is_nvfp4_quantized` uses it for `modelopt_mixed` (`vllm/config/model.py:130-142, 2283-2294`), and that drives `enable_act_fusion` → `pass_config.fuse_act_quant` at -O2 (`vllm/config/vllm.py:159-168, 272`) | `oracle-config-platform-modelopt-mixed-detects-nvfp4` | model-bug | config-platform: `model-config.post-init` / `ConfigVllmConfig` (no quantization resolution, no `is_nvfp4_quantized`); kernels-ops: config `fuse-act-quant` is static, not derived | `create-engine-config` succeeds, but `model_config` has no `quantization` and the result has no `compilation_config`. The checkpoint's `quantization_config` is ignored |
| `tests/test_envs.py:19` (`test_object_storage_shm_default_name`) | The default `VLLM_OBJECT_STORAGE_SHM_BUFFER_NAME` is `"vllm_mm_"` plus an unpadded url-safe base64 UUID, at most 30 characters (macOS limit) (`vllm/envs.py:546-551, 2040-2043`) | `oracle-config-platform-object-storage-shm-default-name` | model-bug | config-platform: `envs` state `variables` (9 entries) lacks `VLLM_OBJECT_STORAGE_SHM_BUFFER_NAME` | `envs.getattr` fails `attribute-error`. Low severity: only the default's shape matters |

Counts: pass 2, model-bug 8, test-mismatch 0, sim-gap 0, untranslatable 0. Two tests also make
untranslatable numeric assertions (HF score equality, identical greedy outputs), which weren't translated.

## Fix requests

### serving-api

1. **Chat requests carry structured outputs, and parsers adjust them.** Add `structured_outputs`,
   `response_format`, `tools` and `tool_choice` to `ServingChatCompletionRequest`, pass
   `structured_outputs` into `async-llm.generate`'s `sampling_params`, and model the
   `parser(...).adjust_request` step in `online-renderer.render-chat`
   (`vllm/renderers/online_renderer.py:830-854`) behind a `tool-call-parser` config. At minimum,
   show the Cohere pass-through when a `structural_tag` is already set
   (`vllm/parser/cohere_command.py:512-528`).
2. **Make `/score` (and `/rerank`) depend on the score type.** `ServingScores` picks the IO processor
   from the model's pooling task (`vllm/entrypoints/pooling/scoring/serving.py:46-58`). For an
   embed model (bi-encoder), encode `queries + documents` with the `embed` task, then return one
   result per pair (`io_processor.py:223-357`). Accept `queries`/`documents` in the request
   schema.
3. **Run `LLM.encode` through the engine.** Replace the `llm-engine.encode-request` boundary stub
   with `_run_tiling_engine`: add requests up to `max_num_seqs * 2` through
   `llm-engine.add-request`, call `llm-engine.step` until none are unfinished, sort the outputs by
   request id, and call `llm-engine.abort` on an exception (`vllm/entrypoints/pooling/offline.py:396-480`).
4. **Accept content parts in chat messages.** `content` may be a list of `text`, `image_url`,
   `image_embeds` and `prompt_embeds` parts. Add the `enable-prompt-embeds` / `enable-mm-embeds`
   configs (refuse with `_ENABLE_PROMPT_EMBEDS_ERROR` when they're off, `vllm/renderers/chat_utils.py:121, 1069-1071`),
   and forward the prompt embeds and multimodal data to the engine request.

### engine-core

1. **Data-parallel clients.** Model `DPAsyncMPClient` / `DPLBAsyncMPClient`, with one
   engine-core-proc instance per DP engine, and a `call_utility_all_async` fan-out
   (`parallel`, `need: all`) used by `wake_up_async` (returns `all`), `sleep_async` and
   `is_sleeping_async` (consensus) (`vllm/v1/engine/core_client.py:1262-1356`).
2. **Ray DP placement.** Add `CoreEngineActorManager.create_dp_placement_groups`, which honors
   `VLLM_RAY_DP_PLACEMENT_NODE_IPS`: it keeps the master, warns when it's omitted, and raises when
   too few groups fit (`vllm/v1/engine/utils.py:642-700`).

### config-platform

1. **Quantization in ModelConfig.** Resolve `quantization` from the checkpoint's
   `quantization_config` (modelopt with `MIXED_PRECISION` → `modelopt_mixed`), and add
   `is_nvfp4_quantized` / `_modelopt_mixed_has_nvfp4` (`vllm/config/model.py:130-142, 2283-2300`).
   Expose `compilation_config.pass_config.fuse_act_quant` derived through `enable_act_fusion` at -O2
   (`vllm/config/vllm.py:159-168, 272`). This needs coordinating with kernels-ops, which owns the
   static `fuse-act-quant` config.
2. **Missing env variables.** Register `VLLM_OBJECT_STORAGE_SHM_BUFFER_NAME` (defaulting to a
   30-character `vllm_mm_<b64 uuid>`) and `VLLM_RAY_DP_PLACEMENT_NODE_IPS` (default `""`) in
   `envs.variables`.

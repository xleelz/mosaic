
## serving-api (round 5)

- `judge3/scenarios/S3-7.yaml` `bench-s3-7-c` (header check): the scenario never sets `--enable-request-id-headers` (config `enable-request-id-headers`), so by the code the response has no X-Request-Id header (serve/middleware/register.py:38-41). With the flag set, the header is echoed: see `serving-api-r5-http-plumbing`.
- `oracle3/serving-api.yaml` `oracle-serving-api-test-model-dump-excludes-none` (chat step): the fault fires in AsyncLLM.generate, after create_chat_completion has set `raw_request.state.request_metadata` (chat_completion/serving.py:317-319). So `_request_id` returns `chatcmpl-<id>`, and the body is `{message, id}` (cohere/api_router.py:94-100, 113-116). Expecting `size() == 1` is wrong about the code.
- `build-oracle/round4/serving-api.yaml` `oracle-r4-serving-api-cohere-error-envelope`: the test sends no X-Request-Id. The scenario sends no headers, but the request schema's X-Request-Id example (`req-1`) fills one in, and the code echoes a client X-Request-Id as `id`. The scenario needs `headers: {X-Request-Id: {$absent: true}}`.
- Model-type renderers: the chat template and BOS now follow the served checkpoint (Llama-3, Qwen ChatML, Mistral [INST]). Scenarios in the VL or MoE worlds that counted Llama-3 special tokens will see different prompt ids.

## distributed (round 5)

- No judge3 or oracle3 expectation in distributed's area is wrong about the code; oracle3/distributed.yaml re-runs as before (2 pass, 1 engine-core model-bug, 1 untranslatable).
- For judges of the MoE world (`moe-mixtral-8x7b-tp2-ep`): TP 2 with `--enable-expert-parallel` and DP 1 uses **no all-to-all**. ParallelConfig.use_all2all is false at DP 1 (config/parallel.py:763-789), so the EP communicator builds no all2all manager (cuda_communicator.py:202) and the MoE output goes through the TP all-reduce. An expectation of all-to-all dispatch/combine in that world is wrong about the code; it needs DP > 1 (see `distributed-moe-ep-dp2-dispatch-combine`).

## scheduler-kv (round 5)

- **Judge3 `bench-q3-2-c` and `bench-q3-3` (scenarios to adapt).** Both call `scheduler-schedule`
  repeatedly without `update-from-output`, then expect a preempted request to be re-admitted. In the
  code, `_preempt_request` sets `num_stale_output_tokens = num_in_flight_tokens`
  (scheduler.py:1596-1606; in-flight tokens grow in `_update_after_schedule`, 1630, and drain only in
  `update_from_output`, 2079-2087), and the waiting loop skips a request with deliverable stale output
  (934-938). With no output applied, the preempted request is deferred, so in Q3-2 (c) W2 gets the turn
  and in Q3-3 C is not re-admitted at s4. The judge's own note ("in the busy loop it drains before the
  next schedule") is right; the scenarios need an `scheduler.update-from-output` for the step before
  the preemption.
- **Judge3 `bench-q3-8-b` (scenario to adapt).** It names images only in segment keys. The scheduler
  learns items from `Request.mm_features`; with `mm_features: [{identifier: p1-img0, offset: 8,
  length: 800}, ...]` and an encoder budget (a multimodal world, or `scheduler.init-encoder-cache`) the
  step is 1608 (`scheduler-kv-r5-encoder-budget-stops-chunk-before-image`).
- **Judge3 P3-8 a-c, Q3-4 c-d** wait on other areas: engine-core must pass `mm_features` and
  `prompt_logprobs` to `scheduler.add-request` and size the encoder cache at startup
  (`scheduler.init-encoder-cache`); worker-runner runs the encoder; serving-api maps echo+logprobs.
- **worlds.yaml.** The VL variant `scheduler-kv-vl-qwen2-vl-7b` (`variant_of: vl-qwen2-vl-7b`) is
  defined; rerun `assign_inventory.py --worlds` once this fragment is accepted, so
  `full-vl-qwen2-vl-7b` includes it.

## kernels-ops

- **oracle3/kernels-ops.md**: its expectations match the code, and the 4 oracle3 scenarios pass unedited.
  judge3 grades no kernels-ops step.
- **build-oracle/round5 `test_aiter_mha_platform_gate_matches_install_and_arch`**: the test expects
  `is_rocm() and on_mi3xx() and IS_AITER_FOUND`. The code returns `get_cdna_version() > 2`
  (`vllm/_aiter_ops.py:218-221`), which is also true on gfx1250 (CDNA 5), and that is not MI3xx. The model follows the code.
  The two agree on every arch the test runs on.
- **Cross-area (models-layers)**: two round-5 kernels-ops tests exercise models-layers code that isn't modeled:
  `FlashInferSSUBackend`'s ImportError (`mamba/ops/ssu_dispatch.py:336-345`), and
  `RoutedExperts._get_hidden_dim` / `_narrow_expert_data_for_padding` (`fused_moe/routed_experts.py`).

## models-layers

- **judge3 P3-7(d), `bench-p3-7d`: the world contradicts the corrected expectation.** It loads the bf16
  Llama-3.1-8B with `quantization: fp8` and `kv-cache-dtype: fp8_e5m2` and expects the fp8_e5m2 refusal.
  With no checkpoint quantization_config, `get_quant_config` takes the `possible_config_filenames == []`
  branch: `--quantization fp8` becomes online `fp8_per_tensor` with a deprecation warning
  (`weight_utils.py:347-357`). `OnlineQuantizationConfig.get_quant_method` returns None for Attention
  (`online/base.py:388-410`), so `should_load_quant_weights` is false and the check at
  `attention.py:201-219` never runs. The load succeeds. The judge's rule ("any checkpoint whose quant
  method is a KV-cache method") is right; it needs an FP8 checkpoint. Regression in that world:
  `models-kv-fp8-e5m2-refused-for-fp8-checkpoint` (full-fp8-llama-3-8b); the as-written case is
  `models-quant-fp8-online-fallback`.
- **oracle3 `oracle-models-layers-reject-fused-moe-lora-before-registration`: test mismatch.** The test
  builds a manager whose only module is a 2D `FusedMoEWithLoRA` and an adapter whose `lora_a` is one fused
  tensor (`tests/lora/test_lora_manager.py:55-83`). The scenario calls `add-adapter {adapter_id: 7}` in
  the dense Llama world, which has no MoE wrapper and carries no adapter weights, and there the code
  accepts the adapter (`model_manager.py:1257-1263` skips non-MoE modules). The validation is now
  modeled (`lru-cache-lora-model-manager.validate-moe-lora-format`, also called from the worker's
  load-adapter). Regressions in the Mixtral world: `models-lora-reject-fused-moe-before-registration`
  (all three test parametrizations refused, nothing cached) and `models-lora-mixed-moe-format-accepts-declared-3d`.
- **oracle3 `oracle-models-layers-preset-parses`** passes through attention's `kv-quant-mode`; the preset
  table itself is now `turbo-quant-config.from-cache-dtype` (sizes, and the "Unknown TurboQuant cache
  dtype" ValueError), scenario `models-turboquant-presets`.
- **oracle3 terratorch** stays with worker-runner (`get-supported-tasks`).

## worker-runner (round 5)

- `judge3/scenarios/P3-6.yaml` `bench-p3-6-a-b-o2-graphs` expects `calls['gpu-model-runner.capture-model'] == 1`. The scenario runs `wr-determine-available-memory`, whose `profile_cudagraph_memory` calls `runner.capture_model(profile_only=True)` (v1/worker/gpu/cudagraph_utils.py:942-943) before the real capture in `compile_or_warm_up_model`, so the code calls it twice. The other expectations pass.
- `oracle3/worker-runner.yaml` `oracle-worker-runner-backend-and-cudagraph-mode-combo` passes, but only with `--max-events 400000`: generating 10 prompts offline exceeds the default 20,000-event budget. The scenario should set `max_events`.
- `oracle3/models-layers.yaml` `oracle-models-layers-terratorch-inference` runs `runner: pooling` on the Llama checkpoint. A converted Llama pooler supports embed/token_embed, not `plugin`; only an IdentityPooler model (Terratorch, pooler/special.py:153-155) does, and the V2 runner then filters `plugin` out (pool/pooling_runner.py:61-64), so the test needs a Terratorch model and `VLLM_USE_V2_MODEL_RUNNER=0`. With `gpu-model-runner.model.architecture: Terratorch` and V1, `get-supported-tasks` returns `['plugin']` (`wr-r5-supported-tasks-v1-keeps-plugin`).
- `judge3/scenarios/P3-7.yaml` c and d are attention's layer init (attention.py:185, 205-219), not the worker's.

## attention

- **Oracle3 `oracle-attention-glm5next-indexer-kernel-block-sizes`** expects `describe(DEEPSEEK_V32_INDEXER)`
  to give `[128, 256]`. That name belongs to two classes. `DeepseekV32IndexerBackend.get_name()` returns it,
  and Glm5NextIndexerBackend inherits it (indexer.py:280-281). Asked by name with no kpool, the answer is
  DeepseekV32IndexerBackend's `[64]` on CUDA (indexer.py:283-285). `[128, 256]` is the GLM-5 class with
  `index_kpool = 4` (indexer.py:296-306), and the scenario gives no kpool. The model now describes the GLM
  class by its class name, `Glm5NextIndexerBackend`, with the kpool from a spec (`tokens_per_state`) or from
  `index_kpool`. The test's three rows pass in `attention-r5-indexer-kernel-block-sizes`.
- **Oracle3 `oracle-attention-reorder-batch-to-split-decodes-and-prefills`** is commented out in
  `oracle3/attention.yaml`. Uncommented and otherwise unedited, it passes.
- **Judge3 P3-7** isn't attention's. (a, b) are `attn-utils.get-kv-cache-spec` (worker-runner), and (c, d) are
  the Attention layer in `vllm/model_executor/layers/attention/attention.py` (models-layers). On the backend
  side, the fp8 cache now reaches FlashAttention: `attention-r5-fp8-kv-world-forward`.

## config-platform (round 5)

- **Judge3 L3-4** (`bench-l3-4a`, `-4a-cli`, `-4b`, `-4c`, `-4d`): all 5 pass unedited. (a) The message now prints
  `max_position_embeddings=131072.0 or model_max_length=None` and ends with the caution text (model.py:2585-2665). (c) `128K`
  parses through `engine-args.add-cli-args` (human_readable_int_or_auto, arg_utils.py:398-400, argparse_utils.py:29-93).
  bench-l3-4c still warns `serve-subcommand.cmd request: $.max_model_len: expected [integer null], got string`: serving-api's
  schema should take the CLI string.
- **Judge3 L3-8(a)** passes: `model-config.get-diff-sampling-param` is now the owner's behavior (model.py:1847-1901). The
  generation_config.json rows it reads are in config-platform-seed's `hf-hub.generation_configs`, so they exist only in
  `full-*` worlds; they belong in `fixtures.yaml` (config-platform notes, "Coordinator: fixtures"). L3-8(d) is engine-core's.
- **Judge3 P3-7(c)**: `CacheConfig._validate_cache_dtype`'s info log is now `ctx.cache_dtype_info` (cache.py:353-367), shown
  in `config-fp8-kv-cache-fp8`. P3-7(d) (`bench-p3-7d`, fp8_e5m2 with an fp8 checkpoint) is the Attention layer's
  (models-layers), not config-platform's.
- **Oracle3 `oracle-config-platform-dict-overrides-not-forwarded-to-draft`** is commented out in `oracle3/config-platform.yaml`.
  Uncommented and otherwise unedited it now resolves (`speculative-config.compose-draft-hf-overrides`); regression
  `config-draft-hf-overrides`.
- **Oracle3 `oracle-config-platform-mp-reducer`** still fails: the reducer registration belongs to engine-core's
  `async-llm.init` (the function is in serving-api's transformers_utils).
- `oracle2/distributed.yaml` `oracle-distributed-turn2-deadline-gate-expired` (fails before and after this round): the test builds the worker with `BIDIR_KV_EXTRA_CONFIG` (test_bidirectional_kv_transfer.py:92-93), which turns on `bidirectional_kv_xfer`; the gate only runs when it is on (pull_worker.py:150). The scenario leaves `nixl-pull-connector-worker.bidirectional_kv_xfer` false, so the READ is issued. It needs `state: {nixl-pull-connector-worker: {bidirectional_kv_xfer: true}}`, as the passing far-future twin's sibling `distributed-nixl-turn2-deadline-gate` does.

## engine-core (round 5)
- **judge3 L3-8d-enabled** sets `config: {disable-log-stats: false}`, which is already the world default (`vllm serve`). `LLM()` turns stat logging off unless the caller passes `disable_log_stats` (llm.py:226-227). A config override can't express that kwarg, so the scenario can't tell the two cases apart. Express it as `state: {llm-engine: {log_stats: true}}`, or call `llm-engine.from-engine-args` with `disable_log_stats: false`. L3-8d-default now passes.
- **judge3 L3-5d.** This follows judge3's wrong claim 10. AsyncLLM.shutdown cancels the output handler in the same event-loop turn as the output task (async_llm.py:305-308). So the EngineDeadError the cancelled task queues (core_client.py:1218-1221) is never read, and an in-flight generate() is not failed; the server cancels it. The step's assertion indexes the last streamed item of a stream that produced none in 30 ms, so it now errors (index -1). Its intent, "not finished with length", holds.
- **judge3 P3-2b** runs `dp-client-stats-update-task` with stats as input, which is the client side of the coordinator's publish. The coordinator (`dp-coordinator.*`) appears only on FIRST_REQ, wave or engine-output paths, so this flow never calls it.
- **judge3 P3-2a / P3-3c** need one engine-core, executor and scheduler instance per DP rank. The topology names only engine-core-proc and dp-engine-core-proc, so the ranks share dp0's scheduler, and idle ranks see dp0's request. (DP placement of workers is an instance-group change across areas.)
- **judge3 P3-8 / Q3-8** configure `model: Qwen/Qwen2.5-VL-7B-Instruct`, which no world's hf-hub has. Use the `full-vl-qwen2-vl-7b` world.
- **oracle3 step-invalidates-mm-cache-misses**: the invalidate calls now happen, in order. The last expectation reads `state['lru-key-replicated-sender-cache']`, but that component's state is `@rank0` (models-layers' parenting), so the key is absent.

## merge (round 5)

Expectations the merged model doesn't meet because they are wrong about the code, or need a world the scenario doesn't use. Each was re-run unedited; the adapted copies named here were run from a scratch file only.

- **Multimodal on a model that isn't multimodal (judge3 `bench-s3-4-a`, `bench-s3-4-b`; build-oracle round 3 `oracle-r3-serving-api-video-num-frames-override`; oracle `oracle-serving-api-chat-mixed-image-and-prompt-embeds`).** All four run in `full-tp1-llama-8b`. S3-4 sets `model: Qwen/Qwen2.5-VL-7B-Instruct`, which that world's hf-hub doesn't hold. The two oracles set `model-is-multimodal: true` on the Llama checkpoint. In the code the processor comes from the served architecture, not from a flag. `MultiModalRegistry.create_processor` resolves the model class from the checkpoint's `architectures` and refuses a text-only class (`vllm/multimodal/registry.py:157-159`). `ModelConfig.is_multimodal_model` is only `multimodal_config is not None`, and ModelConfig builds that config only for a multimodal architecture (`vllm/config/model.py:817-868`, `1981-1982`). So `LlamaForCausalLM` gets 400 `llama-8b is not a multimodal model`, and a repo that isn't on the hub fails when its config is fetched (`vllm/transformers_utils/config.py:816-860`). The tests use a real VL checkpoint: `test_video.py:15` uses llava-onevision, and `test_chat_completion_with_mixed_image_embeds.py:24` uses Qwen2-VL-2B. In `full-vl-qwen2-vl-7b`, with `model: qwen2-vl-7b` and no flag override, all four pass unedited otherwise: S3-4 a and b give `At most 1 image(s)` with `data.param == 'image'` and `At most 0 audio(s)`. The scenarios need the VL world.
- **Judge `bench-e1` and `bench-e1-tp4` (startup order and counts).** `Worker.determine_available_memory` profiles CUDA-graph memory whenever `cudagraph_mode != NONE` (`vllm/v1/worker/gpu_worker.py:700-704`). `profile_cudagraph_memory` builds a minimal KV cache with `runner.initialize_kv_cache(minimal_config, is_profiling=True)` (`vllm/v1/worker/gpu/cudagraph_utils.py:990-1013`), then calls `runner.capture_model(profile_only=True)` (`cudagraph_utils.py:942-943`). The real `initialize_kv_cache` and `capture_model` follow. So each appears twice per rank (8 times at TP 4), and the single-occurrence order and the `== 4` counts are wrong about the code. Worker-runner's P3-6 note above has the same cause.
- **Judge `bench-e3` (abort order).** `process_input_sockets` puts an ABORT on both the aborts queue and the input queue (`vllm/v1/engine/core.py:1923-1931`). The step drains the aborts queue after the model runs and before `update_from_output` (`core.py:678-681`, `814-822`). So an abort that arrives mid-step reaches `engine-core.abort-requests` (and `scheduler.finish-requests`, `kv-cache-manager.free`) before `engine-core-proc.handle-abort` dequeues the same ids. Aborting is idempotent (the comment at `core.py:1924-1927`). The expected order holds only for an abort that arrives between steps.
- **Judge2 `bench-l2` (startup memory error text).** The scenario expects raw byte counts in the message. The code prints `format_gib` values: `Free memory on device cuda:0 (60.0/80.0 GiB) on startup is less than desired GPU memory utilization (0.92, 73.6 GiB). ...` (`vllm/v1/worker/utils.py:760-768`; `format_gib` rounds to 2 places, `vllm/utils/mem_utils.py:30-31`). Worker-runner's round-5 precision sweep moved the message to the code's text. The other six expectations pass.
- **Judge `bench-v6`.** The scenario aborts on the default 20,000-event budget. Round 5's labeled metrics and stat recording add events to every step. It passes unedited with `--max-events 400000`, so the scenario should set `max_events`.
- **Judge `bench-x5-worker-crash-mid-generation` (path order; timing).** The outcome expectations pass: the request fails with `engine-dead-error` and is not aborted, the engine is dead, and the health check fails. The path differs. The monitor sets `is_failed`, then shuts the executor down before it calls the failure callback (`vllm/v1/executor/multiproc_executor.py:299-333`). The busy loop's next `execute_model` meets `collective_rpc`'s `if self.is_failed: raise RuntimeError("Executor failed.")` (`multiproc_executor.py:398-399`), so it dies through the step-error path before EXECUTOR_FAILED is dequeued. Both paths raise `RuntimeError('Executor failed.')` and send ENGINE_CORE_DEAD. No `update_from_output` runs before the crash at 560 ms. That is probably the TP-4 70B step time with async scheduling's batch queue of 2 (`vllm/config/vllm.py:577-587`, engine-core round 5), but this is unverified. Which thread wins is a race in the code. The scenario pins one order.
- **Oracle3 `oracle-distributed-torchrun-consistent-across-ranks`.** The external launcher is now modeled: one engine per torchrun rank in lockstep, and the budget is the `ReduceOp.MIN` of every rank's (`vllm/v1/executor/uniproc_executor.py:161-207`; `engine-core-r5-external-launcher-min-memory`). The scenario puts 8 GiB of another process on rank1 at the default utilization. That rank then fails startup in `request_memory`, because free memory is below the requested budget (`vllm/v1/worker/utils.py:760-768`), and the code does the same. With 4 GiB the scenario passes. Separately, the MIN reduction is `dist.all_reduce(memory_tensor, group=get_world_group().cpu_group, op=ReduceOp.MIN)`, not `GroupCoordinator.all_reduce`. The `group-coordinator.all-reduce` the second expectation finds is the profile run's TP all-reduce.

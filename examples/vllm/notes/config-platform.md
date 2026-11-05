# config-platform notes (vLLM v0.32.0, 5df63a7203)

Fragment: `examples/vllm/fragments/config-platform.yaml`. Skips: `examples/vllm/skips/config-platform.json`.
Code root: `/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`. All line references below are relative to it.

Final check (skeleton + fixtures + this fragment, `--strict-citations --inventory --min-modeled 0.5
--min-substantive 0.5 --max-trivial 0.35 --behavior-coverage --lint hollow,trivial --no-mocks -v`): exit 0;
validation 0 errors / 0 warnings; 93/93 scenarios pass, 0 scenario warnings, 0 mocks; citations 307/307 ok;
behavior coverage 362/362 steps, 0 unexecuted fail/if branches; hollow lint 0 failing (2 advisory "no state
change": the probe-loop scenarios where the loop is disabled or stopped, which is their point); trivial 0/15;
modeled 15/22 owned entries (68%), substantive 15.

## 1. Entry points

22 inventory entries carry `area: config-platform`.

| Entry | Covered by |
|---|---|
| plugin `builtin_platform_plugins tpu` (vllm/platforms/__init__.py:232) | `platforms.tpu-platform-plugin` (flow config-platform-detect) |
| plugin `builtin_platform_plugins cuda` (:233) | `platforms.cuda-platform-plugin` |
| plugin `builtin_platform_plugins rocm` (:234) | `platforms.rocm-platform-plugin` |
| plugin `builtin_platform_plugins xpu` (:235) | `platforms.xpu-platform-plugin` |
| plugin `builtin_platform_plugins cpu` (:236) | `platforms.cpu-platform-plugin` |
| plugin `group vllm.platform_plugins` (:250) | `platforms.resolve-current-platform-cls-qualname` |
| plugin `group vllm.general_plugins` (vllm/plugins/__init__.py:87) | `plugins.load-general-plugins` (flow config-general-plugins) |
| plugin `group vllm.endpoint_plugins` (vllm/plugins/__init__.py:123) | `plugins.load-endpoint-plugins` (flow config-endpoint-plugins) |
| plugin `group vllm.io_processor_plugins` (vllm/plugins/io_processors/__init__.py:59) | `io-processors.get-io-processor` (flow config-io-processor) |
| plugin `vllm.general_plugins lora_filesystem_resolver` (pyproject.toml:46) | `filesystem-resolver.register-filesystem-resolver` |
| plugin `vllm.general_plugins lora_hf_hub_resolver` (pyproject.toml:47) | `hf-hub-resolver.register-hf-hub-resolver` |
| busy-loop `benchmark.probe_loop` (vllm/benchmarks/serve.py:992) | `benchmarks-serve.probe-loop`, flow config-bench-probe-loop (`entry.repeat`) |
| python-cli `vllm` (pyproject.toml:43) | `console-scripts.vllm`, flow config-vllm-cli |
| python-cli `server` (vllm/snapshot/server.py:251) | `snapshot-server.main`, flow config-snapshot-server |
| torch-op-wrapper `get_mem_info_wrapper` (vllm/platforms/xpu.py:31) | `xpu.get-mem-info-wrapper`, flow config-xpu-mem-info |
| python-cli × 7: `create_txt_slices_dataset`, `mm_processor`, `plot`, `plot_pareto`, `serve` (sweep), `serve_workload`, `startup` under vllm/benchmarks/** | **skipped**: `__main__` blocks of benchmark/sweep tooling modules, not entry points of the served product (the `vllm bench` subcommands are serving-api cli-commands) |

EngineArgs (vllm/engine/arg_utils.py) is ours by override; it has no inventory entries of its own, but
`engine-args.create-engine-config` is the main flow (config-create-engine-config).

## 2. Components

All under the skeleton module `control`.

| Component | Code |
|---|---|
| engine-args | EngineArgs, vllm/engine/arg_utils.py:471; create_engine_config 2205-2872; helpers 1932-2099, 2874-3187 |
| model-config | ModelConfig, vllm/config/model.py:151 (post_init 561-811, get_and_verify_max_len 2129-2153 + 2527-2666, verify_with_parallel_config 1532-1610, is_*_supported 2174-2273) |
| cache-config | CacheConfig, vllm/config/cache.py:69 (gpu_memory_utilization Field 102, _apply_block_size_default 336-347) |
| parallel-config | ParallelConfig, vllm/config/parallel.py:136 (__post_init__ 943-1116) |
| scheduler-config | SchedulerConfig, vllm/config/scheduler.py:25 (__post_init__ 292-312, verify_max_model_len 314-358) |
| speculative-config | SpeculativeConfig, vllm/config/speculative.py:387 (_maybe_override_draft_max_position_embeddings 1677-1709) |
| aux-output-config | AuxOutputConfig, vllm/config/aux_output.py:11 |
| vllm-config | VllmConfig vllm/config/vllm.py:341; set/get_current_vllm_config 3421-3490. **Holds the shared datum** in `state.resolved` (last resolved config) and `state.current` (the context value) |
| platforms | vllm/platforms/__init__.py (probes 33-228, resolve 240-293, `__getattr__`/`__setattr__` 303-336). State `host` = what the probes see; `current` = cached platform |
| cuda-platform | CudaPlatformBase/NvmlCudaPlatform, vllm/platforms/cuda.py:224, 1044 (check_and_update_config 323-364) |
| cpu-platform | CpuPlatform vllm/platforms/cpu.py:103 (check_and_update_config 215-320, `_cpu_mamba_backend` 39-91 modeled on this component) |
| xpu | module vllm/platforms/xpu.py (get_mem_info_wrapper 31-100) |
| plugins | vllm/plugins/__init__.py (load_plugins_by_group 36-74, load_general_plugins 77-90, load_endpoint_plugins 93-159). State `entry_points` = installed entry points per group, `plugins_loaded` guard |
| filesystem-resolver, hf-hub-resolver | vllm/plugins/lora_resolvers/*.py register functions |
| io-processors | vllm/plugins/io_processors/__init__.py:32-88 |
| envs | vllm/envs.py (`__getattr__` 2291-2299, enable_envs_cache 2308-2326, get_vllm_port 516-543, env_with_choices 399-441) |
| console-scripts | pyproject.toml:42-43 → vllm/entrypoints/cli/main.py:39-120 (dispatch only; serving-api owns the CLI internals) |
| benchmarks-serve | vllm/benchmarks/serve.py probe loop 990-1009 and probe stats 1240-1251 |
| snapshot-server | vllm/snapshot/server.py:72-252 |

## 3. Boundary stubs

No owner fragment existed for any of these when I built; `fragments/distributed.yaml` appeared later but I call
nothing of distributed's and did not read it.

| Stub | Owner | Contract source |
|---|---|---|
| hf-hub.download-config | shared | shared-infra naming (`hf-hub.<op>`, kind http). Declared with `store: {table: models, op: get}` so the fixture's seeded `hf-hub.models` rows are what ModelConfig reads. A miss is 404 `not_found`; my behaviors map it to vLLM's `value-error` (transformers_utils/config.py:846-860) |
| local-disk.stat | shared | shared-infra naming (`local-disk.<op>`, kind io); `store` on table `paths`, missing path = `{exists: false, is_dir: false}` |
| gpu-memory.get-memory-info | shared | shared-infra naming (`gpu-memory.<op>`, kind io); stub, response `{free_bytes, total_bytes}`. Op name `get-memory-info` is mine (the list names allocate/free/profile-peak as examples) |
| lora-resolver-registry.register-resolver | models-layers | shared shapes; request `{resolver_name}` (vllm/lora/resolver.py:52-72). Component id is `_LoRAResolverRegistry` in kebab-case |
| openai-serving-completion.post-v1-completions | serving-api | naming rule + HTTP envelope `{path, body, headers}`; error invalid_request_error 400 from the fixed table |
| async-llm.generate | engine-core | skeleton seam list names `async-llm.generate`; shapes are the shared ones I use (request_id, prompt, sampling_params); error engine-dead-error 500 from the fixed table |

Expect to align these in reconciliation (especially the two `store`s on shared components, and the response
shapes of async-llm.generate and the completions route).

## 4. Config

Owned:

| id | deployed | code default | sources | note |
|---|---|---|---|---|
| max-model-len | 131072 | None (derive) | config/model.py:245, arg_utils.py:502, model.py:2624-2635 | **differs**: deployed value is the derived one (Llama-3.1 max_position_embeddings 131072; rope_type llama3 is excluded from the factor multiply, model.py:2595-2605). The fixtures reference had default 131072; I set default null |
| vllm-target-device | cuda | cuda | envs.py:91, 621 | |
| vllm-plugins | null (unset) | null | envs.py:117, 1172-1176 | |
| vllm-tpu-using-pathways | false | false | envs.py:201, 1615-1617 | |
| vllm-allow-long-max-model-len | false | false | envs.py:110, 1123-1126 | |
| vllm-lora-resolver-cache-dir | null | null | envs.py:118, 1180-1182 | |
| vllm-lora-resolver-hf-repo-list | null | null | envs.py:119, 1187-1189 | |
| vllm-enable-v1-multiprocessing | true | true | envs.py:165, 1463-1465 | |
| vllm-port | null | null | envs.py:16, 516-543 | raw string |
| vllm-worker-multiproc-method | null (→ fork) | null (→ fork) | envs.py:70, 956-958 | raw string |
| probe-request-rate | 0.0 | 0.0 | benchmarks/serve.py:816, 1719-1722 | bench CLI arg |
| release-timeout-s | 900.0 | 900.0 | snapshot/server.py:76 | snapshot CLI arg |

Env vars are modeled as config entities named after the variable in kebab-case (`attributes.key` = the env
name, `env: true`); no fixture sets any, so deployed = default.

Referenced (owners): max-num-seqs, max-num-batched-tokens, enable-chunked-prefill, enable-prefix-caching,
block-size (scheduler-kv); gpu-memory-utilization (worker-runner); tensor-parallel-size (distributed). The flow
config-create-engine-config feeds them in as the operator's CLI flags: tensor_parallel_size and
gpu_memory_utilization directly, enable_prefix_caching / enable_chunked_prefill as "flag passed only when the
deployed value is false".

**Deployed vs default differences I found in the code (for the owners and the coordinator):**

- `max_num_seqs` / `max_num_batched_tokens`: EngineArgs leaves both None and `get_batch_defaults`
  (arg_utils.py:2894-2985) picks them by usage context and hardware. For `vllm serve` (usage_context
  OPENAI_API_SERVER, api_server/entry.py:73,83) on an 80 GB GPU that is not an A100 (H100/H200) the result is
  **max_num_seqs 1024, max_num_batched_tokens 8192**; on an A100-80GB **256 / 2048**; on >=160 GiB GPUs
  1024 / 16384. The fixtures' 128 / 2048 are SchedulerConfig's class defaults (scheduler.py:41-43) and are only
  what you get when the usage context is not in the table (None, or ENGINE_CONTEXT from
  LLMEngine.from_engine_args, llm_engine.py:160,183). Scenario `config-create-engine-config-serve-h100` asserts
  1024/8192; `config-create-engine-config-usage-none` asserts the fixture values under ENGINE_CONTEXT.
- `block_size`: CacheConfig.block_size defaults to None and `_apply_block_size_default` sets 16
  (cache.py:343-346); the CPU platform then turns an unset block size into 128 (cpu.py:292-293).
- `enable_chunked_prefill` / `enable_prefix_caching`: EngineArgs defaults are None (arg_utils.py:580, 695),
  resolved from what the model supports (arg_utils.py:2987-3037); both true for decoder-only generative models,
  both false for encoder-decoder models, forced false on RISC-V CPUs.

## 5. Fixture requests

1. **Batch defaults vs the fixture**: `tp1-llama-8b` says "the default engine args" with max_num_seqs 128 and
   max_num_batched_tokens 2048, but `vllm serve` on an 80 GB H100 resolves 1024 / 8192 (see 4). Either name the
   GPU (an A100-80GB still gives 256 / 2048, not 128) or set the two values to what `vllm serve` resolves. This
   is scheduler-kv's config; I did not change it.
2. **Name the GPU in the fixture**: the resolution depends on the device name and memory NVML reports. I keep
   them in `platforms.host` (`device_name: NVIDIA H100 80GB HBM3`, `device_total_memory: 85899345920` = the
   fixture's gpu-memory total). A fixture field for the GPU model would remove this assumption and the duplicate
   of gpu-memory's total.
3. Nice to have: model-architecture facts on the hf-hub rows that ModelConfig reads (`rope_type`, attention type
   for non-decoder models). My scenarios seed extra hf-hub rows (EAGLE3 draft, whisper, a linear-RoPE model)
   through scenario `state`, which is per-case state on a shared component.

## 6. What the code didn't settle / assumptions

- Device facts (name, memory, count, CPU arch, TPU chip) are host state on `platforms` (assumption, see 5).
- `vllm-config.post-init` calls `verify-with-parallel-config` with `pp_supported: true` (the model registry,
  owned by models-layers, decides this; Llama implements SupportsPP).
- `platforms.getattr` maps the resolved class name to a device type by name (Cuda/Rocm → cuda, Cpu → cpu,
  XPU → xpu, Tpu → tpu, Unspecified → ""), standing in for the instantiated Platform's `device_type`.
- The probe loop's request is one call to the completions route with `max_tokens: 1`; the loop's sleep is
  `wait 1000/rate` ms after each probe.
- The snapshot canary's comparison (`oracles_match`) and the release marker's arrival are choices
  (`rehearsal_matches`, `release_marker`): they depend on engine output and an external controller.
- XPU host: `xpu.state.device_count = 1` (the default world has no XPU).

## 7. Docs / common knowledge vs code

- "max_num_seqs defaults to 256" (older vLLM, many guides): in v0.32.0 the default depends on usage context and
  GPU (1024 on H100 serving, 256 on A100, 128 when no usage context applies).
- "Chunked prefill is off by default" (V0 era): it is on for every generative decoder model and only off for
  encoder-decoder or some pooling models.
- "max_model_len is the model's context window × RoPE factor": the factor is applied only for RoPE types other
  than su/longrope/llama3/yarn/deepseek_yarn/deepseek_llama_scaling; Llama-3.1 stays at 131072.

## 8. Simulator gaps

- **Null config values are absent from CEL `config`.** `config['vllm-plugins']` with `value: null` aborts with
  "no such key". Every read of a nullable config is guarded with `'<id>' in config ? config['<id>'] : null`
  (e.g. plugins.load-plugins-by-group, envs.get-vllm-port).
- **A null cannot override a value in entry/scenario input** (deepMerge keeps the base when the overlay is nil).
  So a scenario cannot pass `usage_context: None`; I used ENGINE_CONTEXT, which the code treats identically
  (not a key of the defaults table). Nullable request fields carry `default: null` so fake data doesn't invent
  values for them.
- **`entry.repeat` does not apply when a flow runs as a scenario step**; the probe-loop write-then-read scenario
  calls the flow once per step instead.
- CEL ternaries mixing null and a typed value need `dyn(...)` (`cond ? dyn(null) : dyn(false)`).
- Pydantic field validation (gt/le bounds) is modeled as explicit `if/fail` steps returning `validation-error`.
- `set_current_vllm_config` is a context manager; modeled as an interface that sets `state.current`, calls the
  "body" (get-current-vllm-config) and restores the old value, also on error.

## 9. Known gaps

- create_engine_config is modeled for model, cache, parallel, speculative, scheduler and the VllmConfig
  hook. Not modeled: LoRA config and its spec-decode budget check (arg_utils.py:2671-2684), attention/kernel/
  mamba/compilation overrides and their mutual-exclusion errors (2686-2805), KV transfer/events, offload,
  data-parallel rank/address inference for multi-node (2357-2512), `validate_environ` (unknown VLLM_* vars,
  interface.py:1446-1460), HF offline path rewriting in __post_init__, and most of VllmConfig.__post_init__
  (cudagraph sizes, compile ranges, async scheduling).
- ModelConfig: runner/convert resolution is reduced to `runner == pooling`; pooling chunked-prefill/prefix
  support ignores MEAN/CLS/STEP pooling types (model.py:2186-2206, 2232-2252); dtype resolution, quantization,
  multimodal config and sliding-window handling are not modeled.
- ParallelConfig: elastic EP, external_launcher, ray placement-group detection and EPLB communicator choice
  are not modeled; `prefill_context_parallel_size` is taken as 1.
- Platform classes: only CudaPlatform.check_and_update_config (worker class, MM prefix-LM) and the parts of
  CpuPlatform.check_and_update_config covered by the oracle test (block size, GDN SSM dtype). ROCm, XPU and TPU
  platform classes are not modeled beyond detection.
- Profiler (vllm/profiler/**), logging_utils, assets and setup.py have no inventory entries and are not modeled.
- The loaded LoRA resolvers' `resolve_lora` paths (filesystem/HF hub adapter lookup) are not modeled.

## 10. In-build oracle

| Test | Scenario | Verdict | Cause |
|---|---|---|---|
| tests/platforms/test_cpu.py:135 `test_cpu_accelerated_gdn_dtype_policy` (8 params) | oracle-build-config-platform-1 (one step per param) | pass | `cpu-platform.check-and-update-config` + `cpu-mamba-backend`; avx512_bf16 set through `cpu-platform` state, the fake model's state dtype passed as `state_dtype` |
| tests/config/test_aux_output_config.py:62 `test_aux_output_config_defaults` | oracle-build-config-platform-2 | pass | `aux-output-config.init` with no args: enabled false, enable_return_routed_experts false, max_bytes null |
| tests/config/test_speculative_draft_max_position_embeddings.py:48 `test_override_raises_smaller_value` | oracle-build-config-platform-3 | pass | 2048 raised to 8192 and the INFO log recorded in `ctx.spec_override_log` |

## Reconciliation round

- **Configs (decision 7).** Now owned here: model, served-model-name, runner, quantization, model-impl,
  enforce-eager, enable-sleep-mode, enable-lora, return-sampling-mask, enable-trace-replay,
  enable-batch-sharded-sampling, disable-hybrid-kv-cache-manager, max-cudagraph-capture-size,
  use-v2-model-runner, profiler, weight-transfer-backend, watermark-enabled, speculative-method,
  num-speculative-tokens, speculative-draft-architecture, mtp-num-nextn-predict-layers,
  enable-adaptive-verification, vllm-batch-invariant, vllm-lora-enable-dual-stream (plus vllm-target-device).
  If a code default is None and the value is a string or int, the config stores '' or 0 (`attributes.none_is`),
  because null config values drop out of CEL `config`. disable-hybrid-kv-cache-manager and quantization keep null,
  so their readers guard them with `in config`. `async-scheduling` is a boundary copy of scheduler-kv's.
  engine-core still defines it unmarked; engine-core has to mark its copy.
- **Batch defaults.** The fixture now has 1024 / 8192 (vllm serve on an H100). `serve-h100` asserts it equals
  config. `usage-none` (ENGINE_CONTEXT) asserts the class defaults 128 / 2048.
- **async-llm.generate.** It now uses engine-core's contract: request EngineCoreRequest, response
  EngineCoreGenerateResult, and engine-core's error list. The `async-llm` component's parent is now engine-core
  and its layer frontend. The snapshot canary sends `prompt_token_ids`. Assumption: the ids
  [128000, 791, 6864, 315, 9822, 374] are illustrative Llama-3 ids for "The capital of France is". The real code
  passes the string through the input processor. The snapshot scenarios run in `full-tp1-llama-8b`, so they need
  the merged world.
- **openai-serving-completion** no longer has a parent (decision 12).
- **Seed fixture.** `config-platform-seed` sets `platforms.host` (H100 80GB, 1 GPU, X86) and
  `cuda-platform.device_capability` (9.0).
- **New `cuda-platform.get-attn-backend-cls`** (cuda.py:417-516, priorities 83-178).
  - It copies attention's stub contract. It validates the selected backend, or every candidate in priority
    order, through attention's `attention-backend.validate-configuration` (called `on: rank0` with `fill: true`),
    and returns the class path of the first valid one.
  - A `key-error` from attention (a backend attention doesn't model) stands in for the code's ImportError path:
    the backend counts as invalid.
  - Not modeled: the `--block-size` "precluded higher-priority backend" warning (cuda.py:487-505), and the
    SM100/SM120 sparse-MLA ordering details.
  - The SM major is cuda-platform state (9 by default). It duplicates gpu-memory's `compute_capability`.
- **Speculators auto-detection.** `maybe_override_with_speculators` is modeled inside
  `engine-args.create-engine-config` (arg_utils.py:2223-2238, transformers_utils/config.py:754-813,
  speculators/base.py:77-137):
  - the checkpoint's config.json is read from hf-hub;
  - peagle becomes eagle3 with parallel drafting, and dflash2 becomes dflash;
  - the user's --speculative-config is merged in, then method and model are locked to the checkpoint's;
  - the verifier becomes the model.
  The function is in serving-api's transformers_utils. I model it inline because only create_engine_config calls
  it.

In-build oracle, added this round:

| Test | Scenario | Verdict | Cause |
|---|---|---|---|
| tests/v1/spec_decode/test_speculators_correctness.py:136 `test_speculators_model` (dflash, peagle, qwen3arch_eagle3) | oracle-build-config-platform-4 | pass | The config asserts are translated: method, parallel_drafting, num_speculative_tokens > 0, draft model = path. The `generate_greedy` step is **untranslatable** at this level: it needs real drafting and generation output through the merged engine. The fp8 quantization of the dflash param is ignored. |

## Fix round

- **Quantization detection.** `model-config.verify-quantization` (model.py:1370-1468) and
  `model-config.is-nvfp4-quantized` (model.py:2283-2302, 130-142).
  - `verify-quantization` takes the checkpoint's `quantization_config.quant_method` and refines it with the
    ModelOpt override rules (modelopt.py:284-299, quant_algo FP8 / NVFP4 / MXFP8 / MIXED_PRECISION). It refuses
    a mismatch with `--quantization`, unknown methods and deprecated methods.
  - The GPTQ/AWQ Marlin overrides depend on the GPU and are not modeled; the checkpoint's method is kept.
  - `ConfigVllmConfig.model_config` now carries `quantization` and `is_nvfp4_quantized`.
- **fuse_act_quant.** `vllm-config.enable-act-fusion` (vllm.py:159-168; is_custom_op_enabled at
  compilation.py:1356-1367) derives `compilation_config.pass_config.fuse_act_quant`. -O0 forces it false, and -O1
  to -O3 take enable_act_fusion (vllm.py:289-293, 1779-1780).
  - kernels-ops still reads the static world config `fuse-act-quant`; `config` can't be written at run time
    (simulator gap). `vllm-config.post-init` sets `ctx.fuse_act_quant_config_mismatch` when the derived value
    differs from that config.
  - The default world derives false, which matches. A world serving an NVFP4 checkpoint must set
    `fuse-act-quant: true`.
- **EPLB.** New configs `enable-eplb` and `enable-expert-parallel`, plus `parallel-config.validate-parallel-config`
  (parallel.py:517-587):
  - EPLB is refused off CUDA/ROCm/XPU;
  - EPLB needs `--enable-expert-parallel` and TP×PCP×DP > 1;
  - `num_redundant_experts` without EPLB is refused.
  `parallel_config` now carries `enable_eplb` and `enable_expert_parallel`.
- **Environment.**
  - `VLLM_OBJECT_STORAGE_SHM_BUFFER_NAME` goes through `envs.get-env-or-set-default` (envs.py:554-571).
    `_generate_shm_name` (envs.py:546-551) gives `vllm_mm_` plus 22 url-safe base64 characters. The name is
    written back to `envs.state.environ`, so later reads agree.
  - `VLLM_RAY_DP_PLACEMENT_NODE_IPS` is registered with default "" (envs.py:189, 1549-1551).
- **Other new configs.** `structured-outputs-backend` (auto) and `optimization-level` (2).
- **ObservabilityConfig.** `observability-config.init` (observability.py:166-221) validates the custom histogram
  buckets and the tracing config. It is called from `create-engine-config` (arg_utils.py:2785) and reaches
  tests/config/test_observability.py.
- **get-attn-backend-cls.** I kept attention's edit: only ImportError/OSError are caught, and each backend's
  reasons are kept. My scenarios now follow the code's answers with attention's full backend table:
  - head 16 in fp32 → FlexAttention;
  - head-576 MLA on SM90 → FLASH_ATTN_MLA, the first valid entry of the SM90 MLA list (cuda.py:147-153), not
    TRITON_MLA;
  - SM100 → FlashInfer;
  - a selected FLEX_ATTENTION is valid.
  A new scenario covers the probe-failure paths through faults.

| Oracle case | Verdict now |
|---|---|
| oracle-config-platform-modelopt-mixed-detects-nvfp4 | pass |
| oracle-config-platform-object-storage-shm-default-name | pass |
| oracle-config-platform-cuda-empty-vs-unset-configs | pass |

## Fix round 3

I edited `fragments/config-platform.yaml` directly; config-platform has no generator.

- **racy: 2 → 0 (system findings).** Both are marked `racy_in_code`, because the code itself checks and then writes
  module globals without a lock:
  - `platforms.getattr`: vllm/platforms/__init__.py:317 checks, :319 assigns;
  - `vllm-config.set-current-vllm-config`: vllm/config/vllm.py:3431 reads, :3442 and :3469 assign.
  The new `hf-hub-resolver.resolve-lora` is marked the same way: hf_hub_resolver.py:41 checks, :42 assigns after
  an await.
- **internal-assertions: 71 → 11.**
  - `platforms` is tagged `cache`: `current` memoizes the resolved platform, and the host facts are read-only.
  - `vllm-config` is tagged `incidental`: create_engine_config returns the config and writes no global
    (arg_utils.py:2872), and `current` is restored when the context exits.
  - Assertions on those states, and on internal call counts, were deleted where `result` or `steps.*` already show
    the outcome.
  - Probe-loop asserts now count the boundary route calls in the trace.
  - The 11 that remain are commented: plugins' `plugins_loaded` guard, the envs cache and export, the platform
    cache hit, CPU-target probe skipping, and the xpu memory-op count.
- **Breaking changes:**
  - Callers that asserted `state.platforms` or `state['vllm-config']` expecting the hollow lint to require them
    (none outside this fragment; the oracle scenarios still pass).
  - `create-speculative-config` now returns `draft_tensor_parallel_size` and `draft_quantization` and takes
    `target_tensor_parallel_size`.
  - New hf-hub store stubs: `list-repo-files` and `snapshot-download`, on table `repos`.
- **Model additions:**
  - draft-model TP and quantization (speculative.py:1308, 1549-1555, 1711-1743);
  - `HfHubResolver.resolve_lora` (hf_hub_resolver.py:29-128). Only one trailing slash is stripped, which is
    enough for the tests.
- **Round-3 tests:** 3 of 6 pass. Tests 1, 3 and 6 test other areas' code (see `build-oracle/round3/config-platform.md`).

## Fix round 4 (coverage)

I edited `fragments/config-platform.yaml` directly (no generator).

**Blind findings fixed**
- oracle2 `test_needs_dp_coordination`: new `vllm-config.needs-dp-coordinator` (vllm.py:843-862); the resolved config
  carries `needs_dp_coordinator`, `model_config.is_moe` (model.py:2276-2277) and `parallel_config.data_parallel_external_lb`.
  Both oracle2 scenarios pass. Engine-core should start the DP coordinator from it (cross-area).
- oracle2 `test_fold_mm_processor_device`: new `multimodal-config` (init validation, `fold-mm-processor-device`,
  `get-mm-processor-device-type`, `compute-hash`) and `vllm-config.resolve-mm-processor-device` (vllm.py:2792-2840).
  ModelConfig builds a MultiModalConfig when the checkpoint has a `vision_config`/`audio_config` (stand-in for the
  registry's `supports_multimodal`, which models-layers' `ModelsModelInfo` lacks).
- oracle2 `test_language_model_only_affects_model_hash`: new `model-config.compute-hash` (model.py:453-514): every
  field except the ignored ones, plus `language_model_only` and video pruning for multimodal models only, as the code
  does. New `vllm-config.compute-hash` (vllm.py:449-565) is the compile-cache key over the sub-config hashes; flow
  `config-compile-cache-key`. kernels-ops' `vllm-backend.call` should call it.
- judge2 W3: `create-engine-config` passes `--scheduling-policy` (default: config `scheduling-policy`), not `fcfs`.
- judge2 execution-parallel #6: async scheduling resolves per speculative method; ngram turns it off. `config` is
  static, so a mismatch with the world's `async-scheduling` is recorded in `ctx.async_scheduling_config_mismatch`.
  A world serving ngram must set `async-scheduling: false` (scheduler-kv/coordinator). ngram/ngram_gpu no longer
  fetch a draft model; the prompt-lookup window defaults 5/5 or copies the given bound (speculative.py:1171-1220).
- Not mine: judge2 P4(c) (`api-server-entry.build-async-engine-client` forwards only `{model}`: serving-api);
  judge2 L8 world `max-cpu-loras` is defined in models-layers' fragment, though `config/lora.py` is my path: it should
  follow `max-loras` (lora.py:120-121).

**Coverage.** Old (by test area) report: reach 16% -> 33%. Owner report (`by-owner/`): 23% (93/407) -> 35% (143/413).
Top-25 owner rows: all modeled (`platforms.is-platform`, `has-device-capability`, `get-cpu-architecture`,
`cuda-platform.get-device-capability`, `rocm-platform.{on-arch,supports-fp8,fp8-dtype,device-count}`,
`quantization-config-args.init`, `scheduler-config.default-factory`, `hisparse-config.init`, `audio-asset`,
`video-asset`). Of the first (test-area) top 25, 17 rows are mine and modeled (image assets, CompilationMode in
`vllm-config.post-init`, `hf-config-override`, `disable-envs-cache`, every compute_hash, DeviceConfig, ECTransferConfig,
`nnodes-within-dp`, `config-utils.replace`, SupportsHash); declined: `ModelArchConfigConvertorBase.*` and its
`is_mm_prefix_lm` overrides (vllm/transformers_utils: serving-api), `FlatLogprobs.append` (vllm/logprobs.py: no
area; output data structure), `ECSharedRegion` (vllm/distributed: distributed). `vllm/scalar_type.py` (now listed
as mine): declined, numeric dtype descriptors for quantized kernels (kernels-ops-level work).

**Also modeled** (coordinator request): `cuda-platform.get-mla-prefill-backend-cls` (interface.py:435-514, was
attention's stub) and `cpu-platform.get-mla-prefill-backend-cls` (cpu.py:182-194).

**Breaking changes**
- `cuda-platform.get-mla-prefill-backend-cls` now validates candidates: attention's `attention-mla-prefill-select`
  step `cpu` (float32, no model) fails, because `mla-prefill-selector` always calls the CUDA platform. On CPU the code
  calls `CpuPlatform.get_mla_prefill_backend_cls`: attention should call `cpu-platform.get-mla-prefill-backend-cls`.
  This also blocks `mcheck --stage --accept` for my fragment.
- `ConfigEngineArgs`/`ConfigVllmConfig` gain fields (additive). `scheduler-config.post-init` `policy` is an enum.
- New shared-infra stubs: `local-disk.put-path` (table `paths`, rows may carry `meta`), `hf-hub.download-dataset-file`.

**Simulator notes.** Hashes are `sha256(json(...))` (vLLM: `json.dumps` with spaces, or `str(list)`), so only
equality matches vLLM. IrOp provider uuids (kernels-ops' registry) are inputs to `ir-op-priority-config.compute-hash`.

## Fix round 5 (precision)

I edited `fragments/config-platform.yaml` directly (no generator).

**Round-4 wrong claims fixed**
- judge3 L3-4(a): `model-config.get-and-verify-max-len` builds the code's message word for word: the derived length prints as a
  float when the config has RoPE parameters (`derived *= scaling_factor`, model.py:2585-2616), `model_max_length=None`, and the
  caution text follows (model.py:2645-2665). RoPE parameters now come from `rope_scaling`/`rope_parameters` (legacy `type`,
  legacy `mrope` -> default) or a plain `rope_theta` (transformers_utils/config.py:563-653), not a Llama default.
- judge3 L3-4(c): `engine-args.add-cli-args` applies the argparse type `_compute_kwargs` registers: human_readable_int_or_auto for
  --max-model-len, human_readable_int for the token budgets (arg_utils.py:389-405, argparse_utils.py:29-93).
  `create-engine-config` accepts the CLI text.
- judge3 L3-8(a): `model-config.get-diff-sampling-param` is now defined by its owner (model.py:1812-1901): generation config
  ('auto' / 'vllm' / a directory), --override-generation-config, the eight keys, max_new_tokens -> max_tokens, and the override
  warning text. New configs `generation-config`, `override-generation-config`.
- judge3 P3-7(c): CacheConfig takes `cache_dtype` (the CacheDType literal) and logs the validator's info (cache.py:39-59, 350-367).
- judge3 P3-4: new `vllm-config.max-concurrent-batches` (vllm.py:576-587); the resolved config carries `max_concurrent_batches`
  (engine-core should size its batch queue from it).
- oracle3 compose_draft_hf_overrides: `speculative-config.compose-draft-hf-overrides` (speculative.py:1083-1107), wired into
  `create-speculative-config`; new config `hf-overrides`; a dict override patches the target's HF config (model.py:605-619).
- oracle3 (minor): `observability-config.init` treats omitted fields as None; messages now match the validators.
- oracle3 side finding: `plugins.load-general-plugins` can run a plugin that calls `model-registry.register-model` with the
  entry point's `input`.

**New worlds**
- MoE: ModelConfig returns `num_experts` / `num_experts_per_tok` (model_arch_config_convertor.py:189-219, in the code's name
  order); ParallelConfig returns `is_moe_model`, `all2all_backend`, `use_sequence_parallel_moe`, `use_all2all`
  (parallel.py:533-539, 763-788). Variant fixture `config-platform-moe-host` (variant_of moe-mixtral-8x7b-tp2-ep) gives the host
  two GPUs.
- VL: `is_multimodal_model` and `vision_config` on the ModelConfig result.
- FP8: new `vllm-config.get-quantization-config` (vllm.py:885-920): minimum capability per method, Fp8Config activation dtypes,
  and Fp8Config.from_config/__init__ checks (fp8.py:95-175, base_config.py:182-189); resolved `quant_config`.
  `kv_cache_dtype` flows from `config['kv-cache-dtype']` (boundary copy, owner attention) into `cache_config.cache_dtype`.
- The flow `config-create-engine-config` reads `config['model']`, `quantization`, `kv-cache-dtype` and `hf-overrides`.

**Error-path sweep** (all 103 `fail`s checked against their raise sites). Corrected to the code's text: Invalid repository ID
(full multi-line text, quoted id), max_model_len positive (`Example:` suffix), Unknown quantization method (`Must be one of [...]`),
deprecated quantization (the code passes `%s` as a second ValueError arg, so str() is the tuple repr), World size (the ray/nnodes
hint), max_num_batched_tokens < max_model_len (middle sentence), --nnodes with non-mp backend (`; got ...` suffix), current-config
AssertionError (full text), selected attention backend (reasons list repr), no valid attention backend (full
AttentionSelectorConfig repr), no valid MLA prefill backend (`with MLAPrefillSelectorConfig(...)`), platform plugin conflicts (list
repr), platforms getattr/setattr and envs getattr (quoted names), IO processor plugin missing (quotes, available list), VLLM_PORT
(quotes, the URI hint's link), VLLM_WORKER_MULTIPROC_METHOD (quoted value and choices), QuantizationConfigArgs targets exclusivity
(`got targets=...`), xpu device strings (the three code branches), mm_processor_kwargs device (repr), pydantic field errors
(gpu_memory_utilization, cache_dtype, mm_hasher_algorithm, device_buffer_size, max_bytes) in pydantic's `1 validation error for
<Class>` format, observability buckets (repr'd family, bounds list, known families). Order of checks: observability's boolean
check now runs over every family before the per-family checks (mode='before').
Left approximate: pydantic wraps validator ValueErrors as "Value error, <text>" (the model keeps the inner text); CEL prints a
whole float like 0.0 as `0`, so pydantic `input_value=0.0` shows `0`; `console-scripts.vllm`'s argparse invalid-choice text depends
on the Python version (and the file is serving-api's).

**Breaking changes** (callers listed)
- `model-config.get-diff-sampling-param` now returns the generation config, not schema examples: serving-api's chat, completion
  and `llm.get-default-sampling-params` paths. In non-`full-*` worlds it returns {} until the coordinator moves the rows (below).
- ModelConfig no longer assumes llama3 RoPE when the config has no rope keys; the experts lookup follows the code's name order.
- Messages changed (above): scenarios asserting the old texts with `==` (none found outside this fragment; my own were updated).
- `cuda-platform.get-attn-backend-cls`'s "no valid backend" message now carries the full selector repr (attention's scenarios
  that match `contains('Reasons: {')` still pass).
- New response fields only (additive) on ConfigVllmConfig: `quant_config`, `max_concurrent_batches`, `cache_config.cache_dtype`,
  model_config expert/multimodal/dtype fields, parallel_config EP fields, compilation_config `cudagraph_mode`.

**Coordinator: fixtures**
- Move config-platform-seed's `hf-hub.generation_configs` rows into `fixtures.yaml` under `tp1-llama-8b` (Llama-3.1-8B and
  -70B: temperature 0.6, top_p 0.9), `fp8-llama-3-8b` (same plus max_length 4096) and `moe-mixtral-8x7b-tp2-ep` (no sampling
  keys), so plain worlds see them. Qwen2-VL's generation_config.json isn't seeded (values unverified).
- `model-is-multimodal` is ModelConfig.is_multimodal_model (model.py:1981-1982, my path), but serving-api and worker-runner
  name models-layers / serving-api as its owner and nobody defines it. I can define it if the coordinator assigns it to me.

**Cross-area**
- engine-core: size the batch queue from `max_concurrent_batches`; read the resolved `async_scheduling`; register the VllmConfig
  reducer (oracle3 mp-reducer).
- serving-api: `serve-subcommand.cmd` should accept the --max-model-len string (bench-l3-4c schema warning).
- models-layers: `bench-p3-7d` (fp8_e5m2 with an fp8 checkpoint) is the Attention layer's check.

**Round-5 tests:** 5 of 6 pass (two partial), 1 untranslatable (`build-oracle/round5/config-platform.md`).
- Round-3 test 2 (`r3-config-platform-2-draft-model-engine-args-tp`): its seeded Qwen3-1.7B-FP8 quantization_config gained the
  checkpoint's real `activation_scheme: dynamic` (and fmt/weight_block_size), because Fp8Config.from_config requires the key
  (fp8.py:161, base_config.py:182-189). The scenario's steps and expectations are unchanged; it passes again.

## Fix round 6 (mechanism coverage)

I edited `fragments/config-platform.yaml` directly (no generator).

**Mechanisms added**
- Runner and convert resolution: `model-config.get-runner-type`, `get-convert-type` (model.py:1270-1367, 2322-2364) with the refusals at model.py:703-725. `--runner auto` goes pooling for a sentence-transformers checkpoint, a registered pooling architecture, or the suffix table.
- Pooler config: `model-config.init-pooler-config` (user, sentence-transformers, registry default; sources recorded), `pooler-config.post-init` (removed parameters and tasks, logit_sigma, pooling_type), `model-config.get-pooling-config` with the new `hf-hub.download-pooling-config` (table `st_modules`).
- `model-config.attn-type` (model.py:2155-2172) from the registry default; `is-prefix-caching-supported` now reads the pooling types, and both support checks receive them.
- `model-config.get-head-size` (convertor:89-116) and `head_size` on ModelConfig; `model-config.get-and-verify-dtype` (model.py:2405-2500), so `--dtype` reaches ModelConfig.
- Multimodal: `model-config.supports-multimodal-inputs` (model.py:912-957), and `mm_processor_cache_type`, `mm_shm_cache_max_object_size_mb`, `limit_mm_per_prompt`, `enable_mm_embeds` pass through.
- Parallel: `eplb-config.init` (parallel.py:62-133), the EPLB communicator default (:1097-1115), `parallel-config.verify-args` with Ray (:1125-1146, ray_utils.py:272-278), `_api_process_count` checks (:519-531), `expert_placement_strategy`, `all2all_backend` forwarding, `use_batched_dp_moe` and its 256 default (arg_utils.py:3113-3117).
- `engine-args.resolve-kv-cache-dtype-string` (torch_utils.py:457-529), online `quant_config` through `weight-utils.get-quant-config`, the backend logs and `AttentionBackendEnum.` prefix in `cuda-platform.get-attn-backend-cls`.
- New configs: `seed`, `dtype`, `convert`, `pooler-config`, `eplb-config`, `expert-placement-strategy`, `api-server-count`, `ray-available`, `ray-import-error`, `nixl-available`, `vllm-mla-disable`, `mm-shm-cache-max-object-size-mb`, `data-parallel-external-lb`, `mm-encoder-attn-backend` (the last two read by models-layers, undefined before). `ray-available` and `nixl-available` are environment facts, not engine args.

**Unwritten fields:** `has_index_topk` is now returned by `model-config.post-init` (vllm.py:1800-1835 reads `hf_text_config.index_topk`).

**Approximations**
- The generate-runner refusal (model.py:713-717) is left out: models-layers' rows give `is_text_generation: false` for multimodal generators, which would refuse Qwen2-VL.
- ModelConfig reads the registry through `model-registry.resolve-model-cls` (same row, no subprocess): the code's `_ModelInfo` cache file is taken as warm, so the 1.5 s cold-cache subprocess and its cache write aren't charged to config resolution.
- A registry miss continues on the suffix defaults; the code's `_normalize_arch` and Transformers lookups are models-layers'.
- "registered" means the resolved architecture is in the list; its flags answer for every listed architecture (exact for single-architecture checkpoints).
- A hf row's `attn_type` still stands in for the registry's `is_hybrid` / `is_attention_free`, which `ModelsModelInfo` lacks.
- Note titles are static (simulator gap), so the backend success log is one `when`-gated note per CUDA backend; the auto-scan log with its list is in `ctx.attn_backend_log` and the note title has the placeholder.

**Breaking changes** (callers)
- `attn_type` and pooling types no longer read `seq_pooling_type` from the HF row (`build-oracle/round5` e5 passes through the registry).
- `parallel-config.post-init` takes `eplb_config`, not `eplb_num_redundant_experts`; the ray backend now needs `ray-available: true`.
- `config-create-engine-config` reads `runner`, `data-parallel-size` and `distributed-executor-backend` from config instead of literals.
- `--quantization fp8` with no checkpoint config: `quant_config.quant_method` is `online`.

**Coordinator: fixtures**
- None.
- `worlds.yaml` needs no new variant from me.

**Cross-area**
- serving-api: read `config['api-server-count']` in `serve-subcommand.cmd`.
- models-layers: `_normalize_arch` for unregistered `*ForSequenceClassification` (oracle4 classification); `is_text_generation` for multimodal rows; read `config['expert-placement-strategy']`.
- worker-runner: read `config['seed']`; `get-kv-cache-spec` should read the resolved `cache_config.cache_dtype` (Q4-6 d).

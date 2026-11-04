# Judge 4: execution-parallel

Blind judge, vLLM v0.32.0, merged model `examples/vllm/vllm.json`. Scenarios: `judge4/scenarios/P4-1.yaml` to `P4-8.yaml`.
They run with `go run ./internal/devtools/check -f examples/vllm/vllm.json -f examples/vllm/judge4/scenarios/<CASE>.yaml --no-mocks --scenario '^bench-p4'`.
A scenario's failing expectations are the evidence for the non-pass steps. Some steps are scored partial even though their scenario passes. In those cases the exact log text the step names isn't modeled anywhere (no note, state or output carries it).

**Totals:** 0 of 8 cases pass (fail 5, missing 3). **Steps: 8 / 35 pass** (partial 12, missing 10, fail 5).

## 1. Cases

| Case | Step | Verified expectation (correction?) | Score | Root cause | Evidence |
|---|---|---|---|---|---|
| P4-1 | a | As written. `parallel.py:1079-1080` gives `uni`. `UniProcExecutor` builds the worker in process. | pass | | `bench-p4-1-a`: backend uni, UniProcExecutor, init-device only on rank0, no mp init |
| | b | As written. mp is the default because Ray is not found (`parallel.py:1035-1077`). Names: `VllmWorker-{rank}` (`multiproc_executor.py:744-749`), `Worker_TP{n}` (`:1088-1103`). | partial | model: no process names or titles, no `Defaulting to use mp` | backend mp, 4 ranks init and load; output-rank reply is modeled (`engine-core-tp4-output-rank-replies`); name assertion fails |
| | c | As written (`cli/main.py:70-71`, `api_utils.py:164-166`, `system_utils.py:122-160`, `envs.py:956-958`) | missing | model: `cli_env_setup` and `_maybe_force_spawn` aren't modeled; only `envs.env-with-choices` (default fork) | spawn warning absent |
| | d | As written (`parallel.py:1143-1146`, `ray_utils.py:272-278`; the message has no space after the period) | fail | model: `parallel-config.post-init` omits `_verify_args` and `assert_ray_available` | config succeeds with backend `ray` |
| P4-2 | a | As written (`multiproc_executor.py:299-333`) | partial | model: the log text with `VllmWorker-2` and `exit code: -9` is not modeled | the kill at 9 s wakes monitor-workers (died_rank rank2), `is_failed`, shutdown |
| | b | **Corrected.** The death pipe closes, so idle survivors log `Parent process exited, terminating worker queues`, their busy loop ends, and they exit. SIGTERM is sent only to workers still alive after `VLLM_WORKER_SHUTDOWN_TIMEOUT_SECONDS`=5, and SIGKILL 4 s later (`:466-503`). Usually the result is `[shutdown] Executor: all workers exited gracefully`. | partial | model: death-pipe shutdown of survivors is right, with nothing killed. No log texts. Busy workers go straight to kill after 5+4 s, with no SIGTERM stage (`multiproc-executor.shutdown`). | `gpu-worker-impl.shutdown` on rank0, 1 and 3; `killed == []` |
| | c | As written (`core.py:1148-1151,1701-1702`, `multiproc_executor.py:398-399`) | pass | | `EXECUTOR_FAILED` callback; busy loop and later collective_rpc raise `Executor failed.` |
| | d | As written: only `response_mqs[0]` is dequeued. kv_output_aggregator is None without a connector (`abstract.py:128`), so RuntimeError comes back at once (`:404-449`). | fail | model: `multiproc-executor.collective-rpc` joins `need: all` over every rank even with `unique_reply_rank`. Ranks 1-3 block in the TP all-reduce, so the result is a TimeoutError after 300 s instead of RuntimeError. | `bench-p4-2-d`: loop error `timeout-error` at 300 s |
| | e | **Confirmed.** Rank 2 doesn't reply (`:1063-1066`). Rank 0 blocks in the TP all-reduce. `TimeoutError: RPC call to execute_model timed out.` comes after 300 s. The exception kills the engine core (`core.py:1508-1513`). | pass | | rank2 reply `replied:false`; collective timeout at about 300000 ms; `send-engine-dead` |
| P4-3 | a | As written (`model.py:1376-1442`, `fp8.py:158-175`) | pass | | quantization fp8, serialized, static, ignored `[lm_head]` |
| | b | **Corrected detail.** For fused layers the per-shard weight scales are also requantized to their max (`fp8_utils.py:1454-1479`, `w8a8_utils.py:75-105`). CUTLASS then broadcasts that single scale per channel (`cutlass.py:60-66`). The input scales collapse to their max (`fp8.py:397-399`). | partial | model: Fp8LinearMethod per linear, lm_head unquantized, Fp8KVCacheMethod and a CUTLASS forward are right. But the kernel is a `choice` taken by default, not computed from capability. No `Selected CutlassFP8ScaledMMLinearKernel for Fp8LinearMethod`, and no input_scale handling. | choice `kernel` origin default |
| | c | **Confirmed.** `cutlass_scaled_mm_supports_fp8(80)` is false (`csrc/.../scaled_mm_entry.cu:145-159`). Torch scaled_mm needs 89. Marlin wins and logs the warning (`marlin_utils_fp8.py:103-113`). | fail | model: `fp8-linear-method.apply` has no Marlin option and still picks CUTLASS on SM80 | forward fails `runtime-error` (`Expected a.scalar_type() == ...Char`) |
| P4-4 | a | As written (`weight_utils.py:347-356`) | partial | model: `weight-utils.get-quant-config` is right (deprecation note, OnlineQuantizationConfig fp8_per_tensor, no Fp8Config). But the VllmConfig's quant_config reports `quant_method: fp8`, not the `online` config that `_get_quantization_config` builds. | `bench-p4-4-a`, last expectation fails |
| | b | **Confirmed text:** `Quantizing 128 layers of types: mlp.down_proj: 32 (from linear: fp8_per_tensor_static); mlp.gate_up_proj: 32 (...); self_attn.o_proj: 32 (...); self_attn.qkv_proj: 32 (...)` (`online/base.py:172-198`, `config/quantization.py:35-48,91-104`) | missing | model: no online linear method, no layer summary, no timing log | `bench-p4-4-bc`: log assertion fails |
| | c | As written (`online/fp8.py:208-268`) | partial | model: the forward reaches CUTLASS, but through `fp8-linear-method.apply`. There is no per-tensor amax scale, no dynamic per-token activations and no log. | CUTLASS calls > 0 |
| | d | **Confirmed.** `EngineArgs.__post_init__` resolves `quantization_config` but keeps `quantization="fp8_per_tensor"` (`arg_utils.py:897-901`), so `_verify_quantization` raises the mismatch error | pass | | both d scenarios pass, with the exact message |
| P4-5 | a | As written (`fused_moe/config.py:1189-1236`) | partial | model: no `Worker_TP0_EP0` or `Worker_TP1_EP1` titles | MoE tp 1, ep 2, ep_rank 0 and 1 in state |
| | b | As written (`expert_map_manager.py:62-77,248-261,401-414`) | partial | model: no EP log line. Maps are computed per forward in `moe-runner`. | 4 local each; maps `[0..3,-1x4]` and `[-1x4,0..3]` |
| | c | **Confirmed.** No routed-output transform for Mixtral, so the late all-reduce applies (`moe_runner.py:455-517`) | pass | | `use_all2all` false, no dispatch or combine, all-reduce on rank0 |
| | d | As written | partial | model: no `Worker_TP0` or `Worker_TP1` titles | ep 1, moe_tp 2, 8 local experts, all-reduce |
| | e | As written (`mixtral.py:118-131`, `expert_map_manager.py:116-136`) | missing | model: no `expert_placement_strategy` config, and `determine_expert_placement_strategy` isn't modeled. `determine-expert-map` with round_robin returns a strided map. | config knob unknown; no warning |
| P4-6 | a | As written (`parallel.py:62-103,1097-1115`) | missing | model and world: EPLBConfig isn't modeled (window_size, step_interval, log_balancedness, policy, communicator). Only `num-redundant-experts` 0 exists. | `eplb_config` absent |
| | b | As written. ParallelConfig is built at `arg_utils.py:2528` before VllmConfig. Unverified: the error probably surfaces wrapped in a pydantic ValidationError ("Value error, ..."). | pass | | all three exact messages; `vllm-config.post-init` not called |
| | c | As written (`layer.py:257-268`) | fail | model: `mixtral-for-causal-lm.init` lacks the even-distribution check. One redundant expert loads with 9/2=4 local instead of ValueError. Two redundant experts give 5/10 correctly, but the log is absent. | `bench-p4-6-c2` load ok |
| | d | **Confirmed spacing:** `Rearranging experts (async mode) (profile)...` then `Rearranged experts  (profile)  in X s.` (`eplb_state.py:786-790,958-961`) | missing | model: `eplb-state` is a boundary stub; profile_run never steps EPLB | no eplb step in the profile run |
| | e | As written (`eplb_state.py:466-473,591-708`) | missing | model: EPLB step, recording window and rearrangement aren't modeled | as above |
| P4-7 | a | As written | pass | world: there is no 2-GPU VL world, so rank0 was driven with TP 2. Ranks are symmetric. | one tower call with 3 images, `tp == 2`; tokens 1000/250/250 |
| | b | **Confirmed** greedy split (4000 to rank0, 1000+1000 to rank1) (`vision.py:325-375`) | missing | model: data mode is never used. The tower is always TP-sharded, with no split, padding, all-gather or fallback warning. | data-mode assertions fail |
| | c | **Corrected (N, M):** max image tokens 16384 (max_pixels 12845056 / 28^2). Max video tokens 32768 (4 frames at seq_len 32768). The modality is **video**, N=**32768**, M=**1**: `...budget of 32768 tokens, and profiled with 1 video items...` (`qwen2_vl.py:980-1192`, `encoder_budget.py`, `encoder_cache_manager.py:316-361`). This assumes the checkpoint's preprocessor max_pixels. | missing | model: `gpu-model-runner.profile-run` cites `model_runner.py:991-1021` but omits the encoder-profile branch | no budget call or encoder run in profiling |
| | d | **Confirmed.** ViT head size 80 is supported by FA. Log `Using backend AttentionBackendEnum.FLASH_ATTN for vit attention` (`cuda.py:518-570`). | missing | model: no ViT backend selection; the tower is a latency stub | no vit-attn call |
| P4-8 | a | As written. FA3 on SM90. | partial | model: no `Using FLASH_ATTN attention backend out of potential backends: [...]` log | FlashAttentionBackend; fa_version 3 |
| | b | As written (`cuda.py:427-447`) | partial | model: no `Using AttentionBackendEnum.FLASHINFER backend.` log | one validate call; FlashInfer path |
| | c | **Confirmed reasons** `['head_size not supported', 'non-MLA not supported', 'compute capability not supported']`. **Corrected:** the startup error goes on with `Failed core proc(s): {...}` (`engine/utils.py:1431-1440`). | fail | model: the message says `Selected backend FLASHINFER_MLA` instead of `AttentionBackendEnum.FLASHINFER_MLA`. `engine-startup` succeeds with the flag, because startup never selects a backend. | sel message mismatch; startup ok |
| | d | As written (`dummy_loader.py:20-46`, `weight_utils.py:1544-1596`) | partial | model: DummyModelLoader with no download is right; uniform(-1e-3, 1e-3) with seed 1234 isn't modeled | `prepare-weights` 0 calls |
| | e | As written (`model.py:206`, `gpu_worker.py:521,1060-1064`, `torch_utils.py:542-553`, `sample/states.py:53-57`). Not fully confirmed that nothing else draws numpy randomness before the first request. | missing | model and world: no `seed` config. `sampler.add-request` stores seed 0 for every unseeded request. | `model_config.seed` absent |

## 2. Wrong claims in the model

1. `multiproc-executor.collective-rpc` (cites `multiproc_executor.py:382-456`) waits for every rank's branch even when `unique_reply_rank` is set. The code dequeues only `response_mqs[output_rank]` (`:421-423`). So a rank-0 failure under TP becomes a 300 s TimeoutError instead of an immediate RuntimeError (P4-2 d).
2. `fp8-linear-method.apply` decides the scaled-mm kernel as a `choice` defaulting to cutlass, while the cited `kernels/linear/__init__.py:726-810` computes it from capability. There is no Marlin path, so an FP8 checkpoint on an A100 fails in the CUTLASS dtype check (P4-3 c).
3. `cuda-platform.get-attn-backend-cls` formats `Selected backend <name>`, but the code interpolates the enum, which gives `AttentionBackendEnum.<NAME>` (`cuda.py:437,442`) (P4-8 c).
4. `parallel-config.post-init` doesn't validate Ray (`_verify_args`, `parallel.py:1143-1146`), so `ray` without Ray is accepted (P4-1 d).
5. `mixtral-for-causal-lm.init` sizes `num_local_physical_experts` with integer division and has no `global % ep != 0` check (`layer.py:257-264`) (P4-6 c).
6. `sampler.add-request` cites `sample/states.py:41-71` but stores seed 0 for unseeded requests. The code draws `np.random.randint` (`:55-56`).
7. `gpu-model-runner.profile-run` cites `model_runner.py:991-1021` but leaves out the encoder-cache profiling branch (`:992-1001`).
8. `vllm-config.get-quantization-config` returns `quant_method: fp8` for online `--quantization fp8`. The runtime builds `OnlineQuantizationConfig` (name `online`).

Citation sample (`--cite-sample 10 --seed 404`): 10 of 10 resolve and match their claims. Global count: 9925 citations cited, 9925 ok. In addition I read about 25 citations in this group's entities. Items 1-8 are the mismatches.

Coverage versus nearby citations: the executor and monitor, FP8 detection, MoE parallel config and the backend selector are modeled by real behaviors. Online quantization, EPLB stepping, encoder TP data mode, ViT backend selection and seeding only appear in summaries, or not at all.

## 3. Builder findings ("docs versus code")

The merged document records no docs-versus-code findings for this group's entities, so none could be confirmed or refuted.

## 4. Simulator gaps

None found. Every non-pass step is a model or world gap: no topology or config knob for a 2-GPU VL world, `expert_placement_strategy`, `seed`, EPLBConfig, or Ray availability. Rank collectives, worker kills, timeouts and per-instance state were all expressible (P4-2 e passes end to end).

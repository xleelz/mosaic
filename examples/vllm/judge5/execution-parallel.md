# Judge report: `execution-parallel` (vLLM 0.32, benchmark 5)

**Cases:** 0 pass / 8 (partial 2, missing 3, fail 3). **Steps: 8 pass / 34** (partial 12, missing 10, fail 4). Scenarios: `judge5/scenarios/P5-1.yaml` to `P5-8.yaml`, ids `bench-p5-<case>-<step>-*`.
A red scenario there records the verified expectation the model does not meet. Paths below are relative to the vLLM source root.

## 1. Cases

| Case | Case score | Corrected? | Root cause |
|---|---|---|---|
| P5-1 | missing | no | model |
| P5-2 | fail | confirmed (c) | model |
| P5-3 | fail | no | model |
| P5-4 | missing | confirmed (c) | model |
| P5-5 | partial | yes (d) | model |
| P5-6 | partial | yes (c) | model, world (no flag) |
| P5-7 | fail | confirmed (a), (d) | model |
| P5-8 | missing | yes (d) | model |

### Steps

| Step | Verified expectation | Score | Evidence (scenario suffix) and root cause |
|---|---|---|---|
| P5-1a | As written: `vllm/config/speculative.py:1121-1140`, then `eagle-` before `eagle3` at `:1326-1345` | **missing** | `a-*`, six scenarios all abort: `engine-args.create-speculative-config.behavior[1].if: ... no such key: method`. **model**: the interface reads `speculative_config.method`, with no inference, name detection or the "without speculative model" error. The flow `config-create-engine-config` aborts the same way (`a-flow-eagle3`) |
| P5-1b | As written: `:1289-1312,1393-1420,1712-1743` | partial | `b-draft-tp2` passes word for word, and the draft TP defaults to 1. `b-draft-config` fails: **model** returns no draft ModelConfig (`runner="draft"`, tokenizer, `spec_target_max_model_len`) and no `EAGLEConfig` wrap (`grep EAGLEConfig` finds nothing). Driven with an explicit `method` because of (a) |
| P5-1c | As written: `eagle3_utils.py:15-33`, `interfaces.py:1712-1733`, (2, 16, 29) for 32 layers | **missing** | `c-aux-layers`. No entity for `set_eagle3_aux_hidden_state_layers`; `grep auxiliary` finds only the unrelated routed-experts store |
| P5-1d | As written: `vllm/config/vllm.py:614-686`, `scheduler.py:344-356,570-589`, `speculative.py:1888-1925` | partial | `d-kv-lookahead` (`allocate-slots` gets `num_lookahead_tokens` 3) and `d-async-v2` pass. **model**: `uniform_decode_query_len` is only a seeded `cuda-graph-manager` state or a caller's input (`d-sizing-properties`); `num_prefill_lookahead_tokens`, the drafting-slot count and the step block margin `cdiv(7, 16)` have no entity |
| P5-1e | As written: `:1196-1221` | **pass** | `e-ngram-window`: 4 and 4, the exact error text, no draft fetch |
| P5-2a | As written: `vllm.py:702-738` | partial | `a-default-v2` runs `gpu-model-runner.init`. **model**: `use-v2-model-runner` is a fixed config value; the env, Triton and unsupported-feature decision isn't computed |
| P5-2b | As written: `speculative.py:1594-1610`, `vllm.py:729-736,2914-2930` | **fail** | `b-suffix-with-arctic`: with `speculative-method: suffix` and the default runner value, startup fails with `suffix is not supported yet.` where the code falls back to V1 and starts. `b-suffix-no-arctic` aborts (`no such key: model`). **model**: no `_validate_suffix_decoding` or `has_arctic_inference` ("arctic" finds nothing), no 24 default, no fallback warning |
| P5-2c | Confirmed: the env value returns first (`vllm.py:720-722`); suffix then fails at `model_runner.py:296` in `init_speculator`, `spec_decode/__init__.py:85-86`: `NotImplementedError("suffix is not supported yet.")` | partial | `c-forced-v2-flow`, `c-forced-v2-suffix`: the outcome, text and path match, with no warning. **model**: the "env before the unsupported check" ordering isn't modeled, so it passes only because nothing is ever unsupported |
| P5-2d | As written: `speculative.py:1109-1134,1230-1240` | **missing** | `d-custom-class` aborts. No `_is_custom_proposer_path` or `custom_class` anywhere |
| P5-3a | As written: `lora_utils.py:20-50`, `lora/utils.py:51-65`, `cudagraph_utils.py:198-222,300-312` | **missing** | `a-capture-cases`, `a-specialized`. No `lora_capture_cases`, no dispatch map; `num_active_loras` appears once, as a literal 0 in `forward-context.set-forward-context`. **world**: no `specialize-active-lora` or `cudagraph-specialize-lora` config, which the validator refused |
| P5-3b | As written: `config/lora.py:120-121`, `worker_manager.py:262-327` | **pass** | `b-lru` (ending `[3, 4]`, evicting 1 then 2, load before each add), `b-bad-load-keeps-cache`, `b-three-in-batch` (exact text, no add) |
| P5-3c | As written: `peft_helper.py:102-121` | **missing** | `c-scaling`. `load-adapter` returns id, rank and modules. No `lora_alpha / r`, rsLoRA or the log |
| P5-3d | As written: `peft_helper.py:102-112,188-202` | **fail** | `d-rank-pattern-high` and `d-rank-pattern-zero` both load successfully where the code raises. **model**: `validate-legal` compares only `input.r` |
| P5-3e | As written: `peft_helper.py:27-30,155-171` | **fail** | `e-missing-fields` loads successfully. **model**: `from-local-dir` returns the JSON without `from_dict`'s required-field check |
| P5-4a | As written: `qwen2_vl.py:1354-1388` | **pass** | `a-positions`: all three axes, in the code's grid order |
| P5-4b | As written. Delta at `:1387-1390`; `rope.py:144-192` confirms `orig_pos + delta` for decode | partial | `b-delta` gives -760. `b-decode-position`: **model** `rope-state.prepare-positions` is a kernel stub returning no positions, so 65 can't be read |
| P5-4c | Confirmed: `rope.py:40-75`, (3072, 32768) int32 = 402653184 bytes, UVA-backed; the kernel adds the delta | **missing** | `c-storage`, `c-add-request`. **model**: no `init_prefill_positions` or storage, and no behavior calls `get-mrope-input-positions`: the runner never computes positions for an added request |
| P5-4d | As written: `qwen2_vl.py:1362-1379` | **pass** | `d-two-images` |
| P5-5a | As written: `special.py:29-35`, `poolers.py:97-108`, `model.py:2090-2116` | partial | `a-embed`: tasks, LAST at token index 7, dim 4096, normalized, no sampler or logits, all right. **model**: the fp32 head isn't in the output; `head_dtype` appears only in a component summary |
| P5-5b | As written: `heads.py:84-117` | **pass** | `b-no-activation` |
| P5-5c | As written: `pooling_runner.py:138-165`, `v1/pool/metadata.py:35` | **pass** | `c-chunks`: 8192, 8192, 3616; the pooler runs 3 times; mask false, false, true; output only on the last |
| P5-5d | **Corrected**: the runner's text is right (`pooling_runner.py:73-78`), but a served request is refused earlier: by `/pooling` (`entrypoints/pooling/pooling/serving.py:61-86`) and by `EngineCore.add_request` with a different text, no period (`v1/engine/core.py:525-529`) | **pass** | `d-classify-runner` (exact text through `add-requests`), `d-engine-core-first` (the runner isn't reached) |
| P5-6a | As written: `parallel_state.py:2135-2141,2289-2320` | partial | `a-init-device-ismoe`, `a-ep-from-moe-not-flag` pass, and sizes are right. `a-groups`: **model** keeps `world_size` per group, not the rank lists `[[0, 1]]`, `[[0], [1]]` |
| P5-6b | As written: `:2348-2365` | **pass** | `b-logs`, `b-dense-log`, word for word |
| P5-6c | **Corrected**: FlashInfer precedes custom all-reduce and is on by default (`envs.py:278,1970`, `cuda_communicator.py:362-368,392-396,407-415`). With it available, the 8 KiB decode goes to FlashInfer; 8 KiB only *qualifies* for custom, which runs with FlashInfer off or absent. 64 MiB fails `inp_size < max_size`. Max size is `min(64 MiB, 8 MiB)` on 9.0 | partial | `c-flashinfer-first`, `c-custom-eligibility`, `c-disable` pass. **model**: no group-name gate (`c-tp-only`); nothing reads the flag: `set_custom_all_reduce(not disable_custom_all_reduce)` at `gpu_worker.py:1656` isn't in `init-device` (`c-init-device-reads-flag`), and there is no such config (**world**) |
| P5-6d | As written: `:2322-2345` | partial | `d-eplb`: size 2 and both log endings right; no rank list |
| P5-7a | Confirmed: `model_runner.py:273,435-438,518-524`, `structured_outputs.py:72-90`; 16416768 and 65667072 bytes | **missing** | `a-buffer`, `a-buffer-spec`. `structured-outputs-worker` has no state |
| P5-7b | As written: `structured_outputs.py:10-31,92-158,163-206` | partial | `b-mixed`: only the structured request is masked, one kernel launch. **model**: no `req_idx x mask_stride + position` mapping and no `-inf` store |
| P5-7c | As written: `structured_outputs.py:10-31,163-206`; `num_masks == len(mapping)` | **fail** | `c-drafts`: **model** launches the kernel with `num_rows` 1 (requests, not rows) where the code has 3, even when given a 3-row bitmask. No inactive-position rule |
| P5-7d | Confirmed: the mask is in place at `model_runner.py:1620-1628`, and `sampler.py:88-89` computes raw logprobs from those logits | partial | `d-order` (mask before sampler), `d-clamp` (5 entries, floor -9999.0). **model**: the mask never produces `-inf` logprobs; driven with -1e300. See simulator gaps |
| P5-8a | As written: `model_runner.py:264-267,1928-1962`, `default.py:100-133` | **missing** | `a-on-flag`: `enable-prompt-embeds` has no effect on the runner (only `hf-renderer.render-messages` reads it). `uses_prompt_embeds` is an unrelated model state. No `embed_input_ids` for Llama, no `input_ids=None`; the forward input has neither field |
| P5-8b | As written: `default.py:123-133`, `prompt_embeds.py:70-152` | **missing** | `b-mixed-batch`, state-driven: `prompt-embeds-state.apply` runs as a stub; no per-request rows |
| P5-8c | As written: `prompt_embeds.py:99-150` | partial | `c-scheduler-chunks` gives 8192 then 1808, and `apply` gets those sizes. `c-chunks`: **model** has no overlay offset |
| P5-8d | **Corrected**: for a pure-embeds prompt, `EngineCoreRequest.prompt_token_ids` is `None` and there is no prompt-length field (`v1/engine/__init__.py:116-130`). The length is derived (`utils/__init__.py:15-27`), and `Request._all_token_ids = [0] * N` holds the placeholders (`v1/request.py:143-148`). CPU cast at `renderers/base.py:972-1000` | **missing** | `d-engine-request`: `input-processor.process-inputs` drops `prompt_embeds` from its return. `d-renderer-off`: no refusal |

## 2. Wrong claims in the model

Group citations read next to the code: over 15, listed here and in the table. Random sample `--cite-sample 12 --seed 505`: all 12 resolve and say what the cited code does; `citations: 11193 ok`.

1. `peft-helper.validate-legal`: the summary says "including rank_pattern"; the behavior checks only `input.r` (`peft_helper.py:193`). Adapters the code refuses load.
2. `peft-helper.from-local-dir`: "parse it", citing lines ending `return cls.from_dict(config)` (`:176-186`). It skips the required-field check and `__post_init__`.
3. Config `use-v2-model-runner`: its summary says V2 "unless a feature it lacks is configured"; it never changes, so suffix startup fails instead of falling back (`vllm.py:729-736`).
4. `engine-args.create-speculative-config`: cited for `SpeculativeConfig`, but it requires a `method` key the code infers (`speculative.py:1121-1140`).
5. `structured-outputs-worker.apply-grammar-bitmask`: kernel `num_rows` counts requests; the code's grid is per position (`structured_outputs.py:137-141`).
6. `base-renderer.process-singleton`: the summary says an embeds prompt "goes to _process_embeds"; the behavior returns it as is, skipping the flag refusal, the squeeze and the shape check (`renderers/base.py:972-990`).
7. `gpu-model-runner.execute-model` step 24 cites `model_runner.py:1931-1960` but tests a state flag, not `uses_inputs_embeds` derived from `enable_prompt_embeds`.
8. `custom-allreduce.init`: max size is fixed to the 9.0 table, regardless of capability or `symm_mem_enabled` (`custom_all_reduce.py:241-254`). Harmless on the H100 worlds.

Entry points without a modeling entity: `set_eagle3_aux_hidden_state_layers`, `get_lora_capture_cases`, `_validate_suffix_decoding`, `_is_custom_proposer_path`, `PEFTHelper.from_dict`, `RopeState.init_prefill_positions`, `_build_grammar_mapping`. `get_mrope_input_positions` is modeled correctly but unreached from the runner.

## 3. Builder findings

Not assessed. The builders' "docs versus code" notes live under `notes/**`, which the blind rules forbid, and a search of the merged model for docs-versus-code wording found none.

## 4. Simulator gaps

- **Non-finite numbers** (P5-7d): scenario YAML refuses `-.inf` (`unsupported number "-.inf"`), so a `-inf` logprob can't be an input. Minor: -1e300 stands in, and the step's shortfall is the model's.

No step scored sim-gap. Every shortfall can be expressed in mosaic; the entities or decisions are absent.

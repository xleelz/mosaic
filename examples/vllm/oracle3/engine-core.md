# Oracle round 3: engine-core

Run: `check -f examples/vllm/vllm.json -f examples/vllm/oracle3/engine-core.yaml --no-mocks --lint hollow -v`.
The first scenario names an interface the model lacks, so `check` refuses the whole file
(`unknown interface "engine-core.get-kv-cache-group-metadata"`). The other two were run from a copy
without it: both fail, 0 passed. Hollow lint: clean.

| Test | Behavior | Scenario | Verdict | At fault / missing | Evidence |
|---|---|---|---|---|---|
| tests/v1/engine/test_kv_cache_group_metadata.py:56 | `EngineCore.get_kv_cache_group_metadata` reports per group `{group_idx, kind, block_size, sliding_window}`, where block_size is the single-type manager's: the MLA group is scaled by DCP (1536 x 8 = 12288) and the Mamba group isn't (1536) | oracle-engine-core-kv-cache-group-metadata-dcp | model-bug (missing) | engine-core: no `engine-core.get-kv-cache-group-metadata`; `kv-cache-manager` state holds `kv_cache_groups[].block_size` but no DCP scaling per spec kind | code vllm/v1/engine/core.py:482-506; validation error: unknown interface |
| tests/v1/engine/test_llm_engine.py:25 | `LLMEngine.step` calls `renderer.mm_processor_cache.invalidate(h)` for each `mm_cache_miss_hashes` entry of each EngineCoreOutput, in order, then returns the request outputs | oracle-engine-core-step-invalidates-mm-cache-misses | model-bug | engine-core: `llm-engine.step` behavior goes from `output-processor.process-outputs` straight to `sync-mp-client.abort-requests`; it never calls `lru-key-replicated-sender-cache.invalidate` (which exists), and `EngineCoreOutput` has no `mm_cache_miss_hashes` | code vllm/v1/engine/llm_engine.py:341-346; run: step returns `[]` (ok), no invalidate call, seeded entries remain |
| tests/engine/test_short_mm_context.py:21 | With max_model_len=579, an image prompt (576 image tokens plus text) fails `_validate_prompt_len` with VLLMValidationError "...longer than the maximum model length..." | oracle-engine-core-context-length-too-short-mm | model-bug | serving-api: `llm.add-completion-requests` passes only `{prompt}` to `base-renderer.tokenize-prompt` and drops `multi_modal_data`, so image placeholder tokens never count toward the prompt length; `input-processor.process-inputs` validation (engine-core) is right | code vllm/renderers/base.py:948-951 (`_process_tokens` expands multi_modal_data), vllm/v1/engine/input_processor.py:574-591; run: generate status ok, value `[]`, add-request reached the engine |

Counts: pass 0, model-bug 3, test-mismatch 0, sim-gap 0, untranslatable 0.
The LLaVA model and image numerics are approximated: the world is Llama text-only, so test 3 checks
only that multimodal tokens enter the prompt length, not the 576 feature size.

## Fix requests

### engine-core
1. Add `engine-core.get-kv-cache-group-metadata` (core.py:482-506): `[]` when the scheduler has no
   kv_cache_config; otherwise one `{group_idx, kind, block_size, sliding_window}` per group, with
   block_size the single-type manager's. Make `kv-cache-manager` derive each group's effective block
   size from `decode-context-parallel-size` (attention specs scaled by the DCP world size, Mamba
   not; kv_cache_manager.py / kv_cache_coordinator.py), so the scenario's seeded 1536/1536 reports
   12288/1536.
2. `llm-engine.step`: after process-outputs, for each output's `mm_cache_miss_hashes` call the
   renderer's mm processor cache `invalidate` (llm_engine.py:341-346), when the cache is configured;
   add `mm_cache_miss_hashes` to the `EngineCoreOutput` schema. Check the async path (AsyncLLM
   output handler) does the same.

### serving-api
3. `llm.add-completion-requests` / `base-renderer.tokenize-prompt`: keep `multi_modal_data` on a
   prompt dict and run the multimodal processing (renderers/base.py:948-951) so placeholder tokens
   are part of `prompt_token_ids` before `llm-engine.add-request`; then the existing length check
   refuses an image prompt over `max-model-len`.

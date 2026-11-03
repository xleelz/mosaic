# vLLM fix round 4: earlier measures re-run at merge

Re-run unedited on the merged model (skeleton, fixtures, worlds, all fragments) against the HEAD
model of round 3 (`acd07a3`):

| Measure | Round 3 (HEAD) | Round 4 merge |
|---|---|---|
| judge | 40/43 | 38/43 |
| judge2 | 31/58 | 53/58 |
| oracle | 19/19 | 19/19 |
| oracle2 | 3/20 | 10/20 |
| build-oracle round 3 | 37/37 | 37/37 |
| build-oracle round 4 | - | 50/50 |

V2, V5 and X4 already failed at HEAD (`reconcile/round3/coordinator-x4.md`).

## Scenarios to adapt (the model follows the code)

- **Judge V3** (`bench-v3`, `max_tokens: 16` with `max_model_len: 10`). The chat request now fails
  in `TokenizeParams.__post_init__` before the prompt length check:
  `ChatCompletionRequest.build_tok_params` passes `max_output_tokens=self.max_tokens` and
  `max_total_tokens=model_config.max_model_len` (chat_completion/protocol.py:657-675), and
  `max_output_tokens > max_total_tokens` raises
  `VLLMValidationError("max_tokens=16 cannot be greater than max_model_len=10. ...")`
  (renderers/params.py:256-268), a 400. The 400 is right. To test the prompt-length message
  (params.py:515-537) the scenario must ask for `max_tokens <= 10`.
- **Judge E6** (`bench-e6`) reads `state['kv-cache-manager'].prefix_cache_stats` after the steps.
  `Scheduler.make_stats` calls `kv_cache_manager.make_prefix_cache_stats()` every step
  (scheduler.py:2925), which returns the stats and resets them to a fresh `PrefixCacheStats()`
  (kv_cache_manager.py:236-247). The counters therefore read 0 after the step that reported them.
  The scenario should read `scheduler_stats.prefix_cache_stats` from the step outputs
  (scheduler-kv notes, round 4).

## Fixed at merge

- **Judge E1** (`bench-e1-tp4`): `build-async-engine-client` now forwards `--tensor-parallel-size`,
  so `ParallelConfig` checks the world size against the host's devices. The merged tp4 world now
  declares four GPUs (`engine-core-tp4-llama-70b-host`, a variant of `tp4-llama-70b`; the world
  in `fixtures.yaml` says the same).
- **Oracle `oracle-serving-api-cohere-structural-tag-not-modified`** and
  **`serving-api-tool-calling-required`**: engine-core passes
  `scheduler.get-grammar-bitmask` to `sample-tokens` on the sync and the batch-queue path, and the
  async scheduler sets `pending_structured_output_tokens`, so sampling waits for the previous
  step's tokens before it fills the bitmask (core.py:668-676, 737-750, 790-808;
  async_scheduler.py:31-38).

# Oracle 4: worker-runner

Snapshot: vLLM v0.32.0 (`/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`). Model: `examples/vllm/vllm.json`.
Fragment: `oracle4/worker-runner.yaml`. All three scenarios validate (0 errors, 0 warnings), pass
`--no-mocks --lint hollow`, and fail on the expectations below.

| Test | Behavior | Scenario | Verdict | Entity at fault / missing feature | Evidence |
|---|---|---|---|---|---|
| `tests/v1/sample/test_logprobs.py:322` `test_get_logprobs_and_prompt_logprobs` | A request with `logprobs=k` gets one sample-logprobs position per generated token, each with k entries (k+1 when the sampled token is outside the top k) that include the sampled token, plus a cumulative logprob; with `prompt_logprobs` it gets one entry per prompt position, the first None; a request with neither gets None for both | `oracle-worker-runner-get-logprobs-and-prompt-logprobs` | model-bug | worker-runner: `sampler.sample` / `gpu-model-runner.sample-tokens` compute top-k scores (`logprob.compute-topk-scores`) and prompt logprobs (`prompt-logprobs-worker.compute-prompt-logprobs`) but return neither in the ModelRunnerOutput (only `sampled_token_ids`). scheduler-kv: `Scheduler.update_from_output` never sets `new_logprobs` / `new_prompt_logprobs_tensors` on EngineCoreOutput. So `output-processor.process-outputs` never calls `logprobs-processor.update-sample-logprobs`, and LLM.generate returns `logprobs: null`, `cumulative_logprob: null` and no `prompt_logprobs` though both were requested. HF numeric comparisons are untranslatable and left out | Run: `steps.lp` value `completions[0].logprobs == null`, no `prompt_logprobs` key; no `logprobs-processor.update-sample-logprobs` call in the trace. Code: `vllm/v1/worker/gpu/sample/sampler.py:171-218` (logprobs_tensors returned in SamplerOutput), `vllm/v1/worker/gpu/model_runner.py:2088`/`2150-2176` (sample_tokens puts logprobs and prompt_logprobs_dict in ModelRunnerOutput), `vllm/v1/core/sched/scheduler.py:2156-2270` (`new_logprobs = logprobs.slice_request(...)`, `new_prompt_logprobs_tensors=...`), `vllm/v1/engine/output_processor.py:784-785` |
| `tests/v1/worker/test_mamba_hybrid_model_state.py:26` `test_prepare_attn_forwards_positions` | `MambaHybridModelState.prepare_attn` passes `input_batch.positions` to `build_attn_metadata` and returns its metadata | `oracle-worker-runner-prepare-attn-forwards-positions` | model-bug | worker-runner: `gpu-model-runner.execute-model` collapses `model_state.prepare_attn -> build_attn_metadata` into one direct call to `flash-attention-metadata-builder.build` whose input has no `positions`, for hybrid models too; `MambaHybridModelState.prepare_attn` (is_prefilling, num_accepted_tokens, num_decode_draft_tokens, aligned state indices) is not modeled | Run: the build call is in the trace, but no build call carries `input.positions`. Code: `vllm/v1/worker/gpu/model_states/mamba_hybrid.py:230-341` (`positions=input_batch.positions` at `:339`), `vllm/v1/worker/gpu/attn_utils.py:472` (`build_attn_metadata(..., positions=...)`). Model: `gpu-model-runner.execute-model` step "Build attention metadata (model_state.prepare_attn -> build_attn_metadata)" (`model_runner.py:1915-1926`) |
| `tests/samplers/test_no_bad_words.py:52` `TestOneTokenBadWord::test_one_token_bad_word` | Greedy output's first token is T; with `bad_words=[T's text]` the output never contains T | `oracle-worker-runner-one-token-bad-word` | model-bug | worker-runner: `sampler.apply-sampling-params` returns sampled tokens from the prompt-hash stand-in and ignores the bad-words mask it just computed, so a masked token is still sampled. `bad-words-state.add-request`, `.apply` and `.bad-words-kernel` run and report `masked` containing T, yet the banned run emits T again. Also (engine-core/serving-api): `SamplingParams.update_from_tokenizer` is not modeled, so `bad_words` given as text is dropped before the worker (the scenario passes `bad_words_token_ids` to isolate the sampler) | Run: `steps.plain` and `steps.banned` both return the same first token T; trace shows `bad-words-state.apply` with non-empty `masked`. Code: `vllm/v1/worker/gpu/sample/bad_words.py:79-91`, `:165` (`tl.store(... -inf)` on the bad word's last token, so the Gumbel argmax cannot pick it), `vllm/sampling_params.py:802` (`update_from_tokenizer`), `vllm/v1/engine/input_processor.py:494` |

Totals: pass 0, model-bug 3, test-mismatch 0, sim-gap 0, untranslatable 0.

## Fix requests

### worker-runner

1. **Return logprobs from the worker.** `sampler.sample` should return `logprobs_tensors` (per row:
   the sampled token first with its rank, then the top-k ids with ranks 1..k) when any row asks for
   logprobs, and `gpu-model-runner.sample-tokens` should put them, and the prompt logprobs from
   `prompt-logprobs-worker.compute-prompt-logprobs` (one row per prompt position after the first),
   into the ModelRunnerOutput (`model_runner.py:2088-2180`, `sampler.py:171-218`).
2. **Bad words must change the sample.** In `sampler.apply-sampling-params`, a row whose stand-in
   token is in that row's `masked` set (the bad-words mask, likewise `allowed_token_ids` and a
   logit-bias of -inf) must pick another deterministic token, as the -inf logit does in
   `bad_words.py:165` before the Gumbel argmax.
3. **Positions reach attention metadata; hybrid prepare_attn.** Pass the batch's positions into the
   attention-metadata build in `gpu-model-runner.execute-model`, and route hybrid models through
   `mamba-hybrid-model-state.prepare-attn` (`mamba_hybrid.py:230-341`), which builds
   `MambaHybridAttnMetadata` and calls `build_attn_metadata(..., positions=input_batch.positions)`.

### scheduler-kv

4. **Forward logprobs in update_from_output.** `Scheduler.update_from_output` should slice the
   runner's logprobs per request into `EngineCoreOutput.new_logprobs` and pass
   `new_prompt_logprobs_tensors` (`scheduler.py:2156-2270`), so `output-processor.process-outputs`
   reaches `logprobs-processor.update-sample-logprobs` and the prompt-logprobs update.

### engine-core

5. **Prompt logprobs and bad-word tokenization in the output/input path.** Add the prompt-logprobs
   update to `logprobs-processor` (first position None, one dict per later prompt token, rank of the
   actual prompt token) and model `SamplingParams.update_from_tokenizer` in the input processor
   (`input_processor.py:494`, `sampling_params.py:802`) so text `bad_words` become
   `bad_words_token_ids` before reaching the worker.

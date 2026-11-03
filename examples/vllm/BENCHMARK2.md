# vLLM 0.32 benchmark 2: a blind re-measurement of the generated ontology

The builders never see this file. The first benchmark (`BENCHMARK.md`) was visible during fix
rounds, so it no longer measures the model honestly. This file has no case in common with it.
It lists well-known behaviors of vllm-project/vllm at v0.32.0 (the V1 engine). Each is written so
that it can run as a mosaic scenario against the merged ontology (`examples/vllm/vllm.json`).

**Verify each case against the code before scoring it.** The expectations below come from the
v0.32.0 docs (`docs/`, the README, the OpenAI-compatible server page) and common knowledge. Any of
them can be wrong for v0.32.0 with the default engine args. A judge first confirms or corrects each
step from the code, citing file and line. Only then is the ontology scored against the corrected
expectation. A corrected step keeps its letter; note the correction next to the score.

**Default world:** `full-tp1-llama-8b`.
- One 80 GB GPU (rank0) serving Llama-3.1-8B-Instruct as `llama-8b`, with `max_model_len` 131072
  (from the HF config).
- The default engine args: block size 16, max_num_seqs 128, max_num_batched_tokens 2048, chunked
  prefill on, prefix caching on, policy fcfs, gpu_memory_utilization 0.92, no speculative
  decoding, LoRA off.
- Other worlds: `full-tp4-llama-70b`, `full-small-batch-limits`, `full-prefix-caching-off`, plus
  the area fixtures, such as scheduler-kv's nearly-full and prefix-warm worlds.
- Some cases name an engine-arg variant (say `--enable-lora`, a `speculative_config`, or
  `policy: priority`). Select it through the world's inputs or `choices`. If no world can express
  the variant without a model edit, score the steps that depend on it **partial** and name the
  missing knob.

## Scoring

Each case is broken into lettered steps, (a), (b), (c) and so on. Score every step separately,
using this scale:

| Score | Meaning |
|---|---|
| **pass** | The verified outcome **and** the code's path are reproduced: the right processes or ranks, messages and decisions |
| **partial** | The outcome is right, but the path is wrong or incomplete; or the behavior is modeled but can't be driven without an edit (say which) |
| **sim-gap** | The behavior is modeled as well as mosaic allows. Name the missing feature |
| **missing** | The behavior isn't modeled |
| **fail** | The model produces a different outcome |

**Case score (worst step).** A case scores its worst step, in the order
pass > partial > sim-gap > missing > fail. A case with steps (a) pass, (b) partial, (c) pass
scores partial. A case passes only when every step passes.

**Step-level pass count.** Count the steps scored pass, and report it as `passed / total` per group
and overall, next to the case-level counts. This file has 32 cases and 105 steps: `serving` 11 cases
and 37 steps, `scheduling-kv` 8 and 24, `execution-parallel` 5 and 16, `engine-lifecycle` 8 and 28. The step count shows progress
that the worst-step rule hides. It is not a substitute for the case score.

Write each case's scenario at `judge2/scenarios/<ID>.yaml`, using fixtures, inputs, `choices`,
`faults` and `steps` only. No mocks, and no model edits. Give each step its own expectation, so a
step can be scored from the run's summary or trace.

## Serving (`serving`)

The OpenAI-compatible API's request and response shapes, stop and EOS handling, `max_tokens`
validation, detokenization and structured outputs.

| ID | Behavior | Expected outcome |
|---|---|---|
| S1 | `POST /v1/completions` (non-streaming, `prompt: "Hello"`, no `max_tokens`) | (a) `max_tokens` defaults to 16 for the completions API (unlike chat, which defaults to the rest of the context). (b) The response has `id` starting `cmpl-`, `object: "text_completion"`, `created`, `model: "llama-8b"`, and `choices[0]` with `index: 0`, `text`, `logprobs: null`, `finish_reason` and `stop_reason`. (c) `usage` has `prompt_tokens`, `completion_tokens` and `total_tokens`, with `total_tokens = prompt_tokens + completion_tokens` |
| S2 | Streaming chat with `stream_options: {include_usage: true}` | (a) Every SSE event is `data: {...}` with `object: "chat.completion.chunk"` and the same `id` (`chatcmpl-...`) in every chunk. (b) The first chunk's delta carries `role: "assistant"`; later chunks carry `delta.content` pieces, with `finish_reason: null` until the last content chunk. (c) The last content chunk carries `finish_reason`. (d) Then one extra chunk with `choices: []` and the `usage` object, then `data: [DONE]`. (e) Without `stream_options`, no chunk carries `usage`. (f) Adding `continuous_usage_stats: true` puts `usage` on every chunk, with `completion_tokens` growing monotonically and `prompt_tokens` constant |
| S3 | The model emits its EOS token (`<|eot_id|>`) at token 5 of `max_tokens: 64` | (a) The engine core stops the request (`FINISHED_STOPPED`) in `update_from_output` by checking the sampled token against the EOS id. (b) The response has `finish_reason: "stop"` and `stop_reason: null`. (c) The EOS token's text isn't in `content` (special tokens are skipped by default). (d) Its blocks are freed in the same step |
| S4 | `stop_token_ids: [128009]`, `stop: ["\n\n"]`, and the stop string arrives first | (a) A stop string match gives `finish_reason: "stop"` with `stop_reason: "\n\n"` (the matched string), and the string is truncated from the text. (b) The matching happens in the API process's output processor (detokenizer), not the scheduler, and the engine core is told to abort the request. (c) Had a stop token id hit first, `stop_reason` would be the integer id `128009` and the check would run in the engine core's scheduler |
| S5 | `ignore_eos: true, max_tokens: 32`, then `min_tokens: 8` with an EOS sampled at token 3 | (a) With `ignore_eos`, exactly 32 tokens come back and `finish_reason` is `"length"`, even though EOS was sampled. (b) With `min_tokens: 8`, EOS (and the stop token ids) are masked out of the logits for the first 8 tokens, so the earliest stop is token 9 or later |
| S6 | `max_tokens` validation: `max_tokens: 0`, then `min_tokens: 10, max_tokens: 5`, then chat with both `max_tokens: 100` and `max_completion_tokens: 20`; then `stream_options` without streaming | (a) `max_tokens: 0` gives 400 (`max_tokens must be at least 1`). (b) `min_tokens > max_tokens` gives 400. (c) When both are sent to chat, `max_completion_tokens` wins and 20 is the limit. (d) `stream_options` with `stream: false` gives 400 (`Stream options can only be defined when stream=True`). Every rejection comes back as an `ErrorResponse` (`error.type`, `error.message`, `error.param`, `error.code: 400`) before the engine core sees the request |
| S7 | `max_tokens` against the context: `max_tokens: 200000` with a short prompt; then a 131000-token prompt with `max_tokens: 1000`; then a prompt of exactly 131072 tokens | (a) `max_tokens` above `max_model_len` gives 400 (`max_tokens=200000 cannot be greater than max_model_len=131072`). (b) Prompt plus `max_tokens` over `max_model_len`, with `max_tokens` itself in range, is not rejected: `max_tokens` is clamped to `max_model_len - prompt_len` (72), and the request ends with `finish_reason: "length"` after 72 tokens. (c) A prompt of exactly `max_model_len` tokens is rejected with 400, because no room is left for one output token |
| S8 | Detokenization across token boundaries (streaming) | (a) A multi-byte UTF-8 character (an emoji split across two byte-level tokens) is held back by the incremental detokenizer until it completes. No chunk carries a lone `U+FFFD`. (b) With `stop: ["END"]` and output `...xEN` then `D`, the streamed text never shows `EN`: the output processor holds back `len(stop) - 1` characters until it knows they aren't part of a stop string. (c) With `include_stop_str_in_output: true`, the final text keeps `END` |
| S9 | Detokenization of special tokens | (a) By default (`skip_special_tokens: true`), special tokens the model emits are dropped from the text but still counted in `completion_tokens`. (b) With `skip_special_tokens: false`, they appear in the text verbatim. (c) `logprobs: true, top_logprobs: 3` returns per-token `logprobs.content[i]` with `token`, `logprob`, `bytes` and 3 `top_logprobs`; `top_logprobs: 25` (over `max_logprobs` 20) is rejected with 400 |
| S10 | Structured outputs: `structured_outputs: {choice: ["positive", "negative"]}`, then `response_format: {type: "json_schema", json_schema: {...}}` | (a) The request enters the scheduler's waiting queue as `WAITING_FOR_STRUCTURED_OUTPUT_GRAMMAR` while the grammar compiles asynchronously (backend `auto`, xgrammar for these), and isn't scheduled until compilation finishes. (b) Each step, the scheduler sends the grammar bitmask, the model runner applies it to the logits before sampling, and the accepted token advances the grammar's FSM. (c) The output is exactly one of the choices, or JSON valid against the schema. (d) `finish_reason` is `"stop"` once the grammar terminates |
| S11 | Structured outputs failures: a malformed JSON schema; `max_tokens: 5` with a schema needing more | (a) A schema the backend can't compile is rejected with 400 and no generation runs. (b) A truncated structured output ends with `finish_reason: "length"` and invalid (incomplete) JSON; vLLM doesn't repair it |

## Scheduling and the KV cache (`scheduling-kv`)

Chunked prefill, preemption and recompute, priority, budgets, block allocation and prefix caching.

| ID | Behavior | Expected outcome |
|---|---|---|
| Q1 | A 6000-token prompt arrives while 10 requests are decoding | (a) Step 1 schedules the 10 decodes first (1 token each), then a 2038-token chunk of the new prompt: the token budget is 2048 per step. (b) Step 2 schedules the 10 decodes and 2038 more; step 3 the 10 decodes and the remaining 1924. (c) Partial-prefill steps produce no sampled token for the new request (its sampled output is discarded). Its first token comes from step 3. (d) `num_computed_tokens` reads 2038, 4076, then 6000 |
| Q2 | 200 distinct 20-token prompts arrive at once on an idle engine | (a) Step 1 admits requests until the 2048-token budget runs out: 102 full prefills (2040 tokens) and an 8-token chunk of the 103rd. (b) The rest wait. (c) Later steps fill up to `max_num_seqs` (128) running; no step runs more than 128 requests, and requests past 128 wait until one finishes |
| Q3 | `full-small-batch-limits` style budget with chunked prefill **off** (`--no-enable-chunked-prefill`, `max_num_batched_tokens` 2048, `max_model_len` 8192) | (a) Startup config validation fails: with chunked prefill off, `max_num_batched_tokens` must be at least `max_model_len`, so the engine never starts |
| Q4 | KV pressure, fcfs: running requests A, B, C (arrived in that order); C needs a new block for its next token and none are free | (a) The scheduler preempts the last request in the running queue (C itself here, so C is not scheduled this step). (b) Preemption frees C's blocks, sets its status to `PREEMPTED` and `num_computed_tokens` to 0, and puts it at the **front** of the waiting queue. (c) When C resumes, it is recomputed as a prefill over prompt plus already-generated tokens (prefix-cache hits can shorten it). (d) The client sees no duplicated tokens, and C's `num_preemptions` increments |
| Q5 | Priority policy (`policy: priority`): KV full with running requests of priority 5 and 10; the priority-5 request needs a block | (a) The victim is the running request with the largest `(priority, arrival_time)`, the priority-10 one, not the last in the running queue. (b) If it had already been scheduled this step, its tokens are returned to the step budget. (c) The priority-5 request then gets its block |
| Q6 | Priority policy: KV full of priority-10 requests, and a priority-0 request arrives | (a) The new request goes to the waiting queue, ordered ahead of other waiting requests by `(priority, arrival_time)`. (b) Waiting requests don't preempt running ones in V1: the priority-0 request waits for blocks to be freed by finishing (or preempted) requests. (c) It is admitted first once blocks free up |
| Q7 | Prefix cache: the same 40-token prompt twice; then a 48-token prompt identical to a cached one | (a) Only full blocks are cached and hashed (each hash chains the parent block's hash, the tokens, and extra keys such as the LoRA id). (b) For 40 tokens, the second request hits 2 blocks (32 tokens) and computes 8. (c) For a fully cached 48-token prompt, the hit is capped at `prompt_len - 1`, so it hits 2 blocks (32 tokens), not 3, and recomputes the last block to get logits |
| Q8 | Prefix cache isolation and eviction | (a) Two requests with the same prompt but different `cache_salt` values share no blocks. (b) The same prompt under two different LoRA adapters shares no blocks. (c) When free blocks run out, freed-but-cached blocks are evicted LRU from the free queue (the tail block of a finished request is evicted before its prefix blocks), and their hashes are removed from the cache map |

## Execution and parallelism (`execution-parallel`)

Speculative decoding and tensor and pipeline parallel failures.

| ID | Behavior | Expected outcome |
|---|---|---|
| P1 | N-gram speculative decoding (`method: ngram, num_speculative_tokens: 5, prompt_lookup_max: 4`) on a prompt that repeats itself | (a) After each step, the proposer matches the last n-gram of the context against earlier tokens and proposes up to 5 draft tokens, carried in the next `SchedulerOutput`. (b) The scheduler reserves KV slots for the draft tokens. (c) One target forward pass scores all drafts; the rejection sampler accepts a prefix and adds one bonus or recovered token, so a step emits 1 to 6 tokens. (d) With no n-gram match, no drafts are proposed and the step is an ordinary decode |
| P2 | Speculative decoding meets limits: `max_tokens: 10`, and a stop string inside the accepted drafts | (a) Accepted tokens beyond `max_tokens` are dropped: output is exactly 10 tokens, `finish_reason: "length"`. (b) When a stop token id or EOS lies inside the accepted run, tokens after it are discarded and the request finishes `"stop"`. (c) Rejected drafts' KV slots are reused, not leaked |
| P3 | Speculative decoding output quality and metrics (EAGLE draft with `num_speculative_tokens: 3`) | (a) At `temperature: 0`, output is identical to non-speculative greedy output. (b) At `temperature > 0`, rejection sampling preserves the target model's distribution. (c) `vllm:spec_decode_num_draft_tokens` and `vllm:spec_decode_num_accepted_tokens` count drafts and acceptances, giving the acceptance rate |
| P4 | Bad parallel layouts at startup: `--tensor-parallel-size 3` for Llama-3.1-8B (32 attention heads, 8 KV heads); then `--tensor-parallel-size 8` on a host with 4 GPUs | (a) TP 3 fails config validation at startup, because the attention heads aren't divisible by the TP size; no worker is spawned. (b) TP 8 on 4 GPUs fails at startup (the executor can't place 8 ranks, or the Ray placement group can't be satisfied). (c) In both, the API server never starts listening |
| P5 | TP 2 × PP 2 (`full-tp4-llama-70b` hardware), one PP-stage-1 worker dies mid-step | (a) Stage 0 finishes its forward pass and sends intermediate tensors to stage 1; the dead worker never answers. (b) The executor's worker monitor detects the death and marks the engine failed. (c) The engine core raises, every in-flight request fails with `EngineDeadError`, and the API server answers 500 to in-flight requests, then shuts down (unless `VLLM_KEEP_ALIVE_ON_ENGINE_DEATH` is set) |

## Engine lifecycle (`engine-lifecycle`)

Startup and health, abort and cancellation, and LoRA load and unload.

| ID | Behavior | Expected outcome |
|---|---|---|
| L1 | Requests during startup | (a) The API server binds its socket only after the engine core reports ready (model loaded, KV cache sized, warmup done), so `/health` and `/v1/models` are unreachable during load. (b) Once up, `GET /v1/models` lists `llama-8b` with `object: "model"`, `owned_by: "vllm"` and `max_model_len: 131072` |
| L2 | `gpu_memory_utilization 0.92` when another process already holds 20 GB of the 80 GB GPU | (a) The worker checks free memory at startup, against the requested 73.6 GB. (b) Startup fails with an error that names the free and requested memory, before any KV cache is allocated. (c) The engine-core process exits, and the API server reports the startup failure instead of listening |
| L3 | The engine-core process is killed after startup, while idle | (a) The API process's output handler sees the engine-core socket die and marks the client errored. (b) `GET /health` returns 503. (c) A new completion request fails with 500 instead of hanging. (d) The server then terminates itself |
| L4 | Abort a request that is still waiting (never scheduled), including one whose structured-output grammar is still compiling | (a) The abort reaches the engine core, which removes the request from the waiting queue. (b) No blocks are freed, because none were allocated. (c) The request finishes with `finish_reason: "abort"`, and it never appears in any `SchedulerOutput`. (d) The same holds for a request still in `WAITING_FOR_STRUCTURED_OUTPUT_GRAMMAR`: it leaves as aborted, and its finished grammar compilation is discarded |
| L5 | A non-streaming request with `n: 3` whose client disconnects mid-generation | (a) The server notices the disconnect and aborts the parent request. (b) All three child requests are aborted in the engine core, and every child's blocks are freed (the shared prompt blocks return to the cache once their last holder is gone). (c) Nothing is written to the closed connection |
| L6 | Runtime LoRA load (`--enable-lora`, `VLLM_ALLOW_RUNTIME_LORA_UPDATING=True`): `POST /v1/load_lora_adapter {lora_name: "sql", lora_path: "/adapters/sql"}`, then a chat request with `model: "sql"` | (a) The server checks the request, assigns a new `lora_int_id`, and calls `add_lora` on the engine, which loads the weights on the workers. (b) 200 with `Success: LoRA adapter 'sql' added successfully.` (c) `/v1/models` now lists `sql` with `parent: "llama-8b"`. (d) The chat request runs with the adapter's `LoRARequest`, its blocks hashed with the LoRA id |
| L7 | LoRA load and unload errors | (a) Loading `sql` again without `load_inplace: true` gives 400 (`has already been loaded`). (b) Loading with `lora_name: "llama-8b"` gives 400 (conflicts with a served base model). (c) Loading from a path with no adapter gives 404 (`LoRAAdapterNotFoundError`). (d) `POST /v1/unload_lora_adapter {lora_name: "sql"}` gives 200 and removes `sql` from `/v1/models`; a later chat request with `model: "sql"` gets 404. (e) Unloading an unknown name gives 404. (f) Without `VLLM_ALLOW_RUNTIME_LORA_UPDATING`, the load and unload routes aren't registered (404) |
| L8 | More adapters than `max_loras` (2) in one batch: requests for 3 different adapters | (a) At most 2 adapters are active in any step; the scheduler holds back a request whose adapter would be the third and schedules it once a slot frees. (b) Adapters swap in and out of GPU slots from the CPU cache (`max_cpu_loras`), without restarting the engine |

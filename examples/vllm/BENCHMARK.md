# vLLM 0.32 benchmark: does the generated ontology map vLLM's workflows correctly?

The builders never see this file. It lists well-known behaviors of vllm-project/vllm at v0.32.0
(the V1 engine), each written so that it can run as a mosaic scenario against the merged ontology
(`examples/vllm/vllm.json`).

**Verify each case against the code before scoring it.** The expectations below come from docs,
talks and common knowledge, and any of them can be wrong for v0.32.0 with the default engine args.
A judge first confirms or corrects each expectation from the code, citing it. Only then is the
ontology scored against the corrected expectation.

**Default world:** `full-tp1-llama-8b`.
- One 80 GB GPU (rank0) serving Llama-3.1-8B-Instruct as `llama-8b`.
- The default engine args: block size 16, max_num_seqs 128, max_num_batched_tokens 2048, chunked
  prefill on, prefix caching on, policy fcfs, gpu_memory_utilization 0.92.
- Other worlds: `full-tp4-llama-70b`, `full-small-batch-limits`, `full-prefix-caching-off`, plus
  the area fixtures, such as scheduler-kv's nearly-full and prefix-warm worlds.

## Scoring per case

| Score | Meaning |
|---|---|
| **pass** | The verified outcome **and** the code's path are reproduced: the right processes or ranks, messages and decisions |
| **partial** | The outcome is right, but the path is wrong or incomplete; or the behavior is modeled but can't be driven without an edit (say which) |
| **fail** | The model produces a different outcome |
| **missing** | The behavior isn't modeled |
| **sim-gap** | The behavior is modeled as well as mosaic allows. Name the missing feature |

Write each case's scenario at `judge/scenarios/<ID>.yaml`, using fixtures, inputs, `choices`,
`faults` and `steps` only. No mocks, and no model edits.

## Serving (`serving`)

| ID | Behavior | Expected outcome |
|---|---|---|
| V1 | `POST /v1/chat/completions` (non-streaming, max_tokens 16) | The route validates the request and applies the chat template. Tokenization feeds `AsyncLLM.generate`, which sends `EngineCoreRequest` to the engine core. Outputs are detokenized, and a single JSON response comes back with `finish_reason: length` and `usage` counts |
| V2 | The same request with `stream: true` | SSE chunks arrive as tokens are generated, ending with `data: [DONE]` |
| V3 | A prompt longer than `max_model_len` | Rejected with 400 (`invalid_request_error`) before reaching the engine core |
| V4 | An unknown `model` name | 404 (model not found) |
| V5 | The client disconnects mid-stream | The request is aborted. The engine core removes it, and its KV blocks are freed |
| V6 | `temperature: 0` | Greedy sampling (argmax), deterministic across runs |
| V7 | A `stop` string appears | Generation ends with `finish_reason: stop`, and the stop string is excluded from the output by default |
| V8 | `GET /health` | 200 while the engine is alive; an error when the engine core is dead |

## Scheduling and the KV cache (`scheduling-kv`)

| ID | Behavior | Expected outcome |
|---|---|---|
| K1 | Continuous batching | New requests join the running batch at the next scheduler step. Finished requests leave without waiting for the batch |
| K2 | Chunked prefill | A 5000-token prompt is prefilled in chunks bounded by `max_num_batched_tokens` (2048) per step, with decode requests scheduled first in each step |
| K3 | `max_num_seqs` | No more than `max_num_seqs` requests run at once; the rest wait |
| K4 | Prefix caching hit | A second request sharing a 512-token prefix reuses the cached full blocks (32 blocks of 16), so only the remaining tokens are computed (`num_computed_tokens` starts at 512) |
| K5 | KV cache exhaustion | When no free blocks remain for a running request's next token, the lowest-priority (most recently added, under fcfs) running request is preempted. Its blocks are freed and it is recomputed later (recompute, not swap, in V1) |
| K6 | Block allocation | A request of n tokens holds ceil(n / 16) blocks. Blocks are freed (and kept in the prefix cache, evictable) when it finishes |
| K7 | Prefix caching off | Shared prefixes are recomputed, and no blocks are reused |
| K8 | Priority scheduling (`policy: priority`) | Lower priority values are scheduled first. Under memory pressure, the lowest-priority running request is preempted |

## Execution and parallelism (`execution-parallel`)

| ID | Behavior | Expected outcome |
|---|---|---|
| X1 | One engine step on TP 1 | The scheduler output goes to the executor, then `execute_model` on rank0. The model runner prepares inputs and runs the forward pass (attention through the paged KV cache), then samples. The output tokens go back to `update_from_output` |
| X2 | TP 4 | `execute_model` is broadcast to all four ranks. Each forward pass all-reduces after the attention and MLP blocks (row-parallel linear), and only rank0's sampled output is returned |
| X3 | KV cache sizing at startup | The worker profiles peak memory with a dummy run. The KV cache gets `total * gpu_memory_utilization - weights - peak activations`, which sets the number of blocks. Startup fails if there isn't room for one max-length request |
| X4 | CUDA graphs | Decode batches up to a capture size run from captured CUDA graphs. Larger batches or prefill run eagerly |
| X5 | A worker crash | The executor detects the dead worker, and the engine core fails; requests error out with an engine-dead error |
| X6 | Speculative decoding (n-gram or EAGLE) | Draft tokens are proposed, then verified in one target forward pass. Accepted tokens are appended, rejected ones discarded. Outputs match the target model's |

## Engine lifecycle (`engine-lifecycle`)

| ID | Behavior | Expected outcome |
|---|---|---|
| E1 | `vllm serve` startup | Args are parsed into `VllmConfig`. The engine-core process starts, the executor spawns workers, the model loads (download from the HF hub or the local cache), the KV cache is allocated, CUDA graphs are captured, and the API server starts listening |
| E2 | The engine-core busy loop | The loop processes the input queue (add/abort), runs `step()` when requests exist, and sends outputs back over ZMQ. When idle, it blocks on the input queue |
| E3 | Abort a request | Abort reaches the engine core, and the scheduler frees the request's blocks. The request finishes with `finish_reason: abort` |
| E4 | Graceful shutdown (SIGTERM) | The API server stops, the engine core shuts down the executor, and the workers exit |
| E5 | Offline `LLM.generate` with 3 prompts | The prompts are added to an in-process engine, which steps until all finish. Outputs come back in input order |
| E6 | A request with `n: 2` | Two sequences are generated from one prompt, sharing the prompt's KV blocks (a parallel-sampling fan-out in the output processor) |

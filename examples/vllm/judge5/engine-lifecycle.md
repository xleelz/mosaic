# vLLM benchmark 5 judge: engine-lifecycle

**Result: 0 of 8 cases pass; 9 of 34 steps pass.** Case scores: 6 fail, 2 missing.

Run with `check -f examples/vllm/vllm.json -f judge5/scenarios/L5-<n>.yaml --no-mocks --steps --trace`.
A scenario that fails here is the verified expectation failing against the model; each `expect` is that step's observable.
Scenarios that can't be written (an unknown config id is a validation error for the whole document) are noted as comments in the YAML.

## 1. Cases

| ID | Step | Verified expectation | Score | Root cause | Evidence |
|---|---|---|---|---|---|
| **L5-1** | | | **fail** (1/5) | | |
| | a | As written. `get_chat_request_role` returns `messages[-1].role` without a generation prompt (serving.py:433-436) | fail | model | First half reproduced (`chatcmpl-<uuid>`, chunk shape, no `usage`). With `add_generation_prompt: false` the role is `assistant`, not `user`: `chat-completion-stream-generator` hard-codes it |
| | b | As written: 1, 4, 4, 1 (output_processor.py:324-345) | missing | model, world | No `stream-interval` config ("unknown config"), and no `sent_tokens_offset` gate in `output-processor.process-outputs` |
| | c | As written (output_processor.py:253-255) | fail | model | `stream_interval: 8` on the default engine should give 1, 8, 1; the model gives 10 single-token chunks. The field reaches the sampling params and is ignored |
| | d | As written (serving.py:576-588, 814) | pass | | `bench-l5-1-d-usage` |
| | e | As written; param `body.stream_interval` (validation.py:135-146, 167-195) | fail | model | `[DONE]` is right. `stream_interval: 0` is 400 but `BadRequestError`, param `stream_interval`, text `stream_interval must be at least 1, got 0.`: the `SamplingParams` check, which pydantic's `ge=1` (protocol.py:529) never lets a request reach |
| **L5-2** | | | **missing** (1/4) | | |
| | a | As written (metrics.py:200-264, loggers.py:1191-1194) | missing | model | With n-gram config, `/metrics` has no `vllm:spec_decode_*`; `init-prometheus` doesn't create them. The default-world half holds only because they never exist |
| | b | As written | partial | model | Scheduler stats and `spec-decoding-prom.observe` compute 3, 9, 4, `[2,1,1]` when the scenario calls observe itself. Nothing calls it, so the counters never reach the registry. Edit: `stat-logger-manager.record-prometheus` must call it |
| | c | As written (metrics.py:84-138) | partial | model | `spec-decoding-stats.log` returns 2.33, `[.667,.333,.333]`, 44.4, 4, 9. No caller, no periodic logger path, no log line or throughput values |
| | d | As written (scheduler.py:861-872, 2969-2970) | pass | | `bench-l5-2-d-no-match-and-cut`: no drafts gives null stats; budget 2 cuts 3 drafts to `[201]`, counting 1 draft, 1 token, `[1,0,0]` |
| **L5-3** | | | **missing** (0/4) | | |
| | a | Confirmed (loggers.py:1092-1111, 1236) | missing | model | `vllm:lora_requests_info` is nowhere in the model |
| | b | Confirmed: both labels are the dict keys (stats.py:695-700, loggers.py:1220-1233) | missing | model | `LoRARequestStates` isn't modeled; `lora-stats.update` exists with no caller |
| | c | Judge-confirm **confirmed**: `lora_name is None` returns early (stats.py:678-679), and events ride on outputs (stats.py:556-578) | missing | model | As (b) |
| | d | Judge-confirm **confirmed**: the entry is deleted when empty (stats.py:683-684), and `labels(...)` children are never removed | missing | model | As (b) |
| **L5-4** | | | **fail** (1/5) | | |
| | a | As written (filesystem_resolver.py:49-60, plugins/__init__.py:62-90) | pass | | `bench-l5-4-a-*`. Message prefix exact; both plugins load with `VLLM_PLUGINS` unset |
| | b | As written (serving.py:62-66, models/serving.py:315-330) | fail | model | Gets 404. `base-serving.check-model` has no resolver branch, though it cites serving.py:49-91 |
| | c | As written (models/serving.py:318) | fail | model | The 404 and text are right, but `lora_id_counter` doesn't rise: the next load gets id 1, not 3 |
| | d | As written (filesystem_resolver.py:32-37, models/serving.py:345-354) | fail | model | The mismatch 404 is right only because nothing resolves. `r: 32` gets 404, not 400 `LoRA adapter 'x' was found but could not be loaded.` |
| | e | **Completed**: 500 `InternalServerError`, message `'peft_type'` (`str(KeyError)`) via the raw `Exception` handler (register.py:42, error_response.py:86-91) | fail | model | Gets 404. The env-off half is right (`bench-l5-4-e-env-off`) |
| **L5-5** | | | **fail** (3/4) | | |
| | a | As written (offline.py:136-142, 197-240, 338-342) | pass | | Exact texts, `llm.encode` on the path, no `add-request` |
| | b | As written (llm.py:462-468, 517-519) | pass | | Exact texts |
| | c | As written (offline.py:143-187) | pass | | Exact texts. Needs `state: llm.supported_tasks`, as the model's own scenarios do |
| | d | As written (offline.py:366-372, scoring/io_processor.py:320-351) | fail | model | `embed` returns generated text (`kind: final_only`, `t34173`), no 4096-value vector. `score` returns counts, not cosines, and ignores `pooling_params`, so `task="classify"` succeeds instead of raising |
| **L5-6** | | | **missing** (2/4) | | |
| | a | As written (base `_base_request_id`, input_processor.py:360-371) | pass | | `bench-l5-6-a-ids`, including header over body and `<external>-<8 chars>` |
| | b | As written (output_processor.py:552-590) | pass | | Distinct internal ids; the external abort finds both |
| | c | As written. Addition: `abort()` also logs `Aborted request(s) <ids>.` (async_llm.py:921-922) | partial | model | Abort scopes are right: one on disconnect, two by external id, `0_P` and `1_P` by parent. No log line and no `--enable-log-requests` knob. At HTTP the disconnect token derives from `X-Request-Id`, so one client's disconnect cancels both chats; only `generate` with separate tokens can drive it. Edit: a per-connection token |
| | d | As written (input_processor.py:364-371) | missing | model, world | No config id, no warning, and `assign-request-id` always appends the suffix |
| **L5-7** | | | **fail** (1/4) | | |
| | a | As written (parallel_sampling.py:71-81) | fail | model | Three children `0_P` to `2_P` with `n: 1`, but seeds are 7, 7, 7, not 7, 8, 9 |
| | b | Judge-confirm **confirmed**: each seeded request has its own generator (gpu_model_runner.py:1262) | fail | model | Aggregation is right, but all three choices are identical; choice 2 differs from the `seed: 9` run |
| | c | As written (serving.py:549, parallel_sampling.py:115-122) | fail | model | Only `index: 0` is streamed: one role chunk and 3 tokens, not 3 role chunks and 9 tokens. The generator hard-codes the index |
| | d | As written | pass | | Success and e2e +3; `request_params_n` one observation of 3; max generation tokens one observation of 3 |
| **L5-8** | | | **fail** (0/4) | | |
| | a | As written (gpu_worker.py:1451-1453) | fail | model | Right path and 2 ranks, but `{"results":[{"healthy":true},{"healthy":true}]}`, not `[null, null]` |
| | b | As written (api_router.py:25-41) | missing | model | `Missing 'method'` is exact. A list body aborts the run with a CEL error; malformed JSON gets the wrong error. Neither branch exists |
| | c | Judge-confirm **confirmed**: `init_static_loras` loads through `add_lora` (app_state.py:86, models/serving.py:124-135) | fail | model, world | `{"results":[{"lora_ids":[1]}]}`, not `["{1}"]`: no set return and no `str()` rule. `--lora-modules` has no knob, so the scenario loads through `load-lora-adapter` |
| | d | As written (cache/api_router.py:47-54, routers.py:40-43) | partial | model | 200 and the no-dev-mode 404s are right; the log `Resetting multi-modal cache...` is absent |

## 2. Wrong claims in the model

1. `openai-serving-chat.chat-completion-stream-generator`, "First chunk per choice carries the role" (citing serving.py:546-588): the model emits one chunk, `index: 0`, role `assistant`. The code loops over `num_choices` and uses `get_chat_request_role`.
2. `spec-decoding-prom.observe`, "increments vllm:spec_decode_num_drafts...", and scenario `wr-spec-decoding-stats-and-metrics`, "feed the vllm:spec_decode_* counters": it has no caller and writes only its own state; `record-prometheus` omits loggers.py:1191-1194.
3. `async-llm.add-request`, which cites parallel_sampling behavior: children keep the parent's seed (code: `seed + index`, parallel_sampling.py:78-81).
4. `base-serving.check-model` cites serving.py:49-91 but leaves out lines 60-71, the resolver branch. Its summary states only base model or loaded adapter.
5. `gpu-worker-impl.check-health` cites gpu_worker.py:1451-1453, which returns `None`; the model returns `{healthy: true}`.
6. `gpu-model-runner.list-loras` and `dev-rpc-router.post-collective-rpc`: `{lora_ids: [...]}` instead of a set, with the `str()` rule (api_router.py:51-58) and the non-object check (api_router.py:32-36) missing, despite citing 23-59.
7. `llm.embed` and `llm.score` (citing offline.py:285-394): `run-tiling-engine` returns generated text for pooling, and `score` ignores `pooling_params` and computes no score.
8. `sampling-params.post-init` is the modeled source of the HTTP error for `stream_interval: 0`; in the code pydantic rejects it first.

Entry points covered only by a nearby citation or an uncalled entity: `resolve_lora` (cited range only), `SpecDecodingLogging.log`, `SpecDecodingProm.observe`, `LoRAStats.update`, `hf-hub-resolver.resolve-lora`.

Citations: `--cite-sample 12 --seed 55`, all 12 cited the right code, plus 15 read beside the code for the entities above. Those citations resolve, so the faults above are omissions and wrong values in behaviors, not bad line numbers.

## 3. Builder findings

No "docs versus code" finding for this group appears in the merged model or the fragments, and `notes/**` is off limits, so none could be confirmed or refuted.

## 4. Simulator gaps

None. Every non-pass above is model or world. `--stream-interval`, `--enable-log-requests`, `--lora-modules` and `VLLM_DISABLE_REQUEST_ID_RANDOMIZATION` are missing knobs, not simulator limits.

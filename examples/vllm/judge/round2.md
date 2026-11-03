# Judge report: vLLM round 2 (after the fix round)

Model: the merged `skeleton.yaml` + `fixtures.yaml` + `worlds.yaml` + `fragments/*.yaml`. Code: vLLM v0.32.0.
I made no model edits. In 5 scenario files I adapted only the call or the result path to the new
streaming contract. `async-llm.generate` now `yield`s each RequestOutput, and a non-streaming caller gets
`{items, value}`, with the final output in `items[size(items)-1]`.

## Harness adaptations

| Case | Change | Why it's drift and not a new assertion |
|---|---|---|
| E2, E3, E4, E6, V7 | `steps.gen.result.value.X` became `steps.gen.result.value.items[size(...)-1].X` | This is the streaming contract: the final RequestOutput is the last item. |
| E6 | The token count is read from `completions.map(c, c.token_ids).flatten()` | A RequestOutput keeps its tokens per completion (`outputs[i].token_ids`). The asserted value, 8, is unchanged. |
| E2 | `iterations == 12 && input_queue == []` became `loop_active && !exited && channel_len('engine-core-input:engine-core-proc') == 0` | The busy loop now blocks on a `receive` (FIXES.md, engine-core) instead of spending a 1 ms poll budget, so it parks while idle. `input_queue` moved from state to a channel. The claim is unchanged: the loop is idle again, its input queue is empty and the scheduler is empty. |

## Verdicts for the 7 cases that failed

| Case | Verdict | Root cause and citation |
|---|---|---|
| E2 | **pass** | Harness drift only (the result path and the idle-loop state). After adaptation every path assertion holds. |
| E3 | **model-bug** (engine-core) | `output-processor.abort-requests` hard-codes the final abort output as `kind: delta` with `token_ids: []` (`fragments/engine-core.yaml:1615-1632`). In the code, `abort_requests` calls `make_request_output(new_token_ids=[], finish_reason=ABORT)` (`v1/engine/output_processor.py:589-603`). For a non-DELTA request, `_new_completion_output` replaces token_ids with `detokenizer.output_token_ids` (`output_processor.py:437-442`), and the default output_kind is CUMULATIVE (`sampling_params.py:383`). The final abort output should therefore carry every token generated so far. Earlier stream items do carry tokens. Only the last item is empty. |
| E4 | **pass** | Harness drift only. Both `bench-e4` and `bench-e4-tp4` now pass, so the TP 4 per-rank worker shutdown is fixed. |
| E5 | **model-bug** (serving-api) | `bench-e5` passes, but `bench-e5-per-prompt-params` fails. `llm.add-completion-requests` still sends `sampling_params: '= type(input.params) == list ? {} : input.params'` (`fragments/serving-api.yaml:7308`). The params list is dropped, so `max_tokens` is missing at `llm-engine.add-request`. The code pairs `params[i]` with prompt `i` (`entrypoints/common/offline.py:258-263, 550-560`). This is round-1 issue 3, still unfixed. |
| E6 | **wrong-expectation** | The assertion "the final output holds both completions, 8 tokens" is not guaranteed by the code. With the default CUMULATIVE kind, `ParentRequest.get_outputs` streams only the current child's completion ("If streaming, just return the current output", `v1/engine/parallel_sampling.py:117-121`). It aggregates all n only for FINAL_ONLY (`:122-125`). The final RequestOutput holds both completions only if both children finish in the same engine step and merge in the shared collector (`output_processor.py:69-83`, `outputs.py:203-247`), and that depends on when the two ADDs arrive. In the model, child 1 is scheduled one step later, so the last item correctly holds only child 1's 4 tokens. The other assertions pass: client fan-out, prefix-cache hits == 32, `finished`, both children freed. *Side finding (model, engine-core):* in the same step the generate poll (`fragments/engine-core.yaml:988`) runs between two `request-output-collector.put` calls. The code can't do this, because `process_outputs` is synchronous with no `await` between puts (`v1/engine/async_llm.py:860-885`). So the model streams 8 items where the code streams merged ones. |
| V7 | **pass** | Harness drift only. `bench-v7` and `bench-v7-engine` pass. |
| X5 | **model-bug** (engine-core) | `bench-x5-worker-crash-mid-generation` passes. In `bench-x5-nonoutput-rank-raises`, the main path now matches the code. Rank 2's exception is logged and not replied (`return replied:false`). The executor's `collective-rpc` fails with `timeout-error` after 300 s. The engine dies with `engine-dead-error`. What's still wrong is that `multiproc-executor.shutdown` (`fragments/engine-core.yaml:4308-4333`) only calls `gpu-worker-impl.shutdown` on each rank. It never terminates the worker processes. Its summary says "wait for (and kill)", but the behavior doesn't do it. In the code, `_ensure_worker_termination` waits `VLLM_WORKER_SHUTDOWN_TIMEOUT_SECONDS=5`, then sends SIGTERM, then SIGKILL (`v1/executor/multiproc_executor.py:459-507, 526`). Rank 0, stuck in the TP collective, is therefore killed. In the model, rank 0's `worker-proc.execute-worker-rpc` stays alive and ends at about 600 s with a `runtime-error` FAILURE (`late`, after a `dist-backend-error` rendezvous timeout). That is the error the probe's last assertion catches. The overall `status error` is expected, because the busy loop dies with a `timeout-error`. The `kill` primitive could model the SIGKILL. |

## Scorecard (28 cases)

| Case | Round 2 | Note |
|---|---|---|
| E1 | pass | prior verdict (engine-lifecycle.md) |
| E2 | pass | harness drift adapted |
| E3 | model-bug | the abort output drops its cumulative tokens (engine-core) |
| E4 | pass | harness drift adapted; TP 4 shutdown now fixed |
| E5 | model-bug | per-prompt SamplingParams are dropped (serving-api) |
| E6 | wrong-expectation | a CUMULATIVE parent stream doesn't aggregate the completions |
| K1–K8 | pass ×8 | prior verdicts (scheduling-kv.md / .json) |
| V1–V6, V8 | pass ×7 | prior verdicts (serving.md / .json) |
| V7 | pass | harness drift adapted |
| X1–X4, X6 | pass ×5 | prior verdicts (execution-parallel.md / .json) |
| X5 | model-bug | executor shutdown never kills stuck workers (engine-core) |

**Total: 24 pass, 3 model-bug (E3, E5, X5), 1 wrong-expectation (E6).** If E6's corrected expectation
is that the final item holds the last-finishing child's completion, the model is 25/28 correct against the code.

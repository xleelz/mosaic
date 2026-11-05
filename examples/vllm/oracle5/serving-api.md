# Oracle 5: serving-api

Scenarios run with `--no-mocks --lint hollow`: 0 validation errors, hollow lint clean, 1 of 14 scenarios passes. No expectation was changed to match the model. The 13 failures are the verdicts below.

| Test | Behavior | Scenario | Verdict | Entity at fault | Evidence |
|---|---|---|---|---|---|
| `tests/entrypoints/pooling/scoring/test_io_processor_unit.py:66` `test_llm_reranker_tokenization_is_independent_of_nonbinding_doc_limit` | An LLM reranker (`use_sep_token` False) tokenizes `prompt_1 + prompt_2` as one sequence, and a `max_tokens_per_doc` that doesn't bind changes nothing. Code: `CrossEncoderIOProcessor.get_score_prompt`, `vllm/entrypoints/pooling/scoring/io_processor.py:634` | `oracle-serving-api-llm-reranker-pair-no-separator` (nested: `oracle-serving-api-llm-reranker-nonbinding-doc-limit`) | `model-bug` | `serving-scores.serve-score` | See sub-results |
| `tests/entrypoints/openai/responses/test_harmony_utils.py:26` `TestResponsePreviousInputToHarmony.test_message_with_empty_content` | A previous user message with empty content becomes one Harmony message with one empty text part. Code: `response_previous_input_to_harmony`, `vllm/entrypoints/openai/responses/harmony.py:221`; `_parse_chat_format_message`, `harmony.py:136-143` | `oracle-serving-api-harmony-previous-input-empty-content` | `model-bug` (missing) | `openai-serving-responses.create-responses`, `online-renderer.render-responses` | A probe with content `"x"` showed the message never leaves the serving layer: `previous_messages` is null at the renderer, while the new input `"hi"` does reach it. `previous_input_messages` appears in the model only in the exclusivity check (`responses/serving.py:275`). The code consumes it at `vllm/renderers/online_renderer.py:429`. |
| `tests/parser/cohere/test_tool_calls.py:180` `TestExtractToolCalls.test_streaming` (8 parametrized cases) | Streaming the Cohere output through `parse_delta` accumulates the expected tool call ids, names and arguments. Code: `CohereCommandParser.parse_delta`, `vllm/parser/cohere_command.py:608`, `_tool_call_deltas` `:666` | `oracle-serving-api-cohere-streaming-{3,4}-{single-tool-call,citations-no-tool-calls,multiple-tool-calls,reasoning-only}`, `oracle-serving-api-cohere-stream-flow-{3,4}` | `model-bug` (missing) | `cohere-command-parser`, `openai-serving-chat.chat-completion-stream-generator` | See sub-results |
| `tests/entrypoints/pooling/test_utils.py:19` `test_encode_pooling_output_float_or_ndarray_returns_numpy_array` | The helper returns the pooled output's data as an ndarray for the JSON renderer. Code: `encode_pooling_output_float_or_ndarray`, `vllm/entrypoints/pooling/utils.py:75`, called at `vllm/entrypoints/pooling/embed/serving.py:124` | `oracle-serving-api-embeddings-float-observable-json-array` | `model-bug` | `async-llm.encode`, `pooling-base-serving.serve` | See sub-results |

## Sub-results

**Reranker**

| Scenario | Verdict | Evidence |
|---|---|---|
| `oracle-serving-api-llm-reranker-nonbinding-doc-limit` | `pass` | Both calls give the same tokenizer text, ids and usage. `truncate-text-to-tokens` runs once and returns `bc` unchanged, as `io_processor.py:658-659` does. |
| `oracle-serving-api-llm-reranker-pair-no-separator` | `model-bug` | The tokenizer receives `a bc`; the code passes `abc` (`io_processor.py:696-699`). The expected ids `[1,3,5,6,2]` are `[CLS] a ##b ##c [SEP]`, which only `abc` can yield, while `a bc` would be `[1,3,4,2]`. The ids themselves are tokenizer internals, so the scenario asserts the text instead. The model has no way to select this branch: it holds `use_sep_token` only in a step title. `adapters.py:443` defaults it to False for LLMs converted to rerankers. |

**Cohere**

| Scenario | Verdict | Evidence |
|---|---|---|
| `oracle-serving-api-cohere-streaming-{3,4}-*` (8) | `model-bug` | `parser-manager.get-parser` resolves `CohereCommandParser`, but `delegating-parser.parse-delta` then aborts: `input.parser.config: no such key: config`. The model has no Cohere engine config and no `cohere-command-parser.parse-delta`. Each case carries the test's expected calls. They split the output into two deltas instead of token-sized ones, since the test's assertion is over the accumulated stream. |
| `oracle-serving-api-cohere-stream-flow-{3,4}` | `model-bug` | The stream succeeds but no parser runs. `vars.engine_parser` is true only for `Inkling*` classes, whereas the code calls `parser.parse_delta` for any resolved parser (`vllm/entrypoints/openai/chat_completion/serving.py:667`). The trace also shows `llama3-json-tool-parser.adjust-request` on this path, not the Cohere one. |

The model's generated text can't be seeded, so the 8 cases go to the parser interface directly and the flow scenarios only check that a parser runs.

**Embedding helper**

| Part | Verdict | Evidence |
|---|---|---|
| `isinstance(encoded, np.ndarray)`, `assert_allclose` | `untranslatable` | A Python return type and tensor values, both below the model. |
| The output's elements reach the response (`oracle-serving-api-embeddings-float-observable-json-array`) | `model-bug` | `async-llm.encode` returns only `{finished, request_id}`, so `serve` falls back to `[]`. A probe confirmed `size(embedding) == 0`. In the code, the vector comes from `final_res.outputs.data` (`embed/serving.py:124`). |

The row's `model-bug` is a judgment call. The test only asserts on the helper, so the wire-level check is my translation of "the output's elements come through". Without that part, this row would be `untranslatable`.

## Fix requests

1. **serving-api, `serving-scores.serve-score`:** add the `use_sep_token` False branch of `get_score_prompt`, where the pair is `prompt_1 + prompt_2` with no separator, and a way to select it for LLM rerankers (`io_processor.py:672-699`, `adapters.py:443`).
2. **serving-api, `openai-serving-responses.create-responses`, `online-renderer.render-responses`:** carry `previous_input_messages` into rendering, including the Harmony path for `gpt_oss` and the conversion rules of `_parse_chat_format_message`. The Harmony path also drops system and developer messages (`harmony.py:237-261`).
3. **serving-api, `cohere-command-parser`, `openai-serving-chat.chat-completion-stream-generator`:** add `parse` and `parse_delta` for the Cohere parser, and call them from the stream generator for any resolved parser. Also check that `adjust_request` reaches `cohere-command-parser.adjust-request` on this path. The trace shows the llama3 one there, which I did not investigate further.
4. **engine-core, `async-llm.encode`:** return the pooled `outputs.data` (the behavior is in `fragments/engine-core.yaml`). `pooling-base-serving.serve` in serving-api already reads `outputs.data`, so `/v1/embeddings` stops answering an empty vector once it is returned.

## Count check

Entries in the sample: 4. Rows written: 4. Verdicts: `pass` 0, `model-bug` 4, `test-mismatch` 0, `sim-gap` 0, `untranslatable` 0 at row level (1 sub-part untranslatable).

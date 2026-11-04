# Round-5 in-build oracle: serving-api

The 6 tests in `serving-api.json`, translated in `serving-api.yaml`. Run against the merged model:

```sh
go run ./internal/devtools/check -f <merged.json> -f examples/vllm/build-oracle/round5/serving-api.yaml --no-mocks --scenario '^oracle-r5-serving-api'
```

**6 of 6 pass.**

| Test | Scenario | Verdict | Model work |
|---|---|---|---|
| tests/reasoning/test_holo2_reasoning_parser.py:170 `test_reasoning` | `oracle-r5-serving-api-holo2-reasoning` | pass (the 5 non-streaming parametrizations) | `deepseek-v3-reasoning-parser.extract-reasoning`: thinking delegates to the R1 split, otherwise identity; `default_thinking` is `DeepSeekV3ReasoningWithThinkingParser` (`--reasoning-parser holo2`, deepseek_v3_reasoning_parser.py:85-96). The 5 streaming parametrizations give the same (reasoning, content) through `run_reasoning_extraction`. The model has no per-token stream for this parser, so they aren't separate cases. |
| tests/parser/cohere/test_structural_tags.py:237 `test_response_format_cleared` | `oracle-r5-serving-api-cohere-response-format-cleared` | pass (both parametrizations; the pydantic and dict json_schema forms are the same wire body) | `cohere-command-parser.adjust-request` (cohere_command.py:504-563): the response_format schema, else the structured_outputs schema, is folded into one triggered_tags structural tag for the architecture's tag style, and response_format is cleared. The tool grammar text (`collect_tool_schema`) is a labeled placeholder. |
| tests/entrypoints/launchers/test_run_batch.py:978 `test_transcription_wrapper_rejects_oversized_data_url_before_decode` | `oracle-r5-serving-api-transcription-oversized-data-url` | pass (scaled) | `run-batch.download-bytes-from-url` (run_batch.py:461-531) estimates the decoded size from the encoded length before decoding. `run-batch.transcription-wrapper` (639-709) turns any exception into `Failed to process transcription: ...` (400), and the handler is never called. The test's 1 MiB limit and 1.4 M-character payload are scaled down by 2^16 (`VLLM_MAX_AUDIO_CLIP_FILESIZE_MB` = 2^-16, so a 16-byte limit, and 24 base64 characters), which keeps the over-the-limit relation. |
| tests/entrypoints/scale_out/derender/test_derender_stream.py:1263 `test_tool_call_id_pinned_across_chunks` | `oracle-r5-serving-api-derender-tool-call-id-pinned` | pass | `online-derenderer.apply-chat-stream-delta` (online_derenderer.py:588-692): an id-bearing tool-call delta reuses the id already recorded for its index. The test's `_FakeParser` is test-only code, so the scenario passes the parser's two deltas (two fresh ids) and the state the first chunk returned. |
| tests/parser/engine/test_qwen3.py:298 `test_streaming_multi_param` | `oracle-r5-serving-api-qwen3-streaming-multi-param` | pass | `qwen3-parser.stream-tool-call`: the name is sent once `<function=NAME>` is complete. The arguments are `_qwen3_arg_converter`'s JSON of the complete parameters (qwen3.py:51-86), streamed as the growing text, with the closing brace held back until `</function>`. |
| tests/parser/test_harmony.py:581 `test_tool_call_split_across_deltas` | `oracle-r5-serving-api-harmony-tool-call-split` | pass (commentary and analysis) | `harmony-parser.parse-delta` (harmony.py:237-372): stream state is kept per parser instance. The text of a message to `functions.*` is a tool call: a new recipient opens index n with the name, and later text extends it with no name. Analysis text is reasoning. The harmony token stream is modeled on the decoded text, split at its special markers. |

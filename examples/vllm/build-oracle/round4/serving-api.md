# Round-4 in-build oracle: serving-api

| Test | Scenario | Verdict | Cause |
|---|---|---|---|
| `tests/entrypoints/pooling/embed/test_cohere_openai_parity.py:75` test_batch_parity | `oracle-r4-serving-api-batch-parity` | pass | `/v2/embed` now reads Cohere's `texts` (CohereEmbedRequest, `pooling/embed/protocol.py:229-250`) and embeds them through the same `pooling-base-serving.serve` as `/v1/embeddings`; the 3 embeddings come back in input order and equal. Cosine values are numerics; equality of the stand-in vectors stands in for cosine > 0.9999. |
| `tests/entrypoints/cohere/test_api_router.py:524` test_error_response_translated_to_cohere_envelope | `oracle-r4-serving-api-cohere-error-envelope` | pass | New `cohere-serving-chat-v2.error-response` (`cohere/api_router.py:102-117`): the render route's errors keep their status (404) and carry the body `{message}`. The test stubs the render handler; the scenario reaches the 404 through a real unknown-model render. |
| `tests/reasoning/test_kimi_k3_reasoning_parser.py:51` test_parser_manager_selects_kimi_k3_parser_for_reasoning_only | `oracle-r4-serving-api-kimi-k3-reasoning-only` | pass | New `parser-manager.get-parser` (`parser/parser_manager.py:99-268`) composes kimi_k3 onto KimiK3Parser with the registry's KimiK3ReasoningParser and no tool parser. |
| `tests/renderers/test_hf.py:849` test_developer_at_non_first_position_consolidated | `oracle-r4-serving-api-developer-consolidated` | pass | New `hf-renderer.safe-apply-chat-template` (`renderers/hf.py:511-567, 770-835`): developer -> system, then all system messages merged into one leading message, so the strict template doesn't raise. `render-messages` uses it too. |
| `tests/entrypoints/launchers/test_cli_args.py:301` test_chat_template_validation_for_happy_paths | `oracle-r4-serving-api-chat-template-happy-path` | pass | New `cli-args.validate-parsed-serve-args` with `validate_chat_template` (`cli_args.py:502-546`, `chat_utils.py:1457-1490`); file existence is `local-disk.stat`. |
| `tests/entrypoints/cohere/test_serving_conversion.py:2408` test_tool_content_json_text_parsed_as_tool_output | `oracle-r4-serving-api-tool-json-text-output` | pass | New `cohere-serving-chat-v2.build-position-to-source` (`cohere/serving.py:773-900, 1254-1296`). ASSUMPTION: a JSON-object text is recognized by balanced braces (CEL has no try-parse). |

Passing: 6 of 6.

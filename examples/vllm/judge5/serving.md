# vLLM judge5, group serving

Steps passed: **5 / 39**. Cases: 0 pass, 8 fail (worst step rule).

Scenarios: `judge5/scenarios/S5-1.yaml` to `S5-8.yaml`. They assert the verified code behavior, so a failing expectation is the evidence for a non-pass. Runs used `--no-mocks`; no model edits.

## 1. Cases

| Case | Score | Steps passed | Root cause | Expectation corrected |
|---|---|---|---|---|
| S5-1 | fail | 0/5 | model; world | no |
| S5-2 | fail | 2/5 | model | no |
| S5-3 | fail | 3/5 | model | no |
| S5-4 | fail | 0/5 | model; simulator | no |
| S5-5 | fail | 0/5 | model; simulator | no |
| S5-6 | fail | 0/5 | model; benchmark | yes |
| S5-7 | fail | 0/4 | model; contract | no |
| S5-8 | fail | 0/5 | model | no |

### Steps

| Step | Score | Evidence |
|---|---|---|
| S5-1(a) | partial | Runner, convert log, LAST/ALL, tasks [embed, token_embed], pooling task embed, chunked prefill and prefix caching all match. head_dtype float32 appears nowhere in the model (config/model.py:2090-2116). Tasks must be seeded in app-state: `config: {runner: pooling}` does not derive them for routes. |
| S5-1(b) | fail | /classify, /v1/embeddings, /v2/embed, /pooling, /score correct; /v1/chat/completions and /v1/completions answer 200 with generated text instead of 404 (routers.py:49-54; openai-serving-chat.post-v1-chat-completions has no task gate). |
| S5-1(c) | fail | ids embd-<id>-0/-1 and order correct; `embedding: []` instead of 4096 floats with norm 1; usage lacks completion_tokens and prompt_tokens_details. async-llm.encode returns {finished:false}; calls['pooling-runner.pool'] == 0. |
| S5-1(d) | missing | encoding_format/embed_dtype/endianness are absent from the model; base64 request returns the empty list (embed/serving.py:150-160). |
| S5-1(e) | fail | dimensions=256: exact 400, param null. normalize=true: 200, the removed-parameter refusal is unmodeled (base/protocol.py:23-32). Expectation confirmed: VLLMError subclasses Exception, not ValueError, so pydantic does not wrap it. |
| S5-2(a) | partial | bi-encoder, encodes score-<id>-0/-1/-2, shape correct. s0 > s1 not reproduced: both 0.999..., from the literal fallback [1.0] in serving-scores.serve-score. Prefix score- correct. |
| S5-2(b) | pass | All three texts exact, 400, BadRequestError, param null, no encode. |
| S5-2(c) | fail | Sort and top_n correct. id is rerank-<id> but code uses score-<id> (scoring/serving.py:37: one ServingScores, request_id_prefix=score; api_router.py:30-34). document lacks multi_modal: null. |
| S5-2(d) | partial | Same shape; the /v1/score warning (every call) and /v1/rerank warning_once are not modeled (api_router.py:60-63,92-96). |
| S5-2(e) | pass | prompt_tokens == total_tokens == sum over the three engine inputs. |
| S5-3(a) | pass | 3 entries, 2 top_logprobs, sampled token first, bytes and logprob present. |
| S5-3(b) | pass | Sampled token first, then best-ranked; confirmed in code. Synthetic ranks stop at 4 (sampler.sample), so rank 5 itself is not drivable; a rank>2 position shows the same mechanism. |
| S5-3(c) | pass | Four keys; dict sizes 2 or 3, including a 3-entry position. |
| S5-3(d) | fail | logprob_token_ids ignored on chat: `top_logprobs: 5` kept and no 9642/2822 entries; 129 ids and [200000] answer 200; no check that logprobs is true (protocol.py:834-850,754-766; sampling_params.py:919-965). Model has the kernel and sampler pieces only. |
| S5-3(e) | fail | Request field return_tokens_as_token_ids ignored: tokens remain ' t<id>' (serving.py:1284-1302). |
| S5-4(a) | fail | Rewrite happens, but schema differs: no items.type object, anyOf entries carry type object, name has no type string; parallel_tool_calls false adds no maxItems (tool_parsers/utils.py:378-395,425-446). |
| S5-4(b) | fail | A required response is not parsed as list[FunctionDefinition]: the JSON array goes to llama3 extract, which returns it as content (abstract_parser.py:427-441). No chatcmpl-tool- id; arguments not json.dumps'd. Fake output never parses. |
| S5-4(c) | fail | Named schema with parameters correct; empty parameters give {} not {type: object, properties: {}}; the output does not become arguments, content is the text (abstract_parser.py:415-426). |
| S5-4(d) | partial | No constraint; JSON and plain-text parses correct, plain text end to end correct. Tool-call finish_reason not drivable end to end (synthetic text). Arguments stay a map, not a string; surrounding text defeats the parser, which code scans past (llama_tool_parser.py:76-126). |
| S5-4(e) | fail | Regex with named tool: exact 400. Truncated required: finish length, tool_calls [] correct, content is the text instead of ''. |
| S5-5(a) | fail | auto gives xgrammar in grammar-init; _backend_was_auto absent. Output ' t1 t34173...' does not match regex. Under xgrammar, regex '(' answers 200: the compile stub never rejects (backend_xgrammar.py:407-434). |
| S5-5(b) | fail | uniqueItems stays xgrammar instead of guidance; patternProperties stays xgrammar instead of outlines; xgrammar variant answers 200. has_xgrammar_unsupported_json_features, has_guidance_unsupported_json_features are absent. input-processor.process-inputs has no outlines fallback. |
| S5-5(c) | fail | regex+choice exact 400. regex+grammar and {} answer 200 (sampling_params.py:99-138). Expectation confirmed: dataclass raises VLLMValidationError, not wrapped by pydantic. |
| S5-5(d) | fail | json_object accepted; with regex 200 instead of the multiple-constraints 400. json_schema without the field aborts the run in to-sampling-params (no such key) instead of the 400 (protocol.py:788-822). |
| S5-5(e) | fail | choice becomes request_type grammar, but output is not yes/no; {choice: []} and {grammar: ''} answer 200 (sampling_params.py:1263-1279). |
| S5-6(a) | partial | Driven through load-lora-adapter: ids 1 and 2, /v1/models cards exact. LoRAParserAction, init_static_loras and the Loaded log are absent. Edit needed: app-state calling load per --lora-modules. |
| S5-6(b) | partial | Corrected message reproduced with 500. The startup failure (init_static_loras re-raises ValueError, models/serving.py:135-141) is not modeled. |
| S5-6(c) | fail | Rank 32 refusal (corrected) before weights, rank-32 allowed correct. --max-lora-rank 24 accepted by config-create-engine-config instead of an argparse refusal (config/lora.py:26). |
| S5-6(d) | fail | Says only 'Adapter bias is not supported.'; _validate_features unmodeled (peft_helper.py:53-99). |
| S5-6(e) | fail | max-loras 2, max-cpu-loras 1 accepted; validator unmodeled (config/lora.py:117-127). Default-follows-max_loras exists elsewhere. |
| S5-7(a) | partial | Hash img-1, one hit, HF once, R2 cached 800 tokens. But a control with a different UUID also caches 800, so the mm hash does not reach block keys on this path (kv_cache_utils.py:628-660); create-chat-completion's engine_req carries no mm hashes. 'Describes X' is not expressible. |
| S5-7(b) | fail | image_url null aborts in hf-renderer.render-messages (no such key: url) instead of 200 (chat_utils.py:1728-1745). |
| S5-7(c) | fail | Same abort; the 'Cache miss ...' text is unmodeled in the API path (processor.py:1365-1375). |
| S5-7(d) | missing | No mm_cache_stats reach record-prometheus; no vllm:mm_cache_* increments in the serve path (base.py:238-253; async_llm.py:903). Expected +3/+2 confirmed: is_cached uses `in`, get counts once per item (utils/cache.py:125-138; cache/lru.py:47-60). |
| S5-8(a) | missing | No prompt: run aborts. With a prompt and flag off: 200. Confirmed: safe_load_prompt_embeds fires first (renderers/base.py:531-535), not _process_embeds. |
| S5-8(b) | missing | prompt_embeds never loaded; usage comes from prompt text. |
| S5-8(c) | missing | embed_utils checks unmodeled for completions (embed_utils.py:21-110). |
| S5-8(d) | fail | prompt+embeds gives 1 choice, not 2; echo and prompt_logprobs answer 200; suffix answers the FIM message, contradicting 'suffix is not supported with prompt_embeds' (online_renderer.py:600-664). |
| S5-8(e) | missing | kv-cache-utils.request-block-hasher has no prompt_embeds key (kv_cache_utils.py:598-622). Run aborts without a prompt. |

### Corrected expectations

- **S5-6(b, c, d)**: the failure text gains a prefix. At TP1 the uni-process executor raises directly and `EngineCore` wraps it: `Call to add_lora method failed: LoRA is not enabled. Use --enable-lora to enable LoRA.` (`vllm/v1/engine/core.py:1750-1751`; `vllm/v1/executor/uniproc_executor.py` collective_rpc). The message does not survive unchanged. Same prefix for the rank and DoRA texts. Under the mp executor it would be wrapped further (`multiproc_executor.py:444-447`).
- **S5-6(e)**: `LoRAConfig` is a pydantic `@config` class, so the `ValueError` surfaces inside a pydantic `ValidationError` whose text contains the stated message (`vllm/config/lora.py:29,117-127`). The model raises nothing, so the step fails either way.

All "judge: confirm" items not listed above were confirmed from the code: S5-1(e), S5-3(b), S5-5(c), S5-7(d), S5-8(a).

## 2. Wrong claims in the model

1. `pooling-base-serving.serve` and `serving-scores.serve-score` claim to collect outputs, but `async-llm.encode` returns `{finished: false}`, never runs the pooling runner, and data falls back to `[]` or the literal `[1.0]`. Every cosine score is 0.9999. Code: `vllm/entrypoints/pooling/base/serving.py:150-185`, `scoring/io_processor.py:325-357`.
2. `peft-helper.validate-legal` says "including rank_pattern" and reads only `r` and `bias`; `_validate_features` is absent. Code: `vllm/lora/peft_helper.py:53-99,188-202`.
3. `online-renderer.render-completion` says "suffix/echo/prompt-embeds checks", and has no prompt-embeds check. Code: `vllm/renderers/online_renderer.py:600-664`.
4. `llama3-json-tool-parser.adjust-request` builds a different schema from the code, and ignores `parallel_tool_calls`. Code: `vllm/tool_parsers/utils.py:378-395,425-446`.
5. `openai-serving-chat.chat-completion-full-generator` runs the llama3 parser for required and named choices; the code has separate branches. Code: `vllm/parser/abstract_parser.py:415-441`.
6. `serving-scores.post-rerank` passes prefix `rerank`; the code has one `request_id_prefix = "score"`. Code: `scoring/serving.py:37`.
7. `llama3-json-tool-parser.extract-tool-calls` requires every `;` segment to be a JSON object; the code scans with a regex and ignores surrounding text. Code: `vllm/tool_parsers/llama_tool_parser.py:76-126`.
8. `xgrammar-backend.validate-xgrammar-grammar` never rejects a bad regex or unsupported schema feature, and `process-inputs` falls back only to guidance. Code: `backend_xgrammar.py:290-316,407-471`, `sampling_params.py:1386-1435`.

Spot-check: `--cite-sample 12 --seed 515` over the model: all 12 citations match their claims (all 11,193 resolve). The wrong claims above came from reading group behaviors next to code, beyond the sample. Covered entry points: embeddings, score, rerank, pooling, chat and completions routes are modeled by dedicated interfaces. Their request parsing is what is thin.

## 3. Builder findings

Not checked: builder "docs versus code" findings live under `notes/**`, which the brief forbids, and `fragments/serving-api.yaml` has none inline. Neither confirmed nor refuted.

## 4. Simulator gaps

- **Constrained text** (S5-4 b and d, S5-5 a and e): output is synthetic `' t<id>'`, so nothing can emit text matching a regex, a JSON schema or a choice. A generator from a constraint would be needed. It did not set a score: each of these steps also has a model fault.
- **Vector semantics** (S5-2 a, S5-7 a): no way to express s0 > s1 or "the answer describes X" except by assigning values.

# Judge 4: serving group (S4-1 to S4-8)

Model: `examples/vllm/vllm.json` (618 components, 1,573 scenarios, all passing, every citation resolving).
Code: vLLM v0.32.0 at `/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`. Scenarios: `judge4/scenarios/S4-*.yaml`, one
scenario per step group so that an abort can't hide the other steps:

```sh
/tmp/mcheck -f examples/vllm/vllm.json -f examples/vllm/judge4/scenarios/S4-N.yaml --no-mocks --scenario '^bench-s4' --steps
```

I confirmed the FastAPI and pydantic behaviors the expectations depend on with a local FastAPI 0.136 / pydantic 2.14
reproduction: the 404 body for an unknown route, the error dicts, before validators running in reverse definition
order, and a non-`ValueError` raised in a validator escaping pydantic.

**Totals: 0 / 8 cases pass (1 partial, 5 fail, 2 missing). Steps: 9 / 37 pass.**

## 1. Cases

| Case | Step | Verified expectation (corrections in bold) | Score | Root cause | Evidence |
|---|---|---|---|---|---|
| **S4-1** | a | Confirmed. 400, type `Bad Request`, param `body.messages`, `1 validation error:\n  {'type': 'missing', 'loc': 'body.messages', 'msg': 'Field required', 'input': '<dict of 1 items>'}` (validation.py:84-106,149-195) | missing | model: there's no pydantic field validation on `ChatCompletionRequest`. The run aborts in `online-renderer.render-chat` with `no such key: messages` | bench-s4-1-a |
| | b | Confirmed: `2 validation errors:` (`list_type` body.messages, `int_parsing` body.max_tokens), param `body.messages` | missing | model: same gap. The run aborts in `tokenize-params.post-init` on the string `max_tokens` | bench-s4-1-b |
| | c | Confirmed: all three messages and params, including `Requested sample logprobs of 128256, which is greater than max allowed: 20 (parameter=logprobs, value=128256)` (protocol.py:876-889, sampling_params.py:919-933, model.py:282) | pass | | bench-s4-1-c, goes through `sampling-params.verify` |
| | d | Confirmed: before validators run last-defined first, so `check_tool_usage` runs before `check_logprobs`, and both run before field validation. Still a JSON 400 with `stream: true` | pass | | bench-s4-1-d (the `$.body missing messages` schema warnings come from the deliberately invalid input) |
| **S4-2** | a | Confirmed. `priority` rides on the engine request; `FCFSRequestQueue` appends and pops in arrival order (request_queue.py:75-84; scheduler.py:794-802) | pass | | bench-s4-2-a: `async-llm.generate` input `priority == 5`; policy fcfs |
| | b | Confirmed (base/serving.py:42,258-269) | missing | model: `X-Vllm-Priority` / `_get_priority` isn't modeled. `create-chat-completion` always takes `body.priority`, so the engine sees 7, not -3 | bench-s4-2-b |
| | c | Confirmed: `less_than_equal` for body.priority and `greater_than_equal` for body.seed (protocol.py:65-66,238,388-391); checked with pydantic | fail | model: there are no `ge`/`le` bounds, so the model returns 200 for `priority: 2**63`. The seed request then aborts in `sampler.add-request` (string to int). simulator (minor): an out-of-int64 value can only be sent as a `$bigint` string | bench-s4-2-c |
| | d | Confirmed (engine/protocol.py:25-76) | partial | model: 200 with no structured output is right, but the `warning_once` naming `['guided_json']` isn't modeled | bench-s4-2-d |
| **S4-3** | a | Confirmed, **corrected: `created` is `int(time.time())`, so two listings in the same second share it; only the permission `id` always differs** | partial | model: `show-available-models` returns id/object/owned_by/root/max_model_len but no `created`, `parent: null` or `permission` (engine/protocol.py:90-118) | bench-s4-3-a |
| | b | Confirmed: `{"detail": "Not Found"}`. Starlette's router raises a starlette `HTTPException`, and vLLM's handler is registered for FastAPI's subclass, so FastAPI's default handler answers | missing | model: no unknown-route 404. `GET /v1/models/llama-8b` returns the list | bench-s4-3-b |
| | c | Confirmed (serve/engine/serving.py:49-91; models/serving.py:144-147) | pass | | bench-s4-3-c |
| | d | Confirmed (fingerprint.py:48-84; base/serving.py:156-167) | missing | model: `system_fingerprint` appears nowhere in the model, on either world | bench-s4-3-d, bench-s4-3-d-moe |
| | e | Confirmed, **corrected: content chunks *omit* `system_fingerprint` (`model_dump_json(exclude_unset=True)`, serving.py:588,829); they don't carry `null`** | missing | model: as (d) | bench-s4-3-e |
| **S4-4** | a | Confirmed (routers.py:49-77; gpu_model_runner.py:3158-3166), body `{"detail":"Not Found"}` | pass | | bench-s4-4-a: `app-state.supported-tasks` decides, 404 `Not Found`. The mosaic error can't show the body shape |
| | b | Confirmed (generate/factories.py:20-40) | pass | | bench-s4-4-b (the inner route re-runs the middleware for the inner path, which is harmless) |
| | c | Confirmed from vLLM code (completion/protocol.py:591-610 raise `VLLMValidationError`, which isn't caught by `except pydantic.ValidationError`). The `model_hosting_container_standards` decorators weren't available to read | fail | model: `post-invocations` dispatches on whether `messages`/`prompt` is present, not by validation, so it answers `Cannot find suitable handler...` | bench-s4-4-c |
| | d | Confirmed. The message is `Expected one of: ['ChatCompletionRequest', 'CompletionRequest']`, with quotes (an f-string of a list) | fail | model: `prompt: 5` is routed into completions, and the run aborts in `render-completion`. The model's message text also lacks the quotes | bench-s4-4-d |
| | e | Confirmed. `HTTPException` (FastAPI) goes to vLLM's handler: type `Bad Request`, `JSON decode error: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)` | missing | model: no JSON decode step | bench-s4-4-e |
| **S4-5** | a | Confirmed (responses/protocol.py:880-921; serving.py:778-842) | partial | model: `id` resp_N, object, model and `status: incomplete` are right. `incomplete_details` and `max_output_tokens` are absent from the response | bench-s4-5-a |
| | b | Confirmed (serving.py:160-165,352-359,1133-1147,1185-1191) | partial | model: 404 `invalid_request_error` with the exact message, but `param` is null. `get-v1-responses-response-id`'s `on_error` passes no `param` to `vllm-error-handler` (the code returns the ErrorResponse with `param: "response_id"`, api_router.py:98-104) | bench-s4-5-b |
| | c | Confirmed (serving.py:262-273) | pass | | bench-s4-5-c, no generate |
| | d | Confirmed (serving.py:275-283,361-368) | pass | | bench-s4-5-d, renderer not called |
| | e | Confirmed (serving.py:1156-1172) | partial | model: same dropped `param` on the cancel route | bench-s4-5-e |
| **S4-6** | a | Confirmed (connector.py:314-332,410-417) | partial | contract: the outcomes are right (base64 ok, 501 `NotImplementedError`), but `media-connector.fetch-image` runs `@rank0` (the GPU worker), not in the API server's thread pool | bench-s4-6-a |
| | b | Confirmed; `sanitize_message` leaves `/etc/passwd` alone | partial | world/model: the 500 without the flag is right. `--allowed-local-media-path` isn't a config and `hf-renderer.render-messages` passes only `image_url`, so the `/data` case can be driven only by calling `fetch-image` directly (it gives the right `value-error` text). Edit needed: add the config and pass it through | bench-s4-6-b |
| | c | Confirmed. Note: `sanitize_message` replaces a URL path with two or more segments that ends in `file.ext` with `<path>` in the `value=` suffix | fail | model: the 404 comes out as `code: vllm-unprocessable-entity-error` with no `(parameter=image_url, value=...)` suffix, because `create-error-response`'s first branch passes any error with status >= 400 through unchanged. `--allowed-media-domains` isn't a config either (the direct call is right) | bench-s4-6-c |
| | d | Confirmed (connections.py:25-29,286-318; envs.py:73,79). aiohttp's float timeout is not verified | fail | model: there's no `_async_retry`. One 5 s timeout, then 500 after about 5 s, against the code's 3 attempts and about 110 s | bench-s4-6-d: 1 call, 5021 ms |
| **S4-7** | a | Confirmed (qwen2_vl.py:989-1040,1236-1265,1394-1396). Pixel bounds 3136 to 12845056 per the checkpoint (the model's defaults agree) | partial | model: `qwen2-vl-processing-info.get-num-image-tokens` gives grid 1x40x80 and 800 tokens, and `get-placeholder-str` is right, but nothing on the chat path calls them. contract: they run `@rank0`. world: a data URL carries no image size | bench-s4-7-a |
| | b | Confirmed, **corrected: `created_cache_tokens` isn't null. The output state starts it at 0 and the scheduler fills it from `PrefillStats.finalize` with the full-block prompt tokens written to the prefix cache (output_processor.py:183,733-740; scheduler.py:2208-2212; stats.py:340-345), about floor(prompt_tokens/16)*16 on a cold cache with prefix caching on** | fail | model: the image request reports `prompt_tokens: 12`, with no image-token expansion and no `prompt_tokens_details` | bench-s4-7-b |
| | c | Confirmed (896x504, grid 36x64, 576) | partial | model: right on a direct call only; it can't be driven through chat | bench-s4-7-c |
| | d | Confirmed (serving.py:73-88) | missing | model: no `multimodal_tokens` / `prompt_tokens_details` | bench-s4-7-d |
| | e | Confirmed (serving.py:90-97) | missing | model/world: no `--enable-prompt-tokens-details` knob | bench-s4-7-e |
| **S4-8** | a | Confirmed (params.py:351-359,524-535; online_renderer.py:773-784). The character pre-check can't fire first, since `max_chars_per_token` is the longest vocab entry (hf.py:122) | fail | model: `base-renderer.tokenize-prompt` counts the whole prompt instead of encoding with `max_length = max_input_tokens + 1`, so it says `contains 10008 input tokens`, not `at least 8193` | bench-s4-8-a |
| | b | Confirmed | fail | model: the text gives `10001 input tokens` (should be `at least 8193`). The id list (`10000`, no "at least") is right | bench-s4-8-b |
| | c | Confirmed (serving.py:229-249,420-424) | pass | | bench-s4-8-c: 8184 words plus 8 template tokens = 8192 |
| | d | Confirmed (params.py:243-283; chat protocol.py:657-675) | missing | model: the output-bound message is exact, but `tokenize-params.post-init` has no `truncate_prompt_tokens` check, so the second request returns 200 | bench-s4-8-d |
| | e | Confirmed. `CompletionRequest.max_tokens` defaults to 16, so `max_truncation_tokens` = 8191, and `get_max_tokens` clamps to 1 | missing | model: `truncate_prompt_tokens` appears nowhere in the model; the request is refused with `10001 input tokens` | bench-s4-8-e |

Case scores (worst step): S4-1 missing, S4-2 fail, S4-3 missing, S4-4 fail, S4-5 partial, S4-6 fail, S4-7 fail,
S4-8 fail. Steps passed per case: 2/4, 1/4, 1/5, 2/5, 2/5, 0/4, 0/5, 1/5, for **9 / 37**.

World note: `fp8-llama-3-8b` serves `neuralmagic/Meta-Llama-3-8B-Instruct-FP8-KV` (served name `llama-3-8b-fp8`),
not the `-FP8` checkpoint the benchmark names. That doesn't matter for S4-8.

## 2. Wrong claims in the model

1. `exception-handling.create-error-response`: its first branch returns any input with `status >= 400` unchanged,
   which skips the `VLLMUnprocessableEntityError` and `VLLMValidationError` mapping for errors that already carry a
   status. Code: error_response.py:41-48 maps by exception type, and `str(exc)` appends `(parameter=..., value=...)`
   (exceptions.py:49-56). Visible in S4-6(c).
2. `sagemaker-router.post-invocations`: it chooses chat or completions by whether `messages` or `prompt` is present.
   The code tries `TypeAdapter.validate_python` in order and lets a non-`ValidationError` escape
   (sagemaker/api_router.py:120-140). The model's message also drops the quotes the list repr has.
3. `base-renderer.tokenize-prompt`: it counts the full prompt. The code encodes with truncation at
   `max_input_tokens + 1` (params.py:351-359), so text prompts always report `at least <max+1>`.
4. `media-connector.fetch-image` / `remote-media-host.get`: there's no retry or backoff (connections.py:286-318:
   timeouts x4 per attempt, 1 s and 4 s sleeps, 3 attempts).
5. `openai-serving-models.show-available-models`: the card omits `created`, `parent` and `permission`
   (engine/protocol.py:90-118).
6. `openai-serving-responses.get-v1-responses-response-id` and the cancel route drop `param: "response_id"`; the code
   returns the handler's ErrorResponse as is (responses/api_router.py:98-124).
7. `openai-serving-chat.post-v1-chat-completions` (and the other routes) carry an ASSUMPTION that a request with no
   Content-Type is a JSON client's. The code reads `headers.get("content-type", "")`, so a missing header is a 400
   `Unsupported Media Type` (api_utils.py:350-356).
8. The chat path never applies the Qwen2-VL prompt replacement: an image request reports `prompt_tokens: 12`.
   `media-connector` and `qwen2-vl-processing-info` run on `rank0`, not in the API server process
   (renderers/chat_utils.py, qwen2_vl.py:1236-1265).

Things the code has and the model lacks entirely: pydantic field validation (`missing`, `list_type`, `int_parsing`,
`ge`/`le`), the `X-Vllm-Priority` header, `system_fingerprint`, `prompt_tokens_details`, `truncate_prompt_tokens`,
the extra-field and guided warning, the unknown-route 404, and the `/invocations` JSON decode error.

Claims I checked and found correct: the `check_tool_usage` / `check_logprobs` / `validate_stream_options` order and
texts (protocol.py:821-1031); the `validate_json_request` message with no param (validation.py:158-185, since a
string error has no `loc`); `_check_model`'s 404 text; the Responses background, previous-response and >= checks;
the data-URL, file-URL and allowed-domain texts; the Qwen2-VL `smart_resize` arithmetic and its documented
round-half-even caveat; the TokenizeParams output-bound message; and the fcfs queue. A `--cite-sample 12 --seed 404`
draw (outside this group) resolved and matched the cited code in all 12.

## 3. Builder findings

The fragments and the merged model contain no "docs versus code" findings for this group. The builders' notes are
off limits under the blind rules. Two docs-versus-code points in the benchmark itself, both confirmed:

- The `priority` field description says a non-zero priority "will raise an error" without priority scheduling.
  Nothing checks it; fcfs ignores it (protocol.py:388-397). The model agrees.
- `store` defaults to true but is silently disabled without `VLLM_ENABLE_RESPONSES_API_STORE` (serving.py:160-165,
  352-359). The model agrees.

## 4. Simulator gaps

- **Integers beyond int64** (S4-2(c)): `{$bigint}` reaches behaviors as a string, so a model can't apply a numeric
  `le=2**63-1` check without string comparison. It didn't decide the score, because the model has no bound.
- **Response body shape** (S4-3(b), S4-4(a)): a mosaic error is `{code, message, status, data}`, so FastAPI's
  `{"detail": "Not Found"}` can't be told apart from an `ErrorResponse` with type `Not Found`.
- **CEL cost on long prompts** (S4-8(c)): an 8,000-token prompt aborts in `kv-cache-utils.request-block-hasher`
  unless the scenario raises `max_cel_cost` (I used 1e10).
- **Raw request bytes** (S4-4(e)): an HTTP entry takes a structured body. The malformed `{` was sent as a string,
  and no model can express "JSON decode before validation" without a raw-body input. The model doesn't model it,
  so I scored it missing, not sim-gap.

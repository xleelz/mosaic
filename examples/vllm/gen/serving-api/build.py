#!/usr/bin/env python3
"""Generate examples/vllm/fragments/serving-api.yaml and skips/serving-api.json.

Run from anywhere:  python3 -I examples/vllm/gen/serving-api/build.py
The hand-written parts live in this file as Python data; the repetitive parts
(thin dev/RL routes, LLM delegations, boundary stubs, skips) are generated.
"""
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))  # examples/vllm
E = "vllm/entrypoints/"


def s(path, a, b=None):
    return f"{path}:{a}-{b}" if b else f"{path}:{a}"


comps, ifaces, schemas, configs, flows, scenarios = [], [], [], [], [], []


def comp(id, name, kind, parent, sources, summary, **kw):
    c = {"id": id, "name": name, "kind": kind, "parent": parent, "layer": kw.pop("layer", "api"),
         "summary": summary, "sources": sources}
    c.update(kw)
    comps.append(c)
    return c


def iface(component, name, kind, sources, summary, **kw):
    i = {"component": component, "name": name, "kind": kind, "summary": summary, "sources": sources}
    i.update(kw)
    ifaces.append(i)
    return i


def boundary_comp(id, name, parent, owner, sources, summary, layer="frontend"):
    comps.append({"id": id, "name": name, "kind": "module", "parent": parent, "layer": layer,
                  "summary": summary, "sources": sources,
                  "attributes": {"boundary": True, "owner": owner}})


def stub(component, name, owner, sources, summary, request=None, response=None, errors=None, kind="rpc"):
    i = {"component": component, "name": name, "kind": kind, "summary": summary, "sources": sources,
         "attributes": {"boundary": True, "owner": owner}}
    if request is not None:
        i["request"] = request
    if response is not None:
        i["response"] = response
    if errors:
        i["errors"] = errors
    ifaces.append(i)


def obj(props, required=None):
    o = {"type": "object", "properties": props}
    if required:
        o["required"] = required
    return o


STR = {"type": "string"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}

# ---------------------------------------------------------------------------
# Configs (serving-api owns the frontend args and the env flags its code reads)
# ---------------------------------------------------------------------------
CLI = E + "launchers/cli_args.py"
ENVS = "vllm/envs.py"


def cfg(id, typ, value, default, summary, sources, key, boundary_owner=None):
    c = {"id": id, "type": typ, "value": value, "default": default, "summary": summary,
         "sources": sources, "attributes": {"key": key}}
    if boundary_owner:
        c["attributes"].update({"boundary": True, "owner": boundary_owner})
    configs.append(c)


cfg("api-key", "array", None, None, "--api-key: bearer tokens the AuthenticationMiddleware accepts on /v1, /v2, /inference and /cohere (deployed: unset, so no middleware)",
    [s(CLI, 325), s(E + "serve/middleware/register.py", 32, 36)], "api_key")
cfg("enable-server-load-tracking", "boolean", False, False, "--enable-server-load-tracking: count in-flight requests for GET /load",
    [s(CLI, 152), s(E + "launchers/api_server/app_state.py", 175, 176)], "enable_server_load_tracking")
cfg("sse-keep-alive-interval", "integer", 0, 0, "--sse-keep-alive-interval (seconds): 0 disables SSE keep-alive comments",
    [s(CLI, 156), s(E + "openai/chat_completion/api_router.py", 75, 79)], "sse_keep_alive_interval")
cfg("enable-tokenizer-info-endpoint", "boolean", False, False, "--enable-tokenizer-info-endpoint: registers GET /tokenizer_info",
    [s(CLI, 163), s(E + "serve/tokenize/api_router.py", 86, 99)], "enable_tokenizer_info_endpoint")
cfg("enable-scale-out", "boolean", False, False, "--enable-scale-out: without it (and without render/tokens-only mode) every scale-out route answers 403",
    [s(CLI, 207), s(E + "scale_out/factories.py", 82, 110)], "enable_scale_out")
cfg("tokens-only", "boolean", False, False, "--tokens-only: dedicated token-in/token-out server; also registers the unauthenticated POST /abort_requests",
    [s(CLI, 202), s(E + "scale_out/token_in_token_out/api_router.py", 107, 111)], "tokens_only")
cfg("trust-request-chat-template", "boolean", False, False, "--trust-request-chat-template: without it a request carrying chat_template is refused",
    [s(CLI, 95), s("vllm/renderers/online_renderer.py", 678, 697)], "trust_request_chat_template")
cfg("enable-auto-tool-choice", "boolean", False, False, "--enable-auto-tool-choice: needed for tool_choice=auto with HF tokenizers",
    [s(CLI, 116), s("vllm/renderers/online_renderer.py", 257, 267)], "enable_auto_tool_choice")
cfg("exclude-tools-when-tool-choice-none", "boolean", False, False, "--exclude-tools-when-tool-choice-none: with tool_choice none the tools are not rendered into the chat template",
    [s(CLI, 119), s("vllm/renderers/online_renderer.py", 282, 287)], "exclude_tools_when_tool_choice_none")
cfg("enable-request-id-headers", "boolean", False, False, "--enable-request-id-headers: XRequestIdMiddleware echoes X-Request-Id (or a new uuid hex) on every response",
    [s(CLI, 357), s(E + "serve/middleware/register.py", 38, 41), s(E + "serve/middleware/x_request_id.py", 10, 35)], "enable_request_id_headers")
cfg("vllm-max-completion-prompts", "integer", 1024, 1024, "VLLM_MAX_COMPLETION_PROMPTS: the most prompts one /v1/completions request may carry",
    [s(ENVS, 1155, 1157), s(E + "openai/completion/protocol.py", 613, 641)], "VLLM_MAX_COMPLETION_PROMPTS")
cfg("vllm-server-dev-mode", "boolean", False, False, "VLLM_SERVER_DEV_MODE: registers the dev and RL routes (sleep, cache resets, collective_rpc, pause, weight updates)",
    [s(ENVS, 1487), s(E + "launchers/api_server/routers.py", 40, 47)], "VLLM_SERVER_DEV_MODE")
cfg("vllm-allow-runtime-lora-updating", "boolean", False, False, "VLLM_ALLOW_RUNTIME_LORA_UPDATING: registers /v1/load_lora_adapter and /v1/unload_lora_adapter",
    [s(ENVS, 1206, 1208), s(E + "serve/lora/api_router.py", 30, 32)], "VLLM_ALLOW_RUNTIME_LORA_UPDATING")
cfg("vllm-enable-responses-api-store", "boolean", False, False, "VLLM_ENABLE_RESPONSES_API_STORE: without it store=true is silently dropped and background mode is refused",
    [s(ENVS, 1952, 1954), s(E + "openai/responses/serving.py", 160, 166)], "VLLM_ENABLE_RESPONSES_API_STORE")
cfg("vllm-keep-alive-on-engine-death", "boolean", False, False, "VLLM_KEEP_ALIVE_ON_ENGINE_DEATH: keep the HTTP server up when the engine core died",
    [s(ENVS, 1116, 1118), s(E + "launchers/launcher.py", 330, 333)], "VLLM_KEEP_ALIVE_ON_ENGINE_DEATH")
cfg("vllm-enable-cohere-api", "boolean", False, False, "VLLM_ENABLE_COHERE_API: builds the Cohere v2 chat handler (also needs the cohere SDK)",
    [s(ENVS, 1958, 1960), s(E + "generate/api_router.py", 76, 82)], "VLLM_ENABLE_COHERE_API")
cfg("vllm-watchdog-time-ms", "integer", 5000, 5000, "VLLM_WATCHDOG_TIME_S = 5.0, a constant in watchdog_loop (not configurable), as ms",
    [s(E + "launchers/launcher.py", 317), s(E + "launchers/launcher.py", 318, 320)], "VLLM_WATCHDOG_TIME_S")
cfg("api-tokenize-us-per-token", "integer", 20, 20, "ASSUMPTION: API-process tokenization cost per prompt token (the code gives no number; HF fast tokenizers run at roughly 50k tokens/s per core)",
    [s("vllm/renderers/base.py", 628, 643)], "assumption:tokenize_us_per_token")
cfg("api-chat-template-ms", "integer", 1, 1, "ASSUMPTION: Jinja chat-template rendering cost per request (no number in the code)",
    [s("vllm/renderers/hf.py", 1123, 1135)], "assumption:chat_template_ms")
# references to config-platform-owned values
cfg("served-model-name", "array", ["llama-8b"], None, "--served-model-name: aliases clients must use in `model` (deployed llama-8b; default None means the model path)",
    [s("vllm/config/model.py", 325), s(E + "launchers/api_server/app_state.py", 49, 61)], "served_model_name", "config-platform")
cfg("model", "string", "meta-llama/Llama-3.1-8B-Instruct", "Qwen/Qwen3-0.6B", "--model: the served model path",
    [s("vllm/config/model.py", 154), s(E + "launchers/api_server/app_state.py", 59, 61)], "model", "config-platform")
cfg("runner", "string", "auto", "auto", "--runner: auto resolves to generate for *ForCausalLM checkpoints; LLM.generate refuses pooling runners",
    [s("vllm/config/model.py", 162), s(E + "llm.py", 459, 465)], "runner", "config-platform")
cfg("enable-fault-tolerance", "boolean", False, False, "--enable-fault-tolerance: registers /fault_tolerance/apply and /fault_tolerance/status",
    [s("vllm/config/parallel.py", 462), s(E + "launchers/api_server/routers.py", 79, 84)], "enable_fault_tolerance", "config-platform")
cfg("tool-call-parser", "string", None, None, "--tool-call-parser: the tool parser (llama3_json for Llama-3.1); with --enable-auto-tool-choice tool calls are extracted from the output",
    [s(CLI, 122), s(E + "openai/chat_completion/serving.py", 1053, 1090)], "tool_call_parser")
cfg("reasoning-parser", "string", "", "", "--reasoning-parser (structured_outputs_config.reasoning_parser): '' means none",
    ["vllm/config/structured_outputs.py:34", s(E + "openai/chat_completion/serving.py", 997, 1010)], "structured_outputs_config.reasoning_parser", "config-platform")
configs[-1]["attributes"]["none_is"] = ""
cfg("enable-prompt-embeds", "boolean", False, False, "--enable-prompt-embeds: prompt_embeds inputs (and chat content parts) are refused without it",
    ["vllm/config/model.py:319", "vllm/renderers/chat_utils.py:1062-1076"], "enable_prompt_embeds", "config-platform")
cfg("enable-mm-embeds", "boolean", False, False, "--enable-mm-embeds: image_embeds content parts are refused without it",
    ["vllm/config/multimodal.py:326", "vllm/renderers/chat_utils.py:1286-1293"], "enable_mm_embeds", "models-layers")
cfg("limit-mm-per-prompt", "object", {}, {}, "--limit-mm-per-prompt: per-modality item limit (unset modality: 999), read by the processor's validate_num_items",
    ["vllm/config/multimodal.py:307"], "limit_mm_per_prompt", "models-layers")
cfg("model-is-multimodal", "boolean", False, False, "ModelConfig.is_multimodal_model, resolved from the registry for the served architecture (LlamaForCausalLM: text-only)",
    ["vllm/config/model.py:1981", "vllm/renderers/base.py:228-230"], "is_multimodal_model", "config-platform")
cfg("trust-request-mm-kwargs", "boolean", False, False, "--trust-request-mm-kwargs: without it per-request media_io_kwargs / mm_processor_kwargs are refused",
    [s(CLI, 99), s(E + "generate/base/protocol.py", 72, 97)], "trust_request_mm_kwargs")
cfg("media-io-video-num-frames", "integer", 32, 32, "--media-io-kwargs video.num_frames: frames sampled per video (the loader's default is 32)",
    ["vllm/config/multimodal.py:339", "vllm/multimodal/media/video.py:95-101"], "media_io_kwargs.video.num_frames", "models-layers")
cfg("api-video-tokens-per-frame", "integer", 1, 1, "ASSUMPTION: placeholder tokens per video frame after the processor (model-specific; llava-onevision uses many more)",
    ["vllm/renderers/chat_utils.py:1043-1110"], "assumption:video_tokens_per_frame")
cfg("enable-lora", "boolean", False, False, "--enable-lora: without it the workers refuse add_lora, so /v1/load_lora_adapter answers 500",
    ["vllm/engine/arg_utils.py:676", s(E + "openai/models/serving.py", 196, 215)], "enable_lora", "config-platform")
cfg("profiler", "string", "", "", "--profiler-config.profiler (torch, cuda, proton): None ('' here) means profiling is off and the profile routes are not registered",
    ["vllm/config/profiler.py:70", "vllm/engine/arg_utils.py:764"], "profiler_config.profiler", "config-platform")
configs[-1]["attributes"]["none_is"] = ""

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
HEADERS = obj({"Authorization": {"type": "string", "examples": ["Bearer token-abc123"]},
               "X-Request-Id": {"type": "string", "examples": ["req-1"]},
               "Content-Type": {"type": "string", "default": "application/json", "description": "validate_json_request reads it; JSON clients send application/json"}})
schemas.append({"id": "ServingHttpHeaders", "summary": "The request headers the routes read (Authorization for --api-key, X-Request-Id for the request id).",
                "schema": HEADERS})
schemas.append({"id": "ServingErrorResponse", "summary": "ErrorResponse{error: ErrorInfo{message, type, param, code}} (serve/engine/protocol.py:79-87).",
                "schema": obj({"error": obj({"message": STR, "type": {"type": "string", "examples": ["BadRequestError"]},
                                             "param": STR, "code": {"type": "integer", "examples": [400]}})})})
MSG = obj({"role": {"type": "string", "examples": ["user"]},
           "content": {"type": ["string", "array", "null"], "examples": ["What is the capital of France?"]},
           "tool_calls": {"type": ["array", "null"], "items": {"type": "object"}, "default": None}}, ["role", "content"])
schemas.append({"id": "ServingChatCompletionRequest",
                "summary": "ChatCompletionRequest body fields the model reads (openai/chat_completion/protocol.py). Branch fields (chat_template, tool_choice, ...) come from scenario input only.",
                "schema": obj({"model": {"type": "string", "examples": ["llama-8b"]},
                               "messages": {"type": "array", "items": MSG, "default": [{"role": "user", "content": "What is the capital of France?"}]},
                               "max_tokens": {"type": "integer", "examples": [16]},
                               "max_completion_tokens": {"type": ["integer", "null"], "default": None},
                               "stream": {"type": "boolean", "default": False},
                               "n": {"type": "integer", "default": 1},
                               "temperature": {"type": ["number", "null"], "default": None},
                               "top_p": {"type": ["number", "null"], "default": None},
                               "top_k": {"type": ["integer", "null"], "default": None},
                               "min_p": {"type": ["number", "null"], "default": None},
                               "seed": {"type": ["integer", "null"], "default": None},
                               "stop": {"type": ["string", "array", "null"], "items": STR, "default": None},
                               "stop_token_ids": {"type": ["array", "null"], "items": INT, "default": None},
                               "include_stop_str_in_output": {"type": "boolean", "default": False},
                               "ignore_eos": {"type": "boolean", "default": False},
                               "presence_penalty": {"type": ["number", "null"], "default": None},
                               "frequency_penalty": {"type": ["number", "null"], "default": None},
                               "repetition_penalty": {"type": ["number", "null"], "default": None},
                               "response_format": {"type": ["object", "null"], "default": None},
                               "structured_outputs": {"type": ["object", "null"], "default": None},
                               "cache_salt": {"type": ["string", "null"], "default": None},
                               "tools": {"type": ["array", "null"], "items": {"type": "object"}, "default": None},
                               "tool_choice": {"type": ["string", "object", "null"], "default": None},
                               "stream_options": {"type": ["object", "null"], "default": None},
                               "chat_template": {"type": ["string", "null"], "default": None},
                               "media_io_kwargs": {"type": ["object", "null"], "default": None},
                               "mm_processor_kwargs": {"type": ["object", "null"], "default": None},
                               "priority": {"type": ["integer", "null"], "default": None},
                               "min_tokens": {"type": ["integer", "null"], "default": 0},
                               "logprobs": {"type": ["boolean", "null"], "default": False},
                               "top_logprobs": {"type": ["integer", "null"], "default": 0},
                               "skip_special_tokens": {"type": ["boolean", "null"], "default": True},
                               "logit_bias": {"type": ["object", "null"], "default": None},
                               "allowed_token_ids": {"type": ["array", "null"], "items": INT, "default": None},
                               "bad_words": {"type": ["array", "null"], "items": STR, "default": None},
                               "stream_interval": {"type": ["integer", "null"], "default": None},
                               "prompt_logprobs": {"type": ["integer", "null"], "default": None},
                               "echo": {"type": "boolean", "default": False},
                               "add_generation_prompt": {"type": "boolean", "default": True, "description": "ASSUMPTION: the field default is filled before check_generation_prompt, which in the code reads the raw data (an omitted flag is falsy there)"},
                               "continue_final_message": {"type": "boolean", "default": False},
                               "chat_template_kwargs": {"type": ["object", "null"], "default": None},
                               "use_beam_search": {"type": "boolean", "default": False},
                               "request_id": {"type": ["string", "null"], "default": None},
                               "cache_salt": {"type": ["string", "null"], "default": None}}, ["messages"])})
schemas.append({"id": "ServingCompletionRequest", "summary": "CompletionRequest body fields the model reads (openai/completion/protocol.py).",
                "schema": obj({"model": {"type": "string", "examples": ["llama-8b"]},
                               "prompt": {"type": ["string", "array"], "items": {"type": ["string", "integer", "array"]}, "default": ["The capital of France is"]},
                               "max_tokens": {"type": ["integer", "null"], "examples": [16]},
                               "stream": {"type": "boolean", "default": False},
                               "stream_options": {"type": ["object", "null"], "default": None},
                               "n": {"type": "integer", "default": 1},
                               "temperature": {"type": ["number", "null"], "default": None},
                               "top_p": {"type": ["number", "null"], "default": None},
                               "top_k": {"type": ["integer", "null"], "default": None},
                               "seed": {"type": ["integer", "null"], "default": None},
                               "stop": {"type": ["string", "array", "null"], "items": STR, "default": None},
                               "stop_token_ids": {"type": ["array", "null"], "items": INT, "default": None},
                               "ignore_eos": {"type": "boolean", "default": False},
                               "min_tokens": {"type": ["integer", "null"], "default": 0},
                               "logprobs": {"type": ["integer", "null"], "default": None},
                               "include_stop_str_in_output": {"type": "boolean", "default": False},
                               "skip_special_tokens": {"type": ["boolean", "null"], "default": True},
                               "structured_outputs": {"type": ["object", "null"], "default": None},
                               "suffix": {"type": ["string", "null"], "default": None},
                               "echo": {"type": "boolean", "default": False},
                               "logit_bias": {"type": ["object", "null"], "default": None},
                               "allowed_token_ids": {"type": ["array", "null"], "items": INT, "default": None},
                               "bad_words": {"type": ["array", "null"], "items": STR, "default": None},
                               "stream_interval": {"type": ["integer", "null"], "default": None},
                               "prompt_logprobs": {"type": ["integer", "null"], "default": None},
                               "length_penalty": {"type": "number", "default": 1.0},
                               "use_beam_search": {"type": "boolean", "default": False}}, ["prompt"])})
schemas.append({"id": "ServingResponsesRequest", "summary": "ResponsesRequest body fields the model reads (openai/responses/protocol.py: store defaults to true, background to false).",
                "schema": obj({"model": {"type": "string", "examples": ["llama-8b"]},
                               "input": {"type": ["string", "array"], "items": {"type": "object"}, "examples": ["Hello!"]},
                               "store": {"type": "boolean", "default": True},
                               "background": {"type": "boolean", "default": False},
                               "stream": {"type": "boolean", "default": False},
                               "max_output_tokens": {"type": "integer", "examples": [16]},
                               "previous_response_id": {"type": ["string", "null"], "default": None},
                               "previous_input_messages": {"type": ["array", "null"], "items": {"type": "object"}, "default": None}}, ["input"])})
COMPLETION_OUTPUT = obj({"index": {"type": "integer", "default": 0},
                         "text": {"type": "string", "examples": ["The capital of France is Paris."]},
                         "token_ids": {"type": "array", "minItems": 7, "maxItems": 7, "items": {"type": "integer", "minimum": 1, "maximum": 128000}},
                         "finish_reason": {"type": "string", "enum": ["stop", "length", "abort", "error"], "examples": ["stop"]}})
GEN_RESULT = obj({"request_id": {"type": "string", "examples": ["chatcmpl-req-1"]},
                  "finished": {"type": "boolean", "default": True},
                  "finish_reason": {"type": ["string", "null"], "examples": ["stop"]},
                  "num_outputs": {"type": "integer", "default": 1},
                  "token_ids": {"type": "array", "minItems": 7, "maxItems": 7, "items": {"type": "integer", "minimum": 1, "maximum": 128000}},
                  "text": {"type": "string", "examples": ["The capital of France is Paris."]}})
schemas.append({"id": "ServingPoolingRequestOutput", "summary": "PoolingRequestOutput (vllm/outputs.py), the item AsyncLLM.encode yields.",
                "schema": obj({"request_id": {"type": "string", "examples": ["embd-req-1-0"]},
                               "outputs": obj({"data": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number"}}}),
                               "prompt_token_ids": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "integer", "minimum": 1, "maximum": 128000}},
                               "finished": {"type": "boolean", "default": True}})})


def http_req(body_schema=None, path=None, extra=None):
    props = {"path": {"type": "string", "examples": [path]} if path else STR,
             "headers": {"$ref": "ServingHttpHeaders"}}
    if body_schema is not None:
        props["body"] = body_schema if isinstance(body_schema, dict) else {"$ref": body_schema}
    if extra:
        props.update(extra)
    return obj(props, ["path"])


# ---------------------------------------------------------------------------
# Boundary components and stubs (owners: engine-core, config-platform)
# ---------------------------------------------------------------------------
boundary_comp("async-llm", "AsyncLLM", "engine-core", "engine-core", ["vllm/v1/engine/async_llm.py"],
              "The engine client in the API process (owned by engine-core); serving-api calls it through the EngineClient protocol.")
boundary_comp("llm-engine", "LLMEngine", "engine-core", "engine-core", ["vllm/v1/engine/llm_engine.py"],
              "The synchronous engine the offline LLM class drives (owned by engine-core).")
boundary_comp("engine-args", "EngineArgs", "control", "config-platform", ["vllm/engine/arg_utils.py"],
              "Engine arguments and VllmConfig resolution (owned by config-platform).", layer="control")

AL = "vllm/v1/engine/async_llm.py"
DEAD = {"code": "engine-dead-error", "status": 500, "retryable": False}
stub("async-llm", "generate", "engine-core", [s(AL, 698)],
     "AsyncLLM.generate: adds the request (EngineCoreRequest over ZMQ) and yields RequestOutputs until finished; modeled as one call returning the final output.",
     request="EngineCoreRequest", response=GEN_RESULT,
     errors=[DEAD, {"code": "engine-generate-error", "status": 500, "retryable": False}])
stub("async-llm", "encode", "engine-core", [s(AL, 994)], "AsyncLLM.encode: a pooling request; yields one PoolingRequestOutput.",
     request=obj({"request_id": {"type": "string", "examples": ["embd-req-1-0"]}, "prompt_token_ids": {"type": "array", "items": INT}, "pooling_params": obj({"task": STR})}),
     response="ServingPoolingRequestOutput", errors=[DEAD])
stub("async-llm", "abort", "engine-core", [s(AL, 911)], "AsyncLLM.abort(request_ids): abort in the output processor and the engine core.",
     request=obj({"request_ids": {"type": "array", "items": STR}, "internal": BOOL}), response=obj({}))
stub("async-llm", "check-admission", "engine-core", [s(AL, 316)],
     "The _preflight checks: EngineClient.errored raises dead_error, then check_admission(n) refuses past the request queue limits.",
     request=obj({"n": {"type": "integer", "default": 1}}), response=obj({}),
     errors=[DEAD, {"code": "queue-overflow-error", "status": 503, "retryable": True}, {"code": "max-queued-tokens-error", "status": 503, "retryable": True}])
stub("async-llm", "check-health", "engine-core", [s(AL, 1089)], "AsyncLLM.check_health: raises EngineDeadError when the engine core died.",
     request=obj({}), response=obj({}), errors=[DEAD])
boundary_comp("async-mp-client", "AsyncMPClient", "engine-core", "engine-core", ["vllm/v1/engine/core_client.py:1106-1148"],
              "The engine core's ZMQ client; BackgroundResources.engine_dead marks the engine dead (owned by engine-core).")
stub("async-mp-client", "ensure-alive", "engine-core", [s("vllm/v1/engine/core_client.py", 785, 787)],
     "MPClient.ensure_alive: EngineDeadError once engine_dead is set; AsyncLLM.errored reads the same flag (async_llm.py:1308-1309).",
     request=obj({}), response=obj({"alive": {"type": "boolean", "examples": [True]}}), errors=[DEAD])
stub("async-llm", "add-lora", "engine-core", [s(AL, 1189)], "AsyncLLM.add_lora: load the adapter into the engine (all workers).",
     request=obj({"lora_name": STR, "lora_int_id": INT, "lora_path": STR}), response={"type": "boolean", "examples": [True]},
     errors=[{"code": "lora-adapter-not-found-error", "status": 404, "retryable": False}, {"code": "value-error", "status": 0, "retryable": False}])
for nm, ln, req, resp, summ in [
    ("sleep", 1154, obj({"level": INT, "mode": STR}), obj({}), "AsyncLLM.sleep(level, mode)"),
    ("wake-up", 1169, obj({"tags": {"type": "array", "items": STR}}), {"type": "boolean", "examples": [True]}, "AsyncLLM.wake_up(tags): returns whether fully awake"),
    ("is-sleeping", 1183, obj({}), {"type": "boolean", "examples": [False]}, "AsyncLLM.is_sleeping"),
    ("reset-prefix-cache", 1144, obj({"reset_running_requests": BOOL, "reset_external": BOOL}), {"type": "boolean", "examples": [True]}, "AsyncLLM.reset_prefix_cache: False while blocks are still held"),
    ("collective-rpc", 1205, obj({"method": STR, "args": {"type": "array", "items": STR}, "kwargs": obj({})}), {"type": "array", "minItems": 1, "maxItems": 1, "items": obj({})}, "AsyncLLM.collective_rpc: run a worker method on every worker"),
    ("pause-generation", 952, obj({"mode": STR, "clear_cache": BOOL}), obj({}), "AsyncLLM.pause_generation(mode)"),
]:
    stub("async-llm", nm, "engine-core", [s(AL, ln)], summ, request=req, response=resp,
         errors=[{"code": "value-error", "status": 0, "retryable": False}] if nm == "pause-generation" else None)
EC_PROTO = "vllm/engine/protocol.py"
EC_LINES = {"reset-mm-cache": 181, "reset-encoder-cache": 186, "release-kv-cache-memory": 203, "start-profile": 165, "stop-profile": 176,
            "resume-generation": 245, "is-paused": 250, "init-weight-transfer-engine": 293, "shutdown-weight-transfer-engine": 299,
            "start-weight-update": 303, "start-draft-weight-update": 307, "update-weights": 311, "finish-weight-update": 315,
            "update-weight-version": 319, "get-weight-version": 323, "compute-weight-checksums": 275, "scale-elastic-ep": 259,
            "handle-fault": 279, "get-status": 285, "get-kv-event-sources": 67}
for nm, summ, req, resp in [
    ("reset-mm-cache", "EngineClient.reset_mm_cache", obj({}), obj({})),
    ("reset-encoder-cache", "EngineClient.reset_encoder_cache", obj({}), obj({})),
    ("release-kv-cache-memory", "EngineClient.release_kv_cache_memory (after sleep level 0)", obj({}), obj({})),
    ("start-profile", "EngineClient.start_profile(**overrides)", obj({"profile_prefix": STR}), obj({})),
    ("stop-profile", "EngineClient.stop_profile", obj({}), obj({})),
    ("resume-generation", "EngineClient.resume_generation", obj({}), obj({})),
    ("is-paused", "EngineClient.is_paused", obj({}), {"type": "boolean", "examples": [False]}),
    ("init-weight-transfer-engine", "EngineClient.init_weight_transfer_engine", obj({"init_info": obj({})}), obj({})),
    ("shutdown-weight-transfer-engine", "EngineClient.shutdown_weight_transfer_engine", obj({}), obj({})),
    ("start-weight-update", "EngineClient.start_weight_update", obj({}), obj({})),
    ("start-draft-weight-update", "EngineClient.start_draft_weight_update", obj({}), obj({})),
    ("update-weights", "EngineClient.update_weights", obj({"update_info": obj({})}), obj({})),
    ("finish-weight-update", "EngineClient.finish_weight_update(weight_version)", obj({"weight_version": STR}), obj({})),
    ("update-weight-version", "EngineClient.update_weight_version", obj({"new_version": STR}), obj({})),
    ("get-weight-version", "EngineClient.get_weight_version", obj({}), {"type": "string", "examples": ["v1"]}),
    ("compute-weight-checksums", "EngineClient.compute_weight_checksums: one {param: checksum} map per worker",
     obj({}), {"type": "array", "minItems": 1, "maxItems": 1, "items": obj({"model.embed_tokens.weight": {"type": "string", "examples": ["9f2c"]}})}),
    ("scale-elastic-ep", "AsyncLLM.scale_elastic_ep(new_data_parallel_size, drain_timeout)", obj({"new_data_parallel_size": INT, "drain_timeout": INT}), obj({})),
    ("handle-fault", "EngineClient.handle_fault(FaultToleranceRequest)", obj({"instruction": STR, "params": obj({}), "request_id": STR}), obj({"success": {"type": "boolean", "examples": [True]}})),
    ("get-status", "EngineClient.get_status (fault tolerance)", obj({}), obj({"status": {"type": "string", "examples": ["healthy"]}})),
    ("get-kv-event-sources", "EngineClient.get_kv_event_sources", obj({}), obj({})),
]:
    stub("async-llm", nm, "engine-core", [s(EC_PROTO, EC_LINES[nm])], summ, request=req, response=resp,
         errors=[{"code": "timeout-error", "status": 0, "retryable": False}, {"code": "value-error", "status": 0, "retryable": False}] if nm == "scale-elastic-ep" else None)
stub("async-llm", "from-vllm-config", "engine-core", [s(AL, 241)], "AsyncLLM.from_vllm_config: start the engine-core process(es) and the client.",
     request=obj({"usage_context": STR}), response=obj({}), errors=[DEAD])
stub("async-llm", "get-supported-tasks", "engine-core", [s(AL, 381)], "EngineClient.get_supported_tasks: the tasks the loaded model supports.",
     request=obj({}), response={"type": "array", "minItems": 1, "maxItems": 1, "items": {"type": "string", "examples": ["generate"]}})
stub("async-llm", "shutdown", "engine-core", [s(AL, 296)], "AsyncLLM.shutdown(timeout)", request=obj({"timeout": INT}), response=obj({}))
stub("engine-args", "create-engine-config", "config-platform", ["vllm/engine/arg_utils.py"],
     "AsyncEngineArgs.from_cli_args(args).create_engine_config(): resolve and validate the VllmConfig.",
     request=obj({"model": {"type": "string", "examples": ["meta-llama/Llama-3.1-8B-Instruct"]}}), response=obj({"max_model_len": {"type": "integer", "examples": [131072]}}),
     errors=[{"code": "value-error", "status": 0, "retryable": False}])
LE = "vllm/v1/engine/llm_engine.py"
LE_LINES = {"sleep": 418, "wake-up": 433, "collective-rpc": 485, "apply-model": 501, "reset-prefix-cache": 403, "reset-mm-cache": 396,
            "start-profile": 368, "stop-profile": 392, "release-kv-cache-memory": 426, "get-metrics": 444, "get-tokenizer": 452,
            "get-vllm-config": 174, "set-weight-version": 494, "get-weight-version": 497, "from-engine-args": 174}
stub("llm-engine", "add-request", "engine-core", [s(LE, 229)], "LLMEngine.add_request(request_id, prompt, params): returns the request id.",
     request="EngineCoreRequest", response={"type": "string", "examples": ["0"]}, errors=[{"code": "value-error", "status": 0, "retryable": False}])
stub("llm-engine", "has-unfinished-requests", "engine-core", [s(LE, 203)], "LLMEngine.has_unfinished_requests", request=obj({}), response={"type": "boolean", "examples": [True]})
stub("llm-engine", "step", "engine-core", [s(LE, 319)], "LLMEngine.step: one engine-core step; returns the RequestOutputs produced (FINAL_ONLY: only finished ones).",
     request=obj({}), response=obj({"request_outputs": {"type": "array", "minItems": 1, "maxItems": 1, "items": obj({"request_id": {"type": "string", "examples": ["0"]}, "text": {"type": "string", "examples": ["Paris."]}, "token_ids": {"type": "array", "items": INT}, "finish_reason": {"type": ["string", "null"], "examples": ["stop"]}, "stop_reason": {"type": ["string", "null"]}, "finished": {"type": "boolean", "default": True}})}}), errors=[DEAD])
stub("llm-engine", "abort-request", "engine-core", [s(LE, 224)], "LLMEngine.abort_request(request_ids, internal)", request=obj({"request_ids": {"type": "array", "items": STR}, "internal": BOOL}), response=obj({}))
for nm, summ, resp in [
    ("sleep", "LLMEngine.sleep(level, mode)", obj({})), ("wake-up", "LLMEngine.wake_up(tags)", {"type": "boolean", "examples": [True]}),
    ("collective-rpc", "LLMEngine.collective_rpc(method, timeout, args, kwargs)", {"type": "array", "minItems": 1, "maxItems": 1, "items": obj({})}),
    ("apply-model", "LLMEngine.apply_model(func): run func on every worker's nn.Module", {"type": "array", "minItems": 1, "maxItems": 1, "items": obj({})}),
    ("reset-prefix-cache", "LLMEngine.reset_prefix_cache", {"type": "boolean", "examples": [True]}),
    ("reset-mm-cache", "LLMEngine.reset_mm_cache", obj({})), ("start-profile", "LLMEngine.start_profile", obj({})),
    ("stop-profile", "LLMEngine.stop_profile", obj({})), ("release-kv-cache-memory", "LLMEngine.release_kv_cache_memory", obj({})),
    ("get-metrics", "LLMEngine.get_metrics: a snapshot of the Prometheus metrics", {"type": "array", "minItems": 1, "maxItems": 1, "items": obj({"name": {"type": "string", "examples": ["vllm:num_requests_running"]}})}),
    ("get-tokenizer", "LLMEngine.get_tokenizer", obj({"name_or_path": {"type": "string", "examples": ["meta-llama/Llama-3.1-8B-Instruct"]}})),
    ("get-vllm-config", "LLMEngine.vllm_config (parallel_config.world_size / world_size_across_dp)", obj({"world_size": {"type": "integer", "examples": [1]}, "world_size_across_dp": {"type": "integer", "examples": [1]}})),
    ("set-weight-version", "LLMEngine.set_weight_version", obj({})), ("get-weight-version", "LLMEngine.get_weight_version", {"type": "string", "examples": ["v1"]}),
    ("from-engine-args", "LLMEngine.from_engine_args: build the engine (and its engine-core process) for the offline LLM", obj({})),
]:
    stub("llm-engine", nm, "engine-core", [s(LE, LE_LINES[nm])], summ, request=obj({}), response=resp)

# ---------------------------------------------------------------------------
# Hand-written core (components, interfaces, flows, scenarios) in YAML
# ---------------------------------------------------------------------------
import glob
for fn in sorted(glob.glob(os.path.join(HERE, "core*.yaml"))):
    with open(fn, encoding="utf-8") as f:
        core = yaml.safe_load(f) or {}
    comps.extend(core.get("components") or [])
    ifaces.extend(core.get("interfaces") or [])
    flows.extend(core.get("flows") or [])
    scenarios.extend(core.get("scenarios") or [])
    schemas.extend(core.get("schemas") or [])
    configs.extend(core.get("configs") or [])

# ---------------------------------------------------------------------------
# Thin engine-client routes (dev, RL, profile, cache): gate + call + return
# ---------------------------------------------------------------------------
NOT_FOUND = {"code": "Not Found", "status": 404}


def gated_route(component, method, path, src, gate_cfg, gate_src, call, call_input, ret, summary, extra_steps=None, request_extra=None, gate_title=None):
    from_cfg = isinstance(gate_cfg, str)
    beh = []
    if gate_cfg:
        beh.append({"title": gate_title or f"Route not registered unless {gate_cfg}",
                    "detail": "FastAPI answers 404 for a route that was never included.",
                    "source": gate_src,
                    "if": f"!config['{gate_cfg}']" if from_cfg else gate_cfg[0],
                    "then": [{"fail": {"code": "Not Found", "status": 404, "message": "Not Found"}}]})
    if extra_steps:
        beh.extend(extra_steps)
    if call:
        beh.append({"title": summary, "source": src, "call": call, "input": call_input, "as": "res",
                    "on_error": [{"title": "An engine-side exception goes through the app's exception handlers",
                                  "source": s(E + "serve/exception_handling/register.py", 26, 42),
                                  "call": "exception-handling.vllm-error-handler",
                                  "input": {"code": "= error.code", "status": "= error.status", "message": "= error.message"}}]})
    beh.append({"return": ret})
    name = route_slug(method, path)
    i = iface(component, name, "http", [src], summary, attributes={"method": method, "path": path},
              request=http_req(path=path, extra=request_extra), behavior=beh,
              errors=[NOT_FOUND])
    return i


def route_slug(method, p):
    import re
    p = p.replace("{", "").replace("}", "")
    sl = re.sub(r"[^a-z0-9]+", "-", (method + "-" + p).lower()).strip("-")
    return sl[:64].rstrip("-")


DEV = "vllm-server-dev-mode"
DEV_SRC = s(E + "launchers/api_server/routers.py", 40, 47)
Q = {"query": obj({"level": {"type": "integer", "default": 1}, "mode": {"type": "string", "default": "abort"},
                   "tags": {"type": "array", "maxItems": 0, "items": STR},
                   "reset_running_requests": {"type": "boolean", "default": False},
                   "reset_external": {"type": "boolean", "default": False},
                   "include_dp": {"type": "boolean", "default": True},
                   "clear_cache": {"type": "boolean", "default": True}})}
CACHE = E + "serve/dev/cache/api_router.py"
gated_route("dev-cache-router", "POST", "/reset_prefix_cache", s(CACHE, 20, 44), DEV, DEV_SRC, "async-llm.reset-prefix-cache",
            {"reset_running_requests": "= input.query.reset_running_requests", "reset_connector": "= input.query.reset_external"},
            {"success": "= vars.res.value == true"}, "Reset the local (and optionally external) prefix cache; success=false while blocks are held", request_extra=Q)
gated_route("dev-cache-router", "POST", "/reset_mm_cache", s(CACHE, 47, 54), DEV, DEV_SRC, "async-llm.reset-mm-cache", {}, {"status_code": 200},
            "Reset the multi-modal cache (result not checked)")
gated_route("dev-cache-router", "POST", "/reset_encoder_cache", s(CACHE, 57, 64), DEV, DEV_SRC, "async-llm.reset-encoder-cache", {}, {"status_code": 200},
            "Reset the encoder cache (result not checked)")
SLEEP = E + "serve/dev/sleep/api_router.py"
gated_route("dev-sleep-router", "POST", "/sleep", s(SLEEP, 26, 34), DEV, DEV_SRC, "async-llm.sleep",
            {"level": "= input.query.level", "mode": "= input.query.mode"}, {"status": "sleeping", "level": "= input.query.level"},
            "Put the engine to sleep at the given level (0 pause, 1 offload weights, 2 discard)", request_extra=Q,
            extra_steps=[{"title": "level is validated by the Query(ge=0, le=2) annotation", "source": s(SLEEP, 29),
                          "if": "input.query.level < 0 || input.query.level > 2",
                          "then": [{"fail": {"code": "Bad Request", "status": 400, "message": "level must be between 0 and 2", "data": {"param": "level"}}}]}])
gated_route("dev-sleep-router", "POST", "/release_kv_cache_memory", s(SLEEP, 37, 41), DEV, DEV_SRC, "async-llm.release-kv-cache-memory", {},
            {"status": "kv_cache_released"}, "Release KV cache memory after a level-0 sleep")
gated_route("dev-sleep-router", "POST", "/wake_up", s(SLEEP, 44, 55), DEV, DEV_SRC, "async-llm.wake-up",
            {"tags": "= size(input.query.tags) == 0 ? null : input.query.tags"},
            {"status": "= vars.res.value ? 'awake' : 'sleeping'", "tags": "= size(input.query.tags) == 0 ? null : input.query.tags"},
            "Wake the engine (all tags when none are given); reports awake only when fully awake", request_extra=Q)
gated_route("dev-sleep-router", "GET", "/is_sleeping", s(SLEEP, 58, 61), DEV, DEV_SRC, "async-llm.is-sleeping", {},
            {"is_sleeping": "= vars.res.value"}, "Report whether the engine sleeps")
PROF = E + "serve/profile/api_router.py"
PROF_GATE = ("!('profiler' in config) || config['profiler'] == null || config['profiler'] == ''",)
gated_route("profile-router", "POST", "/start_profile", s(PROF, 35, 45), PROF_GATE, s(PROF, 56, 65), "async-llm.start-profile",
            "= has(input.body) && has(input.body.profile_prefix) ? {'profile_prefix': input.body.profile_prefix} : {}", {"status_code": 200},
            "Start the profiler, passing only the overrides the client supplied", gate_title="Profile routes are registered only when --profiler-config.profiler is set",
            request_extra={"body": obj({"profile_prefix": STR})})
gated_route("profile-router", "POST", "/stop_profile", s(PROF, 48, 53), PROF_GATE, s(PROF, 56, 65), "async-llm.stop-profile", {}, {"status_code": 200},
            "Stop the profiler", gate_title="Profile routes are registered only when --profiler-config.profiler is set")

RL = E + "rl/online/api_router.py"
RL_SRC = s(E + "launchers/api_server/routers.py", 45, 47)
rl_simple = [
    ("POST", "/init_weight_transfer_engine", 159, 168, "async-llm.init-weight-transfer-engine", {"init_info": "= input.body.init_info"}, {"message": "Weight transfer initialized"}, "Initialize the weight transfer engine on the workers", {"body": obj({"init_info": obj({"backend": {"type": "string", "examples": ["nccl"]}})})}),
    ("POST", "/shutdown_weight_transfer_engine", 171, 175, "async-llm.shutdown-weight-transfer-engine", {}, {"message": "Weight transfer shut down"}, "Shut the weight transfer engine down", None),
    ("POST", "/start_weight_update", 178, 182, "async-llm.start-weight-update", {}, {"message": "Weight update started"}, "Start a weight update", None),
    ("POST", "/start_draft_weight_update", 185, 189, "async-llm.start-draft-weight-update", {}, {"message": "Draft weight update started"}, "Start a draft-model weight update", None),
    ("POST", "/update_weights", 192, 201, "async-llm.update-weights", {"update_info": "= input.body.update_info"}, {"message": "Weights updated"}, "Push a weight update", {"body": obj({"update_info": obj({"names": {"type": "array", "maxItems": 1, "items": {"type": "string", "examples": ["model.embed_tokens.weight"]}}})})}),
    ("POST", "/finish_weight_update", 204, 211, "async-llm.finish-weight-update", {"weight_version": "= has(input.body) && has(input.body.weight_version) ? input.body.weight_version : null"}, {"message": "Weight update finished"}, "Finish a weight update, optionally stamping a version", {"body": obj({"weight_version": {"type": "string", "examples": ["v2"]}})}),
    ("POST", "/update_weight_version", 214, 220, "async-llm.update-weight-version", {"new_version": "= input.body.new_version"}, {"success": True, "new_version": "= input.body.new_version"}, "Set the weight version", {"body": obj({"new_version": {"type": "string", "examples": ["v2"]}}, ["new_version"])}),
    ("GET", "/weight_info", 223, 226, "async-llm.get-weight-version", {}, {"weight_version": "= vars.res.value"}, "Report the weight version", None),
]
for m, p, a, b, call, ci, ret, summ, extra in rl_simple:
    gated_route("rl-online-router", m, p, s(RL, a, b), DEV, RL_SRC, call, ci, ret, summ, request_extra=extra)

# ---------------------------------------------------------------------------
# LLM (offline) delegations: one call each into LLMEngine
# ---------------------------------------------------------------------------
LLM = E + "llm.py"
RLO = E + "rl/offline.py"


def llm_method(name, src, call, call_input, ret, summary, request=None, pre=None):
    beh = list(pre or [])
    beh.append({"title": summary, "source": src, "call": call, "input": call_input, "as": "res"})
    beh.append({"return": ret})
    iface("llm", name, "function", [src], summary, request=request or obj({}), behavior=beh)


llm_method("get-tokenizer", s(LLM, 386, 387), "llm-engine.get-tokenizer", {}, "= vars.res.value", "LLM.get_tokenizer: the engine's tokenizer")
llm_method("get-world-size", s(LLM, 389, 405), "llm-engine.get-vllm-config", {},
           "= input.include_dp ? vars.res.value.world_size_across_dp : vars.res.value.world_size",
           "LLM.get_world_size: TP*PP, times DP when include_dp", request=obj({"include_dp": {"type": "boolean", "default": True}}))
llm_method("collective-rpc", s(LLM, 574, 603), "llm-engine.collective-rpc", {"method": "= input.method"}, "= vars.res.value",
           "LLM.collective_rpc: run a worker method on every worker", request=obj({"method": {"type": "string", "examples": ["check_health"]}}))
llm_method("apply-model", s(LLM, 605, 615), "llm-engine.apply-model", {}, "= vars.res.value", "LLM.apply_model: run a function on each worker's model")
llm_method("start-profile", s(LLM, 801, 824), "llm-engine.start-profile", {}, None, "LLM.start_profile")
llm_method("stop-profile", s(LLM, 826, 827), "llm-engine.stop-profile", {}, None, "LLM.stop_profile")
llm_method("reset-prefix-cache", s(LLM, 829, 834), "llm-engine.reset-prefix-cache", {}, "= vars.res.value", "LLM.reset_prefix_cache")
llm_method("sleep", s(LLM, 836, 859), "llm-engine.sleep", {"level": "= has(input.level) ? input.level : 1"}, None, "LLM.sleep(level, mode)", request=obj({"level": {"type": "integer", "default": 1}}))
llm_method("release-kv-cache-memory", s(LLM, 861, 867), "llm-engine.release-kv-cache-memory", {}, None, "LLM.release_kv_cache_memory")
llm_method("wake-up", s(LLM, 869, 885), "llm-engine.wake-up", {}, "= vars.res.value", "LLM.wake_up(tags): whether the engine is fully awake")
llm_method("get-metrics", s(LLM, 887, 898), "llm-engine.get-metrics", {}, "= vars.res.value", "LLM.get_metrics")
llm_method("reset-mm-cache", s(LLM, 407, 409), "llm-engine.reset-mm-cache", {}, None, "LLM.reset_mm_cache: clear the renderer's and the engine's multi-modal caches")
llm_method("from-engine-args", s(LLM, 381, 384), "llm-engine.from-engine-args", {}, {"constructed": True}, "LLM.from_engine_args: LLM(**vars(engine_args))")
for nm, a, b, call, ci, ret, summ in [
    ("init-weight-transfer-engine", 12, 27, "llm-engine.collective-rpc", {"method": "init_weight_transfer_engine"}, None, "RLOfflineMixin.init_weight_transfer_engine: collective_rpc('init_weight_transfer_engine')"),
    ("shutdown-weight-transfer-engine", 29, 31, "llm-engine.collective-rpc", {"method": "shutdown_weight_transfer_engine"}, None, "collective_rpc('shutdown_weight_transfer_engine')"),
    ("start-weight-update", 33, 35, "llm-engine.collective-rpc", {"method": "start_weight_update"}, None, "collective_rpc('start_weight_update')"),
    ("start-draft-weight-update", 37, 39, "llm-engine.collective-rpc", {"method": "start_draft_weight_update"}, None, "collective_rpc('start_draft_weight_update')"),
    ("update-weights", 41, 54, "llm-engine.collective-rpc", {"method": "update_weights"}, None, "collective_rpc('update_weights', update_info)"),
    ("update-weight-version", 62, 64, "llm-engine.set-weight-version", {"weight_version": "= input.new_version"}, None, "LLMEngine.set_weight_version"),
    ("get-weight-version", 66, 68, "llm-engine.get-weight-version", {}, "= vars.res.value", "LLMEngine.get_weight_version"),
]:
    llm_method(nm, s(RLO, a, b), call, ci, ret, summ,
               request=obj({"new_version": {"type": "string", "examples": ["v2"]}}) if nm == "update-weight-version" else None)
# finish_weight_update has a branch: the version is stamped only when given
iface("llm", "finish-weight-update", "function", [s(RLO, 56, 60)], "RLOfflineMixin.finish_weight_update: finish on the workers, then stamp the version if one is given",
      request=obj({"weight_version": {"type": ["string", "null"], "default": None}}),
      behavior=[{"source": s(RLO, 58), "call": "llm-engine.collective-rpc", "input": {"method": "finish_weight_update"}},
                {"title": "Stamp the new weight version", "source": s(RLO, 58, 59), "if": "has(input.weight_version) && input.weight_version != null",
                 "then": [{"call": "llm-engine.set-weight-version", "input": {"weight_version": "= input.weight_version"}}]}])

# ---------------------------------------------------------------------------
# DSML argument converter (regexes are easier to write here than in YAML)
# ---------------------------------------------------------------------------
DS = "vllm/parser/deepseek_v4.py"
HEAD = r'(?s)^\s+name="([^"]+)"(?:\s+string="([^"]*)")?\s*>'
for i in ifaces:
    if i["component"] == "deepseek-v4-parser" and i["name"] == "dsml-arg-converter":
        i["behavior"] = [
            {"title": "Split on the DSML parameter start tag; each chunk is one parameter (the head regex needs name=, string= is optional)",
             "source": s(DS, 69, 76),
             "set": {"vars.chunks": "= input.raw_args.split('<｜DSML｜parameter').slice(1, size(input.raw_args.split('<｜DSML｜parameter')))",
                     "vars.params": {}}},
            {"source": s(DS, 90, 100), "foreach": "= vars.chunks", "as": "c", "index": "k", "max": 32, "steps": [
                {"if": "!vars.c.matches(r'" + HEAD + "')", "then": [{"continue": True}]},
                {"title": "A complete parameter ends at its close tag or at the next parameter; the trailing unclosed one counts only when partial",
                 "source": s(DS, 70, 73),
                 "if": "!vars.c.contains('</｜DSML｜parameter>') && vars.k == size(vars.chunks) - 1 && !input.partial",
                 "then": [{"continue": True}]},
                {"set": {"vars.name": "= replace(vars.c, r'" + HEAD + r".*$', '$1')",
                         "vars.is_str": "= replace(vars.c, r'" + HEAD + r".*$', '$2')",
                         "vars.value": "= replace(vars.c, r'" + HEAD + r"(.*?)(?:</｜DSML｜parameter>.*)?$', '$3')"}},
                {"title": "string=\"true\" keeps the text; otherwise (including a missing string attribute) try JSON and fall back to the literal text",
                 "source": s(DS, 92, 100),
                 "if": "vars.is_str == 'true' || !vars.value.matches(r'(?s)^\\s*(-?[0-9]+(\\.[0-9]+)?([eE][-+]?[0-9]+)?|true|false|null|\\[.*\\]|\\{.*\\}|\".*\")\\s*$')",
                 "then": [{"set": {"vars.params": "= merge(vars.params, {vars.name: vars.value})"}}],
                 "else": [{"set": {"vars.params": "= merge(vars.params, {vars.name: eval(vars.value.trim(), {})})"}}]},
            ]},
            {"title": "json.dumps(params, ensure_ascii=False)", "source": s(DS, 112), "return": {"arguments": "= vars.params"}},
        ]

# ---------------------------------------------------------------------------
# Main HTTP routes: middleware, load tracking, with_cancellation, error mapping
# ---------------------------------------------------------------------------
def token_for(prefix):
    return "= 'disconnect-" + prefix + "' + (has(input.headers) && 'X-Request-Id' in input.headers ? input.headers['X-Request-Id'] : 'anonymous')"


TOKEN = token_for("")
XRID = "= has(input.headers) && 'X-Request-Id' in input.headers ? input.headers['X-Request-Id'] : null"
APIU = E + "serve/utils/api_utils.py"
HTTP_ERRORS = [{"code": "BadRequestError", "status": 400}, {"code": "NotFoundError", "status": 404},
               {"code": "InternalServerError", "status": 500}, {"code": "unauthorized", "status": 401},
               {"code": "Service Unavailable", "status": 503, "retryable": True},
               {"code": "ConnectionRefusedError", "status": 0, "retryable": True}, {"code": "Bad Request", "status": 400}]


JSON_CT_CHECK = {
    "title": "validate_json_request (a route dependency, after the middleware): a Content-Type other than application/json is a RequestValidationError (ASSUMPTION: a request without the header is a JSON client's)",
    "source": s(APIU, 350, 356),
    "if": "has(input.headers) && input.headers != null && 'Content-Type' in input.headers && input.headers['Content-Type'].lowerAscii().split(';')[0].trim() != 'application/json'",
    "then": [{"title": "validation_exception_handler: '<n> validation error:' plus each error, type Bad Request, no param", "source": s(E + "serve/exception_handling/handlers/validation.py", 150, 180),
              "fail": {"code": "Bad Request", "status": 400, "message": "1 validation error:\n  Unsupported Media Type: Only 'application/json' is allowed"}}]}
REQUEST_ID_HEADER = {
    "if": "config['enable-request-id-headers'] && type(vars.res.value) == map",
    "then": [{"title": "XRequestIdMiddleware appends X-Request-Id to the response: the request's header, else uuid4().hex", "source": s(E + "serve/middleware/x_request_id.py", 25, 35),
              "set": {"vars.out": "= merge(vars.res.value, {'headers': {'X-Request-Id': has(input.headers) && 'X-Request-Id' in input.headers ? input.headers['X-Request-Id'] : id('random-uuid', seq('random-uuid'))}})"}}]}


def main_route(component, method, path, src, handler, handler_input, summary, body=None, load=True, cancel=True,
               pre=None, mapper="exception-handling.vllm-error-handler", examples_path=None, extra_errors=None, token_prefix="",
               streams=False, json_ct=True, body_checks=None):
    beh = [{"call": "launcher.accept-connection"}] + list(pre or [])
    beh.append({"title": "ScalingMiddleware (outermost) refuses while elastic EP scales", "source": s(E + "serve/middleware/register.py", 43, 47),
                "call": "scaling-middleware.call", "input": {"path": "= input.path"}})
    beh.append({"call": "authentication-middleware.call", "input": {"path": "= input.path", "headers": "= has(input.headers) ? input.headers : {}"}})
    if json_ct and method == "POST":
        beh.append(JSON_CT_CHECK)
    beh.extend(body_checks or [])
    if load:
        beh.append({"title": "load_aware_call counts the request", "source": s(APIU, 110, 117),
                    "when": "config['enable-server-load-tracking']", "call": "server-load-metrics.increment"})
    on_error = []
    if cancel:
        on_error.append({"when": "error.code == 'canceled' && config['enable-server-load-tracking']",
                         "title": "listen_for_disconnect saw http.disconnect and decremented the counter", "source": s(APIU, 40, 48),
                         "call": "server-load-metrics.decrement"})
        on_error.append({"when": "error.code == 'canceled'", "title": "The client disconnected first: the handler task is cancelled and the wrapper returns None",
                         "source": s(APIU, 83, 91), "return": {"disconnected": True}})
    if load:
        on_error.append({"when": "config['enable-server-load-tracking']", "title": "load_aware_call decrements on an exception or error response",
                         "source": s(APIU, 118, 145), "call": "server-load-metrics.decrement"})
    mapper_input = {"code": "= error.code", "status": "= error.status", "message": "= error.message",
                    "param": "= has(error.data) && error.data != null && 'param' in error.data ? error.data.param : (has(error.data) && error.data != null && 'parameter' in error.data ? error.data.parameter : null)",
                    "value": "= has(error.data) && error.data != null && 'value' in error.data ? error.data.value : null"}
    if mapper == "cohere-serving-chat-v2.error-response":
        mapper_input["request_id"] = "= has(error.data) && error.data != null && 'request_id' in error.data ? error.data.request_id : (has(input.headers) && 'X-Request-Id' in input.headers ? input.headers['X-Request-Id'] : null)"
    on_error.append({"call": mapper, "input": mapper_input})
    call = {"title": "with_cancellation: the handler races a client-disconnect listener" if cancel else summary,
            "source": s(APIU, 75, 91) if cancel else src, "call": handler, "input": handler_input, "as": "res", "on_error": on_error}
    if cancel:
        call["token"] = token_for(token_prefix)
    STREAMING = "has(input.body) && input.body != null && has(input.body.stream) && input.body.stream == true"
    if streams:
        # The handler yields SSE chunks on its stream=true path; the route consumes them. Only a
        # stream=true request is a StreamingResponse that sends each frame as it is produced
        # (api_router.py:75-80); a non-stream request returns the plain response (streams_when).
        call["stream"] = True
        call["on_item"] = [{"if": STREAMING,
                            "then": [{"title": "StreamingResponse sends each SSE frame as it is produced",
                                      "source": s(E + "openai/chat_completion/api_router.py", 75, 80),
                                      "yield": "= vars.item"}]}]
    beh.append(call)
    if load:
        beh.append({"when": "config['enable-server-load-tracking']", "title": "The response's BackgroundTask decrements the counter",
                    "source": s(APIU, 124, 139), "call": "server-load-metrics.decrement"})
    beh.append({"set": {"vars.out": "= vars.res.value"}})
    beh.append(REQUEST_ID_HEADER)
    beh.append({"return": "= vars.out"})
    req = http_req(body, path=examples_path or path)
    extra = {"streams_when": "= " + STREAMING} if streams else {}
    iface(component, route_slug(method, path), "http", [src], summary, attributes={"method": method, "path": path},
          request=req, behavior=beh, errors=HTTP_ERRORS + (extra_errors or []), **extra)


CHAT_R = E + "openai/chat_completion/api_router.py"
main_route("openai-serving-chat", "POST", "/v1/chat/completions", s(CHAT_R, 41, 80), "openai-serving-chat.create-chat-completion",
           {"body": "= input.body", "x_request_id": XRID}, "POST /v1/chat/completions: an OpenAI chat completion, JSON or SSE", body="ServingChatCompletionRequest",
           token_prefix="chatcmpl-", streams=True)
main_route("openai-serving-chat-batch", "POST", "/v1/chat/completions/batch", s(CHAT_R, 83, 108), "openai-serving-chat-batch.create-batch-chat-completion",
           {"body": "= input.body", "x_request_id": XRID}, "POST /v1/chat/completions/batch: several conversations in one request",
           body=obj({"model": {"type": "string", "examples": ["llama-8b"]}, "max_tokens": {"type": ["integer", "null"], "default": None}, "messages": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "array", "minItems": 1, "maxItems": 1, "items": MSG}}}))
main_route("openai-serving-completion", "POST", "/v1/completions", s(E + "openai/completion/api_router.py", 35, 72), "openai-serving-completion.create-completion",
           {"body": "= input.body", "x_request_id": XRID}, "POST /v1/completions: an OpenAI text completion, JSON or SSE", body="ServingCompletionRequest")
RESP_R = E + "openai/responses/api_router.py"
main_route("openai-serving-responses", "POST", "/v1/responses", s(RESP_R, 48, 77), "openai-serving-responses.create-responses",
           {"body": "= input.body", "token": token_for("")}, "POST /v1/responses: create a response (stored, background or streamed)", body="ServingResponsesRequest",
           pre=[{"title": "ResponsesRequest.validate_background runs during body validation (RequestValidationError -> 400 Bad Request)",
                 "source": s(E + "openai/responses/protocol.py", 596, 608),
                 "if": "has(input.body.background) && input.body.background && has(input.body.store) && input.body.store == false",
                 "then": [{"fail": {"code": "Bad Request", "status": 400, "message": "background can only be used when `store` is true", "data": {"param": "background"}}}]}],
           extra_errors=[{"code": "invalid_request_error", "status": 400, "reachable_by": "create-responses fails invalid_request_error 400 (vllm/entrypoints/openai/responses/serving.py:262-282) and the exception handler passes the ErrorResponse through"}, {"code": "Bad Request", "status": 400}])
MODELS_R = E + "openai/models/api_router.py"
iface("openai-serving-models", "get-v1-models", "http", [s(MODELS_R, 20, 25)], "GET /v1/models: the served model(s) and loaded LoRA adapters",
      attributes={"method": "GET", "path": "/v1/models"}, request=http_req(path="/v1/models"),
      errors=[{"code": "unauthorized", "status": 401}, {"code": "ConnectionRefusedError", "status": 0, "retryable": True}],
      behavior=[{"call": "launcher.accept-connection"},
                {"call": "scaling-middleware.call", "input": {"path": "= input.path"}},
                {"title": "/v1/models is under a guarded prefix", "source": s(E + "serve/middleware/authenticate.py", 11),
                 "call": "authentication-middleware.call", "input": {"path": "= input.path", "headers": "= has(input.headers) ? input.headers : {}"}},
                {"call": "openai-serving-models.show-available-models", "as": "m"},
                {"return": "= vars.m.value"}])
LORA_R = E + "serve/lora/api_router.py"
for path, a, b, handler, summ in [("/v1/load_lora_adapter", 63, 74, "openai-serving-models.load-lora-adapter", "POST /v1/load_lora_adapter (VLLM_ALLOW_RUNTIME_LORA_UPDATING)"),
                                  ("/v1/unload_lora_adapter", 81, 96, "openai-serving-models.unload-lora-adapter", "POST /v1/unload_lora_adapter (VLLM_ALLOW_RUNTIME_LORA_UPDATING)")]:
    main_route("openai-serving-models", "POST", path, s(LORA_R, a, b), handler, "= input.body", summ,
               body=obj({"lora_name": {"type": "string", "examples": ["sql-lora"]}, "lora_path": {"type": "string", "examples": ["/models/loras/sql-lora"]}, "load_inplace": {"type": "boolean", "default": False}}),
               load=False, cancel=False, mapper="exception-handling.create-error-response",
               pre=[{"title": "Routes are attached only when runtime LoRA updating is allowed", "source": s(LORA_R, 30, 32),
                     "if": "!config['vllm-allow-runtime-lora-updating']",
                     "then": [{"fail": {"code": "Not Found", "status": 404, "message": "Not Found"}}]}],
               extra_errors=[{"code": "InvalidUserInput", "status": 400}, {"code": "Not Found", "status": 404}])
TOK_R = E + "serve/tokenize/api_router.py"
main_route("serving-tokenization", "POST", "/tokenize", s(TOK_R, 33, 58), "serving-tokenization.create-tokenize", {"body": "= input.body"},
           "POST /tokenize: token ids of a prompt or a chat conversation", load=False,
           body=obj({"model": {"type": "string", "examples": ["llama-8b"]}, "prompt": {"type": "string", "examples": ["Hello world"]}, "messages": {"type": ["array", "null"], "items": {"type": "object"}, "default": None},
                     "add_generation_prompt": {"type": "boolean", "default": True}, "continue_final_message": {"type": "boolean", "default": False},
                     "add_special_tokens": {"type": ["boolean", "null"], "default": None, "description": "null: the request type's default (true for a prompt, false for messages)"}}))
main_route("serving-tokenization", "POST", "/detokenize", s(TOK_R, 61, 83), "serving-tokenization.create-detokenize", {"body": "= input.body"},
           "POST /detokenize: text of token ids", load=False,
           body_checks=[{"title": "DetokenizeRequest.tokens is list[Annotated[int, Field(ge=0, le=2**63 - 1)]]: a negative id fails field validation (RequestValidationError -> 400 Bad Request, param body.tokens.<i>)",
                         "source": s(E + "serve/tokenize/protocol.py", 165, 169),
                         "if": "has(input.body.tokens) && input.body.tokens.exists(t, t < 0)",
                         "then": [{"set": {"vars.neg": "= lists.range(size(input.body.tokens)).filter(i, input.body.tokens[i] < 0)[0]"}},
                                  {"fail": {"code": "Bad Request", "status": 400, "message": "= '1 validation error:\\n  {\\'type\\': \\'greater_than_equal\\', \\'loc\\': \\'body.tokens.' + string(vars.neg) + '\\', \\'msg\\': \\'Input should be greater than or equal to 0\\', \\'input\\': ' + string(input.body.tokens[vars.neg]) + ', \\'ctx\\': {\\'ge\\': 0}}'",
                                            "data": {"param": "= 'body.tokens.' + string(vars.neg)"}}}]}],
           body=obj({"model": {"type": "string", "examples": ["llama-8b"]}, "tokens": {"type": "array", "items": {"type": "integer"}, "default": [128000, 1005, 1005]}}))
ANT_R = E + "anthropic/api_router.py"
ANT_BODY = obj({"model": {"type": "string", "examples": ["llama-8b"]}, "max_tokens": {"type": "integer", "examples": [16]},
                "system": {"type": ["string", "null"], "default": None}, "stream": {"type": "boolean", "default": False},
                "messages": {"type": "array", "minItems": 1, "items": MSG, "default": [{"role": "user", "content": "What is the capital of France?"}]}})
main_route("anthropic-serving-messages", "POST", "/v1/messages", s(ANT_R, 51, 86), "anthropic-serving-messages.create-messages",
           {"body": "= input.body", "x_request_id": XRID}, "POST /v1/messages: the Anthropic Messages API (errors in Anthropic's envelope)", body=ANT_BODY,
           mapper="exception-handling.create-error-response")
main_route("anthropic-serving-messages", "POST", "/v1/messages/count_tokens", s(ANT_R, 89, 119), "anthropic-serving-messages.count-tokens",
           {"body": "= input.body"}, "POST /v1/messages/count_tokens", body=ANT_BODY, mapper="exception-handling.create-error-response")
COH = E + "cohere/api_router.py"
COH_GATE = [{"title": "The Cohere routes are attached only with VLLM_ENABLE_COHERE_API=1 (and the cohere SDK)", "source": s(COH, 291, 297),
             "if": "!config['vllm-enable-cohere-api']", "then": [{"fail": {"code": "Not Found", "status": 404, "message": "Not Found"}}]}]
main_route("cohere-serving-chat-v2", "POST", "/cohere/v2/chat", s(COH, 118, 154), "openai-serving-chat.create-chat-completion",
           {"body": "= merge({'model': has(input.body.model) ? input.body.model : '', 'messages': input.body.messages}, has(input.body.max_tokens) && input.body.max_tokens != null ? dyn({'max_tokens': input.body.max_tokens}) : dyn({}))", "x_request_id": XRID},
           "POST /cohere/v2/chat: Cohere v2 chat through the chat handler; every exception and ErrorResponse goes out in Cohere's {message} envelope", body=ANT_BODY, pre=COH_GATE, mapper="cohere-serving-chat-v2.error-response", streams=True,
           extra_errors=[{"code": "CohereError", "status": 400}])
main_route("cohere-serving-chat-v2", "POST", "/cohere/v2/chat/render", s(COH, 156, 206), "serving-render.render-chat-request",
           {"body": "= {'model': has(input.body.model) ? input.body.model : '', 'messages': input.body.messages}"},
           "POST /cohere/v2/chat/render: tokenize a Cohere v2 chat request without generating", body=ANT_BODY, pre=COH_GATE, load=False,
           mapper="cohere-serving-chat-v2.error-response", extra_errors=[{"code": "CohereError", "status": 400}])

# pooling routes: registered per supported task
EMB_R, CLS_R, POOL_R, SCO_R = (E + "pooling/embed/api_router.py", E + "pooling/classify/api_router.py",
                               E + "pooling/pooling/api_router.py", E + "pooling/scoring/api_router.py")
FAC = E + "pooling/factories.py"
POOL_BODY = obj({"model": {"type": "string", "examples": ["llama-8b"]}, "input": {"type": "array", "items": {"type": "string"}, "default": ["hello world"]}})


def task_gate(tasks, src):
    return [{"call": "app-state.supported-tasks", "as": "tasks"},
            {"title": "Pooling routers are included only for the tasks the model supports", "source": src,
             "if": " && ".join(f"!('{t}' in vars.tasks.value)" for t in tasks),
             "then": [{"fail": {"code": "Not Found", "status": 404, "message": "Not Found"}}]}]


for comp_id, method, path, src, task, prefix, tasks, gsrc in [
    ("serving-embedding", "POST", "/v1/embeddings", s(EMB_R, 28, 43), "embed", "embd", ["embed"], s(FAC, 132, 135)),
    ("serving-embedding", "POST", "/v2/embed", s(EMB_R, 46, 61), "embed", "embd", ["embed"], s(FAC, 132, 135)),
    ("serving-classification", "POST", "/classify", s(CLS_R, 26, 33), "classify", "classify", ["classify"], s(FAC, 125, 130)),
    ("serving-pooling", "POST", "/pooling", s(POOL_R, 27, 39), "embed", "pooling", ["embed", "classify", "token_embed", "token_classify"], s(FAC, 118, 123)),
    ("serving-scores", "POST", "/score", s(SCO_R, 37, 49), "score", "score", ["embed", "score", "classify"], s(FAC, 137, 140)),
    ("serving-scores", "POST", "/v1/score", s(SCO_R, 52, 66), "score", "score", ["embed", "score", "classify"], s(FAC, 137, 140)),
    ("serving-scores", "POST", "/rerank", s(SCO_R, 69, 81), "score", "rerank", ["embed", "score", "classify"], s(FAC, 137, 140)),
    ("serving-scores", "POST", "/v1/rerank", s(SCO_R, 84, 99), "score", "rerank", ["embed", "score", "classify"], s(FAC, 137, 140)),
    ("serving-scores", "POST", "/v2/rerank", s(SCO_R, 102, 111), "score", "rerank", ["embed", "score", "classify"], s(FAC, 137, 140)),
]:
    if comp_id == "serving-scores":
        main_route(comp_id, method, path, src, "serving-scores.serve-score",
                   {"prefix": prefix, "body": "= input.body", "x_request_id": XRID},
                   f"{method} {path}: score (queries, documents) pairs with the model's scoring IO processor",
                   body=obj({"model": {"type": "string", "examples": ["llama-8b"]},
                             "queries": {"type": ["string", "array"], "examples": ["What is the capital of France?"]},
                             "documents": {"type": ["string", "array"], "examples": ["The capital of France is Paris."]},
                             "top_n": {"type": ["integer", "null"], "default": None}}),
                   pre=task_gate(tasks, gsrc))
        continue
    if path == "/v2/embed":
        # CohereEmbedRequest carries its texts under `texts` (protocol.py:229-250); the handler embeds them like `input`
        main_route(comp_id, method, path, src, "pooling-base-serving.serve",
                   {"task": task, "prefix": prefix, "body": "= has(input.body.texts) && input.body.texts != null ? merge(omit(input.body, 'texts', 'embedding_types'), {'input': input.body.texts}) : input.body", "x_request_id": XRID},
                   f"{method} {path}: Cohere embed request (texts)", body=obj({"model": {"type": "string", "examples": ["llama-8b"]}, "input": {"type": "array", "items": {"type": "string"}, "default": ["hello world"]},
                                                                                "texts": {"type": ["array", "null"], "items": {"type": "string"}, "default": None},
                                                                                "embedding_types": {"type": ["array", "null"], "items": {"type": "string"}, "default": None}}),
                   pre=task_gate(tasks, gsrc))
        continue
    main_route(comp_id, method, path, src, "pooling-base-serving.serve",
               {"task": task, "prefix": prefix, "body": "= input.body", "x_request_id": XRID},
               f"{method} {path}: pooling request ({task})", body=POOL_BODY, pre=task_gate(tasks, gsrc))

# scale-out routes: 403 unless enabled
SO_GATE = [{"title": "Scale-out routes answer 403 unless --enable-scale-out (or render / tokens-only mode)", "source": s(E + "scale_out/factories.py", 82, 110),
            "call": "serving-render.check-scale-out"}]
REN = E + "scale_out/render/api_router.py"
main_route("serving-render", "POST", "/v1/chat/completions/render", s(REN, 28, 51), "serving-render.render-chat-request", {"body": "= input.body"},
           "POST /v1/chat/completions/render: tokenize a chat request into a GenerateRequest", body="ServingChatCompletionRequest", pre=SO_GATE, load=False, cancel=False)
main_route("serving-render", "POST", "/v1/messages/render", s(REN, 54, 75), "serving-render.render-chat-request",
           {"body": "= {'model': has(input.body.model) ? input.body.model : '', 'messages': input.body.messages, 'max_tokens': input.body.max_tokens}"},
           "POST /v1/messages/render: tokenize an Anthropic Messages request", body=ANT_BODY, pre=SO_GATE, load=False, cancel=False)
main_route("serving-render", "POST", "/v1/completions/render", s(REN, 78, 98), "online-renderer.render-completion", {"body": "= input.body"},
           "POST /v1/completions/render: tokenize completion prompts", body="ServingCompletionRequest", pre=SO_GATE, load=False, cancel=False)
main_route("serving-render", "POST", "/v1/responses/render", s(REN, 101, 120), "online-renderer.render-responses", {"input": "= input.body.input"},
           "POST /v1/responses/render: tokenize a Responses request", body="ServingResponsesRequest", pre=SO_GATE, load=False, cancel=False)
DER = E + "scale_out/derender/api_router.py"
DER_BODY = obj({"model": {"type": "string", "examples": ["llama-8b"]},
                "generate_response": obj({"request_id": {"type": "string", "examples": ["generate-tokens-req-1"]},
                                          "token_ids": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "integer", "minimum": 1, "maximum": 128000}},
                                          "finish_reason": {"type": "string", "examples": ["stop"]}})})
main_route("serving-derender", "POST", "/v1/chat/completions/derender", s(DER, 31, 78), "serving-derender.derender", {"kind": "chat", "body": "= input.body"},
           "POST /v1/chat/completions/derender: a token-level generate response to a ChatCompletionResponse", body=DER_BODY, pre=SO_GATE, load=False, cancel=False)
main_route("serving-derender", "POST", "/v1/completions/derender", s(DER, 81, 126), "serving-derender.derender", {"kind": "completion", "body": "= input.body"},
           "POST /v1/completions/derender: a token-level generate response to a CompletionResponse", body=DER_BODY, pre=SO_GATE, load=False, cancel=False)
TIO = E + "scale_out/token_in_token_out/api_router.py"
main_route("serving-tokens", "POST", "/inference/v1/generate", s(TIO, 46, 73), "serving-tokens.serve-tokens", {"body": "= input.body", "x_request_id": XRID},
           "POST /inference/v1/generate: token ids in, token ids out",
           body=obj({"model": {"type": "string", "examples": ["llama-8b"]}, "token_ids": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "integer", "minimum": 1, "maximum": 128000}},
                     "sampling_params": obj({"max_tokens": {"type": "integer", "examples": [8]}})}), pre=SO_GATE)
ABORT_BODY = obj({"request_ids": {"type": ["array", "null"], "items": STR, "default": None}})
main_route("serving-tokens", "POST", "/inference/v1/abort_requests", s(TIO, 76, 102), "serving-tokens.abort-requests", {"body": "= input.body"},
           "POST /inference/v1/abort_requests: abort by id (guarded by --api-key)", body=ABORT_BODY, pre=SO_GATE, load=False, cancel=False,
           extra_errors=[{"code": "Bad Request", "status": 400, "reachable_by": "serving-tokens.abort-requests raises HTTPException 400 for a missing request_ids (vllm/entrypoints/scale_out/token_in_token_out/api_router.py:89-94)"}])
main_route("serving-tokens", "POST", "/abort_requests", s(TIO, 104, 111), "serving-tokens.abort-requests", {"body": "= input.body"},
           "POST /abort_requests: the unauthenticated legacy abort path, attached only with --tokens-only", body=ABORT_BODY, load=False, cancel=False,
           pre=[{"title": "Only --tokens-only attaches the legacy path", "source": s(TIO, 107, 111), "if": "!config['tokens-only']",
                 "then": [{"fail": {"code": "Not Found", "status": 404, "message": "Not Found"}}]}],
           extra_errors=[{"code": "Bad Request", "status": 400, "reachable_by": "serving-tokens.abort-requests raises HTTPException 400 for a missing request_ids (vllm/entrypoints/scale_out/token_in_token_out/api_router.py:89-94)"}])

# Contracts: where engine-core's fragment defines the interface, copy its request, response, kind and
# errors (BRIEF "Contracts" rule 2), inlining its schema refs and keeping our fake-data examples.
ec_schemas, ec_ifaces = {}, {}
for owner_frag in ("engine-core", "config-platform"):
    fp = os.path.join(ROOT, "fragments", owner_frag + ".yaml")
    if not os.path.exists(fp):
        continue
    ec = yaml.safe_load(open(fp, encoding="utf-8"))
    ec_schemas.update({sc["id"]: sc["schema"] for sc in ec.get("schemas") or []})
    for i in ec.get("interfaces") or []:
        if (i.get("attributes") or {}).get("boundary"):
            continue  # only the owner's own definition is the contract
        ec_ifaces[(owner_frag, i.get("id") or f"{i['component']}.{i['name']}")] = i
if ec_ifaces:

    def inline(v):
        if isinstance(v, dict):
            if set(v) == {"$ref"} and v["$ref"] in ec_schemas:
                return inline(ec_schemas[v["$ref"]])
            return {k: inline(x) for k, x in v.items()}
        if isinstance(v, list):
            return [inline(x) for x in v]
        if isinstance(v, str) and v in ec_schemas:
            return inline(ec_schemas[v])
        return v

    def overlay(owner, mine):
        """owner's shape, with our examples/defaults/bounds where the owner has none"""
        if not isinstance(owner, dict) or not isinstance(mine, dict):
            return owner
        out = dict(owner)
        for k in ("examples", "default", "minItems", "maxItems", "minimum", "maximum"):
            if k in mine and k not in owner:
                out[k] = mine[k]
        if "properties" in owner and "properties" in mine:
            out["properties"] = {k: overlay(v, mine["properties"].get(k)) for k, v in owner["properties"].items()}
        if "items" in owner and "items" in mine:
            out["items"] = overlay(owner["items"], mine["items"])
        return out

    for i in ifaces:
        key = (i.get("attributes", {}).get("owner"), f"{i['component']}.{i['name']}")
        if not i.get("attributes", {}).get("boundary") or key not in ec_ifaces:
            continue
        o = ec_ifaces[key]
        i["kind"] = o.get("kind", i.get("kind"))
        for f in ("request", "response"):
            if o.get(f) is None:
                pass  # the owner declares none: keep the shape our call site reads
            elif o[f] == "EngineCoreRequest":
                i[f] = "EngineCoreRequest"
            else:
                i[f] = overlay(inline(o[f]), i.get(f) if isinstance(i.get(f), dict) else {})
        if o.get("errors"):
            i["errors"] = o["errors"]
        else:
            i.pop("errors", None)
        i["summary"] = i["summary"] + f" (contract copied from {i['attributes']['owner']}'s fragment)"

# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
fixtures = [{"id": "serving-api-seed", "summary": "serving-api's own starting state: a generate model's app state, no stored responses, no LoRA adapters.",
             "state": {"app-state": {"supported_tasks": ["generate"], "initialized": True},
                       "openai-serving-models": {"lora_requests": {}, "lora_id_counter": 0},
                       "openai-serving-responses": {"response_store": {}, "msg_store": {}, "background_tasks": {}, "seq": 0}}}]
doc = {
    "schema_version": 1, "id": "vllm",
    "configs": configs, "fixtures": fixtures, "schemas": schemas, "components": comps, "interfaces": ifaces,
    "flows": flows, "scenarios": scenarios,
}


class D(yaml.SafeDumper):
    pass


def str_rep(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


D.add_representer(str, str_rep)
out = os.path.join(ROOT, "fragments", "serving-api.yaml")
with open(out, "w", encoding="utf-8") as f:
    f.write("# serving-api fragment of the vLLM v0.32.0 ontology. Generated by gen/serving-api/build.py from\n")
    f.write("# gen/serving-api/core.yaml plus the repetitive routes, delegations and boundary stubs in build.py.\n")
    yaml.dump(doc, f, Dumper=D, sort_keys=False, allow_unicode=True, width=180)

# skips
inv = json.load(open(os.path.join(ROOT, "inventory.json")))
skip_rules = json.load(open(os.path.join(HERE, "skips.json")))
out_skips = []
for e in inv["entries"]:
    if e.get("area") != "serving-api":
        continue
    key = f"{e['kind']}|{e['name']}|{e['file']}|{e['line']}"
    if key in skip_rules:
        rec = {"kind": e["kind"], "name": e["name"], "file": e["file"], "line": e["line"], "reason": skip_rules[key]["reason"]}
        if skip_rules[key].get("covered_by"):
            rec["covered_by"] = skip_rules[key]["covered_by"]
        out_skips.append(rec)
missing = set(skip_rules) - {f"{r['kind']}|{r['name']}|{r['file']}|{r['line']}" for r in out_skips}
if missing:
    sys.exit(f"skip rules naming no inventory entry: {sorted(missing)}")
with open(os.path.join(ROOT, "skips", "serving-api.json"), "w", encoding="utf-8") as f:
    json.dump(out_skips, f, indent=1, ensure_ascii=False)
    f.write("\n")
print(f"wrote {out}: {len(comps)} components, {len(ifaces)} interfaces, {len(flows)} flows, {len(scenarios)} scenarios; {len(out_skips)} skips")

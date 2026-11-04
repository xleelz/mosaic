"""Boundary stubs for the engine-core fragment: interfaces other areas own.

Shapes follow the brief's shared shapes (no owner fragment existed when this was written).
Single `examples` keep the stubs' fake answers deterministic in isolation; the owners'
definitions replace them at merge.
"""

SCHED = "scheduler-kv"
WORKER = "worker-runner"


def stub(component, name, owner, src, request=None, response=None, kind="function", summary=None, errors=None):
    d = {
        "component": component,
        "name": name,
        "kind": kind,
        "summary": summary or f"{name} (boundary stub; owner {owner})",
        "sources": [src],
        "attributes": {"boundary": True, "owner": owner},
        "request": request or {"type": "object"},
    }
    if response is not None:
        d["response"] = response
    if errors:
        d["errors"] = errors
    return d


# The first and second internal ids a run assigns to the canonical request id
# (input-processor.assign-request-id numbers them 00000001, 00000002, ...).
OUTPUT_EXAMPLE = [
    {"request_id": "chatcmpl-abc123-00000001", "new_token_ids": [9906], "finish_reason": "length", "stop_reason": None},
    {"request_id": "chatcmpl-abc123-00000002", "new_token_ids": [9906], "finish_reason": "length", "stop_reason": None},
    {"request_id": "0_chatcmpl-abc123-00000001", "new_token_ids": [9906], "finish_reason": "length", "stop_reason": None},
    {"request_id": "1_chatcmpl-abc123-00000001", "new_token_ids": [9906], "finish_reason": "length", "stop_reason": None},
]

import copy
import json
import os

# Contracts copied from fragments/scheduler-kv.yaml (the owner's fragment), extracted to
# owner_contracts.json. Named schemas the owner defines (SchedKvRequest,
# SchedKvEngineCoreOutputs) are inlined, since only the owner defines them. The only
# additions are `examples` that keep the stubs' fake answers deterministic in isolation,
# and request_ids accepting null on finish-requests (EngineCore passes None = all).
_C = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "owner_contracts.json")))
_I = _C["ifaces"]


def _owner(name, src, summary, request=None, response=None):
    c = _I[name]
    d = stub("scheduler", name, SCHED, src, request=copy.deepcopy(request if request is not None else c["request"]),
             response=copy.deepcopy(response if response is not None else c["response"]), kind=c["kind"], summary=summary,
             errors=c["errors"])
    return d


_UPD = copy.deepcopy(_C["SchedKvEngineCoreOutputs"])
_UPD["properties"]["outputs"]["examples"] = [OUTPUT_EXAMPLE]
_UPD["properties"]["finished_req_ids"]["examples"] = [[]]
_SCHED_RESP = {"allOf": [{"$ref": "SchedulerOutput"}, {"type": "object", "properties": {"total_num_scheduled_tokens": {"type": "integer", "examples": [16]}}}]}
_FIN_RESP = copy.deepcopy(_I["finish-requests"]["response"])
_FIN_RESP["properties"]["finished"]["examples"] = [["chatcmpl-abc123-00000001"]]
_RP_RESP = copy.deepcopy(_I["reset-prefix-cache"]["response"])
_RP_RESP["properties"]["reset"]["examples"] = [True]

STUBS = [
    _owner("add-request", "vllm/v1/core/sched/scheduler.py:2616", "Queue a new Request as WAITING (owner scheduler-kv).",
           request=_C["SchedKvRequest"]),
    _owner("finish-requests", "vllm/v1/core/sched/scheduler.py:2649",
           "Finish requests (all when request_ids is None) with a status; returns the ids it finished (owner scheduler-kv).",
           response=_FIN_RESP),
    _owner("has-requests", "vllm/v1/core/sched/scheduler.py:2823",
           "Whether any request is unfinished or finished-but-not-yet-removed (owner scheduler-kv)."),
    _owner("schedule", "vllm/v1/core/sched/scheduler.py:591", "One scheduling step: which requests run and how many tokens each (owner scheduler-kv).",
           response=_SCHED_RESP),
    _owner("update-from-output", "vllm/v1/core/sched/scheduler.py:2026",
           "Apply the model output to request state; returns the client's EngineCoreOutputs (owner scheduler-kv).", response=_UPD),
    _owner("set-pause-state", "vllm/v1/core/sched/scheduler.py:2755", "Set the scheduler's pause state (owner scheduler-kv)."),
    _owner("pause-state", "vllm/v1/core/sched/scheduler.py:2752", "The scheduler's pause state (owner scheduler-kv)."),
    _owner("reset-prefix-cache", "vllm/v1/core/sched/scheduler.py:2840", "Reset the prefix cache (owner scheduler-kv).", response=_RP_RESP),
    _owner("reset-encoder-cache", "vllm/v1/core/sched/scheduler.py:2907", "Reset the encoder cache manager (owner scheduler-kv)."),
    _owner("shutdown", "vllm/v1/core/sched/scheduler.py:2980", "Shut the scheduler down (owner scheduler-kv)."),
    _owner("update-draft-token-ids", "vllm/v1/core/sched/scheduler.py:2550",
           "Sync speculative decoding: store the drafter's new draft tokens on the decoding requests (owner scheduler-kv)."),
]
_K = _I["kv:get-kv-cache-configs"]
STUBS.append(stub("kv-cache-utils", "get-kv-cache-configs", SCHED, "vllm/v1/core/kv_cache_utils.py:2531",
                  request=_K["request"], response=_K["response"], kind=_K["kind"], errors=_K["errors"],
                  summary="Size the KV cache pool from the profiled free memory (owner scheduler-kv)."))
_O = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "owner_outlines.json")))
STUBS.append(stub("backend-outlines", "validate-structured-output-request-outlines", SCHED, "vllm/v1/structured_output/backend_outlines.py:195-238",
                  request=_O["request"], response=_O["response"], kind=_O["kind"], errors=_O["errors"],
                  summary="Validate a request's structured outputs for the outlines backend; every regex must be buildable (owner scheduler-kv)."))
BOUNDARY_COMPONENTS = [
    {"id": "structured-output-manager", "name": "StructuredOutputManager", "kind": "module", "parent": "engine-core", "layer": "structured-output",
     "summary": "Creates grammars for structured-output requests (owned by scheduler-kv).", "sources": ["vllm/v1/structured_output/__init__.py:47"],
     "attributes": {"boundary": True, "owner": SCHED}},
    {"id": "backend-outlines", "name": "backend_outlines (OutlinesBackend)", "kind": "module", "parent": "structured-output-manager",
     "summary": "Outlines structured-output backend (owned by scheduler-kv).", "sources": ["vllm/v1/structured_output/backend_outlines.py:39"],
     "attributes": {"boundary": True, "owner": SCHED}},
]
for cid in ("kv-cache-manager", "kv-cache-utils"):
    c = {k: v for k, v in _C["components"][cid].items() if v is not None}
    c["sources"] = ["vllm/v1/core/kv_cache_manager.py:1"] if cid == "kv-cache-manager" else ["vllm/v1/core/kv_cache_utils.py:2531"]
    c["attributes"] = {"boundary": True, "owner": SCHED}
    BOUNDARY_COMPONENTS.append(c)

MRO = {"$ref": "ModelRunnerOutput"}
WORKER_METHODS = [
    # name, source, request, response
    ("execute-model", "vllm/v1/worker/gpu_worker.py:1302", {"$ref": "SchedulerOutput"}, MRO),
    ("sample-tokens", "vllm/v1/worker/gpu_worker.py:1295", {"type": "object", "properties": {"grammar_output": {"type": ["object", "null"]}}}, MRO),
    ("execute-dummy-batch", "vllm/v1/worker/gpu_worker.py:1431", None, {"type": "object"}),
    ("take-draft-token-ids", "vllm/v1/worker/gpu_worker.py:1362", None, {"type": ["object", "null"]}),
    ("sleep", "vllm/v1/worker/gpu_worker.py:294", {"type": "object", "properties": {"level": {"type": "integer", "default": 1}}}, {"type": "object"}),
    ("wake-up", "vllm/v1/worker/gpu_worker.py:332", {"type": "object", "properties": {"tags": {"type": ["array", "null"], "items": {"type": "string"}}}}, {"type": "object"}),
    ("discard", "vllm/v1/worker/gpu_worker.py:358", {"type": "object", "properties": {"tags": {"type": "array", "items": {"type": "string"}}}}, {"type": "object"}),
    ("profile", "vllm/v1/worker/gpu_worker.py:1365", {"type": "object", "properties": {"is_start": {"type": "boolean"}, "profile_prefix": {"type": ["string", "null"]}}}, {"type": "object"}),
    ("add-lora", "vllm/v1/worker/gpu_worker.py:1439", {"type": "object", "properties": {"lora_request": {"type": "object"}}}, {"type": "boolean", "examples": [True]}),
    ("remove-lora", "vllm/v1/worker/gpu_worker.py:1442", {"type": "object", "properties": {"lora_id": {"type": "integer"}}}, {"type": "boolean", "examples": [True]}),
    ("pin-lora", "vllm/v1/worker/gpu_worker.py:1448", {"type": "object", "properties": {"lora_id": {"type": "integer"}}}, {"type": "boolean", "examples": [True]}),
    ("list-loras", "vllm/v1/worker/gpu_worker.py:1445", None, {"type": "array", "items": {"type": "integer"}, "examples": [[1]]}),
    ("reset-mm-cache", "vllm/v1/worker/worker_base.py:141", None, {"type": "object"}),
    ("reset-encoder-cache", "vllm/v1/worker/gpu_worker.py:1126", None, {"type": "object"}),
    ("save-sharded-state", "vllm/v1/worker/gpu_worker.py:1455", {"type": "object", "properties": {"path": {"type": "string"}}}, {"type": "object"}),
    ("determine-available-memory", "vllm/v1/worker/gpu_worker.py:634", None, {"type": "integer", "examples": [58000000000]}),
    ("get-kv-cache-spec", "vllm/v1/worker/gpu_worker.py:837", None, {"type": "object"}),
    ("initialize-from-config", "vllm/v1/worker/gpu_worker.py:853", {"type": "object", "properties": {"num_gpu_blocks": {"type": "integer"}}}, {"type": "object"}),
    ("compile-or-warm-up-model", "vllm/v1/worker/gpu_worker.py:908", None, {"type": "object"}),
    ("get-supported-tasks", "vllm/v1/worker/gpu_worker.py:1168", None, {"type": "array", "items": {"type": "string"}, "examples": [["generate"]]}),
    ("synchronize-device", "vllm/v1/worker/worker_base.py:129", None, {"type": "object"}),
    ("compute-weight-checksums", "vllm/v1/worker/gpu_worker.py:375", None, {"type": "object"}),
    ("init-device", "vllm/v1/worker/worker_base.py:135", None, {"type": "object"}),
    ("load-model", "vllm/v1/worker/gpu_worker.py:587", None, {"type": "object"}),
    ("shutdown", "vllm/v1/worker/worker_base.py:214", None, {"type": "object"}),
    ("handle-ft-command", "vllm/v1/worker/gpu_worker.py:581", {"type": "object"}, {"type": "object"}),
    ("checkpoint-prepare", "vllm/v1/worker/gpu_worker.py:361", None, {"type": "object"}),
    ("checkpoint-restore", "vllm/v1/worker/gpu_worker.py:364", None, {"type": "object"}),
    ("init-weight-transfer-engine", "vllm/v1/worker/gpu_worker.py:1484", {"type": "object", "properties": {"init_info": {"type": "object"}}}, {"type": "object"}),
    ("shutdown-weight-transfer-engine", "vllm/v1/worker/gpu_worker.py:1498", None, {"type": "object"}),
    ("start-weight-update", "vllm/v1/worker/gpu_worker.py:1507", None, {"type": "object"}),
    ("start-draft-weight-update", "vllm/v1/worker/gpu_worker.py:1517", None, {"type": "object"}),
    ("update-weights", "vllm/v1/worker/gpu_worker.py:1550", {"type": "object", "properties": {"update_info": {"type": "object"}}}, {"type": "object"}),
    ("finish-weight-update", "vllm/v1/worker/gpu_worker.py:1587", None, {"type": "object"}),
    ("apply-model", "vllm/v1/worker/worker_base.py:160", {"type": "object"}, {"type": "object"}),
]

# worker-runner's fragment exists: its request/response/kind/errors win (owner_worker_contracts.json);
# `examples` are added where a fake answer must be deterministic in isolation.
_W = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "owner_worker_contracts.json")))
_EX = {"add-lora": ("added", True), "remove-lora": ("removed", True), "pin-lora": ("pinned", True),
       "list-loras": ("lora_ids", [1]), "get-supported-tasks": ("tasks", ["generate"])}
for name, src, req, resp in WORKER_METHODS:
    kind, errors = "rpc", None
    if name in _W:
        c = copy.deepcopy(_W[name])
        req, resp, kind, errors = c["request"], c["response"], c["kind"], c["errors"]
        if name in _EX:
            field, ex = _EX[name]
            resp["properties"][field]["examples"] = [ex]
    STUBS.append(stub("gpu-worker-impl", name, WORKER, src, request=req, response=resp, kind=kind, errors=errors,
                      summary=f"Worker.{name.replace('-', '_')} on one rank, reached by collective_rpc (owner worker-runner)."))

WORKER_TARGETS = [f"gpu-worker-impl.{n}" for n, *_ in WORKER_METHODS]

# Structured-output contracts copied from fragments/scheduler-kv.yaml (owner_structured.json):
# grammar_init from preprocess_add_request, validate_xgrammar_grammar from SamplingParams.verify.
_S = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "owner_structured.json")))
for _key, _summary in (("structured-output-manager.grammar-init", "StructuredOutputManager.grammar_init: start compiling the request's grammar (owner scheduler-kv)."),
                       ("xgrammar-backend.validate-xgrammar-grammar", "validate_xgrammar_grammar: request validation for the xgrammar backend (owner scheduler-kv)."),
                       ("scheduler.get-grammar-bitmask", "Scheduler.get_grammar_bitmask: the step's GrammarOutput, or None without structured-output rows (owner scheduler-kv).")):
    _c = copy.deepcopy(_S[_key])
    if _key == "scheduler.get-grammar-bitmask":
        _c["response"]["examples"] = [None]  # in isolation: no structured-output rows to mask
    _comp, _name = _key.split(".", 1)
    STUBS.append(stub(_comp, _name, SCHED, _c["sources"][0], request=_c["request"], response=_c["response"], kind=_c["kind"],
                      errors=_c["errors"], summary=_summary))
_XC = {k: v for k, v in _S["components"]["xgrammar-backend"].items() if v is not None}
_XC["attributes"] = {"boundary": True, "owner": SCHED}
BOUNDARY_COMPONENTS.append(_XC)

# Multimodal processor caches copied from fragments/models-layers.yaml (owner_mm.json): the P1 receiver
# cache EngineCore uses on add-request and reset_mm_cache, and the P0 sender cache AsyncLLM clears.
_M = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "owner_mm.json")))
for _key in ("lru-key-replicated-receiver-cache.get-and-update-features", "lru-key-replicated-receiver-cache.clear-cache",
             "lru-key-replicated-sender-cache.clear-cache", "lru-key-replicated-sender-cache.invalidate"):
    _c = copy.deepcopy(_M[_key])
    _comp, _name = _key.split(".", 1)
    STUBS.append(stub(_comp, _name, "models-layers", _c["sources"][0], request=_c["request"], response=_c["response"],
                      kind=_c["kind"], errors=_c["errors"], summary=f"{_key} (owner models-layers)"))
for _cid in ("lru-key-replicated-receiver-cache", "lru-key-replicated-sender-cache"):
    _cc = {k: v for k, v in _M["components"][_cid].items() if v is not None}
    _cc["attributes"] = {"boundary": True, "owner": "models-layers"}
    BOUNDARY_COMPONENTS.append(_cc)

# Round 5: contracts copied by owner5.py into owner5.json (owner fragment named per entry).
_R5 = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "owner5.json")))
for _key, _c in sorted(_R5["ifaces"].items()):
    _comp, _name = _key.split(".", 1)
    _own = (_c.get("attributes") or {}).get("owner") or _c["owner"]
    _s = stub(_comp, _name, _own, _c["sources"][0], request=copy.deepcopy(_c["request"]),
              response=copy.deepcopy(_c["response"]), kind=_c["kind"], errors=_c["errors"],
              summary=_c["summary"] if _c.get("store") else f"{_c['summary']} (owner {_c['owner']})")
    if _c.get("store"):
        _s["store"] = copy.deepcopy(_c["store"])  # shared infrastructure: the same store as every copy
    STUBS.append(_s)
_HAVE = {c["id"] for c in BOUNDARY_COMPONENTS}
for _cid, _cc in sorted(_R5["components"].items()):
    if _cid in _HAVE:
        continue
    _d = {k: v for k, v in _cc.items() if v is not None and k != "owner"}
    _d["attributes"] = {"boundary": True, "owner": _cc["owner"]}
    BOUNDARY_COMPONENTS.append(_d)

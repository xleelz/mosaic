#!/usr/bin/env python3
"""Assemble examples/vllm/fragments/engine-core.yaml from parts/*.yaml plus generated
boundary stubs and the thin AsyncLLM/LLMEngine utility delegators.

Run: python3 examples/vllm/gen/engine-core/build.py
"""
import glob
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stubs import BOUNDARY_COMPONENTS, STUBS, WORKER_TARGETS  # noqa: E402

OUT = os.path.normpath(os.path.join(HERE, "..", "..", "fragments", "engine-core.yaml"))
KINDS = ["configs", "schemas", "components", "interfaces", "flows", "fixtures", "scenarios"]

# (component, name, source, utility method, args template, request schema, summary, result expr)
A = "vllm/v1/engine/async_llm.py"
L = "vllm/v1/engine/llm_engine.py"
DELEGATES = [
    ("async-llm", "reset-mm-cache", f"{A}:1137-1142", "reset_mm_cache", {}, None, "Clear the frontend multimodal cache, then the engine's.", None),
    ("async-llm", "reset-prefix-cache", f"{A}:1144-1149", "reset_prefix_cache",
     {"reset_running_requests": "= has(input.reset_running_requests) ? input.reset_running_requests : false", "reset_connector": "= has(input.reset_connector) ? input.reset_connector : false"},
     {"type": "object", "properties": {"reset_running_requests": {"type": "boolean", "default": False}, "reset_connector": {"type": "boolean", "default": False}}},
     "Reset the prefix cache on every engine (call_utility_all_async); true only if all succeeded.", None),
    ("async-llm", "reset-encoder-cache", f"{A}:1151-1152", "reset_encoder_cache", {}, None, None, None),
    ("async-llm", "resume-generation", f"{A}:986-988", "resume_scheduler", {}, None, "Resume scheduling after pause_generation.", None),
    ("async-llm", "is-paused", f"{A}:990-992", "is_scheduler_paused", {}, None, "Whether the engine scheduler is in any pause state (consensus across engines).", None),
    ("async-llm", "is-sleeping", f"{A}:1183-1184", "is_sleeping", {}, None, None, None),
    ("async-llm", "compute-weight-checksums", f"{A}:1186-1187", "compute_weight_checksums", {}, None, None, None),
    ("async-llm", "add-lora", f"{A}:1189-1191", "add_lora", {"lora_request": "= input.lora_request"},
     {"type": "object", "properties": {"lora_request": {"type": "object", "properties": {"lora_name": {"type": "string", "examples": ["sql-adapter"]}, "lora_int_id": {"type": "integer", "examples": [1]}, "lora_path": {"type": "string", "examples": ["/models/lora/sql-adapter"]}}}}},
     "Load a LoRA adapter into the engine for future requests.", None),
    ("async-llm", "remove-lora", f"{A}:1193-1195", "remove_lora", {"lora_id": "= input.lora_id"},
     {"type": "object", "properties": {"lora_id": {"type": "integer", "examples": [1]}}}, None, None),
    ("async-llm", "list-loras", f"{A}:1197-1199", "list_loras", {}, None, None, None),
    ("async-llm", "pin-lora", f"{A}:1201-1203", "pin_lora", {"lora_id": "= input.lora_id"},
     {"type": "object", "properties": {"lora_id": {"type": "integer", "examples": [1]}}}, None, None),
    ("async-llm", "collective-rpc", f"{A}:1205-1215", "collective_rpc", {"method": "= input.method", "args": "= has(input.args) ? input.args : {}"},
     {"type": "object", "properties": {"method": {"type": "string", "examples": ["compute_weight_checksums"]}, "args": {"type": "object"}}}, None, None),
    ("async-llm", "checkpoint-prepare", f"{A}:1177-1178", "collective_rpc", {"method": "checkpoint_prepare"}, None, None, None),
    ("async-llm", "checkpoint-restore", f"{A}:1180-1181", "collective_rpc", {"method": "checkpoint_restore"}, None, None, None),
    ("async-llm", "init-weight-transfer-engine", f"{A}:1315-1326", "collective_rpc", {"method": "init_weight_transfer_engine", "args": {"init_info": "= has(input.init_info) ? input.init_info : {}"}},
     {"type": "object", "properties": {"init_info": {"type": "object"}}}, "Initialize weight transfer for RL training on every worker.", None),
    ("async-llm", "shutdown-weight-transfer-engine", f"{A}:1328-1330", "collective_rpc", {"method": "shutdown_weight_transfer_engine"}, None, None, None),
    ("async-llm", "start-weight-update", f"{A}:1332-1334", "collective_rpc", {"method": "start_weight_update"}, None, None, None),
    ("async-llm", "start-draft-weight-update", f"{A}:1336-1338", "collective_rpc", {"method": "start_draft_weight_update"}, None, None, None),
    ("async-llm", "update-weights", f"{A}:1340-1349", "collective_rpc", {"method": "update_weights", "args": {"update_info": "= has(input.update_info) ? input.update_info : {}"}},
     {"type": "object", "properties": {"update_info": {"type": "object"}}}, None, None),
    ("async-llm", "update-weight-version", f"{A}:1357-1359", "set_weight_version", {"weight_version": "= input.new_version"},
     {"type": "object", "properties": {"new_version": {"type": "string", "examples": ["step-200"]}}}, "Set the weight version without updating weights.", None),
    ("async-llm", "get-weight-version", f"{A}:1361-1363", "get_weight_version", {}, None, "The latest committed weight version.", "= vars.r.value.weight_version"),
    ("llm-engine", "reset-mm-cache", f"{L}:396-401", "reset_mm_cache", {}, None, None, None),
    ("llm-engine", "reset-prefix-cache", f"{L}:403-408", "reset_prefix_cache",
     {"reset_running_requests": "= has(input.reset_running_requests) ? input.reset_running_requests : false", "reset_connector": "= has(input.reset_connector) ? input.reset_connector : false"},
     {"type": "object", "properties": {"reset_running_requests": {"type": "boolean", "default": False}, "reset_connector": {"type": "boolean", "default": False}}}, None, None),
    ("llm-engine", "reset-encoder-cache", f"{L}:410-416", "reset_encoder_cache", {}, None, None, None),
    ("llm-engine", "is-sleeping", f"{L}:441-442", "is_sleeping", {}, None, None, None),
    ("llm-engine", "add-lora", f"{L}:469-471", "add_lora", {"lora_request": "= input.lora_request"},
     {"type": "object", "properties": {"lora_request": {"type": "object", "properties": {"lora_name": {"type": "string", "examples": ["sql-adapter"]}, "lora_int_id": {"type": "integer", "examples": [1]}, "lora_path": {"type": "string", "examples": ["/models/lora/sql-adapter"]}}}}}, None, None),
    ("llm-engine", "remove-lora", f"{L}:473-475", "remove_lora", {"lora_id": "= input.lora_id"}, {"type": "object", "properties": {"lora_id": {"type": "integer", "examples": [1]}}}, None, None),
    ("llm-engine", "list-loras", f"{L}:477-479", "list_loras", {}, None, None, None),
    ("llm-engine", "pin-lora", f"{L}:481-483", "pin_lora", {"lora_id": "= input.lora_id"}, {"type": "object", "properties": {"lora_id": {"type": "integer", "examples": [1]}}}, None, None),
    ("llm-engine", "collective-rpc", f"{L}:485-492", "collective_rpc", {"method": "= input.method", "args": "= has(input.args) ? input.args : {}"},
     {"type": "object", "properties": {"method": {"type": "string", "examples": ["compute_weight_checksums"]}, "args": {"type": "object"}}}, None, None),
    ("llm-engine", "set-weight-version", f"{L}:494-495", "set_weight_version", {"weight_version": "= input.weight_version"},
     {"type": "object", "properties": {"weight_version": {"type": "string", "examples": ["step-100"]}}}, None, None),
    ("llm-engine", "get-weight-version", f"{L}:497-499", "get_weight_version", {}, None, None, "= vars.r.value.weight_version"),
    ("llm-engine", "apply-model", f"{L}:501-502", "collective_rpc", {"method": "apply_model"}, None, "Run a function on every worker's model (collective_rpc('apply_model')).", None),
]


ALL = {"reset_prefix_cache": "= vars.r.value.all(x, x == true)",
       "compute_weight_checksums": "= vars.r.value.map(x, x).flatten()"}
CONSENSUS = {"is_sleeping", "is_scheduler_paused", "get_weight_version"}


def delegate(comp, name, src, method, args, req, summary, result):
    client = "async-mp-client.call-utility-async" if comp == "async-llm" else "sync-mp-client.call-utility"
    if comp == "async-llm" and (method in ALL or method in CONSENSUS):
        client = "async-mp-client.call-utility-all-async"
        if method in ALL:
            result = ALL[method]
        else:
            result = "= vars.r.value[0].weight_version" if method == "get_weight_version" else "= vars.r.value[0]"
    cls = "AsyncLLM" if comp == "async-llm" else "LLMEngine"
    d = {
        "component": comp,
        "name": name,
        "kind": "function",
        "summary": summary or f"{cls}.{name.replace('-', '_')}: a '{method}' utility call to the engine core.",
        "sources": [src],
    }
    if req:
        d["request"] = req
    d["behavior"] = [
        {"call": client, "input": {"method": method, "args": args}, "as": "r"},
    ]
    if comp == "async-llm" and method == "reset_mm_cache":
        d["behavior"].insert(0, {"title": "renderer.clear_mm_cache_async(): clear the P0 sender cache first",
                                 "source": "vllm/v1/engine/async_llm.py:1137-1142",
                                 "call": "lru-key-replicated-sender-cache.clear-cache"})
    if client == "async-mp-client.call-utility-all-async" and method in CONSENSUS:
        d["behavior"].append({"title": "call_utility_consensus_async: every engine must return the same answer",
                              "source": "vllm/v1/engine/core_client.py:1271-1277",
                              "if": "vars.r.value.exists(x, x != vars.r.value[0])",
                              "then": [{"fail": {"code": "runtime-error", "message": f"= 'Engines returned different {method} results: [' + vars.r.value.map(x, type(x) == bool ? (x ? 'True' : 'False') : (type(x) == string ? \"'\" + x + \"'\" : string(x))).join(', ') + ']'"}}]})
    d["behavior"].append({"return": result or "= vars.r.value"})
    return d


def main():
    doc = {"schema_version": 1, "id": "vllm"}
    lists = {k: [] for k in KINDS}
    for path in sorted(glob.glob(os.path.join(HERE, "parts", "*.yaml"))):
        with open(path) as f:
            part = fix_on(yaml.safe_load(f) or {})
        for k in KINDS:
            lists[k].extend(part.get(k) or [])
    lists["interfaces"].extend(delegate(*d) for d in DELEGATES)
    lists["interfaces"].extend(STUBS)
    lists["components"].extend(BOUNDARY_COMPONENTS)
    for i in lists["interfaces"]:
        for step in walk(i.get("behavior") or []):
            if step.get("targets") == "__WORKER_TARGETS__":
                step["targets"] = WORKER_TARGETS
    seen = set()
    for i in lists["interfaces"]:
        key = (i["component"], i["name"])
        if key in seen:
            raise SystemExit(f"duplicate interface {key}")
        seen.add(key)
    for k in KINDS:
        if lists[k]:
            doc[k] = lists[k]
    header = (
        "# engine-core area fragment of the vLLM 0.32 ontology, built from code (v0.32.0, 5df63a7203).\n"
        "# Owns vllm/v1/engine/**, vllm/engine/** (except EngineArgs), vllm/v1/executor/**, vllm/v1/metrics/**,\n"
        "# vllm/v1/fault_tolerance/**, vllm/v1/request.py, vllm/v1/outputs.py, vllm/v1/serial_utils.py, vllm/v1/utils.py.\n"
        "# Generated by examples/vllm/gen/engine-core/build.py from gen/engine-core/parts; edit the parts, not this file.\n"
    )
    with open(OUT, "w") as f:
        f.write(header)
        yaml.safe_dump(doc, f, sort_keys=False, width=200, allow_unicode=True)
    print(f"wrote {OUT}: " + ", ".join(f"{len(lists[k])} {k}" for k in KINDS))


def fix_on(v):
    """PyYAML reads the key `on` as boolean True (YAML 1.1); mosaic wants the string."""
    if isinstance(v, dict):
        return {("on" if k is True else k): fix_on(x) for k, x in v.items()}
    if isinstance(v, list):
        return [fix_on(x) for x in v]
    return v


def walk(steps):
    for s in steps:
        if not isinstance(s, dict):
            continue
        yield s
        for key in ("then", "else", "steps", "on_error"):
            v = s.get(key)
            if isinstance(v, list):
                yield from walk(v)
        if isinstance(s.get("options"), dict):
            for v in s["options"].values():
                yield from walk(v)
        if isinstance(s.get("branches"), list):
            for b in s["branches"]:
                yield from walk(b)


if __name__ == "__main__":
    main()

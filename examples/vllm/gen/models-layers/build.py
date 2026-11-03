#!/usr/bin/env python3
"""Build examples/vllm/fragments/models-layers.yaml from the hand-written core-*.yaml files,
the registry tables parsed from vllm/model_executor/models/registry.py, and scenarios.py.

Usage: python3 -I build.py <vllm snapshot path> <examples/vllm dir>
"""
import ast
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SNAP = Path(sys.argv[1])
OUT = Path(sys.argv[2])
sys.path.insert(0, str(HERE))
import scenarios  # noqa: E402
import scenarios_r4  # noqa: E402

REG = "vllm/model_executor/models/registry.py"
TABLES = {
    "_TEXT_GENERATION_MODELS": "text_generation",
    "_EMBEDDING_MODELS": "embedding",
    "_LATE_INTERACTION_MODELS": "late_interaction",
    "_REWARD_MODELS": "reward",
    "_TOKEN_CLASSIFICATION_MODELS": "token_classification",
    "_SEQUENCE_CLASSIFICATION_MODELS": "sequence_classification",
    "_MULTIMODAL_MODELS": "multimodal",
    "_SPECULATIVE_DECODING_MODELS": "speculative_decoding",
    "_TRANSFORMERS_SUPPORTED_MODELS": "transformers_supported",
    "_TRANSFORMERS_BACKEND_MODELS": "transformers_backend",
}
POOLING_TABLES = {"embedding", "late_interaction", "reward", "token_classification", "sequence_classification"}
# Classes modeled in depth: the registry row points the loader at their component.
DEFAULTS_FILES = {"core-r4.yaml", "core-r4b.yaml", "core-r4c.yaml"}
DEFAULTS_IFACES = {"base-multi-modal-processor.apply", "base-multi-modal-processor.apply-hf-processor-main", "qkv-parallel-linear.weight-loader"}
MODELED = {("llama", "LlamaForCausalLM"): "llama-for-causal-lm", ("mixtral", "MixtralForCausalLM"): "mixtral-for-causal-lm"}


def parse_registry():
    tree = ast.parse((SNAP / REG).read_text())
    models, spans, prev, oot = {}, [], {}, {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name in TABLES:
            table = TABLES[name]
            spans.append((name, node.lineno, node.end_lineno))
            for k, v in zip(node.value.keys, node.value.values):
                if k is None:
                    continue
                arch = ast.literal_eval(k)
                mod, cls = ast.literal_eval(v)
                # _VLLM_MODELS merges the tables in order, so later tables override.
                row = {"module": mod, "class_name": cls, "table": table,
                       "is_pooling": table in POOLING_TABLES,
                       "is_text_generation": table in ("text_generation", "transformers_supported")}
                comp = MODELED.get((mod, cls))
                if comp:
                    row["component"] = comp
                models[arch] = row
        elif name == "_PREVIOUSLY_SUPPORTED_MODELS":
            prev = ast.literal_eval(node.value)
            spans.append((name, node.lineno, node.end_lineno))
        elif name == "_OOT_SUPPORTED_MODELS":
            oot = ast.literal_eval(node.value)
            spans.append((name, node.lineno, node.end_lineno))
    return models, spans, prev, oot



def cel_lit(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(cel_lit(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(json.dumps(k) + ": " + cel_lit(x) for k, x in v.items()) + "}"
    raise TypeError(v)


INPUT_RE = re.compile(r"(?<![A-Za-z0-9_.])input\.")


def with_defaults(iface):
    """Call inputs carry only the keys the caller sent; give behaviors the request schema's
    defaults by reading `vars.input` = defaults merged under the input."""
    props = (iface.get("request") or {}).get("properties") or {}
    defaults = {k: v["default"] for k, v in props.items() if isinstance(v, dict) and "default" in v}
    if not defaults or not iface.get("behavior"):
        return

    def sub(o):
        if isinstance(o, dict):
            return {k: (v if k in ("title", "detail", "source") else sub(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [sub(x) for x in o]
        if isinstance(o, str):
            return INPUT_RE.sub("vars.input.", o)
        return o
    iface["behavior"] = [{"set": {"vars.input": "= merge(" + cel_lit(defaults) + ", input)"}}] + sub(iface["behavior"])


def load(name):
    return yaml.safe_load((HERE / name).read_text())


GEMM = ("= (math.greatest((double(input.in_features) * double(input.out_features) * double(input.bytes_per_weight)"
        " + 2.0 * double(input.num_tokens) * double(input.in_features + input.out_features))"
        " / (double(config['gpu-hbm-bandwidth-gbps']) * 1000000.0),"
        " 2.0 * double(input.num_tokens) * double(input.in_features) * double(input.out_features)"
        " / (double(config['gpu-dense-bf16-tflops']) * {scale}1000000000.0)))")
MOE = ("= (math.greatest(double(math.least(input.num_experts, input.num_tokens * input.top_k))"
       " * double(input.k) * double(input.n) * double(input.bytes_per_weight)"
       " / (double(config['gpu-hbm-bandwidth-gbps']) * 1000000.0),"
       " 2.0 * double(input.num_tokens * input.top_k) * double(input.k) * double(input.n)"
       " / (double(config['gpu-dense-bf16-tflops']) * 1000000000.0)))")


def fill(obj):
    if isinstance(obj, dict):
        return {k: fill(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fill(v) for v in obj]
    if obj == "{{GEMM_LAT}}":
        return GEMM.format(scale="")
    if obj == "{{GEMM_LAT_FP8}}":
        return GEMM.format(scale="2.0 * ")
    if obj == "{{MOE_LAT}}":
        return MOE
    return obj


def main():
    models, spans, prev, oot = parse_registry()
    doc = {"schema_version": 1, "id": "vllm", "components": [], "interfaces": [], "schemas": [],
           "configs": [], "flows": [], "scenarios": [], "fixtures": []}
    for f in ["core-registry.yaml", "core-loader.yaml", "core-layers.yaml", "core-moe.yaml", "core-lora.yaml", "core-fix.yaml", "core-mm.yaml", "core-r3.yaml", "core-r4.yaml", "core-r4b.yaml", "core-r4c.yaml"]:
        part = load(f)
        for i in part.get("interfaces") or []:
            if f in DEFAULTS_FILES or (i["component"] + "." + i["name"]) in DEFAULTS_IFACES:
                with_defaults(i)
        for k in ("components", "interfaces"):
            doc[k].extend(part.get(k) or [])
    for c in doc["components"]:
        if c["id"] == "model-registry":
            c["state"]["initial"].update({"models": models, "previously_supported": prev, "oot_supported": oot})
            c["sources"] = c["sources"] + [f"{REG}:{lo}-{hi}" for _, lo, hi in spans]
            c["description"] = ("Registry tables cited in sources: " + ", ".join(n for n, _, _ in spans) +
                                f". {len(models)} architectures are seeded into state.models (module, class, table).")
    for i in doc["interfaces"]:
        i.pop("tags", None)
        if "latency_ms" not in i:
            i["latency_ms"] = 0  # in-process Python; the kernels below carry the time
    for extra in (scenarios.extra(), scenarios_r4.extra()):
        for k in ("components", "interfaces", "schemas", "configs", "flows", "scenarios", "fixtures"):
            doc[k].extend(extra.get(k) or [])
    doc = fill(doc)
    out = OUT / "fragments" / "models-layers.yaml"
    out.write_text("# Generated by examples/vllm/gen/models-layers/build.py; edit the generator, not this file.\n"
                   + yaml.safe_dump(doc, sort_keys=False, width=1000, allow_unicode=True))
    print(f"wrote {out}: {len(doc['components'])} components, {len(doc['interfaces'])} interfaces, "
          f"{len(doc['flows'])} flows, {len(doc['scenarios'])} scenarios, {len(models)} registry rows")


if __name__ == "__main__":
    main()

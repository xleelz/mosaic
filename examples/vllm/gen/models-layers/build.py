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
import scenarios_r5  # noqa: E402
import scenarios_r6  # noqa: E402

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
DEFAULTS_FILES = {"core-r4.yaml", "core-r4b.yaml", "core-r4c.yaml", "core-r5.yaml", "core-r6.yaml"}
DEFAULTS_IFACES = {"base-multi-modal-processor.apply", "base-multi-modal-processor.apply-hf-processor-main", "qkv-parallel-linear.weight-loader"}
MODELED = {("llama", "LlamaForCausalLM"): "llama-for-causal-lm", ("mixtral", "MixtralForCausalLM"): "mixtral-for-causal-lm",
           ("qwen2_vl", "Qwen2VLForConditionalGeneration"): "qwen2-vl-for-conditional-generation",
           ("qwen3_vl", "Qwen3VLForConditionalGeneration"): "qwen3-vl-for-conditional-generation",
           ("embedding_gemma2", "EmbeddingGemma2Model"): "embedding-gemma2-model",
           ("bert", "BertEmbeddingModel"): "bert-embedding-model", ("roberta", "RobertaEmbeddingModel"): "bert-embedding-model"}
MODELS_DIR = "vllm/model_executor/models"
_CLASSES = {}


def _module_classes(mod):
    """Class definitions of a model module: decorators (default_pooling_type, attn_type), class
    attributes, bases, and names imported from sibling modules."""
    if mod in _CLASSES:
        return _CLASSES[mod]
    path = SNAP / MODELS_DIR / (mod + ".py")
    out = {"classes": {}, "imports": {}, "assigns": set()}
    _CLASSES[mod] = out
    if not path.exists():
        return out
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            for a in node.names:
                out["imports"][a.asname or a.name] = node.module
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out["assigns"].add(node.targets[0].id)
        elif isinstance(node, ast.ClassDef):
            info = {"bases": [b.id for b in node.bases if isinstance(b, ast.Name)], "seq": None, "tok": None, "attn": None}
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Name):
                    if d.func.id == "default_pooling_type":
                        kw = {k.arg: ast.literal_eval(k.value) for k in d.keywords}
                        info["seq"], info["tok"] = kw.get("seq_pooling_type", "LAST"), kw.get("tok_pooling_type", "ALL")
                    elif d.func.id == "attn_type" and d.args:
                        info["attn"] = ast.literal_eval(d.args[0])
            for st in node.body:
                if isinstance(st, (ast.Assign, ast.AnnAssign)):
                    tgt = st.targets[0] if isinstance(st, ast.Assign) else st.target
                    if isinstance(tgt, ast.Name) and st.value is not None and isinstance(st.value, ast.Constant):
                        if tgt.id == "default_seq_pooling_type":
                            info["seq"] = st.value.value
                        elif tgt.id == "default_tok_pooling_type":
                            info["tok"] = st.value.value
                        elif tgt.id == "attn_type":
                            info["attn"] = st.value.value
            out["classes"][node.name] = info
    return out


def pooling_info(mod, cls, depth=0):
    """_ModelInfo.default_seq_pooling_type / default_tok_pooling_type / attn_type of a registered
    class: the class attribute the decorators set, inherited through the bases (interfaces_base.py:
    235-273); adapters (as_seq_cls_model, as_embedding_model) and undecorated classes keep the
    defaults LAST / ALL / decoder."""
    res = {"seq": None, "tok": None, "attn": None}
    if depth > 8:
        return res
    m = _module_classes(mod)
    info = m["classes"].get(cls)
    if info is None:
        if cls in m["imports"]:
            return pooling_info(m["imports"][cls], cls, depth + 1)
        return res
    res = {k: info[k] for k in res}
    for b in info["bases"]:
        if all(res[k] is not None for k in res):
            break
        bmod = mod if b in m["classes"] else m["imports"].get(b)
        if bmod is None:
            continue
        sub = pooling_info(bmod, b, depth + 1)
        for k in res:
            if res[k] is None:
                res[k] = sub[k]
    return res


def has_interface(mod, cls, marker, depth=0):
    """_ModelInfo.is_hybrid / is_attention_free: the class inherits the IsHybrid or IsAttentionFree
    interface (interfaces.py:909-941, registry.py:867-910), directly or through a base."""
    if depth > 8:
        return False
    m = _module_classes(mod)
    info = m["classes"].get(cls)
    if info is None:
        return cls in m["imports"] and has_interface(m["imports"][cls], cls, marker, depth + 1)
    if marker in info["bases"]:
        return True
    return any(has_interface(mod if b in m["classes"] else m["imports"][b], b, marker, depth + 1)
               for b in info["bases"] if b in m["classes"] or b in m["imports"])


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
                       "is_text_generation": table in ("text_generation", "transformers_supported", "multimodal")}
                pi = pooling_info(mod, cls)
                row["default_seq_pooling_type"] = pi["seq"] or "LAST"
                row["default_tok_pooling_type"] = pi["tok"] or "ALL"
                row["attn_type"] = pi["attn"] or "decoder"
                row["is_hybrid"] = has_interface(mod, cls, "IsHybrid")
                row["is_attention_free"] = has_interface(mod, cls, "IsAttentionFree")
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
    req = iface.get("request")
    if not isinstance(req, dict):
        return
    props = req.get("properties") or {}
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
    for f in ["core-registry.yaml", "core-loader.yaml", "core-layers.yaml", "core-moe.yaml", "core-lora.yaml", "core-fix.yaml", "core-mm.yaml", "core-r3.yaml", "core-r4.yaml", "core-r4b.yaml", "core-r4c.yaml", "core-r5.yaml", "core-r6.yaml"]:
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
    for extra in (scenarios.extra(), scenarios_r4.extra(), scenarios_r5.extra(), scenarios_r6.extra()):
        for k in ("components", "interfaces", "schemas", "configs", "flows", "scenarios", "fixtures"):
            doc[k].extend(extra.get(k) or [])
    scenarios_r5.patch(doc)
    scenarios_r6.patch(doc)
    doc = fill(doc)
    out = OUT / "fragments" / "models-layers.yaml"
    out.write_text("# Generated by examples/vllm/gen/models-layers/build.py; edit the generator, not this file.\n"
                   + yaml.safe_dump(doc, sort_keys=False, width=1000, allow_unicode=True))
    print(f"wrote {out}: {len(doc['components'])} components, {len(doc['interfaces'])} interfaces, "
          f"{len(doc['flows'])} flows, {len(doc['scenarios'])} scenarios, {len(models)} registry rows")


if __name__ == "__main__":
    main()

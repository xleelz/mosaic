"""Assemble examples/vllm/fragments/kernels-ops.yaml and skips/kernels-ops.json.

Run from anywhere: python3 -I examples/vllm/gen/kernels-ops/build.py
(reads the vLLM snapshot read-only)."""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml  # noqa: E402

import hand  # noqa: E402
import hand2  # noqa: E402
import hand3  # noqa: E402
import hand4  # noqa: E402
import ops  # noqa: E402
import scen  # noqa: E402
from common import HERE, findline  # noqa: E402

scen.SCENARIOS = scen.SCENARIOS + hand3.SCENARIOS + hand4.SCENARIOS

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

# ------------------------------------------------------------ interfaces
ifaces = {}
for iid, f in ops.OP_IFACES.items():
    ifaces[iid] = {k: v for k, v in f.items() if not k.startswith("_")}
for iid, f in ops.EXTRA_IFACES.items():
    ifaces[iid] = dict(f)

# op behaviors for host-side dispatch
for iid, extra in hand2.OP_BEHAVIORS.items():
    ifaces[iid].update(copy.deepcopy(extra))

# direct-registered Python ops dispatch to their registered impl function
wrappers_by_file_fn = {}
for iid, w in ops.WRAPPER_IFACES.items():
    e = w["_entry"]
    wrappers_by_file_fn[(e["file"], e["name"])] = iid

for iid, f in list(ifaces.items()):
    e = ops.OP_IFACES.get(iid, {}).get("_entry")
    if not e or e["via"] == "torch-library":
        continue
    impl = e.get("detail", "").replace("impl ", "").strip()
    w = wrappers_by_file_fn.get((e["file"], impl))
    if w and w != iid:
        ln = findline(e["file"], f"def {impl}(")
        f["behavior"] = [{"title": f"The registered op runs its Python impl {impl}", "source": f"{e['file']}:{ln}", "call": w, "input": "= input", "fill": True}]

# wrappers: generated, then hand-written overrides, keeping the inventory span as first source
for iid, w in ops.WRAPPER_IFACES.items():
    d = {k: v for k, v in w.items() if not k.startswith("_")}
    if iid in hand2.I:
        h = copy.deepcopy(hand2.I[iid])
        span = d["sources"][0]
        h["sources"] = [span] + [s for s in h.get("sources", []) if s != span]
        h.setdefault("kind", "function")
        d = h
    if d.get("behavior") is None:
        raise SystemExit(f"wrapper {iid} has no behavior (multi-op wrappers need hand2)")
    if iid in ifaces:
        # same id as a direct-registered op (safeFusedQuantizeNv): one interface for both
        op = ifaces[iid]
        op["behavior"] = d["behavior"]
        op["sources"] = d["sources"] + [s for s in op["sources"] if s not in d["sources"]]
        op["summary"] = d["summary"] + " (also the registered custom op)"
        continue
    ifaces[iid] = d

for iid, h in hand2.I.items():
    if iid not in ifaces:
        ifaces[iid] = copy.deepcopy(h)

# ------------------------------------------------------------ components
components = {c["id"]: c for c in hand.components()}
for f, (cid, name, desc) in ops.BINDING_COMPONENTS.items():
    if cid not in components:
        components[cid] = {"id": cid, "name": name, "kind": "module", "layer": "kernels", "parent": "compilation" if "compilation" in f else "kernels-ops",
                           "summary": desc, "sources": [f"{f}:1"], "attributes": {"owner": "kernels-ops"}}
for c in hand3.COMPONENTS:
    components[c["id"]] = c
for cid, init in hand3.COMPONENT_PATCHES.items():
    c = components[cid]
    st = c.setdefault("state", {"schema": {"type": "object", "properties": {}}, "initial": {}})
    for k, v in init.items():
        st["initial"][k] = v
        st["schema"]["properties"].setdefault(k, {"type": ["object", "array", "string", "boolean", "integer", "null"]} if v is None else
                                                  {"type": {bool: "boolean", str: "string", dict: "object", list: "array", int: "integer"}[type(v)]})
components["rms-norm-quant-fusion-pass"]["parent"] = "rms-quant-fusion"
components["all-reduce-fusion-pass"]["parent"] = "allreduce-rms-fusion"
for iid, f in ifaces.items():
    if f["component"] not in components:
        raise SystemExit(f"interface {iid}: unknown component {f['component']}")

# ------------------------------------------------------------ reachability and opcheck scenarios
def targets_of(steps):
    out = []
    def walk(v):
        if isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            c = v.get("call")
            if isinstance(c, str) and not c.startswith("="):
                out.append(c)
            out.extend(v.get("targets", []) or [])
            for k, x in v.items():
                if k not in ("input", "return", "set", "fail"):
                    walk(x)
    walk(steps)
    return out


def reach(starts):
    seen, q = set(), list(starts)
    while q:
        i = q.pop()
        if i in seen or i not in ifaces:
            continue
        seen.add(i)
        q.extend(targets_of(ifaces[i].get("behavior") or []))
    return seen


starts = [f["entry"]["interface"] for f in scen.FLOWS]
for s in scen.SCENARIOS:
    for st in s.get("steps", []) or []:
        if "interface" in st:
            starts.append(st["interface"])
reached = reach(starts)

# called-in-scenario wrappers come first; unreached ops follow
GROUPS = [
    ("custom-ops", "custom-ops"), ("cpu-triton-utils", "cpu-triton-utils"), ("xpu-ops", "xpu-ops"), ("aiter-ops", "aiter-ops"),
    ("flashinfer", "flashinfer"), ("torch-bindings", "torch-bindings"), ("cpu-torch-bindings", "cpu-torch-bindings"),
    ("moe-torch-bindings", "moe-torch-bindings"), ("rocm-torch-bindings", "rocm-torch-bindings"), ("quickreduce-torch-bindings", "quickreduce-torch-bindings"),
    ("flashkda-registration", "flashkda-registration"), ("fusion", None), ("other", None),
]
wrapper_ids = [i for i in ops.WRAPPER_IFACES]
opcheck_wrappers = [i for i in wrapper_ids]
# every wrapper is exercised once by an opcheck step (so it is modeled), unless a flow scenario already calls it
called_by_scenarios = set()
for s in scen.SCENARIOS:
    for st in s.get("steps", []) or []:
        if "interface" in st:
            called_by_scenarios.add(st["interface"])
for f in scen.FLOWS:
    called_by_scenarios.add(f["entry"]["interface"])
need = [i for i in opcheck_wrappers if i not in called_by_scenarios]
reached_all = reach(starts + need)
need += [i for i in ifaces if ifaces[i].get("kind") == "kernel" and i not in reached_all and not ifaces[i].get("attributes", {}).get("boundary")]
reached_all = reach(starts + need)

CHUNK = 60
opcheck = []
pools = {"cuda": [], "cpu": []}
for i in need:
    pools["cpu" if ifaces[i]["component"] in ("cpu-torch-bindings", "cpu-triton-utils") else "cuda"].append(i)
for pool, ids_all in pools.items():
    ids_all.sort(key=lambda i: (ifaces[i]["component"], i))
    for n in range(0, len(ids_all), CHUNK):
        chunk = ids_all[n:n + CHUNK]
        part = n // CHUNK + 1
        comps = sorted({ifaces[i]["component"] for i in chunk})
        comp_ = ", ".join(comps)
        sid = f"kernels-ops-opcheck-{pool}-{part}"
        cpu = pool == "cpu"
        # the ops these steps should reach (static targets, plus the CPU/CUDA choice)
        expect_ops = []
        for i in chunk:
            top = []
            for st in ifaces[i].get("behavior") or []:
                c = st.get("call")
                if isinstance(c, str) and not c.startswith("="):
                    top.append(c)
                top.extend(st.get("targets", []) or [])
            for t in top:
                if t in ifaces and t not in expect_ops and (not t.startswith("cpu-torch-bindings.") or cpu):
                    if t.startswith("torch-bindings.") and cpu:
                        continue
                    expect_ops.append(t)
        steps = [{"interface": i, "caller": "gpu-worker", "as": f"s{k}"} for k, i in enumerate(chunk)]
        lst = ", ".join(f"'{x}'" for x in (chunk + expect_ops))
        sc = {"id": sid, "name": f"opcheck ({pool} build): call each entry point of {comp_} once ({len(chunk)} calls)",
              "description": "Mirrors tests/kernels opcheck-style tests: every op or wrapper is called once with the canonical Llama-3.1-8B shapes; each wrapper must reach its registered op.",
              "fixtures": ["tp1-llama-8b"], "steps": steps,
              "expect": ["[" + ", ".join(f"steps.s{k}.result.ok" for k in range(len(chunk))) + "].all(x, x)",
                         "!trace.exists(e, e.type == 'call.end' && has(e.error) && e.error != null)"]}
        if cpu:
            sc["config"] = {"vllm-target-device": "cpu"}
        opcheck.append(sc)

# ------------------------------------------------------------ assemble
import re as _re
KEEP = {
    ("kernels-ops-vllm-backend-compile-cold", 1), ("kernels-ops-vllm-backend-compile-warm-restart", 1),
    ("kernels-ops-support-torch-compile-aot-warm-restart", 1), ("kernels-ops-post-grad-pass-manager-deployed", 3),
    ("kernels-ops-cuda-graph-wrapper-capture-then-replay", 2), ("kernels-ops-op-capture-toggle", 1),
    # round 5: the MoE world's end-to-end forward is checked by the kernel paths its trace records
    ("kernels-ops-moe-world-mixtral-forward", 1), ("kernels-ops-moe-world-mixtral-forward", 2),
}
_IFACE_LIT = _re.compile(r"'([a-z0-9-]+\.[a-z0-9-]+)'")
_STATE = _re.compile(r"state\['([a-z0-9-]+)@rank0'\]")
STORE_COMPS = {"torch-compile-cache", "helion-config-manager"}


def blackbox(sc):
    """Keep expectations on result, steps and io; drop assertions on internal calls the result
    already proves; turn assertions on internal component state into checks of the run's state
    writes on that component (needed by the hollow lint)."""
    ex = sc.get("expect", [])
    if sc["id"].startswith("oracle-build"):
        return sc
    boundary_ok = lambda e: ("result" in e or "steps." in e or "io." in e)
    out = []
    for n, e in enumerate(ex):
        if (sc["id"], n) in KEEP:
            out.append(e)
            continue
        names = [m for m in _IFACE_LIT.findall(e) if m in ifaces and m not in boundary_set]
        comps = [c for c in _STATE.findall(e) if c not in STORE_COMPS]
        if not names and not comps:
            out.append(e)
            continue
        if comps and not names:
            # state the scenario writes is the point of these flows (and the hollow lint needs it): kept
            out.append(e)
            continue
        # internal call assertion: dropped when the result or steps already show the branch
        if not any(boundary_ok(x) for x in ex):
            out.append(e)
    sc = dict(sc)
    sc["expect"] = out
    return sc


def clean_scenario(s):
    s = blackbox(dict(s))
    if s.get("flow") is None:
        s.pop("flow", None)
    return s


boundary_set = set(starts)
for iid, f in ifaces.items():
    if f.get("attributes", {}).get("boundary") or components.get(f["component"], {}).get("kind") == "external":
        boundary_set.add(iid)
schemas = [{"id": k, **v} for k, v in {**ops.SCHEMAS, **hand.SCHEMAS_HAND}.items()]
ORDER = ["component", "name", "kind", "summary", "description", "sources", "attributes", "request", "response", "errors", "latency_ms", "store", "behavior"]


def ordered(d):
    return {k: d[k] for k in ORDER if k in d} | {k: v for k, v in d.items() if k not in ORDER}


doc = {
    "schema_version": 1,
    "id": "vllm",
    "configs": hand.configs() + hand3.CONFIGS + hand4.CONFIGS,
    "schemas": schemas,
    "components": list(components.values()),
    "interfaces": [ordered(ifaces[i]) for i in sorted(ifaces)],
    "fixtures": [{"id": "kernels-ops-seed", "summary": "kernels-ops state at worker start: CUDA graph capture allowed, no graphs captured, empty compile caches.",
                  "state": {"compilation-monitor": {"cudagraph_capturing_enabled": True}, "cuda-graph-wrapper": {"entries": {}, "num_cudagraph_captured": 0},
                            "compiler-manager": {"cache": {}, "is_cache_updated": False, "disable_cache": False}, "torch-compile-cache": {"files": {}, "aot": {}}}}],
    "flows": scen.FLOWS,
    "scenarios": [clean_scenario(s) for s in scen.SCENARIOS] + opcheck,
}


class Dumper(yaml.SafeDumper):
    pass


def str_rep(d, s):
    style = None
    if s.startswith("=") or any(c in s for c in ":#{}[],&*!|>'\"%@`") or s in ("true", "false", "null", "yes", "no", "on", "off") or s.strip() != s:
        style = '"'
    return d.represent_scalar("tag:yaml.org,2002:str", s, style=style)


Dumper.add_representer(str, str_rep)
Dumper.ignore_aliases = lambda *a: True

out = os.path.join(ROOT, "fragments", "kernels-ops.yaml")
with open(out, "w") as f:
    f.write("# kernels-ops fragment of the vLLM v0.32.0 ontology. GENERATED by examples/vllm/gen/kernels-ops/build.py; edit the generator.\n")
    yaml.dump(doc, f, Dumper=Dumper, sort_keys=False, width=200, allow_unicode=True)

# ------------------------------------------------------------ skips
skips = []
for e in ops.mine:
    if e["kind"] == "python-cli":
        skips.append({"kind": e["kind"], "name": e["name"], "file": e["file"], "line": e["line"],
                      "reason": "not an entry point of the product: build-time code generator run by CMake to emit kernel instantiation sources"})
with open(os.path.join(ROOT, "skips", "kernels-ops.json"), "w") as f:
    json.dump(skips, f, indent=1)
    f.write("\n")

print(f"interfaces {len(ifaces)} components {len(components)} flows {len(scen.FLOWS)} scenarios {len(doc['scenarios'])} (opcheck {len(opcheck)}) skips {len(skips)}")
unreached = [i for i in ifaces if i not in reached_all]
print("unreached interfaces:", len(unreached), unreached[:20])

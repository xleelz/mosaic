#!/usr/bin/env python3
"""Round 5: copy the owners' contracts for the stubs engine-core added this round into owner5.json.

Run: python3 examples/vllm/gen/engine-core/owner5.py (re-run when an owner changes its contract)."""
import json, os, yaml

HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, "..", "..", "fragments")
WANT = {
    "config-platform": ["vllm-config.resolve-async-scheduling", "hf-hub.download-config"],
    "serving-api": ["sampling-params.verify", "base-renderer.validate-token-ids"],
}
out = {"ifaces": {}, "components": {}}
for area, keys in WANT.items():
    d = yaml.safe_load(open(os.path.join(FR, area + ".yaml")))
    comps = {c["id"]: c for c in d.get("components") or []}
    for i in d["interfaces"]:
        k = i["component"] + "." + i["name"]
        if k in keys:
            out["ifaces"][k] = {"owner": area, **{f: i.get(f) for f in ("kind", "sources", "request", "response", "errors", "summary", "store", "attributes")}}
            c = comps.get(i["component"])
            if c:
                out["components"][c["id"]] = {"owner": area, **{f: c.get(f) for f in ("id", "name", "kind", "parent", "layer", "summary", "sources")}}
missing = {k for ks in WANT.values() for k in ks} - set(out["ifaces"])
assert not missing, missing
json.dump(out, open(os.path.join(HERE, "owner5.json"), "w"), indent=1, sort_keys=True)
print("owner5.json:", sorted(out["ifaces"]))

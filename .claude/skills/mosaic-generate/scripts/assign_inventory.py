#!/usr/bin/env python3
"""Assign inventory entries to areas, merge the areas' skip files, and generate the merged worlds.

Usage: assign_inventory.py <workspace> [--worlds] [--dry-run]   (e.g. examples/vscode)

Reads <workspace>/profile.yaml, <workspace>/inventory.json and <workspace>/skips/*.json (but not
skips/*.features.json, the feature skips that `check --features` reads).
Writes <workspace>/inventory.json in place (unless --dry-run), setting each entry's:
  - "area": the owning area by the profile's globs. The most specific glob, meaning the longest
    literal prefix, wins, and an area's `except` globs carve paths out. Entry overrides beat the
    globs: a profile `overrides` item {file: <path or glob>, name: <entry name or glob>, area,
    reason} assigns every entry whose file and name both match (fnmatch; `name` defaults to "*").
    When several match, the most specific wins: the longest literal prefix of `name` (leading
    wildcards skipped, so "* /v1/nodes/pod-*" beats "* /v1/nodes/*"), then of `file`, then the
    first listed. Overrides with `symbol` and no `file` are code-ownership notes for the brief
    and are ignored here. The check tool uses "area" for --min-modeled and --min-substantive.
  - "level": the kind's `level` from the profile ("registered" for declaration-only kinds);
  - "skip": "<area>: <reason>" for entries listed in skips/<area>.json, unless the skip is
    rejected. Rejected skips are reported and not applied, so the entry counts as uncovered:
      - a reason starting with one of REJECT (case-insensitive);
      - a reason that says "covered by" without a `covered_by` field (DESIGN §13.1 item 15);
      - a `covered_by` naming no entity in the merged fragments (skeleton.yaml, fixtures.yaml and
        fragments/*.yaml). An entity key is "<kind>:<id>", for example
        "interface:git-service.commit" or "component:git-service"; a bare id is accepted when an
        interface or component has it.
Existing "skip" fields are cleared first, so the skip files are the only source.

--worlds also writes <workspace>/worlds.yaml (DESIGN §13.1 item 15), so the merged worlds can't
go stale. For each world in the profile's `fixtures.worlds` it writes `full-<id>` (or the
world's `full_id`; `full: false` leaves the world out), which extends:
  1. the world itself;
  2. every `<area>-seed` fixture defined in fragments/*.yaml, sorted by id;
  3. the area variants of the world: fragment fixtures marked `attributes: {variant_of: <world>}`,
     or, unmarked, fragment fixtures whose `extends` is exactly [<world>, <area>-seed] when the
     world is a leaf (no other profile world extends it). Fixtures extending an inner world (the
     window every area seed already describes) are scenario setups, not variants; mark one
     `variant_of` to include it, or `variant_of: none` to leave out a leaf-world fixture.
Then it appends the profile's `fixtures.derived` fixtures verbatim (overlays such as a config
change on top of a full world).
"""
import argparse
import collections
import fnmatch
import glob
import json
import os
import re
import sys

import yaml

REJECT = ("not modeled", "not modelled", "out of scope", "too large", "todo")
COVERED_BY = re.compile(r"\bcovered by\b", re.I)
KINDS = {
    "components": "component",
    "interfaces": "interface",
    "links": "link",
    "schemas": "schema",
    "flows": "flow",
    "scenarios": "scenario",
    "configs": "config",
    "fixtures": "fixture",
}


def literal_prefix(g):
    return len(g.split("*")[0])


def name_prefix(g):
    """Literal prefix of a name glob, skipping leading wildcards (route names start with "* ")."""
    return literal_prefix(g.lstrip("*? "))


def entry_overrides(prof):
    """The profile's entry overrides ({file, name, area}), validated, in profile order."""
    ids = {a["id"] for a in prof["areas"]}
    out = []
    for i, o in enumerate(prof.get("overrides") or []):
        if not isinstance(o, dict) or "file" not in o:
            continue  # symbol overrides: code ownership for the brief, not inventory
        if o.get("area") not in ids:
            sys.exit(f"overrides[{i}]: area {o.get('area')!r} is not a profile area")
        out.append({"i": i, "file": str(o["file"]), "name": str(o.get("name", "*")), "area": o["area"]})
    return out


def override_for(e, ovr):
    """The most specific entry override matching e, or None."""
    best = None
    for o in ovr:
        if fnmatch.fnmatch(e["file"], o["file"]) and fnmatch.fnmatch(e["name"], o["name"]):
            k = (name_prefix(o["name"]), literal_prefix(o["file"]), -o["i"])
            if best is None or k > best[0]:
                best = (k, o)
    return best[1] if best else None


def owner(path, areas):
    best = None
    for a in areas:
        if any(fnmatch.fnmatch(path, x) for x in a.get("except", [])):
            continue
        for g in a["owns"]:
            if fnmatch.fnmatch(path, g):
                n = literal_prefix(g)
                if best is None or n > best[0]:
                    best = (n, a["id"])
    return best[1] if best else None


def load_docs(ws):
    """The merged model's source documents: skeleton, fixtures and every fragment, by path."""
    paths = [os.path.join(ws, "skeleton.yaml"), os.path.join(ws, "fixtures.yaml")]
    paths += sorted(glob.glob(os.path.join(ws, "fragments", "*.yaml")))
    docs = {}
    for p in paths:
        if os.path.exists(p):
            docs[p] = yaml.safe_load(open(p)) or {}
    return docs


def entity_id(kind, x):
    if kind == "interface" and not x.get("id") and x.get("component") and x.get("name"):
        return f"{x['component']}.{x['name']}"
    return x.get("id")


def entity_keys(docs):
    keys = set()
    for d in docs.values():
        for field, kind in KINDS.items():
            for x in d.get(field) or []:
                if isinstance(x, dict) and entity_id(kind, x):
                    keys.add(f"{kind}:{entity_id(kind, x)}")
    return keys


def resolve_covered_by(ref, keys):
    ref = ref.strip()
    if ref in keys:
        return ref
    kind, _, rest = ref.partition("/")
    if kind in KINDS.values() and f"{kind}:{rest}" in keys:
        return f"{kind}:{rest}"
    for kind in ("interface", "component"):
        if f"{kind}:{ref}" in keys:
            return f"{kind}:{ref}"
    return None


def skip_problem(x, keys):
    """Why a skip entry is rejected, or None."""
    reason = (x.get("reason") or "").strip()
    if not reason:
        return "no reason"
    if reason.lower().startswith(REJECT):
        return "rejected reason"
    cov = x.get("covered_by")
    if cov:
        if resolve_covered_by(str(cov), keys) is None:
            return "covered_by names no entity"
    elif COVERED_BY.search(reason):
        return "says covered by, without covered_by"
    return None


def assign(ws, dry_run, docs):
    prof = yaml.safe_load(open(os.path.join(ws, "profile.yaml")))
    inv_path = os.path.join(ws, "inventory.json")
    inv = json.load(open(inv_path))
    entries = inv["entries"] if isinstance(inv, dict) else inv
    levels = {k["kind"]: k.get("level", "") for k in prof["inventory"]["kinds"]}
    ovr = entry_overrides(prof)
    ovr_hits = collections.Counter()
    by_key, by_line = {}, collections.defaultdict(list)
    for e in entries:
        e.pop("skip", None)
        e.pop("level", None)
        if levels.get(e["kind"]):
            e["level"] = levels[e["kind"]]
        o = override_for(e, ovr) if ovr else None
        if o:
            ovr_hits[o["i"]] += 1
            e["area"] = o["area"]
        else:
            e["area"] = owner(e["file"], prof["areas"]) or ""
        by_key[(e["file"], e["line"], e["kind"], e["name"])] = e
        by_line[(e["file"], e["line"])].append(e)
    keys = entity_keys(docs)
    stats = collections.Counter()
    rejected = collections.defaultdict(collections.Counter)
    for f in sorted(glob.glob(os.path.join(ws, "skips", "*.json"))):
        if f.endswith(".features.json"):  # feature skips (DESIGN §13.1 item 19), read by check --features
            continue
        area = os.path.basename(f)[:-5]
        for x in json.load(open(f)):
            e = by_key.get((x.get("file"), x.get("line"), x.get("kind"), x.get("name")))
            if e is None:
                cand = by_line.get((x.get("file"), x.get("line")), [])
                e = cand[0] if len(cand) == 1 else None
            if e is None:
                stats[area + ":unmatched"] += 1
                continue
            why = skip_problem(x, keys)
            if not why and not area.startswith("_") and e.get("area") and e["area"] != area:
                # Only the owning area skips an entry; _profile.json holds the coordinator's group skips.
                why = f"entry owned by {e['area']}, not {area}"
            if why:
                rejected[area][why] += 1
                continue
            reason = x["reason"].strip()
            if x.get("covered_by"):
                ref = resolve_covered_by(str(x["covered_by"]), keys)
                reason = f"{reason} (covered by {ref})"
            e["skip"] = f"{area}: {reason}"
            stats[area] += 1
    if not dry_run:
        json.dump(inv, open(inv_path, "w"), indent=2)
        open(inv_path, "a").write("\n")
    areas = collections.Counter(e["area"] or "(none)" for e in entries)
    print("entries per area:", dict(areas.most_common()))
    if ovr:
        unused = [f"overrides[{o['i']}] {o['file']} {o['name']!r}" for o in ovr if not ovr_hits[o["i"]]]
        print(f"entry overrides: {sum(ovr_hits.values())} entries by {len(ovr) - len(unused)} of {len(ovr)} overrides;",
              "matching nothing:", unused)
    print("skips applied:", dict(sorted(stats.items())))
    print("skips rejected (count as uncovered):", {a: dict(c) for a, c in sorted(rejected.items())})
    if dry_run:
        print("dry run: inventory.json not written")
    return sum(sum(c.values()) for c in rejected.values())


def worlds(ws, docs):
    prof = yaml.safe_load(open(os.path.join(ws, "profile.yaml")))
    fx = prof.get("fixtures") or {}
    ws_worlds = fx.get("worlds") or []
    area_ids = [a["id"] for a in prof["areas"]]
    frag_fixtures = []
    for p, d in docs.items():
        if os.path.dirname(p).endswith("fragments"):
            frag_fixtures += [x for x in d.get("fixtures") or [] if isinstance(x, dict)]
    ids = {x["id"] for x in frag_fixtures}
    seeds = sorted(f"{a}-seed" for a in area_ids if f"{a}-seed" in ids)
    missing = [a for a in area_ids if f"{a}-seed" not in ids]
    parents = {p for w in ws_worlds for p in (w.get("extends") or [])}

    def variants(w):
        out = []
        for x in frag_fixtures:
            if x["id"] in seeds:
                continue
            mark = (x.get("attributes") or {}).get("variant_of")
            if mark is not None:
                if mark == w:
                    out.append(x["id"])
                continue
            ext = x.get("extends") or []
            if w not in parents and len(ext) == 2 and ext[0] == w and ext[1] in seeds \
                    and x["id"].startswith(ext[1][: -len("seed")]):
                out.append(x["id"])
        return sorted(out)

    fixtures = []
    for w in ws_worlds:
        if w.get("full") is False:
            continue
        fid = w.get("full_id") or f"full-{w['id']}"
        var = variants(w["id"])
        summary = f"{w['id']} plus every area seed"
        if var:
            summary += " and the areas' variants of it (" + ", ".join(var) + ")"
        fixtures.append({"id": fid, "summary": summary + ".", "extends": [w["id"]] + seeds + var})
    fixtures += fx.get("derived") or []
    doc = {"schema_version": 1, "id": prof["id"], "fixtures": fixtures}
    out = os.path.join(ws, "worlds.yaml")
    with open(out, "w") as f:
        f.write("# Generated by .claude/skills/mosaic-generate/scripts/assign_inventory.py --worlds; do not edit.\n")
        f.write("# Merged worlds (coordinator): each extends a profile world, every area seed and the\n")
        f.write("# areas' variants of the world, so they are valid only when all fragments are merged.\n")
        f.write("# Benchmark, oracle and judge scenarios start here.\n")
        yaml.safe_dump(doc, f, sort_keys=False, width=100)
    print(f"worlds: wrote {out}: {[x['id'] for x in fixtures]}; seeds {len(seeds)}; areas without a seed: {missing}")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("workspace")
    ap.add_argument("--worlds", action="store_true", help="also write <workspace>/worlds.yaml")
    ap.add_argument("--dry-run", action="store_true", help="report, but don't write inventory.json")
    args = ap.parse_args(argv)
    docs = load_docs(args.workspace)
    assign(args.workspace, args.dry_run, docs)
    if args.worlds:
        worlds(args.workspace, docs)


if __name__ == "__main__":
    main(sys.argv[1:])

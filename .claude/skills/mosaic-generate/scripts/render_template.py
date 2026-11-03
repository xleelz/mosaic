#!/usr/bin/env python3
"""Render a pipeline template with a repo profile.

Usage: render_template.py <workspace> <template name or path> [out]
  e.g. render_template.py examples/vllm BRIEF            -> examples/vllm/BRIEF.md
       render_template.py examples/vllm JUDGE judge/JUDGE.md

Each {{dotted.path}} names a profile field. Lists of mappings render as Markdown tables, lists of
scalars as comma-separated code spans, and mappings as `key: value` bullets. Derived fields:
{{areas.count}}, and {{inventory.counts}} (from <workspace>/inventory.json). Unresolved
placeholders are listed on stderr and left in place, so nothing is silently dropped.
"""
import collections
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(__file__)
TABLE_COLS = {
    "areas": [("id", "Area"), ("module", "Module"), ("owns", "Owns"), ("except", "Except"), ("entry_points", "Typical entry points")],
    "overrides": [("symbol", "Symbol"), ("file", "File"), ("name", "Entry"), ("area", "Area"), ("reason", "Reason")],
    "errors.table": [("code", "Code"), ("status", "Status"), ("retryable", "Retryable"), ("source", "Source")],
    "inventory.kinds": [("kind", "Kind"), ("owner", "Owner"), ("cover", "What covers it"), ("level", "Level")],
    "shared_data": [("datum", "Datum"), ("owner", "Owner"), ("readers", "Readers")],
    "features": [("id", "Feature"), ("summary", "Summary"), ("sources", "Sources"), ("owner", "Owner")],
}


def cell(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ", ".join(f"`{x}`" for x in v)
    if v is None:
        return ""
    return str(v).replace("|", "\\|")


def table(rows, cols):
    cols = [c for c in cols if any(c[0] in r for r in rows)]
    out = ["| " + " | ".join(h for _, h in cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(cell(r.get(k)) for k, _ in cols) + " |")
    return "\n".join(out)


def inline(v):
    """A list of mappings inside a sentence: each item's values joined, as code spans."""
    return "; ".join(", ".join(f"`{x}`" if i == 0 else str(x) for i, x in enumerate(d.values())) for d in v)


def render_value(key, v, midline=False):
    if midline and isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
        return inline(v)
    if key in TABLE_COLS and isinstance(v, list):
        return table(v, TABLE_COLS[key])
    if isinstance(v, list):
        if v and all(isinstance(x, dict) for x in v):
            keys = list(dict.fromkeys(k for x in v for k in x))
            return table(v, [(k, k) for k in keys])
        return ", ".join(f"`{x}`" for x in v) if v else "(none)"
    if isinstance(v, dict):
        return "\n".join(f"- `{k}`: {cell(x)}" for k, x in v.items())
    return cell(v)


def get(prof, path):
    v = prof
    for k in path.split("."):
        if not isinstance(v, dict) or k not in v:
            raise KeyError(path)
        v = v[k]
    return v


def main(ws, tmpl, out=None):
    prof = yaml.safe_load(open(os.path.join(ws, "profile.yaml")))
    path = tmpl if os.path.exists(tmpl) else os.path.join(HERE, "..", "templates", tmpl.removesuffix(".md") + ".md")
    t = open(path).read()
    t = re.sub(r"^<!--.*?-->\n\n", "", t, flags=re.S)
    derived = {"areas.count": str(len(prof["areas"]))}
    inv = os.path.join(ws, "inventory.json")
    if os.path.exists(inv):
        d = json.load(open(inv))
        e = d["entries"] if isinstance(d, dict) else d
        c = collections.Counter(x["kind"] for x in e)
        derived["inventory.counts"] = f"{len(e)} entries: " + ", ".join(f"{n} {k}" for k, n in c.most_common())
    missing = []

    def rep(m):
        k = m.group(1)
        if k in derived:
            return derived[k]
        line_start = m.string.rfind("\n", 0, m.start()) + 1
        line_end = m.string.find("\n", m.end())
        line_end = len(m.string) if line_end < 0 else line_end
        midline = m.string[line_start:m.start()].strip() != "" or m.string[m.end():line_end].strip() != ""
        try:
            return render_value(k, get(prof, k), midline)
        except KeyError:
            missing.append(k)
            return m.group(0)

    t = re.sub(r"\{\{([a-z_][a-z_.]*)\}\}", rep, t)
    t = re.sub(r"[ \t]*<!-- (table|list):[^>]*-->", "", t)
    out = out or os.path.basename(path)
    dest = out if os.path.isabs(out) else os.path.join(ws, out)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "w").write(t)
    print(f"wrote {dest}" + (f"; unresolved: {sorted(set(missing))}" if missing else ""), file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:])

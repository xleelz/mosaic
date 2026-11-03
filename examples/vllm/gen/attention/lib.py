"""Helpers for generating the attention fragment: line lookups against the vLLM snapshot,
citations, kernel stubs and launch steps. Read-only against the code."""
import ast
import json
import os
import re

ROOT = "/home/lbethay/.cache/mosaic-bench/vllm-0.32.0"
HERE = os.path.dirname(os.path.abspath(__file__))
INV_PATH = os.path.join(HERE, "..", "..", "inventory.json")

_src = {}


def lines(f):
    if f not in _src:
        with open(os.path.join(ROOT, f)) as fh:
            _src[f] = fh.read().splitlines()
    return _src[f]


def ln(f, pat, after=1, nth=1):
    """Line number (1-based) of the nth regex match at or after `after`."""
    rx = re.compile(pat)
    n = 0
    for i, l in enumerate(lines(f), 1):
        if i < after:
            continue
        if rx.search(l):
            n += 1
            if n == nth:
                return i
    raise SystemExit(f"pattern not found: {f}: {pat!r} after {after}")


_ast = {}


def fn(f, name, after=1):
    """(first line, last line) of the def `name` at or after `after` (decorators excluded)."""
    if f not in _ast:
        _ast[f] = ast.parse("\n".join(lines(f)))
    best = None
    for n in ast.walk(_ast[f]):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name and n.lineno >= after:
            if best is None or n.lineno < best.lineno:
                best = n
    if best is None:
        raise SystemExit(f"def not found: {f}: {name}")
    return best.lineno, best.end_lineno


def cls(f, name):
    if f not in _ast:
        _ast[f] = ast.parse("\n".join(lines(f)))
    for n in ast.walk(_ast[f]):
        if isinstance(n, ast.ClassDef) and n.name == name:
            return n.lineno, n.end_lineno
    raise SystemExit(f"class not found: {f}: {name}")


def C(f, a, b=None):
    lines(f)  # check the file exists
    assert a >= 1
    if b is None or b == a:
        return f"{f}:{a}"
    return f"{f}:{a}-{b}"


def Cfn(f, name, after=1):
    a, b = fn(f, name, after)
    return C(f, a, b)


def Cln(f, pat, after=1, nth=1):
    return C(f, ln(f, pat, after, nth))


with open(INV_PATH) as fh:
    INV_ALL = json.load(fh)["entries"]
INV = [e for e in INV_ALL if e.get("area") == "attention"]
_inv_by = {}
for e in INV:
    _inv_by.setdefault((e["file"], e["name"]), []).append(e)


def inv(f, name):
    es = _inv_by.get((f, name))
    if not es:
        raise SystemExit(f"inventory entry not found: {f} {name}")
    assert len(es) == 1, (f, name)
    return es[0]


def Cinv(f, name):
    e = inv(f, name)
    return C(f, e["line"], e.get("end_line"))


USED = set()  # (file, name) of inventory entries cited


def mark(f, name):
    inv(f, name)
    USED.add((f, name))


# Latency expressions (labeled assumptions; the code gives no numbers). See notes §4.
LAT_ATTN = ("= ((double(config['attn-kernel-launch-us'])"
            " + double(input.num_tokens) * double(config['attn-us-per-query-token'])"
            " + double(input.kv_tokens) * double(config['attn-us-per-kv-token'])) / 1000.0)")
LAT_META = "= double(config['attn-kernel-launch-us']) / 1000.0"

SHAPE = "= has(input.shape) ? input.shape : {}"


def kernel(comp, name, f, invname, summary, lat=LAT_ATTN, lang="triton", extra_sources=()):
    """A kernel interface (kind kernel) citing the inventory entry's own lines; no body."""
    mark(f, invname)
    return {
        "component": comp,
        "name": name,
        "kind": "kernel",
        "summary": summary,
        "sources": [Cinv(f, invname), *extra_sources],
        "attributes": {"kernel": invname, "language": lang},
        "request": "AttnKernelShape",
        "response": "AttnKernelResult",
        "latency_ms": lat,
    }


def op_kernel(comp, name, src, summary, opname, lat=LAT_ATTN, lang="cuda"):
    """A kernel interface for an op whose body lives outside the inventory (FA, FlashMLA)."""
    return {
        "component": comp,
        "name": name,
        "kind": "kernel",
        "summary": summary,
        "sources": [src],
        "attributes": {"op": opname, "language": lang},
        "request": "AttnKernelShape",
        "response": "AttnKernelResult",
        "latency_ms": lat,
    }


def launch(target, f, line, title, detail=None, shape=SHAPE):
    s = {"title": title, "source": C(f, line), "call": target, "input": shape, "fill": True}
    if detail:
        s["detail"] = detail
    return s


def helper(f, invname, title):
    """A narrative step naming a @triton.jit device helper inlined into a kernel."""
    mark(f, invname)
    return {"title": title, "source": Cinv(f, invname)}


def note(title, src, detail=None):
    s = {"title": title, "source": src}
    if detail:
        s["detail"] = detail
    return s

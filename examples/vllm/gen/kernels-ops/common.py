"""Shared helpers for the kernels-ops fragment generator (read-only on the code tree)."""
import json
import os
import re

CODE = "/home/lbethay/.cache/mosaic-bench/vllm-0.32.0"
HERE = os.path.dirname(os.path.abspath(__file__))

_cache = {}


def lines(path):
    if path not in _cache:
        with open(os.path.join(CODE, path), errors="replace") as f:
            _cache[path] = f.read().split("\n")
    return _cache[path]


def findline(path, needle, start=1, end=None, regex=False, nth=1):
    """1-based line number of the nth line in [start, end] containing needle."""
    ls = lines(path)
    end = end or len(ls)
    seen = 0
    for i in range(max(start, 1) - 1, min(end, len(ls))):
        hit = re.search(needle, ls[i]) if regex else (needle in ls[i])
        if hit:
            seen += 1
            if seen == nth:
                return i + 1
    raise KeyError(f"{needle!r} not found in {path}:{start}-{end}")


def src(path, needle=None, start=1, end=None, regex=False, nth=1, span=0):
    """A citation string path:line (or path:line-line+span)."""
    if needle is None:
        ln = start
    else:
        ln = findline(path, needle, start, end, regex, nth)
    if span:
        return f"{path}:{ln}-{ln + span}"
    return f"{path}:{ln}"


def defline(path, name, kind="def"):
    """Line of `def name(` / `class name` in a Python file."""
    pat = rf"^\s*{kind}\s+{re.escape(name)}\b"
    return findline(path, pat, regex=True)


_camel = re.compile(r"([a-z0-9])([A-Z])")
_non = re.compile(r"[^a-z0-9]+")


def slug(name, limit=64):
    s = _camel.sub(r"\1-\2", name)
    s = _non.sub("-", s.lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rstrip("-")
    return s


def load_json(name):
    return json.load(open(os.path.join(HERE, name)))

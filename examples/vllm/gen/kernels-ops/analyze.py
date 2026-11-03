"""Analyze the kernels-ops inventory entries against the vLLM source.

Finds, for every torch-library op, the host functions named in its `impl`
registrations and where they are defined, and, for every __global__ kernel,
the host function that launches it and the op that registers that function.
Writes gen/kernels-ops/analysis.json. Read-only on the code tree.
"""
import json
import os
import re
import sys

CODE = "/home/lbethay/.cache/mosaic-bench/vllm-0.32.0"
HERE = os.path.dirname(os.path.abspath(__file__))

mine = json.load(open(os.path.join(HERE, "mine.json")))

_cache = {}


def lines(path):
    if path not in _cache:
        with open(os.path.join(CODE, path), errors="replace") as f:
            _cache[path] = f.read().split("\n")
    return _cache[path]


csrc_files = []
for root, _, files in os.walk(os.path.join(CODE, "csrc")):
    for fn in files:
        if fn.endswith((".cu", ".cpp", ".cuh", ".h", ".hpp", ".cc")):
            csrc_files.append(os.path.relpath(os.path.join(root, fn), CODE))
csrc_files.sort()

# function definitions: a line starting at column 0 (or after 'static', 'inline',
# template) whose text has `name(` and the definition opens a brace soon after.
defre = re.compile(r"^(?:template\s*<[^>]*>\s*)?(?:static\s+|inline\s+|__host__\s+)*[A-Za-z_][\w:<>,\s\*&]*?\b(\w+)\s*\(")


def find_defs(name, prefer=None):
    out = []
    pat = re.compile(r"^[A-Za-z_].*?\b" + re.escape(name) + r"\s*\(")
    for f in csrc_files:
        ls = lines(f)
        for i, l in enumerate(ls):
            if pat.match(l) and not l.rstrip().endswith(";"):
                # skip declarations: look ahead for '{' before ';'
                j, ok = i, False
                while j < min(i + 15, len(ls)):
                    s = ls[j]
                    if "{" in s:
                        ok = True
                        break
                    if s.rstrip().endswith(";"):
                        break
                    j += 1
                if ok:
                    out.append((f, i + 1))
    if prefer:
        out.sort(key=lambda x: (0 if x[0].startswith(prefer) else 1, x[0]))
    return out


impl_re = re.compile(r"(\w+)=TORCH_BOX\(&([\w:]+)\)|(torch::k\w+)=&([\w:]+)|(\w+)=&([\w:]+)")

ops = [e for e in mine if e["kind"] == "torch-op"]
op_impls = {}
for e in ops:
    if e["via"] != "torch-library":
        continue
    det = e.get("detail", "")
    impls = []
    if "; impl " in det:
        for m in impl_re.finditer(det.split("; impl ", 1)[1]):
            key = m.group(1) or m.group(3) or m.group(5)
            fn = (m.group(2) or m.group(4) or m.group(6)).split("::")[-1]
            impls.append((key, fn))
    op_impls[e["name"] + "@" + e["file"]] = impls

# function name -> op keys
fn_to_ops = {}
for k, impls in op_impls.items():
    for key, fn in impls:
        fn_to_ops.setdefault(fn, []).append(k)

kernels = [e for e in mine if e["kind"] == "cuda-kernel"]


def enclosing_function(path, lineno):
    """The name of the top-level function or macro containing line lineno (1-based)."""
    ls = lines(path)
    depth_line = lineno - 1
    for i in range(depth_line, -1, -1):
        l = ls[i]
        m = re.match(r"^#define\s+(\w+)", l)
        if m:
            return ("macro", m.group(1), i + 1)
        if l and not l[0].isspace() and l[0] not in "#/}{*":
            m = re.search(r"\b(\w+)\s*\(", l)
            if m and m.group(1) not in ("if", "for", "while", "switch", "return", "sizeof", "decltype"):
                return ("func", m.group(1), i + 1)
    return (None, None, None)


def launch_sites(path, kname, kline):
    ls = lines(path)
    out = []
    pat = re.compile(r"\b" + re.escape(kname) + r"\b")
    for i, l in enumerate(ls):
        if i + 1 == kline:
            continue
        if pat.search(l):
            # skip the kernel's own definition / declaration lines
            if "__global__" in l:
                continue
            window = " ".join(ls[i:i + 6])
            if "<<<" in window or "cudaLaunchKernel" in window or "hipLaunchKernel" in window or "&" + kname in l or "launch" in window.lower() or "kernel" in window:
                out.append(i + 1)
    return out


def resolve_macro_users(path, macro, depth=0):
    """Functions in path that use the macro (directly, or through another macro)."""
    ls = lines(path)
    users = []
    pat = re.compile(r"\b" + re.escape(macro) + r"\b")
    for i, l in enumerate(ls):
        if pat.search(l) and not l.startswith("#define"):
            kind, name, at = enclosing_function(path, i + 1)
            if kind == "func":
                users.append((name, at))
            elif kind == "macro" and depth < 3 and name != macro:
                users += resolve_macro_users(path, name, depth + 1)
    return users


res = {"ops": {}, "kernels": []}
for k, impls in op_impls.items():
    name, f = k.split("@")
    prefer = os.path.dirname(f)
    defs = {}
    for key, fn in impls:
        d = find_defs(fn, prefer=prefer)
        defs[key + ":" + fn] = d[:4]
    res["ops"][k] = defs

for e in kernels:
    f, kname, kline = e["file"], e["name"], e["line"]
    sites = launch_sites(f, kname, kline)
    hosts = []
    for s in sites:
        kind, name, at = enclosing_function(f, s)
        if kind == "func":
            hosts.append((name, at))
        elif kind == "macro":
            hosts += resolve_macro_users(f, name)
    # walk host functions up to op impls (one level: callers of the host in the same dir)
    opk = []
    seen = set()
    frontier = list(hosts)
    for _ in range(4):
        nxt = []
        for name, at in frontier:
            if name in seen:
                continue
            seen.add(name)
            if name in fn_to_ops:
                opk += fn_to_ops[name]
                continue
            # callers of `name` across csrc files in the same top directory
            pat = re.compile(r"\b" + re.escape(name) + r"\s*(<[^;(]*>)?\s*\(")
            d = os.path.dirname(f)
            for ff in csrc_files:
                if not (ff.startswith(d) or os.path.dirname(ff) == os.path.dirname(d) or ff.startswith("csrc/" + d.split("/")[1] if d.count("/") >= 1 else "csrc")):
                    continue
                ls = lines(ff)
                for i, l in enumerate(ls):
                    if pat.search(l) and not l.strip().startswith("//"):
                        kind, nm, at2 = enclosing_function(ff, i + 1)
                        if kind == "func" and nm != name:
                            nxt.append((nm, at2))
                        elif kind == "macro":
                            nxt += [(n2, a2) for n2, a2 in resolve_macro_users(ff, nm)]
        frontier = nxt
    res["kernels"].append({
        "name": kname, "file": f, "line": kline,
        "sites": sites[:6], "hosts": sorted(set(hosts))[:6], "ops": sorted(set(opk)),
    })

json.dump(res, open(os.path.join(HERE, "analysis.json"), "w"), indent=1)
n = sum(1 for k in res["kernels"] if k["ops"])
print("kernels mapped to ops:", n, "of", len(res["kernels"]))
for k in res["kernels"]:
    if not k["ops"]:
        print("UNMAPPED", k["file"], k["line"], k["name"], k["hosts"][:3])

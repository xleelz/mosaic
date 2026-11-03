#!/usr/bin/env python3
"""Rank the functions the repo's tests call that the model does not cite, per area (fix rounds).

Usage: coverage_gaps.py <workspace> [--out-dir DIR] [--top N] [--by owner|test]

Test reach (`check --tests test-targets.json`) is per file: a test counts as reached when the model
cites any line of a file it targets. This script works one level down, at definitions. It reads
<workspace>/profile.yaml (`snapshot.path`, the code root, and its `forbidden` globs),
<workspace>/test-targets.json ([{test, targets, area}], from test_targets.py), every
<workspace>/fragments/*.yaml (the model) and every <workspace>/skips/*.json (inventory entries an
area chose not to model: [{kind, name, file, line, reason, covered_by?}]). Only source files are
opened (.go .py .ts .tsx .js .mjs .cjs .jsx .java), never a forbidden path; the code root is read only.

  - Citations: every string anywhere in the fragments holding `path:line` or `path:a-b`, collected
    recursively (not only `sources:`/`source:`). A path is normalized (`./`, the snapshot prefix);
    one that names no snapshot file matches a target ending in `/<path>`.
  - Definitions of each target file, with line ranges. Python by ast (`def`, `async def`, `class` at
    any depth, decorators included), falling back to indentation. Go `func Name(` and
    `func (r *T) Name(`; TS/JS `function name`, `const name = (`/`async (`/`function`, classes and
    class methods; Java classes and methods. A brace-language definition ends at the closing
    brace at its own indent (or before the next line at the same or lower indent).
  - Referenced: the test file holds the definition's name as a whole word. Names under 4
    characters and common ones (get, run, main, init, New, String, close, start, ...) are ignored.
  - Modeled: some citation of the file overlaps the definition's range. A class counts as modeled
    when any line of its body is cited; its methods are ranked on their own.

--by owner (the default) groups the rows by code owner: the area whose profile `owns` globs match
the definition's file (assign_inventory.py's rule: the longest literal prefix wins, `except` globs
carve paths out; entry overrides are per inventory entry and don't apply). A file no area owns goes
to `unowned`, reported last. Each owner's header counts the definitions in its code that any test
references, how many are modeled, and the function-level reach; its unmodeled definitions are
ranked by how many distinct test files (from any area) reference them, and each row lists the
testing areas with their test counts. --by test keeps the earlier grouping by the test's `area`
(test-targets.json); each row then names the owner. Test-hit skips are skip entries whose file a
test targets and whose name (its last word) the test references, or whose line falls in a
definition a test references; they are grouped the same way, by the skip file's owner or the test's
area.

Writes <out-dir>/coverage-<area>.md (counts, function-level reach, the top N unmodeled definitions
with example tests and any covering skip, then the test-hit skips) and <out-dir>/coverage.json
(everything, untruncated, every row with its owner and its testing areas). --out-dir defaults to
<workspace>/reconcile; --top to 40. Prints one summary line per area.
"""
import argparse
import ast
import collections
import fnmatch
import glob
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from assign_inventory import owner  # noqa: E402  (the inventory's ownership rule)

SRC_EXT = (".go", ".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".jsx", ".java")
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv"}
SECRET = ("**/.env*", "**/*.env*", "**/*.age", "**/*.pem", "**/*.key", "**/credentials*", "**/.netrc")
COMMON = {
    "get", "set", "run", "main", "init", "new", "New", "String", "close", "Close", "start", "Start",
    "stop", "Stop", "test", "Test", "self", "call", "load", "save", "send", "read", "write", "Read",
    "Write", "open", "Open", "reset", "Reset", "update", "Update", "create", "Create", "delete",
    "Delete", "list", "List", "apply", "build", "Build", "parse", "Parse", "check", "setup", "setUp",
    "tearDown", "wait", "Wait", "next", "Next", "name", "Name", "type", "Type", "value", "Value",
    "data", "Data", "items", "keys", "values", "copy", "Copy", "clear", "add", "Add", "remove",
    "Remove", "handle", "Handle", "execute", "process", "forward", "__init__", "__call__",
    "__repr__", "__str__", "__eq__", "__hash__", "__enter__", "__exit__", "__post_init__",
    "__len__", "__iter__", "__getitem__", "__aenter__", "__aexit__", "Error", "error", "Err",
    "render", "default", "Default", "config", "Config", "constructor", "toString", "toJSON",
    "fetch", "Run", "Get", "Set", "Len", "Less", "Swap", "ServeHTTP", "Validate", "validate",
    "format", "Format", "from_dict", "to_dict", "dispatch", "shutdown", "Shutdown", "flush",
    "Flush", "size", "Size", "lock", "Lock", "Unlock", "done", "Done", "match", "Match",
}
IDENT = re.compile(r"[A-Za-z_]\w*")
CITE = re.compile(r"((?:[\w.@+()\[\]-]+/)*[\w.@+()\[\]-]+\.\w+):(\d+)(?:-(\d+))?\b")
CONTINUATION = (")", "]", ">", "}", ".", "&&", "||", "?", ":", "+", ",", "|")
TS_FUNC = re.compile(r"^(\s*)(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)")
TS_CONST = re.compile(r"^(\s*)(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*"
                      r"(?:async\s+)?(?:\(|function\b|[A-Za-z_$][\w$]*\s*=>|<)")
TS_CLASS = re.compile(r"^(\s*)(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")
TS_METHOD = re.compile(r"^(\s+)(?:(?:public|private|protected|static|async|readonly|override|abstract|get|set)\s+)*"
                       r"\*?#?([A-Za-z_$][\w$]*)\s*(?:<[^>(]*>)?\s*(?:\(|=\s*(?:async\s+)?\()")
JAVA_CLASS = re.compile(r"^(\s*)(?:(?:public|private|protected|static|final|abstract|sealed)\s+)*"
                        r"(?:class|interface|enum|record)\s+(\w+)")
JAVA_METHOD = re.compile(r"^(\s+)(?:@\w+\s+)*(?:(?:public|private|protected|static|final|abstract|synchronized|"
                         r"default|native)\s+)*(?:<[^>]+>\s+)?[\w<>\[\],.?\s]+?\s+(\w+)\s*\([^;]*$")
GO_FUNC = re.compile(r"^func\s+(?:\(\s*\w*\s*\*?\s*([\w.]+)(?:\[[^\]]*\])?\s*\)\s*)?([A-Za-z_]\w*)\s*[\[(]")
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "new", "else", "do", "try",
            "with", "await", "typeof", "super", "this", "throw", "case", "synchronized", "import"}


def indent(s):
    return len(s) - len(s.lstrip())


def forbidden(rel, prof):
    pats = list(SECRET) + list(prof["snapshot"].get("forbidden", []))
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch("x/" + rel, p) for p in pats)


def read_source(root, rel, prof):
    if not rel.endswith(SRC_EXT) or forbidden(rel, prof):
        return None
    try:
        with open(os.path.join(root, rel), errors="replace") as f:
            return f.read()
    except OSError:
        return None


# ---- definitions: [{name, qual, start, end}] -------------------------------------------------

def brace_end(lines, i):
    """End line (1-based) of a brace-language definition starting at 0-based line i."""
    first = lines[i]
    if "{" in first and first.count("{") == first.count("}") and first.rstrip().endswith("}"):
        return i + 1
    ind = indent(first)
    last = i
    for j in range(i + 1, len(lines)):
        s = lines[j].strip()
        if not s:
            continue
        if indent(lines[j]) <= ind:
            if s.startswith("}"):
                return j + 1
            if s.startswith(CONTINUATION) or s.startswith(("//", "/*", "*")):
                last = j
                continue
            return last + 1
        last = j
    return last + 1


def defs_python(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return defs_indent(text, re.compile(r"^(\s*)(?:async\s+def|def|class)\s+(\w+)"))
    out = []

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([ch.lineno] + [d.lineno for d in ch.decorator_list])
                out.append({"name": ch.name, "qual": prefix + ch.name, "start": start, "end": ch.end_lineno})
                walk(ch, prefix + ch.name + ".")
            else:
                walk(ch, prefix)
    walk(tree, "")
    return out


def defs_indent(text, pat):
    lines = text.split("\n")
    heads = [(i, len(m.group(1)), m.group(2)) for i, l in enumerate(lines) for m in [pat.match(l)] if m]
    out = []
    for k, (i, ind, name) in enumerate(heads):
        end = len(lines)
        for i2, ind2, _ in heads[k + 1:]:
            if ind2 <= ind:
                end = i2
                break
        out.append({"name": name, "qual": name, "start": i + 1, "end": end})
    return out


def defs_go(text):
    lines = text.split("\n")
    out = []
    for i, l in enumerate(lines):
        m = GO_FUNC.match(l)
        if m:
            recv, name = m.group(1), m.group(2)
            out.append({"name": name, "qual": f"{recv.lstrip('*')}.{name}" if recv else name,
                        "start": i + 1, "end": brace_end(lines, i)})
    return out


def defs_brace(text, pats):
    lines = text.split("\n")
    out = []
    classes = []
    for i, l in enumerate(lines):
        for kind, pat in pats:
            m = pat.match(l)
            if not m or m.group(2) in KEYWORDS:
                continue
            if kind == "method" and (l.rstrip().endswith(";") or not classes
                                     or not any(c["start"] <= i + 1 <= c["end"] for c in classes)):
                continue
            end = brace_end(lines, i)
            d = {"name": m.group(2), "qual": m.group(2), "start": i + 1, "end": end}
            if kind == "class":
                classes.append(d)
            else:
                owner = [c for c in classes if c["start"] < i + 1 <= c["end"]]
                if owner:
                    d["qual"] = owner[-1]["name"] + "." + d["name"]
            out.append(d)
            break
    return out


def definitions(rel, text):
    if rel.endswith(".py"):
        return defs_python(text)
    if rel.endswith(".go"):
        return defs_go(text)
    if rel.endswith(".java"):
        return defs_brace(text, [("class", JAVA_CLASS), ("method", JAVA_METHOD)])
    return defs_brace(text, [("class", TS_CLASS), ("func", TS_FUNC), ("func", TS_CONST), ("method", TS_METHOD)])


# ---- model citations and skips ---------------------------------------------------------------

def citations(ws, root):
    """{path: [(a, b)]} from every citation-shaped string in the fragments."""
    out = collections.defaultdict(list)
    root_prefix = root.rstrip("/") + "/"

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and ":" in x:
            for m in CITE.finditer(x.replace(root_prefix, "")):
                p = m.group(1)
                # Path segments may hold () and [] (Next.js route groups and dynamic routes), so a
                # citation written in parentheses captures its opening "(": drop an unbalanced one.
                while p.startswith("(") and p.count("(") > p.count(")"):
                    p = p[1:]
                while p.startswith("./"):
                    p = p[2:]
                a = int(m.group(2))
                b = int(m.group(3) or a)
                out[p].append((min(a, b), max(a, b)))
    for f in sorted(glob.glob(os.path.join(ws, "fragments", "*.yaml"))):
        with open(f) as fh:
            for doc in yaml.safe_load_all(fh):
                walk(doc)
    return out


def source_files(root):
    """Relative paths of the snapshot's source files (names only; nothing is opened)."""
    out = set()
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, root)
        for n in names:
            if n.endswith(SRC_EXT):
                out.add(os.path.normpath(os.path.join(rel_dir, n)))
    return out


def cites_for(path, cites, suffix_index):
    got = list(cites.get(path, []))
    for p in suffix_index.get(path, ()):
        got.extend(cites[p])
    return got


def load_skips(ws):
    out = []
    for f in sorted(glob.glob(os.path.join(ws, "skips", "*.json"))):
        with open(f) as fh:
            d = json.load(fh)
        for e in d if isinstance(d, list) else []:
            if isinstance(e, dict) and e.get("file"):
                out.append(dict(e, skip_file=os.path.basename(f)))
    return out


# ---- main ------------------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("workspace")
    ap.add_argument("--out-dir")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--by", choices=("owner", "test"), default="owner")
    args = ap.parse_args(argv)
    ws = args.workspace
    with open(os.path.join(ws, "profile.yaml")) as f:
        prof = yaml.safe_load(f)
    root = os.path.expanduser(prof["snapshot"]["path"])
    with open(os.path.join(ws, "test-targets.json")) as f:
        tt = json.load(f)
    cites = citations(ws, root)
    skips = load_skips(ws)

    # A cited path that names no snapshot file (a short form: `routers/serving.ts:12`) stands for
    # the one snapshot source file ending in /<path>; an ambiguous one (`utils.py:3`) is dropped.
    snapshot = source_files(root)
    by_base = collections.defaultdict(list)
    for f in snapshot:
        by_base[os.path.basename(f)].append(f)
    suffix_index = collections.defaultdict(list)
    ambiguous = 0
    for p in cites:
        if p in snapshot:
            continue
        hits = [f for f in by_base.get(os.path.basename(p), ()) if f.endswith("/" + p)]
        if len(hits) == 1:
            suffix_index[hits[0]].append(p)
        elif hits:
            ambiguous += 1

    defs_cache, idents_cache = {}, {}

    def defs_of(rel):
        if rel not in defs_cache:
            text = read_source(root, rel, prof)
            ds = definitions(rel, text) if text is not None else []
            spans = cites_for(rel, cites, suffix_index)
            for d in ds:
                d["modeled"] = any(a <= d["end"] and b >= d["start"] for a, b in spans)
            defs_cache[rel] = ds
        return defs_cache[rel]

    def idents_of(rel):
        if rel not in idents_cache:
            text = read_source(root, rel, prof)
            idents_cache[rel] = set(IDENT.findall(text)) if text is not None else set()
        return idents_cache[rel]

    skips_by_file = collections.defaultdict(list)
    for s in skips:
        skips_by_file[s["file"]].append(s)

    def skip_word(s):
        words = IDENT.findall(str(s.get("name", "")))
        return words[-1] if words else ""

    def covering_skip(path, d):
        for s in skips_by_file.get(path, ()):
            if skip_word(s) == d["name"] or (s.get("line") and d["start"] <= s["line"] <= d["end"]):
                return s
        return None

    # every referenced definition: {(path, start): {def, path, tests: {test area: tests}}};
    # skips hit: {(skip_file, file, name, line): {test area: tests}}
    rows = {}
    skip_hits = collections.defaultdict(lambda: collections.defaultdict(set))
    tests_by_area = collections.Counter()
    for e in tt:
        area = e.get("area") or "unassigned"
        tests_by_area[area] += 1
        if not e["targets"]:
            continue
        ids = idents_of(e["test"])
        if not ids:
            continue
        for t in e["targets"]:
            referenced = []
            for d in defs_of(t):
                if len(d["name"]) < 4 or d["name"] in COMMON or d["name"] not in ids:
                    continue
                referenced.append(d)
                row = rows.setdefault((t, d["start"]), {"def": d, "path": t,
                                                        "tests": collections.defaultdict(set)})
                row["tests"][area].add(e["test"])
            for s in skips_by_file.get(t, ()):
                w = skip_word(s)
                hit = (len(w) >= 4 and w not in COMMON and w in ids) or any(
                    s.get("line") and d["start"] <= s["line"] <= d["end"] for d in referenced)
                if hit:
                    key = (s["skip_file"], s["file"], s.get("name"), s.get("line"))
                    skip_hits[key][area].add(e["test"])

    owner_cache = {}

    def owner_of(path):
        if path not in owner_cache:
            owner_cache[path] = owner(path, prof["areas"]) or "unowned"
        return owner_cache[path]

    # group: {group: [(item, {test area: tests})]}. By owner, an item joins its code's owner with
    # all its tests; by test, it joins each testing area with that area's tests.
    def grouped(items, path_of):
        g = collections.defaultdict(list)
        for item, by_area in items:
            if args.by == "owner":
                g[owner_of(path_of(item))].append((item, by_area))
            else:
                for a, ts in by_area.items():
                    g[a].append((item, {a: ts}))
        return g

    def all_tests(by_area):
        return set().union(*by_area.values())

    def area_counts(by_area):
        return {a: len(ts) for a, ts in sorted(by_area.items())}

    row_groups = grouped([(r, r["tests"]) for r in rows.values()], lambda r: r["path"])
    hit_groups = grouped(list(skip_hits.items()), lambda k: k[1])
    if args.by == "owner":
        names = [a["id"] for a in prof["areas"]] + ["unowned"]
    else:
        names = sorted(tests_by_area, key=lambda a: (a == "unassigned", a))
    names = [a for a in names if a in row_groups or a in hit_groups
             or (args.by == "owner" and a != "unowned") or (args.by == "test" and tests_by_area[a])]

    out_dir = args.out_dir or os.path.join(ws, "reconcile")
    os.makedirs(out_dir, exist_ok=True)
    skip_index = {(s["skip_file"], s["file"], s.get("name"), s.get("line")): s for s in skips}
    report = {"workspace": ws, "by": args.by, "areas": {}}
    for area in names:
        grp = row_groups.get(area, [])
        modeled = sum(r["def"]["modeled"] for r, _ in grp)
        unmodeled = sorted(((r, ba) for r, ba in grp if not r["def"]["modeled"]),
                           key=lambda x: (-len(all_tests(x[1])), x[0]["path"], x[0]["def"]["start"]))
        reach = 100.0 * modeled / max(len(grp), 1)
        tests = set().union(*(all_tests(ba) for _, ba in grp)) if grp else set()
        tests_from = collections.defaultdict(set)  # testing area: its tests that reference this code
        for _, ba in grp:
            for a, ts in ba.items():
                tests_from[a] |= ts
        testing_areas = collections.Counter({a: len(ts) for a, ts in tests_from.items()})
        gaps = []
        for r, ba in unmodeled:
            d = r["def"]
            sk = covering_skip(r["path"], d)
            gaps.append({"path": r["path"], "start": d["start"], "end": d["end"], "name": d["qual"],
                         "owner": owner_of(r["path"]), "test_areas": area_counts(ba),
                         "tests": len(all_tests(ba)), "example_tests": sorted(all_tests(ba)),
                         "skip": {"file": sk["skip_file"], "name": sk.get("name"), "line": sk.get("line"),
                                  "reason": sk.get("reason"), "covered_by": sk.get("covered_by")} if sk else None})
        hits = []
        for key, ba in sorted(hit_groups.get(area, []),
                              key=lambda kv: (-len(all_tests(kv[1])), kv[0][1], str(kv[0][2]))):
            s = skip_index[key]
            hits.append({"skip_file": s["skip_file"], "kind": s.get("kind"), "name": s.get("name"), "file": s["file"],
                         "line": s.get("line"), "reason": s.get("reason"), "covered_by": s.get("covered_by"),
                         "owner": owner_of(s["file"]), "test_areas": area_counts(ba),
                         "tests": len(all_tests(ba)), "example_tests": sorted(all_tests(ba))})
        report["areas"][area] = {"tests": len(tests) if args.by == "owner" else tests_by_area[area],
                                 "testing_areas": dict(testing_areas.most_common()),
                                 "referenced": len(grp), "modeled": modeled,
                                 "unmodeled": len(unmodeled), "reach_pct": round(reach, 1),
                                 "gaps": gaps, "test_hit_skips": hits}
        write_md(os.path.join(out_dir, f"coverage-{area}.md"), area, report["areas"][area], args.top, args.by)
        if args.by == "owner":
            kind = "unowned" if area == "unowned" else "owned"
            print(f"{area}: {len(grp)} {kind} definitions referenced by {len(tests)} tests from "
                  f"{len(testing_areas)} area{'s' * (len(testing_areas) != 1)}, {modeled} modeled, {len(unmodeled)} unmodeled, "
                  f"function-level reach {reach:.0f}%, {len(hits)} test-hit skips")
        else:
            print(f"{area}: {len(grp)} definitions referenced by {tests_by_area[area]} tests, {modeled} modeled, "
                  f"{len(unmodeled)} unmodeled, function-level reach {reach:.0f}%, {len(hits)} test-hit skips")
    with open(os.path.join(out_dir, "coverage.json"), "w") as f:
        json.dump(report, f, indent=1)
        f.write("\n")
    if ambiguous:
        print(f"short-form cited paths matching several files, ignored: {ambiguous}")
    print("->", out_dir)


def md_cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def areas_cell(counts):
    return ", ".join(f"{a} ({n})" for a, n in counts.items())


def write_md(path, area, a, top, by):
    if by == "owner":
        who = ("code no profile area owns" if area == "unowned" else "code this area owns")
        head = (f"Definitions in {who} that any test references: {a['referenced']} "
                f"(by {a['tests']} tests from {len(a['testing_areas'])} areas: "
                f"{areas_cell(a['testing_areas']) or 'none'}); "
                f"modeled (cited): {a['modeled']}; unmodeled: {a['unmodeled']}. "
                f"Function-level reach: {a['reach_pct']:.0f}%.")
        rule = ("Rows are grouped by the area whose `owns` globs match the definition's file; the tests "
                "column counts tests from every area, and testing areas gives each area's count.")
    else:
        head = (f"Tests mapped to this area: {a['tests']}. Definitions the tests reference: {a['referenced']}; "
                f"modeled (cited): {a['modeled']}; unmodeled: {a['unmodeled']}. "
                f"Function-level reach: {a['reach_pct']:.0f}%.")
        rule = "Rows are grouped by the testing area; the owner column names the area that owns the code."
    L = [f"# Coverage gaps: {area}", "", head, "",
         "Generated by coverage_gaps.py. A definition is referenced when a test that targets its file names it "
         "(whole word), modeled when a model citation overlaps its lines. " + rule, "",
         f"## Top {min(top, len(a['gaps']))} unmodeled definitions", ""]
    col, colf = (("testing areas", lambda g: areas_cell(g["test_areas"])) if by == "owner"
                 else ("owner", lambda g: g["owner"]))
    if a["gaps"]:
        L += [f"| definition | name | tests | {col} | example tests | skip |", "|---|---|---|---|---|---|"]
        for g in a["gaps"][:top]:
            ex = ", ".join(f"`{t}`" for t in g["example_tests"][:3])
            sk = f"{g['skip']['file']}: {g['skip']['name']}" if g["skip"] else ""
            L.append(f"| `{g['path']}:{g['start']}-{g['end']}` | `{md_cell(g['name'])}` | {g['tests']} | "
                     f"{md_cell(colf(g))} | {ex} | {md_cell(sk)} |")
    else:
        L.append("None.")
    L += ["", f"## Test-hit skips ({len(a['test_hit_skips'])})", ""]
    if a["test_hit_skips"]:
        L += [f"| skip | entry | tests | {col} | example tests | reason |", "|---|---|---|---|---|---|"]
        for h in a["test_hit_skips"]:
            ex = ", ".join(f"`{t}`" for t in h["example_tests"][:3])
            cov = f" (covered by {h['covered_by']})" if h.get("covered_by") else ""
            L.append(f"| {h['skip_file']} | `{h['file']}:{h['line']}` {md_cell(h['name'])} | {h['tests']} | "
                     f"{md_cell(colf(h))} | {ex} | {md_cell(h['reason'])}{md_cell(cov)} |")
    else:
        L.append("None.")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])

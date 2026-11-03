#!/usr/bin/env python3
"""Map each of the repo's test files to the code it tests (DESIGN §13.1 item 19).

Usage: test_targets.py <workspace> [--max-share 0.1] [--out FILE] [-v]

Reads <workspace>/profile.yaml (`snapshot.path`, `oracle`, `areas`) and lists the test files the
way sample_tests.py does: `oracle.include` under `oracle.test_dirs`, minus `oracle.exclude`. For
each test file it finds the code under test, heuristically, by reading (never running) the file:

  - Python: `import a.b` and `from a.b import X` (ast). `X` resolves to the submodule a/b/X.py
    when there is one, else to the file defining X, following re-exports in __init__.py
    (`from .c import X` and lazy `"X": ".c:X"` tables) up to three levels.
  - TypeScript / JavaScript: `import ... from '<spec>'`, `export ... from`, `import('<spec>')`
    and `require('<spec>')` with a relative spec (or a `vs/...` path, VS Code's src root);
    `.js` resolves to `.ts`/`.tsx`, a directory to its `index.ts`.
  - Java: `import [static] a.b.C[.member];` resolved to the `a/b/C.java` source file, plus the
    class under test in the same package (FooTest -> Foo), which needs no import.
  - Go (no import resolution): the file in the test's own directory named like the test, dropping
    trailing name words until one exists (admin_list_e2e_test.go -> admin_list.go); then the
    same-directory non-test files declaring the identifiers the test uses (top-level funcs without a
    receiver, types, vars and consts of more than two characters), the top three by hit count.
  - Other languages: the source file named like the test (test_scheduler.py -> scheduler.py,
    textModel.test.ts -> textModel.ts), when at most three non-test files have that name
    (preferring those in the test's area).

Imports of small test helpers (files under the test dirs importing at most ten source files) are
followed one level, so a test that builds its subject through a helper (createTextModel) still
reaches the subject; a large harness (workbenchTestServices) says nothing about the subject. Targets are source files
under the snapshot outside the test dirs. A target imported by more than --max-share of all test
files (a platform shim, a logging or lifecycle utility) is dropped from tests that have other
targets: it says nothing about what a test exercises. A target named like the test is always kept.

The area is `oracle.area_globs`, else the area owning the test's path by the profile's globs, else
the area owning most of its targets.

With `oracle.colocated: true` (tests sit next to their code, so `test_dirs` covers source too),
test code is decided by file name (`*_test.go`, `*.test.ts(x)`, `*.spec.ts`, `test_*.py`,
`*_test.py`, the include globs, */test/ and */tests/ dirs) instead of by being under a test dir.

Writes <workspace>/test-targets.json (or --out): [{test, targets: [paths], area}], sorted by test,
and prints how many tests resolved at least one target, in total and per area.
"""
import argparse
import ast
import collections
import fnmatch
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from assign_inventory import owner  # noqa: E402

PY_EXT = (".py",)
TS_EXT = (".ts", ".tsx", ".js", ".mjs", ".cjs", ".jsx")
JAVA_EXT = (".java",)
SRC_EXT = PY_EXT + TS_EXT + JAVA_EXT + (".go", ".kt", ".scala", ".rs", ".c", ".cc", ".cpp", ".cu", ".h", ".hpp", ".cuh")
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "build", "out", "dist", "target"}

TS_IMPORT = re.compile(
    r"""(?:\bimport\s+(?:type\s+)?(?:[^'"`;]*?\bfrom\s*)?|\bexport\s+[^'"`;]*?\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*)(['"])([^'"]+)\1""")
JAVA_IMPORT = re.compile(r"^\s*import\s+(static\s+)?([\w.]+)(\.\*)?\s*;", re.M)
JAVA_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
GO_DECL = re.compile(r"^(?:func\s+([A-Za-z_]\w*)|(?:type|var|const)\s+([A-Za-z_]\w*))", re.M)
GO_BLOCK = re.compile(r"^(?:type|var|const)\s*\((.*?)^\)", re.M | re.S)
GO_IDENT = re.compile(r"(?<![.\w])[A-Za-z_]\w*")
TEST_NAMES = ("*_test.go", "*.test.ts", "*.test.tsx", "*.spec.ts", "test_*.py", "*_test.py")
LAZY_ATTR = re.compile(r"""['"](\w+)['"]\s*:\s*['"](\.?[\w.]*):(\w+)['"]""")


def in_dirs(rel, dirs):
    return any(fnmatch.fnmatch(rel, d + "/**") or fnmatch.fnmatch(rel, d + "/*") or rel == d for d in dirs)


class Snapshot:
    def __init__(self, prof):
        self.prof = prof
        self.root = prof["snapshot"]["path"]
        o = prof["oracle"]
        self.test_dirs = o["test_dirs"]
        self.include = o["include"]
        self.colocated = bool(o.get("colocated"))
        self.exclude = o.get("exclude", [])
        self.files = set()
        for dirpath, dirnames, names in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel_dir = os.path.relpath(dirpath, self.root)
            for n in names:
                if n.endswith(SRC_EXT):
                    self.files.add(os.path.normpath(os.path.join(rel_dir, n)))
        self.by_stem = collections.defaultdict(list)
        self.java = collections.defaultdict(list)  # "a/b/C.java" basename -> paths
        for f in self.files:
            if self.is_test_path(f):
                continue
            base = os.path.basename(f)
            self.by_stem[os.path.splitext(base)[0]].append(f)
            if f.endswith(".java"):
                self.java[base].append(f)
        self._py_cache = {}
        self._go_decls = {}
        self._go_dirs = None

    def is_test(self, rel):
        return (any(fnmatch.fnmatch(rel, p) for p in self.include) and in_dirs(rel, self.test_dirs)
                and not any(fnmatch.fnmatch(rel, p) for p in self.exclude))

    def is_test_path(self, rel):
        """Test code: anything under a test dir (unless oracle.colocated, where test files are
        told by name) or a */test/ or */tests/ directory, or a test file."""
        if self.colocated:
            if any(fnmatch.fnmatch(os.path.basename(rel), p) for p in TEST_NAMES):
                return True
        elif in_dirs(rel, self.test_dirs):
            return True
        parts = rel.split("/")
        if any(p in ("test", "tests", "__tests__") for p in parts[:-1]):
            return True
        return any(fnmatch.fnmatch(rel, p) for p in self.include)

    def tests(self):
        return sorted(f for f in self.files if self.is_test(f))

    def text(self, rel):
        try:
            return open(os.path.join(self.root, rel), errors="replace").read()
        except OSError:
            return ""

    # --- Python -------------------------------------------------------------------------------

    def py_module(self, mod):
        """The file of a dotted module: a/b.py or a/b/__init__.py (also under src/)."""
        p = mod.replace(".", "/")
        for pre in ("", "src/"):
            for cand in (pre + p + ".py", pre + p + "/__init__.py"):
                if cand in self.files:
                    return cand
        return None

    def py_parse(self, rel):
        if rel not in self._py_cache:
            try:
                self._py_cache[rel] = ast.parse(self.text(rel))
            except (SyntaxError, ValueError):
                self._py_cache[rel] = None
        return self._py_cache[rel]

    @staticmethod
    def py_package(rel):
        d = os.path.dirname(rel)
        return d.replace("/", ".")

    def py_absolute(self, rel, module, level):
        if level == 0:
            return module or ""
        pkg = self.py_package(rel).split(".") if self.py_package(rel) else []
        if rel.endswith("__init__.py"):
            level -= 1
        else:
            level -= 1
        base = pkg[: len(pkg) - level] if level else pkg
        return ".".join([*base, *([module] if module else [])])

    def py_symbol(self, mod, name, depth=0):
        """The file defining `name` imported from module `mod`."""
        sub = self.py_module(mod + "." + name) if mod else None
        if sub:
            return sub
        f = self.py_module(mod) if mod else None
        if not f or depth > 3:
            return f
        tree = self.py_parse(f)
        if tree is None:
            return f
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                return f
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return f
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any((a.asname or a.name) == name for a in node.names):
                src = self.py_absolute(f, node.module, node.level)
                orig = next(a.name for a in node.names if (a.asname or a.name) == name)
                return self.py_symbol(src, orig, depth + 1) or f
        m = next((m for m in LAZY_ATTR.finditer(self.text(f)) if m.group(1) == name), None)
        if m:
            spec = m.group(2)
            src = self.py_absolute(f, spec.lstrip("."), len(spec) - len(spec.lstrip("."))) if spec.startswith(".") else spec
            return self.py_symbol(src, m.group(3), depth + 1) or f
        return f

    def py_imports(self, rel):
        tree = self.py_parse(rel)
        out = []
        if tree is None:
            return out
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    f = self.py_module(a.name)
                    if f:
                        out.append(f)
            elif isinstance(node, ast.ImportFrom):
                mod = self.py_absolute(rel, node.module, node.level)
                for a in node.names:
                    f = self.py_symbol(mod, a.name) if a.name != "*" else self.py_module(mod)
                    if f:
                        out.append(f)
        return out

    # --- TypeScript ---------------------------------------------------------------------------

    def ts_resolve(self, rel, spec):
        if spec.startswith("."):
            base = os.path.normpath(os.path.join(os.path.dirname(rel), spec))
        elif spec.startswith("vs/"):
            base = "src/" + spec
        else:
            return None
        stem = re.sub(r"\.(js|mjs|cjs|jsx|ts)$", "", base)
        for cand in (base, stem + ".ts", stem + ".tsx", stem + ".js", stem + "/index.ts", stem + "/index.js"):
            if cand in self.files:
                return cand
        return None

    def ts_imports(self, rel):
        out = []
        for m in TS_IMPORT.finditer(self.text(rel)):
            f = self.ts_resolve(rel, m.group(2))
            if f:
                out.append(f)
        return out

    # --- Java ---------------------------------------------------------------------------------

    def java_class(self, qualified):
        parts = qualified.split(".")
        # a.b.C, a.b.C.Inner or (static) a.b.C.member: the longest prefix naming a file.
        for n in range(len(parts), 0, -1):
            tail = "/".join(parts[:n]) + ".java"
            for f in self.java.get(parts[n - 1] + ".java", []):
                if f.endswith("/" + tail) or f == tail:
                    return f
        return None

    def java_imports(self, rel):
        text = self.text(rel)
        out = []
        for m in JAVA_IMPORT.finditer(text):
            if m.group(3):
                continue
            f = self.java_class(m.group(2))
            if f:
                out.append(f)
        pkg = JAVA_PACKAGE.search(text)
        stem = os.path.splitext(os.path.basename(rel))[0]
        subject = re.sub(r"(Tests?|IT)$", "", re.sub(r"^Test", "", stem))
        if pkg and subject:
            f = self.java_class(pkg.group(1) + "." + subject)
            if f:
                out.append(f)
        return out

    # --- Go -----------------------------------------------------------------------------------

    def go_decls(self, d):
        """name -> declaring file over the non-test, non-generated .go files of directory d."""
        if d not in self._go_decls:
            idx = {}
            if self._go_dirs is None:
                self._go_dirs = collections.defaultdict(list)
                for f in sorted(self.files):
                    if f.endswith(".go"):
                        self._go_dirs[os.path.dirname(f)].append(f)
            for f in self._go_dirs.get(d, []):
                if f.endswith(".gen.go") or self.is_test_path(f):
                    continue
                text = self.text(f)
                names = [m.group(1) or m.group(2) for m in GO_DECL.finditer(text)]
                for b in GO_BLOCK.finditer(text):
                    for line in b.group(1).splitlines():
                        m = re.match(r"\s*([A-Za-z_]\w*)", line)
                        if m:
                            names.append(m.group(1))
                for n in names:
                    if len(n) > 2:
                        idx.setdefault(n, f)
            self._go_decls[d] = idx
        return self._go_decls[d]

    def go_imports(self, rel):
        """The same-directory files declaring the identifiers the test uses, top three by hits."""
        idx = self.go_decls(os.path.dirname(rel))
        text = re.sub(r"//[^\n]*", "", self.text(rel))
        hits = collections.Counter(idx[i] for i in GO_IDENT.findall(text) if i in idx)
        return [f for f, _ in sorted(hits.items(), key=lambda x: (-x[1], x[0]))[:3]]

    def go_by_name(self, rel):
        """The file in the test's directory named like it, dropping trailing name words."""
        d = os.path.dirname(rel)
        parts = os.path.basename(rel)[: -len("_test.go")].split("_")
        while parts:
            cand = os.path.normpath(os.path.join(d, "_".join(parts) + ".go"))
            if cand in self.files and not self.is_test_path(cand):
                return [cand]
            parts.pop()
        return []

    # --- all ----------------------------------------------------------------------------------

    def imports(self, rel):
        if rel.endswith(PY_EXT):
            return self.py_imports(rel)
        if rel.endswith(TS_EXT):
            return self.ts_imports(rel)
        if rel.endswith(JAVA_EXT):
            return self.java_imports(rel)
        if rel.endswith("_test.go"):
            return self.go_imports(rel)
        return []

    def by_name(self, rel, area):
        """Non-test files named like the test file's subject, at most three."""
        if rel.endswith("_test.go"):
            return self.go_by_name(rel)
        stem = os.path.basename(rel)
        stem = re.sub(r"\.(test|spec|integrationTest|perf\.test)\.\w+$", "", stem)
        stem = os.path.splitext(stem)[0]
        stem = re.sub(r"^test_|_test$|(Tests?|IT)$", "", stem)
        if not stem:
            return []
        ext = os.path.splitext(rel)[1]
        family = PY_EXT if ext in PY_EXT else TS_EXT if ext in TS_EXT else JAVA_EXT if ext in JAVA_EXT else (ext,)
        cands = [f for f in self.by_stem.get(stem, []) if f.endswith(family)]
        if len(cands) > 3 and area:
            cands = [f for f in cands if owner(f, self.prof["areas"]) == area]
        return sorted(cands) if 0 < len(cands) <= 3 else []


def test_area(prof, rel):
    a = next((g["area"] for g in prof["oracle"].get("area_globs", []) if fnmatch.fnmatch(rel, g["glob"])), None)
    return a or owner(rel, prof["areas"])


def targets_of(snap, rel, area, max_helper=10):
    """The test's targets: (imported, named). Named targets (the file named like the test) are
    never dropped as common."""
    out, helpers = [], []
    for f in snap.imports(rel):
        (helpers if snap.is_test_path(f) else out).append(f)
    for h in dict.fromkeys(helpers):  # one level through small test helpers
        via = [f for f in dict.fromkeys(snap.imports(h)) if not snap.is_test_path(f)]
        if len(via) <= max_helper:
            out += via
    named = [f for f in snap.by_name(rel, area) if f != rel]
    return [f for f in dict.fromkeys(out) if f != rel and f not in named], named


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("workspace")
    ap.add_argument("--max-share", type=float, default=0.1,
                    help="drop a target imported by more than this share of test files (when the test has others)")
    ap.add_argument("--out", default=None, help="output file (default <workspace>/test-targets.json)")
    ap.add_argument("-v", action="store_true", help="list the dropped common targets")
    args = ap.parse_args(argv)
    ws = args.workspace
    prof = yaml.safe_load(open(os.path.join(ws, "profile.yaml")))
    snap = Snapshot(prof)
    rows = []
    for t in snap.tests():
        area = test_area(prof, t)
        imported, named = targets_of(snap, t, area)
        rows.append({"test": t, "targets": imported, "area": area, "named": named})
    freq = collections.Counter(f for r in rows for f in r["targets"])
    common = {f for f, n in freq.items() if n > args.max_share * len(rows)}
    for r in rows:
        named = r.pop("named")
        kept = [f for f in r["targets"] if f not in common]
        r["targets"] = sorted(set(kept + named)) or sorted(r["targets"])
        if not r["area"]:
            owners = collections.Counter(owner(f, prof["areas"]) for f in r["targets"])
            owners.pop(None, None)
            r["area"] = owners.most_common(1)[0][0] if owners else ""
    out = args.out or os.path.join(ws, "test-targets.json")
    json.dump(rows, open(out, "w"), indent=1)
    open(out, "a").write("\n")
    per = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        per[r["area"] or "(none)"][1] += 1
        per[r["area"] or "(none)"][0] += bool(r["targets"])
    res = sum(v[0] for v in per.values())
    print(f"test files: {len(rows)}, resolved to at least one target: {res} ({100 * res / max(len(rows), 1):.0f}%), "
          f"mean targets per resolved test: {sum(len(r['targets']) for r in rows) / max(res, 1):.1f}")
    print(f"common targets dropped (imported by > {args.max_share:.0%} of tests): {len(common)}"
          + (": " + ", ".join(sorted(common)) if args.v else ""))
    for a, (n, d) in sorted(per.items()):
        print(f"  {a}: {n}/{d} resolved ({100 * n / max(d, 1):.0f}%)")
    print("->", out)


if __name__ == "__main__":
    main(sys.argv[1:])

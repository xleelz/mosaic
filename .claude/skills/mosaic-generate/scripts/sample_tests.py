#!/usr/bin/env python3
"""Pick test-oracle samples: the in-build sample per area (stage 4b) and the final sample (stage 6).

Usage:
  sample_tests.py <workspace> --area <id> [--area <id>...] [-n 3] [--seed S]   # stage 4b
  sample_tests.py <workspace> [--exclude-sample FILE...] [--unit-share F] [--out FILE]   # stage 6
  both modes also take [--unit file|function] [--min-size N] [--reach-from TARGETS.json...
  [--scope-paths FILE]]

Reads <workspace>/profile.yaml (`oracle`, `areas`, `snapshot.path`). It lists the test files
matching `oracle.include` under `oracle.test_dirs`, minus `oracle.exclude`, and assigns each to
the area owning it: `oracle.area_globs` first (for repos whose tests live apart from the code), else
the area owning the path by the profile's globs.
Each test file contributes one named test case, the first `test(`/`it(`/`def test_`/`@Test`/Go
`func TestXxx(t *testing.T)` in the file.

Sampling unit (--unit). `file` (the default) draws test files, one case each, as above. `function`
draws test functions: the pool is every case in the mapped test files (Go `func TestX`, Python
`def test_x`, TS/JS `it(`/`test(`, Java `@Test` methods), so a component-scope run whose scope maps
to a handful of files still has a pool after the build oracles; --exclude-sample then leaves out
(file, name) pairs, not whole files. With no --unit, a sample that would come back empty, or hold
fewer than --min-size N tests, is redrawn by function (said on stderr), and in function mode the
sample size is at least N. --unit file never switches.

Parent tests reaching the scope (--reach-from, repeatable). A child run (DESIGN §14) adds the tests
of a parent's test-targets.json whose targets include any of the scope's paths: --scope-paths FILE
(one path or glob per line, or a JSON list), else the profile's `inventory.scope_paths`, else its
areas' `owns`. A reached test joins the area that oracle.area_globs or the profile's globs give
it, else the area owning the scope path it reaches; `oracle.exclude` still applies, and tests
missing from the snapshot are skipped.

Stage 6 (no --area): draws a seeded sample (`oracle.sample.seed`) of at least `per_area_min` tests
per area and `total` overall, and writes <workspace>/oracle/sample.json (or --out): {area: [{file,
line, name, unit}]}. --exclude-sample (repeatable; each FILE is a sample written by either mode)
leaves out every test file (by function: every (file, name)) already sampled, so the final oracle never reuses a test an area agent
translated during the build, nor one an earlier round's oracle scored (DESIGN §13.1 item 31).

Unit weighting (item 31): a test is a **unit test** when code its area owns sits in the test's own
directory, or where the language's convention puts the code it tests: the directory with one
`test`/`tests`/`__tests__` component removed (src/vs/editor/test/common/x.test.ts ->
src/vs/editor/common/), or any directory ending in that remainder when it has two or more parts
(tests/v1/core -> vllm/v1/core); a project's own tests dir (services/x/tests/test_a.py) reaches
its package one or two levels down (services/x/x_pkg/, services/x/src/x_pkg/); for Java, any
source directory of the test's package. Source and
test files are told apart as in test_targets.py. --unit-share F draws that share of unit tests,
both within each area's minimum and overall; the default is the share of unit tests among all
mapped tests, so the sample tests the unit-level rules (rounding, job specs, startup checks) as
often as the repo does. The script prints the share it achieved.

Stage 4b (--area): for each named area, draws -n tests (default `oracle.sample.build_n`, else 3)
from that area's own paths, with a different seed (`--seed`, default `oracle.sample.build_seed`,
else `oracle.sample.seed` + 1000), and writes <workspace>/build-oracle/<area>.json: [{file, line,
name}]. Area agents may read their own file; it is not under oracle/, which builders never read.
"""
import argparse
import fnmatch
import glob
import json
import os
import random
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from assign_inventory import owner  # noqa: E402
from test_targets import JAVA_PACKAGE, Snapshot  # noqa: E402

TEST_DIR_PARTS = ("test", "tests", "__tests__")

CASE = re.compile(r"""^\s*(?:test|it)\s*\(\s*(['"`])(.+?)\1|^\s*def (test_\w+)|^\s*@Test"""
                  r"""|^func (Test\w+)\(\s*\w+ \*testing\.T\)""", re.M)


def test_files(prof):
    root = prof["snapshot"]["path"]
    o = prof["oracle"]
    files = []
    for dirpath, _, names in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if "node_modules" in rel_dir.split(os.sep):
            continue
        for n in names:
            rel = os.path.normpath(os.path.join(rel_dir, n))
            if not any(fnmatch.fnmatch(rel, p) for p in o["include"]):
                continue
            if not any(fnmatch.fnmatch(rel, d + "/**") or fnmatch.fnmatch(rel, d + "/*") for d in o["test_dirs"]):
                continue
            if any(fnmatch.fnmatch(rel, p) for p in o.get("exclude", [])):
                continue
            files.append(rel)
    # Repos that keep tests apart from code (tests/...) map test paths to areas explicitly:
    # oracle.area_globs: [{glob, area}], most specific glob first; otherwise the code owner.
    area_globs = prof["oracle"].get("area_globs", [])
    by_area = {}
    for f in sorted(files):
        a = next((g["area"] for g in area_globs if fnmatch.fnmatch(f, g["glob"])), None) or owner(f, prof["areas"])
        if a:
            by_area.setdefault(a, []).append(f)
    return by_area


FUNC = re.compile(r"""^\s*(?:test|it)\s*\(\s*(['"`])(.+?)\1|^\s*(?:async\s+)?def (test_\w+)"""
                  r"""|^\s*@Test\b(?:\([^)]*\))?\s*(?:@[\w.]+(?:\([^)]*\))?\s*)*(?:(?:public|protected|private|static|final)\s+)*"""
                  r"""(?:void|fun)\s+(\w+)|^func (Test\w+)\(\s*\w+ \*testing\.T\)""", re.M)


def functions(root, f):
    """Every test function in the file: [(file, line, name)]."""
    text = open(os.path.join(root, f), errors="replace").read()
    out = []
    for m in FUNC.finditer(text):
        name = m.group(2) or m.group(3) or m.group(4) or m.group(5)
        out.append((f, text[: m.start()].count("\n") + 1, name))
    return out


def case(root, f):
    text = open(os.path.join(root, f), errors="replace").read()
    m = CASE.search(text)
    line = text[: m.start()].count("\n") + 1 if m else 1
    name = (m.group(2) or m.group(3) or m.group(4) or "test") if m else "test"
    return {"file": f, "line": line, "name": name}


def excluded(paths):
    """Tests named in earlier samples: {area: [...]} or [...] JSON files, globs allowed.
    Returns (files, (file, name) pairs)."""
    files, pairs = set(), set()
    for p in paths:
        matches = sorted(glob.glob(p)) or [p]
        for f in matches:
            d = json.load(open(f))
            items = [x for v in d.values() for x in v] if isinstance(d, dict) else d
            files.update(x["file"] for x in items)
            pairs.update((x["file"], x["name"]) for x in items)
    return files, pairs


def scope_paths(prof, path=None):
    if path:
        text = open(path).read()
        try:
            v = json.loads(text)
        except ValueError:
            v = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        return list(v)
    sp = (prof.get("inventory") or {}).get("scope_paths")
    return list(sp) if sp else [g for a in prof["areas"] for g in a["owns"]]


def reach(prof, by_area, targets_files, scope):
    """Add the tests of each parent test-targets.json whose targets include a scope path."""
    root = prof["snapshot"]["path"]
    exclude = prof["oracle"].get("exclude", [])
    have = {f for fs in by_area.values() for f in fs}
    for tf in targets_files:
        added = missing = 0
        for row in json.load(open(tf)):
            t = row["test"]
            hit = [x for x in row.get("targets", []) if any(fnmatch.fnmatch(x, p) for p in scope)]
            if not hit or t in have or any(fnmatch.fnmatch(t, p) for p in exclude):
                continue
            if not os.path.isfile(os.path.join(root, t)):
                missing += 1
                continue
            a = (next((g["area"] for g in prof["oracle"].get("area_globs", []) if fnmatch.fnmatch(t, g["glob"])), None)
                 or owner(t, prof["areas"]) or next((owner(x, prof["areas"]) for x in hit if owner(x, prof["areas"])), None))
            if not a and len(prof["areas"]) == 1:
                a = prof["areas"][0]["id"]
            if not a:
                continue
            by_area.setdefault(a, []).append(t)
            have.add(t)
            added += 1
        print(f"reach-from {tf}: {added} test files reach the scope"
              + (f" ({missing} missing from the snapshot)" if missing else ""), file=sys.stderr)
    for a in by_area:
        by_area[a].sort()
    return by_area


def pool_of(root, fs, unit):
    """The sampling pool for these test files: the files, or their (file, line, name) functions."""
    return list(fs) if unit == "file" else [k for f in fs for k in functions(root, f)]


def file_of(k):
    return k if isinstance(k, str) else k[0]


def describe(root, k):
    return case(root, k) if isinstance(k, str) else {"file": k[0], "line": k[1], "name": k[2]}


def build_sample(ws, prof, by_area, areas, n, seed, unit=None, min_size=1):
    root = prof["snapshot"]["path"]
    os.makedirs(os.path.join(ws, "build-oracle"), exist_ok=True)
    for a in areas:
        if a not in {x["id"] for x in prof["areas"]}:
            sys.exit(f"sample_tests: unknown area {a!r}")
        fs = by_area.get(a, [])
        mode, k = unit or "file", n
        if unit is None and min(n, len(fs)) < min_size:
            mode, k = "function", max(n, min_size)
            print(f"sample_tests: {a}: {min(n, len(fs))} test files < {min_size}; sampling by test function",
                  file=sys.stderr)
        pool = pool_of(root, fs, mode)
        # One generator per area, seeded from the seed and the area id, so an area's sample
        # doesn't depend on which other areas were asked for in the same run.
        rng = random.Random(f"{seed}:{a}")
        picked = rng.sample(pool, min(k, len(pool)))
        out = [describe(root, x) for x in picked]
        path = os.path.join(ws, "build-oracle", a + ".json")
        json.dump(out, open(path, "w"), indent=2)
        what = "test files" if mode == "file" else f"test functions in {len(fs)} files"
        print(f"{a}: {len(out)} of {len(pool)} {what} -> {path}")


class Units:
    """Tells unit tests from the rest: does code the test's area owns sit where the test is?"""

    def __init__(self, prof):
        self.prof = prof
        self.snap = Snapshot(prof)
        self.code_dirs = {}  # dir -> set of areas owning a non-test source file there
        for f in self.snap.files:
            if self.snap.is_test_path(f):
                continue
            a = owner(f, prof["areas"])
            if a:
                self.code_dirs.setdefault(os.path.dirname(f), set()).add(a)
        self._suffix = {}
        self._pkgs = {}

    def dirs_ending(self, tail):
        if tail not in self._suffix:
            self._suffix[tail] = [d for d in self.code_dirs if d == tail or d.endswith("/" + tail)]
        return self._suffix[tail]

    def packages(self, project):
        if project not in self._pkgs:
            self._pkgs[project] = [d for d in self.code_dirs if d.startswith(project + "/")
                                     and 1 <= d.count("/") - project.count("/") <= 2]
        return self._pkgs[project]

    def candidates(self, test):
        d = os.path.dirname(test)
        out = [d]
        parts = d.split("/") if d else []
        i = next((i for i, p in enumerate(parts) if p in TEST_DIR_PARTS), None)
        if i is not None:
            rest = parts[i + 1:]
            out.append("/".join(parts[:i] + rest))
            if len(rest) >= 2:
                out += self.dirs_ending("/".join(rest))
            if i > 0:  # a project's own tests/ dir: its package, <project>/<pkg> or <project>/src/<pkg>
                out += self.packages("/".join(parts[:i]))
        if test.endswith(".java"):
            m = JAVA_PACKAGE.search(self.snap.text(test))
            if m:
                out += self.dirs_ending(m.group(1).replace(".", "/"))
        return out

    def is_unit(self, test, area):
        return any(area in self.code_dirs.get(d, ()) for d in self.candidates(test))


def final_sample(ws, prof, by_area, skip, unit_share=None, out_path=None, unit_mode=None, min_size=1):
    root = prof["snapshot"]["path"]
    units = Units(prof)
    unit_files = {f for a, fs in by_area.items() for f in fs if units.is_unit(f, a)}
    total = prof["oracle"]["sample"].get("total", 40)
    mode = unit_mode or "file"
    res = draw(prof, by_area, skip, unit_files, unit_share, mode, total)
    if unit_mode is None and res[1] < min_size:
        print(f"sample_tests: the file sample holds {res[1]} tests (< {min_size}); sampling by test function",
              file=sys.stderr)
        mode = "function"
    if mode == "function":
        res = draw(prof, by_area, skip, unit_files, unit_share, mode, max(total, min_size))
    picked, n, n_unit, pools, unit, repo_share, share, nskip = res
    out = {}
    for a, ks in picked.items():
        for k in ks:
            out.setdefault(a, []).append({**describe(root, k), "unit": k in unit})
    path = out_path or os.path.join(ws, "oracle", "sample.json")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    json.dump(out, open(path, "w"), indent=2)
    open(path, "a").write("\n")
    mapped = sum(len(v) for v in pools.values())
    if mode == "function":
        print(f"sampling by test function: {mapped} functions in {sum(len(fs) for fs in by_area.values())} "
              f"test files, {mapped - nskip} not yet sampled")
    print(f"unit share: repo {repo_share:.2f} ({len(unit)} of {mapped} mapped tests), target {share:.2f}, "
          f"achieved {n_unit / max(n, 1):.2f} ({n_unit} of {n}); "
          f"excluded {len(skip[0]) if mode == 'file' else nskip}")
    print(f"{'area':<24} {'sampled':>7} {'unit':>5} {'available':>9} {'unit avail':>10}")
    for a in sorted(pools):
        v = out.get(a, [])
        avail = [k for k in pools[a] if not is_skipped(k, skip)]
        print(f"{a:<24} {len(v):>7} {sum(c['unit'] for c in v):>5} {len(avail):>9} "
              f"{sum(k in unit for k in avail):>10}")
    print("->", path)


def is_skipped(k, skip):
    return k in skip[0] if isinstance(k, str) else (k[0], k[2]) in skip[1]


def draw(prof, by_area, skip, unit_files, unit_share, mode, total):
    """One seeded draw over files or functions. Returns (picked, n, n_unit, all pools by area,
    unit keys, repo share, target share, number of mapped keys excluded)."""
    root = prof["snapshot"]["path"]
    o = prof["oracle"]
    all_keys = {a: pool_of(root, fs, mode) for a, fs in by_area.items()}
    unit = {k for ks in all_keys.values() for k in ks if file_of(k) in unit_files}
    mapped = sum(len(ks) for ks in all_keys.values())
    repo_share = len(unit) / max(mapped, 1)
    share = repo_share if unit_share is None else unit_share
    if not 0 <= share <= 1:
        sys.exit("sample_tests: --unit-share must be between 0 and 1")
    nskip = sum(is_skipped(k, skip) for ks in all_keys.values() for k in ks)
    by_area = {a: [k for k in ks if not is_skipped(k, skip)] for a, ks in all_keys.items()}
    rng = random.Random(o["sample"].get("seed", 1))
    per = o["sample"].get("per_area_min", 3)

    def take(pool, k):
        k = min(k, len(pool))
        got = rng.sample(pool, k)
        for f in got:
            pool.remove(f)
        return got

    # Each area's minimum keeps the stratification; its unit quota is per * share, the fraction
    # rounded at random so the quotas add up to the share on average. A short pool lends to the other.
    pools = {a: ([f for f in fs if f in unit], [f for f in fs if f not in unit]) for a, fs in sorted(by_area.items())}
    picked = {}
    for a, (u, other) in pools.items():
        k = min(per, len(u) + len(other))
        ku = min(int(per * share + rng.random()), len(u), k)
        ku = max(ku, k - len(other))
        picked[a] = take(u, ku) + take(other, k - ku)
    # The rest: units until the overall share is reached, then the others, each drawn across
    # areas in proportion to what they have left.
    rest_u = [(a, f) for a, (u, _) in pools.items() for f in u]
    rest_o = [(a, f) for a, (_, other) in pools.items() for f in other]
    rng.shuffle(rest_u)
    rng.shuffle(rest_o)
    n = sum(len(v) for v in picked.values())
    n_unit = sum(f in unit for v in picked.values() for f in v)
    target = round(share * total)
    while n < total and (rest_u or rest_o):
        src = rest_u if (n_unit < target and rest_u) or not rest_o else rest_o
        a, f = src.pop()
        picked[a].append(f)
        n += 1
        n_unit += f in unit
    return picked, n, n_unit, all_keys, unit, repo_share, share, nskip


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("workspace")
    ap.add_argument("--area", action="append", default=[], help="stage 4b: sample this area's own tests (repeatable)")
    ap.add_argument("-n", type=int, default=None, help="stage 4b: tests per area")
    ap.add_argument("--seed", default=None, help="stage 4b: seed (default oracle.sample.build_seed, else seed + 1000)")
    ap.add_argument("--exclude-sample", action="append", default=[], metavar="FILE",
                    help="stage 6: leave out the test files of this earlier sample (repeatable, globs allowed)")
    ap.add_argument("--unit-share", type=float, default=None, metavar="F",
                    help="stage 6: share of unit tests to draw (default: their share among all mapped tests)")
    ap.add_argument("--out", default=None, metavar="FILE",
                    help="stage 6: write the sample here (default <workspace>/oracle/sample.json)")
    ap.add_argument("--unit", choices=("file", "function"), default=None,
                    help="draw test files (one case each) or test functions (default: file, switching to "
                         "function when the sample would be empty or smaller than --min-size)")
    ap.add_argument("--min-size", type=int, default=1, metavar="N",
                    help="with no --unit: redraw by test function when the file sample holds fewer than N tests")
    ap.add_argument("--reach-from", action="append", default=[], metavar="TARGETS",
                    help="add the tests of this parent test-targets.json that reach the scope's paths (repeatable)")
    ap.add_argument("--scope-paths", default=None, metavar="FILE",
                    help="the scope's paths or globs, one per line or a JSON list "
                         "(default: profile inventory.scope_paths, else the areas' owns)")
    args = ap.parse_args(argv)
    ws = args.workspace
    prof = yaml.safe_load(open(os.path.join(ws, "profile.yaml")))
    s = prof["oracle"]["sample"]
    by_area = test_files(prof)
    if args.scope_paths and not args.reach_from:
        sys.exit("sample_tests: --scope-paths needs --reach-from")
    if args.reach_from:
        by_area = reach(prof, by_area, args.reach_from, scope_paths(prof, args.scope_paths))
    if args.area:
        if args.exclude_sample or args.unit_share is not None or args.out:
            sys.exit("sample_tests: --exclude-sample, --unit-share and --out apply to the final sample, not --area")
        n = args.n if args.n is not None else s.get("build_n", 3)
        seed = args.seed if args.seed is not None else s.get("build_seed", s.get("seed", 1) + 1000)
        build_sample(ws, prof, by_area, args.area, n, seed, args.unit, args.min_size)
    else:
        final_sample(ws, prof, by_area, excluded(args.exclude_sample), args.unit_share, args.out,
                     args.unit, args.min_size)


if __name__ == "__main__":
    main(sys.argv[1:])

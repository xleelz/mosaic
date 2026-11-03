#!/usr/bin/env python3
"""Rerun every area generator of a workspace until a pass changes nothing (DESIGN §15.2).

    regen.py <workspace> [--copy AREA,...] [--max-passes 3] [--cwd DIR] [--dry-run]

Generators are gen/<area>/build.py, gen/<area>/gen.py or gen/<area>/generate.py (the
first found). A generator is copy-based when its fragment copies other areas'
contracts: it (or a sibling module it imports) reads the workspace's fragments
directory other than to write its own <area>.yaml. --copy AREA,... names the
copy-based generators instead of detecting them.

Each pass runs the owners first, then the copy-based generators, so copies see the
owners' fresh contracts. The script hashes every workspace file outside gen/
(fragments, skips, ...) before and after each generator, and stops after the first
pass that changes no file's content, or after --max-passes (default 3). It reports
which generator changed which files in each pass, and what changed in total.

Exit status: 0 when a pass changed nothing, 1 when the last pass still changed files,
2 when a generator failed.
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
import time

NAMES = ("build.py", "gen.py", "generate.py")
SKIP_DIRS = {"gen", "__pycache__", "node_modules"}


def discover(ws):
    gen = os.path.join(ws, "gen")
    out = []
    if not os.path.isdir(gen):
        return out
    for area in sorted(os.listdir(gen)):
        d = os.path.join(gen, area)
        if not os.path.isdir(d) or area.startswith((".", "_")):
            continue
        for n in NAMES:
            if os.path.isfile(os.path.join(d, n)):
                out.append((area, os.path.join(d, n)))
                break
    return out


IMPORT_RE = re.compile(r"^\s*(?:from\s+([A-Za-z_]\w*)\s+import|import\s+([A-Za-z_][\w, ]*))")
FRAG_RE = re.compile(r"""fragments(?:/|["'])""")


def local_modules(script):
    """The script and the sibling modules it imports, transitively."""
    d = os.path.dirname(script)
    seen, todo = [], [script]
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.append(f)
        try:
            text = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for line in text.splitlines():
            m = IMPORT_RE.match(line)
            if not m:
                continue
            names = [m.group(1)] if m.group(1) else [n.strip().split(" ")[0] for n in m.group(2).split(",")]
            for n in names:
                p = os.path.join(d, n + ".py")
                if n and os.path.isfile(p):
                    todo.append(p)
    return seen


def copy_reason(area, script):
    """Where a generator reads other areas' fragments, or None."""
    own = area + ".yaml"
    for f in local_modules(script):
        try:
            lines = open(f, encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith("#") or not FRAG_RE.search(s) or own in s:
                continue
            return "%s:%d: %s" % (os.path.relpath(f, os.path.dirname(script)), i, s[:100])
    return None


def snapshot(ws, cache):
    """Content hashes of the workspace files outside gen/ and hidden directories."""
    out = {}
    for root, dirs, files in os.walk(ws):
        rel_root = os.path.relpath(root, ws)
        dirs[:] = sorted(
            x for x in dirs
            if not x.startswith(".") and x not in ("__pycache__", "node_modules") and not (rel_root == "." and x == "gen")
        )
        for n in files:
            p = os.path.join(root, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            key = (p, st.st_size, st.st_mtime_ns)
            h = cache.get(key)
            if h is None:
                with open(p, "rb") as fh:
                    h = hashlib.sha256(fh.read()).hexdigest()
                cache[key] = h
            out[os.path.relpath(p, ws)] = h
    return out


def diff(a, b):
    changed = sorted(k for k in b if k in a and a[k] != b[k])
    added = sorted(k for k in b if k not in a)
    removed = sorted(k for k in a if k not in b)
    return changed, added, removed


def describe(d):
    changed, added, removed = d
    parts = []
    if changed:
        parts.append("changed " + ", ".join(changed))
    if added:
        parts.append("added " + ", ".join(added))
    if removed:
        parts.append("removed " + ", ".join(removed))
    return "; ".join(parts)


def default_cwd(ws):
    try:
        top = subprocess.run(["git", "-C", ws, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
        if top.returncode == 0 and top.stdout.strip():
            return top.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ws


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("workspace")
    ap.add_argument("--copy", default=None, help="comma-separated copy-based areas (default: detected)")
    ap.add_argument("--max-passes", type=int, default=3)
    ap.add_argument("--cwd", default=None, help="directory to run generators in (default: the workspace's git top level, else the workspace)")
    ap.add_argument("--timeout", type=float, default=1800, help="seconds per generator run")
    ap.add_argument("--dry-run", action="store_true", help="print the order and the copy detection, run nothing")
    a = ap.parse_args()
    ws = os.path.abspath(a.workspace)
    gens = discover(ws)
    if not gens:
        print("regen: no gen/<area>/{build,gen,generate}.py under %s" % ws, file=sys.stderr)
        return 2
    areas = {g[0] for g in gens}
    reasons = {}
    if a.copy is not None:
        copies = {x.strip() for x in a.copy.split(",") if x.strip()}
        unknown = sorted(copies - areas)
        if unknown:
            print("regen: --copy names no generator: %s" % ", ".join(unknown), file=sys.stderr)
            return 2
        reasons = {x: "--copy" for x in copies}
    else:
        for area, script in gens:
            r = copy_reason(area, script)
            if r:
                reasons[area] = r
    order = [g for g in gens if g[0] not in reasons] + [g for g in gens if g[0] in reasons]
    cwd = os.path.abspath(a.cwd) if a.cwd else default_cwd(ws)
    print("workspace: %s (generators run in %s)" % (ws, cwd))
    for area, script in order:
        kind = "copy-based (%s)" % reasons[area] if area in reasons else "owner"
        print("  %-24s %-12s %s" % (area, os.path.basename(script), kind))
    if a.dry_run:
        return 0

    cache = {}
    start = snapshot(ws, cache)
    cur = start
    stable = False
    for n in range(1, a.max_passes + 1):
        t0 = time.time()
        pass_changes = []
        for area, script in order:
            res = subprocess.run([sys.executable, script], cwd=cwd, capture_output=True, text=True, timeout=a.timeout)
            if res.returncode != 0:
                print("✗ pass %d: %s (%s) exited %d" % (n, area, os.path.basename(script), res.returncode))
                tail = (res.stderr or res.stdout).strip().splitlines()[-15:]
                for line in tail:
                    print("    " + line)
                return 2
            nxt = snapshot(ws, cache)
            d = diff(cur, nxt)
            if any(d):
                pass_changes.append((area, d))
            cur = nxt
        if not pass_changes:
            print("pass %d: no changes (%.1fs); stable" % (n, time.time() - t0))
            stable = True
            break
        print("pass %d: %d generators changed files (%.1fs)" % (n, len(pass_changes), time.time() - t0))
        for area, d in pass_changes:
            print("  %s: %s" % (area, describe(d)))
    total = diff(start, cur)
    print("total: %s" % (describe(total) or "no files changed"))
    if not stable:
        print("✗ not stable after %d passes" % a.max_passes)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

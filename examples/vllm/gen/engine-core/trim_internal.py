"""Round 3: drop internal-assertion clauses that a boundary expectation already covers.

For each expectation the internal-assertions lint flagged (/tmp list), split at top-level
'&&'; drop clauses that read the state of a non-store engine-core component or
count/trace an engine-core-owned interface. An expectation left empty is removed,
unless the scenario would lose all its expectations (those are listed for hand
conversion). Prints what it did.
"""
import re, sys, yaml
P = 'parts/50-scenarios.yaml'
INTERNAL = ['async-llm', 'llm-engine', 'input-processor', 'output-processor', 'request-output-collector',
            'incremental-detokenizer', 'async-mp-client', 'dp-lb-async-mp-client', 'sync-mp-client',
            'core-engine-proc-manager', 'core-engine-actor-manager', 'ray-cluster', 'stat-logger-manager',
            'buckets', 'reader', 'engine-core-proc', 'engine-core-sentinel', 'executor', 'uni-proc-executor',
            'multiproc-executor', 'worker-proc', 'engine-core']
N = '(?:' + '|'.join(sorted(map(re.escape, INTERNAL), key=len, reverse=True)) + ')'
PAT = re.compile(r"state\['%s'\]|state\.%s\b|calls(?:_by_instance)?\['%s[.@]|interface == '%s\.|interface in \[[^\]]*'%s\." % (N, N, N, N, N))

def split(expr):
    out, depth, cur, i, q = [], 0, '', 0, None
    while i < len(expr):
        c = expr[i]
        if q:
            cur += c
            if c == q: q = None
        elif c in "'\"":
            q = c; cur += c
        elif c in '([{':
            depth += 1; cur += c
        elif c in ')]}':
            depth -= 1; cur += c
        elif depth == 0 and expr.startswith('&&', i):
            out.append(cur.strip()); cur = ''; i += 2; continue
        else:
            cur += c
        i += 1
    out.append(cur.strip())
    return out

def has_or(expr):
    # a top-level '||' makes splitting on '&&' unsafe
    depth, q = 0, None
    for i, c in enumerate(expr):
        if q:
            if c == q: q = None
        elif c in "'\"": q = c
        elif c in '([{': depth += 1
        elif c in ')]}': depth -= 1
        elif depth == 0 and expr.startswith('||', i): return True
    return False

FLAG = {}
cur = None
for l in open('/tmp/ecproto/ia_detail.txt'):
    if l.startswith('## '): cur = l[3:].strip(); continue
    m = re.match(r'  X (\d+) ', l)
    if m: FLAG.setdefault(cur, set()).add(int(m.group(1)))
text = open(P).read()
doc = yaml.safe_load(text)
manual = []
removed = changed = 0
for sc in doc['scenarios']:
    exps = sc.get('expect') or []
    new = []
    for k, e in enumerate(exps):
        if k not in FLAG.get(sc['id'], ()) or has_or(e):
            new.append(e); continue
        keep = [c for c in split(e) if not PAT.search(c)]
        if keep:
            new.append(' && '.join(keep)); changed += 1
        else:
            new.append(None)
    if all(x is None for x in new) and new:
        manual.append(sc['id']); continue
    # rewrite this scenario's expect block in text
    for old, nw in zip(exps, new):
        if old == nw: continue
        line = '      - ' + yaml.safe_dump(old, width=10**6, default_style='"').strip()
        line2 = '      - "%s"' % old.replace('\\', '\\\\').replace('"', '\\"')
        tgt = line if line in text else line2
        if tgt not in text:
            print('NOTFOUND', sc['id'], old[:80]); continue
        if nw is None:
            text = text.replace(tgt + '\n', '', 1); removed += 1
        else:
            text = text.replace(tgt, '      - "%s"' % nw.replace('\\', '\\\\').replace('"', '\\"'), 1)
open(P, 'w').write(text)
print('removed', removed, 'changed', changed, 'manual', manual)

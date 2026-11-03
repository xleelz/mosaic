import json, yaml, re, collections, sys
sys.path.insert(0, '/home/lbethay/workplace/mosaic/examples/cassandra/ops-gen')
FR = '/home/lbethay/workplace/mosaic/examples/cassandra/fragments/ops.yaml'
OUT = '/home/lbethay/workplace/mosaic/examples/cassandra/notes/ops.md'
doc = yaml.safe_load(open(FR))
mine = json.load(open('/tmp/ops_work/mine.json'))
groups = json.load(open('/tmp/ops_work/groups.json'))


def parse(src):
    if isinstance(src, dict):
        return src['path'], src.get('line', 0), src.get('end_line', src.get('line', 0))
    m = re.match(r'^(.*?)(?::(\d+)(?:-(\d+))?)?$', src)
    lo = int(m.group(2) or 0)
    return m.group(1), lo, int(m.group(3) or lo)


cites = collections.defaultdict(list)  # file -> (lo, hi, entity)


def walk(steps, ent):
    for st in steps or []:
        if not isinstance(st, dict):
            continue
        if 'source' in st:
            f, lo, hi = parse(st['source'])
            cites[f].append((lo, hi, ent))
        for k, v in st.items():
            if k in ('input', 'return', 'fail', 'set', 'source', 'when', 'retry'):
                continue
            if isinstance(v, list):
                walk(v, ent)
            elif isinstance(v, dict):
                for o in v.values():
                    if isinstance(o, list):
                        walk(o, ent)


for i in doc['interfaces']:
    ent = i['component'] + '.' + i['name']
    for s in i.get('sources') or []:
        f, lo, hi = parse(s)
        cites[f].append((lo, hi, ent))
    walk(i.get('behavior'), ent)
for c in doc['components']:
    for s_ in c.get('sources') or []:
        f, lo, hi = parse(s_)
        cites[f].append((lo, hi, 'component ' + c['id']))
for fl in doc['flows']:
    for s in fl.get('sources') or []:
        f, lo, hi = parse(s)
        cites[f].append((lo, hi, 'flow ' + fl['id']))


def covering(e):
    lo, hi = e['line'] - 3, e.get('end_line', e['line']) + 3
    out = []
    for a, b, ent in cites.get(e['file'], []):
        if a and a <= hi and b >= lo and ent not in out:
            out.append(ent)
    return out


lines = []
P = lines.append
P(open('/home/lbethay/workplace/mosaic/examples/cassandra/ops-gen/notes_head.md').read())
P('\n### Covered entry points (%d)\n' % len(mine['covered']))
P('Each line: inventory entry, then the flow-reachable entities that cite its lines.\n')
bykind = collections.defaultdict(list)
for e in mine['covered']:
    bykind[e['kind']].append(e)
for k in sorted(bykind):
    P('\n**%s** (%d)\n' % (k, len(bykind[k])))
    for e in sorted(bykind[k], key=lambda x: x['name']):
        P('- `%s` (%s:%d) -> %s' % (e['name'], e['file'].split('/')[-1], e['line'], ', '.join('`%s`' % c for c in covering(e)[:3]) or '(name match)'))
P('\n### Skipped entry points (%d)\n' % sum(len(g['items']) for g in groups.values()))
P('Groups are exact: every entry listed belongs to its group and to no other. Format: `kind name` (file:line).\n')
for key, g in groups.items():
    P('\n#### %s (%d)\n' % (key, len(g['items'])))
    P('Reason: %s\n' % g['reason'])
    bymb = collections.defaultdict(list)
    for kind, name, f, line in g['items']:
        owner = name.rsplit('.', 1)[0] if kind == 'jmx-operation' else kind
        bymb[owner].append((name.rsplit('.', 1)[-1] if kind == 'jmx-operation' else name, f.split('/')[-1], line))
    for owner in sorted(bymb):
        P('- %s (%d): %s' % (owner, len(bymb[owner]), ', '.join('%s (%s:%d)' % x for x in sorted(bymb[owner]))))
P(open('/home/lbethay/workplace/mosaic/examples/cassandra/ops-gen/notes_tail.md').read())
open(OUT, 'w').write('\n'.join(lines) + '\n')
print('wrote', OUT, len(lines))

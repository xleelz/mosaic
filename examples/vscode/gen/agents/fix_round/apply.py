# Fix round: applies patches/*.yaml (sorted) onto the generated fragment SRC and writes OUT (both default to fragments/agents.yaml).
import yaml, glob, sys, os
PAT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'patches', '*.yaml')
OUT = sys.argv[2] if len(sys.argv) > 2 else '/home/lbethay/workplace/mosaic/examples/vscode/fragments/agents.yaml'
SRC = sys.argv[3] if len(sys.argv) > 3 else OUT
class D(yaml.SafeDumper):
    def ignore_aliases(self, data): return True
def str_rep(d, v):
    style = None
    if v.startswith('=') or v.startswith('!') or ': ' in v or v.startswith("'") or '#' in v or v.startswith('*') or v.startswith('&'):
        style = '"'
    return d.represent_scalar('tag:yaml.org,2002:str', v, style=style)
D.add_representer(str, str_rep)
doc = yaml.safe_load(open(SRC))
ifx = {i['component'] + '.' + i['name']: i for i in doc['interfaces']}
def upsert(lst, item, key):
    k = key(item)
    for n, x in enumerate(lst):
        if key(x) == k:
            lst[n] = item; return
    lst.append(item)
errs = []
for f in sorted(glob.glob(PAT)):
    p = yaml.safe_load(open(f)) or {}
    for pt in p.get('patches') or []:
        i = ifx.get(pt['iface'])
        if not i:
            errs.append(f'{f}: unknown iface {pt["iface"]}'); continue
        for k in ('behavior', 'sources', 'summary', 'request', 'response', 'errors', 'kind', 'subscribe'):
            if k in pt: i[k] = pt[k]
    for c in p.get('configs') or []: upsert(doc['configs'], c, lambda x: x['id'])
    for c in p.get('components') or []: upsert(doc['components'], c, lambda x: x['id'])
    for c in p.get('interfaces') or []:
        upsert(doc['interfaces'], c, lambda x: x['component'] + '.' + x['name'])
        ifx[c['component'] + '.' + c['name']] = c
    for c in p.get('flows') or []: upsert(doc['flows'], c, lambda x: x['id'])
    for c in p.get('scenarios') or []: upsert(doc['scenarios'], c, lambda x: x['id'])
    for c in p.get('fixtures') or []: upsert(doc['fixtures'], c, lambda x: x['id'])
    for fid, tags in (p.get('flow_tags') or {}).items():
        fl = [x for x in doc['flows'] if x['id'] == fid]
        if not fl: errs.append(f'{f}: unknown flow {fid}'); continue
        fl[0]['tags'] = list(dict.fromkeys((fl[0].get('tags') or []) + tags))
    for iid in p.get('drop_interfaces') or []:
        doc['interfaces'] = [x for x in doc['interfaces'] if x['component'] + '.' + x['name'] != iid]
    for sid in p.get('drop_scenarios') or []:
        doc['scenarios'] = [s for s in doc['scenarios'] if s['id'] != sid]
hdr = "# Fragment of the agents area: the agent host process, the Agents (sessions) window and MCP.\n# Built from VS Code 1.144.0 (2c33b50b16) source; see notes/agents.md.\n"
open(OUT, 'w').write(hdr + yaml.dump(doc, Dumper=D, sort_keys=False, width=200, allow_unicode=True))
print('\n'.join(errs) or 'ok', file=sys.stderr)

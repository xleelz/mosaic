import sys
sys.path.insert(0, '/home/lbethay/workplace/mosaic/examples/cassandra/ops-gen')
import gen_flows  # noqa
from gen_base import dump, DOC
import json as _j
def _refs(doc):
    used=set()
    def w(x):
        if isinstance(x, dict):
            for k in ('call','emit'):
                if isinstance(x.get(k), str) and not x[k].startswith('='): used.add(x[k])
            for t in x.get('targets') or []: used.add(t)
            for v in x.values(): w(v)
        elif isinstance(x, list):
            for v in x: w(v)
    for i in doc['interfaces']: w(i.get('behavior'))
    for f in doc['flows']: used.add(f['entry']['interface'])
    return used
_used=_refs(DOC)
_drop=[i['component']+'.'+i['name'] for i in DOC['interfaces'] if (i.get('attributes') or {}).get('boundary') and i['component']+'.'+i['name'] not in _used]
print('dropping unused stubs', _drop)
DOC['interfaces'][:]=[i for i in DOC['interfaces'] if i['component']+'.'+i['name'] not in _drop]
import yaml as _y0
_need0 = set(k.split('@')[0] for f in _y0.safe_load(open('/home/lbethay/workplace/mosaic/examples/cassandra/fixtures.yaml')).get('fixtures', []) for k in (f.get('state') or {}))
_ic=set(i['component'] for i in DOC['interfaces']) | _need0 | set(k.split('@')[0] for sc in DOC['scenarios'] for k in (sc.get('state') or {}))
_dc=[c['id'] for c in DOC['components'] if (c.get('attributes') or {}).get('boundary') and c['id'] not in _ic]
print('dropping unused stub components', _dc)
DOC['components'][:]=[c for c in DOC['components'] if c['id'] not in _dc]
import align
# fixture state names other areas' components: declare them as boundary stubs (owner wins) so the
# fragment validates with fixtures.yaml on its own
import yaml as _y
_fx = _y.safe_load(open('/home/lbethay/workplace/mosaic/examples/cassandra/fixtures.yaml'))
_need = sorted(set(k.split('@')[0] for f in _fx.get('fixtures', []) for k in (f.get('state') or {})))
_have = set(c['id'] for c in DOC['components'])
_oc = align.load_owner_components()
for _cid in _need:
    if _cid in _have or _cid not in _oc:
        continue
    _area, _o = _oc[_cid]
    DOC['components'].append({'id': _cid, 'name': _o.get('name', _cid), 'kind': _o.get('kind', 'module'), 'parent': _o.get('parent'),
                              'summary': '%s (boundary stub for fixture state; %s models it).' % (_o.get('name', _cid), _area),
                              'sources': (_o.get('sources') or [])[:1], 'attributes': {'boundary': True, 'owner': _area}})
print('fixture stub components:', [c for c in _need if c not in _have])
rep, owners = align.align(DOC)
print('aligned', len(rep))
import json
open('/tmp/ops_work/aligned.json','w').write(json.dumps([{'id': a, 'owner': b, 'request': next(i for i in DOC['interfaces'] if i['component']+'.'+i['name']==a).get('request'), 'response': next(i for i in DOC['interfaces'] if i['component']+'.'+i['name']==a).get('response'), 'errors': next(i for i in DOC['interfaces'] if i['component']+'.'+i['name']==a).get('errors')} for a,b in rep], indent=1))
mine=set(i['component']+'.'+i['name'] for i in DOC['interfaces'] if (i.get('attributes') or {}).get('boundary'))
print('unaligned stubs:', sorted(mine - set(a for a,_ in rep)))
dump('/home/lbethay/workplace/mosaic/examples/cassandra/fragments/ops.yaml')
print({k: len(v) for k, v in DOC.items()})
from gen_base import SHIFTS
print('\n'.join(SHIFTS))

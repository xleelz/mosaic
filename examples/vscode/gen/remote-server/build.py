import yaml, glob, sys
out = {'schema_version': 1, 'id': 'vscode'}
order = ['configs','schemas','fixtures','components','interfaces','flows','scenarios']
for f in sorted(glob.glob('/home/lbethay/workplace/mosaic/examples/vscode/gen/remote-server/parts/*.yaml')):
    d = yaml.safe_load(open(f))
    for k, v in (d or {}).items():
        out.setdefault(k, []).extend(v)
# python-generated parts
import importlib.util
for f in sorted(glob.glob('/home/lbethay/workplace/mosaic/examples/vscode/gen/remote-server/parts/*.py')):
    spec = importlib.util.spec_from_file_location('m', f); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    for k, v in m.PART.items():
        out.setdefault(k, []).extend(v)
# boundary components auto-declared
known = {c['id'] for c in out.get('components', [])}
skeleton = yaml.safe_load(open('/home/lbethay/workplace/mosaic/examples/vscode/skeleton.yaml'))
known |= {c['id'] for c in skeleton['components']}
owners = {}
for i in out.get('interfaces', []):
    a = i.get('attributes') or {}
    if a.get('boundary') and i['component'] not in known:
        owners[i['component']] = a.get('owner')
for cid, o in sorted(owners.items()):
    out['components'].append({'id': cid, 'kind': 'service', 'summary': f'Boundary stub of a {o} component', 'attributes': {'boundary': True, 'owner': o}})
exec(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/remote-server/transform.py').read())
res = {k: out[k] for k in ['schema_version','id'] + [k for k in order if k in out]}
class D(yaml.SafeDumper): pass
D.ignore_aliases = lambda *a: True
open('/home/lbethay/workplace/mosaic/examples/vscode/fragments/remote-server.yaml','w').write(
  '# remote-server area fragment (VS Code 1.144.0). Generated from the area agent\'s parts; see notes/remote-server.md.\n' +
  yaml.dump(res, Dumper=D, sort_keys=False, width=200, allow_unicode=True))
print({k: len(v) for k, v in res.items() if isinstance(v, list)})
# Fix round: apply fixround/ (new and replaced entities, scenario edits, reconnect-loop and fixture patches) on top of the reconciled output.
exec(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/remote-server/fixround/apply.py').read(), {'__file__': '/home/lbethay/workplace/mosaic/examples/vscode/gen/remote-server/fixround/apply.py', '__name__': 'fixround'})

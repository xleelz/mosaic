"""Copy other areas' fragments, dropping scenarios that reference undefined fixtures (local runs only)."""
import sys, os, glob, re, shutil, yaml

class L(yaml.SafeLoader):
    pass
# YAML 1.2 booleans only: keep `on:`/`off:`/`yes`/`no` as strings
L.yaml_implicit_resolvers = {k: [(t, r) for t, r in v if t != 'tag:yaml.org,2002:bool'] for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}
L.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|True|TRUE|false|False|FALSE)$'), list('tTfF'))
src, dst, mine = sys.argv[1], sys.argv[2], sys.argv[3]
docs = {}
for f in glob.glob(os.path.join(src, '*.yaml')):
    if f.endswith('workbench-contribs.yaml'):
        continue
    try:
        docs[f] = yaml.load(open(f), Loader=L)
    except Exception:
        print('local_filter: unparsable, skipped', f); continue
fx = set()
for d in list(docs.values()) + [yaml.safe_load(open(mine)), yaml.safe_load(open('examples/vscode/fixtures.yaml')), yaml.load(open('examples/vscode/worlds.yaml'), Loader=L)]:
    fx |= {x['id'] for x in (d.get('fixtures') or [])}
class D(yaml.SafeDumper): pass
D.ignore_aliases = lambda self, data: True
for f, d in docs.items():
    sc = d.get('scenarios') or []
    keep = [s for s in sc if all(x in fx for x in (s.get('fixtures') or []))]
    if len(keep) == len(sc):
        shutil.copy(f, os.path.join(dst, os.path.basename(f)))
        continue
    print('local_filter: dropped', len(sc) - len(keep), 'scenarios from', os.path.basename(f))
    d['scenarios'] = keep
    yaml.dump(d, open(os.path.join(dst, os.path.basename(f)), 'w'), Dumper=D, sort_keys=False, width=200)

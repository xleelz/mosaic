"""Print owner contracts (non-boundary definitions) for interfaces this area calls."""
import yaml, glob, json, sys
want = set(sys.argv[1:])
for f in sorted(glob.glob('/home/lbethay/workplace/mosaic/examples/vscode/fragments/*.yaml')):
    if 'workbench-contribs' in f:
        continue
    try:
        d = yaml.safe_load(open(f))
    except Exception as ex:
        print('SKIP', f, type(ex).__name__); continue
    for i in d.get('interfaces', []) or []:
        iid = (i.get('component') or i['id'].split('.')[0]) + '.' + (i.get('name') or i['id'].split('.', 1)[1])
        if (iid in want or iid.split('.')[0] + '.*' in want) and not (i.get('attributes') or {}).get('boundary'):
            print('=====', iid, f.split('/')[-1], 'kind', i.get('kind'))
            print(' req', json.dumps(i.get('request'))[:900])
            print(' resp', json.dumps(i.get('response'))[:500])
            print(' err', json.dumps(i.get('errors')))
    for s in d.get('schemas', []) or []:
        if s['id'] in want:
            print('SCHEMA', s['id'], f.split('/')[-1], json.dumps(s['schema'])[:900])

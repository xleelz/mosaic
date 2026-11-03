import yaml, glob, sys, json
import os
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '/home/lbethay/workplace/mosaic/examples/vscode/fragments/remote-server.yaml'
DST = '/home/lbethay/workplace/mosaic/examples/vscode/fragments/remote-server.yaml'
doc = yaml.safe_load(open(SRC))

def key(kind, e):
    if kind == 'interfaces':
        return (e['component'], e['name'])
    return e['id']

DROP_IFACES = set()  # (component, name) to drop
KEEP_EXISTING = {('editor-service', 'open-editor')}

for f in sorted(glob.glob('' + HERE + '/new/*.yaml')):
    d = yaml.safe_load(open(f)) or {}
    for kind, items in d.items():
        lst = doc.setdefault(kind, [])
        idx = {key(kind, e): i for i, e in enumerate(lst)}
        for e in items:
            k = key(kind, e)
            if k in KEEP_EXISTING and k in idx:
                continue
            if k in idx:
                lst[idx[k]] = e
            else:
                lst.append(e)
                idx[k] = len(lst) - 1

ifaces = {(i['component'], i['name']): i for i in doc['interfaces']}

# Reconnecting loop: no attempt cap, it runs until the grace time expires.
loop = ifaces[('management-persistent-connection', 'run-reconnecting-loop')]
for st in loop['behavior']:
    if 'foreach' in st:
        st['title'] = ('do { attempt++; wait TIMES[attempt] (the last value, 30 s, repeats) } while (!permanent failure): '
                       'no attempt limit, only the grace time ends it (the model bounds the loop at 1000 attempts, far beyond 3 h)')
        st['source'] = 'src/vs/platform/remote/common/remoteAgentConnection.ts:669-745'
        st['foreach'] = ("= lists.range(1000).map(i, i < size(config['remote-reconnect-wait-times-s']) ? "
                         "config['remote-reconnect-wait-times-s'][i] : "
                         "config['remote-reconnect-wait-times-s'][size(config['remote-reconnect-wait-times-s']) - 1])")
        st['max'] = 1000

# Fixtures
fx = {f['id']: f for f in doc['fixtures']}
seed = fx['remote-server-seed']
seed['state']['commands-registry']['commands']['workbench.action.showRuntimeExtensions'] = {
    'handler': 'show-runtime-extensions-action.cmd-workbench-action-showruntimeextensions'}
srv = fx['remote-server-srv1']
srv['summary'] = ('A remote folder: window w1 connects to the remote server instance srv1, which was started with '
                  '--connection-token tok-dev (the resolver result for ssh-remote+dev-box, and for the shared remote-folder '
                  'authority ssh-remote+devbox, carries that token).')
srv.setdefault('state', {})['remote-extension-host-agent-server'] = {'args': {'connection_token': 'tok-dev'}}
for c in doc['components']:
    if c['id'] == 'remote-authority-resolver-service':
        c['state']['initial']['resolved']['ssh-remote+devbox'] = dict(c['state']['initial']['resolved']['ssh-remote+dev-box'])

# Feature tags
FEAT = {
    'extension-management': ['rs-ext-install', 'rs-ext-uninstall', 'rs-ext-auto-update', 'rs-ext-channel-install'],
    'settings-sync': ['rs-sync-turn-on', 'rs-sync-turn-off', 'rs-sync-trigger', 'rs-sync-status'],
    'remote-development': ['rs-remote-connect', 'rs-remote-reconnect', 'rs-remote-ext-host-connect', 'rs-remote-server-http-request'],
}
flows = {f['id']: f for f in doc['flows']}
for feat, ids in FEAT.items():
    for i in ids:
        t = flows[i].setdefault('tags', [])
        if 'feature:' + feat not in t:
            t.append('feature:' + feat)

# Scenario edits
scs = {s['id']: s for s in doc['scenarios']}
scs['remote-server-ext-install-disallowed-by-policy']['config']['extensions-allowed'] = {'redhat': True}
scs['remote-server-ext-install-allowed-publisher']['config']['extensions-allowed'] = {'redhat': True, 'ms-python': True}
exec(open('' + HERE + '/scen_edits.py').read())

# New scenarios
for f in sorted(glob.glob('' + HERE + '/scen/*.yaml')):
    for s in yaml.safe_load(open(f))['scenarios']:
        if s['id'] in scs:
            doc['scenarios'][[x['id'] for x in doc['scenarios']].index(s['id'])] = s
        else:
            doc['scenarios'].append(s)
        scs[s['id']] = s

def fixon(x):
    if isinstance(x, dict):
        return {('on' if k is True else k): fixon(v) for k, v in x.items()}
    if isinstance(x, list):
        return [fixon(v) for v in x]
    return x
doc = fixon(doc)
class D(yaml.SafeDumper):
    pass
D.ignore_aliases = lambda *a: True
order = ['schema_version', 'id', 'configs', 'schemas', 'fixtures', 'components', 'interfaces', 'flows', 'scenarios']
res = {k: doc[k] for k in order if k in doc}
open(DST, 'w').write("# remote-server area fragment (VS Code 1.144.0). Generated from the area agent's parts, then edited by the fix round (see notes/remote-server.md).\n"
                     + yaml.dump(res, Dumper=D, sort_keys=False, width=200, allow_unicode=True))
print('ok', {k: len(v) for k, v in res.items() if isinstance(v, list)})

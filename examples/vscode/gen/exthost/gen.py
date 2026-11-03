import json, re, yaml, copy, os
ROOT = '/home/lbethay/.cache/mosaic-bench/vscode-1.144.0/'
HERE = os.path.dirname(os.path.abspath(__file__)) + '/'
OUT = os.path.abspath(HERE + '../..') + '/'
mine = json.load(open('' + HERE + 'mine.json'))
api_lines = json.load(open(HERE + 'api_lines.json'))
api_tg = json.load(open(HERE + 'api_targets.json'))
rpc_tg = json.load(open(HERE + 'rpc_targets.json'))

def fixkeys(v):
    if isinstance(v, dict): return {('on' if k is True else k): fixkeys(x) for k, x in v.items()}
    if isinstance(v, list): return [fixkeys(x) for x in v]
    return v
def L(p): return fixkeys(yaml.safe_load(open(HERE + '' + p)))
def kebab(n):
    n = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', n)
    n = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1-\2', n)
    return n.lower()

doc = {'schema_version': 1, 'id': 'vscode'}
cs = L('core_configs_schemas.yaml')
doc['configs'] = cs['configs']; doc['schemas'] = cs['schemas']
comps = L('core_components.yaml')['components']
ifaces = []
for f in ['core_ifaces_lifecycle.yaml', 'core_ifaces_host.yaml', 'core_ifaces_api.yaml', 'core_ifaces_debug.yaml']:
    ifaces += L(f)['interfaces']
byid = {c['id']: c for c in comps}

def add_comp(cid, **kw):
    if cid in byid:
        c = byid[cid]
        for s in kw.get('sources', []):
            if s not in c.setdefault('sources', []): c['sources'].append(s)
        if 'state' in kw and 'state' not in c: c['state'] = kw['state']
        return c
    c = {'id': cid}
    c.update(kw)
    c.setdefault('attributes', {})['owner'] = 'exthost'
    comps.append(c); byid[cid] = c
    return c

# ---- customers
customer_ids = []
for e in mine:
    if e['kind'] != 'exthost-customer': continue
    name = e['name']
    if name == 'SaveParticipant':
        cid = 'main-thread-notebook-save-participant' if 'Notebook' in e['file'] else 'main-thread-save-participant'
    else:
        cid = kebab(name)
    add_comp(cid, name=name, kind='module', layer='extensions', parent='exthost-bridge',
             summary=f"{name}: RPC customer instantiated by ExtensionHostManager for {e.get('detail') or 'the extension host'}.",
             sources=[f"{e['file']}:{e['line']}"])
    customer_ids.append(cid)
byid['main-thread-commands'].setdefault('state', {'schema': {'type': 'object', 'properties': {'registrations': {'type': 'array', 'items': {'type': 'string'}}}}, 'initial': {'registrations': []}})
add_comp('main-thread-notebooks', sources=['src/vs/workbench/api/browser/mainThreadNotebook.ts:199-213', 'src/vs/workbench/api/browser/mainThreadNotebook.ts:215-227'])
add_comp('main-thread-file-system-event-service', sources=['src/vs/workbench/api/browser/mainThreadFileSystemEventService.ts:278-292'])

# ---- services
svc_ids = []
special = {'IExtensionService': 'extension-service', 'IExtensionUrlHandler': 'extension-url-handler', 'IExtHostExtensionService': 'ext-host-extension-service',
           'IHostUtils': 'host-utils', 'IExtHostInitDataService': 'ext-host-init-data-service', 'IExtHostRpcService': 'ext-host-rpc-service',
           'IURITransformerService': 'uri-transformer-service', 'IExtHostTimeline': 'ext-host-timeline'}
skip_svcs = {'IExtensionHostStarter': 'owned by main-process: no registerSingleton; implementation ExtensionHostStarter lives in src/vs/platform/extensions/electron-main (exthost calls it as boundary stub extension-host-starter.*)',
             'IBuiltinExtensionsScannerService': 'owned by workbench-shell: registerSingleton BuiltinExtensionsScannerService in src/vs/workbench/services/extensionManagement/browser/builtinExtensionsScannerService.ts:110'}
for e in mine:
    if e['kind'] != 'service' or e['name'] in skip_svcs: continue
    n = e['name']
    if n in special: cid = special[n]
    else:
        impls = re.findall(r'registerSingleton (.*)$', e.get('detail', ''))
        cls = None
        if impls:
            for part in impls[0].split(', '):
                c = part.split(' ')[0]
                if not c.startswith(('Node', 'Worker', 'Native')): cls = c; break
            if not cls: cls = impls[0].split(' ')[0]
        cid = kebab(cls) if cls else kebab(n[1:])
    parent = 'exthost-runtime' if '/api/common/' in e['file'] else 'exthost-bridge'
    add_comp(cid, name=n[1:], kind='service', layer='extensions', parent=parent,
             summary=f"{n} implementation ({e.get('detail','')}).", sources=[f"{e['file']}:{e['line']}"])
    svc_ids.append(cid)
add_comp('ext-host-commands', state={'schema': {'type': 'object', 'properties': {'commands': {'type': 'array', 'items': {'type': 'string'}}}}, 'initial': {'commands': []}})
add_comp('ext-host-urls', state={'schema': {'type': 'object', 'properties': {'handles': {'type': 'array', 'items': {'type': 'string'}}}}, 'initial': {'handles': []}})
for cid in ['ext-host-workspace', 'ext-host-commands', 'ext-host-urls']:
    assert cid in byid, cid

# ---- contributions and extension points
ep = [
 ('extension-points', 'ExtensionPoints', 'module', ['src/vs/workbench/api/browser/extensionHost.contribution.ts:130', 'src/vs/workbench/api/browser/extensionHost.contribution.ts:120-127'], 'Workbench contribution (BlockStartup) that instantiates the built-in extension point handlers.'),
 ('views-extension-handler', 'ViewsExtensionHandler', 'module', ['src/vs/workbench/api/browser/viewsExtensionPoint.ts:760', 'src/vs/workbench/api/browser/viewsExtensionPoint.ts:252-255', 'src/vs/workbench/api/browser/viewsExtensionPoint.ts:258-273', 'src/vs/workbench/api/browser/viewsExtensionPoint.ts:277'], 'Handles the viewsContainers and views extension points (registers view containers and views).'),
 ('extension-url-bootstrap-handler', 'ExtensionUrlBootstrapHandler', 'module', ['src/vs/workbench/services/extensions/browser/extensionUrlHandler.ts:389', 'src/vs/workbench/services/extensions/browser/extensionUrlHandler.ts:360-387'], 'Buffers extension URLs that arrive before ExtensionUrlHandler exists (BlockRestore).'),
 ('status-bar-items-extension-point', 'StatusBarItemsExtensionPoint', 'module', ['src/vs/workbench/api/browser/statusBarExtensionPoint.ts:250-253', 'src/vs/workbench/api/browser/statusBarExtensionPoint.ts:255-261'], 'Handles the statusBarItems extension point.'),
 ('configuration-extension-point', 'configuration extension points', 'module', ['src/vs/workbench/api/common/configurationExtensionPoint.ts:188-194', 'src/vs/workbench/api/common/configurationExtensionPoint.ts:244-258'], 'configurationDefaults and configuration extension point handlers (register settings and default overrides).'),
 ('json-validation-extension-point', 'JSONValidationExtensionPoint', 'module', ['src/vs/workbench/api/common/jsonValidationExtensionPoint.ts:26-51', 'src/vs/workbench/api/common/jsonValidationExtensionPoint.ts:53-71', 'src/vs/workbench/api/common/jsonValidationExtensionPoint.ts:73'], 'jsonValidation and jsonValidationRegistry extension point handlers.'),
]
for cid, name, kind, srcs, summ in ep:
    add_comp(cid, name=name, kind=kind, layer='extensions', parent='exthost-bridge', summary=summ, sources=srcs)

exec(open(HERE + 'chunk_api.py').read())
exec(open(HERE + 'chunk_stateful.py').read())

# ---- flows and scenarios
fs = L('flows.yaml')
flows = fs['flows']; scen = fs['scenarios']
for f in flows:
    if f['id'] == 'exthost-rpc-customers':
        f['steps'] = [{'component': c, 'title': f"Instantiate {byid[c]['name']}", 'source': byid[c]['sources'][0]} for c in customer_ids] + \
            [{'component': c, 'title': f"{byid[c]['name']}", 'source': byid[c]['sources'][0]} for c in ['main-thread-documents', 'main-thread-cli-commands']]
    if f['id'] == 'exthost-runtime-services':
        f['steps'] = [{'component': c, 'title': f"Service {byid[c]['name']} (identifier and registered implementation)", 'source': byid[c]['sources'][-1] if c in ('extension-service', 'extension-url-handler', 'ext-host-extension-service') else byid[c]['sources'][0]} for c in svc_ids]
    if f['id'] == 'exthost-start':
        f['steps'] = f.get('steps', []) + [{'component': c, 'title': f"Extension point handling: {byid[c]['name']}", 'source': byid[c]['sources'][0]} for c, *_ in ep]

exec(open(HERE + 'chunk_scen.py').read())
doc['components'] = comps; doc['interfaces'] = ifaces; doc['flows'] = flows; doc['scenarios'] = scen

class D(yaml.SafeDumper):
    def ignore_aliases(self, data): return True
open(os.environ.get('EXTHOST_OUT', OUT + 'fragments/exthost.yaml'), 'w').write('# exthost area fragment (VS Code 1.144.0): extension host lifecycle, activation, RPC customers and the vscode API.\n' + yaml.dump(doc, Dumper=D, sort_keys=False, width=200, allow_unicode=True))

# ---- skips
cited = set()
def walk(v):
    if isinstance(v, dict):
        for k, x in v.items():
            if k in ('sources',) and isinstance(x, list):
                for s in x: cited.add(s)
            elif k == 'source' and isinstance(x, str): cited.add(x)
            else: walk(x)
    elif isinstance(v, list):
        for x in v: walk(x)
walk(ifaces)
proto_lines = set()
for s in cited:
    m = re.match(r'src/vs/workbench/api/common/extHost.protocol.ts:(\d+)$', s)
    if m: proto_lines.add(int(m.group(1)))
skips = []
for e in mine:
    base = {k: e[k] for k in ('kind', 'name', 'file', 'line')}
    if e['kind'] == 'exthost-rpc' and e['line'] not in proto_lines:
        t = rpc_tg[e['name']]
        shape, meth = e['name'].split('.', 1)
        if (t.get('impl') or '').startswith('MainThread') or shape.startswith('MainThread') or shape == 'IChatAgentProgressShape':
            impl = kebab(t['impl']) if t.get('impl') else 'main-thread-chat-agents2'
            svc = t.get('service')
            if not svc:
                inj = [x for x in (t.get('inj') or []) if x not in ('ILogService', 'IInstantiationService', 'IUriIdentityService', 'ITelemetryService', 'IEnvironmentService', 'IConfigurationService')]
                svc = inj[0] if inj else None
            tgt = f"{kebab(svc[1:])}{'.' + kebab(t['svc_method']) if t.get('svc_method') and t.get('service') == svc else ''}" if svc else 'its own registries'
            reason = f"RPC plumbing: {impl}.{kebab(meth[1:])} forwards to {tgt}; covered by the service interface it forwards to"
        else:
            impl = kebab(t['impl']) if t.get('impl') else kebab(shape.replace('Shape', '').lstrip('I'))
            reason = f"RPC plumbing: {impl}.{kebab(meth[1:])} (main thread to extension host) forwards to the extension-registered provider/callback held by {impl}, reached through vscode-api; covered by the vscode-api interface that registers it"
        skips.append(dict(base, reason=reason))
    elif e['kind'] == 'service' and e['name'] in skip_svcs:
        skips.append(dict(base, reason=skip_svcs[e['name']]))
    elif e['kind'] == 'vscode-command' and e['name'] in ('_generateCommandsDocumentation', '_extensionTests.setLogLevel', '_extensionTests.getLogLevel', '_telemetry.setCapiAssignmentContext', '_workbench.revertAllDirty'):
        skips.append(dict(base, reason='developer or internal command with no user-visible behavior (tests, telemetry, developer diagnostics or _workbench.*)'))
json.dump(skips, open(os.environ.get('EXTHOST_SKIPS', OUT + 'skips/exthost.json'), 'w'), indent=1)
print('components', len(comps), 'interfaces', len(ifaces), 'flows', len(flows), 'scenarios', len(scen), 'skips', len(skips), 'rpc modeled', len(proto_lines))

# ---- fix round (after judging): real logic for E3, X5, X8, API commands, editor tabs, debug visualizers,
# DA sessions, the text-search provider, chat $invokeAgent, R1/R3 hops; skips get covered_by. See notes/exthost.md.
import subprocess as _sp, sys as _sys
_fr = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fix_round')
_sp.run([_sys.executable, os.path.join(_fr, 'patch.py'), os.environ.get('EXTHOST_OUT', OUT + 'fragments/exthost.yaml')], check=True)
_sp.run([_sys.executable, os.path.join(_fr, 'fixskips.py'), os.environ.get('EXTHOST_SKIPS', OUT + 'skips/exthost.json')], check=True)

import json, re, sys, yaml

ROOT = '/home/lbethay/.cache/mosaic-bench/vscode-1.144.0/'
OUT = '/home/lbethay/workplace/mosaic/examples/vscode/fragments/platform-core.yaml'

inv = json.load(open('/home/lbethay/workplace/mosaic/examples/vscode/inventory.json'))
# decorator name -> service id (createDecorator string)
dec_id = {}
for e in inv['entries']:
    if e['kind'] == 'service':
        m = re.match(r'id (\S+?);?(\s|$)', e.get('detail', ''))
        if m:
            dec_id.setdefault(e['name'], m.group(1).rstrip(';'))

svcs = json.load(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/platform-core/svcs.json'))
drop = {'accessibility-signal-service', 'telemetry-service', 'request-service', 'browser-clipboard-service', 'context-menu-service', 'git-hub-service', 'local-transcription-service'}
svcs = [s for s in svcs if s['id'] not in drop]

# deep services that also get constructor stubs: (component, decorator, file, ctor line range)
deep = [
    ('command-service', 'ICommandService', 'src/vs/workbench/services/commands/common/commandService.ts', 28, 36),
    ('configuration-service', 'IConfigurationService', 'src/vs/platform/configuration/common/configurationService.ts', 42, 70),
    ('file-service', 'IFileService', 'src/vs/platform/files/common/fileService.ts', 35, 50),
    ('storage-service', 'IStorageService', 'src/vs/platform/storage/common/storage.ts', 351, 355),
    ('context-key-service', 'IContextKeyService', 'src/vs/platform/contextkey/browser/contextKeyService.ts', 386, 393),
    ('undo-redo-service', 'IUndoRedoService', 'src/vs/platform/undoRedo/common/undoRedoService.ts', 464, 470),
    ('marker-service', 'IMarkerService', 'src/vs/platform/markers/common/markerService.ts', 155, 172),
    ('menu-service', 'IMenuService', 'src/vs/platform/actions/common/menuService.ts', 26, 32),
    ('action-widget-service', 'IActionWidgetService', 'src/vs/platform/actionWidget/browser/actionWidget.ts', 90, 96),
]

def ctor_deps(path, start):
    L = open(ROOT + path).read().split('\n')
    deps = []
    for j in range(start - 1, min(start + 40, len(L))):
        deps += re.findall(r'@(I\w+)', L[j])
        if re.search(r'\)\s*\{', L[j]) or L[j].rstrip().endswith(') {'):
            break
    return deps

# services created before the instantiation service in the desktop workbench (desktop.main)
precreated = {'IConfigurationService', 'IFileService', 'IStorageService', 'ILogService', 'IInstantiationService',
              'IPolicyService', 'IUriIdentityService', 'IUserDataProfilesService', 'IEnvironmentService',
              'IMainProcessService', 'ISignService', 'ILoggerService'}

services = {'instantiationService': {'ctor': '', 'deps': [], 'created': True}}
components, interfaces, targets = [], [], []

for s in svcs:
    sources = list(s['decl']) + [f"{s['file']}:{s['cls_line']}"]
    comp = {
        'id': s['id'], 'name': s['cls'], 'kind': 'service', 'parent': 'platform',
        'summary': f"{s['iface']} implementation ({s['cls']}); created on first use by the instantiation service.",
        'sources': sources,
        'attributes': {'owner': 'platform-core', 'class': s['cls'], 'decorator': dec_id.get(s['iface'], ''), 'process': s['proc']},
    }
    if s['id'] == 'logger-service':
        comp['state'] = {'schema': {'type': 'object', 'properties': {'log_level': {'type': 'string'}, 'loggers': {'type': 'object'}}},
                         'initial': {'log_level': 'info', 'loggers': {}}}
    if s['id'] == 'shared-process-git-hub-service':
        comp['sources'].append('src/vs/platform/github/electron-browser/githubService.ts:26')
    components.append(comp)
    line = s['ctor_line'] or s['cls_line']
    iface = {
        'component': s['id'], 'name': 'constructor', 'kind': 'function',
        'summary': f"new {s['cls']}(...) (constructor arguments, injected services among them)" + ("" if s["ctor_line"] else " (implicit constructor)"),
        'sources': [f"{s['file']}:{line}"],
    }
    if s['id'] == 'shared-process-git-hub-service':
        iface['sources'] = ['src/vs/platform/github/electron-browser/githubService.ts:20-29']
        iface['behavior'] = [
            {'title': 'Register the githubCredentials channel on the shared-process connection',
             'source': 'src/vs/platform/github/electron-browser/githubService.ts:26',
             'call': 'git-hub-credentials-channel.constructor'},
            {'title': "Client for the shared process's github channel (registered per connection by registerGitHubChannel)",
             'source': 'src/vs/platform/github/electron-browser/githubService.ts:27',
             'call': 'git-hub-channel.constructor'},
        ]
    interfaces.append(iface)
    targets.append(f"{s['id']}.constructor")
    deps = ctor_deps(s['file'], s['ctor_line']) if s['ctor_line'] else []
    sid = dec_id.get(s['iface'])
    if sid:
        services[sid] = {'ctor': f"{s['id']}.constructor", 'deps': [dec_id.get(d, d) for d in deps], 'created': s['iface'] in precreated}

for cid, deco, path, a, b in deep:
    interfaces.append({'component': cid, 'name': 'constructor', 'kind': 'function',
                       'summary': f"Constructor of the {deco} implementation with its injected services.",
                       'sources': [f"{path}:{a}-{b}"]})
    targets.append(f"{cid}.constructor")
    deps = ctor_deps(path, a)
    services[dec_id[deco]] = {'ctor': f"{cid}.constructor", 'deps': [dec_id.get(d, d) for d in deps], 'created': deco in precreated}

doc = yaml.safe_load(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/platform-core/deep.yaml'))
fl = yaml.safe_load(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/platform-core/flows.yaml'))
for c in doc['components']:
    if c['id'] == 'instantiation-service':
        c['state']['initial']['services'] = services
# command handlers: my own registry rows plus every area's commands-registry seed (decision 6),
# kept only when the handler interface exists in some fragment
import glob
FRAG = '/home/lbethay/workplace/mosaic/examples/vscode/fragments/'
known = set()
handlers = set()
for c in doc['components']:
    if c['id'] == 'commands-registry':
        handlers |= {r['handler'] for r in c['state']['initial']['commands'].values()}
for f in sorted(glob.glob(FRAG + '*.yaml')):
    if f.endswith('platform-core.yaml'):
        continue
    other = yaml.safe_load(open(f))
    for i in other.get('interfaces') or []:
        if not (i.get('attributes') or {}).get('boundary'):
            known.add(i['component'] + '.' + i['name'])
    for fx in other.get('fixtures') or []:
        for k, v in (fx.get('state') or {}).items():
            if k.split('@')[0] == 'commands-registry':
                handlers |= {r['handler'] for r in ((v or {}).get('commands') or {}).values() if isinstance(r, dict) and 'handler' in r}
# runtime registrations: literal handlers passed to commands-registry.register-command in any behavior
def _walk_reg(x):
    if isinstance(x, dict):
        if x.get('call') == 'commands-registry.register-command':
            h = (x.get('input') or {}).get('handler')
            if isinstance(h, str) and not h.startswith('='):
                handlers.add(h)
        for v in x.values():
            _walk_reg(v)
    elif isinstance(x, list):
        for v in x:
            _walk_reg(v)
for f in sorted(glob.glob(FRAG + '*.yaml')):
    if not f.endswith('platform-core.yaml'):
        _walk_reg((yaml.safe_load(open(f)) or {}).get('interfaces') or [])
handlers.add('editor-command.run-command')  # editor's request: its generic command runner
handlers.add('emmet-extension.cmd-emmet-expandabbreviation')  # builtin-extensions' request: emmet.expandAbbreviation (registered in its own registrations map, not the seed)
mine_ids = {i['component'] + '.' + i['name'] for i in doc['interfaces']}
cmd_targets = sorted(h for h in handlers if h in known or h in mine_ids)
print('command handler targets:', len(cmd_targets), 'dropped (unknown):', sorted(h for h in handlers if h not in known and h not in mine_ids)[:10])
for i in doc['interfaces']:
    if i.get('component') == 'command-service' and i['name'] == 'try-execute-command':
        for st in i['behavior']:
            if 'targets' in st:
                st['targets'] = cmd_targets
for i in doc['interfaces']:
    if i.get('component') == 'instantiation-service' and i['name'] == 'get-or-create-service-instance':
        for st in i['behavior']:
            if st.get('targets') == '__CTOR_TARGETS__':
                st['targets'] = sorted(targets)
doc['components'] += components
doc['interfaces'] += interfaces
doc['flows'] = fl['flows']
doc['scenarios'] = fl['scenarios']

out = {'schema_version': 1, 'id': 'vscode', 'schemas': doc['schemas'], 'components': doc['components'],
       'interfaces': doc['interfaces'], 'flows': doc['flows'], 'scenarios': doc['scenarios']}
hdr = ("# platform-core fragment of the VS Code 1.144.0 ontology (src/vs/base/**, src/vs/platform/** minus the excepted\n"
       "# subtrees). Owns the seams command-service.execute-command, configuration-service.get-value and\n"
       "# file-service.* (plus the disk.* store stubs). Generated from hand-written parts; see notes/platform-core.md.\n")
with open(OUT, 'w') as f:
    f.write(hdr)
    yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True, width=200, default_flow_style=False)
print('services seeded:', len(services), 'targets:', len(targets), 'components:', len(out['components']), 'interfaces:', len(out['interfaces']))

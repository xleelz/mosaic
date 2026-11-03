import json, re, sys, os, collections, glob
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
# usage: gen.py [OUTPUT_FRAGMENT] [--only PART ...]
args = sys.argv[1:]
OUTFILE = args[0] if args and not args[0].startswith('--') else None
ONLY = args[args.index('--only') + 1:] if '--only' in args else None

ROOT = '/home/lbethay/.cache/mosaic-bench/vscode-1.144.0'
OUT = '/home/lbethay/workplace/mosaic/examples/vscode'
C = 'src/vs/workbench/contrib/'

inv = json.load(open(OUT + '/inventory.json'))['entries']
others = ['files', 'search', 'searchEditor', 'scm', 'markers', 'mergeEditor', 'multiDiffEditor', 'terminal', 'terminalContrib', 'debug', 'tasks', 'testing', 'output', 'notebook', 'webview', 'webviewPanel', 'customEditor', 'interactive', 'chat', 'inlineChat', 'agentsVoice', 'mcp', 'remote', 'extensions', 'userDataSync', 'update']

# services implemented in my folders, by registerSingleton
impl = {}
for line in open(os.path.join(HERE, 'singletons.txt')):
    m = re.match(r'([^:]+):(\d+):.*registerSingleton\((I\w+),\s*(?:class\s+)?(\w+)', line)
    if not m:
        continue
    f, ln, iface, cls = m.groups()
    if f.split('/')[0] in others:
        continue
    prev = impl.get(iface)
    # prefer the desktop (electron-browser) implementation
    if prev is None or ('electron-browser' in f and 'electron-browser' not in prev[0]):
        impl[iface] = (f, int(ln), cls)

mine = []
for e in inv:
    f = e['file']
    if f.startswith(C):
        if f.split('/')[4] in others:
            continue
        mine.append(e)
    elif e['kind'] == 'service' and e['name'] in impl:
        mine.append(e)

def kebab(s):
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', s)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1-\2', s)
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def cmd_slug(cid):
    s = re.sub(r'[._]', '-', cid).lower()
    s = re.sub(r'[^a-z0-9-]+', '-', s).strip('-')
    return ('cmd-' + s)[:64].rstrip('-')

# ---------------- skips ----------------
DEV = re.compile(r'^(_workbench\.|_developer\.|developer\.|perf\.|_aiEdits\.)')
DEV_NAMES = {'perfview.show', 'workbench.action.inspectKeyMappings', 'workbench.action.inspectKeyMappingsJSON', 'editor.action.inspectTMScopes', 'editor.action.startDebugTextMate', 'workbench.action.toggleKeybindingsLog'}
UI = {
    'editor.action.accessibleViewNext', 'editor.action.accessibleViewNextCodeBlock', 'editor.action.accessibleViewPreviousCodeBlock', 'editor.action.accessibleViewPrevious', 'editor.action.accessibleViewGoToSymbol',
    '${commandPrefix}.showFind', '${commandPrefix}.hideFind', '${commandPrefix}.findNext', '${commandPrefix}.findPrevious', '${commandPrefix}.focusUrlInput', '${commandPrefix}.toggleDevTools', 'workbench.action.browser.stopElementSelection',
    'editor.refocusCallHierarchy', 'editor.closeCallHierarchy', 'editor.refocusTypeHierarchy', 'editor.closeTypeHierarchy',
    'comments.collapse', 'comments.expand', 'editor.action.nextCommentThreadAction', 'editor.action.previousCommentThreadAction', 'editor.action.nextCommentedRangeAction', 'editor.action.previousCommentedRangeAction', 'editor.action.nextCommentingRange', 'editor.action.previousCommentingRange',
    'workbench.action.focusCommentOnCurrentLine', 'workbench.action.collapseAllComments', 'workbench.action.expandAllComments', 'workbench.action.expandUnresolvedComments', 'commentsFocusViewFromFilter', 'commentsClearFilterText', 'commentsFocusFilter',
    'workbench.actions.${COMMENTS_VIEW_ID}.toggleUnResolvedComments', 'workbench.actions.${COMMENTS_VIEW_ID}.toggleResolvedComments', 'workbench.actions.${COMMENTS_VIEW_ID}.toggleSortByUpdatedAt', 'workbench.actions.${COMMENTS_VIEW_ID}.toggleSortByResource',
    'outline.collapse', 'outline.expand', 'outline.followCursor', 'outline.filterOnType', 'outline.sortByPosition', 'outline.sortByName', 'outline.sortByKind',
    'settings.action.search', 'settings.action.clearSearchResults', 'settings.action.focusSettingsFile', 'settings.action.focusSettingsFromSearch', 'settings.action.showPreviousSearch', 'settings.action.focusSettingsFromSearchOnEnter', 'settings.action.focusSearchFromSettings', 'settings.action.focusSettingsList', 'settings.action.focusTOC', 'settings.action.focusSettingControl', 'settings.action.showContextMenu', 'settings.action.focusLevelUp',
    'settings.filterByOnline', 'settings.filterUntrusted', 'settings.filterByTelemetry', 'settings.action.toggleAiSearch',
    'keybindings.editor.showDefaultKeybindings', 'keybindings.editor.showExtensionKeybindings', 'keybindings.editor.showUserKeybindings', 'keybindings.editor.clearSearchResults', 'keybindings.editor.searchKeybindings', 'keybindings.editor.recordSearchKeys', 'keybindings.editor.toggleSortByPrecedence', 'keybindings.editor.showConflicts', 'keybindings.editor.focusKeybindings', 'keybindings.editor.rejectWhenExpression', 'keybindings.editor.acceptWhenExpression',
    'workbench.action.quickOpenNavigateNextInViewPicker', 'workbench.action.quickOpenNavigatePreviousInViewPicker',
    'repl.focusLastItemExecuted', 'repl.input.focus', 'list.find.replInputFocus',
    'workbench.action.toggleLockedScrolling', 'workbench.action.holdLockedScrolling',
    'timeline.toggleFollowActiveEditor',
    'WalkThroughArrowUp', 'WalkThroughArrowDown', 'WalkThroughPageUp', 'WalkThroughPageDown', 'welcome.goBack', 'walkthroughs.selectStep',
    'list.resizeColumn', 'imagePreview.zoomIn', 'imagePreview.zoomOut', 'imagePreview.selectZoomLevel',
}
skips = []
covered = []
for e in mine:
    r = None
    if e['kind'] == 'vscode-command':
        if DEV.match(e['name']) or e['name'] in DEV_NAMES:
            r = 'developer or internal command with no user-visible behavior (developer diagnostics, perf tooling, internal settings-editor plumbing or AI edit telemetry)'
        elif e['name'] in UI:
            r = 'UI toggle: no state beyond the layout'
    if r:
        skips.append({'kind': e['kind'], 'name': e['name'], 'file': e['file'], 'line': e['line'], 'reason': r})
    else:
        covered.append(e)

# ---------------- deep part ----------------
deep = yaml.safe_load(open(os.path.join(HERE, 'deep.yaml')))
flows = yaml.safe_load(open(os.path.join(HERE, 'flows.yaml')))
comps = {c['id']: c for c in deep['components']}

# explicit entry -> deep component
def deep_target(e):
    f, ln = e['file'], e['line']
    rel = f[len(C):] if f.startswith(C) else f
    if rel == 'welcomeGettingStarted/browser/gettingStarted.contribution.ts':
        return 'startup-page-runner-contribution' if ln == 357 else 'getting-started-commands'
    if rel in ('welcomeGettingStarted/browser/gettingStartedService.ts', 'welcomeGettingStarted/browser/gettingStartedExtensionPoint.ts'):
        return 'walkthroughs-service'
    if rel in ('snippets/browser/snippets.ts', 'snippets/browser/snippetsService.ts'):
        return 'snippets-service'
    if rel == 'snippets/browser/snippets.contribution.ts' and ln == 26:
        return 'insert-snippet-action'
    if rel == 'url/browser/url.contribution.ts' and ln == 69:
        return 'opener-validator-contributions'
    if rel == 'url/common/trustedDomainService.ts':
        return 'trusted-domain-service'
    if rel == 'workspace/browser/workspace.contribution.ts':
        return {705: 'workspace-trust-request-handler', 706: 'workspace-trust-ux-handler', 751: 'workspace-trust-commands', 769: 'workspace-trust-commands'}.get(ln)
    if rel == 'codeEditor/browser/saveParticipants.ts':
        return 'save-participants-contribution'
    if rel == 'format/browser/formatActionsMultiple.ts' and ln == 271:
        return 'default-formatter'
    if rel == 'format/browser/formatActionsNone.ts':
        return 'format-document-none-action'
    if rel == 'format/browser/formatModified.ts':
        return 'format-modified'
    if e['kind'] == 'service' and e['name'] == 'IBulkEditService':
        return 'bulk-edit-service'
    if rel == 'bulkEdit/browser/preview/bulkEdit.contribution.ts':
        return 'bulk-edit-preview-contribution'
    if rel == 'editSessions/browser/editSessions.contribution.ts':
        return 'edit-sessions-contribution'
    if rel == 'editSessions/browser/editSessionsStorageService.ts' or (rel == 'editSessions/common/editSessions.ts' and ln == 23):
        return 'edit-sessions-workbench-service'
    return None

used_ids = set(comps)
file_comp = {}
catalog = collections.OrderedDict()

def file_component(f):
    if f in file_comp:
        return file_comp[f]
    parts = f[len(C):].split('/') if f.startswith(C) else f.split('/')
    d = parts[0]
    base = parts[-1][:-3]
    cid = kebab(base.replace('.contribution', 'Contribution').replace('.', '-'))
    if not cid.startswith(kebab(d)) and kebab(d) not in cid:
        cid = kebab(d) + '-' + cid
    plat = parts[1] if len(parts) > 2 else ''
    if plat == 'electron-browser':
        cid += '-native'
    elif plat == 'common' and len(parts) > 2:
        cid += '-common'
    base_id = cid
    n = 2
    while cid in used_ids:
        cid = f'{base_id}-{n}'; n += 1
    used_ids.add(cid)
    file_comp[f] = cid
    catalog[cid] = {'id': cid, 'name': parts[-1], 'kind': 'module', 'parent': 'workbench', 'file': f, 'entries': []}
    return cid

def service_component(e):
    f, ln, cls = impl[e['name']]
    cid = kebab(cls)
    if cid in catalog:
        return cid
    if cid in used_ids:
        cid = cid + '-impl'
    used_ids.add(cid)
    catalog[cid] = {'id': cid, 'name': cls, 'kind': 'service', 'parent': 'workbench', 'file': C + f, 'entries': [], 'extra': [f'{C}{f}:{ln}']}
    return cid

deep_extra = collections.defaultdict(list)
for e in covered:
    t = deep_target(e)
    if t:
        deep_extra[t].append(e)
        continue
    if e['kind'] == 'service' and e['name'] in impl:
        cid = service_component(e)
    else:
        cid = file_component(e['file'])
    catalog[cid]['entries'].append(e)

def describe(e):
    k = e['kind']
    if k == 'vscode-command':
        return f"command {e['name']}"
    if k == 'workbench-contribution':
        return f"contribution {e['name']}"
    if k == 'service':
        return f"service {e['name']}"
    if k == 'extension-point':
        return f"extension point {e['name']}"
    if k == 'process-main':
        return f"worker main {e['name'].split('/')[-1]}"
    return f"{k} {e['name']}"

def summary_for(entries, lead):
    names = [describe(e) for e in entries]
    s = lead + '; '.join(names)
    return s

out_components = list(deep['components'])
existing_srcs = {c['id']: set(str(s).split(':')[0] + ':' + str(s).split(':')[1].split('-')[0] if ':' in str(s) else str(s) for s in c.get('sources', [])) for c in out_components}
for c in out_components:
    extra = deep_extra.get(c['id'], [])
    srcs = c.setdefault('sources', [])
    have = {str(s) for s in srcs}
    for e in extra:
        s = f"{e['file']}:{e['line']}"
        # skip when an existing source already starts at that line
        if any(str(x).startswith(s) and (len(str(x)) == len(s) or str(x)[len(s)] == '-') for x in srcs):
            continue
        srcs.append(s)
    if extra:
        c['summary'] = c.get('summary', '') + ' Also registers: ' + '; '.join(describe(e) for e in extra) + '.'

for cid, c in catalog.items():
    entries = c['entries']
    srcs = list(c.get('extra', []))
    for e in entries:
        s = f"{e['file']}:{e['line']}"
        if s not in srcs:
            srcs.append(s)
    lead = 'Registers ' if c['kind'] == 'module' else f"{c['name']}, the registerSingleton implementation of "
    if c['kind'] == 'service':
        summ = f"{c['name']}: registerSingleton implementation of " + ', '.join(e['name'] for e in entries) + '.'
    else:
        summ = 'Registers ' + '; '.join(describe(e) for e in entries) + '.'
    out_components.append({'id': cid, 'name': c['name'], 'kind': c['kind'], 'parent': 'workbench', 'summary': summ, 'sources': srcs, 'attributes': {'catalog': True}})

# ---------------- flows: catalog steps on the startup flow ----------------
steps = []
for cid, c in catalog.items():
    first = c['entries'][0] if c['entries'] else None
    src = f"{first['file']}:{first['line']}" if first else c['extra'][0]
    n_cmd = sum(1 for e in c['entries'] if e['kind'] == 'vscode-command')
    n_con = sum(1 for e in c['entries'] if e['kind'] == 'workbench-contribution')
    bits = []
    if n_cmd: bits.append(f'{n_cmd} command(s)')
    if n_con: bits.append(f'{n_con} workbench contribution(s)')
    other = len(c['entries']) - n_cmd - n_con
    if other: bits.append(f'{other} service/extension point/worker registration(s)')
    steps.append({'component': cid, 'title': f"{c['name']} registers " + ', '.join(bits), 'source': src})
for c in out_components:
    if c['id'] in deep_extra and c['id'] not in ('startup-page-runner-contribution',):
        pass
for f in flows['flows']:
    if f['id'] == 'workbench-contribs-startup':
        f['steps'] = [{'component': 'save-participants-contribution', 'title': 'SaveParticipantsContribution is registered for the Restored phase and adds the five save participants', 'source': 'src/vs/workbench/contrib/codeEditor/browser/saveParticipants.ts:465'}, {'component': 'startup-page-runner-contribution', 'title': 'StartupPageRunnerContribution is registered for the AfterRestored phase', 'source': 'src/vs/workbench/contrib/welcomeGettingStarted/browser/gettingStarted.contribution.ts:357'}] + steps

configs = list(deep['configs'])
interfaces = list(deep['interfaces'])
scenarios = list(flows['scenarios'])
fixtures = []
seed_state = {}
comp_ids = {c['id'] for c in out_components}
iface_ids = {(i['component'], i['name']) for i in interfaces}
cfg_ids = {c['id'] for c in configs}
sc_ids = {s['id'] for s in scenarios}
# Only parts this area's builder wrote (wc-*.yaml). Other files in parts/ (e.g. left by an earlier
# helper run) are ignored unless reviewed and renamed.
# Allowlist: parts built by builder.py from parts_src/<name>.py. Other files that appear in parts/
# (helper runs that were not reviewed) are ignored.
OWN = sorted(os.path.basename(x)[:-3] for x in glob.glob(os.path.join(HERE, 'parts_src', '*.py')))
part_files = [os.path.join(HERE, 'parts', f'wc-{n}.yaml') for n in OWN]
if ONLY:
    part_files = [p for p in part_files if os.path.basename(p)[3:-5] in ONLY]
for pf in part_files:
    part = yaml.safe_load(open(pf)) or {}
    pname = os.path.basename(pf)
    for c in part.get('configs', []) or []:
        if c['id'] in cfg_ids:
            continue  # first definition wins (shared within this area)
        cfg_ids.add(c['id']); configs.append(c)
    for c in part.get('components', []) or []:
        if c['id'] in comp_ids:
            if (c.get('attributes') or {}).get('boundary'):
                continue
            sys.exit(f'{pname}: duplicate component {c["id"]}')
        comp_ids.add(c['id']); out_components.append(c)
    for i in part.get('stubs', []) or []:
        k = (i['component'], i['name'])
        if k in iface_ids:
            continue
        iface_ids.add(k); interfaces.append(i)
    for i in part.get('interfaces', []) or []:
        k = (i['component'], i['name'])
        if k in iface_ids:
            sys.exit(f'{pname}: duplicate interface {k}')
        if i['component'] not in comp_ids:
            sys.exit(f'{pname}: unknown component {i["component"]}')
        iface_ids.add(k); interfaces.append(i)
    for s in part.get('scenarios', []) or []:
        if s['id'] in sc_ids:
            sys.exit(f'{pname}: duplicate scenario {s["id"]}')
        sc_ids.add(s['id']); scenarios.append(s)
    for comp, stv in (part.get('seed') or {}).items():
        if comp in seed_state:
            sys.exit(f'{pname}: seed for {comp} already given by another part')
        seed_state[comp] = stv
# align boundary stubs with the owners' definitions (decision 1)
owner_defs = {}
for ff in glob.glob(OUT + '/fragments/*.yaml'):
    if ff.endswith('workbench-contribs.yaml'):
        continue
    try:
        od = yaml.safe_load(open(ff)) or {}
    except Exception:
        continue
    for oi in od.get('interfaces', []) or []:
        if (oi.get('attributes') or {}).get('boundary'):
            continue
        comp = oi.get('component') or oi['id'].split('.')[0]
        name = oi.get('name') or oi['id'].split('.', 1)[1]
        owner_defs[(comp, name)] = oi
aligned = []
for i in interfaces:
    if (i.get('attributes') or {}).get('boundary') and (i['component'], i['name']) in owner_defs:
        o = owner_defs[(i['component'], i['name'])]
        for k in ('kind', 'request', 'response', 'errors'):
            if o.get(k) is not None:
                i[k] = o[k]
            else:
                i.pop(k, None)
        aligned.append(f"{i['component']}.{i['name']}")
json.dump(sorted(aligned), open(os.path.join(HERE, 'aligned.json'), 'w'), indent=1)
# workbench-contribs-seed: register modeled commands with platform-core's commands-registry (decision 6)
cmd_ids = {}
for i in interfaces:
    cid = (i.get('attributes') or {}).get('command')
    if cid and not (i.get('attributes') or {}).get('boundary'):
        cmd_ids[cid] = {'handler': f"{i['component']}.{i['name']}"}
seed_state['commands-registry'] = {'commands': cmd_ids}
fixtures.append({'id': 'workbench-contribs-seed', 'summary': 'workbench-contribs seed: the modeled commands of this area registered in the CommandsRegistry (keyed by command id), plus initial state of this area\'s own components.', 'state': seed_state})
# every scenario asserts on its trace or state (hollow lint)
st = re.compile(r'\b(state|trace)\b')
for s in scenarios:
    ex = s.setdefault('expect', [])
    if not any(st.search(e) for e in ex):
        if s.get('flow'):
            entry = next(f['entry']['interface'] for f in flows['flows'] if f['id'] == s['flow'])
        else:
            entry = s['steps'][0]['interface'] if 'interface' in s['steps'][0] else next(f['entry']['interface'] for f in flows['flows'] if f['id'] == s['steps'][0]['flow'])
        ex.append(f"trace.exists(e, e.type == 'call.start' && e.interface == '{entry}')")
doc = {'schema_version': 1, 'id': 'vscode', 'configs': configs, 'components': out_components, 'interfaces': interfaces, 'flows': flows['flows'], 'scenarios': scenarios, 'fixtures': fixtures}

class D(yaml.SafeDumper):
    pass
D.ignore_aliases = lambda self, data: True
def str_rep(dumper, data):
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='"')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)
D.add_representer(str, str_rep)
with open(OUTFILE or (OUT + '/fragments/workbench-contribs.yaml'), 'w') as fh:
    fh.write('# workbench-contribs fragment: every src/vs/workbench/contrib folder not owned by a more specific area.\n')
    fh.write('# Generated from hand-written deep flows plus a catalog of the remaining contribution modules; see notes/workbench-contribs.md.\n')
    yaml.dump(doc, fh, Dumper=D, sort_keys=False, width=200, allow_unicode=True)
if not OUTFILE:
    json.dump(skips, open(OUT + '/skips/workbench-contribs.json', 'w'), indent=1)
json.dump({'catalog': {k: [describe(e) + f" ({e['file']}:{e['line']})" for e in v['entries']] for k, v in catalog.items()}, 'deep_extra': {k: [describe(e) + f" ({e['file']}:{e['line']})" for e in v] for k, v in deep_extra.items()}, 'skips': skips, 'mine': len(mine)}, open(os.path.join(HERE, 'catalog.json'), 'w'), indent=1)
print('mine', len(mine), 'skipped', len(skips), 'catalog comps', len(catalog), 'components', len(out_components))

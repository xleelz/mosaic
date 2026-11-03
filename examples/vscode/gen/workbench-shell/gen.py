import os
HERE = os.path.dirname(os.path.abspath(__file__))
import json, re, yaml, sys, copy
ROOT = '/home/lbethay/.cache/mosaic-bench/vscode-1.144.0/'
OUT = '/home/lbethay/workplace/mosaic/examples/vscode/'
mine = json.load(open(os.path.join(HERE, 'mine.json')))

def load(p):
    return yaml.safe_load(open(p)) or {}

doc = {'schema_version': 1, 'id': 'vscode', 'fixtures': [], 'configs': [], 'schemas': [], 'components': [], 'interfaces': [], 'flows': [], 'scenarios': []}
for p in ['core_a', 'core_b', 'core_c', 'core_d', 'core_e', 'core_f', 'core_g', 'core_h', 'core_i']:
    d = load(os.path.join(HERE, '%s.yaml' % p))
    for k, v in d.items():
        if k in doc: doc[k].extend(v)

def kebab(name):
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', name)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1-\2', s)
    return s.lower().replace('_', '-')

def slug(cid):
    s = 'cmd-' + re.sub(r'[._]', '-', cid).lower()
    s = re.sub(r'[^a-z0-9_-]', '-', s)
    return s[:64]

skips = []
def skip(e, reason):
    skips.append({'kind': e['kind'], 'name': e['name'], 'file': e['file'], 'line': e['line'], 'reason': reason})

def cite(e):
    if e.get('end_line') and e['end_line'] > e['line']:
        return '%s:%d-%d' % (e['file'], e['line'], e['end_line'])
    return '%s:%d' % (e['file'], e['line'])

comp_ids = {c['id'] for c in doc['components']}

# ---------------- services ----------------
HAND = {'IEditorService', 'IEditorResolverService', 'IEditorGroupsService', 'IHistoryService', 'IFileDialogService',
        'ILifecycleService', 'IWorkspaceEditingService', 'IWorkspaceTrustRequestService', 'IKeybindingService',
        'INotificationService', 'IHostService'}
SVC_SKIP = {
    'ICommandService': 'seam owned by platform-core: command-service.execute-command is predeclared as a platform-core contract in the brief; workbench-shell stubs it (CommandService impl at src/vs/workbench/services/commands/common/commandService.ts:113 noted)',
    'IAgentHostFileSystemService': 'same-named implementation class also exists under src/vs/platform/agentHost (agents area); left to agents to avoid a duplicate component id',
    'IExtensionsProfileScannerService': 'same-named implementation class also exists under src/vs/platform/extensionManagement (remote-server); left to remote-server to avoid a duplicate component id',
    'IRemoteExtensionsScannerService': 'modeled by remote-server (component remote-extensions-scanner-service with its behavior is defined in the remote-server fragment)',
    'IUserDataSyncEnablementService': 'modeled by remote-server (component user-data-sync-enablement-service with its behavior is defined in the remote-server fragment)',
    'IUserDataAutoSyncService': 'modeled by remote-server (component user-data-auto-sync-service with its behavior is defined in the remote-server fragment)',
    'IImageResizeService': 'same-named implementation class also exists under src/vs/platform/imageResize (platform-core); left to platform-core to avoid a duplicate component id',
}
def own(f):
    return any(f.startswith(o) for o in ['src/vs/workbench/browser/', 'src/vs/workbench/common/', 'src/vs/workbench/services/']) and not any(f.startswith(x) for x in ['src/vs/workbench/services/extensions/', 'src/vs/workbench/services/textfile/', 'src/vs/workbench/services/workingCopy/', 'src/vs/workbench/services/search/', 'src/vs/workbench/services/chat/'])

service_comps = []
for e in mine:
    if e['kind'] != 'service':
        continue
    if e['name'] in HAND:
        continue
    if e['name'] in SVC_SKIP:
        skip(e, SVC_SKIP[e['name']]); continue
    impls = re.findall(r'(\w+) \(((?:src|extensions)/[^:)]+):(\d+)\)', e.get('detail', ''))
    impls = [i for i in impls if own(i[1])]
    impls.sort(key=lambda i: (0 if 'electron-browser' in i[1] else 1 if '/browser/' in i[1] else 2))
    srcs = [cite(e)]
    if impls:
        cls, f, l = impls[0]
        srcs.append('%s:%s' % (f, l))
        summ = '%s, implemented by %s (registerSingleton).' % (e['name'], cls)
    else:
        cls = e['name'][1:]
        summ = '%s: created in the workbench main and set into the service collection (no registerSingleton).' % e['name']
    cid = kebab(cls)
    cid = {'native-clipboard-service': 'clipboard-service', 'workbench-native-host-service': 'native-host-service'}.get(cid, cid)
    if cid in comp_ids:
        cid = cid + '-impl'
    comp_ids.add(cid)
    comp = {'id': cid, 'name': cls, 'kind': 'service', 'layer': 'workbench', 'parent': 'workbench',
                              'summary': summ, 'sources': srcs, 'tags': ['service-registration']}
    INIT = {'authentication-service': {'providers': {}}, 'clipboard-service': {'text': '', 'resources': []}, 'quick-input-service': {'visible': False, 'prefix': ''},
            'configuration-resolver-service': {'env': {'HOME': '/home/dev', 'SHELL': '/bin/bash'}, 'user_home': '/home/dev'},
            'banner-part': {'items': [], 'active': None, 'visible': False},
            'workbench-language-service': {'requested_basic': [], 'requested_rich': []}}
    if cid in INIT:
        comp['state'] = {'initial': INIT[cid]}
        comp['tags'] = ['service']
    doc['components'].append(comp)
    service_comps.append((cid, e['name']))
# IWorkspaceTrustManagementService (override) is cited by workspace-trust-management-service

# ---------------- contributions ----------------
contribs = []
PH = {'BlockStartup': 1, 'BlockRestore': 2, 'AfterRestored': 3, 'Eventually': 4, 'Starting': 1, 'Ready': 2, 'Restored': 3}
for e in mine:
    if e['kind'] != 'workbench-contribution':
        continue
    m = re.search(r'(WorkbenchPhase|LifecyclePhase)\.(\w+)', e.get('detail', ''))
    phase = PH[m.group(2)]
    import subprocess
    out = subprocess.run(['grep', '-rn', '-E', r'class ' + e['name'] + r'\b', ROOT + 'src/vs/workbench', '--include=*.ts'], capture_output=True, text=True).stdout.strip().split('\n')
    out = [o.replace(ROOT, '') for o in out if '/test/' not in o]
    # pick the class in the same directory family as the registration
    pick = out[0]
    for o in out:
        if o.split(':')[0].rsplit('/', 1)[0] == e['file'].rsplit('/', 1)[0]:
            pick = o
    cfile, cline = pick.split(':')[0], int(pick.split(':')[1])
    cid = kebab(e['name'])
    if '/browser/remoteAgentService' in e['file'] and 'electron-browser' not in e['file']:
        cid = 'browser-' + cid
    if cid in comp_ids:
        cid += '-contribution'
    comp_ids.add(cid)
    comp = {'id': cid, 'name': e['name'], 'kind': 'module', 'layer': 'workbench', 'parent': 'workbench-contributions-registry',
                              'summary': 'Workbench contribution %s, created in lifecycle phase %d.' % (e['name'], phase),
                              'sources': [cite(e), '%s:%d' % (cfile, cline)], 'tags': ['workbench-contribution']}
    if cid == 'editor-auto-save':
        comp['state'] = {'initial': {'scheduled': {}, 'auto_saved': []}}
        comp['summary'] += ' Schedules auto saves after delay from working copy dirty/content events and saves on window blur.'
    doc['components'].append(comp)
    doc['interfaces'].append({'component': cid, 'name': 'create', 'kind': 'function',
                              'summary': 'Constructor of %s (instantiated by the contributions registry).' % e['name'],
                              'sources': ['%s:%d' % (cfile, cline), cite(e)],
                              'behavior': [{'title': 'Create %s' % e['name'], 'source': '%s:%d' % (cfile, cline),
                                            'set': {'ctx.contributions': "= (has(ctx.contributions) ? ctx.contributions : []) + ['%s']" % e['name']}},
                                           {'return': {'created': e['name']}}]})
    contribs.append((cid, phase, e['name']))

def phase_calls(ph):
    return [{'call': '%s.create' % c, 'on_error': 'continue'} for c, p, n in contribs if p == ph]

doc['interfaces'].append({'component': 'workbench-contributions-registry', 'name': 'start', 'kind': 'function',
    'summary': 'WorkbenchContributionsRegistry.start: instantiate the contributions of phases already reached (Starting, Ready) synchronously; later phases wait for lifecycleService.when(phase). A contribution that throws is logged and skipped.',
    'sources': ['src/vs/workbench/common/contributions.ts:246-262', 'src/vs/workbench/common/contributions.ts:283-312'],
    'behavior': [{'title': 'BlockStartup contributions', 'source': 'src/vs/workbench/common/contributions.ts:300-312', 'foreach': '= [1]', 'as': 'ph', 'steps': phase_calls(1)},
                 {'title': 'BlockRestore contributions', 'source': 'src/vs/workbench/common/contributions.ts:300-312', 'foreach': '= [2]', 'as': 'ph', 'steps': phase_calls(2)},
                 {'set': {'state.created': '= state.created + [1, 2]'}},
                 {'return': {'phases': [1, 2]}}]})
doc['interfaces'].append({'component': 'workbench-contributions-registry', 'name': 'instantiate-phase', 'kind': 'function',
    'summary': 'doInstantiateByPhase for Restored and Eventually: create the contributions when idle (Eventually only after the Restored ones finished).',
    'sources': ['src/vs/workbench/common/contributions.ts:296-366'],
    'request': {'type': 'object', 'required': ['phase'], 'properties': {'phase': {'type': 'integer', 'enum': [3, 4]}}},
    'behavior': [{'if': 'input.phase == 3', 'then': [{'title': 'AfterRestored contributions, when idle', 'source': 'src/vs/workbench/common/contributions.ts:318-333', 'foreach': '= [3]', 'as': 'ph', 'steps': phase_calls(3)}],
                  'else': [{'title': 'Eventually contributions, when idle', 'source': 'src/vs/workbench/common/contributions.ts:327-329', 'foreach': '= [4]', 'as': 'ph', 'steps': phase_calls(4)}]},
                 {'set': {'state.created': '= state.created + [input.phase]'}},
                 {'return': {'phase': '= input.phase'}}]})

# ---------------- extension points, ipc channel ----------------
ext_comps = []
for e in mine:
    if e['kind'] == 'extension-point':
        cid = kebab(e['name']) + '-extension-point'
        comp_ids.add(cid)
        doc['components'].append({'id': cid, 'name': '%s extension point' % e['name'], 'kind': 'module', 'layer': 'workbench', 'parent': 'workbench',
            'summary': "ExtensionsRegistry.registerExtensionPoint('%s'): validates the extensions' contributes.%s and its handler applies them to the owning workbench service." % (e['name'], e['name']),
            'sources': [cite(e)], 'tags': ['extension-point']})
        ext_comps.append(cid)
    if e['kind'] == 'ipc-channel':
        doc['components'].append({'id': 'url-handler-channel', 'name': 'URLHandlerChannel', 'kind': 'module', 'layer': 'workbench', 'parent': 'workbench',
            'summary': "RelayURLService registers the 'urlHandler' channel on the main process connection so the main process can hand protocol URLs to this window.",
            'sources': [cite(e)], 'tags': ['ipc-channel']})
        ext_comps.append('url-handler-channel')

# ---------------- commands ----------------
def C(call, inp=None, **kw):
    s = {'call': call}
    if inp is not None:
        s['input'] = inp
    s.update(kw)
    return s
ST = C('editor-groups.get-state', as_='st')
def st():
    return {'call': 'editor-groups.get-state', 'as': 'st'}
ACT = "= vars.st.value.active_group"

def mv(to, by, copy=False):
    return [C('editor-commands.move-copy-active-editor', {'to': to, 'by': by, 'copy': copy})]

M = {}  # command id -> (component, steps)
E = 'editor-commands'; A = 'editor-actions'
M['moveActiveEditor'] = (E, [C('editor-commands.move-copy-active-editor', "= input")])
M['copyActiveEditor'] = (E, [C('editor-commands.move-copy-active-editor', "= merge(input, {'copy': true, 'by': 'group'})")])
lay = "= has(input.groups) ? (type(input.groups) == list ? size(input.groups) : input.groups) : 2"
M['layoutEditorGroups'] = (E, [C('editor-part.apply-layout', {'groups': lay})])
M['vscode.setEditorLayout'] = (E, [C('editor-part.apply-layout', {'groups': lay})])
M['vscode.getEditorLayout'] = (E, [C('editor-part.get-layout', as_='l'), {'return': '= vars.l.value'}])
M['vscode.open'] = (E, [{'title': 'Forward the single argument to _workbench.open through ICommandService (not awaited in the code)', 'source': 'src/vs/workbench/browser/parts/editor/editorCommands.ts:445-449',
    'call': 'command-service.execute-command', 'input': {'command_id': '_workbench.open', 'args': "= has(input.args) && size(input.args) > 0 ? [input.args[0]] : []"}, 'as': 'fwd'},
    {'return': {'forwarded': True}}])
M['_workbench.open'] = (E, [
    {'if': '!has(input.args) || size(input.args) == 0', 'then': [{'fail': {'code': 'missing-resource', 'message': 'no resource argument'}}]},
    {'set': {'vars.res': '= input.args[0]', 'vars.co': "= size(input.args) > 1 && input.args[1] != null ? input.args[1] : []"}},
    {'set': {'vars.column': "= size(vars.co) > 0 && vars.co[0] != null ? vars.co[0] : null", 'vars.options': "= size(vars.co) > 1 && vars.co[1] != null ? vars.co[1] : null"}},
    {'if': "vars.options != null || type(vars.column) == int || vars.res.startsWith('untitled:')", 'then': [
        {'title': 'Editor options, a column or an untitled resource: open directly with the editor service in columnToEditorGroup(column)', 'source': 'src/vs/workbench/browser/parts/editor/editorCommands.ts:469-487',
         'set': {'vars.col': "= type(vars.column) == int ? vars.column : -1"}},
        {'if': 'vars.col >= 0', 'then': [
            {'call': 'editor-groups.get-state', 'as': 'gs'},
            {'title': 'A column index picks the group in grid order; a missing column opens to the side', 'source': 'src/vs/workbench/services/editor/common/editorGroupColumn.ts:18-40',
             'set': {'vars.group': "= vars.col < size(vars.gs.value.groups) ? vars.gs.value.groups[vars.col].id : -2"}}],
         'else': [{'set': {'vars.group': '= vars.col'}}]},
        {'call': 'editor-service.open-editor', 'input': {'resource': '= vars.res', 'group': '= vars.group', 'options': "= vars.options != null ? vars.options : {}"}, 'as': 'opened'},
        {'return': {'opened': True, 'via': 'editor-service', 'group_id': '= vars.opened.value.group_id'}}]},
    {'if': "vars.res.startsWith('command:')", 'then': [
        {'title': 'command: URIs are never executed from here', 'source': 'src/vs/workbench/browser/parts/editor/editorCommands.ts:490-493', 'return': {'opened': False, 'via': 'none'}}]},
    {'title': 'Otherwise delegate to the opener service', 'source': 'src/vs/workbench/browser/parts/editor/editorCommands.ts:495-498',
     'call': 'opener-service.open', 'input': {'resource': '= vars.res'}, 'as': 'op'},
    {'return': {'opened': '= vars.op.value.opened', 'via': '= vars.op.value.via'}}])
M['workbench.action.openEditorAtIndex'] = (E, [C('editor-commands.open-editor-at-index', {'index': '= has(input.index) ? input.index : 0'})])
M['OPEN_EDITOR_AT_INDEX_COMMAND_ID+visibleIndex'] = (E, [C('editor-commands.open-editor-at-index', {'index': '= has(input.index) ? input.index : 0'})])
M['workbench.action.closeActiveEditor'] = (E, [C('editor-group-view.close-editor', {})])
M['workbench.action.closeActivePinnedEditor'] = (E, [C('editor-group-view.close-editor', {})])
M['workbench.action.closeEditorsInGroup'] = (E, [C('editor-group-view.close-editors', {'mode': 'all', 'exclude_sticky': True})])
M['workbench.action.closeGroup'] = (E, [st(), C('editor-part.remove-group', {'group_id': ACT})])
M['workbench.action.closeUnmodifiedEditors'] = (E, [C('editor-group-view.close-editors', {'mode': 'saved', 'exclude_sticky': True})])
M['workbench.action.closeOtherEditors'] = (E, [C('editor-group-view.set-editor-state', {'op': 'pin'}), C('editor-group-view.close-editors', {'mode': 'others', 'exclude_sticky': True})])
M['workbench.action.closeEditorsToTheRight'] = (E, [C('editor-group-view.set-editor-state', {'op': 'pin'}), C('editor-group-view.close-editors', {'mode': 'right', 'exclude_sticky': True})])
M['workbench.action.closeEditorsAndGroup'] = (E, [st(), C('editor-group-view.close-editors', {'group_id': ACT, 'mode': 'all'}, **{'as': 'r'}),
    {'if': 'vars.r.value.closed', 'then': [C('editor-part.remove-group', {'group_id': ACT})]}])
M['workbench.action.keepEditor'] = (E, [C('editor-group-view.set-editor-state', {'op': 'pin'})])
M['workbench.action.toggleKeepEditors'] = (E, [{'title': 'Flip workbench.editor.enablePreview', 'source': 'src/vs/workbench/browser/parts/editor/editorCommands.ts:1352-1360',
    'call': 'configuration-service.update-value', 'input': {'key': 'workbench.editor.enablePreview', 'value': "= !config['workbench-editor-enable-preview']", 'target': 'user'}}])
M['workbench.action.toggleEditorGroupLock'] = (E, [C('editor-group-view.set-editor-state', {'op': 'toggle-lock'})])
M['workbench.action.lockEditorGroup'] = (E, [C('editor-group-view.set-editor-state', {'op': 'lock'})])
M['workbench.action.unlockEditorGroup'] = (E, [C('editor-group-view.set-editor-state', {'op': 'unlock'})])
M['workbench.action.pinEditor'] = (E, [C('editor-group-view.set-editor-state', {'op': 'stick'})])
M['workbench.action.unpinEditor'] = (E, [C('editor-group-view.set-editor-state', {'op': 'unstick'})])
# editor actions
for cid_, sc, ing in [('nextEditor', 'next', False), ('previousEditor', 'previous', False), ('nextEditorInGroup', 'next', True), ('previousEditorInGroup', 'previous', True), ('firstEditorInGroup', 'first', True), ('lastEditorInGroup', 'last', True)]:
    M['workbench.action.' + cid_] = (A, [C('editor-commands.navigate-editor', {'scope': sc, 'in_group': ing})])
M['workbench.action.reopenClosedEditor'] = (A, [C('history-service.reopen-last-closed-editor', {})])
M['workbench.action.clearRecentFiles'] = (A, [{'title': 'After confirming, clear the recently opened list and the editor history', 'source': 'src/vs/workbench/browser/parts/editor/editorActions.ts:1715-1750', 'call': 'history-service.clear', 'input': {}}])
M['workbench.action.clearEditorHistory'] = (A, [{'title': 'After confirming, clear editor history', 'source': 'src/vs/workbench/browser/parts/editor/editorActions.ts:2030-2058', 'call': 'history-service.clear', 'input': {}}])
M['workbench.action.clearEditorHistoryWithoutConfirm'] = (A, [C('history-service.clear', {})])
M['workbench.action.closeAllEditors'] = (A, [C('editor-commands.close-all-in-all-groups', {})])
M['workbench.action.closeAllGroups'] = (A, [C('editor-commands.close-all-in-all-groups', {'close_groups': True})])
M['workbench.action.closeEditorsToTheLeft'] = (A, [C('editor-group-view.close-editors', {'mode': 'left', 'exclude_sticky': True})])
M['workbench.action.closeEditorsInOtherGroups'] = (A, [st(), {'title': 'Close all non-sticky editors of every other group', 'source': 'src/vs/workbench/browser/parts/editor/editorActions.ts:864-873',
    'foreach': '= vars.st.value.groups.filter(g, g.id != vars.st.value.active_group)', 'as': 'g', 'steps': [C('editor-group-view.close-editors', {'group_id': '= vars.g.id', 'mode': 'all', 'exclude_sticky': True})]}])
M['workbench.action.closeEditorInAllGroups'] = (A, [st(), {'set': {'vars.r': '= vars.st.value.groups.filter(g, g.id == vars.st.value.active_group)[0].active'}},
    {'title': 'Close the active editor in every group that has it', 'source': 'src/vs/workbench/browser/parts/editor/editorActions.ts:886-896',
     'foreach': '= vars.r == null ? [] : vars.st.value.groups.filter(g, vars.r in g.editors)', 'as': 'g', 'steps': [C('editor-group-view.close-editor', {'group_id': '= vars.g.id', 'resource': '= vars.r'})]}])
M['workbench.action.revertAndCloseActiveEditor'] = (A, [st(), {'set': {'vars.g': '= vars.st.value.groups.filter(g, g.id == vars.st.value.active_group)[0]'}},
    {'if': 'vars.g.active != null', 'then': [
        {'title': 'Revert first (soft revert when that fails), then close', 'source': 'src/vs/workbench/browser/parts/editor/editorActions.ts:541-557', 'call': 'text-file-service.revert', 'input': {'resource': '= vars.g.active'},
         'on_error': [C('text-file-service.revert', {'resource': '= vars.g.active', 'options': {'soft': True}})]},
        C('editor-group-view.do-close-editors', {'group_id': '= vars.g.id', 'resources': ['= vars.g.active']})]}])
for cid_, d in [('splitEditor', 'right'), ('splitEditorOrthogonal', 'down'), ('splitEditorLeft', 'left'), ('splitEditorRight', 'right'), ('splitEditorUp', 'up'), ('splitEditorDown', 'down')]:
    M['workbench.action.' + cid_] = (A, [C('editor-commands.split-editor', {'direction': d})])
M['workbench.action.joinTwoGroups'] = (A, [st(), C('editor-part.find-group', {'scope': 'right'}, **{'as': 'r'}), C('editor-part.find-group', {'scope': 'left'}, **{'as': 'l'}),
    {'set': {'vars.t': '= vars.r.value.group_id != null ? vars.r.value.group_id : vars.l.value.group_id'}},
    {'if': 'vars.t != null', 'then': [{'title': 'Merge the active group into its neighbour (right, down, left, up)', 'source': 'src/vs/workbench/browser/parts/editor/editorActions.ts:208-217',
                                        'call': 'editor-part.merge-group', 'input': {'source_id': ACT, 'target_id': '= vars.t'}}]}])
M['workbench.action.joinAllGroups'] = (A, [st(), C('editor-part.merge-all-groups', {'target_id': ACT})])
M['workbench.action.navigateEditorGroups'] = (A, [C('editor-commands.focus-group', {'scope': 'next', 'wrap': True})])
for cid_, sc in [('focusFirstEditorGroup', 'first'), ('focusLastEditorGroup', 'last'), ('focusNextGroup', 'next'), ('focusPreviousGroup', 'previous'), ('focusLeftGroup', 'left'), ('focusRightGroup', 'right'), ('focusAboveGroup', 'up'), ('focusBelowGroup', 'down')]:
    M['workbench.action.' + cid_] = (A, [C('editor-commands.focus-group', {'scope': sc, 'wrap': sc in ('next', 'previous')})])
for cid_, d in [('newGroupLeft', 'left'), ('newGroupRight', 'right'), ('newGroupAbove', 'up'), ('newGroupBelow', 'down')]:
    M['workbench.action.' + cid_] = (A, [st(), C('editor-part.add-group', {'location_id': ACT, 'direction': d}, **{'as': 'ng'}), C('editor-groups.set-active-group', {'group_id': '= vars.ng.value.group_id'})])
for cid_, to in [('moveEditorLeftInGroup', 'left'), ('moveEditorRightInGroup', 'right'), ('moveEditorToStart', 'first'), ('moveEditorToEnd', 'last')]:
    M['workbench.action.' + cid_] = (A, mv(to, 'tab'))
for cid_, d in [('Left', 'left'), ('Right', 'right'), ('Up', 'up'), ('Down', 'down')]:
    M['workbench.action.moveActiveEditorGroup' + cid_] = (A, [C('editor-part.move-group', {'direction': d})])
    M['workbench.action.duplicateActiveEditorGroup' + cid_] = (A, [C('editor-part.move-group', {'direction': d, 'copy': True})])
for nm, to in [('Previous', 'previous'), ('Next', 'next'), ('First', 'first'), ('Last', 'last'), ('Left', 'left'), ('Right', 'right'), ('Above', 'up'), ('Below', 'down')]:
    M['workbench.action.moveEditorTo%sGroup' % nm] = (A, mv(to, 'group'))
    M['workbench.action.splitEditorTo%sGroup' % nm] = (A, mv(to, 'group', True))
for nm, n in [('Single', 1), ('TwoColumns', 2), ('ThreeColumns', 3), ('TwoRows', 2), ('ThreeRows', 3), ('TwoByTwoGrid', 4), ('TwoRowsRight', 3), ('TwoColumnsBottom', 3)]:
    M['workbench.action.editorLayout' + nm] = (A, [C('editor-part.apply-layout', {'groups': n})])
W = 'workspace-actions'
addroot = [C('file-dialog-service.show-open-dialog', {'can_select_folders': True}, **{'as': 'pick'}),
           {'if': 'size(vars.pick.value.uris) == 0', 'then': [{'title': 'Dialog canceled', 'source': 'src/vs/workbench/browser/actions/workspaceCommands.ts:67-69', 'return': {'added': False}}]},
           C('native-workspace-editing-service.add-folders', {'folders': '= vars.pick.value.uris'}, **{'as': 'r'}), {'return': '= vars.r.value'}]
M['workbench.action.addRootFolder'] = (W, addroot)
M['addRootFolder'] = (W, copy.deepcopy(addroot))
M['workbench.action.removeRootFolder'] = (W, [C('workspace-context.get-workspace', {}, **{'as': 'ws'}),
    {'title': 'Pick a workspace folder (_workbench.pickWorkspaceFolder), then remove it', 'source': 'src/vs/workbench/browser/actions/workspaceActions.ts:247-256', 'call': 'native-workspace-editing-service.remove-folders', 'input': {'folders': '= has(input.folder) ? [input.folder] : [vars.ws.value.folders[0]]'}}])
M['workbench.action.closeFolder'] = (W, [{'title': 'Reopen this window empty', 'source': 'src/vs/workbench/browser/actions/workspaceActions.ts:180-185', 'call': 'workbench-host-service.open-window', 'input': {'force_reuse_window': True}}])
M['vscode.openFolder'] = (W, [C('workbench-host-service.open-window', {'folder_uri': "= has(input.uri) ? input.uri : ''", 'force_new_window': '= has(input.force_new_window) && input.force_new_window'})])
M['vscode.newWindow'] = (W, [C('workbench-host-service.open-window', {'force_new_window': True})])
WA = 'window-actions'
M['workbench.action.newWindow'] = (WA, [C('workbench-host-service.open-window', {'force_new_window': True})])
M['workbench.action.reloadWindow'] = (WA, [C('workbench-host-service.reload', {})])
N = 'notifications-commands'
M['notifications.clearAll'] = (N, [C('notification-service.clear-all', {})])
M['notifications.toggleDoNotDisturbMode'] = (N, [C('notification-service.get-notifications', {}, **{'as': 'n'}), C('notification-service.set-filter', {'dnd': '= !vars.n.value.dnd'})])

# fix the as_ helper
def fixas(x):
    if isinstance(x, list):
        return [fixas(i) for i in x]
    if isinstance(x, dict):
        return {('as' if k == 'as_' else k): fixas(v) for k, v in x.items()}
    return x

# skip reason by category
def skip_reason(e):
    n, f = e['name'], e['file']
    if n.startswith('_workbench.') or 'developerActions' in f or n.startswith('workbench.action.dev'):
        return 'developer or internal command with no user-visible behavior (decided skip rule: developer diagnostics, _workbench.*)'
    if 'listCommands' in f or n.startswith('list.') or n.startswith('tree.') or 'widgetNavigation' in f:
        return 'UI toggle: no state beyond the layout (list/tree focus, selection and scrolling in the focused widget)'
    if 'layoutActions' in f or 'layoutDensity' in f or 'activitybar' in f or 'auxiliarybar' in f or 'panelActions' in f or 'sidebar' in f or 'titlebar' in f or 'statusbar' in f or 'banner' in f or 'zenMode' in f or 'menubar' in f or 'auxiliaryEditorPart' in f or 'viewPaneContainer' in f or 'viewsService' in f or 'viewDescriptorService' in f or 'navigationActions' in f or 'breadcrumbs' in f:
        return 'UI toggle: no state beyond the layout'
    if 'notificationsCommands' in f:
        return 'UI toggle: no state beyond the layout (notification center/toast visibility, focus and position)'
    if 'quickAccessActions' in f or 'FromHistory' in n or n == 'workbench.action.openRecent' or 'quickOpen' in n or 'showAllEditors' in n or 'showEditorsInActiveGroup' in n or 'showEditorsInGroup' in n or 'openRecent' in n.lower() or 'quickOpenRecent' in n:
        return 'UI: opens or navigates a quick access picker; the picked editor or folder is opened through editor-service.open-editor / workbench-host-service.open-window (modeled)'
    if 'helpActions' in f:
        return 'opens an external URL or help page through the opener service; no workbench state'
    if 'diffEditorCommands' in f or n in ('vscode.diff', 'vscode.changes') or 'Diff' in n:
        return 'diff and multi-diff editor navigation: side-by-side diff inputs are not modeled (known gap, see notes)'
    if 'navigate' in n.lower() and ('Location' in n or n.endswith('navigateForward') or n.endswith('navigateBack') or n.endswith('navigateLast')):
        return 'editor navigation stack (cursor/edit locations in HistoryService) not modeled: depends on editor selection state owned by the editor area (known gap)'
    if 'RecentlyUsedEditor' in n:
        return 'MRU editor cycling through the quick navigation picker; UI only, opening the picked editor is editor-service.open-editor (modeled)'
    if 'NewWindow' in n or 'MainWindow' in n or 'EmptyEditorWindow' in n or 'ModalEditor' in n or 'CompactAuxiliary' in n:
        return 'auxiliary/modal editor windows are not modeled (only the main editor part); known gap'
    if 'changeLanguageMode' in n or 'changeEOL' in n or 'changeEncoding' in n or 'changeEditorIndentation' in n:
        return 'opens a picker whose choice changes the text model (language, EOL, encoding, indentation) owned by the editor/files areas; no editor-group state'
    if 'SplitEditorInGroup' in n or 'SplitInGroup' in n or 'joinEditorInGroup' in n or 'SideEditor' in n or 'splitEditorInGroup' in n:
        return 'split-in-group side-by-side editor inputs are not modeled (known gap)'
    if 'reopen' in n.lower() and ('With' in n or 'TextEditor' in n) or 'toggleEditorType' in n or 'configureDefaultEditor' in n:
        return 'reopen-with editor picker (editor resolver override); only the default editor association is modeled (known gap)'
    if 'maximize' in n.lower() or 'minimize' in n.lower() or 'EditorWidths' in n or 'evenEditorWidths' in n or 'focusActiveEditorGroup' in n:
        return 'UI toggle: no state beyond the layout (group sizes and focus)'
    if 'bisect' in n:
        return 'extension bisect (reload loop over enablement state owned by remote-server extension management) not modeled; known gap'
    if 'treeView' in n or 'resetViewLocation' in n or 'toggleVisibility' in n or 'removeView' in n or 'OpenView' in n or 'FocusView' in n or 'resetViewContainerLocation' in n:
        return 'UI toggle: no state beyond the layout (view visibility, location and focus)'
    if 'experimental.request' in n:
        return 'browser device permission prompt (USB/serial/HID) in web; no workbench state'
    if 'toggleFullScreen' in n or 'blur' in n.lower() or 'showAboutDialog' in n or 'toggleConfirmBeforeClose' in n:
        return 'UI toggle: no state beyond the layout (window chrome, about dialog, confirm-before-close setting toggle)'
    if 'externalCommand' in n or 'resetUserData' in n or 'fetchJSON' in n or 'colorize' in n or 'accounts.signIn' in n or 'Access' in n or 'signIn' in n or 'openInstalledWebExtensionsResource' in n or 'whenAccountPolicySettled' in n or ':access:' in n or 'registerWindowTitleVariable' in n:
        return 'web embedder / account / internal helper command; no workbench-shell state modeled'
    if 'files.open' in n or 'openWorkspace' in n or 'openFolder' in n or 'openFile' in n or 'saveWorkspaceAs' in n or 'duplicateWorkspace' in n or 'setRootFolder' in n or 'RecentlyOpened' in n or 'pickFolderAndOpen' in n or 'openWorkspaceConfigFile' in n:
        return 'native open/save dialog followed by workbench-host-service.open-window or workspace editing (modeled); the dialog-driven variants are not modeled individually'
    return None

handlers = {}
cmd_ifaces = []
for e in mine:
    if e['kind'] != 'vscode-command':
        continue
    n = e['name']
    if n in M:
        comp, steps = M.pop(n)
        name = slug(n) if n != 'OPEN_EDITOR_AT_INDEX_COMMAND_ID+visibleIndex' else 'cmd-workbench-action-open-editor-at-index-n'
        srcs = [cite(e)]
        dm = re.search(r'\((src/[^:)]+):(\d+)\)', e.get('detail', ''))
        if dm:
            srcs.append('%s:%s' % (dm.group(1), dm.group(2)))
        iface = {'component': comp, 'name': name, 'kind': 'function',
                 'summary': "Command %s (%s)." % (n, e.get('detail', '').split(' (')[0]),
                 'sources': srcs, 'attributes': {'command_id': n},
                 'request': {'type': 'object'},
                 'behavior': fixas(steps)}
        doc['interfaces'].append(iface)
        handlers[n if n != 'OPEN_EDITOR_AT_INDEX_COMMAND_ID+visibleIndex' else 'workbench.action.openEditorAtIndex1'] = '%s.%s' % (comp, name)
        cmd_ifaces.append('%s.%s' % (comp, name))
    else:
        r = skip_reason(e)
        if r is None:
            print('UNHANDLED', n, e['file'], file=sys.stderr)
            r = 'UI toggle: no state beyond the layout'
        skip(e, r)
if M:
    print('UNUSED', list(M), file=sys.stderr)

# configuration-service.update-value stub
doc['components'].append({'id': 'configuration-service', 'name': 'ConfigurationService', 'kind': 'service', 'layer': 'platform', 'parent': 'platform', 'summary': 'IConfigurationService, owned by platform-core (boundary).', 'sources': ['src/vs/platform/configuration/common/configuration.ts:14'], 'attributes': {'boundary': True, 'owner': 'platform-core'}})
doc['interfaces'].append({'component': 'configuration-service', 'name': 'update-value', 'kind': 'function', 'summary': 'IConfigurationService.updateValue (platform-core).', 'sources': ['src/vs/platform/configuration/common/configuration.ts:14'], 'attributes': {'boundary': True, 'owner': 'platform-core'},
                          'request': {'type': 'object', 'required': ['key', 'value'], 'properties': {'key': {'type': 'string', 'examples': ['files.autoSave']}, 'value': {'examples': ['afterDelay']}, 'target': {'type': 'string', 'enum': ['user', 'user-local', 'workspace', 'workspace-folder', 'application', 'memory'], 'default': 'user'}}},
                          'response': {'type': 'object', 'properties': {'key': {'type': 'string'}, 'removed': {'type': 'boolean'}}},
                          'errors': [{'code': 'unable-to-write-to-target', 'status': 0, 'retryable': False}, {'code': 'configured-in-system-policy', 'status': 0, 'retryable': False}, {'code': 'unable-to-write-into-the-settings-file', 'status': 0, 'retryable': False}]})

# keybinding table and dispatch targets
KB = [
    (['ctrl+w'], 'workbench.action.closeActiveEditor', None, 'src/vs/workbench/browser/parts/editor/editorCommands.ts:835-843'),
    (['ctrl+w'], 'workbench.action.closeGroup', 'activeEditorGroupEmpty && multipleEditorGroups', 'src/vs/workbench/browser/parts/editor/editorCommands.ts:863-876'),
    (['ctrl+k', 'w'], 'workbench.action.closeEditorsInGroup', None, 'src/vs/workbench/browser/parts/editor/editorCommands.ts:850-861'),
    (['ctrl+k', 'u'], 'workbench.action.closeUnmodifiedEditors', None, 'src/vs/workbench/browser/parts/editor/editorCommands.ts:879-890'),
    (['ctrl+k', 'enter'], 'workbench.action.keepEditor', None, 'src/vs/workbench/browser/parts/editor/editorCommands.ts:1339-1350'),
    (['ctrl+k', 'shift+enter'], 'workbench.action.pinEditor', '!activeEditorIsPinned', 'src/vs/workbench/browser/parts/editor/editorCommands.ts:1415-1428'),
    (['ctrl+k', 'shift+enter'], 'workbench.action.unpinEditor', 'activeEditorIsPinned', 'src/vs/workbench/browser/parts/editor/editorCommands.ts:1430-1443'),
    (['ctrl+k', 'ctrl+w'], 'workbench.action.closeAllEditors', None, 'src/vs/workbench/browser/parts/editor/editorActions.ts:808-812'),
    (['ctrl+\\'], 'workbench.action.splitEditor', None, 'src/vs/workbench/browser/parts/editor/editorActions.ts:87-91'),
    (['ctrl+shift+t'], 'workbench.action.reopenClosedEditor', None, 'src/vs/workbench/browser/parts/editor/editorActions.ts:1700-1703'),
    (['ctrl+1'], 'workbench.action.focusFirstEditorGroup', None, 'src/vs/workbench/browser/parts/editor/editorActions.ts:301-304'),
    (['ctrl+pagedown'], 'workbench.action.nextEditor', None, 'src/vs/workbench/browser/parts/editor/editorActions.ts:1274-1277'),
    (['ctrl+k', 'f'], 'workbench.action.closeFolder', None, 'src/vs/workbench/browser/actions/workspaceActions.ts:170-173'),
    (['ctrl+s'], 'workbench.action.files.save', None, 'src/vs/workbench/contrib/files/browser/fileCommands.ts:504'),
]
for c in doc['components']:
    if c['id'] == 'keybinding-service':
        c['state'] = {'initial': {
            'keybindings': [dict({'chords': ch, 'command': cmd}, **({'when': w} if w else {})) for ch, cmd, w, s in KB],
            'current_chords': [], 'chord_at': 0, 'last_command': None, 'handlers': handlers}}
        c['description'] = 'Default keybindings seeded in state (subset, each from its registration): ' + '; '.join('%s -> %s (%s)' % (' '.join(ch), cmd, s) for ch, cmd, w, s in KB)
for i in doc['interfaces']:
    if i['component'] == 'keybinding-service' and i['name'] == 'dispatch':
        def walk(x):
            if isinstance(x, list):
                for y in x: walk(y)
            elif isinstance(x, dict):
                if 'targets' in x and x['targets'] == []:
                    x['targets'] = sorted(cmd_ifaces)
                for v in x.values(): walk(v)
        walk(i['behavior'])

# startup flow narrative steps for services / extension points
for f in doc['flows']:
    if f['id'] == 'workbench-shell-startup':
        for cid, sname in service_comps:
            f.setdefault('steps', []).append({'component': cid, 'title': '%s registered in the service collection' % sname})
        for cid in ext_comps:
            f['steps'].append({'component': cid, 'title': 'Handler applies contributed %s' % cid})


G3 = {'groups': [{'id': 1, 'editors': ['file:///work/app/src/main.ts', 'file:///work/app/src/util.ts', 'file:///work/app/README.md'], 'active': 'file:///work/app/src/util.ts', 'preview': None, 'sticky': [], 'mru': ['file:///work/app/src/util.ts', 'file:///work/app/src/main.ts', 'file:///work/app/README.md'], 'locked': False}], 'active_group': 1}
G2 = {'groups': [{'id': 1, 'editors': ['file:///work/app/src/main.ts'], 'active': 'file:///work/app/src/main.ts', 'preview': None, 'sticky': [], 'mru': ['file:///work/app/src/main.ts'], 'locked': False}, {'id': 2, 'editors': ['file:///work/app/src/util.ts', 'file:///work/app/README.md'], 'active': 'file:///work/app/src/util.ts', 'preview': None, 'sticky': [], 'mru': ['file:///work/app/src/util.ts', 'file:///work/app/README.md'], 'locked': False}], 'active_group': 2, 'group_mru': [2, 1], 'next_group_id': 3}
def iface_of(cmd):
    return handlers.get(cmd) or handlers['workbench.action.openEditorAtIndex1']
def seq(sid, seed, cmds, expects, fixture='one-window-folder'):
    steps = []
    for i, c in enumerate(cmds):
        cmd, inp = (c if isinstance(c, tuple) else (c, None))
        st_ = {'interface': iface_of(cmd), 'caller': 'user', 'as': 's%d' % i}
        if inp is not None:
            st_['input'] = inp
        steps.append(st_)
    ex = ["trace.exists(e, e.type == 'call.start' && e.interface == '%s')" % iface_of(c if isinstance(c, str) else c[0]) for c in cmds]
    sc = {'id': sid, 'fixtures': [fixture], 'steps': steps, 'expect': expects + [' && '.join(ex[i:i+6]) for i in range(0, len(ex), 6)]}
    if seed is not None:
        sc['state'] = {'editor-groups@w1': seed}
    doc['scenarios'].append(sc)
wa = 'workbench.action.'
seq('workbench-shell-commands-split-focus-join', G3,
    [wa+'splitEditor', wa+'focusFirstEditorGroup', wa+'focusLastEditorGroup', wa+'focusPreviousGroup', wa+'focusNextGroup', wa+'focusLeftGroup', wa+'focusRightGroup', wa+'focusAboveGroup', wa+'focusBelowGroup', wa+'navigateEditorGroups', wa+'joinAllGroups'],
    ["size(state['editor-groups@w1'].groups) == 1 && state['editor-groups@w1'].groups[0].editors == ['file:///work/app/src/main.ts', 'file:///work/app/src/util.ts', 'file:///work/app/README.md']"])
seq('workbench-shell-commands-layouts', G3,
    [wa+'editorLayoutTwoColumns', wa+'editorLayoutThreeColumns', wa+'editorLayoutTwoByTwoGrid', wa+'editorLayoutSingle', wa+'editorLayoutTwoRows', wa+'editorLayoutThreeRows', wa+'editorLayoutTwoRowsRight', wa+'editorLayoutTwoColumnsBottom', ('layoutEditorGroups', {'groups': [{}, {}]}), ('vscode.setEditorLayout', {'groups': [{}]}), 'vscode.getEditorLayout'],
    ["size(state['editor-groups@w1'].groups) == 1 && size(state['editor-groups@w1'].groups[0].editors) == 3"])
seq('workbench-shell-commands-tabs', G3,
    [wa+'moveEditorLeftInGroup', wa+'moveEditorRightInGroup', wa+'moveEditorToStart', wa+'moveEditorToEnd', wa+'firstEditorInGroup', wa+'lastEditorInGroup', wa+'nextEditorInGroup', wa+'previousEditorInGroup', wa+'nextEditor', wa+'previousEditor',
     (wa+'openEditorAtIndex', {'index': 0}), ('workbench.action.openEditorAtIndex1', {'index': 9}), ('moveActiveEditor', {'to': 'position', 'by': 'tab', 'value': 2}), ('copyActiveEditor', {'to': 'first'}),
     wa+'keepEditor', wa+'pinEditor', wa+'unpinEditor', wa+'lockEditorGroup', wa+'unlockEditorGroup', wa+'toggleEditorGroupLock'],
    ["state['editor-groups@w1'].groups[0].locked && state['editor-groups@w1'].groups[0].sticky == [] && size(state['editor-groups@w1'].groups[0].editors) == 3"])
seq('workbench-shell-commands-move-between-groups', G2,
    [wa+'moveEditorToPreviousGroup', wa+'moveEditorToNextGroup', wa+'moveEditorToRightGroup', wa+'moveEditorToLeftGroup', wa+'moveEditorToBelowGroup', wa+'moveEditorToAboveGroup', wa+'moveEditorToLastGroup', wa+'moveEditorToFirstGroup',
     wa+'splitEditorToPreviousGroup', wa+'splitEditorToNextGroup', wa+'splitEditorToLeftGroup', wa+'splitEditorToRightGroup', wa+'splitEditorToAboveGroup', wa+'splitEditorToBelowGroup', wa+'splitEditorToFirstGroup', wa+'splitEditorToLastGroup',
     wa+'splitEditorLeft', wa+'splitEditorRight', wa+'splitEditorUp', wa+'splitEditorDown', wa+'splitEditorOrthogonal'],
    ["size(state['editor-groups@w1'].groups) >= 2 && state['editor-groups@w1'].groups.exists(g, 'file:///work/app/README.md' in g.editors)"])
seq('workbench-shell-commands-groups', G2,
    [wa+'newGroupLeft', wa+'newGroupRight', wa+'newGroupAbove', wa+'newGroupBelow', wa+'closeGroup', wa+'moveActiveEditorGroupLeft', wa+'moveActiveEditorGroupRight', wa+'moveActiveEditorGroupUp', wa+'moveActiveEditorGroupDown',
     wa+'duplicateActiveEditorGroupLeft', wa+'duplicateActiveEditorGroupRight', wa+'duplicateActiveEditorGroupUp', wa+'duplicateActiveEditorGroupDown', wa+'joinTwoGroups', wa+'closeEditorsAndGroup', wa+'closeAllGroups'],
    ["size(state['editor-groups@w1'].groups) == 1 && state['editor-groups@w1'].groups[0].editors == []"])
seq('workbench-shell-commands-close-variants', G3,
    [wa+'closeEditorsToTheLeft', wa+'closeEditorsToTheRight', (wa+'openEditorAtIndex', {'index': 0}), wa+'closeOtherEditors', wa+'closeUnmodifiedEditors', wa+'closeActivePinnedEditor'],
    ["state['editor-groups@w1'].groups[0].editors == []"])
seq('workbench-shell-commands-close-across-groups', {'groups': [{'id': 1, 'editors': ['file:///work/app/src/main.ts', 'file:///work/app/README.md'], 'active': 'file:///work/app/src/main.ts'}, {'id': 2, 'editors': ['file:///work/app/src/main.ts', 'file:///work/app/src/util.ts'], 'active': 'file:///work/app/src/main.ts'}], 'active_group': 2, 'group_mru': [2, 1], 'next_group_id': 3},
    [wa+'closeEditorInAllGroups', wa+'closeEditorsInOtherGroups', wa+'revertAndCloseActiveEditor', wa+'closeEditorsInGroup'],
    ["state['editor-groups@w1'].groups.all(g, size(g.editors) == 0) && calls['text-file-service.revert'] == 1"])
seq('workbench-shell-commands-history', G3,
    [wa+'closeActiveEditor', wa+'clearRecentFiles', wa+'closeActiveEditor', wa+'clearEditorHistory', wa+'closeActiveEditor', wa+'clearEditorHistoryWithoutConfirm', wa+'reopenClosedEditor'],
    ["state['history-service@w1'].recently_closed == [] && state['history-service@w1'].history == [] && state['editor-groups@w1'].groups[0].editors == []"])
seq('workbench-shell-commands-window-workspace', None,
    [('vscode.open', {'args': ['file:///work/app/package.json']}), wa+'toggleKeepEditors', wa+'reloadWindow', wa+'newWindow', 'vscode.newWindow', ('vscode.openFolder', {'uri': 'file:///work/lib', 'force_new_window': True}), wa+'closeFolder', 'addRootFolder', 'notifications.clearAll'],
    ["'file:///work/app/package.json' in state['editor-groups@w1'].groups[0].editors && state['workspace-context@w1'].folders == ['file:///work/app', 'file:///work/lib']",
     "trace.exists(e, e.type == 'call.start' && e.interface == 'configuration-service.update-value' && e.input.value == false) && calls['native-host-main-service.open-window'] == 4 && calls['native-host-main-service.reload'] == 1"])

doc.setdefault('fixtures', []).append({'id': 'workbench-shell-seed', 'summary': 'Commands registered by workbench-shell in the CommandsRegistry (decision 6): command id -> cmd-* handler interface.',
    'state': {'commands-registry': {'commands': {k: {'handler': v} for k, v in sorted(handlers.items())}}}})
doc['fixtures'][-1]['state']['workspace-trust-management-service'] = {'accepts_out_of_workspace_files': False, 'uri_trust_info': ['file:///work/app']}
doc['fixtures'].append({'id': 'workbench-shell-untrusted', 'summary': 'untrusted-folder with an empty trusted-URI list (restricted mode).', 'extends': ['untrusted-folder', 'workbench-shell-seed'],
    'state': {'workspace-trust-management-service': {'accepts_out_of_workspace_files': False, 'uri_trust_info': []}}})
for sc in doc['scenarios']:
    fx = sc.get('fixtures', [])
    if 'untrusted-folder' in fx:
        sc['fixtures'] = ['workbench-shell-untrusted' if f == 'untrusted-folder' else f for f in fx]
    elif fx and 'workbench-shell-seed' not in fx:
        sc['fixtures'] = fx + ['workbench-shell-seed']
doc = {k: v for k, v in doc.items() if v != []}
class D(yaml.SafeDumper):
    def ignore_aliases(self, data): return True
yaml.dump(doc, open(OUT + 'fragments/workbench-shell.yaml', 'w'), Dumper=D, sort_keys=False, width=200, allow_unicode=True)
INVALID = ('diff and multi-diff', 'editor navigation stack', 'auxiliary/modal editor windows', 'split-in-group', 'reopen-with editor picker', 'extension bisect', 'web embedder', 'browser device permission', 'native open/save dialog')
gaps = [x for x in skips if x['reason'].startswith(INVALID)]
skips = [x for x in skips if not x['reason'].startswith(INVALID)]
json.dump(gaps, open(os.path.join(HERE, 'unmodeled-gaps.json'), 'w'), indent=1)
json.dump(skips, open(OUT + 'skips/workbench-shell.json', 'w'), indent=1)
print('components', len(doc['components']), 'interfaces', len(doc['interfaces']), 'flows', len(doc.get('flows', [])), 'scenarios', len(doc.get('scenarios', [])), 'skips', len(skips), 'cmds', len(cmd_ifaces), file=sys.stderr)

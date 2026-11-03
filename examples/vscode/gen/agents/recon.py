# Reconciliation round (RECONCILE.md): owner contracts for stubs, area fixtures, services,
# contributions and commands modeled at the depth the gate asks for. Runs after build1-5,
# fix5 and extra_mcp, before fill and build6.
import glob as _glob
import json as _json
import re as _re
import yaml as _yaml

VS = '/home/lbethay/workplace/mosaic/examples/vscode'
GEN = VS + '/gen/agents'
_FR = {}


def _frag(name):
    if name not in _FR:
        _FR[name] = _yaml.safe_load(open(f'{VS}/fragments/{name}.yaml'))
    return _FR[name]


_SKEL = _yaml.safe_load(open(f'{VS}/skeleton.yaml'))


def _inline(ref, frag):
    if isinstance(ref, str):
        for d in (frag, _SKEL):
            for sc in d.get('schemas') or []:
                if sc['id'] == ref:
                    return _json.loads(_json.dumps(sc['schema']))
        raise KeyError(ref)
    return ref


def _kebab(name):
    return _re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', _re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1-\2', name)).lower()


# ------------------------------------------------------------------ 1. stubs copied from the owners
components[:] = [c for c in components if not (c.get('attributes') or {}).get('boundary')]
interfaces[:] = [i for i in interfaces if not (i.get('attributes') or {}).get('boundary')]

OWNED = {  # interface id -> owner area (its fragment defines the contract)
    'workspace-trust-management-service.is-workspace-trusted': 'workbench-shell',
    'workspace-trust-request-service.request-workspace-trust': 'workbench-shell',
    'extension-service.activate-by-event': 'exthost',
    'editor-service.open-editor': 'workbench-shell',
    'lifecycle-service.on-before-shutdown': 'workbench-shell',
    'lifecycle-service.veto': 'workbench-shell',
    'language-models-service.send-chat-request': 'chat',
    'language-models-service.select-language-models': 'chat',
    'chat-service.send-request': 'chat',
    'chat-service.start-new-local-session': 'chat',
    'native-host-main-service.open-agents-window': 'main-process',
    'native-host-main-service.get-windows': 'main-process',
    'native-host-main-service.focus-window': 'main-process',
    'native-host-service.open-window': 'workbench-shell',
    'native-host-service.close-window': 'workbench-shell',
    'configuration-service.update-value': 'platform-core',
    'clipboard-service.write-text': 'workbench-shell',
    'storage-service.store': 'platform-core',
    'storage-service.remove': 'platform-core',
    'file-service.del': 'platform-core',
    'file-service.read-file': 'platform-core',
    'file-service.write-file': 'platform-core',
    'dialog-service.confirm': 'workbench-shell',
    'notification-service.notify': 'workbench-shell',
    'command-service.execute-command': 'platform-core',
    'commands-registry.get-command': 'platform-core',
}
# Interfaces the owner has not defined yet: shapes from my call sites (shared shapes).
GUESSED = {
    'workbench-mcp-management-service.install': ('workbench-shell', obj({'name': s('github'), 'config': {'type': 'object'}, 'target': s('user')}), obj({'name': S})),
    'opener-service.open': ('platform-core', obj({'resource': s('https://github.com/microsoft/vscode/pull/1'), 'open_external': {'type': 'boolean', 'default': True}}), obj({'opened': B})),
    'automation-service.create-automation': ('chat', obj({'name': s('Nightly triage'), 'enabled': {'type': 'boolean', 'default': True}}), obj({'id': s('auto-1')})),
    'automation-service.delete-automation': ('chat', obj({'id': s('auto-1')}), obj({})),
    'automation-service.update-automation-if-unchanged': ('chat', obj({'id': s('auto-1'), 'enabled': B}), obj({})),
    'authentication-service.remove-session': ('workbench-shell', obj({'provider_id': s('github'), 'session_id': s('gh-1')}), obj({})),
    'secret-storage-service.set': ('platform-core', obj({'key': s('mcp.oauth.clientSecret'), 'value': S}), obj({})),
    'secret-storage-service.delete': ('platform-core', obj({'key': s('mcp.oauth.clientSecret')}), obj({})),
    'prompts-service.set-disabled-prompt-files': ('chat', obj({'type': s('prompt'), 'uris': {'type': 'array', 'items': S}}), obj({})),
}
_COMP_NAMES = {}
for iid, owner in OWNED.items():
    comp_id, name = iid.split('.', 1)
    src = _frag(owner)
    oi = next(i for i in src['interfaces'] if (i.get('id') or i['component'] + '.' + i['name']) == iid)
    st = {'component': comp_id, 'name': name, 'kind': oi.get('kind', 'function'), 'summary': (oi.get('summary') or iid)[:300],
          'attributes': {'boundary': True, 'owner': owner}}
    for k in ('request', 'response'):
        if oi.get(k) is not None:
            st[k] = _inline(oi[k], src)
    if oi.get('errors'):
        st['errors'] = oi['errors']
    interfaces.append(st)
    oc = next((c for c in src['components'] if c['id'] == comp_id), None)
    _COMP_NAMES[comp_id] = (oc or {}).get('name', comp_id), owner
for iid, (owner, rq, rs) in GUESSED.items():
    comp_id, name = iid.split('.', 1)
    interfaces.append({'component': comp_id, 'name': name, 'kind': 'function', 'summary': f'{iid} (boundary; the owner has not defined it yet, shape from the call sites)',
                       'attributes': {'boundary': True, 'owner': owner}, 'request': rq, 'response': rs})
    _COMP_NAMES.setdefault(comp_id, (comp_id, owner))
for cid, (nm, owner) in _COMP_NAMES.items():
    # kind and parent are left to the owner's definition (decision 7)
    components.append({'id': cid, 'name': nm, 'summary': f'Boundary stub ({owner}).', 'attributes': {'boundary': True, 'owner': owner}})


def _iface(iid):
    return next(i for i in interfaces if (i.get('id') or i['component'] + '.' + i['name']) == iid)


def _comp(cid):
    return next(c for c in components if c['id'] == cid)


# ------------------------------------------------------------------ 2. call sites aligned to the owners
# MCP registry: request-workspace-trust answers {trusted}
_r = _iface('mcp-registry.resolve-connection')
_r['behavior'] = _json.loads(_json.dumps(_r['behavior']).replace('!vars.wr.value.granted', 'vars.wr.value.trusted != true'))
# extension activation: ExthostActivateByEventRequest
_r = _iface('mcp-server-runtime.start')
for st in _r['behavior']:
    if st.get('call') == 'extension-service.activate-by-event':
        st['input'] = {'activation_event': st['input']['activation_event'], 'activation_kind': 'normal'}
# sampling: the owner's language model contract (select ids, send returns {started})
_r = _iface('mcp-sampling-service.sample')
_r['response'] = obj({'model': S, 'started': B})
_r['behavior'] = [
    {'call': 'mcp-sampling-service.get-matching-model', 'input': '= input', 'as': 'm'},
    {'title': 'sendChatRequest; only the text parts of the streamed response are kept', 'source': f'{MC}/common/mcpSamplingService.ts:82-110',
     'call': 'language-models-service.send-chat-request', 'input': {'model_id': '= vars.m.value.model', 'messages': [{'role': 'user', 'content': 'sampling request'}]}, 'as': 'resp'},
    {'return': {'model': '= vars.m.value.model', 'started': '= vars.resp.value.started'}},
]
_r = _iface('mcp-sampling-service.get-matching-model')
for st in _r['behavior']:
    if 'else' in st and st.get('if') == "'allowedModels' in vars.cfg":
        st['else'] = [{'title': 'Default models: the registered language models (models with a multiplier are dropped in code)', 'source': f'{MC}/common/mcpSamplingService.ts:264-290',
                       'call': 'language-models-service.select-language-models', 'input': {'vendor': 'copilot'}, 'as': 'ids'},
                      {'set': {'vars.models': '= vars.ids.value.ids'}}]
        st['then'] = [{'title': 'allowedModels filtered to models that exist (lookupLanguageModel)', 'source': f'{MC}/common/mcpSamplingService.ts:245',
                       'call': 'language-models-service.select-language-models', 'input': {'vendor': ''}, 'as': 'known'},
                      {'set': {'vars.models': '= vars.cfg.allowedModels.filter(m, m in vars.known.value.ids)'}}]
# chat-service.send-request: {session_resource, message}
_r = _iface('local-agent-host-sessions-provider.send-request')
for n_, st in enumerate(list(_r['behavior'])):
    if st.get('call') == 'chat-service.send-request':
        st['input'] = {'session_resource': '= vars.chat.value.session_resource', 'message': '= input.query'}
        _r['behavior'].insert(n_, {'title': 'chatService.acquireOrLoadSession(chatResource): the chat model of the session (chat has no acquire-or-load interface yet; start-new-local-session stands in)',
                                   'source': f'{BASEP}:7998-8001', 'call': 'chat-service.start-new-local-session', 'input': {'location': 'panel', 'can_use_tools': True}, 'as': 'chat'})
        break
# editor-service.open-editor: WorkbenchOpenEditorRequest (resource, group)
# native-host-main-service.open-agents-window answers {opened}
# lifecycle: subscribe to the owner's topic and answer through lifecycle-service.veto (decision 8)
_r = _iface('local-agent-host-lifecycle-contribution.on-before-shutdown')
_r['request'] = _inline('WorkbenchShutdownRequest', _frag('workbench-shell'))
_r['behavior'] = [
    {'if': "input.reason != 'quit' || !state.active_session_working",
     'then': [{'source': f'{SS}/contrib/providers/agentHost/electron-browser/localAgentHostLifecycle.contribution.ts:52-60', 'title': 'Not quitting or nothing running: no veto', 'return': {'veto': False}}]},
    {'title': 'confirmSessionShutdown', 'source': f'{SS}/contrib/providers/agentHost/electron-browser/localAgentHostLifecycle.contribution.ts:61-68',
     'choice': 'confirm_quit', 'default': 'quit', 'options': {
         'quit': [{'return': {'veto': False}}],
         'cancel': [{'title': "event.veto(..., 'veto.sessions.localAgentHost')", 'source': f'{SS}/contrib/providers/agentHost/electron-browser/localAgentHostLifecycle.contribution.ts:30-40',
                     'call': 'lifecycle-service.veto', 'input': {'id': 'veto.sessions.localAgentHost', 'veto': True}},
                    {'return': {'veto': True}}]}},
]
for sc in scenarios:
    if sc['id'] == 'agents-sessions-quit-veto-working-cancelled':
        sc['expect'].append("trace.exists(e, e.type == 'call.start' && e.interface == 'lifecycle-service.veto' && e.input.id == 'veto.sessions.localAgentHost')")

# ------------------------------------------------------------------ 3. area fixtures (decision 10)
for c in components:
    if c['id'] == 'mcp-server-runtime':
        c['state']['initial'] = {'servers': {}}
fixtures = [
    {'id': 'agents-mcp-servers', 'summary': 'one-window-folder with two MCP servers known to McpService: github (user mcp.json, trusted collection) and workspace-db (.vscode/mcp.json, trusted on nonce, never trusted yet).',
     'extends': ['one-window-folder'], 'state': {'mcp-server-runtime': {'servers': MCP_SERVERS_INITIAL}}},
]


def _cmd_registry():
    regs = {}
    for i in interfaces:
        if i.get('kind') == 'command' and i['name'].startswith('cmd-') and 'command_id' in (i.get('attributes') or {}):
            regs[i['attributes']['command_id']] = {'handler': i['component'] + '.' + i['name']}
    return regs


# ------------------------------------------------------------------ 4. services: implementation components named in the startup flows
INV = _json.load(open(f'{VS}/inventory.json'))['entries']
MINE = [e for e in INV if e.get('area') == 'agents']


def svc_comp(cid, name, parent, summary, sources, state=None):
    comp(cid, name, parent, summary, sources, kind='service', layer='process' if parent == 'agent-host' else 'ai', state=state)


# explicit services that commands call
SVC = [
    ('agent-feedback-service', 'AgentFeedbackService', f'{SS}/contrib/agentFeedback/browser/agentFeedbackService.ts:128', [f'{SS}/contrib/agentFeedback/browser/agentFeedbackService.ts:319', f'{SS}/contrib/agentFeedback/browser/agentFeedback.contribution.ts:93'],
     'Feedback comments on agent changes per session; submits accepted feedback to the agent.', {'submitted': 0, 'cleared': 0}),
    ('session-groups-service', 'SessionGroupsService', f'{SS}/services/sessions/browser/sessionGroupsService.ts:294', [f'{SS}/services/sessions/browser/sessionGroupsService.ts:309', f'{SS}/services/sessions/browser/sessionGroupsService.ts:1013'],
     'User-defined groups of sessions in the sessions list, persisted in storage.', {'groups': ['g1', 'g2']}),
    ('sessions-chat-background-service', 'SessionsChatBackgroundService', f'{SS}/services/chatBackground/browser/chatBackgroundService.ts:101', [f'{SS}/services/chatBackground/browser/chatBackgroundService.ts:122', f'{SS}/contrib/chat/browser/chat.contribution.ts:667'],
     'The Agents window chat background image and layout (written to chat.agentSessions.preferred*Background* settings).', {'background': 'none', 'layout': 'cover'}),
    ('get-started-checklist-service', 'GetStartedChecklistService', f'{SS}/contrib/getStarted/browser/getStartedChecklistService.ts:30', [f'{SS}/contrib/getStarted/browser/getStartedChecklistService.ts:103', f'{SS}/contrib/getStarted/browser/getStarted.contribution.ts:51'],
     'The get started checklist, its state stored as agentSessions.getStarted.state.', {'shown': False}),
    ('sessions-tasks-service', 'SessionsTasksService', f'{SS}/contrib/chat/browser/sessionsTasksService.ts:187', [f'{SS}/contrib/chat/browser/sessionsTasksService.ts:189', f'{SS}/contrib/chat/browser/chat.contribution.ts:661'],
     'Run tasks of a session (scripts, build, dev server), stored per session or workspace.', {'tasks': [], 'runs': 0}),
    ('agents-window-remote-agent-host-service', 'AgentsWindowRemoteAgentHostService', f'{AH}/common/remoteAgentHostService.ts:696', [f'{AH}/browser/remoteAgentHostServiceImpl.ts:1268', f'{SS}/sessions.desktop.main.ts:130'],
     'Remote agent host connections of the Agents window (WebSocket, SSH, WSL, tunnel, Mission Control).', {'connections': [], 'upgrades': 0}),
    ('ssh-remote-agent-host-service', 'SSHRemoteAgentHostService', f'{AH}/common/sshRemoteAgentHost.ts:25', [f'{AH}/electron-browser/sshRemoteAgentHostServiceImpl.ts:460', f'{AH}/electron-browser/sshRemoteAgentHostService.ts:11'],
     'SSH agent hosts: SSH config files and connections that start a remote agent host over SSH.', {'connected': [], 'config_created': False}),
    ('tunnel-agent-host-service', 'TunnelAgentHostService', f'{AH}/common/tunnelAgentHost.ts:11', [f'{AH}/common/tunnelAgentHost.ts:483-520'],
     'Dev tunnel agent hosts: lists the signed-in user\'s tunnels and connects to one.', {'connected': []}),
    ('wsl-remote-agent-host-service', 'WSLRemoteAgentHostService', f'{AH}/common/wslRemoteAgentHost.ts:82', [f'{AH}/electron-browser/wslRemoteAgentHostServiceImpl.ts:381', f'{AH}/electron-browser/wslRemoteAgentHostService.ts:11'],
     'WSL agent hosts: lists distributions and starts an agent host inside one.', {'connected': []}),
    ('ssh-host-key-trust-service', 'SSHHostKeyTrustService', f'{AH}/common/sshHostKeyTrust.ts:39', [f'{SS}/sessions.desktop.main.ts:132'],
     'Trusted SSH host keys for SSH agent hosts.', {'trusted_hosts': ['build.example.internal:22']}),
    ('remote-agent-host-location-preference-service', 'RemoteAgentHostLocationPreferenceService', f'{AH}/common/remoteAgentHostLocationPreference.ts:20', [f'{SS}/sessions.desktop.main.ts:131'],
     'Per-host preference for where a remote agent host runs.', {'preferences': {}}),
    ('changes-view-service', 'ChangesViewService', f'{SS}/contrib/changes/common/changesViewService.ts:29', [f'{SS}/contrib/changes/browser/changes.contribution.ts:149'],
     'The active session changes view: changeset selection and reviewed files.', {'reviewed': []}),
    ('session-changes-service', 'SessionChangesService', f'{SS}/contrib/changes/common/sessionChangesService.ts:14', [f'{SS}/contrib/changes/browser/changes.contribution.ts:150'],
     'Session changesets and their operations (commit, sync, pull request).', {'operations_run': []}),
]
for cid, nm, dec, more, summ, init in SVC:
    svc_comp(cid, nm, 'agents', summ, [dec] + more, state={'schema': {'type': 'object'}, 'initial': init})

cited = set()
for c in components + interfaces:
    for src in c.get('sources') or []:
        cited.add(src.split(':')[0] + ':' + (src.split(':')[1].split('-')[0] if ':' in src else ''))

OTHER_AREA_SKIPS = {}
SVC_STEPS_HOST, SVC_STEPS_WIN = [], []
_ids = {c['id'] for c in components}
for e in MINE:
    if e['kind'] != 'service':
        continue
    key = f"{e['file']}:{e['line']}"
    if key in cited:
        continue
    regs = _re.findall(r'(\w+) \((src/vs/[^:)]+):(\d+)\)', e.get('detail', ''))
    mine_regs = [r for r in regs if r[1].startswith(('src/vs/sessions/', 'src/vs/platform/'))]
    if regs and not mine_regs:
        owner = 'chat' if any('/contrib/chat/' in r[1] for r in regs) else 'workbench-shell' if any('/workbench/services/' in r[1] or r[1].startswith('src/vs/workbench/workbench.') for r in regs) else 'workbench-shell'
        OTHER_AREA_SKIPS[key] = f"another area owns the implementation: {owner} (registerSingleton {regs[0][0]} at {regs[0][1]}:{regs[0][2]})"
        continue
    impl = mine_regs[0][0] if mine_regs else e['name'][1:]
    cid = _kebab(impl)[:60]
    if cid in _ids:
        cid = (cid + '-impl')[:64]
    _ids.add(cid)
    host = e['file'].startswith(f'{AH}/node') or (e['file'].startswith(f'{AH}/common') and not regs)
    srcs = [key] + [f'{r[1]}:{r[2]}' for r in mine_regs[:1]]
    svc_comp(cid, impl, 'agent-host' if host else 'agents',
             f"{e['name']} implementation ({'built by registerAgentHostCoreServices/HostServices in the agent host' if host else 'registered with registerSingleton'}).", srcs)
    step = {'component': cid, 'title': f"Instantiate {e['name']} ({impl})",
            'source': f'{AH}/node/agentHostServices.ts:102-183' if host else (f'{mine_regs[0][1]}:{mine_regs[0][2]}' if mine_regs else key)}
    (SVC_STEPS_HOST if host else SVC_STEPS_WIN).append(step)
for f in flows:
    if f['id'] == 'agents-agent-host-startup':
        f['steps'] = [{'component': 'agent-host-main', 'title': 'createAgentHostRuntime: the service collection', 'source': f'{AH}/node/agentHostBootstrap.ts:109-251'}] + SVC_STEPS_HOST
    if f['id'] == 'agents-sessions-window-startup':
        f['steps'] = [{'component': 'sessions-workbench', 'title': 'initServices: every registerSingleton descriptor joins the service collection', 'source': f'{SS}/browser/workbench.ts:678-681'}] + SVC_STEPS_WIN
        for cid, *_ in SVC:
            f['steps'].append({'component': cid, 'title': f'Instantiate {_comp(cid)["name"]}', 'source': _comp(cid)['sources'][-1]})

# ------------------------------------------------------------------ 5. workbench contributions with their constructor behavior
_CONTRIB_CALLS = []
_seen = {}
for line in open(f'{GEN}/contribs.txt'):
    line = line.rstrip('\n')
    if not line:
        continue
    cls, reg, clsfile, clsline, ctor, desc = line.split('|')
    regfile, regline = reg.rsplit(':', 1)
    regpath = f'{SS}/{regfile}'
    if clsfile:
        clspath = ('src/vs/' + clsfile[3:]) if clsfile.startswith('../') else f'{SS}/{clsfile}'
    else:
        clspath = regpath
    cid = _kebab(cls)
    chat_owned = clsfile.startswith('../workbench/contrib/chat/')
    if cid in ('agent-host-settings-contribution', 'agent-session-settings-contribution'):
        cid = 'sessions-' + cid  # chat models the workbench classes of the same name
    if chat_owned:
        # chat owns the class (src/vs/workbench/contrib/chat); the Agents window registers it from my file
        oi = next(i for i in _frag('chat')['interfaces'] if i['component'] == cid and i['name'] == 'constructor')
        if not any(c['id'] == cid for c in components):
            components.append({'id': cid, 'name': cls, 'summary': 'Boundary stub (chat).', 'attributes': {'boundary': True, 'owner': 'chat'}})
            st = {'component': cid, 'name': 'constructor', 'kind': oi.get('kind', 'function'), 'summary': (oi.get('summary') or '')[:300], 'attributes': {'boundary': True, 'owner': 'chat'}}
            for k in ('request', 'response'):
                if oi.get(k) is not None:
                    st[k] = _inline(oi[k], _frag('chat'))
            interfaces.append(st)
        rid = (cid + '-registration')[:64]
        comp(rid, cls + ' (Agents window registration)', 'agents', f'The Agents window registers chat\'s {cls} at AfterRestored. ' + desc + '.', [f'{regpath}:{regline}'])
        iface(rid, 'start', f'registerWorkbenchContribution2 in the Agents window: instantiates chat\'s {cls}.', [f'{regpath}:{regline}'],
              request=obj({}), response=obj({'started': B}),
              behavior=[{'title': desc, 'source': f'{regpath}:{regline}', 'call': cid + '.constructor'}, {'return': {'started': True}}])
        _CONTRIB_CALLS.append(rid + '.start')
        _ids.add(rid)
        continue
    if cid in _ids:
        cid = (cid + ('-desktop' if 'desktop' in regfile else '-web' if 'web' in regfile else '-2'))[:64]
    _ids.add(cid)
    comp(cid, cls, 'agents', desc + '.', [f'{clspath}:{clsline}', f'{regpath}:{regline}'])
    iface(cid, 'start', f'Constructor (registerWorkbenchContribution2): {desc}.', [f'{clspath}:{ctor}', f'{regpath}:{regline}'],
          request=obj({}), response=obj({'started': B}),
          behavior=[{'title': desc, 'source': f'{clspath}:{ctor}', 'set': {f'ctx.contrib_{cid.replace("-", "_")}': True}},
                    {'return': {'started': True}}])
    _CONTRIB_CALLS.append(cid + '.start')
_wb = _iface('sessions-workbench.startup')
_ret = _wb['behavior'].pop()
_wb['behavior'].append({'title': 'Remaining Agents window contributions, instantiated by phase', 'source': f'{SS}/browser/workbench.ts:595',
                        'foreach': _CONTRIB_CALLS, 'as': 'contrib', 'max': 200,
                        'steps': [{'call': '= vars.contrib', 'targets': _CONTRIB_CALLS}]})
_wb['behavior'].append(_ret)

for sc in scenarios:
    if sc['id'] == 'agents-mcp-sampling-then-read-config':
        sc['expect'] = [x for x in sc['expect'] if 'gpt-4o-mini' not in x]
for f in flows:
    if f['id'] == 'agents-sessions-quit-veto':
        f['entry']['input'] = {'reason': 'quit', 'window_id': 'w1'}

for sc in scenarios:
    if sc['id'] == 'agents-mcp-sampling-outside-chat-configured':
        sc['expect'] = ["result.ok", "result.value.model == 'copilot/gpt-4.1'", "!trace.exists(e, e.type == 'choice' && e.key == 'mcp-sampling-service.get-matching-model.allow_prompt')"]

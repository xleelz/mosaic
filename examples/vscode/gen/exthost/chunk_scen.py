# ---- exthost-seed fixture and generated scenarios
SEED_REG = {}
for a in owner_docs:  # nothing from other areas; the seed mirrors fixtures.yaml one-window-folder
    pass
fx = yaml.safe_load(open(OUT + 'fixtures.yaml'))
for f in fx['fixtures']:
    if f['id'] == 'one-window-folder':
        for k, v in f['state']['extension-registry@w1']['extensions'].items():
            SEED_REG[k] = {'identifier': k, 'activation_events': v.get('activation_events', []), 'main': v.get('main', ''), 'extension_dependencies': v.get('extension_dependencies', [])}
doc['fixtures'] = [{'id': 'exthost-seed',
                    'summary': "The extension host's own registry (ExtHostExtensionService._globalRegistry/_myRegistry, filled from the init data), mirroring the extensions one-window-folder registers in the window.",
                    'state': {'ext-host-extension-service': {'registry': SEED_REG}}}]
def default_for(n, sch):
    t = sch.get('type')
    if n == 'extension_id': return 'vscode.git'
    if sch.get('format') == 'uri': return 'file:///work/app/src/main.ts'
    if 'examples' in sch: return sch['examples'][0]
    return {'string': 'smoke', 'integer': 1, 'boolean': False, 'array': []}.get(t, {})
SPECIAL_IN = {
 'commands-execute-command': {'command': 'noop', 'rest': []},
 'commands-register-command': {'command': 'smoke.hello', 'callback': {}},
 'commands-register-text-editor-command': {'command': 'smoke.editorHello', 'callback': {}},
 'window-show-information-message': {'message': 'Smoke', 'items': [], 'options': {'modal': False}},
 'window-show-warning-message': {'message': 'Smoke', 'items': [], 'options': {'modal': False}},
 'window-show-error-message': {'message': 'Smoke', 'items': [], 'options': {'modal': False}},
 'workspace-apply-edit': {'edit': {'edits': [{'resource': 'file:///work/app/src/main.ts', 'text': '// smoke\n'}]}, 'metadata': {'is_refactoring': False}},
 'scm-create-source-control': {'id': 'smoke-scm', 'label': 'Smoke', 'root_uri': 'file:///work/app'},
 'window-create-terminal': {'name': 'smoke'},
 'debug-start-debugging': {'folder': {}, 'name_or_configuration': {'type': 'node', 'request': 'launch', 'name': 'Launch'}},
 'debug-add-breakpoints': {'breakpoints': [{'id': 'bp-1', 'uri': 'file:///work/app/src/main.ts', 'line': 2}]},
 'debug-remove-breakpoints': {'breakpoints': [{'id': 'bp-1'}]},
 'tasks-execute-task': {'task': {'label': 'build', 'type': 'shell'}},
 'window-create-output-channel': {'name': 'Smoke'},
 'workspace-open-text-document': {'uri': 'file:///work/app/src/main.ts'},
 'window-register-uri-handler': {'handler': {}},
 'extensions-get-extension': {'extension_id': 'vscode.git'},
 'languages-match': {'selector': 'typescript', 'document': {'language_id': 'typescript'}},
}
by_ns = {}
for e in api_entries:
    _, ns, fn = e['name'].split('.')
    nm = f'{ns}-{kebab(fn)}'
    req = apiif[nm]['request']
    inp = {k: default_for(k, req['properties'][k]) for k in req.get('required', [])}
    inp.update(SPECIAL_IN.get(nm, {}))
    inp.setdefault('extension_id', 'vscode.git')
    by_ns.setdefault(ns, []).append((nm, inp))
for ns, items in by_ns.items():
    for chunk_i in range(0, len(items), 12):
        part = items[chunk_i:chunk_i + 12]
        sid = f'exthost-api-smoke-{ns}' + (f'-{chunk_i // 12 + 1}' if len(items) > 12 else '')
        steps = [{'interface': f'vscode-api.{nm}', 'caller': 'third-party-extension', 'as': f's{k}', 'input': inp} for k, (nm, inp) in enumerate(part)]
        exp = [' && '.join(f'steps.s{k}.result.ok' for k in range(len(part)))]
        exp.append(' && '.join(f"trace.exists(e, e.type == 'call.start' && e.interface == 'vscode-api.{nm}' && e.instance == 'eh1')" for nm, _ in part))
        if ns == 'languages':
            n_reg = sum(1 for nm, _ in part if nm.startswith('languages-register') or nm == 'languages-set-language-configuration')
            exp.append(f"size(state['ext-host-language-features@eh1'].adapters) == {n_reg}")
        scen.append({'id': sid, 'flow': 'exthost-api-call', 'name': f'Every vscode.{ns} function forwards through its ExtHost service',
                     'fixtures': ['dirty-editor' if ns == 'workspace' else 'one-window-folder'], 'steps': steps, 'expect': exp})
# stateful customers
order = {'add': 0, 'flag': 1, 'update': 1, 'use': 2, 'remove': 3}
for comp, items in stateful_steps.items():
    items = sorted(items, key=lambda x: order[x[2]])
    steps = []
    for nm, key, kind in items:
        if kind == 'use':
            steps.append({'interface': f'{comp}.{nm}', 'caller': 'extension-host-manager', 'as': f'u{len(steps)}', 'input': {key: 99}})
    pre = len(steps)
    for k, (nm, key, kind) in enumerate(items):
        inp = {key: 1} if key else {}
        steps.append({'interface': f'{comp}.{nm}', 'caller': 'extension-host-manager', 'as': f's{k}', 'input': inp})
    exp = [' && '.join(f'steps.s{k}.result.ok' for k in range(len(items))),
           f"size(state['{comp}@w1'].handles) == 0"]
    uses = [k for k, it in enumerate(items) if it[2] == 'use']
    if uses and any(it[2] == 'add' for it in items):
        exp.append(f"!steps.s{uses[0]}.result.value.ignored")
    if pre:
        exp.append(' && '.join(f'steps.u{k}.result.value.ignored' for k in range(pre)))
    scen.append({'id': f'exthost-{comp}-lifecycle', 'flow': 'exthost-rpc-customers', 'name': f'{byid[comp]["name"]}: create, use and dispose per-handle objects',
                 'fixtures': ['one-window-folder'], 'steps': steps, 'expect': exp})
for s in scen:
    if s['id'] == 'exthost-api-smoke-tasks': s['fixtures'] = ['full-window']
    if s['id'] == 'exthost-api-smoke-window-2': s['fixtures'] = ['full-two-windows']
    if s['id'] == 'exthost-api-call-apply-edit': s['fixtures'] = ['full-dirty-editor']
    fxl = s.setdefault('fixtures', ['one-window-folder'])
    if 'exthost-seed' not in fxl: fxl.append('exthost-seed')

scen.append({'id': 'exthost-debug-adapter-relay', 'flow': 'exthost-api-call', 'name': 'DAP relay through the extension host ($startDASession, $sendDAMessage, $stopDASession)',
  'fixtures': ['one-window-folder', 'exthost-seed'],
  'steps': [
    {'interface': 'ext-host-debug-service.send-da-message', 'caller': 'main-thread-debug-service', 'on': 'eh1', 'as': 'early', 'input': {'handle': 1, 'command': 'initialize', 'arguments': {}}},
    {'interface': 'ext-host-debug-service.start-da-session', 'caller': 'main-thread-debug-service', 'on': 'eh1', 'as': 'start', 'input': {'handle': 1, 'session_id': 'session-1', 'type': 'node'}},
    {'interface': 'ext-host-debug-service.send-da-message', 'caller': 'main-thread-debug-service', 'on': 'eh1', 'as': 'init', 'input': {'handle': 1, 'command': 'initialize', 'arguments': {}}},
    {'interface': 'ext-host-debug-service.stop-da-session', 'caller': 'main-thread-debug-service', 'on': 'eh1', 'as': 'stop', 'input': {'handle': 1}}],
  'expect': ["steps.early.result.ok && !has(steps.early.result.value.success)", "steps.init.result.ok && steps.init.result.value.success",
             "calls['debug-adapter.handle-request'] == 1", "size(state['ext-host-debug-service@eh1'].adapters) == 0"]})
scen.append({'id': 'exthost-api-unknown-extension', 'flow': 'exthost-api-call', 'name': 'getExtension and $activate for an id the host does not know',
  'fixtures': ['one-window-folder', 'exthost-seed'],
  'steps': [
    {'interface': 'vscode-api.extensions-get-extension', 'caller': 'third-party-extension', 'as': 'get', 'input': {'extension_id': 'acme.unknown'}},
    {'interface': 'ext-host-extension-service.activate', 'caller': 'extension-host-manager', 'on': 'eh1', 'as': 'act', 'input': {'extension_id': 'acme.unknown', 'reason': {'startup': False, 'extension_id': 'acme.unknown', 'activation_event': 'onCommand:x'}}}],
  'expect': ["!steps.get.result.value.found && !steps.act.result.value.activated", "calls['extensions-activator.handle-activation-request'] == 0 && size(state['extensions-activator@eh1'].operations) == 0"]})

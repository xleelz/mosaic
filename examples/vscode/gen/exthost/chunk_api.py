# ---- boundary stubs, copied from the owners' fragments (decision 1)
import glob
FR = OUT + 'fragments/'
skel = yaml.safe_load(open(OUT + 'skeleton.yaml'))
skel_comp = {c['id'] for c in skel['components']}
skel_schema = {s['id'] for s in skel.get('schemas', [])}
owner_docs = {}
for f in sorted(glob.glob(FR + '*.yaml')):
    a = os.path.basename(f)[:-5]
    if a != 'exthost': owner_docs[a] = fixkeys(yaml.safe_load(open(f)))
def owner_iface(iid):
    for a, d in owner_docs.items():
        for i in d.get('interfaces', []):
            if (i.get('id') or f"{i['component']}.{i['name']}") == iid and not (i.get('attributes') or {}).get('boundary'):
                return a, d, i
    return None, None, None
def resolve(v, d):
    if isinstance(v, str) and v not in skel_schema:
        for s in d.get('schemas', []):
            if s['id'] == v: return resolve(copy.deepcopy(s['schema']), d)
        return v
    if isinstance(v, dict):
        if '$ref' in v and isinstance(v['$ref'], str) and v['$ref'] not in skel_schema and len(v) == 1:
            return resolve(v['$ref'], d)
        return {k: resolve(x, d) for k, x in v.items()}
    if isinstance(v, list): return [resolve(x, d) for x in v]
    return v
def copy_comp(cid, owner):
    if cid in byid or cid in skel_comp: return
    for a, d in owner_docs.items():
        for c in d.get('components', []):
            if c['id'] == cid and not (c.get('attributes') or {}).get('boundary'):
                nc = {'id': cid, 'kind': c.get('kind', 'service'), 'parent': c.get('parent')}
                if c.get('name'): nc['name'] = c['name']
                nc['summary'] = f'Boundary stub; modeled by {a}.'
                nc['attributes'] = {'boundary': True, 'owner': a}
                if not nc['parent']: del nc['parent']
                comps.append(nc); byid[cid] = nc
                if nc.get('parent'): copy_comp(nc['parent'], a)
                return
    raise SystemExit('no owner component for ' + cid)
FALLBACK_RES = {'editor-service.save': {'type': 'object', 'properties': {'success': {'type': 'boolean', 'default': True}}},
                'editor-service.save-all': {'type': 'object', 'properties': {'saved': {'type': 'boolean', 'default': True}}},
                'bulk-edit-service.apply': {'type': 'object', 'properties': {'is_applied': {'type': 'boolean', 'default': True}, 'applied': {'type': 'integer'}}},
                'dialog-service.confirm': {'type': 'object', 'properties': {'confirmed': {'type': 'boolean', 'default': True}, 'checkbox_checked': {'type': 'boolean', 'default': False}}}}
def stub(iid):
    a, d, i = owner_iface(iid)
    if not i: raise SystemExit('no owner for ' + iid)
    comp, name = iid.split('.', 1)
    copy_comp(comp, a)
    n = {'component': comp, 'name': name, 'kind': i.get('kind'), 'attributes': {'boundary': True, 'owner': a}}
    for k in ('request', 'response', 'errors'):
        if i.get(k) is not None: n[k] = resolve(copy.deepcopy(i[k]), d)
    if iid in FALLBACK_RES: n['response'] = FALLBACK_RES[iid]
    ifaces.append(n)
for iid in ['command-service.execute-command', 'text-file-service.save', 'text-file-service.read', 'editor-service.save', 'editor-service.save-all',
            'editor-service.open-editor', 'notification-service.notify', 'notification-service.prompt', 'notification-service.status',
            'dialog-service.confirm', 'dialog-service.prompt', 'quick-input-service.pick', 'native-host-service.close-window', 'bulk-edit-service.apply',
            'extension-host-starter.create-extension-host', 'extension-host-starter.start', 'scm-service.register-scm-provider',
            'terminal-service.create-terminal', 'debug-service.start-debugging', 'debug-service.stop-session', 'debug-service.add-breakpoints',
            'debug-service.remove-breakpoints', 'task-service.execute-task', 'file-dialog-service.show-open-dialog',
            'output-service.on-did-register-channel', 'language-features-service.register-provider', 'lifecycle-service.on-will-shutdown',
            'debug-adapter.handle-request']:
    stub(iid)

add_comp('ext-host-debug-service', state={'schema': {'type': 'object', 'properties': {'adapters': {'type': 'object'}}}, 'initial': {'adapters': {}}})

# ---- customers: constructor interfaces, created by ExtensionHostManager._createExtensionHostCustomers
cust_calls = []
for cid in customer_ids:
    ifaces.append({'component': cid, 'name': 'create', 'kind': 'function',
                   'summary': f"new {byid[cid]['name']}(extHostContext): instantiated for each extension host and registered on its RPC protocol.",
                   'sources': [byid[cid]['sources'][0]], 'behavior': [{'return': {'customer': byid[cid]['name']}}]})
    cust_calls.append({'call': f'{cid}.create'})
ifaces.append({'component': 'extension-host-manager', 'name': 'create-customers', 'kind': 'function',
               'summary': '_createExtensionHostCustomers: create every named customer (rpcProtocol.set) and every unnamed customer, then assert no MainContext proxy is missing.',
               'sources': ['src/vs/workbench/services/extensions/common/extensionHostManager.ts:249-318'], 'behavior': cust_calls})

# ---- vscode-api interfaces: parameters from vscode.d.ts (decision 4)
api_params = json.load(open(HERE + 'api_params.json'))
lf = json.load(open(HERE + 'lf.json'))
for i in L('core_ifaces_vscode_api.yaml')['interfaces']: ifaces.append(i)
apiif = {i['name']: i for i in ifaces if i['component'] == 'vscode-api'}
def req_schema(api):
    p = api_params[api]
    props = copy.deepcopy(p['properties'])
    if 'extension_id' not in props:
        props['extension_id'] = {'type': 'string', 'examples': ['vscode.git'], 'description': 'the calling extension (implicit: each extension gets its own vscode namespace)'}
    for k, v in props.items():
        if v.get('format') == 'uri': v.setdefault('examples', ['file:///work/app/src/main.ts'])
    if api == 'vscode.workspace.applyEdit':
        props['edit'] = {'type': 'object', 'description': props['edit']['description'], 'properties': {'edits': {'type': 'array', 'items': {'type': 'object', 'properties': {'resource': {'type': 'string', 'examples': ['file:///work/app/src/util.ts']}, 'text': {'type': 'string'}}}, 'default': [{'resource': 'file:///work/app/src/util.ts', 'text': '// edited\n'}]}}}
        props['metadata'] = {'type': 'object', 'description': props['metadata']['description'], 'properties': {'is_refactoring': {'type': 'boolean', 'default': False}}}
    if api == 'vscode.debug.addBreakpoints' or api == 'vscode.debug.removeBreakpoints':
        props['breakpoints']['items'] = {'type': 'object', 'properties': {'id': {'type': 'string', 'examples': ['bp-1']}, 'uri': {'type': 'string', 'examples': ['file:///work/app/src/main.ts']}, 'line': {'type': 'integer', 'examples': [2]}}}
    return {'type': 'object', 'required': sorted(set(p['required']) | {'extension_id'}), 'properties': props}
def var2comp(v):
    special = {'extHostComment': 'ext-host-comments', 'extHostMessageService': 'ext-host-message-service', 'extHostLogService': 'ext-host-log-service',
               'extHostFileSystemEvent': 'ext-host-file-system-event-service', 'extHostApiDeprecation': 'ext-host-api-deprecation-service',
               'extHostLocalization': 'ext-host-localization-service', 'extHostMcp': 'ext-host-mcp-service', 'extHostUrls': 'ext-host-urls',
               'extHostConsumerFileSystem': 'ext-host-consumer-file-system'}
    return special.get(v, kebab(v[0].upper() + v[1:]))
API_IMPL = 'src/vs/workbench/api/common/extHost.api.impl.ts'
impl_src = open(ROOT + API_IMPL).read()
def ensure_eh_comp(var):
    cid = var2comp(var)
    if cid not in byid:
        m = re.search(r'\b(?:const )?%s = ' % var, impl_src)
        ln = impl_src[:m.start()].count('\n') + 1 if m else 152
        add_comp(cid, name=var[0].upper() + var[1:], kind='module', layer='extensions', parent='exthost-runtime',
                 summary=f"{var}: extension host side of an API area, created in createApiFactoryAndRegisterActors.", sources=[f"{API_IMPL}:{ln}"])
    return cid
def find_method(cid, meth):
    """Line of `meth(` in the class file of an ext-host component, else None."""
    files = [s.split(':')[0] for s in byid[cid].get('sources', []) if s.startswith('src/vs/workbench/api/common/') and 'api.impl' not in s]
    cls = byid[cid].get('name', '')
    cand = files or [f[len(ROOT):] for f in glob.glob(ROOT + 'src/vs/workbench/api/common/extHost*.ts') if re.search(r'class %s\b' % re.escape(cls), open(f).read())]
    for f in cand:
        s = open(ROOT + f).read()
        m = re.search(r'\n\t(?:public |async |override )*%s\s*(?:<[^(\n]*>)?\(' % re.escape(meth), s)
        if m: return f"{f}:{s[:m.start()].count(chr(10)) + 2}"
    return None

# wired rows: (api, eh var, eh method, main-thread comp, shape, rpc, owner iface, owner input, result)
WIRED = [
 ('vscode.scm.createSourceControl', 'extHostSCM', 'createSourceControl', 'main-thread-scm', 'MainThreadSCMShape', '$registerSourceControl', 'scm-service.register-scm-provider',
  {'id': "= input.id", 'label': "= input.label", 'root_uri': "= has(input.root_uri) ? input.root_uri : 'file:///work/app'"}, {'disposable_id': "= 'scm:' + input.id"}),
 ('vscode.window.createTerminal', 'extHostTerminalService', 'createTerminalFromOptions', 'main-thread-terminal-service', 'MainThreadTerminalServiceShape', '$createTerminal', 'terminal-service.create-terminal',
  {'name': "= has(input.name) ? input.name : 'bash'", 'executable': "= has(input.shell_path) ? input.shell_path : '/bin/bash'", 'args': [], 'cwd': 'file:///work/app'}, {'disposable_id': "= 'terminal:' + (has(input.name) ? input.name : 'bash')"}),
 ('vscode.debug.startDebugging', 'extHostDebugService', 'startDebugging', 'main-thread-debug-service', 'MainThreadDebugServiceShape', '$startDebugging', 'debug-service.start-debugging',
  {'config': "= has(input.name_or_configuration) ? input.name_or_configuration : null", 'no_debug': False, 'started_by_user': False}, {'value': "= has(vars.o.value.started) ? vars.o.value.started : true"}),
 ('vscode.debug.stopDebugging', 'extHostDebugService', 'stopDebugging', 'main-thread-debug-service', 'MainThreadDebugServiceShape', '$stopDebugging', 'debug-service.stop-session',
  {'session_id': None, 'disconnect': False}, {'value': True}),
 ('vscode.debug.addBreakpoints', 'extHostDebugService', 'addBreakpoints', 'main-thread-debug-service', 'MainThreadDebugServiceShape', '$registerBreakpoints', 'debug-service.add-breakpoints',
  {'uri': "= size(input.breakpoints) > 0 && has(input.breakpoints[0].uri) ? input.breakpoints[0].uri : 'file:///work/app/src/main.ts'", 'breakpoints': "= input.breakpoints.map(b, {'line_number': has(b.line) ? b.line : 1})"}, {'value': True}),
 ('vscode.debug.removeBreakpoints', 'extHostDebugService', 'removeBreakpoints', 'main-thread-debug-service', 'MainThreadDebugServiceShape', '$unregisterBreakpoints', 'debug-service.remove-breakpoints',
  {'ids': "= input.breakpoints.map(b, has(b.id) ? b.id : '')"}, {'value': True}),
 ('vscode.tasks.executeTask', 'extHostTask', 'executeTask', 'main-thread-task', 'MainThreadTaskShape', '$executeTask', 'task-service.execute-task',
  {'task': "= input.task", 'run_source': 'extension'}, {'value': "= vars.o.value"}),
 ('vscode.workspace.saveAll', 'extHostWorkspace', 'saveAll', 'main-thread-workspace', 'MainThreadWorkspaceShape', '$saveAll', 'editor-service.save-all',
  {'reason': 'explicit'}, {'value': "= has(vars.o.value.saved) ? vars.o.value.saved : false"}),
 ('vscode.window.showOpenDialog', 'extHostDialogs', 'showOpenDialog', 'main-thread-dialogs', 'MainThreadDiaglogsShape', '$showOpenDialog', 'file-dialog-service.show-open-dialog',
  {'can_select_folders': "= has(input.options) && has(input.options.can_select_folders) && input.options.can_select_folders"}, {'value': "= has(vars.o.value.uris) ? vars.o.value.uris : []"}),
 ('vscode.window.createOutputChannel', 'extHostOutputService', 'createOutputChannel', 'main-thread-output-service', 'MainThreadOutputServiceShape', '$register', 'output-service.on-did-register-channel',
  {'id': "= 'extension-output-' + input.extension_id + '-#1-' + input.name", 'label': "= input.name", 'log': False, 'user': False}, {'disposable_id': "= 'extension-output-' + input.extension_id + '-#1-' + input.name"}),
 ('vscode.workspace.openTextDocument', 'extHostDocuments', 'ensureDocumentData', 'main-thread-documents', 'MainThreadDocumentsShape', '$tryOpenDocument', 'text-file-service.read',
  {'resource': "= has(input.uri) ? input.uri : (has(input.path) ? 'file://' + input.path : 'file:///work/app/src/main.ts')"}, {'value': "= has(input.uri) ? input.uri : (has(input.path) ? 'file://' + input.path : 'file:///work/app/src/main.ts')"}),
]
proto_line = {e['name']: e['line'] for e in mine if e['kind'] == 'exthost-rpc'}
mt_files = {'main-thread-scm': 'mainThreadSCM.ts', 'main-thread-terminal-service': 'mainThreadTerminalService.ts', 'main-thread-debug-service': 'mainThreadDebugService.ts',
            'main-thread-task': 'mainThreadTask.ts', 'main-thread-workspace': 'mainThreadWorkspace.ts', 'main-thread-dialogs': 'mainThreadDialogs.ts',
            'main-thread-output-service': 'mainThreadOutputService.ts', 'main-thread-documents': 'mainThreadDocuments.ts', 'main-thread-language-features': 'mainThreadLanguageFeatures.ts',
            'main-thread-comments': 'mainThreadComments.ts', 'main-thread-quick-open': 'mainThreadQuickOpen.ts'}
def mt_line(comp, rpc):
    f = 'src/vs/workbench/api/browser/' + mt_files[comp]
    s = open(ROOT + f).read()
    m = re.search(r'\n\t(?:public |async |override )*%s\s*(?:<[^(\n]*>)?\(' % re.escape(rpc), s)
    if not m: raise SystemExit(f'no {rpc} in {f}')
    return f"{f}:{s[:m.start()].count(chr(10)) + 2}"
W = chr(39) + 'w' + chr(39)
ON_W = "= 'w' + self.substring(2)"
api_behaviors = {}
for api, var, meth, mt, shape, rpc, owner, oin, result in WIRED:
    eh = ensure_eh_comp(var)
    ehm = kebab(meth); mtn = kebab(rpc[1:])
    _, ns, fn = api.split('.')
    api_behaviors[f'{ns}-{kebab(fn)}'] = (f'{eh}.{ehm}', f"{var}.{meth}")
    if not any(i['component'] == eh and i['name'] == ehm for i in ifaces):
        src = find_method(eh, meth)
        ifaces.append({'component': eh, 'name': ehm, 'kind': 'function', 'summary': f"{var}.{meth}: convert the API arguments and call {rpc} on the window.",
                       'sources': [src] if src else [f"{API_IMPL}:{api_lines[api][0]}"], 'request': req_schema(api), 'response': 'ExthostApiResult',
                       'behavior': [{'call': f'{mt}.{mtn}', 'on': ON_W, 'input': '= input', 'as': 'r'}, {'return': '= vars.r.value'}]})
    o_area, o_doc, oi = owner_iface(owner)
    oprops = (resolve(copy.deepcopy(oi.get('request')), o_doc) or {}).get('properties', {}) if oi else {}
    oin = dict(oin)
    for pn, ps in oprops.items():
        if pn not in oin:
            t = ps.get('type'); t = t[0] if isinstance(t, list) else t
            oin[pn] = ps['default'] if 'default' in ps else {'boolean': False, 'string': '', 'array': [], 'integer': 0}.get(t)
    if not any(i['component'] == mt and i['name'] == mtn for i in ifaces):
        ifaces.append({'component': mt, 'name': mtn, 'kind': 'rpc', 'attributes': {'shape': shape},
                       'summary': f"{rpc}: forwards to {owner} (the owning area's service).",
                       'sources': [f"src/vs/workbench/api/common/extHost.protocol.ts:{proto_line[shape + '.' + rpc]}", mt_line(mt, rpc)],
                       'request': req_schema(api), 'response': 'ExthostApiResult',
                       'behavior': [{'call': owner, 'input': oin, 'as': 'o'}, {'return': result}]})
# languages registration
add_comp('ext-host-language-features', name='ExtHostLanguageFeatures', kind='module', layer='extensions', parent='exthost-runtime',
         summary='Holds the provider adapters extensions register, by handle, and registers each with the window ($register*).',
         sources=['src/vs/workbench/api/common/extHostLanguageFeatures.ts:2227'],
         state={'schema': {'type': 'object', 'properties': {'next_handle': {'type': 'integer'}, 'adapters': {'type': 'object'}}}, 'initial': {'next_handle': 0, 'adapters': {}}})
for api, info in lf.items():
    _, ns, fn = api.split('.')
    feat = re.sub(r'^(register|set)', '', info['rpc'][1:])
    feat = kebab(re.sub(r'(Support|Provider)$', '', feat))
    ehm = kebab(info['method']); mtn = kebab(info['rpc'][1:])
    api_behaviors[f'{ns}-{kebab(fn)}'] = (f'ext-host-language-features.{ehm}', f"extHostLanguageFeatures.{info['method']}")
    if not any(i['component'] == 'ext-host-language-features' and i['name'] == ehm for i in ifaces):
        ifaces.append({'component': 'ext-host-language-features', 'name': ehm, 'kind': 'function',
                       'summary': f"{info['method']}: allocate a handle, keep the provider adapter and call {info['rpc']}(handle, selector, ...); the Disposable unregisters the handle.",
                       'sources': [f"src/vs/workbench/api/common/extHostLanguageFeatures.ts:{info['line']}-{info['end']}"],
                       'request': req_schema(api), 'response': 'ExthostApiResult',
                       'behavior': [
                           {'set': {'state.next_handle': '= state.next_handle + 1'}},
                           {'set': {'state.adapters': f"= merge(state.adapters, {{string(state.next_handle): {{'kind': '{feat}', 'extension_id': input.extension_id, 'selector': has(input.selector) ? input.selector : (has(input.language) ? input.language : '')}}}})"}},
                           {'call': f'main-thread-language-features.{mtn}', 'on': ON_W,
                            'input': {'handle': '= state.next_handle', 'selector': "= has(input.selector) ? input.selector : (has(input.language) ? input.language : '')", 'extension_id': '= input.extension_id'}},
                           {'return': {'disposable_id': "= 'provider:' + string(state.next_handle)"}}]})
    if not any(i['component'] == 'main-thread-language-features' and i['name'] == mtn for i in ifaces):
        beh = [{'call': 'language-features-service.register-provider', 'input': {'feature': feat, 'handle': '= input.handle', 'language': '= input.selector', 'extension_id': '= input.extension_id'}, 'as': 'reg'},
               {'return': {'registered': True}}]
        if info['rpc'] == '$setLanguageConfiguration':
            beh = [{'title': 'ILanguageConfigurationService.register for the language (editor area); no provider registry entry', 'source': mt_line('main-thread-language-features', info['rpc']), 'set': {'vars.language': '= input.selector'}},
                   {'return': {'registered': True}}]
        ifaces.append({'component': 'main-thread-language-features', 'name': mtn, 'kind': 'rpc', 'attributes': {'shape': 'MainThreadLanguageFeaturesShape'},
                       'summary': f"{info['rpc']}(handle, selector, ...): register a proxy provider with ILanguageFeaturesService that calls back into the host.",
                       'sources': [f"src/vs/workbench/api/common/extHost.protocol.ts:{info['proto_line']}", mt_line('main-thread-language-features', info['rpc'])],
                       'request': {'type': 'object', 'required': ['handle', 'selector'], 'properties': {'handle': {'type': 'integer', 'examples': [1]}, 'selector': {'type': 'string', 'examples': ['typescript']}, 'extension_id': {'type': 'string', 'examples': ['vscode.git']}}},
                       'response': {'type': 'object', 'properties': {'registered': {'type': 'boolean'}}},
                       'behavior': beh})

api_entries = [e for e in mine if e['kind'] == 'extension-api']
api_ids = []
for e in api_entries:
    _, ns, fn = e['name'].split('.')
    nm = f"{ns}-{kebab(fn)}"
    a, b = api_lines[e['name']]
    dts = f"{e['file']}:{e['line']}"
    impl = f"{API_IMPL}:{a}-{b}" if b and b > a else f"{API_IMPL}:{a}"
    api_ids.append('vscode-api.' + nm)
    if nm in apiif:
        i = apiif[nm]
    else:
        i = {'component': 'vscode-api', 'name': nm, 'kind': 'function'}
        ifaces.append(i); apiif[nm] = i
        if nm in api_behaviors:
            tgt, desc = api_behaviors[nm]
            i['summary'] = f"vscode.{ns}.{fn} -> {desc}."
        else:
            tg = api_tg.get(e['name']) or []
            if not tg:
                special = {'window-register-webview-view-provider': ('extHostWebviewViews', 'registerWebviewViewProvider'), 'workspace-get-configuration': ('extHostConfiguration', 'getConfiguration')}
                tg = [special[nm]]
            var, meth = [t for t in tg if t[0] != 'extHostApiDeprecation'][0]
            eh = ensure_eh_comp(var); ehm = kebab(meth)
            tgt = f'{eh}.{ehm}'
            i['summary'] = f"vscode.{ns}.{fn} -> {var}.{meth}."
            if not any(x['component'] == eh and x['name'] == ehm for x in ifaces):
                src = find_method(eh, meth)
                ifaces.append({'component': eh, 'name': ehm, 'kind': 'function',
                               'summary': f"{var}.{meth} (extension host side; its main-thread RPCs are listed in skips/exthost.json with their targets).",
                               'sources': [src] if src else [impl], 'request': req_schema(e['name']), 'response': 'ExthostApiResult'})
        i['response'] = 'ExthostApiResult'
        i['behavior'] = [{'call': tgt, 'input': '= input', 'as': 'r'}, {'return': '= vars.r.value'}]
    i['sources'] = [dts, impl]
    i['request'] = req_schema(e['name'])
api_ids.append('vscode-api.text-document-save')
for i in ifaces:
    if i['component'] == 'third-party-extension' and i['name'] == 'call-api':
        i['behavior'] = [{'call': "= 'vscode-api.' + input.api", 'input': '= input.args', 'targets': sorted(set(api_ids)), 'as': 'r'},
                         {'return': '= vars.r.value'}]

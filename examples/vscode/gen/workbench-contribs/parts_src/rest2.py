from builder import Part, call, ret, iff, choice, sets, note, called, foreach

RL = 'relauncher/browser/relauncher.contribution.ts'
WS = 'workspaces/browser/workspaces.contribution.ts'
UC = 'url/browser/url.contribution.ts'
ET = 'externalTerminal/electron-browser/externalTerminal.contribution.ts'
WT = 'workspace/browser/workspace.contribution.ts'

RELAUNCH_KEYS = ['window.titleBarStyle', 'window.menuStyle', 'window.nativeTabs', 'window.nativeFullScreen', 'window.clickThroughInactive', 'window.controlsStyle',
                 'editor.accessibilitySupport', 'security.workspace.trust.enabled', 'workbench.enableExperiments', '_extensionsGallery.enablePPE', 'security.restrictUNCAccess',
                 'accessibility.verbosity.debug', 'telemetry.feedback.enabled']


def build():
    p = Part('rest2')
    ws, pc = 'workbench-shell', 'platform-core'
    confirm = p.stub('dialog-service.confirm', ws)
    restart = p.stub('host-service.restart', ws)
    reload = p.stub('host-service.reload', ws)
    open_window = p.stub('host-service.open-window', ws, {'type': 'object', 'properties': {'workspace_uri': {'type': 'string'}}})
    stop_eh = p.stub('extension-service.stop-extension-hosts', 'exthost')
    start_eh = p.stub('extension-service.start-extension-hosts', 'exthost')
    notify = p.stub('notification-service.notify', ws)
    prompt = p.stub('notification-service.prompt', ws)
    input_box = p.stub('quick-input-service.input', ws, {'type': 'object', 'properties': {'prompt': {'type': 'string'}, 'value': {'type': 'string'}}},
                       {'type': 'object', 'properties': {'value': {'type': 'string', 'examples': ['https://code.visualstudio.com/docs']}}})
    opener = p.stub('opener-service.open', pc)
    store = p.stub('storage-service.store', pc)
    register_provider = p.stub('file-service.register-provider', pc, {'type': 'object', 'properties': {'scheme': {'type': 'string'}}})
    set_ctx = p.stub('context-key-service.set-context', pc)
    get_value = p.stub('configuration-service.get-value', pc)
    open_term = p.stub('external-terminal-service.open-terminal', pc, {'type': 'object', 'properties': {'cwd': {'type': 'string'}}})
    publog = p.stub('telemetry-service.public-log2', pc, {'type': 'object', 'properties': {'event': {'type': 'string'}}})

    # ---- relauncher ----
    scr = p.comp('settings-change-relauncher', 'SettingsChangeRelauncher', 'relauncher-contribution', [f'{RL}:56'],
                 'Asks to restart when a setting that only applies at startup changes (no debounce; only when the window has focus).',
                 state={'schema': {'type': 'object'}, 'initial': {'values': {}}})
    p.seed['settings-change-relauncher'] = {'values': {'workbench.enableExperiments': True, 'telemetry.feedback.enabled': True, 'security.workspace.trust.enabled': True}}
    on_change = p.iface(scr, 'on-configuration-change', 'Configuration change: ignore unrelated keys; a changed value of a listed setting (not from defaults) prompts Restart, which restarts the host.',
                        [f'{RL}:126-137', f'{RL}:223-244'],
                        [iff(f'!(input.key in {RELAUNCH_KEYS})', [ret({'prompted': False, 'reason': 'unrelated'})], title='Only the SETTINGS list', source=f'{RL}:127-129'),
                         iff('input.key in state.values && state.values[input.key] == input.value', [ret({'prompted': False, 'reason': 'unchanged'})], title='ChangeObserver: same value is no change', source=f'{RL}:265-272'),
                         sets({'state.values': '= merge(state.values, {input.key: input.value})'}),
                         iff("input.source == 'default' || !input.has_focus", [ret({'prompted': False, 'reason': 'not-asked'})], title='Defaults changing or no focus: no prompt', source=f'{RL}:223'),
                         call(confirm, {'message': 'A setting has changed that requires a restart to take effect.', 'primary_button': '&&Restart'}, as_='c', source=f'{RL}:224-234'),
                         iff('vars.c.value.confirmed', [call(restart, {}, source=f'{RL}:234'), ret({'prompted': True, 'restarted': True})], source=f'{RL}:241'),
                         ret({'prompted': True, 'restarted': False})],
                        request={'type': 'object', 'properties': {'key': {'type': 'string', 'default': 'workbench.enableExperiments'}, 'value': {'default': False},
                                                                  'source': {'type': 'string', 'default': 'user'}, 'has_focus': {'type': 'boolean', 'default': True}}})
    p.iface(scr, 'constructor', 'Records the current values as the baseline (update(false)), then listens to configuration changes and to sync being turned on.',
            [f'{RL}:357', f'{RL}:110-124'],
            [foreach(f"= {RELAUNCH_KEYS}", 'k', [
                call(get_value, {'key': '= vars.k'}, as_='v', title='ChangeObserver.handleChange(config value), with askToRelaunch false', source=f'{RL}:143-150'),
                iff('has(vars.v.value.value) && vars.v.value.value != null && (!(vars.k in state.values) || state.values[vars.k] != vars.v.value.value)',
                    [sets({'state.values': '= merge(state.values, {vars.k: vars.v.value.value})'})], title='A typed value that differs from the last one becomes the new last value', source=f'{RL}:265-272')]),
             sets({'state.listening': True}, title='update(false): baseline without prompting; then onDidChangeConfiguration and onDidTurnOnSync', source=f'{RL}:121-123'),
             ret({'listening': True, 'observed': '= size(state.values)'})])
    p.scenario_for(f'{scr}.constructor', {'id': 'settings-relauncher-start', 'caller': 'workbench', 'expect': ["state['settings-change-relauncher@w1'].listening"]})
    for sc in [{'id': 'relaunch-confirm', 'caller': 'platform', 'expect': ['steps.s.result.value.restarted', called(restart), "state['settings-change-relauncher@w1'].values['workbench.enableExperiments'] == false"]},
               {'id': 'relaunch-declined', 'caller': 'platform', 'choices': {'dialog-service.confirm.answer': 'cancel'}, 'expect': ['steps.s.result.value.prompted', '!' + called(restart)]},
               {'id': 'relaunch-unrelated', 'caller': 'platform', 'input': {'key': 'editor.fontSize', 'value': 14}, 'expect': ["steps.s.result.value.reason == 'unrelated'", '!' + called(confirm)]},
               {'id': 'relaunch-unchanged', 'caller': 'platform', 'input': {'value': True}, 'expect': ["steps.s.result.value.reason == 'unchanged'", '!' + called(confirm)]},
               {'id': 'relaunch-no-focus', 'caller': 'platform', 'input': {'has_focus': False}, 'expect': ["steps.s.result.value.reason == 'not-asked'", '!' + called(confirm)]}]:
        p.scenario_for(on_change, sc)
    wcr = p.comp('workspace-change-ext-host-relauncher', 'WorkspaceChangeExtHostRelauncher', 'relauncher-contribution', [f'{RL}:275'],
                 'Restarts the extension host when the first workspace folder changes (deprecated workspace.rootPath depends on it).',
                 state={'schema': {'type': 'object'}, 'initial': {'first_folder': 'file:///work/app'}})
    p.seed['workspace-change-ext-host-relauncher'] = {'first_folder': 'file:///work/app'}
    p.iface(wcr, 'on-did-change-workspace-folders', 'First folder changed: (10 ms scheduler) reload when remote, else stop the extension hosts and start them again.',
            [f'{RL}:358', f'{RL}:343-353', f'{RL}:290-307'],
            [iff('input.first_folder == state.first_folder', [ret({'restarted': False})], source=f'{RL}:348'),
             sets({'state.first_folder': '= input.first_folder'}, source=f'{RL}:349'),
             iff('input.remote', [call(reload, {}, source=f'{RL}:300'), ret({'restarted': 'reload'})], source=f'{RL}:299'),
             call(stop_eh, {'reason': 'Changing workspace folders', 'auto': False}, as_='st', source=f'{RL}:302'),
             call(start_eh, {}, source=f'{RL}:303-304'), ret({'restarted': 'extension-hosts'})],
            request={'type': 'object', 'properties': {'first_folder': {'type': 'string', 'default': 'file:///work/lib'}, 'remote': {'type': 'boolean', 'default': False}}})
    p.scenario_for('workspace-change-ext-host-relauncher.on-did-change-workspace-folders', {'id': 'exthost-relaunch-first-folder', 'caller': 'workbench',
                                                                                           'expect': [called(stop_eh), "state['workspace-change-ext-host-relauncher@w1'].first_folder == 'file:///work/lib'"]})
    p.scenario_for('workspace-change-ext-host-relauncher.on-did-change-workspace-folders', {'id': 'exthost-relaunch-same-folder', 'caller': 'workbench', 'input': {'first_folder': 'file:///work/app'},
                                                                                           'expect': ['!' + called(stop_eh)]})

    # ---- url ----
    p.cmd('url-contribution', 'workbench.action.url.openUrl', f'{UC}:55', f'{UC}:39-52', 'Developer: Open URL: input box pre-filled with the last URL; opens it (contributed openers allowed) and remembers it.',
          [call(input_box, {'prompt': 'URL to open', 'value': "= has(state.last_input) ? state.last_input : ''"}, as_='i', source=f'{UC}:44-46'),
           iff("vars.i.value.value == ''", [ret({'opened': False})], source=f'{UC}:47'),
           call(opener, {'resource': '= vars.i.value.value'}, source=f'{UC}:48'),
           call(store, {'key': 'workbench.action.url.openUrl.lastInput', 'value': '= vars.i.value.value', 'scope': 'workspace', 'target': 'machine'}, source=f'{UC}:49'),
           sets({'state.last_input': '= vars.i.value.value'}), ret({'opened': True})],
          scen=[{'expect': [called(opener), "state['url-contribution@w1'].last_input != ''"]}])
    tdf = p.comp('trusted-domains-file-system-provider', 'TrustedDomainsFileSystemProvider', 'url-contribution', ['url/browser/trustedDomainsFileSystemProvider.ts:77'],
                 'File system provider for trustedDomains:/Trusted Domains (the editable trusted domains list).')
    p.iface(tdf, 'constructor', 'Registers the trustedDomains file system provider.', [f'{UC}:73', 'url/browser/trustedDomainsFileSystemProvider.ts:86-92'],
            [call(register_provider, {'scheme': 'trustedDomains'}, source='url/browser/trustedDomainsFileSystemProvider.ts:91'), ret({'registered': True})])
    p.scenario_for(f'{tdf}.constructor', {'id': 'trusted-domains-fs-provider', 'caller': 'workbench', 'expect': [called(register_provider, "e.input.scheme == 'trustedDomains'")]})
    eur = p.comp('external-uri-resolver-contribution', 'ExternalUriResolverContribution', 'url-contribution', ['url/browser/externalUriResolver.ts:11'],
                 'Web embedders only: delegates external URI resolution to options.resolveExternalUri.')
    p.iface(eur, 'constructor', 'Registers an external URI resolver only when the embedder supplies resolveExternalUri (never on desktop).',
            [f'{UC}:78', 'url/browser/externalUriResolver.ts:15-33'],
            [iff('!input.embedder_resolves', [ret({'registered': False})], source='url/browser/externalUriResolver.ts:21'), ret({'registered': True})],
            request={'type': 'object', 'properties': {'embedder_resolves': {'type': 'boolean', 'default': False}}})
    p.scenario_for(f'{eur}.constructor', {'id': 'external-uri-resolver-desktop', 'caller': 'workbench', 'expect': ['!steps.s.result.value.registered']})

    # ---- workspace trust contributions ----
    wtc = p.comp('workspace-trust-context-keys', 'WorkspaceTrustContextKeys', 'workspace-contribution', [f'{WT}:72'], 'Binds the isWorkspaceTrustEnabled and isWorkspaceTrusted context keys.')
    p.iface(wtc, 'constructor', 'Sets isWorkspaceTrustEnabled and isWorkspaceTrusted, and updates the latter on every trust change.', [f'{WT}:94', f'{WT}:72-92'],
            [call(set_ctx, {'key': 'isWorkspaceTrustEnabled', 'value': "= config['security-workspace-trust-enabled']"}, source=f'{WT}:84-85'),
             call('workspace-trust-management-service.is-workspace-trusted', {}, as_='t'),
             call(set_ctx, {'key': 'isWorkspaceTrusted', 'value': '= vars.t.value.trusted'}, source=f'{WT}:87-88'), ret({'trusted': '= vars.t.value.trusted'})])
    p.scenario_for(f'{wtc}.constructor', {'id': 'trust-context-keys', 'caller': 'workbench', 'expect': [called(set_ctx, "e.input.key == 'isWorkspaceTrusted'")]})
    wtt = p.comp('workspace-trust-telemetry-contribution', 'WorkspaceTrustTelemetryContribution', 'workspace-contribution', [f'{WT}:855'], 'Logs workspace trust state at startup and on changes.')
    p.iface(wtt, 'constructor', 'After trust initializes: workspaceTrustDisabled (setting) or workspaceTrustFolderCounts, then workspaceTrustStateChanged on changes.', [f'{WT}:975', f'{WT}:855-907'],
            [iff("!config['security-workspace-trust-enabled']", [call(publog, {'event': 'workspaceTrustDisabled'}, source=f'{WT}:888'), ret({'logged': 'workspaceTrustDisabled'})]),
             call(publog, {'event': 'workspaceTrustFolderCounts'}, source=f'{WT}:904'), ret({'logged': 'workspaceTrustFolderCounts'})])
    p.scenario_for(f'{wtt}.constructor', {'id': 'trust-telemetry', 'caller': 'workbench', 'expect': [called(publog, "e.input.event == 'workspaceTrustFolderCounts'")]})
    p.scenario_for(f'{wtt}.constructor', {'id': 'trust-telemetry-disabled', 'caller': 'workbench', 'config': {'security-workspace-trust-enabled': False}, 'expect': [called(publog, "e.input.event == 'workspaceTrustDisabled'")]})

    # ---- workspaces ----
    p.cmd('workspaces-contribution', 'workbench.action.openWorkspaceFromEditor', f'{WS}:111', f'{WS}:129-145', 'Open Workspace button on a .code-workspace file: opens it in a window unless it is the workspace already open.',
          [iff('has(input.current_workspace) && input.current_workspace == input.uri', [call(notify, {'severity': 'info', 'message': 'This workspace is already open.'}, source=f'{WS}:137'), ret({'opened': False})], source=f'{WS}:134-140'),
           call(open_window, {'workspace_uri': '= input.uri'}, source=f'{WS}:143'), ret({'opened': True})],
          request={'type': 'object', 'properties': {'uri': {'type': 'string', 'default': 'file:///work/app/app.code-workspace'}}},
          scen=[{'expect': [called(open_window, "e.input.workspace_uri == 'file:///work/app/app.code-workspace'")]},
                {'id': 'open-workspace-already-open', 'input': {'current_workspace': 'file:///work/app/app.code-workspace'}, 'expect': [called(notify), '!' + called(open_window)]}])
    wf = p.comp('workspaces-finder-contribution', 'WorkspacesFinderContribution', 'workspaces-contribution', [f'{WS}:32'],
                'In a folder window, offers to open a .code-workspace file found at the folder root.')
    p.iface(wf, 'constructor', 'findWorkspaces: only for a (non-virtual) folder workspace; one workspace file prompts "Open Workspace", several prompt "Select Workspace" (never show again per workspace).',
            [f'{WS}:107', f'{WS}:47-104'],
            [iff("size(input.workspace_files) == 0", [ret({'prompted': False})], source=f'{WS}:55-57'),
             call(prompt, {'severity': 'info', 'message': "= size(input.workspace_files) == 1 ? 'This folder contains a workspace file. Do you want to open it?' : 'This folder contains multiple workspace files. Do you want to open one?'",
                           'choices': ["= size(input.workspace_files) == 1 ? 'Open Workspace' : 'Select Workspace'"]}, source=f'{WS}:67-100'),
             choice('answer', 'open', {'open': [call(open_window, {'workspace_uri': "= 'file:///work/app/' + input.workspace_files[0]"}, source=f'{WS}:76'), ret({'prompted': True, 'opened': True})],
                                       'ignore': [ret({'prompted': True, 'opened': False})]})],
            request={'type': 'object', 'properties': {'workspace_files': {'type': 'array', 'items': {'type': 'string'}, 'default': ['app.code-workspace']}}})
    p.scenario_for(f'{wf}.constructor', {'id': 'workspaces-finder-one', 'caller': 'workbench', 'expect': [called(prompt), called(open_window)]})
    p.scenario_for(f'{wf}.constructor', {'id': 'workspaces-finder-none', 'caller': 'workbench', 'input': {'workspace_files': []}, 'expect': ['!' + called(prompt)]})

    # ---- external terminal ----
    p.cmd('external-terminal-contribution-native', 'workbench.action.terminal.openNativeConsole', f'{ET}:30', f'{ET}:35-80',
          'Open New External Terminal: picks a folder when there are several, opens the OS terminal (terminal.external.*) at the workspace root.',
          [iff('size(input.folders) > 1', [choice('folder', 'first', {'first': [], 'dismissed': [ret({'opened': False})]}, source=f'{ET}:48-59')], source=f'{ET}:48'),
           iff("!input.folders[0].startsWith('file:')", [ret({'opened': False})]),
           call(open_term, {'cwd': "= input.folders[0].replace('file://', '')"}, source=f'{ET}:66-68'), ret({'opened': True})],
          request={'type': 'object', 'properties': {'folders': {'type': 'array', 'items': {'type': 'string'}, 'default': ['file:///work/app']}}},
          scen=[{'expect': [called(open_term, "e.input.cwd == '/work/app'")]},
                {'id': 'native-console-pick-dismissed', 'input': {'folders': ['file:///work/app', 'file:///work/lib']},
                 'choices': {'external-terminal-contribution-native.cmd-workbench-action-terminal-opennativeconsole.folder': 'dismissed'}, 'expect': ['!' + called(open_term)]}])
    return p

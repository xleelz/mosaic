from builder import Part, call, ret, iff, choice, sets, note, called

PC = 'preferences/browser/preferences.contribution.ts'
PCC = 'preferences/common/preferencesContribution.ts'
KL = 'preferences/browser/keyboardLayoutPicker.ts'
MS = 'meteredConnection/browser/meteredConnectionStatus.ts'
WB = 'src/vs/workbench/browser/workbench.contribution.ts'


def build():
    p = Part('rest6')
    ws, pc = 'workbench-shell', 'platform-core'
    reg_editor = p.stub('editor-resolver-service.register-editor', ws, {'type': 'object', 'properties': {'glob': {'type': 'string'}, 'id': {'type': 'string'}, 'priority': {'type': 'string'}}})
    reg_fs = p.stub('file-service.register-provider', pc, {'type': 'object', 'properties': {'scheme': {'type': 'string'}}})
    add_entry = p.stub('statusbar-service.add-entry', ws, {'type': 'object', 'properties': {'id': {'type': 'string'}, 'text': {'type': 'string'}, 'command': {'type': 'string'}}})
    p.configs += [
        {'id': 'workbench-settings-use-split-json', 'type': 'boolean', 'value': False, 'default': False, 'summary': 'workbench.settings.useSplitJSON: edit settings.json in the split JSON editor.',
         'sources': [f'{WB}:570-573', f'src/vs/workbench/contrib/{PCC}:57'], 'attributes': {'key': 'workbench.settings.useSplitJSON', 'boundary': True, 'owner': 'workbench-shell'}},
        {'id': 'workbench-settings-open-default-settings', 'type': 'boolean', 'value': False, 'default': False, 'summary': 'workbench.settings.openDefaultSettings: also show the default settings when opening settings.',
         'sources': [f'{WB}:565-568', f'src/vs/workbench/contrib/{PCC}:57'], 'attributes': {'key': 'workbench.settings.openDefaultSettings', 'boundary': True, 'owner': 'workbench-shell'}},
    ]
    prc = p.comp('preferences-contribution-registrar', 'PreferencesContribution', 'preferences-contribution', [f'{PCC}:25'],
                 'Registers the vscode: settings file system provider and, when split JSON or default settings are on, an editor for **/settings.json.')
    p.iface(prc, 'constructor', 'handleSettingsEditorRegistration (also on changes of the two settings), then the settings file system provider.',
            [f'{PC}:1520', f'{PCC}:37-51'],
            [iff("config['workbench-settings-use-split-json'] || config['workbench-settings-open-default-settings']",
                 [call(reg_editor, {'glob': '**/settings.json', 'id': 'workbench.editorinputs.sidebysideEditorInput', 'priority': 'builtin'}, title='Split Settings Editor for settings.json', source=f'{PCC}:57-66')],
                 source=f'{PCC}:57'),
             call(reg_fs, {'scheme': 'vscode'}, title='SettingsFileSystemProvider (default settings as files)', source=f'{PCC}:49-50'),
             ret({'split_editor': "= config['workbench-settings-use-split-json'] || config['workbench-settings-open-default-settings']"})])
    p.scenario_for(f'{prc}.constructor', {'id': 'preferences-contribution-default', 'caller': 'workbench', 'expect': ['!steps.s.result.value.split_editor', called(reg_fs), '!' + called(reg_editor)]})
    p.scenario_for(f'{prc}.constructor', {'id': 'preferences-contribution-split-json', 'caller': 'workbench', 'config': {'workbench-settings-use-split-json': True},
                                          'expect': [called(reg_editor, "e.input.glob == '**/settings.json'")]})
    st = p.comp('settings-editor-title-contribution', 'SettingsEditorTitleContribution', 'preferences-contribution', [f'{PC}:1382'],
                'Registers the "Open Settings (UI)" title action on JSON settings files of the current profile.', state={'schema': {'type': 'object'}, 'initial': {}})
    p.iface(st, 'constructor', 'registerSettingsEditorTitleActions: the open-UI action for user, workspace and folder settings files, re-registered on profile change.',
            [f'{PC}:1521', f'{PC}:1386-1392', f'{PC}:1394-1434'],
            [call('user-data-profile.get-current-profile', {}, as_='p', source=f'{PC}:1397-1402'),
             iff('vars.p.value.is_default',
                 [sets({'state.open_ui_on': ['= vars.p.value.settings_resource']})],
                 [sets({'state.open_ui_on': ['= vars.p.value.settings_resource', '= vars.p.value.default_settings_resource']})],
                 title='_workbench.openUserSettingsEditor shows on the current profile\'s settings.json or the default profile\'s (not in the settings editor or a diff)', source=f'{PC}:1397-1402'),
             sets({'state.title_actions_registered': True, 'state.registered_for_profile': '= vars.p.value.id'}, title='registerOpenUserSettingsEditorFromJsonAction; re-run on onDidChangeCurrentProfile', source=f'{PC}:1428-1432'),
             ret({'registered': True, 'open_ui_on': '= state.open_ui_on'})])
    p.scenario_for(f'{st}.constructor', {'id': 'settings-editor-title-contribution', 'caller': 'workbench',
                                         'expect': ["state['settings-editor-title-contribution@w1'].title_actions_registered", "steps.s.result.value.open_ui_on == ['vscode-userdata:/User/settings.json']"]})
    p.scenario_for(f'{st}.constructor', {'id': 'settings-editor-title-contribution-profile', 'caller': 'workbench',
                                         'state': {'user-data-profile@w1': {'current_profile': 'work', 'profiles': {'default': {'name': 'Default', 'is_default': True}, 'work': {'name': 'Work', 'is_default': False}}}},
                                         'expect': ["steps.s.result.value.open_ui_on == ['vscode-userdata:/User/profiles/work/settings.json', 'vscode-userdata:/User/settings.json']"]})
    klp = p.comp('keyboard-layout-picker-contribution', 'KeyboardLayoutPickerContribution', 'preferences-keyboard-layout-picker', [f'{KL}:23'],
                 'Status bar entry "Layout: <name>" for the current keyboard layout, opening the layout picker.')
    p.iface(klp, 'constructor', 'Adds the status bar entry when a layout is known and updates it on layout changes.', [f'{KL}:83', f'{KL}:30-77'],
            [iff("input.layout == ''", [ret({'shown': False})], source=f'{KL}:38'),
             call(add_entry, {'id': 'status.workbench.keyboardLayout', 'text': "= 'Layout: ' + input.layout", 'command': 'workbench.action.openKeyboardLayoutPicker'}, source=f'{KL}:41-50'),
             ret({'shown': True})],
            request={'type': 'object', 'properties': {'layout': {'type': 'string', 'default': 'US'}}})
    p.scenario_for(f'{klp}.constructor', {'id': 'keyboard-layout-status', 'caller': 'workbench', 'expect': [called(add_entry, "e.input.text == 'Layout: US'")]})
    mcs = p.comp('metered-connection-status-contribution', 'MeteredConnectionStatusContribution', 'metered-connection-contribution', [f'{MS}:12'],
                 'Shows a status bar entry while the connection is considered metered.')
    p.iface(mcs, 'constructor', 'Status bar entry while metered (updated on onDidChangeIsConnectionMetered), cleared otherwise.', ['meteredConnection/browser/meteredConnection.contribution.ts:17', f'{MS}:18-44'],
            [iff('!input.is_metered', [ret({'shown': False})], title='Not metered: clear the entry', source=f'{MS}:42'),
             call(add_entry, {'id': 'status.meteredConnection', 'text': 'Metered connection', 'command': 'workbench.action.configureMeteredConnection'}, source=f'{MS}:33-40'), ret({'shown': True})],
            request={'type': 'object', 'properties': {'is_metered': {'type': 'boolean', 'default': True}}})
    p.scenario_for(f'{mcs}.constructor', {'id': 'metered-status-on', 'caller': 'workbench', 'expect': [called(add_entry, "e.input.id == 'status.meteredConnection'")]})
    p.scenario_for(f'{mcs}.constructor', {'id': 'metered-status-off', 'caller': 'workbench', 'input': {'is_metered': False}, 'expect': ['!' + called(add_entry)]})
    build_troubleshoot(p)
    return p


IT = 'issue/browser/issueTroubleshoot.ts'


def build_troubleshoot(p):
    ws = 'workbench-shell'
    confirm = p.stub('dialog-service.confirm', ws)
    create_profile = p.stub('user-data-profile-import-export-service.create-troubleshoot-profile', ws)
    switch = p.stub('user-data-profile-management-service.switch-profile', ws, {'type': 'object', 'properties': {'profile_id': {'type': 'string'}}})
    set_ctx = p.stub('context-key-service.set-context', 'platform-core')
    tis = 'troubleshoot-issue-service'
    start = p.iface(tis, 'start', 'Troubleshoot Issue: confirm, create a temporary troubleshoot profile, record the original profile and start the extensions stage (the window then reloads between stages).',
                    [f'{IT}:106-120'],
                    [iff("has(state.stage) && state.stage != ''", [{'fail': {'code': 'invalid-state', 'message': 'invalid state'}}], source=f'{IT}:107-109'),
                     call(confirm, {'message': 'Troubleshoot Issue'}, as_='c', source=f'{IT}:111-117'),
                     iff('!vars.c.value.confirmed', [ret({'started': False})], source=f'{IT}:118-120'),
                     call(create_profile, {}, source=f'{IT}:123'),
                     sets({'state.stage': 'extensions', 'state.profile': 'default'}, title='TroubleShootState(EXTENSIONS, original profile); resume() continues with the stage prompts', source=f'{IT}:124'),
                     ret({'started': True})],
                    errors=[{'code': 'invalid-state', 'status': 0, 'retryable': False}])
    stop = p.iface(tis, 'stop', 'Stop: reset extension bisect if active, clear the state and switch back to the original profile.', [f'{IT}:144-161'],
                   [iff("!has(state.stage) || state.stage == ''", [ret({'stopped': False})], source=f'{IT}:145-147'),
                    sets({'vars.profile': '= state.profile'}),
                    sets({'state.stage': '', 'state.profile': ''}, source=f'{IT}:159'),
                    call(switch, {'profile_id': '= vars.profile'}, source=f'{IT}:160'), ret({'stopped': True})])
    p.seed[tis] = {'stage': '', 'profile': ''}
    p.cmd('issue-troubleshoot', 'workbench.action.troubleshootIssue.start', f'{IT}:348', f'{IT}:358-360', 'Help: Troubleshoot Issue... (desktop, local windows).',
          [call(start, {}, as_='r', source=f'{IT}:359'), ret('= vars.r.value')], errors=[{'code': 'invalid-state', 'status': 0, 'retryable': False}],
          scen=[{'post': [{'interface': 'issue-troubleshoot.cmd-workbench-action-troubleshootissue-stop', 'caller': 'user', 'input': {}, 'as': 'stop'}],
                 'expect': ['steps.stop.result.value.stopped', called(create_profile), called(switch, "e.input.profile_id == 'default'"), "state['troubleshoot-issue-service@w1'].stage == ''"]},
                {'id': 'troubleshoot-declined', 'choices': {'dialog-service.confirm.answer': 'cancel'}, 'expect': ['!steps.s.result.value.started', '!' + called(create_profile)]},
                {'id': 'troubleshoot-already-active', 'state': {'troubleshoot-issue-service@w1': {'stage': 'extensions'}}, 'fails': True, 'expect': ["steps.s.result.error.code == 'invalid-state'"]}])
    p.cmd('issue-troubleshoot', 'workbench.action.troubleshootIssue.stop', f'{IT}:363', f'{IT}:374-376', 'Help: Stop Troubleshoot Issue.',
          [call(stop, {}, as_='r', source=f'{IT}:375'), ret('= vars.r.value')],
          scen=[{'id': 'troubleshoot-stop-inactive', 'expect': ['!steps.s.result.value.stopped', '!' + called(switch)]}])
    ui = p.comp('issue-troubleshoot-ui', 'IssueTroubleshootUi', 'issue-troubleshoot', [f'{IT}:321'], 'Keeps the issueTroubleshootActive context key and resumes an active troubleshooting after a reload.')
    p.iface(ui, 'constructor', 'Sets issueTroubleshootActive; when troubleshooting is active after a reload, resumes it.', [f'{IT}:346', f'{IT}:325-342'],
            [call(set_ctx, {'key': 'issueTroubleshootActive', 'value': "= input.active"}, source=f'{IT}:341'),
             iff('input.active', [ret({'resumed': True})], title='troubleshootIssueService.resume()', source=f'{IT}:332-333'), ret({'resumed': False})],
            request={'type': 'object', 'properties': {'active': {'type': 'boolean', 'default': False}}})
    p.scenario_for(f'{ui}.constructor', {'id': 'troubleshoot-ui', 'caller': 'workbench', 'expect': [called(set_ctx, "e.input.key == 'issueTroubleshootActive'")]})

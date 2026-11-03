from builder import Part, call, ret, iff, choice, sets, note, called, fail

PC = 'preferences/browser/preferences.contribution.ts'
KE = 'preferences/browser/keybindingsEditor.ts'


def build():
    p = Part('prefs')
    ws = 'workbench-shell'
    get_ws = p.stub('workspace-context.get-workspace', ws)
    open_settings = p.stub('preferences-service.open-settings', ws, {'type': 'object', 'properties': {'json_editor': {'type': 'boolean'}, 'query': {'type': 'string'}}})
    open_app = p.stub('preferences-service.open-application-settings', ws, {'type': 'object', 'properties': {'json_editor': {'type': 'boolean'}}})
    open_user = p.stub('preferences-service.open-user-settings', ws, {'type': 'object', 'properties': {'json_editor': {'type': 'boolean'}, 'query': {'type': 'string'}}})
    open_raw = p.stub('preferences-service.open-raw-default-settings', ws)
    open_ws = p.stub('preferences-service.open-workspace-settings', ws, {'type': 'object', 'properties': {'json_editor': {'type': 'boolean'}}})
    open_folder = p.stub('preferences-service.open-folder-settings', ws, {'type': 'object', 'properties': {'folder_uri': {'type': 'string'}, 'json_editor': {'type': 'boolean'}}})
    open_remote = p.stub('preferences-service.open-remote-settings', ws, {'type': 'object', 'properties': {'json_editor': {'type': 'boolean'}}})
    open_lang = p.stub('preferences-service.open-language-specific-settings', ws, {'type': 'object', 'properties': {'language_id': {'type': 'string'}}})
    open_dkb = p.stub('preferences-service.open-default-keybindings-file', ws)
    open_gkb = p.stub('preferences-service.open-global-keybinding-settings', ws, {'type': 'object', 'properties': {'textual': {'type': 'boolean'}}})
    kb_add = p.stub('keybindings-editing-service.add-keybinding', ws, {'type': 'object', 'properties': {'command': {'type': 'string'}, 'key': {'type': 'string'}, 'when': {'type': 'string'}}})
    kb_edit = p.stub('keybindings-editing-service.edit-keybinding', ws, {'type': 'object', 'properties': {'command': {'type': 'string'}, 'key': {'type': 'string'}, 'when': {'type': 'string'}}})
    kb_remove = p.stub('keybindings-editing-service.remove-keybinding', ws, {'type': 'object', 'properties': {'command': {'type': 'string'}}})
    kb_reset = p.stub('keybindings-editing-service.reset-keybinding', ws, {'type': 'object', 'properties': {'command': {'type': 'string'}}})
    clip = p.stub('clipboard-service.write-text', ws, {'type': 'object', 'properties': {'text': {'type': 'string'}}})

    # --- settings commands (PreferencesActionsContribution.registerSettingsActions) ---
    pc = 'preferences-contribution'
    p.cmd(pc, 'workbench.action.openSettings', f'{PC}:227', f'{PC}:251-255', 'Open Settings: the settings editor (UI or JSON per workbench.settings.editor), with an optional query.',
          [call(open_settings, {'query': "= has(input.query) ? input.query : ''"}, source=f'{PC}:254'), ret({'opened': True})],
          scen=[{'input': {'query': 'editor.fontSize'}, 'expect': [called(open_settings, "e.input.query == 'editor.fontSize'")]}])
    p.cmd(pc, 'workbench.action.openSettings2', f'{PC}:257', f'{PC}:266-269', 'Open Settings (UI): always the settings editor UI.',
          [call(open_settings, {'json_editor': False}, source=f'{PC}:268'), ret({'opened': True})],
          scen=[{'expect': [called(open_settings, '!e.input.json_editor')]}])
    p.cmd(pc, 'workbench.action.openSettingsJson', f'{PC}:272', f'{PC}:284-287', 'Open User Settings (JSON).',
          [call(open_settings, {'json_editor': True}, source=f'{PC}:286'), ret({'opened': True})],
          scen=[{'expect': [called(open_settings, 'e.input.json_editor')]}])
    p.cmd(pc, 'workbench.action.openApplicationSettingsJson', f'{PC}:291', f'{PC}:303-306', 'Open Application Settings (JSON).',
          [call(open_app, {'json_editor': True}, source=f'{PC}:305'), ret({'opened': True})],
          scen=[{'expect': [called(open_app, 'e.input.json_editor')]}])
    p.cmd(pc, 'workbench.action.openGlobalSettings', f'{PC}:310', f'{PC}:319-322', 'Open User Settings.',
          [call(open_user, {}, source=f'{PC}:321'), ret({'opened': True})],
          scen=[{'expect': [called(open_user)]}])
    p.cmd(pc, 'workbench.action.openRawDefaultSettings', f'{PC}:324', f'{PC}:333-335', 'Open Default Settings (JSON), the read-only defaults.',
          [call(open_raw, {}, source=f'{PC}:334'), ret({'opened': True})],
          scen=[{'expect': [called(open_raw)]}])
    p.cmd(pc, 'workbench.action.configureLanguageBasedSettings', f'{PC}:338', ['preferences/browser/preferencesActions.ts:46-77', f'{PC}:347-349'],
          'Configure Language Specific Settings: pick a language, then open its settings section.',
          [choice('language_pick', 'typescript', {
              'typescript': [sets({'vars.lang': 'typescript'})],
              'dismissed': [ret({'opened': False})]}, title='Select Language quick pick', source='preferences/browser/preferencesActions.ts:68'),
           call(open_lang, {'language_id': '= vars.lang'}, source='preferences/browser/preferencesActions.ts:73'), ret({'opened': True, 'language_id': '= vars.lang'})],
          scen=[{'expect': [called(open_lang, "e.input.language_id == 'typescript'")]},
                {'id': 'configure-language-settings-dismissed', 'choices': {'preferences-contribution.cmd-workbench-action-configurelanguagebasedsettings.language_pick': 'dismissed'},
                 'expect': ['!steps.s.result.value.opened', '!' + called(open_lang)]}])
    p.cmd(pc, 'workbench.action.openWorkspaceSettings', f'{PC}:351', f'{PC}:363-367', 'Open Workspace Settings.',
          [call(open_ws, {}, source=f'{PC}:366'), ret({'opened': True})], scen=[{'expect': [called(open_ws)]}])
    p.cmd(pc, 'workbench.action.openAccessibilitySettings', f'{PC}:370', f'{PC}:382-384', 'Open Accessibility Settings: the settings editor filtered to @tag:accessibility.',
          [call(open_settings, {'json_editor': False, 'query': '@tag:accessibility'}, source=f'{PC}:383'), ret({'opened': True})],
          scen=[{'expect': [called(open_settings, "e.input.query == '@tag:accessibility'")]}])
    p.cmd(pc, 'workbench.action.openWorkspaceSettingsFile', f'{PC}:386', f'{PC}:398-401', 'Open Workspace Settings (JSON).',
          [call(open_ws, {'json_editor': True}, source=f'{PC}:400'), ret({'opened': True})], scen=[{'expect': [called(open_ws, 'e.input.json_editor')]}])
    folder_pick = lambda line: choice('folder_pick', 'app', {
        'app': [sets({'vars.folder': 'file:///work/app'})],
        'dismissed': [ret({'opened': False})]}, title='Pick a workspace folder (PICK_WORKSPACE_FOLDER_COMMAND_ID)', source=f'{PC}:{line}')
    p.cmd(pc, 'workbench.action.openFolderSettings', f'{PC}:403', f'{PC}:415-423', 'Open Folder Settings: pick a workspace folder, then open its settings.',
          [folder_pick(418), call(open_folder, {'folder_uri': '= vars.folder'}, source=f'{PC}:421'), ret({'opened': True})],
          scen=[{'expect': [called(open_folder, "e.input.folder_uri == 'file:///work/app'")]},
                {'id': 'open-folder-settings-dismissed', 'choices': {'preferences-contribution.cmd-workbench-action-openfoldersettings.folder_pick': 'dismissed'}, 'expect': ['!' + called(open_folder)]}])
    p.cmd(pc, 'workbench.action.openFolderSettingsFile', f'{PC}:425', f'{PC}:437-445', 'Open Folder Settings (JSON).',
          [folder_pick(440), call(open_folder, {'folder_uri': '= vars.folder', 'json_editor': True}, source=f'{PC}:443'), ret({'opened': True})],
          scen=[{'expect': [called(open_folder, 'e.input.json_editor')]}])
    p.cmd(pc, 'workbench.action.openRemoteSettings', f'{PC}:552', f'{PC}:564-567', 'Open Remote Settings (registered only with a remote authority).',
          [call(open_remote, {}, source=f'{PC}:566'), ret({'opened': True})], scen=[{'expect': [called(open_remote)]}])
    p.cmd(pc, 'workbench.action.openRemoteSettingsFile', f'{PC}:569', f'{PC}:581-584', 'Open Remote Settings (JSON).',
          [call(open_remote, {'json_editor': True}, source=f'{PC}:583'), ret({'opened': True})], scen=[{'expect': [called(open_remote, 'e.input.json_editor')]}])

    # --- keybindings commands ---
    p.cmd(pc, 'workbench.action.openDefaultKeybindingsFile', f'{PC}:925', f'{PC}:934-936', 'Open Default Keyboard Shortcuts (JSON).',
          [call(open_dkb, {}, source=f'{PC}:935'), ret({'opened': True})], scen=[{'expect': [called(open_dkb)]}])
    p.cmd(pc, 'workbench.action.openGlobalKeybindingsFile', f'{PC}:938', f'{PC}:960-963', 'Open Keyboard Shortcuts (JSON): keybindings.json as text.',
          [call(open_gkb, {'textual': True}, source=f'{PC}:962'), ret({'opened': True})], scen=[{'expect': [called(open_gkb, 'e.input.textual')]}])

    # KeybindingsEditor: the editor pane with the selected entry
    ke = p.comp('keybindings-editor', 'KeybindingsEditor', 'preferences-contribution', [f'{KE}:74'],
                'The Keyboard Shortcuts editor pane: selected entry, define-keybinding widget, search history.',
                state={'schema': {'type': 'object', 'properties': {'open': {'type': 'boolean'}, 'active_entry': {'type': 'object'}, 'search_history': {'type': 'array'}}},
                       'initial': {'open': False, 'active_entry': {'command': 'workbench.action.files.save', 'command_label': 'File: Save', 'key': 'ctrl+s', 'when': ''}, 'search_history': []}})
    p.seed['keybindings-editor'] = {'open': True, 'active_entry': {'command': 'workbench.action.files.save', 'command_label': 'File: Save', 'key': 'ctrl+s', 'when': ''}, 'search_history': ['save']}
    entry = 'state.active_entry'
    define = p.iface(ke, 'define-keybinding', 'Shows the define-keybinding widget; a new key edits (or adds) the entry through the keybinding editing service.',
                     [f'{KE}:220-234', f'{KE}:251-263'],
                     [choice('key', 'pressed', {
                         'pressed': [sets({'vars.key': 'ctrl+alt+s'})],
                         'escaped': [ret({'changed': False})]}, title='DefineKeybindingWidget.define(): the user presses a key or escapes', source=f'{KE}:224'),
                      iff(f"vars.key == {entry}.key", [ret({'changed': False})], title='Same key and when: nothing to write', source=f'{KE}:253'),
                      iff('input.add', [call(kb_add, {'command': f'= {entry}.command', 'key': '= vars.key', 'when': f'= {entry}.when'}, source=f'{KE}:255')],
                          [call(kb_edit, {'command': f'= {entry}.command', 'key': '= vars.key', 'when': f'= {entry}.when'}, source=f'{KE}:257')]),
                      ret({'changed': True, 'key': '= vars.key'})],
                     request={'type': 'object', 'properties': {'add': {'type': 'boolean', 'default': False}}})
    remove = p.iface(ke, 'remove-keybinding', 'Removes the selected entry\'s keybinding (only when it has one).', [f'{KE}:265-276'],
                     [iff(f"{entry}.key == ''", [ret({'removed': False})], source=f'{KE}:267'),
                      call(kb_remove, {'command': f'= {entry}.command'}, source=f'{KE}:269'), ret({'removed': True})])
    reset = p.iface(ke, 'reset-keybinding', 'Resets the selected entry to its default keybinding.', [f'{KE}:278-290'],
                    [call(kb_reset, {'command': f'= {entry}.command'}, source=f'{KE}:281'), ret({'reset': True})])
    copy = p.iface(ke, 'copy-keybinding', 'Copies {key, command, when} of the selected entry as JSON.', [f'{KE}:292-302'],
                   [call(clip, {'text': f"= '{{\"key\": \"' + {entry}.key + '\", \"command\": \"' + {entry}.command + '\"}}'"}, source=f'{KE}:301'), ret({'copied': True})])
    copy_cmd = p.iface(ke, 'copy-keybinding-command', 'Copies the selected entry\'s command id.', [f'{KE}:304-307'],
                       [call(clip, {'text': f'= {entry}.command'}, source=f'{KE}:306'), ret({'copied': True})])
    copy_title = p.iface(ke, 'copy-keybinding-command-title', 'Copies the selected entry\'s command label.', [f'{KE}:309-312'],
                         [call(clip, {'text': f'= {entry}.command_label'}, source=f'{KE}:311'), ret({'copied': True})])
    define_when = p.iface(ke, 'define-when-expression', 'Opens the when-expression input for an entry that has a keybinding.', [f'{KE}:236-241'],
                          [iff(f"{entry}.key == ''", [ret({'editing_when': False})], source=f'{KE}:237'),
                           sets({'state.editing_when': True}, source=f'{KE}:239'), ret({'editing_when': True})])
    clear_hist = p.iface(ke, 'clear-keyboard-shortcut-search-history', 'Clears the search history and saves it to the editor memento (PROFILE, USER).', [f'{KE}:602-606'],
                         [sets({'state.search_history': []}, source=f'{KE}:603-605'), ret({'cleared': True})])

    def ke_cmd(cid, line, handler, summary, target, inp=None, scen=None):
        return p.cmd(pc, cid, f'{PC}:{line}', f'{PC}:{handler}', summary,
                     [call('keybindings-editor.get-active', {}, as_='pane', title='activeEditorPane instanceof KeybindingsEditor', source=f'{PC}:{handler.split("-")[0]}'),
                      iff('!vars.pane.value.open', [ret({'ran': False})]),
                      call(target, inp or {}, as_='r'), ret('= vars.r.value')], scen=scen)
    p.iface(ke, 'get-active', 'Whether the active editor pane is the Keyboard Shortcuts editor.', [f'{KE}:74'], [ret({'open': '= state.open'})])
    ke_cmd('keybindings.editor.defineKeybinding', 1079, '1084-1089', 'Change Keybinding (Ctrl+K Ctrl+K in the editor): define a new key for the selected entry.', define, {'add': False},
           scen=[{'expect': ['steps.s.result.value.changed', called(kb_edit, "e.input.command == 'workbench.action.files.save' && e.input.key == 'ctrl+alt+s'")]},
                 {'id': 'define-keybinding-escaped', 'choices': {'keybindings-editor.define-keybinding.key': 'escaped'}, 'expect': ['!steps.s.result.value.changed', '!' + called(kb_edit)]},
                 {'id': 'define-keybinding-editor-closed', 'state': {'keybindings-editor@w1': {'open': False}}, 'expect': ['!steps.s.result.value.ran', '!' + called(define)]}])
    ke_cmd('keybindings.editor.addKeybinding', 1092, '1097-1102', 'Add Keybinding: adds another key for the selected command.', define, {'add': True},
           scen=[{'expect': [called(kb_add, "e.input.key == 'ctrl+alt+s'")]}])
    ke_cmd('keybindings.editor.defineWhenExpression', 1105, '1110-1115', 'Change When Expression of the selected keybinding.', define_when,
           scen=[{'expect': ["state['keybindings-editor@w1'].editing_when"]}])
    ke_cmd('keybindings.editor.removeKeybinding', 1118, '1126-1131', 'Remove Keybinding (Delete) of the selected entry.', remove,
           scen=[{'expect': [called(kb_remove, "e.input.command == 'workbench.action.files.save'")]},
                 {'id': 'remove-keybinding-unbound', 'state': {'keybindings-editor@w1': {'active_entry': {'key': ''}}}, 'expect': ['!steps.s.result.value.removed', '!' + called(kb_remove)]}])
    ke_cmd('keybindings.editor.resetKeybinding', 1134, '1139-1144', 'Reset Keybinding of the selected entry.', reset,
           scen=[{'expect': [called(kb_reset)]}])
    ke_cmd('keybindings.editor.clearSearchHistory', 1051, '1065-1070', 'Clear Keyboard Shortcuts Search History.', clear_hist,
           scen=[{'expect': ["size(state['keybindings-editor@w1'].search_history) == 0"]}])
    ke_cmd('keybindings.editor.copyKeybindingEntry', 1201, '1206-1211', 'Copy the selected keybinding entry as JSON.', copy,
           scen=[{'expect': [called(clip, "e.input.text.contains('ctrl+s')")]}])
    ke_cmd('keybindings.editor.copyCommandKeybindingEntry', 1214, '1219-1224', 'Copy Command ID of the selected entry.', copy_cmd,
           scen=[{'expect': [called(clip, "e.input.text == 'workbench.action.files.save'")]}])
    ke_cmd('keybindings.editor.copyCommandTitle', 1227, '1232-1237', 'Copy Command Title of the selected entry.', copy_title,
           scen=[{'expect': [called(clip, "e.input.text == 'File: Save'")]}])

    # editor.action.defineKeybinding (keybindings.json open in a text editor)
    dkc = p.comp('define-keybinding-editor-contribution', 'DefineKeybindingEditorContribution', 'preferences-keybindings-editor-contribution',
                 ['preferences/browser/keybindingsEditorContribution.ts:273'], 'Editor contribution on keybindings.json: the define-keybinding widget that inserts a snippet entry.')
    show = p.iface(dkc, 'show-define-keybinding-widget', 'Shows the widget; the pressed key is inserted into keybindings.json as a new entry snippet.',
                   ['preferences/browser/keybindingsEditorContribution.ts:273'],
                   [choice('key', 'pressed', {'pressed': [], 'escaped': [ret({'inserted': False})]}),
                    ret({'inserted': True})])
    p.cmd(pc, 'editor.action.defineKeybinding', f'{PC}:1282', f'{PC}:1303-1308', 'Define Keybinding in keybindings.json (Ctrl+K Ctrl+K in the text editor).',
          [call(show, {}, source=f'{PC}:1306'), ret({'shown': True})], scen=[{'expect': [called(show)]}])

    # settings.switchToJSON
    se = p.comp('settings-editor2', 'SettingsEditor2', 'preferences-contribution', ['preferences/browser/settingsEditor2.ts:120'],
                'The settings editor UI pane.')
    sw = p.iface(se, 'switch-to-settings-file', 'Opens the JSON file of the settings target shown in the settings editor, keeping the search query.', ['preferences/browser/settingsEditor2.ts:1036-1044'],
                 [call(open_settings, {'json_editor': True}), ret({'opened': True})])
    p.cmd(pc, 'settings.switchToJSON', f'{PC}:1438', f'{PC}:1457-1464', 'Open Settings (JSON) from the settings editor title.',
          [call(sw, {}, source=f'{PC}:1461'), ret({'switched': True})], scen=[{'expect': [called(open_settings, 'e.input.json_editor')]}])

    # contributions
    pac = p.comp('preferences-actions-contribution', 'PreferencesActionsContribution', pc, [f'{PC}:203'], 'Registers the settings and keybindings actions and keeps the Preferences menu in sync with the workbench state.',
                 state={'schema': {'type': 'object'}, 'initial': {'actions_registered': False}})
    p.iface(pac, 'constructor', 'Registers settings and keybindings actions, then updates the preferences menu item on workbench state and folder changes.',
            [f'{PC}:1519', f'{PC}:207-225'],
            [sets({'state.actions_registered': True}, title='registerSettingsActions + registerKeybindingsActions', source=f'{PC}:218-219'),
             call(get_ws, {}, as_='ws', title='workspaceContextService.getWorkbenchState() and folders', source=f'{PC}:1317'),
             iff("vars.ws.value.workbench_state == 'workspace'",
                 [sets({'vars.menu': ['_workbench.openWorkspaceSettingsEditor']})], [sets({'vars.menu': []})],
                 title='A multi-root workspace gets "Open Workspace Settings" on the workspace settings file', source=f'{PC}:1317-1340'),
             sets({'state.menu_commands': "= vars.menu + vars.ws.value.folders.map(f, '_workbench.openFolderSettings.' + f)"},
                  title='updatePreferencesEditorMenuItemForWorkspaceFolders: one per folder, opening folder (or workspace, in a folder window) settings', source=f'{PC}:1344-1360'),
             ret({'actions_registered': True, 'menu_commands': '= state.menu_commands'})])
    p.scenario_for('preferences-actions-contribution.constructor', {'id': 'preferences-actions-contribution', 'caller': 'workbench',
                                                                    'expect': ["state['preferences-actions-contribution@w1'].actions_registered",
                                                                               "steps.s.result.value.menu_commands == ['_workbench.openFolderSettings.file:///work/app']"]})
    return p

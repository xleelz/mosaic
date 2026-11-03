from builder import Part, call, ret, iff, choice, sets, note, called

MC = 'meteredConnection/browser/meteredConnection.contribution.ts'
KL = 'preferences/browser/keyboardLayoutPicker.ts'
TL = 'telemetry/browser/telemetry.contribution.ts'


def build():
    p = Part('rest5')
    ws, pc = 'workbench-shell', 'platform-core'
    update = p.stub('configuration-service.update-value', pc)
    set_level = p.stub('logger-service.set-log-level', pc)
    show_channel = p.stub('output-service.show-channel', 'terminal-debug-tasks')
    open_editor = p.stub('editor-service.open-editor', ws)
    create_file = p.stub('file-service.create-file', pc)
    p.cmd('metered-connection-contribution', 'workbench.action.configureMeteredConnection', f'{MC}:19', f'{MC}:31-65',
          'Configure Metered Connection: pick Auto / On / Off (current one pre-selected) and write network.meteredConnection.',
          [choice('pick', 'on', {'auto': [sets({'vars.v': 'auto'})], 'on': [sets({'vars.v': 'on'})], 'off': [sets({'vars.v': 'off'})], 'dismissed': [ret({'value': None})]},
                  title='Select Metered Connection Mode', source=f'{MC}:58-61'),
           call(update, {'key': 'network.meteredConnection', 'value': '= vars.v'}, source=f'{MC}:63-64'), ret({'value': '= vars.v'})],
          scen=[{'expect': [called(update, "e.input.key == 'network.meteredConnection' && e.input.value == 'on'")]},
                {'id': 'metered-connection-dismissed', 'choices': {'metered-connection-contribution.cmd-workbench-action-configuremeteredconnection.pick': 'dismissed'}, 'expect': ['!' + called(update)]}])
    p.cmd('preferences-keyboard-layout-picker', 'workbench.action.openKeyboardLayoutPicker', f'{KL}:103', f'{KL}:112-189',
          'Change Keyboard Layout: Auto Detect, Configure Keyboard Layout (opens keyboardLayout.json, created with defaults if missing) or a layout; writes keyboard.layout.',
          [choice('pick', 'layout', {
              'autodetect': [call(update, {'key': 'keyboard.layout', 'value': 'autodetect'}, source=f'{KL}:164-166'), ret({'layout': 'autodetect'})],
              'configure': [call(create_file, {'resource': 'vscode-userdata:/User/keyboardLayout.json', 'content': '// Place your keyboard layout here', 'overwrite': False}, as_='c', on_error='continue', title='stat, else create with the default content', source=f'{KL}:171-173'),
                            call(open_editor, {'resource': 'vscode-userdata:/User/keyboardLayout.json', 'options': {'pinned': True}}, source=f'{KL}:177-181'), ret({'layout': None})],
              'layout': [call(update, {'key': 'keyboard.layout', 'value': 'com.apple.keylayout.German'}, source=f'{KL}:188'), ret({'layout': 'com.apple.keylayout.German'})],
              'dismissed': [ret({'layout': None})]}, title='Select Keyboard Layout', source=f'{KL}:157-160')],
          scen=[{'expect': [called(update, "e.input.key == 'keyboard.layout'")]},
                {'id': 'keyboard-layout-autodetect', 'choices': {'preferences-keyboard-layout-picker.cmd-workbench-action-openkeyboardlayoutpicker.pick': 'autodetect'}, 'expect': [called(update, "e.input.value == 'autodetect'")]},
                {'id': 'keyboard-layout-configure', 'choices': {'preferences-keyboard-layout-picker.cmd-workbench-action-openkeyboardlayoutpicker.pick': 'configure'}, 'expect': [called(open_editor)]}])
    p.cmd('telemetry-contribution', 'workbench.action.showTelemetry', f'{TL}:239', f'{TL}:248-256',
          'Developer: Show Telemetry: telemetry loggers go to Trace and become visible, then the Telemetry output channel is shown.',
          [call(set_level, {'resource': 'file:///user/logs/telemetry.log', 'log_level': 'trace'}, title='Each logger of the telemetry group: trace + visible', source=f'{TL}:249-254'),
           call(show_channel, {'id': 'telemetry', 'preserve_focus': False}, source=f'{TL}:255'), ret({'shown': True})],
          scen=[{'expect': [called(set_level, "e.input.log_level == 'trace'"), called(show_channel, "e.input.id == 'telemetry'")]}])
    return p

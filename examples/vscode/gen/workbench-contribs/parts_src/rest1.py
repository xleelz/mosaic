from builder import Part, call, ret, iff, choice, sets, note, called, foreach

LA = 'logs/common/logsActions.ts'
LC = 'logs/common/logs.contribution.ts'
LN = 'logs/electron-browser'
LO = 'localization/common/localizationsActions.ts'
BE = 'bulkEdit/browser/preview'
FM = 'format/browser/formatActionsMultiple.ts'


def build():
    p = Part('rest1')
    ws, pc = 'workbench-shell', 'platform-core'
    set_level = p.stub('logger-service.set-log-level', pc)
    default_level = p.stub('default-log-levels-service.set-default-log-level', ws, {'type': 'object', 'properties': {'log_level': {'type': 'string'}, 'extension_id': {'type': ['string', 'null']}}})
    show_channel = p.stub('output-service.show-channel', 'terminal-debug-tasks')
    show_folder = p.stub('native-host-service.show-item-in-folder', ws)
    open_editor = p.stub('editor-service.open-editor', ws)
    notify = p.stub('notification-service.notify', ws)
    set_locale = p.stub('locale-service.set-locale', ws, {'type': 'object', 'properties': {'locale': {'type': 'string'}}})
    clear_locale = p.stub('locale-service.clear-locale-preference', ws)
    qa = p.stub('quick-input-service.quick-access-show', ws)
    confirm = p.stub('dialog-service.confirm', ws)
    warn = p.stub('dialog-service.warn', ws, {'type': 'object', 'properties': {'message': {'type': 'string'}}})
    exec_cmd = p.stub('command-service.execute-command', pc)
    ordered = p.stub('language-features-service.ordered', 'editor')
    fmt_with = p.stub('format.format-document-with-provider', 'editor')
    fmt_ranges = p.stub('format.format-document-ranges-with-selected-provider', 'editor')
    update = p.stub('configuration-service.update-value', pc)

    # ---- logs ----
    p.cmd('logs-contribution-common', 'workbench.action.setLogLevel', f'{LC}:25', [f'{LC}:33-36', f'{LA}:38-47'],
          'Developer: Set Log Level...: pick a level for all loggers or pick a channel, then its level.',
          [choice('pick', 'global', {
              'global': [call(set_level, {'log_level': 'debug'}, title='A level: loggerService.setLogLevel(level)', source=f'{LA}:42'), ret({'scope': 'global', 'level': 'debug'})],
              'channel': [call('output-service.set-log-level', {'channel_id': 'exthost', 'log_level': 'trace'}, title='A channel, then its level: outputService.setLogLevel', source=f'{LA}:129'), ret({'scope': 'channel', 'level': 'trace'})],
              'dismissed': [ret({'scope': None})]}, source=f'{LA}:39-46')],
          scen=[{'expect': [called(set_level, "e.input.log_level == 'debug'")]},
                {'id': 'set-log-level-channel', 'choices': {'logs-contribution-common.cmd-workbench-action-setloglevel.pick': 'channel'}, 'expect': [called('output-service.set-log-level')]}])
    p.stub('output-service.set-log-level', 'terminal-debug-tasks')
    p.cmd('logs-contribution-common', 'workbench.action.setDefaultLogLevel', f'{LC}:40', f'{LC}:48-50', 'Set Default Log Level (programmatic): persists the default level, optionally for one extension.',
          [call(default_level, {'log_level': '= input.log_level', 'extension_id': "= has(input.extension_id) ? input.extension_id : null"}, source=f'{LC}:49'), ret({'level': '= input.log_level'})],
          request={'type': 'object', 'properties': {'log_level': {'type': 'string', 'default': 'debug'}}},
          scen=[{'expect': [called(default_level, "e.input.log_level == 'debug'")]}])
    p.cmd('logs-contribution-common', 'workbench.action.showWindowLog', f'{LC}:183', f'{LC}:192-195', 'Developer: Show Window Log: reveals the "Window" output channel.',
          [call(show_channel, {'id': 'rendererLog', 'preserve_focus': False}, source=f'{LC}:194'), ret({'shown': 'rendererLog'})],
          scen=[{'expect': [called(show_channel, "e.input.id == 'rendererLog'")]}])
    p.cmd('logs-contribution-native', 'workbench.action.openLogsFolder', f'{LN}/logs.contribution.ts:12', [f'{LN}/logs.contribution.ts:21-23', f'{LN}/logsActions.ts:26-28'],
          'Developer: Open Logs Folder: reveals main.log of the logs home in the OS file manager.',
          [call(show_folder, {'path': '/user/logs/20261030T000000/main.log'}, source=f'{LN}/logsActions.ts:27'), ret({'revealed': True})],
          scen=[{'expect': [called(show_folder, "e.input.path.endsWith('main.log')")]}])
    p.cmd('logs-contribution-native', 'workbench.action.openExtensionLogsFolder', f'{LN}/logs.contribution.ts:26', [f'{LN}/logs.contribution.ts:35-37', f'{LN}/logsActions.ts:44-49'],
          'Developer: Open Extension Logs Folder: reveals the first entry of the extension host logs folder.',
          [call(show_folder, {'path': '/user/logs/20261030T000000/window1/exthost/exthost.log'}, source=f'{LN}/logsActions.ts:47'), ret({'revealed': True})],
          scen=[{'expect': [called(show_folder, "e.input.path.contains('exthost')")]}])
    p.cmd('logs-contribution', 'workbench.action.openSessionLogFile', 'logs/browser/logs.contribution.ts:28', [f'{LA}:175-200'],
          'Developer: Open Window Log File (Session)...: pick a session, then a log file, open it pinned (web).',
          [choice('pick', 'file', {'file': [], 'dismissed': [ret({'opened': None})]}, source=f'{LA}:176-196'),
           call(open_editor, {'resource': 'vscode-userdata:/logs/20261030T000000/window1/renderer.log', 'options': {'pinned': True}}, source=f'{LA}:197'),
           ret({'opened': 'renderer.log'})],
          scen=[{'expect': [called(open_editor, 'e.input.options.pinned')]}])

    # ---- localization ----
    lc = 'localization-contribution-common'
    p.cmd(lc, 'workbench.action.configureLocale', 'localization/common/localization.contribution.ts:22', f'{LO}:31-95',
          'Configure Display Language: pick an installed or marketplace language pack; the locale service writes argv.json locale and asks to restart.',
          [choice('pick', 'installed', {'installed': [sets({'vars.l': 'de'})], 'dismissed': [ret({'locale': None})]}, source=f'{LO}:44-68'),
           call(set_locale, {'locale': '= vars.l'}, source=f'{LO}:70'), ret({'locale': '= vars.l'})],
          scen=[{'expect': [called(set_locale, "e.input.locale == 'de'")]},
                {'id': 'configure-locale-dismissed', 'choices': {'localization-contribution-common.cmd-workbench-action-configurelocale.pick': 'dismissed'}, 'expect': ['!' + called(set_locale)]}])
    p.cmd(lc, 'workbench.action.clearLocalePreference', 'localization/common/localization.contribution.ts:23', f'{LO}:112-115',
          'Clear Display Language Preference.', [call(clear_locale, {}, source=f'{LO}:114'), ret({'cleared': True})], scen=[{'expect': [called(clear_locale)]}])

    # ---- quick access ----
    qc = 'quickaccess-quick-access-contribution'
    QA = 'quickaccess/browser'
    p.cmd(qc, 'workbench.action.showCommands', f'{QA}/quickAccess.contribution.ts:116', f'{QA}/commandsQuickAccess.ts:291-293', 'Show All Commands: the command palette (">" prefix).',
          [call(qa, {'prefix': '>'}, source=f'{QA}/commandsQuickAccess.ts:292'), ret({'prefix': '>'})], scen=[{'expect': [called(qa, "e.input.prefix == '>'")]}])
    p.cmd(qc, 'workbench.action.openView', f'{QA}/quickAccess.contribution.ts:117', f'{QA}/viewQuickAccess.ts:242-244', 'Open View: quick access with the "view " prefix.',
          [call(qa, {'prefix': 'view '}, source=f'{QA}/viewQuickAccess.ts:243'), ret({'prefix': 'view '})], scen=[{'expect': [called(qa, "e.input.prefix == 'view '")]}])
    p.cmd(qc, 'workbench.action.quickOpenView', f'{QA}/quickAccess.contribution.ts:118', f'{QA}/viewQuickAccess.ts:270-277', 'Quick Open View (Ctrl+Q): view picker with quick navigation, first item active.',
          [call(qa, {'prefix': 'view '}, source=f'{QA}/viewQuickAccess.ts:276'), ret({'prefix': 'view '})], scen=[{'expect': [called(qa)]}])
    p.configs.append({'id': 'workbench-command-palette-history', 'type': 'integer', 'value': 50, 'default': 50, 'summary': 'workbench.commandPalette.history: recently used commands kept (0 disables).',
                      'sources': ['src/vs/workbench/browser/workbench.contribution.ts:515-518', f'src/vs/workbench/contrib/{QA}/commandsQuickAccess.ts:311'],
                      'attributes': {'key': 'workbench.commandPalette.history', 'boundary': True, 'owner': 'workbench-shell'}})
    p.cmd(qc, 'workbench.action.clearCommandHistory', f'{QA}/quickAccess.contribution.ts:115', f'{QA}/commandsQuickAccess.ts:306-328',
          'Clear Command History: with history enabled, confirm ("This action is irreversible!") and reset the recently used commands.',
          [iff("config['workbench-command-palette-history'] <= 0", [ret({'cleared': False})], source=f'{QA}/commandsQuickAccess.ts:312'),
           call(confirm, {'message': 'Do you want to clear the history of recently used commands?', 'primary_button': '&&Clear'}, as_='c', source=f'{QA}/commandsQuickAccess.ts:315-321'),
           iff('!vars.c.value.confirmed', [ret({'cleared': False})], source=f'{QA}/commandsQuickAccess.ts:322-324'),
           sets({'state.command_history': []}, title='CommandsHistory.clearHistory: a fresh LRU cache', source='src/vs/platform/quickinput/browser/commandsQuickAccess.ts:500-506'),
           ret({'cleared': True})],
          scen=[{'state': {'quickaccess-quick-access-contribution@w1': {'command_history': ['workbench.action.files.save']}}, 'expect': ["size(state['quickaccess-quick-access-contribution@w1'].command_history) == 0"]},
                {'id': 'clear-command-history-declined', 'choices': {'dialog-service.confirm.answer': 'cancel'}, 'expect': ['!steps.s.result.value.cleared', called(confirm)]},
                {'id': 'clear-command-history-disabled', 'config': {'workbench-command-palette-history': 0}, 'expect': ['!steps.s.result.value.cleared', '!' + called(confirm)]}])
    CC = 'commands/common/commands.contribution.ts'
    p.cmd('commands-contribution-common', 'runCommands', f'{CC}:157', f'{CC}:80-145',
          'Run Commands: runs the given commands in sequence (string or {command, args}); stops at the first error, which is notified.',
          [iff("!has(input.commands)", [call(notify, {'severity': 'error', 'message': "'runCommands' has received an argument with incorrect type. Please, review the argument passed to the command."}, source=f'{CC}:85-88'), ret({'ran': 0})]),
           iff('size(input.commands) == 0', [call(notify, {'severity': 'warning', 'message': "'runCommands' has not received commands to run. Did you forget to pass commands in the 'runCommands' argument?"}, source=f'{CC}:90-93'), ret({'ran': 0})]),
           sets({'vars.ran': 0, 'vars.failed': False}),
           foreach('= input.commands', 'cmd', [
               iff('vars.failed', [{'break': True}]),
               call(exec_cmd, {'command_id': '= vars.cmd.command', 'args': "= has(vars.cmd.args) ? vars.cmd.args : []"}, as_='r', on_error='continue', source=f'{CC}:102'),
               iff('!vars.r.ok', [call(notify, {'severity': 'error', 'message': '= vars.r.error.message'}, source=f'{CC}:107'), sets({'vars.failed': True})], [sets({'vars.ran': '= vars.ran + 1'})])]),
           ret({'ran': '= vars.ran'})],
          request={'type': 'object', 'properties': {'commands': {'type': 'array', 'default': [{'command': 'welcome.markStepComplete', 'args': ['pickColorTheme']}, {'command': 'welcome.markStepIncomplete', 'args': ['pickColorTheme']}]}}},
          scen=[{'expect': ['steps.s.result.value.ran == 2', called(exec_cmd, "e.input.command_id == 'welcome.markStepIncomplete'")]},
                {'id': 'run-commands-empty', 'input': {'commands': []}, 'expect': [called(notify, "e.input.severity == 'warning'")]},
                {'id': 'run-commands-unknown', 'input': {'commands': [{'command': 'no.such.command'}, {'command': 'welcome.markStepComplete', 'args': ['pickColorTheme']}]},
                 'expect': ['steps.s.result.value.ran == 0', called(notify, "e.input.severity == 'error'"), '!' + called(exec_cmd, "e.input.command_id == 'welcome.markStepComplete'")]}])

    # ---- refactor preview pane ----
    bp = p.comp('bulk-edit-pane', 'BulkEditPane', 'bulk-edit-preview-contribution', [f'{BE}/bulkEditPane.ts:49'],
                'The Refactor Preview view: the pending edit, its grouping and the checked state of its elements.',
                state={'schema': {'type': 'object'}, 'initial': {'has_input': False, 'group_by_file': True, 'unchecked': [], 'resolved': ''}})
    p.seed['bulk-edit-pane'] = {'has_input': True, 'group_by_file': True, 'unchecked': [], 'focused': 'file:///work/app/src/main.ts', 'resolved': '', 'conflicts': []}
    accept = p.iface(bp, 'accept', 'Apply: resolves the preview with the checked edits, unless a file changed meanwhile (warning, then discard).', [f'{BE}/bulkEditPane.ts:253-266'],
                     [iff('size(state.conflicts) > 0', [call(warn, {'message': "= 'Cannot apply refactoring because \\'' + state.conflicts[0] + '\\' has changed in the meantime.'"}, source=f'{BE}/bulkEditPane.ts:260-265'),
                                                        sets({'state.resolved': 'discarded', 'state.has_input': False}), ret({'applied': False})], source=f'{BE}/bulkEditPane.ts:255'),
                      sets({'state.resolved': 'accepted', 'state.has_input': False}, title='_done(true)', source=f'{BE}/bulkEditPane.ts:256'), ret({'applied': True})])
    discard = p.iface(bp, 'discard', 'Discard: resolves the preview with no edits.', [f'{BE}/bulkEditPane.ts:272-274'],
                      [sets({'state.resolved': 'discarded', 'state.has_input': False}, source=f'{BE}/bulkEditPane.ts:273'), ret({'applied': False})])
    toggle_checked = p.iface(bp, 'toggle-checked', 'Toggles the checked state of the focused file/edit/category element.', [f'{BE}/bulkEditPane.ts:283-290'],
                             [sets({'state.unchecked': '= state.focused in state.unchecked ? state.unchecked.filter(x, x != state.focused) : state.unchecked + [state.focused]'}, source=f'{BE}/bulkEditPane.ts:285-289'),
                              ret({'checked': '= !(state.focused in state.unchecked)'})])
    toggle_group = p.iface(bp, 'toggle-grouping', 'Switches between grouping by file and by type, keeping the tree view state per mode.', [f'{BE}/bulkEditPane.ts:304-320'],
                           [sets({'state.group_by_file': '= !state.group_by_file'}), ret({'group_by_file': '= state.group_by_file'})])
    BC = f'{BE}/bulkEdit.contribution.ts'

    def pane_cmd(cid, line, handler, summary, steps, scen):
        p.cmd('bulk-edit-preview-contribution', cid, f'{BC}:{line}', f'{BC}:{handler}', summary,
              [note('getBulkEditPane(viewsService)', source=f'{BC}:{handler.split("-")[0]}')] + steps, scen=scen)
    pane_cmd('refactorPreview.apply', 165, '186-190', 'Apply Refactoring (Ctrl/Cmd+Enter in the preview).', [call(accept, {}, as_='r', source=f'{BC}:189'), ret('= vars.r.value')],
             [{'expect': ["state['bulk-edit-pane@w1'].resolved == 'accepted'"]},
              {'id': 'refactor-apply-conflict', 'state': {'bulk-edit-pane@w1': {'conflicts': ['src/main.ts']}}, 'expect': [called(warn), "state['bulk-edit-pane@w1'].resolved == 'discarded'"]}])
    pane_cmd('refactorPreview.discard', 194, '210-214', 'Discard Refactoring.', [call(discard, {}, as_='r', source=f'{BC}:213'), ret('= vars.r.value')],
             [{'expect': ["state['bulk-edit-pane@w1'].resolved == 'discarded'"]}])
    pane_cmd('refactorPreview.toggleCheckedState', 219, '239-243', 'Toggle Change (Space): include or exclude the focused change.', [call(toggle_checked, {}, as_='r', source=f'{BC}:242'), ret('= vars.r.value')],
             [{'expect': ["'file:///work/app/src/main.ts' in state['bulk-edit-pane@w1'].unchecked"]}])
    pane_cmd('refactorPreview.groupByFile', 248, '266-270', 'Group Changes By File (toggles only when grouped by type).',
             [call('bulk-edit-pane.get-grouping', {}, as_='g'),
              iff('!vars.g.value.group_by_file', [call(toggle_group, {}, source='bulkEdit/browser/preview/bulkEditPane.ts:293-295')], source='bulkEdit/browser/preview/bulkEditPane.ts:293'), ret({'group_by_file': True})],
             [{'state': {'bulk-edit-pane@w1': {'group_by_file': False}}, 'expect': ["state['bulk-edit-pane@w1'].group_by_file"]}])
    pane_cmd('refactorPreview.groupByType', 273, '291-295', 'Group Changes By Type (toggles only when grouped by file).',
             [call('bulk-edit-pane.get-grouping', {}, as_='g'),
              iff('vars.g.value.group_by_file', [call(toggle_group, {}, source='bulkEdit/browser/preview/bulkEditPane.ts:299-301')], source='bulkEdit/browser/preview/bulkEditPane.ts:299'), ret({'group_by_file': False})],
             [{'expect': ["!state['bulk-edit-pane@w1'].group_by_file"]}])
    pane_cmd('refactorPreview.toggleGrouping', 298, '315-319', 'Toggle grouping between file and type.', [call(toggle_group, {}, as_='r', source=f'{BC}:318'), ret('= vars.r.value')],
             [{'expect': ["!state['bulk-edit-pane@w1'].group_by_file"]}])
    p.iface(bp, 'get-grouping', 'Current grouping mode (_treeDataSource.groupByFile).', [f'{BE}/bulkEditPane.ts:292-302'], [ret({'group_by_file': '= state.group_by_file'})])

    # ---- format commands ----
    ed = ['editor-dirty', 'editor-ts-providers', 'workbench-contribs-seed']
    p.cmd('format-actions-multiple', 'editor.action.formatDocument.multiple', f'{FM}:360', f'{FM}:375-399',
          'Format Document With...: a given formatter (args.formatter) or a pick among the document formatters (or Configure Default Formatter...), then format explicitly.',
          [call(ordered, {'feature': 'documentFormatting', 'language_id': 'typescript'}, as_='o', source=f'{FM}:381'),
           iff('has(input.formatter)', [sets({'vars.p': '= vars.o.value.providers.filter(x, x.extension_id == input.formatter)'}),
                                        iff('size(vars.p) == 0', [ret({'formatted': False})], title='Unknown formatter: nothing', source=f'{FM}:386-389')],
               [choice('pick', 'first', {'first': [sets({'vars.p': '= vars.o.value.providers'})],
                                         'configure': [call('default-formatter.pick-and-persist-default-formatter', {'formatters': ['vscode.typescript-language-features'], 'language_id': 'typescript'}, source=f'{FM}:335-342'), ret({'formatted': False})],
                                         'dismissed': [ret({'formatted': False})]}, title='showFormatterPick', source=f'{FM}:390-394'),
                iff('size(vars.p) == 0', [ret({'formatted': False})], title='No document formatter for the model')]),
           call(fmt_with, {'resource': 'file:///work/app/src/main.ts', 'handle': '= vars.p[0].handle', 'mode': 'explicit', 'via_editor': True}, source=f'{FM}:398'),
           ret({'formatted': True, 'formatter': '= vars.p[0].extension_id'})],
          request={'type': 'object'},
          scen=[{'fixtures': ed, 'expect': ["steps.s.result.value.formatter == 'vscode.typescript-language-features'", called(fmt_with, "e.input.mode == 'explicit'")]},
                {'id': 'format-with-unknown-formatter', 'fixtures': ed, 'input': {'formatter': 'acme.nope'}, 'expect': ['!steps.s.result.value.formatted', '!' + called(fmt_with)]},
                {'id': 'format-with-configure', 'fixtures': ed, 'choices': {'format-actions-multiple.cmd-editor-action-formatdocument-multiple.pick': 'configure'}, 'expect': [called(update, "e.input.key == 'editor.defaultFormatter'")]}])
    p.cmd('format-actions-multiple', 'editor.action.formatSelection.multiple', f'{FM}:402', f'{FM}:418-436',
          'Format Selection With...: an empty selection grows to its whole line; pick a range formatter, format the range.',
          [sets({'vars.range': {'start_line': 2, 'start_column': 1, 'end_line': 2, 'end_column': 25}}, title='Empty selection: the full line', source=f'{FM}:427-428'),
           call(ordered, {'feature': 'documentRangeFormatting', 'language_id': 'typescript'}, as_='o', source=f'{FM}:430'),
           choice('pick', 'first', {'first': [], 'dismissed': [ret({'formatted': False})]}, source=f'{FM}:431-433'),
           call(fmt_ranges, {'resource': 'file:///work/app/src/main.ts', 'ranges': ['= vars.range'], 'mode': 'explicit'}, title='formatDocumentRangesWithProvider(picked provider)', source=f'{FM}:434'),
           ret({'formatted': True})],
          scen=[{'fixtures': ed, 'expect': [called(fmt_ranges, 'e.input.ranges[0].start_line == 2')]}])
    p.cmd('format-modified', 'editor.action.formatChanges', 'format/browser/formatModified.ts:23', 'format/browser/formatModified.ts:33-48',
          'Format Modified Lines: formats only the ranges changed against the SCM original.',
          [call('format-modified.get-modified-ranges', {'resource': 'file:///work/app/src/main.ts'}, as_='r', source='format/browser/formatModified.ts:39'),
           iff("vars.r.value.status != 'ranges'", [ret({'formatted': False})], source='format/browser/formatModified.ts:40'),
           call(fmt_ranges, {'resource': 'file:///work/app/src/main.ts', 'ranges': '= vars.r.value.ranges', 'mode': 'explicit'}, source='format/browser/formatModified.ts:41-46'),
           ret({'formatted': True})],
          scen=[{'fixtures': ed, 'expect': [called(fmt_ranges)]},
                {'id': 'format-changes-no-scm', 'fixtures': ed, 'choices': {'format-modified.get-modified-ranges.diff': 'no-scm'}, 'expect': ['!' + called(fmt_ranges)]}])
    p.cmd('format-actions-multiple', 'formatter/configure/dfl/${generateUuid()}', f'{FM}:254', f'{FM}:254-255',
          '"Configure..." on the Formatter Conflicts language status item (a fresh command id per status): pick and persist the default formatter.',
          [call('default-formatter.pick-and-persist-default-formatter', {'formatters': ['esbenp.prettier-vscode', 'vscode.typescript-language-features'], 'language_id': 'typescript'}, as_='r', source=f'{FM}:255'),
           ret('= vars.r.value')],
          scen=[{'id': 'configure-formatter-status', 'expect': [called(update, "e.input.key == 'editor.defaultFormatter' && e.input.value == 'esbenp.prettier-vscode'")]}])
    return p

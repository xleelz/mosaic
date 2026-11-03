from builder import Part, call, ret, iff, choice, sets, note, called

AV = 'accessibility/browser/accessibleView.ts'
AA = 'accessibility/browser/accessibleViewActions.ts'
IC = 'issue/common/issue.contribution.ts'
IS = 'issue/electron-browser/issueService.ts'
IN = 'issue/electron-browser/issue.contribution.ts'


def build():
    p = Part('rest4')
    ws, pc = 'workbench-shell', 'platform-core'
    update = p.stub('configuration-service.update-value', pc)
    opener = p.stub('opener-service.open', pc)
    exec_cmd = p.stub('command-service.execute-command', pc)
    notify = p.stub('notification-service.notify', ws)
    p.configs.append({'id': 'telemetry-feedback-enabled', 'type': 'boolean', 'value': True, 'default': True,
                      'summary': 'telemetry.feedback.enabled: issue reporter, surveys and other feedback. When off, openIssueReporter only says "Feedback is disabled."',
                      'sources': ['src/vs/platform/telemetry/common/telemetryService.ts:381-383', f'src/vs/workbench/contrib/{IC}:68'], 'attributes': {'key': 'telemetry.feedback.enabled'}})

    # ---- accessible view ----
    avs = 'accessible-view-service'
    p.seed[avs] = {'current_provider': {'id': 'editor', 'verbosity_key': 'accessibility.verbosity.editor', 'read_more_url': 'https://code.visualstudio.com/docs/editor/accessibility',
                                        'configure_items': ['editor.action.accessibleView']}}
    dh = p.iface(avs, 'disable-hint', 'Turns off the current provider\'s verbosity setting and announces it.', [f'{AV}:564-569', f'{AV}:1036-1038'],
                 [iff("!has(state.current_provider) || state.current_provider.verbosity_key == ''", [ret({'disabled': None})], source=f'{AV}:565-567'),
                  call(update, {'key': '= state.current_provider.verbosity_key', 'value': False}, source=f'{AV}:568'), ret({'disabled': '= state.current_provider.verbosity_key'})])
    ck = p.iface(avs, 'configure-keybindings', 'Quick pick of the provider\'s (un)assigned commands; accepting opens the keybindings editor on that command.', [f'{AV}:478-500', f'{AV}:1005-1007'],
                 [iff("!has(state.current_provider) || size(state.current_provider.configure_items) == 0", [ret({'opened': False})], source=f'{AV}:481-484'),
                  choice('pick', 'first', {'first': [], 'dismissed': [ret({'opened': False})]}, source=f'{AV}:491-496'),
                  call(exec_cmd, {'command_id': 'workbench.action.openGlobalKeybindings', 'args': ['= state.current_provider.configure_items[0]']}, source=f'{AV}:494', on_error='continue'),
                  ret({'opened': True})],
                 request={'type': 'object', 'properties': {'unassigned': {'type': 'boolean', 'default': True}}})
    hl = p.iface(avs, 'open-help-link', 'Opens the provider\'s read-more URL, if any.', [f'{AV}:471-476', f'{AV}:1008-1010'],
                 [iff("!has(state.current_provider) || state.current_provider.read_more_url == ''", [ret({'opened': False})], source=f'{AV}:472-474'),
                  call(opener, {'resource': '= state.current_provider.read_more_url'}, source=f'{AV}:475'), ret({'opened': True})])
    aa = 'accessibility-accessible-view-actions'
    p.cmd(aa, 'editor.action.accessibleViewDisableHint', f'{AA}:229', f'{AA}:225-227', 'Disable Accessible View Hint for the current provider.',
          [call(dh, {}, as_='r', source=f'{AA}:226'), ret('= vars.r.value')],
          scen=[{'expect': [called(update, "e.input.key == 'accessibility.verbosity.editor' && e.input.value == false")]},
                {'id': 'disable-hint-no-provider', 'state': {'accessible-view-service@w1': {'current_provider': {'verbosity_key': ''}}}, 'expect': ['!' + called(update)]}])
    p.cmd(aa, 'editor.action.accessibilityHelpConfigureKeybindings', f'{AA}:256', f'{AA}:252-254', 'Accessibility Help: configure keybindings for commands without one.',
          [call(ck, {'unassigned': True}, as_='r', source=f'{AA}:253'), ret('= vars.r.value')],
          scen=[{'expect': [called(exec_cmd, "e.input.command_id == 'workbench.action.openGlobalKeybindings'")]}])
    p.cmd(aa, 'editor.action.accessibilityHelpConfigureAssignedKeybindings', f'{AA}:283', f'{AA}:279-281', 'Accessibility Help: change keybindings of commands that have one.',
          [call(ck, {'unassigned': False}, as_='r', source=f'{AA}:280'), ret('= vars.r.value')],
          scen=[{'choices': {'accessible-view-service.configure-keybindings.pick': 'dismissed'}, 'expect': ['!steps.s.result.value.opened', '!' + called(exec_cmd)]}])
    p.cmd(aa, 'editor.action.accessibilityHelpOpenHelpLink', f'{AA}:302', f'{AA}:298-300', 'Accessibility Help: open the documentation link of the current help.',
          [call(hl, {}, as_='r', source=f'{AA}:299'), ret('= vars.r.value')],
          scen=[{'expect': [called(opener, "e.input.resource.startsWith('https://code.visualstudio.com')")]}])

    # ---- issue reporter ----
    nis = 'native-issue-service'
    open_rep = p.iface(nis, 'open-reporter', 'Opens the issue reporter window with the given data (extension id, issue source).', [f'{IS}:52-100'],
                       [sets({'state.reporter_open': True, 'state.reporter_data': '= input'}, title='issueFormService.openReporter(issueReporterData)', source=f'{IS}:95'),
                        ret({'opened': True})],
                       request={'type': 'object', 'properties': {'extension_id': {'type': 'string', 'default': ''}}})
    icc = 'issue-contribution-common'
    for cid, line in (('workbench.action.openIssueReporter', 70), ('vscode.openIssueReporter', 100)):
        p.cmd(icc, cid, f'{IC}:{line}', [f'{IC}:68-79', f'{IC}:{line - 1}-{line + 9}'],
              'Report Issue: opens the issue reporter (args: extension id string, [id] or options); with feedback disabled only "Feedback is disabled."',
              [iff("!config['telemetry-feedback-enabled']",
                   [call(notify, {'severity': 'info', 'message': 'Feedback is disabled.'}, source=f'{IC}:73-74'), ret({'opened': False})] if line == 70 else
                   [{'fail': {'code': 'command-not-found', 'message': "command 'vscode.openIssueReporter' not found"}}],
                   title='Feedback disabled: only a stub workbench.action.openIssueReporter is registered', source=f'{IC}:68'),
               call(open_rep, {'extension_id': "= has(input.extension_id) ? input.extension_id : ''"}, as_='r', source=f'{IC}:{line + 8}'), ret('= vars.r.value')],
              request={'type': 'object', 'properties': {'extension_id': {'type': 'string', 'default': 'vscode.git'}}},
              scen=[{'expect': ["state['native-issue-service@w1'].reporter_data.extension_id == 'vscode.git'"]},
                    ({'id': 'issue-feedback-off', 'config': {'telemetry-feedback-enabled': False}, 'expect': [called(notify, "e.input.message == 'Feedback is disabled.'"), '!' + called(open_rep)]} if line == 70 else
                     {'id': 'api-issue-feedback-off', 'config': {'telemetry-feedback-enabled': False}, 'fails': True, 'expect': ["steps.s.result.error.code == 'command-not-found'"]})],
              errors=[{'code': 'command-not-found', 'status': 0, 'retryable': False}])
    return p

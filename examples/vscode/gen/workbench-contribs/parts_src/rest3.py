from builder import Part, call, ret, iff, choice, sets, note, called, foreach

MP = 'mediaPreview/browser'
EV = 'editSessions/browser/editSessionsViews.ts'
EC = 'editSessions/browser/editSessions.contribution.ts'
ES = 'editSessions/browser/editSessionsStorageService.ts'
CONFIGURED = {'edit-sessions-store': 'https://edit-sessions.example'}


def build():
    p = Part('rest3')
    ws, pc = 'workbench-shell', 'platform-core'
    reg_editor = p.stub('editor-resolver-service.register-editor', ws, {'type': 'object', 'properties': {'glob': {'type': 'string'}, 'id': {'type': 'string'}, 'priority': {'type': 'string'}}})
    replace = p.stub('editor-service.replace-editors', ws, {'type': 'object', 'properties': {'replacements': {'type': 'array'}, 'group': {'type': 'integer'}}})
    set_ctx = p.stub('context-key-service.set-context', pc)
    exec_cmd = p.stub('command-service.execute-command', pc)
    clip_img = p.stub('clipboard-service.write-image', ws, {'type': 'object', 'properties': {'resource': {'type': 'string'}}})
    show_channel = p.stub('output-service.show-channel', 'terminal-debug-tasks')
    open_view = p.stub('views-service.open-view', ws, {'type': 'object', 'properties': {'id': {'type': 'string'}, 'focus': {'type': 'boolean'}}})
    confirm = p.stub('dialog-service.confirm', ws)

    # ---- media preview ----
    mc = 'media-preview-contribution'
    rc = p.comp('media-preview-editor-resolver-contribution', 'MediaPreviewEditorResolverContribution', mc, [f'{MP}/mediaPreview.contribution.ts:121'],
                'Registers the built-in image, video and audio preview editors for their file patterns.')
    p.iface(rc, 'constructor', 'Registers imagePreview.previewEditor for *.{jpg,...,svg} and the video and audio players with builtin priority.',
            [f'{MP}/mediaPreview.contribution.ts:177', f'{MP}/mediaPreview.contribution.ts:125-174'],
            [call(reg_editor, {'glob': '*.{jpg,jpe,jpeg,png,bmp,gif,ico,webp,avif,svg}', 'id': 'imagePreview.previewEditor', 'priority': 'builtin'}, source=f'{MP}/mediaPreview.contribution.ts:141-147'),
             call(reg_editor, {'glob': 'video', 'id': 'vscode.videoPreview', 'priority': 'builtin'}, title='registerMediaPlayer(video)', source=f'{MP}/mediaPreview.contribution.ts:172'),
             call(reg_editor, {'glob': 'audio', 'id': 'vscode.audioPreview', 'priority': 'builtin'}, title='registerMediaPlayer(audio)', source=f'{MP}/mediaPreview.contribution.ts:173'),
             ret({'registered': 3})])
    p.scenario_for(f'{rc}.constructor', {'id': 'media-preview-resolver', 'caller': 'workbench', 'expect': [called(reg_editor, "e.input.id == 'imagePreview.previewEditor'")]})
    lm = p.comp('media-preview-legacy-editor-migration', 'MediaPreviewLegacyEditorMigration', mc, [f'{MP}/mediaPreview.contribution.ts:192'],
                'Replaces restored editors of the former media-preview extension custom editors with the built-in previews.')
    p.iface(lm, 'constructor', 'For each restored legacy media custom editor (imagePreview.previewEditor, vscode.videoPreview, vscode.audioPreview), replace it in its group, keeping pinned/sticky.',
            [f'{MP}/mediaPreview.contribution.ts:236', f'{MP}/mediaPreview.contribution.ts:196-232'],
            [sets({'vars.legacy': "= input.restored.filter(e, e.view_type in ['imagePreview.previewEditor', 'vscode.videoPreview', 'vscode.audioPreview'])"}, source=f'{MP}/mediaPreview.contribution.ts:183-185'),
             iff('size(vars.legacy) == 0', [ret({'replaced': 0})]),
             call(replace, {'replacements': "= vars.legacy.map(e, {'resource': e.resource, 'override': e.view_type})", 'group': 1}, source=f'{MP}/mediaPreview.contribution.ts:231'),
             ret({'replaced': '= size(vars.legacy)'})],
            request={'type': 'object', 'properties': {'restored': {'type': 'array', 'default': [{'resource': 'file:///work/app/logo.png', 'view_type': 'imagePreview.previewEditor'}, {'resource': 'file:///work/app/src/main.ts', 'view_type': 'default'}]}}})
    p.scenario_for(f'{lm}.constructor', {'id': 'media-legacy-migration', 'caller': 'workbench', 'expect': ['steps.s.result.value.replaced == 1', called(replace)]})
    p.scenario_for(f'{lm}.constructor', {'id': 'media-legacy-none', 'caller': 'workbench', 'input': {'restored': []}, 'expect': ['!' + called(replace)]})
    ac = p.comp('active-image-preview-context-key-contribution', 'ActiveImagePreviewContextKeyContribution', mc, [f'{MP}/activeMediaPreview.ts:51'],
                'Keeps the activeImagePreview context key true while the active inner editor is an image preview.')
    p.iface(ac, 'constructor', 'Binds activeImagePreview and sets it on every active inner editor pane change.', [f'{MP}/mediaPreview.contribution.ts:244', f'{MP}/activeMediaPreview.ts:55-63'],
            [call(set_ctx, {'key': 'activeImagePreview', 'value': "= input.active_editor_id == 'imagePreview.previewEditor'"}, source=f'{MP}/activeMediaPreview.ts:62'), ret({'active': "= input.active_editor_id == 'imagePreview.previewEditor'"})],
            request={'type': 'object', 'properties': {'active_editor_id': {'type': 'string', 'default': 'imagePreview.previewEditor'}}})
    p.scenario_for(f'{ac}.constructor', {'id': 'active-image-preview', 'caller': 'workbench', 'expect': [called(set_ctx, "e.input.key == 'activeImagePreview' && e.input.value")]})
    MA = f'{MP}/mediaPreviewActions.ts'
    p.cmd(mc, 'imagePreview.copyImage', f'{MP}/mediaPreview.contribution.ts:249', f'{MA}:144-146', 'Copy the image of the active image preview to the clipboard.',
          [iff("!has(input.resource) || input.resource == ''", [ret({'copied': False})], title='No active image viewer', source=f'{MA}:52-60'),
           call(clip_img, {'resource': '= input.resource'}, title='viewer.copyImage()', source=f'{MA}:145'), ret({'copied': True})],
          request={'type': 'object', 'properties': {'resource': {'type': 'string', 'default': 'file:///work/app/logo.png'}}},
          scen=[{'expect': [called(clip_img)]}, {'id': 'copy-image-no-viewer', 'input': {'resource': ''}, 'expect': ['!' + called(clip_img)]}])
    p.cmd(mc, 'imagePreview.reopenAsText', f'{MP}/mediaPreview.contribution.ts:250', f'{MA}:166-168', 'Reopen an SVG image preview as text: Reopen Editor With the default text editor.',
          [call(exec_cmd, {'command_id': 'workbench.action.reopenWithEditor', 'args': ['default']}, as_='r', on_error='continue', source=f'{MA}:167'), ret({'reopened_with': 'default'})],
          scen=[{'expect': [called(exec_cmd, "e.input.command_id == 'workbench.action.reopenWithEditor' && e.input.args[0] == 'default'")]}])
    p.cmd(mc, 'imagePreview.reopenAsPreview', f'{MP}/mediaPreview.contribution.ts:251', f'{MA}:188-190', 'Reopen an SVG text editor as Image Preview.',
          [call(exec_cmd, {'command_id': 'workbench.action.reopenWithEditor', 'args': ['imagePreview.previewEditor']}, as_='r', on_error='continue', source=f'{MA}:189'), ret({'reopened_with': 'imagePreview.previewEditor'})],
          scen=[{'expect': [called(exec_cmd, "e.input.args[0] == 'imagePreview.previewEditor'")]}])

    # ---- edit sessions extras (registered only with a configured store) ----
    gate = lambda: iff("!state.actions_registered", [{'fail': {'code': 'command-not-found', 'message': 'command not registered: no editSessions.store in product.json'}}], title='Registered only when product.json configures editSessions.store', source=f'{EC}:169-179')
    on = {'edit-sessions-contribution@w1': {'actions_registered': True}}
    ecm = 'edit-sessions-contribution'
    p.cmd(ecm, 'workbench.editSessions.actions.showEditSessions', f'{EC}:315', f'{EC}:325-329', 'Show Cloud Changes: opens the Cloud Changes view.',
          [gate(), call(open_view, {'id': 'workbench.views.editSessions.data', 'focus': True}, source=f'{EC}:328'), ret({'shown': True})],
          errors=[{'code': 'command-not-found', 'status': 0, 'retryable': False}],
          scen=[{'state': on, 'config': CONFIGURED, 'expect': [called(open_view)]},
                {'id': 'show-edit-sessions-unconfigured', 'fails': True, 'expect': ["steps.s.result.error.code == 'command-not-found'"]}])
    p.cmd(ecm, 'workbench.editSessions.actions.showOutputChannel', f'{EC}:301', f'{EC}:306-309', 'Show Cloud Changes log (output channel).',
          [gate(), call(show_channel, {'id': 'editSessions', 'preserve_focus': True}, source=f'{EC}:308'), ret({'shown': True})],
          errors=[{'code': 'command-not-found', 'status': 0, 'retryable': False}],
          scen=[{'state': on, 'config': CONFIGURED, 'expect': [called(show_channel, "e.input.id == 'editSessions'")]}])
    evc = 'edit-sessions-views'
    p.cmd(evc, 'workbench.editSessions.actions.resume', f'{EV}:72', f'{EV}:86-91', 'Resume a stored change from the Cloud Changes view (forced apply of unrelated changes), then refresh.',
          [call('edit-sessions-contribution.resume-edit-session', {}, as_='r', title="executeCommand('workbench.editSessions.actions.resumeLatest', id, true)", source=f'{EV}:89'),
           ret('= vars.r.value')],
          scen=[{'state': on, 'config': CONFIGURED, 'pre': [{'interface': 'edit-sessions-contribution.cmd-workbench-edit-sessions-actions-store-current', 'caller': 'user', 'input': {}}],
                 'expect': ['steps.s.result.value.resumed', called('file-service.write-file')]}])
    p.cmd(evc, 'workbench.editSessions.actions.store', f'{EV}:94', f'{EV}:103-107', 'Store Working Changes from the view title, then refresh.',
          [call('edit-sessions-contribution.cmd-workbench-edit-sessions-actions-store-current', {}, as_='r', source=f'{EV}:105'), ret('= vars.r.value')],
          scen=[{'state': on, 'config': CONFIGURED, 'expect': ["'editSessions' in state['edit-sessions-store-client@w1'].resources"]}])
    p.cmd(evc, 'workbench.editSessions.actions.delete', f'{EV}:110', f'{EV}:124-139', 'Delete one stored change after confirmation ("You cannot undo this action.").',
          [call(confirm, {'message': "= 'Are you sure you want to permanently delete your working changes with ref ' + input.ref + '?'"}, as_='c', source=f'{EV}:128-133'),
           iff('!vars.c.value.confirmed', [ret({'deleted': False})], source=f'{EV}:134'),
           call('edit-sessions-workbench-service.delete', {'resource': 'editSessions', 'ref': '= input.ref'}, source=f'{EV}:135'), ret({'deleted': True})],
          request={'type': 'object', 'properties': {'ref': {'type': 'string', 'default': 'ref-1'}}},
          scen=[{'config': CONFIGURED, 'state': {'edit-sessions-store-client@w1': {'resources': {'editSessions': {'ref': 'ref-1', 'content': {'version': 2, 'folders': []}}}}},
                 'expect': ["!('editSessions' in state['edit-sessions-store-client@w1'].resources)"]},
                {'id': 'edit-session-delete-declined', 'config': CONFIGURED, 'choices': {'dialog-service.confirm.answer': 'cancel'}, 'expect': ['!' + called('edit-sessions-workbench-service.delete')]}])
    p.cmd(evc, 'workbench.editSessions.actions.deleteAll', f'{EV}:141', f'{EV}:154-167', 'Delete all stored changes from the cloud after confirmation.',
          [call(confirm, {'message': 'Are you sure you want to permanently delete all stored changes from the cloud?'}, as_='c', source=f'{EV}:157-162'),
           iff('!vars.c.value.confirmed', [ret({'deleted': False})], source=f'{EV}:163'),
           call('edit-sessions-workbench-service.delete', {'resource': 'editSessions', 'ref': None}, source=f'{EV}:164'), ret({'deleted': True})],
          scen=[{'config': CONFIGURED, 'state': {'edit-sessions-store-client@w1': {'resources': {'editSessions': {'ref': 'ref-1', 'content': {'version': 2, 'folders': []}}}}},
                 'expect': ["size(state['edit-sessions-store-client@w1'].resources) == 0"]}])
    esw = 'edit-sessions-workbench-service'
    p.cmd(esw, 'workbench.editSessions.actions.signIn', f'{ES}:464', f'{ES}:482-484', 'Turn on Cloud Changes...: initialize for write, which asks for an account when needed.',
          [call('edit-sessions-workbench-service.initialize', {'reason': 'write'}, as_='i', source=f'{ES}:483'), ret('= vars.i.value')],
          scen=[{'config': CONFIGURED, 'expect': ['steps.s.result.value.initialized', "state['edit-sessions-workbench-service@w1'].initialized"]}])
    p.cmd(esw, 'workbench.editSessions.actions.resetAuth', f'{ES}:499', f'{ES}:517-528', 'Turn off Cloud Changes: confirm, optionally delete all stored data, then forget the account preference.',
          [call(confirm, {'message': 'Do you want to disable storing working changes in the cloud?', 'checkbox': 'Delete all stored data from the cloud.'}, as_='c', source=f'{ES}:518-521'),
           iff('!vars.c.value.confirmed', [ret({'signed_out': False})], source=f'{ES}:522'),
           iff('vars.c.value.checkbox_checked', [call('edit-sessions-store-client.delete-resource', {'resource': 'editSessions'}, source=f'{ES}:524')], source=f'{ES}:523'),
           sets({'state.initialized': False}, title='clearAuthenticationPreference', source=f'{ES}:526'), ret({'signed_out': True})],
          scen=[{'config': CONFIGURED, 'state': {'edit-sessions-workbench-service@w1': {'initialized': True}}, 'expect': ["!state['edit-sessions-workbench-service@w1'].initialized"]}])
    return p

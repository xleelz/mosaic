from builder import Part, call, ret, iff, choice, sets, note, called, publish

CE = 'comments/browser/commentsEditorContribution.ts'
CC = 'comments/browser/commentsController.ts'
CS = 'comments/browser/commentService.ts'
CO = 'comments/browser/comments.contribution.ts'

SEED = {
    'commenting_enabled': True,
    'commenting_ranges': {'file:///work/app/src/main.ts': {'owner': 'githubpr', 'start_line': 1, 'end_line': 2}},
    'threads': {'t1': {'resource': 'file:///work/app/src/main.ts', 'line': 2, 'state': 'unresolved', 'comments': ['Should this log?'], 'expanded': False, 'owner': 'githubpr'}},
    'active_thread': 't1',
    'draft': '',
}


def build():
    p = Part('comments')
    ws = 'workbench-shell'
    notify = p.stub('notification-service.notify', ws)
    open_editor = p.stub('editor-service.open-editor', ws)
    exec_cmd = p.stub('command-service.execute-command', 'platform-core')
    set_ctx = p.stub('context-key-service.set-context', 'platform-core')
    show_activity = p.stub('activity-service.show-view-activity', ws, {'type': 'object', 'properties': {'view_id': {'type': 'string'}, 'badge': {'type': 'integer'}}})
    p.seed['comment-service'] = SEED
    cs = 'comment-service'
    p.iface(cs, 'enable-commenting', 'Sets commenting on or off; on a change updates the commentingEnabled context key and fires onDidChangeCommentingEnabled.',
            [f'{CS}:293-299'],
            [iff('input.enable == state.commenting_enabled', [ret({'changed': False})], source=f'{CS}:294'),
             sets({'state.commenting_enabled': '= input.enable'}, source=f'{CS}:295'),
             call(set_ctx, {'key': 'commentingEnabled', 'value': '= input.enable'}, source=f'{CS}:296'), ret({'changed': True})],
            request={'type': 'object', 'required': ['enable'], 'properties': {'enable': {'type': 'boolean'}}})
    p.iface(cs, 'is-commenting-enabled', 'isCommentingEnabled.', [f'{CS}:289-291'], [ret({'enabled': '= state.commenting_enabled'})])
    p.iface(cs, 'get-comment-threads', 'The comment threads known to the service (from all comment controllers); with a resource, only that document\'s threads, '
            'as getDocumentComments collects them per controller.', [f'{CS}:27', f'{CS}:465-490'],
            [iff("!has(input.resource) || input.resource == ''", [ret({'threads': '= state.threads'})], title='Every thread'),
             ret({'threads': '= state.threads.transformMap(k, v, v.resource == input.resource, v)'}, title='Threads of one document', source=f'{CS}:468-489')],
            request={'type': 'object', 'properties': {'resource': {'type': 'string'}}})

    # CommentController (editor contribution)
    ctl = p.comp('comment-controller', 'CommentController', 'comments-editor-contribution', [f'{CC}:453'],
                 'Per-editor comments controller: commenting range decorations, comment thread zone widgets, add/expand/collapse.')
    add = p.iface(ctl, 'add-or-toggle-comment-at-line', 'Existing threads at the line are expanded (or collapsed when all are expanded); otherwise a new empty thread is added if the line is in a commenting range, else an error notification.',
                  [f'{CC}:1152-1169', f'{CC}:1181-1200'],
                  [call('comment-service.get-comment-threads', {'resource': '= input.resource'}, as_='t', title='getCommentsAtLine: the threads of this document', source=f'{CC}:1158'),
                   sets({'vars.at': "= vars.t.value.threads.filter(k, vars.t.value.threads[k].resource == input.resource && vars.t.value.threads[k].line == input.line)"}),
                   iff('size(vars.at) > 0', [call('comment-service.set-thread-expanded', {'id': '= vars.at[0]', 'expanded': '= !vars.t.value.threads[vars.at[0]].expanded'}, source=f'{CC}:1159-1161'),
                                             ret({'toggled': '= vars.at[0]'})], title='Comments already at this line: toggle their widgets', source=f'{CC}:1158'),
                   call('comment-service.has-commenting-range', {'resource': '= input.resource', 'line': '= input.line'}, as_='r', title='getMatchedCommentAction(range)', source=f'{CC}:1182'),
                   iff('!vars.r.value.in_range', [call(notify, {'severity': 'error', 'message': 'The cursor must be within a commenting range to add a comment.'}, source=f'{CC}:1186-1187'),
                                                  ret({'added': None})], source=f'{CC}:1183'),
                   call('comment-service.create-pending-thread', {'resource': '= input.resource', 'line': '= input.line', 'owner': '= vars.r.value.owner'}, as_='n', title='Add an empty thread with the reply editor focused', source=f'{CC}:1205-1236'),
                   ret({'added': '= vars.n.value.id'})],
                  request={'type': 'object', 'properties': {'resource': {'type': 'string', 'default': 'file:///work/app/src/main.ts'}, 'line': {'type': 'integer', 'default': 1}}})
    p.iface(cs, 'has-commenting-range', 'Whether a comment controller offers a commenting range at the line.', [f'{CC}:1181-1183'],
            [sets({'vars.has': '= input.resource in state.commenting_ranges'}),
             ret({'in_range': '= vars.has && input.line >= state.commenting_ranges[input.resource].start_line && input.line <= state.commenting_ranges[input.resource].end_line',
                  'owner': "= vars.has ? state.commenting_ranges[input.resource].owner : ''"})],
            request={'type': 'object', 'properties': {'resource': {'type': 'string'}, 'line': {'type': 'integer'}}})
    p.iface(cs, 'create-pending-thread', 'A new, empty, expanded thread awaiting its first comment (the controller\'s pending thread).', [f'{CC}:1205-1236'],
            [sets({'vars.id': "= 'pending-' + string(size(state.threads) + 1)"}),
             sets({'state.threads': "= merge(state.threads, {vars.id: {'resource': input.resource, 'line': input.line, 'state': 'unresolved', 'comments': [], 'expanded': true, 'owner': input.owner}})",
                   'state.active_thread': '= vars.id'}),
             ret({'id': '= vars.id'})],
            request={'type': 'object', 'properties': {'resource': {'type': 'string'}, 'line': {'type': 'integer'}, 'owner': {'type': 'string'}}})
    p.iface(cs, 'set-thread-expanded', 'Expands or collapses a thread\'s widget.', [f'{CC}:1159-1161'],
            [sets({'state.threads': "= merge(state.threads, {input.id: merge(state.threads[input.id], {'expanded': input.expanded})})"}), ret({'expanded': '= input.expanded'})],
            request={'type': 'object', 'properties': {'id': {'type': 'string'}, 'expanded': {'type': 'boolean'}}})
    p.iface(ctl, 'constructor', 'Created per code editor after first render; tracks the model\'s commenting ranges and threads.', [f'{CE}:34', f'{CC}:453-520'],
            [call('comment-service.is-commenting-enabled', {}, as_='e'), ret({'commenting_enabled': '= vars.e.value.enabled'})])
    p.scenario_for('comment-controller.constructor', {'id': 'comment-controller-created', 'caller': 'editor', 'expect': ['steps.s.result.value.commenting_enabled', called('comment-service.is-commenting-enabled')]})

    ced = 'comments-editor-contribution'
    p.cmd(ced, 'workbench.action.toggleCommenting', f'{CE}:223', f'{CE}:241-245', 'Toggle Editor Commenting: flips CommentService commenting enablement.',
          [call('comment-service.is-commenting-enabled', {}, as_='e', source=f'{CE}:243'),
           call('comment-service.enable-commenting', {'enable': '= !vars.e.value.enabled'}, source=f'{CE}:244'), ret({'enabled': '= !vars.e.value.enabled'})],
          scen=[{'post': [{'interface': 'comment-service.is-commenting-enabled', 'caller': 'user', 'as': 'r'}],
                 'expect': ['!steps.r.result.value.enabled', "!state['comment-service@w1'].commenting_enabled"]}])
    p.cmd(ced, 'workbench.action.addComment', f'{CE}:248', f'{CE}:272-285', 'Add Comment on Current Selection: the controller adds (or toggles) a thread at the selection or the given range.',
          [call(add, {'resource': 'file:///work/app/src/main.ts', 'line': "= has(input.line) ? input.line : 1"}, as_='a', source=f'{CE}:284'), ret('= vars.a.value')],
          request={'type': 'object', 'properties': {'line': {'type': 'integer', 'default': 1}}},
          scen=[{'fixtures': ['editor-main-open', 'workbench-contribs-seed'], 'expect': ["steps.s.result.value.added == 'pending-2'", "state['comment-service@w1'].threads['pending-2'].expanded"]},
                {'id': 'add-comment-existing-thread', 'fixtures': ['editor-main-open', 'workbench-contribs-seed'], 'input': {'line': 2},
                 'expect': ["steps.s.result.value.toggled == 't1'", "state['comment-service@w1'].threads['t1'].expanded"]},
                {'id': 'add-comment-outside-range', 'fixtures': ['editor-main-open', 'workbench-contribs-seed'], 'input': {'line': 9},
                 'expect': ['steps.s.result.value.added == null', called(notify, "e.input.severity == 'error'")]}])
    submit = p.iface(cs, 'submit-active-comment', 'CommentReply.submitComment: runs the comment controller\'s default (primary) action with the thread and the reply text, then clears the pending comment.',
                     ['comments/browser/commentReply.ts:226-229'],
                     [iff("state.active_thread == '' || !(state.active_thread in state.threads)", [ret({'submitted': False})]),
                      call(exec_cmd, {'command_id': "= state.threads[state.active_thread].owner + '.createComment'", 'args': [{'thread': '= state.active_thread', 'text': '= input.text'}]},
                           title='triggerDefaultAction: the extension\'s comment command', source='comments/browser/commentReply.ts:227', on_error='continue'),
                      sets({'state.draft': ''}, source='comments/browser/commentReply.ts:228'), ret({'submitted': True, 'thread': '= state.active_thread'})],
                     request={'type': 'object', 'properties': {'text': {'type': 'string', 'default': 'Looks good'}}})
    p.cmd(ced, 'editor.action.submitComment', f'{CE}:416', f'{CE}:421-426', 'Ctrl+Enter in a comment editor: submit the comment of its parent thread.',
          [call(submit, {'text': "= has(input.text) ? input.text : 'Looks good'"}, as_='r', source=f'{CE}:424'), ret('= vars.r.value')],
          scen=[{'expect': ["steps.s.result.value.thread == 't1'", called(exec_cmd, "e.input.command_id == 'githubpr.createComment'")]}])
    p.cmd(ced, 'workbench.action.hideComment', f'{CE}:429', f'{CE}:435-466', 'Escape: collapse the comment thread being edited (or the last active comment\'s thread); error notification when there is none.',
          [note('enableKeybindingHoldMode, then collapse', source=f'{CE}:442'),
           call('comment-service.get-comment-threads', {}, as_='t'),
           call('comment-service.get-active-thread', {}, as_='a'),
           iff("vars.a.value.id == ''", [call(notify, {'severity': 'error', 'message': 'The cursor must be on a line with a comment to focus the comment'}, source=f'{CE}:462-465'), ret({'collapsed': None})]),
           call('comment-service.set-thread-expanded', {'id': '= vars.a.value.id', 'expanded': False}, source=f'{CE}:457'), ret({'collapsed': '= vars.a.value.id'})],
          scen=[{'state': {'comment-service@w1': {'threads': {'t1': {'expanded': True}}}}, 'expect': ["steps.s.result.value.collapsed == 't1'", "!state['comment-service@w1'].threads['t1'].expanded"]},
                {'id': 'hide-comment-none-active', 'state': {'comment-service@w1': {'active_thread': ''}}, 'expect': [called(notify)]}])
    p.iface(cs, 'get-active-thread', 'lastActiveCommentcontroller.activeComment\'s thread.', [f'{CS}:317-319'], [ret({'id': '= state.active_thread'})])
    p.cmd('comments-contribution', 'comments.reply', f'{CO}:76', f'{CO}:95-99', 'Reply from the Comments view: reveals the thread in its editor with the reply box focused.',
          [call(open_editor, {'resource': 'file:///work/app/src/main.ts', 'options': {'pinned': False, 'preserve_focus': False}}, title='revealCommentThread opens the resource at the thread range', source=f'{CC}:434-441'),
           call('comment-service.set-thread-expanded', {'id': "= has(input.thread) ? input.thread : 't1'", 'expanded': True}, title='controller.revealCommentThread(..., focusReply)', source=f'{CC}:442-445'),
           ret({'revealed': "= has(input.thread) ? input.thread : 't1'"})],
          request={'type': 'object', 'properties': {'thread': {'type': 'string', 'default': 't1'}}},
          scen=[{'expect': [called(open_editor, "e.input.resource == 'file:///work/app/src/main.ts'"), "state['comment-service@w1'].threads['t1'].expanded"]}])
    # UnresolvedCommentsBadge
    ucb = p.comp('unresolved-comments-badge', 'UnresolvedCommentsBadge', 'comments-contribution', [f'{CO}:154'],
                 'Shows the number of unresolved comment threads as a badge on the Comments view.', state={'schema': {'type': 'object'}, 'initial': {'total_unresolved': 0}})
    p.iface(ucb, 'on-all-comments-changed', 'Counts unresolved threads and updates the Comments view badge when the count changed.',
            [f'{CO}:200', f'{CO}:166-196'],
            [call('comment-service.get-comment-threads', {}, as_='t', source=f'{CO}:162'),
             sets({'vars.n': "= size(vars.t.value.threads.filter(k, vars.t.value.threads[k].state == 'unresolved'))"}, source=f'{CO}:168-173'),
             iff('vars.n == state.total_unresolved', [ret({'badge': '= vars.n', 'changed': False})], source=f'{CO}:190-192'),
             sets({'state.total_unresolved': '= vars.n'}, source=f'{CO}:194'),
             call(show_activity, {'view_id': 'workbench.panel.comments', 'badge': '= vars.n'}, source=f'{CO}:196'), ret({'badge': '= vars.n', 'changed': True})])
    p.scenario_for('unresolved-comments-badge.on-all-comments-changed', {'id': 'unresolved-badge', 'caller': 'workbench',
                                                                         'expect': ['steps.s.result.value.badge == 1', called(show_activity, 'e.input.badge == 1'), "state['unresolved-comments-badge@w1'].total_unresolved == 1"]})
    return p

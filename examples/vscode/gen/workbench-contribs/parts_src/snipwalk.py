from builder import Part, call, ret, iff, choice, sets, note, called, foreach

SN = 'snippets/browser'
GS = 'welcomeGettingStarted/browser/gettingStarted.contribution.ts'
GSS = 'welcomeGettingStarted/browser/gettingStartedService.ts'


def build():
    p = Part('snipwalk')
    ws = 'workbench-shell'
    insert = p.stub('snippet-controller2.insert', 'editor')
    apply_snip = p.stub('snippet-controller2.apply', 'editor', {'type': 'object', 'properties': {'uri': {'type': 'string'}, 'edits': {'type': 'array'}}})
    clip_read = p.stub('clipboard-service.read-text', ws, response={'type': 'object', 'properties': {'text': {'type': 'string', 'examples': ['copied text']}}})
    open_editor = p.stub('editor-service.open-editor', ws)
    store = p.stub('storage-service.store', 'platform-core')
    exec_cmd = p.stub('command-service.execute-command', 'platform-core')
    set_ctx = p.stub('context-key-service.set-context', 'platform-core')
    write_file = p.stub('text-file-service.write', 'files-search-scm', {'type': 'object', 'properties': {'resource': {'type': 'string'}, 'value': {'type': 'string'}}})
    get_snips = 'snippets-service.get-snippets'
    usage = 'snippets-service.update-usage-timestamp'
    ed = ['editor-main-open', 'workbench-contribs-seed']

    # _snippet.markAsUsed
    p.cmd('snippets-snippet-completion-provider', '_snippet.markAsUsed', f'{SN}/snippetCompletionProvider.ts:27', f'{SN}/snippetCompletionProvider.ts:27-33',
          'Run when a snippet completion is accepted: records the snippet\'s usage so it sorts first next time.',
          [iff('!has(input.snippet_id)', [ret({'marked': False})], title='Only Snippet arguments count', source=f'{SN}/snippetCompletionProvider.ts:30'),
           call(usage, {'id': '= input.snippet_id'}, source=f'{SN}/snippetCompletionProvider.ts:31'), ret({'marked': True})],
          request={'type': 'object', 'properties': {'snippet_id': {'type': 'string', 'default': 'vscode.typescript-basics/For Loop'}}},
          scen=[{'post': [{'interface': get_snips, 'caller': 'editor', 'input': {'language_id': 'typescript'}, 'as': 'r'}],
                 'expect': ["steps.r.result.value.snippets.exists(x, x.name == 'For Loop' && x.last_used > 0)"]}])
    # Surround with snippet
    p.cmd('snippets-contribution', 'editor.action.surroundWithSnippet', f'{SN}/snippets.contribution.ts:28', f'{SN}/commands/surroundWithSnippet.ts:48-77',
          'Surround with Snippet: pick among the language\'s snippets that use the selection, insert it, record usage.',
          [call(get_snips, {'language_id': 'typescript', 'include_no_prefix_snippets': True}, as_='all', title='getSurroundableSnippets: snippets of the language at the cursor that use $TM_SELECTED_TEXT', source=f'{SN}/commands/surroundWithSnippet.ts:20-28'),
           sets({'vars.cands': '= vars.all.value.snippets.filter(s, has(s.uses_selection) && s.uses_selection)'}),
           iff('size(vars.cands) == 0', [ret({'inserted': False})], source=f'{SN}/commands/surroundWithSnippet.ts:59-61'),
           choice('pick', 'first', {'first': [], 'dismissed': [ret({'inserted': False})]}, source=f'{SN}/commands/surroundWithSnippet.ts:63-66'),
           call(insert, {'uri': 'file:///work/app/src/main.ts', 'template': '= vars.cands[0].body'}, source=f'{SN}/commands/surroundWithSnippet.ts:73'),
           call(usage, {'id': '= vars.cands[0].id'}, source=f'{SN}/commands/surroundWithSnippet.ts:74'), ret({'inserted': True, 'id': '= vars.cands[0].id'})],
          scen=[{'fixtures': ed, 'expect': ["steps.s.result.value.id == 'vscode.typescript-basics/For Loop'", called(insert, "e.input.template.contains('TM_SELECTED_TEXT')")]},
                {'id': 'surround-dismissed', 'fixtures': ed, 'choices': {'snippets-contribution.cmd-editor-action-surroundwithsnippet.pick': 'dismissed'}, 'expect': ['!' + called(insert)]}])
    # Fill file with snippet
    p.cmd('snippets-contribution', 'workbench.action.populateFileFromSnippet', f'{SN}/snippets.contribution.ts:29', f'{SN}/commands/fileTemplateSnippets.ts:31-63',
          'Fill File with Snippet: pick a file-template snippet, set the model language, replace the whole file with it.',
          [call(get_snips, {'language_id': 'typescript', 'include_no_prefix_snippets': True}, as_='all', source=f'{SN}/commands/fileTemplateSnippets.ts:43'),
           sets({'vars.cands': '= vars.all.value.snippets.filter(s, has(s.is_file_template) && s.is_file_template)'}),
           iff('size(vars.cands) == 0', [ret({'applied': False})], source=f'{SN}/commands/fileTemplateSnippets.ts:44-46'),
           choice('pick', 'first', {'first': [], 'dismissed': [ret({'applied': False})]}, source=f'{SN}/commands/fileTemplateSnippets.ts:48-51'),
           call(apply_snip, {'uri': 'file:///work/app/src/main.ts', 'edits': [{'range': 'full', 'template': '= vars.cands[0].body'}]}, title='Replace the full model range with the template', source=f'{SN}/commands/fileTemplateSnippets.ts:54-61'),
           ret({'applied': True, 'id': '= vars.cands[0].id'})],
          scen=[{'fixtures': ed, 'expect': ["steps.s.result.value.id == 'vscode.typescript-basics/Class Definition'", called(apply_snip)]},
                {'id': 'populate-file-no-templates', 'fixtures': ed, 'state': {'snippets-service@w1': {'snippets': {'typescript': []}}}, 'expect': ['!steps.s.result.value.applied', '!' + called(apply_snip)]}])
    # Configure snippets
    CS = f'{SN}/commands/configureSnippets.ts'
    p.cmd('snippets-contribution', 'workbench.action.openSnippets', f'{SN}/snippets.contribution.ts:30', f'{CS}:287-341',
          'Configure Snippets: pick an existing snippet file, a new global/folder .code-snippets file, or a language file; new files are written with a commented template, then opened.',
          [choice('pick', 'language', {
              'existing': [call(open_editor, {'resource': 'vscode-userdata:/User/snippets/typescript.json'}, source=f'{CS}:338'), ret({'opened': 'existing'})],
              'new-global': [call(write_file, {'resource': 'vscode-userdata:/User/snippets/my.code-snippets', 'value': '{\n\t// Place your global snippets here.\n}', 'etag': '', 'mtime': 0}, title='createSnippetFile writes a commented template', source=f'{CS}:169-233'),
                             call(open_editor, {'resource': 'vscode-userdata:/User/snippets/my.code-snippets'}, source=f'{CS}:233'), ret({'opened': 'new-global'})],
              'new-folder': [call(write_file, {'resource': 'file:///work/app/.vscode/app.code-snippets', 'value': '{\n\t// Place your app workspace snippets here.\n}', 'etag': '', 'mtime': 0}, source=f'{CS}:316'),
                             call(open_editor, {'resource': 'file:///work/app/.vscode/app.code-snippets'}), ret({'opened': 'new-folder'})],
              'language': [call(write_file, {'resource': 'vscode-userdata:/User/snippets/typescript.json', 'value': '{\n\t// Place your snippets for typescript here.\n}', 'etag': '', 'mtime': 0}, title='createLanguageSnippetFile writes <lang>.json', source=f'{CS}:237-267'),
                           call(open_editor, {'resource': 'vscode-userdata:/User/snippets/typescript.json'}, source=f'{CS}:338'), ret({'opened': 'language'})],
              'dismissed': [ret({'opened': 'none'})]}, title='Select Snippets File or Create Snippets', source=f'{CS}:326-339')],
          scen=[{'expect': [called(write_file, "e.input.resource.endsWith('typescript.json')"), called(open_editor)]},
                {'id': 'open-snippets-new-folder', 'choices': {'snippets-contribution.cmd-workbench-action-opensnippets.pick': 'new-folder'}, 'expect': [called(write_file, "e.input.resource == 'file:///work/app/.vscode/app.code-snippets'")]},
                {'id': 'open-snippets-dismissed', 'choices': {'snippets-contribution.cmd-workbench-action-opensnippets.pick': 'dismissed'}, 'expect': ['!' + called(open_editor)]}])
    # Tab completion
    TC = f'{SN}/tabCompletion.ts'
    tcc = p.comp('tab-completion-controller', 'TabCompletionController', 'snippets-tab-completion', [f'{TC}:27'],
                 'Editor contribution: with editor.tabCompletion on, Tab inserts the snippet whose prefix matches the word before the cursor.')
    perf = p.iface(tcc, 'perform-snippet-completions', 'One matching snippet is inserted directly (replacing the prefix); several open the suggest widget restricted to them.',
                   [f'{TC}:157-190'],
                   [call(get_snips, {'language_id': 'typescript'}, as_='all', title='_activeSnippets: snippets whose prefix matches the word left of the cursor', source=f'{TC}:81-121'),
                    sets({'vars.active': '= vars.all.value.snippets.filter(s, s.prefix == input.word)'}),
                    iff('size(vars.active) == 1', [call(insert, {'uri': 'file:///work/app/src/main.ts', 'template': '= vars.active[0].body'}, source=f'{TC}:162-181'), ret({'inserted': '= vars.active[0].id'})], source=f'{TC}:162'),
                    iff('size(vars.active) > 1', [ret({'suggest': '= size(vars.active)'})], title='Several: show them in the suggest widget', source=f'{TC}:182-189'),
                    ret({'inserted': None})],
                   request={'type': 'object', 'properties': {'word': {'type': 'string', 'default': 'for'}}})
    p.cmd('snippets-tab-completion', 'insertSnippet', f'{TC}:195', f'{TC}:195-198', 'Tab (when a snippet prefix is before the cursor and editor.tabCompletion is on): performSnippetCompletions.',
          [call(perf, {'word': "= has(input.word) ? input.word : 'for'"}, as_='r', source=f'{TC}:198'), ret('= vars.r.value')],
          request={'type': 'object', 'properties': {'word': {'type': 'string', 'default': 'for'}}},
          scen=[{'fixtures': ed, 'expect': ["steps.s.result.value.inserted == 'vscode.typescript-basics/For Loop'", called(insert)]},
                {'id': 'tab-completion-no-match', 'fixtures': ed, 'input': {'word': 'xyz'}, 'expect': ['steps.s.result.value.inserted == null', '!' + called(insert)]}])

    # --- walkthroughs ---
    gsc = 'getting-started-commands'
    open_wt = p.cmd(gsc, 'workbench.action.openWalkthrough', f'{GS}:40', f'{GS}:58-110',
                    'Open Walkthrough: opens the Welcome editor on a walkthrough (and step), reveals the step when it is already open, or opens the Welcome page.',
                    [sets({'vars.id': "= has(input.walkthrough_id) ? input.walkthrough_id : (has(input.args) && size(input.args) > 0 ? input.args[0] : '')"}),
                     iff("vars.id == '' && config['workbench-startup-editor'] == 'agentSessionsWelcomePage'",
                         [call(exec_cmd, {'command_id': 'workbench.action.openAgentSessionsWelcome', 'args': []}, source=f'{GS}:73-75'), ret({'opened': 'agent-sessions-welcome'})], source=f'{GS}:73'),
                     iff("vars.id != '' && has(input.step) && has(state.open_category) && state.open_category == vars.id",
                         [call(exec_cmd, {'command_id': 'walkthroughs.selectStep', 'args': ["= vars.id + '#' + input.step"]}, source=f'{GS}:87-90'), ret({'opened': 'step-revealed'})],
                         title='Walkthrough already open: just reveal the step', source=f'{GS}:87'),
                     call(open_editor, {'resource': 'walkThrough://vscode_getting_started_page', 'options': {'preserve_focus': False}}, source=f'{GS}:100-108'),
                     sets({'state.open_category': '= vars.id'}),
                     ret({'opened': "= vars.id == '' ? 'welcome' : 'walkthrough'"})],
                    request={'type': 'object', 'properties': {'walkthrough_id': {'type': 'string', 'default': 'Setup'}}},
                    scen=[{'expect': ["steps.s.result.value.opened == 'walkthrough'", called(open_editor, "e.input.resource == 'walkThrough://vscode_getting_started_page'"), "state['getting-started-commands@w1'].open_category == 'Setup'"]},
                          {'id': 'open-walkthrough-welcome', 'input': {'walkthrough_id': ''}, 'expect': ["steps.s.result.value.opened == 'welcome'"]}])
    p.cmd(gsc, 'welcome.showAllWalkthroughs', f'{GS}:200', f'{GS}:229-258', 'Open Walkthrough...: quick pick of the registered walkthroughs; accepting runs workbench.action.openWalkthrough.',
          [call('walkthroughs-service.get-walkthroughs', {}, as_='w', source=f'{GS}:215-226'),
           choice('pick', 'first', {'first': [], 'dismissed': [ret({'picked': None})]}, source=f'{GS}:245-250'),
           call(open_wt, {'walkthrough_id': '= vars.w.value.steps[0].walkthrough'}, title="executeCommand('workbench.action.openWalkthrough', selection.id)", source=f'{GS}:248'),
           ret({'picked': '= vars.w.value.steps[0].walkthrough'})],
          scen=[{'expect': ["steps.s.result.value.picked == 'Setup'", called(open_editor)]},
                {'id': 'show-all-walkthroughs-dismissed', 'choices': {'getting-started-commands.cmd-welcome-showallwalkthroughs.pick': 'dismissed'}, 'expect': ['!' + called(open_editor)]}])
    p.cmd(gsc, 'welcome.newWorkspaceChat', f'{GS}:262', f'{GS}:262-268', 'Opens agent chat pre-filled with "#new " to create a new workspace.',
          [call(exec_cmd, {'command_id': 'workbench.action.chat.open', 'args': [{'mode': 'agent', 'query': '#new ', 'isPartialQuery': True}]}, source=f'{GS}:266', title='Not awaited: a failure is not reported to the caller', on_error='continue'), ret({'ran': True})],
          scen=[{'expect': [called(exec_cmd, "e.input.command_id == 'workbench.action.chat.open'")]}])
    p.cmd('walkthroughs-service', 'resetGettingStartedProgress', f'{GSS}:728', f'{GSS}:740-768',
          'Developer: Reset Welcome Page Walkthrough Progress: clears hidden categories and walkthrough metadata, deprogresses every recorded step.',
          [call(store, {'key': 'workbench.welcomePage.hiddenCategories', 'value': '[]', 'scope': 'profile', 'target': 'user'}, source=f'{GSS}:745-749'),
           call(store, {'key': 'workbench.welcomePage.walkthroughMetadata', 'value': '[]', 'scope': 'profile', 'target': 'user'}, source=f'{GSS}:750-754'),
           foreach('= state.progress', 'step', [call('walkthroughs-service.deprogress-step', {'id': '= vars.index'}, source=f'{GSS}:759-762')]),
           ret({'reset': True})],
          scen=[{'pre': [{'interface': 'getting-started-commands.cmd-welcome-mark-step-complete', 'caller': 'user', 'input': {'arg': 'pickColorTheme'}}],
                 'post': [{'interface': 'walkthroughs-service.get-walkthroughs', 'caller': 'workbench', 'as': 'r'}],
                 'expect': ["steps.r.result.value.steps.all(s, !s.done)", "size(state['walkthroughs-service@w1'].progress) == 0"]}])
    wpc = p.comp('workspace-platform-contribution', 'WorkspacePlatformContribution', gsc, [f'{GS}:271'],
                 'Sets the workspacePlatform context key (mac/linux/windows/webworker) from the remote OS or the local platform.')
    p.iface(wpc, 'constructor', 'Sets workspacePlatform from the remote environment\'s OS, else the local platform (webworker on web).',
            [f'{GS}:355', f'{GS}:276-300'],
            [iff("has(input.remote_os) && input.remote_os != ''", [call(set_ctx, {'key': 'workspacePlatform', 'value': '= input.remote_os'}, source=f'{GS}:289'), ret({'platform': '= input.remote_os'})]),
             call(set_ctx, {'key': 'workspacePlatform', 'value': 'linux'}, title='Local extension management server: the local OS', source=f'{GS}:291-299'), ret({'platform': 'linux'})],
            request={'type': 'object', 'properties': {'remote_os': {'type': 'string', 'default': ''}}})
    p.scenario_for('workspace-platform-contribution.constructor', {'id': 'workspace-platform-local', 'caller': 'workbench', 'expect': [called(set_ctx, "e.input.key == 'workspacePlatform' && e.input.value == 'linux'")]})
    p.scenario_for('workspace-platform-contribution.constructor', {'id': 'workspace-platform-remote', 'caller': 'workbench', 'input': {'remote_os': 'windows'}, 'expect': [called(set_ctx, "e.input.value == 'windows'")]})
    p.seed[gsc] = {'open_category': ''}
    return p

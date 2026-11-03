from builder import Part, call, ret, iff, choice, sets, note, called, fail, foreach, publish

LH = 'localHistory/browser/localHistoryCommands.ts'
LHN = 'localHistory/electron-browser/localHistoryCommands.ts'
TS = 'timeline/common/timelineService.ts'
TP = 'timeline/browser/timelinePane.ts'

ENTRY = {'id': 'Ab12.ts', 'resource': 'file:///work/app/src/main.ts', 'name': 'main.ts',
         'location': 'file:///user/History/-7f3a1c/Ab12.ts', 'source': 'workbench.action.files.save', 'timestamp': 1793318300000}
ENTRY2 = {'id': 'Cd34.ts', 'resource': 'file:///work/app/src/main.ts', 'name': 'main.ts',
          'location': 'file:///user/History/-7f3a1c/Cd34.ts', 'source': 'workbench.action.files.save', 'timestamp': 1793318350000}


def build():
    p = Part('history')
    fs, ws = 'files-search-scm', 'workbench-shell'
    get_entries = p.stub('working-copy-history-service.get-entries', fs,
                         {'type': 'object', 'required': ['resource'], 'properties': {'resource': {'type': 'string'}}},
                         {'type': 'object', 'properties': {'entries': {'type': 'array', 'items': {'type': 'object'}, 'examples': [[ENTRY, ENTRY2]]}}})
    add_entry = p.stub('working-copy-history-service.add-entry', fs, {'type': 'object', 'properties': {'resource': {'type': 'string'}, 'source': {'type': 'string'}}})
    remove_entry = p.stub('working-copy-history-service.remove-entry', fs, {'type': 'object', 'properties': {'id': {'type': 'string'}, 'resource': {'type': 'string'}}})
    remove_all = p.stub('working-copy-history-service.remove-all', fs)
    update_entry = p.stub('working-copy-history-service.update-entry', fs, {'type': 'object', 'properties': {'id': {'type': 'string'}, 'resource': {'type': 'string'}, 'source': {'type': 'string'}}})
    clone = p.stub('file-service.clone-file', 'platform-core', {'type': 'object', 'properties': {'source': {'type': 'string'}, 'target': {'type': 'string'}}})
    confirm = p.stub('dialog-service.confirm', ws)
    dlg_error = p.stub('dialog-service.error', ws, {'type': 'object', 'properties': {'message': {'type': 'string'}, 'detail': {'type': 'string'}}})
    open_editor = p.stub('editor-service.open-editor', ws)
    close_editor = p.stub('editor-service.close-editor', ws)
    show_in_folder = p.stub('native-host-service.show-item-in-folder', ws, {'type': 'object', 'properties': {'path': {'type': 'string'}}})
    set_ctx = p.stub('context-key-service.set-context', 'platform-core')
    open_view = p.stub('views-service.open-view', ws, {'type': 'object', 'properties': {'id': {'type': 'string'}, 'focus': {'type': 'boolean'}}})
    store = p.stub('storage-service.store', 'platform-core')

    lhc = 'local-history-commands'
    # findLocalHistoryEntry helper
    find = p.iface(lhc, 'find-local-history-entry', 'Finds the entry (and its previous one) of a timeline item by handle among the working copy history entries of the resource.',
                   [f'{LH}:693-712'],
                   [call(get_entries, {'resource': '= input.uri'}, as_='list', source=f'{LH}:703'),
                    sets({'vars.idx': "= vars.list.value.entries.transformList(i, e, e.id == input.handle ? i : -1).filter(i, i >= 0)"}, source=f'{LH}:705-712'),
                    iff('size(vars.idx) == 0', [ret({'found': False})], title='No entry with that handle'),
                    ret({'found': True, 'entry': '= vars.list.value.entries[vars.idx[0]]',
                         'previous': '= vars.idx[0] > 0 ? vars.list.value.entries[vars.idx[0] - 1] : null'})],
                   request={'type': 'object', 'required': ['uri', 'handle'], 'properties': {'uri': {'type': 'string'}, 'handle': {'type': 'string'}}})
    item = {'type': 'object', 'properties': {'uri': {'type': 'string', 'default': 'file:///work/app/src/main.ts'}, 'handle': {'type': 'string', 'default': 'Cd34.ts'}}}
    find_step = lambda line: call(find, {'uri': '= input.uri', 'handle': '= input.handle'}, as_='f', source=f'{LH}:{line}')
    not_found = iff('!vars.f.value.found', [ret({'done': False})])
    unknown = {'id': None, 'input': {'handle': 'gone.ts'}}

    # restore
    restore = p.iface(lhc, 'restore', 'Restore Contents: confirm, soft-revert dirty working copies, copy the history entry over the file, force revert, open it, record a "restored" entry, close the history editor.',
                      [f'{LH}:257-323'],
                      [find_step(262), not_found,
                       call(confirm, {'message': "= 'Do you want to restore the contents of \\'' + vars.f.value.entry.name + '\\'?'", 'primary_button': '&&Restore'}, as_='c',
                            title='Restoring will discard any unsaved changes', source=f'{LH}:268-275'),
                       iff('!vars.c.value.confirmed', [ret({'done': False, 'confirmed': False})], source=f'{LH}:275'),
                       call(clone, {'source': '= vars.f.value.entry.location', 'target': '= vars.f.value.entry.resource'}, as_='cl', on_error='continue', source=f'{LH}:291'),
                       iff('!vars.cl.ok', [call(dlg_error, {'message': "= 'Unable to restore \\'' + vars.f.value.entry.name + '\\'.'", 'detail': '= vars.cl.error.message'}, source=f'{LH}:299'),
                                          ret({'done': False, 'error': '= vars.cl.error.code'})]),
                       call(open_editor, {'resource': '= vars.f.value.entry.resource'}, source=f'{LH}:312'),
                       call(add_entry, {'resource': '= vars.f.value.entry.resource', 'source': 'restore'}, title='Add a "Restored" entry so the restore can be undone', source=f'{LH}:315-318'),
                       call(close_editor, {'resource': "= 'vscode-local-history:' + vars.f.value.entry.location"}, source=f'{LH}:321'),
                       ret({'done': True})], request=item)
    p.cmd(lhc, 'workbench.action.localHistory.restore', f'{LH}:237', f'{LH}:250-255', 'Restore Contents from the Timeline item context menu.',
          [call(restore, {'uri': '= has(input.uri) ? input.uri : \'file:///work/app/src/main.ts\'', 'handle': "= has(input.handle) ? input.handle : 'Cd34.ts'"}, as_='r', source=f'{LH}:254'), ret('= vars.r.value')],
          request=item,
          scen=[{'fixtures': ['dirty-editor', 'workbench-contribs-seed'], 'expect': ['steps.s.result.value.done', called(clone, "e.input.target == 'file:///work/app/src/main.ts'"), called(add_entry, "e.input.source == 'restore'")]},
                {'id': 'restore-declined', 'choices': {'dialog-service.confirm.answer': 'cancel'}, 'expect': ['!steps.s.result.value.done', '!' + called(clone)]},
                {'id': 'restore-unknown-entry', 'input': {'handle': 'gone.ts'}, 'expect': ['!steps.s.result.value.done', '!' + called(confirm)]},
                {'id': 'restore-clone-fails', 'expect': ['!steps.s.result.value.done', called(dlg_error)],
                 }])
    # patch the last scenario with a fault
    p.scenarios[-1].pop('faults', None)
    p.scenarios[-1]['faults'] = [{'target': clone, 'type': 'error', 'code': 'file-not-found', 'message': 'entry location missing'}]
    p.cmd(lhc, 'workbench.action.localHistory.restoreViaEditor', f'{LH}:216', f'{LH}:230-235', 'Restore Contents from the title of a local history editor: maps the vscode-local-history URI back to resource and handle.',
          [call(restore, {'uri': 'file:///work/app/src/main.ts', 'handle': "= input.uri.split('/')[size(input.uri.split('/')) - 1]"}, as_='r', title='fromLocalHistoryFileSystem(uri)', source=f'{LH}:231-233'),
           ret('= vars.r.value')],
          request={'type': 'object', 'properties': {'uri': {'type': 'string', 'default': 'vscode-local-history:/user/History/-7f3a1c/Cd34.ts'}}},
          scen=[{'expect': [called(clone, "e.input.source == 'file:///user/History/-7f3a1c/Cd34.ts'")]}])
    p.cmd(lhc, 'workbench.action.localHistory.open', f'{LH}:188', f'{LH}:201-209', 'Show Contents: opens the history entry in an editor (vscode-local-history scheme).',
          [find_step(205), not_found,
           call(open_editor, {'resource': "= 'vscode-local-history:' + vars.f.value.entry.location"}, source=f'{LH}:640-644'), ret({'done': True})], request=item,
          scen=[{'expect': [called(open_editor, "e.input.resource == 'vscode-local-history:file:///user/History/-7f3a1c/Cd34.ts'")]},
                {'id': 'open-unknown-entry', 'input': {'handle': 'gone.ts'}, 'expect': ['!' + called(open_editor)]}])
    p.iface(lhc, 'get-selected-for-compare', 'The item selected for compare (module variable itemSelectedForCompare), resolved as Compare with Selected does: nothing when no item was selected or its history entry is gone.',
            [f'{LH}:122', f'{LH}:166-175'],
            [iff('!has(state.selected)', [ret({'item': None})], title='Nothing selected for compare', source=f'{LH}:168-170'),
             call(find, {'uri': '= state.selected.uri', 'handle': '= state.selected.handle'}, as_='f', title='findLocalHistoryEntry(itemSelectedForCompare)', source=f'{LH}:172'),
             iff('!vars.f.value.found', [ret({'item': None})], title='The selected entry was deleted meanwhile', source=f'{LH}:173-175'),
             ret({'item': '= state.selected', 'entry': '= vars.f.value.entry'})])
    p.cmd(lhc, 'workbench.action.localHistory.selectForCompare', f'{LH}:126', f'{LH}:139-147', 'Select for Compare: remembers the item and sets the localHistoryItemSelectedForCompare context key.',
          [find_step(143), not_found,
           sets({'state.selected': {'uri': '= input.uri', 'handle': '= input.handle'}}, source=f'{LH}:145'),
           call(set_ctx, {'key': 'localHistoryItemSelectedForCompare', 'value': True}, source=f'{LH}:146'), ret({'done': True})], request=item,
          scen=[{'post': [{'interface': 'local-history-commands.get-selected-for-compare', 'caller': 'user', 'as': 'r'}],
                 'expect': ["steps.r.result.value.item.handle == 'Cd34.ts'", "state['local-history-commands@w1'].selected.handle == 'Cd34.ts'"]}])
    p.cmd(lhc, 'workbench.action.localHistory.rename', f'{LH}:444', f'{LH}:457-503', 'Rename: a new label for the entry (inline in the Timeline or via an input box); empty names are ignored.',
          [find_step(463), not_found,
           choice('name', 'typed', {'typed': [sets({'vars.name': 'before refactor'})], 'empty': [sets({'vars.name': ''})]}, title='Input box value', source=f'{LH}:470-500'),
           iff("vars.name == ''", [ret({'done': False})], source=f'{LH}:466'),
           call(update_entry, {'id': '= vars.f.value.entry.id', 'resource': '= vars.f.value.entry.resource', 'source': '= vars.name'}, source=f'{LH}:467'), ret({'done': True})], request=item,
          scen=[{'expect': [called(update_entry, "e.input.source == 'before refactor'")]},
                {'id': 'rename-empty', 'choices': {'local-history-commands.cmd-workbench-action-localhistory-rename.name': 'empty'}, 'expect': ['!' + called(update_entry)]}])
    p.cmd(lhc, 'workbench.action.localHistory.delete', f'{LH}:506', f'{LH}:519-553', 'Delete: confirm ("This action is irreversible!"), remove the entry and close its editor.',
          [find_step(523), not_found,
           call(confirm, {'message': "= 'Do you want to delete the local history entry of \\'' + vars.f.value.entry.name + '\\'?'", 'primary_button': '&&Delete'}, as_='c', source=f'{LH}:531-540'),
           iff('!vars.c.value.confirmed', [ret({'done': False})], source=f'{LH}:540-542'),
           call(remove_entry, {'id': '= vars.f.value.entry.id', 'resource': '= vars.f.value.entry.resource'}, source=f'{LH}:547'),
           call(close_editor, {'resource': "= 'vscode-local-history:' + vars.f.value.entry.location"}, source=f'{LH}:550'), ret({'done': True})], request=item,
          scen=[{'expect': [called(remove_entry, "e.input.id == 'Cd34.ts'")]},
                {'id': 'delete-declined', 'choices': {'dialog-service.confirm.answer': 'cancel'}, 'expect': ['!' + called(remove_entry)]}])
    p.cmd(lhc, 'workbench.action.localHistory.deleteAll', f'{LH}:559', f'{LH}:569-590', 'Delete All: confirm, then remove every local history entry.',
          [call(confirm, {'message': 'Do you want to delete all entries of all files in local history?', 'primary_button': '&&Delete All'}, as_='c', source=f'{LH}:574-583'),
           iff('!vars.c.value.confirmed', [ret({'done': False})], source=f'{LH}:583-585'),
           call(remove_all, {}, source=f'{LH}:586'), ret({'done': True})],
          scen=[{'expect': [called(remove_all)]},
                {'id': 'delete-all-declined', 'choices': {'dialog-service.confirm.answer': 'cancel'}, 'expect': ['!' + called(remove_all)]}])
    p.cmd(lhc, 'workbench.action.localHistory.create', f'{LH}:594', f'{LH}:604-631', 'Create Entry: for the active file (file or vscode-userdata scheme), an input box names a new history entry.',
          [iff("!(input.resource.startsWith('file:') || input.resource.startsWith('vscode-userdata:'))", [ret({'done': False})], title='Only for the default and user data schemes', source=f'{LH}:612-614'),
           choice('name', 'typed', {'typed': [sets({'vars.name': 'checkpoint'})], 'empty': [sets({'vars.name': ''})]}, source=f'{LH}:616-623'),
           iff("vars.name == ''", [ret({'done': False})], source=f'{LH}:626'),
           call(add_entry, {'resource': '= input.resource', 'source': '= vars.name'}, source=f'{LH}:627'), ret({'done': True})],
          request={'type': 'object', 'properties': {'resource': {'type': 'string', 'default': 'file:///work/app/src/main.ts'}}},
          scen=[{'expect': [called(add_entry, "e.input.source == 'checkpoint'")]},
                {'id': 'create-untitled', 'input': {'resource': 'untitled:Untitled-1'}, 'expect': ['!' + called(add_entry)]}])
    p.cmd('local-history-commands-native', 'workbench.action.localHistory.revealInOS', f'{LHN}:20', f'{LHN}:33-41', 'Reveal in File Explorer / Finder: shows the history entry file in the OS file manager.',
          [call(find, {'uri': '= input.uri', 'handle': '= input.handle'}, as_='f', source=f'{LHN}:37'), not_found,
           call(show_in_folder, {'path': "= vars.f.value.entry.location.replace('file://', '')"}, source=f'{LHN}:39'), ret({'done': True})], request=item,
          scen=[{'expect': [called(show_in_folder, "e.input.path == '/user/History/-7f3a1c/Cd34.ts'")]}])

    # --- Timeline service (my area) ---
    tsc = 'timeline-service'
    p.seed[tsc] = {'providers': {}, 'workspace_providers': {}}
    reg = p.iface(tsc, 'register-timeline-provider', 'Registers (or overwrites) a provider by id, updates the timelineHasProvider context and fires onDidChangeProviders.',
                  [f'{TS}:121-153'],
                  [sets({'state.providers': "= merge(has(state.providers) ? state.providers : {}, {input.id: {'id': input.id, 'label': input.label}})"}, source=f'{TS}:136'),
                   call(set_ctx, {'key': 'timelineHasProvider', 'value': True}, source=f'{TS}:138'),
                   ret({'registered': '= input.id'})],
                  request={'type': 'object', 'required': ['id'], 'properties': {'id': {'type': 'string', 'default': 'timeline.localHistory'}, 'label': {'type': 'string', 'default': 'Local History'}}})
    unreg = p.iface(tsc, 'unregister-timeline-provider', 'Unregisters a provider; unknown ids are ignored.', [f'{TS}:155-165'],
                    [iff("!has(state.providers) || !(input.id in state.providers)", [ret({'removed': False})], source=f'{TS}:158-160'),
                     sets({'state.providers': '= omit(state.providers, input.id)'}, source=f'{TS}:162'), ret({'removed': True})],
                    request={'type': 'object', 'required': ['id'], 'properties': {'id': {'type': 'string', 'default': 'timeline.localHistory'}}})
    sources = p.iface(tsc, 'get-sources', 'Distinct {id, label} of the registered providers.', [f'{TS}:61-69'],
                      [ret({'sources': "= has(state.providers) ? state.providers.transformList(k, v, {'id': k, 'label': v.label}) : []"})])
    set_uri = p.iface(tsc, 'set-uri', 'Opens the Timeline view, then fires onDidChangeUri.', [f'{TS}:226-230'],
                      [call(open_view, {'id': 'timeline', 'focus': True}, source=f'{TS}:228'), sets({'state.uri': '= input.uri'}, source=f'{TS}:229'), ret({'uri': '= input.uri'})],
                      request={'type': 'object', 'properties': {'uri': {'type': 'string', 'default': 'file:///work/app/src/main.ts'}}})
    p.cmd('timeline-contribution', 'files.openTimeline', 'timeline/browser/timeline.contribution.ts:89', 'timeline/browser/timeline.contribution.ts:73-85',
          'Open Timeline for a resource (explorer item or active editor); without one, just opens the view.',
          [iff("has(input.uri) && input.uri != ''", [call(set_uri, {'uri': '= input.uri'}, source='timeline/browser/timeline.contribution.ts:80'), ret({'uri': '= input.uri'})]),
           call(open_view, {'id': 'timeline', 'focus': True}, source='timeline/browser/timeline.contribution.ts:82'), ret({'uri': None})],
          request={'type': 'object', 'properties': {'uri': {'type': 'string', 'default': 'file:///work/app/src/util.ts'}}},
          scen=[{'expect': ["state['timeline-service@w1'].uri == 'file:///work/app/src/util.ts'", called(open_view)]},
                {'id': 'open-timeline-no-resource', 'input': {'uri': ''}, 'expect': [called(open_view), "!('uri' in state['timeline-service@w1'])"]}])
    # Timeline pane commands
    load = p.iface('timeline-pane', 'load-timeline',
                   'TimelinePane.loadTimeline(reset): with no target (no uri and not the workspace timeline) the pane is cleared; otherwise every registered source '
                   'that is not excluded (timeline.excludeSources) is requested again.',
                   [f'{TP}:653-690', f'{TP}:695-698'],
                   [iff("!(has(state.uri) && state.uri != null) && !state.workspace",
                        [sets({'state.requested': []}, title='clear(false); refresh()'), ret({'requested': []})], title='No target: nothing to load', source=f'{TP}:665-670'),
                    call(sources, {}, as_='src', title='timelineService.getSources()', source=f'{TP}:678'),
                    sets({'vars.ex': '= has(state.excluded) ? state.excluded : []'}),
                    sets({'state.requested': '= vars.src.value.sources.map(s, s.id).filter(id, !(id in vars.ex))'}, title='loadTimelineForSource skips excluded sources', source=f'{TP}:679-700'),
                    ret({'requested': '= state.requested'})])
    p.cmd('timeline-pane', 'timeline.refresh', f'{TP}:1472', f'{TP}:1486-1488', 'Refresh: resets the pane (loadTimeline(true) with TimelineTriggerKind.Invoke), which reloads every source that is not excluded.',
          [sets({'state.reset_count': "= (has(state.reset_count) ? state.reset_count : 0) + 1"}, title='pane.reset()', source=f'{TP}:1487'),
           call(load, {}, as_='l', source=f'{TP}:356-358'), ret({'reset': True, 'requested': '= vars.l.value.requested'})],
          scen=[{'expect': ["state['timeline-pane@w1'].reset_count == 1", 'size(steps.s.result.value.requested) == 0']},
                {'id': 'timeline-refresh-workspace', 'state': {'timeline-pane@w1': {'excluded': ['timeline.localHistory'], 'reset_count': 0, 'workspace': True},
                                                              'timeline-service@w1': {'providers': {'timeline.localHistory': {'id': 'timeline.localHistory', 'label': 'Local History'},
                                                                                                    'git-history': {'id': 'git-history', 'label': 'Git History'}}, 'workspace_providers': {}}},
                 'expect': ["steps.s.result.value.requested == ['git-history']"]}])
    p.cmd('timeline-pane', 'timeline.showWorkspaceTimeline', f'{TP}:1491', f'{TP}:1502-1504', 'Pin Workspace Timeline: setUriCore(undefined, workspace=true, disableFollowing=true) stops following the active editor, sets timelineForWorkspace and reloads.',
          [sets({'state.follow_active_editor': False, 'state.uri': None, 'state.workspace': True}, title='pane.showWorkspaceTimeline() -> setUriCore', source=f'{TP}:370-376'),
           call(set_ctx, {'key': 'timelineForWorkspace', 'value': True}, source=f'{TP}:377'),
           call(load, {}, as_='l', source=f'{TP}:384'), ret({'workspace': True, 'requested': '= vars.l.value.requested'})],
          scen=[{'expect': ["state['timeline-pane@w1'].workspace", called(set_ctx, "e.input.key == 'timelineForWorkspace'"), "!state['timeline-pane@w1'].follow_active_editor"]},
                {'id': 'show-workspace-timeline-with-provider', 'pre': [{'interface': reg, 'caller': 'workbench', 'input': {'id': 'timeline.localHistory', 'label': 'Local History'}}],
                 'expect': ["steps.s.result.value.requested == ['timeline.localHistory']"]}])
    p.cmd('timeline-pane', 'timeline.toggleExcludeSource:${source.id}', f'{TP}:1600', f'{TP}:1612-1619',
          'Toggle a timeline source in the filter (one command per source, e.g. timeline.toggleExcludeSource:timeline.localHistory); persisted as timeline.excludeSources (PROFILE).',
          [sets({'vars.ex': "= has(state.excluded) ? state.excluded : []"}),
           sets({'state.excluded': "= input.source in vars.ex ? vars.ex.filter(s, s != input.source) : vars.ex + [input.source]"}, source=f'{TP}:1613-1615'),
           call(store, {'key': 'timeline.excludeSources', 'value': "= '[' + state.excluded.map(s, '\"' + s + '\"').join(',') + ']'", 'scope': 'profile', 'target': 'user'}, source=f'{TP}:1617-1618'),
           ret({'excluded': '= state.excluded'})],
          request={'type': 'object', 'properties': {'source': {'type': 'string', 'default': 'timeline.localHistory'}}},
          scen=[{'id': 'toggle-exclude-source', 'expect': ["'timeline.localHistory' in state['timeline-pane@w1'].excluded", called(store, "e.input.key == 'timeline.excludeSources'")]},
                {'id': 'toggle-exclude-source-twice', 'pre': [{'interface': 'timeline-pane.cmd-timeline-toggleexcludesource-source-id', 'caller': 'user', 'input': {}}],
                 'expect': ["size(state['timeline-pane@w1'].excluded) == 0"]}])
    p.seed['timeline-pane'] = {'excluded': [], 'reset_count': 0, 'workspace': False}

    # LocalHistoryTimeline contribution
    lht = p.comp('local-history-timeline', 'LocalHistoryTimeline', 'local-history-contribution', ['localHistory/browser/localHistoryTimeline.ts:28'],
                 'Timeline provider of local history entries; registered only while workbench.localHistory.enabled.')
    p.iface(lht, 'constructor', 'Registers the timeline provider when local history is enabled (and the vscode-local-history file system provider).',
            ['localHistory/browser/localHistory.contribution.ts:11', 'localHistory/browser/localHistoryTimeline.ts:45-76'],
            [iff("'workbench-local-history-enabled' in config && config['workbench-local-history-enabled']",
                 [call(reg, {'id': 'timeline.localHistory', 'label': 'Local History'}, source='localHistory/browser/localHistoryTimeline.ts:70-71'), ret({'timeline_registered': True})],
                 [call(unreg, {'id': 'timeline.localHistory'}, source='localHistory/browser/localHistoryTimeline.ts:72-73'), ret({'timeline_registered': False})],
                 title='updateTimelineRegistration reads workbench.localHistory.enabled')])
    p.scenario_for('local-history-timeline.constructor', {'id': 'local-history-timeline-enabled', 'caller': 'workbench',
                                                          'post': [{'interface': 'timeline-service.get-sources', 'caller': 'workbench', 'as': 'r'}],
                                                          'expect': ["steps.r.result.value.sources.exists(s, s.id == 'timeline.localHistory')", "'timeline.localHistory' in state['timeline-service@w1'].providers"]})
    p.scenario_for('local-history-timeline.constructor', {'id': 'local-history-timeline-disabled', 'caller': 'workbench', 'config': {'workbench-local-history-enabled': False},
                                                          'expect': ['!steps.s.result.value.timeline_registered', "!('timeline.localHistory' in state['timeline-service@w1'].providers)"]})
    return p

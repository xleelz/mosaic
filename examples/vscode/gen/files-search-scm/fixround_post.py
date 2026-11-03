"""Scenario rewrites and new scenarios for the fix round (applied by patch.py before dumping)."""

MAIN = 'file:///work/app/src/main.ts'
UTIL = 'file:///work/app/src/util.ts'
DIRTY = "import { add } from './util';\nconsole.log(add(1, 2))\n"
CLEAN = "import { add } from './util';\nconsole.log(add(1, 2));\n"
SEED = ['one-window-folder', 'files-search-scm-seed', 'editor-seed']
DSEED = ['dirty-editor', 'files-search-scm-seed', 'editor-dirty']
PROVIDER = {'search-service@w1': {'text_providers': {'file': True}}}


def edit(text, line=1, col=1):
    return {'uri': MAIN, 'edits': [{'range': {'start_line': line, 'start_column': col, 'end_line': line, 'end_column': col}, 'text': text}]}


def apply(d):
    S = {s['id']: s for s in d['scenarios']}

    # _executeWorkspaceSymbolProvider asserts a string query
    for st in S['commands-search-actions']['steps']:
        if st.get('input', {}).get('command_id') == '_executeWorkspaceSymbolProvider':
            st['input']['args'] = ['add']

    # the revert command catches the error and shows a notification
    S['files-revert-error-restores-dirty']['expect'] = [
        "result.ok && !result.value.result.reverted",
        "trace.exists(e, e.type == 'call.start' && e.interface == 'notification-service.notify' && e.input.severity == 'error')",
        f"state['text-file-models@w1'].models['{MAIN}'].dirty",
    ]

    # typing goes through the editor's text model, which calls the text file model's listener
    s = S['files-content-change-marks-dirty-and-backs-up']
    s['steps'] = [{'interface': 'text-model.apply-edits', 'caller': 'user', 'as': 'edit', 'input': edit('b', 1, 2)},
                  {'flow': 'files-backups-read', 'as': 'backups'}]
    s['expect'] = [
        f"steps.edit.result.value.changed && state['text-file-models@w1'].models['{MAIN}'].dirty",
        "trace.exists(e, e.type == 'call.end' && e.interface == 'text-file-models.on-model-content-changed' && e.output.dirty && e.output.version_id == 2)",
        "steps.backups.result.value.resources == ['file:///work/app/src/main.ts']",
        f"state['native-working-copy-backup-service@w1'].backups['{MAIN}'].content == 'ab\\n'",
        "state['dirty-files-indicator@w1'].badge == 1",
        "trace.exists(e, e.type == 'call.start' && e.interface == 'editor-service.open-editor' && e.input.options.inactive)",
        f"!has(state['text-file-models@w1'].models['{MAIN}'].value)",
    ]

    s = S['files-content-change-readonly']
    s.pop('input', None)
    s['steps'] = [{'interface': 'text-model.apply-edits', 'caller': 'user', 'as': 'edit', 'input': edit('b')}]
    s['expect'] = [
        f"steps.edit.result.ok && !state['text-file-models@w1'].models['{MAIN}'].dirty",
        f"state['text-model@w1'].models['{MAIN}'].version_id == 2",
    ]

    s = S['files-content-change-undo-to-saved']
    s['fixtures'] = SEED
    s.pop('input', None)
    s['steps'] = [{'interface': 'text-model.push-edit-operations', 'caller': 'user', 'as': 'edit', 'input': edit('// ')},
                  {'interface': 'text-model.undo', 'caller': 'user', 'as': 'undo', 'input': {'uri': MAIN}}]
    s['expect'] = [
        f"steps.undo.result.ok && !state['text-file-models@w1'].models['{MAIN}'].dirty",
        "trace.exists(e, e.type == 'call.start' && e.interface == 'text-file-models.on-model-content-changed' && e.input.is_undoing_or_redoing && e.input.alternative_version_id == 1)",
        f"state['native-working-copy-backup-service@w1'].backups == {{}}",
        "calls['text-file-save-error-handler.on-file-saved-or-reverted'] == 1",
    ]

    new = []
    # E1 / X7: Ctrl+S and the command service with no args save the active editor
    new.append({'id': 'files-save-ctrl-s-active-editor', 'flow': 'files-save', 'fixtures': DSEED,
                'name': 'Ctrl+S resolves workbench.action.files.save; the command finds the active editor and saves it',
                'steps': [{'flow': 'workbench-shell-keybinding-dispatch', 'input': {'keypress': 'ctrl+s'}, 'as': 'key'},
                          {'flow': 'files-model-get', 'input': {'resource': MAIN}, 'as': 'get'}],
                'expect': [
                    "steps.key.result.ok",
                    "!steps.get.result.value.model.dirty && steps.get.result.value.model.saved_version_id == steps.get.result.value.model.alternative_version_id",
                    "state['disk'].files['file:///work/app/src/main.ts'].content == \"import { add } from './util';\\nconsole.log(add(1, 2))\\n\"",
                    "trace.filter(e, e.type == 'call.start' && e.interface in ['command-service.execute-command','file-commands.cmd-workbench-action-files-save','file-commands.resolve-command-editor','editor-service.save','text-file-models.save','disk.write-file']).map(e, e.interface) == ['command-service.execute-command','file-commands.cmd-workbench-action-files-save','file-commands.resolve-command-editor','editor-service.save','text-file-models.save','disk.write-file']",
                    "trace.exists(e, e.type == 'call.start' && e.interface == 'editor-service.save' && e.input.resource == 'file:///work/app/src/main.ts' && e.input.force)",
                ]})
    new.append({'id': 'files-save-command-no-active-editor', 'flow': 'files-save', 'fixtures': SEED,
                'steps': [{'interface': 'command-service.execute-command', 'caller': 'user', 'as': 'cmd',
                           'input': {'command_id': 'workbench.action.files.save', 'args': []}},
                          {'flow': 'files-model-get', 'input': {'resource': MAIN}, 'as': 'get'}],
                'expect': ["steps.cmd.result.ok && calls['editor-service.save'] == 0 && calls['disk.write-file'] == 0",
                           "trace.exists(e, e.type == 'call.end' && e.interface == 'file-commands.resolve-command-editor' && !e.output.found)",
                           "!steps.get.result.value.model.dirty"]})
    new.append({'id': 'files-save-command-uri-argument', 'flow': 'files-save', 'fixtures': DSEED,
                'steps': [{'interface': 'command-service.execute-command', 'caller': 'user', 'as': 'cmd',
                           'input': {'command_id': 'workbench.action.files.save', 'args': [MAIN]}},
                          {'flow': 'files-model-get', 'input': {'resource': MAIN}, 'as': 'get'}],
                'expect': ["steps.cmd.result.ok && !steps.get.result.value.model.dirty",
                           "trace.exists(e, e.type == 'call.end' && e.interface == 'file-commands.resolve-command-editor' && e.output.resource == 'file:///work/app/src/main.ts')"]})
    # E8: revert reloads the one text model
    new.append({'id': 'files-revert-active-editor-reloads-text-model', 'flow': 'files-revert', 'fixtures': DSEED,
                'steps': [{'interface': 'file-commands.cmd-workbench-action-files-revert', 'caller': 'user', 'as': 'revert',
                           'input': {'command_id': 'workbench.action.files.revert'}},
                          {'flow': 'files-model-get', 'input': {'resource': MAIN}, 'as': 'get'},
                          {'flow': 'editor-read-model', 'input': {'uri': MAIN}, 'as': 'text'}],
                'expect': ["steps.revert.result.ok && !steps.get.result.value.model.dirty",
                           "steps.text.result.value.value == \"import { add } from './util';\\nconsole.log(add(1, 2));\\n\"",
                           "steps.get.result.value.model.saved_version_id == steps.text.result.value.alternative_version_id",
                           "calls['text-model.set-value'] == 1 && calls['disk.write-file'] == 0",
                           f"!has(state['text-file-models@w1'].models['{MAIN}'].value) || state['text-file-models@w1'].models['{MAIN}'].value != steps.text.result.value.value"]})
    # E9: an external change reloads the text model of a clean model
    new.append({'id': 'files-external-change-updates-text-model', 'flow': 'files-external-change', 'fixtures': SEED,
                'state': {'disk': {'files': {MAIN: {'content': '// changed on disk\n', 'mtime': 1793318500000, 'size': 19}}}},
                'steps': [{'flow': 'files-external-change', 'input': {'changes': [{'resource': MAIN, 'type': 'updated'}]}, 'as': 'change'},
                          {'flow': 'editor-read-model', 'input': {'uri': MAIN}, 'as': 'text'},
                          {'flow': 'files-model-get', 'input': {'resource': MAIN}, 'as': 'get'}],
                'expect': ["steps.change.result.value.reloaded == ['file:///work/app/src/main.ts']",
                           "steps.text.result.value.value == '// changed on disk\\n' && steps.text.result.value.version_id == 2",
                           "!steps.get.result.value.model.dirty && steps.get.result.value.model.saved_version_id == 2",
                           "calls['notification-service.notify'] == 0",
                           f"!state['text-file-models@w1'].models['{MAIN}'].dirty && !has(state['text-file-models@w1'].models['{MAIN}'].value)"]})
    # E7b: saving after an undo remembers the alternative version id
    new.append({'id': 'files-undo-back-to-version-saved-after-undo', 'flow': 'files-save', 'fixtures': ['full-window', 'editor-main-open'],
                'steps': [{'flow': 'editor-type-text', 'as': 't1'},
                          {'flow': 'editor-run-command', 'input': {'command_id': 'undo'}, 'as': 'u1'},
                          {'flow': 'files-save', 'input': {'command_id': 'workbench.action.files.save', 'resource': MAIN}, 'as': 'save'},
                          {'flow': 'editor-type-text', 'input': {'args': {'text': 'x'}}, 'as': 't2'},
                          {'flow': 'files-model-get', 'input': {'resource': MAIN}, 'as': 'dirty'},
                          {'flow': 'editor-run-command', 'input': {'command_id': 'undo'}, 'as': 'u2'},
                          {'flow': 'files-model-get', 'input': {'resource': MAIN}, 'as': 'after'}],
                'expect': ["steps.save.result.ok && steps.dirty.result.value.model.dirty",
                           "steps.after.result.value.model.alternative_version_id == 1 && steps.after.result.value.model.saved_version_id == 1",
                           "!steps.after.result.value.model.dirty",
                           f"!state['text-file-models@w1'].models['{MAIN}'].dirty && state['text-model@w1'].models['{MAIN}'].alternative_version_id == 1"]})
    # create keeps its contents (oracle)
    new.append({'id': 'files-create-keeps-contents', 'flow': 'files-working-copy-create', 'fixtures': SEED,
                'steps': [{'flow': 'files-working-copy-create', 'input': {'resource': 'file:///work/app/small_new.txt', 'value': 'Hello World'}, 'as': 'create'},
                          {'interface': 'file-service.read-file', 'caller': 'user', 'input': {'resource': 'file:///work/app/small_new.txt'}, 'as': 'read'}],
                'expect': ["steps.create.result.ok && steps.read.result.value.value == 'Hello World' && steps.read.result.value.size == 11",
                           "trace.exists(e, e.type == 'call.start' && e.interface == 'file-service.create-file' && e.input.content == 'Hello World')"]})
    # a new model's text lands in the editor's text model, the file model keeps file state only
    new.append({'id': 'files-resolve-new-model-text-in-text-model', 'flow': 'files-resolve', 'fixtures': SEED,
                'steps': [{'flow': 'files-resolve', 'as': 'res'},
                          {'flow': 'editor-read-model', 'input': {'uri': UTIL}, 'as': 'text'}],
                'expect': ["steps.res.result.ok && steps.res.result.value.value == steps.text.result.value.value",
                           "steps.text.result.value.value.startsWith('export function add')",
                           f"!has(state['text-file-models@w1'].models['{UTIL}'].value) && state['text-file-models@w1'].models['{UTIL}'].saved_version_id == 1",
                           f"state['text-file-models@w1'].models['{UTIL}'].encoding == 'utf8' && state['text-file-models@w1'].models['{UTIL}'].eol == '\\n'",
                           "calls['model-service.create-model'] == 1"]})

    # search: streaming through the search service and the text search manager
    new.append({'id': 'search-text-search-streams-open-editor-first', 'fixtures': DSEED, 'state': PROVIDER,
                'steps': [{'interface': 'search-service.text-search', 'caller': 'user', 'as': 's',
                           'input': {'query': {'pattern': 'add', 'folders': ['file:///work/app'], 'max_results': 20000,
                                               'folder_queries': [{'folder': 'file:///work/app', 'file_encoding': 'utf8'}]}}}],
                'expect': ["steps.s.result.ok && steps.s.result.value.value.results.exists(r, r.resource == 'file:///work/app/src/main.ts')",
                           "trace.exists(e, e.type == 'yield' && e.interface == 'search-service.text-search-split-sync-async' && e.output.resource == 'file:///work/app/src/main.ts')",
                           "trace.exists(e, e.type == 'call.start' && e.interface == 'ext-host-search.provide-text-search-results' && e.instance == 'eh1' && e.input.folder_encodings['file:///work/app'] == 'utf8')",
                           "trace.filter(e, e.type == 'yield' && e.interface == 'search-service.text-search-split-sync-async')[0].seq < trace.filter(e, e.type == 'call.start' && e.interface == 'ext-host-search.provide-text-search-results')[0].seq"]})
    new.append({'id': 'search-text-search-manager-streams-per-file', 'fixtures': SEED,
                'steps': [{'interface': 'text-search-manager.search', 'caller': 'user', 'as': 's',
                           'input': {'query': {'pattern': 'add', 'folders': ['file:///work/app'], 'max_results': 20000, 'folder_queries': []}}}],
                'expect': ["steps.s.result.ok && !steps.s.result.value.value.limit_hit",
                           "trace.filter(e, e.type == 'yield' && e.interface == 'text-search-manager.search').map(e, e.output.resource) == ['file:///work/app/src/main.ts', 'file:///work/app/src/util.ts']",
                           "trace.filter(e, e.type == 'yield' && e.interface == 'ripgrep-text-search-engine.provide-text-search-results').size() == 2"]})
    new.append({'id': 'search-text-search-manager-limit-hit', 'fixtures': SEED,
                'steps': [{'interface': 'text-search-manager.search', 'caller': 'user', 'as': 's',
                           'input': {'query': {'pattern': 'add', 'folders': ['file:///work/app'], 'max_results': 2, 'folder_queries': []}}}],
                'expect': ["steps.s.result.ok && steps.s.result.value.value.limit_hit",
                           "sum(trace.filter(e, e.type == 'yield' && e.interface == 'text-search-manager.search').map(e, e.output.matches)) == 2",
                           "trace.filter(e, e.type == 'call.start' && e.interface == 'disk.read-file').size() == 1"]})
    new.append({'id': 'search-text-search-manager-canonical-encoding', 'fixtures': SEED,
                'steps': [{'interface': 'text-search-manager.search', 'caller': 'user', 'as': 's',
                           'input': {'query': {'pattern': 'zzz', 'folders': ['file:///work/app', 'file:///work/lib'],
                                               'folder_queries': [{'folder': 'file:///work/app', 'file_encoding': 'windows1252'},
                                                                  {'folder': 'file:///work/lib', 'file_encoding': 'shiftjis'}]}}}],
                'expect': ["steps.s.result.value.value.folder_options.map(o, o.encoding) == ['windows-1252', 'shift-jis']",
                           "trace.exists(e, e.type == 'call.start' && e.interface == 'ripgrep-text-search-engine.provide-text-search-results' && e.input.options.folder_options[0].encoding == 'windows-1252')",
                           "!trace.exists(e, e.type == 'yield')"]})
    new.append({'id': 'search-text-search-manager-empty-pattern', 'fixtures': SEED,
                'steps': [{'interface': 'text-search-manager.search', 'caller': 'user', 'as': 's',
                           'input': {'query': {'pattern': '', 'folders': ['file:///work/app'], 'folder_queries': []}}}],
                'expect': ["steps.s.result.ok && !steps.s.result.value.value.limit_hit && calls['disk.read-file'] == 0"]})
    new.append({'id': 'search-ripgrep-cancel-kills-rg', 'fixtures': SEED,
                'steps': [{'interface': 'text-search-manager.search', 'caller': 'user', 'as': 's', 'await': False,
                           'input': {'query': {'pattern': 'add', 'folders': ['file:///work/app'], 'folder_queries': []}, 'token_name': 'rg-1'}},
                          {'cancel': 'rg-1', 'at_ms': 6}],
                'expect': ["trace.exists(e, e.type == 'cancel' && e.key == 'rg-1')",
                           "trace.filter(e, e.type == 'yield' && e.interface == 'ripgrep-text-search-engine.provide-text-search-results').size() < 2"]})
    # S2: cancel while the search runs keeps the results that arrived
    new.append({'id': 'search-cancel-running-keeps-results', 'flow': 'search-find-in-files', 'fixtures': DSEED, 'state': PROVIDER,
                'steps': [{'flow': 'search-find-in-files', 'as': 'find', 'await': False},
                          {'interface': 'search-actions.cmd-search-action-cancel', 'caller': 'user', 'at_ms': 12,
                           'input': {'command_id': 'search.action.cancel'}, 'as': 'cancel'}],
                'expect': ["steps.cancel.result.ok && steps.cancel.result.value.result.canceled",
                           "trace.exists(e, e.type == 'cancel' && e.key.startsWith('search-w1-'))",
                           "calls['search-model.clear'] == 0",
                           "state['search-model@w1'].results.exists(r, r.resource == 'file:///work/app/src/main.ts')",
                           "state['search-model@w1'].current_token == ''"]})
    new.append({'id': 'search-cancel-nothing-running', 'flow': 'search-find-in-files', 'fixtures': DSEED, 'state': PROVIDER,
                'steps': [{'flow': 'search-find-in-files', 'as': 'find'},
                          {'interface': 'search-actions.cmd-search-action-cancel', 'caller': 'user',
                           'input': {'command_id': 'search.action.cancel'}, 'as': 'cancel'}],
                'expect': ["steps.find.result.ok && !steps.cancel.result.value.result.canceled",
                           "size(state['search-model@w1'].results) > 0 && calls['search-model.clear'] == 0",
                           "!trace.exists(e, e.type == 'cancel')"]})
    # workspace symbols
    new.append({'id': 'search-workspace-symbols-invalid-argument', 'fixtures': SEED,
                'steps': [{'interface': 'search-actions.cmd-executeworkspacesymbolprovider', 'caller': 'user', 'as': 'none',
                           'input': {'command_id': '_executeWorkspaceSymbolProvider', 'args': []}},
                          {'interface': 'search-actions.cmd-executeworkspacesymbolprovider', 'caller': 'user', 'as': 'bool',
                           'input': {'command_id': '_executeWorkspaceSymbolProvider', 'args': [True]}}],
                'expect': ["!steps.none.result.ok && steps.none.result.error.code == 'unexpected-type'",
                           "!steps.bool.result.ok && steps.bool.result.error.code == 'unexpected-type'",
                           "calls['workspace-symbol-provider-registry.get-workspace-symbols'] == 0"]})
    new.append({'id': 'search-workspace-symbols-register-then-query', 'fixtures': SEED,
                'steps': [{'interface': 'workspace-symbol-provider-registry.register', 'caller': 'user', 'as': 'reg',
                           'input': {'handle': 1, 'extension_id': 'vscode.typescript-language-features'}},
                          {'interface': 'search-actions.cmd-executeworkspacesymbolprovider', 'caller': 'user', 'as': 'q',
                           'input': {'command_id': '_executeWorkspaceSymbolProvider', 'args': ['']}}],
                'expect': ["steps.reg.result.value.count == 1 && steps.q.result.ok",
                           "size(state['workspace-symbol-provider-registry@w1'].providers) == 1",
                           "trace.exists(e, e.type == 'call.start' && e.interface == 'ext-host-language-features.provide-workspace-symbols' && e.instance == 'eh1' && e.input.search == '' && e.input.handle == 1)"]})
    new.append({'id': 'search-workspace-symbols-no-provider', 'fixtures': SEED,
                'steps': [{'interface': 'search-actions.cmd-executeworkspacesymbolprovider', 'caller': 'user', 'as': 'q',
                           'input': {'command_id': '_executeWorkspaceSymbolProvider', 'args': ['add']}}],
                'expect': ["steps.q.result.ok && steps.q.result.value.result == []",
                           "calls['ext-host-language-features.provide-workspace-symbols'] == 0 && state['workspace-symbol-provider-registry@w1'].providers == []"]})
    # E3b: a hung formatter; the user presses Skip on the progress notification
    FMT = ['full-format-on-save', 'editor-ts-providers']
    HUNG = [{'target': 'ext-host-language-features.provide-document-formatting-edits', 'type': 'timeout'}]
    new.append({'id': 'files-save-skip-hung-formatter', 'flow': 'files-save', 'fixtures': FMT, 'faults': HUNG,
                'steps': [{'flow': 'files-save', 'input': {'command_id': 'workbench.action.files.save', 'resource': MAIN}, 'as': 'save', 'await': False},
                          {'interface': 'text-file-save-participant.skip', 'caller': 'user', 'at_ms': 6000, 'input': {'resource': MAIN}, 'as': 'skip'},
                          {'flow': 'files-model-get', 'input': {'resource': MAIN}, 'at_ms': 8000, 'as': 'get'}],
                'expect': ["steps.skip.result.value.skipped && steps.save.result.ok && steps.save.result.value.result.success",
                           "trace.exists(e, e.type == 'cancel' && e.key.startsWith('save-participants-'))",
                           "trace.exists(e, e.type == 'call.end' && e.interface == 'text-file-save-participant.participate' && e.output.skipped)",
                           "trace.filter(e, e.type == 'call.start' && e.interface == 'disk.write-file')[0].t < 7000",
                           "state['disk'].files['file:///work/app/src/main.ts'].content == \"import { add } from './util';\\nconsole.log(add(1, 2))\\n\"",
                           "!steps.get.result.value.model.dirty && state['text-file-save-participant@w1'].running == {}"]})
    new.append({'id': 'files-save-skip-before-progress-shows', 'flow': 'files-save', 'fixtures': FMT, 'faults': HUNG,
                'max_virtual_ms': 120000,
                'steps': [{'flow': 'files-save', 'input': {'command_id': 'workbench.action.files.save', 'resource': MAIN}, 'as': 'save', 'await': False},
                          {'interface': 'text-file-save-participant.skip', 'caller': 'user', 'at_ms': 1000, 'input': {'resource': MAIN}, 'as': 'skip'}],
                'expect': ["!steps.skip.result.value.skipped",
                           "!trace.exists(e, e.type == 'cancel' && e.key.startsWith('save-participants-'))",
                           "trace.filter(e, e.type == 'call.start' && e.interface == 'disk.write-file')[0].t > 6000"]})
    new.append({'id': 'files-save-skip-nothing-running', 'flow': 'files-save', 'fixtures': SEED,
                'steps': [{'interface': 'text-file-save-participant.skip', 'caller': 'user', 'input': {'resource': MAIN}, 'as': 'skip'}],
                'expect': ["!steps.skip.result.value.skipped && state['text-file-save-participant@w1'].running == {}"]})
    have = {s['id'] for s in d['scenarios']}
    d['scenarios'] += [s for s in new if s['id'] not in have]

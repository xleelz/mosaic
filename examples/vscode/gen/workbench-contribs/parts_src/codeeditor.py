from builder import Part, call, ret, iff, choice, sets, note, called

CB = 'codeEditor/browser'
EO = 'src/vs/editor/common/config/editorOptions.ts'


def cfg(id, key, typ, val, reg, read):
    return {'id': id, 'type': typ, 'value': val, 'default': val, 'summary': f'{key} (editor option; registered by the editor area, read here by a toggle command).',
            'sources': [reg, read], 'attributes': {'key': key, 'boundary': True, 'owner': 'editor'}}


def build():
    p = Part('codeeditor')
    ws = 'workbench-shell'
    update = p.stub('configuration-service.update-value', 'platform-core')
    qa = p.stub('quick-input-service.quick-access-show', ws)
    set_ctx = p.stub('context-key-service.set-context', 'platform-core')
    prompt = p.stub('notification-service.prompt', ws)
    clip_read = p.stub('clipboard-service.read-text', ws, response={'type': 'object', 'properties': {'text': {'type': 'string', 'examples': ['selected words']}}})
    push = p.stub('text-model.push-edit-operations', 'editor')
    p.configs += [
        cfg('editor-minimap-enabled', 'editor.minimap.enabled', 'boolean', True, f'{EO}:3505-3507', f'src/vs/workbench/contrib/{CB}/toggleMinimap.ts:38'),
        cfg('editor-render-control-characters', 'editor.renderControlCharacters', 'boolean', True, f'{EO}:6631-6633', f'src/vs/workbench/contrib/{CB}/toggleRenderControlCharacter.ts:38'),
        cfg('editor-column-selection', 'editor.columnSelection', 'boolean', False, f'{EO}:6238-6240', f'src/vs/workbench/contrib/{CB}/toggleColumnSelection.ts:43'),
        cfg('editor-multi-cursor-modifier', 'editor.multiCursorModifier', 'string', 'alt', f'{EO}:6511-6514', f'src/vs/workbench/contrib/{CB}/toggleMultiCursorModifier.ts:34'),
        cfg('editor-render-whitespace', 'editor.renderWhitespace', 'string', 'selection', f'{EO}:6664-6667', f'src/vs/workbench/contrib/{CB}/toggleRenderWhitespace.ts:120'),
        cfg('editor-accessibility-support', 'editor.accessibilitySupport', 'string', 'auto', f'{EO}:6048', f'src/vs/workbench/contrib/{CB}/accessibility/accessibility.ts:48'),
    ]

    def toggle(comp, cid, entry, handler, summary, key, cfgid, newval, line, scen_expect_val, alt_val=None):
        sc = [{'expect': [called(update, f"e.input.key == '{key}' && e.input.value == {scen_expect_val}")]}]
        if alt_val is not None:
            sc.append({'id': cid.split('.')[-1] + '-back', 'config': {cfgid: alt_val[0]}, 'expect': [called(update, f"e.input.key == '{key}' && e.input.value == {alt_val[1]}")]})
        return p.cmd(comp, cid, entry, handler, summary,
                     [call(update, {'key': key, 'value': newval}, title='Write the toggled value to user settings', source=line), ret({'value': newval})], scen=sc)

    toggle('code-editor-toggle-minimap', 'editor.action.toggleMinimap', f'{CB}/toggleMinimap.ts:43', f'{CB}/toggleMinimap.ts:35-40', 'View: Toggle Minimap (writes editor.minimap.enabled).',
           'editor.minimap.enabled', 'editor-minimap-enabled', "= !config['editor-minimap-enabled']", f'{CB}/toggleMinimap.ts:38-39', 'false', (False, 'true'))
    toggle('code-editor-toggle-render-control-character', 'editor.action.toggleRenderControlCharacter', f'{CB}/toggleRenderControlCharacter.ts:43', f'{CB}/toggleRenderControlCharacter.ts:35-40',
           'View: Toggle Control Characters.', 'editor.renderControlCharacters', 'editor-render-control-characters', "= !config['editor-render-control-characters']", f'{CB}/toggleRenderControlCharacter.ts:38-39', 'false')
    toggle('code-editor-toggle-multi-cursor-modifier', 'workbench.action.toggleMultiCursorModifier', f'{CB}/toggleMultiCursorModifier.ts:71', f'{CB}/toggleMultiCursorModifier.ts:31-38',
           'Toggle Multi-Cursor Modifier between Alt and Ctrl/Cmd.', 'editor.multiCursorModifier', 'editor-multi-cursor-modifier',
           "= config['editor-multi-cursor-modifier'] == 'ctrlCmd' ? 'alt' : 'ctrlCmd'", f'{CB}/toggleMultiCursorModifier.ts:35-37', "'ctrlCmd'", ('ctrlCmd', "'alt'"))
    ws_file = f'{CB}/toggleRenderWhitespace.ts'
    for cls_line, val, run in [(134, 'none', '28-30'), (135, 'boundary', '46-48'), (136, 'selection', '64-66'), (137, 'trailing', '82-84'), (138, 'all', '100-102')]:
        toggle('code-editor-toggle-render-whitespace', f'editor.action.renderWhitespace.{val}', f'{ws_file}:{cls_line}', f'{ws_file}:{run}', f'View: Render Whitespace {val}.',
               'editor.renderWhitespace', 'editor-render-whitespace', val, f'{ws_file}:{run}', f"'{val}'")
    toggle('code-editor-toggle-render-whitespace', 'editor.action.toggleRenderWhitespace', f'{ws_file}:139', f'{ws_file}:118-131', 'View: Toggle Render Whitespace: none -> all, anything else -> none.',
           'editor.renderWhitespace', 'editor-render-whitespace', "= config['editor-render-whitespace'] == 'none' ? 'all' : 'none'", f'{ws_file}:122-131', "'none'", ('none', "'all'"))
    p.cmd('code-editor-toggle-column-selection', 'editor.action.toggleColumnSelection', f'{CB}/toggleColumnSelection.ts:89', f'{CB}/toggleColumnSelection.ts:39-87',
          'Toggle Column Selection Mode (editor.columnSelection); the current selection is converted to/from a column selection.',
          [call(update, {'key': 'editor.columnSelection', 'value': "= !config['editor-column-selection']"}, source=f'{CB}/toggleColumnSelection.ts:45'),
           ret({'column_selection': "= !config['editor-column-selection']"})],
          scen=[{'expect': ['steps.s.result.value.column_selection', called(update, "e.input.key == 'editor.columnSelection' && e.input.value == true")]}])
    p.cmd('code-editor-toggle-overtype', 'editor.action.toggleOvertypeInsertMode', f'{CB}/toggleOvertype.ts:43', f'{CB}/toggleOvertype.ts:36-40', 'Toggle Overtype/Insert Mode (global InputMode).',
          [sets({'vars.old': "= has(state.input_mode) ? state.input_mode : 'insert'"}, title='InputMode.getInputMode() (starts as insert)', source=f'{CB}/toggleOvertype.ts:37'),
           iff("vars.old == 'insert'", [sets({'state.input_mode': 'overtype'})], [sets({'state.input_mode': 'insert'})],
               title='insert -> overtype, anything else -> insert; setInputMode fires onDidChangeInputMode', source=f'{CB}/toggleOvertype.ts:38-39'),
           ret({'input_mode': '= state.input_mode', 'previous': '= vars.old'})],
          scen=[{'expect': ["state['code-editor-toggle-overtype@w1'].input_mode == 'overtype'"]},
                {'id': 'toggle-overtype-twice', 'pre': [{'interface': 'code-editor-toggle-overtype.cmd-editor-action-toggleovertypeinsertmode', 'caller': 'user', 'input': {}}],
                 'expect': ["state['code-editor-toggle-overtype@w1'].input_mode == 'insert'"]}])
    acc = f'{CB}/accessibility/accessibility.ts'
    p.cmd('code-editor-accessibility', 'editor.action.toggleScreenReaderAccessibilityMode', f'{acc}:54', f'{acc}:45-51', 'Toggle Screen Reader Accessibility Mode: writes editor.accessibilitySupport on/off (user) and announces the change.',
          [sets({'vars.optimized': "= config['editor-accessibility-support'] == 'on'"}, title='isScreenReaderOptimized()', source=f'{acc}:48'),
           call(update, {'key': 'editor.accessibilitySupport', 'value': "= vars.optimized ? 'off' : 'on'", 'target': 'user'}, source=f'{acc}:49'),
           ret({'announced': "= vars.optimized ? 'Screen Reader Optimized Mode disabled' : 'Screen Reader Optimized Mode enabled'"})],
          scen=[{'expect': [called(update, "e.input.value == 'on' && e.input.target == 'user'")]},
                {'id': 'screen-reader-mode-off', 'config': {'editor-accessibility-support': 'on'}, 'expect': [called(update, "e.input.value == 'off'")]}])
    gl = f'{CB}/quickaccess/gotoLineQuickAccess.ts'
    p.cmd('code-editor-goto-line-quick-access', 'workbench.action.gotoLine', f'{gl}:94', f'{gl}:89-91', 'Go to Line/Column...: opens quick access with the ":" prefix.',
          [call(qa, {'prefix': ':'}, source=f'{gl}:90'), ret({'prefix': ':'})], scen=[{'expect': [called(qa, "e.input.prefix == ':'")]}])
    p.cmd('code-editor-goto-line-quick-access', 'workbench.action.gotoOffset', f'{gl}:120', f'{gl}:115-117', 'Go to Offset...: opens quick access with the "::" prefix.',
          [call(qa, {'prefix': '::'}, source=f'{gl}:116'), ret({'prefix': '::'})], scen=[{'expect': [called(qa, "e.input.prefix == '::'")]}])
    gs = f'{CB}/quickaccess/gotoSymbolQuickAccess.ts'
    p.cmd('code-editor-goto-symbol-quick-access', 'workbench.action.gotoSymbol', f'{gs}:371', f'{gs}:366-368', 'Go to Symbol in Editor...: opens quick access with the "@" prefix.',
          [call(qa, {'prefix': '@'}, source=f'{gs}:367'), ret({'prefix': '@'})], scen=[{'expect': [called(qa, "e.input.prefix == '@'")]}])
    sc = 'codeEditor/electron-browser/selectionClipboard.ts'
    p.cmd('code-editor-selection-clipboard-native', 'editor.action.selectionClipboardPaste', f'{sc}:142', f'{sc}:125-137',
          'Paste Selection Clipboard (Linux middle-click): reads the selection clipboard and pastes it at the cursor.',
          [call(clip_read, {'type': 'selection'}, as_='t', source=f'{sc}:129'),
           call(push, {'uri': 'file:///work/app/src/main.ts', 'edits': [{'range': {'start_line': 1, 'start_column': 1, 'end_line': 1, 'end_column': 1}, 'text': '= vars.t.value.text'}], 'source': 'paste'},
                title='editor.trigger(keyboard, paste, {text})', source=f'{sc}:131-135'),
           ret({'pasted': True})],
          scen=[{'fixtures': ['editor-main-open', 'workbench-contribs-seed'], 'expect': [called(push, "e.input.source == 'paste'")]}])
    # contributions
    mcm = p.comp('multi-cursor-modifier-context-key-controller', 'MultiCursorModifierContextKeyController', 'code-editor-toggle-multi-cursor-modifier',
                 [f'{CB}/toggleMultiCursorModifier.ts:43'], 'Keeps the multiCursorModifier context key in sync with editor.multiCursorModifier.')
    p.iface(mcm, 'constructor', 'Sets multiCursorModifier (ctrlCmd or altKey) now and on every change of editor.multiCursorModifier.',
            [f'{CB}/toggleMultiCursorModifier.ts:69', f'{CB}/toggleMultiCursorModifier.ts:50-66'],
            [call(set_ctx, {'key': 'multiCursorModifier', 'value': "= config['editor-multi-cursor-modifier'] == 'ctrlCmd' ? 'ctrlCmd' : 'altKey'"}, source=f'{CB}/toggleMultiCursorModifier.ts:62-65'),
             ret({'value': "= config['editor-multi-cursor-modifier'] == 'ctrlCmd' ? 'ctrlCmd' : 'altKey'"})])
    p.scenario_for(f'{mcm}.constructor', {'id': 'multi-cursor-modifier-context', 'caller': 'workbench', 'expect': [called(set_ctx, "e.input.value == 'altKey'")]})
    lfo = p.comp('large-file-optimizations-warner', 'LargeFileOptimizationsWarner', 'code-editor-large-file-optimizations',
                 [f'{CB}/largeFileOptimizations.ts:18'], 'Warns when a file is too large for tokenization and offers to turn optimizations off.')
    p.iface(lfo, 'update', 'On model change: for a model too large for tokenization, prompt (never show again) with "Forcefully Enable Features" that writes editor.largeFileOptimizations=false.',
            [f'{CB}/largeFileOptimizations.ts:67', f'{CB}/largeFileOptimizations.ts:33-63'],
            [iff('!input.too_large_for_tokenization', [ret({'warned': False})], source=f'{CB}/largeFileOptimizations.ts:39'),
             call(prompt, {'severity': 'info', 'message': "= input.file_name + ': tokenization, wrapping, folding, codelens, word highlighting and sticky scroll have been turned off for this large file in order to reduce memory usage and avoid freezing or crashing.'", 'choices': ['Forcefully Enable Features']},
                  source=f'{CB}/largeFileOptimizations.ts:51-62'),
             choice('answer', 'dismiss', {'enable': [call(update, {'key': 'editor.largeFileOptimizations', 'value': False}, source=f'{CB}/largeFileOptimizations.ts:55'), ret({'warned': True, 'disabled_optimizations': True})],
                                          'dismiss': []}),
             ret({'warned': True, 'disabled_optimizations': False})],
            request={'type': 'object', 'properties': {'file_name': {'type': 'string', 'default': 'big.log'}, 'too_large_for_tokenization': {'type': 'boolean', 'default': True}}})
    p.scenario_for(f'{lfo}.update', {'id': 'large-file-warning', 'caller': 'editor', 'expect': [called(prompt)]})
    p.scenario_for(f'{lfo}.update', {'id': 'large-file-force-enable', 'caller': 'editor', 'choices': {'large-file-optimizations-warner.update.answer': 'enable'},
                                      'expect': [called(update, "e.input.key == 'editor.largeFileOptimizations' && e.input.value == false")]})
    p.scenario_for(f'{lfo}.update', {'id': 'large-file-small', 'caller': 'editor', 'input': {'too_large_for_tokenization': False}, 'expect': ['!' + called(prompt)]})
    return p

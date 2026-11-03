import json, re, yaml, copy, sys
ROOT = '/home/lbethay/.cache/mosaic-bench/vscode-1.144.0/'
OUT = '/home/lbethay/workplace/mosaic/examples/vscode/'
inv = json.load(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/editor/editor_inv.json'))
cmds = json.load(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/editor/cmds.json'))
core = yaml.safe_load(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/editor/core.yaml'))
scen = yaml.safe_load(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/editor/scenarios.yaml'))

def kebab(name):
    return re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', name).lower()

def slug(cid):
    s = 'cmd-' + cid.replace('.', '-').replace('_', '-').lower()
    return s[:64]

def lines_of(f):
    return open(ROOT + f).read().split('\n')

skips = []
def skip(e, reason):
    skips.append({k: e[k] for k in ('kind', 'name', 'file', 'line')} | {'reason': reason})

# ---------- file -> component for commands ----------
FILECOMP = {
 'browser/coreCommands.ts': 'core-navigation-commands',
 'browser/widget/diffEditor/diffEditor.contribution.ts': 'diff-editor-actions',
 'contrib/anchorSelect/browser/anchorSelect.ts': 'selection-anchor-controller',
 'contrib/bracketMatching/browser/bracketMatching.ts': 'bracket-matching-controller',
 'contrib/caretOperations/browser/caretOperations.ts': 'caret-operations',
 'contrib/caretOperations/browser/transpose.ts': 'caret-operations',
 'contrib/clipboard/browser/clipboard.ts': 'clipboard-actions',
 'contrib/codeAction/browser/codeAction.ts': 'code-action-model',
 'contrib/codeAction/browser/codeActionContributions.ts': 'code-action-controller',
 'contrib/codelens/browser/codelens.ts': 'code-lens-model',
 'contrib/codelens/browser/codelensController.ts': 'code-lens-contribution',
 'contrib/colorPicker/browser/colorPickerContribution.ts': 'color-detector',
 'contrib/comment/browser/comment.ts': 'comment-actions',
 'contrib/contextmenu/browser/contextmenu.ts': 'context-menu-controller',
 'contrib/cursorUndo/browser/cursorUndo.ts': 'cursor-undo-redo-controller',
 'contrib/documentSymbols/browser/documentSymbols.ts': 'outline-model-service',
 'contrib/dropOrPasteInto/browser/copyPasteContribution.ts': 'copy-paste-controller',
 'contrib/dropOrPasteInto/browser/dropIntoEditorContribution.ts': 'drop-into-editor-controller',
 'contrib/editorState/browser/keybindingCancellation.ts': 'editor-cancellation-tokens',
 'contrib/find/browser/findController.ts': 'find-controller',
 'contrib/folding/browser/folding.ts': 'folding-controller',
 'contrib/fontZoom/browser/fontZoom.ts': 'font-zoom-actions',
 'contrib/format/browser/format.ts': 'format',
 'contrib/format/browser/formatActions.ts': 'format-actions',
 'contrib/gotoError/browser/gotoError.ts': 'marker-controller',
 'contrib/gotoSymbol/browser/goToCommands.ts': 'symbol-navigation-action',
 'contrib/gotoSymbol/browser/peek/referencesController.ts': 'references-controller',
 'contrib/gotoSymbol/browser/symbolNavigation.ts': 'symbol-navigation-service',
 'contrib/hover/browser/hoverContribution.ts': 'content-hover-controller',
 'contrib/inPlaceReplace/browser/inPlaceReplace.ts': 'in-place-replace-controller',
 'contrib/indentation/browser/indentation.ts': 'indentation-actions',
 'contrib/inlayHints/browser/inlayHintsController.ts': 'inlay-hints-controller',
 'contrib/inlineCompletions/browser/inlineCompletions.contribution.ts': 'inline-completions-controller',
 'contrib/inlineCompletions/browser/model/renameSymbolProcessor.ts': 'inline-completions-controller',
 'contrib/insertFinalNewLine/browser/insertFinalNewLine.ts': 'insert-final-new-line-action',
 'contrib/lineSelection/browser/lineSelection.ts': 'expand-line-selection-action',
 'contrib/linesOperations/browser/linesOperations.ts': 'lines-operations',
 'contrib/linkedEditing/browser/linkedEditing.ts': 'linked-editing-contribution',
 'contrib/links/browser/getLinks.ts': 'link-detector',
 'contrib/links/browser/links.ts': 'link-detector',
 'contrib/message/browser/messageController.ts': 'message-controller',
 'contrib/multicursor/browser/multicursor.ts': 'multi-cursor-selection-controller',
 'contrib/parameterHints/browser/parameterHints.ts': 'parameter-hints-controller',
 'contrib/parameterHints/browser/provideSignatureHelp.ts': 'parameter-hints-controller',
 'contrib/rename/browser/rename.ts': 'rename-controller',
 'contrib/semanticTokens/common/getSemanticTokens.ts': 'get-semantic-tokens',
 'contrib/smartSelect/browser/smartSelect.ts': 'smart-select-controller',
 'contrib/snippet/browser/snippetController2.ts': 'snippet-controller2',
 'contrib/stickyScroll/browser/stickyScrollContribution.ts': 'sticky-scroll-controller',
 'contrib/suggest/browser/suggest.ts': 'suggest-model',
 'contrib/suggest/browser/suggestController.ts': 'suggest-controller',
 'contrib/toggleTabFocusMode/browser/toggleTabFocusMode.ts': 'toggle-tab-focus-mode-action',
 'contrib/tokenization/browser/tokenization.ts': 'force-retokenize-action',
 'contrib/unicodeHighlighter/browser/unicodeHighlighter.ts': 'unicode-highlighter',
 'contrib/wordHighlighter/browser/wordHighlighter.ts': 'word-highlighter-contribution',
 'contrib/wordOperations/browser/wordOperations.ts': 'word-operations',
 'contrib/wordPartOperations/browser/wordPartOperations.ts': 'word-part-operations',
}
EDITING_CORE = {'lineBreakInsert', 'outdent', 'tab', 'deleteLeft', 'deleteRight'}
REALID = {'QuickFixAction': 'editor.action.quickFix', 'SourceAction': 'editor.action.sourceAction',
          'ToggleStickyScroll': 'editor.action.toggleStickyScroll'}
API_RPC = {
 '_executeCodeActionProvider': ('codeAction', 'provide-code-actions'),
 '_executeCodeLensProvider': ('codeLens', 'provide-code-lenses'),
 '_executeDocumentColorProvider': ('color', 'provide-document-colors'),
 '_executeColorPresentationProvider': ('color', 'provide-color-presentations'),
 '_executeDocumentSymbolProvider': ('documentSymbol', 'provide-document-symbols'),
 '_executeFoldingRangeProvider': ('foldingRange', 'provide-folding-ranges'),
 '_executeFormatRangeProvider': ('documentRangeFormatting', 'provide-document-range-formatting-edits'),
 '_executeFormatDocumentProvider': ('documentFormatting', 'provide-document-formatting-edits'),
 '_executeFormatOnTypeProvider': ('onTypeFormatting', 'provide-on-type-formatting-edits'),
 '_executeInlayHintProvider': ('inlayHints', 'provide-inlay-hints'),
 '_executeLinkProvider': ('links', 'provide-document-links'),
 '_executeSignatureHelpProvider': ('signatureHelp', 'provide-signature-help'),
 '_provideDocumentSemanticTokens': ('documentSemanticTokens', 'provide-document-semantic-tokens'),
 '_provideDocumentRangeSemanticTokens': ('documentRangeSemanticTokens', 'provide-document-range-semantic-tokens'),
 '_executeSelectionRangeProvider': ('selectionRange', 'provide-selection-ranges'),
 '_executeCompletionItemProvider': ('completion', 'provide-completion-items'),
}
STANDALONE_REASON = 'not an entry point: standalone Monaco only, registered under src/vs/editor/standalone, which the VS Code workbench does not load'
DEV_REASON = 'developer or internal command with no user-visible behavior'
GOTO = {
 'editor.action.revealDefinition': ('definition', 'provide-definition', {}),
 'editor.action.revealDefinitionAside': ('definition', 'provide-definition', {'open_to_side': True}),
 'editor.action.peekDefinition': ('definition', 'provide-definition', {'open_in_peek': True}),
 'editor.action.revealDeclaration': ('declaration', 'provide-declaration', {}),
 'editor.action.peekDeclaration': ('declaration', 'provide-declaration', {'open_in_peek': True}),
 'editor.action.goToTypeDefinition': ('typeDefinition', 'provide-type-definition', {}),
 'editor.action.peekTypeDefinition': ('typeDefinition', 'provide-type-definition', {'open_in_peek': True}),
 'editor.action.goToImplementation': ('implementation', 'provide-implementation', {}),
 'editor.action.peekImplementation': ('implementation', 'provide-implementation', {'open_in_peek': True}),
 'editor.action.goToReferences': ('references', 'provide-references', {'preference': "= config['editor-goto-location-multiple-references']"}),
 'editor.action.referenceSearch.trigger': ('references', 'provide-references', {'open_in_peek': True}),
 'editor.action.findReferences': ('references', 'provide-references', {'open_in_peek': True}),
}
CODEACTION = {
 'editor.action.quickFix': ('', 'never', 'No code actions available'),
 'editor.action.refactor': ('refactor', 'never', 'No refactorings available'),
 'editor.action.sourceAction': ('source', 'never', 'No source actions available'),
 'editor.action.organizeImports': ('source.organizeImports', 'ifSingle', 'No organize imports action available'),
 'editor.action.autoFix': ('quickfix', 'ifSingle', 'No auto fixes available'),
 'editor.action.fixAll': ('source.fixAll', 'ifSingle', 'No fix all action available'),
 'editor.action.codeAction': ('', 'never', 'No code actions available'),
}
FOLD = {'editor.fold': 'fold', 'editor.unfold': 'unfold', 'editor.toggleFold': 'toggle', 'editor.foldAll': 'fold-all',
        'editor.unfoldAll': 'unfold-all', 'editor.foldRecursively': 'fold', 'editor.unfoldRecursively': 'unfold',
        'editor.toggleFoldRecursively': 'toggle'}
FIND = {'actions.find': ('start', {}), 'editor.action.startFindReplaceAction': ('start', {}),
        'editor.actions.findWithArgs': ('start', {}), 'actions.findWithSelection': ('start', {}),
        'editor.action.nextMatchFindAction': ('move-to-match', {}), 'editor.action.previousMatchFindAction': ('move-to-match', {}),
        'editor.action.goToMatchFindAction': ('move-to-match', {}), 'editor.action.nextSelectionMatchFindAction': ('move-to-match', {}),
        'editor.action.previousSelectionMatchFindAction': ('move-to-match', {}),
        'closeFindWidget': ('close-widget', None), 'toggleFindCaseSensitive': ('toggle-option', {'option': 'match_case'}),
        'toggleFindWholeWord': ('toggle-option', {'option': 'whole_word'}), 'toggleFindRegex': ('toggle-option', {'option': 'is_regex'}),
        'toggleFindInSelection': ('toggle-option', {'option': 'in_selection'}), 'togglePreserveCase': ('toggle-option', {'option': 'preserve_case'}),
        'editor.action.replaceOne': ('replace-one', {}), 'editor.action.replaceAll': ('replace-all', {}),
        'editor.action.selectAllMatches': ('move-to-match', {})}
SUGGEST = {'editor.action.triggerSuggest': 'trigger-suggest', 'acceptSelectedSuggestion': 'accept-selected-suggestion',
           'acceptAlternativeSelectedSuggestion': 'accept-selected-suggestion', 'focusAndAcceptSuggestion': 'accept-selected-suggestion',
           'insertBestCompletion': 'accept-selected-suggestion', 'hideSuggestWidget': 'cancel'}
CORE_HANDLED = {'deleteLeft': 'core-editing-commands', 'editor.action.transformToUppercase': 'lines-operations',
                'editor.action.insertFinalNewLine': 'insert-final-new-line-action', 'editor.action.commentLine': 'comment-actions',
                'editor.action.formatDocument': 'format-actions'}

core_ifaces = {(i['component'], i['name']) for i in core['interfaces']}
gen_ifaces = []
registry = {}
scenario_groups = {}   # component -> [command ids with behavior]
comp_sources = {}      # component -> set of cites

def add_src(comp, s):
    comp_sources.setdefault(comp, [])
    if s not in comp_sources[comp]:
        comp_sources[comp].append(s)

def writable(c):
    if not c.get('idline') or not c.get('idfile'):
        return False
    ls = lines_of(c['idfile'])
    blk = '\n'.join(ls[c['idline'] - 1:c['idline'] + 14])
    return 'EditorContextKeys.writable' in blk

def call_step(title, src, target, inp):
    st = {'title': title, 'source': src, 'call': target}
    if inp is not None:
        st['input'] = inp
    return st

URI = '= input.uri'
for c in cmds:
    f = c['file']
    rel = f[len('src/vs/editor/'):]
    if rel.startswith('standalone/'):
        skip(c, STANDALONE_REASON); continue
    if c['name'] in ('editor.action.inlineSuggest.dev.extractRepro', 'editor.action.forceRetokenize'):
        skip(c, DEV_REASON + ' (Developer: ' + c['name'] + ')'); continue
    comp = FILECOMP[rel]
    ids = [c['name']]
    if c['name'] in REALID:
        ids = [REALID[c['name']]]
    if c['name'] == 'FoldLevelAction.ID(i)':
        ids = ['editor.foldLevel%d' % i for i in range(1, 8)]
    if rel == 'browser/coreCommands.ts' and c['name'] in EDITING_CORE:
        comp = 'core-editing-commands'
    reg = '%s:%d' % (f, c['line'])
    add_src(comp, reg)
    for cid in ids:
        name = slug(cid)
        target = comp + '.' + name
        kind = 'api' if (cid in API_RPC or cid.startswith('_execute') or cid.startswith('_provide')) else 'editor'
        registry[cid] = {'target': target, 'kind': kind, 'writable': writable(c)}
        if cid in CORE_HANDLED:
            # core interface exists; make sure it cites the registration line
            for i in core['interfaces']:
                if i['component'] == CORE_HANDLED[cid] and i['name'] == name:
                    if reg not in i['sources']:
                        i['sources'].insert(0, reg)
            scenario_groups.setdefault('core', []).append(cid)
            continue
        label = (c.get('label') if c.get('idfile') == f else None) or cid
        srcs = [reg]
        if c.get('idline') and c.get('idfile') and abs(c['idline'] - c['line']) > 3 or (c.get('idfile') and c['idfile'] != f):
            srcs.append('%s:%d' % (c['idfile'], c['idline']))
        iface = {'component': comp, 'name': name, 'kind': 'function',
                 'summary': "%s ('%s')" % (cid, label), 'sources': srcs,
                 'request': 'EditorCommandInvocation', 'attributes': {'command_id': cid}}
        beh = None
        t = 'Run ' + cid
        if kind == 'api' and cid in API_RPC:
            feat, rpc = API_RPC[cid]
            beh = [
                call_step('Resolve a model reference for the resource (ITextModelService.createModelReference)', reg,
                          'text-model-resolver-service.create-model-reference',
                          {'resource': "= !has(input.args) ? 'file:///work/app/src/main.ts' : (type(input.args) == list ? (size(input.args) > 0 && type(input.args[0]) == string ? input.args[0] : 'file:///work/app/src/main.ts') : (type(input.args) == map && 'resource' in input.args ? input.args.resource : 'file:///work/app/src/main.ts'))"}),
                {'call': 'language-features-service.invoke-providers', 'as': 'r',
                 'input': {'feature': feat, 'rpc': rpc, 'resource': "= !has(input.args) ? 'file:///work/app/src/main.ts' : (type(input.args) == list ? (size(input.args) > 0 && type(input.args[0]) == string ? input.args[0] : 'file:///work/app/src/main.ts') : (type(input.args) == map && 'resource' in input.args ? input.args.resource : 'file:///work/app/src/main.ts'))",
                           'language_id': "= has(input.args) && type(input.args) == map && 'language_id' in input.args ? input.args.language_id : 'typescript'"}},
                {'return': "= vars.r.value"}]
            iface['summary'] = "%s: API command (vscode.execute* in the extension host) that queries the registered %s providers for a resource" % (cid, feat)
            iface['request'] = {'type': 'object', 'properties': {'command_id': {'type': 'string'}, 'args': {'description': 'the positional arguments [resource, ...] or an object'}}}
        elif comp == 'core-navigation-commands' or comp in ('word-operations', 'word-part-operations', 'multi-cursor-selection-controller',
                                                              'selection-anchor-controller', 'expand-line-selection-action', 'smart-select-controller') \
                and not cid.startswith('delete'):
            if cid.startswith('scroll') or cid in ('editorScroll', 'revealLine'):
                beh = [call_step(t + ': scroll the viewport', reg, 'code-editor-widget.reveal', {'source': cid})]
            else:
                inp = {'source': cid}
                if 'Cursor' in cid and ('insert' in cid or 'add' in cid):
                    inp['cursor_count'] = 2
                if cid in ('removeSecondaryCursors', 'cancelSelection'):
                    inp['cursor_count'] = 1
                beh = [call_step(t + ': set the new cursor states', reg, 'cursors-controller.set-cursor-states', inp)]
        elif comp in ('core-editing-commands', 'word-operations', 'word-part-operations', 'lines-operations', 'caret-operations',
                      'indentation-actions', 'comment-actions', 'in-place-replace-controller', 'bracket-matching-controller') \
                and not cid.startswith('cursor') and cid not in ('editor.action.selectToBracket', 'editor.action.jumpToBracket',
                                                                  'editor.action.changeTabDisplaySize', 'editor.action.detectIndentation',
                                                                  'editor.action.indentUsingTabs', 'editor.action.indentUsingSpaces'):
            beh = [call_step(t + ': execute its edit command on the focused editor (edit content not modeled)', reg,
                             'code-editor-widget.execute-commands', {'uri': URI, 'edits': [], 'source': cid})]
        elif cid in FIND:
            op, extra = FIND[cid]
            inp = {'uri': URI} if op != 'close-widget' else None
            if extra:
                inp.update(extra)
            beh = [call_step(t, reg, 'find-controller.' + op, inp)]
        elif cid in FOLD:
            beh = [call_step(t + ' (as ' + FOLD[cid] + ')', reg, 'folding-controller.run-folding-action',
                             {'uri': URI, 'action': FOLD[cid], 'line': 1})]
        elif cid.startswith('editor.foldLevel') or cid in ('editor.foldAllBlockComments', 'editor.foldAllMarkerRegions', 'editor.foldAllExcept'):
            beh = [call_step(t + ' (modeled as fold-all)', reg, 'folding-controller.run-folding-action', {'uri': URI, 'action': 'fold-all', 'line': 1})]
        elif cid in ('editor.unfoldAllMarkerRegions', 'editor.unfoldAllExcept'):
            beh = [call_step(t + ' (modeled as unfold-all)', reg, 'folding-controller.run-folding-action', {'uri': URI, 'action': 'unfold-all', 'line': 1})]
        elif cid in SUGGEST:
            op = SUGGEST[cid]
            beh = [call_step(t, reg, ('suggest-model.cancel' if op == 'cancel' else 'suggest-controller.' + op),
                             None if op == 'cancel' else {'uri': URI})]
        elif cid in GOTO:
            k, rpc, extra = GOTO[cid]
            inp = {'uri': URI, 'kind': k, 'rpc': rpc}
            inp.update(extra)
            beh = [call_step(t, reg, 'symbol-navigation-action.run', inp)]
        elif cid in CODEACTION:
            only, aa, msg = CODEACTION[cid]
            beh = [call_step(t, reg, 'code-action-controller.manual-trigger',
                             {'uri': URI, 'only': only, 'auto_apply': aa, 'not_available_message': msg})]
        elif cid in ('editor.action.formatSelection', 'editor.action.format'):
            beh = [call_step(t + ' (selection: line 1)', reg, 'format.format-document-ranges-with-selected-provider',
                             {'resource': URI, 'ranges': [{'start_line': 1, 'start_column': 1, 'end_line': 1, 'end_column': 2}]})]
        elif cid == 'editor.action.showHover':
            beh = [call_step(t, reg, 'content-hover-controller.show-or-focus-hover', {'uri': URI})]
        elif cid == 'editor.action.hideHover':
            beh = [call_step(t, reg, 'content-hover-controller.hide', None)]
        elif cid == 'editor.action.rename':
            beh = [call_step(t, reg, 'rename-controller.run', {'uri': URI})]
        elif cid == 'closeReferenceSearch':
            beh = [call_step(t, reg, 'references-controller.close-widget', None)]
        elif cid == 'leaveEditorMessage':
            beh = [call_step(t, reg, 'message-controller.close-message', None)]
        elif cid == 'editor.cancelOperation':
            beh = [call_step(t, reg, 'editor-cancellation-tokens.cancel', None)]
        elif cid == 'editor.action.inlineSuggest.snooze':
            beh = [call_step(t, reg, 'inline-completions-service.snooze', {'duration_ms': 300000})]
        elif cid == 'editor.action.inlineSuggest.cancelSnooze':
            beh = [call_step(t, reg, 'inline-completions-service.cancel-snooze', None)]
        elif cid in ('cursorUndo', 'cursorRedo'):
            beh = [call_step(t, reg, 'cursors-controller.set-cursor-states', {'source': cid})]
        if beh:
            iface['behavior'] = beh
            scenario_groups.setdefault(comp, []).append(cid)
        else:
            iface['summary'] += '; UI or view state only, effect not modeled'
        gen_ifaces.append(iface)

# core-only commands not in the inventory
for cid, tgt in [('type', 'core-editing-commands.cmd-type'), ('undo', 'core-editing-commands.cmd-undo'), ('redo', 'core-editing-commands.cmd-redo')]:
    registry[cid] = {'target': tgt, 'kind': 'editor', 'writable': False}

# ---------- contributions ----------
contribs = []
CLASSCOMP = {'CommonFindController': 'find-controller', 'FindController': 'find-controller'}
for e in inv:
    if e['kind'] != 'workbench-contribution':
        continue
    rel = e['file'][len('src/vs/editor/'):]
    if rel.startswith('standalone/'):
        skip(e, STANDALONE_REASON); continue
    text = lines_of(e['file'])[e['line'] - 1]
    m = re.search(r'EditorContributionInstantiation\.(\w+)', text)
    mode = {'Eager': 'eager', 'AfterFirstRender': 'after-first-render', 'BeforeFirstInteraction': 'before-first-interaction',
            'Eventually': 'eventually', 'Lazy': 'lazy'}[m.group(1)]
    cls = e['name']
    m2 = re.search(r'\((\w+)\.hot\)|\(\(\)=>(\w+)\)', cls)
    if m2:
        cls = m2.group(1) or m2.group(2)
    comp = CLASSCOMP.get(cls, kebab(cls))
    reg = '%s:%d' % (e['file'], e['line'])
    add_src(comp, reg)
    # constructor line
    srcs = [reg]
    ctor = None
    for ff in [e['file']]:
        ls = lines_of(ff)
        for i, l in enumerate(ls):
            if re.search(r'class %s\b' % re.escape(cls), l):
                for j in range(i, min(i + 120, len(ls))):
                    if 'constructor(' in ls[j]:
                        ctor = '%s:%d' % (ff, j + 1); break
                break
    if ctor:
        srcs.append(ctor)
    contribs.append({'id': cls, 'component': comp, 'mode': mode})
    gen_ifaces.append({'component': comp, 'name': 'construct', 'kind': 'function',
                       'summary': '%s constructor: the editor contribution is instantiated (%s)' % (cls, mode),
                       'sources': srcs, 'attributes': {'contribution': cls, 'instantiation': mode}})

# ---------- services ----------
OWNED_SVC = {
 'IInlineCompletionsService': ('inline-completions-service', 'src/vs/editor/browser/services/inlineCompletionsService.ts:176'),
 'IDiffProviderFactoryService': ('worker-based-diff-provider-factory-service', 'src/vs/editor/browser/widget/diffEditor/diffProviderFactoryService.ts:42'),
 'ILanguageConfigurationService': ('language-configuration-service', None),
 'IEditorWorkerService': ('editor-worker-service', None),
 'ILanguageFeatureDebounceService': ('language-feature-debounce-service', 'src/vs/editor/common/services/languageFeatureDebounce.ts:165'),
 'ILanguageFeaturesService': ('language-features-service', None),
 'IMarkerDecorationsService': ('marker-decorations-service', 'src/vs/editor/common/services/markerDecorationsService.ts'),
 'ISemanticTokensStylingService': ('semantic-tokens-styling-service', 'src/vs/editor/common/services/semanticTokensStylingService.ts:41'),
 'ITextResourceConfigurationService': ('text-resource-configuration-service', 'src/vs/editor/common/services/textResourceConfigurationService.ts'),
 'ITreeViewsDnDService': ('tree-views-dnd-service', 'src/vs/editor/common/services/treeViewsDndService.ts:13'),
 'ICodeLensCache': ('code-lens-cache', 'src/vs/editor/contrib/codelens/browser/codeLensCache.ts:132'),
 'IOutlineModelService': ('outline-model-service', 'src/vs/editor/contrib/documentSymbols/browser/outlineModel.ts:497'),
 'IEditorCancellationTokens': ('editor-cancellation-tokens', 'src/vs/editor/contrib/editorState/browser/keybindingCancellation.ts:28'),
 'IMarkerNavigationService': ('marker-navigation-service', 'src/vs/editor/contrib/gotoError/browser/markerNavigationService.ts:254'),
 'ISymbolNavigationService': ('symbol-navigation-service', None),
 'IInlayHintsCache': ('inlay-hints-cache', 'src/vs/editor/contrib/inlayHints/browser/inlayHintsController.ts:66'),
 'IPeekViewService': ('peek-view-service', 'src/vs/editor/contrib/peekView/browser/peekView.ts:37'),
 'ISuggestMemoryService': ('suggest-memory-service', None),
}
OTHER_SVC = {
 'IBulkEditService': 'workbench-contribs (BulkEditService, src/vs/workbench/contrib/bulkEdit/browser/bulkEditService.ts:330)',
 'ICodeEditorService': 'workbench-shell (CodeEditorService, src/vs/workbench/services/editor/browser/codeEditorService.ts:116)',
 'IRenameSymbolTrackerService': 'workbench-contribs (RenameSymbolTrackerService, src/vs/workbench/contrib/inlineCompletions/browser/renameSymbolTrackerService.ts:316)',
 'ILanguageService': 'workbench-shell (WorkbenchLanguageService, src/vs/workbench/services/language/common/languageService.ts:372)',
 'IModelService': 'workbench-shell (WorkbenchModelService, src/vs/workbench/services/model/common/modelService.ts:35)',
 'ITextModelService': 'workbench-shell (TextModelResolverService, src/vs/workbench/services/textmodelResolver/common/textModelResolverService.ts:279)',
 'ITextResourcePropertiesService': 'workbench-shell (TextResourcePropertiesService, src/vs/workbench/services/textresourceProperties/common/textResourcePropertiesService.ts:57)',
 'ITreeSitterLibraryService': 'workbench-shell (TreeSitterLibraryService, src/vs/workbench/services/treeSitter/browser/treeSitter.contribution.ts:12)',
 'ITreeSitterThemeService': 'workbench-shell (TreeSitterThemeService, src/vs/workbench/services/treeSitter/browser/treeSitter.contribution.ts:13)',
}
svc_narrative = []
for e in inv:
    if e['kind'] != 'service':
        continue
    if e['name'] == 'IStandaloneThemeService':
        skip(e, STANDALONE_REASON); continue
    if e['name'] in OTHER_SVC:
        skip(e, 'another area owns it: the registerSingleton implementation belongs to ' + OTHER_SVC[e['name']]); continue
    comp, regline = OWNED_SVC[e['name']]
    add_src(comp, '%s:%d' % (e['file'], e['line']))
    if regline:
        add_src(comp, regline)
    svc_narrative.append({'component': comp, 'title': 'createDecorator(%s): the service id, implemented by %s' % (e['name'], comp), 'source': '%s:%d' % (e['file'], e['line'])})

for e in inv:
    if e['kind'] == 'process-main' and e['name'] == 'src/vs/editor/editor.main':
        skip(e, 'not an entry point: the Monaco editor standalone ESM entry, not loaded by the workbench')

# ---------- assemble components ----------
existing = {c['id']: c for c in core['components']}
SUMMARY = {
 'diff-editor-actions': 'Diff editor actions (collapse/show unchanged regions, revert hunk, switch side, accessible diff viewer).',
 'selection-anchor-controller': 'Selection anchor (set, go to, select from anchor, cancel).',
 'bracket-matching-controller': 'Bracket matching highlights and bracket jump/select/remove.',
 'caret-operations': 'Move caret left/right and transpose letters.',
 'clipboard-actions': 'Copy with syntax highlighting.',
 'code-lens-model': 'getCodeLensModel and the _executeCodeLensProvider API command.',
 'code-lens-contribution': 'Code lens: computes lenses after a debounce and shows them.',
 'color-detector': 'Document colors: detector contribution and the color API commands.',
 'comment-actions': 'Line and block comment actions.',
 'context-menu-controller': 'The editor context menu.',
 'cursor-undo-redo-controller': 'Undo/redo of cursor positions.',
 'outline-model-service': 'Document symbol outline models (cached) and _executeDocumentSymbolProvider.',
 'copy-paste-controller': 'Paste with providers (paste as, paste as text).',
 'drop-into-editor-controller': 'Drop with providers.',
 'editor-cancellation-tokens': 'Cancellation tokens bound to an editor; editor.cancelOperation cancels them.',
 'font-zoom-actions': 'Editor font zoom in/out/reset.',
 'marker-controller': 'Go to next/previous problem (marker navigation widget).',
 'in-place-replace-controller': 'Replace with next/previous value.',
 'indentation-actions': 'Convert indentation, indent using tabs/spaces, detect indentation, reindent.',
 'inlay-hints-controller': 'Inlay hints and _executeInlayHintProvider.',
 'inline-completions-controller': 'Inline suggestions (ghost text) and their commands.',
 'insert-final-new-line-action': 'Insert final new line.',
 'expand-line-selection-action': 'Expand line selection.',
 'lines-operations': 'Line operations: copy/move/sort/delete/join/transform lines.',
 'linked-editing-contribution': 'Linked editing ranges.',
 'link-detector': 'Document links and _executeLinkProvider.',
 'multi-cursor-selection-controller': 'Multi-cursor: add cursors, add selection to next find match, select highlights.',
 'parameter-hints-controller': 'Parameter hints (signature help) and _executeSignatureHelpProvider.',
 'get-semantic-tokens': 'Semantic tokens API commands (legend and tokens).',
 'smart-select-controller': 'Expand/shrink selection and _executeSelectionRangeProvider.',
 'sticky-scroll-controller': 'Sticky scroll.',
 'toggle-tab-focus-mode-action': 'Toggle Tab key moves focus.',
 'force-retokenize-action': 'Developer: force retokenize.',
 'unicode-highlighter': 'Unicode highlighting and its exclusion commands.',
 'word-highlighter-contribution': 'Highlight occurrences of the word at the cursor.',
 'word-operations': 'Word-wise cursor movement and deletion.',
 'word-part-operations': 'Word-part-wise cursor movement and deletion.',
 'inline-completions-service': 'Inline completion snoozing.',
 'worker-based-diff-provider-factory-service': 'Creates worker-based document diff providers for diff editors.',
 'language-feature-debounce-service': 'Per-feature adaptive debounce delays.',
 'marker-decorations-service': 'Squiggle decorations for markers.',
 'semantic-tokens-styling-service': 'Semantic token styling per theme and legend.',
 'text-resource-configuration-service': 'Resource and language scoped editor configuration.',
 'tree-views-dnd-service': 'Drag and drop data for tree views.',
 'code-lens-cache': 'Code lens cache per model.',
 'marker-navigation-service': 'Marker lists for problem navigation.',
 'inlay-hints-cache': 'Inlay hints cache per model.',
 'peek-view-service': 'Peek view registration.',
}
comps = list(core['components'])
for cid_, srcs in comp_sources.items():
    if cid_ in existing:
        c = existing[cid_]
        for s in srcs:
            if s not in c.setdefault('sources', []):
                c['sources'].append(s)
    else:
        nm = cid_
        comps.append({'id': cid_, 'name': nm, 'kind': 'module', 'parent': 'editor', 'sources': srcs,
                      'summary': SUMMARY.get(cid_, 'Editor contribution ' + cid_ + '.')})
        existing[cid_] = comps[-1]
for extra in ['code-lens-cache', 'editor-cancellation-tokens', 'inline-completions-service']:
    pass
# stateful extras
existing['editor-cancellation-tokens']['state'] = {'initial': {'canceled': 0}}
existing['inline-completions-service']['state'] = {'initial': {'snooze_until': 0}}
existing['editor-contribution-registry']['state'] = {'initial': {'editor_commands': registry, 'contributions': contribs}}

# ---------- extra core interfaces needed by routes ----------
extra = yaml.safe_load(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/editor/extra.yaml'))
ifaces = core['interfaces'] + extra['interfaces'] + gen_ifaces

# fill dispatcher targets
editor_targets = sorted({v['target'] for v in registry.values() if v['kind'] == 'editor'})
api_targets = sorted({v['target'] for v in registry.values() if v['kind'] == 'api'})
for i in ifaces:
    if i['component'] == 'editor-command' and i['name'] == 'run-command':
        for st in i['behavior']:
            if 'then' in st:
                for s2 in st['then']:
                    if s2.get('targets') == []:
                        s2['targets'] = api_targets
            if st.get('targets') == []:
                st['targets'] = editor_targets
    if i['component'] == 'code-editor-contributions' and i['name'] == 'instantiate-some':
        def fill(steps):
            for s in steps:
                if s.get('targets') == []:
                    s['targets'] = sorted({c['component'] + '.construct' for c in contribs})
                for k in ('steps', 'then', 'else'):
                    if k in s:
                        fill(s[k])
        fill(i['behavior'])
RPCS = ['provide-hover', 'provide-code-actions', 'provide-definition', 'provide-declaration', 'provide-type-definition',
        'provide-implementation', 'provide-references'] + sorted({v[1] for v in API_RPC.values()})
RPCS = sorted(set(RPCS))
for i in ifaces:
    if i['component'] == 'language-features-service' and i['name'] == 'invoke-providers':
        for st in i['behavior']:
            if 'parallel' in st:
                st['steps'][0]['targets'] = ['ext-host-language-features.' + r for r in RPCS]

# boundary stubs for exthost RPCs
RESP = {
 'provide-completion-items': {'type': 'object', 'properties': {'suggestions': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': {'type': 'object', 'properties': {'label': {'type': 'string', 'examples': ['add']}, 'insert_text': {'type': 'string', 'examples': ['add']}, 'kind': {'type': 'integer', 'examples': [1]}, 'command': {'type': 'string', 'examples': ['']}}}}}},
 'provide-hover': {'type': 'object', 'properties': {'contents': {'type': 'array', 'items': {'type': 'string', 'examples': ['function add(a: number, b: number): number']}}}},
 'provide-code-actions': {'type': 'object', 'properties': {'actions': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': {'type': 'object', 'properties': {'title': {'type': 'string', 'examples': ['Add missing semicolon']}, 'kind': {'type': 'string', 'examples': ['quickfix']}, 'edits': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': {'type': 'object', 'properties': {'type': {'type': 'string', 'const': 'text'}, 'op': {'type': 'string', 'const': 'edit'}, 'needs_confirmation': {'type': 'boolean', 'const': False}, 'resource': {'type': 'string', 'examples': ['file:///work/app/src/main.ts']}, 'text': {'type': 'string', 'examples': [';']}}}}, 'command': {'type': 'string', 'examples': ['']}}}}}},
 'provide-document-formatting-edits': {'type': 'object', 'properties': {'edits': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': {'type': 'object', 'properties': {'range': {'type': 'object', 'properties': {'start_line': {'type': 'integer', 'const': 2}, 'start_column': {'type': 'integer', 'const': 23}, 'end_line': {'type': 'integer', 'const': 2}, 'end_column': {'type': 'integer', 'const': 23}}}, 'text': {'type': 'string', 'const': ';'}}}}}},
 'provide-document-range-formatting-edits': {'type': 'object', 'properties': {'edits': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': {'type': 'object', 'properties': {'range': {'type': 'object', 'properties': {'start_line': {'type': 'integer', 'const': 2}, 'start_column': {'type': 'integer', 'const': 23}, 'end_line': {'type': 'integer', 'const': 2}, 'end_column': {'type': 'integer', 'const': 23}}}, 'text': {'type': 'string', 'const': ';'}}}}}},
 'resolve-rename-location': {'type': 'object', 'properties': {'text': {'type': 'string', 'examples': ['add']}, 'reject_reason': {'type': 'string', 'default': ''}}},
 'provide-rename-edits': {'type': 'object', 'properties': {'edits': {'type': 'array', 'minItems': 1, 'maxItems': 2, 'items': {'type': 'object', 'properties': {'type': {'type': 'string', 'const': 'text'}, 'op': {'type': 'string', 'const': 'edit'}, 'needs_confirmation': {'type': 'boolean', 'const': False}, 'resource': {'type': 'string', 'examples': ['file:///work/app/src/main.ts']}, 'text': {'type': 'string', 'examples': ['sum']}}}}, 'reject_reason': {'type': 'string', 'default': ''}}},
 'provide-folding-ranges': {'type': 'object', 'properties': {'ranges': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': {'type': 'object', 'properties': {'start': {'type': 'integer', 'const': 1}, 'end': {'type': 'integer', 'const': 2}}}}}},
}
LOC = {'type': 'object', 'properties': {'locations': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': {'type': 'object', 'properties': {'uri': {'type': 'string', 'examples': ['file:///work/app/src/util.ts']}, 'range': {'$ref': 'EditorRange'}}}}}}
for r in ['provide-definition', 'provide-declaration', 'provide-type-definition', 'provide-implementation', 'provide-references']:
    RESP[r] = LOC
allrpcs = sorted(set(RPCS) | set(RESP.keys()))
for r in allrpcs:
    req = {'type': 'object', 'required': ['handle', 'resource'], 'properties': {'handle': {'type': 'integer'}, 'resource': {'type': 'string'}, 'token': {'type': 'object', 'properties': {'canceled': {'type': 'boolean'}}}}}
    if r == 'provide-rename-edits':
        req['properties']['new_name'] = {'type': 'string'}
    st = {'component': 'ext-host-language-features', 'name': r, 'kind': 'rpc', 'attributes': {'boundary': True, 'owner': 'exthost', 'shape': 'ExtHostLanguageFeaturesShape'},
          'request': req, 'response': RESP.get(r, {'type': 'object'}), 'latency_ms': {'min': 2, 'max': 30}}
    ifaces.append(st)
for b in extra['boundary']:
    ifaces.append(b)

# narrative flow for services
flows = core['flows'] + extra['flows']
flows.append({'id': 'editor-service-registrations', 'name': 'Editor services registered with the instantiation service',
              'description': 'registerSingleton registrations of the editor services this area implements; each is created on first use (Delayed) or at startup (Eager).',
              'steps': svc_narrative, 'sources': ['src/vs/editor/browser/services/contribution.ts:13']})

# ---------- generated scenarios ----------
SEED = scen['seed']
def dmerge(a, b):
    a = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            a[k] = dmerge(a[k], v)
        else:
            a[k] = copy.deepcopy(v)
    return a
FIX_FOR = {'main': 'editor-main-open', 'dirty': 'editor-dirty', 'providers': 'editor-ts-providers'}
scenarios = []
for s in scen['scenarios']:
    s = copy.deepcopy(s)
    seeds = s.pop('x_seed', [])
    fx = list(s.get('fixtures', []))
    if 'main' in seeds:
        fx = [f for f in fx if f != 'one-window-folder']
        fx.insert(0, 'editor-main-open')
    if 'dirty' in seeds:
        fx.append('editor-dirty')
    if 'providers' in seeds:
        fx.append('editor-ts-providers')
    if not seeds:
        fx.append('editor-seed')
    s['fixtures'] = fx
    scenarios.append(s)
for comp, ids in sorted(scenario_groups.items()):
    if comp == 'core':
        continue
    for chunk_i in range(0, len(ids), 30):
        chunk = ids[chunk_i:chunk_i + 30]
        sid = 'editor-run-command-%s%s' % (comp, '' if chunk_i == 0 else '-%d' % (chunk_i // 30 + 1))
        steps = [{'flow': 'editor-run-command', 'as': 's%d' % n, 'input': {'command_id': cid}} for n, cid in enumerate(chunk)]
        exp = ["steps.s%d.result.ok && steps.s%d.result.value.ran" % (n, n) for n in range(len(chunk))]
        exp = [' && '.join(exp)]
        exp.append("trace.filter(e, e.type == 'call.start' && e.interface.startsWith('%s.cmd-')).size() >= %d" % (comp, len(chunk)))
        scenarios.append({'id': sid[:64], 'name': 'Every modeled %s command runs on the focused editor' % comp,
                          'fixtures': ['editor-main-open', 'editor-ts-providers'], 'steps': steps, 'expect': exp})

cmdreg = {cid: {'handler': (v['target'] if v['kind'] == 'api' else 'editor-command.run-command')} for cid, v in sorted(registry.items())}
fixtures = [
    {'id': 'editor-seed', 'summary': 'Editor area seed: the clean text model of src/main.ts (as files-search-scm-seed resolves it) and the editor commands registered in the CommandsRegistry (EditorCommand handlers run through editor-command.run-command; API commands name their cmd-* interface).',
     'state': {'commands-registry': {'commands': cmdreg}, 'text-model': copy.deepcopy(SEED['main']['text-model@w1'])}},
    {'id': 'editor-main-open', 'summary': 'one-window-folder with src/main.ts open and focused in a code editor in w1 (clean text model, version 1, cursor at 1:1).',
     'extends': ['one-window-folder', 'editor-seed'], 'state': copy.deepcopy(SEED['main'])},
    {'id': 'editor-dirty', 'summary': 'dirty-editor seen from the editor: the text model of src/main.ts at version 2 with the unsaved value, focused in w1.',
     'extends': ['dirty-editor', 'editor-seed'], 'state': copy.deepcopy(SEED['dirty'])},
    {'id': 'editor-ts-providers', 'summary': 'Language feature providers of vscode.typescript-language-features registered for typescript in w1 (completion, hover, code actions, formatting, definition, references, rename, folding, code lens).',
     'state': copy.deepcopy(SEED['providers'])},
]

def fixon(x):
    if isinstance(x, dict):
        return {('on' if k is True else k): fixon(v) for k, v in x.items()}
    if isinstance(x, list):
        return [fixon(v) for v in x]
    return x
doc = {'schema_version': 1, 'id': 'vscode', 'configs': core['configs'], 'components': comps, 'schemas': core['schemas'],
       'interfaces': ifaces, 'flows': flows, 'scenarios': scenarios, 'fixtures': fixtures}
doc = fixon(doc)

class D(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True
open(OUT + 'fragments/editor.yaml', 'w').write('# Editor area fragment (src/vs/editor/**), generated from code at 1.144.0.\n' + yaml.dump(doc, Dumper=D, sort_keys=False, width=200, allow_unicode=True))
json.dump(skips, open(OUT + 'skips/editor.json', 'w'), indent=1)
json.dump({'registry': len(registry), 'groups': {k: len(v) for k, v in scenario_groups.items()}, 'skips': len(skips)}, sys.stdout)

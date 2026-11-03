#!/usr/bin/env python3
"""Generate examples/vscode/fragments/files-search-scm.yaml and skips/files-search-scm.json."""
import json, re, sys, yaml

CODE = '/home/lbethay/.cache/mosaic-bench/vscode-1.144.0'
OUT = '/home/lbethay/workplace/mosaic/examples/vscode'
GEN = f'{OUT}/gen/files-search-scm'
INV = [e for e in json.load(open(f'{OUT}/inventory.json'))['entries'] if e.get('area') == 'files-search-scm']

def slug(cmd):
    s = re.sub(r'[._]', '-', cmd).lower()
    s = re.sub(r'[^a-z0-9-]', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return ('cmd-' + s)[:64].rstrip('-')

file_lines = {}
def nlines(path):
    if path not in file_lines:
        file_lines[path] = len(open(f'{CODE}/{path}').read().split('\n'))
    return file_lines[path]

entry_lines = {}
for e in INV:
    entry_lines.setdefault(e['file'], []).append(e['line'])
for v in entry_lines.values():
    v.sort()

def cite(e, span=10):
    nxt = [l for l in entry_lines[e['file']] if l > e['line']]
    end = min(e['line'] + span, (nxt[0] - 1) if nxt else 10**9, nlines(e['file']))
    if end <= e['line']:
        return f"{e['file']}:{e['line']}"
    return f"{e['file']}:{e['line']}-{end}"

UI = 'UI toggle: no state beyond the layout'
NAV = 'UI navigation/focus: moves focus or the cursor between existing items, no state beyond the view'
DEV = 'developer or internal command with no user-visible behavior'
FILTER = 'UI toggle: no state beyond the layout (Problems view filter presentation only)'

# command -> (component, template, arg, summary) or ('SKIP', reason)
O = 'editor-service.open-editor'
C = {}
def m(cmd, comp, tmpl, arg=None, summary=None):
    C[cmd] = (comp, tmpl, arg, summary)
def k(cmd, reason):
    C[cmd] = ('SKIP', reason)

# ---- files: fileActions.contribution.ts ----
m('workbench.files.action.compareFileWith', 'file-actions', 'open', {'diff': True}, 'Compare the active file with a picked file in a diff editor.')
k('workbench.files.action.focusFilesExplorer', NAV)
m('workbench.files.action.showActiveFileInExplorer', 'file-actions', 'call', ('explorer-service.select', {'resource': '= input.resource'}), 'Reveal the active file in the explorer.')
m('workbench.files.action.compareWithClipboard', 'file-actions', 'open', {'diff': True}, 'Compare the active file with the clipboard contents.')
m('workbench.files.action.compareNewUntitledTextFiles', 'file-actions', 'open', {'diff': True}, 'Open a diff of two new untitled text files.')
m('workbench.action.toggleAutoSave', 'file-actions', 'call', ('configuration-service.update-value', {'key': 'files.autoSave', 'value': "= config['files-auto-save'] == 'off' ? 'afterDelay' : 'off'"}), 'Toggle files.autoSave between off and afterDelay in user settings.')
m('workbench.action.files.showOpenedFileInNewWindow', 'file-actions', 'call', ('host-service.open-window', {'resource': '= input.resource', 'force_new_window': True}), 'Open the active file in a new window.')
for c, v in [('setActiveEditorReadonlyInSession', 'true'), ('setActiveEditorWriteableInSession', 'false'), ('toggleActiveEditorReadonlyInSession', 'toggle'), ('resetActiveEditorReadonlyInSession', 'reset')]:
    m('workbench.action.files.' + c, 'file-actions', 'call', ('files-configuration-service.update-readonly', {'resource': '= input.resource', 'readonly': v}), f'Set the active editor readonly state in this session ({v}).')
m('_files.windowOpen', 'file-actions', 'call', ('host-service.open-window', {'resource': '= input.resource', 'force_new_window': False}), 'Internal: open a window for the given URIs.')
m('_files.newWindow', 'file-actions', 'call', ('host-service.open-window', {'resource': '', 'force_new_window': True}), 'Internal: open a new empty window.')
m('renameFile', 'file-actions', 'call', ('file-actions.rename-handler', {'resource': '= input.resource', 'new_name': 'math.ts'}), 'Rename the selected explorer item (renameHandler).')
m('moveFileToTrash', 'file-actions', 'call', ('file-actions.delete-files', {'resources': '= [input.resource]', 'use_trash': True}), 'Move the selected explorer items to the trash (moveFileToTrashHandler).')
m('deleteFile', 'file-actions', 'call', ('file-actions.delete-files', {'resources': '= [input.resource]', 'use_trash': False}), 'Delete the selected explorer items permanently (deleteFileHandler).')
m('filesExplorer.cut', 'file-actions', 'cut', None, 'Cut the selected explorer items (cutFileHandler).')
m('filesExplorer.copy', 'file-actions', 'copy', None, 'Copy the selected explorer items (copyFileHandler).')
m('filesExplorer.paste', 'file-actions', 'call', ('file-actions.paste-file-handler', {'target_folder': 'file:///work/app/src'}), 'Paste copied or cut items into the selected folder (pasteFileHandler).')
m('filesExplorer.cancelCut', 'file-actions', 'call', ('explorer-service.set-to-copy', {'resources': [], 'cut': False}), 'Cancel a pending cut.')
m('filesExplorer.openFilePreserveFocus', 'file-actions', 'open', {'preserve_focus': True}, 'Open the selected file keeping focus in the explorer.')
# fileActions.ts
m('explorer.newFile', 'file-actions', 'call', ('file-actions.open-explorer-and-create', {'folder': 'file:///work/app/src', 'name': 'new.ts', 'is_folder': False}), 'New File in the explorer (openExplorerAndCreate, file).')
m('explorer.newFolder', 'file-actions', 'call', ('file-actions.open-explorer-and-create', {'folder': 'file:///work/app', 'name': 'lib', 'is_folder': True}), 'New Folder in the explorer (openExplorerAndCreate, folder).')
m('explorer.download', 'file-actions', 'call', ('file-dialog-service.pick-file-to-save', {'default_uri': '= input.resource'}), 'Download the selected explorer items (asks for a target).')
m('explorer.upload', 'file-actions', 'call', ('file-dialog-service.pick-file-to-save', {'default_uri': 'file:///work/app'}), 'Upload files into the selected folder (web).')
# fileCommands.ts
m('explorer.openToSide', 'file-commands', 'open', {'side_by_side': True}, 'Open the selected explorer file to the side.')
m('explorer.openAndPassFocus', 'file-commands', 'open', {}, 'Open the selected explorer file and focus it.')
m('workbench.files.action.compareWithSaved', 'file-commands', 'open', {'diff': True, 'original_scheme': 'showModifications'}, 'Compare the active file with its saved version.')
m('selectForCompare', 'file-commands', 'select-compare', None, 'Remember a resource to compare.')
m('compareSelected', 'file-commands', 'open', {'diff': True}, 'Compare the selected resources.')
m('compareFiles', 'file-commands', 'open', {'diff': True, 'compare_with_selected': True}, 'Compare the resource with the one selected for compare.')
for c in ['copyFilePath', 'copyRelativeFilePath', 'workbench.action.files.copyPathOfActiveFile']:
    m(c, 'file-commands', 'clip', None, 'Copy the path of the selected or active file to the clipboard.')
m('revealInExplorer', 'file-commands', 'call', ('explorer-service.select', {'resource': '= input.resource'}), 'Reveal the resource in the explorer.')
m('explorer.openWith', 'file-commands', 'open', {'override': 'pick'}, 'Open the resource with a picked editor.')
m('workbench.action.files.save', 'file-commands', 'save', {'reason': 'explicit', 'force': True}, 'Save the active editor (force, explicit).')
m('workbench.action.files.saveWithoutFormatting', 'file-commands', 'save', {'reason': 'explicit', 'force': True, 'skip_save_participants': True}, 'Save without running save participants.')
m('workbench.action.files.saveAs', 'file-commands', 'call', ('editor-service.save', {'resource': '= input.resource', 'reason': 'explicit', 'force': False, 'save_as': True, 'skip_save_participants': False}), 'Save the active editor as another file (editorService.save with saveAs).')
m('saveAll', 'file-commands', 'save-all', None, 'Save the dirty editors of all groups.')
m('workbench.files.action.saveAllInGroup', 'file-commands', 'save-all', None, 'Save the dirty editors of a group.')
m('workbench.action.files.saveFiles', 'file-commands', 'save-all', None, 'Save all files (editorService.saveAll without untitled).')
m('workbench.action.files.revert', 'file-commands', 'call', ('text-file-service.revert', {'resource': '= input.resource', 'options': {'force': True}}), 'Revert the active editor (force).')
m('removeRootFolder', 'file-commands', 'call', ('workspace-editing-service.remove-folders', {'folders': '= [input.resource]'}), 'Remove a root folder from the workspace.')
for c in ['previousCompressedFolder', 'nextCompressedFolder', 'firstCompressedFolder', 'lastCompressedFolder']:
    k(c, NAV)
m('workbench.action.files.newUntitledFile', 'file-commands', 'new-untitled', None, 'New untitled text file.')
m('NEW_FILE_COMMAND_ID', 'file-commands', 'new-file', None, "workbench.action.files.newFile: ask for a path, create the file (overwrite) and open it.")
# explorerView.ts
m('workbench.files.action.createFileFromExplorer', 'explorer-view', 'exec', 'explorer.newFile', 'Explorer title action: run explorer.newFile.')
m('workbench.files.action.createFolderFromExplorer', 'explorer-view', 'exec', 'explorer.newFolder', 'Explorer title action: run explorer.newFolder.')
m('workbench.files.action.refreshFilesExplorer', 'explorer-view', 'call', ('explorer-service.refresh', {}), 'Refresh the explorer.')
k('workbench.files.action.collapseExplorerFolders', UI)
# openEditorsView.ts
k('workbench.action.toggleEditorGroupLayout', UI)
m('workbench.action.files.saveAll', 'open-editors-view', 'save-all', None, 'Open Editors title action: save all.')
m('openEditors.closeAll', 'open-editors-view', 'exec', 'workbench.action.closeAllEditors', 'Open Editors title action: close all editors.')
m('openEditors.newUntitledFile', 'open-editors-view', 'exec', 'workbench.action.files.newUntitledFile', 'Open Editors title action: new untitled file.')
# electron-browser
m('revealFileInOS', 'electron-file-actions', 'call', ('native-host-service.show-item-in-folder', {'path': '= input.resource'}), 'Reveal the selected file in the OS file manager.')
m('workbench.action.files.revealActiveFileInWindows', 'electron-file-actions', 'call', ('native-host-service.show-item-in-folder', {'path': '= input.resource'}), 'Reveal the active file in the OS file manager.')

# ---- markers ----
m('problems.action.open', 'markers-actions', 'call', ('views-service.open-view', {'view_id': 'workbench.panel.markers.view', 'focus': True}), 'Open the selected problem in an editor.')
m('problems.action.openToSide', 'markers-actions', 'open', {'side_by_side': True}, 'Open the selected problem to the side.')
m('workbench.action.showErrorsWarnings', 'markers-actions', 'call', ('views-service.open-view', {'view_id': 'workbench.panel.markers.view', 'focus': True}), 'Show the Problems view.')
m('problems.action.showQuickFixes', 'markers-actions', 'exec', 'editor.action.quickFix', 'Show quick fixes for the selected problem.')
k('workbench.actions.table.${Markers.MARKERS_VIEW_ID}.viewAsTree', UI)
k('workbench.actions.table.${Markers.MARKERS_VIEW_ID}.viewAsTable', UI)
for c in ['toggleErrors', 'toggleWarnings', 'toggleInfos', 'toggleActiveFile', 'toggleExcludedFiles']:
    k('workbench.actions.${Markers.MARKERS_VIEW_ID}.' + c, FILTER)
k('workbench.action.problems.focus', NAV)
for c in ['problems.action.copy', 'problems.action.copyMessage', 'problems.action.copyRelatedInformationMessage']:
    m(c, 'markers-actions', 'clip', None, 'Copy the selected problem (or its message) to the clipboard.')
for c in ['problems.action.focusProblemsFromFilter', 'problems.action.focusFilter']:
    k(c, NAV)
for c in ['problems.action.showMultilineMessage', 'problems.action.showSinglelineMessage', 'problems.action.clearFilterText', 'workbench.actions.treeView.${Markers.MARKERS_VIEW_ID}.collapseAll', 'workbench.actions.view.toggleProblems']:
    k(c, UI)

# ---- merge editor ----
m('merge.openResult', 'merge-editor-actions', 'open', {}, 'Open the merge result file in a text editor.')
k('merge.mixedLayout', UI); k('merge.columnLayout', UI)
m('_open.mergeEditor', 'merge-editor-actions', 'open', {'merge': True}, 'Internal: open a merge editor for base/input1/input2/result.')
m('merge.openBaseEditor', 'merge-editor-actions', 'open', {'base': True}, 'Open the merge base in an editor.')
for c in ['merge.showNonConflictingChanges', 'merge.showBase', 'merge.showBaseTop', 'merge.showBaseCenter']:
    k(c, UI)
k('merge.goToNextUnhandledConflict', NAV); k('merge.goToPreviousUnhandledConflict', NAV)
m('merge.toggleActiveConflictInput1', 'merge-editor-actions', 'merge-accept', 'input1', 'Toggle input 1 of the active conflict in the result.')
m('merge.toggleActiveConflictInput2', 'merge-editor-actions', 'merge-accept', 'input2', 'Toggle input 2 of the active conflict in the result.')
m('mergeEditor.compareInput1WithBase', 'merge-editor-actions', 'open', {'diff': True}, 'Compare input 1 with the base.')
m('mergeEditor.compareInput2WithBase', 'merge-editor-actions', 'open', {'diff': True}, 'Compare input 2 with the base.')
m('merge.acceptAllInput1', 'merge-editor-actions', 'merge-accept-all', 'input1', 'Accept all changes from input 1.')
m('merge.acceptAllInput2', 'merge-editor-actions', 'merge-accept-all', 'input2', 'Accept all changes from input 2.')
m('mergeEditor.resetResultToBaseAndAutoMerge', 'merge-editor-actions', 'merge-reset', None, 'Reset the result to the base and re-run the auto merge.')
m('mergeEditor.acceptMerge', 'merge-editor-actions', 'call', ('merge-editor-actions.accept-merge', {'result_uri': '= input.resource'}), 'Complete the merge (AcceptMerge).')
m('mergeEditor.resetCloseWithConflictsChoice', 'merge-editor-actions', 'call', ('storage-service.remove', {'key': 'mergeEditorCloseWithConflicts', 'scope': 'profile'}), 'Reset the remembered close-with-conflicts choice.')
m('mergeEditor.acceptAllCombination', 'merge-editor-actions', 'merge-accept-all', 'combination', 'Accept all non-conflicting combinations.')
k('mergeEditor.toggleBetweenInputs', NAV)
for c in ['merge.dev.copyContentsJson', 'merge.dev.saveContentsToFolder', 'merge.dev.loadContentsFromFolder', 'merge.dev.openContentsJson', 'merge.dev.openSelectionInTemporaryMergeEditor']:
    k(c, DEV + ' (merge editor developer diagnostics)')

# ---- multi diff ----
m('GoToFileAction', 'multi-diff-editor-actions', 'open', {}, 'multiDiffEditor.goToFile: open the focused file of the multi diff editor.')
k('multiDiffEditor.goToNextChange', NAV); k('multiDiffEditor.goToPreviousChange', NAV)
k('multiDiffEditor.focusFileList', NAV)
for c in ['multiDiffEditor.toggleFileList', 'ViewFileListAsTreeAction', 'ViewFileListAsListAction', 'PositionFileListLeftAction', 'PositionFileListRightAction', 'CollapseAllAction', 'ExpandAllAction']:
    k(c, UI)
k('multiDiffEditor.openLayoutDebug', DEV)
k('_workbench.openScmMultiDiffEditor', DEV + ' (_workbench.* internal command)')

# ---- scm ----
m('workbench.scm.action.toggleQuickDiffVisibility.${provider.id}', 'scm-actions', 'call', ('quick-diff-service.toggle-quick-diff-provider-visibility', {'provider_id': 'git'}), 'Toggle the visibility of one quick diff provider (registered per provider).')
for c in ['editor.action.dirtydiff.previous', 'editor.action.dirtydiff.next', 'workbench.action.editor.previousChange', 'workbench.action.editor.nextChange']:
    k(c, NAV)
k('closeQuickDiff', UI); k('toggleQuickDiffWidgetFocus', NAV)
m('scm.acceptInput', 'scm-actions', 'scm-accept', None, 'Accept the SCM input: run the provider acceptInputCommand (e.g. git.commit).')
m('scm.clearValidation', 'scm-actions', 'call', ('scm-service.input-clear-validation', {'repository_id': '= input.repository_id'}), 'Clear the SCM input validation message.')
m('scm.clearInput', 'scm-actions', 'call', ('scm-service.input-set-value', {'repository_id': '= input.repository_id', 'value': '', 'transient': True}), 'Clear the SCM input box.')
for c, d in [('scm.viewNextCommit', 'next'), ('scm.viewPreviousCommit', 'previous'), ('scm.forceViewNextCommit', 'next'), ('scm.forceViewPreviousCommit', 'previous')]:
    m(c, 'scm-actions', 'call', ('scm-service.input-show-history-value', {'repository_id': '= input.repository_id', 'direction': d}), f'Show the {d} commit message from the input history.')
m('scm.openInIntegratedTerminal', 'scm-actions', 'exec', 'openInIntegratedTerminal', 'Open the repository root in the integrated terminal.')
m('scm.openInTerminal', 'scm-actions', 'exec', 'openInTerminal', 'Open the repository root in an external terminal.')
m('scm.setActiveProvider', 'scm-actions', 'call', ('scm-view-service.focus', {'repository_id': '= input.repository_id'}), 'Make a repository the active one.')
for c in ['workbench.scm.action.focusPreviousInput', 'workbench.scm.action.focusNextInput', 'workbench.scm.action.focusPreviousResourceGroup', 'workbench.scm.action.focusNextResourceGroup']:
    k(c, NAV)
m('scm.editor.triggerSetup', 'scm-actions', 'exec', 'workbench.action.chat.triggerSetup', 'Trigger chat setup from the SCM input (commit message generation).')
m('scm.input.triggerSetup', 'scm-actions', 'exec', 'workbench.action.chat.triggerSetup', 'Trigger chat setup from the SCM input widget.')
m('workbench.scm.action.graph.addHistoryItemToChat', 'scm-actions', 'exec', 'workbench.action.chat.attachContext', 'Attach a history item to the chat.')
m('workbench.scm.action.graph.summarizeHistoryItem', 'scm-actions', 'exec', 'workbench.action.chat.open', 'Ask chat to summarize a history item.')
m('workbench.scm.action.graph.addHistoryItemChangeToChat', 'scm-actions', 'exec', 'workbench.action.chat.attachContext', 'Attach a history item change to the chat.')
m('workbench.scm.action.graph.pickRepository', 'scm-actions', 'call', ('scm-view-service.focus', {'repository_id': '= input.repository_id'}), 'Pick the repository shown in the graph.')
m('workbench.scm.action.graph.pickHistoryItemRefs', 'scm-actions', 'call', ('scm-view-service.get-active-repository', {}), 'Pick the history item references shown in the graph.')
k('workbench.scm.action.graph.revealCurrentHistoryItem', NAV)
m('workbench.scm.action.graph.refresh', 'scm-actions', 'call', ('scm-view-service.get-active-repository', {}), 'Refresh the source control graph.')
k('workbench.scm.action.graph.setListViewMode', UI); k('workbench.scm.action.graph.setTreeViewMode', UI)
m('workbench.scm.action.graph.viewChanges', 'scm-actions', 'call', ('multi-diff-source-resolver-service.resolve', {'source': 'scm-history-item:scm0'}), 'Open the changes of a history item in a multi diff editor.')
m('workbench.scm.action.graph.openFile', 'scm-actions', 'open', {}, 'Open a file of a history item.')
k('${actionId}.${historyItemRef.id}', 'UI toggle: no state beyond the layout (context-menu entry registered per history item ref; selects a ref in the graph filter)')
for c in ['SetListViewModeAction', 'SetTreeViewModeAction', 'SetListViewModeNavigationAction', 'SetTreeViewModeNavigationAction', 'RepositorySortByDiscoveryTimeAction', 'RepositorySortByNameAction', 'RepositorySortByPathAction', 'RepositorySingleSelectionModeAction', 'RepositoryMultiSelectionModeAction', 'SetSortByNameAction', 'SetSortByPathAction', 'SetSortByStatusAction', 'workbench.scm.action.collapseAllRepositories', 'workbench.scm.action.expandAllRepositories', 'workbench.scm.action.collapseAll']:
    k(c, UI)

# ---- search ----
m('_executeWorkspaceSymbolProvider', 'search-actions', 'exec', 'vscode.executeWorkspaceSymbolProvider', 'Internal API command: query workspace symbol providers.')
for c in ['search.action.copyMatch', 'search.action.copyPath', 'search.action.copyAll']:
    m(c, 'search-actions', 'clip', None, 'Copy search results to the clipboard.')
m('search.action.getSearchResults', 'search-actions', 'call', ('search-view-model-workbench-service.get-search-results', {}), 'Return the current search results as text.')
m('search.action.restrictSearchToFolder', 'search-actions', 'call', ('search-view.trigger-query-change', {'includes': '= input.resource'}), 'Restrict the search to the selected folder.')
k('search.action.expandRecursively', UI)
m('search.action.excludeFromSearch', 'search-actions', 'call', ('search-view.trigger-query-change', {'excludes': '= input.resource'}), 'Exclude the selected folder from the search.')
m('search.action.excludeFileTypeFromSearch', 'search-actions', 'call', ('search-view.trigger-query-change', {'excludes': '**/*.ts'}), 'Exclude the file type from the search.')
m('search.action.includeFileTypeInSearch', 'search-actions', 'call', ('search-view.trigger-query-change', {'includes': '**/*.ts'}), 'Include only the file type in the search.')
m('search.action.revealInSideBar', 'search-actions', 'call', ('explorer-service.select', {'resource': '= input.resource'}), 'Reveal the search result file in the explorer.')
m('workbench.action.findInFiles', 'search-actions', 'find-in-files', None, 'Find in Files: open the search view with the arguments and run the query.')
m('filesExplorer.findInFolder', 'search-actions', 'call', ('search-view.trigger-query-change', {'includes': '= input.resource'}), 'Find in the selected explorer folder.')
m('filesExplorer.findInWorkspace', 'search-actions', 'call', ('search-view.trigger-query-change', {'includes': ''}), 'Find in the whole workspace.')
k('workbench.action.search.toggleQueryDetails', UI)
k('closeReplaceInFilesWidget', UI)
for c, o in [('toggleSearchCaseSensitive', 'is_case_sensitive'), ('toggleSearchWholeWord', 'is_word_match'), ('toggleSearchRegex', 'is_regex'), ('toggleSearchPreserveCase', 'preserve_case')]:
    m(c, 'search-actions', 'call', ('search-view.set-option', {'option': o}), f'Toggle the search option {o} and re-run the search.')
m('search.action.openResult', 'search-actions', 'open', {}, 'Open the selected search result.')
m('search.action.openResultToSide', 'search-actions', 'open', {'side_by_side': True}, 'Open the selected search result to the side.')
m('addCursorsAtSearchResults', 'search-actions', 'exec', 'editor.action.selectHighlights', 'Add cursors at the search results of the active file.')
for c in ['search.focus.nextInputBox', 'search.focus.previousInputBox', 'search.action.focusSearchFromResults', 'search.action.focusSearchList', 'search.action.focusNextSearchResult', 'search.action.focusPreviousSearchResult']:
    k(c, NAV)
m('workbench.action.toggleSearchOnType', 'search-actions', 'call', ('configuration-service.update-value', {'key': 'search.searchOnType', 'value': False}), 'Toggle search.searchOnType.')
m('workbench.action.replaceInFiles', 'search-actions', 'find-in-files', None, 'Replace in Files: open the search view with replace and run the query.')
m('search.action.remove', 'search-actions', 'call', ('search-model.clear', {}), 'Dismiss the selected search results.')
m('search.action.replace', 'search-actions', 'call', ('search-view.replace-all', {}), 'Replace the selected match.')
m('search.action.replaceAllInFile', 'search-actions', 'call', ('search-view.replace-all', {}), 'Replace all matches in the selected file.')
m('search.action.replaceAllInFolder', 'search-actions', 'call', ('search-view.replace-all', {}), 'Replace all matches in the selected folder.')
m('workbench.action.showAllSymbols', 'search-actions', 'call', ('quick-input-service.quick-access-show', {'prefix': '#'}), 'Go to Symbol in Workspace (quick access #).')
m('workbench.action.quickTextSearch', 'search-actions', 'call', ('quick-input-service.quick-access-show', {'prefix': '%'}), 'Quick text search (quick access %).')
m('search.action.clearHistory', 'search-actions', 'call', ('search-history-service.clear-history', {}), 'Clear the search history.')
m('search.action.cancel', 'search-actions', 'call', ('search-model.clear', {}), 'Cancel the running search.')
m('search.action.refreshSearchResults', 'search-actions', 'call', ('search-view.trigger-query-change', {}), 'Re-run the current search.')
k('search.action.collapseSearchResults', UI); k('search.action.expandSearchResults', UI)
m('search.action.clearSearchResults', 'search-actions', 'call', ('search-view.clear-search-results', {}), 'Clear the search results.')
k('search.action.viewAsTree', UI); k('search.action.viewAsList', UI)
m('search.action.searchWithAI', 'search-actions', 'exec', 'workbench.action.chat.open', 'Search with AI (opens the AI text search).')
m('search.action.replaceAll', 'search-actions', 'call', ('search-view.replace-all', {}), 'Replace All from the search widget (ReplaceAllAction).')
# search editor
m('cleanSearchEditorState', 'search-editor-actions', 'set-se', {'editors': '= state.editors > 0 ? state.editors - 1 : 0'}, 'Internal: clean up a search editor model state.')
m('search.searchEditor.action.deleteFileResults', 'search-editor-actions', 'set-se', {'editors': '= state.editors'}, 'Delete the results of a file in the search editor.')
for c in ['search.action.openNewEditor', 'search.action.openEditor', 'search.action.openNewEditorToSide', 'search.action.openInEditor', 'search.action.openNewEditorFromView']:
    m(c, 'search-editor-actions', 'search-editor-open', None, 'Open a search editor (and run its query).')
m('rerunSearchEditorSearch', 'search-editor-actions', 'search-editor-open', None, 'Re-run the search editor query.')
for c in ['search.action.focusQueryEditorWidget', 'search.action.focusFilesToInclude', 'search.action.focusFilesToExclude']:
    k(c, NAV)
for c, o in [('toggleSearchEditorCaseSensitive', 'is_case_sensitive'), ('toggleSearchEditorWholeWord', 'is_word_match'), ('toggleSearchEditorRegex', 'is_regex'), ('toggleSearchEditorContextLines', 'show_context')]:
    m(c, 'search-editor-actions', 'set-se', {'options': f"= merge(state.options, {{'{o}': !state.options.{o}}})"}, f'Toggle the search editor option {o}.')
m('increaseSearchEditorContextLines', 'search-editor-actions', 'set-se', {'context_lines': '= state.context_lines + 1'}, 'Increase the search editor context lines.')
m('decreaseSearchEditorContextLines', 'search-editor-actions', 'set-se', {'context_lines': '= state.context_lines > 0 ? state.context_lines - 1 : 0'}, 'Decrease the search editor context lines.')
m('selectAllSearchEditorMatches', 'search-editor-actions', 'exec', 'editor.action.selectHighlights', 'Select all matches in the search editor.')

# ---------------------------------------------------------------------------
def behavior(cmd, comp, tmpl, arg, src):
    st = lambda **kw: dict(kw)
    if tmpl == 'open':
        opts = {k2: v for k2, v in (arg or {}).items()}
        return [st(title='Open through the editor service', source=src, call=O, input={'resource': '= input.resource', 'options': opts}), {'return': {'handled': True}}]
    if tmpl == 'exec':
        return [st(title=f'Run {arg}', source=src, call='command-service.execute-command', input={'command_id': arg, 'args': '= input.args'}), {'return': {'handled': True}}]
    if tmpl == 'call':
        iface, inp = arg
        return [st(title=f'Call {iface}', source=src, call=iface, input=inp, **{'as': 'res'}), {'return': {'handled': True, 'result': '= vars.res.value'}}]
    if tmpl == 'clip':
        return [st(title='Write to the clipboard', source=src, call='clipboard-service.write-text', input={'text': '= input.resource'}), {'return': {'handled': True}}]
    if tmpl == 'cut' or tmpl == 'copy':
        cut = tmpl == 'cut'
        return [st(title=('Cut' if cut else 'Copy') + ' the selected items', source=src, call='explorer-service.set-to-copy', input={'resources': '= [input.resource]', 'cut': cut}),
                {'set': {'state.paste_should_move': cut}}, {'return': {'handled': True}}]
    if tmpl == 'select-compare':
        return [st(title='Remember the resource for a later compare', source=src, set={'state.resource_to_compare': '= input.resource'}), {'return': {'handled': True}}]
    if tmpl == 'save':
        inp = {'resource': '= input.resource', 'reason': arg['reason'], 'force': arg.get('force', False), 'save_as': False, 'skip_save_participants': bool(arg.get('skip_save_participants'))}
        return [st(title='Save the active editor through the editor service (saveSelectedEditors -> doSaveEditors -> editorService.save)', source=src, call='editor-service.save', input=inp, **{'as': 'saved'}),
                {'return': {'handled': True, 'result': '= vars.saved.value'}}]
    if tmpl == 'save-all':
        return [st(title='Save the dirty editors through the editor service', source=src, call='editor-service.save-all', input={'reason': 'explicit'}, **{'as': 'saved'}),
                {'return': {'handled': True, 'result': '= vars.saved.value'}}]
    if tmpl == 'new-untitled':
        return [st(title='Create an untitled text editor input and open it', source=src, call='text-editor-service.create-text-editor', input={'resource': 'untitled:Untitled-1'}, **{'as': 'ed'}),
                {'call': O, 'input': {'resource': '= vars.ed.value.resource', 'options': {'pinned': True}}}, {'return': {'handled': True}}]
    if tmpl == 'new-file':
        return [st(title='Ask for the new file path', source=src, call='file-dialog-service.pick-file-to-save', input={'default_uri': 'file:///work/app/Untitled.txt'}, **{'as': 'pick'}),
                {'if': "!has(vars.pick.value.resource) || vars.pick.value.resource == ''", 'then': [{'return': {'handled': False}}]},
                {'call': 'file-service.create-file', 'input': {'resource': '= vars.pick.value.resource', 'overwrite': True}},
                {'call': O, 'input': {'resource': '= vars.pick.value.resource', 'options': {'pinned': True}}}, {'return': {'handled': True}}]
    if tmpl == 'scm-accept':
        return [
            {'if': "!has(input.repository_id) || input.repository_id == ''", 'then': [{'title': 'No scmRepository context key, nothing to accept', 'source': src, 'return': {'handled': False}}]},
            {'call': 'scm-service.get-repository', 'input': {'id': '= input.repository_id'}, 'as': 'repo'},
            {'if': "!vars.repo.value.exists || !has(vars.repo.value.repository.provider.accept_input_command) || vars.repo.value.repository.provider.accept_input_command == null", 'then': [{'title': 'Unknown repository or no acceptInputCommand', 'source': src, 'return': {'handled': False}}]},
            {'title': "Run the provider's acceptInputCommand with its arguments", 'source': src, 'call': 'command-service.execute-command',
             'input': {'command_id': '= vars.repo.value.repository.provider.accept_input_command.id', 'args': "= has(vars.repo.value.repository.provider.accept_input_command.arguments) ? vars.repo.value.repository.provider.accept_input_command.arguments : []"}},
            {'return': {'handled': True, 'result': {'command_id': '= vars.repo.value.repository.provider.accept_input_command.id'}}}]
    if tmpl == 'find-in-files':
        return [st(title='Open the search view', source=src, call='views-service.open-view', input={'view_id': 'workbench.view.search', 'focus': True}),
                {'call': 'search-view.trigger-query-change', 'input': {'query': "= has(input.query) ? input.query : ''"}, 'as': 'res'},
                {'return': {'handled': True, 'result': '= vars.res.value'}}]
    if tmpl == 'merge-accept' or tmpl == 'merge-accept-all':
        return [st(title=f'Accept {arg} into the result', source=src, set={'state.accepted': f"= state.accepted + ['{arg}']", 'state.unhandled_conflicts': ('= 0' if tmpl == 'merge-accept-all' else '= state.unhandled_conflicts > 0 ? state.unhandled_conflicts - 1 : 0')}), {'return': {'handled': True}}]
    if tmpl == 'merge-reset':
        return [st(title='Reset the result to the base and auto merge', source=src, set={'state.accepted': []}), {'return': {'handled': True}}]
    if tmpl == 'set-se':
        return [st(title='Update the active search editor', source=src, set={f'state.{k2}': v for k2, v in arg.items()}), {'return': {'handled': True}}]
    if tmpl == 'search-editor-open':
        return [st(title='Open a search editor input', source=src, set={'state.editors': '= state.editors + 1'}),
                {'call': O, 'input': {'resource': 'search-editor:Untitled-1', 'options': {'pinned': True}}},
                {'when': "has(input.query) && input.query != ''", 'call': 'search-model.search', 'input': {'query': {'pattern': '= input.query', 'folders': ['file:///work/app'], 'max_results': "= config['search-max-results']"}}},
                {'return': {'handled': True}}]
    raise Exception(tmpl)

ifaces, skips, handlers, groups = [], [], {}, {}
for e in INV:
    if e['kind'] != 'vscode-command':
        continue
    d = C.get(e['name'])
    if d is None:
        print('UNDECIDED', e['name'], file=sys.stderr); continue
    if d[0] == 'SKIP':
        skips.append({'kind': e['kind'], 'name': e['name'], 'file': e['file'], 'line': e['line'], 'reason': d[1]})
        continue
    comp, tmpl, arg, summary = d
    real = e['name']
    if real == 'NEW_FILE_COMMAND_ID': real = 'workbench.action.files.newFile'
    if real == 'GoToFileAction': real = 'multiDiffEditor.goToFile'
    name = slug(real)
    src = cite(e)
    iid = f'{comp}.{name}'
    if iid in [x['component'] + '.' + x['name'] for x in ifaces]:
        print('DUP', iid, file=sys.stderr)
    ifaces.append({'component': comp, 'name': name, 'kind': 'command', 'summary': f'{real}: {summary}',
                   'sources': [src], 'attributes': {'command_id': real},
                   'request': 'FilesCommandRequest', 'response': {'type': 'object', 'properties': {'handled': {'type': 'boolean'}, 'result': {}}},
                   'behavior': behavior(real, comp, tmpl, arg, src)})
    handlers[real] = iid
    groups.setdefault(comp, []).append(real)

# skips that are not commands: none beyond rules (all other entries are modeled)
CMD_IFACES = sorted(handlers.values())

# ---- contributions ----
CONTRIB = {
  'block-restore': ['file-editor-working-copy-editor-handler.constructor', 'search-editor-working-copy-editor-handler.constructor'],
  'block-startup': ['explorer-viewlet-views-contribution.constructor', 'text-file-editor-tracker.constructor', 'text-file-save-error-handler.constructor', 'file-uri-label-contribution.constructor', 'dirty-files-indicator.constructor', 'merge-editor-resolver-contribution.constructor', 'multi-diff-editor-resolver-contribution.constructor', 'scm-multi-diff-source-resolver-contribution.constructor', 'replace-preview-content-provider.constructor', 'search-editor-contribution.constructor', 'native-working-copy-backup-tracker.constructor', 'browser-working-copy-backup-tracker.constructor'],
  'restored': ['markers-status-bar-contributions.constructor', 'activity-updater.constructor', 'markers-file-decorations.constructor', 'merge-editor-open-handler-contribution.constructor', 'quick-diff-workbench-controller.constructor', 'scm-active-repository-controller.constructor', 'scm-active-resource-context-key-controller.constructor', 'working-copy-history-tracker.constructor'],
  'after-restored': ['workspace-watcher.constructor', 'marker-chat-context-contribution.constructor', 'scm-working-set-controller.constructor', 'scm-history-item-context-contribution.constructor', 'search-chat-context-contribution.constructor'],
  'editor-first-render': ['quick-diff-editor-controller.constructor'],
}
ALL_CONTRIB = sorted(sum(CONTRIB.values(), []))

def ctor(comp, summary, src, steps=None):
    b = steps or []
    b = b + [{'return': {'started': True}}]
    return {'component': comp, 'name': 'constructor', 'kind': 'function', 'summary': summary, 'sources': [src], 'request': {'type': 'object'}, 'behavior': b}

F = 'src/vs/workbench/contrib/files/browser'
gen_ctors = [
  ctor('file-editor-working-copy-editor-handler', 'FileEditorWorkingCopyEditorHandler constructor: registers the file editor handler with the working copy editor service.', f'{F}/editors/fileEditorHandler.ts',
       [{'call': 'working-copy-editor-service.register-handler', 'input': {'handler': 'file-editor'}}]),
  ctor('search-editor-working-copy-editor-handler', 'SearchEditorWorkingCopyEditorHandler constructor: registers the search editor handler with the working copy editor service.', 'src/vs/workbench/contrib/searchEditor/browser/searchEditor.contribution.ts:621-652',
       [{'call': 'working-copy-editor-service.register-handler', 'input': {'handler': 'search-editor'}}]),
  ctor('explorer-viewlet-views-contribution', 'Registers the explorer, open editors and empty views for the workbench state.', f'{F}/explorerViewlet.ts'),
  ctor('text-file-editor-tracker', 'Starts listening to dirty changes, save errors and window focus.', f'{F}/editors/textFileEditorTracker.ts:27-55'),
  ctor('file-uri-label-contribution', 'Registers the file: URI label formatter.', f'{F}/files.contribution.ts:60-98'),
  ctor('merge-editor-resolver-contribution', 'Registers the merge editor with the editor resolver.', 'src/vs/workbench/contrib/mergeEditor/browser/view/mergeEditor.ts:785'),
  ctor('merge-editor-open-handler-contribution', 'Registers the open handler for merge editor inputs.', 'src/vs/workbench/contrib/mergeEditor/browser/view/mergeEditor.ts:754'),
  ctor('multi-diff-editor-resolver-contribution', 'Registers the multi diff editor with the editor resolver.', 'src/vs/workbench/contrib/multiDiffEditor/browser/multiDiffEditorInput.ts:452'),
  ctor('scm-multi-diff-source-resolver-contribution', 'Registers the SCM resource group and history item multi diff source resolvers.', 'src/vs/workbench/contrib/multiDiffEditor/browser/scmMultiDiffSourceResolver.ts:197-216',
       [{'call': 'multi-diff-source-resolver-service.register-resolver', 'input': {'resolver': 'scm-multi-diff-source'}}, {'call': 'multi-diff-source-resolver-service.register-resolver', 'input': {'resolver': 'scm-history-item'}}]),
  ctor('replace-preview-content-provider', 'Registers the replace preview text model content provider.', 'src/vs/workbench/contrib/search/browser/replaceService.ts:45-62'),
  ctor('search-editor-contribution', 'Registers the search editor for *.code-search resources.', 'src/vs/workbench/contrib/searchEditor/browser/searchEditor.contribution.ts:120-147'),
  ctor('browser-working-copy-backup-tracker', 'Web backup tracker; on desktop the native tracker is used instead.', 'src/vs/workbench/services/workingCopy/browser/workingCopyBackupTracker.ts'),
  ctor('markers-status-bar-contributions', 'Adds the problems status bar entry from the marker statistics.', 'src/vs/workbench/contrib/markers/browser/markers.contribution.ts:579-590',
       [{'call': 'marker-service.get-statistics', 'as': 'stats'}, {'set': {'state.errors': '= vars.stats.value.errors', 'state.warnings': '= vars.stats.value.warnings', 'state.infos': '= vars.stats.value.infos'}}]),
  ctor('activity-updater', 'Shows the total problem count (errors + warnings + infos) as the Problems view badge.', 'src/vs/workbench/contrib/markers/browser/markers.contribution.ts:709-719',
       [{'call': 'marker-service.get-statistics', 'as': 'stats'}, {'set': {'state.badge': '= vars.stats.value.errors + vars.stats.value.warnings + vars.stats.value.infos'}}]),
  ctor('markers-file-decorations', 'Registers the problems file decorations provider when problems.decorations.enabled is on.', 'src/vs/workbench/contrib/markers/browser/markersFileDecorations.ts:56-121'),
  ctor('quick-diff-workbench-controller', 'Starts decorating visible text editors with quick diff models.', 'src/vs/workbench/contrib/scm/browser/quickDiffDecorator.ts:218',
       [{'call': 'quick-diff-model-service.create-quick-diff-model-reference', 'input': {'resource': 'file:///work/app/src/main.ts'}}]),
  ctor('quick-diff-editor-controller', 'Editor contribution for the quick diff peek widget.', 'src/vs/workbench/contrib/scm/browser/quickDiffWidget.ts:481'),
  ctor('scm-active-repository-controller', 'Tracks the active repository for the SCM badge and status bar.', 'src/vs/workbench/contrib/scm/browser/activity.ts:31'),
  ctor('scm-active-resource-context-key-controller', 'Maintains the scmActiveResource context keys.', 'src/vs/workbench/contrib/scm/browser/activity.ts:188'),
  ctor('working-copy-history-tracker', 'Starts listening to working copy saves and file moves.', 'src/vs/workbench/services/workingCopy/common/workingCopyHistoryTracker.ts:56-79'),
  ctor('workspace-watcher', 'Watches every workspace folder recursively.', 'src/vs/workbench/contrib/files/browser/workspaceWatcher.ts:133-177',
       [{'foreach': "= ['file:///work/app']", 'as': 'folder', 'steps': [{'title': 'Recursive watch with excludes', 'source': 'src/vs/workbench/contrib/files/browser/workspaceWatcher.ts:177', 'call': 'file-service.watch', 'input': {'resource': '= vars.folder', 'recursive': True}},
                                                                        {'set': {'state.watched': '= state.watched + [vars.folder]'}}]}]),
  ctor('marker-chat-context-contribution', 'Registers problems as chat context.', 'src/vs/workbench/contrib/markers/browser/markersChatContext.ts:120'),
  ctor('scm-working-set-controller', 'Saves and restores editor working sets per branch (scm.workingSets.enabled).', 'src/vs/workbench/contrib/scm/browser/workingSet.ts:28'),
  ctor('scm-history-item-context-contribution', 'Registers SCM history items as chat context.', 'src/vs/workbench/contrib/scm/browser/scmHistoryChatContext.ts:50'),
  ctor('search-chat-context-contribution', 'Registers search chat context pickers.', 'src/vs/workbench/contrib/search/browser/searchChatContext.ts:41-54'),
]

extra_ifaces = [
  {'component': 'search-view-model-workbench-service', 'name': 'get-search-results', 'kind': 'function', 'summary': 'The search model owned by the service and its current results.', 'sources': ['src/vs/workbench/contrib/search/browser/searchTreeModel/searchModel.ts:412-430'], 'request': {'type': 'object'}, 'response': 'SearchComplete',
   'behavior': [{'call': 'search-model.get-results', 'as': 'res'}, {'return': '= vars.res.value'}]},
  {'component': 'text-editor-service', 'name': 'create-text-editor', 'kind': 'function', 'summary': 'TextEditorService.createTextEditor: an untitled or file editor input for an untyped input.', 'sources': ['src/vs/workbench/services/textfile/common/textEditorService.ts:96-200'],
   'request': {'type': 'object', 'properties': {'resource': {'type': 'string', 'default': 'untitled:Untitled-1'}}}, 'response': {'type': 'object', 'properties': {'resource': {'type': 'string'}, 'type_id': {'type': 'string'}}},
   'behavior': [{'return': {'resource': '= input.resource', 'type_id': "= input.resource.startsWith('untitled:') ? 'workbench.editors.untitledEditorInput' : 'workbench.editors.files.fileEditorInput'"}}]},
  {'component': 'multi-diff-source-resolver-service', 'name': 'register-resolver', 'kind': 'function', 'summary': 'MultiDiffSourceResolverService.registerResolver.', 'sources': ['src/vs/workbench/contrib/multiDiffEditor/browser/multiDiffSourceResolverService.ts:58-65'],
   'request': {'type': 'object', 'properties': {'resolver': {'type': 'string'}}}, 'behavior': [{'set': {'state.resolvers': '= state.resolvers + [input.resolver]'}}]},
  {'component': 'multi-diff-source-resolver-service', 'name': 'resolve', 'kind': 'function', 'summary': 'MultiDiffSourceResolverService.resolve: the first registered resolver that handles the URI resolves it; without one the result is undefined.', 'sources': ['src/vs/workbench/contrib/multiDiffEditor/browser/multiDiffSourceResolverService.ts:67-74'],
   'request': {'type': 'object', 'properties': {'source': {'type': 'string', 'default': 'scm-history-item:scm0'}}},
   'behavior': [{'if': 'size(state.resolvers) == 0', 'then': [{'title': 'No resolver handles the URI, resolves to undefined', 'source': 'src/vs/workbench/contrib/multiDiffEditor/browser/multiDiffSourceResolverService.ts:73', 'return': {'resolved': False}}]},
                {'return': {'resolved': True}}]},
  {'component': 'quick-diff-service', 'name': 'toggle-quick-diff-provider-visibility', 'kind': 'function', 'summary': 'QuickDiffService.toggleQuickDiffProviderVisibility.', 'sources': ['src/vs/workbench/contrib/scm/common/quickDiffService.ts:53'],
   'request': {'type': 'object', 'properties': {'provider_id': {'type': 'string'}}}, 'behavior': [{'return': {'toggled': True}}]},
  {'component': 'quick-diff-model-service', 'name': 'create-quick-diff-model-reference', 'kind': 'function', 'summary': 'QuickDiffModelService.createQuickDiffModelReference: a ref-counted quick diff model for a text file model.', 'sources': ['src/vs/workbench/contrib/scm/browser/quickDiffModel.ts:72-94'],
   'request': {'type': 'object', 'properties': {'resource': {'type': 'string'}}},
   'behavior': [{'call': 'text-file-models.get', 'input': {'resource': '= input.resource'}, 'as': 'model'}, {'return': {'created': '= vars.model.value.exists'}}]},
]

# dispatchers
dispatch = [
  {'component': 'files-area-registrations', 'name': 'run-command', 'kind': 'function',
   'summary': "Routes a command id to this area's handler interface; an unknown id fails like CommandService.executeCommand.",
   'sources': ['src/vs/platform/commands/common/commands.ts'], 'request': 'FilesCommandRequest', 'response': {'type': 'object'},
   'errors': [{'code': 'command-not-found', 'status': 0, 'retryable': False}],
   'behavior': [
     {'if': '!(input.command_id in state.handlers)', 'then': [{'title': 'No handler registered for the command id', 'source': 'src/vs/platform/commands/common/commands.ts', 'fail': {'code': 'command-not-found', 'message': "= 'command \\'' + input.command_id + '\\' not found'"}}]},
     {'call': '= state.handlers[input.command_id]', 'targets': CMD_IFACES, 'input': '= input', 'as': 'ran'},
     {'return': '= vars.ran.value'}]},
  {'component': 'files-area-registrations', 'name': 'instantiate-contributions', 'kind': 'function',
   'summary': "Instantiates this area's workbench contributions registered for a phase, one after another.",
   'sources': ['src/vs/workbench/common/contributions.ts'],
   'request': {'type': 'object', 'properties': {'phase': {'type': 'string', 'enum': list(CONTRIB.keys()), 'default': 'block-startup'}}},
   'response': {'type': 'object', 'properties': {'started': {'type': 'integer'}}},
   'behavior': [
     {'set': {'vars.started': 0}},
     {'foreach': '= state.contributions[input.phase]', 'as': 'ctor', 'steps': [
        {'call': '= vars.ctor', 'targets': ALL_CONTRIB, 'input': {}},
        {'set': {'vars.started': '= vars.started + 1'}}]},
     {'return': {'started': '= vars.started'}}]},
]

def stub(iid, owner, kind, req, resp=None, errors=None, summary=None, attrs=None):
    comp, name = iid.split('.', 1)
    d = {'component': comp, 'name': name, 'kind': kind, 'attributes': dict({'boundary': True, 'owner': owner}, **(attrs or {})), 'request': req}
    if resp is not None: d['response'] = resp
    if errors: d['errors'] = errors
    if summary: d['summary'] = summary
    return d

S = lambda **p: {'type': 'object', 'properties': p}
STR = {'type': 'string'}
BOOL = {'type': 'boolean'}
ERR = lambda *cs: [{'code': c, 'status': 0, 'retryable': False} for c in cs]
PFS = {'type': 'object', 'properties': {'resource': {'type': 'string', 'examples': ['file:///work/app/src/main.ts']}, 'mtime': {'type': 'integer', 'examples': [1793318400000]}, 'size': {'type': 'integer', 'examples': [54]}, 'etag': {'type': 'string', 'examples': ['1793318400000-54']}, 'readonly': {'type': 'boolean', 'default': False}}}
stubs = [
  stub('model-service.create-model', 'editor', 'function', {'type': 'object', 'required': ['resource', 'value'], 'properties': {'resource': {'type': 'string', 'examples': ['file:///work/app/src/main.ts']}, 'value': {'type': 'string', 'examples': ["import { add } from './util';\nconsole.log(add(1, 2));\n"]}, 'language_id': {'type': 'string', 'default': 'plaintext', 'examples': ['typescript']}}}, S(resource=STR, version_id={'type': 'integer'}), ERR('model-already-exists'), 'IModelService.createModel (editor).'),
  stub('command-service.execute-command', 'platform-core', 'function', {'type': 'object', 'required': ['command_id'], 'properties': {'command_id': {'type': 'string', 'examples': ['git.commit']}, 'args': {'type': 'array', 'items': {}}}}, {}, ERR('command-not-found'), 'Seam: execute a registered command.'),
  stub('configuration-service.update-value', 'platform-core', 'function', {'type': 'object', 'required': ['key', 'value'], 'properties': {'key': {'type': 'string', 'examples': ['files.autoSave']}, 'value': {}, 'target': {'type': 'string', 'default': 'user'}}}, S(key=STR, removed=BOOL)),
  stub('file-service.write-file', 'platform-core', 'function', {'type': 'object', 'required': ['resource', 'content'], 'properties': {'resource': {'type': 'string', 'examples': ['file:///work/app/src/main.ts']}, 'content': STR, 'mtime': {'type': 'integer'}, 'etag': STR, 'unlock': {'type': 'boolean', 'default': False}}}, PFS,
       ERR('file-modified-since', 'file-permission-denied', 'no-file-system-provider-found', 'file-write-locked', 'file-too-large'), 'Seam: write a file; refuses with file-modified-since when the mtime/etag no longer match the file on disk.'),
  stub('file-service.read-file', 'platform-core', 'function', S(resource={'type': 'string', 'examples': ['file:///work/app/src/main.ts']}, etag=STR), S(resource=STR, value=STR, mtime={'type': 'integer'}, size={'type': 'integer'}, etag=STR),
       ERR('file-not-found', 'file-not-modified-since', 'file-too-large')),
  stub('file-service.exists', 'platform-core', 'function', S(resource=STR), S(exists={'type': 'boolean', 'default': True})),
  stub('file-service.can-move', 'platform-core', 'function', S(source=STR, target=STR, overwrite=BOOL), S(ok={'type': 'boolean', 'default': True}, error_code=STR)),
  stub('file-service.can-delete', 'platform-core', 'function', S(resource=STR, use_trash=BOOL, recursive=BOOL), S(ok={'type': 'boolean', 'default': True}, error_code=STR)),
  stub('file-service.can-create-file', 'platform-core', 'function', S(resource=STR, overwrite=BOOL), S(ok={'type': 'boolean', 'default': True}, error_code=STR)),
  stub('file-service.move', 'platform-core', 'function', S(source=STR, target=STR, overwrite=BOOL), 'PlatformFileStat', ERR('file-not-found', 'file-move-conflict')),
  stub('file-service.del', 'platform-core', 'function', S(resource=STR, use_trash=BOOL, recursive=BOOL), S(deleted=STR), ERR('file-not-found', 'file-permission-denied', 'trash-unsupported')),
  stub('file-service.create-file', 'platform-core', 'function', S(resource=STR, overwrite=BOOL), 'PlatformFileStat', ERR('file-exists')),
  stub('file-service.watch', 'platform-core', 'function', S(resource=STR, recursive=BOOL), {}),
  stub('elevated-file-service.write-file-elevated', 'workbench-shell', 'function', S(resource=STR, value=STR), 'FilesFileStat'),
  stub('notification-service.notify', 'workbench-shell', 'function', {'type': 'object', 'required': ['severity', 'message'], 'properties': {'severity': {'type': 'string', 'enum': ['info', 'warning', 'error']}, 'message': STR, 'actions': {'type': 'array', 'items': STR}}}, S(id={'type': 'integer'}, silent=BOOL)),
  stub('clipboard-service.write-text', 'workbench-shell', 'function', S(text=STR), {}),
  stub('clipboard-service.write-resources', 'workbench-shell', 'function', S(resources={'type': 'array', 'items': STR}), {}),
  stub('clipboard-service.read-resources', 'workbench-shell', 'function', {'type': 'object'}, S(resources={'type': 'array', 'items': STR, 'default': ['file:///work/app/src/util.ts']})),
  stub('storage-service.store', 'platform-core', 'function', {'type': 'object', 'required': ['key', 'scope'], 'properties': {'key': STR, 'value': {'type': ['string', 'null'], 'default': None}, 'scope': {'type': 'string', 'enum': ['application', 'profile', 'workspace']}}}, S(changed=BOOL)),
  stub('storage-service.remove', 'platform-core', 'function', {'type': 'object', 'required': ['key', 'scope'], 'properties': {'key': STR, 'scope': {'type': 'string', 'enum': ['application', 'profile', 'workspace']}}}, S(changed=BOOL)),
  stub('marker-service.get-statistics', 'platform-core', 'function', {'type': 'object'}, S(errors={'type': 'integer', 'default': 0}, warnings={'type': 'integer', 'default': 0}, infos={'type': 'integer', 'default': 0})),
  stub('quick-input-service.quick-access-show', 'workbench-shell', 'function', S(prefix=STR), {}),
  stub('editor-service.open-editor', 'workbench-shell', 'function', {'type': 'object', 'required': ['resource'], 'properties': {'resource': {'type': 'string', 'examples': ['file:///work/app/src/main.ts']}, 'original': STR, 'group': {'type': 'integer', 'default': -1}, 'options': {'type': 'object', 'properties': {'pinned': BOOL, 'inactive': BOOL, 'preserve_focus': BOOL}, 'default': {}}}}, {'type': 'object', 'required': ['opened'], 'properties': {'opened': BOOL, 'resource': STR, 'group_id': {'type': 'integer'}, 'pinned': BOOL, 'is_new': BOOL}}, ERR('invalid-editor-group-provided'), 'Seam: open an editor.'),
  stub('editor-service.close-editor', 'workbench-shell', 'function', S(resource=STR), {}),
  stub('lifecycle-service.on-before-shutdown', 'workbench-shell', 'event', {'type': 'object', 'required': ['reason'], 'properties': {'reason': {'type': 'string', 'enum': ['close', 'quit', 'reload', 'load']}, 'window_id': {'type': 'string', 'examples': ['w1']}}}, {'type': 'object', 'required': ['veto'], 'properties': {'veto': BOOL, 'vetoed_by': {'type': 'array', 'items': STR}}}, None, 'Seam: onBeforeShutdown; listeners return a veto.'),
  stub('file-dialog-service.pick-file-to-save', 'workbench-shell', 'function', S(default_uri=STR), S(resource={'type': 'string', 'default': 'file:///work/app/src/copy.ts'})),
  stub('views-service.open-view', 'workbench-shell', 'function', S(view_id=STR, focus=BOOL), {}),
  stub('host-service.open-window', 'workbench-shell', 'function', S(resource=STR, force_new_window=BOOL), {}),
  stub('files-configuration-service.update-readonly', 'workbench-shell', 'function', S(resource=STR, readonly=STR), {}),
  stub('workspace-editing-service.remove-folders', 'workbench-shell', 'function', S(folders={'type': 'array', 'items': STR}), {}),
  stub('extension-service.activate-by-event', 'exthost', 'function', {'type': 'object', 'required': ['activation_event'], 'properties': {'activation_event': {'type': 'string', 'examples': ['onSearch:file']}, 'activation_kind': {'type': 'string', 'enum': ['normal', 'immediate'], 'default': 'normal'}}}, S(activated={'type': 'array', 'items': STR, 'default': []}, deferred={'type': 'boolean', 'default': False}, cached={'type': 'boolean', 'default': False}), ERR('canceled'), 'Seam: activate extensions for an activation event.'),
  stub('ext-host-save-participant.participate', 'exthost', 'function', S(resource=STR, reason=STR), {}, ERR('canceled'), 'Fires onWillSaveTextDocument in the extension host (1750 ms budget).'),
  stub('main-thread-file-system-event-service.participate', 'exthost', 'function', S(operation=STR, files={'type': 'array', 'items': {'type': 'object'}}, timeout_ms={'type': 'integer'}), {}, None, 'Extension onWillCreate/Rename/DeleteFiles participants.'),
  stub('ext-host-search.provide-text-search-results', 'exthost', 'rpc', S(scheme=STR, query={'$ref': 'SearchTextQuery'}), 'SearchComplete', None, 'ExtHostSearchShape.$provideTextSearchResults (ripgrep in the node extension host).', {'shape': 'ExtHostSearchShape'}),
  stub('format-on-save-participant.participate', 'workbench-contribs', 'function', S(resource={'type': 'string', 'examples': ['file:///work/app/src/main.ts']}, reason={'type': 'string', 'enum': ['explicit', 'auto', 'focus-change', 'window-change'], 'default': 'explicit'}, content={'type': 'string', 'examples': ['const a = 1;  \nconsole.log(a)']}), None, None, 'Format on save participant (contract copied from workbench-contribs).'),
  stub('bulk-edit-service.apply', 'workbench-contribs', 'function', S(edits={'type': 'array', 'items': {'type': 'object', 'properties': {'type': {'type': 'string', 'enum': ['text', 'file']}, 'resource': STR, 'op': {'type': 'string', 'enum': ['edit', 'create', 'delete', 'rename']}, 'target': STR, 'needs_confirmation': BOOL}}}, show_preview={'type': 'boolean', 'default': False}, respect_auto_save_config={'type': 'boolean', 'default': False}, label=STR, code=STR), None, [{'code': 'has-changed-in-the-meantime', 'status': 0, 'retryable': False}, {'code': 'does-not-exist-and-can-not-be-deleted', 'status': 0, 'retryable': False}]),
  stub('native-host-main-service.get-window-count', 'main-process', 'ipc', S(window_id={'type': 'string', 'examples': ['w1']}), S(count={'type': 'integer', 'examples': [1]})),
  stub('lifecycle-service.on-before-shutdown-final', 'workbench-shell', 'event', S(reason=STR), None, None, 'Seam: the final veto round (InternalBeforeShutdownEvent.finalVeto).'),
  stub('lifecycle-service.veto', 'workbench-shell', 'function', {'type': 'object', 'required': ['id', 'veto'], 'properties': {'id': {'type': 'string', 'examples': ['veto.backups']}, 'veto': BOOL}}, None),
  stub('editor-service.save', 'workbench-shell', 'function', S(resource={'type': 'string', 'examples': ['file:///work/app/src/main.ts']}, reason={'type': 'string', 'default': 'explicit'}, save_as={'type': 'boolean', 'default': False}, force={'type': 'boolean', 'default': False}, skip_save_participants={'type': 'boolean', 'default': False}), S(success=BOOL)),
  stub('editor-service.save-all', 'workbench-shell', 'function', S(reason={'type': 'string', 'default': 'explicit'}), S(saved=BOOL)),
  stub('native-host-service.show-item-in-folder', 'workbench-shell', 'function', S(path=STR), {}),
]

def fixon(v):
    if isinstance(v, dict):
        return {('on' if k is True else k): fixon(x) for k, x in v.items()}
    if isinstance(v, list):
        return [fixon(x) for x in v]
    return v
docs = []
for i in range(1, 10):
    try:
        docs.append(fixon(yaml.safe_load(open(f'{GEN}/core{i}.yaml'))))
    except FileNotFoundError:
        pass
out = {'schema_version': 1, 'id': 'vscode'}
for key in ['configs', 'schemas', 'components', 'interfaces', 'links', 'flows', 'scenarios']:
    lst = []
    for d in docs:
        lst += d.get(key, []) or []
    if key == 'interfaces':
        lst += ifaces + gen_ctors + extra_ifaces + dispatch + stubs
    if key == 'scenarios':
        out_sc = lst
    if lst:
        out[key] = lst

# command coverage scenarios, one multi-step scenario per registering component
for comp, cmds in groups.items():
    steps = []
    if comp == 'scm-actions':
        steps.append({'flow': 'scm-register-provider', 'as': 'reg', 'input': {'accept_input_command': {'id': 'git.commit', 'arguments': []}}})
    for n, c in enumerate(cmds):
        steps.append({'flow': 'files-run-command', 'as': f's{n}', 'input': {'command_id': c, 'resource': 'file:///work/app/src/main.ts', 'repository_id': 'scm0', 'query': 'add', 'args': []}})
    exp = ['[' + ', '.join(f"steps.s{n}" for n in range(len(cmds))) + "].all(x, x.status == 'ok' || x.result.error.code == 'command-not-found')",
           "trace.filter(e, e.type == 'call.start' && e.interface.startsWith('" + comp + ".cmd-')).size() >= " + str(len(cmds))]
    out_sc.append({'id': f'commands-{comp}', 'name': f'Every modeled command registered by {comp} runs through its handler', 'flow': 'files-run-command',
                   'fixtures': ['dirty-editor'], 'steps': steps, 'expect': exp})

# area seed fixture (decision 10) and command registration in platform-core's registry (decision 6)
MAIN = "import { add } from './util';\nconsole.log(add(1, 2));\n"
out['fixtures'] = [{
    'id': 'files-search-scm-seed',
    'summary': 'files-search-scm initial state: the exthost text search provider for file:, the git repository scm0 (acceptInputCommand git.commit), a clean src/main.ts text file model, and this area\'s commands in the command registry.',
    'state': {
        'search-service': {'text_providers': {'file': True}},
        'scm-service': {'repositories': {'scm0': {'provider': {'id': 'scm0', 'label': 'Git', 'root_uri': 'file:///work/app', 'accept_input_command': {'id': 'git.commit', 'arguments': []}}, 'input': {'value': '', 'history': [''], 'index': 0}}}},
        'scm-view-service': {'active_repository': 'scm0', 'visible': ['scm0']},
        'text-file-models': {'models': {'file:///work/app/src/main.ts': {'value': MAIN, 'version_id': 1, 'saved_version_id': 1, 'dirty': False, 'language_id': 'typescript', 'mtime': 1793318400000, 'etag': '1793318400000-54', 'size': 54}}},
        'commands-registry': {'commands': {cid: {'handler': iid} for cid, iid in handlers.items()}},
    }}]
for sc in out['scenarios']:
    fx = sc.setdefault('fixtures', [])
    if 'files-search-scm-seed' not in fx:
        fx.append('files-search-scm-seed')

# dispatcher state
for c in out['components']:
    if c['id'] == 'files-area-registrations':
        c['state'] = {'schema': {'type': 'object', 'properties': {'handlers': {'type': 'object'}, 'contributions': {'type': 'object'}}},
                      'initial': {'handlers': handlers, 'contributions': CONTRIB}}

# stub components: boundary interfaces need their components? only if not defined elsewhere
own_comps = {c['id'] for c in out['components']}
skeleton = {'text-file-models', 'workbench', 'user'}
need = sorted({i['component'] for i in out['interfaces']} - own_comps - skeleton)
STUB_PARENT = {'platform-core': 'platform', 'workbench-shell': 'workbench', 'exthost': 'exthost-bridge', 'editor': 'editor', 'workbench-contribs': 'workbench', 'main-process': 'main-process'}
import glob
SKELETON_IDS = {c['id'] for c in yaml.safe_load(open(f'{OUT}/skeleton.yaml'))['components']}
others_owner, others_stub = {}, {}
by_frag = {}
for fpath in sorted(glob.glob(f'{OUT}/fragments/*.yaml')):
    if fpath.endswith('files-search-scm.yaml'):
        continue
    try:
        od = yaml.safe_load(open(fpath))
    except Exception:
        continue
    for oc in od.get('components', []) or []:
        tgt = others_stub if (oc.get('attributes') or {}).get('boundary') else others_owner
        tgt.setdefault(oc['id'], oc)
        if not (oc.get('attributes') or {}).get('boundary'):
            by_frag[(fpath.split('/')[-1][:-5], oc['id'])] = oc
need = sorted(set(need) | {'commands-registry'})
def owner_of(cid):
    for i in out['interfaces']:
        if i['component'] == cid:
            return i['attributes']['owner']
    return {'commands-registry': 'platform-core'}.get(cid, 'workbench-contribs')
extra_parents = []
for cid in need:
    owner = owner_of(cid)
    if False: next(i['attributes']['owner'] for i in out['interfaces'] if i['component'] == cid)
    parent = STUB_PARENT[owner]
    kind = 'service'
    if cid == 'ext-host-search':
        parent = 'exthost-runtime'
    ref = by_frag.get((owner, cid)) or others_owner.get(cid) or others_stub.get(cid)
    if ref:
        kind = ref.get('kind', kind)
        if ref.get('parent'):
            parent = ref['parent']
            p = parent
            while p not in SKELETON_IDS and p not in own_comps and p not in need and p not in [x['id'] for x in extra_parents]:
                pr = by_frag.get((owner, p)) or others_owner.get(p) or others_stub.get(p)
                if not pr:
                    parent = STUB_PARENT[owner]; break
                extra_parents.append({'id': p, 'kind': pr.get('kind', 'module'), 'parent': pr.get('parent'), 'attributes': {'boundary': True, 'owner': (pr.get('attributes') or {}).get('owner', owner)}})
                p = pr.get('parent')
    out['components'].append({'id': cid, 'kind': kind, 'parent': parent, 'attributes': {'boundary': True, 'owner': owner}})

extra_parents = [p for p in extra_parents if p['id'] != 'save-participants-contribution']
for c in out['components']:
    if c['id'] == 'format-on-save-participant':
        c.pop('kind', None); c.pop('parent', None)
out['components'] += extra_parents

# Fix round (after judging): fixround.py edits the generated document (see notes, "Fix round").
sys.path.insert(0, GEN)
import fixround
fixround.apply(out)

class D(yaml.SafeDumper):
    pass
D.ignore_aliases = lambda self, data: True
def str_presenter(dumper, data):
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='"')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)
D.add_representer(str, str_presenter)
with open(f'{OUT}/fragments/files-search-scm.yaml', 'w') as f:
    f.write('# files-search-scm fragment of the VS Code 1.144 ontology (text files, working copies, explorer, search, SCM, problems, merge and multi diff editors).\n')
    yaml.dump(out, f, Dumper=D, sort_keys=False, allow_unicode=True, width=200)
json.dump(skips, open(f'{OUT}/skips/files-search-scm.json', 'w'), indent=1)
print('ifaces', len(out['interfaces']), 'cmds', len(ifaces), 'skips', len(skips), 'components', len(out['components']), file=sys.stderr)

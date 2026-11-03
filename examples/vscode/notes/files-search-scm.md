# files-search-scm notes

Fragment: `examples/vscode/fragments/files-search-scm.yaml` (generated from hand-written
behavior sources plus a command table; 63 own components, 278 own interfaces, 37 boundary stubs,
10 configs, 10 schemas, 28 flows, 112 scenarios). Skips: `examples/vscode/skips/files-search-scm.json`
(93 entries). All paths below are relative to the snapshot root.

## 1. Entry points (284 inventory entries owned by this area)

Covered: 191; skipped: 93; uncovered: 0.

- **service (18, all covered)**: each implementation component cites the `createDecorator` line
  (`text-file-service` textfiles.ts:23, `working-copy-service`, `working-copy-file-service`,
  `native-working-copy-backup-service`, `native-working-copy-history-service`,
  `working-copy-editor-service`, `text-editor-service`, `search-service`,
  `search-view-model-workbench-service`, `search-history-service`, `replace-service`,
  `notebook-search-service`, `scm-service`, `scm-view-service`, `quick-diff-service`,
  `quick-diff-model-service`, `explorer-service`, `multi-diff-source-resolver-service`).
- **workbench-contribution (28, all covered)**: one component per contribution class citing the
  registration line, with a `constructor` interface. They are instantiated by
  `files-area-registrations.instantiate-contributions` per phase (block-restore, block-startup,
  restored, after-restored, editor-first-render); scenario `files-contributions-startup-all-phases`.
- **process-main (1, covered)**: `localFileSearchMain.ts:9` → `local-file-search-worker.bootstrap`,
  flow `files-text-search-worker-start` (web worker; not loaded on desktop).
- **vscode-command (237)**: 144 modeled as `cmd-<id slug>` on the registering component
  (`file-actions`, `file-commands`, `electron-file-actions`, `explorer-view`, `open-editors-view`,
  `markers-actions`, `merge-editor-actions`, `multi-diff-editor-actions`, `scm-actions`,
  `search-actions`, `search-editor-actions`), each citing its registration lines (inventory line to
  the line before the next entry, at most 10 lines). They are reached through
  `files-area-registrations.run-command` (state `handlers`: command id → interface), and every
  modeled command runs in one multi-step scenario per component (`commands-<component>`).
  Two inventory names are constants/classes: `NEW_FILE_COMMAND_ID` = `workbench.action.files.newFile`
  (fileConstants.ts:50) and `GoToFileAction` = `multiDiffEditor.goToFile` (multiDiffEditor/browser/actions.ts:54).
  Skipped (93), grouped:
  - 47 "UI toggle: no state beyond the layout": view-mode/sort/layout toggles (scmViewPane.ts:1147-1358
    view/sort/selection-mode actions, merge editor layouts and base-view toggles, multi diff file list
    toggles, search viewAsTree/List, collapse/expand, Problems view as tree/table, multiline/singleline
    message, clear filter text, toggleProblems, closeQuickDiff, toggleQueryDetails, closeReplaceInFilesWidget,
    collapseExplorerFolders, toggleEditorGroupLayout, graph list/tree mode).
  - 33 "UI navigation/focus": focus moves and next/previous navigation (compressed folders, problems
    focus, search focus boxes and result navigation, search editor focus inputs, SCM focus input/group,
    dirty diff next/previous, merge next/previous conflict, multi diff next/previous change, toggleBetweenInputs,
    focusFilesExplorer, revealCurrentHistoryItem, toggleQuickDiffWidgetFocus, expandRecursively).
  - 5 Problems view filter toggles (toggleErrors/Warnings/Infos/ActiveFile/ExcludedFiles): filter presentation only.
  - 7 developer/internal: `merge.dev.*` (5), `multiDiffEditor.openLayoutDebug`, `_workbench.openScmMultiDiffEditor` (rule `_workbench.*`).
  - 1 `${actionId}.${historyItemRef.id}` (scmHistoryViewPane.ts:2154): context-menu entry registered per history ref; graph filter selection.
- No exthost-rpc, ipc-channel or extension entries fall in this area (MainThreadSCM/Search/Documents live in `src/vs/workbench/api/**`, exthost).

## 2. Components and code

Text files and working copies (deep):
- `text-file-service` (NativeTextFileService; textFileService.ts:47, save 351-385, saveAs 387-498, revert 735-752, read 181-251, write 266-274, create 253-264).
- `text-file-models` (skeleton anchor; TextFileEditorModelManager + TextFileEditorModel): `get`, `list-modified`, `resolve`, `save`, `revert`, `on-model-content-changed`, `on-did-files-change`, `backup`, `find-matches`, and the move/copy restore listeners (textFileEditorModelManager.ts:201-340). State `models[uri] = {value, version_id, saved_version_id, dirty, language_id, mtime, etag, size, conflict, error, orphaned, readonly}`; `models_to_restore` during a move.
- `text-file-save-participant` (textFileSaveParticipant.ts:35-93), `text-file-save-error-handler` (textFileSaveErrorHandler.ts:43-395, state `messages`), `text-file-editor-tracker`, `dirty-files-indicator`.
- `working-copy-service` (relays dirty/content/save events, workingCopyService.ts:183-228), `working-copy-file-service` + `working-copy-file-operation-participant` (workingCopyFileService.ts:346-497, workingCopyFileOperationParticipant.ts:31-46).
- `native-working-copy-backup-tracker` (workingCopyBackupTracker.ts common:84-238 and electron-browser:50-410), `native-working-copy-backup-service` (state `backups`), `working-copy-history-tracker`, `native-working-copy-history-service` (state `entries`), `working-copy-editor-service`, `text-editor-service`.
Explorer: `explorer-service` (applyBulkEdit 259-289, setToCopy, select, refresh, setEditable), `file-actions` (deleteFiles 87-253, openExplorerAndCreate 901-981, renameHandler 997-1034, pasteFileHandler 1122-1303), `file-commands`, `electron-file-actions`, `explorer-view`, `open-editors-view`.
Search: `search-view` (triggerQueryChange/_onQueryChanged 1589-1711, replaceAll 812-856), `search-model` (SearchModelImpl.search/doSearch), `search-service` (textSearchSplitSyncAsync/doSearch searchService.ts:116-222, registerSearchResultProvider), `search-history-service`, `replace-service` (115-138), `notebook-search-service`, `search-actions`, `search-editor-actions`.
SCM: `scm-service` (registerSCMProvider 389-424, getRepository, SCMInput.setValue 139-152 and history 154-176), `scm-view-service`, `scm-actions` (scm.acceptInput scm.contribution.ts:420-445), quick diff services.
Others: markers contributions (`markers-status-bar-contributions`, `activity-updater` badge = errors + warnings + infos), merge editor (`merge-editor-actions.accept-merge`, commands.ts:639-662 + mergeEditorInputModel.ts:161-166), multi diff resolver service and contributions.
`files-area-registrations` is a modeling device (see §8).

## 3. Boundary stubs and contracts

Copied from the owner fragment where it existed at hand-off: `file-service.write-file` (platform-core: field `content`, mtime/etag, `PlatformFileStat` fields inlined), `file-service.read-file`, `file-service.del`, `configuration-service.update-value`, `storage-service.store/remove`, `command-service.execute-command` (platform-core); `editor-service.open-editor`, `lifecycle-service.on-before-shutdown` (`{reason, window_id}` → `{veto}`), `notification-service.notify` (workbench-shell); `extension-service.activate-by-event` (exthost); `bulk-edit-service.apply` edits `{type, op, resource, target}` and `format-on-save-participant.participate` `{resource, reason, content}` (as declared by workbench-contribs/editor).
Shared shapes only (no owner definition yet): `file-service.exists/can-move/can-delete/can-create-file/move/create-file/watch`, `elevated-file-service.write-file-elevated`, `clipboard-service.*`, `marker-service.get-statistics`, `quick-input-service.quick-access-show`, `editor-service.close-editor`, `file-dialog-service.pick-file-to-save`, `views-service.open-view`, `host-service.open-window`, `files-configuration-service.update-readonly`, `workspace-editing-service.remove-folders`, `native-host-service.*`, `ext-host-save-participant.participate`, `main-thread-file-system-event-service.participate`, `ext-host-search.provide-text-search-results` (rpc, ExtHostSearchShape, called `on: eh<N>`).
Owners chosen from the registerSingleton location: notification, quick input, clipboard, native host (WorkbenchNativeHostService, workbench/services/host/electron-browser/nativeHostService.ts:282), elevated file, file dialog, views → workbench-shell. Other fragments' stubs disagree on some of these owners and on component `kind` (module vs service); those are stub-vs-stub disagreements between other areas' guesses, flagged for reconciliation.
Interfaces other areas stub on my side (my definitions are the contract): `text-file-service.save` (request `{resource, options: FilesSaveOptions}`, response `{saved, resource, skipped, error_code}`), `text-file-models.get/resolve/save/revert/on-model-content-changed`, events `text-file-models.on-did-*` and `working-copy-service.on-did-change-dirty/-content/-save` (EditorAutoSave in workbench-shell should subscribe to these), `working-copy-file-service.move/create/delete`, `scm-service.register-scm-provider` (MainThreadSCM), `search-service.register-search-result-provider` (MainThreadSearch). `FilesSaveOptions` is the skeleton's schema; I also pass `ignore_modified_since`, `write_unlock`, `write_elevated` (ITextFileSaveOptions fields) which the skeleton schema does not list — proposed addition.

## 4. Config

| id | value | default | sources | note |
|---|---|---|---|---|
| files-auto-save | off | off | files.contribution.ts:261-274 | default is afterDelay on web and in the agents window; desktop off. product.json: no override |
| files-auto-save-delay | 1000 | 1000 | files.contribution.ts:275-281 | ≤1000 = short delay (filesConfigurationService.ts:128, 366) |
| editor-format-on-save | false | (none) | files.contribution.ts:391-395 | registration has no default → undefined → false; read by the editor-area participant |
| files-participants-timeout | 60000 | 60000 | files.contribution.ts:380-384 | ≤0 disables participants |
| search-max-results | 20000 | 20000 | search.common.contribution.ts:83-87, search.ts:32 | nullable (null = unlimited); fixture cited only search.ts |
| files-save-conflict-resolution | askUser | askUser | files.contribution.ts:354-367 | overwriteFileOnDisk disables the etag check |
| explorer-confirm-delete | true | true | files.contribution.ts:494-498 | |
| workbench-local-history-enabled | true | true | browser/workbench.contribution.ts:480-485 | registered by workbench, read by my tracker |
| workbench-local-history-max-file-size | 256 (KB) | 256 | browser/workbench.contribution.ts:486-492 | |
| files-hot-exit | onExit | onExit | boundary reference, owner main-process | web default onExitAndWindowClose |

No deployed value differs from its code default (product.json sets none of these). The code
defaults differ by platform for files.autoSave (web) and files.hotExit (web).

## 5. Fixture requests

- A `search-providers` world: `search-service@w1.text_providers.file = true` (the exthost registers the ripgrep provider at startup); scenarios currently seed it via `state`.
- A registered git SCM repository (`scm-service@w1.repositories.scm0` with acceptInputCommand git.commit); scenarios register it in a first step.
- An open clean model (`text-file-models@w1` with src/main.ts at version 1, not dirty); several scenarios seed it via `state`.

## 6. What the code didn't settle / assumptions

- Commands that go through `editorService.save/revert/saveAll` (workbench-shell) are modeled calling `text-file-service.save/revert` directly; the editor input hop (TextResourceEditorInput.save) is elided. Reconcile with workbench-shell's editor-service.
- Language id of a new model is derived from the extension (ILanguageService is elided).
- `etag` when a model has none (fixture data) falls back to `string(mtime)`.
- The save sequentializer (one save at a time per model, queued saves) is not modeled; `text-file-models` is the skeleton anchor and has no `capacity`.
- Binary detection is a choice point `text-file-service.read.decode` (text/binary).
- Explorer, replace, paste and rename go through `bulk-edit-service.apply` (workbench-contribs); the bulk edit's own call into `working-copy-file-service` is theirs. `working-copy-file-service.*` has its own flows.
- Search history is stored as a newline-joined string in storage (the code stores JSON).

## 7. Docs vs code

- files.autoSave is often described as "off by default"; the code defaults it to afterDelay on web and in the agents window.
- Hot exit "onExit" still backs up on window close when it is the last window on Windows/Linux (workingCopyBackupTracker.ts:179-187), and on reload always.
- Auto save never saves a model in conflict or error state (textFileEditorModel.ts:842-849); only explicit saves retry.

## 8. Simulator gaps

- Command dispatch and contribution instantiation are platform-core/workbench-shell code; `files-area-registrations` stands in for them so commands and contributions are flow-reachable (dynamic call with `targets`).
- Behaviors cannot read another component's state; text file model logic therefore lives on the `text-file-models` anchor, and other services read it through `get`/`list-modified`.
- Debounces (backup schedule, RunOnceWorker 800 ms) are `emit after_ms` plus a "newer schedule wins" check (workingCopyBackupTracker.ts:169-223).
- Stub outputs cannot be driven without mocks: `file-service.exists=false` (orphan after delete, textFileEditorModel.ts:190-195), `can-*` returning an Error, and `native-host-service.get-window-count > 1` are unreached branches. Faults on those calls produce errors, not the alternative value.
- `Promises.settled` (failures ignored) is modeled as `parallel` with branch `on_error: continue`.
- Cancellation tokens racing with work (`raceCancellation`) are approximated by an input `token.canceled` flag.

## 9. Known gaps

- Behavior coverage 96.7%; unexecuted branches: the stub-output branches above, `save-as` same-target and canceled-dialog, `search-service` canceled-token and no-folders paths, `text-file-save-participant` pre-canceled token, `working-copy-service` duplicate registration, `text-file-models.backup/revert` on unknown model, `open-explorer-and-create` folder/readonly paths, paste with empty clipboard / cut-move.
- Untitled models (UntitledTextEditorService, workbench-shell) are not modeled; untitled save stops after the save dialog.
- Encoding, readonly-in-session (FilesConfigurationService), notebook working copies, stored-file working copies other than text, AI search, SCM history graph data, quick diff computation and merge editor model internals are modeled at the command level only.
- Markers depend on platform-core's marker service; the Problems view itself is not modeled.

## Reconciliation round

Generator: `examples/vscode/gen/files-search-scm/gen.py` (reads `core1..9.yaml` beside it and
`inventory.json` filtered by `area`).

Changes:
- Decision 2: file-service calls send `resource` (and `content` for write-file); the create-file/move stubs now return the owner's `PlatformFileStat`.
- Decision 3: `extension-service.activate-by-event` calls send `activation_kind: normal`.
- Decision 5: `bulk-edit-service.apply` calls send `show_preview: false` and `respect_auto_save_config: false`, with edits `{type, op, resource, target}`.
- Decision 6: `files-search-scm-seed` seeds platform-core's `commands-registry.commands` with all 144 of this area's commands, each `{handler: <cmd interface>}`.
- Decision 7: window counts go through `native-host-main-service.get-window-count` (main-process, ipc). Stub components take the owner's `kind`, and `service` when no owner defines them.
- Decision 8: the backup tracker subscribes to `lifecycle-service.on-before-shutdown-final`. It decides in `on-final-before-shutdown-decide` and answers with `lifecycle-service.veto {id: veto.backups}`. The `text-file-models.on-did-*` and `working-copy-service.on-did-change-*` topics are published synchronously, and workbench-shell's EditorAutoSave now subscribes to them.
- Decision 9: save commands go through `editor-service.save` (`workbench.action.files.saveAs` sends `save_as: true`; `saveWithoutFormatting` sends `skip_save_participants: true`), and the save-all commands go through `editor-service.save-all`.
- Decision 10: the `files-search-scm-seed` fixture holds:
  - `search-service.text_providers.file`;
  - the git repository `scm0` (acceptInputCommand `git.commit`), made active in `scm-view-service`;
  - a clean `src/main.ts` model whose mtime and etag match the disk;
  - the command registry entries above.

  Every scenario lists the seed. Scenarios no longer assume an empty `text-file-models` or `scm-service`, and registration scenarios use `scm1`/`scm2`.
- `working-copy-file-service.move/create/delete` treat `overwrite`, `use_trash` and `recursive` as optional, as the code does (bulk edit callers omit them).
- deleteFiles: a failed retry that already ignores missing files now defaults the retry dialog to cancel. Before, a scripted run could loop until the call depth limit.
- The command coverage scenarios accept `command-not-found` from commands other areas have not registered (e.g. `editor.action.quickFix`).

Remaining failures, each waiting on another area:
- `files-save-as-new-target`: workbench-shell's `editor-service.save` ignores `save_as`; it should call `text-file-service.save-as`.
- `files-save-without-formatting-skips-participants`: workbench-shell's `editor-service.save` drops `skip_save_participants`; it should forward it.
- `search-find-in-files-happy`, `search-register-provider-then-search`: `file-service.exists('file:///work/app')` is false because the disk has no folder entries, so the search drops the folder (platform-core `disk.stat` for directories, or a shared fixture request below).
- `search-replace-all-confirmed`, `search-replace-all-then-read`: the bulk text edit fails with `model-is-disposed`, because the editor area's `text-model` has no model for the open `src/main.ts` (editor seed, or a shared fixture).

Shared fixture requests:
- folder entries `file:///work/app` and `file:///work/app/src` on `disk` in `base-workspace`, or `disk.stat` resolving directories;
- editor text models for files that `dirty-editor` and the seed open.

Follow-ups (same round):
- `format-on-save-participant` stub: owner workbench-contribs, no kind or parent; the contract is copied from `fragments/workbench-contribs.yaml`.
- `editor-service.save` calls always send `skip_save_participants` (the owner reads it); save-as and save-without-formatting pass now.
- Replace-all scenarios use editor's `editor-dirty` fixture. `editor-seed` holds no text model, only command registrations. The first edit (open `src/main.ts`) applies. The provider's matches in closed files fail with `model-is-disposed`, because bulk text edits do not resolve models of closed files (`ITextModelService.createModelReference`). That waits on workbench-contribs or editor.
- The `commands-*` scenarios abort inside exthost's `ext-host-extension-service.activate-by-event` (`state.registry` filter), which waits on exthost. That abort also lowers this area's modeled count in the merged run.
- `text-file-models.resolve` calls editor's `model-service.create-model` on a model's first load (contents, backup or file paths; textFileEditorModel.ts:656-667). It tolerates `model-already-exists`. With this, the replace-all scenarios pass, and all of this area's merged scenarios pass with `worlds.yaml`.

## Fix round (after judging)

`gen/files-search-scm/gen.py` applies this round through `fixround.py` (with `fixround_post.py`
for scenarios, `fixround_{textfiles,search,files}.yaml` for interfaces and `fixround_stubs.yaml`
for the owners' contracts, frozen when copied). Regenerating reproduces the fragment byte for byte.

Fixes (citations relative to the snapshot):
- **One owner for document text (contract 2, E7–E9).** `text-file-models.models[uri]` holds only
  file state: `dirty`, `saved_version_id`, `mtime`, `etag`, `size`, `encoding`, `eol` and the
  conflict/error/orphaned/readonly flags (plus a transient `ignore_dirty`). Text and versions come
  from the editor: `text-model.get-value` / `set-value` / `model-service.create-model`.
  - New `text-file-models.update-text-model` = `doCreateTextEditorModel` / `doUpdateTextModel`
    (textEditorModel.ts:169-184, textFileEditorModel.ts:669-678): `set-value` on an existing text
    model (dirty tracking ignored meanwhile), else `createModel`.
  - `resolve`, `revert`, external reloads (`on-did-files-change` → resolve) write through it, so
    the editor sees reverted/reloaded text (E8, E9).
  - `saved_version_id` is the text model's **alternative** version id at save and on
    `setDirty(false)` (textFileEditorModel.ts:1100-1108); `on-model-content-changed` compares
    the alternative version id (712-731). E7b passes.
  - `save` writes the text model snapshot taken after the participants (1027-1043); `backup`,
    `find-matches`, and the move/copy dirty snapshot read the text model.
  - `get` keeps its shape: the file state merged with the text model's value/version_id/
    alternative_version_id/language_id (model.textEditorModel).
- **Save/revert commands use the active editor (E1, X7).** New `file-commands.resolve-command-editor`
  (fileCommands.ts:416-439): URI argument → open-editors selection (`input.resource`) → active
  editor of the active group (`editor-groups.get-state`); nothing to do when none. Revert catches
  failures and shows an error notification (fileCommands.ts:586-596).
- **`text-file-service.create` keeps the content** (textFileService.ts:253-264;
  workingCopyFileService.ts:371-372 forwards `contents` to `file-service.create-file.content`).
- **Search streams (contract 3, S1).** `search-service.text-search-split-sync-async` now has the
  code's shape: onProgress is `yield {resource, matches}` (open-editor matches first, then the
  provider's progress unless an open editor matched the file, searchService.ts:116-163); it
  returns `{sync_results, async_results}`. New `search-service.text-search` (searchService.ts:82-91).
  The provider call streams (`stream: true`) and sends `folder_encodings` (map folder →
  fileEncoding, the exthost owner's shape). `search-model.search` takes each item into the
  result tree as it arrives.
- **TextSearchManager and ripgrep (my paths).** `text-search-manager.search`
  (textSearchManager.ts:49-102, 223: canonical encodings, maxResults trim, limitHit, token cancel)
  over `ripgrep-text-search-engine.provide-text-search-results` (ripgrepTextSearchEngine.ts:29-173:
  per-file progress, hitLimit at maxResults, cancel kills rg) reading `disk.read-file`.
- **Cancel (S2).** `search.action.cancel` → `search-view.cancel-search` → `search-model.cancel-search`
  cancels the running search's token (`cancel:`, searchModel.ts:381-387); results stay.
  A new search cancels the previous one (searchModel.ts:219).
- **Workspace symbols.** `_executeWorkspaceSymbolProvider` asserts a string query
  (`unexpected-type`, search.contribution.ts:242-247) and runs `getWorkspaceSymbols` over the new
  `workspace-symbol-provider-registry` (search.ts:56-130), each provider via
  `ext-host-language-features.provide-workspace-symbols` on eh (stub, owner exthost).
- `files-eol` config defined here (files.contribution.ts:216-230), as the editor's reference expects.
- Features: `save-and-revert` (files-save, files-revert), `auto-save` (files-save-model),
  `file-watching` (files-external-change), `search` (search-find-in-files), `scm` (scm-input-type,
  scm-accept-input).

### Breaking changes

| Change (citation) | Broken caller | What it must now do |
|---|---|---|
| `text-file-models` holds no text (contract 2) | shared fixture `dirty-editor` (coordinator) | seed `text-model@w1` with the dirty text (as editor's `editor-dirty` does); until then every scenario on `dirty-editor` without `editor-dirty` fails with `model-is-disposed` when saving/backing up: workbench-shell `workbench-shell-auto-save-after-delay`, `-auto-save-on-content-change`, `-close-editor-auto-save-fails-asks`, `-close-editor-auto-save-focus-change`, `-close-editor-auto-save-window-change`, `-close-editor-dirty-dont-save`, `-close-editor-dirty-revert-fails`, `-close-editor-dirty-save`, `-editor-service-save-and-close`; exthost `exthost-api-call-document-save`, `exthost-api-call-workspace-save`; builtin-extensions `builtin-extensions-git-commit-save-all-first`; main-process `main-process-reload-hot-exit-off-clears-dirty` |
| same | `dirty-editor` fixture fields `value`, `version_id` on `text-file-models@w1` | drop them (ignored now) |
| same | oracle `oracle-files-search-scm-autosave-after-short-delay`, judge `bench-c4-restart-restores-dirty` | read the text from `state['text-model@w1'].models[uri].value` (or `files-model-get`'s `model.value`) |
| `search-service.text-search-split-sync-async` returns `{sync_results, async_results}` and yields matches (searchService.ts:116-163) | no other fragment; judge S2 and oracle encoding only check ok/error | — |
| `_executeWorkspaceSymbolProvider` queries `WorkspaceSymbolProviderRegistry` (search.ts:56-83) | exthost `main-thread-language-features.register-navigate-type-support` | register with `workspace-symbol-provider-registry.register {handle, extension_id}` (mainThreadLanguageFeatures.ts:488-509), not `language-features-service` |
| `text-search-manager` / `ripgrep-text-search-engine` model textSearchManager.ts and ripgrepTextSearchEngine.ts (this area's paths) | exthost `ext-host-search.provide-text-search-results` + `ext-host-search.run-ripgrep` duplicate them with generated matches | call `text-search-manager.search` (stream) and yield its items; then judge `bench-s1-gap-provider-limit` passes (today the stand-in reports `util.ts` ×2 and the view counts 4) |

### Remaining
- E3 (1750 ms onWillSave budget, Skip) is exthost's row.
- `ripgrep-text-search-engine` walks a fixed list of workspace files (`src/main.ts`, `src/util.ts`,
  `README.md`, `package.json`) or `folder_options[].files`: the `disk` store has no listing
  interface (request to platform-core: `disk.list`, a `query` over `files` that returns keys).
  `text-search-manager` runs in the extension host in the code but sits in this area's window
  group, so calls from eh1 run it on w1.
- `oracle-exthost-workspace-symbols-empty-query` aborts inside exthost's
  `ext-host-commands.execute-command` (`input.retry`).

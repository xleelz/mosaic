# Editor area notes (src/vs/editor/**, VS Code 1.144.0 @ 2c33b50b16)

Fragment: `examples/vscode/fragments/editor.yaml`. Skips: `examples/vscode/skips/editor.json`.
Check (skeleton + fixtures + this fragment, `--strict-citations --inventory --behavior-coverage --lint hollow --no-mocks -v`):
0 errors, 0 warnings, 120/120 scenarios, 1698 citations ok, behavior coverage 731/744 (98.3%),
hollow lint clean, 0 mocks. Inventory: 450 editor entries, 427 covered by line, 23 skipped.

## 1. Entry points

| Kind | Entries | Covered by | Skipped |
|---|---|---|---|
| vscode-command | 367 (373 ids: `FoldLevelAction.ID(i)` is editor.foldLevel1..7) | `<component>.cmd-<id slug>` citing the registration line, reached through `editor-command.run-command` (flow `editor-run-command`, dynamic `targets`) | 9 |
| workbench-contribution | 53 | `<contribution component>.construct` citing the `registerEditorContribution` line (and the constructor), reached from `code-editor-contributions.instantiate-some` (flow `editor-create-widget`) | 4 |
| service | 28 | the implementation component cites the `createDecorator` line (and `registerSingleton`); reached through behaviors or the narrative flow `editor-service-registrations` | 10 |
| process-main | 2 | `editorWebWorkerMain` -> flow `editor-worker-start` (`editor-worker.bootstrap`) | 1 (`editor.main`) |

Skip groups (each entry listed in skips/editor.json):
- 7 commands, 4 contributions, `IStandaloneThemeService`: under `src/vs/editor/standalone/**`, the Monaco standalone build; the workbench never loads them (it has its own inspect tokens, quick access, references).
- `src/vs/editor/editor.main`: the Monaco ESM entry, not a VS Code process.
- `editor.action.inlineSuggest.dev.extractRepro`, `editor.action.forceRetokenize`: developer diagnostics.
- 9 services whose `registerSingleton` implementation lives in another area: IBulkEditService, IRenameSymbolTrackerService (workbench-contribs); ICodeEditorService, ILanguageService, IModelService, ITextModelService, ITextResourcePropertiesService, ITreeSitterLibraryService, ITreeSitterThemeService (workbench-shell).

Commands are grouped by behavior depth:
- Hand-modeled (real edits on the text model): `type`, `undo`, `redo` (not in the inventory; `MultiCommand`/`EditorHandlerCommand`), `deleteLeft`, `editor.action.transformToUppercase`, `editor.action.insertFinalNewLine`, `editor.action.commentLine`, `editor.action.formatDocument`.
- Routed (one step into a modeled component): cursor/selection/word moves -> `cursors-controller.set-cursor-states`; scrolls -> `code-editor-widget.reveal`; line/word/indent/comment edit commands -> `code-editor-widget.execute-commands` with no computed edits (see gaps); find commands -> `find-controller.*`; folding -> `folding-controller.run-folding-action`; suggest -> `suggest-controller.*`; go to/peek -> `symbol-navigation-action.run`; code actions -> `code-action-controller.manual-trigger`; format selection -> `format.format-document-ranges-with-selected-provider`; hover show/hide, rename, cancelOperation, snooze/cancelSnooze, leaveEditorMessage, closeReferenceSearch; `_execute*`/`_provide*` API commands -> `text-model-resolver-service.create-model-reference` + `language-features-service.invoke-providers`.
- Stubs (registered, UI/view only, summary says so): hover scrolling, suggest widget focus/selection, sticky scroll, diff editor toggles, inline suggestion navigation, peek focus, etc. 336 of my interfaces carry behavior; every behavior command runs in a generated multi-step scenario `editor-run-command-<component>`.

## 2. Components (main ones, with code)

- `code-editor-widget` (CodeEditorWidget, codeEditorWidget.ts:1107-1161, 1255-1329): focus and readOnly per window, trigger/type routing, executeEdits/executeCommands/pushUndoStop, onDidAttemptReadOnlyEdit. `capacity: {concurrency: 1}` (single renderer thread).
- `view-model` (viewModelImpl.ts:1202-1221) readOnly gate; `cursors-controller` (cursor.ts:354-585) cursor state and typing.
- `text-model` (textModel.ts) models by URI: value, versionId, alternativeVersionId, language; `apply-edits` bumps the version and publishes `text-model.on-did-change-content` (`delivery: sync`). `edit-stack` (editStack.ts:384-441) open/closed undo elements.
- `editor-contribution-registry` (EditorExtensionsRegistry: command table with target/kind/writable precondition, contribution table with instantiation mode) and `editor-command` (EditorCommand.runEditorCommand, editorExtensions.ts:302-326).
- `code-editor-contributions` (codeEditorContributions.ts:43-165): Eager now, AfterFirstRender/BeforeFirstInteraction at idle, Eventually at idle or 5 s, once per mode, constructor errors skipped.
- `find-controller` + `find-model`; `folding-controller` + `folding-model` + `indent-range-provider`; `suggest-controller` + `suggest-model` + `suggest-memory-service` + `snippet-controller2`; `content-hover-controller`; `code-action-controller` + `code-action-model`; `format` (format.ts functions) + `formatting-conflicts` + `format-actions`; `rename-controller` + `rename-skeleton`; `symbol-navigation-action` + `symbol-navigation-service` + `references-controller`; `message-controller` + `read-only-message-controller`; `language-features-service` (providers per feature); `language-configuration-service`; `editor-worker-service` + `worker-manager` + `editor-worker`; `worker-based-diff-provider-factory-service`; `inline-completions-service`; `editor-cancellation-tokens`.
- One component per remaining contribution class and per action file (lines-operations, word-operations, multi-cursor-selection-controller, ...). 104 own components: above the 90 target because every workbench-contribution needs its own component.

## 3. Boundary stubs and whose contract

| Stub | Owner | Contract from |
|---|---|---|
| `command-service.execute-command` | platform-core | owner fragment (request, errors) |
| `undo-redo-service.undo` / `.redo` | platform-core | owner fragment (undo); redo: shared shapes |
| `notification-service.notify` | workbench-shell | owner fragment (severity, message) |
| `bulk-edit-service.apply` | workbench-contribs | owner fragment, copied exactly (edits items `type/op/resource/target/needs_confirmation`, `show_preview`, `respect_auto_save_config`, `label`, errors); my response lists what the owner returns (`aria_summary`, `is_applied`, `resources`) |
| `text-file-models.on-model-content-changed` | files-search-scm | owner fragment, copied exactly (kind event; resource, value, alternative_version_id, is_undoing_or_redoing) |
| `commands-registry` (component only) | platform-core | owner kind/parent, so `editor-seed` validates alone. Since one-window-folder now seeds workbench-shell's `workspace-trust-management-service`, a standalone check needs workbench-shell.yaml too |
| `default-formatter.select-formatter` | workbench-contribs | owner fragment (formatters, mode, language_id) plus a `formatter` response |
| `code-editor-service.open-code-editor`, `text-model-resolver-service.create-model-reference` | workbench-shell | shared shapes (no owner interface yet) |
| `ext-host-language-features.<provide-*>` (24 RPCs, `on: eh<N>`) | exthost | shared shapes; responses with fixed examples so providers answer deterministically |
| `storage-db.workspace-write` | shared | shared infra naming |

Contracts I own that others call: `text-model.push-edit-operations` (accepts `uri` or `resource`; callers send `resource`), `format.format-document-with-selected-provider` and `format.format-document-ranges-with-selected-provider` (field `resource`; I renamed my component from editor-format to `format` to match workbench-contribs' stub), `EditorTextEdit` (now defined in the skeleton; I do not redefine it). The format-on-save participant itself (saveParticipants.ts) is modeled by workbench-contribs; I read the brief's rule as "editor owns the formatting providers the participant invokes" and dropped my duplicate.

## 4. Config

All defaults come from `editorOptions.ts` via `editorConfigurationSchema.ts:363` (`registerConfiguration`), or the cited `registerConfiguration`. product.json sets none of them, so deployed = default for every one.

| Config (owned) | Key | Value = default | Sources |
|---|---|---|---|
| editor-format-on-save-mode | editor.formatOnSaveMode | file | files.contribution.ts:396-398, saveParticipants.ts:254 (read only by workbench-contribs' participant) |
| editor-goto-location-multiple-definitions | editor.gotoLocation.multipleDefinitions | peek | editorOptions.ts:2243 |
| editor-goto-location-multiple-references | editor.gotoLocation.multipleReferences | peek | editorOptions.ts:2247 |
| editor-folding | editor.folding | true | editorOptions.ts:6383 |
| editor-folding-strategy | editor.foldingStrategy | auto | editorOptions.ts:6386-6388 |
| editor-suggest-selection | editor.suggestSelection | first | editorOptions.ts:6805-6807 |
| editor-hover-enabled | editor.hover.enabled | on | editorOptions.ts:2399 |
| editor-rename-enable-preview | editor.rename.enablePreview | true | rename.ts:534-539 (defined, not branched on: the preview handler is the bulk edit service's) |

Referenced, owned elsewhere: `editor-format-on-save` (files-search-scm, via the `format-on-save` fixture). Code constants used as literals with citations (not settings): computeMoreMinimalEdits race 1000 ms (editorWorkerService.ts:157), worker idle 5 min / check every 2.5 min (editorWorkerService.ts:45, 363), suggest memory persist 500 ms (suggestMemory.ts:241), MATCHES_LIMIT 19999 (findModel.ts:81), snooze 300000 ms (inlineCompletionsService.ts:66), contributions Eventually 5000 ms.

## 5. Fixtures and requests

Defined in my fragment (decision 10):
- `editor-seed`: registers every editor command in platform-core's `commands-registry` (EditorCommand ids -> `editor-command.run-command`, the handler Command.register installs; `_execute*`/`_provide*` API commands -> their `cmd-*` interface).
- `editor-main-open` (one-window-folder + editor-seed): src/main.ts open, focused and clean in w1 (`text-model@w1`, `code-editor-widget@w1`, `cursors-controller@w1`).
- `editor-dirty` (dirty-editor + editor-seed): the same with the unsaved version 2 value, matching `text-file-models@w1`.
- `editor-ts-providers`: typescript-language-features providers in `language-features-service@w1`.

Requests for shared fixtures: none beyond the shared worlds extending `editor-seed`. Platform-core's `command-service.try-execute-command` needs `editor-command.run-command` and my API `cmd-*` interfaces in its dynamic `targets` for plans to follow them.

## 6. Unsettled by the code / assumptions

- Ranges are line/column; edits are applied last-to-first (equivalent to the buffer applying against original positions for non-overlapping edits). Edits with an empty range (`range: {}`, sent by workbench-contribs) are skipped.
- One editor per window (the focused one); multi-cursor is a count, not positions.
- The undo/redo service (platform-core) calls back into the element: I call `undo-redo-service.undo` and then `edit-stack.undo` myself to stand for that callback.
- Provider scoring is "language matches or '*'"; completion groups use an explicit `group` number.
- `FormattingConflicts.select` always has the workbench selector registered, so it always calls `default-formatter.select-formatter`.
- The `precondition: EditorContextKeys.writable` flag per command is detected from the action's definition block (writable in the next 15 lines of the id); other context-key preconditions are not modeled.
- Idle-time contribution instantiation is modeled as 1 ms after creation (real time depends on idle callbacks).

## 7. Docs/common knowledge vs code

- "Format on save formats the document": the code skips SaveReason.AUTO saves (saveParticipants.ts:231-233), so auto save never formats.
- "Go to Definition jumps": with several results the default (`peek`) opens the peek widget, not the first result (goToCommands.ts:180).
- The default `editor.suggestSelection` is `first`, so suggestion memory selects nothing unless changed; it still persists (an empty strategy) 500 ms after each accept.

## 8. Simulator gaps

- Regex, whole-word and preserve-case find are not computable in CEL; find is literal (findModel.ts:507-513).
- The ICommand edits of most line/word commands (sort, move, join, transpose, indent ...) are not computed; those commands record the command and apply no edit.
- `computeMoreMinimalEdits` races a timeout with `Promise.race`; modeled as `timeout_ms: 1000` with a fallback, which is the same outcome.
- Hover results arrive in resolve order as an async iterable (getHover.ts:40); modeled as `join: all`.
- A boundary stub returns its schema's fake data, so branches that depend on another area's negative answer cannot be driven standalone: `bulk-edit-service.apply` returning `is_applied: false`, rename providers rejecting (`reject_reason`), a provider returning zero formatting edits. These 7 if-branches are the unexecuted ones in the behavior coverage report.
- The indentation folding provider is not computed (returns its example region).

## 9. Known gaps

- Inline completions (ghost text), code lens, inlay hints, semantic tokens, links, color picker, sticky scroll, linked editing, word highlighter, bracket matching are at the command/contribution level only.
- Merged run with all current fragments: `editor-suggest-accept-with-command` aborts inside platform-core -> exthost `extension-service.activate-by-event` (missing `activation_kind`), a seam between those two areas, not in editor code. All other editor scenarios pass in the merged run.
- Stub disagreements left in the merge are between other areas' stubs (kind module vs service for command-service / bulk-edit-service); mine match the owners.

## Reconciliation round

- Decision 8: `text-model.apply-edits` and `apply-undo-redo` call `text-file-models.on-model-content-changed` after publishing `on-did-change-content` (undo/redo passes `is_undoing_or_redoing` and the restored alternative version, so going back to the saved version clears dirty in files-search-scm).
- Decision 5: bulk-edit calls send the owner's request (no `code`; `respect_auto_save_config: true` as rename and code actions pass it); code-action and rename edits carry `type: text, op: edit`.
- Decision 6/10: fixtures above; scenarios use them instead of per-scenario seed state.
- Commands accept `args` as an object or the positional list the command service passes.
- `text-model` interfaces accept `resource` as well as `uri` (callers in workbench-contribs send `resource`).
- Skip reasons reworded to the allowed forms (not an entry point / another area owns it / developer tooling).
- Generator: `examples/vscode/gen/editor/gen.py` (inputs core.yaml, extra.yaml, scenarios.yaml, cmds.json, editor_inv.json).
- The 7 negative-answer branches still can't be driven: ext-host-language-features (rename rejections, empty formatting edits) has no owner definition in exthost yet, and bulk-edit `is_applied: false` needs the owner's preview choice, which a fragment-standalone scenario cannot name.

## Fix round

### Fixes
- **`text-model.set-value`** (contract 2, shipped first): `{uri, value}` → `{uri, version_id, alternative_version_id}`. Replaces the text, `_increaseVersionId` (both ids = version+1, no equality short-cut), clears the model's undo history (`edit-stack.clear`, EditStack.clear → removeElements), pushes no undo stop, publishes one flush `on-did-change-content` (`is_flush: true`) and calls `text-file-models.on-model-content-changed` like every content change (textModel.ts:484-493, 514-545; editStack.ts:408-410; textFileEditorModel.ts:687). Unknown model → `model-is-disposed`; null value → `illegal-argument`. Scenarios `editor-set-value-*`.
  - Note for files-search-scm: the real listener runs for setValue/updateModel too; TextFileEditorModel suppresses dirty with its own `ignoreDirtyOnModelContentChange` flag while resolving/reverting (textFileEditorModel.ts:408-416, 673-677, 710). The file model must hold that flag; the editor doesn't skip the call. Also: the real revert path is `ModelService.updateModel` (pushEditOperations between two pushStackElement, so undoable; modelService.ts:365-386), not setValue; the contract picked setValue.
- **Undo goes through the undo/redo service (E7 claims 2–3).** `edit-stack.push-edit-operation` pushes each new element to `undo-redo-service.push-element` (editStack.ts:412-419) and records the cursor (beforeCursorState). `text-model.undo/redo` ask the service first and run `edit-stack.undo/redo` only when it returned an element; undo restores the recorded cursor (editStack.ts:220).
- **files.eol on create (oracle modelService.test.ts:50).** `model-service.create-model` reads `files.eol` through `configuration-service.get-value` with `resource` and `override_identifier` (modelService.ts:184-212) and stores `default_eol` (LF/CRLF; `auto` → LF, Linux). `text-model.get-value` returns `default_eol` too (additive). Config `files-eol` is a boundary copy (owner files-search-scm, files.contribution.ts:216-230).
- **Double-click selects inside brackets (oracle viewController.test.ts:118).** New `view-controller.dispatch-mouse` (viewController.ts:217-308): 4+ clicks select all, 3 `_lineSelect`, 2 → `editor.doubleClickSelectsBlock` bracket scan (after an opener / before a closer, nesting by depth; viewController.ts:140-158) else `_wordSelect`; modifiers/drag route to their commands. `_wordSelect` now computes the word (or whitespace gap) selection (cursorWordOperations.ts:741-783); `cursors-controller` holds `selection`.
- Features: `feature:editing` (editor-type-text, editor-mouse-click), `feature:language-features` (editor-hover).

### Breaking changes
None to other areas. All shape changes are additive: `get-position` and `get-value` gain `selection`/`default_eol`; `set-cursor-states`, `add-model` and `on-did-change-content` gain optional inputs; `cmd--wordselect` now returns `{selected}`. Grepped fragments, judge and oracle: no external caller reads the old shapes. Own scenarios `editor-undo-nothing`/`editor-redo-nothing` updated (edit-stack is no longer called when the service has nothing).

### Still open / explained
- `oracle-editor-double-click-selects-bracket-content` drives `_wordSelect` directly; in the code `_wordSelect` never selects bracket content (that is dispatchMouse), so it selects the gap 10–11. The real path passes in `editor-mouse-double-click-bracket-content`.
- `oracle-editor-eol-setting-respected-by-root` needs a `/myroot`-scoped `files.eol` the scenario never sets; it waits on C6 (resource-scoped settings, workbench-shell/platform-core) plus a scenario setting. LF cases pass.
- E7b (saved_version_id = alternative id), E8, E9: files-search-scm must store `saved_version_id` from the alternative id and call `text-model.set-value`/`get-value` instead of keeping `value`.
- `edit-stack.clear` doesn't remove the service's elements: platform-core has no `undo-redo-service.remove-elements` (undoRedoService removeElements). After setValue the service still lists a 'Typing' element; undo then finds no edit-stack element and does nothing.
- String-content double-click (`_trySelectStringContent`) and separator words in `_wordSelect` are not modeled.
- Standalone (editor + skeleton + fixtures only) the undo/redo-nothing and EOL scenarios fail because bodiless stubs return placeholder values; they pass merged.
- X1: `text-model.add-model` now calls `workbench-language-service.request-rich-language-features` (textModel.ts:406), so a fresh resolve fires `onLanguage:<id>`. `bench-x1-open-ts-file` still fails because `full-window` already holds main.ts's text-file model, so `text-file-models.resolve` reuses it and never creates a text model. The scenario has to open a file with no model yet (or start from a world without the seeded main.ts model). No language-change interface is modeled yet, so only creation requests features.

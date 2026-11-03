# notebook-webview: notes

Fragment: `examples/vscode/fragments/notebook-webview.yaml`. Skips: `examples/vscode/skips/notebook-webview.json`.
Paths below are relative to the snapshot (vscode 1.144.0). `nb/` = `src/vs/workbench/contrib/notebook/`.

Check (skeleton + fixtures + this fragment, `--strict-citations --behavior-coverage --lint hollow --no-mocks -v`):
validation 0 errors / 0 warnings; 69 scenarios pass, 0 warnings; 0 mocks; citations 637/637 ok;
hollow lint 0 failing (3 advisory "no state change" on refusal/no-op scenarios); behavior coverage
833/836 steps (99.6%), 2 unexecuted `if` branches (explained in §6). Area entries: 223; 93 covered by line, 130 skipped.

## 1. Entry points

Covered (93):
- **vscode-command (44)**. Through `notebook-action.run` (NotebookAction/NotebookCellAction/NotebookMultiCellAction
  `run` → `runWithContext`, coreActions.ts:159-279; a dynamic call with `targets`): cell commands moveUp/moveDown/
  copyUp/copyDown/changeToCode/changeToMarkdown; clipboard copy/cut/paste/pasteAbove; delete, clearOutputs,
  clearAllCellsOutputs, changeLanguage; execute, cell.execute, executeCellsAbove, executeCellAndBelow,
  executeAndFocusContainer, cell.cancelExecution, executeAndSelectBelow, executeAndInsertBelow, cancelExecution,
  interruptExecution; the 8 insert-cell commands. Own flows: `_notebook.selectKernel`,
  `notebook.clearNotebookKernelsMRUCache`, `_resolveNotebookContentProvider`, `_resolveNotebookKernels`,
  `notebook.section.runSingleCell`, `notebook.section.runCells`, `workbench.action.webview.reloadWebviewAction`,
  `_interactive.open`, `interactive.execute`, `interactive.input.clear`, `interactive.history.previous/next`.
- **service (14)**: INotebookService, INotebookEditorModelResolverService, INotebookKernelService,
  INotebookKernelHistoryService, INotebookExecutionService, INotebookExecutionStateService,
  INotebookCellStatusBarService, INotebookRendererMessagingService, INotebookEditorService, IWebviewService
  (desktop impl ElectronWebviewService), IWebviewWorkbenchService (WebviewEditorService), ICustomEditorService,
  IInteractiveHistoryService, IInteractiveDocumentService.
- **workbench-contribution (31)**: all, via flow `notebook-startup` (`notebook-contrib.instantiate-contributions`
  calls each contribution's `start`, its constructor).
- **extension-point (4)**: notebooks, notebookRenderer, notebookPreload, customEditors (handler flows).

Skipped (130, grouped; exact entries in the skips file):
- 65 UI toggles ("UI toggle: no state beyond the layout"): collapse/expand/toggle outputs and output scrolling,
  find widgets (notebook and webview), arrow navigation and focus, fold/unfold and section fold/expand, layout
  and toolbar toggles, line numbers, outline toggles, sticky scroll, breadcrumbs, cell edit/quitEdit, render all
  markdown, reveal running/failed cell, show empty outputs, output select all, open variables view, interactive
  scroll/focus, multicursor commands, getting started walkthrough.
- 18 notebook diff editor commands (diff editor not modeled) + 2 inline-diff factories + the diff web worker
  service and its `notebookWebWorkerMain` process-main.
- 8 chat / inline chat commands (cell chat, fix/explain error, failure actions, add output to chat, kernel
  variable picker): delegate to the chat area.
- 7 developer commands (troubleshoot layout, clipboard log, view zones, editor-type cache, webview devtools).
- 5 indentation commands + selectIndentation (delegate to editor indentation); split/join (4) and
  commentSelectedCells (bulk text edits); notebook.format / formatCell (editor formatting providers);
  detectLanguage (language detection service).
- 5 cell output actions (clipboard, save image, open output in editor/preview); 3 variables commands;
  setProfile; saveMimeTypeOrder.
- Helper services: keymap recommendations, logging, outline factories.

The exthost-rpc and exthost-customer entries for the Notebook/Webview/CustomEditor/Interactive shapes live in
`src/vs/workbench/api/**` and belong to exthost; I only stub the ExtHost* RPCs my code calls.

## 2. Components (code references are in each entity's `sources`)

Notebook: `notebook-service`, `notebook-provider-info-store`, `notebook-text-model` (all open documents, keyed by
URI), `notebook-model-resolver-service-impl`, `simple-notebook-editor-model`, `notebook-file-working-copy-model`,
`notebook-editor-input`, `notebook-editor-widget` (+ `notebook-editor-context-keys`), `notebook-editor-widget-service`,
`notebook-kernel-service`, `notebook-kernel-history-service`, `kernel-picker-mru-strategy`, `notebook-kernel-view`,
`notebook-execution-service` (+ `format-on-cell-execution-participant`), `notebook-execution-state-service`,
`notebook-cell-status-bar-service`, `notebook-renderer-messaging-service`, action components (`notebook-action`,
`notebook-cell-commands`, `notebook-cell-operations`, `notebook-clipboard-contribution`, `notebook-edit-actions`,
`notebook-execute-actions`, `notebook-insert-cell-actions`, `notebook-section-actions`, `notebook-api-actions`),
22 notebook contributions. Webview: `electron-webview-service`, `webview-element`, `webview-editor-service`,
`lazily-resolved-webview-editor-input`, `webview-panel-contribution`, `reload-webview-action`. Custom editors:
`custom-editor-service`, `contributed-custom-editors`, `custom-editor-model-manager`,
`custom-editor-resolver-contribution`, `custom-editor-input`, `complex-custom-working-copy-editor-handler`.
Interactive: `interactive-history-service`, `interactive-document-service`, `interactive-editor-input`,
`interactive-window-actions`, 3 contributions. Module groupings: `notebook-contrib`, `webview-contrib`,
`custom-editor-contrib`, `interactive-contrib` (parent `workbench`).

## 3. Boundary stubs (no owner fragment existed when written; shared shapes, my call sites only)

- exthost: `extension-service.activate-by-event` (seam; request field `activation_event`),
  `ext-host-notebook-controller.{data-to-notebook, notebook-to-data, save-notebook, provide-notebook-cell-status-bar-items}`,
  `ext-host-notebook-kernels.{execute-cells, cancel-cells}`, `ext-host-webviews.on-message`,
  `ext-host-webview-panels.deserialize-webview-panel`, `ext-host-custom-editors.on-save`,
  `ext-host-interactive.will-add-interactive-document` (all kind rpc, `attributes.shape` set); caller-only
  components `main-thread-*`.
- workbench-shell: `workspace-trust-request-service.request-workspace-trust` (response `trusted`),
  `editor-service.open-editor` (seam). platform-core: `configuration-service.update-value`.
  files-search-scm: `working-copy-file-service.add-save-participant`. workbench-contribs: `bulk-edit-service.apply`.
- shared infra: `disk.read-file` (store get on `files`, not_found `file-not-found`), `disk.write-file` (store put),
  `storage-db.workspace-write`.

## 4. Config

| id (key) | deployed | default | sources | notes |
|---|---|---|---|---|
| notebook-experimental-remote-save (notebook.experimental.remoteSave) | false | false | notebook.contribution.ts:1248-1253, product.json | default is `product.quality && quality !== 'stable'`; this OSS product.json has no `quality`, so false. Insiders builds would default true (save via $saveNotebook). |
| notebook-confirm-delete-running-cell | true | true | notebook.contribution.ts:1214-1218 | |
| notebook-format-on-cell-execution | false | false | notebook.contribution.ts:1209-1213 | |
| notebook-backup-size-limit (KB) | 10000 | 10000 | notebook.contribution.ts:1291-1295 | |
| interactive-window-prompt-to-save-on-close | false | false | interactive.contribution.ts:856-860 | false → interactive notebooks are scratchpads (never dirty). |

All are mine; I reference none owned by others. No deployed/default differences in this build except the
quality-dependent remoteSave default noted above.

## 5. Fixture requests

The shared fixtures have no notebook world. Scenarios add it on top of `one-window-folder` via `state`
(YAML anchors `*ser`, `*models`, `*widget`, `*kernbound`, `*disknb`). Requested for the coordinator:
- disk: `file:///work/app/analysis.ipynb` (a small ipynb).
- a "notebook-open" fixture: vscode.ipynb activated with serializers `jupyter-notebook` and `interactive`
  registered; analysis.ipynb open in w1 with 3 cells (code, markdown, code with output).
- a kernel (controller) registered for jupyter-notebook, e.g. `ms-toolsai.jupyter/python3` (python). No built-in
  extension provides a kernel; the extension id is not one of the canonical names.

## 6. What the code didn't settle / assumptions

- Kernel ids: modeled as `<extension>/<id>` (`_notebook.selectKernel` builds `wantedKernelId` that way,
  notebookKernelView.ts:138). Kernel ordering in getMatchingKernel (sort by affinity, score, label) is not
  modeled; with two kernels the quick-pick `first_kernel` option may pick either.
- The kernel quick pick is a `choice` (`kernel-picker-mru-strategy.show-quick-pick.pick`: first_kernel |
  dismissed; default from whether kernels exist). The delete confirmation is the choice
  `notebook-edit-actions.cmd-notebook-cell-delete.confirm`.
- `resolve-kernel` calls the `_notebook.selectKernel` handler directly; the code goes through
  ICommandService.executeCommand (notebookKernelQuickPickStrategy.ts:816).
- Saving: StoredFileWorkingCopy (files-search-scm) is collapsed into `notebook-file-working-copy-model.save`
  (dirty check from storedFileWorkingCopy.ts:897-902, then snapshot + `disk.write-file`). The dirty flag is
  kept here per URI, driven by `notebook-text-model.on-did-change-content` (non-transient changes only).
- Opening reads the file with `disk.read-file` directly (IFileService/working-copy resolve not modeled);
  untitled notebooks start from empty bytes. The `data-to-notebook` stub returns a fixed 3-cell example, so an
  interactive window also starts with those 3 cells in simulation (the real ipynb serializer returns none).
- Custom document saves call `ext-host-custom-editors.on-save` directly; MainThreadCustomEditorModel (exthost)
  decides this in the real code (custom text editors save through the text file service instead).
- Webview revival calls `ext-host-webview-panels.deserialize-webview-panel` directly; the reviver object is
  MainThreadWebviewPanels'.
- Unexecuted branches: (a) `notebook-execution-service.execute-notebook-cells` untrusted return
  (notebookExecutionServiceImpl.ts:44-47): the answer comes from workbench-shell's trust stub, which returns its
  example `true`; it needs the merged model (fixture `untrusted-folder`) to run. (b)
  `notebook-renderer-messaging-service.post-message` "activation still pending" queueing: the activation
  completes in an async delivery that always runs before the next scenario step, so a second message can't
  arrive while it is pending.
- `notebook-text-model.apply-edits` applies edits in order; the real model sorts by end index and merges
  output appends (notebookTextModel.ts:716-750). Callers here send single structural edits.

## 7. Docs / common knowledge vs code

- "Run cell asks you to trust the workspace": the code calls requestWorkspaceTrust on every execution request
  (not only the first) and silently returns when declined (notebookExecutionServiceImpl.ts:43-47).
- Executions that the kernel never confirms are completed with no result right after `$executeCells`
  returns (lines 85-90) — not left pending.
- notebook.experimental.remoteSave is on by default only in non-stable (Insiders) builds.
- `_resolveNotebookContentProvider` is the API's view of contributed types; `notebook.cell.changeLanguage` to
  `markdown` converts the cell kind rather than setting a language.

## 8. Simulator gaps

- Map-keyed state can only be rewritten whole (`merge`/`omit` on `state.models` etc.), e.g.
  `notebook-text-model.apply-edits` rebuilds the cell list with `slice` and `transformList`.
- Optional request fields get fake values at entries, so absent arguments are encoded as defaults (`""`, `-1`,
  `null`) — e.g. resolver `view_type: ""` stands for "no view type" (notebookEditorModelResolverServiceImpl.ts:205-230).
- Publish topics are not followed by coverage reachability; subscribers in other areas (MainThreadWebviews,
  MainThreadInteractive, MainThreadNotebookEditors) were replaced by direct stub calls (webview `on-message`,
  `will-add-interactive-document`) or narrated notes.
- `Event.debounce`/`runWhenWindowIdle`: the 100 ms idle persistence of kernel bindings is an `emit` with
  `after_ms: 100`; the debounced dirty-editor opener of NotebookEditorManager is only narrated.
- Promise continuations that race with later user actions (renderer activation queue) can't be interleaved
  across scenario steps.

## 9. Known gaps

Notebook diff editor; notebook find/replace; outline; variables view; cell output renderers in the back-layer
webview (only renderer messaging); undo/redo; multi-cell selections (commands act on one cell); cell text edits
(join/split/format/indent); notebook backups/hot exit (only the snapshot size check); webview views
(`webviewView` is another area); custom text editors (CustomTextEditorModel); interactive window close/removal
(`willRemoveInteractiveDocument`).

## Reconciliation round (decisions 1-11)

- **Contracts copied from owners:** `extension-service.activate-by-event` (exthost: `ExthostActivateByEventRequest`
  with `activation_kind: normal`, `ExthostActivationResult`); `editor-service.open-editor` (workbench-shell
  `WorkbenchOpenEditorRequest/Result`); `workspace-trust-request-service.request-workspace-trust` (workbench-shell:
  `trusted` may be null, so the gate is `trusted == true`); `configuration-service.update-value`
  (platform-core); `bulk-edit-service.apply` (workbench-contribs; the format-on-execution participant now
  sends `edits: []`, because the formatting providers are not consulted here); `disk.read-file`/`disk.write-file`
  (platform-core: keyed by `resource`); `command-service.execute-command` (platform-core).
  `storage-db.workspace-write` values are now strings (the bindings as `key=kernel;...`).
- **Ownership fix:** boundary stubs and steps no longer cite other areas' files (extHost.protocol.ts,
  mainThread*.ts, storedFileWorkingCopy.ts, commands.ts). Those citations made the gate attribute 1,181
  entries to this fragment. Component stubs that their owners define were removed. My
  `SaveParticipantsContribution` (notebook saveParticipants.ts) is renamed `notebook-save-participants-contribution`
  because workbench-contribs models the codeEditor class of the same name.
- **Decision 9:** `kernel-picker-mru-strategy.resolve-kernel` runs `_notebook.selectKernel` through
  `command-service.execute-command` (notebookKernelQuickPickStrategy.ts:816). The handler reads its
  KernelQuickPickContext from `args[0]` and the notebook from the active editor (notebookKernelView.ts:115-130).
- **Decision 6/10 fixtures (in my fragment):**
  - `notebook-webview-seed` registers my modeled commands in `commands-registry` (NotebookAction subclasses →
    `notebook-action.run`; Action2 commands → their `cmd-*`). Handlers invoked through the command service read
    `args[0]` (section, `_resolveNotebookKernels`, `_interactive.open`, `interactive.execute`) or the active editor.
  - `notebook-webview-notebook-open`: serializers for jupyter-notebook and interactive, the
    `ms-toolsai.jupyter/python3` kernel (unbound), and analysis.ipynb open and active in w1.
- **Decision 8:** `notebook-kernel-detection.on-will-activate-by-event` subscribes to exthost's
  `extension-service.on-will-activate-by-event` and registers a kernel detection task per notebook type
  (`notebook-kernel-service.register-notebook-kernel-detection-task`). The "an inactive extension lists this
  event" check reads exthost's extension status; it is assumed true. The MainThreadWebviews/MainThreadInteractive
  listeners are still direct RPC stub calls, because exthost defines no MainThread listener for my events.
- **Ownership (cellOutput):** `notebook.cellOutput.copy` and `notebook.cellOutput.openInTextEditor` are now
  modeled (`notebook-cell-output-actions`). `notebook.cellOutput.addToChat`, `saveImage` and
  `openInOutputPreview` are not modeled. They are no longer skipped.
- **Skips (decision 11):** 93 remain: UI toggles (including the diff editor view-state commands and inline
  values), developer/internal commands, and not-an-entry-point helpers. Chat commands, diff reverts,
  indentation, formatting, split/join, detectLanguage, setProfile, saveMimeTypeOrder and the variable copy
  are no longer skipped. They count as not modeled.
- **Untrusted execution** is now exercised in the merged world (`notebook-webview-exec-untrusted-declined`:
  `untrusted-folder` and the trust modal canceled). The one branch still never run is the renderer-messaging
  "activation pending" queue (§6).

### Shared fixture requests (for fixtures.yaml)
- disk: `file:///work/app/analysis.ipynb` (a small ipynb). Scenarios still seed it in their own `state` until it is added.
- `extension-registry`: vscode.ipynb is already in `all-builtin-extensions`; `one-window-folder` lacks it.

## Fix round (FIXES.md)

Oracle fix requests 6 and 7 (oracle/editing.md) and the feature list.

- **Kernel source actions.** `notebook-kernel-service.get-source-actions` builds the
  `NotebookKernelSource` menu's actions once per notebook (key `viewType/uri`) and caches them in
  `state.kernel_sources` (notebookKernelServiceImpl.ts:312-353). Each action's `enabled` is its
  precondition evaluated with CEL `eval` against the caller's context keys (MenuItemAction,
  actions.ts:617); items whose `when` fails are hidden. The context is `input.context_keys` (the
  editor's scoped context key service) over the root `context-key-service.get-context-key-value`.
  Menu items live in `state.source_menu`; they carry `precondition_keys` because the model can't
  list a when clause's keys (an assumption of the model, not of the code).
  `run-source-action` is SourceAction.runAction (64-87): a second run while one is in flight
  joins it, and a failing command is only logged. `get-running-source-actions` is 302-310.
  `notebook-service.on-will-dispose-document` (notebookServiceImpl.ts:929-938) fires
  `on-will-remove-notebook-document`, which clears the cache and unbinds untitled notebooks
  (notebookKernelServiceImpl.ts:134-140), then `notebook-text-model.dispose` drops the model.
  Scenario `notebook-webview-kernel-source-reopen-reevaluates` is notebookKernelSource.test.ts:59.
  Not modeled: `getKernelSourceActions2` providers and the quick pick's use of source actions.
- **Output copy MIME filter.** `cmd-notebook-celloutput-copy` now follows copyCellOutput
  (cellOutputTextHelper.ts:109-128): a text-based picked MIME copies that item, otherwise the
  first TEXT_BASED_MIMETYPES item, otherwise nothing; stream MIME types join the consecutive
  stream outputs (getOutputStreamText, 62-80). The picked MIME is the first item's (the model has
  no renderer ranking). Error-output JSON reformatting (getOutputText 84-106) is not modeled.
- **Open output in text editor** now builds the URI with CellUri.generateCellOutputUriWithId
  (notebookCommon.ts:603-612): `?openIn=editor&outputId=…&notebookScheme=…`.
- **Features.** `notebook-open` is tagged `feature:notebooks`, `webview-panel-open`
  `feature:webviews`.
- **Contract 2.** This fragment never calls the editor's `text-model`, so `set-value` changes
  nothing here.

### Breaking changes

None. No existing interface changed its request or response shape. Changed behaviors only:
`cmd-notebook-celloutput-copy` (same `{copied, via}`; cellOutputTextHelper.ts:109-128) and
`cmd-notebook-celloutput-openintexteditor` (same `{opened, resource}`; the resource now has the
`?openIn=editor&outputId=…&notebookScheme=…` query, notebookCommon.ts:603-612). Their outside
callers, platform-core's command registry seed and oracle/editing.yaml, still pass.
`notebook-editor-context-keys.update-kernel-context` gained an optional `view_type` input field.

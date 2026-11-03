# workbench-shell notes

Fragment: `examples/vscode/fragments/workbench-shell.yaml` (generated from hand-written core YAML plus
a generator for the per-entry components; the output file is the artifact). Skips:
`examples/vscode/skips/workbench-shell.json` (345 entries). All paths below are relative to the
snapshot root.

Final check (skeleton + fixtures + this fragment, `--strict-citations --inventory --behavior-coverage
--lint hollow --no-mocks -v`): 226 components (194 defined here), 232 interfaces, 7 schemas, 20 flows,
98 scenarios; validation 0 errors / 2 warnings (publish topics with no subscriber inside this fragment:
`lifecycle-service.on-before-shutdown-final`, `workspace-trust-management-service.on-did-change-trust`;
other areas subscribe); 98/98 scenarios pass, 0 scenario warnings, 0 mocks; citations 934/934 ok;
hollow lint clean; behavior coverage 750/772 steps (97.2%).

## 1. Entry points

Ownership: path rules of the brief, services by the area of their workbench `registerSingleton`
implementation, plus the override `IWorkspaceTrustManagementService`. That gives 632 entries:
446 vscode-command, 139 service, 25 workbench-contribution, 19 extension-point, 2 process-main,
1 ipc-channel. 284 are covered at their lines by flow-reachable entities, 348 are skipped.

- **Commands, modeled (106)** as `cmd-<id slug>` on the component of the registering file:
  `editor-commands` (editorCommands.ts, 23: close family, keep/pin/unpin/lock, move/copy active
  editor, layouts, vscode.open, openEditorAtIndex[1-9]), `editor-actions` (Action2 classes registered
  in editor.contribution.ts, 73: split/join/focus/new/move/duplicate groups, move/split editor to
  group, tab moves, navigation next/previous/first/last, layouts, close all/left/other groups,
  revert-and-close, reopen closed editor, clear history), `workspace-actions` (6), `window-actions`
  (2), `notifications-commands` (2). All are reachable through `keybinding-service.dispatch`
  (dynamic call with `targets` = every cmd interface) and run in scenarios.
- **Commands, skipped (340)**, grouped (exact entries in the skips file):
  - UI toggle: no state beyond the layout — layoutActions, panel/sidebar/auxiliary bar/activity bar,
    title bar, status bar, banner, zen mode, menubar, views (move/reset/toggle/focus view), navigation
    actions, breadcrumbs, group maximize/minimize/sizes, list/tree commands (39), notification
    center/toast focus and position (18).
  - Developer/internal (decided rule): developerActions, `_workbench.*` (23). Note `_workbench.open`
    is folded into `cmd-vscode-open`.
  - Quick access pickers (quickOpen*, showAllEditors*, openRecent, previous-editor-from-history) and
    MRU cycling: UI only; what they open goes through `editor-service.open-editor`.
  - Not modeled, known gaps: diff/multi-diff editor commands (12), editor navigation stack
    (navigateBack/Forward/edit locations, 11), auxiliary/modal editor windows (18), split-in-group
    (7), reopen-with/editor type (4), extension bisect (3), language/EOL/encoding/indentation
    pickers (4), help/URL commands (11), web-embedder/account helper commands (8), dialog-driven
    open/save workspace variants (10), web device permission prompts (3).
- **Services (139)**: 11 modeled with behavior (editor-service, editor-resolver-service,
  editor-parts, history-service, file-dialog-service, lifecycle-service, native-workspace-editing-
  service, workspace-trust-request-service, keybinding-service, notification-service,
  workbench-host-service) plus workspace-trust-management-service (override). 120 are registration
  components (class name in kebab-case, citing createDecorator + registerSingleton), made reachable
  as narrative steps of the `workbench-shell-startup` flow. Skipped (8): IRemoteExtensionsScannerService,
  IUserDataSyncEnablementService, IUserDataAutoSyncService (remote-server's fragment defines these
  components with behavior; a second definition would be a merge conflict); ICommandService (the brief
  makes `command-service.execute-command` a platform-core seam; impl
  `src/vs/workbench/services/commands/common/commandService.ts:113`), IAgentHostFileSystemService,
  IExtensionsProfileScannerService, IImageResizeService (same-named impl classes in other areas'
  paths; duplicate component ids avoided).
- **Workbench contributions (25)**: one component each (registration line + class line) with a
  `create` interface, called by `workbench-contributions-registry.start` (phases 1-2) and
  `instantiate-phase` (3-4) during `workbench-shell-startup`.
- **Extension points (19)**: `<name>-extension-point` components citing registerExtensionPoint,
  steps of the startup flow. **ipc-channel** urlHandler: `url-handler-channel`.
- **process-main (2)**: flows `workbench-shell-language-detection-worker`,
  `workbench-shell-textmate-worker`.

Flows (20): open-editor (seam), is-opened, get-groups, close-editor, keybinding-dispatch,
shutdown (seam), will-shutdown, trust-request, trust-query, set-trust, open-files-trust,
add-folder, get-workspace, notify, get-notifications, reopen-closed-editor, get-history, startup,
two worker mains.

## 2. Components (key ones)

- `editor-service` EditorService — `src/vs/workbench/services/editor/browser/editorService.ts:540-599`;
  group finding `src/vs/workbench/services/editor/common/editorGroupFinder.ts:101-232`.
- `editor-groups` (anchor, state) — interfaces get-state (normalises missing preview/sticky/mru/
  locked of fixture groups), put-group, insert-group, delete-group, set-active-group.
- `editor-part` EditorPart — add/remove/merge/merge-all/find/activate group, apply/get layout,
  move/copy group (`src/vs/workbench/browser/parts/editor/editorPart.ts:360-1012`).
- `editor-group-view` EditorGroupView — open (pinned decision 1202-1208), close confirmation
  (1738-1883), close/closeEditors/doCloseEditors, stick/pin/lock, move/copy editor.
- `editor-group-model` EditorGroupModel — insert position, preview replacement, next active on close
  (`src/vs/workbench/common/editor/editorGroupModel.ts:290-587`).
- `history-service` — recently closed (batched, max 20), reopen, clear.
- `lifecycle-service` NativeLifecycleService — `src/vs/workbench/services/lifecycle/electron-browser/lifecycleService.ts`.
- `native-workspace-editing-service`, `workspace-context` (anchor: get-workspace, set-folders,
  set-trusted), `workspace-trust-management-service`, `workspace-trust-enablement-service`,
  `workspace-trust-request-service` (`src/vs/workbench/services/workspaces/common/workspaceTrust.ts`).
- `keybinding-service` WorkbenchKeybindingService — dispatch logic of
  `src/vs/platform/keybinding/common/abstractKeybindingService.ts:306-404` and
  `keybindingResolver.ts:320-392`; default keybindings seeded in state (14, each cited in the
  component description).
- `notification-service`, `workbench-contributions-registry`, `workbench` (startup,
  enter-eventually-phase, on-will-shutdown), `workbench-host-service`, `file-dialog-service`.

## 3. Seams I own (contracts for other areas)

- `editor-service.open-editor`: request `WorkbenchOpenEditorRequest` {resource (required), group:
  integer, default -1 = ACTIVE_GROUP, -2 = SIDE_GROUP, >=1 a group id; options {pinned, sticky,
  inactive, preserve_focus, reveal_if_opened, index}}; response `WorkbenchOpenEditorResult`
  {opened, resource, group_id, pinned, is_new}; error `invalid-editor-group-provided` (status 0,
  not retryable) for an unknown explicit group.
- `lifecycle-service.on-before-shutdown`: kind event; request `WorkbenchShutdownRequest` {reason:
  close|quit|reload|load, window_id}; response {veto, vetoed_by}. main-process calls it (vscode:
  onBeforeUnload). Participants declare `subscribe: [lifecycle-service.on-before-shutdown]` and
  answer by calling `lifecycle-service.veto {id, veto}`. Final vetoes (working copy backup tracker,
  files-search-scm) subscribe to `lifecycle-service.on-before-shutdown-final`, published only when no
  regular veto was raised. `lifecycle-service.on-will-shutdown` is the will-unload topic (joiners
  subscribe).

## 3b. Boundary stubs declared (contract source)

Owner fragments appeared while I worked; the final stubs copy the owners' request/response/kind/
errors for: `command-service.execute-command` and `configuration-service.update-value`
(platform-core), `text-file-service.save|revert` and `text-file-models.get` (files-search-scm),
`extension-service.stop-extension-hosts|start-extension-hosts` (exthost),
`native-host-main-service.get-window-count|reload|open-window|close-window` (main-process). Every
call passes the owners' optional fields explicitly (their behaviors read them).
`text-file-models.get` is declared with a `store` on the anchor's models table so the fragment-only
run reads the fixture; callers accept both the owner's `{exists, model}` and the bare row.
Interfaces other areas stubbed on my components and that I now define: `editor-service.close-editor`,
`editor-service.save`, `editor-service.save-all`, `dialog-service.confirm`, `dialog-service.prompt`,
`notification-service.prompt` (shapes copied from their stubs). Still undefined here (stubs from
others, for reconciliation): `quick-input-service.*`, `views-service.open-view*`,
`file-dialog-service.pick-*`, `remote-explorer-service.*`, `user-data-sync-workbench-service.*`,
`extension-gallery-account-service.sign-in`, `preferences-service.open-user-settings`,
`files-configuration-service.update-readonly`, `code-editor-service.open-code-editor`,
`text-model-resolver-service.create-model-reference`; workbench-contribs stubs
`workspace-trust-management-service.complete-workspace-trust-request` etc., which live on
`workspace-trust-request-service` here.

Merged run (all 13 fragments): my 98 scenarios pass except 6 that reach other areas' seams and abort
there: `disk.write-file` / `disk.read-file` store keyed by `input.uri` while files-search-scm's save/
revert path passes another field (close-editor dirty save/don't-save/autosave, save-all), and
`extension-service.activate-by-event` reading `input.activation_kind` behind platform-core's
`command-service.execute-command` (keybinding ctrl+s). Both are between those owners.

Original stub list:

- `command-service.execute-command` (platform-core; seam, shared shapes command_id/args; error
  command-not-found from the brief table).
- `configuration-service.update-value` (platform-core; shared shapes).
- `text-file-service.save` (files-search-scm seam; shared shapes: resource, options {reason, force,
  skip_save_participants}; response {resource}) and `text-file-service.revert` (shared shapes).
- `text-file-models.get` (files-search-scm anchor; originally named get-model): a store `get` on the anchor's `models`
  table so the dirty-editor fixture is read. (Owner now defines it.)

- `extension-service.stop-extension-hosts` / `start-extension-hosts` (exthost; shared shapes).
- `native-host-main-service.get-window-count|reload|open-window|close-window` (main-process; names
  predicted from NativeHostMainService).
- `storage-db.workspace-write|global-write|global-read` (shared infrastructure naming).
No owner fragments existed when I wrote these; nothing was copied from another fragment.

## 4. Config

Owned (all deployed = default; product.json overrides none): `security-workspace-trust-enabled`
(true; `src/vs/workbench/contrib/workspace/browser/workspace.contribution.ts:799-805`, read
`workspaceTrust.ts:82-88`; replaces the fixtures reference, same value), `workbench-editor-enable-preview`
(true), `workbench-editor-open-positioning` (right), `workbench-editor-focus-recent-editor-after-close`
(true), `workbench-editor-close-empty-groups` (true), `workbench-editor-reveal-if-open` (false), all
registered in `src/vs/workbench/browser/workbench.contribution.ts:321-373`.
Referenced (boundary copies): `security-workspace-trust-empty-window` (true) and
`security-workspace-trust-untrusted-files` (prompt), owner workbench-contribs;
`window-confirm-save-untitled-workspace` (true), owner main-process; `files-auto-save` from fixtures
(owner files-search-scm). No deployed/default differences found.

## 5. Fixture requests

- An untitled multi-root workspace world (`workspace-context@w1.untitled_workspace: true`); I set it
  in scenario state for now.
- Trusted-URI list for the trusted fixtures: `one-window-folder` says `trusted: true` but the trusted
  URI list (application storage) is empty, so a recomputation (startup, folder change) makes the
  folder untrusted. Scenarios that recompute seed
  `workspace-trust-management-service@w1.uri_trust_info: [file:///work/app]`. Suggest the fixture
  seeds it.

## 6. Assumptions / what the code didn't settle

- The editor grid is a flat list in grid order: left/up = previous group, right/down = next.
- `isDirty()` after a save in the close confirmation is approximated by the save result (veto when
  `text-file-service.save` fails), since the save is another area's.
- History batches: editors closed by one close operation share a batch (keyed by the operation's
  start time) instead of the microtask turn.
- Keybinding when-clauses are context-key names (or `!name`) looked up in the dispatch input's
  `context` map.
- Platform is Linux (non-mac) for the untitled-workspace prompt; `get-window-count` stub answers 1.
- `lifecycle-service` starts at phase 4 (fixtures describe a running window); startup scenarios set 1.
- Workspace trust: `is-workspace-trusted` returns true when the feature is disabled (the code computes
  it at construction; same observable result).

## 7. Docs / common knowledge vs code

- Ctrl+W on an empty group with several groups closes the group (closeGroup's when clause), not an
  editor; modeled.
- "Pin editor" (Ctrl+K Shift+Enter) makes the editor sticky; "Keep editor" (Ctrl+K Enter) ends
  preview mode — the names are easy to confuse.
- Adding a folder to a single-folder window enters an untitled multi-root workspace and restarts the
  extension hosts (no window reload locally).

## 8. Simulator gaps

- CommandsRegistry lookup: the dispatcher routes workbench-shell commands with a dynamic call on a
  `handlers` table in keybinding-service state (mirror of CommandsRegistry entries registered by this
  area), others go to `command-service.execute-command`. Real code always goes through
  ICommandService (`src/vs/workbench/services/commands/common/commandService.ts:80-105`).
- Promise joining: a second `requestWorkspaceTrust` while one is pending returns the same promise
  (`workspaceTrust.ts:897-900`); modeled as `{trusted: null, joined: true}`. The modal dialog that
  completes the request lives in contrib/workspace; its answer is the `modal` choice.
- Veto promises run in parallel (`handleVetos`) — modeled as synchronous subscribers calling `veto`.
- The 500 ms chord checker (`abstractKeybindingService.ts:175-191`) is checked lazily on the next
  keypress: a timer would delay the next scenario step past the 5 s window.
- Scenario/entry inputs get fake values for optional request fields; optional fields that change
  behavior use `default` (e.g. `update-workspace-trust.trusted: null`).

## 9. Known gaps

Diff/side-by-side/split-in-group editors, auxiliary and modal editor parts, the navigation (back/
forward) stack, editor associations and reopen-with, sticky-editor protection on Ctrl+W
(`workbench.editor.preventPinnedEditorClose`), extension bisect, startup kind from the last shutdown
reason. Unrun branches (23, listed by `--behavior-coverage`): mostly defensive guards
(invalid group ids inside internal calls, empty groups, `move-copy-active-editor` copy-by-tab and
position targets, `remove-group` merge path, `set-phase` same phase) and
`add-folders` when stopping the extension hosts is vetoed (the exthost stub always answers
`stopped: true`; needs the exthost seam to drive it).

## Reconciliation round

Generator moved to `examples/vscode/gen/workbench-shell/` (`gen.py` + `core_*.yaml`; `core_h.yaml` holds
this round's additions). Fragment-only check: 230 components, 263 interfaces, 116/116 scenarios,
990/990 citations, hollow clean, behavior 827/849 (97.4%). Merged gate: all workbench-shell scenarios
pass; modeled 222/319 = 70% (was 169/475 = 36% in the round's input, 91% after the first fix before
the invalid skips were dropped).

- **Decision 6:** fixture `workbench-shell-seed` registers the 106 workbench-shell commands in
  `commands-registry` (`command id -> cmd-* interface`). The keybinding dispatcher keeps its internal
  route for this area's commands; other commands go to `command-service.execute-command`.
- **Decision 7:** components renamed to the seam ids other areas use: `clipboard-service`
  (NativeClipboardService: write-text, read-text, write-resources, read-resources, with state) and
  `native-host-service` (WorkbenchNativeHostService: get-window-count, close-window, reload,
  open-window, show-item-in-folder, each a `nativeHost` channel call to `native-host-main-service`).
  `quick-input-service` gained pick (accept/dismiss choice) and quick-access-show. The host service
  and the untitled-workspace veto now go through `native-host-service`.
- **Decision 8:** `editor-auto-save` (EditorAutoSave, `src/vs/workbench/browser/parts/editor/editorAutoSave.ts`)
  subscribes to `working-copy-service.on-did-change-dirty` / `on-did-change-content` (schedule an
  auto save after `files.autoSaveDelay` when autoSave is afterDelay, discard when clean; the timer
  saves through `text-file-models.save` with reason auto) and to my
  `workbench-host-service.on-did-change-focus` (window blur saves all dirty editors through
  `editor-service.save-all` with reason window-change, for onFocusChange/onWindowChange).
- **Decision 9:** `extension-management-service` (ExtensionManagementService) with
  install-from-gallery (workspace-trust check for extensions without untrusted-workspace support;
  Cancel fails with `canceled`), update-from-gallery, get-installed and uninstall, each forwarding
  to remote-server's `extension-management-channel.*` (shapes copied from remote-server's stubs).
  `editor-service.save` / `save-all` / `close-editor` were already defined.
- **Decision 12:** `code-editor-service` and `tree-sitter-theme-service` are registration
  components here (inventory now assigns the two entries to editor, registered by workbench-shell).
- **Decision 13 (with the coordinator's correction):** `workbench-shell-seed` sets
  `workspace-trust-management-service: {accepts_out_of_workspace_files: false, uri_trust_info:
  [file:///work/app]}`; `workbench-shell-untrusted` extends `untrusted-folder` with an empty list.
  All my scenarios list `workbench-shell-seed` (or `workbench-shell-untrusted` instead of
  `untrusted-folder`). startup-untrusted, trust-empty-window and untrust-not-directly-trusted were
  rewritten for the seeded list; startup-trust-recomputed keeps the "list empty, recompute to
  untrusted" case.
- **Decision 11:** 76 skips whose reason was a modeling gap (diff/multi-diff, navigation stack,
  auxiliary/modal windows, split-in-group, reopen-with, extension bisect, web-embedder/account
  helpers, web device prompts, dialog-driven open variants) are no longer skips; they count as
  uncovered and are listed in `gen/workbench-shell/unmodeled-gaps.json`. 272 skips remain (UI
  toggles, developer/internal, quick-access pickers, help URLs, entries owned by other areas).
- Scenario expectations that depended on stub answers were made true under both the stub and the
  owner (e.g. the real save cleans the model; the OSS product has no marketplace, so gallery installs
  fail with not-allowed in the merged run, and the scenarios assert the hop, not the result).

Remaining merge warnings naming this fragment come from agents' stubs of my components
(`editor-service`, `lifecycle-service`, `workspace-trust-*`: kind module and parent workbench vs
my service / workspace-context; `request-workspace-trust.trusted` boolean vs my `[boolean, null]`,
which is right because the code resolves `undefined` on cancel). Agents should align.
Shared-fixture requests: none new.
- `editor-service.save` now passes the full `FilesSaveOptions` (reason, force, skip_save_participants)
  to `text-file-service.save`, and implements Save As like EditorService.save
  (`editorService.ts:1013-1043`): open the editor pinned, `text-file-service.save-as {source,
  target: null, options}`, then `editor-group-view.replace-editor` puts the saved resource in the
  old editor's place; a failed or canceled save-as returns success false.

## Fix round (after judging)

The fix-round entities live in `gen/workbench-shell/core_i.yaml` (new) and in their original
`core_*.yaml` blocks (changed); `gen.py` regenerates the fragment byte-identically.

### Fixes

- **Keybindings through the command service, `when` via `eval` (C2, contract 5).**
  `keybinding-service.dispatch` reads each key its candidates' `when` clauses mention from
  `context-key-service.get-context-key-value` (`abstractKeybindingService.ts:334`,
  `contextKeyService.ts:332-337`), overlays `input.context` as the focused target's scoped keys
  (`contextKeyService.ts:598-615`), turns every `when` into a CEL rule with `replace` (bare key is
  truthy, `key == value`, `&&`, `||`, `!`) and evaluates it with `eval(rule, {c: context})`,
  last candidate first (`keybindingResolver.ts:380-397`). Every command now goes through
  `command-service.execute-command` (`abstractKeybindingService.ts:384-391`); the direct
  `state.handlers` shortcut is gone. closeGroup's `when` is the real
  `activeEditorGroupEmpty && multipleEditorGroups` (`editorCommands.ts:866`).
- **Command palette (C3).** New `commands-quick-access` (`commandsQuickAccess.ts`):
  `get-picks` keeps CommandPalette menu items whose `when` holds (same eval path,
  `menuService.ts:181,326`), filters by label or exact id (`:99-121`), sorts recently used first
  (`:152-183`); `accept` pushes the history (`:450-457`), runs
  `command-service.execute-command`, shows `dialog-service.error` on non-cancel errors
  (`:303-324`). Flows `workbench-shell-command-palette-list` / `-run`.
- **Open resolves the model (C7).** `editor-group-view.open-editor` calls
  `text-file-models.resolve` for an active `file://` editor (`editorGroupView.ts:1288-1306`,
  `textFileEditor.ts:102-108`).
- **Modal editor part (coordinator request, remote-server's Running Extensions).**
  `editor-service.open-editor` opens RequiresModal inputs (`runtime-extensions:`,
  `vscode-workspace-trust:`; `runtimeExtensionsInput.ts:25`, `workspaceTrustEditorInput.ts:21`)
  in the modal part unless `workbench.editor.useModal` is `off` (`editorGroupFinder.ts:105-110`),
  reusing an open part (`editorParts.ts:196-240`); a normal editor opened while it is open closes
  it (`editorGroupFinder.ts:58-72`). New config `workbench-editor-use-modal` (value = default
  `some`, `workbench.contribution.ts:374-388`), component `modal-editor-part`.
- **Close confirmation.** `autoSave: onWindowChange` saves instead of asking on native Windows and
  Linux (`editorGroupView.ts:1792-1798`; `state.host_os` defaults to linux), and the
  `shouldConfirmClose` re-check after the dialog (`:1836-1845`).
- **`resolveAsync` (oracle).** `configuration-resolver-service.resolve-async`
  (`variableResolver.ts:83-331`): env, config, workspaceFolder[:name], workspaceFolderBasename,
  cwd, userHome, file, fileBasename, relativeFile, pathSeparator; command/input/unknown stay
  verbatim; VariableError -> `variable-error`.
- **AccountPolicyService (oracle).** `account-policy-service` with policy providers held as CEL
  data and run with `eval` (`accountPolicyService.ts:168-211`), `get-policy-value`
  (`policy.ts:95-108`), and `publish account-policy-service.on-did-change` (sync,
  `accountPolicyService.ts:190-192`), which platform-core's `configuration-service.on-did-change-policies`
  subscribes to. The account gate (Restricted values) and managed settings are not modeled.
- **Features.** `feature:commands-and-keybindings` (keybinding dispatch, palette list/run),
  `feature:workspace-trust` (trust request/query/set/open-files), `feature:editor-management`
  (open, is-opened, close, reopen).

### Breaking changes

No request or response shape changed. Behavior changes callers may see:

- `keybinding-service.dispatch`: the `when` of `workbench.action.closeGroup` is now
  `activeEditorGroupEmpty && multipleEditorGroups`; the synthetic key
  `activeEditorGroupEmptyAndMultipleGroups` no longer matches. Broken: judge
  `C2 bench-c2-when-true` (it must set `activeEditorGroupEmpty` and `multipleEditorGroups` in
  `context-key-service` state or `input.context`). Every command, workbench-shell's included,
  now runs through `command-service.execute-command`, so counts of that interface and of
  `extension-service.activate-by-event` go up by one per keypress.
- `editor-service.open-editor` / `editor-group-view.open-editor`: an active `file://` editor now
  calls `text-file-models.resolve` (one more call; a missing file records `open_failures` and keeps
  the editor). Inputs with scheme `runtime-extensions` or `vscode-workspace-trust` now land in the
  modal part (result `group_id: -4`), not in `editor-groups`. No other fragment's scenario broke.

### Still open

- 9 of my scenarios using `dirty-editor` fail because `text-file-models.get` now reads
  `text-model.get-value`, which has no model for main.ts in that fixture ("Model is disposed"):
  waits on editor (`editor-seed` text model) / the coordinator's `dirty-editor` (contract 2).
- Judge C4 `bench-c4-restart-restores-dirty` reads `text-file-models...value`, removed by
  files-search-scm's contract-2 change (re-scorer). `restoreBackups` belongs to files-search-scm
  (`services/workingCopy`).
- Oracle `oracle-workbench-shell-account-policy-default-account` expects a
  `get-value` read to call `account-policy-service.*`; in the code PolicyConfiguration reads
  policy values on change (`configurations.ts:232-302`), not per read, so it needs re-adapting.
- `when` translation covers keys, `==`/`!=`, `&&`, `||`, `!` and parentheses, not `=~`, `in`,
  `<`/`>` (simulator-adjacent gap: no list-to-map or regex find-all, so keys are extracted with
  `replace` + `split`).
- The code doesn't await the command from a keybinding; the model awaits it (the warning on
  rejection stays the same).
- **Banner part (X8b).** `banner-part.show` / `hide` / `render-active-item` / `get-state`
  (`bannerPart.ts:170-250`): items keyed by id, active = last item with the top priority, the
  part hides when none is left. The restricted-mode trigger, `WorkspaceTrustUXHandler.updateWorkbenchIndicators`
  (`workspace.contribution.ts:431-443`, `getBannerItem` `:555-592`), is workbench-contribs'
  `workspace-trust-ux-handler`; it must call `banner-part.show` with id
  `workbench.banner.restrictedMode` when untrusted (and `hide` when trusted).
- **`_workbench.open` (exthost request).** `editor-commands.cmd--workbench-open`
  (`editorCommands.ts:456-499`): options, a column or `untitled:` opens through
  `editor-service.open-editor` in `columnToEditorGroup(column)` (`editorGroupColumn.ts:18-40`,
  a missing column opens to the side); `command:` URIs do nothing; everything else goes to
  `opener-service.open`. Registered in `workbench-shell-seed`; its skip is gone.
  **Breaking change:** `editor-commands.cmd-vscode-open` now reads `args[0]` (the command-handler
  shape) and forwards it to `_workbench.open` via `command-service.execute-command`
  (`editorCommands.ts:445-449`); it no longer reads `input.resource` or `input.group`. In my
  fragment I fixed `workbench-shell-commands-window-workspace`. No other fragment calls the
  interface directly; callers that go through `command-service` already send `args`.
- **onLanguage activation (X1).** `workbench-language-service.request-rich-language-features`
  (`editor/common/services/languageService.ts:140-152`, once per language, basic first) and its
  listener (`workbench/services/language/common/languageService.ts:287-291`): `extension-service.activate-by-event`
  `onLanguage:<id>`, then `onLanguage`. Waits on editor: `text-model.add-model` (and the
  set-language path) must call it as `TextModel` does (`textModel.ts:406`, `:2101`); no shape
  change. Judge `bench-x1-open-ts-file` opens main.ts, whose model the seed already holds; in the
  code that reuse requests nothing (activation happened at creation), so it passes only for a file
  without a model, once editor adds the call.

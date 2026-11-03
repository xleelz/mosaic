# platform-core notes (VS Code 1.144.0, 2c33b50b16)

Fragment: `examples/vscode/fragments/platform-core.yaml`. Skips: `examples/vscode/skips/platform-core.json`.
All paths below are relative to the snapshot. The fragment was generated from hand-written parts plus a
generated block of shallow service components (`<service>.constructor` stubs).

## 1. Entry points

Owned entries are the inventory entries under `src/vs/base/**` and `src/vs/platform/**` (minus the excepted
subtrees) whose *implementation* lives in platform-core. 77 of them are covered at their lines by
flow-reachable entities, and 12 are skipped.

| Kind | Entry | Covered by |
|---|---|---|
| process-main | `files/node/watcher/watcherMain.ts:14` | flow `pc-watcher-main` (`watcher-main.main`) |
| process-main | `localTranscription/node/localTranscriptionMain.ts:13` | flow `pc-local-transcription-main` |
| process-main | `profiling/electron-browser/profileAnalysisWorkerMain.ts:9` | flow `pc-profile-analysis-worker-main` (stub entry) |
| ipc-channel | `watcher` (watcherMain.ts:21) | `universal-watcher` (+ `watcher-main.main`) |
| ipc-channel | `localTranscription` (localTranscriptionMain.ts:19) | `local-transcription-main` |
| ipc-channel | `githubCredentials` (electron-browser/githubService.ts:26) | `shared-process-git-hub-service.constructor` -> `git-hub-credentials-channel` |
| ipc-channel | `github` (remote/ipcServer.ts:28) | `git-hub-channel.constructor`, called from the constructor above |
| vscode-command | `noop` | `commands-registry.cmd-noop` |
| vscode-command | `_setContext`, `getContextKeyInfo` | `context-key-service.cmd--setcontext`, `cmd-getcontextkeyinfo` |
| vscode-command | `menu.resetHiddenStates` | `menu-hidden-states-reset.cmd-menu-resethiddenstates` -> menu-service -> persisted-menu-hide-state -> storage |
| vscode-command | `hideCodeActionWidget`, `acceptSelectedCodeAction`, `previewSelectedCodeAction` | `action-widget-service.cmd-*` |
| vscode-command | `quickInput.accept` | `quick-input-controller.cmd-quickinput-accept` |
| service | ICommandService, IConfigurationService, IFileService, IStorageService, IContextKeyService, IInstantiationService, IUndoRedoService, IMarkerService, IMenuService, IActionWidgetService | deep components with behaviors and flows |
| service | 49 more (IAccessibilityService, IAccessibilitySignalService, IActionViewItemService, IArtifactIntegrationRegistry, IPlaywrightService, IChecksumService, IContextViewService, ICSSDevelopmentService, IPlatformCustomizationMarketplaceService, IDiagnosticsService, IDownloadService, IExtensionResourceLoaderService, IExternalTerminalService x2, IBrowserResourceService, ILocalGitService, IHoverService, IImageResizeService, IMainProcessService, ISharedProcessLifecycleService, ILanguagePackService, IListService, ILogService, ILoggerService, IMarkdownRendererService, IMeteredConnectionService, IAgentNetworkFilterService, IOTelSqliteStore, INativeManagedSettingsService, IFileManagedSettingsService, IPolicyService, IV8InspectProfilingService, IProfileAnalysisWorkerService, IRemoteTunnelService, ITunnelProcessCoordinator, ISandboxHelperService, ISignService, IStateReadService, IStateService, ICustomEndpointTelemetryService, ISharedTunnelsService, IUriIdentityService, IUserDataProfilesService, IUserDataProfileStorageService, IUserInteractionService, IWebContentExtractorService, ISharedWebContentExtractorService, IWebWorkerService, IEnvironmentService, ISharedProcessGitHubService) | a component per implementation class citing the createDecorator line, with a `constructor` interface reached through `instantiation-service.get-or-create-service-instance` (dynamic call with `targets`) |

Skipped (in `skips/platform-core.json`):
- UI toggles ("no state beyond the layout"): `selectPrevCodeAction`, `selectNextCodeAction`, `collapseSectionCodeAction`, `expandSectionCodeAction`, `toggleSectionCodeAction`, `clearFilterCodeActionWidget`, `workbench.action.showHover`. (clearFilter is reported "covered" by line tolerance from the hide command's citation; it is not modelled.)
- `history.showPrevious` / `history.showNext`: widget-local input history navigation, no service state.
- `_generateContextKeyInfo`: developer diagnostics (console.log); also hit only by line tolerance.
- `externalCommand` (actions.ts:740): inventory false positive inside the generic `registerAction2` helper.
- `IProductService`: product.json as a plain object, no implementation class.

**Not mine** (createDecorator in platform but the registered implementation lives in another area; for the
coordinator to assign): IAccessibleViewService, IClipboardService (desktop NativeClipboardService), IContextMenuService
(desktop ContextMenuService in workbench; class name clashes with the platform one, so not modelled here),
ICustomizationMarketplaceService, IDataChannelService, ILinkPresentationService, IExtensionHostDebugService,
IDefaultAccountService, IDialogService, IFileDialogService, IEncryptionService, ICopilotHomeService,
IExtensionRecommendationNotificationService, IGitHubService (registered from src/vs/sessions), IGitHubCredentialBroker,
ISharedProcessService, IKeybindingService, IKeyboardLayoutService, ILabelService, ILayoutService,
ILocalTranscriptionService (workbench client), IMenubarService, INativeHostService, INotificationService,
IOnboardingTryoutHandoffService, IOpenerService (editor), IPathService, IProgressService, IEditorProgressService,
IQuickInputService (workbench subclass), IRequestService, ITelemetryService (workbench), ITerminalSandboxService,
ISecretStorageService, IThemeService, ITunnelService, IManagedSettingsService (AccountPolicyService), IURLService,
ICanonicalUriService, IEditSessionIdentityService, IWorkspaceContextService, IWorkspaceTrust*Service,
IWorkspacesService; main-process: IEncryptionMainService, IProcessService, IWebviewManagerService. Four of these
(IContextMenuService, IGitHubCredentialBroker, IManagedSettingsService, ITelemetryService, ITunnelService) show
"file only" because a platform component cites the same file.

## 2. Components

Deep: `command-service` (workbench/services/commands/common/commandService.ts:15-111), `commands-registry`
(platform/commands/common/commands.ts:67-147), `configuration-service` + `configuration-editing`
(configuration/common/configurationService.ts:27-229, configurationModels.ts:768-1070), `file-service`
(files/common/fileService.ts), `storage-service` (storage/common/storage.ts:332 + base/parts/storage/common/storage.ts:115),
`context-key-service` (contextkey/browser/contextKeyService.ts:379), `instantiation-service`
(instantiation/common/instantiationService.ts:28), `undo-redo-service`, `marker-service` + `marker-stats`,
`menu-service` + `persisted-menu-hide-state` + `menu-hidden-states-reset`, `action-widget-service`,
`quick-input-controller`, `watcher-main` + `universal-watcher`, `local-transcription-main`,
`profile-analysis-worker-main`, `git-hub-channel`, `git-hub-credentials-channel`. Plus 49 shallow service
components (section 1). Naming: implementation class in kebab-case; where the class is abstract or differs per
host (storage, policy, logger) the component is named after the decorator (`storage-service`, `policy-service`,
`logger-service`).

Flows (19): pc-execute-command, pc-get-configuration-value, pc-update-configuration-value, pc-write-file,
pc-read-file, pc-delete-file, pc-store-storage-value, pc-get-storage-value, pc-get-context-key-value,
pc-instantiate-service, pc-invoke-function, pc-push-undo-element, pc-undo, pc-can-undo, pc-change-markers,
pc-read-markers, and three process mains. It is over the 6-14 target because each process main needs its own
flow and every write flow needs a read flow.

### Seam contracts other areas should copy
- `command-service.execute-command`: request `{command_id, args}`; error `command-not-found` (status 0, not
  retryable). It resolves the handler from `commands-registry` state (`commands.<id>.handler` = interface id) and
  calls it with `{command_id, args}`. **Areas that register commands** must get a row into
  `commands-registry.state.commands` (reconciliation: generate it from every `cmd-*` interface, or call
  `commands-registry.register-command {command_id, handler}`), and their `cmd-*` interfaces should accept
  `{command_id, args}`. The handler's return value is returned as is.
- `configuration-service.get-value`: request `{key, resource?, override_identifier?}` where `key` is the
  setting key (`files.autoSave`), response `{value}`. The default layer is `config[<kebab id>]` (computed from the key),
  so fixture `config` overrides work. User and workspace layers come from `settings-store` (store tables `user` and
  `workspace` keyed by setting key), and `state.policy` overrides everything.
- `file-service.write-file`: request `{resource, content, mtime?, etag?, unlock?, atomic?}`, response
  `PlatformFileStat {resource, mtime, size, etag, readonly}`; errors `file-modified-since`, `file-permission-denied`,
  `no-file-system-provider-found`. `file-service.read-file` `{resource, etag?, limits_size?}` -> `{resource, value,
  mtime, size, etag}`; `file-service.del` `{resource, use_trash?, recursive?}`.
- etag encoding in the model: `"<mtime>-<size>"` (the code uses `mtime.toString(29) + size.toString(31)`).

## 3. Boundary stubs
- `extension-service` component and `extension-service.activate-by-event` (exthost): there was no skeleton stub
  and no exthost fragment yet, so this uses shared shapes: request `{activation_event}`, error
  `extension-host-crashed` (retryable) from the profile table. Align in reconciliation.
- `disk.stat`, `disk.read-file`, `disk.write-file`, `disk.delete` (shared): declared with `store` ops on
  `disk.files` (rows `{content, mtime, size, readonly?}`; write sets `mtime = now`, `size = size(content)`; a miss
  is `file-not-found`). Other areas' copies merge by union, and these stores survive.
- `settings-store.user-read/workspace-read/user-write/user-delete` (shared): store ops on tables `user` and
  `workspace` keyed by setting key; a miss is `setting-not-found`.
- `storage-db.global-insert/global-delete/workspace-insert/workspace-delete` (shared): store ops on `global` and
  `workspace` keyed by storage key.

## 4. Config
platform-core defines no config entities. None of the modelled behavior reads a setting registered under
src/vs/platform. `get-value` reads any config by id (`config[...]`), and the default/deployed distinction belongs
to each setting's owner. Constants that are not settings are cited literals: the 30 s `*` activation race
(commandService.ts:43), the 100 ms storage flush delay (base storage.ts:117) and the 60 s idle flush interval
(not modelled).

## 5. Fixture requests
None required. Scenarios add their own state on top of `one-window-folder` (policy values, readonly disk rows,
settings-store rows, storage items).

## 6. Assumptions and what the code did not settle
- ICommandService and the IConfigurationService seam: the brief gives them to platform-core, but CommandService
  lives under src/vs/workbench/services/commands, and the workbench's IConfigurationService is WorkspaceService
  (workbench-shell). I model the platform `Configuration` resolution order (configurationModels.ts:1033-1070)
  without folder or memory layers.
- `update-value` follows the platform ConfigurationService, which only writes USER/USER_LOCAL. WorkspaceService
  (workbench-shell) can also write workspace targets.
- `activationEventIsDone` short-circuit (commandService.ts:62-64) is folded into the awaited activation. For an
  already-done event, the call returns at once, so the outcome is the same.
- Storage scopes: `profile` and `application` flush to `storage-db.global` (the default profile shares the
  application database), and `workspace` flushes to `storage-db.workspace`.
- Instantiation dependencies are parsed from the real constructors' `@I...` parameters. Services that
  desktop.main creates before the instantiation service (configuration, file, storage, log, policy, ...) are seeded
  `created: true`. Delayed instantiation (proxies) is not modelled.
- Undo/redo: `element.actual.undo()` is the owner's callback (the editor's text model); the model records only the
  stack movement. Groups, workspace elements, confirmation prompts, locks and invalid elements are not modelled.

## 7. Docs or common knowledge vs code
- "Writing a setting equal to its default keeps it": the code removes it from settings.json
  (configurationService.ts:127-130). Scenario `platform-core-update-configuration-value-default-removes`.
- "An mtime mismatch means a save conflict": the code also needs the etag (size at the caller's mtime) to differ,
  and it still allows the write when the bytes are identical (fileService.ts:519-537).
- "executeCommand of an unknown command fails at once": it first waits for onCommand and `*` activation (up to 30 s).

## 8. Simulator gaps
- `Promise.all` rejection: a failing `parallel` branch fails with the fixed `on_insufficient` error, not the
  branch's own error. execute-command uses `extension-host-crashed` (commandService.ts:80-87).
- The race "`*` activation vs. `CommandsRegistry.onDidRegisterCommand`" (commandService.ts:82-86) cannot wait on
  an event. In the model, registration during activation shows up only if the activation stub registers the
  command. So `execute-command` behavior[5] (the return after a late registration) never runs: 219/220 steps.
- Per-resource write queues (`ResourceQueue` in FileService) cannot be expressed. Capacity is per component, so
  writes are not serialized per URI.
- ThrottledDelayer coalescing: multi-step scenario steps never overlap, so two stores inside one 100 ms window
  cannot be shown in one batch. Each store schedules a flush, and later flushes return early when nothing is
  pending (scenario `platform-core-storage-flush-nothing-pending`).
- Events without a subscriber in this fragment are not published (that would raise a validation warning):
  `onWillExecuteCommand` / `onDidExecuteCommand`, `onDidRunOperation`, and quick input `onDidAccept`. They appear as
  narrated steps. Published: `configuration-service.on-did-change-configuration`,
  `context-key-service.on-did-change-context`, `storage-service.on-did-change-value` (sync), and
  `marker-service.on-marker-changed` (async, MicrotaskEmitter). Other areas may subscribe to these.
- The JSON stringify of storage objects and `config.*` arrays is approximated with `string()`.

## 9. Known gaps
- No `redo` flow (canRedo is modelled). No FileService `move`, `copy`, `createFolder`, `resolve` or `watch` (the
  watcher is modelled only as process startup). No notification, dialog or keybinding services (owned by
  workbench-shell).
- The settings.json parse-error branch is a `choice` (`configuration-editing.write.settings_file`), because
  settings content is not modelled as text.
- (Fixed in the fix round) language overrides and folder scoping in `get-value`; see below. Still not modelled: the memory
  and application layers, deep merge of object-valued settings across layers, and JSON parsing of string policy values.

## Reconciliation round

- **Generator** is now in `examples/vscode/gen/platform-core/` (`gen.py`, `deep.yaml`, `flows.yaml`, `svcs.*`). Run
  `python3 gen.py` there.
- **Decision 2:** `file-service.*` and `disk.*` take `resource`. The four `disk.*` interfaces are now
  platform-core's **non-stub** definitions (`attributes.owner: platform-core`), with `store` ops keyed by
  `input.resource` on `disk.files`. `write-file` sets `mtime = now` and `size = size(content)`. Callers send
  `{resource, content}`.
- **Decision 3:** execute-command sends exthost's `ExthostActivateByEventRequest` (`activation_event`,
  `activation_kind: normal`; executeCommand never passes a kind) for `onCommand:<id>` and `*`. My stub of
  `extension-service` / `activate-by-event` now holds only id, kind and owner, so it can't diverge from
  exthost's definition. The `Promise.all` rejection code is now `canceled`, exthost's only declared error.
- **Decision 6, the command registry contract:** each area seeds `commands-registry` in its `<area>-seed` fixture as
  `commands-registry: {commands: {"<command id>": {handler: "<component>.cmd-<slug>"}}}`. The newest registration
  wins, as in the code. `command-service.try-execute-command` calls `vars.lookup.value.handler` with
  `{command_id, args}`. Its `targets` list is **generated** from every area's `commands-registry` seed plus
  `editor-command.run-command` (editor's request), keeping only handlers that exist as interfaces
  (360 at this run). An unseeded id fails with `command-not-found`. Runtime registration goes through
  `commands-registry.register-command`.
- **Interfaces other areas called that I didn't define yet** (decision 9), now modelled with behaviors and
  scenarios:
  - `file-service.exists`, `can-create-file`, `create-file` (FILE_MODIFIED_SINCE when the file exists
    without overwrite, fileService.ts:363-366), `can-delete`, `can-move`, `move` (`file-move-conflict`,
    fileService.ts:950-956), `watch` (stub);
  - `undo-redo-service.redo`;
  - `marker-service.get-statistics`;
  - `logger-service.set-log-level` (an empty `resource` means the global level).
  - files-search-scm's `FilesFileStat` responses for move and create-file should become `PlatformFileStat`.
- Dropped `accessibility-signal-service`: workbench-contribs models it from its registerSingleton.
- Skips: added 16 service entries whose registered implementation another area owns, each naming the area.
- **Fixture request:** `base-workspace` gives `src/util.ts` `size: 61`, but its content is 60 characters. Writes
  recompute the size from the content, so after a move or rewrite the size is 60. Please correct the fixture to 60.

## Final round
- Added `opener-service.open` (openerService.ts:190-225, under src/vs/editor but assigned to platform-core) with request `{resource, open_external, allow_commands, open_to_side}` and response `{opened, via}`. Command links run through `command-service.execute-command`, and files open through workbench-shell's `editor-service.open-editor`. The `IOpenerService` skip is removed.
- Added `secret-storage-service.get/set/delete` (BaseSecretStorageService, secrets.ts:101-191). It keeps `secret://<key>` in APPLICATION storage; encryption is not modelled.

## Fix round (judge C6, oracle core, features, test reach)

Generator: `gen/platform-core/` (`deep.yaml`, `flows.yaml`, `gen.py`); run `python3 gen.py` there.

- **Settings scopes and language overrides (C6).** `configuration-service.get-value` now follows
  `Configuration.getConsolidatedConfigurationModel` as `WorkspaceService.getValue` runs it
  (`workbench/services/configuration/browser/configurationService.ts:335-339`,
  `configurationModels.ts:1033-1085`): policy on top; with `override_identifier`, a `[lang]` section at any layer
  (folder > workspace > user > registered default override) beats every general value, and `[lang]`-only sections
  beat multi-language ones such as `[javascript][typescript]` (`configurationModels.ts:231-252`); then the folder of
  the resource's root (`workspace.ts:393-399`, longest folder prefix, via workbench-shell's
  `workspace-context.get-workspace`), workspace, user, default. Default language overrides come from
  `modesRegistry.ts:64-86` (`[shellscript]` gives `files.eol` = LF, which the editor's create-model call reads).
  New shared io: `settings-store.folder-read` (table `folder`, keyed by folder URI, row = that folder's settings
  object), `settings-store.workspace-override-query` and `user-override-query` (multi-language sections).
  Request shape unchanged; `resource` and `override_identifier` now default to `""` (= absent) instead of
  carrying examples, because entry fake data filled them in.
- **Policy layer (AccountPolicyService seam).** `configuration-service.on-did-change-policies` models
  `PolicyConfiguration.onDidChangePolicies` + `update` (`configurations.ts:232-302`): it subscribes to
  workbench-shell's `account-policy-service.on-did-change` (`{names}`), maps names to setting keys through the
  registry's policy table (`state.policy_settings`, from the real `policy: {name}` declarations), reads
  `account-policy-service.get-policy-value`, sets or removes `state.policy[key]`, and publishes
  `on-did-change-configuration` with `source: policy`. **Waits on workbench-shell:** its
  `update-policy-definitions` only sets `last_changed`; it must `publish: account-policy-service.on-did-change`
  with `{names: <updated>}` (accountPolicyService.ts:190-192) so the chain runs end to end. My scenarios drive the
  subscriber directly with seeded `account-policy-service` state until then.
- **Context for `when` clauses (C2 support).** New `context-key-service.get-context` (`{keys?}` -> `{values}`,
  contextKeyService.ts:361-366): root values plus `config.*` keys, resolved lazily through
  `get-context-key-value` for the keys the caller lists. Workbench-shell's keybinding resolver and palette can call it
  and `eval(when, values)`. Keys that are not set are absent from `values` (undefined in VS Code).
- **Feature `settings`:** flows `pc-get-configuration-value`, `pc-update-configuration-value`,
  `pc-on-did-change-policies` are tagged `feature:settings`.

### Breaking changes

None. `configuration-service.get-value` keeps its request and response; callers that pass `resource` or
`override_identifier` (editor `model-service.create-model` for `files.eol`) now get the folder and language
layers, which is the code's behavior.

### Still open

- **C1, `activationEventIsDone` short-circuit** (commandService.ts:61-63): needs exthost to expose
  `extension-service.activation-event-is-done` (abstractExtensionService.ts:1059-1068). Not added as a stub of an
  interface the owner doesn't define.
- **C1, `*` activation raced against `onDidRegisterCommand`** (commandService.ts:80-86): the outcome (a command
  registered during `*` activation runs) needs exthost's `main-thread-commands.register-command` to call
  `commands-registry.register-command`; today it only records the id in its own state. The early-resolution timing
  is not modelled.
- Oracle `account-policy-default-account` expects a call into `account-policy-service.*` during `get-value`; the code
  reads the PolicyConfiguration model there, and the service is only consulted on `onDidChange`, so that path
  expectation needs re-scoring.
- `when`-clause syntax (`=~`, `in`, unquoted RHS) is the resolver's job (workbench-shell, contract 5).

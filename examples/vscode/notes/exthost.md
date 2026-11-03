# exthost area notes (VS Code 1.144.0, 2c33b50b16)

Fragment: `fragments/exthost.yaml` (generated from hand-written core YAML plus mechanical lists;
165 components, 242 interfaces, 13 flows, 82 scenarios). Skips: `skips/exthost.json` (1,020 entries).

## 1. Entry points (1,316 owned)

| Kind | Owned | Covered | Skipped | How |
|---|---|---|---|---|
| exthost-rpc | 1034 | 21 | 1013 | modeled methods cite their extHost.protocol.ts line; rest skipped by the profile's exthost-rpc rule |
| extension-api | 121 | 121 | 0 | one `vscode-api.<ns>-<fn>` interface each, citing vscode.d.ts and the extHost.api.impl.ts lines; reachable from flow `exthost-api-call` (dynamic call with `targets`) |
| exthost-customer | 87 | 87 | 0 | one component per MainThread customer citing its `@extHostNamedCustomer` line; reachable via narrative flow `exthost-rpc-customers` |
| service | 47 | 45 | 2 | component per registerSingleton impl citing the createDecorator line (flow `exthost-runtime-services`) |
| vscode-command | 15 | 10 | 5 | `cmd-*` interfaces |
| extension-point | 7 | 7 | 0 | handler components (start flow steps) |
| workbench-contribution | 3 | 3 | 0 | ExtensionPoints, ViewsExtensionHandler, ExtensionUrlBootstrapHandler components |
| process-main | 2 | 2 | 0 | `extension-host.start-extension-host-process` (extensionHostProcess.ts) and `extension-host-worker.main` |

Modeled RPC methods (21): ExtHostExtensionService `$startExtensionHost $activateByEvent $activate $deltaExtensions $test_latency $test_up $test_down`; MainThreadExtensionService `$onWillActivateExtension $onDidActivateExtension $onExtensionActivationError $setPerformanceMarks`; MainThreadCommands `$registerCommand $fireCommandActivationEvent $executeCommand $getCommands`; `$showMessage`, `$trySaveDocument`, `$tryApplyWorkspaceEdit`, MainThreadWorkspace `$save`, MainThreadUrls `$registerUriHandler`, ExtHostUrls `$handleExternalUri`.

Skips (grouped; each entry in the JSON names its target):
- 529 MainThread*Shape methods: "RPC plumbing: <main-thread-x>.<method> forwards to <service>[.<method>]". The target was derived mechanically from the first injected service the method body calls (`this._xService.m(...)`), falling back to the class's main injected service. A few (e.g. MainThreadTerminalService, MainThreadQuickOpen, MainThreadComments, MainThreadSCM) do keep per-handle maps; the rule treats them as plumbing, the judges may disagree.
- 484 ExtHost*Shape methods (main thread -> extension host): forward to the extension-registered provider/callback held by the named ExtHost* component, reached through the vscode-api register function.
- Services: IExtensionHostStarter (impl in platform/extensions/electron-main, main-process), IBuiltinExtensionsScannerService (impl in services/extensionManagement, workbench-shell).
- Commands (rule): `_generateCommandsDocumentation`, `_workbench.revertAllDirty`, `_extensionTests.setLogLevel/getLogLevel`, `_telemetry.setCapiAssignmentContext`.

Flows: exthost-start, exthost-activate-by-event (seam), exthost-get-extension, exthost-crash, exthost-restart, exthost-unresponsive, exthost-delta-extensions, exthost-api-call, exthost-url-handle, exthost-manage-authorized-uris, exthost-measure-latency, plus narrative flows exthost-rpc-customers and exthost-runtime-services.

## 2. Components (key ones; all cite code)
- `extension-service` (NativeExtensionService/AbstractExtensionService, abstractExtensionService.ts:61, nativeExtensionService.ts:63,773): activateByEvent, _initialize, stop/start with veto, crash handling, delta extensions.
- `extension-registry` (skeleton anchor): I define its interfaces (contains-activation-event, snapshot, get-extension-description, delta-extensions, mark-activation-started, clear-activated). `activated` = ExtensionStatus.activationStarted.
- `extension-host-manager` (extensionHostManager.ts:58), `extension-host-crash-tracker` (:1549), `native-local-process-extension-host` (localProcessExtensionHost.ts:95), `rpc-protocol` / `ext-host-rpc-protocol` (rpcProtocol.ts), `web-worker-extension-host`, `extension-host-worker`.
- Host side: `ext-host-extension-service` (extHostExtensionService.ts), `extensions-activator` (extHostExtensionActivator.ts), `ext-host-commands`, `ext-host-message-service`, `ext-host-bulk-edits`, `ext-host-document-data`, `ext-host-workspace`, `ext-host-urls`, `vscode-api`.
- URIs: `extension-url-handler`, `user-trusted-extension-id-storage`, `manage-authorized-extension-uris-action`.
- Commands: `restart-extension-host-action`, `measure-ext-host-latency-action`, `main-thread-cli-commands` (_remoteCLI.*), `main-thread-notebooks` (_executeDataToNotebook/_executeNotebookToData), `main-thread-file-system-event-service` (files.participants.resetChoice).
- 87 customers + ~40 ExtHost services as thin components (generated).

## 3. Boundary stubs (no owner fragments existed; shared shapes used)
command-service.execute-command (seam, platform-core); text-file-service.save (seam, files-search-scm; options = skeleton FilesSaveOptions); editor-service.save / open-editor (workbench-shell); notification-service.notify/prompt/status, dialog-service.confirm/prompt, quick-input-service.pick, native-host-service.close-window (workbench-shell; owners by registerSingleton location); bulk-edit-service.apply (workbench-contribs); extension-host-starter.create-extension-host/start (main-process, ipc). Stub components are declared with `boundary: true` under their owners' skeleton modules. `dialog-service.confirm` response defaults `confirmed: true`; `editor-service.save` defaults `success: true`; `bulk-edit-service.apply` defaults `is_applied: true`.

Seam I own: `extension-service.activate-by-event` (request ExthostActivateByEventRequest {activation_event, activation_kind normal|immediate}; response ExthostActivationResult {activated, deferred, cached}; error canceled only). It never rejects for a failing extension.

## 4. Config
Owned (product.json has no overrides, so deployed = default everywhere):
- extensions-web-worker = 'auto' (extensions.contribution.ts:223-233; read nativeExtensionService.ts:667-681).
- extensions-experimental-deferred-startup-finished-activation = false (extensions.contribution.ts:312; read extHostExtensionService.ts:652).
- extensions-confirmed-uri-handler-extension-ids = [] (extensions.contribution.ts:214; read extensionUrlHandler.ts:336).
- Code constants as configs (no setting key, `attributes.constant`): exthost-handshake-timeout-ms 60000, exthost-crash-limit 3, exthost-crash-window-ms 300000, rpc-unresponsive-time-ms 3000, rpc-unresponsive-check-interval-ms 1000, exthost-eager-activation-timeout-ms 10000, exthost-auto-restart-status-hide-ms 5000.
These settings are registered in contrib/extensions (remote-server's path) but read by my code, so I own them per rule 4. No shared fixture config is read.

## 5. Fixture requests
- The extension host's own registry (`ext-host-extension-service@ehN`) is not seeded; I pass the mirror with each RPC instead (see 6). A seed would let the host side read its own registry.
- No fixture with an extension under development or a remote extension host; I drive those via component state (`is_extension_dev_host`).

## 6. Assumptions / not settled by code
- Host-side registry: the renderer's ExtensionHostManager keeps `extensions` identical to the host's (set by $startExtensionHost/$deltaExtensions). The model passes the matching descriptions (`extensions`, `registry`) in the RPC request instead of a second copy of state (ExthostMirrorActivationRequest). Shape attributes still name the real method.
- Only the local process host is modeled for activation; remote hosts and LazyCreateExtensionHostManager are narrated, not simulated.
- `main-thread-commands.get-commands` returns only commands the extension host registered (CommandsRegistry belongs to platform-core). Whether a command is in CommandsRegistry for the retry path is the choice `main-thread-commands.execute-command.registered`.
- User answers to prompts/dialogs are choices on my interfaces (the stubs' return values are not mine).
- Built product assumed (isBuilt): activation errors without a missing dependency are console-only.
- Missing dependency handling: modeled the "unknown dependency, not installed" notification; the installed-but-disabled/enable-and-reload variants (mainThreadExtensionService.ts:111-157) are not.
- Component naming collisions: two classes named `SaveParticipant` became `main-thread-save-participant` and `main-thread-notebook-save-participant`. Services with node and worker impls use the common class name (e.g. ext-host-authentication, not node-ext-host-authentication). `_startExtensionHost` is `start-extension-host-internal` because `$startExtensionHost` takes `start-extension-host`.
- Command id slugs drop the leading `_` (cmd-remotecli-openexternal).

## 7. Docs / common knowledge vs code
- "Crashes restart forever" is wrong: the local host auto-restarts only while fewer than 3 crashes were recorded in 5 minutes; then a prompt (Bisect / Restart / Learn More). Exit code 55 (version mismatch) never auto-restarts.
- "Restart Extension Host" after a veto plus "Restart Anyway" returns stopped=true without stopping; startExtensionHosts does the stop.
- Unresponsive is not about slow handlers: it is a missing *acknowledgement* (sent on receipt) for >3 s, checked every 1 s.

## 8. Simulator gaps
- Promise caching: ExtensionHostManager caches the activation *promise*; concurrent callers share it. The model returns `cached: true` immediately for a second caller (extensionHostManager.ts:329-332).
- Barrier waits (`_installedExtensionsReady.wait()`, `_readyToRunExtensions.wait()`) cannot block; a Normal activation before ready returns `deferred` and the start flow replays `requested_events` after the barrier (abstractExtensionService.ts:1023).
- Unresponsive detection: modeled with a call `timeout_ms` = 3000 + 1000 on `ext-host-rpc-protocol.receive-request` and a late async ack; the 1 s RunOnceScheduler polling is approximated (rpcProtocol.ts:206-219).
- publish/subscribe subscribers are not followed by coverage reachability; 7 validation warnings are publishes whose subscribers live in other areas (onWillActivateByEvent, onDidChangeExtensionsStatus, onWillStop, ...).
- `list.transformMap` cannot build a map keyed by a field, so registry inserts use `foreach` + `merge`.
- Dependency activation waits sequentially (foreach) where the code races dependency barriers (extHostExtensionActivator.ts:374-411).

## 9. Known gaps
- Unexecuted branches (7): `ext-host-extension-service.activate` unknown-extension (renderer only calls it for registered extensions); `ext-host-urls.handle-external-uri` unknown handle; `extension-host-manager.start` without proxy (initialize only calls it after a successful start); `stop-extension-hosts` auto paths (no automatic caller modeled in my area); `extension-url-handler.handle-url` handler-registered-during-confirmation; `main-thread-workspace.save` failure (editor-service stub always succeeds).
- Remote authority resolution, extension tests runner, workspaceContains activation, extension host profiling/inspect ports, terminate/deactivate are narrated or stubs only.
- 110 vscode-api functions are forwarding stubs (no behavior) with ExthostApiArgs/ExthostApiResult shapes.
- Scenario count (82) and component count (165) exceed the rough targets because every customer, service and API function needs an entity.

## Reconciliation round

Generator now lives in `gen/exthost/` (`gen.py` + `chunk_api.py`, `chunk_stateful.py`, `chunk_scen.py`, core YAML; `dts.py` parses vscode.d.ts, `lf.py` maps languages APIs to RPCs). It writes to `EXTHOST_OUT` first so the fragment is published only after a clean standalone check.

- **Decision 3 (activate-by-event):** contract unchanged (ExthostActivateByEventRequest / ExthostActivationResult). `activation_kind` is treated as optional with default `normal`, because the code declares `activationKind = ActivationKind.Normal` (abstractExtensionService.ts:993). The host-side `$activateByEvent` now takes only `{activation_event, activation_kind}` and reads the host's own registry.
- **Seed fixture `exthost-seed`:** `ext-host-extension-service.registry` mirrors the extensions one-window-folder registers (git, typescript, markdown, js-debug). The component's `initial` also has `registry: {}`, so worlds without the seed don't abort. `$startExtensionHost`, the init data and `$deltaExtensions` update it.
- **Decision 4 (vscode-api):** every `vscode-api.*` request is generated from vscode.d.ts: parameter names in snake_case, union across overloads, required = required in every overload, plus the implicit `extension_id` (the calling extension). DocumentSelector is modeled as a language id string. All 121 functions have behavior:
  - languages register*/setLanguageConfiguration allocate a handle in `ext-host-language-features`, call `main-thread-language-features.$register*` (modeled, cites protocol + impl), which calls editor's `language-features-service.register-provider`;
  - wired end to end: scm.createSourceControl -> scm-service, window.createTerminal -> terminal-service, debug start/stop/add/removeBreakpoints -> debug-service, tasks.executeTask -> task-service, workspace.saveAll -> editor-service.save-all, showOpenDialog -> file-dialog-service, createOutputChannel -> output-service (id `extension-output-<ext>-#1-<name>`, log false, as $register), openTextDocument -> text-file-service.read (approximates ITextModelService.createModelReference);
  - the rest forward to the named ExtHost* service method (stub on my own component).
  Missing owner fields are filled from the owner's request defaults.
- **DAP relay (decision 9):** `ext-host-debug-service.start-da-session / send-da-message / stop-da-session` (extHostDebugService.ts:607-736) keep adapters by handle and forward to `debug-adapter.handle-request`; unknown handles are dropped like `da?.sendMessage`.
- **Decision 8:** my topics stay `extension-service.on-will-activate-by-event`, `on-did-change-extensions-status`, `on-will-stop`; I subscribe `extension-service.on-will-shutdown` to workbench-shell's `lifecycle-service.on-will-shutdown` (stop hosts, abstractExtensionService.ts:211-235).
- **Decision 12:** the 55 RPC methods of MainThreadSCM, MainThreadTerminalService, MainThreadQuickOpen and MainThreadComments are no longer skipped. Each is modeled on its customer: register/create keep a per-handle object, unregister/dispose drop it, other methods look the handle up and are ignored when unknown, start/stop toggles are flags, and payload-only updates count updates. Approximation: the payload contents are not modeled.
- **Customers:** each of the 87 customers has a `create` interface, called by `extension-host-manager.create-customers` (extensionHostManager.ts:249-318) at every host start.
- Boundary stubs are copied from the owners' fragments (request/response/errors/kind; component kind and parent). Response defaults added only for standalone determinism (editor-service.save/save-all, dialog-service.confirm, bulk-edit-service.apply).
- Scenarios that depend on another area's answer set my own choices explicitly (crash prompt, veto confirm, modal answer, URL decision).

Remaining merged failures, not mine:
- `exthost-api-smoke-tasks`, `exthost-api-smoke-window-2`: `terminal-service.create-terminal` fails `no-terminal-backend` until the shared worlds extend `terminal-debug-tasks-seed` (coordinator, decision 10).
- `exthost-api-call-apply-edit`: `text-model.push-edit-operations` fails `model-is-disposed`; BulkEditService resolves model references itself in the code (workbench-contribs / editor).
- Merge warnings naming exthost: agents stubs `editor-service`, `lifecycle-service` and `extension-service` with kind `module` (owners say `service`; decision 7, agents).

## Fix round (after judging)

Edits live in `gen/exthost/fix_round/` (`patch.py` + `parts.py` + YAML snippets, `fixskips.py`), run at the end of `gen.py`; `gen.py` reproduces the fragment and skips byte for byte.

- **E3** `ext-host-save-participant.participate` (new owner definition, mainThreadSaveParticipant.ts:25-49) calls `ext-host-document-save-participant.participate-in-save` on ehN with `timeout_ms: 1750` and rejects `timeout`/`listener-failed`; the host side delivers to listeners in order, stops after 1500 ms and skips listeners with >3 errors (extHostDocumentSaveParticipant.ts:51-104).
- **X8** `extension-service.initialize` asks `workspace-trust-management-service.is-workspace-trusted`; untrusted -> extensions with `main` whose `capabilities.untrusted_workspaces.supported` is not true/'limited' (default false) are removed from the registry before the host starts (abstractExtensionService.ts:525-533, extensionManifestPropertiesService.ts:314-345). `exthost-seed` adds the real manifest capabilities (git, TS false; markdown limited) to `extension-registry@w1`.
- **X5** `extensions-auto-profiler.on-did-change-responsive-change` (subscribes to `extension-service.on-did-change-responsive-change`) and `stop-and-analyse` (5 s timer or responsive event; blame >=95% and >=5 s, once per extension, at most 3, SILENT prompt, no restart) (extensionsAutoProfiler.ts:63-245). The component is remote-server's; the interfaces are mine (assigned X5).
- **API commands**: `ext-host-commands` holds `api_commands`; `run-api-command` validates arguments in the host (`invalid-argument` before any RPC) and runs the internal id; `setContext` -> `_setContext`. `main-thread-commands.execute-command` computes "unknown" with `commands-registry.get-command` (the old `registered` choice is gone). `$registerCommand` registers `main-thread-commands.execute-contributed-command` in CommandsRegistry, which calls `ext-host-commands.execute-contributed-command`.
- **Editor tabs**: `main-thread-editor-tabs.create` builds the model (`create-tabs-model`), `on-did-editors-change` patches/ignores/rebuilds (modal-part label early return), `ext-host-editor-tabs.accept-editor-tab-model` / `accept-tab-operation`.
- **Debug visualizers**: register (contributed + once), dispose, `$provideDebugVisualizers` returns [] for a disposed provider; main-thread register/unregister/provide.
- **DAP**: `start-da-session` resolves the descriptor (factory or contributed executable; empty type fails) and calls `debug-adapter.start-session`; `stop-da-session` calls `debug-adapter.stop-session` for known handles; descriptor factories are once per type.
- **Search**: `ext-host-search.provide-text-search-results` (owner definition) streams `text-search-manager.search` items (yield = $handleTextMatch) and returns `{limit_hit, stats}`; `folder_encodings` become the folder queries' `file_encoding`.
- **Chat**: `ext-host-chat-agents2.invoke-agent` streams the participant's parts and returns metadata or errorDetails; the participant calls `ext-host-language-models.send-chat-request` -> `main-thread-language-models.try-start-chat-request` -> `language-models-service.send-chat-request`.
- **R1**: a window with a remote authority starts `remote-extension-host.start` (resolve authority, ExtensionHost connection to `remote-extension-host-agent-server.handle-web-socket-connection`) with the extensions that have code; the local host keeps the rest (extensionHostKind.ts:47-88, nativeExtensionService.ts:585-589).
- **R3**: `extension-service.on-did-install-extensions` subscribes to `node-extension-management-service.on-did-install-extensions` and calls `handle-delta-extensions` (abstractExtensionService.ts:182-199). The code listens to the workbench management service, which relays this event.
- Smaller: `languages-match` scores `*` 5 / language 10; `set-language-configuration` calls `language-configuration-service.register`; `user-trusted-extension-id-storage.set` stores to profile storage; `$registerNavigateTypeSupport` registers with `workspace-symbol-provider-registry.register`; `main-thread-commands.create` registers `_generateCommandsDocumentation`.
- Features: flows tagged `feature:extension-host-lifecycle` (start, activate, crash, unresponsive) and `feature:extension-api` (api-call).
- Skips: every "covered by" skip now names `covered_by`; RPCs modeled this round were removed from the skips.

### Breaking changes

1. `ext-host-search.provide-text-search-results` result: `{results, limit_hit}` -> yields `{resource, matches}` per file and returns `{limit_hit, stats}` (extHostSearch.ts:170-179). Callers: files-search-scm `search-service` text search (already reads the stream); oracle `oracle-files-search-scm-text-search-fixes-encoding` must now look for `text-search-manager.search` and its folder options (the canonical encoding is computed there).
2. `main-thread-commands.execute-command`: choice `registered` removed (mainThreadCommands.ts:87). Callers: my scenario `exthost-api-call-execute-retry` (fixed). No others.
3. `main-thread-commands.register-command` now writes `commands-registry` with handler `main-thread-commands.execute-contributed-command`. platform-core must add that interface to `command-service.try-execute-command` `targets`, or executing an extension command through the command service fails.
4. `main-thread-language-features.register-navigate-type-support` calls `workspace-symbol-provider-registry.register` instead of `language-features-service.register-provider` (mainThreadLanguageFeatures.ts:488-509).
5. `ext-host-chat-agents2.invoke-agent` is now owned and yields progress items (non-streaming callers get `{items, value}`). Chat calls it with `stream: true` already.

### Still open
- E3a (`bench-e3-exthost-participant-hangs`) faults `ext-host-save-participant.participate` itself, so the bound must come from the caller: files-search-scm `text-file-save-participant.participate` has no `timeout_ms`. The 1750 ms budget now lives inside my participant (scenario `exthost-save-participant-budget`). E3b (Skip) is files-search-scm's.
- X8a: the world `full-untrusted` registers TS as enabled and the scenario never runs `initialize`; X8b needs workbench-shell's banner (`banner-part`).
- R1 judge expects `extension-host-manager.*` inside remote-server's server-side flow; the renderer hop is `remote-extension-host.start` (scenario `exthost-remote-window-starts-remote-host`); the judge scenario needs re-adapting.
- A1 `onChatParticipant` activation belongs to chat.
- `run-ripgrep` was dropped in favour of files-search-scm's `text-search-manager`.
- Follow-up: `authentication.getSession` -> `$ensureProvider` (activates onAuthenticationRequest:<id>) -> `main-thread-authentication.get-session` -> `ext-host-authentication.get-sessions` -> the registered provider (`github-session-engine.get-sessions` for GitHubSessionEngine). getSession on an unregistered provider now fails `no-provider` (smoke scenario updated). `vscode.open` is an API command (-> `_workbench.open`, extHostApiCommands.ts:430-441); workbench-shell registers only `vscode.open`, so `_workbench.open` must be registered (editorCommands.ts:456) for the internal hop to resolve.

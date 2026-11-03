# main-process area notes (VS Code 1.144.0, 2c33b50b16)

Fragment: `examples/vscode/fragments/main-process.yaml`. Skips: `examples/vscode/skips/main-process.json` (empty: every owned entry is modeled).
Modeled platform: Linux/Windows (non-macOS). macOS-only branches are narrated or noted, not executed.

## 1. Entry points (117 owned, 117 covered by line, 0 skipped)

| Kind | Count | Covered by |
|---|---|---|
| process-main `src/main` (src/main.ts:8), `src/vs/code/electron-main/main` (main.ts:739) | 2 | flow `main-startup`, entry `code-main.startup` |
| process-main `src/cli` (src/cli.ts:14), `src/vs/code/node/cli` (cli.ts:592) | 2 | flow `cli-launch`, entry `node-cli.main` |
| process-main `cliProcessMain` (cliProcessMain.ts:357) | 1 | `cli-main.main` (reached from `cli-launch`) |
| process-main `sharedProcessMain` (:644), `src/bootstrap-fork` (:11) | 2 | flow `shared-process-startup` -> `bootstrap-fork.run` -> `shared-process-main.main` |
| process-main `desktop.main` (:431) | 1 | flow `renderer-startup`, entry `desktop-main.main` |
| ipc-channel, app.ts:1386-1532 (33) | 33 | `code-application.init-channels` cites each registerChannel line; deep servers: launch (`launch-main-service`), nativeHost, update (`update-channel`), workspaces, storage, extensionHostStarter |
| ipc-channel, sharedProcessMain.ts:361-539 (25) | 25 | `shared-process-main.init-channels` cites each line |
| service (25 createDecorator lines) | 25 | one component per registered implementation class, citing the decorator line; deep: windows, lifecycle, backup, native host, launch, update, dialog, workspaces history/management, menubar, storage; the rest are reached through the `main-startup` narrative steps (app.ts initServices lines). `IUpdateService` (update.ts:108): the inventory lists BrowserUpdateService (workbench-shell); in desktop the main-process implementation is the platform class -> `linux-update-service`. |
| vscode-command (desktop.contribution.ts, 25) | 25 | `cmd-*` interfaces on `desktop-window-actions`, `desktop-developer-actions`, `desktop-install-actions`, `desktop-contribution`, `native-window` (revealPathInFinder${i}, window.ts:683). `externalCommand` (line 103) = macOS native tab commands -> `desktop-window-actions.cmd-workbench-action-newwindowtab`. The three "id unresolved" entries are workbench.action.zoomIn/zoomOut/toggleDevTools. |
| workbench-contribution DialogHandlerContribution | 1 | `desktop-dialog-handler-contribution.start`, flow `dialog-handler-startup` |

## 2. Components (code references in each entity's `sources`)

Main process (parent `main-process`): code-main (main.ts), code-application (app.ts), windows-main-service (+ windows-state-handler, code-window), lifecycle-main-service, backup-main-service, native-host-main-service, launch-main-service, linux-update-service (+ update-channel), metered-connection-main-service, workspaces-main-service, workspaces-history-main-service, workspaces-management-main-service, menubar-main-service (+ menubar), dialog-main-service (capacity 1: per-window dialog queue), shared-process-host (SharedProcess), storage-main-service (+ application-storage-main-service), extension-host-starter, and narrative-only services (auxiliary windows, browser view(s), diagnostics, external terminal, global keybindings, GPU process, keyboard layout, proxy auth, protocol, sandbox helper, theme, utility process worker). External: update-server.
Child processes modeled here: bootstrap-fork (parent main-process), shared-process-main (parent skeleton `shared-process`, owned by remote-server in the skeleton; its code is under src/vs/code/** so main-process models it), node-cli and cli-main (parent main-process; they are separate node processes).
Renderer (per window, parent `workbench-window`): desktop-main, and children native-window, desktop-window-actions, desktop-developer-actions, desktop-install-actions, desktop-contribution, desktop-dialog-handler-contribution.
Renames to avoid id clashes with workbench-shell (its browser windowActions.ts / dialog contribution use the same names): the electron-browser files are `desktop-*`.

## 3. Boundary stubs and contract source

| Stub | Owner | Contract copied from |
|---|---|---|
| lifecycle-service.on-before-shutdown, on-will-shutdown, veto | workbench-shell | workbench-shell fragment (request WorkbenchShutdownRequest inlined; I added only `default: false` on veto for standalone runs) |
| workbench.startup, editor-service.open-editor | workbench-shell | workbench-shell fragment |
| command-service.execute-command, configuration-service.update-value | platform-core | platform-core fragment |
| extension-management-cli.list/install/uninstall-extensions | remote-server | shared shapes (remote-server has no ExtensionManagementCLI component yet) |

Callers of my interfaces found in other fragments: workbench-shell (native-host-main-service.get-window-count, reload, open-window, close-window), agents (open-agents-window), exthost (extension-host-starter.create-extension-host/start). I added get-window-count, open-agents-window and extension-host-starter. Contract differences they must align to: workbench-shell's `open-window` sends `folder_uri` (mine: `folder_uris`/`file_uris` arrays); close-window target defaults to the calling window. terminal-debug-tasks/exthost/files-search-scm stub `native-host-service.get-window-count` (the renderer proxy, not owned by me): it should be `native-host-main-service.get-window-count`.

## 4. Config

Owned (value = default; product.json overrides none of them): files-hot-exit (onExit; files.contribution.ts:123-128,321; read in backupMainService.ts:97-101), update-mode (default), window-restore-windows (all), window-open-files-in-new-window (off), window-open-folders-in-new-window (default), window-open-without-arguments-in-new-window (on on Win/Linux; registered default is `off` on macOS: platform-dependent default), security-prompt-for-local-file-protocol-handling (true), window-zoom-level (0), window-zoom-per-window (true), window-dialog-style (native; agents window default custom), window-native-tabs (false).
product.json values: product-update-url and product-quality are ABSENT in the OSS product.json, so the deployed update service is disabled (MissingConfiguration) while a Microsoft build would check; product-tunnel-application-name = code-tunnel-oss.
Code constants as configs: update-initial-check-delay-ms 30000, update-check-interval-ms 3600000, second-instance-warning-timeout-ms 10000, kill-window-close-timeout-ms 1000, eventually-phase-delay-ms 2500.
Referenced (boundary): window-confirm-before-close (owner workbench-shell, never on desktop). window.openFilesInNewWindow / openFoldersInNewWindow are registered in workbench-shell's workbench.contribution.ts but only read by WindowsMainService, so I own them.

## 5. Fixture requests

- The fixtures do not seed main-process state. My components' `state.initial` mirror `one-window-folder` (w1 open on /work/app, ready). Request: add `windows-main-service`, `code-window` (and w2 entries) to `one-window-folder`/`two-windows`, so `two-windows` scenarios don't need my per-scenario overrides.
- A renderer (re)boot needs a fresh renderer world: scenarios that boot desktop.main set `lifecycle-service@w1: {phase: 1}`. Request: a fixture (or engine support) for "window w1 freshly loaded".

## 6. What the code didn't settle / assumptions

- The renderer's veto reaches main as a reply on one-time ok/cancel IPC channels. Modeled as choice `lifecycle-main-service.unload.renderer_reply` whose default follows the seam's `veto`; scenarios force `cancel` to model a vetoing participant (e.g. a cancelled save prompt).
- Window ids are instance names (w1, w2...); new windows are named `'w' + next_window`, so scenarios that open a window add w2 to the topology.
- `findWindowOnFile` is approximated by URI prefix; paths in CLI args are classified as files when they end in .ts/.md/.json.
- Closing windows in a quit is concurrent in Electron; modeled as `parallel` (join all), branches see state in list order.
- `isMacintosh` branches (dock context, window-all-closed keeps running, native tabs, shell command) are not executed; the shell command and native tab commands are still modeled behind their config/state.
- Unknown window ids are no-ops (`window?.win?.close()`), not failures: the code wins over the brief's "unknown keys fail".
- Profiles (forceProfile, newWindowProfile), agents windows, extension development hosts beyond the quit special case, and remote authorities are narrated only.

## 7. Docs / common knowledge vs code

- "Hot exit restores your windows": in the main process it only (a) restores empty windows that have backups on startup (windowsMainService.ts:407-418) and (b) keeps the edited marker across a reload when files.hotExit != off (windowImpl.ts:1274-1278). Folder backups are restored by the renderer (files-search-scm).
- Builds from this repo never check for updates: product.json has no updateUrl/quality (abstractUpdateService.ts:206-210), and running from sources is NotBuilt.
- Closing the last window on Windows/Linux quits the app; `window.openWithoutArgumentsInNewWindow` defaults differ per platform.

## 8. Simulator gaps

- Process restarts: when a window reloads, the renderer's per-instance state (e.g. workbench-shell's `lifecycle-service@w1.phase`) is not reset, so `desktop-main.main` -> `workbench.startup` fails with lifecycle-cannot-go-backwards in the merged model unless the scenario resets it (desktop.main.ts:118-146).
- Unbounded periodic timers: the hourly update check (abstractUpdateService.ts:455-459) is bounded to `count: 2`.
- Second instance vs first instance: both are the same components; the second process's `kill(0)` is not called (main.ts:535-557) so it does not mark the running instance as exited.
- Command registry dispatch: `native-window.run-action` calls my command handlers dynamically (window.ts:181-182) and other areas' commands through the `command-service.execute-command` seam; the registry lookup itself is platform-core's.
- The 10 s "not responding" dialog of a second instance (main.ts:435-442) needs a timer cancelled on success; not modeled.

## 9. Known gaps and unexecuted branches (16, all defensive)

claim-instance ECONNREFUSED after retry (needs a stale handle that survives unlink); code-window/windows-main-service unknown-id guards; fire-on-will-shutdown already running; set-phase backwards (never happens in main's own sequence); update reconfigure when permanently disabled / not Idle (initialize returns first); do-check result after disable mid-check (no concurrent disable); close-window unknown target; clearRecentlyOpened({confirm:true}) (only reached from the macOS dock/menu, not the workspaces channel).
Merged-model failures caused by other areas (reconciliation): `main-process-open-folder-reuse-vetoed` and `main-process-reload-hot-exit-off-clears-dirty` abort in `disk.write-file` (missing `uri`) via native-working-copy-backup-tracker -> text-file-service.write -> file-service.write-file. Scale is above the rough targets (23 flows, 107 scenarios) because commands and channel servers are many and each branch has a scenario.

## Reconciliation round

- Fixtures defined in my fragment (decision 10): `main-process-seed` holds windows-main-service and code-window state for w1, plus the desktop commands registered in platform-core's `commands-registry` (decision 6; 25 commands, handlers are my `cmd-*` interfaces). `main-process-two-windows` extends `two-windows` and `main-process-seed` and adds w2 (open, ready, /work/lib). All scenarios now list one of these, and their inline two-window state is gone. `native-window.run-action` keeps its internal dispatch to my handlers (decision 6 allows per-area routers).
- Boundary stub components added for the seeded and fixture-referenced owners: `commands-registry` (platform-core) and `workspace-trust-management-service` (workbench-shell; kind and parent copied from the owner).
- Hollow: added trace expectations to the 7 scenarios the lint flagged. The lint now shows 0 failing and 0 advisory for this fragment.
- Remaining:
  - `main-process-open-folder-reuse-vetoed` and `main-process-reload-hot-exit-off-clears-dirty` abort in `disk.write-file` (`uri` vs `resource`) on the backup-tracker save path. They wait on platform-core and files-search-scm (decision 2). main-process does not call file-service or disk.
  - Merge warning "native-host-main-service kind service vs module": agents' stub must say `service` (decision 7).
  - The workspace-trust stub disagreement is between agents' stub and mine; mine matches the owner.
- Shared fixture request: make `two-windows` include the `main-process-two-windows` state (w2 open in windows-main-service and code-window). Otherwise, once shared worlds extend `main-process-seed`, w2 exists in the renderer but not in the main process.

## Fix round

Fixes for the oracle findings (oracle/core.md, main-process rows):

1. **Agents window open intent.** `native-host-main-service.open-agents-window` (nativeHostMainService.ts:375-385) now calls the new `windows-main-service.open-agents-window` (windowsMainService.ts:296-334: resolveAgentsWindowFolder, ensureAgentsWindow writes `agent-sessions.code-workspace` through `file-service.exists`/`write-file` when missing, `open` with forceNewWindow and noRecentEntry) and force-focuses the first window. `windows-main-service.send-agents-window-open-intent` (agentsWindow.ts:15-28) skips a focus-only API open of an existing window, defaults source to `commandLine`/`unknown`, keeps the draft only for reveal `new` or a link, and sends `vscode:selectAgentsFolder` through the new `code-window.send-when-ready` (windowImpl.ts:1660-1670), which queues until `set-ready` flushes (windowImpl.ts:857-863). Scenarios `main-process-agents-window-*`; oracle `oracle-main-process-agents-window-new-window-reveal-omitted` passes.
2. **OnboardingTryoutHandoff** (onboardingTryoutHandoff.ts:25-118): component `onboarding-tryout-handoff` with `open`, `complete`, `cancel` (onboardingTryout channel) and `cancel-pending-request`. The DeferredPromise is a run-wide channel `onboarding-tryout:<requestId>`: `open` blocks on `receive` with the 30 s timeout (config `onboarding-tryout-accept-timeout-ms`), `complete` and cancellation `put` the result. Scenarios: accepted, timeout, superseded, cancel-only-source, invalid request.
3. **Snap environment**: `environment-main-service.unset-snap-exported-variables` / `restore-snap-exported-variables` (environmentMainService.ts:75-108) over a process-env state, and `electron-pty-host-starter.create-pty-host-configuration` (electronPtyHostStarter.ts:86-107) around them. Scenarios `main-process-snap-env-*`, `main-process-pty-host-env-without-snap`.

Also: `metered-connection-main-service.set-is-browser-connection-metered` (meteredConnectionMainService.ts:28-31, meteredConnection.ts:116-133; reads boundary config `network-metered-connection`, owner platform-core); `dialog-main-service.show-message-box` records the Linux `massageMessageBoxOptions` result (dialogMainUtils.ts:43-67). Features: `window-lifecycle` (main-startup, window-open, window-close, app-quit, window-reload, agents-window-open) and `hot-exit` (window-reload, scenario `main-process-reload-hot-exit-keeps-dirty`) are tagged; `skips/main-process.features.json` is empty.

### Breaking changes

- `native-host-main-service.open-agents-window` now responds `{}` (the code's `Promise<void>`, nativeHostMainService.ts:375) instead of `{opened: true}`, and its request gains the optional `IOpenAgentsWindowOptions` fields (folder_uri, reveal, folder_uri_is_default, draft, onboarding_session_resource). Callers: agents `open-agents-window-command.cmd-workbench-action-openagentswindow` calls it without reading the result (no break); agents' boundary stub still declares `{opened}` in its response and should drop it. Oracle `oracle-main-process-agents-window-new-window-reveal-omitted` reads only `ok` and the call count.

### Gaps and assumptions

- The `file-service` calls in `windows-main-service.open-agents-window` say `on: w1`: the model's file service lives per window, the main process has its own (simulator/model approximation).
- `sendWhenReady`'s cancellation token is not modeled: a queued `vscode:runOnboardingTryout` is still flushed on ready after a cancel (windowImpl.ts:1664-1667).
- `OnboardingTryoutHandoff.dispose` and the `Promise.race` against the opening (onboardingTryoutHandoff.ts:46-52, 110-117) are not modeled.
- `ensureAgentsWindow`'s "Agents workspace is not configured" throw is not reachable: the workspace path always exists.
- Mnemonic labels and the product title in `massageMessageBoxOptions` are not modeled; the user's choice is the logical button, as `buttonIndeces` maps it back.
- Optional request fields of an entry are fake-filled unless they have a `default`; `open-agents-window`'s optional fields default to `''` so an omitted `reveal` means a focus-only open.

# remote-server area notes (VS Code 1.144.0, 2c33b50b16)

Fragment: `fragments/remote-server.yaml`. Skips: `skips/remote-server.json`. All paths below are relative to the snapshot root.

Totals: 128 components (12 of them boundary stubs), 320 interfaces (31 boundary stubs), 26 configs, 3 schemas, 91 flows and 91 scenarios.

## 1. Entry points (242 inventory entries in this area)

All 242 entries are accounted for: 193 are modeled and 49 are skipped.

### Modeled

- **cli-command (37/37).** Each clap subcommand in `cli/src/commands/args.rs` is an interface `code-cli.cli-<subcommand path>` that cites its clap line. Flow `rs-cli-main` enters through `code-cli.main`, which dispatches on the subcommand with a dynamic call plus `targets`, as `cli/src/bin/code/main.rs:63-157` does with `match`.
  - `tunnel kill`, `tunnel restart` and `tunnel status` call `tunnel-singleton.rpc`, which models the lock-file RPC and fails with `no-running-tunnel`.
  - `ext *` and `status` translate into editor CLI arguments (`start_code`).
  - `agent *`, `serve-web`, `version *` and `command-shell` are narrated at the command level.
- **process-main (3/3).**

  | Entry | Covering flow |
  |---|---|
  | `src/server-main.ts:23` | `rs-remote-server-start` (`server-main.start`) |
  | `src/vs/server/node/server.main.ts:19` | `server-main-module.create-server`, reached from `rs-remote-server-http-request` |
  | `src/server-cli.ts:15` | `rs-remote-server-cli` |

- **ipc-channel (20/20).**
  - The 15 `registerChannel` calls in `serverServices.ts` are narrated steps (each citing its line) of `server-services.setup-server-services`.
  - `extensionGalleryManifest` is covered by `extension-gallery-manifest-ipc-service.register-channel`.
  - `remoteResourceHandler` is covered by `electron-remote-resource-loader.do-request` (flow `rs-remote-resource-load`).
  - `extensionRecommendationNotification`, `download` and `userDataSyncUtil` are steps of the `start` interfaces of `extensions-contributions-electron`, `remote-channels-contribution` and `user-data-sync-util-channel-contribution`.
- **service (28 modeled of 31).** Each implementation component cites its `createDecorator` line. Two cases are not the obvious owner:
  - `IRemoteExtensionsScannerService` is modeled by the *server* implementation (`server/node/remoteExtensionsScanner.ts`). The renderer implementation is workbench-shell's.
  - `IUserDataSyncUtilService` is cited by `user-data-sync-util-channel-contribution.start`, which exposes the service to the shared process. Its implementation is workbench-shell's.
- **vscode-command (57 modeled).** Each is `cmd-<id slug>` on its registering class or module, with one thin flow per command (`rs-cmd-*`). The flows are exercised by multi-step scenarios. Templated ids have their `${...}` stripped from the slug, for example `remote.tunnel.privacy${privacyOption.id}` becomes `tunnel-panel.cmd-remote-tunnel-privacy-privacyoption-id`.
- **workbench-contribution (48/48).** Each class has a component with a `start` interface (its constructor behavior, citing the constructor range). Each registering file has a `*-contribution-registrations` module whose `instantiate-contributions` interface calls the `start` interfaces, citing each `registerWorkbenchContribution` line. There are 9 startup flows, `rs-startup-*`.

### Skipped (49, grouped; see the JSON for exact entries)

| Group | Count | Reason |
|---|---|---|
| Developer or diagnostic commands | 17 | `Developer:` debug, profile or running-extensions commands, `triggerReconnect`, `pauseSocketWriting`, `developer.showCurrentFileAsReleaseNotes`, `update.showUpdateInfo`, `_update.applyupdate`, `_workbench.extensions.action.cleanUpExtensionsFolder` |
| UI toggles | 18 | Extension-editor find, Remote Explorer show/toggle, the remote and web-start menus, the update indicator, and the sync views, log, settings, help, manage, open/compare/resolve editors and load activity |
| Not registered in the deployed OSS product | 4 | `update.showCurrentReleaseNotes` (no `releaseNotesUrl`), `workbench.action.download` (no `downloadUrl`), `update.showUpdateReleaseNotes` (quality is not stable), `update.switchQuality.*` (web embedder only) |
| No-op placeholders and internal commands | 7 | `update.checking`, `update.downloading`, `update.updating`, `update.cancelling`, `_update.state`, `workbench.userData.actions.turningOn`, `_update.showUpdateInfo` |
| Services | 3 | `IUserDataSyncLogService` (log plumbing); `IExtensionHostProfileService` (developer profiling); `ISharedProcessTunnelService` (the implementation is platform-core's `platform/tunnel/node`, and this area's file only declares the decorator) |

Two skipped entries are also cited by modeled components, because their lines sit next to modeled code: `_workbench...cleanUpExtensionsFolder` (`electron-browser/extensions.contribution.ts:67`) and `_update.showUpdateInfo` (`postUpdateWidget.ts:69`). The skips file is authoritative for both.

## 2. Components (main ones; every one cites code)

- **Renderer (under `remote`):**
  - `extensions-workbench-service` (`extensionsWorkbenchService.ts:976`): install, queryLocal, uninstall, openSearch, open, the update-check timer, autoUpdateExtensions
  - `global-extension-enablement-service`
  - `management-persistent-connection` (`remoteAgentConnection.ts:532-830`): reconnection loop and state events
  - `remote-agent-connection`: handshake and initial-connection retries
  - `remote-authority-resolver-service`, `remote-socket-factory-service`
  - `remote-agent-connection-status-listener` (`remote.ts:787-1050`)
  - The command modules: `extensions-contribution-commands`, `tunnel-view-commands`, `remote-electron-commands`, `update-actions`, `user-data-sync-electron-commands`
  - The 48 contribution components
- **Shared process:**
  - `extension-management-channel`
  - `node-extension-management-service`: the node `ExtensionManagementService`. It is renamed with a `node-` prefix to avoid colliding with workbench-shell's workbench `ExtensionManagementService`.
  - `install-extension-in-profile-task`, `extensions-downloader`, `extensions-scanner`
  - `extension-signature-verification-service`, `extension-gallery-service`, `extension-gallery-manifest-service`, `allowed-extensions-service`
  - `extensions-scanner-service`, with system extensions matching the fixture's built-ins
  - `extensions-profile-scanner-service` (extensions.json, `store` interfaces)
  - Sync: `user-data-sync-service`, `settings-synchroniser`, `user-data-auto-sync-service`, `user-data-sync-store-service` (HTTP status mapping and the session limit), `user-data-sync-enablement-service`, `user-data-sync-account-service`, `user-data-sync-machines-service`, `user-data-sync-store-management-service`, `user-data-sync-local-store-service`, `user-data-sync-resource-provider-service`
- **Remote server:**
  - `server-main`, `server-main-module`, `remote-extension-host-agent-cli`
  - `remote-extension-host-agent-server` (`remoteExtensionHostAgentServer.ts:69-520`), with HTTP routes, the handshake and reconnection-token tables
  - `management-connection`, with the grace and short-grace disposal timers
  - `extension-host-connection`, `server-lifetime-service`, `server-services`, `remote-agent-environment-channel`, `web-client-server`, `server-agent-host-manager`, `extension-host-status-service`
- **CLI:** `code-cli` (skeleton) interfaces, `tunnel-singleton`.
- **External:** `marketplace-gallery-endpoint` (under `marketplace`), `user-data-sync-store-endpoint`, `dev-tunnels-service`.

## 3. Boundary stubs (all copied from shared shapes; no owner fragments were read)

| Owner | Stubs |
|---|---|
| workbench-shell | `editor-service.open-editor` (seam); `views-service.open-view-container`; `remote-explorer-service.{forward,close,set-editable,restore}`; `host-service.open-window`; `file-dialog-service.{pick-file-folder-and-open,pick-file-and-open,pick-folder-and-open,pick-file-to-save}`; `user-data-sync-workbench-service.{turn-on,turnoff,sign-in,sync-now,reset-synced-data,accept,download-sync-activity}`; `extension-gallery-account-service.sign-in` |
| platform-core | `command-service.execute-command` (seam, `command_id`/`args`); `opener-service.open`; `clipboard-service.write-text` |
| main-process | `abstract-update-service.{check-for-updates,download-update,apply-update,quit-and-install,set-internal-org}` (renderer IUpdateService is a channel client to the main process); `native-host-service.show-item-in-folder` |
| shared | `disk.write-file`, `disk.read-file`, `settings-store.user-write` (kind io) |

## 4. Config

### Configs I own

| Config | Value / default | Source |
|---|---|---|
| `extensions-auto-update` | `on` / `on` | extensions.contribution.ts:139-148. Its enum is only on/off; the code maps legacy values at extensionsWorkbenchService.ts:1225. The fixture reference was correct. |
| `extensions-auto-update-delay` | 12 h | |
| `extensions-auto-check-updates` | true | |
| `extensions-verify-signature` | true | |
| `extensions-request-timeout` | 60000 | |
| `extensions-allowed` | `*` / `*` | extensionManagement.ts:745-750. Declared `type: 'object'` but the code default is the string `'*'`; the model config has no `type`. Any non-object value, or exactly `{'*': true}`, means no restriction (allowedExtensionsService.ts:55-64). |
| `extensions-support-node-global-navigator` | false / false | extensions.contribution.ts:396-400; adds `--supportGlobalNavigator` to the remote extension host fork (extensionHostConnection.ts:287-289). |
| `settings-sync-ignored-extensions` | [] | |

### Product and environment values

**Deployed differs from what a Microsoft build ships:**
- `product-extensions-gallery-service-url` is `""`, because product.json has no `extensionsGallery`. As a result:
  - every gallery install, query and update check refuses (`no-extension-gallery-service-configured` or `not-allowed` "Marketplace is not enabled");
  - `workbench.action.remote.extensions` is not registered.
- `product-configuration-sync-store-url` is `""`. As a result:
  - settings sync is Uninitialized;
  - the sync commands and views are never registered (userDataSync.ts:124);
  - `manifest()` throws.
- `product-builtin-extensions-enabled-with-auto-updates` is `["GitHub.copilot-chat"]` (product.json:245); the code default is none.

**Other values:**
- `environment-is-built` is true.

Scenarios that model a Marketplace- or sync-enabled build override these values.

### Code constants modeled as configs (deployed equals default)

- `extensions-updates-check-interval-ms`
- `extensions-download-retries`
- `remote-reconnection-grace-time-ms` and `remote-reconnection-short-grace-time-ms` (`ProtocolConstants`; the server's `--reconnection-grace-time` overrides them)
- `remote-reconnect-timeout-ms`
- `remote-handshake-timeout-ms`
- `remote-initial-connection-max-attempts`
- `remote-disconnect-prompt-time-ms`
- `remote-reconnect-wait-times-s`
- `remote-max-port-number`
- `settings-sync-auto-sync-interval-ms`
- `settings-sync-trigger-delay-ms`
- `settings-sync-request-session-limit` and `settings-sync-request-session-interval-ms`
- `server-shutdown-timeout-ms`

### Configs owned by other areas

- `security-workspace-trust-enabled` (workbench-shell), read through its fixtures reference.

## 5. Fixture requests

- **remote-folder world.** A remote window (`remote_authority` `ssh-remote+dev-box`) and a server instance `srv1`. For now the resolver result is seeded in `remote-authority-resolver-service` initial state, and the server is a single unnamed instance.
- **Marketplace-enabled and sync-enabled worlds.** Products with `extensionsGallery` and `configurationSync.store`. Scenarios currently override the two product configs.
- **An installed user extension in the default profile**, for example `ms-python.python@2026.16.0` for auto update. Scenarios currently seed my own `extensions-profile-scanner-service` state.

## 6. Unsettled points and assumptions

- **Workbench-shell hop folded.** ExtensionsWorkbenchService installs through workbench-shell's workbench `ExtensionManagementService`, which routes to the local server's `extensions` channel. I call `extension-management-channel` directly and fold that hop.
  - The same applies to the renderer gallery service (`WorkbenchExtensionGalleryService`, workbench-shell), which is approximated by the shared-process `extension-gallery-service`.
  - The `uninstallExtension` command's `getInstalled` check is modeled with the profile store.
- **Reconnection token.** It is a request field (in the code it is `generateUuid()` per attempt) so scenarios can address it.
- **Version comparison.** Outdated detection compares versions with `!=`, not semver.
- **Gallery catalog.** The marketplace catalog (`ms-python.python`) is seeded state of my external stub.
- **Sync merge outcome.** The result is a choice (`no-changes`, `local-changes`, `remote-changes`, `conflict`). Only the settings synchroniser is modeled.
- **CLI agent and serve-web subcommands** are narrated, not modeled in depth.

## 7. Docs or common knowledge vs code

- **`extensions.autoUpdate`.** Commonly described as true/false/`onlyEnabledExtensions`/`onlySelectedExtensions`. In 1.144 it is `on`/`off`, and legacy values are mapped.
- **`extensions.autoUpdateDelay`.** It exists (12 h): new versions are delayed unless the publisher is product-trusted.
- **Metered connections.** Auto update and auto sync are suspended on metered connections. This is not modeled (see gaps).
- **`extensions.allowed` refusal error code.** An `extensions.allowed` refusal inside `installGalleryExtensions` surfaces as `IncompatibleTargetPlatform`, not `NotAllowed` (abstractExtensionManagementService.ts:730-733).
- **The OSS build has no Marketplace.** Installing by id fails, contrary to the usual "install from Marketplace" expectation.
- **Reconnection.** Reconnection does not give up after a fixed number of attempts. It runs until the grace time (3 h) expires or a permanent error occurs.
- **Server-side short grace.** The server shortens a disconnected client's grace to 5 min as soon as any other client connects.

## 8. Simulator gaps

- **Unbounded reconnection loop.** The `do…while` loop (`remoteAgentConnection.ts:669-745`) has no attempt limit. Fix round: it is a `foreach` over `lists.range(1000)` (the language's maximum), which is far more than the ~370 attempts that fit in the 3 h grace, so in practice only the grace time or a permanent error ends it.
- **Generated UUIDs.** There is no uuid helper; `generateUuid()` for the default connection token is `'uuid-' + string(random(1000000000))` (seeded, deterministic).
- **Entry inputs are faked.** Optional request fields left out of a scenario get fake values, so "no tkn / no cookie / no auth" is modeled as `null` (the declared default), not as an absent key.
- **Re-arming timers.** `ThrottledDelayer` and `disposableTimeout` re-arm themselves forever (`extensionsWorkbenchService.ts:2223`, `userDataAutoSyncService.ts:414`). The update check is modeled as `every_ms` with `count: 2`. Auto sync re-emits itself while `state.interval_runs < 2`, a model-only guard to stay within the event budget.
- **Static `set` paths.** These forced keyed rows (connections, disconnected timers, profile extensions) into `store` interfaces. `store get` with `default: null` reads as missing, so defaults are `{}` and the checks use `has(x.id)`.
- **Cancelling a scheduled timer.** This cannot be expressed: `acceptReconnection` cancelling `_disconnectRunner1/2` is modeled by deleting the row so the timer handler returns early (`management-connection.clean-resources`).
- **YAML 1.1 bool aliases.** Step aliases `on`/`off` are parsed as booleans; avoid them.

## 9. Known gaps

**Not modeled:**
- VSIX install path (`install(vsix)`)
- extension packs and dependencies
- pre-release handling
- `installEverywhere` and multi-server routing
- workspace-scoped extensions
- metered connection checks
- the extension host connection internals
- tunnels on the server
- the remote file system and terminal channels (narrated only)
- synchronisers other than settings
- profile sync
- web-only sync paths
- the handled-error path of `RemoteAuthorityResolverError`

**Unexecuted branches (8), with reasons:**
- `cli-tunnel-status` with a non-`NoRunningTunnel` RPC error.
- `extensions-workbench-service.uninstall` "Missing local": its only caller passes installed extensions.
- The malicious checker when the control manifest fetch fails.
- The status listener when the permanent failure is `handled`: no handled resolver errors are modeled.
- `settings-synchroniser.sync` re-fail after a read-resource error.
- `auto-sync` after the AutoSync was disposed.

## Reconciliation round

The generator now lives in `gen/remote-server/`: `build.py` collects `parts/*` and applies `transform.py`.

### Changes, by binding decision

- **Decision 2 (files and disk use `resource`).** `disk.write-file` and `disk.read-file` now send `resource`; their stubs copy platform-core's contract. `settings-store.user-write` now sends `{key, value}`: the remote settings are written one key at a time.
- **Decision 7 (seam ownership and kinds).** The `clipboard-service` and `native-host-service` stubs now name workbench-shell as owner, and the stub components have kind `service`.
- **Decision 9 (restore missing hops).** Installs now go through workbench-shell's workbench `ExtensionManagementService`, as stubs:
  - `extension-management-service.install-from-gallery`
  - `extension-management-service.update-from-gallery` (used by auto update, matching `extensionsWorkbenchService.ts:3075-3078`)
  - `extension-management-service.get-installed`
  - `extension-management-service.uninstall`

  The expected owner behavior is to forward to this area's `extension-management-channel.*` and return its value.
- **Decision 10 (area fixtures).** I defined four fixtures:

  | Fixture | What it adds |
  |---|---|
  | `remote-server-seed` | `redhat.vscode-yaml@1.14.0` installed in the default profile, plus the `commands-registry` rows for every modeled command (decision 6) |
  | `remote-server-marketplace` | the gallery URL as a config override |
  | `remote-server-sync` | the sync store URL as a config override |
  | `remote-server-srv1` | topology `remote-server-process: [srv1]`, so server state is keyed `@srv1` |

  The catalog now also lists `redhat.vscode-yaml@1.14.0`, so the seeded extension is not outdated.

### Other changes

- **Command handlers tolerate a bare command-service call.** `command-service` calls a handler with only `{command_id, args}`. Every `cmd-*` handler therefore first merges its declared defaults under its input (`vars.cmd`).
- **Forward a Port without input.** If the input box is dismissed, the command returns without forwarding.
- **Skip reasons.** They were reworded into the accepted categories (decision 11).

### Shared-fixture request

A remote-folder world with `workspace-context@w1.remote_authority` set to `ssh-remote+dev-box`.

## Fix round

The fix round lives in `gen/remote-server/fixround/` (`apply.py` with `new/`, `scen/` and `scen_edits.py`); `build.py` applies it last, and regenerating reproduces the fragment byte for byte.

### Fixes

- **Connection token (security).** `createServer` runs `determineServerConnectionToken(args)` first (remoteExtensionHostAgentServer.ts:612-618), memoized by server-main.ts:57-63 for both requests and WebSocket upgrades (new `server-main.on-upgrade`, server-main.ts:100-108). New component `server-connection-token`:
  - `parse-server-connection-token` (serverConnectionToken.ts:50-90): `--without-connection-token` → None; with a token or token file → parse error (55-58); token file + token → error (63-65); unreadable file → error (67-72); bad characters → error (74-76, 82-84); otherwise Mandatory; nothing → the default.
  - `determine-server-connection-token` (92-120): reads `<user-data-dir>/token` (server.main.ts:42-48 always sets user-data-dir), else generates and stores one; without user-data-dir only generates. An empty `--connection-token ""` is dropped by parseArgs (argv.ts:402-405), so it falls back to the stored/generated token: the server is never tokenless unless `--without-connection-token`.
  - `request-has-valid-connection-token` (122-132): the single `tkn` query value, then the `vscode-tkn` cookie; repeated `tkn` parameters form an array and never match; None accepts everything.
  - A parse error exits the process (`exited`), so every later request fails.
  - `handle-request` returns 403 for an empty, missing, wrong or repeated token (157-160); `/version` and `/delay-shutdown` stay open (145-155). Resource responses carry the remoteResourceResponse.ts headers.
  - The handshake checks `auth` only for a Mandatory token (308-310). The signature check applies only with vsda installed (279, 360-378); the OSS build has none (`has_vsda: false`), and signedData equal to the token is accepted (web client).
  - `get-environment-data` returns the token ('' for None, remoteAgentEnvironmentImpl.ts:113).
  - Scenarios: `remote-server-token-http-gate` (empty, missing, wrong, repeated, wrong cookie, query, cookie), `-token-no-args-generates-and-stores`, `-token-empty-arg-ignored`, `-token-no-user-data-dir`, `-token-file`, `-token-file-bad-characters`, `-token-parse-errors`, `-token-bad-arg-exits`, `-token-without-connection-token`, `-token-handshake-auth` (empty, missing, wrong), `-handshake-web-client-signed-data`, `-handshake-oss-no-vsda`.
- **`extensions-allowed` is an object** and `is-allowed` follows allowedExtensionsService.ts:55-143 (id entry: boolean, 'stable', version list with platform; then publisher: boolean, 'stable'; then `'*': true`; else refused, with the reason text).
- **The remote extension host is forked (R1).** `extension-host-connection.start` builds exec args (`--inspect[-brk]` for a debug port), fork args (`--type=extensionHost --transformURIs --useHostProxy=false [--supportGlobalNavigator]`) and records the forked `bootstrap-fork` process, then sends it the socket on `VSCODE_EXTHOST_IPC_READY` (extensionHostConnection.ts:247-322). New: process exit (`on-process-exit`: setExitInfo, cleanup, server forgets the connection and releases the lifetime token), `getExtensionHostExitInfo`, extension host reconnection / duplicate / unknown token (remoteExtensionHostAgentServer.ts:451-502), and the grace reduction for extension hosts (386-389).
- **Reconnect loop has no 20-attempt cap (R2)**; see simulator gaps. `remote-server-reconnect-no-attempt-cap` reconnects at attempt 41.
- **Initial connection retries any error** up to 5 attempts (remoteAgentConnection.ts:440-457), not only listed codes.
- **Running Extensions editor.** `RuntimeExtensionsInput` (runtimeExtensionsInput.ts:16-56: singleton, Readonly + Singleton + RequiresModal, `runtime-extensions:/default`) and `workbench.action.showRuntimeExtensions` (abstractRuntimeExtensionsEditor.ts:521-541), no longer skipped.
- **Shared remote-folder authority.** The resolver seed also resolves `ssh-remote+devbox` (fixtures.yaml's `remote-folder`), and `remote-server-srv1` starts srv1 with `--connection-token tok-dev`.
- **Features:** `feature:extension-management`, `feature:settings-sync`, `feature:remote-development` tagged on the install/uninstall/auto-update/channel-install, sync turn-on/off/trigger/status and remote connect/reconnect/handshake/HTTP/exit flows.

### Breaking changes

Grepped `fragments/*.yaml`, `judge/` and `oracle/` for each changed interface.

| Change | Citation | Callers broken |
|---|---|---|
| `allowed-extensions-service.is-allowed` returns `{allowed, reason}` and reads `extensions-allowed` as an object | allowedExtensionsService.ts:55-143 | none outside this fragment. Own scenarios moved from `'redhat'` / `'redhat,ms-python'` strings to objects. The oracle cases now run as written. |
| `remote-socket-factory-service.connect` now goes through `server-main.on-upgrade` (createServer first) | server-main.ts:100-108 | none outside this fragment |
| `remote-extension-host-agent-server.handle-web-socket-connection`: `auth` is checked only for a Mandatory token; vsda signature only with vsda | remoteExtensionHostAgentServer.ts:308, 360-378 | own `remote-server-handshake-refusals` now seeds `has_vsda: true` |
| `extension-host-connection.start` takes `{token, start_params}` and forks | extensionHostConnection.ts:247-322 | none outside this fragment |
| `remote-agent-connection.connect-remote-agent-management` retries every error (no `retry` events) | remoteAgentConnection.ts:440-457 | own `remote-server-connect-refused` now counts 5 attempts instead of `retries == 4` |
| `management-persistent-connection.run-reconnecting-loop` has no 20-attempt cap | remoteAgentConnection.ts:669-745 | judge `bench-r2-default-grace-keeps-trying` asserted the cap (`connect` size 21, not `connection-gain`): with 30 faults the loop now reconnects at call 31. Re-scorers should re-adapt it. |
| `remote-extension-host-agent-server` state: `connection_token` is now the resolved token, set by createServer from `args` | remoteExtensionHostAgentServer.ts:614 | oracle `oracle-remote-server-connection-token-no-args-mandatory` seeds `connection_token: ''`; createServer overwrites it, and the request still gets 403 as the test expects |

### Still open

- The renderer-side `RemoteExtensionHost` and extensionKind placement (judge R1 probe `bench-r1-workspace-extension-runs-remotely` expects `extension-host-manager.start/create`) are exthost's code (src/vs/workbench/services/extensions/common/remoteExtensionHost.ts); exthost's `extension-host-manager.create` only starts the local process host.
- `RequiresModal` placement in the modal editor part belongs to workbench-shell's `editor-service.open-editor`, which has no modal part.
- `onDidInstallExtensions` → `handle-delta-extensions` (judge R3) is not wired.
- Metered-connection and consent checks for auto update (judge R4) are not modeled.

# Notes: agents area (agent host process, Agents window, MCP)

Fragment: `examples/vscode/fragments/agents.yaml`. Skips: `examples/vscode/skips/agents.json`.
Snapshot: VS Code 1.144.0 (2c33b50b16). Paths below are relative to the snapshot. The fragment is generated from a
builder script kept outside the repo. Hand edits are fine, but the ids must stay stable.

Abbreviations: AH = `src/vs/platform/agentHost`, MC = `src/vs/workbench/contrib/mcp`, PM = `src/vs/platform/mcp`,
SS = `src/vs/sessions`.

## 1. Entry points

My inventory has 636 entries: 308 vscode-command, 170 service, 141 workbench-contribution, 10 ipc-channel, 6 process-main and
1 extension-point. Of these, 84 are covered at their lines by flow-reachable entities and 552 are skipped (5 more of the covered ones are also skipped because their coverage is proximity only, see §9), for 557 skip objects in
`skips/agents.json`, one object per entry.

### Covered

**Process mains (6)**
- `agentHostMain` is covered by flow `agents-agent-host-startup` (AH/node/agentHostMain.ts:74-80).
- `agentHostServerMain` is covered by `agents-agent-host-server-startup`.
- `diffWorkerMain` is covered by `agents-diff-compute` (the worker `diff-worker.handle-message`).
- `sessions.main` is covered by `agents-sessions-window-startup`.
- `sessions.desktop.main` (line 26, `registerOpenAgentsWindowCommand()`) is covered by `open-agents-window-command.register`, which the sessions startup flow calls.
- `sessions.web.main` is covered by `agents-sessions-web-startup`.

**IPC channels (10)**

| Channel | Covered by | Flow |
|---|---|---|
| agentHostLogger | agent-host-logger-channel | agents-agent-host-log-forward |
| agentHost | agent-service (ProxyChannel over AgentService) | |
| agentHostProtocol | protocol-server-handler | the agents-ahp-* flows |
| agentHostManagement | agent-host-management-service | agents-agent-host-shutdown |
| agentHostConnectionTracker | agent-host-connection-tracker | agents-agent-host-websocket |
| agentHostClientProxy | agent-host-client-proxy-channel | |
| agentHostClientByokLm | agent-host-client-byok-lm-channel | |
| mcpGalleryManifest | mcp-gallery-manifest-ipc-service | agents-mcp-gallery-manifest-set |
| mcpGatewayToolBroker, browser and electron-browser variants | mcp-gateway-tool-broker-channel | agents-mcp-gateway |

**Extension point (1).** `mcpServerDefinitionProviders` is covered by `extension-mcp-discovery`, which the startup flow reaches through `mcp-discovery.start`.

**Services (21).** Each implementation component cites its createDecorator line:

| Service | Component |
|---|---|
| IAgentService | agent-service |
| IAgentHostProviderService | agent-host-provider-service |
| IAgentHostStateManager | agent-host-state-manager |
| IAgentHostDatabase | agent-host-database |
| IAgentHostTurnService | agent-host-turn-service |
| IAgentHostAuthenticationService | agent-host-authentication-service |
| IAgentHostWorktreeIsolation | worktree-isolation |
| IAgentHostWorktreeCleanupService | agent-host-worktree-cleanup-service |
| IDiffComputeService | diff-compute-service |
| IAgentHostEnablementService | browser-agent-host-enablement-service |
| IAllowedMcpServersService | allowed-mcp-servers-service |
| IMcpService | mcp-service |
| IMcpRegistry | mcp-registry |
| IMcpSamplingService | mcp-sampling-service |
| IMcpElicitationService | mcp-elicitation-service |
| ISessionsManagementService | sessions-management-service |
| ISessionsService | sessions-service |
| ISessionsProvidersService | sessions-providers-service |
| ISessionsListModelService | sessions-list-model-service |

**Workbench contributions (16).**
- The 12 MCP contributions are reached through `sessions-workbench.startup`:
  - mcp.contribution.ts:74-79 and :109-112
  - mcp.view.contribution.ts:9
  - electron-browser/mcp.contribution.ts:23
- From the Agents window:
  - LocalAgentHostContribution (:98)
  - LocalAgentHostLifecycleContribution
  - DefaultSessionsProviderContribution
- AgentHostContribution (localAgentHost.contribution.ts:90) is covered only through the tolerance window next to the `LocalAgentHostContribution` class lines. That is a weak match; see §9.

**vscode-commands (40).**
- MCP: 24 of the 27 MCP commands each have a `cmd-*` interface on `mcp-commands` and a flow, or are reached from List Servers or Server Options.
- Agents window commands:
  - sessionsViewPane.renameSession, deleteSession, archiveSessionsWithUndo, pinSession and unpinSession
  - sessions.sessionHeader.rename and sessions.closeAllSessions
  - NewChatInSessionsWindowAction and workbench.action.chat.branchChatSession
  - workbench.action.openAgentsWindow
  - workbench.action.chat.restartLocalAgentHost
- The check tool also counts four commands as covered only because they sit next to cited lines:
  - `CLOSE_SESSION_COMMAND_ID` (sessionsActions.ts:1969, next to the header-rename run lines)
  - the three agent-host developer commands at agentHost.contribution.ts:12, 14 and 15
  
  None of the four has a modeled handler. They are listed in skips/agents.json as well (see §9).

### Skipped, grouped

Each line is: count, kind, reason. The reasons are written in full in the JSON file.

```
84 vscode-command | UI toggle: no state beyond the layout
72 service | agent host internal service built by agentHostServices.ts/agentHostBootstrap.ts (no registerSingleton); not modeled at this depth: the modeled AgentService create/dispatch/turn flows abstract it
44 vscode-command | not modeled: sessions list, chat tabs and grid command outside the modeled session create/send/rename/archive/delete/pin flows
37 vscode-command | not modeled: agent host providers (pickers, settings, agent merge, remote hosts) command outside the modeled session create/send/rename/archive/delete/pin flows
26 workbench-contribution | not modeled: agent host providers (pickers, settings, agent merge, remote hosts) contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
25 workbench-contribution | not modeled: Agents window chat input, pickers and backgrounds contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
20 service | Agents window UI service (Agents window shell); not modeled: no state that the modeled session lifecycle reads
17 vscode-command | not modeled: Agents window chat input, pickers and backgrounds command outside the modeled session create/send/rename/archive/delete/pin flows
15 vscode-command | developer or internal command with no user-visible behavior
15 vscode-command | not modeled: session changes view and changeset operations command outside the modeled session create/send/rename/archive/delete/pin flows
15 workbench-contribution | not modeled: sessions list, chat tabs and grid contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
14 vscode-command | internal command (leading underscore) called by other components, not user-facing; not modeled
11 workbench-contribution | not modeled: session changes view and changeset operations contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
10 service | MCP service outside the modeled start/tool/sampling/gateway flows (gallery, management, scanning, sandbox, dev-mode, gateway, Copilot global config); not modeled
10 workbench-contribution | not modeled: agent feedback comments on diffs contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
9 service | Agents window UI service (Agents window chat input, pickers and backgrounds); not modeled: no state that the modeled session lifecycle reads
8 service | remote/SSH/WSL/tunnel/dev-container agent host connection service; not modeled: only the local agent host connection is modeled
8 vscode-command | not modeled: Agents window editor area tabs command outside the modeled session create/send/rename/archive/delete/pin flows
6 vscode-command | not modeled: Agents window shell command outside the modeled session create/send/rename/archive/delete/pin flows
6 vscode-command | not modeled: AI customization tree view command outside the modeled session create/send/rename/archive/delete/pin flows
6 vscode-command | not modeled: GitHub pull request and issue actions command outside the modeled session create/send/rename/archive/delete/pin flows
5 vscode-command | MCP UI command (marketplace browsing, chat prompt insertion or OAuth secret entry) without modeled state; not modeled
5 workbench-contribution | not modeled: Agents window editor area tabs contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
5 workbench-contribution | not modeled: onboarding tours contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
4 vscode-command | not modeled: agent feedback comments on diffs command outside the modeled session create/send/rename/archive/delete/pin flows
3 vscode-command | not modeled: account menu and sign-in widget command outside the modeled session create/send/rename/archive/delete/pin flows
3 workbench-contribution | not modeled: Agents window shell contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
2 service | Agents window UI service (session changes view and changeset operations); not modeled: no state that the modeled session lifecycle reads
2 service | Agents window UI service (GitHub pull request and issue actions); not modeled: no state that the modeled session lifecycle reads
2 service | Agents window UI service (remote session tools); not modeled: no state that the modeled session lifecycle reads
2 vscode-command | not modeled: automations (scheduled agent runs) command outside the modeled session create/send/rename/archive/delete/pin flows
2 vscode-command | not modeled: get started checklist command outside the modeled session create/send/rename/archive/delete/pin flows
2 vscode-command | not modeled: Agents window search command outside the modeled session create/send/rename/archive/delete/pin flows
2 workbench-contribution | not modeled: automations (scheduled agent runs) contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
2 workbench-contribution | not modeled: GitHub pull request and issue actions contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
2 workbench-contribution | not modeled: session comparison grid contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
2 workbench-contribution | not modeled: session terminals contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 service | implementation registered by the chat area (src/vs/workbench/contrib/chat/browser/remoteAgentHost/remoteAgentHost.contribution.ts:46): owned by chat
1 service | BYOK language-model handler (AgentHostByokLmHandler, registered in the sessions and chat contributions); not modeled beyond the agentHostClientByokLm channel (agent-host-client-byok-lm-channel)
1 service | browser list of agent host connections (AgentHostConnectionsService); not modeled: connection management UI state
1 service | implementation registered under src/vs/workbench/services (src/vs/platform/agentHost/common/agentHostFileSystemService.ts:80): owned by workbench-shell
1 service | MCP OAuth metadata lookup for agent-host sessions; not modeled
1 service | implementation registered under src/vs/workbench/services (src/vs/workbench/services/agentHost/common/agentHostResourceService.ts:623): owned by workbench-shell
1 service | desktop implementation WorkbenchAgentHostService is registered under src/vs/workbench/services/agentHost: owned by workbench-shell; its wrapped LocalAgentHostServiceClient is modeled as local-agent-host-service-client
1 service | implementation registered by the chat area (src/vs/workbench/contrib/chat/browser/remoteAgentHost/remoteAgentHost.contribution.ts:39): owned by chat
1 service | implementation registered by the chat area (src/vs/workbench/contrib/chat/browser/remoteAgentHost/remoteAgentHost.contribution.ts:38): owned by chat
1 service | implementation registered by the chat area (src/vs/workbench/contrib/chat/browser/remoteAgentHost/remoteAgentHost.contribution.ts:41): owned by chat
1 service | implementation registered by the chat area (src/vs/workbench/contrib/chat/browser/remoteAgentHost/remoteAgentHost.contribution.ts:44): owned by chat
1 service | implementation registered by the chat area (src/vs/workbench/contrib/chat/browser/remoteAgentHost/remoteAgentHost.contribution.ts:43): owned by chat
1 service | implementation registered by the chat area (src/vs/workbench/contrib/chat/browser/remoteAgentHost/remoteAgentHost.contribution.ts:42): owned by chat
1 service | registerSingleton implementation McpGalleryManifestService lives under src/vs/workbench/services/mcp: owned by workbench-shell; the IPC variant is modeled as mcp-gallery-manifest-ipc-service
1 service | Agents window UI service (agent feedback comments on diffs); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (aquarium easter egg overlay); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (session canvases); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (code review runs); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (Agents window editor area tabs); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (Agents window extension suggestions); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (get started checklist); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (Agents window layout); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (agent host providers (pickers, settings, agent merge, remote hosts)); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (session comparison grid); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (session input banners (disk space, worktree cleanup)); not modeled: no state that the modeled session lifecycle reads
1 service | Agents window UI service (sessions list, chat tabs and grid); not modeled: no state that the modeled session lifecycle reads
1 vscode-command | not modeled: apply worktree changes to the parent repository command outside the modeled session create/send/rename/archive/delete/pin flows
1 vscode-command | not modeled: code review runs command outside the modeled session create/send/rename/archive/delete/pin flows
1 vscode-command | not modeled: Agents window files view command outside the modeled session create/send/rename/archive/delete/pin flows
1 vscode-command | not modeled: session comparison grid command outside the modeled session create/send/rename/archive/delete/pin flows
1 vscode-command | not modeled: session terminals command outside the modeled session create/send/rename/archive/delete/pin flows
1 workbench-contribution | not modeled: account menu and sign-in widget contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: apply worktree changes to the parent repository contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: session browser view contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: session canvases contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: chat debug view contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: custom view test harness contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: Agents window extension suggestions contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: GitHub file tree view contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: Agents window files view contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: get started checklist contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: Agents window layout contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: system-wide open-agents keybinding contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: policy-blocked banner contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: remote session tools contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: Agents window search contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: session input banners (disk space, worktree cleanup) contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: tunnel host sharing contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
1 workbench-contribution | not modeled: workspace folder management contribution (UI, context keys, notifications or telemetry wiring) outside the modeled flows
```

Notes on the skip groups:
- **Services registered in another area are skipped as owned by that area.** The owner is the area that owns the registerSingleton implementation:
  - chat: the RemoteAgentHost* resolvers, CloudSandbox*, MissionControl*
  - workbench-shell: IAgentHostService (WorkbenchAgentHostService), IAgentHostResourceService, IAgentHostFileSystemService, IMcpGalleryManifestService
- **Agent-host internal services** (`AH/node/**` without registerSingleton) are built in AH/node/agentHostServices.ts:102-183. They sit beneath the modeled AgentService create/dispatch/turn flows and are not modeled one by one.
- **Agents window UI commands and contributions** (pickers, tabs, layout, tours, telemetry, badges) are skipped:
  - "UI toggle" for layout, focus and navigation commands
  - "not modeled: <feature>" for feature commands outside the session lifecycle

## 2. Components and code references

Agent host process (parent `agent-host`):

| Component | Code |
|---|---|
| agent-host-main | AH/node/agentHostMain.ts:74-80, 113-546, 616-688 |
| agent-host-provider-service | AH/node/agentHostProviderService.ts:81-141 |
| agent-service | AH/node/agentService.ts:943; createSession 5864-5971, dispatchAction 11610-11670, 12682+ |
| agent-host-state-manager | AH/node/agentHostStateManager.ts:1171, 2588-2624, 3083-3091 |
| agent-host-database | AH/node/agentHostDatabase.ts:673-731, 1166 |
| agent-side-effects | AH/node/agentSideEffects.ts:1795-1941 |
| agent-host-turn-service | AH/node/agentHostTurnService.ts:126-172 |
| agent-host-turn-starter | AH/node/agentHostTurnStarter.ts:70-148 |
| turn-admission-contribution | AH/node/chatContributions/turnAdmission/turnAdmissionContribution.ts:29-43 |
| session-permissions | AH/node/sessionPermissions.ts:253-360 |
| command-auto-approver | AH/node/commandAutoApprover.ts:286-315 |
| agent-host-authentication-service | AH/node/agentHostAuthenticationService.ts:109-273 |
| worktree-isolation | AH/node/shared/worktreeIsolation.ts:1118-1170 |
| agent-host-worktree-cleanup-service | AH/node/agentHostWorktreeCleanupService.ts:322-352 |
| protocol-server-handler | AH/node/protocolServerHandler.ts:801-953, 991-1040, 2126-2440 |
| agent-host-management-service | AH/node/agentHostManagementService.ts:294-331 |
| agent-host-connection-tracker | AH/node/agentHostMain.ts:391-477 |
| agent-host-server-main | AH/node/agentHostServerMain.ts:90-401 |
| diff-compute-service, diff-worker | AH/node/diffComputeService.ts, diffWorkerMain.ts |
| agent-host-process-manager | AH/node/agentHostService.ts:37-260 |
| agent-host-logger-channel | AH/node/agentHostMain.ts:127 |
| copilot-agent, claude-agent | the harnesses, as stubs with behavior; Claude authentication at claude/claudeAgent.ts:781-785 |

`agent-host-process-manager` runs in the main process, but it is parented under `agent-host` because agents owns AH/node.

Renderer side (parent `agents`):
- **Agent host client:**
  - local-agent-host-service-client (AH/electron-browser/localAgentHostService.ts:173, 816-819, 866-879)
  - agent-host-client-proxy-channel
  - agent-host-client-byok-lm-channel
  - browser-agent-host-enablement-service
- **MCP:**
  - mcp-service, mcp-server-runtime (class McpServer), mcp-server-connection, mcp-registry, allowed-mcp-servers-service
  - mcp-tool, mcp-language-model-tool-contribution, mcp-tool-implementation
  - mcp-sampling-service, mcp-elicitation-service
  - mcp-discovery, extension-mcp-discovery
  - mcp-commands, which groups the Action2 classes of mcpCommands.ts the way the brief's `save-file-actions` example groups commands
  - mcp-gateway-tool-broker-channel and -contribution
  - mcp-gallery-manifest-ipc-service, which runs in a utility process and is parented here
  - 8 startup-only MCP contributions
- **Agents window:**
  - sessions-main, sessions-web-main, sessions-workbench
  - sessions-providers-service, sessions-management-service, sessions-service, sessions-list-model-service
  - local-agent-host-sessions-provider, which carries the BaseAgentHostSessionsProvider logic at baseAgentHostSessionsProvider.ts:5299, 7030, 7248, 7391, 7463, 7935
  - copilot-chat-sessions-provider
  - local-agent-host-contribution, default-sessions-provider-contribution, local-agent-host-lifecycle-contribution
  - sessions-view-actions, sessions-actions, sessions-chat-actions
  - agent-host-electron-contribution, open-agents-window-command

**Naming deviations**
- **McpServer is `mcp-server-runtime`, not `mcp-server`.** The skeleton already uses `mcp-server` for the external MCP server process. I gave that external component two interfaces: `mcp-server.initialize` and `mcp-server.tools-call`.
- **LocalAgentHostServiceClient is `local-agent-host-service-client`.**

## 3. Boundary stubs

Every stub is declared with `attributes: {boundary: true, owner}`. The fragments of the other areas did not exist yet, apart from main-process, which declares component stubs only. So all request and response shapes come from the shared shapes or from what my call sites send and read. Expect alignment in reconciliation.

| Owner | Stubs |
|---|---|
| workbench-shell | workspace-trust-management-service.is-workspace-trusted {trusted}; workspace-trust-request-service.request-workspace-trust {message} -> {granted}; editor-service.open-editor {resource}; workbench-mcp-management-service.install {name, config, target}; lifecycle-service.on-before-shutdown (event, {reason} -> {veto}) |
| chat | language-models-service.get-language-model-ids -> {ids}; language-models-service.send-chat-request {model, messages} -> {text}; chat-service.send-request {resource, query} |
| exthost | extension-service.activate-by-event {activation_event} |
| main-process | native-host-main-service.open-agents-window {source} |

Component stubs lifecycle-service and editor-service are copied from the main-process fragment.

## 4. Config

**Configs I own.** Unless noted, deployed = default, and product.json sets none of these keys.

| Config | Value | Default sources |
|---|---|---|
| chat-mcp-autostart | newAndOutdated | chat.shared.contribution.ts:1285/1288 |
| chat-mcp-access | all | :1141/1154 (policy ChatMCP can override) |
| chat-mcp-apps-enabled | true | :1301/1304 |
| chat-mcp-server-sampling | {} | :1355; the per-entry schema defaults are not applied, see §7 |
| chat-agent-host-claude-agent-enabled | true | AH/common/agentHostStarter.config.contribution.ts:334 |
| chat-agent-host-codex-agent-enabled | true | AH/common/agentHostStarter.config.contribution.ts:364 |

- **chat-agent-host-codex-agent-enabled differs.** Deployed is true; the default is the expression `quality !== 'stable'`. product.json in this OSS build has no `quality`, so it evaluates to true here; Stable builds deploy false. No behavior reads this config: Codex registration is driven by the env var or root config (AH/node/agentHostMain.ts:210-225).

**Code constants** (`attributes.constant: true`):

| Config | Value | Code |
|---|---|---|
| agent-host-max-restarts | 5 | AH/node/agentHostService.ts:17-20 |
| agent-host-shutdown-timeout-ms | 6000 | AH/node/agentHostService.ts:19 |
| mcp-gateway-startup-grace-period-ms | 5000 | mcpGatewayToolBrokerChannel.ts:55 |
| agent-host-server-default-port | '8081' | agentHostServerMain.ts:92-94 |
| ahp-supported-protocol-versions | | registry.ts:36-39 |
| agent-host-worktree-cleanup-interval-ms | 300000 | |

**References.**
- chat-disable-ai-features (chat, false)
- chat-tools-global-auto-approve (chat, false, chat.shared.contribution.ts:832-833)

**Not read.** I don't read any of the fixture's shared configs.

## 5. Fixture requests

- **A workspace-trust answer the stubs can return.** The `untrusted-folder` fixture seeds `workspace-context@w1.trusted=false`, but my workspace-trust stub can only return its schema example (true). The workspace-trust branches of `mcp-registry.resolve-connection` therefore can't run locally:
  - the quiet start that throws `workspaceTrust`
  - the refused trust request
  
  Once the workbench-shell owner defines `is-workspace-trusted` over workspace-context, a scenario with `fixtures: [untrusted-folder]` and the workspace-db server will run them.
- **MCP servers and Agents window providers in a fixture.** The shared fixtures have none, so they are seeded in component `state.initial` (mcp-server-runtime: github, workspace-db) or in per-scenario `state`. A shared `mcp-servers` fixture would help other areas, such as chat tools.

## 6. What the code didn't settle, and my assumptions

- **The Claude env var.** The agent host gets Claude enablement through `AgentHostClaudeAgentEnabledEnvVar` (agentHostMain.ts:204-206). I assume the starter derives it from `chat.agentHost.claudeAgent.enabled`, so register-providers reads that config.
- **SDK availability.** Product.json has no agent SDK entries, so `claude_sdk_available` defaults to false (Claude not registered) unless a scenario says otherwise.
- **Provider routing.** `get-provider-for-session` uses only the URI scheme (copilot:, claude:). The associated-provider map is not modeled.
- **Agent host state is flattened.** I key it by session, and the session's default chat stands for "chat". Peer chats, the chat catalog and SDK sessions are not modeled.
- **The protocol path from the Agents window.** The provider's rename, archive and delete go through the AHP `dispatchAction` and `disposeSession` requests (`connection.dispatch`). I model them as direct calls into `protocol-server-handler`, without the transport, reconnect and replay.
- **Sending the first request.** It goes through ChatService (chat area) and the chat area's agent host session contribution. That is where `createSession` happens on the host, and it is outside my area. So `agents-sessions-send` ends at the `chat-service.send-request` stub.
- **Command invocation inside my area.** The commands executed with `commandService.executeCommand` (ServerOptions, AddConfiguration, ConfigureSamplingModels, BrowseResources, AgentHostServerOptions, renameSession from the header) are modeled as direct calls to my `cmd-*` interfaces, not through `command-service.execute-command`.
- **Restart Local Agent Host.** Its action class lives in the chat area (src/vs/workbench/contrib/chat/electron-browser/actions/restartAgentHostAction.ts). It is registered from my file SS/contrib/providers/agentHost/electron-browser/agentHost.contribution.ts:13, so the cmd interface lives here. The path IAgentHostService -> WorkbenchAgentHostService (workbench-shell) -> LocalAgentHostServiceClient is collapsed into `local-agent-host-service-client.restart-agent-host`, which then calls the process manager. The IPC message is `vscode:restartAgentHost` via the electron-main starter, which belongs to main-process.
- **Process manager to host start.** `AgentHostProcessManager._start` drives `IAgentHostStarter` (electron-main, owned by main-process). I model it as a direct call to `agent-host-main.start`.
- **The connection tracker's shutdown check.** The real check is `protocolIngressDisposables.isDisposed`, which the management drain sets. I model it as the management service's `shutting_down` flag.
- **Simplifications in the MCP trust and launch path:**
  - the policy check uses the server id as the name
  - allow and deny lists are seeded in state, not taken from the policy settings
  - variable resolution, env expansion and the sandbox are one choice, `launch_resolution`
- **Command auto-approval.** It is tree-sitter based in code. I approximate it with prefix rules, and a `>` in the command counts as an unapproved redirect.

## 7. Where docs or common knowledge disagree with the code

- **MCP sampling defaults.** The `chat.mcp.serverSampling` schema documents `allowedDuringChat` default true. But `_getMatchingModelInner` (mcpSamplingService.ts:238-241) reads the inspected value, which is undefined for a server with no entry, and then prompts. So by default the first sampling request during a tool call prompts.
- **There is no `chat.agentHost.enabled` setting.** Agent host enablement is "desktop and not chat.disableAIFeatures" (AH/browser/agentHostEnablementService.ts:33).
- **Branch Chat.** Its run method always throws 'Branching chat sessions is not yet supported.' (branchChatSessionAction.ts:108).
- **The agent host does not back off between restarts.** Crash restarts happen immediately, up to 5 times, and then it gives up for good until an explicit restart (agentHostService.ts:206-248).
- **MCP initialize has no timeout.** A 5 s timer only logs (mcpServerRequestHandler.ts:106-109).
- **AGENTS.md (orientation only)** describes the multi-chat orchestrator as complete. The model keeps only the default chat.

## 8. Simulator gaps

- **A promise that never settles.** A non-quiet `McpServer.start` that ends in Error shows `showInteractiveError` and never resolves (mcpServer.ts:896-911). The model returns `{state: 'error'}`. As a result `McpServer.callOn` and tool calls fail with `mcp-connection-failed`. In the code they would hang behind the error dialog.
- **Config writes.** `chat.mcp.serverSampling` writes ("Always"/"Never", Configure Sampling Models) are mirrored in `mcp-sampling-service.state.server_sampling`, because config values are immutable during a run. `get-config` merges both.
- **Autostart is asynchronous.** It returns an observable and runs `Promise.all` asynchronously (mcpService.ts:81-162). The model runs the parallel start synchronously and returns the final result.
- **Gateway startup race.** `Promise.race(ensureServerReady, setTimeout(grace))` (mcpGatewayToolBrokerChannel.ts:110-134) is a call with `timeout_ms` from config and `on_error: continue`. The server start still completes late, as in the code.
- **Store lookups that miss.** A store `get` with `default: null` counts as not found, so the lookups that tolerate unknown keys use `default: {missing: true}` and test `has(x.missing)`.
- **Keyed state.** Static `set` paths prevent keyed updates. Session-keyed state uses store tables.
- **Sequencers.** McpServer's `_connectionSequencer`, AgentService's per-session creation sequencer and per-client dispatch queues are not modeled; `agent-service` has capacity 1. The sampling model sequencer is capacity 1 on `mcp-sampling-service`.
- **Startup phases.** Workbench contribution phases (BlockStartup, BlockRestore, AfterRestored, Eventually) are a fixed call order in `sessions-workbench.startup`. The real registry instantiates by phase on idle callbacks.

## 9. Known gaps

- **Untested branches.**
  - Workspace-trust branches of `mcp-registry.resolve-connection`, 4 of them: see §5.
  - `promptType: 'never'`: no modeled caller passes it.
  
  Behavior coverage is 99.1%, with these 5 if branches not run.
- **Four commands count as covered by proximity only.** The check tool counts them through its ±3 line tolerance next to cited lines:
  - `CLOSE_SESSION_COMMAND_ID`
  - `workbench.action.chat.debugAgentHostInDevTools`, `profileAgentHost` and `stopAgentHostProfile`
  
  None has a modeled handler, so they are also listed in skips/agents.json: "developer command" for the three agent host ones, "not modeled: chat close" for CLOSE_SESSION.
- **AgentHostContribution** (localAgentHost.contribution.ts:90) is covered the same way by proximity, with no modeled constructor. It is also listed in skips/agents.json.
- **Not modeled:**
  - Mark read and unread, chat tabs and groups, worktree management, changes view and changeset operations, agent merge, remote agent hosts (SSH, WSL, tunnel, dev container, Mission Control), automations and agent feedback. All of these are skipped.
  - In the agent host: peer chats, chat move and fork, checkpoints, changesets, the git and GitHub services, OTel and telemetry, the SDK downloader, BYOK and local models.
- **Over the scale targets.** The fragment has 188 scenarios and 63 flows, against the brief's rough targets of 25-60 and 6-14. Many flows are one-command flows that exist so the command's interface is reachable. Each has a single happy scenario.

## Reconciliation round

The generator now lives in `examples/vscode/gen/agents/` (decision 14). Run `build.sh` there. The inputs it reads are:
- the original builder parts;
- `recon.py`: owner contracts, fixtures, services and contributions;
- `recon_cmds.py`: commands and the methods they call;
- `recon_fix.py`: command ids, the registry seed and skips;
- `contribs.txt`: the Agents window contribution constructors.

### What changed

- **Stubs take the owner's contract (decisions 1, 7).**
  - Every boundary interface is now copied from the owning fragment at build time, with request, response, kind and errors, and schema refs inlined.
  - Stub components carry no `kind` or `parent`, so the owner's definition wins.
  - Shapes the owners don't define yet are guessed from my call sites:
    - `workbench-mcp-management-service.install` and `authentication-service.remove-session` (workbench-shell)
    - `opener-service.open` and `secret-storage-service.set`/`delete` (platform-core)
    - `automation-service.*` and `prompts-service.set-disabled-prompt-files` (chat)
- **Call sites aligned to those contracts.**
  - `language-models-service.send-chat-request` takes `{model_id, messages}` and returns `{started}`. `mcp-sampling-service.sample` now returns `{model, started}` (fixes the 8 merged failures).
  - Default sampling models come from `select-language-models`, and `allowedModels` is filtered to known models (mcpSamplingService.ts:245).
  - `request-workspace-trust` returns `{trusted}`.
  - `activate-by-event` sends `ExthostActivateByEventRequest`.
  - `chat-service.send-request` takes `{session_resource, message}`.
- **The quit veto follows decision 8.** `local-agent-host-lifecycle-contribution.on-before-shutdown` subscribes to `lifecycle-service.on-before-shutdown` and vetoes through `lifecycle-service.veto` with `veto.sessions.localAgentHost`.
- **Fixtures (decision 10).**
  - `agents-seed` registers every modeled agents command in `commands-registry` (decision 6), keyed by the command id and naming its `cmd-*` interface.
  - `agents-mcp-servers` extends one-window-folder with the github and workspace-db MCP servers. `mcp-server-runtime` now starts empty.
  - Every scenario lists `agents-seed`. MCP and sessions-startup scenarios also list `agents-mcp-servers`.
- **Services.**
  - Each owned service has an implementation component (kind `service`) citing its createDecorator line and its registration line.
  - Each is named in a startup flow's `steps`:
    - agent host services in `agents-agent-host-startup`, cited at agentHostServices.ts:102-183;
    - window services in `agents-sessions-window-startup`, cited at their registerSingleton line.
  - Thirteen of these services carry the methods the commands call:
    - agent feedback, session groups, chat background, get started, session tasks
    - remote, SSH, tunnel and WSL agent hosts, SSH host-key trust, location preference
    - changes view, session changes
- **Contributions.**
  - 126 Agents window contributions have a component and a `start` interface. Each cites the constructor and the registration line. `sessions-workbench.startup` calls all of them, through a `foreach` over a dynamic call with `targets`.
  - Contribution classes that chat owns (the AgentHost* classes and AgentHostSandboxNotifications, declared under src/vs/workbench/contrib/chat) are modeled differently. My `*-registration` components cite my registration lines and call chat's `<class>.constructor`.
  - My two settings contributions are `sessions-agent-host-settings-contribution` and `sessions-agent-session-settings-contribution`, because chat uses the plain ids for the workbench classes.
- **Commands.**
  - About 80 user-triggered commands now have behavior and are run by the multi-step scenarios `agents-commands-<group>`:
    - read state, chats, groups
    - welcome and background settings, run tasks
    - automations, feedback, AI customization files
    - changeset operations, GitHub links, Agent Merge
    - remote/SSH/WSL/tunnel connect
    - desktop window hand-offs
    - the MCP OAuth secret
  - New SessionsManagementService methods: send-request, mark-read/unread, mark-all-read, mark-chats-read, import-session, rename-chat, delete-chat, create-new-chat-in-session, fork-chat-in-session, create-and-send-new-chat-request.
  - New provider methods: read state, import, chat rename/delete, Agent Merge.
  - New SessionsService methods: close-session, close-chat, open-new-chat-in-session.
- **Skips (decisions 11, 12).** No skip says "not modeled" any more. The 203 skips are:

  | Count | Reason |
  |---|---|
  | 139 | UI toggle: focus, navigation, view mode, or opening a view, editor or picker |
  | 15 | not an entry point: run() is empty, the id anchors a picker or widget |
  | 19 | developer tooling |
  | 14 | internal underscore commands of the voice and review bridges |
  | 3 | not an entry point: the archive-actions registration loop, embedder commands, a menu id constant |
  | 13 | another area owns the implementation (7 chat, 6 workbench-shell) |

  None of the five entries that were both covered and skipped is in skips any more. `CLOSE_SESSION_COMMAND_ID` and AgentHostContribution are modeled now. The three agent host developer commands are no longer covered by proximity and are skipped as developer tooling.

### Gate (merged, my fragment)

- modeled 417/432 (97%), up from 69/367 (19%)
- 203/203 agents scenarios pass in the merged run
- 0 mocks
- citations ok
- hollow: 0 failing, 7 advisory

This is the full merged gate, run with `-f examples/vscode/worlds.yaml`.

### Remaining, with owners

- **Merge warning naming my fragment:** "component lifecycle-service / editor-service: kind service vs module (agents.yaml vs main-process.yaml)". My stubs declare no kind. The `module` comes from main-process's stubs, and waits on main-process applying decision 7.
- **Standalone (non-merged), 2 scenarios fail** because they depend on owner behavior that a stub can't supply:
  - `agents-mcp-reset-trust-prompts-again`: the workspace-trust answer
  - `agents-mcp-sampling-outside-chat-configured`: the known language-model ids
  
  Both pass merged.
- **Requests:**
  - **chat:** expose `chat-service.acquire-or-load-session` (baseAgentHostSessionsProvider.ts:7998). `start-new-local-session` stands in for it now.
  - **chat:** define the `automation-service` contract.
  - **chat:** register `workbench.action.chat.triggerSetup` in the commands registry. Sign In currently fails with command-not-found in the merged run.
  - **workbench-shell:** define the `workbench-mcp-management-service.install` and `authentication-service.remove-session` contracts.
  - **platform-core:** define the `opener-service.open` and `secret-storage-service` contracts.
- **Unexecuted branches (40):** most are refusal guards in the command behaviors that the group scenarios run only on their happy path: confirm-cancel, automations disabled per command, artifact-integrations per Agent Merge command, unknown-provider no-ops. Each guard family has one scenario that runs it:
  - `agents-commands-automations-disabled`
  - `agents-commands-agent-merge-artifacts-on`
  - `agents-commands-sync-unavailable`
  - `agents-commands-rename-chat-empty`
  - `agents-commands-mark-unread-unknown-provider`
  - `agents-commands-sign-out-cancelled`
- **Shallow depth.** Contribution constructors are modeled one level deep: a narrated decision, recorded in `ctx`. The commands' service methods record their effect in component state, not in the services' full logic.

## Fix round (after judging)

The fix round is folded into the generator: `gen/agents/build.sh` runs the builder, then `gen/agents/fix_round/apply.py` applies `fix_round/patches/*.yaml` in sorted order (ids unchanged). The rebuild was checked byte-identical to the fragment.

### Fixes

- **A3: MCP start lists and registers its tools** (judge chat-agents-remote.md §4).
  - `mcp-server-runtime.start` no longer sets `cache_state: live` by itself. Once the connection is Running it calls the new `mcp-server-runtime.populate-live-data` (`_populateLiveData`, mcpServer.ts:603-612, 1224-1260). That sends `mcp-server.tools-list` (tools/list, mcpServerRequestHandler.ts:510-511) unless the server lacks the tools capability, stores the tools with the live cache state (`_setServerTools`, mcpServer.ts:1178-1187), and publishes `mcp-server-runtime.on-did-change-tools`.
  - `mcp-language-model-tool-contribution.sync-tools` (`_syncTools`, mcpLanguageModelToolContribution.ts:106-173) subscribes. It skips disabled servers and app-only tools, and calls chat's `language-model-tools-service.register-tool` with `{tool_id: mcp_<label>_<name>, reference_name, source: mcp, server_id, has_impl, needs_confirmation}` (the contract agreed through the coordinator). `mcp-language-model-tool-contribution.start` now syncs every server at construction, so cached tools register before any server starts (the judge's correction, mcpServer.ts:452-482).
  - The external server's catalog is world data: `agents-mcp-servers` seeds `mcp-server.tools_by_server` (github: search_issues, create_issue; workspace-db: query).
  - The dispatch half (`invoke-tool` sending `source: mcp` tools to `mcp-tool-implementation.invoke`) is chat's.
- **Startup performance markers** (oracle agentHostBootstrap.test.ts:37).
  - `agent-host-startup-performance` holds `marks` (processStart pre-seeded) with `mark`, `start-operation` and `complete-operation` (agentHostStartupPerformance.ts:92-111, 231-297). A milestone is recorded once per provider, and an operation stops after a success or three attempts.
  - `agent-host-main.start` marks bootstrapStart, configuration, telemetry, services and bootstrap (agentHostBootstrap.ts:110-236), and when the configured WebSocket start settles calls the new `agent-service.mark-startup-complete` with `error` if it failed (agentHostMain.ts:537-542).
  - `agent-service.list-sessions` brackets the listing with sessionListStart/sessionList, marks firstSessionList once, and opens startupSettled when both host startup and the first listing happened (agentService.ts:1550-1564, 4970-5010). `agent-service` now has state for those three flags.
- **Chat pet achievements** (oracle chatPetAchievements.test.ts:17). The contribution's `start` unlocks agentsWindowOpened and starts listening (chatPetAchievements.ts:16-29). `sessions-management-service.send-new-chat-request` publishes `on-did-send-request` with the request's `attached_context` (sessionsManagementService.ts:875). The subscriber unlocks firstChatMessage, plus imageRequest when an entry has kind image.
- **Agents window title bar height** (oracle titlebarPart.test.ts:44). New `sessions-titlebar-part`: `get-minimum-height` returns 35 for `window.density.layout: compact` and 44 otherwise, raised by the WCO height and divided by the zoom factor when zoom is prevented; max == min (titlebarPart.ts:39, 58-70). It subscribes to configuration changes and re-lays out on a density change (122-129).
- **Sandbox toggle policy** (oracle agentHostSandboxToggle.test.ts:69). New `agent-host-sandbox-toggle` with `get-toggle-state` and `get-collapsed-state` (agentHostSandboxToggle.ts:34-57), flow `agents-sandbox-toggle`, 7 scenarios.
- **Thin behaviors.** About 70 Agents window contribution constructors and handlers that only set a `ctx` flag now model what the constructor does: the context keys they bind (`context-key-service.set-context`), the settings they read, the services they call and their early returns. Those that only register a widget, action view item or menu are left as they are (pure rendering).
- **Features.** `feature:agent-sessions` tags the sessions window startup, new session, send, title bar and sandbox flows. `feature:mcp` tags start-server, tool-invoke and sampling.
- **Stub alignment.** `chat-service.send-request` copies chat's new request shape (`attached_files` items are objects).

### Breaking changes

None of the interfaces I changed changed shape for callers in other areas:
- `mcp-server-runtime.start`, `mcp-language-model-tool-contribution.start` and `agent-service.list-sessions` keep their request and response.
- `sessions-management-service.send-new-chat-request` gains an optional `attached_context` input (default: one image attachment, so the default request carries an image, as the oracle drives it).

### Boundary stubs added

- `context-key-service.set-context`, `configuration-service.get-value`, `storage-service.get` (platform-core, copied from its fragment).
- The `language-model-tools-service.register-tool` and `chat-pet-service.unlock-achievement` stubs I added during the round were deleted once chat defined both interfaces with the agreed shapes. The `native-host-main-service.open-agents-window` stub was deleted too, because main-process now owns it and returns `{}`.
- Chunk configs: agents-owned `chat-agent-merge-{address-reviews,fix-ci,resolve-conflicts,merge-pull-request}`, `extensions-experimental-agents-window-management`, `chat-agent-sessions-appearance-tools-enabled`, `chat-agent-sessions-session-storage-cleanup-suggestion-enabled` and other session settings, and the constant `session-disk-space-initial-check-delay-ms`. Boundary copies: `chat-agent-host-cloud-sandbox-enabled`, `chat-remote-agent-hosts-enabled`, `chat-agent-enabled`, `chat-experimental-session-archive-action-wording`, `agents-voice-enabled` (chat); `environment-is-built`, `product-quality`; `workbench-experimental-modern-ui-editor-tab-style` (workbench-shell).
- Config `window-density-layout` (owner workbench-shell, workbench.contribution.ts:260-268; no fragment defines it yet).

### Still open

- `agent-host-main.create-agent-host-runtime` (agentHostBootstrap.ts:109-251) is createAgentHostRuntime alone: bootstrap marks, providers, contributions, and no markStartupComplete. Flow `agents-agent-host-runtime` runs it. `agent-host-main.start` calls it, and then calls its own markStartupComplete (agentHostMain.ts:537-542). `oracle-agents-bootstrap-renderer-byok-startup-markers` passes once its first step runs `agents-agent-host-runtime`. As written, it runs `agents-agent-host-startup`, so agentHostMain's `success` hostReady is recorded before the test's `error`. The oracle file isn't mine to change.
- The plugin discovery fix (agentPluginServiceImpl.ts) is chat's.
- `sync-tools` keeps its own `registered` map, so equal tool data isn't registered twice; chat's `register-tool` refuses duplicates. When a tool's data changes, the code disposes and re-registers it (mcpLanguageModelToolContribution.ts:162-170). Chat has no unregister interface, so that path isn't modeled.
- 63 entry-citing interfaces remain trivial (24.3%). They only register widgets, action view items, menus or registry entries, or their logic reads state that no modeled interface exposes (the window layout, the voice controller).
- **Simulator gap:** the external MCP server's catalog is keyed by server id in the server's state, because one external component stands for every server. In the code, each connection has its own server.

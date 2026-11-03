# Judge report: chat-agents-remote (A1–A4, R1–R4)

The model was judged on the merged document, `examples/vscode/vscode.json`, against the code in
`vscode-1.144.0`. The scenarios are in `judge/scenarios/{A1..A4,R1..R4}.yaml`, and every one starts
from `full-window`. Run them with:

```sh
go run ./internal/devtools/check -q -f examples/vscode/vscode.json \
  -f examples/vscode/judge/scenarios/A1.yaml ... -f examples/vscode/judge/scenarios/R4.yaml \
  --scenario '^bench' --no-mocks --trace
```

Result: 25 bench scenarios ran, 17 passed and 8 failed, with no mocks. All 8 failures are
deliberate probes, each marked "(probe)". They fail on purpose to show a missing path.

## 1. Cases

| ID | Verified expectation | Corrected? | Score | Root cause | Evidence |
|---|---|---|---|---|---|
| A1 | `chat.submit` → `ChatWidget.acceptInput` → `ChatService.sendRequest` (chatServiceImpl.ts:1540-1670). The agent is the detected one, else the `@`-mentioned `ChatRequestAgentPart`, else the default for the widget's mode (1648-1653, 2135). The widget's mode defaults to **Agent** (chatInputPart.ts:1205; chatWidget.ts:3562). Then: `activateByEvent('onChatParticipant:<id>')` (2138), MCP autostart when the model can use tools (2170-2176), `invokeAgent` (2182), `$invokeAgent` on the extension host. Progress chunks stream back through `$handleProgressChunk` (mainThreadChatAgents2.ts:481) into `model.acceptResponseProgress` (chatServiceImpl.ts:1862-1883). The language model call happens inside the participant (Copilot, built in at extensions/copilot). | Yes (mode-dependent default participant) | **partial** | model, world | `bench-a1-default-participant` passes: send-request, emit run-request, activation of `onChatParticipant:github.copilot.default`, `invoke-agent@eh1`, then the response is `success` and the session is freed. `bench-a1-at-mention-routes` fails: `@vscode` is still sent to `github.copilot.default`, because `chat-service.send-request` never parses mentions. `bench-a1-response-streams` fails: no progress and no LM call. `ext-host-chat-agents2.invoke-agent` is a stub. `send-request` hard-codes `mode: ask`, and chat-seed gives `github.copilot.default` the modes ask, edit and agent at all four locations. package.json says modes `['ask']` and location `['panel']`; `editsAgent` is the default for agent mode. MCP autostart isn't called from run-request. |
| A2 | `LanguageModelToolsService.invokeTool` appends the invocation part (languageModelToolsService.ts:651-658). When `prepareToolInvocation` returns `confirmationMessages` and nothing auto-confirms (1409-1435; `chat.tools.global.autoApprove` defaults to false, chat.shared.contribution.ts:832-833), it awaits `awaitConfirmation` (679-681). **Deny throws `CancellationError`** (684-686); it is not a refusal message. The Copilot tool loop turns it into the tool result "The user cancelled the tool call." (toolCalling.tsx:694-697). Skip returns a text result (687-695). Approve calls `impl.invoke` (741-745), which reaches `$invokeTool` on the extension host for extension tools. | Yes (the deny wording) | **pass** | — (minor model notes below) | All four scenarios pass. **Approve:** `begin` returns `waiting-for-confirmation`, then the `user_confirmation=allow` choice, then `ext-host-language-model-tools.invoke-tool@eh1` ×1, then the invocation is `completed`. **Deny:** error `canceled`, no extension host call, state `denied`. **The Accept command:** `confirm-with` on the waiting call, then invoke without a choice, which runs on eh1. **Control:** no wait for a tool that needs no confirmation. |
| A3 | Start runs `McpServer.start`, then `McpServerConnection.start`, then `initialize` (mcpServerRequestHandler.ts:102-155). `_populateLiveData` then sends **`tools/list`** (mcpServer.ts:608, 1224-1260; mcpServerRequestHandler.ts:510-511, refreshed on `tools/list_changed` at 374). `McpLanguageModelToolContribution._syncTools` registers each Model-visible tool with `registerTool` and `McpToolImplementation` (mcpLanguageModelToolContribution.ts:118-173). A model call goes through `invokeTool`, `McpToolImplementation.invoke` (265), `callOn` (which starts the server if needed, mcpServer.ts:360-380), then `tools/call` (1409; mcpServerRequestHandler.ts:517-518). **Correction:** tools are also registered from the cached tool list before the server starts (cacheState, mcpServer.ts:452-482). The server starts lazily on the first call or by autostart. | Yes | **partial** | model, contract | `bench-a3-start-server` passes: policy check, `onMcpCollection:` activation, `resolve-connection`, `initialize`, then running and live. `bench-a3-tool-call-goes-to-server` passes: `callOn` starts the server, and `mcp-server.tools-call` is called with `name=search_issues`. `bench-a3-tools-listed-and-registered` fails: there's no `tools/list`, the tools are static state in the `agents-mcp-servers` fixture, and `mcp-language-model-tool-contribution.start` only counts them without registering anything. `bench-a3-lm-tool-dispatches-to-mcp` fails: `language-model-tools-service.invoke-tool` dispatches only `source == 'extension'` tools. MCP and internal tools never reach an implementation, so the chat↔agents seam is broken. |
| A4 | `chat.cancel` (chatExecuteActions.ts:986-988) calls `cancelCurrentRequestForSession` (chatServiceImpl.ts:2613-2645). With nothing pending it is a logged no-op. Otherwise `CancellableRequest.cancel()` runs `toolsService.cancelToolCallsForRequest` and cancels the token (136-142), and the pending request is removed. The token listener calls `model.cancelRequest`, then `response.cancel()` (1987-2003; chatModel.ts:3726-3729). `progressCallback` drops later chunks (1863). The token also crosses the RPC boundary to the participant. | No (verified) | **partial** | model, simulator | `bench-a4-cancel-in-flight` passes with a seeded pending request: canceled, pending cleared, and the response reads back as `canceled` through `chat-view-model`. `bench-a4-cancel-nothing-pending` passes. `bench-a4-cancel-propagates` fails: there's no `cancelToolCallsForRequest`, and nothing reaches the extension host. `bench-a4-cancel-during-stream` fails: the cancel step can't start until the submit has finished (warning: started at 1650 ms, not 100 ms), so it is a no-op and the response stays `success`. |
| R1 | The management connection resolves the authority, opens the socket, and runs the auth, sign and connectionType handshake (remoteAgentConnection.ts:231-293, 390-404; remoteExtensionHostAgentServer.ts:300-391, 439-448). `RemoteExtensionHost` then connects the extension host (remoteExtensionHost.ts:130), and `ExtensionHostConnection.start` forks it (extensionHostConnection.ts:247-290). Nuance: an extension with extensionKind `workspace` runs remotely only if it is installed on the remote (extensionHostKind.ts:47-88; extensionManifestPropertiesService.ts:271). | Nuance only | **partial** | model, contract, world | `bench-r1-connect-and-ext-host` passes: the token lands on srv1, ConnectionGain fires, and the server starts the extension host connection. `bench-r1-workspace-extension-runs-remotely` fails: `extension-host-connection.start` only records exit info, so nothing is forked and no extension is placed by extensionKind. The renderer-side `RemoteExtensionHost` hop is absent. The world disagrees with itself: the `remote-folder` fixture uses `ssh-remote+devbox`, while the resolver seed uses `ssh-remote+dev-box`. |
| R2 | There's no fixed attempt count. Waits are 0, 5, 5, 10, 10, 10, 10, 10, then 30 s repeating, until the **3 h** grace expires (remoteAgentConnection.ts:660-744; ipc.net.ts:304). `VSCODE_CONNECTION_ERROR` or an unknown error gives up immediately. The progress dialog appears only after 40 s without data (remote.ts:785). "Reload Window" is shown once, and only when the failure wasn't handled (remote.ts:1004-1018). | Yes | **pass** | simulator (noted) | `bench-r2-backoff-then-reconnect` passes: waits of 5 and 5 s, 4 connects, and the server accepts the reconnection. `bench-r2-grace-expired-reload` passes with the grace set to 20 s through state: permanent failure, the reload dialog, then `reloadWindow`. `bench-r2-default-grace-keeps-trying` passes; it documents the 20-attempt cap. |
| R3 | **product.json has no `extensionsGallery`.** The gallery manifest stays Unavailable (extensionGalleryManifestService.ts:137-140), and install by id throws "No extension gallery service configured." (extensionGalleryService.ts:694-698, via extensionsWorkbenchService.ts:2659). Nothing is downloaded. With a Marketplace the path would be: download, verify the signature, extract, add to the profile, `onDidInstallExtensions`, then `handleDeltaExtensions` with no reload (abstractExtensionService.ts:182-197). | Yes | **pass** | contract (Marketplace variant only) | `bench-r3-oss-no-marketplace` passes with no gallery, channel or download calls. The counterfactual `bench-r3-marketplace-install` passes and calls things in the right order. `bench-r3-marketplace-install-no-reload` fails: nothing connects `onDidInstallExtensions` to `extension-service.handle-delta-extensions`, which is modeled but has no caller. |
| R4 | The defaults are `extensions.autoUpdate: 'on'` (on/off only; extensions.contribution.ts:139-148) and `autoCheckUpdates: true`. The check runs at startup and then every 12 h (extensionsWorkbenchService.ts:978, 2223-2231). With no gallery, `checkForUpdates` returns early (2036), **so nothing updates**. With a Marketplace there is also a 12 h delay after publish (1243-1265), and the update is skipped on metered connections or when consent is required. | Yes | **pass** | — | `bench-r4-oss-check-finds-nothing` passes: two checks, the second at 12 h or later, with no query and no update. The counterfactual `bench-r4-marketplace-auto-update` passes: the extension is updated at the first check through the `extensions` channel. The consent and metered checks aren't modeled (minor). |

Score totals: 4 pass (A2, R2, R3, R4) and 4 partial (A1, A3, A4, R1). No case scored fail,
missing or sim-gap.

## 2. Wrong claims found in the model

1. **`chat-service.send-request` ignores `@`-mentions and the chat mode.**
   - The model routes every request to `agent_id_silent` or else to the default agent. It passes
     `mode: ask` to `get-default-agent`.
   - The code routes to the mentioned agent (`ChatRequestAgentPart`, chatServiceImpl.ts:1652-1653,
     2135). The default it falls back to depends on the widget mode, which defaults to Agent
     (chatInputPart.ts:1205, chatServiceImpl.ts:1648).
2. **The chat-seed default participant is wrong.**
   - The seed declares `github.copilot.default` with modes `[ask, edit, agent]` at the locations
     panel, editor, terminal and notebook.
   - extensions/copilot/package.json gives it modes `['ask']` and location `['panel']`. There is a
     separate default participant per mode and location (`editsAgent` for agent, `terminal`,
     `notebook`, `editingSessionEditor`).
3. **`language-model-tools-service.invoke-tool` runs only extension tools.**
   - In the model, internal tools and MCP tools "complete" without any implementation running.
   - The code calls `currentTool.impl.invoke` for every tool (languageModelToolsService.ts:741-745).
     For MCP tools that implementation is `McpToolImplementation` (mcpLanguageModelToolContribution.ts:120).
4. **`mcp-server-runtime.start` and `mcp-language-model-tool-contribution.start` are incomplete.**
   - After `initialize` the model sets `cache_state: live` without `tools/list`.
   - The contribution only counts the seeded tools, and nothing registers them.
   - In the code: mcpServer.ts:1224-1260 and mcpLanguageModelToolContribution.ts:107-173.
5. **`chat-service.run-request` cites the wrong place for its cancellation check.**
   - The "Canceled before the agent ran" check cites chatServiceImpl.ts:2211-2212.
   - That code runs *after* `invokeAgent` returns (`token.isCancellationRequested && !rawResult`).
   - Cancellation during the run (`model.cancelRequest` at 1987-2003, or progress dropped at 1863)
     isn't modeled. The model also skips MCP autostart before the invocation (2170-2176).
6. **`chat-service.cancel-current-request-for-session` leaves out half of `CancellableRequest.cancel()`.**
   - The model omits `toolsService.cancelToolCallsForRequest` (chatServiceImpl.ts:136-142;
     languageModelToolsService.ts:1550).
7. **Remote (from the R fork):**
   - `remote-agent-connection.connect-remote-agent-management` retries only listed error codes.
     The code retries the initial connection on any error, up to 5 times
     (remoteAgentConnection.ts:440-457).
   - `extension-host-connection.start` is trivial. The code forks the extension host process
     (extensionHostConnection.ts:247-290).
   - `remote-extension-host-agent-server.handle-web-socket-connection` always checks auth. The code
     checks only when the token is Mandatory (line 308). It also shortens the grace for
     extension-host connections, not just management connections (386-389).
   - `node-extension-management-service.download-and-extract-gallery-extension` always accepts
     `not-signed`. The code refuses it when `shouldRequireRepositorySignatureFor` holds
     (extensionManagementService.ts:346-352).
8. **A sampled claim outside this group:**
   - `sessions-management-service.mark-all-read` says it is a no-op.
   - The cited sessionsManagementService.ts:1440-1442 calls `setSessionReadState` for each session.

A2 notes, not counted as failures:
- Whether a tool needs confirmation is a static `needs_confirmation` flag. In the code it comes from
  `prepareToolInvocation`'s `confirmationMessages`. The MCP version of that is modeled separately in
  `mcp-tool-implementation.prepare-tool-invocation` and verified at mcpLanguageModelToolContribution.ts:232-242.
- The participant's conversion of a denial into a "cancelled" tool result sits beyond the extension
  host stub.

**Citation check.** `--cite-sample 10 --seed 23`: all 10 resolve and match their claims. A claim
that lists many contributions cites only one of their lines; that's acceptable.

I also checked about 25 citations by hand on the A flows, and all match:
- chatServiceImpl.ts 1540-1543, 1569-1579, 1626-1629, 1643-1649, 2616-2642
- chatAgents.ts 549-555
- chatExecuteActions.ts 986-988
- chatToolActions.ts 103-105
- languageModelToolsService.ts 651-658, 679-695, 1409-1435
- mcpServer.ts 371-374, 1408-1416
- mcpServerRequestHandler.ts 102-155
- mcpLanguageModelToolContribution.ts 232-242

The R fork checked 12 more remote and extension-management citations, and all match.

**Entry points.** Every entry interface for these cases has real behavior: submit, cancel,
`invoke-tool`, `start-server`, `connect`, `on-socket-close`, `install`, `initialize-auto-update`.
The trivial ones are boundary stubs, and in two cases the code does much more than the stub:
- `ext-host-chat-agents2.invoke-agent` (the participant)
- `extension-host-connection.start` (forks a process)

## 3. Builder findings

| Finding | Verdict |
|---|---|
| chat: the default queue action is `steer` | **Confirmed** (chat.shared.contribution.ts:1956-1965) |
| chat: global auto-approve needs a one-time opt-in | **Confirmed** (languageModelToolsService.ts:1430-1435) |
| chat: awaiting confirmation and cancel-while-running are simulator gaps | **Confirmed** (by A2 and A4) |
| agents: MCP initialize has no timeout; a 5 s timer only logs | **Confirmed** (mcpServerRequestHandler.ts:106-109) |
| remote-server §7, every item | **Confirmed**: autoUpdate is on/off only; 12 h autoUpdateDelay; suspended on metered connections; an `extensions.allowed` refusal shows as IncompatibleTargetPlatform; no Marketplace in the deployed build; no reconnection attempt limit, only the grace; the server shortens the grace to 5 min (it also does this for extension-host connections, which the model leaves out) |

## 4. Simulator gaps

- **Concurrent user actions across steps (A4, A2).**
  - Steps never overlap, so a cancel can't race an in-flight request, and an Accept click can't
    resolve an invoke that is already waiting.
  - Both are worked around: a seeded `pending` state for cancel, and a choice or a pre-seeded
    `waiting-for-confirmation` for confirmation.
  - Missing feature: steps that overlap at `at_ms`, or an external event injected into a run that
    is waiting.
- **Unbounded retry loops (R2).**
  - The reconnection loop is capped at 20 attempts (about 390 s), so the 3 h grace is
    unreachable. With the deployed grace, the model stops retrying silently.
- **Timers that re-arm forever (R4).**
  - The 12 h update check is modeled as two passes. That's enough for this case.
- **Cancelling a scheduled timer (R2, server side).**
  - It is modeled by deleting the row.
- **Streaming (A1).**
  - Mosaic has no streamed partial responses. Progress chunks could still be modeled as `emit`s to
    a progress handler, so A1's streaming gap is a model gap, not a simulator one.

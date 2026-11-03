# Judge round 2: VS Code model after the fix round

This round re-scores the 12 cases that had a failing scenario after the fix round, plus E3. The
model is the merged fragments (`skeleton.yaml`, `fixtures.yaml`, `worlds.yaml`,
`fragments/*.yaml`), run with `/tmp/mcheck -q ... --scenario '^bench'`. The code is
`vscode-1.144.0`. No model file was edited.

**E3 did not pass at the start of this round.** Both of its scenarios failed (E3a: write at
30 087 ms, E3b: no Skip). So 27 of 40 cases passed in full at the start, not 28, and 13 cases had
a failing scenario.

The fix round changed two contracts on purpose (DESIGN §13.1 item 14):
- Document text lives in `text-model@w1` (value, version_id, alternative_version_id).
- A step without `at_ms` waits for the previous step's emits and timers.

## 1. Adaptations (harness drift)

Each adaptation changes only the call, the path, the timing or the world. None changes what a case
asserts. Every edited line in `judge/scenarios/*.yaml` carries a `round 2` comment.

| Case / scenario | What changed | Why (code) | Result |
|---|---|---|---|
| C2 `when-true`, `when-false-falls-through` | input `context: {activeEditorGroupEmptyAndMultipleGroups: …}` → `{activeEditorGroupEmpty: true\|false, multipleEditorGroups: true}` | closeGroup's when clause is `and(ActiveEditorGroupEmptyContext, MultipleEditorGroupsContext)` (editorCommands.ts:866; contextkeys.ts:100, 104). The combined key never existed. | 5/5 pass |
| C4 `restart-restores-dirty` | `state['text-file-models@w1']…value` → `state['text-model@w1']…value` | Contract item 14: text moved to the editor's text model | 3/3 pass |
| D2 `gap-error-notification` | entry step `raw-debug-session.shutdown` → `raw-debug-session.on-adapter-exit {code: 1}` | The code enters at debugAdapter.onExit (rawDebugSession.ts:100-107), which is now modeled. Only this entry carries the error, and the error is what selects the 200 ms disconnect (:602-606). | 200 ms disconnect now passes. The notify assertion still fails (see §2). |
| R1 `workspace-extension-runs-remotely` | entry `rs-remote-ext-host-connect` (server side) → `exthost-start` in `[full-window, remote-folder, remote-server-srv1]`, with the hosts seeded as stopped | Extension placement is done by the window's extension service (determineExtensionHostKinds, extensionHostKind.ts:47-88; nativeExtensionService.ts:585-589), not by the server | 2/2 pass. Trace: `remote-extension-host.start@w1` → `handle-web-socket-connection@srv1` → `extension-host-connection.start@srv1` (fork), with git, TS, markdown and js-debug on the remote host |
| T2 `reload-single-run` | reconnect step gets `at_ms: 30000` | Engine contract: without `at_ms` the step waited for the 60 s grace runner (ptyService.ts:810-816) | 4/4 pass. Attach at 34 s cancels the runners, `trigger-replay` → `local-pty.handle-replay`, and the shell is not shut down |
| X7 `extension-executes-save` | `text-file-models…version_id` → `text-model@w1…version_id` (compared with `saved_version_id`) | Contract item 14 | 2/2 pass (saved_version_id 2 == version_id 2) |
| X8 `untrusted-ts-not-activated` | an `exthost-start` step first, with the hosts seeded as stopped | The trust filter runs when extensions are resolved (abstractExtensionService.ts:525-533; extensionEnablementService.ts:494-495). full-untrusted pre-seeds a registry as if that step had already run unfiltered. | pass |
| X8 `untrusted-startup-no-git` | adds a step `workspace-trust-ux-handler.show-modal-on-start` | The banner comes from WorkspaceTrustUXHandler (workspace.contribution.ts:488-523 → updateWorkbenchIndicators 432-444), not from the extension host start. `startupPrompt` = never → `banner-part.show`. | pass |
| E3 `exthost-participant-hangs` | fault target `ext-host-save-participant.participate` → `ext-host-document-save-participant.participate-in-save`. The timeout trace assertion names that callee. | The 1750 ms timer (mainThreadSaveParticipant.ts:33-38) is `timeout_ms: 1750` on the renderer participant's call to the eh1 side (exthost.yaml:19866-19871). The old fault hung the timer's owner, so the bound never applied. The simulator records the timeout on the callee. | pass: timeout at 1764 ms, format still runs, write at 1838 ms |

## 2. Verdicts for the failing cases

| Case | Verdict | Evidence |
|---|---|---|
| **A1** | **(b) wrong expectation** | The widget's mode defaults to Agent (chatInputPart.ts:1205) and is passed as `modeInfo` (chatWidget.ts:3562). `getDefaultAgent(location, modeInfo.kind)` (chatServiceImpl.ts:1645) keeps only default agents whose modes include `agent` (chatAgents.ts:459-467). That agent is `github.copilot.editsAgent` (extensions/copilot/package.json:1437-1448, modes [agent], isDefault, when `chat.agent.enabled`, default true at chat.shared.contribution.ts:1539-1542). The model activates `onChatParticipant:github.copilot.editsAgent` and records `agent_id: github.copilot.editsAgent`. The scenario's `github.copilot.default` is wrong. The other two A1 scenarios pass. |
| **C2** | **(a) harness drift → pass** | See §1 |
| **C4** | **(a) harness drift → pass** | See §1 |
| **D1** | **(b) wrong expectation** | `bench-d1-f5-default-world` asserts the round-1 gap (`guess-debugger == 1`, name != Launch Program). The code selects the first launch.json configuration when nothing is selected (debugConfigurationManager.ts:477-481), so F5 starts "Launch Program". The model now does exactly that: `get-selected-configuration`, no guess, and session-1 is named "Launch Program". |
| **D2** | **(a) entry point, then (b) wrong expectation** | After the entry is adapted, the disconnect with `timeout_ms: 200` passes. The notification assertion is wrong. `stopAdapter` sets `debugAdapterStopped = true` once `da.stopSession()` resolves (rawDebugSession.ts:621-626), and `fireAdapterExitEvent` attaches `e.error` only `if (error && !this.debugAdapterStopped)` (:640). Stopping an adapter that has exited resolves: `$stopDASession` → `ExecutableDebugAdapter.stopSession`, which returns early or kills a dead pid (extHostDebugService.ts:721-736; node/debugAdapter.ts:344-361). So `debugService.ts:751-753` shows no error. A probe with a fault on `ext-host-debug-service.stop-da-session` does reach `notification-service.notify`, so the model follows the code's branch. |
| **R1** | **(a) harness drift → pass** | See §1. One caveat: the model sends every extension that has code from the local registry snapshot to the remote host. The code uses the remote scanner's list (round-1 nuance), so the path is simplified. |
| **R2** | **(b) wrong expectation** | `bench-r2-default-grace-keeps-trying` asserts the round-1 20-attempt cap (21 connects, no ConnectionGain). The code loops until the 3 h grace (remoteAgentConnection.ts:660-744; ipc.net.ts:304). With failures on connects 2-30, about 11.5 min of waits, connect 31 succeeds. The model makes 31 connects and ends at `connection-gain` with `attempts: 30` and no permanent failure. |
| **T2** | **(a) timing → pass** | See §1 |
| **T3** | **(b) wrong expectation** | (1) The restarted pty host is a new process with a new `PtyService`, whose `_lastPtyId` starts at 0 (ptyService.ts:122, 337). The relaunched shell therefore gets id 1 again, so `!('1' in ptys) \|\| size > 1` cannot hold. The model's pty 1 after the restart is the new one (`interaction: None`). (2) `_connectToDirectProxy` is *invoked* 3 times: by the first createProcess (localTerminalBackend.ts:216), by onPtyHostRestart (:104-108), and by the relaunch's createProcess (:216), which returns early on the pending connection (:116-118). The model calls it 3 times and models that early return. The other assertions pass (2 createProcess, 2 spawns, 1 instance). |
| **X1** | **(c) model bug** (owner **workbench-shell**, with **editor**) | Opening `main.ts` now resolves the text model (`text-file-models.resolve`, `text-model.get-value`) but never requests language features. In the code, TextModel creation calls `languageService.requestRichLanguageFeatures(languageId)` (editor/common/model/textModel.ts:406; editor/common/services/languageService.ts:140). WorkbenchLanguageService's listener then calls `activateByEvent('onLanguage:<id>')` and `activateByEvent('onLanguage')` (workbench/services/language/common/languageService.ts:287-291). The model has no such hop (no `onLanguage:` activation outside the extension host's own scenarios), so TS is not activated when a .ts file is opened. The seam scenario passes. |
| **X7** | **(a) harness drift → pass** | See §1 |
| **X8** | **(a) harness drift → pass** (both scenarios) | See §1. The trace shows `Disabled extensions are never registered`, a registry with only markdown (`limited`), TS activating nothing, and the restricted-mode banner shown. |
| **E3** | E3a **(a) → pass**; E3b **(c) model bug** (owner **files-search-scm**) → case **partial** | E3a now exercises the 1750 ms budget: the `timeout` event on `ext-host-document-save-participant.participate-in-save` at 1764 ms, and the write at 1838 ms (below 2500). The agents' claim is confirmed, with one precision: the bound is `timeout_ms: 1750` in exthost's `ext-host-save-participant.participate` around its call to `participate-in-save` (exthost.yaml:19866-19871), mirroring mainThreadSaveParticipant.ts:33-38. E3b: `text-file-save-participant.participate` has no cancellable "Skip" progress (`withProgress({cancellable: 'Skip', delay: dirty ? 5000 : 3000}, …, () => cts.cancel())`) and no race against `cts.token`, which would end the loop (textFileSaveParticipant.ts:47-82). A hung formatter holds the save until the simulator's 30 s default. The outcome is right (the unformatted file is saved and the save does not fail), but the path is wrong. |

## 3. Scorecard (40 cases)

- **pass** (scenarios reproduce the verified outcome and path):
  - Passing at the start of the round: A2 A3 A4 C1 C3 C5 C6 C7 E1 E2 E4 E5 E6 E7 E8 E9 R3 R4 S1 S2 T1 X2 X3 X4 X5 X6 X9.
  - Passing after harness adaptation: C2 C4 R1 T2 X7 X8.
- **wrong-expectation**: the model matches the code, and the scenario's assertion is wrong and is left unchanged.
- **model-bug**: the model's outcome differs from the code.
- **partial**: the outcome is right, but part of the path is not modeled.

| Score | Count | Cases |
|---|---|---|
| pass | 33 | 27 that passed at the start of the round, plus 6 after adaptation |
| wrong-expectation | 5 | A1, D1, D2, R2, T3 |
| model-bug | 1 | X1 (workbench-shell/editor: no requestRichLanguageFeatures → `onLanguage:` activation on open) |
| partial | 1 | E3 (files-search-scm: no Skip progress or token race in TextFileSaveParticipant) |
| **total** | **40** | |

If the 5 wrong-expectation cases are counted as passes (the model is right), the model is correct
on 38 of 40 cases. Two model fixes remain open: X1 and E3b.

The "pass" cases that passed at the start of the round were not re-verified path by path in this
round. Their round-1 notes still apply.

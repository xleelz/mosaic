# Oracle round 2: VS Code model after the fix round

All four groups were run against the merged fragments (skeleton, fixtures, worlds and fragments/*.yaml, plus oracle/<group>.yaml) with `--no-mocks`.
The scenarios are in oracle/<group>.yaml and the verdicts in oracle/<group>.json.

Causes: **fixed** (the model now agrees, and the round-1 scenario passes unchanged), **drift** (only calls, paths, world or timing were adapted), **mistranslation** (the scenario was corrected to match the test), **new** (a test with no round-1 scenario, translated now), **model-bug**.

| # | Test | Round 1 | Round 2 | Cause |
|---|---|---|---|---|
| 1 | agentHost/test/node/agentHostBootstrap.test.ts:37 | model-bug | **model-bug (agents)** | mistranslation + model-bug: see below |
| 2 | sessions/contrib/chat/test/browser/chatPetAchievements.test.ts:17 | model-bug | pass | fixed |
| 3 | sessions/test/browser/titlebarPart.test.ts:44 | model-bug (no scenario) | pass | new: 44 default and 35 compact (titlebarPart.ts:58-70); two scenarios, one per density |
| 4 | agentHost/test/browser/agentHostSandboxToggle.test.ts:69 | model-bug (no scenario) | pass | new: all 10 state cases plus the collapsed state (agentHostSandboxToggle.ts:34-57) |
| 5 | chat/test/common/plugins/agentPluginFormatDetection.test.ts:138 | model-bug (no scenario) | pass | new: plugins are unresolved before the first refresh. Caveat: the model's start schedules a 0 ms refresh that the test's subclass doesn't, so the scenario reads with `await: false` before it runs |
| 6 | extensions/test/common/runtimeExtensionsInput.test.ts:13 | model-bug (no scenario) | pass | new: readonly, singleton, requires-modal (runtimeExtensionsInput.ts:24-35) |
| 7 | server/test/node/serverConnectionToken.test.ts:26 | model-bug | pass | fixed |
| 8 | allowedExtensionsService.test.ts:29 | pass | pass | — |
| 9 | allowedExtensionsService.test.ts:34 | model-bug | pass | fixed (object-valued extensions.allowed) |
| 10 | allowedExtensionsService.test.ts:40 | model-bug | pass | fixed |
| 11 | windows/test/electron-main/agentsWindow.test.ts:33 | model-bug | pass | fixed |
| 12 | onboarding/test/electron-main/onboardingTryoutHandoff.test.ts:42 | model-bug (no scenario) | pass | new: one openAgentsWindow, focus, and vscode:runOnboardingTryout to the new window; complete resolves 'accepted'. The same-file case at :86 also passes |
| 13 | environment/test/electron-main/environmentMainService.test.ts:13 | model-bug (no scenario) | pass | new: unset/restore of snap-exported variables (environmentMainService.ts:75-108). The not-Linux case and :60 also pass |
| 14 | policies/test/browser/accountPolicyService.test.ts:267 (case at :269) | model-bug | pass | mistranslation: the scenario read a config key and expected a policy-service call; the code reads policy only on change. Rewritten to the test's acts (lines 238-266): refresh with policyData `{}` (the provider's default, line 58), then getPolicyValue is null for every policy and the policy model is empty |
| 15 | configurationResolverService.test.ts:95 | model-bug (no scenario) | pass | new: `${workspaceFolder}` resolves (variableResolver.ts:149-164). The cases at :147 and :155 also pass |
| 16 | editor/test/common/services/modelService.test.ts:50 | model-bug | pass | mistranslation: the scenario never set the test's files.eol (lines 36-37). Now the user value is `\n`, and /myroot is a workspace folder whose settings give `\r\n` |
| 17 | editor/test/browser/view/viewController.test.ts:118 | model-bug | pass | drift: drives `view-controller.dispatch-mouse` (the test's dispatchMouse, lines 94-108), not `_wordSelect`, which can't select a bracket block |
| 18 | search/test/node/textSearchManager.test.ts:16 | model-bug | pass | drift: drives `text-search-manager.search` directly, as the test builds NativeTextSearchManager; the provider gets `windows-1252` |
| 19 | textFileService.io.test.ts:56 | pass | pass | — |
| 20 | textFileService.io.test.ts:66 | model-bug | pass | fixed |
| 21 | files/test/browser/editorAutoSave.test.ts:75 | pass | pass | drift: the text moved to `state['text-model@w1'].models[uri].value` |
| 22 | browserView/.../browserNavigationFeatures.test.ts:25 | model-bug | pass | fixed |
| 23 | notebook/test/browser/notebookKernelSource.test.ts:59 (case at :60) | model-bug (no scenario) | pass | new: the cached actions keep their first context; closing through notebook-service drops the cache; reopening gives [false, true] |
| 24 | notebook/test/browser/cellOperations.test.ts:20 | pass | pass | — |
| 25 | notebook/.../outputCopyTests.test.ts:48 | pass | pass | — |
| 26 | notebook/.../outputCopyTests.test.ts:61 | model-bug | pass | fixed |
| 27 | api/test/browser/extHostDebugVisualization.test.ts:60 | model-bug (no scenario) | pass | new: after dispose, $provideDebugVisualizers returns [] (extHostDebugService.ts:364-366, 408-411); the reregister case at :72 also passes |
| 28 | api/test/browser/mainThreadEditorTabs.test.ts:33 | model-bug (no scenario) | pass | new: a modal label change doesn't rebuild the tabs model; the next open rebuilds it once (mainThreadEditorTabs.ts:276-298) |
| 29 | api/test/browser/extHostApiCommands.test.ts:232 | model-bug | pass | fixed (validation in the ext host; no RPC) |
| 30 | api/test/browser/extHostApiCommands.test.ts:274 | model-bug | pass | fixed |
| 31 | github-authentication/src/test/github.test.ts:36 | model-bug (no scenario) | **model-bug (builtin-extensions)** | new: see below |
| 32 | chatAgentTools/test/browser/outputMonitor.test.ts:58 | model-bug (no scenario) | pass | new: Idle with the latest output, Cancelled on a cancelled token (plus :75, :83). Not asserted: the model also counts output-length changes as new data, while the code only uses onData (outputMonitor.ts:525-530) |
| 33 | chatAgentTools/test/browser/terminalOutputCache.test.ts:17 | model-bug (no scenario) | pass | new: record then lookup returns 'clean', entries are keyed by cwd, fast entries expire (terminalOutputCache.ts:190-238) |

Paths are shortened. The full paths are in the group .json files.

## Totals

- Translatable tests: 33. Untranslatable: 12, unchanged; smart-select keeps its scenario but stays untranslatable.
- Round 1: 5 pass, 28 model-bug (13 of those had no scenario).
- Round 2: **31 pass, 2 model-bug**, with 0 sim-gaps and 0 test-mismatches. All 33 now have scenarios.
- Of the 6 failing scenarios the area agents reported:
  - 3 were drift: double-click, text search, autosave.
  - 2 were mistranslations: account policy and EOL. Byok was also mistranslated.
  - 1 is a model bug: byok.

## Remaining model bugs

### agents: `agentHostBootstrap.test.ts:37` (byok startup markers)

The test calls `createAgentHostRuntime(...)` (agentHostBootstrap.ts:109-251) and never runs agentHostMain. Then it calls `runtime.agentService.markStartupComplete('error')` itself (test line 69), and it expects `['hostReady', 'processStart', 'error']` (line 91).

The model has no entry for `createAgentHostRuntime` on its own. The flow `agents-agent-host-startup` (`agent-host-main.start`) runs the bootstrap marks and also agentHostMain's own `markStartupComplete(startupOutcome)` (agentHostMain.ts:537-542). That marks hostReady as 'success', so the test's later `agent-service.mark-startup-complete {outcome: error}` returns "Already complete".

The agents area's explanation ("the WebSocket start succeeds") is accurate about the model, but the test never starts a WebSocket server.

**Fix:** model a `createAgentHostRuntime`-only interface. It should emit processStart through bootstrap and contain no markStartupComplete. `agent-host-main.start` then calls it and does its own markStartupComplete afterwards. The scenario then drives the new interface, then `agent-service.mark-startup-complete {outcome: error}`, then `list-sessions`.

Reordering so that the test's 'error' call lands before agentHostMain's own call is not the fix. The test never runs agentHostMain.

### builtin-extensions: `github.test.ts:36` (readSessions hydration)

The test asserts that the hydrated `account.icon` is the avatar URL (test line 93). The code takes it from `userInfo.avatarUrl` (github.ts:758-760, gitHubAccount.ts:49).

In the model, `github-server.get-user-info` drops `avatar_url`, and `github-session-engine.read-sessions` never sets `icon`.

The test's other checks pass:
- one GET /user
- no store-sessions or keychain write-back
- the fallback authorization server

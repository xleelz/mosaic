# builtin-extensions: notes

Fragment: `fragments/builtin-extensions.yaml` (45 components, 610 interfaces, 51 flows, 145 scenarios),
skips `skips/builtin-extensions.json` (5 entries). Snapshot: vscode 1.144.0 at `2c33b50b16`.

The generator and its hand-written parts live in `examples/vscode/gen/builtin-extensions/`:
`gen.py`, `common.yaml`, `deep_git.yaml`, `deep_ts.yaml`, `deep_md.yaml`, `scenarios.yaml`, plus
`gather.py` (inventory titles and registration sites) and `analyze_git.py` (git command bodies). It
reads `fragments/exthost.yaml` to copy the vscode-api contracts.

Standalone check, reconciliation round: 0 validation errors, 0 warnings; 145/145 scenarios pass;
0 mocks; hollow lint clean; behavior coverage 93.9%; citations all ok.

Merged gate: modeled 394/552 (71%), up from 39/552 (7%). No merge warning or hollow finding names
this fragment. 38 of my scenarios still fail in the merged run, all on other areas' state (see
Reconciliation below).

## 1. Entry points

| Inventory kind | Count | Covered by |
|---|---|---|
| activation-event (git, 4) | 4 | `git-extension.activate` cites `extensions/git/package.json:51-56`; flows `git-activate`, `builtin-extension-activate` |
| activation-event (typescript-language-features, 12) | 12 | `typescript-extension.activate` cites `package.json:58-71`; flow `typescript-activate` |
| activation-event (markdown-language-features, 8) | 8 | `markdown-extension.activate` cites `package.json:28-37`; flow `markdown-activate` |
| activation-event (24 other extensions, 50) | 50 | `<ext>-extension.activate` cites the extension's activationEvents range and its activate() line. It has a behavior (registers the extension's commands) and is the entry of flow `<ext>-activate`. |
| extension-command git (183) | 183 | 180 `git-command-center.cmd-*`, reached through `git-command-center.run-command` (flow `git-command`); 3 `git-extension.cmd-git-api-*` (registerAPICommands). Deep: refresh, stage, stageAll, commit, api.getRepositories, api.getRepositoryState |
| extension-command typescript-language-features (15) | 15 | `typescript-command-manager.cmd-*`. Deep: restartTsServer, reloadProjects (ts/js), plus the API-only tsserverRequest |
| extension-command markdown-language-features (64) | 64 | 16 on `markdown-command-manager` (deep: showPreview, showPreviewToSide, showLockedPreviewToSide, showSource, preview.refresh, preview.toggleLock, plus the API-only api.render and api.reloadPlugins); 48 on `markdown-editor-provider` (46 `$generated` markdown.editor.* commands plus rename and triggerSuggest) |
| extension-command, other extensions (221) | 216 | `<ext>-extension.cmd-*` cite the package.json line and the registration line, and are reached through that component's own `execute-registered-command` (flow `<ext>-commands`). emmet, references-view, github, npm and debug-auto-launch have handler behaviors (emmet's include validate()). Copilot and the rest stay registration-only. |
| skipped | 5 | see below |

Skipped (also in `skips/builtin-extensions.json`):
- `notebook.cellOutput.copy`, `notebook.cellOutput.openInTextEditor`, `notebook.cellOutput.addToChat`
  (ipynb): ipynb only contributes them in package.json for its menus. The handlers are registered
  by the workbench notebook contribution (`src/vs/workbench/contrib/notebook/browser/controller/cellOutputActions.ts:26,148`,
  `.../chat/notebook.chat.contribution.ts:316`), which belongs to notebook-webview.
- `github.copilot.debug.generateInlineEditTests`, `github.copilot.chat.clearTemporalContext`
  (copilot): they are contributed in package.json, but nothing under `extensions/copilot` registers
  them (a grep of the whole extension finds only package.json). They are dead contributions.

Command-level stubs have no behavior. Their summary is the command title (resolved from
package.nls.json) and they cite the contribution line. They are reachable through the dispatchers,
so each covers its inventory line.

## 2. Components

Git (`extensions/git/src`):
- `git-extension`: main.ts:192-264, which covers activate, _activate, createModel and warnAboutMissingGit (159-190).
- `git`: the Git class and findGit (git.ts:395, 167-189), exec/_exec (603-680), getGitErrorCode (337-375).
- `git-base-repository`: the git.ts Repository, imported as BaseRepository (git.ts:1400): getStatus 2830-2925,
  add 2011-2027, commit plus handleCommitError 2118-2224, getHEADRef 2929, getRefs 3033.
- `git-model`: Model (model.ts:186): constructor and doInitialScan 289-358, openRepository 599-705,
  pickRepository 898-927, getRepository 929.
- `git-repository`: the repository.ts Repository (713). Covers status/refresh 1175-1183, add 1278, commit
  1437-1490, run 2863-2903, retryRun 2987-3006, updateModelState 3028-3088, getStatus grouping 3110-3253,
  onFileChange, debounce and throttle 3339-3388.
- `git-decoration-provider`: subscriber of onDidRunGitStatus (decorationProvider.ts:131-150).
- `git-command-center`: CommandCenter (commands.ts:785). createCommand 5527-5690 is `run-command` and
  `show-error-notification`. Also stage 1522, stageAll 1583, smartCommit/commitWithAnyInput/commit 2374-2617, refresh 808.

TypeScript (`extensions/typescript-language-features/src`):
- `typescript-extension` (extension.ts:32-110), `lazy-client-host` (lazyClientHost.ts:23-100),
  `typescript-service-client-host` (typeScriptServiceClientHost.ts:51-186),
  `typescript-service-client` (typescriptServiceClient.ts: restart 322, ensure 377, startService
  384-539, serviceExited 647-773, execute 875-956), `typescript-server-spawner` (tsServer/spawner.ts:38-121),
  `typescript-command-manager` (commands/commandManager.ts:14-41).

Markdown (`extensions/markdown-language-features/src`):
- `markdown-extension` (extension.ts:15-27, extension.shared.ts:28-82), `md-language-client`
  (client/client.ts:68-184), `markdown-command-manager` (commandManager.ts, commands/index.ts),
  `markdown-preview-manager` (preview/previewManager.ts: openDynamicPreview 142-158, refresh 124,
  toggleLock 177, store matching 45-53 and preview.ts:890-904), `markdown-it-engine` (markdownEngine.ts:100-230),
  `markdown-editor-provider` (preview/markdownEditorProvider.ts:254, executeCommand 762-769).

Command level: one `<ext>-extension` component for each of 24 other extensions (copilot is
`copilot-chat-extension`). Each has an `activate` stub and its `cmd-*` stubs.

Routers (decision 6: internal dispatch only). Each component that registers commands has
`execute-registered-command`, which looks up its own registrations (state `registrations`, id to
interface). git-command-center keeps `run-command`, createCommand's wrapper. The seam stays
platform-core's `command-service.execute-command`: `builtin-extensions-seed` seeds
`commands-registry.commands` with all 323 modeled commands. The earlier stand-ins,
`builtin-extension-entry-points` and `builtin-extension-command-index`, are deleted (decision 3).

Externals I own (from the skeleton):
- `git-binary.exec`: one git process. It simulates the repository: rev-parse, status, add, commit,
  config, symbolic-ref/for-each-ref, index.lock contention and missing user config.
- `language-server.start/request/kill`: tsserver processes and the Markdown server worker.

## 3. Boundary stubs

`vscode-api` (component and every interface I call): copied from `fragments/exthost.yaml` at
generation time, with kind, request, response and errors unchanged (decision 4). Call sites fill
exthost's parameters:
- `command` and `rest` for commands-execute-command;
- `command`, `callback` and `extension_id` for commands-register-command;
- `message`, `items`, `options.modal` and `extension_id` for the show-message functions;
- the vscode.d.ts parameter names (`glob_pattern`, `view_type`, `show_options` ...) for the rest.

Four functions exthost doesn't define stay as my stubs, owner exthost, kind function:
workspace-workspace-folders, workspace-text-documents, workspace-request-resource-trust and
workspace-configuration-update. `commands-registry` is a boundary stub, owner platform-core. The
config copy `url-protocol` is a boundary copy, owner platform-core.


## 4. Config

All extension settings come from each extension's `contributes.configuration` in package.json, not
from registerConfiguration. product.json has no `configurationDefaults`, so the deployed value
equals the package.json default for every setting below. Sources cite the default line and the
line that reads it.

| id | key | value = default | read at |
|---|---|---|---|
| git-enabled | git.enabled | true | main.ts:209-210, model.ts:608 |
| git-autorefresh | git.autorefresh | true | repository.ts:3341 |
| git-status-limit | git.statusLimit | 10000 | repository.ts:3120 |
| git-untracked-changes | git.untrackedChanges | mixed | repository.ts:3117 |
| git-enable-smart-commit | git.enableSmartCommit | false | commands.ts:2387 |
| git-suggest-smart-commit | git.suggestSmartCommit | true | commands.ts:2428 |
| git-smart-commit-changes | git.smartCommitChanges | all | commands.ts:2477 |
| git-use-editor-as-commit-input | git.useEditorAsCommitInput | **true** | commands.ts:2468 |
| git-require-git-user-config | git.requireGitUserConfig | true | repository.ts:1472-1475 |
| git-optimistic-update | git.optimisticUpdate | true | repository.ts:3483-3486 |
| git-auto-repository-detection | git.autoRepositoryDetection | true | model.ts:318 |
| git-open-repository-in-parent-folders | git.openRepositoryInParentFolders | prompt | model.ts:632 |
| git-ignore-missing-git-warning | git.ignoreMissingGitWarning | false | main.ts:160-161 |
| js-ts-experimental-use-tsgo | js/ts.experimental.useTsgo | false | extension.ts:62-64 |
| git-allow-no-verify-commit | git.allowNoVerifyCommit | false | commands.ts:2508 |
| js-ts-tsserver-log | js/ts.tsserver.log | off | typescriptServiceClient.ts:552 |
| js-ts-tsserver-use-syntax-server | js/ts.tsserver.useSyntaxServer | auto | configuration.ts:243-250 |
| url-protocol (boundary, platform-core) | product.json urlProtocol | **code-oss** (deployed; no code default) | typescriptServiceClient.ts:707 |

The deployed value and the code default differ only for `url-protocol`: the OSS build ships
`code-oss`, while Stable ships `vscode`. This changes TypeScript crash handling (§7). I read no
shared config from fixtures.yaml.

Code constants modeled as literals, with their source cited:
- the @debounce(1000) on file changes (repository.ts:3361);
- the 5000 ms throttle hold (3370);
- the retry limits: 11 attempts and 50·n² ms back-off (2995-3002);
- the TypeScript crash windows: 5 restarts, 10 s and 5 min (typescriptServiceClient.ts:670-695).

## 5. Fixtures

Defined here: `builtin-extensions-seed` (the commands-registry entries for the modeled commands).

`git-binary.exec` reads the base-workspace seed `git-binary.repositories['/work/app']` (head, user,
staged, changes) and flattens it into its own fields; scenario-set fields win. The language server
still defaults its own empty state.

Request: the shared `ext-host-extension-service` state needs the `registry` its behaviors read
(exthost).

## 6. Unsettled points and assumptions

- **Generic git command handlers.** analyze_git.py reads each @command method and maps its
  first Repository, Model, window and commands.executeCommand calls to steps:
  - Repository methods become `git-repository.operation`: read-only queries run git directly,
    the others go through run() and refresh the model state.
  - The commitX variants become `commit-with-any-input` with their options.

  This is a summary of each handler, not every branch.
- **The git command map.** Every git id maps to `git-command-center.run-command` (createCommand's
  closure), which then dispatches by slug to `cmd-<slug>`. That matches
  `commands.registerCommand(commandId, createCommand(...))`.
- **One repository.** Model state is a list of roots. `git-repository` holds one repository's state
  (the fixture has one repo); a second repository would share it.
- **Simplified checks.**
  - The parent-folder check is "the root does not start with the folder path".
  - Scanning subfolders (traverseWorkspaceFolder) is narrated, not modeled.
  - The first `getRepositoryExact(repoPath)` check is folded into the root check.
- **git status.** Status is derived from `git-binary` lists (staged, modified, untracked,
  conflicted) rather than from comparing disk with HEAD. Disk edits by other areas do not change
  git status; only `git-binary` state does.
- **smartCommit simplifications.**
  - The unsaved-files prompt is a `choice` (`unsaved_files`), because workspace.textDocuments'
    dirty state is exthost's mirror.
  - The input-box answer is a choice (`message_input`).
  - Branch protection (branchProtectionPrompt), noVerify, commit signing and the "tracked and all
    untracked" no-change clause (commands.ts:2486) are not modeled.
- **Stage without arguments.** git.stage without arguments returns nothing staged. The real code
  falls back to the active editor's resource (getSCMResource).
- **TypeScript plugins.** No TS plugins are installed, so crash prompts use the no-plugins branch.
  extensions.getExtension is assumed to report no TS native preview extension.
- **workspace.textDocuments at activation.** The stub returns one open TS document, because
  `onLanguage:typescript` implies one.

## 7. Where common knowledge disagrees with the code

- **Committing with an empty SCM box.** Many people expect "Commit" with an empty message box to
  prompt for a message. With the default `git.useEditorAsCommitInput: true`, smartCommit sets
  `opts.useEditor` and runs `git commit` without `--file`, so git opens COMMIT_EDITMSG through VS
  Code's git editor (commands.ts:2468-2473, git.ts:2139-2149). The input box appears only when the
  setting is false (scenarios `...-commit-editor-message` and `...-commit-input-box`).
- **The "5 crashes" limit in the OSS build.** On `code-oss` and `vscode-insiders`, serviceExited
  resets `numberRestarts` to 0 after every crash and prompts each time
  (typescriptServiceClient.ts:707-718). The 5-crash limit, "will not be restarted", is therefore
  unreachable in this build; it applies only with `urlProtocol: vscode`. Scenarios
  `...-stable-five-crashes-fatal` and `...-stable-five-crashes-in-minutes` override `url-protocol`.
- **Git command errors.** createCommand catches them and shows a notification. The command promise
  resolves, so callers of `executeCommand('git.*')` never see the git error (commands.ts:5561-5686).
- **Opening a repository's status.** The first status after openRepository is not awaited; it is
  queued through a Limiter(5) (model.ts:697-700).

## 8. Simulator gaps

- **Quadratic back-off.** retryRun waits `attempt² × 50` ms (repository.ts:3002). mosaic back-off is
  geometric, so it is approximated with 50 ms × 4ⁿ⁻¹, capped at 5000. The first two waits (50 ms,
  200 ms) match.
- **@throttle.** It queues one follow-up call while a call runs. It is modeled as a flag that drops
  the call (`update_in_flight`), so the queued re-run is lost.
- **@debounce.** It is modeled as a recorded timestamp plus a delayed emit. A scenario can't
  overlap two file events inside one debounce window, because multi-step steps wait for the earlier
  timers. "Superseded" is therefore driven by calling the debounced interface directly.
- **Cancellation of an in-flight updateModelState.** A newer update cancels the older one
  (repository.ts:3029) and the CancellationError is swallowed. Calls are sequential, so this race
  isn't expressed.
- **whenIdleAndFocused.** It awaits events (onDidRunOperation, a window focus change). It is modeled
  as a choice, and the unfocused option just records `waiting_for_focus`.
- **Lazy activation.** onDidOpenTextDocument subscription (lazyClientHost.ts:82-86) can't be
  subscribed to across areas without an exthost topic. `maybe-activate` is a flow entry instead.

## 9. Known gaps

Unexecuted branches (7 steps), all explained:
- The rethrow in `git-base-repository.commit` (git.ts:2223) and git-binary's "nothing to commit"
  can't be reached. smartCommit always prompts before committing with nothing staged, unless
  `--allow-empty` is used.
- The disabled check in `git-model.open-repository` can't be reached: with git.enabled off, activate
  returns before any repository opens. The per-folder (resource-scoped) setting is not modeled.
- The "root already open" check in open-repository can't be reached: the workspace folder is the
  root itself.
- The "untrusted" branch in open-repository needs `vscode-api.workspace-request-resource-trust` to
  answer false. That is exthost or workbench-shell state; in the merged model it runs through the
  owner's behavior.
- `language-server.request` with no process can't be reached: the client never sends without a
  Running state.

Not modeled:
- Other git operations (push, pull, fetch/autofetch, checkout, stash, worktrees, blame, timeline)
  are command-level stubs only.
- Askpass, the IPC server and the git editor IPC.
- TypeScript language features (completions, diagnostics via geterr, organize imports): the
  sortImports/removeUnusedImports commands are stubs.
- TypeScript version selection and an invalid tsdk.
- Markdown language-server features (links, diagnostics, paste and drop), the preview webview
  messaging, and static previews.
- Copilot (133 commands) is modeled only at the command level.

## Reconciliation round

Fixed:
- 21 aborts in the `window-show-*-message` calls (exthost's request shapes are now copied);
- the TypeScript activate abort on `found`;
- 13 stub-vs-owner kind warnings;
- the stand-in activation and command-map components are deleted;
- modeled coverage went from 7% to 71%.

Remaining merged failures (38), none in my behaviors:
- 26 abort in `ext-host-extension-service.activate-by-event` (`no such key: registry`), reached
  when my handlers call `commands.executeCommand`. Waits on exthost.
- 3 abort in `ext-host-extension-service.get-extension-description` (`registry`), from TypeScript
  activation's getExtension. Waits on exthost.
- 9 abort in `output-service.on-did-register-channel` (`no such key: log`). Git activation passes
  `options: {log: true}` as vscode.d.ts has it; exthost forwards the input and terminal-debug-tasks
  reads a top-level `log`. Waits on exthost and terminal-debug-tasks.

Final round (merged with worlds.yaml):
- `git-activate-git-missing` and `-warning-ignored` failed because `setContext` wasn't found. The
  call now continues on error, since main.ts:244 doesn't await it.
- The real gap is exthost's: `setContext` is an API command that ExtHostApiCommands registers
  (extHostApiCommands.ts:532, mapping to `_setContext`), and exthost's command map lacks it.
- `markdown-show-preview-no-resource` now uses `builtin-extensions-seed`, so `markdown.showSource`
  resolves through command-service.

## Fix round

Sources of this round: FIXES.md (builtin-extensions row), oracle/extensions.md (fix request 5), the
test-reach list from `--tests examples/vscode/test-targets.json`, and the feature list.

**How the fragment is built now.** `gen/builtin-extensions/gen.py` produced the reconciliation
fragment. This round's additions live in `gen/builtin-extensions/fixround/*.yaml`; gen.py applies them by
id (component + name for interfaces): an id that already exists is replaced, a new one is appended.
The part files are `ghauth`, `ts`, `md`, `emmet-html` and `misc`, applied in sorted order. Running
gen.py reproduces the fragment and skips byte for byte.

### github-authentication (oracle fix request 5, FIXES row)
- Components: `github-authentication-extension` (extension.ts:13-90), `github-session-engine`
  (github.ts:171-1018), `keychain` (keychain.ts:9-48), `github-server` (githubServer.ts:106-300),
  `github-auth-flows` (flows.ts:607-662), `account-links` (accountLinks.ts:57-141),
  `microsoft-authentication` (microsoftAuthentication.ts:60-75), `entra-token-exchange`
  (entraTokenExchange.ts:163-470), `enterprise-configuration` (enterpriseConfiguration.ts,
  enterpriseStorage.ts), `github-enterprise-authentication-provider` (githubEnterprise.ts) and the
  external `github-rest-api`.
- readSessions (github.ts:703-792) hydrates an accountless session with one GET /user. It writes
  back only when an account id was a number or a session was dropped (:786-789). The oracle case
  `does not loop when Codespaces secret storage drops hydrated account data` is
  `builtin-extensions-github-auth-sessions-no-write-loop`, and it passes: one get-user call and 0
  keychain writes.
- Covered: getSessions (scope and account filter, probe validation), restore through the Entra
  exchange (signed out, minted, account mismatch unlinks), createSession over getFlows (device code
  only without a client secret; fallback prompt; cancel; invalid provider), removeSession
  (transient or persisted; the server token is deleted only with a client secret and a gho_ token),
  checkForUpdates diffs, and the enterprise URI validation and host keys.
- Configs: `github-authentication-prefer-device-code-flow` (false/false), `github-enterprise-uris`
  and `github-enterprise-uri` (unset, modeled as empty).
- Assumptions:
  - `Config.gitHubClientSecret` is absent in the source (config.ts:17-19). Published builds mix it
    in, so `github-server.client_secret_configured` defaults to false.
  - The user's part of each sign-in flow is the choice `github-auth-flows.trigger.outcome`.
  - GitHub's 401 message is modeled as `Unauthorized`.
- Gap (exthost): `ExtHostAuthentication.$getSessions` is skipped as plumbing, and
  `ext-host-authentication.get-session`/`get-accounts` have no behavior. So the workbench's
  getSessions doesn't reach this provider yet: the flows enter at the provider. The Microsoft
  accounts are held on `microsoft-authentication` for the same reason. The per-host enterprise
  engines aren't modeled separately.

### Test reach and features
- Test reach went from 22/141 (16%) to 111/141 (79%), in four clusters:
  - TypeScript: the request queue, cached responses, completions, fixAll, quickFix, code lenses,
    signature help, jsDoc, text rendering and notifications;
  - Markdown, ipynb and notebook-renderers: editor RPC and protocol, the recovering task queue,
    rich links, image paste, openDocumentLink, serializers and linkify;
  - emmet commands with their real action logic, and the HTML/CSS language-server modes;
  - terminal-suggest specs and the PATH cache, git askpass, repositoryCache, timeline,
    worktreeInclude and notifications, plus npm, php, git-base, configuration-editing and github's
    push error handler.
- Unreached (30):
  - 29 copilot completions-core tests, left untranslatable as FIXES.md says (string and algorithm
    helpers inside the extension, e.g. textDocument.ts:194);
  - typescript `onEnter.test.ts`, which targets src/vs/editor (editor area).
- Features: `git` covers git-activate, git-command and 6 more; `typescript` covers
  typescript-activate, typescript-open-document and 13 more.
- Coarse spots (each test is still reached at the decision level):
  - emmet-helper's expansion text;
  - copyFiles' `${var/pattern/repl/}` transforms;
  - linkify and stack-trace regexes;
  - ipynb base64 buffers;
  - the textRendering @link details;
  - external process output (git for-each-ref, php -l, npm view), held as state or input.

### Breaking changes
- `typescript-service-client.execute` (typescriptServiceClient.ts:947-956, tsServer/server.ts:228-306)
  now goes through `single-ts-server.execute-impl` and `request-queue`:
  - the response `type` can also be `noContent` or `pending`;
  - a write error fails with `typescript-server-error`;
  - the optional `config.low_priority` request field is new;
  - `state.sent` lists only requests written to tsserver.

  No other area or judge/oracle file calls it. My callers (tsserverRequest, goToProjectConfig,
  findAllFileReferences, goToSourceDefinition) check `type == 'response'` and still pass.
- `builtin-extensions-typescript-request-cancelled`: cancellation now follows the queue
  (server.ts:187-207). A request already sent is still answered.
- Additive only, with no caller broken:
  - `markdown-it-engine.render` adds `containing_images`;
  - `cmd-npm-packagemanager` adds `package_manager`;
  - `cmd-git-clone` returns the clone outcome;
  - `cmd-editor-emmet-action-updateimagesize` now fails `no-valid-image-source` when there is no
    image (updateImageSize.ts:105-107).

### Requests for other areas
- exthost:
  - give `ext-host-authentication` `$getSessions`, `get-session` and `get-accounts` behaviors
    that reach the registered provider (extHostAuthentication.ts:100, 132);
  - register `vscode.open` and `revealInExplorer` as commands. Calls to them fail
    `command-not-found` today, so mine continue on error (openDocumentLink.ts:99, 114).
- platform-core: the command-service dispatch `targets` lack the new
  `emmet-extension.cmd-emmet-expandabbreviation`.

### After the generator move
- `emmet.expandAbbreviation` (emmetCommon.ts:33) is registered in `builtin-extensions-seed`
  through gen.py's `FIXROUND_COMMANDS`. The scenario
  `builtin-extensions-emmet-expand-via-command-service` runs it through
  `command-service.execute-command`. The workbench's `editor.emmet.action.expandAbbreviation` is a
  separate workbench-contribs action that calls this command.
- exthost's `ext-host-authentication.get-sessions` now dispatches to a generic
  `third-party-extension.get-authentication-sessions`, not to `github-session-engine.get-sessions`.
  The gist scenarios therefore activate github-authentication first, so that the `github` provider
  is registered. Routing the `github` provider id to `github-session-engine.get-sessions` is still
  exthost's to do.


## 2. Components modeled in depth (code references)

- `walkthroughs-service` (gettingStartedService.ts:121): step progress memento (PROFILE, :172-173). `progress-step` (:548-558)
  saves before checking the step exists, so an unknown step is persisted and then throws "Tried to progress unknown step";
  fires onDidProgressStep (sync) to `getting-started-page.on-did-progress-step` (gettingStarted.ts:284).
- `getting-started-commands` (gettingStarted.contribution.ts:168-198): no-op on a falsy argument.
- `startup-page-runner-contribution` (startupPage.ts:113-153, isStartupPageEnabled :271-287): welcome page, README
  (markdown.showPreview), terminal editor, or nothing; never on a reloaded window or with an active editor.
- `insert-snippet-action` (commands/insertSnippet.ts:79-150): inline body -> ad-hoc snippet `random/<n>`; name+language
  lookup; quick pick; silently returns when nothing resolves; reads the clipboard for CLIPBOARD variables; records usage.
- `snippets-service` (snippetsService.ts): getSnippets (:278-303) sorted by usage recency (:343-347);
  usage in `snippets.usageTimestamps` (PROFILE, last 100, :170-205).
- `opener-validator-contributions` (trustedDomainsValidator.ts:46-145), `trusted-domain-service` (trustedDomainService.ts:54-59),
  `trusted-domains-configure` (trustedDomains.ts:77-165): non-http links open; links from a trusted workspace skip the prompt
  unless promptInTrustedWorkspace; trusted domains open; else Open / Copy / Configure Trusted Domains / Cancel.
- `workspace-trust-ux-handler` (workspace.contribution.ts:287, showModalOnStart :488-523, doShowModal :448-486),
  `workspace-trust-request-handler` (:204-279), `workspace-trust-commands` (:748-789).
- Save participants (saveParticipants.ts): trim whitespace (:48-58), final newline (:116-141), format on save (:226-270),
  code actions on save (:321-378, apply :389-433); `format-modified.get-modified-ranges` (formatModified.ts:51-82).
- `format-document-none-action` (formatActionsNone.ts:35-66), `default-formatter` (formatActionsMultiple.ts:138-223).
- `bulk-edit-service.apply` (bulkEditService.ts:206-286), `bulk-edit.perform` (:99-142), `bulk-text-edits.apply`
  (bulkTextEdits.ts:293-339, version check :218-220), `bulk-file-edits.apply` (bulkFileEdits.ts:243-244),
  `bulk-edit-preview-contribution.preview-edit` (preview/bulkEdit.contribution.ts:111-160).
- `edit-sessions-contribution` (editSessions.contribution.ts: constructor gate :169-171, store :686-810, resume :491-583),
  `edit-sessions-workbench-service` (editSessionsStorageService.ts: initialize :187-239, write :106-122, read :131-157,
  delete :159-170, list :172-185), `edit-sessions-store-client` (rows of the remote store).

## 3. Boundary stubs (all contracts from the shared shapes; no owner fragment existed when I wrote mine)

| Stub | Owner | Fields I send/read |
|---|---|---|
| editor-service.open-editor (seam) | workbench-shell | resource, options |
| command-service.execute-command (seam) | platform-core | command_id, args; error command-not-found |
| configuration-service.update-value | platform-core | key, value, target |
| clipboard-service.read-text / write-text | platform-core | text |
| file-service.write-file (seam) | platform-core | resource, content |
| workspace-trust-management-service.is-workspace-trusted / complete-workspace-trust-request / cancel-workspace-trust-request / set-parent-folder-trust / request-workspace-trust-on-startup | workbench-shell | trusted (is-workspace-trusted response `{trusted}`, default false) |
| preferences-service.open-user-settings | workbench-shell | json_editor, query |
| snippet-controller2.insert | editor | template, clipboard_text |
| text-model.push-edit-operations | editor | resource, edits[{range, text}] (EditorTextEdit shape) |
| format.format-document-with-selected-provider / format-document-ranges-with-selected-provider | editor | resource, mode, ranges. Component id `format` is my guess for the functions in editor/contrib/format/browser/format.ts:290 and :107; align in reconciliation |
| text-file-service.save (seam) | files-search-scm | resource, options.reason |
| working-copy-file-service.create / delete / move | files-search-scm | resource, target |
| extensions-workbench-service.open-search | remote-server | text |

## 4. Config

Owned by this area (code that reads them is here; product.json sets none of them, so deployed = default):

| Config | Value | Default | Sources |
|---|---|---|---|
| files-trim-trailing-whitespace | false | false | files.contribution.ts:237-239, saveParticipants.ts:53 |
| files-insert-final-newline | false | false | files.contribution.ts:249-251, saveParticipants.ts:121 |
| files-trim-final-newlines | false | false | files.contribution.ts:255-257, saveParticipants.ts:159 |
| editor-code-actions-on-save | {} | {} | codeActionsContribution.ts:71, saveParticipants.ts:330 |
| files-refactoring-auto-save | true | true | bulkEditService.ts:332-339, :272 |
| editor-default-formatter | "" | null | formatActionsMultiple.ts:276-282, :139. Modeled as "" because a null config value is dropped from the CEL map |
| workbench-trusted-domains-prompt-in-trusted-workspace | false | false | url.contribution.ts:89-92 |
| security-workspace-trust-startup-prompt | never | never | workspace.contribution.ts:806-808 |
| workbench-startup-editor | welcomePage | welcomePage | gettingStarted.contribution.ts:317-330 (registered with `experiment: {mode: auto}`, so experiments may change the running value) |
| edit-sessions-store | "" | "" | product.json key editSessions.store.url, read at editSessions.contribution.ts:169 and editSessionsStorageService.ts:87. **The OSS product.json has no editSessions.store, so Cloud Changes registers no actions, views or auto resume in a build from code.** |

Referenced from fixtures.yaml (not redefined): editor-format-on-save and files-participants-timeout (files-search-scm),
editor-format-on-save-mode (editor). files.trimTrailingWhitespace etc. are registered in files.contribution.ts
(files-search-scm path); I own them because only this area's code reads them. Files-search-scm may disagree in reconciliation.

No deployed value differs from its code default (product.json registers no configurationDefaults). The one deployment
difference is the product key editSessions.store, which is absent.

## 5. Fixture requests

- No walkthrough or snippet seed exists in the fixtures. I seed them in my own components' initial state
  (`walkthroughs-service.steps` with two built-in Setup steps from gettingStartedContent.ts:254-339, and
  `snippets-service.snippets.typescript` with "For Loop" from extensions/typescript-basics). A coordinator-owned fixture
  could carry them instead.
- A fixture variant with `edit-sessions-store` configured would help; my scenarios set it per scenario.

## 6. What the code didn't settle, and assumptions

- Trust state, formatter counts, SCM quick-diff ranges, model versions, language registration and file existence belong to
  other areas. Where my code branches on them I used named choices (`formatters`, `diff`, `model_version`,
  `language_registered`, `target_exists`, `working_changes`, `conflicts`) or the trust stub. The two `if trusted` branches
  (validate-link from a trusted workspace, showModalOnStart already trusted) don't run in my fragment alone because the
  stub answers `trusted: false`; they run after merge when workbench-shell's real behavior reads `workspace-context`.
- `workspace-trust-startup-prompt-next-start` is the same entry as `workspace-trust-startup-prompt`, named as a later
  window start; it is the code's only reader of `workspace.trust.startupPrompt.shown`.
- showModalOnStart's canSetWorkspaceTrust, virtual-workspace and empty-workbench exits (:495-508) are not modeled.
- Snippet language at the cursor is approximated as typescript (the dirty-editor file) when no lang_id is given.
- isURLDomainTrusted is reduced to '*', an exact origin, or a `*.suffix` match.
- The startup README lookup assumes README.md exists (it does in base-workspace); the folder scan is not modeled.
- bulk-edit perform runs file edits before text edits; the code groups consecutive edits of the same type into runs
  in their original order. Cell and opaque edits are not modeled. The shutdown veto (:267, :304-327) is a narrated step.
- validate-link's `command:` URI branch for untrusted workspaces (:49-58) is not modeled.
- The workspace trust request handler's ContinueWithoutTrust option is only offered when the caller supplies that button;
  the model doesn't check the button list.

## 7. Docs or common knowledge vs code

- Cloud Changes ("Continue Working On", store/resume) is commonly described as available; in a build from code it is
  absent because product.json lacks editSessions.store (editSessions.contribution.ts:169-171). The commands
  `workbench.editSessions.actions.*` and the `continueEditSession` extension point handlers are not registered there.
- The workspace trust startup dialog is often remembered as shown on first open; the default
  security.workspace.trust.startupPrompt is `never` (workspace.contribution.ts:808), so restricted mode is entered
  silently with a banner.
- files.refactoring.autoSave saves only when a refactoring touched more than one file (bulkEditService.ts:272).
- welcome.markStepComplete on an unknown step id persists the progress before throwing (gettingStartedService.ts:551-554).

## 8. Simulator gaps

- Debounces and per-resource maps: snippet usage keeps the last 100 entries (snippetsService.ts:200); not expressed.
- A store `get` with `default: null` still fails not_found, so read misses are modeled as `on_error: continue`
  (editSessionsStorageService.ts:152-156 returns undefined).
- A null config value is dropped from `config`, so editor.defaultFormatter's null default is the empty string.
- Optional request properties are always generated as fake data, so `insert-snippet-action`'s request declares no
  properties (otherwise the quick-pick branch is unreachable from a scenario).
- Events that another area fires (onDidInitiateWorkspaceTrustRequestOnStartup, opener validators run by OpenerService)
  are modeled as direct calls or as flow entries, because the publisher's behavior lives in another fragment.

## 9. Known gaps

- 449 entries are covered, but only about 30 have modeled behavior. The rest are covered at registration level through
  the catalog components: comments (CommentService, threads), preferences (settings/keybindings editors, ~45 commands),
  local history commands (restore/delete/rename call IWorkingCopyHistoryService), user data profiles, themes,
  localization, logs, issue reporter, browserView (Integrated Browser), timeline, call/type hierarchy, remote tunnels,
  accessibility, relauncher (SettingsChangeRelauncher prompts a restart via hostService.restart on listed settings),
  welcome views, surveys, telemetry and performance contributions. Candidates for the next round: local history restore,
  relauncher, comments reply, theme selection (writes workbench.colorTheme), profile create/switch.
- Inventory line for `editor.action.insertSnippet` is the registerAction2 call (snippets.contribution.ts:26); the
  handler is cited separately.


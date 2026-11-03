# workbench-contribs notes

Area: every `src/vs/workbench/contrib/**` folder that no more specific area owns (66 folders), plus six services whose
`createDecorator` is outside contrib but whose `registerSingleton` implementation is in these folders
(IBulkEditService, IRenameSymbolTrackerService, IAccessibleViewService, IAccessibleViewInformationService,
IAccessibilitySignalService, IOnboardingTryoutHandoffService). 557 inventory entries: 449 covered, 108 skipped.

Fragment: `fragments/workbench-contribs.yaml`. It is generated from two hand-written parts (the deep flows) plus a
catalog of the remaining contribution modules, so every catalog component lists exactly the entries it covers.

## 1. Entry points

Covered by modeled flows (interfaces with behavior, reached from flow entries):

| Entry | Covered by |
|---|---|
| welcome.markStepComplete / markStepIncomplete | `getting-started-commands.cmd-welcome-mark-step-complete` / `-incomplete` (flows `walkthrough-mark-step-complete`, `walkthrough-mark-step-incomplete`) |
| IWalkthroughsService, `walkthroughs` extension point, resetGettingStartedProgress | `walkthroughs-service` (progress-step, deprogress-step, get-walkthroughs) |
| StartupPageRunnerContribution | `startup-page-runner-contribution.run` (flow `workbench-contribs-startup`) |
| editor.action.insertSnippet, ISnippetsService, `snippets` extension point | `insert-snippet-action.cmd-editor-action-insert-snippet`, `snippets-service` (flows `snippets-insert`, `snippets-list`) |
| OpenerValidatorContributions, ITrustedDomainService | `opener-validator-contributions.validate-link`, `trusted-domain-service`, `trusted-domains-configure` (flows `link-protection-open`, `trusted-domain-check`) |
| WorkspaceTrustUXHandler, WorkspaceTrustRequestHandler, workbench.trust.manage / configure | `workspace-trust-ux-handler`, `workspace-trust-request-handler`, `workspace-trust-commands` (4 flows) |
| SaveParticipantsContribution | `save-participants-contribution` and its participants (4 flows) |
| editor.action.formatDocument.none, DefaultFormatter, editor.action.formatChanges | `format-document-none-action`, `default-formatter`, `format-modified` (flows `format-document-none`, `default-formatter-select`, `save-participant-format-on-save`) |
| IBulkEditService, BulkEditPreviewContribution, refactorPreview.* | `bulk-edit-service`, `bulk-edit`, `bulk-text-edits`, `bulk-file-edits`, `bulk-edit-preview-contribution` (flow `bulk-edit-apply`) |
| EditSessionsContribution, storeCurrent, resumeLatest, IEditSessionsStorageService | `edit-sessions-contribution`, `edit-sessions-workbench-service`, `edit-sessions-store-client` (4 flows) |

All other covered entries are cataloged: the registering module (or the service's registerSingleton implementation
class) is a component whose `sources` cite each entry's registration line, and the `workbench-contribs-startup` flow
names each such component in a narrative step ("<file> registers N commands, M contributions"). That is coverage of
the registration, not of each command's handler behavior; see section 9.


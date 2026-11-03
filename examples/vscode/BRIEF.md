# Brief: build the Visual Studio Code 1.144 (built from code) ontology from code

You are one of 13 area agents building a mosaic ontology of **microsoft/vscode at
1.144.0** directly from its source code. Each agent writes one fragment. The fragments
are merged with `skeleton.yaml` and `fixtures.yaml` into one ontology. Then the repo's own tests
are translated into scenarios against it, and independent judges test it against well-known
behavior of the system. Model what the code does, not what you remember about the system. Where
they differ, the code wins, and you record the difference in your notes.

Contracts, naming and the shared worlds are fixed before you start. Coverage is measured against
an inventory of entry points. Citations are checked mechanically and then by a judge.

## Rules

1. **Source of truth.** The code at `/home/lbethay/.cache/mosaic-bench/vscode-1.144.0` (`1.144.0`, `2c33b50b16c472efe58357d1d2a8a5414bc23fbf`).
   It is read-only: never modify, build or run anything in it.
2. **Independence.** Read only these: the code, `skeleton.yaml`, `fixtures.yaml`, the inventory,
   your own files, and, for contracts only, an owner's fragment when you call another area. Never
   read `other areas' notes`, `BENCHMARK.md`, `judge/**`, `oracle/**`.
3. **Evidence.** Every component, interface, config and narrated step cites code, as
   path:line or path:line-end, relative to snapshot.path, one source per string. Use **one source per string**, and the `sources` list when you need
   several. Cite files, not directories. Cite **the method's own lines**, because coverage and
   judges match them; a citation near an entry point doesn't cover it. `**/*.md`, `**/test/**`, `**/*.test.ts`, `test/**`, `build/**`, `scripts/**`, `.github/**`
   may orient you, but they are not evidence. Cite them only in your notes.
4. **Deployed config decides modes.** Code defaults aren't always what runs. The deployed values
   come from registerConfiguration calls (Registry.as<IConfigurationRegistry>(...).registerConfiguration) across src/vs/** (default); product.json (deployed), in that order. Every value a behavior reads is a **config
   entity**, read as `config['<id>']`, durations included:
   `timeout_ms: "= config['write-request-timeout-ms']"` (`deadline_ms`, `after_ms`, `every_ms`,
   `stagger_ms`, `count` and `join.need` take templates too). A config belongs to the area whose
   code reads it:
   - **you own it**: define it in your fragment, named by the setting key in kebab-case with dots as -: files.autoSaveDelay -> files-auto-save-delay (keep the unit in the name only if the key has one; attributes.key holds the original), with the deployed
     `value`, the code `default`, and both lines in `sources`. For the shared values in
     `files.autoSave` (owner files-search-scm); `files.autoSaveDelay` (owner files-search-scm); `files.hotExit` (owner main-process); `editor.formatOnSave` (owner files-search-scm); `editor.formatOnSaveMode` (owner editor); `files.participants.timeout` (owner files-search-scm); `security.workspace.trust.enabled` (owner workbench-shell); `extensions.autoUpdate` (owner remote-server); `terminal.integrated.enablePersistentSessions` (owner terminal-debug-tasks); `search.maxResults` (owner files-search-scm) that the profile assigns to you, `fixtures.yaml` holds a reference;
     your definition replaces it, and you fix its value if the reference is wrong;
   - **another area owns it**: use the reference in `fixtures.yaml`, or add your own copy marked
     `attributes: {boundary: true, owner: <area>}`. An unmarked copy that differs is a merge error.
   Record every place where the deployed value and the default differ.
5. **Secrets.** Never open `**/*.env*`, `**/*.age`, `**/*.pem`, `**/*.key`, `**/credentials*`, `**/.npmrc`. Never copy a token, key, password or internal
   hostname into the ontology.
6. **Your files only.** Write `fragments/<area>.yaml`, `notes/<area>.md` and `skips/<area>.json`
   under `examples/vscode/`. Edit nothing else. Don't commit.

## Areas and ownership

An area owns the code under its paths. Where paths overlap, the more specific glob wins. The
overrides below beat paths.

| Area | Module | Owns | Except | Typical entry points |
|---|---|---|---|---|
| platform-core | platform | `src/vs/base/**`, `src/vs/platform/**` | `src/vs/platform/agentHost/**`, `src/vs/platform/mcp/**`, `src/vs/platform/terminal/**`, `src/vs/platform/extensionManagement/**`, `src/vs/platform/userDataSync/**`, `src/vs/platform/remote/**`, `src/vs/platform/*/electron-main/**`, `src/vs/platform/windows/**`, `src/vs/platform/update/**` | service implementations (instantiation, configuration, storage, files, lifecycle, commands, keybinding, contextkey, quickinput, notification, dialogs), IPC channels |
| main-process | main-process | `src/vs/code/**`, `src/main.ts`, `src/cli.ts`, `src/bootstrap-*.ts`, `src/vs/platform/*/electron-main/**`, `src/vs/platform/windows/**`, `src/vs/platform/update/**`, `src/vs/workbench/electron-browser/**` |  | process mains, window lifecycle (open, reload, close with veto), native host, update, shared and utility processes, backup on exit (hot exit) |
| editor | editor | `src/vs/editor/**` |  | editor commands and actions, text model edits and undo, cursor, find, suggest/completion, hover, code actions, formatting, folding, rename |
| workbench-shell | workbench | `src/vs/workbench/browser/**`, `src/vs/workbench/common/**`, `src/vs/workbench/services/**` | `src/vs/workbench/services/extensions/**`, `src/vs/workbench/services/textfile/**`, `src/vs/workbench/services/workingCopy/**`, `src/vs/workbench/services/search/**`, `src/vs/workbench/services/chat/**` | workbench startup, layout and parts, editor service and groups, views, command palette, keybinding resolution, configuration resolution, workspace trust |
| exthost | extension-host | `src/vs/workbench/api/**`, `src/vs/workbench/services/extensions/**`, `src/vs/platform/extensions/**`, `src/vscode-dts/**` |  | extension host start/restart/unresponsive, activation by events, the vscode.* API, MainThread/ExtHost RPC |
| files-search-scm | workbench | `src/vs/workbench/contrib/files/**`, `src/vs/workbench/contrib/search/**`, `src/vs/workbench/contrib/searchEditor/**`, `src/vs/workbench/contrib/scm/**`, `src/vs/workbench/contrib/markers/**`, `src/vs/workbench/contrib/mergeEditor/**`, `src/vs/workbench/contrib/multiDiffEditor/**`, `src/vs/workbench/services/textfile/**`, `src/vs/workbench/services/workingCopy/**`, `src/vs/workbench/services/search/**` |  | open/save/revert/auto save, save participants (format on save), dirty tracking, save conflicts, file watching, explorer operations, search, SCM views |
| terminal-debug-tasks | workbench | `src/vs/workbench/contrib/terminal/**`, `src/vs/workbench/contrib/terminalContrib/**`, `src/vs/workbench/contrib/debug/**`, `src/vs/workbench/contrib/tasks/**`, `src/vs/workbench/contrib/testing/**`, `src/vs/workbench/contrib/output/**`, `src/vs/platform/terminal/**` |  | terminal creation and pty host (persistence, reconnect), debug sessions over DAP, tasks, test runs, output channels |
| notebook-webview | workbench | `src/vs/workbench/contrib/notebook/**`, `src/vs/workbench/contrib/webview/**`, `src/vs/workbench/contrib/webviewPanel/**`, `src/vs/workbench/contrib/customEditor/**`, `src/vs/workbench/contrib/interactive/**` |  | notebook open/execute/kernel selection, webviews and custom editors |
| chat | workbench | `src/vs/workbench/contrib/chat/**`, `src/vs/workbench/contrib/inlineChat/**`, `src/vs/workbench/services/chat/**`, `src/vs/workbench/contrib/agentsVoice/**` |  | chat requests to participants and language models, tools and confirmations, edits sessions, inline chat |
| agents | agents | `src/vs/platform/agentHost/**`, `src/vs/platform/mcp/**`, `src/vs/workbench/contrib/mcp/**`, `src/vs/sessions/**` |  | the agent host process, agent sessions app, MCP servers (start, tools, sampling) |
| remote-server | remote-server | `src/vs/server/**`, `src/server-*.ts`, `cli/**`, `remote/**`, `src/vs/platform/remote/**`, `src/vs/workbench/contrib/remote/**`, `src/vs/platform/extensionManagement/**`, `src/vs/workbench/contrib/extensions/**`, `src/vs/platform/userDataSync/**`, `src/vs/workbench/contrib/userDataSync/**`, `src/vs/workbench/contrib/update/**` |  | remote server and CLI, remote connection/reconnect, extension install/update/enablement, settings sync |
| workbench-contribs | workbench | `src/vs/workbench/contrib/**` |  | every other workbench contribution (preferences, codeEditor, accessibility, comments, browserView, welcome, snippets, ...) |
| builtin-extensions | builtin-extensions | `extensions/**` |  | built-in extensions' activation and commands; model git and typescript-language-features and markdown-language-features in depth, the rest at the command level |

**Overrides (owned by function, not by file):**

| Symbol | Area | Reason |
|---|---|---|
| ExtensionService.startExtensionHosts and restart/unresponsive handling | exthost | extension host lifecycle is exthost logic living under workbench/services/extensions |
| WorkspaceTrustManagementService | workbench-shell | trust gates many areas; one owner |

**Cross-area rules:**

- Commands are invoked through platform-core's command-service.execute-command; the registering area models the command's handler as interface cmd-<id slug> on its own component.
- Keybindings resolve in workbench-shell (keybinding-service.dispatch) and then execute the command; areas don't model key dispatch.
- Extensions call the vscode API (exthost owns vscode-api.<namespace>-<function>); the API's MainThread side calls the owning area's service. builtin-extensions model only extension logic and call vscode-api stubs.
- Saving goes through files-search-scm's text-file-service.save; the editor area owns format-on-save providers, invoked as a save participant.

## Naming (fixed, so callers can predict the owner's ids)

- **Components:** the class in kebab-case (TextFileService -> text-file-service); a service's component is its registerSingleton implementation class; MainThreadDocuments -> main-thread-documents. Put every component under your skeleton module, or under
  another of your components.
- **Interfaces:** the method in kebab-case without a leading $ (save, try-save-document); commands are cmd-<command id with . and _ as -> lowercase, cut to 64> (workbench.action.files.save -> cmd-workbench-action-files-save).
- **Routes and messages:**  RPC: the shape method on its implementation component, kind rpc, attributes {shape: MainThreadDocumentsShape}
- **Schemas:** area prefix in PascalCase (FilesTextFileModel); shared contracts keep the owner's name. A shared contract keeps its owner's name, and only the owner
  defines it.
- **Configs:** the setting key in kebab-case with dots as -: files.autoSaveDelay -> files-auto-save-delay (keep the unit in the name only if the key has one; attributes.key holds the original). **Instances:** w1, w2 for workbench windows; eh1, eh2 for extension hosts (ehN serves wN); pty1 for the pty host; srv1 for a remote server.
- **Scenarios:** <area>-<flow>-<case>.
- Ids are globally unique across all areas. Never use bare generic names: `handler`, `store`, `client`, `service`, `manager`, `request`, `result`, `error`, `model`, `provider`, `controller`.

Worked examples: vscode-command workbench.action.files.save → component `save-file-actions`, interface `save-file-actions.cmd-workbench-action-files-save`; service ITextFileService → component `text-file-service`, interface `text-file-service.save`; exthost-rpc MainThreadDocumentsShape.$trySaveDocument → component `main-thread-documents`, interface `main-thread-documents.try-save-document`; extension-api workspace.applyEdit → component `vscode-api`, interface `vscode-api.workspace-apply-edit`

## Contracts (fixed before fan-out)

- **The owner's definition is the contract.** Each interface has one owner: the area that owns
  its code. When you call another area's interface:
  1. if `skeleton.yaml` predeclares it (a boundary stub with `owner`), copy that stub exactly;
  2. else, if the owner's fragment exists, copy its request, response, kind and errors (including
     `retryable`), and read that fragment for nothing else;
  3. else, use the shared shapes below, declare only what your call site really sends and reads,
     and expect to align in the reconciliation round.
  Never invent a different `kind`, response type or error status for someone else's interface.
- **Shared shapes.** Use these field names everywhere, so stubs merge cleanly:

  - `uri`: string, a URI (file:///work/app/src/main.ts)
  - `resource`: string, a URI, as `uri`
  - `version_id`: integer, the text model's version
  - `language_id`: string (typescript, markdown, ...)
  - `command_id`: string, the registered command id
  - `args`: list, command arguments
  - `window_id`: string, the window instance (w1)
  - `reason`: string, the SaveReason / close reason enum name in kebab-case (explicit, auto, focus-change, window-change)
  - `token`: object {canceled: bool}, a CancellationToken

  Shared schemas, defined once in `skeleton.yaml`: `FilesSaveOptions` (owner files-search-scm: reason, force, skip_save_participants); `EditorTextEdit` (owner editor: range, text); `ExthostExtensionDescription` (owner exthost: identifier, activation_events, main, browser, capabilities). Seams, canonical interface ids that the owner defines and callers stub (owner: callers): `command-service.execute-command` (platform-core: all); `configuration-service.get-value` (platform-core: all); `file-service.write-file` (platform-core: files-search-scm, workbench-shell, remote-server); `text-file-service.save` (files-search-scm: workbench-shell, exthost, editor); `extension-service.activate-by-event` (exthost: all); `editor-service.open-editor` (workbench-shell: all); `lifecycle-service.on-before-shutdown` (workbench-shell: files-search-scm, terminal-debug-tasks, main-process).
  
- **Errors.** the error class or result enum in kebab-case: CancellationError -> canceled, FileOperationResult.FILE_MODIFIED_SINCE -> file-modified-since; a thrown Error with a fixed message -> a short slug of the message; the status is none (0) except remote/HTTP surfaces, which use their HTTP status. The fixed table:

| Code | Status | Retryable | Source |
|---|---|---|---|
| canceled | 0 | false | src/vs/base/common/errors.ts:226 |
| file-not-found | 0 | false | src/vs/platform/files/common/files.ts:1487 |
| file-modified-since | 0 | false | src/vs/platform/files/common/files.ts:1489 |
| file-write-locked | 0 | false | src/vs/platform/files/common/files.ts:1491 |
| file-permission-denied | 0 | false | src/vs/platform/files/common/files.ts:1492 |
| file-too-large | 0 | false | src/vs/platform/files/common/files.ts:1493 |
| command-not-found | 0 | false | src/vs/platform/commands/common/commands.ts |
| extension-host-crashed | 0 | true | src/vs/workbench/services/extensions/common/abstractExtensionService.ts |

  Check any code you add against `src/vs/base/common/errors.ts`, `src/vs/platform/files/common/files.ts` and the code that throws it.
- **Stubs merge by union.** When several areas stub the same boundary interface, the merge combines
  their properties, required lists, enums and errors, keeps the first value of any scalar, and
  warns about every disagreement. The owner's definition wins over every stub. So declare every
  field your code really reads, and copy the owner's scalars.
- **Shared infrastructure.** `disk` (kind io, named disk.<op> (read-file, write-file, stat, watch, delete)); `settings-store` (kind io, named settings-store.<scope>-<op> (user-read, workspace-write, ...)); `storage-db` (kind io, named storage-db.<scope>-<op> (global/workspace state.vscdb)): calls to them are boundary-stub interfaces
  named after the operation, with one kind for all areas. Stateful storage that scenarios must
  inspect belongs on the owner's own component, as `store` interfaces.

## The world: fixtures, instances and config

- **Use the shared fixtures. Never seed a private world.** `fixtures.yaml` defines
  `base-workspace` (folder /work/app with src/main.ts, src/util.ts, README.md, package.json, a git repo; default settings; trusted); `one-window-folder` (base-workspace opened in w1 with extension host eh1 running; built-in extensions registered, none activated); `two-windows` (w1 on /work/app and w2 on /work/lib, eh1 and eh2); `untrusted-folder` (one-window-folder with the folder not trusted (restricted mode)); `dirty-editor` (one-window-folder with src/main.ts open and modified (version 2, not saved)). Every scenario lists `fixtures: [...]` and adds only the state its case
  needs on top. Use the canonical names (folder: /work/app; files: ['src/main.ts', 'src/util.ts', 'README.md', 'package.json']; extension: vscode.typescript-language-features; user: dev) in inputs and in your
  schemas' `examples`, so fake entry data lands in the seeded world. Never seed another area's
  state under names of your own; if the fixture lacks something your case needs, ask the
  coordinator to add it, and record the request in your notes.
- **Unknown keys fail.** A behavior that looks up a table, key, tenant or route that isn't there
  fails with the code's real error. It never logs and skips.
- **Instances, not `to` fields.** Copies of the same code (`workbench-window` (a renderer window running the workbench); `extension-host` (a local extension host process; ehN serves window wN)) are instances.
  Address a peer with `on: <instance>` on the `call`, `emit` or `publish`, not with a `to` or
  `endpoint` field in the request. A behavior knows where it runs from `self`. Per-instance state
  is keyed `<component>@<instance>`. Entries run on `w1` unless a step
  says `on:`.
- **Time.** Every timestamp derives from `now`. The fixture sets the clock's epoch. Never write a
  wall-clock literal. Deadlines and timeouts read config
  (`deadline_ms: "= config['read-request-timeout-ms']"`), and periodic work uses timers (`emit`
  or `publish` with `every_ms` and `count`) or `entry.repeat`.

## How to model

Read these first: `.claude/skills/mosaic-ontology/SKILL.md` with its
`references/document-format.md` and `references/modeling-codebases.md`; then
`.claude/skills/mosaic-simulation/SKILL.md` with its `references/behavior-language.md` and
`references/recipes.md`. Ignore their CLI instructions: you verify with the check tool below.

- **Fragment header.** `schema_version: 1`, `id: vscode`, then your entities. Don't redefine
  skeleton components, configs or fixtures.
- **Depth.** Go down to the smallest components that make a decision or own state. Behaviors
  follow the real control flow: refusals with the real codes; retries with their real triggers;
  timeouts and deadlines from config; fallbacks and state transitions; capacity limits
  (`capacity`) where the code bounds concurrency; background work as timers, events or repeated
  flows.
- **Fan-out is `parallel` with a join, not a sequential `foreach`.** When the code sends to
  several peers at once and waits for some of them, model it with `parallel` and `join:
  {need: ...}`, a `timeout_ms` or deadline, and `stagger_ms` for hedged or speculative requests.
  Keep `foreach` for loops the code really runs one after another.
- **Events.** Listeners and subscribers use `subscribe:` on the interface and `publish:` at the
  source, with `delivery: sync` when the code calls listeners inline.
- **Boundary stubs.** When your behavior calls an interface another area owns, declare it in your
  fragment with `attributes: {boundary: true, owner: <area>}`, give it the owner's shapes, and
  leave out the behavior. Never model another area's internals.
- **No mocks.** Your scenarios drive branches with inputs, fixtures, `state`, `config`,
  `choices`, `faults` and `steps`. `mocks` are refused by the gate. If a branch depends on another
  area's answer, set that area's state through the fixture or `state`, so the real seam runs.
- **Flows** come from the inventory's entry points. Each modeled flow has an `entry` and
  scenarios: a happy path plus one per significant branch, each with `expect` that proves the
  branch and its cause.
- **Write, then read.** Every flow that writes state carries `tags: [writes]` and has at least one
  multi-step scenario that writes and then reads the effect back through the system's own read
  path (`steps: [{flow: <write>}, {flow: <read>}]`), asserting on the read's result. `--lint
  hollow` reports a `writes` flow without one. Steps never overlap; concurrency inside a step is
  `parallel`. Assert on `state` or `trace` in every scenario that writes, never only on `result.ok`.
- **Assert on your own calls and the outcome**, not on how many times another area's internal
  interfaces are called.
- **Scale.** Breadth first. Rough target per area: components 20–90, flows 6–14, scenarios 25–60. Quality over volume, but
  every entry point is accounted for.

## Coverage: every entry point is modeled or skipped with a reason

The inventory is at `examples/vscode/inventory.json` (6086 entries: 2682 vscode-command, 1034 exthost-rpc, 728 service, 650 workbench-contribution, 483 extension-command, 121 extension-api, 98 ipc-channel, 87 exthost-customer, 74 activation-event, 55 extension-point, 37 cli-command, 33 process-main, 3 cron, 1 python-cli). Each entry is
`{kind, name, file, line}`. Ownership and coverage per kind:

| Kind | Owner | What covers it |
|---|---|---|
| vscode-command | path | an interface on the registering component named cmd-<command id slug>, citing the registration lines |
| exthost-rpc | the area owning the MainThread*/ExtHost* implementation of the shape | the implementation's method interface cites the shape method's line in extHost.protocol.ts |
| service | the area owning the registerSingleton implementation | the implementation component cites the createDecorator line |
| workbench-contribution | path | a component for the contribution class, with its constructor/startup behavior as an interface |
| extension-command | builtin-extensions | an interface on the extension's component named cmd-<command id slug> |
| extension-api | exthost | an interface on vscode-api named <namespace>-<function> citing vscode.d.ts |
| ipc-channel | path | the channel's server component cites the registerChannel line |
| exthost-customer | path | the MainThread* component cites the @extHostNamedCustomer line |
| activation-event | builtin-extensions | the extension's activate flow cites its package.json activationEvents line |
| extension-point | path | the extension point's handler component cites the registration |
| cli-command | remote-server | a cli interface citing the clap definition |
| process-main | path | a startup flow whose entry cites the main |

Skip rules already decided: cron, python-cli matching ".github/**": not an entry point of the product: CI workflow or repo tooling; exthost-rpc matching "methods of shapes whose implementation is a pure pass-through to a service already modeled": RPC plumbing: covered by the service interface it forwards to (list each in skips with the target); vscode-command matching "commands registered only for tests, telemetry or developer diagnostics (workbench.action.dev*, _workbench.*)": developer or internal command with no user-visible behavior.

For every entry your area owns:
- **model it**: a flow-reachable interface or component cites the entry's own lines, or is named
  after it by the rules above. Covering an entry can be cheap: an entry interface whose behavior
  calls an already modeled component, with one happy-path scenario;
- **or skip it**: with a one-line reason. Heuristic false positives are skips too ("not an entry
  point: ...").

**Group skips go into `skips/<area>.json`, machine-readable.** Write a JSON array of
`{"kind", "name", "file", "line", "reason"}`, one object per inventory entry. Expand each group
into its exact entries, copying `kind`, `name`, `file` and `line` from the inventory. Your notes
keep the grouped, human-readable form ("the 212 getters in `FooMBean`: reads of config or
metrics, no behavior").

## Verify before hand-off

```sh
cd <mosaic repo>
export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
go run ./internal/devtools/check \
  -f examples/vscode/skeleton.yaml -f examples/vscode/fixtures.yaml -f examples/vscode/fragments/<area>.yaml \
  --code /home/lbethay/.cache/mosaic-bench/vscode-1.144.0 --strict-citations --inventory examples/vscode/inventory.json \
  --behavior-coverage --lint hollow --no-mocks -v
# debugging one scenario:
go run ./internal/devtools/check -f ... --scenario '^<id>$' --trace
```

Hand off only when:
1. **0 errors, 0 failed scenarios, 0 scenario warnings, 0 mocks.** Warnings are usually a stub
   that guessed a shape.
2. **Citations resolve** (`--strict-citations`), and **support their claims**: run
   `--cite-sample 15 --seed <n>` twice with different seeds and read each
   sampled claim next to its code. Fix every bad one.
3. **No merge warnings that mention your fragment.**
4. **Coverage.** Every entry you own is covered in the `-v` output or listed in
   `skips/<area>.json`.
5. **Hollow lint clean**, and **behavior coverage** at least 0.85
   for your area, with every `fail` and `if` branch run by some scenario or explained in your notes.
6. **Write-then-read**: every flow that writes state is tagged `writes` and has its read-back
   scenario (part of the hollow lint).

## Independent review

After hand-off, your fragment is merged, the repo's tests are run against it as scenarios, and
judges who didn't build it check it against the code. Their findings come back to you as fixes,
not suggestions. Write your notes so that a stranger can check them.

## Notes file (`notes/<area>.md`)

1. Entry points: each inventory entry in your area, with the flow or interface that covers it, or
   its skip reason (grouped).
2. The components you modeled, with code references.
3. The boundary stubs you declared, and whose contract you copied (skeleton, owner fragment, or
   shared shapes).
4. The config you read: deployed value and default, with references, and where they differ.
   Configs you own, and the owners of those you reference.
5. Fixture requests: state your cases needed that the shared fixtures lack.
6. What the code didn't settle, and the assumptions you made.
7. Where the docs, or common knowledge, disagree with the code.
8. **Simulator gaps**: behavior you couldn't express in mosaic, or only approximately. Give each
   an example and the code line.
9. Known gaps.

## Report back (≤200 words)

Entity counts; the check tool's final lines (validation, citations, coverage, behavior coverage,
hollow lint, mocks); the flows you modeled; entries covered and skipped; fixture requests; the
top modeling gaps and simulator gaps.

## VS Code specifics

- **Processes and instances.** Code in the renderer runs per window (`workbench-window`
  instances w1, w2). Code in the extension host runs per host (`extension-host` instances eh1,
  eh2; ehN serves wN). Calls that cross a process boundary are `rpc` (MainThread/ExtHost) or
  `ipc` (channels) interfaces, called with `on:`.
- **User actions are flows.** The `user` actor starts them: a key press resolves a keybinding,
  then runs a command; a menu item or the palette runs a command; typing is a text model edit.
  Rendering and pixels are out of scope. Model the state the UI shows (dirty markers, editors,
  notifications, prompts) as component state, and user prompts as `choice` steps the scenario
  can drive.
- **Events.** VS Code's `Emitter.fire` calls listeners synchronously. Model `onDid*` events as
  `publish` with `delivery: sync` and subscribers. Debounced or throttled events
  (`Delayer`, `RunOnceScheduler`, `ThrottledDelayer`) are timers with `after_ms`.
- **Cancellation.** A `CancellationToken` is the `token` field. Timeouts that cancel work are
  deadlines or `timeout_ms` with `on_error` handling `canceled`.
- **The single-threaded renderer and extension host.** Where ordering or queueing between
  requests matters, give the component `capacity: {concurrency: 1}`.
- **Commands.** Each command is `cmd-<id slug>` on the component whose code registers it. Group
  skips are fine for commands that only toggle UI visibility, focus or layout, as long as each
  entry is listed in your skips file with the reason "UI toggle: no state beyond the layout".

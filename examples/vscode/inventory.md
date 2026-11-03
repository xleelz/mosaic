# VS Code 1.144.0: stage-1 inventory audit

Snapshot: `/home/lbethay/.cache/mosaic-bench/vscode-1.144.0` (read-only).
Command: `go run ./internal/devtools/inventory --code $CODE --out examples/vscode/inventory.json`.
Auto-detect turns on the `ts-frontend` plugin, because the root has `src/vs`. The base `ts`
scanner finds no Next.js or tRPC entries here. The single `python-cli` entry comes from the base
`python` scanner and the 3 `cron` entries from the YAML scan.

Total: 6,086 entries over 14 kinds.

## Counts by kind

| kind | count | via (count) | detail |
|---|---:|---|---|
| vscode-command | 2,682 | action2 1,810; commands-registry 316; keybinding-rule 230; editor-action 187; editor-command 139 | the owning class or handler; 94 ids (3.5%) are unresolved and named by their class or constant expression ("id unresolved") |
| exthost-rpc | 1,034 | rpc-shape | `Shape.$method`; 979 name the implementing `MainThread*`/`ExtHost*` class |
| service | 728 | create-decorator | the decorator id and the `registerSingleton` implementations (563 have one) |
| workbench-contribution | 650 | workbench-contribution2 437; contribution-registry 129; editor-contribution 84 | contribution id and phase |
| extension-command | 483 | package-json | the extension, plus the handler site when the extension calls `registerCommand('id')` or `@command('id')` (365) |
| extension-api | 121 | vscode-dts | `vscode.<namespace>.<function>` |
| ipc-channel | 98 | register-channel | the channel implementation (e.g. `ProxyChannel.fromService(...)`) |
| exthost-customer | 87 | extHostNamedCustomer 80; extHostCustomer 7 | the `MainContext.*` identifier |
| activation-event | 74 | package-json | |
| extension-point | 55 | extension-point | |
| cli-command | 37 | clap-subcommand | Rust `cli/`: `code tunnel service install` and similar, with the clap enum |
| process-main | 33 | top-level-startup 29; export-main 3; bundle-entry 1 | |
| cron | 3 | gha-schedule | base YAML scanner (GitHub Actions schedules) |
| python-cli | 1 | py-main | base Python scanner |

## Precision

I read a seeded sample of 40 entries (`shuf -n 40 --random-source=<(yes 42)`) against the code.
All 40 were true entry points with the right name and line: 18 commands, 7 RPC methods,
5 extension commands, 5 activation events, 3 services and 2 customers. I checked command ids that were resolved through constants (for example
`ForceUpdateAgentPluginsCommandId`, `InlineChatActions.FixDiagnosticsAction` and the
`CONFIGURE_VOICE_INSTRUCTIONS_ACTION_ID` passed to a base constructor) by hand.

**Measured precision: 40/40 (1.00).**

I also reviewed every `process-main` entry. All 33 are process, worker or bundle entries (the
electron main, cli, server, extension host, shared process, pty host, watcher, agent host and the
web workers). Two classes of false positive were found and fixed during the audit:

- `*.common.main` modules are now excluded.
- A clap line drift came from Rust lifetimes read as unterminated quotes. The TS lexer now keeps
  the newline.

## Recall

Recall is measured against a grep of each registration pattern over the same non-test sources.
An entry counts as found when the inventory has an entry of that kind at that file and line
(within an entry's extent). Raw recall counts every grep hit. Adjusted recall leaves out hits that
are not registrations (declarations, the output-channel registry) and hits merged by design (the
same id registered twice in one file is one entry).

| pattern | grep | found | raw | what the rest are |
|---|---:|---:|---:|---|
| `registerAction2(` | 1,837 | 1,818 | 0.990 | 19 parametric registrations in loops or helpers (`id` from a destructured config or a template built from a parameter, or a duplicate id) |
| `CommandsRegistry.registerCommand(` | 346 | 316 | 0.913 | 30 helper or parametric registrations (`descriptor.id`, `id`, `commandId`, `this.cmdId`, a descriptor variable). Their ids exist only at the helpers' call sites |
| `KeybindingsRegistry.registerCommandAndKeybindingRule(` | 238 | 230 | 0.966 | 8 ids from a `...rule` spread in a helper, a loop (`toCommandId(i)`) or a duplicate id |
| `registerEditorAction(` | 184 | 182 | 0.989 | 1 method declaration, 1 duplicate |
| `registerEditorCommand(` | 141 | 139 | 0.986 | 2 duplicate ids (`FIND_IDS.ReplaceOneAction` registered twice) |
| `registerWorkbenchContribution2(` | 443 | 437 | 0.986 | 5 overload declarations and 1 internal forwarding call: 1.00 adjusted |
| `.registerWorkbenchContribution(` | 129 | 129 | 1.000 | |
| `registerEditorContribution(` | 84 | 84 | 1.000 | |
| `ExtensionsRegistry.registerExtensionPoint` | 56 | 55 | 0.982 | 1 descriptor passed as a variable from another module |
| `createDecorator<` | 729 | 728 | 0.999 | 1 duplicate name in one file |
| `.registerChannel(` | 130 | 108 | 0.831 | 9 are the output-channel registry (not IPC); 7 are IPC plumbing that forwards a `channelName` parameter; 6 are the same channel registered on several branches: 1.00 adjusted |
| `@extHost(Named)Customer` | 87 | 87 | 1.000 | |
| `$method` lines in `extHost.protocol.ts` | 1,034 | 1,034 | 1.000 | |
| `vscode.d.ts` namespace functions (unique) | 121 | 121 | 1.000 | |
| extension `contributes.commands` (JSON) | 492 | 483 | 0.982 | 9 in `vscode-test-resolver`, a test extension that is skipped by design: 1.00 adjusted |
| extension `activationEvents` (JSON) | 84 | 74 | 0.881 | 10 in test extensions (skipped by design): 1.00 adjusted |
| process entries in `build/next/index.ts` | 28 | 19 | 0.679 | see the misses below. The 14 entries not in that list (electron main, cli, server, `desktop.main`) are true entries that are built separately |

**Measured recall for commands across all five forms: 2,682 of 2,746 grep sites (0.977) raw.** All
the misses are parametric registrations (ids known only at run time or at a helper's call site) or
duplicates.

## Known misses and limits

- **Parametric commands.** Ids that come from a loop variable, a destructured config or a helper
  parameter are not listed. Examples: `PositionPanelActionConfigs.forEach(...)`,
  `toCommandId(groupIndex)`, `registerQuickInputCommandAndKeybindingRule({...rule})` and the
  `CommandsRegistry.registerCommand(id, ...)` helpers in `editorCommands.ts` and
  `fileActions.contribution.ts`. Add these by hand from the helpers' call sites if a builder needs
  them.
- **Unresolved ids (94).** When an id expression can't be evaluated (a class built by a factory,
  `registerAction2(action)` in a loop, ids from another module's computed values), the entry is
  named after the class or constant and the detail says `id unresolved`.
- **Process entries.**
  - Not found: renderer bootstraps not named `*main*` (`vs/code/electron-browser/workbench/workbench`,
    `vs/code/browser/workbench/workbench`, `vs/sessions/electron-browser/sessions`),
    `vs/workbench/contrib/debug/node/telemetryApp`, the `*.main.internal` web bundles and the
    three keyboard-layout contribution bundles.
  - The build's entry list lives in `build/`, which is skipped.
- **The extension API** covers only namespace functions in `vscode.d.ts`. Not listed: namespace
  `const`/`let` members (events such as `window.onDidChangeActiveTextEditor`, properties), classes
  and the 180 `vscode.proposed.*.d.ts` files.
- **Built-in extensions' own code** (for example the `copilot` extension's internal DI services and
  commands registered only in TS) is not scanned for core patterns. Its commands appear through
  `package.json`, with the handler site in the detail when it can be found.
- **Merged duplicates.** The same command id, channel name or decorator registered twice in one
  file is one entry, at the first site.
- **Test sources** are skipped: `test/` directories, `*.test.ts`, `*.integrationTest.ts`, and
  extensions whose names contain "test". The test-explorer feature directories named `testing` are
  kept when ts-frontend is on.

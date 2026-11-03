# Fix round (VS Code, after judging)

The model passes every gate, but the judges and the test oracle found wrong claims, thin
behaviors and missing paths (`RESULTS.md`, `judge/*.md`, `oracle/*.md`). This round fixes them.

- The rules in `BRIEF.md` and the decisions in `RECONCILE.md` still apply.
- **You may now read `judge/` and `oracle/`** files that concern your area, because they're your
  fix list. Fix the model, never the judges' or the oracle's scenarios.

## New tools since your build (DESIGN §13.1 items 14–19)

- **Concurrency:** steps can overlap (`at_ms`, `await: false`).
- **Cancellation:** tokens, with `token` and `cancel`.
- **Instances:** `restart` revives an instance, and a `kill` fault or step kills one.
- **Streams:** a callee uses `yield`; the caller sets `stream: true` and handles items in
  `on_item`.
- **Channels:** `put` and `receive`.
- **CEL helpers:**
  - `eval(expr, vars)`, which evaluates `when` clauses held as data;
  - `replace` and `matches` for strings;
  - dynamic `set` paths.
- **Time:** microseconds.
- **Features:** `profile.yaml` now lists 31 features, each with an owner. For each one you own, model it with a flow tagged `feature:<id>` that a scenario runs, or skip it in `skips/<area>.features.json` with a reason.
- **Gates:**
  - `--lint trivial`, `--max-trivial 0.35`, `--min-substantive 0.5`;
  - `--tests examples/vscode/test-targets.json` (test reach);
  - `--features examples/vscode/profile.yaml`.

## Contracts and breaking changes (binding)

**A breaking change that makes an interface match the code is welcome.** The breakage is the
point: it shows every caller that relied on the wrong shape. Never add a parallel interface or a
shim the code doesn't have just to keep old callers passing.

1. **Make the interface match the code, then report who it breaks.**
   1. Before you change an interface's shape, grep `fragments/*.yaml` and
      `judge/`/`oracle/` for `<component>.<interface>`.
   2. After the change, run the merged gate.
   3. In `notes/<area>.md` under **Breaking changes**, list each change with its citation and
      every caller it broke: the area, the interface or scenario, and what it must now read.
   4. Put the same list in your report.

   Update callers in your own fragment. Leave other areas' callers broken: the coordinator routes
   them to their owners. Judge and oracle scenarios that break are re-adapted by the re-scorers.
2. **Document text (shared_data `document-text`).** The editor owns `text-model`. It adds
   `text-model.set-value`, with input `{uri, value}`. It replaces the text, bumps `version_id`
   and `alternative_version_id`, and pushes no undo stop (`textModel.ts` `setValue`).
   `text-model.get-value`, with input `{uri}`, already returns `value`, `version_id` and
   `alternative_version_id`. Text-file models (files-search-scm) hold only
   `{dirty, saved_version_id, mtime, encoding, eol}` per resource. They call these interfaces for
   text and versions, and never hold a copy. The editor ships `set-value` first. Until it exists,
   files-search-scm writes its calls against this name and reports any failure instead of
   working around it.
3. **Search streaming.** Files-search-scm owns it. Model `ISearchService.textSearch` as the
   code shapes it, with the progress callback or iterable it really uses (citing it). If that
   changes the existing interface's result, it's a breaking change under rule 1. The exthost
   text-search provider (`ext-host-search.provide-text-search-results`) gains the
   `folder_encodings` input.
4. **Terminal output streaming.** Terminal-debug-tasks owns it. Model the pty data path as the
   code does. If chat's or agents' terminal tools read a shape that changes, list them under
   rule 1.
5. **Command service.** Workbench-shell owns it. Keybindings and the palette call
   `command-service.execute-command` with its current shape. `when` clauses go through CEL
   `eval(expr, context_keys)`, inside the keybinding resolver and the palette, not in callers.

## Fix list by area

| Area | Fix |
|---|---|
| editor + files-search-scm | **One owner for document text (`shared_data`).** The editor's `text-model` owns the text. Text-file models hold only the file state (dirty, saved version, mtime), and read and write the text through the editor's interfaces. Revert and external-change reloads update the one copy (E8, E9). `saved_version_id` uses the alternative version id, so undoing back to the saved version is clean (E7). `files.eol` applies on create. Double-click selects inside brackets |
| files-search-scm + workbench-shell | The save command uses the active editor when no resource is given, so Ctrl+S works through the command service (E1, X7). `text-file-service.create` keeps the content. Search goes through a real provider (ripgrep stand-in) with streamed results (`yield`), the `search.maxResults` limit and the limit-hit flag (S1). Cancel cancels the search with a token instead of clearing results (S2). Workspace symbol providers are queried directly |
| exthost | The onWillSave budget (1750 ms) is enforced (E3). Extension init filters by workspace trust (X8). The auto-profiler and the unresponsive notification have behavior (X5). API commands, including `executeWorkspaceSymbolProvider`'s argument validation and `setContext`. Debug visualization providers. Editor tabs beyond `create`. The text-search provider passes folder encodings |
| workbench-shell + platform-core | Settings reads apply language overrides and resource or folder scopes (C6). Keybindings go through the command service, and `when` clauses are evaluated with `eval` against the context keys (C2). The command palette lists and runs commands (C3). Opening an editor resolves its model (C7). Backups are restored on restart (`restart` keeps backups, C4). `AccountPolicyService`. `resolveAsync` in the configuration resolver |
| terminal-debug-tasks | Shell output streams to the renderer (`yield`, T1). On a pty-host crash, terminals are notified, normal terminals restart and task terminals exit −1 (`kill` and `restart`, T3). Reload keeps only terminals that had input, replaying the live buffer (T2, overlapping steps). The adapter really starts (`start-da-session`), and adapter exit ends the session (D1, D2). `OutputMonitor` polling and `TerminalOutputCache` |
| chat + agents | `send-request` honors `@`-mentions and the default Agent mode (A1). Agent tool calls reach MCP, and MCP start lists and registers its tools (A3). Cancel aborts an in-flight request (A4, token). Tool confirmation waits for a later user step (A2, overlapping steps). Thin behaviors (chat 59% and agents 42% trivial) get real logic for the entries the oracle hit: perf markers, chat-pet, title-bar density, the sandbox policy, plugin discovery |
| remote-server | **Security-relevant:** the connection token is generated and checked, and an empty or missing token gets 403. `extensions-allowed` is an object. The remote extension host is forked (R1). The reconnect loop has no 20-attempt cap, so it runs to the 3 h grace (R2). The Running Extensions editor input |
| main-process | The Agents window open intent and `vscode:selectAgentsFolder`. `OnboardingTryoutHandoff`. Snap env unset and restore |
| builtin-extensions | The github-authentication extension. Copilot text-document helpers stay untranslatable |
| workbench-contribs | The integrated browser's `newTab` and `open` commands are registered and modeled |
| notebook-webview | Kernel source actions and their per-notebook cache. Copying a cell output checks the MIME type |

**Thin behaviors.** Every area brings `--lint trivial` under 0.35 and substantive modeled to
≥ 0.5. Today chat, agents, exthost and workbench-contribs fail.

## Verify

The gate is the RECONCILE.md command plus
`--lint hollow,trivial --max-trivial 0.35 --min-substantive 0.5 --tests examples/vscode/test-targets.json --features examples/vscode/profile.yaml`.
Also re-run your judge and oracle scenarios against the merged model.

**Exit criteria:**
- your judge and oracle cases that were `fail`, `partial` or `model-bug` now pass, or are
  explained;
- the gates are green;
- your test reach goes up.

## Report (≤150 words)

Report the fixes with citations, the cases now passing, the gate numbers before and after, and
what's still open.

# VS Code 1.144 benchmark: does the generated ontology map VS Code's workflows correctly?

The builders never see this file. It lists well-known behaviors of microsoft/vscode at 1.144.0.
Each one is written so it can run as a mosaic scenario against the merged ontology
(`examples/vscode/vscode.json`).

**Verify each case against the code before scoring it.** These expectations come from the
documentation and common knowledge, and either can be wrong for 1.144.0 with the registered
setting defaults and `product.json`. A judge first confirms or corrects each expectation from the
code, citing it. Docs and tests may also be cited, for the record. Only then is the ontology
scored against the corrected expectation.

**Default world:** the fixture `one-window-folder`.
- **Windows and processes:** window w1 on `/work/app`, served by extension host eh1.
- **Extensions:** git, TypeScript and Markdown are registered, and none is activated yet.
- **Files:** four files on disk.
- **Settings:** every setting at its registered default. That includes `files.autoSave` off,
  `files.autoSaveDelay` 1000 and `files.hotExit` onExit.
- **Trust:** the folder is trusted.

Other fixtures are `dirty-editor`, `format-on-save`, `auto-save-after-delay`, `two-windows` and
`untrusted-folder`.

## Scoring per case

| Score | Meaning |
|---|---|
| **pass** | The verified outcome **and** the code's path are reproduced: the right components, processes or instances, messages, and decisions |
| **partial** | The outcome is right but the path is wrong or incomplete. Or the behavior is modeled, but no scenario can drive it without editing the model (say what edit) |
| **fail** | The model produces a different outcome |
| **missing** | The behavior isn't modeled |
| **sim-gap** | Modeled as well as mosaic allows, but the simulator can't express it. Name the missing feature |

Each case gets a scenario under `judge/scenarios/<ID>.yaml`. The scenario uses fixtures, inputs,
`choices`, `faults` and multi-step `steps` only. It never uses mocks, and it never edits the
model.

## Editing and saving (`editing-saving`)

| ID | Behavior | Expected outcome |
|---|---|---|
| E1 | Save a dirty file (Ctrl+S → `workbench.action.files.save`) | The keybinding resolves to the command. The command reaches the text file service's save, then the save participants, then a file write. The model is no longer dirty, and `saved_version_id` equals `version_id`. The disk content changes |
| E2 | Save with `editor.formatOnSave` true | The format-on-save participant runs the formatter before the write, bounded by `files.participants.timeout` (60000 ms). The written content is the formatted text |
| E3 | A save participant exceeds `files.participants.timeout` | The participant is canceled, and the save goes ahead with the unformatted content (the save isn't failed) |
| E4 | Save when the file changed on disk after it was opened (mtime newer) | The save fails with `file-modified-since`. The user gets a save-conflict choice: compare or overwrite. Overwrite retries with force |
| E5 | `files.autoSave` = afterDelay, then type | After `files.autoSaveDelay` (1000 ms) of no further edits, the file saves with reason auto. Each new edit restarts the delay (debounce) |
| E6 | Auto save afterDelay with formatOnSave on | Format on save is **not** applied on auto save after a delay. Only explicit saves format |
| E7 | Undo after an edit | The text model reverts to the previous version, and the dirty state follows: undo back to the saved version makes the model clean again |
| E8 | Revert a dirty file | The model reloads from disk and is no longer dirty. No write happens |
| E9 | A file changes on disk while open and **not** dirty | The file watcher event leads to a model reload with the new content. No prompt |

## Extensions and the extension host (`extensions`)

| ID | Behavior | Expected outcome |
|---|---|---|
| X1 | Open a `.ts` file | The `onLanguage:typescript` activation event activates `vscode.typescript-language-features` in eh1. Its `activate()` runs once. Markdown isn't activated |
| X2 | `*` activation | `vscode.git` activates at startup, after the extension host starts (on the `*` event, after startup finished) |
| X3 | An extension's `activate()` throws | That activation fails and is recorded. Other extensions still activate, and the extension host keeps running |
| X4 | The extension host crashes | The renderer detects the exit and restarts the host automatically, a limited number of times within a time window. After that it asks the user to restart. Extensions activate again in the new host |
| X5 | The extension host becomes unresponsive | It's detected after a timeout (about 10 s), the user is notified, and the host can be profiled or restarted |
| X6 | An extension calls `vscode.workspace.applyEdit` | The edit crosses RPC (MainThread bulk edit), applies to the text models, and makes them dirty. It isn't saved automatically |
| X7 | An extension calls `vscode.commands.executeCommand('workbench.action.files.save')` | It crosses RPC to the renderer's command service, and the save happens as in E1 |
| X8 | Untrusted folder | In restricted mode, extensions that don't support untrusted workspaces aren't activated, and the trust banner shows |
| X9 | Two windows | Each window has its own extension host (eh1 and eh2). Activating in w1 doesn't activate in eh2 |

## Workbench and commands (`workbench-commands`)

| ID | Behavior | Expected outcome |
|---|---|---|
| C1 | Execute an unknown command id | The command service rejects it with "command not found" |
| C2 | Keybinding with a `when` clause | The keybinding resolves only when the context key expression is true, for example `editorTextFocus`. Otherwise the next matching binding wins, or none |
| C3 | Command palette | Quick open with `>` lists commands, and selecting one runs it through the command service |
| C4 | Close a window with a dirty file and `files.hotExit` onExit | Hot exit backs up the dirty model, and the window closes **without** a prompt. On restart the backup is restored and the file is still dirty |
| C5 | Close a dirty **editor**, not the window | The user is asked Save / Don't Save / Cancel, and Cancel keeps the editor open |
| C6 | Setting precedence | Folder over workspace over user over default, with language-specific overrides (`[typescript]`) over the general value |
| C7 | Open a file that is already open | The existing editor is activated, and no second model is created |

## Terminal, debug and search (`terminal-debug-search`)

| ID | Behavior | Expected outcome |
|---|---|---|
| T1 | Create a terminal | The renderer asks the pty host for a new pty, and a shell process starts. Data streams to the renderer |
| T2 | Reload the window with `terminal.integrated.enablePersistentSessions` true | Terminals are detached, then reattached after the reload, with their buffer restored. The shell process isn't killed |
| T3 | The pty host crashes | It restarts automatically, and terminals reconnect or are reported lost |
| D1 | Start debugging (F5) | The launch config resolves, and the adapter starts. Initialize, then launch, then setBreakpoints, then configurationDone, in that DAP order |
| D2 | The debug adapter exits unexpectedly | The session ends, and the debug toolbar disappears with an error notification |
| S1 | Text search in the workspace | The query goes to the search provider (ripgrep, in a separate process). Results stream back and stop at `search.maxResults` (20000) with a "limit hit" flag |
| S2 | Cancel a running search | The cancellation token propagates, and the search process is killed |

## Chat, agents and remote (`chat-agents-remote`)

| ID | Behavior | Expected outcome |
|---|---|---|
| A1 | Send a chat request | It's routed to the participant (default or `@`-mentioned), sent to the language model, and the response streams into the chat view |
| A2 | The agent requests a tool that needs confirmation | The tool call waits for user confirmation. Approving runs it, and denying returns a refusal to the model |
| A3 | An MCP server's tools | When the server starts, its tools are listed and registered, and a tool call goes to the server over MCP |
| A4 | Cancel a chat request | The request's cancellation token stops streaming, and the response is marked canceled |
| R1 | Connect to a remote | The renderer connects to the remote server, the remote extension host starts there, and workspace extensions run remotely |
| R2 | The remote connection drops | It reconnects automatically with backoff. After a grace period it gives up, and the user is asked to reload |
| R3 | Install an extension from the marketplace | The shared process downloads it, verifies it, extracts it, and registers it. The extension becomes available without a reload when possible |
| R4 | `extensions.autoUpdate` on | Outdated extensions update automatically on a periodic check |

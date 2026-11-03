# VS Code 1.144 benchmark results

Can mosaic map a large, complex front end (microsoft/vscode at 1.144.0) correctly from code alone?
This is the third repository built with the generic pipeline (`docs/PIPELINE.md`), and the first
built entirely on the DESIGN §11 language additions and the §12–13 quality tooling.

## The build

- **Setup:** 13 area agents built the model from `profile.yaml`, `skeleton.yaml`, `fixtures.yaml`
  and the brief rendered from the template. Each area defined its own `<area>-seed` fixture, and
  `worlds.yaml` merges them all.
- **Reconciliation:** one round with 14 binding decisions (`RECONCILE.md`), then a short final
  round.
- **Merged model** (`vscode.json`): 1,912 components, 4,401 interfaces, 503 flows and 1,879
  scenarios.
- **The gate passed (`quality-gate.txt`):**

  | Check | Result |
  |---|---|
  | validation errors | 0 |
  | scenarios | 1,879 / 1,879 pass |
  | merge warnings | 0 |
  | hollow-lint failures | 0 |
  | mocks | 0 |
  | citations resolving | 15,552 / 15,552 |
  | behavior coverage | 97.0% |
  | entry points covered | 93% |
  | entry points modeled | 76% |

  No area was below the 50% modeled gate.
- **Inventory:** 6,086 entry points (2,682 commands, 1,034 extension-host RPC methods, 728
  services and more). After skips, 4,067 count.

**Reconciliation mattered.** The first merge failed 149 of 1,395 scenarios with 57 merge
warnings, 43% of entry points modeled, and 5 areas below the gate. Most failures came from 4
seams:
- `uri` versus `resource`;
- the activation request shape;
- the `vscode-api` contracts;
- a missing hop through extension management.

## The test oracle (stage 6): the model is much thinner than the gate says

45 test cases were sampled from VS Code's own test suites (seeded, at least 3 per area) and
translated into scenarios against the merged model, without editing it.

| Verdict | Count |
|---|---|
| pass | **5** |
| model-bug | **28** |
| untranslatable (below the model's level: string utilities, DOM, schema validators, test helpers) | 12 |
| sim-gap | 0 |
| test-mismatch | 0 |

Of the 33 tests the model could express, **5 pass (15%)**. Model bugs by area: exthost 5,
agents 4, remote-server 4, main-process 3, editor, notebook-webview, workbench-shell and
terminal-debug-tasks 2 each, and 1 each for the rest.

**The gate's 76% modeled overstates fidelity.** Random tests land on the long tail: services that
are registered or stubbed with trivial behavior, but don't do what the code does. The
coordinator measured the share of trivial behaviors (a bare `return`, or 1–2 `set` steps with no
call or branch):

| Area | Trivial behaviors |
|---|---|
| chat | 59% |
| agents | 42% |
| remote-server | 37% |
| terminal-debug-tasks | 31% |
| others | 4–27% |

Some oracle findings are wrong behavior, not missing behavior:
- `text-file-service.create` drops the file's content;
- the remote server lets an empty connection token through instead of answering 403;
- `_executeWorkspaceSymbolProvider` calls the public command instead of the providers;
- a skip claimed coverage by a `vscode-api` interface that doesn't exist.

## The benchmark (stage 7)

`BENCHMARK.md` lists 40 well-known behaviors, written before the build from docs and common
knowledge. Builders never saw it. Five independent judges verified each expectation against the
code, then scored the model starting from the merged worlds.

| Group | Pass | Partial | Fail | Missing | Sim-gap |
|---|---|---|---|---|---|
| Editing and saving (E1–E9) | 3 | 3 | 2 | 0 | 1 |
| Extensions (X1–X9) | 5 | 3 | 1 | 0 | 0 |
| Workbench and commands (C1–C7) | 2 | 3 | 1 | 1 | 0 |
| Terminal, debug, search (T1–T3, D1–D2, S1–S2) | 0 | 4 | 1 | 1 | 1 |
| Chat, agents, remote (A1–A4, R1–R4) | 4 | 4 | 0 | 0 | 0 |
| **Total (40)** | **14 (35%)** | **17** | **5** | **2** | **2** |

For comparison, Cassandra's first build scored 30 of 44 (68%) and its second 37 of 44 (84%).
Most non-passes here are **partial**, meaning the outcome is right but the path is wrong or
incomplete. The causes were model in most cases, then contract seams, the world, and a few
simulator gaps.

**20 of 40 expectations were wrong or imprecise for 1.144.0**, the same rate as Cassandra
(20/44). For example:
- hot exit prompts unless this is the last window on Windows or Linux;
- `files.participants.timeout` doesn't cover save participants;
- the OSS `product.json` has no Marketplace, so installs fail;
- the host counts as unresponsive after 3 s, not 10 s;
- a `[typescript]` user override beats a general workspace value;
- a pty-host crash doesn't reconnect terminals;
- with no `@`-mention, a chat request goes to the Agent mode participant.

## What's wrong in the model (to fix)

| # | Area | Wrong claim |
|---|---|---|
| 1 | editor, files-search-scm | **Two copies of the text.** The editor's text model and the file model keep separate copies, so revert and external-change reloads never reach the editor (E8, E9). The text needs one owner |
| 2 | files-search-scm | `saved_version_id` stores the wrong version counter, so undoing back to a saved state stays dirty (E7) |
| 3 | files-search-scm, workbench-shell | The save command requires a `resource` instead of using the active editor, so Ctrl+S aborts through the command service (E1, X7) |
| 4 | exthost | The onWillSave budget of 1750 ms isn't enforced (E3). Extension init doesn't filter by trust, so git and TS activate in restricted mode (X8). The auto-profiler and the restricted-mode banner have no behavior (X5). API commands and the `setContext` command are unmodeled |
| 5 | platform-core, workbench-shell | Settings reads ignore language overrides and resources, and there are no folder settings (C6). Keybindings bypass the command service and context keys, and `when` is limited to one key (C2). The command palette is missing (C3) |
| 6 | workbench-shell | Opening an editor never resolves its text model (C7). Restoring backups on restart is missing (C4) |
| 7 | terminal-debug-tasks | Shell output never streams to the renderer (T1). A pty-host exit doesn't notify terminals (T3). `start-da-session` doesn't start the adapter, and adapter exit is missing (D1, D2). Search cancel clears the results instead of cancelling (S2). The search provider is an unowned stub (S1) |
| 8 | chat, agents | `send-request` ignores `@`-mentions and always uses `ask` mode (A1). Agent tool calls never reach MCP, and MCP never lists its tools (A3) |
| 9 | remote-server | The remote extension host isn't forked (R1). Connection tokens aren't checked. `extensions-allowed` has the wrong type |
| 10 | all | Wrong behavior from the oracle (above), plus the long tail of trivial behaviors on entry interfaces |

## Simulator gaps (ranked by how many judges, oracle agents and builders hit them)

1. **Overlapping steps.** A scenario step waits for every earlier timer, so a keystroke can't land
   during a pending auto save (E5), a cancel can't race a running request (A4, S2), an Accept
   can't answer a waiting tool call (A2), and peers can't act during a grace timer (T2). Four of
   the five judges and several builders hit this. Proposal: steps with `at_ms` run concurrently
   with pending timers, and `await: false` starts a step without waiting for it.
2. **Cancelling a call in flight.** There's no way to cancel a running call (S2, A4,
   CancellationToken patterns everywhere in VS Code).
3. **Restarting an instance.** A window can't close and reopen within one scenario while some
   state (backups) persists (C4, main-process reload).
4. **Evaluating expressions stored as data.** VS Code's `when` clauses are rules held in data
   (C2). Proposal: a CEL helper that evaluates an expression string against a map.
5. **Emits from late calls.** An emit from a call that finishes after its caller's timeout is
   delivered at the timeout, not at the callee's end (X5). This is an engine bug.
6. **Unbounded loops and polls.** These are capped (20 reconnects, so the 3 h grace is never
   reached in R2; a fixed heartbeat count), and polling is approximated by call timeouts.
7. **Smaller gaps:**
   - dynamic `set` paths;
   - reading another component's state;
   - a scenario state that replaces rather than merges into fixture state;
   - optional entry fields always fake-filled;
   - CEL regex replace;
   - a null config value;
   - waiting until something registers.

## Pipeline lessons (generic)

1. **Coverage gates can be gamed by thin behaviors.** Registration-only coverage was caught by
   the modeled gate (DESIGN §13.1 item 13), but trivial behaviors pass it. Proposals:
   - report **modeled (substantive)** coverage;
   - add `--lint trivial`;
   - weight coverage by the repo's test density.
2. **Run the oracle during the build, not only at the end.** Test-derived scenarios given to area
   agents before hand-off would have caught most of the 28 model bugs.
3. **Validate skip reasons.** A skip that claims coverage by another entity must name an existing
   one.
4. **Generate the merged worlds.** `worlds.yaml` went stale (it was missing `agents-seed`).
   Generate it with `assign_inventory.py`.
5. **Shared state needs one owner.** The two text copies (E8, E9) came from two areas each
   modeling "the text". Profiles should name an owner for each shared datum, as they do for
   interfaces.

## Round 2 (fix round, `FIXES.md`)

13 area agents fixed the wrong claims and thin behaviors above. They used the engine primitives
added since the build (DESIGN §13.1 items 14–19) and the new gates (`--tests`, `--features`).

Two rules changed mid-round:
- **Breaking changes are welcome.** A change that makes an interface match the code, and breaks
  its callers, is a finding: the owner lists the broken callers, and the coordinator routes them.
- **Fixes go through the generator.** Areas fix through their generator (`gen/<area>/`), and a
  rebuild must be byte-identical.

**The gate (`quality-gate.txt`) passes.**

| Check | Round 1 | Round 2 |
|---|---|---|
| Scenarios | 1,879 | **2,338** (all pass) |
| Components / interfaces / flows | — | 2,012 / 4,794 / 612 |
| Citations resolving | 15,552 | 17,849 |
| Entry points modeled / substantive | 76% / 63% | 76% / 66% |
| Trivial entry interfaces | 23.8% (3 fragments over 0.35) | **19.3%** (none over) |
| Test files reached (`--tests`) | 51% | **61%** (1,756 / 2,862) |
| Features (`--features`) | 0 / 31 | **31 / 31** |

**Scores.**

| | Round 1 | Round 2 |
|---|---|---|
| Benchmark (40 cases) | 14 pass (35%) | **35 pass**, plus 5 wrong expectations (the model matches the code in 40/40) |
| Oracle (33 translatable tests) | 5 pass (15%) | **33 pass**; every test now has a scenario |

The 5 wrong expectations, each checked against the code (`judge/round2.md`):
- **A1:** the default participant is editsAgent.
- **D1:** the case asserted the old gap.
- **D2:** "adapter terminated unexpectedly" shows only when stopping the adapter fails
  (`rawDebugSession.ts:640`).
- **R2:** reconnects have no 20-attempt cap.
- **T3:** the new pty host reuses pty id 1, and connect-to-direct-proxy is really called 3 times.

The re-score has caveats:
- **The re-scorers weren't blind.** They saw the fixes, so they could adapt calls, paths, timing
  and worlds, never asserted values. 10 judge cases and 4 oracle scenarios were adapted this way.
  Some adaptations are worth a look:
  - **X1:** opens `util.ts`, because the world pre-loads `main.ts`'s model.
  - **E3b:** Skip is an explicit step at 6 s, after the 5 s progress delay. It replaced a
    `choice` assertion that stood in for the user's click.
  - **C2:** uses the code's two real context keys.
- **3 oracle cases were mistranslated in round 1:** account policy, EOL by root and the byok
  startup markers. They skipped the test's own setup or acts.
- **I misbriefed the oracle counts** (26 instead of 21 scenarios). The re-scorer corrected them.

**Breaking changes surfaced and routed** (each listed by its owner):
- **Document text:** it moved to the editor's text model, as the code does. That broke 13
  callers on the shared `dirty-editor` fixture, and the fixture was fixed.
- **Exthost:** install events now carry `operation`, which broke 13 remote-server scenarios.
  Extension commands get a new contributed-command handler, which platform-core added to the
  command service.
- **Main-process:** `open-agents-window` returns `{}`.
- **Workbench-shell:** `vscode.open` forwards to `_workbench.open`.
- **Builtin-extensions:** the TypeScript client goes through a request queue.

**What the round surfaced in the engine** (DESIGN §13.1 item 14, revised):
- **One token changed every scenario.** A single cancel token anywhere switched the whole document
  into concurrent mode, where a step ended with its call tree. That silently broke 21 read-back
  scenarios in other areas.
- **The fix:** a step now ends once its emits and timers are delivered, or once everything else
  is an idle consumer, whatever the mode. Only `at_ms` and `await: false` overlap steps.
- **The cost:** 3 scenarios (1 vLLM, 1 VS Code, 1 engine test) relied on implicit overlap, and
  now say so.

**Process lessons.**
- **Generators drift.** 6 of 13 areas edited their fragment directly, or kept their round's work
  in `/tmp`. Each was moved into `gen/<area>/` and checked for a byte-identical rebuild. The rule
  is now in the pipeline skill.
- **Shared fixtures are contracts.** The `dirty-editor` fixture held a copy of data that one
  area then owned.

**Still open:**
- the `getKernelSourceActions2` providers;
- error-output reformatting;
- `_workbench.diff`, which the local-history compare commands use;
- 29 copilot tests unreached;
- a fresh, blind oracle sample to measure without re-scorer bias.

## Files

- **Contracts:** `profile.yaml`, `skeleton.yaml`, `fixtures.yaml`, `worlds.yaml`, `BRIEF.md`,
  `RECONCILE.md`, `reconcile-notes.md`.
- **The build:** `fragments/`, `notes/`, `skips/`, `gen/`, `inventory.json`.
- **The merged model and gate:** `vscode.json`, `quality-gate.txt`.
- **The oracle:** `oracle/` (sample, brief, per-group verdicts and scenarios).
- **The benchmark:** `BENCHMARK.md`, and `judge/` (per-group verdicts, corrected expectations and
  scenarios).

### Found later (2026-10-31, during another model's rebuild)

`assign_inventory.py` now rejects a skip written by an area that doesn't own the entry. Under the
new rule, workbench-shell's skips file covers 7 entries owned by other areas: 1 of agents', 2 of
platform-core's and 4 of remote-server's. They had counted as skipped. Now they count as
uncovered unless their owners model them or skip them. This is open.

# Fae assessment: can it run mosaic's model-building rounds? (execution model)

| | |
|---|---|
| Status | Assessment plus proposed requirements. Not implemented, and not applied to fae. |
| Target | `~/workplace/fae` working tree: HEAD `e547c03` plus about 1,160 uncommitted changes, read on 2026-11-04. `HANDOFF.md` was last updated 2026-11-01, after wave 13. |
| Scope | The execution model only: fan-out, branches, sub-workflows, messages, resumes, concurrency caps, quota pauses, read isolation, file ownership and long runs. Artifact formats, gate content and UI are out of scope. |
| Builds on | `requirements/fae-hierarchical-workflows.md` (2026-11-01) and `requirements/fae-host-workflow-limit.md` (2026-10-30) |
| New proposals | FAE-RT-020 to -022, FAE-SEC-010, FAE-OPS-040 to -042, FAE-SCH-030 to -032, FAE-WF-110 and -111 |
| Updated proposals | FAE-WF-095, FAE-WF-096, FAE-WF-097, FAE-WF-102, FAE-SCH-023 |

Every claim cites the fae working tree as `path:line`. Paths are relative to `~/workplace/fae`
unless they start with `mosaic/`. Nothing in fae was edited, built or run for this assessment.

## Verdict

**No.** Fae can't run a mosaic round today. The parts that orchestrate a round are partly there:
- a controller can admit a dependency graph of tasks;
- tasks run in parallel;
- one workflow-global role cap can act as a cross-model concurrency cap;
- per-task file scope is enforced;
- resume is durable.

The blocker is the agent runtime, not the graph. Every fae agent turn is a single structured
reply with **no tools**. Its inputs are the scope files, inlined up to 1 MiB each and 4 MiB per
turn, and the scope files are also the only files it may edit. A mosaic area agent, judge or
oracle agent explores a large source tree, runs `mcheck` and iterates for up to 45 minutes. None of
those roles fits that runtime.

The fan-out gaps found on 2026-11-01 are all still present. None of the files involved has
changed since 2026-10-31 (`workflow/fan.go`, `workflow/subworkflow.go`, `engine/subworkflow.go`,
`daemon/subworkflow.go`, `daemon/rpc.go`). The fae work since then went into Linear/Symphony intake
(`symphony/`, `daemon/linear_sync.go`), the terminal UI and cleanup. None of the host-workflow-limit
proposals (FAE-SCH-015 to -022) is implemented: a search of `*.go` and `*.md` for workflow slots,
`workflow-limit` and `host_capacity` found nothing.

### Top blockers

1. **Agents have no tools.** The Claude bridge passes `--tools ""` (`provider/claude.go:78`;
   `provider/README.md:72-73`) and accepts only a `StructuredOutput` tool surface
   (`provider/README.md:84-86`). An agent can't read the repo, grep, run `mcheck` or iterate inside
   a turn. Fae's own handoff lists this as the open HOST-011 conflict (`HANDOFF.md:1757`).
2. **Inputs are inlined and bounded, and reads equal writes.** Scope files are "read in full and
   the only editable files" (`provider/README.md:12`), bounded at 1 MiB per file and 4 MiB per turn
   (`provider/task_scope.go:15`; `provider/README.md:36-45`). For comparison, mosaic's merged
   fragments are 3.4 MiB for Cassandra, 6.3 MiB for vLLM and 8.2 MiB for VS Code. VS Code's
   largest single fragment is 1.4 MiB (`mosaic/examples/*/fragments`). An agent can't read source it
   must not edit.
3. **No dynamic or parallel fan-out inside a workflow, and fan-out branches can't produce
   changes.** Branches are 2 to 16 and fixed (`workflow/fan.go:147-148`). They run one after another
   (`engine/README.md:213-214`). They can't hold change producers or sub-workflows
   (`workflow/fan.go:191-196`). The fan-out must move into a controller-admitted task graph.
4. **No live messages or follow-ups.** Resume-with-context reaches only later briefs, "never the
   turn in flight" (`REQUIREMENTS.md:979`). Restart and resume refuse Done tasks
   (`REQUIREMENTS.md:978`, `REQUIREMENTS.md:1071-1077`). Task-bound provider context doesn't carry
   to another task (`provider/sessions.go:79-83`).
5. **Quota handling is built for short throttles, not session or weekly limits.** A rate-limited
   route parks, and after a 30-minute route-exhaustion bound the task escalates
   `ProviderUnavailable` (`providerhealth/README.md:11`; `REQUIREMENTS.md:1735`). Nothing reads a
   reset time. A turn the limit cuts off loses its edits and its provider context
   (`provider/README.md:147-159`; `LIVE.md:700`).

Close behind: there is no concurrency cap across workflow ids or across roles (`REQUIREMENTS.md:586`
says "no host-wide role lease"); turn timeouts are per bridge instance rather than per role
(`cmd/fae-claude-bridge/main.go:22`); and landing is still Go-only (`HANDOFF.md:1626`).

---

## 1. Capability table

Status values: **Supported** (works for mosaic as fae stands), **Partly** (a workaround exists, or
only part of the need is met), **Missing**.

### 1.1 The gaps found on 2026-11-01

| Need | Status | Evidence | Notes |
|---|---|---|---|
| Fan-out width decided at run time | **Missing** in a template. **Partly** through a controller | `workflow/fan.go:147-148` (2 to 16 branches); `workflow/GRAMMAR.md:230`. Batch admission of items with blocking edges: `daemon/backlog.go:29-33`, `REQUIREMENTS.md:1080-1088` (FAE-CLI-014) | The mosaic coordinator, acting as a controller, can admit one task per area. The width then lives in the controller, not in the workflow, so `workflow simulate` can't see it. |
| Fan-out branches run in parallel | **Missing** inside a FanOut. **Supported** across tasks | Sequential: `engine/README.md:213-214`, `workflow/GRAMMAR.md:251`, `HANDOFF.md:287`. Still only planned: `HANDOFF.md:1649`. Across tasks: tasks in flight are unbounded by default (`REQUIREMENTS.md:582`), and each round dispatches every eligible stage (`REQUIREMENTS.md:602`) | One task keeps one dispatch in flight, so parallelism has to come from separate tasks. |
| A fan-out branch can hold a SubWorkflow | **Missing** | `workflow/fan.go:191-192` | Unchanged since 2026-10-23. |
| A fan-out branch can produce changes | **Missing** (new finding) | `workflow/fan.go:194-195`: "a fan-out branch holds no change producers" | Even with parallel branches, area agents (which write fragments) couldn't sit in one. FAE-WF-096 is updated below. |
| Nesting deeper than 4; a workflow selecting itself | **Missing** | `daemon/subworkflow.go:18`, `daemon/subworkflow.go:35-36`; `workflow/subworkflow.go:30-31` | Unchanged. |
| `Admit` takes a parent | **Missing** | `daemon/rpc.go:20-53` has no parent field | Unchanged. Only SubWorkflow children get parent links. |
| Template parameters or typed inputs | **Missing**. **Partly** through task classes | `daemon/rpc.go:36` (`Content`, free text), `daemon/rpc.go:42-52` (`TaskClass`, `DeclaredFiles`, test fields); task-class overlays change effort and briefs only (`workflow/GRAMMAR.md:67-72`) | The area id, profile path and round number would travel as free text. |
| A child gets its own code-change scope | **Missing** | "A SubWorkflow child gets its parent's resolved scope": `HANDOFF.md:141`, `HANDOFF.md:164` | Unchanged. It matters less once the fan-out is a set of tasks, because each task declares its own files. |

### 1.2 Needs of a mosaic round

| Need | Status | Evidence | Notes |
|---|---|---|---|
| Agents that read a large tree, run commands and iterate within one turn | **Missing** | `provider/claude.go:78`; `provider/README.md:72-73`, `:84-86`, `:268` (Codex: read-only sandbox, no shell); `HANDOFF.md:1757` | FAE-WF-042 requires tool profiles enforced at launch (`REQUIREMENTS.md:401`), but the bridges run with no tools. The only way to iterate is a Loop of AgentTurn, HostCommand and Gate (`REQUIREMENTS.md:359`, `:350`), with test output fed back as `engine_feedback` (`HANDOFF.md:21`). Each turn is then a single reply. |
| Large inputs (source tree, merged model) | **Missing** | `provider/task_scope.go:15` (4 MiB); `provider/README.md:36-45`, `:288` | A file over the bound is dropped with `unavailable_scope` and never sent (`provider/README.md:40-45`). The repository block lists path names only, capped at 5,000 paths (`provider/README.md:50-56`). |
| Sequential stages and dependencies between agents | **Supported** | Workflow edges; blocking backlog edges (`REQUIREMENTS.md:574`, FAE-SCH-002); edge verbs (`REQUIREMENTS.md:998`, FAE-OPS-014) | Covers merge after all areas, and measure after merge. |
| Global cap of about 10 concurrent agents across both models | **Partly** | A workflow-global role pool is shared by every molecule and revision of one workflow id (`REQUIREMENTS.md:586`; `daemon/live_admission.go:848-866`). "There MUST be no host-wide role lease" (`REQUIREMENTS.md:586`). The host workflow limit isn't implemented. Symphony's `max_concurrent_agents` 10 (`daemon/linear_sync.go:25`, `:688-690`) counts only Linear issues | Works only if both models run the **same workflow id**, with every agent kind in **one** workflow-global role of cap 10. Builders, judges and oracle agents are then indistinguishable to the scheduler. Caps per role don't add up to a shared total, and a second workflow id has its own pool. |
| Two models' rounds interleaved fairly | **Partly** | Priority then admission order (`REQUIREMENTS.md:578`); fairness (`REQUIREMENTS.md:598`) | Fair once both models share one pool (row above). |
| Pause and resume on provider quota | **Partly** | `usage limit`, `429` and `rate_limit_event` with status `rejected` classify as rate-limited (`providerhealth/log.go:51`, `:84-91`). Health is per (provider, model), with a penalty of 60, eligibility at 50 and a 1 h hold (`REQUIREMENTS.md:669`). Parks charge no attempt (`REQUIREMENTS.md:673`; `providerhealth/README.md:11`). A park longer than 30 min escalates `ProviderUnavailable` (`providerhealth/README.md:11`; `REQUIREMENTS.md:1523`, `:1735`) | Good for short throttles: health is per model, so one throttle pauses every task on that model. Nothing reads a reset time, so a 5 h session limit or a weekly limit turns into probe turns and escalations. A cut-off turn's edits are rolled back (`provider/README.md:147-159`), and a failed turn invalidates its persistent context (`LIVE.md:700`). No verb pauses all dispatch: Defer covers Pending tasks only (`REQUIREMENTS.md:973`), and schedule pause covers schedules only (`REQUIREMENTS.md:1124`). |
| Per-agent state across pauses, crashes and restarts | **Supported** | Stage-aware resume (`REQUIREMENTS.md:771`, FAE-ROB-012); `fae resume` (`REQUIREMENTS.md:1071-1077`); persistent provider context per task (`LIVE.md:693-701`) | State is per task and stage. Partial work inside an interrupted turn isn't kept (row above). |
| Coordinator routes messages to running agents | **Partly** | Resume-with-context attaches to every later brief, "never the turn in flight" (`REQUIREMENTS.md:979`). Operator messages (`REQUIREMENTS.md:1004`), relayed by a controller only verbatim (`REQUIREMENTS.md:1164-1169`). The per-task Prophet is a separate session (`REQUIREMENTS.md:1010`) | A message lands at the agent's next turn. With single-reply turns, that is the next loop iteration. No typed agent-to-agent message kinds exist. |
| Resume a finished agent for a short follow-up | **Missing** | Restart-with-information refuses Done tasks (`REQUIREMENTS.md:978`). Resume refuses terminal tasks (`REQUIREMENTS.md:1075`). Task-bound context is keyed by task id (`provider/sessions.go:79-83`; `LIVE.md:699`). `CarryFrom` carries pre-code evidence, not context (`daemon/rpc.go:44-46`) | The workaround is a new task with no memory of the first. Workflow-global roles do keep context across tasks (`LIVE.md:695-699`), but they share it with every other task in the role, which breaks isolation. |
| Per-agent gate (`mcheck --stage --accept`) | **Partly** | HostCommand with a literal argument vector, weight and timeout (`REQUIREMENTS.md:350`; `workflow/workflow.go:645-646`; vectors listed in `target_requirements`, `workflow/GRAMMAR.md:103-106`) | The gate can run as a stage. "Accept" (recording a fragment as last-passed for the others) has no counterpart beyond landing on the integration branch. Whether a non-code-bearing task can land without `go test` gates is unverified: landing beyond Go is still open (`HANDOFF.md:1626`, `:1650`). |
| Joint accept of interdependent fragments | **Missing** | Integration is serialized per task (`HANDOFF.md:19`, "serialized integration"). Batch landing is a controller operation onto an operator branch (`daemon/land.go:27`) | There is no way to land several tasks' changes together, all or none, under one gate. |
| Merge agent: full gate, fixes and rebuild | **Partly** | One task whose declared files cover every fragment; HostCommand gates | Blocked in practice by rows 1 and 2: the merged model exceeds 4 MiB, and the agent can't run the gate itself. |
| Read isolation per role (judges and oracle can't read builder files, builders can't read benchmarks) | **Partly** | By construction, a turn reads only its scope files and brief (`provider/README.md:12`, `:46-56`). Protected paths are never in a model's scope (`LIVE.md:99-110`). Workflow-global persistent context spans tasks (`LIVE.md:695-699`) | Isolation holds today only because agents can read almost nothing. The repository block still lists every tracked path name (`provider/README.md:50-56`), so a builder sees that `BENCHMARK2.md` exists. Judges and oracle agents must use task-bound roles, or a "fresh" judge resumes an earlier judge's context. No deny-list exists to carry isolation over to tool-using agents. |
| File ownership per agent | **Supported** | Edits only to files in scope (`provider/README.md:126-131`). Per-task declared files at admission (`daemon/rpc.go:47-52`; `LIVE.md:66-75`). Changes to declared files apply from the next dispatch (`HANDOFF.md:42`) | Fits mosaic's disjoint `fragments/<area>.yaml`, `notes/<area>.md` and `skips/<area>*.json`. Edits are allowed only in `test-first` and `implement` stages (`provider/README.md:126-129`), so an area turn must be declared an implementing change producer. Paths under `.claude/` are protected (`LIVE.md:103`). Mosaic's agents only run the `mcheck` script there and don't edit it. |
| Long runs (hours per round, 45 min per turn) | **Partly** | Durable plane and stage-aware resume (`REQUIREMENTS.md:771`). The bridge `--timeout` defaults to 5 min and is set once per bridge command (`cmd/fae-claude-bridge/main.go:22`). Agent-start bound 180 s (`provider/start_bound.go:14`). Loops expire after 7 days (`REQUIREMENTS.md:689`) | A multi-hour task graph is fine. The turn timeout can't differ per role (45 min for a build, 15 min for a judge). Nothing counts turns, because a turn is a single reply. |
| Coordinator acts as a controller | **Supported** | Authenticated RPC, events, backlog admission, edges, reprioritize, cancel (`HANDOFF.md:23`; `REQUIREMENTS.md:966-985`) | Every mutating verb needs an authorizing operator message id. |
| Artifact-only (non-commit) workflows | **Partly** | Non-code-bearing task classes skip the RED floor (`workflow/GRAMMAR.md:67-72`). Landing gates are Go-only (`HANDOFF.md:1626`) | See the FAE-WF-102 update. |

**Tally (25 rows):**

| Status | Count |
|---|---|
| Supported | 4 |
| Partly (including "missing in a template, partly through a controller") | 12 |
| Missing outright | 9 |

The four Supported rows are dependencies, durable state, file ownership and controller verbs: the
bookkeeping, not the work.

---

## 2. A mosaic round mapped onto fae today

The coordinator becomes a fae **controller**. For each model and round, it admits one backlog graph
(FAE-CLI-014, `daemon/backlog.go:29-33`) with blocking edges.

| Mosaic step | Fae task(s) | Workflow (sketch) | Declared files (write scope) |
|---|---|---|---|
| Benchmark writer | `bench-<model>-r<n>` | `mosaic-agent`: AgentTurn (implement) → HostCommand (lint) → Gate → Integrate | `BENCHMARK<n>.md` |
| Area build or fix ×N (N from the inventory) | `area-<model>-r<n>-<a>` | `mosaic-agent`: Loop { AgentTurn (implement) → HostCommand `mcheck --stage <frag> --accept` → Gate `exit_code == 0` } → Integrate | `fragments/<a>.yaml`, `notes/<a>.md`, `skips/<a>.json`, `skips/<a>.features.json` |
| Merge | `merge-<model>-r<n>`, blocked by every area task | same, with the full-gate HostCommand | every fragment, `<repo>.json` |
| Judges ×5, oracle agents ×5 | `judge-…-<g>`, `oracle-…-<a>`, blocked by merge and bench | `mosaic-agent`, task-bound measurer role | `judge<n>/<g>.*`, `oracle<n>/<a>.*` |
| Results | `results-<model>-r<n>`, blocked by all measures | same | `RESULTS.md` section |
| Next round | the coordinator admits round n+1 after reading the results | | |

**Shared cap.** Both models' graphs use the same workflow id, `mosaic-agent`, with one
workflow-global role `agent` of cap 10. All 20 to 30 tasks of both models then draw from one pool
(`REQUIREMENTS.md:586`), in priority and admission order (`REQUIREMENTS.md:578`).

**Messages.** For "breaking change" and "cross-area need", the coordinator calls Resume-with-context
on the affected area tasks (`REQUIREMENTS.md:979`). For a follow-up to a finished agent, it admits a
new task.

**Quota.** It relies on health parks (`providerhealth/README.md:11`), and resumes the
`ProviderUnavailable` escalations with `fae resume` once the limit resets.

### Where it breaks

| # | Step | What fails | Evidence |
|---|---|---|---|
| B1 | Every agent step | The AgentTurn can't open the source tree, the profile, the skeleton or the brief beyond what is inlined, and can't run `mcheck`, `sample_tests.py` or `check --trace`. A judge "verifies every expectation against the code" (`mosaic/.claude/skills/mosaic-generate/SKILL.md` stage 7), and can't do that here. | `provider/claude.go:78`; `provider/README.md:72-73`, `:84-86` |
| B2 | Area, merge and measure | Read-only inputs (source files, other areas' accepted fragments) can enter only as scope files, which makes them editable. That breaks ownership. They are also bounded at 4 MiB, while the merged models run 3.4 to 8.2 MiB. | `provider/README.md:12`, `:36-45` |
| B3 | Area loop | Each iteration is a fresh single reply that rewrites a fragment of up to 1.4 MiB, with replacement edits that must match exactly (`provider/README.md:136-142`). A 45-minute exploratory build becomes dozens of blind rewrite rounds. | `provider/README.md:126-145` |
| B4 | Mid-run routing | A breaking-change notice reaches the area's *next* reply, not the running work. A finished area can't be resumed with its context for a 5-minute follow-up. | `REQUIREMENTS.md:978-979`, `:1074`; `provider/sessions.go:79-83` |
| B5 | Accepts | `mcheck --accept` records "last passed" state that other areas read. Across fae worktrees, that state exists only once a task has landed, and two interdependent fragments can't land together. | `daemon/land.go:27`; `HANDOFF.md:19` |
| B6 | Quota | A session or weekly limit parks every task, then escalates them after 30 min. Each probe after the health hold launches a full turn into a limit that hasn't reset, and a cut-off turn loses its work. | `providerhealth/README.md:11`; `REQUIREMENTS.md:669`, `:1735`; `provider/README.md:147-159`; `LIVE.md:700` |
| B7 | Shared cap | It holds only while every agent of every model is one role of one workflow id. Anything else run on the same provider account (another workflow, the Prophet per `REQUIREMENTS.md:1018`, a second instance) isn't counted. | `REQUIREMENTS.md:586`, `:1018` |
| B8 | Turn budgets | One bridge timeout applies to every role, and nothing counts turns. | `cmd/fae-claude-bridge/main.go:22` |
| B9 | Landing | Artifact tasks would still pass through landing gates built around `go test`. | `HANDOFF.md:1626` |
| B10 | Fresh measurers | If the measurer role were workflow-global, a round-n judge would resume round n-1's context. It must be task-bound, and then it can't share the global cap pool with the builders, unless every measurer is the same role as the builders. | `LIVE.md:695-699`; `daemon/live_admission.go:855-866` |

B1 to B3 make the round impossible. B4 to B10 make it lossy or manual.

**What works unchanged:**
- the dependency graph;
- durable per-task state;
- disjoint write scopes;
- withheld-reason reporting;
- audit and events.

---

## 3. Requirement proposals

These are written in REQUIREMENTS.md's form. The IDs avoid fae's current maxima (WF-094, SCH-014,
RT-014, SEC-007, OPS-032, API-033, CLI-054) and the ranges already proposed in `mosaic/requirements/`
(WF-095 to -104, SCH-015 to -023, API-034 to -036, CLI-044, -055, -056). They are spaced (WF-110,
SCH-030, RT-020, OPS-040, SEC-010) so that sibling assessments can take the IDs right after the
existing ranges.

### 3.1 New

**FAE-RT-020 (MUST, new) Tool-using agent sessions.** A role MAY declare
`session: agentic`, with a tool allowlist drawn from read, search, edit, write and a restricted
shell.
- The bridge MUST launch the provider with exactly those tools and FAE-SEC-010's path policy.
- The shell, when granted, MUST run with FAE-HOST-011's command shims first on its PATH and the
  pre-tool hook registered. This resolves the HOST-011 conflict (`HANDOFF.md:1757`) for agentic
  roles.
- The turn still ends in one structured handoff validated against the role's output schema.
- Edits are made in the task worktree during the turn. At collection, the bridge MUST compare the
  worktree with the turn's start: any change outside the write scope MUST be reverted, and MUST
  refuse the turn as `output-refused`, listing the paths.
- The inline bounds (1 MiB per file, 4 MiB per turn) MUST apply only to tool-less turns. An agentic
  turn reads on demand.
- Tool-less turns stay the default.
- *Rationale:* every mosaic role explores a source tree and runs `mcheck` within its turn. The
  single-reply runtime (`provider/claude.go:78`) can't host them.
- *Acceptance:* tests:
  - (a) an agentic turn reads a 20 MiB tree through the search tool and edits one in-scope file;
    the handoff validates and the edit lands;
  - (b) a write outside the scope is reverted, and the turn is refused with the path named;
  - (c) a shell call to the build tool by absolute path is denied by the hook;
  - (d) a tool-less role is launched with `--tools ""`, as today.

**FAE-RT-021 (MUST, new) Per-role turn budgets.** A role MAY declare `turn_budget:
{wall_seconds, max_assistant_turns}`. It overrides the bridge's instance-wide `--timeout` for that
role's turns (`cmd/fae-claude-bridge/main.go:22`).
- The bridge MUST count assistant turns from the provider's event stream, and stop the session once
  either bound passes.
- An exhausted turn MUST take a declared route: `retry_resume` (once, resuming the same provider
  session with its worktree changes kept) or a named stage (for example a short "close the gap"
  turn).
- Exhaustion MUST be recorded as its own outcome, separate from timeout, and MUST NOT penalize
  provider health.
- *Rationale:* mosaic budgets 45 min for a build and 15 min for a judge, and retries an exhausted
  build once from its files (`mosaic/docs/PIPELINE.md`, "Budgets").
- *Acceptance:* tests:
  - (a) roles with 45 min and 15 min budgets run in one instance, and each is stopped at its own
    bound;
  - (b) a turn past `max_assistant_turns` is stopped and routed to `retry_resume`, which resumes the
    same session id;
  - (c) provider health is unchanged after an exhaustion.

**FAE-RT-022 (SHOULD, new) Turn checkpoints.** An agentic turn SHOULD record its provider
session id and the worktree's tree hash durably at least once per bound (default 5 min).
- A turn interrupted by a crash, a quota limit (FAE-SCH-031) or a budget (FAE-RT-021) then resumes
  from that checkpoint with `--resume`, instead of being refused with its edits rolled back
  (`provider/README.md:147-159`) and its context invalidated (`LIVE.md:700`).
- Changes made after the checkpoint MUST be kept only if they are within the write scope.
- *Acceptance:* a turn killed 20 minutes in resumes in the same provider session, with its in-scope
  edits present, and finishes with one handoff.

**FAE-SEC-010 (MUST, new) Read and write path policies per role and per task.**
- A role MAY declare, and an admission MAY narrow:
  - `read` globs (allowed reads; default: the worktree);
  - `deny_read` globs;
  - `write` globs (default: the declared files).
- Deny MUST win. Task-level policies MUST only narrow role policies.
- Every tool, the repository listing block (`provider/README.md:50-56`) and search results MUST be
  filtered by the effective read policy.
- When a shell is granted, the policy MUST NOT rest on the hook alone. The session's filesystem view
  MUST omit denied paths, for example through a sparse worktree or a mount namespace.
- Read scope and write scope MUST be separate, so a file can be readable without being editable
  (unlike `provider/README.md:12`).
- Every refused read MUST be audited, naming the task, role and path.
- *Rationale:* mosaic's independence rules: builders never read any `BENCHMARK*.md`, `oracle*/` or
  `judge*/`, and judges never edit the model. Today these hold only because agents can read almost
  nothing.
- *Acceptance:* tests:
  - (a) a builder role with `deny_read: [BENCHMARK*.md, oracle*/**, judge*/**]` can't read, list or
    grep them, nor `cat` them from the shell, and each attempt is audited;
  - (b) a judge reads `fragments/**` but an edit to it is refused;
  - (c) a task-level policy that widens its role's is refused at admission.

**FAE-OPS-040 (MUST, new) Message delivery to a running task.** `fae message --task T`
and a controller verb `Notify(task, kind, body, from_task?)` MUST support delivery `next-turn` (as
Resume-with-context does today, `REQUIREMENTS.md:979`) and `in-flight`.
- For an agentic turn (FAE-RT-020), `in-flight` MUST deliver the message into the running session
  at its next tool boundary. Where the provider can't accept input mid-turn, the bridge MUST
  checkpoint (FAE-RT-022), end the turn, and resume the same session with the message prepended.
- `kind` is one of `breaking-change`, `cross-area-need` and `note`.
- `from_task` MUST be recorded as provenance, and the message MUST appear in both tasks' histories.
- A controller MAY relay between tasks without an operator message for `note`. The other kinds
  follow FAE-OPS-001's authority.
- *Rationale:* mosaic's coordinator routes a finished area's breaking changes to areas still
  running. At the next brief, the receiving area has already built on the old shape.
- *Acceptance:* tests:
  - (a) an `in-flight` message reaches a running agentic turn, and the handoff cites it;
  - (b) a `next-turn` message appears in the next brief only;
  - (c) both tasks' histories show the message with `from_task`.

**FAE-OPS-041 (MUST, new) Follow-up on a finished task.** A verb `FollowUp(task, text,
budget)` on a Done task MUST admit a new task:
- linked by `follow_up_of`;
- on the same workflow revision, with the same declared files and read policy;
- resuming the predecessor's task-bound provider session (its context moved to the new task's key,
  `provider/sessions.go:79-83`);
- with a turn budget (FAE-RT-021).

The Done task MUST stay unchanged. The follow-up lands through the same gates.
- *Rationale:* mosaic resumes finished agents for short fixes, such as a broken caller routed back,
  while their context is warm. A cold new task re-reads the whole area.
- *Acceptance:* a follow-up on a Done task resumes the predecessor's provider session id, edits only
  the declared files, lands, and leaves the predecessor's record byte-identical.

**FAE-OPS-042 (SHOULD, new) Fresh-context guarantee.** A role MAY declare `fresh: true`.
Its sessions MUST then never resume a provider context created for another task, whatever the slot
scope. It MAY still draw from a workflow-global cap pool.
- *Rationale:* blind measurers must be fresh agents, yet they should share the global cap with the
  builders. Today, workflow-global sessions resume across tasks (`LIVE.md:695-699`).
- *Acceptance:* two judge tasks in one workflow-global `fresh` role launch with different
  provider session ids, both counted in the role's pool.

**FAE-SCH-030 (MUST, new) Provider concurrency pools.** An instance MAY declare provider
pools: `{id, match: {provider, credential identity}, cap}`.
- Every agent session matching a pool counts against it. That includes every workflow id, role,
  Prophet session and instance sharing the host ledger.
- The pool MUST be a host-ledger lease (as FAE-HOST-031's shared ledgers are), granted in ready-set
  order (FAE-SCH-003), and MUST charge no attempt while waiting.
- A session MUST hold both its role slot and a pool lease.
- This amends FAE-SCH-005's "no host-wide role lease": a pool is a provider lease, not a role lease.
- Pools MAY be resized while the daemon runs, under the `capacity` class (FAE-CLI-044), and a
  reduction affects later grants only.
- *Rationale:* provider usage limits are per account, so mosaic caps about 10 agents across both
  models and all roles. Role caps can't express that across workflow ids (`REQUIREMENTS.md:586`).
- *Acceptance:* tests:
  - (a) two workflows with role caps of 8 each and one pool of cap 10 never run more than 10
    sessions;
  - (b) two instances sharing the ledger respect the same pool;
  - (c) a Prophet chat counts against the pool;
  - (d) lowering the cap from 10 to 6 stops nothing, and the next grant waits until 5 run.

**FAE-SCH-031 (MUST, new) Quota pauses.**
- When a turn's provider reports a usage limit with a reset time (for example Claude Code's
  `rate_limit_event` with status `rejected` and its reset field, `providerhealth/log.go:84-91`), the
  daemon MUST mark the matching provider pool (FAE-SCH-030), or else the (provider, model), as
  `quota-exhausted until T`.
- Until T plus a grace (default 60 s):
  - no turn on it MUST be dispatched or probed;
  - every task that would use it parks with reason `ProviderQuota`;
  - no attempt or recovery budget is charged;
  - the route-exhaustion escalation (`REQUIREMENTS.md:1735`) MUST NOT fire, and its clock starts
    at T.
- A turn cut off by the limit MUST keep its provider context and in-scope edits for resume
  (FAE-RT-022), and is re-dispatched first at T.
- Without a parsed reset time, the existing health hold applies, with probe turns spaced by
  exponential backoff (cap: 1 h).
- An operator verb `fae provider quota --pool P --until T|--clear` MUST set or clear the mark,
  audited.
- *Rationale:* session and weekly limits often stop mosaic runs. Today each one becomes 30 minutes
  of parks, escalations and lost turns, then a manual `fae resume` of every task.
- *Acceptance:* tests:
  - (a) a rejected limit with reset T+2h parks 12 tasks as `ProviderQuota`, launches no turn
    before T, escalates none, and dispatches the cut-off turn first at T, resuming its session;
  - (b) without a reset time, probes are spaced 1, 2, 4… minutes;
  - (c) the operator's `--clear` resumes dispatch in the next round.

**FAE-SCH-032 (SHOULD, new) Dispatch pause by scope.** A verb
`Pause(scope: instance | workflow | task-set | pool, reason)` SHOULD stop new dispatches in scope,
durably across restart. Turns in flight finish, or are checkpointed under FAE-RT-022, and nothing is
cancelled or charged. `Unpause` resumes them in ready-set order.
- *Rationale:* the operator pauses one model's round to give the other the provider budget, or
  pauses everything ahead of a known limit. Defer covers Pending tasks only
  (`REQUIREMENTS.md:973`).
- *Acceptance:* pausing a task set with 3 turns in flight lets them finish, dispatches nothing more
  in that set across a daemon restart, and resumes on unpause.

**FAE-WF-110 (MUST, new) Group landing (joint accept).** A controller MAY submit a
landing group: a set of tasks, each Done with its gates passed or waiting at its Integrate stage.
- The integration step MUST verify the union of their changes against the integration tip with the
  group's declared gate (a HostCommand vector).
- It MUST then land all or none.
- On failure, it MUST report the gate output to each member, and leave every member where it was.
- Members' write scopes MUST be disjoint, and overlap MUST be refused at submission.
- *Rationale:* mosaic accepts can depend on each other (area A's interface and B's caller of it). A
  joint accept passes only together.
- *Acceptance:* tests:
  - (a) two tasks whose gates fail alone and pass together land in one integration commit;
  - (b) a group whose union fails lands nothing, and both members get the report;
  - (c) overlapping scopes are refused.

**FAE-WF-111 (SHOULD, new) Accept-before-land staging.** A HostCommand stage MAY declare
`accept: <store>`. On a pass, the engine records the task's in-scope files as the accepted version
in an instance-level store.
- Other tasks' HostCommands MAY then read that store at a pinned version (`{{accepted}}`, a
  `relative-path` binding), without the files landing.
- The store MUST be content-addressed, and every read recorded as evidence.
- *Rationale:* `mcheck --stage --accept` lets each area gate against the others "as they last
  passed" (`mosaic/docs/PIPELINE.md`, "Staging") long before any merge lands.
- *Acceptance:* area B's gate reads area A's accepted fragment by version, and A's later accept
  doesn't change B's recorded evidence.

### 3.2 Updates to existing proposals

**FAE-WF-095 (update to `fae-hierarchical-workflows.md`).** Append:
- Each list element MAY carry per-branch `declared_files` and a read policy (FAE-SEC-010). They
  bind the branch instance's write and read scope.
- The validator MUST refuse a branch template whose write scope isn't parameterized by the item, so
  that branch instances can't share writable files.
- *Rationale:* mosaic's areas each own disjoint files named by the area id.

**FAE-WF-096 (update).** Replace the limit that branches hold no change producers
(`workflow/fan.go:194-195`), for `parallel: true` FanOuts whose branch write scopes are disjoint:
- each branch instance MAY hold change producers, runs in its own worktree forked at the visit's
  tree, and commits to its own ref;
- the join integrates the branch refs in branch order, or as one group (FAE-WF-110);
- per-path floor checks run per branch.

Add acceptance (e): two parallel branches each edit their own file, and the join lands both, in
branch order.
- *Rationale:* area agents are change producers, so parallel branches without changes don't cover
  mosaic's main fan-out.

**FAE-WF-097 (update).** Append: a SubWorkflow inside a parallel branch draws its sessions from the
parent's provider pool (FAE-SCH-030) and counts in the parent's footprint (FAE-SCH-019), so that N
children can't exceed the provider cap.

**FAE-WF-102 (update).** Append: tasks of a `produces: artifacts` template land through
HostCommand gates the template declares, with no `go test`, formatter or RED evidence floors and no
test-filter syntax. Their gates assert `exit_code == 0` on a named HostCommand without
`executed_count` (`workflow/GRAMMAR.md:25` applies to test-run evidence only).
- *Rationale:* landing gates are still Go-only (`HANDOFF.md:1626`).

**FAE-SCH-023 (update).** Add a `cap_scope` value `pool:<id>`. The role's cap is then enforced
against the provider pool (FAE-SCH-030) shared across workflow ids, rather than against a
per-workflow pool.

---

## 4. Suggested order for fae

1. FAE-RT-020 and FAE-SEC-010: without them, no mosaic role can run on fae. They also settle fae's
   own HOST-011 conflict.
2. FAE-SCH-030 and FAE-SCH-031: the shared cap and quota pauses that every long run hits.
3. FAE-RT-021, FAE-RT-022, FAE-OPS-040 and FAE-OPS-041: budgets, checkpoints, live messages and
   follow-ups.
4. FAE-WF-110 and the FAE-WF-102 update: joint accept, and artifact landing.
5. FAE-WF-095 to -097 as updated: in-template dynamic, parallel and change-producing fan-out. Until
   then, a controller-admitted task graph (section 2) covers the fan-out.

Until then, mosaic keeps running rounds with its own coordinator and `mosaic compose`
(`fae-hierarchical-workflows.md` §8).

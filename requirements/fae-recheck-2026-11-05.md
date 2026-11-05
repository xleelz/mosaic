# Fae re-check: can it run mosaic's model-building rounds? (2026-11-05)

| | |
|---|---|
| Status | Re-check of the two 2026-11-04 assessments, plus proposals marked in fae's `REQUIREMENTS.md`. Nothing implemented. |
| Target | `~/workplace/fae` working tree, HEAD `e547c03` plus 1,169 uncommitted entries before this edit (`git status --short`), read 2026-11-05. Includes the other process's edits up to 2026-11-04 23:51. |
| Re-checks | `fae-model-building-assessment-execution.md`, `fae-model-building-assessment-controller.md`. Background: `fae-hierarchical-workflows.md`, `fae-host-workflow-limit.md` |
| Edited in fae | `REQUIREMENTS.md` only: 104 lines added, 0 removed. 15 new proposed requirements, 5 amendment blocks and 1 conventions note (listed in §4). Nothing built, run, staged or committed. |

Paths are relative to `~/workplace/fae` unless they start with `mosaic/`. `REQUIREMENTS.md` line
numbers are the post-edit ones, unless a line is marked "pre-edit".

## Verdict

**Still no.** None of the blockers the two assessments found has been fixed. Every file that
carries one is unchanged since the assessments were written:
- `provider/claude.go`, `provider/task_scope.go`, `provider/sessions.go`;
- `workflow/fan.go`, `engine/fanout.go`;
- `effects/broker.go`, `providerhealth/`;
- `cmd/fae-claude-bridge/main.go`, `controlplane/store.go`.

The work since then went into four areas:
- Symphony, a Linear-driven intake and runner;
- legacy import;
- landing test shapes;
- the API and the terminal UI.

Symphony is the only change that touches agent tools, workspaces or long runs, and it does so
**outside** fae's workflow engine (§1.1). It doesn't remove any blocker, but it is evidence that
fae's owner is willing to run tool-using, multi-turn agents.

## 1. What changed in fae since 2026-11-04

Files modified on 2026-11-04 (21:53 and 23:51) include `api/api.go`, `api/schema.json`, `HANDOFF.md`,
`symphony/*`, `daemon/linear_sync.go`, `daemon/symphony_http.go`, `daemon/{subworkflow,land,drive_landing,live,import_legacy,admission}.go`,
`engine/{subworkflow,engine,control,job}.go`, `tracker/*`, `tui/*`, `cmd/fae/{symphony,serve,import_legacy}.go` and
`workflow/GRAMMAR.md`. There is no copy of yesterday's tree, so "new" below means one of two things:
first described today, or contradicting yesterday's citations.

### 1.1 Symphony (`symphony/`, `daemon/linear_sync.go`, `cmd/fae/symphony.go`)

**What it is.** An implementation of a "Symphony" service spec. It:
- polls an issue tracker (`linear`, `memory` or `fae` adapters, `cmd/fae/symphony.go:93-96`);
- reads a `WORKFLOW.md` with YAML front matter and a prompt template (`symphony/workflow.go:25-35`,
  `symphony/template.go:15`);
- creates one directory per issue under a workspace root, with shell hooks: `after_create`,
  `before_run`, `after_run` and `before_remove`, each run with `sh -lc` (`symphony/types.go:72-78`,
  `symphony/workspace.go:178`, `:299`).

It runs in two modes:
- **Standalone, `fae symphony`.** `EnableAppServerRunner: true` (`cmd/fae/symphony.go:117`). For each
  issue it launches a coding-agent **app-server** over JSON-RPC (`bash -lc <codex.command>`, or over
  SSH; `symphony/runner.go:164-166`). The agent runs in the issue workspace, with the agent CLI's own
  tools under a configurable sandbox and approval policy; the default approval policy is `never`
  (`symphony/runner.go:667-673`, `:735-741`). A run takes up to `max_turns` turns on one thread
  (default 20, `symphony/config.go:19`). Every turn after the first gets a fixed "continue" prompt
  (`symphony/runner.go:710-723`, `symphony/template.go:44-64`). The agent also gets the tracker's own
  tools, which are Linear GraphQL, issue and comment tools (`tracker/linear_tools.go:42-118`). A
  global cap, `max_concurrent_agents` (default 10), and per-state caps count only this
  orchestrator's in-memory `Running` map (`daemon/linear_sync.go:23`, `:999-1001`). Rate-limit data
  is only stored for display (`daemon/linear_sync.go:1599-1600`).
- **Embedded, `fae serve --workflow-md`.** The orchestrator only **admits a fae task** per issue
  through `DaemonTaskBridge.AdmitLinearIssue` (`daemon/daemon.go:946-951`,
  `daemon/linear_sync.go:265-327`), without the app-server runner. That task then runs through
  the normal tool-less engine.

**Does it address mosaic's gaps?**

| Gap | Symphony | Why it doesn't close the gap |
|---|---|---|
| Agent tools | Partly, outside the engine | Standalone only. There are no fae gates, kernel floors, declared-file scope, worktree, control-plane state or read policy, and no HOST-011 shims. The app-server protocol is the Codex one, and Codex isn't logged in on this host (`HANDOFF.md:1668`). |
| Snapshot outside the workspace | No | Workspaces are per issue under one root, populated by hooks. There is no read-only root with an identity. |
| Long runs | Partly, outside the engine | `max_turns`, `turn_timeout_ms` and `stall_timeout_ms` (`symphony/types.go:81-97`). Continuation prompts are fixed text, not coordinator messages. |
| Shared cap | No | Its cap counts only Symphony's own sessions, not fae engine sessions or other instances. |
| Quota | No | Limits are recorded, not acted on. |

### 1.2 API and schema

- New RPC `import_legacy` (`api/api.go:28`, `daemon/import_legacy.go`, task class). It is the start of
  FAE-CLI-051, which `HANDOFF.md` still lists as missing (`HANDOFF.md:1459`, `:1517`).
- `OutsideRepository` and `RepositoryFreeCredential` refuse a delegated credential file inside any
  repository or worktree (`api/api.go:72-101`, FAE-SEC-003).
- A typed `shutting-down` error, and the listener is closed on a failed start (`api/api.go:189-191`,
  `:278-284`).
- `api/schema.json` now lists every RPC (95 methods, `$defs.rpc*`). Nothing in it bears on
  mosaic's gaps:
  - `rpcAdmit` still has no parent and no typed inputs;
  - `rpcEvents` still takes only `after`, `include_retired` and `limit`;
  - there is no `Notify`, `FollowUp`, `Pause` or quota verb.

### 1.3 HANDOFF.md

The header still reads "Updated 2026-11-01 after wave 13" (`HANDOFF.md:3`). There is no wave 14
entry, and Symphony isn't mentioned. The only new content found is the claim that `test_shape` is
unified across admission, HostCommand execution and landing receipts (`HANDOFF.md:42`, `:1789`).
The open items mosaic depends on are unchanged:
- the HOST-011 conflict (`HANDOFF.md:1757`);
- landing gates beyond Go (`:1650`);
- concurrent FanOut (`:1649`);
- non-Go repositories (`:1626`).

### 1.4 Other code

- **Landing test shapes** `run`, `pkg`, `file` and `custom` (`daemon/drive_landing.go:21-35`). The
  `custom` shape only appends arguments to the base `go test` vector
  (`daemon/drive_landing.go:271-285`), and the policy is still `go test` (`controller/land.go:34`,
  `:44-46`). Landing remains Go-only.
- **SubWorkflow children** now get their parent's resolved file scope as declared files
  (`daemon/subworkflow.go:268-346`). Nesting is still capped at 4 (`daemon/subworkflow.go:19`), and
  self-selection is still refused (`workflow/subworkflow.go:30-31`).
- **Line shift.** The refusal of non-test commands moved from `daemon/live.go:667-669` to
  `:679-680`. Its content is unchanged.

## 2. Status of every blocker and gap

Status: **open** (unchanged), **changed** (something moved but the need is still unmet), **fixed**.
The "REQ" column gives the fae `REQUIREMENTS.md` proposal that now covers the gap (§4).

### 2.1 The nine confirmed blockers

| # | Blocker (assessment ref) | Status | Evidence today | REQ |
|---|---|---|---|---|
| 1 | Agents have no tools, and can't read a snapshot outside the workspace (exec Top 1, B1; ctl FAE-CTL-101, -102) | **open** (changed: Symphony runs tool agents outside the engine) | `provider/claude.go:78` (`--tools ""`); `provider/README.md:70-74`, `:84-86`; HOST-011 conflict `HANDOFF.md:1757`; one workspace per instance (glossary, `REQUIREMENTS.md:56`); §1.1 | RT-015, RT-016, HOST-011 amendment |
| 2 | Inline file limits, and reads equal writes (exec Top 2, B2, B3) | **open** | `provider/task_scope.go:13-15` (4 MiB per turn), 1 MiB per file; `provider/README.md:10-12` (scope files "read in full and the only editable files") | RT-017 |
| 3 | Gates can't run arbitrary commands, read output or write (ctl "Gates and decisions") | **open** | `daemon/live.go:679-680` ("unsupported non-test command artifact"); `effects/broker.go:438` ("host command mutated source tree") | WF-095 |
| 4 | Fan-out: fixed width, sequential, no change producers (exec Top 3, §1.1) | **open** | `workflow/fan.go:147-148` (2 to 16), `:191-196` (no change producers, no SubWorkflow); `engine/README.md:213-214`; `workflow/GRAMMAR.md:251`; still only planned, `HANDOFF.md:1649` | WF-096, WF-030 amendment |
| 5 | No live messages to running agents; no resume of a finished task (exec Top 4, B4) | **open** | OPS-010 rows (`REQUIREMENTS.md:1048-1049`; pre-edit `:978-979`): "never the turn in flight", "refused for Done"; `provider/sessions.go:79-83`; `rpcResumeWithContext` unchanged | OPS-033, OPS-034, OPS-010 amendment |
| 6 | Quota: no reset time, cut-off turn loses its work (exec Top 5, B6) | **open** | `providerhealth/README.md:11` (30-minute route bound); no reset parsing in `providerhealth/` or `provider/`; `provider/README.md:147-159`; `LIVE.md:700`; Symphony stores rate limits only (`daemon/linear_sync.go:1599-1600`) | RT-018, RT-019 |
| 7 | No per-stage read isolation (exec §1.2; ctl FAE-CTL-106) | **open** | `execution/executor.go:52-55` (scope per task); repository path list in every turn, `provider/README.md:50-56` | SEC-008 |
| 8 | Commit identity hard-coded, no scrub list, no push (ctl "Floors, commits") | **open** | `effects/broker.go:894` and `controller/land.go:335` (`Fae <fae@localhost>`); no content deny-list; Local push refused (FAE-MODE-002) | VCS-012, SEC-009, EXT-023, MODE-002 amendment |
| 9 | No concurrency cap across workflow ids (exec B7) | **open** (changed: Symphony's own cap of 10 covers only Symphony sessions) | FAE-SCH-005 "no host-wide role lease"; `daemon/live_admission.go:848-866`; `daemon/linear_sync.go:999-1001` | SCH-015, SCH-005 amendment |

**Fixed: none.** So no blocker was dropped from the proposals.

### 2.2 The other gaps from the execution assessment

| Gap | Status | Evidence today | Where it now stands |
|---|---|---|---|
| Per-role turn budgets (B8, FAE-RT-021) | open | `cmd/fae-claude-bridge/main.go:22` (one 5-minute `--timeout`) | folded into RT-015 |
| Turn checkpoints (FAE-RT-022) | open | `provider/README.md:147-159` | RT-019 |
| Fresh-context guarantee (B10, FAE-OPS-042) | open | `provider/sessions.go:79-83` | folded into OPS-034 |
| Dispatch pause by scope (FAE-SCH-032) | open | Defer covers Pending only (OPS-010) | folded into RT-018 |
| Joint accept, group landing (B5, FAE-WF-110) | open | `HANDOFF.md:19` serialized integration; `daemon/land.go` per task | not proposed in fae; stays in the mosaic assessment |
| Accept-before-land staging (FAE-WF-111) | open | none | not proposed in fae |
| Artifact or document landing (B9, FAE-WF-102 update) | **changed** (`pkg`, `file` and `custom` shapes) but still Go-only | `daemon/drive_landing.go:271-285`; `controller/land.go:34` | CTL-052, CTL-030 by reference |
| `Admit` with a parent and typed inputs (FAE-WF-099, -100) | open | `daemon/rpc.go:20-53`; `rpcAdmit` schema | not proposed (hierarchical proposal) |
| Nesting deeper than 4; self-recursion | open | `daemon/subworkflow.go:19`; `workflow/subworkflow.go:30-31` | not proposed |
| SubWorkflow child scope | **changed**: the child gets the parent's resolved scope | `daemon/subworkflow.go:324-346` | still no per-child scope |
| Host workflow limit (FAE-SCH-015 to -022 in `fae-host-workflow-limit.md`) | open | no workflow slot or footprint in the Go sources | not applied (see the ID note in §4) |

### 2.3 The other gaps from the controller assessment

| Gap | Status | Evidence today | Where it now stands |
|---|---|---|---|
| Authorizing messages expire after 24 h (FAE-CTL-111) | open | `controlplane/store.go:39-40` | not proposed in fae |
| Per-item decisions (FAE-CTL-108) | open | no `items_from` in `workflow/` | not proposed |
| Brief parameters (FAE-CTL-107) | open | `daemon/rpc.go:20-53` (free-text `Content`) | not proposed |
| Writing documents outside `implement` (FAE-CTL-104) | open | `workflow/workflow.go:577`; `workflow/fan.go:194-196` | partly in WF-096 (3) and RT-017; `phase: author` not proposed |
| Event filters and RunReport (FAE-CTL-112) | open | `rpcEvents` schema: `after`, `include_retired` and `limit` only | not proposed |
| Deny secret paths (part of FAE-CTL-109) | open | `workflow/protected_path.go:34` (the operator can still name such a file) | SEC-009 `deny_paths` |

"Not proposed" items stay as written in the two 2026-11-04 assessments. They are real gaps, but
outside the confirmed-blocker list this re-check was asked to carry into fae.

## 3. What mosaic can do on fae today

Nothing beyond the 2026-11-04 picture:
- a controller-admitted task graph with tool-less, single-reply agents;
- a shared cap only if every agent is one role of one workflow id.

Running agents under `fae symphony` would give them tools, but without any of fae's gates,
scope or durable state, so it is no better than mosaic's own coordinator and `mosaic compose`.
Those stay.

## 4. Edits to `~/workplace/fae/REQUIREMENTS.md`

Every edit is a block quote starting `> Proposed 2026-11-05 (mosaic model-building)`. A new
conventions bullet (line 12) explains that marker, so the owner can accept a proposal by removing
the quote markers, or drop it by deleting the block. No existing text was changed: `git diff
--numstat` gives 104 added and 0 deleted.

### 4.1 New requirements (15)

| ID | Section | Line | Covers | Mosaic source |
|---|---|---|---|---|
| FAE-WF-095 | §4.3 Stage primitives (after WF-036) | 396 | check commands: parsed output, `writes` exemption | ctl FAE-CTL-105 |
| FAE-WF-096 | §4.3 | 402 | FanOut width at run time, `parallel`, change-producing branches | exec §1.1, §3.2 (WF-095/-096 updates); ctl FAE-CTL-104 |
| FAE-SCH-015 | §5 (after SCH-014) | 655 | provider concurrency pools across workflow ids, Prophets and instances | exec FAE-SCH-030 |
| FAE-RT-015 | §6 (after RT-014) | 721 | agentic sessions: tool allowlist, write-scope revert, shims and hook, per-role turn budget | exec FAE-RT-020, -021; ctl FAE-CTL-101 |
| FAE-RT-016 | §6 | 727 | read roots outside the workspace, with identity, read-only | ctl FAE-CTL-102 |
| FAE-RT-017 | §6 | 733 | inline bounds as settings; read-only inputs; range reads and edits of large files | exec Top 2, B2, B3 |
| FAE-RT-018 | §6 | 739 | quota pause from the reset time, no escalation, operator mark and scoped pause | exec FAE-SCH-031, -032 |
| FAE-RT-019 | §6 | 745 | turn checkpoints: keep a cut-off turn's session and in-scope edits | exec FAE-RT-022 |
| FAE-VCS-012 | §7 (after VCS-011) | 799 | commit identity | ctl FAE-CTL-109 |
| FAE-EXT-023 (SHOULD) | §9.2 (after EXT-006) | 955 | declared-remote `git-push` effect in Local mode | ctl FAE-CTL-110 |
| FAE-OPS-033 | §10.2 (after OPS-014) | 1076 | `in-flight` and `next-turn` messages, with kinds and provenance | exec FAE-OPS-040 |
| FAE-OPS-034 | §10.2 | 1082 | follow-up on a Done task resuming its context; `fresh: true` roles | exec FAE-OPS-041, -042 |
| FAE-CTL-052 | §12.4 (after CTL-030) | 1389 | document-only landings gated by check commands | ctl FAE-CTL-113; exec B9 |
| FAE-SEC-008 | §16 (after SEC-007) | 1652 | read policy per role, stage and task; filtered path list; filesystem view | exec FAE-SEC-010; ctl FAE-CTL-106 |
| FAE-SEC-009 | §16 | 1658 | content policy (scrub list) at commit, land and push; `deny_paths` | ctl FAE-CTL-109 |

### 4.2 Amendment blocks (5) and the conventions note

| Amends | Section | Line | Says |
|---|---|---|---|
| Conventions | header | 12 | defines the "Proposed" block marker |
| FAE-WF-030 | §4.3 | 368 | the HostCommand and FanOut rows are extended by WF-095 and WF-096; no new primitive |
| FAE-SCH-005 | §5 | 608 | a provider pool is not a role lease; "no host-wide role lease" stays |
| FAE-MODE-002 | §9.1 | 917 | the engine may push only through EXT-023 |
| FAE-OPS-010 | §10.2 | 1056 | Resume with context gains `in-flight` (OPS-033); Done gains follow-up (OPS-034) |
| FAE-HOST-011 | §14.2 | 1548 | resolves the conflict: applies to sessions that can execute commands; an agentic shell session needs shims and the hook, or it doesn't launch |

In total there are 20 proposal blocks, 15 new and 5 amendments, plus the conventions note.

### 4.3 ID note

The IDs follow fae's own scheme, taking the next free number in each area of `REQUIREMENTS.md`:
WF-095, SCH-015, RT-015, VCS-012, EXT-023, OPS-033, CTL-052 and SEC-008. Mosaic's proposal IDs
(FAE-RT-020, FAE-SCH-030, FAE-CTL-101 and so on) are cited as sources and not reused.

**Collision to resolve before any older mosaic proposal is applied.** Two earlier unapplied
mosaic documents use IDs that now mean something else in fae's document:
- `fae-hierarchical-workflows.md` uses FAE-WF-095 to -104 and FAE-SCH-023;
- `fae-host-workflow-limit.md` uses FAE-SCH-015 to -022.

Fae's `REQUIREMENTS.md` is authoritative. Those documents must be renumbered from the next free
IDs when they are proposed. WF-096 here already absorbs the parallel and change-producing parts of
the hierarchical FAE-WF-095 and -096.

## 5. Suggested order for fae (unchanged in substance)

1. RT-015, RT-016, RT-017 and SEC-008, with the HOST-011 amendment. Without them, no mosaic role
   runs.
2. SCH-015, RT-018 and RT-019: the shared cap, and quota handling for long runs.
3. WF-095 and CTL-052: real gates and YAML landings.
4. OPS-033 and OPS-034: messages and follow-ups.
5. WF-096: in-template fan-out. Until then, a controller-admitted task graph covers it.
6. VCS-012, SEC-009 and EXT-023, before any commit leaves the machine.

## ID collision resolved (coordinator, 2026-11-05)

The REQUIREMENTS.md proposals above took fae's next free IDs (WF-095, WF-096, SCH-015). Mosaic's
earlier, unapplied proposals were renumbered so they no longer clash: in
`fae-hierarchical-workflows.md`, `fae-host-workflow-limit.md` and the two model-building assessments,
FAE-WF-095..104 are now FAE-WF-097..106 and FAE-SCH-015..023 are now FAE-SCH-016..024.

# Fae requirements amendment: host workflow limit

| | |
|---|---|
| Status | Proposed. Not implemented, and not applied to fae. |
| Target | `~/workplace/fae/REQUIREMENTS.md` (unchanged since `de4719f`; fae HEAD `e547c03`) |
| Prepared | 2026-10-30, for the mosaic composer |
| New | FAE-SCH-016 to FAE-SCH-023, FAE-CLI-044, one escalation kind, one park reason, four glossary terms, six defaults |
| Amended | FAE-SCH-004, -007, -010; FAE-WF-001, -090, -091; FAE-HOST-031; FAE-ROB-014, -041; FAE-OBS-004, -005; FAE-CLI-012; FAE-API-001 |

Another process owns fae's working tree, so this amendment lives here. It is written in REQUIREMENTS.md's form so that it can be pasted in.

## Summary

- A **workflow** is a running molecule. A molecule runs only while it holds a **workflow slot** in the host lease ledger (`~/.fae/host-ledger`). Every instance on the host shares that ledger.
- A slot is granted only while the slots held on the host are below **min(requested limit, host ceiling)**. The **requested limit** is the operator's or a controller's suggestion and can change while the daemon runs. The **host ceiling** is measured, and nothing can override it.
- The ceiling counts **commitments**, not only free memory. Each running workflow is committed its **footprint**: the session count derived from its template, times the per-session memory estimate, less the memory it already uses.
- A workflow that cannot get a slot does not start. Its task waits with a reason and loses no budget. Running workflows are never stopped when a limit falls.
- **Role capacity stays with each workflow.** Tasks that join a running workflow need no slot; that workflow's role caps and launch admission bound them.

## Decisions encoded (operator, 2026-10-30)

1. A "workflow" is a running molecule: one revision of a composed workflow.
2. Role caps stay workflow-specific. Tasks joining a running molecule are bounded by that workflow's role caps, not by the host limit.
3. The operator, a controller or the mosaic composer may request the number while the daemon runs. No request raises it above what the host can sustain.
4. A workflow the host cannot sustain fails to spawn; its task is not failed.

## Where each part goes

| Part | Location in REQUIREMENTS.md |
|---|---|
| Glossary rows | §1.2, after **Role slot** |
| FAE-SCH-016 to -022 | §5, after FAE-SCH-014 |
| FAE-CLI-044 | §11.4, after FAE-CLI-043 |
| Amendments | replace the quoted text in place |
| Defaults, kinds and parks | Appendix A and Appendix B |
| Open questions | §19, numbered from 12 |

---

## 1. Glossary additions

| Term | Definition |
|---|---|
| **Workflow slot** | A durable, owner-identified entry in the host lease ledger that permits one molecule to run. Every instance sharing the ledger counts against the same slots. |
| **Footprint** | The host capacity a workflow revision is expected to need for one task: a session count derived from its content, and the memory and panes those sessions need. |
| **Host ceiling** | How many workflows the host can sustain, computed by the daemon from measured host state and the footprints of running molecules. No request, verb, content or authority raises it. |
| **Host workflow limit** | The most workflow slots that may be held on the host at once: the smaller of the requested limit and the host ceiling. |

## 2. New requirements (§5, after FAE-SCH-014)

**FAE-SCH-016 (MUST)** A molecule MUST hold a workflow slot while it runs, and acquiring one MUST be the only way a molecule starts running. A molecule runs while at least one of its tasks is in a stage or Blocked. Pending, Escalated and terminal tasks do not run it, and SubWorkflow children are covered by FAE-SCH-022. No turn, host command, VCS step or external effect may be dispatched for a task whose molecule holds no slot. This MUST hold on every path that moves a task of a molecule without a slot into a stage: release from Pending (including a carried re-admission, FAE-WF-086), restart with information or resume of an Escalated task (FAE-OPS-010), migration (FAE-WF-093), and any later path. A slot MUST be acquired before the checkpoint that makes its molecule's first task dispatchable, and released after the checkpoint in which the molecule stops running. Within one round, the daemon MUST release any slot it holds for a molecule that is not running and has no release in progress, as FAE-ROB-015 requires for role slots. The host lease ledger is the sole authority for slots (FAE-GEN-011); the plane records each acquisition and release as an audit row and an event. Prophet sessions (FAE-OPS-032), loop schedules (FAE-RT-014), controller operations and daemon-internal operations neither need nor hold slots.
- *Rationale:* operator ruling (2026-10-30): the number of workflows running on a host is bounded by what the host can sustain. Today the instance molecule limit (FAE-SCH-007) is checked only on release from Pending, so restarting an Escalated task can start a molecule past it. A single acquisition point closes every path.
- *Acceptance:* tests: (a) with no slot free, a Pending task whose molecule holds none is not released, and its worktree is not moved to the integration tip; (b) a restart with information of the only Escalated task of a molecule without a slot is recorded and audited, but nothing is dispatched until a slot is acquired; (c) the same for a migration to a revision whose molecule holds no slot; (d) a fault injected between acquisition and the release checkpoint leaves no slot held after the next round; (e) when a molecule's last running task escalates, its slot is released within one round; (f) a Prophet chat and a loop iteration run with no slot free; (g) a search finds one slot-acquisition function, reached from every path in (a) to (c).

**FAE-SCH-017 (MUST)** Role capacity MUST stay with each workflow. A task released into a molecule that holds a slot MUST NOT need a slot of its own. Its concurrency MUST be bounded only as for any task within a molecule: by the role caps its workflow declares (FAE-SCH-005, -006), the tasks-in-flight limit (FAE-SCH-004) and launch admission (§14.1). A slot MUST NOT grant, pool, raise or lower any role cap, and the host workflow limit MUST NOT be applied to role slots, tasks or sessions.
- *Rationale:* operator ruling (2026-10-30): role caps are workflow-specific. The host limit bounds how many workflows run; each workflow's caps bound how much it does.
- *Acceptance:* tests: (a) with the host workflow limit at 1 and one running molecule whose workflow declares coder cap 4, four of its Pending tasks are released in one round and run four coder turns at once; (b) two molecules of different workflows, each declaring oracle cap 1, run two oracle turns at once; (c) changing the requested limit leaves every role cap and role-slot lease in the Leases read unchanged.

**FAE-SCH-018 (MUST)** A molecule MAY acquire a slot only while the slots held on the host are fewer than the host workflow limit: the smaller of the requested limit and the host ceiling (FAE-SCH-019). Each instance sharing the ledger MAY register one request (FAE-CLI-044). The requested limit is the smallest request of a live instance; −1 (the default) registers none, and with no request the host ceiling alone applies. FAE-SCH-007's instance and per-workflow limits MUST be checked at the same point. A change of request, or a fall in the host ceiling, MUST affect only later acquisitions. No running molecule may be stopped, parked or signalled because the count exceeds the limit; the count drains as molecules stop running.
- *Rationale:* a controller or the composer may suggest how many workflows run, but measured capacity always wins. The pane ledger already combines per-instance limits this way: the tightest live limit wins, and a reduction affects only future admission.
- *Acceptance:* tests: (a) a request of 8 against a ceiling of 3: three molecules acquire slots and the fourth waits with host_capacity; (b) a request of 2 against a ceiling of 5: the third waits with workflow_limit; (c) lowering the request from 4 to 2 with four molecules running stops none, and the next acquisition waits until three have stopped; (d) instances requesting 4 and 2 both see an effective request of 2, and once the second is proved dead, the next ledger access yields 4; (e) with no request, the limit equals the host ceiling; (f) an instance limit of 1 (FAE-SCH-007) holds back a second molecule of that instance with molecule_limit while the host limit has room.

**FAE-SCH-019 (MUST)** The host ceiling MUST be computed from measured host state and the footprints of running molecules, and nothing may override it: no request, verb, workflow content or authority class may give a slot to a molecule the ceiling refuses. With these definitions:

| Symbol | Meaning |
|---|---|
| `M` | memory available, from a host sample (FAE-HOST-001) taken in the current round |
| `S` | the effective soft memory floor (FAE-HOST-002) |
| `F_i`, `P_i` | the memory and pane footprint of slot holder `i` (FAE-SCH-020) |
| `U_i`, `L_i` | the resident memory and live panes of slot holder `i`'s sessions, its SubWorkflow children's included, as last published to the ledger by the slot's owner. The owner MUST refresh them at least once per staleness bound (default 60 s) while it holds slots; an older or unmeasured value counts as 0. |
| `H` | uncommitted memory: `M − S − Σ_i max(0, F_i − U_i)` |
| `H_p` | uncommitted panes (pane adapters only): `pane limit − live panes − Σ_i max(0, P_i − L_i)` |

a molecule with footprint `(F, P)` MAY acquire a slot only when `H ≥ F`, `H_p ≥ P`, memory available was read, and no pressure hold is in force. The pressure hold MUST be the one launch admission uses (FAE-HOST-005), so spawning resumes no earlier than launching. If pressure or load is unreadable, acquisition proceeds on the memory and pane terms and the gap is recorded (FAE-HOST-004). If memory available is unreadable, every acquisition MUST be refused, because a spawn commits capacity and needs positive evidence that the capacity exists. An unreadable ledger, or one whose lock is not obtained within a bound (default 1 s), MUST also refuse every acquisition. Each acquisition MUST be atomic under the ledger's cross-process lock (FAE-HOST-031) and MUST add its footprint to the committed sums before any later decision, whether in the same round or by another instance. Acquisition MUST NOT wait, back off or poll inside the drive (FAE-WF-032). The reported host ceiling MUST be the slots held plus `min(⌊H ÷ F_ref⌋, ⌊H_p ÷ P_ref⌋)`, where `(F_ref, P_ref)` is the footprint of the latest revision of the instance's default workflow.
- *Rationale:* whether the host can sustain one more workflow is a question about commitments, not only about the memory free now: a workflow that has just started uses little of what it will need. Counting every running workflow's unused footprint stops a burst of spawns from passing the check together and breaching the floor later, the failure FAE-HOST-006 fixed for launches. Treating an unmeasured workflow as using nothing is the conservative reading.
- *Acceptance:* tests with injected telemetry: (a) `M` 20 GiB, `S` 6 GiB, nothing running and every footprint 4 GiB: three molecules acquire slots in one round and the fourth waits with host_capacity; (b) one holder with `F` 4 GiB and `U` 1 GiB lowers `H` by exactly 3 GiB, and by 4 GiB once its `U` is stale; (c) a pressure hold entered by a launch refuses acquisition, and acquisition resumes only after two clear readings 30 s apart; (d) unreadable memory available refuses acquisition and reports telemetry_gap, while unreadable pressure with ample memory admits and records the gap; (e) a ledger kept locked by another process for 5 s holds back that round's spawns with host_ledger, and the round still completes; (f) two instances race for the last uncommitted 4 GiB and exactly one acquires, in every run of a repeated test, and a bounded model of concurrent acquisition never exceeds the limit (FAE-VER-009); (g) with 55 of 60 panes live and nothing committed, a molecule needing 5 panes is admitted and one needing 6 is refused; (h) firing controls (FAE-VER-001): a request, a workflow declaration and an operator verb each fail to obtain a slot the ceiling refuses.

**FAE-SCH-020 (MUST)** Every workflow revision MUST have a footprint, derived from its content by the validator (FAE-WF-090). Its session count `n` is the largest number of distinct agent sessions on any path from the start stage to Done. Each AgentTurn role counts once, each reviewer of a Review stage counts once, a Loop body counts once, and a SubWorkflow stage counts the session count of the child revision it pins. `n` is at least 1. The memory footprint is `n` times the effective per-session estimate: the per-pane reservation of FAE-HOST-006 in force at acquisition, default 0.7 GiB. The pane footprint is `n` under a pane adapter. Content MAY declare a larger session count, but a declaration smaller than the derived count MUST be refused at validation: content may tighten, never weaken (FAE-WF-070). The session count is pinned with the revision. Validation and simulation (FAE-WF-091) MUST report the derived and the effective footprint.
- *Rationale:* the composer authors templates, so a template's cost to the host must be known before any of it runs, and an author's claim must not undercut what the graph says.
- *Acceptance:* tests: (a) AgentTurn → Gate → Done has `n` = 1; (b) an AgentTurn followed by a Review of four dimensions with one reviewer each has `n` = 5; (c) a Loop body counts once whatever its cap; (d) a SubWorkflow stage that pins a child revision with `n` = 3 adds 3; (e) declaring 8 on a graph that derives 5 yields 8, and declaring 2 is refused with its document path; (f) `workflow validate` and `workflow simulate` print the derived and effective footprint.

**FAE-SCH-021 (MUST)** A spawn that cannot acquire a slot MUST fail closed without failing its task.
1. The task stays where it is. A Pending task stays Pending. A task that a restart or migration placed in a stage stays there with park reason WorkflowSlot (Appendix B).
2. The round records the task as withheld with exactly one reason: workflow_limit (the requested limit binds), host_capacity (the host ceiling binds), host_ledger (the ledger is unreadable or busy) or molecule_limit (FAE-SCH-007).
3. While a molecule waits, the drive MUST decide again within a bound (default 30 s), and whenever this instance releases a slot or its request changes. It MUST NOT poll while nothing waits (FAE-ARC-002).
4. Waiting MUST NOT consume an attempt or any bounded-recovery budget (FAE-ROB-017), MUST NOT escalate except under item 7, and MUST NOT hold a role slot, pane or heavy-op unit or move the task's worktree.
5. Molecules waiting for host capacity MUST be served in ready-set order (priority, then the time each began waiting; FAE-SCH-003) across every instance that shares the ledger. No molecule may take uncommitted capacity that a waiter ahead of it is waiting for.
6. A molecule withheld only by its own workflow's limit (FAE-SCH-007) MUST NOT hold back molecules of other workflows.
7. A molecule whose footprint exceeds the host's total memory less the soft floor, or exceeds the pane limit, can never acquire a slot. Its tasks MUST escalate with kind FootprintExceedsHost instead of waiting, and it MUST NOT hold back other waiters.
8. The reply of an admission, restart, resume or migration that leaves a task waiting MUST say so and name the reason.
9. Each molecule MUST produce one event when it starts waiting, one when its reason changes and one when it acquires a slot, not one per round (FAE-OBS-006). A molecule waiting longer than a bound (default 30 min) MUST raise one alert (FAE-OBS-005) naming the molecule, its footprint, the binding reason, uncommitted memory and panes, and the slot holders.
- *Rationale:* a workflow the host cannot sustain should not start, but the work is still wanted, so it waits where the operator and the composer can see why. Serving waiters in order, as the heavy-op pool does (FAE-SCH-011), keeps a large workflow from starving behind a stream of small ones. A workflow too large for the host must not hold the queue forever.
- *Acceptance:* tests: (a) a waiting task's attempt count and budgets are unchanged after 100 rounds; (b) withheld counts for each new reason appear in status and metrics; (c) with uncommitted capacity for one small molecule and a large molecule waiting ahead of it, the small one does not acquire a slot, but a large molecule held back only by its own per-workflow limit does not block it; (d) (c) also holds when the two waiters belong to different instances; (e) with no other event, a waiting molecule acquires a slot within 30 s of capacity becoming available; (f) a molecule needing 80 GiB on a 64 GiB host escalates with FootprintExceedsHost and does not block a 4 GiB waiter behind it; (g) a restart-with-information reply states that dispatch waits for a slot, and why; (h) a 30 min wait raises exactly one alert, and one wait produces exactly one start event and one acquisition event.

**FAE-SCH-022 (MUST)** A SubWorkflow child task MUST run on its parent's slot. It needs no slot of its own, does not count toward the host workflow limit, and its sessions count in its parent's measured usage. A molecule whose running tasks are all such children MUST NOT need or hold a slot; a task that is not such a child, released into that molecule, MUST acquire one for it. A parent's footprint includes the child revisions its SubWorkflow stages pin (FAE-SCH-020).
- *Rationale:* a parent keeps its slot while it waits for its child. If children needed slots of their own, a host at its limit with every slot held by a waiting parent would deadlock. The default workflow's Normal-mode code review is a SubWorkflow, so this is the shipped path, not a corner case.
- *Acceptance:* tests: (a) with the host workflow limit at 1, a parent that reaches a SubWorkflow stage runs its child to Done and then reaches Done itself; (b) with the limit at N, N parents each waiting on a child all reach Done; (c) an independent task released into a molecule running only children acquires a slot, and waits when none is free.

**FAE-SCH-023 (MUST)** At startup, before its first dispatch, the daemon MUST re-establish a slot for each of its running molecules, with an audit row each, exempt from the requested limit and the host ceiling. It MUST NOT dispatch for a molecule until that molecule's slot is re-established. Slots and requests whose owner is proved dead MUST be reclaimed, with an audit entry, on the next ledger access by any instance (FAE-ROB-014, FAE-HOST-031). Re-establishment MAY leave the host above its limit; later acquisitions then wait until the count falls below it. A request MUST survive restart and MUST be registered again before the first acquisition.
- *Rationale:* running work continues across a crash or a roll, as leases and pane reservations do, and capacity freed by a dead owner returns to the host without operator action.
- *Acceptance:* tests: (a) SIGKILL a daemon holding three slots, fill the host from another instance, then restart the first daemon: its three molecules resume with re-established slots, status reports the host above its limit, and no molecule starts anywhere until the count is below the limit; (b) a dead owner's slots and request are cleared on another instance's next ledger access; (c) a request of 3 is in force after a restart, before any acquisition.

## 3. New CLI verb (§11.4, after FAE-CLI-043)

**FAE-CLI-044 `fae workflow-limit` (MUST)**
- **Purpose:** read the host workflow limit, or request one.
- **Inputs:** none to read. To request: `--max N` and `--authorizing-message`. `--max -1` withdraws this instance's request.
- **Authorization:** reading is a read. A request needs the operator, or a controller citing an operator message that grants the `capacity` class (FAE-OPS-001, -002). The `capacity` class MUST authorise this request and nothing else, and no other class, `runtime` included, may authorise it.
- **Validation:** `N` is −1 or an integer from 1 to 1,000,000. Anything else is refused and nothing is stored. A request cannot carry or change host thresholds, the per-session estimate, the pane limit or role caps.
- **Outputs:**
  - this instance's request, with its principal, authorizing message and time;
  - the effective request and the instance that set it;
  - slots held on the host and by this instance;
  - uncommitted memory and panes, and the per-session estimate;
  - the host ceiling, the host workflow limit, and what limits it (`none`, `request`, `host_memory`, `pane_limit`, `pressure_hold`, `telemetry_gap` or `host_ledger`);
  - the molecules waiting for a slot, with footprint, reason and time waited.

  A request's reply also states whether the limit in force is below the request.
- **Failure modes:** invalid value or authority (exit 1, nothing stored); unreadable ledger (exit 1, nothing stored); daemon unreachable (exit 3).
- **Acceptance:** tests:
  - a request above the host ceiling exits 0, is stored, and reports the limit in force and its cause;
  - a request below the running count exits 0 and stops nothing;
  - a controller citing a message that grants only `runtime` is refused;
  - a controller citing a `capacity` message succeeds, and the same message is refused for RuntimeConfig, Drain and Shutdown;
  - every request is audited, takes effect at the next round (FAE-ROB-041) and survives restart (FAE-SCH-023);
  - `--json` output carries every output field.

## 4. Amendments to existing requirements

| Requirement | Change |
|---|---|
| FAE-SCH-004 | "the molecule concurrency limits, the host guard and the pane limit" → "the molecule concurrency limits, the host workflow limit (FAE-SCH-018), the host guard and the pane limit" |
| FAE-SCH-007 | Append: "Both limits MUST be checked when a molecule acquires its workflow slot (FAE-SCH-016) and MUST count slot-holding molecules, so that no path starts a molecule past them." |
| FAE-SCH-010 | "(cap, molecule limit, host guard, pane limit, edge, deferral, route unhealthy)" → "(cap, molecule limit, workflow limit, host capacity, host ledger, host guard, pane limit, edge, deferral, route unhealthy)" |
| FAE-WF-001 | After "molecule concurrency;" insert "an optional host footprint (a session count, FAE-SCH-020);" |
| FAE-WF-090 | Append: "It MUST also derive and report the revision's footprint (FAE-SCH-020), and refuse a declared footprint below the derived one." |
| FAE-WF-091 | Append: "The report MUST include the revision's footprint." |
| FAE-HOST-031 | "(heavy-op pool, pane totals)" → "(heavy-op pool, pane totals, workflow slots and requested workflow limits)" |
| FAE-ROB-014 | "role-slot leases, heavy-op leases, pane-accounting entries and locks" → "role-slot leases, heavy-op leases, workflow slots and requests, pane-accounting entries and locks" |
| FAE-ROB-041 | "(pane limit, heavy-op capacity, host thresholds, tasks-in-flight limit)" → "(pane limit, heavy-op capacity, host thresholds, tasks-in-flight limit, host workflow limit request)" |
| FAE-OBS-004 | After "withheld counts by reason;" insert "workflow slots held and molecules waiting by reason; slot wait from first withheld to acquisition, median and 90th percentile; uncommitted memory and panes;" |
| FAE-OBS-005 | After "dead edges," insert "molecules waiting for a workflow slot beyond a bound (default 30 min)," |
| FAE-CLI-012 | Append to Outputs: "host workflow limit (the outputs of FAE-CLI-044)" |
| FAE-API-001 | Leases row: "role slots, heavy ops, deployment leases and pane reservations" → "role slots, heavy ops, deployment leases, pane reservations and workflow slots (with footprints and measured usage)" |

## 5. Appendix additions

Appendix A (defaults):

| Area | Setting | Default |
|---|---|---|
| Scheduler | host workflow limit request | −1 (none: the host ceiling alone applies) |
| Scheduler | re-decision interval while a molecule waits for a slot | 30 s |
| Scheduler | workflow-slot wait alert | 30 min |
| Host | per-session estimate for footprints | the per-pane reservation (0.7 GiB) |
| Host | slot usage staleness | 60 s (an older value counts as 0) |
| Host | ledger lock bound for slot acquisition | 1 s |

Appendix B (escalation kinds):

| Kind | Raised when |
|---|---|
| FootprintExceedsHost | The workflow's footprint exceeds the host's total memory less the soft floor, or the pane limit, so it can never acquire a slot. |

Appendix B (park reasons):

| Park reason | Raised when |
|---|---|
| WorkflowSlot | The task is in a stage, but its molecule holds no workflow slot and cannot acquire one yet. |

## 6. Open questions (§19)

12. **Footprint basis.** Proposed: the longest path of one task (FAE-SCH-020). The alternative is the workflow's whole role capacity (the sum of its caps times the estimate). That would guarantee capacity at the workflow's peak, but it is far more conservative and undefined for caps of −1.
13. **Commitments at launch.** Launch admission (FAE-HOST-006) is unchanged here. Should a molecule that uses more than its footprint be kept from launching into capacity committed to another molecule?
14. **Joins versus spawns.** Tasks joining running molecules need no slot (FAE-SCH-017), so they can keep uncommitted capacity below a waiter's footprint indefinitely. Proposed: only the alert of FAE-SCH-021. The alternative: after the alert bound, hold back releases into running molecules of equal or lower priority.
15. **Operator versus controller requests.** Proposed: one request per instance, and the last writer wins. The alternative: an operator's request caps later controller requests until the operator withdraws it.
16. **Host thresholds.** `runtime-config` can set a hard memory floor of 0 (`hostguard.ValidConfig` accepts `Hard >= 0`), under the same `runtime` class as Drain and Shutdown. That is outside this amendment, but it is the remaining way to override host capacity. Should Appendix A's hard floors become fixed minimums?
17. **Instance molecule limit.** Keep `--max-molecules` (FAE-SCH-007) alongside the host request, or fold it into the request?

## 7. Traceability

| Operator requirement (2026-10-30) | Covered by |
|---|---|
| A global setting for how many workflows run in parallel on a host | FAE-SCH-016, -017 |
| Configurable while the daemon runs | FAE-CLI-044; FAE-ROB-041 (amended) |
| Takes host resources into account | FAE-SCH-019, -019 |
| The number can be suggested by a controller or the composer | FAE-CLI-044 (`capacity` class); FAE-SCH-018 |
| The suggestion never overrides host capacity | FAE-SCH-018, -018 |
| New workflows fail to spawn while the host cannot sustain them | FAE-SCH-016, -018, -020 |
| Role capacity stays with each workflow's role caps | FAE-SCH-017 |

## 8. Notes for the implementer (non-normative)

Line numbers refer to fae's working tree on 2026-10-30, which had uncommitted changes.

- The molecule limit is checked only for Pending tasks, at `daemon/drive.go:516` (`releasesMolecule`, `daemon/molecules.go:43`). It runs after `forkAtRelease` (`daemon/drive.go:492`), which moves the worktree to the tip even when the task is then held back. Acquire the slot before that fork.
- Restart and resume move an Escalated task into a stage without that check, at `daemon/task_controls.go:73-82`.
- `scheduler/panes.go` (per-instance limits where the tightest wins, owner proofs, reductions that affect only future admission) and `reconcileHost` in `scheduler/dynamic_host.go` are the pattern to follow for slots and requests.
- `RuntimeConfig`, `Drain` and `Shutdown` share the `runtime` class at `daemon/authority.go:31`. The request needs its own RPC, class and plane marker.
- Launch admission and its pressure hold live in `daemon/live_admission.go` (`acquire`, `pressure`).
- SubWorkflow children are separate tasks in their own molecules (`engine/subworkflow.go`, `ChildRef`).

## 9. How the mosaic composer uses this (non-normative)

- Read `fae workflow-limit --json` before planning, and size plans to the limit in force and to each template's footprint.
- Learn a template's footprint by validating it before installing it.
- Request a number only through a `capacity`-class grant, never `runtime`.
- Treat host_capacity waits as a planning signal: reprioritise, defer, or merge small plans into one template so they share one slot.

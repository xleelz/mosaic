# Fae requirements amendment: hierarchical, recursive workflows

| | |
|---|---|
| Status | Proposed. Not implemented, and not applied to fae. |
| Target | `~/workplace/fae/REQUIREMENTS.md` (fae HEAD `e547c03`, with about 1,145 uncommitted changes as of 2026-11-01) |
| Prepared | 2026-11-01, for mosaic's hierarchical ontology pipeline (mosaic `docs/DESIGN.md` §14) |
| New | FAE-WF-097 to FAE-WF-106, FAE-SCH-024, FAE-API-034 to FAE-API-036, FAE-CLI-055 to FAE-CLI-056, five glossary terms, four defaults, two escalation kinds |
| Amended | FAE-WF-030 (FanOut/FanIn and SubWorkflow rows), FAE-SCH-005, FAE-API-001, the `workflow-simulate` requirement |
| Depends on | `requirements/fae-host-workflow-limit.md` (FAE-SCH-016 to -022): recursion multiplies running molecules, and the host workflow limit bounds them |

Another process owns fae's working tree, so this amendment lives here. It is written in
REQUIREMENTS.md's form so that it can be pasted in.

## Summary

Mosaic builds an ontology of a system with a pipeline:
1. inventory;
2. skeleton;
3. a fan-out to N area agents;
4. reconcile;
5. oracle;
6. judges;
7. a blind measure.

The operator can then **zoom into** any component, and the same pipeline runs at that component's
scope as a child run. Each child receives the parent's contract and scenarios, and returns:
- a child ontology;
- timing that replaces the parent's;
- change requests against the parent's contract.

Children may be zoomed in turn, recursively, down to the runtime and machine levels.

Fae has the right building blocks: SubWorkflow with a parent link (`engine/subworkflow.go`), typed
content-addressed artifacts, controller RPCs and a resumable event stream. It can't run this
workflow today:

| Need | Fae today | Evidence |
|---|---|---|
| N parallel area agents, N decided by an earlier stage | FanOut branches are listed in the template (2–16) and run one after another | `workflow/fan.go:150-151`, `GRAMMAR.md:230, 250-251`, `engine/README.md:213` |
| N child runs at once | A fan-out branch can't contain a SubWorkflow; one child per stage visit | `workflow/fan.go:191`, `workflow/subworkflow.go:9-80` |
| The same pipeline on a component, recursively | A workflow can't select itself; nesting is refused past depth 4 | `workflow/subworkflow.go:30-31`, `daemon/subworkflow.go:17-36` |
| Zoom in after the parent finished | A child exists only while its parent's SubWorkflow stage waits; `AdmitParams` has no parent field | `daemon/rpc.go:20-50` |
| Results flowing up to a finished parent | Outputs map only into a waiting parent | `engine/subworkflow.go:98-180` |
| One template for every scope | No template parameters or typed workflow inputs; all scopes share one workflow id, so one oracle cap of 1 and one QA cap of 1 | REQUIREMENTS.md:592 (FAE-SCH-005), `daemon/rpc.go:36-50` |
| Workflows that produce artifacts, not commits | A child runs Local with its parent's file scope; the default workflow is built around commits | `HANDOFF.md:141` |

## Decisions encoded (operator, 2026-11-01)

1. The hierarchical ontology workflow is to run on fae, where fae can support it.
2. Zooming in is on demand and recursive. A child is the same pipeline at a smaller scope, linked
   to its parent.
3. Refinements are separate linked documents (a mosaic concern). Fae links the runs, not the
   documents.
4. Until fae supports this, mosaic runs a local emulator with the same interface, so that moving
   onto fae later changes nothing on mosaic's side.

## Where each part goes

| Part | Location in REQUIREMENTS.md |
|---|---|
| Glossary rows | §1.2, after **Workflow slot** (from the host-limit amendment) |
| FAE-WF-097 to -104 | §4, after FAE-WF-094 |
| FAE-SCH-024 | §5, after FAE-SCH-023 |
| FAE-API-034 to -036 | the API section, after FAE-API-033 |
| FAE-CLI-055, -056 | §11, after FAE-CLI-054 |
| Amendments | replace the quoted text in place |
| Defaults and kinds | Appendix A and Appendix B |
| Open questions | §19, numbered after the host-limit amendment's |

---

## 1. Glossary additions

| Term | Definition |
|---|---|
| **Run tree** | The tasks linked by parent links, rooted at a task with no parent. A child's place in the tree is fixed at admission. |
| **Workflow signature** | A template's declared, schema-typed `inputs` and `outputs`. Admission and SubWorkflow bind and check them. |
| **Recursion budget** | A template's declared bounds on its own recursion: maximum depth, maximum descendants per tree, and maximum children per stage visit. |
| **Detached child** | A child task admitted by a controller with a parent link to a task that may already be terminal, as opposed to a SubWorkflow child that its waiting parent started. |
| **Change request** | A typed artifact that a child addresses to an ancestor, proposing a correction to that ancestor's outputs or contract. |

## 2. New requirements (§4, after FAE-WF-094)

**FAE-WF-097 (MUST)** A FanOut MUST accept `branches_from`: a binding to a list-typed artifact
recorded earlier in the task. Instead of fixed branches, it then declares one `branch` sub-graph.
- At the stage's visit, the engine MUST create one branch instance per list element, in list
  order, binding the element as the branch's input `item` (typed by the list's item schema).
- The template MUST declare `max_branches` (default 64, upper bound 1024). A list longer than
  `max_branches` MUST fail the stage with the declared failure route. It is never truncated.
- An empty list MUST evaluate the join rule over zero branches: `all` passes; `any` and `k-of-n`
  fail.
- Kernel floors and graph properties MUST be proved once, over the branch sub-graph. The validator
  MUST NOT need the runtime width.
- Fixed `branches` remain valid, and unchanged.
- *Rationale:* mosaic's area count comes from its inventory stage (11 areas for a gateway platform, 13 for
  VS Code, 9 for vLLM), so it isn't known when the template is written.
- *Acceptance:* tests:
  - (a) a list artifact of 11 items yields 11 branch instances, each bound to its item, in order;
  - (b) 70 items with `max_branches: 64` fail the stage through its failure route, and no branch
    is dispatched;
  - (c) an empty list passes `all` and fails `any`;
  - (d) the validator refuses a branch sub-graph that violates a kernel floor, without any list
    artifact present;
  - (e) a template with fixed `branches` validates, and runs as before.

**FAE-WF-098 (MUST)** FanOut branch instances MUST be able to run concurrently.
- A FanOut MAY declare `parallel: true`. Its branch instances are then dispatched concurrently,
  bounded only by role caps (FAE-SCH-005, -006, -023), tasks in flight (FAE-SCH-004), launch
  admission (§14.1) and the host workflow limit (FAE-SCH-018) where it applies.
- The join MUST be evaluated once every branch instance is terminal, or as soon as the join rule
  is decided (`any` passing, or `all` failing). The remaining instances are then cancelled, and
  their cancellation recorded.
- Branch outputs MUST be collected into the join artifact in branch order, whatever order they
  finish in.
- Without `parallel: true`, branches run one after another, as today.
- *Rationale:* N area agents in parallel is the point of the fan-out; running them one at a time
  multiplies wall-clock time by N.
- *Acceptance:* tests on the scripted adapter:
  - (a) 4 branches with a coder cap of 4 dispatch 4 turns in one round;
  - (b) with a cap of 2, at most 2 are in flight at any time;
  - (c) an `any` join cancels the others once one branch passes, and records the cancellations;
  - (d) the join artifact lists outputs in branch order when branches finish in reverse order.

**FAE-WF-099 (MUST)** A FanOut branch MUST be able to contain a SubWorkflow stage. With
FAE-WF-097 and -096, one stage visit can then start N child tasks concurrently.
- Each child MUST get the id `<parent>.<stage>.<visit>.<branch-index>` and a parent link. Each
  child's outputs MUST map into its own branch's outputs.
- `workflow/fan.go:191`'s refusal MUST be removed.
- *Acceptance:* tests:
  - (a) a dynamic FanOut of 3 branches, each a SubWorkflow, admits 3 children with distinct ids
    and parent links, runs them concurrently when allowed, and joins their mapped outputs in
    branch order;
  - (b) one child failing routes only its own branch through the SubWorkflow failure route.

**FAE-WF-100 (MUST)** A workflow MUST be able to select its own workflow id in a SubWorkflow stage
(self-recursion), when its template declares a `recursion` budget:
`{max_depth, max_descendants, max_children_per_visit}`.
- Admission MUST refuse a child that would exceed any bound, and route the parent's stage through
  its failure route with the reason `recursion_budget`.
- `max_depth` MUST NOT exceed the instance ceiling (default 8; FAE-SCH-024 bounds caps across the
  tree). For recursive templates, it replaces the hard-coded nesting limit of 4.
- Mutual recursion between templates MUST be refused, unless each declares a budget. The depth and
  descendant counts are then counted across the whole run tree.
- Templates without `recursion` keep today's refusal of self-selection and of nesting deeper
  than 4.
- *Rationale:* zooming into a component runs the same pipeline at a smaller scope, and a
  component's parts can be zoomed in turn.
- *Acceptance:* tests:
  - (a) a template with `max_depth: 3` admits a child and a grandchild, and refuses a
    great-grandchild with `recursion_budget`;
  - (b) `max_descendants: 5` refuses the sixth descendant anywhere in the tree;
  - (c) a template without `recursion` that selects itself is refused by the validator, as today;
  - (d) the validator refuses `max_depth` above the instance ceiling.

**FAE-WF-101 (MUST)** A template MAY declare a workflow signature: `inputs` and `outputs`, each a
map of names to JSON Schemas.
- `Admit` (FAE-API-034) and SubWorkflow input mappings MUST bind every required input, and the
  values MUST validate against the schemas before any stage runs. A failure refuses admission,
  listing every error.
- The output mapping of a SubWorkflow MUST be checked against the child's declared outputs at
  validation time.
- Inputs MUST be readable by stages as artifacts, with provenance `input:<name>`.
- *Rationale:* the scope, the parent's contract and the parent's scenarios are a child's inputs.
  Passing them as free text in `Content` can't be validated, and makes every scope look the same
  to the template.
- *Acceptance:* tests:
  - (a) an `Admit` missing a required input is refused, and the error names it;
  - (b) a SubWorkflow whose output mapping names an output the child doesn't declare is refused by
    the validator;
  - (c) a stage reads an input as an artifact with provenance `input:scope`.

**FAE-WF-102 (MUST)** A controller MUST be able to admit a **detached child**: a task with
`parent_task` set to an existing task in any state, Done included.
- The link MUST be recorded at admission, and MUST appear in the run tree, in events and in task
  history.
- The parent's recorded artifacts MUST be readable by the child as inputs, by mapping
  (`from_parent: <artifact name>`), with provenance pointing at the parent's artifact ids.
- The child's outputs MUST be recorded as artifacts in the run tree's lineage. They MUST NOT
  mutate the parent's recorded artifacts or state.
- Recursion budgets (FAE-WF-100) MUST count detached children.
- *Rationale:* an operator zooms into a component after the parent run has finished, often much
  later. The parent can't be kept waiting in a SubWorkflow stage for that.
- *Acceptance:* tests:
  - (a) a detached child of a Done task is admitted, reads the parent's `contract` artifact by
    mapping, and the tree read shows the link;
  - (b) the parent's artifacts are byte-identical before and after the child runs;
  - (c) a detached child that exceeds the parent template's `max_depth` is refused.

**FAE-WF-103 (MUST)** A child MUST be able to address a **change request** to an ancestor: an
artifact of a declared schema, with `target: {task, artifact}`.
- Recording one MUST emit an event and appear in the target's task history.
- It MUST NOT change the target.
- A controller (or the operator) MAY act on it: by admitting a new run of the target's workflow
  with the request as an input, or by recording a decision that declines it.
- If the target is waiting in a SubWorkflow stage for this child, the request MAY also be returned
  in the child's mapped outputs.
- *Rationale:* a child that finds its parent's contract wrong must say so, and the parent's owners
  decide. Silent divergence between levels is what mosaic is built to prevent.
- *Acceptance:* tests:
  - (a) a child records a change request against its Done parent's `contract`; the event and the
    parent's task history show it, and the parent's artifacts are unchanged;
  - (b) a controller admits a new run of the parent's workflow with the request bound as an input,
    and the tree records both links.

**FAE-WF-104 (MUST)** A template MAY declare `produces: artifacts`. Its tasks then produce only
artifacts, written under a declared output directory, and no commits.
- Such templates MUST NOT need VcsCommit, Merge or Integrate stages.
- Kernel floors for code-bearing classes (protected commit, test first) MUST NOT apply to them.
- Their file scope MUST be limited to their declared inputs (read) and their output directory
  (write).
- A SubWorkflow or detached child of such a template MUST get its own output directory, under the
  parent's, named by its task id.
- *Rationale:* building an ontology writes model documents and reports, not code changes. A child
  shouldn't run Local with its parent's code-change scope.
- *Acceptance:* tests:
  - (a) a `produces: artifacts` template made only of AgentTurn and Gate stages validates and runs
    to Done;
  - (b) a turn that writes outside the output directory is refused;
  - (c) a child's outputs land under `<parent output dir>/<child task id>/`.

**FAE-WF-105 (MUST)** `workflow-simulate` MUST simulate SubWorkflow children, recursive and
detached included, and dynamic FanOuts.
- Child outputs, list widths and change requests come from scripted values in the scenario.
- The simulation MUST report the run tree it would create, and every budget refusal.
- *Acceptance:* a scenario that scripts a 3-item area list and one recursive zoom yields a
  simulated tree of 1 root, 3 parallel branches and 1 child, with the child's mapped outputs in the
  root's join artifact.

**FAE-WF-106 (SHOULD)** The engine SHOULD expose the run tree's recursion depth to gates and briefs
as a read-only value (`tree.depth`), and the remaining budget (`tree.remaining_descendants`), so
that a template can stop zooming deeper by itself.
- *Acceptance:* a gate on `tree.depth < 2` stops a recursive template from admitting a child at
  depth 2, through its routed arm, without a budget refusal.

## 3. New requirement (§5, after FAE-SCH-023)

**FAE-SCH-024 (MUST)** A recursive or detached template MAY declare a `cap_scope` per
workflow-global role:
- `workflow`: as today, shared by every molecule of the workflow id across revisions;
- `tree`: shared within one run tree;
- `task`: one cap per task.

The default MUST stay `workflow`.

Whatever the declared scope, the sum of concurrent sessions MUST stay bounded by tasks in flight,
launch admission and the host workflow limit.
- *Rationale:* every scope of a hierarchy runs the same workflow id (FAE-WF-100). With
  `workflow`-scoped caps of oracle 1 and QA 1, every component zoomed anywhere on the host would
  queue behind one oracle. `tree` keeps the deliberate bottleneck within one hierarchy, and lets
  separate hierarchies proceed.
- *Acceptance:* tests:
  - (a) two run trees of the same workflow with `oracle: {cap: 1, cap_scope: tree}` run two oracle
    turns at once, while a second oracle turn within one tree waits;
  - (b) with the default scope, behavior is unchanged.

## 4. API and CLI

**FAE-API-034 (MUST)** `Admit` MUST accept:
- `inputs` (an object, validated against the workflow signature, FAE-WF-101);
- `parent_task` (FAE-WF-102);
- `from_parent` (a map of input names to parent artifact names).

Refusals MUST list every signature and budget error.

**FAE-API-035 (MUST)** A read RPC `Tree(task)` MUST return the run tree containing the task:
- each node's id, workflow id and revision, parent, state, depth and budget use;
- its mapped outputs;
- the change requests addressed to it.

It MUST be consistent with the event stream at a stated sequence number.

**FAE-API-036 (MUST)** Events MUST carry `parent_task` and `tree_root` for every task in a tree. A
controller MUST be able to subscribe to one tree's events by `tree_root`.

**FAE-CLI-055 (MUST)** `fae tree <task>` MUST print the run tree: states, depths, and the change
requests per node.

**FAE-CLI-056 (MUST)** `fae admit` MUST accept `--input name=@file.json` (repeatable),
`--parent <task>` and `--from-parent input=artifact`.

## 5. Amendments

- **FAE-WF-030, the FanOut / FanIn row.** Required configuration becomes: "branches, or
  `branches_from` with one `branch` sub-graph and `max_branches` (FAE-WF-097); `parallel`
  (FAE-WF-098); join rule (all, any, k-of-n)."
- **FAE-WF-030, the SubWorkflow row.** Required configuration becomes: "workflow selector (the
  workflow's own id allowed under FAE-WF-100); input mapping (checked against the child's
  signature, FAE-WF-101); output mapping; may appear inside a FanOut branch (FAE-WF-099)."
- **FAE-SCH-005.** Append: "unless the role declares another `cap_scope` (FAE-SCH-024)."
- **FAE-API-001.** Add `Tree` to the read RPCs, and add the new `Admit` fields.
- **The `workflow-simulate` requirement** (REQUIREMENTS.md:550). Append: "including SubWorkflow
  children, recursion and dynamic FanOuts (FAE-WF-105)."

## 6. Appendix additions

- **Appendix A (defaults):**
  - `max_branches` 64 (upper bound 1024);
  - the instance recursion ceiling 8;
  - `cap_scope` `workflow`;
  - `parallel` false.
- **Appendix B (escalation kinds):**
  - `recursion_budget`: a child was refused for exceeding a declared budget;
  - `change_request_pending`: a task's run can't continue until an operator or controller decides
    a change request addressed to it, for templates that declare a gate on pending requests.

## 7. Open questions (§19)

- **Run-tree retention.** Should a run tree's artifacts be kept as long as any descendant may
  still be zoomed? Today retention is per task.
- **Cross-host trees.** Should children be able to run on another host once cross-host support
  exists? For now, a tree runs on one host.
- **Budget accounting.** Should a change request that triggers a new parent run start a new tree,
  or extend the old one (and count against its budget)?

## 8. Mosaic's stopgap until fae implements this

Mosaic runs a local emulator, `mosaic compose` (mosaic `docs/DESIGN.md` §14.9). It implements this
amendment's semantics with the same names, so moving onto fae later changes nothing on mosaic's
side:
- dynamic parallel FanOut;
- SubWorkflow inside branches;
- recursion budgets;
- workflow signatures;
- detached children;
- change requests;
- artifact-only output directories;
- the run tree.

Each AgentTurn runs a headless Claude Code agent. The emulator doesn't enforce fae's kernel floors,
leases or authority model, so it is for development, not a replacement.

# The generation pipeline as a compose workflow

`ontology-pipeline.yaml` encodes `docs/PIPELINE.md` as one recursive workflow for
`mosaic compose` (DESIGN §14.9, §14.11). The same template builds a whole repo at level `system`,
or one component of a parent model at a deeper level, with the parent's contract.
`ontology-pipeline-light.yaml` is its light profile for small scopes, with the same inputs and
outputs. `zoom.yaml` starts either one on a component of a finished parent run. The briefs point
at `../templates/` and at the runbook instead of copying them.

**The stage graph.** A stage starts as soon as its bindings exist, so independent stages overlap:

```
inventory -> skeleton -+-> areas -> reconcile -> refix -> merge -> merge_gate -+
                       '-> benchmark (beside the builds)                       |
+------------------------------------------------------------------------------+
+-> conformance -> contract   +-> judges (one per benchmark group)
+-> refinement                +-> measure_judges (one per blind group) -+
+-> oracle_sample -> oracle   '-> measure_sample -> measure_oracle -----+-> measure
all of them -> results -> check -> check_gate -> zoom_known -> children
```

- The benchmark depends only on the skeleton and reads no model; builders never read it. It
  runs beside the area builds instead of before them.
- After the merge gate, the oracle, the judges, both halves of the blind measure, the
  conformance check and the refinement turn all start together. The contract review follows the
  conformance command. `refinement` only verifies the link the skeleton predeclared, and edits
  nothing, so nothing else waits for it.
- The blind measure is no longer one agent. Fresh agents score one blind benchmark group each
  (`measure_judges`) or translate one area of the fresh sample each (`measure_oracle`). Then a
  short `measure` turn on a cheaper model sums them into the same `measure` artifact as before.

| Stage(s) | Kind | Runbook stage |
|---|---|---|
| `inventory` | agent_turn (coordinator) | 1 |
| `skeleton` | agent_turn (coordinator) | 2 and 3, the 4b samples, `BRIEF.md`; for a child, `refines`, `implements` seams and the projected acceptance scenarios |
| `benchmark` | agent_turn (benchmark, builds nothing) | `BENCHMARK.md` and the held-back `BENCHMARK1.md` (groups of at most 5 cases each), beside the fan-out |
| `areas` | fanout over `skeleton.areas`, parallel, one `build` turn per area; it reports done only once `mcheck --stage <its fragment> --accept` passes | 4, 4b |
| `reconcile`, `refix`, `merge`, `merge_gate` | turn, fanout over the relaunched areas (each `fix` stages its fragment again), command, gate | 5 |
| `refinement`, `conformance` | turn, command (`check --refinement --apply-timing <out>/timing.json`) | DESIGN §14.3, §14.4 |
| `oracle_sample`, `oracle` | command, fanout over areas | 6 |
| `judges` | fanout over `benchmark.groups` | 7 |
| `measure_sample`, `measure_judges`, `measure_oracle`, `measure` | command; fanout over `benchmark.blind_groups`; fanout over areas of `oracle1/sample.json`; a short summing turn | the blind measure of the round |
| `contract`, `contract_agrees`, `file_change_requests` | turn, gate, change_request (only when routed) | §14.3, "Rectifying up" |
| `results` | agent_turn | 8 |
| `check`, `check_gate` | command (the full gate), gate | every hand-off |
| `zoom_known`, `children` | gate, fanout of `subworkflow: self` | zooming in during the run |

**Inputs.**
- `scope`: `{repo, paths}` for a repo; `{repo, component, paths}` for a component.
- `contract`: `null` at the root. For a child, `{parent: {task, ontology, document}, component,
  interfaces, scenarios}`.
- `level`: `system` by default.
- `zoom`: component ids to refine once this run passes its gate (default `[]`).

**Outputs.**
- `ontology`: the document path, name, level, scores, and the components with their code paths,
  interfaces and crossing scenarios, which is what a zoom reads.
- `refines`: the link, the `implements` pairs and the refinement candidates (§14.7).
- `timing`: the conformance report.
- `change_requests`: the requests. Those with `target: parent` are also filed against the parent
  run.

Each run's workspace is its `out/` directory. A child's sits under its parent's, by task id.

```sh
# a whole repo
mosaic compose run .claude/skills/mosaic-generate/compose/ontology-pipeline.yaml \
  --input scope=@scope.json --executor claude --max-parallel 8
# the same, zooming into two components once the root passes its gate
mosaic compose run .claude/skills/mosaic-generate/compose/ontology-pipeline.yaml \
  --input scope=@scope.json --input zoom=@zoom.json --executor claude
# later: zoom into one component of the finished run <root>
mosaic compose run .claude/skills/mosaic-generate/compose/zoom.yaml --parent <root> \
  --from-parent parent=ontology --from-parent parent_scope=scope --from-parent parent_level=level \
  --input component=@component.json --executor claude
# the same zoom with the light profile ("light" in light.json)
mosaic compose run .claude/skills/mosaic-generate/compose/zoom.yaml --parent <root> \
  --from-parent parent=ontology --from-parent parent_scope=scope --from-parent parent_level=level \
  --input component=@component.json --input profile=@light.json --executor claude
# a small scope on its own, with the light profile
mosaic compose run .claude/skills/mosaic-generate/compose/ontology-pipeline-light.yaml \
  --input scope=@scope.json --input level=@level.json --executor claude
mosaic compose tree <root> --stats; mosaic compose requests <root>
```

**Budgets and failures.** Every `agent_turn` has a `budget: {max_turns, timeout_min}` (DESIGN
§14.13). The `claude` executor passes `--max-turns` when the CLI has it. Otherwise it runs the
session with `--output-format stream-json --verbose`, counts the main session's assistant turns
as the events arrive, and kills the session's process group once the count passes `max_turns`
(DESIGN §15.7). Running out fails the turn with reason `budget`, and `on_fail` routes every turn's
failure once:

| Turn | Budget (full) | On failure |
|---|---|---|
| `inventory`, `reconcile`, `results` | 30 min | retry (`<stage>_retry`), resuming from the files left in the workspace |
| `skeleton` | 45 min | retry |
| `benchmark` | 30 min | retry |
| `build` | 45 min | `build_retry`, 30 min, resuming the fragment |
| `fix` | 30 min | `fix_retry`, 20 min |
| `refinement`, `contract` | 15 min | retry |
| `judge`, `blind_judge` | 15 min | `*_gap`, 10 min: keep the scored cases, score the rest `missing` with cause `budget` |
| `translate`, `blind_translate` | 20 min | `*_gap`, 10 min: keep the verdict rows, count the rest as `unscored` |
| `measure` (summing) | 5 min, `sonnet` | retry |

A retry that fails too fails the run. A recorded gap is unmeasured, not failed: `results` lists
gaps apart from the scores, with each turn's cost from `mosaic compose tree <task> --stats`. A
shared brief opens with a retry note that renders only in the handler (`with index . "failure"`),
so the primary stage doesn't bind `failure`.

## Profiles: full or light

`ontology-pipeline-light.yaml` takes the same inputs and produces the same outputs, with the same
recursion. Its zooms recurse into itself. It drops stages, not just cases (DESIGN §15.7): 15
top-level stages against the full profile's 34.

```
inventory -> skeleton -> areas -> reconcile (merge + refinement link) -+
+----------------------------------------------------------------------+
+-> conformance -> contract -> contract_agrees [-> file_change_requests]
+-> oracle   +-> judges   +-> measure
all of them -> results -> check -> check_gate -> children
```

Compared with the full profile:
- **No benchmark stage.** The skeleton turn writes the cases from the docs and well-known
  behavior: about 8 in one group, and 4 to 6 held back. It also draws the oracle and blind
  samples, so there are no sample commands either. Area agents never read either file.
- **Reconcile and merge are one turn.** There's no refix fan-out. The coordinator applies the
  reconciliation decisions to the owning areas' files itself, runs the merge command until it
  exits 0 (`merge_exit` must be 0, or the turn fails), and verifies the refinement link in the
  same turn: its artifact is `refines`. The `check` stage reruns the same gate independently
  before the children start.
- **Judging and measuring.** One judge, and one blind-measure turn that judges the few blind
  cases and translates a small fresh sample (`--min-size 5`). Each is a fanout over its single
  case group, so its gap turn sits inside the branch.
- **Retries.** Coordinator turns have no retry stage. The executor still retries a bad artifact
  once, and a turn that runs out of budget fails the run. Builds keep `build_retry`. The oracle,
  the judge and the blind measure keep their gap turns.
- **Gates.** `check_gate` also checks that every `zoom` id names a component.
- **Models.** Mechanical turns run on `sonnet`: the inventory and the oracle translations.
  Builds, judges and the coordinator's judgment turns keep the default model.
- **Budgets.** Smaller, for example 40 minutes per build and 15 per judge.

**Which to pick:**
- **Light:** the scope is one or two files, or a single component whose code fits one to three
  areas and maps to a handful of test files (a metering component: 9 files, 83 test functions).
  Use it for zooms into small components, and for quick iterations on a profile or brief.
- **Full:** a whole repo or a service with several separable areas, or any run whose score will
  be reported or compared across rounds. Eight cases give a coarse score, and one judge has no
  second opinion. The full benchmark's several groups and per-group blind judges measure more
  finely.

`zoom.yaml` takes `--input profile=@p.json` with `"full"` (the default) or `"light"`. Its
`full` gate passes for `full`; for `light`, its failure routes to the `pipeline_light`
subworkflow. That gate shows as failed and routed in `mosaic compose tree`, which is expected.

**Dry runs.**
- `scenarios/simulate.yaml`: a root with 3 parallel areas and one zoom during the run. One build
  fails and is retried, and one judge closes its group with a recorded gap.
- `scenarios/zoom.yaml`: a zoom through `zoom.yaml` after the root finishes.
- `scenarios/zoom-light.yaml`: the same zoom with `profile: light`.
- `scenarios/simulate-light.yaml`: a light root on one component, with a light zoom during the
  run. One build is retried, and the judge closes its group with a recorded gap.

In each, the child files a change request against the root.

```sh
C=.claude/skills/mosaic-generate/compose
mosaic compose simulate $C/ontology-pipeline.yaml --scenario $C/scenarios/simulate.yaml
mosaic compose simulate $C/ontology-pipeline.yaml --scenario $C/scenarios/zoom-light.yaml
mosaic compose simulate $C/ontology-pipeline-light.yaml --scenario $C/scenarios/simulate-light.yaml
```

**Notes.**
- Role caps are scoped to the tree. Area agents of every scope in one hierarchy share 8 slots,
  judges 6, blind-measure agents 8 and oracle agents 4. Separate hierarchies don't queue behind
  each other. After the merge gate, up to about 20 sessions can be ready at once, so bound the
  host with `--max-parallel`.
- The coordinator cap is 2 per scope, so `refinement` and `contract` run side by side.
- `zoom.yaml` adds one level to the tree (root, zoom, child), so `max_depth: 6` allows about three
  levels of zooming through it. Zooms during the run (`zoom`) don't add that level.
- A child files its requests to its parent task. Through `zoom.yaml`, that is the zoom task, which
  forwards them to the parent run.
- At the root, `refinement` and `contract` are short turns: there's no link to record, and no
  parent to disagree with.

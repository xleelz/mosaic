<!--
Template: area-agent brief (pipeline stage 4). Render with the profile into {{workspace}}/BRIEF.md.
Each {{placeholder}} names a profile field. {{areas}}, {{overrides}}, {{errors.table}} and
{{shared_shapes.*}} render as tables or lists. Keep every rule's wording; each one exists
because a build broke without it. Requires mosaic with DESIGN §11 (in progress).
-->

# Brief: build the {{name}} ontology from code

You are one of {{areas.count}} area agents building a mosaic ontology of **{{snapshot.repo}} at
{{snapshot.ref}}** directly from its source code. Each agent writes one fragment. The fragments
are merged with `skeleton.yaml` and `fixtures.yaml` into one ontology. Then the repo's own tests
are translated into scenarios against it, and independent judges test it against well-known
behavior of the system. Model what the code does, not what you remember about the system. Where
they differ, the code wins, and you record the difference in your notes.

Contracts, naming and the shared worlds are fixed before you start. Coverage is measured against
an inventory of entry points. Citations are checked mechanically and then by a judge.

## Rules

1. **Source of truth.** The code at `{{snapshot.path}}` (`{{snapshot.ref}}`, `{{snapshot.sha}}`).
   It is read-only: never modify, build or run anything in it.
2. **Independence.** Read only these: the code, `skeleton.yaml`, `fixtures.yaml`, the inventory,
   your own files, and, for contracts only, an owner's fragment when you call another area. Never
   read {{independence.area_never_read}} or {{independence.never_read}}, nor any `BENCHMARK*.md`,
   `oracle*/` or `judge*/`: every round is scored on them blind, and a case you saw stops
   measuring the model.
3. **Evidence.** Every component, interface, config and narrated step cites code, as
   {{evidence.cite_form}}. Use **one source per string**, and the `sources` list when you need
   several. Cite files, not directories. Cite **the method's own lines**, because coverage and
   judges match them; a citation near an entry point doesn't cover it. {{evidence.not_evidence}}
   may orient you, but they are not evidence. Cite them only in your notes.
4. **Deployed config decides modes.** Code defaults aren't always what runs. The deployed values
   come from {{config.sources}}, in that order. Every value a behavior reads is a **config
   entity**, read as `config['<id>']`, durations included:
   `timeout_ms: "= config['write-request-timeout-ms']"` (`deadline_ms`, `after_ms`, `every_ms`,
   `stagger_ms`, `count` and `join.need` take templates too). A config belongs to the area whose
   code reads it:
   - **you own it**: define it in your fragment, named by {{naming.config}}, with the deployed
     `value`, the code `default`, and both lines in `sources`. For the shared values in
     {{config.required}} that the profile assigns to you, `fixtures.yaml` holds a reference;
     your definition replaces it, and you fix its value if the reference is wrong;
   - **another area owns it**: use the reference in `fixtures.yaml`, or add your own copy marked
     `attributes: {boundary: true, owner: <area>}`. An unmarked copy that differs is a merge error.
   Record every place where the deployed value and the default differ.
5. **Secrets.** Never open {{snapshot.forbidden}}. Never copy a token, key, password or internal
   hostname into the ontology.
6. **Your files only.** Write `fragments/<area>.yaml`, `notes/<area>.md`, `skips/<area>.json`,
   `skips/<area>.features.json`, `skips/<area>.failures.json` and, if you generate your fragment, `gen/<area>/**`, under
   `{{workspace}}/`. Edit nothing else. Don't commit. You may read your own
   `build-oracle/<area>.json`, and no other file there.

## Areas and ownership

An area owns the code under its paths. Where paths overlap, the more specific glob wins. The
overrides below beat paths.

{{areas}}  <!-- table: area | module | owns | except | typical entry points -->

**Overrides (owned by function, not by file):**

{{overrides}}  <!-- table: symbol | area | reason -->

{{cross_area_rules}}

## Naming (fixed, so callers can predict the owner's ids)

- **Components:** {{naming.component}}. Put every component under your skeleton module, or under
  another of your components.
- **Interfaces:** {{naming.interface}}.
- **Routes and messages:** {{naming.routes}} {{naming.messages}}
- **Schemas:** {{naming.schema}}. A shared contract keeps its owner's name, and only the owner
  defines it.
- **Configs:** {{naming.config}}. **Instances:** {{naming.instance}}.
- **Scenarios:** {{naming.scenario}}.
- Ids are globally unique across all areas. Never use bare generic names: {{naming.forbidden}}.

Worked examples: {{naming.examples}}

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

  {{shared_shapes.fields}}  <!-- list: field: type; meaning -->

  Shared schemas, defined once in `skeleton.yaml`: {{shared_shapes.schemas}}.
  {{shared_shapes.envelope}}
- **Errors.** {{errors.code_from}}; the status is {{errors.status_from}}. The fixed table:

  {{errors.table}}  <!-- table: code | status | retryable | source -->

  Check any code you add against {{errors.verify_against}} and the code that throws it.
- **Breaking changes toward the code are welcome.** If making an interface you own match the
  code changes its shape, change it, even when other areas' callers break. Never keep a shim or a
  parallel interface the code doesn't have. In your notes, under **Breaking changes**, list each
  change with its citation and every caller it breaks (the area, the interface or scenario, and
  what it must now read), and put the list in your report. Fix callers in your own fragment; the
  coordinator routes the rest.
- **If you generate your fragment, fix through the generator.** A script that writes
  `fragments/<area>.yaml` lives in `gen/<area>/` (never only in `/tmp`), and every fix goes into
  it. A rebuild must reproduce your fragment byte for byte.
- **Stubs merge by union.** When several areas stub the same boundary interface, the merge combines
  their properties, required lists, enums and errors, keeps the first value of any scalar, and
  warns about every disagreement. The owner's definition wins over every stub. So declare every
  field your code really reads, and copy the owner's scalars.
- **Shared infrastructure.** {{shared_components}}: calls to them are boundary-stub interfaces
  named after the operation, with one kind for all areas. Stateful storage that scenarios must
  inspect belongs on the owner's own component, as `store` interfaces.

## The world: fixtures, instances and config

- **Use the shared fixtures. Never seed a private world.** `fixtures.yaml` defines
  {{fixtures.worlds}}. Every scenario lists `fixtures: [...]` and adds only the state its case
  needs on top. Use the canonical names ({{fixtures.canonical_names}}) in inputs and in your
  schemas' `examples`, so fake entry data lands in the seeded world. Never seed another area's
  state under names of your own; if the fixture lacks something your case needs, ask the
  coordinator to add it, and record the request in your notes.
- **Unknown keys fail.** A behavior that looks up a table, key, tenant or route that isn't there
  fails with the code's real error. It never logs and skips.
- **Instances, not `to` fields.** Copies of the same code ({{instances.groups}}) are instances.
  Address a peer with `on: <instance>` on the `call`, `emit` or `publish`, not with a `to` or
  `endpoint` field in the request. A behavior knows where it runs from `self`. Per-instance state
  is keyed `<component>@<instance>`. Entries run on `{{instances.entry_instance}}` unless a step
  says `on:`.
- **Shared data has one owner.** Each datum several areas touch has one owner, which keeps the
  only copy in its own component's state:

  {{shared_data}}  <!-- table: datum | owner | readers -->

  If you're a reader, read and change it only by calling the owner's interfaces (copy their
  contracts as for any other seam), and seed it only through the owner's fixtures. Never keep a
  copy of your own, under any name: two copies drift, and edits through one never reach the
  other. If you own it, give the readers the interfaces they need.
- **Time.** Every timestamp derives from `now`. The fixture sets the clock's epoch. Never write a
  wall-clock literal. Deadlines and timeouts read config
  (`deadline_ms: "= config['read-request-timeout-ms']"`), and periodic work uses timers (`emit`
  or `publish` with `every_ms` and `count`) or `entry.repeat`.

## How to model

Read these first: `.claude/skills/mosaic-ontology/SKILL.md` with its
`references/document-format.md` and `references/modeling-codebases.md`; then
`.claude/skills/mosaic-simulation/SKILL.md` with its `references/behavior-language.md` and
`references/recipes.md`. Ignore their CLI instructions: you verify with the check tool below.

- **Fragment header.** `schema_version: 1`, `id: {{id}}`, then your entities. Don't redefine
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
  hollow` reports a `writes` flow without one. A step starts after the previous step has ended,
  its emits and timers included (or when everything left is a loop idling on a `receive`). Steps
  overlap only when you say so: `at_ms` starts a step on time, and `await: false` moves straight
  on. Concurrency inside a step is `parallel`. Assert on `state` or `trace` in every scenario
  that writes, never only on `result.ok`.
- **Concurrency and lifecycle primitives** (DESIGN §13.1 items 14–18). Use them where the code
  has them, not as approximations:
  - cancellation tokens (`token`, `cancel`);
  - `restart` and `kill` of an instance;
  - `rendezvous` for collectives;
  - streams (the callee `yield`s, and the caller sets `stream: true` with `on_item`);
  - channels (`put`, and a blocking `receive` with a timeout and a capacity) for queues and
    long-lived loops;
  - CEL `eval` for rules held as data (policies, `when` clauses);
  - microsecond time.
- **Rate limits and back pressure are `limiters`** (DESIGN §13.1 item 27), keyed by whatever input
  the code keys on: a client IP (`key: "= input.x_peer_ip"`), an org, an API key, a dimension.
  Apply them with the interface's `limits`, or `admit`/`charge`/`release` steps. Never hand-roll
  a counter in `state`: in one build every area rolled its own, and one couldn't key by IP at all.
- **Compare-and-set is `if` or `transact`, never read-then-write.** A `get` followed by a plain
  `put` or `update` of the same row loses updates the moment two callers race; use `if:`,
  `if_absent`, `incr` or `transact` as the code's CAS, Lua script or `WHERE` clause does.
  `--lint racy` reports the rest. A real single writer carries `attributes.single_writer` with
  its citation.
- **Spell a seam's fields as the writer does.** Copy field names from the owner, letter for
  letter: `limitUSD` written and `limitUsd` read passed every scenario, because each side
  agreed with itself. `--lint seam-names` reports them.
- **Assert on your own calls and the outcome**, not on how many times another area's internal
  interfaces are called.
- **Scale.** Breadth first. Rough target per area: {{scale.per_area}}. Quality over volume, but
  every entry point is accounted for.

## Coverage: every entry point is modeled or skipped with a reason

The inventory is at `{{workspace}}/inventory.json` ({{inventory.counts}}). Each entry is
`{kind, name, file, line}`. Ownership and coverage per kind:

{{inventory.kinds}}  <!-- table: kind | owner | what covers it -->

Skip rules already decided: {{inventory.skip_rules}}.

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

**A skip that says another entity covers the entry must name it**, in `"covered_by": "<kind>:<id>"`
(for example `"interface:git-service.commit"`). The coordinator's `assign_inventory.py` rejects a
reason that says "covered by" without the field, and a `covered_by` that names no entity in the
merged fragments. A rejected skip counts as uncovered.

**Thin behaviors don't count.** An interface whose behavior only returns, or sets a field or two
with no call, branch, `fail`, `emit`, `publish` or store, is **trivial**. It registers the entry but
doesn't model it: the check tool lists it under `--lint trivial`, leaves it out of the
**substantive** count, and fails your area when more than 35% of your entry-citing interfaces are
trivial (`--max-trivial 0.35`) or fewer than half your unskipped entries are substantive
(`--min-substantive 0.5`). Model the real control flow, or skip the entry with a reason.

## Features and tests: model the system, not only the inventory

The inventory counts entry points, and in past builds a whole area passed every coverage gate
while the features users rely on were never modeled. Two more gates weight your work by what the
project itself cares about.

**Features.** The coordinator listed the system's user-visible features before fan-out:

{{features}}  <!-- table: id | summary | sources | owner -->

For every feature your area owns, either:
- **model it**: a flow tagged `feature:<id>` (next to its other tags, such as `writes`) whose
  scenarios run the feature's real control flow, with the config it is switched by; or
- **skip it** in `skips/<area>.features.json`: `[{"id": "<feature id>", "reason": "..."}]`. The
  reason must hold up: "not modeled", "out of scope", "too large" and "todo" are rejected, and a
  reason that says another entity covers it names that entity in `"covered_by": "<kind>:<id>"`.

`--features {{workspace}}/profile.yaml --strict-features` fails your area on a feature that is
neither. Features owned by other areas are reported apart and don't fail your check.

**Failures.** The coordinator also listed the failure matrix: the ways a shared component or edge
fails (`on`: redis, the scheduler, a client disconnect, a node death, a lease loss, an upstream
provider) and which area handles each:

{{failures}}  <!-- table: id | summary | on | sources | owner -->

For every failure your area owns, either model it as a flow tagged `failure:<id>` that a scenario
runs **with the failure injected** (a `faults` entry, a `kill` fault or step, a `cancel` or
`restart` step, a mock with `fail`, or seeded `state`) and whose expectations check what the
system does about it; or skip it in `skips/<area>.failures.json` under the feature skip rules.
A tagged flow whose scenarios inject nothing does not count. `--failures
{{workspace}}/profile.yaml --strict-failures` fails your area on a failure that is neither.

**A two-sided failure needs both sides.** An entry with `sides: [{owner, role}]` (a client's retry
and the server's dedupe) is covered only when every side is. For each side you own, tag a flow
`failure:<id>:<role>` and run it under injection, or skip that side with `{id, role, reason}`. In
one build, the CLI's retry counted the idempotent-retry failure as covered while the control plane
ignored the key.

**Test reach.** `{{workspace}}/test-targets.json` maps each of the repo's test files to the code
it tests (`[{test, targets, area}]`, read from its imports). A test is **reached** when an
interface citing one of its target files is called in some scenario's trace. At least half of
your area's tests must be reached (`--tests ... --min-test-reach 0.5`). `-v` lists the unreached
ones: each is either code your scenarios should run (model it, and cite the file) or code below
the model's level (a byte format, a kernel's numerics), which your notes may say. Don't read the
tests to write scenarios from them; the target files tell you where the tested logic lives.

## Oracle in the build (stage 4b)

`{{workspace}}/build-oracle/<area>.json` lists 3 tests from your own paths
(`[{file, line, name}]`, drawn by the coordinator). Before hand-off, translate each one into a
scenario in your own fragment, with id `oracle-build-<area>-<n>`:
- the test's arrange step becomes `fixtures` and `state`; its act steps become `steps`; its
  asserts become `expect` over `result`, `state`, `steps` and `trace`;
- read the test, never run it;
- each must pass. When one fails, the model is wrong: fix the model, never the scenario. If the
  test checks something below the model's level, or needs a feature mosaic lacks, keep no
  scenario and record it in your notes as `untranslatable` (say what) or `sim-gap` (name the
  feature).

The final oracle (stage 6) draws a different sample, so these tests don't count twice.

## Verify before hand-off

```sh
cd <mosaic repo>
export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
go run ./internal/devtools/check \
  -f {{workspace}}/skeleton.yaml -f {{workspace}}/fixtures.yaml -f {{workspace}}/fragments/<area>.yaml \
  --code {{snapshot.path}} --strict-citations --inventory {{workspace}}/inventory.json \
  --min-modeled 0.5 --min-substantive 0.5 --max-trivial 0.35 \
  --tests {{workspace}}/test-targets.json --min-test-reach 0.5 \
  --features {{workspace}}/profile.yaml --strict-features \
  --behavior-coverage --no-mocks \
  --lint hollow,trivial,racy,seam-names --max-racy 0 --max-seam-names 0 -v
# debugging one scenario:
go run ./internal/devtools/check -f ... --scenario '^<id>$' --trace
```

Hand off only when:
1. **0 errors, 0 failed scenarios, 0 scenario warnings, 0 mocks.** Warnings are usually a stub
   that guessed a shape.
2. **Citations resolve** (`--strict-citations`), and **support their claims**: run
   `--cite-sample {{scale.gates.cite_sample}} --seed <n>` twice with different seeds and read each
   sampled claim next to its code. Fix every bad one.
3. **No merge warnings that mention your fragment.**
4. **Coverage.** Every entry you own is covered in the `-v` output or listed in
   `skips/<area>.json`, and at least half the entries you own that aren't skipped are modeled
   (`--min-modeled 0.5`). Covered means registered: something reachable cites the entry. Modeled
   means an interface that cites the entry or is named for it has a behavior or a `store`, and
   some scenario calls it. At least half are **substantive** (`--min-substantive 0.5`): modeled by
   a non-trivial interface. At most 35% of your entry-citing interfaces are trivial
   (`--max-trivial 0.35`). Every "covered by" skip names its entity in `covered_by`.
5. **Hollow lint clean**, and **behavior coverage** at least {{scale.gates.behavior_coverage_min}}
   for your area, with every `fail` and `if` branch run by some scenario or explained in your notes.
6. **Write-then-read**: every flow that writes state is tagged `writes` and has its read-back
   scenario (part of the hollow lint).
7. **In-build oracle**: each test in `build-oracle/<area>.json` is a passing
   `oracle-build-<area>-<n>` scenario, or is recorded in your notes as `untranslatable` or
   `sim-gap`.
8. **Shared data**: you hold no copy of a datum another area owns.
9. **Features**: every feature you own is covered by a flow tagged `feature:<id>` that a scenario
   runs, or skipped with a valid reason in `skips/<area>.features.json` (`--strict-features`).
   Likewise every failure you own: a flow tagged `failure:<id>` run with the failure injected, or
   a valid skip in `skips/<area>.failures.json` (`--strict-failures`).
10. **Test reach** at least 0.5 for your area (`--min-test-reach 0.5`).
11. **No racy or seam-names findings** (`--max-racy 0 --max-seam-names 0`).
12. **Ratcheted gates** (the profile's `gates:`, read by `--profile`): fix every new lint finding in your area (unknown-inputs, exemptions, internal-assertions, clock-ids, stubs that disagree), and never raise a threshold.

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
10. In-build oracle: one row per sampled test (test, scenario, verdict, cause).
11. Features: each feature you own, with its flow or its skip reason; and the groups of unreached
    tests, with why (not modeled yet, or below the model's level).

## Report back (≤200 words)

Entity counts; the check tool's final lines (validation, citations, coverage, behavior coverage,
hollow lint, trivial lint, racy, seam-names, substantive, test reach, features, mocks); the in-build oracle verdicts; the flows you modeled; entries covered and skipped; fixture requests; the
top modeling gaps and simulator gaps.

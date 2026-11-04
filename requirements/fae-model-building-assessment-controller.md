# Fae assessment: can mosaic's model-building rounds run on fae? (controller and gate side)

| | |
|---|---|
| Status | Assessment and proposal. Nothing here is implemented, and nothing is applied to fae. |
| Target | `~/workplace/fae` working tree (HEAD `e547c03`, about 1,160 uncommitted changes, read 2026-11-04). Line numbers refer to that working tree. |
| Scope | The controller and gate side: the coordinator as a fae Controller, per-round templates, gate steps, decision points, artifact passing, blind roles, prompt parameters, kernel floors, commit and push, secrets and observability. The execution side (sessions, fan-out width, concurrency, recursion) is covered by the parallel assessment, `requirements/fae-model-building-assessment-execution.md`. |
| New | FAE-CTL-101 to FAE-CTL-113 |
| Builds on | `requirements/fae-hierarchical-workflows.md` (FAE-WF-095 to -104, FAE-SCH-023, FAE-API-034 to -036, FAE-CLI-055, -056), `requirements/fae-host-workflow-limit.md` (FAE-SCH-015 to -022, FAE-CLI-044) |

Another process owns fae's working tree, so this document lives in mosaic. The proposals are
written in REQUIREMENTS.md's form, so that they can be pasted in.

## Verdict

**Not yet.** Fae's control surface fits a mosaic coordinator well. A coordinator can be a fae
Controller, author a template revision per round (validate, simulate, put), admit one task per
area, answer HumanDecision stages, and watch an event stream.

What a round's steps need is another matter. Three gaps block a real round on their own:
- **Agents can't read code.** Every agent turn runs with no tools. It sees only the files
  declared for its task (at most 1 MiB each and 4 MiB per turn) and a list of paths. Mosaic's
  area agents, judges and oracle agents read and search a whole snapshot, which lives outside
  the workspace.
- **A gate can't read `mcheck`.** The only non-test HostCommand fae runs is `gofmt -l .`. A test
  run yields only an exit code and counts. A gate can't read `mcheck`'s ratchets, coverage or
  stage-accept state, and a command may not write anything in the worktree.
- **Fragments can't be written as documents.** A model may edit only in the `implement` or
  `test-first` phase. Such a change producer can't sit in a FanOut, and the edit scope is the
  task's declared files, not a stage's.

Commit identity is also hard-coded, with no scrub-list gate. There is no general push, and stage
reads aren't scoped per stage, so "blind" holds only across separate tasks.

## What has landed since the earlier proposals

**No proposed requirement has landed.** `REQUIREMENTS.md` is unchanged against HEAD (its highest
ids are still FAE-WF-094, FAE-SCH-014, FAE-API-033 and FAE-CLI-054). The gaps the hierarchical
proposal named are all still in the code:

| Gap (earlier proposal) | Still true | Evidence today |
|---|---|---|
| FanOut width fixed at 2 to 16 | yes | `workflow/fan.go:147-148` |
| Branches run one after another | yes | `engine/fanout.go:18-22`; `workflow/GRAMMAR.md:250` |
| No SubWorkflow, change producer or HumanDecision in a branch | yes | `workflow/fan.go:191-196` |
| No self-recursion; nesting capped at 4 | yes | `workflow/subworkflow.go:31`; `daemon/subworkflow.go:18` |
| `Admit` has no inputs or parent | yes | `daemon/rpc.go:20-50` |
| No workflow slot or host workflow limit | yes | a search for `WorkflowSlot`, `workflow-limit` or `Footprint` finds nothing in Go sources |

The working tree has gained these, and they matter for this assessment:
- **HumanDecision**, with declared options, `fae decide` and operator provenance
  (`workflow/GRAMMAR.md:164-179`). A controller may decide under the `task` class
  (`daemon/authority.go:36`).
- **Aggregated Review**: `all-pass`, `k-of-n` and `any-blocking-fails`, with a failure route
  (`GRAMMAR.md:187-196`).
- **Shaped HostCommand** (`expected_shape` exit, executed and matched), a stage `environment`
  (`GRAMMAR.md:208-219`), and typed argument bindings (`GRAMMAR.md:85-90`).
- **Loop** `exit_gate`, `backoff_seconds` and `on_exhaustion` (`GRAMMAR.md:198-206`).
- **FanOut/FanIn**, with sibling isolation and branch verdicts (`GRAMMAR.md:230-269`).
- **SubWorkflow** with `input_map` and `output_map` (`GRAMMAR.md:271-297`).
- **Content-addressed gate records** with replay (`GRAMMAR.md:299-312`).
- **Schema 2**, which makes gate names and Escalate kinds required (`GRAMMAR.md:114-138`).
- **Delegated principals**: a controller credential file (`daemon/principals.go:20-70`) and
  class-directed operator messages (`controlplane/action_authority.go:36-71`).
- **The path protection list** for model-chosen scopes (`workflow/protected_path.go:7-36`).

## Capability table

Status: **S** supported, **P** partly, **M** missing.

### Controller

| Need | Status | Evidence | Notes |
|---|---|---|---|
| Coordinator acts as a Controller over the daemon API | S | Glossary `REQUIREMENTS.md:59`; FAE-OPS-001 `:943`; `api/principal.go:22-42`; `daemon/principals.go:20-70`; `daemon/authority.go:76-78` | Credential file (0600, outside any repo) names actor `controller`. Every mutating RPC is open to it, ProphetChat excepted. |
| Authorizing messages | P | FAE-OPS-002 `REQUIREMENTS.md:956`; `controlplane/action_authority.go:56-62`; `daemon/messages.go:60-66`; `controlplane/job.go:421-424`; `controlplane/store.go:39-40` | The operator must record each message; a controller can only relay one, and a relay carries no authority. One message whose `authorize.classes` are `[governance, task]` covers put, admit and decide. It expires after 24 h (default `MessageMaxAge`), so a multi-day round needs fresh operator messages. → FAE-CTL-111 |
| Author a new template per round: validate, simulate, put | S | FAE-CLI-020 `REQUIREMENTS.md:1107`; `cmd/fae/workflow.go:31, 92-110`; `daemon/authority.go:31-32` (`WorkflowValidate`, `WorkflowSimulate` reads; `WorkflowInstall` governance) | Validate runs offline and lists every error. Simulate runs the real engine on scripted outputs (`GRAMMAR.md:140-148`), but doesn't run SubWorkflow children (`GRAMMAR.md:295-297`). Revisions are immutable, and a put appends latest+1 (FAE-WF-002). |
| Admit tasks on a chosen revision | S | `daemon/rpc.go:20-50` (`WorkflowID`, `Revision`, `Content`, `DeclaredFiles`, `TestFilter`, `TaskClass`); `daemon/authority.go:32` | No typed inputs or parent link (FAE-WF-099, -100 still proposed). |
| Footprint and host limit before admitting about 10 tasks | M | not in the code (see above) | FAE-SCH-015 to -022 are still proposed. |

### Gates and decisions

| Need | Status | Evidence | Notes |
|---|---|---|---|
| Deterministic gate on a command's exit code | P | HostCommand `REQUIREMENTS.md:350`; `GRAMMAR.md:208-213`; `daemon/live.go:666`; `effects/shapes.go:70-110` | Works only as a **test run**. Exit, executed and matched counts come from `go test -json` or TAP (`script` or `runner` shape, which take the pinned id as the last argument). So `mcheck` needs a TAP wrapper script checked into the worktree, and the gate needs `executed_count >= 1` (FAE-WF-062, `GRAMMAR.md:25`). |
| Gate on the command's **output** (ratchet lines, stage-accept, coverage numbers) | M | `daemon/live.go:667-669` refuses any non-test command other than `gofmt -l .` ("unsupported non-test command artifact"). The EngineRun artifact holds only exit, counts, `red_passed` and `output_digest` (`defaults/defaults.go:219`; `effects/broker.go:120-148`). | → FAE-CTL-105 |
| A gate command that writes (`mcheck --stage --accept` writes `.mosaic/stage/`; `-o` writes the merged model) | M | `effects/broker.go:430-438` ("host command mutated source tree") | Unverified whether ignored paths count in the tree hash (`Broker.Tree`, `effects/broker.go:798`). → FAE-CTL-105 |
| Commands on an allowlist, from argument vectors | S | FAE-WF-035 `REQUIREMENTS.md:383`; `effects/broker.go:262-268`; `GRAMMAR.md:85-90, 103-106` | Each round's `mcheck` vector must appear in `target_requirements.commands` and in the target allowlist. |
| Human or coordinator decision points | S | `GRAMMAR.md:164-179`; `daemon/authority.go:36`; `daemon/decision.go:54` | A fixed option list (1 to 32), routed. It never decides on a timeout. |
| Per-item decisions ("accept this judge claim, reject that one", route each breaking change) | P | Options are static and the decision artifact holds one `option` (`GRAMMAR.md:170-176`) | A list of N claims can't be decided as one structured record. → FAE-CTL-108 |
| Retry until the gate passes | S | Loop `GRAMMAR.md:198-206`; progress `GRAMMAR.md:91-95` | Progress counts need findings inside an artifact. `mcheck` failure counts aren't one (FAE-CTL-105). |
| Independent judges | P | Review `REQUIREMENTS.md:348, 375`; `GRAMMAR.md:187-196` | Isolated sessions, but judges see only declared files (below). |

### Artifacts, blind roles and parameters

| Need | Status | Evidence | Notes |
|---|---|---|---|
| Artifacts between steps of one task | S | FAE-WF-050, -051 `REQUIREMENTS.md:419-425`; inputs as typed blocks `execution/executor.go:542-544` | Typed JSON, content-addressed, with provenance. |
| Files between tasks (fragments into the merge, the merged model to judges) | P | A task's worktree forks from the integration tip at release; files move only by VcsCommit and Integrate (`REQUIREMENTS.md:353-355`). SubWorkflow maps artifacts, not files (`GRAMMAR.md:271-290`). | Moving a file means committing to the protected integration branch, which brings in the protected-commit floor. |
| Agents read the code under study and the model | **M** | `provider/claude.go:16-19, 78` (`--tools ""`; only `StructuredOutput`); `provider/codex.go:169` (read-only sandbox, shell disabled); `provider/README.md:10-46`; `LIVE.md:9-12, 551` ("general brokered agent command tools ... remain open") | A turn sees its declared files in full and a list of paths (at most 5,000). Each file is capped at 1 MiB and a turn at 4 MiB. One gateway-platform fragment is 2.0 MB, and merged models run from 5.5 MB to 22 MB. The snapshot is outside the bound workspace (one workspace per instance, `REQUIREMENTS.md:55`). → FAE-CTL-101, -102 |
| Agents write fragment documents | P | Edits only in `test-first` and `implement` phases (`provider/README.md:121-129`). `phase` is closed to those two (`workflow/workflow.go:577`). A change producer can't be in a FanOut (`workflow/fan.go:194-196`). | An area agent would be a code-style `implement` change producer, one task per area. → FAE-CTL-104 |
| "Blind" role with restricted readable inputs | P | Inputs are bound explicitly (FAE-WF-031); siblings are hidden in a FanOut (`GRAMMAR.md:259-260`). But scope is **per task**: `taskScopeBlock(binding.Scope)` in every brief (`execution/executor.go:52-55, 543`), and every turn gets the repository path list (`provider/README.md:52-56`). | Blindness holds across tasks with disjoint declared files, never across stages of one task, and file names still show in the path list. → FAE-CTL-106 |
| Per-area prompt parameters | P | Brief templates are static strings, sent as-is beside the bound inputs (`execution/executor.go:531-545`). Task `Content` reaches every brief as acceptance context (`daemon/backlog.go:862-871`, `daemon/live.go:331`). No template parameters (`daemon/rpc.go:20-50`). | Today: one task per area, with the area spec in `Content` and its files in `DeclaredFiles`. → FAE-CTL-107 (with FAE-WF-099) |

### Floors, commits, secrets and observability

| Need | Status | Evidence | Notes |
|---|---|---|---|
| Kernel floors fit YAML work | P | FAE-WF-070, -071, -073 `REQUIREMENTS.md:455-479`; `GRAMMAR.md:31-42, 67-77` | Test-first applies only to code-bearing classes, so a document workflow with `code_bearing: false` escapes it. Protected-commit applies to any commit or integration onto a protected branch (the integration branch always is). It needs a test run with a positive count plus an independent Review, which `mcheck`-as-TAP and a merge reviewer can satisfy. `fae land` requires a test filter and Go format, compile and suite gates (`REQUIREMENTS.md:1290-1302`). No-bypass (FAE-WF-031) fits as is. → FAE-CTL-113 |
| Commits are gated | S | FAE-WF-071; VcsCommit commits only declared, reviewed files (`REQUIREMENTS.md:353`); `fae land` (FAE-CTL-030) | — |
| Commit author identity | M | `effects/broker.go:894` hard-codes `Fae <fae@localhost>` | Mosaic commits under the user's identity. → FAE-CTL-109 |
| Scrub list (names that must never appear) | M | Fae redacts secret shapes in output (`secretshape/`, `daemon/secret_redaction.go`). There is no content deny-list gate on diffs or messages. | It could be faked as a TAP test script, but that's unenforced policy. → FAE-CTL-109 |
| Push | M | A Local session's `git push` exits 78 (`LIVE.md:639`, FAE-MODE-002 `REQUIREMENTS.md:851`). Pushing exists only as Normal-mode code-review effects (`REQUIREMENTS.md:356`). | → FAE-CTL-110 |
| Deny secret paths | P | No file tools, so a turn reads nothing it wasn't given. `workflow/protected_path.go:7-36` refuses credential-like files in model-chosen scope, but "the operator can still name such a file" (`:34`), and the list is fixed (no `*.age`, for example). | → FAE-CTL-109 (deny globs) |
| Event stream | S | FAE-API-020, -021 `REQUIREMENTS.md:1387-1393`; `api/api.go:154` (`GET /v1/events`); paged `Events` with `after` (`daemon/rpc.go:340-352`) | No filter by task, run or workflow. → FAE-CTL-112 |
| Per-agent status | S | `Panes`, `Leases`, `Board` reads (`daemon/authority.go:31, 35`; FAE-API-001 `REQUIREMENTS.md:1351`) | — |
| Final reports | S | Role outputs are artifacts in TaskHistory (FAE-WF-052, FAE-OBS-003 `REQUIREMENTS.md:1516`) | No run-level summary across a round's tasks. → FAE-CTL-112 |

## Sketch: one mosaic round as fae templates

This sketch assumes FAE-CTL-101 to -107. Where fae can do a step today, that is noted. The
coordinator stays **outside** fae, as the Controller. Fae runs the steps and gates, and the
coordinator authors, admits, decides and lands.

### Coordinator loop (Controller, outside fae)

1. Read the blind findings of round n−1 (TaskHistory of the `mosaic-measure` task). Write
   `FIXES<n>.md` and render the briefs.
2. Write this round's revisions of the templates below. Briefs for this round go in role
   `briefs`, and `mcheck` vectors in `target_requirements.commands`. Then:
   - `workflow-validate`;
   - `workflow-simulate` with a scripted pass, fail and fix path;
   - `workflow-put` under a governance-class message.
3. Admit the `mosaic-benchmark` task first. Builders never get its files.
4. Admit one `mosaic-area` task per area under a task-class message:
   - `Content`: the area's spec and fix list;
   - `DeclaredFiles`: its four owned files.

   Then wait on `/v1/events`.
5. Answer `HumanDecision` stages:
   - breaking-change routing;
   - deadlocks;
   - disputed judge claims (FAE-CTL-108).
6. When the merge task is Done, land it (`fae land`, gated, FAE-CTL-109, -113) and admit
   `mosaic-measure`.
7. Write `RESULTS.md` and update memory (coordinator files, outside fae), then go back to step 1.

### Templates

**`mosaic-area`** (one task per area; `code_bearing: false`; task-bound role `area`, cap 10)

| Stage | Primitive | Gate or route |
|---|---|---|
| `build` | AgentTurn, role `area`, writes its declared files (needs FAE-CTL-101, -102 to read code; FAE-CTL-104 to write YAML outside `implement`) | — |
| `stage-check` | HostCommand: `mcheck --stage fragments/<area>.yaml --accept …`, with structured output (FAE-CTL-105; today only a TAP wrapper) | shaped: exit `zero`, `min_executed 1`; failure → `fix-loop` |
| `accepted` | Gate | `stage-check.accepted == true ∧ stage-check.failures == 0 ∧ executed_count ≥ 1` (needs FAE-CTL-105); failure → `fix-loop` |
| `fix-loop` | Loop, `max_iterations 3`, progress on `stage-check.failures` | exhausted → `area-stuck` |
| `area-stuck` | HumanDecision: "retry with context / split area / accept skip" | routed |
| `commit` | VcsCommit of the declared files onto the task branch | the protected-commit floor applies only if the target is protected |

**`mosaic-merge`** (one task; declared files: the merged model, `RECONCILE.md`, the notes index)

| Stage | Primitive | Gate or route |
|---|---|---|
| `merge` | AgentTurn, role `merge` (reads every area's committed fragment, FAE-CTL-101) | — |
| `full-gate` | HostCommand: the full `mcheck` gate from `docs/PIPELINE.md` plus `--profile`, structured (FAE-CTL-105) | shaped exit `zero`; failure → `reconcile` |
| `ratchet` | Gate: no gate value above the profile's; ratchet suggestions recorded as follow-ups | failure → `reconcile` |
| `reconcile` | HumanDecision with structured items (FAE-CTL-108): breaking changes to route, deadlocks | `relaunch` (the coordinator admits the listed areas again) or `accept` |
| `review` | Review, role `merge-reviewer`, `any-blocking-fails` | protected-commit floor (b) |
| `scrub` | content policy at commit (FAE-CTL-109) | refusal holds the commit |
| `commit`, `integrate` | VcsCommit, Integrate | protected-commit floor (a) is met by `full-gate` (FAE-CTL-113) |

**`mosaic-benchmark`** (a separate task before fan-out; declared files: `BENCHMARK<n>.md` only;
role `benchmark` reads code and docs, never the model)

- `write` (AgentTurn), then `shape-check` (HostCommand: groups of at most 5 cases), then a Gate,
  then commit to a branch that builders' tasks never fork from. The parameter is FAE-CTL-106's
  deny glob `BENCHMARK*`, `oracle*/`, `judge*/` on every builder role.

**`mosaic-measure`** (one task after the merge lands; blind roles)

| Stage | Primitive | Gate or route |
|---|---|---|
| `sample` | HostCommand `sample_tests.py --exclude-sample …` (a non-test command, FAE-CTL-105) | shaped exit `zero` |
| `judges` | FanOut over benchmark groups (at most 16, run one after another today); each branch is a `judge` AgentTurn emitting a typed scorecard (no edits, so allowed in a branch) | branch `pass`: scorecard present, `verified_count ≥ 1` |
| `oracle` | FanOut over oracle areas; `oracle` AgentTurn, typed verdicts | same |
| `join` | FanIn `all` | failure → Escalate |
| `measure` | AgentTurn summing scorecards into `Measure` | Gate: every case scored or recorded as unscorable |

The judge and oracle roles carry FAE-CTL-106 read scopes: code, the merged model and their group,
but never builders' notes or other groups.

### Gate map

| Mosaic gate | Fae construct | Today |
|---|---|---|
| `mcheck --stage --accept` per area | HostCommand + Gate on structured fields | TAP wrapper with exit and counts only; the `--accept` write refused |
| Full gate (all flags, `--profile`) | HostCommand + Gate | as above |
| Ratchet (`~ ratchet: --flag can go down to N`) | Gate over parsed values, follow-ups | M |
| `--cite-sample` support check | AgentTurn (reads cited code) + Gate on its findings | M (no code reading) |
| Judges verify expectations first | Review or FanOut of AgentTurns with a typed `corrections` list | P (no code reading) |
| "Judge is wrong" claims | HumanDecision with structured items | P (one option per decision) |
| Commit author, scrub list, secret files | Target content policy at VcsCommit, Integrate and land | M |

## New requirements

The ids are in the FAE-CTL-1xx range, clear of fae's FAE-CTL-001 to -051 and of every id in the
two earlier proposals. Each requirement names the section where it belongs.

### Reading code (§6, the runtime adapter)

**FAE-CTL-101 (MUST)** A role MAY declare the capability `explore`. Its sessions then get
read-only file tools: read a file or a line range, list a directory, and search by glob and by
regular expression. They read over the session's **read roots** (FAE-CTL-102), and nothing else.
- The bridge MUST enforce the roots and the role's deny globs (FAE-CTL-106) for every tool call:
  - by the agent CLI's own permission rules, where it has them;
  - by a pre-tool hook;
  - and by resolving each path physically (no symlink escapes, no `..`).
- Tool results MUST be bounded per call (default 256 KiB) and per turn (default 64 MiB), never
  truncated silently.
- `explore` grants no write, no command execution and no network.
- The 1 MiB and 4 MiB bounds on *declared* files (`provider/README.md:36-46`) still apply to the
  files sent in the prompt. Files reached by tools are read by range.
- `explore` MUST appear in the validator's capability set (`workflow/primitives.go:346-349`), and
  a stage profile may only remove it.
- *Rationale:* every mosaic agent reads and searches a whole snapshot: builders cite the method's
  own lines, judges verify each expectation against the code, and oracle agents read the repo's
  tests. A path list plus at most 4 MiB of declared files can't support that.
- *Acceptance:* tests on the scripted bridge and the Claude bridge:
  - (a) an `explore` turn reads a line range of a 5 MiB file under a read root;
  - (b) a read outside every root is refused, recorded, and the turn continues;
  - (c) a symlink inside a root that points outside it is refused;
  - (d) a role without `explore` announces no file tool, and its turn is refused if one appears;
  - (e) a stage that widens to `explore` is refused by the validator.

**FAE-CTL-102 (MUST)** A target configuration MAY declare **read roots** outside the bound
workspace:
- each is an absolute path;
- each has an identity (a git commit, or a content digest of a tree listing);
- each MAY list deny globs.

A role's sessions read the task worktree plus the roots the role names.
- At admission, the daemon MUST verify each named root's identity, and record it on the task.
  A root whose identity has changed MUST refuse further dispatch with a typed refusal.
- Roots are read-only to every session and every command. A HostCommand MAY receive a root as a
  typed `relative-path`-style binding of a new type `read-root`.
- *Rationale:* mosaic models a snapshot of another repository (for example `~/.cache/<repo>-<sha>`),
  and must never build or change it. One workspace per instance (`REQUIREMENTS.md:55`) can't hold
  it.
- *Acceptance:*
  - (a) a root whose commit differs from the declared one refuses dispatch;
  - (b) a write by any path into a root fails;
  - (c) TaskHistory shows the root identity each turn read.

### Writing documents (§4.3, §6)

**FAE-CTL-104 (MUST)** A non-code-bearing workflow MAY declare `phase: author` on an AgentTurn.
- It is a change producer whose edits are confined to a stage-level `writes` list of globs, bound
  from task inputs (for example `fragments/{{input.area}}.yaml`), intersected with the task's
  declared files.
- `author` MUST be refused in a code-bearing class. The test-first floor MUST NOT apply to it, and
  the protected-commit floor MUST apply unchanged.
- Edits by replacement MUST be allowed on files above 1 MiB without sending the whole file in the
  prompt (FAE-CTL-101 reads them). The 1 MiB per-edit result bound becomes a target setting
  (default 1 MiB, maximum 16 MiB).
- An `author` stage MAY sit inside a FanOut region when the regions' `writes` globs are provably
  disjoint. The validator MUST refuse overlapping globs.
- It complements FAE-WF-102 (`produces: artifacts`): `author` writes files that are later
  committed, while FAE-WF-102 writes no commits.
- *Rationale:* an area agent writes YAML, notes and skip files, not code. Pretending it's an
  `implement` turn imports code-only rules, keeps it out of fan-outs, and caps its fragment at
  1 MiB.
- *Acceptance:*
  - (a) an `author` turn edits `fragments/a.yaml` and is refused for `fragments/b.yaml`;
  - (b) `author` in a code-bearing class fails validation;
  - (c) two FanOut regions with disjoint `writes` validate, and overlapping ones are refused;
  - (d) a replacement edit on a 2 MiB file applies.

### Gate commands (§4.3, §4.6, §14.2)

**FAE-CTL-105 (MUST)** A HostCommand MAY declare `check: {format: json | lines, output: <artifact
type>, writes: [globs]}`. This makes it a **check command** that is not a test run.
- The broker MUST run it under the same allowlist, environment, timeout and heavy-op rules as a
  test run.
- The broker MUST parse standard output as one JSON document, or as `key: value` lines, into the
  declared artifact type, validated against its schema. A parse or schema failure is a failed run,
  never a pass. Exit code, `timed_out` and `truncated` MUST always be recorded as fields beside it.
- The tree-mutation refusal (`effects/broker.go:430-438`) MUST exempt only paths matching
  `writes`. Those paths MUST be outside the task's declared change scope, and MUST NOT be
  committed.
- Gates read the parsed fields like any artifact. FAE-WF-062's positive-evidence rule applies:
  the artifact MUST declare which field is its executed count (`count_field`), and the validator
  MUST require a lower bound on it.
- `daemon/live.go:667-669`'s refusal of non-test commands MUST be removed for check commands.
- *Rationale:* mosaic's gate is `mcheck`. Its verdict is a set of numbers (coverage, trivial share,
  racy and seam-name counts, ratchet values) and a stage-accept state, and it writes
  `.mosaic/stage/`. Exit code alone loses the ratchet, and a test-run TAP wrapper turns a
  deterministic checker into a fake test suite.
- *Acceptance:*
  - (a) a check command printing `{"failures": 0, "checked": 412, "accepted": true}` yields an
    artifact whose fields a gate reads;
  - (b) the validator refuses a gate over it without a bound on `checked`;
  - (c) malformed JSON fails the run;
  - (d) a write under a `writes` glob is allowed, and a write elsewhere is refused as today;
  - (e) a `writes` glob overlapping declared files fails validation.

### Blind roles (§4.4)

**FAE-CTL-106 (MUST)** A role and a stage MAY declare `reads: {allow: [globs], deny: [globs]}`
over the worktree and each read root. It applies to:
- declared files sent in the prompt;
- the repository path list (`provider/README.md:52-56`), which MUST omit denied paths;
- tool reads (FAE-CTL-101);
- bound inputs whose provenance names a denied stage.

A stage may only tighten its role's `reads`. The kernel contract MUST state the effective read
scope.
- The daemon MUST record on each turn's provenance the read scope it ran under, so a judge's or
  builder's blindness can be audited after the fact.
- *Rationale:* mosaic's score is the blind one. Builders must never see `BENCHMARK*`, `oracle*/` or
  `judge*/`, and judges must not see builders' notes. Today, scope is per task and the path list
  shows every name.
- *Acceptance:*
  - (a) a builder role denied `BENCHMARK*` gets a path list without those names, and a tool read
    of one is refused;
  - (b) two stages in one task with different `reads` see different files;
  - (c) a stage that widens its role's `reads` fails validation;
  - (d) TaskHistory shows each turn's effective read scope.

### Parameters (§4.4)

**FAE-CTL-107 (MUST)** Brief templates MAY reference the workflow's signature inputs (FAE-WF-099)
and, inside a dynamic FanOut branch, its `item` (FAE-WF-095), as `{{input.<name>}}` and
`{{item.<path>}}`.
- The executor MUST render each reference as a quoted, typed data block positioned at the
  reference (FAE-WF-043's structured binding), never by splicing text into instructions.
- The same references MAY appear in `writes` (FAE-CTL-104), `reads` (FAE-CTL-106) and HostCommand
  bindings of a typed placeholder (FAE-WF-035).
- The validator MUST refuse a reference to an undeclared input or item field.
- *Rationale:* one area template, parameterized by area id, owned paths and fix list, replaces
  ten roles or ten revisions per round.
- *Acceptance:*
  - (a) a brief with `{{input.area}}` renders the area as a data block;
  - (b) an instruction-like value stays inside its block;
  - (c) a reference to an undeclared input fails validation;
  - (d) a FanOut over three items yields three briefs and three `writes` scopes.

### Decisions (§4.3, §10)

**FAE-CTL-108 (MUST)** A HumanDecision MAY declare `items_from: <artifact field path>` (a list) and
`item_options` (1 to 8 ids, each with a description), instead of or as well as its routing
`options`.
- `fae decide` MUST then accept one option per item (by item index or item `id`) and a rationale
  per item.
- The decision MUST be refused until every item has an option.
- The decision artifact MUST record the items, each choice, the authorizing message and the
  decider.
- Gates and later briefs read it like any artifact (for example "count of items decided
  `accept`"). Routing still uses the routed `options`, chosen in the same call.
- *Rationale:* a round's coordinator decides lists: which "the judge is wrong" claims to accept,
  where each breaking change goes, and which deadlocked seam's owner wins. One option per stage
  can't record that, and splitting it into N stages needs a dynamic graph.
- *Acceptance:*
  - (a) a decision over five items with one missing is refused;
  - (b) a complete decision records every item;
  - (c) a gate counts the accepted items;
  - (d) the simulator accepts scripted per-item decisions.

### Controller authority (§10.1)

**FAE-CTL-111 (MUST)** An operator MAY record a **standing grant** for a controller principal. It
names:
- classes, verbs and workflow ids;
- an optional maximum number of uses;
- an expiry no later than 14 days.

A controller citing a standing grant is authorized for matching verbs past `MessageMaxAge`, until
expiry or revocation by the operator.
- Every use MUST be audited with the grant id.
- `governance` uses MUST be limited to the named workflow ids.
- A grant can't include `runtime`, `host-wide` or `capacity`.
- *Rationale:* a model-building round runs for hours to days, with about 10 admissions, several
  template puts and many decisions. The 24-hour message age (`controlplane/store.go:39-40`) forces
  the operator back mid-round for authority they already gave.
- *Acceptance:*
  - (a) a grant for `governance` on workflow `mosaic-area` authorizes a put of `mosaic-area` on day
    3, and refuses a put of `default`;
  - (b) a revoked grant is refused;
  - (c) a grant naming `runtime` is refused at creation.

### Commits, content policy and push (§7, §9, §16)

**FAE-CTL-109 (MUST)** A target configuration MAY declare:
- `commit_identity: {name, email}`;
- `content_policy: {deny_literals, deny_patterns}`, case-insensitive;
- `deny_paths: [globs]`.

These apply as follows:
- VcsCommit, Integrate and `fae land` MUST commit as `commit_identity`, which replaces
  `effects/broker.go:894`'s fixed `Fae <fae@localhost>`. Fae's own identity MAY be added as a
  `Co-authored-by` trailer.
- Before any commit, integration or landing, the daemon MUST scan the added lines of the diff, the
  commit message and the paths for `content_policy`. A match MUST refuse with the policy entry's
  index, never its text. The scan MUST NOT be skippable by content or authority.
- `deny_paths` MUST extend `workflow/protected_path.go`. A path matching it can never enter any
  task's scope, operator-declared files included, nor any read root's readable set, nor any
  commit.
- Policy text is a secret-like value: it MUST NOT appear in events, logs, artifacts or briefs
  (FAE-SEC-003).
- *Rationale:* mosaic commits under the user's identity, and must never publish certain names or
  open certain files (age-encrypted keys, TLS keys, `.env` files in a snapshot). Today these are
  instructions to agents, which is what FAE-WF-042 says not to rely on.
- *Acceptance:*
  - (a) a commit on a target with `commit_identity` has that author;
  - (b) a diff adding a denied literal is refused, and the refusal names the entry index only;
  - (c) a declared file matching `deny_paths` is refused at admission, even from the operator;
  - (d) a scan of logs and events finds no policy text.

**FAE-CTL-110 (SHOULD)** A target configuration MAY declare `push: {remote, branches, mode:
fast-forward-only}`, and a new ExternalEffect kind `git-push`.
- It MUST be reachable in Local mode only for the declared remote and branches.
- It MUST be preceded by the protected-commit floor's gates and by FAE-CTL-109's content scan on
  the pushed range.
- It MUST be idempotent on (remote, branch, sha).
- *Rationale:* mosaic pushes to its own private remote after a round. Today the only push path is
  the Normal-mode code-review sub-workflow.
- *Acceptance:*
  - (a) a push to an undeclared branch is refused;
  - (b) a repeated push of the same sha is recorded as adopted;
  - (c) a pushed range with a denied literal is refused.

### Document workflows and the floors (§4.7, §12.4)

**FAE-CTL-113 (MUST)** A target configuration MAY declare `document_globs` and, for them,
`document_checks` (check commands, FAE-CTL-105, each with a required count field).
- When the target's diff classifier proves that a task's diff touches only `document_globs`:
  - the protected-commit floor's test-run requirement MUST be satisfied by a passing
    `document_checks` run on the committed tree, with a positive count;
  - `fae land`'s required test filter, format and compile gates MUST be replaced by the
    `document_checks` and the target's always-required checks.
- The independent-Review requirement and every other floor MUST stay unchanged.
- A diff that touches any other path MUST get the full code gates.
- *Rationale:* a merged ontology is not code. Requiring a Go test filter and Go format gates for a
  YAML-only landing either blocks it or invents a meaningless test. The diff classifier already
  governs the no-red exception (FAE-WF-073) in the same way.
- *Acceptance:*
  - (a) a YAML-only diff lands on a passing model check with a positive count and a review;
  - (b) the same diff with one `.go` file needs the full code gates;
  - (c) a document check reporting `checked: 0` fails the landing.

### Observability (§13)

**FAE-CTL-112 (MUST)** `Events`, both the paged read and `/v1/events`, MUST accept filters on
`task`, `run_id`, `workflow_id` and event type. A read `RunReport(run_id)` MUST return, per task
of the run:
- state and current stage;
- every gate record's name and value;
- each output artifact's id and type;
- turns, tokens and wall time per role.

It MUST be consistent with the event stream at a stated sequence number.
- *Rationale:* a coordinator follows about 13 tasks per round. Paging the instance-wide stream and
  joining histories by hand is what a run report replaces. It also feeds `RESULTS.md`.
- *Acceptance:*
  - (a) a filtered subscription on one `run_id` receives only its tasks' events, with gaps
    signalled as today;
  - (b) `RunReport` for a scripted run of three tasks lists every gate record of each.

## Open questions

1. **Where does the coordinator live?** This assessment keeps it outside fae, as a Controller.
   Making it a fae role would need a role that can author templates and admit tasks, which
   FAE-OPS-001 forbids to workflow roles. That is probably right.
2. **Blind by task or by stage?** FAE-CTL-106 makes it per stage. The cheaper alternative is to
   keep blind roles in separate tasks and only filter the path list.
3. **One template per round, or one with parameters?** With FAE-CTL-107 and FAE-WF-099, briefs
   can stay stable and per-round content can go in inputs. Per-round revisions are still useful
   when a round changes the graph.
4. **`mcheck` in the broker.** `go run` compiles on every call. Should the target pin a prebuilt
   `check` binary, with its digest, as the allowlisted program?

## Until fae has these

Mosaic keeps `mosaic compose` (`.claude/skills/mosaic-generate/compose/`) and headless agents
with full read tools. FAE-CTL-101, -102 and -105 are the minimum for a first real round on fae.
FAE-CTL-104 and -106 are needed for a faithful one, and FAE-CTL-109 before any commit leaves the
machine.

---
name: mosaic-generate
description: Coordinate building a mosaic ontology of a whole repository with parallel area agents, through the eight-stage generation pipeline (inventory, skeleton and contracts, fixtures, fan-out, reconciliation, test oracle, judging, results), ending every build and fix round with a blind re-measurement. Use this whenever the user wants to generate, regenerate or benchmark an ontology of a large codebase from its source, write a per-repo profile, brief area agents, run a reconciliation round, turn a repo's tests into scenarios, or judge a generated model against well-known behavior. It also applies to "map all of <repo> into mosaic", "fan this out to agents", or "how good is the generated model". For editing one ontology by hand, use mosaic-ontology and mosaic-simulation instead.
---

# Mosaic generation pipeline (coordinator)

> Requires mosaic with DESIGN §11 (in progress): config and fixture entities, instances,
> `parallel`/`join`, multi-step scenarios, trace assertions, and the check flags
> `--behavior-coverage`, `--lint hollow,trivial`, `--no-mocks`, `--min-modeled`,
> `--min-substantive`, `--max-trivial`, `--tests`, `--min-test-reach`, `--features`,
> `--strict-features`, `--lint racy,seam-names`, `--max-racy`, `--max-seam-names`, `--contract`
> and `--max-contract-issues`.

You are the coordinator. You don't write fragments. You fix the contracts, author the shared
worlds, brief and launch agents, make binding decisions, and keep the gates honest. The runbook,
with every command and exit criterion, is `docs/PIPELINE.md`. Read it first.

## Inputs you prepare

1. **The profile**, `examples/<repo>/profile.yaml`, copied from
   `examples/_profile-template/profile.yaml`. Every repo-specific fact goes there: the snapshot,
   inventory plugins and kinds, areas with owned paths and overrides, naming, the error
   convention, shared shapes and seams, shared data with one owner each, config sources,
   instances and fixtures, the test oracle, the user-visible features, independence rules and
   scale targets.
2. **Briefs rendered from the templates** in `templates/`. Each `{{placeholder}}` names a profile
   field (`{{snapshot.path}}`, `{{naming.interface}}`, `{{areas}}`). Render lists as tables.
   Two are derived rather than stored: `{{areas.count}}` and `{{inventory.counts}}` (from
   `inventory.json`). `<N>` and `<...>` marks are yours to fill from the run. Keep the rules'
   wording: each one exists because a build broke without it.

| Template | Rendered to | Stage | Audience |
|---|---|---|---|
| [templates/BRIEF.md](templates/BRIEF.md) | `BRIEF.md` | 4 | every area agent |
| [templates/RECONCILE.md](templates/RECONCILE.md) | `RECONCILE.md` | 5 | every area agent |
| [templates/ORACLE.md](templates/ORACLE.md) | `oracle/ORACLE.md` | 6 | oracle agents |
| [templates/BENCHMARK.md](templates/BENCHMARK.md) | `BENCHMARK.md`, then `BENCHMARK<n>.md` | before 4; before each later round | a separate agent writes it; judges |
| [templates/JUDGE.md](templates/JUDGE.md) | `judge/JUDGE.md` | 7 | judges |

## The stages

1. **Inventory.** Run the scanner with the profile's plugins. Audit precision by reading a
   sample, and recall against independent lists. Turn false-positive classes into skip rules.
2. **Skeleton and contracts.** Write `skeleton.yaml`: deployables and modules with owners,
   shared components, shared schemas, and boundary stubs for every seam you can already see,
   with the owner's shapes. Fix the naming rules and the error table in the profile.
   - **Features.** Write the profile's `features` (`[{id, summary, sources, owner}]`) from the
     docs, config flags and CLI options, before fan-out. Each owning area models a feature as a
     flow tagged `feature:<id>` or skips it in `skips/<area>.features.json` with a valid reason.
   - **Contracts.** Extract what the API spec doesn't cover (zod and tRPC routers, SSE
     emitters with their frames and terminator, event bodies) into `contracts/*.yaml`
     (`contracts: [{id, match, request, response, errors, stream, sources}]`, citing the code).
     The full gate passes each with `--contract FILE` and `--max-contract-issues 0`.
   - **Test targets.** Run `scripts/test_targets.py <ws>`: it maps every test file to the code it
     tests (`test-targets.json`) and prints the share resolved. Expect above 90%; add
     `oracle.area_globs` or read the unresolved tests when it is lower.
3. **Fixtures.** Write `fixtures.yaml`: the shared worlds (topology, clock, config overrides,
   seed state), and a reference (`attributes: {boundary: true, owner: <area>}`, deployed `value`,
   code `default`, both cited) for each shared config. Configs belong to the area that reads them,
   which defines the real entity. Add a smoke scenario per fixture. Put the profile's
   `shared_data` (one owner per datum, the readers) into the brief.
4. **Fan-out.** Write `BENCHMARK.md` now, before anyone builds, and keep it from builders. Then
   launch one agent per area, in parallel, each with `BRIEF.md` and its area id. Each one owns
   only `fragments/<area>.yaml`, `notes/<area>.md`, `skips/<area>.json` and
   `skips/<area>.features.json`.
   - **4b. Oracle in the build.** Before launch, draw each area's in-build sample with
     `scripts/sample_tests.py <ws> --area <id>` (3 tests from its own paths, written to
     `build-oracle/<area>.json`). The agent translates them into scenarios in its own fragment
     and makes them pass, or records each as `untranslatable` or `sim-gap`, before hand-off.
5. **Reconciliation.** Merge everything and run the full gate. Split the failures per area and
   group them by root cause. Write `RECONCILE.md` with one numbered decision per cause, then
   relaunch the areas. Run `scripts/assign_inventory.py <ws> --worlds`: it merges the skips into
   the inventory (rejecting a "covered by" skip without a `covered_by` entity that exists) and
   regenerates `worlds.yaml` from the profile and every `<area>-seed`. Require
   `--strict-coverage`.
6. **Test oracle.** Draw the final sample with `scripts/sample_tests.py <ws> --exclude-sample
   "<ws>/build-oracle/*.json"`, so it shares no test with stage 4b, and launch oracle agents on
   it. Each failure is a model bug, filed to its owner, or a simulator gap. The sample is
   unit-weighted: tests sitting with code their area owns are drawn at the repo's share
   (`--unit-share F` overrides), because areas model the request path and miss unit-level rules.
   `--unit function` samples test functions instead of files (one per file otherwise); with no
   `--unit`, an empty sample, or one under `--min-size N`, switches to functions on its own. In
   a component-scope (child) run, use `--unit function --reach-from <parent>/test-targets.json`
   in every draw, so the parent's tests that reach the scope join the pool.
7. **Judging.** Launch one judge per benchmark group. Judges verify every expectation against
   the code before they score.
8. **Results.** Write `RESULTS.md`: build counts, coverage, oracle verdicts, scorecards,
   corrected expectations, wrong claims to fix, and ranked simulator gaps.
9. **Blind re-measurement, at the end of every build and fix round.** Before round n starts, have
   a separate agent, one that builds nothing, write `BENCHMARK<n>.md` with new cases. When the
   round's fixes pass the gate, draw `oracle<n>/sample.json` with `--out` and `--exclude-sample`
   over every earlier sample (`build-oracle/*.json`, `oracle*/sample.json`). Fresh judges and
   oracle agents score both. Builders never read these files. Report the blind scores as the
   round's; re-scores of seen cases are regression checks, reported apart. In one gateway-platform
   build, 38 of 45 seen benchmark cases passed and 10 of 40 blind ones did.

## Rules you enforce

- **Gates are not negotiable.** Each hand-off runs the full gate in `docs/PIPELINE.md`
  (`--strict-citations --inventory --min-modeled 0.5 --min-substantive 0.5 --max-trivial 0.35
  --tests <ws>/test-targets.json --min-test-reach 0.5 --features <ws>/profile.yaml
  --strict-features --behavior-coverage --lint hollow,trivial,racy,seam-names --max-racy 0
  --max-seam-names 0 --no-mocks`) plus two `--cite-sample` rounds. The
  hollow lint also requires each flow tagged `writes` to have a write-then-read scenario. The
  trivial lint and the substantive count keep thin behaviors (only a `return`, or a set or two)
  from passing as modeled. Test reach and the feature list keep an area from passing on its
  inventory while the features users rely on, and the code the project tests, go unmodeled.
  The racy and seam-names lints catch what no scenario sees: compare-and-set written as
  read-then-write, and one field spelled two ways across a seam.
- **The reported score is the blind one.** A case a builder fixed against stops measuring the
  model. Every round's score comes from a benchmark written before it and an oracle sample no
  earlier round drew, scored by agents who didn't build.
- **Limiters, not counters; both sides of a failure.** Rate limits and back pressure are
  `limiters` keyed by what the code keys on (IP, org, key, dimension). A two-sided failure
  (`sides` in the profile) counts as covered only when each owner covers its side.
- **One owner per shared datum.** The profile's `shared_data` names who holds, say, an open
  document's text; other areas read it through the owner's interfaces and never keep a copy.
- **Config, not numbers.** Behaviors read every deployed value as `config['<id>']`, durations
  included (`timeout_ms: "= config['write-request-timeout-ms']"`). "Passes its own scenarios" proves only internal consistency.
- **Contracts before fan-out.** Anything two areas must agree on (names, shapes, errors, seams,
  the world) is fixed in stages 2 and 3. A contract retrofitted mid-build costs a round.
- **Fix through the generator.** When an area's fragment is generated (`gen/<area>/`), its
  fixes go into the generator, and a regeneration must reproduce the fragment byte for byte.
  Direct edits are lost on the next rebuild. In the VS Code fix round, 6 of 13 areas did this.
- **Breaking changes toward the code are welcome.** When an owner corrects an interface to match
  the code and that breaks callers, keep the break. Don't add shims or parallel interfaces. The
  owner lists every broken caller (area, interface or scenario, what it must now read) under
  "Breaking changes" in its notes and its report. You route each one to its owner, and report
  them to the user as findings.
- **Decide, don't mediate.** In reconciliation, the owner's contract wins unless it is wrong
  about the code. Name the owner and the exact shape in each decision.
- **Independence.** The oracle reads the repo's tests and never runs them. Builders never see any benchmark, oracle sample or judge's file, of any round, or each other's notes.
  Judges and oracle agents never edit the model. You read everything, and you write only
  coordinator files.
- **Parallel agents, disjoint paths.** Launch the areas together, each with explicit file
  ownership. A failure caused by another area's unfinished fix gets reported, not worked around.
- **Feed the roadmap.** Every "simulator gap" from notes, the oracle and the judges goes into
  `RESULTS.md`, ranked by how many areas and cases hit it.

## When you're done

Report the merged entity counts, the final gate lines (validation, citations, coverage, behavior
coverage, hollow, racy and seam-names lints, test reach, features, mocks), the blind oracle verdicts
and benchmark scorecard with root causes (seen re-scores apart), the
number of expectations corrected, and the top simulator gaps.

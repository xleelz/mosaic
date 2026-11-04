<!--
Template: judge brief (pipeline stage 7). Render into {{workspace}}/judge/JUDGE.md. The coordinator
assigns each judge one group from {{benchmark.groups}}. Requires mosaic with DESIGN §11 (in
progress).
-->

# Judge brief: does the {{name}} ontology map the system correctly?

You are an independent judge. {{areas.count}} area agents built `{{workspace}}/{{id}}.json` from
the code of {{snapshot.repo}} at {{snapshot.ref}}: <N> components, <N> interfaces, <N> flows and
<N> scenarios, all passing, with <N> citations that all resolve, and a test-oracle verdict of
<N> of <N> passing. Passing its own scenarios proves only internal consistency. Your job is to
find out whether the model is **right about the system**.

## Sources

- **Code (ground truth):** `{{snapshot.path}}`, read-only. The deployed configuration comes from
  {{config.sources}}, in that order.
- **Independent expectations:** `{{workspace}}/{{benchmark.file}}` (your group), the docs, and the
  tests under {{oracle.test_dirs}}.
- **The model:** `{{workspace}}/{{id}}.json` (merged), with the shared worlds in `fixtures.yaml`.
  You may read the fragments and the notes to find things, but judge the merged document.
- **How mosaic works:** `.claude/skills/mosaic-simulation/SKILL.md` and its references;
  `docs/DESIGN.md` §2–5 and §11.
- **Secrets:** never open {{snapshot.forbidden}}. Never copy a token, key, password or internal
  hostname into a scenario, your notes or your report.

## Step 1: verify each expectation against the code

Before you score a case, confirm or correct its expected outcome from the code: the classes,
methods and config lines involved. The benchmark was written from docs and common knowledge, and
expectations are often wrong for the deployed version or configuration. A corrected expectation
replaces the original. Record each correction with citations. **Never score the model against an
expectation you haven't verified.**

## Step 2: run each case against the model

Write each case as a small fragment, `judge/scenarios/<CASE>.yaml`:

```yaml
schema_version: 1
id: {{id}}
scenarios:
  - id: bench-<case>
    flow: <an existing flow>            # or omit, with steps
    fixtures: {{benchmark.default_world}}
    config: {}                          # overrides, by config id
    state: {}                           # per instance: "<component>@<instance>"
    faults: []                          # with instance and calls to hit one peer
    steps: []                           # for multi-step cases: write then read, prepare then execute
    expect: []                          # the verified outcome AND the code's path (trace assertions)
```

Use only fixtures, inputs, `state`, `config`, `choices`, `faults` and `steps`. **Never edit the
ontology or the fragments, and never use mocks.** Prove the path, not just the outcome: assert on
`trace` (which instance received which call, in which order, and what was `late`), on `state` per
instance, and on step results.

```sh
cd <mosaic repo>
export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
go run ./internal/devtools/check -f {{workspace}}/{{id}}.json -f {{workspace}}/judge/scenarios/<CASE>.yaml \
  --no-mocks -v --trace
```

## Step 3: score

**Score every labeled step, exactly as the benchmark labels it.** A case broken into steps (a),
(b), (c) gets one score per step, under the benchmark's own letters: don't merge steps, split
them, add your own, or skip one you didn't reach (score it `missing`, and say why). Step counts
are compared across rounds, so they must match the benchmark's. A corrected expectation keeps its
step's letter. The case scores its worst step, in the order fail, missing, sim-gap, partial,
pass (worst first); a case passes only when every step passes.

| Score | Meaning |
|---|---|
| **pass** | The verified outcome **and** the code's path are reproduced |
| **partial** | The outcome is right but the path is wrong or incomplete; or the behavior is modeled but the scenario can't drive it without an ontology edit (say what edit) |
| **fail** | The model produces a different outcome from the code |
| **missing** | The behavior isn't modeled |
| **sim-gap** | Modeled as well as mosaic allows, but the simulator can't express it. Name the missing feature |

For every case that isn't a pass, name the root cause, one or more of:
- **model**: which entity is wrong, and what the code says, with a citation;
- **contract**: a seam between areas (shapes, ids, a world the areas disagree on);
- **world**: a fixture or config value that is wrong or missing;
- **simulator**: the missing mosaic feature;
- **benchmark**: the expectation was wrong (record the correction).

## Step 4: spot-check faithfulness beyond the benchmark

For the flows your cases touch, read each behavior next to its cited code. Check 10 or more
citations:

```sh
go run ./internal/devtools/check -f {{workspace}}/{{id}}.json --code {{snapshot.path}} --cite-sample 10 --seed <n>
```

Report wrong claims: places where the model says something the code doesn't do, with citations.
Check that the covered entry points in your group are covered by an entity that models them, not
one that only cites nearby lines. Verify the builders' "docs versus code" findings in your group:
confirmed or refuted.

## Output

Write `judge/<group>.md` with:
1. one row per case: ID, verified expectation (corrected?), each step's score, the case score,
   root cause, evidence;
2. wrong claims found in the model;
3. builder findings confirmed or refuted;
4. simulator gaps, with the case that exposed each.

Also write `judge/<group>.json`: an array of
`{"case", "score", "cause", "expectation_corrected": bool, "steps": {"a": "<score>", ...}, "summary"}`,
one row per case in your group, with every labeled step in `steps` (a case without lettered steps
gives `{"a": <its score>}`). Before you finish, check that the steps you scored equal the steps
your group labels, case by case.

Write only your own files under `judge/`. Don't commit.

## Report (≤150 words)

Scores per case and steps scored (= steps labeled), the corrected expectations, the top 3 wrong claims, and the top simulator gaps.

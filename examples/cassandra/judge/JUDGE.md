# Judge brief: does the Cassandra ontology map Cassandra correctly?

You are an independent judge. Eleven area agents built `examples/cassandra/cassandra.json` from
the Cassandra 5.0.9 code: 502 components, 1,365 interfaces, 270 flows and 1,165 scenarios, all
passing, with 4,525 citations that all resolve. Passing its own scenarios proves only internal
consistency. Your job is to find out whether the model is **right about Cassandra**.

## Sources

- Code (ground truth): `/home/lbethay/.cache/cassandra-bench/cassandra-5.0.9`, read-only. The
  deployed config is `conf/cassandra.yaml`, falling back to `src/java/org/apache/cassandra/config/Config.java`.
- Independent expectations: `examples/cassandra/BENCHMARK.md`, the docs under `doc/modules/`, and
  the tests under `test/unit` and `test/distributed`.
- The model: `examples/cassandra/cassandra.json` (merged). You may read the fragments in
  `examples/cassandra/fragments/` and the notes in `examples/cassandra/notes/` to find things, but
  judge the merged document.
- How mosaic works: `.claude/skills/mosaic-simulation/SKILL.md` and
  `.claude/skills/mosaic-simulation/references/behavior-language.md`; `docs/DESIGN.md` §2–5.

## Step 1: verify each benchmark expectation against the code

Before you score a case, confirm or correct its expected outcome from the code: the classes,
methods and config lines involved. The benchmark was written from docs and common knowledge,
and some expectations may be wrong for 5.0.9 or for the deployed config. A corrected expectation
replaces the original. Record the correction with citations. Never score the model against an
expectation you haven't verified.

## Step 2: run each case against the model

Write a scenario for each case as a small fragment, `examples/cassandra/judge/scenarios/<CASE>.yaml`:

```yaml
schema_version: 1
id: cassandra
scenarios:
  - id: bench-w2
    flow: <an existing flow id>
    input: {...}
    state: {...}        # e.g. gossiper.endpoint_state_map to mark nodes down
    choices: {...}
    faults: [...]
    expect: [...]       # assertions proving the verified outcome AND the code's path
```

Use only inputs, `state`, `choices` and `faults`. **Never edit the ontology or the fragments.**
Run it with:

```sh
cd /home/lbethay/workplace/mosaic
PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly go run ./internal/devtools/check \
  -f examples/cassandra/cassandra.json -f examples/cassandra/judge/scenarios/<CASE>.yaml -v
```

`-v` prints the run, so you can read the trace and confirm the path (components, verbs,
decisions), not just the result. The cluster convention is in `examples/cassandra/BRIEF.md`
("Cluster convention"), and the cluster state contract is membership's: nodes `10.0.0.1` (this
node), `.2` and `.3`, RF 3, and `gossiper.endpoint_state_map.<ep>.alive`.

## Step 3: score

| Score | Meaning |
|---|---|
| **pass** | The verified outcome **and** the code's path are reproduced |
| **partial** | The outcome is right but the path is wrong or incomplete; or the behavior is modeled but the scenario can't drive it without an ontology edit (say what edit) |
| **fail** | The model produces a different outcome from the code |
| **missing** | The behavior isn't modeled |
| **sim-gap** | Modeled as well as mosaic allows, but the simulator can't express it. Name the missing feature |

For every case that isn't a pass, name the root cause:
- **model**: which entity is wrong, and what the code says, with a citation;
- **contract**: a seam between areas;
- **simulator**: the missing mosaic feature;
- **benchmark**: the expectation was wrong.

## Step 4: spot-check faithfulness beyond the benchmark

For the flows your cases touch, read each behavior next to its cited code. Check 10 or more
citations with
`go run ./internal/devtools/check -f examples/cassandra/cassandra.json --code <checkout> --cite-sample 10 --seed <n>`.
Report wrong claims, meaning places where the model says something the code doesn't do, with
citations. Also verify the code findings the builders made in your areas, which their notes list
under docs or common knowledge versus code: confirmed, or refuted.

## Output

Write `examples/cassandra/judge/<group>.md`, with:
1. one table row per case: ID, verified expectation (corrected?), score, root cause, evidence;
2. wrong claims found in the model;
3. builder findings confirmed or refuted;
4. simulator gaps, with the case that exposed each.

Also write `examples/cassandra/judge/<group>.json`: an array of
`{"case", "score", "cause", "expectation_corrected": bool, "summary"}`.

Write only your own files under `examples/cassandra/judge/`. Don't commit.

## Report (≤150 words)

Scores per case, the corrected expectations, the top 3 wrong claims, and the top simulator gaps.

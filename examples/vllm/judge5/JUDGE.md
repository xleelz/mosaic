# Judge brief: does the vLLM 0.32 (built from code) ontology map the system correctly?

You are an independent judge. 9 area agents built `examples/vllm/vllm.json` from
the code of vllm-project/vllm at v0.32.0: 659 components, 2,645 interfaces, 276 flows and
1,805 scenarios, all passing, with every citation resolving. The test oracle runs in parallel
with you, so its verdicts aren't available to you. Passing its own scenarios proves only internal consistency. Your job is to
find out whether the model is **right about the system**.

## Sources

- **Code (ground truth):** `/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`, read-only. The deployed configuration comes from
  | path | role | format |
|---|---|---|
| vllm/config/*.py (pydantic Field defaults) and vllm/engine/arg_utils.py (EngineArgs defaults) | default | code |
| the fixture's deployment (engine args given to `vllm serve`) | deployed | fixture |, in that order.
- **Independent expectations:** `examples/vllm/BENCHMARK5.md` (your group), the docs, and the
  tests under `tests`.
- **The model:** `examples/vllm/vllm.json` (merged), with the shared worlds in `fixtures.yaml`.
  You may read the fragments to find things, but judge the merged document.
- **How mosaic works:** `.claude/skills/mosaic-simulation/SKILL.md` and its references;
  `docs/DESIGN.md` §2–5 and §11.

## Blind rules

- **Never read** `BENCHMARK.md`, `BENCHMARK2.md`, `BENCHMARK3.md`, `BENCHMARK4.md`, `judge/**`, `judge2/**`, `judge3/**`, `judge4/**`, `oracle/**`, `oracle2/**`, `oracle3/**`, `oracle4/**`, `oracle5/**`, `notes/**`, `RESULTS.md`,
  `FIXES*.md`, `RECONCILE.md`, `reconcile/**` or `build-oracle/**`. This is a blind re-measurement:
  score only what the model and the code say.
- Only edit files under `examples/vllm/judge5/`. Never edit the model.

- **Worlds.** Start from a `full-*` world in `worlds.yaml`. Including `full-tp2-llama-8b`, `full-moe-mixtral-8x7b-tp2-ep`, `full-vl-qwen2-vl-7b`, `full-fp8-llama-3-8b`, `full-fp8-llama-3-8b-kv-fp8`. A case that names another model (for example a Qwen3 MoE) starts from the closest world, with `state` and `config` on top; when that can't express it, score root cause **world** and say what's missing.
- **Steps.** Score every labeled step in your group exactly as BENCHMARK5.md labels them (its "Scoring" section), so step counts compare across rounds.

## Step 1: verify each expectation against the code

Before you score a case, confirm or correct its expected outcome from the code: the classes,
methods and config lines involved. The benchmark was written from docs and common knowledge, and
expectations are often wrong for the deployed version or configuration. A corrected expectation
replaces the original. Record each correction with citations. **Never score the model against an
expectation you haven't verified.**

## Step 2: run each case against the model

Write each case as a small fragment, `judge5/scenarios/<CASE>.yaml`:

```yaml
schema_version: 1
id: vllm
scenarios:
  - id: bench-<case>
    flow: <an existing flow>            # or omit, with steps
    fixtures: `full-tp1-llama-8b`
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
go run ./internal/devtools/check -f examples/vllm/vllm.json -f examples/vllm/judge5/scenarios/<CASE>.yaml \
  --no-mocks -v --trace
```

## Step 3: score

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
go run ./internal/devtools/check -f examples/vllm/vllm.json --code /home/lbethay/.cache/mosaic-bench/vllm-0.32.0 --cite-sample 10 --seed <n>
```

Report wrong claims: places where the model says something the code doesn't do, with citations.
Check that the covered entry points in your group are covered by an entity that models them, not
one that only cites nearby lines. Verify the builders' "docs versus code" findings in your group:
confirmed or refuted.

## Output

Write `judge5/<group>.md` with:
1. one row per case: ID, verified expectation (corrected?), score, root cause, evidence;
2. wrong claims found in the model;
3. builder findings confirmed or refuted;
4. simulator gaps, with the case that exposed each.

Also write `judge5/<group>.json`: an array of
`{"case", "score", "cause", "expectation_corrected": bool, "summary"}`.

Write only your own files under `judge5/`. Don't commit.

## Report (≤150 words)

Scores per case, the corrected expectations, the top 3 wrong claims, and the top simulator gaps.

## vLLM specifics

- **Worlds.** Start from `full-tp1-llama-8b` (default), `full-tp4-llama-70b`,
  `full-small-batch-limits` or `full-prefix-caching-off`, plus area fixtures, such as
  scheduler-kv's nearly-full and prefix-warm worlds and models-layers' LoRA world.
- **The merged model:** `examples/vllm/vllm.json`.
- **Concurrency is opt-in.** Use `await: false`, `token`/`cancel` and `rendezvous` where the
  case overlaps work (DESIGN §13.1 items 14, 16 and 17). Time is in µs, and `duration_us` is
  available.
- **Watch for** latency coefficients the builders labeled as assumptions. Judge the control
  flow, the decisions and the state against the code; don't treat assumed throughput numbers
  as facts.

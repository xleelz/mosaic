# Judge brief: does the Visual Studio Code 1.144 (built from code) ontology map the system correctly?

You are an independent judge. 13 area agents built `examples/vscode/vscode.json` from
the code of microsoft/vscode at 1.144.0: <N> components, <N> interfaces, <N> flows and
<N> scenarios, all passing, with <N> citations that all resolve, and a test-oracle verdict of
<N> of <N> passing. Passing its own scenarios proves only internal consistency. Your job is to
find out whether the model is **right about the system**.

## Sources

- **Code (ground truth):** `/home/lbethay/.cache/mosaic-bench/vscode-1.144.0`, read-only. The deployed configuration comes from
  the registerConfiguration defaults and product.json, in that order.
- **Independent expectations:** `examples/vscode/BENCHMARK.md` (your group), the docs, and the
  tests under src/vs/**/test, extensions/*/src/test, test/integration.
- **The model:** `examples/vscode/vscode.json` (merged), with the shared worlds in `fixtures.yaml`.
  You may read the fragments and the notes to find things, but judge the merged document.
- **How mosaic works:** `.claude/skills/mosaic-simulation/SKILL.md` and its references;
  `docs/DESIGN.md` §2–5 and §11.

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
id: vscode
scenarios:
  - id: bench-<case>
    flow: <an existing flow>            # or omit, with steps
    fixtures: `full-window` (worlds.yaml)
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
go run ./internal/devtools/check -f examples/vscode/vscode.json -f examples/vscode/judge/scenarios/<CASE>.yaml \
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
go run ./internal/devtools/check -f examples/vscode/vscode.json --code /home/lbethay/.cache/mosaic-bench/vscode-1.144.0 --cite-sample 10 --seed <n>
```

Report wrong claims: places where the model says something the code doesn't do, with citations.
Check that the covered entry points in your group are covered by an entity that models them, not
one that only cites nearby lines. Verify the builders' "docs versus code" findings in your group:
confirmed or refuted.

## Output

Write `judge/<group>.md` with:
1. one row per case: ID, verified expectation (corrected?), score, root cause, evidence;
2. wrong claims found in the model;
3. builder findings confirmed or refuted;
4. simulator gaps, with the case that exposed each.

Also write `judge/<group>.json`: an array of
`{"case", "score", "cause", "expectation_corrected": bool, "summary"}`.

Write only your own files under `judge/`. Don't commit.

## Report (≤150 words)

Scores per case, the corrected expectations, the top 3 wrong claims, and the top simulator gaps.

## VS Code specifics

- **Worlds.** Start from the merged worlds in `worlds.yaml`. `full-window` is the default; the
  others are `full-two-windows`, `full-untrusted`, `full-dirty-editor`, `full-format-on-save` and
  `full-auto-save-after-delay`. Area fixtures (`remote-server-srv1`, `notebook-webview-notebook-open`,
  ...) may be added on top.
- **The merged model.** `examples/vscode/vscode.json`. Run a case with:
  `go run ./internal/devtools/check -q -f examples/vscode/vscode.json -f examples/vscode/judge/scenarios/<CASE>.yaml --scenario '^bench' --trace`.
- **What to look out for.** The coordinator measured that many entry interfaces in chat (59%),
  agents (42%) and remote-server (37%) have trivial behaviors (a bare return, or a set). When a
  case runs through one, check whether the code really is that simple. If it isn't, the case is
  `partial` with cause `model`.

<!--
Template: test-oracle brief (pipeline stage 6). Render into {{workspace}}/oracle/ORACLE.md. The
coordinator gives each oracle agent an area and its list of sampled tests (seeded, from
{{oracle.test_dirs}}, at least {{oracle.sample.per_area_min}} per area).
Requires mosaic with DESIGN §11 (in progress).
-->

# Oracle brief: turn the repo's own tests into scenarios

The merged ontology `{{workspace}}/{{id}}.json` was built from the code of {{snapshot.repo}} at
{{snapshot.ref}} by area agents, and all its own scenarios pass. That proves internal consistency
only. The repo's tests were written by people who know what the code must do. Your job is to
translate a sample of them into mosaic scenarios and find out whether the model agrees.

## Sources

- **The tests:** your assigned list, under `{{snapshot.path}}`. The oracle reads tests and
  never runs them: **never build or run anything in the snapshot**.
- **The code** (ground truth when a test and the model disagree): `{{snapshot.path}}`, read-only.
- **The model:** `{{workspace}}/{{id}}.json`, and `fixtures.yaml` for the shared worlds. You may
  read the fragments to find entities.
- **Never read** {{independence.oracle_never_read}}.
- How mosaic works: `.claude/skills/mosaic-simulation/SKILL.md` and its references.

## One entry, one verdict

Your list is the sample's entries for your area. **Cover every entry**: skipping one silently
breaks the round-to-round comparison, so an entry you can't finish still gets a row, with the
verdict that fits (`untranslatable` or `sim-gap`) and the reason.

**Each entry gets exactly one verdict**, even when it is a whole test file or class rather than
one test method. Then translate each of its methods (or parametrized cases) as a sub-scenario,
`oracle-<area>-<test-slug>-<method-slug>`, and give each a verdict of its own. The entry's verdict
is `pass` only if every sub-verdict is `pass`; otherwise it is the worst sub-verdict, in the order
`model-bug` (worst), `sim-gap`, `untranslatable`, `test-mismatch`, `pass`. Never split an entry
into several rows: one entry split into 16 rows broke a round's comparability.

## For each test

1. **Understand what it proves.** Name the behavior in one sentence, and the code under test
   (class and method, with `path:line`).
2. **Map it to the model.** Find the flow or interface that runs the code under test. If none
   exists, the verdict is `model-bug` (missing), and you say what's missing.
3. **Translate**, without editing the model:

   | Test part | Scenario part |
   |---|---|
   | setup: cluster, schema, tenants, open documents, loaded model | `fixtures: [...]` first, then `topology`, `config` and `state` on top |
   | configuration overrides | `config: {<id>: value}`; the config ids are in the model's `configs` |
   | each act call (request, RPC, user action, scheduler tick) | one entry in `steps`, with `flow` or `interface`, `input`, `on`, `at_ms` (a step starts after the previous one's emits and timers finish; acts that overlap in the test use `at_ms` or `await: false`, and concurrent sends inside one act use `parallel`) |
   | injected failures (a node down, a dropped message, a slow peer) | `faults` with `instance` and `calls` |
   | asserted return values | `expect` over `steps.<as>.result` and `result` |
   | asserted stored effects | `expect` over `state` (per instance: `state['<component>@<instance>']`) |
   | asserted effective settings or placement | `expect` over `config`, `topology`, `calls_by_instance['<interface>@<instance>']` |
   | asserted interactions (this was sent, in this order, to that node) | `expect` over `trace`, e.g. `trace.exists(e, e.type == 'call.start' && e.interface == '...' && e.instance == 'n2')` |
   | elapsed time, timeouts | `expect` over `steps.<as>.duration_ms`, `duration_ms`, error codes |

   Use only fixtures, inputs, `state`, `config`, `choices`, `faults` and `steps`. **No mocks.** If a
   test mocks a collaborator, drive the real collaborator in the model through its state instead.
   A test that can only pass with a mock is `untranslatable` or a `sim-gap`; say which.
4. **Run it** against the merged model:

   ```sh
   cd <mosaic repo>
   export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
   go run ./internal/devtools/check -f {{workspace}}/{{id}}.json -f {{workspace}}/oracle/<area>.yaml \
     --no-mocks --lint hollow -v
   go run ./internal/devtools/check -f {{workspace}}/{{id}}.json -f {{workspace}}/oracle/<area>.yaml \
     --scenario '^oracle-<area>-<test>$' --trace
   ```

5. **Give a verdict.** Never change the expectations to match the model.

   | Verdict | Meaning |
   |---|---|
   | `pass` | The scenario reproduces the test's asserted outcome, and the trace takes the code's path |
   | `model-bug` | The model disagrees with the test, and the code agrees with the test. Name the entity and cite the code |
   | `test-mismatch` | The test asserts something the code at {{snapshot.sha}} doesn't do (a stale or disabled test). Cite the code |
   | `sim-gap` | The model is as right as mosaic allows, but the simulator can't express it. Name the missing feature |
   | `untranslatable` | The test checks something below the model's level (byte layout, a parser's internals). Say what |

## Output

- `oracle/<area>.yaml`: a fragment with `schema_version: 1`, `id: {{id}}`, and only
  `scenarios` (ids `oracle-<area>-<test-slug>`). Each has a `description` naming the test file
  and method.
- `oracle/<area>.md`: one row per sample entry: test (`path:line`), behavior, scenario id,
  verdict, the entity at fault or the missing feature, and evidence; an entry with sub-scenarios
  lists them under its row. Then the model bugs as fix requests, one per owning area.
- `oracle/<area>.json`: one row per sample entry, in the sample's order:
  `[{"test", "scenario", "verdict", "area_at_fault", "summary"}]`, where `test` is the entry
  (`<file>:<line>::<name>`). An entry with sub-scenarios nests them in the same row, as
  `"sub": [{"name", "scenario", "verdict", "summary"}]`, and its `verdict` is the combined one.

**Count check.** Before you report, count the entries in your area of the sample and the rows in
`oracle/<area>.json`. They must be equal, with every entry's `test` appearing exactly once. If
they differ, add the missing rows or merge the split ones before you finish.

Write only these files. Don't commit.

## Report (≤120 words)

The count check (entries in the sample = rows written); verdict counts; the model bugs with their owning areas; the simulator gaps with the test that
exposed each; tests you found untranslatable and why.

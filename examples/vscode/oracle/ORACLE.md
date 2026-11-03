# Oracle brief: turn the repo's own tests into scenarios

The merged ontology `examples/vscode/vscode.json` was built from the code of microsoft/vscode at
1.144.0 by area agents, and all its own scenarios pass. That proves internal consistency
only. The repo's tests were written by people who know what the code must do. Your job is to
translate a sample of them into mosaic scenarios and find out whether the model agrees.

## Sources

- **The tests:** your assigned list, under `/home/lbethay/.cache/mosaic-bench/vscode-1.144.0`. The oracle reads tests and
  never runs them: **never build or run anything in the snapshot**.
- **The code** (ground truth when a test and the model disagree): `/home/lbethay/.cache/mosaic-bench/vscode-1.144.0`, read-only.
- **The model:** `examples/vscode/vscode.json`, with `fixtures.yaml` and `worlds.yaml` for the shared worlds. Start every scenario from a `full-*` world in `worlds.yaml` (e.g. `full-window`), which includes every area's seed. You may
  read the fragments to find entities.
- **Never read** `notes/**`, `BENCHMARK.md`, `judge/**`.
- How mosaic works: `.claude/skills/mosaic-simulation/SKILL.md` and its references.

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
   | each act call (request, RPC, user action, scheduler tick) | one entry in `steps`, with `flow` or `interface`, `input`, `on`, `at_ms` (steps never overlap; concurrent acts go in one step's flow as `parallel`) |
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
   go run ./internal/devtools/check -f examples/vscode/vscode.json -f examples/vscode/oracle/<area>.yaml \
     --no-mocks --lint hollow -v
   go run ./internal/devtools/check -f examples/vscode/vscode.json -f examples/vscode/oracle/<area>.yaml \
     --scenario '^oracle-<area>-<test>$' --trace
   ```

5. **Give a verdict.** Never change the expectations to match the model.

   | Verdict | Meaning |
   |---|---|
   | `pass` | The scenario reproduces the test's asserted outcome, and the trace takes the code's path |
   | `model-bug` | The model disagrees with the test, and the code agrees with the test. Name the entity and cite the code |
   | `test-mismatch` | The test asserts something the code at 2c33b50b16 doesn't do (a stale or disabled test). Cite the code |
   | `sim-gap` | The model is as right as mosaic allows, but the simulator can't express it. Name the missing feature |
   | `untranslatable` | The test checks something below the model's level (byte layout, a parser's internals). Say what |

## Output

- `oracle/<area>.yaml`: a fragment with `schema_version: 1`, `id: vscode`, and only
  `scenarios` (ids `oracle-<area>-<test-slug>`). Each has a `description` naming the test file
  and method.
- `oracle/<area>.md`: one row per test: test (`path:line`), behavior, scenario id, verdict, the
  entity at fault or the missing feature, and evidence. Then the model bugs as fix requests, one
  per owning area.
- `oracle/<area>.json`: `[{"test", "scenario", "verdict", "area_at_fault", "summary"}]`.

Write only these files. Don't commit.

## Report (≤120 words)

Verdict counts; the model bugs with their owning areas; the simulator gaps with the test that
exposed each; tests you found untranslatable and why.

## VS Code specifics

- **Your tests:** `oracle/sample.json` lists them by area: file, line of the first test case, and
  name. Translate that test case, plus up to two more cases from the same file if they test the
  same unit.
- **Test style.** VS Code tests are mocha `suite`/`test` with `assert`. They build services with
  `TestInstantiationService`, `workbenchInstantiationService` or `createTextModel`, and stub
  collaborators with `TestXService` classes or `stub(...)`. Translate a stubbed collaborator into
  seeded state for the model's real collaborator. Never mock.
- **Driving the code under test.** Tests often call a class's method directly. Use a scenario step
  with `interface: <component.method>` and `caller: user`, or the flow that reaches it.
- **Mechanics below the model.** Pure string, array or path utilities in `src/vs/base` (strings,
  arrays, glob, uri parsing) are below the model unless the model has an interface for them.
  That's `untranslatable` with the reason.

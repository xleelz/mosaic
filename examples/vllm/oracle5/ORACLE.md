# Oracle brief: turn the repo's own tests into scenarios

The merged ontology `examples/vllm/vllm.json` was built from the code of vllm-project/vllm at
v0.32.0 by area agents, and all its own scenarios pass. That proves internal consistency
only. The repo's tests were written by people who know what the code must do. Your job is to
translate a sample of them into mosaic scenarios and find out whether the model agrees.

## Sources

- **The tests:** your assigned list, under `/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`. The oracle reads tests and
  never runs them: **never build or run anything in the snapshot**.
- **The code** (ground truth when a test and the model disagree): `/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`, read-only.
- **The model:** `examples/vllm/vllm.json`, and `fixtures.yaml` for the shared worlds. You may
  read the fragments to find entities.
- **Never read** `notes/**`, `BENCHMARK*.md`, `judge/**`, `judge2/**`, `judge3/**`, `judge4/**`, `judge5/**`, `oracle/**`, `oracle2/**`, `oracle3/**`, `oracle4/**`, `build-oracle/**`,
  `reconcile/**`, `FIXES*.md` or `RESULTS.md`. This is a blind re-measurement.
- Only edit files under `examples/vllm/oracle5/`. Never edit the model.
- **One verdict per sample entry.** If an entry is a whole file or class, translate its methods as sub-scenarios, but the entry gets one row: pass only if all pass, otherwise the worst verdict, with sub-results nested. Cover every entry; end with the count check: entries in the sample = rows written.
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
   go run ./internal/devtools/check -f examples/vllm/vllm.json -f examples/vllm/oracle5/<area>.yaml \
     --no-mocks --lint hollow -v
   go run ./internal/devtools/check -f examples/vllm/vllm.json -f examples/vllm/oracle5/<area>.yaml \
     --scenario '^oracle-<area>-<test>$' --trace
   ```

5. **Give a verdict.** Never change the expectations to match the model.

   | Verdict | Meaning |
   |---|---|
   | `pass` | The scenario reproduces the test's asserted outcome, and the trace takes the code's path |
   | `model-bug` | The model disagrees with the test, and the code agrees with the test. Name the entity and cite the code |
   | `test-mismatch` | The test asserts something the code at 5df63a7203cdb9328d824a27b682e77c7b9928be doesn't do (a stale or disabled test). Cite the code |
   | `sim-gap` | The model is as right as mosaic allows, but the simulator can't express it. Name the missing feature |
   | `untranslatable` | The test checks something below the model's level (byte layout, a parser's internals). Say what |

## Output

- `oracle5/<area>.yaml`: a fragment with `schema_version: 1`, `id: vllm`, and only
  `scenarios` (ids `oracle-<area>-<test-slug>`). Each has a `description` naming the test file
  and method.
- `oracle5/<area>.md`: one row per test: test (`path:line`), behavior, scenario id, verdict, the
  entity at fault or the missing feature, and evidence. Then the model bugs as fix requests, one
  per owning area.
- `oracle5/<area>.json`: `[{"test", "scenario", "verdict", "area_at_fault", "summary"}]`.

Write only these files. Don't commit.

## Report (≤120 words)

Verdict counts; the model bugs with their owning areas; the simulator gaps with the test that
exposed each; tests you found untranslatable and why.

## vLLM specifics

- **Your tests:** `oracle5/sample.json`, which is disjoint from the in-build samples. Start every
  scenario from a `full-*` world in `worlds.yaml`.
- **Test style.** vLLM tests are pytest, usually with real models and GPUs. Translate what the
  test asserts about control flow, scheduling, state and timing, and treat numeric tensor
  equality (`torch.testing.assert_close`, logits values) as untranslatable. Translate a
  monkeypatched collaborator into seeded state or a fault on the real collaborator, never a mock.
- **Mechanics below the model.** Kernel numerics, model accuracy and tokenizer internals are
  below the model's level.

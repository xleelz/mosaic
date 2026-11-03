# Model-quality baseline: vLLM 0.32 (examples/vllm)

Test reach and feature coverage (DESIGN §13.1 item 19), measured on 2026-10-31 against the merged
model after judging: `skeleton.yaml`, `fixtures.yaml`, `worlds.yaml` and all 9 fragments (894 of
894 scenarios pass). The other gates are in `quality-gate.txt`.

```sh
python3 .claude/skills/mosaic-generate/scripts/test_targets.py examples/vllm
F=""; for f in examples/vllm/fragments/*.yaml; do F="$F -f $f"; done
go run ./internal/devtools/check -q -f examples/vllm/skeleton.yaml -f examples/vllm/fixtures.yaml \
  -f examples/vllm/worlds.yaml $F --tests examples/vllm/test-targets.json --min-test-reach 0.5 \
  --features examples/vllm/profile.yaml
```

## Test targets

1,720 test files (`tests/**/test_*.py` minus the profile's excludes). 1,647 (96%) resolve at
least one target, 5.3 targets each on average: `from vllm.x import Y` resolved to the file
defining `Y` (through `vllm/__init__.py`'s lazy `MODULE_ATTRS` and package re-exports), small test
helpers followed one level, and the file named like the test. Five targets imported by more than
10% of the tests (`vllm/platforms/__init__.py`, `vllm/config/vllm.py`...) are dropped from tests
that have others. Unresolved: 43 serving-api tests (mostly pure HTTP tests against a running
server, importing only the client SDK and `tests.utils`), 9 distributed, 11 with no area.

## Test reach: 1,037 of 1,647 (63%)

`--min-test-reach 0.5` fails one area.

| Area | Reached / resolved | Reach |
|---|---|---|
| attention | 52/62 | 84% |
| config-platform | 53/69 | 77% |
| distributed | 118/158 | 75% |
| engine-core | 48/59 | 81% |
| kernels-ops | 267/347 | 77% |
| models-layers | 174/404 | **43%** |
| scheduler-kv | 45/64 | 70% |
| serving-api | 178/346 | 51% |
| worker-runner | 102/126 | 81% |
| (no area: tests outside `oracle.area_globs`) | 0/12 | 0% (not gated) |

models-layers is the one below: 404 tests over many model architectures, quantization methods,
LoRA and multimodal processors, of which the model covers a few representative ones.

## Features: 0 of 28 covered

The profile's 28 `features` were added after the build, so no flow carries a `feature:<id>` tag
and no area has a `skips/<area>.features.json`: all 28 are missing (scheduler-kv 8, serving-api 6,
engine-core 4, models-layers 3, worker-runner 3, distributed 2, kernels-ops 2).
`--strict-features` would fail every area. Several are modeled under other names (continuous
batching, prefix caching, chunked prefill, tensor parallel, streaming); tagging their flows is
the first step of the next round.

## Against the oracle

Of the 36 stage-6 oracle tests, 22 are reached and 14 aren't.
- Translatable tests pass at 14% when reached (2 of 14) and 0% when not (0 of 5). Most reached
  tests are still model bugs (12 of 14): reach is file-level, so a test counts once a target file
  is cited, even when the feature it checks (NIXL remote prefill, hybrid KV managers, structured
  output tags) isn't modeled. The feature list is what catches those.
- Untranslatable tests are half unreached (9 of 17): kernel numerics and model internals sit
  below the model's level. models-layers, the lowest area (43%), had 6 of 6 oracle tests
  untranslatable.
- By area the correlation is weak: scheduler-kv (70%) and serving-api (51%) had 8 of the 17
  model bugs; engine-core (81%) and worker-runner (81%) had 4.

Test reach is a necessary signal, not a sufficient one; low reach here mostly marks code the
model deliberately doesn't simulate. Its use is the `-v` list of unreached tests per area.

# Oracle 5: worker-runner

Sample entries: 4. Rows: 4. Verdicts: 0 pass, 4 model-bug.

| Test | Behavior | Scenario | Verdict | Entity at fault / missing | Evidence |
|---|---|---|---|---|---|
| `tests/v1/worker/test_sleep_mode_backend.py:17` test_cumem_is_the_default_registered_backend | The sleep-mode registry resolves `cumem` to `CuMemBackend`, a `SleepModeBackend` | `oracle-worker-runner-cumem-default-backend` | model-bug (missing) | No `SleepModeBackendFactory` entity and no `sleep-mode-backend` config; `gpu-worker-impl.sleep` calls `cu-mem-allocator.sleep` directly | Code: `sleep_mode_backend.py:160-214`, `gpu_worker.py:246-255`, `config/model.py:375`. `get_backend_class` has no interface to call, so the scenario probes the nearest effect: the effective `sleep-mode-backend` config (fails, unknown config). The `cu-mem-allocator.sleep` assertion passes |
| `tests/samplers/test_ignore_eos.py:20` test_ignore_eos | `LLM.generate` with `ignore_eos` and `max_tokens=512` returns exactly 512 tokens | `oracle-worker-runner-ignore-eos`; control `oracle-worker-runner-ignore-eos-control-200` | model-bug | `llm.run-engine`: its step loop is `foreach lists.range(256)`, `max: 256` | Code: `entrypoints/common/offline.py:610`, an unbounded `while has_unfinished_requests()`. The model stops after 256 steps and returns `[]` with `result.ok`, silently dropping the unfinished request. Cause check: the same request at 200 tokens passes with 200 tokens, so the `ignore_eos` logic itself is right |
| `tests/samplers/test_non_finite_params.py:25` test_non_finite_temperature_rejected | `SamplingParams(temperature=NaN, inf or -inf)` raises `VLLMValidationError` naming temperature | `oracle-worker-runner-non-finite-temperature` | model-bug | `sampling-params.post-init` has no finite check | Code: `sampling_params.py:653-658`. NaN passes the model's range check (`< 0.0 \|\| > 2.0`), so the step succeeds. `inf` and `-inf` are refused only by the range check, which satisfies this test's match on "temperature" but not the code's "must be a finite number" message. Values are built with CEL `double('NaN')`, since the YAML loader refuses `.nan` |
| `tests/v1/cudagraph/test_cudagraph_dispatch.py:104` TestCudagraphDispatcher.test_dispatcher | Dispatcher construction check, key counts per mode and LoRA case, and dispatch results | `oracle-worker-runner-dispatcher-keys`, `-lora-keys`, `-piecewise-needs-compile` | model-bug | `cudagraph-dispatcher-v1`: no `dispatch`, no LoRA cases, no construction assertion, and no caller | Sub-results below |

## test_dispatcher sub-results

| Part | Scenario | Result | Evidence |
|---|---|---|---|
| Key counts for FULL, FULL_DECODE_ONLY, PIECEWISE without LoRA | `oracle-worker-runner-dispatcher-keys` | pass | 2 keys of the expected kind per mode |
| PIECEWISE with LoRA specialization: 10 keys | `oracle-worker-runner-dispatcher-lora-keys` | model-bug | The model returns 2. It lacks `_get_lora_cases` and `get_captured_lora_counts` (`lora/utils.py:51-65`), and the product with capture sizes |
| FULL_AND_PIECEWISE with compile mode NONE raises AssertionError | `oracle-worker-runner-dispatcher-piecewise-needs-compile` | model-bug | The assertion is in `CudagraphDispatcher.__init__`. The model has no construction interface, so the scenario drives `initialize-cudagraph-keys`, which succeeds. The code agrees with the test: `VLLM_USE_BREAKABLE_CUDAGRAPH` defaults to off (`envs.py:184`) and `is_attention_compiled_piecewise` is false for this config |
| The dispatch assertions: non-uniform, uniform and no-match batches | none | model-bug (missing) | No `cudagraph-dispatcher-v1.dispatch`. Code: `cudagraph_dispatcher.py:233`, called from `gpu_model_runner.py:2715` and `:3763`. `cuda-graph-manager.dispatch` is a different class (`worker/gpu/cudagraph_utils.py`), so it was not used as a substitute |

## Fix requests

**worker-runner**
1. Add `SleepModeBackendFactory` (`register_backend`, `get_backend_class`, `create_backend`), a `sleep-mode-backend` config defaulting to `cumem`, and `CuMemBackend`. Route `gpu-worker-impl.sleep` and wake through it (`sleep_mode_backend.py:160-214`, `gpu_worker.py:246-255`, `:311`).
2. Complete `cudagraph-dispatcher-v1`: the construction assertion, LoRA cases in key initialization, and `dispatch`. Connect them to the V1 runner (`cudagraph_dispatcher.py`, `gpu_model_runner.py:873`, `:2715`, `:3763`).

**serving-api**
1. `llm.run-engine`: remove the 256-step bound or make it follow `max_tokens`, so that a request cannot be silently dropped (`offline.py:610`). A run that hits the limit should abort, not return `[]`.
2. `sampling-params.post-init`: add the finite checks for `temperature` and `repetition_penalty`, in the code's order and with its messages (`sampling_params.py:643-658`). Only the temperature check was exercised here; the repetition penalty one comes from reading the code.

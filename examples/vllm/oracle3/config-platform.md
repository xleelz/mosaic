# Oracle round 3: config-platform

| Test | Behavior | Scenario | Verdict | At fault / missing | Evidence |
|---|---|---|---|---|---|
| tests/config/test_mp_reducer.py:9 `test_mp_reducer` | Building AsyncLLM registers a multiprocessing reducer for VllmConfig (cloudpickle by value) when transformers_modules isn't importable (`vllm/v1/engine/async_llm.py:132` -> `vllm/transformers_utils/config.py:1105-1160`) | `oracle-config-platform-mp-reducer` | model-bug (missing) | engine-core: `async-llm.init` (the function lives in serving-api's `transformers_utils`) | `engine-startup` succeeds, but no call registers a reducer. `async-llm.init` goes straight to stat-logger plugins and `async-mp-client.init` |
| tests/config/test_speculative_draft_hf_overrides.py:35 `test_dict_overrides_are_not_forwarded_to_draft` | A dict `hf_overrides` on the target is not forwarded to the draft: `compose_draft_hf_overrides` returns `hf_config_override` itself, and only a callable is composed (`vllm/config/speculative.py:1084-1107`) | `oracle-config-platform-dict-overrides-not-forwarded-to-draft` (commented out in the yaml: check refuses unknown interfaces) | model-bug (missing) | config-platform: `speculative-config` has no compose-draft-hf-overrides, and there is no hf-overrides config | Only `hf-config-override`, `maybe-override-draft-max-position-embeddings` and `verify-and-get-draft-tp` exist |
| tests/config/test_observability.py:9 `test_custom_histogram_buckets_default_none` | `ObservabilityConfig()` leaves custom_histogram_buckets None (`vllm/config/observability.py`) | `oracle-config-platform-custom-histogram-buckets-default-none` | pass | none | `observability-config.init` with `{}` returns null. Minor: sending the field `{$absent: true}` aborts, because behavior[0] reads `input.custom_histogram_buckets` without `has()` |

Verdicts: 1 pass, 2 model-bug.

## Fix requests

**config-platform**
1. Add `speculative-config.compose-draft-hf-overrides`. For a non-callable (dict or None) target `hf_overrides` it returns the arch-mapping override only. A callable is composed with it (`speculative.py:1084-1107`). Add an `hf-overrides` config so the draft ModelConfig path can show that a dict like `{max_position_embeddings: 1234}` doesn't reach the draft.
2. (minor) `observability-config.init`: read `has(input.custom_histogram_buckets)` and the other optional fields, so an omitted field means None.

**engine-core**
3. `async-llm.init` (and `engine-core-proc` startup, `core.py:1398`) should call a `maybe-register-config-serialize-by-value` step that registers the VllmConfig reducer with `multiprocessing.reducer.register` (`transformers_utils/config.py:1105-1160`; the function itself is serving-api's).

# Oracle 5: scheduler-kv

Run: all sub-scenarios in `scheduler-kv.yaml`, `check --no-mocks --lint hollow`: validation 0 errors, hollow lint 0 failing.

| Test | Behavior | Scenario id | Verdict | Entity at fault or missing feature | Evidence |
|---|---|---|---|---|---|
| `tests/v1/core/test_kv_sharing.py:17` | Layers sharing another layer's cache are appended to the target's KV cache group, in mapping order (`vllm/v1/worker/utils.py:775-805`). | `oracle-scheduler-kv-kv-sharing-same-attn-groups` | model-bug | Missing: `add_kv_sharing_layers_to_kv_cache_groups` | No interface or behavior in `vllm.json` handles `shared_kv_cache_layers`. `attn-utils.init-kv-cache` says shared layers alias their target, but only sets `vars.bound_pool`; it returns no groups. Callers: `gpu/attn_utils.py:208` (init_attn_backend), `gpu_model_runner.py:7028-7038`. |
| `tests/v1/structured_output/test_structured_output_manager.py:390` | Validate drafts, bitmask with rollback, accept, post-accept state: the grammar applies only from the reasoning end, invalid drafts are cut, and a stop token terminates (`structured_output/__init__.py:231-308`, `:310`, `:330`, `:462`; `scheduler.py:2012`, `:2186`, `:2567`). | `oracle-scheduler-kv-real-flow-* (14 FlowCase ids on xgrammar, plus -guidance)` | model-bug | `scheduler.update-draft-token-ids`, `scheduler.get-grammar-bitmask`, `structured-output-manager.accept-tokens`; missing `validate_tokens`, `_get_constraint_bounds`, reasoning gating; guidance backend | All 15 fail. Drafts are stored unvalidated (e.g. active-first-token-invalid keeps the rejected token; code cuts to `[]`). accept-tokens feeds reasoning tokens to the grammar, so every becomes-active case and `inactive` are rejected where the code returns True. No per-row bitmask and no reasoning_ended exist. Guidance grammars are "assumed ready" and reject nothing. Stand-in grammar: JSON is mapped onto the model's string FSM; becomes-active-later-token-invalid needs one extra token, so its pattern is UUCCCU. The reasoners are test doubles; their end marker is carried as seeded request state. |
| `tests/v1/core/test_kv_cache_metrics.py:16` | A new BlockMetricsState has birth and last access at now and an empty access history (`vllm/v1/core/kv_cache_metrics.py:19-24`). | `oracle-scheduler-kv-block-metrics-state-init` | model-bug | Missing: `KVCacheMetricsCollector` and `BlockMetricsState`; configs `kv-cache-metrics`, `kv-cache-metrics-sample` | No component, interface or config in `vllm.json` mentions them. `block-pool.get-new-blocks` runs but keeps no metrics; code calls `on_block_allocated` at `block_pool.py:692-693`. The test patches time; the scenario would use the virtual clock. |

Count check: sample entries 3, rows 3.

The kv-sharing test file lives in core, but the function is in `vllm/v1/worker/utils.py`, so the fix request goes to worker-runner.

## Fix requests

### scheduler-kv

- **Structured output draft flow.** Add `StructuredOutputManager.validate_tokens` (call it from `scheduler.update-draft-token-ids`, `scheduler.py:2567`, and the in-output variant, `:2595`), `_get_constraint_bounds` with `reasoning_ended` (`__init__.py:231-308`), reasoning-aware `accept-tokens` (`:462-482`) and a per-row `grammar_bitmask` over spec tokens with rollback (`:330`, `scheduler.py:2012`). Model the guidance backend's validation (`structured-output-manager.grammar-init` currently assumes ready).
- **KV cache residency metrics.** Add the collector (`kv_cache_metrics.py`), its hooks in block-pool (`block_pool.py:692-698`) and the two configs (`config/observability.py:62,67`).

### worker-runner

- **KV sharing.** Add `add_kv_sharing_layers_to_kv_cache_groups` (`worker/utils.py:775`) and use it in `init_attn_backend` (`gpu/attn_utils.py:208`) and `gpu_model_runner.py:7028`, so shared layers join their target's group.

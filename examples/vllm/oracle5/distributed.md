# Oracle 5: distributed

Sample entries: 5. Rows: 5. Verdicts: 1 pass, 3 model-bug, 1 untranslatable.

| Test | Behavior | Scenario | Verdict | Entity at fault / missing | Evidence |
|---|---|---|---|---|---|
| `tests/v1/kv_connector/unit/test_moriio_routing.py:58` test_request_finished_returns_prefill_rank_for_propagation | A MoRIIO prefill scheduler finishing a length-capped request returns its own global DP rank, marked authoritative, keeps `transfer_id`, and frees at once with no blocks | `oracle-distributed-moriio-request-finished-prefill-rank` | model-bug | `kv-connector-base-v1.request-finished` has no MoRIIO branch; `moriio-connector-scheduler.request-finished` does not exist | Code: `moriio_connector.py:1406`, return dict `:1510-1526`. The trace goes to "Base implementation (ExampleConnector and no connector) frees blocks now" and returns `kv_transfer_params: null`. `remote_dp_rank` appears nowhere in the model. `delay_free_blocks == false` passes only because the base branch always returns false |
| `tests/v1/kv_connector/mooncake_integration/test_mooncake_imports.py:6` test_mooncake_engine_imports | The installed Mooncake wheel's compiled extension imports (CUDA 12 vs 13 wheel selection) | none | untranslatable | Python packaging and native ABI, below the model | The test only runs `import mooncake.engine` and prints package versions. No vLLM code is under test |
| `tests/v1/kv_connector/nixl_integration/test_edge_cases.py:20` test_edge_cases | P/D through NIXL handles a prompt shorter than a block, a decode-side prefix hit and a partial decode-side hit | `oracle-distributed-nixl-edge-short-prompt`, `-full-decode-hit`, `-partial-decode-hit` | pass | none | Sub-results below. Control flow only, see the limits |
| `tests/v1/kv_connector/unit/test_offloading_connector.py:258` test_cpu_offloading | OffloadingConnector stores a cold prompt to CPU and publishes `BlockStored` medium CPU; after a prefix-cache reset the prompt reloads from CPU | `oracle-distributed-cpu-offloading-store-reset-reload` | model-bug | `kv-connector-base-v1` hooks do not route `OffloadingConnector`; no `OffloadingConnector` component | Code: registered at `kv_connector/factory.py:214-216`, `offloading_connector.py:154`, `offloading/scheduler.py:1039`, `:2005`. The trace takes "A registered connector this model does not implement" and matches 0 tokens. `cpu-offloading-manager.prepare-store` and `.lookup` are never called in this run; their only callers are `tiering-offloading-manager.*` |
| `tests/v1/kv_connector/unit/test_moriio_proxy_routing.py:156` test_full_slot_space_is_covered_uniformly | `flat_interleaved_dp_route` hits every (instance, dp_rank) slot equally over three cycles | none: no interface to call | model-bug (missing) | No entity for the MoRIIO toy proxy's router | Code: `examples/disaggregated/disaggregated_serving/moriio_toy_proxy_server.py:232-256`. No model entity cites this file. Scope caveat: `profile.yaml` lists `examples/**` as `not_evidence`, so this may be a scope decision rather than an area's error. The brief's rule for a missing entity gives model-bug |

## test_edge_cases sub-results

| Part | Scenario | Result | Asserted |
|---|---|---|---|
| (1) short prompt | `oracle-distributed-nixl-edge-short-prompt` | pass | 4-token prompt: prefill returns `do_remote_prefill`; decode schedules 0 tokens, matches 4 external tokens async, then recomputes 1 token from 3 computed |
| (2) decode-side hit | `oracle-distributed-nixl-edge-full-decode-hit` | pass | 40-token primed prompt: 32 computed locally, 8 external, then 1 token from 39 computed |
| (3) partial hit | `oracle-distributed-nixl-edge-partial-decode-hit` | pass | 132-token prompt with a primed 32-token prefix: 100 external, then 1 token from 131 computed |

Expected values were derived from `nixl/pull_scheduler.py:34-65` and `scheduler.py:3157-3172` before the first run.

Limits of this pass:
- The test's only assertions compare generated text between routes. That equality is below the model, so the scenarios assert the control flow instead.
- The toy proxy is not modeled. Parameters are passed between steps directly in part (1) and written by hand in parts (2) and (3).
- One scheduler plays both roles in part (1), and only the decode role in parts (2) and (3).

## test_cpu_offloading limits

The scenario translates the store, reset and reload path. The test's latency ratio and generated text are below the model. The `BlockStored` medium CPU event and the `reset_prefix_cache` refusal while stores are in flight are not asserted, because the connector they need is absent.

## Fix requests

**distributed**
1. Add `moriio-connector-scheduler.request-finished` and route `kv-connector-base-v1.request-finished` to it for `MoRIIOConnector`. Cover the consumer unmap, the `do_remote_prefill` abort path, the status gate, delayed free, and the returned parameters including `remote_dp_rank`, `remote_dp_rank_override`, `remote_dp_size`, `remote_dp_size_local` and `transfer_id` (`moriio_connector.py:1406-1526`).
2. Add `OffloadingConnector` and route all `kv-connector-base-v1` hooks to it for matching, allocation, metadata, finish, events and reset (`offloading_connector.py`, `offloading/scheduler.py`). Connect it to the existing `cpu-offloading-*` entities, which the **scheduler-kv** area owns.
3. Decide whether the toy proxy is in scope. If so, add `flat_interleaved_dp_route` (`moriio_toy_proxy_server.py:232-256`). If not, record the exclusion in the profile.

# Oracle round 3 (fix round 4): scheduler-kv

| Test | Behavior | Scenario | Verdict | Entity at fault / feature | Evidence |
|---|---|---|---|---|---|
| tests/v1/core/test_async_scheduler.py:36 `test_stop_by_max_tokens` (params 3 and 1) | With async scheduling, outputs applied one step late, each request stops at exactly max_tokens and the scheduler never schedules past it (total = prompt + max_tokens - 1 per request). Code: `Scheduler.schedule` running loop skip, vllm/v1/core/sched/scheduler.py:667-681; `AsyncScheduler._update_after_schedule`, vllm/v1/core/sched/async_scheduler.py:25-57 | `oracle-scheduler-kv-stop-by-max-tokens`, `oracle-scheduler-kv-stop-by-max-tokens-1` | pass | - | Steps schedule 10, 1+10, 1+1, 1 then 0, 0 (total 24) for max_tokens=3 and 10, 10, 0, 0 for 1, matching a hand run of the code; the "in-flight step already reaches max_tokens" branch fires twice; both finish with `length`, 0 running/waiting. |
| tests/v1/kv_offload/tiering/p2p/test_manager.py:152 `TestHashSeed.test_missing_pythonhashseed_uses_default` | With PYTHONHASHSEED unset, `P2PSecondaryTierManager._get_hash_seed()` (the seed advertised in the P2P handshake) is `DEFAULT_NONE_HASH_SEED`. Code: vllm/v1/kv_offload/tiering/p2p/manager.py:689-693 -> `get_none_hash_seed`, vllm/v1/core/kv_cache_utils.py:146-157 | `oracle-scheduler-kv-missing-pythonhashseed-uses-default` | model-bug (missing) | `secondary-tier-factory.create-secondary-tier` / no P2PSecondaryTierManager component | The seed resolution itself is right (`kv-cache-utils.init-none-hash`, `get-none-hash-seed` both give `vllm-none-hash`), but the factory returns `class_name: P2PSecondaryTierManager` with the note "Other tier classes (fs, p2p, obj, kvcr) are resolved but their managers are not modeled" (fragments/scheduler-kv.yaml:5051). No p2p manager interface runs, so nothing reads the seed for the handshake (manager.py:732, 776). |
| tests/v1/core/prefix_cache/test_partial_prefix_cache_hits.py:42 `test_connector_without_divergent_hit_support_uses_common_lookup` | A connector whose `supports_divergent_local_hybrid_hits` is False gets the common `get_computed_blocks` lookup, never `get_computed_blocks_for_connector`. Code: `Scheduler._get_local_prefix_cache_hit`, vllm/v1/core/sched/scheduler.py:558-568 | `oracle-scheduler-kv-non-divergent-connector-common-lookup` | pass | - | With `kv-connector: ExampleConnector` (base default False, base.py:188-194) the schedule step calls `kv-cache-manager.get-computed-blocks` (0 hit), then the connector with the local hit, no for-connector lookup. The test's MagicMock scheduler is replaced by a real schedule step. Note: the model has no divergent branch at all, so the sibling test (capable connector, NixlConnector/MoRIIO/MultiConnector) would fail. |

Counts: 2 pass, 1 model-bug, 0 test-mismatch, 0 sim-gap, 0 untranslatable.

## Fix requests

### scheduler-kv

1. Model `P2PSecondaryTierManager` (vllm/v1/kv_offload/tiering/p2p/manager.py), at least its
   construction from `secondary-tier-factory.create-secondary-tier` (factory.py:91-97) and
   `_get_hash_seed` (manager.py:689-693): resolved lazily on first session via
   `kv-cache-utils.get-none-hash-seed`, cached, and sent as `local_hash_seed` when a session
   opens (manager.py:732, 776). Scenario: `oracle-scheduler-kv-missing-pythonhashseed-uses-default`.
2. (Seen while mapping, not a failing test here.) `scheduler.schedule` always calls
   `kv-cache-manager.get-computed-blocks`; add the `supports_divergent_local_hybrid_hits` branch
   (scheduler.py:562-563) that calls `get_computed_blocks_for_connector` for NixlConnector,
   MoRIIOConnector and a MultiConnector whose children all support it (multi_connector.py:216-218).

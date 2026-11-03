# Oracle: distributed (vLLM fix round 3, blind)

| Test | Behavior | Scenario | Verdict | Entity at fault / missing | Evidence |
|---|---|---|---|---|---|
| tests/distributed/aux_output_connector/test_store.py:502 `test_logical_buffer_captures_one_row_per_decode_step` | Capturing one routed-experts row per decode step stages them in a request tail and hands back exactly one completed block once `block_size` rows are in | none | model-bug (missing) | `RoutedExpertsBuffer.capture` (vllm/distributed/aux_output_connector/routed_experts.py:68-117), and its caller `AuxOutputConnectorWorker` capture loop (worker.py:200-290) | The model has only the block-object store (`block-object-store`, `background-block-object-store`, flows `distributed-aux-store-*`); no component stages rows into tails or completes blocks |
| tests/distributed/test_multi_node_assignment.py:31 `test_multi_node_assignment` | `initialize_ray_cluster` builds a PACK placement group whose first GPU bundle is pinned to the driver node (`node:<ip>` 0.001), so the workers land on the driver's node, and removing the group frees the GPUs | none | model-bug (missing, scoped out) | `initialize_ray_cluster` (vllm/v1/executor/ray_utils.py:510-656); owner engine-core (vllm/v1/executor/**) | `ray-cluster` only serves DP placement (`core-engine-actor-manager.create-dp-placement-groups`); the Ray executor was skipped in the inventory as "not reachable with the deployed uni and mp backends". Multi-node GPU test, skipped unless VLLM_MULTI_NODE |
| tests/v1/kv_connector/unit/offloading_connector/test_worker_metadata.py:20 `test_aggregate_disjoint_jobs` | Worker metadata with disjoint completed_jobs aggregates to their union | oracle-distributed-aggregate-disjoint-jobs | model-bug | `kv-output-aggregator.aggregate` drops `kv_connector_worker_meta`; `OffloadingWorkerMetadata.aggregate` (offloading/common.py:92-104) missing | Code: utils.py:143-152 folds each worker's `kv_connector_worker_meta` with `.aggregate` and returns it at :183. Model response schema and return carry only finished/failed/invalid; run: `no such key: kv_connector_worker_meta` |
| tests/v1/kv_connector/unit/test_moriio_hma_scheduler.py:784 `test_truncate_mamba_request_is_idempotent_across_reschedule` | The prefill-side hybrid (Mamba) truncation pops the last prompt token once, marks `_p_side_truncated`, and a second call after preemption is a no-op | none | model-bug (missing) | `MoRIIOConnectorScheduler.on_new_request` / `_truncate_mamba_request_for_prefill` (moriio_connector.py:788-830) | `moriio-connector-scheduler` has get-num-new-matched-tokens (READ N-1 accounting), update-state-after-alloc, split-block-groups, but no on-new-request hook and no truncation; the N-1 contract's producer half is absent. `kv-connector-base-v1` has no on_new_request hook either |
| tests/v1/kv_connector/unit/offloading_connector/test_config.py:743 `test_resolves_heterogeneous_hybrid_block_sizes` | `build_offloading_config` keeps per-group tokens_per_block (12, 16), sets tokens_per_hash to their common hash block size 4, blocks_per_chunk 1 | none | model-bug (missing) | `build_offloading_config` (offloading/config.py:59-140) and the whole OffloadingConnector | `OffloadingConnector` is only a name in `kv-connector-factory` state; no component, interface or flow models it |
| tests/v1/kv_connector/unit/test_bidirectional_kv_transfer.py:946 `test_turn2_deadline_gate` | On a turn-2 readback, P declines the READ when D's block deadline (minus the handshake clock offset) is within the 5 s safety margin; the request still finishes receiving and is counted as expired, not as a failed transfer | oracle-distributed-turn2-deadline-gate-expired (fails); oracle-distributed-turn2-deadline-gate-far-future (passes, control) | model-bug | `nixl-pull-connector-worker.start-load-kv` has no expiry gate | Code: pull_worker.py:125-134 `_is_turn2_read_expired`, :152-163 declines and records `num_kv_expired_reqs`. The model's source range cites :136-175 but always calls `nixl-agent.read-blocks` (expired run: read-blocks called once). No clock-offset state, no expired-request stat |

## Fix requests (owning area: distributed)

1. **kv-output-aggregator.aggregate**: carry `kv_connector_worker_meta` through. Fold the first
   non-null worker meta with each later one (`utils.py:143-152`) and return it on the output
   (`:183`). Add the OffloadingWorkerMetadata merge (sum counts per job id, aggregate transfer
   stats; `offloading/common.py:92-104`) to the response schema.
2. **nixl-pull-connector-worker.start-load-kv**: add the turn-2 deadline gate. When bidirectional
   transfer is on, the request has local blocks and `remote.blocks_expiry_time` is set, decline if
   `now + 5 s >= expiry - engine_clock_offset[engine]` (`pull_worker.py:125-163`). Skip the READ,
   finish the request through the failed-transfer cleanup without counting a transport failure,
   and count `num_kv_expired_reqs`. Keep `engine_clock_offset` from the handshake (`base_worker.py:1314`).
3. **moriio-connector-scheduler**: add `on_new_request` with `_truncate_mamba_request_for_prefill`
   (`moriio_connector.py:788-830`): a producer with Mamba layers and `do_remote_decode` drops the
   last prompt token, sets `max_tokens = 1` and `_p_side_truncated`, at most once. It needs a
   connector `on_new_request` hook on `kv-connector-base-v1`, called by the scheduler on admission.
4. **OffloadingConnector**: model `build_offloading_config` (per-group tokens_per_block, DCP scaling,
   tokens_per_hash, blocks_per_chunk) and the worker metadata. It is registered in the factory but
   absent.
5. **RoutedExpertsBuffer**: model the capture tail (stage rows per request, emit a block when full,
   reject non-contiguous captures) between the aux-output worker and the block-object store.

## Fix request (owning area: engine-core)

6. **Ray executor**: `initialize_ray_cluster` placement (first GPU bundle pinned to the driver
   node). Scoped out on purpose because the deployed backends are uni and mp; lowest priority.

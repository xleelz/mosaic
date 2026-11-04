# distributed area notes (vLLM v0.32.0, 5df63a7203)

The fragment is `fragments/distributed.yaml`. It is generated from `gen/distributed/p1-*.yaml` through `p9-*.yaml`
(collectives, KV connectors, connectors and events, EC/weight transfer and the seed, disaggregated prefill, simple CPU offload,
round 3, the KV spec and offloading config arithmetic, and the round-4 connectors) by `gen/distributed/build.py`, which does a textual
concatenation so YAML 1.2 semantics are kept. Edit the parts, then run `python3 -I gen/distributed/build.py`.
Size after fix round 4: 18 configs, 10 schemas, 70 components, 234 interfaces, 95 flows, 249 scenarios.

Every path below is relative to the snapshot root.

## 1. Entry points (43 owned)

| Entries | Covered by |
|---|---|
| torch-op `vllm::all_reduce`, `vllm::all_gather`, `vllm::reduce_scatter`, `vllm::patched_fused_scaled_matmul_reduce_scatter` (parallel_state.py:398-423) | `parallel-state.all-reduce`, `.all-gather`, `.reduce-scatter` and `.patched-fused-scaled-matmul-reduce-scatter` (kind kernel; each has a behavior that looks up the group, then calls the communicator). Flows: `distributed-tp-all-reduce`, `-tp-all-gather`, `-tp-reduce-scatter`, `-fused-matmul-reduce-scatter`. |
| torch-op `vllm::all_reduce_symmetric_with_copy` (pynccl.py:84) | `pynccl.all-reduce-symmetric-with-copy` (NCCL symmetric-memory path of the all-reduce). |
| torch-op `_C_custom_ar::custom_all_gather`, `mnnvl_lamport_all_gather`, `custom_reduce_scatter`, `mnnvl_lamport_reduce_scatter`, `mnnvl_multimem_reduce_scatter` (custom_all_gather_reduce_scatter_ops.cpp:7-22) | Interfaces of the same names on `custom-all-gather-reduce-scatter-ops`. Each has the world-size switch and throws `runtime-error`. Flows: `distributed-sp-custom-collectives` and `distributed-sp-custom-reduce-scatter`. |
| cuda-kernel `cross_device_reduce_1stage` / `_2stage` (custom_all_reduce.cuh:8,31) | `custom-allreduce-cuda.cross-device-reduce-1stage` / `-2stage` (kind kernel, CEL latency). `custom-allreduce-cuda.all-reduce` picks between them as REDUCE_CASE does. |
| cuda-kernel `cross_device_all_gather`, `cross_device_reduce_scatter`, `mnnvl_multimem_barrier_kernel`, `mnnvl_multimem_reduce_scatter_kernel`, `mnnvl_lamport_all_gather`, `mnnvl_lamport_reduce_scatter_kernel` (custom_all_gather_reduce_scatter.cuh) | Cited in the `sources` of the launching op interfaces on `custom-all-gather-reduce-scatter-ops`. |
| triton-kernel `kv_cache_gather_kernel` / `kv_cache_scatter_kernel` (hf3fs gather_scatter_helper.py:10,60) | `hf3fs-gather-scatter-helper.gather-kv-caches` / `scatter-kv-caches`, called by the HF3FS save and load workers. |
| python-cli `all_reduce_utils` (all_reduce_utils.py:436) | `all-reduce-utils.main`: the P2P probe subprocess, reached from `custom-allreduce.init` → `can-p2p` → `gpu-p2p-access-check`. |
| python-cli `hf3fs_metadata_server` (hf3fs_metadata_server.py:522) | `hf3fs-metadata-server.main` (flow `distributed-hf3fs-metadata-server`). |
| python-cli `moriio_heartbeat` (moriio_heartbeat.py:95) | `moriio-heartbeat.main` (flow `distributed-moriio-heartbeat`, entry.repeat). |
| busy-loop `ZmqEventPublisher._publisher_thread` | `zmq-event-publisher.publisher-thread` (flow `distributed-kv-events-thread`, repeat 3). |
| busy-loop `NixlBaseConnectorScheduler._nixl_handshake_listener` | `nixl-pull-connector-scheduler.nixl-handshake-listener` (repeat 3). |
| busy-loop `NixlPushConnectorWorker._push_writer_loop` | `nixl-push-connector-worker.push-writer-loop` (repeat 2). |
| busy-loop `MoRIIOConnectorWorker._moriio_handshake_listener`, `MoRIIOWriter._write_worker_loop`, `MoRIIOWrapper.async_wait_reqid._async_wait` | `moriio-connector-worker.moriio-handshake-listener`, `moriio-writer.write-worker-loop`, `moriio-wrapper.async-wait-reqid` (repeat flows). |
| busy-loop `MooncakeConnectorWorker._mooncake_sender_listener`, `_sender_worker`, `receive_kv_from_single_worker` | `mooncake-connector-worker.mooncake-sender-listener` (repeat), `.sender-worker`, `.receive-kv-from-single-worker`. |
| busy-loop `KVTransferThread.run`, `LookupKeyServer.__init__.process_request` (mooncake store) | `mooncake-store-worker.kv-transfer-thread-run` (repeat), `.lookup-key-server-process-request`. |
| busy-loop `AsyncOperationManager._save_worker` / `_load_worker` (hf3fs) | `hf3fs-async-operation-manager.save-worker` / `load-worker` (repeat). |
| busy-loop `BackgroundBlockObjectStore._run` | `background-block-object-store.run` (repeat). |
| busy-loop `ZmqServerTransport.poll`, `ConsumerControlServer.start.loop`, `ECMooncakeWorker._dispatch_pushes` (encoder-cache transfer) | `ec-zmq-server-transport.poll`, `ec-consumer-control-server.loop`, `ec-mooncake-worker.dispatch-pushes` (repeat flows; added in the reconciliation round). |
| busy-loop `ShardedRDTWeightTransferEngine._proc_worker_loop` / `_quant_worker_loop`, `ShardedRDTTrainerWeightTransferEngine._run_gather_loop` (RL weight sync) | `sharded-rdt-weight-transfer-engine.proc-worker-loop` / `quant-worker-loop`, `sharded-rdt-trainer-weight-transfer-engine.run-gather-loop`. The trainer engine runs in the RL trainer process, so it is parented under the `python-user` actor. |
| **Skipped** | None; `skips/distributed.json` is `[]`. |

Check tool result: 43/43 modeled and substantive; 0 of 36 entry-citing interfaces are trivial.

## 2. Components (code references are in each component's `sources`)

- **gpu-worker subtree (per rank):**
  - `parallel-state` and its children: `group-coordinator` → `cuda-communicator` → {`flashinfer-all-reduce`, `symm-mem-communicator`, `pynccl` → `pynccl-communicator`, `torch-distributed` (external), `custom-allreduce` → {`custom-allreduce-cuda` → `custom-all-gather-reduce-scatter-ops`, `all-reduce-utils`}}.
  - `tensor-model-parallel` (communication_op.py).
  - `kv-transfer-state`, `nixl-push-connector-worker` (+`nixl-agent`), `moriio-connector-worker` → {`moriio-wrapper` → `moriio-writer`, `moriio-heartbeat`}.
  - `mooncake-connector-worker` (+`mooncake-transfer-engine`), `mooncake-store-worker`.
  - `hf3fs-async-operation-manager` (+`hf3fs-gather-scatter-helper`).
  - `background-block-object-store` → `block-object-store`, and `single-writer-shm-ring-buffer` → `posix-shared-memory`.
- **Under engine-core:** `kv-connector-factory`, `kv-connector-base-v1`, `example-connector` (+`example-connector-storage`), `nixl-pull-connector-scheduler`, `moriio-connector-scheduler`, `event-publisher-factory`, `zmq-event-publisher` and `hf3fs-metadata-server`.
  - **Deviation from the brief.** The brief says to put every component under gpu-worker. These objects run in the engine-core process instead: the scheduler-role connector, the KV-event publisher, and the NIXL handshake listener (which must share the scheduler's process, base_scheduler.py:369-372). Under gpu-worker, a call from the scheduler would cross into another instance group, give a warning in tp4, and run on rank0.
  - `hf3fs-metadata-server` is a separate process. It sits under engine-core only so that it has a single instance.

- **Naming collision.** The Python `CustomAllreduce` is `custom-allreduce`. The C++ `vllm::CustomAllreduce` is `custom-allreduce-cuda`.

## 3. Boundary stubs and contracts

- **I declared no boundary interfaces.** Every call stays inside my area. `parallel-state.get-tp-group` stands in for the TP group that every caller reads.
- **Seams I own:**
  - `tensor-model-parallel.all-reduce` is the profile seam. Request `DistCollectiveRequest {num_tokens (required), hidden_size, dtype, dim, num_collectives}`, response `DistCollectiveResult {backend, algorithm, bytes, world_size, num_tokens, hidden_size}`, errors `assertion-error`, `dist-backend-error` (status 0).
  - The same shapes apply to `tensor-model-parallel.all-gather` and `.reduce-scatter`.
  - KV connector hooks on `kv-connector-base-v1`: `get-num-new-matched-tokens`, `update-state-after-alloc`, `build-connector-meta` and `request-finished`, called by scheduler-kv. `save-kv-layer` and `start-load-kv` are called by worker-runner and attention. Request shape: `DistKvRequest`.
  - `zmq-event-publisher.publish` (called by scheduler-kv).
- **Config reference:** `disable-hybrid-kv-cache-manager` (owner config-platform).
- **Contract wiring for reconciliation:**
  - kernels-ops owns `custom-ops.all-reduce` (`vllm/_custom_ops.py:3106`, binding `csrc/torch_bindings.cpp:1100`). My `custom-allreduce.custom-all-reduce` calls `custom-allreduce-cuda.all-reduce` directly, which stands in for the `csrc/custom_all_reduce.cu:70` op body. kernels-ops should have its wrapper call `custom-allreduce-cuda.all-reduce`.
  - The same applies to the `_custom_ops.py` wrappers of the custom all-gather and reduce-scatter ops.

## 4. Config

| id | deployed | default | sources / note |
|---|---|---|---|
| tensor-parallel-size (owned) | 1 (tp4-llama-70b: 4) | 1 | config/parallel.py:141, engine/arg_utils.py:530 |
| vllm-allreduce-use-flashinfer | true | true | envs.py:1970; **FlashInfer AR is tried first** on the TP group |
| vllm-allreduce-use-symm-mem | true | true | envs.py:1966 |
| vllm-use-nccl-symm-mem | false | false | envs.py:2099 |
| vllm-custom-allreduce-algo | "" | "" | getenv in custom_all_reduce.cuh:271 |
| vllm-skip-p2p-check | true | true | envs.py:1216 (lambda default "1"); the typed stub at envs.py:129 says False |
| kv-connector, kv-role | "" (unset) | None | config/kv_transfer.py:60,71. No fixture deploys P/D, so scenarios override them. |
| disable-hybrid-kv-cache-manager (ref, config-platform) | null | None | config/scheduler.py:182; resolved in config/vllm.py:2170-2192 |
| nixl-kv-lease-duration / nixl-kv-recompute-threshold / nixl-decoder-kv-blocks-ttl | 30 s / 64 / 480 s | same | `kv_connector_extra_config` defaults, nixl/base_scheduler.py:82,165,178 |
| enable-kv-cache-events, kv-events-publisher, kv-events-buffer-steps | false, null, 10000 | same | config/kv_events.py:14,19,31 |
| dist-nvlink-bus-gbps=300, dist-custom-ar-base-us=6, dist-flashinfer-ar-base-us=5, dist-symm-mem-base-us=8, dist-nccl-base-us=15, dist-nixl-rdma-gbps=25 | | | **ASSUMPTIONS.** The code gives no numbers. The values are labeled H100/NVLink/RDMA guesses with `attributes.assumption: true`. |

- **Referenced, not owned:** everything in fixtures.yaml that I read is `tensor-parallel-size`, which I own.
- **Deployed vs default:** they differ only in the tp4 fixture (tensor-parallel-size 4).
- **disable_custom_all_reduce** is read by worker-runner code (gpu_worker.py:1656 → `set_custom_all_reduce`), so I do not define a config for it. I model the effect through `parallel-state.set-custom-all-reduce` with input `enable`.

## 5. Fixture requests

None were required. Scenarios seed my own components' state and override configs.

Two things would help the coordinator:
- A P/D fixture: kv-connector NixlConnector with kv-role kv_consumer or kv_producer.
- A fixture with the H100 capability made explicit. It is currently an assumption in `cuda-communicator.state.device_capability` ("9.0") with flashinfer installed.

## 6. Assumptions and unsettled points

- **Default world:** a worker after startup. `parallel-state.state.initial` has the groups initialized, and the TP ranks follow config `tensor-parallel-size`. Fresh-process scenarios override `world_initialized`/`mp_initialized` to false.
- **Platform:** CUDA sm90 (H100) with flashinfer installed (`requirements/cuda.txt:13`), NVLink fully connected, and a CustomAllreduce built with max_size 8 MiB for 2 or 4 GPUs (min of CUSTOM_ALL_REDUCE_MAX_SIZES["9.0"] and 8 MiB).
- **All-reduce backend order (cuda_communicator.py:362-446):**
  1. FlashInfer, if `nbytes` ≤ FI_ALLREDUCE_FUSION_MAX_SIZE_MB[90][ws]: 64 MB at 2 GPUs, 2 MB at 4, 0.5 MB at 8.
  2. NCCL symmetric memory (opt-in).
  3. Custom all-reduce, if < 8 MiB.
  4. torch symmetric memory, if bf16 and ≤ SYMM_MEM_ALL_REDUCE_MAX_SIZES.
  5. PyNccl, or torch.distributed when PyNccl is disabled.

  I left out ROCm quick-reduce, AITER, FlashInfer PCIe-IPC and the batch-invariant branches. FlashInfer's tuned max size and its workspace check (`is_buffer_size_sufficient`) are approximated by the static table.
- **Multi-rank semantics:** a call on one rank fans out with `parallel ... join: all` over the TP ranks. Each branch runs the backend kernel on its rank, so the slowest rank sets the time and one failed rank fails the call with `dist-backend-error`. In reality every rank calls the collective itself. A caller that already fans out per rank will therefore see the collective N times.
- **Latency granularity:** time is whole ms, and the kernels compute µs then ceil, so every collective costs at least 1 ms. Callers should batch with `num_collectives` (for example 2 × layers) instead of calling once per layer.
- **ExampleConnector:**
  - The folder hash is modeled as the joined token ids of the block-aligned prefix.
  - Its worker-role methods sit on the engine-core component (one shared folder). In the real code every TP rank writes the same file path (example_connector.py:250-259): ranks overwrite each other, and this is not modeled.
- **NIXL time:** `time.perf_counter()` deadlines are modeled from `now` in ms.
- **hf3fs:** buffer allocation failures and partial-batch IO are not modeled. A `write_ok` flag stands for the batch-write result.
- **Mooncake store:** LOOKUP is simplified to "leading stored hashes × block_size, one block short on a full hit".
- **Mooncake P2P:** the decode side's response stream from the prefill node is a `choice` (finish/error/exception), because the remote engine is a different deployment.

## 7. Docs or common knowledge vs code

- People commonly assume "custom all-reduce, else NCCL". In v0.32 the TP all-reduce tries FlashInfer first by default (`VLLM_ALLREDUCE_USE_FLASHINFER` defaults to 1). Large prefill tensors also go to torch symmetric memory before NCCL.
- `VLLM_SKIP_P2P_CHECK` defaults to true: the lambda default is "1" (envs.py:1216), although the typed default is False (envs.py:129). The subprocess P2P probe therefore normally does not run.
- `NixlConnector` is an alias of `NixlPullConnector` (nixl/connector.py:414).
- `PyNcclCommunicator.reduce_scatter` silently returns when disabled (pynccl.py:366-367). CudaCommunicator then returns an uninitialized output; this is not modeled as an error.

## 8. Simulator gaps

- **No race between rank arrival and the collective.** `parallel` branches execute in list order and state isn't interleaved. A rank that never arrives (a hang) can only be modeled with a `timeout` fault plus the join, and the code passes no timeout (torch's default applies).
- **Integer-ms clock:** see the latency note in section 6. Example: a 1 MB FlashInfer all-reduce of about 8 µs shows as 1 ms.
- **Threads as repeat flows:** background threads are modeled as one iteration per call. Inside multi-step scenarios a repeat flow runs once per step, so the scenarios use several steps.
- **`transformMap(i, v, key, value)` from the skill docs is wrong:** the 4-argument form is (filter, transform). I used `transformMapEntry`.

## 9. Known gaps

- Not modeled:
  - The `shm_broadcast` MessageQueue (the TP broadcast of the scheduler output).
  - The all2all managers and expert-parallel dispatch/combine.
  - EPLB rebalancing.
  - Elastic EP.
  - The DCP/PCP group internals.
  - The NIXL worker READ path (base_worker.py) and the NIXL push scheduler.
  - The other connectors: LMCache, Offloading, MultiConnector, FlexKV, SimpleCPUOffload, HiSparse, DecodeBench and ExampleHiddenStates. The dispatcher returns `connector: not-modeled` for them.
  - EC transfer and weight transfer.
- `build-connector-meta`, `save-kv-layer` and `start-load-kv` dispatch only for ExampleConnector.
- Scale: 45 flows and 166 scenarios are above the rough targets (14/60). Most are one flow per background loop, plus branch scenarios.
- Advisory hollow notes (11) are refusal or no-op scenarios that by design write no state.

## 10. In-build oracle

| test | scenario | verdict | cause |
|---|---|---|---|
| tests/distributed/test_shm_buffer.py:26 `test_buffer_opening` | `oracle-build-distributed-1` | pass | The writer creates the segment, the reader attaches with (size, name) from the handle, `is_writer` is false, and the names are equal. |
| tests/distributed/test_expert_placement.py:50 `test_expert_placement_various_sizes` | none | **untranslatable** | The code under test, `determine_expert_map`, is in `vllm/model_executor/layers/fused_moe/expert_map_manager.py:22`, which models-layers owns. The distributed area may not model it, and nothing in `vllm/distributed/**` places experts round-robin. Recommend reassigning the test to models-layers. |
| tests/v1/kv_connector/unit/test_moriio_connector.py:196 `test_write_mode_does_not_reload_remote_kv_after_preemption` | `oracle-build-distributed-3` | pass | A WRITE-mode consumer returns (32, True) while `do_remote_prefill` is set, and (0, False) after it is cleared. |

## 11. Reconciliation round (RECONCILE.md)

- **Decision 4, collectives use `rendezvous`.** The previous design fanned out from one caller with `parallel ... join: all`, so N calling ranks made N × N kernel calls. It is replaced in `cuda-communicator.all-reduce`, `.all-gather`, `.reduce-scatter` and `custom-allreduce.custom-all-gather` / `.custom-reduce-scatter`.
  - Each rank calls the collective once, on its own rank.
  - The call meets its peers with `rendezvous: "= 'tp-allreduce:' + string(input.layer)"` (default layer 0; `tp-allgather`, `tp-reducescatter`, `tp-custom-allgather` and `tp-custom-reducescatter` for the others) and `count: config['tensor-parallel-size']`.
  - After the rendezvous, every rank runs the chosen backend kernel, whose `latency_ms` is the collective's cost. All ranks therefore finish at the latest arrival plus the kernel time. This is equivalent to putting the latency on the rendezvous step, and it keeps the kernel choice (1-stage or 2-stage) visible.
  - `timeout_ms` is the process-group timeout: config `distributed-timeout-seconds`, a boundary reference owned by worker-runner (parallel.py:360). Its null value means torch's 600 s NCCL default. A timeout fails with `dist-backend-error` ("collective timed out: k of n ranks arrived").
  - A rank that fails before arriving leaves its peers waiting until the timeout. This matches NCCL's hang-then-timeout behavior, not an immediate failure.
  - Scenarios drive the 4 TP ranks as 4 concurrent steps (`on: rankK, at_ms: 0, await: false`). A slow rank is a latency fault on `group-coordinator.all-reduce`, which delays its arrival.
- **Decision 9, µs latencies.** The collective and RDMA kernels now return fractional ms (µs exact), and the old ceil to 1 ms is gone. HF3FS gather/scatter: an assumed 10 µs plus 1.4 µs per 2 MiB block.
- **Decision 3, the parallel-state contract.** `ensure-model-parallel-initialized` keeps the code's argument names, `tensor_model_parallel_size` and `pipeline_model_parallel_size` (parallel_state.py:2366-2372). Worker-runner and engine-core send that shape.
  - I added `parallel-state.checkpoint-prepare-distributed-state` and `checkpoint-restore-distributed-state` (parallel_state.py:2418-2429), which worker-runner calls.
- **Decision 10, seed.** Fixture `distributed-seed` uses plain component keys: parallel-state initialized, cuda-communicator on H100 sm 9.0 with flashinfer, custom-allreduce enabled and fully connected. It equals the components' initial state.
- **Decision 11, skips.** The 6 rejected skips are now modeled; see section 1.
- **Merge warning.** `custom-all-gather-reduce-scatter-ops` is now parented under `gpu-worker`, matching kernels-ops' boundary copy.
- **Hollow advisories.** The 11 no-op scenarios now assert that no state changed.
  - The writes tags were dropped on the EC control/poll/dispatch loops and the RDT quant loop: their state models socket output or thread-local queues, with no read path in the system.
- **Merged run:** none of the distributed scenarios fail, and no failure involves a distributed interface.

## 12. Fix round (FIXES.md)

- **Disaggregated prefill end to end (NIXL pull).** Scenario `distributed-pd-nixl-end-to-end` drives these steps in order:
  1. The prefill node's `request-finished` keeps the blocks for the lease and returns the pull parameters (nixl/pull_scheduler.py:191-292).
  2. On the decoder, `get-num-new-matched-tokens` returns the external tokens, loaded asynchronously.
  3. `update-state-after-alloc` queues the pull.
  4. The new `nixl-pull-connector-scheduler.build-connector-meta` (base_scheduler.py:474-520) emits `reqs_to_recv` with local blocks and RemoteMeta, `reqs_to_send`, `reqs_in_batch` and `reqs_not_processed`, then clears its state.
  5. The new worker `nixl-pull-connector-worker.start-load-kv` (pull_worker.py:47-175) handshakes once per remote engine and starts the READ. Full local hits only notify the prefill node; known-bad engines fail at once.
  6. `get-finished` (base_worker.py:2853-3040) reports finished, failed and invalid blocks, and on the prefill side releases blocks on a read notification or an expired lease.
  7. The new `kv-output-aggregator.aggregate` (kv_connector/utils.py:79-196) reports a request finished only after every worker did.
- **Dispatch.** `kv-connector-base-v1.build-connector-meta` now dispatches to NIXL and MoRIIO, `update-state-after-alloc` includes MoRIIO, and `start-load-kv` dispatches to the NIXL worker.
- **MoRIIO.** New interfaces:
  - `split-block-groups` (moriio_connector.py:1353-1375, clip_ssm_state_blocks utils.py:37-44). It is the oracle test `test_split_block_groups_separates_attention_and_mamba`, scenario `distributed-oracle-moriio-split-block-groups`, which passes.
  - `update-state-after-alloc` (917-1200): sidecar transfer ids; WRITE-mode save on the prefill node; READ-mode pulls with the hybrid split and the group-count check; the WRITE-mode decode notify, gated on the owning rank.
  - `build-connector-meta` (1242-1320).
- **Contract for scheduler-kv.** The hooks take `DistKvRequest`:
  - `block_ids` is **per KV-cache group** (`BlockIds`, as in the code: `local_block_ids == ([b0, b1, b2],)` for one group).
  - `build-connector-meta` returns NIXL's `reqs_to_recv[req].local_block_ids` in that per-group form. The oracle's last expectation in `oracle-distributed-nixl-basic-interface` compares it with the flat `req_to_blocks['1']`. Against the code it should compare with `[req_to_blocks['1']]`.
  - That oracle case still fails because `scheduler.schedule` and `scheduler.add-request` don't call the hooks yet. This waits on scheduler-kv.
- **Features:** `feature:tensor-parallel` (`distributed-tp-all-reduce`) and `feature:disaggregated-prefill` (kv-match, kv-alloc, kv-meta, kv-finished, nixl-start-load, nixl-get-finished, kv-output-aggregate).
- **Test reach:** 118/158 → 132/158. Newly reached targets: kv_connector/utils.py, nixl base_worker.py, and distributed/utils.py (`get_pp_indices`, scenario `distributed-pp-indices-cases`).
- **Simplification:** the NIXL handshake is synchronous here. The code runs it in the background and starts the READ when `_ready_requests` drains, possibly a step later (pull_worker.py:81-83).

## 13. SimpleCPUOffloadConnector (follow-up)

- New component `simple-cpu-offload-connector` (gen/distributed/p6-simple-cpu-offload.yaml), eager mode. Its hooks:
  - get-num-new-matched-tokens (manager.py:338-393)
  - update-state-after-alloc (395-506)
  - request-finished, with the finish-time store flush (1181-1255)
  - build-connector-meta, with store and load events (508-570)
  - update-connector-output (1005-1163)
  - reset (1387-1446)
- New dispatcher seams on `kv-connector-base-v1`: `update-connector-output` (base.py:606-614) and `reset-cache` (base.py:778-790).
- Scenario `distributed-cpu-offload-store-reset-reload` passes: after a GPU-cache reset, a repeated 2010-token prompt gets 2000 external tokens loaded from CPU.
- The oracle `oracle-scheduler-kv-simple-cpu-offload-reload` still fails, and passing it needs changes from scheduler-kv:
  - The lookup is by `request.block_hashes` (manager.py:366-367). Scheduler-kv must add `block_hashes: vars.wreq.block_hashes` to its `get-num-new-matched-tokens` call.
  - Stores land in the CPU cache only when the worker reports them, so scheduler-kv must call `kv-connector-base-v1.update-connector-output` from update_from_output (scheduler.py, connector.update_connector_output).
  - The CPU hit is asynchronous (`return hit_length, True`, manager.py:392). Step s2 therefore parks the request in WAITING_FOR_REMOTE_KVS and doesn't schedule it, so the oracle's s2 expectation contradicts the code.

## 14. Fix round 3

- **racy: 8 → 0.**
  - Seven components are owned by one thread, so they get `capacity: {concurrency: 1}` with the owning thread cited: all-reduce-utils, background-block-object-store, ec-zmq-server-transport, example-connector, kv-transfer-state, moriio-writer, nixl-push-connector-worker.
  - The shm ring buffer's cursor update is a compare-and-set (`where: row.next_id == expected_id`, conflict assertion-error). Only the writer allocates (shm_object_storage.py:223).
  - ExampleConnector's build_connector_meta takes the pending loads and clears them without a yield in between.
  - `kv-transfer-state.ensure-kv-transfer-initialized` is marked `racy_in_code`: an unlocked check-then-set of a module global (kv_transfer_state.py:78-91).
  - The EmbeddingCache alloc is `single_writer` under `self._lock` (embedding_cache.py:94).
- **internal-assertions: 165 → 66.**
  - Expectations now assert on `result` and `steps`. Each scenario that writes state keeps one state assertion, because the hollow lint requires it.
  - Real lookup tables became stores:
    - `parallel-state.get-pp-group` over the group registry (parallel_state.py:1638)
    - NIXL `_reqs_need_recv` (`reqs-need-recv-put`)
    - MoRIIO's request/transfer-id maps (`map-request-id` / `unmap-request-id`, moriio_connector.py:709-742)
    - HF3FS key metadata (`batch-key-exists` / `key-metadata-get`)
- **Concurrency:** `distributed-all-reduce-concurrent-ranks` (`tags: [concurrency]`) has 4 ranks entering the rendezvous at once, with invariants checked under `--explore`. It passes on 20 schedules.
- **New code under the round-3 tests:** `canonical-mapping.opaque-fallback-mapping`, `ec-embedding-cache` (get, alloc), `m2n-common.check-transferable`.
- **Round-3 unit tests:** 4 pass, and 2 are untranslatable (see build-oracle/round3/distributed.md).
- **Breaking changes:** none for other areas. Internally:
  - `posix-shared-memory.update` now requires `expected_id`.
  - parallel-state's initial `groups` holds `pp` and `dp`, as after startup.

## 15. Fix round 4 (FIXES4.md): coverage

### Blind findings (oracle2/distributed.md; judge2 names no distributed entity)

| Finding | Fix | Re-run of the unedited scenario |
|---|---|---|
| 1. `kv-output-aggregator.aggregate` drops `kv_connector_worker_meta` | The aggregate now folds the workers' worker metadata (first non-null is the accumulator, then `offloading-worker-metadata.aggregate`, utils.py:143-152, common.py:92-104), the connector stats (NixlKVConnectorStats.aggregate extends the lists, utils.py:132-142) and a worker's positive `expected_finished_count` (utils.py:113-124), and returns all three. | `oracle-distributed-aggregate-disjoint-jobs` **passes** |
| 2. No turn-2 deadline gate in `nixl-pull-connector-worker.start-load-kv` | Added (pull_worker.py:125-163): with `bidirectional_kv_xfer`, a known `blocks_expiry_time`, and local blocks, the READ is declined when `now + 5 s >= expiry - engine_clock_offset[engine]`; the request goes through the failed-transfer cleanup (reported done and failed, base_worker.py:2881-2889), `num_kv_expired_reqs` is counted, and `num_failed_transfers` is not. The handshake now records a clock offset. New `get-kv-connector-stats` (clone and reset). Own scenario: `distributed-nixl-turn2-deadline-gate` (expired, offset-made-expired, far, missing, full-hit). | `oracle-distributed-turn2-deadline-gate-far-future` passes. `...-expired` **still fails, explained**: the scenario does not turn on bidirectional transfer, and the worker gates on its own flag (`self._bidirectional_kv_xfer_enabled and self._is_turn2_read_expired(meta)`, pull_worker.py:152; the flag defaults to False, base_worker.py:534-538). The test enables it through `BIDIR_KV_EXTRA_CONFIG` (test_bidirectional_kv_transfer.py:92-94). With `nixl-pull-connector-worker: {bidirectional_kv_xfer: true}` added, the same case passes in `distributed-nixl-turn2-deadline-gate`. |
| 3. MoRIIO `on_new_request` / Mamba truncation missing | New `kv-connector-base-v1.on-new-request` seam (base.py:598-604), `moriio-connector-scheduler.on-new-request` (moriio_connector.py:788-802) and `truncate-mamba-request-for-prefill` (804-829): pop the last prompt token, N-1 prompt tokens, `max_tokens = 1`, `_p_side_truncated`, idempotent, one-token prompts untouched. The hook returns the changed request fields. | no oracle scenario; `distributed-kv-on-new-request-*` |
| 4. OffloadingConnector absent | New `offloading-config.build-offloading-config` (offloading/config.py:36-151): group selection (prefix-cacheable, or HiSparse indexer groups), DCP-scaled tokens per block, the hash granularity (one group: its block size; several: GCD, LCM when a Mamba group isn't in align mode, `prefix_match_unit` override), the divisibility assert, `blocks_per_chunk` / `block_size` resolution and errors, and bytes per worker block. Plus `offloading-worker-metadata.aggregate`. `test_resolves_heterogeneous_hybrid_block_sizes` is step `hybok` of `distributed-offloading-build-config-cases` (12, 16 -> hash 4, chunk 1). | no oracle scenario |
| 5. RoutedExpertsBuffer missing | New `routed-experts-buffer` (`init`, `capture`, `discard`; routed_experts.py:29-154): tails per request, the aligned-block fast path, the contiguity and skipped-block asserts, pool exhaustion. `test_logical_buffer_captures_one_row_per_decode_step` is `distributed-aux-routed-experts-decode-steps`. | no oracle scenario |
| 6. Ray `initialize_ray_cluster` | engine-core's (vllm/v1/executor/ray_utils.py); not changed here. | - |

### Coverage (reconcile/round4/coverage-distributed.md)

Test-area ranking (superseded by the owner ranking below): reach **13% (289 of 2162) before, 22% (470 of 2162) after** (`coverage_gaps.py examples/vllm --out-dir /tmp/cov-distributed`, with the other areas' working copies of the moment).

Top 25 rows: 17 modeled, 8 declined.
- **Modeled** (new `kv-cache-interface`, `kv-cache-layout`, `kv-connector-base-v1-worker`):
  - `FullAttentionSpec`, `MLAAttentionSpec`, `SlidingWindowSpec`, `CircularBufferSpec`, `MambaSpec`, and the six `page_size_bytes` (KVCacheSpec, HiSparseHot, HiSparseResident, AttentionSpec, MambaSpec, UniformTypeKVCacheSpecs): `kv-cache-interface.page-size-bytes` and `.merge` (KVCacheSpec / FullAttentionSpec / MLAAttentionSpec merge, rows 38-40 too).
  - `KVCacheConfig`, `KVCacheGroupSpec`, `KVCacheTensor`: `kv-cache-interface.prefix-cacheable-group-ids`, `.select-transfer-block-ids`, and the `kv_cache_config` input of `build-offloading-config`.
  - `KVCacheLayout`: `kv-cache-layout.properties`.
  - `KVConnectorBase_V1.register_kv_caches` and `.role`: `kv-connector-base-v1-worker.register-kv-caches` (NIXL: records layers and computes the compatibility hash) and `.role`. Beyond the top 25: `bind_connector_metadata`, `clear`/`has`/`_get_connector_metadata`, `wait_for_save`, `get_finished`, `get_transfer_results`, `get_block_ids_with_load_errors`, `get_kv_connector_stats`, `KVConnectorWorkerMetadata.aggregate`.
- **Declined (another area's code):**
  - `Request.num_tokens`, `RequestStatus` (vllm/v1/request.py), `KVConnectorOutput`, `ModelRunnerOutput` (vllm/v1/outputs.py): engine-core.
  - `SchedulerOutput` (vllm/v1/core/sched/output.py), `FreeKVCacheBlockQueue.append` (vllm/v1/core/kv_cache_utils.py): scheduler-kv.
  - `get_open_port` (vllm/utils/network_utils.py), `update_environment_variables` (vllm/utils/system_utils.py): kernels-ops.
- **Ownership note.** `vllm/v1/kv_cache_interface.py` and `vllm/v1/kv_cache_layout.py` match no area's `owns`. The connector tests drive them, so this area models what its connectors read. The coordinator may reassign them; the interfaces are pure functions.
- **Test-hit skips:** the 7 listed are engine-core's (`AsyncLLMEngine.*`, `RayExecutorV2...monitor_workers`) and the profile's example-script rule; `skips/distributed.json` stays `[]`.
- Test reach: 136/158 -> 141/158.

### Owner-ranked coverage (reconcile/round4/by-owner/coverage-distributed.md)

The coordinator replaced the test-area ranking with an owner ranking (definitions in `vllm/distributed/**` and the custom all-reduce sources, referenced by any area's tests). Function-level reach on it: **12% (179 of 1482) before, 18% (292 of 1591) after** (`coverage_gaps.py examples/vllm --out-dir /tmp/cov-distributed`; the denominator grew with the other areas' current tests). **All top 25 rows are modeled; none declined.** New part `gen/distributed/p10-owned-coverage.yaml`:
- `BlockStored`, `BlockRemoved`, `KVConnectorKVEvents.aggregate`: schema `DistKvCacheEvent` and `kv-event-aggregator` (init, add-events, get-common-events, increment-workers/clear; kv_events.py:145-205).
- `GroupCoordinator.barrier` / `.gather` / `.graph_capture`, `graph_capture`, `get_world_group`, `cleanup_dist_env_and_memory`: `group-coordinator.barrier` and `.gather` (rendezvous over the group, timeout from `distributed-timeout-seconds`), `group-coordinator.graph-capture` -> new `custom-allreduce.capture` (capture mode, graph-buffer registration on exit), `parallel-state.graph-capture`, `.get-world-group`, `.cleanup-dist-env-and-memory`.
- `StatelessProcessGroup`: `send-obj`, `recv-obj`, `broadcast-obj` over a shared `stateless-tcp-store`.
- `ECConnectorRole`, `ECConnectorBase.is_producer`, `.save_caches`, `ECSharedRegion` (+`cleanup`), `ECCPUScheduler`: `ec-connector-base`, `ec-shared-region` over `dev-shm-files`, `ec-cpu-scheduler` (has-cache-item, update-state-after-alloc, build-connector-meta, on the existing `ec-embedding-cache`).
- `MultiConnector` (+`build_connector_meta`), `HiSparseConnector`, `KVConnectorBase_V1.wait_for_layer_load`: `multi-connector`, `hisparse-connector`, `kv-connector-base-v1-worker.wait-for-layer-load`.
- Weight transfer (`ModuleSource`, `finish_weight_update` x2, `send_weights`, `WeightTransferTrainerFactory` + `trainer_init`): `weight-transfer-trainer-factory`, `nccl-trainer-weight-transfer-engine`, `vllm-weight-sync-client`, `nccl-weight-transfer-engine`.
- Gaps: no modeled child connector looks up asynchronously, so MultiConnector's None answer (multi_connector.py:444-447) is not modeled; the dispatchers of `kv-connector-base-v1` do not route to `multi-connector` or `hisparse-connector` yet (their scenarios call them directly); `ECCPUScheduler` does not pin entries or model the NIXL path; `ModuleSource` is the `params` metadata list of `send-weights`; the sync client records its POSTs instead of calling serving-api's RL routes.

### Other changes

- `nixl-push-connector-worker`: new `get-new-notifs` (push_worker.py:747-808, heartbeats via base_worker.py:3042-3062) and `get-transfer-results` (810-849), with the P/D-side counting state.
- `nixl-metadata.compute-nixl-compatibility-hash` (metadata.py:102-215), called by the NIXL worker's `register-kv-caches`.
- `mooncake-connector-worker.build-transfer-params` (mooncake_connector.py:1744-1935): Mamba null-block filter, partial prefix hit, group-count and P<D errors, run grouping, coalesced or per-block descriptors. Only the same-TP plan (`tp_ratio == 1`, 249-250) is modeled.
- `kv-output-aggregator` gets `capacity: {concurrency: 1}`: the step futures are drained in order on the engine-core thread (multiproc_executor.py:91-103).
- Round-4 unit tests: 3 pass, 3 untranslatable (build-oracle/round4/distributed.md).

### Breaking changes

None. Additions only: `DistKvRequest.max_tokens` (optional), the aggregator's extra response fields, new state fields.

### Cross-area requests

- **scheduler-kv:** call `kv-connector-base-v1.on-new-request` from `add-request` after enqueueing (scheduler.py:2639-2640) and adopt the returned `prompt_token_ids`, `num_prompt_tokens`, `max_tokens` and `kv_transfer_params`. Round-4 test 4 (`_update_waiting_for_remote_kv` re-zeroing) is yours. `build-offloading-config` inlines `resolve_dcp_kv_block_size` and `resolve_kv_cache_block_sizes` (kv_cache_utils.py:728-730, 804-...); an interface of yours would replace the inlined arithmetic.
- **worker-runner:** the KV connector model-runner mixin should call `kv-connector-base-v1-worker.bind-connector-metadata` / `clear-connector-metadata` around the forward, and `wait-for-save`, `get-transfer-results`, `get-block-ids-with-load-errors`, `get-kv-connector-stats` after it; `register-kv-caches` after KV cache allocation.
- **engine-core:** `kv-output-aggregator.aggregate` now returns `kv_connector_worker_meta`, `kv_connector_stats` and `expected_finished_count`; pass the workers' values in.

### Simulator and modeling gaps

- NIXL clocks: `perf_counter` seconds are modeled as `now / 1000`; the handshake's measured clock offset is taken as 0.
- Only OffloadingWorkerMetadata's `aggregate` is modeled; other connectors' worker metadata would need their own.
- NIXL `on_new_request` (heartbeat tracking and `_truncate_request_for_prefill`, base_scheduler.py:199-237) is not modeled; the dispatcher falls back to the base no-op for NIXL.
- The parallelism-agnostic and replicated-layout flags of `build_offloading_config` (config.py:153-...) are not modeled.

### Round 4 merge (coordinator)

- `DistKvRequest.prompt_token_ids` has no item cap.
- New part `p11-round4-merge.yaml`: `kv-cache-interface.max-num-blocks-per-req` (base, DCP-sharded
  attention, HiSparse hot, circular buffer, Mamba align/none, UniformType agreement; 
  kv_cache_interface.py) and `.needs-kv-cache-zeroing` (Mamba or mixed device precisions,
  1563-1594). Worker-runner does not call them yet (it takes `needs_kv_cache_zeroing` as an
  input); the model runner's block-table sizing would call the first.
- Dispatchers route `MultiConnector` (`get-num-new-matched-tokens`, `build-connector-meta`) and
  `HiSparseConnector` (`get-num-new-matched-tokens` = (0, False), `update-state-after-alloc`).
  MultiConnector's other hooks still fall back to the unmodeled-connector branch.

## 16. Fix round 5 (FIXES5.md): precision

### Round-4 wrong claims
- `RESULTS.md` "Wrong claims to fix" names no distributed entity. `judge3/*.md` grades no step whose
  component is distributed's (P3-3's EP finding is `mixtral-for-causal-lm.init`, models-layers).
  `oracle3/distributed.md` has no distributed model-bug: its one model-bug (torchrun MIN all-reduce)
  is engine-core's. Re-run unedited: oracle3/distributed 2 pass, 1 model-bug (engine-core), 1
  untranslatable, as before.

### Error-path sweep (all 110 `fail` steps of the fragment, against the cited code)
Corrected, word for word (Python `str(exc)` semantics: an `assert` without a message is `''`, a
KeyError prints the key's repr, an f-string `{x=}` prints `x=<value>`):
- `parallel-state.ensure-model-parallel-initialized`: TP and PP mismatch texts carry
  `get_tensor_model_parallel_world_size()=N` / `pp_world_size=N` (parallel_state.py:2392-2402).
- `group-coordinator.all-gather` / `.reduce-scatter`: `... for input tensor with shape torch.Size([n, h])` (757-759, 788-790).
- `cuda-communicator.reduce-scatter`, `nixl-pull-connector-scheduler.update-state-after-alloc`,
  `example-connector.build-connector-meta`, `hisparse-connector.update-state-after-alloc`,
  `single-writer-shm-ring-buffer.init`, `kv-cache-interface.page-size-bytes` (both),
  `offloading-worker-metadata.aggregate`, `kv-connector-base-v1-worker.get-connector-metadata` and
  `.wait-for-save`: bare asserts / `raise NotImplementedError`, so the message is empty (invented texts removed).
- KeyError reprs: `kv-cache-layout.properties` (`'NHD'`), `ec-connector-base.save-caches`, the NIXL
  handshake listener (`(0, 3)`, base_scheduler.py:376).
- Truncated messages completed: MoRIIO `Unhandled message format: <repr>` and
  `Invalid consumer_tp_size in release message: <n>` (moriio_engine.py:795, 847-849);
  `BlockObjectStore.get_concatenated` (store.py:212-217); the P2P probe crash (all_reduce_utils.py:411-415);
  MoRIIO's missing-peer ValueError with `!r` and the `(got ...)` tail (moriio_connector.py:1153-1160);
  `EmbeddingCache` duplicate alloc `{key!r}`; `check_transferable`'s `Supported: [...]` list
  (m2n_common.py:47-66, 259-263); offloading `tokens_per_block=N not divisible by ...` (config.py:91-96);
  sharded RDT's order mismatch text (sharded_rdt_trainer.py:1393-1397), and an exhausted WeightSource
  now raises `stop-iteration` from `next(groups)` (1391) instead of the mismatch.
- Verified unchanged: the rest (codes, statuses and texts match; check order matches the code).
- Not checkable against vLLM: collective/barrier/gather/store timeouts (`dist-backend-error`,
  `dist-store-error`) come from torch/NCCL, not vLLM; their texts are the simulator's rendezvous
  timeout. The hf3fs metadata server's bind failure is uvicorn's.

### The new worlds
- **MoE (`moe-mixtral-8x7b-tp2-ep`)**: `initialize-model-parallel` builds the EP group for MoE models
  with `use_all2all` (ParallelConfig.use_all2all, config/parallel.py:763-789) and the all2all manager
  the EP communicator builds per `--all2all-backend` (new config `all2all-backend`,
  cuda_communicator.py:202-276). DP now comes from `config['data-parallel-size']` when the caller
  passes none (the code reads the current config, parallel_state.py:2093-2097). New:
  `parallel-state.get-ep-group`/`get-dp-group`/`get-pcp-group`, `group-coordinator.dispatch`/`combine`,
  `ag-rs-all2all-manager` (dispatch = all_gatherv, combine = reduce_scatterv over the DP group,
  all2all.py:67-173), `cuda-communicator.all-gatherv`/`reduce-scatterv`. **Code finding:** in this world
  (TP 2, EP, DP 1) there is no all-to-all at all: use_all2all is false, no manager is built, the MoE
  layer makes no prepare/finalize and reduces with the TP all-reduce; `dispatch` would assert.
  `distributed-moe-ep-group-tp2-no-all2all` shows it; `distributed-moe-ep-dp2-dispatch-combine` drives
  the real dispatch/combine with DP 2 in the same world.
- VL and FP8 worlds: nothing in distributed depends on multimodality or FP8 weights. (The NIXL
  compatibility hash already hashes `cache_dtype`.)

### Round-5 unit tests: 6 of 6 pass (build-oracle/round5/distributed.md)
New: `nixl-push-connector-scheduler` (request_finished), NIXL pull-worker peer replacement
(`ensure-handshake`, `background-nixl-handshake`, `read-blocks-for-req`, `cleanup-remote-engines`),
`mooncake-store-config` + `mooncake-distributed-store` + `mooncake-store-worker.init-store` +
`mooncake-embedding-store-client.create`, `m2n-trainer-init-info.post-init`.

### Breaking changes
- `nixl-pull-connector-worker.start-load-kv`: the per-request body moved to `read-blocks-for-req`.
  A request with no local blocks now only notifies (the code's `_read_blocks` notify path) even when
  it awaits KV, and is then reported done; before, the model issued a READ. The response gains
  `drained`. `get-finished` now also releases replaced peers. Callers: `kv-connector-base-v1.start-load-kv`
  (mine); no other area calls it.
- `parallel-state.initialize-model-parallel`: `data_parallel_size` defaults to null (= the config);
  the EP group record gains `use_all2all` and `all2all_manager`. Callers: worker-runner's
  `init-device` passes no DP (unchanged result at DP 1).
- Error texts listed above; no other area's scenario asserts on them.
- `nixl-agent.send-notif` request gains `engine_id` and `notif_msg` (optional).

### Cross-area requests
- **worker-runner:** `init-device` calls `ensure-model-parallel-initialized` without `is_moe`, so the
  MoE world's workers build no EP group. Pass the model config's `is_moe` (model.py:1686-1690; your
  stub already declares the field) and `data_parallel_size`.
- **models-layers:** when `all2all-utils.maybe-make-prepare-finalize` picks the naive/AgRs
  prepare/finalize, call `group-coordinator.dispatch` / `.combine` (seams, DistAll2AllResult).
- **engine-core:** the external-launcher MIN all-reduce (oracle3) is still yours.

### Simulator notes
- None needed from the round-5 simulator fixes; `{$absent: true}` is used in the round-5 test 6 and a
  regression scenario.

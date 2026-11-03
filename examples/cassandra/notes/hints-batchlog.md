# hints-batchlog: notes

Fragment: `examples/cassandra/fragments/hints-batchlog.yaml`. Code: cassandra-5.0.9 (`b5f2a54210`).
All paths below are relative to the checkout root, and `src/` stands for `src/java/org/apache/cassandra/`.

Check after the migration round: 50 components, 93 interfaces (30 boundary stubs in all), 8 configs,
5 schemas, 19 flows (17 tagged `writes`) and 75 scenarios (18 multi-step).
- **Merged** (skeleton + `fixtures.yaml` + all fragments, `--lint hollow --no-mocks --behavior-coverage`):
  all 75 pass, there are no lint findings or merge warnings for this fragment, and no mocks.
  Behavior coverage is 362/376 steps (96.3%); the baseline was 93.9%.
- **Standalone** (skeleton + this fragment + a copy of the fixtures cut down to the components that
  exist standalone): 61 of 75 pass. The other 14 need membership's gossip state (a node marked down
  in `gossiper@n1`, the host-id map) or coordination's real `send-to-hinted-replicas`.

## Migration round (instances, parallel, configs, timers)

- **Instances.** Every component runs per node (`cassandra-node: [n1, n2, n3]` from `three-node-rf3`).
  - 12 `to` request fields and call-site arguments are gone, and so are all the
    `coordinator`/`holder`/`replica` fields (183 occurrences). Verbs go out with `on:` (19 call sites).
  - State is per instance: `batchlog-manager@nK.batches` is keyed by batch id,
    `hints-buffer@nK`/`hints-store@nK.hints` by `host_id:pk:timestamp`, and `hints-catalog@nK.stores`
    by host id.
  - The HINT_REQ handler reads its own host id with `get-local-host-uuid` on the receiving node.
  - Every scenario uses `fixtures: [three-node-rf3]`. A node is marked down with
    `gossiper@n1.endpoint_state_map.<n>.alive: false`.
- **`parallel`** (5 places):
  - BATCH_STORE to the batchlog endpoints joins on blockFor, with `timeout_ms` set to the write
    timeout and `on_insufficient` `write-failure`. The caller maps a join timeout to WriteTimeout
    BATCH_LOG.
  - All batched mutations are sent before any `get()`.
  - Replay sends every mutation of a batch at once, and every live replica of a mutation.
  - A hint page is sent at once and all its callbacks are awaited.
  - The judge's "2 hung replicas time out at 2000 ms" now holds (`hb-logged-batch-quorum-timeout`
    asserts 2000 ≤ duration < 3000).
- **Configs** (8):
  - `write-request-timeout-ms` is a boundary reference to coordination's.
  - The others are `hints-flush-period-ms`, `max-hints-delivery-threads`,
    `hinted-handoff-throttle-kib`, `max-hints-file-size-mib`, `auto-hints-cleanup-enabled`,
    `batchlog-replay-throttle-kib` and `use-creation-time-for-hint-ttl`.
  - Behaviors read `config[...]`. The cleanup trigger's flag moved from state to config.
- **Timers and capacity:**
  - Batchlog replay: `repeat.initial_delay_ms: 30000` (RING_DELAY, BatchlogManager.java:114-117),
    then every 10 s. `batchlog-manager.start` emits the first replay `after_ms: 30000`.
  - Dispatch poll: first after 10 s, then every 10 s (HintsService.java:229). `start-dispatch` emits
    it `after_ms: 10000`.
  - Flush: after `hints_flush_period`. Cleanup: after 1 h.
  - Capacity: the HintsDispatcher task has `concurrency: 2` (max_hints_delivery_threads), and
    HintsWriteExecutor has `concurrency: 1`.
- **Judge fixes:**
  - **H1:** dispatch is the 10 s alive-check poll. I added the trigger's `!isScheduled(store)` filter
    (`hints-dispatch-executor.is-scheduled`/`done`, HintsDispatchTrigger.java:58,
    HintsDispatchExecutor.java:92-95, 235-238) and the 10 s initial delay. `hb-dispatch-node-comes-back`
    shows the whole sequence: down → hinted → the poll skips the node → realMarkAlive → the poll closes
    the writer → the next poll delivers.
  - **H2/W1:** hint and batch times are epoch ms from `now`, so `find-oldest-hint-timestamp` and
    coordination's should-hint (which now computes `now - max_hint_window`) compare on one clock.
    `hb-submit-hint-then-window` checks it.
  - **B3:** the replay starts 30 s after start, and `RateLimiter.acquire(bytes)` becomes a `wait`
    (BatchlogManager.java:367). The fix round replaced the up-front wait of bytes / rate with Guava's
    charge-the-next-caller timing (section 9). The hint reader's limiter also waits
    (HintsReader.java:338-339).
  - **lwt-batch citation 3:** "Pick the batchlog endpoints" now cites StorageProxy.java:1203.
  - Narration titles no longer sit on `if` steps.
- **Write-then-read:** every `writes` flow has a multi-step scenario that reads the effect back
  through `count-all-batches`, `get-total-hints-size`, `find-oldest-hint-timestamp` or
  `is-dispatch-paused`, or through a later replay or dispatch.

## 1. Entry points

### Covered (20)

| Inventory entry | Covered by |
|---|---|
| verb-handler `BatchStoreVerbHandler.doVerb` | `batch-store-verb-handler.do-verb` (flows `hb-batch-store-verb`, `hb-logged-batch`) |
| verb-handler `BatchRemoveVerbHandler.doVerb` | `batch-remove-verb-handler.do-verb` (flows `hb-batch-remove-verb`, `hb-logged-batch`) |
| verb-handler `HintVerbHandler.doVerb` | `hint-verb-handler.do-verb` (flows `hb-hint-verb`, `hb-hints-dispatch`) |
| messaging-verb `BATCH_STORE_REQ` (Verb.java:122), `BATCH_STORE_RSP` (:121) | `batch-store-verb-handler.do-verb` sources. The RSP is sent by that handler and consumed by `storage-proxy.sync-write-to-batchlog` |
| messaging-verb `BATCH_REMOVE_REQ` (:124), `BATCH_REMOVE_RSP` (:123) | `batch-remove-verb-handler.do-verb`. The RSP is **never sent** (see section 6) |
| messaging-verb `HINT_REQ` (:118), `HINT_RSP` (:117) | `hint-verb-handler.do-verb`. The RSP is consumed by `hints-dispatcher.dispatch` |
| scheduled-task `BatchlogManager.start: replayFailedBatches` | `batchlog-manager.replay-failed-batches` (flow `hb-batchlog-replay`, repeat 2 x 10 s) |
| scheduled-task `HintsService: writeExecutor.flushBufferPool` | `hints-write-executor.flush-buffer-pool` (flow `hb-hints-flush`) |
| scheduled-task `HintsService: cleanupTrigger` | `hints-cleanup-trigger.run` (flow `hb-hints-cleanup`) |
| scheduled-task `HintsService.startDispatch: trigger` | `hints-dispatch-trigger.run` (flow `hb-hints-dispatch`, repeat 2 x 10 s) |
| stage-task `Stage.MUTATION StorageProxy.submitHint: runnable` | `storage-proxy.submit-hint` and `storage-proxy-hint-runnable.run` (flow `hb-submit-hint`) |
| jmx `BatchlogManagerMBean.countAllBatches` | `batchlog-manager.count-all-batches` (flow `hb-jmx-count-all-batches`) |
| jmx `BatchlogManagerMBean.forceBatchlogReplay` | `batchlog-manager.force-batchlog-replay` (flow `hb-jmx-force-batchlog-replay`) |
| jmx `HintsServiceMBean.pauseDispatch` | `hints-service.pause-dispatch` (flow `hb-jmx-pause-dispatch`) |
| jmx `HintsServiceMBean.resumeDispatch` | `hints-service.resume-dispatch` (flow `hb-jmx-resume-dispatch`) |
| jmx `HintsServiceMBean.deleteAllHints` | `hints-service.delete-all-hints` (flow `hb-jmx-delete-all-hints`) |
| jmx `HintsServiceMBean.deleteAllHintsForEndpoint` | `hints-service.delete-all-hints-for-endpoint` (flow `hb-jmx-delete-hints-for-endpoint`) |

### Skipped entry points (2)

- `BatchlogManagerMBean.getTotalBatchesReplayed` (batchlog/BatchlogManagerMBean.java:32): JMX getter
  that reads a counter and has no behavior. The counter is modeled as `batchlog-manager` state
  `total_batches_replayed`.
- `HintsServiceMBean.getPendingHints` (hints/HintsServiceMBean.java:52): JMX getter that reads the
  catalog (`HintsStore.getPendingHintsInfo`) and has no behavior.

### Not mine, though related

- The hint and batchlog JMX operations in `service/StorageProxyMBean.java` and
  `service/StorageServiceMBean.java` belong to `ops`. So do the `nodetool` commands (`truncatehints`,
  `listpendinghints`, `replaybatchlog`, the throttle and window setters, and so on). The interfaces
  `ops` should call are `hints-service.delete-all-hints`, `hints-service.delete-all-hints-for-endpoint`,
  `hints-service.pause-dispatch`/`resume-dispatch` and `batchlog-manager.force-batchlog-replay`.
  `nodetool replaybatchlog` goes through `StorageService.forceBatchlogReplay` →
  `BatchlogManager.startBatchlogReplay().get()`.
- The isolated coverage run also counts `MUTATION_REQ/RSP`, `READ_REPAIR_REQ/RSP` and
  `PAXOS_PREPARE_REQ/RSP` as covered. That comes from the ±3-line tolerance around my `Verb.java`
  citations, and `MutationVerbHandler.doVerb` comes from my boundary stub's citation. Those entries
  belong to write-path, coordination and paxos, and the owners' definitions replace my stubs at merge.

## 2. Components

All parents are `hints-batchlog` or one of my components.

| Component | Class | Code |
|---|---|---|
| `batchlog-manager` (state `batches`, `total_batches_replayed`, `last_replayed_ms`) | BatchlogManager | batchlog/BatchlogManager.java:87-332 |
| `batchlog-manager-rate-limiter` (state `bytes_per_sec`, `stored`, `next_free_us`) | BatchlogManager.rateLimiter (Guava SmoothBursty) | BatchlogManager.java:102, 243-247, 367 |
| `batchlog-manager-replaying-batch` | BatchlogManager.ReplayingBatch | BatchlogManager.java:337-519 |
| `batchlog-manager-replaying-batch-replay-write-response-handler` | ReplayWriteResponseHandler | BatchlogManager.java:525-549 |
| `batch-store-verb-handler` | BatchStoreVerbHandler | batchlog/BatchStoreVerbHandler.java:24-33 |
| `batch-remove-verb-handler` | BatchRemoveVerbHandler | batchlog/BatchRemoveVerbHandler.java:24-32 |
| `batchlog-response-handler` (state `handlers`: requiredBeforeFinish left per mutation) | BatchlogResponseHandler | service/BatchlogResponseHandler.java:30-91 |
| `batchlog-response-handler-batchlog-cleanup` (state `cleanups`: mutations left per batch) | BatchlogResponseHandler.BatchlogCleanup | BatchlogResponseHandler.java:93-122 |
| `storage-proxy-hint-runnable` | StorageProxy.HintRunnable | service/StorageProxy.java:2708-2734, 2781-2828 |
| `hints-service` (state `dispatch_paused`, `shut_down`, `total_hints`) | HintsService | hints/HintsService.java:71-476 |
| `hints-catalog` (state `stores`) | HintsCatalog | hints/HintsCatalog.java:46-147 |
| `hints-buffer-pool` | HintsBufferPool | hints/HintsBufferPool.java:34-140 |
| `hints-buffer` (state `hints`, stage `buffered`) | HintsBuffer | hints/HintsBuffer.java:55-246 |
| `hints-write-executor` | HintsWriteExecutor | hints/HintsWriteExecutor.java:46-258 |
| `hints-store` (state `hints`, stages `writing` and `file`) | HintsStore | hints/HintsStore.java:52-338 |
| `hints-dispatch-trigger` | HintsDispatchTrigger | hints/HintsDispatchTrigger.java:34-77 |
| `hints-dispatch-executor` | HintsDispatchExecutor | hints/HintsDispatchExecutor.java:51-145 |
| `hints-dispatch-executor-dispatch-hints-task` | DispatchHintsTask | HintsDispatchExecutor.java:202-340 |
| `hints-dispatch-executor-transfer-hints-task` | TransferHintsTask | HintsDispatchExecutor.java:147-200 |
| `hints-dispatcher` | HintsDispatcher | hints/HintsDispatcher.java:51-263 |
| `hint-verb-handler` | HintVerbHandler | hints/HintVerbHandler.java:45-124 |
| `hint` | Hint | hints/Hint.java:60-160 |
| `hints-cleanup-trigger` (state `auto_hints_cleanup_enabled: false`) | HintsCleanupTrigger | hints/HintsCleanupTrigger.java:35-70 |

My interfaces on coordination's `storage-proxy` (owned by function, per the brief's override):
`mutate-atomically`, `wrap-batch-response-handler`, `sync-write-to-batchlog`,
`sync-write-batched-mutations`, `async-remove-from-batchlog` and `submit-hint`.

### State layout and keys

- `batchlog-manager@nK.batches` is keyed by batch id: one row is the batchlog copy on node nK.
- `hints-buffer@nK.hints` and `hints-store@nK.hints` are keyed `host_id:partition_key:timestamp`, on
  the node that holds the hint. A hint moves from `buffered` (HintsBuffer) to `writing` (open
  HintsWriter file, after the flush) to `file` (closed and on the dispatch queue, after
  `closeWriter`). Dispatch reads only `file` rows.
- `hints-catalog@nK.stores` is keyed by host id.
- `hints-dispatch-executor@nK.scheduled` holds the host ids with a running dispatch.

### Flows

`hb-logged-batch` (11 scenarios), `hb-batch-store-verb`, `hb-batch-remove-verb`, `hb-batchlog-replay`
(6), `hb-jmx-force-batchlog-replay`, `hb-jmx-count-all-batches`, `hb-submit-hint` (4), `hb-hints-flush`
(2), `hb-hints-dispatch` (6), `hb-hints-dispatch-task` (2), `hb-hint-verb` (7), `hb-jmx-pause-dispatch`,
`hb-jmx-resume-dispatch`, `hb-jmx-delete-all-hints`, `hb-jmx-delete-hints-for-endpoint` (2),
`hb-hints-cleanup` (3), `hb-hints-transfer` (2), `hb-hints-excise` and `hb-hint-window-lookup` (2).

The interfaces other areas are expected to call:
- coordination calls `storage-proxy.mutate-atomically`, `storage-proxy.submit-hint`,
  `hints-service.find-oldest-hint-timestamp` and `hints-service.get-total-hints-size`
  (from `shouldHint`);
- paxos calls `storage-proxy.submit-hint` (from `PaxosCommit`);
- membership calls `hints-service.start-dispatch`, `batchlog-manager.start`, `hints-service.excise`,
  `hints-service.transfer-hints` and `hints-service.pause-dispatch`;
- ops calls the JMX ones listed in section 1.

## 3. Boundary stubs

Migration update: the stubs now use instance names (`n1`..`n3`) where an endpoint is data. They no
longer carry `to` or `coordinator`, and `mutation-verb-handler.do-verb` requires only `{mutation}`, as
write-path's message does. I added `storage-service.get-local-host-uuid` and `gossiper.real-mark-alive`
(both owned by membership).

No other fragment existed when I wrote mine, so every stub uses the brief's shared shapes. Each one
declares only what my call sites send and read.

| Stub | Owner | Request → response I read |
|---|---|---|
| `storage-proxy` (component) | coordination | |
| `replica-plans` / `replica-plans.for-write` | coordination | `{keyspace, token, consistency}` → `{replicas, pending}`; error `unavailable` 4096 |
| `replica-plans.for-batchlog-write` | coordination | `{is_any}` → `{endpoints, consistency: ONE\|TWO}`; error `unavailable` 4096 |
| `replica-layout` / `replica-layout.for-token-write-live-and-down` | coordination | `{keyspace, token}` → `{replicas}` |
| `storage-proxy.should-hint` | coordination | `{endpoint, try_enable_persistent_window}` → `{should_hint}` |
| `storage-proxy.applies-locally` | coordination | `{mutation}` → `{applies_locally}` |
| `failure-detector` / `failure-detector.is-alive` | membership | `{endpoint}` → `{alive}` |
| `storage-service` / `.get-host-id-for-endpoint` | membership | `{endpoint}` → `{host_id}` |
| `storage-service.get-endpoint-for-host-id` | membership | `{host_id}` → `{endpoint}` |
| `storage-service.get-local-host-uuid` | membership | `{}` → `{host_id}` |
| `token-metadata` / `.get-size-of-all-endpoints` | membership | `{}` → `{count}` |
| `mutation-verb-handler` / `.do-verb` (verb MUTATION_REQ) | write-path | `{to, from, mutation}` |
| `mutation` / `mutation.apply`, `mutation.apply-future` | write-path | `{mutation}` |
| `schema` / `schema.largest-gcgs` | schema-auth | `{}` → `{gcgs}` |
| `hints-disk.hints-file-append`, `.hints-file-fsync`, `.hints-file-delete` | shared | kind `io` |

Reconciliation round (done):
1. **One copy of sendToHintedReplicas (decision 7).** `storage-proxy.sync-write-batched-mutations` now calls
   coordination's `storage-proxy.send-to-hinted-replicas` once per mutation, passing the plan from
   `replica-plans.for-write` and `contacts = plan.live_and_down`. It feeds the returned `acks` into
   `batchlog-response-handler.on-response`, which now takes an `acks` count, and it counts the
   non-TIMEOUT `failure_reasons` as failures for `batchlog-response-handler.get`. `blockFor` comes from
   `plan.block_for`; `requiredBeforeFinish` is still computed here from `plan.rf`
   (StorageProxy.java:1417).
2. **Owners' shapes.** I aligned stubs and call sites to the owners:
   - `should-hint` is called with `replica`;
   - `is-alive` returns `{endpoint, alive}`;
   - `for-write` returns coordination's `CoordinationReplicaPlan` shape;
   - `mutation-verb-handler.do-verb` requires `{to, from, mutation}` and returns `{from, verb}`;
   - `send-to-hinted-replicas` is copied from coordination.
   Membership returns `""` (not an error) for an unknown host id or endpoint, so every check now treats
   an empty `host_id` or `endpoint` as null. Host-id examples and seeded state use membership's ids
   (`6d194555-f6eb-41d0-c000-00000000000N`). Component kinds follow the owners: `storage-service`,
   `mutation`, `schema` and `replica-plans` are `module`, `mutation-verb-handler` is `handler`, and
   `hints-service` and `batchlog-manager` are `module`.
3. **Cluster state (decision 4).** The down-node logged-batch scenarios now set
   `state: {gossiper: {endpoint_state_map: {"10.0.0.2": {alive: false}}}}` on a `gossiper` stub
   component, instead of faulting `failure-detector.is-alive` by call index. Other scenarios still
   inject faults on owner interfaces, and those faults hold in the merged run.
4. **HintVerbHandler's local host id** is now the host id of the message's `to`
   (`storage-service.get-host-id-for-endpoint`), not `get-local-host-uuid`. In the merged model the
   latter answers for the node we follow (10.0.0.1), but the handler runs on the receiving replica.
5. **New interfaces** `batchlog-manager.start-batchlog-replay` (BatchlogManager.java:188-192) and
   `batchlog-manager.set-rate` (:235-248), which `replay-failed-batches` now calls.
6. **Standalone failures.** Eight `hb-logged-batch-*` scenarios now need coordination's
   `send-to-hinted-replicas`/`for-write` and membership's gossiper. They fail standalone, against stubs,
   and pass in the merged run.
7. **Skips file.** `skips/hints-batchlog.json` has 2 entries.

## 4. Deployed config

Since the migration, each setting this area reads is a `config` entity in the fragment (deployed value
and code default, both with sources). `write-request-timeout-ms` is a boundary reference to
coordination's.

| Setting | conf/cassandra.yaml | Config.java default | Effective value and where it matters |
|---|---|---|---|
| `hinted_handoff_enabled` | :68 `true` | :112 `true` | true. Read by coordination's shouldHint. **Ignored by batchlog replay** (section 6) |
| `hinted_handoff_disabled_datacenters` | :72 commented | :113 empty | empty |
| `max_hint_window` | :80 `3h` | :115 `3h` | 3h (shouldHint, coordination) |
| `hint_window_persistent_enabled` | :152 commented | :117 `true` | true |
| `hinted_handoff_throttle` | :88 `1024KiB` | :439 `1024KiB` | 1024 KiB/s divided by (nodes - 1) per dispatch task (HintsDispatchExecutor.java:219-221). Narrated only |
| `max_hints_delivery_threads` | :93 `2` | :443 `2` | 2 |
| `hints_flush_period` | :102 `10000ms` | :445 `10s` | 10 s, the period of `hb-hints-flush` |
| `max_hints_file_size` | :106 `128MiB` | :447 `128MiB` | 128 MiB. File rolling is narrated, not simulated |
| `max_hints_size_per_host` | :111 commented (`0MiB`) | :448 `0B` (disabled) | disabled |
| `auto_hints_cleanup_enabled` | :115 `false` | :451 `false` | false (config `auto-hints-cleanup-enabled`) |
| `transfer_hints_on_decommission` | :120 commented | :452 `true` | true |
| `hints_compression` | :125 commented | :450 null | none |
| `batchlog_replay_throttle` | :157 `1024KiB` | :441 `1024KiB` | 1024 KiB/s divided by the ring size (`ctx.replayThrottleKiBPerEndpoint`) |
| `batchlog_endpoint_strategy` | :183 commented | :442 `random_remote` | random_remote (coordination's forBatchlogWrite) |
| `use_creation_time_for_hint_ttl` | absent | :453 `true` | true (the hint creation time is backdated to the request start) |
| `enforce_native_deadline_for_hints` | absent | :1400 `false` | false, so `requestTime.shouldSendHints()` is always true |
| `write_request_timeout` | :1330 `2000ms` | :151 `2000ms` | 2000 ms. The timeout on BATCH_STORE, MUTATION and HINT_REQ (all `writeTimeout` in Verb.java:115-124). BATCHLOG_REPLAY_TIMEOUT = 2 x 2000 = 4000 ms (BatchlogManager.java:95) |
| `storage_compatibility_mode` | :2320 `CASSANDRA_4` | :1380 (no initializer) | CASSANDRA_4, so `MessagingService.current_version` = 12 (VERSION_40), the `version` column of batchlog rows |

Constants that aren't config: RING_DELAY 30 s (StorageService.java:297-325), REPLAY_INTERVAL 10 s,
the dispatch trigger every 10 s (HintsService.java:229), cleanup hourly (:125), MAX_HINT_BUFFERS 3,
`cassandra.maxHintTTL` Integer.MAX_VALUE (CassandraRelevantProperties.java:96), and the default
gc_grace_seconds of 864000 (TableParams.java:360).

None of the values I read differ between the yaml and Config.java. In every case either the yaml
repeats the default or leaves the setting commented out.

## 5. What the code didn't settle, and my assumptions

- **One clock.** Batch and hint times are epoch ms from `now`, with the fixture epoch
  2026-10-30T00:00:00Z. `last_replayed_ms` starts at 0, which is `TimeUUID.minAtUnixMillis(0)`.
  Scenario seeds use absolute epoch-ms literals.
- **The shared request deadline.** In the code both waits in `mutateAtomically` are timed from the
  request start. Putting `deadline_ms` on them would also refuse every later in-process step,
  including hintOnFailure's shouldHint at expiry. So each wait gets the full write timeout instead.
- **gc_grace_seconds** isn't part of the shared mutation shape, so batch rows and hints carry
  `gc_grace_seconds`/`gcgs`, defaulting to 864000.
- **Host ids.** Hints are keyed by host id, as in the code. In isolation the membership stub returns
  the same host id for every endpoint, so two hints for the same mutation to different targets
  collapse into one buffer row. Scenarios assert `total_hints` instead.
- **Truncation filtering** (`SystemKeyspace.getTruncatedAt`) in `Hint.applyFuture` and in replay's
  `addMutation` is narrated, not modeled. A batch whose tables were all truncated is represented by an
  empty `mutations` list.
- **Undecodable batches.** An IOException while deserializing a batch (skip and remove) is not modeled.
- **Oversized hints.** `HintsBuffer.allocate` throws IllegalArgumentException for a hint larger than
  half a buffer; this is not modeled.
- **Write failure versus write timeout.** When failures alone make blockFor unreachable,
  `batchlog-response-handler.get` and `sync-write-to-batchlog` throw write-failure. Otherwise they
  throw write-timeout. In the code, expiries also arrive as onFailure(TIMEOUT) at about the deadline,
  and `isTimeout` turns all-timeout failures into a WriteTimeoutException, so the result is the same.
- **Hints during dispatch.** I modeled one page per hints file. A failed page delivers nothing and the
  whole file is resent later, so already-applied hints in that page are delivered twice. That is
  harmless because the writes are idempotent.

## 6. Where common knowledge and the code disagree

1. **Batchlog replay hints ignore the hint window and `hinted_handoff_enabled`.**
   `sendSingleReplayMutation` writes hints for dead replicas straight to `HintsService.write`
   (BatchlogManager.java:491-502) without calling `shouldHint`. Scenario: `hb-replay-dead-replica-hinted`.
2. **A replay write that fails is hinted twice.** `ReplayWriteResponseHandler` passes the mutation as
   `hintOnFailure` (BatchlogManager.java:529-533), so AbstractWriteResponseHandler.onFailure submits a
   hint (subject to shouldHint). Then `finish()` → `writeHintsForUndeliveredEndpoints` writes another
   one. The TODO in the code admits this. Scenario: `hb-replay-timeout-hinted-twice`.
3. **BATCH_REMOVE_RSP is defined but never sent.** BatchRemoveVerbHandler only removes
   (BatchRemoveVerbHandler.java:28-31), and the coordinator uses `send`, not `sendWithCallback`
   (StorageProxy.java:1319).
4. **The batchlog isn't removed when the client is acknowledged.** Removal fires only when every
   mutation reaches the *batch* consistency level (BatchlogCleanup), and that can be stricter than the
   client's. For example, view updates force QUORUM even at CL ONE (StorageProxy.java:1189-1200).
   Scenario: `hb-logged-batch-view-quorum-for-remove`.
5. **A batchlog timeout doesn't mean the batch was dropped.** On WriteTimeout(BATCH_LOG), any copy
   that landed is replayed later by its node, so the batch may still be applied
   (`hb-logged-batch-batchlog-timeout` leaves one row).
6. **Orphaned hint files expire after 14.4 minutes, not 10 days.** `HintsStore.hasExpired` adds
   `Schema.largestGcgs()` (seconds) to `File.lastModified()` (milliseconds) (HintsStore.java:201;
   Schema.java:272-279). This only matters with `auto_hints_cleanup_enabled`, which the deployed config
   leaves off. Scenario: `hb-cleanup-orphan-expired`.
7. **The periodic dispatch never converts hints for a host that left the ring.** `HintsDispatchTrigger`
   keeps only `HintsStore::isLive` stores, and isLive requires `getEndpointForHostId != null`
   (HintsStore.java:146-150). So `DispatchHintsTask.convert` runs only in a race, and such hints wait
   for excise, cleanup or a transfer. Scenarios: `hb-dispatch-orphan-skipped` and
   `hb-dispatch-task-converts`.
8. **convert/writeForAllReplicas never hints the local node.** shouldHint refuses `isSelf`, so if this
   node became a replica for the hint's token, that copy is dropped rather than applied locally.
9. **The batchlog endpoints can include dead nodes in small DCs.** In a DC with two or fewer
   endpoints, `validate` returns all of them, dead or local, without filtering
   (ReplicaPlans.java:295-297). That is coordination's code, but it shapes batchlog timeouts.
10. **The replay window advances even after failures.** `lastReplayedUuid` advances to the limit
    after every run (BatchlogManager.java:225). A batch row that arrives with an id older than the
    last limit (for example a BATCH_STORE delivered more than 4 s late, after a replay ran) is never
    replayed.
11. **A replay stalls on a local apply error.** The local apply during replay is inline and not caught
    (BatchlogManager.java:484-486), so an error aborts the whole replay run and the batch stays.
    Scenario: `hb-replay-local-apply-fails`.
12. **Failed hint applies get no response.** When `Hint.applyFuture` fails, HintVerbHandler only logs
    at debug and never responds (HintVerbHandler.java:116). The sender sees a timeout, not a failure.

13. **A logged batch at CL ANY with no live batchlog endpoint is unavailable, not stored locally.**
    `forBatchlogWrite` computes the batchlog CL (`size == 1 ? ONE : TWO`) before the ANY fallback to
    this node, so it ends with CL TWO and one endpoint. `forWrite` then fails
    `assureSufficientLiveReplicasForWrite` (ReplicaPlans.java:250-276, 469-476). Scenario:
    `hb-logged-batch-any-no-batchlog-endpoint`.

## 7. Simulator gaps

Resolved by the migration:
- **Parallel fan-out and k-of-n waits.** Batchlog stores, batched mutations, replay writes and hint
  pages all use `parallel` with a join. Timeouts now cost one write timeout, not one per replica.
- **Replay initial delay.** `entry.repeat.initial_delay_ms` and `emit after_ms` give the 30 s
  RING_DELAY and the 10 s dispatch delay.
- **Rate limiters in time.** The replay and hint-reader limiters are `wait`s of bytes / rate.
- **Per-node state and two-sided conversations.** Each replica's batchlog and hints are its own
  instance state, so BATCH_STORE on n2 and countAllBatches on n2 meet.
- **Chaining entries.** The judge's "node comes back, then the next poll dispatches" is one
  multi-step scenario.
- **Stub outputs as levers.** Down nodes come from gossip state in the fixture. Faults remain only for
  the "not in the ring" and "token not owned" cases.

Still open:
- **A request deadline that bounds only the waits.** `deadline_ms` is inherited by every nested call,
  so a budget shared by two waits refuses the later bookkeeping and the expiry-time hints. The model
  gives each wait its own timeout.
- ~~**Acks after the join.**~~ Fixed in the fix round with `on_late` (section 9).
- **Interleaved races.** HintsDispatchTrigger's dispatch emit and its closeWriter, and the replay's
  concurrent batches, still run in list order: branches don't interleave shared state.
- **Batches within a replay page** are sent sequentially across batches, though each batch's
  mutations and replicas are parallel.
- **No call-input or map-building helpers were needed.** `trace` queries replaced the ctx
  bookkeeping where order mattered (`hb-logged-batch-happy` asserts the batchlog store precedes the
  mutation sends).

## 8. Known gaps

- `asyncWriteBatchedMutations` and `wrapViewBatchResponseHandler` (the materialized-view batchlog
  path, StorageProxy.java:1323-1339 and 1425-1443) are not modeled. They are reached from coordination's
  mutateMV.
- The `checkHintOverload` OverloadedException now comes from coordination's `send-to-hinted-replicas`
  and propagates (`overloaded`, 4097). No scenario of mine drives it.
- HintsStore offsets within a file (`markDispatchOffset` and `seek`), corrupted-file handling
  (FSReadError → markCorrupted) and HintsReader paging are only narrated.
- `HintsService.shutdownBlocking`, `getPendingHintsInfo` (the `system_views.pending_hints` virtual
  table, owned by ops) and the diagnostics events are not modeled.
- Transfer re-invokes the target supplier on retry (`getPreferredHintsStreamTarget`). The model reuses
  one `target_host_id`.
- Transient replication (logged batches throw AssertionError, StorageProxy.java:1184-1185) is not modeled.

## 9. Fix round (after round 2)

Both rows of the fix table are done. Every judge case of mine passes (B1–B5, H1–H3, G4).

1. **Batchlog cleanup reacts to late acks.** In the code each response reaches the mutation's
   `BatchlogResponseHandler.onResponse`, which decrements `requiredBeforeFinish` whether or not
   `get()` still waits, and the last mutation to reach zero runs `asyncRemoveFromBatchlog`
   (BatchlogResponseHandler.java:51-56, 107-116; StorageProxy.java:1205-1207). The model used to
   count only the acks that coordination's `send-to-hinted-replicas` returned at its join.
   - `sync-write-batched-mutations` now calls the new `batchlog-response-handler.collect-responses`
     for each mutation (still all at once). It hints the down contacts in one
     `send-to-hinted-replicas` call and sends to each live contact in its own call. So each response
     is a branch of its join, which waits for `blockFor` acks.
   - The join's `on_late` sends each later ack to `batchlog-response-handler.on-response`. That
     interface and `ack-mutation` now keep their counters in state, keyed by handler and batch, so a
     late ack can finish the batch and send BATCH_REMOVE after the client has its answer.
   - `get()` waits for what is left of write_request_timeout since the request start
     (`currentTimeoutNanos`, AbstractWriteResponseHandler.java:112-127). Each MUTATION callback
     expires write_request_timeout after its own send, so a response that comes after `get()` has
     timed out but before its callback expires still counts.
   - A down contact gets no message and never answers, so it holds the wait open until the timeout,
     as `candidateReplicaCount` does. An expired callback fails only after `get()` has timed out, so
     timeouts stay WriteTimeout (AbstractWriteResponseHandler.java:126-137).
   - Scenarios: `hb-logged-batch-view-late-ack-removes` (a view batch at ONE returns on the local ack,
     and the remote acks at 300 ms remove the batchlog), `hb-logged-batch-timeout-late-ack-removes`
     (the client gets a write timeout at 2000 ms, and n3's ack at 2200 ms still removes the batchlog)
     and `hb-logged-batch-ack-after-expiry-dropped` (an ack after the callback expires is dropped,
     and the batchlog stays).
2. **The replay throttle timing** (lwt-batch wrong claim 3). `setRate` sets the limiter to
   `batchlog_replay_throttle / ring size` (integer KiB) × 1024 bytes/s, and only when the rate changes
   (BatchlogManager.java:240-247). `acquire(replayedBytes)` comes after sending (:367). The new
   component `batchlog-manager-rate-limiter` models Guava's SmoothBursty limiter, with a 1 s burst:
   - an acquire waits until the next free ticket, which is the debt of earlier acquires. Its own
     bytes, less the banked permits, push the ticket back for the next caller;
   - leaving `Double.MAX_VALUE` (the limiter's starting rate, :102) starts with a full bucket.
   - The replay interval was already right: the first replay is after RING_DELAY 30 s, then the
     fixed delay is 10 s (:114-117). `batchlog-manager.start` still emits only the first pass,
     because a self-rescheduling timer would exhaust the run's timer budget. The `hb-batchlog-replay`
     flow's `repeat` shows the later passes. Scenario: `hb-replay-throttle-charges-next-batch`
     (1 KiB/s per endpoint and three 1 KiB batches: only the third batch waits, about 0.87 s).
   - The replay still assumes 512 bytes per serialized mutation.

Still open:
- An OverloadedException from `send-to-hinted-replicas` now surfaces only if it fails a mutation's
  wait. The code throws it before anything is sent. No scenario drives it.
- When more than one contact of a mutation is down, the down contacts are one branch of the join,
  so the possible-success count is lower by (down − 1). The availability check refuses those
  cases first at RF 3.

### Breaking changes

All the callers are in my fragment and are fixed. Nobody else calls these interfaces.
- `batchlog-response-handler.on-response` now requires `handler_id`, `batch_id`, `mutations` and
  `batchlog_endpoints`, and it returns `batchlog_removed`.
- `batchlog-response-handler-batchlog-cleanup.ack-mutation` now requires `batch_id` and
  `batchlog_endpoints`, and it calls `storage-proxy.async-remove-from-batchlog` itself.
- `batchlog-manager-replaying-batch.replay` no longer takes `endpoint_throttle_kib`.
- `batchlog-manager.set-rate` keeps its shape. ops' boundary stub (`ops.yaml:2740-2760`) still matches.


# write-path notes

Fragment: `examples/cassandra/fragments/write-path.yaml`. Code: cassandra-5.0.9 (`b5f2a54210`).
All paths below are relative to `src/java/org/apache/cassandra/` unless they start with `conf/`.

Check result (skeleton + this fragment): 0 validation errors and 0 warnings. 66/66 scenarios
pass with no run warnings. 387/387 citations resolve. 19 of my inventory entries are covered and
14 are skipped (listed below).

## 1. Entry points

### Covered

| Inventory entry | Covered by | Flow |
|---|---|---|
| verb-handler `MutationVerbHandler.doVerb` (db/MutationVerbHandler.java:45) | `mutation-verb-handler.do-verb` | replica-mutation-verb |
| verb-handler `AbstractMutationVerbHandler.doVerb` (db/AbstractMutationVerbHandler.java:42) | `counter-mutation-verb-handler.do-verb` (inherited doVerb) | replica-counter-mutation-verb |
| verb-handler `CounterMutationVerbHandler` (db/CounterMutationVerbHandler.java:30) | `counter-mutation-verb-handler.do-verb`, `.apply-mutation` | replica-counter-mutation-verb |
| verb-handler `TruncateVerbHandler.doVerb` (db/TruncateVerbHandler.java:34), claimed (see §5) | `truncate-verb-handler.do-verb` | replica-truncate-verb |
| messaging-verb `MUTATION_REQ` (net/Verb.java:116) | `mutation-verb-handler.do-verb` | replica-mutation-verb |
| messaging-verb `PAXOS2_COMMIT_REMOTE_REQ` (net/Verb.java:186), handler is MutationVerbHandler | `mutation-verb-handler.do-verb` | replica-mutation-verb |
| messaging-verb `COUNTER_MUTATION_REQ` (net/Verb.java:137) | `counter-mutation-verb-handler.do-verb` | replica-counter-mutation-verb |
| messaging-verb `TRUNCATE_REQ` (net/Verb.java:134), claimed | `truncate-verb-handler.do-verb` | replica-truncate-verb |
| background-task `COMMIT-LOG-ALLOCATOR` (db/commitlog/AbstractCommitLogSegmentManager.java:158) | `abstract-commit-log-segment-manager.allocator-runnable-run` | commitlog-segment-allocator |
| background-task `AbstractCommitLogService.start: sync` (db/commitlog/AbstractCommitLogService.java:155) | `abstract-commit-log-service.sync-runnable-run` | commitlog-periodic-sync |
| background-task `MemtableCleanerThread: clean` (utils/memory/MemtableCleanerThread.java:120), claimed | `memtable-cleaner-thread-clean.run` | memtable-cleaner |
| scheduled-task `AbstractAllocatorMemtable.scheduleFlush: runnable` (db/memtable/AbstractAllocatorMemtable.java:223) | `abstract-allocator-memtable.schedule-flush` | memtable-period-flush |
| stage-task `Stage.MUTATION Keyspace.applyInternal` (db/Keyspace.java:585-587) | `keyspace.apply-internal` (view-lock deferral retry) | replica-mutation-verb (wp-mutation-view-lock-deferred) |
| stage-task `Stage.MUTATION CommitLogReplayer.MutationInitiator.initiateMutation` (db/commitlog/CommitLogReplayer.java:331) | `commit-log-replayer-mutation-initiator.initiate-mutation` | commitlog-replay-startup |
| jmx-operation `CommitLogMBean.recover` (:65) | `commit-log.recover` | commitlog-jmx-recover |
| jmx-operation `CommitLogMBean.setCDCBlockWrites` (:94) | `commit-log.set-cdc-block-writes` | commitlog-jmx-cdc-block-writes |
| jmx-operation `CommitLogMBean.setCDCOnRepairEnabled` (:100) | `commit-log.set-cdc-on-repair-enabled` | commitlog-jmx-cdc-on-repair |

Interfaces other areas are expected to call (my contracts):
- `mutation.apply` (coordination's performLocally), `mutation.apply-future`, `keyspace.apply`,
  `keyspace.apply-future` (hints, batchlog, paxos commit), `counter-mutation.apply-counter-mutation`
  (coordination's counter write task).
- `column-family-store.force-flush` / `force-blocking-flush` (ops: `nodetool flush`, membership:
  drain, repair-streaming: streaming/validation flushes), `column-family-store.truncate-blocking`
  (cql: TruncateStatement.executeLocally).
- `mutation-verb-handler.do-verb`, `counter-mutation-verb-handler.do-verb`,
  `truncate-verb-handler.do-verb` (internode messages, kind `verb`).
- `skip-list-memtable.cells-query` / `cells-get` (store of each replica's data; read-path may read it).

How a replica's answer looks to the coordinator (`mutation-verb-handler.do-verb`):
- success: returns `{from, verb: MUTATION_RSP}`;
- failure response: the error code names the exception (`mutation-exceeded-max-size` 8704,
  `cdc-write` 5632, `fs-write-error` 0, `request-failure` for the out-of-range rejection), and
  `ctx.failureReason = UNKNOWN` (InboundSink.java:80-90, RequestFailureReason.forException);
- no reply: error code `timeout` (same as a mosaic timeout fault), for an expired message or a
  swallowed WriteTimeoutException from the MV lock.

### Skipped entry points

- The 12 `CommitLogMBean` getters: `getArchiveCommand` (:30), `getRestoreCommand` (:35),
  `getRestoreDirectories` (:40), `getRestorePointInTime` (:54), `getRestorePrecision` (:60),
  `getActiveSegmentNames` (:70), `getArchivingSegmentNames` (:75), `getActiveContentSize` (:80),
  `getActiveOnDiskSize` (:85), `getActiveSegmentCompressionRatios` (:90), `getCDCBlockWrites` (:92),
  `isCDCOnRepairEnabled` (:97). Reason: reads of config or segment metrics, no behavior.
  (The checker shows `getCDCBlockWrites` and `isCDCOnRepairEnabled` as covered only because the
  setter citations at :94 and :100 fall within its ±3-line tolerance.)
- `ShardedMemtableConfigMXBean.setDefaultShardCount` (:27) and `getDefaultShardCount` (:32):
  a config attribute of the sharded memtable, which the deployed config doesn't use (default memtable is
  SkipListMemtable). No behavior beyond storing the value.

### Inventory entries near my area that I did not claim

- `ColumnFamilyStoreMBean.*` (db/ColumnFamilyStoreMBean.java, 45 entries): not under my paths, and
  nearly all of them are compaction, compression, sstable or sampling operations (read-path) or getters.
  None of them is flush or truncate. Suggest read-path or ops.
- `nodetool flush` (tools/nodetool/Flush.java) and `StorageServiceMBean.forceKeyspaceFlush` are ops entries.
  They should call `column-family-store.force-blocking-flush` (USER_FORCED); StorageService.java:4743-4750
  calls forceBlockingFlush once per table.
- View nodetool/JMX (`viewbuildstatus`, `get/setconcurrentviewbuilders`, `CompactionManagerMBean.*ViewBuild*`,
  `StorageServiceMBean.getViewBuildStatuses*`) are ops entries; `CREATE/ALTER/DROP MATERIALIZED VIEW` are schema-auth.
- `CacheServiceMBean.*CounterCache*` and `nodetool invalidatecountercache` are ops/read-path (cache).
- `StorageProxyMBean/StorageServiceMBean.get/setCounterWriteRpcTimeout` are ops (config).
- **Coverage spillover:** my `net/Verb.java` citations (116, 134, 137, 186) put 14 *other* verbs
  within the checker's ±3-line tolerance, so they show as covered: MUTATION_RSP, HINT_RSP, HINT_REQ,
  READ_REPAIR_RSP, PAXOS_COMMIT_REQ, TRUNCATE_RSP, COUNTER_MUTATION_RSP, READ_RSP, READ_REQ,
  SNAPSHOT_RSP, SNAPSHOT_REQ, PAXOS2_COMMIT_REMOTE_RSP, PAXOS2_PREPARE_RSP, PAXOS2_PREPARE_REQ.
  Their owners must still model them. A coverage report that counts them as write-path work is
  wrong.

## 2. Components modeled (36 own, plus 7 boundary stub components)

| Component | Code |
|---|---|
| mutation-verb-handler | db/MutationVerbHandler.java:29-94 |
| abstract-mutation-verb-handler | db/AbstractMutationVerbHandler.java:36-81 |
| counter-mutation-verb-handler | db/CounterMutationVerbHandler.java:30-55 |
| truncate-verb-handler | db/TruncateVerbHandler.java:28-47 |
| mutation | db/Mutation.java:55-300 |
| counter-mutation | db/CounterMutation.java:55-335 |
| keyspace | db/Keyspace.java:85-785 |
| cassandra-keyspace-write-handler | db/CassandraKeyspaceWriteHandler.java:32-131 |
| cassandra-table-write-handler | db/CassandraTableWriteHandler.java:24-40 |
| column-family-store (flush/truncate) | db/ColumnFamilyStore.java (flush 995-1440, apply 1467-1503, truncate 2740-2846, snapshot 2334-2389, discardSSTables 3295-3319) |
| column-family-store-flush | db/ColumnFamilyStore.java:1175-1411 |
| column-family-store-post-flush | db/ColumnFamilyStore.java:1123-1165 |
| skip-list-memtable | db/memtable/SkipListMemtable.java:66-140 |
| abstract-allocator-memtable | db/memtable/AbstractAllocatorMemtable.java:55-324 |
| flushing-flush-runnable | db/memtable/Flushing.java:130-201 |
| memtable-allocator | utils/memory/MemtableAllocator.java:31-303 |
| memtable-pool | utils/memory/MemtablePool.java:42-262 |
| memtable-cleaner-thread-clean | utils/memory/MemtableCleanerThread.java:44-123 |
| commit-log | db/commitlog/CommitLog.java:75-712 |
| abstract-commit-log-service (+ SyncRunnable) | db/commitlog/AbstractCommitLogService.java:51-344 |
| periodic-/batch-/group-commit-log-service | PeriodicCommitLogService.java:26-46, BatchCommitLogService.java:22-44, GroupCommitLogService.java:27-43 |
| abstract-commit-log-segment-manager (+ AllocatorRunnable) | db/commitlog/AbstractCommitLogSegmentManager.java:69-665 |
| commit-log-segment-manager-standard | CommitLogSegmentManagerStandard.java:24-69 |
| commit-log-segment-manager-cdc (+ CDCSizeTracker) | CommitLogSegmentManagerCDC.java:48-452 |
| commit-log-segment | CommitLogSegment.java:66-767, MemoryMappedSegment.java |
| commit-log-archiver | CommitLogArchiver.java:55-371 |
| commit-log-replayer, commit-log-replayer-mutation-initiator | CommitLogReplayer.java:72-571 |
| commit-log-reader | CommitLogReader.java:50-532 |
| view-manager | db/view/ViewManager.java:56-207 |
| table-views | db/view/TableViews.java:52-580 |
| view | db/view/View.java:48-266 |
| view-builder | db/view/ViewBuilder.java:60-249 |
| view-builder-task | db/view/ViewBuilderTask.java:66-273 |

Naming deviation: the inner `Runnable`s `AbstractCommitLogService.SyncRunnable` and
`AbstractCommitLogSegmentManager.AllocatorRunnable` are modeled as interfaces on their outer
component (`abstract-commit-log-service.sync-runnable-run`, `abstract-commit-log-segment-manager.allocator-runnable-run`)
and not as separate `*-sync-runnable` components. They read and write the outer class's fields
(lastSyncedAt, syncRequested, availableSegment), and mosaic state is per component.
`ColumnFamilyStore.Flush`/`PostFlush` and `MemtableCleanerThread.Clean` follow the rule
(`column-family-store-flush`, `column-family-store-post-flush`, `memtable-cleaner-thread-clean`).

## 3. Boundary stubs (no owner fragment existed when I wrote them; shared shapes used)

| Stub | Owner | Code |
|---|---|---|
| `storage-proxy.apply-counter-mutation-on-leader` | coordination | service/StorageProxy.java:1806-1810 |
| `storage-proxy.mutate-mv` | coordination | service/StorageProxy.java:1010-1113 |
| `storage-service.is-endpoint-valid-for-write` (response `{valid}`) | membership | service/StorageService.java:5209-5213 |
| `gossiper.wait-for-schema-agreement` (response `{agreed}`) | membership | gms/Gossiper.java:2519 |
| `single-partition-read-command.query-memtable-and-disk` | read-path | db/SinglePartitionReadCommand.java:658 |
| `single-partition-read-command.execute-locally` | read-path | db/ReadCommand.java:426 |
| `secondary-index-manager.truncate-all-indexes-blocking` | read-path | index/SecondaryIndexManager.java:907 |
| `compaction-manager.submit-view-builder` | read-path | db/compaction/CompactionManager.java:1986 |
| `active-repair-service.abort` | repair-streaming | service/ActiveRepairService.java:1095 |
| `commitlog-disk.segment-create/-append/-sync/-read/-delete` | shared | (io) |
| `data-disk.sstable-write`, `data-disk.snapshot-create` | shared | (io) |

The read stubs send the shared `read_command` fields inline (`keyspace, table, partition_key,
token, columns, limit, digest`). Boundary components (`storage-proxy`, `storage-service`, `gossiper`,
`single-partition-read-command`, `secondary-index-manager`, `compaction-manager`,
`active-repair-service`) carry only id, name, parent (the owner's module) and the boundary attributes.
Expect to align them in the reconciliation round.

## 4. Deployed config read

| Setting | conf/cassandra.yaml | Config.java default | Effective (modeled) |
|---|---|---|---|
| commitlog_sync | `periodic` (:634) | null (must be set) | periodic (`abstract-commit-log-service.state.commitlog_sync`) |
| commitlog_sync_period | `10000ms` (:636) | `0ms` (:395) | 10000ms |
| periodic_commitlog_sync_lag_block | commented (:641) | null (:403) | 1.5 × period = 15000ms (DatabaseDescriptor.java:3423-3429) |
| commitlog_sync_group_window | commented `1000ms` (:629) | `0ms` (:393) | unused (not group). With group and 0ms, `start()` throws (AbstractCommitLogService.java:150-152) |
| marker interval | n/a | 100ms constant (AbstractCommitLogService.java:57) | 100ms (uncompressed, so markHeadersFaster) |
| commitlog_segment_size | `32MiB` (:660) | `32MiB` (:397) | 32MiB |
| max_mutation_size | not in yaml (comment only :652) | null (:407) | segment/2 = 16MiB (DatabaseDescriptor.java:898-899) |
| commitlog_total_space | commented `8192MiB` (:883) | null (:390) | min(8192MiB, 1/4 of volume) (DatabaseDescriptor.java:664-674); modeled 8GiB |
| commitlog_disk_access_mode | `legacy` (:678) | `legacy` (:401) | mmap (legacy + uncompressed, DatabaseDescriptor.java:1525-1528) |
| commitlog_compression | commented (:665) | null | none |
| commit_failure_policy | `stop` (:488) | `stop` (:125) | stop |
| cdc_enabled | `false` (:413) | `false` (:410) | false (CommitLogSegmentManagerStandard) |
| cdc_block_writes | commented `true` (:418) | `true` (:413) | true |
| cdc_on_repair_enabled | commented `true` (:425) | `true` (:416) | true |
| cdc_total_space | commented `4096MiB` (:923) | `0MiB` (:419) | min(4096MiB, 1/8 volume) when 0 (DatabaseDescriptor.java:684-694) |
| write_request_timeout | `2000ms` (:1330) | `2000ms` (:151) | 2000ms (MV lock timeout) |
| counter_write_request_timeout | `5000ms` (:1334) | `5000ms` (:154) | 5000ms (counter lock timeout, CounterMutation.java:328-331) |
| truncate_request_timeout | `60000ms` (:1345) | `60000ms` (:160) | not used on the replica |
| concurrent_writes / counter / MV writes | 32 / 32 / 32 (:723-728) | 32 (:180-182) | not modeled (stage sizes). MV writes size the view lock stripes ×1024 |
| memtable (default) | `default: inherits skiplist` (:783-791) | n/a | SkipListMemtable |
| memtable_allocation_type | `heap_buffers` (:825) | `heap_buffers` (:524) | SlabPool on heap |
| memtable_heap_space | commented `2048MiB` (:797) | null (:187) | 1/4 heap; **assumed 8GiB heap -> 2048MiB** |
| memtable_flush_writers | commented `2` (:912) | 0 (:185) | 2 (one data dir; DatabaseDescriptor.java:753-755) |
| memtable_cleanup_threshold | commented `0.11` (:812) | null (:190) | 1/(writers+1) = 0.333 (DatabaseDescriptor.java:761-763) |
| auto_snapshot | `true` (:1147) | `true` (:313) | true |
| materialized_views_enabled | `false` (:1981) | `false` (:596) | false. It only gates CREATE MATERIALIZED VIEW (schema-auth). The write path still maintains views that exist. |
| concurrent_materialized_view_builders | `1` (:1242) | `1` (:346) | 1 |
| log_out_of_token_range_requests | not in yaml | `true` (:792) | true |
| reject_out_of_token_range_requests | not in yaml | `false` (:793) | false |
| memtable_flush_period_in_ms (table param) | n/a | 0 (schema/TableParams.java:363) | 0, so no periodic flush |
| commitlog_archiving.properties | all empty (`archive_command=` etc.) | n/a | archiver is a no-op |

Where the yaml and Config.java differ: `commitlog_sync` (yaml periodic, Config null),
`commitlog_sync_period` (yaml 10000ms, Config 0ms), `commitlog_sync_group_window` (yaml example
1000ms is commented, Config 0ms), `cdc_total_space` (yaml comment says 4096MiB, Config 0MiB means
computed), `memtable_cleanup_threshold` (yaml comment 0.11, effective default 0.333),
`memtable_flush_writers` (Config 0 means computed 2).

## 5. What the code didn't settle, and assumptions

- **Ownership claims.** `TruncateVerbHandler` and `TRUNCATE_REQ` sit in `db/` and match no row of the table.
  I claimed them because write-path owns ColumnFamilyStore truncate and the handler only calls
  `cfs.truncateBlocking()`. Coordination owns `TruncateResponseHandler` (the coordinator side). The
  memtable pool and cleaner (`utils/memory/MemtablePool`, `MemtableAllocator`, `MemtableCleanerThread`)
  are under ops' `utils/**` ("only as needed"), but exist only for memtables, so I modeled them.
  `Cassandra{Keyspace,Table}WriteHandler` are unlisted `db/` classes on the write path.
  `ColumnFamilyStore.snapshot` is CFS code used by truncate. `service/snapshot/**` stays with
  repair-streaming.
- **Replica identity.** Store keys use `replica + ':' + keyspace.table + ':' + partition_key[:column]`.
  `replica` comes from the verb's `to`, or from `keyspace.state.local_endpoint` (10.0.0.1) for local applies.
- **The memtable's `cells` table stands for the replica's readable data.** A flush resets the memtable stats and
  writes an sstable (`data-disk.sstable-write`, plus a count in `column-family-store.live_sstables`),
  but leaves the cells in place so that reads after a flush still see the data. Only truncate
  deletes them. Partitions/cells are cell-level LWW (higher timestamp wins; ties: greater value,
  compared as strings), per db/rows/Cells.java:79-128. Tombstones, TTLs and deletion-time tie
  breaks are not modeled.
- **One memtable pool for all simulated replicas.** In reality each node has its own pool. All replicas share
  `memtable-pool` state in the sim.
- **Commit log segment state.** `commit-log-segment` represents whichever segment is `allocatingFrom`.
  `discard-unused-tail` rolls it to the next segment. The reserve segment is a flag on the manager
  (`available_segment`). `archive-and-discard` discards all older segments at once, unless a scenario
  picks `still_dirty`, because the model doesn't track per-segment dirty tables.
- **Write position returned by flushes** (`commit_log_upper_bound`) is fake data. Positions aren't tracked.
- **Counter values.** CounterMutation's shard arithmetic (clock = max(now, clock+1), count = current+delta)
  is narrated only. The result mutation carries the client's deltas. A counter cache hit or miss is a
  choice (the cache belongs to read-path). block_for in the counter WriteTimeoutException assumes RF 3.
- **View mutations** use the base partition key and the base columns. The real view key comes from the
  view's primary key (ViewUpdateGenerator). The paired-replica choice (ViewUtils.getViewNaturalEndpoint)
  is coordination's, inside `mutateMV`.
- **The view build's ranges and keys** are request defaults (two ranges, two keys). Local ranges come from
  StorageService.getLocalReplicas (membership), which is not stubbed. It is only narrated.
- **The view-lock timeout** is measured from when the mutation was created (`approxCreatedAtNanos +
  write_request_timeout`). The model approximates it as 20 attempts with 100ms backoff (about 2s
  from when the lock attempts start).
- `Keyspace.applyInternal` with a missing table logs an error and skips that update, but still
  "succeeds". The replica therefore acks a mutation for a table it doesn't know (wp-mutation-unknown-table).
- The `TEST_FAIL_WRITES` and `TEST_FAIL_MV_LOCKS_COUNT` system properties are test hooks and aren't modeled.

## 6. Where docs or common knowledge disagree with the code

- "materialized_views_enabled: false disables MVs": in the code it only gates creation. Existing views
  are still maintained on every base write (Keyspace.java:535, ViewManager.java:73-93).
- "The replica always answers": an expired MUTATION_REQ is silently dropped (MutationVerbHandler.java:47-52),
  and a WriteTimeoutException from the MV lock is swallowed with no reply (:39-42, :75). Both look
  like timeouts to the coordinator. Any other exception produces an explicit failure response
  through InboundSink (net/InboundSink.java:80-90), so it isn't a timeout.
- "Out-of-range writes are rejected": by default they're only logged and counted
  (`reject_out_of_token_range_requests` defaults to false, Config.java:793). They're still applied.
- "Periodic commitlog never blocks writes": it blocks when the last sync is more than
  1.5 × commitlog_sync_period old (PeriodicCommitLogService.java:36-45).
- "Truncate always snapshots": only when `auto_snapshot` is true and the table allows it
  (`allow_auto_snapshot`, CFS.java:3277-3280). Without a snapshot it still flushes when the keyspace is
  durable (CFS.java:2775-2781). It discards the memtable unwritten only when the keyspace is neither
  durable nor auto-snapshotting.
- "A mutation CRC failure in replay stops reading the segment": the reader reports it and *continues
  with the next entry* (CommitLogReader.java:384-393). Startup fails only through
  commit_failure_policy (stop/die/stop_commit) when the error isn't permissible.
- "Counter writes are just writes": a COUNTER_MUTATION_REQ skips the expiry and size checks that
  MUTATION_REQ does (AbstractMutationVerbHandler.doVerb has no expiry check).
- The yaml comment says `cdc_total_space` defaults to 4096MiB. Config.java's default is 0MiB, which
  DatabaseDescriptor turns into min(4096MiB, 1/8 of the cdc_raw volume).

## 7. Simulator gaps

- **Asynchronous futures run inline.** `applyFuture` deferral re-queues work on Stage.MUTATION
  (Keyspace.java:585-587). The model expresses it as call retries with backoff. Example:
  wp-mutation-view-lock-deferred shows `retries == 1` rather than a re-queued task.
- **Waiting for another thread.** Periodic/batch/group `awaitSyncAt`, `awaitAvailableSegment` and a writer
  blocked on `hasRoom` all wait for a different thread (the sync thread, the allocator thread, the cleaner
  plus a flush). The model runs that thread's iteration inline in the writer's call tree. Example:
  wp-mutation-memtable-pool-full runs the whole MEMTABLE_LIMIT flush inside the write. In reality the
  write waits for any flush that frees memory.
- **Flush executors.** Flush runs on MemtableFlushWriter (2 threads), the per-disk FlushRunnables run in
  parallel, and PostFlush on a single thread orders completion. All of this is sequential in the model,
  so flushes can't overlap and the ordering guarantee isn't exercised.
- **Infinite loops** (sync thread every 100ms, allocator, cleaner) are single iterations or
  `repeat` with coarse intervals (5000ms in commitlog-periodic-sync). Lag detection
  (`maybeLogFlushLag`) isn't modeled.
- **FORWARD_TO relays** are emitted after the entry call finishes. The relayed replicas' acks go to
  the original coordinator, and mosaic can't route an emit's result back to it. Example:
  wp-mutation-forwarded writes 10.0.0.3's memtable, but nobody counts its ack.
- **Per-component state.** CEL can't index `set` paths dynamically, so per-replica data has to live in
  `store` tables. Shared config such as table params is duplicated between `keyspace` and
  `column-family-store` state.
- **Per-cell reconciliation** needs a loop of store reads and writes per column. A merge of two
  maps isn't available in CEL.
- **"No reply" can't be expressed directly.** It's modeled as an error with code `timeout`, so it
  arrives immediately (expired message) instead of at the coordinator's callback expiry. The
  coordinator should use its own `timeout_ms`.

## 8. Known gaps

- Not modeled: ShardedSkipListMemtable/TrieMemtable, memtable sharding, compressed or encrypted and direct-I/O
  segments, commit log compression/encryption, point-in-time restore (archiver restore and
  `restore_point_in_time`), CDC index files and the CDC size recalculation executor,
  `forceRecycleAllSegments` (drain, drop table), `unloadCf`.
- Secondary index updates during apply (UpdateTransaction) and row-cache invalidation are
  narrated. They belong to read-path.
- Truncate's view truncation, view build stop/restart and cache invalidation are narrated only.
- Commit log replay doesn't apply truncation records or sstable intervals. A per-entry
  `already_persisted` flag stands in for them. Replay filters (`cassandra.replayList`) aren't
  modeled.
- Hint and batchlog application through `keyspace.apply` belong to hints-batchlog. They should call
  `keyspace.apply` / `mutation.apply` and not reimplement them.
- `drain` (membership) should call `column-family-store.force-blocking-flush` with reason DRAIN.

## 9. Reconciliation round

- **Repair cells (decision 5).** `WritePathMutation` gains an optional `cells` list
  (`[{column, value, timestamp}]`). `keyspace.apply` and `mutation.apply` pass the mutation through unchanged,
  and `skip-list-memtable.put` reconciles each listed cell with its own timestamp (Cells.java:79-84),
  in addition to the `columns` map.
- **Stubs now defined (decision 6):** `column-family-store.{add-sstables, import-new-sstables,
  load-new-sstables, on-paxos-repair-complete, reload, sync-paxos-repair-history}`, `commit-log.start`,
  `keyspace.{drop-cf, get-column-family-stores, init-cf, open, unload}`, and
  `view-utils.get-view-natural-endpoint` (choice self/remote/none; default self = 10.0.0.1, which matches
  coordination's earlier store default). Paxos repair history is kept in a `paxos_repair_history` store on
  column-family-store.
- **`column-family-store.snapshot`** now rejects names that contain `/` or are `.`/`..`
  (`illegal-argument-exception`), and ephemeral snapshots that have a TTL (`illegal-state-exception`)
  (CFS.java:2139-2186). It registers the TableSnapshot through repair-streaming's
  `snapshot-manager.add-snapshot` (CFS.java:2205-2232). Callers that also call add-snapshot after
  it write the same key twice, which is harmless.
- **ColumnFamilyStoreMBean:** `importNewSSTables` (:191) and `loadNewSSTables` (:253) are now mine
  and covered by flows `cfs-import-new-sstables` and `cfs-load-new-sstables`. That MBean has no
  flush operation.
- New flows: cfs-import-new-sstables, cfs-load-new-sstables, table-snapshot, schema-drop-table (8 new scenarios).
- Fixed wp-counter-verb-forwards-to-leader-path: it no longer asserts that `mutation.validate-size` is never
  called, because coordination's leader path legitimately validates (decision 9).
- Skips are written to `skips/write-path.json` (14 entries, the groups listed in §1).
- **Tombstones (follow-up).** `skip-list-memtable.put` stores cell tombstones as cells with
  `deleted: true, value: null`. A tombstone comes from a `cells` entry with `deleted: true` or a null
  value in `columns`. A partition deletion (`mutation.partition_deletion: true`) is recorded as
  `deletion_timestamp` on the partition row. It is also written as a tombstone over every older live
  cell, so read-path's cells-query sees it. Later cells not newer than that timestamp are dropped.
  Reconciliation: the higher timestamp wins; on a tie a tombstone beats a live cell (Cells.java:83-128).
  Range tombstones and TTL/expiring cells are not modeled. Read-path counts each shadowing cell
  tombstone written for a partition deletion against its tombstone thresholds, which over-counts
  compared with the real single partition-level DeletionTime.

## 10. Migration round (instances, parallel, config, fixtures)

- **Instances.** I removed every `to`, `from` and `replica` request field and the `local_endpoint` state.
  Behaviors use `self`, and per-replica store keys lost their `<replica>:` prefix: memtable cells are keyed
  `ks.table:pk:col` on each instance. FORWARD_TO relays are `emit ... on: <instance>`. The private table lists
  in `keyspace`, `column-family-store` and `view-manager` were emptied, so base-schema seeds them. `init-cf`,
  `drop-cf`, `open` and `unload` maintain them with `merge`/`omit`.
- **Config.** 28 config entities: commit log sync and sizes, CDC, memtable pool, auto_snapshot, the
  out-of-token-range flags, and the concurrency values that size the capacities. Six are boundary
  references because another area owns them: write/counter timeouts (coordination),
  concurrent_materialized_view_builders (read-path), cdc_on_repair_enabled (repair-streaming) and
  reject_out_of_token_range_requests (coordination). log_out_of_token_range_requests is a copy identical
  to paxos's definition. JMX setters still override cdc_block_writes and cdc_on_repair_enabled through state.
- **Capacity:** MUTATION and COUNTER_MUTATION stages 32 each, MemtableFlushWriter 2, MemtablePostFlush 1, and
  the view build executor 1.
- **parallel:** the view build's range tasks (`FutureCombiner.allOf`, join all) queue on the capacity-1 view
  build executor. Write-path has no replica fan-out of its own; that belongs to coordination.
- **Deadlines:** an expired MUTATION_REQ is detected through `deadline`. It is checked before deserialization
  (InboundMessageHandler.java:414-423) and again in doVerb.
- **Judged fixes:**
  - (W wrong claim 1 / C1) Every table comes from base-schema. A MUTATION_REQ for an unknown table now fails
    at deserialization with `unknown-table` (an INCOMPATIBLE_SCHEMA failure response;
    PartitionUpdate.java:723, InboundMessageHandlers.java:247-256).
  - (wrong claim 2) In a local apply, the commit log append comes before the unknown-table skip
    (Keyspace.java:625-634).
  - (W10) Replay lists this node's commit log directory (`commit-log.segments_on_disk`, CommitLog.java:168-174).
    Every `commit-log.add` writes its entry there, and a flush marks the entries persisted and deletes
    files that become unused. Replay now also calls maybeWaitForArchiving and lists the files again
    (CommitLog.java:187-197).
  - (C1) A flush (and add-sstables) calls `tracker.add-sstables` and then `compaction-manager.submit-background`
    (CFS.java:1679-1682, 1835-1839).
  - (claim 5) TableViews citations fixed.
- **Simulator gaps resolved:**
  - One memtable pool per node (state is per instance).
  - Per-replica stores without key prefixes.
  - Expiry tied to the real request deadline.
  - Stage and executor sizes via capacity.
  - Timestamps derive from `now`; the sync thread's first iteration records its start time.
- **Simulator gaps still open:**
  - Waits on other threads are still inline (await-sync-at forces a flushing sync iteration).
  - View-lock deferral is still retries with backoff.
  - FORWARD_TO acks can't reach the original coordinator.

## 11. Fix round (W9, commit-log discard, B1-xtable, P2 pending repair)

- **A flush moves the data into the sstable (W9, judge wrong claim 1).** `skip-list-memtable.switch-out`
  returns the retired memtable's cells and partitions (getFlushSet, SkipListMemtable.java:246-250);
  `flushing-flush-runnable.call` turns them into sstable partitions `{cells, deletion_ts, tombstones,
  size_bytes, token}` (Flushing.java:157-174); `column-family-store.add-to-tracker` publishes them with
  `max_timestamp` in read-path's View (CFS:1836-1837); `skip-list-memtable.discard` then drops exactly the
  flushed cells and partitions (reclaim, CFS:1391-1404). A cell rewritten after the switch stays (new
  memtable). A failed flush reclaims nothing. Reads after a flush go through `big-table-reader.row-iterator`.
- **Commit-log discard deletes only unused segments (CommitLog.java:353-383, judge wrong claims 2, 3).**
  The `active_segments` counter path and its `oldest_segments` choice are gone.
  `commit-log.discard-completed-segments` walks the segment files oldest first, marks the table clean per
  entry (`clean_tables`, `already_persisted` once every table of the entry is clean), hands each
  `isUnused` segment to `abstract-commit-log-segment-manager.archive-and-discard` (now per segment:
  archive wait, delete that file, decrement `active_segments`; AbstractCommitLogSegmentManager.java:402-414),
  and stops at the allocating segment, which holds the flush's upper bound (CommitLog.java:379-381).
- **Multi-table mutations (B1-xtable).** `WritePathMutation.updates` is the complete list of the
  Mutation's PartitionUpdates (Mutation.java:65, 147), one per table; the top-level table and columns
  mirror the first. This is the shape cql's `batch-statement.get-mutations` now builds. `keyspace.apply-internal`
  appends once to the commit log and writes each update into its own table's memtable, skipping unknown
  tables with `continue` (Keyspace.java:626-653). Replay re-applies only the updates whose table is not
  clean (CommitLogReplayer.java:307-321). Gap: the view check and lock still use the first table only.
- **pending_repair kept (P2, for repair-streaming).** `column-family-store.add-sstables` takes
  `pending_repair` and `add-to-tracker` stores it on the sstable in the View (CFS:1679-1681).
- Scenarios rewritten: `wp-flush-dirty` and `wp-flush-segments-still-dirty` seed real segment files;
  `wp-write-flush-read`, the replay and JMX-recover read-backs now read through
  `single-partition-read-command.query-memtable-and-disk` or the Tracker View, because the post-replay
  flush (CommitLogReplayer.java:244-270) moves replayed rows into an sstable. New: `wp-local-apply-two-tables`,
  `wp-two-tables-flush-one-then-replay`.

### Breaking changes

- `abstract-commit-log-segment-manager.archive-and-discard`: request is now `{name, id}` (one segment), not a
  table ref; the `oldest_segments` choice is removed. Callers: only write-path (fixed).
- `skip-list-memtable.switch-out`, `column-family-store-flush.run`, `flushing-flush-runnable.call`,
  `skip-list-memtable.discard`, `column-family-store.add-to-tracker`, `column-family-store.add-sstables`:
  new optional fields only (`cells`, `partition_rows`, `partitions`, `max_timestamp`, `pending_repair`).
- Observable: after any flush, the flushed rows are no longer in `skip-list-memtable.cells`. Scenarios that
  read `skip-list-memtable@n.cells` after a flush must read the Tracker View or go through a read.
  **judge/v2 `W10.yaml` `bench-w10`** asserts `state['skip-list-memtable@n1'].cells['shop.users:user:43:name']`
  after the startup replay, whose blockForWrites flush (CommitLogReplayer.java:244-270) moves the row into
  an sstable. The judge's own W9 wrong claim 1 says this "holds after replay's flush (W10)". The assertion
  now contradicts the code; it should read `state['tracker@n1'].views['shop.users'].sstables` (coordinator).

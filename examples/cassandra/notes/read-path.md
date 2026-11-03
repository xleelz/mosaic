# read-path notes

Fragment: `examples/cassandra/fragments/read-path.yaml`. Code: cassandra-5.0.9 (`b5f2a54210`).
All paths below are relative to `src/java/org/apache/cassandra/` unless they start with `conf/`.

Final standalone check (skeleton + this fragment, `--strict-citations --inventory -v`):

```
entities: 52 components, 67 interfaces, 0 links, 9 schemas, 16 flows, 70 scenarios (12 boundary stubs)
validation: 0 errors, 0 warnings
scenarios: 70 passed, 0 failed
citations: 282 cited, 282 ok, 0 missing, 0 bad_line, 0 dir, 0 packed, 0 skipped; 0 entities with problems
```

Citation samples were read against the code with seeds 7, 42 and 1234. Fixes made after sampling:
CompactionManager cleanup and stop line ranges, the background resubmit line (382-383), the
flushInProgress check (1939-1943), getUserDefinedTasks (1112-1130), the row cache get (516), and the
CompactionStrategyManager summary (it orders suppliers by remaining tasks, not unrepaired first).

## 1. Entry points

43 inventory entries fall under read-path paths. 12 are covered by line and 31 are skipped.

| Entry | Covered by |
|---|---|
| verb-handler `ReadCommandVerbHandler.doVerb` (db/ReadCommandVerbHandler.java:50) | `read-command-verb-handler.do-verb`, flow `replica-read` |
| messaging-verb `READ_REQ` (net/Verb.java:140) | `read-command-verb-handler.do-verb` sources, flow `replica-read` |
| messaging-verb `RANGE_REQ` (net/Verb.java:142) | same interface, scenarios `read-range-*`, `read-legacy-index`, `read-sai-*` |
| jmx `CompactionManagerMBean.forceUserDefinedCompaction` (:44) | `compaction-manager.force-user-defined-compaction`, flow `user-defined-compaction` |
| jmx `CompactionManagerMBean.forceUserDefinedCleanup` (:54) | `compaction-manager.force-user-defined-cleanup`, flow `user-defined-cleanup` |
| jmx `CompactionManagerMBean.stopCompaction` (:66) | `compaction-manager.stop-compaction`, flow `stop-compaction` |
| jmx `CompactionManagerMBean.stopCompactionById` (:74) | `compaction-manager.stop-compaction-by-id`, flow `stop-compaction-by-id` |
| jmx `IndexSummaryManagerMBean.redistributeSummaries` (:41) | `index-summary-manager.redistribute-summaries`, flow `index-summary-redistribute-jmx` |
| jmx `IndexSummaryManagerMBean.setResizeIntervalInMinutes` (:49) | `index-summary-manager.set-resize-interval-in-minutes`, flow `index-summary-resize-interval` |
| scheduled `AutoSavingCache.scheduleSaving: runnable` (cache/AutoSavingCache.java:174) | `auto-saving-cache.submit-write`, flow `cache-periodic-save` (repeat every 4h) |
| scheduled `SSTableReader.GlobalTidy.ensureReadMeter: maybePersistSSTableReadMeter` (io/sstable/format/SSTableReader.java:1649) | `sstable-reader-global-tidy.maybe-persist-sstable-read-meter`, flow `sstable-read-meter-sync` (repeat every 5 min) |
| scheduled `IndexSummaryManager.setResizeIntervalInMinutes: WrappedRunnable` (io/sstable/indexsummary/IndexSummaryManager.java:141) | `index-summary-manager.redistribute-summaries`, flow `index-summary-periodic-redistribution` (repeat every 60 min) |

Interfaces that other areas call: `read-command.execute-locally` (coordination's LocalReadRunnable),
`compaction-manager.submit-background` (write-path after flush, ops' periodic submitter at
service/CassandraDaemon.java:435), `compaction-manager.perform-maximal` and `perform-cleanup` (ops'
nodetool compact and cleanup), `auto-saving-cache.schedule-saving`, `submit-write` and `load-saved`
(ops, CacheService), `index-status-manager.filter-for-query` (coordination's ReplicaPlans:656).
These accept a missing `replica` (defaulting to 10.0.0.1) and, for `execute-locally` and
`query-memtable-and-disk`, a flattened command instead of `read_command`.

### Skipped entry points

- The 25 CompactionManagerMBean attributes in db/compaction/CompactionManagerMBean.java:
  `getCompactions`, `getCompactionSummary`, `getCompactionHistory` (reads of the active list and
  system.compaction_history, no behavior) and `getCoreCompactorThreads`, `setCoreCompactorThreads`,
  `getMaximumCompactorThreads`, `setMaximumCompactorThreads`, `getCoreValidationThreads`,
  `setCoreValidationThreads`, `getMaximumValidatorThreads`, `setMaximumValidatorThreads`,
  `getCoreViewBuildThreads`, `setCoreViewBuildThreads`, `getMaximumViewBuildThreads`,
  `setMaximumViewBuildThreads`, `getMaximumSecondaryIndexExecutorThreads`,
  `setMaximumSecondaryIndexExecutorThreads`, `getCoreSecondaryIndexExecutorThreads`,
  `setCoreSecondaryIndexExecutorThreads`, `getDisableSTCSInL0`, `setDisableSTCSInL0`,
  `getAutomaticSSTableUpgradeEnabled`, `setAutomaticSSTableUpgradeEnabled`,
  `getMaxConcurrentAutoUpgradeTasks`, `setMaxConcurrentAutoUpgradeTasks`. Reason: getters and setters
  of executor pool sizes and config flags. The flags they flip are modeled as state
  (`compaction-manager.executor_max_pool_size`, `leveled-manifest.disable_stcs_in_l0`,
  `compaction-manager.automatic_sstable_upgrade`), so there is no separate flow.
- The 6 IndexSummaryManagerMBean attributes in io/sstable/indexsummary/IndexSummaryManagerMBean.java:
  `getMemoryPoolCapacityInMB`, `setMemoryPoolCapacityInMB`, `getMemoryPoolSizeInMB`,
  `getIndexIntervals`, `getAverageIndexInterval`, `getResizeIntervalInMinutes`. Reason: config and
  metric reads. The capacity setter only changes the pool that the next redistribution uses.

Related entries outside read-path paths, so not counted here: `ReadRepairVerbHandler.doVerb` /
`READ_REPAIR_REQ` (db/ReadRepairVerbHandler.java, no read-path row), the CacheService stage tasks
(service/CacheService.java, no owner row), and `CassandraDaemon.setup` background compaction
submitter (ops). Ops should point it at `compaction-manager.submit-background`.

## 2. Components (all under the `read-path` module)

| Component | Code |
|---|---|
| read-command-verb-handler | db/ReadCommandVerbHandler.java:42-135 |
| read-command | db/ReadCommand.java:426-503 (executeLocally), 525-654 (tombstones), 663-745 (read size), 865-887 (purge) |
| single-partition-read-command | db/SinglePartitionReadCommand.java:487-855 |
| partition-range-read-command | db/PartitionRangeReadCommand.java:312-380 |
| read-execution-controller | db/ReadExecutionController.java:129-171 |
| big-table-reader | io/sstable/format/big/BigTableReader.java:126-134, 214-361 |
| bti-table-reader | io/sstable/format/bti/BtiTableReader.java:222-260 (declared only, not the deployed format) |
| sstable-reader-global-tidy | io/sstable/format/SSTableReader.java:1632-1660 |
| auto-saving-cache, auto-saving-cache-writer | cache/AutoSavingCache.java:71-460 |
| compaction-manager, compaction-manager-background-compaction-candidate | db/compaction/CompactionManager.java:141-263, 343-409, 617-677, 986-1030, 1155-1282, 1408-1496, 1928-1964, 2217-2236, 2502 |
| active-compactions | db/compaction/ActiveCompactions.java:38-55, CompactionInfo.java:249-269 |
| compaction-strategy-manager | db/compaction/CompactionStrategyManager.java:197-239, 1076-1130 |
| size-tiered-compaction-strategy | db/compaction/SizeTieredCompactionStrategy.java:79-230 |
| leveled-compaction-strategy, leveled-manifest | db/compaction/LeveledCompactionStrategy.java:131-182, LeveledManifest.java:199-317, 495-570 |
| time-window-compaction-strategy | db/compaction/TimeWindowCompactionStrategy.java:83-361 |
| unified-compaction-strategy | db/compaction/UnifiedCompactionStrategy.java:220-344 |
| compaction-task, compaction-controller, compaction-iterator | db/compaction/CompactionTask.java:98-472, AbstractCompactionTask.java:96-112, CompactionController.java:245-284, CompactionIterator.java:341-410, 720-746 |
| tracker, lifecycle-transaction | db/lifecycle/Tracker.java:115-150, LifecycleTransaction.java:215-300 |
| index-summary-manager, index-summary-redistribution | io/sstable/indexsummary/IndexSummaryManager.java:100-290 |
| secondary-index-manager | index/SecondaryIndexManager.java:314-321, 1245-1290 |
| cassandra-index-searcher | index/internal/CassandraIndexSearcher.java:56-103 |
| storage-attached-index-searcher, query-controller | index/sai/plan/StorageAttachedIndexSearcher.java:82-215, QueryController.java:248-345 |
| index-status-manager | index/IndexStatusManager.java:64-133 |

Simulation data model:
- Written data comes from write-path's `skip-list-memtable` cells table (one row per cell, key
  `replica:ks.table:pk:column`). write-path documents that this table also stands for data already
  flushed.
- Extra sstable state lives on `data-disk`, store table `sstables`, key `replica:ks.table:pk`. That
  covers partition deletions, tombstone counts (`tombstones`, `purgeable_tombstones`), `sstable_count`
  and `size_bytes`, plus data put directly in sstables (index tables, seeded rows).
- Reads merge both sources cell by cell: the newest timestamp wins, and a partition deletion hides
  older cells.
- Partitions are `{partition_key, cells: [{column, value, timestamp}], timestamp}`. The digest is
  `md5:` + `pk|col=value@ts,...` with columns sorted.
- Compaction state is the Tracker View per table (store `tracker.views`, key `replica:ks.table`).
  It holds the sstable list (id, size_mb, level, repaired, droppable_tombstone_ratio, age_s,
  fully_expired, tombstones, purgeable_tombstones, unowned_mb, window), the compacting set, and the
  table's compaction parameters.

## 3. Boundary stubs

| Stub | Owner | Contract source |
|---|---|---|
| `skip-list-memtable` component, `skip-list-memtable.cells-query` | write-path | Copied write-path's store exactly (table cells, op query, same `where`). The request is left out because it is write-path's `WritePathTableRef` schema, which only write-path may define. Kind/parent/layer copied. |
| `storage-service.is-bootstrap-mode` | membership | Membership does not define it yet. Copied coordination's stub (store table `mode`, key `local`, default `{bootstrapping: false}`) so the stubs merge cleanly. Membership's own state has `is_bootstrap_mode`; the owner should define this interface. |
| `storage-service.is-joined` | membership | Membership's contract: no request, response `{joined}`. Standalone, the stub reads store table `joined_by_endpoint` (key `local`). The not-joined scenario also sets membership's `survey_mode: true`, so it still holds under the owner's behavior. |
| `token-metadata.get-pending-ranges` | membership | Not defined by membership. Response `{ranges: [string]}` follows ops' stub. Standalone store table `pending_ranges_by_keyspace` (membership's `pending_ranges` is a list, so that name can't be reused as a table). |
| `data-disk.sstable-read`, `sstable-scan`, `sstable-write`, `saved-cache-write`, `saved-cache-read` | shared | `kind: io`. The read and scan stubs are stores over `data-disk.sstables`, and the saved-cache stubs over `data-disk.saved_caches`. `sstable-write` merges with write-path's stub. |

Merged check (all fragments except schema-auth, whose YAML did not parse at the time) shows no
warnings that mention read-path.yaml.

## 4. Deployed config read

| Setting | conf/cassandra.yaml | Config.java default | Effective |
|---|---|---|---|
| read_request_timeout | 5000ms (:1322) | 5000ms (:145) | READ_REQ deadline 5000ms |
| range_request_timeout | 10000ms (:1326) | 10000ms (:148) | RANGE_REQ deadline 10000ms |
| tombstone_warn_threshold / tombstone_failure_threshold | 1000 / 100000 (:1814-1815) | same (:534-535) | as yaml |
| read_thresholds_enabled | commented (:2015) | false (:526) | off, so TRACK_WARNINGS is not sent |
| local_read_size_warn/fail_threshold | commented (:2025-2026) | null (:529-530) | off |
| key_cache_size | empty, auto (:525) | null, auto (:468) | min(5% heap, 100MiB) > 0 |
| key_cache_save_period | 4h (:538) | 4h (:470) | 4h |
| row_cache_size / row_cache_save_period | 0MiB / 0s (:564, :575) | 0MiB / 0s (:474, :476) | row cache off, not saved |
| counter_cache_save_period | 7200s (:603) | 7200s (:482) | 7200s |
| cache_load_timeout | commented (:617) | 30s (:488) | 30s |
| concurrent_compactors | commented (:1230) | null (:335) | DatabaseDescriptor.java:777-778: min(8, max(2, min(cores, dirs))) = 2 with one data dir |
| compaction_throughput | 64MiB/s (:1251) | 64MiB/s (:337) | 64MiB/s |
| snapshot_before_compaction | false (:1141) | false (:312) | false |
| default_compaction | commented (:1209) | null (:1161) | STCS, min 4, max 32 (schema/CompactionParams.java:79-104) |
| automatic_sstable_upgrade | commented (:1887) | false (:697) | false |
| index_summary_resize_interval | 60m (:947) | 60m (:543) | 60m |
| index_summary_capacity | empty (:939) | null (:540) | auto, 5% heap |
| sstable.selected_format | commented (:1171-1172) | big (:373) | BIG |
| storage_compatibility_mode | CASSANDRA_4 (:2320) | no default (null, :1380) | CASSANDRA_4 (DatabaseDescriptor.java:239 also falls back to CASSANDRA_4), so BIG version "nb" |
| default_secondary_index | commented (:2260) | legacy_local_table (:900) | CREATE INDEX makes a CassandraIndex |
| sai_sstable_indexes_per_query warn/fail | commented (:2240, :2243) | 32 / -1 (:939-940) | warn above 32, fail disabled |
| log_ / reject_out_of_token_range_requests | not present | true / false (:792-793) | out-of-range reads are logged and served |
| sstable_read_rate_persistence_enabled | not present | false (:1146) | read meters are not persisted |
| disk_access_mode | commented (:448) | mmap_index_only (:122) | mmap_index_only (not modeled) |
| concurrent_reads | 32 (:722) | 32 (:179) | READ stage size (not modeled) |

The only difference between the two files is `storage_compatibility_mode`: the yaml sets it,
Config.java has no default, and both end up at CASSANDRA_4. Code constants used: gc_grace_seconds
864000 (schema/TableParams.java:360), STCS bucket 0.5/1.5 and min 50MiB, tombstone_threshold 0.2,
tombstone_compaction_interval 86400s, LCS sstable 160MiB and fanout 10, MAX_COMPACTING_L0 32, UCS
scaling parameter T4 (threshold 4).

## 5. What the code didn't settle, and assumptions

- Out-of-range ownership (`isOutOfRangeRead`) depends on the ring. It is a choice
  (`read-command-verb-handler.do-verb.token_ownership`). Membership's replica interfaces could
  replace it.
- A replica's failure response carries only a RequestFailureReason. The verb handler fails with the
  replica-side exception name (`tombstone-overwhelming`, `runtime`, `index-not-available`,
  `corrupt-sstable`, ...) and puts `data.failure_reason` / `data.failure_code` next to it (1 for
  tombstones, 0 UNKNOWN otherwise). No native-protocol status is set, because the coordinator turns
  failures into read-failure (0x1300).
- A dropped read (rejected out of range, or past its deadline) is modeled as waiting past the verb
  timeout and then failing with `timeout`. That way the coordinator's call times out whether or not
  it set `timeout_ms`.
- Digest: the real digest is MD5 over the serialized partitions. The model concatenates the
  reconciled cells, so equal data gives equal digests and different data gives different ones.
- Compaction output size is the sum of the inputs. Merging overwrites is not estimated.
  Purgeable tombstones come from a per-sstable `purgeable_tombstones` seed.
- STCS buckets: sstables under 50MiB form one bucket; larger ones join a bucket within 0.5x-1.5x of
  the first larger sstable. Hotness ordering is not modeled.
- LCS: an over-target level compacts its first sstable with all of the next level, and L0
  candidates are taken to overlap. TWCS windows come from a seeded `window` number, and the newest
  window counts as "now". UCS density levels are approximated by size (<100, <400, <1600 MiB).
- Cleanup needs per-sstable `unowned_mb` instead of computing range intersection.
- `compacting_cf_count` and the executor's active-task count are seeded state. They are not
  maintained per table.
- `stop_requested_types` on `active-compactions` is a scenario lever. It stands for a
  stopCompaction(type) that arrives while the task runs.
- The schema version written into saved caches is a constant in `auto-saving-cache` state, standing
  in for Schema.instance.getVersion().

## 6. Docs / common knowledge vs the code

- A replica that hits tombstone_failure_threshold does not just time out. READ_REQ carries
  CALL_BACK_ON_FAILURE (db/ReadCommand.java:836), so InboundSink sends a failure response with
  READ_TOO_MANY_TOMBSTONES (net/InboundSink.java:81-91), and the coordinator can fail fast with
  ReadFailure.
- Only TombstoneOverwhelmingException and IncompatibleSchemaException get their own failure reasons
  on a replica (exceptions/RequestFailureReason.java:82-91). An IndexNotAvailableException or a
  bootstrap refusal arrives as UNKNOWN. INDEX_NOT_AVAILABLE is raised only on the coordinator, by
  IndexStatusManager, and as a ReadFailure rather than Unavailable.
- Purgeable tombstones (past gc_grace and shadowing nothing) are dropped before counting, so they
  never trip the tombstone thresholds (db/ReadCommand.java:460, 865-887).
- Local system keyspaces (system, system_schema and the virtual ones) ignore the tombstone
  thresholds (db/ReadCommand.java:532).
- cassandra.yaml says read_thresholds_enabled is "scheduled to be set true in 4.2", but it is false in
  5.0.9.
- Reads for tokens a node doesn't own are logged and served by default
  (reject_out_of_token_range_requests false).
- Major compaction does not always produce one sstable: repaired and unrepaired data are compacted
  separately (CompactionManager.java:1025-1026).
- LCS size-tiers L0 only when it has more than 32 sstables and a higher level is over its target, or
  when no normal L0 candidate exists (LeveledManifest.java:241-301). It does not always size-tier
  L0 when L0 falls behind.
- The default compaction strategy in 5.0.9 is still STCS (default_compaction commented out), not UCS.
- A BackgroundCompactionCandidate resubmits only if it actually compacted
  (CompactionManager.java:382-383). submitBackground skips when the table is already compacting
  and the executor is saturated.

## 7. Simulator gaps

- **No map construction in CEL.** A list of cells can't be folded into a column map: there is no
  `toMap`, and `set` paths are static. Partitions therefore carry a `cells` list. Example:
  `query-memtable-and-disk` builds `vars.merged` as a list of winning cells per column.
- **No sum or fold.** Totals such as sstable sizes and tombstones need a `foreach` that accumulates
  into `vars`. Example: `compaction-task.execute` sums `size_mb` before the disk-space loop.
- **Mid-iteration aborts.** The real read checks its monitoring deadline per row
  (QueryCancellationChecker) and aborts mid-scan. The model checks once, after the local read.
  Example: `read-slow-disk-response-discarded` uses a 6000ms latency fault on
  `data-disk.sstable-read`.
- **Concurrent operations.** A stopCompaction issued while a compaction runs can't be expressed as
  two concurrent flows, so it is a seeded lever (`active-compactions.stop_requested_types`).
  Example: `compaction-stopped-mid-run`.
- **Async executor.** The background candidate is an `emit` delivered after the entry call, and
  later resubmissions chain as emits. Real compactions on 2 threads would overlap; the model runs
  them in sequence. Example: `stcs-compacts-four-small-sstables` runs the candidate twice in a row.
- **Store updates can't read the row.** `tracker.try-modify` can't append to the stored compacting
  list, so the caller passes the current list. That is race-free only because the simulator is
  sequential.
- **Scheduled tasks.** `entry.repeat` models a fixed delay but not the initial delay. Example: the
  first index-summary pass runs at t=0, while the code waits 60 minutes.
- **Token order.** Range results are in key order from the store, not token order. The model can't
  sort by a computed token.

## 8. Known gaps

- Repaired-data tracking (RepairedDataInfo digests, overread) is a flag only. The row filter for
  non-index (ALLOW FILTERING) reads, paging state, and per-row DataLimits are not applied.
- Not modeled: the counter and chunk caches, BTI reads, compression and CRC checks, the bloom filter
  false-positive path, and the names-filter timestamp-order shortcut (it gives the same result).
- Also not modeled: secondary index maintenance on writes (SecondaryIndexManager update
  transactions), index builds and rebuilds (nodetool rebuild_index), SAI on-disk structures and ANN
  top-k, and IndexStatusManager status propagation through gossip.
- Compaction operations not modeled: scrub, verify, upgradesstables, relocate, garbage collect,
  split, anticompaction (repair-streaming), view builds, pending-repair holders, upgrade tasks,
  disk boundaries, SSTableRewriter early open, the LCS starved-sstable logic, and droppable-tombstone
  estimation (seeded ratios instead).
- The TWCS expired-check frequency and UCS sharding are not modeled.
- CacheService (service/CacheService.java) has no owner row. The cache instances are modeled as
  tables of `auto-saving-cache`.
- Other areas' scenarios count `read-command.execute-locally` calls to tell local from remote reads
  (coordination: `range-read-quorum`, `read-one-closest-replica`). ReadCommandVerbHandler always runs
  executeLocally on the replica (db/ReadCommandVerbHandler.java:92-93), so those expectations need
  another signal. Ops' `cleanup-*` scenarios expect one pending-range check for two tables, but
  performCleanup checks once per table (CompactionManager.java:621-625).

## Reconciliation round

- **Owned stubs defined (decision 6, 20):** `auto-saving-cache.{clear, set-capacity}`;
  `column-family-store.{disable-auto-compaction, enable-auto-compaction,
  force-compaction-keys-ignoring-gc-grace, rebuild-secondary-index, set-compaction-thresholds}`;
  `compaction-manager.{force-compaction-for-token-range, get-pending-tasks, perform-garbage-collection,
  perform-scrub, perform-sstable-rewrite, perform-verify, relocate-sstables, set-concurrent-compactors,
  set-concurrent-view-builders, set-rate-in-bytes, submit-view-builder}`;
  `secondary-index-manager.truncate-all-indexes-blocking`; `single-partition-read-command.execute-locally`.
  Shapes follow the callers' existing stubs (ops, repair-streaming, write-path). Error codes use
  the brief's convention (`runtime` for RuntimeException; ops' stub said `runtime-exception`).
  Helpers added: `compaction-manager.parallel-all-sstable-operation`,
  `column-family-store.validate-compaction-thresholds`, `secondary-index-manager.rebuild-indexes-blocking`.
- **ColumnFamilyStoreMBean compaction operations:** covered `forceMajorCompaction` (:53),
  `forceCompactionForTokenRange(s)` (:67, :75), `setMinimumCompactionThreshold` (:85),
  `setCompactionThresholds` (:95), `setMaximumCompactionThreshold` (:100),
  `setCompactionParametersJson` / `setCompactionParameters` (:109, :119), `compactionDiskSpaceCheck`
  (:317) and `setNeverPurgeTombstones` (:319). Each has a flow and scenarios.
  Skipped the 17 compaction getters: `getMinimumCompactionThreshold`, `getMaximumCompactionThreshold`,
  `getCompactionParametersJson`, `getCompactionParameters`, `isAutoCompactionDisabled`,
  `getUnleveledSSTables`, `getSSTableCountPerLevel`, `getPerLevelSizeBytes`, `isLeveledCompaction`,
  `getSSTableCountPerTWCSBucket`, `getLevelFanoutSize`, `getDroppableTombstoneRatio`,
  `isCompactionDiskSpaceCheckEnabled`, `getNeverPurgeTombstones`, `hasMisplacedSSTables`,
  `getMaxSSTableSize` and `getMaxSSTableDuration`. Reason: getters of compaction state, with no
  behavior. The other ColumnFamilyStoreMBean entries (compression, sampling, top partitions,
  getSSTablesForKey, flush, load and import) are not read-path's.
- **Tombstones on the local read path:**
  - A partition deletion (data-disk) hides older cells.
  - A cell tombstone, meaning a memtable cell with `deleted: true` or a null value (CQL writes
    null as a tombstone), hides the older value of that column and counts toward
    `tombstones_scanned`.
  - The warn threshold (1000) and failure threshold (100000) apply to the combined count, after
    purgeable tombstones are removed.
  - New scenarios: `read-cell-tombstone-shadows-older-value` and
    `read-memtable-tombstones-count-toward-warning`.
  - Gap waiting on write-path and cql: write-path's cells table carries no deletions yet, so a CQL
    DELETE never reaches the read as a tombstone unless it writes null-valued or `deleted` cells.
- **Compaction and tombstones:** `never_purge_tombstones` (setNeverPurgeTombstones) keeps every
  tombstone. `force-compaction-keys-ignoring-gc-grace` purges all of the keys' tombstones
  (CompactionIterator.java:386-390). `disk_space_check_enabled: false` skips the disk check for
  COMPACTION (CompactionTask.java:386-390).
- **Membership alignment:** `storage-service.is-bootstrap-mode` now returns `{bootstrap_mode}`.
  Scenarios seed membership's state (`storage-service.is_bootstrap_mode`, `survey_mode`,
  `token-metadata.pending_ranges`) instead of stub tables. Standalone,
  `read-while-bootstrapping`, `cleanup-aborted-pending-ranges` and `user-defined-cleanup-not-joined`
  fail by design, because they need membership's real definitions. All three pass merged.
- Skips file: `skips/read-path.json`, 47 entries after the migration round (getResizeIntervalInMinutes is now covered).

## Migration round (instances, configs, fixtures)

**Converted.**
- The `to` field is gone from `read-command-verb-handler.do-verb`. The handler runs on the
  instance it is called `on`, and `self` is the replica. Every endpoint (`10.0.0.x`) and
  `replica` key prefix was re-keyed. Tracker views, key and row caches, index status and
  non-queryable indexes are now per-instance state, keyed `ks.table[:pk[:sstable]]`.
- 24 configs were added. `read-request-timeout-ms` and `range-request-timeout-ms` are boundary
  references owned by coordination. Behaviors read `config[...]` for the timeouts, tombstone
  thresholds, read-size thresholds, row cache size, save periods, concurrent_compactors,
  snapshot_before_compaction, the SAI guardrail, out-of-range logging and rejection, and read-meter
  persistence.
- 23 flows are tagged `writes`. Each one has a multi-step scenario that reads its effect back
  (`tracker.get-view`, a replica read, `cache-load`, `active-compactions.get-compactions` or
  `index-summary-manager.get-resize-interval-in-minutes`).
- Scenarios use the `one-node` fixture (local compaction and caches) or `three-node-rf3` (reads on
  n2, index filtering).
- `compaction-task` has `capacity: {concurrency: 2}` (concurrent_compactors). Periodic flows use
  `initial_delay_ms`: 60 min for index summaries, 4 h for cache saves, 1 min for the read meter.
- `auto-saving-cache` is tagged incidental.
- Read-path has no replica fan-out, so no `foreach` became `parallel`. Coordination owns the
  fan-out.

**Data model change (judge W5).**
- SSTables now hold their partitions inside the Tracker View entry:
  `partitions: {pk: {cells, deletion_ts, tombstones, purgeable_tombstones, size_bytes, token}}`,
  plus `max_timestamp`, `read_rate` and `pending_repair`.
- `data-disk.sstable-read` is now a plain IO stub; fault injection still targets it. The
  data-disk `sstables` store and `sstable-scan` are removed.
- Reads go sstable by sstable: newest max timestamp first, bloom filter skip per sstable, and a
  stop at sstables older than a partition deletion already seen (SinglePartitionReadCommand.java:744-767).
- Compaction merges the input partitions through `cells.reconcile`. `tracker.add-sstables`
  (Tracker.java:252-270) lets write-path's flush make a new sstable live; write-path still has to
  call it and `compaction-manager.submit-background` (judge C1).

**Judged errors fixed.**
- W1/R2: replicas keep tombstones. `query-memtable-and-disk`, the range scan and `create-response`
  return tombstone cells (`deleted: true`, value null) and the partition `deletion_ts`, and the
  digest covers them (ReadCommand.java:426, ReadResponse.java:46-74).
  - Coordination still has to filter tombstones after its merge (DataResolver.java:315-317) and use
    the Cells.reconcile tie-break in data-resolver.
- W2/R7: new `cells.reconcile` (Cells.java:80-128). The higher timestamp wins; on a tie a tombstone
  wins, then the greater value; a partition deletion hides cells at or below it.
- W3/R6: a tombstone warning calls `client-warn.warn` when TRACK_WARNINGS is off
  (ReadCommand.java:635-638). It reaches a client only on the coordinator's own read, where
  transport's ClientWarn is capturing.
- C1: STCS runs the real getBuckets: sorted by size, running average, within 0.5-1.5x or all
  under 50MiB (SizeTieredCompactionStrategy.java:248-290). It trims each bucket to the
  max_threshold hottest sstables and picks the hottest bucket (:116-152).
  - On equal hotness the comparator prefers the larger average size, because `Collections.max`
    takes the greater (:45-56), although the code comment says "smallest first". The code wins.
- P2:
  - `compaction-manager.submit-pending-anti-compaction` (CompactionManager.java:817-880) marks
    sstables `pending_repair`.
  - `compaction-strategy-manager.get-next-background-task` first asks
    `pending-repair-manager.get-next-repair-finished-task` (PendingRepairManager.java:355-365).
  - When the session is FINALIZED, RepairFinishedCompactionTask promotes the sstables to repaired;
    FAILED or unknown demotes them to unrepaired (:498-540; LocalSessions.java:1147-1160).
  - Repair-streaming's anticompaction should call `submit-pending-anti-compaction`. LocalSessions
    is keyed by session id here.

**Simulator gaps.**
- Resolved:
  - map construction and folds: `merge`, `sum`, `transformList` and `lists.range` now carry the
    STCS buckets, the compaction partition merge and the tombstone sums;
  - initial delays of periodic tasks;
  - executor concurrency (capacity on compaction-task);
  - per-sstable reads (W5).
- Still open:
  - mid-iteration read aborts (the deadline is checked after the read);
  - a stopCompaction that arrives while a task runs still needs the `stop_requested_types` lever;
  - store updates can't read the row, so callers pass the compacting list;
  - range results are not in token order;
  - gc_grace purgeability is seeded (`purgeable_tombstones`), not computed from cell deletion
    times against `now`.

## Fix round (C1: gc_grace evaluated)

`compaction-task.execute` now decides purgeability per tombstone instead of summing a
precomputed `purgeable_tombstones` count (judge v2 wrong claim 2):

- `gcBefore = now / 1000 - gc_grace_seconds` (`ColumnFamilyStore.java:1970-1973`). `gc_grace_seconds`
  is a table parameter kept on the tracker view beside the compaction params; absent, it is the
  `TableParams` default 864000 (`TableParams.java:360`).
- A tombstone (cell or partition deletion) is dropped from the merged partition when
  `localDeletionTime < gcBefore` (or `ignore_gc_grace`), its timestamp is below the minimum timestamp of
  every sstable outside the compaction and every memtable that holds the key, and
  `never_purge_tombstones` is off (`PurgeFunction.java:36-45`, `CompactionController.java:245-284`).
  The memtable check calls `skip-list-memtable.cells-query`.
- Abstraction: a tombstone's localDeletionTime is its write timestamp (us) / 10^6, since the model
  stores no separate local deletion time. Sstables without `partitions` data keep their summary
  counters; for sstables with data, `tombstones` and `tombstones_purged` come from the data.
- New scenarios: `compaction-purges-tombstone-past-gc-grace`, `compaction-keeps-tombstone-shadowing-overlap`,
  `compaction-keeps-tombstone-memtable-overlap`, `compaction-gc-grace-table-param`,
  `compaction-never-purge-tombstones`. `background-compaction-then-read` now seeds a tombstone written
  100 s before the clock (inside gc_grace) and data-consistent counters.
- Judge: `bench-c1-probe-gc-grace-not-evaluated` now fails as intended (it pinned the wrong claim).
  The other C1 cases pass.
- Open: `ALTER TABLE ... WITH gc_grace_seconds` (cql/schema-auth) doesn't reach the tracker view, so
  only scenario state sets a non-default value. Read-time purging (`withoutPurgeableTombstones` on the
  read path) still uses the counters.

### Breaking changes

None. The `compaction-task.execute` request and response are unchanged, and every scenario of every
area passes against the merged model.

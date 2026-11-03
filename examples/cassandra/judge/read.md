# Judge report: read path (R1–R7)

Model: `examples/cassandra/cassandra.json` (merged: 502 components, 1,365 interfaces, 1,165 scenarios).
Code: cassandra-5.0.9. Paths are relative to `src/java/org/apache/cassandra/` unless noted.
Scenarios: `judge/scenarios/R1.yaml` … `R7.yaml`, 15 scenarios. 11 pass. 4 fail on purpose: they
state what the code does and the model doesn't (`bench-r2-tombstone-wins`, `bench-r4-slow-not-hung`,
`bench-r6-warn`, `bench-r7-equal-timestamp-tiebreak`). Every run was traced event by event to confirm
the path, not only the result.

## 1. Cases

| ID | Verified expectation (corrected?) | Score | Root cause | Evidence |
|---|---|---|---|---|
| R1 | Confirmed. QUORUM, RF 3, all up: `SpeculatingReadExecutor` (table default `99p`, TableParams.java:366). Contacts are blockFor = 2 replicas, and `initialDataRequestCount` is 1 because readQuorum is not below the contact count (AbstractReadExecutor.java:302). So one data request goes to the first replica in ring order (SimpleSnitch keeps ring order, SimpleSnitch.java:41-45), a digest request goes to the other, the local read runs last (:161-166), and the data is returned when the digests match (:428-430). | **pass** | — | `bench-r1`: ring for token 100 is [.3, .1, .2]. Data comes from 10.0.0.3 (`read-command-verb-handler.do-verb`) and the digest from the local `storage-proxy-local-read-runnable.run`. `read-callback.await-results` gets received 2. `digest-resolver.responses-match` matches on computed digests (not a forced choice). No read repair. |
| R2 | Confirmed, with one detail. On a mismatch, `startRepair` re-sends full data reads to the contacts (AbstractReadRepair.java:148-151). `DataResolver` merges them (DataResolver.java:315-317), where the newest timestamp wins and a tombstone at the newer timestamp shadows older data. `BlockingPartitionRepair` sends each stale replica a mutation and waits for the acks before the response (BlockingReadRepair.java:83-107). The detail: each mutation is that replica's **diff**, not the whole merged partition (RowIteratorMergeListener.java:382-398). | **partial** | model, contract | `bench-r2` passes end to end, driven by data rather than choices: 10.0.0.3 holds Old@1000 and this node holds New@2000. The digests differ, New is returned, and the READ_REPAIR_REQ to 10.0.0.3 rewrites its memtable cell to New. **But:** (a) `bench-r2-tombstone-wins` fails. When the newer value is a tombstone, the model resurrects the deleted value: it returns `Ada@1000` and "repairs" 10.0.0.1 with it (wrong claim W1). (b) The repair write is applied only when the scenario seeds `keyspace.tables['shop.users']`. Without the seed, `keyspace.apply-internal` logs "unknown table" and drops the write, but the read still reports success. The builders' own `read-digest-mismatch-read-repair` passes in that state (contract C1). |
| R3 | Confirmed. `ReplicaPlans.forRead` filters live replicas, then `assureSufficientLiveReplicas` throws `UnavailableException` (0x1000) with required 2 and alive 1 (ReplicaPlans.java:186-194, 716-724) before any message is sent. | **pass** | — | `bench-r3`, full CQL path `query-processor.process` → `select-statement.execute` → `storage-proxy.read`. Failure-detector checks run for .2 and .3 (down) and .1 (alive), giving `unavailable` 4096 `{alive:1, required:2}`. Zero verb or local-read calls. |
| R4 | Confirmed. At ONE there is 1 contact and 3 candidates, so a speculating executor is used. `maybeTryAdditionalReplicas` waits until start + `sampleReadLatencyMicros` (initially read_request_timeout / 2 = 2500ms, ColumnFamilyStore.java:498; later the 99p of coordinator read latency, :594). If no data has arrived by then, it sends a **data** request to the first uncontacted full candidate (AbstractReadExecutor.java:305-349). The first data response satisfies blockFor 1. | **sim-gap** | simulator | `bench-r4` passes: with the chosen replica hung, the model speculates a data read to 10.0.0.1 and returns its rows. The response arrives at t≈5043ms, though, after the 5000ms read deadline, where the code answers at about 2500ms. `bench-r4-slow-not-hung` fails: a replica that answers after 3000ms (past the 2500ms threshold) never triggers speculation in the model, because `maybe-try-additional-replicas` runs only after the initial calls return and checks whether they responded, not when. Missing feature: concurrent in-flight calls with a "wait until T, or until k of n responses" primitive. |
| R5 | **Corrected.** With the deployed 99p policy and all 3 nodes up, one silent replica does **not** cause a timeout. Speculation goes to the third replica, and the read succeeds. `read-timeout` happens only when no spare replica is left (or with speculative_retry NONE). For example, with 10.0.0.2 down and the data replica silent, there are 2 live candidates, so contacts = candidates and `NeverSpeculatingReadExecutor` is used (AbstractReadExecutor.java:209-213). `ReadCallback.awaitResults` then throws `ReadTimeoutException(QUORUM, received 1, blockFor 2, dataPresent false)` at start + 5000ms (ReadCallback.java:127-178; conf/cassandra.yaml:1322). | **pass** | benchmark | `bench-r5`: read-timeout 4608 `{received:1, block_for:2, data_present:false}`, executor `never_insufficient`, duration 5000–5100ms. `bench-r5-cql` shows the same through CQL. `bench-r5-all-up-speculates` shows the original premise: the model speculates and succeeds, as the code does (timing distorted as in R4). |
| R6 | Confirmed, with one detail. Counting is strict: more than 1000 warns and more than 100000 throws (ReadCommand.java:588-603, 622-645), after purgeable tombstones are dropped (:460). `TombstoneOverwhelmingException` on a remote replica becomes a READ_TOO_MANY_TOMBSTONES failure response (CALL_BACK_ON_FAILURE at ReadCommand.java:836; InboundSink.java:81-91; RequestFailureReason.java:82-91). On the coordinator it is `onFailure` (StorageProxy.java:2243-2248). Since blockFor + failures > contacts (ReadCallback.java:241-250), the callback signals at once, so the client gets `ReadFailureException` (0x1300) without speculation. The detail: the warning is logged on each replica, but it reaches the **client** only through `ClientWarn.warn` on the coordinator's own local read (ReadCommand.java:631, executor locals carry ClientWarn), because read_thresholds_enabled is false (Config.java:526). | **partial** | model | `bench-r6-fail` passes on the CQL path: both contacted replicas fail, and the client gets read-failure 4864 with `failure_reasons` READ_TOO_MANY_TOMBSTONES, `received` 0 and no speculation. `bench-r6-warn` gets the server-side part right (`tombstone_warnings` 2, success). It fails on the client warning: `client-warn.warn` is never called from the read path, so the result carries no warning (W3). |
| R7 | Confirmed. `queryMemtableAndDiskInternal` reads every memtable, then the sstables in descending max-timestamp order. It skips non-intersecting sstables and stops at sstables older than a partition tombstone it has seen (SinglePartitionReadCommand.java:701-806). BIG sstables are ruled out by key range and bloom filter (BigTableReader.java:255-263). The iterators merge with `Cells.reconcile` (Cells.java:80-128): the higher timestamp wins; on a tie a tombstone wins, then the greater value; a partition deletion hides cells with ts ≤ markedForDeleteAt. Single-row SELECTs on tables without clustering columns take the names-filter `queryMemtableAndSSTablesInTimestampOrder` path (:701-706), which gives the same result. | **partial** | model | `bench-r7` passes: memtable New@3000 beats sstable Old@2000, a memtable tombstone@2500 hides the sstable email@2000 and counts 1 tombstone, and city@2000 survives. `bench-r7-partition-deletion` passes (equal timestamp deleted) and so does `bench-r7-bloom-skip`. Incomplete path: the model collapses all sstables into one `data-disk.sstables` row per partition with one timestamp, so it can't express per-sstable bloom rejection, max-timestamp ordering and early stop, or two sstables that disagree. The timestamp-order path isn't modeled. `bench-r7-equal-timestamp-tiebreak` fails: on equal timestamps the model keeps the memtable value 'Aaa' where the code picks 'Zed' (W2). |

## 2. Wrong claims in the model

- **W1: tombstones are stripped before the replica's response, so a newer deletion loses to older
  data across replicas (resurrection).**
  - The model's version: `single-partition-read-command.query-memtable-and-disk` returns only live
    cells (`vars.live`), and `read-command.create-response` builds the data response from them.
    `data-resolver.resolve` and `row-iterator-merge-listener.close` then merge only live cells.
  - What the code does: `executeLocally` returns an `UnfilteredPartitionIterator`
    (ReadCommand.java:426) that is serialized unfiltered into the response
    (ReadCommandVerbHandler.java:92-95, ReadResponse.java:46-74). The coordinator merges the
    unfiltered data and filters only afterwards (DataResolver.java:315-317). That way a tombstone
    shadows other replicas' older cells, and read repair propagates the tombstone.
  - Effect: in `bench-r2-tombstone-wins`, the model returns the deleted `Ada@1000` and sends it as a
    "repair" to the replica that holds the tombstone.
- **W2: the read merge breaks timestamp ties by source order, not by `Cells.reconcile`.**
  - The model's version: query-memtable-and-disk's `vars.merged` takes the first cell with the
    maximum timestamp, which is always the memtable cell. data-resolver's `sortBy(timestamp)[last]`
    breaks ties arbitrarily.
  - What the code does: Cells.java:80-128 prefers the tombstone, then the greater value. The
    write-path memtable put (`skip-list-memtable.put`) does implement this rule, so the two merges
    disagree.
- **W3: the tombstone warning never reaches the client.** `read-command.execute-locally` logs and
  counts it (ReadCommand.java:622-645 cited), but it omits `ClientWarn.instance.warn(msg)` (:631).
  With TRACK_WARNINGS off, that call is how the coordinator's local read surfaces the warning in
  the client response.
- **W4 (minor): the read-repair mutation is the full merged partition.**
  `row-iterator-merge-listener.close` sends `vars.e.partition.cells`. The code sends each replica
  only its diff (`repairs[i].build()`), and `fullDiffRepair` only to write-plan contacts that
  weren't read (RowIteratorMergeListener.java:382-398). The result is the same after
  reconciliation, but the mutation size and the commit-log bytes are overstated.
- **W5 (minor, path): sstables are one aggregate row per partition.** See R7. `sstable_count` is
  only a counter.

I found no wrong citations. The random sample (seed 731, 10 citations across all areas) all matched
the code. I also read 14 read-flow citations against the code, and each says what the code says:

- AbstractReadExecutor.java:161-166, 234-252, 313-349, 432-443
- ReadCallback.java:176-178
- ReadCommand.java:588-603, 622-645 (apart from the ClientWarn omission in W3), 865-887
- ReplicaPlans.java:186-194
- StorageProxy.java:1861-1868, 2243-2254
- BigTableReader.java:255-263
- SinglePartitionReadCommand.java:907-930
- RowIteratorMergeListener.java:382-398 (the claim is right; the mutation content is wrong, W4)

## 3. Builder findings (notes "docs/common knowledge vs code")

| Finding | Verdict | Evidence |
|---|---|---|
| A tombstone-overwhelmed replica sends a failure response (CALL_BACK_ON_FAILURE), not a timeout | confirmed | ReadCommand.java:836; InboundSink.java:81-91 |
| Only TombstoneOverwhelming and IncompatibleSchema have their own failure reasons; everything else is UNKNOWN | confirmed | RequestFailureReason.java:82-91 |
| Purgeable tombstones are dropped before counting | confirmed | ReadCommand.java:460 (`withoutPurgeableTombstones` before `withMetricsRecording`) |
| Local system keyspaces ignore the tombstone thresholds | confirmed | ReadCommand.java:532 |
| read_thresholds_enabled is false in 5.0.9 | confirmed | Config.java:526 |
| Out-of-range reads are logged and served by default | confirmed | Config.java:792-793 |
| SimpleSnitch doesn't prefer the local node | confirmed | SimpleSnitch.java:41-45 |
| `speculative_retry = ALWAYS` at QUORUM, RF 3, doesn't speculate | confirmed | ReplicaPlans.java:724 adds blockFor + 1 contacts, which is every candidate, so AbstractReadExecutor.java:209-213 picks NeverSpeculating first |
| A replica failure decides a read before speculation | confirmed | ReadCallback.java:247-248 signals when blockFor + failures > **contacts**; then `awaitUntil` returns true, so there is no speculation (:252) |
| Read-repair writes wait until the read deadline | confirmed | BlockingReadRepair.java:88-107 (`getReadRpcTimeout`) |
| Initial speculation threshold is 2500ms | confirmed | ColumnFamilyStore.java:498 |

## 4. Simulator gaps

- **No concurrent in-flight calls or "wait until T, or until k of n".** Exposed by R4
  (`bench-r4-slow-not-hung`) and R5 (`bench-r5-all-up-speculates`).
  - A slow replica that still answers can't trigger speculation.
  - A hung replica triggers speculation only after its full 5000ms timeout, and the sim then
    succeeds after the read deadline has passed.
  - What would fix it: a parallel fan-out step with a deadline that collects whatever has arrived,
    or a per-call "soft timeout" that keeps the late response.
- **No deadline accounting across sequential calls.** Exposed by R4 and R5. `await-results` never
  compares `now` with start + read_request_timeout, so the sim accepts a response at 5043ms.
  Mosaic could expose a request-scoped deadline (`ctx` deadline plus a `now` check helper), or the
  model could add the check.
- **No map construction or fold in CEL.** Exposed by R7 and W4, and already noted by the builders.
  Partitions stay lists of cells, which makes per-replica diffs and multi-sstable merges awkward.
  A `transformMap` or fold would let the model compute diff mutations and per-sstable merges.

## 5. Contract seams

- **C1: keyspace naming.** Coordination and read-path use keyspace `shop`, but write-path's
  `keyspace` component only knows `ks1.*` and `system.batches` (`keyspace.state.initial.tables`).
  Every read-repair write in the builders' coordinator-read scenarios is silently dropped as an
  unknown table, while the read still reports the repair as acked. Fix: seed `shop.users` (and
  `shop.orders`) in `keyspace.state.initial.tables`, or derive the tables from schema-auth's schema.

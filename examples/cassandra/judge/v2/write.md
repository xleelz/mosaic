# Judge report, round 2: write group (W1–W10)

Judged against Cassandra 5.0.9 (`/home/lbethay/.cache/cassandra-bench/cassandra-5.0.9`) and the
deployed `conf/cassandra.yaml`, using the migrated, merged `examples/cassandra/cassandra.json`
(1,571 scenarios, all passing). Scenarios: `judge/v2/scenarios/W*.yaml`, all on the shared fixtures
(`three-node-rf3`, `four-node-rf3`, `one-node`), no mocks, no state beyond gossip liveness, commit log
segment files and the commit log sync time. Run:

```sh
PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly go run ./internal/devtools/check -q \
  -f examples/cassandra/cassandra.json $(for f in examples/cassandra/judge/v2/scenarios/W*.yaml; do echo -f $f; done) \
  --scenario '^bench' --trace
```

Result: 11 of 12 pass. `bench-w9-readback` **fails on purpose**: it asserts the code's behavior after a
flush and documents wrong claim 1.

Config used (all re-read): `hinted_handoff_enabled: true` (yaml:68), `max_hint_window: 3h` (yaml:80),
`commitlog_sync: periodic`, `commitlog_sync_period: 10000ms` (yaml:634-636),
`periodic_commitlog_sync_lag_block` commented out (yaml:641), so 1.5 × period = 15000ms
(DatabaseDescriptor.java:3423-3429), `write_request_timeout: 2000ms` (yaml:1330). The model's config
entities carry the same values (`write-request-timeout-ms` 2000, `max-hint-window-ms` 10800000,
`periodic-commitlog-sync-lag-block-ms` 15000, `commitlog-sync` periodic), and the scenarios assert them.

## 1. Cases

Every round 1 expectation was re-checked against the code; none of round 1's corrections is wrong.

| ID | Verified expectation (corrected?) | Score | Root cause | Evidence |
|---|---|---|---|---|
| W1 | Success. n1 is a replica, so it applies locally (`insertLocal`) and sends MUTATION_REQ to n2 and n3; `get()` returns after blockFor = 2 acks. Not corrected. SP:1503-1576 (1509-1515 local, 1566-1576 sends), SP:1371-1393, AWRH:112-137. | **pass** | – | `bench-w1` (flow `cql-write`, full CQL path → `mutate-with-triggers` → `mutate` → `perform-write`): do-verb@n2 1, @n3 1, @n1 0, perform-locally@n1 1, block_for 2, SIMPLE, no hint. Trace: `parallel 3 branches, need 2`, join at the 2nd success (72ms) while the local apply finished at 64ms. Each replica runs commit-log.add then the memtable write for `shop.users` (round 1's wrong claim 1 is fixed). |
| W2 | Success with 2 acks; the down replica is marked expired, `shouldHint` passes (downtime < 3h, host id in ring) and one hint is submitted before the sends. Not corrected. SP:1549-1564, 2442-2501. | **pass** | – | `bench-w2` (n3 down): do-verb only @n2, perform-locally@n1, should-hint → `should_hint: true`, one submit-hint → hint-runnable, `ctx.hinted == ['n3']`, and the submit-hint call precedes the first do-verb (SP:1563 before 1566). |
| W3 | `unavailable` (0x1000, required 2, alive 1) from `ReplicaPlans.forWrite` → `assureSufficientLiveReplicas` (ReplicaPlans:186-194, 475) inside `performWrite` before `sendToHintedReplicas`; no hints. Not corrected. | **pass** | – | `bench-w3`: assure-sufficient-live-replicas 1; send-to-hinted-replicas, do-verb, perform-locally, should-hint, submit-hint all 0. |
| W4 | `write-timeout` (0x1100), received 1 of blockFor 2, SIMPLE, at write_request_timeout 2000ms from the request start (AWRH:112-127, 140-150, 152-159). Both non-responders are hinted when their callbacks expire: RequestCallbacks.onExpired → onFailure(TIMEOUT) (RequestCallbacks.java:149-157) → hintOnFailure (AWRH:309-310). Not corrected beyond round 1's clarification. | **pass** | – | `bench-w4` (timeout fault on every do-verb): write-timeout 4352, received 1, block_for 2, SIMPLE, `2000 <= duration_ms < 2200`, local apply on n1, two submit-hint calls for n2 and n3, both at t ≥ 2000. |
| W5 | Success at ONE on the first ack (the local apply); n3's callback expires at 2000ms and it is hinted after the client already has its answer (AWRH:309-310). Not corrected. | **pass** | – | `bench-w5` (timeout fault on do-verb@n3): `query-processor.process` ends before 200ms, block_for 1; the only submit-hint (targets [n3]) starts at t ≥ 2000, i.e. a late branch after the join. |
| W6 | Success at ANY: `assureSufficientLiveReplicas` skips ANY (ReplicaPlans:140-142); every down replica goes into **one** HintRunnable (SP:1563-1564), whose `onResponse(null)` is the ack for blockFor 1 (SP:2810-2815). **Corrected in round 1, confirmed:** with 3 nodes and RF 3 the coordinator is always a live replica (FailureDetector.java:299-302), so "all replicas down" needs n1 outside the replica set (four-node ring, token −100 → n2, n4, n3). | **pass** | – | `bench-w6` (`four-node-rf3`, n2–n4 down): acks 1, block_for 1, do-verb 0, perform-locally 0, **one** submit-hint with 3 targets, one hint-runnable run (round 1's wrong claim 3 is fixed). |
| W7 | `unavailable` (required 3, alive 2) before anything is sent (ReplicaPlans:186-194; blockForWrite ALL = RF). Not corrected. | **pass** | – | `bench-w7` (`cql-write`, ALL, n2 down): unavailable 4096, required 3, alive 2, nothing sent or hinted. |
| W8 | The replica appends to the commit log in `beginWrite` (CassandraKeyspaceWriteHandler.java:42-56), then writes the memtable (Keyspace.java:625, 653), then replies MUTATION_RSP from the applyFuture callback (MutationVerbHandler.java:72-76). Under periodic sync it waits for no fsync **unless the last sync is more than 15000ms old** (PeriodicCommitLogService.java:36-45; CommitLog.java:336 → finishWriteFor). Clarified in round 1, confirmed. | **pass** | – | `bench-w8` (last sync 5s ago): commit-log.add@n2 before cassandra-table-write-handler.write@n2, `maybe-wait-for-sync` returns `waited: false`, segment-sync 0, one entry in n2's segment file, MUTATION_RSP from n2. `bench-w8-lag` (last sync 20s ago): await-sync-at@n2 1 and a segment sync, before the memtable write. |
| W9 | A flush switches the memtable, writes the memtable's partitions to an sstable through the per-disk FlushRunnables (CFS:1298-1316), makes it live (CFS:1352-1379, 1836-1837), reclaims the old memtable (CFS:1391-1404), then PostFlush calls `discardCompletedSegments` (CFS:1149-1153). That marks the table clean up to the segment containing the upper bound and deletes only segments that became unused (CommitLog.java:353-383). Clarified in round 1, confirmed. | **partial** | model | `bench-w9` passes: switch-out, one flush runnable, a `data-disk.sstable-write` for users, live_sstables 1, then discard-completed-segments; the users-only old segment file is deleted, the mixed users/orders segment is kept with orders still dirty, and the allocating segment is kept. **But** the sstable carries no data and the memtable keeps it (wrong claim 1, `bench-w9-readback` fails), and the counter path deletes a segment the file path kept (wrong claim 2). |
| W10 | `CassandraDaemon.setup` calls `recoverSegmentsOnDisk` (CassandraDaemon.java:345) before `initServer` (:383) and long before `start()` starts the native transport (:643-669). Replay skips entries at or below each table's persisted position (CommitLogReplayer.java:314, 497), applies the rest with `Keyspace.apply(m, false, true, false)` (:326, no commit log), then `blockForWrites` flushes (:244-270), and the files are deleted (CommitLog.java:182-218). Not corrected. | **pass** | – | `bench-w10` (flow `daemon-startup`, the real startup path, segment file seeded with one persisted and two unflushed entries): keyspace.apply 2 (never user:42), commit-log.add 0, bob in the memtable, keyspace.flush, the file deleted; recover-segments-on-disk ends before init-server starts and before native-transport-service.start (8261ms). |

Totals: 9 pass, 1 partial, 0 fail, 0 missing, 0 sim-gap.

### Change against round 1

Round 1: 7 pass, 1 partial (W10), 2 sim-gap (W4, W5). I scored the cases before reading round 1's scores.

| ID | Round 1 → round 2 | Why |
|---|---|---|
| W1 | pass → pass (better path) | The write fan-out is now a `parallel` join with `need = blockFor`, so the coordinator returns at the 2nd ack instead of collecting all 3. Round 1's wrong claim 1 (`shop.users` unknown, so no commit log or memtable write anywhere) is fixed by the shared `base-schema` fixture. |
| W2 | pass → pass | Unchanged. |
| W3 | pass → pass | Unchanged. |
| W4 | sim-gap → **pass** | DESIGN §11.2 `parallel` + the handler's deadline (`start_ms + write-request-timeout-ms`): WriteTimeout at 2000ms, not 4082ms. |
| W5 | sim-gap → **pass** | The join completes at the first ack; branches after it run on as `late` work, so the hint lands after 2000ms, after the client's answer. |
| W6 | pass → pass (better path) | One HintRunnable for all down replicas (round 1's wrong claim 3 fixed). |
| W7 | pass → pass | Unchanged. |
| W8 | pass → pass | Unchanged; I also exercised the 15000ms lag block, which round 1 only noted. |
| W9 | pass → **partial** | Regression in score, from deeper checking that §11.7 multi-step scenarios now allow (write → flush → read) and from the per-file segment model added in the migration, which now coexists with the older counter model. See wrong claims 1 and 2. |
| W10 | partial → **pass** | `commit-log.recover-segments-on-disk` now lists this node's segment files from state (`commit-log.segments_on_disk`), so the real `daemon-startup` path replays seeded segments. `cassandra-daemon.setup` still passes a vestigial `segments: []` that is ignored. |

## 2. Wrong claims found in the model

1. **A flush doesn't move the data into the sstable, and the memtable keeps it.**
   `skip-list-memtable.switch-out` zeroes the table's `stats` but leaves its `cells` and `partitions`;
   `flushing-flush-runnable.call` passes only a partition count to `data-disk.sstable-write`; and
   `column-family-store.add-to-tracker` publishes an sstable with no `partitions`. The code switches
   in a new, empty memtable (CFS:1183-1227), writes the old memtable's partitions into the sstable
   (CFS:1298-1316; Flushing.java:157-174) and reclaims the old memtable (CFS:1391-1404). Effect, in
   `bench-w9-readback` (write → flush → local read on `one-node`): after the flush
   `skip-list-memtable@n1.cells['shop.users:user:42:name']` is still there, the read serves the row from
   the memtable, and `big-table-reader.row-iterator` rules the flushed sstable out with `BLOOM_FILTER`. A
   read after a flush returns the right value by the wrong path. The same holds after replay's flush
   (W10). Also, a second write after a flush is counted from zero stats while the old cells stay.
2. **Two models of commit log segments disagree.** `commit-log.discard-completed-segments` correctly
   deletes only per-file entries that became all-persisted (`segments_on_disk`), then always calls
   `abstract-commit-log-segment-manager.archive-and-discard`, which decides from the
   `active_segments` counter (choice default `active_segments > 1 ? 'unused'`) and deletes an
   `oldest-segment` regardless of dirtiness. Probe: seed `active_segments: 3` with the only older
   segment still dirty for `shop.orders`; the flush keeps the file (segments-delete 0) yet calls
   `commitlog-disk.segment-delete` and sets `active_segments` to 1. The code deletes only segments where
   `isUnused()` (CommitLog.java:366-370). The model's own `wp-flush-dirty` scenario passes through the
   counter path.
3. Minor: `commit-log.discard-completed-segments` marks the table clean in every segment file and doesn't
   stop at the segment containing the flush's upper bound (CommitLog.java:379-381). This can't be
   observed while steps don't interleave, because no write lands between the switch and PostFlush.
4. Minor: `cassandra-daemon.setup` still passes `segments: []` to `commit-log.recover-segments-on-disk`,
   which ignores it. That's harmless, but it's the literal round 1 flagged.

Round 1's wrong claims: 1 (unknown `shop.users`) **fixed**; 2 (unknown-table check before `beginWrite`)
**fixed** (`keyspace.apply-internal` calls `begin-write` before the `known` check, Keyspace.java:625-634);
3 (one HintRunnable per replica) **fixed**; 4 (no `maybeWaitForArchiving` or second listing) **fixed**
(CommitLog.java:187-197); 5 (TableViews citation) not re-checked.

Spot-checked as faithful, with the cited code read alongside: `storage-proxy.mutate` (SP:880-950),
`perform-write` (SP:1371-1393, AWRH:152-159), `send-to-hinted-replicas` (SP:1503-1576, AWRH:293-311),
`replica-plans.for-write` and `assure-sufficient-live-replicas` (ReplicaPlans:135-196, 470-522),
`abstract-write-response-handler.get` (AWRH:112-150, including candidates = liveAndDown, :239-245),
`should-hint` (SP:2442-2501), `submit-hint` (SP:2776-2828), `failure-detector.is-alive` self rule
(FailureDetector.java:299-302), `keyspace.apply-internal`, `commit-log.add` (CommitLog.java:300-336),
`periodic-commit-log-service.maybe-wait-for-sync` (PeriodicCommitLogService.java:36-45),
`mutation-verb-handler.do-verb` (MutationVerbHandler.java:44-76), `column-family-store-post-flush.call`
(CFS:1123-1160), `cassandra-daemon.setup` ordering (CassandraDaemon.java:256, 345, 383),
`commit-log.recover-segments-on-disk` (CommitLog.java:182-218).

`--cite-sample 12 --seed 22`: all 12 accurate (AlterTableStatement:404-408, CassandraDaemon:278 and
:534-537, PaxosPrepare:389-405, SetConcurrentCompactors:27-38, StorageService:5217 and :4294-4306,
StreamSession:704-744, SnapshotManager:129-140 (its 5s/60s come from CassandraRelevantProperties:509-511),
ActiveRepairService:831-845, AlterRoleStatement:92-93, NativeTransportService:140-148). All 5,099
citations resolve.

## 3. Builder findings confirmed or refuted

write-path.md §6 and §10:
- Periodic sync blocks writes past 1.5 × period. **Confirmed** (PeriodicCommitLogService.java:36-45;
  DatabaseDescriptor.java:3423-3429), and now exercised by `bench-w8-lag`.
- An expired MUTATION_REQ is dropped silently. **Confirmed** (MutationVerbHandler.java:47-52).
- Out-of-range writes are only logged by default. **Confirmed** (Config.java:792-793).
- §10 "a flush marks the entries persisted and deletes files that become unused". **Confirmed for the
  file model**, but see wrong claim 2: the counter model still deletes independently.
- §10 "Replay lists this node's commit log directory, calls maybeWaitForArchiving and lists again".
  **Confirmed** (CommitLog.java:168-174, 187-197); `bench-w10` reaches it through `daemon-startup`.

coordination.md §6 and migration round (write-related):
- Hints also go to live replicas that time out or fail. **Confirmed** (AWRH:309-310;
  RequestCallbacks.java:149-157).
- QUORUM with one down and one failing gives WriteTimeout. **Confirmed**: candidates = liveAndDown = 3
  (AWRH:239-245), `expired()` doesn't count a failure (:219-222), so 2 + 1 > 3 never holds.
- "W4 now fails at 2000ms; W5 returns on the first ack and hints late; down replicas get one
  HintRunnable." **Confirmed** by `bench-w4`, `bench-w5` and `bench-w6`.

## 4. Simulator gaps

Resolved by DESIGN §11:
- **Parallel fan-out with a k-of-n join** (§11.2): closes round 1's gap 1. W1 returns at the 2nd ack;
  W4's timeouts no longer add up.
- **A shared request deadline** (§11.2 `timeout_ms`, §11.3 deadlines; the handler uses
  `start_ms + config`): W4 times out at 2000ms.
- **Work after the response** (§11.2 late branches): W5's hint lands after the client's answer, closing
  round 1's gap 2.
- **Per-instance state and fixtures** (§11.1, §11.7): the commit log, memtable and sync time are per node
  (W8 asserts n2's segment file); multi-step scenarios make write → flush → read checkable (W9).
- **Trace assertions** (§11.8): ordering claims (hint before send, append before memtable, replay before
  initServer and the native transport) are now asserted, not read off a trace by hand.

Still open:
- **Waiting on another thread runs inline.** In `bench-w8-lag` the writer's `await-sync-at` runs the sync
  thread's iteration inside the write's call tree. The code parks the writer until the
  PERIODIC-COMMIT-LOG-SYNCER thread syncs. A wait-for-signal primitive is needed (W8).
- **No interleaving of shared state between concurrent work** (§11.2 says so). The race between a flush's
  switch and concurrent writes, which is what bounds `discardCompletedSegments` at the upper bound, can't
  be shown (W9, minor claim 3).
- **Tooling:** `check` can't print a state value or a map (CEL `string(map)` has no overload), so finding
  wrong state shapes takes bisecting assertions. `has()` doesn't accept a bracketed map key
  (`calls_by_instance['x@n1']`), so absence needs `!('k' in m) || m['k'] == 0`.

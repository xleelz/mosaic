# Judge report: write group (W1–W10)

Judged against Cassandra 5.0.9 (`/home/lbethay/.cache/cassandra-bench/cassandra-5.0.9`) and the
deployed `conf/cassandra.yaml`, using the merged `examples/cassandra/cassandra.json`. Scenarios are in
`judge/scenarios/W*.yaml`, and all 12 pass (`go run ./internal/devtools/check -f cassandra.json -f <W>.yaml`).
`check -v` doesn't print the run, so I read the paths from traces. I ran a private `mosaicd` on a
throwaway port and data dir, imported the merged document plus the judge scenarios, and ran
`mosaic sim run --scenario bench-wN --format summary`.

Config used: `hinted_handoff_enabled: true` (yaml:68), `max_hint_window: 3h` (yaml:80),
`commitlog_sync: periodic` / `commitlog_sync_period: 10000ms` (yaml:634-636),
`write_request_timeout: 2000ms` (yaml:1330), `periodic_commitlog_sync_lag_block` unset, so 1.5 × period
(DatabaseDescriptor.java:3423-3429), `enforce_native_deadline_for_hints = false` (Config.java:1400),
and the default memtable is SkipListMemtable (yaml:783-790).

All coordinator scenarios use `keyspace: ks1, table: users` in the input. The flow's default `shop.users`
silently skips the local apply (see wrong claim 1).

## 1. Cases

| ID | Verified expectation (corrected?) | Score | Root cause | Evidence |
|---|---|---|---|---|
| W1 | Success. The coordinator (a replica) applies locally instead of messaging itself, and MUTATION_REQ goes to .2 and .3. `get()` returns once blockFor = 2 acks are in. Not corrected. StorageProxy.java:1503-1576, 1371-1393; AbstractWriteResponseHandler.java:112-137 | **pass** | – | `bench-w1`: perform-locally 1 (commit-log.add, then skip-list-memtable.put), do-verb 2, block_for 2, no hints. The sim reports acks = 3 because it collects every response before `get()` (see simulator gap 1). |
| W2 | Success with 2 acks. The down replica is marked expired, `shouldHint` passes (downtime < 3h, in ring), and a hint is submitted. Not corrected. SP:1549-1564, 2442-2501 | **pass** | – | `bench-w2`: do-verb 1, perform-locally 1, should-hint 1, submit-hint → hint-runnable → hints-service.write 1, ctx.hinted = [10.0.0.2]. |
| W3 | `unavailable` (0x1000, required 2, alive 1), thrown by `ReplicaPlans.forWrite` inside `performWrite` before `sendToHintedReplicas` runs. No hints. Not corrected. ReplicaPlans.java:138-196, 475; SP:1385 | **pass** | – | `bench-w3`: assure-sufficient-live-replicas 1, send-to-hinted-replicas 0, do-verb 0, commit-log.add 0, submit-hint 0. |
| W4 | `write-timeout` (0x1100), received 1 of blockFor 2, SIMPLE, at write_request_timeout (2000ms). Both non-responders are hinted when their callbacks expire (onFailure TIMEOUT → hintOnFailure). Clarified (the hint mechanism): RequestCallbacks.java:149-157; AWRH.java:112-148, 293-311 | **sim-gap** | simulator | Outcome and path reproduced (`bench-w4`: local apply, 2 timeouts, 2 hints, received 1, SIMPLE). But the client sees the error at **4082 ms**, not 2000 ms: the sequential `foreach` waits for each replica's `timeout_ms: 2000` in turn. |
| W5 | Success at ONE as soon as the first ack arrives (the local apply). The slow replica's callback expires at 2000ms and it is hinted, after the client already has its answer. Clarified (timing of the hint): AWRH.java:309-310 | **sim-gap** | simulator | Outcome, hint and path reproduced (`bench-w5`). But success arrives at **2095 ms**, because the sim waits out the faulted replica before `get()`. |
| W6 | Success at ANY: `assureSufficientLiveReplicas` skips ANY, every down replica is hinted in **one** HintRunnable, and that runnable's `onResponse(null)` is the ack for blockFor 1. **Corrected:** with 3 nodes and RF 3 the coordinator is always a replica and always alive to itself (FailureDetector.java:299-302), so "all replicas down" needs a coordinator that isn't a replica (4-node ring; token −100 → .2, .4, .3). Code: ReplicaPlans.java:140-142; SP:1563-1564, 2780-2817 | **pass** | benchmark | `bench-w6`: do-verb 0, perform-locally 0, acks 1, block_for 1, three replicas hinted. Minor path difference: the model makes 3 submit-hint / 3 HintRunnable / 3 HintsService.write calls where the code makes 1 (wrong claim 2). |
| W7 | `unavailable` (required 3, alive 2) before anything is sent. Not corrected. | **pass** | – | `bench-w7`: send-to-hinted-replicas 0, do-verb 0, commit-log.add 0, submit-hint 0. |
| W8 | The replica appends to the commit log in `beginWrite`, then writes the memtable, then replies MUTATION_RSP (from the applyFuture callback). Under periodic sync it doesn't wait for an fsync **unless the last sync is more than 15000ms old**. Clarified (lag block): CassandraKeyspaceWriteHandler.java:42-65; Keyspace.java:624-653; CommitLog.java:300-336; PeriodicCommitLogService.java:36-45; MutationVerbHandler.java:72-76 | **pass** | – | `bench-w8`: commit-log.add → segment-append → maybe-wait-for-sync (no wait, await-sync-at 0, segment-sync 0) → skip-list-memtable.put → MUTATION_RSP. `bench-w8-order`: a failed append gives fs-write-error with memtable put 0, so the append comes first. |
| W9 | A flush switches the memtable, writes an SSTable through the per-disk FlushRunnables, adds it to the live set, and PostFlush calls `discardCompletedSegments`. That marks the table clean in each segment up to the one containing the upper bound and deletes only the segments that became **unused**; segments still dirty for other tables are kept. Clarified: ColumnFamilyStore.java:1123-1160, 1175-1300; CommitLog.java:353-383 | **pass** | – | `bench-w9`: switch-memtable → flush-runnable → data-disk.sstable-write → live_sstables 1 → memtable discard (pool 0) → post-flush → discard-completed-segments → segment-delete. The model also has `wp-flush-segments-still-dirty` for the kept-dirty case. |
| W10 | `CassandraDaemon.setup` calls `recoverSegmentsOnDisk` (CassandraDaemon.java:345) before `initServer` (:383) and long before `start()` starts the native transport (:643-669). Replay skips entries at or below each table's persisted position (CommitLogReplayer.java:314, 497), applies the rest with `Keyspace.apply(m, false, true, false)`, so without the commit log (:326), then flushes (`blockForWrites`, :244-270) and deletes the files. Not corrected. | **partial** | model | `bench-w10` (flow `commitlog-replay-startup`): replayed 2, keyspace.apply 2, commit-log.add 0, the persisted entry skipped, memtable cells bob/carol present, flush and delete happen. `bench-w10-startup-order` (`daemon-startup`): replay comes before init-server and native-transport start, but `cassandra-daemon.setup` passes `segments: []` as a literal, so the real startup path always logs "No commitlog files found" (recover-files 0). **Edit needed:** have `cassandra-daemon.setup` take the on-disk segments from state, e.g. `segments: "= state.commitlog_segments_on_disk"` or a `commitlog-disk` store query, so a scenario can seed segments and watch them replay before serving. |

Totals: 7 pass, 1 partial, 2 sim-gap, 0 fail, 0 missing.

## 2. Wrong claims found in the model

1. **Contract seam (coordination ↔ write-path): the coordinator write path never reaches the
   commit log or memtable with its own data.** The `coordinator-write` flow and every `write-*`
   scenario write `shop.users`, but `keyspace.state.tables` knows only `ks1.*`. So `keyspace.apply-internal`
   takes "Update for a non-existent table is logged and skipped" on the coordinator **and** on both
   replicas: no commit-log.add, no memtable put. The scenarios pass anyway, because they only count
   do-verb and perform-locally calls. You can see this in a `bench-w1` run that uses the default input.
   Fix: align the keyspace names, or add `shop.*` to `keyspace` / `column-family-store` state.
2. **Unknown-table ordering.** `keyspace.apply-internal` checks for an unknown table before
   `beginWrite`, so it never appends to the commit log. In the code, `beginWrite` (and so the commit log
   append) runs first, and `cfs == null` is only checked per partition update inside the try block
   (Keyspace.java:624-634).
3. **Hints for down replicas: one HintRunnable per replica, not one for all.** In
   `storage-proxy.send-to-hinted-replicas`, the step titled "one HintRunnable for all of them" loops
   `submit-hint` once per target (and `submit-hint.targets` has `maxItems: 1`). The code calls
   `submitHint(mutation, EndpointsForToken.copyOf(..., endpointsToHint), responseHandler)` once
   (SP:1563-1564), which makes one `HintsService.write(hostIds, hint)` (SP:2810). The outcome is the
   same, including the single ANY ack, but call counts and hints-in-progress accounting differ.
4. `commit-log.recover-segments-on-disk` leaves out `archiver.maybeWaitForArchiving` per file
   (CommitLog.java:187-191) and the second listing of unmanaged files after restore (:196). Minor.
5. Imprecise citation: `table-views.push-view-replica-updates` ("read the existing base rows ... send
   through mutateMV") cites TableViews.java:189-200, which is `generateViewUpdates`.
   `pushViewReplicaUpdates` is at :143.

Spot-checked faithful, with no problems found: storage-proxy.mutate (SP:878-957),
mutate-with-triggers (SP:1116-1160), perform-write (SP:1371-1393), send-to-hinted-replicas apart from
claim 3 (SP:1475-1576), should-hint (SP:2423-2501), submit-hint (SP:2776-2828),
abstract-write-response-handler.get (AWRH:112-148, including the "all failures are timeouts →
WriteTimeout" rule), replica-plans.for-write (ReplicaPlans:447-540),
keyspace.apply-internal (apart from claim 2), cassandra-keyspace-write-handler.begin-write,
commit-log.add (CommitLog:300-336), periodic-commit-log-service.maybe-wait-for-sync,
mutation-verb-handler.do-verb (MutationVerbHandler:44-76), commit-log.discard-completed-segments
(CommitLog:353-383). I also checked the random `--cite-sample` runs (seeds 11 and 12, 12 citations
across areas): 11 accurate, 1 imprecise (claim 5).

## 3. Builder findings (notes §6) confirmed or refuted

write-path.md §6:
- `materialized_views_enabled: false` only gates creation; existing views are still maintained. **Confirmed**: `ViewManager.updatesAffectView` (ViewManager.java:73-93) and Keyspace.java:535 never read the flag.
- An expired MUTATION_REQ is silently dropped, and a WriteTimeoutException from the MV lock is swallowed with no reply. **Confirmed**: MutationVerbHandler.java:47-52 and :64-67, :72-76.
- Out-of-range writes are only logged by default. **Confirmed**: Config.java:793 is `false`; AbstractMutationVerbHandler.java:63-66.
- Periodic commit log blocks writes past 1.5 × period. **Confirmed**: PeriodicCommitLogService.java:36-45; DatabaseDescriptor.java:3423-3429.
- A replay CRC failure continues with the next entry. **Confirmed**: CommitLogReader.java:383-393 (`continue`, with termination only if the handler says so).
- COUNTER_MUTATION_REQ skips the expiry and size checks. **Confirmed**: CounterMutationVerbHandler overrides only `applyMutation`; `AbstractMutationVerbHandler.doVerb` (:42-45) has neither check.
- `cdc_total_space` defaults to 0MiB, then min(4096MiB, 1/8 of the volume). **Confirmed**: Config.java:419; DatabaseDescriptor.java:684-694.
- Truncate snapshot rule: not checked (outside W1–W10).

coordination.md §6 (the write-related ones):
- Hints are also written for live replicas that time out or fail. **Confirmed**: AWRH.java:309-310, and RequestCallbacks.java:156 for timeouts.
- QUORUM with one replica down and one failing gives WriteTimeout, not WriteFailure. **Confirmed**: candidateReplicaCount is liveAndDown = 3 (AWRH.java:239-245), so 2 + 1 > 3 is false, no early signal, and `get()` times out (:126-127).
- `forBatchlogWrite`, the counter leader and the read findings: outside this group, not checked.

## 4. Simulator gaps

1. **No parallel fan-out, and no shared deadline across a fan-out.** Exposed by **W4** (4082ms instead
   of 2000ms), **W5** (2095ms instead of returning on the first ack) and **W1** (acks 3 instead of
   returning at 2). A `foreach` runs its replica calls one after another, each with its own fixed
   `timeout_ms`, so timeouts add up, and the coordinator can't return once `blockFor` acks are in
   while slower replicas are still outstanding. Features needed: a parallel `foreach` that can join on
   "first N successes, or deadline", or at least a CEL `timeout_ms` (`"= deadline - now"`). Today
   `timeout_ms` is an `int64` literal (internal/model/model.go:285), so models can't express a shared
   request deadline.
2. **Work that happens after the response.** In W5 the hint is written when the callback expires,
   *after* the client got its success. The sim does it inside the entry call, before the reply. `emit`
   comes close but can't be delayed to a point in virtual time, such as `emit` with `delay_ms`.

Tooling note: JUDGE.md says `check -v` "prints the run", but it only lists warnings and stubs. Traces
need `mosaicd` + `mosaic sim run`, or a `--trace <scenario>` flag on `check`.

# Judge report: `lwt-batch` (L1–L5, B1–B5)

Code: cassandra-5.0.9 at `/home/lbethay/.cache/cassandra-bench/cassandra-5.0.9`. `SP` stands for
`src/java/org/apache/cassandra/service/StorageProxy.java`, `RP` for `locator/ReplicaPlans.java` and
`BS` for `cql3/statements/BatchStatement.java`, all under `src/java/org/apache/cassandra/`.

The deployed config this report relies on:
- `paxos_variant` is unset (`#paxos_variant: v1`, cassandra.yaml:1602), so it falls back to `v1` (Config.java:1051).
- `cas_contention_timeout: 1000ms` (yaml:1339). Config.java:157 defaults to 1800ms.
- `write_request_timeout: 2000ms` (yaml:1330).
- `batch_size_warn_threshold: 5KiB` and `batch_size_fail_threshold: 50KiB` (yaml:1840, 1844).
- `batchlog_replay_throttle: 1024KiB` (yaml:157), and `batchlog_endpoint_strategy` defaults to `random_remote` (Config.java:442).

Scenarios are in `judge/scenarios/L{1..5}.yaml` and `B{1..5}.yaml`, 14 in all, including the extra
variants `bench-l4-retry` and `bench-b4-*`. All 14 pass on the merged ontology with no warnings.
Every case is driven end to end from the CQL entry, except B3, which is the scheduled replay flow.
- LWT cases use `cql-conditional-write`, and L5 uses `cql-select` at SERIAL.
- Batch cases use `cql-batch`.

**The contract seam (applies to L1, L5, B1, B2, B3 and B5).** write-path's `keyspace` component
only knows `ks1.*` and `system.batches`. The CQL, Paxos and batch flows write to `shop.*`, so
`keyspace.apply-internal` logs "Update for a non-existent table" and skips the commit log and the
memtable. You can see it as `ctx.unknownTable == 'shop.users'` in an unmodified L1 run. The outcome
of each case is unchanged. To make the path real, my scenarios declare the `shop` tables in the
`keyspace` state. That is state only: no ontology edit. I scored the outcomes as pass and recorded
the cause as **contract**.

## 1. Cases

| ID | Verified expectation (corrected?) | Score | Root cause | Evidence |
|---|---|---|---|---|
| L1 | v1 (`Paxos.useV2()` is false, SP:325-328). `legacyCas` then `doPaxos`. One ballot. Prepare goes to all live contacts and needs a majority (RP:630-635). Then the precondition read at QUORUM (SP:351-356), the propose, and the commit at the commit CL, skipped only when the update is empty (SP:525-534). `[applied]` is true. Not corrected. | pass | contract (keyspace seam, worked around) | `bench-l1` reproduces this path. `next-ballot` is called once. There are 2 `prepare-verb-handler.do-verb` calls plus the local prepare, so 3 `legacy-prepare`. Then 1 `read-one` through the full read path, 3 `legacy-propose`, 3 `commit-direct`, 3 `keyspace.apply`, and `commitAcks` is 3. |
| L2 | **Corrected.** `[applied]` false with the current values of the condition columns (ModificationStatement.java:605-618). In v1, **an empty update is still proposed and accepted by a quorum**. Only the commit is skipped (SP:359-364, 525-534). The benchmark's "no proposal is accepted" is wrong for v1. | pass | benchmark | `bench-l2` seeds balance=100 on all 3 replicas and runs `IF balance = 50`. Result: `applied:false` with the cell balance=100. `make-updates` is never called. 3 `legacy-propose` leave `accepted_empty:true` at our ballot. `commit-paxos` and `keyspace.apply` are 0 and `committed_ballot` stays 0. The rows are raw cells without the `[applied]` column (minor; see section 2). |
| L3 | `forPaxos`: with 3 participants, 2 are required and 1 is live, so `UnavailableException(SERIAL, 2, 1)` is thrown at the start of the `doPaxos` loop, before any ballot or message (RP:627-635, SP:506). Not corrected. | pass | none | `bench-l3` returns `unavailable` 4096 with `{consistency: SERIAL, required: 2, alive: 1}`. `next-ballot`, prepare and read are all 0. |
| L4 | **Clarified.** A rejected prepare increments `contentions` and sleeps a *uniform random 0-99ms* (not exponential). The next ballot is above the highest in-progress ballot seen, and the loop runs until `cas_contention_timeout` (1000ms) from the request start. The result is `CasWriteTimeoutException(WriteType.CAS, SERIAL, received 0, blockFor 2, contentions)` (SP:603-615, 682 and 568). | partial | simulator | `bench-l4` returns `write-timeout` 4352 with `{write_type: CAS, consistency: SERIAL, received: 0, block_for: 2, contentions: 1}`, after the "sleep 0-100ms and retry" step, at t=1049ms. `bench-l4-retry` shows the re-prepare at `promised+1` succeeding. The model can't express sustained contention: there is no concurrent proposer, so the deadline is reached with a 950ms latency fault plus one seeded higher promise. |
| L5 | v1 `legacyReadWithPaxos`. `doPaxos` with an empty-update proposer, because v1 is linearizable (SP:1930-1933). `beginAndRepairPaxos` finishes the in-progress round (re-propose plus commit at QUORUM, SP:638-646), then prepares again. The empty proposal is accepted and never committed. Then `fetchRows` at QUORUM (SP:1956). Not corrected. | pass | contract (keyspace seam, worked around) | `bench-l5` (CQL SELECT, SERIAL) returns the replayed value `name=Grace`. 2 `prepare-paxos`, 2 `propose-paxos`, 1 `commit-paxos` (the replay), `unfinishedCommit` is true, our empty update is accepted at `lastBallot`, then 1 `fetch-rows` and 0 `read-one`. |
| B1 | `mutateWithTriggers` sends a LOGGED batch with more than 1 mutation to `mutateAtomically` (BS:444, SP:1151-1156). Steps, in order:<br>1. `forBatchlogWrite` picks min(2, live non-local endpoints in the local DC) at CL TWO (RP:238-276). The other-rack preference only applies with more than 2 candidates (RP:310-318), so it can't trigger in a 3-node cluster.<br>2. The availability check on every mutation's replicas.<br>3. `syncWriteToBatchlog` (BATCH_STORE_REQ).<br>4. `syncWriteBatchedMutations`.<br>5. `asyncRemoveFromBatchlog` (BATCH_REMOVE_REQ, no callback) once every mutation reaches the batch CL (BatchlogResponseHandler.java:51-56, 111-115).<br>Not corrected. | pass | contract (keyspace seam, worked around) | `bench-b1`: `batchlogEndpoints` is [.2, .3], 2 `batch-store` calls, then 2 `send-to-hinted-replicas` and 4 MUTATION_REQ (acks [3, 3]), then 2 `batch-remove` emits. The batches table ends empty. The order was confirmed with `--trace` (store at t=65, first MUTATION_REQ at t=96, remove at t=253). |
| B2 | **Clarified.** With .3 down: the batchlog goes to .2 only (CL ONE). Each mutation succeeds at QUORUM. .3 is hinted through `shouldHint` and `submitHint` without a message. The batchlog **is removed**, because `requiredBeforeFinish` = QUORUM blockFor is met (SP:1415-1417). Replay only covers mutations that never reached the batch CL. | pass | benchmark (expectation imprecise) | `bench-b2`: `batchlogEndpoints` is [.2], 1 `batch-store`, acks [2, 2], `hinted` is [.3, .3], 2 `hints-service.write`, `total_hints` is 2, the batchlog is removed. |
| B3 | **Clarified.** The schedule is `scheduleWithFixedDelay(replayFailedBatches, RING_DELAY 30s, 10s)` (BatchlogManager.java:114-117). The pass replays batches older than `BATCHLOG_REPLAY_TIMEOUT` = 2 x write_request_timeout = 4000ms (:95, :214). The rate is `batchlog_replay_throttle / ring size` = 341 KiB/s (:235-248). Then fsync the hints, delete, and advance `lastReplayedUuid` (:225). | pass | simulator (throttle effect, initial delay) | `bench-b3`: pass 1 at t=0 replays the batch written at -10000ms and leaves the one written at -1000ms. Pass 2 starts at 10104ms (fixed delay after the end of pass 1) and replays it. `replayThrottleKiBPerEndpoint` is 341. Both are deleted and `last_replayed_ms` is the limit. |
| B4 | **Corrected.** `verifyBatchSize` returns early when `mutations.size() <= 1` (a single partition, BS:333-335). It applies to LOGGED **and UNLOGGED** batches (`executeWithoutConditions`, BS:439), and conditional batches skip it. With `size > 51200` it throws `InvalidRequestException("Batch too large")` before any write. With `size > 5120` it adds one client warning and executes normally (BS:337-366). | pass | benchmark | `bench-b4-fail` (LOGGED, 52000B): `invalid` 8704 "Batch too large", 0 writes. `bench-b4-warn` (6000B): 1 warning, "...threshold of 5120 by 880", still atomic with the batchlog. `bench-b4-unlogged-fail`: refused. `bench-b4-single-partition` (60000B on one partition): accepted with no warning and no batchlog. |
| B5 | An UNLOGGED batch calls `mutateWithTriggers(mutateAtomically=false)`. Without views that goes to `StorageProxy.mutate` with `WriteType.UNLOGGED_BATCH` (SP:885), with no batchlog. Not corrected. | pass | contract (keyspace seam, worked around) | `bench-b5`: 1 `storage-proxy.mutate` call. `mutate-atomically`, `for-batchlog-write`, `batch-store` and `batch-remove` are all 0. 2 `send-to-hinted-replicas`, 4 MUTATION_REQ, `write_type` is UNLOGGED_BATCH. |

## 2. Wrong claims in the model

1. **`storage-proxy.commit-paxos` omits the live-replica check in `ReplicaPlans.forWrite`.**
   - The code calls `ReplicaPlans.forWrite(keyspace, consistencyLevel, tk, writeAll)` (SP:785). That method calls `assureSufficientLiveReplicasForWrite` (RP:469-476 → 186-193).
   - So a v1 commit at **ALL with a replica down throws `UnavailableException(ALL, 3, 2)`** after the proposal was accepted. Nothing is sent and nothing is hinted.
   - The model computes blockFor by hand, hints the down replica and reports `write-timeout` with write_type SIMPLE. Scenario `cas-v1-commit-all-down-replica` asserts that wrong outcome.
   - The hint branch for a down replica (SP:812-822) is only reachable when the CL is still satisfiable, for example QUORUM with one replica down. The model's `cas-v1-commit-down-replica-hinted` case is fine.
   - The same check probably affects the v2 counterpart (`cas-v2-commit-all-down-replica`). I didn't verify it, because v2 isn't deployed.
2. **The CAS and SERIAL result shape (minor, cql/paxos).** `[applied]=false` rows are returned as raw `{partition_key, cells}` partitions. The code builds a result set with an `[applied]` column followed by the condition columns (ModificationStatement.java:605-618, 650-668). SERIAL SELECT rows have the same raw shape.
3. **Citation off by one (cosmetic).** In `storage-proxy.mutate-atomically`, "Pick the batchlog endpoints" cites SP:1202, which is a blank line. The call is at SP:1203.
4. **The keyspace seam (contract, described above).** write-path's `keyspace` state doesn't declare the `shop` and `bank` tables that the CQL, Paxos and batch flows use by default, so the default flows silently skip storage.

I read about 60 behavior steps next to their citations, across these interfaces:
- `legacy-cas`, `do-paxos`, `begin-and-repair-paxos`, `prepare-paxos`, `propose-paxos`, `commit-paxos`, `legacy-read-with-paxos` and `for-paxos`;
- `mutate-with-triggers`, `mutate-atomically`, `wrap-batch-response-handler`, `sync-write-to-batchlog`, `sync-write-batched-mutations`, `async-remove-from-batchlog` and `for-batchlog-write`;
- `batch-statement.execute-without-conditions`, `batchlog-manager.replay-failed-batches` and `set-rate`.

Apart from item 1, all of them are accurate. The ProposeCallback latch and fail-fast logic is modeled faithfully, and so is the rule that only non-empty proposals are committed. The random citation sample (`--cite-sample 10 --seed 5150`) gave 10 of 10 matching claims, with one cited range starting a line early (`storage-service.repair-async`, :4797).

## 3. Builder findings, confirmed or refuted

Paxos (notes/paxos.md §6):
- **Confirmed:** "A failed condition is still proposed" in v1 (SP:359-364, 525-534).
- **Confirmed:** a v1 commit timeout is SIMPLE, while prepare and propose timeouts are CAS. `commitPaxos` uses `WriteType.SIMPLE` (SP:789), and `doPaxos` rewraps keeping `e.writeType` (SP:558-562).
- **Confirmed:** v1 failure responses only log. `AbstractPaxosCallback.onFailure` (:77-80) doesn't count down the latch.
- **Confirmed:** `cas_contention_timeout` is 1800ms in Config and 1000ms in the yaml.
- **Confirmed:** `casWithSnapshot` doesn't exist (no match in src).
- **Confirmed:** "LWT = 4 round trips" holds for v1.
- **Refuted:** "a v1 commit to a down replica is hinted but does not count as a failure, so you get a write timeout" at ALL. It is Unavailable from `forWrite` (wrong claim 1). The underlying fact, that `expired()` (AbstractWriteResponseHandler.java:219-222) doesn't count a failure, is true. It just can't decide the outcome when the failure detector already sees the replica as down.
- **Not verified:** the v2-only claims, because v2 isn't deployed.

Hints and batchlog (notes/hints-batchlog.md §6):
- **Confirmed #1:** replay hints dead replicas directly through `HintsService.write`, without `shouldHint` (BatchlogManager.java:491-502).
- **Confirmed #3:** BATCH_REMOVE_RSP is never sent. The handler only removes (BatchRemoveVerbHandler.java:28-31), and the coordinator uses `send` (SP:1319).
- **Confirmed #4:** removal waits for the batch CL (QUORUM for views), not the client CL (SP:1189-1200, 1417).
- **Confirmed #9:** with 2 or fewer endpoints, `validate` returns them all unfiltered (RP:296-297).
- **Confirmed #10:** `lastReplayedUuid` always advances to the limit (BatchlogManager.java:225).
- **Confirmed #13:** the batchlog CL is computed before the ANY fallback (RP:254-266).

## 4. Simulator gaps

- **Concurrency, or a competing proposer (L4).** Contention can't be sustained. A seeded higher promise is beaten on the first retry, because the next ballot is `promised+1`. Reaching `cas_contention_timeout` needs a latency fault as a stand-in. Mosaic needs concurrent flows, or scripted per-call responses, for example "reject the first N prepares".
- **Parallel fan-out, waiting for k of n (L1, L5, B1, B2).** Every prepare, propose, commit, BATCH_STORE and MUTATION_REQ runs as a sequential `foreach`. The decisions are right, but the latencies add up (L4 has its rejection arrive after the local promise, sequentially).
- **No call-order assertion (B1).** "The batchlog is written before the mutations" can only be checked in the trace. CEL `expect` has `calls` counts but no ordering, such as the index of the first call.
- **A rate limiter in time or bytes (B3).** `batchlog_replay_throttle` is computed (341 KiB/s) but doesn't slow anything down.
- **`entry.repeat` has no initial delay (B3).** `RING_DELAY` (30s) before the first replay can't be expressed: pass 1 runs at t=0.
- **Random back-off (L4).** `nextInt(100)` is a fixed 50ms.
- **Result reshaping (L2, L5).** Cell lists can't be turned into column-keyed rows in CEL, so CQL results carry raw partitions.

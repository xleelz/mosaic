# Judge report, round 2: `lwt-batch` (L1–L5, B1–B5)

Code: cassandra-5.0.9 at `/home/lbethay/.cache/cassandra-bench/cassandra-5.0.9`. `SP` stands for
`service/StorageProxy.java`, `RP` for `locator/ReplicaPlans.java`, `BS` for
`cql3/statements/BatchStatement.java` and `BM` for `batchlog/BatchlogManager.java`, all under
`src/java/org/apache/cassandra/`.

The model is the migrated `examples/cassandra/cassandra.json` (509 components, 1,426 interfaces, 1,571
scenarios, all passing, 5,099 citations that all resolve). My scenarios are in `judge/v2/scenarios/L{1..5}.yaml`
and `B{1..5}.yaml`: 14 scenarios, all on `fixtures: [three-node-rf3]`, with no mocks, all passing. Run them with:

```sh
go run ./internal/devtools/check -q -f examples/cassandra/cassandra.json \
  -f examples/cassandra/judge/v2/scenarios/<CASE>.yaml --scenario '^bench' --trace
```

`B1-xtable.yaml` is a separate probe for a wrong claim (section 2). It is **expected to fail**.

The deployed config I re-checked:
- `paxos_variant` is unset (`#paxos_variant: v1`, cassandra.yaml:1602), so it is `v1` (Config.java:1051).
  `Paxos.useV2()` is false and `isLinearizable()` is true for v1 (Paxos.java:1210-1240).
- `cas_contention_timeout: 1000ms` (yaml:1339), `write_request_timeout: 2000ms` (yaml:1330).
- `batch_size_warn_threshold: 5KiB` and `batch_size_fail_threshold: 50KiB` (yaml:1840, 1844),
  `batchlog_replay_throttle: 1024KiB` (yaml:157), and `endpoint_snitch: SimpleSnitch` (yaml:1556), so there is one rack.

**Round 1's keyspace seam is gone.** The shared `base-schema` fixture declares `shop.*` in write-path's `keyspace`
state. Every CAS commit, batch mutation and replay now reaches `commit-log.add` and the memtable on each node
(L1 asserts `commit-log.add@n1`, `@n2` and `@n3`). No scenario needs state workarounds any more.

## 1. Cases

I scored each case before reading round 1's scores. The round 1 comparison is in the last column.

| ID | Verified expectation (round 1's, re-checked) | Score | Root cause | Evidence | vs round 1 |
|---|---|---|---|---|---|
| L1 | v1: `cas` → `legacyCas` (SP:325-328) → `doPaxos`. One ballot. Prepare goes to every live contact and waits for `participants/2+1` (RP:627-635). Then the precondition `readOne` at QUORUM (SP:351-356), the propose, and the commit at the commit CL to every live replica (SP:785-826). The commit is skipped only for an empty update (SP:533-534). `[applied]` is true. **Confirmed.** | pass | — | `bench-l1`: 1 `next-ballot`, then local `legacy-prepare@n1` plus `prepare-verb-handler@n2` and `@n3`, running concurrently at t=31. Next, `read-one` at QUORUM (n1 data plus n2), which the trace places after the prepare and before the propose. Then 3 `legacy-propose`, `commit-paxos` with 3 `commit-direct` and `commit-log.add` on n1–n3, and `paxos-state@n3` committed `name=Ada`. `mutate-with-triggers` is not called. | unchanged (pass). Better: the seam workaround is gone, and the fan-outs are concurrent. |
| L2 | **Round 1's correction confirmed.** `[applied]` false plus the current values (ModificationStatement.java:605-618). v1 **still proposes the empty update, and a quorum accepts it**. Only the commit is skipped (SP:359-364, 529-534). | pass | benchmark | `bench-l2` is a **multi-step** scenario. Step 1 is `INSERT IF NOT EXISTS name=Ada`. Step 2 is `UPDATE SET name=Cy IF name=Bob`. It returns `rows[0] == {'[applied]': false, name: 'Ada'}` and `casConditionMet` false. The second propose has `update_empty: true`, and all 3 replicas accept it (6 `legacy-propose` in total). There is only 1 `commit-paxos` (step 1's). n2 ends with `committed name=Ada, accepted_empty: true`. | unchanged (pass). Better: the result now has the `[applied]` column, which fixes round 1's wrong claim 2, and the state is seeded by a real earlier write rather than by hand. |
| L3 | `forPaxos`: 3 participants, so 2 are required, and only 1 is live. It throws `UnavailableException(SERIAL, 2, 1)` at the start of the attempt, before any ballot (RP:630-635, SP:507). **Confirmed.** | pass | — | `bench-l3` (gossiper@n1 sees n2 and n3 down): `unavailable` 4096 `{SERIAL, required 2, alive 1}`. 1 `for-paxos`. `next-ballot`, `prepare-paxos`, PAXOS_PREPARE and `read-one` are all 0. | unchanged |
| L4 | **Round 1's clarification confirmed.** A rejected prepare increments `contentions` and sleeps a uniform `nextInt(100)` ms (SP:608-615). The rejection carries the replica's **promised** ballot (PaxosState.java:751-753), so the next ballot is `promised+1` (SP:597-600). The loop runs until `cas_contention_timeout` (1000ms) from the request start (SP:502-504, 591). It ends in `CasWriteTimeoutException(CAS, SERIAL, 0, SERIAL.blockFor(rs)=2, contentions)` (SP:682). | partial | simulator | `bench-l4-retry`: n2 holds a higher promise. The prepare is rejected, `prepareRejected` is set, and `random(100)` back-off follows. The second prepare's ballot is exactly `1793318400500001` (promise+1), it wins, and the write applies with `casContentions == 1`. `bench-l4-timeout`: n2 and n3 both hold the higher promise and answer slowly (990ms latency on their first PREPARE). The next attempt starts past the deadline, giving `write-timeout` `{CAS, SERIAL, received 0, block_for 2, contentions ≥1}` with duration between 1000 and 2000ms, and no read, propose or commit. Contention can't be **sustained** without a concurrent competing proposer, so reaching the deadline still needs a latency stand-in. | unchanged (partial, simulator). Better: the back-off is now random rather than a fixed 50ms, and the replicas answer concurrently. |
| L5 | v1 `legacyReadWithPaxos` (SP:1898-1904) → `doPaxos` with an empty-update proposer (`isLinearizable()` is true, SP:1930-1933). `beginAndRepairPaxos` finishes the in-progress round: it re-proposes with our ballot and commits at QUORUM with no hints (SP:638-646, `consistencyForReplayCommits` = QUORUM, SP:1922-1924). Then it prepares again, and the empty proposal is accepted but never committed. Last, `fetchRows` at QUORUM (SP:1956). **Confirmed.** | pass | — | `bench-l5` (CQL SELECT at SERIAL, with n1 holding the accepted `name=Ada` proposal): 1 `legacy-read-with-paxos`, 0 `paxos.read`. `unfinishedCommit` is set. There are 2 `prepare-paxos`, 2 `propose-paxos` (the second with `update_empty: true`) and 1 `commit-paxos` at QUORUM with `name=Ada`, which the trace places before `fetch-rows` at QUORUM. n3 ends committed. The result is `rows == [{name: 'Ada'}]`, a column map. | unchanged (pass). Better: the seam is gone, and the rows are column maps. |
| B1 | `executeWithoutConditions` → `mutateAtomic = isLogged && mutations.size() > 1` (BS:443-444) → `mutateAtomically` (SP:1151-1156, 1173). The steps, in order:<br>1. `forBatchlogWrite` picks min(2, live non-local nodes in the local DC) at CL TWO (RP:238-276). The rack preference is unreachable with 3 nodes, because `validate` returns early at ≤2 (RP:310-311), and with SimpleSnitch.<br>2. `wrapBatchResponseHandler` checks availability for every mutation (SP:1209-1220).<br>3. `syncWriteToBatchlog` (SP:1223).<br>4. `syncWriteBatchedMutations` (SP:1226).<br>5. `asyncRemoveFromBatchlog` once every mutation reaches the batch CL (BatchlogResponseHandler.java:51-56, 111-115).<br>**Confirmed.** | pass | — | `bench-b1`: `batchPartitions` 2, `mutateAtomically` true. `batchlogEndpoints == [n2, n3]`, and `sync-write-to-batchlog` runs at `TWO` with BATCH_STORE on n2 and n3 and no local store. 2 `wrap-batch-response-handler` calls, and **trace order is asserted**: wrap, then batchlog, then mutations. 4 MUTATION_REQ and 2 local applies. 1 `async-remove-from-batchlog`, BATCH_REMOVE on n2 and n3, and both batchlogs end empty. | unchanged (pass). Better: the order is now asserted in `expect`, which round 1 could only check by eye, and the fan-outs are concurrent. |
| B2 | **Round 1's clarification confirmed.** With n3 down, the batchlog goes to n2 only at CL ONE (RP:255). Each mutation succeeds at QUORUM. n3 is hinted through `shouldHint`/`submitHint` and gets no message. The batchlog **is removed**, because `requiredBeforeFinish = batchCL.blockFor` (SP:1417) is met: without views the batch CL is the client CL, here QUORUM (SP:1192-1201). | pass | benchmark (imprecise) | `bench-b2`: `batchlogEndpoints == [n2]` at `ONE`, BATCH_STORE on n2 only. `mutation-verb-handler@n2` is called twice and `@n3` never. There are 2 `submit-hint` calls targeting n3. Then `async-remove` and BATCH_REMOVE on n2, and n2's batchlog ends empty. | unchanged |
| B3 | **Round 1's clarification confirmed.** `scheduleWithFixedDelay(replayFailedBatches, RING_DELAY 30s, 10s)` (BM:114-117, :90). Each pass replays batches older than `BATCHLOG_REPLAY_TIMEOUT` = 2 × write_request_timeout = 4000ms (BM:95, :214). The throttle is `1024 / ring size` = 341 KiB/s per endpoint (BM:235-248), acquired after sending (BM:367). Then the hints are fsynced, the batches deleted, and `lastReplayedUuid` set to the limit (BM:225). | pass | — | `bench-b3` uses `b-old` (written at -10s) and `b-young` (written at +27s). Pass 1 runs at **exactly t=30000**: it replays `b-old` only, because `b-young` is 3s old (under 4s). Pass 2 runs at 40000 < t < 41000, which is 10s after pass 1 *ends* (fixed delay), and replays `b-young`. `replayThrottleKiBPerEndpoint` is 341. Both batches are deleted, `total_batches_replayed` is 2, MUTATION_REQ goes to n2 and n3 twice each, and there are 2 `flush-and-fsync-blockingly`. | unchanged (pass). Better: the RING_DELAY initial delay and the fixed-delay schedule are now reproduced, and the throttle is a `wait`. Round 1 had to note both as simulator gaps. |
| B4 | **Round 1's correction confirmed.** `verifyBatchSize` returns early when `mutations.size() <= 1` (BS:333-334). It applies to LOGGED **and UNLOGGED** batches (`executeWithoutConditions`, BS:439), and conditional batches skip it. Over 51,200 bytes it throws `InvalidRequestException("Batch too large")` before any write. Over 5,120 bytes it adds one client warning and executes (BS:337-366). | pass | benchmark | `bench-b4-fail` (LOGGED, 60,000B over 2 partitions): `invalid` 8704 "Batch too large", with 0 `mutate-with-triggers`, 0 `for-batchlog-write` and 0 `keyspace.apply`. `bench-b4-warn` (6,000B): 1 warning, "…threshold of 5120…", still atomic with batchlog removal. `bench-b4-unlogged-fail`: refused the same way. `bench-b4-single-partition` (60,000B on one key): accepted with no warning, no batchlog, and plain `mutate`. | unchanged |
| B5 | An UNLOGGED batch calls `mutateWithTriggers(mutateAtomically=false)`. Without views that goes to `StorageProxy.mutate` with `WriteType.UNLOGGED_BATCH` when there is more than 1 mutation (SP:885), and no batchlog. **Confirmed.** | pass | — | `bench-b5`: 1 `mutate`, 0 `mutate-atomically`. `for-batchlog-write`, BATCH_STORE, BATCH_REMOVE and `batchlog-manager.store` are all 0. 4 MUTATION_REQ and 2 local applies. `ctx.write_type` is UNLOGGED_BATCH, and so is `perform-write`'s input. | unchanged (pass). Better: the seam is gone. |

**Totals:** 9 pass and 1 partial (L4, simulator), the same as round 1. No case regressed. Round 1 scored L1, L5, B1 and
B5 as passes that relied on a state workaround for the keyspace contract seam. They now pass on the shared
fixture alone. **I found no round 1 correction that was wrong.**

## 2. Wrong claims found in the model

1. **`batch-statement.get-mutations` merges a cross-table, same-partition batch into one table.** (New. Model, cql
   area.)
   - **The code.** A batch builds one `Mutation` per keyspace and partition key. That mutation holds **one
     `PartitionUpdate` per table**, because `MutationBuilder.modifications` is keyed by `TableId`
     (cql3/statements/BatchUpdatesCollector.java:193-231).
   - **The model.** Its "Same partition, merge into the existing PartitionUpdate" step merges the second
     statement's `columns` into the first statement's mutation, which keeps only the first statement's `table`.
   - **The probe** (`B1-xtable.yaml`) is `INSERT INTO users (k1, name)` plus `INSERT INTO orders (k1, total)` in one
     batch. The model writes `total` into `shop.users` on every replica and writes nothing to `shop.orders`. The
     outcome is still `ok`, and it is correctly non-atomic, because `size == 1`.
   - **The fix.** Key the merge by keyspace, partition key and table, or carry a per-table update list inside each
     mutation.
2. **The contention-timeout `block_for` uses Paxos participants, not `SERIAL.blockFor(rs)`.** (Minor.)
   - **The code.** `doPaxos` (SP:568) and `beginAndRepairPaxos` (SP:682) throw
     `CasWriteTimeoutException(..., consistencyForPaxos.blockFor(rs), ...)`, which is the quorum of the replication
     factor.
   - **The model.** It reports `plan.required_participants`, which is `(natural + pending)/2 + 1`.
   - **The effect.** The two are equal in the 3-node fixture, so no benchmark case is affected. With one pending
     replica the model reports 3 where the code reports 2.
3. **The replay rate limiter is charged up front.** (Cosmetic.) `batchlog-manager-replaying-batch.replay` waits
   `bytes / rate` on the current acquire, with an assumed 512 bytes per mutation. Guava's `RateLimiter.acquire`
   grants the current request and makes the *next* caller pay (BM:367). The timing is approximate, but the
   decisions are unaffected.

**Round 1's wrong claims have all been fixed:**
- **Claim 1.** `commit-paxos` now calls `replica-plans.for-write` (SP:785), so a commit at ALL with a replica down is
  `unavailable` (scenario `cas-v1-commit-all-down-replica`).
- **Claim 2.** CAS and SERIAL rows are now `[applied]` plus column maps (L2, L5).
- **Claim 3.** The citation is now SP:1203.
- **Claim 4.** The seam is fixed by the shared fixture.

**Spot checks.** `--cite-sample 10 --seed 52` gave 10 of 10 accurate claims. One is weak:
`storage-service-mbean.set-concurrent-view-builders` claims "values <= 0 are refused" but cites only the MBean
signature. By hand I checked 30 in-area citations against the code, all accurate:
- `do-paxos`: 502-503, 506-508, 525-527, 529-534, 543-546 and 568;
- `begin-and-repair-paxos`: 597-600, 608-615, 638-646, 661-671 and 682;
- `cas` and `legacy-cas`: 319-328 and 344-364;
- `for-paxos`: RP:630-644;
- `commit-paxos`: 785, 793-826 and 807-810;
- `sync-write-to-batchlog`: 1296-1305;
- `execute-without-conditions`: BS:351-365 and 443-445;
- `legacy-read-with-paxos`: 1930-1933;
- `replay`: BM:361-367.

## 3. Builder findings, confirmed or refuted

These are the claims in `notes/paxos.md` §6 and in the `notes/hints-batchlog.md` migration section.
- **Confirmed:**
  - A failed v1 condition is still proposed (L2).
  - A v1 commit timeout is SIMPLE, while prepare and propose timeouts are CAS (SP:789, 558-562).
  - v1 failure responses only log.
  - `cas_contention_timeout` is 1800ms in Config.java:157 and 1000ms in the yaml.
  - Batchlog replay starts after RING_DELAY 30s (BM:114-117; `bench-b3` shows t=30000).
  - `RateLimiter.acquire(bytes)` comes after sending (BM:367). The up-front timing is approximate, see wrong claim 3.
  - The "Pick the batchlog endpoints" citation is fixed (SP:1203).
  - Sustained contention is still not expressible (paxos.md migration "Still open"). I agree.
- **Refuted, as a stale note:** paxos.md §6 still says "a v1 commit to a down replica is hinted but does not count as
  a failure, so you get a write timeout (`cas-v1-commit-all-down-replica`)". At ALL it is
  `UnavailableException` from `forWrite` (SP:785 → RP:469-476). The model and its scenario are now right, and the
  migration section says it supersedes §6. Still, §6 should be corrected.

## 4. Simulator gaps

**Still open:**
- **Concurrent competing requests (L4).** The DESIGN §11.2 rule that state isn't interleaved between branches,
  and the fact that steps are sequential, mean a second proposer can't keep re-promising during our request. A
  seeded higher promise is beaten on the first retry (`promised+1`), so `cas_contention_timeout` is reached only
  with a latency stand-in. Mosaic needs interleaved concurrent flows, or scripted per-call responses (such as
  "replica n2 rejects the first N prepares").
- **v1 CasWriteUnknownResult** (a promiser refusing our proposal) is unreachable for the same reason. It isn't a
  benchmark case.
- **Minor: `calls_by_instance` has zero-valued keys** for interfaces that ran nowhere on an instance, such as
  `batchlog-manager.store@n1` in B1. That makes `'k' in calls_by_instance` true even for calls that never happened.
  This is a documentation gap rather than a missing feature. Scenario authors should assert `== 0`.

**Resolved by DESIGN §11 since round 1:**
- **Parallel k-of-n fan-out (§11.2).** Prepare, propose, commit, BATCH_STORE and MUTATION_REQ are concurrent with
  real joins (L1, B1).
- **Call-order assertions (§11.8 `trace`).** B1, L1 and L5 assert the ordering in `expect`.
- **Initial delay for repeats and fixed-delay scheduling (§11.3).** B3's first pass is at 30s.
- **Random back-off (`random(n)`, §11.8).** L4.
- **Result reshaping (`transformMapEntry`, §11.8).** L2 and L5 now return `[applied]` and column maps.
- **A rate limiter.** B3's throttle is now a `wait` (approximate, see wrong claim 3).
- **Per-node state and instance targeting (§11.1)** and **shared fixtures (§11.7).** These removed round 1's
  keyspace seam workaround.
- **Multi-step scenarios (§11.7).** L2 seeds its row with a real CAS write.

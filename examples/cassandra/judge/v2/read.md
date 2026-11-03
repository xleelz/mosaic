# Judge round 2: read group (R1–R7)

Model: the migrated `examples/cassandra/cassandra.json` (1,571 scenarios, all passing; DESIGN §11
features). Scenarios: `judge/v2/scenarios/R1.yaml` … `R7.yaml`. 20 scenarios, all on the shared
fixture `three-node-rf3`, no mocks, and all data-driven (no forced `choices`). 18 pass. The 2 that
fail are deliberate. Each one records a defect: `bench-r2-repair-mutation-is-a-diff` and
`bench-r6-failure-signals-immediately`.

Run:

```sh
go run ./internal/devtools/check -q -no-mocks -f examples/cassandra/cassandra.json \
  -f examples/cassandra/judge/v2/scenarios/R1.yaml ... -f .../R7.yaml --scenario '^bench'
```

Cluster: token 100 has natural replicas [n3, n1, n2] in ring order. SimpleSnitch keeps that order
(SimpleSnitch.java:41-45), and the dynamic snitch with no scores keeps the subsnitch order. So n3
gets the data request and n1, the coordinator, gets the local digest request.

## 1. Cases

I re-checked each round 1 "verified expectation" against the code before relying on it. All
seven still hold. I found no round 1 correction to be wrong.

| ID | Verified expectation (corrected?) | Score | Root cause | Evidence |
|---|---|---|---|---|
| R1 | Round 1 is confirmed. The table default is 99p (TableParams.java:366), so a `SpeculatingReadExecutor` is used (AbstractReadExecutor.java:214-217). There are blockFor = 2 contacts (ReplicaPlans.java:716-727). initialDataRequestCount is 1 because readQuorum is not below the contact count (:302). The data request goes to n3 and the digest request to the local n1, which runs last (:161-166). The data is returned when the digests match (:428-430). | **pass** | – | `bench-r1-quorum-all-up`: executor `speculating` with contacts [n3, n1]. One READ_REQ goes to n3 with digest=false, and the local runnable on n1 runs with digest=true. Digests match and come from the data. There is no repair and no speculation (the speculative branch wakes at 2500ms, sees the read signaled and does nothing). The row is returned in under 2500ms. |
| R2 | Round 1 is confirmed, with its detail. `startRepair` sends full data reads to the contacts (AbstractReadRepair.java:147-150). The DataResolver merges the unfiltered data, where the newest cell wins and tombstones shadow older cells. `BlockingReadRepair` waits for the repair acks (BlockingReadRepair.java:83-107). Each stale replica gets only its **diff** (RowIteratorMergeListener.java:382-398). | **pass** (one minor wrong claim) | model (minor) | `bench-r2-digest-mismatch-blocking-repair`: the replicas' data causes the mismatch (choice origin `expression`). Full re-reads go to n3 and n1. The newest cell wins for each column (name=Bea@2000 from n3, city=Oslo@3000 from n1). Both replicas are stale, each gets a READ_REPAIR_REQ, both memtables are rewritten, and `await-writes` runs before the response. `bench-r2-newer-tombstone-wins-across-replicas`: a newer tombstone on n3 shadows Ada@1000 on n1, the client sees no name, and n1 is repaired with the tombstone. Gap: `bench-r2-repair-mutation-is-a-diff` **fails**, because the mutation is the whole merged partition (W1). |
| R3 | Round 1 is confirmed. `forRead` filters to live replicas, then `assureSufficientLiveReplicasForRead` throws `UnavailableException` 0x1000 with required 2 and alive 1, before any message is sent (ReplicaPlans.java:723-726). | **pass** | – | `bench-r3-*`: with n2 and n3 dead in gossiper@n1, the read fails with `unavailable`/4096 and data {required 2, alive 1}. It makes 0 READ_REQs and 0 local reads. The same happens end to end through `cql-select`. |
| R4 | Round 1 is confirmed. At ONE there is 1 contact and 3 candidates, so a speculating executor is used. `maybeTryAdditionalReplicas` waits for `sampleReadLatency`, initially read_request_timeout / 2 = 2500ms (ColumnFamilyStore.java:498), and later the 99p (:594). With no data by then, it sends a **data** request to the first uncontacted full candidate (AbstractReadExecutor.java:305-349). | **pass** | – | `bench-r4-one-slow-replica-speculates`: n3 answers after 4000ms. At t ≥ 2500 a data read goes to n1, the first uncontacted candidate, and its row is returned in the 2500–4000ms window. n3's response is marked `late`. `bench-r4-sampled-latency-used`: with a sampled latency of 20ms, speculation fires at about 20ms. |
| R5 | **Corrected** in round 1, and the correction holds. With 99p and all 3 nodes up, a silent replica is speculated around and the read succeeds. `read-timeout` needs no spare replica: with n2 down there are 2 contacts and 2 candidates, so `NeverSpeculatingReadExecutor` is used (AbstractReadExecutor.java:209-213), and the read fails with `ReadTimeoutException(QUORUM, received 1, blockFor 2, dataPresent false)` at 5000ms (ReadCallback.java:128-178; conf/cassandra.yaml:1322). | **pass** | benchmark (expectation corrected) | `bench-r5-silent-replica-all-up-speculates`: n3 times out, a data read speculates to n2, and the read succeeds between 2500 and 5000ms. `bench-r5-no-spare-replica-read-timeout`: executor `never_insufficient`, `read-timeout`/4608 with {received 1, block_for 2, data_present false, QUORUM}, duration 5000–5100ms. CQL end to end: 0x1200. |
| R6 | Round 1 is confirmed, with its detail. The counts are strict (more than 1000 warns, more than 100000 throws; ReadCommand.java:588-603, 622-645), taken after the purgeable tombstones are dropped (:460). A remote `TombstoneOverwhelmingException` becomes a READ_TOO_MANY_TOMBSTONES failure response (ReadCommand.java:836; InboundSink.java:81-91; RequestFailureReason.java:82-91). blockFor + failures > contacts **signals at once** (ReadCallback.java:241-250), so the result is `ReadFailureException` 0x1300 with no speculation. The warning reaches the client only through `ClientWarn` on the coordinator's own read (:631), because read_thresholds_enabled is false (Config.java:526). | **partial** | model + simulator | Outcome right: `bench-r6-warning-from-coordinator-local-read` puts 5000 tombstones on n1 and the native-query response carries the "5000 tombstone cells" warning. `bench-r6-warning-on-remote-replica-not-sent`: n3 logs and counts the warning, and the client gets none. `bench-r6-strictly-greater-than-1000`: no warning. `bench-r6-tombstone-overwhelming-read-failure`: 200000 tombstones on n3 lead to `read-failure`/4864 with reasons [READ_TOO_MANY_TOMBSTONES], no speculation, and the client gets 0x1300. **Path wrong:** `bench-r6-failure-signals-immediately` **fails**. The failure is in at 39ms, but the read fails only at 2522ms (W2). |
| R7 | Round 1 is confirmed. `queryMemtableAndDiskInternal` reads every memtable, then the sstables in descending max-timestamp order, stopping at sstables older than a partition tombstone it has seen (SinglePartitionReadCommand.java:708-806). Key range and bloom filter rule out BIG sstables (BigTableReader.java:255-263). The merge uses `Cells.reconcile` (Cells.java:80-128): a higher timestamp wins; on a tie a tombstone wins, then the greater value. The names-filter path (:701-706) gives the same result. | **pass** | – | `bench-r7-local-read-merges-sources` uses a memtable and 3 sstables on n2. nb-2 (max ts 5000) doesn't hold the key and is skipped without a data read (BLOOM_FILTER). nb-3 (1500) supplies a partition deletion. nb-1 (1000) is never opened (OLDER_THAN_PARTITION_TOMBSTONE). The result is city=Rome@2000, the email tombstone@2500 kept in the replica response, deletion_ts 1500, and no name. `bench-r7-tie-rules`: on a tie the tombstone beats the live cell, and Bea beats Ada. `bench-r7-coordinator-sees-merged-row`: the client sees only the live merged cells. The names-filter shortcut isn't modeled (the notes say so), but it gives the same result. |

## 2. Comparison with round 1

I scored all seven cases above before I read `judge/read.md` and `judge/read.json`.

| ID | Round 1 | Round 2 | Change | Why |
|---|---|---|---|---|
| R1 | pass | pass | unchanged | Same path, now with instances and a `parallel` join. |
| R2 | partial | pass | **improved** | Round 1's W1 is fixed: replicas now return unfiltered data, `data-resolver.resolve` merges with tombstones and filters afterwards, and a newer tombstone wins and is repaired onto the stale replica. The contract seam is fixed too: repair writes land, because `base-schema` seeds `keyspace.tables`. Only the minor diff-versus-full-partition issue remains (round 1's W4, now W1). |
| R3 | pass | pass | unchanged | – |
| R4 | sim-gap | pass | **improved** | DESIGN §11.2 `parallel` + join + `wait` lets the speculative branch fire at start + sampleReadLatency while the slow call is still in flight. A slow replica that still answers now triggers speculation, as the code does. |
| R5 | pass | pass | unchanged | It also no longer succeeds after the read deadline: the join's `timeout_ms` is start + read_request_timeout. |
| R6 | partial | partial | unchanged score, different reason | Fixed: round 1's W3, because `client-warn.warn` is now called on the coordinator's own read and the warning reaches the native response. **Regressed:** round 1 saw the failure signal at once, but after the migration to `parallel` the ReadFailure is held until the speculative branch wakes at 2500ms (W2). |
| R7 | partial | pass | **improved** | Round 1's W2 and W5 are fixed. Sstables are now separate entries, sorted by descending max timestamp, with a per-sstable bloom filter / key range skip and the early stop at a partition deletion. `cells.reconcile` breaks ties by tombstone, then by the greater value, and the cross-replica merge in `data-resolver.resolve` does the same. |

Totals: round 1 had 3 pass, 3 partial and 1 sim-gap. Round 2 has 6 pass and 1 partial.

## 3. Wrong claims in the model

- **W1 (minor): a read-repair mutation is the whole merged partition, not the replica's diff.**
  - Where: `row-iterator-merge-listener.close` sends `cells: vars.e.partition.cells` to each stale
    replica. It cites RowIteratorMergeListener.java:365-399, and those lines say otherwise.
  - What the code does: each read contact gets `repairs[i].build()`, its own diff. `fullDiffRepair`
    goes only to write-plan contacts that weren't read (:382-398).
  - Effect: after reconciliation the result is the same, but the mutation size is overstated.
  - Exposed by `bench-r2-repair-mutation-is-a-diff`, where n1 receives name **and** city when it
    needed only name. Round 1 reported this too, and it is unfixed.
- **W2: a replica failure doesn't decide the read at once when a speculative request is pending.**
  - Where: `abstract-read-executor.execute-async` puts the not-yet-sent speculative request into
    the `parallel` join as a third branch, with `need: block_for`.
  - What goes wrong: once n3 fails at about 39ms, 2 successes are still "possible" (n1 plus the
    dormant speculative branch). The join therefore stays open until that branch wakes at 2522ms,
    finds the read already decided and fails with `no-speculation`.
  - What the code does: `onFailure` signals when blockFor + failures > **contacts** (2 + 1 > 2,
    ReadCallback.java:247-248). The speculative replica isn't a contact until it is sent. So
    `awaitResults` throws ReadFailure in milliseconds, and `shouldSpeculateAndMaybeWait` returns
    false.
  - Effect: the outcome is right (read-failure, no speculation), but the latency is wrong by the
    whole sample latency. It also contradicts `read-callback.await-results`, which cites the same
    lines and computes `signaled` correctly, but runs only after the join.
  - The same pattern is in `abstract-read-repair.start-repair`.
  - Exposed by `bench-r6-failure-signals-immediately`. The model's own `read-tombstone-failure`
    doesn't assert timing, so it passes.

Citations:
- Random sample (`--cite-sample 12 --seed 2207`): every citation resolves (5099/5099), and the 12
  claims match the code. I read #2, #8, #10, #11 and #12 in full: DefaultSchemaUpdateHandler:237,
  StorageProxy:1928-1934, Flushing:171, IndexSummaryManager:111-114 and
  BatchCommitLogService:36-42.
- I also checked these read-flow citations against the code, and they match: ReplicaPlans.java:716-727;
  AbstractReadExecutor.java:190-217, 290-351, 420-430; ReadCallback.java:128-178, 241-250;
  ReadCommand.java:458-461, 530-533, 580-650, 834-837; DigestResolver.java:77-103;
  AbstractReadRepair.java:140-152; BlockingReadRepair.java:80-108; Cells.java:80-128;
  SinglePartitionReadCommand.java:698-712; ColumnFamilyStore.java:498, 588-598;
  TableParams.java:366. The one exception is the RowIteratorMergeListener claim (W1).

## 4. Builder findings (notes/read-path.md §6)

| Finding | Verdict | Evidence |
|---|---|---|
| A tombstone-overwhelmed replica sends a failure response, not a timeout | confirmed | ReadCommand.java:836 (CALL_BACK_ON_FAILURE); InboundSink.java:81-91 |
| Only TombstoneOverwhelming and IncompatibleSchema have their own failure reasons | confirmed | RequestFailureReason.java:82-91 |
| Purgeable tombstones are dropped before counting | confirmed | ReadCommand.java:460 (`withoutPurgeableTombstones` before `withMetricsRecording`) |
| Local system keyspaces ignore the tombstone thresholds | confirmed | ReadCommand.java:532 |
| read_thresholds_enabled is false in 5.0.9 | confirmed | Config.java:526; conf/cassandra.yaml:2015 (commented out) |
| Out-of-range reads are logged and served by default | confirmed | Config.java:793 |
| The names-filter timestamp-order shortcut gives the same result (not modeled) | confirmed, for the R7 cases | SinglePartitionReadCommand.java:701-706 |

## 5. Simulator gaps

**Resolved by DESIGN §11:**
- *No concurrent in-flight calls / "wait until T, or k of n"* (round 1: R4, R5) is resolved by
  §11.2 `parallel` + `join.need` + `wait` in a branch. Speculation now fires at the sample latency
  while the slow call is in flight.
- *No deadline accounting* (round 1: R4, R5) is resolved by the join's `timeout_ms` (start +
  read_request_timeout) and the §11.3 deadlines. The read times out at 5000ms and never succeeds
  after it.
- *No map construction or fold* (round 1: R7, W4) is resolved in part by §11.8 `sum`, `merge` and
  `transformMap`, and the per-sstable merge is now modeled. The per-replica diff (W1) is still
  awkward, but it could be expressed now.

**Still open:**
- **A join has no failure budget or early-fail predicate** (exposed by R6,
  `bench-r6-failure-signals-immediately`).
  - The problem: `parallel` fails only when `need` successes become impossible. Cassandra fails
    when blockFor + failures > contacts, and a dormant speculative branch isn't a contact yet.
    Mosaic has no way to make a delayed, conditional branch not count as pending. So the join
    can't fail before that branch wakes.
  - Possible fixes: a `join.fail_when: "=cel over {received, failed, pending, started}"`, or
    letting a staggered branch be cancelled once the join's outcome is decided (today a due
    branch starts only while the join is unmet, but an already-started branch sitting in a
    `wait` is not cancelled).
  - Alternatively, the model could use `stagger_ms` for the speculative branch, if staggered
    branches that aren't due yet are dropped from the "possible" count. That would need checking.
- **Branch state is not interleaved** (§11.2). This is a limitation, not a failing case. The
  speculation branch decides from `ctx.read.responses` filtered by `t <= now`. That works only
  because the branches run in list order and the speculative branch comes last. Any model where
  an earlier branch needs to see a later branch's timed result can't express it.
- **The 99p sample latency is a static table parameter.** It is not computed from the recorded
  coordinator read latency (ColumnFamilyStore.java:594), so adaptive speculation can't emerge from
  a run. Scenarios can only set `sample_read_latency_ms`.

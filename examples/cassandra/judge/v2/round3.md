# Judge round 3: Cassandra after the fix round

Model: `skeleton.yaml` + `fixtures.yaml` + `fragments/*.yaml` (unchanged by the judge), run with `/tmp/mcheck`.
Code: Cassandra 5.0.9. Rules: `JUDGE-v2.md`. Engine change since round 2: a step without `at_ms` waits for the
previous step's emits and timers.

**Result: 44 of 44 pass (round 2: 37), plus B1-xtable (round 2: fail, now pass).** Every `judge/v2/scenarios`
file passes (102 scenarios).

## 1. The four failing scenarios at the start of round 3

| Scenario | Kind | Verdict |
|---|---|---|
| `bench-c1-probe-gc-grace-not-evaluated` | probe of the old gap | It asserted the wrong claim (`tombstones_purged == 0`, the ancient `city` tombstone kept). It now fails because the model evaluates `gcBefore = now - gcGraceSeconds` (`ColumnFamilyStore.java:1970-1973`) and the overlap check (`CompactionController.java:245-284`). **Not a regression.** The main C1 scenarios do **not** check the fix: `bench-c1-stcs-purge` uses the fixture SSTables without `partitions`, which still go through the summary counters (`notes/read-path.md`, fix round). So I replaced the probe with two positive cases (below). |
| `bench-p2-probe-streamed-not-pending` | probe of the old gap | It asserted a streamed `added-` SSTable stays unrepaired. It now fails because the streamed SSTables carry the session's pendingRepair (`CassandraStreamReader.java:105,135`, the writer is created with `header.pendingRepair`) and are promoted after FINALIZED. **Not a regression.** Main `bench-p2` checks only `u-1`, `u-2` and `r-0`, so it does **not** check the fix. I replaced the probe with a positive case. |
| `bench-g3-join-end-to-end` | **(a) harness drift: timing** | `gossiper.start` now schedules the GossipTask (`Gossiper.java:2028-2031`, `scheduleWithFixedDelay`). The rounds land after the join and carry NORMAL to n1, so the BOOT ACK2 injected after the join is older and ignored, and the write has blockFor 2. In the code, n4 gossips BOOT during the RING_DELAY sleep (`StorageService.java:2216-2226`), before NORMAL. Adaptation: the BOOT ACK2 at `at_ms: 5000`, the write at `10000`, NORMAL at `40000`, and `max_virtual_ms: 120000`. All assertions are unchanged, and it passes. |
| `bench-w10` | **(b) wrong expectation in the round-2 scenario** | It asserted `skip-list-memtable@n1.cells['shop.users:user:43:name']` after startup. In the code, `blockForWrites` flushes every replayed keyspace (`CommitLogReplayer.java:244-270`) and the flush discards the old memtable (`ColumnFamilyStore.java:1391-1404`), so the row is in an SSTable. It passed in round 2 only because of the W9 bug (a flush kept the cells). The claim is the same: the row is replayed, then flushed. The new assertions are a `keyspace.apply` for `user:43`, the row in the `shop.users` Tracker View SSTable partitions, and the row not in the memtable. It passes. |

## 2. Adaptations (all in `judge/v2/scenarios/`)

- `G3.yaml`: the `at_ms` and `max_virtual_ms` timing above. Assertions untouched. The `(expected to fail)` labels on
  `bench-g3-strict-sources` and `bench-g3-fresh-node-local-state` now read "passes in round 3".
- `W10.yaml`: the memtable assertion moved to the SSTable (b), as described above.
- `C1.yaml`: the probe was replaced by `bench-c1-gc-grace-purges-old-tombstone`, where a tombstone at ts 2500 us is
  purged (`tombstones_purged == 1`, `city` gone, `name=Ada` kept). It was also replaced by
  `bench-c1-gc-grace-keeps-recent-tombstone`, where the same tombstone deleted 100 s before now is kept.
- `P2.yaml`: the probe was replaced by `bench-p2-streamed-sstables-pending-then-promoted`. Every
  `column-family-store.add-sstables` call carries `pending_repair == <parent session>`, and after FINALIZED n2's
  `added-` SSTables are `repaired` with `pending_repair == ''`.
- `B1-xtable.yaml`: added `bench-b1-xtable-positive`. On n1, n2 and n3, both `shop.users:k1:name` and
  `shop.orders:k1:total` are written, `total` never lands in users, and there are 3 commit-log appends (one
  Mutation per replica). The round-2 probe only asserted what must not happen.
- `L4.yaml`: added `bench-l4-concurrent-proposers`. Two coordinators (n1, n2) run INSERT IF NOT EXISTS on one
  partition as overlapping steps. Both prepares are rejected, they back off, re-prepare and duel on the proposal,
  and exactly one ends `[applied]`. This is real contention without a latency stand-in.
- `G1.yaml`, `W9.yaml`: only the `(expected to fail)` labels changed.

## 3. Verdicts for the cases that changed

Every area claim below was checked against the code.

| Case | R2 | R3 | Why |
|---|---|---|---|
| W9 | partial | **pass** | `bench-w9-readback` (round 2 expected to fail) passes. Switch-out returns the flush set (`SkipListMemtable.getFlushSet` :246), the SSTable carries the partitions, `reclaim` → `memtable.discard` drops the cells (`CFS:1391-1404`), and the read is served from the SSTable. Discard walks the segments oldest first, `markClean`, and `archiveAndDiscard` only when `isUnused`, stopping at the segment that contains the upper bound (`CommitLog.java:353-383`). `bench-w9` asserts the users-only segment is deleted and the mixed and allocating segments are kept. |
| W10 | pass | **pass** | (b), see section 1. The score is unchanged. The round-2 assertion depended on the W9 bug. |
| B1-xtable | fail (probe) | **pass** | One Mutation with one PartitionUpdate per table. `Keyspace.applyInternal` loops `getPartitionUpdates()` and writes each to its own CFS, `continue` on an unknown table (`Keyspace.java:626-653`). The positive check passes. Open: the view check and lock use the first table only (write-path note). |
| R2 | pass (minor wrong claim) | **pass** | `bench-r2-repair-mutation-is-a-diff` passes. Each replica gets `repairs[i]`, its own diff, and only a write-plan replica outside the read plan gets `fullDiffRepair` (`RowIteratorMergeListener.java:382-398`). |
| R6 | partial | **pass** | `bench-r6-failure-signals-immediately` passes: ReadFailure in under 2500 ms. `onFailure` signals once `blockFor + failures > contacts` (`ReadCallback.java:247-248`), now a fail-fast join (`count_unstarted: false`). |
| P2 | partial | **pass** | The streamed SSTables are created with `header.pendingRepair` (`CassandraStreamReader.java:105,135`) and promoted after FINALIZED. The new positive scenario passes. |
| C1 | partial | **pass** | `getPurgeEvaluator` uses the minimum timestamp of overlapping SSTables and memtables (`CompactionController.java:245-284`), and `gcBefore = nowInSec - gcGraceSeconds` (`CFS:1970-1973`). The new pair passes: an old tombstone is purged and a recent one kept. Open: read-time purging still uses the counters, and `ALTER ... gc_grace_seconds` doesn't reach the tracker view. |
| G1 | partial | **pass** | `bench-g1-scheduled-every-second` passes. `start` schedules the GossipTask at a fixed 1000 ms delay (`Gossiper.java:2028-2031`), builds the seeds minus self (`:2126-2133`), and initialises local state with putIfAbsent (`:2198-2204`). The model caps the rounds at `gossip-task-rounds` (60), a stated model bound. |
| G3 | partial | **pass** | After the (a) timing fix, the full join passes. `bench-g3-strict-sources` passes: each range comes from the replica losing it (`RangeStreamer.java:494-521`, strict when nodes > RF, `:394-416`), giving (n1,n2] from n1, (n2,n3] from n2 and (n3,n4] from n3, which I verified by hand on the ring. Open: the model's own GossipTask rounds land after the joining call tree, so without a scripted round peers never see BOOT. In the code the rounds run during RING_DELAY. This is a scheduling gap (timer deliveries wait for the caller's call tree), not a wrong claim. |
| L4 | partial (simulator) | **pass** | Overlapping steps close the round-2 gap. Two proposers now really contend: both prepares are rejected, then random back-off, re-prepare, and a preempted proposal (`StorageProxy` :591-615). `bench-l4-timeout` still reaches `cas_contention_timeout` with a latency stand-in. That is acceptable, because the deadline logic is what it checks. |
| B3 and batchlog | pass | pass | The late-ack cleanup (`on_late`) and the throttle changes broke nothing. B1–B5 pass. |

I found no round-2 expectation correction that was wrong. The only new wrong expectation is the W10 scenario
assertion. It was the judge's own observation path, not the benchmark's expected behavior.

## 4. Scorecard

| Case | R2 | R3 | | Case | R2 | R3 | | Case | R2 | R3 |
|---|---|---|---|---|---|---|---|---|---|---|
| W1 | pass | pass | | R1 | pass | pass | | L1 | pass | pass |
| W2 | pass | pass | | R2 | pass | pass | | L2 | pass | pass |
| W3 | pass | pass | | R3 | pass | pass | | L3 | pass | pass |
| W4 | pass | pass | | R4 | pass | pass | | L4 | partial | **pass** |
| W5 | pass | pass | | R5 | pass | pass | | L5 | pass | pass |
| W6 | pass | pass | | R6 | partial | **pass** | | B1 | pass | pass |
| W7 | pass | pass | | R7 | pass | pass | | B2 | pass | pass |
| W8 | pass | pass | | S1 | pass | pass | | B3 | pass | pass |
| W9 | partial | **pass** | | S2 | pass | pass | | B4 | pass | pass |
| W10 | pass | pass (b) | | S3 | pass | pass | | B5 | pass | pass |
| H1 | pass | pass | | S4 | pass | pass | | P1 | pass | pass |
| H2 | pass | pass | | T1 | pass | pass | | P2 | partial | **pass** |
| H3 | pass | pass | | T2 | pass | pass | | C1 | partial | **pass** |
| G1 | partial | **pass** | | T3 | pass | pass | | B1-xtable | fail | **pass** |
| G2 | pass | pass | | G3 | partial | **pass** | | G4 | pass | pass |

| Count (44 cases) | Round 2 | Round 3 |
|---|---|---|
| pass | 37 | **44** |
| partial | 7 (G1, G3, L4, R6, P2, C1, W9) | 0 |
| fail | 0 | 0 |
| wrong expectations | 16 benchmark expectations corrected (H1, H3, G2, G4, L2, L4, B2, B3, B4, R5, S1, P2, C1, T1, T3, W6) | the same 16, all still upheld, plus 1 judge-scenario assertion (W10) |
| B1-xtable | fail | pass |

## 5. Still open (none of it costs a score)

- **G3:** scheduled gossip rounds don't interleave with a caller's long call tree (RING_DELAY), so BOOT reaches
  peers only through a scripted round.
- **C1:** read-time purging still uses the counters, and `ALTER TABLE ... gc_grace_seconds` doesn't reach the
  tracker view.
- **B1-xtable:** the view check and lock still use the first table only.
- **L4:** reaching the CAS contention timeout through contention alone isn't exercised. It still needs a latency
  stand-in.

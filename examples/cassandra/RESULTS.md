# Cassandra benchmark results

Can mosaic map Apache Cassandra 5.0.9's workflows correctly from code alone?

## The build

- **Who built it:** 11 area agents worked from code only, under `BRIEF.md`, then ran one
  reconciliation round (`RECONCILE.md`).
- **Merged ontology:** `cassandra.json`, with 502 components, 1,365 interfaces, 270 flows and 1,165
  scenarios.
- **Checks:** 0 validation errors, 0 merge warnings, 1,165 of 1,165 scenarios pass, and all 4,525 code
  citations resolve.
- **Coverage:** 478 of 483 entry points in the inventory that aren't skipped are covered (99%). 870
  are skipped, each with a reason recorded in `inventory.json`; most are JMX getters, metrics and
  offline tools.

## The benchmark

`BENCHMARK.md` lists 44 well-known behaviors, written from docs and common knowledge before the
build. The builders never saw it. Five independent judges (`judge/`) first verified each
expectation against the code, then ran it as a scenario on the merged model without editing the
model, and read the trace to check the code's path.

| Group | Pass | Partial | Sim-gap | Fail |
|---|---|---|---|---|
| Write (W1–W10) | 7 | 1 | 2 | 0 |
| Read (R1–R7) | 3 | 3 | 1 | 0 |
| LWT and batches (L1–L5, B1–B5) | 9 | 1 | 0 | 0 |
| Hints and membership (H1–H3, G1–G4) | 3 | 3 | 0 | 1 |
| Schema, repair, protocol (S1–S4, P1–P2, C1, T1–T3) | 8 | 2 | 0 | 0 |
| **Total (44)** | **30 (68%)** | **10** | **3** | **1** |

No behavior was **missing**. Every one of the 44 was modeled somewhere.

**Root causes of the 14 non-passes:**
- **9 model errors.** Wrong logic in one area.
- **3 contract seams.** Wiring between areas.
- **4 simulator gaps.** Mosaic can't express the behavior yet.

**20 of the 44 benchmark expectations were wrong or imprecise for 5.0.9.** The judges corrected
them from the code. The ontology built from code was more often right about Cassandra than the
benchmark written from docs and common knowledge. For example:
- the deployed compaction default is STCS, not UCS;
- CREATE TABLE doesn't wait for schema agreement;
- hint dispatch is a 10 s poll, not a gossip event;
- decommission with RF equal to the cluster size is refused;
- an LWT back-off is random from 0 to 99 ms, not exponential;
- with the default `99p` speculative retry, one silent replica doesn't cause a read-timeout.

**Trust in the evidence:** spot checks found no bad citations, and confirmed the builders' findings
where the code differs from common knowledge (33 confirmed; 1 refuted, a v1 Paxos commit at ALL).

## What the model gets wrong (to fix)

| # | Area | Wrong claim | Code |
|---|---|---|---|
| 1 | write-path / seed data | `keyspace` only knows `ks1.*`. Writes to `shop.*` from coordination's default flows and from read repair silently skip the commit log and memtable, and the scenarios still pass. "Unknown table" should fail, not skip | `Keyspace.java:624-634` |
| 2 | read-path / coordination | Replicas strip tombstones before they respond, so a newer delete loses on the coordinator and the deleted value is repaired back | `DataResolver.java:315-317` |
| 3 | hints-batchlog | `should-hint` compares epoch ms with simulator time, so after one flushed hint all later hints for that host are refused (H2 fail) | |
| 4 | membership | `endpoint-state-mark-dead` resets the down-since time, which restarts the hint window | |
| 5 | membership / repair-streaming | Decommission streams to `peers: []`. Bootstrap streams from every live node, itself included, and passes no ranges | |
| 6 | paxos | A v1 commit skips `forWrite`'s live-replica check. At ALL with a replica down it should be Unavailable, not a hinted write timeout | `StorageProxy.java:785`, `ReplicaPlans.java:475` |
| 7 | paxos / cql | CAS and SERIAL results come back as raw cells, with no `[applied]` column | |
| 8 | cql / schema-auth | DDL can't be reached from QUERY: `process-statement` aborts on `CREATE_TABLE` | |
| 9 | repair-streaming / read-path | Incremental repair never marks pending-repair SSTables or promotes them after FINALIZED | `RepairFinishedCompactionTask` |
| 10 | write-path / read-path | A flush never submits background compaction. STCS picks the first bucket, not the hottest | |
| 11 | read-path | Tombstone warnings never reach the client (`ClientWarn.warn`). Equal-timestamp merges don't use `Cells.reconcile` | `ReadCommand.java:631` |
| 12 | write-path | The unknown-table check runs before the commit log append. Down replicas get one HintRunnable each instead of one for all. Startup replay is passed an empty segment list | `StorageProxy.java:1563` |

## Simulator gaps (the mosaic roadmap from this benchmark)

Ranked by how many areas and judges hit each one:

1. **Concurrent fan-out with "wait for k of n, or a deadline".** It exposed W4, W5, R4 and L4, and
   every area builder hit it. A QUORUM write with two hung replicas takes 4,082 ms instead of
   2,000 ms, and speculation can't fire for a slow replica that still answers.
2. **Request deadlines.** `timeout_ms` is a literal per call, not a deadline from the request start,
   so responses after the deadline are accepted.
3. **Stub response overrides in scenarios.** Today a branch that depends on another area's answer
   needs a choice.
4. **Multi-step scenarios.** A sequence of entry calls sharing state: PREPARE then EXECUTE (T1),
   login (S4), gossip rounds then a dispatch tick.
5. **Per-node state, or instances.** One state per component means there is only the coordinator's
   gossip view, so SYN, ACK and ACK2 and schema agreement across nodes can't be followed.
6. **Expectation access to call inputs and call order.**
7. **CEL helpers.** Building a map from a list, sum, deleting a map key.
8. **Seeded random choice, rate limiters, and an initial delay on repeated flows.**

## Files

- `skeleton.yaml`, `BRIEF.md`, `RECONCILE.md`, `inventory.json`, `fragments/`, `notes/`, `skips/`.
- `cassandra.json`, the merged ontology.
- `BENCHMARK.md`, the original expectations.
- `judge/<group>.md` and `judge/<group>.json`, the per-case verdicts with corrected expectations.
- `judge/scenarios/`, 91 benchmark scenarios. 84 pass. The 7 that fail on purpose assert the code's
  behavior where the model is wrong or the simulator falls short.

---

# Round 2: after the generic language additions (DESIGN §11–13)

The model was migrated onto instances, `parallel` joins, deadlines, configs, shared fixtures
(`fixtures.yaml`) and multi-step scenarios, and the round 1 wrong claims were fixed
(`MIGRATE.md`). Fresh judges then re-scored it independently (`judge/v2/`).

## The build

- **Size:** 509 components, 1,426 interfaces, 292 flows and 1,571 scenarios, all passing.
- **Citations:** all 5,099 resolve (including 347 config citations).
- **Quality gate:** 0 mocks, 0 failing hollow-lint findings (137 advisory), and 99% inventory
  coverage.
- **Behavior coverage:** 92.7% of behavior steps run in some scenario, up from 88.0%. Per area
  it ranges from 83.1% (ops) to 99.8% (write-path).

## The benchmark

| Group | Round 1 | Round 2 |
|---|---|---|
| Write | 7 pass, 1 partial, 2 sim-gap | 9 pass, 1 partial |
| Read | 3 pass, 3 partial, 1 sim-gap | 6 pass, 1 partial |
| LWT and batches | 9 pass, 1 partial | 9 pass, 1 partial |
| Hints and membership | 3 pass, 3 partial, 1 fail | 5 pass, 2 partial |
| Schema, repair, protocol | 8 pass, 2 partial | 8 pass, 2 partial |
| **Total (44)** | **30 pass (68%)**, 10 partial, 3 sim-gap, 1 fail | **37 pass (84%)**, 7 partial, 0 sim-gap, 0 fail |

All of round 1's sim-gaps (W4, W5, R4) now pass:
- the write timeout fires at 2000 ms;
- an ack at consistency ONE returns on the first replica;
- speculation fires while the slow replica is still answering.

Round 1's fail (H2, the clock bug) passes. Every round 1 expectation correction re-checked as right.

## Still wrong (round 2 findings, to fix)

| Area | Wrong claim |
|---|---|
| write-path | A flush leaves the cells in the memtable, so reads never touch the flushed SSTable (W9). Commit log discard uses a segment counter, while the code deletes only unused segments (`CommitLog.java:366-370`) |
| cql or write-path | A batch writing two tables on the same partition key merges into the first table, so nothing reaches the second |
| coordination | A tombstone-overwhelmed replica's failure waits for the pending speculative branch: ReadFailure at 2522 ms instead of about 39 ms (R6). Read repair sends the whole merged partition instead of each replica's diff |
| read-path / repair-streaming | SSTables streamed in during incremental repair aren't marked pending repair (P2). gc_grace isn't evaluated when purging tombstones (C1) |
| membership | Bootstrap streams from the first natural replica instead of the one losing the range (G3, `RangeStreamer.java:494-521`). `gossiper.start` cites scheduling, seed building and own-state creation that it doesn't model (G1). Live peers are read from `live_endpoints`, not the `alive` flag |
| fixtures | n1 is in its own seed list; the code excludes self |

## Simulator gaps still open

1. **Fail-fast joins.** A join can't fail on a failure count while a staggered branch is still
   pending (R6). The code fails as soon as the consistency level is unreachable.
2. **Late replies.** Branch results that arrive after the join completes are invisible to
   follow-up work, such as batchlog cleanup reacting to late acks.
3. **Overlapping steps.** Steps can't overlap a running step, so peers can't gossip during
   RING_DELAY. Also, an early `at_ms` is clamped **without** the warning §13.1 item 3 requires.
4. **Interleaved state.** Shared state isn't interleaved between concurrent branches.
5. **Concurrent proposers.** There are no concurrent competing callers, which L4's contention needs.
6. **Fixtures can't delete keys,** and the check tool can't print state maps.

# Round 3 (fix round, `FIXES.md`)

7 area agents fixed the round-2 findings: write-path, cql, coordination, repair-streaming,
read-path, membership and hints-batchlog. The round followed the same rules as the VS Code round:
- **Breaking changes are welcome:** a change that makes an interface match the code is welcome
  even if it breaks callers. The owner lists the callers it breaks.
- **Overlap is explicit:** steps overlap only with `at_ms` or `await: false` (DESIGN §13.1 item 14,
  revised).

## The gate (`quality-gate.txt`)

| Check | Round 2 | Round 3 |
|---|---|---|
| Scenarios | 1,571 | **1,591** (all pass) |
| Citations resolving | — | 5,159 / 5,159 |
| Entry points modeled / substantive | 92% / 87% | 92% / 87% |
| Trivial entry interfaces | 15.5% | 15.5% |
| Hollow-lint failures | 0 | 0 |

## The benchmark (`judge/v2/round3.md`)

| | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| Pass | 30 / 44 | 37 / 44 (7 partial) | **44 / 44** |
| B1-xtable (added in round 2) | — | fail | pass |

All 102 judge scenarios pass.

**Fixes, each checked against the code by the judge:**
- **W9:** a flush moves the memtable's cells into the SSTable, and reads follow them.
- **Commit log:** only unused segments are discarded.
- **B1-xtable:** a batch keeps one update per table.
- **R6:** a fail-fast join, `count_unstarted: false`.
- **R2:** read repair sends per-replica diffs.
- **P2:** streamed SSTables carry `pending_repair` all the way to the tracker.
- **C1:** tombstones are purged by `gc_grace_seconds` and overlap.
- **G1:** gossip starts with seeds that exclude the node itself, and the GossipTask is scheduled.
- **G3:** bootstrap streams each range from the replica that is losing it.
- **Batchlog:** late acks go through `on_late`, and replay uses Guava's rate limiter.

**The judge adapted these cases:**
- **C1 and P2 probes:** they asserted the old gaps, so they now fail as expected. They were
  replaced with positive checks, because the main scenarios didn't test either fix.
- **G3 end-to-end:** membership's GossipTask now runs by default, as the code does
  (`Gossiper.java:2028-2031`). The injected BOOT and the write moved inside RING_DELAY. Only
  timing changed.
- **W10 (wrong expectation):** startup replay flushes into an SSTable
  (`CommitLogReplayer:244-270`). The old memtable check passed only because of the W9 bug.
- **Added cases:** a B1-xtable positive check and a two-proposer L4 contention case.

The judge saw the fixes, so this is not a blind score.

## Breaking changes (listed by their owners)

- **coordination:** read repair takes `mutations: [{replica, mutation}]`.
- **write-path:** `archive-and-discard` takes one segment. Reads after a flush go to the SSTable.
- **hints-batchlog:** the requests for `on-response`, `ack-mutation` and `replay` changed.
- **Mid-round contract race:** write-path changed the `WritePathMutation.updates` rule while cql
  was mid-edit, which broke B1's read-back until cql followed.

Every caller was in its owner's own fragment, or was fixed.

## Still open (no score impact)

- **G3:** a plain startup never delivers BOOT to peers without a scripted gossip round.
- **C1:**
  - read-time purging still uses precomputed counts;
  - `ALTER ... gc_grace_seconds` doesn't reach the compaction view (schema-auth).
- **R2:** real Cassandra merges only the unacked diffs into speculated writes.
- **B1-xtable:** the view check and the lock use the first table only.
- **L4:** the contention timeout needs a latency stand-in.
- **cql:** 24 advisory hollow warnings, on DESCRIBE and SELECT scenarios.

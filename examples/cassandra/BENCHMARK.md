# Cassandra benchmark: does the generated ontology map Cassandra's workflows correctly?

The builders never see this file. It lists well-known Cassandra 5.0 behaviors, each written so it
can be run as a mosaic scenario against the merged ontology (`examples/cassandra/cassandra.json`).

**Verify each case against the code before scoring it.** The expectations below come from
Cassandra's documentation and common knowledge, and either can be wrong for 5.0.9 with the
deployed `conf/cassandra.yaml`. A judge first confirms or corrects each expectation, citing code
(and, for the record, docs or tests under `test/unit` or `test/distributed`). Only then is the
ontology scored against the corrected expectation.

The default cluster is 3 nodes in one DC, RF 3, the coordinator `n1` also a replica, and the
deployed config.

## Scoring per case

- **pass**: a scenario run on the merged ontology reproduces the verified outcome, and the trace
  takes the code's path: the right components, verbs and decisions.
- **partial**: the outcome is right, but the path is wrong or incomplete. Or the behavior is
  modeled, but no scenario can drive it without editing the ontology.
- **fail**: the ontology produces a different outcome.
- **missing**: the behavior isn't modeled.
- **sim-gap**: the ontology models it as well as mosaic allows, but the simulator can't express it.
  Name the missing feature.

Write a scenario for each case under `judge/scenarios/<case>.yaml`. Use only inputs, `state`,
`choices` and `faults`; never edit the ontology. If the ontology needs an edit before it can run
the case, score it partial at best and say what the edit would be.

## Write path

| ID | Behavior | Expected outcome |
|---|---|---|
| W1 | INSERT at QUORUM, all replicas up | success; MUTATION_REQ to the two remote replicas, local apply on n1; acknowledged after 2 acks |
| W2 | INSERT at QUORUM, one replica down (failure detector) | success; the down replica gets a hint (hinted handoff enabled, within max_hint_window) |
| W3 | INSERT at QUORUM, two replicas down | `unavailable` (protocol 0x1000) **before** any mutation is sent; no hints written |
| W4 | INSERT at QUORUM, replicas alive per the FD but two don't respond | `write-timeout` (0x1100) after write_request_timeout (2000ms); `received` 1 of `blockFor` 2; write type SIMPLE; hints for the non-responders |
| W5 | INSERT at ONE, one replica times out | success after the first ack; a hint for the slow replica |
| W6 | INSERT at ANY, all replicas down | success; a hint is stored on the coordinator, which counts for ANY |
| W7 | INSERT at ALL, one replica down | `unavailable` |
| W8 | Local apply order on a replica | commit log append before the memtable update; the write is acknowledged without waiting for fsync under periodic sync (10000ms) |
| W9 | Memtable flush | a flush writes an SSTable to the data directories and discards commit log segments up to the flush position |
| W10 | Commit log replay at startup | unflushed mutations in the segments are reapplied to the memtables before the node serves traffic |

## Read path

| ID | Behavior | Expected outcome |
|---|---|---|
| R1 | SELECT at QUORUM, all up | one full data read plus digest reads, enough to reach blockFor 2; result returned when the digests match |
| R2 | SELECT at QUORUM, digest mismatch | full data reads from the contacted replicas; the newest-timestamp value wins; blocking read repair sends the merged mutation to stale replicas before responding |
| R3 | SELECT at QUORUM, two replicas down | `unavailable` |
| R4 | SELECT at ONE, the chosen replica slow | speculative retry (table default `99p`) sends an extra request to another replica; returns its response |
| R5 | SELECT at QUORUM, a replica doesn't respond | `read-timeout` (0x1200) after read_request_timeout (5000ms), with `received` < blockFor and `data_present` reported |
| R6 | Tombstones over the thresholds | a warning past `tombstone_warn_threshold` (1000); `TombstoneOverwhelmingException`, a `read-failure` to the client, past `tombstone_failure_threshold` (100000) |
| R7 | Local read merges sources | a single-partition read merges the memtable(s) and the SSTables (after filtering by bloom filter and key range); the newest cell wins and tombstones shadow older cells |

## Lightweight transactions

| ID | Behavior | Expected outcome |
|---|---|---|
| L1 | `INSERT ... IF NOT EXISTS`, no contention | Paxos (v1 by default `paxos_variant`): prepare and promise from a quorum, read, propose and accept from a quorum, commit; `[applied]` true |
| L2 | `UPDATE ... IF col = x`, condition false | `[applied]` false with the current values; no proposal is accepted |
| L3 | LWT with two replicas down | `unavailable` for SERIAL |
| L4 | LWT under contention | prepare is rejected by a higher ballot; the coordinator retries with backoff until `cas_contention_timeout` (1000ms), then `write-timeout` with write type CAS |
| L5 | SERIAL read | runs a Paxos round, completing any in-progress proposal before returning |

## Batches

| ID | Behavior | Expected outcome |
|---|---|---|
| B1 | LOGGED batch across partitions, all up | the batchlog is written to 2 other nodes (in other racks when possible) before the mutations; the batchlog entry is removed after success |
| B2 | LOGGED batch, a replica down | the batch still succeeds at the CL; the down replica gets hints; replay later covers any failure |
| B3 | Batchlog replay | `BatchlogManager` replays batches older than the timeout on a fixed schedule (every 10s by default), throttled by `batchlog_replay_throttle` |
| B4 | Batch over `batch_size_fail_threshold` (50KiB) | refused with `invalid` (InvalidRequestException); over warn (5KiB) only a client warning |
| B5 | UNLOGGED batch | no batchlog; the mutations are sent directly |

## Hints

| ID | Behavior | Expected outcome |
|---|---|---|
| H1 | Hint dispatch when the node comes back | the gossip or FD state change to UP triggers dispatch of that node's hint files; hints are deleted after delivery |
| H2 | Node down longer than max_hint_window (3h) | no new hints are written for it |
| H3 | hinted_handoff_enabled false | no hints; the write outcome is otherwise unchanged |

## Membership

| ID | Behavior | Expected outcome |
|---|---|---|
| G1 | Gossip round | every second, gossip to one random live endpoint, maybe one unreachable endpoint, and maybe a seed; SYN → ACK → ACK2 exchanges digests and states |
| G2 | Failure detection | phi accrual (`phi_convict_threshold` 8) marks an endpoint DOWN; subscribers (hints, StorageService) are notified |
| G3 | Bootstrap | a new node gossips its tokens, streams its ranges from existing replicas while pending writes go to it as well, then becomes NORMAL |
| G4 | Decommission | the node streams its data to new owners, then hints, then leaves the ring (LEFT) |

## Schema and auth

| ID | Behavior | Expected outcome |
|---|---|---|
| S1 | CREATE TABLE | applied locally, then pushed to the other nodes as a schema mutation; schema version agreement via gossip |
| S2 | CREATE TABLE that exists | `already-exists` (0x2400) unless `IF NOT EXISTS` |
| S3 | Login with the deployed authenticator | AllowAllAuthenticator: no AUTHENTICATE challenge; STARTUP returns READY |
| S4 | PasswordAuthenticator, bad password | `bad-credentials` (0x0100) |

## Repair and compaction

| ID | Behavior | Expected outcome |
|---|---|---|
| P1 | `nodetool repair -full` on a keyspace | per range: a validation compaction builds Merkle trees on each replica, the trees are compared, and mismatching ranges are synced by streaming |
| P2 | Incremental repair (the default) | prepare and anticompaction mark the repaired SSTables; then validation and sync; finalize promotes them |
| C1 | Compaction trigger | after a flush, the strategy (UnifiedCompactionStrategy is the 5.0 default? verify against `cassandra.yaml` and the table defaults) picks candidates; the compaction merges SSTables and purges droppable tombstones after gc_grace_seconds |

## Protocol

| ID | Behavior | Expected outcome |
|---|---|---|
| T1 | EXECUTE with an unknown prepared id | `unprepared` (0x2500); the driver re-prepares |
| T2 | QUERY with a syntax error | `syntax-error` (0x2000) |
| T3 | Overloaded native transport | `overloaded` (0x1001) when rate limits or byte limits are exceeded (if enabled by the deployed config) |

# Judge report, round 2: schema-repair-protocol (S1–S4, P1–P2, C1, T1–T3)

Model: the migrated `examples/cassandra/cassandra.json` (509 components, 1,426 interfaces, 292 flows,
1,571 scenarios). Code: Cassandra 5.0.9 at `/home/lbethay/.cache/cassandra-bench/cassandra-5.0.9`. All
code paths below are relative to `src/java/org/apache/cassandra/` unless they start with `conf/`.

Scenarios: `judge/v2/scenarios/{S1..S4,P1,P2,C1,T1..T3}.yaml`, 29 `bench-*` scenarios. They all use the
shared fixtures (`three-node-rf3`, `one-node`, `auth-users`) and declare no mocks. All 29 pass with
`check --no-mocks --scenario '^bench' --trace`, and I read each trace to confirm the path (instance,
component, verb, decision). Three of them are probes that pin down a wrong claim (they pass because the
model does the wrong thing). Their names say so.

Totals: **8 pass, 2 partial, 0 fail, 0 missing, 0 sim-gap.**

Independence note: I opened round 1's report to read its "verified expectation" column. That column
shares a table row with the scores, so I saw round 1's scores before I ran my scenarios. I scored every
case from my own runs and traces. Where I agree with round 1 (P2 and C1 partial), it is for a
different reason.

## 1. Cases

| ID | Verified expectation (corrected?) | Score | Root cause | Evidence |
|---|---|---|---|---|
| S1 | Round 1's clarification holds (re-checked). `DefaultSchemaUpdateHandler.apply` (synchronized) applies the transformation, then `convertSchemaDiffToMutations`, `SchemaKeyspace.applyChanges`, a new digest, `updateSchema` (merge, then `announce` puts SCHEMA into gossip), then an **async** `pushSchemaMutations` on the migration executor (`schema/DefaultSchemaUpdateHandler.java:228-271`). The push goes to `gossiper.getLiveMembers()` filtered by `shouldPushSchemaTo` (known, current messaging version), with no callback (`schema/MigrationCoordinator.java:747-777`). The client gets SCHEMA_CHANGE with no server-side wait for agreement. A peer that misses the push hears the SCHEMA version in gossip and pulls. A running node postpones the pull by MIGRATION_DELAY (60 s) (`MigrationCoordinator.java:402-416,549-570`) | **pass** | – | `bench-s1-native-ddl`: a CREATE TABLE QUERY goes through `query-processor.process-statement` → `alter-schema-statement.execute@n1` → `default-schema-update-handler.apply` → `apply-changes` → `init-cf@n1` → `announce` → `gossiper.add-local-application-state`. The emit then pushes to `schema-push-verb-handler.do-verb@n2` and `@n3`, and all three nodes end with the same schema version. `bench-s1-no-wait-for-agreement`: both pushes fail and the client still gets SCHEMA_CHANGE. `bench-s1-peer-down`: only n2 is pushed to. `bench-s1-pull-converges` (multi-step): the push to n3 fails, n3's `on-change(SCHEMA)` at 1 s postpones, `pull-schema@n3` runs at 61,011 ms, `schema-pull-verb-handler.do-verb@n1` answers, and n3 converges |
| S2 | Confirmed (re-checked). `CreateTableStatement.apply` throws AlreadyExistsException (0x2400) before any schema write. IF NOT EXISTS returns the unchanged keyspaces, so the diff is empty, `apply` returns early (`DefaultSchemaUpdateHandler.java:234-235`) and the result is Void | **pass** | – | Both scenarios go over native QUERY. `bench-s2`: already-exists 9216 with the exact message, and `apply-changes`, `announce`, `push` and `init-cf` are all 0. `bench-s2-if-not-exists`: RESULT/VOID and nothing written |
| S3 | Confirmed. `conf/cassandra.yaml:198` sets `authenticator: AllowAllAuthenticator`. `StartupMessage.execute` returns `ReadyMessage` when `requireAuthentication()` is false (`transport/messages/StartupMessage.java:122-126`) | **pass** | – | `bench-s3` (STARTUP, then QUERY): READY, connection stage READY, user `anonymous`, no AUTH_RESPONSE and no `password-authenticator*` call. The following QUERY returns RESULT |
| S4 | Confirmed (not the deployed config). STARTUP → AUTHENTICATE. AUTH_RESPONSE → `evaluateResponse` → `authenticate` → `cache.get` (`queryHashedPassword`, with roles read at LOCAL_QUORUM per `config/Config.java:753`) → `checkpw` fails → AuthenticationException "Provided username %s and/or password are incorrect" = BAD_CREDENTIALS 0x0100 (`auth/PasswordAuthenticator.java:140-168`) | **pass** | – | `bench-s4` (multi-step, `auth-users` fixture, wrong password as input, no fault): AUTHENTICATE with the PasswordAuthenticator class name, then bad-credentials 256 with the exact message, on the auth executor. The role is read through `select-statement.execute` → `storage-proxy.read`. `client-state.login` is 0 and the stage stays AUTHENTICATING. `bench-s4-good-password`: logged in, READY |
| P1 | Confirmed (re-checked). nodetool sends PARALLEL by default (`tools/nodetool/Repair.java:171-176`), so there's no snapshot. `paxos_variant` is v1 (`config/Config.java:1051`), so there's no paxos repair (`repair/RepairJob.java:128`). Then PREPARE to the neighbours, validation on all 3 replicas (the local tree is answered locally, `repair/Validator.java:284-300`), sync tasks per differing pair, streaming, and cleanup. A dead neighbour fails the prepare unless the repair is forced and full (`service/ActiveRepairService.java:685-700`) | **pass** | – | `bench-p1` (n3 diverged): prepare on n2 and n3, validation on n1, n2 and n3 (now a `parallel` join in `repair-job.run`), no snapshot, no paxos cleanup, 2 sync tasks (1 local, 1 symmetric remote), 2 stream plans, 2 cleanups, no consistent-repair messages. `bench-p1-in-sync`: no sync, no stream. `bench-p1-replica-down`: the session fails before validation |
| P2 | Round 1's correction holds (re-checked). Anticompaction rewrites the SSTables as UNREPAIRED with `pendingRepair = session` (`db/compaction/CompactionManager.java:866-871`). Streamed SSTables are written with the session's pendingRepair too (`db/streaming/CassandraStreamReader.java:105,135`; `CassandraEntireSSTableStreamReader.java:137`). After FINALIZE_COMMIT, `PendingRepairManager` → `RepairFinishedCompactionTask` → `mutateRepaired(repairedAt, NO_PENDING_REPAIR)` promotes them (`db/compaction/PendingRepairManager.java:270-276,524-532`) | **partial** | model | `bench-p2`: PREPARE_CONSISTENT ×3, `pending-anti-compaction.run` ×3, `submit-pending-anti-compaction@n2`, validation ×3, 2 sync tasks, 2 streams, FINALIZE_PROPOSE and COMMIT ×3, local and coordinator sessions FINALIZED. Then `local-sessions.session-completed` → `submit-background@n2` → `pending-repair-manager.get-next-repair-finished-task` → `repair-finished-compaction-task.run-may-throw@n2`, which promotes u-1 and u-2 (`ctx.repair_finished == 'promoted'`). `bench-p2-pending-before-finalize`: anticompaction marks `pending_repair = s-1`, `repaired = false`. **But** `bench-p2-probe-streamed-not-pending`: the SSTable streamed into n2 during sync is added by `column-family-store.add-to-tracker` with `repaired: false` and no `pending_repair`, so it stays unrepaired after FINALIZED (wrong claim 1). Edit: `cassandra-stream-receiver.finished` should pass the stream session's pending repair id through `add-sstables` and `add-to-tracker` |
| C1 | Round 1's correction holds (re-checked). The deployed default is **STCS**: `default_compaction` is commented out (`conf/cassandra.yaml:1205-1213`) and `CompactionParams.DEFAULT` falls back to STCS (`schema/CompactionParams.java:90-100`). `replaceFlushed` calls `submitBackground` when the flush added SSTables (`db/ColumnFamilyStore.java:1834-1839`). STCS takes the hottest bucket of at least 4. The compaction purges tombstones whose local deletion time is before `gcBefore = now - gc_grace_seconds` (864000) and which shadow nothing outside the compaction (`db/compaction/CompactionController.java:245-284`, `ColumnFamilyStore.gcBefore` :1970) | **partial** | model | `bench-c1-flush-triggers-stcs`: a dirty flush on n1 adds a 4th SSTable, "replaceFlushed submits a background compaction check", and STCS compacts the 4 into 1. That is the round 1 seam, now fixed. `bench-c1-stcs-purge`: 4 → 1 (42 MB), 50 tombstones purged, resubmit, recheck finds nothing. `bench-c1-below-threshold`: nothing compacts. **But** `bench-c1-probe-gc-grace-not-evaluated`: a cell tombstone with timestamp 2500 (decades before the fixture clock), in a partition fully covered by the 4 inputs, survives the compaction with `tombstones_purged == 0`. The purge is a precomputed per-SSTable `purgeable_tombstones` count, and the merged cells are never filtered by age (wrong claim 2). Edit: compute purgeability in `compaction-task.execute` from each tombstone's deletion time against `now - gc_grace_seconds` (a table parameter, 864000 by default) and the minimum timestamp of overlapping SSTables, and drop those cells from the merged partition |
| T1 | Round 1's correction (scope) holds (re-checked). `ExecuteMessage.execute`: `getPrepared` returns null → PreparedQueryNotFoundException = UNPREPARED 0x2500, before the page-size check (`transport/messages/ExecuteMessage.java:131-157`). The re-prepare is driver behavior, not server behavior | **pass** | benchmark (re-prepare is client-side) | `bench-t1`: unprepared 9472, `process-prepared` = 0. `bench-t1-before-page-size`: still unprepared with page_size 0. `bench-t1-reprepare-then-execute` (multi-step): EXECUTE → UNPREPARED, PREPARE → PREPARED with the md5 id, EXECUTE with that id → RESULT and one `process-prepared` |
| T2 | Confirmed. `QueryProcessor.parse` → `CQLFragmentParser.parseAnyUnhandled` → `throwFirstSyntaxError` → SYNTAX_ERROR 0x2000 (`cql3/CQLFragmentParser.java:80`) | **pass** | – | `bench-t2` (input `SELEC ...`, no fault): syntax-error 8192 "no viable alternative at input 'SELEC'", `query-processor.process` = 0. The grammar is a first-keyword regex (an abstraction) |
| T3 | Round 1's correction holds (re-checked). Deployed config: `native_transport_rate_limiting_enabled` false, `native_transport_throw_on_overload` false (v5 falls back to it when the client sends no THROW_ON_OVERLOAD, `transport/PipelineConfigurator.java:309-314`). A bytes-in-flight breach then means backpressure, not `overloaded`. `overloaded` (0x1001) comes only with THROW_ON_OVERLOAD and a breach (`transport/CQLMessageHandler.java:198-203`), from a queue wait over `native_transport_timeout` of 12 s (`transport/Dispatcher.java:364-367`), or on shutdown (`Dispatcher.java:105-110`) | **pass** | benchmark | Six scenarios, now asserting the §11.6 configs: default backpressure (paused, warning, processed); throw-on-overload → overloaded 4097, not dispatched; rate limiter ignored when disabled; rate limiting enabled with throw → overloaded; queue timeout → "Query timed out before it could start"; shutting down → overloaded |

## 2. Comparison with round 1

| Case | Round 1 | Round 2 | Change | Why |
|---|---|---|---|---|
| S1 | pass | pass | unchanged score, better model | DDL is now reachable from native QUERY (`process-statement` routes DDL to `alter-schema-statement.*` and role statements to theirs). The SCHEMA gossip state no longer warns. With instances and steps, push, miss, gossip, postponed pull and convergence run in one scenario across n1–n3 |
| S2 | pass | pass | unchanged | Now driven over native QUERY rather than the standalone `create-table` entry |
| S3 | pass | pass | unchanged | – |
| S4 | pass | pass | unchanged | Now a real STARTUP → AUTH_RESPONSE session on the `auth-users` fixture. The model's own scenario `auth-response-bad-credentials` still uses a fault, but input alone drives it |
| P1 | pass | pass | unchanged | Validation now runs as a `parallel` join. The `not_found` round 1 saw (wrong replica key on the SYNC_REQ receiver) is gone: stats are per instance now, and `not_found` just means a clean memtable |
| P2 | partial | partial | **improved**, still partial | Fixed: anticompaction marks the tracker's SSTables `pending_repair`, and `PendingRepairManager` / `RepairFinishedCompactionTask` promote them after FINALIZED. Still wrong: streamed SSTables aren't marked pending, so they stay unrepaired |
| C1 | partial | partial | **improved**, still partial for a different reason | Fixed: the flush triggers `submit-background` and the new SSTable enters `tracker.views`, and STCS takes the hottest bucket (round 1's claim 4). Still wrong: the gc_grace rule isn't evaluated. Round 1 called this a simulator gap. §11.3's clock (`now` from an epoch) makes it expressible, so it is now a model gap |
| T1 | pass | pass | unchanged | The re-prepare loop now runs as a multi-step scenario |
| T2 | pass | pass | unchanged | – |
| T3 | pass | pass | unchanged | Config values are now entities (`native-transport-*` configs), and scenarios override them with `config:` instead of state |

## 3. Wrong claims found in the model

1. **Streamed SSTables in an incremental repair aren't pending (P2).** `column-family-store.add-to-tracker`
   builds every new SSTable with `repaired: false` and no `pending_repair`. `cassandra-stream-receiver.finished`
   → `column-family-store.add-sstables` doesn't pass the session's pending repair id. In the code the receiving
   writer gets `header.pendingRepair` (`db/streaming/CassandraStreamReader.java:105,135`,
   `CassandraEntireSSTableStreamReader.java:137`). So `PendingRepairManager` promotes the streamed data along with
   the anticompacted data. In the model it stays unrepaired and would be streamed again by the next incremental
   repair. Probe: `bench-p2-probe-streamed-not-pending`.
2. **gc_grace is narrated, not evaluated (C1).** `compaction-task.execute` says "tombstones older than gc_grace that
   shadow nothing elsewhere are purged; gcBefore = now - gc_grace_seconds". It actually sums a precomputed
   `purgeable_tombstones` per SSTable, and keeps every deleted cell in the merged partitions unless
   `ignore_gc_grace` is set. The SSTable counter and the data can disagree. The model's own
   `background-compaction-then-read` seeds nb-4 with `purgeable_tombstones: 10`, yet its only tombstone survives.
   `gc_grace_seconds` isn't a config or table state. Code: `db/compaction/CompactionController.java:245-284`,
   `db/ColumnFamilyStore.java:1970`. Probe: `bench-c1-probe-gc-grace-not-evaluated`.
3. **Contract note, unchanged from round 1.** `gossiper.get-live-members` reads `live_endpoints`. Marking a peer
   down only through `endpoint_state_map.<ep>.alive` still pushes schema to it. The code keeps the two consistent
   (`markDead` updates `liveEndpoints`), so this is a redundant state contract, not wrong code. Scenarios must set
   both keys, as `bench-s1-peer-down` does.

Round 1's claims 1 (DDL unreachable from QUERY), 2 (no pending/promotion), 3 (flush doesn't trigger
compaction), 4 (STCS first bucket rather than hottest), 5 (SCHEMA rejected by the gossip enum) and 6 (wrong
replica key in the streaming flush) are all **fixed**.

Citation sample (`--cite-sample 12 --seed 22`): all 5,099 citations resolve. 12 of 12 support their claims:
AlterTableStatement drop-column, CassandraDaemon populateTokenMetadata and virtual keyspaces, PaxosPrepare
MAYBE_FAILURE, SetConcurrentCompactors, setLoggingLevel, StreamSession.onError, SnapshotManager cleanup
scheduling, registerParentRepairSession, the AlterRole superuser check, relocateSSTables and
NativeTransportService.stop. I also read the behaviors my traces ran next to their code:
`DefaultSchemaUpdateHandler.apply/updateSchema`, `MigrationCoordinator.pushSchemaMutations/shouldPushSchemaTo/
scheduleSchemaPull/shouldPullImmediately`, `CreateTableStatement.apply`, `QueryProcessor.processStatement`,
`StartupMessage.execute`, `PasswordAuthenticator.authenticate`, `ActiveRepairService.prepareForRepair`,
`CompactionManager` anticompaction, `PendingRepairManager` repair-finished task, `ColumnFamilyStore.replaceFlushed`,
the `CQLMessageHandler` overload branches and `Dispatcher` queue timeout and shutdown. Apart from the two wrong
claims above, they are faithful.

## 4. Builder findings (notes' "docs or common knowledge vs code")

Confirmed (re-checked in round 2):
- schema-auth: DDL doesn't wait for agreement, and a lost push is repaired by a pull postponed by MIGRATION_DELAY (`DefaultSchemaUpdateHandler.java:244-250`, `MigrationCoordinator.java:549-570`).
- schema-auth: role and permission statements under AllowAllAuthenticator fail with "You have to be logged in and not anonymous to perform this request" (`service/ClientState.java:586`, `CreateRoleStatement.java:78`).
- schema-auth: auth reads at LOCAL_QUORUM and writes at EACH_QUORUM (`Config.java:753-754`), and `cassandra` uses QUORUM (`CassandraRoleManager.java:99`).
- repair-streaming: nodetool sends `parallel`, incremental unless `--full` (`tools/nodetool/Repair.java:171-178`). No paxos repair under v1 (`RepairJob.java:128`). The coordinator answers its own validation locally (`Validator.java:284-300`).
- transport: on v5 an absent THROW_ON_OVERLOAD falls back to `native_transport_throw_on_overload` (`PipelineConfigurator.java:309-314`). Shutdown reports OVERLOADED (`Dispatcher.java:105-110`).
- read-path: the default compaction is STCS (`conf/cassandra.yaml:1205-1213`, `CompactionParams.java:90-100`).

Refuted: none.

## 5. Simulator gaps

Resolved by DESIGN §11:
- **Cross-node eventual convergence (S1)**: resolved by instances (§11.1), multi-step scenarios (§11.7) and timers (§11.3). `bench-s1-pull-converges` runs push → miss → gossip → postponed pull at +60 s → agreement.
- **Client sessions of different messages (S4, T1)**: resolved by multi-step scenarios (§11.7).
- **Parallel repair (P1, P2)**: resolved by `parallel` with a join (§11.2). `repair-job.run` uses it.
- **Time-based purgeability (C1)**: now expressible with the clock (§11.3). What remains is a model gap (wrong claim 2), not a simulator gap.
- **Configs (T3)**: `config:` overrides (§11.6) replace the old state flags.

Still open:
- **Interleaved shared state across concurrent branches** (§11.2: branches run in list order). In P1/P2 the validations and syncs on different nodes touch disjoint per-instance state, so it doesn't change any outcome in this group. It would matter for a repair racing a compaction on the same node.
- **Parser fidelity (T2)**: the ANTLR grammar is a first-keyword regex (`SELECT FROM` parses). This is a model abstraction rather than a missing simulator feature, but the simulator has no grammar or parse primitive that would make it cheap to fix.
- **Merkle trees (P1)**: one digest per replica and table, not per range. This is a model abstraction. Maps with `parallel` could express per-range trees.

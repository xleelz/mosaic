# Judge report: schema-repair-protocol (S1–S4, P1–P2, C1, T1–T3)

Model: `examples/cassandra/cassandra.json` (merged). Code: Cassandra 5.0.9 at
`/home/lbethay/.cache/cassandra-bench/cassandra-5.0.9`. All paths below are relative to that checkout.
Scenarios: `judge/scenarios/{S1..S4,P1,P2,C1,T1..T3}.yaml`, 21 scenarios (`bench-*`). All pass with
`check --scenario '^bench-' --trace`, and I read each trace to confirm the path.

Totals: **8 pass, 2 partial, 0 fail, 0 missing, 0 sim-gap.** I corrected 5 expectations.

## 1. Cases

| ID | Verified expectation (corrected?) | Score | Root cause | Evidence |
|---|---|---|---|---|
| S1 | **Clarified (counted as corrected).** `AlterSchemaStatement.execute` → `Schema.transform` → `DefaultSchemaUpdateHandler.apply` (synchronized): the statement applies itself, `convertSchemaDiffToMutations`, `SchemaKeyspace.applyChanges` (local system_schema), a new digest, then `updateSchema` (merge, then `announce` puts the version in gossip `SCHEMA`), then an **async** `pushSchemaMutations` with SCHEMA_PUSH_REQ to `gossiper.getLiveMembers()` whose messaging version is known and current, with no callback. The client gets SCHEMA_CHANGE **without any server-side wait for agreement**. Agreement is eventual: peers that see a different gossiped version pull (MigrationCoordinator). `schema/DefaultSchemaUpdateHandler.java:228-271`, `schema/MigrationCoordinator.java:574-577,747-777`, `cql3/statements/schema/AlterSchemaStatement.java:107-137` | pass | (contract seam, noted; not scored) | `bench-s1`: SCHEMA_CHANGE CREATED TABLE, `apply-changes`, `keyspace.init-cf`, `announce` → `gossiper.add-local-application-state`, 2× `schema-push-verb-handler.do-verb`, and both peers hold the table row. `bench-s1-peer-down`: only the live peer gets the push. The gossip-driven pull is a separate flow (`schema-pull`). Seams: DDL can't be reached through QUERY (§2.1), and the gossip state enum rejects `SCHEMA` (§2.5) |
| S2 | Confirmed. `CreateTableStatement.apply` throws `AlreadyExistsException` (ALREADY_EXISTS 0x2400, "Cannot add already existing table \"t\" to keyspace \"ks\"") before any schema write. With IF NOT EXISTS it returns the unchanged schema: an empty diff, `ResultMessage.Void`, and nothing announced or pushed. `CreateTableStatement.java:97-109`, `exceptions/AlreadyExistsException.java:27,34`, `DefaultSchemaUpdateHandler.java:234-235`, `AlterSchemaStatement.java:122-123` | pass | (same seam as S1) | `bench-s2`: already-exists 9216 with the exact message, `apply-changes`/`announce`/`push` = 0. `bench-s2-if-not-exists`: VOID, nothing written |
| S3 | Confirmed. `conf/cassandra.yaml:198` sets `authenticator: AllowAllAuthenticator`. `StartupMessage.execute` returns `ReadyMessage` because `requireAuthentication()` is false (`StartupMessage.java:122-126`), and ClientState uses ANONYMOUS_USER (`service/ClientState.java:175-176`) | pass | – | `bench-s3`: READY, stage READY, user `anonymous`, no AUTH_RESPONSE or SASL calls. STARTUP runs on the event loop, not `dispatcher.dispatch` (matches `InitialConnectionHandler`) |
| S4 | Confirmed (not the deployed config). STARTUP → AUTHENTICATE. AUTH_RESPONSE → `PlainTextSaslAuthenticator.evaluateResponse` → `getAuthenticatedUser` → `authenticate` → the credentials cache (role read at LOCAL_QUORUM, or QUORUM for `cassandra`) → `checkpw` fails → `AuthenticationException` "Provided username X and/or password are incorrect" = BAD_CREDENTIALS 0x0100, returned as an ERROR response. The connection stays AUTHENTICATING. `auth/PasswordAuthenticator.java:140-166,254-270`, `transport/messages/AuthResponse.java:72-97`, `exceptions/AuthenticationException.java:24` | pass | – | `bench-s4` is driven by input (a wrong password, no fault): bad-credentials 256 with the exact message, a real system_auth.roles read through the read path, `client-state.login` = 0, stage AUTHENTICATING. `bench-s4-startup-challenge`: AUTHENTICATE |
| P1 | Confirmed, with detail. nodetool sends `parallel` by default (`tools/nodetool/Repair.java:171-176`), so there's no snapshot (`repair/RepairJob.java:163-193`). Under the deployed `paxos_variant: v1` there's no paxos repair (`RepairJob.java:128`, Config.java:1051). Steps: PREPARE_MSG to the neighbours, VALIDATION_REQ to all 3 replicas including self (the local tree is answered locally, `repair/Validator.java:281-306`), `createStandardSyncTasks` (`LocalSyncTask` for pairs with self, `SymmetricRemoteSyncTask` with SYNC_REQ otherwise, `RepairJob.java:295-351`), streaming, then CLEANUP_MSG | pass | – | `bench-p1` (10.0.0.3 diverged): 2 prepare, 0 snapshot, 0 paxos cleanup, 3 validation, 2 sync tasks (1 local and 1 symmetric remote), 2 stream plans, 2 cleanup, no finalize. `bench-p1-in-sync`: no sync and no streaming. Trees are one digest per replica and table, not per range (an abstraction) |
| P2 | **Corrected.** Anticompaction does not mark SSTables *repaired*. It rewrites them as UNREPAIRED with `pendingRepair = session` (`db/compaction/CompactionManager.java:871,1798`). Then come validation and sync (streamed SSTables are also pending), then FINALIZE_PROPOSE/PROMISE/COMMIT, which set LocalSession FINALIZED (`repair/consistent/LocalSessions.java:1025-1040`). Promotion to repaired (`repairedAt`) happens **afterwards** in the background, through `PendingRepairManager` → `RepairFinishedCompactionTask` → `mutateRepaired` (`db/compaction/PendingRepairManager.java:274-276,503-531`) | partial | model + contract | `bench-p2`: the protocol is right: PREPARE_CONSISTENT ×3, `pending-anti-compaction.run` ×3, validation ×3, 2 sync tasks, FINALIZE_PROPOSE/COMMIT ×3, all local sessions FINALIZED. But `pending-anti-compaction.run` only flushes and checks for conflicts: no SSTable gets `pending_repair`, and nothing promotes pending → repaired after FINALIZED. The `compaction-strategy-manager` note "Promote or demote sstables from finished repairs first" is narration with no behavior behind it. Edit: anticompaction should mark the tracker's SSTables `pending_repair` (read-path state) and `compaction-strategy-manager.get-next-background-task` should run a repair-finished task that sets `repaired` |
| C1 | **Corrected.** The deployed default is **SizeTieredCompactionStrategy**, not UCS: `default_compaction` is commented out (`conf/cassandra.yaml:1209-1213`) and `CompactionParams.DEFAULT` is STCS (`schema/CompactionParams.java:90-103`). UCS is only in `conf/cassandra_latest.yaml`. After a flush, `ColumnFamilyStore.replaceFlushed` calls `CompactionManager.submitBackground` (`db/ColumnFamilyStore.java:1834-1840`). STCS picks the hottest bucket of at least min_threshold (4) similar-size SSTables, capped at 32 (`SizeTieredCompactionStrategy.java:80-131`). The compaction merges and purges tombstones older than gc_grace (864000s) that shadow nothing in overlapping sources. If no bucket qualifies, it compacts one SSTable with more than 20% droppable tombstones | partial | contract | `bench-c1`: STCS, 4 SSTables → 1 (42MB), 50 of 160 tombstones purged, resubmit, recheck finds nothing. Path right from `submit-background` on. But `bench-c1-flush-trigger` shows a dirty flush writes an SSTable and **never calls `compaction-manager.submit-background`**: `column-family-store-flush.run` does `live-sstables-incr` (write-path state) and `column-family-store.add-sstables` has only a title. Write-path's live-sstable count and read-path's `tracker.views` are disjoint. Edit: emit `compaction-manager.submit-background` from the flush's replaceFlushed step and from `add-sstables`, and add the new SSTable to `tracker.views` |
| T1 | **Corrected (scope).** `ExecuteMessage.execute`: `getPrepared` (cache `getIfPresent`) returns null → `PreparedQueryNotFoundException` = UNPREPARED 0x2500, before the page-size check (`transport/messages/ExecuteMessage.java:131-157`, `cql3/QueryProcessor.java:244-247`). The re-prepare is driver behavior, not server behavior | pass | benchmark (re-prepare is client-side) | `bench-t1`: unprepared 9472 with the code's message, `process-prepared` = 0. `bench-t1-unprepared-before-page-size` confirms the ordering |
| T2 | Confirmed. `QueryMessage.execute` → `QueryProcessor.parse` → `CQLFragmentParser.parseAnyUnhandled` → `errorCollector.throwFirstSyntaxError()` → SyntaxException = SYNTAX_ERROR 0x2000. Nothing executes. `transport/messages/QueryMessage.java:116`, `cql3/CQLFragmentParser.java:80`, `exceptions/SyntaxException.java:24` | pass | – | `bench-t2` is driven by input (`SELEC ...`, no fault): syntax-error 8192 "no viable alternative at input 'SELEC'", `query-processor.process` = 0. The grammar is approximated by a first-keyword regex (§4) |
| T3 | **Corrected.** Deployed: `native_transport_rate_limiting_enabled: false` (Config.java:299; yaml:1076 commented out), the queue-age threshold is `Double.MAX_VALUE` (Config.java:1394), and the byte limits are heap/10 global and heap/40 per IP (DatabaseDescriptor.java:651-656). With THROW_ON_OVERLOAD unset (`native_transport_throw_on_overload` false, Config.java:1393), a bytes-in-flight breach **does not** produce `overloaded`: the request is still processed, the connection is paused (backpressure) and the client gets a warning (`transport/CQLMessageHandler.java:218-259`). `overloaded` (0x1001) comes only (a) with THROW_ON_OVERLOAD=1 and a byte-limit breach (`:198-203`), (b) when the request waited longer than `native_transport_timeout` 12s in the queue (`transport/Dispatcher.java:364-367`), or (c) when the server is shutting down (`Dispatcher.java:110`). Rate limits can't trigger under the deployed config | pass | benchmark | `bench-t3-default-backpressure`: ok, paused, warning, processed. `bench-t3-throw-on-overload`: overloaded 4097 "Request breached limit on bytes in flight", not dispatched. `bench-t3-rate-limit-disabled`: an exhausted limiter is ignored. `bench-t3-queue-timeout`: overloaded "Query timed out before it could start" |

The known `keyspace`/`shop.users` write-path seam doesn't affect this group. S1 writes system_schema
through `schema-keyspace` rows, C1 uses read-path `tracker.views`, and S4 reads system_auth.

## 2. Wrong claims found in the model

1. **DDL and auth statements can't be reached from the native protocol (contract cql ↔ schema-auth).**
   `query-processor.process-statement` dispatches through a fixed map of SELECT, INSERT, UPDATE,
   DELETE, BATCH, USE, TRUNCATE, DESCRIBE and ADD/DROP_IDENTITY. A QUERY with `statement.type: CREATE_TABLE` aborts with
   `no such key: CREATE_TABLE`. In the code, `QueryProcessor.processStatement` is generic: it calls `statement.authorize/validate/execute`
   on any `CQLStatement`. Nothing in the model calls `alter-schema-statement.execute` or the role and permission statements' `execute`,
   so the CREATE/ALTER/DROP, GRANT and role flows exist only as standalone entries.
2. **Incremental repair never marks or promotes SSTables (P2).** `pending-anti-compaction.run`, titled "Isolate the data
   with PendingAntiCompaction", only flushes and checks conflicts. It never sets `pendingRepair`
   (`CompactionManager.java:871,1798`). Nothing models `PendingRepairManager`/`RepairFinishedCompactionTask`
   (`PendingRepairManager.java:274-276,531`), although `compaction-strategy-manager` narrates "Promote or
   demote sstables from finished repairs first".
3. **A flush doesn't trigger compaction (C1).** `column-family-store-flush.run` "replaceFlushed" and
   `column-family-store.add-sstables` (title "CompactionManager.submitBackground") never call or emit
   `compaction-manager.submit-background`. The code does both (`ColumnFamilyStore.java:1679-1682,1834-1840`). The new
   SSTable also never appears in read-path's `tracker.views`.
4. **The STCS bucket choice is wrong.** `size-tiered-compaction-strategy.get-next-background-task` says "keep the first
   bucket with at least min_threshold" and slices the first 32. The code picks the **hottest** qualifying bucket
   (`Collections.max(..., bucketsByHotnessComparator)`) and trims by read hotness
   (`SizeTieredCompactionStrategy.java:116-131`). The large-SSTable bucketing is also anchored on the first SSTable
   rather than on running averages (`getBuckets`).
5. **Schema enum (contract membership ↔ schema-auth).** `gossiper.add-local-application-state` allows only
   STATUS_WITH_PORT, TOKENS, LOAD and RPC_READY, so every DDL run warns "SCHEMA is not one of the allowed values".
   `gms/ApplicationState.java:34` has SCHEMA, and the existing snitch scenario also warns for SEVERITY.
6. Minor: in streaming during repair, `column-family-store.force-flush` on the SYNC_REQ receiver (10.0.0.2) looks up
   memtable stats under `10.0.0.1:ks1.users` (the `not_found` in the `bench-p1` trace). The replica isn't propagated.
7. Contract note (not wrong code): `gossiper.get-live-members` reads `live_endpoints`, so marking a peer down only
   through the membership contract key `endpoint_state_map.<ep>.alive` still pushes schema to it
   (`bench-s1-alive-flag-only`). Scenarios must set both keys.

Citation sample (`--cite-sample 12 --seed 4711`): 12 of 12 support their claims (I checked the Gossiper schema-agreement backoff
50→1000ms, `checkServiceAllowedToStart`, `CassandraAuthorizer` superuser, ReadCommand.executeLocally, and others). For the flows my
cases touch, I read these behaviors next to their code and found them faithful:
`DefaultSchemaUpdateHandler.apply/updateSchema`, `MigrationCoordinator.pushSchemaMutations/shouldPushSchemaTo`,
`CreateTableStatement.apply`, `StartupMessage.execute`, `PasswordAuthenticator.authenticate/queryHashedPassword`,
`AuthResponse.execute`, `Validator.respond`, `RepairJob` snapshot/paxos gating, `StreamSession` always-flush,
`CompactionManager.submitBackground`, `ExecuteMessage.execute` ordering, and `CQLMessageHandler` overload branches.

## 3. Builder findings (from the notes' "docs vs code" sections)

Confirmed:
- schema-auth: DDL doesn't wait for schema agreement; the push is async with no callback (`DefaultSchemaUpdateHandler.java:244-250`).
- schema-auth: non-default roles are read at LOCAL_QUORUM and written at EACH_QUORUM; `cassandra` uses QUORUM (`Config.java:753-754`, `CassandraRoleManager.java:721-726`).
- transport: on v5, an absent THROW_ON_OVERLOAD falls back to `native_transport_throw_on_overload` (`PipelineConfigurator.java:309-314`).
- transport: server shutdown is reported as OVERLOADED (`Dispatcher.java:110`). A queue wait over `native_transport_timeout` gives OVERLOADED "Query timed out before it could start" (`Dispatcher.java:364-367`).
- transport: UNPREPARED is checked before page size 0 (`ExecuteMessage.java:137-157`).
- repair-streaming: nodetool sends `parallel` (`Repair.java:171-176`). Snapshots happen only for non-parallel full repair (`RepairJob.java:163-193`).
- repair-streaming: `repairPaxos` is a no-op under `paxos_variant: v1` (`RepairJob.java:128`).
- repair-streaming: the coordinator validates itself via VALIDATION_REQ but answers locally (`Validator.java:281-306`).
- repair-streaming: PREPARE_CONSISTENT_REQ is sent with `sendMessageWithRetries(..., notDone(prepareFuture), ...)`, which has no final failure callback (NOOP), so a lost reply relies on LocalSessions cleanup (`CoordinatorSession.java:180-190`, `RepairMessage.java:166-174`).
- read-path: the 5.0.9 default compaction is STCS, not UCS (`cassandra.yaml:1209`, `CompactionParams.java:96`).
- read-path: a BackgroundCompactionCandidate resubmits only after it compacted. submitBackground skips when the table is already compacting and the executor is saturated (`CompactionManager.java:244-250,382-383`).

Refuted: none in this group.

## 4. Simulator and tooling gaps

- **Cross-node eventual convergence (S1).** The async push is an `emit` delivered after the entry call. Gossip propagation of the
  new version and the peers' pull are a separate flow (`schema-pull`), and one run can't chain "announce → peer sees a
  different version → pull → agreement". Missing feature: composing flows in a scenario (a follow-on entry triggered by state/gossip),
  or a multi-node clock.
- **Client sessions of different messages (T1, S4).** EXECUTE → UNPREPARED → PREPARE → EXECUTE, or STARTUP →
  AUTHENTICATE → AUTH_RESPONSE, needs a sequence of different entry calls. `entry.repeat` replays the same input. Missing
  feature: multi-step scenarios (a list of entry calls sharing state).
- **Parallel repair (P1/P2).** Validation, sync and streaming run as a sequential `foreach`, so repair durations and the
  "first failure fails the job" ordering are distorted. Missing feature: parallel fan-out with join/k-of-n.
- **Time-based purgeability (C1).** gc_grace isn't computed from cell timestamps against `now`. Each SSTable carries a
  precomputed `purgeable_tombstones`. Missing feature: none strictly, but data-level timestamps would make the gc_grace rule testable.
- **Parser (T2).** The ANTLR grammar is approximated by a first-keyword regex, so `SELECT FROM` parses. This is inherent.
- **Tooling.** `check -v` doesn't print runs, despite what JUDGE.md said. The coordinator's new `--trace`/`--scenario` flags fixed that, and I
  re-verified all 21 scenarios with them.

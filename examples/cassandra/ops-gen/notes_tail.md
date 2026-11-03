
## 2. Components modeled

Daemon and configuration:
- `cassandra-daemon`: CassandraDaemon (`service/CassandraDaemon.java`): `activate` 718-771, `setup` 229-455, `start` 643-663, `validate-transports-can-start` 783-807, `start-native-transport` 809-825, `stop-native-transport` 833-837, `deactivate` 847-856.
- `startup-checks`: StartupChecks (`service/StartupChecks.java`): `verify` 176-193 with checkNativeLibraryInitialization 409-420, checkDataDirs 561-594, checkSSTablesFormat 596-709, checkDatacenter 736-771, checkRack 773-808, checkLegacyAuthTables 810-822.
- `database-descriptor`: DatabaseDescriptor (`config/DatabaseDescriptor.java`): `daemon-initialization` 245-265 and loadConfig 391-400; `start-native-transport` and `get-autocompaction-on-startup-enabled` read the effective flags.
- `virtual-keyspace-registry`: VirtualKeyspaceRegistry.register (`db/virtual/VirtualKeyspaceRegistry.java:41-48`), called by setupVirtualKeyspaces (CassandraDaemon 534-544).
- `mbean-wrapper`: MBeanWrapper / PlatformMBeanWrapper (`utils/MBeanWrapper.java:173-186`).

JMX surfaces:
- `storage-service-mbean`: StorageServiceMBean + the StorageService glue (flush, cleanup/scrub/verify/upgrade/recompress/garbagecollect/relocate status loop, major and ranged compaction, auto-compaction toggles, transports, audit log, FQL, schema reset/reload, truncate, setters reachable from nodetool, JMX-only snapshot/sampling/bulk load/paxos repair operations).
- `storage-proxy-mbean`: StorageProxyMBean (hinted handoff switch with `checkServiceAllowedToStart`, hints per DC, max hint window, denylist, repaired-data tracking and duplicate-row flags).
- `cache-service-mbean`: CacheServiceMBean (invalidate, capacity with negative refusal, keys to save with negative refusal, saveCaches).
- `active-repair-service-mbean`: failSession, cleanupPending (repair_admin).

nodetool:
- `node-tool` (NodeTool.execute 96-296, connect 444-464), `node-tool-node-tool-cmd` (parseOptionalKeyspace 476-502, runInternal 380-401), `node-probe` (connect 246-270, perform 447-460, checkJobs 396-401), `repair-runner` (RepairRunner run 63-91, progress 126-146, queryForCompletedRepair 148-186).
- 88 `nodetool-*` command components, one per command class in `tools/nodetool/` (plus `ReloadSslCertificates` and the RepairAdmin inner commands), each citing its class.

Tracing, audit, FQL:
- `tracing-impl` (TracingImpl.begin 53-67, stopSessionImpl 40-51, trace 106-117), `trace-state-impl` (executeMutation 104-110, mutateWithCatch 112-122).
- `audit-log-manager` (constructor 71-87, initialize 89-96, log 136-142, querySuccess 242-252, enable 187-218, disableAuditLog 174-180), `audit-log-filter` (isFiltered 106-131), `bin-audit-logger` (log 87-95).
- `full-query-logger` (enableWithoutClean 106-120, stop 159-183, reset 190-250) with `BinLog.Builder.path` validation (`utils/binlog/BinLog.java:377-387`).

## 3. Boundary stubs

After the reconciliation round every one of the 85 boundary interfaces ops calls is copied from its
owner's fragment by `ops-gen/align.py` (request, response, kind and errors; owner schemas inlined so
the fragment validates alone). Owners: membership (storage-service lifecycle, gossiper, token-metadata,
messaging), read-path (compaction-manager, column-family-store compaction/index operations,
auto-saving-cache, tracker), write-path (column-family-store flush/import/load/snapshot, commit-log),
repair-streaming (repair-async, take/clear-snapshot, active-repair-service, local-sessions, stream rate
limiter), hints-batchlog, coordination (storage-proxy), schema-auth (schema, auth caches, CIDR), cql
(query-processor) and transport (native-transport-service). Stub components copy the owner's kind.
Calls pass `replica`/`holder` `10.0.0.1` where the owner's contract keys state by replica.

Interfaces ops defines for other areas (decision 6): `fb-utilities.get-broadcast-address-and-port`,
`diagnostic-snapshot-service.snapshot` (plus its `run-task`, the executor task that calls
`column-family-store.snapshot`), `tracing.new-session`, `tracing.begin`, `tracing.stop-session`.

## 4. Deployed configuration read

| Setting | cassandra.yaml | Config.java default | Effective | Where it matters |
|---|---|---|---|---|
| `start_native_transport` | true (1020) | true (278) | true | CassandraDaemon.startClientTransports 665-672 |
| `audit_logging_options.enabled` | false, logger BinAuditLogger (1893-1896) | AuditLogOptions enabled false (703) | disabled | AuditLogManager 71-96: NoOpAuditLogger, no listener |
| `full_query_logging_options` | commented out (1917) | log_dir "" (FullQueryLoggerOptions.java:27) | log_dir "" | enablefullquerylog without `--path` fails in BinLog.Builder.path 382 |
| `allow_nodetool_archive_command` | commented, false | false | false | StorageService 7003-7004, 7139-7140 |
| `startup_checks` | commented out (2270) | check_dc/check_rack on, filesystem ownership and data resurrection off (StartupChecks.java:106-126) | as default | checkDatacenter, checkRack |
| `trace_type_query_ttl` / `trace_type_repair_ttl` | 1d / 7d (1752-1754) | 1d / 7d (551-554) | same | trace rows TTL |
| `compaction_throughput` | 64MiB/s (1251) | 64MiB/s (337) | 64 | setcompactionthroughput |
| `concurrent_compactors` | commented (1230) | null -> min(8, max(2, min(cpus, data dirs))) (DatabaseDescriptor 777-778) | 2 with one data dir | NodeProbe.checkJobs |
| `column_index_size` | commented (1188) | null -> -1 (DatabaseDescriptor 2034-2037) | -1 (format default) | setcolumnindexsize |
| `hinted_handoff_enabled` | true (68) | true (112) | true | disablehandoff/enablehandoff |
| `max_hint_window` | 3h (80) | 3h (115) | 10800000 ms | setmaxhintwindow |
| `hinted_handoff_throttle` | 1024KiB (88) | 1024KiB (439) | 1024 | sethintedhandoffthrottlekb |
| `batchlog_replay_throttle` | 1024KiB (157) | 1024KiB (441) | 1024 | setbatchlogreplaythrottle |
| `incremental_backups` | false (1135) | false (455) | false | enablebackup |
| `snapshot_links_per_second` | 0 (1162) | 0 (322) | unthrottled | snapshots |
| `stream_throughput_outbound` and inter-DC / entire-SSTable | commented (1285-1304) | 24MiB/s (362-366) | 24MiB/s | setstreamthroughput |
| `read/range/write/counter_write/cas_contention/truncate/request` timeouts | 5000/10000/2000/5000/1000/60000/10000 ms (1322-1349) | same | same | settimeout |
| `internode_tcp_connect/user_timeout`, streaming user timeout | commented (1356-1368) | 2s / 30s / 300s (Config 265-276) | same | settimeout internode* |
| `key_cache_save_period` / `row_cache_save_period` / `counter_cache_save_period` | 4h / 0s / 7200s (538, 575, 603) | | same | setcachekeystosave reschedules saving |
| `row_cache_size` | 0MiB (564) | | row cache off | startup cache load |
| `default_keyspace_rf` | commented (1878) | 1 (712) | 1 | setdefaultrf |
| `auth_cache_warming_enabled` | commented (1965) | false (749) | false | CassandraDaemon 447-450 |
| `autocompaction_on_startup_enabled` | not in yaml | property default true (833) | true | CassandraDaemon 408-428 |
| `auto_repair` | commented (2342) | AutoRepairConfig enabled false | off | AutoRepairServiceMBean skipped |
| `server_encryption_options.internode_encryption` | none (1648) | | TLS off | SSLFactory hot reload skipped |
| JMX | cassandra-env.sh: LOCAL_JMX=yes, port 7199, authenticate=false (228-240) | | local-only, no auth | maybeInitJmx 139-185 |
| nodetool notification poll | | `cassandra.nodetool.jmx_notification_poll_interval_seconds` 300 s (CassandraRelevantProperties 376) | 300 s | RepairRunner |

Differences between cassandra.yaml and Config.java defaults among the settings above: none in value.
The yaml leaves `concurrent_compactors`, `column_index_size`, the stream throughputs and the internode
timeouts unset, so the Config.java/DatabaseDescriptor defaults apply.

## 5. What the code did not settle, and assumptions

- JMX exception transport: the MBean proxy (`JMX.newMBeanProxy`) rethrows a server-side
  RuntimeException as itself, so NodeTool sees IllegalArgumentException/IllegalStateException from the
  server and exits 1. This is JDK behavior (`MBeanServerInvocationHandler`), not Cassandra code.
- `node-tool.execute` treats the modeled read-only commands as out of model (exit 0, no calls).
- The keyspace and table catalogue the commands see lives in `storage-service-mbean` state
  (`system`, `system_schema`, `system_auth`, `system_distributed`, `system_traces`, `ks1`); in the
  real node it comes from Schema (schema-auth). Virtual keyspaces are not in `Schema.getKeyspaces`.
- Decisions that depend on another area's runtime values the model cannot compute are choices whose
  default reads the stub's value: repair `started` and `parent_status`, cleanup `pending_ranges` and
  `op_status`, decommission `decommissioning` and `bootstrap_state`, daemon `bootstrap`. Owner-aligned
  stubs without a `default` in their response schema return random enum values in a standalone run,
  so the happy-path cleanup scenarios pin `op_status: SUCCESSFUL`.
- `repair-runner.run` folds the poll loop (every 300 s) into one confirmation call after the
  notification choice; an unknown parent status (null) is treated as success, as the code does.
- Startup: `migrateSystemDataIfNeeded`, `Mx4jTool`, `logSystemInfo`, `scrubDataDirectories`,
  `doAuthSetup`, the view build schedule and PaxosState tracker setup are narrated, not modeled.
- The SizeEstimatesRecorder (every 300 s), background compaction submitter (every minute) and
  speculative retry threshold updater (every read timeout) are scheduled in `setup` and narrated with
  their lines; their work belongs to read-path/coordination.
- `StorageService.setLoggingLevel` validation (logback) is not modeled; `setConcurrency` checks only
  the pool name.

## 6. Where docs or common knowledge differ from the code

- `nodetool repair` is incremental by default (`incremental = !fullRepair`, Repair.java:178), and
  skips `system_distributed` unless it is named (Repair.java:143). Many guides still describe full
  repair as the default.
- `nodetool flush` with an unknown table exits 2, not 1: Flush wraps every exception in
  RuntimeException (Flush.java:44-49). An unknown keyspace exits 1 because it is checked client side.
- `nodetool cleanup` with ABORTED status for a table prints a message and still exits 0; only
  UNABLE_TO_CANCEL (status 2) fails the command (NodeProbe.perform 447-460).
- `nodetool bootstrap resume` is disabled unless `cassandra.reset_bootstrap_progress` is explicitly
  false or `--force` is given (BootstrapResume.java:44-45).
- `getNonSystemKeyspaces` returns the same set as `getNonLocalStrategyKeyspaces` and includes
  `system_auth`, `system_distributed` and `system_traces` (StorageService 6236-6244).
- Trace rows are written with `StorageProxy.mutate` at consistency ANY on the TRACING stage, and an
  OverloadedException silently drops them (TraceStateImpl 104-122).
- `setconcurrency` with an unknown stage name throws IllegalStateException, not
  IllegalArgumentException (Stage.java:92-121).
- `StorageServiceMBean.deliverHints` still exists but always throws UnsupportedOperationException
  (StorageService 3940-3943).
- `nodetool enablefullquerylog` without `--path` fails on the stock yaml: `log_dir` is "" and
  `BinLog.Builder.path` rejects it ("you might have forgotten to specify a directory to save logs").

## 7. Simulator gaps

- **Input integers break `string()`.** Numbers that arrive through flow or scenario input decode as
  Go `int`, and CEL's `string()` has no overload for them (`no such overload: string(int)`), while the
  same value in component state works. Example: `string(input.options['jobs'])` in `nodetool-cleanup`;
  the fragment uses `string(int(...))`. Worth fixing in the engine.
- **Stub outputs cannot be steered by scenarios (resolved in the merged model).** With the shared
  fixtures, the owners' real state drives those branches, so the pinned choices were dropped. A
  standalone run (ops plus fixtures, stubs only) is no longer deterministic for the cleanup,
  decommission, startup and compaction-status scenarios. Originally: A boundary stub returns fake data; a scenario
  can fault it but cannot choose its value. Branches on another area's return values therefore need
  a choice with an expression default (repair parent status, cleanup op status, pending ranges). A
  `stub_returns` scenario lever would remove those choices.
- **Waiting on notifications.** RepairRunner waits on JMX notifications with a 300 s poll; the model
  has no event subscription, so the notification is a choice and the poll is one call.
- **Asynchronous futures joined later (resolved for two cases).** `CassandraDaemon.setup`'s key and
  row cache loads and `CacheService.saveCaches`' three writes are now `parallel` with `join: {need: all}`.
  `TraceStateImpl` pending futures, awaited only when a session stops, are still emits.
- **Periodic tasks scheduled at startup.** `entry.repeat` models a periodic task as its own flow; it
  cannot start one from inside another flow's behavior, so the tasks `setup` schedules are narrated.
- **Process exit.** `System.exit(code)` is modeled as a failure carrying `data.exit_code`; mosaic has
  no notion of a process ending while emitted work is still queued.

## 8. Known gaps

- Virtual table reads (`db/virtual/**`) are not modeled: they are reached from CQL SELECT on
  `system_views`, and the cql fragment's contract for virtual tables was not available; only
  registration at startup is modeled.
- Guardrails and auto-repair JMX/nodetool configuration are skipped as groups (section 1).
- The read-only nodetool commands are out of the model; their getters are skipped as a group.
- Diagnostic events (`diag/`), `NativeAccessMBean`, GC inspector and metrics MBeans are skipped.
- StorageService setters not reachable from nodetool are skipped as a group even where they also
  resize an executor; the nodetool-reachable ones carry that behavior.
- Native-protocol tracing decisions (`tracing` flag, `shouldTraceProbablistically`) belong to
  transport; ops models the setter and the session writes.
- Stub components for other areas cite only the class line; their parents are the owners' skeleton modules.

## Merged-run check (reconciliation round)

All 175 ops scenarios pass in the merged ontology and no merge warning names ops. Changes made:
- `cmd-compact` seeds read-path's `tracker.views['10.0.0.1:ks1.users']`; `cmd-removenode` marks
  10.0.0.3 down in membership's `gossiper` (decision 4) and removes its host id; `cmd-repair-admin-cancel`
  seeds repair-streaming's `local-sessions` row. `tracker` and `local-sessions` are declared as stub
  components so the standalone fragment validates.
- Assertions on other areas' internals were dropped (decision 9), notably the pending-range count in
  `cleanup-keyspace` (CompactionManager.performCleanup checks pending ranges again, 621-625).
- Decisions that read another area's return value are choices; the scenarios pin the value the
  owner's state gives (`bootstrap: complete`, `pending_ranges: none`, `op_status: SUCCESSFUL`,
  `decommissioning: no`, `started`, `joined`), so the standalone run is deterministic.
- `cmd-invalidatecidrpermissionscache` and `cmd-reloadcidrgroupscache` assert only ops' own calls: with
  the deployed AllowAllCIDRAuthorizer schema-auth correctly refuses them (exit 2).
- `cmd-rebuild` names `datacenter1`, the DC membership knows.
- `decommission-ok` passes `--force` (3 nodes at RF 3).
- repair-streaming's `rs-snapshot-req-diagnostic` asserts `column-family-store.snapshot == 0` after a
  diagnostic snapshot; ops' DiagnosticSnapshotTask runs asynchronously and does call it
  (DiagnosticSnapshotService.java:207-215), so that assertion is about ops internals.
- The generator lives in `examples/cassandra/ops-gen/` (`bash ops-gen/all.sh` rebuilds the fragment,
  these notes and `skips/ops.json`).

## Migration round (instances, configs, fixtures, multi-step scenarios)

- Every ops scenario runs on `fixtures: [three-node-rf3]`; ops components sit under `cassandra-node`, so
  they are per instance and expectations read `state['<component>@n1']` (n1 is the entry instance).
- Endpoint literals are gone: owner calls pass `self` where the owner's contract still has a
  `replica`/`holder`/`endpoint` field, `fb-utilities.get-broadcast-address-and-port` returns `self`,
  and command arguments name instances (`assassinate n3`).
- `storage-service-mbean`'s keyspace and table lists equal `base-schema` (ks1 and shop added).
- 13 config entities (section 4 values): `start-native-transport`, `autocompaction-on-startup-enabled`,
  `auth-cache-warming-enabled`, `audit-logging-enabled`, the two `*-allow-nodetool-archive-command`,
  `full-query-logging-log-dir`, the two trace TTLs, the two startup DC/rack checks, the nodetool
  notification poll interval and the size recorder interval. Behaviors read `config[...]`; runtime
  values changed through JMX setters stay in component state.
- Flows tagged `writes`: daemon-startup, nodetool-hinted-handoff, nodetool-runtime-config,
  nodetool-audit-and-fql, jmx-operation, nodetool-command. Each has a multi-step read-back
  (setcompactionthroughput then getCompactionThroughputMbPerSec; disablehandoff then
  getHintedHandoffEnabled; enableauditlog then a logged query; enablefullquerylog then
  isFullQueryLogEnabled; denylistKey then isKeyDenylisted; enablebackup then
  isIncrementalBackupsEnabled; startup then enablebinary). Seven JMX getters were modeled for this.
- Every scenario asserts state or the trace (hollow lint): an ops state effect where there is one,
  otherwise that the command's key call ran on n1.
- Fixture components of other areas are declared as boundary stub components so the fragment
  validates with `fixtures.yaml` alone.
- No mocks. No `to` fields existed in ops; two sequential loops became `parallel`.

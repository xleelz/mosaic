# ops: notes

Area `ops` of the Cassandra 5.0.9 ontology (`fragments/ops.yaml`): the daemon's startup, nodetool and
the JMX operations it invokes, tracing sessions, the audit log and the full query log, plus the
operational glue in `StorageService` behind `StorageServiceMBean`. All citations are relative to
the checkout `cassandra-5.0.9` (`b5f2a54210`).

How the fragment is organised:

- **nodetool** is one dispatcher, `node-tool.execute` (NodeTool.execute), that connects through
  `node-probe.connect` and calls `nodetool-<command>.execute` (one component per command class).
  It maps exceptions as NodeTool does: IllegalArgumentException or IllegalStateException (and airline
  parse errors) give exit status 1 with `nodetool: <message>`; anything else gives exit 2 with
  `error: <root cause message>`; a failed JMX connection exits 1. The result is
  `{exit_status, output}`, so scenarios assert the exit status the operator sees.
- **JMX operations** of the service MBeans (`StorageServiceMBean`, `StorageProxyMBean`,
  `CacheServiceMBean`, `ActiveRepairServiceMBean`) are interfaces of kind `jmx` on ops components
  named after the MBean (`storage-service-mbean.force-keyspace-flush`). Each cites the MBean
  declaration line (coverage) and the implementing method, and models the StorageService glue
  (table resolution, refusals, status aggregation). Where the implementation is another area's,
  the operation calls that area's interface as a boundary stub. For MBean operations whose whole
  behavior another area already models on its own component (repairAsync, takeSnapshot,
  clearSnapshot, drain, decommission, move, removeNode, joinRing, rebuild, resumeBootstrap,
  start/stopGossiping), the nodetool command calls the owner's interface directly and cites the
  MBean declaration in the step, so nothing is modeled twice.
- Operations of MBeans in other areas' packages (HintsServiceMBean, GossiperMBean,
  CompactionManagerMBean, ColumnFamilyStoreMBean, auth caches, BatchlogManagerMBean,
  MessagingServiceMBean) are reached the same way: the nodetool command calls the owner's interface
  and cites the MBean line.
- `mbean-wrapper.invoke-operation` is the path for any JMX client (jconsole, scripts): a dynamic call
  over every modeled service-MBean operation, used by the `jmx-operation` flow for operations no
  nodetool command invokes.

## Flows and scenarios

| Flow | Entry | Scenarios | What it proves |
|---|---|---|---|
| `daemon-startup` | `cassandra-daemon.activate` | 13 | setup order, startup checks with their exit codes (1, 3, 100), config error exit 3, commit log replay failure exit 3, initServer ConfigurationException exit 1, transports skipped when bootstrap incomplete or `start_native_transport: false`, cache load failure tolerated |
| `nodetool-repair` | `node-tool.execute` (repair) | 11 | system_distributed skipped unless named, incremental by default, RF 1, FAILED parent status, ERROR notification, connection closed, `-pr` with `-dc`, unknown keyspace, JMX unreachable, invalid options |
| `nodetool-flush` | `node-tool.execute` (flush) | 7 | per-table forceBlockingFlush, unknown table wrapped (exit 2, not 1), unknown or virtual keyspace refused client side (exit 1), flush failure |
| `nodetool-cleanup` | `node-tool.execute` (cleanup) | 7 | pending ranges refusal, local system keyspace skipped client side, ABORTED (exit 0 with message) vs UNABLE_TO_CANCEL (exit 2), `--jobs` warning |
| `nodetool-decommission` | `node-tool.execute` | 4 | already decommissioning/decommissioned short-circuits, UnsupportedOperationException becomes IllegalStateException (exit 1) |
| `nodetool-drain` | `node-tool.execute` | 3 | only IOException/InterruptedException/ExecutionException are wrapped |
| `nodetool-snapshot` | `node-tool.execute` | 6 | tag with path separator refused client side, server IOExceptions wrapped (exit 2), IllegalArgumentException not wrapped (exit 1) |
| `nodetool-hinted-handoff` | `node-tool.execute` | 10 | disable/enable handoff (enable refused after drain), pause/resume dispatch, truncatehints all or per endpoint, hints per DC, max hint window |
| `nodetool-runtime-config` | `node-tool.execute` | 11 | compaction throughput updates the rate limiter, settimeout dispatch and validation, client-side checkArgument refusals, unknown stage IllegalStateException, cache capacity refusal |
| `nodetool-audit-and-fql` | `node-tool.execute` | 7 | enable/disable audit log, archive command refused, FQL refused with the deployed empty `log_dir`, FQL already configured |
| `audit-log-query` | `audit-log-manager.query-success` | 5 | disabled by default (nothing logged), logged when enabled, exclusion beats inclusion, user include list |
| `tracing-session` | `tracing-impl.begin` | 3 | trace rows written async at CL ANY on the TRACING stage; OverloadedException swallowed; other failures do not affect the traced request |
| `tracing-remote-event` | `tracing-impl.trace` | 1 | replica-side event on the TRACING stage |
| `jmx-operation` | `mbean-wrapper.invoke-operation` | 11 | JMX-only operations: truncate (and Unavailable -> IOException), denylist, repaired-data tracking, saveCaches, deliverHints unsupported, sampling validation |
| `nodetool-command` | `node-tool.execute` | 72 | one happy path per remaining action command, plus unknown command, read-only command, bootstrap resume disabled, client-side validation |

## 1. Entry points

Inventory entries in this area: all `jmx-operation` (913) and `cli-command` (159) entries, the
`java-main` entries under `tools/` plus `CassandraDaemon` and `utils/DynamicList`, the four
`python-cli` entries, and the scheduled, background and stage tasks under `utils/`, `metrics/`,
`security/`, `tracing/`, `CassandraDaemon` and `DataResurrectionCheck` (claimed because it is
StartupChecks' heartbeat). That is 1118 entries: 253 covered and 865 skipped with a reason.
Owners may also cover some of the skipped JMX entries of their own MBeans. One getter,
`CacheServiceMBean.getRowCacheSavePeriodInSeconds`, counts as covered only because the
`cache-service-mbean` component cites the interface declaration two lines above it.


### Covered entry points (260)

Each line: inventory entry, then the flow-reachable entities that cite its lines.


**cli-command** (88)

- `nodetool assassinate` (Assassinate.java:29) -> `nodetool-assassinate.execute`, `component nodetool-assassinate`
- `nodetool bootstrap resume` (BootstrapResume.java:31) -> `nodetool-bootstrap-resume.execute`, `component nodetool-bootstrap-resume`
- `nodetool cleanup` (Cleanup.java:31) -> `nodetool-cleanup.execute`, `component nodetool-cleanup`, `flow nodetool-cleanup`
- `nodetool clearsnapshot` (ClearSnapshot.java:39) -> `nodetool-clear-snapshot.execute`, `component nodetool-clear-snapshot`
- `nodetool compact` (Compact.java:32) -> `nodetool-compact.execute`, `component nodetool-compact`
- `nodetool decommission` (Decommission.java:26) -> `nodetool-decommission.execute`, `component nodetool-decommission`, `flow nodetool-decommission`
- `nodetool disableauditlog` (DisableAuditLog.java:25) -> `nodetool-disable-audit-log.execute`, `component nodetool-disable-audit-log`
- `nodetool disableautocompaction` (DisableAutoCompaction.java:30) -> `nodetool-disable-auto-compaction.execute`, `component nodetool-disable-auto-compaction`
- `nodetool disablebackup` (DisableBackup.java:25) -> `nodetool-disable-backup.execute`, `component nodetool-disable-backup`
- `nodetool disablebinary` (DisableBinary.java:25) -> `nodetool-disable-binary.execute`, `component nodetool-disable-binary`
- `nodetool disablefullquerylog` (DisableFullQueryLog.java:25) -> `nodetool-disable-full-query-log.execute`, `component nodetool-disable-full-query-log`
- `nodetool disablegossip` (DisableGossip.java:25) -> `nodetool-disable-gossip.execute`, `component nodetool-disable-gossip`
- `nodetool disablehandoff` (DisableHandoff.java:25) -> `nodetool-disable-handoff.execute`, `component nodetool-disable-handoff`, `flow nodetool-hinted-handoff`
- `nodetool disablehintsfordc` (DisableHintsForDC.java:30) -> `nodetool-disable-hints-for-dc.execute`, `component nodetool-disable-hints-for-dc`
- `nodetool disableoldprotocolversions` (DisableOldProtocolVersions.java:25) -> `nodetool-disable-old-protocol-versions.execute`, `component nodetool-disable-old-protocol-versions`
- `nodetool drain` (Drain.java:28) -> `nodetool-drain.execute`, `component nodetool-drain`, `flow nodetool-drain`
- `nodetool dropcidrgroup` (DropCIDRGroup.java:34) -> `nodetool-drop-cidrgroup.execute`, `component nodetool-drop-cidrgroup`
- `nodetool enableauditlog` (EnableAuditLog.java:28) -> `nodetool-enable-audit-log.execute`, `component nodetool-enable-audit-log`, `flow nodetool-audit-and-fql`
- `nodetool enableautocompaction` (EnableAutoCompaction.java:30) -> `nodetool-enable-auto-compaction.execute`, `component nodetool-enable-auto-compaction`
- `nodetool enablebackup` (EnableBackup.java:25) -> `nodetool-enable-backup.execute`, `component nodetool-enable-backup`
- `nodetool enablebinary` (EnableBinary.java:25) -> `nodetool-enable-binary.execute`, `component nodetool-enable-binary`
- `nodetool enablefullquerylog` (EnableFullQueryLog.java:26) -> `nodetool-enable-full-query-log.execute`, `component nodetool-enable-full-query-log`, `flow nodetool-audit-and-fql`
- `nodetool enablegossip` (EnableGossip.java:25) -> `nodetool-enable-gossip.execute`, `component nodetool-enable-gossip`
- `nodetool enablehandoff` (EnableHandoff.java:25) -> `nodetool-enable-handoff.execute`, `component nodetool-enable-handoff`
- `nodetool enablehintsfordc` (EnableHintsForDC.java:30) -> `nodetool-enable-hints-for-dc.execute`, `component nodetool-enable-hints-for-dc`
- `nodetool enableoldprotocolversions` (EnableOldProtocolVersions.java:26) -> `nodetool-enable-old-protocol-versions.execute`, `component nodetool-enable-old-protocol-versions`
- `nodetool flush` (Flush.java:29) -> `nodetool-flush.execute`, `component nodetool-flush`, `flow nodetool-flush`
- `nodetool forcecompact` (ForceCompact.java:32) -> `nodetool-force-compact.execute`, `component nodetool-force-compact`
- `nodetool garbagecollect` (GarbageCollect.java:30) -> `nodetool-garbage-collect.execute`, `component nodetool-garbage-collect`
- `nodetool import` (Import.java:37) -> `nodetool-import.execute`, `component nodetool-import`
- `nodetool invalidatecidrpermissionscache` (InvalidateCIDRPermissionsCache.java:31) -> `nodetool-invalidate-cidrpermissions-cache.execute`, `component nodetool-invalidate-cidrpermissions-cache`
- `nodetool invalidatecountercache` (InvalidateCounterCache.java:25) -> `nodetool-invalidate-counter-cache.execute`, `component nodetool-invalidate-counter-cache`
- `nodetool invalidatecredentialscache` (InvalidateCredentialsCache.java:28) -> `nodetool-invalidate-credentials-cache.execute`, `component nodetool-invalidate-credentials-cache`
- `nodetool invalidatejmxpermissionscache` (InvalidateJmxPermissionsCache.java:28) -> `nodetool-invalidate-jmx-permissions-cache.execute`, `component nodetool-invalidate-jmx-permissions-cache`
- `nodetool invalidatekeycache` (InvalidateKeyCache.java:25) -> `nodetool-invalidate-key-cache.execute`, `component nodetool-invalidate-key-cache`
- `nodetool invalidatenetworkpermissionscache` (InvalidateNetworkPermissionsCache.java:28) -> `nodetool-invalidate-network-permissions-cache.execute`, `component nodetool-invalidate-network-permissions-cache`
- `nodetool invalidatepermissionscache` (InvalidatePermissionsCache.java:38) -> `nodetool-invalidate-permissions-cache.execute`, `component nodetool-invalidate-permissions-cache`
- `nodetool invalidaterolescache` (InvalidateRolesCache.java:28) -> `nodetool-invalidate-roles-cache.execute`, `component nodetool-invalidate-roles-cache`
- `nodetool invalidaterowcache` (InvalidateRowCache.java:25) -> `nodetool-invalidate-row-cache.execute`, `component nodetool-invalidate-row-cache`
- `nodetool join` (Join.java:28) -> `nodetool-join.execute`, `component nodetool-join`
- `nodetool move` (Move.java:29) -> `nodetool-move.execute`, `component nodetool-move`
- `nodetool pausehandoff` (PauseHandoff.java:25) -> `nodetool-pause-handoff.execute`, `component nodetool-pause-handoff`, `flow nodetool-hinted-handoff`
- `nodetool rebuild` (Rebuild.java:27) -> `nodetool-rebuild.execute`, `component nodetool-rebuild`
- `nodetool rebuild_index` (RebuildIndex.java:31) -> `nodetool-rebuild-index.execute`, `component nodetool-rebuild-index`
- `nodetool recompress_sstables` (RecompressSSTables.java:30) -> `nodetool-recompress-sstables.execute`, `component nodetool-recompress-sstables`
- `nodetool refresh` (Refresh.java:30) -> `nodetool-refresh.execute`, `component nodetool-refresh`
- `nodetool refreshsizeestimates` (RefreshSizeEstimates.java:25) -> `nodetool-refresh-size-estimates.execute`, `component nodetool-refresh-size-estimates`
- `nodetool reloadcidrgroupscache` (ReloadCIDRGroupsCache.java:27) -> `nodetool-reload-cidrgroups-cache.execute`, `component nodetool-reload-cidrgroups-cache`
- `nodetool reloadlocalschema` (ReloadLocalSchema.java:24) -> `nodetool-reload-local-schema.execute`, `component nodetool-reload-local-schema`
- `nodetool reloadseeds` (ReloadSeeds.java:28) -> `nodetool-reload-seeds.execute`, `component nodetool-reload-seeds`
- `nodetool reloadssl` (ReloadSslCertificates.java:24) -> `nodetool-reload-ssl-certificates.execute`, `component nodetool-reload-ssl-certificates`
- `nodetool reloadtriggers` (ReloadTriggers.java:25) -> `nodetool-reload-triggers.execute`, `component nodetool-reload-triggers`
- `nodetool relocatesstables` (RelocateSSTables.java:29) -> `nodetool-relocate-sstables.execute`, `component nodetool-relocate-sstables`
- `nodetool removenode` (RemoveNode.java:27) -> `nodetool-remove-node.execute`, `component nodetool-remove-node`
- `nodetool repair` (Repair.java:44) -> `nodetool-repair.execute`, `component nodetool-repair`, `flow nodetool-repair`
- `nodetool repair_admin cancel` (RepairAdmin.java:273) -> `nodetool-repair-admin-cancel-cmd.execute`, `nodetool-repair-admin-cleanup-data-cmd.execute`, `component nodetool-repair-admin-cancel-cmd`
- `nodetool repair_admin cleanup` (RepairAdmin.java:215) -> `nodetool-repair-admin-cancel-cmd.execute`, `nodetool-repair-admin-cleanup-data-cmd.execute`, `component nodetool-repair-admin-cancel-cmd`
- `nodetool replaybatchlog` (ReplayBatchlog.java:28) -> `nodetool-replay-batchlog.execute`, `component nodetool-replay-batchlog`
- `nodetool resetfullquerylog` (ResetFullQueryLog.java:25) -> `nodetool-reset-full-query-log.execute`, `component nodetool-reset-full-query-log`
- `nodetool resetlocalschema` (ResetLocalSchema.java:27) -> `nodetool-reset-local-schema.execute`, `component nodetool-reset-local-schema`
- `nodetool resumehandoff` (ResumeHandoff.java:25) -> `nodetool-resume-handoff.execute`, `component nodetool-resume-handoff`
- `nodetool scrub` (Scrub.java:31) -> `nodetool-scrub.execute`, `component nodetool-scrub`
- `nodetool setbatchlogreplaythrottle` (SetBatchlogReplayThrottle.java:25) -> `nodetool-set-batchlog-replay-throttle.execute`, `component nodetool-set-batchlog-replay-throttle`
- `nodetool setcachecapacity` (SetCacheCapacity.java:30) -> `nodetool-set-cache-capacity.execute`, `component nodetool-set-cache-capacity`
- `nodetool setcachekeystosave` (SetCacheKeysToSave.java:30) -> `nodetool-set-cache-keys-to-save.execute`, `component nodetool-set-cache-keys-to-save`
- `nodetool setcolumnindexsize` (SetColumnIndexSize.java:26) -> `nodetool-set-column-index-size.execute`, `component nodetool-set-column-index-size`
- `nodetool setcompactionthreshold` (SetCompactionThreshold.java:31) -> `nodetool-set-compaction-threshold.execute`, `component nodetool-set-compaction-threshold`
- `nodetool setcompactionthroughput` (SetCompactionThroughput.java:26) -> `nodetool-set-compaction-throughput.execute`, `component nodetool-set-compaction-throughput`, `flow nodetool-runtime-config`
- `nodetool setconcurrency` (SetConcurrency.java:30) -> `nodetool-set-concurrency.execute`, `component nodetool-set-concurrency`
- `nodetool setconcurrentcompactors` (SetConcurrentCompactors.java:27) -> `nodetool-set-concurrent-compactors.execute`, `component nodetool-set-concurrent-compactors`, `flow nodetool-runtime-config`
- `nodetool setconcurrentviewbuilders` (SetConcurrentViewBuilders.java:28) -> `nodetool-set-concurrent-view-builders.execute`, `component nodetool-set-concurrent-view-builders`
- `nodetool setdefaultrf` (SetDefaultKeyspaceRF.java:26) -> `nodetool-set-default-keyspace-rf.execute`, `component nodetool-set-default-keyspace-rf`
- `nodetool sethintedhandoffthrottlekb` (SetHintedHandoffThrottleInKB.java:26) -> `nodetool-set-hinted-handoff-throttle-in-kb.execute`, `component nodetool-set-hinted-handoff-throttle-in-kb`
- `nodetool setinterdcstreamthroughput` (SetInterDCStreamThroughput.java:26) -> `nodetool-set-inter-dcstream-throughput.execute`, `component nodetool-set-inter-dcstream-throughput`
- `nodetool setlogginglevel` (SetLoggingLevel.java:33) -> `nodetool-set-logging-level.execute`, `component nodetool-set-logging-level`
- `nodetool setmaxhintwindow` (SetMaxHintWindow.java:26) -> `nodetool-set-max-hint-window.execute`, `component nodetool-set-max-hint-window`
- `nodetool setsnapshotthrottle` (SetSnapshotThrottle.java:25) -> `nodetool-set-snapshot-throttle.execute`, `component nodetool-set-snapshot-throttle`
- `nodetool setstreamthroughput` (SetStreamThroughput.java:26) -> `nodetool-set-stream-throughput.execute`, `component nodetool-set-stream-throughput`
- `nodetool settimeout` (SetTimeout.java:31) -> `nodetool-set-timeout.execute`, `component nodetool-set-timeout`, `flow nodetool-runtime-config`
- `nodetool settraceprobability` (SetTraceProbability.java:27) -> `nodetool-set-trace-probability.execute`, `component nodetool-set-trace-probability`
- `nodetool snapshot` (Snapshot.java:39) -> `nodetool-snapshot.execute`, `component nodetool-snapshot`, `flow nodetool-snapshot`
- `nodetool sstablerepairedset` (SSTableRepairedSet.java:37) -> `nodetool-sstable-repaired-set.execute`, `component nodetool-sstable-repaired-set`
- `nodetool stop` (Stop.java:28) -> `nodetool-stop.execute`, `component nodetool-stop`
- `nodetool stopdaemon` (StopDaemon.java:27) -> `nodetool-stop-daemon.execute`, `component nodetool-stop-daemon`
- `nodetool truncatehints` (TruncateHints.java:27) -> `nodetool-truncate-hints.execute`, `component nodetool-truncate-hints`, `flow nodetool-hinted-handoff`
- `nodetool updatecidrgroup` (UpdateCIDRGroup.java:34) -> `nodetool-update-cidrgroup.execute`, `component nodetool-update-cidrgroup`
- `nodetool upgradesstables` (UpgradeSSTable.java:33) -> `nodetool-upgrade-sstable.execute`, `component nodetool-upgrade-sstable`
- `nodetool verify` (Verify.java:31) -> `nodetool-verify.execute`, `component nodetool-verify`

**java-main** (2)

- `org.apache.cassandra.service.CassandraDaemon` (CassandraDaemon.java:863) -> `cassandra-daemon.activate`, `component cassandra-daemon`, `flow daemon-startup`
- `org.apache.cassandra.tools.NodeTool` (NodeTool.java:85) -> `component node-tool`

**jmx-operation** (165)

- `ActiveRepairServiceMBean.cleanupPending` (ActiveRepairServiceMBean.java:65) -> `active-repair-service-mbean.cleanup-pending`, `nodetool-repair-admin-cleanup-data-cmd.execute`
- `ActiveRepairServiceMBean.failSession` (ActiveRepairServiceMBean.java:30) -> `active-repair-service-mbean.fail-session`, `nodetool-repair-admin-cancel-cmd.execute`
- `AuthCacheMBean.invalidate` (AuthCacheMBean.java:23) -> `nodetool-invalidate-credentials-cache.execute`, `nodetool-invalidate-jmx-permissions-cache.execute`, `nodetool-invalidate-network-permissions-cache.execute`
- `AuthorizationProxy.JmxPermissionsCacheMBean.invalidatePermissions` (AuthorizationProxy.java:592) -> `nodetool-invalidate-jmx-permissions-cache.execute`
- `BatchlogManagerMBean.forceBatchlogReplay` (BatchlogManagerMBean.java:37) -> `nodetool-replay-batchlog.execute`
- `CIDRGroupsMappingManagerMBean.dropCidrGroup` (CIDRGroupsMappingManagerMBean.java:58) -> `nodetool-drop-cidrgroup.execute`
- `CIDRGroupsMappingManagerMBean.loadCidrGroupsCache` (CIDRGroupsMappingManagerMBean.java:78) -> `nodetool-reload-cidrgroups-cache.execute`
- `CIDRGroupsMappingManagerMBean.updateCidrGroup` (CIDRGroupsMappingManagerMBean.java:51) -> `nodetool-update-cidrgroup.execute`
- `CIDRPermissionsManagerMBean.invalidateCidrPermissionsCache` (CIDRPermissionsManagerMBean.java:31) -> `nodetool-invalidate-cidrpermissions-cache.execute`
- `CacheServiceMBean.getRowCacheSavePeriodInSeconds` (CacheServiceMBean.java:24) -> `component cache-service-mbean`
- `CacheServiceMBean.invalidateCounterCache` (CacheServiceMBean.java:52) -> `cache-service-mbean.invalidate-row-cache`, `cache-service-mbean.invalidate-counter-cache`, `cache-service-mbean.set-row-cache-capacity-in-mb`
- `CacheServiceMBean.invalidateKeyCache` (CacheServiceMBean.java:45) -> `cache-service-mbean.invalidate-key-cache`, `nodetool-invalidate-key-cache.execute`
- `CacheServiceMBean.invalidateRowCache` (CacheServiceMBean.java:50) -> `cache-service-mbean.invalidate-row-cache`, `cache-service-mbean.invalidate-counter-cache`, `nodetool-invalidate-row-cache.execute`
- `CacheServiceMBean.saveCaches` (CacheServiceMBean.java:66) -> `cache-service-mbean.save-caches`
- `CacheServiceMBean.setCounterCacheCapacityInMB` (CacheServiceMBean.java:58) -> `cache-service-mbean.set-key-cache-capacity-in-mb`, `cache-service-mbean.set-counter-cache-capacity-in-mb`, `nodetool-set-cache-capacity.execute`
- `CacheServiceMBean.setCounterCacheKeysToSave` (CacheServiceMBean.java:40) -> `cache-service-mbean.set-key-cache-keys-to-save`, `cache-service-mbean.set-counter-cache-keys-to-save`, `nodetool-set-cache-keys-to-save.execute`
- `CacheServiceMBean.setKeyCacheCapacityInMB` (CacheServiceMBean.java:56) -> `cache-service-mbean.set-row-cache-capacity-in-mb`, `cache-service-mbean.set-key-cache-capacity-in-mb`, `cache-service-mbean.set-counter-cache-capacity-in-mb`
- `CacheServiceMBean.setKeyCacheKeysToSave` (CacheServiceMBean.java:37) -> `cache-service-mbean.set-row-cache-keys-to-save`, `cache-service-mbean.set-key-cache-keys-to-save`, `cache-service-mbean.set-counter-cache-keys-to-save`
- `CacheServiceMBean.setRowCacheCapacityInMB` (CacheServiceMBean.java:54) -> `cache-service-mbean.invalidate-counter-cache`, `cache-service-mbean.set-row-cache-capacity-in-mb`, `cache-service-mbean.set-key-cache-capacity-in-mb`
- `CacheServiceMBean.setRowCacheKeysToSave` (CacheServiceMBean.java:34) -> `cache-service-mbean.set-row-cache-keys-to-save`, `cache-service-mbean.set-key-cache-keys-to-save`, `nodetool-set-cache-keys-to-save.execute`
- `ColumnFamilyStoreMBean.importNewSSTables` (ColumnFamilyStoreMBean.java:191) -> `nodetool-import.execute`
- `ColumnFamilyStoreMBean.setCompactionThresholds` (ColumnFamilyStoreMBean.java:95) -> `nodetool-set-compaction-threshold.execute`
- `CompactionManagerMBean.forceUserDefinedCompaction` (CompactionManagerMBean.java:44) -> `nodetool-compact.execute`
- `CompactionManagerMBean.stopCompaction` (CompactionManagerMBean.java:66) -> `nodetool-stop.execute`
- `CompactionManagerMBean.stopCompactionById` (CompactionManagerMBean.java:74) -> `nodetool-stop.execute`
- `GossiperMBean.assassinateEndpoint` (GossiperMBean.java:32) -> `nodetool-assassinate.execute`, `nodetool-reload-seeds.execute`
- `GossiperMBean.reloadSeeds` (GossiperMBean.java:34) -> `nodetool-assassinate.execute`, `nodetool-reload-seeds.execute`
- `HintsServiceMBean.deleteAllHints` (HintsServiceMBean.java:39) -> `nodetool-truncate-hints.execute`
- `HintsServiceMBean.deleteAllHintsForEndpoint` (HintsServiceMBean.java:45) -> `nodetool-truncate-hints.execute`
- `HintsServiceMBean.pauseDispatch` (HintsServiceMBean.java:28) -> `nodetool-pause-handoff.execute`
- `HintsServiceMBean.resumeDispatch` (HintsServiceMBean.java:33) -> `nodetool-resume-handoff.execute`
- `MessagingServiceMBean.reloadSslCertificates` (MessagingServiceMBean.java:148) -> `nodetool-reload-ssl-certificates.execute`
- `NetworkPermissionsCacheMBean.invalidateNetworkPermissions` (NetworkPermissionsCacheMBean.java:28) -> `nodetool-invalidate-network-permissions-cache.execute`
- `PasswordAuthenticator.CredentialsCacheMBean.invalidateCredentials` (PasswordAuthenticator.java:345) -> `nodetool-invalidate-credentials-cache.execute`
- `PermissionsCacheMBean.invalidatePermissions` (PermissionsCacheMBean.java:25) -> `nodetool-invalidate-permissions-cache.execute`
- `RolesCacheMBean.invalidateRoles` (RolesCacheMBean.java:25) -> `nodetool-invalidate-roles-cache.execute`
- `StorageProxyMBean.denylistKey` (StorageProxyMBean.java:80) -> `storage-proxy-mbean.denylist-key`, `storage-proxy-mbean.remove-denylist-key`
- `StorageProxyMBean.disableCheckForDuplicateRowsDuringCompaction` (StorageProxyMBean.java:133) -> `storage-proxy-mbean.disable-check-for-duplicate-rows-during-reads`, `storage-proxy-mbean.enable-check-for-duplicate-rows-during-compaction`, `storage-proxy-mbean.disable-check-for-duplicate-rows-during-compaction`
- `StorageProxyMBean.disableCheckForDuplicateRowsDuringReads` (StorageProxyMBean.java:130) -> `storage-proxy-mbean.enable-check-for-duplicate-rows-during-reads`, `storage-proxy-mbean.disable-check-for-duplicate-rows-during-reads`, `storage-proxy-mbean.enable-check-for-duplicate-rows-during-compaction`
- `StorageProxyMBean.disableHintsForDC` (StorageProxyMBean.java:31) -> `storage-proxy-mbean.set-hinted-handoff-enabled`, `storage-proxy-mbean.set-max-hint-window`, `storage-proxy-mbean.enable-hints-for-dc`
- `StorageProxyMBean.disableRepairedDataTrackingForPartitionReads` (StorageProxyMBean.java:113) -> `storage-proxy-mbean.enable-repaired-data-tracking-for-partition-reads`, `storage-proxy-mbean.disable-repaired-data-tracking-for-partition-reads`, `storage-proxy-mbean.enable-reporting-unconfirmed-repaired-data-mismatches`
- `StorageProxyMBean.disableRepairedDataTrackingForRangeReads` (StorageProxyMBean.java:109) -> `storage-proxy-mbean.enable-repaired-data-tracking-for-range-reads`, `storage-proxy-mbean.disable-repaired-data-tracking-for-range-reads`, `storage-proxy-mbean.enable-repaired-data-tracking-for-partition-reads`
- `StorageProxyMBean.disableReportingUnconfirmedRepairedDataMismatches` (StorageProxyMBean.java:117) -> `storage-proxy-mbean.enable-reporting-unconfirmed-repaired-data-mismatches`, `storage-proxy-mbean.disable-reporting-unconfirmed-repaired-data-mismatches`, `storage-proxy-mbean.enable-snapshot-on-repaired-data-mismatch`
- `StorageProxyMBean.disableSnapshotOnDuplicateRowDetection` (StorageProxyMBean.java:125) -> `storage-proxy-mbean.enable-snapshot-on-duplicate-row-detection`, `storage-proxy-mbean.disable-snapshot-on-duplicate-row-detection`
- `StorageProxyMBean.disableSnapshotOnRepairedDataMismatch` (StorageProxyMBean.java:121) -> `storage-proxy-mbean.enable-snapshot-on-repaired-data-mismatch`, `storage-proxy-mbean.disable-snapshot-on-repaired-data-mismatch`, `storage-proxy-mbean.enable-snapshot-on-duplicate-row-detection`
- `StorageProxyMBean.enableCheckForDuplicateRowsDuringCompaction` (StorageProxyMBean.java:132) -> `storage-proxy-mbean.enable-check-for-duplicate-rows-during-reads`, `storage-proxy-mbean.disable-check-for-duplicate-rows-during-reads`, `storage-proxy-mbean.enable-check-for-duplicate-rows-during-compaction`
- `StorageProxyMBean.enableCheckForDuplicateRowsDuringReads` (StorageProxyMBean.java:129) -> `storage-proxy-mbean.enable-check-for-duplicate-rows-during-reads`, `storage-proxy-mbean.disable-check-for-duplicate-rows-during-reads`, `storage-proxy-mbean.enable-check-for-duplicate-rows-during-compaction`
- `StorageProxyMBean.enableHintsForDC` (StorageProxyMBean.java:30) -> `storage-proxy-mbean.set-hinted-handoff-enabled`, `storage-proxy-mbean.enable-hints-for-dc`, `storage-proxy-mbean.disable-hints-for-dc`
- `StorageProxyMBean.enableRepairedDataTrackingForPartitionReads` (StorageProxyMBean.java:112) -> `storage-proxy-mbean.disable-repaired-data-tracking-for-range-reads`, `storage-proxy-mbean.enable-repaired-data-tracking-for-partition-reads`, `storage-proxy-mbean.disable-repaired-data-tracking-for-partition-reads`
- `StorageProxyMBean.enableRepairedDataTrackingForRangeReads` (StorageProxyMBean.java:108) -> `storage-proxy-mbean.enable-repaired-data-tracking-for-range-reads`, `storage-proxy-mbean.disable-repaired-data-tracking-for-range-reads`
- `StorageProxyMBean.enableReportingUnconfirmedRepairedDataMismatches` (StorageProxyMBean.java:116) -> `storage-proxy-mbean.disable-repaired-data-tracking-for-partition-reads`, `storage-proxy-mbean.enable-reporting-unconfirmed-repaired-data-mismatches`, `storage-proxy-mbean.disable-reporting-unconfirmed-repaired-data-mismatches`
- `StorageProxyMBean.enableSnapshotOnDuplicateRowDetection` (StorageProxyMBean.java:124) -> `storage-proxy-mbean.disable-snapshot-on-repaired-data-mismatch`, `storage-proxy-mbean.enable-snapshot-on-duplicate-row-detection`, `storage-proxy-mbean.disable-snapshot-on-duplicate-row-detection`
- `StorageProxyMBean.enableSnapshotOnRepairedDataMismatch` (StorageProxyMBean.java:120) -> `storage-proxy-mbean.disable-reporting-unconfirmed-repaired-data-mismatches`, `storage-proxy-mbean.enable-snapshot-on-repaired-data-mismatch`, `storage-proxy-mbean.disable-snapshot-on-repaired-data-mismatch`
- `StorageProxyMBean.getHintedHandoffEnabled` (StorageProxyMBean.java:28) -> `storage-proxy-mbean.set-hinted-handoff-enabled`, `storage-proxy-mbean.enable-hints-for-dc`, `storage-proxy-mbean.disable-hints-for-dc`
- `StorageProxyMBean.getTotalHints` (StorageProxyMBean.java:27) -> `storage-proxy-mbean.set-hinted-handoff-enabled`, `storage-proxy-mbean.enable-hints-for-dc`, `storage-proxy-mbean.get-hinted-handoff-enabled`
- `StorageProxyMBean.isKeyDenylisted` (StorageProxyMBean.java:84) -> `storage-proxy-mbean.remove-denylist-key`, `storage-proxy-mbean.is-key-denylisted`
- `StorageProxyMBean.loadPartitionDenylist` (StorageProxyMBean.java:73) -> `storage-proxy-mbean.load-partition-denylist`
- `StorageProxyMBean.logBlockingReadRepairAttemptsForNSeconds` (StorageProxyMBean.java:102) -> `storage-proxy-mbean.log-blocking-read-repair-attempts-for-nseconds`
- `StorageProxyMBean.reloadTriggerClasses` (StorageProxyMBean.java:62) -> `storage-proxy-mbean.reload-trigger-classes`, `nodetool-reload-triggers.execute`
- `StorageProxyMBean.removeDenylistKey` (StorageProxyMBean.java:81) -> `storage-proxy-mbean.denylist-key`, `storage-proxy-mbean.remove-denylist-key`, `storage-proxy-mbean.is-key-denylisted`
- `StorageProxyMBean.setHintedHandoffEnabled` (StorageProxyMBean.java:29) -> `storage-proxy-mbean.set-hinted-handoff-enabled`, `storage-proxy-mbean.enable-hints-for-dc`, `storage-proxy-mbean.disable-hints-for-dc`
- `StorageProxyMBean.setMaxHintWindow` (StorageProxyMBean.java:34) -> `storage-proxy-mbean.set-max-hint-window`, `storage-proxy-mbean.disable-hints-for-dc`, `nodetool-disable-hints-for-dc.execute`
- `StorageServiceMBean.bulkLoad` (StorageServiceMBean.java:881) -> `storage-service-mbean.bulk-load`
- `StorageServiceMBean.bulkLoadAsync` (StorageServiceMBean.java:887) -> `storage-service-mbean.bulk-load-async`, `storage-service-mbean.reschedule-failed-deletions`
- `StorageServiceMBean.bypassConcurrentValidatorsLimit` (StorageServiceMBean.java:823) -> `storage-service-mbean.get-concurrent-compactors`, `storage-service-mbean.set-concurrent-compactors`, `storage-service-mbean.bypass-concurrent-validators-limit`
- `StorageServiceMBean.cleanupSizeEstimates` (StorageServiceMBean.java:360) -> `storage-service-mbean.cleanup-size-estimates`
- `StorageServiceMBean.clearConnectionHistory` (StorageServiceMBean.java:1108) -> `storage-service-mbean.clear-connection-history`, `storage-service-mbean.enable-audit-log`, `storage-service-mbean.disable-audit-log`
- `StorageServiceMBean.clearPaxosRepairs` (StorageServiceMBean.java:1270) -> `storage-service-mbean.evict-hung-repairs`, `storage-service-mbean.clear-paxos-repairs`
- `StorageServiceMBean.clearSnapshot` (StorageServiceMBean.java:302) -> `nodetool-clear-snapshot.execute`
- `StorageServiceMBean.decommission` (StorageServiceMBean.java:509) -> `nodetool-decommission.execute`, `flow nodetool-decommission`
- `StorageServiceMBean.deliverHints` (StorageServiceMBean.java:972) -> `storage-service-mbean.enable-auto-compaction`, `storage-service-mbean.deliver-hints`, `nodetool-enable-auto-compaction.execute`
- `StorageServiceMBean.disableAuditLog` (StorageServiceMBean.java:1109) -> `storage-service-mbean.clear-connection-history`, `storage-service-mbean.enable-audit-log`, `storage-service-mbean.disable-audit-log`
- `StorageServiceMBean.disableAutoCompaction` (StorageServiceMBean.java:968) -> `storage-service-mbean.disable-auto-compaction`, `storage-service-mbean.enable-auto-compaction`, `storage-service-mbean.get-trace-probability`
- `StorageServiceMBean.disableNativeTransportOldProtocolVersions` (StorageServiceMBean.java:679) -> `storage-service-mbean.start-native-transport`, `storage-service-mbean.enable-native-transport-old-protocol-versions`, `storage-service-mbean.disable-native-transport-old-protocol-versions`
- `StorageServiceMBean.drain` (StorageServiceMBean.java:581) -> `nodetool-drain.execute`, `flow nodetool-drain`
- `StorageServiceMBean.dropPreparedStatements` (StorageServiceMBean.java:1332) -> `storage-service-mbean.drop-prepared-statements`
- `StorageServiceMBean.enableAuditLog` (StorageServiceMBean.java:1110) -> `storage-service-mbean.clear-connection-history`, `storage-service-mbean.enable-audit-log`, `storage-service-mbean.disable-audit-log`
- `StorageServiceMBean.enableAutoCompaction` (StorageServiceMBean.java:969) -> `storage-service-mbean.disable-auto-compaction`, `storage-service-mbean.enable-auto-compaction`, `storage-service-mbean.deliver-hints`
- `StorageServiceMBean.enableFullQueryLogger` (StorageServiceMBean.java:1145) -> `storage-service-mbean.enable-full-query-logger`, `nodetool-enable-full-query-log.execute`
- `StorageServiceMBean.enableNativeTransportOldProtocolVersions` (StorageServiceMBean.java:678) -> `storage-service-mbean.start-native-transport`, `storage-service-mbean.enable-native-transport-old-protocol-versions`, `storage-service-mbean.disable-native-transport-old-protocol-versions`
- `StorageServiceMBean.enforceConcurrentValidatorsLimit` (StorageServiceMBean.java:824) -> `storage-service-mbean.set-concurrent-compactors`, `storage-service-mbean.bypass-concurrent-validators-limit`, `storage-service-mbean.enforce-concurrent-validators-limit`
- `StorageServiceMBean.evictHungRepairs` (StorageServiceMBean.java:1269) -> `storage-service-mbean.evict-hung-repairs`, `storage-service-mbean.clear-paxos-repairs`
- `StorageServiceMBean.forceCompactionKeysIgnoringGcGrace` (StorageServiceMBean.java:392) -> `storage-service-mbean.force-compaction-keys-ignoring-gc-grace`, `nodetool-force-compact.execute`
- `StorageServiceMBean.forceKeyspaceCleanup` (StorageServiceMBean.java:399) -> `storage-service-mbean.force-keyspace-cleanup`, `nodetool-cleanup.execute`, `flow nodetool-cleanup`
- `StorageServiceMBean.forceKeyspaceCompaction` (StorageServiceMBean.java:365) -> `storage-service-mbean.force-keyspace-compaction`, `nodetool-compact.execute`
- `StorageServiceMBean.forceKeyspaceCompactionForPartitionKey` (StorageServiceMBean.java:385) -> `storage-service-mbean.force-keyspace-compaction-for-partition-key`, `nodetool-compact.execute`
- `StorageServiceMBean.forceKeyspaceCompactionForTokenRange` (StorageServiceMBean.java:380) -> `storage-service-mbean.force-keyspace-compaction-for-token-range`, `nodetool-compact.execute`
- `StorageServiceMBean.forceKeyspaceFlush` (StorageServiceMBean.java:463) -> `storage-service-mbean.force-keyspace-flush`, `nodetool-flush.execute`, `flow nodetool-flush`
- `StorageServiceMBean.forceRemoveCompletion` (StorageServiceMBean.java:550) -> `nodetool-remove-node.execute`
- `StorageServiceMBean.forceTerminateAllRepairSessions` (StorageServiceMBean.java:478) -> `storage-service-mbean.force-terminate-all-repair-sessions`, `repair-runner.run`
- `StorageServiceMBean.garbageCollect` (StorageServiceMBean.java:454) -> `storage-service-mbean.garbage-collect`, `nodetool-garbage-collect.execute`
- `StorageServiceMBean.getBootstrapState` (StorageServiceMBean.java:1087) -> `nodetool-decommission.execute`, `nodetool-bootstrap-resume.execute`
- `StorageServiceMBean.getCompactionThroughputMbPerSec` (StorageServiceMBean.java:811) -> `storage-service-mbean.set-compaction-throughput-mb-per-sec`, `storage-service-mbean.get-compaction-throughput-mb-per-sec`, `nodetool-set-compaction-throughput.execute`
- `StorageServiceMBean.getConcurrentCompactors` (StorageServiceMBean.java:820) -> `storage-service-mbean.get-concurrent-compactors`, `storage-service-mbean.set-concurrent-compactors`, `storage-service-mbean.set-batchlog-replay-throttle-in-kb`
- `StorageServiceMBean.getKeyspaces` (StorageServiceMBean.java:614) -> `storage-service-mbean.get-keyspaces`, `storage-service-mbean.get-non-system-keyspaces`
- `StorageServiceMBean.getNonLocalStrategyKeyspaces` (StorageServiceMBean.java:618) -> `storage-service-mbean.get-non-local-strategy-keyspaces`, `storage-service-mbean.get-non-system-keyspaces`
- `StorageServiceMBean.getNonSystemKeyspaces` (StorageServiceMBean.java:616) -> `storage-service-mbean.get-keyspaces`, `storage-service-mbean.get-non-local-strategy-keyspaces`, `storage-service-mbean.get-non-system-keyspaces`
- `StorageServiceMBean.getParentRepairStatus` (StorageServiceMBean.java:503) -> `storage-service-mbean.get-parent-repair-status`
- `StorageServiceMBean.getTraceProbability` (StorageServiceMBean.java:966) -> `storage-service-mbean.disable-auto-compaction`, `storage-service-mbean.enable-auto-compaction`, `storage-service-mbean.get-trace-probability`
- `StorageServiceMBean.isAuditLogEnabled` (StorageServiceMBean.java:1130) -> `storage-service-mbean.is-audit-log-enabled`
- `StorageServiceMBean.isBootstrapMode` (StorageServiceMBean.java:701) -> `nodetool-join.execute`
- `StorageServiceMBean.isDecommissioning` (StorageServiceMBean.java:526) -> `nodetool-decommission.execute`
- `StorageServiceMBean.isFullQueryLogEnabled` (StorageServiceMBean.java:1158) -> `storage-service-mbean.stop-full-query-logger`, `storage-service-mbean.is-full-query-log-enabled`, `nodetool-disable-full-query-log.execute`
- `StorageServiceMBean.isIncrementalBackupsEnabled` (StorageServiceMBean.java:844) -> `storage-service-mbean.set-incremental-backups-enabled`, `storage-service-mbean.set-concurrent-view-builders`, `storage-service-mbean.is-incremental-backups-enabled`
- `StorageServiceMBean.isJoined` (StorageServiceMBean.java:693) -> `nodetool-join.execute`
- `StorageServiceMBean.joinRing` (StorageServiceMBean.java:692) -> `nodetool-join.execute`
- `StorageServiceMBean.loadNewSSTables` (StorageServiceMBean.java:901) -> `storage-service-mbean.load-new-sstables`, `nodetool-refresh.execute`
- `StorageServiceMBean.move` (StorageServiceMBean.java:532) -> `nodetool-move.execute`
- `StorageServiceMBean.mutateSSTableRepairedState` (StorageServiceMBean.java:1338) -> `storage-service-mbean.mutate-sstable-repaired-state`, `nodetool-sstable-repaired-set.execute`
- `StorageServiceMBean.rebuild` (StorageServiceMBean.java:854) -> `nodetool-rebuild.execute`
- `StorageServiceMBean.rebuildSecondaryIndex` (StorageServiceMBean.java:916) -> `storage-service-mbean.reset-local-schema`, `storage-service-mbean.rebuild-secondary-index`, `nodetool-reset-local-schema.execute`
- `StorageServiceMBean.recompressSSTables` (StorageServiceMBean.java:448) -> `storage-service-mbean.recompress-sstables`, `nodetool-recompress-sstables.execute`
- `StorageServiceMBean.refreshSizeEstimates` (StorageServiceMBean.java:355) -> `storage-service-mbean.refresh-size-estimates`, `nodetool-refresh-size-estimates.execute`
- `StorageServiceMBean.reloadLocalSchema` (StorageServiceMBean.java:920) -> `storage-service-mbean.reset-local-schema`, `storage-service-mbean.reload-local-schema`, `nodetool-reload-local-schema.execute`
- `StorageServiceMBean.relocateSSTables` (StorageServiceMBean.java:369) -> `storage-service-mbean.relocate-sstables`, `nodetool-relocate-sstables.execute`
- `StorageServiceMBean.removeNode` (StorageServiceMBean.java:538) -> `nodetool-remove-node.execute`
- `StorageServiceMBean.repairAsync` (StorageServiceMBean.java:476) -> `storage-service-mbean.force-terminate-all-repair-sessions`, `repair-runner.run`
- `StorageServiceMBean.rescheduleFailedDeletions` (StorageServiceMBean.java:889) -> `storage-service-mbean.bulk-load-async`, `storage-service-mbean.reschedule-failed-deletions`
- `StorageServiceMBean.resetFullQueryLogger` (StorageServiceMBean.java:1151) -> `storage-service-mbean.reset-full-query-logger`, `nodetool-reset-full-query-log.execute`
- `StorageServiceMBean.resetLocalSchema` (StorageServiceMBean.java:918) -> `storage-service-mbean.reset-local-schema`, `storage-service-mbean.reload-local-schema`, `storage-service-mbean.rebuild-secondary-index`
- `StorageServiceMBean.resumeBootstrap` (StorageServiceMBean.java:1085) -> `nodetool-decommission.execute`, `nodetool-bootstrap-resume.execute`
- `StorageServiceMBean.scrub` (StorageServiceMBean.java:410) -> `storage-service-mbean.scrub`, `nodetool-scrub.execute`
- `StorageServiceMBean.setBatchlogReplayThrottleInKB` (StorageServiceMBean.java:818) -> `storage-service-mbean.get-concurrent-compactors`, `storage-service-mbean.set-concurrent-compactors`, `storage-service-mbean.set-batchlog-replay-throttle-in-kb`
- `StorageServiceMBean.setCasContentionTimeout` (StorageServiceMBean.java:737) -> `storage-service-mbean.set-counter-write-rpc-timeout`, `storage-service-mbean.set-cas-contention-timeout`, `storage-service-mbean.set-truncate-rpc-timeout`
- `StorageServiceMBean.setColumnIndexSize` (StorageServiceMBean.java:1018) -> `storage-service-mbean.set-column-index-size`, `nodetool-set-column-index-size.execute`
- `StorageServiceMBean.setCompactionThroughputMbPerSec` (StorageServiceMBean.java:812) -> `storage-service-mbean.set-compaction-throughput-mb-per-sec`, `storage-service-mbean.get-compaction-throughput-mb-per-sec`, `nodetool-set-compaction-throughput.execute`
- `StorageServiceMBean.setConcurrency` (StorageServiceMBean.java:1105) -> `storage-service-mbean.clear-connection-history`, `storage-service-mbean.set-concurrency`, `nodetool-set-concurrency.execute`
- `StorageServiceMBean.setConcurrentCompactors` (StorageServiceMBean.java:821) -> `storage-service-mbean.get-concurrent-compactors`, `storage-service-mbean.set-concurrent-compactors`, `storage-service-mbean.set-batchlog-replay-throttle-in-kb`
- `StorageServiceMBean.setConcurrentViewBuilders` (StorageServiceMBean.java:842) -> `storage-service-mbean.set-incremental-backups-enabled`, `storage-service-mbean.set-concurrent-view-builders`, `storage-service-mbean.is-incremental-backups-enabled`
- `StorageServiceMBean.setCounterWriteRpcTimeout` (StorageServiceMBean.java:734) -> `storage-service-mbean.set-counter-write-rpc-timeout`, `storage-service-mbean.set-cas-contention-timeout`, `storage-service-mbean.set-internode-streaming-tcp-user-timeout-in-ms`
- `StorageServiceMBean.setDefaultKeyspaceReplicationFactor` (StorageServiceMBean.java:1232) -> `storage-service-mbean.set-default-keyspace-replication-factor`, `nodetool-set-default-keyspace-rf.execute`
- `StorageServiceMBean.setEntireSSTableInterDCStreamThroughputMebibytesPerSec` (StorageServiceMBean.java:801) -> `storage-service-mbean.set-entire-sstable-stream-throughput-mebibytes-per-sec`, `storage-service-mbean.set-entire-sstable-inter-dcstream-throughput-mebibytes-per-sec`, `nodetool-set-stream-throughput.execute`
- `StorageServiceMBean.setEntireSSTableStreamThroughputMebibytesPerSec` (StorageServiceMBean.java:798) -> `storage-service-mbean.set-entire-sstable-stream-throughput-mebibytes-per-sec`, `storage-service-mbean.set-entire-sstable-inter-dcstream-throughput-mebibytes-per-sec`, `nodetool-set-stream-throughput.execute`
- `StorageServiceMBean.setHintedHandoffThrottleInKB` (StorageServiceMBean.java:1064) -> `storage-service-mbean.set-hinted-handoff-throttle-in-kb`, `nodetool-set-hinted-handoff-throttle-in-kb.execute`
- `StorageServiceMBean.setIncrementalBackupsEnabled` (StorageServiceMBean.java:845) -> `storage-service-mbean.set-incremental-backups-enabled`, `storage-service-mbean.set-concurrent-view-builders`, `storage-service-mbean.is-incremental-backups-enabled`
- `StorageServiceMBean.setInterDCStreamThroughputMbitPerSec` (StorageServiceMBean.java:770) -> `storage-service-mbean.set-inter-dcstream-throughput-mbit-per-sec`, `nodetool-set-inter-dcstream-throughput.execute`
- `StorageServiceMBean.setInterDCStreamThroughputMebibytesPerSec` (StorageServiceMBean.java:790) -> `storage-service-mbean.set-inter-dcstream-throughput-mebibytes-per-sec`, `nodetool-set-inter-dcstream-throughput.execute`
- `StorageServiceMBean.setInternodeStreamingTcpUserTimeoutInMS` (StorageServiceMBean.java:731) -> `storage-service-mbean.set-internode-tcp-user-timeout-in-ms`, `storage-service-mbean.set-counter-write-rpc-timeout`, `storage-service-mbean.set-internode-streaming-tcp-user-timeout-in-ms`
- `StorageServiceMBean.setInternodeTcpConnectTimeoutInMS` (StorageServiceMBean.java:725) -> `storage-service-mbean.set-write-rpc-timeout`, `storage-service-mbean.set-internode-tcp-connect-timeout-in-ms`, `storage-service-mbean.set-internode-tcp-user-timeout-in-ms`
- `StorageServiceMBean.setInternodeTcpUserTimeoutInMS` (StorageServiceMBean.java:728) -> `storage-service-mbean.set-internode-tcp-connect-timeout-in-ms`, `storage-service-mbean.set-internode-tcp-user-timeout-in-ms`, `storage-service-mbean.set-internode-streaming-tcp-user-timeout-in-ms`
- `StorageServiceMBean.setLoggingLevel` (StorageServiceMBean.java:566) -> `storage-service-mbean.set-logging-level`, `nodetool-set-logging-level.execute`
- `StorageServiceMBean.setRangeRpcTimeout` (StorageServiceMBean.java:719) -> `storage-service-mbean.set-read-rpc-timeout`, `storage-service-mbean.set-range-rpc-timeout`, `storage-service-mbean.set-write-rpc-timeout`
- `StorageServiceMBean.setReadRpcTimeout` (StorageServiceMBean.java:716) -> `storage-service-mbean.set-rpc-timeout`, `storage-service-mbean.set-read-rpc-timeout`, `storage-service-mbean.set-range-rpc-timeout`
- `StorageServiceMBean.setRpcTimeout` (StorageServiceMBean.java:713) -> `storage-service-mbean.set-rpc-timeout`, `storage-service-mbean.set-read-rpc-timeout`
- `StorageServiceMBean.setSnapshotLinksPerSecond` (StorageServiceMBean.java:342) -> `storage-service-mbean.set-snapshot-links-per-second`, `nodetool-set-snapshot-throttle.execute`
- `StorageServiceMBean.setStreamThroughputMbitPerSec` (StorageServiceMBean.java:743) -> `storage-service-mbean.set-stream-throughput-mbit-per-sec`, `storage-service-mbean.set-truncate-rpc-timeout`, `nodetool-set-stream-throughput.execute`
- `StorageServiceMBean.setStreamThroughputMebibytesPerSec` (StorageServiceMBean.java:762) -> `storage-service-mbean.set-stream-throughput-mebibytes-per-sec`, `nodetool-set-stream-throughput.execute`
- `StorageServiceMBean.setTraceProbability` (StorageServiceMBean.java:929) -> `storage-service-mbean.set-trace-probability`, `nodetool-set-trace-probability.execute`
- `StorageServiceMBean.setTruncateRpcTimeout` (StorageServiceMBean.java:740) -> `storage-service-mbean.set-stream-throughput-mbit-per-sec`, `storage-service-mbean.set-cas-contention-timeout`, `storage-service-mbean.set-truncate-rpc-timeout`
- `StorageServiceMBean.setWriteRpcTimeout` (StorageServiceMBean.java:722) -> `storage-service-mbean.set-range-rpc-timeout`, `storage-service-mbean.set-write-rpc-timeout`, `storage-service-mbean.set-internode-tcp-connect-timeout-in-ms`
- `StorageServiceMBean.startGossiping` (StorageServiceMBean.java:663) -> `nodetool-disable-gossip.execute`, `nodetool-enable-gossip.execute`
- `StorageServiceMBean.startNativeTransport` (StorageServiceMBean.java:676) -> `storage-service-mbean.start-native-transport`, `storage-service-mbean.stop-native-transport`, `storage-service-mbean.enable-native-transport-old-protocol-versions`
- `StorageServiceMBean.startSamplingPartitions` (StorageServiceMBean.java:946) -> `storage-service-mbean.start-sampling-partitions`
- `StorageServiceMBean.stopDaemon` (StorageServiceMBean.java:669) -> `storage-service-mbean.stop-daemon`, `nodetool-stop-daemon.execute`
- `StorageServiceMBean.stopFullQueryLogger` (StorageServiceMBean.java:1156) -> `storage-service-mbean.stop-full-query-logger`, `storage-service-mbean.is-full-query-log-enabled`, `nodetool-disable-full-query-log.execute`
- `StorageServiceMBean.stopGossiping` (StorageServiceMBean.java:660) -> `nodetool-disable-gossip.execute`, `nodetool-enable-gossip.execute`
- `StorageServiceMBean.stopNativeTransport` (StorageServiceMBean.java:674) -> `storage-service-mbean.start-native-transport`, `storage-service-mbean.stop-native-transport`, `nodetool-disable-binary.execute`
- `StorageServiceMBean.stopSamplingPartitions` (StorageServiceMBean.java:954) -> `storage-service-mbean.stop-sampling-partitions`
- `StorageServiceMBean.takeMultipleTableSnapshot` (StorageServiceMBean.java:279) -> `storage-service-mbean.take-multiple-table-snapshot`
- `StorageServiceMBean.takeSnapshot` (StorageServiceMBean.java:267) -> `nodetool-snapshot.execute`, `flow nodetool-snapshot`
- `StorageServiceMBean.takeTableSnapshot` (StorageServiceMBean.java:273) -> `storage-service-mbean.take-table-snapshot`
- `StorageServiceMBean.truncate` (StorageServiceMBean.java:593) -> `storage-service-mbean.truncate`
- `StorageServiceMBean.updateSnitch` (StorageServiceMBean.java:640) -> `storage-service-mbean.update-snitch`
- `StorageServiceMBean.upgradeSSTables` (StorageServiceMBean.java:439) -> `storage-service-mbean.upgrade-sstables`, `nodetool-upgrade-sstable.execute`
- `StorageServiceMBean.verify` (StorageServiceMBean.java:430) -> `storage-service-mbean.verify`, `nodetool-verify.execute`

**scheduled-task** (3)

- `CassandraDaemon.setup: ColumnFamilyStore.getBackgroundCompactionTaskSubmitter` (CassandraDaemon.java:435) -> `cassandra-daemon.setup`
- `CassandraDaemon.setup: SPECULATION_THRESHOLD_UPDATER` (CassandraDaemon.java:438) -> `cassandra-daemon.setup`
- `CassandraDaemon.setup: SizeEstimatesRecorder.instance` (CassandraDaemon.java:371) -> `cassandra-daemon.setup`

**stage-task** (2)

- `Stage.TRACING TraceStateImpl.executeMutation: mutateWithCatch` (TraceStateImpl.java:106) -> `trace-state-impl.execute-mutation`
- `Stage.TRACING TracingImpl.trace: WrappedRunnable` (TracingImpl.java:110) -> `tracing-impl.trace`, `flow tracing-remote-event`

### Skipped entry points (858)

Groups are exact: every entry listed belongs to its group and to no other. Format: `kind name` (file:line).


#### guardrails (136)

Reason: GuardrailsMBean threshold/flag getters and setters (db/guardrails): each reads or assigns one GuardrailsConfig field; enforcement happens where each guardrail is checked (cql/schema paths), not here.

- GuardrailsMBean (136): getAllowFilteringEnabled (GuardrailsMBean.java:216), getAlterTableEnabled (GuardrailsMBean.java:272), getCollectionSizeFailThreshold (GuardrailsMBean.java:556), getCollectionSizeWarnThreshold (GuardrailsMBean.java:548), getColumnValueSizeFailThreshold (GuardrailsMBean.java:530), getColumnValueSizeWarnThreshold (GuardrailsMBean.java:523), getColumnsPerTableFailThreshold (GuardrailsMBean.java:83), getColumnsPerTableWarnThreshold (GuardrailsMBean.java:78), getCompactTablesEnabled (GuardrailsMBean.java:258), getDataDiskUsageMaxDiskSize (GuardrailsMBean.java:652), getDataDiskUsagePercentageFailThreshold (GuardrailsMBean.java:636), getDataDiskUsagePercentageWarnThreshold (GuardrailsMBean.java:630), getDropKeyspaceEnabled (GuardrailsMBean.java:312), getDropTruncateTableEnabled (GuardrailsMBean.java:300), getFieldsPerUDTFailThreshold (GuardrailsMBean.java:592), getFieldsPerUDTWarnThreshold (GuardrailsMBean.java:587), getGroupByEnabled (GuardrailsMBean.java:286), getInSelectCartesianProductFailThreshold (GuardrailsMBean.java:381), getInSelectCartesianProductWarnThreshold (GuardrailsMBean.java:375), getIntersectFilteringQueryEnabled (GuardrailsMBean.java:902), getIntersectFilteringQueryWarned (GuardrailsMBean.java:894), getItemsPerCollectionFailThreshold (GuardrailsMBean.java:576), getItemsPerCollectionWarnThreshold (GuardrailsMBean.java:571), getKeyspacesFailThreshold (GuardrailsMBean.java:48), getKeyspacesWarnThreshold (GuardrailsMBean.java:42), getMaterializedViewsPerTableFailThreshold (GuardrailsMBean.java:129), getMaterializedViewsPerTableWarnThreshold (GuardrailsMBean.java:123), getMaximumReplicationFactorFailThreshold (GuardrailsMBean.java:687), getMaximumReplicationFactorWarnThreshold (GuardrailsMBean.java:682), getMaximumTimestampFailThreshold (GuardrailsMBean.java:742), getMaximumTimestampWarnThreshold (GuardrailsMBean.java:734), getMinimumReplicationFactorFailThreshold (GuardrailsMBean.java:669), getMinimumReplicationFactorWarnThreshold (GuardrailsMBean.java:664), getMinimumTimestampFailThreshold (GuardrailsMBean.java:770), getMinimumTimestampWarnThreshold (GuardrailsMBean.java:762), getNonPartitionRestrictedQueryEnabled (GuardrailsMBean.java:880), getPageSizeFailThreshold (GuardrailsMBean.java:329), getPageSizeWarnThreshold (GuardrailsMBean.java:323), getPartitionKeysInSelectFailThreshold (GuardrailsMBean.java:361), getPartitionKeysInSelectWarnThreshold (GuardrailsMBean.java:355), getPartitionSizeFailThreshold (GuardrailsMBean.java:485), getPartitionSizeWarnThreshold (GuardrailsMBean.java:476), getPartitionTombstonesFailThreshold (GuardrailsMBean.java:508), getPartitionTombstonesWarnThreshold (GuardrailsMBean.java:501), getReadBeforeWriteListOperationsEnabled (GuardrailsMBean.java:342), getReadConsistencyLevelsDisallowed (GuardrailsMBean.java:414), getReadConsistencyLevelsDisallowedCSV (GuardrailsMBean.java:419), getReadConsistencyLevelsWarned (GuardrailsMBean.java:394), getReadConsistencyLevelsWarnedCSV (GuardrailsMBean.java:399), getSaiFrozenTermSizeFailThreshold (GuardrailsMBean.java:838), getSaiFrozenTermSizeWarnThreshold (GuardrailsMBean.java:831), getSaiSSTableIndexesPerQueryFailThreshold (GuardrailsMBean.java:792), getSaiSSTableIndexesPerQueryWarnThreshold (GuardrailsMBean.java:787), getSaiStringTermSizeFailThreshold (GuardrailsMBean.java:814), getSaiStringTermSizeWarnThreshold (GuardrailsMBean.java:807), getSaiVectorTermSizeFailThreshold (GuardrailsMBean.java:862), getSaiVectorTermSizeWarnThreshold (GuardrailsMBean.java:855), getSecondaryIndexesEnabled (GuardrailsMBean.java:110), getSecondaryIndexesPerTableFailThreshold (GuardrailsMBean.java:99), getSecondaryIndexesPerTableWarnThreshold (GuardrailsMBean.java:94), getSimpleStrategyEnabled (GuardrailsMBean.java:230), getTablePropertiesDisallowed (GuardrailsMBean.java:160), getTablePropertiesDisallowedCSV (GuardrailsMBean.java:165), getTablePropertiesIgnored (GuardrailsMBean.java:180), getTablePropertiesIgnoredCSV (GuardrailsMBean.java:185), getTablePropertiesWarned (GuardrailsMBean.java:140), getTablePropertiesWarnedCSV (GuardrailsMBean.java:145), getTablesFailThreshold (GuardrailsMBean.java:66), getTablesWarnThreshold (GuardrailsMBean.java:60), getUncompressedTablesEnabled (GuardrailsMBean.java:244), getUserTimestampsEnabled (GuardrailsMBean.java:202), getVectorDimensionsFailThreshold (GuardrailsMBean.java:608), getVectorDimensionsWarnThreshold (GuardrailsMBean.java:603), getVectorTypeEnabled (GuardrailsMBean.java:624), getWriteConsistencyLevelsDisallowed (GuardrailsMBean.java:454), getWriteConsistencyLevelsDisallowedCSV (GuardrailsMBean.java:459), getWriteConsistencyLevelsWarned (GuardrailsMBean.java:434), getWriteConsistencyLevelsWarnedCSV (GuardrailsMBean.java:439), getZeroTTLOnTWCSEnabled (GuardrailsMBean.java:719), getZeroTTLOnTWCSWarned (GuardrailsMBean.java:703), setAllowFilteringEnabled (GuardrailsMBean.java:223), setAlterTableEnabled (GuardrailsMBean.java:279), setCollectionSizeThreshold (GuardrailsMBean.java:566), setColumnValueSizeThreshold (GuardrailsMBean.java:540), setColumnsPerTableThreshold (GuardrailsMBean.java:89), setCompactTablesEnabled (GuardrailsMBean.java:265), setDataDiskUsageMaxDiskSize (GuardrailsMBean.java:659), setDataDiskUsagePercentageThreshold (GuardrailsMBean.java:644), setDropKeyspaceEnabled (GuardrailsMBean.java:317), setDropTruncateTableEnabled (GuardrailsMBean.java:305), setFieldsPerUDTThreshold (GuardrailsMBean.java:598), setGroupByEnabled (GuardrailsMBean.java:293), setInSelectCartesianProductThreshold (GuardrailsMBean.java:389), setIntersectFilteringQueryEnabled (GuardrailsMBean.java:904), setIntersectFilteringQueryWarned (GuardrailsMBean.java:896), setItemsPerCollectionThreshold (GuardrailsMBean.java:582), setKeyspacesThreshold (GuardrailsMBean.java:54), setMaterializedViewsPerTableThreshold (GuardrailsMBean.java:135), setMaximumReplicationFactorThreshold (GuardrailsMBean.java:695), setMaximumTimestampThreshold (GuardrailsMBean.java:754), setMinimumReplicationFactorThreshold (GuardrailsMBean.java:677), setMinimumTimestampThreshold (GuardrailsMBean.java:782), setNonPartitionRestrictedQueryEnabled (GuardrailsMBean.java:888), setPageSizeThreshold (GuardrailsMBean.java:335), setPartitionKeysInSelectThreshold (GuardrailsMBean.java:369), setPartitionSizeThreshold (GuardrailsMBean.java:496), setPartitionTombstonesThreshold (GuardrailsMBean.java:516), setReadBeforeWriteListOperationsEnabled (GuardrailsMBean.java:349), setReadConsistencyLevelsDisallowed (GuardrailsMBean.java:424), setReadConsistencyLevelsDisallowedCSV (GuardrailsMBean.java:429), setReadConsistencyLevelsWarned (GuardrailsMBean.java:404), setReadConsistencyLevelsWarnedCSV (GuardrailsMBean.java:409), setSaiFrozenTermSizeThreshold (GuardrailsMBean.java:848), setSaiSSTableIndexesPerQueryThreshold (GuardrailsMBean.java:800), setSaiStringTermSizeThreshold (GuardrailsMBean.java:824), setSaiVectorTermSizeThreshold (GuardrailsMBean.java:872), setSecondaryIndexesEnabled (GuardrailsMBean.java:117), setSecondaryIndexesPerTableThreshold (GuardrailsMBean.java:105), setSimpleStrategyEnabled (GuardrailsMBean.java:237), setTablePropertiesDisallowed (GuardrailsMBean.java:170), setTablePropertiesDisallowedCSV (GuardrailsMBean.java:175), setTablePropertiesIgnored (GuardrailsMBean.java:190), setTablePropertiesIgnoredCSV (GuardrailsMBean.java:195), setTablePropertiesWarned (GuardrailsMBean.java:150), setTablePropertiesWarnedCSV (GuardrailsMBean.java:155), setTablesThreshold (GuardrailsMBean.java:72), setUncompressedTablesEnabled (GuardrailsMBean.java:251), setUserTimestampsEnabled (GuardrailsMBean.java:209), setVectorDimensionsThreshold (GuardrailsMBean.java:614), setVectorTypeEnabled (GuardrailsMBean.java:619), setWriteConsistencyLevelsDisallowed (GuardrailsMBean.java:464), setWriteConsistencyLevelsDisallowedCSV (GuardrailsMBean.java:469), setWriteConsistencyLevelsWarned (GuardrailsMBean.java:444), setWriteConsistencyLevelsWarnedCSV (GuardrailsMBean.java:449), setZeroTTLOnTWCSEnabled (GuardrailsMBean.java:726), setZeroTTLOnTWCSWarned (GuardrailsMBean.java:711)

#### autorepair (26)

Reason: AutoRepairServiceMBean (service/AutoRepairService.java) scheduler configuration: auto-repair is disabled in the deployed config (auto_repair commented out in cassandra.yaml 2342; AutoRepairConfig() enabled=false and cassandra.autorepair.enable=false, AutoRepairConfig.java:127-146, CassandraRelevantProperties.java:62).

- AutoRepairServiceMBean (26): getAutoRepairConfiguration (AutoRepairServiceMBean.java:64), getOnGoingRepairHostIds (AutoRepairServiceMBean.java:68), isAutoRepairDisabled (AutoRepairServiceMBean.java:62), setAllowParallelReplicaRepair (AutoRepairServiceMBean.java:56), setAllowParallelReplicaRepairAcrossSchedules (AutoRepairServiceMBean.java:58), setAutoRepairEnabled (AutoRepairServiceMBean.java:28), setAutoRepairHistoryClearDeleteHostsBufferDuration (AutoRepairServiceMBean.java:40), setAutoRepairMaxRetriesCount (AutoRepairServiceMBean.java:74), setAutoRepairMinRepairTaskDuration (AutoRepairServiceMBean.java:42), setAutoRepairRetryBackoff (AutoRepairServiceMBean.java:76), setAutoRepairTableMaxRepairTime (AutoRepairServiceMBean.java:46), setAutoRepairTokenRangeSplitterParameter (AutoRepairServiceMBean.java:70), setForceRepairForHosts (AutoRepairServiceMBean.java:34), setIgnoreDCs (AutoRepairServiceMBean.java:48), setMVRepairEnabled (AutoRepairServiceMBean.java:60), setMixedMajorVersionRepairEnabled (AutoRepairServiceMBean.java:78), setParallelRepairCount (AutoRepairServiceMBean.java:54), setParallelRepairPercentage (AutoRepairServiceMBean.java:52), setPrimaryTokenRangeOnly (AutoRepairServiceMBean.java:50), setRepairByKeyspace (AutoRepairServiceMBean.java:72), setRepairMinInterval (AutoRepairServiceMBean.java:36), setRepairPriorityForHosts (AutoRepairServiceMBean.java:32), setRepairSSTableCountHigherThreshold (AutoRepairServiceMBean.java:44), setRepairSessionTimeout (AutoRepairServiceMBean.java:66), setRepairThreads (AutoRepairServiceMBean.java:30), startScheduler (AutoRepairServiceMBean.java:38)

#### metrics (35)

Reason: CassandraMetricsRegistry JMX metric beans (gauge, counter, meter, histogram, timer reads): metric values only, no behavior.

- CassandraMetricsRegistry.JmxCounterMBean (1): getCount (CassandraMetricsRegistry.java:473)
- CassandraMetricsRegistry.JmxGaugeMBean (1): getValue (CassandraMetricsRegistry.java:321)
- CassandraMetricsRegistry.JmxHistogramMBean (13): get50thPercentile (CassandraMetricsRegistry.java:353), get75thPercentile (CassandraMetricsRegistry.java:355), get95thPercentile (CassandraMetricsRegistry.java:357), get98thPercentile (CassandraMetricsRegistry.java:359), get999thPercentile (CassandraMetricsRegistry.java:363), get99thPercentile (CassandraMetricsRegistry.java:361), getCount (CassandraMetricsRegistry.java:343), getMax (CassandraMetricsRegistry.java:347), getMean (CassandraMetricsRegistry.java:349), getMin (CassandraMetricsRegistry.java:345), getRecentValues (CassandraMetricsRegistry.java:367), getStdDev (CassandraMetricsRegistry.java:351), values (CassandraMetricsRegistry.java:365)
- CassandraMetricsRegistry.JmxMeterMBean (6): getCount (CassandraMetricsRegistry.java:495), getFifteenMinuteRate (CassandraMetricsRegistry.java:503), getFiveMinuteRate (CassandraMetricsRegistry.java:501), getMeanRate (CassandraMetricsRegistry.java:497), getOneMinuteRate (CassandraMetricsRegistry.java:499), getRateUnit (CassandraMetricsRegistry.java:505)
- CassandraMetricsRegistry.JmxTimerMBean (13): get50thPercentile (CassandraMetricsRegistry.java:599), get75thPercentile (CassandraMetricsRegistry.java:601), get95thPercentile (CassandraMetricsRegistry.java:603), get98thPercentile (CassandraMetricsRegistry.java:605), get999thPercentile (CassandraMetricsRegistry.java:609), get99thPercentile (CassandraMetricsRegistry.java:607), getDurationUnit (CassandraMetricsRegistry.java:615), getMax (CassandraMetricsRegistry.java:593), getMean (CassandraMetricsRegistry.java:595), getMin (CassandraMetricsRegistry.java:591), getRecentValues (CassandraMetricsRegistry.java:613), getStdDev (CassandraMetricsRegistry.java:597), values (CassandraMetricsRegistry.java:611)
- CassandraMetricsRegistry.MetricMBean (1): objectName (CassandraMetricsRegistry.java:299)

#### getters (366)

Reason: JMX getters (get*/is*): reads of a config value, metric, status or report; no state change.

- ActiveRepairServiceMBean (11): getConcurrentMerkleTreeRequests (ActiveRepairServiceMBean.java:53), getIncrementalRepairDiskHeadroomRejectRatio (ActiveRepairServiceMBean.java:78), getPaxosRepairParallelism (ActiveRepairServiceMBean.java:75), getPendingStats (ActiveRepairServiceMBean.java:64), getRepairPendingCompactionRejectThreshold (ActiveRepairServiceMBean.java:60), getRepairSessionSpaceInMebibytes (ActiveRepairServiceMBean.java:48), getRepairSessionSpaceInMegabytes (ActiveRepairServiceMBean.java:37), getRepairSessionSpaceInMiB (ActiveRepairServiceMBean.java:51), getRepairStats (ActiveRepairServiceMBean.java:63), getSessions (ActiveRepairServiceMBean.java:29), getUseOffheapMerkleTrees (ActiveRepairServiceMBean.java:57)
- AuditLogManagerMBean (1): getAuditLogOptionsData (AuditLogManagerMBean.java:28)
- AuthCacheMBean (5): getActiveUpdate (AuthCacheMBean.java:37), getEstimatedSize (AuthCacheMBean.java:41), getMaxEntries (AuthCacheMBean.java:35), getUpdateInterval (AuthCacheMBean.java:31), getValidity (AuthCacheMBean.java:27)
- AuthPropertiesMXBean (2): getReadConsistencyLevel (AuthPropertiesMXBean.java:26), getWriteConsistencyLevel (AuthPropertiesMXBean.java:28)
- BatchlogManagerMBean (1): getTotalBatchesReplayed (BatchlogManagerMBean.java:32)
- CIDRFilteringMetricsTableMBean (2): getCountsMetricsFromVtable (CIDRFilteringMetricsTableMBean.java:33), getLatenciesMetricsFromVtable (CIDRFilteringMetricsTableMBean.java:39)
- CIDRGroupsMappingManagerMBean (3): getAvailableCidrGroups (CIDRGroupsMappingManagerMBean.java:36), getCidrGroupsOfIP (CIDRGroupsMappingManagerMBean.java:73), getCidrsOfCidrGroupAsStrings (CIDRGroupsMappingManagerMBean.java:44)
- CacheServiceMBean (5): getCounterCacheKeysToSave (CacheServiceMBean.java:39), getCounterCacheSavePeriodInSeconds (CacheServiceMBean.java:30), getKeyCacheKeysToSave (CacheServiceMBean.java:36), getKeyCacheSavePeriodInSeconds (CacheServiceMBean.java:27), getRowCacheKeysToSave (CacheServiceMBean.java:33)
- ColumnFamilyStoreMBean (28): getBuiltIndexes (ColumnFamilyStoreMBean.java:150), getColumnFamilyName (ColumnFamilyStoreMBean.java:44), getCompactionParameters (ColumnFamilyStoreMBean.java:120), getCompactionParametersJson (ColumnFamilyStoreMBean.java:110), getCompressionParameters (ColumnFamilyStoreMBean.java:125), getCompressionParametersJson (ColumnFamilyStoreMBean.java:127), getDataPaths (ColumnFamilyStoreMBean.java:330), getDroppableTombstoneRatio (ColumnFamilyStoreMBean.java:291), getLevelFanoutSize (ColumnFamilyStoreMBean.java:285), getMaxSSTableDuration (ColumnFamilyStoreMBean.java:354), getMaxSSTableSize (ColumnFamilyStoreMBean.java:342), getMaximumCompactionThreshold (ColumnFamilyStoreMBean.java:90), getMinimumCompactionThreshold (ColumnFamilyStoreMBean.java:80), getNeverPurgeTombstones (ColumnFamilyStoreMBean.java:321), getPerLevelSizeBytes (ColumnFamilyStoreMBean.java:269), getSSTableCountPerLevel (ColumnFamilyStoreMBean.java:263), getSSTableCountPerTWCSBucket (ColumnFamilyStoreMBean.java:280), getSSTablesForKey (ColumnFamilyStoreMBean.java:157), getSSTablesForKeyWithLevel (ColumnFamilyStoreMBean.java:174), getTableName (ColumnFamilyStoreMBean.java:46), getTopSizePartitions (ColumnFamilyStoreMBean.java:332), getTopSizePartitionsLastUpdate (ColumnFamilyStoreMBean.java:333), getTopTombstonePartitions (ColumnFamilyStoreMBean.java:334), getTopTombstonePartitionsLastUpdate (ColumnFamilyStoreMBean.java:335), getUnleveledSSTables (ColumnFamilyStoreMBean.java:257), isAutoCompactionDisabled (ColumnFamilyStoreMBean.java:141), isCompactionDiskSpaceCheckEnabled (ColumnFamilyStoreMBean.java:312), isLeveledCompaction (ColumnFamilyStoreMBean.java:274)
- CommitLogMBean (12): getActiveContentSize (CommitLogMBean.java:80), getActiveOnDiskSize (CommitLogMBean.java:85), getActiveSegmentCompressionRatios (CommitLogMBean.java:90), getActiveSegmentNames (CommitLogMBean.java:70), getArchiveCommand (CommitLogMBean.java:30), getArchivingSegmentNames (CommitLogMBean.java:75), getCDCBlockWrites (CommitLogMBean.java:92), getRestoreCommand (CommitLogMBean.java:35), getRestoreDirectories (CommitLogMBean.java:40), getRestorePointInTime (CommitLogMBean.java:54), getRestorePrecision (CommitLogMBean.java:60), isCDCOnRepairEnabled (CommitLogMBean.java:97)
- CompactionManagerMBean (14): getAutomaticSSTableUpgradeEnabled (CompactionManagerMBean.java:159), getCompactionHistory (CompactionManagerMBean.java:33), getCompactionSummary (CompactionManagerMBean.java:30), getCompactions (CompactionManagerMBean.java:27), getCoreCompactorThreads (CompactionManagerMBean.java:79), getCoreSecondaryIndexExecutorThreads (CompactionManagerMBean.java:129), getCoreValidationThreads (CompactionManagerMBean.java:101), getCoreViewBuildThreads (CompactionManagerMBean.java:123), getDisableSTCSInL0 (CompactionManagerMBean.java:136), getMaxConcurrentAutoUpgradeTasks (CompactionManagerMBean.java:169), getMaximumCompactorThreads (CompactionManagerMBean.java:90), getMaximumSecondaryIndexExecutorThreads (CompactionManagerMBean.java:125), getMaximumValidatorThreads (CompactionManagerMBean.java:112), getMaximumViewBuildThreads (CompactionManagerMBean.java:148)
- DiagnosticEventServiceMBean (1): isDiagnosticsEnabled (DiagnosticEventServiceMBean.java:33)
- DisallowedDirectoriesMBean (2): getUnreadableDirectories (DisallowedDirectoriesMBean.java:25), getUnwritableDirectories (DisallowedDirectoriesMBean.java:27)
- DynamicEndpointSnitchMBean (7): getBadnessThreshold (DynamicEndpointSnitchMBean.java:33), getResetInterval (DynamicEndpointSnitchMBean.java:32), getScores (DynamicEndpointSnitchMBean.java:30), getScoresWithPort (DynamicEndpointSnitchMBean.java:27), getSeverity (DynamicEndpointSnitchMBean.java:61), getSubsnitchClassName (DynamicEndpointSnitchMBean.java:34), getUpdateInterval (DynamicEndpointSnitchMBean.java:31)
- EndpointSnitchInfoMBean (3): getDatacenter (EndpointSnitchInfoMBean.java:39), getRack (EndpointSnitchInfoMBean.java:32), getSnitchName (EndpointSnitchInfoMBean.java:55)
- FailureDetectorMBean (12): getAllEndpointStates (FailureDetectorMBean.java:35), getAllEndpointStatesWithPort (FailureDetectorMBean.java:38), getAllEndpointStatesWithPortAndResolveIp (FailureDetectorMBean.java:39), getAllEndpointStatesWithResolveIp (FailureDetectorMBean.java:37), getDownEndpointCount (FailureDetectorMBean.java:47), getEndpointState (FailureDetectorMBean.java:41), getPhiConvictThreshold (FailureDetectorMBean.java:32), getPhiValues (FailureDetectorMBean.java:52), getPhiValuesWithPort (FailureDetectorMBean.java:53), getSimpleStates (FailureDetectorMBean.java:44), getSimpleStatesWithPort (FailureDetectorMBean.java:45), getUpEndpointCount (FailureDetectorMBean.java:49)
- GCInspectorMXBean (4): getAndResetStats (GCInspectorMXBean.java:26), getGcLogThresholdInMs (GCInspectorMXBean.java:30), getGcWarnThresholdInMs (GCInspectorMXBean.java:28), getStatusThresholdInMs (GCInspectorMXBean.java:31)
- GossiperMBean (5): getCurrentGenerationNumber (GossiperMBean.java:28), getEndpointDowntime (GossiperMBean.java:26), getLooseEmptyEnabled (GossiperMBean.java:41), getReleaseVersionsWithPort (GossiperMBean.java:39), getSeeds (GossiperMBean.java:36)
- HintsServiceMBean (1): getPendingHints (HintsServiceMBean.java:52)
- IndexSummaryManagerMBean (5): getAverageIndexInterval (IndexSummaryManagerMBean.java:39), getIndexIntervals (IndexSummaryManagerMBean.java:37), getMemoryPoolCapacityInMB (IndexSummaryManagerMBean.java:25), getMemoryPoolSizeInMB (IndexSummaryManagerMBean.java:32), getResizeIntervalInMinutes (IndexSummaryManagerMBean.java:43)
- LastEventIdBroadcasterMBean (2): getLastEventIds (LastEventIdBroadcasterMBean.java:52), getLastEventIdsIfModified (LastEventIdBroadcasterMBean.java:58)
- MessagingServiceMBean (25): getBackPressurePerHost (MessagingServiceMBean.java:130), getDroppedMessages (MessagingServiceMBean.java:110), getGossipMessageCompletedTasks (MessagingServiceMBean.java:96), getGossipMessageCompletedTasksWithPort (MessagingServiceMBean.java:97), getGossipMessageDroppedTasks (MessagingServiceMBean.java:104), getGossipMessageDroppedTasksWithPort (MessagingServiceMBean.java:105), getGossipMessagePendingTasks (MessagingServiceMBean.java:88), getGossipMessagePendingTasksWithPort (MessagingServiceMBean.java:89), getLargeMessageCompletedTasks (MessagingServiceMBean.java:44), getLargeMessageCompletedTasksWithPort (MessagingServiceMBean.java:45), getLargeMessageDroppedTasks (MessagingServiceMBean.java:52), getLargeMessageDroppedTasksWithPort (MessagingServiceMBean.java:53), getLargeMessagePendingTasks (MessagingServiceMBean.java:36), getLargeMessagePendingTasksWithPort (MessagingServiceMBean.java:37), getSmallMessageCompletedTasks (MessagingServiceMBean.java:70), getSmallMessageCompletedTasksWithPort (MessagingServiceMBean.java:71), getSmallMessageDroppedTasks (MessagingServiceMBean.java:79), getSmallMessageDroppedTasksWithPort (MessagingServiceMBean.java:80), getSmallMessagePendingTasks (MessagingServiceMBean.java:61), getSmallMessagePendingTasksWithPort (MessagingServiceMBean.java:62), getTimeoutsPerHost (MessagingServiceMBean.java:122), getTimeoutsPerHostWithPort (MessagingServiceMBean.java:123), getTotalTimeouts (MessagingServiceMBean.java:115), getVersion (MessagingServiceMBean.java:146), isBackPressureEnabled (MessagingServiceMBean.java:144)
- NativeAccessMBean (2): isAvailable (NativeAccessMBean.java:22), isMemoryLockable (NativeAccessMBean.java:24)
- ResizableThreadPoolMXBean (2): getCoreThreads (ResizableThreadPoolMXBean.java:27), getMaximumThreads (ResizableThreadPoolMXBean.java:41)
- ShardedMemtableConfigMXBean (1): getDefaultShardCount (ShardedMemtableConfigMXBean.java:32)
- StorageProxyMBean (40): getCasContentionTimeout (StorageProxyMBean.java:49), getCheckForDuplicateRowsDuringCompaction (StorageProxyMBean.java:131), getCheckForDuplicateRowsDuringReads (StorageProxyMBean.java:128), getClientRequestSizeMetricsEnabled (StorageProxyMBean.java:153), getCounterWriteRpcTimeout (StorageProxyMBean.java:47), getDumpHeapOnUncaughtException (StorageProxyMBean.java:147), getHintedHandoffDisabledDCs (StorageProxyMBean.java:32), getHintsInProgress (StorageProxyMBean.java:39), getIdealConsistencyLevel (StorageProxyMBean.java:99), getMaxHintWindow (StorageProxyMBean.java:33), getMaxHintsInProgress (StorageProxyMBean.java:37), getMaxHintsSizePerHostInMiB (StorageProxyMBean.java:35), getNativeTransportMaxConcurrentConnections (StorageProxyMBean.java:57), getNativeTransportMaxConcurrentConnectionsPerIp (StorageProxyMBean.java:60), getNumberOfTables (StorageProxyMBean.java:97), getOtcBacklogExpirationInterval (StorageProxyMBean.java:71), getPartitionDenylistLoadAttempts (StorageProxyMBean.java:74), getPartitionDenylistLoadSuccesses (StorageProxyMBean.java:75), getPaxosContentionStrategy (StorageProxyMBean.java:142), getPaxosCoordinatorLockingDisabled (StorageProxyMBean.java:145), getPaxosVariant (StorageProxyMBean.java:136), getRangeRpcTimeout (StorageProxyMBean.java:51), getReadRepairAttempted (StorageProxyMBean.java:64), getReadRepairRepairTimedOut (StorageProxyMBean.java:67), getReadRepairRepairedBackground (StorageProxyMBean.java:66), getReadRepairRepairedBlocking (StorageProxyMBean.java:65), getReadRpcTimeout (StorageProxyMBean.java:43), getRepairedDataTrackingEnabledForPartitionReads (StorageProxyMBean.java:114), getRepairedDataTrackingEnabledForRangeReads (StorageProxyMBean.java:110), getReportingUnconfirmedRepairedDataMismatchesEnabled (StorageProxyMBean.java:118), getRpcTimeout (StorageProxyMBean.java:41), getSStableReadRatePersistenceEnabled (StorageProxyMBean.java:150), getSchemaVersions (StorageProxyMBean.java:94), getSchemaVersionsWithPort (StorageProxyMBean.java:95), getSnapshotOnDuplicateRowDetectionEnabled (StorageProxyMBean.java:126), getSnapshotOnRepairedDataMismatchEnabled (StorageProxyMBean.java:122), getTruncateRpcTimeout (StorageProxyMBean.java:53), getUseStatementsEnabled (StorageProxyMBean.java:138), getWriteRpcTimeout (StorageProxyMBean.java:45), isLoggingReadRepairs (StorageProxyMBean.java:103)
- StorageServiceMBean (167): getAllDataFileLocations (StorageServiceMBean.java:132), getAutoCompactionStatus (StorageServiceMBean.java:970), getBatchSizeFailureThreshold (StorageServiceMBean.java:1041), getBatchSizeWarnThreshold (StorageServiceMBean.java:1050), getBatchSizeWarnThresholdInKiB (StorageServiceMBean.java:1059), getBatchlogEndpointStrategy (StorageServiceMBean.java:652), getBatchlogReplayThrottleInKB (StorageServiceMBean.java:817), getCachedReplicaRowsFailThreshold (StorageServiceMBean.java:996), getCachedReplicaRowsWarnThreshold (StorageServiceMBean.java:990), getCasContentionTimeout (StorageServiceMBean.java:738), getClusterName (StorageServiceMBean.java:975), getColumnIndexCacheSize (StorageServiceMBean.java:1025), getColumnIndexCacheSizeInKiB (StorageServiceMBean.java:1035), getColumnIndexSizeInKiB (StorageServiceMBean.java:1005), getCommitLogLocation (StorageServiceMBean.java:152), getCompactionThroughtputBytesPerSec (StorageServiceMBean.java:805), getCompactionThroughtputMibPerSecAsDouble (StorageServiceMBean.java:804), getCompactionTombstoneWarningThreshold (StorageServiceMBean.java:1212), getCompressedReadAheadBufferInKB (StorageServiceMBean.java:814), getConcurrency (StorageServiceMBean.java:1102), getConcurrentIndexBuilders (StorageServiceMBean.java:827), getConcurrentValidators (StorageServiceMBean.java:830), getConcurrentViewBuilders (StorageServiceMBean.java:841), getCoordinatorLargeReadAbortThreshold (StorageServiceMBean.java:1219), getCoordinatorLargeReadWarnThreshold (StorageServiceMBean.java:1217), getCorruptedTombstoneStrategy (StorageServiceMBean.java:1131), getCounterWriteRpcTimeout (StorageServiceMBean.java:735), getCurrentGenerationNumber (StorageServiceMBean.java:245), getDefaultKeyspaceReplicationFactor (StorageServiceMBean.java:1233), getDrainProgress (StorageServiceMBean.java:578), getDynamicUpdateInterval (StorageServiceMBean.java:650), getEndpointToHostId (StorageServiceMBean.java:217), getEndpointWithPortToHostId (StorageServiceMBean.java:218), getEnforceNativeDeadlineForHints (StorageServiceMBean.java:1301), getEntireSSTableInterDCStreamThroughputMebibytesPerSecAsDouble (StorageServiceMBean.java:802), getEntireSSTableStreamThroughputMebibytesPerSecAsDouble (StorageServiceMBean.java:799), getForceOptimizedIndexStatusFormat (StorageServiceMBean.java:1325), getFullQueryLoggerOptions (StorageServiceMBean.java:1163), getGitSHA (StorageServiceMBean.java:114), getHostIdToEndpoint (StorageServiceMBean.java:224), getHostIdToEndpointWithPort (StorageServiceMBean.java:225), getInitialRangeTombstoneListAllocationSize (StorageServiceMBean.java:1169), getInterDCStreamThroughputMbPerSec (StorageServiceMBean.java:789), getInterDCStreamThroughputMbitPerSec (StorageServiceMBean.java:777), getInterDCStreamThroughputMbitPerSecAsDouble (StorageServiceMBean.java:778), getInterDCStreamThroughputMebibytesPerSec (StorageServiceMBean.java:795), getInterDCStreamThroughputMebibytesPerSecAsDouble (StorageServiceMBean.java:796), getInternodeStreamingTcpUserTimeoutInMS (StorageServiceMBean.java:732), getInternodeTcpConnectTimeoutInMS (StorageServiceMBean.java:726), getInternodeTcpUserTimeoutInMS (StorageServiceMBean.java:729), getInvalidateKeycacheOnSSTableDeletion (StorageServiceMBean.java:838), getJoiningNodes (StorageServiceMBean.java:68), getJoiningNodesWithPort (StorageServiceMBean.java:69), getKeyspaceCountWarnThreshold (StorageServiceMBean.java:1202), getKeyspaceReplicationInfo (StorageServiceMBean.java:126), getLeavingNodes (StorageServiceMBean.java:77), getLeavingNodesWithPort (StorageServiceMBean.java:78), getLiveNodes (StorageServiceMBean.java:49), getLiveNodesWithPort (StorageServiceMBean.java:50), getLoadMap (StorageServiceMBean.java:237), getLoadMapWithPort (StorageServiceMBean.java:238), getLoadString (StorageServiceMBean.java:228), getLocalHostId (StorageServiceMBean.java:211), getLocalReadTooLargeAbortThreshold (StorageServiceMBean.java:1224), getLocalReadTooLargeWarnThreshold (StorageServiceMBean.java:1222), getLocalSystemKeyspacesDataFileLocations (StorageServiceMBean.java:139), getLoggingLevels (StorageServiceMBean.java:569), getMaxHintTTL (StorageServiceMBean.java:1075), getMaxTopSizePartitionCount (StorageServiceMBean.java:1276), getMaxTopTombstonePartitionCount (StorageServiceMBean.java:1278), getMigrateKeycacheOnCompaction (StorageServiceMBean.java:836), getMinTrackedPartitionSize (StorageServiceMBean.java:1280), getMinTrackedPartitionTombstoneCount (StorageServiceMBean.java:1282), getMovingNodes (StorageServiceMBean.java:86), getMovingNodesWithPort (StorageServiceMBean.java:87), getNativeTransportMaxBackoffOnQueueOverloadInMillis (StorageServiceMBean.java:1292), getNativeTransportMaxConcurrentRequestsInBytes (StorageServiceMBean.java:682), getNativeTransportMaxConcurrentRequestsInBytesPerIp (StorageServiceMBean.java:684), getNativeTransportMaxRequestsPerSecond (StorageServiceMBean.java:686), getNativeTransportMinBackoffOnQueueOverloadInMillis (StorageServiceMBean.java:1291), getNativeTransportQueueMaxItemAgeThreshold (StorageServiceMBean.java:1288), getNativeTransportRateLimitingEnabled (StorageServiceMBean.java:689), getNativeTransportThrowOnOverload (StorageServiceMBean.java:1295), getNativeTransportTimeoutMillis (StorageServiceMBean.java:1298), getNaturalEndpoints (StorageServiceMBean.java:257), getNaturalEndpointsWithPort (StorageServiceMBean.java:258), getNonLocalSystemKeyspacesDataFileLocations (StorageServiceMBean.java:146), getOperationMode (StorageServiceMBean.java:572), getOutOfRangeOperationCounts (StorageServiceMBean.java:1320), getOutstandingSchemaVersions (StorageServiceMBean.java:1182), getOutstandingSchemaVersionsWithPort (StorageServiceMBean.java:1183), getOwnership (StorageServiceMBean.java:600), getOwnershipWithPort (StorageServiceMBean.java:601), getPartitionerName (StorageServiceMBean.java:977), getPaxosAutoRepairTables (StorageServiceMBean.java:1247), getPaxosAutoRepairsEnabled (StorageServiceMBean.java:1241), getPaxosBallotLowBound (StorageServiceMBean.java:1264), getPaxosDcLocalCommitEnabled (StorageServiceMBean.java:1261), getPaxosOnLinearizabilityViolations (StorageServiceMBean.java:1252), getPaxosPurgeGraceSeconds (StorageServiceMBean.java:1249), getPaxosRepairEnabled (StorageServiceMBean.java:1258), getPaxosRepairRaceWait (StorageServiceMBean.java:1330), getPaxosStateFlushEnabled (StorageServiceMBean.java:1244), getPaxosStatePurging (StorageServiceMBean.java:1255), getPendingRangeToEndpointMap (StorageServiceMBean.java:197), getPendingRangeToEndpointWithPortMap (StorageServiceMBean.java:198), getPrioritizeSAIOverLegacyIndex (StorageServiceMBean.java:1322), getRangeRpcTimeout (StorageServiceMBean.java:720), getRangeToEndpointMap (StorageServiceMBean.java:167), getRangeToEndpointWithPortMap (StorageServiceMBean.java:168), getRangeToNativeaddressWithPortMap (StorageServiceMBean.java:178), getRangeToRpcaddressMap (StorageServiceMBean.java:177), getRangeTombstoneResizeListGrowthFactor (StorageServiceMBean.java:1175), getReadRpcTimeout (StorageServiceMBean.java:717), getReadThresholdsEnabled (StorageServiceMBean.java:1214), getReleaseVersion (StorageServiceMBean.java:108), getRemovalStatus (StorageServiceMBean.java:544), getRemovalStatusWithPort (StorageServiceMBean.java:545), getRepairRpcTimeout (StorageServiceMBean.java:1266), getRepairSessionMaxTreeDepth (StorageServiceMBean.java:490), getRepairSessionMaximumTreeDepth (StorageServiceMBean.java:494), getRowIndexReadSizeAbortThreshold (StorageServiceMBean.java:1229), getRowIndexReadSizeWarnThreshold (StorageServiceMBean.java:1227), getRpcTimeout (StorageServiceMBean.java:714), getSSTablePreemptiveOpenIntervalInMB (StorageServiceMBean.java:833), getSampleTasks (StorageServiceMBean.java:961), getSavedCachesLocation (StorageServiceMBean.java:158), getSchemaVersion (StorageServiceMBean.java:120), getSkipPaxosRepairCompatibilityCheck (StorageServiceMBean.java:1272), getSkipPaxosRepairOnTopologyChange (StorageServiceMBean.java:1235), getSkipPaxosRepairOnTopologyChangeKeyspaces (StorageServiceMBean.java:1238), getSkipStreamDiskSpaceCheck (StorageServiceMBean.java:1286), getSnapshotDetails (StorageServiceMBean.java:320), getSnapshotLinksPerSecond (StorageServiceMBean.java:350), getStreamThroughputMbPerSec (StorageServiceMBean.java:761), getStreamThroughputMbitPerSec (StorageServiceMBean.java:749), getStreamThroughputMbitPerSecAsDouble (StorageServiceMBean.java:750), getStreamThroughputMebibytesPerSec (StorageServiceMBean.java:767), getStreamThroughputMebibytesPerSecAsDouble (StorageServiceMBean.java:768), getTableCountWarnThreshold (StorageServiceMBean.java:1196), getTablesForKeyspace (StorageServiceMBean.java:1335), getToken (StorageServiceMBean.java:1274), getTokenToEndpointMap (StorageServiceMBean.java:207), getTokenToEndpointWithPortMap (StorageServiceMBean.java:208), getTokens (StorageServiceMBean.java:94), getTombstoneFailureThreshold (StorageServiceMBean.java:985), getTombstoneWarnThreshold (StorageServiceMBean.java:980), getTransferHintsOnDecommission (StorageServiceMBean.java:1066), getTruncateRpcTimeout (StorageServiceMBean.java:741), getUncompressedLoadString (StorageServiceMBean.java:231), getUnreachableNodes (StorageServiceMBean.java:59), getUnreachableNodesWithPort (StorageServiceMBean.java:60), getViewBuildStatuses (StorageServiceMBean.java:621), getViewBuildStatusesWithPort (StorageServiceMBean.java:622), getWriteRpcTimeout (StorageServiceMBean.java:723), isBootstrapFailed (StorageServiceMBean.java:711), isConcurrentValidatorsLimitEnforced (StorageServiceMBean.java:825), isDecommissionFailed (StorageServiceMBean.java:519), isDrained (StorageServiceMBean.java:694), isDraining (StorageServiceMBean.java:695), isGossipRunning (StorageServiceMBean.java:666), isHintTtlUseMutationCreationTime (StorageServiceMBean.java:1070), isInitialized (StorageServiceMBean.java:672), isNativeTransportRunning (StorageServiceMBean.java:677), isOutOfTokenRangeRequestLoggingEnabled (StorageServiceMBean.java:1308), isOutOfTokenRangeRequestRejectionEnabled (StorageServiceMBean.java:1311), isStarting (StorageServiceMBean.java:575)
- StreamManagerMBean (3): getCurrentStreams (StreamManagerMBean.java:31), getStreamingSlowEventsLogTimeout (StreamManagerMBean.java:46), getStreamingStatsEnabled (StreamManagerMBean.java:36)

#### readonly-ops (22)

Reason: Read-only report or diagnostic JMX operations without a get/is prefix (ring description, ownership, samples, counts, timing dumps): no state change that affects request handling.

- ActiveRepairServiceMBean (1): parentRepairSessionsCount (ActiveRepairServiceMBean.java:74)
- BatchlogManagerMBean (1): countAllBatches (BatchlogManagerMBean.java:27)
- ColumnFamilyStoreMBean (5): beginLocalSampling (ColumnFamilyStoreMBean.java:302), estimateKeys (ColumnFamilyStoreMBean.java:143), finishLocalSampling (ColumnFamilyStoreMBean.java:307), hasMisplacedSSTables (ColumnFamilyStoreMBean.java:328), trueSnapshotsSize (ColumnFamilyStoreMBean.java:296)
- DiagnosticEventServiceMBean (1): readEvents (DiagnosticEventServiceMBean.java:48)
- DynamicEndpointSnitchMBean (1): dumpTimings (DynamicEndpointSnitchMBean.java:35)
- FailureDetectorMBean (1): dumpInterArrivalTimes (FailureDetectorMBean.java:28)
- GossiperMBean (1): compareGossipAndTokenMetadata (GossiperMBean.java:49)
- StorageServiceMBean (11): autoOptimiseFullRepairStreams (StorageServiceMBean.java:1188), autoOptimiseIncRepairStreams (StorageServiceMBean.java:1186), autoOptimisePreviewRepairStreams (StorageServiceMBean.java:1190), describeRingJMX (StorageServiceMBean.java:188), describeRingWithPortJMX (StorageServiceMBean.java:189), effectiveOwnership (StorageServiceMBean.java:611), effectiveOwnershipWithPort (StorageServiceMBean.java:612), sampleKeyRange (StorageServiceMBean.java:911), samplePartitions (StorageServiceMBean.java:931), topPartitionsEnabled (StorageServiceMBean.java:1275), trueSnapshotsSize (StorageServiceMBean.java:334)

#### svc-setters (110)

Reason: Runtime-tunable setters on service MBeans (StorageService, StorageProxy, CacheService, ActiveRepairService, GCInspector) that no nodetool command invokes: each assigns one DatabaseDescriptor/Config value (a few also resize an executor or limiter) read later by the owning area. The nodetool-reachable setters are modeled.

- ActiveRepairServiceMBean (8): setConcurrentMerkleTreeRequests (ActiveRepairServiceMBean.java:55), setIncrementalRepairDiskHeadroomRejectRatio (ActiveRepairServiceMBean.java:80), setPaxosRepairParallelism (ActiveRepairServiceMBean.java:76), setRepairPendingCompactionRejectThreshold (ActiveRepairServiceMBean.java:61), setRepairSessionSpaceInMebibytes (ActiveRepairServiceMBean.java:43), setRepairSessionSpaceInMegabytes (ActiveRepairServiceMBean.java:34), setRepairSessionSpaceInMiB (ActiveRepairServiceMBean.java:50), setUseOffheapMerkleTrees (ActiveRepairServiceMBean.java:58)
- CacheServiceMBean (3): setCounterCacheSavePeriodInSeconds (CacheServiceMBean.java:31), setKeyCacheSavePeriodInSeconds (CacheServiceMBean.java:28), setRowCacheSavePeriodInSeconds (CacheServiceMBean.java:25)
- GCInspectorMXBean (2): setGcLogThresholdInMs (GCInspectorMXBean.java:29), setGcWarnThresholdInMs (GCInspectorMXBean.java:27)
- StorageProxyMBean (26): setCasContentionTimeout (StorageProxyMBean.java:50), setClientRequestSizeMetricsEnabled (StorageProxyMBean.java:154), setCounterWriteRpcTimeout (StorageProxyMBean.java:48), setDenylistMaxKeysPerTable (StorageProxyMBean.java:82), setDenylistMaxKeysTotal (StorageProxyMBean.java:83), setDumpHeapOnUncaughtException (StorageProxyMBean.java:148), setEnableDenylistRangeReads (StorageProxyMBean.java:79), setEnableDenylistReads (StorageProxyMBean.java:78), setEnableDenylistWrites (StorageProxyMBean.java:77), setEnablePartitionDenylist (StorageProxyMBean.java:76), setIdealConsistencyLevel (StorageProxyMBean.java:100), setMaxHintsInProgress (StorageProxyMBean.java:38), setMaxHintsSizePerHostInMiB (StorageProxyMBean.java:36), setNativeTransportMaxConcurrentConnections (StorageProxyMBean.java:56), setNativeTransportMaxConcurrentConnectionsPerIp (StorageProxyMBean.java:59), setOtcBacklogExpirationInterval (StorageProxyMBean.java:88), setPaxosContentionStrategy (StorageProxyMBean.java:141), setPaxosCoordinatorLockingDisabled (StorageProxyMBean.java:144), setPaxosVariant (StorageProxyMBean.java:135), setRangeRpcTimeout (StorageProxyMBean.java:52), setReadRpcTimeout (StorageProxyMBean.java:44), setRpcTimeout (StorageProxyMBean.java:42), setSStableReadRatePersistenceEnabled (StorageProxyMBean.java:151), setTruncateRpcTimeout (StorageProxyMBean.java:54), setUseStatementsEnabled (StorageProxyMBean.java:139), setWriteRpcTimeout (StorageProxyMBean.java:46)
- StorageServiceMBean (71): setAutoOptimiseFullRepairStreams (StorageServiceMBean.java:1189), setAutoOptimiseIncRepairStreams (StorageServiceMBean.java:1187), setAutoOptimisePreviewRepairStreams (StorageServiceMBean.java:1191), setBatchSizeFailureThreshold (StorageServiceMBean.java:1043), setBatchSizeWarnThreshold (StorageServiceMBean.java:1056), setBatchSizeWarnThresholdInKiB (StorageServiceMBean.java:1061), setBatchlogEndpointStrategy (StorageServiceMBean.java:657), setCachedReplicaRowsFailThreshold (StorageServiceMBean.java:999), setCachedReplicaRowsWarnThreshold (StorageServiceMBean.java:993), setColumnIndexCacheSize (StorageServiceMBean.java:1032), setColumnIndexCacheSizeInKiB (StorageServiceMBean.java:1038), setColumnIndexSizeInKiB (StorageServiceMBean.java:1011), setCompactionTombstoneWarningThreshold (StorageServiceMBean.java:1209), setCompressedReadAheadBufferInKB (StorageServiceMBean.java:815), setConcurrentIndexBuilders (StorageServiceMBean.java:828), setConcurrentValidators (StorageServiceMBean.java:831), setCoordinatorLargeReadAbortThreshold (StorageServiceMBean.java:1220), setCoordinatorLargeReadWarnThreshold (StorageServiceMBean.java:1218), setCorruptedTombstoneStrategy (StorageServiceMBean.java:1132), setDynamicUpdateInterval (StorageServiceMBean.java:645), setEnforceNativeDeadlineForHints (StorageServiceMBean.java:1302), setForceOptimizedIndexStatusFormat (StorageServiceMBean.java:1326), setInitialRangeTombstoneListAllocationSize (StorageServiceMBean.java:1166), setInterDCStreamThroughputMbPerSec (StorageServiceMBean.java:782), setInvalidateKeycacheOnSSTableDeletion (StorageServiceMBean.java:839), setKeyspaceCountWarnThreshold (StorageServiceMBean.java:1205), setLocalReadTooLargeAbortThreshold (StorageServiceMBean.java:1225), setLocalReadTooLargeWarnThreshold (StorageServiceMBean.java:1223), setMaxHintTTL (StorageServiceMBean.java:1077), setMaxTopSizePartitionCount (StorageServiceMBean.java:1277), setMaxTopTombstonePartitionCount (StorageServiceMBean.java:1279), setMigrateKeycacheOnCompaction (StorageServiceMBean.java:837), setMinTrackedPartitionSize (StorageServiceMBean.java:1281), setMinTrackedPartitionTombstoneCount (StorageServiceMBean.java:1283), setNativeTransportBackoffOnQueueOverloadInMillis (StorageServiceMBean.java:1293), setNativeTransportMaxConcurrentRequestsInBytes (StorageServiceMBean.java:683), setNativeTransportMaxConcurrentRequestsInBytesPerIp (StorageServiceMBean.java:685), setNativeTransportMaxRequestsPerSecond (StorageServiceMBean.java:687), setNativeTransportQueueMaxItemAgeThreshold (StorageServiceMBean.java:1289), setNativeTransportRateLimitingEnabled (StorageServiceMBean.java:688), setNativeTransportThrowOnOverload (StorageServiceMBean.java:1296), setNativeTransportTimeoutMillis (StorageServiceMBean.java:1299), setOutOfTokenRangeRequestLoggingEnabled (StorageServiceMBean.java:1309), setOutOfTokenRangeRequestRejectionEnabled (StorageServiceMBean.java:1312), setPaxosAutoRepairsEnabled (StorageServiceMBean.java:1242), setPaxosDcLocalCommitEnabled (StorageServiceMBean.java:1262), setPaxosOnLinearizabilityViolations (StorageServiceMBean.java:1253), setPaxosPurgeGraceSeconds (StorageServiceMBean.java:1250), setPaxosRepairEnabled (StorageServiceMBean.java:1259), setPaxosRepairRaceWait (StorageServiceMBean.java:1328), setPaxosStateFlushEnabled (StorageServiceMBean.java:1245), setPaxosStatePurging (StorageServiceMBean.java:1256), setPrioritizeSAIOverLegacyIndex (StorageServiceMBean.java:1323), setRangeTombstoneListResizeGrowthFactor (StorageServiceMBean.java:1172), setReadThresholdsEnabled (StorageServiceMBean.java:1215), setRepairRpcTimeout (StorageServiceMBean.java:1267), setRepairSessionMaxTreeDepth (StorageServiceMBean.java:484), setRepairSessionMaximumTreeDepth (StorageServiceMBean.java:492), setRowIndexReadSizeAbortThreshold (StorageServiceMBean.java:1230), setRowIndexReadSizeWarnThreshold (StorageServiceMBean.java:1228), setSSTablePreemptiveOpenIntervalInMB (StorageServiceMBean.java:834), setSkipPaxosRepairCompatibilityCheck (StorageServiceMBean.java:1271), setSkipPaxosRepairOnTopologyChange (StorageServiceMBean.java:1236), setSkipPaxosRepairOnTopologyChangeKeyspaces (StorageServiceMBean.java:1239), setSkipStreamDiskSpaceCheck (StorageServiceMBean.java:1285), setStreamThroughputMbPerSec (StorageServiceMBean.java:754), setTableCountWarnThreshold (StorageServiceMBean.java:1199), setTombstoneFailureThreshold (StorageServiceMBean.java:987), setTombstoneWarnThreshold (StorageServiceMBean.java:982), setTransferHintsOnDecommission (StorageServiceMBean.java:1067), setUseCreationTimeForHintTtl (StorageServiceMBean.java:1072)

#### pool-setters (2)

Reason: ResizableThreadPoolMXBean setters (concurrent/): per-executor core/max pool size; the same resize is modeled through nodetool setconcurrency (StorageService.setConcurrency).

- ResizableThreadPoolMXBean (2): setCoreThreads (ResizableThreadPoolMXBean.java:34), setMaximumThreads (ResizableThreadPoolMXBean.java:48)

#### other-area-jmx (51)

Reason: JMX-only operations and setters of MBeans in other areas' packages (auth, db, db/commitlog, db/compaction, db/memtable, diag, gms, io, locator, net, streaming) that no nodetool command calls: the owning area models what they do.

- AuthCacheMBean (4): setActiveUpdate (AuthCacheMBean.java:39), setMaxEntries (AuthCacheMBean.java:33), setUpdateInterval (AuthCacheMBean.java:29), setValidity (AuthCacheMBean.java:25)
- AuthPropertiesMXBean (2): setReadConsistencyLevel (AuthPropertiesMXBean.java:25), setWriteConsistencyLevel (AuthPropertiesMXBean.java:27)
- CIDRGroupsMappingManagerMBean (1): recreateCidrGroupsMapping (CIDRGroupsMappingManagerMBean.java:65)
- ColumnFamilyStoreMBean (13): compactionDiskSpaceCheck (ColumnFamilyStoreMBean.java:317), forceCompactionForTokenRange (ColumnFamilyStoreMBean.java:67), forceCompactionForTokenRanges (ColumnFamilyStoreMBean.java:75), forceMajorCompaction (ColumnFamilyStoreMBean.java:53), loadNewSSTables (ColumnFamilyStoreMBean.java:253), setCompactionParameters (ColumnFamilyStoreMBean.java:119), setCompactionParametersJson (ColumnFamilyStoreMBean.java:109), setCompressionParameters (ColumnFamilyStoreMBean.java:133), setCompressionParametersJson (ColumnFamilyStoreMBean.java:134), setCrcCheckChance (ColumnFamilyStoreMBean.java:139), setMaximumCompactionThreshold (ColumnFamilyStoreMBean.java:100), setMinimumCompactionThreshold (ColumnFamilyStoreMBean.java:85), setNeverPurgeTombstones (ColumnFamilyStoreMBean.java:319)
- CommitLogMBean (3): recover (CommitLogMBean.java:65), setCDCBlockWrites (CommitLogMBean.java:94), setCDCOnRepairEnabled (CommitLogMBean.java:100)
- CompactionManagerMBean (12): forceUserDefinedCleanup (CompactionManagerMBean.java:54), setAutomaticSSTableUpgradeEnabled (CompactionManagerMBean.java:163), setCoreCompactorThreads (CompactionManagerMBean.java:85), setCoreSecondaryIndexExecutorThreads (CompactionManagerMBean.java:131), setCoreValidationThreads (CompactionManagerMBean.java:107), setCoreViewBuildThreads (CompactionManagerMBean.java:143), setDisableSTCSInL0 (CompactionManagerMBean.java:137), setMaxConcurrentAutoUpgradeTasks (CompactionManagerMBean.java:175), setMaximumCompactorThreads (CompactionManagerMBean.java:96), setMaximumSecondaryIndexExecutorThreads (CompactionManagerMBean.java:127), setMaximumValidatorThreads (CompactionManagerMBean.java:118), setMaximumViewBuildThreads (CompactionManagerMBean.java:154)
- DiagnosticEventServiceMBean (3): disableDiagnostics (DiagnosticEventServiceMBean.java:39), disableEventPersistence (DiagnosticEventServiceMBean.java:58), enableEventPersistence (DiagnosticEventServiceMBean.java:53)
- DisallowedDirectoriesMBean (2): markUnreadable (DisallowedDirectoriesMBean.java:29), markUnwritable (DisallowedDirectoriesMBean.java:31)
- DynamicEndpointSnitchMBean (1): setSeverity (DynamicEndpointSnitchMBean.java:56)
- FailureDetectorMBean (1): setPhiConvictThreshold (FailureDetectorMBean.java:30)
- GossiperMBean (2): setLooseEmptyEnabled (GossiperMBean.java:43), unsafeAssassinateEndpoint (GossiperMBean.java:30)
- IndexSummaryManagerMBean (3): redistributeSummaries (IndexSummaryManagerMBean.java:41), setMemoryPoolCapacityInMB (IndexSummaryManagerMBean.java:26), setResizeIntervalInMinutes (IndexSummaryManagerMBean.java:49)
- MessagingServiceMBean (1): setBackPressureEnabled (MessagingServiceMBean.java:137)
- ShardedMemtableConfigMXBean (1): setDefaultShardCount (ShardedMemtableConfigMXBean.java:27)
- StreamManagerMBean (2): setStreamingSlowEventsLogTimeout (StreamManagerMBean.java:51), setStreamingStatsEnabled (StreamManagerMBean.java:41)

#### readonly-cli (60)

Reason: Read-only nodetool report commands: they call JMX getters (or temporary samplers, for profileload and toppartitions) and print; repair_admin list/summarize-* and getguardrailsconfig/getautorepairconfig/autorepairstatus included.

- cli-command (60): nodetool autorepairstatus (AutoRepairStatus.java:37), nodetool checktokenmetadata (CheckTokenMetadata.java:28), nodetool cidrfilteringstats (CIDRFilteringStats.java:35), nodetool clientstats (ClientStats.java:35), nodetool compactionhistory (CompactionHistory.java:29), nodetool compactionstats (CompactionStats.java:40), nodetool datapaths (DataPaths.java:32), nodetool describecluster (DescribeCluster.java:35), nodetool describering (DescribeRing.java:30), nodetool failuredetector (FailureDetectorInfo.java:30), nodetool gcstats (GcStats.java:25), nodetool getauditlog (GetAuditLog.java:27), nodetool getauthcacheconfig (GetAuthCacheConfig.java:27), nodetool getautorepairconfig (GetAutoRepairConfig.java:31), nodetool getbatchlogreplaythrottle (GetBatchlogReplayTrottle.java:24), nodetool getcidrgroupsofip (GetCIDRGroupsOfIP.java:34), nodetool getcolumnindexsize (GetColumnIndexSize.java:25), nodetool getcompactionthreshold (GetCompactionThreshold.java:31), nodetool getcompactionthroughput (GetCompactionThroughput.java:28), nodetool getconcurrency (GetConcurrency.java:29), nodetool getconcurrentcompactors (GetConcurrentCompactors.java:25), nodetool getconcurrentviewbuilders (GetConcurrentViewBuilders.java:25), nodetool getdefaultrf (GetDefaultKeyspaceRF.java:25), nodetool getendpoints (GetEndpoints.java:31), nodetool getfullquerylog (GetFullQueryLog.java:27), nodetool getguardrailsconfig (GuardrailsConfigCommand.java:55), nodetool getinterdcstreamthroughput (GetInterDCStreamThroughput.java:27), nodetool getlogginglevels (GetLoggingLevels.java:27), nodetool getmaxhintwindow (GetMaxHintWindow.java:25), nodetool getseeds (GetSeeds.java:27), nodetool getsnapshotthrottle (GetSnapshotThrottle.java:24), nodetool getsstables (GetSSTables.java:33), nodetool getstreamthroughput (GetStreamThroughput.java:27), nodetool gettimeout (GetTimeout.java:31), nodetool gettraceprobability (GetTraceProbability.java:25), nodetool gossipinfo (GossipInfo.java:26), nodetool info (Info.java:38), nodetool listcidrgroups (ListCIDRGroups.java:32), nodetool listpendinghints (ListPendingHints.java:37), nodetool listsnapshots (ListSnapshots.java:35), nodetool netstats (NetStats.java:37), nodetool profileload (ProfileLoad.java:46), nodetool proxyhistograms (ProxyHistograms.java:28), nodetool rangekeysample (RangeKeySample.java:27), nodetool repair_admin list (RepairAdmin.java:48), nodetool repair_admin summarize-pending (RepairAdmin.java:94), nodetool repair_admin summarize-repaired (RepairAdmin.java:153), nodetool ring (Ring.java:43), nodetool status (Status.java:42), nodetool statusautocompaction (StatusAutoCompaction.java:32), nodetool statusbackup (StatusBackup.java:25), nodetool statusbinary (StatusBinary.java:25), nodetool statusgossip (StatusGossip.java:25), nodetool statushandoff (StatusHandoff.java:25), nodetool tablehistograms (TableHistograms.java:43), nodetool tablestats (TableStats.java:30), nodetool toppartitions (TopPartitions.java:22), nodetool tpstats (TpStats.java:28), nodetool version (Version.java:25), nodetool viewbuildstatus (ViewBuildStatus.java:34)

#### cli-config-other (3)

Reason: nodetool commands that only drive configuration owned by other areas or disabled features: setguardrailsconfig (reflective GuardrailsMBean setters), setautorepairconfig (auto-repair disabled), setauthcacheconfig (AuthCacheMBean setters, schema-auth).

- cli-command (3): nodetool setauthcacheconfig (SetAuthCacheConfig.java:28), nodetool setautorepairconfig (SetAutoRepairConfig.java:44), nodetool setguardrailsconfig (GuardrailsConfigCommand.java:172)

#### cli-diagnostic (1)

Reason: nodetool sjk: embedded Swiss Java Knife JVM diagnostics, not Cassandra behavior.

- cli-command (1): nodetool sjk (Sjk.java:67)

#### cli-offline (7)

Reason: Standalone tools that do not talk to a running node's request path: jmxtool (dumps/diffs MBean metadata), fqltool compare/dump/replay (read or replay full query log files from outside), compaction-stress (offline stress of compaction).

- cli-command (7): compaction-stress compact (CompactionStress.java:216), compaction-stress write (CompactionStress.java:282), fqltool compare (Compare.java:43), fqltool dump (Dump.java:53), fqltool replay (Replay.java:47), jmxtool diff (JMXTool.java:191), jmxtool dump (JMXTool.java:112)

#### java-main (23)

Reason: Standalone main() of an offline or client-side tool (sstable utilities, standalone scrub/verify/upgrade/split, bulk loader, stress, token generator, password hasher, log viewers, version printer); they run outside the daemon. DynamicList.main and DistributionQuantized.main are test mains (not an entry point).

- java-main (23): org.apache.cassandra.fqltool.FullQueryLogTool (FullQueryLogTool.java:44), org.apache.cassandra.stress.CompactionStress (CompactionStress.java:357), org.apache.cassandra.stress.Stress (Stress.java:52), org.apache.cassandra.stress.generate.DistributionQuantized (DistributionQuantized.java:85), org.apache.cassandra.tools.AuditLogViewer (AuditLogViewer.java:58), org.apache.cassandra.tools.BulkLoader (BulkLoader.java:55), org.apache.cassandra.tools.GenerateTokens (GenerateTokens.java:50), org.apache.cassandra.tools.GetVersion (GetVersion.java:23), org.apache.cassandra.tools.HashPassword (HashPassword.java:50), org.apache.cassandra.tools.JMXTool (JMXTool.java:857), org.apache.cassandra.tools.SSTableExpiredBlockers (SSTableExpiredBlockers.java:51), org.apache.cassandra.tools.SSTableExport (SSTableExport.java:110), org.apache.cassandra.tools.SSTableLevelResetter (SSTableLevelResetter.java:44), org.apache.cassandra.tools.SSTableMetadataViewer (SSTableMetadataViewer.java:504), org.apache.cassandra.tools.SSTableOfflineRelevel (SSTableOfflineRelevel.java:80), org.apache.cassandra.tools.SSTablePartitions (SSTablePartitions.java:152), org.apache.cassandra.tools.SSTableRepairedAtSetter (SSTableRepairedAtSetter.java:38), org.apache.cassandra.tools.StandaloneSSTableUtil (StandaloneSSTableUtil.java:44), org.apache.cassandra.tools.StandaloneScrubber (StandaloneScrubber.java:82), org.apache.cassandra.tools.StandaloneSplitter (StandaloneSplitter.java:66), org.apache.cassandra.tools.StandaloneUpgrader (StandaloneUpgrader.java:57), org.apache.cassandra.tools.StandaloneVerifier (StandaloneVerifier.java:70), org.apache.cassandra.utils.DynamicList (DynamicList.java:229)

#### python-cli (4)

Reason: cqlsh is the Python CQL shell (a native-protocol client, modeled as the cql-client actor); the doc/scripts entries are documentation generators (not an entry point).

- python-cli (4): convert_yaml_to_adoc (convert_yaml_to_adoc.py:138), cqlprotodoc (cqlprotodoc.py:346), cqlsh (cqlsh.py:87), gen-antora-yml (gen-antora-yml.py:92)

#### tasks (10)

Reason: Background or scheduled housekeeping in utils/metrics/security with no effect on request outcomes: Ref leak detection and reaper, BufferPool cleanup, MonotonicClock approximate-time updaters, ResourceWatcher file polling, SSLFactory certificate hot-reload check (TLS off in the deployed config: internode_encryption none, cassandra.yaml 1648), MessagingMetrics dropped-message logging, TopPartitionTracker hourly save.

- background-task (2): BufferPool.BufferPool: cleanupOneReference (BufferPool.java:195), Ref: Reference-Reaper (Ref::reapOneReference) (Ref.java:385)
- scheduled-task (8): MessagingMetrics.scheduleLogging: logDroppedMessages (MessagingMetrics.java:174), MonotonicClock.AbstractEpochSamplingClock.resumeEpochSampling: updateAlmostSameTime (MonotonicClock.java:210), MonotonicClock.SampledClock.resumeNowSampling: precise.now (MonotonicClock.java:346), Ref: StrongLeakDetector (Ref.java:392), Ref: Visitor (Ref.java:391), ResourceWatcher.watch: WatchedResource (ResourceWatcher.java:32), SSLFactory.initHotReloading: SSLFactory::checkCertFilesForHotReloading (SSLFactory.java:275), TopPartitionTracker.TopPartitionTracker: save (TopPartitionTracker.java:91)

#### memtable-cleaner (1)

Reason: MemtableCleanerThread (utils/memory): when memtable memory passes memtable_cleanup_threshold it flushes the largest memtable; the flush itself is write-path's model (ColumnFamilyStore flush).

- background-task (1): MemtableCleanerThread.MemtableCleanerThread: clean (MemtableCleanerThread.java:120)

#### resurrection-heartbeat (1)

Reason: DataResurrectionCheck heartbeat writer: only scheduled by the check_data_resurrection startup check, which is disabled by default (startup_checks commented out, cassandra.yaml 2270; StartupCheckType.check_data_resurrection(true), StartupChecks.java:113).

- scheduled-task (1): DataResurrectionCheck.postAction: Heartbeat (DataResurrectionCheck.java:251)

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


"""StorageService/StorageProxy/CacheService/ActiveRepairService MBean operations."""
from gen_base import *
from gen_ops import ss, sp, cs, jop, KS, VOID, ISE, IAE, IOE, RTE, CS

TBL = a_(s_(), default=[])


def per_table(keyspace_expr, tables_expr, steps, allow=True):
    """Resolve the tables like getValidColumnFamilies, then run steps for each."""
    return [
        {'call': 'storage-service-mbean.get-valid-column-families', 'as': 'cfs', 'input': {'keyspace': keyspace_expr, 'tables': tables_expr}},
        {'foreach': '= vars.cfs.value.tables', 'as': 't', 'steps': steps},
    ]


def status_op(method, summary, impl, cm_iface, extra_req=None, pre=None, impl_extra=None, op_name=None):
    """StorageService ops that run a CompactionManager AllSSTableOpStatus job per table and return the worst status code."""
    req = obj(dict({'keyspace': KS, 'tables': TBL, 'jobs': i_(default=2)}, **(extra_req or {})), ['keyspace'])
    beh = list(pre or []) + [{'set': {'vars.status': 'SUCCESSFUL'}}] + per_table('= input.keyspace', '= input.tables', [
        {'title': 'Run the job for this table', 'source': impl if isinstance(impl, str) else impl[0],
         'call': cm_iface, 'as': 'r', 'input': {'replica': '= self', 'keyspace': '= input.keyspace', 'table': '= vars.t', 'jobs': '= input.jobs'}},
        {'choice': 'op_status', 'default': '= vars.r.value.status', 'options': {
            'SUCCESSFUL': [{'set': {'vars.one': 'SUCCESSFUL'}}],
            'ABORTED': [{'set': {'vars.one': 'ABORTED'}}],
            'UNABLE_TO_CANCEL': [{'set': {'vars.one': 'UNABLE_TO_CANCEL'}}]}},
        {'when': "vars.one != 'SUCCESSFUL'", 'set': {'vars.status': '= vars.one'}},
    ]) + [
        {'title': 'Return AllSSTableOpStatus.statusCode (0 SUCCESSFUL, 1 ABORTED, 2 UNABLE_TO_CANCEL)', 'source': at(J + 'db/compaction/CompactionManager.java', 502, 'public enum AllSSTableOpStatus'),
         'return': {'status_code': "= vars.status == 'SUCCESSFUL' ? 0 : (vars.status == 'ABORTED' ? 1 : 2)", 'status': '= vars.status'}},
    ]
    return ss(method, summary, [impl] + (impl_extra or []) if isinstance(impl, str) else impl, req,
              obj({'status_code': i_(default=0), 'status': s_(default='SUCCESSFUL')}), beh, [IAE, RTE])


# ---------------------------------------------------------------- flush / compaction family
ss('forceKeyspaceFlush', 'StorageService.forceKeyspaceFlush: forceBlockingFlush(USER_FORCED) on every valid table of the keyspace (all tables when none are named).',
   rng(SS, 4743, 4750, 'public void forceKeyspaceFlush(String keyspaceName, String... tableNames)'),
   obj({'keyspace': KS, 'tables': TBL}, ['keyspace']), VOID,
   per_table('= input.keyspace', '= input.tables', [
       {'title': 'cfStore.forceBlockingFlush(USER_FORCED)', 'source': at(SS, 4748, 'cfStore.forceBlockingFlush(ColumnFamilyStore.FlushReason.USER_FORCED);'),
        'call': 'column-family-store.force-blocking-flush', 'input': {'keyspace': '= input.keyspace', 'table': '= vars.t', 'replica': '= self', 'reason': 'USER_FORCED'}}]) + [{'return': {}}],
   [IAE, IOE])
status_op('forceKeyspaceCleanup', 'StorageService.forceKeyspaceCleanup: refuse for local system keyspaces and while this node has pending ranges, then performCleanup per table.',
          rng(SS, 4154, 4172, 'public int forceKeyspaceCleanup(int jobs, String keyspaceName'), 'compaction-manager.perform-cleanup',
          pre=[
              {'if': 'input.keyspace in state.local_system_keyspaces', 'then': [
                  {'title': 'Cleanup of a local system keyspace is refused', 'source': rng(SS, 4156, 4157, 'isLocalSystemKeyspace(keyspaceName)'),
                   'fail': {'code': 'runtime-exception', 'message': 'Cleanup of the system keyspace is neither necessary nor wise'}}]},
              {'call': 'token-metadata.get-pending-ranges', 'as': 'pr', 'input': {'keyspace': '= input.keyspace', 'endpoint': '= self'}},
              {'choice': 'pending_ranges', 'default': "= size(vars.pr.value.ranges) > 0 ? 'pending' : 'none'", 'options': {
                  'none': [],
                  'pending': [{'title': 'Node is involved in a membership change', 'source': rng(SS, 4159, 4160, 'getPendingRanges(keyspaceName'),
                               'fail': {'code': 'runtime-exception', 'message': 'Node is involved in cluster membership changes. Not safe to run cleanup.'}}]}},
          ])
status_op('scrub', 'StorageService.scrub: performScrub on every valid table (snapshot first unless disabled) and return the worst AllSSTableOpStatus.',
          rng(SS, 4184, 4196, 'public int scrub(boolean disableSnapshot, IScrubber.Options options'), 'compaction-manager.perform-scrub',
          impl_extra=[rng(SS, 4174, 4182, None)])
status_op('verify', 'StorageService.verify: performVerify on every valid table and return the worst AllSSTableOpStatus.',
          rng(SS, 4205, 4223, 'public int verify(boolean extendedVerify, boolean checkVersion'), 'compaction-manager.perform-verify')
status_op('upgradeSSTables', 'StorageService.upgradeSSTables: rewriteSSTables, rewriting SSTables not on the current version (performSSTableRewrite) per table.',
          rng(SS, 4225, 4237, None), 'compaction-manager.perform-sstable-rewrite', impl_extra=[rng(SS, 4247, 4266, 'public int rewriteSSTables(String keyspaceName,')])
status_op('recompressSSTables', 'StorageService.recompressSSTables: rewriteSSTables keeping only SSTables whose compression differs from the table params.',
          rng(SS, 4239, 4244, 'public int recompressSSTables(String keyspaceName,'), 'compaction-manager.perform-sstable-rewrite', impl_extra=[rng(SS, 4247, 4266, 'public int rewriteSSTables(String keyspaceName,')])
status_op('garbageCollect', 'StorageService.garbageCollect: performGarbageCollection (tombstone option ROW or CELL) per table.',
          rng(SS, 4308, 4321, 'public int garbageCollect(String tombstoneOptionString'), 'compaction-manager.perform-garbage-collection',
          extra_req={'tombstone_option': s_(enum=['NONE', 'ROW', 'CELL'], default='ROW')})
status_op('relocateSSTables', 'StorageService.relocateSSTables: move SSTables to the data directory owning their token range, per table.',
          rng(SS, 4294, 4306, 'public int relocateSSTables(int jobs, String keyspaceName'), 'compaction-manager.relocate-sstables')
ss('forceKeyspaceCompaction', 'StorageService.forceKeyspaceCompaction: major compaction (forceMajorCompaction, CompactionManager.performMaximal) of every valid table.',
   rng(SS, 4281, 4287, 'public void forceKeyspaceCompaction(boolean splitOutput'),
   obj({'keyspace': KS, 'tables': TBL, 'split_output': b_(default=False)}, ['keyspace']), VOID,
   per_table('= input.keyspace', '= input.tables', [
       {'title': 'cfStore.forceMajorCompaction(splitOutput)', 'source': at(SS, 4285, 'cfStore.forceMajorCompaction(splitOutput);'),
        'call': 'compaction-manager.perform-maximal', 'input': {'replica': '= self', 'keyspace': '= input.keyspace', 'table': '= vars.t', 'split_output': '= input.split_output'}}]) + [{'return': {}}],
   [IAE], extra_sources=[rng(J + 'db/ColumnFamilyStore.java', 2518, 2521, 'public void forceMajorCompaction(boolean splitOutput)')])
ss('forceKeyspaceCompactionForTokenRange', 'StorageService.forceKeyspaceCompactionForTokenRange: compact only SSTables overlapping (start, end] on every valid table.',
   rng(SS, 4373, 4381, 'public void forceKeyspaceCompactionForTokenRange'),
   obj({'keyspace': KS, 'tables': TBL, 'start_token': s_(ex='-9223372036854775808'), 'end_token': s_(ex='0')}, ['keyspace']), VOID,
   per_table('= input.keyspace', '= input.tables', [
       {'call': 'compaction-manager.force-compaction-for-token-range', 'input': {'replica': '= self', 'keyspace': '= input.keyspace', 'table': '= vars.t', 'ranges': ["= '(' + input.start_token + ',' + input.end_token + ']'"]}}]) + [{'return': {}}], [IAE])
ss('forceKeyspaceCompactionForPartitionKey', 'StorageService.forceKeyspaceCompactionForPartitionKey: validate the key parses for each table, then compact the SSTables holding it.',
   rng(SS, 4384, 4405, 'public void forceKeyspaceCompactionForPartitionKey'),
   obj({'keyspace': KS, 'tables': TBL, 'partition_key': s_(ex='user:42')}, ['keyspace']), VOID,
   per_table('= input.keyspace', '= input.tables', [
       {'call': 'compaction-manager.force-compaction-for-token-range', 'input': {'replica': '= self', 'keyspace': '= input.keyspace', 'table': '= vars.t', 'ranges': ['= input.partition_key']}}]) + [{'return': {}}], [IAE])
ss('forceCompactionKeysIgnoringGcGrace', 'StorageService.forceCompactionKeysIgnoringGcGrace: compact the given partitions of one table purging tombstones regardless of gc_grace.',
   rng(SS, 4418, 4423, None), obj({'keyspace': KS, 'table': s_(ex='users'), 'keys': a_(s_(), default=['user:42'])}, ['keyspace', 'table']), VOID,
   [{'call': 'storage-service-mbean.get-valid-column-families', 'input': {'keyspace': '= input.keyspace', 'tables': ['= input.table']}},
    {'call': 'column-family-store.force-compaction-keys-ignoring-gc-grace', 'input': {'keyspace': '= input.keyspace', 'table': '= input.table', 'keys': '= input.keys'}},
    {'return': {}}], [IAE])
ss('disableAutoCompaction', 'StorageService.disableAutoCompaction(ks, tables): disable auto-compaction on every valid table (indexes included).',
   rng(SS, 6641, 6647, 'public void disableAutoCompaction(String ks, String... tables)'), obj({'keyspace': KS, 'tables': TBL}, ['keyspace']), VOID,
   per_table('= input.keyspace', '= input.tables', [{'call': 'column-family-store.disable-auto-compaction', 'input': {'keyspace': '= input.keyspace', 'table': '= vars.t'}}]) + [{'return': {}}], [IAE])
ss('enableAutoCompaction', 'StorageService.enableAutoCompaction(ks, tables): refused while draining/drained or not NORMAL, else enable auto-compaction on every valid table.',
   rng(SS, 6649, 6657, 'void enableAutoCompaction(String ks, String... tables)'), obj({'keyspace': KS, 'tables': TBL}, ['keyspace']), VOID,
   [{'title': 'checkServiceAllowedToStart("auto compaction")', 'source': at(SS, 6651, 'checkServiceAllowedToStart("auto compaction");'),
     'call': 'storage-service.check-service-allowed-to-start', 'input': {'service': 'auto compaction'}}] +
   per_table('= input.keyspace', '= input.tables', [{'call': 'column-family-store.enable-auto-compaction', 'input': {'keyspace': '= input.keyspace', 'table': '= vars.t'}}]) + [{'return': {}}], [IAE, ISE])

# ---------------------------------------------------------------- snapshots
# ---------------------------------------------------------------- repair
ss('forceTerminateAllRepairSessions', 'StorageService.forceTerminateAllRepairSessions: ActiveRepairService.terminateSessions.',
   rng(SS, 4963, 4966, 'public void forceTerminateAllRepairSessions()'), VOID, VOID, [{'call': 'active-repair-service.terminate-sessions'}, {'return': {}}])

# ---------------------------------------------------------------- lifecycle (membership) call-throughs
# ---------------------------------------------------------------- transports, gossip, daemon
ss('startNativeTransport', 'StorageService.startNativeTransport: checkServiceAllowedToStart("native transport"), then CassandraDaemon.startNativeTransport; failures become RuntimeException.',
   rng(SS, 631, 648, 'public synchronized void startNativeTransport()'), VOID, VOID,
   [{'call': 'storage-service.check-service-allowed-to-start', 'input': {'service': 'native transport'}},
    {'call': 'cassandra-daemon.start-native-transport', 'on_error': [
        {'title': 'Wrapped as RuntimeException', 'source': rng(SS, 643, 647, 'catch (Exception e)'),
         'fail': {'code': 'runtime-exception', 'message': "= 'Error starting native transport: ' + error.message"}}]},
    {'return': {}}], [ISE, RTE])
ss('stopNativeTransport', 'StorageService.stopNativeTransport(force): CassandraDaemon.stopNativeTransport.',
   rng(SS, 650, 657, 'public void stopNativeTransport(boolean force)'), obj({'force': b_(default=False)}), VOID,
   [{'call': 'cassandra-daemon.stop-native-transport', 'input': {'force': '= input.force'}}, {'return': {}}])
ss('stopDaemon', 'StorageService.stopDaemon: CassandraDaemon.deactivate (stops transports and JMX, exits the JVM).',
   rng(SS, 735, 740, 'public void stopDaemon()'), VOID, VOID, [{'call': 'cassandra-daemon.deactivate'}, {'return': {}}])
for m, val, lo, hi in [('enableNativeTransportOldProtocolVersions', True, 669, 672), ('disableNativeTransportOldProtocolVersions', False, 675, 678)]:
    ss(m, 'StorageService.%s: DatabaseDescriptor.setNativeTransportAllowOlderProtocols(%s).' % (m, str(val).lower()),
       rng(SS, lo, hi, None), VOID, VOID, [{'set': {'state.native_transport_allow_older_protocols': val}}, {'return': {}}])
ss('clearConnectionHistory', 'StorageService.clearConnectionHistory: CassandraDaemon clears the native transport connection history.',
   rng(SS, 6961, 6965, 'public void clearConnectionHistory()'), VOID, VOID, [{'return': {}}])

# ---------------------------------------------------------------- schema, size estimates, misc
ss('resetLocalSchema', 'StorageService.resetLocalSchema: Schema.resetLocalSchema (drop local schema, re-pull from peers).',
   rng(SS, 6616, 6619, 'public void resetLocalSchema()'), VOID, VOID, [{'call': 'schema.reset-local-schema'}, {'return': {}}], [IOE])
ss('reloadLocalSchema', 'StorageService.reloadLocalSchema: Schema.reloadSchemaAndAnnounceVersion.',
   rng(SS, 6621, 6624, 'public void reloadLocalSchema()'), VOID, VOID, [{'call': 'schema.reload-schema-and-announce-version'}, {'return': {}}])
ss('refreshSizeEstimates', 'StorageService.refreshSizeEstimates: clear system.size_estimates and run SizeEstimatesRecorder now, waiting for it.',
   rng(SS, 4713, 4717, 'public void refreshSizeEstimates()'), VOID, VOID, [{'return': {}}])
ss('loadNewSSTables', 'StorageService.loadNewSSTables (nodetool refresh): refuse before initialisation, validate the keyspace, then ColumnFamilyStore.loadNewSSTables.',
   rng(SS, 6498, 6504, 'public void loadNewSSTables(String ksName, String cfName)'), obj({'keyspace': KS, 'table': s_(ex='users')}, ['keyspace', 'table']), VOID,
   [{'call': 'storage-service-mbean.get-valid-column-families', 'input': {'keyspace': '= input.keyspace', 'tables': []}},
    {'call': 'column-family-store.load-new-sstables', 'input': {'keyspace': '= input.keyspace', 'table': '= input.table'}}, {'return': {}}], [IAE, RTE])
ss('rebuildSecondaryIndex', 'StorageService.rebuildSecondaryIndex: map index table names to index names and rebuild them on the base table.',
   rng(SS, 6606, 6614, 'public void rebuildSecondaryIndex(String ksName, String cfName'), obj({'keyspace': KS, 'table': s_(ex='users'), 'indexes': a_(s_(), default=['users_email_idx'])}, ['keyspace', 'table']), VOID,
   [{'call': 'column-family-store.rebuild-secondary-index', 'input': '= input'}, {'return': {}}])
ss('truncate', 'StorageService.truncate: validate the keyspace and StorageProxy.truncateBlocking; UnavailableException becomes IOException.',
   rng(SS, 6088, 6100, 'public void truncate(String keyspace, String table)'), obj({'keyspace': KS, 'table': s_(ex='users')}, ['keyspace', 'table']), VOID,
   [{'call': 'storage-service-mbean.get-valid-column-families', 'input': {'keyspace': '= input.keyspace', 'tables': ['= input.table']}},
    {'call': 'storage-proxy.truncate-blocking', 'input': '= input', 'on_error': [
        {'if': "error.code == 'unavailable'", 'then': [{'title': 'UnavailableException is rethrown as IOException', 'source': rng(SS, 6096, 6099, 'catch (UnavailableException e)'),
                                                         'fail': {'code': 'io-exception', 'message': '= error.message'}}]},
        {'fail': '= error'}]},
    {'return': {}}], [IAE, IOE])
ss('mutateSSTableRepairedState', 'StorageService.mutateSSTableRepairedState: mark the SSTables of the named tables repaired or unrepaired (preview lists them without changing).',
   rng(SS, 7740, 7768, None), obj({'keyspace': KS, 'tables': TBL, 'repaired': b_(default=True), 'preview': b_(default=True)}, ['keyspace']), obj({'sstables': a_(s_(), default=[])}),
   [{'foreach': '= input.tables', 'as': 't', 'steps': [
       {'if': '!(vars.t in state.tables[input.keyspace])', 'then': [
           {'title': 'Unknown table', 'source': at(SS, 7745, 'throw new RuntimeException("Table " + tableName + " does not exist in keyspace "'),
            'fail': {'code': 'runtime-exception', 'message': "= 'Table ' + vars.t + ' does not exist in keyspace ' + input.keyspace"}}]}]},
    {'return': {'sstables': []}}], [RTE])
ss('dropPreparedStatements', 'StorageService.dropPreparedStatements: QueryProcessor.clearPreparedStatements(memoryOnly).',
   rng(SS, 4275, 4278, 'public void dropPreparedStatements(boolean memoryOnly)'), obj({'memory_only': b_(default=False)}), VOID,
   [{'call': 'query-processor.clear-prepared-statements', 'input': {'memory_only': '= input.memory_only'}}, {'return': {}}])

# ---------------------------------------------------------------- audit / FQL
ss('enableAuditLog', 'StorageService.enableAuditLog: refuse an archive command unless allow_nodetool_archive_command, build AuditLogOptions from the yaml defaults plus overrides, AuditLogManager.enable.',
   [rng(SS, 6998, 7025, 'public void enableAuditLog(String loggerName, Map<String, String> parameters'), rng(SS, 6974, 6987, None)],
   obj({'logger': s_(default='BinAuditLogger'), 'included_keyspaces': a_(s_(), default=[]), 'excluded_keyspaces': a_(s_(), default=['system', 'system_schema', 'system_virtual_schema']),
        'included_categories': a_(s_(), default=[]), 'excluded_categories': a_(s_(), default=[]), 'included_users': a_(s_(), default=[]), 'excluded_users': a_(s_(), default=[]),
        'archive_command': s_(default='')}), VOID,
   [{'if': "input.archive_command != '' && !config['audit-logging-allow-nodetool-archive-command']", 'then': [
       {'title': 'allow_nodetool_archive_command is false by default', 'source': rng(SS, 7003, 7004, 'allow_nodetool_archive_command'),
        'fail': {'code': 'configuration-exception', 'message': "Can't enable audit log archiving via nodetool unless audit_logging_options.allow_nodetool_archive_command is set to true"}}]},
    {'call': 'audit-log-manager.enable', 'input': {'logger': '= input.logger', 'included_keyspaces': '= input.included_keyspaces', 'excluded_keyspaces': '= input.excluded_keyspaces',
                                                   'included_categories': '= input.included_categories', 'excluded_categories': '= input.excluded_categories',
                                                   'included_users': '= input.included_users', 'excluded_users': '= input.excluded_users'}},
    {'return': {}}], [err('configuration-exception'), ISE])
ss('disableAuditLog', 'StorageService.disableAuditLog: AuditLogManager.disableAuditLog.',
   rng(SS, 6966, 6970, 'public void disableAuditLog()'), VOID, VOID, [{'call': 'audit-log-manager.disable-audit-log'}, {'return': {}}])
ss('enableFullQueryLogger', 'StorageService.enableFullQueryLogger: fill unset parameters from full_query_logging_options, refuse an archive command unless allowed, FullQueryLogger.enableWithoutClean.',
   rng(SS, 7131, 7146, 'public void enableFullQueryLogger'), obj({'path': s_(default=''), 'roll_cycle': s_(default='HOURLY'), 'blocking': b_(default=True), 'archive_command': s_(default='')}), VOID,
   [{'if': "input.archive_command != '' && !config['full-query-logging-allow-nodetool-archive-command']", 'then': [
       {'source': rng(SS, 7139, 7140, 'allow_nodetool_archive_command'), 'title': 'Archive command refused',
        'fail': {'code': 'configuration-exception', 'message': "Can't enable full query log archiving via nodetool unless full_query_logging_options.allow_nodetool_archive_command is set to true"}}]},
    {'title': 'path defaults to full_query_logging_options.log_dir, which is "" in the deployed config', 'source': at(SS, 7134, 'path = path != null ? path : fqlOptions.log_dir;'),
     'call': 'full-query-logger.enable-without-clean', 'input': {'path': "= input.path != '' ? input.path : config['full-query-logging-log-dir']", 'roll_cycle': '= input.roll_cycle', 'blocking': '= input.blocking'}},
    {'return': {}}], [err('configuration-exception'), IAE, ISE])
ss('stopFullQueryLogger', 'StorageService.stopFullQueryLogger: FullQueryLogger.stop.', rng(SS, 7155, 7158, 'public void stopFullQueryLogger()'), VOID, VOID,
   [{'call': 'full-query-logger.stop'}, {'return': {}}])
ss('resetFullQueryLogger', 'StorageService.resetFullQueryLogger: FullQueryLogger.reset with the configured log_dir.', rng(SS, 7149, 7152, 'public void resetFullQueryLogger()'), VOID, VOID,
   [{'call': 'full-query-logger.reset', 'input': {'log_dir': ''}}, {'return': {}}])

# ---------------------------------------------------------------- runtime config setters reached by nodetool
def setter(method, lo, hi, needle, field, summary, value_schema, extra=None, pre=None, mbean='ss'):
    beh = list(pre or []) + [{'title': summary, 'source': rng(SS if mbean == 'ss' else SP, lo, hi, needle), 'set': {'state.' + field: '= input.value'}}] + list(extra or []) + [{'return': {}}]
    f = ss if mbean == 'ss' else sp
    return f(method, summary, rng(SS if mbean == 'ss' else SP, lo, hi, needle), obj({'value': value_schema}, ['value']), VOID, beh, [IAE] if pre else None)


setter('setIncrementalBackupsEnabled', 2049, 2052, 'public void setIncrementalBackupsEnabled', 'incremental_backups', 'DatabaseDescriptor.setIncrementalBackupsEnabled (incremental_backups, yaml 1135: false).', b_())
setter('setCompactionThroughputMbPerSec', 1924, 1932, 'public void setCompactionThroughputMbPerSec', 'compaction_throughput_mib_per_sec',
       'Set compaction_throughput (MiB/s) and reset the compaction RateLimiter in bytes per second.', i_(ex=128),
       extra=[{'title': 'CompactionManager.setRateInBytes(value * 1024 * 1024)', 'source': at(SS, 1928, 'CompactionManager.instance.setRateInBytes(valueInBytes);'),
               'call': 'compaction-manager.set-rate-in-bytes', 'input': {'bytes_per_second': '= double(input.value) * 1048576.0'}}])
setter('setConcurrentCompactors', 1964, 1970, 'public void setConcurrentCompactors', 'concurrent_compactors', 'Set concurrent_compactors and resize the compaction executor; values <= 0 are refused.', i_(ex=4),
       pre=[{'if': 'input.value <= 0', 'then': [{'source': at(SS, 1966, 'if (value <= 0)'), 'title': 'Refused',
                                                'fail': {'code': 'illegal-argument-exception', 'message': 'Number of concurrent compactors should be greater than 0.'}}]}],
       extra=[{'call': 'compaction-manager.set-concurrent-compactors', 'input': {'value': '= input.value'}}])
setter('setConcurrentViewBuilders', 2036, 2042, None, 'concurrent_view_builders', 'Set concurrent_materialized_view_builders and resize the view build executor; values <= 0 are refused.', i_(ex=2),
       pre=[{'if': 'input.value <= 0', 'then': [{'source': at(SS, 2038, 'if (value <= 0)'), 'title': 'Refused',
                                                'fail': {'code': 'illegal-argument-exception', 'message': 'Number of concurrent view builders should be greater than 0.'}}]}],
       extra=[{'call': 'compaction-manager.set-concurrent-view-builders', 'input': {'value': '= input.value'}}])
setter('setBatchlogReplayThrottleInKB', 1953, 1957, None, 'batchlog_replay_throttle_kib', 'Set batchlog_replay_throttle and BatchlogManager.setRate.', i_(ex=2048),
       extra=[{'call': 'batchlog-manager.set-rate', 'input': {'throttle_kib': '= input.value'}}])
setter('setHintedHandoffThrottleInKB', 6917, 6921, None, 'hinted_handoff_throttle_kib', 'Set hinted_handoff_throttle (KiB/s per delivery thread, shared across nodes).', i_(ex=2048))
setter('setColumnIndexSize', 6779, 6784, None, 'column_index_size_kib', 'Set column_index_size in KiB for new SSTables.', i_(ex=16))
setter('setSnapshotLinksPerSecond', 4702, 4706, None, 'snapshot_links_per_second', 'Set snapshot_links_per_second (0 = unthrottled).', i_(ex=100))
setter('setDefaultKeyspaceReplicationFactor', 7362, 7366, None, 'default_keyspace_rf', 'Set default_keyspace_rf used by CREATE KEYSPACE without a replication factor.', i_(ex=3))
setter('setTraceProbability', 6626, 6629, 'public void setTraceProbability(double probability)', 'trace_probability',
       'Set the probability that a request is traced without the client asking (StorageService.traceProbability; transport checks shouldTraceProbablistically).', n_(ex=0.01))
for m, lo, hi, field, summ in [
    ('setStreamThroughputMbitPerSec', 1782, 1789, 'stream_throughput_mib', 'Set stream_throughput_outbound (megabits/s; <= 0 unlimited) and update the stream rate limiter.'),
    ('setStreamThroughputMebibytesPerSec', 1791, 1797, 'stream_throughput_mib', 'Set stream_throughput_outbound in MiB/s and update the stream rate limiter.'),
    ('setEntireSSTableStreamThroughputMebibytesPerSec', 1828, 1835, 'entire_sstable_stream_throughput_mib', 'Set entire_sstable_stream_throughput_outbound and update its limiter.'),
    ('setInterDCStreamThroughputMbitPerSec', 1849, 1855, 'inter_dc_stream_throughput_mib', 'Set inter_dc_stream_throughput_outbound (megabits/s) and update the limiter.'),
    ('setInterDCStreamThroughputMebibytesPerSec', 1876, 1882, 'inter_dc_stream_throughput_mib', 'Set inter_dc_stream_throughput_outbound in MiB/s and update the limiter.'),
    ('setEntireSSTableInterDCStreamThroughputMebibytesPerSec', 1894, 1900, 'entire_sstable_inter_dc_stream_throughput_mib', 'Set entire_sstable_inter_dc_stream_throughput_outbound and update its limiter.')]:
    tgt = 'stream-manager-stream-rate-limiter.' + ('update-entire-sstable-inter-dc-throughput' if 'EntireSSTableInterDC' in m else 'update-entire-sstable-throughput' if 'EntireSSTable' in m
                                                   else 'update-inter-dc-throughput' if 'InterDC' in m else 'update-throughput')
    setter(m, lo, hi, None, field, summ, i_(ex=48), extra=[{'call': tgt}])
for m, lo, hi, key in [('setRpcTimeout', 1664, 1668, 'misc'), ('setReadRpcTimeout', 1675, 1679, 'read'), ('setRangeRpcTimeout', 1686, 1690, 'range'),
                       ('setWriteRpcTimeout', 1697, 1701, 'write'), ('setInternodeTcpConnectTimeoutInMS', 1708, 1712, 'internodeconnect'),
                       ('setInternodeTcpUserTimeoutInMS', 1719, 1723, 'internodeuser'), ('setCounterWriteRpcTimeout', 1742, 1746, 'counterwrite'),
                       ('setCasContentionTimeout', 1753, 1757, 'cascontention'), ('setTruncateRpcTimeout', 1764, 1768, 'truncate')]:
    ss(m, 'StorageService.%s: DatabaseDescriptor setter for the %s timeout (ms); read by later requests.' % (m, key), rng(SS, lo, hi, 'public void ' + m),
       obj({'value': i_(ex=3000)}, ['value']), VOID,
       [{'set': {'state.timeout_%s_ms' % key: '= input.value'}}, {'return': {}}])
ss('setInternodeStreamingTcpUserTimeoutInMS', 'StorageService.setInternodeStreamingTcpUserTimeoutInMS: refuse negative values, then set the streaming TCP user timeout.',
   rng(SS, 1730, 1735, 'public void setInternodeStreamingTcpUserTimeoutInMS'), obj({'value': i_(ex=300000)}, ['value']), VOID,
   [{'if': 'input.value < 0', 'then': [{'source': at(SS, 1732, 'Preconditions.checkArgument(value >= 0'), 'title': 'Negative value refused',
                                         'fail': {'code': 'illegal-argument-exception', 'message': "= 'TCP user timeout cannot be negative for internode streaming connection. Got ' + string(input.value)"}}]},
    {'set': {'state.timeout_internodestreaminguser_ms': '= input.value'}}, {'return': {}}], [IAE])
ss('setLoggingLevel', 'StorageService.setLoggingLevel: LoggingSupport (logback) sets the level of a logger, or resets to logback.xml when both arguments are empty.',
   rng(SS, 5215, 5218, 'public void setLoggingLevel(String classQualifier, String rawLevel)'), obj({'class_qualifier': s_(ex='org.apache.cassandra.gms'), 'level': s_(ex='DEBUG')}), VOID,
   [{'title': 'LogbackLoggingSupport.setLoggingLevel', 'source': at(SS, 5217, 'LoggingSupportFactory.getLoggingSupport().setLoggingLevel(classQualifier, rawLevel);'),
     'set': {'ctx.opsLoggingLevelSet': "= input.class_qualifier + '=' + input.level"}},
    {'return': {}}], [err('exception', 'invalid level or logger')])
ss('setConcurrency', 'StorageService.setConcurrency: resize a stage\'s thread pool (core size only when >= 0); an unknown pool name is an IllegalArgumentException from Stage.fromPoolName.',
   rng(SS, 2397, 2403, 'public void setConcurrency(String threadPoolName'), obj({'pool': s_(ex='MutationStage'), 'core': i_(default=-1), 'max': i_(ex=64)}, ['pool', 'max']), VOID,
   [{'if': '!(input.pool in state.stage_pools)', 'then': [
       {'title': 'Stage.fromPoolName: an unknown pool name is an IllegalStateException', 'source': rng(J + 'concurrent/Stage.java', 92, 121, 'public static Stage fromPoolName(String stageName)'),
        'fail': {'code': 'illegal-state-exception', 'message': 'Must be one of READ,MUTATION,COUNTER_MUTATION,VIEW_MUTATION,GOSSIP,REQUEST_RESPONSE,ANTI_ENTROPY,MIGRATION,MISC,TRACING,INTERNAL_RESPONSE,IMMEDIATE,PAXOS_REPAIR'}}]},
    {'set': {'ctx.opsStageResized': "= input.pool + ':' + string(input.max)"}}, {'return': {}}], [ISE])

# ---------------------------------------------------------------- StorageProxyMBean
setter('setHintedHandoffEnabled', 2377, 2386, 'public void setHintedHandoffEnabled(boolean b)', 'hinted_handoff_enabled',
       'StorageProxy.setHintedHandoffEnabled: enabling checks checkServiceAllowedToStart("hinted handoff") first; DatabaseDescriptor.setHintedHandoffEnabled.', b_(),
       mbean='sp', pre=[{'when': 'input.value', 'title': 'Enabling is refused while draining, drained or not NORMAL', 'source': at(SP, 2382, 'StorageService.instance.checkServiceAllowedToStart("hinted handoff");'),
                         'call': 'storage-service.check-service-allowed-to-start', 'input': {'service': 'hinted handoff'}}])
setter('setMaxHintWindow', 2408, 2411, 'public void setMaxHintWindow(int ms)', 'max_hint_window_ms', 'StorageProxy.setMaxHintWindow: DatabaseDescriptor.setMaxHintWindow (ms).', i_(ex=7200000), mbean='sp')
sp('enableHintsForDC', 'StorageProxy.enableHintsForDC: remove the DC from hinted_handoff_disabled_datacenters.', rng(SP, 2388, 2391, 'public void enableHintsForDC(String dc)'),
   obj({'dc': s_(ex='dc2')}, ['dc']), VOID, [{'set': {'state.hints_disabled_dcs': '= state.hints_disabled_dcs.filter(d, d != input.dc)'}}, {'return': {}}])
sp('disableHintsForDC', 'StorageProxy.disableHintsForDC: add the DC to hinted_handoff_disabled_datacenters.', rng(SP, 2393, 2396, 'public void disableHintsForDC(String dc)'),
   obj({'dc': s_(ex='dc2')}, ['dc']), VOID, [{'set': {'state.hints_disabled_dcs': '= state.hints_disabled_dcs.filter(d, d != input.dc) + [input.dc]'}}, {'return': {}}])
sp('reloadTriggerClasses', 'StorageProxy.reloadTriggerClasses: TriggerExecutor.reloadClasses (re-scan the triggers directory).', rng(SP, 2857, 2857, None), VOID, VOID, [{'return': {}}])
for m, lo, hi, field, val in [
    ('enableRepairedDataTrackingForRangeReads', 2908, 2911, 'repaired_data_tracking_range_reads', True), ('disableRepairedDataTrackingForRangeReads', 2914, 2917, 'repaired_data_tracking_range_reads', False),
    ('enableRepairedDataTrackingForPartitionReads', 2926, 2929, 'repaired_data_tracking_partition_reads', True), ('disableRepairedDataTrackingForPartitionReads', 2932, 2935, 'repaired_data_tracking_partition_reads', False),
    ('enableReportingUnconfirmedRepairedDataMismatches', 2944, 2947, 'report_unconfirmed_repaired_data_mismatches', True), ('disableReportingUnconfirmedRepairedDataMismatches', 2950, 2953, 'report_unconfirmed_repaired_data_mismatches', False),
    ('enableSnapshotOnRepairedDataMismatch', 2968, 2971, 'snapshot_on_repaired_data_mismatch', True), ('disableSnapshotOnRepairedDataMismatch', 2974, 2977, 'snapshot_on_repaired_data_mismatch', False),
    ('enableSnapshotOnDuplicateRowDetection', 3015, 3018, 'snapshot_on_duplicate_row_detection', True), ('disableSnapshotOnDuplicateRowDetection', 3021, 3024, 'snapshot_on_duplicate_row_detection', False),
    ('enableCheckForDuplicateRowsDuringReads', 3033, 3036, 'check_duplicate_rows_reads', True), ('disableCheckForDuplicateRowsDuringReads', 3039, 3042, 'check_duplicate_rows_reads', False),
    ('enableCheckForDuplicateRowsDuringCompaction', 3051, 3054, 'check_duplicate_rows_compaction', True), ('disableCheckForDuplicateRowsDuringCompaction', 3057, 3060, 'check_duplicate_rows_compaction', False)]:
    sp(m, 'StorageProxy.%s: flip the DatabaseDescriptor flag %s (JMX only).' % (m, field), rng(SP, lo, hi, 'public void ' + m), VOID, VOID,
       [{'set': {'state.' + field: val}}, {'return': {}}])
sp('loadPartitionDenylist', 'StorageProxy.loadPartitionDenylist: reload the partition denylist cache from system_distributed.partition_denylist.', rng(SP, 3068, 3071, 'public void loadPartitionDenylist()'), VOID, VOID, [{'return': {}}])
sp('denylistKey', 'StorageProxy.denylistKey: false when the keyspace or table is unknown, else add the key to the partition denylist.', rng(SP, 3129, 3140, 'public boolean denylistKey'),
   obj({'keyspace': KS, 'table': s_(ex='users'), 'partition_key': s_(ex='user:42')}, ['keyspace', 'table', 'partition_key']), obj({'added': b_()}),
   [{'set': {'state.denylisted_keys': "= state.denylisted_keys + [input.keyspace + '.' + input.table + ':' + input.partition_key]"}},
    {'set': {'ctx.opsDenylisted': "= input.keyspace + '.' + input.table + ':' + input.partition_key"}}, {'return': {'added': True}}])
sp('removeDenylistKey', 'StorageProxy.removeDenylistKey: false when the keyspace or table is unknown, else remove the key from the denylist.', rng(SP, 3150, 3161, 'public boolean removeDenylistKey'),
   obj({'keyspace': KS, 'table': s_(ex='users'), 'partition_key': s_(ex='user:42')}, ['keyspace', 'table', 'partition_key']), obj({'removed': b_()}), [{'return': {'removed': True}}])
sp('logBlockingReadRepairAttemptsForNSeconds', 'StorageProxy.logBlockingReadRepairAttemptsForNSeconds: log blocking read repairs until now + seconds.',
   rng(SP, 3180, 3183, 'public void logBlockingReadRepairAttemptsForNSeconds'), obj({'seconds': i_(ex=60)}), VOID, [{'return': {}}])

# ---------------------------------------------------------------- CacheServiceMBean
SAVE_PERIOD = {'KeyCache': 14400, 'RowCache': 0, 'CounterCache': 7200}  # key_cache_save_period 4h, row 0s, counter 7200s (yaml 538, 575, 603)
CT = {'KeyCache': 'KEY_CACHE', 'RowCache': 'ROW_CACHE', 'CounterCache': 'COUNTER_CACHE'}
for m, lo, hi, cache in [('invalidateKeyCache', 276, 279, 'KeyCache'), ('invalidateRowCache', 292, 295, 'RowCache'), ('invalidateCounterCache', 319, 322, 'CounterCache')]:
    cs(m, 'CacheService.%s: clear the %s.' % (m, cache), rng(CS, lo, hi, 'public void ' + m), VOID, VOID,
       [{'call': 'auto-saving-cache.clear', 'input': {'cache_type': CT[cache]}}, {'return': {}}])
for m, lo, hi, cache in [('setRowCacheCapacityInMB', 327, 333, 'RowCache'), ('setKeyCacheCapacityInMB', 336, 342, 'KeyCache'), ('setCounterCacheCapacityInMB', 344, 350, 'CounterCache')]:
    cs(m, 'CacheService.%s: refuse negative capacity, then resize the %s.' % (m, cache), rng(CS, lo, hi, 'public void ' + m), obj({'capacity_mb': i_(ex=100)}, ['capacity_mb']), VOID,
       [{'if': 'input.capacity_mb < 0', 'then': [{'title': 'Negative capacity refused', 'source': rng(CS, lo + 2, lo + 3, 'if (capacity < 0)'),
                                                 'fail': {'code': 'runtime-exception', 'message': 'capacity should not be negative.'}}]},
        {'call': 'auto-saving-cache.set-capacity', 'input': {'cache_type': CT[cache], 'capacity_bytes': '= input.capacity_mb * 1048576'}}, {'return': {}}], [RTE])
for m, lo, hi, cache, field, label in [('setRowCacheKeysToSave', 242, 248, 'RowCache', 'row_cache_keys_to_save', 'RowCacheKeysToSave'),
                                       ('setKeyCacheKeysToSave', 255, 261, 'KeyCache', 'key_cache_keys_to_save', 'KeyCacheKeysToSave'),
                                       ('setCounterCacheKeysToSave', 268, 274, 'CounterCache', 'counter_cache_keys_to_save', 'CounterCacheKeysToSave')]:
    cs(m, 'CacheService.%s: refuse negative counts, store the setting and reschedule saving of the %s.' % (m, cache), rng(CS, lo, hi, 'public void ' + m), obj({'count': i_(ex=100)}, ['count']), VOID,
       [{'if': 'input.count < 0', 'then': [{'title': 'Negative count refused', 'source': rng(CS, lo + 2, lo + 3, 'if (count < 0)'),
                                           'fail': {'code': 'runtime-exception', 'message': label + ' must be non-negative.'}}]},
        {'set': {'state.' + field: '= input.count'}},
        {'call': 'auto-saving-cache.schedule-saving', 'input': {'cache_type': CT[cache], 'save_period_s': SAVE_PERIOD[cache], 'keys_to_save': '= input.count'}}, {'return': {}}], [RTE])
cs('saveCaches', 'CacheService.saveCaches: submit writes of the key, row and counter caches and wait for all three.', rng(CS, 352, 363, 'public void saveCaches()'), VOID, VOID,
   [{'title': 'Submit the three cache writes, then wait for all of them', 'source': rng(CS, 352, 363, 'public void saveCaches()'),
     'parallel': ['KEY_CACHE', 'ROW_CACHE', 'COUNTER_CACHE'], 'as': 'c', 'join': {'need': 'all'},
     'steps': [{'call': 'auto-saving-cache.submit-write', 'input': {'cache_type': '= vars.c', 'keys_to_save': 2147483647}}]}, {'return': {}}])

# ---------------------------------------------------------------- ActiveRepairServiceMBean
jop('active-repair-service-mbean', 'ActiveRepairServiceMBean', 'failSession', 'ActiveRepairService.failSession: cancel a local incremental repair session (repair_admin cancel).',
    rng(J + 'service/ActiveRepairService.java', 297, 301, None), obj({'session': s_(ex='a3e1c2d0-9b1e-11ef-8f3a-0242ac120002'), 'force': b_(default=False)}, ['session']), VOID,
    [{'call': 'active-repair-service.fail-session', 'input': '= input'}, {'return': {}}])
jop('active-repair-service-mbean', 'ActiveRepairServiceMBean', 'cleanupPending', 'ActiveRepairService.cleanupPending: clean up finished-but-pending incremental repair data for the tables (repair_admin cleanup).',
    rng(J + 'service/ActiveRepairService.java', 411, 427, None), obj({'keyspace': KS, 'ranges': s_(default=''), 'force': b_(default=False)}), obj({'stats': a_(s_(), default=[])}),
    [{'call': 'active-repair-service.cleanup-pending', 'input': '= input', 'as': 'c'}, {'return': '= vars.c.value'}])

# ---------------------------------------------------------------- JMX-only StorageService operations (no nodetool command)
ss('takeTableSnapshot', 'StorageService.takeTableSnapshot (deprecated): takeMultipleTableSnapshot of keyspace.table; the snapshot itself is StorageService.takeSnapshot (repair-streaming).',
   [rng(SS, 4366, 4370, None), rng(SS, 4503, 4557, None)], obj({'keyspace': KS, 'table': s_(ex='users'), 'tag': s_(ex='before-upgrade')}, ['keyspace', 'table', 'tag']), VOID,
   [{'call': 'storage-service.take-snapshot', 'input': {'tag': '= input.tag', 'entities': ["= input.keyspace + '.' + input.table"], 'ttl_seconds': 0, 'skip_flush': False}}, {'return': {}}], [IOE])
ss('takeMultipleTableSnapshot', 'StorageService.takeMultipleTableSnapshot (deprecated): snapshot a list of keyspace.table entries under one tag.',
   [rng(SS, 4444, 4448, None), rng(SS, 4503, 4557, None)], obj({'tag': s_(ex='before-upgrade'), 'tables': a_(s_(), default=['ks1.users'])}, ['tag']), VOID,
   [{'call': 'storage-service.take-snapshot', 'input': {'tag': '= input.tag', 'entities': '= input.tables', 'ttl_seconds': 0, 'skip_flush': False}}, {'return': {}}], [IOE])
ss('cleanupSizeEstimates', 'StorageService.cleanupSizeEstimates: SystemKeyspace.clearAllEstimates (also run at startup).', rng(SS, 4719, 4722, None), VOID, VOID, [{'return': {}}])
ss('updateSnitch', 'StorageService.updateSnitch: apply dynamic snitch settings and optionally swap the endpoint snitch class (must keep the same DC/rack topology).',
   rng(SS, 6294, 6357, None), obj({'snitch_class': s_(default=''), 'dynamic': b_(default=True), 'update_interval_ms': i_(default=100), 'reset_interval_ms': i_(default=600000), 'badness_threshold': n_(default=1.0)}), VOID,
   [{'return': {}}], [err('class-not-found-exception')])
for m, lo, hi, val in [('bypassConcurrentValidatorsLimit', 1972, 1976, True), ('enforceConcurrentValidatorsLimit', 1978, 1982, False)]:
    ss(m, 'StorageService.%s: set DatabaseDescriptor.allowUnlimitedConcurrentValidations = %s.' % (m, str(val).lower()), rng(SS, lo, hi, None), VOID, VOID,
       [{'set': {'state.allow_unlimited_concurrent_validations': val}}, {'return': {}}])
ss('bulkLoad', 'StorageService.bulkLoad: stream the SSTables in a directory to their replicas (SSTableLoader) and wait; failures become RuntimeException.', rng(SS, 6432, 6442, None),
   obj({'directory': s_(ex='/tmp/load/ks1/users')}), VOID, [{'return': {}}], [RTE])
ss('bulkLoadAsync', 'StorageService.bulkLoadAsync: start the same bulk load and return the stream plan id.', rng(SS, 6444, 6447, None),
   obj({'directory': s_(ex='/tmp/load/ks1/users')}), obj({'plan_id': s_(ex='c1d2e3f0-9b1e-11ef-8f3a-0242ac120002')}), [{'return': {'plan_id': 'c1d2e3f0-9b1e-11ef-8f3a-0242ac120002'}}])
ss('rescheduleFailedDeletions', 'StorageService.rescheduleFailedDeletions: LifecycleTransaction retries SSTable deletions that failed.', rng(SS, 6489, 6492, None), VOID, VOID, [{'return': {}}])
ss('startSamplingPartitions', 'StorageService.startSamplingPartitions: validate duration/interval/capacity, then register a sampling schedule with SamplingManager.',
   rng(SS, 6569, 6592, None), obj({'duration_ms': i_(ex=10000), 'interval_ms': i_(default=-1), 'capacity': i_(default=256)}), obj({'registered': b_()}),
   [{'if': 'input.duration_ms <= 0', 'then': [{'title': 'Duration must be positive', 'source': at(SS, 6571, 'Preconditions.checkArgument(duration > 0'),
                                                'fail': {'code': 'illegal-argument-exception', 'message': "= 'Sampling duration ' + string(int(input.duration_ms)) + ' must be positive.'"}}]},
    {'return': {'registered': True}}], [IAE])
ss('stopSamplingPartitions', 'StorageService.stopSamplingPartitions: unregister a sampling schedule.', rng(SS, 6595, 6598, None),
   obj({'keyspace': s_(default=''), 'table': s_(default='')}), obj({'stopped': b_()}), [{'return': {'stopped': True}}])
ss('deliverHints', 'StorageService.deliverHints: removed behavior - always throws UnsupportedOperationException.', rng(SS, 3940, 3943, None), obj({'host': s_(ex='n2')}), VOID,
   [{'title': 'Unsupported since hints moved to HintsService', 'source': at(SS, 3942, 'throw new UnsupportedOperationException();'),
     'fail': {'code': 'unsupported-operation-exception', 'message': ''}}], [err('unsupported-operation-exception')])
ss('evictHungRepairs', 'StorageService.evictHungRepairs: Paxos.evictHungRepairs.', rng(SS, 7519, 7523, None), VOID, VOID, [{'return': {}}])
ss('clearPaxosRepairs', 'StorageService.clearPaxosRepairs: PaxosRepairState.clearRepairs.', rng(SS, 7525, 7529, None), VOID, VOID, [{'return': {}}])

# ---------------------------------------------------------------- getters used to read back the effect of a write (multi-step scenarios)
ss('getCompactionThroughputMbPerSec', 'StorageService.getCompactionThroughputMbPerSec: the current compaction_throughput in MiB/s.', rng(SS, 1919, 1922, 'public int getCompactionThroughputMbPerSec()'),
   VOID, obj({'value': i_()}), [{'return': {'value': '= state.compaction_throughput_mib_per_sec'}}])
ss('isIncrementalBackupsEnabled', 'StorageService.isIncrementalBackupsEnabled: the current incremental_backups flag.', rng(SS, 2044, 2047, 'public boolean isIncrementalBackupsEnabled()'),
   VOID, obj({'value': b_()}), [{'return': {'value': '= state.incremental_backups'}}])
ss('getTraceProbability', 'StorageService.getTraceProbability: the probability set by settraceprobability.', rng(SS, 6631, 6634, 'public double getTraceProbability()'),
   VOID, obj({'value': n_()}), [{'return': {'value': '= state.trace_probability'}}])
ss('isAuditLogEnabled', 'StorageService.isAuditLogEnabled: AuditLogManager.isEnabled (the installed logger is not NoOpAuditLogger).', rng(SS, 7027, 7030, 'public boolean isAuditLogEnabled()'),
   VOID, obj({'value': b_()}), [{'call': 'audit-log-manager.is-enabled', 'as': 'e'}, {'return': {'value': '= vars.e.value.enabled'}}])
ss('isFullQueryLogEnabled', 'StorageService.isFullQueryLogEnabled: FullQueryLogger.isEnabled (a BinLog is configured).', rng(SS, 7161, 7164, 'public boolean isFullQueryLogEnabled()'),
   VOID, obj({'value': b_()}), [{'call': 'full-query-logger.is-enabled', 'as': 'e'}, {'return': {'value': '= vars.e.value.enabled'}}])
sp('getHintedHandoffEnabled', 'StorageProxy.getHintedHandoffEnabled: DatabaseDescriptor.hintedHandoffEnabled.', rng(SP, 2372, 2375, 'public boolean getHintedHandoffEnabled()'),
   VOID, obj({'value': b_()}), [{'return': {'value': '= state.hinted_handoff_enabled'}}])
sp('isKeyDenylisted', 'StorageProxy.isKeyDenylisted: false for an unknown keyspace or table, else whether the partition key is on the denylist.', rng(SP, 3166, 3177, 'public boolean isKeyDenylisted'),
   obj({'keyspace': KS, 'table': s_(ex='users'), 'partition_key': s_(ex='user:42')}, ['keyspace', 'table', 'partition_key']), obj({'value': b_()}),
   [{'return': {'value': "= (input.keyspace + '.' + input.table + ':' + input.partition_key) in state.denylisted_keys"}}])

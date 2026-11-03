"""Core ops components: daemon startup, startup checks, config, tracing, audit, FQL, JMX dispatcher."""
from gen_base import *

# ---------------------------------------------------------------- schemas
schema('OpsNodetoolArgs', 'Parsed nodetool arguments, the fields an airline command object carries (NodeTool commands).', obj({
    'keyspace': s_(default='', desc='First positional argument when the command takes [<keyspace> <tables>...]; empty means not given.'),
    'tables': a_(s_(), default=[], desc='Remaining positional table names.'),
    'args': a_(s_(), default=[], desc='Other positional arguments, in order.'),
    'options': obj({}, default={}, description='Command options by long name (for example force, jobs, tag).'),
}))
schema('OpsNodetoolResult', 'What NodeTool.execute returns to main(): the process exit status and what it printed.', obj({
    'exit_status': i_(default=0, desc='0 success, 1 bad use (IllegalArgument/IllegalState or parse errors, or JMX connect failure), 2 any other error.'),
    'output': s_(default=''),
}, ['exit_status']))
schema('OpsStartupResult', 'Outcome of CassandraDaemon.activate.', obj({
    'setup_completed': b_(default=True),
    'native_transport_started': b_(default=True),
    'message': s_(default='Startup complete'),
}))
schema('OpsAuditLogEntry', 'An AuditLogEntry as built by AuditLogManager (audit/AuditLogEntry.java).', obj({
    'user': s_(ex='cassandra'),
    'keyspace': s_(ex='ks1'),
    'type': s_(ex='SELECT', desc='AuditLogEntryType name'),
    'category': s_(ex='QUERY', enum=['QUERY', 'DML', 'DDL', 'DCL', 'OTHER', 'AUTH', 'ERROR', 'PREPARE', 'TRANSACTION']),
    'operation': s_(ex='SELECT * FROM ks1.users WHERE id = 42'),
    'source': s_(ex='/10.0.0.9:51234'),
}, ['keyspace', 'category', 'user']))
schema('OpsTraceEvent', 'A trace session row or event written to system_traces (tracing/TraceKeyspace.java).', obj({
    'session_id': s_(ex='4c5f2a10-9b1e-11ef-8f3a-0242ac120002'),
    'request': s_(ex='Execute CQL3 query'),
    'activity': s_(ex='Parsing SELECT * FROM ks1.users WHERE id = 42'),
    'trace_type': s_(enum=['QUERY', 'REPAIR'], default='QUERY'),
    'ttl_seconds': i_(default=86400),
}))

# shared shapes reused by many ops
KS = s_(ex='ks1')
TABLES = a_(s_(), default=[])
OK_RESP = obj({'ok': b_(default=True)})
VOID = obj({})

# ---------------------------------------------------------------- boundary stub components
stub_comp('storage-service', 'StorageService', 'membership', 'membership', SS)
stub_comp('column-family-store', 'ColumnFamilyStore', 'write-path', 'write-path', J + 'db/ColumnFamilyStore.java')
stub_comp('keyspace', 'Keyspace', 'write-path', 'write-path', J + 'db/Keyspace.java')
stub_comp('compaction-manager', 'CompactionManager', 'read-path', 'read-path', J + 'db/compaction/CompactionManager.java')
stub_comp('commit-log', 'CommitLog', 'write-path', 'write-path', J + 'db/commitlog/CommitLog.java')
stub_comp('hints-service', 'HintsService', 'hints-batchlog', 'hints-batchlog', J + 'hints/HintsService.java')
stub_comp('batchlog-manager', 'BatchlogManager', 'hints-batchlog', 'hints-batchlog', J + 'batchlog/BatchlogManager.java')
stub_comp('gossiper', 'Gossiper', 'membership', 'membership', J + 'gms/Gossiper.java')
stub_comp('token-metadata', 'TokenMetadata', 'membership', 'membership', J + 'locator/TokenMetadata.java')
stub_comp('active-repair-service', 'ActiveRepairService', 'repair-streaming', 'repair-streaming', J + 'service/ActiveRepairService.java')
stub_comp('schema', 'Schema', 'schema-auth', 'schema-auth', J + 'schema/Schema.java')
stub_comp('native-transport-service', 'NativeTransportService', 'transport', 'transport', J + 'service/NativeTransportService.java')
stub_comp('query-processor', 'QueryProcessor', 'cql', 'cql', J + 'cql3/QueryProcessor.java')
stub_comp('storage-proxy', 'StorageProxy', 'coordination', 'coordination', SP)
stub_comp('auth-cache', 'AuthCache', 'schema-auth', 'schema-auth', J + 'auth/AuthCache.java')
stub_comp('cidr-groups-mapping-manager', 'CIDRGroupsMappingManager', 'schema-auth', 'schema-auth', J + 'auth/CIDRGroupsMappingManager.java')
stub_comp('cidr-permissions-manager', 'CIDRPermissionsManager', 'schema-auth', 'schema-auth', J + 'auth/CIDRPermissionsManager.java')
stub_comp('auto-saving-cache', 'AutoSavingCache', 'read-path', 'read-path', J + 'cache/AutoSavingCache.java')
stub_comp('messaging-service-mbean-impl', 'MessagingServiceMBeanImpl', 'messaging', 'membership', J + 'net/MessagingServiceMBeanImpl.java')
stub_comp('stream-manager-stream-rate-limiter', 'StreamManager.StreamRateLimiter', 'repair-streaming', 'repair-streaming', J + 'streaming/StreamManager.java', 'StreamRateLimiter')

# ---------------------------------------------------------------- boundary stub interfaces
ISE = err('illegal-state-exception', 'IllegalStateException')
IAE = err('illegal-argument-exception', 'IllegalArgumentException')
IOE = err('io-exception', 'IOException')
RTE = err('runtime-exception', 'RuntimeException')
UOE = err('unsupported-operation-exception', 'UnsupportedOperationException')

stub('commit-log', 'start', 'write-path', VOID, VOID, summary='CommitLog.start: start the segment manager and the sync service (write-path).')
stub('commit-log', 'recover-segments-on-disk', 'write-path', obj({'segments': a_(obj({}), default=[])}, ['segments']), obj({'replayed': i_(default=0)}), [IOE],
     summary='CommitLog.recoverSegmentsOnDisk: replay commit log segments found on disk (write-path).')
stub('storage-service', 'populate-token-metadata', 'membership', VOID, VOID, summary='StorageService.populateTokenMetadata: load saved tokens and peers into TokenMetadata (membership).')
stub('storage-service', 'init-server', 'membership', VOID, VOID, [err('config-error', 'ConfigurationException')],
     summary='StorageService.initServer: start gossip, join the ring or bootstrap (membership).')
stub('storage-service', 'set-rpc-ready', 'membership', obj({'value': b_(default=True)}), VOID, summary='StorageService.setRpcReady: announce RPC_READY in gossip (membership).')
stub('storage-service', 'check-service-allowed-to-start', 'membership', obj({'service': s_(ex='hinted handoff')}), VOID, [ISE],
     summary='StorageService.checkServiceAllowedToStart: refuse when draining, drained, or not NORMAL while joining the ring (membership).')
stub('storage-service', 'drain', 'membership', VOID, VOID, [IOE, err('interrupted-exception'), err('execution-exception')],
     summary='StorageService.drain: stop transports, gossip, flush and shut down executors (membership).')
stub('storage-service', 'decommission', 'membership', obj({'force': b_(default=False)}), VOID, [UOE, ISE, err('interrupted-exception')],
     summary='StorageService.decommission: stream data away and leave the ring (membership).')
stub('storage-service', 'is-decommissioning', 'membership', VOID, obj({'decommissioning': b_(default=False)}),
     summary='StorageService.isDecommissioning (membership).')
stub('storage-service', 'get-bootstrap-state', 'membership', VOID, obj({'state': s_(enum=['NEEDS_BOOTSTRAP', 'COMPLETED', 'IN_PROGRESS', 'DECOMMISSIONED'], default='COMPLETED')}),
     summary='StorageService.getBootstrapState: SystemKeyspace bootstrap state (membership).')
stub('storage-service', 'get-operation-mode', 'membership', VOID, obj({'mode': s_(enum=['STARTING', 'NORMAL', 'JOINING', 'LEAVING', 'DECOMMISSIONED', 'MOVING', 'DRAINING', 'DRAINED'], default='NORMAL')}),
     summary='StorageService operation mode (membership).')
stub('storage-service', 'start-gossiping', 'membership', VOID, VOID, [ISE], summary='StorageService.startGossiping (membership).')
stub('storage-service', 'stop-gossiping', 'membership', VOID, VOID, [ISE], summary='StorageService.stopGossiping (membership).')
stub('storage-service', 'move', 'membership', obj({'new_token': s_(ex='-3074457345618258603')}), VOID, [IOE], summary='StorageService.move (membership).')
stub('storage-service', 'remove-node', 'membership', obj({'host_id': s_(ex='6d194555-f6eb-41d0-c000-000000000002')}), VOID, [UOE], summary='StorageService.removeNode (membership).')
stub('storage-service', 'force-remove-completion', 'membership', VOID, VOID, summary='StorageService.forceRemoveCompletion (membership).')
stub('storage-service', 'join-ring', 'membership', VOID, VOID, [IOE], summary='StorageService.joinRing (membership).')
stub('storage-service', 'rebuild', 'membership', obj({'source_dc': s_(default=''), 'keyspace': s_(default=''), 'tokens': s_(default=''), 'specific_sources': s_(default=''), 'exclude_local_dc': b_(default=False)}), VOID, [IAE, ISE],
     summary='StorageService.rebuild: stream ranges from other replicas (membership).')
stub('storage-service', 'resume-bootstrap', 'membership', VOID, obj({'resumed': b_(default=True)}), summary='StorageService.resumeBootstrap (membership).')
stub('storage-service', 'repair-async', 'repair-streaming', obj({'keyspace': KS, 'options': obj({}, default={})}, ['keyspace']),
     obj({'cmd': i_(default=1, desc='repair command number; 0 when there is nothing to repair (RF 1)')}), [IAE],
     summary='StorageService.repairAsync: parse RepairOption and submit a RepairCoordinator; returns the command number (repair-streaming).')
stub('token-metadata', 'get-pending-ranges', 'membership', obj({'keyspace': KS, 'endpoint': s_(ex='n1')}),
     obj({'ranges': a_(s_(), default=[])}), summary='TokenMetadata.getPendingRanges for this node (membership).')
stub('active-repair-service', 'get-repair-status', 'repair-streaming', obj({'cmd': i_(default=1)}),
     obj({'status': s_(enum=['IN_PROGRESS', 'COMPLETED', 'FAILED'], default='COMPLETED'), 'messages': a_(s_(), default=['Repair command #1 finished in 2 seconds'])}),
     summary='ActiveRepairService.getRepairStatus: parent repair status and messages for a command (repair-streaming).')
stub('active-repair-service', 'start', 'repair-streaming', VOID, VOID, summary='ActiveRepairService.start (repair-streaming).')
stub('active-repair-service', 'terminate-sessions', 'repair-streaming', VOID, VOID, summary='ActiveRepairService.terminateSessions (repair-streaming).')
stub('active-repair-service', 'fail-session', 'repair-streaming', obj({'session': s_(ex='a3e1c2d0-9b1e-11ef-8f3a-0242ac120002'), 'force': b_(default=False)}), VOID,
     summary='ActiveRepairService.failSession: cancel a pending incremental repair session (repair-streaming).')
stub('active-repair-service', 'cleanup-pending', 'repair-streaming', obj({'keyspace': KS, 'ranges': s_(default=''), 'force': b_(default=False)}), obj({'stats': a_(s_(), default=[])}),
     summary='ActiveRepairService.cleanupPending (repair-streaming).')
stub('column-family-store', 'force-blocking-flush', 'write-path', obj({'keyspace': KS, 'table': s_(ex='users'), 'replica': s_(default='n1'), 'reason': s_(default='USER_FORCED')}, ['keyspace', 'table']),
     obj({'flushed': b_(default=True), 'sstables': i_(default=1)}), summary='ColumnFamilyStore.forceBlockingFlush: forceFlush and wait (write-path).')
stub('storage-service', 'take-snapshot', 'repair-streaming', obj({'tag': s_(ex='before-upgrade'), 'entities': a_(s_(), default=[]), 'ttl_seconds': i_(default=0), 'skip_flush': b_(default=False)}),
     obj({'snapshots': i_(default=1)}), [err('illegal-argument-exception'), err('io-exception')], kind='jmx',
     summary='StorageService.takeSnapshot(tag, options, entities): validate and snapshot keyspaces or keyspace.table entries (repair-streaming).')
stub('storage-service', 'clear-snapshot', 'repair-streaming', obj({'tag': s_(default=''), 'keyspaces': a_(s_(), default=[]), 'older_than_seconds': i_(default=0)}),
     obj({'cleared': i_(default=1)}), kind='jmx', summary='StorageService.clearSnapshot(options, tag, keyspaces) (repair-streaming).')
for nm, summ in [('perform-cleanup', 'performCleanup: rewrite SSTables dropping ranges this node no longer owns'),
                 ('perform-scrub', 'performScrub'), ('perform-verify', 'performVerify'),
                 ('perform-sstable-rewrite', 'performSSTableRewrite (upgradesstables / recompress)'),
                 ('perform-garbage-collection', 'performGarbageCollection'), ('relocate-sstables', 'relocateSSTables')]:
    stub('compaction-manager', nm, 'read-path', obj({'replica': s_(default='n1'), 'keyspace': KS, 'table': s_(ex='users'), 'jobs': i_(default=2)}, ['keyspace', 'table']),
         obj({'status': s_(enum=['SUCCESSFUL', 'ABORTED', 'UNABLE_TO_CANCEL'], default='SUCCESSFUL'), 'status_code': i_(default=0)}),
         summary='CompactionManager.%s; returns AllSSTableOpStatus (read-path).' % summ)
stub('compaction-manager', 'perform-maximal', 'read-path', obj({'replica': s_(default='n1'), 'keyspace': KS, 'table': s_(ex='users'), 'split_output': b_(default=False)}), VOID,
     summary='CompactionManager.performMaximal: major compaction of one table (read-path).')
stub('compaction-manager', 'force-compaction-for-token-range', 'read-path', obj({'replica': s_(default='n1'), 'keyspace': KS, 'table': s_(ex='users'), 'ranges': a_(s_(), default=[])}), VOID,
     summary='CompactionManager.forceCompactionForTokenRange (read-path).')
stub('compaction-manager', 'force-user-defined-compaction', 'read-path', obj({'replica': s_(default='n1'), 'data_files': s_(ex='/var/lib/cassandra/data/ks1/users-1b255f4d/nb-1-big-Data.db')}), VOID,
     summary='CompactionManager.forceUserDefinedCompaction (read-path).')
stub('compaction-manager', 'stop-compaction', 'read-path', obj({'type': s_(ex='COMPACTION')}), VOID, [IAE], summary='CompactionManager.stopCompaction: stop active operations of a type (read-path).')
stub('compaction-manager', 'stop-compaction-by-id', 'read-path', obj({'compaction_id': s_(ex='b7a4c3e0-9b1e-11ef-8f3a-0242ac120002')}), VOID, summary='CompactionManager.stopCompactionById (read-path).')
stub('compaction-manager', 'set-rate-in-bytes', 'read-path', obj({'bytes_per_second': n_(default=67108864.0)}), VOID, summary='CompactionManager.setRateInBytes: reset the compaction RateLimiter (read-path).')
stub('compaction-manager', 'set-concurrent-compactors', 'read-path', obj({'value': i_(default=2)}), VOID, summary='CompactionManager.setConcurrentCompactors: resize the compaction executor (read-path).')
stub('compaction-manager', 'set-concurrent-view-builders', 'read-path', obj({'value': i_(default=1)}), VOID, summary='CompactionManager.setConcurrentViewBuilders (read-path).')
stub('compaction-manager', 'submit-background', 'read-path', obj({'keyspace': KS, 'table': s_(ex='users')}), VOID, summary='CompactionManager.submitBackground (read-path).')
stub('hints-service', 'pause-dispatch', 'hints-batchlog', VOID, VOID, summary='HintsService.pauseDispatch: set isDispatchPaused (hints-batchlog).')
stub('hints-service', 'resume-dispatch', 'hints-batchlog', VOID, VOID, summary='HintsService.resumeDispatch (hints-batchlog).')
stub('hints-service', 'delete-all-hints', 'hints-batchlog', obj({'holder': s_(default='n1')}), VOID, summary='HintsService.deleteAllHints: delete every hints file (hints-batchlog).')
stub('hints-service', 'delete-all-hints-for-endpoint', 'hints-batchlog', obj({'address': s_(ex='n2'), 'holder': s_(default='n1')}, ['address']), VOID, [IAE],
     summary='HintsService.deleteAllHintsForEndpoint: refuses an unknown address (hints-batchlog).')
stub('batchlog-manager', 'force-batchlog-replay', 'hints-batchlog', obj({'replica': s_(default='n1')}), VOID, summary='BatchlogManager.forceBatchlogReplay: replay and wait (hints-batchlog).')
stub('batchlog-manager', 'set-rate', 'hints-batchlog', obj({'throttle_kib': i_(default=1024)}), VOID, summary='BatchlogManager.setRate: replay throttle (hints-batchlog).')
stub('gossiper', 'assassinate-endpoint', 'membership', obj({'address': s_(ex='n3')}), VOID, [err('unknown-host-exception')], summary='Gossiper.assassinateEndpoint (membership).')
stub('gossiper', 'reload-seeds', 'membership', VOID, obj({'seeds': a_(s_(), default=['n1'])}), summary='Gossiper.reloadSeeds (membership).')
stub('gossiper', 'wait-to-settle', 'membership', VOID, VOID, summary='Gossiper.waitToSettle: wait for gossip to stabilise before serving (membership).')
stub('schema', 'load-from-disk', 'schema-auth', VOID, VOID, summary='Schema.loadFromDisk (schema-auth).')
stub('schema', 'reset-local-schema', 'schema-auth', VOID, VOID, [IOE], summary='Schema.resetLocalSchema: drop local schema and pull it from peers (schema-auth).')
stub('schema', 'reload-schema-and-announce-version', 'schema-auth', VOID, VOID, summary='Schema.reloadSchemaAndAnnounceVersion (schema-auth).')
stub('native-transport-service', 'start', 'transport', VOID, VOID, summary='NativeTransportService.start: bind the CQL server (port 9042) (transport).')
stub('native-transport-service', 'stop', 'transport', obj({'force': b_(default=False)}), VOID, summary='NativeTransportService.stop (transport).')
stub('query-processor', 'preload-prepared-statements', 'cql', VOID, obj({'count': i_(default=0)}), summary='QueryProcessor.preloadPreparedStatements (cql).')
stub('query-processor', 'clear-prepared-statements', 'cql', obj({'memory_only': b_(default=False)}), VOID, summary='QueryProcessor.clearPreparedStatements (cql).')
stub('storage-proxy', 'mutate', 'coordination', obj({'mutations': a_(obj({'keyspace': s_(), 'table': s_(), 'partition_key': s_(), 'token': i_(), 'timestamp': i_(), 'columns': obj({})})), 'consistency': s_(ex='ANY')}, ['mutations', 'consistency']), VOID,
     [err('overloaded', status=4097), err('unavailable', status=4096), err('write-timeout', status=4352)],
     summary='StorageProxy.mutate: coordinate a write at a consistency level (coordination).')
stub('storage-proxy', 'truncate-blocking', 'coordination', obj({'keyspace': KS, 'table': s_(ex='users')}), VOID,
     [err('unavailable', status=4096), err('truncate-error', status=4099), err('timeout-exception')],
     summary='StorageProxy.truncateBlocking: send TRUNCATE to all replicas and wait (coordination).')
stub('auth-cache', 'invalidate', 'schema-auth', obj({'cache': s_(default='RolesCache'), 'key': s_(default='')}), VOID,
     summary='AuthCache.invalidate(): rebuild the whole cache, or invalidate(K) for one key (schema-auth).')
stub('cidr-groups-mapping-manager', 'update-cidr-group', 'schema-auth', obj({'group': s_(ex='office'), 'cidrs': a_(s_(), default=['10.0.0.0/24'])}), VOID, summary='CIDRGroupsMappingManager.updateCidrGroup (schema-auth).')
stub('cidr-groups-mapping-manager', 'drop-cidr-group', 'schema-auth', obj({'group': s_(ex='office')}), VOID, [RTE], summary='CIDRGroupsMappingManager.dropCidrGroup (schema-auth).')
stub('cidr-groups-mapping-manager', 'load-cidr-groups-cache', 'schema-auth', VOID, VOID, summary='CIDRGroupsMappingManager.loadCidrGroupsCache (schema-auth).')
stub('cidr-permissions-manager', 'invalidate-cidr-permissions-cache', 'schema-auth', obj({'role': s_(default='')}), obj({'invalidated': b_(default=True)}), summary='CIDRPermissionsManager.invalidateCidrPermissionsCache (schema-auth).')
stub('auto-saving-cache', 'load-saved', 'read-path', obj({'cache_type': s_(enum=['KEY_CACHE', 'ROW_CACHE', 'COUNTER_CACHE'], ex='KEY_CACHE')}, ['cache_type']), obj({'loaded': i_(default=0)}), summary='AutoSavingCache.loadSaved (run by loadSavedAsync): load a saved cache file (read-path).')
stub('auto-saving-cache', 'clear', 'read-path', obj({'cache_type': s_(enum=['KEY_CACHE', 'ROW_CACHE', 'COUNTER_CACHE'], ex='KEY_CACHE')}, ['cache_type']), VOID, summary='AutoSavingCache.clear (read-path).')
stub('auto-saving-cache', 'set-capacity', 'read-path', obj({'cache_type': s_(enum=['KEY_CACHE', 'ROW_CACHE', 'COUNTER_CACHE'], ex='KEY_CACHE'), 'capacity_bytes': i_(default=104857600)}, ['cache_type']), VOID, summary='Cache setCapacity (read-path).')
stub('auto-saving-cache', 'schedule-saving', 'read-path', obj({'cache_type': s_(enum=['KEY_CACHE', 'ROW_CACHE', 'COUNTER_CACHE'], ex='KEY_CACHE'), 'save_period_s': i_(ex=14400), 'keys_to_save': i_(default=100)}, ['cache_type']), VOID, summary='AutoSavingCache.scheduleSaving (read-path).')
stub('auto-saving-cache', 'submit-write', 'read-path', obj({'cache_type': s_(enum=['KEY_CACHE', 'ROW_CACHE', 'COUNTER_CACHE'], ex='KEY_CACHE'), 'keys_to_save': i_(default=2147483647)}, ['cache_type']), VOID, summary='AutoSavingCache.submitWrite: save the cache to saved_caches (read-path).')
stub('messaging-service-mbean-impl', 'reload-ssl-certificates', 'membership', VOID, VOID, [IOE], summary='MessagingServiceMBeanImpl.reloadSslCertificates (membership).')
for nm in ['update-throughput', 'update-inter-dc-throughput', 'update-entire-sstable-throughput', 'update-entire-sstable-inter-dc-throughput']:
    stub('stream-manager-stream-rate-limiter', nm, 'repair-streaming', VOID, VOID, summary='StreamManager.StreamRateLimiter.%s: re-read the outbound stream throughput (repair-streaming).' % nm)

# ---------------------------------------------------------------- config entities (deployed value and code default)
config('start-native-transport', 'boolean', True, True, 'start_native_transport: CassandraDaemon starts the CQL server at startup.', [at(YAML, 1020, 'start_native_transport: true'), at(CFG, 278, 'start_native_transport')])
config('autocompaction-on-startup-enabled', 'boolean', True, True, 'autocompaction_on_startup_enabled (not in cassandra.yaml): re-enable auto-compaction once gossip settles.', [at(CFG, 833, 'autocompaction_on_startup_enabled')])
config('auth-cache-warming-enabled', 'boolean', False, False, 'auth_cache_warming_enabled: prewarm auth caches at the end of setup.', [at(YAML, 1965, 'auth_cache_warming_enabled'), at(CFG, 749, 'auth_cache_warming_enabled')])
config('audit-logging-enabled', 'boolean', False, False, 'audit_logging_options.enabled: AuditLogManager installs BinAuditLogger and registers listeners only when true.', [at(YAML, 1894, 'enabled: false'), at(J + 'audit/AuditLogOptions.java', 39, 'public volatile boolean enabled = false;')])
config('audit-logging-allow-nodetool-archive-command', 'boolean', False, False, 'audit_logging_options.allow_nodetool_archive_command (commented out in cassandra.yaml).', [at(YAML, 1893, 'audit_logging_options:'), at(J + 'utils/binlog/BinLogOptions.java', 32, 'allow_nodetool_archive_command')])
config('full-query-logging-log-dir', 'string', '', '', 'full_query_logging_options.log_dir: commented out, so "" and enablefullquerylog needs --path.', [at(YAML, 1917, 'full_query_logging_options'), at(J + 'fql/FullQueryLoggerOptions.java', 27, 'public String log_dir')])
config('full-query-logging-allow-nodetool-archive-command', 'boolean', False, False, 'full_query_logging_options.allow_nodetool_archive_command (commented out).', [at(YAML, 1926, 'allow_nodetool_archive_command'), at(J + 'utils/binlog/BinLogOptions.java', 32, 'allow_nodetool_archive_command')])
config('trace-type-query-ttl-s', 'integer', 86400, 86400, 'trace_type_query_ttl 1d: TTL of query trace rows.', [at(YAML, 1752, 'trace_type_query_ttl'), at(CFG, 552, 'trace_type_query_ttl')])
config('trace-type-repair-ttl-s', 'integer', 604800, 604800, 'trace_type_repair_ttl 7d: TTL of repair trace rows.', [at(YAML, 1754, 'trace_type_repair_ttl'), at(CFG, 554, 'trace_type_repair_ttl')])
config('startup-checks-check-dc-enabled', 'boolean', True, True, 'startup_checks.check_dc.enabled: startup_checks is commented out, so the StartupCheckType default (enabled) applies.', [at(YAML, 2277, 'check_dc'), at(SC, 110, 'check_dc')])
config('startup-checks-check-rack-enabled', 'boolean', True, True, 'startup_checks.check_rack.enabled: enabled by default.', [at(YAML, 2280, 'check_rack'), at(SC, 111, 'check_rack')])
config('nodetool-jmx-notification-poll-interval-s', 'integer', 300, 300, 'cassandra.nodetool.jmx_notification_poll_interval_seconds: RepairRunner re-queries the parent repair status after each interval without a notification.', [at(J + 'config/CassandraRelevantProperties.java', 376, 'NODETOOL_JMX_NOTIFICATION_POLL_INTERVAL_SECONDS')])
config('size-recorder-interval-s', 'integer', 300, 300, 'cassandra.size_recorder_interval: SizeEstimatesRecorder period scheduled by CassandraDaemon.setup (0 disables).', [at(J + 'config/CassandraRelevantProperties.java', 495, 'SIZE_RECORDER_INTERVAL')])

# ---------------------------------------------------------------- config
DD = J + 'config/DatabaseDescriptor.java'
comp('database-descriptor', 'DatabaseDescriptor', 'node-ops',
     'Loads cassandra.yaml into Config and applies it; the effective runtime configuration other code reads and JMX setters change.',
     [class_line(DD, 'DatabaseDescriptor'), class_line(CFG, 'Config')],
     state={'initial': {
         'config_valid': True,
     }},
     description='Effective values used by the ops flows (cassandra.yaml first, Config.java defaults where the yaml is silent): '
                 'start_native_transport true (yaml 1020), audit_logging_options.enabled false (yaml 1894), '
                 'full_query_logging_options commented out so log_dir is "" (FullQueryLoggerOptions.java:27), '
                 'auth_cache_warming_enabled false (Config.java:749), autocompaction_on_startup_enabled true (Config.java:833 property default).')
iface('database-descriptor', 'daemon-initialization', 'DatabaseDescriptor.daemonInitialization: load cassandra.yaml through YamlConfigurationLoader, applyAll, then AuthConfig.applyAuth.',
      [rng(DD, 245, 265, 'public static void daemonInitialization()'), rng(DD, 391, 400, 'public static Config loadConfig()')],
      VOID, VOID, errors=[err('configuration-exception', 'ConfigurationException: invalid cassandra.yaml')],
      behavior=[
          {'if': '!state.config_valid', 'then': [
              note('Invalid configuration', rng(DD, 250, 264, 'daemonInitialization(Supplier<Config> config)'),
                   'loadConfig/applyAll reject the yaml with a ConfigurationException; activate() catches it.',
                   fail={'code': 'configuration-exception', 'message': 'Invalid yaml: cassandra.yaml'})]},
          {'title': 'Config loaded and applied', 'source': rng(DD, 262, 264, 'setConfig(config.get());'), 'return': {}},
      ])

# ---------------------------------------------------------------- startup checks
comp('startup-checks', 'StartupChecks', 'node-ops',
     'Pre-flight checks run by CassandraDaemon.setup before any local state is mutated; a failing check halts startup with its StartupException return code.',
     [class_line(SC, 'StartupChecks'), rng(SC, 138, 155, 'private final List<StartupCheck> DEFAULT_TESTS')],
     state={'initial': {
         'native_library_ok': True,
         'data_dirs': {'/var/lib/cassandra/data': {'exists': True, 'can_create': True, 'writable': True},
                       '/var/lib/cassandra/commitlog': {'exists': True, 'can_create': True, 'writable': True},
                       '/var/lib/cassandra/saved_caches': {'exists': True, 'can_create': True, 'writable': True},
                       '/var/lib/cassandra/hints': {'exists': True, 'can_create': True, 'writable': True}},
         'sstables_need_upgrade': False,
         'stored_dc': 'datacenter1', 'current_dc': 'datacenter1',
         'stored_rack': 'rack1', 'current_rack': 'rack1',
         'legacy_auth_tables_present': False,
     }},
     description='startup_checks is commented out in cassandra.yaml (2270), so check_dc and check_rack are enabled and check_filesystem_ownership and check_data_resurrection are disabled (StartupCheckType defaults, StartupChecks.java:106-126).')
iface('startup-checks', 'verify', 'StartupChecks.verify: run every pre-flight check in order, then each post-action; the first StartupException aborts startup.',
      [rng(SC, 176, 193, 'public void verify(StartupChecksOptions options)')],
      VOID, VOID,
      errors=[err('startup-exception', 'StartupException; data.exit_code is its returnCode (1 machine state, 3 disk state, 100 config)')],
      behavior=[
          note('checkNativeLibraryInitialization', rng(SC, 409, 420, 'checkNativeLibraryInitialization'),
               'Fails with ERR_WRONG_MACHINE_STATE (1) when JNA could not initialise.', **{'if': '!state.native_library_ok', 'then': [
                   {'fail': {'code': 'startup-exception', 'message': 'The native library could not be initialized properly. ', 'data': {'exit_code': 1}}}]}),
          note('checkDataDirs: data, commitlog, saved_caches and hints directories', rng(SC, 561, 594, 'checkDataDirs'),
               'A missing directory is created; failing that, or lacking full permissions, is ERR_WRONG_DISK_STATE (3).',
               foreach='= state.data_dirs', **{'as': 'dir', 'index': 'path', 'steps': [
                   {'if': '!vars.dir.exists && !vars.dir.can_create', 'then': [
                       {'fail': {'code': 'startup-exception', 'message': "= 'Has no permission to create directory ' + vars.path", 'data': {'exit_code': 3}}}]},
                   {'if': '!vars.dir.writable', 'then': [
                       {'fail': {'code': 'startup-exception', 'message': "= 'Insufficient permissions on directory ' + vars.path", 'data': {'exit_code': 3}}}]}]}),
          note('checkSSTablesFormat', rng(SC, 596, 709, 'checkSSTablesFormat'),
               'SSTables in a format this version cannot read stop startup with ERR_WRONG_DISK_STATE (3).',
               **{'if': 'state.sstables_need_upgrade', 'then': [
                   {'fail': {'code': 'startup-exception', 'message': 'Detected unreadable sstables, please check NEWS.txt and ensure that you have upgraded through all required intermediate versions, running upgradesstables', 'data': {'exit_code': 3}}}]}),
          note('checkDatacenter', rng(SC, 736, 771, 'checkDatacenter'),
               'The snitch DC must match the DC saved in system.local, unless check_dc is disabled; mismatch is ERR_WRONG_CONFIG (100).',
               **{'if': "config['startup-checks-check-dc-enabled'] && state.stored_dc != '' && state.stored_dc != state.current_dc", 'then': [
                   {'fail': {'code': 'startup-exception', 'data': {'exit_code': 100},
                             'message': "= \"Cannot start node if snitch's data center (\" + state.current_dc + ') differs from previous data center (' + state.stored_dc + ').'"}}]}),
          note('checkRack', rng(SC, 773, 808, 'checkRack'),
               'Same rule for the rack; mismatch is ERR_WRONG_CONFIG (100).',
               **{'if': "config['startup-checks-check-rack-enabled'] && state.stored_rack != '' && state.stored_rack != state.current_rack", 'then': [
                   {'fail': {'code': 'startup-exception', 'data': {'exit_code': 100},
                             'message': "= \"Cannot start node if snitch's rack (\" + state.current_rack + ') differs from previous rack (' + state.stored_rack + ').'"}}]}),
          note('checkLegacyAuthTables', rng(SC, 810, 822, 'checkLegacyAuthTables'),
               'Pre-2.2 auth tables still present stop startup with ERR_WRONG_CONFIG (100).',
               **{'if': 'state.legacy_auth_tables_present', 'then': [
                   {'fail': {'code': 'startup-exception', 'message': 'Legacy auth tables credentials, users, permissions in keyspace system_auth still exist and have not been properly migrated.', 'data': {'exit_code': 100}}}]}),
          {'title': 'All checks passed; run post-actions (failures only logged)', 'source': rng(SC, 181, 192, 'test.postAction(options);'), 'return': {}},
      ])

# ---------------------------------------------------------------- virtual tables
VKR = J + 'db/virtual/VirtualKeyspaceRegistry.java'
comp('virtual-keyspace-registry', 'VirtualKeyspaceRegistry', 'node-ops',
     'Registry of virtual keyspaces (system_virtual_schema, system_views) whose tables are computed on read.',
     [class_line(VKR, 'VirtualKeyspaceRegistry'), class_line(J + 'db/virtual/SystemViewsKeyspace.java', 'SystemViewsKeyspace')],
     state={'initial': {'keyspaces': []}})
iface('virtual-keyspace-registry', 'register', 'VirtualKeyspaceRegistry.register: add a virtual keyspace (called by CassandraDaemon.setupVirtualKeyspaces).',
      [rng(VKR, 41, 48, 'public void register(VirtualKeyspace keyspace)'), rng(CD, 534, 544, 'public void setupVirtualKeyspaces()')], obj({'keyspace': s_(ex='system_views')}), VOID,
      behavior=[{'set': {'state.keyspaces': '= state.keyspaces + [input.keyspace]'}}, {'return': {}}])

# ---------------------------------------------------------------- audit log
ALM = J + 'audit/AuditLogManager.java'
ALF = J + 'audit/AuditLogFilter.java'
comp('audit-log-manager', 'AuditLogManager', 'node-ops',
     'Listens to query and auth events and writes AuditLogEntries through the configured IAuditLogger, after the include/exclude filter.',
     [class_line(ALM, 'AuditLogManager'), rng(ALM, 71, 87, 'private AuditLogManager()')],
     state={'initial': {'enabled': False, 'listener_registered': False, 'logger': 'NoOpAuditLogger',
                        'included_keyspaces': [], 'excluded_keyspaces': ['system', 'system_schema', 'system_virtual_schema'],
                        'included_categories': [], 'excluded_categories': [], 'included_users': [], 'excluded_users': [],
                        'logged': 0}},
     description='Deployed: audit_logging_options.enabled false with logger BinAuditLogger (cassandra.yaml 1893-1896), so the constructor installs NoOpAuditLogger and initialize() does not register listeners. '
                 'excluded_keyspaces defaults to system, system_schema, system_virtual_schema (AuditLogOptions).')
iface('audit-log-manager', 'initialize', 'AuditLogManager.initialize: register as a query/auth listener only when audit logging is enabled in the yaml, and register the MBean.',
      [rng(ALM, 89, 96, 'public void initialize()')], VOID, VOID,
      behavior=[{'title': 'audit_logging_options.enabled decides the logger and the listener registration', 'source': rng(ALM, 73, 84, 'auditLogOptions = DatabaseDescriptor.getAuditLoggingOptions();'),
                 'if': "config['audit-logging-enabled']", 'then': [{'set': {'state.enabled': True, 'state.listener_registered': True, 'state.logger': 'BinAuditLogger'}}]},
                {'return': {}}])
comp('audit-log-filter', 'AuditLogFilter', 'audit-log-manager', 'Include/exclude sets for keyspaces, categories and users; exclusion wins over inclusion.',
     [class_line(ALF, 'AuditLogFilter')])
iface('audit-log-filter', 'is-filtered', 'AuditLogFilter.isFiltered: an entry is dropped when its keyspace, category or user is excluded, or not in a non-empty include set.',
      [rng(ALF, 106, 131, 'boolean isFiltered(AuditLogEntry auditLogEntry)')],
      obj({'entry': {'$ref': 'OpsAuditLogEntry'}, 'filter': obj({})}, ['entry', 'filter']), obj({'filtered': b_()}),
      behavior=[
          {'set': {'vars.f': '= input.filter', 'vars.e': '= input.entry'}},
          {'set': {'vars.ks': '= (size(vars.f.excluded_keyspaces) > 0 && vars.e.keyspace in vars.f.excluded_keyspaces) || !(size(vars.f.included_keyspaces) == 0 || vars.e.keyspace in vars.f.included_keyspaces)',
                   'vars.cat': '= (size(vars.f.excluded_categories) > 0 && vars.e.category in vars.f.excluded_categories) || !(size(vars.f.included_categories) == 0 || vars.e.category in vars.f.included_categories)',
                   'vars.usr': '= (size(vars.f.excluded_users) > 0 && vars.e.user in vars.f.excluded_users) || !(size(vars.f.included_users) == 0 || vars.e.user in vars.f.included_users)'}},
          {'title': 'Exclude set first, then a non-empty include set', 'source': rng(ALF, 125, 131, 'static boolean isFiltered(String input'),
           'return': {'filtered': '= vars.ks || vars.cat || vars.usr'}},
      ])
BAL = J + 'audit/BinAuditLogger.java'
comp('bin-audit-logger', 'BinAuditLogger', 'audit-log-manager', 'Audit logger that appends entries to a Chronicle Queue binary log (BinLog).',
     [class_line(BAL, 'BinAuditLogger')], state={'initial': {'entries': 0}})
iface('bin-audit-logger', 'log', 'BinAuditLogger.log: append the entry to the binary log queue (blocking per audit_logging_options.block, default true).',
      [rng(BAL, 87, 95, 'public void log(AuditLogEntry auditLogEntry)')], {'$ref': 'OpsAuditLogEntry'}, VOID,
      behavior=[{'set': {'state.entries': '= state.entries + 1'}}, {'return': {}}])
iface('audit-log-manager', 'query-success', 'AuditLogManager.querySuccess: build an AuditLogEntry for a successful CQL query and log it unless filtered.',
      [rng(ALM, 242, 252, 'public void querySuccess'), rng(ALM, 136, 142, 'private void log(AuditLogEntry logEntry)')],
      {'$ref': 'OpsAuditLogEntry'}, obj({'logged': b_()}),
      behavior=[
          {'if': '!state.listener_registered', 'then': [
              note('Not registered as a QueryEvents listener', rng(ALM, 89, 93, 'public void initialize()'),
                   'With audit logging disabled the manager never registers, so no entry is produced (the installed logger is NoOpAuditLogger).',
                   **{'return': {'logged': False}})]},
          {'call': 'audit-log-filter.is-filtered', 'as': 'flt', 'input': {'entry': '= input', 'filter': {
              'included_keyspaces': '= state.included_keyspaces', 'excluded_keyspaces': '= state.excluded_keyspaces',
              'included_categories': '= state.included_categories', 'excluded_categories': '= state.excluded_categories',
              'included_users': '= state.included_users', 'excluded_users': '= state.excluded_users'}}},
          {'if': 'vars.flt.value.filtered', 'then': [{'set': {'ctx.opsAuditFiltered': True}}, {'return': {'logged': False}}]},
          {'title': 'Hand the entry to the configured logger', 'source': rng(ALM, 138, 141, 'if (!filter.isFiltered(logEntry))'),
           'call': 'bin-audit-logger.log', 'input': '= input'},
          {'set': {'state.logged': '= state.logged + 1', 'ctx.opsAuditFiltered': False}},
          {'return': {'logged': True}},
      ])
iface('audit-log-manager', 'enable', 'AuditLogManager.enable: swap in the configured logger (unless the class is unchanged), always reload the filters, register as listener.',
      [rng(ALM, 187, 218, 'public synchronized void enable(AuditLogOptions auditLogOptions)')],
      obj({'logger': s_(default='BinAuditLogger'), 'included_keyspaces': a_(s_(), default=[]), 'excluded_keyspaces': a_(s_(), default=['system', 'system_schema', 'system_virtual_schema']),
           'included_categories': a_(s_(), default=[]), 'excluded_categories': a_(s_(), default=[]),
           'included_users': a_(s_(), default=[]), 'excluded_users': a_(s_(), default=[])}), VOID,
      errors=[err('configuration-exception', 'logger class not on the classpath')],
      behavior=[
          {'set': {'state.included_keyspaces': '= input.included_keyspaces', 'state.excluded_keyspaces': '= input.excluded_keyspaces',
                   'state.included_categories': '= input.included_categories', 'state.excluded_categories': '= input.excluded_categories',
                   'state.included_users': '= input.included_users', 'state.excluded_users': '= input.excluded_users'},
           'title': 'Filters are rebuilt in the finally block, even when the logger is unchanged', 'source': rng(ALM, 203, 210, 'finally')},
          {'set': {'state.logger': '= input.logger', 'state.enabled': True, 'state.listener_registered': True},
           'title': 'Register with QueryEvents and AuthEvents, then stop the old logger', 'source': rng(ALM, 212, 217, 'registerAsListener();')},
          {'return': {}},
      ])
iface('audit-log-manager', 'is-enabled', 'AuditLogManager.isEnabled: whether the installed logger is enabled (NoOpAuditLogger reports false).',
      [rng(ALM, 116, 119, 'public boolean isEnabled()')], VOID, obj({'enabled': b_()}),
      behavior=[{'return': {'enabled': "= state.logger != 'NoOpAuditLogger'"}}])
iface('audit-log-manager', 'disable-audit-log', 'AuditLogManager.disableAuditLog: unregister listeners, install NoOpAuditLogger and stop the old one.',
      [rng(ALM, 174, 180, 'public synchronized void disableAuditLog()')], VOID, VOID,
      behavior=[{'set': {'state.enabled': False, 'state.listener_registered': False, 'state.logger': 'NoOpAuditLogger'}}, {'return': {}}])

# ---------------------------------------------------------------- full query log
FQL = J + 'fql/FullQueryLogger.java'
BL = J + 'utils/binlog/BinLog.java'
comp('full-query-logger', 'FullQueryLogger', 'node-ops', 'Logs every successful query, prepared execute and batch to a Chronicle Queue binary log once enabled.',
     [class_line(FQL, 'FullQueryLogger')], state={'initial': {'bin_log_path': '', 'listener_registered': False}},
     description='Not enabled at startup: full_query_logging_options is commented out in cassandra.yaml (1917), so log_dir is the empty string (FullQueryLoggerOptions.java:27).')
iface('full-query-logger', 'enable-without-clean', 'FullQueryLogger.enableWithoutClean: refuse when a BinLog is already configured, build one on the path and register as QueryEvents listener.',
      [rng(FQL, 106, 120, 'public synchronized void enableWithoutClean'), rng(BL, 377, 387, 'public Builder path(Path path)')],
      obj({'path': s_(default=''), 'roll_cycle': s_(default='HOURLY'), 'blocking': b_(default=True)}), VOID,
      errors=[ISE, IAE],
      behavior=[
          {'if': "state.bin_log_path != ''", 'then': [
              note('Already configured', rng(FQL, 108, 109, 'if (this.binLog != null)'), **{'fail': {'code': 'illegal-state-exception', 'message': 'Binlog is already configured'}})]},
          {'if': "input.path == ''", 'then': [
              note('BinLog.Builder.path rejects an empty directory', rng(BL, 382, 382, 'you might have forgotten to specify a directory to save logs'),
                   **{'fail': {'code': 'illegal-argument-exception', 'message': 'you might have forgotten to specify a directory to save logs'}})]},
          {'set': {'state.bin_log_path': '= input.path', 'state.listener_registered': True}},
          {'return': {}},
      ])
iface('full-query-logger', 'is-enabled', 'FullQueryLogger.isEnabled: a BinLog is configured.',
      [rng(FQL, 252, 255, 'public boolean isEnabled()')], VOID, obj({'enabled': b_()}),
      behavior=[{'return': {'enabled': "= state.bin_log_path != ''"}}])
iface('full-query-logger', 'stop', 'FullQueryLogger.stop: unregister and close the BinLog (no-op when not running).',
      [rng(FQL, 159, 183, 'public synchronized void stop()')], VOID, VOID,
      behavior=[{'set': {'state.bin_log_path': '', 'state.listener_registered': False}}, {'return': {}}])
iface('full-query-logger', 'reset', 'FullQueryLogger.reset: stop logging and delete the log files in the old and the configured directory.',
      [rng(FQL, 190, 250, 'public synchronized void reset')], obj({'log_dir': s_(default='')}), VOID,
      behavior=[{'set': {'state.bin_log_path': '', 'state.listener_registered': False}}, {'return': {}}])

# ---------------------------------------------------------------- tracing
TR = J + 'tracing/Tracing.java'
TRI = J + 'tracing/TracingImpl.java'
TSI = J + 'tracing/TraceStateImpl.java'
TK = J + 'tracing/TraceKeyspace.java'
comp('tracing-impl', 'TracingImpl', 'node-ops', 'Default Tracing implementation: writes session and event rows to system_traces through StorageProxy at CL ANY on the TRACING stage.',
     [class_line(TRI, 'TracingImpl'), class_line(TR, 'Tracing')], state={'initial': {'sessions_started': 0, 'remote_events': 0}},
     description='trace_type_query_ttl 1d and trace_type_repair_ttl 7d (cassandra.yaml 1752-1754, same as Config.java:551-554).')
comp('trace-state-impl', 'TraceStateImpl', 'tracing-impl', 'Thread-local state of one trace session; each event becomes a mutation submitted to Stage.TRACING.',
     [class_line(TSI, 'TraceStateImpl')], state={'initial': {'pending': 0, 'dropped_overloaded': 0}})
iface('trace-state-impl', 'execute-mutation', 'TraceStateImpl.executeMutation: submit mutateWithCatch to Stage.TRACING and remember the future.',
      [rng(TSI, 104, 110, 'void executeMutation(final Mutation mutation)')], {'$ref': 'OpsTraceEvent'}, VOID, kind='queue',
      behavior=[{'set': {'state.pending': '= state.pending + 1'}},
                {'title': 'Stage.TRACING runs mutateWithCatch', 'source': at(TSI, 106, 'Stage.TRACING.executor().submit'),
                 'emit': 'trace-state-impl.mutate-with-catch', 'input': '= input'}, {'return': {}}])
iface('trace-state-impl', 'mutate-with-catch', 'TraceStateImpl.mutateWithCatch: StorageProxy.mutate at CL ANY; OverloadedException is logged and swallowed.',
      [rng(TSI, 112, 122, 'static void mutateWithCatch(Mutation mutation)')], {'$ref': 'OpsTraceEvent'}, VOID,
      behavior=[
          {'title': 'Write the trace row at consistency ANY', 'source': at(TSI, 116, 'StorageProxy.mutate(singletonList(mutation), ANY'),
           'call': 'storage-proxy.mutate', 'as': 'w', 'on_error': 'continue',
           'input': {'consistency': 'ANY', 'mutations': [{'keyspace': 'system_traces', 'table': 'events', 'partition_key': '= input.session_id',
                                                         'token': 0, 'timestamp': 0, 'columns': {'activity': '= input.activity'}}]}},
          {'if': "!vars.w.ok && vars.w.error.code == 'overloaded'", 'then': [
              note('Too many nodes are overloaded to save trace events', rng(TSI, 118, 121, 'catch (OverloadedException e)'),
                   **{'set': {'state.dropped_overloaded': '= state.dropped_overloaded + 1', 'ctx.opsTraceDropped': True}})]},
          {'if': "!vars.w.ok && vars.w.error.code != 'overloaded'", 'then': [
              {'title': 'Other failures escape the stage task (logged by the executor)', 'source': at(TSI, 116, 'StorageProxy.mutate'),
               'fail': '= vars.w.error'}]},
          {'set': {'state.pending': '= state.pending - 1'}},
          {'return': {}},
      ])
iface('tracing-impl', 'begin', 'TracingImpl.begin: write the start-session row (request, client, parameters, started_at, command, ttl) for the current session.',
      [rng(TRI, 53, 67, 'public TraceState begin(final String request, final InetAddress client'), rng(TR, 174, 189, 'public TimeUUID newSession(TimeUUID sessionId, Map<String,ByteBuffer> customPayload)')],
      {'$ref': 'OpsTraceEvent'}, obj({'session_id': s_()}),
      behavior=[
          {'set': {'state.sessions_started': '= state.sessions_started + 1'}},
          {'title': 'makeStartSessionMutation, submitted on the TRACING stage', 'source': at(TRI, 65, 'makeStartSessionMutation'),
           'call': 'trace-state-impl.execute-mutation',
           'input': {'session_id': '= input.session_id', 'request': '= input.request', 'activity': '= input.request',
                     'trace_type': '= input.trace_type', 'ttl_seconds': "= input.trace_type == 'REPAIR' ? config['trace-type-repair-ttl-s'] : config['trace-type-query-ttl-s']"}},
          {'return': {'session_id': '= input.session_id'}},
      ])
iface('tracing-impl', 'stop-session-impl', 'TracingImpl.stopSessionImpl: write the stop-session row with the elapsed time.',
      [rng(TRI, 40, 51, 'public void stopSessionImpl()'), rng(TR, 201, 216, 'public void stopSession()')], {'$ref': 'OpsTraceEvent'}, VOID,
      behavior=[{'call': 'trace-state-impl.execute-mutation', 'input': '= input'}, {'return': {}}])
iface('tracing-impl', 'trace', 'TracingImpl.trace(sessionId, message, ttl): trace for a session not started on this node; the event mutation runs on Stage.TRACING.',
      [rng(TRI, 106, 117, 'public void trace(final ByteBuffer sessionId'), rng(TRI, 110, 116, 'Stage.TRACING.execute')],
      {'$ref': 'OpsTraceEvent'}, VOID, kind='queue',
      behavior=[{'set': {'state.remote_events': '= state.remote_events + 1'}},
                {'title': 'makeEventMutation on the TRACING stage', 'source': at(TRI, 114, 'TraceStateImpl.mutateWithCatch'),
                 'emit': 'trace-state-impl.mutate-with-catch', 'input': '= input'},
                {'return': {}}])

# ---------------------------------------------------------------- reconciliation: stub components for owner state seeded by ops scenarios
stub_comp('tracker', 'Tracker', 'read-path', 'read-path', J + 'db/lifecycle/Tracker.java')
stub_comp('local-sessions', 'LocalSessions', 'repair-streaming', 'repair-streaming', J + 'repair/consistent/LocalSessions.java')
stub('column-family-store', 'snapshot', 'write-path', obj({'keyspace': KS, 'table': s_(ex='users'), 'replica': s_(default='n1'), 'snapshot_name': s_(ex='RepairedDataMismatch-2026-10-30')}, ['keyspace', 'table', 'snapshot_name']), None,
     summary='ColumnFamilyStore.snapshot: flush then hard-link the live SSTables (write-path).')

# ---------------------------------------------------------------- reconciliation: interfaces other areas call that ops owns
FBU = J + 'utils/FBUtilities.java'
comp('fb-utilities', 'FBUtilities', 'node-ops', "Static utilities; here only this node's broadcast address (the coordinator the cluster convention follows).",
     [class_line(FBU, 'FBUtilities')], kind='function')
iface('fb-utilities', 'get-broadcast-address-and-port', 'FBUtilities.getBroadcastAddressAndPort: the broadcast address (listen address unless broadcast_address is set) with the storage port, cached after first use.',
      [rng(FBU, 246, 262, 'public static InetAddressAndPort getBroadcastAddressAndPort()')], obj({}), obj({'endpoint': s_(ex='n1')}),
      behavior=[{'title': 'The node itself (instance)', 'source': at(FBU, 262, 'return broadcastInetAddressAndPort;'), 'return': {'endpoint': '= self'}}])

DSS = J + 'utils/DiagnosticSnapshotService.java'
comp('diagnostic-snapshot-service', 'DiagnosticSnapshotService', 'node-ops',
     'Rate-limited diagnostic snapshots on repaired-data mismatch or duplicate rows; the replica side runs each requested snapshot on its own single-thread executor.',
     [class_line(DSS, 'DiagnosticSnapshotService')], state={'initial': {'tasks_run': 0}})
iface('diagnostic-snapshot-service', 'snapshot', 'DiagnosticSnapshotService.snapshot: require a RepairedDataMismatch-/DuplicateRows- snapshot name, then queue a DiagnosticSnapshotTask on the service executor.',
      [rng(DSS, 111, 115, 'public static void snapshot(SnapshotCommand command'), rng(DSS, 158, 161, 'private void maybeSnapshot')],
      obj({'keyspace': s_(ex='ks1'), 'column_family': s_(ex='users'), 'snapshot_name': s_(ex='RepairedDataMismatch-2026-10-30'), 'from': s_(ex='n2')}), obj({}),
      errors=[IAE],
      behavior=[
          {'if': "!(input.snapshot_name.startsWith('RepairedDataMismatch-') || input.snapshot_name.startsWith('DuplicateRows-'))", 'then': [
              {'title': 'Only diagnostic snapshot names are accepted', 'source': rng(DSS, 105, 113, 'public static boolean isDiagnosticSnapshotRequest'),
               'fail': {'code': 'illegal-argument-exception', 'message': ''}}]},
          {'title': 'executor.execute(new DiagnosticSnapshotTask(...))', 'source': at(DSS, 160, 'executor.execute(new DiagnosticSnapshotTask'),
           'emit': 'diagnostic-snapshot-service.run-task', 'input': '= input'},
          {'return': {}}])
iface('diagnostic-snapshot-service', 'run-task', 'DiagnosticSnapshotTask.run: skip when the keyspace is unknown or the snapshot tag already exists, else ColumnFamilyStore.snapshot (filtered by the requested ranges when given).',
      [rng(DSS, 177, 224, 'public void run()')],
      obj({'keyspace': s_(ex='ks1'), 'column_family': s_(ex='users'), 'snapshot_name': s_(ex='RepairedDataMismatch-2026-10-30'), 'from': s_(ex='n2')}), obj({}), kind='queue',
      behavior=[{'set': {'state.tasks_run': '= state.tasks_run + 1'}},
                {'title': 'cfs.snapshot(snapshot_name); a missing table is only logged', 'source': rng(DSS, 207, 223, 'if (ranges.isEmpty())'),
                 'call': 'column-family-store.snapshot', 'on_error': 'continue',
                 'input': {'keyspace': '= input.keyspace', 'table': '= input.column_family', 'replica': '= self', 'snapshot_name': '= input.snapshot_name'}},
                {'return': {}}])

comp('tracing', 'Tracing', 'node-ops', 'Tracing facade (Tracing.instance, a TracingImpl): opens, begins and stops the session bound to the current request.',
     [class_line(TR, 'Tracing')], state={'initial': {'current_session': '', 'trace_type': 'QUERY', 'next_session': '5f0c2a40-7a9e-11ef-8f1a-3b2d4c5e6f70'}})
iface('tracing', 'new-session', 'Tracing.newSession: create a TraceState for a new time-UUID session (type QUERY unless given) and bind it to the request.',
      [rng(TR, 158, 189, 'public TimeUUID newSession(Map<String,ByteBuffer> customPayload)')], obj({'trace_type': s_(enum=['QUERY', 'REPAIR'], default='QUERY')}),
      obj({'session_id': s_(ex='5f0c2a40-7a9e-11ef-8f1a-3b2d4c5e6f70')}),
      behavior=[{'set': {'state.current_session': '= state.next_session', 'state.trace_type': "= has(input.trace_type) ? input.trace_type : 'QUERY'"}},
                {'return': {'session_id': '= state.next_session'}}])
iface('tracing', 'begin', 'Tracing.begin(request, parameters): TracingImpl.begin writes the session row for the bound session.',
      [rng(TR, 236, 241, 'public TraceState begin(final String request, final Map<String, String> parameters)')],
      obj({'request': s_(ex='Execute CQL3 query'), 'parameters': obj({})}), None,
      behavior=[{'if': "state.current_session == ''", 'then': [{'title': 'begin asserts a session is bound (isTracing)', 'source': at(TRI, 55, 'assert isTracing();'), 'return': {}}]},
                {'call': 'tracing-impl.begin', 'input': {'session_id': '= state.current_session', 'request': "= has(input.request) ? input.request : ''",
                                                          'activity': "= has(input.request) ? input.request : ''", 'trace_type': '= state.trace_type', 'ttl_seconds': 86400}},
                {'return': {}}])
iface('tracing', 'stop-session', 'Tracing.stopSession: when a session is bound, TracingImpl.stopSessionImpl writes the duration, then the state is unbound.',
      [rng(TR, 201, 216, 'public void stopSession()')], None, None,
      behavior=[{'if': "state.current_session == ''", 'then': [{'return': {}}]},
                {'call': 'tracing-impl.stop-session-impl', 'input': {'session_id': '= state.current_session', 'request': '', 'activity': 'stop', 'trace_type': '= state.trace_type', 'ttl_seconds': 86400}},
                {'set': {'state.current_session': ''}}, {'return': {}}])

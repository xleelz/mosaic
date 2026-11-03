"""Daemon, JMX MBeans (service/*MBean.java) and the nodetool command layer."""
from gen_base import *
import gen_core  # noqa: F401  (registers core entities first)

KS = s_(ex='ks1')
VOID = obj({})
ISE = err('illegal-state-exception', 'IllegalStateException')
IAE = err('illegal-argument-exception', 'IllegalArgumentException')
IOE = err('io-exception', 'IOException')
RTE = err('runtime-exception', 'RuntimeException')

# ---------------------------------------------------------------- more boundary stubs used below
stub('storage-service', 'is-joined', 'membership', VOID, obj({'joined': b_(default=True)}), summary='StorageService.isJoined (membership).')
stub('storage-service', 'is-bootstrap-mode', 'membership', VOID, obj({'bootstrap_mode': b_(default=False)}), summary='StorageService.isBootstrapMode (membership).')
stub('column-family-store', 'import-new-sstables', 'write-path', obj({'keyspace': KS, 'table': s_(ex='users'), 'src_paths': a_(s_(), default=['/tmp/import/ks1/users'])}),
     obj({'failed_directories': a_(s_(), default=[])}), summary='ColumnFamilyStore.importNewSSTables through SSTableImporter (write-path).')
stub('column-family-store', 'load-new-sstables', 'write-path', obj({'keyspace': KS, 'table': s_(ex='users')}), VOID, summary='ColumnFamilyStore.loadNewSSTables (deprecated refresh) (write-path).')
stub('column-family-store', 'rebuild-secondary-index', 'read-path', obj({'keyspace': KS, 'table': s_(ex='users'), 'indexes': a_(s_(), default=['users_email_idx'])}), VOID,
     summary='ColumnFamilyStore.rebuildSecondaryIndex: SecondaryIndexManager rebuild (read-path).')
stub('column-family-store', 'set-compaction-thresholds', 'read-path', obj({'keyspace': KS, 'table': s_(ex='users'), 'min': i_(default=4), 'max': i_(default=32)}), VOID, [RTE],
     summary='ColumnFamilyStore.setCompactionThresholds: validate, set and submit background compaction (read-path).')
stub('column-family-store', 'disable-auto-compaction', 'read-path', obj({'keyspace': KS, 'table': s_(ex='users')}), VOID, summary='ColumnFamilyStore.disableAutoCompaction (read-path).')
stub('column-family-store', 'enable-auto-compaction', 'read-path', obj({'keyspace': KS, 'table': s_(ex='users')}), VOID, summary='ColumnFamilyStore.enableAutoCompaction (read-path).')
stub('column-family-store', 'force-compaction-keys-ignoring-gc-grace', 'read-path', obj({'keyspace': KS, 'table': s_(ex='users'), 'keys': a_(s_(), default=['user:42'])}), VOID,
     summary='ColumnFamilyStore.forceCompactionKeysIgnoringGcGrace (read-path).')

# ---------------------------------------------------------------- CassandraDaemon
comp('cassandra-daemon', 'CassandraDaemon', 'node-ops',
     'Process entry point: applies config, runs setup (JMX, commit log, startup checks, schema, replay, ring join) and starts the client transports.',
     [class_line(CD, 'CassandraDaemon'), rng(CD, 863, 866, 'public static void main(String[] args)')],
     state={'initial': {'setup_completed': False, 'native_transport_running': False, 'has_joined': True, 'survey_mode': False,
                        'local_address_is_loopback': False}})
iface('database-descriptor', 'get-autocompaction-on-startup-enabled', 'DatabaseDescriptor.getAutocompactionOnStartupEnabled (autocompaction_on_startup_enabled, default true).',
      [rng(CFG, 833, 833, 'autocompaction_on_startup_enabled')],
      VOID, obj({'enabled': b_()}), behavior=[{'return': {'enabled': "= config['autocompaction-on-startup-enabled']"}}])
iface('database-descriptor', 'start-native-transport', 'DatabaseDescriptor.startNativeTransport: the start_native_transport flag (cassandra.yaml 1020: true).',
      [at(YAML, 1020, 'start_native_transport: true'), at(CFG, 278, 'start_native_transport')],
      VOID, obj({'enabled': b_()}), behavior=[{'return': {'enabled': "= config['start-native-transport']"}}])

iface('cassandra-daemon', 'activate', 'CassandraDaemon.activate: applyConfig, registerNativeAccess, setup, start; any Throwable escaping is logged and the JVM exits with status 3.',
      [rng(CD, 718, 771, 'public void activate()'), rng(CD, 863, 866, 'public static void main(String[] args)')],
      VOID, {'$ref': 'OpsStartupResult'},
      errors=[err('startup-exception', 'startup halted; data.exit_code is the process exit status'),
              err('configuration-exception', 'configuration rejected; data.exit_code is the process exit status')],
      behavior=[
          {'title': 'applyConfig: DatabaseDescriptor.daemonInitialization', 'source': rng(CD, 723, 723, 'applyConfig();'),
           'call': 'database-descriptor.daemon-initialization', 'as': 'cfg', 'on_error': [
               {'title': 'Exception encountered during startup', 'source': rng(CD, 751, 768, 'boolean logStackTrace ='),
                'detail': 'activate() catches the Throwable and calls exitOrFail(3, ...): System.exit(3) when not run managed.',
                'fail': {'code': 'configuration-exception', 'message': '= error.message', 'data': {'exit_code': 3}}}]},
          {'title': 'registerNativeAccess: NativeAccessMBean', 'source': rng(CD, 773, 776, 'public static void registerNativeAccess()')},
          {'call': 'cassandra-daemon.setup', 'as': 'setup', 'on_error': [
              {'if': "error.code == 'startup-exception' || error.code == 'configuration-exception'", 'then': [{'fail': '= error'}]},
              {'title': 'Exception encountered during startup', 'source': rng(CD, 749, 768, 'catch (Throwable e)'),
               'fail': {'code': '= error.code', 'message': '= error.message', 'data': {'exit_code': 3}}}]},
          {'call': 'cassandra-daemon.start', 'as': 'start'},
          {'title': 'Startup complete', 'source': at(CD, 744, 'logger.info("Startup complete");'),
           'return': {'setup_completed': True, 'native_transport_started': '= vars.start.value.native_transport_started',
                      'message': '= vars.start.value.native_transport_started ? \'Startup complete\' : \'Startup complete; client transports not started\''}},
      ])

iface('cassandra-daemon', 'setup', 'CassandraDaemon.setup: JMX, commit log, startup checks, local metadata, schema, virtual keyspaces, caches, commit log replay, background tasks, initServer, gossip settle, audit log.',
      [rng(CD, 229, 455, 'protected void setup()')], VOID, VOID,
      errors=[err('startup-exception'), err('configuration-exception'), RTE],
      behavior=[
          {'title': 'maybeInitJmx: local-only JMX on 7199 (cassandra-env.sh LOCAL_JMX=yes, no authentication)', 'source': rng(CD, 139, 185, 'private void maybeInitJmx()')},
          {'title': 'Start the commit log', 'source': at(CD, 256, 'CommitLog.instance.start();'), 'call': 'commit-log.start'},
          {'title': 'runStartupChecks: a StartupException exits with its return code', 'source': rng(CD, 457, 468, 'public void runStartupChecks()'),
           'call': 'startup-checks.verify'},
          {'title': 'Snapshot system tables on version change; persist local metadata (first SystemKeyspace write)', 'source': rng(CD, 260, 271, 'SystemKeyspace.snapshotOnVersionChange();')},
          {'title': 'Populate token metadata before flushing', 'source': at(CD, 278, 'StorageService.instance.populateTokenMetadata();'), 'call': 'storage-service.populate-token-metadata'},
          {'title': 'Load schema from disk', 'source': at(CD, 283, 'Schema.instance.loadFromDisk();'), 'call': 'schema.load-from-disk'},
          {'title': 'setupVirtualKeyspaces: system_virtual_schema', 'source': rng(CD, 534, 537, 'public void setupVirtualKeyspaces()'),
           'call': 'virtual-keyspace-registry.register', 'input': {'keyspace': 'system_virtual_schema'}},
          {'title': 'setupVirtualKeyspaces: system_views', 'source': at(CD, 537, 'SystemViewsKeyspace.instance'),
           'call': 'virtual-keyspace-registry.register', 'input': {'keyspace': 'system_views'}},
          {'title': 'scrubDataDirectories, Keyspace.setInitialized, open keyspaces with auto-compaction disabled until gossip settles', 'source': rng(CD, 293, 317, 'scrubDataDirectories();')},
          {'title': 'loadRowAndKeyCacheAsync: key and row cache loads run concurrently; get() waits for both, and a failure is only logged',
           'source': rng(CD, 572, 582, 'private Future<?> loadRowAndKeyCacheAsync()'),
           'parallel': ['KEY_CACHE', 'ROW_CACHE'], 'as': 'cache', 'join': {'need': 'all'}, 'as_result': 'cacheLoads',
           'steps': [{'title': 'AutoSavingCache.loadSavedAsync (row_cache_size 0MiB, so the row cache is empty)', 'source': rng(CD, 319, 327, 'loadRowAndKeyCacheAsync().get();'),
                      'call': 'auto-saving-cache.load-saved', 'input': {'cache_type': '= vars.cache'}, 'on_error': 'continue'}]},
          {'title': 'Replay commit log segments found on disk; an IOException becomes a RuntimeException', 'source': rng(CD, 343, 350, 'CommitLog.instance.recoverSegmentsOnDisk();'),
           'call': 'commit-log.recover-segments-on-disk', 'as': 'replay', 'input': {'segments': []}, 'on_error': [
               {'fail': {'code': 'runtime-exception', 'message': '= error.message'}}]},
          {'title': 'Re-populate token metadata after replay', 'source': at(CD, 353, 'StorageService.instance.populateTokenMetadata();'), 'call': 'storage-service.populate-token-metadata'},
          {'title': 'cleanupSizeEstimates; schedule SizeEstimatesRecorder every 300 s after 30 s (cassandra.size_recorder_interval)', 'source': rng(CD, 365, 371, 'StorageService.instance.cleanupSizeEstimates();')},
          {'title': 'Start ActiveRepairService and StreamManager', 'source': rng(CD, 373, 374, 'ActiveRepairService.instance().start();'), 'call': 'active-repair-service.start'},
          {'title': 'Preload prepared statements', 'source': at(CD, 377, 'QueryProcessor.instance.preloadPreparedStatements();'), 'call': 'query-processor.preload-prepared-statements'},
          {'title': 'initServer; a ConfigurationException exits with status 1', 'source': rng(CD, 380, 389, 'StorageService.instance.registerDaemon(this);'),
           'call': 'storage-service.init-server', 'on_error': [
               {'if': "error.code in ['config-error', 'configuration-exception']", 'then': [
                   {'fail': {'code': 'configuration-exception', 'message': 'Fatal configuration error', 'data': {'exit_code': 1}}}]},
               {'title': 'Other failures propagate to activate() (exit 3)', 'source': rng(CD, 381, 389, 'try'), 'fail': '= error'}]},
          {'title': 'Schedule the materialized view build after RING_DELAY', 'source': rng(CD, 393, 401, 'Runnable viewRebuild')},
          {'when': '!state.local_address_is_loopback', 'title': 'Wait for gossip to settle (skipped on loopback)', 'source': rng(CD, 403, 404, 'Gossiper.waitToSettle();'),
           'call': 'gossiper.wait-to-settle'},
          {'title': 'doAuthSetup', 'source': at(CD, 406, 'StorageService.instance.doAuthSetup(false);')},
          {'call': 'database-descriptor.get-autocompaction-on-startup-enabled', 'as': 'ac'},
          {'title': 'Reload stores and re-enable auto-compaction when autocompaction_on_startup_enabled', 'source': rng(CD, 408, 428, 're-enable auto-compaction after gossip is settled'),
           'set': {'ctx.opsAutocompactionReenabled': '= vars.ac.value.enabled'}},
          {'title': 'Initialise the audit log manager', 'source': at(CD, 431, 'AuditLogManager.instance.initialize();'), 'call': 'audit-log-manager.initialize'},
          {'title': 'Schedule the background compaction submitter every 1 min after 5 min', 'source': at(CD, 435, 'getBackgroundCompactionTaskSubmitter(), 5, 1, TimeUnit.MINUTES')},
          {'title': 'Schedule speculative retry threshold updates every read_request_timeout (5000 ms)', 'source': rng(CD, 438, 441, 'SPECULATION_THRESHOLD_UPDATER')},
          {'title': 'initializeClientTransports: create NativeTransportService (not started yet)', 'source': rng(CD, 561, 567, 'public synchronized void initializeClientTransports()')},
          {'title': 'Auth cache warming disabled by default; start Paxos auto repairs', 'source': rng(CD, 447, 452, 'getAuthCacheWarmingEnabled()')},
          {'title': 'completeSetup', 'source': rng(CD, 586, 590, 'public void completeSetup()'), 'set': {'state.setup_completed': True}},
          {'return': {}},
      ])

iface('cassandra-daemon', 'start', 'CassandraDaemon.start: wait for peer connectivity, then start client transports unless validateTransportsCanStart refuses (logged, not fatal).',
      [rng(CD, 643, 663, 'public void start()')], VOID, obj({'native_transport_started': b_()}),
      behavior=[
          {'title': 'StartupClusterConnectivityChecker waits up to block_for_peers_timeout_in_secs for peers', 'source': rng(CD, 645, 647, 'StartupClusterConnectivityChecker')},
          {'call': 'cassandra-daemon.validate-transports-can-start', 'as': 'valid', 'on_error': [
              {'title': 'Transports not started; the reason is only logged', 'source': rng(CD, 655, 659, 'catch (IllegalStateException isx)'),
               'set': {'ctx.opsTransportsSkipped': '= error.message'}},
              {'return': {'native_transport_started': False}}]},
          {'call': 'database-descriptor.start-native-transport', 'as': 'flag'},
          {'if': '!vars.flag.value.enabled', 'then': [
              {'title': 'Not starting native transport as requested', 'source': rng(CD, 665, 672, 'private void startClientTransports()'),
               'return': {'native_transport_started': False}}]},
          {'title': 'startClientTransports', 'source': at(CD, 669, 'startNativeTransport();'), 'call': 'cassandra-daemon.start-native-transport'},
          {'return': {'native_transport_started': True}},
      ])
iface('cassandra-daemon', 'validate-transports-can-start', 'CassandraDaemon.validateTransportsCanStart: once joined, refuse in write_survey mode while bootstrapping or with auth, and refuse until bootstrap completed.',
      [rng(CD, 783, 807, 'public void validateTransportsCanStart()')], VOID, VOID, errors=[ISE],
      behavior=[
          {'if': '!state.has_joined', 'then': [{'return': {}}]},
          {'call': 'storage-service.get-bootstrap-state', 'as': 'bs'},
          {'if': 'state.survey_mode', 'then': [
              {'title': 'write_survey refusal', 'source': rng(CD, 790, 797, 'if (StorageService.instance.isSurveyMode())'),
               'fail': {'code': 'illegal-state-exception', 'message': 'Not starting client transports in write_survey mode as it\'s bootstrapping or auth is enabled'}}]},
          {'choice': 'bootstrap', 'default': "= vars.bs.value.state == 'COMPLETED' ? 'complete' : 'incomplete'", 'options': {'complete': [], 'incomplete': [
              {'title': 'Bootstrap incomplete', 'source': rng(CD, 799, 805, 'if (!SystemKeyspace.bootstrapComplete())'),
               'fail': {'code': 'illegal-state-exception', 'message': 'Node is not yet bootstrapped completely. Use nodetool to check bootstrap state and resume. For more, see `nodetool help bootstrap`'}}]}},
          {'return': {}},
      ])
iface('cassandra-daemon', 'start-native-transport', 'CassandraDaemon.startNativeTransport: validate, require setup, start the servers, and set RPC ready in gossip if none was running.',
      [rng(CD, 809, 825, 'public void startNativeTransport()')], VOID, VOID, errors=[ISE],
      behavior=[
          {'call': 'cassandra-daemon.validate-transports-can-start'},
          {'if': '!state.setup_completed', 'then': [
              {'title': 'setup() must run first', 'source': at(CD, 813, 'if (nativeTransportService == null)'),
               'fail': {'code': 'illegal-state-exception', 'message': 'setup() must be called first for CassandraDaemon'}}]},
          {'set': {'vars.already': '= state.native_transport_running'}},
          {'title': 'NativeTransportService.start', 'source': at(CD, 820, 'nativeTransportService.start();'), 'call': 'native-transport-service.start'},
          {'set': {'state.native_transport_running': True}},
          {'when': '!vars.already', 'title': 'Announce RPC readiness', 'source': rng(CD, 823, 824, 'if (!alreadyRunning)'),
           'call': 'storage-service.set-rpc-ready', 'input': {'value': True}},
          {'return': {}},
      ])
iface('cassandra-daemon', 'stop-native-transport', 'CassandraDaemon.stopNativeTransport(force): stop the native transport servers if created.',
      [rng(CD, 833, 837, 'public void stopNativeTransport(boolean force)')], obj({'force': b_(default=False)}), VOID,
      behavior=[{'call': 'native-transport-service.stop', 'input': {'force': '= input.force'}}, {'set': {'state.native_transport_running': False}}, {'return': {}}])
iface('cassandra-daemon', 'deactivate', 'CassandraDaemon.deactivate: stop (transports, RPC ready false, JMX server), destroy, then System.exit(0) when not run managed.',
      [rng(CD, 847, 856, 'public void deactivate()'), rng(CD, 679, 698, 'public void stop()')], VOID, VOID,
      behavior=[{'call': 'cassandra-daemon.stop-native-transport', 'input': {'force': False}},
                {'call': 'storage-service.set-rpc-ready', 'input': {'value': False}},
                {'set': {'ctx.opsProcessExit': 0}}, {'return': {}}])

# ---------------------------------------------------------------- JMX dispatch
MW = J + 'utils/MBeanWrapper.java'
comp('mbean-wrapper', 'MBeanWrapper', 'node-ops',
     'Registers every Cassandra MBean with the platform MBeanServer; JMX clients (nodetool, jconsole) invoke operations through it.',
     [class_line(MW, 'MBeanWrapper'), rng(MW, 173, 180, 'class PlatformMBeanWrapper implements MBeanWrapper')],
     description='The dispatch itself is the JDK platform MBeanServer behind the JMX connector created by maybeInitJmx (local-only on port 7199 per cassandra-env.sh).')

# ---------------------------------------------------------------- service MBeans
comp('storage-service-mbean', 'StorageServiceMBean', 'node-ops',
     'JMX surface of StorageService (org.apache.cassandra.db:type=StorageService) and the operational glue StorageService runs behind it.',
     [class_line(SSM, 'StorageServiceMBean'), class_line(SS, 'StorageService')],
     state={'initial': {
         'keyspaces': ['system', 'system_schema', 'system_auth', 'system_distributed', 'system_traces', 'ks1', 'shop'],
         'distributed_keyspaces': ['system_auth', 'system_distributed', 'system_traces', 'ks1', 'shop'],
         'local_system_keyspaces': ['system', 'system_schema'],
         'virtual_keyspaces': ['system_views', 'system_virtual_schema'],
         'tables': {'system': ['local', 'peers_v2'], 'system_schema': ['tables'], 'system_auth': ['roles'],
                    'system_distributed': ['repair_history'], 'system_traces': ['sessions', 'events'], 'ks1': ['events', 'page_views', 'users'],
                    'shop': ['accounts', 'entries', 'orders', 'page_views', 'users']},
         'compaction_throughput_mib_per_sec': 64, 'concurrent_compactors': 2, 'concurrent_view_builders': 1,
         'trace_probability': 0.0, 'incremental_backups': False, 'column_index_size_kib': -1,
         'snapshot_links_per_second': 0, 'batchlog_replay_throttle_kib': 1024, 'hinted_handoff_throttle_kib': 1024,
         'default_keyspace_rf': 1, 'native_transport_allow_older_protocols': True, 'allow_unlimited_concurrent_validations': False,
         'stream_throughput_mib': 24, 'inter_dc_stream_throughput_mib': 24, 'entire_sstable_stream_throughput_mib': 24, 'entire_sstable_inter_dc_stream_throughput_mib': 24,
         'timeout_read_ms': 5000, 'timeout_range_ms': 10000, 'timeout_write_ms': 2000, 'timeout_counterwrite_ms': 5000, 'timeout_cascontention_ms': 1000,
         'timeout_truncate_ms': 60000, 'timeout_misc_ms': 10000, 'timeout_internodeconnect_ms': 2000, 'timeout_internodeuser_ms': 30000, 'timeout_internodestreaminguser_ms': 300000,
         'stage_pools': {'MutationStage': {'core': 32, 'max': 32}, 'ReadStage': {'core': 32, 'max': 32}, 'CounterMutationStage': {'core': 32, 'max': 32}, 'ViewMutationStage': {'core': 32, 'max': 32}},
     }},
     description='State mirrors the effective runtime values the operations below read and write. Defaults: compaction_throughput 64MiB/s (yaml 1251), '
                 'concurrent_compactors unset so min(8, max(2, min(cpus, data dirs))) = 2 with one data directory (DatabaseDescriptor.java:777-778), '
                 'column_index_size unset so -1 (DatabaseDescriptor.java:2034-2037), snapshot_links_per_second 0 (yaml 1162), '
                 'batchlog_replay_throttle and hinted_handoff_throttle 1024KiB (yaml 157, 88), timeouts per yaml 1322-1349, '
                 'stream throughputs 24MiB/s (Config.java:362-366; commented in yaml), concurrent_writes/reads 32.')
comp('storage-proxy-mbean', 'StorageProxyMBean', 'node-ops',
     'JMX surface of StorageProxy (org.apache.cassandra.db:type=StorageProxy): hinted handoff switches, hint window, denylist and repaired-data tracking flags.',
     [class_line(SPM, 'StorageProxyMBean'), class_line(SP, 'StorageProxy')],
     state={'initial': {'hinted_handoff_enabled': True, 'max_hint_window_ms': 10800000, 'hints_disabled_dcs': [],
                        'repaired_data_tracking_range_reads': False, 'repaired_data_tracking_partition_reads': False,
                        'report_unconfirmed_repaired_data_mismatches': False, 'snapshot_on_repaired_data_mismatch': False,
                        'snapshot_on_duplicate_row_detection': False, 'check_duplicate_rows_reads': True, 'check_duplicate_rows_compaction': True,
                        'denylisted_keys': []}},
     description='hinted_handoff_enabled true (yaml 68), max_hint_window 3h = 10800000 ms (yaml 80).')
CSM = J + 'service/CacheServiceMBean.java'
CS = J + 'service/CacheService.java'
comp('cache-service-mbean', 'CacheServiceMBean', 'node-ops', 'JMX surface of CacheService (key, row and counter caches): invalidate, resize, keys to save, save now.',
     [class_line(CSM, 'CacheServiceMBean'), class_line(CS, 'CacheService')],
     state={'initial': {'key_cache_keys_to_save': 2147483647, 'row_cache_keys_to_save': 2147483647, 'counter_cache_keys_to_save': 2147483647}},
     description='key_cache_size auto (min 5% heap, 100MiB), row_cache_size 0MiB, counter_cache_size auto (yaml 525-603); keys_to_save default all (Integer.MAX_VALUE).')
ARSM = J + 'service/ActiveRepairServiceMBean.java'
comp('active-repair-service-mbean', 'ActiveRepairServiceMBean', 'node-ops', 'JMX surface of ActiveRepairService used by nodetool repair_admin.',
     [class_line(ARSM, 'ActiveRepairServiceMBean')])


def jop(mbean_comp, mbean, method, summary, impl, request, response, behavior, errors=None, extra_sources=None, description=None):
    srcs = [jmx(mbean + '.' + method)] + ([impl] if isinstance(impl, str) else list(impl)) + (extra_sources or [])
    return iface(mbean_comp, kebab(method), summary, srcs, request, response, behavior, errors, kind='jmx',
                 attrs={'mbean': mbean, 'operation': method}, description=description)


def ss(method, summary, impl, request, response, behavior, errors=None, **kw):
    return jop('storage-service-mbean', 'StorageServiceMBean', method, summary, impl, request, response, behavior, errors, **kw)


def sp(method, summary, impl, request, response, behavior, errors=None, **kw):
    return jop('storage-proxy-mbean', 'StorageProxyMBean', method, summary, impl, request, response, behavior, errors, **kw)


def cs(method, summary, impl, request, response, behavior, errors=None, **kw):
    return jop('cache-service-mbean', 'CacheServiceMBean', method, summary, impl, request, response, behavior, errors, **kw)


# helpers on storage-service-mbean
iface('storage-service-mbean', 'get-valid-column-families', 'StorageService.getValidColumnFamilies: validate the keyspace (not virtual, exists) and resolve table names; an unknown table is an IllegalArgumentException.',
      [rng(SS, 4731, 4735, 'public Iterable<ColumnFamilyStore> getValidColumnFamilies'), rng(SS, 4559, 4572, 'private void verifyKeyspaceIsValid'),
       rng(J + 'db/Keyspace.java', 688, 739, 'public Iterable<ColumnFamilyStore> getValidColumnFamilies'), rng(J + 'db/Keyspace.java', 215, 221, 'public ColumnFamilyStore getColumnFamilyStore(String cfName)')],
      obj({'keyspace': KS, 'tables': a_(s_(), default=[])}, ['keyspace', 'tables']), obj({'tables': a_(s_())}), errors=[IAE],
      behavior=[
          {'if': 'input.keyspace in state.virtual_keyspaces', 'then': [
              {'fail': {'code': 'illegal-argument-exception', 'message': "= 'Cannot perform any operations against virtual keyspace ' + input.keyspace"}}]},
          {'if': '!(input.keyspace in state.keyspaces)', 'then': [
              {'fail': {'code': 'illegal-argument-exception', 'message': "= 'Keyspace ' + input.keyspace + ' does not exist'"}}]},
          {'if': 'size(input.tables) == 0', 'then': [{'return': {'tables': '= state.tables[input.keyspace]'}}]},
          {'foreach': '= input.tables', 'as': 't', 'steps': [
              {'if': '!(vars.t in state.tables[input.keyspace])', 'then': [
                  {'fail': {'code': 'illegal-argument-exception', 'message': "= 'Unknown keyspace/cf pair (' + input.keyspace + '.' + vars.t + ')'"}}]}]},
          {'return': {'tables': '= input.tables'}},
      ])
ss('getKeyspaces', 'StorageService.getKeyspaces: every local and distributed keyspace from Schema (used by nodetool to resolve its keyspace argument).',
   rng(SS, 6231, 6234, 'public List<String> getKeyspaces()'), VOID, obj({'keyspaces': a_(s_())}),
   [{'return': {'keyspaces': '= state.keyspaces'}}])
ss('getNonLocalStrategyKeyspaces', 'StorageService.getNonLocalStrategyKeyspaces: Schema.distributedKeyspaces (system_auth, system_distributed, system_traces and user keyspaces).',
   rng(SS, 6241, 6244, 'public List<String> getNonLocalStrategyKeyspaces()'), VOID, obj({'keyspaces': a_(s_())}),
   [{'return': {'keyspaces': '= state.distributed_keyspaces'}}])
ss('getNonSystemKeyspaces', 'StorageService.getNonSystemKeyspaces: also Schema.distributedKeyspaces, so it includes system_auth, system_distributed and system_traces.',
   rng(SS, 6236, 6239, 'public List<String> getNonSystemKeyspaces()'), VOID, obj({'keyspaces': a_(s_())}),
   [{'return': {'keyspaces': '= state.distributed_keyspaces'}}])
ss('getParentRepairStatus', 'StorageService.getParentRepairStatus: [status, messages...] of a repair command from ActiveRepairService, or null when unknown.',
   rng(SS, 4969, 4974, 'public List<String> getParentRepairStatus(int cmd)'), obj({'cmd': i_(default=1)}),
   obj({'status': s_(desc='IN_PROGRESS, COMPLETED or FAILED; empty when unknown'), 'messages': a_(s_())}),
   [{'call': 'active-repair-service.get-repair-status', 'input': {'cmd': '= input.cmd'}, 'as': 'st'},
    {'return': '= vars.st.value'}])
ss('getConcurrentCompactors', 'StorageService.getConcurrentCompactors: concurrent_compactors (NodeProbe.checkJobs compares --jobs with it).',
   rng(SS, 1959, 1962, None), VOID, obj({'value': i_()}), [{'return': {'value': '= state.concurrent_compactors'}}])

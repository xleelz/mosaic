import sys; sys.path.insert(0, "/home/lbethay/workplace/mosaic/examples/cassandra/ops-gen")
import json, collections
d = json.load(open('/tmp/ops_work/mine.json'))
unc = d['uncovered']
def mb(e): return e['name'].split('.')[-2] if e['kind'] == 'jmx-operation' else ''
def meth(e): return e['name'].split('.')[-1]
SVC = ('StorageServiceMBean', 'StorageProxyMBean', 'CacheServiceMBean', 'ActiveRepairServiceMBean', 'GCInspectorMXBean', 'NativeAccessMBean')
READ_ONLY = {'describeRingJMX', 'describeRingWithPortJMX', 'trueSnapshotsSize', 'effectiveOwnership', 'effectiveOwnershipWithPort', 'sampleKeyRange', 'samplePartitions',
             'autoOptimiseIncRepairStreams', 'autoOptimiseFullRepairStreams', 'autoOptimisePreviewRepairStreams', 'topPartitionsEnabled', 'parentRepairSessionsCount',
             'countAllBatches', 'estimateKeys', 'hasMisplacedSSTables', 'finishLocalSampling', 'beginLocalSampling', 'dumpTimings', 'dumpInterArrivalTimes',
             'compareGossipAndTokenMetadata', 'readEvents'}
READONLY_CLI = None
GROUPS = collections.OrderedDict()
def g(key, reason, pred):
    GROUPS[key] = {'reason': reason, 'pred': pred, 'items': []}
g('guardrails', 'GuardrailsMBean threshold/flag getters and setters (db/guardrails): each reads or assigns one GuardrailsConfig field; enforcement happens where each guardrail is checked (cql/schema paths), not here.',
  lambda e: e['kind'] == 'jmx-operation' and mb(e) == 'GuardrailsMBean')
g('autorepair', 'AutoRepairServiceMBean (service/AutoRepairService.java) scheduler configuration: auto-repair is disabled in the deployed config (auto_repair commented out in cassandra.yaml 2342; AutoRepairConfig() enabled=false and cassandra.autorepair.enable=false, AutoRepairConfig.java:127-146, CassandraRelevantProperties.java:62).',
  lambda e: e['kind'] == 'jmx-operation' and mb(e) == 'AutoRepairServiceMBean')
g('metrics', 'CassandraMetricsRegistry JMX metric beans (gauge, counter, meter, histogram, timer reads): metric values only, no behavior.',
  lambda e: e['kind'] == 'jmx-operation' and e['file'].endswith('CassandraMetricsRegistry.java'))
g('getters', 'JMX getters (get*/is*): reads of a config value, metric, status or report; no state change.',
  lambda e: e['kind'] == 'jmx-operation' and (meth(e).startswith('get') or meth(e).startswith('is')))
g('readonly-ops', 'Read-only report or diagnostic JMX operations without a get/is prefix (ring description, ownership, samples, counts, timing dumps): no state change that affects request handling.',
  lambda e: e['kind'] == 'jmx-operation' and meth(e) in READ_ONLY)
g('svc-setters', 'Runtime-tunable setters on service MBeans (StorageService, StorageProxy, CacheService, ActiveRepairService, GCInspector) that no nodetool command invokes: each assigns one DatabaseDescriptor/Config value (a few also resize an executor or limiter) read later by the owning area. The nodetool-reachable setters are modeled.',
  lambda e: e['kind'] == 'jmx-operation' and mb(e) in SVC and meth(e).startswith('set'))
g('pool-setters', 'ResizableThreadPoolMXBean setters (concurrent/): per-executor core/max pool size; the same resize is modeled through nodetool setconcurrency (StorageService.setConcurrency).',
  lambda e: e['kind'] == 'jmx-operation' and mb(e) == 'ResizableThreadPoolMXBean')
g('other-area-jmx', 'JMX-only operations and setters of MBeans in other areas\' packages (auth, db, db/commitlog, db/compaction, db/memtable, diag, gms, io, locator, net, streaming) that no nodetool command calls: the owning area models what they do.',
  lambda e: e['kind'] == 'jmx-operation')
g('readonly-cli', 'Read-only nodetool report commands: they call JMX getters (or temporary samplers, for profileload and toppartitions) and print; repair_admin list/summarize-* and getguardrailsconfig/getautorepairconfig/autorepairstatus included.',
  lambda e: e['kind'] == 'cli-command' and e['name'].split(' ', 1)[1] in READONLY_SET)
g('cli-config-other', 'nodetool commands that only drive configuration owned by other areas or disabled features: setguardrailsconfig (reflective GuardrailsMBean setters), setautorepairconfig (auto-repair disabled), setauthcacheconfig (AuthCacheMBean setters, schema-auth).',
  lambda e: e['kind'] == 'cli-command' and e['name'] in ('nodetool getguardrailsconfig', 'nodetool setguardrailsconfig', 'nodetool setautorepairconfig', 'nodetool setauthcacheconfig'))
g('cli-diagnostic', 'nodetool sjk: embedded Swiss Java Knife JVM diagnostics, not Cassandra behavior.',
  lambda e: e['kind'] == 'cli-command' and e['name'] in ('nodetool sjk', 'nodetool profileload', 'nodetool toppartitions'))
g('cli-offline', 'Standalone tools that do not talk to a running node\'s request path: jmxtool (dumps/diffs MBean metadata), fqltool compare/dump/replay (read or replay full query log files from outside), compaction-stress (offline stress of compaction).',
  lambda e: e['kind'] == 'cli-command')
g('java-main', 'Standalone main() of an offline or client-side tool (sstable utilities, standalone scrub/verify/upgrade/split, bulk loader, stress, token generator, password hasher, log viewers, version printer); they run outside the daemon. DynamicList.main and DistributionQuantized.main are test mains (not an entry point).',
  lambda e: e['kind'] == 'java-main')
g('python-cli', 'cqlsh is the Python CQL shell (a native-protocol client, modeled as the cql-client actor); the doc/scripts entries are documentation generators (not an entry point).',
  lambda e: e['kind'] == 'python-cli')
g('tasks', 'Background or scheduled housekeeping in utils/metrics/security with no effect on request outcomes: Ref leak detection and reaper, BufferPool cleanup, MonotonicClock approximate-time updaters, ResourceWatcher file polling, SSLFactory certificate hot-reload check (TLS off in the deployed config: internode_encryption none, cassandra.yaml 1648), MessagingMetrics dropped-message logging, TopPartitionTracker hourly save.',
  lambda e: e['kind'] in ('scheduled-task', 'background-task') and not e['file'].endswith(('MemtableCleanerThread.java', 'DataResurrectionCheck.java')))
g('memtable-cleaner', 'MemtableCleanerThread (utils/memory): when memtable memory passes memtable_cleanup_threshold it flushes the largest memtable; the flush itself is write-path\'s model (ColumnFamilyStore flush).',
  lambda e: e['file'].endswith('MemtableCleanerThread.java'))
g('resurrection-heartbeat', 'DataResurrectionCheck heartbeat writer: only scheduled by the check_data_resurrection startup check, which is disabled by default (startup_checks commented out, cassandra.yaml 2270; StartupCheckType.check_data_resurrection(true), StartupChecks.java:113).',
  lambda e: e['file'].endswith('DataResurrectionCheck.java'))
import gen_nodetool_readonly as R
READONLY_SET = set(R.READONLY)
left = []
for e in unc:
    for k, G in GROUPS.items():
        if G['pred'](e):
            G['items'].append(e); break
    else:
        left.append(e)
print('unassigned', len(left), [(x['kind'], x['name']) for x in left])
tot = 0
for k, G in GROUPS.items():
    print(k, len(G['items'])); tot += len(G['items'])
print('total', tot)
json.dump({k: {'reason': G['reason'], 'items': [(e['kind'], e['name'], e['file'], e['line']) for e in G['items']]} for k, G in GROUPS.items()}, open('/tmp/ops_work/groups.json', 'w'), indent=1)

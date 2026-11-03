"""nodetool: NodeTool dispatcher, NodeProbe, RepairRunner and one component per modeled command."""
from gen_base import *
import gen_mbeans  # noqa: F401
from gen_ops import KS, VOID, ISE, IAE, IOE, RTE

ND = J + 'tools/nodetool/'
COMMANDS = {}
READONLY = []


def jx(name):
    return jmx(name)


# ---------------------------------------------------------------- NodeTool, NodeToolCmd, NodeProbe
comp('node-tool', 'NodeTool', 'node-ops',
     'The nodetool CLI (a separate JVM on the operator side): parses the command line with airline, connects to the node over JMX and runs one command.',
     [class_line(NT, 'NodeTool'), rng(NT, 85, 88, 'public static void main(String... args)')], kind='client', layer='tools',
     state={'initial': {'commands': {}, 'readonly_commands': []}},
     description='Exit status: 0 success; 1 for IllegalArgumentException, IllegalStateException and airline parse errors (badUse) and for a failed JMX connection; 2 for any other Throwable, printing the root cause message.')
comp('node-tool-node-tool-cmd', 'NodeTool.NodeToolCmd', 'node-tool', 'Base class of every JMX-backed command: connects a NodeProbe, runs execute(probe), and fails when the probe recorded a failure.',
     [rng(NT, 348, 355, 'public static abstract class NodeToolCmd'), rng(NT, 380, 401, 'public void runInternal()')], kind='function', layer='tools')
comp('node-probe', 'NodeProbe', 'node-tool', 'JMX client: opens the RMI connector to host:port (default 127.0.0.1:7199) and proxies the Cassandra MBeans.',
     [class_line(NP, 'NodeProbe'), rng(NP, 246, 270, 'protected void connect()')], kind='client', layer='tools')
iface('node-probe', 'connect', 'NodeProbe.connect: JMXConnectorFactory.connect to service:jmx:rmi:///jndi/rmi://host:port/jmxrmi and build the MBean proxies.',
      [rng(NP, 246, 270, 'protected void connect()')], obj({'host': s_(default='127.0.0.1'), 'port': i_(default=7199)}), VOID,
      errors=[IOE, err('security-exception')], kind='jmx', behavior=[{'return': {}}], latency={'min': 20, 'max': 80})
iface('node-tool-node-tool-cmd', 'parse-optional-keyspace', 'NodeToolCmd.parseOptionalKeyspace: the given keyspace, or all / non-system / non-local-strategy keyspaces; each must exist on the node.',
      [rng(NT, 476, 502, 'protected List<String> parseOptionalKeyspace(List<String> cmdArgs, NodeProbe nodeProbe, KeyspaceSet')],
      obj({'keyspace': s_(default=''), 'set': s_(enum=['ALL', 'NON_SYSTEM', 'NON_LOCAL_STRATEGY'], default='ALL')}), obj({'keyspaces': a_(s_())}), errors=[IAE],
      behavior=[
          {'call': 'storage-service-mbean.get-keyspaces', 'as': 'all'},
          {'if': "input.keyspace != ''", 'then': [{'set': {'vars.list': ['= input.keyspace']}}], 'else': [
              {'if': "input.set == 'ALL'", 'then': [{'set': {'vars.list': '= vars.all.value.keyspaces'}}], 'else': [
                  {'call': 'storage-service-mbean.get-non-local-strategy-keyspaces', 'as': 'nl'},
                  {'set': {'vars.list': '= vars.nl.value.keyspaces'}}]}]},
          {'foreach': '= vars.list', 'as': 'k', 'steps': [
              {'if': '!(vars.k in vars.all.value.keyspaces)', 'then': [
                  {'title': 'Unknown keyspace', 'source': at(NT, 498, 'does not exist.'),
                   'fail': {'code': 'illegal-argument-exception', 'message': "= 'Keyspace [' + vars.k + '] does not exist.'"}}]}]},
          {'return': {'keyspaces': '= vars.list'}},
      ])

# ---------------------------------------------------------------- RepairRunner
RR = J + 'tools/RepairRunner.java'
comp('repair-runner', 'RepairRunner', 'node-tool', 'nodetool side of a repair: calls repairAsync, then waits on JMX progress notifications and polls the parent repair status.',
     [class_line(RR, 'RepairRunner')], kind='function', layer='tools',
     description='Waits in rounds of cassandra.nodetool.jmx_notification_poll_interval_seconds (default 300 s, CassandraRelevantProperties.java:376) and re-queries getParentRepairStatus after each round and on completion.')
iface('repair-runner', 'run', 'RepairRunner.run: repairAsync; 0 means nothing to repair (RF 1); otherwise wait for COMPLETE or ERROR notifications, then confirm with getParentRepairStatus.',
      [rng(RR, 63, 91, 'public void run()'), rng(RR, 126, 146, 'public void progress(String tag, ProgressEvent event)'), rng(RR, 148, 186, 'private void queryForCompletedRepair')],
      obj({'keyspace': KS, 'options': obj({}, default={})}, ['keyspace']), obj({'cmd': i_(), 'status': s_()}),
      errors=[RTE, IOE],
      behavior=[
          {'title': 'ssProxy.repairAsync(keyspace, options): StorageServiceMBean.repairAsync, modeled by repair-streaming', 'source': at(RR, 65, 'cmd = ssProxy.repairAsync(keyspace, options);'),
           'call': 'storage-service.repair-async', 'as': 'cmd', 'input': {'keyspace': '= input.keyspace', 'options': '= input.options'}},
          {'title': 'The JMX operation behind ssProxy.repairAsync: StorageServiceMBean.repairAsync', 'source': jx('StorageServiceMBean.repairAsync')},
          {'choice': 'started', 'default': "= vars.cmd.value.cmd > 0 ? 'started' : 'nothing_to_repair'", 'options': {
              'nothing_to_repair': [
                  {'title': 'Replication factor is 1. No repair is needed', 'source': rng(RR, 66, 71, 'if (cmd <= 0)'),
                   'set': {'ctx.opsRepairOutcome': 'nothing to repair'}},
                  {'return': {'cmd': 0, 'status': 'NONE'}}],
              'started': []}},
          {'title': 'Wait for progress notifications tagged repair:<cmd>', 'source': rng(RR, 74, 78, 'while (!condition.await(JMX_NOTIFICATION_POLL_INTERVAL_SECONDS, SECONDS))'),
           'choice': 'notification', 'default': 'complete', 'options': {
               'complete': [],
               'error': [{'title': 'An ERROR progress event fails the run', 'source': rng(RR, 135, 140, 'if (type == ERROR)'),
                          'set': {'ctx.opsRepairOutcome': 'error notification'}},
                         {'fail': {'code': 'runtime-exception', 'message': 'Repair job has failed with the error message: Repair session failed. Check the logs on the repair participants for further details'}}],
               'connection_closed': [{'title': 'JMX connection closed', 'source': rng(RR, 116, 123, 'public void handleConnectionFailed'),
                                      'set': {'ctx.opsRepairOutcome': 'connection closed'}},
                                     {'fail': {'code': 'io-exception', 'message': "= 'JMX connection closed. You should check server log for repair status of keyspace ' + input.keyspace + '(Subsequent keyspaces are not going to be repaired).'"}}]}},
          {'title': 'Notifications are lossy: confirm with getParentRepairStatus', 'source': rng(RR, 79, 85, 'Exception error = this.error;'),
           'call': 'storage-service-mbean.get-parent-repair-status', 'as': 'st', 'input': {'cmd': '= vars.cmd.value.cmd'}},
          {'choice': 'parent_status', 'default': "= vars.st.value.status in ['COMPLETED', 'FAILED', 'IN_PROGRESS'] ? vars.st.value.status : 'UNKNOWN'", 'options': {
              'COMPLETED': [{'set': {'ctx.opsRepairOutcome': 'completed'}}],
              'UNKNOWN': [{'title': 'No recorded status: the message is printed, no error is raised', 'source': rng(RR, 151, 156, 'if (status == null)'),
                           'set': {'ctx.opsRepairOutcome': 'completed (status not found)'}}],
              'IN_PROGRESS': [{'set': {'ctx.opsRepairOutcome': 'in progress after completion signal'}}],
              'FAILED': [{'title': 'FAILED parent status becomes an IOException with the first message', 'source': rng(RR, 164, 172, 'case FAILED:'),
                          'set': {'ctx.opsRepairOutcome': 'failed'}},
                         {'fail': {'code': 'io-exception', 'message': "= size(vars.st.value.messages) > 0 ? vars.st.value.messages[0] : 'Repair failed'"}}]}},
          {'return': {'cmd': '= vars.cmd.value.cmd', 'status': '= vars.st.value.status'}},
      ])


# ---------------------------------------------------------------- command helpers
def command(cli, cls, summary, behavior, src_name=None, comp_id=None, extra_sources=None):
    cid = comp_id or ('nodetool-' + kebab(cls))
    srcs = [cmd_src(src_name or ('nodetool ' + cli))] + (extra_sources or [])
    comp(cid, cls, 'node-tool', summary, srcs[:1], kind='function', layer='tools')
    iface(cid, 'execute', summary, srcs, {'$ref': 'OpsNodetoolArgs'}, obj({'output': s_(default='')}), behavior)
    COMMANDS[cli] = cid
    return cid + '.execute'


def parse(set_='ALL'):
    return {'call': 'node-tool-node-tool-cmd.parse-optional-keyspace', 'as': 'ks', 'input': {'keyspace': '= input.keyspace', 'set': set_}}


def wrap(msg, only=None):
    f = {'fail': {'code': 'runtime-exception', 'message': msg, 'data': {'root_cause': '= error.message'}}}
    if only:
        return [{'if': 'error.code in %s' % json.dumps(only).replace('"', "'"), 'then': [f]}, {'fail': '= error'}]
    return [f]


def call(target, mbean_op, inp=None, title=None, on_error=None, as_=None, when=None):
    st = {'title': title or ('Invoke %s over JMX' % mbean_op), 'source': jx(mbean_op), 'call': target}
    if inp is not None:
        st['input'] = inp
    if on_error is not None:
        st['on_error'] = on_error
    if as_:
        st['as'] = as_
    if when:
        st['when'] = when
    return st


def done(out="''"):
    return {'return': {'output': '= ' + out}}


def opt(name, default):
    """CEL for an option with a default."""
    d = json.dumps(default).replace('"', "'") if not isinstance(default, bool) else ('true' if default else 'false')
    return "= '%s' in input.options ? input.options['%s'] : %s" % (name, name, d)


def arg(i, default="''"):
    return '= size(input.args) > %d ? input.args[%d] : %s' % (i, i, default)


# ---------------------------------------------------------------- flush, cleanup and the AllSSTableOpStatus family
command('flush', 'Flush', 'nodetool flush: forceKeyspaceFlush for the named keyspace (or all keyspaces); any server error is wrapped as "Error occurred during flushing".', [
    parse('ALL'),
    {'foreach': '= vars.ks.value.keyspaces', 'as': 'k', 'steps': [
        call('storage-service-mbean.force-keyspace-flush', 'StorageServiceMBean.forceKeyspaceFlush', {'keyspace': '= vars.k', 'tables': '= input.tables'},
             on_error=wrap('Error occurred during flushing'))]},
    done("'flushed ' + string(size(vars.ks.value.keyspaces)) + ' keyspace(s)'")])


def sstable_job(cli, cls, mbean_method, job, set_, mbean_input, summary, skip_local=False, check_jobs=True, wrap_msg=None):
    steps = [parse(set_), {'set': {'vars.failed': False, 'vars.out': ''}}]
    if check_jobs:
        steps += [{'call': 'storage-service-mbean.get-concurrent-compactors', 'as': 'cc'},
                  {'when': "'jobs' in input.options && input.options['jobs'] > vars.cc.value.value",
                   'title': 'checkJobs: warn when --jobs exceeds concurrent_compactors', 'source': rng(NP, 396, 401, 'private void checkJobs(PrintStream out, int jobs)'),
                   'set': {'vars.out': "= 'jobs (' + string(int(input.options['jobs'])) + ') is bigger than configured concurrent_compactors (' + string(int(vars.cc.value.value)) + ') on the host, using at most ' + string(int(vars.cc.value.value)) + ' threads; '"}}]
    body = []
    if skip_local:
        body.append({'if': "vars.k in ['system', 'system_schema']", 'then': [{'continue': True}]})
    body += [
        call('storage-service-mbean.' + kebab(mbean_method), 'StorageServiceMBean.' + mbean_method, mbean_input, as_='r',
             on_error=wrap(wrap_msg or ('Error occurred during ' + job))),
        {'title': 'NodeProbe.perform: 1 prints "Aborted", 2 marks the probe failed', 'source': rng(NP, 446, 459, 'private void perform(PrintStream out, String ks, Job job, String jobName)'),
         'if': 'vars.r.value.status_code == 1', 'then': [{'set': {'vars.out': "= vars.out + 'Aborted %s for at least one table in keyspace ' + vars.k + ', check server logs for more information. '" % job}}]},
        {'if': 'vars.r.value.status_code == 2', 'then': [{'set': {'vars.failed': True, 'vars.out': "= vars.out + 'Failed marking some sstables compacting in keyspace ' + vars.k + ', check server logs for more information. '"}}]},
    ]
    steps += [{'foreach': '= vars.ks.value.keyspaces', 'as': 'k', 'steps': body},
              {'if': 'vars.failed', 'then': [{'title': 'probe.isFailed(): nodetool failed', 'source': rng(NT, 392, 394, 'if (probe.isFailed())'),
                                              'fail': {'code': 'runtime-exception', 'message': 'nodetool failed, check server logs'}}]},
              done('vars.out')]
    return command(cli, cls, summary, steps)


sstable_job('cleanup', 'Cleanup', 'forceKeyspaceCleanup', 'cleaning up', 'NON_LOCAL_STRATEGY',
            {'keyspace': '= vars.k', 'tables': '= input.tables', 'jobs': opt('jobs', 2)},
            'nodetool cleanup: per non-local-strategy keyspace (local system keyspaces skipped) run forceKeyspaceCleanup; status 2 makes nodetool fail.',
            skip_local=True, wrap_msg='Error occurred during cleanup')
sstable_job('scrub', 'Scrub', 'scrub', 'scrubbing', 'ALL', {'keyspace': '= vars.k', 'tables': '= input.tables', 'jobs': opt('jobs', 2)},
            'nodetool scrub: scrub each keyspace (snapshot first unless --no-snapshot); status 2 makes nodetool fail.', wrap_msg='Error occurred during scrubbing')
sstable_job('verify', 'Verify', 'verify', 'verifying', 'ALL', {'keyspace': '= vars.k', 'tables': '= input.tables', 'jobs': 0},
            'nodetool verify: verify SSTable checksums (extended with -e) per keyspace.', check_jobs=False, wrap_msg='Error occurred during verifying')
sstable_job('upgradesstables', 'UpgradeSSTable', 'upgradeSSTables', 'upgrading sstables', 'ALL', {'keyspace': '= vars.k', 'tables': '= input.tables', 'jobs': opt('jobs', 2)},
            'nodetool upgradesstables: rewrite SSTables not on the current format version.', wrap_msg='Error occurred during enabling auto-compaction')
sstable_job('recompress_sstables', 'RecompressSSTables', 'recompressSSTables', 'recompressing sstables', 'ALL', {'keyspace': '= vars.k', 'tables': '= input.tables', 'jobs': opt('jobs', 2)},
            'nodetool recompress_sstables: rewrite SSTables whose compression differs from the table settings.', wrap_msg='Error occurred during enabling auto-compaction')
command('garbagecollect', 'GarbageCollect', 'nodetool garbagecollect: remove deleted data from SSTables per keyspace; any non-zero status marks the probe failed.', [
    parse('ALL'), {'set': {'vars.failed': False}},
    {'foreach': '= vars.ks.value.keyspaces', 'as': 'k', 'steps': [
        call('storage-service-mbean.garbage-collect', 'StorageServiceMBean.garbageCollect',
             {'keyspace': '= vars.k', 'tables': '= input.tables', 'jobs': opt('jobs', 2), 'tombstone_option': opt('granularity', 'ROW')}, as_='r',
             on_error=wrap('Error occurred during garbage collection')),
        {'when': 'vars.r.value.status_code != 0', 'title': 'Any non-zero status fails the probe', 'source': rng(NP, 461, 468, 'public void garbageCollect(PrintStream out'),
         'set': {'vars.failed': True}}]},
    {'if': 'vars.failed', 'then': [{'fail': {'code': 'runtime-exception', 'message': 'nodetool failed, check server logs'}}]}, done()])
command('relocatesstables', 'RelocateSSTables', 'nodetool relocatesstables: move SSTables to the correct disk for their token range.', [
    parse('ALL'),
    {'foreach': '= vars.ks.value.keyspaces', 'as': 'k', 'steps': [
        call('storage-service-mbean.relocate-sstables', 'StorageServiceMBean.relocateSSTables', {'keyspace': '= vars.k', 'tables': '= input.tables', 'jobs': opt('jobs', 2)},
             on_error=wrap('Got error while relocating'))]}, done()])
command('compact', 'Compact', 'nodetool compact: user-defined compaction of named files, or major compaction of a keyspace (optionally a token range or one partition key).', [
    {'if': "'user-defined' in input.options && input.options['user-defined']", 'then': [
        {'if': "'split-output' in input.options && input.options['split-output']", 'then': [
            {'fail': {'code': 'runtime-exception', 'message': 'Invalid option combination: Can not use split-output here'}}]},
        call('compaction-manager.force-user-defined-compaction', 'CompactionManagerMBean.forceUserDefinedCompaction', {'replica': '= self', 'data_files': "= input.args.join(',')"},
             on_error=wrap('Error occurred during user defined compaction')),
        done()]},
    parse('ALL'),
    {'foreach': '= vars.ks.value.keyspaces', 'as': 'k', 'steps': [
        {'if': "'start-token' in input.options", 'then': [
            call('storage-service-mbean.force-keyspace-compaction-for-token-range', 'StorageServiceMBean.forceKeyspaceCompactionForTokenRange',
                 {'keyspace': '= vars.k', 'tables': '= input.tables', 'start_token': "= input.options['start-token']", 'end_token': opt('end-token', '')},
                 on_error=wrap('Error occurred during compaction'))], 'else': [
            {'if': "'partition' in input.options", 'then': [
                call('storage-service-mbean.force-keyspace-compaction-for-partition-key', 'StorageServiceMBean.forceKeyspaceCompactionForPartitionKey',
                     {'keyspace': '= vars.k', 'tables': '= input.tables', 'partition_key': "= input.options['partition']"}, on_error=wrap('Error occurred during compaction'))], 'else': [
                call('storage-service-mbean.force-keyspace-compaction', 'StorageServiceMBean.forceKeyspaceCompaction',
                     {'keyspace': '= vars.k', 'tables': '= input.tables', 'split_output': opt('split-output', False)}, on_error=wrap('Error occurred during compaction'))]}]}]},
    done()])
command('forcecompact', 'ForceCompact', 'nodetool forcecompact: compact the given partition keys of one table ignoring gc_grace (needs keyspace, table and keys).', [
    {'if': 'size(input.args) < 3', 'then': [{'title': 'checkArgument', 'source': at(ND + 'ForceCompact.java', 42, 'checkArgument(args.size() >= 3'),
                                            'fail': {'code': 'illegal-argument-exception', 'message': 'forcecompact requires keyspace, table and keys args'}}]},
    call('storage-service-mbean.force-compaction-keys-ignoring-gc-grace', 'StorageServiceMBean.forceCompactionKeysIgnoringGcGrace',
         {'keyspace': '= input.args[0]', 'table': '= input.args[1]', 'keys': '= input.args.slice(2, size(input.args))'}, on_error=wrap('Error occurred during compaction keys')),
    done()])
command('stop', 'Stop', 'nodetool stop: stop active compactions of a type (COMPACTION, CLEANUP, ...) or one compaction by id.', [
    {'if': "'id' in input.options", 'then': [
        call('compaction-manager.stop-compaction-by-id', 'CompactionManagerMBean.stopCompactionById', {'compaction_id': "= input.options['id']"})], 'else': [
        call('compaction-manager.stop-compaction', 'CompactionManagerMBean.stopCompaction', {'type': arg(0, "'COMPACTION'")})]},
    done()])
for cli, cls, m, msg in [('disableautocompaction', 'DisableAutoCompaction', 'disableAutoCompaction', 'Error occurred during disabling auto-compaction'),
                         ('enableautocompaction', 'EnableAutoCompaction', 'enableAutoCompaction', 'Error occurred during enabling auto-compaction')]:
    command(cli, cls, 'nodetool %s: %s for the named tables of each keyspace.' % (cli, m), [
        parse('ALL'),
        {'foreach': '= vars.ks.value.keyspaces', 'as': 'k', 'steps': [
            call('storage-service-mbean.' + kebab(m), 'StorageServiceMBean.' + m, {'keyspace': '= vars.k', 'tables': '= input.tables'}, on_error=wrap(msg))]},
        done()])

# ---------------------------------------------------------------- snapshots
command('snapshot', 'Snapshot', 'nodetool snapshot: validate the tag and options, then takeSnapshot for keyspaces (or a keyspace.table list); IOExceptions become "Error during taking a snapshot".', [
    {'set': {'vars.tag': opt('tag', '1730284800000'), 'vars.kt': opt('kt-list', '')}},
    {'if': "vars.tag.contains(':')", 'then': [
        {'title': 'Snapshot name cannot contain the path separator', 'source': rng(ND + 'Snapshot.java', 77, 80, 'File.pathSeparator()'),
         'fail': {'code': 'runtime-exception', 'message': 'Error during taking a snapshot', 'data': {'root_cause': 'Snapshot name cannot contain :'}}}]},
    {'if': "vars.kt != '' && input.keyspace != ''", 'then': [
        {'title': 'kt-list and keyspaces are exclusive', 'source': rng(ND + 'Snapshot.java', 86, 91, 'if (keyspaces.isEmpty() && null == table)'),
         'fail': {'code': 'runtime-exception', 'message': 'Error during taking a snapshot',
                  'data': {'root_cause': 'When specifying the Keyspace table list (using -kt,--kt-list,-kc,--kc.list), you must not also specify keyspaces to snapshot'}}}]},
    call('storage-service.take-snapshot', 'StorageServiceMBean.takeSnapshot',
         {'tag': '= vars.tag', 'skip_flush': opt('skip-flush', False), 'ttl_seconds': opt('ttl', 0),
          'entities': "= vars.kt != '' ? vars.kt.split(',') : (input.keyspace != '' ? [input.keyspace] + input.args : [])"},
         on_error=[{'if': "error.code == 'io-exception'", 'then': [
             {'fail': {'code': 'runtime-exception', 'message': 'Error during taking a snapshot', 'data': {'root_cause': '= error.message'}}}]}, {'fail': '= error'}]),
    done("'Snapshot directory: ' + vars.tag")])
command('clearsnapshot', 'ClearSnapshot', 'nodetool clearsnapshot: require a tag or --all (but not both), then clearSnapshot on the keyspaces.', [
    {'if': "!('t' in input.options) && !('all' in input.options && input.options['all'])", 'then': [
        {'title': 'Specify snapshot name or --all', 'source': rng(ND + 'ClearSnapshot.java', 61, 66, 'Specify snapshot name or --all'),
         'fail': {'code': 'illegal-argument-exception', 'message': 'Specify snapshot name or --all'}}]},
    {'if': "'t' in input.options && 'all' in input.options && input.options['all']", 'then': [
        {'fail': {'code': 'illegal-argument-exception', 'message': 'Specify only one of snapshot name or --all'}}]},
    call('storage-service.clear-snapshot', 'StorageServiceMBean.clearSnapshot',
         {'tag': opt('t', ''), 'keyspaces': "= input.keyspace != '' ? [input.keyspace] + input.args : []", 'older_than_seconds': 0}, on_error=wrap('Error during clearing snapshots')),
    done()])

# ---------------------------------------------------------------- repair
command('repair', 'Repair', 'nodetool repair: for each non-local-strategy keyspace (system_distributed only when named) run a RepairRunner; any failure is wrapped as "Error occurred during repair".', [
    {'if': "('pr' in input.options && input.options['pr']) && ('dc' in input.options || 'hosts' in input.options)", 'then': [
        {'title': 'Primary range repair must run on all nodes', 'source': rng(ND + 'Repair.java', 137, 138, 'if (primaryRange && '),
         'fail': {'code': 'runtime-exception', 'message': 'Primary range repair should be performed on all nodes in the cluster.'}}]},
    parse('NON_LOCAL_STRATEGY'),
    {'title': 'createOptions: RepairOption keys; incremental unless --full', 'source': rng(ND + 'Repair.java', 168, 204, 'private Map<String, String> createOptions'),
     'set': {'vars.opts': {
         'parallelism': "= 'seq' in input.options && input.options['seq'] ? 'sequential' : ('dcpar' in input.options && input.options['dcpar'] ? 'dc_parallel' : 'parallel')",
         'primaryRange': "= 'pr' in input.options && input.options['pr'] ? 'true' : 'false'",
         'incremental': "= 'full' in input.options && input.options['full'] ? 'false' : 'true'",
         'jobThreads': '1', 'trace': 'false', 'columnFamilies': "= input.tables.join(',')", 'pullRepair': 'false',
         'forceRepair': "= 'force' in input.options && input.options['force'] ? 'true' : 'false'", 'previewKind': 'NONE', 'optimiseStreams': 'false',
         'ignoreUnreplicatedKeyspaces': 'false', 'repairPaxos': 'true', 'paxosOnly': 'false'}}},
    {'set': {'vars.runs': 0}},
    {'foreach': '= vars.ks.value.keyspaces', 'as': 'k', 'steps': [
        {'if': "input.keyspace == '' && vars.k == 'system_distributed'", 'then': [
            {'title': 'system_distributed is repaired only when named (CASSANDRA-9621)', 'source': rng(ND + 'Repair.java', 142, 144, 'ONLY_EXPLICITLY_REPAIRED.contains(keyspace)'), 'continue': True}]},
        {'title': 'NodeProbe.repairAsync registers a RepairRunner as notification listener and runs it', 'source': rng(NP, 520, 545, 'public void repairAsync(final PrintStream out'),
         'call': 'repair-runner.run', 'input': {'keyspace': '= vars.k', 'options': '= vars.opts'}, 'on_error': wrap('Error occurred during repair')},
        {'set': {'vars.runs': '= vars.runs + 1'}}]},
    {'set': {'ctx.opsRepairRuns': '= vars.runs'}},
    done("'repaired ' + string(vars.runs) + ' keyspace(s)'")])
command('repair_admin cancel', 'RepairAdmin.CancelCmd', 'nodetool repair_admin cancel: fail an incremental repair session by id.', [
    call('active-repair-service-mbean.fail-session', 'ActiveRepairServiceMBean.failSession', {'session': arg(0), 'force': opt('force', False)}), done()],
    src_name='nodetool repair_admin cancel', comp_id='nodetool-repair-admin-cancel-cmd')
command('repair_admin cleanup', 'RepairAdmin.CleanupDataCmd', 'nodetool repair_admin cleanup: clean up pending incremental repair data.', [
    call('active-repair-service-mbean.cleanup-pending', 'ActiveRepairServiceMBean.cleanupPending', {'keyspace': "= input.keyspace", 'ranges': '', 'force': opt('force', False)}), done()],
    src_name='nodetool repair_admin cleanup', comp_id='nodetool-repair-admin-cleanup-data-cmd')

# ---------------------------------------------------------------- lifecycle
command('drain', 'Drain', 'nodetool drain: StorageService.drain; IOException, InterruptedException and ExecutionException are wrapped.', [
    call('storage-service.drain', 'StorageServiceMBean.drain', on_error=wrap('Error occurred during flushing', ['io-exception', 'interrupted-exception', 'execution-exception'])),
    done()])
command('decommission', 'Decommission', 'nodetool decommission: no-op when already decommissioning or decommissioned; UnsupportedOperationException becomes IllegalStateException.', [
    {'title': 'probe.getStorageService().isDecommissioning()', 'source': jx('StorageServiceMBean.isDecommissioning'), 'call': 'storage-service.is-decommissioning', 'as': 'dec'},
    {'choice': 'decommissioning', 'default': "= vars.dec.value.decommissioning ? 'yes' : 'no'", 'options': {
        'no': [], 'yes': [{'title': 'Already decommissioning: print and return', 'source': rng(ND + 'Decommission.java', 40, 44, 'isDecommissioning()'), 'return': {'output': 'This node is still decommissioning.'}}]}},
    {'title': 'getBootstrapState()', 'source': jx('StorageServiceMBean.getBootstrapState'), 'call': 'storage-service.get-bootstrap-state', 'as': 'bs'},
    {'choice': 'bootstrap_state', 'default': "= vars.bs.value.state == 'DECOMMISSIONED' ? 'decommissioned' : 'other'", 'options': {
        'other': [], 'decommissioned': [{'title': 'Already decommissioned', 'source': rng(ND + 'Decommission.java', 45, 49, 'DECOMMISSIONED'), 'return': {'output': 'Node was already decommissioned.'}}]}},
    call('storage-service.decommission', 'StorageServiceMBean.decommission', {'force': opt('force', False)}, on_error=[
        {'if': "error.code == 'unsupported-operation-exception'", 'then': [
            {'title': 'Unsupported operation', 'source': rng(ND + 'Decommission.java', 54, 57, 'catch (UnsupportedOperationException e)'),
             'fail': {'code': 'illegal-state-exception', 'message': "= 'Unsupported operation: ' + error.message"}}]},
        {'if': "error.code == 'interrupted-exception'", 'then': [{'fail': {'code': 'runtime-exception', 'message': 'Error decommissioning node', 'data': {'root_cause': '= error.message'}}}]},
        {'fail': '= error'}]),
    done()])
command('move', 'Move', 'nodetool move: move this node to a new token; IOException becomes "Error during moving node".', [
    call('storage-service.move', 'StorageServiceMBean.move', {'new_token': '= int(input.args[0])'}, on_error=wrap('Error during moving node', ['io-exception'])), done()])
command('removenode', 'RemoveNode', 'nodetool removenode status|force|<host id>: print the removal status, force completion, or remove a dead node.', [
    {'if': "size(input.args) > 0 && input.args[0] == 'status'", 'then': [done("'RemovalStatus: No removals in process.'")]},
    {'if': "size(input.args) > 0 && input.args[0] == 'force'", 'then': [
        call('storage-service.force-remove-completion', 'StorageServiceMBean.forceRemoveCompletion'), done()]},
    call('storage-service.remove-node', 'StorageServiceMBean.removeNode', {'host_id': arg(0)}), done()])
command('join', 'Join', 'nodetool join: refuse if already joined or still bootstrapping, else joinRing.', [
    {'title': 'isJoined()', 'source': jx('StorageServiceMBean.isJoined'), 'call': 'storage-service.is-joined', 'as': 'j'},
    {'choice': 'joined', 'default': "= vars.j.value.joined ? 'yes' : 'no'", 'options': {'no': [], 'yes': [
        {'title': 'checkState', 'source': at(ND + 'Join.java', 34, 'checkState(!probe.isJoined()'),
         'fail': {'code': 'illegal-state-exception', 'message': 'This node has already joined the ring.'}}]}},
    {'title': 'isBootstrapMode()', 'source': jx('StorageServiceMBean.isBootstrapMode'), 'call': 'storage-service.is-bootstrap-mode', 'as': 'b'},
    {'choice': 'bootstrap_mode', 'default': "= vars.b.value.bootstrap_mode ? 'yes' : 'no'", 'options': {'no': [], 'yes': [
        {'fail': {'code': 'illegal-state-exception', 'message': 'Cannot join the ring until bootstrap completes'}}]}},
    call('storage-service.join-ring', 'StorageServiceMBean.joinRing', on_error=wrap('Error during joining the ring', ['io-exception'])), done()])
command('rebuild', 'Rebuild', 'nodetool rebuild [source dc]: tokens need a keyspace; then StorageService.rebuild.', [
    {'if': "'tokens' in input.options && !('keyspace' in input.options)", 'then': [
        {'title': 'Tokens without keyspace', 'source': at(ND + 'Rebuild.java', 60, 'Cannot specify tokens without keyspace.'),
         'fail': {'code': 'illegal-argument-exception', 'message': 'Cannot specify tokens without keyspace.'}}]},
    call('storage-service.rebuild', 'StorageServiceMBean.rebuild', {'source_dc': arg(0), 'keyspace': opt('keyspace', ''), 'tokens': opt('tokens', ''),
                                                                          'specific_sources': opt('sources', ''), 'exclude_local_dc': opt('exclude-local-dc', False)}), done()])
command('bootstrap resume', 'BootstrapResume', 'nodetool bootstrap resume: disabled unless cassandra.reset_bootstrap_progress is explicitly false or --force is given.', [
    {'if': "!('force' in input.options && input.options['force'])", 'then': [
        {'title': 'Disabled by default (reset_bootstrap_progress not set)', 'source': rng(ND + 'BootstrapResume.java', 44, 45, 'RESET_BOOTSTRAP_PROGRESS'),
         'fail': {'code': 'runtime-exception', 'message': "'nodetool bootstrap resume' is disabled."}}]},
    call('storage-service.resume-bootstrap', 'StorageServiceMBean.resumeBootstrap'), done()], comp_id='nodetool-bootstrap-resume')
command('stopdaemon', 'StopDaemon', 'nodetool stopdaemon: StorageService.stopDaemon.', [call('storage-service-mbean.stop-daemon', 'StorageServiceMBean.stopDaemon'), done("'Cassandra has shutdown.'")])
command('assassinate', 'Assassinate', 'nodetool assassinate <ip>: forcefully remove an endpoint from gossip (Gossiper.assassinateEndpoint).', [
    call('gossiper.assassinate-endpoint', 'GossiperMBean.assassinateEndpoint', {'address': arg(0)}, on_error=wrap('java.net.UnknownHostException', ['unknown-host-exception'])), done()])
command('reloadseeds', 'ReloadSeeds', 'nodetool reloadseeds: Gossiper.reloadSeeds re-reads the seed provider.', [
    call('gossiper.reload-seeds', 'GossiperMBean.reloadSeeds', as_='s'), done("'Updated seed node IP list, excluding the current node\\'s IP: ' + vars.s.value.seeds.join(' ')")])

# ---------------------------------------------------------------- transports and gossip
for cli, cls, target, mop, inp in [
    ('disablebinary', 'DisableBinary', 'storage-service-mbean.stop-native-transport', 'StorageServiceMBean.stopNativeTransport', {'force': opt('force', False)}),
    ('enablebinary', 'EnableBinary', 'storage-service-mbean.start-native-transport', 'StorageServiceMBean.startNativeTransport', None),
    ('disablegossip', 'DisableGossip', 'storage-service.stop-gossiping', 'StorageServiceMBean.stopGossiping', None),
    ('enablegossip', 'EnableGossip', 'storage-service.start-gossiping', 'StorageServiceMBean.startGossiping', None),
    ('disableoldprotocolversions', 'DisableOldProtocolVersions', 'storage-service-mbean.disable-native-transport-old-protocol-versions', 'StorageServiceMBean.disableNativeTransportOldProtocolVersions', None),
    ('enableoldprotocolversions', 'EnableOldProtocolVersions', 'storage-service-mbean.enable-native-transport-old-protocol-versions', 'StorageServiceMBean.enableNativeTransportOldProtocolVersions', None),
    ('disablebackup', 'DisableBackup', 'storage-service-mbean.set-incremental-backups-enabled', 'StorageServiceMBean.setIncrementalBackupsEnabled', {'value': False}),
    ('enablebackup', 'EnableBackup', 'storage-service-mbean.set-incremental-backups-enabled', 'StorageServiceMBean.setIncrementalBackupsEnabled', {'value': True}),
    ('disableauditlog', 'DisableAuditLog', 'storage-service-mbean.disable-audit-log', 'StorageServiceMBean.disableAuditLog', None),
    ('disablefullquerylog', 'DisableFullQueryLog', 'storage-service-mbean.stop-full-query-logger', 'StorageServiceMBean.stopFullQueryLogger', None),
    ('resetfullquerylog', 'ResetFullQueryLog', 'storage-service-mbean.reset-full-query-logger', 'StorageServiceMBean.resetFullQueryLogger', None),
    ('reloadlocalschema', 'ReloadLocalSchema', 'storage-service-mbean.reload-local-schema', 'StorageServiceMBean.reloadLocalSchema', None),
    ('refreshsizeestimates', 'RefreshSizeEstimates', 'storage-service-mbean.refresh-size-estimates', 'StorageServiceMBean.refreshSizeEstimates', None),
    ('reloadtriggers', 'ReloadTriggers', 'storage-proxy-mbean.reload-trigger-classes', 'StorageProxyMBean.reloadTriggerClasses', None),
    ('disablehandoff', 'DisableHandoff', 'storage-proxy-mbean.set-hinted-handoff-enabled', 'StorageProxyMBean.setHintedHandoffEnabled', {'value': False}),
    ('enablehandoff', 'EnableHandoff', 'storage-proxy-mbean.set-hinted-handoff-enabled', 'StorageProxyMBean.setHintedHandoffEnabled', {'value': True}),
    ('pausehandoff', 'PauseHandoff', 'hints-service.pause-dispatch', 'HintsServiceMBean.pauseDispatch', None),
    ('resumehandoff', 'ResumeHandoff', 'hints-service.resume-dispatch', 'HintsServiceMBean.resumeDispatch', None),
    ('invalidatekeycache', 'InvalidateKeyCache', 'cache-service-mbean.invalidate-key-cache', 'CacheServiceMBean.invalidateKeyCache', None),
    ('invalidaterowcache', 'InvalidateRowCache', 'cache-service-mbean.invalidate-row-cache', 'CacheServiceMBean.invalidateRowCache', None),
    ('invalidatecountercache', 'InvalidateCounterCache', 'cache-service-mbean.invalidate-counter-cache', 'CacheServiceMBean.invalidateCounterCache', None),
    ('reloadcidrgroupscache', 'ReloadCIDRGroupsCache', 'cidr-groups-mapping-manager.load-cidr-groups-cache', 'CIDRGroupsMappingManagerMBean.loadCidrGroupsCache', None),
    ('reloadssl', 'ReloadSslCertificates', 'messaging-service-mbean-impl.reload-ssl-certificates', 'MessagingServiceMBean.reloadSslCertificates', None),
]:
    srcname = 'nodetool ' + cli
    command(cli, cls, 'nodetool %s: invoke %s.' % (cli, mop.split('.')[1]), [call(target, mop, inp), done()], src_name=srcname)
command('resetlocalschema', 'ResetLocalSchema', 'nodetool resetlocalschema: Schema.resetLocalSchema; IOException wrapped as RuntimeException.', [
    call('storage-service-mbean.reset-local-schema', 'StorageServiceMBean.resetLocalSchema', on_error=wrap('java.io.IOException', ['io-exception'])), done()])
command('replaybatchlog', 'ReplayBatchlog', 'nodetool replaybatchlog: BatchlogManager.forceBatchlogReplay and wait; IOException becomes IOError.', [
    call('batchlog-manager.force-batchlog-replay', 'BatchlogManagerMBean.forceBatchlogReplay', {'replica': '= self'},
         on_error=[{'if': "error.code == 'io-exception'", 'then': [{'fail': {'code': 'io-error', 'message': '= error.message'}}]}, {'fail': '= error'}]), done()])
command('truncatehints', 'TruncateHints', 'nodetool truncatehints [endpoint]: delete all hints, or the hints for one endpoint.', [
    {'if': 'size(input.args) == 0', 'then': [call('hints-service.delete-all-hints', 'HintsServiceMBean.deleteAllHints', {'holder': '= self'}), done()]},
    call('hints-service.delete-all-hints-for-endpoint', 'HintsServiceMBean.deleteAllHintsForEndpoint', {'address': '= input.args[0]', 'holder': '= self'}), done()])
for cli, cls, m in [('disablehintsfordc', 'DisableHintsForDC', 'disableHintsForDC'), ('enablehintsfordc', 'EnableHintsForDC', 'enableHintsForDC')]:
    command(cli, cls, 'nodetool %s <dc>: exactly one data center, then StorageProxy.%s.' % (cli, m), [
        {'if': 'size(input.args) != 1', 'then': [{'title': 'checkArgument', 'source': at(ND + cls + '.java', 38, 'checkArgument(args.size() == 1'),
                                                  'fail': {'code': 'illegal-argument-exception', 'message': cli + ' requires exactly one data center'}}]},
        call('storage-proxy-mbean.' + kebab(m), 'StorageProxyMBean.' + m, {'dc': '= input.args[0]'}), done()])

# ---------------------------------------------------------------- auth caches and CIDR
AUTH_CACHES = [('invalidatecredentialscache', 'InvalidateCredentialsCache', 'CredentialsCache', 'PasswordAuthenticator.CredentialsCacheMBean.invalidateCredentials'),
               ('invalidatejmxpermissionscache', 'InvalidateJmxPermissionsCache', 'JmxPermissionsCache', 'AuthorizationProxy.JmxPermissionsCacheMBean.invalidatePermissions'),
               ('invalidatenetworkpermissionscache', 'InvalidateNetworkPermissionsCache', 'NetworkPermissionsCache', 'NetworkPermissionsCacheMBean.invalidateNetworkPermissions'),
               ('invalidatepermissionscache', 'InvalidatePermissionsCache', 'PermissionsCache', 'PermissionsCacheMBean.invalidatePermissions'),
               ('invalidaterolescache', 'InvalidateRolesCache', 'RolesCache', 'RolesCacheMBean.invalidateRoles')]
for cli, cls, cache, mop in AUTH_CACHES:
    command(cli, cls, 'nodetool %s [roles...]: invalidate the whole %s, or the entries of the given roles.' % (cli, cache), [
        {'if': 'size(input.args) == 0', 'then': [
            call('auth-cache.invalidate', 'AuthCacheMBean.invalidate', {'cache': cache, 'key': ''}, title='AuthCacheMBean.invalidate(): rebuild the cache'), done()]},
        {'foreach': '= input.args', 'as': 'role', 'steps': [call('auth-cache.invalidate', mop, {'cache': cache, 'key': '= vars.role'})]}, done()])
command('invalidatecidrpermissionscache', 'InvalidateCIDRPermissionsCache', 'nodetool invalidatecidrpermissionscache [roles...]: invalidate CIDR permissions for roles (all when none).', [
    call('cidr-permissions-manager.invalidate-cidr-permissions-cache', 'CIDRPermissionsManagerMBean.invalidateCidrPermissionsCache', {'role': arg(0)}), done()])
command('updatecidrgroup', 'UpdateCIDRGroup', 'nodetool updatecidrgroup <group> <cidr>...: needs a group and at least one CIDR.', [
    {'if': 'size(input.args) <= 1', 'then': [{'title': 'checkArgument', 'source': at(ND + 'UpdateCIDRGroup.java', 43, 'checkArgument(args.size() > 1'),
                                              'fail': {'code': 'illegal-argument-exception', 'message': 'updatecidrgroup command requires a cidr group name and atleast one CIDR'}}]},
    call('cidr-groups-mapping-manager.update-cidr-group', 'CIDRGroupsMappingManagerMBean.updateCidrGroup', {'group': '= input.args[0]', 'cidrs': '= input.args.slice(1, size(input.args))'},
         on_error=wrap('CIDR update failed')), done()])
command('dropcidrgroup', 'DropCIDRGroup', 'nodetool dropcidrgroup <group>: refuses an unknown group (RuntimeException from the server).', [
    {'if': 'size(input.args) != 1', 'then': [{'title': 'checkArgument', 'source': at(ND + 'DropCIDRGroup.java', 43, 'checkArgument(args.size() == 1'),
                                              'fail': {'code': 'illegal-argument-exception', 'message': 'dropcidrgroup command requires a cidr group name'}}]},
    call('cidr-groups-mapping-manager.drop-cidr-group', 'CIDRGroupsMappingManagerMBean.dropCidrGroup', {'group': '= input.args[0]'}), done()])

# ---------------------------------------------------------------- tables: import, refresh, index, thresholds, repaired state
command('import', 'Import', 'nodetool import <keyspace> <table> <dir>...: importNewSSTables on the table\'s ColumnFamilyStore MBean; lists directories that failed.', [
    {'if': 'size(input.args) < 3', 'then': [{'title': 'checkArgument', 'source': at(ND + 'Import.java', 96, 'checkArgument(args.size() >= 3'),
                                            'fail': {'code': 'illegal-argument-exception', 'message': 'import requires keyspace, table name and directories'}}]},
    call('column-family-store.import-new-sstables', 'ColumnFamilyStoreMBean.importNewSSTables', {'keyspace': '= input.args[0]', 'table': '= input.args[1]', 'src_paths': '= input.args.slice(2, size(input.args))'}, as_='imp'),
    done("size(vars.imp.value.failed_directories) > 0 ? 'Some directories failed to import, check server logs for details: ' + vars.imp.value.failed_directories.join(', ') : ''")])
command('refresh', 'Refresh', 'nodetool refresh <keyspace> <table>: deprecated loadNewSSTables.', [
    {'if': 'size(input.args) != 2', 'then': [{'title': 'checkArgument', 'source': at(ND + 'Refresh.java', 40, 'checkArgument(args.size() == 2'),
                                             'fail': {'code': 'illegal-argument-exception', 'message': 'refresh requires ks and cf args'}}]},
    call('storage-service-mbean.load-new-sstables', 'StorageServiceMBean.loadNewSSTables', {'keyspace': '= input.args[0]', 'table': '= input.args[1]'}), done()])
command('rebuild_index', 'RebuildIndex', 'nodetool rebuild_index <ks> <cf> <idx>...: rebuild secondary indexes.', [
    {'if': 'size(input.args) < 3', 'then': [{'title': 'checkArgument', 'source': at(ND + 'RebuildIndex.java', 40, 'checkArgument(args.size() >= 3'),
                                            'fail': {'code': 'illegal-argument-exception', 'message': 'rebuild_index requires ks, cf and idx args'}}]},
    call('storage-service-mbean.rebuild-secondary-index', 'StorageServiceMBean.rebuildSecondaryIndex', {'keyspace': '= input.args[0]', 'table': '= input.args[1]', 'indexes': '= input.args.slice(2, size(input.args))'}), done()])
command('setcompactionthreshold', 'SetCompactionThreshold', 'nodetool setcompactionthreshold <ks> <cf> <min> <max>: validate thresholds client side, then set them on the table.', [
    {'if': 'size(input.args) != 4', 'then': [{'fail': {'code': 'illegal-argument-exception', 'message': 'setcompactionthreshold requires ks, cf, min, and max threshold args.'}}]},
    {'set': {'vars.min': '= int(input.args[2])', 'vars.max': '= int(input.args[3])'}},
    {'title': 'Client-side checks', 'source': rng(ND + 'SetCompactionThreshold.java', 44, 46, 'checkArgument(minthreshold >= 0 && maxthreshold >= 0'),
     'if': 'vars.min < 0 || vars.max < 0', 'then': [{'fail': {'code': 'illegal-argument-exception', 'message': 'Thresholds must be positive integers'}}]},
    {'if': 'vars.min > vars.max', 'then': [{'fail': {'code': 'illegal-argument-exception', 'message': 'Min threshold cannot be greater than max.'}}]},
    {'if': 'vars.min < 2 && vars.max != 0', 'then': [{'fail': {'code': 'illegal-argument-exception', 'message': 'Min threshold must be at least 2'}}]},
    call('column-family-store.set-compaction-thresholds', 'ColumnFamilyStoreMBean.setCompactionThresholds', {'keyspace': '= input.args[0]', 'table': '= input.args[1]', 'min': '= vars.min', 'max': '= vars.max'}),
    done()])
command('sstablerepairedset', 'SSTableRepairedSet', 'nodetool sstablerepairedset: mark (or preview) the SSTables of tables as repaired or unrepaired.', [
    call('storage-service-mbean.mutate-sstable-repaired-state', 'StorageServiceMBean.mutateSSTableRepairedState',
         {'keyspace': '= input.keyspace', 'tables': '= input.tables', 'repaired': opt('is-repaired', True), 'preview': "= !('really-set' in input.options && input.options['really-set'])"}), done()])

# ---------------------------------------------------------------- audit and FQL
command('enableauditlog', 'EnableAuditLog', 'nodetool enableauditlog: validate --blocking, then StorageService.enableAuditLog with the filters given.', [
    {'if': "'blocking' in input.options && !(input.options['blocking'] in ['true', 'false'])", 'then': [
        {'title': 'Blocking only accepts true or false', 'source': at(ND + 'EnableAuditLog.java', 80, 'Blocking only accepts'),
         'fail': {'code': 'illegal-argument-exception', 'message': "= 'Invalid [' + input.options['blocking'] + ']. Blocking only accepts \\'true\\' or \\'false\\'.'"}}]},
    call('storage-service-mbean.enable-audit-log', 'StorageServiceMBean.enableAuditLog',
         {'logger': opt('logger', 'BinAuditLogger'), 'included_keyspaces': "= 'included-keyspaces' in input.options ? input.options['included-keyspaces'].split(',') : []",
          'excluded_keyspaces': "= 'excluded-keyspaces' in input.options ? input.options['excluded-keyspaces'].split(',') : ['system', 'system_schema', 'system_virtual_schema']",
          'included_categories': "= 'included-categories' in input.options ? input.options['included-categories'].split(',') : []",
          'excluded_categories': "= 'excluded-categories' in input.options ? input.options['excluded-categories'].split(',') : []",
          'included_users': "= 'included-users' in input.options ? input.options['included-users'].split(',') : []",
          'excluded_users': "= 'excluded-users' in input.options ? input.options['excluded-users'].split(',') : []",
          'archive_command': opt('archive-command', '')}), done()])
command('enablefullquerylog', 'EnableFullQueryLog', 'nodetool enablefullquerylog: validate --blocking, then StorageService.enableFullQueryLogger (path from --path or full_query_logging_options.log_dir).', [
    {'if': "'blocking' in input.options && !(input.options['blocking'] in ['true', 'false'])", 'then': [
        {'title': 'Blocking only accepts true or false', 'source': at(ND + 'EnableFullQueryLog.java', 59, 'Blocking only accepts'),
         'fail': {'code': 'illegal-argument-exception', 'message': "= 'Invalid [' + input.options['blocking'] + ']. Blocking only accepts \\'true\\' or \\'false\\'.'"}}]},
    call('storage-service-mbean.enable-full-query-logger', 'StorageServiceMBean.enableFullQueryLogger',
         {'path': opt('path', ''), 'roll_cycle': opt('roll-cycle', 'HOURLY'), 'blocking': "= 'blocking' in input.options ? input.options['blocking'] == 'true' : true", 'archive_command': opt('archive-command', '')}),
    done()])

# ---------------------------------------------------------------- runtime config setters
def set_cmd(cli, cls, target, mop, inp, pre=None, summary=None):
    return command(cli, cls, summary or ('nodetool %s: %s.' % (cli, mop.split('.')[-1])), list(pre or []) + [call(target, mop, inp), done()])


def int_arg_check(cls, line, needle, cond, msg):
    return {'if': cond, 'then': [{'title': 'checkArgument', 'source': at(ND + cls + '.java', line, needle), 'fail': {'code': 'illegal-argument-exception', 'message': msg}}]}


set_cmd('setcompactionthroughput', 'SetCompactionThroughput', 'storage-service-mbean.set-compaction-throughput-mb-per-sec', 'StorageServiceMBean.setCompactionThroughputMbPerSec', {'value': '= int(input.args[0])'})
set_cmd('setconcurrentcompactors', 'SetConcurrentCompactors', 'storage-service-mbean.set-concurrent-compactors', 'StorageServiceMBean.setConcurrentCompactors', {'value': '= int(input.args[0])'},
        pre=[int_arg_check('SetConcurrentCompactors', 35, 'checkArgument(concurrentCompactors > 0', 'int(input.args[0]) <= 0', 'concurrent_compactors should be great than 0.')])
set_cmd('setconcurrentviewbuilders', 'SetConcurrentViewBuilders', 'storage-service-mbean.set-concurrent-view-builders', 'StorageServiceMBean.setConcurrentViewBuilders', {'value': '= int(input.args[0])'},
        pre=[int_arg_check('SetConcurrentViewBuilders', 36, 'checkArgument(concurrentViewBuilders > 0', 'int(input.args[0]) <= 0', 'concurrent_view_builders should be great than 0.')])
set_cmd('setbatchlogreplaythrottle', 'SetBatchlogReplayThrottle', 'storage-service-mbean.set-batchlog-replay-throttle-in-kb', 'StorageServiceMBean.setBatchlogReplayThrottleInKB', {'value': '= int(input.args[0])'})
set_cmd('sethintedhandoffthrottlekb', 'SetHintedHandoffThrottleInKB', 'storage-service-mbean.set-hinted-handoff-throttle-in-kb', 'StorageServiceMBean.setHintedHandoffThrottleInKB', {'value': '= int(input.args[0])'})
set_cmd('setcolumnindexsize', 'SetColumnIndexSize', 'storage-service-mbean.set-column-index-size', 'StorageServiceMBean.setColumnIndexSize', {'value': '= int(input.args[0])'})
set_cmd('setsnapshotthrottle', 'SetSnapshotThrottle', 'storage-service-mbean.set-snapshot-links-per-second', 'StorageServiceMBean.setSnapshotLinksPerSecond', {'value': '= int(input.args[0])'})
set_cmd('setdefaultrf', 'SetDefaultKeyspaceRF', 'storage-service-mbean.set-default-keyspace-replication-factor', 'StorageServiceMBean.setDefaultKeyspaceReplicationFactor', {'value': '= int(input.args[0])'})
set_cmd('setmaxhintwindow', 'SetMaxHintWindow', 'storage-proxy-mbean.set-max-hint-window', 'StorageProxyMBean.setMaxHintWindow', {'value': '= int(input.args[0])'})
set_cmd('settraceprobability', 'SetTraceProbability', 'storage-service-mbean.set-trace-probability', 'StorageServiceMBean.setTraceProbability', {'value': '= double(input.args[0])'},
        pre=[int_arg_check('SetTraceProbability', 36, 'checkArgument(traceProbability >= 0 && traceProbability <= 1', 'double(input.args[0]) < 0.0 || double(input.args[0]) > 1.0', 'Trace probability must be between 0 and 1')])
set_cmd('setlogginglevel', 'SetLoggingLevel', 'storage-service-mbean.set-logging-level', 'StorageServiceMBean.setLoggingLevel', {'class_qualifier': arg(0), 'level': arg(1)})
set_cmd('setconcurrency', 'SetConcurrency', 'storage-service-mbean.set-concurrency', 'StorageServiceMBean.setConcurrency',
        {'pool': '= input.args[0]', 'core': '= size(input.args) == 3 ? int(input.args[1]) : -1', 'max': '= int(input.args[size(input.args) - 1])'},
        pre=[int_arg_check('SetConcurrency', 42, 'checkArgument(args.size() >= 2 && args.size() <= 3', 'size(input.args) < 2 || size(input.args) > 3', 'setconcurrency requires stage name, optional core pool size and maximum concurrency'),
             {'if': 'int(input.args[size(input.args) - 1]) < 0', 'then': [{'fail': {'code': 'illegal-argument-exception', 'message': 'Maximum pool size must be non-negative'}}]}])
command('settimeout', 'SetTimeout', 'nodetool settimeout <type> <ms>: dispatch to the matching DatabaseDescriptor timeout setter; an unknown type is an IllegalArgumentException.', [
    {'if': 'size(input.args) != 2', 'then': [{'title': 'checkArgument', 'source': at(ND + 'SetTimeout.java', 42, 'checkArgument(args.size() == 2'),
                                             'fail': {'code': 'illegal-argument-exception', 'message': 'Timeout type followed by value in ms (0 disables socket streaming timeout). Type should be one of (read, range, write, counterwrite, cascontention, truncate, internodeconnect, internodeuser, internodestreaminguser, misc (general rpc_timeout_in_ms))'}}]},
    {'set': {'vars.targets': {'misc': 'storage-service-mbean.set-rpc-timeout', 'read': 'storage-service-mbean.set-read-rpc-timeout', 'range': 'storage-service-mbean.set-range-rpc-timeout',
                              'write': 'storage-service-mbean.set-write-rpc-timeout', 'counterwrite': 'storage-service-mbean.set-counter-write-rpc-timeout',
                              'cascontention': 'storage-service-mbean.set-cas-contention-timeout', 'truncate': 'storage-service-mbean.set-truncate-rpc-timeout',
                              'internodeconnect': 'storage-service-mbean.set-internode-tcp-connect-timeout-in-ms', 'internodeuser': 'storage-service-mbean.set-internode-tcp-user-timeout-in-ms',
                              'internodestreaminguser': 'storage-service-mbean.set-internode-streaming-tcp-user-timeout-in-ms'}}},
    {'if': '!(input.args[0] in vars.targets)', 'then': [
        {'title': 'NodeProbe.setTimeout rejects an unknown type', 'source': cmd_src('nodetool settimeout'),
         'fail': {'code': 'illegal-argument-exception', 'message': 'Timeout type requires one of (read, range, write, counterwrite, cascontention, truncate, internodeconnect, internodeuser, internodestreaminguser, misc (general rpc_timeout_in_ms))'}}]},
    {'title': 'NodeProbe.setTimeout calls the setter for the type over JMX', 'source': cmd_src('nodetool settimeout'),
     'call': '= vars.targets[input.args[0]]', 'input': {'value': '= int(input.args[1])'},
     'targets': ['storage-service-mbean.set-rpc-timeout', 'storage-service-mbean.set-read-rpc-timeout', 'storage-service-mbean.set-range-rpc-timeout', 'storage-service-mbean.set-write-rpc-timeout',
                 'storage-service-mbean.set-counter-write-rpc-timeout', 'storage-service-mbean.set-cas-contention-timeout', 'storage-service-mbean.set-truncate-rpc-timeout',
                 'storage-service-mbean.set-internode-tcp-connect-timeout-in-ms', 'storage-service-mbean.set-internode-tcp-user-timeout-in-ms', 'storage-service-mbean.set-internode-streaming-tcp-user-timeout-in-ms'],
     'on_error': [{'if': "error.code == 'illegal-argument-exception'", 'then': [
         {'title': 'Rethrown as IllegalArgumentException', 'source': rng(ND + 'SetTimeout.java', 48, 53, 'catch (Exception e)'),
          'fail': {'code': 'illegal-argument-exception', 'message': '= error.message'}}]}, {'fail': {'code': 'illegal-argument-exception', 'message': '= error.message'}}]},
    done()])
for cli, cls, mib, mbit, ent in [('setstreamthroughput', 'SetStreamThroughput', 'setStreamThroughputMebibytesPerSec', 'setStreamThroughputMbitPerSec', 'setEntireSSTableStreamThroughputMebibytesPerSec'),
                                 ('setinterdcstreamthroughput', 'SetInterDCStreamThroughput', 'setInterDCStreamThroughputMebibytesPerSec', 'setInterDCStreamThroughputMbitPerSec', 'setEntireSSTableInterDCStreamThroughputMebibytesPerSec')]:
    command(cli, cls, 'nodetool %s <value>: megabits/s by default, MiB/s with -m, entire-SSTable throughput with -e (not both).' % cli, [
        {'if': "('entire-sstable-throughput' in input.options && input.options['entire-sstable-throughput']) && ('mib' in input.options && input.options['mib'])", 'then': [
            {'title': '-e and -m are exclusive', 'source': at(ND + cls + '.java', 45, 'You cannot use -e and -m at the same time'),
             'fail': {'code': 'illegal-argument-exception', 'message': 'You cannot use -e and -m at the same time'}}]},
        {'if': "'entire-sstable-throughput' in input.options && input.options['entire-sstable-throughput']", 'then': [
            call('storage-service-mbean.' + kebab(ent), 'StorageServiceMBean.' + ent, {'value': '= int(input.args[0])'}), done()]},
        {'if': "'mib' in input.options && input.options['mib']", 'then': [
            call('storage-service-mbean.' + kebab(mib), 'StorageServiceMBean.' + mib, {'value': '= int(input.args[0])'}), done()]},
        call('storage-service-mbean.' + kebab(mbit), 'StorageServiceMBean.' + mbit, {'value': '= int(input.args[0])'}), done()])
command('setcachecapacity', 'SetCacheCapacity', 'nodetool setcachecapacity <key> <row> <counter>: resize the three caches (MiB).', [
    {'if': 'size(input.args) != 3', 'then': [{'title': 'checkArgument', 'source': at(ND + 'SetCacheCapacity.java', 42, 'checkArgument(args.size() == 3'),
                                             'fail': {'code': 'illegal-argument-exception', 'message': 'setcachecapacity requires key-cache-capacity, row-cache-capacity, and counter-cache-capacity args.'}}]},
    call('cache-service-mbean.set-key-cache-capacity-in-mb', 'CacheServiceMBean.setKeyCacheCapacityInMB', {'capacity_mb': '= int(input.args[0])'}),
    call('cache-service-mbean.set-row-cache-capacity-in-mb', 'CacheServiceMBean.setRowCacheCapacityInMB', {'capacity_mb': '= int(input.args[1])'}),
    call('cache-service-mbean.set-counter-cache-capacity-in-mb', 'CacheServiceMBean.setCounterCacheCapacityInMB', {'capacity_mb': '= int(input.args[2])'}), done()])
command('setcachekeystosave', 'SetCacheKeysToSave', 'nodetool setcachekeystosave <key> <row> <counter>: how many keys of each cache to save.', [
    {'if': 'size(input.args) != 3', 'then': [{'title': 'checkArgument', 'source': at(ND + 'SetCacheKeysToSave.java', 42, 'checkArgument(args.size() == 3'),
                                             'fail': {'code': 'illegal-argument-exception', 'message': 'setcachekeystosave requires key-cache-keys-to-save, row-cache-keys-to-save, and counter-cache-keys-to-save args.'}}]},
    call('cache-service-mbean.set-key-cache-keys-to-save', 'CacheServiceMBean.setKeyCacheKeysToSave', {'count': '= int(input.args[0])'}),
    call('cache-service-mbean.set-row-cache-keys-to-save', 'CacheServiceMBean.setRowCacheKeysToSave', {'count': '= int(input.args[1])'}),
    call('cache-service-mbean.set-counter-cache-keys-to-save', 'CacheServiceMBean.setCounterCacheKeysToSave', {'count': '= int(input.args[2])'}), done()])

# ---------------------------------------------------------------- read-only report commands (not modeled; see notes)
READONLY = ['status', 'info', 'ring', 'describecluster', 'describering', 'tablestats', 'tpstats', 'gcstats', 'netstats', 'compactionstats', 'compactionhistory',
            'listsnapshots', 'version', 'gossipinfo', 'failuredetector', 'proxyhistograms', 'tablehistograms', 'statusautocompaction', 'statusbackup', 'statusbinary',
            'statusgossip', 'statushandoff', 'getendpoints', 'getsstables', 'getseeds', 'datapaths', 'clientstats', 'viewbuildstatus', 'listpendinghints',
            'cidrfilteringstats', 'getcidrgroupsofip', 'listcidrgroups', 'rangekeysample', 'checktokenmetadata', 'getauditlog', 'getfullquerylog',
            'getlogginglevels', 'getauthcacheconfig', 'getdefaultrf', 'getbatchlogreplaythrottle', 'getcolumnindexsize', 'getcompactionthreshold',
            'getcompactionthroughput', 'getconcurrency', 'getconcurrentcompactors', 'getconcurrentviewbuilders', 'getinterdcstreamthroughput', 'getmaxhintwindow',
            'getsnapshotthrottle', 'getstreamthroughput', 'gettimeout', 'gettraceprobability', 'profileload', 'toppartitions', 'repair_admin list',
            'repair_admin summarize-pending', 'repair_admin summarize-repaired', 'getguardrailsconfig', 'getautorepairconfig', 'autorepairstatus']

# ---------------------------------------------------------------- the dispatcher
TARGETS = sorted(set(c + '.execute' for c in COMMANDS.values()))
iface('node-tool', 'execute', 'NodeTool.execute: parse the command, connect over JMX, run it, and map exceptions to exit status 1 (bad use) or 2 (error, root cause printed).',
      [rng(NT, 96, 296, 'public int execute(String... args)'), rng(NT, 444, 464, 'private NodeProbe connect()')],
      obj({'command': s_(ex='flush', desc='the command name as typed (for example flush, repair, "repair_admin cancel")'),
           'args': {'$ref': 'OpsNodetoolArgs'}, 'host': s_(default='127.0.0.1'), 'port': i_(default=7199)}, ['command', 'args']),
      {'$ref': 'OpsNodetoolResult'},
      behavior=[
          {'if': 'input.command in state.readonly_commands', 'then': [
              {'title': 'Read-only report command (getter calls only; not modeled)', 'source': rng(NT, 98, 252, 'List<Class<? extends NodeToolCmdRunnable>> commands = newArrayList('),
               'set': {'ctx.opsExitStatus': 0}},
              {'return': {'exit_status': 0, 'output': "= 'read-only report: ' + input.command"}}]},
          {'if': '!(input.command in state.commands)', 'then': [
              {'title': 'airline: unknown command (badUse, exit 1)', 'source': rng(NT, 276, 289, 'catch (IllegalArgumentException |'), 'set': {'ctx.opsExitStatus': 1}},
              {'return': {'exit_status': 1, 'output': "= 'nodetool: Found unexpected parameters: [' + input.command + ']'"}}]},
          {'title': 'NodeToolCmd.connect: a failed JMX connection prints and exits 1', 'source': rng(NT, 444, 464, 'private NodeProbe connect()'),
           'call': 'node-probe.connect', 'input': {'host': '= input.host', 'port': '= input.port'}, 'as': 'conn', 'on_error': [
               {'set': {'ctx.opsExitStatus': 1}},
               {'return': {'exit_status': 1, 'output': "= 'nodetool: Failed to connect to \\'' + input.host + ':' + string(int(input.port)) + '\\' - ' + error.code + ': \\'' + error.message + '\\'.'"}}]},
          {'title': 'parse.run(...) -> runInternal -> execute(probe)', 'source': rng(NT, 274, 276, 'NodeToolCmdRunnable parse = parser.parse(args);'),
           'call': '= state.commands[input.command] + \'.execute\'', 'targets': TARGETS, 'input': '= input.args', 'as': 'cmd', 'on_error': [
               {'if': "error.code in ['illegal-argument-exception', 'illegal-state-exception']", 'then': [
                   {'title': 'badUse: exit 1', 'source': rng(NT, 276, 288, 'catch (IllegalArgumentException |'), 'set': {'ctx.opsExitStatus': 1, 'ctx.opsErrorCode': '= error.code'}},
                   {'return': {'exit_status': 1, 'output': "= 'nodetool: ' + error.message"}}]},
               {'title': 'Any other Throwable: print the root cause, exit 2', 'source': rng(NT, 289, 293, 'catch (Throwable throwable)'),
                'set': {'ctx.opsExitStatus': 2, 'ctx.opsErrorCode': '= error.code'}},
               {'return': {'exit_status': 2, 'output': "= 'error: ' + (error.data != null && 'root_cause' in error.data ? error.data.root_cause : error.message)"}}]},
          {'set': {'ctx.opsExitStatus': 0}},
          {'return': {'exit_status': 0, 'output': '= vars.cmd.value.output'}},
      ])
# record the command map in node-tool state
for c in DOC['components']:
    if c['id'] == 'node-tool':
        c['state']['initial']['commands'] = dict(sorted(COMMANDS.items()))
        c['state']['initial']['readonly_commands'] = READONLY

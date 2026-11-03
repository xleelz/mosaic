"""Flows and scenarios for the ops fragment."""
from gen_base import *
TR = J + 'tracing/Tracing.java'
TRACKER_KEYS = ['ks1.users']  # read-path's per-instance tracker view key
import gen_nodetool as N

A = lambda **kw: dict({'keyspace': '', 'tables': [], 'args': [], 'options': {}}, **kw)  # noqa: E731


def nt(cmd, **kw):
    return {'command': cmd, 'args': A(**kw)}


EXIT = lambda n: "result.ok && result.value.exit_status == %d" % n  # noqa: E731

# ---------------------------------------------------------------- JMX dispatcher interface (needs every jmx op id)
JMX_TARGETS = sorted(i['component'] + '.' + i['name'] for i in DOC['interfaces']
                     if i.get('kind') == 'jmx' and i['component'] in ('storage-service-mbean', 'storage-proxy-mbean', 'cache-service-mbean', 'active-repair-service-mbean'))
iface('mbean-wrapper', 'invoke-operation', 'A JMX client invoking one operation of a registered MBean through the platform MBeanServer (the path jconsole or any JMX tool uses).',
      [rng(MW := J + 'utils/MBeanWrapper.java', 173, 186, 'class PlatformMBeanWrapper implements MBeanWrapper'), rng(CD, 139, 185, 'private void maybeInitJmx()')],
      obj({'operation': s_(ex='storage-service-mbean.force-keyspace-flush', desc='the MBean operation, as <mbean component>.<operation>'), 'args': obj({}, default={})}, ['operation']),
      obj({'result': obj({})}), kind='jmx',
      behavior=[{'title': 'MBeanServer.invoke dispatches to the registered MBean', 'source': rng(MW, 176, 186, 'public void registerMBean(Object obj, ObjectName mbeanName, OnException onException)'),
                 'call': '= input.operation', 'targets': JMX_TARGETS, 'input': '= input.args', 'as': 'r'},
                {'return': {'result': '= vars.r.value'}}])

# ---------------------------------------------------------------- daemon startup
flow('daemon-startup', 'Node startup (CassandraDaemon.main)', 'cassandra-daemon.activate',
     [rng(CD, 863, 866, 'public static void main(String[] args)'), rng(CD, 718, 771, 'public void activate()')],
     description='bin/cassandra runs CassandraDaemon.main: config, setup (JMX, commit log, startup checks, schema, replay, initServer) and start (client transports).')
scenario('startup-happy-path', 'daemon-startup', 'Clean start: checks pass, commit log replayed, native transport started', [
    "result.ok && result.value.native_transport_started",
    "calls['startup-checks.verify'] == 1 && calls['commit-log.recover-segments-on-disk'] == 1 && calls['storage-service.init-server'] == 1",
    "calls['native-transport-service.start'] == 1 && calls['storage-service.set-rpc-ready'] == 1 && calls['gossiper.wait-to-settle'] == 1",
    "state['cassandra-daemon'].setup_completed && state['cassandra-daemon'].native_transport_running",
    "state['virtual-keyspace-registry'].keyspaces == ['system_virtual_schema', 'system_views'] && !state['audit-log-manager'].listener_registered"])
scenario('startup-commitlog-dir-unwritable', 'daemon-startup', 'checkDataDirs: commit log directory lacks permissions -> exit 3', [
    "!result.ok && result.error.code == 'startup-exception' && result.error.data.exit_code == 3",
    "result.error.message == 'Insufficient permissions on directory /var/lib/cassandra/commitlog'",
    "calls['commit-log.start'] == 1 && calls['schema.load-from-disk'] == 0 && calls['native-transport-service.start'] == 0"],
    state={'startup-checks': {'data_dirs': {'/var/lib/cassandra/commitlog': {'exists': True, 'can_create': True, 'writable': False}}}})
scenario('startup-data-dir-cannot-be-created', 'daemon-startup', 'checkDataDirs: a missing directory that cannot be created -> exit 3', [
    "!result.ok && result.error.data.exit_code == 3 && result.error.message.startsWith('Has no permission to create directory')"],
    state={'startup-checks': {'data_dirs': {'/var/lib/cassandra/hints': {'exists': False, 'can_create': False, 'writable': False}}}})
scenario('startup-dc-mismatch', 'daemon-startup', 'checkDatacenter: snitch DC differs from the saved DC -> exit 100', [
    "!result.ok && result.error.code == 'startup-exception' && result.error.data.exit_code == 100",
    "result.error.message.contains('differs from previous data center (dc1)')", "calls['storage-service.populate-token-metadata'] == 0"],
    state={'startup-checks': {'stored_dc': 'dc1'}})
scenario('startup-dc-check-disabled', 'daemon-startup', 'check_dc disabled: a DC change no longer stops startup', [
    "result.ok && calls['storage-service.init-server'] == 1"], state={'startup-checks': {'stored_dc': 'dc1'}}, config={'startup-checks-check-dc-enabled': False})
scenario('startup-rack-mismatch', 'daemon-startup', 'checkRack: snitch rack differs -> exit 100', [
    "!result.ok && result.error.data.exit_code == 100 && result.error.message.contains('rack')"], state={'startup-checks': {'stored_rack': 'rack2'}})
scenario('startup-native-library-missing', 'daemon-startup', 'checkNativeLibraryInitialization fails -> exit 1', [
    "!result.ok && result.error.data.exit_code == 1"], state={'startup-checks': {'native_library_ok': False}})
scenario('startup-invalid-config', 'daemon-startup', 'cassandra.yaml rejected by daemonInitialization -> exit 3 before anything starts', [
    "!result.ok && result.error.code == 'configuration-exception' && result.error.data.exit_code == 3",
    "calls['commit-log.start'] == 0 && calls['startup-checks.verify'] == 0"], state={'database-descriptor': {'config_valid': False}})
scenario('startup-commitlog-replay-fails', 'daemon-startup', 'Commit log replay throws IOException -> RuntimeException -> exit 3', [
    "!result.ok && result.error.code == 'runtime-exception' && result.error.data.exit_code == 3",
    "calls['storage-service.init-server'] == 0 && calls['native-transport-service.start'] == 0"],
    faults=[{'target': 'commit-log.recover-segments-on-disk', 'type': 'error', 'code': 'io-exception', 'message': 'corrupt segment CommitLog-7-1730284800000.log'}])
scenario('startup-init-server-config-error', 'daemon-startup', 'initServer throws ConfigurationException -> exit 1 (Fatal configuration error)', [
    "!result.ok && result.error.code == 'configuration-exception' && result.error.data.exit_code == 1 && result.error.message == 'Fatal configuration error'"],
    faults=[{'target': 'storage-service.init-server', 'type': 'error', 'code': 'config-error', 'message': 'Saved cluster name Test Cluster != configured name Prod'}])
scenario('startup-bootstrap-incomplete', 'daemon-startup', 'Joined but bootstrap not completed: transports stay down, startup still completes', [
    "result.ok && !result.value.native_transport_started && calls['native-transport-service.start'] == 0",
    "ctx.opsTransportsSkipped.startsWith('Node is not yet bootstrapped completely')"],
    choices={'cassandra-daemon.validate-transports-can-start.bootstrap': 'incomplete'})
scenario('startup-native-transport-disabled', 'daemon-startup', 'start_native_transport: false -> not started, can be enabled later with nodetool enablebinary', [
    "result.ok && !result.value.native_transport_started && calls['native-transport-service.start'] == 0 && calls['storage-service.set-rpc-ready'] == 0"],
    config={'start-native-transport': False})
scenario('startup-key-cache-load-fails', 'daemon-startup', 'Saved key cache cannot be loaded: logged, startup continues', [
    "result.ok && calls['auto-saving-cache.load-saved'] == 2 && faults == 1"],
    faults=[{'target': 'auto-saving-cache.load-saved', 'type': 'error', 'code': 'io-exception', 'calls': [1]}])

# ---------------------------------------------------------------- nodetool repair
flow('nodetool-repair', 'nodetool repair', 'node-tool.execute', [cmd_src('nodetool repair'), rng(J + 'tools/RepairRunner.java', 63, 91, 'public void run()')],
     input=nt('repair'), description='Operator runs nodetool repair; each keyspace is repaired by a RepairRunner that calls StorageServiceMBean.repairAsync and waits for completion.')
scenario('repair-all-keyspaces', 'nodetool-repair', 'Repair every non-local keyspace; system_distributed is skipped when not named', [
    EXIT(0), "calls['repair-runner.run'] == 4 && calls['storage-service.repair-async'] == 4 && ctx.opsRepairRuns == 4",
    "calls['storage-service-mbean.get-parent-repair-status'] == 4 && ctx.opsRepairOutcome.startsWith('completed')"])
scenario('repair-full', 'nodetool-repair', 'nodetool repair --full sends incremental=false (incremental is the default)', [EXIT(0), "calls['storage-service.repair-async'] == 1"],
         input={'args': {'keyspace': 'ks1', 'options': {'full': True}}})
scenario('repair-named-system-distributed', 'nodetool-repair', 'system_distributed is repaired when named explicitly', [
    EXIT(0), "calls['repair-runner.run'] == 1"], input={'args': {'keyspace': 'system_distributed'}})
scenario('repair-parent-status-failed', 'nodetool-repair', 'Parent repair session FAILED: IOException wrapped, exit 2, later keyspaces not repaired', [
    EXIT(2), "result.value.output.startsWith('error: ')", "calls['repair-runner.run'] == 1 && ctx.opsRepairOutcome == 'failed'"],
    choices={'repair-runner.run.parent_status': 'FAILED'})
scenario('repair-error-notification', 'nodetool-repair', 'An ERROR progress notification fails the repair (exit 2)', [
    EXIT(2), "result.value.output.contains('Repair job has failed with the error message')", "calls['storage-service-mbean.get-parent-repair-status'] == 0"],
    choices={'repair-runner.run.notification': 'error'}, input={'args': {'keyspace': 'ks1'}})
scenario('repair-jmx-connection-closed', 'nodetool-repair', 'JMX connection drops while waiting: IOException, exit 2', [
    EXIT(2), "result.value.output.contains('JMX connection closed')"], choices={'repair-runner.run.notification': 'connection_closed'}, input={'args': {'keyspace': 'ks1'}})
scenario('repair-rf1-nothing-to-do', 'nodetool-repair', 'repairAsync returns 0 (RF 1): nothing to repair, no status polling', [
    EXIT(0), "calls['storage-service-mbean.get-parent-repair-status'] == 0 && ctx.opsRepairOutcome == 'nothing to repair'"],
    choices={'repair-runner.run.started': 'nothing_to_repair'}, input={'args': {'keyspace': 'ks1'}})
scenario('repair-primary-range-with-dc', 'nodetool-repair', '-pr with -dc is refused client side (RuntimeException, exit 2)', [
    EXIT(2), "result.value.output == 'error: Primary range repair should be performed on all nodes in the cluster.'",
    "calls['node-tool-node-tool-cmd.parse-optional-keyspace'] == 0 && calls['storage-service.repair-async'] == 0"],
    input={'args': {'options': {'pr': True, 'dc': 'dc1'}}})
scenario('repair-unknown-keyspace', 'nodetool-repair', 'Unknown keyspace: IllegalArgumentException from argument parsing, exit 1', [
    EXIT(1), "result.value.output == 'nodetool: Keyspace [nosuch] does not exist.'", "calls['repair-runner.run'] == 0"], input={'args': {'keyspace': 'nosuch'}})
scenario('repair-jmx-unreachable', 'nodetool-repair', 'Node not reachable on 7199: connect fails, exit 1', [
    EXIT(1), "result.value.output.startsWith('nodetool: Failed to connect to')", "calls['repair-runner.run'] == 0"],
    faults=[{'target': 'node-probe.connect', 'type': 'error', 'code': 'io-exception', 'message': 'Connection refused'}])
scenario('repair-invalid-options', 'nodetool-repair', 'RepairOption.parse rejects the options: IllegalArgumentException wrapped, exit 2', [
    EXIT(2), "ctx.opsErrorCode == 'runtime-exception'"], input={'args': {'keyspace': 'ks1'}},
    faults=[{'target': 'storage-service.repair-async', 'type': 'error', 'code': 'illegal-argument-exception', 'message': 'Invalid parallelism'}])

# ---------------------------------------------------------------- nodetool flush
flow('nodetool-flush', 'nodetool flush', 'node-tool.execute', [cmd_src('nodetool flush'), jmx('StorageServiceMBean.forceKeyspaceFlush')], input=nt('flush', keyspace='ks1'))
scenario('flush-keyspace', 'nodetool-flush', 'Flush every table of ks1', [EXIT(0), "calls['column-family-store.force-blocking-flush'] == 3"])
scenario('flush-one-table', 'nodetool-flush', 'Flush one table', [EXIT(0), "calls['column-family-store.force-blocking-flush'] == 1"], input={'args': {'tables': ['users']}})
scenario('flush-all-keyspaces', 'nodetool-flush', 'No keyspace: every keyspace, local system ones included', [
    EXIT(0), "calls['storage-service-mbean.force-keyspace-flush'] == 7 && calls['column-family-store.force-blocking-flush'] == 15"], input={'args': {'keyspace': ''}})
scenario('flush-unknown-table', 'nodetool-flush', 'Unknown table: server IllegalArgumentException is wrapped by Flush, so exit 2 (not 1)', [
    EXIT(2), "result.value.output == 'error: Unknown keyspace/cf pair (ks1.nosuch)'", "calls['column-family-store.force-blocking-flush'] == 0"], input={'args': {'tables': ['nosuch']}})
scenario('flush-unknown-keyspace', 'nodetool-flush', 'Unknown keyspace caught client side: exit 1', [
    EXIT(1), "calls['storage-service-mbean.force-keyspace-flush'] == 0"], input={'args': {'keyspace': 'nosuch'}})
scenario('flush-virtual-keyspace', 'nodetool-flush', 'Virtual keyspace: not in Schema.getKeyspaces, refused client side (exit 1)', [
    EXIT(1), "result.value.output == 'nodetool: Keyspace [system_views] does not exist.'"], input={'args': {'keyspace': 'system_views'}})
scenario('flush-memtable-flush-fails', 'nodetool-flush', 'The memtable flush fails on disk: wrapped, exit 2', [
    EXIT(2), "result.value.output == 'error: No space left on device'"],
    faults=[{'target': 'column-family-store.force-blocking-flush', 'type': 'error', 'code': 'fs-write-error', 'message': 'No space left on device'}])

# ---------------------------------------------------------------- nodetool cleanup
flow('nodetool-cleanup', 'nodetool cleanup', 'node-tool.execute', [cmd_src('nodetool cleanup'), jmx('StorageServiceMBean.forceKeyspaceCleanup')], input=nt('cleanup', keyspace='ks1'))
OK_CLEANUP = None
scenario('cleanup-keyspace', 'nodetool-cleanup', 'Cleanup ks1: performCleanup per table', [EXIT(0), "calls['compaction-manager.perform-cleanup'] == 3 && calls['storage-service-mbean.force-keyspace-cleanup'] == 1"],
         choices=OK_CLEANUP)
scenario('cleanup-all-keyspaces', 'nodetool-cleanup', 'No keyspace: every non-local-strategy keyspace', [
    EXIT(0), "calls['storage-service-mbean.force-keyspace-cleanup'] == 5 && calls['compaction-manager.perform-cleanup'] == 12"], input={'args': {'keyspace': ''}}, choices=OK_CLEANUP)
scenario('cleanup-local-system-keyspace-skipped', 'nodetool-cleanup', 'nodetool skips a local system keyspace before calling the server', [
    EXIT(0), "calls['storage-service-mbean.force-keyspace-cleanup'] == 0"], input={'args': {'keyspace': 'system'}})
scenario('cleanup-pending-ranges', 'nodetool-cleanup', 'Node has pending ranges (membership change): refused, exit 2', [
    EXIT(2), "result.value.output == 'error: Node is involved in cluster membership changes. Not safe to run cleanup.'", "calls['compaction-manager.perform-cleanup'] == 0"],
    choices={'storage-service-mbean.force-keyspace-cleanup.pending_ranges': 'pending'})
scenario('cleanup-unable-to-cancel', 'nodetool-cleanup', 'Compactions could not be cancelled (status 2): probe marked failed, exit 2', [
    EXIT(2), "result.value.output == 'error: nodetool failed, check server logs'"], choices={'storage-service-mbean.force-keyspace-cleanup.op_status': 'UNABLE_TO_CANCEL'})
scenario('cleanup-aborted', 'nodetool-cleanup', 'Cleanup aborted for a table (status 1): message printed, exit 0', [
    EXIT(0), "result.value.output.contains('Aborted cleaning up for at least one table in keyspace ks1')"], choices={'storage-service-mbean.force-keyspace-cleanup.op_status': 'ABORTED'})
scenario('cleanup-jobs-above-compactors', 'nodetool-cleanup', '--jobs above concurrent_compactors only warns', [
    EXIT(0), "result.value.output.startsWith('jobs (4) is bigger than configured concurrent_compactors (2)')"], input={'args': {'options': {'jobs': 4}}}, choices=OK_CLEANUP)

# ---------------------------------------------------------------- nodetool decommission and drain
flow('nodetool-decommission', 'nodetool decommission', 'node-tool.execute', [cmd_src('nodetool decommission'), jmx('StorageServiceMBean.decommission')], input=nt('decommission'))
scenario('decommission-ok', 'nodetool-decommission', 'Decommission with --force (3 nodes at RF 3 would otherwise be refused by the server)', [EXIT(0), "calls['storage-service.decommission'] == 1"],
         input={'args': {'options': {'force': True}}})
scenario('decommission-already-running', 'nodetool-decommission', 'Already decommissioning: message only, no second decommission', [
    EXIT(0), "result.value.output == 'This node is still decommissioning.' && calls['storage-service.decommission'] == 0"],
    choices={'nodetool-decommission.execute.decommissioning': 'yes'})
scenario('decommission-already-done', 'nodetool-decommission', 'Bootstrap state DECOMMISSIONED: message only', [
    EXIT(0), "result.value.output == 'Node was already decommissioned.' && calls['storage-service.decommission'] == 0"],
    choices={'nodetool-decommission.execute.bootstrap_state': 'decommissioned'})
scenario('decommission-unsupported', 'nodetool-decommission', 'Server refuses (no other normal nodes): UnsupportedOperationException -> IllegalStateException, exit 1', [
    EXIT(1), "result.value.output == 'nodetool: Unsupported operation: no other normal nodes in the ring; decommission would be pointless'"],
    faults=[{'target': 'storage-service.decommission', 'type': 'error', 'code': 'unsupported-operation-exception', 'message': 'no other normal nodes in the ring; decommission would be pointless'}])
flow('nodetool-drain', 'nodetool drain', 'node-tool.execute', [cmd_src('nodetool drain'), jmx('StorageServiceMBean.drain')], input=nt('drain'))
scenario('drain-ok', 'nodetool-drain', 'Drain the node', [EXIT(0), "calls['storage-service.drain'] == 1"])
scenario('drain-io-failure', 'nodetool-drain', 'Drain fails with IOException while flushing: wrapped, exit 2', [
    EXIT(2), "result.value.output == 'error: disk failure'"], faults=[{'target': 'storage-service.drain', 'type': 'error', 'code': 'io-exception', 'message': 'disk failure'}])
scenario('drain-runtime-failure-not-wrapped', 'nodetool-drain', 'A RuntimeException from drain is not wrapped but still exits 2', [
    EXIT(2), "ctx.opsErrorCode == 'runtime-exception'"], faults=[{'target': 'storage-service.drain', 'type': 'error', 'code': 'runtime-exception', 'message': 'boom'}])

# ---------------------------------------------------------------- nodetool snapshot
flow('nodetool-snapshot', 'nodetool snapshot', 'node-tool.execute', [cmd_src('nodetool snapshot'), jmx('StorageServiceMBean.takeSnapshot')], input=nt('snapshot', options={'tag': 'before-upgrade'}))
scenario('snapshot-all-keyspaces', 'nodetool-snapshot', 'Snapshot every keyspace with a tag (entities empty)', [
    EXIT(0), "calls['storage-service.take-snapshot'] == 1 && result.value.output == 'Snapshot directory: before-upgrade'"])
scenario('snapshot-one-keyspace', 'nodetool-snapshot', 'Snapshot ks1 only', [EXIT(0), "calls['storage-service.take-snapshot'] == 1"], input={'args': {'keyspace': 'ks1'}})
scenario('snapshot-tag-exists', 'nodetool-snapshot', 'Server refuses an existing tag (IOException): wrapped, exit 2', [
    EXIT(2), "result.value.output == 'error: Snapshot before-upgrade already exists.'"],
    faults=[{'target': 'storage-service.take-snapshot', 'type': 'error', 'code': 'io-exception', 'message': 'Snapshot before-upgrade already exists.'}])
scenario('snapshot-while-joining', 'nodetool-snapshot', 'Server refuses while JOINING (IOException): wrapped, exit 2', [
    EXIT(2), "result.value.output == 'error: Cannot snapshot until bootstrap completes'"],
    faults=[{'target': 'storage-service.take-snapshot', 'type': 'error', 'code': 'io-exception', 'message': 'Cannot snapshot until bootstrap completes'}])
scenario('snapshot-bad-name', 'nodetool-snapshot', 'Tag containing the path separator is refused client side', [
    EXIT(2), "result.value.output == 'error: Snapshot name cannot contain :' && calls['storage-service.take-snapshot'] == 0"],
    input={'args': {'options': {'tag': 'a:b'}}})
scenario('snapshot-ttl-too-short', 'nodetool-snapshot', 'Server refuses a TTL under 60 s (IllegalArgumentException, not wrapped): exit 1', [
    EXIT(1), "result.value.output == 'nodetool: ttl for snapshot must be at least 60 seconds'"], input={'args': {'options': {'tag': 'x', 'ttl': 30}}},
    faults=[{'target': 'storage-service.take-snapshot', 'type': 'error', 'code': 'illegal-argument-exception', 'message': 'ttl for snapshot must be at least 60 seconds'}])

# ---------------------------------------------------------------- hinted handoff controls
flow('nodetool-hinted-handoff', 'nodetool hinted handoff controls', 'node-tool.execute',
     [cmd_src('nodetool disablehandoff'), cmd_src('nodetool pausehandoff'), cmd_src('nodetool truncatehints')], input=nt('disablehandoff'))
scenario('handoff-disable', 'nodetool-hinted-handoff', 'disablehandoff: new hints stop being written', [
    EXIT(0), "!state['storage-proxy-mbean'].hinted_handoff_enabled && calls['storage-service.check-service-allowed-to-start'] == 0"])
scenario('handoff-enable', 'nodetool-hinted-handoff', 'enablehandoff on a normal node', [
    EXIT(0), "state['storage-proxy-mbean'].hinted_handoff_enabled && calls['storage-service.check-service-allowed-to-start'] == 1"],
    input={'command': 'enablehandoff'}, state={'storage-proxy-mbean': {'hinted_handoff_enabled': False}})
scenario('handoff-enable-after-drain', 'nodetool-hinted-handoff', 'enablehandoff after drain: IllegalStateException, exit 1, flag unchanged', [
    EXIT(1), "result.value.output == 'nodetool: Unable to start hinted handoff because the node was drained.'", "!state['storage-proxy-mbean'].hinted_handoff_enabled"],
    input={'command': 'enablehandoff'}, state={'storage-proxy-mbean': {'hinted_handoff_enabled': False}},
    faults=[{'target': 'storage-service.check-service-allowed-to-start', 'type': 'error', 'code': 'illegal-state-exception', 'message': 'Unable to start hinted handoff because the node was drained.'}])
scenario('handoff-pause', 'nodetool-hinted-handoff', 'pausehandoff: hint dispatch paused (writing continues)', [EXIT(0), "calls['hints-service.pause-dispatch'] == 1"], input={'command': 'pausehandoff'})
scenario('handoff-resume', 'nodetool-hinted-handoff', 'resumehandoff', [EXIT(0), "calls['hints-service.resume-dispatch'] == 1"], input={'command': 'resumehandoff'})
scenario('truncatehints-all', 'nodetool-hinted-handoff', 'truncatehints with no endpoint deletes every hint', [
    EXIT(0), "calls['hints-service.delete-all-hints'] == 1 && calls['hints-service.delete-all-hints-for-endpoint'] == 0"], input={'command': 'truncatehints'})
scenario('truncatehints-unknown-endpoint', 'nodetool-hinted-handoff', 'truncatehints for an address with no host id: IllegalArgumentException, exit 1', [
    EXIT(1), "result.value.output == 'nodetool: Can\\'t delete hints for unknown address n9'"],
    input={'command': 'truncatehints', 'args': {'args': ['n9']}},
    faults=[{'target': 'hints-service.delete-all-hints-for-endpoint', 'type': 'error', 'code': 'illegal-argument-exception', 'message': "Can't delete hints for unknown address n9"}])
scenario('hints-disabled-for-dc', 'nodetool-hinted-handoff', 'disablehintsfordc dc2', [EXIT(0), "state['storage-proxy-mbean'].hints_disabled_dcs == ['dc2']"],
         input={'command': 'disablehintsfordc', 'args': {'args': ['dc2']}})
scenario('hints-disable-dc-missing-arg', 'nodetool-hinted-handoff', 'disablehintsfordc without a DC: exit 1', [
    EXIT(1), "calls['storage-proxy-mbean.disable-hints-for-dc'] == 0"], input={'command': 'disablehintsfordc'})
scenario('max-hint-window-set', 'nodetool-hinted-handoff', 'setmaxhintwindow 7200000', [EXIT(0), "state['storage-proxy-mbean'].max_hint_window_ms == 7200000"],
         input={'command': 'setmaxhintwindow', 'args': {'args': ['7200000']}})

# ---------------------------------------------------------------- runtime config
flow('nodetool-runtime-config', 'nodetool runtime configuration setters', 'node-tool.execute',
     [cmd_src('nodetool setcompactionthroughput'), cmd_src('nodetool settimeout'), cmd_src('nodetool setconcurrentcompactors')],
     input=nt('setcompactionthroughput', args=['128']))
scenario('compaction-throughput-set', 'nodetool-runtime-config', 'setcompactionthroughput 128: config and the compaction rate limiter updated', [
    EXIT(0), "state['storage-service-mbean'].compaction_throughput_mib_per_sec == 128 && calls['compaction-manager.set-rate-in-bytes'] == 1"])
scenario('write-timeout-set', 'nodetool-runtime-config', 'settimeout write 3000', [EXIT(0), "state['storage-service-mbean'].timeout_write_ms == 3000 && calls['storage-service-mbean.set-write-rpc-timeout'] == 1"],
         input={'command': 'settimeout', 'args': {'args': ['write', '3000']}})
scenario('timeout-unknown-type', 'nodetool-runtime-config', 'settimeout with an unknown type: exit 1', [EXIT(1), "calls['storage-service-mbean.set-write-rpc-timeout'] == 0"],
         input={'command': 'settimeout', 'args': {'args': ['bogus', '3000']}})
scenario('streaming-timeout-negative', 'nodetool-runtime-config', 'settimeout internodestreaminguser -1: server refuses, exit 1', [
    EXIT(1), "state['storage-service-mbean'].timeout_internodestreaminguser_ms == 300000"], input={'command': 'settimeout', 'args': {'args': ['internodestreaminguser', '-1']}})
scenario('concurrent-compactors-zero', 'nodetool-runtime-config', 'setconcurrentcompactors 0: refused client side, exit 1', [
    EXIT(1), "calls['storage-service-mbean.set-concurrent-compactors'] == 0"], input={'command': 'setconcurrentcompactors', 'args': {'args': ['0']}})
scenario('concurrent-compactors-set', 'nodetool-runtime-config', 'setconcurrentcompactors 4 resizes the compaction executor', [
    EXIT(0), "state['storage-service-mbean'].concurrent_compactors == 4 && calls['compaction-manager.set-concurrent-compactors'] == 1"],
    input={'command': 'setconcurrentcompactors', 'args': {'args': ['4']}})
scenario('trace-probability-out-of-range', 'nodetool-runtime-config', 'settraceprobability 1.5: exit 1', [EXIT(1), "state['storage-service-mbean'].trace_probability == 0.0"],
         input={'command': 'settraceprobability', 'args': {'args': ['1.5']}})
scenario('trace-probability-set', 'nodetool-runtime-config', 'settraceprobability 0.01', [EXIT(0), "state['storage-service-mbean'].trace_probability == 0.01"],
         input={'command': 'settraceprobability', 'args': {'args': ['0.01']}})
scenario('concurrency-unknown-stage', 'nodetool-runtime-config', 'setconcurrency with an unknown stage: IllegalStateException, exit 1', [
    EXIT(1), "result.value.output.startsWith('nodetool: Must be one of')"], input={'command': 'setconcurrency', 'args': {'args': ['NoSuchStage', '8']}})
scenario('stream-throughput-exclusive-flags', 'nodetool-runtime-config', 'setstreamthroughput -e -m: exit 1', [EXIT(1)],
         input={'command': 'setstreamthroughput', 'args': {'args': ['48'], 'options': {'entire-sstable-throughput': True, 'mib': True}}})
scenario('cache-capacity-negative', 'nodetool-runtime-config', 'setcachecapacity with a negative size: RuntimeException from CacheService, exit 2', [
    EXIT(2), "result.value.output == 'error: capacity should not be negative.'"], input={'command': 'setcachecapacity', 'args': {'args': ['-1', '0', '50']}})

# ---------------------------------------------------------------- audit log and FQL via nodetool
flow('nodetool-audit-and-fql', 'nodetool enableauditlog / enablefullquerylog', 'node-tool.execute',
     [cmd_src('nodetool enableauditlog'), cmd_src('nodetool enablefullquerylog')], input=nt('enableauditlog'))
scenario('auditlog-enable', 'nodetool-audit-and-fql', 'enableauditlog: BinAuditLogger installed and listeners registered', [
    EXIT(0), "state['audit-log-manager'].enabled && state['audit-log-manager'].listener_registered && state['audit-log-manager'].logger == 'BinAuditLogger'"])
scenario('auditlog-archive-command-refused', 'nodetool-audit-and-fql', 'enableauditlog --archive-command without allow_nodetool_archive_command: ConfigurationException, exit 2', [
    EXIT(2), "!state['audit-log-manager'].enabled && calls['audit-log-manager.enable'] == 0"], input={'args': {'options': {'archive-command': '/usr/local/bin/archive.sh %path'}}})
scenario('auditlog-bad-blocking', 'nodetool-audit-and-fql', 'enableauditlog --blocking maybe: exit 1', [EXIT(1)], input={'args': {'options': {'blocking': 'maybe'}}})
scenario('auditlog-disable', 'nodetool-audit-and-fql', 'disableauditlog', [EXIT(0), "!state['audit-log-manager'].listener_registered"],
         input={'command': 'disableauditlog'}, state={'audit-log-manager': {'enabled': True, 'listener_registered': True, 'logger': 'BinAuditLogger'}})
scenario('fql-enable-without-path', 'nodetool-audit-and-fql', 'enablefullquerylog with no --path: deployed log_dir is empty, IllegalArgumentException, exit 1', [
    EXIT(1), "result.value.output == 'nodetool: you might have forgotten to specify a directory to save logs'", "!state['full-query-logger'].listener_registered"],
    input={'command': 'enablefullquerylog'})
scenario('fql-enable-with-path', 'nodetool-audit-and-fql', 'enablefullquerylog --path /var/log/cassandra/fql', [
    EXIT(0), "state['full-query-logger'].bin_log_path == '/var/log/cassandra/fql' && state['full-query-logger'].listener_registered"],
    input={'command': 'enablefullquerylog', 'args': {'options': {'path': '/var/log/cassandra/fql'}}})
scenario('fql-already-enabled', 'nodetool-audit-and-fql', 'enablefullquerylog when a BinLog is configured: IllegalStateException, exit 1', [
    EXIT(1), "result.value.output == 'nodetool: Binlog is already configured'"],
    input={'command': 'enablefullquerylog', 'args': {'options': {'path': '/var/log/cassandra/fql2'}}},
    state={'full-query-logger': {'bin_log_path': '/var/log/cassandra/fql', 'listener_registered': True}})

# ---------------------------------------------------------------- audit log on the query path
flow('audit-log-query', 'Audit logging of a successful query', 'audit-log-manager.query-success', [rng(J + 'audit/AuditLogManager.java', 242, 252, 'public void querySuccess')],
     input={'user': 'cassandra', 'keyspace': 'ks1', 'type': 'SELECT', 'category': 'QUERY', 'operation': 'SELECT * FROM ks1.users WHERE id = 42', 'source': '/10.0.0.9:51234'})
scenario('audit-disabled-by-default', 'audit-log-query', 'Deployed config: audit logging disabled, nothing logged', [
    "result.ok && !result.value.logged && calls['bin-audit-logger.log'] == 0 && calls['audit-log-filter.is-filtered'] == 0"])
scenario('audit-enabled-logged', 'audit-log-query', 'Audit logging enabled: entry written to the binary log', [
    "result.ok && result.value.logged && calls['bin-audit-logger.log'] == 1 && state['bin-audit-logger'].entries == 1"],
    state={'audit-log-manager': {'enabled': True, 'listener_registered': True, 'logger': 'BinAuditLogger'}})
scenario('audit-excluded-keyspace', 'audit-log-query', 'Query on an excluded keyspace (system) is filtered', [
    "result.ok && !result.value.logged && ctx.opsAuditFiltered && calls['bin-audit-logger.log'] == 0"],
    input={'keyspace': 'system'}, state={'audit-log-manager': {'enabled': True, 'listener_registered': True}})
scenario('audit-included-users-only', 'audit-log-query', 'included_users = alice: a query by cassandra is filtered', [
    "result.ok && !result.value.logged"], state={'audit-log-manager': {'enabled': True, 'listener_registered': True, 'included_users': ['alice']}})
scenario('audit-exclude-wins', 'audit-log-query', 'Category both included and excluded: exclusion wins', [
    "result.ok && !result.value.logged"], state={'audit-log-manager': {'enabled': True, 'listener_registered': True, 'included_categories': ['QUERY'], 'excluded_categories': ['QUERY']}})

# ---------------------------------------------------------------- tracing
flow('tracing-session', 'Tracing session start (TracingImpl.begin)', 'tracing-impl.begin', [rng(J + 'tracing/TracingImpl.java', 53, 67, 'public TraceState begin(final String request, final InetAddress client')],
     caller='cassandra-daemon', input={'session_id': '4c5f2a10-9b1e-11ef-8f3a-0242ac120002', 'request': 'Execute CQL3 query', 'activity': 'Execute CQL3 query', 'trace_type': 'QUERY', 'ttl_seconds': 86400})
scenario('trace-session-recorded', 'tracing-session', 'Session row written asynchronously at CL ANY on the TRACING stage', [
    "result.ok && calls['trace-state-impl.execute-mutation'] == 1 && calls['trace-state-impl.mutate-with-catch'] == 1 && calls['storage-proxy.mutate'] == 1",
    "state['trace-state-impl'].pending == 0 && state['tracing-impl'].sessions_started == 1"])
scenario('trace-overloaded-dropped', 'tracing-session', 'Coordinator overloaded: OverloadedException swallowed, the request is unaffected', [
    "result.ok && state['trace-state-impl'].dropped_overloaded == 1 && ctx.opsTraceDropped"],
    faults=[{'target': 'storage-proxy.mutate', 'type': 'error', 'code': 'overloaded', 'status': 4097, 'message': 'Too many in flight hints'}])
scenario('trace-write-unavailable', 'tracing-session', 'Write fails with another error: logged by the TRACING stage executor, the request is still unaffected', [
    "result.ok && state['trace-state-impl'].dropped_overloaded == 0 && state['trace-state-impl'].pending == 1"],
    faults=[{'target': 'storage-proxy.mutate', 'type': 'error', 'code': 'unavailable', 'status': 4096}])
flow('tracing-remote-event', 'Trace event for a session started on another node (TracingImpl.trace)', 'tracing-impl.trace', [rng(J + 'tracing/TracingImpl.java', 106, 117, 'public void trace(final ByteBuffer sessionId')],
     caller='cassandra-daemon', input={'session_id': '4c5f2a10-9b1e-11ef-8f3a-0242ac120002', 'request': 'MUTATION', 'activity': 'Appending to commitlog', 'trace_type': 'QUERY', 'ttl_seconds': 86400})
scenario('trace-remote-event-recorded', 'tracing-remote-event', 'Replica-side trace event written on the TRACING stage', [
    "result.ok && calls['storage-proxy.mutate'] == 1 && state['tracing-impl'].remote_events == 1"])

# ---------------------------------------------------------------- JMX-only operations
flow('jmx-operation', 'JMX client invokes an operation (no nodetool command)', 'mbean-wrapper.invoke-operation', [rng(CD, 139, 185, 'private void maybeInitJmx()')],
     input={'operation': 'storage-service-mbean.truncate', 'args': {'keyspace': 'ks1', 'table': 'users'}})
scenario('jmx-truncate', 'jmx-operation', 'StorageService.truncate via JMX: StorageProxy.truncateBlocking', ["result.ok && calls['storage-proxy.truncate-blocking'] == 1"])
scenario('jmx-truncate-unavailable', 'jmx-operation', 'truncate with replicas down: UnavailableException rethrown as IOException', [
    "!result.ok && result.error.code == 'io-exception'"], faults=[{'target': 'storage-proxy.truncate-blocking', 'type': 'error', 'code': 'unavailable', 'status': 4096, 'message': 'Cannot achieve consistency level ALL'}])
scenario('jmx-denylist-key', 'jmx-operation', 'StorageProxy.denylistKey', ["result.ok && state['storage-proxy-mbean'].denylisted_keys == ['ks1.users:user:42']"],
         input={'operation': 'storage-proxy-mbean.denylist-key', 'args': {'keyspace': 'ks1', 'table': 'users', 'partition_key': 'user:42'}})
scenario('jmx-repaired-data-tracking', 'jmx-operation', 'enableRepairedDataTrackingForPartitionReads', ["result.ok && state['storage-proxy-mbean'].repaired_data_tracking_partition_reads"],
         input={'operation': 'storage-proxy-mbean.enable-repaired-data-tracking-for-partition-reads', 'args': {}})
scenario('jmx-save-caches', 'jmx-operation', 'CacheService.saveCaches writes all three caches', ["result.ok && calls['auto-saving-cache.submit-write'] == 3"],
         input={'operation': 'cache-service-mbean.save-caches', 'args': {}})
scenario('jmx-terminate-repairs', 'jmx-operation', 'forceTerminateAllRepairSessions', ["result.ok && calls['active-repair-service.terminate-sessions'] == 1"],
         input={'operation': 'storage-service-mbean.force-terminate-all-repair-sessions', 'args': {}})
scenario('jmx-drop-prepared', 'jmx-operation', 'dropPreparedStatements', ["result.ok && calls['query-processor.clear-prepared-statements'] == 1"],
         input={'operation': 'storage-service-mbean.drop-prepared-statements', 'args': {'memory_only': True}})
scenario('jmx-deliver-hints-unsupported', 'jmx-operation', 'deliverHints always throws UnsupportedOperationException', [
    "!result.ok && result.error.code == 'unsupported-operation-exception'"], input={'operation': 'storage-service-mbean.deliver-hints', 'args': {'host': 'n2'}})
scenario('jmx-take-table-snapshot', 'jmx-operation', 'takeTableSnapshot delegates to StorageService.takeSnapshot with a keyspace.table entity', [
    "result.ok && calls['storage-service.take-snapshot'] == 1"], input={'operation': 'storage-service-mbean.take-table-snapshot', 'args': {'keyspace': 'ks1', 'table': 'users', 'tag': 't1'}})
scenario('jmx-start-sampling-invalid', 'jmx-operation', 'startSamplingPartitions with a non-positive duration is refused', [
    "!result.ok && result.error.code == 'illegal-argument-exception'"], input={'operation': 'storage-service-mbean.start-sampling-partitions', 'args': {'duration_ms': 0, 'interval_ms': -1, 'capacity': 256}})
scenario('jmx-mutate-repaired-unknown-table', 'jmx-operation', 'mutateSSTableRepairedState with an unknown table: RuntimeException', [
    "!result.ok && result.error.code == 'runtime-exception'"], input={'operation': 'storage-service-mbean.mutate-sstable-repaired-state', 'args': {'keyspace': 'ks1', 'tables': ['nosuch'], 'repaired': True, 'preview': True}})

# ---------------------------------------------------------------- every other command through the dispatcher
flow('nodetool-command', 'nodetool <command> (dispatch)', 'node-tool.execute', [rng(NT, 96, 296, 'public int execute(String... args)')], input=nt('refreshsizeestimates'),
     description='Covers each remaining action command with one happy-path run through NodeTool.execute.')
covered_elsewhere = {'repair', 'flush', 'cleanup', 'decommission', 'drain', 'snapshot', 'disablehandoff', 'enablehandoff', 'pausehandoff', 'resumehandoff', 'truncatehints',
                     'disablehintsfordc', 'setmaxhintwindow', 'setcompactionthroughput', 'settimeout', 'setconcurrentcompactors', 'settraceprobability', 'setconcurrency',
                     'setstreamthroughput', 'setcachecapacity', 'enableauditlog', 'disableauditlog', 'enablefullquerylog'}
HAPPY = {
    'scrub': (A(keyspace='ks1'), 'compaction-manager.perform-scrub', 3), 'verify': (A(keyspace='ks1'), 'compaction-manager.perform-verify', 3),
    'upgradesstables': (A(keyspace='ks1'), 'compaction-manager.perform-sstable-rewrite', 3), 'recompress_sstables': (A(keyspace='ks1'), 'compaction-manager.perform-sstable-rewrite', 3),
    'garbagecollect': (A(keyspace='ks1'), 'compaction-manager.perform-garbage-collection', 3), 'relocatesstables': (A(keyspace='ks1'), 'compaction-manager.relocate-sstables', 3),
    'compact': (A(keyspace='ks1', tables=['users']), 'compaction-manager.perform-maximal', 1), 'forcecompact': (A(args=['ks1', 'users', 'user:42']), 'column-family-store.force-compaction-keys-ignoring-gc-grace', 1),
    'stop': (A(args=['COMPACTION']), 'compaction-manager.stop-compaction', 1),
    'disableautocompaction': (A(keyspace='ks1'), 'column-family-store.disable-auto-compaction', 3), 'enableautocompaction': (A(keyspace='ks1'), 'column-family-store.enable-auto-compaction', 3),
    'clearsnapshot': (A(options={'t': 'before-upgrade'}), 'storage-service.clear-snapshot', 1),
    'repair_admin cancel': (A(args=['a3e1c2d0-9b1e-11ef-8f3a-0242ac120002'], options={'force': True}), 'active-repair-service.fail-session', 1),
    'repair_admin cleanup': (A(keyspace='ks1'), 'active-repair-service.cleanup-pending', 1),
    'move': (A(args=['-3074457345618258603']), 'storage-service.move', 1), 'removenode': (A(args=['6d194555-f6eb-41d0-c000-000000000002']), 'storage-service.remove-node', 1),
    'join': (A(), 'storage-service.join-ring', 0), 'rebuild': (A(args=['datacenter1']), 'storage-service.rebuild', 1),
    'bootstrap resume': (A(options={'force': True}), 'storage-service.resume-bootstrap', 1), 'stopdaemon': (A(), 'cassandra-daemon.deactivate', 1),
    'assassinate': (A(args=['n3']), 'gossiper.assassinate-endpoint', 1), 'reloadseeds': (A(), 'gossiper.reload-seeds', 1),
    'disablebinary': (A(), 'native-transport-service.stop', 1), 'enablebinary': (A(), 'storage-service.check-service-allowed-to-start', 1),
    'disablegossip': (A(), 'storage-service.stop-gossiping', 1), 'enablegossip': (A(), 'storage-service.start-gossiping', 1),
    'disableoldprotocolversions': (A(), 'storage-service-mbean.disable-native-transport-old-protocol-versions', 1),
    'enableoldprotocolversions': (A(), 'storage-service-mbean.enable-native-transport-old-protocol-versions', 1),
    'disablebackup': (A(), 'storage-service-mbean.set-incremental-backups-enabled', 1), 'enablebackup': (A(), 'storage-service-mbean.set-incremental-backups-enabled', 1),
    'disablefullquerylog': (A(), 'full-query-logger.stop', 1), 'resetfullquerylog': (A(), 'full-query-logger.reset', 1),
    'reloadlocalschema': (A(), 'schema.reload-schema-and-announce-version', 1), 'refreshsizeestimates': (A(), 'storage-service-mbean.refresh-size-estimates', 1),
    'reloadtriggers': (A(), 'storage-proxy-mbean.reload-trigger-classes', 1), 'invalidatekeycache': (A(), 'auto-saving-cache.clear', 1),
    'invalidaterowcache': (A(), 'auto-saving-cache.clear', 1), 'invalidatecountercache': (A(), 'auto-saving-cache.clear', 1),
    'reloadcidrgroupscache': (A(), 'cidr-groups-mapping-manager.load-cidr-groups-cache', 1), 'reloadssl': (A(), 'messaging-service-mbean-impl.reload-ssl-certificates', 1),
    'resetlocalschema': (A(), 'schema.reset-local-schema', 1), 'replaybatchlog': (A(), 'batchlog-manager.force-batchlog-replay', 1),
    'enablehintsfordc': (A(args=['dc2']), 'storage-proxy-mbean.enable-hints-for-dc', 1),
    'invalidatecredentialscache': (A(), 'auth-cache.invalidate', 1), 'invalidatejmxpermissionscache': (A(), 'auth-cache.invalidate', 1),
    'invalidatenetworkpermissionscache': (A(args=['alice', 'bob']), 'auth-cache.invalidate', 2), 'invalidatepermissionscache': (A(), 'auth-cache.invalidate', 1),
    'invalidaterolescache': (A(args=['alice']), 'auth-cache.invalidate', 1), 'invalidatecidrpermissionscache': (A(), 'cidr-permissions-manager.invalidate-cidr-permissions-cache', 1),
    'updatecidrgroup': (A(args=['office', '10.0.0.0/24']), 'cidr-groups-mapping-manager.update-cidr-group', 1), 'dropcidrgroup': (A(args=['office']), 'cidr-groups-mapping-manager.drop-cidr-group', 1),
    'import': (A(args=['ks1', 'users', '/tmp/import/ks1/users']), 'column-family-store.import-new-sstables', 1), 'refresh': (A(args=['ks1', 'users']), 'column-family-store.load-new-sstables', 1),
    'rebuild_index': (A(args=['ks1', 'users', 'users_email_idx']), 'column-family-store.rebuild-secondary-index', 1),
    'setcompactionthreshold': (A(args=['ks1', 'users', '4', '32']), 'column-family-store.set-compaction-thresholds', 1),
    'sstablerepairedset': (A(keyspace='ks1', tables=['users']), 'storage-service-mbean.mutate-sstable-repaired-state', 1),
    'setconcurrentviewbuilders': (A(args=['2']), 'compaction-manager.set-concurrent-view-builders', 1), 'setbatchlogreplaythrottle': (A(args=['2048']), 'batchlog-manager.set-rate', 1),
    'sethintedhandoffthrottlekb': (A(args=['2048']), 'storage-service-mbean.set-hinted-handoff-throttle-in-kb', 1), 'setcolumnindexsize': (A(args=['16']), 'storage-service-mbean.set-column-index-size', 1),
    'setsnapshotthrottle': (A(args=['100']), 'storage-service-mbean.set-snapshot-links-per-second', 1), 'setdefaultrf': (A(args=['3']), 'storage-service-mbean.set-default-keyspace-replication-factor', 1),
    'setlogginglevel': (A(args=['org.apache.cassandra.gms', 'DEBUG']), 'storage-service-mbean.set-logging-level', 1),
    'setinterdcstreamthroughput': (A(args=['48']), 'stream-manager-stream-rate-limiter.update-inter-dc-throughput', 1),
    'setcachekeystosave': (A(args=['100', '0', '100']), 'auto-saving-cache.schedule-saving', 3),
}
missing = sorted(set(N.COMMANDS) - covered_elsewhere - set(HAPPY))
assert not missing, missing
for cli in sorted(HAPPY):
    args, target, n = HAPPY[cli]
    exp = [EXIT(0), "calls['%s'] == %d" % (target, n)]
    st = None
    if cli in ('invalidatecidrpermissionscache', 'reloadcidrgroupscache'):
        # outcome is schema-auth's: with the deployed AllowAllCIDRAuthorizer the server refuses (exit 2)
        exp = ["result.ok", "calls['%s'] == %d" % (target, n)]
    ch = None
    if cli in ('scrub', 'verify', 'upgradesstables', 'recompress_sstables', 'garbagecollect', 'relocatesstables'):
        m = {'scrub': 'scrub', 'verify': 'verify', 'upgradesstables': 'upgrade-sstables', 'recompress_sstables': 'recompress-sstables',
             'garbagecollect': 'garbage-collect', 'relocatesstables': 'relocate-sstables'}[cli]
        ch = None
    if cli == 'compact':
        view = {'auto_compaction_enabled': True, 'strategy': 'SizeTieredCompactionStrategy', 'min_threshold': 4, 'max_threshold': 32, 'compacting': [],
                'sstables': [{'id': 'nb-%d' % n, 'size_mb': 10, 'level': 0, 'repaired': False, 'droppable_tombstone_ratio': 0.0, 'age_s': 3600, 'fully_expired': False,
                              'tombstones': 0, 'purgeable_tombstones': 0, 'unowned_mb': 0, 'window': 0} for n in (1, 2)]}
        st = {'tracker@n1': {'views': {k: view for k in TRACKER_KEYS}}}
    if cli == 'removenode':
        args = A(args=['6d194555-f6eb-41d0-c000-000000000003'])
        st = {'gossiper@n1': {'live_endpoints': ['n2'], 'unreachable_endpoints': ['n3'], 'endpoint_state_map': {'n3': {'alive': False}}}}
    if cli == 'repair_admin cancel':
        st = {'local-sessions@n1': {'sessions': {'a3e1c2d0-9b1e-11ef-8f3a-0242ac120002': {'state': 'PREPARED', 'coordinator': 'n1', 'participants': ['n1']}}}}
    if cli == 'enablebinary':
        st = {'cassandra-daemon': {'setup_completed': True}}
    if cli == 'join':
        exp = [EXIT(1), "result.value.output == 'nodetool: This node has already joined the ring.'"]
    scenario('cmd-' + kebab(cli.replace(' ', '-').replace('_', '-')), 'nodetool-command', 'nodetool %s' % cli, exp, input={'command': cli, 'args': args}, state=st, choices=ch)
scenario('cmd-unknown-command', 'nodetool-command', 'Unknown command: airline parse error, exit 1', [EXIT(1), "calls['node-probe.connect'] == 0"], input={'command': 'frobnicate'})
scenario('cmd-readonly-report', 'nodetool-command', 'Read-only report commands (status, tpstats, ...) are out of the model: exit 0 without calls', [
    EXIT(0), "result.value.output == 'read-only report: status' && calls['node-probe.connect'] == 0"], input={'command': 'status'})
scenario('cmd-bootstrap-resume-disabled', 'nodetool-command', 'bootstrap resume without --force is disabled by default (exit 2)', [
    EXIT(2), "result.value.output == 'error: \\'nodetool bootstrap resume\\' is disabled.' && calls['storage-service.resume-bootstrap'] == 0"], input={'command': 'bootstrap resume'})
scenario('cmd-scrub-system-keyspace', 'nodetool-command', 'scrub of a virtual keyspace is refused client side (not a schema keyspace)', [EXIT(1)],
         input={'command': 'scrub', 'args': A(keyspace='system_views')})
scenario('cmd-setcompactionthreshold-invalid', 'nodetool-command', 'setcompactionthreshold with min > max is refused client side', [
    EXIT(1), "result.value.output == 'nodetool: Min threshold cannot be greater than max.' && calls['column-family-store.set-compaction-thresholds'] == 0"],
    input={'command': 'setcompactionthreshold', 'args': A(args=['ks1', 'users', '40', '32'])})
scenario('cmd-enablebinary-not-bootstrapped', 'nodetool-command', 'enablebinary before bootstrap completes: wrapped as RuntimeException, exit 2', [
    EXIT(2), "result.value.output.startsWith('error: Error starting native transport: Node is not yet bootstrapped completely')"],
    input={'command': 'enablebinary'}, state={'cassandra-daemon': {'setup_completed': True}}, choices={'cassandra-daemon.validate-transports-can-start.bootstrap': 'incomplete'})
scenario('cmd-dropcidrgroup-unknown', 'nodetool-command', 'dropcidrgroup of an unknown group: RuntimeException from the server, exit 2', [EXIT(2)],
         input={'command': 'dropcidrgroup', 'args': A(args=['nosuch'])},
         faults=[{'target': 'cidr-groups-mapping-manager.drop-cidr-group', 'type': 'error', 'code': 'runtime-exception', 'message': "CIDR group 'nosuch' doesn't exists"}])

# ---------------------------------------------------------------- interfaces ops owns for other areas
flow('diagnostic-snapshot', 'Diagnostic snapshot requested by another node', 'diagnostic-snapshot-service.snapshot',
     [rng(J + 'utils/DiagnosticSnapshotService.java', 111, 115, 'public static void snapshot(SnapshotCommand command')], caller='cassandra-daemon',
     input={'keyspace': 'ks1', 'column_family': 'users', 'snapshot_name': 'RepairedDataMismatch-2026-10-30', 'from': 'n2'})
scenario('diagnostic-snapshot-taken', 'diagnostic-snapshot', 'A RepairedDataMismatch- request is queued and the task snapshots the table', [
    "result.ok && calls['diagnostic-snapshot-service.run-task'] == 1 && state['diagnostic-snapshot-service'].tasks_run == 1"])
scenario('diagnostic-snapshot-wrong-name', 'diagnostic-snapshot', 'A non-diagnostic snapshot name fails the precondition', [
    "!result.ok && result.error.code == 'illegal-argument-exception' && calls['diagnostic-snapshot-service.run-task'] == 0"], input={'snapshot_name': 'manual-1'})
flow('tracing-request-session', 'Traced request: Tracing.begin then stopSession', 'tracing.begin',
     [rng(TR, 236, 241, 'public TraceState begin(final String request, final Map<String, String> parameters)')], caller='cassandra-daemon',
     input={'request': 'Execute CQL3 query', 'parameters': {'query': 'SELECT * FROM ks1.users WHERE id = 42'}})
scenario('tracing-begin-bound-session', 'tracing-request-session', 'A bound session writes its session row', [
    "result.ok && calls['tracing-impl.begin'] == 1"], state={'tracing': {'current_session': '5f0c2a40-7a9e-11ef-8f1a-3b2d4c5e6f70'}})
scenario('tracing-begin-no-session', 'tracing-request-session', 'Without a bound session nothing is written', ["result.ok && calls['tracing-impl.begin'] == 0"])

# ---------------------------------------------------------------- write then read back (multi-step)
def jget(op, args=None):
    return {'flow': 'jmx-operation', 'input': {'operation': op, 'args': args or {}}, 'as': 'get'}


scenario('compaction-throughput-read-back', 'nodetool-runtime-config', 'setcompactionthroughput 96, then read it back over JMX', [
    "steps.set.result.value.exit_status == 0", "steps.get.result.ok && steps.get.result.value.result.value == 96",
    "state['storage-service-mbean@n1'].compaction_throughput_mib_per_sec == 96"],
    steps=[{'flow': 'nodetool-runtime-config', 'input': {'command': 'setcompactionthroughput', 'args': {'args': ['96']}}, 'as': 'set'},
           jget('storage-service-mbean.get-compaction-throughput-mb-per-sec')])
scenario('handoff-disable-read-back', 'nodetool-hinted-handoff', 'disablehandoff, then getHintedHandoffEnabled over JMX returns false', [
    "steps.set.result.value.exit_status == 0", "steps.get.result.ok && steps.get.result.value.result.value == false",
    "!state['storage-proxy-mbean@n1'].hinted_handoff_enabled"],
    steps=[{'flow': 'nodetool-hinted-handoff', 'input': {'command': 'disablehandoff'}, 'as': 'set'}, jget('storage-proxy-mbean.get-hinted-handoff-enabled')])
scenario('auditlog-enable-then-query-logged', 'nodetool-audit-and-fql', 'enableauditlog, then a successful query is written to the audit log', [
    "steps.set.result.value.exit_status == 0", "steps.q.result.ok && steps.q.result.value.logged",
    "state['bin-audit-logger@n1'].entries == 1"],
    steps=[{'flow': 'nodetool-audit-and-fql', 'input': {'command': 'enableauditlog'}, 'as': 'set'},
           {'flow': 'audit-log-query', 'as': 'q'}])
scenario('fql-enable-read-back', 'nodetool-audit-and-fql', 'enablefullquerylog --path, then isFullQueryLogEnabled over JMX', [
    "steps.set.result.value.exit_status == 0", "steps.get.result.value.result.value == true",
    "state['full-query-logger@n1'].bin_log_path == '/var/log/cassandra/fql'"],
    steps=[{'flow': 'nodetool-audit-and-fql', 'input': {'command': 'enablefullquerylog', 'args': {'options': {'path': '/var/log/cassandra/fql'}}}, 'as': 'set'},
           jget('storage-service-mbean.is-full-query-log-enabled')])
scenario('jmx-denylist-read-back', 'jmx-operation', 'denylistKey, then isKeyDenylisted', [
    "steps.set.result.ok", "steps.get.result.value.value == true", "state['storage-proxy-mbean@n1'].denylisted_keys == ['ks1.users:user:42']"],
    steps=[{'flow': 'jmx-operation', 'input': {'operation': 'storage-proxy-mbean.denylist-key', 'args': {'keyspace': 'ks1', 'table': 'users', 'partition_key': 'user:42'}}, 'as': 'set'},
           {'interface': 'storage-proxy-mbean.is-key-denylisted', 'caller': 'operator', 'input': {'keyspace': 'ks1', 'table': 'users', 'partition_key': 'user:42'}, 'as': 'get'}])
scenario('enablebackup-read-back', 'nodetool-command', 'enablebackup, then isIncrementalBackupsEnabled over JMX', [
    "steps.set.result.value.exit_status == 0", "steps.get.result.value.result.value == true", "state['storage-service-mbean@n1'].incremental_backups"],
    steps=[{'flow': 'nodetool-command', 'input': {'command': 'enablebackup'}, 'as': 'set'}, jget('storage-service-mbean.is-incremental-backups-enabled')])
scenario('startup-then-enablebinary', 'daemon-startup', 'After startup, nodetool enablebinary finds the transport already running (no second RPC-ready announcement)', [
    "steps.start.result.ok", "steps.bin.result.value.exit_status == 0",
    "calls['native-transport-service.start'] == 2 && calls['storage-service.set-rpc-ready'] == 1",
    "state['cassandra-daemon@n1'].native_transport_running"],
    steps=[{'flow': 'daemon-startup', 'as': 'start'}, {'flow': 'nodetool-command', 'input': {'command': 'enablebinary'}, 'as': 'bin'}])

# ---------------------------------------------------------------- more command branches
def ntc(id, name, cmd, args, expect, **kw):
    scenario(id, 'nodetool-command', name, expect, input={'command': cmd, 'args': args}, **kw)


ntc('cmd-compact-token-range', 'nodetool compact -st/-et compacts only the token range', 'compact', A(keyspace='ks1', tables=['users'], options={'start-token': '-100', 'end-token': '100'}),
    [EXIT(0), "calls['compaction-manager.force-compaction-for-token-range'] == 1 && calls['compaction-manager.perform-maximal'] == 0"])
ntc('cmd-compact-partition-key', 'nodetool compact --partition compacts the SSTables holding one key', 'compact', A(keyspace='ks1', tables=['users'], options={'partition': 'user:42'}),
    [EXIT(0), "calls['storage-service-mbean.force-keyspace-compaction-for-partition-key'] == 1"])
ntc('cmd-compact-user-defined', 'nodetool compact --user-defined compacts the named data files', 'compact', A(args=['/var/lib/cassandra/data/ks1/users-1/nb-1-big-Data.db'], options={'user-defined': True}),
    [EXIT(0), "calls['compaction-manager.force-user-defined-compaction'] == 1 && calls['node-tool-node-tool-cmd.parse-optional-keyspace'] == 0"])
ntc('cmd-compact-user-defined-split', 'nodetool compact --user-defined with --split-output is refused client side', 'compact', A(args=['x-Data.db'], options={'user-defined': True, 'split-output': True}),
    [EXIT(2), "result.value.output == 'error: Invalid option combination: Can not use split-output here'"])
ntc('cmd-setstreamthroughput-mbit', 'setstreamthroughput 48 (megabits/s by default)', 'setstreamthroughput', A(args=['48']),
    [EXIT(0), "state['storage-service-mbean@n1'].stream_throughput_mib == 48 && calls['stream-manager-stream-rate-limiter.update-throughput'] == 1"])
ntc('cmd-setstreamthroughput-mib', 'setstreamthroughput -m 48 (MiB/s)', 'setstreamthroughput', A(args=['48'], options={'mib': True}),
    [EXIT(0), "calls['storage-service-mbean.set-stream-throughput-mebibytes-per-sec'] == 1 && state['storage-service-mbean@n1'].stream_throughput_mib == 48"])
ntc('cmd-setstreamthroughput-entire', 'setstreamthroughput -e 48 sets the entire-SSTable throughput', 'setstreamthroughput', A(args=['48'], options={'entire-sstable-throughput': True}),
    [EXIT(0), "state['storage-service-mbean@n1'].entire_sstable_stream_throughput_mib == 48"])
ntc('cmd-setinterdcstreamthroughput-mib', 'setinterdcstreamthroughput -m 48', 'setinterdcstreamthroughput', A(args=['48'], options={'mib': True}),
    [EXIT(0), "calls['storage-service-mbean.set-inter-dcstream-throughput-mebibytes-per-sec'] == 1 && state['storage-service-mbean@n1'].inter_dc_stream_throughput_mib == 48"])
ntc('cmd-setinterdcstreamthroughput-entire', 'setinterdcstreamthroughput -e 48', 'setinterdcstreamthroughput', A(args=['48'], options={'entire-sstable-throughput': True}),
    [EXIT(0), "state['storage-service-mbean@n1'].entire_sstable_inter_dc_stream_throughput_mib == 48"])
ntc('cmd-setcachecapacity', 'setcachecapacity 100 0 50 resizes the three caches', 'setcachecapacity', A(args=['100', '0', '50']),
    [EXIT(0), "calls['auto-saving-cache.set-capacity'] == 3"])
ntc('cmd-setconcurrency-core-and-max', 'setconcurrency MutationStage 16 64', 'setconcurrency', A(args=['MutationStage', '16', '64']),
    [EXIT(0), "ctx.opsStageResized == 'MutationStage:64'"])
ntc('cmd-join-not-joined', 'join on a node started with join_ring=false joins the ring', 'join', A(),
    [EXIT(0), "calls['storage-service.join-ring'] == 1"], choices={'nodetool-join.execute.joined': 'no', 'nodetool-join.execute.bootstrap_mode': 'no'})
ntc('cmd-join-bootstrapping', 'join while bootstrapping is refused', 'join', A(),
    [EXIT(1), "result.value.output == 'nodetool: Cannot join the ring until bootstrap completes'"], choices={'nodetool-join.execute.joined': 'no', 'nodetool-join.execute.bootstrap_mode': 'yes'})
ntc('cmd-removenode-status', 'removenode status prints the removal status only', 'removenode', A(args=['status']),
    [EXIT(0), "calls['storage-service.remove-node'] == 0 && result.value.output.startsWith('RemovalStatus')"])
ntc('cmd-removenode-force', 'removenode force completes a pending removal', 'removenode', A(args=['force']),
    [EXIT(0), "calls['storage-service.force-remove-completion'] == 1"])
ntc('cmd-clearsnapshot-no-tag', 'clearsnapshot without a tag or --all is refused', 'clearsnapshot', A(),
    [EXIT(1), "calls['storage-service.clear-snapshot'] == 0"])
ntc('cmd-clearsnapshot-tag-and-all', 'clearsnapshot with both a tag and --all is refused', 'clearsnapshot', A(options={'t': 'x', 'all': True}),
    [EXIT(1), "result.value.output == 'nodetool: Specify only one of snapshot name or --all'"])
ntc('cmd-replaybatchlog-io-error', 'replaybatchlog failing with IOException rethrows IOError (exit 2)', 'replaybatchlog', A(),
    [EXIT(2), "ctx.opsErrorCode == 'io-error'"], faults=[{'target': 'batchlog-manager.force-batchlog-replay', 'type': 'error', 'code': 'io-exception', 'message': 'disk'}])
ntc('cmd-resetlocalschema-io-error', 'resetlocalschema IOException is wrapped (exit 2)', 'resetlocalschema', A(),
    [EXIT(2), "ctx.opsErrorCode == 'runtime-exception'"], faults=[{'target': 'schema.reset-local-schema', 'type': 'error', 'code': 'io-exception', 'message': 'no live peers'}])
ntc('cmd-move-io-error', 'move IOException becomes "Error during moving node" (exit 2)', 'move', A(args=['100']),
    [EXIT(2), "ctx.opsErrorCode == 'runtime-exception'"], faults=[{'target': 'storage-service.move', 'type': 'error', 'code': 'io-exception', 'message': 'target token 100 is already owned by another node.'}])
ntc('cmd-assassinate-unknown-host', 'assassinate an unresolvable address wraps UnknownHostException (exit 2)', 'assassinate', A(args=['nohost']),
    [EXIT(2), "ctx.opsErrorCode == 'runtime-exception'"], faults=[{'target': 'gossiper.assassinate-endpoint', 'type': 'error', 'code': 'unknown-host-exception', 'message': 'nohost'}])
scenario('timeouts-set-all', 'nodetool-runtime-config', 'settimeout for every type updates each timeout', [
    "steps.misc.result.value.exit_status == 0 && result.value.exit_status == 0",
    "state['storage-service-mbean@n1'].timeout_read_ms == 6000 && state['storage-service-mbean@n1'].timeout_range_ms == 11000 && state['storage-service-mbean@n1'].timeout_truncate_ms == 61000",
    "state['storage-service-mbean@n1'].timeout_misc_ms == 12000 && state['storage-service-mbean@n1'].timeout_counterwrite_ms == 6000 && state['storage-service-mbean@n1'].timeout_cascontention_ms == 1500",
    "state['storage-service-mbean@n1'].timeout_internodeconnect_ms == 3000 && state['storage-service-mbean@n1'].timeout_internodeuser_ms == 40000"],
    steps=[{'flow': 'nodetool-runtime-config', 'input': {'command': 'settimeout', 'args': {'args': [t, v]}}, 'as': t} for t, v in
           [('misc', '12000'), ('read', '6000'), ('range', '11000'), ('truncate', '61000'), ('counterwrite', '6000'), ('cascontention', '1500'), ('internodeconnect', '3000'), ('internodeuser', '40000')]])
scenario('tracing-full-session', 'tracing-request-session', 'newSession, begin, then stopSession writes the start and stop rows', [
    "steps.open.result.ok && result.ok", "calls['tracing-impl.begin'] == 1 && calls['tracing-impl.stop-session-impl'] == 1",
    "state['tracing@n1'].current_session == ''"],
    steps=[{'interface': 'tracing.new-session', 'caller': 'cassandra-daemon', 'input': {'trace_type': 'QUERY'}, 'as': 'open'},
           {'flow': 'tracing-request-session', 'as': 'begin'},
           {'interface': 'tracing.stop-session', 'caller': 'cassandra-daemon', 'as': 'stop'}])
scenario('jmx-take-multiple-table-snapshot', 'jmx-operation', 'takeMultipleTableSnapshot delegates the keyspace.table list', [
    "result.ok && trace.exists(e, e.type == 'call.start' && e.interface == 'storage-service.take-snapshot' && e.input.entities == ['ks1.users', 'shop.orders'])"],
    input={'operation': 'storage-service-mbean.take-multiple-table-snapshot', 'args': {'tag': 't2', 'tables': ['ks1.users', 'shop.orders']}})

# ---------------------------------------------------------------- pin decisions that read another area's return values
# Owner-aligned stubs return random enum/boolean values in a standalone run; in the merged run the
# owner's state gives the same answer as the pin. A scenario that overrides a choice keeps its own value.
# Migration round: the owners' real state (fixtures) now drives these branches in the merged model,
# so no scenario pins them any more. A standalone run (stubs return fake values) is not deterministic here.
PINS = {}
SCEN_PINS = {}
for sc in DOC['scenarios']:
    pins = dict(PINS.get(sc['flow'], {}), **SCEN_PINS.get(sc['id'], {}))
    if pins:
        ch = dict(pins)
        ch.update(sc.get('choices') or {})
        sc['choices'] = ch

# ---------------------------------------------------------------- instances: expectations read n1's state (the default entry instance)
import re as _re
for sc in DOC['scenarios']:
    sc['expect'] = [_re.sub(r"state\['([a-z0-9-]+)'\]", lambda m: "state['%s@n1']" % m.group(1), e) for e in sc['expect']]

WRITES = {'daemon-startup', 'nodetool-hinted-handoff', 'nodetool-runtime-config', 'nodetool-audit-and-fql', 'jmx-operation', 'nodetool-command'}
for f in DOC['flows']:
    if f['id'] in WRITES:
        f['tags'] = ['writes']

# ---------------------------------------------------------------- every scenario checks state or the trace (hollow lint)
STATE_EXPECT = {
    'cmd-disablebackup': "!state['storage-service-mbean@n1'].incremental_backups",
    'cmd-enablebackup': "state['storage-service-mbean@n1'].incremental_backups",
    'cmd-disablebinary': "!state['cassandra-daemon@n1'].native_transport_running",
    'cmd-enablebinary': "state['cassandra-daemon@n1'].native_transport_running",
    'cmd-disablefullquerylog': "state['full-query-logger@n1'].bin_log_path == ''",
    'cmd-resetfullquerylog': "state['full-query-logger@n1'].bin_log_path == ''",
    'cmd-disableoldprotocolversions': "!state['storage-service-mbean@n1'].native_transport_allow_older_protocols",
    'cmd-enableoldprotocolversions': "state['storage-service-mbean@n1'].native_transport_allow_older_protocols",
    'cmd-enablehintsfordc': "state['storage-proxy-mbean@n1'].hints_disabled_dcs == []",
    'cmd-setbatchlogreplaythrottle': "state['storage-service-mbean@n1'].batchlog_replay_throttle_kib == 2048",
    'cmd-setcachekeystosave': "state['cache-service-mbean@n1'].key_cache_keys_to_save == 100 && state['cache-service-mbean@n1'].row_cache_keys_to_save == 0",
    'cmd-sethintedhandoffthrottlekb': "state['storage-service-mbean@n1'].hinted_handoff_throttle_kib == 2048",
    'cmd-setcolumnindexsize': "state['storage-service-mbean@n1'].column_index_size_kib == 16",
    'cmd-setsnapshotthrottle': "state['storage-service-mbean@n1'].snapshot_links_per_second == 100",
    'cmd-setdefaultrf': "state['storage-service-mbean@n1'].default_keyspace_rf == 3",
    'cmd-setconcurrentviewbuilders': "state['storage-service-mbean@n1'].concurrent_view_builders == 2",
    'cmd-setinterdcstreamthroughput': "state['storage-service-mbean@n1'].inter_dc_stream_throughput_mib == 48",
}
_callre = _re.compile(r"calls\['([a-z0-9.-]+)'\] (?:==|>=) ([1-9][0-9]*)")
for sc in DOC['scenarios']:
    if sc['id'] in STATE_EXPECT:
        sc['expect'].append(STATE_EXPECT[sc['id']])
        continue
    if any('state' in e or 'trace' in e for e in sc['expect']):
        continue
    hits = [m.group(1) for e in sc['expect'] for m in _callre.finditer(e)]
    flow_ = next(f for f in DOC['flows'] if f['id'] == sc['flow'])
    target = hits[-1] if hits else flow_['entry']['interface']
    sc['expect'].append("trace.exists(e, e.type == 'call.start' && e.interface == '%s' && e.instance == 'n1')" % target)

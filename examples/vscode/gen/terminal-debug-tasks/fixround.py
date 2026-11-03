"""Fix round (after judging): T1 pty data streaming, T2 replay, T3 pty-host exit, D1/D2 debug adapter
start/exit, OutputMonitor and TerminalOutputCache, feature tags. Applied by run.py after the other
modules; edits base.COMPS/IFACES/FLOWS/SCEN in place. See notes/terminal-debug-tasks.md section 11."""
import os
import base

HERE = os.path.dirname(os.path.abspath(__file__))
doc = {'configs': base.CONFIGS, 'fixtures': base.FIXTURES, 'components': base.COMPS, 'interfaces': base.IFACES,
       'flows': base.FLOWS, 'scenarios': base.SCEN}
IF = doc['interfaces']; COMPS = doc['components']; FLOWS = doc['flows']; SCEN = doc['scenarios']
CFG = doc['configs']; SEED = doc['fixtures'][0]['state']

TP = 'src/vs/platform/terminal/node/terminalProcess.ts'
PS = 'src/vs/platform/terminal/node/ptyService.ts'
PHS = 'src/vs/platform/terminal/node/ptyHostService.ts'
TDB = 'src/vs/platform/terminal/common/terminalDataBuffering.ts'
LTB = 'src/vs/workbench/contrib/terminal/electron-browser/localTerminalBackend.ts'
BTB = 'src/vs/workbench/contrib/terminal/browser/baseTerminalBackend.ts'
BP = 'src/vs/workbench/contrib/terminal/common/basePty.ts'
TPM = 'src/vs/workbench/contrib/terminal/browser/terminalProcessManager.ts'
TS = 'src/vs/workbench/contrib/terminal/browser/terminalService.ts'
RDS = 'src/vs/workbench/contrib/debug/browser/rawDebugSession.ts'
DSV = 'src/vs/workbench/contrib/debug/browser/debugService.ts'
DSE = 'src/vs/workbench/contrib/debug/browser/debugSession.ts'
DCM = 'src/vs/workbench/contrib/debug/browser/debugConfigurationManager.ts'
DAM = 'src/vs/workbench/contrib/debug/browser/debugAdapterManager.ts'
DA = 'src/vs/workbench/contrib/debug/node/debugAdapter.ts'
OM = 'src/vs/workbench/contrib/terminalContrib/chatAgentTools/browser/tools/monitoring/outputMonitor.ts'
OMT = 'src/vs/workbench/contrib/terminalContrib/chatAgentTools/browser/tools/monitoring/types.ts'
TOC = 'src/vs/workbench/contrib/terminalContrib/chatAgentTools/browser/tools/terminalOutputCache.ts'
TOCMP = 'src/vs/workbench/contrib/terminalContrib/chatAgentTools/browser/tools/terminalOutputCompressor.ts'


def iface(key):
    c, n = key.split('.', 1)
    for i in IF:
        if i['component'] == c and i['name'] == n:
            return i
    raise KeyError(key)


def comp(cid):
    for c in COMPS:
        if c['id'] == cid:
            return c
    raise KeyError(cid)


def flow(fid):
    for f in FLOWS:
        if f['id'] == fid:
            return f
    raise KeyError(fid)


def scen(sid):
    for s in SCEN:
        if s['id'] == sid:
            return s
    raise KeyError(sid)


def add_if(**kw):
    d = {'component': kw.pop('component'), 'name': kw.pop('name')}
    d.update(kw)
    IF.append(d)
    return d


def obj(**props):
    return {'type': 'object', 'properties': props}


INT = {'type': 'integer'}
STR = {'type': 'string'}
BOOL = {'type': 'boolean'}

# ---------------------------------------------------------------- configs (code constants)
CFG += [
    {'id': 'terminal-flow-control-high-watermark-chars', 'type': 'integer', 'value': 100000, 'default': 100000,
     'summary': 'Code constant: node-pty is paused once more than 100000 chars are unacknowledged by the renderer.',
     'sources': ['src/vs/platform/terminal/common/terminal.ts:897', TP + ':333-341'],
     'attributes': {'key': 'FlowControlConstants.HighWatermarkChars', 'constant': True}},
    {'id': 'terminal-data-buffer-throttle-ms', 'type': 'integer', 'value': 5, 'default': 5,
     'summary': 'Code constant: TerminalDataBufferer coalesces pty data for 5 ms before firing one event to the renderer.',
     'sources': [TDB + ':28-50', PS + ':829-830'],
     'attributes': {'key': 'TerminalDataBufferer.startBuffering throttleBy', 'constant': True}},
    {'id': 'debug-disconnect-error-timeout-ms', 'type': 'integer', 'value': 200, 'default': 200,
     'summary': 'Code constant: on shutdown with an error the adapter is probably gone, so disconnect waits only 200 ms (2000 ms otherwise).',
     'sources': [RDS + ':605-606'], 'attributes': {'key': 'RawDebugSession.shutdown error timeout', 'constant': True}},
    {'id': 'output-monitor-min-polling-ms', 'type': 'integer', 'value': 500, 'default': 500,
     'summary': 'Code constant PollingConsts.MinPollingDuration: the first OutputMonitor poll interval; it doubles up to 10 s.',
     'sources': [OMT + ':47', OM + ':484-501'], 'attributes': {'key': 'PollingConsts.MinPollingDuration', 'constant': True}},
    {'id': 'output-monitor-max-polling-interval-ms', 'type': 'integer', 'value': 10000, 'default': 10000,
     'summary': 'Code constant PollingConsts.MaxPollingIntervalDuration: the poll interval stops doubling at 10 s.',
     'sources': [OMT + ':50', OM + ':484-501'], 'attributes': {'key': 'PollingConsts.MaxPollingIntervalDuration', 'constant': True}},
    {'id': 'output-monitor-first-polling-max-ms', 'type': 'integer', 'value': 20000, 'default': 20000,
     'summary': 'Code constant PollingConsts.FirstPollingMaxDuration: the first idle wait gives up (Timeout) after 20 s.',
     'sources': [OMT + ':48', OM + ':483'], 'attributes': {'key': 'PollingConsts.FirstPollingMaxDuration', 'constant': True}},
    {'id': 'output-monitor-extended-polling-max-ms', 'type': 'integer', 'value': 120000, 'default': 120000,
     'summary': 'Code constant PollingConsts.ExtendedPollingMaxDuration: an extended idle wait gives up after 2 min.',
     'sources': [OMT + ':49', OM + ':483'], 'attributes': {'key': 'PollingConsts.ExtendedPollingMaxDuration', 'constant': True}},
    {'id': 'output-monitor-min-idle-events', 'type': 'integer', 'value': 2, 'default': 2,
     'summary': 'Code constant PollingConsts.MinIdleEvents: two polls without new data mean the terminal is idle.',
     'sources': [OMT + ':46', OM + ':531-538'], 'attributes': {'key': 'PollingConsts.MinIdleEvents', 'constant': True}},
]

# ---------------------------------------------------------------- T1: pty data path (yield)
comp('pty-service')['state']['initial']  # exists
comp('local-terminal-backend')['state']['initial']['has_started'] = False
comp('local-terminal-backend')['state']['initial']['pty_host_exited_at'] = None
comp('local-terminal-backend')['state']['schema']['properties']['has_started'] = BOOL
comp('local-terminal-backend')['state']['schema']['properties']['pty_host_exited_at'] = {'type': ['integer', 'null']}
comp('terminal-process-manager')['state'] = {
    'initial': {'procs': {}},
    'schema': {'type': 'object', 'properties': {'procs': {'type': 'object'}}}}
comp('terminal-process-manager')['summary'] += ' Per process it keeps the launch config, the process state and the data written to xterm (keyed by persistent process id).'

add_if(component='terminal-process', name='on-process-data', kind='stream',
       summary='node-pty onData: each chunk counts against flow control (pause past the high watermark) and is re-fired as onProcessData.',
       sources=[TP + ':333-348'],
       request=obj(chunks={'type': 'array', 'items': STR, 'default': ['$ ']}),
       response=obj(chars=INT, paused=BOOL),
       behavior=[
           {'set': {'vars.unacked': 0, 'vars.paused': False}},
           {'foreach': '= input.chunks', 'as': 'chunk', 'steps': [
               {'set': {'vars.unacked': '= vars.unacked + size(vars.chunk)'}},
               {'if': "!vars.paused && vars.unacked > config['terminal-flow-control-high-watermark-chars']", 'then': [
                   {'title': 'Flow control: pause node-pty until the renderer acknowledges', 'source': TP + ':336-340',
                    'set': {'vars.paused': True}}]},
               {'title': "_onProcessData.fire(data)", 'source': TP + ':342-344', 'yield': {'data': '= vars.chunk'}}]},
           {'return': {'chars': '= vars.unacked', 'paused': '= vars.paused'}}])

add_if(component='pty-service', name='on-process-data', kind='stream',
       summary='PersistentTerminalProcess: TerminalDataBufferer coalesces the shell\'s data for 5 ms, the serializer records it for replay, and PtyService re-fires it as {id, event}.',
       sources=[PS + ':353', PS + ':828-833', TDB + ':28-50', PS + ':1079-1082'],
       request=obj(id=INT, chunks={'type': 'array', 'items': STR, 'default': ['$ ']}),
       response=obj(events=INT),
       errors=[{'code': 'could-not-find-pty-on-pty-host', 'status': 0, 'retryable': False}],
       behavior=[
           {'if': "!(string(input.id) in state.ptys)", 'then': [
               {'title': '_throwIfNoPty', 'source': PS + ':679-685',
                'fail': {'code': 'could-not-find-pty-on-pty-host', 'message': "= 'Could not find pty ' + string(input.id) + ' on pty host'"}}]},
           {'set': {'vars.pending': ''}},
           {'call': 'terminal-process.on-process-data', 'input': {'chunks': '= input.chunks'}, 'stream': True,
            'on_item': [{'set': {'vars.pending': '= vars.pending + vars.item.data'}}], 'as': 'proc'},
           {'title': 'Bufferer flush after throttleBy: data that arrived within the window is one event', 'source': TDB + ':38-50',
            'wait': "= config['terminal-data-buffer-throttle-ms']"},
           {'if': "!(string(input.id) in state.ptys) || vars.pending == ''", 'then': [{'return': {'events': 0}}]},
           {'title': 'Data recording for reconnect: the serializer keeps what the renderer was sent', 'source': PS + ':832-833',
            'set': {'state.ptys': "= merge(state.ptys, {string(input.id): {'replay_buffer': (has(state.ptys[string(input.id)].replay_buffer) ? state.ptys[string(input.id)].replay_buffer : '') + vars.pending}})"}},
           {'title': 'PtyService re-fires onProcessData {id, event}', 'source': PS + ':353',
            'yield': {'id': '= input.id', 'event': '= vars.pending'}},
           {'return': {'events': 1}}])

add_if(component='local-terminal-backend', name='listen-process-data', kind='function',
       summary='The direct proxy\'s onProcessData listener: route each {id, event} to the LocalPty with that id (dropped when the window has no such pty).',
       sources=[LTB + ':152'],
       request=obj(id=INT, chunks={'type': 'array', 'items': STR, 'default': ['$ ']}),
       response=obj(delivered=INT),
       behavior=[
           {'set': {'vars.n': 0}},
           {'call': 'pty-service.on-process-data', 'input': {'id': '= input.id', 'chunks': '= input.chunks'}, 'stream': True,
            'on_error': 'continue', 'as': 'src',
            'on_item': [
                {'if': 'string(vars.item.id) in state.ptys', 'then': [
                    {'call': 'local-pty.handle-data', 'input': {'id': '= vars.item.id', 'data': '= vars.item.event'}},
                    {'set': {'vars.n': '= vars.n + 1'}}]}]},
           {'return': {'delivered': '= vars.n'}}])

add_if(component='local-pty', name='handle-data', kind='function',
       summary='BasePty.handleData: fire onProcessData to the TerminalProcessManager listening on this pty.',
       sources=[BP + ':63-65'],
       request=obj(id=INT, data=STR), response={'type': 'object'},
       behavior=[{'call': 'terminal-process-manager.on-process-data', 'input': {'id': '= input.id', 'data': '= input.data'}}])

add_if(component='local-pty', name='handle-replay', kind='function',
       summary='BasePty.handleReplay: apply each replay event\'s size override and write its data (trackCommit) to the terminal, then fire onProcessReplayComplete.',
       sources=[BP + ':90-116'],
       request=obj(id=INT, events={'type': 'array', 'items': {'type': 'object'}}), response=obj(chars=INT),
       behavior=[
           {'set': {'vars.chars': 0}},
           {'foreach': '= input.events', 'as': 'ev', 'steps': [
               {'call': 'terminal-process-manager.on-process-data', 'input': {'id': '= input.id', 'data': '= vars.ev.data'}},
               {'set': {'vars.chars': '= vars.chars + size(vars.ev.data)'}}]},
           {'title': 'onProcessReplayComplete', 'source': BP + ':114-115',
            'set': {'ctx.terminal_replay_complete': '= input.id'}},
           {'return': {'chars': '= vars.chars'}}])

add_if(component='terminal-process-manager', name='on-process-data', kind='function',
       summary='The data filter\'s onProcessData: onBeforeProcessData may rewrite it, then onProcessData writes it to xterm (kept here as the process\'s written output).',
       sources=[TPM + ':174-186'],
       request=obj(id=INT, data=STR), response=obj(written=INT),
       behavior=[
           {'if': '!(string(input.id) in state.procs) || input.data == ""', 'then': [{'return': {'written': 0}}]},
           {'set': {'state.procs': "= merge(state.procs, {string(input.id): {'output': state.procs[string(input.id)].output + input.data}})"}},
           {'return': {'written': '= size(input.data)'}}])

add_if(component='terminal-process-manager', name='get-output', kind='function',
       summary='What an execution\'s getOutput() reads back: the text written to the instance\'s xterm buffer for this process.',
       sources=['src/vs/workbench/contrib/terminalContrib/chatAgentTools/browser/outputHelpers.ts:96-98', 'src/vs/workbench/contrib/terminalContrib/chatAgentTools/browser/taskHelpers.ts:246'],
       request=obj(id=INT), response=obj(output=STR, length=INT),
       errors=[{'code': 'no-such-terminal', 'status': 0, 'retryable': False}],
       behavior=[
           {'if': '!(string(input.id) in state.procs)', 'then': [{'fail': {'code': 'no-such-terminal', 'message': 'No terminal for the execution'}}]},
           {'return': {'output': '= state.procs[string(input.id)].output', 'length': '= size(state.procs[string(input.id)].output)'}}])

# create-process: remember the process; after a fresh launch the shell's output starts flowing
cp = iface('terminal-process-manager.create-process')
beh = cp['behavior']
# insert before the final return (last element) and in the launch-error return path leave as is
reg = {'title': 'Listen to the process before start(): remember its launch config and state', 'source': TPM + ':386-443',
       'set': {'state.procs': "= merge(state.procs, {string(vars.pid): {'executable': has(input.executable) ? input.executable : '', 'cwd': has(input.cwd) ? input.cwd : 'file:///work/app', "
                              "'is_feature_terminal': input.is_feature_terminal, 'has_reconnection': input.reconnection_properties != null, 'process_state': 'running', 'exit_code': null, "
                              "'disconnected': false, 'output': string(vars.pid) in state.procs ? state.procs[string(vars.pid)].output : '', 'slc': input}})"}}
listen = {'title': 'The shell writes its prompt: node-pty data flows to the renderer through the direct proxy', 'source': LTB + ':152',
          'when': '!vars.attached', 'emit': 'local-terminal-backend.listen-process-data', 'input': {'id': '= vars.pid', 'chunks': ['$ ']}}
start_i = next(i for i, s in enumerate(beh) if s.get('call') == 'local-pty.start')
beh.insert(start_i, reg)
beh.insert(len(beh) - 1, listen)

# ---------------------------------------------------------------- T2: replay to the renderer
add_if(component='pty-service', name='trigger-replay', kind='function',
       summary='triggerReplay: an untouched process becomes ReplayOnly; the serializer\'s replay event is fired as onProcessReplay {id, event} to the window.',
       sources=[PS + ':957-972', PS + ':354', PS + ':1095-1110'],
       request=obj(id=INT), response=obj(chars=INT),
       behavior=[
           {'set': {'vars.p': '= state.ptys[string(input.id)]'}},
           {'when': "vars.p.interaction == 'None'", 'set': {'state.ptys': "= merge(state.ptys, {string(input.id): {'interaction': 'ReplayOnly'}})"}},
           {'set': {'vars.data': "= has(vars.p.replay_buffer) ? vars.p.replay_buffer : ''"}},
           {'title': '_onProcessReplay.fire(ev) -> PtyService onProcessReplay {id, event}', 'source': PS + ':967',
            'publish': 'pty-service.on-process-replay', 'delivery': 'sync', 'on': 'w1',
            'input': {'id': '= input.id', 'events': [{'cols': 80, 'rows': 30, 'data': '= vars.data'}]}},
           {'return': {'chars': '= size(vars.data)'}}])
add_if(component='pty-service', name='on-process-replay', kind='event',
       summary='PtyService.onProcessReplay: {id, event: IPtyHostProcessReplayEvent}.', sources=[PS + ':129-130'],
       request=obj(id=INT, events={'type': 'array', 'items': {'type': 'object'}}))
add_if(component='local-terminal-backend', name='on-process-replay', kind='function',
       summary='The direct proxy\'s onProcessReplay listener: hand the replay to the LocalPty with that id.',
       sources=[LTB + ':163'], subscribe=['pty-service.on-process-replay'],
       request=obj(id=INT, events={'type': 'array', 'items': {'type': 'object'}}), response={'type': 'object'},
       behavior=[{'if': 'string(input.id) in state.ptys', 'then': [
           {'call': 'local-pty.handle-replay', 'input': {'id': '= input.id', 'events': '= input.events'}}]}])

st = iface('pty-service.start')
for i, s in enumerate(st['behavior']):
    if s.get('if') == 'vars.p.started':
        s['then'] = [
            {'title': 'Already started: fire ready and replay the buffer', 'source': PS + ':889-893',
             'call': 'pty-service.trigger-replay', 'input': {'id': '= input.id'}},
            {'return': {'pid': '= vars.p.pid'}}]
# revived processes replay on their first start (ptyService.ts:883)
st['behavior'].insert(len(st['behavior']) - 1, {
    'title': 'A revived process replays its buffer on first start', 'source': PS + ':883',
    'if': 'vars.p.was_revived', 'then': [{'call': 'pty-service.trigger-replay', 'input': {'id': '= input.id'}}]})

# ---------------------------------------------------------------- T3: pty host exit
add_if(component='pty-host-service', name='pty-host-exit', kind='event',
       summary='onPtyHostExit(code), fired before any restart.', sources=[PHS + ':162'], request=obj(code=INT))
add_if(component='pty-host-service', name='on-pty-host-start', kind='event',
       summary='onPtyHostStart, fired at the end of every _startPtyHost.', sources=[PHS + ':189'], request={'type': 'object'})
ex = iface('pty-host-service.on-pty-host-exit')
ex['behavior'] = [
    {'set': {'state.started': False}},
    {'title': 'The pty host process is gone: every pty and the PtyService state die with it', 'source': PHS + ':161-162',
     'restart': {'component': 'pty-service'}},
    {'title': '_onPtyHostExit.fire(code)', 'source': PHS + ':162', 'publish': 'pty-host-service.pty-host-exit', 'delivery': 'sync', 'on': 'w1',
     'input': {'code': '= input.code'}},
] + ex['behavior'][1:]
sp = iface('pty-host-service.start-pty-host')
sp['behavior'].append({'title': '_onPtyHostStart.fire()', 'source': PHS + ':189', 'publish': 'pty-host-service.on-pty-host-start',
                       'delivery': 'sync', 'on': 'w1', 'input': {}})

ctp = iface('local-terminal-backend.connect-to-direct-proxy')
ctp['behavior'][-1]['set']['state.has_started'] = True
ctp['behavior'][-1]['title'] = 'Port acquired: onPtyHostConnected marks the backend started'
ctp['behavior'][-1]['source'] = LTB + ':137-148'

add_if(component='local-terminal-backend', name='on-pty-host-exit', kind='function',
       summary='BaseTerminalBackend logs that the pty host exited and the connection to all terminal processes was lost.',
       sources=[BTB + ':46-48'], subscribe=['pty-host-service.pty-host-exit'], request=obj(code=INT), response={'type': 'object'},
       behavior=[{'set': {'state.pty_host_exited_at': '= now'}},
                 {'call': 'terminal-log-service.warn', 'input': {'message': "The terminal's pty host process exited, the connection to all terminal processes was lost"}}])
add_if(component='local-terminal-backend', name='on-pty-host-start', kind='function',
       summary='BaseTerminalBackend: once the backend has connected before, a pty host start is a restart: fire onPtyHostRestart.',
       sources=[BTB + ':49-59'], subscribe=['pty-host-service.on-pty-host-start'], request={'type': 'object'}, response=obj(restart=BOOL),
       behavior=[
           {'if': '!state.has_started', 'then': [{'return': {'restart': False}}]},
           {'title': '_onPtyHostRestart.fire()', 'source': BTB + ':54-56', 'publish': 'local-terminal-backend.on-pty-host-restart', 'delivery': 'sync', 'input': {}},
           {'return': {'restart': True}}])
add_if(component='local-terminal-backend', name='on-pty-host-restart', kind='event',
       summary='onPtyHostRestart.', sources=[BTB + ':55'], request={'type': 'object'})
add_if(component='local-terminal-backend', name='reconnect-direct-proxy', kind='function',
       summary='LocalTerminalBackend drops its direct proxy on onPtyHostRestart and connects to the new pty host.',
       sources=[LTB + ':104-108'], subscribe=['local-terminal-backend.on-pty-host-restart'], request={'type': 'object'}, response={'type': 'object'},
       behavior=[{'set': {'state.direct_proxy': False}}, {'call': 'local-terminal-backend.connect-to-direct-proxy'}])

add_if(component='terminal-process-manager', name='on-pty-host-restart', kind='function',
       summary='Each process manager on onPtyHostRestart: mark disconnected; a feature terminal without reconnection properties (a task) exits -1, a normal terminal prints the restart message and relaunches its shell.',
       sources=[TPM + ':589-617', TPM + ':459-474'], subscribe=['local-terminal-backend.on-pty-host-restart'],
       request={'type': 'object'}, response=obj(relaunched=INT, exited=INT),
       behavior=[
           {'set': {'vars.relaunched': 0, 'vars.exited': 0,
                    'vars.live': "= state.procs.filter(k, state.procs[k].process_state == 'running')"}},
           {'foreach': '= vars.live', 'as': 'k', 'steps': [
               {'set': {'vars.p': '= state.procs[vars.k]'}},
               {'if': 'vars.p.is_feature_terminal && !vars.p.has_reconnection', 'then': [
                   {'title': 'Feature terminal (task): report the process exited with -1', 'source': TPM + ':598-605',
                    'set': {'state.procs': "= merge(state.procs, {vars.k: {'disconnected': true, 'process_state': 'killed-by-process', 'exit_code': -1}})"}},
                   {'publish': 'terminal-process-manager.on-process-exit', 'delivery': 'sync',
                    'input': {'persistent_process_id': '= int(vars.k)', 'exit_code': -1}},
                   {'set': {'vars.exited': '= vars.exited + 1'}}],
                'else': [
                   {'title': 'Normal terminal: write the restart message, then relaunch with the previous shell launch config', 'source': TPM + ':606-615',
                    'set': {'state.procs': "= merge(state.procs, {vars.k: {'disconnected': true, 'output': vars.p.output + 'Restarting the terminal because the connection to the shell process was lost...'}})"}},
                   {'set': {'vars.old_output': '= state.procs[vars.k].output'}},
                   {'set': {'state.procs': '= omit(state.procs, vars.k)'}},
                   {'call': 'terminal-process-manager.create-process', 'input': "= merge(vars.p.slc, {'attach_persistent_process': null})", 'as': 'rl'},
                   {'set': {'state.procs': "= merge(state.procs, {string(vars.rl.value.persistent_process_id): {'output': vars.old_output}})"}},
                   {'title': 'onAnyInstanceProcessIdReady: the instance now points at the new process', 'source': TS + ':564',
                    'publish': 'terminal-process-manager.on-process-id-ready', 'delivery': 'sync',
                    'input': {'old_id': '= int(vars.k)', 'new_id': '= vars.rl.value.persistent_process_id'}},
                   {'set': {'vars.relaunched': '= vars.relaunched + 1'}}]}]},
           {'return': {'relaunched': '= vars.relaunched', 'exited': '= vars.exited'}}])
add_if(component='terminal-process-manager', name='on-process-exit', kind='event',
       summary='onProcessExit(exitCode).', sources=[TPM + ':604'], request=obj(persistent_process_id=INT, exit_code=INT))
add_if(component='terminal-process-manager', name='on-process-id-ready', kind='event',
       summary='onProcessReady after a relaunch, re-fired by the service as onAnyInstanceProcessIdReady.', sources=[TS + ':564'],
       request=obj(old_id=INT, new_id=INT))
add_if(component='terminal-service', name='on-any-instance-process-exit', kind='function',
       summary='An instance\'s process exited: record the exit code on the instance (task terminals see their process gone).',
       sources=[TPM + ':598-605'], subscribe=['terminal-process-manager.on-process-exit'],
       request=obj(persistent_process_id=INT, exit_code=INT), response=obj(updated=INT),
       behavior=[
           {'set': {'vars.ks': '= state.instances.filter(k, state.instances[k].persistent_process_id == input.persistent_process_id)'}},
           {'foreach': '= vars.ks', 'as': 'k', 'steps': [
               {'set': {'state.instances': "= merge(state.instances, {vars.k: {'process_state': 'killed-by-process', 'exit_code': input.exit_code}})"}}]},
           {'return': {'updated': '= size(vars.ks)'}}])
add_if(component='terminal-service', name='on-any-instance-process-id-ready', kind='function',
       summary='onAnyInstanceProcessIdReady: point the instance at its new persistent process and save the layout (debounced).',
       sources=[TS + ':561-564'], subscribe=['terminal-process-manager.on-process-id-ready'],
       request=obj(old_id=INT, new_id=INT), response=obj(updated=INT),
       behavior=[
           {'set': {'vars.ks': '= state.instances.filter(k, state.instances[k].persistent_process_id == input.old_id)'}},
           {'foreach': '= vars.ks', 'as': 'k', 'steps': [
               {'set': {'state.instances': "= merge(state.instances, {vars.k: {'persistent_process_id': input.new_id, 'process_state': 'running'}})"}}]},
           {'when': 'state.layout_listeners_attached', 'emit': 'terminal-service.save-state',
            'after_ms': "= config['terminal-save-state-debounce-ms']", 'input': {'scheduled_at': '= now'}},
           {'return': {'updated': '= size(vars.ks)'}}])

# ---------------------------------------------------------------- D1: adapter start, onDebugResolve activation, selection
add_if(component='adapter-manager', name='activate-debuggers', kind='function',
       summary='activateDebuggers(event, type): activate `event`, `onDebug` and `event:type` in parallel (Promise.all).',
       sources=[DAM + ':488-499'],
       request=obj(activation_event=STR, debug_type=STR), response=obj(activated=INT),
       behavior=[
           {'set': {'vars.events': "= [input.activation_event, 'onDebug'] + (has(input.debug_type) && input.debug_type != '' ? [input.activation_event + ':' + input.debug_type] : [])"}},
           {'parallel': '= vars.events', 'as': 'ev', 'join': {'need': 'all'}, 'as_result': 'acts', 'steps': [
               {'call': 'extension-service.activate-by-event', 'input': {'activation_event': '= vars.ev', 'activation_kind': 'normal'}}]},
           {'return': {'activated': '= vars.acts.received'}}])
rc = iface('configuration-manager.resolve-configuration-by-providers')
rc['summary'] = 'For the config\'s type, then "*": activate onDebugResolve (not for "*") and run the providers\' resolveDebugConfiguration (none registered in the base world, so the config comes back as is).'
rc['sources'] = [DCM + ':148-173']
rc['behavior'] = [
    {'set': {'vars.type': "= has(input.config.type) ? input.config.type : ''"}},
    {'title': "activateDebuggers('onDebugResolve', type) before the type's providers run", 'source': DCM + ':150-152',
     'call': 'adapter-manager.activate-debuggers', 'input': {'activation_event': 'onDebugResolve', 'debug_type': '= vars.type'}},
    {'set': {'vars.providers': "= has(state.config_providers) ? state.config_providers.filter(p, p == vars.type || p == '*') : []"}},
    {'if': 'size(vars.providers) > 0', 'then': [
        {'title': 'resolveDebugConfiguration of each matching provider (extension host)', 'source': DCM + ':154-158',
         'call': 'extension-service.activate-by-event', 'input': {'activation_event': "= 'onDebugResolve:' + vars.type", 'activation_kind': 'normal'}}]},
    {'return': {'config': '= input.config'}}]

gs = iface('configuration-manager.get-selected-configuration')
gs['behavior'] = [{'return': {'name': "= has(state.selected) ? state.selected : null",
                              'config': "= has(state.selected) && state.selected != null && state.selected in state.launch_configurations ? state.launch_configurations[state.selected] : null"}}]
sc = iface('configuration-manager.select-configuration')
sc['behavior'] = [
    {'set': {'vars.names': '= state.launch_configurations.map(k, k)'}},
    {'if': 'has(input.name) && input.name in state.launch_configurations', 'then': [
        {'set': {'state.selected': '= input.name'}}],
     'else': [
        {'title': 'Name not found: pick the first configuration, or reset the selection when there is none', 'source': DCM + ':476-481',
         'set': {'state.selected': '= size(vars.names) > 0 ? vars.names[0] : null'}}]},
    {'return': {'selected': '= state.selected'}}]
sc['response'] = obj(selected={'type': ['string', 'null']})
# ConfigurationManager's constructor selects the first launch.json configuration at startup.
SEED['configuration-manager']['selected'] = 'Launch Program'

dss = iface('debug-adapter.start-session')
dss['summary'] = 'ExecutableDebugAdapter.startSession: check the adapter executable, fork or spawn it, wire its exit/error, connect over stdio. Called by the extension host\'s $startDASession.'
dss['request'] = obj(handle=INT, session_id=STR, type=STR, command={'type': 'string', 'default': 'node'})
dss['errors'] = [{'code': 'cannot-determine-executable-for-debug-adapter', 'status': 0, 'retryable': False}]
dss['response'] = obj(pid=INT)
dss['behavior'] = [
    {'if': "has(input.command) && input.command == ''", 'then': [
        {'title': "Cannot determine executable for debug adapter (fired as onError)", 'source': DA + ':268-271',
         'fail': {'code': 'cannot-determine-executable-for-debug-adapter', 'message': "= 'Cannot determine executable for debug adapter ' + input.type"}}]},
    {'title': 'fork/spawn the adapter process, wire exit and error, connect stdio', 'source': DA + ':278-336',
     'set': {'state.running': "= merge(has(state.running) ? state.running : {}, {string(has(input.handle) ? input.handle : 1): {'session_id': has(input.session_id) ? input.session_id : '', 'type': has(input.type) ? input.type : '', 'pid': 5151}})"}},
    {'return': {'pid': 5151}}]
dst = iface('debug-adapter.stop-session')
dst['request'] = obj(handle=INT)
dst['behavior'] = [
    {'title': 'No process: nothing to stop', 'source': DA + ':346-348', 'if': "!has(state.running) || !(string(has(input.handle) ? input.handle : 1) in state.running)", 'then': [{'return': {}}]},
    {'title': 'kill(SIGTERM) the adapter process', 'source': DA + ':356-358',
     'set': {'state.running': '= omit(state.running, string(has(input.handle) ? input.handle : 1))'}}]

# ---------------------------------------------------------------- D2: adapter exit
add_if(component='raw-debug-session', name='on-adapter-exit', kind='function',
       summary='debugAdapter.onExit: a non-zero code shuts down with Error("exit code: N"), code 0 shuts down normally.',
       sources=[RDS + ':100-107'], request=obj(session_id={'type': 'string', 'examples': ['session-1']}, code={'type': 'integer', 'examples': [1]}),
       response={'type': 'object'},
       behavior=[
           {'if': 'input.code != 0', 'then': [
               {'call': 'raw-debug-session.shutdown', 'input': {'session_id': '= input.session_id', 'error': "= 'exit code: ' + string(input.code)"}}],
            'else': [
               {'title': 'normal exit', 'source': RDS + ':103-105', 'call': 'raw-debug-session.shutdown', 'input': {'session_id': '= input.session_id'}}]}])
add_if(component='raw-debug-session', name='on-adapter-error', kind='function',
       summary='debugAdapter.onError: shut down with the error.', sources=[RDS + ':96-98'],
       request=obj(session_id={'type': 'string', 'examples': ['session-1']}, message={'type': 'string', 'examples': ['read error']}),
       response={'type': 'object'},
       behavior=[{'call': 'raw-debug-session.shutdown', 'input': {'session_id': '= input.session_id', 'error': '= input.message'}}])

sd = iface('raw-debug-session.shutdown')
sd['summary'] = 'shutdown(error?): send disconnect (200 ms with an error, else 2 s; errors swallowed), stop the adapter, then fire the adapter exit event. The error travels with it only if stopping the adapter failed.'
sd['sources'] = [RDS + ':592-617', RDS + ':619-645']
sd['request']['properties']['error'] = {'type': ['string', 'null'], 'default': None}
for s in sd['behavior']:
    if s.get('call') == 'raw-debug-session.send':
        s['input']['timeout_ms'] = "= has(input.error) && input.error != null ? config['debug-disconnect-error-timeout-ms'] : config['debug-disconnect-timeout-ms']"
        s['input']['arguments']['terminateDebuggee'] = '= has(input.terminate_debuggee) ? input.terminate_debuggee : null'
        s['title'] = 'disconnect: with an error the DA is probably gone, so a much shorter timeout'
        s['source'] = RDS + ':605-606'
    if s.get('call') == 'ext-host-debug-service.stop-da-session':
        s['on_error'] = 'continue'
        s['as'] = 'stop'
    if s.get('call') == 'debug-session.on-did-exit-adapter':
        s['title'] = 'fireAdapterExitEvent: e.error only when the adapter could not be stopped'
        s['source'] = RDS + ':632-645'
        s['input']['error'] = "= has(input.error) && input.error != null && !vars.stop.ok ? input.error : null"
# set adapter_running false only when stop succeeded? code nulls debugAdapter regardless.
oda = iface('debug-session.on-did-exit-adapter')
oda['request']['properties']['error'] = {'type': ['string', 'null'], 'default': None}
for s in oda['behavior']:
    if s.get('call') == 'debug-service.on-did-end-adapter':
        s['input']['error'] = "= has(input.error) ? input.error : null"
oea = iface('debug-service.on-did-end-adapter')
oea['sources'] = [DSV + ':749-800']
oea['summary'] = 'A session\'s adapter ended: an exit event with an error shows "Debug adapter process has terminated unexpectedly"; run postDebugTask, end initializing state.'
oea['request']['properties']['error'] = {'type': ['string', 'null'], 'default': None}
oea['behavior'].insert(0, {'if': 'has(input.error) && input.error != null', 'then': [
    {'title': 'notificationService.error(debugAdapterCrash)', 'source': DSV + ':751-753',
     'call': 'notification-service.notify',
     'input': {'severity': 'error', 'message': "= 'Debug adapter process has terminated unexpectedly (' + input.error + ')'", 'source': 'debug'}}]})
IF.append({'component': 'notification-service', 'name': 'notify', 'kind': 'function', 'attributes': {'boundary': True, 'owner': 'workbench-shell'},
           'summary': 'Show a notification. (contract copied from the owner fragment)',
           'request': {'type': 'object', 'required': ['severity', 'message'], 'properties': {
               'message': {'type': 'string', 'examples': ['Extension host terminated unexpectedly.']},
               'severity': {'type': 'string', 'enum': ['info', 'warning', 'error'], 'examples': ['info']},
               'source': {'type': 'string'}}},
           'response': {'type': 'object', 'properties': {'id': {'type': 'integer'}, 'silent': {'type': 'boolean'}}}})
if not any(c['id'] == 'notification-service' for c in COMPS):
    COMPS.append({'id': 'notification-service', 'name': 'NotificationService', 'kind': 'service', 'parent': 'workbench',
                  'summary': 'Boundary reference to a component owned by workbench-shell.', 'attributes': {'boundary': True, 'owner': 'workbench-shell'}})

# ---------------------------------------------------------------- OutputMonitor and TerminalOutputCache
COMPS.append({'id': 'output-monitor', 'name': 'OutputMonitor', 'kind': 'module', 'layer': 'workbench', 'parent': 'terminal-contrib',
              'sources': [OM + ':61'], 'attributes': {'owner': 'terminal-debug-tasks'},
              'summary': 'Watches a run-in-terminal (or task) execution for the chat agent: polls its output with exponential backoff until it is idle, needs input, times out or is cancelled.',
              'state': {'initial': {'runs': {}}, 'schema': {'type': 'object', 'properties': {'runs': {'type': 'object'}}}}})
COMPS.append({'id': 'terminal-output-cache', 'name': 'TerminalOutputCache', 'kind': 'module', 'layer': 'workbench', 'parent': 'terminal-contrib',
              'sources': [TOC + ':163', TOCMP + ':670'], 'attributes': {'owner': 'terminal-debug-tasks'},
              'summary': 'Session dedup cache for run_in_terminal results, keyed by cwd::command, with a TTL per command class (fast 30 s, medium 2 min, slow 5 min) and invalidation by mutating commands. Registered with the chat tool-result compressor.',
              'state': {'initial': {'entries': {}}, 'schema': {'type': 'object', 'properties': {'entries': {'type': 'object'}}}}})

CLASSIFY = ("= vars.head == 'git' ? (vars.sub.matches('^(add|commit|push|pull|fetch|merge|rebase|reset|checkout|switch|restore|cherry-pick|revert|stash|tag|branch|am|apply|clean|rm|mv)$') ? {'cls': '', 'invalidates': ['git']} "
            ": (vars.sub in ['status', 'diff', 'show', 'blame'] ? {'cls': 'fast', 'invalidates': []} : (vars.sub in ['log', 'reflog', 'shortlog'] ? {'cls': 'slow', 'invalidates': []} : {'cls': '', 'invalidates': []}))) "
            ": (vars.head in ['ls', 'pwd'] ? {'cls': 'fast', 'invalidates': []} : (vars.head in ['find', 'tree', 'env', 'printenv'] ? {'cls': 'slow', 'invalidates': []} "
            ": (vars.head in ['npm', 'pnpm', 'yarn'] ? (vars.sub in ['install', 'i', 'ci', 'add', 'remove', 'uninstall', 'update'] ? {'cls': '', 'invalidates': ['npm', 'pnpm', 'yarn']} "
            ": (vars.sub in ['ls', 'list', 'outdated'] ? {'cls': 'slow', 'invalidates': []} : (vars.sub in ['test', 'run', ''] ? {'cls': 'medium', 'invalidates': []} : {'cls': '', 'invalidates': []}))) "
            ": (vars.head in ['pytest', 'jest', 'vitest'] || (vars.head == 'go' && vars.sub in ['test', 'build', 'vet']) || (vars.head == 'cargo' && vars.sub in ['test', 'nextest', 'check', 'build']) ? {'cls': 'medium', 'invalidates': []} : {'cls': '', 'invalidates': []}))))")
PARSE = [
    {'set': {'vars.cmd': "= has(input.command) ? input.command.trim() : ''", 'vars.cwd': "= has(input.cwd) ? input.cwd : ''"}},
    {'set': {'vars.compound': "= vars.cmd.matches(r'&&|\\|\\||;|\\|')",
             'vars.words': "= vars.cmd.split(' ').filter(w, w != '')"}},
    {'set': {'vars.head': "= size(vars.words) > 0 ? vars.words[0] : ''", 'vars.sub': "= size(vars.words) > 1 ? vars.words[1] : ''"}},
    {'title': 'parseCommand/segmentHead: split the command line into segments and take the program and subcommand', 'source': 'src/vs/workbench/contrib/terminalContrib/chatAgentTools/browser/tools/terminalCommandParser.ts:276-324', 'set': {'vars.parsed': True}},
    {'title': 'classifyCommand: cache class and the programs a command invalidates (compound commands are never cached)', 'source': TOC + ':52-148',
     'set': {'vars.c': CLASSIFY}},
    {'when': 'vars.compound', 'set': {'vars.c': "= {'cls': '', 'invalidates': vars.c.invalidates}"}},
]
CACHE_REQ = obj(tool_id={'type': 'string', 'default': 'run_in_terminal'}, command={'type': 'string', 'examples': ['git status']},
                cwd={'type': 'string', 'examples': ['/work/app']})
add_if(component='terminal-output-cache', name='record', kind='function',
       summary='record: store the output of a cacheable command under cwd::command with its class and the time (oldest dropped past 256 entries).',
       sources=[TOC + ':212-238'],
       request={'type': 'object', 'properties': dict(CACHE_REQ['properties'], text={'type': 'string', 'examples': ['clean']})},
       response=obj(recorded=BOOL),
       behavior=[{'if': "!has(input.command) || input.command.trim() == ''", 'then': [{'title': 'getInput: no command', 'source': TOC + ':150-160', 'return': {'recorded': False}}]}]
       + PARSE + [
           {'if': "vars.c.cls == ''", 'then': [{'return': {'recorded': False}}]},
           {'set': {'vars.key': "= vars.cwd + '::' + vars.cmd"}},
           {'set': {'state.entries': "= merge(omit(state.entries, vars.key), {vars.key: {'cwd': vars.cwd, 'command': vars.cmd, 'head': vars.head, 'text': input.text, 'timestamp': now, 'cls': vars.c.cls}})"}},
           {'if': 'size(state.entries) > 256', 'then': [
               {'title': 'Evict the oldest entry past MAX_ENTRIES', 'source': TOC + ':231-237',
                'set': {'state.entries': '= omit(state.entries, state.entries.map(k, k).sortBy(k, state.entries[k].timestamp)[0])'}}]},
           {'return': {'recorded': True}}])
add_if(component='terminal-output-cache', name='lookup', kind='function',
       summary='lookup: a hit returns the recorded text unless its class TTL (30 s / 2 min / 5 min) has passed, in which case the entry is dropped.',
       sources=[TOC + ':190-210', TOC + ':37-41', TOCMP + ':651-670'], request=CACHE_REQ, response=obj(hit=BOOL, text=STR, timestamp=INT),
       behavior=[{'if': "!has(input.command) || input.command.trim() == ''", 'then': [{'return': {'hit': False}}]}]
       + PARSE + [
           {'if': "vars.c.cls == ''", 'then': [{'return': {'hit': False}}]},
           {'set': {'vars.key': "= vars.cwd + '::' + vars.cmd"}},
           {'if': '!(vars.key in state.entries)', 'then': [{'return': {'hit': False}}]},
           {'set': {'vars.e': '= state.entries[vars.key]'}},
           {'set': {'vars.ttl': "= vars.e.cls == 'fast' ? 30000 : (vars.e.cls == 'medium' ? 120000 : 300000)"}},
           {'if': 'now - vars.e.timestamp > vars.ttl', 'then': [
               {'title': 'Expired: delete and miss', 'source': TOC + ':204-207', 'set': {'state.entries': '= omit(state.entries, vars.key)'}},
               {'return': {'hit': False}}]},
           {'return': {'hit': True, 'text': '= vars.e.text', 'timestamp': '= vars.e.timestamp'}}])
add_if(component='terminal-output-cache', name='observe', kind='function',
       summary='observe: a mutating command (git commit, npm install, ...) drops the cached entries of the programs it invalidates in the same cwd.',
       sources=[TOC + ':178-188', TOC + ':252-264'], request=CACHE_REQ, response=obj(invalidated=INT),
       behavior=[{'if': "!has(input.command) || input.command.trim() == ''", 'then': [{'return': {'invalidated': 0}}]}]
       + PARSE + [
           {'if': 'size(vars.c.invalidates) == 0', 'then': [{'return': {'invalidated': 0}}]},
           {'set': {'vars.drop': '= state.entries.filter(k, state.entries[k].cwd == vars.cwd && state.entries[k].head in vars.c.invalidates)'}},
           {'set': {'state.entries': '= state.entries.filter(k, !(k in vars.drop)).map(k, k).size() == size(state.entries) ? state.entries : state.entries'}},
           {'foreach': '= vars.drop', 'as': 'k', 'steps': [{'set': {'state.entries': '= omit(state.entries, vars.k)'}}]},
           {'return': {'invalidated': '= size(vars.drop)'}}])
# drop the no-op set step above (kept simple)
iface('terminal-output-cache.observe')['behavior'] = [s for s in iface('terminal-output-cache.observe')['behavior'] if not (isinstance(s.get('set'), dict) and list(s['set'].values()) == ['= state.entries.filter(k, !(k in vars.drop)).map(k, k).size() == size(state.entries) ? state.entries : state.entries'])]

YN = "(?i)(?:\\(|\\[)\\s*(?:y(?:es)?\\s*/\\s*n(?:o)?|n(?:o)?\\s*/\\s*y(?:es)?)\\s*(?:\\]|\\))\\s+$"
add_if(component='output-monitor', name='wait-for-idle', kind='function',
       summary='_waitForIdle: poll with an interval doubling from 500 ms to 10 s until max wait (20 s, or 2 min extended). A y/n prompt on the last line is Idle at once; two polls without new data while the process is not active is Idle; running out of time is Timeout; the token cancels.',
       sources=[OM + ':477-560'],
       request=obj(id=INT, extended={'type': 'boolean', 'default': False}, is_active={'type': 'boolean', 'default': False},
                   token={'type': 'string', 'default': 'output-monitor'}),
       response=obj(state=STR, waited=INT, polls=INT),
       behavior=[
           {'set': {'vars.max': "= input.extended ? config['output-monitor-extended-polling-max-ms'] : config['output-monitor-first-polling-max-ms']",
                    'vars.interval': "= config['output-monitor-min-polling-ms']", 'vars.waited': 0, 'vars.idle': 0, 'vars.polls': 0, 'vars.state': 'Timeout'}},
           {'call': 'terminal-process-manager.get-output', 'input': {'id': '= input.id'}, 'as': 'o0'},
           {'set': {'vars.len': '= vars.o0.value.length'}},
           {'foreach': '= [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]', 'as': 'n', 'steps': [
               {'if': 'vars.waited >= vars.max', 'then': [{'break': True}]},
               {'set': {'vars.step': '= vars.interval < vars.max - vars.waited ? vars.interval : vars.max - vars.waited'}},
               {'title': 'await timeout(waitTime, token): cancellation ends the wait as Cancelled', 'source': OM + ':488-496',
                'wait': '= vars.step', 'token': '= input.token', 'on_error': 'continue'},
               {'if': "canceled(input.token)", 'then': [{'set': {'vars.state': 'Cancelled'}}, {'break': True}]},
               {'set': {'vars.waited': '= vars.waited + vars.step', 'vars.polls': '= vars.polls + 1',
                        'vars.interval': "= vars.interval * 2 < config['output-monitor-max-polling-interval-ms'] ? vars.interval * 2 : config['output-monitor-max-polling-interval-ms']"}},
               {'call': 'terminal-process-manager.get-output', 'input': {'id': '= input.id'}, 'as': 'o'},
               {'set': {'vars.last': "= vars.o.value.output.split('\\n')[size(vars.o.value.output.split('\\n')) - 1]"}},
               {'if': "vars.last.matches(r'" + YN + "')", 'then': [
                   {'title': 'High-confidence input pattern on the last line: Idle at once', 'source': OM + ':514-520',
                    'set': {'vars.state': 'Idle'}}, {'break': True}]},
               {'if': 'vars.o.value.length != vars.len', 'then': [
                   {'set': {'vars.idle': 0, 'vars.len': '= vars.o.value.length'}}],
                'else': [{'set': {'vars.idle': '= vars.idle + 1'}}]},
               {'if': "vars.idle >= config['output-monitor-min-idle-events'] && !input.is_active", 'then': [
                   {'title': 'recentlyIdle && !active: Idle', 'source': OM + ':531-543', 'set': {'vars.state': 'Idle'}}, {'break': True}]}]},
           {'return': {'state': '= vars.state', 'waited': '= vars.waited', 'polls': '= vars.polls'}}])
add_if(component='output-monitor', name='start-monitoring', kind='function',
       summary='startMonitoring/_startMonitoring: PollingForIdle, then Idle (stop with the latest output), Timeout (stop, outside async mode) or Cancelled; records the polling result and fires onDidFinishCommand.',
       sources=[OM + ':156-196', OM + ':198-290', OM + ':344-360', 'src/vs/workbench/contrib/terminalContrib/chatAgentTools/browser/taskHelpers.ts:268-274'],
       request=obj(id={'type': 'integer', 'examples': [1]}, command={'type': 'string', 'examples': ['npm test']},
                   is_active={'type': 'boolean', 'default': False}, token={'type': 'string', 'default': 'output-monitor'}),
       response=obj(state=STR, output=STR, poll_duration_ms=INT),
       behavior=[
           {'set': {'vars.start': '= now'}},
           {'call': 'output-monitor.wait-for-idle', 'input': {'id': '= input.id', 'extended': False, 'is_active': '= input.is_active', 'token': '= input.token'}, 'as': 'r'},
           {'set': {'vars.output': "''"}},
           {'if': "vars.r.value.state == 'Idle'", 'then': [
               {'title': '_handleIdleState: no prompt to answer, stop polling with the output', 'source': OM + ':344-360',
                'call': 'terminal-process-manager.get-output', 'input': {'id': '= input.id'}, 'as': 'out'},
               {'set': {'vars.output': '= vars.out.value.output'}}]},
           {'set': {'state.runs': "= merge(state.runs, {string(input.id): {'command': has(input.command) ? input.command : '', 'state': vars.r.value.state, 'output': vars.output, 'poll_duration_ms': now - vars.start}})"}},
           {'return': {'state': '= vars.r.value.state', 'output': '= vars.output', 'poll_duration_ms': '= now - vars.start'}}])
add_if(component='output-monitor', name='get-polling-result', kind='function',
       summary='pollingResult: the state and output of the last monitoring run for an execution.', sources=[OM + ':81-82'],
       request=obj(id={'type': 'integer', 'examples': [1]}), response=obj(state=STR, output=STR),
       behavior=[{'if': '!(string(input.id) in state.runs)', 'then': [{'return': {'state': 'none', 'output': ''}}]},
                 {'return': '= state.runs[string(input.id)]'}])

# ---------------------------------------------------------------- flows
flow('terminal-create').setdefault('tags', []).append('feature:integrated-terminal')
flow('debug-start-selected').setdefault('tags', []).append('feature:debugging')
flow('task-run').setdefault('tags', []).append('feature:tasks')
flow('test-run').setdefault('tags', []).append('feature:testing')
FLOWS += [
    {'id': 'debug-adapter-exit', 'name': 'Debug adapter process exits',
     'description': 'The adapter process exits in the extension host; $acceptDAExit (exthost relay) fires the RawDebugSession onExit handler, which tears the session down.',
     'sources': [RDS + ':100-107'], 'tags': ['writes'],
     'entry': {'caller': 'debug-adapter', 'interface': 'raw-debug-session.on-adapter-exit', 'input': {'session_id': 'session-1', 'code': 1}}},
    {'id': 'terminal-output-monitor', 'name': 'Chat tool waits for terminal output to go idle',
     'description': 'run_in_terminal hands its execution to an OutputMonitor that polls the terminal output until it is idle.',
     'sources': [OM + ':156-196'], 'tags': ['writes'],
     'entry': {'caller': 'chat', 'interface': 'output-monitor.start-monitoring', 'input': {'id': 1, 'command': 'npm test'}}},
    {'id': 'terminal-output-cache-record', 'name': 'Record a run_in_terminal result in the session cache',
     'sources': [TOC + ':212-238'], 'tags': ['writes'],
     'entry': {'caller': 'chat', 'interface': 'terminal-output-cache.record', 'input': {'command': 'git status', 'cwd': '/work/app', 'text': 'clean'}}},
    {'id': 'terminal-output-cache-lookup', 'name': 'Look up a cached run_in_terminal result',
     'sources': [TOC + ':190-210'],
     'entry': {'caller': 'chat', 'interface': 'terminal-output-cache.lookup', 'input': {'command': 'git status', 'cwd': '/work/app'}}},
    {'id': 'terminal-output-cache-observe', 'name': 'A mutating command invalidates cached results',
     'sources': [TOC + ':178-188'], 'tags': ['writes'],
     'entry': {'caller': 'chat', 'interface': 'terminal-output-cache.observe', 'input': {'command': 'git commit -m x', 'cwd': '/work/app'}}},
]

exec(open(os.path.join(HERE, 'fixround_scen.py')).read())
for sid in ('debug-start-guess-no-candidates', 'debug-start-selected-none'):
    scen(sid).setdefault('state', {})['configuration-manager@w1'] = {'selected': None}
e = scen('debug-start-happy')['expect']
e[e.index("calls['editor-service.save-all'] == 1 && calls['extension-service.activate-by-event'] == 1")] = (
    "calls['editor-service.save-all'] == 1 && calls['extension-service.activate-by-event'] == 4 && "
    "trace.exists(e, e.type == 'call.start' && e.interface == 'extension-service.activate-by-event' && e.input.activation_event == 'onDebugResolve:node')")


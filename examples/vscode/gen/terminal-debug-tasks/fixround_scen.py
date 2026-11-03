# Scenarios added in the fix round (exec'd by fixround.py).
FX = ['one-window-folder', 'terminal-debug-tasks-seed']
BK = {'terminal-instance-service@w1': {'backends': {'local': True}}}
CH = {'debug-service.start-debugging.trust': 'trusted', 'task-service.trust.trust': 'trusted',
      'test-service.run-resolved-tests.trust': 'trusted', 'run-automatic-tasks.try-run-tasks.trust': 'trusted'}


def S(id, name, expect, flow=None, steps=None, state=None, **kw):
    s = {'id': id, 'name': name}
    if flow:
        s['flow'] = flow
    s['fixtures'] = kw.pop('fixtures', FX)
    st = dict(BK)
    st.update(state or {})
    s['state'] = st
    for k, v in kw.items():
        s[k] = v
    if steps:
        s['steps'] = steps
    s['expect'] = expect
    s['choices'] = CH
    SCEN.append(s)


FLOWS.append({'id': 'terminal-output-monitor-result', 'name': 'Read the last OutputMonitor polling result',
              'sources': [OM + ':81-82'],
              'entry': {'caller': 'chat', 'interface': 'output-monitor.get-polling-result', 'input': {'id': 1}}})

# ---- T1
S('terminal-output-streams-to-renderer', 'T1: the shell prompt streams node-pty -> bufferer (5 ms) -> direct proxy -> LocalPty.handleData -> xterm',
  ["result.ok",
   "trace.exists(e, e.type == 'yield' && e.interface == 'terminal-process.on-process-data' && e.output.data == '$ ')",
   "trace.exists(e, e.type == 'yield' && e.interface == 'pty-service.on-process-data' && e.output.id == 1)",
   "trace.exists(e, e.type == 'call.start' && e.interface == 'local-pty.handle-data' && e.input.data == '$ ')",
   "state['terminal-process-manager@w1'].procs['1'].output == '$ '",
   "state['pty-service'].ptys['1'].replay_buffer == '$ '"],
  flow='terminal-create')
S('terminal-output-flow-control-pauses', 'T1: past the high watermark node-pty is paused until the renderer acknowledges',
  ["result.ok && result.value.value.paused && result.value.value.chars == 6 && size(result.value.items) == 2",
   "trace.filter(e, e.type == 'yield' && e.interface == 'terminal-process.on-process-data').size() == 2"],
  steps=[{'interface': 'terminal-process.on-process-data', 'caller': 'pty-service', 'input': {'chunks': ['abc', 'def']}}],
  config={'terminal-flow-control-high-watermark-chars': 4})
S('terminal-output-unknown-pty', 'T1: data for a pty the host does not know fails with the real error',
  ["result.ok && result.value.delivered == 0", "trace.exists(e, e.type == 'call.end' && e.interface == 'pty-service.on-process-data' && e.error.code == 'could-not-find-pty-on-pty-host')"],
  steps=[{'interface': 'local-terminal-backend.listen-process-data', 'caller': 'pty-service', 'input': {'id': 7, 'chunks': ['x']}}])

# ---- T2
S('terminal-reload-replays-live-buffer', 'T2: type, reload (window restarts) and reattach within the grace time: the pty host replays the live buffer; the shell is never killed',
  ["steps.w.result.value.detached == 1",
   "calls['local-terminal-backend.persist-terminal-state'] == 0",
   "steps.r.result.ok && steps.r.result.value.reconnected == 1",
   "calls['terminal-process.shutdown'] == 0 && calls['pty-service.create-process'] == 1",
   "trace.exists(e, e.type == 'call.end' && e.interface == 'local-pty.handle-replay' && e.output.chars == 2)",
   "state['terminal-process-manager@w1'].procs['1'].output == '$ '",
   "state['pty-service'].ptys['1'].grace_scheduled_at == null"],
  state={'terminal-service@w1': {'layout_listeners_attached': True}},
  steps=[{'flow': 'terminal-create', 'as': 'c'},
         {'interface': 'local-pty.input', 'caller': 'terminal-process-manager', 'input': {'id': 1, 'data': 'ls\r'}, 'as': 'i', 'at_ms': 1000},
         {'flow': 'terminal-before-shutdown', 'input': {'reason': 'reload'}, 'as': 'b', 'at_ms': 2000},
         {'flow': 'terminal-will-shutdown', 'input': {'reason': 'reload'}, 'as': 'w', 'at_ms': 2100},
         {'restart': {'component': 'workbench-window', 'instance': 'w1'}, 'at_ms': 2200},
         {'flow': 'terminal-reconnect', 'input': {'startup_kind': 'reloaded-window'}, 'as': 'r', 'at_ms': 3000}])
S('terminal-reload-grace-expires', 'T2: no window reattaches within 60 s: the grace runner shuts the shell down',
  ["steps.w.result.value.detached == 1", "calls['terminal-process.shutdown'] == 1",
   "!('1' in state['pty-service'].ptys)"],
  state={'terminal-service@w1': {'layout_listeners_attached': True}},
  steps=[{'flow': 'terminal-create', 'as': 'c'},
         {'interface': 'local-pty.input', 'caller': 'terminal-process-manager', 'input': {'id': 1, 'data': 'ls\r'}, 'as': 'i', 'at_ms': 1000},
         {'flow': 'terminal-will-shutdown', 'input': {'reason': 'reload'}, 'as': 'w', 'at_ms': 2000}])

# ---- T3
S('pty-host-crash-relaunches-terminal', 'T3: the pty host dies; it restarts, the window reconnects and the normal terminal relaunches a new shell with the restart message',
  ["steps.x.result.value.restarted",
   "trace.exists(e, e.type == 'restart' && e.component == 'pty-service')",
   "calls['local-terminal-backend.on-pty-host-exit'] == 1 && calls['local-terminal-backend.reconnect-direct-proxy'] == 1",
   "calls['pty-service.create-process'] == 2 && calls['terminal-process.start'] == 2 && calls['pty-host-main.start-pty-host'] == 2",
   "state['terminal-process-manager@w1'].procs['1'].output.contains('Restarting the terminal because the connection to the shell process was lost...')",
   "size(state['terminal-service@w1'].instances) == 1 && state['terminal-service@w1'].instances['1'].persistent_process_id == 1",
   "state['pty-service'].last_pty_id == 1 && state['pty-service'].ptys['1'].started"],
  steps=[{'flow': 'terminal-create', 'as': 'c'},
         {'flow': 'pty-host-exit', 'input': {'code': 1}, 'as': 'x', 'at_ms': 1000}])
S('pty-host-crash-task-terminal-exits', 'T3: a feature (task) terminal without reconnection properties is reported exited with -1, not relaunched',
  ["steps.x.result.value.restarted",
   "calls['pty-service.create-process'] == 1",
   "state['terminal-process-manager@w1'].procs['1'].process_state == 'killed-by-process' && state['terminal-process-manager@w1'].procs['1'].exit_code == -1",
   "state['terminal-service@w1'].instances['1'].exit_code == -1"],
  steps=[{'flow': 'terminal-create', 'input': {'is_feature_terminal': True}, 'as': 'c'},
         {'flow': 'pty-host-exit', 'input': {'code': 1}, 'as': 'x', 'at_ms': 1000}])
S('pty-host-killed-then-restarted', 'T3: a kill of the pty host fails its pending work; the exit handler restarts it and the terminal relaunches',
  ["trace.exists(e, e.type == 'kill' && e.component == 'pty-service')",
   "steps.x.result.value.restarted && !has(state['pty-service'].dead)",
   "calls['terminal-process.start'] == 2"],
  faults=[{'type': 'kill', 'target': 'pty-service', 'at_ms': 500}],
  steps=[{'flow': 'terminal-create', 'as': 'c'},
         {'flow': 'pty-host-exit', 'input': {'code': 1}, 'as': 'x', 'at_ms': 1000}])

# ---- D1
S('debug-f5-default-world-starts-selected', 'D1: the first launch.json configuration is selected at startup, so F5 starts "Launch Program" and activates onDebugResolve:node',
  ["result.ok && result.value.started",
   "calls['adapter-manager.guess-debugger'] == 0",
   "state['debug-model@w1'].sessions['session-1'].name == 'Launch Program'",
   "trace.exists(e, e.type == 'call.start' && e.interface == 'extension-service.activate-by-event' && e.input.activation_event == 'onDebugResolve:node')",
   "trace.exists(e, e.type == 'call.start' && e.interface == 'extension-service.activate-by-event' && e.input.activation_event == 'onDebugResolve')"],
  flow='debug-start-selected')
S('debug-select-configuration-fallback', 'D1: selecting an unknown name falls back to the first configuration',
  ["steps.s.result.value.selected == 'Launch Program'", "steps.g.result.value.name == 'Launch Program'",
   "state['configuration-manager@w1'].selected == 'Launch Program'"],
  state={'configuration-manager@w1': {'selected': None}},
  steps=[{'interface': 'configuration-manager.select-configuration', 'caller': 'debug-service', 'input': {'name': 'Nope'}, 'as': 's'},
         {'interface': 'configuration-manager.get-selected-configuration', 'caller': 'debug-service', 'as': 'g'}])
S('debug-adapter-start-session', 'D1: the adapter process starts and is tracked by handle; stopping it kills it',
  ["steps.s.result.ok && steps.s.result.value.pid == 5151",
   "state['debug-adapter'].running.size() == 0", "calls['debug-adapter.stop-session'] == 1"],
  steps=[{'interface': 'debug-adapter.start-session', 'caller': 'ext-host-debug-service', 'input': {'handle': 1, 'session_id': 'session-1', 'type': 'node'}, 'as': 's'},
         {'interface': 'debug-adapter.stop-session', 'caller': 'ext-host-debug-service', 'input': {'handle': 1}}])
S('debug-adapter-start-no-executable', 'D1: no executable for the adapter fails with the real message',
  ["!result.ok && result.error.code == 'cannot-determine-executable-for-debug-adapter'"],
  steps=[{'interface': 'debug-adapter.start-session', 'caller': 'ext-host-debug-service', 'input': {'handle': 1, 'type': 'node', 'command': ''}}])
S('debug-adapter-stop-unknown-handle', 'D1: stopping an adapter that never started does nothing',
  ["result.ok", "trace.exists(e, e.type == 'call.end' && e.interface == 'debug-adapter.stop-session')"],
  steps=[{'interface': 'debug-adapter.stop-session', 'caller': 'ext-host-debug-service', 'input': {'handle': 9}}])

# ---- D2
S('debug-adapter-exit-nonzero', 'D2: the adapter exits with code 1: disconnect with the 200 ms error timeout, adapter stopped, session inactive; the stop succeeded, so the exit event carries no error and no notification shows',
  ["steps.x.result.ok",
   "trace.exists(e, e.type == 'call.start' && e.interface == 'raw-debug-session.send' && e.input.command == 'disconnect' && e.input.timeout_ms == 200)",
   "calls['ext-host-debug-service.stop-da-session'] == 1 && calls['notification-service.notify'] == 0",
   "state['debug-model@w1'].sessions['session-1'].state == 'inactive'",
   "!steps.l.result.value.sessions.exists(s, s.id == 'session-1')"],
  steps=[{'flow': 'debug-start-selected', 'as': 'f5'},
         {'flow': 'debug-adapter-exit', 'input': {'session_id': 'session-1', 'code': 1}, 'as': 'x', 'at_ms': 5000},
         {'flow': 'debug-sessions', 'as': 'l', 'at_ms': 6000}])
S('debug-adapter-exit-stop-fails-notifies', 'D2: stopping the dead adapter fails, so the exit event keeps the error and the user sees "Debug adapter process has terminated unexpectedly (exit code: 3)"',
  ["trace.exists(e, e.type == 'call.start' && e.interface == 'notification-service.notify' && e.input.severity == 'error' && e.input.message == 'Debug adapter process has terminated unexpectedly (exit code: 3)')",
   "state['debug-model@w1'].sessions['session-1'].state == 'inactive'"],
  faults=[{'target': 'ext-host-debug-service.stop-da-session', 'type': 'error', 'code': 'canceled'}],
  steps=[{'flow': 'debug-start-selected', 'as': 'f5'},
         {'flow': 'debug-adapter-exit', 'input': {'session_id': 'session-1', 'code': 3}, 'as': 'x', 'at_ms': 5000}])
S('debug-adapter-exit-zero', 'D2: a normal exit (code 0) shuts down with the 2 s disconnect timeout',
  ["trace.exists(e, e.type == 'call.start' && e.interface == 'raw-debug-session.send' && e.input.command == 'disconnect' && e.input.timeout_ms == 2000)",
   "state['debug-model@w1'].sessions['session-1'].state == 'inactive'"],
  steps=[{'flow': 'debug-start-selected', 'as': 'f5'},
         {'flow': 'debug-adapter-exit', 'input': {'session_id': 'session-1', 'code': 0}, 'as': 'x', 'at_ms': 5000}])
S('debug-adapter-error', 'D2: an adapter error (read error) shuts the session down like a crash',
  ["trace.exists(e, e.type == 'call.start' && e.interface == 'raw-debug-session.send' && e.input.command == 'disconnect' && e.input.timeout_ms == 200)",
   "state['debug-model@w1'].sessions['session-1'].state == 'inactive'"],
  steps=[{'flow': 'debug-start-selected', 'as': 'f5'},
         {'interface': 'raw-debug-session.on-adapter-error', 'caller': 'debug-adapter', 'input': {'session_id': 'session-1', 'message': 'read error'}, 'at_ms': 5000}])

# ---- OutputMonitor
S('output-monitor-idle', 'Oracle outputMonitor.test.ts:58: output stops changing and the process is inactive: Idle with the latest output after two quiet polls, nothing sent to the terminal',
  ["steps.m.result.value.state == 'Idle' && steps.m.result.value.output == '$ '",
   "steps.m.result.value.poll_duration_ms >= 1500 && steps.m.result.value.poll_duration_ms < 1600",
   "calls['local-pty.input'] == 0",
   "steps.p.result.value.state == 'Idle'",
   "state['output-monitor@w1'].runs['1'].state == 'Idle'"],
  steps=[{'flow': 'terminal-create', 'as': 'c'},
         {'flow': 'terminal-output-monitor', 'as': 'm', 'at_ms': 100},
         {'flow': 'terminal-output-monitor-result', 'as': 'p', 'at_ms': 30000}])
S('output-monitor-active-times-out', 'OutputMonitor: a still-active execution never counts as idle; polling backs off 500 ms -> 10 s and gives up at 20 s (Timeout)',
  ["steps.m.result.value.state == 'Timeout' && steps.m.result.value.poll_duration_ms >= 20000 && steps.m.result.value.poll_duration_ms < 20100",
   "trace.filter(e, e.type == 'call.start' && e.interface == 'terminal-process-manager.get-output').size() == 7"],
  steps=[{'flow': 'terminal-create', 'as': 'c'},
         {'flow': 'terminal-output-monitor', 'input': {'id': 1, 'is_active': True}, 'as': 'm', 'at_ms': 100}])
S('output-monitor-yn-prompt', 'OutputMonitor: a (y/n) prompt on the last line is Idle at the first poll',
  ["steps.m.result.value.state == 'Idle' && steps.m.result.value.poll_duration_ms >= 500 && steps.m.result.value.poll_duration_ms < 600",
   "steps.m.result.value.output.endsWith('(y/n) ')"],
  steps=[{'flow': 'terminal-create', 'as': 'c'},
         {'interface': 'local-pty.handle-data', 'caller': 'local-terminal-backend', 'input': {'id': 1, 'data': '\nContinue? (y/n) '}, 'at_ms': 50},
         {'flow': 'terminal-output-monitor', 'input': {'id': 1, 'is_active': True}, 'as': 'm', 'at_ms': 100}])
S('output-monitor-new-data-resets-idle', 'OutputMonitor: data arriving between polls resets the idle count (quiet at 0.5 s, data by 1.5 s, quiet at 3.5 s and 7.5 s: Idle)',
  ["steps.m.result.value.state == 'Idle' && steps.m.result.value.poll_duration_ms >= 7500 && steps.m.result.value.poll_duration_ms < 7600"],
  steps=[{'flow': 'terminal-create', 'as': 'c'},
         {'flow': 'terminal-output-monitor', 'as': 'm', 'at_ms': 100, 'await': False},
         {'interface': 'local-pty.handle-data', 'caller': 'local-terminal-backend', 'input': {'id': 1, 'data': 'PASS\n'}, 'at_ms': 1200}])
S('output-monitor-cancelled', 'OutputMonitor: the tool invocation is cancelled while polling: the monitor ends Cancelled',
  ["steps.p.result.value.state == 'Cancelled'", "trace.exists(e, e.type == 'cancel' && e.key == 'output-monitor')"],
  steps=[{'flow': 'terminal-create', 'as': 'c'},
         {'flow': 'terminal-output-monitor', 'input': {'id': 1, 'is_active': True}, 'as': 'm', 'at_ms': 100, 'await': False},
         {'cancel': 'output-monitor', 'at_ms': 800},
         {'flow': 'terminal-output-monitor-result', 'as': 'p', 'at_ms': 2000}])
S('output-monitor-no-terminal', 'OutputMonitor: an execution without a terminal fails',
  ["!result.ok && result.error.code == 'no-such-terminal'"],
  flow='terminal-output-monitor', input={'id': 9, 'command': 'ls'})
S('output-monitor-result-none', 'OutputMonitor: no run yet for the execution',
  ["result.value.state == 'none'", "!('9' in state['output-monitor@w1'].runs)"],
  flow='terminal-output-monitor-result', input={'id': 9})

# ---- TerminalOutputCache
S('terminal-output-cache-hit', 'Oracle terminalOutputCache.test.ts:17: record `git status` in /repo, then lookup returns `clean`',
  ["steps.r.result.value.recorded", "steps.l.result.value.hit && steps.l.result.value.text == 'clean'",
   "state['terminal-output-cache@w1'].entries['/repo::git status'].cls == 'fast'"],
  steps=[{'flow': 'terminal-output-cache-record', 'input': {'command': 'git status', 'cwd': '/repo', 'text': 'clean'}, 'as': 'r'},
         {'flow': 'terminal-output-cache-lookup', 'input': {'command': 'git status', 'cwd': '/repo'}, 'as': 'l'}])
S('terminal-output-cache-keyed-by-cwd', 'TerminalOutputCache: keys include the cwd',
  ["!steps.l.result.value.hit", "size(state['terminal-output-cache@w1'].entries) == 1"],
  steps=[{'flow': 'terminal-output-cache-record', 'input': {'command': 'git status', 'cwd': '/repo', 'text': 'clean'}},
         {'flow': 'terminal-output-cache-lookup', 'input': {'command': 'git status', 'cwd': '/other'}, 'as': 'l'}])
S('terminal-output-cache-fast-ttl-expires', 'TerminalOutputCache: a fast-class entry expires after 30 s and is dropped',
  ["!steps.l.result.value.hit", "size(state['terminal-output-cache@w1'].entries) == 0"],
  steps=[{'flow': 'terminal-output-cache-record', 'input': {'command': 'git status', 'cwd': '/repo', 'text': 'clean'}},
         {'flow': 'terminal-output-cache-lookup', 'input': {'command': 'git status', 'cwd': '/repo'}, 'as': 'l', 'at_ms': 31000}])
S('terminal-output-cache-slow-ttl-survives', 'TerminalOutputCache: a slow-class entry (git log) still hits after 31 s',
  ["steps.l.result.value.hit", "state['terminal-output-cache@w1'].entries['/repo::git log'].cls == 'slow'"],
  steps=[{'flow': 'terminal-output-cache-record', 'input': {'command': 'git log', 'cwd': '/repo', 'text': 'abc'}},
         {'flow': 'terminal-output-cache-lookup', 'input': {'command': 'git log', 'cwd': '/repo'}, 'as': 'l', 'at_ms': 31000}])
S('terminal-output-cache-mutation-invalidates', 'TerminalOutputCache: `git commit` in the same cwd drops cached git reads; other programs and cwds stay',
  ["steps.o.result.value.invalidated == 1", "!steps.l.result.value.hit",
   "'/repo::ls' in state['terminal-output-cache@w1'].entries && '/other::git status' in state['terminal-output-cache@w1'].entries"],
  steps=[{'flow': 'terminal-output-cache-record', 'input': {'command': 'git status', 'cwd': '/repo', 'text': 'clean'}},
         {'flow': 'terminal-output-cache-record', 'input': {'command': 'git status', 'cwd': '/other', 'text': 'clean'}},
         {'flow': 'terminal-output-cache-record', 'input': {'command': 'ls', 'cwd': '/repo', 'text': 'a b'}},
         {'flow': 'terminal-output-cache-observe', 'input': {'command': 'git commit -m x', 'cwd': '/repo'}, 'as': 'o'},
         {'flow': 'terminal-output-cache-lookup', 'input': {'command': 'git status', 'cwd': '/repo'}, 'as': 'l'}])
S('terminal-output-cache-npm-install-invalidates', 'TerminalOutputCache: npm install invalidates npm/pnpm/yarn reads',
  ["steps.o.result.value.invalidated == 1", "size(state['terminal-output-cache@w1'].entries) == 0"],
  steps=[{'flow': 'terminal-output-cache-record', 'input': {'command': 'npm test', 'cwd': '/repo', 'text': 'ok'}},
         {'flow': 'terminal-output-cache-observe', 'input': {'command': 'npm install', 'cwd': '/repo'}, 'as': 'o'}])
S('terminal-output-cache-read-only-observe', 'TerminalOutputCache: a read command invalidates nothing',
  ["steps.o.result.value.invalidated == 0", "size(state['terminal-output-cache@w1'].entries) == 1"],
  steps=[{'flow': 'terminal-output-cache-record', 'input': {'command': 'git status', 'cwd': '/repo', 'text': 'clean'}},
         {'flow': 'terminal-output-cache-observe', 'input': {'command': 'git status', 'cwd': '/repo'}, 'as': 'o'}])
S('terminal-output-cache-compound-not-cached', 'TerminalOutputCache: compound commands are never cached',
  ["!steps.r.result.value.recorded", "!steps.l.result.value.hit", "size(state['terminal-output-cache@w1'].entries) == 0"],
  steps=[{'flow': 'terminal-output-cache-record', 'input': {'command': 'git status && ls', 'cwd': '/repo', 'text': 'x'}, 'as': 'r'},
         {'flow': 'terminal-output-cache-lookup', 'input': {'command': 'git status && ls', 'cwd': '/repo'}, 'as': 'l'}])
S('terminal-output-cache-uncacheable', 'TerminalOutputCache: an unclassified command (rm) and an empty command are not recorded',
  ["!steps.a.result.value.recorded && !steps.b.result.value.recorded", "!steps.l.result.value.hit && !steps.m.result.value.hit",
   "size(state['terminal-output-cache@w1'].entries) == 0"],
  steps=[{'flow': 'terminal-output-cache-record', 'input': {'command': 'rm -rf x', 'cwd': '/repo', 'text': ''}, 'as': 'a'},
         {'flow': 'terminal-output-cache-record', 'input': {'command': '  ', 'cwd': '/repo', 'text': ''}, 'as': 'b'},
         {'flow': 'terminal-output-cache-lookup', 'input': {'command': 'rm -rf x', 'cwd': '/repo'}, 'as': 'l'},
         {'flow': 'terminal-output-cache-lookup', 'input': {'command': '', 'cwd': '/repo'}, 'as': 'm'}])
S('terminal-output-cache-test-runner-medium', 'TerminalOutputCache: test runners are medium class (2 min)',
  ["steps.l.result.value.hit", "state['terminal-output-cache@w1'].entries['/repo::go test'].cls == 'medium'"],
  steps=[{'flow': 'terminal-output-cache-record', 'input': {'command': 'go test', 'cwd': '/repo', 'text': 'ok'}},
         {'flow': 'terminal-output-cache-lookup', 'input': {'command': 'go test', 'cwd': '/repo'}, 'as': 'l', 'at_ms': 100000}])

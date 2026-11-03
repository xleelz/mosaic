# part 5: flows and scenarios
def flow(id, entry, caller, name, sources, tags=None, inp=None, desc=None):
    f = {'id': id, 'name': name, 'entry': {'caller': caller, 'interface': entry}, 'sources': sources}
    if inp is not None:
        f['entry']['input'] = inp
    if tags:
        f['tags'] = tags
    if desc:
        f['description'] = desc
    flows.append(f)


def scen(id, flow_id, expect, name=None, fixtures=None, **kw):
    sc = {'id': id}
    if flow_id:
        sc['flow'] = flow_id
    if name:
        sc['name'] = name
    sc['fixtures'] = fixtures or ['one-window-folder']
    sc.update(kw)
    sc['expect'] = expect
    scenarios.append(sc)


def tr(iface_id, typ='call.start'):
    return f"trace.exists(e, e.type == '{typ}' && e.interface == '{iface_id}')"


def ntr(iface_id):
    return '!' + tr(iface_id)


W = '@w1'
SEED_SESSION = {'session': 'copilot:/9f2c4e1a', 'provider': 'copilot', 'title': '', 'status': 'idle', 'archived': False, 'read_only': False, 'active_turn': ''}
SEED_CACHE = {'local-agent-host/9f2c4e1a': {'session_id': 'local-agent-host/9f2c4e1a', 'title': '', 'archived': False, 'backend_uri': 'copilot:/9f2c4e1a'}}
SEED_PROVIDERS = {'providers': {'local-agent-host': {'id': 'local-agent-host', 'order': 0, 'session_types': ['copilotcli']}}}
AH_SEEDED = {'agent-host-state-manager': {'sessions': {'copilot:/9f2c4e1a': SEED_SESSION}},
             'agent-host-database': {'sessions_v2': {'copilot:/9f2c4e1a': {'session': 'copilot:/9f2c4e1a', 'provider': 'copilot'}}}}
WS_SEEDED = dict(AH_SEEDED)
WS_SEEDED.update({'sessions-providers-service' + W: SEED_PROVIDERS, 'local-agent-host-sessions-provider' + W: {'session_cache': SEED_CACHE}})
CLIENT = {'protocol-server-handler': {'clients': {'w1-client': {'client_id': 'w1-client', 'protocol_version': '1.1.0'}}}}

# ---------------- agent host process
flow('agents-agent-host-startup', 'agent-host-main.start', 'agent-host-process-manager', 'Agent host utility process startup',
     [f'{AHM}:74-80', f'{AHM}:113-546'])
scen('agents-agent-host-startup-happy', 'agents-agent-host-startup',
     ["result.ok", "result.value.providers == ['copilot']", "result.value.channels == ['agentHostLogger', 'agentHostProtocol', 'agentHostManagement']",
      "result.value.websocket == 'none'", "state['agent-host-provider-service'].providers == ['copilot']"])
scen('agents-agent-host-startup-claude', 'agents-agent-host-startup',
     ["result.ok", "result.value.providers == ['copilot', 'claude']"], input={'claude_sdk_available': True})
scen('agents-agent-host-startup-claude-disabled', 'agents-agent-host-startup',
     ["result.ok", "result.value.providers == ['copilot']"], input={'claude_sdk_available': True}, config={'chat-agent-host-claude-agent-enabled': False})
scen('agents-agent-host-startup-codex-root-config', 'agents-agent-host-startup',
     ["result.ok", "result.value.providers == ['copilot', 'codex']"], input={'codex_root_config_enabled': True})
scen('agents-agent-host-startup-configured-port', 'agents-agent-host-startup',
     ["result.ok", "result.value.websocket == 'localhost:8080'"], input={'configured_port': '8080'})
scen('agents-agent-host-startup-websocket-fails', 'agents-agent-host-startup',
     ["result.ok", "result.value.websocket == 'failed'"], input={'configured_port': '8080'},
     faults=[{'target': 'agent-host-main.start-configured-web-socket-server', 'type': 'error', 'code': 'eaddrinuse'}])
scen('agents-agent-host-startup-runtime-fails', 'agents-agent-host-startup',
     ["!result.ok", "result.error.code == 'agent-host-startup-failed'", ntr('agent-host-worktree-cleanup-service.start')],
     faults=[{'target': 'agent-host-provider-service.register-providers', 'type': 'error', 'code': 'sqlite-open-failed', 'message': 'SQLITE_CANTOPEN'}])

flow('agents-agent-host-server-startup', 'agent-host-server-main.main', 'os-shell', 'Standalone agent host server (code agent host)',
     [f'{AH}/node/agentHostServerMain.ts:14', f'{AH}/node/agentHostServerMain.ts:156-401'])
scen('agents-agent-host-server-startup-default-port', 'agents-agent-host-server-startup', ["result.ok", "result.value.ready == 'READY:8081'", "result.value.providers == ['copilot']"])
scen('agents-agent-host-server-startup-port-arg', 'agents-agent-host-server-startup', ["result.ok", "result.value.ready == 'READY:9000'"], input={'port_arg': '9000', 'connection_token': 'tok_abc-1'})
scen('agents-agent-host-server-startup-quiet', 'agents-agent-host-server-startup', ["result.ok", "result.value.providers == []", ntr('agent-host-provider-service.register-providers')], input={'quiet': True})
scen('agents-agent-host-server-startup-conflicting-token', 'agents-agent-host-server-startup',
     ["!result.ok", "result.error.code == 'invalid-server-options'", "result.error.message.contains('--without-connection-token')"], input={'connection_token': 'abc', 'without_connection_token': True})
scen('agents-agent-host-server-startup-bad-token', 'agents-agent-host-server-startup',
     ["!result.ok", "result.error.message.contains('does not adhere')"], input={'connection_token': 'bad token!'})

flow('agents-diff-compute', 'diff-compute-service.compute-diff-counts', 'agent-service', 'Diff counts on the diff worker thread',
     [f'{AH}/node/diffComputeService.ts:32-57', f'{AH}/node/diffWorkerMain.ts:208-210'])
scen('agents-diff-compute-counts', 'agents-diff-compute', ["result.ok", "result.value.res.added == 1", tr('diff-worker.handle-message')])
scen('agents-diff-compute-unknown-function', 'agents-diff-compute', ["!result.ok", "result.error.message == 'Unknown function: computeEverything'"], input={'fn': 'computeEverything'})

flow('agents-agent-host-crash-recovery', 'agent-host-process-manager.handle-process-exit', 'main-process', 'Agent host unexpected exit and restart',
     [f'{PMG}:206-248'], tags=['writes'])
flow('agents-agent-host-ensure-started', 'agent-host-process-manager.ensure-started', 'main-process', 'Window connection request starts the agent host lazily', [f'{PMG}:78-92'], tags=['writes'])
flow('agents-agent-host-status', 'agent-host-process-manager.status', 'main-process', 'Read agent host process manager state', [f'{PMG}:39-44'])
RUNNING = {'agent-host-process-manager': {'running': True, 'restart_count': 0}}
scen('agents-agent-host-crash-recovery-restarts', None,
     ["steps.crash.result.value.restarted", "steps.read.result.value.running", "steps.read.result.value.restart_count == 1", "steps.read.result.value.starts == 1"],
     state=RUNNING, steps=[{'flow': 'agents-agent-host-crash-recovery', 'as': 'crash'}, {'flow': 'agents-agent-host-status', 'as': 'read'}])
scen('agents-agent-host-crash-recovery-gives-up', None,
     ["steps.crash.result.value.gave_up", "!steps.read.result.ok", "steps.read.result.error.code == 'agent-host-start-error'",
      "steps.read.result.error.message == 'Agent Host process stopped after 5 restarts.'"],
     state={'agent-host-process-manager': {'running': True, 'restart_count': 5}},
     steps=[{'flow': 'agents-agent-host-crash-recovery', 'as': 'crash'}, {'flow': 'agents-agent-host-ensure-started', 'as': 'read'}])
scen('agents-agent-host-crash-recovery-windows-shutdown-code', 'agents-agent-host-crash-recovery',
     ["result.ok", "!result.value.restarted", "!state['agent-host-process-manager'].running", "state['agent-host-process-manager'].restart_count == 0"],
     state=RUNNING, input={'platform': 'win32', 'code': 3221226091})
scen('agents-agent-host-crash-recovery-quit-requested', 'agents-agent-host-crash-recovery',
     ["result.ok", "!result.value.restarted", ntr('agent-host-process-manager.ensure-started')],
     state={'agent-host-process-manager': {'running': True, 'quit_requested': True}})
scen('agents-agent-host-crash-recovery-stale-connection', 'agents-agent-host-crash-recovery', ["result.ok", "!result.value.restarted", "!result.value.gave_up"])
scen('agents-agent-host-ensure-started-first-start', None,
     ["steps.start.result.value.started", "steps.read.result.value.running", "steps.read.result.value.starts == 1", tr('agent-host-main.start')],
     steps=[{'flow': 'agents-agent-host-ensure-started', 'as': 'start'}, {'flow': 'agents-agent-host-status', 'as': 'read'}])
scen('agents-agent-host-ensure-started-already-running', 'agents-agent-host-ensure-started', ["result.ok", "!result.value.started", ntr('agent-host-main.start')], state=RUNNING)
scen('agents-agent-host-ensure-started-shutting-down', 'agents-agent-host-ensure-started',
     ["!result.ok", "result.error.code == 'agent-host-process-manager-shutting-down'"], state={'agent-host-process-manager': {'quit_requested': True}})

flow('agents-agent-host-restart', 'agent-host-electron-contribution.' + cmd_slug('workbench.action.chat.restartLocalAgentHost'), 'user',
     'Restart Local Agent Host command', [f'{SS}/contrib/providers/agentHost/electron-browser/agentHost.contribution.ts:13'], tags=['writes'])
scen('agents-agent-host-restart-after-limit', None,
     ["steps.cmd.result.value.ran", "steps.read.result.value.running", "!steps.read.result.value.restart_limit_reached", "steps.read.result.value.restart_count == 0",
      tr('agent-host-management-service.shutdown')],
     state={'agent-host-process-manager': {'running': True, 'restart_count': 5, 'restart_limit_reached': True}},
     steps=[{'flow': 'agents-agent-host-restart', 'as': 'cmd'}, {'flow': 'agents-agent-host-status', 'as': 'read'}])
scen('agents-agent-host-restart-not-running', 'agents-agent-host-restart',
     ["result.value.ran", "state['agent-host-process-manager'].running", ntr('agent-host-management-service.shutdown')])
scen('agents-agent-host-restart-shutdown-times-out', 'agents-agent-host-restart',
     ["result.value.ran", "state['agent-host-process-manager'].running", "trace.exists(e, e.type == 'call.end' && e.interface == 'agent-host-management-service.shutdown' && e.late)"],
     state=RUNNING, faults=[{'target': 'agent-host-management-service.shutdown', 'type': 'latency', 'latency_ms': 7000}])
scen('agents-agent-host-restart-ai-disabled', 'agents-agent-host-restart',
     ["!result.value.ran", ntr('agent-host-process-manager.restart')], config={'chat-disable-ai-features': True})
scen('agents-agent-host-restart-quitting', 'agents-agent-host-restart',
     ["!result.ok", "result.error.code == 'agent-host-process-manager-shutting-down'"], state={'agent-host-process-manager': {'quit_requested': True}})

# ---------------- AHP
flow('agents-ahp-initialize', 'protocol-server-handler.initialize', 'local-agent-host-service-client', 'AHP initialize handshake', [f'{PSH}:814-842'], tags=['writes'])
flow('agents-ahp-create-session', 'protocol-server-handler.create-session', 'local-agent-host-service-client', 'AHP createSession', [f'{PSH}:2126-2177'], tags=['writes'])
flow('agents-ahp-list-sessions', 'protocol-server-handler.list-sessions', 'local-agent-host-service-client', 'AHP listSessions', [f'{PSH}:2311-2320'])
flow('agents-ahp-dispatch-action', 'protocol-server-handler.dispatch-action', 'local-agent-host-service-client', 'AHP dispatchAction notification', [f'{PSH}:923-936'], tags=['writes'])
flow('agents-ahp-dispose-session', 'protocol-server-handler.dispose-session', 'local-agent-host-service-client', 'AHP disposeSession', [f'{PSH}:2180-2183'], tags=['writes'])
flow('agents-ahp-authenticate', 'protocol-server-handler.authenticate', 'local-agent-host-service-client', 'AHP authenticate', [f'{PSH}:2417-2440'], tags=['writes'])
flow('agents-ahp-reconnect', 'protocol-server-handler.reconnect', 'local-agent-host-service-client', 'AHP reconnect', [f'{PSH}:843-860'])

scen('agents-ahp-initialize-then-create-session', None,
     ["steps.init.result.value.protocol_version == '1.1.0'", "steps.create.result.ok", "steps.list.result.value.sessions.size() == 1",
      "steps.list.result.value.sessions[0].provider == 'copilot'"],
     steps=[{'flow': 'agents-ahp-initialize', 'as': 'init', 'input': {'protocol_versions': ['1.1.0', '1.0.0']}},
            {'flow': 'agents-ahp-create-session', 'as': 'create'}, {'flow': 'agents-ahp-list-sessions', 'as': 'list'}])
scen('agents-ahp-initialize-legacy-version', 'agents-ahp-initialize', ["result.value.protocol_version == '0.10.0'"], input={'protocol_versions': ['0.10.0', '0.9.0']})
scen('agents-ahp-initialize-unsupported', 'agents-ahp-initialize',
     ["!result.ok", "result.error.code == 'ahp-unsupported-protocol-version'", "result.error.data.jsonrpc_code == -32005", "!('w1-client' in state['protocol-server-handler'].clients)"],
     input={'protocol_versions': ['2.0.0', '0.8.0']})
scen('agents-ahp-create-session-before-initialize', 'agents-ahp-create-session', ["!result.ok", "result.error.code == 'method-not-found'"])
scen('agents-ahp-create-session-unknown-provider', 'agents-ahp-create-session',
     ["!result.ok", "result.error.code == 'ahp-provider-not-found'", "result.error.message == 'No agent provider registered for: gemini'"], state=CLIENT, input={'provider': 'gemini'})
scen('agents-ahp-create-session-already-owned', 'agents-ahp-create-session',
     ["!result.ok", "result.error.message == 'Session copilot:/9f2c4e1a is already owned by claude'"],
     state=dict(CLIENT, **{'agent-host-provider-service': {'providers': ['copilot', 'claude']},
                         'agent-host-database': {'sessions_v2': {'copilot:/9f2c4e1a': {'session': 'copilot:/9f2c4e1a', 'provider': 'claude'}}}}))
scen('agents-ahp-create-session-worktree', 'agents-ahp-create-session',
     ["result.ok", "trace.exists(e, e.type == 'call.end' && e.interface == 'worktree-isolation.resolve-working-directory' && e.output.working_directory == 'file:///work/app.worktrees/agent-fix-add')"],
     state=CLIENT, input={'isolation': 'worktree', 'branch': 'agent/fix-add'})
scen('agents-ahp-create-session-worktree-no-branch', 'agents-ahp-create-session',
     ["result.ok", "trace.exists(e, e.type == 'call.end' && e.interface == 'worktree-isolation.resolve-working-directory' && !e.output.isolated)"],
     state=CLIENT, input={'isolation': 'worktree', 'branch': ''})
scen('agents-ahp-create-session-claude-needs-auth', 'agents-ahp-create-session',
     ["!result.ok", "result.error.message == 'Authentication is required to use Claude'", "!('claude:/77aa' in state['agent-host-state-manager'].sessions)"],
     state=dict(CLIENT, **{'agent-host-provider-service': {'providers': ['copilot', 'claude']}}), input={'provider': 'claude', 'session': 'claude:/77aa'})
scen('agents-ahp-authenticate-then-claude-session', None,
     ["steps.auth.result.value.authenticated", "steps.create.result.ok", "state['agent-host-state-manager'].sessions['claude:/77aa'].provider == 'claude'"],
     state=dict(CLIENT, **{'agent-host-provider-service': {'providers': ['copilot', 'claude']}}),
     steps=[{'flow': 'agents-ahp-authenticate', 'as': 'auth', 'input': {'resource': 'https://api.anthropic.com', 'token': 'gho_demo'}},
            {'flow': 'agents-ahp-create-session', 'as': 'create', 'input': {'provider': 'claude', 'session': 'claude:/77aa'}}])
scen('agents-ahp-authenticate-revoke', None,
     ["!steps.revoke.result.value.authenticated", "!steps.create.result.ok", "steps.create.result.error.code == 'ahp-provider-not-found'"],
     state=dict(CLIENT, **{'agent-host-provider-service': {'providers': ['copilot', 'claude']}, 'agent-host-authentication-service': {'tokens': {'https://api.anthropic.com': {'token': 'gho_old'}}}}),
     steps=[{'flow': 'agents-ahp-authenticate', 'as': 'revoke', 'input': {'resource': 'https://api.anthropic.com', 'token': ''}},
            {'flow': 'agents-ahp-create-session', 'as': 'create', 'input': {'provider': 'claude', 'session': 'claude:/77aa'}}])
scen('agents-ahp-dispatch-turn-started', None,
     ["steps.turn.result.value.applied", tr('copilot-agent.send-message'), "steps.list.result.value.sessions[0].status == 'in-progress'", "steps.list.result.value.sessions[0].active_turn == 't1'"],
     state=AH_SEEDED, steps=[{'flow': 'agents-ahp-dispatch-action', 'as': 'turn', 'input': {'action': {'type': 'chat-turn-started', 'turn_id': 't1', 'text': 'Add a unit test for add()'}}},
                             {'flow': 'agents-ahp-list-sessions', 'as': 'list'}])
scen('agents-ahp-dispatch-turn-on-archived-session', 'agents-ahp-dispatch-action',
     [ntr('copilot-agent.send-message'), "ctx.last_server_action == 'chat-error'", "state['agent-host-state-manager'].sessions['copilot:/9f2c4e1a'].status == 'error'"],
     state={'agent-host-state-manager': {'sessions': {'copilot:/9f2c4e1a': dict(SEED_SESSION, archived=True)}}},
     input={'action': {'type': 'chat-turn-started', 'turn_id': 't2', 'text': 'continue'}})
scen('agents-ahp-dispatch-turn-read-only-chat', 'agents-ahp-dispatch-action',
     [ntr('copilot-agent.send-message'), "trace.exists(e, e.type == 'call.end' && e.interface == 'turn-admission-contribution.on-incoming-request' && e.output.error.message == 'This chat is read-only.')"],
     state={'agent-host-state-manager': {'sessions': {'copilot:/9f2c4e1a': dict(SEED_SESSION, read_only=True)}}},
     input={'action': {'type': 'chat-turn-started', 'turn_id': 't2', 'text': 'continue'}})
scen('agents-ahp-dispatch-turn-no-agent', 'agents-ahp-dispatch-action',
     ["ctx.last_server_action == 'chat-error'", "trace.exists(e, e.type == 'call.end' && e.interface == 'agent-host-turn-starter.start-turn' && e.output.error.errorType == 'noAgent')"],
     state={'agent-host-state-manager': {'sessions': {'claude:/77aa': dict(SEED_SESSION, session='claude:/77aa', provider='claude')}}},
     input={'session': 'claude:/77aa', 'action': {'type': 'chat-turn-started', 'turn_id': 't1', 'text': 'hi'}})
scen('agents-ahp-dispatch-turn-cancelled', 'agents-ahp-dispatch-action',
     [tr('copilot-agent.abort'), "state['agent-host-state-manager'].sessions['copilot:/9f2c4e1a'].active_turn == ''"],
     state={'agent-host-state-manager': {'sessions': {'copilot:/9f2c4e1a': dict(SEED_SESSION, active_turn='t1', status='in-progress')}}},
     input={'action': {'type': 'chat-turn-cancelled', 'turn_id': 't1'}})
scen('agents-ahp-dispatch-archive-unknown-chat', 'agents-ahp-dispatch-action',
     ["!result.value.applied", "ctx.rejection == 'Only a known chat can change its read state.'", ntr('agent-host-state-manager.dispatch-client-action')],
     input={'action': {'type': 'session-is-archived-changed', 'is_archived': True}})
scen('agents-ahp-dispatch-automation-with-credentials', None,
     ["ctx.rejection == 'Automations do not support client-owned credentials.'"],
     steps=[{'interface': 'agent-service.dispatch-action', 'caller': 'protocol-server-handler',
             'input': {'session': 'ahp-automation:/catalog', 'action': {'type': 'automation-run', 'turn_id': 'x', 'text': ''}, 'client_id': 'w1-client', 'has_credentials': True}}],
     flow='agents-ahp-dispatch-action')
scen('agents-ahp-dispose-session-then-list', None,
     ["steps.dispose.result.ok", "steps.list.result.value.sessions.size() == 0", "!('copilot:/9f2c4e1a' in state['agent-host-database'].sessions_v2)"],
     state=AH_SEEDED, steps=[{'flow': 'agents-ahp-dispose-session', 'as': 'dispose'}, {'flow': 'agents-ahp-list-sessions', 'as': 'list'}])
scen('agents-ahp-dispose-session-unknown-provider', 'agents-ahp-dispose-session',
     ["!result.ok", "result.error.code == 'no-agent-provider-registered'"], input={'session': 'gemini:/1'})
scen('agents-ahp-reconnect-known-client', 'agents-ahp-reconnect', ["result.ok", "result.value.reconnected"], state=CLIENT)
scen('agents-ahp-reconnect-unknown-client', 'agents-ahp-reconnect', ["!result.ok", "result.error.message == 'Reconnect client not found: w1-client'"])

flow('agents-tool-auto-approval', 'session-permissions.get-auto-approval', 'copilot-agent', 'Tool call auto-approval decision', [f'{AH}/node/sessionPermissions.ts:253-360'])
scen('agents-tool-auto-approval-read-in-workdir', 'agents-tool-auto-approval', ["result.value.reason == 'not-needed'"], input={'kind': 'read'})
scen('agents-tool-auto-approval-shell-allowed', 'agents-tool-auto-approval', ["result.value.reason == 'auto-approved-command'"], input={'kind': 'shell', 'command': 'npm test'})
scen('agents-tool-auto-approval-shell-denied', 'agents-tool-auto-approval', ["result.value.reason == 'confirm'",
     "trace.exists(e, e.type == 'call.end' && e.interface == 'command-auto-approver.evaluate' && e.output.result == 'denied')"], input={'kind': 'shell', 'command': 'rm -rf build'})
scen('agents-tool-auto-approval-shell-redirect', 'agents-tool-auto-approval', ["result.value.reason == 'confirm'",
     "trace.exists(e, e.type == 'call.end' && e.interface == 'command-auto-approver.evaluate' && e.output.result == 'noMatch')"], input={'kind': 'shell', 'command': 'ls > /etc/out'})
scen('agents-tool-auto-approval-shell-empty', 'agents-tool-auto-approval', ["result.value.reason == 'auto-approved-command'"], input={'kind': 'shell', 'command': '  '})
scen('agents-tool-auto-approval-terminal-off', 'agents-tool-auto-approval', ["result.value.reason == 'confirm'", ntr('command-auto-approver.evaluate')], input={'kind': 'shell', 'terminal_auto_approve_enabled': False})
scen('agents-tool-auto-approval-global', 'agents-tool-auto-approval', ["result.value.reason == 'setting'"], input={'kind': 'write', 'global_auto_approve': True})
scen('agents-tool-auto-approval-session', 'agents-tool-auto-approval', ["result.value.reason == 'setting'"], input={'kind': 'write', 'session_auto_approve': True})
scen('agents-tool-auto-approval-write', 'agents-tool-auto-approval', ["result.value.reason == 'confirm'"], input={'kind': 'write'})

flow('agents-agent-host-shutdown', 'agent-host-management-service.shutdown', 'agent-host-process-manager', 'Graceful agent host shutdown', [f'{AH}/node/agentHostManagementService.ts:294-320'], tags=['writes'])
flow('agents-agent-host-websocket', 'agent-host-connection-tracker.start-web-socket-server', 'local-agent-host-service-client', 'On-demand local WebSocket server', [f'{AHM}:397-420'], tags=['writes'])
scen('agents-agent-host-websocket-memoized', None,
     ["steps.a.result.value.socket == steps.b.result.value.socket", "state['agent-host-connection-tracker'].socket != ''"],
     steps=[{'flow': 'agents-agent-host-websocket', 'as': 'a'}, {'flow': 'agents-agent-host-websocket', 'as': 'b'}])
scen('agents-agent-host-shutdown-then-websocket-refused', None,
     ["steps.down.result.ok", "!steps.ws.result.ok", "steps.ws.result.error.message == 'Agent Host is shutting down.'"],
     steps=[{'flow': 'agents-agent-host-shutdown', 'as': 'down'}, {'flow': 'agents-agent-host-websocket', 'as': 'ws'}])
scen('agents-agent-host-shutdown-memoized', 'agents-agent-host-shutdown', ["result.ok", ntr('agent-service.shutdown')], state={'agent-host-management-service': {'shutting_down': True}})

flow('agents-agent-host-client-proxy', 'agent-host-client-proxy-channel.call', 'agent-service', 'Host asks the window to resolve a proxy', [f'{AH}/electron-browser/localAgentHostService.ts:871'])
scen('agents-agent-host-client-proxy-resolve', 'agents-agent-host-client-proxy', ["result.value.result == 'DIRECT'"], input={'command': 'resolveProxy'})
scen('agents-agent-host-client-proxy-unknown', 'agents-agent-host-client-proxy', ["!result.ok", "result.error.code == 'unknown-command'"], input={'command': 'setProxy'})
flow('agents-agent-host-byok-chat', 'agent-host-client-byok-lm-channel.call', 'agent-service', 'Host runs a BYOK model request through the window', [f'{AH}/electron-browser/localAgentHostService.ts:874'])
scen('agents-agent-host-byok-chat-happy', 'agents-agent-host-byok-chat', ["result.ok", "result.value.ok"])
flow('agents-agent-host-log-forward', 'agent-host-logger-channel.call', 'agent-host-process-manager', 'Parent forwards the host log', [f'{AHM}:127'])
scen('agents-agent-host-log-forward-happy', 'agents-agent-host-log-forward', ["result.ok"])

# ---------------- MCP
MS1 = 'mcp-server-runtime' + W
WS_SERVER = 'workspace-db'
flow('agents-mcp-start-server', 'mcp-commands.cmd-workbench-mcp-startserver', 'user', 'MCP: Start Server', [f'{MCON}:92', f'{MCMD}:1409-1436'], tags=['writes'])
flow('agents-mcp-server-get', 'mcp-server-runtime.servers-get', 'mcp-commands', 'Read an MCP server (connection state, trust nonce)', [f'{MC}/common/mcpService.ts:183-235'])
scen('agents-mcp-start-server-trusted', None,
     ["steps.start.result.value.state == 'running'", "steps.read.result.value.state == 'running'", "steps.read.result.value.cache_state == 'live'",
      ntr('workspace-trust-request-service.request-workspace-trust'), tr('extension-service.activate-by-event')],
     steps=[{'flow': 'agents-mcp-start-server', 'as': 'start'}, {'flow': 'agents-mcp-server-get', 'as': 'read', 'input': {'server_id': 'github'}}])
scen('agents-mcp-start-server-trust-prompt-accepted', None,
     ["steps.start.result.value.state == 'running'", "steps.read.result.value.trusted_at_nonce == 'n7'",
      "trace.exists(e, e.type == 'choice' && e.key == 'mcp-registry.resolve-connection.trust_prompt')"],
     steps=[{'flow': 'agents-mcp-start-server', 'as': 'start', 'input': {'server_id': WS_SERVER}}, {'flow': 'agents-mcp-server-get', 'as': 'read', 'input': {'server_id': WS_SERVER}}])
scen('agents-mcp-start-server-trust-refused', None,
     ["steps.start.result.value.state == 'stopped'", "steps.read.result.value.trusted_at_nonce == '__vscode_not_trusted'", ntr('mcp-server-connection.start')],
     choices={'mcp-registry.resolve-connection.trust_prompt': 'do_not_trust'},
     steps=[{'flow': 'agents-mcp-start-server', 'as': 'start', 'input': {'server_id': WS_SERVER}}, {'flow': 'agents-mcp-server-get', 'as': 'read', 'input': {'server_id': WS_SERVER}}])
scen('agents-mcp-start-server-trust-dismissed', 'agents-mcp-start-server',
     ["result.value.state == 'stopped'", f"state['{MS1}'].servers['{WS_SERVER}'].trusted_at_nonce == ''"],
     input={'server_id': WS_SERVER}, choices={'mcp-registry.resolve-connection.trust_prompt': 'cancel'})
scen('agents-mcp-start-server-unchanged-nonce', 'agents-mcp-start-server',
     ["result.value.state == 'running'", "!trace.exists(e, e.type == 'choice' && e.key == 'mcp-registry.resolve-connection.trust_prompt')"],
     input={'server_id': WS_SERVER}, state={MS1: {'servers': {WS_SERVER: {'trusted_at_nonce': 'n7'}}}})
scen('agents-mcp-start-server-auto-trust-changes', 'agents-mcp-start-server',
     ["result.value.state == 'running'", f"state['{MS1}'].servers['{WS_SERVER}'].trusted_at_nonce == 'n7'", "!trace.exists(e, e.type == 'choice' && e.key == 'mcp-registry.resolve-connection.trust_prompt')"],
     input={'server_id': WS_SERVER, 'auto_trust_changes': True}, state={MS1: {'servers': {WS_SERVER: {'trusted_at_nonce': 'n6'}}}})
scen('agents-mcp-start-server-launch-error', 'agents-mcp-start-server',
     ["result.value.state == 'error'", f"state['{MS1}'].servers['github'].state == 'error'"], choices={'mcp-server-connection.start.transport': 'launch_error'})
scen('agents-mcp-start-server-exits-before-initialize', 'agents-mcp-start-server',
     ["result.value.state == 'error'", "trace.exists(e, e.type == 'call.end' && e.interface == 'mcp-server-connection.start' && e.output.message == 'Server exited before responding to `initialize` request.')"],
     choices={'mcp-server-connection.start.transport': 'exits_before_initialize'})
scen('agents-mcp-start-server-launch-resolution-error', 'agents-mcp-start-server',
     ["result.value.state == 'stopped'", ntr('mcp-server-connection.start')], choices={'mcp-registry.resolve-connection.launch_resolution': 'error'})
scen('agents-mcp-start-server-policy-denied', 'agents-mcp-start-server',
     ["result.value.state == 'error'", "result.ok", ntr('mcp-registry.resolve-connection')], state={'allowed-mcp-servers-service' + W: {'denylist': ['github']}})
scen('agents-mcp-start-server-not-in-allowlist', 'agents-mcp-start-server',
     ["result.value.state == 'error'", "trace.exists(e, e.type == 'call.end' && e.interface == 'allowed-mcp-servers-service.check-server-allowed' && e.output.message.contains('not in the list'))"],
     state={'allowed-mcp-servers-service' + W: {'allowlist': ['workspace-db']}})
scen('agents-mcp-start-server-access-none', 'agents-mcp-start-server',
     ["result.value.state == 'error'", "trace.exists(e, e.type == 'call.end' && e.interface == 'allowed-mcp-servers-service.check-server-allowed' && e.output.message.contains('disabled in the Editor'))"],
     config={'chat-mcp-access': 'none'})
scen('agents-mcp-start-server-unknown', 'agents-mcp-start-server', ["!result.ok", "result.error.code == 'unknown-server'"], input={'server_id': 'slack'})
scen('agents-mcp-start-server-all', 'agents-mcp-start-server',
     ["result.value.state == 'all'", f"state['{MS1}'].servers['github'].state == 'running'", f"state['{MS1}'].servers['{WS_SERVER}'].state == 'running'"], input={'server_id': '*'})

flow('agents-mcp-stop-server', 'mcp-commands.cmd-workbench-mcp-stopserver', 'user', 'MCP: Stop Server', [f'{MCON}:93'], tags=['writes'])
flow('agents-mcp-restart-server', 'mcp-commands.cmd-workbench-mcp-restartserver', 'user', 'MCP: Restart Server', [f'{MCON}:95'], tags=['writes'])
scen('agents-mcp-stop-server-then-read', None, ["steps.read.result.value.state == 'stopped'"],
     state={MS1: {'servers': {'github': {'state': 'running'}}}},
     steps=[{'flow': 'agents-mcp-stop-server', 'as': 'stop'}, {'flow': 'agents-mcp-server-get', 'as': 'read', 'input': {'server_id': 'github'}}])
scen('agents-mcp-restart-server-then-read', None,
     ["steps.restart.result.value.state == 'running'", "steps.read.result.value.state == 'running'", tr('mcp-server-runtime.stop')],
     state={MS1: {'servers': {'github': {'state': 'running'}}}},
     steps=[{'flow': 'agents-mcp-restart-server', 'as': 'restart'}, {'flow': 'agents-mcp-server-get', 'as': 'read', 'input': {'server_id': 'github'}}])

flow('agents-mcp-autostart', 'mcp-service.autostart', 'chat-service', 'MCP autostart on chat submit', [f'{MC}/common/mcpService.ts:81-162'], tags=['writes'])
scen('agents-mcp-autostart-new-servers', None,
     ["steps.auto.result.value.started == ['github']", "steps.auto.result.value.requiring_interaction == ['workspace-db']", "steps.read.result.value.state == 'running'"],
     steps=[{'flow': 'agents-mcp-autostart', 'as': 'auto'}, {'flow': 'agents-mcp-server-get', 'as': 'read', 'input': {'server_id': 'github'}}])
scen('agents-mcp-autostart-never', 'agents-mcp-autostart', ["result.value.started == []", ntr('mcp-server-runtime.servers-query')], config={'chat-mcp-autostart': 'never'})
scen('agents-mcp-autostart-only-new-skips-outdated', 'agents-mcp-autostart',
     ["result.value.started == []", ntr('mcp-server-runtime.start')], config={'chat-mcp-autostart': 'onlyNew'},
     state={MS1: {'servers': {'github': {'cache_state': 'outdated'}, WS_SERVER: {'enabled': False}}}})
scen('agents-mcp-autostart-outdated', 'agents-mcp-autostart', ["result.value.started == ['github']"],
     state={MS1: {'servers': {'github': {'cache_state': 'outdated'}, WS_SERVER: {'state': 'error'}}}})
scen('agents-mcp-autostart-error-swallowed', 'agents-mcp-autostart',
     ["result.value.started == []", "result.value.requiring_interaction == ['github']"],
     state={MS1: {'servers': {WS_SERVER: {'enabled': False}}}}, choices={'mcp-server-connection.start.transport': 'launch_error'})

flow('agents-mcp-tool-invoke', 'mcp-tool-implementation.invoke', 'chat-service', 'Language model tool invocation of an MCP tool', [f'{MC}/common/mcpLanguageModelToolContribution.ts:265-300'])
flow('agents-mcp-tool-prepare', 'mcp-tool-implementation.prepare-tool-invocation', 'chat-service', 'MCP tool confirmation', [f'{MC}/common/mcpLanguageModelToolContribution.ts:213-263'])
scen('agents-mcp-tool-invoke-happy', 'agents-mcp-tool-invoke', ["result.ok", "result.value.content[0].text == '3 open issues'", tr('mcp-server-runtime.start')])
scen('agents-mcp-tool-invoke-server-fails', 'agents-mcp-tool-invoke',
     ["!result.ok", "result.error.code == 'mcp-connection-failed'", "result.error.message == 'MCP server could not be started: spawn npx ENOENT'"],
     choices={'mcp-server-connection.start.transport': 'launch_error'})
scen('agents-mcp-tool-invoke-server-untrusted', 'agents-mcp-tool-invoke',
     ["!result.ok", "result.error.message == 'MCP server has stopped'"], input={'server_id': WS_SERVER, 'tool': 'query'},
     choices={'mcp-registry.resolve-connection.trust_prompt': 'do_not_trust'})
scen('agents-mcp-tool-prepare-confirm', 'agents-mcp-tool-prepare', ["result.value.confirm", "result.value.title == 'Run search_issues'", "result.value.allow_auto_confirm", "result.value.app_ui"])
scen('agents-mcp-tool-prepare-read-only', 'agents-mcp-tool-prepare', ["!result.value.confirm", "result.value.title == ''"], input={'read_only_hint': True})
scen('agents-mcp-tool-prepare-open-world', 'agents-mcp-tool-prepare', ["result.value.confirm_results"], input={'open_world_hint': True})
scen('agents-mcp-tool-prepare-sandboxed', 'agents-mcp-tool-prepare', ["!result.value.confirm", "!result.value.confirm_results"],
     input={'open_world_hint': True}, state={MS1: {'servers': {'github': {'sandbox_enabled': True}}}})

flow('agents-mcp-sampling', 'mcp-sampling-service.sample', 'mcp-server', 'MCP sampling/createMessage', [f'{MC}/common/mcpSamplingService.ts:59-114'], tags=['writes'])
MSS = 'mcp-sampling-service' + W
scen('agents-mcp-sampling-allow-in-session', None,
     ["steps.first.result.ok", "steps.second.result.ok", f"state['{MSS}'].allowed_during_chat == ['github']",
      "trace.filter(e, e.type == 'choice' && e.key == 'mcp-sampling-service.get-matching-model.allow_prompt').size() == 1"],
     steps=[{'flow': 'agents-mcp-sampling', 'as': 'first'}, {'flow': 'agents-mcp-sampling', 'as': 'second'}])
scen('agents-mcp-sampling-always', None,
     ["steps.first.result.ok", "steps.second.result.ok", f"state['{MSS}'].server_sampling['User: GitHub'].allowedDuringChat == true",
      "trace.filter(e, e.type == 'choice' && e.key == 'mcp-sampling-service.get-matching-model.allow_prompt').size() == 1"],
     choices={'mcp-sampling-service.get-matching-model.allow_prompt': 'always'},
     steps=[{'flow': 'agents-mcp-sampling', 'as': 'first'}, {'flow': 'agents-mcp-sampling', 'as': 'second'}])
scen('agents-mcp-sampling-never', None,
     ["!steps.first.result.ok", "steps.first.result.error.code == 'not-allowed'", "!steps.second.result.ok",
      "trace.filter(e, e.type == 'choice' && e.key == 'mcp-sampling-service.get-matching-model.allow_prompt').size() == 1"],
     choices={'mcp-sampling-service.get-matching-model.allow_prompt': 'never'},
     steps=[{'flow': 'agents-mcp-sampling', 'as': 'first'}, {'flow': 'agents-mcp-sampling', 'as': 'second'}])
scen('agents-mcp-sampling-not-now', 'agents-mcp-sampling', ["!result.ok", "result.error.message == 'The user has denied permission to call this method.'", ntr('language-models-service.send-chat-request')],
     choices={'mcp-sampling-service.get-matching-model.allow_prompt': 'not_now'})
scen('agents-mcp-sampling-outside-chat-configured', 'agents-mcp-sampling',
     ["result.ok", "result.value.model == 'copilot/gpt-4o-mini'", "!trace.exists(e, e.type == 'choice' && e.key == 'mcp-sampling-service.get-matching-model.allow_prompt')"],
     input={'is_during_tool_call': False, 'model_hints': ['mini']},
     config={'chat-mcp-server-sampling': {'User: GitHub': {'allowedOutsideChat': True, 'allowedModels': ['copilot/gpt-4.1', 'copilot/gpt-4o-mini']}}})
scen('agents-mcp-sampling-yolo', 'agents-mcp-sampling', ["result.ok", f"state['{MSS}'].allowed_during_chat == ['github']",
     "!trace.exists(e, e.type == 'choice' && e.key == 'mcp-sampling-service.get-matching-model.allow_prompt')"], config={'chat-tools-global-auto-approve': True})
scen('agents-mcp-sampling-yolo-outside-chat', 'agents-mcp-sampling', ["result.ok", f"state['{MSS}'].allowed_outside_chat == ['github']"],
     input={'is_during_tool_call': False}, config={'chat-tools-global-auto-approve': True})
scen('agents-mcp-sampling-no-models-configure', 'agents-mcp-sampling',
     ["result.ok", "result.value.model == 'copilot/gpt-4.1'", tr('mcp-commands.cmd-workbench-mcp-configuresamplingmodels'), f"state['{MSS}'].server_sampling['User: GitHub'].allowedModels == ['copilot/gpt-4.1']"],
     config={'chat-mcp-server-sampling': {'User: GitHub': {'allowedDuringChat': True, 'allowedModels': []}}})
scen('agents-mcp-sampling-no-models-outside-chat', 'agents-mcp-sampling', ["!result.ok", "result.error.code == 'not-allowed'"],
     input={'is_during_tool_call': False}, config={'chat-mcp-server-sampling': {'User: GitHub': {'allowedOutsideChat': True, 'allowedModels': []}}})
flow('agents-mcp-reset-trust', 'mcp-commands.cmd-workbench-mcp-resettrust', 'user', 'MCP: Reset Trust', [f'{MCON}:85'], tags=['writes'])
scen('agents-mcp-reset-trust-prompts-again', None,
     ["steps.first.result.value.state == 'running'", "steps.reset.result.value.reset == 2", "steps.read.result.value.trusted_at_nonce == 'n7'",
      "trace.filter(e, e.type == 'choice' && e.key == 'mcp-registry.resolve-connection.trust_prompt').size() == 1"],
     state={MS1: {'servers': {WS_SERVER: {'trusted_at_nonce': 'n7'}}}},
     steps=[{'flow': 'agents-mcp-start-server', 'as': 'first', 'input': {'server_id': WS_SERVER}}, {'flow': 'agents-mcp-reset-trust', 'as': 'reset'},
            {'flow': 'agents-mcp-stop-server', 'as': 'stop', 'input': {'server_id': WS_SERVER}},
            {'flow': 'agents-mcp-start-server', 'as': 'again', 'input': {'server_id': WS_SERVER}}, {'flow': 'agents-mcp-server-get', 'as': 'read', 'input': {'server_id': WS_SERVER}}])
flow('agents-mcp-reset-cached-tools', 'mcp-commands.cmd-workbench-mcp-resetcachedtools', 'user', 'MCP: Reset Cached Tools', [f'{MCON}:86'], tags=['writes'])
scen('agents-mcp-reset-cached-tools-then-read', None, ["steps.read.result.value.cache_state == 'unknown'"],
     state={MS1: {'servers': {'github': {'cache_state': 'live'}}}},
     steps=[{'flow': 'agents-mcp-reset-cached-tools', 'as': 'reset'}, {'flow': 'agents-mcp-server-get', 'as': 'read', 'input': {'server_id': 'github'}}])
flow('agents-mcp-skip-autostart', 'mcp-commands.cmd-workbench-mcp-skipautostart', 'user', 'MCP: Skip Current Autostart', [f'{MCON}:107'])
scen('agents-mcp-skip-autostart-happy', 'agents-mcp-skip-autostart', ["result.ok", tr('mcp-service.cancel-autostart')])

flow('agents-mcp-list-servers', 'mcp-commands.cmd-workbench-mcp-listserver', 'user', 'MCP: List Servers', [f'{MCON}:81'])
scen('agents-mcp-list-servers-pick-server', 'agents-mcp-list-servers', ["result.ok", tr('mcp-commands.cmd-workbench-mcp-serveroptions'), f"state['{MS1}'].servers['github'].state == 'running'", tr('mcp-server-runtime.show-output')])
scen('agents-mcp-list-servers-add', 'agents-mcp-list-servers', ["result.ok", tr('workbench-mcp-management-service.install')], choices={'mcp-commands.cmd-workbench-mcp-listserver.picked': 'add'})
scen('agents-mcp-list-servers-add-cancelled', 'agents-mcp-list-servers', ["result.ok", ntr('workbench-mcp-management-service.install')],
     choices={'mcp-commands.cmd-workbench-mcp-listserver.picked': 'add', 'mcp-commands.cmd-workbench-mcp-addconfiguration.server_type': 'cancelled'})
scen('agents-mcp-list-servers-add-http', 'agents-mcp-list-servers', ["trace.exists(e, e.type == 'call.start' && e.interface == 'workbench-mcp-management-service.install' && e.input.config.type == 'http')"],
     choices={'mcp-commands.cmd-workbench-mcp-listserver.picked': 'add', 'mcp-commands.cmd-workbench-mcp-addconfiguration.server_type': 'http'})
scen('agents-mcp-list-servers-agent-host', 'agents-mcp-list-servers', ["result.ok", tr('mcp-commands.cmd-workbench-mcp-agenthostserveroptions')], choices={'mcp-commands.cmd-workbench-mcp-listserver.picked': 'agent_host_server'})
scen('agents-mcp-list-servers-dismissed', 'agents-mcp-list-servers', ["!result.value.ok", ntr('mcp-commands.cmd-workbench-mcp-serveroptions')], choices={'mcp-commands.cmd-workbench-mcp-listserver.picked': 'dismissed'})
flow('agents-mcp-server-options', 'mcp-commands.cmd-workbench-mcp-serveroptionsinconfirmation', 'chat-service', 'MCP server options from a tool confirmation', [f'{MCON}:84'], tags=['writes'])
scen('agents-mcp-server-options-show-output', 'agents-mcp-server-options', ["result.ok", tr('mcp-server-runtime.show-output'), ntr('mcp-server-runtime.start')])
for act, exp in [('stop', [tr('mcp-server-runtime.stop'), f"state['{MS1}'].servers['github'].state == 'stopped'"]),
                 ('restart', [tr('mcp-server-runtime.stop'), f"state['{MS1}'].servers['github'].state == 'running'"]),
                 ('config', [tr('editor-service.open-editor')]),
                 ('config_sampling', [tr('mcp-commands.cmd-workbench-mcp-configuresamplingmodels'), f"state['{MSS}'].server_sampling['User: GitHub'].allowedModels == ['copilot/gpt-4.1']"]),
                 ('resources', [tr('mcp-commands.cmd-workbench-mcp-browseresources')])]:
    scen(f'agents-mcp-server-options-{act.replace("_", "-")}', 'agents-mcp-server-options', ["result.ok"] + exp,
         choices={'mcp-commands.cmd-workbench-mcp-serveroptions.action': act}, state={MS1: {'servers': {'github': {'state': 'running'}}}})

flow('agents-mcp-gateway', 'mcp-gateway-tool-broker-channel.call', 'remote-server-process', 'MCP gateway tool broker channel', [f'{MC}/browser/mcpGatewayToolBrokerContribution.ts:19'])
scen('agents-mcp-gateway-call-tool', 'agents-mcp-gateway', ["result.ok", "result.value.result.content[0].text == '3 open issues'"], input={'command': 'callToolForServer', 'server_id': 'github', 'name': 'search_issues'})
scen('agents-mcp-gateway-unknown-server', 'agents-mcp-gateway', ["!result.ok", "result.error.message == 'Unknown server: slack'"], input={'command': 'callToolForServer', 'server_id': 'slack'})
scen('agents-mcp-gateway-unknown-tool', 'agents-mcp-gateway', ["!result.ok", "result.error.code == 'unknown-tool'"], input={'command': 'callToolForServer', 'server_id': 'github', 'name': 'delete_repo'})
scen('agents-mcp-gateway-list-servers', 'agents-mcp-gateway', ["result.value.result == ['github', 'workspace-db']"], input={'command': 'listServers'})
scen('agents-mcp-gateway-list-tools', 'agents-mcp-gateway', ["result.value.result == ['search_issues', 'create_issue']"], input={'command': 'listToolsForServer', 'server_id': 'github'})
scen('agents-mcp-gateway-list-tools-unknown', 'agents-mcp-gateway', ["result.value.result == []"], input={'command': 'listToolsForServer', 'server_id': 'slack'})
scen('agents-mcp-gateway-list-tools-slow-start', 'agents-mcp-gateway', ["result.ok", "result.value.result == ['search_issues', 'create_issue']",
     "trace.exists(e, e.type == 'call.end' && e.interface == 'mcp-server-runtime.start' && e.late)"],
     input={'command': 'listToolsForServer', 'server_id': 'github'}, faults=[{'target': 'mcp-server-connection.start', 'type': 'latency', 'latency_ms': 6000}])
scen('agents-mcp-gateway-invalid', 'agents-mcp-gateway', ["!result.ok", "result.error.message == 'Invalid call: deleteServer'"], input={'command': 'deleteServer'})

flow('agents-mcp-gallery-manifest-set', 'mcp-gallery-manifest-ipc-service.call', 'workbench', 'Window pushes the MCP gallery manifest (channel mcpGalleryManifest)', [f'{PM}/common/mcpGalleryManifestServiceIpc.ts:31-42'], tags=['writes'])
flow('agents-mcp-gallery-manifest-get', 'mcp-gallery-manifest-ipc-service.get-mcp-gallery-manifest', 'workbench', 'Read the MCP gallery manifest', [f'{PM}/common/mcpGalleryManifestServiceIpc.ts:45-48'])
scen('agents-mcp-gallery-manifest-set-then-get', None, ["steps.get.result.value.status == 'available'", "steps.get.result.value.manifest.url == 'https://api.mcp.github.com/v0'"],
     steps=[{'flow': 'agents-mcp-gallery-manifest-set', 'as': 'set'}, {'flow': 'agents-mcp-gallery-manifest-get', 'as': 'get'}])
scen('agents-mcp-gallery-manifest-invalid-call', 'agents-mcp-gallery-manifest-set', ["!result.ok", "result.error.message == 'Invalid call'"], input={'command': 'getMcpGalleryManifest'})

flow('agents-mcp-elicitation', 'mcp-elicitation-service.elicit', 'mcp-server', 'MCP elicitation/create', [f'{MC}/browser/mcpElicitationService.ts:75-84'])
scen('agents-mcp-elicitation-form-accept', 'agents-mcp-elicitation', ["result.value.action == 'accept'"])
scen('agents-mcp-elicitation-decline', 'agents-mcp-elicitation', ["result.value.action == 'decline'"], choices={'mcp-elicitation-service.elicit.user_response': 'decline'})
scen('agents-mcp-elicitation-cancel', 'agents-mcp-elicitation', ["result.value.action == 'cancel'"], input={'mode': 'url'}, choices={'mcp-elicitation-service.elicit.user_response': 'cancel'})
scen('agents-mcp-elicitation-unsupported', 'agents-mcp-elicitation', ["!result.ok", "result.error.message == 'Unsupported elicitation type'"], input={'mode': 'audio'})

# ---------------- sessions
flow('agents-sessions-window-startup', 'sessions-main.main', 'main-process', 'Agents window startup (desktop)', [f'{SS}/electron-browser/sessions.main.ts:416-420'], tags=['writes'])
flow('agents-sessions-web-startup', 'sessions-web-main.main', 'user', 'Agents window startup (web)', [f'{SS}/sessions.web.main.ts:123-145'])
scen('agents-sessions-window-startup-happy', 'agents-sessions-window-startup',
     ["result.ok", "state['sessions-providers-service@w1'].providers['local-agent-host'].order == 0", "'default' in state['sessions-providers-service@w1'].providers",
      tr('mcp-discovery.start'), tr('extension-mcp-discovery.start'), tr('sessions-service.restore-visible-sessions')])
scen('agents-sessions-window-startup-ai-disabled', 'agents-sessions-window-startup',
     ["result.ok", "!('local-agent-host' in state['sessions-providers-service@w1'].providers)", "trace.exists(e, e.type == 'call.end' && e.interface == 'mcp-discovery.start' && e.output.started.size() == 6)"],
     config={'chat-disable-ai-features': True})
scen('agents-sessions-window-startup-web-runtime', 'agents-sessions-window-startup',
     ["!('local-agent-host' in state['sessions-providers-service@w1'].providers)"], state={'browser-agent-host-enablement-service@w1': {'is_web': True}})
scen('agents-sessions-window-startup-mcp-access-none', 'agents-sessions-window-startup',
     ["trace.exists(e, e.type == 'call.end' && e.interface == 'mcp-discovery.start' && e.output.started.size() == 0)", ntr('extension-mcp-discovery.start')], config={'chat-mcp-access': 'none'})
scen('agents-sessions-window-startup-mcp-access-registry', 'agents-sessions-window-startup',
     ["trace.exists(e, e.type == 'call.end' && e.interface == 'mcp-discovery.start' && e.output.started == ['installed'])"], config={'chat-mcp-access': 'registry'})
scen('agents-sessions-window-startup-duplicate-provider', 'agents-sessions-window-startup',
     ["!result.ok", "result.error.code == 'sessions-provider-already-registered'"], state={'sessions-providers-service@w1': {'providers': {'default': {'id': 'default', 'order': 10}}}})
scen('agents-sessions-window-startup-byok-bridge-fails', 'agents-sessions-window-startup',
     ["result.ok", "trace.exists(e, e.type == 'call.end' && e.interface == 'local-agent-host-service-client.register-client-channels' && e.output.byok == 'null')"],
     choices={'local-agent-host-service-client.register-client-channels.byok_bridge': 'failed'})
scen('agents-sessions-web-startup-happy', 'agents-sessions-web-startup', ["result.ok", "!result.value.local_agent_host"])

flow('agents-open-agents-window', 'open-agents-window-command.' + cmd_slug('workbench.action.openAgentsWindow'), 'user', 'Open Agents Window', [f'{SS}/contrib/openAgentsWindow/electron-browser/openAgentsWindowCommand.ts:13'])
scen('agents-open-agents-window-happy', 'agents-open-agents-window', ["result.ok", "trace.exists(e, e.type == 'call.start' && e.interface == 'native-host-main-service.open-agents-window' && e.input.source == 'commandPalette')"])

flow('agents-sessions-new-session', 'sessions-chat-actions.' + cmd_slug('NewChatInSessionsWindowAction'), 'user', 'Agents window: New Session', [f'{SS}/contrib/chat/browser/chat.contribution.ts:177'], tags=['writes'])
flow('agents-sessions-send', 'sessions-management-service.send-new-chat-request', 'user', 'Send the first request of a new session', [f'{SMS}:818-880'], tags=['writes'])
flow('agents-sessions-list', 'sessions-management-service.get-sessions', 'sessions-view-actions', 'Read the sessions list', [f'{SMS}:244-255'])
scen('agents-sessions-new-session-and-send', None,
     ["steps.new.result.value.session_id == 'local-agent-host/9f2c4e1a'", "steps.send.result.ok", "steps.list.result.value.sessions.size() == 1",
      "state['sessions-service@w1'].active == 'local-agent-host/9f2c4e1a'", tr('chat-service.send-request'), "state['local-agent-host-sessions-provider@w1'].new_session == ''"],
     state={'sessions-providers-service@w1': SEED_PROVIDERS},
     steps=[{'flow': 'agents-sessions-new-session', 'as': 'new'}, {'flow': 'agents-sessions-send', 'as': 'send'}, {'flow': 'agents-sessions-list', 'as': 'list'}])
scen('agents-sessions-new-session-default-provider', 'agents-sessions-new-session', ["result.value.session_id == 'default/cloud-1'", tr('copilot-chat-sessions-provider.create-new-session')],
     state={'sessions-providers-service@w1': {'providers': {'default': {'id': 'default', 'order': 10}}}}, input={'provider_id': 'default'})
scen('agents-sessions-new-session-no-provider', 'agents-sessions-new-session', ["!result.ok", "result.error.message == \"Sessions provider 'local-agent-host' not found\""])
scen('agents-sessions-send-no-provider', 'agents-sessions-send', ["!result.ok", "result.error.code == 'sessions-provider-not-found'"])
scen('agents-sessions-send-unknown-session', 'agents-sessions-send', ["!result.ok", "result.error.code == 'session-not-found'"], state={'sessions-providers-service@w1': SEED_PROVIDERS},
     input={'session_id': 'local-agent-host/0000'})
scen('agents-sessions-send-committed-session', 'agents-sessions-send', ["result.ok", tr('chat-service.send-request')], state=WS_SEEDED)

flow('agents-sessions-rename', 'sessions-actions.' + cmd_slug('sessions.sessionHeader.rename'), 'user', 'Rename a session from its header', [f'{SA}:1953-1965'], tags=['writes'])
scen('agents-sessions-rename-then-read', None,
     ["steps.list.result.value.sessions[0].title == 'Fix add() tests'", "steps.ahp.result.value.sessions[0].title == 'Fix add() tests'"],
     state=WS_SEEDED, steps=[{'flow': 'agents-sessions-rename', 'as': 'rename'}, {'flow': 'agents-sessions-list', 'as': 'list'}, {'flow': 'agents-ahp-list-sessions', 'as': 'ahp'}])
scen('agents-sessions-rename-empty-title', 'agents-sessions-rename', ["result.ok", ntr('sessions-management-service.rename-session')], state=WS_SEEDED, input={'title': '   '})
scen('agents-sessions-rename-unknown-provider', 'agents-sessions-rename', ["result.ok", ntr('local-agent-host-sessions-provider.rename-session')])
scen('agents-sessions-rename-disconnected', 'agents-sessions-rename', ["result.ok", ntr('protocol-server-handler.dispatch-action')],
     state=dict(WS_SEEDED, **{'local-agent-host-sessions-provider@w1': {'session_cache': SEED_CACHE, 'connected': False}}))

flow('agents-sessions-delete', 'sessions-view-actions.' + cmd_slug('sessionsViewPane.deleteSession'), 'user', 'Delete a session', [f'{SVA}:1577-1620'], tags=['writes'])
scen('agents-sessions-delete-then-read', None,
     ["steps.list.result.value.sessions.size() == 0", "steps.ahp.result.value.sessions.size() == 0", tr('agent-service.dispose-session')],
     state=WS_SEEDED, steps=[{'flow': 'agents-sessions-delete', 'as': 'del'}, {'flow': 'agents-sessions-list', 'as': 'list'}, {'flow': 'agents-ahp-list-sessions', 'as': 'ahp'}])
scen('agents-sessions-delete-cancelled', 'agents-sessions-delete', ["!result.value.ok", "size(state['local-agent-host-sessions-provider@w1'].session_cache) == 1"], state=WS_SEEDED,
     choices={'sessions-view-actions.' + cmd_slug('sessionsViewPane.deleteSession') + '.confirm': 'cancel'})
scen('agents-sessions-delete-disconnected', 'agents-sessions-delete', ["result.ok", ntr('protocol-server-handler.dispose-session')],
     state=dict(WS_SEEDED, **{'local-agent-host-sessions-provider@w1': {'session_cache': SEED_CACHE, 'connected': False}}))
scen('agents-sessions-delete-not-cached', 'agents-sessions-delete', ["result.ok", ntr('protocol-server-handler.dispose-session')], state={'sessions-providers-service@w1': SEED_PROVIDERS})

flow('agents-sessions-archive', 'sessions-view-actions.' + cmd_slug('sessionsViewPane.archiveSessionsWithUndo'), 'user', 'Archive (mark done) a session', [f'{SVA}:126-133'], tags=['writes'])
scen('agents-sessions-archive-then-turn-rejected', None,
     ["steps.list.result.value.sessions[0].archived", ntr('copilot-agent.send-message'),
      "trace.exists(e, e.type == 'call.end' && e.interface == 'turn-admission-contribution.on-incoming-request' && e.output.kind == 'reject')"],
     state=WS_SEEDED, steps=[{'flow': 'agents-sessions-archive', 'as': 'archive'}, {'flow': 'agents-sessions-list', 'as': 'list'},
                             {'flow': 'agents-ahp-dispatch-action', 'as': 'turn', 'input': {'action': {'type': 'chat-turn-started', 'turn_id': 't9', 'text': 'more'}}}])
scen('agents-sessions-archive-not-cached', 'agents-sessions-archive', ["result.ok", ntr('protocol-server-handler.dispatch-action')], state={'sessions-providers-service@w1': SEED_PROVIDERS})

flow('agents-sessions-pin', 'sessions-view-actions.' + cmd_slug('sessionsViewPane.pinSession'), 'user', 'Pin a session', [f'{SVA}:1089-1125'], tags=['writes'])
flow('agents-sessions-unpin', 'sessions-view-actions.' + cmd_slug('sessionsViewPane.unpinSession'), 'user', 'Unpin a session', [f'{SVA}:1128-1164'], tags=['writes'])
flow('agents-sessions-is-pinned', 'sessions-list-model-service.is-pinned', 'sessions-view-actions', 'Read pinned state', [f'{SS}/services/sessions/browser/sessionsListModelService.ts:106'])
scen('agents-sessions-pin-then-read', None, ["steps.read.result.value.pinned"], steps=[{'flow': 'agents-sessions-pin', 'as': 'pin'}, {'flow': 'agents-sessions-is-pinned', 'as': 'read'}])
scen('agents-sessions-pin-twice', None, ["trace.filter(e, e.type == 'call.end' && e.interface == 'sessions-list-model-service.pin-session' && !e.output.changed).size() == 1",
     "state['sessions-list-model-service@w1'].pinned == ['local-agent-host/9f2c4e1a']"],
     steps=[{'flow': 'agents-sessions-pin', 'as': 'a'}, {'flow': 'agents-sessions-pin', 'as': 'b'}])
scen('agents-sessions-unpin-then-read', None, ["!steps.read.result.value.pinned"], state={'sessions-list-model-service@w1': {'pinned': ['local-agent-host/9f2c4e1a']}},
     steps=[{'flow': 'agents-sessions-unpin', 'as': 'unpin'}, {'flow': 'agents-sessions-is-pinned', 'as': 'read'}])
scen('agents-sessions-unpin-not-pinned', 'agents-sessions-unpin', ["result.ok", "state['sessions-list-model-service@w1'].pinned == []"])

flow('agents-sessions-close-all', 'sessions-actions.' + cmd_slug('sessions.closeAllSessions'), 'user', 'Close All Sessions', [f'{SA}:567-588'], tags=['writes'])
scen('agents-sessions-close-all-then-restore', None, ["steps.close.result.value.closed == 2", "steps.read.result.value.restored == 0"],
     state={'sessions-service@w1': {'visible': ['local-agent-host/9f2c4e1a', 'local-agent-host/aa11'], 'active': 'local-agent-host/9f2c4e1a'}},
     steps=[{'flow': 'agents-sessions-close-all', 'as': 'close'}, {'interface': 'sessions-service.restore-visible-sessions', 'caller': 'sessions-workbench', 'as': 'read'}])
scen('agents-sessions-close-all-empty', 'agents-sessions-close-all', ["result.value.closed == 0"])

flow('agents-sessions-branch-chat', 'sessions-chat-actions.' + cmd_slug('workbench.action.chat.branchChatSession'), 'user', 'Branch Chat (not supported)', [f'{SS}/contrib/chat/browser/chat.contribution.ts:644'])
scen('agents-sessions-branch-chat-unsupported', 'agents-sessions-branch-chat', ["!result.ok", "result.error.message == 'Branching chat sessions is not yet supported.'"])

flow('agents-sessions-quit-veto', 'local-agent-host-lifecycle-contribution.on-before-shutdown', 'lifecycle-service', 'Quit while a local agent session is working', [f'{SS}/contrib/providers/agentHost/electron-browser/localAgentHostLifecycle.contribution.ts:43-68'])
scen('agents-sessions-quit-veto-idle', 'agents-sessions-quit-veto', ["!result.value.veto"])
scen('agents-sessions-quit-veto-working-confirmed', 'agents-sessions-quit-veto', ["!result.value.veto"], state={'local-agent-host-lifecycle-contribution@w1': {'active_session_working': True}})
scen('agents-sessions-quit-veto-working-cancelled', 'agents-sessions-quit-veto', ["result.value.veto"], state={'local-agent-host-lifecycle-contribution@w1': {'active_session_working': True}},
     choices={'local-agent-host-lifecycle-contribution.on-before-shutdown.confirm_quit': 'cancel'})
scen('agents-sessions-quit-veto-reload', 'agents-sessions-quit-veto', ["!result.value.veto"], state={'local-agent-host-lifecycle-contribution@w1': {'active_session_working': True}}, input={'reason': 'reload'})

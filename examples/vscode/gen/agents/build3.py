# part 3: agent host interfaces
AHM = f'{AH}/node/agentHostMain.ts'
ASV = f'{AH}/node/agentService.ts'
PSH = f'{AH}/node/protocolServerHandler.ts'
STM = f'{AH}/node/agentHostStateManager.ts'
PMG = f'{AH}/node/agentHostService.ts'

SESSION_URI = s('copilot:/9f2c4e1a', default='copilot:/9f2c4e1a')
StartReq = obj({'claude_sdk_available': {'type': 'boolean', 'default': False},
                'codex_enabled_env': {'type': 'boolean', 'default': False},
                'codex_root_config_enabled': {'type': 'boolean', 'default': False},
                'configured_port': s(default='')})

# --- agent-host-main
iface('agent-host-main', 'start', 'startAgentHost: runtime, providers, IPC channels, protocol endpoints, optional configured WebSocket server.',
      [f'{AHM}:113-546', f'{AHM}:74-80'], request=StartReq,
      response=obj({'channels': {'type': 'array'}, 'providers': {'type': 'array'}, 'websocket': S}),
      errors=[err('agent-host-startup-failed', 'startAgentHost rejected: formatAgentHostStartupFailure to stderr, process.exit(1)')],
      behavior=[
          {'title': 'Exit diagnostics, then startAgentHost()', 'detail': 'A rejection is printed and the process exits with code 1.', 'source': f'{AHM}:74-80'},
          {'title': 'Create the runtime and register providers', 'source': f'{AHM}:155-229',
           'call': 'agent-host-provider-service.register-providers',
           'input': {'claude_sdk_available': '= input.claude_sdk_available', 'codex_enabled_env': '= input.codex_enabled_env', 'codex_root_config_enabled': '= input.codex_root_config_enabled'},
           'as': 'reg',
           'on_error': [{'title': "'Failed to create AgentService': disposed and rethrown; the process exits 1", 'source': f'{AHM}:226-230',
                         'fail': {'code': 'agent-host-startup-failed', 'message': "= 'Failed to create AgentService: ' + error.message"}}]},
          {'title': 'registerChannel agentHostLogger (utility process)', 'source': f'{AHM}:127', 'set': {'vars.channels': ['agentHostLogger']}},
          {'title': 'registerChannel agentHostProtocol before the local socket endpoint starts', 'source': f'{AHM}:348',
           'set': {'vars.channels': "= vars.channels + ['agentHostProtocol']"}},
          {'title': 'registerChannel agentHostManagement', 'source': f'{AHM}:513', 'set': {'vars.channels': "= vars.channels + ['agentHostManagement']"}},
          {'title': 'Start the configured WebSocket server (non-fatal)', 'source': f'{AHM}:519-540',
           'call': 'agent-host-main.start-configured-web-socket-server', 'input': {'port': '= input.configured_port'}, 'as': 'ws', 'on_error': 'continue'},
          {'call': 'agent-host-worktree-cleanup-service.start', 'title': 'Contributions activate: worktree cleanup starts', 'source': f'{AH}/node/agentHostBootstrap.ts:230'},
          {'return': {'channels': '= vars.channels', 'providers': '= vars.reg.value.providers',
                      'websocket': "= vars.ws.ok ? vars.ws.value.listening : 'failed'"}},
      ])
iface('agent-host-main', 'start-configured-web-socket-server', 'startWebSocketServer: only when VSCODE_AGENT_HOST_PORT or _SOCKET_PATH is set; prints "Agent host server listening on ...".',
      [f'{AHM}:616-688'], request=obj({'port': s(default='')}), response=obj({'listening': S}),
      behavior=[
          {'if': "input.port == ''", 'then': [{'title': 'No port or socket path configured: nothing to start', 'source': f'{AHM}:629-634', 'return': {'listening': 'none'}}]},
          {'title': 'Agent host server listening on <target>', 'source': f'{AHM}:687', 'return': {'listening': "= 'localhost:' + input.port"}},
      ])
iface('agent-host-logger-channel', 'call', 'LoggerChannel: forwards host log records to the parent logger service.',
      [f'{AHM}:122-139'], request=obj({'command': s('log')}), response=obj({'ok': B}), kind='ipc', attributes={'channel': 'agentHostLogger'},
      behavior=[{'return': {'ok': True}}])

# --- provider service
iface('agent-host-provider-service', 'register-providers', 'Register CopilotAgent first (default), Claude if enabled and its SDK is available, Codex if the env var or root config enables it.',
      [f'{AHM}:188-225', f'{AH}/node/agentHostProviderService.ts:81-104'],
      request=obj({'claude_sdk_available': B, 'codex_enabled_env': B, 'codex_root_config_enabled': B}),
      response=obj({'providers': {'type': 'array'}, 'default': S}),
      behavior=[
          {'title': 'CopilotAgent is always registered first, so it becomes the default provider', 'source': f'{AHM}:190', 'set': {'vars.p': ['copilot']}},
          {'if': "config['chat-agent-host-claude-agent-enabled'] && input.claude_sdk_available",
           'then': [{'title': 'ClaudeAgent registered (enabled and SDK available)', 'source': f'{AHM}:204-206', 'set': {'vars.p': "= vars.p + ['claude']"}}]},
          {'if': 'input.codex_enabled_env || input.codex_root_config_enabled',
           'then': [{'title': 'CodexAgent registered (env var or root config codexAgentEnabled)', 'source': f'{AHM}:210-225', 'set': {'vars.p': "= vars.p + ['codex']"}}]},
          {'set': {'state.providers': '= vars.p'}},
          {'return': {'providers': '= vars.p', 'default': '= vars.p[0]'}},
      ])
iface('agent-host-provider-service', 'resolve-provider', 'resolveProvider: the explicit provider id, or the default (first registered).',
      [f'{AH}/node/agentHostProviderService.ts:122-124'], request=obj({'provider': s('copilot', default='')}),
      response=obj({'found': B, 'provider': S}),
      behavior=[
          {'if': "input.provider == ''", 'then': [{'return': {'found': '= size(state.providers) > 0', 'provider': "= size(state.providers) > 0 ? state.providers[0] : ''"}}]},
          {'return': {'found': '= input.provider in state.providers', 'provider': '= input.provider'}},
      ])
iface('agent-host-provider-service', 'get-provider-for-session', 'getProviderForSession: the associated provider, else the provider named by the session URI scheme.',
      [f'{AH}/node/agentHostProviderService.ts:130-141'], request=obj({'session': SESSION_URI}), response=obj({'found': B, 'provider': S}),
      behavior=[
          {'set': {'vars.scheme': "= input.session.split(':')[0]"}},
          {'return': {'found': '= vars.scheme in state.providers', 'provider': '= vars.scheme'}},
      ])

# --- database and state manager stores
for t, op, extra in [('sessions-v2-get', 'get', {'default': {'missing': True}}), ('sessions-v2-put', 'put', {'value': '= input.value'}), ('sessions-v2-delete', 'delete', {})]:
    st = {'table': 'sessions_v2', 'op': op, 'key': '= input.session'}
    st.update(extra)
    iface('agent-host-database', t, f'agent-host.db sessions_v2 {op} (session registration).',
          [f'{AH}/node/agentHostDatabase.ts:673-731'], kind='sql', request=obj({'session': SESSION_URI, 'value': {'type': 'object'}}, ['session']), store=st)

SessRow = obj({'session': SESSION_URI, 'provider': s('copilot'), 'title': S, 'status': s('idle'), 'archived': B, 'read_only': B, 'active_turn': S})
iface('agent-host-state-manager', 'sessions-get', 'getSessionState / getSessionSummary for a session channel (null when unknown).',
      [f'{STM}:2567'], request=obj({'session': SESSION_URI}, ['session']), store={'table': 'sessions', 'op': 'get', 'key': '= input.session', 'default': {'missing': True}})
iface('agent-host-state-manager', 'sessions-put', 'createSession: add a session summary with its default chat.',
      [f'{STM}:1171'], request=SessRow, store={'table': 'sessions', 'op': 'put', 'key': '= input.session', 'value': '= input'})
iface('agent-host-state-manager', 'sessions-update', 'Apply a reducer result to a session summary.',
      [f'{STM}:2601-2603'], request=obj({'session': SESSION_URI, 'patch': {'type': 'object'}}, ['session', 'patch']),
      errors=[err('unknown-chat-owner', 'Unknown chat owner: <chat>')],
      store={'table': 'sessions', 'op': 'update', 'key': '= input.session', 'value': '= input.patch', 'not_found': 'unknown-chat-owner'})
iface('agent-host-state-manager', 'sessions-delete', 'removeSession.', [f'{STM}:2205'], request=obj({'session': SESSION_URI}, ['session']),
      store={'table': 'sessions', 'op': 'delete', 'key': '= input.session'})
iface('agent-host-state-manager', 'sessions-query', 'All session summaries (listSessions source).', [f'{STM}:3173-3195'],
      request=obj({}), store={'table': 'sessions', 'op': 'query'})
ActionSchema = obj({'type': s('session-title-changed', 'chat-turn-started', 'session-is-archived-changed', 'chat-turn-cancelled'),
                    'title': S, 'is_archived': B, 'turn_id': s('t1'), 'text': s('Add a unit test for add()')}, ['type'])
iface('agent-host-state-manager', 'dispatch-client-action', 'dispatchClientAction: run the reducer on the session and emit an action envelope with the next server sequence number.',
      [f'{STM}:2601-2603'], request=obj({'session': SESSION_URI, 'action': ActionSchema}, ['session', 'action']), response=obj({'server_seq': I}),
      behavior=[
          {'set': {'state.server_seq': '= state.server_seq + 1'}},
          {'if': "input.action.type == 'session-title-changed'", 'then': [{'call': 'agent-host-state-manager.sessions-update', 'input': {'session': '= input.session', 'patch': {'title': '= input.action.title'}}}]},
          {'if': "input.action.type == 'session-is-archived-changed'", 'then': [{'call': 'agent-host-state-manager.sessions-update', 'input': {'session': '= input.session', 'patch': {'archived': '= input.action.is_archived'}}}]},
          {'if': "input.action.type == 'chat-turn-started'", 'then': [{'title': 'Active turn tracked; aggregate status InProgress', 'source': f'{STM}:3083-3091',
                                                                   'call': 'agent-host-state-manager.sessions-update', 'input': {'session': '= input.session', 'patch': {'active_turn': '= input.action.turn_id', 'status': 'in-progress'}}}]},
          {'if': "input.action.type == 'chat-turn-cancelled'", 'then': [{'call': 'agent-host-state-manager.sessions-update', 'input': {'session': '= input.session', 'patch': {'active_turn': '', 'status': 'idle'}}}]},
          {'return': {'server_seq': '= state.server_seq'}},
      ])
iface('agent-host-state-manager', 'dispatch-server-action', 'dispatchServerAction: a host-originated action (ChatError, turn end).',
      [f'{STM}:2588'], request=obj({'session': SESSION_URI, 'type': s('chat-error'), 'message': S}), response=obj({'server_seq': I}),
      behavior=[{'set': {'state.server_seq': '= state.server_seq + 1', 'ctx.last_server_action': '= input.type'}},
                {'if': "input.type == 'chat-error'", 'then': [{'call': 'agent-host-state-manager.sessions-update', 'on_error': 'continue',
                                                              'input': {'session': '= input.session', 'patch': {'active_turn': '', 'status': 'error'}}}]},
                {'return': {'server_seq': '= state.server_seq'}}])
iface('agent-host-state-manager', 'reject-client-action', 'rejectClientAction: emit a rejection envelope with the reason; the reducer is not run.',
      [f'{STM}:2614-2624'], request=obj({'session': SESSION_URI, 'reason': S}), response=obj({'rejected': B, 'reason': S}),
      behavior=[{'set': {'state.server_seq': '= state.server_seq + 1', 'ctx.rejection': '= input.reason'}},
                {'return': {'rejected': True, 'reason': '= input.reason'}}])

# --- agent service
CreateReq = obj({'provider': s('copilot', default=''), 'session': SESSION_URI, 'working_directories': {'type': 'array', 'items': s('file:///work/app'), 'default': ['file:///work/app']},
                 'isolation': s('folder', default='folder'), 'branch': s(default='')}, ['session'])
iface('agent-service', 'create-session', 'createSession: resolve the provider, check the storage identity, optional worktree, provider createChat, register and add to state.',
      [f'{ASV}:5864-5872', f'{ASV}:5874-5971'], request=CreateReq, response=obj({'session': S, 'provider': S}),
      errors=[err('no-agent-provider-registered', 'No agent provider registered for: <provider>'),
              err('session-already-owned', 'Session <uri> is already owned by <provider>')],
      behavior=[
          {'call': 'agent-host-provider-service.resolve-provider', 'input': {'provider': '= input.provider'}, 'as': 'rp'},
          {'if': '!vars.rp.value.found', 'then': [{'title': 'No provider', 'source': f'{ASV}:5877-5879',
                                                   'fail': {'code': 'no-agent-provider-registered', 'message': "= 'No agent provider registered for: ' + (input.provider == '' ? '(none)' : input.provider)"}}]},
          {'call': 'agent-host-database.sessions-v2-get', 'input': {'session': '= input.session'}, 'as': 'reg'},
          {'if': '!has(vars.reg.value.missing) && vars.reg.value.provider != vars.rp.value.provider',
           'then': [{'title': 'Registered to another provider', 'source': f'{ASV}:5885-5888',
                     'fail': {'code': 'session-already-owned', 'message': "= 'Session ' + input.session + ' is already owned by ' + vars.reg.value.provider"}}]},
          {'if': 'size(input.working_directories) > 1', 'then': [{'title': 'More than one working directory without multipleWorkingDirectories: truncated to the first', 'source': f'{ASV}:5918-5921'}]},
          {'if': "input.isolation == 'worktree'", 'then': [{'call': 'worktree-isolation.resolve-working-directory', 'as': 'wt',
                                                            'input': {'folder': '= input.working_directories[0]', 'isolation': 'worktree', 'branch': '= input.branch', 'is_git_repo': True}}]},
          {'title': 'The harness creates the SDK chat; a failure rolls back the provider session', 'source': f'{ASV}:5960-5971',
           'call': "= vars.rp.value.provider + '-agent.create-chat'", 'targets': ['copilot-agent.create-chat', 'claude-agent.create-chat'],
           'input': {'session': '= input.session'}, 'as': 'chat'},
          {'call': 'agent-host-database.sessions-v2-put', 'input': {'session': '= input.session', 'value': {'session': '= input.session', 'provider': '= vars.rp.value.provider'}}},
          {'call': 'agent-host-state-manager.sessions-put', 'input': {'session': '= input.session', 'provider': '= vars.rp.value.provider', 'title': '', 'status': 'idle', 'archived': False, 'read_only': False, 'active_turn': ''}},
          {'return': {'session': '= input.session', 'provider': '= vars.rp.value.provider'}},
      ])
iface('agent-service', 'dispose-session', 'disposeSession: residency disposal; unregister and remove from state.',
      [f'{ASV}:10320-10340'], request=obj({'session': SESSION_URI}, ['session']), response=obj({'disposed': B}),
      errors=[err('no-agent-provider-registered', 'No agent provider registered for: <provider>')],
      behavior=[
          {'call': 'agent-host-provider-service.get-provider-for-session', 'input': {'session': '= input.session'}, 'as': 'p'},
          {'if': '!vars.p.value.found', 'then': [{'fail': {'code': 'no-agent-provider-registered', 'message': "= 'No agent provider registered for: ' + vars.p.value.provider"}}]},
          {'call': 'agent-host-database.sessions-v2-delete', 'input': {'session': '= input.session'}},
          {'call': 'agent-host-state-manager.sessions-delete', 'input': {'session': '= input.session'}},
          {'return': {'disposed': True}},
      ])
iface('agent-service', 'list-sessions', 'listSessions (single-flight per mode).', [f'{ASV}:4850-4870'],
      request=obj({}), response=obj({'sessions': {'type': 'array'}}),
      behavior=[{'call': 'agent-host-state-manager.sessions-query', 'as': 'q'}, {'return': {'sessions': '= vars.q.value'}}])
iface('agent-service', 'dispatch-action', 'dispatchAction: automation guard, unknown-chat guard, apply through the state manager, then side effects.',
      [f'{ASV}:11610-11670', f'{ASV}:12682-12740'],
      request=obj({'session': SESSION_URI, 'action': ActionSchema, 'client_id': s('w1-client'), 'has_credentials': {'type': 'boolean', 'default': False}}, ['session', 'action']),
      response=obj({'applied': B, 'reason': S}),
      behavior=[
          {'if': "input.action.type.startsWith('automation')",
           'then': [{'if': 'input.has_credentials', 'then': [{'title': 'Automations refuse client-owned credentials', 'source': f'{ASV}:11615-11619',
                                                              'call': 'agent-host-state-manager.reject-client-action', 'input': {'session': '= input.session', 'reason': 'Automations do not support client-owned credentials.'}},
                                                             {'return': {'applied': False, 'reason': 'Automations do not support client-owned credentials.'}}]}]},
          {'call': 'agent-host-state-manager.sessions-get', 'input': {'session': '= input.session'}, 'as': 'owner'},
          {'if': "has(vars.owner.value.missing) && input.action.type == 'session-is-archived-changed'",
           'then': [{'title': 'Unknown chat: archive/read actions are rejected', 'source': f'{ASV}:12629-12645',
                     'call': 'agent-host-state-manager.reject-client-action', 'input': {'session': '= input.session', 'reason': 'Only a known chat can change its read state.'}},
                    {'return': {'applied': False, 'reason': 'unknown-chat'}}]},
          {'call': 'agent-host-state-manager.dispatch-client-action', 'input': {'session': '= input.session', 'action': '= input.action'}, 'on_error': 'continue', 'as': 'applied'},
          {'call': 'agent-side-effects.handle-action', 'input': {'session': '= input.session', 'action': '= input.action'}},
          {'return': {'applied': '= vars.applied.ok', 'reason': ''}},
      ])
iface('agent-service', 'shutdown', 'AgentService.shutdown: drain client dispatch queues, stop providers, flush catalog and session state.',
      [f'{ASV}:15089-15120'], request=obj({}), response=obj({'ok': B}), behavior=[{'return': {'ok': True}}])

# --- side effects and turns
iface('agent-side-effects', 'handle-action', 'Side effects of applied actions: ChatTurnStarted starts a turn; ChatTurnCancelled aborts the harness.',
      [f'{AH}/node/agentSideEffects.ts:1795-1941'], request=obj({'session': SESSION_URI, 'action': ActionSchema}, ['session', 'action']),
      response=obj({'handled': B}),
      behavior=[
          {'if': "input.action.type == 'chat-turn-started'",
           'then': [{'title': 'ChatTurnStarted -> turnService.handleTurnStarted', 'source': f'{AH}/node/agentSideEffects.ts:1795-1801',
                     'call': 'agent-host-turn-service.handle-turn-started', 'input': {'session': '= input.session', 'turn_id': '= input.action.turn_id', 'text': '= input.action.text'}},
                    {'return': {'handled': True}}]},
          {'if': "input.action.type == 'chat-turn-cancelled'",
           'then': [{'call': 'agent-host-provider-service.get-provider-for-session', 'input': {'session': '= input.session'}, 'as': 'p'},
                    {'title': 'ChatTurnCancelled -> complete turn cancelled, agent.chats.abort', 'source': f'{AH}/node/agentSideEffects.ts:1907-1941',
                     'call': "= vars.p.value.provider + '-agent.abort'", 'targets': ['copilot-agent.abort', 'claude-agent.abort'], 'input': {'session': '= input.session'}},
                    {'return': {'handled': True}}]},
          {'return': {'handled': False}},
      ])
iface('agent-host-turn-service', 'handle-turn-started', 'handleTurnStarted: require the chat owner, start the turn, send the message to the harness.',
      [f'{AH}/node/agentHostTurnService.ts:126-172'], request=obj({'session': SESSION_URI, 'turn_id': s('t1'), 'text': S}), response=obj({'started': B}),
      behavior=[{'call': 'agent-host-turn-starter.start-turn', 'input': '= input', 'as': 'st'}, {'return': {'started': '= vars.st.value.started'}}])
iface('agent-host-turn-starter', 'start-turn', 'startTurn: incoming-request contributions may reject; no harness -> ChatError noAgent; else send.',
      [f'{AH}/node/agentHostTurnStarter.ts:70-148'], request=obj({'session': SESSION_URI, 'turn_id': s('t1'), 'text': S}),
      response=obj({'started': B, 'error': {'type': 'object'}}),
      behavior=[
          {'call': 'turn-admission-contribution.on-incoming-request', 'input': {'session': '= input.session'}, 'as': 'adm'},
          {'if': "vars.adm.value.kind == 'reject'",
           'then': [{'title': 'Rejected: ChatError plus turnEnd rejected', 'source': f'{AH}/node/agentHostTurnStarter.ts:92-111',
                     'call': 'agent-host-state-manager.dispatch-server-action', 'input': {'session': '= input.session', 'type': 'chat-error', 'message': '= vars.adm.value.error.message'}},
                    {'return': {'started': False, 'error': '= vars.adm.value.error'}}]},
          {'call': 'agent-host-provider-service.get-provider-for-session', 'input': {'session': '= input.session'}, 'as': 'p'},
          {'if': '!vars.p.value.found',
           'then': [{'title': "No agent: ChatError {errorType: 'noAgent'}", 'source': f'{AH}/node/agentHostTurnStarter.ts:119-137',
                     'call': 'agent-host-state-manager.dispatch-server-action', 'input': {'session': '= input.session', 'type': 'chat-error', 'message': 'No agent found for session'}},
                    {'return': {'started': False, 'error': {'errorType': 'noAgent', 'message': 'No agent found for session'}}}]},
          {'call': "= vars.p.value.provider + '-agent.send-message'", 'targets': ['copilot-agent.send-message', 'claude-agent.send-message'],
           'input': {'session': '= input.session', 'text': '= input.text'}},
          {'return': {'started': True, 'error': {}}},
      ])
iface('turn-admission-contribution', 'on-incoming-request', 'Reject turns on archived sessions/chats or read-only chats.',
      [f'{AH}/node/chatContributions/turnAdmission/turnAdmissionContribution.ts:29-43'], request=obj({'session': SESSION_URI}),
      response=obj({'kind': S, 'error': {'type': 'object'}}),
      behavior=[
          {'call': 'agent-host-state-manager.sessions-get', 'input': {'session': '= input.session'}, 'as': 's'},
          {'if': '!has(vars.s.value.missing) && vars.s.value.archived',
           'then': [{'title': 'Archived session is read-only', 'source': f'{AH}/node/chatContributions/turnAdmission/turnAdmissionContribution.ts:36-38',
                     'return': {'kind': 'reject', 'error': {'errorType': 'archived', 'message': 'This session is archived and read-only. Restore the session to continue the conversation.'}}}]},
          {'if': '!has(vars.s.value.missing) && vars.s.value.read_only',
           'then': [{'return': {'kind': 'reject', 'error': {'errorType': 'readOnly', 'message': 'This chat is read-only.'}}}]},
          {'return': {'kind': 'accept', 'error': {}}},
      ])
for ag, src in [('copilot-agent', f'{AH}/node/copilot/copilotAgent.ts'), ('claude-agent', f'{AH}/node/claude/claudeAgent.ts')]:
    if ag == 'claude-agent':
        iface(ag, 'create-chat', 'chats.createChat: Claude requires an authentication token for its protected resource.',
              [f'{src}:781-785'], request=obj({'session': SESSION_URI}), response=obj({'chat': S}),
              errors=[err('ahp-auth-required', "ProtocolError(AHP_AUTH_REQUIRED -32007): 'Authentication is required to use Claude'")],
              behavior=[{'call': 'agent-host-authentication-service.get-auth-token', 'input': {'resource': 'https://api.anthropic.com'}, 'as': 'tok'},
                        {'if': "vars.tok.value.token == ''", 'then': [{'title': 'No token', 'source': f'{src}:781-785',
                                                                       'fail': {'code': 'ahp-auth-required', 'message': 'Authentication is required to use Claude', 'data': {'jsonrpc_code': -32007}}}]},
                        {'return': {'chat': "= input.session + '#default'"}}])
    else:
        iface(ag, 'create-chat', 'chats.createChat: create the SDK session backing the default chat.', [src],
              request=obj({'session': SESSION_URI}), response=obj({'chat': S}), behavior=[{'return': {'chat': "= input.session + '#default'"}}])
    iface(ag, 'send-message', 'Send the turn message to the SDK; progress comes back as signals.', [src],
          request=obj({'session': SESSION_URI, 'text': S}), response=obj({'accepted': B}), behavior=[{'return': {'accepted': True}}])
    iface(ag, 'abort', 'chats.abort: stop the running SDK turn.', [src], request=obj({'session': SESSION_URI}), response=obj({'aborted': B}),
          behavior=[{'return': {'aborted': True}}])

# --- authentication
iface('agent-host-authentication-service', 'get-auth-token', 'getAuthToken: stored token for the resource (empty when none).',
      [f'{AH}/node/agentHostAuthenticationService.ts:267-273'], request=obj({'resource': s('https://api.anthropic.com')}, ['resource']),
      store={'table': 'tokens', 'op': 'get', 'key': '= input.resource', 'default': {'token': ''}})
iface('agent-host-authentication-service', 'tokens-put', 'Store an accepted token.', [f'{AH}/node/agentHostAuthenticationService.ts:206-214'],
      request=obj({'resource': S, 'token': S}), store={'table': 'tokens', 'op': 'put', 'key': '= input.resource', 'value': {'token': '= input.token'}})
iface('agent-host-authentication-service', 'tokens-delete', 'An empty token revokes the stored one.', [f'{AH}/node/agentHostAuthenticationService.ts:206-214'],
      request=obj({'resource': S}), store={'table': 'tokens', 'op': 'delete', 'key': '= input.resource'})
iface('agent-host-authentication-service', 'authenticate', 'authenticate: dedupe per resource, store the token (empty revokes), fire onDidAuthenticate.',
      [f'{AH}/node/agentHostAuthenticationService.ts:109-223'], request=obj({'resource': s('https://api.anthropic.com'), 'token': s('gho_demo')}, ['resource', 'token']),
      response=obj({'authenticated': B}),
      behavior=[{'if': "input.token == ''", 'then': [{'call': 'agent-host-authentication-service.tokens-delete', 'input': {'resource': '= input.resource'}},
                                                     {'return': {'authenticated': False}}]},
                {'call': 'agent-host-authentication-service.tokens-put', 'input': {'resource': '= input.resource', 'token': '= input.token'}},
                {'return': {'authenticated': True}}])

# --- permissions
iface('session-permissions', 'get-auto-approval', 'getAutoApproval: global/session auto-approve, reads inside the working directory, shell commands through the auto approver; otherwise confirmation.',
      [f'{AH}/node/sessionPermissions.ts:253-360'],
      request=obj({'kind': s('read', 'shell', 'write'), 'in_workdir': {'type': 'boolean', 'default': True}, 'command': s('npm test', default='npm test'),
                   'global_auto_approve': {'type': 'boolean', 'default': False}, 'session_auto_approve': {'type': 'boolean', 'default': False},
                   'terminal_auto_approve_enabled': {'type': 'boolean', 'default': True}}, ['kind']),
      response=obj({'reason': S}),
      behavior=[
          {'if': 'input.global_auto_approve', 'then': [{'title': 'globalAutoApproveEnabled root config', 'source': f'{AH}/node/sessionPermissions.ts:274', 'return': {'reason': 'setting'}}]},
          {'if': 'input.session_auto_approve', 'then': [{'title': 'Session-level autoApprove', 'source': f'{AH}/node/sessionPermissions.ts:279', 'return': {'reason': 'setting'}}]},
          {'if': "input.kind == 'read' && input.in_workdir", 'then': [{'title': 'Reads inside the working directory need no approval', 'source': f'{AH}/node/sessionPermissions.ts:317-326', 'return': {'reason': 'not-needed'}}]},
          {'if': "input.kind == 'shell'",
           'then': [{'if': '!input.terminal_auto_approve_enabled', 'then': [{'title': 'terminalAutoApproveEnabled === false: prompt', 'source': f'{AH}/node/sessionPermissions.ts:339-357', 'return': {'reason': 'confirm'}}]},
                    {'call': 'command-auto-approver.evaluate', 'input': {'command': '= input.command'}, 'as': 'ev'},
                    {'return': {'reason': "= vars.ev.value.result == 'approved' ? 'auto-approved-command' : 'confirm'"}}]},
          {'return': {'reason': 'confirm'}},
      ])
iface('command-auto-approver', 'evaluate', 'evaluate: empty -> approved; deny rule -> denied; unparseable or unapproved redirect -> noMatch; allow rules -> approved.',
      [f'{AH}/node/commandAutoApprover.ts:286-315'],
      request=obj({'command': s('npm test'), 'deny_rules': {'type': 'array', 'default': ['rm']}, 'allow_rules': {'type': 'array', 'default': ['npm test', 'git status', 'ls']}}, ['command']),
      response=obj({'result': S}),
      behavior=[
          {'if': "input.command.trim() == ''", 'then': [{'return': {'result': 'approved'}}]},
          {'if': "input.deny_rules.exists(r, input.command.trim().startsWith(r))", 'then': [{'title': 'Deny rule', 'source': f'{AH}/node/commandAutoApprover.ts:295-297', 'return': {'result': 'denied'}}]},
          {'if': "input.command.contains('>')", 'then': [{'title': 'Write redirection to a non-approved destination', 'source': f'{AH}/node/commandAutoApprover.ts:308-312', 'return': {'result': 'noMatch'}}]},
          {'return': {'result': "= input.allow_rules.exists(r, input.command.trim().startsWith(r)) ? 'approved' : 'noMatch'"}},
      ])

# --- worktrees
iface('worktree-isolation', 'resolve-working-directory', 'resolveWorkingDirectory: create <repo>.worktrees/<branch> for isolation worktree in a git repo, else use the folder.',
      [f'{AH}/node/shared/worktreeIsolation.ts:1118-1170', f'{AH}/common/worktreePaths.ts:19-20'],
      request=obj({'folder': s('file:///work/app'), 'isolation': s('worktree'), 'branch': s('agent/fix-add'), 'is_git_repo': B}), response=obj({'working_directory': S, 'isolated': B}),
      behavior=[
          {'if': "input.isolation != 'worktree' || input.branch == '' || !input.is_git_repo",
           'then': [{'title': 'No isolation (not requested, no branch, or not a git repository)', 'source': f'{AH}/node/shared/worktreeIsolation.ts:1128-1148', 'return': {'working_directory': '= input.folder', 'isolated': False}}]},
          {'return': {'working_directory': "= input.folder + '.worktrees/' + input.branch.replace('/', '-')", 'isolated': True}},
      ])
iface('agent-host-worktree-cleanup-service', 'start', 'start: sweep unclaimed detached worktrees, run a pass, schedule periodic passes.',
      [f'{AH}/node/agentHostWorktreeCleanupService.ts:322-330'], request=obj({}), response=obj({'ok': B}),
      behavior=[{'call': 'agent-host-worktree-cleanup-service.run-pass'},
                {'emit': 'agent-host-worktree-cleanup-service.run-pass', 'every_ms': "= config['agent-host-worktree-cleanup-interval-ms']", 'count': 1},
                {'return': {'ok': True}}])
iface('agent-host-worktree-cleanup-service', 'run-pass', 'runPass: single-flight removal of worktrees of archived sessions.',
      [f'{AH}/node/agentHostWorktreeCleanupService.ts:332-352'], request=obj({}), response=obj({'passes': I}),
      behavior=[{'set': {'state.passes': '= state.passes + 1'}}, {'return': {'passes': '= state.passes'}}])

# --- protocol server handler
iface('protocol-server-handler', 'clients-get', 'Connected client record.', [f'{PSH}:955-978'], request=obj({'client_id': s('w1-client')}),
      store={'table': 'clients', 'op': 'get', 'key': '= input.client_id', 'default': {'missing': True}})
iface('protocol-server-handler', 'clients-put', 'Store the client record after initialize.', [f'{PSH}:991-1040'],
      request=obj({'client_id': S, 'protocol_version': S}), store={'table': 'clients', 'op': 'put', 'key': '= input.client_id', 'value': '= input'})
iface('protocol-server-handler', 'initialize', '_handleInitialize: negotiate the protocol version (caret ranges of 1.0.0 and 0.9.0, legacy 0.10.0 preferred), then register the client.',
      [f'{PSH}:991-1040', f'{AH}/common/state/protocol/version/registry.ts:64-80', f'{AH}/common/agentHostProtocolCompatibility.ts:12-23'],
      kind='rpc', attributes={'method': 'initialize'},
      request=obj({'client_id': s('w1-client'), 'protocol_versions': {'type': 'array', 'items': S, 'default': ['1.1.0']}}, ['client_id']),
      response=obj({'protocol_version': S, 'server_version': S}),
      errors=[err('ahp-unsupported-protocol-version', 'ProtocolError -32005: none of the offered versions is compatible')],
      behavior=[
          {'set': {'vars.compatible': "= input.protocol_versions.filter(v, v.startsWith('1.') || v.startsWith('0.9.'))"}},
          {'set': {'vars.negotiated': "= input.protocol_versions.exists(v, v == '0.10.0') ? '0.10.0' : (size(vars.compatible) > 0 ? vars.compatible.filter(v, vars.compatible.all(w, w <= v))[0] : '')"}},
          {'if': "vars.negotiated == ''",
           'then': [{'title': 'Unsupported protocol version (the highest compatible offered version is selected otherwise)', 'source': f'{PSH}:1006-1025',
                     'fail': {'code': 'ahp-unsupported-protocol-version', 'message': "= 'Client offered protocol versions [' + input.protocol_versions.join(', ') + '], none of which are compatible with this server\\'s version 1.1.0'",
                              'data': {'jsonrpc_code': -32005, 'supported_versions': ['1.0.0', '0.10.0', '0.9.0']}}}]},
          {'call': 'protocol-server-handler.clients-put', 'input': {'client_id': '= input.client_id', 'protocol_version': '= vars.negotiated'}},
          {'return': {'protocol_version': '= vars.negotiated', 'server_version': '1.1.0'}},
      ])
iface('protocol-server-handler', 'create-session', 'createSession request: AgentService.createSession; any non-protocol error becomes AHP_PROVIDER_NOT_FOUND (-32002).',
      [f'{PSH}:2126-2177'], kind='rpc', attributes={'method': 'createSession'},
      request=obj({'client_id': s('w1-client'), 'provider': s('copilot', default=''), 'session': SESSION_URI, 'isolation': s('folder', default='folder'), 'branch': s(default='')}, ['client_id', 'session']),
      response=obj({'session': S}), errors=[err('ahp-provider-not-found', 'ProtocolError -32002 wrapping the provider error'), err('method-not-found', 'Method not found before initialize')],
      behavior=[
          {'call': 'protocol-server-handler.clients-get', 'input': {'client_id': '= input.client_id'}, 'as': 'cl'},
          {'if': 'has(vars.cl.value.missing)', 'then': [{'title': 'Requests before initialize: Method not found', 'source': f'{PSH}:886', 'fail': {'code': 'method-not-found', 'message': 'Method not found: createSession'}}]},
          {'call': 'agent-service.create-session', 'as': 'cs',
           'input': {'provider': '= input.provider', 'session': '= input.session', 'working_directories': ['file:///work/app'], 'isolation': '= input.isolation', 'branch': '= input.branch'},
           'on_error': [{'title': 'Wrapped as AHP_PROVIDER_NOT_FOUND', 'source': f'{PSH}:2167-2171', 'fail': {'code': 'ahp-provider-not-found', 'message': '= error.message', 'data': {'jsonrpc_code': -32002}}}]},
          {'return': {'session': '= vars.cs.value.session'}},
      ])
iface('protocol-server-handler', 'dispose-session', 'disposeSession request.', [f'{PSH}:2180-2183'], kind='rpc', attributes={'method': 'disposeSession'},
      request=obj({'session': SESSION_URI}, ['session']), response=obj({'disposed': B}),
      behavior=[{'call': 'agent-service.dispose-session', 'input': {'session': '= input.session'}}, {'return': {'disposed': True}}])
iface('protocol-server-handler', 'list-sessions', 'listSessions request: visible session summaries.', [f'{PSH}:2311-2320'], kind='rpc', attributes={'method': 'listSessions'},
      request=obj({}), response=obj({'sessions': {'type': 'array'}}),
      behavior=[{'call': 'agent-service.list-sessions', 'as': 'l'}, {'return': {'sessions': '= vars.l.value.sessions'}}])
iface('protocol-server-handler', 'dispatch-action', 'dispatchAction notification from a client: forwarded to AgentService.dispatchAction.',
      [f'{PSH}:923-936'], kind='rpc', attributes={'method': 'dispatchAction'},
      request=obj({'session': SESSION_URI, 'action': ActionSchema, 'client_id': s('w1-client')}, ['session', 'action']), response=obj({'applied': B}),
      behavior=[{'call': 'agent-service.dispatch-action', 'input': {'session': '= input.session', 'action': '= input.action', 'client_id': '= input.client_id', 'has_credentials': False}, 'as': 'd'},
                {'return': {'applied': '= vars.d.value.applied'}}])
iface('protocol-server-handler', 'authenticate', 'authenticate request: push a token for a protected resource to the host.',
      [f'{PSH}:2417-2440'], kind='rpc', attributes={'method': 'authenticate'},
      request=obj({'resource': s('https://api.anthropic.com'), 'token': s('gho_demo')}, ['resource', 'token']), response=obj({'authenticated': B}),
      behavior=[{'call': 'agent-host-authentication-service.authenticate', 'input': '= input', 'as': 'a'}, {'return': {'authenticated': '= vars.a.value.authenticated'}}])
iface('protocol-server-handler', 'reconnect', '_handleReconnect: resume a client still in its grace period.',
      [f'{PSH}:1293-1310'], kind='rpc', attributes={'method': 'reconnect'}, request=obj({'client_id': s('w1-client')}), response=obj({'reconnected': B}),
      errors=[err('reconnect-client-not-found', 'Reconnect client not found: <clientId>')],
      behavior=[{'call': 'protocol-server-handler.clients-get', 'input': {'client_id': '= input.client_id'}, 'as': 'cl'},
                {'if': 'has(vars.cl.value.missing)', 'then': [{'title': 'Unknown client', 'source': f'{PSH}:1305', 'fail': {'code': 'reconnect-client-not-found', 'message': "= 'Reconnect client not found: ' + input.client_id"}}]},
                {'return': {'reconnected': True}}])

# --- management, connection tracker
iface('agent-host-management-service', 'shutdown', 'shutdown (memoized): drain protocol and in-flight mutations, AgentService.shutdown, wait for session data.',
      [f'{AH}/node/agentHostManagementService.ts:294-320'], kind='ipc', attributes={'channel': 'agentHostManagement'}, request=obj({}), response=obj({'ok': B}),
      behavior=[{'if': 'state.shutting_down', 'then': [{'return': {'ok': True}}]},
                {'set': {'state.shutting_down': True}},
                {'call': 'agent-service.shutdown'},
                {'return': {'ok': True}}])
iface('agent-host-management-service', 'is-shutting-down', 'Shutdown flag read by the connection tracker and mutations.', [f'{AH}/node/agentHostManagementService.ts:322-331'],
      request=obj({}), response=obj({'shutting_down': B}), behavior=[{'return': {'shutting_down': '= state.shutting_down'}}])
iface('agent-host-connection-tracker', 'start-web-socket-server', 'startWebSocketServer: refuses during shutdown; memoized socket path vscode-agent-host-<uuid>.sock.',
      [f'{AHM}:397-420'], kind='ipc', attributes={'channel': 'agentHostConnectionTracker'}, request=obj({}), response=obj({'socket': S}),
      errors=[err('agent-host-shutting-down', 'Agent Host is shutting down.')],
      behavior=[{'call': 'agent-host-management-service.is-shutting-down', 'as': 'sd'},
                {'if': 'vars.sd.value.shutting_down', 'then': [{'title': 'Refused during shutdown', 'source': f'{AHM}:398-400', 'fail': {'code': 'agent-host-shutting-down', 'message': 'Agent Host is shutting down.'}}]},
                {'if': "state.socket == ''", 'then': [{'set': {'state.socket': '/tmp/vscode-agent-host-7c1e.sock'}}]},
                {'return': {'socket': '= state.socket'}}])

# --- standalone server and diff worker
iface('agent-host-server-main', 'parse-server-options', 'parseServerOptions: port, host and connection token flags; conflicting or malformed tokens exit 1.',
      [f'{AH}/node/agentHostServerMain.ts:90-152'],
      request=obj({'port_arg': s(default=''), 'env_port': s(default=''), 'connection_token': s(default=''), 'connection_token_file': s(default=''), 'without_connection_token': {'type': 'boolean', 'default': False}}),
      response=obj({'port': S, 'token': S}), errors=[err('invalid-server-options', 'Error: ... then process exit(1)')],
      behavior=[
          {'if': "input.without_connection_token && (input.connection_token != '' || input.connection_token_file != '')",
           'then': [{'source': f'{AH}/node/agentHostServerMain.ts:121', 'title': 'Conflicting token flags', 'fail': {'code': 'invalid-server-options', 'message': 'Error: --without-connection-token cannot be used with --connection-token or --connection-token-file'}}]},
          {'if': "input.connection_token != '' && input.connection_token_file != ''",
           'then': [{'source': f'{AH}/node/agentHostServerMain.ts:127', 'title': 'Two token sources', 'fail': {'code': 'invalid-server-options', 'message': 'Error: --connection-token cannot be used with --connection-token-file'}}]},
          {'if': "input.connection_token != '' && !input.connection_token.matches('^[0-9A-Za-z_-]+$')",
           'then': [{'source': f'{AH}/node/agentHostServerMain.ts:142', 'title': 'Malformed token', 'fail': {'code': 'invalid-server-options', 'message': "= 'Error: The connection token \\'' + input.connection_token + '\\' does not adhere to the characters 0-9, a-z, A-Z, _, or -.'"}}]},
          {'return': {'port': "= input.port_arg != '' ? input.port_arg : (input.env_port != '' ? input.env_port : config['agent-host-server-default-port'])",
                      'token': "= input.without_connection_token ? '' : (input.connection_token != '' ? input.connection_token : 'generated-uuid')"}},
      ])
iface('agent-host-server-main', 'main', 'main: parse options, build the runtime (providers unless --quiet), listen on WebSocket, print READY:<port>.',
      [f'{AH}/node/agentHostServerMain.ts:156-401'],
      request=obj({'port_arg': s(default=''), 'connection_token': s(default=''), 'without_connection_token': {'type': 'boolean', 'default': False}, 'quiet': {'type': 'boolean', 'default': False}}),
      response=obj({'ready': S, 'providers': {'type': 'array'}}),
      behavior=[
          {'call': 'agent-host-server-main.parse-server-options', 'input': {'port_arg': '= input.port_arg', 'env_port': '', 'connection_token': '= input.connection_token', 'connection_token_file': '', 'without_connection_token': '= input.without_connection_token'}, 'as': 'opts'},
          {'set': {'vars.providers': []}},
          {'if': '!input.quiet', 'then': [{'title': 'Providers registered unless --quiet (Codex defaults off)', 'source': f'{AH}/node/agentHostServerMain.ts:233-271',
                                          'call': 'agent-host-provider-service.register-providers', 'input': {'claude_sdk_available': False, 'codex_enabled_env': False, 'codex_root_config_enabled': False}, 'as': 'reg'},
                                         {'set': {'vars.providers': '= vars.reg.value.providers'}}]},
          {'title': 'WebSocketProtocolServer.create, then reportReady writes READY:<port>', 'source': f'{AH}/node/agentHostServerMain.ts:309-356',
           'return': {'ready': "= 'READY:' + vars.opts.value.port", 'providers': '= vars.providers'}},
      ])
iface('diff-compute-service', 'compute-diff-counts', 'computeDiffCounts: post the request to the diff worker and await its reply.',
      [f'{AH}/node/diffComputeService.ts:32-57'], request=obj({'fn': s('computeDiffCounts', default='computeDiffCounts'), 'original': S, 'modified': S}), response=obj({'res': {'type': 'object'}}),
      errors=[err('diff-worker-error', 'The worker replied with err (unknown function or a thrown error)')],
      behavior=[{'call': 'diff-worker.handle-message', 'input': {'fn': '= input.fn'}, 'as': 'w'},
                {'if': "has(vars.w.value.err)", 'then': [{'fail': {'code': 'diff-worker-error', 'message': '= vars.w.value.err'}}]},
                {'return': {'res': '= vars.w.value.res'}}])
iface('diff-worker', 'handle-message', 'Worker message loop: three diff functions, anything else answers err "Unknown function: <fn>".',
      [f'{AH}/node/diffWorkerMain.ts:186-205'], kind='message', request=obj({'fn': s('computeDiffCounts')}), response=obj({'res': {'type': 'object'}}),
      behavior=[{'if': "input.fn in ['computeDiffCounts', 'computeDetailedDiff', 'computeDiffHunks']", 'then': [{'return': {'res': {'added': 1, 'removed': 1}}}]},
                {'title': 'Unknown function', 'source': f'{AH}/node/diffWorkerMain.ts:197-198', 'return': {'err': "= 'Unknown function: ' + input.fn"}}])

# --- process manager (main process)
iface('agent-host-process-manager', 'ensure-started', '_ensureStarted: refuse when quitting or after the restart limit; otherwise start once.',
      [f'{PMG}:78-92'], request=obj({}), response=obj({'started': B}),
      errors=[err('agent-host-process-manager-shutting-down', 'Agent Host process manager is shutting down.'),
              err('agent-host-start-error', 'AgentHostStartError (fatal): Agent Host process stopped after 5 restarts.')],
      behavior=[
          {'if': 'state.quit_requested', 'then': [{'source': f'{PMG}:79-81', 'title': 'Quit requested', 'fail': {'code': 'agent-host-process-manager-shutting-down', 'message': 'Agent Host process manager is shutting down.'}}]},
          {'if': 'state.restart_limit_reached', 'then': [{'source': f'{PMG}:82-84', 'title': 'Restart limit reached',
                                                          'fail': {'code': 'agent-host-start-error', 'message': "= 'Agent Host process stopped after ' + string(config['agent-host-max-restarts']) + ' restarts.'", 'data': {'fatal': True}}}]},
          {'if': 'state.running', 'then': [{'return': {'started': False}}]},
          {'call': 'agent-host-main.start', 'input': {'claude_sdk_available': False, 'codex_enabled_env': False, 'codex_root_config_enabled': False, 'configured_port': ''}},
          {'set': {'state.running': True, 'state.starts': '= state.starts + 1'}},
          {'return': {'started': True}},
      ])
iface('agent-host-process-manager', 'handle-process-exit', '_handleProcessExit: ignore expected Windows shutdown codes; restart immediately while under MaxRestarts, else give up.',
      [f'{PMG}:206-248'], kind='event', request=obj({'code': {'type': 'integer', 'default': 1}, 'platform': s('linux', default='linux')}),
      response=obj({'restarted': B, 'gave_up': B}),
      behavior=[
          {'if': '!state.running', 'then': [{'return': {'restarted': False, 'gave_up': False}}]},
          {'set': {'state.running': False}},
          {'if': 'state.quit_requested', 'then': [{'return': {'restarted': False, 'gave_up': False}}]},
          {'if': "input.platform == 'win32' && input.code in [3221226091, 1073807364]",
           'then': [{'title': 'Expected Windows shutdown exit code', 'source': f'{PMG}:215-218', 'return': {'restarted': False, 'gave_up': False}}]},
          {'if': "state.restart_count < config['agent-host-max-restarts']",
           'then': [{'title': 'Unexpected exit: restart immediately, no backoff', 'source': f'{PMG}:229-243', 'set': {'state.restart_count': '= state.restart_count + 1'}},
                    {'call': 'agent-host-process-manager.ensure-started'},
                    {'return': {'restarted': True, 'gave_up': False}}]},
          {'title': 'Giving up after MaxRestarts', 'source': f'{PMG}:244-247', 'set': {'state.restart_limit_reached': True}},
          {'return': {'restarted': False, 'gave_up': True}},
      ])
iface('agent-host-process-manager', 'restart', 'restart: reset crash bookkeeping, shut the current host down (6 s race), start a new one.',
      [f'{PMG}:98-135'], request=obj({}), response=obj({'started': B}),
      errors=[err('agent-host-process-manager-shutting-down', 'Agent Host process manager is shutting down.')],
      behavior=[
          {'if': 'state.quit_requested', 'then': [{'fail': {'code': 'agent-host-process-manager-shutting-down', 'message': 'Agent Host process manager is shutting down.'}}]},
          {'title': 'Reset restartCount and the limit flag', 'source': f'{PMG}:103-104', 'set': {'state.restart_count': 0, 'state.restart_limit_reached': False}},
          {'if': 'state.running',
           'then': [{'title': 'Graceful shutdown raced against ShutdownTimeoutMs', 'source': f'{PMG}:117-127',
                     'call': 'agent-host-management-service.shutdown', 'timeout_ms': "= config['agent-host-shutdown-timeout-ms']", 'on_error': 'continue'},
                    {'set': {'state.running': False}}]},
          {'call': 'agent-host-main.start', 'input': {'claude_sdk_available': False, 'codex_enabled_env': False, 'codex_root_config_enabled': False, 'configured_port': ''}},
          {'set': {'state.running': True, 'state.starts': '= state.starts + 1'}},
          {'return': {'started': True}},
      ])
iface('agent-host-process-manager', 'status', 'Read the manager bookkeeping (running, restart count, limit).', [f'{PMG}:39-44'],
      request=obj({}), response=obj({'running': B, 'restart_count': I, 'restart_limit_reached': B, 'starts': I}),
      behavior=[{'return': {'running': '= state.running', 'restart_count': '= state.restart_count', 'restart_limit_reached': '= state.restart_limit_reached', 'starts': '= state.starts'}}])

# --- renderer client side
iface('local-agent-host-service-client', 'restart-agent-host', 'restartAgentHost: forward the OTel policy, send vscode:restartAgentHost to the main process.',
      [f'{AH}/electron-browser/localAgentHostService.ts:816-819'], kind='ipc', request=obj({}), response=obj({'started': B}),
      behavior=[{'title': 'ipcRenderer.send(vscode:restartAgentHost) -> starter onRequestRestart -> AgentHostProcessManager.restart', 'source': f'{AH}/node/agentHostService.ts:59-63',
                 'call': 'agent-host-process-manager.restart', 'as': 'r'},
                {'return': {'started': '= vars.r.value.started'}}])
iface('local-agent-host-service-client', 'register-client-channels', 'registerAgentHostClientChannels: agentHostClientProxy, then agentHostClientByokLm (Null channel when the BYOK bridge cannot be created).',
      [f'{AH}/electron-browser/localAgentHostService.ts:866-879'], request=obj({}), response=obj({'channels': {'type': 'array'}, 'byok': S}),
      behavior=[{'title': 'registerChannel agentHostClientProxy', 'source': f'{AH}/electron-browser/localAgentHostService.ts:871', 'set': {'vars.ch': ['agentHostClientProxy']}},
                {'choice': 'byok_bridge', 'default': 'created', 'options': {
                    'created': [{'title': 'registerChannel agentHostClientByokLm', 'source': f'{AH}/electron-browser/localAgentHostService.ts:874', 'set': {'vars.byok': 'real'}}],
                    'failed': [{'title': 'BYOK bridge not registered: NullAgentHostClientByokLmChannel', 'source': f'{AH}/electron-browser/localAgentHostService.ts:875-877', 'set': {'vars.byok': 'null'}}]}},
                {'return': {'channels': "= vars.ch + ['agentHostClientByokLm']", 'byok': '= vars.byok'}}])
iface('agent-host-client-proxy-channel', 'call', 'resolveProxy / lookupAuthorization / lookupKerberosAuthorization through the window request service.',
      [f'{AH}/common/agentHostClientProxyChannel.ts:63-82'], kind='ipc', attributes={'channel': 'agentHostClientProxy'},
      request=obj({'command': s('resolveProxy'), 'url': s('https://api.githubcopilot.com')}), response=obj({'result': S}),
      errors=[err('unknown-command', "Unknown command '<command>' on AgentHostClientProxyChannel")],
      behavior=[{'if': "!(input.command in ['resolveProxy', 'lookupAuthorization', 'lookupKerberosAuthorization'])",
                 'then': [{'source': f'{AH}/common/agentHostClientProxyChannel.ts:81', 'title': 'Unknown command', 'fail': {'code': 'unknown-command', 'message': "= 'Unknown command \\'' + input.command + '\\' on AgentHostClientProxyChannel'"}}]},
                {'return': {'result': 'DIRECT'}}])
iface('agent-host-client-byok-lm-channel', 'call', 'chat: run a bring-your-own-key language model request for the host.',
      [f'{AH}/common/agentHostClientByokLmChannel.ts:111'], kind='ipc', attributes={'channel': 'agentHostClientByokLm'},
      request=obj({'command': s('chat')}), response=obj({'ok': B}), behavior=[{'return': {'ok': True}}])
iface('browser-agent-host-enablement-service', 'is-enabled', 'enabled = runtime available (desktop) && !chat.disableAIFeatures.',
      [f'{AH}/browser/agentHostEnablementService.ts:33', f'{AH}/browser/agentHostEnablementService.ts:51'], request=obj({}), response=obj({'enabled': B}),
      behavior=[{'return': {'enabled': "= !state.is_web && !config['chat-disable-ai-features']"}}])
iface('agent-host-electron-contribution', cmd_slug('workbench.action.chat.restartLocalAgentHost'),
      'Restart Local Agent Host (RestartLocalAgentHostAction, registered here): precondition agentHostEnabled; IAgentHostService.restartAgentHost().',
      [f'{SS}/contrib/providers/agentHost/electron-browser/agentHost.contribution.ts:13', 'src/vs/workbench/contrib/chat/electron-browser/actions/restartAgentHostAction.ts:33-35'],
      kind='command', request=obj({}), response=obj({'ran': B}),
      behavior=[{'call': 'browser-agent-host-enablement-service.is-enabled', 'as': 'en'},
                {'if': '!vars.en.value.enabled', 'then': [{'title': 'Precondition agentHostEnabled is false: the command does not run', 'source': 'src/vs/workbench/contrib/chat/electron-browser/actions/restartAgentHostAction.ts:24-28', 'return': {'ran': False}}]},
                {'call': 'local-agent-host-service-client.restart-agent-host'},
                {'return': {'ran': True}}])

# part 4: MCP and sessions interfaces
MS = f'{MC}/common/mcpServer.ts'
MR = f'{MC}/common/mcpRegistry.ts'
MCMD = f'{MC}/browser/mcpCommands.ts'
MCON = f'{MC}/browser/mcp.contribution.ts'
SID = s('github', default='github')
ServerRow = {'type': 'object'}

# boundary stubs
stub('workspace-trust-management-service', 'is-workspace-trusted', 'workbench-shell', 'isWorkspaceTrusted()', request=obj({}), response=obj({'trusted': {'type': 'boolean', 'examples': [True]}}))
stub('workspace-trust-request-service', 'request-workspace-trust', 'workbench-shell', 'requestWorkspaceTrust({message}): the trust dialog', request=obj({'message': S}), response=obj({'granted': {'type': 'boolean', 'examples': [True]}}))
stub('extension-service', 'activate-by-event', 'exthost', 'Activate extensions listening to an activation event.', request=obj({'activation_event': s('onMcpCollection:mcp.config.usrlocal')}), response=obj({}))
stub('editor-service', 'open-editor', 'workbench-shell', 'Open an editor for a resource.', request=obj({'resource': s('file:///work/app/.vscode/mcp.json')}), response=obj({}))
stub('language-models-service', 'get-language-model-ids', 'chat', 'Registered language model ids (default sampling candidates: models without a multiplier, default first).',
     request=obj({}), response=obj({'ids': {'type': 'array', 'items': S, 'examples': [['copilot/gpt-4.1', 'copilot/gpt-4o-mini']]}}))
stub('language-models-service', 'send-chat-request', 'chat', 'sendChatRequest(model, messages): streamed response.',
     request=obj({'model': s('copilot/gpt-4.1'), 'messages': {'type': 'array'}}), response=obj({'text': s('The sum is 3.')}))
stub('workbench-mcp-management-service', 'install', 'workbench-shell', 'Install an MCP server into the chosen mcp.json (user, remote or workspace).',
     request=obj({'name': s('github'), 'config': {'type': 'object'}, 'target': s('user')}), response=obj({'name': S}))
stub('chat-service', 'send-request', 'chat', 'ChatService.sendRequest(chatResource, query, options).',
     request=obj({'resource': s('vscode-chat-session://local-agent-host/9f2c4e1a'), 'query': s('Add a unit test for add()')}), response=obj({'kind': s('sent')}))
stub('native-host-main-service', 'open-agents-window', 'main-process', 'INativeHostService.openAgentsWindow: open or focus the Agents window.',
     request=obj({'source': s('commandPalette')}), response=obj({}), kind='ipc')
stub('lifecycle-service', 'on-before-shutdown', 'workbench-shell', 'onBeforeShutdown event with a veto join.', kind='event',
     request=obj({'reason': s('quit')}), response=obj({'veto': B}))

# --- mcp-server rows
iface('mcp-server-runtime', 'servers-get', 'The McpServer for a definition id.', [f'{MC}/common/mcpService.ts:183-235'],
      request=obj({'server_id': SID}, ['server_id']), errors=[err('unknown-server', 'Unknown server: <id>')],
      store={'table': 'servers', 'op': 'get', 'key': '= input.server_id', 'not_found': 'unknown-server'})
iface('mcp-server-runtime', 'servers-find', 'Lookup that tolerates unknown ids (null).', [f'{MC}/common/mcpGatewayToolBrokerChannel.ts:229-234'],
      request=obj({'server_id': SID}, ['server_id']), store={'table': 'servers', 'op': 'get', 'key': '= input.server_id', 'default': {'missing': True}})
iface('mcp-server-runtime', 'servers-update', 'Update a server (connection state, trust nonce, cache state).', [f'{MS}:819-822'],
      request=obj({'server_id': SID, 'patch': {'type': 'object'}}, ['server_id', 'patch']), errors=[err('unknown-server', 'Unknown server: <id>')],
      store={'table': 'servers', 'op': 'update', 'key': '= input.server_id', 'value': '= input.patch', 'not_found': 'unknown-server'})
iface('mcp-server-runtime', 'servers-query', 'All servers (McpService.servers).', [f'{MC}/common/mcpService.ts:115-120'], request=obj({}),
      store={'table': 'servers', 'op': 'query'})
StartReq2 = obj({'server_id': SID, 'prompt_type': s('only-new', 'all-untrusted', default='only-new'),
                 'error_on_user_interaction': {'type': 'boolean', 'default': False}, 'auto_trust_changes': {'type': 'boolean', 'default': False}}, ['server_id'])
iface('mcp-server-runtime', 'start', 'McpServer.start (sequenced): policy block, extension activation, registry resolveConnection (trust), connection start, error handling.',
      [f'{MS}:743-917'], request=StartReq2, response=obj({'state': S, 'message': S}),
      errors=[err('user-interaction-required', 'UserInteractionRequiredError: "User interaction required: <reason>"'), err('unknown-server', 'Unknown server: <id>')],
      behavior=[
          {'call': 'mcp-server-runtime.servers-get', 'input': {'server_id': '= input.server_id'}, 'as': 'srv'},
          {'call': 'allowed-mcp-servers-service.check-server-allowed', 'input': {'name': '= input.server_id'}, 'as': 'pol'},
          {'if': '!vars.pol.value.allowed',
           'then': [{'title': 'Policy block: connection state Error with the policy message', 'source': f'{MS}:747-757',
                     'call': 'mcp-server-runtime.servers-update', 'input': {'server_id': '= input.server_id', 'patch': {'state': 'error'}}},
                    {'return': {'state': 'error', 'message': '= vars.pol.value.message'}}]},
          {'title': 'Activate extensions for the collection', 'source': f'{MS}:760-770',
           'call': 'extension-service.activate-by-event', 'input': {'activation_event': "= 'onMcpCollection:' + vars.srv.value.collection"}},
          {'call': 'mcp-registry.resolve-connection', 'as': 'conn',
           'input': {'server_id': '= input.server_id', 'scope': '= vars.srv.value.scope', 'trust_behavior': '= vars.srv.value.trust_behavior',
                     'cache_nonce': '= vars.srv.value.cache_nonce', 'trusted_at_nonce': '= vars.srv.value.trusted_at_nonce', 'label': '= vars.srv.value.label',
                     'prompt_type': '= input.prompt_type', 'error_on_user_interaction': '= input.error_on_user_interaction', 'auto_trust_changes': '= input.auto_trust_changes'}},
          {'call': 'mcp-server-runtime.servers-update', 'input': {'server_id': '= input.server_id', 'patch': {'trusted_at_nonce': '= vars.conn.value.trusted_at_nonce'}}},
          {'if': '!vars.conn.value.connected',
           'then': [{'title': 'No connection (untrusted, cancelled or launch error already shown): Stopped', 'source': f'{MS}:798-800', 'return': {'state': 'stopped', 'message': ''}}]},
          {'call': 'mcp-server-runtime.servers-update', 'input': {'server_id': '= input.server_id', 'patch': {'state': 'starting'}}},
          {'call': 'mcp-server-connection.start', 'input': {'server_id': '= input.server_id', 'transport': '= vars.srv.value.transport'}, 'as': 'cs'},
          {'if': "vars.cs.value.state == 'error'",
           'then': [{'call': 'mcp-server-runtime.servers-update', 'input': {'server_id': '= input.server_id', 'patch': {'state': 'error'}}},
                    {'if': 'input.error_on_user_interaction',
                     'then': [{'title': "Quiet start: reject UserInteractionRequiredError('start')", 'source': f'{MS}:904-906',
                               'fail': {'code': 'user-interaction-required', 'message': 'User interaction required: start'}}]},
                    {'title': 'Interactive start: showInteractiveError (the real promise never settles)', 'source': f'{MS}:896-911',
                     'return': {'state': 'error', 'message': '= vars.cs.value.message'}}]},
          {'call': 'mcp-server-runtime.servers-update', 'input': {'server_id': '= input.server_id', 'patch': {'state': 'running', 'cache_state': 'live'}}},
          {'return': {'state': 'running', 'message': ''}},
      ])
iface('mcp-server-runtime', 'stop', 'stop: connection.stop(), state Stopped.', [f'{MS}:1046-1048', f'{MC}/common/mcpServerConnection.ts:136-141'],
      request=obj({'server_id': SID}, ['server_id']), response=obj({'state': S}),
      behavior=[{'call': 'mcp-server-runtime.servers-update', 'input': {'server_id': '= input.server_id', 'patch': {'state': 'stopped'}}}, {'return': {'state': 'stopped'}}])
iface('mcp-server-runtime', 'show-output', 'showOutput: reveal the server log output channel.', [f'{MS}:683-686'], request=obj({'server_id': SID}), response=obj({'shown': B}),
      behavior=[{'return': {'shown': True}}])
iface('mcp-server-runtime', 'reset-cache', 'McpServerMetadataCache.reset: clears cached tools and trust nonces (cacheState back to Unknown).',
      [f'{MS}:186-190'], request=obj({}), response=obj({'reset': I}),
      behavior=[{'call': 'mcp-server-runtime.servers-query', 'as': 'all'},
                {'foreach': '= vars.all.value', 'as': 'row', 'steps': [
                    {'call': 'mcp-server-runtime.servers-update', 'input': {'server_id': '= vars.row.id', 'patch': {'trusted_at_nonce': '', 'cache_state': 'unknown'}}}]},
                {'return': {'reset': '= size(vars.all.value)'}}])
iface('mcp-server-runtime', 'call-on', 'McpServer.callOn: start (all-untrusted, idempotent), then reject when the server ends in Error or Stopped.',
      [f'{MS}:353-397'], request=obj({'server_id': SID}, ['server_id']), response=obj({'state': S, 'sandbox_enabled': B, 'tools': {'type': 'array'}}),
      errors=[err('mcp-connection-failed', 'McpConnectionFailedError: MCP server could not be started / MCP server has stopped')],
      behavior=[
          {'call': 'mcp-server-runtime.start', 'input': {'server_id': '= input.server_id', 'prompt_type': 'all-untrusted', 'error_on_user_interaction': False, 'auto_trust_changes': False}, 'as': 'st'},
          {'if': "vars.st.value.state == 'error'", 'then': [{'title': 'No live connection, state Error', 'source': f'{MS}:371-372',
                                                            'fail': {'code': 'mcp-connection-failed', 'message': "= 'MCP server could not be started: ' + vars.st.value.message"}}]},
          {'if': "vars.st.value.state == 'stopped'", 'then': [{'title': 'No live connection, state Stopped', 'source': f'{MS}:373-374',
                                                              'fail': {'code': 'mcp-connection-failed', 'message': 'MCP server has stopped'}}]},
          {'call': 'mcp-server-runtime.servers-get', 'input': {'server_id': '= input.server_id'}, 'as': 'srv'},
          {'return': {'state': 'running', 'sandbox_enabled': '= vars.srv.value.sandbox_enabled', 'tools': '= vars.srv.value.tools'}},
      ])
iface('mcp-server-connection', 'start', 'start: Starting, launch the transport, then the initialize handshake (no hard timeout; a 5 s timer only logs).',
      [f'{MC}/common/mcpServerConnection.ts:50-133', f'{MC}/common/mcpServerRequestHandler.ts:102-155'],
      request=obj({'server_id': SID, 'transport': s('ok', default='ok')}), response=obj({'state': S, 'message': S}),
      behavior=[
          {'choice': 'transport', 'default': "= input.transport == 'ok' ? 'running' : input.transport",
           'options': {
               'running': [{'title': 'Transport Running; McpServerRequestHandler.create sends initialize then notifications/initialized', 'source': f'{MC}/common/mcpServerRequestHandler.ts:102-155',
                            'call': 'mcp-server.initialize', 'input': {'protocol_version': '2025-06-18'}},
                           {'return': {'state': 'running', 'message': ''}}],
               'launch_error': [{'title': 'Launch throws: state Error', 'source': f'{MC}/common/mcpServerConnection.ts:70-76',
                                 'return': {'state': 'error', 'message': 'spawn npx ENOENT'}}],
               'exits_before_initialize': [{'title': 'Process exits during initialize', 'source': f'{MC}/common/mcpServerConnection.ts:117-125',
                                            'return': {'state': 'error', 'message': 'Server exited before responding to `initialize` request.'}}]}},
      ])
ResolveReq = obj({'server_id': SID, 'scope': s('user'), 'trust_behavior': s('trusted'), 'cache_nonce': s('n1'), 'trusted_at_nonce': s(''), 'label': s('GitHub'),
                  'prompt_type': s('only-new'), 'error_on_user_interaction': B, 'auto_trust_changes': B})
iface('mcp-registry', 'resolve-connection', 'resolveConnection: workspace trust and server trust (_checkTrust), then launch resolution (inputs, env, sandbox); errors become a notification.',
      [f'{MR}:504-592', f'{MR}:225-289'], request=ResolveReq, response=obj({'connected': B, 'trusted_at_nonce': S}),
      errors=[err('user-interaction-required', 'UserInteractionRequiredError: workspaceTrust / serverTrust / variables')],
      behavior=[
          {'set': {'vars.nonce': '= input.trusted_at_nonce'}},
          {'if': "input.scope == 'workspace'",
           'then': [{'call': 'workspace-trust-management-service.is-workspace-trusted', 'as': 'wt'},
                    {'if': '!vars.wt.value.trusted',
                     'then': [{'if': 'input.error_on_user_interaction', 'then': [{'source': f'{MR}:233-234', 'title': 'Untrusted workspace, quiet', 'fail': {'code': 'user-interaction-required', 'message': 'User interaction required: workspaceTrust'}}]},
                              {'call': 'workspace-trust-request-service.request-workspace-trust', 'input': {'message': 'This MCP server definition is defined in your workspace files.'}, 'as': 'wr'},
                              {'if': '!vars.wr.value.granted', 'then': [{'source': f'{MR}:235-237', 'title': 'Workspace trust refused', 'return': {'connected': False, 'trusted_at_nonce': '= vars.nonce'}}]}]}]},
          {'if': "input.trust_behavior == 'trusted-on-nonce' && input.cache_nonce != input.trusted_at_nonce",
           'then': [
               {'if': 'input.auto_trust_changes', 'then': [{'title': 'Changed but explicitly executed: trust the new nonce', 'source': f'{MR}:249-253', 'set': {'vars.nonce': '= input.cache_nonce'}}],
                'else': [
                    {'if': "input.trusted_at_nonce == '__vscode_not_trusted' && input.prompt_type != 'all-untrusted'",
                     'then': [{'title': 'Previously refused: deny without prompting', 'source': f'{MR}:255-265', 'return': {'connected': False, 'trusted_at_nonce': '= vars.nonce'}}]},
                    {'if': "input.prompt_type == 'never'", 'then': [{'source': f'{MR}:267-270', 'title': 'Trust unknown, promptType never', 'return': {'connected': False, 'trusted_at_nonce': '= vars.nonce'}}]},
                    {'if': 'input.error_on_user_interaction', 'then': [{'source': f'{MR}:272-274', 'title': 'Trust prompt needed, quiet', 'fail': {'code': 'user-interaction-required', 'message': 'User interaction required: serverTrust'}}]},
                    {'title': "Prompt 'Trust and run MCP server <label>?'", 'source': f'{MR}:326-340',
                     'choice': 'trust_prompt', 'default': 'trust', 'options': {
                         'trust': [{'set': {'vars.nonce': '= input.cache_nonce'}}],
                         'do_not_trust': [{'title': 'Refusal stored as __vscode_not_trusted', 'source': f'{MR}:284-285', 'return': {'connected': False, 'trusted_at_nonce': '__vscode_not_trusted'}}],
                         'cancel': [{'source': f'{MR}:281-283', 'title': 'Dismissed', 'return': {'connected': False, 'trusted_at_nonce': '= vars.nonce'}}]}}]}]},
          {'title': 'Replace variables, expand env, sandbox; a non-interaction error shows "Error starting <server>: <message>"', 'source': f'{MR}:543-578',
           'choice': 'launch_resolution', 'default': 'resolved', 'options': {
               'resolved': [{'return': {'connected': True, 'trusted_at_nonce': '= vars.nonce'}}],
               'error': [{'return': {'connected': False, 'trusted_at_nonce': '= vars.nonce'}}]}},
      ])
iface('allowed-mcp-servers-service', 'check-server-allowed', 'checkServerAllowed: chat.mcp.access none, deny list, allow list.',
      [f'{PM}/common/allowedMcpServersService.ts:97-129'], request=obj({'name': SID}), response=obj({'allowed': B, 'message': S}),
      behavior=[
          {'if': "config['chat-mcp-access'] == 'none'", 'then': [{'source': f'{PM}/common/allowedMcpServersService.ts:98-101', 'title': 'Access none',
                                                                 'return': {'allowed': False, 'message': 'Model Context Protocol servers are disabled in the Editor. Please check your [settings].'}}]},
          {'if': 'input.name in state.denylist', 'then': [{'source': f'{PM}/common/allowedMcpServersService.ts:112-113', 'title': 'Denied by policy',
                                                          'return': {'allowed': False, 'message': "This Model Context Protocol server is blocked by your organization's policy. Please contact your administrator for more information."}}]},
          {'if': 'state.allowlist != null && !(input.name in state.allowlist)', 'then': [{'source': f'{PM}/common/allowedMcpServersService.ts:124', 'title': 'Not in the allow list',
                                                                                          'return': {'allowed': False, 'message': 'This Model Context Protocol server is not in the list of servers allowed by your organization. Please contact your administrator for more information.'}}]},
          {'return': {'allowed': True, 'message': ''}},
      ])
iface('mcp-tool', 'call-with-progress', '_callWithProgress: tools/call through McpServer.callOn (meta: progress token, conversation id, traceparent).',
      [f'{MS}:1361-1438'], request=obj({'server_id': SID, 'tool': s('search_issues')}, ['server_id', 'tool']), response=obj({'content': {'type': 'array'}, 'is_error': B}),
      errors=[err('mcp-connection-failed', 'MCP server could not be started / has stopped')],
      behavior=[{'call': 'mcp-server-runtime.call-on', 'input': {'server_id': '= input.server_id'}},
                {'title': 'tools/call on the server', 'source': f'{MS}:1408-1416', 'call': 'mcp-server.tools-call', 'input': {'name': '= input.tool'}, 'as': 'r'},
                {'return': {'content': '= vars.r.value.content', 'is_error': '= vars.r.value.isError'}}])
iface('mcp-server', 'initialize', 'JSON-RPC initialize (capabilities roots, sampling, elicitation, tasks) answered by the external MCP server.',
      [f'{MC}/common/mcpServerRequestHandler.ts:110-140'], kind='rpc', attributes={'method': 'initialize'},
      request=obj({'protocol_version': s('2025-06-18')}), response=obj({'protocolVersion': s('2025-06-18'), 'serverInfo': {'type': 'object', 'default': {'name': 'github-mcp'}}}))
iface('mcp-server', 'tools-call', 'JSON-RPC tools/call answered by the external MCP server.', [f'{MS}:1408-1416'], kind='rpc', attributes={'method': 'tools/call'},
      request=obj({'name': s('search_issues')}), response=obj({'content': {'type': 'array', 'default': [{'type': 'text', 'text': '3 open issues'}]}, 'isError': {'type': 'boolean', 'default': False}}))
iface('mcp-tool-implementation', 'prepare-tool-invocation', 'prepareToolInvocation: start the server to learn sandboxing; non-sandboxed tools without readOnlyHint get a "Run <tool>" confirmation; openWorldHint confirms results.',
      [f'{MC}/common/mcpLanguageModelToolContribution.ts:213-263'],
      request=obj({'server_id': SID, 'tool': s('search_issues'), 'read_only_hint': {'type': 'boolean', 'default': False}, 'open_world_hint': {'type': 'boolean', 'default': False}}, ['server_id', 'tool']),
      response=obj({'confirm': B, 'title': S, 'allow_auto_confirm': B, 'confirm_results': B, 'app_ui': B}),
      behavior=[
          {'call': 'mcp-server-runtime.call-on', 'input': {'server_id': '= input.server_id'}, 'as': 'on'},
          {'set': {'vars.confirm': '= !vars.on.value.sandbox_enabled && !input.read_only_hint'}},
          {'title': 'Confirmation built for non-sandboxed, non-read-only tools', 'source': f'{MC}/common/mcpLanguageModelToolContribution.ts:232-242',
           'return': {'confirm': '= vars.confirm', 'title': "= vars.confirm ? 'Run ' + input.tool : ''", 'allow_auto_confirm': '= vars.confirm',
                      'confirm_results': '= !vars.on.value.sandbox_enabled && input.open_world_hint', 'app_ui': "= config['chat-mcp-apps-enabled']"}},
      ])
iface('mcp-tool-implementation', 'invoke', 'invoke: callWithProgress and map MCP content to tool result parts.',
      [f'{MC}/common/mcpLanguageModelToolContribution.ts:265-300'], request=obj({'server_id': SID, 'tool': s('search_issues')}, ['server_id', 'tool']),
      response=obj({'content': {'type': 'array'}}),
      behavior=[{'call': 'mcp-tool.call-with-progress', 'input': {'server_id': '= input.server_id', 'tool': '= input.tool'}, 'as': 'r'},
                {'return': {'content': '= vars.r.value.content'}}])
iface('mcp-language-model-tool-contribution', 'start', 'Constructor: register a language model tool per enabled server tool with Model visibility.',
      [f'{MC}/common/mcpLanguageModelToolContribution.ts:41-160'], request=obj({}), response=obj({'tools': I}),
      behavior=[{'call': 'mcp-server-runtime.servers-query', 'as': 'all'},
                {'return': {'tools': '= sum(vars.all.value.filter(r, r.enabled).map(r, size(r.tools)))'}}])

# --- sampling
SampReq = obj({'server_id': SID, 'server_key': s('User: GitHub', default='User: GitHub'), 'is_during_tool_call': {'type': 'boolean', 'default': True},
               'model_hints': {'type': 'array', 'items': S, 'default': []}, 'system_prompt': s(default='')}, ['server_id'])
iface('mcp-sampling-service', 'sample', 'sample: map messages, pick a permitted model (sequenced), send the language model request, keep the text.',
      [f'{MC}/common/mcpSamplingService.ts:59-114'], request=SampReq, response=obj({'model': S, 'text': S}),
      errors=[err('not-allowed', "McpError.notAllowed (-32000): 'The user has denied permission to call this method.'")],
      behavior=[{'call': 'mcp-sampling-service.get-matching-model', 'input': '= input', 'as': 'm'},
                {'call': 'language-models-service.send-chat-request', 'input': {'model': '= vars.m.value.model', 'messages': [{'role': 'user', 'text': 'sampling request'}]}, 'as': 'resp'},
                {'return': {'model': '= vars.m.value.model', 'text': '= vars.resp.value.text'}}])
NA = {'code': 'not-allowed', 'message': 'The user has denied permission to call this method.', 'data': {'jsonrpc_code': -32000}}
iface('mcp-sampling-service', 'get-matching-model', '_getMatchingModel(Inner): per-context permission (config, session sets, prompt or YOLO), then allowed or default models matched by hints.',
      [f'{MC}/common/mcpSamplingService.ts:125-180', f'{MC}/common/mcpSamplingService.ts:235-262'], request=SampReq, response=obj({'model': S}),
      errors=[err('not-allowed', 'The user has denied permission to call this method.')],
      behavior=[
          {'set': {'vars.cfg': "= merge(input.server_key in config['chat-mcp-server-sampling'] ? config['chat-mcp-server-sampling'][input.server_key] : {}, input.server_key in state.server_sampling ? state.server_sampling[input.server_key] : {})",
                   'vars.field': "= input.is_during_tool_call ? 'allowedDuringChat' : 'allowedOutsideChat'"}},
          {'set': {'vars.allowed': "= (vars.field in vars.cfg && vars.cfg[vars.field] == true) || (input.is_during_tool_call ? input.server_id in state.allowed_during_chat : input.server_id in state.allowed_outside_chat)"}},
          {'if': '!vars.allowed',
           'then': [
               {'if': 'vars.field in vars.cfg', 'then': [{'title': 'Explicitly not allowed', 'source': f'{MC}/common/mcpSamplingService.ts:238-241', 'fail': NA}]},
               {'if': "config['chat-tools-global-auto-approve']",
                'then': [{'title': 'YOLO mode: allow for this session without prompting', 'source': f'{MC}/common/mcpSamplingService.ts:131-133',
                          'set': {'state.allowed_during_chat': '= input.is_during_tool_call ? state.allowed_during_chat + [input.server_id] : state.allowed_during_chat',
                                  'state.allowed_outside_chat': '= !input.is_during_tool_call ? state.allowed_outside_chat + [input.server_id] : state.allowed_outside_chat'}}],
                'else': [{'title': "Prompt: 'Allow MCP tools from <server> to make LLM requests?'", 'source': f'{MC}/common/mcpSamplingService.ts:134-145',
                          'choice': 'allow_prompt', 'default': 'allow_in_session', 'options': {
                              'allow_in_session': [{'set': {'state.allowed_during_chat': '= input.is_during_tool_call ? state.allowed_during_chat + [input.server_id] : state.allowed_during_chat',
                                                            'state.allowed_outside_chat': '= !input.is_during_tool_call ? state.allowed_outside_chat + [input.server_id] : state.allowed_outside_chat'}}],
                              'always': [{'call': 'mcp-sampling-service.update-config', 'input': {'server_key': '= input.server_key', 'patch': '= {vars.field: true}'}}],
                              'not_now': [{'source': f'{MC}/common/mcpSamplingService.ts:143', 'title': 'Refused', 'fail': NA}],
                              'never': [{'call': 'mcp-sampling-service.update-config', 'input': {'server_key': '= input.server_key', 'patch': '= {vars.field: false}'}},
                                        {'fail': NA}]}}]}]},
          {'if': "'allowedModels' in vars.cfg", 'then': [{'set': {'vars.models': '= vars.cfg.allowedModels'}}],
           'else': [{'call': 'language-models-service.get-language-model-ids', 'as': 'ids'}, {'set': {'vars.models': '= vars.ids.value.ids'}}]},
          {'if': 'size(vars.models) == 0',
           'then': [{'title': 'No matching model: during a tool call run Configure Sampling Models', 'source': f'{MC}/common/mcpSamplingService.ts:163-176',
                     'if': 'input.is_during_tool_call', 'then': [{'call': 'mcp-commands.cmd-workbench-mcp-configuresamplingmodels', 'input': {'server_key': '= input.server_key', 'picked': ['copilot/gpt-4.1']}, 'as': 'picked'},
                                                                  {'if': 'vars.picked.value.count > 0', 'then': [{'return': {'model': 'copilot/gpt-4.1'}}]}]},
                    {'fail': NA}]},
          {'set': {'vars.hit': '= vars.models.filter(m, input.model_hints.exists(h, m.lowerAscii().contains(h.lowerAscii())))'}},
          {'return': {'model': '= size(vars.hit) > 0 ? vars.hit[0] : vars.models[0]'}},
      ])
iface('mcp-sampling-service', 'update-config', 'updateConfig: write chat.mcp.serverSampling for the server at its collection configTarget (mirrored in state: config is immutable in the simulator).',
      [f'{MC}/common/mcpSamplingService.ts:312-325'], request=obj({'server_key': s('User: GitHub'), 'patch': {'type': 'object'}}), response=obj({'ok': B}),
      behavior=[{'set': {'state.server_sampling': '= merge(state.server_sampling, {input.server_key: merge(input.server_key in state.server_sampling ? state.server_sampling[input.server_key] : {}, input.patch)})'}},
                {'return': {'ok': True}}])
iface('mcp-elicitation-service', 'elicit', 'elicit: form questions (chat carousel or notification) or URL elicitation through the opener; other modes are refused.',
      [f'{MC}/browser/mcpElicitationService.ts:75-84'], request=obj({'mode': s('form', 'url', default='form')}), response=obj({'action': S}),
      errors=[err('mpc-response-error', "MpcResponseError('Unsupported elicitation type', INVALID_PARAMS)")],
      behavior=[{'if': "!(input.mode in ['form', 'url'])", 'then': [{'source': f'{MC}/browser/mcpElicitationService.ts:82', 'title': 'Unsupported type', 'fail': {'code': 'mpc-response-error', 'message': 'Unsupported elicitation type', 'data': {'jsonrpc_code': -32602}}}]},
                {'choice': 'user_response', 'default': 'accept', 'options': {'accept': [{'return': {'action': 'accept'}}], 'decline': [{'return': {'action': 'decline'}}], 'cancel': [{'return': {'action': 'cancel'}}]}}])

# --- autostart, discovery
iface('mcp-service', 'autostart', 'autostart: unless chat.mcp.autostart is never, start (quietly, in parallel) enabled non-errored servers that are new (and outdated).',
      [f'{MC}/common/mcpService.ts:81-162'], request=obj({}), response=obj({'started': {'type': 'array'}, 'requiring_interaction': {'type': 'array'}}),
      behavior=[
          {'if': "config['chat-mcp-autostart'] == 'never'", 'then': [{'source': f'{MC}/common/mcpService.ts:82-85', 'title': 'Autostart disabled', 'return': {'started': [], 'requiring_interaction': []}}]},
          {'call': 'mcp-server-runtime.servers-query', 'as': 'all'},
          {'set': {'vars.todo': "= vars.all.value.filter(r, r.state != 'error' && r.enabled && (r.cache_state == 'unknown' || (config['chat-mcp-autostart'] == 'newAndOutdated' && r.cache_state == 'outdated')))"}},
          {'set': {'ctx.requiring_interaction': [], 'ctx.autostarted': []}},
          {'if': 'size(vars.todo) == 0', 'then': [{'return': {'started': [], 'requiring_interaction': []}}]},
          {'title': 'Promise.all over the candidates; UserInteractionRequiredError is collected, other errors swallowed', 'source': f'{MC}/common/mcpService.ts:148-161',
           'parallel': '= vars.todo', 'as': 'row', 'join': {'need': 'all'},
           'steps': [{'call': 'mcp-server-runtime.start', 'input': {'server_id': '= vars.row.id', 'prompt_type': 'only-new', 'error_on_user_interaction': True, 'auto_trust_changes': False}, 'as': 'st',
                      'on_error': [{'if': "error.code == 'user-interaction-required'", 'then': [{'set': {'ctx.requiring_interaction': '= ctx.requiring_interaction + [vars.row.id]'}}]}]},
                     {'if': "vars.st.ok && vars.st.value.state == 'running'", 'then': [{'set': {'ctx.autostarted': '= ctx.autostarted + [vars.row.id]'}}]}]},
          {'return': {'started': '= ctx.autostarted', 'requiring_interaction': '= ctx.requiring_interaction'}},
      ])
iface('mcp-service', 'cancel-autostart', 'cancelAutostart: cancel every running autostart token.', [f'{MC}/common/mcpService.ts:75-79'],
      request=obj({}), response=obj({'cancelled': B}), behavior=[{'return': {'cancelled': True}}])
iface('mcp-service', 'reset-caches', 'resetCaches: reset the user and workspace metadata caches.', [f'{MC}/common/mcpService.ts:164-167'],
      request=obj({}), response=obj({'reset': I}), behavior=[{'call': 'mcp-server-runtime.reset-cache', 'as': 'r'}, {'return': {'reset': '= vars.r.value.reset'}}])
iface('mcp-service', 'reset-trust', 'resetTrust: same as resetCaches, the trust nonce lives in the cache.', [f'{MC}/common/mcpService.ts:169-171'],
      request=obj({}), response=obj({'reset': I}), behavior=[{'call': 'mcp-service.reset-caches', 'as': 'r'}, {'return': {'reset': '= vars.r.value.reset'}}])
iface('mcp-discovery', 'start', 'Constructor autorun: chat.mcp.access none starts nothing; registry starts only gallery-backed discovery; all starts every source.',
      [f'{MC}/browser/mcpDiscovery.ts:18-43'], request=obj({}), response=obj({'started': {'type': 'array'}}),
      behavior=[
          {'if': "config['chat-mcp-access'] == 'none'", 'then': [{'source': f'{MC}/browser/mcpDiscovery.ts:30-32', 'title': 'Access none: no discovery', 'return': {'started': []}}]},
          {'if': "config['chat-mcp-access'] == 'registry'", 'then': [{'source': f'{MC}/browser/mcpDiscovery.ts:35-38', 'title': 'Registry: only fromGallery discovery', 'return': {'started': ['installed']}}]},
          {'call': 'extension-mcp-discovery.start'},
          {'return': {'started': ['remote-native', 'installed', 'extension', 'cursor-workspace', 'workspace-dot-mcp', 'plugin']}},
      ])
iface('extension-mcp-discovery', 'start', 'Handle mcpServerDefinitionProviders contributions: register a lazy, Trusted collection per provider.',
      [f'{MC}/common/discovery/extensionMcpDiscovery.ts:76-109', f'{MC}/common/discovery/extensionMcpDiscovery.ts:27'], request=obj({}), response=obj({'collections': I}),
      behavior=[{'set': {'state.collections': ['ext.vscode.typescript-language-features']}}, {'return': {'collections': 1}}])

# --- gateway, gallery manifest, gallery
iface('mcp-gateway-tool-broker-channel', 'call', 'call: listServers, listToolsForServer, callToolForServer (unknown server/tool throw), resource calls; anything else is invalid.',
      [f'{MC}/common/mcpGatewayToolBrokerChannel.ts:163-198', f'{MC}/common/mcpGatewayToolBrokerChannel.ts:226-245'], kind='ipc', attributes={'channel': 'mcpGatewayToolBroker'},
      request=obj({'command': s('callToolForServer', 'listServers'), 'server_id': SID, 'name': s('search_issues', default='search_issues')}, ['command']),
      response=obj({'result': {}}),
      errors=[err('unknown-server', 'Unknown server: <id>'), err('unknown-tool', "Unknown tool '<name>' on server '<id>'"), err('invalid-call', 'Invalid call: <command>')],
      behavior=[
          {'if': "input.command == 'listServers'", 'then': [{'call': 'mcp-server-runtime.servers-query', 'as': 'all'}, {'return': {'result': '= vars.all.value.map(r, r.id)'}}]},
          {'if': "input.command == 'listToolsForServer'",
           'then': [{'call': 'mcp-server-runtime.servers-find', 'input': {'server_id': '= input.server_id'}, 'as': 'f'},
                    {'if': 'has(vars.f.value.missing)', 'then': [{'return': {'result': []}}]},
                    {'title': '_waitForStartup: race readiness against the grace period', 'source': f'{MC}/common/mcpGatewayToolBrokerChannel.ts:110-134',
                     'call': 'mcp-server-runtime.start', 'input': {'server_id': '= input.server_id', 'prompt_type': 'all-untrusted', 'error_on_user_interaction': True, 'auto_trust_changes': False},
                     'timeout_ms': "= config['mcp-gateway-startup-grace-period-ms']", 'on_error': 'continue', 'as': 'ready'},
                    {'return': {'result': '= vars.f.value.tools'}}]},
          {'if': "input.command == 'callToolForServer'",
           'then': [{'call': 'mcp-server-runtime.servers-find', 'input': {'server_id': '= input.server_id'}, 'as': 'f'},
                    {'if': 'has(vars.f.value.missing)', 'then': [{'source': f'{MC}/common/mcpGatewayToolBrokerChannel.ts:231-234', 'title': 'Unknown server', 'fail': {'code': 'unknown-server', 'message': "= 'Unknown server: ' + input.server_id"}}]},
                    {'if': '!(input.name in vars.f.value.tools)', 'then': [{'source': f'{MC}/common/mcpGatewayToolBrokerChannel.ts:236-241', 'title': 'Unknown tool',
                                                                            'fail': {'code': 'unknown-tool', 'message': "= 'Unknown tool \\'' + input.name + '\\' on server \\'' + input.server_id + '\\''"}}]},
                    {'call': 'mcp-tool.call-with-progress', 'input': {'server_id': '= input.server_id', 'tool': '= input.name'}, 'as': 'r'},
                    {'return': {'result': '= vars.r.value'}}]},
          {'source': f'{MC}/common/mcpGatewayToolBrokerChannel.ts:197-198', 'title': 'Invalid call', 'fail': {'code': 'invalid-call', 'message': "= 'Invalid call: ' + input.command"}},
      ])
iface('mcp-gateway-tool-broker-contribution', 'start', 'Constructor: register channel mcpGatewayToolBroker on the remote connection (browser) or the local main-process connection (electron).',
      [f'{MC}/browser/mcpGatewayToolBrokerContribution.ts:15-21', f'{MC}/electron-browser/mcpGatewayToolBrokerContribution.ts:15-21'], request=obj({}), response=obj({'registered': B}),
      behavior=[{'return': {'registered': True}}])
iface('mcp-gallery-manifest-ipc-service', 'call', "Channel mcpGalleryManifest: only 'setMcpGalleryManifest' (stores the manifest, fires change events, opens the barrier); anything else throws.",
      [f'{PM}/common/mcpGalleryManifestServiceIpc.ts:31-42', f'{PM}/common/mcpGalleryManifestServiceIpc.ts:55-60'], kind='ipc', attributes={'channel': 'mcpGalleryManifest'},
      request=obj({'command': s('setMcpGalleryManifest'), 'manifest': {'type': ['object', 'null'], 'default': {'url': 'https://api.mcp.github.com/v0'}}}, ['command']),
      response=obj({'ok': B}), errors=[err('invalid-call', 'Invalid call')],
      behavior=[{'if': "input.command != 'setMcpGalleryManifest'", 'then': [{'source': f'{PM}/common/mcpGalleryManifestServiceIpc.ts:40', 'title': 'Invalid call', 'fail': {'code': 'invalid-call', 'message': 'Invalid call'}}]},
                {'set': {'state.manifest': '= input.manifest', 'state.status': "= input.manifest == null ? 'unavailable' : 'available'"}},
                {'return': {'ok': True}}])
iface('mcp-gallery-manifest-ipc-service', 'get-mcp-gallery-manifest', 'getMcpGalleryManifest: waits for the barrier, returns the manifest or null.',
      [f'{PM}/common/mcpGalleryManifestServiceIpc.ts:45-48'], request=obj({}), response=obj({'manifest': {}, 'status': S}),
      behavior=[{'return': {'manifest': '= state.manifest', 'status': '= state.status'}}])

# --- MCP contribution starts (no decisions)
for cid in ['mcp-context-keys-controller', 'mcp-language-features', 'mcp-resource-filesystem', 'mcp-server-action-rendering', 'mcp-add-context-contribution',
            'mcp-contexts-initialisation', 'mcp-config-migration-contribution', 'mcp-servers-views-contribution']:
    c = next(x for x in components if x['id'] == cid)
    iface(cid, 'start', f'Workbench contribution constructor: {c["summary"]}', [c['sources'][0]], request=obj({}), response=obj({'ok': B}), behavior=[{'return': {'ok': True}}])

# --- MCP commands
def mcmd(cid, line, summary, srcs, behavior, request=None, response=None):
    iface('mcp-commands', cmd_slug(cid), summary, srcs + [f'{MCON}:{line}'], kind='command',
          request=request or obj({}), response=response or obj({'ok': B}), behavior=behavior)

mcmd('workbench.mcp.listServer', 81, 'List Servers: quick pick of servers; Add Server runs addConfiguration, a server runs serverOptions (agent-host sessions use agentHostServerOptions).',
     [f'{MCMD}:115-215'],
     [{'call': 'mcp-server-runtime.servers-query', 'as': 'all'},
      {'choice': 'picked', 'default': 'server', 'options': {
          'server': [{'source': f'{MCMD}:213-214', 'title': 'executeCommand(ServerOptions, id)', 'call': 'mcp-commands.cmd-workbench-mcp-serveroptions', 'input': {'server_id': 'github', 'action': 'start'}}],
          'add': [{'source': f'{MCMD}:211-212', 'title': 'executeCommand(AddConfiguration)', 'call': 'mcp-commands.cmd-workbench-mcp-addconfiguration'}],
          'agent_host_server': [{'source': f'{MCMD}:309', 'title': 'Agent host mode: AgentHostServerOptions', 'call': 'mcp-commands.cmd-workbench-mcp-agenthostserveroptions'}],
          'dismissed': [{'return': {'ok': False}}]}},
      {'return': {'ok': True}}])
mcmd('workbench.mcp.serverOptions', 82, 'Server Options: quick pick of actions for one server (start, stop, restart, output, configuration, sampling, resources).',
     [f'{MCMD}:650-800'],
     [{'call': 'mcp-server-runtime.servers-get', 'input': {'server_id': '= input.server_id'}},
      {'choice': 'action', 'default': "= input.action", 'options': {
          'start': [{'source': f'{MCMD}:758-760', 'title': "server.start({promptType: 'all-untrusted'}), then showOutput", 'call': 'mcp-server-runtime.start', 'input': {'server_id': '= input.server_id', 'prompt_type': 'all-untrusted', 'error_on_user_interaction': False, 'auto_trust_changes': False}},
                    {'call': 'mcp-server-runtime.show-output', 'input': {'server_id': '= input.server_id'}}],
          'stop': [{'source': f'{MCMD}:762-763', 'call': 'mcp-server-runtime.stop', 'input': {'server_id': '= input.server_id'}}],
          'restart': [{'source': f'{MCMD}:765-767', 'call': 'mcp-server-runtime.stop', 'input': {'server_id': '= input.server_id'}},
                      {'call': 'mcp-server-runtime.start', 'input': {'server_id': '= input.server_id', 'prompt_type': 'all-untrusted', 'error_on_user_interaction': False, 'auto_trust_changes': False}}],
          'show_output': [{'source': f'{MCMD}:777-778', 'call': 'mcp-server-runtime.show-output', 'input': {'server_id': '= input.server_id'}}],
          'config': [{'source': f'{MCMD}:780-784', 'call': 'editor-service.open-editor', 'input': {'resource': 'file:///work/app/.vscode/mcp.json'}}],
          'config_sampling': [{'source': f'{MCMD}:786-787', 'call': 'mcp-commands.cmd-workbench-mcp-configuresamplingmodels', 'input': {'server_key': 'User: GitHub', 'picked': ['copilot/gpt-4.1']}}],
          'resources': [{'source': f'{MCMD}:788-789', 'call': 'mcp-commands.cmd-workbench-mcp-browseresources'}]}},
      {'return': {'ok': True}}],
     request=obj({'server_id': SID, 'action': s('start', default='start')}))
mcmd('workbench.mcp.agentHostServerOptions', 83, 'Agent Host Server Options: actions for an MCP server configured in an agent-host session (handled by the agent host customizations).',
     [f'{MCMD}:474-520'], [{'return': {'ok': True}}])
mcmd('workbench.mcp.serverOptionsInConfirmation', 84, 'Server options from a tool confirmation or elicitation: map it to its MCP definition id, then run serverOptions.',
     [f'{MCMD}:611-645'], [{'source': f'{MCMD}:636-642', 'call': 'mcp-commands.cmd-workbench-mcp-serveroptions', 'input': {'server_id': '= input.server_id', 'action': 'show_output'}}, {'return': {'ok': True}}],
     request=obj({'server_id': SID}))
mcmd('workbench.mcp.resetTrust', 85, 'Reset Trust: mcpService.resetTrust().', [f'{MCMD}:1105-1119'],
     [{'call': 'mcp-service.reset-trust', 'as': 'r'}, {'return': {'ok': True, 'reset': '= vars.r.value.reset'}}], response=obj({'ok': B, 'reset': I}))
mcmd('workbench.mcp.resetCachedTools', 86, 'Reset Cached Tools: mcpService.resetCaches().', [f'{MCMD}:1123-1137'],
     [{'call': 'mcp-service.reset-caches'}, {'return': {'ok': True}}])
mcmd('workbench.mcp.addConfiguration', 87, 'Add Server: choose a server type and details, a destination, then install it through the workbench MCP management service.',
     [f'{MCMD}:1140-1180', f'{MC}/browser/mcpCommandsAddConfiguration.ts:534-647'],
     [{'choice': 'server_type', 'default': 'stdio', 'options': {
         'stdio': [{'set': {'vars.config': {'type': 'stdio', 'command': 'npx', 'args': ['-y', '@modelcontextprotocol/server-github']}}}],
         'http': [{'set': {'vars.config': {'type': 'http', 'url': 'https://api.githubcopilot.com/mcp/'}}}],
         'cancelled': [{'source': f'{MC}/browser/mcpCommandsAddConfiguration.ts:536-539', 'title': 'Quick pick dismissed', 'return': {'ok': False}}]}},
      {'source': f'{MC}/browser/mcpCommandsAddConfiguration.ts:647', 'call': 'workbench-mcp-management-service.install', 'input': {'name': 'github', 'config': '= vars.config', 'target': 'user'}},
      {'return': {'ok': True}}])
mcmd('workbench.mcp.startServer', 92, "Start Server: '*' starts every server; else start (all-untrusted, or wait for live tools).",
     [f'{MCMD}:1409-1436'],
     [{'if': "input.server_id == '*'", 'then': [{'call': 'mcp-server-runtime.servers-query', 'as': 'all'},
                                                {'foreach': '= vars.all.value', 'as': 'row', 'steps': [{'call': 'mcp-server-runtime.start', 'input': {'server_id': '= vars.row.id', 'prompt_type': 'all-untrusted', 'error_on_user_interaction': False, 'auto_trust_changes': False}}]},
                                                {'return': {'ok': True, 'state': 'all'}}]},
      {'call': 'mcp-server-runtime.start', 'input': {'server_id': '= input.server_id', 'prompt_type': 'all-untrusted', 'error_on_user_interaction': False, 'auto_trust_changes': '= input.auto_trust_changes'}, 'as': 'st'},
      {'return': {'ok': True, 'state': '= vars.st.value.state'}}],
     request=obj({'server_id': SID, 'auto_trust_changes': {'type': 'boolean', 'default': False}}), response=obj({'ok': B, 'state': S}))
mcmd('workbench.mcp.stopServer', 93, 'Stop Server: server.stop().', [f'{MCMD}:1439-1457'],
     [{'call': 'mcp-server-runtime.stop', 'input': {'server_id': '= input.server_id'}}, {'return': {'ok': True}}], request=obj({'server_id': SID}))
mcmd('workbench.mcp.restartServer', 95, 'Restart Server: showOutput, stop, start (all-untrusted).', [f'{MCMD}:1384-1406'],
     [{'call': 'mcp-server-runtime.show-output', 'input': {'server_id': '= input.server_id'}},
      {'call': 'mcp-server-runtime.stop', 'input': {'server_id': '= input.server_id'}},
      {'call': 'mcp-server-runtime.start', 'input': {'server_id': '= input.server_id', 'prompt_type': 'all-untrusted', 'error_on_user_interaction': False, 'auto_trust_changes': False}, 'as': 'st'},
      {'return': {'ok': True, 'state': '= vars.st.value.state'}}], request=obj({'server_id': SID}), response=obj({'ok': B, 'state': S}))
mcmd('workbench.mcp.browseResources', 104, 'Browse Resources: MCP resource quick pick.', [f'{MCMD}:1707-1724'], [{'return': {'ok': True}}])
mcmd('workbench.mcp.configureSamplingModels', 105, 'Configure Sampling Models: multi-pick of models, written to chat.mcp.serverSampling allowedModels; returns the count.',
     [f'{MCMD}:1727-1768'],
     [{'if': 'size(input.picked) == 0', 'then': [{'return': {'count': 0}}]},
      {'call': 'mcp-sampling-service.update-config', 'input': {'server_key': '= input.server_key', 'patch': {'allowedModels': '= input.picked'}}},
      {'return': {'count': '= size(input.picked)'}}],
     request=obj({'server_key': s('User: GitHub', default='User: GitHub'), 'picked': {'type': 'array', 'items': S, 'default': ['copilot/gpt-4.1']}}), response=obj({'count': I}))
mcmd('workbench.mcp.skipAutostart', 107, 'Skip Current Autostart: mcpService.cancelAutostart().', [f'{MCMD}:1803-1816'],
     [{'call': 'mcp-service.cancel-autostart'}, {'return': {'ok': True}}])
# --- sessions
SESS = s('local-agent-host/9f2c4e1a', default='local-agent-host/9f2c4e1a')
SMS = f'{SS}/services/sessions/browser/sessionsManagementService.ts'
SSV = f'{SS}/services/sessions/browser/sessionsService.ts'
BASEP = f'{SS}/contrib/providers/agentHost/browser/baseAgentHostSessionsProvider.ts'
SVA = f'{SS}/contrib/sessions/browser/views/sessionsViewActions.ts'
SA = f'{SS}/contrib/sessions/browser/sessionsActions.ts'

iface('sessions-main', 'main', 'main(configuration): SessionsMain.open: services and DOM ready, zoom, createSessionsWorkbench, startup.',
      [f'{SS}/electron-browser/sessions.main.ts:416-420', f'{SS}/electron-browser/sessions.main.ts:123-149'], request=obj({}), response=obj({'started': B}),
      behavior=[{'title': 'initServices + domContentLoaded', 'source': f'{SS}/electron-browser/sessions.main.ts:125'},
                {'call': 'sessions-workbench.startup', 'as': 'wb'}, {'return': {'started': True}}])
iface('sessions-web-main', 'main', 'Web entry: register web singletons (remote agent host clients, null SSH/WSL) and the web contributions; no local agent host provider.',
      [f'{SS}/sessions.web.main.ts:123-145'], request=obj({}), response=obj({'local_agent_host': B}),
      behavior=[{'return': {'local_agent_host': False}}])
iface('sessions-workbench', 'startup', 'startup: services, layout, start the contribution registry by phase, then restore: phase Restored and restoreVisibleSessions.',
      [f'{SS}/browser/workbench.ts:559-596', f'{SS}/browser/workbench.ts:1181-1204'], request=obj({}), response=obj({'providers': {'type': 'array'}}),
      behavior=[
          {'title': 'Workbench contributions registry start (BlockStartup/BlockRestore phases)', 'source': f'{SS}/browser/workbench.ts:595'},
          {'call': 'open-agents-window-command.register'},
          {'call': 'mcp-context-keys-controller.start'}, {'call': 'mcp-resource-filesystem.start'}, {'call': 'mcp-server-action-rendering.start'},
          {'title': 'restore(): lifecycle phase Restored, AfterRestored contributions', 'source': f'{SS}/browser/workbench.ts:1181-1195'},
          {'call': 'default-sessions-provider-contribution.start'},
          {'call': 'local-agent-host-contribution.start'},
          {'call': 'local-agent-host-service-client.register-client-channels'},
          {'call': 'mcp-discovery.start'}, {'call': 'mcp-language-model-tool-contribution.start'}, {'call': 'mcp-gateway-tool-broker-contribution.start'},
          {'call': 'mcp-contexts-initialisation.start'}, {'call': 'mcp-servers-views-contribution.start'},
          {'call': 'sessions-service.restore-visible-sessions'},
          {'title': 'Eventually phase (2.5 s idle)', 'source': f'{SS}/browser/workbench.ts:1201-1204'},
          {'call': 'mcp-language-features.start'}, {'call': 'mcp-add-context-contribution.start'}, {'call': 'mcp-config-migration-contribution.start'},
          {'call': 'sessions-providers-service.providers-query', 'as': 'p'},
          {'return': {'providers': '= vars.p.value.map(r, r.id)'}},
      ])
iface('open-agents-window-command', 'register', 'registerOpenAgentsWindowCommand(): registers workbench.action.openAgentsWindow.', [f'{SS}/sessions.desktop.main.ts:26'],
      request=obj({}), response=obj({'ok': B}), behavior=[{'return': {'ok': True}}])
iface('open-agents-window-command', cmd_slug('workbench.action.openAgentsWindow'), 'openAgentsWindow: INativeHostService.openAgentsWindow({source: CommandPalette by default}).',
      [f'{SS}/contrib/openAgentsWindow/electron-browser/openAgentsWindowCommand.ts:13-18'], kind='command', request=obj({'source': s('commandPalette', default='commandPalette')}), response=obj({'ok': B}),
      behavior=[{'call': 'native-host-main-service.open-agents-window', 'input': {'source': '= input.source'}}, {'return': {'ok': True}}])

iface('sessions-providers-service', 'register-provider', "registerProvider: refuse a duplicate id ('Sessions provider <id> is already registered.'), fire onDidChangeProviders.",
      [f'{SS}/services/sessions/browser/sessionsProvidersService.ts:59-73'], request=obj({'id': s('local-agent-host'), 'order': I, 'session_types': {'type': 'array'}}, ['id']),
      errors=[err('sessions-provider-already-registered', "Sessions provider '<id>' is already registered.")],
      store={'table': 'providers', 'op': 'put', 'key': '= input.id', 'value': '= input', 'where': 'row == null', 'conflict': 'sessions-provider-already-registered'})
iface('sessions-providers-service', 'unregister-provider', 'Disposing the registration removes the provider.', [f'{SS}/services/sessions/browser/sessionsProvidersService.ts:66-71'],
      request=obj({'id': s('local-agent-host')}, ['id']), store={'table': 'providers', 'op': 'delete', 'key': '= input.id'})
iface('sessions-providers-service', 'get-provider', 'getProvider (null when unknown).', [f'{SS}/services/sessions/browser/sessionsProvidersService.ts:118-122'],
      request=obj({'id': s('local-agent-host')}, ['id']), store={'table': 'providers', 'op': 'get', 'key': '= input.id', 'default': {'missing': True}})
iface('sessions-providers-service', 'providers-query', 'getProviders.', [f'{SS}/services/sessions/browser/sessionsProvidersService.ts:106-116'],
      request=obj({}), store={'table': 'providers', 'op': 'query'})

iface('local-agent-host-contribution', 'start', 'autorun on agent host enablement: enabled registers the local-agent-host provider, disabled clears the registration.',
      [f'{SS}/contrib/providers/agentHost/browser/localAgentHost.contribution.ts:46-86'], request=obj({}), response=obj({'registered': B}),
      behavior=[{'call': 'browser-agent-host-enablement-service.is-enabled', 'as': 'en'},
                {'if': '!vars.en.value.enabled', 'then': [{'source': f'{SS}/contrib/providers/agentHost/browser/localAgentHost.contribution.ts:80-86', 'title': 'Agent host disabled: no local provider',
                                                          'call': 'sessions-providers-service.unregister-provider', 'input': {'id': 'local-agent-host'}}, {'return': {'registered': False}}]},
                {'source': f'{SS}/contrib/providers/agentHost/browser/localAgentHost.contribution.ts:46-60', 'title': 'Create LocalAgentHostSessionsProvider and register it',
                 'call': 'sessions-providers-service.register-provider', 'input': {'id': 'local-agent-host', 'order': 0, 'session_types': ['copilotcli']}},
                {'return': {'registered': True}}])
iface('default-sessions-provider-contribution', 'start', "Register the 'default' Copilot cloud provider.", [f'{SS}/contrib/providers/copilotChatSessions/browser/copilotChatSessions.contribution.ts:35-36'],
      request=obj({}), response=obj({'registered': B}),
      behavior=[{'call': 'sessions-providers-service.register-provider', 'input': {'id': 'default', 'order': 10, 'session_types': ['copilot-cloud']}}, {'return': {'registered': True}}])
iface('local-agent-host-lifecycle-contribution', 'on-before-shutdown', 'shouldVetoShutdown: only on quit with an active local session; veto unless the user confirms.',
      [f'{SS}/contrib/providers/agentHost/electron-browser/localAgentHostLifecycle.contribution.ts:43-68'], kind='event', subscribe=['lifecycle-service.on-before-shutdown'],
      request=obj({'reason': s('quit', default='quit')}), response=obj({'veto': B}),
      behavior=[{'if': "input.reason != 'quit' || !state.active_session_working", 'then': [{'source': f'{SS}/contrib/providers/agentHost/electron-browser/localAgentHostLifecycle.contribution.ts:52-60', 'title': 'Not quitting or nothing running: no veto', 'return': {'veto': False}}]},
                {'title': 'confirmSessionShutdown', 'source': f'{SS}/contrib/providers/agentHost/electron-browser/localAgentHostLifecycle.contribution.ts:61-68',
                 'choice': 'confirm_quit', 'default': 'quit', 'options': {'quit': [{'return': {'veto': False}}], 'cancel': [{'return': {'veto': True}}]}}])

iface('sessions-management-service', 'create-new-session', '_resolveProviderForNewSession then provider.createNewSession; the previous draft is deleted.',
      [f'{SMS}:479-564'], request=obj({'folder_uri': s('file:///work/app'), 'provider_id': s('local-agent-host', default='local-agent-host')}),
      response=obj({'session_id': S, 'provider_id': S}), errors=[err('sessions-provider-not-found', "Sessions provider '<id>' not found")],
      behavior=[{'call': 'sessions-providers-service.get-provider', 'input': {'id': '= input.provider_id'}, 'as': 'p'},
                {'if': 'has(vars.p.value.missing)', 'then': [{'source': f'{SMS}:501-504', 'title': 'Unknown provider', 'fail': {'code': 'sessions-provider-not-found', 'message': "= 'Sessions provider \\'' + input.provider_id + '\\' not found'"}}]},
                {'call': "= input.provider_id == 'default' ? 'copilot-chat-sessions-provider.create-new-session' : 'local-agent-host-sessions-provider.create-new-session'",
                 'targets': ['copilot-chat-sessions-provider.create-new-session', 'local-agent-host-sessions-provider.create-new-session'], 'input': {'folder_uri': '= input.folder_uri'}, 'as': 'ns'},
                {'set': {'state.new_session': '= vars.ns.value.session_id'}},
                {'return': {'session_id': '= vars.ns.value.session_id', 'provider_id': '= input.provider_id'}}])
iface('sessions-management-service', 'send-new-chat-request', 'sendNewChatRequest (foreground): prepare the draft, clear _newSession, provider.sendRequest, fire onDidStartSession.',
      [f'{SMS}:818-880'], request=obj({'session_id': SESS, 'provider_id': s('local-agent-host', default='local-agent-host'), 'query': s('Add a unit test for add()')}),
      response=obj({'session_id': S}), errors=[err('sessions-provider-not-found', "Sessions provider '<id>' not found")],
      behavior=[{'call': 'sessions-providers-service.get-provider', 'input': {'id': '= input.provider_id'}, 'as': 'p'},
                {'if': 'has(vars.p.value.missing)', 'then': [{'source': f'{SMS}:821', 'title': 'Unknown provider', 'fail': {'code': 'sessions-provider-not-found', 'message': "= 'Sessions provider \\'' + input.provider_id + '\\' not found'"}}]},
                {'set': {'state.new_session': ''}},
                {'call': 'local-agent-host-sessions-provider.send-request', 'input': {'session_id': '= input.session_id', 'query': '= input.query'}, 'as': 'r'},
                {'return': {'session_id': '= vars.r.value.session_id'}}])
for op, line, summ in [('rename-session', f'{SMS}:1509-1512', 'renameSession: provider.renameSession then onDidRenameSession; an unknown provider is a silent no-op.'),
                       ('delete-sessions', f'{SMS}:1450-1481', 'deleteSessions: group by provider (unknown providers skipped), provider.deleteSessions, fire onDidDeleteSession.'),
                       ('archive-session', f'{SMS}:1299-1309', 'archiveSession: cancel active chats, provider.archiveSession, fire onDidArchiveSession.')]:
    target = {'rename-session': 'rename-session', 'delete-sessions': 'delete-sessions', 'archive-session': 'archive-session'}[op]
    iface('sessions-management-service', op, summ, [line],
          request=obj({'session_id': SESS, 'provider_id': s('local-agent-host', default='local-agent-host'), 'title': s('Fix add() tests', default='Fix add() tests')}, ['session_id']),
          response=obj({'done': B}),
          behavior=[{'call': 'sessions-providers-service.get-provider', 'input': {'id': '= input.provider_id'}, 'as': 'p'},
                    {'if': 'has(vars.p.value.missing)', 'then': [{'title': 'Unknown provider: optional chaining makes it a no-op', 'source': line, 'return': {'done': False}}]},
                    {'call': f'local-agent-host-sessions-provider.{target}', 'input': {'session_id': '= input.session_id', 'title': '= input.title'}},
                    {'return': {'done': True}}])
iface('sessions-management-service', 'get-sessions', 'getSessions: provider sessions merged with in-flight ones.', [f'{SMS}:244-255'],
      request=obj({}), response=obj({'sessions': {'type': 'array'}}),
      behavior=[{'call': 'local-agent-host-sessions-provider.get-sessions', 'as': 'l'}, {'return': {'sessions': '= vars.l.value.sessions'}}])

iface('local-agent-host-sessions-provider', 'cache-get', 'Session cache entry.', [f'{BASEP}:4885-4890'], request=obj({'session_id': SESS}),
      store={'table': 'session_cache', 'op': 'get', 'key': '= input.session_id', 'default': {'missing': True}})
iface('local-agent-host-sessions-provider', 'cache-put', 'Add a session to the cache.', [f'{BASEP}:7935-7942'], request=obj({'session_id': SESS, 'value': {'type': 'object'}}),
      store={'table': 'session_cache', 'op': 'put', 'key': '= input.session_id', 'value': '= input.value'})
iface('local-agent-host-sessions-provider', 'cache-update', 'Update a cached session.', [f'{BASEP}:7463-7470'], request=obj({'session_id': SESS, 'patch': {'type': 'object'}}),
      store={'table': 'session_cache', 'op': 'update', 'key': '= input.session_id', 'value': '= input.patch'})
iface('local-agent-host-sessions-provider', 'cache-delete', '_removeCachedSession.', [f'{BASEP}:7391-7420'], request=obj({'session_id': SESS}),
      store={'table': 'session_cache', 'op': 'delete', 'key': '= input.session_id'})
iface('local-agent-host-sessions-provider', 'get-sessions', 'getSessions: the cached sessions.', [f'{BASEP}:4203'], request=obj({}), response=obj({'sessions': {'type': 'array'}}),
      behavior=[{'call': 'local-agent-host-sessions-provider.cache-query', 'as': 'q'}, {'return': {'sessions': '= vars.q.value'}}])
iface('local-agent-host-sessions-provider', 'cache-query', 'All cached sessions.', [f'{BASEP}:4203'], request=obj({}), store={'table': 'session_cache', 'op': 'query'})
iface('local-agent-host-sessions-provider', 'create-new-session', 'createNewSession: a new untitled draft for the folder.', [f'{BASEP}:5299-5310'],
      request=obj({'folder_uri': s('file:///work/app')}), response=obj({'session_id': S}),
      behavior=[{'set': {'state.new_session': 'local-agent-host/9f2c4e1a'}}, {'return': {'session_id': '= state.new_session'}}])
iface('local-agent-host-sessions-provider', 'send-request', 'sendRequest: send the first request of the draft through the chat service (agent host session), cache the session.',
      [f'{BASEP}:7935-7942', f'{BASEP}:7998-8006'], request=obj({'session_id': SESS, 'query': S}), response=obj({'session_id': S}),
      errors=[err('session-not-found', "Session '<id>' not found")],
      behavior=[{'if': 'input.session_id != state.new_session',
                 'then': [{'call': 'local-agent-host-sessions-provider.cache-get', 'input': {'session_id': '= input.session_id'}, 'as': 'c'},
                          {'if': 'has(vars.c.value.missing)', 'then': [{'source': f'{BASEP}:7947-7950', 'title': 'Unknown committed chat', 'fail': {'code': 'session-not-found', 'message': "= 'Session \\'' + input.session_id + '\\' not found'"}}]}]},
                {'call': 'chat-service.send-request', 'input': {'resource': "= 'vscode-chat-session://' + input.session_id", 'query': '= input.query'}},
                {'call': 'local-agent-host-sessions-provider.cache-put', 'input': {'session_id': '= input.session_id', 'value': {'session_id': '= input.session_id', 'title': '', 'archived': False, 'backend_uri': "= 'copilot:/' + input.session_id.split('/')[1]"}}},
                {'set': {'state.new_session': ''}},
                {'return': {'session_id': '= input.session_id'}}])
iface('local-agent-host-sessions-provider', 'rename-session', 'renameSession: set the user title locally and dispatch SessionTitleChanged to the agent host.',
      [f'{BASEP}:7463-7475'], request=obj({'session_id': SESS, 'title': S}), response=obj({'renamed': B}),
      behavior=[{'call': 'local-agent-host-sessions-provider.cache-get', 'input': {'session_id': '= input.session_id'}, 'as': 'c'},
                {'if': 'has(vars.c.value.missing) || !state.connected', 'then': [{'title': 'Not cached or no connection: nothing happens', 'source': f'{BASEP}:7468', 'return': {'renamed': False}}]},
                {'call': 'local-agent-host-sessions-provider.cache-update', 'input': {'session_id': '= input.session_id', 'patch': {'title': '= input.title'}}},
                {'title': 'connection.dispatch(SessionTitleChanged)', 'source': f'{BASEP}:7471-7473',
                 'call': 'protocol-server-handler.dispatch-action', 'input': {'session': '= vars.c.value.backend_uri', 'action': {'type': 'session-title-changed', 'title': '= input.title'}, 'client_id': 'w1-client'}},
                {'return': {'renamed': True}}])
iface('local-agent-host-sessions-provider', 'archive-session', '_setSessionArchived: mark archived locally and dispatch SessionIsArchivedChanged.',
      [f'{BASEP}:7030-7032', f'{BASEP}:7248-7258'], request=obj({'session_id': SESS}), response=obj({'archived': B}),
      behavior=[{'call': 'local-agent-host-sessions-provider.cache-get', 'input': {'session_id': '= input.session_id'}, 'as': 'c'},
                {'if': 'has(vars.c.value.missing) || !state.connected', 'then': [{'return': {'archived': False}}]},
                {'call': 'local-agent-host-sessions-provider.cache-update', 'input': {'session_id': '= input.session_id', 'patch': {'archived': True}}},
                {'call': 'protocol-server-handler.dispatch-action', 'input': {'session': '= vars.c.value.backend_uri', 'action': {'type': 'session-is-archived-changed', 'is_archived': True}, 'client_id': 'w1-client'}},
                {'return': {'archived': True}}])
iface('local-agent-host-sessions-provider', 'delete-sessions', 'deleteSessions: for each cached session, connection.disposeSession then remove from the cache.',
      [f'{BASEP}:7391-7420'], request=obj({'session_id': SESS}), response=obj({'deleted': I}),
      behavior=[{'if': '!state.connected', 'then': [{'return': {'deleted': 0}}]},
                {'call': 'local-agent-host-sessions-provider.cache-get', 'input': {'session_id': '= input.session_id'}, 'as': 'c'},
                {'if': 'has(vars.c.value.missing)', 'then': [{'return': {'deleted': 0}}]},
                {'call': 'protocol-server-handler.dispose-session', 'input': {'session': '= vars.c.value.backend_uri'}},
                {'call': 'local-agent-host-sessions-provider.cache-delete', 'input': {'session_id': '= input.session_id'}},
                {'return': {'deleted': 1}}])
iface('copilot-chat-sessions-provider', 'create-new-session', 'createNewSession for a Copilot cloud session draft.', [f'{SS}/contrib/providers/copilotChatSessions/browser/copilotChatSessions.contribution.ts:35'],
      request=obj({'folder_uri': S}), response=obj({'session_id': S}), behavior=[{'return': {'session_id': 'default/cloud-1'}}])

iface('sessions-service', 'open-new-session', 'openNewSession: resolve the workspace (trust request when needed), createNewSession, activate it.',
      [f'{SSV}:1619-1665'], request=obj({'folder_uri': s('file:///work/app', default='file:///work/app'), 'provider_id': s('local-agent-host', default='local-agent-host')}),
      response=obj({'session_id': S}),
      behavior=[{'call': 'sessions-management-service.create-new-session', 'input': {'folder_uri': '= input.folder_uri', 'provider_id': '= input.provider_id'}, 'as': 'ns'},
                {'set': {'state.active': '= vars.ns.value.session_id', 'state.visible': '= state.visible + [vars.ns.value.session_id]'}},
                {'return': {'session_id': '= vars.ns.value.session_id'}}])
iface('sessions-service', 'close-all-sessions', 'closeAllSessions: no-op without grid sessions; else discard the draft and remove all.', [f'{SSV}:1887-1903'],
      request=obj({}), response=obj({'closed': I}),
      behavior=[{'if': 'size(state.visible) == 0', 'then': [{'return': {'closed': 0}}]},
                {'set': {'vars.n': '= size(state.visible)'}}, {'set': {'state.visible': [], 'state.active': ''}}, {'return': {'closed': '= vars.n'}}])
iface('sessions-service', 'restore-visible-sessions', 'restoreVisibleSessions: reload the persisted grid of visible sessions.', [f'{SSV}:2162-2175'],
      request=obj({}), response=obj({'restored': I}), behavior=[{'return': {'restored': '= size(state.visible)'}}])

iface('sessions-list-model-service', 'pin-session', 'pinSession: add the id, save sessionsListControl.pinnedSessions (profile storage), fire Pinned.',
      [f'{SS}/services/sessions/browser/sessionsListModelService.ts:173-180'], request=obj({'session_id': SESS}), response=obj({'changed': B}),
      behavior=[{'if': 'input.session_id in state.pinned', 'then': [{'return': {'changed': False}}]},
                {'set': {'state.pinned': '= state.pinned + [input.session_id]'}}, {'return': {'changed': True}}])
iface('sessions-list-model-service', 'unpin-session', 'unpinSession.', [f'{SS}/services/sessions/browser/sessionsListModelService.ts:182-189'],
      request=obj({'session_id': SESS}), response=obj({'changed': B}),
      behavior=[{'if': '!(input.session_id in state.pinned)', 'then': [{'return': {'changed': False}}]},
                {'set': {'state.pinned': '= state.pinned.filter(x, x != input.session_id)'}}, {'return': {'changed': True}}])
iface('sessions-list-model-service', 'is-pinned', 'isPinned read path used by the list.', [f'{SS}/services/sessions/browser/sessionsListModelService.ts:106'],
      request=obj({'session_id': SESS}), response=obj({'pinned': B}), behavior=[{'return': {'pinned': '= input.session_id in state.pinned'}}])

def scmd(comp_id, cid, srcs, summary, behavior, request=None, response=None):
    iface(comp_id, cmd_slug(cid), summary, srcs, kind='command', request=request or obj({'session_id': SESS}), response=response or obj({'ok': B}), behavior=behavior)

scmd('sessions-view-actions', 'sessionsViewPane.renameSession', [f'{SVA}:1518-1574'], 'Rename session: inline or quick input (empty refused), renameSession only when the title changed.',
     [{'if': "input.title.trim() == ''", 'then': [{'title': "Validation 'Title cannot be empty'", 'source': f'{SVA}:1560-1565', 'return': {'ok': False}}]},
      {'call': 'sessions-management-service.rename-session', 'input': {'session_id': '= input.session_id', 'provider_id': 'local-agent-host', 'title': '= input.title.trim()'}}, {'return': {'ok': True}}],
     request=obj({'session_id': SESS, 'title': s('Fix add() tests', default='Fix add() tests')}))
scmd('sessions-view-actions', 'sessionsViewPane.deleteSession', [f'{SVA}:1577-1620'], "Delete session: confirm 'Are you sure you want to delete this session?', then deleteSessions.",
     [{'choice': 'confirm', 'default': 'delete', 'options': {'delete': [], 'cancel': [{'return': {'ok': False}}]}},
      {'call': 'sessions-management-service.delete-sessions', 'input': {'session_id': '= input.session_id', 'provider_id': 'local-agent-host'}}, {'return': {'ok': True}}])
scmd('sessions-view-actions', 'sessionsViewPane.archiveSessionsWithUndo', [f'{SVA}:68-133'], 'Archive (mark done) with undo: archiveSession for each not-yet-archived session.',
     [{'call': 'sessions-management-service.archive-session', 'input': {'session_id': '= input.session_id', 'provider_id': 'local-agent-host'}}, {'return': {'ok': True}}])
scmd('sessions-view-actions', 'sessionsViewPane.pinSession', [f'{SVA}:1089-1125'], 'Pin session: SessionsListModelService.pinSession.',
     [{'call': 'sessions-list-model-service.pin-session', 'input': {'session_id': '= input.session_id'}}, {'return': {'ok': True}}])
scmd('sessions-view-actions', 'sessionsViewPane.unpinSession', [f'{SVA}:1128-1164'], 'Unpin session.',
     [{'call': 'sessions-list-model-service.unpin-session', 'input': {'session_id': '= input.session_id'}}, {'return': {'ok': True}}])
scmd('sessions-actions', 'sessions.sessionHeader.rename', [f'{SA}:1928', f'{SA}:1953-1965'], 'Rename from the session header: inline title editing, else run sessionsViewPane.renameSession.',
     [{'call': 'sessions-view-actions.cmd-sessionsviewpane-renamesession', 'input': {'session_id': '= input.session_id', 'title': '= input.title'}}, {'return': {'ok': True}}],
     request=obj({'session_id': SESS, 'title': s('Fix add() tests', default='Fix add() tests')}))
scmd('sessions-actions', 'sessions.closeAllSessions', [f'{SA}:567-588'], 'Close All Sessions (Ctrl+K Ctrl+W): ISessionsService.closeAllSessions().',
     [{'call': 'sessions-service.close-all-sessions', 'as': 'c'}, {'return': {'ok': True, 'closed': '= vars.c.value.closed'}}], request=obj({}), response=obj({'ok': B, 'closed': I}))
scmd('sessions-chat-actions', 'NewChatInSessionsWindowAction', [f'{SS}/contrib/chat/browser/chat.contribution.ts:177', f'{SS}/contrib/chat/browser/newSessionAction.ts:64-142'],
     'New Session (workbench.action.sessions.newChat, Ctrl/Cmd+N): openNewSession for the folder.',
     [{'call': 'sessions-service.open-new-session', 'input': {'folder_uri': 'file:///work/app', 'provider_id': '= input.provider_id'}, 'as': 'n'}, {'return': {'ok': True, 'session_id': '= vars.n.value.session_id'}}],
     request=obj({'provider_id': s('local-agent-host', default='local-agent-host')}), response=obj({'ok': B, 'session_id': S}))
scmd('sessions-chat-actions', 'workbench.action.chat.branchChatSession', [f'{SS}/contrib/chat/browser/chat.contribution.ts:644', f'{SS}/contrib/chat/browser/branchChatSessionAction.ts:58-109'],
     "Branch Chat: hidden menu item; run always throws 'Branching chat sessions is not yet supported.'",
     [{'source': f'{SS}/contrib/chat/browser/branchChatSessionAction.ts:108', 'title': 'Always throws', 'fail': {'code': 'branching-not-supported', 'message': 'Branching chat sessions is not yet supported.'}}],
     request=obj({}))

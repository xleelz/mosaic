extra = {
 'agents-ahp-authenticate-revoke': ["!('https://api.anthropic.com' in state['agent-host-authentication-service'].tokens)"],
 'agents-ahp-dispatch-automation-with-credentials': ["state['agent-host-state-manager'].server_seq == 1"],
 'agents-ahp-initialize-legacy-version': ["state['protocol-server-handler'].clients['w1-client'].protocol_version == '0.10.0'"],
 'agents-ahp-initialize-then-create-session': ["state['agent-host-database'].sessions_v2['copilot:/9f2c4e1a'].provider == 'copilot'"],
 'agents-mcp-autostart-error-swallowed': ["state['mcp-server-runtime@w1'].servers['github'].state == 'error'"],
 'agents-mcp-autostart-outdated': ["state['mcp-server-runtime@w1'].servers['github'].cache_state == 'live'"],
 'agents-mcp-gallery-manifest-set-then-get': ["state['mcp-gallery-manifest-ipc-service@w1'].status == 'available'"],
 'agents-mcp-gateway-call-tool': [tr('mcp-server.tools-call')],
 'agents-mcp-gateway-list-tools': ["state['mcp-server-runtime@w1'].servers['github'].state == 'running'"],
 'agents-mcp-reset-cached-tools-then-read': ["state['mcp-server-runtime@w1'].servers['workspace-db'].cache_state == 'unknown'"],
 'agents-mcp-tool-invoke-server-fails': ["state['mcp-server-runtime@w1'].servers['github'].state == 'error'", ntr('mcp-server.tools-call')],
 'agents-mcp-tool-invoke-server-untrusted': ["state['mcp-server-runtime@w1'].servers['workspace-db'].trusted_at_nonce == '__vscode_not_trusted'"],
 'agents-mcp-tool-prepare-confirm': ["state['mcp-server-runtime@w1'].servers['github'].state == 'running'"],
 'agents-mcp-tool-prepare-open-world': [tr('mcp-server-runtime.call-on')],
 'agents-mcp-tool-prepare-read-only': [tr('mcp-server-runtime.call-on')],
 'agents-mcp-tool-prepare-sandboxed': ["state['mcp-server-runtime@w1'].servers['github'].state == 'running'"],
 'agents-sessions-close-all-then-restore': ["state['sessions-service@w1'].active == ''"],
 'agents-sessions-pin-then-read': ["state['sessions-list-model-service@w1'].pinned == ['local-agent-host/9f2c4e1a']"],
 'agents-sessions-rename-then-read': ["state['local-agent-host-sessions-provider@w1'].session_cache['local-agent-host/9f2c4e1a'].title == 'Fix add() tests'"],
 'agents-sessions-send-unknown-session': ["state['sessions-management-service@w1'].new_session == ''"],
 'agents-sessions-unpin-then-read': ["state['sessions-list-model-service@w1'].pinned == []"],
}
for sc in scenarios:
    if sc['id'] in extra:
        sc['expect'] = sc['expect'] + extra[sc['id']]
# write-then-read for remaining writes flows
scen('agents-mcp-sampling-then-read-config', None,
     ["steps.sample.result.ok", "steps.read.result.ok", "steps.read.result.value.model == 'copilot/gpt-4o-mini'",
      f"state['mcp-sampling-service@w1'].server_sampling['User: GitHub'].allowedDuringChat == true"],
     choices={'mcp-sampling-service.get-matching-model.allow_prompt': 'always'},
     steps=[{'flow': 'agents-mcp-sampling', 'as': 'sample'}, {'flow': 'agents-mcp-sampling', 'as': 'read', 'input': {'model_hints': ['mini']}}])
scen('agents-mcp-server-options-stop-then-read', None, ["steps.read.result.value.state == 'stopped'", tr('mcp-server-runtime.stop')],
     choices={'mcp-commands.cmd-workbench-mcp-serveroptions.action': 'stop'}, state={'mcp-server-runtime@w1': {'servers': {'github': {'state': 'running'}}}},
     steps=[{'flow': 'agents-mcp-server-options', 'as': 'opt'}, {'flow': 'agents-mcp-server-get', 'as': 'read', 'input': {'server_id': 'github'}}])
scen('agents-sessions-window-startup-then-new-session', None,
     ["steps.start.result.ok", "steps.new.result.value.session_id == 'local-agent-host/9f2c4e1a'", "state['sessions-service@w1'].active == 'local-agent-host/9f2c4e1a'"],
     steps=[{'flow': 'agents-sessions-window-startup', 'as': 'start'}, {'flow': 'agents-sessions-new-session', 'as': 'new'}])
flow('agents-agent-host-connection-count', 'agent-host-connection-tracker.get-socket', 'local-agent-host-service-client', 'Read the on-demand WebSocket server socket', [f'{AHM}:392-393'])
iface('agent-host-connection-tracker', 'get-socket', 'The memoized dynamic socket info (empty until started).', [f'{AHM}:392-393'], kind='ipc', request=obj({}), response=obj({'socket': S}),
      behavior=[{'return': {'socket': '= state.socket'}}])
scen('agents-agent-host-websocket-then-read', None, ["steps.read.result.value.socket == '/tmp/vscode-agent-host-7c1e.sock'", "state['agent-host-connection-tracker'].socket != ''"],
     steps=[{'flow': 'agents-agent-host-websocket', 'as': 'ws'}, {'flow': 'agents-agent-host-connection-count', 'as': 'read'}])
# branch coverage extras
scen('agents-agent-host-server-startup-two-token-sources', None, ["!result.ok", "result.error.message == 'Error: --connection-token cannot be used with --connection-token-file'"],
     steps=[{'interface': 'agent-host-server-main.parse-server-options', 'caller': 'agent-host-server-main', 'input': {'connection_token': 'abc', 'connection_token_file': '/tmp/tok'}}], flow='agents-agent-host-server-startup')
scen('agents-ahp-create-session-many-working-dirs', None, ["result.ok", "state['agent-host-state-manager'].sessions['copilot:/9f2c4e1a'].provider == 'copilot'"],
     steps=[{'interface': 'agent-service.create-session', 'caller': 'protocol-server-handler', 'input': {'session': 'copilot:/9f2c4e1a', 'working_directories': ['file:///work/app', 'file:///work/lib']}}], flow='agents-ahp-create-session')
scen('agents-mcp-autostart-previously-refused', 'agents-mcp-autostart',
     ["result.value.started == ['github']", "result.value.requiring_interaction == []", "state['mcp-server-runtime@w1'].servers['workspace-db'].state == 'stopped'",
      "!trace.exists(e, e.type == 'choice' && e.key == 'mcp-registry.resolve-connection.trust_prompt')"],
     state={'mcp-server-runtime@w1': {'servers': {WS_SERVER: {'trusted_at_nonce': '__vscode_not_trusted'}}}})
scen('agents-sessions-archive-unknown-provider', None, ["result.ok", "!result.value.done", ntr('local-agent-host-sessions-provider.archive-session')],
     steps=[{'interface': 'sessions-management-service.archive-session', 'caller': 'sessions-view-actions', 'input': {'session_id': 'local-agent-host/9f2c4e1a'}}], flow='agents-sessions-archive')
scen('agents-sessions-delete-unknown-provider', None, ["result.ok", "!result.value.done", ntr('local-agent-host-sessions-provider.delete-sessions')],
     steps=[{'interface': 'sessions-management-service.delete-sessions', 'caller': 'sessions-view-actions', 'input': {'session_id': 'local-agent-host/9f2c4e1a'}}], flow='agents-sessions-delete')
scen('agents-ahp-dispatch-claude-turn-and-cancel', None, [tr('claude-agent.send-message'), tr('claude-agent.abort'), "state['agent-host-state-manager'].sessions['claude:/77aa'].active_turn == ''"],
     state={'agent-host-provider-service': {'providers': ['copilot', 'claude']}, 'agent-host-state-manager': {'sessions': {'claude:/77aa': dict(SEED_SESSION, session='claude:/77aa', provider='claude')}}},
     steps=[{'flow': 'agents-ahp-dispatch-action', 'as': 'start', 'input': {'session': 'claude:/77aa', 'action': {'type': 'chat-turn-started', 'turn_id': 't1', 'text': 'hi'}}},
            {'flow': 'agents-ahp-dispatch-action', 'as': 'cancel', 'input': {'session': 'claude:/77aa', 'action': {'type': 'chat-turn-cancelled', 'turn_id': 't1'}}}])
scen('agents-mcp-configure-sampling-none-picked', None, ["result.value.count == 0", "!('User: GitHub' in state['mcp-sampling-service@w1'].server_sampling)"],
     steps=[{'interface': 'mcp-commands.cmd-workbench-mcp-configuresamplingmodels', 'caller': 'user', 'input': {'server_key': 'User: GitHub', 'picked': []}}], flow='agents-mcp-server-options')
extra2 = {
 'agents-agent-host-crash-recovery-gives-up': ["state['agent-host-process-manager'].restart_limit_reached"],
 'agents-agent-host-crash-recovery-restarts': ["state['agent-host-process-manager'].running"],
 'agents-agent-host-server-startup-default-port': ["state['agent-host-provider-service'].providers == ['copilot']"],
 'agents-agent-host-server-startup-port-arg': ["state['agent-host-provider-service'].providers == ['copilot']"],
 'agents-agent-host-shutdown-then-websocket-refused': ["state['agent-host-management-service'].shutting_down", "state['agent-host-connection-tracker'].socket == ''"],
 'agents-agent-host-startup-claude': ["state['agent-host-provider-service'].providers == ['copilot', 'claude']"],
 'agents-agent-host-startup-claude-disabled': ["state['agent-host-provider-service'].providers == ['copilot']"],
 'agents-agent-host-startup-codex-root-config': ["state['agent-host-provider-service'].providers == ['copilot', 'codex']"],
 'agents-agent-host-startup-configured-port': ["state['agent-host-worktree-cleanup-service'].passes == 2"],
 'agents-agent-host-startup-websocket-fails': ["state['agent-host-worktree-cleanup-service'].passes == 2"],
}
for sc in scenarios:
    if sc['id'] in extra2:
        sc['expect'] = sc['expect'] + extra2[sc['id']]
iface('mcp-sampling-service', 'get-config', 'getConfig: the effective chat.mcp.serverSampling entry of a server (config merged with the values this run wrote).',
      [f'{MC}/common/mcpSamplingService.ts:293-310'], request=obj({'server_key': s('User: GitHub', default='User: GitHub')}), response=obj({'config': {'type': 'object'}}),
      behavior=[{'return': {'config': "= merge(input.server_key in config['chat-mcp-server-sampling'] ? config['chat-mcp-server-sampling'][input.server_key] : {}, input.server_key in state.server_sampling ? state.server_sampling[input.server_key] : {})"}}])
flow('agents-mcp-sampling-config', 'mcp-sampling-service.get-config', 'mcp-commands', 'Read the MCP sampling configuration of a server', [f'{MC}/common/mcpSamplingService.ts:293-310'])
scen('agents-mcp-sampling-always-then-config', None, ["steps.sample.result.ok", "steps.read.result.value.config.allowedDuringChat == true",
     "state['mcp-sampling-service@w1'].server_sampling['User: GitHub'].allowedDuringChat == true"],
     choices={'mcp-sampling-service.get-matching-model.allow_prompt': 'always'},
     steps=[{'flow': 'agents-mcp-sampling', 'as': 'sample'}, {'flow': 'agents-mcp-sampling-config', 'as': 'read'}])

# part 2: MCP and sessions components

MCP_SERVERS_INITIAL = {
    'github': {'id': 'github', 'label': 'GitHub', 'collection': 'mcp.config.usrlocal', 'collection_label': 'User',
               'scope': 'user', 'trust_behavior': 'trusted', 'cache_nonce': 'n1', 'trusted_at_nonce': '',
               'state': 'stopped', 'enabled': True, 'cache_state': 'unknown', 'transport': 'ok',
               'sandbox_enabled': False, 'tools': ['search_issues', 'create_issue']},
    'workspace-db': {'id': 'workspace-db', 'label': 'Workspace DB', 'collection': 'workspace.dotmcp', 'collection_label': 'Workspace',
                     'scope': 'workspace', 'trust_behavior': 'trusted-on-nonce', 'cache_nonce': 'n7', 'trusted_at_nonce': '',
                     'state': 'stopped', 'enabled': True, 'cache_state': 'unknown', 'transport': 'ok',
                     'sandbox_enabled': False, 'tools': ['query']},
}

comp('mcp-service', 'McpService', 'agents',
     'Owns the McpServer instances built from the registry collections; autostart, reset of caches and trust.',
     [f'{MC}/common/mcpTypes.ts:438', f'{MC}/common/mcpService.ts:28', f'{MC}/browser/mcp.contribution.ts:59'],
     state={'schema': obj({'autostart_running': B}), 'initial': {'autostart_running': False}})
comp('mcp-server-runtime', 'McpServer', 'agents',
     'One MCP server: connection state machine (Stopped/Starting/Running/Error), trust nonce and cached tools; rows keyed by definition id.',
     [f'{MC}/common/mcpServer.ts:345', f'{MC}/common/mcpTypes.ts:913-918'],
     state={'schema': obj({'servers': {'type': 'object'}}), 'initial': {'servers': MCP_SERVERS_INITIAL}})
comp('mcp-server-connection', 'McpServerConnection', 'agents',
     'Starts the transport (stdio process or HTTP) and runs the initialize handshake through McpServerRequestHandler.',
     [f'{MC}/common/mcpServerConnection.ts:20-149', f'{MC}/common/mcpServerRequestHandler.ts:102-155'])
comp('mcp-registry', 'McpRegistry', 'agents',
     'Collections and delegates; decides trust and resolves a server definition into a connection.',
     [f'{MC}/common/mcpRegistryTypes.ts:20', f'{MC}/common/mcpRegistry.ts:225-319', f'{MC}/common/mcpRegistry.ts:504-592', f'{MC}/browser/mcp.contribution.ts:56'],
     state={'schema': obj({'saved_inputs': {'type': 'object'}}), 'initial': {'saved_inputs': {}}})
comp('allowed-mcp-servers-service', 'AllowedMcpServersService', 'agents',
     'Enterprise policy gate: chat.mcp.access none, deny list and allow list.',
     [f'{PM}/common/mcpManagement.ts:295', f'{PM}/common/allowedMcpServersService.ts:21', f'{PM}/common/allowedMcpServersService.ts:97-129'],
     state={'schema': obj({'allowlist': {'type': ['array', 'null']}, 'denylist': {'type': 'array'}}), 'initial': {'allowlist': None, 'denylist': []}})
comp('mcp-tool', 'McpTool', 'agents',
     'A tool of a server: calls tools/call through McpServer.callOn, retries once after URL elicitation.',
     [f'{MC}/common/mcpServer.ts:1330-1458'])
comp('mcp-language-model-tool-contribution', 'McpLanguageModelToolContribution', 'agents',
     'Workbench contribution that registers each enabled server tool with the language model tools service.',
     [f'{MC}/common/mcpLanguageModelToolContribution.ts:41', f'{MC}/browser/mcp.contribution.ts:78'])
comp('mcp-tool-implementation', 'McpToolImplementation', 'agents',
     'The language model tool for one MCP tool: confirmation in prepareToolInvocation, then invoke.',
     [f'{MC}/common/mcpLanguageModelToolContribution.ts:213-263'])
comp('mcp-sampling-service', 'McpSamplingService', 'agents',
     'Serves sampling/createMessage from MCP servers: permission per server (chat.mcp.serverSampling), model choice, then a language model request.',
     [f'{MC}/common/mcpTypes.ts:1233', f'{MC}/common/mcpSamplingService.ts:35', f'{MC}/browser/mcp.contribution.ts:63'],
     state={'schema': obj({'allowed_during_chat': {'type': 'array'}, 'allowed_outside_chat': {'type': 'array'}, 'server_sampling': {'type': 'object'}}),
            'initial': {'allowed_during_chat': [], 'allowed_outside_chat': [], 'server_sampling': {}}},
     capacity={'concurrency': 1})
comp('mcp-elicitation-service', 'McpElicitationService', 'agents',
     'Serves elicitation/create: form questions in chat or a notification, URL elicitation through the opener.',
     [f'{MC}/common/mcpTypes.ts:1303', f'{MC}/browser/mcpElicitationService.ts:65-230', f'{MC}/browser/mcp.contribution.ts:64'])
comp('mcp-discovery', 'McpDiscovery', 'agents',
     'Workbench contribution: starts the registered MCP discovery sources according to chat.mcp.access.',
     [f'{MC}/browser/mcpDiscovery.ts:15-44', f'{MC}/browser/mcp.contribution.ts:74'])
comp('extension-mcp-discovery', 'ExtensionMcpDiscovery', 'agents',
     'Handles the mcpServerDefinitionProviders extension point: lazy, trusted collections per contributing extension.',
     [f'{MC}/common/discovery/extensionMcpDiscovery.ts:27', f'{MC}/common/discovery/extensionMcpDiscovery.ts:34-109'],
     state={'schema': obj({'collections': {'type': 'array'}}), 'initial': {'collections': []}})
comp('mcp-commands', 'MCP commands (mcpCommands.ts)', 'agents',
     'The MCP: ... commands registered by mcp.contribution.ts (list servers, server options, start/stop/restart, trust and cache resets, mcp.json, sampling models).',
     [f'{MC}/browser/mcpCommands.ts'])
comp('mcp-gateway-tool-broker-channel', 'McpGatewayToolBrokerChannel', 'agents',
     'IPC channel mcpGatewayToolBroker registered on the remote/local connection: lists and calls MCP tools for the MCP gateway.',
     [f'{MC}/common/mcpGatewayToolBrokerChannel.ts:35', f'{MC}/browser/mcpGatewayToolBrokerContribution.ts:19', f'{MC}/electron-browser/mcpGatewayToolBrokerContribution.ts:19'])
comp('mcp-gateway-tool-broker-contribution', 'McpGatewayToolBrokerContribution', 'agents',
     'Workbench contributions (remote and local variants) that register the gateway tool broker channel.',
     [f'{MC}/browser/mcpGatewayToolBrokerContribution.ts:13', f'{MC}/browser/mcp.contribution.ts:79',
      f'{MC}/electron-browser/mcpGatewayToolBrokerContribution.ts:13', f'{MC}/electron-browser/mcp.contribution.ts:23'])
comp('mcp-gallery-manifest-ipc-service', 'McpGalleryManifestIPCService', 'agents',
     'Channel mcpGalleryManifest: the window pushes the MCP gallery manifest to a utility process (shared process). Parented here because agents owns src/vs/platform/mcp.',
     [f'{PM}/common/mcpGalleryManifestServiceIpc.ts:12-60'],
     state={'schema': obj({'manifest': {'type': ['object', 'null']}, 'status': S}), 'initial': {'manifest': None, 'status': 'unavailable'}})
# MCP workbench contributions without decisions worth simulating beyond their startup
for cid, name, summ, srcs in [
    ('mcp-context-keys-controller', 'McpContextKeysController', 'Binds MCP context keys (server counts, tools, errors).', [f'{MC}/common/mcpContextKeys.ts:32', f'{MC}/browser/mcp.contribution.ts:75']),
    ('mcp-language-features', 'McpLanguageFeatures', 'Code lenses, decorations and hovers in mcp.json files.', [f'{MC}/browser/mcpLanguageFeatures.ts:50', f'{MC}/browser/mcp.contribution.ts:76']),
    ('mcp-resource-filesystem', 'McpResourceFilesystem', 'Registers the mcp-resource file system provider for server resources.', [f'{MC}/common/mcpResourceFilesystem.ts:36', f'{MC}/browser/mcp.contribution.ts:77']),
    ('mcp-server-action-rendering', 'MCPServerActionRendering', 'Renders the MCP server status action in the chat input.', [f'{MC}/browser/mcpCommands.ts:857', f'{MC}/browser/mcp.contribution.ts:109']),
    ('mcp-add-context-contribution', 'McpAddContextContribution', 'Offers MCP resources in the chat Add Context picker.', [f'{MC}/browser/mcpAddContextContribution.ts:17', f'{MC}/browser/mcp.contribution.ts:110']),
    ('mcp-contexts-initialisation', 'MCPContextsInitialisation', 'Initialises MCP gallery and installed-servers context keys.', [f'{MC}/browser/mcpWorkbenchService.ts:1129', f'{MC}/browser/mcp.contribution.ts:111']),
    ('mcp-config-migration-contribution', 'McpConfigMigrationContribution', 'Migrates MCP servers from settings.json "mcp" into mcp.json.', [f'{MC}/browser/mcpMigration.ts:32', f'{MC}/browser/mcp.contribution.ts:112']),
    ('mcp-servers-views-contribution', 'McpServersViewsContribution', 'Registers the MCP servers views in the extensions container.', [f'{MC}/browser/mcpServersView.ts:479', f'{MC}/browser/mcp.view.contribution.ts:9']),
]:
    comp(cid, name, 'agents', summ, srcs)

# ------------------------------------------------------------------ sessions (Agents window)
comp('sessions-main', 'SessionsMain (sessions.main.ts)', 'agents',
     'Desktop entry of the Agents window renderer: init services, create the sessions workbench, start it.',
     [f'{SS}/electron-browser/sessions.main.ts:80-149', f'{SS}/electron-browser/sessions.main.ts:416-420'], kind='function')
comp('sessions-workbench', 'Workbench (sessions)', 'agents',
     'The Agents window workbench: starts the contribution registry by phase, restores visible sessions.',
     [f'{SS}/browser/workbench.ts:277', f'{SS}/browser/workbench.ts:559-596', f'{SS}/browser/workbench.ts:1181-1204'])
comp('sessions-web-main', 'sessions.web.main', 'agents',
     'Web entry of the Agents window: registers web singletons (remote agent host clients, null SSH/WSL services); no local agent host.',
     [f'{SS}/sessions.web.main.ts:123-145'], kind='function')
comp('sessions-providers-service', 'SessionsProvidersService', 'agents',
     'Registry of sessions providers (local agent host, Copilot cloud, remote hosts), ordered by order.',
     [f'{SS}/services/sessions/browser/sessionsProvidersService.ts:13', f'{SS}/services/sessions/browser/sessionsProvidersService.ts:37-125'],
     state={'schema': obj({'providers': {'type': 'object'}}), 'initial': {'providers': {}}})
comp('sessions-management-service', 'SessionsManagementService', 'agents',
     'Session lifecycle across providers: new sessions, sending, rename, archive, delete, read state.',
     [f'{SS}/services/sessions/common/sessionsManagement.ts:676', f'{SS}/services/sessions/browser/sessionsManagementService.ts:40', f'{SS}/services/sessions/browser/sessionsManagementService.ts:1592'],
     state={'schema': obj({'new_session': S}), 'initial': {'new_session': ''}})
comp('sessions-service', 'SessionsService', 'agents',
     'Visible and active sessions of the Agents window, open/close, restore.',
     [f'{SS}/services/sessions/browser/sessionsService.ts:389', f'{SS}/services/sessions/browser/sessionsService.ts:391', f'{SS}/services/sessions/browser/sessionsService.ts:2412'],
     state={'schema': obj({'visible': {'type': 'array'}, 'active': S}), 'initial': {'visible': [], 'active': ''}})
comp('sessions-list-model-service', 'SessionsListModelService', 'agents',
     'Sessions list state persisted in profile storage: pinned sessions, read markers, sort overrides.',
     [f'{SS}/services/sessions/browser/sessionsListModelService.ts:100', f'{SS}/services/sessions/browser/sessionsListModelService.ts:106', f'{SS}/services/sessions/browser/sessionsListModelService.ts:482'],
     state={'schema': obj({'pinned': {'type': 'array', 'items': S}}), 'initial': {'pinned': []}})
comp('local-agent-host-sessions-provider', 'LocalAgentHostSessionsProvider', 'agents',
     "Sessions provider 'local-agent-host' backed by the local agent host connection (BaseAgentHostSessionsProvider logic).",
     [f'{SS}/contrib/providers/agentHost/browser/localAgentHostSessionsProvider.ts:75', f'{SS}/contrib/providers/agentHost/browser/baseAgentHostSessionsProvider.ts:4203'],
     state={'schema': obj({'session_cache': {'type': 'object'}, 'new_session': S, 'connected': B}),
            'initial': {'session_cache': {}, 'new_session': '', 'connected': True}})
comp('copilot-chat-sessions-provider', 'CopilotChatSessionsProvider', 'agents',
     "Sessions provider 'default': Copilot cloud sessions surfaced from the Copilot extension.",
     [f'{SS}/contrib/providers/copilotChatSessions/browser/copilotChatSessions.contribution.ts:35-36'])
comp('local-agent-host-contribution', 'LocalAgentHostContribution', 'agents',
     'Registers the local agent host sessions provider while the agent host is enabled, unregisters it otherwise.',
     [f'{SS}/contrib/providers/agentHost/browser/localAgentHost.contribution.ts:33-86', f'{SS}/contrib/providers/agentHost/browser/localAgentHost.contribution.ts:98'])
comp('default-sessions-provider-contribution', 'DefaultSessionsProviderContribution', 'agents',
     "Registers the 'default' Copilot cloud sessions provider at AfterRestored.",
     [f'{SS}/contrib/providers/copilotChatSessions/browser/copilotChatSessions.contribution.ts:24-58', f'{SS}/contrib/providers/copilotChatSessions/browser/copilotChatSessions.contribution.ts:61'])
comp('local-agent-host-lifecycle-contribution', 'LocalAgentHostLifecycleContribution', 'agents',
     'Vetoes quitting while a local agent session is still working, unless the user confirms.',
     [f'{SS}/contrib/providers/agentHost/electron-browser/localAgentHostLifecycle.contribution.ts:22-69', f'{SS}/contrib/providers/agentHost/electron-browser/localAgentHostLifecycle.contribution.ts:71'],
     state={'schema': obj({'active_session_working': B}), 'initial': {'active_session_working': False}})
comp('sessions-view-actions', 'Sessions view actions (sessionsViewActions.ts)', 'agents',
     'Commands of the sessions list: rename, delete, archive with undo, pin, mark read.',
     [f'{SS}/contrib/sessions/browser/views/sessionsViewActions.ts'])
comp('sessions-actions', 'Session actions (sessionsActions.ts)', 'agents',
     'Session header and grid commands: rename from header, close all sessions.',
     [f'{SS}/contrib/sessions/browser/sessionsActions.ts'])
comp('sessions-chat-actions', 'Sessions chat actions (chat.contribution.ts)', 'agents',
     'New Session and Branch Chat commands of the Agents window.',
     [f'{SS}/contrib/chat/browser/chat.contribution.ts:176-177', f'{SS}/contrib/chat/browser/newSessionAction.ts:28-143'])
comp('agent-host-electron-contribution', 'agentHost.contribution (electron-browser)', 'agents',
     'Registers the agent host developer and restart commands in the Agents window.',
     [f'{SS}/contrib/providers/agentHost/electron-browser/agentHost.contribution.ts'])
comp('open-agents-window-command', 'registerOpenAgentsWindowCommand', 'agents',
     'Command workbench.action.openAgentsWindow, registered at Agents window startup: asks the main process to open/focus the Agents window.',
     [f'{SS}/contrib/openAgentsWindow/electron-browser/openAgentsWindowCommand.ts:12-19', f'{SS}/sessions.desktop.main.ts:26'], kind='function')

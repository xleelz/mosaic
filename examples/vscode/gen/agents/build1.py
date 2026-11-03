# Builder for examples/vscode/fragments/agents.yaml (part 1: helpers, configs, components)
import json, re

AH = 'src/vs/platform/agentHost'
MC = 'src/vs/workbench/contrib/mcp'
PM = 'src/vs/platform/mcp'
SS = 'src/vs/sessions'
CS = 'src/vs/workbench/contrib/chat/browser/chat.shared.contribution.ts'

components = []
interfaces = []
flows = []
scenarios = []
configs = []
schemas = []


def comp(id, name, parent, summary, sources, kind='module', layer='ai', state=None, attributes=None, capacity=None):
    c = {'id': id, 'name': name, 'kind': kind, 'layer': layer, 'parent': parent, 'summary': summary, 'sources': sources}
    a = {'owner': 'agents'}
    if attributes:
        a.update(attributes)
    c['attributes'] = a
    if state is not None:
        c['state'] = state
    if capacity:
        c['capacity'] = capacity
    components.append(c)
    return c


def stubcomp(id, name, parent, owner, summary, layer='workbench'):
    components.append({'id': id, 'name': name, 'kind': 'module', 'layer': layer, 'parent': parent,
                       'summary': summary, 'attributes': {'boundary': True, 'owner': owner}})


def iface(component, name, summary, sources, behavior=None, request=None, response=None, kind='function',
          errors=None, attributes=None, store=None, subscribe=None, latency=None):
    i = {'component': component, 'name': name, 'kind': kind, 'summary': summary}
    if sources:
        i['sources'] = sources
    if attributes:
        i['attributes'] = attributes
    if request is not None:
        i['request'] = request
    if response is not None:
        i['response'] = response
    if errors:
        i['errors'] = errors
    if subscribe:
        i['subscribe'] = subscribe
    if latency is not None:
        i['latency_ms'] = latency
    if store is not None:
        i['store'] = store
    if behavior is not None:
        i['behavior'] = behavior
    interfaces.append(i)
    return i


def stub(component, name, owner, summary, request=None, response=None, kind='function', errors=None):
    i = {'component': component, 'name': name, 'kind': kind, 'summary': summary,
         'attributes': {'boundary': True, 'owner': owner}}
    if request is not None:
        i['request'] = request
    if response is not None:
        i['response'] = response
    if errors:
        i['errors'] = errors
    interfaces.append(i)


def obj(props, required=None):
    o = {'type': 'object', 'properties': props}
    if required:
        o['required'] = required
    return o


S = {'type': 'string'}
B = {'type': 'boolean'}
I = {'type': 'integer'}


def s(*ex, **kw):
    d = {'type': 'string'}
    if ex:
        d['examples'] = list(ex)
    d.update(kw)
    return d


def err(code, summary, retryable=False, status=0):
    return {'code': code, 'status': status, 'retryable': retryable, 'summary': summary}


def cmd_slug(cid):
    s_ = re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]', '-', re.sub(r'[._]', '-', cid).lower())).strip('-')
    return ('cmd-' + s_)[:64].rstrip('-')


def cfg(id, key, typ, value, default, summary, sources, boundary_owner=None, extra=None):
    c = {'id': id, 'type': typ, 'value': value, 'default': default, 'summary': summary, 'sources': sources}
    a = {'key': key}
    if boundary_owner:
        a = {'boundary': True, 'owner': boundary_owner, 'key': key}
    if extra:
        a.update(extra)
    c['attributes'] = a
    configs.append(c)


# ------------------------------------------------------------------ configs
cfg('chat-mcp-autostart', 'chat.mcp.autostart', 'string', 'newAndOutdated', 'newAndOutdated',
    'chat.mcp.autostart: which MCP servers start automatically when a chat message is submitted (never, onlyNew, newAndOutdated). product.json does not override it.',
    [f'{CS}:1285', f'{CS}:1288'])
cfg('chat-mcp-access', 'chat.mcp.access', 'string', 'all', 'all',
    'chat.mcp.access: none, registry or all (policy ChatMCP can override). product.json does not override it.',
    [f'{CS}:1141', f'{CS}:1154'])
cfg('chat-mcp-apps-enabled', 'chat.mcp.apps.enabled', 'boolean', True, True,
    'chat.mcp.apps.enabled: whether MCP tool invocations may carry custom UI (mcpAppData).',
    [f'{CS}:1301', f'{CS}:1304'])
cfg('chat-mcp-server-sampling', 'chat.mcp.serverSampling', 'object', {}, {},
    'chat.mcp.serverSampling: per-server sampling permissions keyed "<collection label>: <server label>". No top-level default; the per-entry schema defaults (allowedDuringChat true, allowedOutsideChat false) are not applied when a server has no entry, so the code sees undefined and prompts.',
    [f'{CS}:1355', f'{CS}:1365'])
cfg('chat-agent-host-claude-agent-enabled', 'chat.agentHost.claudeAgent.enabled', 'boolean', True, True,
    'chat.agentHost.claudeAgent.enabled: lets the agent host register the Claude harness (passed to the host as an env var; the SDK must also be available).',
    [f'{AH}/common/agentHostStarter.config.contribution.ts:334', f'{AH}/node/agentHostMain.ts:204-206'])
cfg('chat-agent-host-codex-agent-enabled', 'chat.agentHost.codexAgent.enabled', 'boolean', True, False,
    "chat.agentHost.codexAgent.enabled: default is product.quality !== 'stable'. product.json of this OSS build sets no quality, so the deployed value is true. The code default is the expression quality !== 'stable', recorded as false (its Stable value).",
    [f'{AH}/common/agentHostStarter.config.contribution.ts:364', 'product.json:2'])
cfg('chat-disable-ai-features', 'chat.disableAIFeatures', 'boolean', False, False,
    'chat.disableAIFeatures: when true the agent host is reported disabled (reference; registered by chat).',
    ['src/vs/workbench/contrib/chat/browser/chat.shared.contribution.ts:2437', f'{AH}/browser/agentHostEnablementService.ts:33'], boundary_owner='chat')
cfg('chat-tools-global-auto-approve', 'chat.tools.global.autoApprove', 'boolean', False, False,
    'chat.tools.global.autoApprove (YOLO mode): MCP sampling auto-allows without prompting (reference; registered by chat).',
    [f'{CS}:832-833'], boundary_owner='chat')
# Code constants the modeled behaviors read (no setting key): kept as config entities so scenarios can vary them.
cfg('agent-host-max-restarts', 'AgentHostProcessManager.Constants.MaxRestarts', 'integer', 5, 5,
    'Code constant: unexpected agent host exits restart immediately until 5 restarts, then the manager gives up.',
    [f'{AH}/node/agentHostService.ts:17-20'], extra={'constant': True})
cfg('agent-host-shutdown-timeout-ms', 'AgentHostProcessManager.Constants.ShutdownTimeoutMs', 'integer', 6000, 6000,
    'Code constant: graceful shutdown before an explicit restart or quit is raced against 6 s.',
    [f'{AH}/node/agentHostService.ts:19'], extra={'constant': True})
cfg('mcp-gateway-startup-grace-period-ms', 'McpGatewayToolBrokerChannel._startupGracePeriodMs', 'integer', 5000, 5000,
    'Code constant: the gateway tool broker waits up to 5 s for a server to become ready before answering from cache.',
    [f'{MC}/common/mcpGatewayToolBrokerChannel.ts:55', f'{MC}/common/mcpGatewayToolBrokerChannel.ts:126'], extra={'constant': True})
cfg('agent-host-server-default-port', 'agentHostServerMain --port default', 'string', '8081', '8081',
    'Code default: the standalone agent host server listens on --port, else VSCODE_AGENT_HOST_PORT, else 8081.',
    [f'{AH}/node/agentHostServerMain.ts:92-94'], extra={'constant': True})
cfg('ahp-supported-protocol-versions', 'SUPPORTED_PROTOCOL_VERSIONS', 'array', ['1.0.0', '0.9.0'], ['1.0.0', '0.9.0'],
    'Code constant: protocol baselines a host accepts (caret-compatible), plus the legacy 0.10.0 alias; the host speaks PROTOCOL_VERSION 1.1.0.',
    [f'{AH}/common/state/protocol/version/registry.ts:36-39', f'{AH}/common/agentHostProtocolCompatibility.ts:10'], extra={'constant': True})
cfg('agent-host-worktree-cleanup-interval-ms', 'AgentHostWorktreeCleanupService periodic interval', 'integer', 300000, 300000,
    'Code constant: the worktree cleanup service runs a pass every 5 minutes (3 s debounce, 30 s..1 h backoff).',
    [f'{AH}/node/agentHostWorktreeCleanupService.ts:87-90'], extra={'constant': True})

# ------------------------------------------------------------------ boundary components (other areas)
stubcomp('lifecycle-service', 'NativeLifecycleService', 'workbench', 'workbench-shell', "Renderer lifecycle service (workbench-shell): answers the main process's onBeforeUnload/onWillUnload.")
stubcomp('editor-service', 'EditorService', 'workbench', 'workbench-shell', 'Editor service (workbench-shell).')
stubcomp('workspace-trust-management-service', 'WorkspaceTrustManagementService', 'workbench', 'workbench-shell', 'Workspace trust (workbench-shell).')
stubcomp('workspace-trust-request-service', 'WorkspaceTrustRequestService', 'workbench', 'workbench-shell', 'Workspace trust prompts (workbench-shell).')
stubcomp('workbench-mcp-management-service', 'WorkbenchMcpManagementService', 'workbench', 'workbench-shell', 'Workbench MCP management (workbench-shell, src/vs/workbench/services/mcp): installs into user/workspace mcp.json.')
stubcomp('language-models-service', 'LanguageModelsService', 'workbench', 'chat', 'Language model registry and requests (chat).')
stubcomp('chat-service', 'ChatService', 'workbench', 'chat', 'Chat sessions and requests (chat).')
stubcomp('extension-service', 'ExtensionService', 'exthost-bridge', 'exthost', 'Extension service (exthost): activation by event.', layer='extensions')
stubcomp('native-host-main-service', 'NativeHostMainService', 'main-process', 'main-process', 'Native host service in the main process (main-process).', layer='process')

# ------------------------------------------------------------------ agent host process (parent agent-host)
comp('agent-host-main', 'agentHostMain startAgentHost', 'agent-host',
     'Utility-process entry: builds the agent host runtime, registers the IPC channels and the local/configured protocol endpoints.',
     [f'{AH}/node/agentHostMain.ts:74-80', f'{AH}/node/agentHostMain.ts:113-546'], kind='function', layer='process')
comp('agent-host-logger-channel', 'LoggerChannel (agentHostLogger)', 'agent-host',
     'IPC channel agentHostLogger: lets the parent forward the host log to its logger service.',
     [f'{AH}/node/agentHostMain.ts:127'], layer='process')
comp('agent-host-provider-service', 'AgentHostProviderService', 'agent-host',
     'Registry of agent harnesses (Copilot, Claude, Codex); the first registered provider is the default.',
     [f'{AH}/node/agentHostProviderService.ts:19', f'{AH}/node/agentHostProviderService.ts:101-141'],
     state={'schema': obj({'providers': {'type': 'array', 'items': S}}), 'initial': {'providers': ['copilot']}}, layer='process')
comp('agent-service', 'AgentService', 'agent-host',
     'The orchestrator: creates and disposes sessions, routes client actions to the state manager and side effects; served as the agentHost IPC channel.',
     [f'{AH}/common/agentService.ts:966', f'{AH}/node/agentService.ts:943', f'{AH}/node/agentHostMain.ts:268'],
     layer='process', capacity={'concurrency': 1})
comp('agent-host-state-manager', 'AgentHostStateManager', 'agent-host',
     'Authoritative protocol state: sessions, their chats, status aggregation, client action envelopes and rejections.',
     [f'{AH}/node/agentHostStateManager.ts:334', f'{AH}/node/agentHostStateManager.ts:2588-2624'],
     state={'schema': obj({'sessions': {'type': 'object'}, 'server_seq': I}), 'initial': {'sessions': {}, 'server_seq': 0}}, layer='process')
comp('agent-host-database', 'AgentHostDatabase (agent-host.db)', 'agent-host',
     'SQLite orchestrator database globalStorage/agent-host.db: session registrations (sessions_v2) and chats.',
     [f'{AH}/node/agentHostDatabase.ts:408', f'{AH}/node/agentHostDatabase.ts:1166', f'{AH}/node/agentHostBootstrap.ts:120-123'],
     kind='datastore', layer='storage', state={'schema': obj({'sessions_v2': {'type': 'object'}}), 'initial': {'sessions_v2': {}}})
comp('agent-side-effects', 'AgentSideEffects', 'agent-host',
     'Reacts to applied client actions: starts and cancels turns, answers permission requests.',
     [f'{AH}/node/agentSideEffects.ts:1795-1941'], layer='process')
comp('agent-host-turn-service', 'AgentHostTurnService', 'agent-host',
     'Routes ChatTurnStarted to the turn starter and the harness.',
     [f'{AH}/node/agentHostTurnService.ts:21', f'{AH}/node/agentHostTurnService.ts:126-172'], layer='process')
comp('agent-host-turn-starter', 'startTurn', 'agent-host',
     'Admits a turn (incoming-request contributions), resolves the harness and sends the message.',
     [f'{AH}/node/agentHostTurnStarter.ts:70-148'], kind='function', layer='process')
comp('turn-admission-contribution', 'TurnAdmissionContribution', 'agent-host',
     'Rejects turns on archived or read-only chats.',
     [f'{AH}/node/chatContributions/turnAdmission/turnAdmissionContribution.ts:29-43'], layer='process')
comp('copilot-agent', 'CopilotAgent', 'agent-host',
     'The Copilot SDK harness, always registered first, so it is the default provider.',
     [f'{AH}/node/copilot/copilotAgent.ts', f'{AH}/node/agentHostMain.ts:190'], layer='process')
comp('claude-agent', 'ClaudeAgent', 'agent-host',
     'The Claude SDK harness; refuses to create chats without authentication.',
     [f'{AH}/node/claude/claudeAgent.ts:781-785', f'{AH}/node/agentHostMain.ts:204-206'], layer='process')
comp('session-permissions', 'SessionPermissionManager', 'agent-host',
     'Decides whether a tool call needs a confirmation (auto-approve settings, workdir reads, shell commands).',
     [f'{AH}/node/sessionPermissions.ts:253-360'], layer='process')
comp('command-auto-approver', 'CommandAutoApprover', 'agent-host',
     'Tree-sitter based shell command auto-approval: deny rules, unparseable commands and unsafe redirects need confirmation.',
     [f'{AH}/node/commandAutoApprover.ts:286-315'], layer='process')
comp('agent-host-authentication-service', 'AgentHostAuthenticationService', 'agent-host',
     'Stores tokens pushed by clients per protected resource and hands them to harnesses.',
     [f'{AH}/node/agentHostAuthenticationService.ts:28', f'{AH}/node/agentHostAuthenticationService.ts:109-273'],
     state={'schema': obj({'tokens': {'type': 'object'}}), 'initial': {'tokens': {}}}, layer='process')
comp('worktree-isolation', 'WorktreeIsolation', 'agent-host',
     'Creates a git worktree for sessions with isolation "worktree" (serialized per repository).',
     [f'{AH}/node/shared/worktreeIsolation.ts:35', f'{AH}/node/shared/worktreeIsolation.ts:1118-1170'], layer='process',
     capacity={'concurrency': 1})
comp('agent-host-worktree-cleanup-service', 'AgentHostWorktreeCleanupService', 'agent-host',
     'Removes worktrees of archived sessions: a startup sweep, then periodic single-flight passes.',
     [f'{AH}/node/agentHostWorktreeCleanupService.ts:20', f'{AH}/node/agentHostWorktreeCleanupService.ts:322-352'],
     state={'schema': obj({'passes': I, 'running': B}), 'initial': {'passes': 0, 'running': False}}, layer='process')
comp('protocol-server-handler', 'ProtocolServerHandler (agentHostProtocol)', 'agent-host',
     'AHP JSON-RPC server for every client transport (MessagePort channel agentHostProtocol, local socket, WebSocket).',
     [f'{AH}/node/protocolServerHandler.ts:801-953', f'{AH}/node/agentHostMain.ts:348'],
     state={'schema': obj({'clients': {'type': 'object'}}), 'initial': {'clients': {}}}, layer='process')
comp('agent-host-management-service', 'AgentHostManagementService (agentHostManagement)', 'agent-host',
     'Management channel: graceful shutdown (drain protocol, stop providers, flush), WebSocket and inspector control.',
     [f'{AH}/node/agentHostManagementService.ts:18-20', f'{AH}/node/agentHostManagementService.ts:294-331', f'{AH}/node/agentHostMain.ts:513'],
     state={'schema': obj({'shutting_down': B}), 'initial': {'shutting_down': False}}, layer='process')
comp('agent-host-connection-tracker', 'connectionTrackerService (agentHostConnectionTracker)', 'agent-host',
     'Child-process channel: connection counts and an on-demand local WebSocket server.',
     [f'{AH}/node/agentHostMain.ts:391-477', f'{AH}/node/agentHostMain.ts:515'],
     state={'schema': obj({'socket': S}), 'initial': {'socket': ''}}, layer='process')
comp('agent-host-server-main', 'agentHostServerMain', 'agent-host',
     'Standalone agent host server (code agent / CLI): parses --port/--host/--connection-token, serves AHP over WebSocket.',
     [f'{AH}/node/agentHostServerMain.ts:14', f'{AH}/node/agentHostServerMain.ts:156-401'], kind='function', layer='process')
comp('diff-compute-service', 'NodeWorkerDiffComputeService', 'agent-host',
     'Computes diff counts and hunks for session changes on a worker thread.',
     [f'{AH}/common/diffComputeService.ts:62', f'{AH}/node/diffComputeService.ts:17-64'], layer='process')
comp('diff-worker', 'diffWorkerMain', 'agent-host',
     'Worker thread entry answering computeDiffCounts / computeDetailedDiff / computeDiffHunks messages.',
     [f'{AH}/node/diffWorkerMain.ts:180-210'], kind='function', layer='process')
comp('agent-host-process-manager', 'AgentHostProcessManager', 'agent-host',
     'Lazy start and crash recovery of the agent host utility process. Runs in the Electron main process (created by app.ts); parented here because agents owns src/vs/platform/agentHost/node.',
     [f'{AH}/node/agentHostService.ts:37-260'],
     state={'schema': obj({'running': B, 'restart_count': I, 'restart_limit_reached': B, 'quit_requested': B, 'starts': I}),
            'initial': {'running': False, 'restart_count': 0, 'restart_limit_reached': False, 'quit_requested': False, 'starts': 0}},
     layer='process')

# ------------------------------------------------------------------ renderer: agent host client side (parent agents)
comp('local-agent-host-service-client', 'LocalAgentHostServiceClient', 'agents',
     'Renderer client of the local agent host, wrapped by the desktop IAgentHostService (WorkbenchAgentHostService, workbench-shell): acquires a MessagePort, reconnects, restarts the host.',
     [f'{AH}/electron-browser/localAgentHostService.ts:173', f'{AH}/electron-browser/localAgentHostService.ts:816-819', f'{AH}/electron-browser/localAgentHostService.ts:866-879'])
comp('agent-host-client-proxy-channel', 'AgentHostClientProxyChannel', 'agents',
     'Reverse channel agentHostClientProxy: the host asks the window to resolve proxies and proxy authorization.',
     [f'{AH}/common/agentHostClientProxyChannel.ts:19', f'{AH}/electron-browser/localAgentHostService.ts:871'])
comp('agent-host-client-byok-lm-channel', 'AgentHostClientByokLmChannel', 'agents',
     'Reverse channel agentHostClientByokLm: the host runs bring-your-own-key model requests through the window.',
     [f'{AH}/common/agentHostClientByokLmChannel.ts:28', f'{AH}/electron-browser/localAgentHostService.ts:874'])
comp('browser-agent-host-enablement-service', 'BrowserAgentHostEnablementService', 'agents',
     'enabled = runtime available (not web) and not chat.disableAIFeatures; binds the agentHostEnabled context key.',
     [f'{AH}/common/agentHostEnablementService.ts:24', f'{AH}/browser/agentHostEnablementService.ts:33', f'{AH}/browser/agentHostEnablementService.ts:45-55'],
     state={'schema': obj({'is_web': B}), 'initial': {'is_web': False}})

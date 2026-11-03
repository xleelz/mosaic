
i = get('interfaces', 'chat.instantiate-contributions')
b = i['behavior']
n = next(k for k, s in enumerate(b) if s.get('call') == 'extension-agent-plugin-discovery.handle-chat-plugins-extension-point')
b.insert(n, {'title': 'AgentPluginService starts each registered discovery (ExtensionAgentPluginDiscovery among them)',
             'source': 'src/vs/workbench/contrib/chat/common/plugins/agentPluginServiceImpl.ts:160-162',
             'call': 'extension-agent-plugin-discovery.start'})

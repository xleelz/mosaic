for sid in ['chat-submit-happy', 'chat-submit-then-read']:
    s = get('scenarios', sid)
    s['expect'] = [e.replace("'onChatParticipant:github.copilot.default'", "'onChatParticipant:github.copilot.editsAgent'").replace("agent_id == 'github.copilot.default'", "agent_id == 'github.copilot.editsAgent'") for e in s['expect']]
    s['description'] = (s.get('description', '') + ' The widget starts in Agent mode, so the default participant is github.copilot.editsAgent (getDefaultAgent(panel, agent)).').strip()
s = get('scenarios', 'chat-submit-no-default-agent')
s['state'] = {'chat-agent-service@w1': {'agents': {'github.copilot.editsAgent': {'has_impl': False}}}}
s['description'] = 'The Agent-mode default participant is not activated: no default agent for (panel, agent).'

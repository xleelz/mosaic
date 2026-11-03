S = 'src/vs/workbench/contrib/chat/common/chatService/chatServiceImpl.ts'
TOK = "= 'chat-request:' + input.session_resource + ':' + input.request_id"
i = get('interfaces', 'chat-service.run-request')
i['request']['properties']['default_agent_id'] = {'type': 'string', 'default': ''}
b = i['behavior']
# token name first
b.insert(0, {'set': {'vars.tok': TOK}})
for s in b:
    if s.get('title') == 'Canceled before the agent ran':
        s['title'] = 'The request was already cancelled (its token fired and cancelRequest ran) before the async body got here'
        s['detail'] = 'The cancellation listener calls model.cancelRequest; nothing more is recorded.'
        s['source'] = S + ':1987-2003'
        s['if'] = "canceled(vars.tok) || !vars.sess.pending || vars.sess.pending_request_id != input.request_id"
# locate invoke step
n = next(k for k, s in enumerate(b) if s.get('call') == 'chat-agent-service.invoke-agent')
inv = b[n]
inv['token'] = '= vars.tok'
inv['stream'] = True
inv['on_item'] = [{'title': 'Each progress chunk goes through the progress callback into the response',
                   'source': S + ':1862-1883',
                   'call': 'chat-service.accept-response-progress',
                   'input': {'session_resource': '= input.session_resource', 'request_id': '= input.request_id', 'part': '= vars.item'}, 'fill': True}]
old_err = inv['on_error']
inv['on_error'] = [{'title': 'Cancelled while the participant ran: cancelRequest already recorded it',
                    'source': S + ':2211-2212', 'if': "error.code == 'canceled'",
                    'then': [{'return': {'outcome': 'canceled'}}]}] + old_err
autostart = [
  {'title': 'MCP autostart before invoking (only for sessions that can use tools)',
   'source': S + ':2169-2176',
   'if': "!has(vars.sess.can_use_tools) || vars.sess.can_use_tools",
   'then': [
     {'call': 'mcp-service.autostart', 'token': '= vars.tok', 'input': {}, 'as': 'mcp', 'fill': True,
      'on_error': [{'if': "error.code == 'canceled'", 'then': [{'return': {'outcome': 'canceled'}}]}]},
     {'title': 'Servers starting are shown as a ChatMcpServersStarting progress part, awaited before the agent runs',
      'source': S + ':2171-2174',
      'if': 'size(vars.mcp.value.started) > 0 || size(vars.mcp.value.requiring_interaction) > 0',
      'then': [{'call': 'chat-service.accept-response-progress',
                'input': {'session_resource': '= input.session_resource', 'request_id': '= input.request_id',
                          'part': {'kind': 'mcpServersStarting', 'servers': '= vars.mcp.value.started'}}, 'fill': True}]}]}]
b[n:n] = autostart
n = next(k for k, s in enumerate(b) if s.get('call') == 'chat-agent-service.invoke-agent')
b.insert(n + 1, {'title': 'Cancelled with no result: return without recording', 'source': S + ':2211-2212',
                 'if': 'canceled(vars.tok)', 'then': [{'return': {'outcome': 'canceled'}}]})
i['sources'] = [S + ':1821-2301']

# invoke-agent: stream the participant's progress (the progress callback) through to the caller
i = get('interfaces', 'chat-agent-service.invoke-agent')
for s in i['behavior']:
    if s.get('call') == 'ext-host-chat-agents2.invoke-agent':
        s['stream'] = True
        s['as'] = 'eh'
        s['on_item'] = [{'title': '$handleProgressChunk: each chunk reaches the progress callback passed to invokeAgent',
                         'source': 'src/vs/workbench/api/browser/mainThreadChatAgents2.ts:481',
                         'yield': '= vars.item'}]
        s['detail'] = 'The participant runs on the extension host; its progress chunks come back as $handleProgressChunk calls while it runs.'
i['summary'] = 'Invokes an activated agent''s implementation, relaying its progress chunks to the caller''s progress callback; throws when the agent has none.'

# cancel
i = get('interfaces', 'chat-service.cancel-current-request-for-session')
b = i['behavior']
n = next(k for k, s in enumerate(b) if s.get('title') == 'Cancel the token and drop the pending request')
b[n:n] = [
  {'title': 'CancellableRequest.cancel: cancel the request''s tool calls first', 'source': S + ':136-142',
   'call': 'language-model-tools-service.cancel-tool-calls-for-request', 'input': {'request_id': '= vars.sess.pending_request_id'}, 'fill': True},
  {'title': 'then cancel its token (the participant on the extension host sees it)', 'source': S + ':141',
   'cancel': "= 'chat-request:' + input.session_resource + ':' + vars.sess.pending_request_id"}]
c = get('components', 'chat-service')
c.pop('capacity', None)
c['summary'] += ' No capacity limit: the service''s methods await (extension activation, the participant), which frees the renderer thread, so a cancel runs while a request is in flight.'
i = get('interfaces', 'chat-service.run-request')
b = i['behavior']
n = next(k for k, s in enumerate(b) if s.get('title') == 'Record the response (success, error or filtered) and free the session')
b.insert(n, {'set': {'vars.sess': '= state.sessions[input.session_resource]'}})
inv = next(s for s in b if s.get('call') == 'chat-agent-service.invoke-agent')
inv['on_error'].insert(1, {'set': {'vars.sess': '= state.sessions[input.session_resource]'}})

S = 'src/vs/workbench/contrib/chat/common/chatService/chatService.ts'
i = get('interfaces', 'chat-tool-invocation.await-confirmation')
ch = next(s for s in i['behavior'] if s.get('choice') == 'user_confirmation')
ch['detail'] = ("allow/skip/deny answer the widget at once; wait leaves the invocation waiting until a later action "
                "(workbench.action.chat.acceptTool / skipTool, or the request's cancellation) calls confirmWith, which resolves the awaited state.")
ch['options']['wait'] = [
  {'title': 'Block on the invocation''s state until confirmWith settles it', 'source': S + ':1076-1082',
   'receive': "= 'tool-confirmation:' + input.call_id", 'as': 'decided'},
  {'set': {'vars.now': '= state.invocations[input.call_id]'}},
  {'return': {'kind': "= vars.now.state == 'confirmed' ? 'user-action' : vars.now.state"}}]
i = get('interfaces', 'chat-tool-invocation.confirm-with')
b = i['behavior']
ret = b.pop()
b.append({'title': 'The confirmation state change wakes whoever awaits it', 'source': S + ':1103-1105',
          'put': "= 'tool-confirmation:' + input.call_id", 'value': '= input.reason'})
b.append(ret)

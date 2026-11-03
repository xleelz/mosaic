PJ = 'extensions/copilot/package.json'
c = get('components', 'chat-agent-service')
def ag(name, default, modes, locs, line):
    return {'extension': 'GitHub.copilot-chat', 'name': name, 'is_default': default, 'locations': locs, 'modes': modes, 'has_impl': True}
c['state']['initial']['agents'] = {
  'github.copilot.default': ag('GitHubCopilot', True, ['ask'], ['panel'], 1296),
  'github.copilot.editingSession': ag('GitHubCopilot', True, ['edit'], ['panel'], 1413),
  'github.copilot.editsAgent': ag('agent', True, ['agent'], ['panel'], 1437),
  'github.copilot.editingSessionEditor': ag('GitHubCopilot', True, ['ask'], ['editor'], 1426),
  'github.copilot.notebook': ag('GitHubCopilot', True, ['ask'], ['notebook'], 1543),
  'github.copilot.terminal': ag('terminal', True, ['ask'], ['terminal'], 1622),
  'github.copilot.vscode': ag('vscode', False, ['agent', 'ask', 'edit'], ['panel'], 1585),
  'github.copilot.terminalPanel': ag('terminal', False, ['agent', 'ask', 'edit'], ['panel'], 1641),
}
c['summary'] = ('Registry of chat participants (agents) and their implementations; picks the default agent per location and mode and invokes agents. '
  'Initial state: the Copilot participants from extensions/copilot/package.json chatParticipants (default ask/panel, editingSession edit/panel, editsAgent agent/panel, '
  'editingSessionEditor, notebook, terminal, and the non-default vscode and terminalPanel); a default participant without modes gets [ask], a non-default one all three modes (chatParticipant.contribution.ts:318).')
for l in [1296, 1437, 1585]:
    s = f'{PJ}:{l}'
    if s not in c['sources']:
        c['sources'].append(s)
c['sources'].append('src/vs/workbench/contrib/chat/browser/chatParticipant.contribution.ts:318')

# send-request: mode, the parsed @-mention, attachment objects
i = get('interfaces', 'chat-service.send-request')
props = i['request']['properties']
props['mode'] = {'type': 'string', 'default': '', 'enum': ['', 'ask', 'edit', 'agent'], 'description': "options.modeInfo.kind; '' when the caller passes no modeInfo (getDefaultAgent then uses ask)"}
props['attached_files'] = {'type': 'array', 'items': {'type': 'object', 'properties': {'resource': {'type': 'string'}, 'kind': {'type': 'string'}}}, 'default': [],
                           'description': 'options.attachedContext: the attached variable entries'}
b = i['behavior']
b[0]['if'] = "input.message.trim() == '' && size(input.attached_files.filter(a, has(a.kind) && a.kind in ['file', 'directory', 'image'])) == 0 && input.agent_id_silent == ''"
b[0]['detail'] = "No text, no explicit file/directory/image attachment (isExplicitFileOrImageVariableEntry), no slash command and no agent id: rejected 'Empty message'."
for n, s in enumerate(b):
    if s.get('call') == 'chat-agent-service.get-default-agent':
        s['input']['mode'] = "= input.mode != '' ? input.mode : 'ask'"
        s['title'] = "Resolve the default agent for the location and the request's mode (Ask when no modeInfo is given)"
        s['source'] = 'src/vs/workbench/contrib/chat/common/chatService/chatServiceImpl.ts:1643-1646'
    if 'set' in s and 'vars.agent' in s['set']:
        b[n] = {'title': 'Parse the request: an @-mentioned participant becomes the agent part',
                'source': 'src/vs/workbench/contrib/chat/common/chatService/chatServiceImpl.ts:1651',
                'call': 'chat-request-parser.parse-chat-request',
                'input': {'message': '= input.message', 'location': '= input.location', 'mode': '= input.mode'},
                'as': 'parsed', 'fill': True}
        b.insert(n + 1, {'set': {'vars.rid': s['set']['vars.rid']}})
        b.insert(n + 2, {'title': 'The agent is the silent agent, else the @-mentioned one, else the default agent',
                         'source': 'src/vs/workbench/contrib/chat/common/chatService/chatServiceImpl.ts:1652-1653',
                         'set': {'vars.agent': "= input.agent_id_silent != '' ? input.agent_id_silent : (vars.parsed.value.agent_id != '' ? vars.parsed.value.agent_id : vars.def.value.agent_id)"}})
        break
for s in b:
    if s.get('emit') == 'chat-service.run-request':
        s['input']['default_agent_id'] = "= input.agent_id_silent != '' ? input.agent_id_silent : vars.def.value.agent_id"
i['sources'] = ['src/vs/workbench/contrib/chat/common/chatService/chatServiceImpl.ts:1516-1525', 'src/vs/workbench/contrib/chat/common/chatService/chatServiceImpl.ts:1527-1670']

# accept-input: pass the widget's mode and unlock pet achievements
i = get('interfaces', 'chat-widget.accept-input')
b = i['behavior']
for s in b:
    if s.get('call') == 'chat-service.send-request':
        s['input']['mode'] = "= state.mode == 'agent' && !config['chat-agent-enabled'] ? 'edit' : state.mode"
        s['detail'] = "modeInfo.kind is the input part's current mode; Agent falls back to Edit when chat.agent.enabled is off (chatInputPart.ts:936-940)."
        s['source'] = 'src/vs/workbench/contrib/chat/browser/widget/chatWidget.ts:3562'
b.insert(0, {'set': {'vars.editing': "= state.editing_request_id != ''", 'vars.image': "= size(state.attachments.filter(a, type(a) == map && has(a.kind) && a.kind == 'image')) > 0"}})
ret = b.pop()
b += [
  {'title': 'A user query unlocks the firstChatMessage pet achievement', 'source': 'src/vs/workbench/contrib/chat/browser/widget/chatWidget.ts:4028-4030',
   'if': 'vars.user_query', 'then': [{'call': 'chat-pet-service.unlock-achievement', 'input': {'id': 'firstChatMessage'}, 'fill': True}]},
  {'title': 'Resubmitting an edited request unlocks requestRevision', 'source': 'src/vs/workbench/contrib/chat/browser/widget/chatWidget.ts:4031-4033',
   'if': 'vars.editing', 'then': [{'call': 'chat-pet-service.unlock-achievement', 'input': {'id': 'requestRevision'}, 'fill': True}]},
  {'title': 'A request with an image attached tries imageRequest (a disabled achievement)', 'source': 'src/vs/workbench/contrib/chat/browser/widget/chatWidget.ts:4034-4036',
   'if': 'vars.image', 'then': [{'call': 'chat-pet-service.unlock-achievement', 'input': {'id': 'imageRequest'}, 'fill': True}]},
  ret]
i['sources'].append('src/vs/workbench/contrib/chat/browser/widget/chatWidget.ts:4018-4036')

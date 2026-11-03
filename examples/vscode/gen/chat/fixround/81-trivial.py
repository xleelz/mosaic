C = 'src/vs/workbench/contrib/chat/'
VC = C + 'browser/voiceClient/voiceSessionController.ts'
c = get('components', 'voice-session-controller')
c['state'] = {'schema': {'type': 'object', 'properties': {k: {'type': 'boolean'} for k in ['connected', 'connecting', 'reconnecting', 'muted']} | {'voice_state': {'type': 'string'}}},
              'initial': {'connected': False, 'connecting': False, 'reconnecting': False, 'muted': False, 'voice_state': 'idle'}}
i = get('interfaces', 'agents-voice-connected-key-contribution.constructor')
V = 'src/vs/workbench/contrib/agentsVoice/browser/agentsVoice.contribution.ts'
i['behavior'] = [
  {'title': 'Read the voice session''s observables', 'source': V + ':110-115', 'call': 'voice-session-controller.get-state', 'as': 'vs'},
  {'set': {'vars.keys': "= {'agentsVoiceConnected': vars.vs.value.connected, 'agentsVoiceConnecting': vars.vs.value.connecting, 'agentsVoiceReconnecting': vars.vs.value.reconnecting, 'agentsVoiceListening': vars.vs.value.voice_state == 'listening', 'agentsVoiceMuted': vars.vs.value.muted}"}},
  {'title': 'The autorun mirrors them into the five context keys (listening is voiceState == listening)', 'source': V + ':110-116',
   'foreach': '= vars.keys.filter(k, true)', 'as': 'k',
   'steps': [{'call': 'context-key-service.set-context', 'input': {'key': '= vars.k', 'value': '= vars.keys[vars.k]'}}]},
  {'return': {'started': True}}]
cc = get('components', 'chat-context-service')
cc['state'] = {'schema': {'type': 'object', 'properties': {'providers': {'type': 'object'}}}, 'initial': {'providers': {}}}
st = get('components', 'chat-context-contribution')
st['state'] = {'schema': {'type': 'object', 'properties': {'errors': {'type': 'array'}}}, 'initial': {'errors': []}}
H = C + 'browser/contextContrib/chatContext.contribution.ts'
i = get('interfaces', 'chat-context-contribution.handle-chat-context-extension-point')
i['kind'] = 'function'
i['summary'] = 'The chatContext handler: only extensions with the chatContextProvider proposal; each contribution needs a $(codicon) icon, then becomes a context provider picker.'
i['sources'] = [H + ':21', H + ':59-81']
i['request'] = {'type': 'object', 'properties': {'extensions': {'type': 'array', 'default': [], 'items': {'type': 'object', 'properties': {
   'extension_id': {'type': 'string'}, 'proposals': {'type': 'array'}, 'contributions': {'type': 'array'}}}}}}
i['response'] = {'type': 'object', 'properties': {'handled': {'type': 'boolean'}}}
i['behavior'] = [
  {'set': {'vars.exts': '= has(input.extensions) ? input.extensions : []'}},
  {'title': 'Extensions without the chatContextProvider proposal are ignored', 'source': H + ':61-63',
   'set': {'vars.exts': "= vars.exts.filter(e, has(e.proposals) && 'chatContextProvider' in e.proposals && has(e.contributions))"}},
  {'foreach': '= vars.exts', 'as': 'e', 'steps': [
    {'foreach': '= vars.e.contributions', 'as': 'c', 'steps': [
      {'title': 'An icon that is not $(id) or $(id~spin) is an error', 'source': H + ':68-72',
       'if': "!has(vars.c.icon) || !matches(vars.c.icon, '^\\\\$\\\\([a-z0-9-]+(~spin)?\\\\)$')",
       'then': [{'set': {'state.errors': "= state.errors + ['Invalid icon format for chat context contribution ' + vars.c.id]"}}],
       'else': [{'title': 'setChatContextProvider(<extension id>-<contribution id>, {title, icon})', 'source': H + ':78',
                 'call': 'chat-context-service.set-chat-context-provider',
                 'input': {'id': "= vars.e.extension_id + '-' + vars.c.id", 'title': '= vars.c.display_name', 'icon': '= vars.c.icon'}}]}]}]},
  {'return': {'handled': True}}]

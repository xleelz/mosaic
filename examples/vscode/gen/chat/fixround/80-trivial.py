C = 'src/vs/workbench/contrib/chat/'
def st(comp, props, init):
    c = get('components', comp)
    c['state'] = {'schema': {'type': 'object', 'properties': props}, 'initial': init}

# language models: tool calling capability on the seeded Copilot models
lm = get('components', 'language-models-service')
for m in lm['state']['initial']['models'].values():
    m['tool_calling'] = True
    m['name'] = m['family']

# --- default model contributions (explore, plan, utility small)
dm_src = C + 'browser/defaultModelContribution.ts'
def default_model(comp, filt, filt_title, ctor_src, cfg):
    st(comp, {'model_ids': {'type': 'array'}}, {'model_ids': []})
    i = get('interfaces', comp + '.constructor')
    i['summary'] = (f'DefaultModelContribution for {cfg}: rebuilds the setting''s model enum from the selectable language models '
                    '(a visible vendor, user-selectable, not scoped to a session type) that pass its filter; the first entry is the vendor default ("").')
    i['sources'] = [ctor_src, dm_src + ':68-132']
    i['response'] = {'type': 'object', 'properties': {'model_ids': {'type': 'array'}}}
    i['behavior'] = [
      {'title': 'getLanguageModelIds', 'source': dm_src + ':97', 'call': 'language-models-service.get-language-model-ids', 'as': 'ids'},
      {'title': 'getVendors: the visible vendors', 'source': dm_src + ':111-112', 'call': 'language-models-service.get-vendors', 'as': 'vendors'},
      {'set': {'vars.models': []}},
      {'title': 'lookupLanguageModel for each id', 'source': dm_src + ':99-108', 'foreach': '= vars.ids.value.ids', 'as': 'mid',
       'steps': [{'call': 'language-models-service.lookup-language-model', 'input': {'model_id': '= vars.mid'}, 'as': 'md'},
                 {'if': 'vars.md.value.found', 'then': [{'set': {'vars.models': "= vars.models + [merge(vars.md.value.metadata, {'identifier': vars.mid})]"}}]}]},
      {'title': 'Keep models of a visible vendor that are user-selectable and not scoped to a session type', 'source': dm_src + ':113-126',
       'set': {'vars.ok': "= vars.models.filter(m, m.vendor in vars.vendors.value.vendors && !(has(m.is_user_selectable) && m.is_user_selectable == false) && !has(m.target_chat_session_type))"}},
      {'title': filt_title, 'source': ctor_src, 'set': {'vars.ok': '= vars.ok.filter(m, ' + filt + ')'}},
      {'title': 'The vendor default ("") first, then the supported models', 'source': dm_src + ':91-94',
       'set': {'state.model_ids': "= [''] + vars.ok.map(m, m.vendor + '/' + m.id)"}},
      {'return': {'model_ids': '= state.model_ids'}}]
default_model('explore-agent-default-model', 'has(m.tool_calling) && m.tool_calling', 'Only models capable of tool calling',
              C + 'browser/exploreAgentDefaultModel.ts:21-31', 'chat.exploreAgent.defaultModel')
default_model('plan-agent-default-model', 'has(m.tool_calling) && m.tool_calling', 'Only models capable of tool calling',
              C + 'browser/planAgentDefaultModel.ts:21-31', 'chat.planAgent.defaultModel')
default_model('utility-small-model-contribution', "m.vendor != 'copilot'", 'Copilot models are excluded (a non-Copilot small model)',
              C + 'browser/utilityModelContribution.ts:62-75', 'chat.utilitySmallModel')

# --- chat pet context key
i = get('interfaces', 'chat-pet-context-contribution.constructor')
P = C + 'browser/chatPetAchievements.contribution.ts'
i['behavior'] = [
  {'title': 'Read the pet service''s enabled observable', 'source': P + ':133-134', 'call': 'chat-pet-service.get-unlocked-achievements', 'as': 'pet'},
  {'title': 'chatPetEnabled context key mirrors it', 'source': P + ':132-134', 'call': 'context-key-service.set-context',
   'input': {'key': 'chatPetEnabled', 'value': '= vars.pet.value.enabled'}},
  {'return': {'started': True}}]

# --- voice entitlement key
i = get('interfaces', 'agents-voice-entitlement-key-contribution.constructor')
V = 'src/vs/workbench/contrib/agentsVoice/browser/agentsVoice.contribution.ts'
VS = C + 'browser/voiceClient/voiceSessionController.ts'
i['behavior'] = [
  {'call': 'chat-entitlement-service.get-entitlement', 'as': 'ent'},
  {'title': 'isVoiceEntitled: a Pro-tier user (EDU, Pro, Pro+, Max...) who is internal or not on Business/Enterprise', 'source': VS + ':73-78',
   'set': {'vars.entitled': "= vars.ent.value.entitlement in ['edu', 'pro', 'pro-plus', 'max', 'business', 'enterprise'] && (vars.ent.value.is_internal || !(vars.ent.value.entitlement in ['business', 'enterprise']))"}},
  {'title': 'agentsVoiceEntitled', 'source': V + ':84-86', 'call': 'context-key-service.set-context', 'input': {'key': 'agentsVoiceEntitled', 'value': '= vars.entitled'}},
  {'return': {'started': True}}]
ce = get('components', 'chat-entitlement-service')
ce['state']['schema']['properties']['entitlement'] = {'type': 'string'}
ce['state']['schema']['properties']['is_internal'] = {'type': 'boolean'}
ce['state']['initial']['entitlement'] = 'unknown'
ce['state']['initial']['is_internal'] = False

# --- chat participants extension point
i = get('interfaces', 'chat-extension-point-handler.handle-chat-participants-extension-point')
H = C + 'browser/chatParticipant.contribution.ts'
st('chat-extension-point-handler', {'errors': {'type': 'array'}}, {'errors': []})
i['kind'] = 'function'
i['summary'] = 'The chatParticipants handler: validates each contributed participant (name pattern, API proposals for isDefault/modes/locations, id and name) and registers it with ChatAgentService.'
i['sources'] = [H + ':106', H + ':249-330']
i['request'] = {'type': 'object', 'properties': {'added': {'type': 'array', 'default': [], 'items': {'type': 'object', 'properties': {
    'extension_id': {'type': 'string'}, 'id': {'type': 'string'}, 'name': {'type': 'string'}, 'is_default': {'type': 'boolean'},
    'modes': {'type': 'array'}, 'locations': {'type': 'array'}, 'proposals': {'type': 'array'}}}}}}
i['response'] = {'type': 'object', 'properties': {'handled': {'type': 'boolean'}, 'registered': {'type': 'integer'}}}
i['behavior'] = [
  {'set': {'vars.added': '= has(input.added) ? input.added : []', 'vars.n': 0}},
  {'foreach': '= vars.added', 'as': 'p', 'steps': [
    {'set': {'vars.props': "= has(vars.p.proposals) ? vars.p.proposals : []", 'vars.before': '= size(state.errors)'}},
    {'title': 'Invalid name', 'source': H + ':252-255', 'if': "!has(vars.p.name) || !matches(vars.p.name, '^[\\\\w-]+$')",
     'then': [{'set': {'state.errors': "= state.errors + [vars.p.extension_id + ' CANNOT register participant with invalid name']"}}],
     'else': [
       {'title': 'isDefault or modes need the defaultChatParticipant proposal; locations need chatParticipantAdditions', 'source': H + ':268-276',
        'if': "((has(vars.p.is_default) && vars.p.is_default) || has(vars.p.modes)) && !('defaultChatParticipant' in vars.props) || has(vars.p.locations) && !('chatParticipantAdditions' in vars.props)",
        'then': [{'set': {'state.errors': "= state.errors + [vars.p.extension_id + ' CANNOT use API proposal']"}}],
        'else': [
          {'title': 'registerAgent: default participants get modes ?? [ask], others all three; locations default to panel', 'source': H + ':295-319',
           'call': 'chat-agent-service.register-agent',
           'input': {'agent_id': '= vars.p.id', 'extension': '= vars.p.extension_id', 'name': '= vars.p.name',
                     'is_default': '= has(vars.p.is_default) && vars.p.is_default',
                     'locations': "= has(vars.p.locations) && size(vars.p.locations) > 0 ? vars.p.locations : ['panel']",
                     'modes': "= has(vars.p.is_default) && vars.p.is_default ? (has(vars.p.modes) ? vars.p.modes : ['ask']) : ['agent', 'ask', 'edit']"},
           'on_error': [{'title': 'A duplicate id is reported to the extension', 'source': H + ':331-333',
                         'set': {'state.errors': "= state.errors + [error.message]"}}]},
          {'if': 'size(state.errors) == vars.before', 'then': [{'set': {'vars.n': '= vars.n + 1'}}]}]}]}]},
  {'return': {'handled': True, 'registered': '= vars.n'}}]

# --- languageModelTools extension point
i = get('interfaces', 'language-model-tools-extension-point-handler.handle-language-model-tools-extension-point')
T = C + 'common/tools/languageModelToolsContribution.ts'
st('language-model-tools-extension-point-handler', {'errors': {'type': 'array'}}, {'errors': []})
i['kind'] = 'function'
i['summary'] = 'The languageModelTools handler: validates each contributed tool and registers its data (no implementation until the extension activates); tools of the product''s chat extension are internal.'
i['sources'] = [T + ':42', T + ':267-343']
i['request'] = {'type': 'object', 'properties': {'added': {'type': 'array', 'default': [], 'items': {'type': 'object', 'properties': {
    'extension_id': {'type': 'string'}, 'name': {'type': 'string'}, 'display_name': {'type': 'string'}, 'model_description': {'type': 'string'},
    'tool_reference_name': {'type': 'string'}, 'can_be_referenced_in_prompt': {'type': 'boolean'}, 'private_api': {'type': 'boolean'}}}}}}
i['response'] = {'type': 'object', 'properties': {'handled': {'type': 'boolean'}, 'registered': {'type': 'integer'}}}
bad = ("!has(vars.t.name) || !has(vars.t.model_description) || !has(vars.t.display_name) || !matches(vars.t.name, '^[\\\\w-]+$')"
       " || (has(vars.t.can_be_referenced_in_prompt) && vars.t.can_be_referenced_in_prompt && !has(vars.t.tool_reference_name))"
       " || ((vars.t.name.startsWith('copilot_') || vars.t.name.startsWith('vscode_')) && !(has(vars.t.private_api) && vars.t.private_api))")
i['behavior'] = [
  {'set': {'vars.added': '= has(input.added) ? input.added : []', 'vars.n': 0}},
  {'foreach': '= vars.added', 'as': 't', 'steps': [
    {'set': {'vars.before': '= size(state.errors)'}},
    {'title': 'Missing name/modelDescription/displayName, an invalid id, a prompt reference without toolReferenceName, or a reserved copilot_/vscode_ prefix without chatParticipantPrivate',
     'source': T + ':275-293', 'if': bad,
     'then': [{'set': {'state.errors': "= state.errors + [vars.t.extension_id + ' CANNOT register tool ' + (has(vars.t.name) ? vars.t.name : '')]"}}],
     'else': [
       {'title': 'registerToolData: internal for the product''s default chat extension, else an extension tool', 'source': T + ':318-337',
        'call': 'language-model-tools-service.register-tool',
        'input': {'tool_id': '= vars.t.name', 'reference_name': "= has(vars.t.tool_reference_name) ? vars.t.tool_reference_name : ''",
                  'source': "= vars.t.extension_id == 'GitHub.copilot-chat' ? 'internal' : 'extension'", 'server_id': '',
                  'has_impl': False, 'needs_confirmation': False},
        'on_error': [{'title': 'A failed registration is reported', 'source': T + ':340-342', 'set': {'state.errors': "= state.errors + [error.message]"}}]},
       {'if': 'size(state.errors) == vars.before', 'then': [{'set': {'vars.n': '= vars.n + 1'}}]}]}]},
  {'return': {'handled': True, 'registered': '= vars.n'}}]

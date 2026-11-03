c = get('components', 'chat-pet-service')
c['state'] = {'schema': {'type': 'object', 'properties': {'enabled': {'type': 'boolean'}, 'unlocked': {'type': 'array'}}},
              'initial': {'enabled': False, 'unlocked': []}}
c['summary'] = 'ChatPetService (IChatPetService): the pet''s enablement (application storage chat.vscodePet.enabled, default false) and its unlocked achievements (application-shared storage chat.vscodePet.achievement.<id>).'
c['sources'].append('src/vs/workbench/contrib/chat/browser/chatPetService.ts:140')

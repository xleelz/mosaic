c = get('components', 'extension-agent-plugin-discovery')
c['state'] = {'schema': {'type': 'object', 'properties': {
    'plugins': {'type': ['array', 'null']}, 'entries': {'type': 'object'}, 'discover_version': {'type': 'integer'},
    'started': {'type': 'boolean'}, 'errors': {'type': 'array'}}},
  'initial': {'plugins': None, 'entries': {}, 'discover_version': 0, 'started': False, 'errors': []}}
c['summary'] = ('Discovers agent plugins contributed by extensions (chatPlugins extension point). plugins is undefined (null) until the first '
                '_refreshPlugins completes, then the list of discovered plugin roots.')
c['sources'].append('src/vs/workbench/contrib/chat/common/plugins/agentPluginServiceImpl.ts:268-289')
i = get('interfaces', 'extension-agent-plugin-discovery.handle-chat-plugins-extension-point')
i['kind'] = 'function'
i['summary'] = ("The chatPlugins handler (installed by start): validates each added entry (a path inside the extension, a parseable when), "
                "records it by extension and path, drops removed entries and schedules a refresh.")
i['request'] = {'type': 'object', 'properties': {
    'added': {'type': 'array', 'default': [], 'items': {'type': 'object', 'properties': {'extension_id': {'type': 'string'}, 'path': {'type': 'string'}, 'when': {'type': 'string'}}},
              'examples': [[{'extension_id': 'GitHub.copilot-chat', 'path': 'plugins/review', 'when': ''}]]},
    'removed': {'type': 'array', 'default': [], 'items': {'type': 'object'}}}}
i['response'] = {'type': 'object', 'properties': {'handled': {'type': 'boolean'}, 'registered': {'type': 'integer'}}}
S = 'src/vs/workbench/contrib/chat/common/plugins/agentPluginServiceImpl.ts'
i['behavior'] = [
  {'set': {'vars.added': "= has(input.added) ? input.added : []", 'vars.removed': "= has(input.removed) ? input.removed : []"}},
  {'title': 'An entry without a path is reported to the extension and skipped', 'source': S + ':1295-1298',
   'set': {'vars.missing': "= vars.added.filter(r, !has(r.path) || r.path == '')"}},
  {'title': 'A path that resolves outside the extension is reported and skipped', 'source': S + ':1299-1303',
   'set': {'vars.outside': "= vars.added.filter(r, has(r.path) && r.path != '' && (r.path.startsWith('..') || r.path.startsWith('/') || r.path.contains('/../')))"}},
  {'set': {'vars.ok': "= vars.added.filter(r, has(r.path) && r.path != '' && !(r.path.startsWith('..') || r.path.startsWith('/') || r.path.contains('/../')))"}},
  {'if': 'size(vars.missing) + size(vars.outside) > 0',
   'then': [{'set': {'state.errors': "= state.errors + vars.missing.map(r, r.extension_id + ': missing path') + vars.outside.map(r, r.extension_id + ': ' + r.path + ' resolves outside the extension')"}}]},
  {'title': 'Drop the removed extensions\' entries', 'source': S + ':1315-1318', 'foreach': '= vars.removed', 'as': 'rm',
   'steps': [{'set': {'state.entries': "= omit(state.entries, vars.rm.extension_id + '/' + vars.rm.path)"}}]},
  {'title': 'Record the valid entries by extension and path', 'source': S + ':1312',
   'set': {'state.entries': "= merge(state.entries, vars.ok.transformMapEntry(j, r, {r.extension_id + '/' + r.path: {'extension_id': r.extension_id, 'path': r.path, 'when': has(r.when) ? r.when : ''}}))"}},
  {'title': 'Rebuild the when keys and schedule the refresh', 'source': S + ':1320-1321',
   'emit': 'extension-agent-plugin-discovery.refresh-plugins', 'after_ms': 0, 'input': {}},
  {'return': {'handled': True, 'registered': '= size(vars.ok)'}}]
i['sources'] = [S + ':1239', S + ':1292-1322']

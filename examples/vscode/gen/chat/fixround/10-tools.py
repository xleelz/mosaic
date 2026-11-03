c = get('components', 'language-model-tools-service')
c['state']['schema']['properties']['calls_by_request'] = {'type': 'object'}
c['state']['schema']['properties']['tools_changed'] = {'type': 'boolean'}
c['state']['initial']['calls_by_request'] = {}
c['state']['initial']['tools_changed'] = False

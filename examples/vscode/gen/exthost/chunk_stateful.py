# ---- decision 12: stateful MainThread classes (SCM, terminal, quick open, comments) are modeled, not skipped
STATEFUL = {'MainThreadSCMShape': 'main-thread-scm', 'MainThreadTerminalServiceShape': 'main-thread-terminal-service',
            'MainThreadQuickOpenShape': 'main-thread-quick-open', 'MainThreadCommentsShape': 'main-thread-comments'}
cust_line = {kebab(e['name']): (e['file'], e['line']) for e in mine if e['kind'] == 'exthost-customer'}
def snake(n): return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', n).lower()
stateful_steps = {c: [] for c in STATEFUL.values()}
for e in mine:
    if e['kind'] != 'exthost-rpc': continue
    shape, meth = e['name'].split('.', 1)
    if shape not in STATEFUL: continue
    comp = STATEFUL[shape]; nm = kebab(meth[1:])
    if any(i['component'] == comp and i['name'] == nm for i in ifaces): continue
    f, cl = cust_line[comp]
    s = open(ROOT + f).read()
    off = len('\n'.join(s.split('\n')[:cl - 1]))
    m = re.search(r'\n\t(?:public |async |override )*%s\s*(?:<[^(\n]*>)?\(([^)]*)\)' % re.escape(meth), s[off:])
    ln = s[:off + m.start()].count('\n') + 2
    params = []
    for p in re.sub(r'\s+', ' ', m.group(1)).split(','):
        mm = re.match(r'\s*(?:\.\.\.)?(\w+)\??\s*:\s*(.+)$', p)
        if mm: params.append((snake(mm.group(1)).lstrip('_'), mm.group(2).strip()))
    props = {}
    for n, t in params:
        props[n] = {'type': 'integer', 'examples': [1]} if t.startswith('number') or t == 'ExtHostTerminalIdentifier' else ({'type': 'string'} if t.startswith('string') else ({'type': 'boolean'} if t == 'boolean' else {}))
        props[n]['description'] = t[:80]
    key = params[0][0] if params and props[params[0][0]].get('type') == 'integer' else None
    src = [f"src/vs/workbench/api/common/extHost.protocol.ts:{e['line']}", f"{f}:{ln}"]
    low = meth[1:]
    if key and (low.startswith('register') or low.startswith('create')):
        beh = [{'title': f'{meth}: keep the object for {key}', 'source': src[1], 'set': {'state.handles': f"= string(input.{key}) in state.handles ? state.handles : state.handles + [string(input.{key})]"}},
               {'return': {'handle': f'= input.{key}'}}]
        kind = 'add'
    elif key and (low.startswith('unregister') or low.startswith('dispose') or low.startswith('delete')):
        beh = [{'title': f'{meth}: dispose and forget the object for {key}', 'source': src[1], 'set': {'state.handles': f"= state.handles.filter(h, h != string(input.{key}))"}},
               {'return': {'handle': f'= input.{key}'}}]
        kind = 'remove'
    elif key:
        beh = [{'if': f"!(string(input.{key}) in state.handles)", 'then': [{'title': f'No object for {key}; nothing to update', 'source': src[1], 'return': {'ignored': True}}]},
               {'return': {'ignored': False}}]
        kind = 'use'
    elif low.startswith('start') or low.startswith('stop'):
        flag = re.sub(r'^(start|stop)', '', low)
        beh = [{'title': f'{meth}: toggle forwarding of {flag}', 'source': src[1], 'set': {'state.flags': f"= merge(state.flags, {{'{snake(flag)}': {str(low.startswith('start')).lower()}}})"}},
               {'return': {'ignored': False}}]
        kind = 'flag'
    else:
        beh = [{'title': f'{meth}: update the customer-held state from the payload', 'source': src[1], 'set': {'state.updates': '= state.updates + 1'}}, {'return': {'ignored': False}}]
        kind = 'update'
    ifaces.append({'component': comp, 'name': nm, 'kind': 'rpc', 'attributes': {'shape': shape},
                   'summary': f"{meth}: stateful customer method (keeps per-handle objects in {byid[comp]['name']}); unknown handles are ignored in the model.",
                   'sources': src, 'request': {'type': 'object', 'properties': props}, 'response': {'type': 'object', 'properties': {'ignored': {'type': 'boolean'}, 'handle': {}}},
                   'behavior': beh})
    stateful_steps[comp].append((nm, key, kind))
for comp in STATEFUL.values():
    add_comp(comp, state={'schema': {'type': 'object', 'properties': {'handles': {'type': 'array', 'items': {'type': 'string'}}, 'flags': {'type': 'object'}, 'updates': {'type': 'integer'}}},
                          'initial': {'handles': [], 'flags': {}, 'updates': 0}})

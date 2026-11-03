from builder import Part, call, ret, iff, choice, sets, note, called

SPEC = {
    'call': dict(dir='callHierarchy', Cls='CallHierarchy', feature='call-hierarchy', prep_rpc='prepare-call-hierarchy',
                 contrib='call-hierarchy-contribution', common='call-hierarchy-common',
                 ctl_line=40, start='80-98', model_line=65, create='67-77', resolve_a=('incoming', '103-113'), resolve_b=('outgoing', '115-125'),
                 show=('editor.showCallHierarchy', 177, '206-208'), a=('editor.showIncomingCalls', 211, '231-233', '163-166', 'callsTo'),
                 b=('editor.showOutgoingCalls', 236, '256-258', '158-161', 'callsFrom'), reg=175,
                 api=[('_executePrepareCallHierarchy', 132, '132-165'), ('_executeProvideIncomingCalls', 171, '171-182'), ('_executeProvideOutgoingCalls', 184, '184-195')]),
    'type': dict(dir='typeHierarchy', Cls='TypeHierarchy', feature='type-hierarchy', prep_rpc='prepare-type-hierarchy',
                 contrib='type-hierarchy-contribution', common='type-hierarchy-common',
                 ctl_line=39, start='77-95', model_line=53, create='55-65', resolve_a=('supertypes', '91-101'), resolve_b=('subtypes', '103-113'),
                 show=('editor.showTypeHierarchy', 175, '198-200'), a=('editor.showSupertypes', 204, '224-226', '155-158', 'supertypes'),
                 b=('editor.showSubtypes', 229, '249-251', '160-163', 'subtypes'), reg=172,
                 api=[('_executePrepareTypeHierarchy', 120, '120-153'), ('_executeProvideSupertypes', 169, '169-180'), ('_executeProvideSubtypes', 182, '182-193')]),
}


def build():
    p = Part('hierarchy')
    ordered = p.stub('language-features-service.ordered', 'editor')
    set_ctx = p.stub('context-key-service.set-context', 'platform-core')
    for kind, s in SPEC.items():
        B = f"{s['dir']}/browser/{s['dir']}.contribution.ts"
        Cm = f"{s['dir']}/common/{s['dir']}.ts"
        prep = p.stub(f"ext-host-language-features.{s['prep_rpc']}", 'exthost',
                      {'type': 'object', 'properties': {'handle': {'type': 'integer'}, 'resource': {'type': 'string'}, 'line': {'type': 'integer'}}}, kind='rpc')
        res_a = p.stub(f"ext-host-language-features.provide-{s['resolve_a'][0]}" if kind == 'type' else f"ext-host-language-features.provide-{s['resolve_a'][0]}-calls", 'exthost',
                       {'type': 'object', 'properties': {'handle': {'type': 'integer'}, 'session_id': {'type': 'string'}}}, kind='rpc')
        res_b = p.stub(f"ext-host-language-features.provide-{s['resolve_b'][0]}" if kind == 'type' else f"ext-host-language-features.provide-{s['resolve_b'][0]}-calls", 'exthost',
                       {'type': 'object', 'properties': {'handle': {'type': 'integer'}, 'session_id': {'type': 'string'}}}, kind='rpc')
        mid = f"{kind}-hierarchy-model"
        p.comp(mid, f"{s['Cls']}Model", s['common'], [f"{Cm}:{s['model_line']}"],
               f'Sessions of {kind} hierarchy: the first provider for the model prepares the roots; sessions are kept by id for the API commands.',
               state={'schema': {'type': 'object'}, 'initial': {'sessions': {}}})
        create = p.iface(mid, 'create', 'Uses the first registered provider for the document; no provider or no session gives undefined.', [f"{Cm}:{s['create']}"],
                         [call(ordered, {'feature': s['feature'], 'language_id': 'typescript'}, as_='o', source=f"{Cm}:{s['create'].split('-')[0]}"),
                          iff('size(vars.o.value.providers) == 0', [ret({'id': None})], title='No provider for the model', source=f"{Cm}:{int(s['create'].split('-')[0]) + 2}"),
                          call(prep, {'handle': '= vars.o.value.providers[0].handle', 'resource': '= input.resource', 'line': '= input.line'}, on='eh1', title='provider.prepare (extension host)'),
                          sets({'vars.id': "= 'session-' + string(size(state.sessions) + 1)"}),
                          sets({'state.sessions': "= merge(state.sessions, {vars.id: {'handle': vars.o.value.providers[0].handle, 'resource': input.resource, 'line': input.line}})"}),
                          ret({'id': '= vars.id'})],
                         request={'type': 'object', 'properties': {'resource': {'type': 'string', 'default': 'file:///work/app/src/main.ts'}, 'line': {'type': 'integer', 'default': 1}}})
        resolve = p.iface(mid, f"resolve", f'Resolves {s["resolve_a"][0]}/{s["resolve_b"][0]} of an item through its session\'s provider; unknown sessions give [].',
                          [f"{Cm}:{s['resolve_a'][1]}", f"{Cm}:{s['resolve_b'][1]}"],
                          [iff('!(input.session_id in state.sessions)', [ret({'items': []})], title='Unknown session: []'),
                           iff(f"input.direction == '{s['resolve_a'][0]}'", [call(res_a, {'handle': '= state.sessions[input.session_id].handle', 'session_id': '= input.session_id'}, on='eh1')],
                               [call(res_b, {'handle': '= state.sessions[input.session_id].handle', 'session_id': '= input.session_id'}, on='eh1')]),
                           ret({'resolved': '= input.direction'})],
                          request={'type': 'object', 'properties': {'session_id': {'type': 'string', 'default': 'session-1'}, 'direction': {'type': 'string', 'default': s['resolve_a'][0]}}})
        ctl = p.comp(f"{kind}-hierarchy-controller", f"{s['Cls']}Controller", s['contrib'], [f"{B}:{s['ctl_line']}"],
                     f'Editor contribution: shows the {kind} hierarchy peek widget and tracks its direction context key.',
                     state={'schema': {'type': 'object'}, 'initial': {'visible': False, 'direction': s['a'][4]}})
        start = p.iface(ctl, 'start-from-editor', 'Creates a model at the cursor and shows the peek widget in the stored direction; nothing without a provider.', [f"{B}:{s['start']}"],
                        [call(create, {'resource': 'file:///work/app/src/main.ts', 'line': 1}, as_='m', source=f"{B}:{s['start'].split('-')[0]}"),
                         iff('vars.m.value.id == null', [ret({'shown': False})], title='No provider for the document'),
                         sets({'state.visible': True, 'state.session': '= vars.m.value.id'}), ret({'shown': True, 'session': '= vars.m.value.id'})])
        p.iface(ctl, 'constructor', 'Created eagerly per editor so it can bind its visibility and direction context keys.', [f"{B}:{s['reg']}"],
                [call(set_ctx, {'key': f"{kind}HierarchyVisible", 'value': False}), ret({'created': True})])
        p.scenario_for(f'{ctl}.constructor', {'id': f'{kind}-controller-created', 'caller': 'editor', 'expect': [called(set_ctx, f"e.input.key == '{kind}HierarchyVisible'")]})
        pre_reg = {'interface': f"main-thread-language-features.register-{kind}-hierarchy-provider", 'caller': 'exthost-bridge',
                   'input': {'handle': 9, 'selector': 'typescript', 'extension_id': 'vscode.typescript-language-features'}}
        ed = ['editor-main-open', 'workbench-contribs-seed']
        cid, line, h = s['show']
        p.cmd(s['contrib'], cid, f'{B}:{line}', f'{B}:{h}', f'Peek {s["Cls"]} at the cursor.',
              [call(start, {}, as_='r', source=f"{B}:{int(h.split('-')[0]) + 1}"), ret('= vars.r.value')],
              scen=[{'fixtures': ed, 'pre': [pre_reg], 'expect': ['steps.s.result.value.shown', called(prep), f"state['{ctl}@w1'].visible"]},
                    {'id': f'{kind}-hierarchy-no-provider', 'fixtures': ed, 'expect': ['!steps.s.result.value.shown', '!' + called(prep)]}])
        for cid, line, h, mline, dval in (s['a'], s['b']):
            p.cmd(s['contrib'], cid, f'{B}:{line}', [f'{B}:{h}', f'{B}:{mline}'], f'Switch the open {kind} hierarchy to {dval}.',
                  [sets({'state.direction': dval}, title='widget.updateDirection and the direction context key', source=f'{B}:{mline}'),
                   call(set_ctx, {'key': f"{kind}HierarchyDirection", 'value': dval}), ret({'direction': dval})],
                  scen=[{'expect': [f"state['{s['contrib']}@w1'].direction == '{dval}'", called(set_ctx, f"e.input.value == '{dval}'")]}])
        # API commands
        (pc, pl, ph), (ac, al, ah), (bc, bl, bh) = s['api']
        p.cmd(s['common'], pc, f'{Cm}:{pl}', f'{Cm}:{ph}', f'API ({kind} hierarchy prepare): resolves the model (loading it if needed), creates a session and returns its root.',
              [call(create, {'resource': '= input.resource', 'line': '= input.line'}, as_='m', source=f'{Cm}:{int(ph.split("-")[0]) + 15}'),
               iff('vars.m.value.id == null', [ret({'roots': []})]), ret({'roots': [{'session_id': '= vars.m.value.id'}]})],
              request={'type': 'object', 'properties': {'resource': {'type': 'string', 'default': 'file:///work/app/src/main.ts'}, 'line': {'type': 'integer', 'default': 1}}},
              scen=[{'fixtures': ed, 'pre': [pre_reg], 'caller': 'exthost-bridge', 'expect': ["steps.s.result.value.roots[0].session_id == 'session-1'", f"'session-1' in state['{mid}@w1'].sessions"]}])
        for cid, l, h, d in ((ac, al, ah, s['resolve_a'][0]), (bc, bl, bh, s['resolve_b'][0])):
            p.cmd(s['common'], cid, f'{Cm}:{l}', f'{Cm}:{h}', f'API: {d} of an item of a prepared session ([] for an unknown session).',
                  [call(resolve, {'session_id': '= input.session_id', 'direction': d}, as_='r', source=f'{Cm}:{int(h.split("-")[0]) + 5}'), ret('= vars.r.value')],
                  request={'type': 'object', 'properties': {'session_id': {'type': 'string', 'default': 'session-1'}}},
                  scen=[{'fixtures': ed, 'caller': 'exthost-bridge',
                         'pre': [pre_reg, {'interface': f'{s["common"]}.cmd-{pc.lower().replace("_", "-").strip("-")}', 'caller': 'exthost-bridge', 'input': {}}],
                         'expect': [f"steps.s.result.value.resolved == '{d}'"]},
                        {'id': f'{cid.lower().strip("_")}-unknown', 'caller': 'exthost-bridge', 'input': {'session_id': 'nope'}, 'expect': ['size(steps.s.result.value.items) == 0']}])
    return p

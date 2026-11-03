from builder import Part, call, ret, iff, sets, called

# Integrated browser: open / new tab (oracle editing #5, browserNavigationFeatures.test.ts:25).
TM = 'browserView/electron-browser/features/browserTabManagementFeatures.ts'
NAV = 'browserView/electron-browser/features/browserNavigationFeatures.ts'
URLBAR = 'browserView/electron-browser/widgets/browserUrlBarWidget.ts'
WBS = 'browserView/electron-browser/browserViewWorkbenchService.ts'
BV = 'browserView/common/browserView.ts'
PICKER = 'browser-view-browser-navigation-features-native.open-url-picker'


def build():
    p = Part('browser')
    ws = 'workbench-shell'
    open_editor = p.stub('editor-service.open-editor', ws)
    p.configs.append({'id': 'workbench-browser-new-tab-placement', 'type': 'string', 'value': 'activeGroup', 'default': 'activeGroup',
                      'summary': 'workbench.browser.newTabPlacement: where new Integrated Browser tabs open (activeGroup, sideGroup, window).',
                      'sources': [f'src/vs/workbench/contrib/{TM}:944-958'], 'attributes': {'key': 'workbench.browser.newTabPlacement'}})

    svc = 'browser-view-workbench-service'
    p.seed[svc] = {'next_id': 1, 'views': {}}
    pref = p.iface(svc, 'get-preferred-group',
                   'IBrowserViewWorkbenchService.getPreferredGroup: open-to-side goes to the dedicated side group; otherwise workbench.browser.newTabPlacement '
                   'sideGroup or window picks the dedicated (locked) group; else the active group. SIDE_GROUP is -2, ACTIVE_GROUP -1.',
                   [f'{BV}:218', f'{WBS}:324-349', f'{WBS}:357-380'],
                   [iff('has(input.open_to_side) && input.open_to_side', [ret({'group': -2, 'dedicated': 'sideGroup'})], title='"Open to side" is routed into the dedicated side group', source=f'{WBS}:326-328'),
                    sets({'vars.placement': "= config['workbench-browser-new-tab-placement']"}, source=f'{WBS}:336'),
                    iff("vars.placement == 'sideGroup' || vars.placement == 'window'",
                        [ret({'group': "= vars.placement == 'sideGroup' ? -2 : -1", 'dedicated': '= vars.placement'})],
                        title='_getOrCreateDedicatedGroup: reuse or create a locked group (side) or auxiliary window', source=f'{WBS}:337-339'),
                    ret({'group': -1, 'dedicated': ''})],
                   request={'type': 'object', 'properties': {'open_to_side': {'type': 'boolean', 'default': False}}},
                   response={'type': 'object', 'properties': {'group': {'type': 'integer'}, 'dedicated': {'type': 'string'}}})
    track = p.iface(svc, 'track-view', 'A browser editor input for a new view id (BrowserViewUri.forId(generateUuid())): records its URL so contextual views can be matched later.',
                    ['browserView/common/browserEditorInput.ts:265-267', 'src/vs/platform/browserView/common/browserViewUri.ts:19-21'],
                    [sets({'vars.resource': "= 'vscode-browser:/view-' + string(state.next_id)"}, title='BrowserViewUri.forId(id)'),
                     sets({'state.next_id': '= state.next_id + 1', 'state.views': '= merge(state.views, {vars.resource: {\'url\': input.url}})'}),
                     ret({'resource': '= vars.resource'})],
                    request={'type': 'object', 'properties': {'url': {'type': 'string', 'default': ''}}},
                    response={'type': 'object', 'properties': {'resource': {'type': 'string'}}})

    nav = 'browser-view-browser-navigation-features-native'
    p.iface(nav, 'open-url-picker', 'BrowserNavigationFeatures.openUrlPicker -> BrowserUrlBarWidget.openUrlPicker: a read-only view only focuses the URL input; otherwise the URL quick pick opens over the URL bar.',
            [f'{NAV}:305-307', f'{URLBAR}:183-189'],
            [iff('has(input.readonly) && input.readonly', [sets({'state.focused_url_input': '= input.resource'}), ret({'picker': False})], source=f'{URLBAR}:184-187'),
             sets({'state.picker_open': '= input.resource'}, title='_openPicker()', source=f'{URLBAR}:188'),
             ret({'picker': True})],
            request={'type': 'object', 'properties': {'resource': {'type': 'string'}, 'readonly': {'type': 'boolean', 'default': False}}})

    tm = 'browser-view-browser-tab-management-features-native'
    # url from a string argument or IOpenBrowserOptions; direct callers may pass url/open_to_side
    arg0 = "(has(input.args) && size(input.args) > 0 ? input.args[0] : null)"
    p.cmd(tm, 'workbench.action.browser.open', f'{TM}:557', f'{TM}:289-346',
          'Open Integrated Browser: string or {url, openToSide, reuseUrlFilter}; reuses a contextual view matching the filter, else opens a new browser editor in the preferred group '
          '(locked when opened to the side); without a URL the URL picker opens.',
          [sets({'vars.a': f'= {arg0}'}, title='Parse arguments', source=f'{TM}:295'),
           sets({'vars.o': "= vars.a == null ? {} : (type(vars.a) == string ? {'url': vars.a} : vars.a)"}),
           sets({'vars.url': "= has(vars.o.url) ? vars.o.url : ''", 'vars.side': '= has(vars.o.openToSide) && vars.o.openToSide'}),
           call(pref, {'open_to_side': '= vars.side'}, as_='g', source=f'{TM}:297'),
           iff("has(vars.o.reuseUrlFilter) && vars.o.reuseUrlFilter != ''",
               [call(f'{svc}.find-contextual-view', {'filter': '= vars.o.reuseUrlFilter'}, as_='m', source=f'{TM}:298-325'),
                iff('vars.m.value.found',
                    [iff("vars.url != ''", [call(f'{svc}.navigate', {'resource': '= vars.m.value.resource', 'url': '= vars.url'}, source=f'{TM}:324-326')]),
                     call(open_editor, {'resource': '= vars.m.value.resource'}, title='Reveal the existing tab where it lives', source=f'{TM}:330'),
                     ret({'resource': '= vars.m.value.resource', 'reused': True, 'picker': False})])],
               source=f'{TM}:298'),
           call(track, {'url': '= vars.url'}, as_='v', source=f'{TM}:296'),
           call(open_editor, {'resource': '= vars.v.value.resource', 'group': '= vars.g.value.group'}, as_='e', source=f'{TM}:337'),
           iff("vars.url == ''", [call(PICKER, {'resource': '= vars.v.value.resource'}, source=f'{TM}:343-345')], title='No URL: open the URL picker', source=f'{TM}:343'),
           ret({'resource': '= vars.v.value.resource', 'reused': False, 'locked': "= vars.side", 'picker': "= vars.url == ''"})],
          request={'type': 'object', 'properties': {'args': {'type': 'array', 'items': {}, 'default': []}}},
          scen=[{'id': 'browser-open-no-url', 'expect': [called(PICKER), called(open_editor, "e.input.resource.startsWith('vscode-browser:/')")]},
                {'id': 'browser-open-with-url', 'input': {'args': ['https://example.com']}, 'expect': ['!' + called(PICKER), "state['browser-view-workbench-service@w1'].views['vscode-browser:/view-1'].url == 'https://example.com'"]},
                {'id': 'browser-open-to-side', 'input': {'args': [{'url': 'http://localhost:3000', 'openToSide': True}]},
                 'expect': ['steps.s.result.value.locked', called(open_editor, 'e.input.group == -2')]},
                {'id': 'browser-open-reuse', 'state': {'browser-view-workbench-service@w1': {'next_id': 2, 'views': {'vscode-browser:/view-1': {'url': 'http://localhost:3000/app'}}}},
                 'input': {'args': [{'url': 'http://localhost:3000/app?x=1', 'reuseUrlFilter': 'http://localhost:3000/*'}]},
                 'expect': ['steps.s.result.value.reused', "state['browser-view-workbench-service@w1'].views['vscode-browser:/view-1'].url == 'http://localhost:3000/app?x=1'",
                            "state['browser-view-workbench-service@w1'].next_id == 2"]}])
    p.cmd(tm, 'workbench.action.browser.newTab', f'{TM}:560', f'{TM}:426-438',
          'New Tab (Ctrl/Cmd+T in a browser editor): opens a blank browser editor in the preferred group and always opens the URL picker.',
          [call(pref, {}, as_='g', source=f'{TM}:434'),
           call(track, {'url': ''}, as_='v', source=f'{TM}:430'),
           call(open_editor, {'resource': '= vars.v.value.resource', 'group': '= vars.g.value.group'}, source=f'{TM}:434'),
           call(PICKER, {'resource': '= vars.v.value.resource'}, source=f'{TM}:435-437'),
           ret({'resource': '= vars.v.value.resource', 'picker': True})],
          request={'type': 'object', 'properties': {'args': {'type': 'array', 'items': {}, 'default': []}}},
          scen=[{'id': 'browser-new-tab', 'expect': [called(PICKER), "state['browser-view-browser-navigation-features-native@w1'].picker_open == 'vscode-browser:/view-1'"]},
                {'id': 'browser-new-tab-side-placement', 'config': {'workbench-browser-new-tab-placement': 'sideGroup'}, 'expect': [called(open_editor, 'e.input.group == -2')]}])
    p.iface(svc, 'find-contextual-view',
            'The first contextual browser view whose URL matches the reuse filter (glob on scheme, authority and path; "*" is read as any run of characters).',
            [f'{TM}:298-321'],
            [sets({'vars.re': "= '^' + input.filter.replace('.', '\\\\.').replace('?', '\\\\?').replace('*', '.*')"}, title='match(filter, url) per URI part', source=f'{TM}:300-318'),
             sets({'vars.hits': '= state.views.filter(k, state.views[k].url.matches(vars.re))'}),
             iff('size(vars.hits) == 0', [ret({'found': False})], source=f'{TM}:323'),
             ret({'found': True, 'resource': '= vars.hits[0]'})],
            request={'type': 'object', 'required': ['filter'], 'properties': {'filter': {'type': 'string'}}})
    p.iface(svc, 'navigate', 'BrowserEditorInput.navigate(url) on a reused view.', [f'{TM}:324-326'],
            [iff('!(input.resource in state.views)', [ret({'navigated': False})]),
             sets({'state.views': "= merge(state.views, {input.resource: {'url': input.url}})"}), ret({'navigated': True})],
            request={'type': 'object', 'properties': {'resource': {'type': 'string'}, 'url': {'type': 'string'}}})
    return p

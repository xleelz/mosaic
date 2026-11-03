from builder import Part, call, ret, iff, choice, sets, note, called

TH = 'themes/browser/themes.contribution.ts'
THF = 'src/vs/workbench/contrib/' + TH
TC = 'src/vs/workbench/services/themes/common/themeConfiguration.ts'


def build():
    p = Part('themes')
    ws = 'workbench-shell'
    set_color = p.stub('workbench-theme-service.set-color-theme', ws, {'type': 'object', 'properties': {'theme_id': {'type': 'string'}, 'settings_target': {'type': 'string'}}})
    set_icon = p.stub('workbench-theme-service.set-file-icon-theme', ws, {'type': 'object', 'properties': {'theme_id': {'type': 'string'}, 'settings_target': {'type': 'string'}}})
    set_prod = p.stub('workbench-theme-service.set-product-icon-theme', ws, {'type': 'object', 'properties': {'theme_id': {'type': 'string'}, 'settings_target': {'type': 'string'}}})
    get_color = p.stub('workbench-theme-service.get-color-theme', ws, response={'type': 'object', 'properties': {'id': {'type': 'string', 'default': 'Dark 2026'}, 'type': {'type': 'string', 'default': 'dark'}}})
    update = p.stub('configuration-service.update-value', 'platform-core')
    prompt = p.stub('notification-service.prompt', ws)
    open_user = p.stub('preferences-service.open-user-settings', ws, {'type': 'object', 'properties': {'query': {'type': 'string'}}})
    open_editor = p.stub('editor-service.open-editor', ws)
    p.configs += [
        {'id': 'window-auto-detect-color-scheme', 'type': 'boolean', 'value': False, 'default': False,
         'summary': 'window.autoDetectColorScheme: follow the OS light/dark mode. Registered by the theme service (workbench-shell path); read here to refuse Toggle Light/Dark.',
         'sources': [f'{TC}:85-88', f'{THF}:805'], 'attributes': {'key': 'window.autoDetectColorScheme'}},
        {'id': 'workbench-preferred-dark-color-theme', 'type': 'string', 'value': 'Dark 2026', 'default': 'Dark 2026',
         'summary': 'workbench.preferredDarkColorTheme.', 'sources': [f'{TC}:45-48', f'{THF}:835'], 'attributes': {'key': 'workbench.preferredDarkColorTheme'}},
        {'id': 'workbench-preferred-light-color-theme', 'type': 'string', 'value': 'Light 2026', 'default': 'Light 2026',
         'summary': 'workbench.preferredLightColorTheme.', 'sources': [f'{TC}:55-58', f'{THF}:835'], 'attributes': {'key': 'workbench.preferredLightColorTheme'}},
        {'id': 'extensions-gallery', 'type': 'string', 'value': '', 'default': '',
         'summary': 'product.json extensionsGallery.serviceUrl. The OSS product.json has none, so IExtensionGalleryService.isEnabled() is false and marketplace theme browsing returns at once.',
         'sources': [f'{THF}:866-868'], 'attributes': {'key': 'extensionsGallery', 'origin': 'product.json'}},
    ]
    tc = 'themes-contribution'

    def picker(kind, setter, line_set, accept_id, line_pick):
        return [choice('pick', 'accept', {
            'accept': [call(setter, {'theme_id': accept_id, 'settings_target': 'auto'}, title='Accepted: apply and write the setting (InstalledThemesPicker)', source=f'{TH}:354-372'),
                       ret({'applied': accept_id})],
            'dismissed': [call(setter, {'theme_id': '= input.current', 'settings_target': 'preview'}, title='Hidden without accepting: restore the current theme', source=f'{TH}:376-380'),
                          ret({'applied': None})]}, title=f'{kind} quick pick (selection previews after a delay)', source=f'{TH}:{line_pick}')]
    cur = {'type': 'object', 'properties': {'current': {'type': 'string', 'default': 'Dark 2026'}}}
    p.cmd(tc, 'workbench.action.selectTheme', f'{TH}:407', f'{TH}:433-490', 'Color Theme: quick pick of installed (and marketplace) color themes; accepting applies it and writes workbench.colorTheme.',
          picker('Color theme', set_color, 458, 'Light 2026', '309-390'), request=cur,
          scen=[{'expect': ["steps.s.result.value.applied == 'Light 2026'", called(set_color, "e.input.theme_id == 'Light 2026' && e.input.settings_target == 'auto'")]},
                {'id': 'select-theme-dismissed', 'choices': {'themes-contribution.cmd-workbench-action-selecttheme.pick': 'dismissed'},
                 'expect': [called(set_color, "e.input.theme_id == 'Dark 2026' && e.input.settings_target == 'preview'")]}])
    p.cmd(tc, 'workbench.action.selectIconTheme', f'{TH}:492', f'{TH}:503-524', 'File Icon Theme: quick pick including None; accepting writes workbench.iconTheme.',
          picker('File icon theme', set_icon, 511, 'vs-minimal', '523'), request={'type': 'object', 'properties': {'current': {'type': 'string', 'default': 'vs-seti'}}},
          scen=[{'expect': [called(set_icon, "e.input.theme_id == 'vs-minimal'")]}])
    p.cmd(tc, 'workbench.action.selectProductIconTheme', f'{TH}:529', f'{TH}:540-562', 'Product Icon Theme: quick pick including Default; accepting writes workbench.productIconTheme.',
          picker('Product icon theme', set_prod, 549, 'Default', '561'), request={'type': 'object', 'properties': {'current': {'type': 'string', 'default': 'Default'}}},
          scen=[{'expect': [called(set_prod, "e.input.theme_id == 'Default'")]}])
    p.cmd(tc, 'workbench.action.tryNewDefaultThemes', f'{TH}:565', f'{TH}:574-646', 'Try the new default themes: preview each, accepting applies it and resets the preferred light/dark themes to the new defaults; cancel restores the previous theme.',
          [call(get_color, {}, as_='prev', source=f'{TH}:579'),
           choice('pick', 'accept', {
               'accept': [call(set_color, {'theme_id': 'Light 2026', 'settings_target': 'auto'}, source=f'{TH}:623'),
                          call(update, {'key': 'workbench.preferredLightColorTheme', 'value': 'Light 2026', 'target': 'user'}, source=f'{TH}:624'),
                          call(update, {'key': 'workbench.preferredDarkColorTheme', 'value': 'Dark 2026', 'target': 'user'}, source=f'{TH}:625'),
                          ret({'applied': 'Light 2026'})],
               'dismissed': [call(set_color, {'theme_id': '= vars.prev.value.id'}, title='No selection: restore the previous theme', source=f'{TH}:636-637'), ret({'applied': None})]})],
          scen=[{'expect': [called(update, "e.input.key == 'workbench.preferredLightColorTheme'"), called(update, "e.input.key == 'workbench.preferredDarkColorTheme'")]},
                {'id': 'try-new-default-themes-dismissed', 'choices': {'themes-contribution.cmd-workbench-action-trynewdefaultthemes.pick': 'dismissed'}, 'expect': ['!' + called(update)]}])
    p.cmd(tc, 'workbench.action.previewColorTheme', f'{TH}:649', f'{TH}:649-663', 'Preview a theme of an extension (used by the extension editor): previews the built-in or marketplace theme and returns its settings id.',
          [call(set_color, {'theme_id': '= input.theme_settings_id', 'settings_target': 'preview'}, source=f'{TH}:658'), ret({'settings_id': '= input.theme_settings_id'})],
          request={'type': 'object', 'properties': {'theme_settings_id': {'type': 'string', 'default': 'Solarized Light'}}},
          scen=[{'expect': ["steps.s.result.value.settings_id == 'Solarized Light'", called(set_color, "e.input.settings_target == 'preview'")]}])
    p.cmd(tc, 'workbench.action.generateColorTheme', f'{TH}:735', f'{TH}:745-783', 'Developer: Generate Color Theme From Current Settings: opens an untitled JSONC editor with the current colors and token rules.',
          [call(get_color, {}, as_='t', source=f'{TH}:748'),
           call(open_editor, {'resource': 'untitled:Untitled-1', 'options': {'pinned': True}}, title='openEditor({resource: undefined, contents, languageId: jsonc})', source=f'{TH}:782'),
           ret({'generated_from': '= vars.t.value.id'})],
          scen=[{'expect': [called(open_editor, 'e.input.options.pinned')]}])
    p.cmd(tc, 'workbench.action.toggleLightDarkThemes', f'{TH}:788', f'{TH}:799-843', 'Toggle between the preferred light and dark themes; refused (with an Open Settings prompt) while window.autoDetectColorScheme is on.',
          [iff("config['window-auto-detect-color-scheme']",
               [call(prompt, {'severity': 'info', 'message': 'Cannot toggle between light and dark themes when `window.autoDetectColorScheme` is enabled in settings.', 'choices': ['Open Settings']}, source=f'{TH}:806-814'),
                ret({'toggled': False})], source=f'{TH}:805'),
           call(get_color, {}, as_='t', source=f'{TH}:818'),
           sets({'vars.target': "= vars.t.value.type == 'light' ? config['workbench-preferred-dark-color-theme'] : config['workbench-preferred-light-color-theme']"}, title='Light -> preferred dark, dark -> preferred light (HC likewise)', source=f'{TH}:819-835'),
           call(set_color, {'theme_id': '= vars.target', 'settings_target': 'auto'}, source=f'{TH}:837-841'), ret({'toggled': True, 'theme': '= vars.target'})],
          scen=[{'expect': ["steps.s.result.value.theme == 'Light 2026'", called(set_color, "e.input.theme_id == 'Light 2026'")]},
                {'id': 'toggle-light-dark-auto-detect', 'config': {'window-auto-detect-color-scheme': True}, 'expect': [called(prompt), '!' + called(set_color)]}])
    p.cmd(tc, 'workbench.action.browseColorThemesInMarketplace', f'{TH}:848', f'{TH}:858-900', 'Browse Color Themes in Marketplace: needs a configured gallery; then a quick pick of marketplace themes with preview and install.',
          [iff("config['extensions-gallery'] == ''", [ret({'browsed': False})], title='extensionGalleryService.isEnabled() is false without a gallery in product.json', source=f'{TH}:866-868'),
           note('Quick pick of marketplace themes (query category:themes) with preview; picking one installs it and applies it', source=f'{TH}:859'), ret({'browsed': True})],
          scen=[{'expect': ['!steps.s.result.value.browsed']},
                {'id': 'browse-themes-with-gallery', 'config': {'extensions-gallery': 'https://marketplace.example/_apis/public/gallery'}, 'expect': ['steps.s.result.value.browsed']}])
    return p

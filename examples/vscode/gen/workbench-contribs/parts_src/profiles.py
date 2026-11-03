from builder import Part, call, ret, iff, choice, sets, note, called

UP = 'userDataProfile/browser/userDataProfile.ts'
UA = 'userDataProfile/browser/userDataProfileActions.ts'
PROFILES_EDITOR = 'vscode-userdata-profiles:/profiles-editor'


def build():
    p = Part('profiles')
    ws = 'workbench-shell'
    switch = p.stub('user-data-profile-management-service.switch-profile', ws, {'type': 'object', 'properties': {'profile_id': {'type': 'string'}}})
    remove = p.stub('user-data-profile-management-service.remove-profile', ws, {'type': 'object', 'properties': {'profile_id': {'type': 'string'}}})
    open_window = p.stub('host-service.open-window', ws, {'type': 'object', 'properties': {'force_profile': {'type': 'string'}, 'force_temp_profile': {'type': 'boolean'}}})
    open_editor = p.stub('editor-service.open-editor', ws)
    notify = p.stub('notification-service.notify', ws)
    opener = p.stub('opener-service.open', 'platform-core', {'type': 'object', 'properties': {'resource': {'type': 'string'}}})
    cleanup = p.stub('user-data-profiles-service.clean-up', 'platform-core')
    reset_ws = p.stub('user-data-profiles-service.reset-workspaces', 'platform-core')
    set_ctx = p.stub('context-key-service.set-context', 'platform-core')
    udp = 'user-data-profile'
    p.seed[udp] = {'current_profile': 'default', 'profiles': {'default': {'name': 'Default', 'is_default': True}, 'work': {'name': 'Work', 'is_default': False}}}

    def open_profiles_editor(line):
        return call(open_editor, {'resource': PROFILES_EDITOR, 'options': {'pinned': True}}, title='openProfilesEditor: the Profiles editor', source=f'{UP}:{line}')

    p.cmd(udp, 'workbench.profiles.actions.profileEntry.${profile.id}', f'{UP}:222', f'{UP}:239-243',
          'Profiles menu entry (one per profile): switches to that profile unless it is already current.',
          [iff('state.current_profile == input.profile_id', [ret({'switched': False})], source=f'{UP}:240'),
           call(switch, {'profile_id': '= input.profile_id'}, source=f'{UP}:241'),
           sets({'state.current_profile': '= input.profile_id'}, title='onDidChangeCurrentProfile re-registers the profile actions', source=f'{UP}:69-77'),
           ret({'switched': True})],
          request={'type': 'object', 'properties': {'profile_id': {'type': 'string', 'default': 'work'}}},
          scen=[{'id': 'profile-entry-switch', 'expect': [called(switch, "e.input.profile_id == 'work'"), "state['user-data-profile@w1'].current_profile == 'work'"]},
                {'id': 'profile-entry-current', 'input': {'profile_id': 'default'}, 'expect': ['!steps.s.result.value.switched', '!' + called(switch)]}])
    p.cmd(udp, 'workbench.profiles.actions.newWindowWithProfile', f'{UP}:248', f'{UP}:258-278', 'New Window with Profile...: pick a profile, open a window forced to it.',
          [choice('pick', 'work', {'work': [sets({'vars.p': 'Work'})], 'dismissed': [ret({'opened': False})]}, source=f'{UP}:263-274'),
           call(open_window, {'force_profile': '= vars.p'}, source=f'{UP}:276'), ret({'opened': True})],
          scen=[{'expect': [called(open_window, "e.input.force_profile == 'Work'")]},
                {'id': 'new-window-with-profile-dismissed', 'choices': {'user-data-profile.cmd-workbench-profiles-actions-newwindowwithprofile.pick': 'dismissed'}, 'expect': ['!' + called(open_window)]}])
    p.cmd(udp, 'workbench.action.openProfile.${profile.name}', f'{UP}:288', f'{UP}:305-308', 'New Window with a given profile (OpenProfileMenu entry per profile).',
          [call(open_window, {'force_profile': '= input.profile_name'}, source=f'{UP}:307'), ret({'opened': True})],
          request={'type': 'object', 'properties': {'profile_name': {'type': 'string', 'default': 'Work'}}},
          scen=[{'id': 'new-window-action', 'expect': [called(open_window, "e.input.force_profile == 'Work'")]}])
    p.cmd(udp, 'workbench.profiles.actions.switchProfile', f'{UP}:325', f'{UP}:334-356', 'Switch Profile...: quick pick of the non-internal profiles, switch to the picked one.',
          [choice('pick', 'work', {'work': [sets({'vars.p': 'work'})], 'dismissed': [ret({'switched': False})]}, source=f'{UP}:349-352'),
           call(switch, {'profile_id': '= vars.p'}, source=f'{UP}:353'), sets({'state.current_profile': '= vars.p'}), ret({'switched': True})],
          scen=[{'post': [{'interface': 'user-data-profile.cmd-workbench-profiles-actions-profileentry-profile-id', 'caller': 'user', 'input': {'profile_id': 'work'}, 'as': 'again'}],
                 'expect': [called(switch, "e.input.profile_id == 'work'"), '!steps.again.result.value.switched', "state['user-data-profile@w1'].current_profile == 'work'"]}])
    p.cmd(udp, 'workbench.profiles.actions.manageProfiles', f'{UP}:361', f'{UP}:390-394', 'Profiles: opens the Profiles editor.',
          [open_profiles_editor(393), ret({'opened': True})], scen=[{'expect': [called(open_editor, f"e.input.resource == '{PROFILES_EDITOR}'")]}])
    p.cmd(udp, 'workbench.profiles.actions.exportProfile', f'{UP}:411', f'{UP}:421-424', 'Export Profile...: opens the Profiles editor with the current profile selected.',
          [open_profiles_editor(107), ret({'selected': '= state.current_profile'})], scen=[{'expect': ["steps.s.result.value.selected == 'default'", called(open_editor)]}])
    p.cmd(udp, 'workbench.profiles.actions.createFromCurrentProfile', f'{UP}:438', f'{UP}:448-451', 'Save Current Profile As...: Profiles editor with a new profile copied from the current one.',
          [open_profiles_editor(107), ret({'new_profile_from': '= state.current_profile'})], scen=[{'expect': ["steps.s.result.value.new_profile_from == 'default'", called(open_editor)]}])
    p.cmd(udp, 'workbench.profiles.actions.createProfile', f'{UP}:457', f'{UP}:474-477', 'New Profile...: Profiles editor with an empty new profile.',
          [open_profiles_editor(107), ret({'new_profile_from': None})], scen=[{'expect': [called(open_editor)]}])
    p.cmd(udp, 'workbench.profiles.actions.deleteProfile', f'{UP}:482', f'{UP}:493-520', 'Delete Profile...: multi-pick among non-default profiles; removes the picked ones, errors are notified.',
          [sets({'vars.deletable': '= state.profiles.filter(k, !state.profiles[k].is_default)'}, source=f'{UP}:500'),
           iff('size(vars.deletable) == 0', [ret({'deleted': []})], source=f'{UP}:501'),
           choice('pick', 'all', {'all': [], 'dismissed': [ret({'deleted': []})]}, source=f'{UP}:502-513'),
           call(remove, {'profile_id': '= vars.deletable[0]'}, as_='r', on_error='continue', source=f'{UP}:515'),
           iff('!vars.r.ok', [call(notify, {'severity': 'error', 'message': '= vars.r.error.message'}, source=f'{UP}:517'), ret({'deleted': []})]),
           sets({'state.profiles': '= omit(state.profiles, vars.deletable[0])'}),
           ret({'deleted': '= vars.deletable'})],
          scen=[{'expect': ["steps.s.result.value.deleted == ['work']", called(remove, "e.input.profile_id == 'work'"), "!('work' in state['user-data-profile@w1'].profiles)"]},
                {'id': 'delete-profile-only-default', 'state': {'user-data-profile@w1': {'profiles': {'work': {'is_default': True}}}}, 'expect': ['size(steps.s.result.value.deleted) == 0', '!' + called(remove)]}])
    p.cmd(udp, 'workbench.profiles.actions.help', f'{UP}:526', f'{UP}:537-539', 'Profiles help: opens https://aka.ms/vscode-profiles-help.',
          [call(opener, {'resource': 'https://aka.ms/vscode-profiles-help'}, source=f'{UP}:538'), ret({'opened': True})],
          scen=[{'expect': [called(opener, "e.input.resource == 'https://aka.ms/vscode-profiles-help'")]}])
    ua = 'user-data-profile-actions'
    p.cmd(ua, 'workbench.profiles.actions.createTemporaryProfile', f'{UA}:31', f'{UA}:26-28', 'New Window with Temporary Profile.',
          [call(open_window, {'force_temp_profile': True}, source=f'{UA}:27'), ret({'opened': True})], scen=[{'expect': [called(open_window, 'e.input.force_temp_profile')]}])
    p.cmd(ua, 'workbench.profiles.actions.cleanupProfiles', f'{UA}:35', f'{UA}:45-47', 'Developer: Cleanup Profiles.',
          [call(cleanup, {}, source=f'{UA}:46'), ret({'done': True})], scen=[{'expect': [called(cleanup)]}])
    p.cmd(ua, 'workbench.profiles.actions.resetWorkspaces', f'{UA}:50', f'{UA}:60-63', 'Developer: Reset Workspace Profiles Associations.',
          [call(reset_ws, {}, source=f'{UA}:62'), ret({'done': True})], scen=[{'expect': [called(reset_ws)]}])
    c = p.comp('user-data-profiles-workbench-contribution', 'UserDataProfilesWorkbenchContribution', 'user-data-profile-contribution', [f'{UP}:43'],
               'Registers the profile actions and menus; re-registers per-profile entries when the current profile changes.')
    p.iface(c, 'constructor', 'Registers the Profiles menu, the per-profile entries and actions, and listens to profile changes.',
            ['userDataProfile/browser/userDataProfile.contribution.ts:10', f'{UP}:50-80'],
            [call('user-data-profile.get-current-profile', {}, as_='p', title='userDataProfileService.currentProfile', source=f'{UP}:63'),
             call(set_ctx, {'key': 'currentProfile', 'value': '= vars.p.value.id'}, title='CURRENT_PROFILE_CONTEXT', source=f'{UP}:65'),
             call(set_ctx, {'key': 'hasProfiles', 'value': '= vars.p.value.non_internal_count > 1'}, title='HAS_PROFILES_CONTEXT: more than one non-internal profile', source=f'{UP}:70-71'),
             sets({'state.actions_registered': True}, title='registerEditor(); registerActions()', source=f'{UP}:74-75'), ret({'registered': True, 'has_profiles': '= vars.p.value.non_internal_count > 1'})])
    p.scenario_for(f'{c}.constructor', {'id': 'profiles-contribution', 'caller': 'workbench', 'expect': [f"state['{c}@w1'].actions_registered", 'steps.s.result.value.has_profiles',
                                                                                        called(set_ctx, "e.input.key == 'currentProfile' && e.input.value == 'default'")]})
    p.scenario_for(f'{c}.constructor', {'id': 'profiles-contribution-internal-profile', 'caller': 'workbench',
                                        'state': {'user-data-profile@w1': {'profiles': {'work': {'name': 'Work', 'is_default': False, 'is_internal': True}}}},
                                        'expect': ['!steps.s.result.value.has_profiles', called(set_ctx, "e.input.key == 'hasProfiles' && e.input.value == false")]})
    p.iface(udp, 'get-current-profile', 'IUserDataProfileService.currentProfile with its settings resource (the default profile keeps User/settings.json, others User/profiles/<id>/settings.json), '
            'the default profile\'s settings resource and the number of non-internal profiles.',
            [f'{UP}:63-71', 'preferences/browser/preferences.contribution.ts:1397-1402'],
            [sets({'vars.cur': '= state.current_profile', 'vars.n': '= size(state.profiles.filter(k, !has(state.profiles[k].is_internal) || !state.profiles[k].is_internal))'}),
             iff('state.profiles[vars.cur].is_default',
                 [ret({'id': '= vars.cur', 'is_default': True, 'settings_resource': 'vscode-userdata:/User/settings.json', 'default_settings_resource': 'vscode-userdata:/User/settings.json', 'non_internal_count': '= vars.n'})],
                 title='The default profile uses the top-level user settings'),
             ret({'id': '= vars.cur', 'is_default': False, 'settings_resource': "= 'vscode-userdata:/User/profiles/' + vars.cur + '/settings.json'",
                  'default_settings_resource': 'vscode-userdata:/User/settings.json', 'non_internal_count': '= vars.n'})])
    return p

# Reconciliation round, part 2: user-triggered commands modeled with their run() behavior,
# the session-management methods they call, and the scenarios that run them.
SID_IN = '= input.session_id'
P = 'local-agent-host'


def call(i, inp=None, as_=None, title=None, src=None, **kw):
    st = {'call': i}
    if inp is not None:
        st['input'] = inp
    if as_:
        st['as'] = as_
    if title:
        st['title'] = title
    if src:
        st['source'] = src
    st.update(kw)
    return st


def CFG(key, val, src=None):
    return call('configuration-service.update-value', {'key': key, 'value': val, 'target': 'user'}, title=f'updateValue({key})', src=src)


def CLIP(text):
    return call('clipboard-service.write-text', {'text': text})


def OPEN(url):
    return call('opener-service.open', {'resource': url, 'open_external': True})


def EXEC(cid):
    return call('command-service.execute-command', {'command_id': cid, 'args': []}, title=f'executeCommand({cid})')


def RET(**kw):
    return {'return': kw or {'ok': True}}


# ---------------- methods the commands call (session management, provider, services)
def mgmt(name, rng, summary, provider_iface=None, extra=None, req=None, resp=None):
    beh = [call('sessions-providers-service.get-provider', {'id': '= input.provider_id'}, 'p'),
           {'if': 'has(vars.p.value.missing)', 'then': [{'title': 'Unknown provider: optional chaining makes it a no-op', 'source': f'{SMS}:{rng}', 'return': {'done': False}}]}]
    if provider_iface:
        beh.append(call(provider_iface, {'session_id': SID_IN, 'title': '= input.title'}, 'r'))
    beh += (extra or [])
    beh.append(RET(done=True))
    iface('sessions-management-service', name, summary, [f'{SMS}:{rng}'],
          request=req or obj({'session_id': SESS, 'provider_id': s(P, default=P), 'title': s('Fix add() tests', default='Fix add() tests')}, ['session_id']),
          response=resp or obj({'done': B}), behavior=beh)


def prov(name, rng, summary, patch, dispatch=None):
    beh = [call('local-agent-host-sessions-provider.cache-get', {'session_id': SID_IN}, 'c'),
           {'if': 'has(vars.c.value.missing)', 'then': [{'title': 'Not a cached session: nothing to do', 'source': f'{BASEP}:{rng}', 'return': {'changed': False}}]},
           call('local-agent-host-sessions-provider.cache-update', {'session_id': SID_IN, 'patch': patch})]
    if dispatch:
        beh.append(call('protocol-server-handler.dispatch-action', {'session': '= vars.c.value.backend_uri', 'action': dispatch, 'client_id': 'w1-client'},
                        title='connection.dispatch(...) to the agent host', src=f'{BASEP}:{rng}'))
    beh.append(RET(changed=True))
    iface('local-agent-host-sessions-provider', name, summary, [f'{BASEP}:{rng}'],
          request=obj({'session_id': SESS, 'title': S}), response=obj({'changed': B}), behavior=beh)


prov('set-session-read-state', '7272-7300', 'setSessionReadState: mark the cached session read (skipped for policy-disabled agents).', {'read': True})
prov('import-session', '7034-7045', 'importSession: import an external session through the connection (unavailable without import support).', {'external': False})
prov('rename-chat', '7427-7440', 'renameChat: rename a peer chat of the session.', {'chat_title': '= input.title'})
prov('delete-chat', '7536-7560', 'deleteChat: delete a peer chat (refused for the main chat).', {'chats_deleted': 1})
prov('set-agent-merge-enabled', '6423-6427', 'setAgentMergeEnabled: Agent Merge on or off for the session (dispatched to the host).', {'agent_merge': True})
prov('set-agent-merge-overrides', '6428-6432', 'setAgentMergeOverrides: per-session Agent Merge repair actions.', {'agent_merge_overrides': True})
prov('fork-chat', '7574-7590', 'Fork/side chat: create a new peer chat in the session.', {'forked': True})

mgmt('send-request', '1210-1257', 'sendRequest: send a request to an existing chat of the session through its provider.', 'local-agent-host-sessions-provider.send-request',
     req=obj({'session_id': SESS, 'provider_id': s(P, default=P), 'title': s('/generate-run-commands', default='/generate-run-commands')}, ['session_id']))
_iface('sessions-management-service.send-request')['behavior'][2]['input'] = {'session_id': SID_IN, 'query': '= input.title'}
mgmt('mark-read', '1405-1411', 'markRead: mark the main chat read (the provider keeps the read state).', 'local-agent-host-sessions-provider.set-session-read-state')
mgmt('mark-unread', '1413-1416', 'markUnread: mark the main chat unread; remembered as explicitly unread.', None,
     extra=[{'set': {'state.explicitly_unread': '= (has(state.explicitly_unread) ? state.explicitly_unread : []) + [input.session_id]'}}])
mgmt('mark-all-read', '1440-1442', 'markAllRead: mark each given session read.', 'local-agent-host-sessions-provider.set-session-read-state')
mgmt('mark-chats-read', '1386-1403', 'markChatsRead: mark the given chats of a session read.', 'local-agent-host-sessions-provider.set-session-read-state')
mgmt('import-session', '1572-1581', 'importSession: only external sessions that support import.', 'local-agent-host-sessions-provider.import-session')
mgmt('rename-chat', '1504-1507', 'renameChat: provider.renameChat.', 'local-agent-host-sessions-provider.rename-chat')
mgmt('delete-chat', '1483-1497', 'deleteChat: refuses skipConfirmation for sent chats; provider.deleteChat.', 'local-agent-host-sessions-provider.delete-chat')
mgmt('create-new-chat-in-session', '713-730', 'createNewChatInSession: reuse an untitled chat unless forceNew, else provider.createNewChat.', 'local-agent-host-sessions-provider.fork-chat')
mgmt('fork-chat-in-session', '739-760', 'forkChatInSession: fork a chat at a turn into a new peer chat.', 'local-agent-host-sessions-provider.fork-chat')
mgmt('create-and-send-new-chat-request', '959-987', 'createAndSendNewChatRequest: create a session for the folder and send its first request.', None,
     extra=[call('sessions-management-service.create-new-session', {'folder_uri': 'file:///work/app', 'provider_id': '= input.provider_id'}, 'ns'),
            call('sessions-management-service.send-new-chat-request', {'session_id': '= vars.ns.value.session_id', 'provider_id': '= input.provider_id', 'query': '= input.title'})])

iface('sessions-service', 'close-session', 'closeSession: record the closed item, discard the draft, remove it from the grid; reopen a new session if it was the last.',
      [f'{SSV}:1832-1874'], request=obj({'session_id': SESS}), response=obj({'closed': B}),
      behavior=[{'set': {'state.visible': '= state.visible.filter(x, x != input.session_id)', 'state.active': "= state.active == input.session_id ? '' : state.active"}}, RET(closed=True)])
iface('sessions-service', 'close-chat', 'closeChat: hide the chat, persist view state and the closed history.', [f'{SSV}:1082-1110'],
      request=obj({'session_id': SESS}), response=obj({'closed': B}),
      behavior=[{'set': {'state.closed_chats': '= (has(state.closed_chats) ? state.closed_chats : 0) + 1'}}, RET(closed=True)])
iface('sessions-service', 'open-new-chat-in-session', 'openNewChatInSession: createNewChatInSession, activate the session and the chat.', [f'{SSV}:1768-1785'],
      request=obj({'session_id': SESS}), response=obj({'opened': B}),
      behavior=[call('sessions-management-service.create-new-chat-in-session', {'session_id': SID_IN, 'provider_id': P}), {'set': {'state.active': '= input.session_id'}}, RET(opened=True)])


def svc_method(cid, name, src, summary, sets, req=None):
    iface(cid, name, summary, [src], request=req or obj({}), response=obj({'ok': B}),
          behavior=[{'set': sets}, RET(ok=True)])


AFS = f'{SS}/contrib/agentFeedback/browser/agentFeedbackService.ts'
svc_method('agent-feedback-service', 'submit-feedback', f'{AFS}:993-1010', 'submitFeedback: send the accepted feedback of a session to its agent.', {'state.submitted': '= state.submitted + 1'})
svc_method('agent-feedback-service', 'clear-feedback', f'{AFS}:953-960', 'clearFeedback: drop the feedback of a session.', {'state.cleared': '= state.cleared + 1'})
svc_method('session-groups-service', 'delete-group', f'{SS}/services/sessions/browser/sessionGroupsService.ts:680-700', 'deleteGroup: remove a group (its subgroups and sections can be restored by undo).',
           {'state.groups': '= state.groups.filter(g, g != input.group_id)'}, req=obj({'group_id': s('g1', default='g1')}))
CBS = f'{SS}/services/chatBackground/browser/chatBackgroundService.ts'
svc_method('sessions-chat-background-service', 'set-background', f'{CBS}:226-231', 'setBackground: write chat.agentSessions.preferred*BackgroundImage; images are remembered in recent backgrounds.',
           {'state.background': '= input.background'}, req=obj({'background': s('codicons', default='codicons')}))
svc_method('sessions-chat-background-service', 'set-background-image-layout', f'{CBS}:243-250', 'setBackgroundImageLayout: write chat.agentSessions.preferred*BackgroundImageLayout when persisted.',
           {'state.layout': '= input.layout'}, req=obj({'layout': s('tile', default='tile')}))
svc_method('get-started-checklist-service', 'show', f'{SS}/contrib/getStarted/browser/getStartedChecklistService.ts:309-315', 'show: restore the checklist and store agentSessions.getStarted.state.', {'state.shown': True})
STS = f'{SS}/contrib/chat/browser/sessionsTasksService.ts'
svc_method('sessions-tasks-service', 'run-task', f'{STS}:391-420', 'runTask: run a session task through its task runner.', {'state.runs': '= state.runs + 1'})
svc_method('sessions-tasks-service', 'create-and-add-task', f'{STS}:298-330', 'createAndAddTask: store a new task for the session or workspace.', {'state.tasks': "= state.tasks + ['npm run dev']"})
RAH = f'{AH}/common/remoteAgentHostService.ts'
svc_method('agents-window-remote-agent-host-service', 'wait-for-connection', f'{RAH}:763', 'waitForConnection(address).', {'state.connections': '= state.connections + [input.address]'}, req=obj({'address': s('ws://build.example.internal:8081', default='ws://build.example.internal:8081')}))
svc_method('agents-window-remote-agent-host-service', 'remove-remote-agent-host', f'{RAH}:768', 'removeRemoteAgentHost(address).', {'state.connections': '= state.connections.filter(a, a != input.address)'}, req=obj({'address': s('ws://build.example.internal:8081', default='ws://build.example.internal:8081')}))
svc_method('agents-window-remote-agent-host-service', 'trigger-server-upgrade', f'{RAH}:818', 'triggerServerUpgrade(address, method).', {'state.upgrades': '= state.upgrades + 1'})
SSH = f'{AH}/common/sshRemoteAgentHost.ts'
svc_method('ssh-remote-agent-host-service', 'connect', f'{SSH}:177', 'connect(config): start an agent host over SSH.', {'state.connected': "= state.connected + ['build-box']"})
svc_method('ssh-remote-agent-host-service', 'ensure-user-ssh-config', f'{SSH}:194', 'ensureUserSSHConfig: create ~/.ssh/config when missing.', {'state.config_created': True})
svc_method('tunnel-agent-host-service', 'connect', f'{AH}/common/tunnelAgentHost.ts:518', 'connect(tunnel, authProvider): connect to a dev tunnel agent host.', {'state.connected': "= state.connected + ['my-tunnel']"})
svc_method('wsl-remote-agent-host-service', 'connect', f'{AH}/common/wslRemoteAgentHost.ts:101', 'connect({distro}): start an agent host in a WSL distribution.', {'state.connected': "= state.connected + ['Ubuntu']"})
svc_method('ssh-host-key-trust-service', 'forget-host', f'{AH}/common/sshHostKeyTrust.ts:66', 'forgetHost(host, port).', {'state.trusted_hosts': '= state.trusted_hosts.filter(h, h != input.host)'}, req=obj({'host': s('build.example.internal:22', default='build.example.internal:22')}))
svc_method('remote-agent-host-location-preference-service', 'set-preference', f'{AH}/common/remoteAgentHostLocationPreference.ts:38', 'setPreference(hostKey, preference).',
           {'state.preferences': '= merge(state.preferences, {input.host: input.preference})'}, req=obj({'host': s('build-box', default='build-box'), 'preference': s('remote', default='remote')}))
svc_method('changes-view-service', 'set-changeset-files-review-state', f'{SS}/contrib/changes/common/changesViewService.ts:88', 'setChangesetFilesReviewState(resources, reviewed).',
           {'state.reviewed': "= state.reviewed + ['file:///work/app/src/main.ts']"})
svc_method('session-changes-service', 'invoke-operation', f'{SS}/contrib/changes/browser/changesActions.ts:402-421', 'changeset.invokeOperation(id): run a changeset operation (commit, sync, PR).',
           {'state.operations_run': '= state.operations_run + [input.operation]'}, req=obj({'operation': s('commit', default='commit')}))

# ---------------- the commands
SA_ = f'{SS}/contrib/sessions/browser/sessionsActions.ts'
SVA_ = f'{SS}/contrib/sessions/browser/views/sessionsViewActions.ts'
CC = f'{SS}/contrib/chat/browser/chat.contribution.ts'
AV = f'{SS}/contrib/sessions/browser/views/automationsView.ts'
RAA = f'{SS}/contrib/providers/remoteAgentHost/browser/remoteAgentHostActions.ts'
AMA = f'{SS}/contrib/providers/agentHost/browser/agentMergeActions.ts'
VSA = f'{SS}/electron-browser/actions/vscodeActions.ts'
GROUPS = {}


def cmd(group, comp_id, cid, reg, run, summary, beh, req=None):
    slug = cmd_slug(cid)
    if not any(c['id'] == comp_id for c in components):
        comp(comp_id, comp_id.replace('-', ' '), 'agents', f'Commands registered in {reg.split(":")[0].split("/")[-1]}.', [reg.split(':')[0]])
    srcs = [run, reg] if run else [reg]
    iface(comp_id, slug, summary, srcs, kind='command', request=req or obj({'session_id': SESS}), response=obj({'ok': B}),
          attributes={'command_id': cid}, behavior=beh + ([] if beh and 'return' in beh[-1] else [RET(ok=True)]))
    GROUPS.setdefault(group, []).append(f'{comp_id}.{slug}')


ART = "config['chat-artifact-integrations-enabled']"
cfg('chat-artifact-integrations-enabled', 'chat.artifactIntegrations.enabled', 'boolean', False, False,
    'chat.artifactIntegrations.enabled: Agent Merge commands refuse while artifact integrations are on.', [f'{AH}/common/artifactToolsConfiguration.ts:17'])
cfg('chat-automations-enabled', 'chat.automations.enabled', 'boolean', False, False,
    'chat.automations.enabled: automation commands show "automations disabled" unless true (reference; registered by chat).', [f'{AV}:2724-2730'], boundary_owner='chat')


def MERGE_GUARD(src):
    return {'if': ART, 'then': [{'title': 'Agent Merge is unavailable while artifact integrations are enabled', 'source': src,
                                 'fail': {'code': 'agent-merge-unavailable', 'message': 'Agent Merge is unavailable while artifact integrations are enabled.'}}]}


def AUTO_GUARD(src):
    return {'if': "!config['chat-automations-enabled']", 'then': [{'title': 'Automations disabled: show the disabled notice', 'source': src, 'return': {'ok': False}}]}


# sessions list and chats
cmd('sessions', 'sessions-view-actions', 'MARK_SESSION_READ_COMMAND_ID', f'{SVA_}:1654', f'{SVA_}:1693-1695', 'Mark as Read (agentSession.markRead, Shift+I).',
    [call('sessions-management-service.mark-read', {'session_id': SID_IN, 'provider_id': P})])
cmd('sessions', 'sessions-view-actions', 'MARK_SESSION_UNREAD_COMMAND_ID', f'{SVA_}:1698', f'{SVA_}:1737-1739', 'Mark as Unread (agentSession.markUnread, Shift+U).',
    [call('sessions-management-service.mark-unread', {'session_id': SID_IN, 'provider_id': P})])
cmd('sessions', 'sessions-view-actions', 'sessionsViewPane.markAllNestedRead', f'{SVA_}:1742', f'{SVA_}:1756-1768', 'Mark all nested chats read (skips archived sessions).',
    [call('sessions-management-service.mark-chats-read', {'session_id': SID_IN, 'provider_id': P})])
cmd('sessions', 'sessions-view-actions', 'sessionsViewPane.markAllRead', f'{SVA_}:1799', f'{SVA_}:1812-1817', 'Mark all sessions read.',
    [call('sessions-management-service.mark-all-read', {'session_id': SID_IN, 'provider_id': P})])
cmd('sessions', 'sessions-view-actions', 'sessionsViewPane.importSession', f'{SVA_}:1197', f'{SVA_}:1213-1225', 'Import external sessions that support import.',
    [call('sessions-management-service.import-session', {'session_id': SID_IN, 'provider_id': P})])
cmd('sessions', 'sessions-view-actions', 'sessionsViewPane.deleteSessionGroupWithUndo', f'{SVA_}:155', f'{SVA_}:138-159', 'Delete a session group with undo.',
    [call('session-groups-service.delete-group', {'group_id': 'g1'})])
cmd('sessions', 'sessions-view-actions', 'sessionsView.deleteEmptyGroup', f'{SVA_}:1024', f'{SVA_}:1038-1047', 'Delete an empty group (not comparison groups).',
    [call('session-groups-service.delete-group', {'group_id': 'g2'})])
cmd('sessions', 'sessions-view-actions', 'sessionsView.markAllAutomationRunsRead', f'{SVA_}:1934', f'{SVA_}:1941-1956', 'Mark all completed automation runs read.',
    [call('sessions-management-service.mark-all-read', {'session_id': SID_IN, 'provider_id': P})])
cmd('sessions', 'sessions-actions', 'sessions.chatCompositeBar.renameChat', f'{SA_}:657', f'{SA_}:689-713', 'Rename a peer chat (not the main or an untitled chat).',
    [{'if': "input.title.trim() == ''", 'then': [{'title': "Validation 'Title cannot be empty'", 'source': f'{SA_}:627-655', 'return': {'ok': False}}]},
     call('sessions-management-service.rename-chat', {'session_id': SID_IN, 'provider_id': P, 'title': '= input.title'})],
    req=obj({'session_id': SESS, 'title': s('Investigate CI', default='Investigate CI')}))
cmd('sessions', 'sessions-actions', 'sessions.list.deleteChat', f'{SA_}:779', f'{SA_}:800-809', 'Delete a chat from the sessions list (untitled chats skip confirmation).',
    [call('sessions-management-service.delete-chat', {'session_id': SID_IN, 'provider_id': P})])
cmd('sessions', 'sessions-actions', 'sessions.chatCompositeBar.deleteChat', f'{SA_}:1046', f'{SA_}:1075-1092', 'Delete the active peer chat (not the main chat).',
    [call('sessions-management-service.delete-chat', {'session_id': SID_IN, 'provider_id': P})])
cmd('sessions', 'sessions-actions', 'sessions.chatCompositeBar.addChat', f'{SA_}:815', f'{SA_}:844-854', 'New Nested Session (Ctrl/Cmd+T): openNewChatInSession.',
    [call('sessions-service.open-new-chat-in-session', {'session_id': SID_IN})])
cmd('sessions', 'sessions-actions', 'sessions.chatCompositeBar.closeChat', f'{SA_}:921', f'{SA_}:952-979', 'Close chat: untitled chats are deleted, others hidden with their view state.',
    [call('sessions-service.close-chat', {'session_id': SID_IN})])
cmd('sessions', 'sessions-actions', 'sessions.chatCompositeBar.closeAllChats', f'{SA_}:994', f'{SA_}:1022-1043', 'Close all non-main chats.',
    [call('sessions-service.close-chat', {'session_id': SID_IN})])
cmd('sessions', 'sessions-actions', 'CLOSE_SESSION_COMMAND_ID', f'{SA_}:1969', f'{SA_}:2007-2024', 'Close (sessions.chatCompositeBar.close, Ctrl/Cmd+W): close the chat group, else closeSession.',
    [call('sessions-service.close-session', {'session_id': SID_IN})])
cmd('sessions', 'sessions-actions', 'sessions.list.promoteChatToSession', f'{SA_}:745', f'{SA_}:761-776', 'Promote a chat to its own session (needs chat moves enabled).',
    [call('sessions-management-service.create-and-send-new-chat-request', {'session_id': SID_IN, 'provider_id': P, 'title': 'Continue in a new session'})])
cmd('sessions', 'sessions-titlebar-actions', 'sessions.blockedSessions.ignoreAllInputNeeded', f'{SS}/contrib/sessions/browser/sessionsTitleBarWidget.ts:103', f'{SS}/contrib/sessions/browser/sessionsTitleBarWidget.ts:103-105',
    'Ignore all sessions needing input: store the ignored occurrences.', [call('storage-service.store', {'key': 'sessions.blockedIndicator.ignoredOccurrences', 'scope': 'profile', 'value': '[]'})])
# chat contrib
cmd('chat', 'sessions-chat-actions', 'workbench.action.chat.delegateToAgentHostSession', f'{SS}/contrib/chat/browser/agentHostDelegation.ts:22', f'{SS}/contrib/chat/browser/agentHostDelegation.ts:22-61',
    'Delegate a request to a new local agent host session, inserted to the right, and send the prompt.',
    [call('sessions-management-service.create-and-send-new-chat-request', {'session_id': SID_IN, 'provider_id': P, 'title': 'Fix the failing test'})])
cmd('chat', 'sessions-chat-actions', 'workbench.action.sessions.customizeWelcomeMessage', f'{CC}:397', f'{CC}:351-375', 'Customize the welcome message (name or phrases).',
    [CFG('sessions.chat.experimental.welcomeName', 'dev', f'{CC}:377-394')])
cmd('chat', 'sessions-chat-actions', 'workbench.action.sessions.hideWelcomeMessage', f'{CC}:421', f'{CC}:416-418', 'Hide the welcome message.',
    [CFG('sessions.chat.experimental.welcomePhrases', False)])
cmd('chat', 'sessions-chat-actions', 'workbench.action.chat.changeAgentSessionsBackground', f'{CC}:517', f'{CC}:448-514', 'Change the chat background (none, codicons, image).',
    [call('sessions-chat-background-service.set-background', {'background': 'codicons'})])
cmd('chat', 'sessions-chat-actions', 'workbench.action.chat.changeAgentSessionsBackgroundLayout', f'{CC}:564', f'{CC}:544-561', 'Change the background image layout.',
    [call('sessions-chat-background-service.set-background-image-layout', {'layout': 'tile'})])
cmd('chat', 'sessions-chat-actions', 'sessions.chat.disableSessionStorageCleanupSuggestions', f'{CC}:625', f'{CC}:636-640', 'Disable session storage cleanup suggestions (application setting).',
    [CFG('chat.agentSessions.sessionStorageCleanupSuggestion.enabled', False)])
RSA = f'{SS}/contrib/chat/browser/runScriptAction.ts'
cmd('chat', 'sessions-run-script-actions', 'workbench.action.agentSessions.runScriptPrimary', f'{RSA}:208', f'{RSA}:219-246', 'Run the primary session task (or configure one first).',
    [call('sessions-tasks-service.run-task')])
cmd('chat', 'sessions-run-script-actions', 'workbench.action.agentSessions.configureDefaultRunAction', f'{RSA}:259', f'{RSA}:275-281', 'Add Task...: create a task and run it.',
    [call('sessions-tasks-service.create-and-add-task'), call('sessions-tasks-service.run-task')])
cmd('chat', 'sessions-run-script-actions', 'workbench.action.agentSessions.generateRunAction', f'{RSA}:284', f'{RSA}:299-317', "Ask the agent to generate run commands ('/generate-run-commands').",
    [call('sessions-management-service.send-request', {'session_id': SID_IN, 'provider_id': P, 'title': '/generate-run-commands'})])
# automations
cmd('automations', 'automations-view-actions', 'sessions.automations.markAllRead', f'{AV}:2678', f'{AV}:2691-2696', 'Mark all automation runs read.',
    [call('sessions-management-service.mark-all-read', {'session_id': SID_IN, 'provider_id': P})])
cmd('automations', 'automations-view-actions', 'sessionsView.newAutomation', f'{AV}:2715', f'{AV}:2724-2747', 'New automation (needs chat.automations.enabled).',
    [AUTO_GUARD(f'{AV}:2724-2730'), call('automation-service.create-automation', {'name': 'Nightly triage', 'enabled': True})])
cmd('automations', 'automations-view-actions', 'sessions.automations.import', f'{AV}:2750', f'{AV}:2760-2804', 'Import a .automation.md file (created disabled).',
    [AUTO_GUARD(f'{AV}:2760-2765'), call('file-service.read-file', {'resource': 'file:///work/app/triage.automation.md'}), call('automation-service.create-automation', {'name': 'Imported', 'enabled': False})])
cmd('automations', 'automations-view-actions', 'sessions.automations.duplicate', f'{AV}:2807', f'{AV}:2817-2874', 'Duplicate an automation.',
    [AUTO_GUARD(f'{AV}:2817-2822'), call('automation-service.create-automation', {'name': 'Nightly triage (copy)', 'enabled': True})])
cmd('automations', 'automations-view-actions', 'sessions.automations.export', f'{AV}:2877', f'{AV}:2887-2933', 'Export an automation as .automation.md.',
    [AUTO_GUARD(f'{AV}:2887-2892'), call('file-service.write-file', {'resource': 'file:///work/app/triage.automation.md', 'content': '# Nightly triage'})])
cmd('automations', 'automations-view-actions', 'sessions.automations.delete', f'{AV}:2967', f'{AV}:2977-2985', 'Delete an automation after confirmation.',
    [AUTO_GUARD(f'{AV}:2977-2980'), call('dialog-service.confirm', {'message': 'Delete automation "Nightly triage"?'}, 'c'),
     {'if': 'vars.c.value.confirmed != true', 'then': [RET(ok=False)]}, call('automation-service.delete-automation', {'id': 'auto-1'})])
cmd('automations', 'automations-view-actions', 'sessions.automations.disable', f'{AV}:2988', f'{AV}:2998-3000', 'Disable an automation.',
    [AUTO_GUARD(f'{AV}:3018-3025'), call('automation-service.update-automation-if-unchanged', {'id': 'auto-1', 'enabled': False})])
cmd('automations', 'automations-view-actions', 'sessions.automations.enable', f'{AV}:3003', f'{AV}:3013-3015', 'Enable an automation.',
    [AUTO_GUARD(f'{AV}:3018-3025'), call('automation-service.update-automation-if-unchanged', {'id': 'auto-1', 'enabled': True})])
# account, feedback, customization, changes, github, editor, files, get started, code review
ACC = f'{SS}/contrib/accountMenu/browser/account.contribution.ts'
cmd('misc', 'account-actions', 'workbench.action.agenticSignIn', f'{ACC}:107', f'{ACC}:121-123', 'Sign in: run chat setup.', [EXEC('workbench.action.chat.triggerSetup')])
cmd('misc', 'account-actions', 'workbench.action.agenticSignOut', f'{ACC}:127', f'{ACC}:141-170', 'Sign out of the Agents window after confirmation: remove the account sessions.',
    [call('dialog-service.confirm', {'message': 'Sign out of the Agents window?'}, 'c'), {'if': 'vars.c.value.confirmed != true', 'then': [RET(ok=False)]},
     call('authentication-service.remove-session', {'provider_id': 'github', 'session_id': 'gh-1'})])
AFA = f'{SS}/contrib/agentFeedback/browser/agentFeedbackEditorActions.ts'
cmd('misc', 'agent-feedback-actions', 'agentFeedbackEditor.action.submit', f'{AFA}:202', f'{AFA}:99-106', 'Submit feedback of the session in the active editor.', [call('agent-feedback-service.submit-feedback')])
cmd('misc', 'agent-feedback-actions', 'agentFeedbackEditor.action.submitActiveSession', f'{AFA}:203', f'{AFA}:188-198', 'Submit accepted feedback of the active session.', [call('agent-feedback-service.submit-feedback')])
cmd('misc', 'agent-feedback-actions', 'agentFeedbackEditor.action.clearAll', f'{AFA}:206', f'{AFA}:168-171', 'Clear all feedback.', [call('agent-feedback-service.clear-feedback')])
AIC = f'{SS}/contrib/aiCustomizationTreeView/browser/aiCustomizationTreeView.contribution.ts'
cmd('misc', 'ai-customization-actions', 'aiCustomization.runPrompt', f'{AIC}:80', f'{AIC}:88-91', 'Run a prompt file in chat.', [EXEC('workbench.action.chat.run.prompt.current')])
cmd('misc', 'ai-customization-actions', 'aiCustomization.deleteFile', f'{AIC}:96', f'{AIC}:104-123', 'Delete a customization file after confirmation (file scheme only).',
    [call('dialog-service.confirm', {'message': "Are you sure you want to delete 'review.prompt.md'?"}, 'c'), {'if': 'vars.c.value.confirmed != true', 'then': [RET(ok=False)]},
     call('file-service.del', {'resource': 'file:///work/app/.github/prompts/review.prompt.md', 'use_trash': True, 'recursive': True})])
cmd('misc', 'ai-customization-actions', 'aiCustomization.copyPath', f'{AIC}:128', f'{AIC}:136-141', 'Copy the customization file path.', [CLIP('/work/app/.github/prompts/review.prompt.md')])
cmd('misc', 'ai-customization-actions', 'aiCustomization.disableItem', f'{AIC}:181', f'{AIC}:189-207', 'Disable a prompt file.', [call('prompts-service.set-disabled-prompt-files', {'type': 'prompt', 'uris': ['file:///work/app/.github/prompts/review.prompt.md']})])
cmd('misc', 'ai-customization-actions', 'aiCustomization.enableItem', f'{AIC}:212', f'{AIC}:220-238', 'Enable a prompt file.', [call('prompts-service.set-disabled-prompt-files', {'type': 'prompt', 'uris': []})])
APR = f'{SS}/contrib/applyCommitsToParentRepo/browser/applyChangesToParentRepo.ts'
cmd('misc', 'apply-changes-actions', 'chatEditing.applyChangesToParentRepo', f'{APR}:164', f'{APR}:81-161', 'Merge the worktree branch into the parent repository via the git extension.',
    [EXEC('_git.revParseAbbrevRef'), EXEC('_git.mergeBranch')])
CHA = f'{SS}/contrib/changes/browser/changesActions.ts'
cmd('misc', 'changes-actions', 'workbench.contrib.sessions.changesetOperation.${operation.id}', f'{CHA}:380', f'{CHA}:402-421', 'Resource-scoped changeset operation (one action per operation).',
    [call('session-changes-service.invoke-operation', {'operation': 'discard'})])
cmd('misc', 'changes-actions', '${CHANGES_HEADER_CHANGESET_OPERATION_ACTION_PREFIX}${operation.id}', f'{CHA}:508', f'{CHA}:526-528', 'Changeset-scoped header operation (commit, ...).',
    [call('session-changes-service.invoke-operation', {'operation': 'commit'})])
CVA = f'{SS}/contrib/changes/browser/changesViewActions.ts'
cmd('misc', 'changes-actions', 'workbench.action.agentSessions.openPullRequest', f'{CVA}:135', f'{CVA}:123-132', 'Open the session pull request.', [EXEC('workbench.agentSessions.action.openPullRequest')])
cmd('misc', 'changes-actions', 'changeset.review', f'{SS}/contrib/changes/browser/changesetReviewActions.ts:76', f'{SS}/contrib/changes/browser/changesetReviewActions.ts:41-73', 'Toggle a file reviewed.',
    [call('changes-view-service.set-changeset-files-review-state')])
cmd('misc', 'changes-actions', 'sessions.action.fixCIChecks', f'{SS}/contrib/changes/browser/checksActions.ts:241', f'{SS}/contrib/changes/browser/checksActions.ts:213-237', 'Ask the agent to fix the failing CI checks.',
    [call('sessions-management-service.send-request', {'session_id': SID_IN, 'provider_id': P, 'title': 'Fix the failing CI checks'})])
SSC = f'{SS}/contrib/changes/browser/sessionSyncChanges.ts'
cmd('misc', 'changes-actions', 'workbench.action.sessions.syncChanges', f'{SSC}:189', f'{SSC}:88-99', 'Sync Changes (pull/push) through the sync changeset operation.',
    [{'if': '!input.sync_available', 'then': [{'title': 'No sync operation', 'source': f'{SSC}:90-94', 'fail': {'code': 'sync-unavailable', 'message': 'Sync Changes is no longer available for this session.'}}]},
     call('session-changes-service.invoke-operation', {'operation': 'sync'})], req=obj({'sync_available': {'type': 'boolean', 'default': True}}))
CRV = f'{SS}/contrib/codeReview/browser/codeReview.contributions.ts'
cmd('misc', 'code-review-actions', 'sessions.codeReview.run', f'{CRV}:92', f'{CRV}:63-89', 'Run a code review in a new chat of the session.',
    [call('sessions-management-service.send-request', {'session_id': SID_IN, 'provider_id': P, 'title': '/review'})])
EDC = f'{SS}/contrib/editor/browser/editor.contribution.ts'
cmd('misc', 'sessions-editor-actions', 'workbench.action.agentSessions.openModalEditorInEditor', f'{EDC}:369', f'{EDC}:314-366', 'Move the modal editor into the editor part (sets workbench.editor.useModal to some).',
    [CFG('workbench.editor.useModal', 'some')])
FC = f'{SS}/contrib/files/browser/files.contribution.ts'
cmd('misc', 'sessions-files-actions', 'sessions.files.action.downloadRemoteFile', f'{FC}:157', f'{FC}:134-154', 'Download a remote agent-host file to the local disk.',
    [call('file-service.read-file', {'resource': 'file:///work/app/src/main.ts'})])
GS = f'{SS}/contrib/getStarted/browser/getStarted.contribution.ts'
cmd('misc', 'get-started-actions', 'sessions.getStarted.show', f'{GS}:113', f'{GS}:124-129', 'Show the get started checklist.', [call('get-started-checklist-service.show')])
GH = f'{SS}/contrib/github/browser'
cmd('misc', 'github-actions', 'workbench.agentSessions.newSessionFromPullRequest', f'{GH}/createSessionFromPullRequestAction.ts:35', f'{GH}/createSessionFromPullRequestAction.ts:56-263',
    'New session from a pull request: pick a PR, create and send a session for it.',
    [call('sessions-management-service.create-and-send-new-chat-request', {'session_id': SID_IN, 'provider_id': P, 'title': 'Review pull request #42'})])
cmd('misc', 'github-actions', 'workbench.agentSessions.action.openIssue', f'{GH}/issueActions.ts:81', f'{GH}/issueActions.ts:52-79', 'Open the issue (PR extension webview or browser).', [OPEN('https://github.com/acme/app/issues/7')])
cmd('misc', 'github-actions', 'workbench.agentSessions.action.copyIssueUrl', f'{GH}/issueActions.ts:110', f'{GH}/issueActions.ts:98-108', 'Copy the issue URL.', [CLIP('https://github.com/acme/app/issues/7')])
cmd('misc', 'github-actions', 'workbench.agentSessions.action.openPullRequest', f'{GH}/pullRequestActions.ts:75', f'{GH}/pullRequestActions.ts:63-73', 'Open the pull request externally.', [OPEN('https://github.com/acme/app/pull/42')])
cmd('misc', 'github-actions', 'workbench.agentSessions.action.copyPullRequestUrl', f'{GH}/pullRequestActions.ts:143', f'{GH}/pullRequestActions.ts:128-141', 'Copy the pull request URLs.', [CLIP('https://github.com/acme/app/pull/42')])
# agent host provider
AHB = f'{SS}/contrib/providers/agentHost/browser'
cmd('agenthost', 'agent-host-provider-actions', 'workbench.action.chat.forkConversation', f'{AHB}/agentHostForkActions.ts:21', f'{AHB}/agentHostForkActions.ts:22-69', 'Fork the conversation into a new chat of the session.',
    [call('sessions-management-service.fork-chat-in-session', {'session_id': SID_IN, 'provider_id': P})])
cmd('agenthost', 'agent-host-provider-actions', 'sessions.copyAgentHostSessionLink', f'{AHB}/agentHostSessionBranchActions.ts:33', f'{AHB}/agentHostSessionBranchActions.ts:52-59', 'Copy agent host session links.',
    [CLIP('vscode://vscode.agents/open?session=copilot%3A%2F9f2c4e1a')])
cmd('agenthost', 'agent-host-provider-actions', 'sessions.copyAgentHostChatLink', f'{AHB}/agentHostSessionBranchActions.ts:62', f'{AHB}/agentHostSessionBranchActions.ts:76-81', 'Copy an agent host chat link.',
    [CLIP('vscode://vscode.agents/open?session=copilot%3A%2F9f2c4e1a#chat')])
for cid_, reg, run, en, title in [('sessions.agentHost.agentMerge.enableInSession', 244, '261-269', True, 'Enable Agent Merge in the session'),
                                  ('sessions.agentHost.agentMerge.disableInSession', 272, '287-295', False, 'Disable Agent Merge in the session'),
                                  ('sessions.agentHost.agentMerge.enable', 400, '410-420', True, 'Enable Agent Merge (with notification)'),
                                  ('sessions.agentHost.agentMerge.disable', 423, '433-443', False, 'Disable Agent Merge (with notification)')]:
    cmd('agenthost', 'agent-merge-actions', cid_, f'{AMA}:{reg}', f'{AMA}:{run}', title + '.',
        [MERGE_GUARD(f'{AMA}:225-240'), call('local-agent-host-sessions-provider.set-agent-merge-enabled', {'session_id': SID_IN})])
cmd('agenthost', 'agent-merge-actions', 'sessions.agentHost.agentMerge.mergePullRequest.${value}', f'{AMA}:355', f'{AMA}:371-373', 'Set when Agent Merge merges the pull request (always, ifUnchanged, never).',
    [MERGE_GUARD(f'{AMA}:225-240'), call('local-agent-host-sessions-provider.set-agent-merge-overrides', {'session_id': SID_IN})])
cmd('agenthost', 'agent-merge-actions', 'sessions.agentHost.agentMerge.configure', f'{AMA}:446', f'{AMA}:456-485', 'Configure the Agent Merge repair actions.',
    [MERGE_GUARD(f'{AMA}:225-240'), call('local-agent-host-sessions-provider.set-agent-merge-overrides', {'session_id': SID_IN})])
# remote agent hosts
cmd('remote', 'remote-agent-host-actions', 'sessions.remoteAgentHost.add', f'{RAA}:70', f'{RAA}:81-141', 'Add a remote agent host: write chat.remoteAgentHosts, wait for the connection.',
    [CFG('chat.remoteAgentHosts', [{'address': 'ws://build.example.internal:8081', 'name': 'build'}]),
     call('agents-window-remote-agent-host-service.wait-for-connection', {'address': 'ws://build.example.internal:8081'})])
cmd('remote', 'remote-agent-host-actions', 'workbench.action.sessions.connectViaMissionControl', f'{RAA}:144', f'{RAA}:154-170', 'Connect a Mission Control environment, then open a new session in it.',
    [EXEC('workbench.action.chat.connectMissionControlEnvironment'), call('sessions-service.open-new-session', {'folder_uri': 'file:///work/app', 'provider_id': P})])
cmd('remote', 'remote-agent-host-actions', 'workbench.action.sessions.connectViaSSH', f'{RAA}:678', f'{RAA}:696-701', 'Connect via SSH.', [call('ssh-remote-agent-host-service.connect')])
cmd('remote', 'remote-agent-host-actions', 'workbench.action.sessions.addNewSSHHost', f'{RAA}:704', f'{RAA}:715-762', 'Add a new SSH host: ensure ~/.ssh/config, open it with a Host snippet.',
    [call('ssh-remote-agent-host-service.ensure-user-ssh-config'), call('editor-service.open-editor', {'resource': 'file:///home/dev/.ssh/config'})])
cmd('remote', 'remote-agent-host-actions', 'workbench.action.sessions.configureSSHHosts', f'{RAA}:765', f'{RAA}:776-871', 'Configure SSH hosts: pick a config file (created when missing) and open it.',
    [call('ssh-remote-agent-host-service.ensure-user-ssh-config'), call('editor-service.open-editor', {'resource': 'file:///home/dev/.ssh/config'})])
cmd('remote', 'remote-agent-host-actions', 'workbench.action.sessions.connectViaTunnel', f'{RAA}:1122', f'{RAA}:1140-1145', 'Connect via a dev tunnel.', [call('tunnel-agent-host-service.connect')])
cmd('remote', 'remote-agent-host-actions', 'workbench.action.sessions.connectViaWSL', f'{RAA}:1292', f'{RAA}:1316-1321', 'Connect via WSL.', [call('wsl-remote-agent-host-service.connect')])
cmd('remote', 'remote-agent-host-actions', 'workbench.action.sessions.updateRemoteAgentHost', f'{RAA}:1333', f'{RAA}:1344-1392', 'Update incompatible remote agent hosts that advertise an upgrade method.',
    [call('agents-window-remote-agent-host-service.trigger-server-upgrade')])
cmd('remote', 'remote-agent-host-actions', 'workbench.action.sessions.manageRemoteAgentHosts', f'{SS}/contrib/providers/remoteAgentHost/browser/manageRemoteAgentHosts.ts:41',
    f'{SS}/contrib/providers/remoteAgentHost/browser/manageRemoteAgentHosts.ts:52-217', 'Manage remote agent hosts; removing a WebSocket host rewrites chat.remoteAgentHosts.',
    [CFG('chat.remoteAgentHosts', []), call('agents-window-remote-agent-host-service.remove-remote-agent-host', {'address': 'ws://build.example.internal:8081'})])
RAE = f'{SS}/contrib/providers/remoteAgentHost/electron-browser'
cmd('remote', 'remote-agent-host-actions', 'workbench.action.chat.forgetSSHHostKey', f'{RAE}/forgetSSHHostKeyCommand.ts:45', f'{RAE}/forgetSSHHostKeyCommand.ts:59-88', 'Forget saved SSH host keys.',
    [call('ssh-host-key-trust-service.forget-host', {'host': 'build.example.internal:22'})])
cmd('remote', 'remote-agent-host-actions', 'workbench.action.sessions.changeRemoteAgentHostLocationPreference', f'{RAE}/remoteAgentHostLocationPreferenceCommand.ts:135',
    f'{RAE}/remoteAgentHostLocationPreferenceCommand.ts:149-183', 'Change where a remote agent host runs, then reconnect it.',
    [call('remote-agent-host-location-preference-service.set-preference', {'host': 'build-box', 'preference': 'remote'})])
# desktop/web window commands and MCP
cmd('window', 'sessions-vscode-actions', 'agents.openSessionInVSCode', f'{SS}/electron-browser/sessions.desktop.contribution.ts:12', f'{VSA}:57-93', 'Open the session folder in a new VS Code window.',
    [call('native-host-service.open-window', {'folder_uris': ['file:///work/app'], 'force_new_window': True})])
cmd('window', 'sessions-vscode-actions', 'agents.openVSCodeWindow', f'{SS}/electron-browser/sessions.desktop.contribution.ts:13', f'{VSA}:119-131', 'Focus another VS Code window, or open one.',
    [call('native-host-main-service.get-windows', {'window_id': 'w1'}, 'ws'), call('native-host-service.open-window', {'folder_uris': []})])
cmd('window', 'sessions-vscode-actions', 'agents.returnToVSCodeEditor', f'{SS}/electron-browser/sessions.desktop.contribution.ts:14', f'{VSA}:143-146', 'Open a VS Code window and close the Agents window.',
    [call('native-host-service.open-window', {'folder_uris': []}), call('native-host-service.close-window')])
cmd('window', 'sessions-vscode-actions', 'agents.shouldShowReturnToVSCodeEditor', f'{SS}/electron-browser/sessions.desktop.contribution.ts:15', f'{VSA}:158-162', 'True when no other main window is open.',
    [call('native-host-main-service.get-windows', {'window_id': 'w1'}, 'ws')])
cmd('window', 'sessions-vscode-actions', 'sessions.openInVSCode', f'{SS}/browser/sessions.web.contribution.ts:12', f'{SS}/browser/actions/vscodeActions.ts:49-106', 'Web: open the session in desktop VS Code through a vscode:// link.',
    [OPEN('vscode://file/work/app?windowId=_blank&session=copilot%3A%2F9f2c4e1a')])
cmd('window', 'mcp-commands', 'workbench.mcp.setOAuthClientSecret', f'{MCON}:91', f'{MCMD}:1244-1322', 'Set (or, when empty, delete) the OAuth client secret of an MCP server.',
    [{'if': "input.secret == ''", 'then': [call('secret-storage-service.delete', {'key': 'mcp.oauth.clientSecret'}), RET(ok=True)]},
     call('secret-storage-service.set', {'key': 'mcp.oauth.clientSecret', 'value': '= input.secret'})], req=obj({'secret': s('cs_demo', default='cs_demo')}))

# ---------------- scenarios that run every command (one world per group)
_GROUP_STATE = {
    'sessions': WS_SEEDED, 'chat': WS_SEEDED, 'automations': WS_SEEDED, 'misc': WS_SEEDED, 'agenthost': WS_SEEDED, 'remote': {}, 'window': {},
}
_GROUP_EXPECT = {
    'sessions': ["trace.exists(e, e.type == 'call.end' && e.interface == 'local-agent-host-sessions-provider.set-session-read-state' && e.output.changed)",
                 "!('g1' in state['session-groups-service@w1'].groups)", "state['sessions-service@w1'].closed_chats >= 2"],
    'chat': ["state['sessions-chat-background-service@w1'].background == 'codicons'", "state['sessions-tasks-service@w1'].runs == 2"],
    'automations': ["trace.exists(e, e.type == 'call.start' && e.interface == 'automation-service.create-automation')"],
    'misc': ["state['agent-feedback-service@w1'].submitted == 2", "state['session-changes-service@w1'].operations_run.size() == 3"],
    'agenthost': ["state['local-agent-host-sessions-provider@w1'].session_cache['local-agent-host/9f2c4e1a'].agent_merge == true"],
    'remote': ["state['ssh-remote-agent-host-service@w1'].connected == ['build-box']", "state['remote-agent-host-location-preference-service@w1'].preferences['build-box'] == 'remote'"],
    'window': ["trace.exists(e, e.type == 'call.start' && e.interface == 'native-host-service.close-window')"],
}
for grp, ifs in GROUPS.items():
    sc = {'id': f'agents-commands-{grp}', 'name': f'Run the {grp} commands', 'fixtures': ['one-window-folder', 'agents-seed'],
          'steps': [{'interface': i, 'caller': 'user', 'as': f's{n}'} for n, i in enumerate(ifs)],
          'expect': [f"trace.exists(e, e.type == 'call.start' && e.interface == '{i}')" for i in ifs] + _GROUP_EXPECT.get(grp, [])}
    if grp == 'automations':
        sc['config'] = {'chat-automations-enabled': True}
    if _GROUP_STATE.get(grp):
        sc['state'] = _GROUP_STATE[grp]
    scenarios.append(sc)
# branches: guards and refusals
scenarios.append({'id': 'agents-commands-automations-disabled', 'fixtures': ['one-window-folder', 'agents-seed'],
                  'steps': [{'interface': 'automations-view-actions.' + cmd_slug('sessionsView.newAutomation'), 'caller': 'user'}],
                  'expect': ['!result.value.ok', "!trace.exists(e, e.type == 'call.start' && e.interface == 'automation-service.create-automation')"]})
scenarios.append({'id': 'agents-commands-agent-merge-artifacts-on', 'fixtures': ['one-window-folder', 'agents-seed'], 'config': {'chat-artifact-integrations-enabled': True},
                  'steps': [{'interface': 'agent-merge-actions.' + cmd_slug('sessions.agentHost.agentMerge.enable'), 'caller': 'user'}],
                  'expect': ['!result.ok', "result.error.message == 'Agent Merge is unavailable while artifact integrations are enabled.'"]})
scenarios.append({'id': 'agents-commands-sync-unavailable', 'fixtures': ['one-window-folder', 'agents-seed'],
                  'steps': [{'interface': 'changes-actions.' + cmd_slug('workbench.action.sessions.syncChanges'), 'caller': 'user', 'input': {'sync_available': False}}],
                  'expect': ['!result.ok', "result.error.code == 'sync-unavailable'", "state['session-changes-service@w1'].operations_run == []"]})
scenarios.append({'id': 'agents-commands-oauth-secret-cleared', 'fixtures': ['one-window-folder', 'agents-seed'],
                  'steps': [{'interface': 'mcp-commands.' + cmd_slug('workbench.mcp.setOAuthClientSecret'), 'caller': 'user', 'input': {'secret': ''}}],
                  'expect': ["trace.exists(e, e.type == 'call.start' && e.interface == 'secret-storage-service.delete')"]})
scenarios.append({'id': 'agents-commands-rename-chat-empty', 'fixtures': ['one-window-folder', 'agents-seed'], 'state': WS_SEEDED,
                  'steps': [{'interface': 'sessions-actions.' + cmd_slug('sessions.chatCompositeBar.renameChat'), 'caller': 'user', 'input': {'title': '  '}}],
                  'expect': ['!result.value.ok', "!trace.exists(e, e.type == 'call.start' && e.interface == 'sessions-management-service.rename-chat')"]})
scenarios.append({'id': 'agents-commands-mark-read-not-cached', 'fixtures': ['one-window-folder', 'agents-seed'], 'state': {'sessions-providers-service@w1': SEED_PROVIDERS},
                  'steps': [{'interface': 'sessions-view-actions.' + cmd_slug('MARK_SESSION_READ_COMMAND_ID'), 'caller': 'user'}],
                  'expect': ["trace.exists(e, e.type == 'call.end' && e.interface == 'local-agent-host-sessions-provider.set-session-read-state' && !e.output.changed)",
                             "state['local-agent-host-sessions-provider@w1'].session_cache == {}"]})
scenarios.append({'id': 'agents-commands-mark-unread-unknown-provider', 'fixtures': ['one-window-folder', 'agents-seed'],
                  'steps': [{'interface': 'sessions-view-actions.' + cmd_slug('MARK_SESSION_UNREAD_COMMAND_ID'), 'caller': 'user'}],
                  'expect': ["trace.exists(e, e.type == 'call.end' && e.interface == 'sessions-management-service.mark-unread' && !e.output.done)",
                             "!has(state['sessions-management-service@w1'].explicitly_unread)"]})
scenarios.append({'id': 'agents-commands-sign-out-cancelled', 'fixtures': ['one-window-folder', 'agents-seed'],
                  'choices': {}, 'steps': [{'interface': 'account-actions.' + cmd_slug('workbench.action.agenticSignOut'), 'caller': 'user'}],
                  'expect': ["trace.exists(e, e.type == 'call.start' && e.interface == 'dialog-service.confirm')"]})
for i in interfaces:
    if i.get('kind') == 'command' and i['name'].startswith('cmd-') and 'command_id' not in (i.get('attributes') or {}):
        pass

# Reconciliation round, part 3: command ids for the registry seed, fixtures on every scenario, skips.
_CONST = {'CLOSE_SESSION_COMMAND_ID': 'sessions.chatCompositeBar.close', 'MARK_SESSION_READ_COMMAND_ID': 'agentSession.markRead',
          'MARK_SESSION_UNREAD_COMMAND_ID': 'agentSession.markUnread', 'NewChatInSessionsWindowAction': 'workbench.action.sessions.newChat',
          'AddConfigurationAction': 'workbench.mcp.addConfiguration'}
_slug2id = {}
for e in MINE:
    if e['kind'] == 'vscode-command' and '$' not in e['name']:
        _slug2id[cmd_slug(e['name'])] = _CONST.get(e['name'], e['name'])
for i in interfaces:
    if i.get('kind') == 'command' and i['name'] in _slug2id and not (i.get('attributes') or {}).get('boundary'):
        i.setdefault('attributes', {})['command_id'] = _slug2id[i['name']]
fixtures.append({'id': 'agents-seed', 'summary': "The agents area's commands registered in platform-core's commands registry (decision 6).",
                 'state': {'commands-registry': {'commands': _cmd_registry()}}})
for sc in scenarios:
    fx = sc.get('fixtures') or ['one-window-folder']
    if 'agents-seed' not in fx:
        fx = fx + ['agents-seed']
    if (sc['id'].startswith('agents-mcp') or sc['id'].startswith('agents-sessions-window-startup')) and 'agents-mcp-servers' not in fx:
        fx = [x for x in fx if x != 'one-window-folder'] + ['agents-mcp-servers']
        fx = ['agents-mcp-servers'] + [x for x in fx if x != 'agents-mcp-servers']
    sc['fixtures'] = fx

# ---------------- skips: only the reasons decision 11 accepts
UI_REASON = 'UI toggle: no state beyond the layout (focus, navigation, view mode, or opening a view, editor or picker)'
ANCHOR_REASON = 'not an entry point: run() is empty; the id only anchors a picker or widget view item'
DEV_REASON = 'developer or internal tooling with no user-visible behavior'
INTERNAL_REASON = 'developer or internal tooling: internal command (underscore id) invoked by the voice or review bridges, not by users'
ANCHORS = {'sessions.action.titleBarAccountWidget', 'chatEditing.versionsPicker', 'workbench.changesView.headerActions', 'sessions.modelPicker',
           'sessions.newChatComposer.sessionControls', 'workbench.action.agentSessions.runScript.notAvailable', 'sessions.agentHost.mobileChatInputConfigPicker',
           'sessions.agentHostFilter.pick', 'sessions.agentHost.newSessionApprovePicker', 'sessions.agentHost.newSessionPermissionModePicker',
           'sessions.agentHost.newSessionCodexApprovalsPicker', 'sessions.agentHost.newSessionModePicker', 'sessions.agentHost.runningSessionConfigPicker',
           'sessions.agentHost.runningSessionPermissionModePicker', 'sessions.agentHost.runningSessionCodexApprovalsPicker'}
DEVS = {'sessions.showSessionDetails', 'sessions.updateSessionFoldersWithChats', 'sessions.getStarted.reset', 'sessions.showConnectionDiagnostics',
        'workbench.action.chat.debugAgentHostInDevTools', 'workbench.action.chat.profileAgentHost', 'workbench.action.chat.stopAgentHostProfile',
        'sessions.customView.showTestView', 'sessions.customView.hideTestView', 'sessions.customView.testView.ping', 'sessions.aquarium.simulateStreak',
        'sessions.aquarium.toggleActionVisibility', 'sessions.debug.showFakeChatPills', 'agentSession.dumpTerminalTracking', 'agentHost.exportDebugLogs',
        'OpenAgentHostStateFileAction', 'workbench.action.chat.renderAutomationsHarnessChip', 'workbench.action.chat.renderAutomationsWorkspacePicker',
        'workbench.action.chat.renderAutomationsIsolationGroup'}
NOT_ENTRY = {'action': 'not an entry point: the loop that registers the archive action set (SessionsArchiveActionsContribution); the actions are registered per wording',
             'externalCommand': 'not an entry point: the web factory registers embedder-supplied commands under ids the embedder chooses',
             'Menus.SessionActivityBarCanvas.id': 'not an entry point: a menu id constant matched by the command heuristic, not a command registration'}


def _skip_reason(e):
    k, n = e['kind'], e['name']
    if k == 'service':
        return OTHER_AREA_SKIPS.get(f"{e['file']}:{e['line']}")
    if k != 'vscode-command':
        return None
    if n in NOT_ENTRY:
        return NOT_ENTRY[n]
    if n in ANCHORS:
        return ANCHOR_REASON
    if n in DEVS:
        return DEV_REASON
    if n.startswith('_'):
        return INTERNAL_REASON
    return UI_REASON  # only applied to commands left without a modeled interface


_modeled_cmd_names = set()
for i in interfaces:
    cid_ = (i.get('attributes') or {}).get('command_id')
    if cid_:
        _modeled_cmd_names.add(cid_)
_modeled_slugs = {i['name'] for i in interfaces if i.get('kind') == 'command'}
SKIPS = []
for e in MINE:
    if e['kind'] == 'vscode-command':
        if cmd_slug(e['name']) in _modeled_slugs:
            continue
        r = _skip_reason(e)
    elif e['kind'] == 'service':
        r = _skip_reason(e)
    else:
        r = None
    if r:
        SKIPS.append({'kind': e['kind'], 'name': e['name'], 'file': e['file'], 'line': e['line'], 'reason': r})
_json.dump(SKIPS, open(f'{VS}/skips/agents.json', 'w'), indent=1)
print('skips', len(SKIPS))

from base import *
TB='src/vs/workbench/contrib/terminal/browser/'
TC='src/vs/workbench/contrib/terminal/common/'
TE='src/vs/workbench/contrib/terminal/electron-browser/'
TCO='src/vs/workbench/contrib/terminalContrib/'
PT='src/vs/platform/terminal/'
T_SVC=TB+'terminalService.ts'; T_IF=TB+'terminal.ts'; T_CIF=TC+'terminal.ts'; T_PM=TB+'terminalProcessManager.ts'
T_LB=TE+'localTerminalBackend.ts'; T_INST=TB+'terminalInstanceService.ts'; P_IF=PT+'common/terminal.ts'
P_PHS=PT+'node/ptyHostService.ts'; P_PS=PT+'node/ptyService.ts'; P_MAIN=PT+'node/ptyHostMain.ts'; P_HB=PT+'node/heartbeatService.ts'; P_TP=PT+'node/terminalProcess.ts'
T_CFG=TC+'terminalConfiguration.ts'; T_CONTRIB=TB+'terminal.contribution.ts'

# ---------------- configs ----------------
config('terminal-integrated-enable-persistent-sessions','terminal.integrated.enablePersistentSessions','boolean',True,True,
  'Persist terminal sessions/history across window reloads. product.json sets nothing, so deployed == registered default.',
  [S(T_CFG,565,568),'product.json'])
config('terminal-integrated-persistent-session-revive-process','terminal.integrated.persistentSessionReviveProcess','string','onExit','onExit',
  'When to revive terminal processes after shutdown (onExit | onExitAndWindowClose | never). No product.json override.',
  [S(T_CFG,570,580),'product.json'])
config('terminal-integrated-confirm-on-exit','terminal.integrated.confirmOnExit','string','never','never',
  'Confirm window close when terminals are active (never | always | hasChildProcesses). No product.json override.',
  [S(T_CFG,401,411),'product.json'])
config('terminal-integrated-auto-replies','terminal.integrated.autoReplies','object',{},{},
  'Messages auto-answered in the terminal; empty by default. No product.json override.',
  [S('src/vs/workbench/contrib/terminalContrib/autoReplies/common/terminalAutoRepliesConfiguration.ts',19,31),'product.json'])
config('pty-host-heartbeat-beat-interval-ms','HeartbeatConstants.BeatInterval','integer',5000,5000,
  'Code constant (not a setting): the pty host fires a heartbeat every 5000 ms.',[S(P_IF,476)],extra={'constant':True})
config('pty-host-heartbeat-connecting-interval-ms','HeartbeatConstants.ConnectingBeatInterval','integer',20000,20000,
  'Code constant: first wait after the pty host (re)starts before warning about a missing heartbeat.',[S(P_IF,482)],extra={'constant':True})
config('pty-host-heartbeat-first-wait-ms','HeartbeatConstants.BeatInterval*FirstWaitMultiplier','integer',6000,6000,
  'Code constant: BeatInterval 5000 x FirstWaitMultiplier 1.2 = 6000 ms before the warning timer.',[S(P_IF,476),S(P_IF,487)],extra={'constant':True})
config('pty-host-heartbeat-second-wait-ms','HeartbeatConstants.BeatInterval*SecondWaitMultiplier','integer',5000,5000,
  'Code constant: BeatInterval 5000 x SecondWaitMultiplier 1 = 5000 ms before the pty host is declared unresponsive.',[S(P_IF,476),S(P_IF,493)],extra={'constant':True})
config('pty-host-max-restarts','Constants.MaxRestarts','integer',5,5,
  'Code constant: the main process restarts a crashed pty host while restartCount <= 5.',[S(P_PHS,26,28)],extra={'constant':True})
config('pty-reconnect-grace-time-ms','LocalReconnectConstants.GraceTime','integer',60000,60000,
  'Code constant passed by the main process (app.ts) as VSCODE_RECONNECT_GRACE_TIME: a detached persistent process is killed after 60 s without reconnect.',
  [S(P_IF,885),S(P_MAIN,33,37)],extra={'constant':True})
config('pty-reconnect-short-grace-time-ms','LocalReconnectConstants.ShortGraceTime','integer',6000,6000,
  'Code constant: shortened grace time once a window has reconnected (reduceConnectionGraceTime).',[S(P_IF,889),S(P_MAIN,33,37)],extra={'constant':True})
config('pty-orphan-question-timeout-ms','AutoOpenBarrier(4000)','integer',4000,4000,
  'Code constant: the pty host waits up to 4000 ms for a window to claim a process before treating it as an orphan.',[S(P_PS,1013)],extra={'constant':True})
config('terminal-persist-state-timeout-ms','timeout(2000) in _onBeforeShutdownAsync','integer',2000,2000,
  'Code constant: persisting terminal buffers on shutdown races a 2000 ms timeout.',[S(T_SVC,642,649)],extra={'constant':True})
config('terminal-save-state-debounce-ms','@debounce(500) on _saveState','integer',500,500,
  'Code constant: layout saves to the pty host are debounced by 500 ms.',[S(T_SVC,723,724)],extra={'constant':True})

# ---------------- shared terminal schemas ----------------
SCHEMAS.append({'id':'TerminalShellLaunchConfig','summary':'IShellLaunchConfig subset the terminal area reads.','schema':obj({
  'executable':st('/bin/bash'),'args':arr(st(),default=[]),'cwd':st('file:///work/app'),'name':st('bash'),
  'hide_from_user':bo(False),'is_feature_terminal':bo(False),'is_transient':bo(False),'force_persist':bo(False),
  'attach_persistent_process':{'type':['object','null'],'default':None,'properties':{'id':it(1),'pid':it(4242),'find_revived_id':bo(False),'type':st('Task')}},
  'reconnection_properties':{'type':['object','null'],'default':None},
  'task_key':{'type':['string','null'],'default':None}})})
SCHEMAS.append({'id':'TerminalInstanceInfo','summary':'A terminal instance as TerminalService tracks it.','schema':obj({
  'instance_id':it(1),'persistent_process_id':{'type':['integer','null']},'location':st('panel',enum=['panel','editor']),
  'shell':st('/bin/bash'),'cwd':st('file:///work/app'),'process_state':st('running',enum=['uninitialized','launching','running','killed-during-launch','killed-by-user','killed-by-process']),
  'should_persist':bo(),'hide_from_user':bo(),'launch_error':{'type':['string','null']}})})

# ---------------- components ----------------
comp('terminal-contrib','Terminal contribution','workbench','Terminal workbench contribution module: registers terminal services, views, commands and workbench contributions.',
  [S(T_CONTRIB,52,60),S(T_CONTRIB,64,65),S(TE+'terminal.contribution.ts',21,30)])
comp('terminal-service','TerminalService','terminal-contrib','Owns terminal instances in a window: creation, the primary pty backend, reconnect on reload and shutdown persistence.',
  [CL(T_SVC,'TerminalService'),S(T_IF,41),S(T_CONTRIB,54)],
  state={'schema':obj({'instances':ob(),'next_instance_id':it(),'backgrounded':arr(it()),'connection_state':st(),'is_shutting_down':bo(),'active_instance':{'type':['integer','null']},'restored_group_count':it(),'layout_listeners_attached':bo()}),
         'initial':{'instances':{},'next_instance_id':1,'backgrounded':[],'connection_state':'none','is_shutting_down':False,'active_instance':None,'restored_group_count':0,'layout_listeners_attached':False}},
  capacity={'concurrency':1})
comp('terminal-configuration-service','TerminalConfigurationService','terminal-contrib','Reads the terminal.integrated.* configuration section for the rest of the terminal code.',
  [CL(TB+'terminalConfigurationService.ts','TerminalConfigurationService'),S(T_IF,42),S(T_CONTRIB,53)])
comp('terminal-instance-service','TerminalInstanceService','terminal-contrib','Creates TerminalInstance objects and resolves the registered pty backend for a remote authority.',
  [CL(T_INST,'TerminalInstanceService'),S(T_IF,46),S(T_INST,106)],
  state={'schema':obj({'backends':ob()}),'initial':{'backends':{}}})
comp('terminal-process-manager','TerminalProcessManager','terminal-contrib','Per-instance process manager: attaches to a persistent process or launches a new one through the backend, tracks ProcessState.',
  [CL(T_PM,'TerminalProcessManager')])
comp('terminal-profile-service','TerminalProfileService','terminal-contrib','Holds detected and contributed terminal profiles and the default profile per OS.',
  [CL(TB+'terminalProfileService.ts','TerminalProfileService'),S(T_CIF,67),S(T_CONTRIB,59)],
  state={'schema':obj({'available_profiles':ob(),'default_profile_name':st()}),
         'initial':{'available_profiles':{'bash':{'profile_name':'bash','path':'/bin/bash','args':[]}},'default_profile_name':'bash'}})
comp('terminal-profile-resolver-service','ElectronTerminalProfileResolverService','terminal-contrib','Resolves the executable, args and environment of a shell launch config from the default profile.',
  [CL(TE+'terminalProfileResolverService.ts','ElectronTerminalProfileResolverService'),CL(TB+'terminalProfileResolverService.ts','BaseTerminalProfileResolverService'),S(T_CIF,45),S(TE+'terminal.contribution.ts',22)])
comp('terminal-group-service','TerminalGroupService','terminal-contrib','Terminal groups (tabs) in the panel and which instance is active.',
  [CL(TB+'terminalGroupService.ts','TerminalGroupService'),S(T_IF,45),S(T_CONTRIB,57)],
  state={'schema':obj({'groups':arr(arr(it())),'active_index':it()}),'initial':{'groups':[],'active_index':-1}})
comp('terminal-editor-service','TerminalEditorService','terminal-contrib','Terminals shown as editors in editor groups.',
  [CL(TB+'terminalEditorService.ts','TerminalEditorService'),S(T_IF,43),S(T_CONTRIB,55)],
  state={'schema':obj({'instances':arr(it())}),'initial':{'instances':[]}})
comp('terminal-editing-service','TerminalEditingService','terminal-contrib','Tracks which terminal tab is being renamed inline (editable data).',
  [CL(TB+'terminalEditingService.ts','TerminalEditingService'),S(T_IF,44),S(T_CONTRIB,56)],
  state={'schema':obj({'editable':ob(),'editing_terminal':{'type':['integer','null']}}),'initial':{'editable':{},'editing_terminal':None}})
comp('environment-variable-service','EnvironmentVariableService','terminal-contrib','Merges extension-contributed environment variable collections applied to new terminals.',
  [CL(TC+'environmentVariableService.ts','EnvironmentVariableService'),S(TC+'environmentVariable.ts',12),S(TC+'environmentVariable.contribution.ts',10)],
  state={'schema':obj({'collections':ob()}),'initial':{'collections':{}}})
comp('terminal-contribution-service','TerminalContributionService','terminal-contrib','Handler of the "terminal" extension point: contributed terminal profiles.',
  [CL(TC+'terminalExtensionPoints.ts','TerminalContributionService'),S(TC+'terminalExtensionPoints.ts',30),S(TC+'terminalExtensionPoints.ts',16),S(TC+'terminalExtensionPoints.contribution.ts',9)],
  state={'schema':obj({'terminal_profiles':arr()}),'initial':{'terminal_profiles':[]}})
comp('terminal-log-service','TerminalLogService','terminal-contrib','The terminal log channel used by the renderer side.',
  [CL(PT+'common/terminalLogService.ts','TerminalLogService'),S(P_IF,1280),S(T_CONTRIB,52)])
comp('local-terminal-backend','LocalTerminalBackend','terminal-contrib','The local pty backend in the renderer: talks to the pty host directly over a message port, persists layout and buffers in workspace storage.',
  [CL(T_LB,'LocalTerminalBackend')],
  state={'schema':obj({'ptys':ob(),'direct_proxy':bo(),'workspace_storage':ob()}),'initial':{'ptys':{},'direct_proxy':False,'workspace_storage':{}}})
comp('local-pty','LocalPty','terminal-contrib','Renderer proxy for one pty host process (start, input, shutdown, detach).',[CL(TE+'localPty.ts','LocalPty')])
comp('local-terminal-backend-contribution','LocalTerminalBackendContribution','terminal-contrib','Workbench contribution that registers the local terminal backend.',[CL(T_LB,'LocalTerminalBackendContribution'),S(TE+'terminal.contribution.ts',29)])
comp('remote-terminal-backend-contribution','RemoteTerminalBackendContribution','terminal-contrib','Workbench contribution that registers the remote terminal backend when connected to a remote.',[CL(TB+'remoteTerminalBackend.ts','RemoteTerminalBackendContribution'),S(T_CONTRIB,65)])
comp('terminal-main-contribution','TerminalMainContribution','terminal-contrib','Workbench contribution wiring embedder terminals and terminal editors after the Restored phase.',[CL(TB+'terminalMainContribution.ts','TerminalMainContribution'),S(T_CONTRIB,64)])
comp('terminal-native-contribution','TerminalNativeContribution','terminal-contrib','Electron contribution: sets the native window-count delegate used on shutdown and handles open-file requests from the terminal.',[CL(TE+'terminalNativeContribution.ts','TerminalNativeContribution'),S(TE+'terminal.contribution.ts',30)])
comp('agent-host-terminal-service','AgentHostTerminalService','terminal-contrib','Creates terminals for agent-host connections (chat agents running commands).',
  [CL(TB+'agentHostTerminalService.ts','AgentHostTerminalService'),S(TB+'agentHostTerminalService.ts',62),S(T_CONTRIB,60)],
  state={'schema':obj({'entries':ob()}),'initial':{'entries':{}}})
# terminalContrib services
comp('terminal-link-provider-service','TerminalLinkProviderService','terminal-contrib','Extension-registered terminal link providers consulted by each instance\'s link manager.',
  [CL(TCO+'links/browser/terminalLinkProviderService.ts','TerminalLinkProviderService'),S(TCO+'links/browser/links.ts',19),S(TCO+'links/browser/terminal.links.contribution.ts',24)],
  state={'schema':obj({'link_providers':arr()}),'initial':{'link_providers':[]}})
comp('terminal-quick-fix-service','TerminalQuickFixService','terminal-contrib','Quick fix providers and the terminalQuickFixes extension point handler.',
  [CL(TCO+'quickFix/browser/terminalQuickFixService.ts','TerminalQuickFixService'),S(TCO+'quickFix/browser/quickFix.ts',15),S(TCO+'quickFix/browser/terminal.quickFix.contribution.ts',25),S(TCO+'quickFix/browser/terminalQuickFixService.ts',94)],
  state={'schema':obj({'providers':ob(),'extension_quick_fixes':arr()}),'initial':{'providers':{},'extension_quick_fixes':[]}})
comp('terminal-completion-service','TerminalCompletionService','terminal-contrib','Terminal suggest completion providers.',
  [CL(TCO+'suggest/browser/terminalCompletionService.ts','TerminalCompletionService'),S(TCO+'suggest/browser/terminalCompletionService.ts',27),S(TCO+'suggest/browser/terminal.suggest.contribution.ts',44)],
  state={'schema':obj({'providers':ob()}),'initial':{'providers':{}}})
comp('terminal-chat-service','TerminalChatService','terminal-contrib','Tracks terminals created by chat tool sessions and per-session auto approval.',
  [CL(TCO+'chat/browser/terminalChatService.ts','TerminalChatService'),S(T_IF,47),S(TCO+'chat/browser/terminal.chat.contribution.ts',39)],
  state={'schema':obj({'tool_session_terminals':ob(),'auto_approval':ob(),'most_recent_progress_part':{'type':['string','null']}}),'initial':{'tool_session_terminals':{},'auto_approval':{},'most_recent_progress_part':None}})
comp('terminal-chat-session-resolver','TerminalChatSessionResolver','terminal-contrib','Resolves the chat session a terminal chat widget should use.',
  [CL(TCO+'chat/browser/terminalChatSessionResolver.ts','TerminalChatSessionResolver'),S(TCO+'chat/browser/terminalChatSessionResolver.ts',16),S(TCO+'chat/browser/terminal.chat.contribution.ts',40)])
# pty host process
comp('pty-host-service','PtyHostService','pty-host','Main-process supervisor of the pty host utility process: starts it on demand, watches its heartbeat and restarts it after a crash. Implements ILocalPtyService for windows.',
  [CL(P_PHS,'PtyHostService'),S(P_IF,1271),S(TE+'terminal.contribution.ts',21)],
  attributes={'runs_in':'main-process'},layer='process',
  state={'schema':obj({'started':bo(),'responsive':bo(),'restart_count':it(),'last_beat_at':it(),'quit_requested':bo(),'start_count':it()}),
         'initial':{'started':False,'responsive':True,'restart_count':0,'last_beat_at':0,'quit_requested':False,'start_count':0}})
comp('pty-host-main','ptyHostMain','pty-host','Entry point of the pty host process: sets up the IPC server and registers the logger, heartbeat, ptyHost and ptyHostWindow channels.',
  [S(P_MAIN,27),S(P_MAIN,29,104),S(P_MAIN,67),S(P_MAIN,84),S(P_MAIN,89),S(P_MAIN,93)],layer='process')
comp('heartbeat-service','HeartbeatService','pty-host','Fires onBeat every BeatInterval inside the pty host.',[CL(P_HB,'HeartbeatService',True)],layer='process')
comp('pty-service','PtyService','pty-host','The pty host\'s IPtyService: persistent terminal processes by id, per-workspace layout, revive and reconnect, orphan detection.',
  [CL(P_PS,'PtyService'),S(P_IF,408),CL(P_PS,'PersistentTerminalProcess')],layer='process',
  state={'schema':obj({'ptys':ob(),'last_pty_id':it(),'layouts':ob(),'revived':ob()}),
         'initial':{'ptys':{},'last_pty_id':0,'layouts':{},'revived':{}}})
comp('terminal-process','TerminalProcess','pty-host','A node-pty shell process: validates cwd and executable, then spawns.',[CL(P_TP,'TerminalProcess')],layer='process')

# ---------------- boundary stubs ----------------
stub('extension-service','activate-by-event','exthost','Activate extensions listening to an activation event.',
  request=obj({'activation_event':st('onTerminal:*')},['activation_event']),response=ob())
stub('lifecycle-service','on-before-shutdown','workbench-shell','onBeforeShutdown event; listeners may veto.',kind='event',
  request=obj({'reason':st('reload',enum=['close','quit','reload','load'])},['reason']),response=obj({'veto':bo(False)}))
stub('native-host-main-service','get-window-count','main-process','Number of open windows (main process).',request=obj({'window_id':st('w1')}),response=obj({'count':it(1,default=1)}),kind='ipc')
stub('workspace-trust-management-service','is-workspace-trusted','workbench-shell','Whether the workspace is trusted.',response=obj({'trusted':bo(True)}))
stub('workspace-trust-request-service','request-workspace-trust','workbench-shell','Ask the user to trust the workspace (modal when untrusted).',
  request=obj({'message':st()}),response=obj({'trusted':bo(True)}))
stub('editor-service','save-all','workbench-shell','Save all dirty editors.',request=obj({'reason':st('explicit')}),response=obj({'saved':bo(True)}))
stub('editor-service','open-editor','workbench-shell','Open an editor.',request=obj({'resource':st('file:///work/app/.vscode/launch.json')}),response=ob())
stub('views-service','open-view','workbench-shell','Open a view by id.',request=obj({'id':st('workbench.panel.output')}),response=ob())
stub('command-service','execute-command','platform-core','Execute a registered command.',request=obj({'command_id':st(),'args':arr()},['command_id']),response=ob(),
  errors=[{'code':'command-not-found','status':0,'retryable':False}])

# ---------------- interfaces: configuration, profiles ----------------
iface('terminal-configuration-service','get-config','The terminal.integrated config values TerminalService reads.',[S(TB+'terminalConfigurationService.ts',28),S(TB+'terminalConfigurationService.ts',59,63)],
  response=obj({'enable_persistent_sessions':bo(),'persistent_session_revive_process':st(),'confirm_on_exit':st()}),
  behavior=[{'return':{'enable_persistent_sessions':"= config['terminal-integrated-enable-persistent-sessions']",
     'persistent_session_revive_process':"= config['terminal-integrated-persistent-session-revive-process']",
     'confirm_on_exit':"= config['terminal-integrated-confirm-on-exit']"}}])
iface('terminal-profile-service','get-default-profile','Default profile for the OS (terminal.integrated.defaultProfile.*).',[M(TB+'terminalProfileService.ts','getDefaultProfile')],
  response=obj({'profile_name':st(),'path':st(),'args':arr()}),
  behavior=[{'if':"state.default_profile_name in state.available_profiles",'then':[{'return':"= state.available_profiles[state.default_profile_name]"}]},
            {'title':'No configured default: fall back to the first available profile','source':M(TB+'terminalProfileService.ts','getDefaultProfile'),
             'return':"= state.available_profiles[state.available_profiles.map(k, k)[0]]"}])
iface('terminal-profile-resolver-service','resolve-shell-launch-config','Fill executable/args of a launch config from the default profile when it has none.',[M(TB+'terminalProfileResolverService.ts','resolveShellLaunchConfig')],
  request=obj({'executable':st(default=''),'args':arr()}),response=obj({'executable':st(),'args':arr()}),
  behavior=[{'if':"input.executable != ''",'then':[{'return':{'executable':"= input.executable",'args':"= input.args"}}]},
            {'call':'terminal-profile-service.get-default-profile','as':'p'},
            {'return':{'executable':"= vars.p.value.path",'args':"= vars.p.value.args"}}])
iface('environment-variable-service','get-merged-collection','The merged extension environment collection applied to a new terminal.',[S(TC+'environmentVariableService.ts',33),S(TC+'environmentVariableService.ts',62)],
  response=obj({'collections':ob()}),behavior=[{'return':{'collections':"= state.collections"}}])
iface('terminal-log-service','warn','Log a warning to the Terminal log channel.',[M(PT+'common/terminalLogService.ts','warn')],request=obj({'message':st()}),response=ob(),
  behavior=[{'set':{'ctx.terminal_log_warning':"= input.message"}}])

# ---------------- interfaces: instance service, process manager ----------------
iface('terminal-instance-service','get-backend','Resolve the registered backend for a remote authority (waits for it to register).',[M(T_INST,'getBackend')],
  request=obj({'remote_authority':{'type':['string','null'],'default':None}}),response=obj({'backend':st()}),
  errors=[{'code':'no-terminal-backend','status':0,'retryable':False}],
  behavior=[{'set':{'vars.key':"= input.remote_authority == null ? 'local' : input.remote_authority"}},
            {'if':"!(vars.key in state.backends) || !state.backends[vars.key]",'then':[{'title':'No backend registered for the authority','source':S(T_PM,269,272),
               'fail':{'code':'no-terminal-backend','message':"= 'No terminal backend registered for remote authority ' + vars.key"}}]},
            {'return':{'backend':"= vars.key"}}])
iface('terminal-instance-service','did-register-backend','A backend registered itself (local or remote).',[M(T_INST,'didRegisterBackend')],request=obj({'backend':st('local')}),response=ob(),
  behavior=[{'set':{'state.backends':"= merge(state.backends, {input.backend: true})"}}])
iface('terminal-instance-service','create-instance','Create a TerminalInstance; its constructor launches the process through a TerminalProcessManager and attaches per-instance contributions (links, quick fixes, suggest).',
  [M(T_INST,'createInstance',48)],request='TerminalShellLaunchConfig',response='TerminalInstanceInfo',
  behavior=[{'call':'terminal-link-provider-service.get-link-providers','as':'links'},
            {'call':'terminal-quick-fix-service.get-providers','as':'qf'},
            {'call':'terminal-completion-service.get-providers','as':'sug'},
            {'call':'terminal-process-manager.create-process','input':"= input",'as':'proc'},
            {'return':"= vars.proc.value"}])
SHOULD_PERSIST="((config['task-reconnection'] && input.reconnection_properties != null) || !input.is_feature_terminal) && vars.cfg.value.enable_persistent_sessions && !input.is_transient"
iface('terminal-process-manager','create-process','Attach to a persistent process (reconnect) or launch a new one; the process becomes Launching, then Running once start() succeeds.',
  [M(T_PM,'createProcess'),M(T_PM,'_launchLocalProcess')],request='TerminalShellLaunchConfig',response='TerminalInstanceInfo',
  behavior=[{'call':'terminal-instance-service.get-backend','input':{'remote_authority':None},'as':'backend'},
            {'call':'terminal-configuration-service.get-config','as':'cfg'},
            {'set':{'vars.pid':None,'vars.attached':False}},
            {'if':"input.attach_persistent_process != null",'then':[
               {'title':'Reconnect: attach to the persistent process','source':S(T_PM,350,363),
                'call':'local-terminal-backend.attach-to-process','input':{'id':"= input.attach_persistent_process.id",'pid':"= input.attach_persistent_process.pid",'find_revived_id':"= has(input.attach_persistent_process.find_revived_id) ? input.attach_persistent_process.find_revived_id : false"},'as':'att'},
               {'if':"vars.att.value.attached",'then':[{'set':{'vars.pid':"= vars.att.value.id",'vars.attached':True}}],
                'else':[{'title':'Attach failed: warn and create a new terminal','source':S(T_PM,361,362),'call':'terminal-log-service.warn','input':{'message':'Attach to process failed for terminal'}}]}]},
            {'if':"!vars.attached",'then':[
               {'call':'terminal-profile-resolver-service.resolve-shell-launch-config','input':{'executable':"= has(input.executable) ? input.executable : ''",'args':"= has(input.args) ? input.args : []"},'as':'slc'},
               {'call':'environment-variable-service.get-merged-collection','as':'env'},
               {'title':'shouldPersist = (task reconnection or not a feature terminal) && enablePersistentSessions && !isTransient','source':S(T_PM,565,566),
                'call':'local-terminal-backend.create-process','input':{'executable':"= vars.slc.value.executable",'cwd':"= has(input.cwd) ? input.cwd : 'file:///work/app'",'cols':80,'rows':30,
                   'should_persist':"= "+SHOULD_PERSIST,'type':"= has(input.task_key) && input.task_key != null ? 'Task' : ''"},'as':'created'},
               {'set':{'vars.pid':"= vars.created.value.id"}}]},
            {'title':'Process state Launching; start() the process','source':S(T_PM,386,443),
             'call':'local-pty.start','input':{'id':"= vars.pid"},'as':'started'},
            {'if':"has(vars.started.value.message)",'then':[{'title':'Launch error: the instance shows the error; the exit during launch marks KilledDuringLaunch','source':S(T_PM,444,447),
               'return':{'instance_id':0,'persistent_process_id':"= vars.pid",'location':'panel','shell':"= has(input.executable) ? input.executable : ''",'cwd':'file:///work/app','process_state':'killed-during-launch','should_persist':False,'hide_from_user':False,'launch_error':"= vars.started.value.message"}}]},
            {'return':{'instance_id':0,'persistent_process_id':"= vars.pid",'location':'panel','shell':"= has(input.executable) ? input.executable : ''",'cwd':"= has(input.cwd) ? input.cwd : 'file:///work/app'",
               'process_state':'running','should_persist':"= vars.attached || ("+SHOULD_PERSIST+")",'hide_from_user':"= input.hide_from_user",'launch_error':None}}])

# ---------------- interfaces: terminal service ----------------
iface('terminal-service','create-terminal','Create a terminal: default profile, cwd, location; background (hideFromUser) terminals are tracked separately; activates onTerminal:*.',
  [M(T_SVC,'createTerminal'),M(T_SVC,'_createTerminal')],request='TerminalShellLaunchConfig',response='TerminalInstanceInfo',
  errors=[{'code':'no-terminal-backend','status':0,'retryable':False}],
  behavior=[
    {'if':"!has(input.executable) || input.executable == ''",'then':[
       {'title':'No config: use the default profile','source':S(T_SVC,1000,1003),'call':'terminal-profile-service.get-default-profile','as':'prof'},
       {'set':{'vars.exe':"= vars.prof.value.path"}}],'else':[{'set':{'vars.exe':"= input.executable"}}]},
    {'set':{'vars.slc':"= merge(input, {'executable': vars.exe})"}},
    {'if':"input.hide_from_user",'then':[
       {'title':'Background terminal: created without a group and tracked as backgrounded','source':S(T_SVC,1074,1080),
        'call':'terminal-instance-service.create-instance','input':"= vars.slc",'as':'bg'},
       {'set':{'vars.bginfo':"= merge(vars.bg.value, {'instance_id': state.next_instance_id, 'location': 'panel'})"}},
       {'set':{'state.instances':"= merge(state.instances, {string(state.next_instance_id): vars.bginfo})",'state.backgrounded':"= state.backgrounded + [state.next_instance_id]",'state.next_instance_id':"= state.next_instance_id + 1"}},
       {'return':"= vars.bginfo"}]},
    {'call':'extension-service.activate-by-event','input':{'activation_event':'onTerminal:*','activation_kind':'normal'},'source':S(T_SVC,1084)},
    {'call':'terminal-instance-service.create-instance','input':"= vars.slc",'as':'inst'},
    {'set':{'vars.info':"= merge(vars.inst.value, {'instance_id': state.next_instance_id, 'location': has(input.location) ? input.location : 'panel'})"}},
    {'if':"vars.info.location == 'editor'",'then':[{'call':'terminal-editor-service.open-instance','input':{'instance_id':"= vars.info.instance_id"}}],
     'else':[{'call':'terminal-group-service.create-group','input':{'instance_id':"= vars.info.instance_id"}}]},
    {'set':{'state.instances':"= merge(state.instances, {string(state.next_instance_id): vars.info})",'state.active_instance':"= state.next_instance_id",'state.next_instance_id':"= state.next_instance_id + 1"}},
    {'title':'onDidChangeInstances triggers the debounced layout save once layout listeners are attached','source':S(T_SVC,557,565),
     'when':"state.layout_listeners_attached",'emit':'terminal-service.save-state','after_ms':"= config['terminal-save-state-debounce-ms']",'input':{'scheduled_at':"= now"}},
    {'return':"= vars.info"}])
iface('terminal-service','get-instances','The window\'s terminal instances (TerminalService.instances): grouped, editor and background ones.',[S(T_SVC,97,100)],
  response=obj({'instances':arr(ref:={'$ref':'TerminalInstanceInfo'}),'count':it()}),
  behavior=[{'return':{'instances':"= state.instances.map(k, state.instances[k])",'count':"= size(state.instances)"}}])
iface('terminal-service','save-state','Debounced: send the tab layout (persistent process ids) to the pty host unless shutting down or persistence is off.',[M(T_SVC,'_saveState')],
  request=obj({'scheduled_at':it()}),response=obj({'saved':bo()}),
  behavior=[{'if':"state.is_shutting_down",'then':[{'title':'Shutting down: do not overwrite the state to revive','source':S(T_SVC,726,728),'return':{'saved':False}}]},
            {'if':"!config['terminal-integrated-enable-persistent-sessions']",'then':[{'return':{'saved':False}}]},
            {'call':'local-terminal-backend.set-terminal-layout-info','input':{'tabs':"= state.instances.filter(k, !(state.instances[k].hide_from_user) && state.instances[k].persistent_process_id != null).map(k, [state.instances[k].persistent_process_id])",
               'background':"= state.backgrounded.filter(i, string(i) in state.instances && state.instances[string(i)].persistent_process_id != null).map(i, state.instances[string(i)].persistent_process_id)"}},
            {'return':{'saved':True}}])
iface('terminal-service','on-before-shutdown','onBeforeShutdown listener: persist terminal buffers for revive (2 s budget) and, when processes are not persisted, confirm closing per confirmOnExit; never vetoes on errors.',
  [M(T_SVC,'_onBeforeShutdownAsync'),M(T_SVC,'_shouldReviveProcesses'),S(T_SVC,227)],subscribe=['lifecycle-service.on-before-shutdown'],
  request=obj({'reason':st('reload',enum=['close','quit','reload','load'])},['reason']),response=obj({'veto':bo(),'revived':bo()}),
  behavior=[
    {'if':"size(state.instances) == 0",'then':[{'title':'No terminal instances: do not veto','source':S(T_SVC,631,634),'return':{'veto':False,'revived':False}}]},
    {'title':'TerminalNativeContribution delegate: nativeHostService.getWindowCount()','source':S(TE+'terminalNativeContribution.ts',31,33),'call':'native-host-main-service.get-window-count','input':{'window_id':"= self"},'as':'wc'},
    {'call':'terminal-configuration-service.get-config','as':'cfg'},
    {'set':{'vars.revive':"= vars.cfg.value.enable_persistent_sessions && ((vars.cfg.value.persistent_session_revive_process == 'onExit' && ((input.reason == 'close' && vars.wc.value.count == 1) || input.reason == 'load' || input.reason == 'quit')) || (vars.cfg.value.persistent_session_revive_process == 'onExitAndWindowClose' && input.reason != 'reload'))"}},
    {'if':"vars.revive",'then':[{'title':'Persist terminal buffer state, racing a 2000 ms timeout','source':S(T_SVC,641,650),
        'call':'local-terminal-backend.persist-terminal-state','timeout_ms':"= config['terminal-persist-state-timeout-ms']",'on_error':'continue','as':'persisted'}]},
    {'set':{'ctx.terminal_revive_on_shutdown':"= vars.revive"}},
    {'if':"!(vars.cfg.value.enable_persistent_sessions && input.reason == 'reload') && vars.cfg.value.confirm_on_exit == 'always'",'then':[
       {'title':'confirmOnExit: ask before closing terminals','source':M(T_SVC,'_onBeforeShutdownConfirmation'),
        'choice':'close_confirmation','default':'close','options':{'close':[{'set':{'state.is_shutting_down':True}},{'return':{'veto':False,'revived':"= vars.revive"}}],'cancel':[{'return':{'veto':True,'revived':"= vars.revive"}}]}}]},
    {'set':{'state.is_shutting_down':True}},
    {'return':{'veto':False,'revived':"= vars.revive"}}])
iface('terminal-service','on-will-shutdown','onWillShutdown: on reload with persistent sessions, detach persistent processes (they survive for reconnect); otherwise dispose them; clear the saved layout unless persisting or reviving.',
  [M(T_SVC,'_onWillShutdown'),S(T_SVC,228)],request=obj({'reason':st('reload',enum=['close','quit','reload','load'])},['reason']),response=obj({'detached':it(),'disposed':it()}),
  behavior=[
    {'call':'terminal-configuration-service.get-config','as':'cfg'},
    {'set':{'vars.persist':"= vars.cfg.value.enable_persistent_sessions && input.reason == 'reload'",'vars.detached':0,'vars.disposed':0}},
    {'foreach':"= state.instances",'as':'inst','index':'key','steps':[
       {'if':"vars.persist && vars.inst.should_persist",'then':[
          {'title':'detachProcessAndDispose: keep the pty alive for reconnect','source':S(T_SVC,710,712),'call':'local-pty.detach','input':{'id':"= vars.inst.persistent_process_id",'force_persist':False}},
          {'set':{'vars.detached':"= vars.detached + 1"}}],
        'else':[
          {'title':'dispose: shut the process down','source':S(T_SVC,713,714),'when':"vars.inst.persistent_process_id != null",'call':'local-pty.shutdown','input':{'id':"= vars.inst.persistent_process_id",'immediate':True}},
          {'set':{'vars.disposed':"= vars.disposed + 1"}}]}]},
    {'set':{'state.instances':{},'state.backgrounded':[]}},
    {'if':"!vars.persist && !(ctx.terminal_revive_on_shutdown == true)",'then':[
       {'title':'Clear terminal layout info when not persisting or reviving','source':S(T_SVC,717,720),'call':'local-terminal-backend.set-terminal-layout-info','input':{'tabs':[],'background':[],'clear':True}}]},
    {'return':{'detached':"= vars.detached",'disposed':"= vars.disposed"}}])
iface('terminal-service','initialize-primary-backend','Startup: get the local backend; with persistent sessions, reconnect to the pty host\'s layout (recreate orphaned terminals, revive background ones), then mark connected.',
  [M(T_SVC,'_initializePrimaryBackend'),M(T_SVC,'_reconnectToLocalTerminals'),M(T_SVC,'_recreateTerminalGroup')],
  request=obj({'startup_kind':st('reloaded-window',enum=['new-window','reloaded-window','reopened-window'])}),response=obj({'reconnected':it(),'connection_state':st()}),
  behavior=[
    {'call':'terminal-instance-service.get-backend','input':{'remote_authority':None},'as':'backend'},
    {'call':'terminal-configuration-service.get-config','as':'cfg'},
    {'set':{'state.connection_state':'connecting','vars.count':0}},
    {'if':"vars.cfg.value.enable_persistent_sessions",'then':[
       {'title':'Reconnect to local terminals','source':M(T_SVC,'_reconnectToLocalTerminals'),'call':'local-terminal-backend.get-terminal-layout-info','as':'layout'},
       {'if':"vars.layout.value.tabs != null",'then':[
          {'foreach':"= vars.layout.value.tabs",'as':'tab','steps':[
             {'foreach':"= vars.tab.terminals.filter(t, t.is_orphan)",'as':'term','steps':[
                {'if':"input.startup_kind != 'reloaded-window' && vars.term.type == 'Task'",'then':[{'title':'Task terminals are only recreated on reload','source':S(T_SVC,537,539),'continue':True}]},
                {'call':'terminal-service.create-terminal','input':{'attach_persistent_process':{'id':"= vars.term.id",'pid':"= vars.term.pid",'find_revived_id':"= vars.term.revived"}},'fill':True},
                {'set':{'vars.count':"= vars.count + 1"}}]}]}]},
       {'set':{'state.layout_listeners_attached':True}}]},
    {'set':{'state.connection_state':'connected','state.restored_group_count':"= vars.count"}},
    {'return':{'reconnected':"= vars.count",'connection_state':'connected'}}])

# group/editor/editing
iface('terminal-group-service','create-group','Create a terminal group (tab) holding the instance and make it active.',[M(TB+'terminalGroupService.ts','createGroup')],request=obj({'instance_id':it(1)}),response=obj({'group_index':it()}),
  behavior=[{'set':{'state.groups':"= state.groups + [[input.instance_id]]",'state.active_index':"= size(state.groups)"}},{'return':{'group_index':"= size(state.groups) - 1"}}])
iface('terminal-group-service','set-active-instance-by-index','Focus the terminal at a visible index (workbench.action.terminal.focusAtIndexN).',[M(TB+'terminalGroupService.ts','setActiveInstanceByIndex')],request=obj({'index':it(0)}),response=obj({'focused':bo()}),
  behavior=[{'if':"input.index >= size(state.groups)",'then':[{'return':{'focused':False}}]},{'set':{'state.active_index':"= input.index"}},{'return':{'focused':True}}])
iface('terminal-editor-service','open-instance','Open a terminal instance as an editor.',[M(TB+'terminalEditorService.ts','openEditor')],request=obj({'instance_id':it(1)}),response=ob(),
  behavior=[{'set':{'state.instances':"= state.instances + [input.instance_id]"}},{'call':'editor-service.open-editor','input':{'resource':"= 'vscode-terminal:/' + string(input.instance_id)"}}])
iface('terminal-editing-service','set-editable','Start or end inline rename of a terminal tab.',[M(TB+'terminalEditingService.ts','setEditable')],request=obj({'instance_id':it(1),'editing':bo(True)}),response=ob(),
  behavior=[{'if':"input.editing",'then':[{'set':{'state.editable':"= merge(state.editable, {string(input.instance_id): true})",'state.editing_terminal':"= input.instance_id"}}],
             'else':[{'set':{'state.editable':"= omit(state.editable, string(input.instance_id))",'state.editing_terminal':None}}]}])
iface('terminal-editing-service','get-editable-data','Whether a terminal is being renamed.',[M(TB+'terminalEditingService.ts','getEditableData')],request=obj({'instance_id':it(1)}),response=obj({'editable':bo()}),
  behavior=[{'return':{'editable':"= string(input.instance_id) in state.editable"}}])

# per-instance contribution services (getters read when an instance attaches contributions)
iface('terminal-link-provider-service','get-link-providers','Registered external link providers.',[S(TCO+'links/browser/terminalLinkProviderService.ts',15)],response=obj({'count':it()}),behavior=[{'return':{'count':"= size(state.link_providers)"}}])
iface('terminal-link-provider-service','register-link-provider','Register an extension link provider (called by MainThreadTerminalService).',[M(TCO+'links/browser/terminalLinkProviderService.ts','registerLinkProvider')],request=obj({'provider_id':st('vscode.git')}),response=ob(),
  behavior=[{'set':{'state.link_providers':"= state.link_providers + [input.provider_id]"}}])
iface('terminal-quick-fix-service','get-providers','Registered quick fix providers.',[S(TCO+'quickFix/browser/terminalQuickFixService.ts',20)],response=obj({'count':it()}),behavior=[{'return':{'count':"= size(state.providers)"}}])
iface('terminal-quick-fix-service','on-quick-fixes-extension-point','Handler of the terminalQuickFixes extension point: records contributed command selectors.',[S(TCO+'quickFix/browser/terminalQuickFixService.ts',94),S(TCO+'quickFix/browser/terminalQuickFixService.ts',34,41)],
  request=obj({'selectors':arr(st('git-push'),default=[])}),response=ob(),behavior=[{'set':{'state.extension_quick_fixes':"= input.selectors"}}])
iface('terminal-completion-service','get-providers','Registered terminal completion providers.',[S(TCO+'suggest/browser/terminalCompletionService.ts',89,91)],response=obj({'count':it()}),behavior=[{'return':{'count':"= size(state.providers)"}}])
iface('terminal-contribution-service','on-terminal-extension-point','Handler of the "terminal" extension point: collects contributed profiles.',[S(TC+'terminalExtensionPoints.ts',16),S(TC+'terminalExtensionPoints.ts',45,52)],
  request=obj({'profiles':arr(default=[])}),response=ob(),behavior=[{'set':{'state.terminal_profiles':"= input.profiles"}}])
iface('agent-host-terminal-service','create-terminal-for-entry','Create a terminal for an agent host entry (agents area): a TerminalService terminal tagged with the connection.',[M(TB+'agentHostTerminalService.ts','createTerminalForEntry')],
  request=obj({'address':st('local'),'cwd':st('file:///work/app')}),response='TerminalInstanceInfo',
  behavior=[{'if':"!(input.address in state.entries)",'then':[{'title':'Unknown agent host entry: no terminal','source':M(TB+'agentHostTerminalService.ts','createTerminalForEntry'),'return':{'instance_id':0,'persistent_process_id':None,'location':'panel','shell':'','cwd':'','process_state':'uninitialized','should_persist':False,'hide_from_user':False,'launch_error':'unknown agent host entry'}}]},
            {'call':'terminal-service.create-terminal','input':{'cwd':"= input.cwd",'is_feature_terminal':True},'fill':True,'as':'t'},{'return':"= vars.t.value"}])
iface('agent-host-terminal-service','register-entry','Register an agent host connection entry.',[M(TB+'agentHostTerminalService.ts','registerEntry')],request=obj({'address':st('local')}),response=ob(),
  behavior=[{'set':{'state.entries':"= merge(state.entries, {input.address: true})"}}])
iface('terminal-chat-session-resolver','resolve','Resolve the chat session for a terminal chat widget (chat area answers).',[M(TCO+'chat/browser/terminalChatSessionResolver.ts','resolve')],
  request=obj({'shell_type':st('bash')}),response=obj({'resolved':bo()}),
  behavior=[{'title':'Delegates to the chat session services (chat area); modeled as resolved','source':M(TCO+'chat/browser/terminalChatSessionResolver.ts','resolve'),'return':{'resolved':True}}])

# ---------------- local backend / local pty ----------------
iface('local-terminal-backend','connect-to-direct-proxy','Request a direct message-port connection to the pty host; this launches the pty host through the main process if needed.',[M(T_LB,'_connectToDirectProxy')],response=ob(),
  behavior=[{'if':"state.direct_proxy",'then':[{'return':{}}]},
            {'call':'pty-host-service.ensure-pty-host','as':'host'},
            {'set':{'state.direct_proxy':True}}])
iface('local-terminal-backend','create-process','Create a pty on the pty host and wrap it in a LocalPty.',[M(T_LB,'createProcess')],
  request=obj({'executable':st('/bin/bash'),'cwd':st('file:///work/app'),'cols':it(80),'rows':it(30),'should_persist':bo(True),'type':st(default='')}),response=obj({'id':it()}),
  behavior=[{'call':'local-terminal-backend.connect-to-direct-proxy'},
            {'call':'pty-service.create-process','input':{'executable':"= input.executable",'cwd':"= input.cwd",'cols':"= input.cols",'rows':"= input.rows",'should_persist':"= input.should_persist",'workspace_id':'w1-app','attach':False,'is_reviving':False,'type':"= input.type"},'as':'c'},
            {'set':{'state.ptys':"= merge(state.ptys, {string(vars.c.value.id): {'should_persist': input.should_persist}})"}},
            {'return':{'id':"= vars.c.value.id"}}])
iface('local-terminal-backend','attach-to-process','Attach to an existing persistent pty (reconnect); failures are logged and return nothing.',[M(T_LB,'attachToProcess'),M(T_LB,'attachToRevivedProcess')],
  request=obj({'id':it(1),'pid':it(4242),'find_revived_id':bo(False)}),response=obj({'attached':bo(),'id':it()}),
  behavior=[{'call':'local-terminal-backend.connect-to-direct-proxy'},
            {'set':{'vars.id':"= input.id"}},
            {'if':"input.find_revived_id",'then':[{'call':'pty-service.get-revived-pty-new-id','input':{'workspace_id':'w1-app','id':"= input.id"},'as':'rev'},
                {'when':"vars.rev.value.new_id != null",'set':{'vars.id':"= vars.rev.value.new_id"}}]},
            {'call':'pty-service.attach-to-process','input':{'id':"= vars.id",'pid':"= input.find_revived_id ? 0 : input.pid"},'as':'att','on_error':'continue'},
            {'if':"!vars.att.ok",'then':[{'title':"Couldn't attach to process: warn and return undefined",'source':S(T_LB,231,233),'return':{'attached':False,'id':"= vars.id"}}]},
            {'set':{'state.ptys':"= merge(state.ptys, {string(vars.id): {'should_persist': true}})"}},
            {'return':{'attached':True,'id':"= vars.id"}}])
iface('local-terminal-backend','set-terminal-layout-info','Send the layout to the pty host and keep a copy in workspace storage for revive after exit.',[M(T_LB,'setTerminalLayoutInfo')],
  request=obj({'tabs':arr(arr(it())),'background':arr(it()),'clear':bo(False)}),response=ob(),
  behavior=[{'call':'pty-service.set-terminal-layout-info','input':{'workspace_id':'w1-app','tabs':"= input.tabs",'background':"= input.background"}},
            {'call':'local-terminal-backend.workspace-storage-store','input':{'key':'terminal.integrated.layoutInfo','value':{'workspace_id':'w1-app','tabs':"= input.tabs",'background':"= input.background"}}}])
iface('local-terminal-backend','persist-terminal-state','Serialize the buffers of this window\'s ptys on the pty host and store them in workspace storage (bufferState) for revive.',[M(T_LB,'persistTerminalState')],response=ob(),
  behavior=[{'call':'pty-service.serialize-terminal-state','input':{'ids':"= state.ptys.map(k, int(k))"},'as':'ser'},
            {'call':'local-terminal-backend.workspace-storage-store','input':{'key':'terminal.integrated.bufferState','value':"= vars.ser.value"}}])
iface('local-terminal-backend','get-terminal-layout-info','Revive processes from stored buffer state if present (then restore the stored layout on the pty host), then ask the pty host for the layout.',[M(T_LB,'getTerminalLayoutInfo')],
  response=obj({'tabs':{'type':['array','null']},'background':{'type':['array','null']}}),
  behavior=[{'call':'local-terminal-backend.workspace-storage-get','input':{'key':'terminal.integrated.bufferState'},'as':'buf'},
            {'if':"vars.buf.value != null && size(vars.buf.value.state) > 0",'then':[
               {'title':'Revive processes from the serialized buffers','source':S(T_LB,334,357),'call':'pty-service.revive-terminal-processes','input':{'workspace_id':'w1-app','state':"= vars.buf.value.state"}},
               {'call':'local-terminal-backend.workspace-storage-remove','input':{'key':'terminal.integrated.bufferState'}},
               {'call':'local-terminal-backend.workspace-storage-get','input':{'key':'terminal.integrated.layoutInfo'},'as':'lay'},
               {'if':"vars.lay.value != null",'then':[
                  {'title':'Send the stored layout back to the pty host (it was not persisted on exit)','source':S(T_LB,358,366),'call':'pty-service.set-terminal-layout-info','input':{'workspace_id':'w1-app','tabs':"= vars.lay.value.tabs",'background':"= vars.lay.value.background"}},
                  {'call':'local-terminal-backend.workspace-storage-remove','input':{'key':'terminal.integrated.layoutInfo'}}]}]},
            {'call':'pty-service.get-terminal-layout-info','input':{'workspace_id':'w1-app'},'as':'layout'},
            {'return':"= vars.layout.value"}])
for nm,op,sm in [('workspace-storage-store','put','Store a terminal key in workspace storage (IStorageService, StorageScope.WORKSPACE).'),
                 ('workspace-storage-get','get','Read a terminal key from workspace storage.'),('workspace-storage-remove','delete','Remove a terminal key from workspace storage.')]:
    store={'table':'workspace_storage','op':op,'key':"= input.key"}
    if op=='put': store['value']="= input.value"
    if op=='get': store['default']='= null'
    iface('local-terminal-backend',nm,sm,[S(T_LB,187) if op=='put' else (S(T_LB,335) if op=='get' else S(T_LB,357))],
      request=obj({'key':st('terminal.integrated.bufferState'),'value':{}},['key']),response={},store=store,kind='io')
iface('local-pty','start','Start the pty on the pty host.',[M(TE+'localPty.ts','start')],request=obj({'id':it(1)}),response=obj({'message':st()}),
  behavior=[{'call':'pty-service.start','input':{'id':"= input.id"},'as':'r'},{'return':"= vars.r.value"}])
iface('local-pty','input','Send input to the pty.',[M(TE+'localPty.ts','input')],request=obj({'id':it(1),'data':st('ls\r')}),response=ob(),
  behavior=[{'call':'pty-service.input','input':{'id':"= input.id",'data':"= input.data"}}])
iface('local-pty','shutdown','Shut down the pty.',[M(TE+'localPty.ts','shutdown')],request=obj({'id':it(1),'immediate':bo(True)}),response=ob(),
  behavior=[{'call':'pty-service.shutdown','input':{'id':"= input.id",'immediate':"= input.immediate"}}])
iface('local-pty','detach','Detach from the pty, keeping it alive when it should persist.',[M(TE+'localPty.ts','detach')],request=obj({'id':it(1),'force_persist':bo(False)}),response=ob(),
  behavior=[{'call':'pty-service.detach-from-process','input':{'id':"= input.id",'force_persist':"= input.force_persist"}}])

# ---------------- pty host service (main process) ----------------
iface('pty-host-service','ensure-pty-host','_ensurePtyHost: start the pty host process if there is no connection yet.',[M(P_PHS,'_ensurePtyHost'),S(P_PHS,113,115)],response=obj({'started_now':bo()}),
  behavior=[{'if':"state.started",'then':[{'return':{'started_now':False}}]},{'call':'pty-host-service.start-pty-host'},{'return':{'started_now':True}}])
iface('pty-host-service','start-pty-host','Launch the pty host through the starter, connect the heartbeat (first wait is the connecting interval), forward events.',[M(P_PHS,'_startPtyHost')],response=ob(),
  behavior=[{'call':'pty-host-main.start-pty-host','as':'host'},
            {'set':{'state.started':True,'state.start_count':"= state.start_count + 1"}},
            {'title':'Trigger a heartbeat immediately to reset the timeouts (connecting interval)','source':S(P_PHS,156,159),'call':'pty-host-service.handle-heartbeat','input':{'is_connecting':True}}])
iface('pty-host-service','handle-heartbeat','A heartbeat arrived: reset the first wait timer and recover responsiveness.',[M(P_PHS,'_handleHeartbeat')],request=obj({'is_connecting':bo(False)}),response=ob(),
  behavior=[{'set':{'state.last_beat_at':"= now"}},
            {'emit':'pty-host-service.heartbeat-first-timeout','after_ms':"= input.is_connecting ? config['pty-host-heartbeat-connecting-interval-ms'] : config['pty-host-heartbeat-first-wait-ms']",'input':{'scheduled_at':"= now"}},
            {'if':"!state.responsive",'then':[{'set':{'state.responsive':True}},{'title':'onPtyHostResponsive','source':S(P_PHS,389,392),'publish':'pty-host-service.on-pty-host-responsive','delivery':'sync','input':{'responsive':True}}]}])
iface('pty-host-service','heartbeat-first-timeout','No heartbeat for the first wait: warn and arm the second timer (cleared if a newer beat arrived).',[M(P_PHS,'_handleHeartbeatFirstTimeout')],request=obj({'scheduled_at':it()}),response=obj({'superseded':bo()}),
  behavior=[{'if':"state.last_beat_at > input.scheduled_at || !state.started",'then':[{'title':'A newer heartbeat cleared this timer','source':M(P_PHS,'_clearHeartbeatTimeouts'),'return':{'superseded':True}}]},
            {'set':{'ctx.pty_host_heartbeat_warning':True}},
            {'emit':'pty-host-service.heartbeat-second-timeout','after_ms':"= config['pty-host-heartbeat-second-wait-ms']",'input':{'scheduled_at':"= input.scheduled_at"}},
            {'return':{'superseded':False}}])
iface('pty-host-service','heartbeat-second-timeout','Still no heartbeat: declare the pty host unresponsive (fires onPtyHostUnresponsive once).',[M(P_PHS,'_handleHeartbeatSecondTimeout')],request=obj({'scheduled_at':it()}),response=obj({'superseded':bo()}),
  behavior=[{'if':"state.last_beat_at > input.scheduled_at || !state.started",'then':[{'return':{'superseded':True}}]},
            {'if':"state.responsive",'then':[{'set':{'state.responsive':False}},{'publish':'pty-host-service.on-pty-host-unresponsive','delivery':'sync','input':{'responsive':False}}]},
            {'return':{'superseded':False}}])
iface('pty-host-service','on-pty-host-unresponsive','onPtyHostUnresponsive event.',[S(P_PHS,70,71)],kind='event',request=obj({'responsive':bo()}),response=ob())
iface('pty-host-service','on-pty-host-responsive','onPtyHostResponsive event.',[S(P_PHS,72,73)],kind='event',request=obj({'responsive':bo()}),response=ob())
iface('pty-host-service','on-pty-host-exit','The pty host process exited: restart it unless quit was requested, giving up after MaxRestarts.',[S(P_PHS,161,173),M(P_PHS,'restartPtyHost'),M(P_PHS,'_disposePtyHost')],
  request=obj({'code':it(1)}),response=obj({'restarted':bo()}),
  behavior=[{'set':{'state.started':False}},
            {'if':"state.quit_requested",'then':[{'return':{'restarted':False}}]},
            {'if':"state.restart_count <= config['pty-host-max-restarts']",'then':[
               {'title':'ptyHost terminated unexpectedly: restart','source':S(P_PHS,165,168),'set':{'state.restart_count':"= state.restart_count + 1",'state.responsive':True}},
               {'call':'pty-host-service.start-pty-host'},{'return':{'restarted':True}}]},
            {'title':'ptyHost terminated unexpectedly, giving up','source':S(P_PHS,169,171),'set':{'ctx.pty_host_gave_up':True}},
            {'return':{'restarted':False}}])
iface('local-terminal-backend','on-pty-host-unresponsive','BaseTerminalBackend adds the "Pty Host" warning status bar entry and re-fires onPtyHostUnresponsive.',[S(TB+'baseTerminalBackend.ts',61,76)],
  subscribe=['pty-host-service.on-pty-host-unresponsive'],request=obj({'responsive':bo()}),response=ob(),behavior=[{'set':{'ctx.pty_host_status':'unresponsive'}}])
iface('local-terminal-backend','on-pty-host-responsive','The pty host is responsive again: the status entry is removed.',[S(TB+'baseTerminalBackend.ts',77,85)],
  subscribe=['pty-host-service.on-pty-host-responsive'],request=obj({'responsive':bo()}),response=ob(),behavior=[{'set':{'ctx.pty_host_status':'responsive'}}])

# ---------------- pty host process ----------------
iface('pty-host-main','start-pty-host','startPtyHost(): IPC server, logger channel, heartbeat channel, PtyService channel and (utility process) the window channel.',[S(P_MAIN,29,104)],response=obj({'channels':arr(st())}),
  behavior=[{'title':"registerChannel('logger')",'source':S(P_MAIN,67)},
            {'title':"registerChannel('heartbeat') with a new HeartbeatService",'source':S(P_MAIN,83,84),'call':'heartbeat-service.start'},
            {'title':"registerChannel('ptyHost', PtyService)",'source':S(P_MAIN,87,89)},
            {'title':"registerChannel('ptyHostWindow') for the direct message-port connection",'source':S(P_MAIN,92,94)},
            {'return':{'channels':['logger','heartbeat','ptyHost','ptyHostWindow']}}])
iface('heartbeat-service','start','Start firing onBeat every BeatInterval; PtyHostService handles each beat.',[CL(P_HB,'HeartbeatService',True)],response=ob(),
  behavior=[{'emit':'pty-host-service.handle-heartbeat','every_ms':"= config['pty-host-heartbeat-beat-interval-ms']",'count':4,'input':{'is_connecting':False}}])
ERRNOPTY={'code':'could-not-find-pty-on-pty-host','status':0,'retryable':False}
NOPTY=lambda: {'if':"!(string(input.id) in state.ptys)",'then':[{'title':'_throwIfNoPty','source':M(P_PS,'_throwIfNoPty'),'fail':{'code':'could-not-find-pty-on-pty-host','message':"= 'Could not find pty ' + string(input.id) + ' on pty host'"}}]}
iface('pty-service','create-process','Create a TerminalProcess wrapped in a PersistentTerminalProcess under a new id (not started yet).',[M(P_PS,'createProcess')],
  request=obj({'executable':st('/bin/bash'),'cwd':st('file:///work/app'),'cols':it(80),'rows':it(30),'should_persist':bo(True),'workspace_id':st('w1-app'),'attach':bo(False),'is_reviving':bo(False),'type':st(default='')}),response=obj({'id':it()}),
  errors=[{'code':'attempt-to-create-a-process-when-attach-object-was-provided','status':0,'retryable':False}],
  behavior=[{'if':"input.attach",'then':[{'fail':{'code':'attempt-to-create-a-process-when-attach-object-was-provided','message':'Attempt to create a process when attach object was provided'}}]},
            {'set':{'vars.id':"= state.last_pty_id + 1"}},
            {'set':{'state.last_pty_id':"= vars.id",'state.ptys':"= merge(state.ptys, {string(vars.id): {'id': vars.id, 'executable': input.executable, 'cwd': input.cwd, 'workspace_id': input.workspace_id, 'should_persist': input.should_persist, 'started': false, 'interaction': 'None', 'was_revived': input.is_reviving, 'pid': 0, 'grace_scheduled_at': null, 'type': input.type}})"}},
            {'return':{'id':"= vars.id"}}])
iface('pty-service','start','Start the persistent process: the first start spawns it (or returns the launch error); a later start replays the buffer.',[M(P_PS,'start'),M(P_PS,'start',868)],
  request=obj({'id':it(1)}),response=obj({'message':st(),'pid':it()}),
  behavior=[{'if':"!(string(input.id) in state.ptys)",'then':[{'return':{'message':"= 'Could not find pty with id \"' + string(input.id) + '\"'"}}]},
            {'set':{'vars.p':"= state.ptys[string(input.id)]"}},
            {'if':"vars.p.started",'then':[{'title':'Already started: fire ready and replay the buffer','source':S(P_PS,889,893),'return':{'pid':"= vars.p.pid"}}]},
            {'call':'terminal-process.start','input':{'executable':"= vars.p.executable",'cwd':"= vars.p.cwd"},'as':'spawn'},
            {'if':"has(vars.spawn.value.message)",'then':[{'return':{'message':"= vars.spawn.value.message"}}]},
            {'set':{'state.ptys':"= merge(state.ptys, {string(input.id): {'started': true, 'pid': vars.spawn.value.pid, 'interaction': vars.p.was_revived ? 'ReplayOnly' : vars.p.interaction}})"}},
            {'return':{'pid':"= vars.spawn.value.pid"}}])
iface('pty-service','input','Write input to the process; marks the process as interacted with this session.',[M(P_PS,'input'),M(P_PS,'input',897)],request=obj({'id':it(1),'data':st('ls\r')}),response=ob(),errors=[ERRNOPTY],
  behavior=[NOPTY(),{'set':{'state.ptys':"= merge(state.ptys, {string(input.id): {'interaction': 'Session'}})"}},{'call':'terminal-process.input','input':{'data':"= input.data"}}])
iface('pty-service','shutdown','Shut a process down; a missing pty is ignored. The exit removes it from the pty map.',[M(P_PS,'shutdown'),S(P_PS,343,351)],request=obj({'id':it(1),'immediate':bo(True)}),response=ob(),
  behavior=[{'if':"!(string(input.id) in state.ptys)",'then':[{'title':"Don't throw if the pty is already shut down",'source':S(P_PS,447,449),'return':{}}]},
            {'call':'terminal-process.shutdown','input':{'immediate':"= input.immediate"}},
            {'title':'onProcessExit: dispose the persistent process and delete it','source':S(P_PS,343,351),'set':{'state.ptys':"= omit(state.ptys, string(input.id))"}}])
iface('pty-service','attach-to-process','Reconnect a window to a persistent process: checks pid, cancels the disconnect (grace time) runners.',[M(P_PS,'attachToProcess'),S(P_PS,836,842)],
  request=obj({'id':it(1),'pid':it(0)}),response=ob(),errors=[ERRNOPTY,{'code':'pty-has-unexpected-pid','status':0,'retryable':False}],
  behavior=[NOPTY(),
            {'if':"input.pid != 0 && state.ptys[string(input.id)].pid != input.pid",'then':[{'fail':{'code':'pty-has-unexpected-pid','message':"= 'Pty ' + string(input.id) + ' has pid ' + string(state.ptys[string(input.id)].pid) + ', expected ' + string(input.pid)"}}]},
            {'title':'Cancel both disconnect runners','source':S(P_PS,840,841),'set':{'state.ptys':"= merge(state.ptys, {string(input.id): {'grace_scheduled_at': null}})"}}])
iface('pty-service','detach-from-process','Window detached: keep a persistent, interacted-with process alive for the grace time, else shut it down.',[M(P_PS,'detachFromProcess'),S(P_PS,844,852)],
  request=obj({'id':it(1),'force_persist':bo(False)}),response=obj({'kept':bo()}),errors=[ERRNOPTY],
  behavior=[NOPTY(),{'set':{'vars.p':"= state.ptys[string(input.id)]"}},
            {'if':"vars.p.should_persist && (vars.p.interaction != 'None' || input.force_persist)",'then':[
               {'title':'Schedule the disconnect runner (reconnection grace time)','source':S(P_PS,812,814),'set':{'state.ptys':"= merge(state.ptys, {string(input.id): {'grace_scheduled_at': now}})"}},
               {'emit':'pty-service.disconnect-runner-expired','after_ms':"= config['pty-reconnect-grace-time-ms']",'input':{'id':"= input.id",'scheduled_at':"= now"}},
               {'return':{'kept':True}}]},
            {'call':'pty-service.shutdown','input':{'id':"= input.id",'immediate':True}},{'return':{'kept':False}}])
iface('pty-service','disconnect-runner-expired','The reconnection grace time expired without a reconnect: shut the process down.',[S(P_PS,812,814)],
  request=obj({'id':it(1),'scheduled_at':it()}),response=obj({'shutdown':bo()}),
  behavior=[{'if':"!(string(input.id) in state.ptys) || state.ptys[string(input.id)].grace_scheduled_at != input.scheduled_at",'then':[{'title':'Runner was cancelled by a reconnect','source':S(P_PS,840,841),'return':{'shutdown':False}}]},
            {'call':'pty-service.shutdown','input':{'id':"= input.id",'immediate':True}},{'return':{'shutdown':True}}])
iface('pty-service','reduce-connection-grace-time','After a reconnect, switch running disconnect runners to the short grace time.',[M(P_PS,'reduceConnectionGraceTime'),M(P_PS,'reduceGraceTime')],response=ob(),
  behavior=[{'foreach':"= state.ptys",'as':'p','index':'k','steps':[{'when':"vars.p.grace_scheduled_at != null",'emit':'pty-service.disconnect-runner-expired','after_ms':"= config['pty-reconnect-short-grace-time-ms']",'input':{'id':"= vars.p.id",'scheduled_at':"= vars.p.grace_scheduled_at"}}]}])
iface('pty-service','set-terminal-layout-info','Remember a workspace\'s tab layout (in memory on the pty host).',[M(P_PS,'setTerminalLayoutInfo')],
  request=obj({'workspace_id':st('w1-app'),'tabs':arr(arr(it())),'background':arr(it())}),response=ob(),
  behavior=[{'set':{'state.layouts':"= merge(state.layouts, {input.workspace_id: {'tabs': input.tabs, 'background': input.background}})"}}])
iface('pty-service','get-terminal-layout-info','Expand the stored layout to process details, dropping terminals whose pty is gone; non-revived processes go through the orphan question (up to 4 s).',
  [M(P_PS,'getTerminalLayoutInfo'),M(P_PS,'_expandTerminalInstance'),M(P_PS,'_buildProcessDetails')],request=obj({'workspace_id':st('w1-app')}),
  response=obj({'tabs':{'type':['array','null']},'background':{'type':['array','null']}}),
  behavior=[{'if':"!(input.workspace_id in state.layouts)",'then':[{'return':{'tabs':None,'background':None}}]},
            {'set':{'vars.layout':"= state.layouts[input.workspace_id]"}},
            {'set':{'vars.ids':"= vars.layout.tabs.map(t, t.map(i, (input.workspace_id + '-' + string(i)) in state.revived ? state.revived[input.workspace_id + '-' + string(i)].new_id : i))"}},
            {'if':"vars.ids.exists(t, t.exists(i, string(i) in state.ptys && !state.ptys[string(i)].was_revived))",'then':[
               {'title':'Orphan question: wait for a window to claim the process (AutoOpenBarrier)','source':S(P_PS,1011,1019),'wait':"= config['pty-orphan-question-timeout-ms']"}]},
            {'set':{'state.revived':{}}},
            {'return':{'tabs':"= vars.ids.map(t, {'terminals': t.filter(i, string(i) in state.ptys).map(i, {'id': i, 'pid': state.ptys[string(i)].pid, 'is_orphan': true, 'revived': state.ptys[string(i)].was_revived, 'cwd': state.ptys[string(i)].cwd, 'type': state.ptys[string(i)].type})}).filter(t, size(t.terminals) > 0)",
                       'background':"= vars.layout.background.filter(i, string(i) in state.ptys)"}}])
iface('pty-service','serialize-terminal-state','Serialize the replay buffers of the requested persistent processes that have written data.',[M(P_PS,'serializeTerminalState')],
  request=obj({'ids':arr(it())}),response=obj({'version':it(),'state':arr()}),
  behavior=[{'return':{'version':1,'state':"= input.ids.filter(i, string(i) in state.ptys && state.ptys[string(i)].started).map(i, {'id': i, 'executable': state.ptys[string(i)].executable, 'cwd': state.ptys[string(i)].cwd, 'workspace_id': state.ptys[string(i)].workspace_id})"}}])
iface('pty-service','revive-terminal-processes','Recreate processes from serialized state (not started until a window attaches) and map old ids to new ones.',[M(P_PS,'reviveTerminalProcesses'),M(P_PS,'_reviveTerminalProcess')],
  request=obj({'workspace_id':st('w1-app'),'state':arr()}),response=ob(),
  behavior=[{'parallel':"= input.state",'as':'t','join':{'need':'all'},'steps':[
               {'call':'pty-service.create-process','input':{'executable':"= vars.t.executable",'cwd':"= vars.t.cwd",'cols':80,'rows':30,'should_persist':True,'workspace_id':"= vars.t.workspace_id",'attach':False,'is_reviving':True,'type':''},'as':'n'},
               {'set':{'state.revived':"= merge(state.revived, {input.workspace_id + '-' + string(vars.t.id): {'new_id': vars.n.value.id}})"}}]}])
iface('pty-service','get-revived-pty-new-id','Look up the new id of a revived process.',[M(P_PS,'getRevivedPtyNewId')],request=obj({'workspace_id':st('w1-app'),'id':it(1)}),response=obj({'new_id':{'type':['integer','null']}}),
  behavior=[{'set':{'vars.k':"= input.workspace_id + '-' + string(input.id)"}},{'return':{'new_id':"= vars.k in state.revived ? state.revived[vars.k].new_id : null"}}])
iface('pty-service','list-processes','Persistent processes that are orphans (no window claims them).',[M(P_PS,'listProcesses')],response=obj({'processes':arr()}),
  behavior=[{'return':{'processes':"= state.ptys.filter(k, state.ptys[k].should_persist).map(k, {'id': state.ptys[k].id, 'cwd': state.ptys[k].cwd})"}}])
iface('terminal-process','start','Validate cwd and executable, then spawn the shell with node-pty.',[M(P_TP,'start'),M(P_TP,'_validateCwd'),M(P_TP,'_validateExecutable')],
  request=obj({'executable':st('/bin/bash'),'cwd':st('file:///work/app')}),response=obj({'pid':it(4242),'message':st()}),
  behavior=[{'choice':'launch','default':'spawned','options':{
     'spawned':[{'return':{'pid':4242}}],
     'cwd_missing':[{'title':'launchFail.cwdDoesNotExist','source':S(P_TP,270,272),'return':{'message':"= 'Starting directory (cwd) \"' + input.cwd + '\" does not exist'"}}],
     'executable_missing':[{'title':'launchFail.executableDoesNotExist','source':S(P_TP,287,289),'return':{'message':"= 'Path to shell executable \"' + input.executable + '\" does not exist'"}}],
     'spawn_failed':[{'title':'node-pty spawn threw','source':S(P_TP,253,260),'return':{'message':'A native exception occurred during launch (spawn failed)'}}]}}])
iface('terminal-process','input','Write data to the pty.',[M(P_TP,'input')],request=obj({'data':st()}),response=ob(),behavior=[{'set':{'ctx.pty_last_input':"= input.data"}}])
iface('terminal-process','shutdown','Kill the pty (immediately or after flushing).',[M(P_TP,'shutdown')],request=obj({'immediate':bo(True)}),response=ob(),behavior=[{'set':{'ctx.pty_killed':True}}])
config('task-reconnection','task.reconnection','boolean',True,True,'On window reload, reconnect to tasks that have problem matchers (also read by TerminalProcessManager for shouldPersist). No product.json override.',
  [S('src/vs/workbench/contrib/tasks/browser/task.contribution.ts',549,553),'product.json'])

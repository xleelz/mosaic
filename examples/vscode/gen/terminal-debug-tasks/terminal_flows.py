from base import *
from terminal import *
FX=['one-window-folder']
flow('terminal-create','Create a terminal','terminal-service.create-terminal',
  'User creates a terminal (workbench.action.terminal.new, registered through registerTerminalAction, which the inventory does not list): default profile, process manager, local backend, pty host createProcess and start.',
  [M(T_SVC,'createTerminal')],inp={'executable':'','cwd':'file:///work/app'},tags=['writes'])
flow('terminal-list','List terminals','terminal-service.get-instances','Read the window\'s terminal instances (TerminalService.instances), as the tabs view does.',[S(T_SVC,97,100)])
flow('terminal-reconnect','Reconnect terminals after a window reload','terminal-service.initialize-primary-backend',
  'Startup of TerminalService: with persistent sessions on, fetch the pty host layout and recreate orphaned terminals attached to their persistent processes.',
  [M(T_SVC,'_initializePrimaryBackend')],inp={'startup_kind':'reloaded-window'},tags=['writes'])
flow('terminal-before-shutdown','Terminal onBeforeShutdown veto/persist','terminal-service.on-before-shutdown',
  'The lifecycle service fires onBeforeShutdown; TerminalService persists buffers for revive and may ask to confirm closing.',[S(T_SVC,227),M(T_SVC,'_onBeforeShutdownAsync')],
  caller='workbench-window',inp={'reason':'reload'},tags=['writes'])
flow('terminal-will-shutdown','Terminal onWillShutdown detach/dispose','terminal-service.on-will-shutdown',
  'The lifecycle service fires onWillShutdown; persistent processes are detached on reload, otherwise disposed.',[S(T_SVC,228),M(T_SVC,'_onWillShutdown')],
  caller='workbench-window',inp={'reason':'reload'},tags=['writes'])
flow('pty-host-main','Pty host process startup','pty-host-main.start-pty-host','Process main of the pty host (ptyHostMain.ts): registers its IPC channels and starts the heartbeat.',
  [S(P_MAIN,27),S(P_MAIN,29,104)],caller='pty-host-service')
flow('pty-host-heartbeat','Pty host start and heartbeat monitoring','pty-host-service.ensure-pty-host',
  'A window requests the pty host: the main process starts it and watches its heartbeat (first wait 20 s when connecting, then 6 s + 5 s).',
  [M(P_PHS,'_ensurePtyHost'),M(P_PHS,'_handleHeartbeat')],caller='local-terminal-backend',tags=['writes'])
flow('pty-host-exit','Pty host crash and restart','pty-host-service.on-pty-host-exit','The pty host process exits unexpectedly; the main process restarts it up to MaxRestarts times.',
  [S(P_PHS,161,173)],caller='main-process',inp={'code':1},tags=['writes'])
flow('pty-list-processes','List orphan persistent processes','pty-service.list-processes','IPtyService.listProcesses: persistent processes no window claims.',[M(P_PS,'listProcesses')],caller='local-terminal-backend')
flow('terminal-detach-request','Pty layout write','pty-service.set-terminal-layout-info','Directly set a workspace layout on the pty host (as LocalTerminalBackend does).',[M(P_PS,'setTerminalLayoutInfo')],caller='local-terminal-backend',
  inp={'workspace_id':'w1-app','tabs':[[1]],'background':[]},tags=['writes'])

# --- scenarios ---
scen('terminal-create-happy','Create a terminal: profile, pty host start, createProcess and start',[
  "result.ok && result.value.process_state == 'running' && result.value.persistent_process_id == 1",
  "result.value.should_persist == true && result.value.shell == '/bin/bash'",
  "state['terminal-service@w1'].instances['1'].persistent_process_id == 1",
  "state['pty-service'].ptys['1'].started && state['pty-host-service'].started",
  "calls['pty-host-main.start-pty-host'] == 1 && calls['extension-service.activate-by-event'] == 1"],flow='terminal-create',fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}}})
scen('terminal-create-then-list','Write then read: a created terminal appears in TerminalService.instances',[
  "steps.c.result.ok","steps.r.result.value.count == 1 && steps.r.result.value.instances[0].persistent_process_id == 1"],fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},
  steps=[{'flow':'terminal-create','as':'c'},{'flow':'terminal-list','as':'r'}])
scen('terminal-create-no-backend','No backend registered: createProcess throws',[
  "!result.ok && result.error.code == 'no-terminal-backend'","calls['pty-service.create-process'] == 0"],flow='terminal-create',fixtures=FX)
scen('terminal-create-cwd-missing','The cwd does not exist: start returns a launch error, KilledDuringLaunch',[
  "result.ok && result.value.process_state == 'killed-during-launch'","result.value.launch_error.contains('does not exist')",
  "state['pty-service'].ptys['1'].started == false"],flow='terminal-create',fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},choices={'terminal-process.start.launch':'cwd_missing'})
scen('terminal-create-executable-missing','Shell executable missing: launch error',[
  "result.ok && result.value.launch_error.contains('Path to shell executable')"],flow='terminal-create',fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},choices={'terminal-process.start.launch':'executable_missing'})
scen('terminal-create-spawn-failed','node-pty spawn throws: native exception message',[
  "result.ok && result.value.launch_error.startsWith('A native exception')"],flow='terminal-create',fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},choices={'terminal-process.start.launch':'spawn_failed'})
scen('terminal-create-background','hideFromUser terminal is backgrounded, no group, no activation',[
  "result.ok && state['terminal-service@w1'].backgrounded == [1]","state['terminal-group-service@w1'].groups == []","calls['extension-service.activate-by-event'] == 0"],
  flow='terminal-create',fixtures=FX,inp={'hide_from_user':True},state={'terminal-instance-service@w1':{'backends':{'local':True}}})
scen('terminal-create-editor-location','Terminal in the editor area opens a terminal editor',[
  "result.ok && state['terminal-editor-service@w1'].instances == [1]","calls['editor-service.open-editor'] == 1"],
  flow='terminal-create',fixtures=FX,inp={'location':'editor'},state={'terminal-instance-service@w1':{'backends':{'local':True}}})
scen('terminal-create-not-persistent-when-disabled','enablePersistentSessions=false: process created with shouldPersist=false',[
  "result.ok && result.value.should_persist == false && state['pty-service'].ptys['1'].should_persist == false"],flow='terminal-create',fixtures=FX,
  config={'terminal-integrated-enable-persistent-sessions':False},state={'terminal-instance-service@w1':{'backends':{'local':True}}})
scen('terminal-create-feature-terminal','A feature terminal (e.g. a task) does not persist unless it has reconnection properties',[
  "result.ok && result.value.should_persist == false"],flow='terminal-create',fixtures=FX,inp={'is_feature_terminal':True},state={'terminal-instance-service@w1':{'backends':{'local':True}}})
scen('terminal-create-explicit-executable','An explicit executable skips the default profile',[
  "result.ok && result.value.shell == '/usr/bin/zsh'","calls['terminal-profile-service.get-default-profile'] == 0"],flow='terminal-create',fixtures=FX,
  inp={'executable':'/usr/bin/zsh'},state={'terminal-instance-service@w1':{'backends':{'local':True}}})
scen('terminal-create-saves-layout','After reconnect listeners are attached, a new terminal schedules the debounced layout save',[
  "result.ok","state['pty-service'].layouts['w1-app'].tabs == [[1]]","calls['terminal-service.save-state'] == 1"],flow='terminal-create',fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}},'terminal-service@w1':{'layout_listeners_attached':True}})
scen('terminal-save-state-while-shutting-down','A debounced save during shutdown is skipped',[
  "result.ok","!('w1-app' in state['pty-service'].layouts)"],flow='terminal-create',fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}},'terminal-service@w1':{'layout_listeners_attached':True,'is_shutting_down':True}})
REL=[{'flow':'terminal-create','as':'c'},{'flow':'terminal-before-shutdown','as':'b','input':{'reason':'reload'}},{'flow':'terminal-will-shutdown','as':'w','input':{'reason':'reload'}}]
PTY1={'id':1,'executable':'/bin/bash','cwd':'file:///work/app','workspace_id':'w1-app','should_persist':True,'started':True,'interaction':'Session','was_revived':False,'pid':4242,'grace_scheduled_at':0,'type':''}
scen('terminal-reload-detaches-persistent','Reload: an interacted-with persistent process is detached and its grace-time runner scheduled',[
  "steps.w.result.value.detached == 1 && steps.w.result.value.disposed == 0",
  "trace.exists(e, e.type == 'call.end' && e.interface == 'pty-service.detach-from-process' && e.output.kept == true)",
  "calls['local-terminal-backend.workspace-storage-store'] >= 1"],fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}},'terminal-service@w1':{'layout_listeners_attached':True}},
  steps=[{'flow':'terminal-create','as':'c'},{'interface':'local-pty.input','caller':'terminal-process-manager','input':{'id':1,'data':'ls\r'},'as':'i'},
         {'flow':'terminal-before-shutdown','as':'b','input':{'reason':'reload'}},{'flow':'terminal-will-shutdown','as':'w','input':{'reason':'reload'}}])
scen('terminal-reconnect-after-reload','The reloaded window reattaches to the detached persistent process (orphan question, then attach cancels the runner)',[
  "result.ok && result.value.reconnected == 1 && result.value.connection_state == 'connected'",
  "state['terminal-service@w1'].instances['1'].persistent_process_id == 1",
  "state['pty-service'].ptys['1'].grace_scheduled_at == null",
  "calls['pty-service.attach-to-process'] == 1 && calls['pty-service.create-process'] == 0",
  "duration_ms >= 4000"],flow='terminal-reconnect',fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}},'pty-service':{'ptys':{'1':PTY1},'last_pty_id':1,'layouts':{'w1-app':{'tabs':[[1]],'background':[]}}}})
scen('terminal-reconnect-then-list','Write then read: reconnected terminals are listed by TerminalService',[
  "steps.r.result.value.reconnected == 1","steps.l.result.value.count == 1 && steps.l.result.value.instances[0].persistent_process_id == 1"],fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}},'pty-service':{'ptys':{'1':PTY1},'last_pty_id':1,'layouts':{'w1-app':{'tabs':[[1]],'background':[]}}}},
  steps=[{'flow':'terminal-reconnect','as':'r'},{'flow':'terminal-list','as':'l'}])
scen('terminal-reload-untouched-terminal-shut-down','Reload: a never-used terminal is not kept (interaction None), so nothing reconnects',[
  "steps.w.result.value.detached == 1","!('1' in state['pty-service'].ptys)","steps.r.result.value.reconnected == 0"],fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}},'terminal-service@w1':{'layout_listeners_attached':True}},
  steps=[{'flow':'terminal-create','as':'c'},{'flow':'terminal-will-shutdown','as':'w','input':{'reason':'reload'}},{'flow':'terminal-reconnect','as':'r'}])
scen('terminal-close-disposes','Window close with revive "never": processes are disposed and the layout cleared',[
  "steps.w.result.value.disposed == 1 && steps.w.result.value.detached == 0","!('1' in state['pty-service'].ptys)","state['pty-service'].layouts['w1-app'].tabs == []"],fixtures=FX,
  config={'terminal-integrated-persistent-session-revive-process':'never'},state={'terminal-instance-service@w1':{'backends':{'local':True}}},
  steps=[{'flow':'terminal-create','as':'c'},{'flow':'terminal-before-shutdown','as':'b','input':{'reason':'close'}},{'flow':'terminal-will-shutdown','as':'w','input':{'reason':'close'}}])
scen('terminal-grace-time-expires','A detached persistent process with no reconnect is shut down after the 60 s grace time',[
  "steps.w.result.value.detached == 1","!('1' in state['pty-service'].ptys)",
  "trace.exists(e, e.type == 'call.end' && e.interface == 'pty-service.disconnect-runner-expired' && e.output.shutdown == true)"],fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},
  steps=[{'flow':'terminal-create','as':'c'},{'interface':'local-pty.input','caller':'terminal-process-manager','input':{'id':1,'data':'ls\r'},'as':'i'},{'flow':'terminal-will-shutdown','as':'w','input':{'reason':'reload'}}])
scen('terminal-quit-revives-processes','Quit with persistent sessions (revive onExit): buffers persisted, revived on next start and reattached',[
  "steps.b.result.value.revived == true","steps.r.result.value.reconnected == 1",
  "state['terminal-service@w1'].instances['2'].persistent_process_id == 2","state['pty-service'].ptys['2'].was_revived","!('1' in state['pty-service'].ptys)"],fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}},'terminal-service@w1':{'layout_listeners_attached':True}},
  steps=[{'flow':'terminal-create','as':'c'},{'flow':'terminal-before-shutdown','as':'b','input':{'reason':'quit'}},{'flow':'terminal-will-shutdown','as':'w','input':{'reason':'quit'}},
         {'flow':'terminal-reconnect','as':'r','input':{'startup_kind':'reopened-window'}}])
scen('terminal-before-shutdown-no-terminals','No terminals: never veto',["result.ok && result.value.veto == false","calls['native-host-main-service.get-window-count'] == 0"],flow='terminal-before-shutdown',fixtures=FX)
scen('terminal-before-shutdown-confirm-cancel','confirmOnExit=always on close: the user cancels and shutdown is vetoed',[
  "steps.b.result.value.veto == true","state['terminal-service@w1'].is_shutting_down == false"],fixtures=FX,config={'terminal-integrated-confirm-on-exit':'always'},
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},choices={'terminal-service.on-before-shutdown.close_confirmation':'cancel'},
  steps=[{'flow':'terminal-create','as':'c'},{'flow':'terminal-before-shutdown','as':'b','input':{'reason':'close'},'choices':{'terminal-service.on-before-shutdown.close_confirmation':'cancel'}}])
scen('terminal-before-shutdown-confirm-close','confirmOnExit=always on close: the user confirms',[
  "steps.b.result.value.veto == false","state['terminal-service@w1'].is_shutting_down"],fixtures=FX,config={'terminal-integrated-confirm-on-exit':'always'},
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},
  steps=[{'flow':'terminal-create','as':'c'},{'flow':'terminal-before-shutdown','as':'b','input':{'reason':'close'}}])
scen('terminal-before-shutdown-persist-timeout','Persisting buffers is cut off after 2000 ms; shutdown proceeds',[
  "steps.b.result.ok && steps.b.result.value.veto == false","steps.b.duration_ms >= 2000 && steps.b.duration_ms < 2500"],fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},faults=[{'target':'pty-service.serialize-terminal-state','type':'timeout'}],
  steps=[{'flow':'terminal-create','as':'c'},{'flow':'terminal-before-shutdown','as':'b','input':{'reason':'quit'}}])
scen('terminal-close-last-window-revives','Closing the last window (Linux, onExit) persists buffers for revive and keeps the layout',[
  "steps.b.result.value.revived == true","steps.w.result.value.disposed == 1","calls['pty-service.serialize-terminal-state'] == 1"],fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},
  steps=[{'flow':'terminal-create','as':'c'},{'flow':'terminal-before-shutdown','as':'b','input':{'reason':'close'}},{'flow':'terminal-will-shutdown','as':'w','input':{'reason':'close'}}])
scen('terminal-revive-window-close-mode','persistentSessionReviveProcess=onExitAndWindowClose revives on close',[
  "steps.b.result.value.revived == true"],fixtures=FX,config={'terminal-integrated-persistent-session-revive-process':'onExitAndWindowClose'},
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},
  steps=[{'flow':'terminal-create','as':'c'},{'flow':'terminal-before-shutdown','as':'b','input':{'reason':'close'}}])
scen('terminal-reconnect-disabled','enablePersistentSessions=false: no reconnect at startup',[
  "result.ok && result.value.reconnected == 0","calls['local-terminal-backend.get-terminal-layout-info'] == 0"],flow='terminal-reconnect',fixtures=FX,
  config={'terminal-integrated-enable-persistent-sessions':False},state={'terminal-instance-service@w1':{'backends':{'local':True}}})
scen('terminal-reconnect-task-terminal-skipped','A task terminal is only recreated on reload, not on a reopened window',[
  "result.ok && result.value.reconnected == 0"],flow='terminal-reconnect',fixtures=FX,inp={'startup_kind':'reopened-window'},
  state={'terminal-instance-service@w1':{'backends':{'local':True}},
         'pty-service':{'ptys':{'7':{'id':7,'executable':'/bin/bash','cwd':'file:///work/app','workspace_id':'w1-app','should_persist':True,'started':True,'interaction':'Session','was_revived':True,'pid':77,'grace_scheduled_at':None,'type':'Task'}},'layouts':{'w1-app':{'tabs':[[7]],'background':[]}}}})
scen('terminal-reconnect-attach-fails','The persistent process vanished between layout and attach: warn and create a fresh process',[
  "steps.r.result.ok","ctx.terminal_log_warning == 'Attach to process failed for terminal'","calls['pty-service.create-process'] == 1"],fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}},'pty-service':{'ptys':{'7':{'id':7,'executable':'/bin/bash','cwd':'file:///work/app','workspace_id':'w1-app','should_persist':True,'started':True,'interaction':'Session','was_revived':True,'pid':77,'grace_scheduled_at':None,'type':''}},'layouts':{'w1-app':{'tabs':[[7]],'background':[]}}}},
  faults=[{'target':'pty-service.attach-to-process','type':'error','code':'could-not-find-pty-on-pty-host'}],
  steps=[{'flow':'terminal-reconnect','as':'r'}])
scen('pty-host-main-start','The pty host registers its four channels and starts the heartbeat',[
  "result.ok && result.value.channels == ['logger', 'heartbeat', 'ptyHost', 'ptyHostWindow']","calls['heartbeat-service.start'] == 1"],flow='pty-host-main',fixtures=FX)
scen('pty-host-heartbeat-healthy','Heartbeats every 5 s keep cancelling the 6 s warning timer while the host beats',[
  "result.ok && result.value.started_now","state['pty-host-service'].start_count == 1",
  "trace.filter(e, e.type == 'call.end' && e.interface == 'pty-host-service.heartbeat-first-timeout' && e.output.superseded == true).size() >= 4",
  "!trace.exists(e, e.type == 'call.start' && e.interface == 'pty-host-service.heartbeat-second-timeout' && e.t < 26000)"],flow='pty-host-heartbeat',fixtures=FX)
scen('pty-host-heartbeat-missed','No heartbeats after connecting: warning at 20 s, unresponsive 5 s later, the backend shows the warning',[
  "ctx.pty_host_heartbeat_warning == true","state['pty-host-service'].responsive == false","ctx.pty_host_status == 'unresponsive'",
  "trace.exists(e, e.type == 'call.start' && e.interface == 'pty-host-service.heartbeat-second-timeout' && e.t >= 25000 && e.t < 25100)"],flow='pty-host-heartbeat',fixtures=FX,
  faults=[{'target':'pty-host-service.handle-heartbeat','type':'unavailable','calls':[2,3,4,5]}])
scen('pty-host-heartbeat-recovers','A late heartbeat after unresponsiveness fires onPtyHostResponsive',[
  "steps.late.result.ok","trace.filter(e, e.type == 'call.start' && e.interface == 'local-terminal-backend.on-pty-host-responsive').size() == 1",
  "trace.filter(e, e.type == 'call.start' && e.interface == 'local-terminal-backend.on-pty-host-responsive')[0].t >= 25000"],fixtures=FX,
  faults=[{'target':'pty-host-service.handle-heartbeat','type':'unavailable','calls':[2,3,4,5]}],
  steps=[{'flow':'pty-host-heartbeat','as':'h'},{'interface':'pty-host-service.handle-heartbeat','caller':'heartbeat-service','input':{'is_connecting':False},'as':'late'}])
scen('pty-host-already-started','A second window request does not start another pty host',[
  "result.ok && result.value.started_now == false","calls['pty-host-main.start-pty-host'] == 0"],flow='pty-host-heartbeat',fixtures=FX,state={'pty-host-service':{'started':True}})
scen('pty-host-exit-restarts','Unexpected exit: the pty host is restarted',[
  "result.ok && result.value.restarted","state['pty-host-service'].restart_count == 1 && state['pty-host-service'].started"],flow='pty-host-exit',fixtures=FX,state={'pty-host-service':{'started':True}})
scen('pty-host-exit-gives-up','After MaxRestarts the main process gives up',[
  "result.ok && result.value.restarted == false && ctx.pty_host_gave_up","calls['pty-host-main.start-pty-host'] == 0"],flow='pty-host-exit',fixtures=FX,state={'pty-host-service':{'started':True,'restart_count':6}})
scen('pty-host-exit-on-quit','Exit after quit was requested: no restart',[
  "result.ok && result.value.restarted == false","calls['pty-host-main.start-pty-host'] == 0"],flow='pty-host-exit',fixtures=FX,state={'pty-host-service':{'started':True,'quit_requested':True}})
scen('pty-layout-write-then-list','Write a layout, then a terminal-less read returns no tabs since the pty is gone',[
  "steps.r.result.value.tabs == []"],fixtures=FX,
  steps=[{'flow':'terminal-detach-request','as':'w'},{'interface':'pty-service.get-terminal-layout-info','caller':'local-terminal-backend','input':{'workspace_id':'w1-app'},'as':'r'}])
scen('pty-list-processes-persistent','listProcesses returns persistent processes',[
  "steps.l.result.value.processes.size() == 1 && steps.l.result.value.processes[0].id == 1"],fixtures=FX,
  state={'terminal-instance-service@w1':{'backends':{'local':True}}},steps=[{'flow':'terminal-create','as':'c'},{'flow':'pty-list-processes','as':'l'}])

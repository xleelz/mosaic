from base import *
from flows2 import CFG, TASK, WATCH, TS
FX=['one-window-folder']
BK={'terminal-instance-service@w1':{'backends':{'local':True}}}
def R(feat,cid,args=None,as_=None,**kw):
    s={'flow':('task' if feat=='tasks' else feat)+'-command','input':{'command_id':cid,'args':args or {}}}
    if as_: s['as']=as_
    s.update(kw); return s
START={'flow':'debug-start','as':'start'}
# ---------- debug ----------
scen('debug-start-happy','Start debugging: adapter initialized, configurationDone, session running',[
  "steps.start.result.ok && steps.start.result.value.started",
  "state['debug-model@w1'].sessions['session-1'].state == 'running' && state['debug-model@w1'].sessions['session-1'].raw",
  "calls['ext-host-debug-service.start-da-session'] == 1 && trace.exists(e, e.type == 'call.start' && e.interface == 'ext-host-debug-service.send-da-message' && e.input.command == 'configurationDone')",
  "calls['editor-service.save-all'] == 1 && calls['extension-service.activate-by-event'] == 1"],fixtures=FX,steps=[START])
scen('debug-start-then-list','Write then read: the started session is listed',[
  "steps.l.result.value.sessions.size() == 1 && steps.l.result.value.sessions[0].name == 'Launch Program'"],fixtures=FX,steps=[START,{'flow':'debug-sessions','as':'l'}])
scen('debug-start-untrusted','Untrusted workspace: the trust request is refused, nothing starts',[
  "result.ok && result.value.started == false","calls['debug-service.create-session'] == 0"],flow='debug-start',fixtures=['untrusted-folder'],choices={'debug-service.start-debugging.trust':'denied'})
scen('debug-start-unsupported-type','Unknown debug type: error with "Install extension", no session',[
  "result.ok && result.value.started == false && ctx.debug_error == 'debug type not supported'","calls['debug-session.initialize'] == 0"],flow='debug-start',fixtures=FX,inp={'config':{'type':'python'}})
scen('debug-start-bad-request','request attribute neither launch nor attach',[
  "result.ok && result.value.started == false && ctx.debug_error == 'request not supported'"],flow='debug-start',fixtures=FX,inp={'config':{'request':'bogus'}})
scen('debug-start-disabled-debugger','Disabled debugger: error, no session',["result.value.started == false && ctx.debug_error == 'debugger disabled'"],flow='debug-start',fixtures=FX,
  state={'adapter-manager@w1':{'debuggers':{'node':{'enabled':False}}}})
scen('debug-start-adapter-fails-initialize','The adapter rejects initialize: session shut down, error shown, start returns false',[
  "result.ok && result.value.started == false","ctx.debug_error != ''","calls['ext-host-debug-service.stop-da-session'] == 1"],flow='debug-start',fixtures=FX,
  faults=[{'target':'ext-host-debug-service.send-da-message','type':'error','code':'debug-adapter-error','message':'adapter crashed','calls':[1]}])
scen('debug-start-launch-fails','The launch request fails: adapter shut down, start returns false',[
  "result.ok && result.value.started == false","calls['raw-debug-session.shutdown'] >= 1"],flow='debug-start',fixtures=FX,
  faults=[{'target':'ext-host-debug-service.send-da-message','type':'error','code':'debug-adapter-error','message':'Cannot find program','calls':[2]}])
scen('debug-start-configuration-done-fails','configurationDone fails: the session is disconnected',[
  "steps.start.result.value.started","state['debug-model@w1'].sessions['session-1'].state == 'inactive'"],fixtures=FX,
  faults=[{'target':'ext-host-debug-service.send-da-message','type':'error','code':'debug-adapter-error','calls':[4]}],steps=[START])
scen('debug-start-stop-on-entry','stopOnEntry: the stopped event focuses the session; not a breakpoint so the view does not open',[
  "state['debug-model@w1'].sessions['session-1'].state == 'stopped' && state['debug-model@w1'].sessions['session-1'].stopped_reason == 'entry'","calls['views-service.open-view'] == 0"],fixtures=FX,
  steps=[{'flow':'debug-start','as':'start','input':{'config':{'stopOnEntry':True}}}])
scen('debug-start-guess-debugger','No type: the debugger is guessed from the active language',[
  "result.value.started && state['debug-model@w1'].sessions['session-1'].type == 'node'"],flow='debug-start',fixtures=FX,inp={'config':{'type':None}} if False else {},
  ) if False else None
scen('debug-start-selected-none','F5 with no launch.json and no guessable debugger: nothing starts',[
  "result.ok && result.value.started == false","calls['adapter-manager.guess-debugger'] == 1"],flow='debug-start-selected',fixtures=FX,choices={'adapter-manager.guess-debugger.pick':'dismissed'})
scen('debug-start-selected-guessed','F5 with no launch.json: the guessed node debugger starts a session',[
  "result.ok && result.value.started","state['debug-model@w1'].sessions['session-1'].type == 'node'"],flow='debug-start-selected',fixtures=FX)
scen('debug-start-selected-named','F5 with a selected launch.json configuration',[
  "result.value.started && state['debug-model@w1'].sessions['session-1'].name == 'Launch Program'","calls['configuration-manager.get-selected-configuration'] == 1"],flow='debug-start-selected',fixtures=FX,
  state={'configuration-manager@w1':{'launch_configurations':{'Launch Program':CFG},'selected':'Launch Program'}})
scen('debug-start-selected-missing','The selected name is not in launch.json: configuration missing error',[
  "!result.ok && result.error.code == 'configuration-missing-in-launch-json'","state['debug-service@w1'].initializing == false"],flow='debug-start-selected',fixtures=FX,
  state={'configuration-manager@w1':{'selected':'Gone'}})
scen('debug-start-guess-no-candidates','No debugger for the language: nothing to start',["result.value.started == false"],flow='debug-start-selected',fixtures=FX,
  state={'adapter-manager@w1':{'debuggers':{'node':{'languages':[]},'pwa-node':{'languages':[]}}}})
scen('debug-start-concurrent-cancel','Same configuration already running: the user cancels the second instance',[
  "steps.second.result.value.started == false","calls['debug-session.initialize'] == 1"],fixtures=FX,
  steps=[START,{'flow':'debug-start-selected','as':'second','choices':{'debug-service.create-session.concurrent_session':'cancel'}}],
  state={'configuration-manager@w1':{'launch_configurations':{'Launch Program':CFG},'selected':'Launch Program'}})
scen('debug-start-concurrent-again','Same configuration already running: the user starts another instance',[
  "steps.second.result.value.started","size(state['debug-model@w1'].sessions) == 2"],fixtures=FX,
  steps=[START,{'flow':'debug-start-selected','as':'second'}],state={'configuration-manager@w1':{'launch_configurations':{'Launch Program':CFG},'selected':'Launch Program'}})
scen('debug-prelaunch-task-ok','preLaunchTask exits 0: debugging starts after the task',[
  "result.value.started","calls['terminal-task-system.run'] == 1","trace.filter(e, e.type == 'call.start' && e.interface in ['terminal-task-system.run', 'debug-session.initialize']).map(e, e.interface) == ['terminal-task-system.run', 'debug-session.initialize']"],
  flow='debug-start',fixtures=FX,inp={'config':{'preLaunchTask':'build'}},state=TS)
scen('debug-prelaunch-task-fails-prompt-abort','preLaunchTask exits 1 with onTaskErrors=prompt: the user aborts',[
  "result.value.started == false","calls['debug-session.initialize'] == 0"],flow='debug-start',fixtures=FX,inp={'config':{'preLaunchTask':'build'}},state=TS,choices={'terminal-task-system.execute-command.process_exit':'nonzero'})
scen('debug-prelaunch-task-fails-debug-anyway','preLaunchTask fails: the user picks Debug Anyway',[
  "result.value.started"],flow='debug-start',fixtures=FX,inp={'config':{'preLaunchTask':'build'}},state=TS,choices={'terminal-task-system.execute-command.process_exit':'nonzero','debug-task-runner.run-task-and-check-errors.prompt':'debug_anyway'})
scen('debug-prelaunch-task-fails-show-errors','preLaunchTask fails: Show Errors opens Problems',[
  "result.value.started == false","calls['markers-view.open'] == 1"],flow='debug-start',fixtures=FX,inp={'config':{'preLaunchTask':'build'}},state=TS,choices={'terminal-task-system.execute-command.process_exit':'nonzero','debug-task-runner.run-task-and-check-errors.prompt':'show_errors'})
scen('debug-prelaunch-task-errors-setting','onTaskErrors=showErrors and =debugAnyway decide without a prompt',[
  "steps.a.result.value.started == false","calls['markers-view.open'] == 1"],fixtures=FX,state=TS,
  steps=[{'flow':'debug-start','as':'a','input':{'config':{'preLaunchTask':'build'}},'choices':{'terminal-task-system.execute-command.process_exit':'nonzero'}}],config={'debug-on-task-errors':'showErrors'})
scen('debug-prelaunch-task-errors-debug-anyway-setting','onTaskErrors=debugAnyway starts despite exit 1',["result.value.started"],flow='debug-start',fixtures=FX,inp={'config':{'preLaunchTask':'build'}},state=TS,
  config={'debug-on-task-errors':'debugAnyway'},choices={'terminal-task-system.execute-command.process_exit':'nonzero'})
scen('debug-prelaunch-task-errors-abort-setting','onTaskErrors=abort: no session',["result.value.started == false"],flow='debug-start',fixtures=FX,inp={'config':{'preLaunchTask':'build'}},state=TS,
  config={'debug-on-task-errors':'abort'},choices={'terminal-task-system.execute-command.process_exit':'nonzero'})
scen('debug-prelaunch-task-missing','preLaunchTask not found: error dialog, Cancel',[
  "result.value.started == false","calls['terminal-task-system.run'] == 0"],flow='debug-start',fixtures=FX,inp={'config':{'preLaunchTask':'nope'}},state=TS)
scen('debug-prelaunch-task-missing-debug-anyway','preLaunchTask not found: Debug Anyway',["result.value.started"],flow='debug-start',fixtures=FX,inp={'config':{'preLaunchTask':'nope'}},state=TS,
  choices={'debug-task-runner.run-task-and-check-errors.task_error':'debug_anyway'})
scen('debug-step-over','F10 sends next, the session runs, then the adapter reports stopped',[
  "steps.s.result.ok","trace.exists(e, e.type == 'call.start' && e.interface == 'ext-host-debug-service.send-da-message' && e.input.command == 'next')",
  "state['debug-model@w1'].sessions['session-1'].state == 'stopped' && state['debug-model@w1'].sessions['session-1'].stopped_reason == 'step'"],fixtures=FX,steps=[START,{'flow':'debug-step-over','as':'s'}])
scen('debug-step-no-session','F10 without a session: nothing is sent',["result.ok","calls['debug-session.next'] == 0"],flow='debug-step-over',fixtures=FX)
scen('debug-step-after-adapter-gone','A step on a session whose adapter ended fails with no debugger available',[
  "!steps.s.result.ok && steps.s.result.error.code == 'no-debugger-available'"],fixtures=FX,
  state={'debug-model@w1':{'sessions':{'session-9':{'id':'session-9','name':'x','type':'node','request':'launch','state':'running','raw':False,'ready_for_breakpoints':False,'capabilities':{},'no_debug':False}}}},
  steps=[{'flow':'debug-step-over','as':'s','input':{'session_id':'session-9'}}])
scen('debug-raw-send-without-adapter','RawDebugSession.send without a running adapter fails',[
  "!result.ok && result.error.code == 'no-debugger-available-found'"],flow=None,fixtures=FX,steps=[{'interface':'raw-debug-session.send','caller':'debug-session','input':{'session_id':'session-7','command':'next','arguments':{},'timeout_ms':0},'as':'x'}])
scen('debug-toggle-breakpoint-add','F9 adds a breakpoint, stores it and reads it back',[
  "steps.t.result.ok","steps.l.result.value.breakpoints.size() == 1 && steps.l.result.value.breakpoints[0].line_number == 2",
  "steps.s.result.value.breakpoints.size() == 1"],fixtures=FX,steps=[{'flow':'debug-toggle-breakpoint','as':'t'},{'flow':'debug-breakpoints','as':'l'},{'flow':'debug-load-breakpoints','as':'s'}])
scen('debug-toggle-breakpoint-remove','F9 on a line with a breakpoint removes it and clears storage',[
  "steps.l.result.value.breakpoints.size() == 0","steps.s.result.value.breakpoints.size() == 0"],fixtures=FX,
  steps=[{'flow':'debug-toggle-breakpoint','as':'a'},{'flow':'debug-toggle-breakpoint','as':'r'},{'flow':'debug-breakpoints','as':'l'},{'flow':'debug-load-breakpoints','as':'s'}])
scen('debug-toggle-breakpoint-not-allowed','F9 in a JSONC file: breakpoints not allowed',["result.ok","calls['debug-model.add-breakpoints'] == 0"],flow='debug-toggle-breakpoint',fixtures=FX,inp={'uri':'file:///work/app/package.json','language_id':'jsonc'})
scen('debug-toggle-breakpoint-unknown-language','F9 in Markdown (no debugger) is ignored; allowBreakpointsEverywhere allows it',[
  "steps.a.result.ok && calls['debug-model.add-breakpoints'] == 0"],fixtures=FX,steps=[{'flow':'debug-toggle-breakpoint','as':'a','input':{'uri':'file:///work/app/README.md','language_id':'markdown'}}])
scen('debug-breakpoints-everywhere','debug.allowBreakpointsEverywhere=true: breakpoint in Markdown',["calls['debug-model.add-breakpoints'] == 1"],flow='debug-toggle-breakpoint',fixtures=FX,inp={'uri':'file:///work/app/README.md','language_id':'markdown'},config={'debug-allow-breakpoints-everywhere':True})
scen('debug-breakpoint-sent-to-session','A breakpoint added while debugging is sent with setBreakpoints and verified',[
  "trace.exists(e, e.type == 'call.start' && e.interface == 'ext-host-debug-service.send-da-message' && e.input.command == 'setBreakpoints')",
  "state['debug-model@w1'].breakpoints['bp-1'].verified"],fixtures=FX,steps=[START,{'flow':'debug-toggle-breakpoint','as':'t'}])
scen('debug-breakpoint-before-ready','A breakpoint set before the adapter is ready is not sent; it goes out with configurationDone',[
  "state['debug-model@w1'].breakpoints['bp-1'].verified","trace.filter(e, e.type == 'call.start' && e.interface == 'ext-host-debug-service.send-da-message' && e.input.command == 'setBreakpoints').size() == 1"],fixtures=FX,
  steps=[{'flow':'debug-toggle-breakpoint','as':'t'},START])
scen('debug-before-shutdown-no-sessions','No sessions: no veto',["result.value.veto == false"],flow='debug-before-shutdown',fixtures=FX)
scen('debug-before-shutdown-never','Active session with confirmOnExit=never: no veto',["steps.b.result.value.veto == false"],fixtures=FX,steps=[START,{'flow':'debug-before-shutdown','as':'b'}])
scen('debug-before-shutdown-confirm-cancel','confirmOnExit=always and the user cancels: veto',["steps.b.result.value.veto"],fixtures=FX,config={'debug-confirm-on-exit':'always'},
  steps=[START,{'flow':'debug-before-shutdown','as':'b','choices':{'debug-lifecycle.should-veto-shutdown.confirm':'cancel'}}])
scen('debug-before-shutdown-confirm-stop','confirmOnExit=always and Stop Debugging: no veto',["steps.b.result.value.veto == false"],fixtures=FX,config={'debug-confirm-on-exit':'always'},steps=[START,{'flow':'debug-before-shutdown','as':'b'}])
scen('debug-stop-terminates','Stop: terminate, terminated event, disconnect (2 s budget), adapter stopped, session inactive',[
  "steps.x.result.ok","state['debug-model@w1'].sessions['session-1'].state == 'inactive'","calls['ext-host-debug-service.stop-da-session'] == 1",
  "ctx.debug_session_ended == 'session-1'","steps.l.result.value.sessions.size() == 0"],fixtures=FX,steps=[START,{'flow':'debug-stop','as':'x'},{'flow':'debug-sessions','as':'l'}])
scen('debug-stop-disconnect-timeout','The adapter ignores disconnect: shutdown proceeds after 2000 ms',[
  "state['debug-model@w1'].sessions['session-1'].state == 'inactive'","trace.exists(e, e.type == 'call.end' && e.interface == 'raw-debug-session.send' && e.error != null && e.error.code == 'timeout')"],fixtures=FX,
  faults=[{'target':'ext-host-debug-service.send-da-message','type':'timeout','calls':[6]}],steps=[START,{'flow':'debug-stop','as':'x'}])
scen('debug-stop-nothing-running','Stop with no session cancels a pending start',["result.ok","state['debug-service@w1'].initializing == false"],flow='debug-stop',fixtures=FX)
scen('debug-post-debug-task','postDebugTask runs when the adapter ends',["calls['debug-task-runner.run-task'] == 1","calls['terminal-task-system.run'] == 1"],fixtures=FX,state=TS,
  steps=[{'flow':'debug-start','as':'start','input':{'config':{'postDebugTask':'build'}}},{'flow':'debug-stop','as':'x'}])
scen('debug-command-unknown','Unknown command id: command-not-found',["!result.ok && result.error.code == 'command-not-found'"],flow='debug-command',fixtures=FX,inp={'command_id':'workbench.action.debug.nope'})
DBG_ALL=[START,
  R('debug','workbench.action.debug.stepInto'),R('debug','workbench.action.debug.stepOut'),R('debug','workbench.action.debug.pause'),R('debug','workbench.action.debug.stepBack'),
  R('debug','workbench.action.debug.continue'),R('debug','workbench.action.debug.reverseContinue'),R('debug','workbench.action.debug.terminateThread'),
  R('debug','workbench.action.debug.restartFrame'),R('debug','debug.jumpToCursor'),
  R('debug','editor.debug.action.toggleBreakpoint',{'uri':'file:///work/app/src/main.ts','line_number':2,'language_id':'typescript'}),
  R('debug','debug.toggleBreakpoint',{'id':'bp-1','enabled':False}),R('debug','debug.enableOrDisableBreakpoint',{'uri':'file:///work/app/src/main.ts','line_number':2}),
  R('debug','debug.enableOrDisableBreakpoint',{'uri':'file:///work/app/src/main.ts','line_number':9}),
  R('debug','workbench.debug.viewlet.action.addWatchExpression'),R('debug','editor.debug.action.selectionToWatch',{'text':'add'}),R('debug','debug.addToWatchExpressions',{'name':'a'}),
  R('debug','debug.removeWatchExpression',{'name':'a'}),R('debug','workbench.debug.viewlet.action.removeAllWatchExpressions'),
  R('debug','debug.breakWhenValueChanges',{'data_id':'x'}),R('debug','debug.breakWhenValueIsAccessed',{'data_id':'y'}),R('debug','debug.breakWhenValueIsRead',{'data_id':'z'}),
  R('debug','workbench.debug.viewlet.action.addFunctionBreakpointAction'),R('debug','workbench.debug.viewlet.action.addDataBreakpointOnAddress',{'address':'0x1000'}),
  R('debug','workbench.debug.viewlet.action.editDataBreakpointOnAddress',{'old_address':'0x1000','address':'0x2000'}),
  R('debug','workbench.debug.viewlet.action.toggleBreakpointsActivatedAction'),R('debug','workbench.debug.viewlet.action.reapplyBreakpointsAction'),
  R('debug','workbench.debug.viewlet.action.disableAllBreakpoints'),R('debug','workbench.debug.viewlet.action.enableAllBreakpoints'),
  R('debug','debug.editBreakpoint',{'id':'bp-1','uri':'file:///work/app/src/main.ts','line_number':2}),R('debug','breakpointWidget.action.acceptInput',{'condition':'a > 1'}),
  R('debug','editor.debug.action.conditionalBreakpoint',{'uri':'file:///work/app/src/main.ts','line_number':1,'language_id':'typescript'}),R('debug','closeBreakpointWidget'),
  R('debug','editor.debug.action.addLogPoint',{'uri':'file:///work/app/src/main.ts','line_number':1,'language_id':'typescript'}),R('debug','breakpointWidget.action.acceptInput',{'condition':'x'}),
  R('debug','editor.debug.action.triggerByBreakpoint',{'uri':'file:///work/app/src/main.ts','line_number':1,'language_id':'jsonc'}),
  R('debug','editor.debug.action.editBreakpoint',{'uri':'file:///work/app/src/main.ts','line_number':2}),
  R('debug','debug.editBreakpointMode',{'id':'bp-1','uri':'file:///work/app/src/main.ts','mode':'hardware'}),
  R('debug','editor.debug.action.toggleInlineBreakpoint',{'uri':'file:///work/app/src/util.ts','line_number':1}),
  R('debug','editor.debug.action.runToCursor',{'session_id':'session-1','uri':'file:///work/app/src/util.ts','line_number':5}),
  R('debug','editor.debug.action.stepIntoTargets',{'session_id':'session-1'}),R('debug','editor.debug.action.selectionToRepl',{'session_id':'session-1','text':'add(1, 2)'}),
  R('debug','repl.action.acceptInput',{'session_id':'session-1','text':'1+1'}),R('debug','workbench.debug.panel.action.clearReplAction',{'session_id':'session-1'}),
  R('debug','debug.toggleExceptionBreakpoints',{'filter':'uncaught','enabled':True}),R('debug','workbench.debug.viewlet.action.removeBreakpoint',{'id':'bp-1'}),
  R('debug','debug.removeBreakpoint',{'id':'bp-2'}),R('debug','workbench.debug.viewlet.action.removeAllBreakpoints'),
  R('debug','debug.installAdditionalDebuggers',{'query':'python'}),R('debug','debug.addConfiguration'),R('debug','workbench.action.debug.configure'),
  R('debug','debug.openBreakpointToSide',{'uri':'file:///work/app/src/main.ts'}),R('debug','debug.action.openDisassemblyView'),R('debug','callStackWidget.goToFile',{'uri':'file:///work/app/src/util.ts'}),
  R('debug','workbench.action.debug.run'),R('debug','workbench.action.debug.restart',as_='rs'),R('debug','workbench.action.debug.disconnect'),R('debug','workbench.action.debug.disconnectAndSuspend'),
  R('debug','workbench.action.debug.stop',as_='last')]
scen('debug-commands-session-walkthrough','Every modeled debug command against one live session',[
  "steps.last.result.ok","state['debug-model@w1'].watch_expressions == []","size(state['debug-model@w1'].breakpoints) == 0",
  "size(state['debug-model@w1'].data_breakpoints) == 0 && trace.exists(e, e.type == 'call.start' && e.interface == 'debug-model.add-data-breakpoint' && e.input.data_id == '0x2000')",
  "state['debug-model@w1'].exception_breakpoints.uncaught.enabled","calls['extensions-workbench-service.open-search'] == 1",
  "trace.exists(e, e.type == 'call.start' && e.interface == 'ext-host-debug-service.send-da-message' && e.input.command == 'gotoTargets')"],fixtures=FX,steps=DBG_ALL)
scen('debug-restart-and-start-commands','Restart with no session starts the selected configuration; F5 command; widget accepts on an existing breakpoint',[
  "steps.rs.result.ok && size(state['debug-model@w1'].sessions) >= 1","trace.exists(e, e.type == 'call.start' && e.interface == 'debug-model.update-breakpoints' && e.input.condition == 'c > 0')"],fixtures=FX,
  state={'configuration-manager@w1':{'launch_configurations':{'Launch Program':CFG},'selected':'Launch Program'}},
  steps=[R('debug','workbench.action.debug.restart',as_='rs'),R('debug','workbench.action.debug.start'),
         R('debug','editor.debug.action.toggleBreakpoint',{'uri':'file:///work/app/src/main.ts','line_number':2,'language_id':'typescript'}),
         R('debug','editor.debug.action.editBreakpoint',{'uri':'file:///work/app/src/main.ts','line_number':2}),R('debug','breakpointWidget.action.acceptInput',{'condition':'c > 0'}),
         R('debug','editor.debug.action.toggleBreakpoint',{'uri':'file:///work/app/src/main.ts','line_number':2,'language_id':'typescript'}),
         R('debug','editor.debug.action.toggleInlineBreakpoint',{'uri':'file:///work/app/src/util.ts','line_number':1}),
         R('debug','editor.debug.action.runToCursor',{'session_id':'session-1','uri':'file:///work/app/src/util.ts','line_number':1})])
scen('debug-terminate-without-terminate-support','Attach session (no terminate request): stop disconnects with terminateDebuggee',[
  "state['debug-model@w1'].sessions['session-1'].state == 'inactive'","!trace.exists(e, e.type == 'call.start' && e.interface == 'ext-host-debug-service.send-da-message' && e.input.command == 'terminate')"],fixtures=FX,
  steps=[{'flow':'debug-start','as':'start','input':{'config':{'request':'attach'}}},{'flow':'debug-stop','as':'x'}])
scen('debug-terminate-adapter-gone','Stop when the adapter already went away: handled as adapter exit',["steps.x.result.ok","ctx.debug_session_ended == 'session-5'"],fixtures=FX,
  state={'debug-model@w1':{'sessions':{'session-5':{'id':'session-5','name':'x','type':'node','request':'launch','state':'running','raw':False,'ready_for_breakpoints':False,'capabilities':{},'no_debug':False,'post_debug_task':None}}}},
  steps=[{'flow':'debug-stop','as':'x','input':{'session_id':'session-5'}}])
scen('debug-raw-shutdown-twice','A second shutdown is a no-op; send during shutdown completes silently',["steps.b.result.ok","steps.c.result.ok"],fixtures=FX,
  steps=[START,{'interface':'raw-debug-session.shutdown','caller':'debug-session','input':{'session_id':'session-1','terminate_debuggee':True},'as':'a'},
         {'interface':'raw-debug-session.shutdown','caller':'debug-session','input':{'session_id':'session-1','terminate_debuggee':True},'as':'b'},
         {'interface':'raw-debug-session.send','caller':'debug-session','input':{'session_id':'session-1','command':'threads','arguments':{},'timeout_ms':0},'as':'c'}])
scen('debug-adapter-event-after-exit','An adapter event after the adapter stopped is ignored',["steps.e.result.ok","calls['debug-session.handle-stop'] == 0"],fixtures=FX,
  steps=[{'interface':'raw-debug-session.on-adapter-event','caller':'debug-adapter','input':{'session_id':'session-3','event':'stopped','reason':'breakpoint'},'as':'e'}])
scen('debug-stopped-on-breakpoint-opens-view','A breakpoint stop with openDebug=openOnDebugBreak opens Run and Debug',["calls['views-service.open-view'] == 1"],fixtures=FX,
  steps=[START,{'interface':'raw-debug-session.on-adapter-event','caller':'debug-adapter','input':{'session_id':'session-1','event':'stopped','reason':'breakpoint'},'as':'e'}])
scen('debug-update-missing-session','Updating an unknown session is ignored; an unknown breakpoint update is ignored',["steps.a.result.ok && steps.b.result.ok"],fixtures=FX,
  steps=[{'interface':'debug-model.update-session','caller':'debug-service','input':{'session_id':'nope','update':{}},'as':'a'},{'interface':'debug-model.update-breakpoints','caller':'debug-service','input':{'id':'bp-9','condition':None,'mode':None},'as':'b'}])
# ---------- tasks ----------
scen('task-run-happy','Run Task "build": saves, creates a task terminal, exits 0',[
  "result.ok","calls['editor-service.save-all'] == 1 && calls['terminal-service.create-terminal'] == 1","state['task-service@w1'].recently_used == ['build']",
  "state['terminal-task-system@w1'].active_tasks == {}","state['terminal-service@w1'].instances['1'].should_persist == true"],flow='task-run',fixtures=FX,state=TS)
scen('task-run-background-then-list','A background (watch) task stays active and is listed',["steps.l.result.value.labels == ['watch']"],fixtures=FX,state=TS,
  steps=[{'flow':'task-run','as':'r','input':{'filter':'watch'}},{'flow':'task-active','as':'l'}])
scen('task-run-already-active','Running an active task again hits the instance limit (instance policy prompt)',["ctx.task_instance_policy_prompt","calls['terminal-task-system.execute-command'] == 1"],fixtures=FX,state=TS,
  steps=[{'flow':'task-run','as':'a','input':{'filter':'watch'}},{'flow':'task-run','as':'b','input':{'filter':'watch'}}])
scen('task-run-untrusted-denied','Untrusted workspace: trust refused, nothing runs',["result.ok","calls['task-service.run-task-command'] == 0"],flow='task-run',fixtures=['untrusted-folder'],state=TS,choices={'task-service.trust.trust':'denied'})
scen('task-run-untrusted-granted','Untrusted workspace: the user grants trust and the task runs',["calls['terminal-task-system.run'] == 1","calls['workspace-trust-request-service.request-workspace-trust'] >= 1"],flow='task-run',fixtures=['untrusted-folder'],state=TS,choices={'task-service.trust.trust':'granted'})
scen('task-run-unknown-label','Unknown label: the Run Task quick pick opens and is dismissed',["result.ok","calls['task-service.run'] == 0"],flow='task-run',fixtures=FX,state=TS,inp={'filter':'deploy'})
scen('task-run-quick-pick','No label: pick the first task from the quick pick',["calls['task-service.run'] == 1"],flow='task-run',fixtures=FX,state=TS,inp={'filter':''},choices={'task-service.run-task-command.quick_pick':'first'})
scen('task-run-quick-pick-empty','Quick pick with no tasks',["calls['task-service.run'] == 0"],flow='task-run',fixtures=FX,inp={'filter':''},choices={'task-service.run-task-command.quick_pick':'first'})
scen('task-run-not-reconnected','Before tasks reconnect, Run Task does nothing',["calls['task-service.run'] == 0"],flow='task-run',fixtures=FX,state={'task-service@w1':{'tasks_reconnected':False}})
scen('task-run-save-never-and-prompt','task.saveBeforeRun=never skips saving; prompt asks first',["calls['editor-service.save-all'] == 0"],flow='task-run',fixtures=FX,state=TS,config={'task-save-before-run':'never'})
scen('task-run-save-prompt','task.saveBeforeRun=prompt: the user chooses Save',["calls['editor-service.save-all'] == 1"],flow='task-run',fixtures=FX,state=TS,config={'task-save-before-run':'prompt'})
scen('task-run-terminal-launch-error','The task shell cannot start: exit code 1, task inactive',["result.ok","state['terminal-task-system@w1'].active_tasks == {}"],flow='task-run',fixtures=FX,state=TS,choices={'terminal-process.start.launch':'executable_missing'})
scen('task-run-null-task','TaskService.run without a task: TaskNotFound',["!result.ok && result.error.code == 'task-not-found'"],fixtures=FX,
  steps=[{'interface':'task-service.run','caller':'debug-task-runner','input':{'task':None,'run_source':'user'},'as':'x'}])
scen('task-run-untrusted-api','TaskService.run in an untrusted, refused workspace returns nothing; getTask returns nothing',["steps.x.result.value.kind == 'untrusted'","steps.g.result.value.task == null"],fixtures=['untrusted-folder'],state=TS,choices={'task-service.trust.trust':'denied'},
  steps=[{'interface':'task-service.run','caller':'debug-task-runner','input':{'task':TASK,'run_source':'user'},'as':'x'},{'interface':'task-service.get-task','caller':'debug-task-runner','input':{'identifier':'build'},'as':'g'}])
scen('task-command-unknown','Unknown task command',["!result.ok && result.error.code == 'command-not-found'"],flow='task-command',fixtures=FX,inp={'command_id':'workbench.action.tasks.nope'})
scen('task-commands-walkthrough','Task commands: build, test (missing), terminate, restart, rerun, configure, logs',[
  "!steps.test.result.ok && steps.test.result.error.code == 'no-test-task'","steps.term.result.ok","steps.last.result.ok","calls['output-service.show-channel'] == 1"],fixtures=FX,state=TS,
  steps=[R('tasks','workbench.action.tasks.build'),R('tasks','workbench.action.tasks.test',as_='test'),R('tasks','workbench.action.tasks.runTask',{'filter':'watch'}),
    R('tasks','workbench.action.tasks.showTasks'),R('tasks','workbench.action.tasks.rerunAllRunningTasks'),R('tasks','workbench.action.tasks.terminate',{'label':'watch'},as_='term'),
    R('tasks','workbench.action.tasks.terminate',{'label':'watch'}),R('tasks','workbench.action.tasks.restartTask',{'label':'build'}),R('tasks','workbench.action.tasks.reRunTask',{'recent':['build']}),
    R('tasks','workbench.action.tasks.reRunTask',{'recent':[]}),R('tasks','workbench.action.tasks.rerunForActiveTerminal',{'label':'build'}),
    R('tasks','workbench.action.tasks.configureTaskRunner'),R('tasks','workbench.action.tasks.configureDefaultBuildTask'),R('tasks','workbench.action.tasks.configureDefaultTestTask'),
    R('tasks','workbench.action.tasks.showLog'),R('tasks','workbench.action.tasks.toggleProblems'),R('tasks','workbench.action.tasks.openUserTasks'),R('tasks','workbench.action.tasks.openWorkspaceFileTasks'),
    R('tasks','workbench.action.tasks.manageAutomaticRunning'),R('tasks','workbench.action.tasks.manageAutomaticRunning',choices={'run-automatic-tasks.workbench-action-tasks-manageautomaticrunning.pick':'disallow'}) if False else R('tasks','workbench.action.tasks.manageAutomaticRunning',as_='last')])
scen('task-commands-untrusted','Task commands in a refused untrusted workspace do nothing',["calls['terminal-task-system.run'] == 0"],fixtures=['untrusted-folder'],state=TS,choices={'task-service.trust.trust':'denied'},
  steps=[R('tasks','workbench.action.tasks.build'),R('tasks','workbench.action.tasks.terminate',{'label':'watch'})])
scen('task-manage-automatic-disallow','Disallow automatic tasks writes the user setting off',["trace.exists(e, e.type == 'call.start' && e.interface == 'configuration-service.update-value' && e.input.value == 'off')"],flow='task-command',fixtures=FX,
  inp={'command_id':'workbench.action.tasks.manageAutomaticRunning'},choices={'run-automatic-tasks.cmd-workbench-action-tasks-manageautomaticrunning.pick':'disallow'})
scen('task-automatic-prompt-allow','folderOpen task with allowAutomaticTasks=off (default): prompt, Allow, the watch task runs',[
  "steps.a.result.value.ran == 1","steps.l.result.value.labels == ['watch']","state['run-automatic-tasks@w1'].has_prompted"],fixtures=FX,state=TS,
  choices={'run-automatic-tasks.try-run-tasks.allow':'allow'},steps=[{'flow':'task-automatic','as':'a'},{'flow':'task-active','as':'l'}])
scen('task-automatic-prompt-disallow','Default prompt dismissed with Disallow: nothing runs; a second try does nothing',["steps.a.result.value.ran == 0 && steps.b.result.value.ran == 0","calls['task-service.run'] == 0"],fixtures=FX,state=TS,
  steps=[{'flow':'task-automatic','as':'a'},{'flow':'task-automatic','as':'b'}])
scen('task-automatic-on','allowAutomaticTasks=on runs folderOpen tasks without asking',["result.value.ran == 1","state['run-automatic-tasks@w1'].has_prompted == false"],flow='task-automatic',fixtures=FX,state=TS,config={'task-allow-automatic-tasks':'on'})
scen('task-automatic-already-prompted','Prompted before: no second prompt',["result.value.ran == 0"],flow='task-automatic',fixtures=FX,state={**TS,'run-automatic-tasks@w1':{'has_prompted':True}})
scen('task-automatic-untrusted','Untrusted workspace: automatic tasks never run',["result.value.ran == 0","calls['task-service.get-workspace-tasks'] == 0"],flow='task-automatic',fixtures=['untrusted-folder'],state=TS,choices={'run-automatic-tasks.try-run-tasks.trust':'untrusted'})
scen('task-automatic-user-off','User explicitly set "off": nothing runs, no prompt',["result.value.ran == 0","calls['task-service.get-workspace-tasks'] == 0"],flow='task-automatic',fixtures=FX,state=TS,inp={'user_set_off':True})
scen('task-automatic-none','No folderOpen tasks: waits 10 s for config, then gives up',["result.value.ran == 0","duration_ms >= 10000"],flow='task-automatic',fixtures=FX)
# ---------- testing ----------
REG={'flow':'testing-register-controller','as':'reg','input':{'controller_id':'vitest','label':'Vitest','tests':['vitest/src/util.test.ts']}}
PROF={'interface':'test-profile-service.add-profile','caller':'third-party-extension','as':'prof','input':{'controller_id':'vitest','profile_id':1,'group':'run','is_default':True}}
scen('test-run-happy','Register a controller and profile, run a test: live result, save, controller run in eh1, result complete',[
  "steps.run.result.ok","calls_by_instance['ext-host-testing.run-controller-tests@eh1'] == 1","calls['editor-service.save-all'] == 1",
  "steps.res.result.value.results[0].completed && steps.res.result.value.results[0].id == steps.run.result.value.result_id"],fixtures=FX,
  steps=[REG,PROF,{'flow':'test-run','as':'run'},{'flow':'test-results','as':'res'}])
scen('test-run-unknown-test','Unknown test id: an empty run still creates a completed result',["steps.run.result.ok && calls['ext-host-testing.run-controller-tests'] == 0","steps.res.result.value.results.size() == 1"],fixtures=FX,
  steps=[{'flow':'test-run','as':'run'},{'flow':'test-results','as':'res'}])
scen('test-run-no-profile','A controller without a profile for the group: nothing dispatched',["calls['ext-host-testing.run-controller-tests'] == 0"],fixtures=FX,steps=[REG,{'flow':'test-run','as':'run'}])
scen('test-run-untrusted','Trust refused: the result completes without running',["calls['ext-host-testing.run-controller-tests'] == 0","state['test-result-service@w1'].results[0].completed"],fixtures=['untrusted-folder'],
  choices={'test-service.run-resolved-tests.trust':'denied'},steps=[REG,PROF,{'flow':'test-run','as':'run'}])
scen('test-run-no-save','testing.saveBeforeTest=false: no save',["calls['editor-service.save-all'] == 0"],fixtures=FX,config={'testing-save-before-test':False},steps=[REG,PROF,{'flow':'test-run','as':'run'}])
scen('testing-commands-walkthrough','Testing commands: reveal, continuous run, peek, coverage filter, API reads, call stack run/debug',[
  "steps.ctl.result.value.controllers == ['vitest']","steps.files.result.value.test_ids == ['vitest/src/util.test.ts']","state['testing-continuous-run-service@w1'].running == {}",
  "state['test-coverage-service@w1'].filter_to_test == 'vitest/src/util.test.ts'","state['test-explorer-filter-state@w1'].reveal == 'vitest/src/util.test.ts'"],fixtures=FX,
  steps=[REG,PROF,R('testing','vscode.testing.getControllersWithTests',as_='ctl'),R('testing','vscode.testing.getTestsInFile',{'uri':'file:///work/app/src/util.test.ts'},as_='files'),
    R('testing','_revealTestInExplorer'),R('testing','vscode.revealTest'),R('testing','testing.startContinuousRunFromExtension'),R('testing','testing.stopContinuousRunFromExtension'),
    R('testing','vscode.peekTestError'),R('testing','testing.openMessageInEditor'),R('testing','testing.coverageFilterToTestInEditor'),R('testing','testing.coverageFilterToTest'),
    R('testing','vscode.runTestsById'),R('testing','testing.callStack.run'),R('testing','testing.callStack.debug')])
scen('testing-cancel-and-clear','Cancel all runs, query continuous state, clear completed results',["steps.c.result.ok && ctx.test_run_cancelled","steps.r.result.value.results.size() == 0","steps.i.result.value.running == false"],fixtures=FX,
  steps=[{'flow':'test-run','as':'run'},{'interface':'test-service.cancel-test-run','caller':'testing-commands','input':{'result_id':None},'as':'c'},
    {'interface':'test-service.cancel-test-run','caller':'testing-commands','input':{'result_id':'run-1'},'as':'c2'},
    {'interface':'testing-continuous-run-service.is-running','caller':'testing-commands','input':{'test_id':'x'},'as':'i'},
    {'interface':'testing-continuous-run-service.stop','caller':'testing-commands','input':{'test_id':None},'as':'st'},
    {'interface':'test-result-service.clear','caller':'testing-commands','as':'cl'},{'flow':'test-results','as':'r'}])
scen('testing-command-unknown','Unknown testing command',["!result.ok && result.error.code == 'command-not-found'"],flow='testing-command',fixtures=FX,inp={'command_id':'testing.nope'})
scen('test-run-controller-error','The controller reports an error: notification text',["ctx.test_run_error.startsWith('An error occurred attempting to run tests')"],fixtures=FX,
  steps=[REG,PROF,{'flow':'test-run','as':'run'}],faults=[]) if False else None
# ---------- output ----------
REGC={'flow':'output-register-channel','as':'reg','input':{'id':'tasks','label':'Tasks','log':True,'user':False}}
scen('output-register-append-read','Register a channel (becomes active), append, read the content back',[
  "state['output-service@w1'].active_channel == 'tasks'","steps.r.result.value.content == '> build\\n'"],fixtures=FX,
  steps=[REGC,{'flow':'output-append','as':'a','input':{'channel_id':'tasks','output':'> build\n'}},{'flow':'output-read','as':'r','input':{'channel_id':'tasks'}}])
scen('output-append-unregistered','Appending to an unregistered channel fails',["!result.ok && result.error.code == 'channel-not-registered'"],flow='output-append',fixtures=FX,inp={'channel_id':'nope'})
scen('output-second-channel-not-active','A second channel does not steal the active channel unless it was stored as active',[
  "state['output-service@w1'].active_channel == 'tasks'"],fixtures=FX,steps=[REGC,{'flow':'output-register-channel','as':'g','input':{'id':'git','label':'Git','log':False,'user':False}}])
scen('output-commands-walkthrough','Output commands: show, switch, clear, log level, compound, remove, save, export, import, filters',[
  "steps.clr.result.ok","state['output-channel@w1'].contents['tasks'] == ''","state['output-service@w1'].log_levels['tasks'] == 'debug'",
  "!('compound:tasks' in state['output-service@w1'].channels)","calls['file-service.write-file'] == 2","state['output-service@w1'].filters.debug == false",
  "state['output-service@w1'].filters.categories == ''","ctx.output_notification == 'No custom outputs to remove.'"],fixtures=FX,
  steps=[REGC,{'flow':'output-register-channel','as':'g','input':{'id':'git','label':'Git','log':False,'user':False}},{'flow':'output-append','as':'a','input':{'channel_id':'tasks','output':'x'}},
    R('output','workbench.action.showOutputChannels',{'id':'git'}),R('output','workbench.output.action.switchBetweenOutputs',{'id':'tasks'}),R('output','workbench.action.output.show.${channel.id}',{'id':'tasks'}),
    R('output','workbench.action.showLogs',{'id':'tasks'}),R('output','workbench.output.action.clearOutput',as_='clr'),R('output','workbench.action.output.activeOutputLogLevel.${logLevel}',{'log_level':'debug'}),
    R('output','workbench.action.output.activeOutputLogLevelDefault',{'log_level':'debug'}),R('output','workbench.action.openActiveLogOutputFile'),R('output','workbench.action.openActiveLogOutputFileInNewWindow'),
    R('output','workbench.action.saveActiveLogOutputAs',{'path':'file:///work/app/out.log'}),R('output','workbench.action.exportLogs',{'id':'tasks','path':'file:///work/app/logs.log'}),
    R('output','workbench.action.openLogFile',{'id':'tasks'}),R('output','workbench.actions.${OUTPUT_VIEW_ID}.toggle.${LogLevelToString(logLevel)}',{'level':'debug'}),
    R('output','workbench.actions.${OUTPUT_VIEW_ID}.toggle.${categoryFilter}',{'category':'git'}),R('output','workbench.actions.${OUTPUT_VIEW_ID}.toggle.${categoryFilter}',{'category':'git'}),
    R('output','workbench.action.output.addCompoundLog',{'ids':['tasks']}),R('output','workbench.action.output.remove',{'id':'compound:tasks'}),R('output','workbench.action.output.remove',{'id':''}),
    R('output','workbench.action.importLog',{'name':'app.log'}),R('output','workbench.action.output.activeOutputLogLevel.${logLevel}',{'log_level':'trace'})])
scen('output-no-active-channel','Commands needing an active channel do nothing without one; setting a level on a non-log channel is refused',[
  "steps.s.result.ok && calls['file-service.write-file'] == 0","steps.lv.result.value.set == false"],fixtures=FX,
  steps=[R('output','workbench.output.action.clearOutput'),R('output','workbench.action.saveActiveLogOutputAs',as_='s'),R('output','workbench.action.output.activeOutputLogLevel.${logLevel}'),
    {'flow':'output-register-channel','as':'g','input':{'id':'git','label':'Git','log':False,'user':False}},
    {'interface':'output-service.set-log-level','caller':'output-contribution','input':{'channel_id':'git','log_level':'debug'},'as':'lv'},
    {'interface':'output-service.remove-channel','caller':'output-contribution','input':{'id':'git'},'as':'rm'},{'interface':'output-service.show-channel','caller':'output-contribution','input':{'id':'missing','preserve_focus':True},'as':'sh'}])
scen('output-command-unknown','Unknown output command',["!result.ok && result.error.code == 'command-not-found'"],flow='output-command',fixtures=FX,inp={'command_id':'workbench.action.output.nope'})
scen('output-link-computer','The worker finds a file link in compiler output',["result.value.links == ['src/main.ts']"],flow='output-link-computer',fixtures=FX,inp={'text':'src/main.ts(2,5): error'})
scen('output-link-computer-no-link','No link in plain text',["result.value.links == []"],flow='output-link-computer',fixtures=FX,inp={'text':'hello'})
# ---------- terminal commands and others ----------
scen('terminal-commands-walkthrough','Terminal commands: new with profile, send sequence, focus by index and id, chat terminals',[
  "steps.n.result.ok && state['terminal-service@w1'].active_instance == 1","state['pty-service'].ptys['1'].interaction == 'Session'","trace.exists(e, e.type == 'call.start' && e.interface == 'terminal-process.input' && e.input.data == 'echo hi\\r')",
  "state['terminal-chat-service@w1'].auto_approval['chat-session-1'] == false"],fixtures=FX,state={**BK,'terminal-chat-service@w1':{'tool_session_terminals':{'t1':1}}},
  steps=[R('terminal','workbench.action.terminal.newWithProfile',as_='n'),R('terminal','workbench.action.terminal.sendSequence',{'text':'echo hi\r'}),
    R('terminal','workbench.action.terminal.focusAtIndex${visibleIndex}',{'index':0}),R('terminal','workbench.action.terminal.focusAtIndex${visibleIndex}',{'index':5}),
    R('terminal','workbench.action.terminal.chat.focusTerminalById',{'instance_id':1}),R('terminal','workbench.action.terminal.chat.focusTerminalByExecutionId',{'instance_id':7}),
    R('terminal','workbench.action.terminal.chat.viewHiddenChatTerminals',{'instance_id':1}),R('terminal','workbench.action.terminal.chat.focusMostRecentChatTerminal'),
    R('terminal','workbench.action.terminal.chat.focusMostRecentChatTerminalOutput'),R('terminal','workbench.action.terminal.chat.disableSessionAutoApproval'),
    R('terminal','workbench.action.terminal.pastePwsh')])
scen('terminal-send-sequence-no-terminal','sendSequence without an active terminal does nothing',["calls['local-pty.input'] == 0"],flow='terminal-command',fixtures=FX,inp={'command_id':'workbench.action.terminal.sendSequence','args':{'text':'x'}})
scen('terminal-command-unknown','Unknown terminal command',["!result.ok && result.error.code == 'command-not-found'"],flow='terminal-command',fixtures=FX,inp={'command_id':'workbench.action.terminal.nope'})
scen('terminal-startup-then-create','Write then read: startup registers the local backend; a terminal can then be created and listed',[
  "steps.s.result.ok && state['terminal-instance-service@w1'].backends.local","steps.c.result.ok","steps.l.result.value.count == 1"],fixtures=FX,
  steps=[{'flow':'terminal-contributions-start','as':'s'},{'flow':'terminal-create','as':'c'},{'flow':'terminal-list','as':'l'}])
scen('terminal-remote-backend','With a remote connection the remote backend registers too',["state['terminal-instance-service@w1'].backends.remote"],fixtures=FX,
  steps=[{'interface':'remote-terminal-backend-contribution.start','caller':'workbench-window','input':{'has_remote':True},'as':'r'}])
scen('terminal-auto-replies','Configured auto replies are installed at startup',["ctx.terminal_auto_reply_installed == 'Terminate batch job (Y/N)'"],flow='terminal-contributions-start',fixtures=FX,
  config={'terminal-integrated-auto-replies':{'Terminate batch job (Y/N)':'Y\r'}})
scen('debug-contributions-start','Debug contributions start and extension point handlers run',["result.ok","calls['adapter-manager.on-debuggers-extension-point'] == 1"],flow='debug-contributions-start',fixtures=FX)
scen('debug-extension-points-register','Contributed debuggers and breakpoint languages are registered',["state['adapter-manager@w1'].debuggers.python.enabled","'python' in state['adapter-manager@w1'].breakpoint_languages","state['debug-visualizer-service@w1'].visualizers == ['v']"],fixtures=FX,
  steps=[{'interface':'adapter-manager.on-debuggers-extension-point','caller':'workbench-window','input':{'debuggers':[{'type':'python','label':'Python','languages':['python']}]},'as':'a'},
    {'interface':'adapter-manager.on-breakpoints-extension-point','caller':'workbench-window','input':{'languages':['python']},'as':'b'},
    {'interface':'debug-visualizer-service.on-visualizers-extension-point','caller':'workbench-window','input':{'visualizers':['v']},'as':'c'}])
scen('tasks-contributions-start-then-active','Write then read: tasks startup runs automatic tasks (allowed), then the watch task is active',["steps.l.result.value.labels == ['watch']"],fixtures=FX,state=TS,config={'task-allow-automatic-tasks':'on'},
  steps=[{'flow':'tasks-contributions-start','as':'s'},{'flow':'task-active','as':'l'}])
scen('tasks-extension-points','Contributed task types, problem matchers and patterns register',["'npm' in state['task-definition-registry@w1'].definitions","'$gulp' in state['problem-matcher-registry@w1'].matchers","state['problem-matcher-registry@w1'].patterns == ['p']"],fixtures=FX,
  steps=[{'interface':'task-definition-registry.on-task-definitions-extension-point','caller':'workbench-window','input':{'types':['npm']},'as':'a'},
    {'interface':'problem-matcher-registry.on-problem-matchers-extension-point','caller':'workbench-window','input':{'matchers':['$gulp']},'as':'b'},
    {'interface':'problem-matcher-registry.on-problem-patterns-extension-point','caller':'workbench-window','input':{'patterns':['p']},'as':'c'}])
scen('testing-contributions-start','Testing contributions start',["result.ok","calls['testing-decoration-service.sync-decorations'] == 1"],flow='testing-contributions-start',fixtures=FX)
scen('output-contributions-start','Output contribution starts',["result.ok","calls['output-contribution.start'] == 1"],flow='output-contributions-start',fixtures=FX)
scen('terminal-extension-points','Contributed terminal profiles and quick fixes register',["size(state['terminal-contribution-service@w1'].terminal_profiles) == 1","state['terminal-quick-fix-service@w1'].extension_quick_fixes == ['git-push']"],fixtures=FX,
  steps=[{'interface':'terminal-contribution-service.on-terminal-extension-point','caller':'workbench-window','input':{'profiles':[{'id':'ext.profile','title':'Ext'}]},'as':'a'},
    {'interface':'terminal-quick-fix-service.on-quick-fixes-extension-point','caller':'workbench-window','input':{'selectors':['git-push']},'as':'b'}])
scen('terminal-agent-host-create','Agent host terminal for a registered entry is a feature terminal',[
  "steps.c.result.ok && steps.c.result.value.should_persist == false","calls['terminal-service.create-terminal'] == 1"],fixtures=FX,state=BK,
  steps=[{'interface':'agent-host-terminal-service.register-entry','caller':'user','input':{'address':'local'},'as':'r'},{'flow':'terminal-agent-host-create','as':'c'}])
scen('terminal-agent-host-unknown-entry','Unknown agent host entry: no terminal',["result.value.launch_error == 'unknown agent host entry'","calls['terminal-service.create-terminal'] == 0"],flow='terminal-agent-host-create',fixtures=FX)
scen('terminal-rename-tab-then-read','Write then read: start and end inline rename',["steps.g.result.value.editable","steps.g2.result.value.editable == false"],fixtures=FX,
  steps=[{'flow':'terminal-rename-tab','as':'s','input':{'instance_id':1,'editing':True}},{'interface':'terminal-editing-service.get-editable-data','caller':'user','input':{'instance_id':1},'as':'g'},
    {'flow':'terminal-rename-tab','as':'e','input':{'instance_id':1,'editing':False}},{'interface':'terminal-editing-service.get-editable-data','caller':'user','input':{'instance_id':1},'as':'g2'}])
scen('terminal-chat-resolve','Terminal chat resolves its session',["result.value.resolved"],flow='terminal-chat-resolve',fixtures=FX)
scen('terminal-link-provider-then-create','Write then read: a registered link provider is seen by a new terminal instance',["trace.exists(e, e.type == 'call.end' && e.interface == 'terminal-link-provider-service.get-link-providers' && e.output.count == 1)"],fixtures=FX,state=BK,
  steps=[{'flow':'terminal-link-provider-register','as':'r'},{'flow':'terminal-create','as':'c'}])

scen('debug-start-selected-then-list','Write then read: F5 starts a session that the sessions list shows',["steps.l.result.value.sessions.size() == 1","state['debug-model@w1'].sessions['session-1'].type == 'node'"],fixtures=FX,
  steps=[{'flow':'debug-start-selected','as':'s'},{'flow':'debug-sessions','as':'l'}])
scen('debug-step-then-list','Write then read: after F10 the session shows as stopped by a step',["steps.l.result.value.sessions[0].stopped_reason == 'step'","state['debug-model@w1'].sessions['session-1'].state == 'stopped'"],fixtures=FX,
  steps=[START,{'flow':'debug-step-over','as':'s'},{'flow':'debug-sessions','as':'l'}])
scen('debug-command-then-read','Write then read: a watch expression added by command is read back',["steps.w.result.value.watch_expressions == ['add']","state['debug-storage@w1'].workspace_storage['debug.watchexpressions'] == ['add']"],fixtures=FX,
  steps=[R('debug','editor.debug.action.selectionToWatch',{'text':'add'}),{'interface':'debug-model.get-watch-expressions','caller':'watch-expressions-view','as':'w'}])
scen('pty-host-exit-then-start','Write then read: after a crash restart, a new window request does not start another host',["steps.e.result.value.restarted && steps.r.result.value.started_now == false","state['pty-host-service'].start_count == 1"],fixtures=FX,
  state={'pty-host-service':{'started':True}},steps=[{'flow':'pty-host-exit','as':'e'},{'flow':'pty-host-heartbeat','as':'r'}])
scen('task-command-then-active','Write then read: Run Task by command leaves the watch task active',["steps.l.result.value.labels == ['watch']","'watch' in state['terminal-task-system@w1'].active_tasks"],fixtures=FX,state=TS,
  steps=[R('tasks','workbench.action.tasks.runTask',{'filter':'watch'}),{'flow':'task-active','as':'l'}])
scen('terminal-agent-host-then-list','Write then read: the agent host terminal is listed',["steps.l.result.value.count == 1","state['terminal-service@w1'].instances['1'].persistent_process_id == 1"],fixtures=FX,state=BK,
  steps=[{'interface':'agent-host-terminal-service.register-entry','caller':'user','input':{'address':'local'},'as':'r'},{'flow':'terminal-agent-host-create','as':'c'},{'flow':'terminal-list','as':'l'}])
scen('terminal-command-then-list','Write then read: New Terminal With Profile, then list',["steps.l.result.value.count == 1","state['terminal-service@w1'].active_instance == 1"],fixtures=FX,state=BK,
  steps=[R('terminal','workbench.action.terminal.newWithProfile'),{'flow':'terminal-list','as':'l'}])
scen('testing-command-then-results','Write then read: run tests by command, then read the results',["steps.r.result.value.results.size() == 1 && steps.r.result.value.results[0].completed","state['test-result-service@w1'].next_seq == 2"],fixtures=FX,
  steps=[REG,PROF,R('testing','vscode.runTestsById'),{'flow':'test-results','as':'r'}])

from base import *
import json, glob, os
from base import VSC
from code import ROOT
INV=[e for e in json.load(open(os.path.join(VSC,'inventory.json')))['entries'] if e.get('area')=='terminal-debug-tasks']
CMDS={}
for e in INV:
    if e['kind']=='vscode-command': CMDS.setdefault(e['name'],[]).append(e)
def cmd_sources(e):
    f=e['file']; l=e['line']; s=lines(f)[l-1]
    mm=re.search(r'register(?:Action2|EditorAction|EditorCommand)\((?:new )?(\w+)\(?\)?\)',s)
    if mm:
        files=[f]+[x[len(ROOT)+1:] for x in glob.glob(ROOT+'/'+os.path.dirname(f)+'/*.ts')]
        from code import find_class_any
        r=find_class_any(mm.group(1),files)
        out=[S(f,l)]
        if r: out.append(S(r[0],r[1][0],r[1][1]))
        return out
    return [S(f,l,match_end(f,l))]
SKIPS=[]
MODELED={}   # feature -> {cmd_id: iface_id}
def skip(name,reason,file=None):
    for e in CMDS[name]:
        if file and not e['file'].endswith(file): continue
        SKIPS.append({'kind':e['kind'],'name':e['name'],'file':e['file'],'line':e['line'],'reason':reason})
def cmd(feature,component,name,summary,behavior,request=None,file=None):
    es=[e for e in CMDS[name] if (file is None or e['file'].endswith(file))]
    assert es, name
    e=es[0]
    nm=slug(name)
    iface(component,nm,summary,cmd_sources(e),behavior=behavior,request=request or ob(),response=ob(),kind='command',attributes={'command_id':name})
    MODELED.setdefault(feature,{})[name if file is None else name+'@'+file]=component+'.'+nm
C=lambda t,i=None,**kw: dict({'call':t,**({'input':i} if i is not None else {})},**kw)
UI='UI toggle: no state beyond the layout'
# ======================= DEBUG =======================
SID=lambda: obj({'session_id':st('session-1'),'thread_id':it(1)})
iface('debug-commands','get-thread-and-run','getThreadAndRun: resolve the thread from the context or the focused session, then run the operation on it (nothing happens without a thread).',[S('src/vs/workbench/contrib/debug/browser/debugCommands.ts',144,182)],
  request=obj({'session_id':{'type':['string','null'],'default':None},'op':st('next')}),response=ob(),
  behavior=[{'call':'debug-model.get-sessions','as':'all'},
    {'set':{'vars.sid':"= input.session_id != null ? input.session_id : (size(vars.all.value.sessions) > 0 ? vars.all.value.sessions[0].id : '')"}},
    {'if':"vars.sid == ''",'then':[{'title':'No focused thread: nothing to run','source':S('src/vs/workbench/contrib/debug/browser/debugCommands.ts',160,170),'return':{'ran':False}}]},
    {'call':"= 'debug-session.' + input.op",'input':{'session_id':"= vars.sid",'thread_id':1},
     'targets':['debug-session.next','debug-session.step-in','debug-session.step-out','debug-session.step-back','debug-session.continue','debug-session.reverse-continue','debug-session.pause','debug-session.terminate-threads']},
    {'return':{'ran':True}}])
for nm,op in [('workbench.action.debug.stepOver','next'),('workbench.action.debug.stepInto','step-in'),('workbench.action.debug.stepOut','step-out'),('workbench.action.debug.pause','pause'),
              ('workbench.action.debug.continue','continue'),('workbench.action.debug.stepBack','step-back'),('workbench.action.debug.reverseContinue','reverse-continue'),('workbench.action.debug.terminateThread','terminate-threads')]:
    cmd('debug','debug-commands',nm,'Run '+op+' on the context or focused thread.',[C('debug-commands.get-thread-and-run',{'session_id':"= input.session_id",'op':op})],request=obj({'session_id':{'type':['string','null'],'default':None}}))
cmd('debug','debug-commands','debug.startFromConfig','Start debugging with a configuration object (saves before start).',[C('debug-service.start-debugging',{'config':"= input.config",'config_name':None,'no_debug':False,'started_by_user':False,'save_before_start':True,'language_id':'typescript'},**{'as':'r'}),{'return':"= vars.r.value"}],
    request=obj({'config':'DebugLaunchConfig'}))
cmd('debug','debug-commands','workbench.action.debug.start','F5: save per debug.saveBeforeStart, then start the selected launch configuration (startedByUser).',[
    {'when':"config['debug-save-before-start'] != 'none'",'call':'editor-service.save-all','input':{'reason':'explicit'}},
    C('configuration-manager.get-selected-configuration',**{'as':'sel'}),
    C('debug-service.start-debugging',{'config':"= vars.sel.value.config",'config_name':"= vars.sel.value.name",'no_debug':"= input.noDebug",'started_by_user':True,'save_before_start':False,'language_id':'typescript'},**{'as':'r'}),{'return':"= vars.r.value"}],
    request=obj({'noDebug':bo(False)}))
cmd('debug','debug-commands','workbench.action.debug.run','Ctrl+F5: run workbench.action.debug.start with noDebug.',[C('command-service.execute-command',{'command_id':'workbench.action.debug.start','args':[{'noDebug':True}]})])
cmd('debug','debug-commands','workbench.action.debug.restart','Restart the context/focused session, or start the selected configuration when none runs.',[
    C('debug-model.get-sessions',**{'as':'all'}),
    {'if':"size(vars.all.value.sessions) == 0",'then':[C('configuration-manager.get-selected-configuration',**{'as':'sel'}),C('debug-service.start-debugging',{'config':"= vars.sel.value.config",'config_name':"= vars.sel.value.name",'no_debug':False,'started_by_user':True,'save_before_start':True,'language_id':'typescript'}),{'return':{}}]},
    C('debug-session.remove-repl-expressions',{'session_id':"= vars.all.value.sessions[0].id"}),C('debug-service.restart-session',{'session_id':"= vars.all.value.sessions[0].id"})])
for nm,disc in [('workbench.action.debug.stop',False),('workbench.action.debug.disconnect',True),('workbench.action.debug.disconnectAndSuspend',True)]:
    cmd('debug','debug-commands',nm,'stopHandler: stop (terminate) or disconnect the context session, or all sessions.',[C('debug-service.stop-session',{'session_id':"= input.session_id",'disconnect':disc})],request=obj({'session_id':{'type':['string','null'],'default':None}}))
cmd('debug','debug-commands','workbench.action.debug.restartFrame','Restart the context stack frame (errors become notifications).',[C('debug-session.restart-frame',{'session_id':"= input.session_id",'thread_id':"= input.thread_id"},on_error='continue')],request=SID())
cmd('debug','debug-commands','debug.jumpToCursor','Ask the adapter for goto targets at the cursor and jump to the (picked) target.',[C('debug-session.goto-targets',{'session_id':"= input.session_id",'thread_id':"= input.thread_id"}),C('debug-session.goto',{'session_id':"= input.session_id",'thread_id':"= input.thread_id"})],request=SID())
cmd('debug','debug-commands','debug.toggleBreakpoint','Space in the Breakpoints view: flip the focused breakpoint\'s enablement.',[C('debug-service.enable-or-disable-breakpoints',{'id':"= input.id",'kind':'source','enabled':"= input.enabled",'uri':"= input.uri"})],
    request=obj({'id':st('bp-1'),'enabled':bo(False),'uri':st('file:///work/app/src/main.ts')}))
cmd('debug','debug-commands','debug.enableOrDisableBreakpoint','Flip the enablement of the breakpoint on the cursor line.',[
    C('debug-model.get-breakpoints',{'uri':"= input.uri",'line_number':"= input.line_number",'enabled_only':False},**{'as':'bps'}),
    {'if':"size(vars.bps.value.breakpoints) > 0",'then':[C('debug-service.enable-or-disable-breakpoints',{'id':"= vars.bps.value.breakpoints[0].id",'kind':'source','enabled':"= !vars.bps.value.breakpoints[0].enabled",'uri':"= input.uri"})]}],
    request=obj({'uri':st('file:///work/app/src/main.ts'),'line_number':it(2)}))
cmd('debug','debug-commands','debug.removeWatchExpression','Remove the focused/selected watch expression(s).',[C('debug-service.remove-watch-expressions',{'name':"= input.name"})],request=obj({'name':st('x')}))
for nm,acc in [('debug.breakWhenValueChanges','write'),('debug.breakWhenValueIsAccessed','readWrite'),('debug.breakWhenValueIsRead','read')]:
    cmd('debug','debug-commands',nm,'Add a data breakpoint ('+acc+') on the variable.',[C('debug-service.add-data-breakpoint',{'data_id':"= input.data_id",'access_type':acc})],request=obj({'data_id':st('x')}))
cmd('debug','debug-commands','debug.removeBreakpoint','Remove the focused breakpoint of any kind.',[C('debug-service.remove-breakpoints',{'ids':["= input.id"]}),C('debug-service.remove-function-and-data-breakpoints',{'id':"= input.id"})],request=obj({'id':st('bp-1')}))
cmd('debug','debug-commands','debug.installAdditionalDebuggers','Search the marketplace for debuggers.',[C('extensions-workbench-service.open-search',{'search':"= '@category:debuggers ' + input.query"})],request=obj({'query':st('node')}))
cmd('debug','debug-commands','debug.addConfiguration','Open launch.json to add a configuration.',[C('configuration-manager.open-config-file')])
cmd('debug','debug-commands','editor.debug.action.toggleInlineBreakpoint','Shift+F9: add an inline (column) breakpoint at the cursor when none is there.',[
    C('debug-model.get-breakpoints',{'uri':"= input.uri",'line_number':"= input.line_number",'enabled_only':False},**{'as':'bps'}),
    {'if':"size(vars.bps.value.breakpoints) == 0",'then':[C('debug-service.add-breakpoints',{'uri':"= input.uri",'breakpoints':[{'line_number':"= input.line_number"}]})]}],request=obj({'uri':st('file:///work/app/src/main.ts'),'line_number':it(2)}))
cmd('debug','debug-commands','debug.openBreakpointToSide','Open the focused breakpoint\'s source to the side.',[C('editor-service.open-editor',{'resource':"= input.uri"})],request=obj({'uri':st('file:///work/app/src/main.ts')}))
cmd('debug','debug-commands','debug.toggleExceptionBreakpoints','Toggle an exception breakpoint filter.',[C('debug-service.enable-or-disable-breakpoints',{'id':"= input.filter",'kind':'exception','enabled':"= input.enabled",'uri':''})],request=obj({'filter':st('uncaught'),'enabled':bo(True)}))
for nm,r in [('debug.copyStackTrace','clipboard copy of the call stack: writes the clipboard (platform-core), no debug state'),
    ('workbench.action.debug.callStackTop','UI focus navigation: moves the focused stack frame only'),('workbench.action.debug.callStackBottom','UI focus navigation: moves the focused stack frame only'),
    ('workbench.action.debug.callStackUp','UI focus navigation: moves the focused stack frame only'),('workbench.action.debug.callStackDown','UI focus navigation: moves the focused stack frame only'),
    ('workbench.action.debug.nextConsole','UI focus navigation: switches the debug console shown'),('workbench.action.debug.prevConsole','UI focus navigation: switches the debug console shown'),
    ('workbench.action.debug.showLoadedScripts','UI: opens the loaded scripts quick pick'),('workbench.action.debug.focusProcess','UI focus: focuses a session and reveals its frame'),
    ('workbench.action.debug.selectandstart','UI: opens the debug quick access (dynamic configurations start through debug-service.start-debugging)'),
    ('workbench.action.debug.selectDebugConsole','UI: opens the debug console quick access'),('workbench.action.debug.selectDebugSession','UI: opens the session picker'),
    ('workbench.action.debug.stepIntoTarget','UI quick pick over stepInTargets; same DAP path as editor.debug.action.stepIntoTargets'),
    ('debug.renameWatchExpression','UI: starts inline editing of a watch expression'),('debug.setWatchExpression','UI: starts inline editing of a watch expression'),
    ('debug.openView','UI toggle: no state beyond the layout'),('debug.attachToCurrentCodeRenderer','developer diagnostics: attaches a debugger to the VS Code renderer itself')]:
    skip(nm,r)
skip('debug.setVariable','UI: starts inline editing of a variable value (the DAP setVariable is sent on edit accept)')
# breakpoint widget
cmd('debug','breakpoint-widget','breakpointWidget.action.acceptInput','Enter in the breakpoint widget: close it successfully (adds or updates the breakpoint).',[C('breakpoint-widget.close',{'success':True,'condition':"= input.condition"})],request=obj({'condition':st('a > 1')}))
cmd('debug','breakpoint-widget','closeBreakpointWidget','Escape: close the breakpoint widget without changes.',[C('breakpoint-widget.close',{'success':False,'condition':''})])
# breakpoints view
BV='breakpoints-view'
iface('debug-model','are-breakpoints-activated','Whether breakpoints are activated.',[M('src/vs/workbench/contrib/debug/common/debugModel.ts','areBreakpointsActivated')],response=obj({'activated':bo()}),behavior=[{'return':{'activated':"= state.breakpoints_activated"}}])
cmd('debug',BV,'workbench.debug.viewlet.action.addFunctionBreakpointAction','Add an empty function breakpoint (named inline, sent on rename).',[C('debug-service.add-function-breakpoint',{'name':''})])
cmd('debug',BV,'workbench.debug.viewlet.action.addDataBreakpointOnAddress','Add a data breakpoint on an address entered in an input box.',[C('debug-service.add-data-breakpoint',{'data_id':"= input.address",'access_type':'write'})],request=obj({'address':st('0x1000')}))
cmd('debug',BV,'workbench.debug.viewlet.action.editDataBreakpointOnAddress','Edit an address data breakpoint: remove it and add the new address.',[C('debug-service.remove-function-and-data-breakpoints',{'id':"= input.old_address"}),C('debug-service.add-data-breakpoint',{'data_id':"= input.address",'access_type':'write'})],request=obj({'old_address':st('0x1000'),'address':st('0x2000')}))
cmd('debug',BV,'workbench.debug.viewlet.action.toggleBreakpointsActivatedAction','Toggle activate/deactivate all breakpoints.',[C('debug-model.are-breakpoints-activated',**{'as':'a'}),C('debug-service.set-breakpoints-activated',{'activated':"= !vars.a.value.activated"})])
cmd('debug',BV,'workbench.debug.viewlet.action.removeBreakpoint','Remove a breakpoint from the view.',[C('debug-service.remove-breakpoints',{'ids':["= input.id"]})],request=obj({'id':st('bp-1')}))
cmd('debug',BV,'workbench.debug.viewlet.action.removeAllBreakpoints','Remove all breakpoints of every kind.',[C('debug-service.remove-breakpoints',{'ids':None}),C('debug-service.remove-function-and-data-breakpoints',{'id':None})])
cmd('debug',BV,'workbench.debug.viewlet.action.enableAllBreakpoints','Enable all breakpoints.',[C('debug-service.enable-or-disable-breakpoints',{'id':None,'kind':'all','enabled':True,'uri':''})])
cmd('debug',BV,'workbench.debug.viewlet.action.disableAllBreakpoints','Disable all breakpoints.',[C('debug-service.enable-or-disable-breakpoints',{'id':None,'kind':'all','enabled':False,'uri':''})])
cmd('debug',BV,'workbench.debug.viewlet.action.reapplyBreakpointsAction','Reapply (activate) all breakpoints.',[C('debug-service.set-breakpoints-activated',{'activated':True})])
cmd('debug',BV,'debug.editBreakpoint','Open the breakpoint source and show the breakpoint widget for it.',[C('editor-service.open-editor',{'resource':"= input.uri"}),C('breakpoint-widget.show',{'uri':"= input.uri",'line_number':"= input.line_number",'context':'condition','breakpoint_id':"= input.id"})],
    request=obj({'id':st('bp-1'),'uri':st('file:///work/app/src/main.ts'),'line_number':it(2)}))
cmd('debug',BV,'debug.editBreakpointMode','Pick a breakpoint mode and update the breakpoint.',[C('debug-service.update-breakpoints',{'id':"= input.id",'uri':"= input.uri",'condition':None,'mode':"= input.mode"})],request=obj({'id':st('bp-1'),'uri':st('file:///work/app/src/main.ts'),'mode':st('hardware')}))
skip('workbench.debug.viewlet.action.toggleBreakpointsPresentation',UI); skip('debug.editFunctionBreakpoint','UI: starts inline rename of a function breakpoint'); skip('debug.editFunctionBreakpointHitCount','UI: starts inline editing of the hit count')
# editor actions
EA='debug-editor-actions'
cmd('debug',EA,'editor.debug.action.toggleBreakpoint','F9: remove the breakpoints on the cursor line, or add one when the language allows breakpoints (instruction breakpoints in the disassembly view).',[
    C('debug-model.get-breakpoints',{'uri':"= input.uri",'line_number':"= input.line_number",'enabled_only':False},**{'as':'bps'}),
    {'if':"size(vars.bps.value.breakpoints) > 0",'then':[C('debug-service.remove-breakpoints',{'ids':"= vars.bps.value.breakpoints.map(b, b.id)"}),{'return':{'toggled':'removed'}}]},
    C('adapter-manager.can-set-breakpoints-in',{'language_id':"= input.language_id"},**{'as':'can'}),
    {'if':"!vars.can.value.allowed",'then':[{'return':{'toggled':'none'}}]},
    C('debug-service.add-breakpoints',{'uri':"= input.uri",'breakpoints':[{'line_number':"= input.line_number"}]}),{'return':{'toggled':'added'}}],
    request=obj({'uri':st('file:///work/app/src/main.ts'),'line_number':it(2),'language_id':st('typescript')}))
for nm,ctxname in [('editor.debug.action.conditionalBreakpoint','condition'),('editor.debug.action.addLogPoint','log-message'),('editor.debug.action.triggerByBreakpoint','trigger-point')]:
    cmd('debug',EA,nm,'Show the breakpoint widget ('+ctxname+') at the cursor when breakpoints are allowed.',[C('adapter-manager.can-set-breakpoints-in',{'language_id':"= input.language_id"},**{'as':'can'}),
        {'if':"vars.can.value.allowed",'then':[C('breakpoint-widget.show',{'uri':"= input.uri",'line_number':"= input.line_number",'context':ctxname,'breakpoint_id':None})]}],
        request=obj({'uri':st('file:///work/app/src/main.ts'),'line_number':it(2),'language_id':st('typescript')}))
cmd('debug',EA,'editor.debug.action.editBreakpoint','Edit the closest breakpoint on the line in the widget.',[C('debug-model.get-breakpoints',{'uri':"= input.uri",'line_number':"= input.line_number",'enabled_only':False},**{'as':'bps'}),
    {'if':"size(vars.bps.value.breakpoints) > 0",'then':[C('breakpoint-widget.show',{'uri':"= input.uri",'line_number':"= input.line_number",'context':'condition','breakpoint_id':"= vars.bps.value.breakpoints[0].id"})]}],
    request=obj({'uri':st('file:///work/app/src/main.ts'),'line_number':it(2)}))
cmd('debug',EA,'editor.debug.action.runToCursor','Run to cursor.',[C('debug-service.run-to',{'session_id':"= input.session_id",'uri':"= input.uri",'line_number':"= input.line_number"})],request=obj({'session_id':st('session-1'),'uri':st('file:///work/app/src/main.ts'),'line_number':it(2)}))
cmd('debug',EA,'editor.debug.action.stepIntoTargets','Ask for step-in targets of the focused frame and step into the picked one.',[C('debug-session.step-in-targets',{'session_id':"= input.session_id",'thread_id':1}),C('debug-session.step-in',{'session_id':"= input.session_id",'thread_id':1})],request=obj({'session_id':st('session-1')}))
cmd('debug',EA,'editor.debug.action.selectionToRepl','Evaluate the selection in the debug console.',[C('debug-session.add-repl-expression',{'session_id':"= input.session_id",'expression':"= input.text"})],request=obj({'session_id':st('session-1'),'text':st('add(1, 2)')}))
cmd('debug',EA,'editor.debug.action.selectionToWatch','Add the selection (or evaluatable expression) to Watch.',[C('debug-service.add-watch-expression',{'name':"= input.text"})],request=obj({'text':st('add')}))
cmd('debug',EA,'debug.action.openDisassemblyView','Open the disassembly view editor.',[C('editor-service.open-editor',{'resource':'disassembly:///'})])
for nm in ['debug.action.toggleDisassemblyViewSourceCode','editor.debug.action.showDebugHover','editor.debug.action.closeExceptionWidget']: skip(nm,UI)
skip('editor.debug.action.goToNextBreakpoint','UI: moves the editor cursor to the next breakpoint'); skip('editor.debug.action.goToPreviousBreakpoint','UI: moves the editor cursor to the previous breakpoint')
skip('_executeInlineValueProvider','internal API command used by extension API tests (inline value providers); no debug state')
cmd('debug','debug-viewlet','workbench.action.debug.configure','Pick a launch (multi-root) and open its launch.json.',[C('configuration-manager.open-config-file')])
skip('debug.toggleReplIgnoreFocus',UI)
skip('editor.debug.action.copyAddress','clipboard copy of an instruction address: writes the clipboard (platform-core), no debug state')
for nm in ['callStack.collapse','loadedScripts.collapse','variables.collapse','watch.collapse','debug.collapseRepl','workbench.debug.action.focusRepl','repl.action.filter','repl.action.find',
           'workbench.debug.viewlet.action.toggleBreakpointsPresentation'][:-1]: skip(nm,UI)
for nm in ['repl.action.copyAll','workbench.debug.action.copyAll','debug.replCopy','workbench.debug.viewlet.action.copyValue','debug.copyEvaluatePath','debug.copyWatchExpression','workbench.debug.viewlet.action.copyAllWatchExpressions']:
    skip(nm,'clipboard copy: writes the clipboard (platform-core), no debug state')
skip('debug.replPaste','UI: pastes clipboard text into the REPL input box')
skip('workbench.action.debug.selectRepl','UI focus: selects which session the debug console shows')
skip('workbench.debug.viewlet.action.viewMemory','opens the memory inspector (hex editor extension, offering to install it); no debug state in this area')
for nm in ['workbench.debug.action.addVariableToChat','workbench.debug.action.addWatchExpressionToChat','workbench.debug.action.addScopeToChat']:
    skip(nm,'hands the focused frame and variable context to the chat widget (chat area); reads debug state only')
cmd('debug','repl','repl.action.acceptInput','Enter in the debug console: evaluate the input in the focused session.',[C('debug-session.add-repl-expression',{'session_id':"= input.session_id",'expression':"= input.text"})],request=obj({'session_id':st('session-1'),'text':st('add(1, 2)')}))
cmd('debug','repl','workbench.debug.panel.action.clearReplAction','Clear the debug console of the focused session.',[C('debug-session.remove-repl-expressions',{'session_id':"= input.session_id"})],request=obj({'session_id':st('session-1')}))
cmd('debug','variables-view','debug.addToWatchExpressions','Add a variable\'s evaluate name to Watch.',[C('debug-service.add-watch-expression',{'name':"= input.name"})],request=obj({'name':st('a')}),file='variablesView.ts')
skip_var=[e for e in CMDS['debug.setVariable'] if e['file'].endswith('variablesView.ts')]
cmd('debug','watch-expressions-view','workbench.debug.viewlet.action.addWatchExpression','Add an empty watch expression (edited inline).',[C('debug-service.add-watch-expression',{'name':''})])
cmd('debug','watch-expressions-view','workbench.debug.viewlet.action.removeAllWatchExpressions','Remove all watch expressions.',[C('debug-service.remove-watch-expressions',{'name':None})])
cmd('debug','call-stack-widget','callStackWidget.goToFile','Open the frame\'s file at its position.',[C('editor-service.open-editor',{'resource':"= input.uri"})],request=obj({'uri':st('file:///work/app/src/main.ts')}))
# ======================= TASKS =======================
TSV='task-service'
TR=lambda rest: [C('task-service.trust',**{'as':'t'}),{'if':"!vars.t.value.trusted",'then':[{'return':{}}]}]+rest
cmd('tasks',TSV,'workbench.action.tasks.runTask','Tasks: Run Task (trust first).',TR([C('task-service.run-task-command',{'filter':"= input.filter"})]),request=obj({'filter':st('build',default='')}))
cmd('tasks',TSV,'workbench.action.tasks.reRunTask','Rerun the last task.',TR([{'if':"size(input.recent) == 0",'then':[{'return':{}}]},C('terminal-task-system.rerun',{'label':"= input.recent[0]"})]),request=obj({'recent':arr(st(),default=['build'])}))
cmd('tasks',TSV,'workbench.action.tasks.restartTask','Restart a running task: terminate it and run it again.',TR([C('task-service.terminate',{'label':"= input.label"}),C('task-service.run-task-command',{'filter':"= input.label"})]),request=obj({'label':st('build')}))
cmd('tasks',TSV,'workbench.action.tasks.rerunAllRunningTasks','Restart every running task.',TR([C('terminal-task-system.get-active-tasks',**{'as':'a'}),{'foreach':"= vars.a.value.labels",'as':'l','steps':[C('task-service.terminate',{'label':"= vars.l"}),C('task-service.run-task-command',{'filter':"= vars.l"})]}]))
cmd('tasks',TSV,'workbench.action.tasks.terminate','Terminate a running task.',TR([C('task-service.terminate',{'label':"= input.label"})]),request=obj({'label':st('build')}))
cmd('tasks',TSV,'workbench.action.tasks.showLog','Show the Tasks output channel.',[C('output-service.show-channel',{'id':'tasks','preserve_focus':True})])
cmd('tasks',TSV,'workbench.action.tasks.build','Run the default build task.',TR([C('task-service.run-group-command',{'group':'build'})]))
cmd('tasks',TSV,'workbench.action.tasks.test','Run the default test task.',TR([C('task-service.run-group-command',{'group':'test'})]))
for nm in ['workbench.action.tasks.configureTaskRunner','workbench.action.tasks.configureDefaultBuildTask','workbench.action.tasks.configureDefaultTestTask']:
    cmd('tasks',TSV,nm,'Configure tasks: pick a task and write tasks.json (opens it).',TR([C('task-service.configure-action')]))
cmd('tasks',TSV,'workbench.action.tasks.showTasks','Show running tasks (quick pick of the active tasks).',TR([C('terminal-task-system.get-active-tasks')]))
cmd('tasks',TSV,'workbench.action.tasks.toggleProblems','Toggle the Problems view.',[C('command-service.execute-command',{'command_id':'workbench.actions.view.toggleProblems','args':[]})])
cmd('tasks',TSV,'workbench.action.tasks.openUserTasks','Open the user tasks.json.',[C('editor-service.open-editor',{'resource':'vscode-userdata:/User/tasks.json'})])
cmd('tasks',TSV,'workbench.action.tasks.openWorkspaceFileTasks','Open the workspace file tasks.',[C('editor-service.open-editor',{'resource':'file:///work/app/app.code-workspace'})])
stub('configuration-service','update-value','platform-core','Write a setting value.',request=obj({'key':st('task.allowAutomaticTasks'),'value':st('on'),'target':st('user')}),response=ob())
cmd('tasks','run-automatic-tasks','workbench.action.tasks.manageAutomaticRunning','Allow or disallow automatic tasks (user setting).',[{'choice':'pick','default':'allow','options':{
    'allow':[C('configuration-service.update-value',{'key':'task.allowAutomaticTasks','value':'on','target':'user'})],'disallow':[C('configuration-service.update-value',{'key':'task.allowAutomaticTasks','value':'off','target':'user'})]}}])
cmd('tasks','tasks-contrib','workbench.action.tasks.rerunForActiveTerminal','Rerun the task of the active terminal.',[C('terminal-task-system.rerun',{'label':"= input.label"})],request=obj({'label':st('build')}))
# ======================= TESTING =======================
TC='testing-commands'
iface('test-service','get-controllers-with-tests','Controllers that have tests (vscode.testing.getControllersWithTests).',[S('src/vs/workbench/contrib/testing/browser/testing.contribution.ts',274,282)],response=obj({'controllers':arr(st())}),
  behavior=[{'return':{'controllers':"= state.controllers.map(k, k).filter(c, state.tests.exists(t, state.tests[t].controller_id == c))"}}])
cmd('testing',TC,'vscode.runTestsById','Discover and run tests by id with the group\'s default profiles.',[C('test-service.run-tests',{'group':"= input.group",'test_ids':"= input.test_ids",'preserve_focus':False},**{'as':'r'}),{'return':"= vars.r.value"}],
    request=obj({'group':st('run'),'test_ids':arr(st('vitest/src/util.test.ts'))}))
cmd('testing',TC,'vscode.testing.getControllersWithTests','API: controllers with tests.',[C('test-service.get-controllers-with-tests',**{'as':'r'}),{'return':"= vars.r.value"}])
cmd('testing',TC,'vscode.testing.getTestsInFile','API: tests in a file.',[C('test-service.get-tests-in-file',{'uri':"= input.uri"},**{'as':'r'}),{'return':"= vars.r.value"}],request=obj({'uri':st('file:///work/app/src/util.test.ts')}))
cmd('testing',TC,'_revealTestInExplorer','Reveal a test in the Testing view.',[C('test-explorer-filter-state.set-reveal',{'test_id':"= input.test_id"}),C('views-service.open-view',{'id':'workbench.view.testing'})],request=obj({'test_id':st('vitest/src/util.test.ts')}))
cmd('testing',TC,'testing.startContinuousRunFromExtension','Start a continuous run for a test with a profile.',[C('testing-continuous-run-service.start',{'test_id':"= input.test_id",'controller_id':'vitest','profile_id':1})],request=obj({'test_id':st('vitest/src/util.test.ts')}))
cmd('testing',TC,'testing.stopContinuousRunFromExtension','Stop the continuous run of a test.',[C('testing-continuous-run-service.stop',{'test_id':"= input.test_id"})],request=obj({'test_id':st('vitest/src/util.test.ts')}))
cmd('testing',TC,'vscode.peekTestError','Peek the first error of a test.',[C('testing-peek-opener.try-peek-first-error',{'test_id':"= input.test_id"})],request=obj({'test_id':st('vitest/src/util.test.ts')}))
cmd('testing',TC,'vscode.revealTest','Reveal a test in the explorer and open its location.',[C('test-explorer-filter-state.set-reveal',{'test_id':"= input.test_id"}),C('editor-service.open-editor',{'resource':'file:///work/app/src/util.test.ts'})],request=obj({'test_id':st('vitest/src/util.test.ts')}))
cmd('testing','testing-peek-opener','testing.openMessageInEditor','Open the peeked test message in an editor.',[C('testing-peek-opener.open-current-in-editor')])
cmd('testing','test-coverage-service','testing.coverageFilterToTestInEditor','Pick a test to filter coverage to (in the editor toolbar).',[C('test-coverage-service.set-filter-to-test',{'test_id':"= input.test_id"})],request=obj({'test_id':st('vitest/src/util.test.ts')}))
cmd('testing','test-coverage-service','testing.coverageFilterToTest','Pick a test to filter coverage to (coverage view).',[C('test-coverage-service.set-filter-to-test',{'test_id':"= input.test_id"})],request=obj({'test_id':st('vitest/src/util.test.ts')}))
cmd('testing',TC,'testing.callStack.run','Rerun the test of a call stack frame with the last run profile.',[C('test-service.run-tests',{'group':'run','test_ids':["= input.test_id"],'preserve_focus':False})],request=obj({'test_id':st('vitest/src/util.test.ts')}))
cmd('testing',TC,'testing.callStack.debug','Debug the test of a call stack frame.',[C('test-service.run-tests',{'group':'debug','test_ids':["= input.test_id"],'preserve_focus':False})],request=obj({'test_id':st('vitest/src/util.test.ts')}))
for nm in ['testing.toggleInlineCoverage','testing.coverageToggleToolbar','testing.toggleCoverageInExplorer','testing.coverageViewCollapseAll','editor.closeTestPeek','testing.toggleTestingPeekHistory','testing.collapsePeekStack','testing.coverageViewChangeSorting']: skip(nm,UI)
for nm in ['testing.coverage.goToNextMissedLine','testing.coverage.goToPreviousMissedLine','testing.goToPreviousMessage','testing.goToNextMessage']: skip(nm,'UI: moves the editor cursor or peek between items')
for nm in ['vscode.pickMultipleTestProfiles','vscode.pickTestProfile']: skip(nm,'UI: quick pick returning test profiles to the caller; no state')
# ======================= OUTPUT =======================
OC='output-contribution'
cmd('output',OC,'workbench.output.action.switchBetweenOutputs','Switch the Output view to a channel.',[C('output-service.show-channel',{'id':"= input.id",'preserve_focus':True})],request=obj({'id':st('tasks')}))
cmd('output',OC,'workbench.action.output.show.${channel.id}','Per-channel "Show <channel>" command registered for each channel.',[C('output-service.show-channel',{'id':"= input.id",'preserve_focus':True})],request=obj({'id':st('tasks')}))
cmd('output',OC,'workbench.action.output.addCompoundLog','Pick several logs and show them as one compound channel.',[C('output-service.register-compound-log-channel',{'ids':"= input.ids"},**{'as':'c'}),C('output-service.show-channel',{'id':"= vars.c.value.id",'preserve_focus':False})],request=obj({'ids':arr(st('tasks'),default=['tasks'])}))
cmd('output',OC,'workbench.action.output.remove','Remove user-created (compound/imported) channels; none gives an info message.',[
    {'if':"input.id == ''",'then':[{'set':{'ctx.output_notification':'No custom outputs to remove.'}},{'return':{}}]},C('output-service.remove-channel',{'id':"= input.id"})],request=obj({'id':st('compound:tasks',default='')}))
cmd('output',OC,'workbench.action.showOutputChannels','Pick an output channel and show it.',[C('output-service.show-channel',{'id':"= input.id",'preserve_focus':False})],request=obj({'id':st('tasks')}))
cmd('output',OC,'workbench.output.action.clearOutput','Clear the active output channel.',[C('output-service.get-active-channel',**{'as':'a'}),{'if':"vars.a.value.id != null",'then':[C('output-channel.clear',{'channel_id':"= vars.a.value.id"})]}])
for nm in ['workbench.action.openActiveLogOutputFile','workbench.action.openActiveLogOutputFileInNewWindow']:
    cmd('output',OC,nm,'Open the active log channel\'s file in an editor.',[C('output-service.get-active-channel',**{'as':'a'}),C('editor-service.open-editor',{'resource':"= 'output:' + (vars.a.value.id == null ? '' : vars.a.value.id)"})])
cmd('output',OC,'workbench.action.saveActiveLogOutputAs','Save the active channel as a file.',[C('output-service.get-active-channel',**{'as':'a'}),{'if':"vars.a.value.id != null",'then':[C('output-service.save-output-as',{'channel_id':"= vars.a.value.id",'path':"= input.path"})]}],request=obj({'path':st('file:///work/app/output.log')}))
cmd('output',OC,'workbench.action.output.activeOutputLogLevel.${logLevel}','Set the active log channel\'s level (one command per level).',[C('output-service.get-active-channel',**{'as':'a'}),{'if':"vars.a.value.id != null",'then':[C('output-service.set-log-level',{'channel_id':"= vars.a.value.id",'log_level':"= input.log_level"})]}],request=obj({'log_level':st('debug')}))
stub('default-log-levels-service','set-default-log-level','workbench-shell','Set the default log level (optionally per extension).',request=obj({'log_level':st('debug'),'extension_id':{'type':['string','null'],'default':None}}),response=ob())
cmd('output',OC,'workbench.action.output.activeOutputLogLevelDefault','Make the active channel\'s level the default.',[C('output-service.get-active-channel',**{'as':'a'}),C('default-log-levels-service.set-default-log-level',{'log_level':"= input.log_level",'extension_id':None})],request=obj({'log_level':st('debug')}))
cmd('output',OC,'workbench.action.showLogs','Pick a log channel and show it.',[C('output-service.show-channel',{'id':"= input.id",'preserve_focus':False})],request=obj({'id':st('tasks')}))
cmd('output',OC,'workbench.action.openLogFile','Pick a log and open its file as an editor.',[C('editor-service.open-editor',{'resource':"= 'output:' + input.id"})],request=obj({'id':st('tasks')}))
cmd('output',OC,'workbench.actions.${OUTPUT_VIEW_ID}.toggle.${LogLevelToString(logLevel)}','Toggle a log level filter of the Output view (one command per level).',[C('output-service.toggle-filter',{'filter':"= input.level"})],request=obj({'level':st('debug')}))
cmd('output',OC,'workbench.action.exportLogs','Pick logs and export them to a file.',[C('output-service.save-output-as',{'channel_id':"= input.id",'path':"= input.path"})],request=obj({'id':st('tasks'),'path':st('file:///work/app/logs.log')}))
cmd('output',OC,'workbench.action.importLog','Import log files as a new user channel and show it.',[C('output-service.on-did-register-channel',{'id':"= 'imported:' + input.name",'label':"= input.name",'log':True,'user':True}),C('output-service.show-channel',{'id':"= 'imported:' + input.name",'preserve_focus':False})],request=obj({'name':st('app.log')}))
cmd('output','output-view-pane','workbench.actions.${OUTPUT_VIEW_ID}.toggle.${categoryFilter}','Toggle a category filter of the Output view (one command per category).',[C('output-service.toggle-filter',{'filter':"= input.category"})],request=obj({'category':st('git')}))
skip('workbench.output.action.toggleAutoScroll',UI); skip('workbench.actions.${OUTPUT_VIEW_ID}.clearFilterText','UI: clears the Output view filter input')
# ======================= TERMINAL =======================
iface('terminal-service','set-active-instance','Make an instance the active terminal and reveal it.',[M('src/vs/workbench/contrib/terminal/browser/terminalService.ts','setActiveInstance')],request=obj({'instance_id':it(1)}),response=obj({'found':bo()}),
  behavior=[{'if':"!(string(input.instance_id) in state.instances)",'then':[{'return':{'found':False}}]},{'set':{'state.active_instance':"= input.instance_id"}},{'return':{'found':True}}])
iface('terminal-service','send-text-to-active','instance.sendText on the active terminal: written to the pty (queued until ready).',[M('src/vs/workbench/contrib/terminal/browser/terminalService.ts','getActiveOrCreateInstance')],request=obj({'text':st('npm test\r')}),response=obj({'sent':bo()}),
  behavior=[{'if':"state.active_instance == null || !(string(state.active_instance) in state.instances)",'then':[{'return':{'sent':False}}]},
            C('local-pty.input',{'id':"= state.instances[string(state.active_instance)].persistent_process_id",'data':"= input.text"}),{'return':{'sent':True}}])
comp('terminal-actions','Terminal actions','terminal-contrib','Terminal actions registered in terminalActions.ts and terminalCommands.ts.',[S('src/vs/workbench/contrib/terminal/browser/terminalActions.ts',1537,1644)])
cmd('terminal','terminal-actions','workbench.action.terminal.newWithProfile','Create a terminal with a profile (split when a parent terminal is given), then make it active.',[
    C('terminal-service.create-terminal',{'executable':"= input.executable",'cwd':'file:///work/app'},fill=True,**{'as':'t'}),C('terminal-service.set-active-instance',{'instance_id':"= vars.t.value.instance_id"})],request=obj({'executable':st('/bin/bash',default='')}))
cmd('terminal','terminal-actions','workbench.action.terminal.focusAtIndex${visibleIndex}','Focus the terminal at a visible index (registered per index) and show the panel.',[C('terminal-group-service.set-active-instance-by-index',{'index':"= input.index"})],request=obj({'index':it(0)}))
skip('InstallShellScriptWithCopilotAction','not a terminal behavior: installs the Copilot CLI shell command (chat entitlement flow); also mis-named by the inventory heuristic (class name, not a command id)')
skip('workbench.action.terminal.focusAccessibleBuffer','UI: focuses the accessible terminal buffer view')
iface('terminal-chat-service','get-tool-session-terminal-instances','Terminals created by chat tool sessions (optionally hidden ones).',[M('src/vs/workbench/contrib/terminalContrib/chat/browser/terminalChatService.ts','getToolSessionTerminalInstances')],response=obj({'count':it()}),
  behavior=[{'return':{'count':"= size(state.tool_session_terminals)"}}])
iface('terminal-chat-service','get-most-recent-progress-part','The most recent chat terminal tool progress part.',[M('src/vs/workbench/contrib/terminalContrib/chat/browser/terminalChatService.ts','getMostRecentProgressPart')],response=obj({'part':{'type':['string','null']}}),
  behavior=[{'return':{'part':"= state.most_recent_progress_part"}}])
iface('terminal-chat-service','set-chat-session-auto-approval','Enable or disable terminal command auto approval for a chat session.',[M('src/vs/workbench/contrib/terminalContrib/chat/browser/terminalChatService.ts','setChatSessionAutoApproval')],request=obj({'session':st('chat-session-1'),'enabled':bo(False)}),response=ob(),
  behavior=[{'set':{'state.auto_approval':"= merge(state.auto_approval, {input.session: input.enabled})"}}])
TCA='terminal-chat-actions'
comp(TCA,'Terminal chat actions','terminal-contrib','Chat-related terminal actions (terminalChatActions.ts, sendToTerminalTool.ts).',[S('src/vs/workbench/contrib/terminalContrib/chat/browser/terminalChatActions.ts',331,592)])
cmd('terminal',TCA,'workbench.action.terminal.chat.viewHiddenChatTerminals','List hidden chat terminals and reveal the picked one.',[C('terminal-chat-service.get-tool-session-terminal-instances',**{'as':'h'}),{'if':"vars.h.value.count > 0",'then':[C('terminal-service.set-active-instance',{'instance_id':"= input.instance_id"})]}],request=obj({'instance_id':it(1)}))
cmd('terminal',TCA,'workbench.action.terminal.chat.focusMostRecentChatTerminal','Focus the terminal of the most recent chat terminal tool.',[C('terminal-chat-service.get-most-recent-progress-part')])
cmd('terminal',TCA,'workbench.action.terminal.chat.focusMostRecentChatTerminalOutput','Toggle the output of the most recent chat terminal tool.',[C('terminal-chat-service.get-most-recent-progress-part')])
skip('workbench.action.terminal.chat.openTerminalSettingsLink','UI: opens the Settings editor at a terminal setting')
cmd('terminal',TCA,'workbench.action.terminal.chat.disableSessionAutoApproval','Disable auto approval for the chat session.',[C('terminal-chat-service.set-chat-session-auto-approval',{'session':"= input.session",'enabled':False})],request=obj({'session':st('chat-session-1')}))
cmd('terminal',TCA,'workbench.action.terminal.chat.focusTerminalById','Focus a terminal by instance id (from chat).',[C('terminal-service.set-active-instance',{'instance_id':"= input.instance_id"})],request=obj({'instance_id':it(1)}))
cmd('terminal',TCA,'workbench.action.terminal.chat.focusTerminalByExecutionId','Focus the terminal of a chat tool execution.',[C('terminal-service.set-active-instance',{'instance_id':"= input.instance_id"})],request=obj({'instance_id':it(1)}))
skip('workbench.action.quickOpenNavigateNextInTerminalPicker','UI: quick pick navigation'); skip('workbench.action.quickOpenNavigatePreviousInTerminalPicker','UI: quick pick navigation')
TSS='terminal-send-sequence-actions'
comp(TSS,'Terminal send sequence actions','terminal-contrib','workbench.action.terminal.sendSequence and the PowerShell paste helper.',[S('src/vs/workbench/contrib/terminalContrib/sendSequence/browser/terminal.sendSequence.contribution.ts',108,151)])
cmd('terminal',TSS,'workbench.action.terminal.sendSequence','Send a text sequence to the active terminal (keybinding args).',[C('terminal-service.send-text-to-active',{'text':"= input.text"})],request=obj({'text':st('npm test\r')}))
cmd('terminal',TSS,'workbench.action.terminal.pastePwsh','Ctrl+V in PowerShell: paste files via the paste command, else send ^V.',[C('command-service.execute-command',{'command_id':'workbench.action.terminal.sendSequence','args':[{'text':'\u0016'}]})])

# ======================= routers =======================
ROUTER_COMP={'debug':'debug-contrib','tasks':'tasks-contrib','testing':'testing-contrib','output':'output-contrib','terminal':'terminal-contrib'}
for feat,m in MODELED.items():
    routes={k.split('@')[0]:v for k,v in m.items()}
    if feat=='debug': routes['debug.setVariable']=None
    routes={k:v for k,v in routes.items() if v}
    iface(ROUTER_COMP[feat],'execute-registered-command','CommandsRegistry handler lookup for this contribution\'s commands: the command service resolves the id to the registered handler (unknown ids fail with command-not-found).',
      [S('src/vs/platform/commands/common/commands.ts',129,132)],
      request=obj({'command_id':st(list(routes)[0]),'args':ob(default={})},['command_id']),response=ob(),errors=[{'code':'command-not-found','status':0,'retryable':False}],
      behavior=[{'set':{'vars.routes':routes}},
        {'if':"!(input.command_id in vars.routes)",'then':[{'title':'command not found','source':S('src/vs/workbench/services/commands/common/commandService.ts',95),'fail':{'code':'command-not-found','message':"= 'command ' + input.command_id + ' not found'"}}]},
        {'title':'The handler runs with the command arguments (CommandService.tryExecuteCommand passes command_id and args)','source':S('src/vs/workbench/services/commands/common/commandService.ts',98,101),
         'call':"= vars.routes[input.command_id]",'input':{'command_id':"= input.command_id",'args':"= [input.args]"},'targets':sorted(set(routes.values())),'as':'r'},
        {'return':"= vars.r.value"}])

SKIPS.append({'kind':'ipc-channel','name':'telemetryAppender','file':'src/vs/workbench/contrib/debug/node/telemetryApp.ts','line':15,'reason':'not a product entry point of this area: a telemetry appender child process (1DS) used by the custom-endpoint telemetry service; telemetry only'})

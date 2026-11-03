from base import *
DB='src/vs/workbench/contrib/debug/browser/'; DC='src/vs/workbench/contrib/debug/common/'
D_SVC=DB+'debugService.ts'; D_SES=DB+'debugSession.ts'; D_RAW=DB+'rawDebugSession.ts'; D_MOD=DC+'debugModel.ts'; D_CON=DB+'debug.contribution.ts'
D_AM=DB+'debugAdapterManager.ts'; D_CM=DB+'debugConfigurationManager.ts'; D_TR=DB+'debugTaskRunner.ts'; D_ST=DC+'debugStorage.ts'; D_CMD=DB+'debugCommands.ts'

config('debug-save-before-start','debug.saveBeforeStart','string','allEditorsInActiveGroup','allEditorsInActiveGroup','Which editors to save before starting a debug session. No product.json override.',[S(D_CON,652,662),'product.json'])
config('debug-open-debug','debug.openDebug','string','openOnDebugBreak','openOnDebugBreak','When the Run and Debug view opens. No product.json override.',[S(D_CON,563,567),'product.json'])
config('debug-on-task-errors','debug.onTaskErrors','string','prompt','prompt','What to do when the preLaunchTask has errors (debugAnyway | showErrors | prompt | abort). No product.json override.',[S(D_CON,630,635),'product.json'])
config('debug-confirm-on-exit','debug.confirmOnExit','string','never','never','Confirm closing the window while debugging. No product.json override.',[S(D_CON,663,672),'product.json'])
config('debug-allow-breakpoints-everywhere','debug.allowBreakpointsEverywhere','boolean',False,False,'Allow breakpoints in any file. No product.json override.',[S(D_CON,497,501),'product.json'])
config('debug-disconnect-timeout-ms','RawDebugSession.shutdown disconnect timeout','integer',2000,2000,'Code constant: the disconnect request waits 2000 ms (200 ms after an adapter error).',[S(D_RAW,606,607)],extra={'constant':True})

SCHEMAS.append({'id':'DebugLaunchConfig','summary':'An IConfig (launch.json configuration) subset.','schema':obj({
  'type':st('node'),'request':st('launch',enum=['launch','attach','bogus']),'name':st('Launch Program'),'program':st('/work/app/src/main.ts'),
  'preLaunchTask':{'type':['string','null'],'default':None},'postDebugTask':{'type':['string','null'],'default':None},'stopOnEntry':bo(False),'noDebug':bo(False)})})

comp('debug-contrib','Debug contribution','workbench','Debug workbench contribution module: registers the debug services, views, commands, editor and workbench contributions.',[S(D_CON,75,85),S(D_CON,109,111),S(DB+'debug.service.contribution.ts',11,12)])
comp('debug-service','DebugService','debug-contrib','Starts, restarts and stops debug sessions; owns breakpoint operations and sends them to every session.',
  [CL(D_SVC,'DebugService'),S(DC+'debug.ts',1152),S(DB+'debug.service.contribution.ts',11)],
  state={'schema':obj({'initializing':bo(),'next_session_seq':it(),'has_debugged':bo()}),'initial':{'initializing':False,'next_session_seq':1,'has_debugged':False}})
comp('debug-model','DebugModel','debug-contrib','Sessions, breakpoints (source, function, data, exception), watch expressions and the focused session.',[CL(D_MOD,'DebugModel')],
  state={'schema':obj({'sessions':ob(),'breakpoints':ob(),'next_bp_seq':it(),'breakpoints_activated':bo(),'function_breakpoints':ob(),'data_breakpoints':ob(),'exception_breakpoints':ob(),'watch_expressions':arr(st()),'focused_session':{'type':['string','null']}}),
         'initial':{'sessions':{},'breakpoints':{},'next_bp_seq':1,'breakpoints_activated':True,'function_breakpoints':{},'data_breakpoints':{},'exception_breakpoints':{'uncaught':{'enabled':False}},'watch_expressions':[],'focused_session':None}})
comp('debug-storage','DebugStorage','debug-contrib','Persists breakpoints and watch expressions in workspace storage.',[CL(D_ST,'DebugStorage')],
  state={'schema':obj({'workspace_storage':ob()}),'initial':{'workspace_storage':{}}})
comp('configuration-manager','ConfigurationManager','debug-contrib','launch.json configurations, the selected configuration and debug configuration providers.',[CL(D_CM,'ConfigurationManager')],
  state={'schema':obj({'launch_configurations':ob(),'selected':{'type':['string','null']}}),'initial':{'launch_configurations':{},'selected':None}})
comp('adapter-manager','AdapterManager','debug-contrib','Registered debuggers (debuggers extension point) and breakpoint languages (breakpoints extension point). js-debug ships built in (product.json builtInExtensions).',
  [CL(D_AM,'AdapterManager'),S(DC+'debugSchemas.ts',19),S(DC+'debugSchemas.ts',136),'product.json'],
  state={'schema':obj({'debuggers':ob(),'breakpoint_languages':arr(st())}),
         'initial':{'debuggers':{'node':{'type':'node','label':'Node.js','enabled':True,'languages':['javascript','typescript']},'pwa-node':{'type':'pwa-node','label':'Node.js','enabled':True,'languages':['javascript','typescript']}},'breakpoint_languages':['javascript','typescript','javascriptreact','typescriptreact']}})
comp('debug-session','DebugSession','debug-contrib','One debug session: initialize, launch/attach, stepping, breakpoints and termination over its RawDebugSession.',[CL(D_SES,'DebugSession')])
comp('raw-debug-session','RawDebugSession','debug-contrib','DAP client: sends requests to the debug adapter, merges capabilities, dispatches adapter events and shuts the adapter down.',[CL(D_RAW,'RawDebugSession')],
  state={'schema':obj({'sessions':ob()}),'initial':{'sessions':{}}})
comp('debug-task-runner','DebugTaskRunner','debug-contrib','Runs preLaunchTask/postDebugTask and decides whether debugging continues after task errors.',[CL(D_TR,'DebugTaskRunner')])
comp('debug-lifecycle','DebugLifecycle','debug-contrib','onBeforeShutdown veto while debug sessions are active (debug.confirmOnExit).',[CL(DC+'debugLifecycle.ts','DebugLifecycle'),S(D_CON,84)])
comp('debug-visualizer-service','DebugVisualizerService','debug-contrib','Debug visualizers contributed by extensions (debugVisualizers extension point).',
  [CL(DC+'debugVisualizers.ts','DebugVisualizerService'),S(DC+'debugVisualizers.ts',19),S(DC+'debugVisualizers.ts',275),S(DB+'debug.service.contribution.ts',12)],
  state={'schema':obj({'visualizers':arr(st())}),'initial':{'visualizers':[]}})
comp('breakpoint-widget','BreakpointWidget','debug-contrib','Inline widget to edit a breakpoint condition, hit count, log message or trigger (IPrivateBreakpointWidgetService).',
  [CL(DB+'breakpointWidget.ts','BreakpointWidget'),S(DB+'breakpointWidget.ts',51)],
  state={'schema':obj({'visible':bo(),'line_number':it(),'uri':st(),'context':st(),'breakpoint_id':{'type':['string','null']}}),'initial':{'visible':False,'line_number':0,'uri':'','context':'condition','breakpoint_id':None}})
stub('debug-adapter','start-session','terminal-debug-tasks','x',parent='workbench') if False else None
comp_ids_cmd=[('debug-commands','Debug commands',D_CMD,'Commands registered in debugCommands.ts (CommandsRegistry and KeybindingsRegistry).'),
  ('debug-editor-actions','Debug editor actions',DB+'debugEditorActions.ts','Editor actions registered in debugEditorActions.ts.'),
  ('breakpoints-view','BreakpointsView',DB+'breakpointsView.ts','Breakpoints view and its actions.'),
  ('repl','Repl',DB+'repl.ts','Debug console (REPL) view and its actions.'),
  ('variables-view','VariablesView',DB+'variablesView.ts','Variables view and its actions.'),
  ('watch-expressions-view','WatchExpressionsView',DB+'watchExpressionsView.ts','Watch view and its actions.'),
  ('debug-viewlet','DebugViewPaneContainer',DB+'debugViewlet.ts','Run and Debug view container and its actions.'),
  ('call-stack-widget','CallStackWidget',DB+'callStackWidget.ts','Reusable call stack widget (used by test results).')]
for cid,nm,f,sm in comp_ids_cmd:
    comp(cid,nm,'debug-contrib',sm,[f])
# fix sources to real classes where they exist
for c in COMPS:
    if c['id']=='breakpoints-view': c['sources']=[CL(DB+'breakpointsView.ts','BreakpointsView')]
    if c['id']=='repl': c['sources']=[CL(DB+'repl.ts','Repl')]
    if c['id']=='variables-view': c['sources']=[CL(DB+'variablesView.ts','VariablesView')]
    if c['id']=='watch-expressions-view': c['sources']=[CL(DB+'watchExpressionsView.ts','WatchExpressionsView')]
    if c['id']=='debug-viewlet': c['sources']=[CL(DB+'debugViewlet.ts','DebugViewPaneContainer')]
    if c['id']=='call-stack-widget': c['sources']=[CL(DB+'callStackWidget.ts','CallStackWidget')]
    if c['id']=='debug-commands': c['sources']=[S(D_CMD,144,182),S(D_CMD,327,339)]
    if c['id']=='debug-editor-actions': c['sources']=[S(DB+'debugEditorActions.ts',634,648)]
# external debug adapter (skeleton component, owned by this area)
iface('debug-adapter','start-session','Start the debug adapter process/connection (AbstractDebugAdapter.startSession).',[M('src/vs/workbench/contrib/debug/node/debugAdapter.ts','startSession',240)],kind='stream',response=ob())
iface('debug-adapter','handle-request','A DAP request sent to the adapter; it answers with success and a body (js-debug capabilities are constant here).',[M(DC+'abstractDebugAdapter.ts','sendRequest')],kind='stream',
  request=obj({'command':st('initialize'),'arguments':ob()}),
  response=obj({'success':{'type':'boolean','const':True},'body':obj({'supportsConfigurationDoneRequest':{'type':'boolean','const':True},'supportsTerminateRequest':{'type':'boolean','const':True},
     'supportsFunctionBreakpoints':{'type':'boolean','const':True},'supportsRestartRequest':{'type':'boolean','const':False},'supportsDataBreakpoints':{'type':'boolean','const':False}})}),
  errors=[{'code':'debug-adapter-error','status':0,'retryable':False}],latency=None) if False else None
IFACES.append({'component':'debug-adapter','name':'handle-request','kind':'stream','summary':'A DAP request sent to the adapter; it answers with success and a body (the js-debug capabilities are constants here).',
  'sources':[M(DC+'abstractDebugAdapter.ts','sendRequest')],'latency_ms':{'min':2,'max':10},
  'request':obj({'command':st('initialize'),'arguments':ob()}),
  'response':obj({'success':{'type':'boolean','const':True},'body':obj({'supportsConfigurationDoneRequest':{'type':'boolean','const':True},'supportsTerminateRequest':{'type':'boolean','const':True},
     'supportsFunctionBreakpoints':{'type':'boolean','const':True},'supportsRestartRequest':{'type':'boolean','const':False},'supportsDataBreakpoints':{'type':'boolean','const':False}})}),
  'errors':[{'code':'debug-adapter-error','status':0,'retryable':False}]})
iface('debug-adapter','stop-session','Stop the debug adapter process.',[M('src/vs/workbench/contrib/debug/node/debugAdapter.ts','stopSession',340)],kind='stream',response=ob())

stub('extensions-workbench-service','open-search','remote-server','Open the Extensions view with a search.',request=obj({'search':st('@category:debuggers node')}),response=ob())
stub('markers-view','open','files-search-scm','Open the Problems view.',response=ob(),parent='workbench')

# ---------- debug model ----------
iface('debug-model','add-session','Add a session (dropping inactive sessions with the same configuration).',[M(D_MOD,'addSession')],request=obj({'session':ob()}),response=ob(),
  behavior=[{'foreach':"= state.sessions.filter(k, state.sessions[k].state == 'inactive' && state.sessions[k].name == input.session.name)",'as':'old','steps':[{'set':{'state.sessions':"= omit(state.sessions, vars.old)"}}]},
            {'set':{'state.sessions':"= merge(state.sessions, {input.session.id: input.session})"}}])
iface('debug-model','update-session','Update a session\'s state (initialized, running, stopped, inactive) and capabilities.',[M(D_MOD,'getSession',1509)],request=obj({'session_id':st('session-1'),'update':ob()}),response=ob(),
  behavior=[{'if':"!(input.session_id in state.sessions)",'then':[{'return':{}}]},{'set':{'state.sessions':"= merge(state.sessions, {input.session_id: input.update})"}}])
iface('debug-model','get-session','A session by id (undefined when unknown).',[M(D_MOD,'getSession',1509)],request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=[{'return':"= input.session_id in state.sessions ? state.sessions[input.session_id] : {'id': input.session_id, 'raw': false, 'missing': true, 'state': 'inactive', 'capabilities': {}, 'ready_for_breakpoints': false}"}])
iface('debug-model','get-sessions','Active sessions (inactive ones excluded).',[M(D_MOD,'getSessions')],response=obj({'sessions':arr()}),
  behavior=[{'return':{'sessions':"= state.sessions.filter(k, state.sessions[k].state != 'inactive').map(k, state.sessions[k])"}}])
iface('debug-model','set-focus','Focus a session/thread (view model).',[M(D_SVC,'focusStackFrame')],request=obj({'session_id':st('session-1')}),response=ob(),behavior=[{'set':{'state.focused_session':"= input.session_id"}}])
iface('debug-model','add-breakpoints','Create source breakpoints for a URI (enabled unless stated).',[M(D_MOD,'addBreakpoints')],
  request=obj({'uri':st('file:///work/app/src/main.ts'),'breakpoints':arr(obj({'line_number':it(2),'condition':{'type':['string','null'],'default':None},'enabled':bo(True)}))}),response=obj({'ids':arr(st())}),
  behavior=[{'set':{'vars.ids':"= input.breakpoints.map(b, 'bp-' + string(state.next_bp_seq + input.breakpoints.indexOf(b)))"}} if False else {'set':{'vars.ids':[]}},
    {'foreach':"= input.breakpoints",'as':'b','steps':[
       {'set':{'vars.id':"= 'bp-' + string(state.next_bp_seq)"}},
       {'set':{'state.breakpoints':"= merge(state.breakpoints, {vars.id: {'id': vars.id, 'uri': input.uri, 'line_number': vars.b.line_number, 'enabled': has(vars.b.enabled) ? vars.b.enabled : true, 'condition': has(vars.b.condition) ? vars.b.condition : null, 'verified': false}})",'state.next_bp_seq':"= state.next_bp_seq + 1",'vars.ids':"= vars.ids + [vars.id]"}}]},
    {'return':{'ids':"= vars.ids"}}])
iface('debug-model','get-breakpoints','Breakpoints filtered by uri, line and enabledOnly (enabledOnly also requires breakpoints to be activated).',[M(D_MOD,'getBreakpoints')],
  request=obj({'uri':{'type':['string','null'],'default':None},'line_number':{'type':['integer','null'],'default':None},'enabled_only':bo(False)}),response=obj({'breakpoints':arr()}),
  behavior=[{'return':{'breakpoints':"= state.breakpoints.map(k, state.breakpoints[k]).filter(b, (input.uri == null || b.uri == input.uri) && (input.line_number == null || b.line_number == input.line_number) && (!input.enabled_only || (state.breakpoints_activated && b.enabled)))"}}])
iface('debug-model','remove-breakpoints','Remove the given breakpoints (all when ids is null).',[M(D_MOD,'removeBreakpoints')],request=obj({'ids':{'type':['array','null'],'default':None}}),response=obj({'uris':arr(st())}),
  behavior=[{'set':{'vars.gone':"= state.breakpoints.filter(k, input.ids == null || k in input.ids)"}},
            {'set':{'vars.uris':"= vars.gone.map(k, state.breakpoints[k].uri)"}},
            {'foreach':"= vars.gone",'as':'g','steps':[{'set':{'state.breakpoints':"= omit(state.breakpoints, vars.g)"}}]},
            {'return':{'uris':"= vars.uris"}}])
iface('debug-model','update-breakpoints','Update condition, hit count, log message or mode of a breakpoint.',[M(D_MOD,'updateBreakpoints')],request=obj({'id':st('bp-1'),'condition':{'type':['string','null'],'default':None},'mode':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'if':"!(input.id in state.breakpoints)",'then':[{'return':{}}]},{'set':{'state.breakpoints':"= merge(state.breakpoints, {input.id: {'condition': input.condition, 'mode': input.mode}})"}}])
iface('debug-model','set-enablement','Enable/disable one breakpoint of any kind, or all of them.',[M(D_MOD,'setEnablement'),M(D_MOD,'enableOrDisableAllBreakpoints')],
  request=obj({'id':{'type':['string','null'],'default':None},'kind':st('source',enum=['source','function','exception','all']),'enabled':bo(True)}),response=ob(),
  behavior=[{'if':"input.kind == 'all'",'then':[{'set':{'state.breakpoints':"= state.breakpoints.transformMap(k, v, merge(v, {'enabled': input.enabled}))",'state.function_breakpoints':"= state.function_breakpoints.transformMap(k, v, merge(v, {'enabled': input.enabled}))"}},{'return':{}}]},
            {'if':"input.kind == 'exception'",'then':[{'set':{'state.exception_breakpoints':"= merge(state.exception_breakpoints, {input.id: {'enabled': input.enabled}})"}},{'return':{}}]},
            {'if':"input.kind == 'function'",'then':[{'set':{'state.function_breakpoints':"= merge(state.function_breakpoints, {input.id: {'enabled': input.enabled}})"}},{'return':{}}]},
            {'when':"input.id in state.breakpoints",'set':{'state.breakpoints':"= merge(state.breakpoints, {input.id: {'enabled': input.enabled}})"}}])
iface('debug-model','set-breakpoints-activated','Activate or deactivate all breakpoints.',[M(D_MOD,'setBreakpointsActivated')],request=obj({'activated':bo(True)}),response=ob(),behavior=[{'set':{'state.breakpoints_activated':"= input.activated"}}])
iface('debug-model','set-breakpoint-session-data','Record the adapter\'s verification of breakpoints for a session.',[M(D_MOD,'setBreakpointSessionData')],request=obj({'ids':arr(st()),'verified':bo(True)}),response=ob(),
  behavior=[{'set':{'state.breakpoints':"= state.breakpoints.transformMap(k, v, k in input.ids ? merge(v, {'verified': input.verified}) : v)"}}])
iface('debug-model','add-function-breakpoint','Add a function breakpoint.',[M(D_MOD,'addFunctionBreakpoint')],request=obj({'name':st('add')}),response=ob(),
  behavior=[{'set':{'state.function_breakpoints':"= merge(state.function_breakpoints, {'fbp-' + input.name: {'name': input.name, 'enabled': true}})"}}])
iface('debug-model','remove-function-breakpoints','Remove one or all function breakpoints.',[M(D_MOD,'removeFunctionBreakpoints')],request=obj({'id':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'set':{'state.function_breakpoints':"= input.id == null ? {} : omit(state.function_breakpoints, input.id)"}}])
iface('debug-model','add-data-breakpoint','Add a data breakpoint.',[M(D_MOD,'addDataBreakpoint')],request=obj({'data_id':st('x'),'access_type':st('write',enum=['write','readWrite','read'])}),response=ob(),
  behavior=[{'set':{'state.data_breakpoints':"= merge(state.data_breakpoints, {input.data_id: {'access_type': input.access_type, 'enabled': true}})"}}])
iface('debug-model','remove-data-breakpoints','Remove one or all data breakpoints.',[M(D_MOD,'removeDataBreakpoints')],request=obj({'id':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'set':{'state.data_breakpoints':"= input.id == null ? {} : omit(state.data_breakpoints, input.id)"}}])
iface('debug-model','add-watch-expression','Add a watch expression (empty name starts an inline edit).',[M(D_MOD,'addWatchExpression')],request=obj({'name':st('x',default='')}),response=ob(),
  behavior=[{'set':{'state.watch_expressions':"= state.watch_expressions + [input.name]"}}])
iface('debug-model','remove-watch-expressions','Remove one watch expression, or all.',[M(D_MOD,'removeWatchExpressions')],request=obj({'name':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'set':{'state.watch_expressions':"= input.name == null ? [] : state.watch_expressions.filter(w, w != input.name)"}}])
iface('debug-model','get-watch-expressions','Watch expressions.',[M(D_MOD,'getWatchExpressions')],response=obj({'watch_expressions':arr(st())}),behavior=[{'return':{'watch_expressions':"= state.watch_expressions"}}])

iface('debug-storage','store-breakpoints','Store breakpoints in workspace storage (debug.breakpoint), or remove the key when there are none.',[M(D_ST,'storeBreakpoints')],response=ob(),
  behavior=[{'call':'debug-model.get-breakpoints','input':{'uri':None,'line_number':None,'enabled_only':False},'as':'bps'},
            {'if':"size(vars.bps.value.breakpoints) > 0",'then':[{'set':{'state.workspace_storage':"= merge(state.workspace_storage, {'debug.breakpoint': vars.bps.value.breakpoints})"}}],
             'else':[{'set':{'state.workspace_storage':"= omit(state.workspace_storage, 'debug.breakpoint')"}}]}])
iface('debug-storage','load-breakpoints','Breakpoints restored from workspace storage on startup.',[M(D_ST,'loadBreakpoints')],response=obj({'breakpoints':arr()}),
  behavior=[{'return':{'breakpoints':"= 'debug.breakpoint' in state.workspace_storage ? state.workspace_storage['debug.breakpoint'] : []"}}])
iface('debug-storage','store-watch-expressions','Store watch expressions.',[M(D_ST,'storeWatchExpressions')],request=obj({'watch_expressions':arr(st())}),response=ob(),
  behavior=[{'set':{'state.workspace_storage':"= merge(state.workspace_storage, {'debug.watchexpressions': input.watch_expressions})"}}])

# ---------- adapter manager / configuration manager ----------
iface('adapter-manager','get-debugger','The debugger registered for a type (case-insensitive).',[M(D_AM,'getDebugger')],request=obj({'type':st('node')}),response=ob(),
  behavior=[{'return':"= input.type.lowerAscii() in state.debuggers ? state.debuggers[input.type.lowerAscii()] : {'missing': true}"}])
iface('adapter-manager','guess-debugger','No type configured: pick a debugger for the active editor\'s language (quick pick when several).',[M(D_AM,'guessDebugger')],
  request=obj({'language_id':st('typescript')}),response=obj({'type':{'type':['string','null']}}),
  behavior=[{'set':{'vars.cands':"= state.debuggers.filter(k, state.debuggers[k].enabled && input.language_id in state.debuggers[k].languages)"}},
            {'if':"size(vars.cands) == 0",'then':[{'return':{'type':None}}]},
            {'choice':'pick','default':'first','options':{'first':[{'return':{'type':"= vars.cands[0]"}}],'dismissed':[{'return':{'type':None}}]}}])
iface('adapter-manager','can-set-breakpoints-in','Breakpoints are allowed when a debugger contributes breakpoints for the language (never in jsonc/log), or everywhere by setting.',[M(D_AM,'canSetBreakpointsIn')],
  request=obj({'language_id':st('typescript')}),response=obj({'allowed':bo()}),
  behavior=[{'if':"input.language_id == '' || input.language_id == 'jsonc' || input.language_id == 'log'",'then':[{'return':{'allowed':False}}]},
            {'if':"config['debug-allow-breakpoints-everywhere']",'then':[{'return':{'allowed':True}}]},
            {'return':{'allowed':"= input.language_id in state.breakpoint_languages"}}])
iface('adapter-manager','on-debuggers-extension-point','debuggers extension point handler: register contributed debuggers.',[S(DC+'debugSchemas.ts',18,20),S(D_AM,114,150)],
  request=obj({'debuggers':arr(default=[])}),response=ob(),behavior=[{'foreach':"= input.debuggers",'as':'d','steps':[{'set':{'state.debuggers':"= merge(state.debuggers, {vars.d.type: merge(vars.d, {'enabled': true})})"}}]}])
iface('adapter-manager','on-breakpoints-extension-point','breakpoints extension point handler: languages that accept breakpoints.',[S(DC+'debugSchemas.ts',135,137),S(D_AM,152,156)],
  request=obj({'languages':arr(st(),default=[])}),response=ob(),behavior=[{'set':{'state.breakpoint_languages':"= state.breakpoint_languages + input.languages.filter(l, !(l in state.breakpoint_languages))"}}])
iface('debug-visualizer-service','on-visualizers-extension-point','debugVisualizers extension point handler.',[S(DC+'debugVisualizers.ts',275),S(DC+'debugVisualizers.ts',110,125)],
  request=obj({'visualizers':arr(st(),default=[])}),response=ob(),behavior=[{'set':{'state.visualizers':"= state.visualizers + input.visualizers"}}])
iface('configuration-manager','get-selected-configuration','The configuration selected in the Run and Debug view.',[S(D_CM,397,416)],response=obj({'name':{'type':['string','null']},'config':{'type':['object','null']}}),
  behavior=[{'return':{'name':"= state.selected",'config':"= state.selected != null && state.selected in state.launch_configurations ? state.launch_configurations[state.selected] : null"}}])
iface('configuration-manager','select-configuration','Select a launch configuration.',[M(D_CM,'selectConfiguration')],request=obj({'name':st('Launch Program')}),response=ob(),behavior=[{'set':{'state.selected':"= input.name"}}])
iface('configuration-manager','get-configuration','A named configuration from launch.json (Launch.getConfiguration).',[M(D_CM,'getConfiguration')],request=obj({'name':st('Launch Program')}),response=obj({'config':{'type':['object','null']}}),
  behavior=[{'return':{'config':"= input.name in state.launch_configurations ? state.launch_configurations[input.name] : null"}}])
iface('configuration-manager','resolve-configuration-by-providers','Run resolveDebugConfiguration of providers registered for the type (none in the base world: the config is returned as is).',[M(D_CM,'resolveConfigurationByProviders')],
  request=obj({'config':'DebugLaunchConfig'}),response=obj({'config':{'type':['object','null']}}),behavior=[{'return':{'config':"= input.config"}}])
iface('configuration-manager','open-config-file','Open (creating if needed) .vscode/launch.json in an editor.',[M(D_CM,'openConfigFile',631)],response=ob(),
  behavior=[{'call':'editor-service.open-editor','input':{'resource':'file:///work/app/.vscode/launch.json'}}])


EH="= 'eh' + self.substring(1)"
MT='src/vs/workbench/api/browser/mainThreadDebugService.ts'
DAPRESP=obj({'success':{'type':'boolean','const':True},'body':obj({'supportsConfigurationDoneRequest':{'type':'boolean','const':True},'supportsTerminateRequest':{'type':'boolean','const':True},
     'supportsFunctionBreakpoints':{'type':'boolean','const':True},'supportsRestartRequest':{'type':'boolean','const':False},'supportsDataBreakpoints':{'type':'boolean','const':False}})})
stub('ext-host-debug-service','start-da-session','exthost','ExtHostDebugServiceShape.$startDASession: start the extension-provided debug adapter in the extension host (ExtensionHostDebugAdapter.startSession).',kind='rpc',attributes={'shape':'ExtHostDebugServiceShape'},
  request=obj({'handle':it(1),'session_id':st('session-1'),'type':st('node')}),response=ob())
stub('ext-host-debug-service','send-da-message','exthost','ExtHostDebugServiceShape.$sendDAMessage: relay a DAP request to the adapter running behind the extension host; the response comes back through $acceptDAMessage (modeled as the RPC reply).',kind='rpc',attributes={'shape':'ExtHostDebugServiceShape'},
  request=obj({'handle':it(1),'command':st('initialize'),'arguments':ob()}),response=DAPRESP,errors=[{'code':'debug-adapter-error','status':0,'retryable':False}])
stub('ext-host-debug-service','stop-da-session','exthost','ExtHostDebugServiceShape.$stopDASession.',kind='rpc',attributes={'shape':'ExtHostDebugServiceShape'},request=obj({'handle':it(1)}),response=ob())
# ---------- raw session ----------
iface('raw-debug-session','start','Start the debug adapter for a session.',[M(D_RAW,'start')],request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=[{'title':'ExtensionHostDebugAdapter.startSession relays to the extension host','source':S(MT,488,490),'call':'ext-host-debug-service.start-da-session','on':EH,'input':{'handle':1,'session_id':"= input.session_id",'type':'node'}},{'set':{'state.sessions':"= merge(state.sessions, {input.session_id: {'adapter_running': true, 'in_shutdown': false, 'ready_for_breakpoints': false}})"}}])
iface('raw-debug-session','send','Send a DAP request; without an adapter it fails (or completes silently during shutdown); an unsuccessful response rejects.',[M(D_RAW,'send')],
  request=obj({'session_id':st('session-1'),'command':st('initialize'),'arguments':ob(),'timeout_ms':it(0,default=0)}),response=obj({'success':bo(),'body':ob()}),
  errors=[{'code':'no-debugger-available-found','status':0,'retryable':False},{'code':'debug-adapter-error','status':0,'retryable':False}],
  behavior=[{'if':"!(input.session_id in state.sessions) || !state.sessions[input.session_id].adapter_running",'then':[
               {'if':"input.session_id in state.sessions && state.sessions[input.session_id].in_shutdown",'then':[{'return':{'success':True,'body':{}}}]},
               {'fail':{'code':'no-debugger-available-found','message':"= 'No debugger available found. Can not send ' + input.command + '.'"}}]},
            {'title':'ExtensionHostDebugAdapter.sendMessage -> $sendDAMessage','source':S(MT,492,494),'call':'ext-host-debug-service.send-da-message','on':EH,'input':{'handle':1,'command':"= input.command",'arguments':"= input.arguments"},'timeout_ms':"= input.timeout_ms > 0 ? input.timeout_ms : 30000",'as':'r'},
            {'return':"= vars.r.value"}])
iface('raw-debug-session','on-adapter-event','Dispatch a DAP event from the adapter: initialized (ready for breakpoints), stopped, terminated.',[S(D_RAW,109,147)],
  request=obj({'session_id':st('session-1'),'event':st('initialized',enum=['initialized','stopped','terminated']),'reason':st('breakpoint',default='breakpoint')}),response=ob(),
  behavior=[{'if':"!(input.session_id in state.sessions) || !state.sessions[input.session_id].adapter_running",'then':[{'return':{}}]},
            {'if':"input.event == 'initialized'",'then':[{'set':{'state.sessions':"= merge(state.sessions, {input.session_id: {'ready_for_breakpoints': true}})"}},
                {'call':'debug-model.update-session','input':{'session_id':"= input.session_id",'update':{'ready_for_breakpoints':True}}},
                {'call':'debug-session.on-did-initialize','input':{'session_id':"= input.session_id"}},{'return':{}}]},
            {'if':"input.event == 'stopped'",'then':[{'call':'debug-session.handle-stop','input':{'session_id':"= input.session_id",'reason':"= input.reason"}},{'return':{}}]},
            {'call':'debug-session.on-did-terminate-debuggee','input':{'session_id':"= input.session_id"}}])
iface('raw-debug-session','shutdown','Send disconnect (2 s timeout; errors swallowed), then stop the adapter and report the adapter exit.',[M(D_RAW,'shutdown'),M(D_RAW,'stopAdapter')],
  request=obj({'session_id':st('session-1'),'terminate_debuggee':bo(True)}),response=ob(),
  behavior=[{'if':"!(input.session_id in state.sessions) || state.sessions[input.session_id].in_shutdown",'then':[{'return':{}}]},
            {'set':{'state.sessions':"= merge(state.sessions, {input.session_id: {'in_shutdown': true}})"}},
            {'call':'raw-debug-session.send','input':{'session_id':"= input.session_id",'command':'disconnect','arguments':{'restart':False,'terminateDebuggee':"= input.terminate_debuggee"},'timeout_ms':"= config['debug-disconnect-timeout-ms']"},'on_error':'continue'},
            {'title':'ExtensionHostDebugAdapter.stopSession -> $stopDASession','source':S(MT,496,499),'call':'ext-host-debug-service.stop-da-session','on':EH,'input':{'handle':1}},
            {'set':{'state.sessions':"= merge(state.sessions, {input.session_id: {'adapter_running': false}})"}},
            {'call':'debug-session.on-did-exit-adapter','input':{'session_id':"= input.session_id"}}])

# ---------- debug session ----------
NOADAPTER=lambda what:[{'call':'debug-model.get-session','input':{'session_id':"= input.session_id"},'as':'s'},
  {'if':"!vars.s.value.raw",'then':[{'title':'noDebugAdapter','source':S(D_SES,397),'fail':{'code':'no-debugger-available','message':"No debugger available, can not send '%s'"%what}}]}]
iface('debug-session','initialize','Create the adapter, start RawDebugSession and send initialize; capabilities are remembered. On failure the session shuts down.',[M(D_SES,'initialize')],
  request=obj({'session_id':st('session-1'),'type':st('node')}),response=ob(),errors=[{'code':'debug-adapter-error','status':0,'retryable':False}],
  behavior=[{'call':'raw-debug-session.start','input':{'session_id':"= input.session_id"}},
            {'call':'raw-debug-session.send','input':{'session_id':"= input.session_id",'command':'initialize','arguments':{'clientID':'vscode','adapterID':"= input.type",'linesStartAt1':True,'supportsRunInTerminalRequest':True},'timeout_ms':0},'as':'init',
             'on_error':[{'title':'initialize failed: shut down and rethrow','source':S(D_SES,384,389),'call':'raw-debug-session.shutdown','input':{'session_id':"= input.session_id",'terminate_debuggee':True}},{'fail':"= error"}]},
            {'call':'debug-model.update-session','input':{'session_id':"= input.session_id",'update':{'raw':True,'state':'initializing','capabilities':"= vars.init.value.body"}}}])
iface('debug-session','launch-or-attach','Send the launch or attach request; the adapter then sends "initialized" (and "stopped" when stopOnEntry).',[M(D_SES,'launchOrAttach'),M(D_RAW,'launchOrAttach')],
  request=obj({'session_id':st('session-1'),'config':'DebugLaunchConfig'}),response=ob(),errors=[{'code':'no-debugger-available','status':0,'retryable':False},{'code':'debug-adapter-error','status':0,'retryable':False}],
  behavior=NOADAPTER('launch or attach')+[
            {'call':'raw-debug-session.send','input':{'session_id':"= input.session_id",'command':"= input.config.request",'arguments':"= input.config",'timeout_ms':0},'as':'r',
             'on_error':[{'call':'raw-debug-session.shutdown','input':{'session_id':"= input.session_id",'terminate_debuggee':True}},{'fail':"= error"}]},
            {'title':'Adapter event: initialized','source':S(D_RAW,111,114),'emit':'raw-debug-session.on-adapter-event','input':{'session_id':"= input.session_id",'event':'initialized','reason':''}},
            {'when':"has(input.config.stopOnEntry) && input.config.stopOnEntry",'emit':'raw-debug-session.on-adapter-event','input':{'session_id':"= input.session_id",'event':'stopped','reason':'entry'}}])
iface('debug-session','on-did-initialize','Adapter initialized: send all breakpoints, then configurationDone (disconnect if it fails); the debuggee runs.',[S(D_SES,1071,1099)],
  request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=[{'call':'debug-service.send-all-breakpoints','input':{'session_id':"= input.session_id"},'on_error':'continue'},
            {'call':'debug-model.get-session','input':{'session_id':"= input.session_id"},'as':'s'},
            {'if':"has(vars.s.value.capabilities.supportsConfigurationDoneRequest) && vars.s.value.capabilities.supportsConfigurationDoneRequest",'then':[
               {'call':'raw-debug-session.send','input':{'session_id':"= input.session_id",'command':'configurationDone','arguments':{},'timeout_ms':0},'as':'cd',
                'on_error':[{'title':'configurationDone error: notify and disconnect','source':S(D_SES,1081,1086),'call':'raw-debug-session.shutdown','input':{'session_id':"= input.session_id",'terminate_debuggee':True}},{'return':{}}]}]},
            {'call':'debug-model.update-session','input':{'session_id':"= input.session_id",'update':{'state':'running'}}}])
iface('debug-session','handle-stop','Stopped event: focus the thread; on a breakpoint with openDebug=openOnDebugBreak open the Run and Debug view.',[M(D_SES,'handleStop')],
  request=obj({'session_id':st('session-1'),'reason':st('breakpoint')}),response=ob(),
  behavior=[{'call':'debug-model.update-session','input':{'session_id':"= input.session_id",'update':{'state':'stopped','stopped_reason':"= input.reason"}}},
            {'call':'debug-model.set-focus','input':{'session_id':"= input.session_id"}},
            {'if':"input.reason == 'breakpoint' && config['debug-open-debug'] == 'openOnDebugBreak'",'then':[{'title':'openOnDebugBreak','source':S(D_SES,1392,1394),'call':'views-service.open-view','input':{'id':'workbench.view.debug'}}]}])
iface('debug-session','on-did-terminate-debuggee','Debuggee terminated: disconnect the adapter (or restart when requested).',[S(D_SES,1123,1130)],request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=[{'call':'raw-debug-session.shutdown','input':{'session_id':"= input.session_id",'terminate_debuggee':False}}])
iface('debug-session','on-did-exit-adapter','The adapter exited: clear breakpoint session data and threads, mark the session inactive, fire onDidEndAdapter.',[M(D_SES,'onDidExitAdapter'),M(D_SES,'shutdown',1490)],
  request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=[{'call':'debug-model.update-session','input':{'session_id':"= input.session_id",'update':{'raw':False,'state':'inactive','ready_for_breakpoints':False}}},
            {'call':'debug-service.on-did-end-adapter','input':{'session_id':"= input.session_id"}}])
for nm,meth,cmd,sm,stop in [('next','next','next','Step over',True),('step-in','stepIn','stepIn','Step into',True),('step-out','stepOut','stepOut','Step out',True),
    ('step-back','stepBack','stepBack','Step back (reverse debugging)',True),('continue','continue','continue','Continue',False),('reverse-continue','reverseContinue','reverseContinue','Reverse continue',False),
    ('pause','pause','pause','Pause',True),('terminate-threads','terminateThreads','terminateThreads','Terminate a thread',False),('restart-frame','restartFrame','restartFrame','Restart a stack frame',True),
    ('goto-targets','gotoTargets','gotoTargets','Ask the adapter where execution can jump for a line',False),('goto','goto','goto','Jump to a goto target',True),('step-in-targets','stepInTargets','stepInTargets','Ask the adapter for step-in targets',False),
    ('evaluate','evaluate','evaluate','Evaluate an expression (REPL, watch, hover)',False)]:
    beh=NOADAPTER(cmd)+[{'call':'raw-debug-session.send','input':{'session_id':"= input.session_id",'command':cmd,'arguments':{'threadId':"= input.thread_id"},'timeout_ms':0},'as':'r'}]
    if stop:
        beh+=[{'call':'debug-model.update-session','input':{'session_id':"= input.session_id",'update':{'state':'running'}}},
              {'title':'The adapter reports the thread stopped again ('+cmd+')','source':S(D_RAW,124,128),'emit':'raw-debug-session.on-adapter-event','input':{'session_id':"= input.session_id",'event':'stopped','reason':'pause' if cmd=='pause' else 'step'}}]
    elif cmd in ('continue','reverseContinue'):
        beh+=[{'call':'debug-model.update-session','input':{'session_id':"= input.session_id",'update':{'state':'running'}}}]
    beh+=[{'return':"= vars.r.value.body"}]
    iface('debug-session',nm,sm+' ('+cmd+' request).',[M(D_SES,meth)],request=obj({'session_id':st('session-1'),'thread_id':it(1)}),response=ob(),
      errors=[{'code':'no-debugger-available','status':0,'retryable':False},{'code':'debug-adapter-error','status':0,'retryable':False}],behavior=beh)
iface('debug-session','send-breakpoints','Send a file\'s breakpoints with setBreakpoints once the adapter is ready; record verification.',[M(D_SES,'sendBreakpoints')],
  request=obj({'session_id':st('session-1'),'uri':st('file:///work/app/src/main.ts'),'ids':arr(st())}),response=ob(),errors=[{'code':'no-debugger-available','status':0,'retryable':False}],
  behavior=NOADAPTER('breakpoints')+[{'if':"!vars.s.value.ready_for_breakpoints",'then':[{'title':'Not ready for breakpoints yet','source':S(D_SES,493,495),'return':{}}]},
    {'call':'raw-debug-session.send','input':{'session_id':"= input.session_id",'command':'setBreakpoints','arguments':{'source':{'path':"= input.uri"}},'timeout_ms':0},'as':'r'},
    {'call':'debug-model.set-breakpoint-session-data','input':{'ids':"= input.ids",'verified':True}}])
iface('debug-session','send-function-breakpoints','Send function breakpoints (when supported).',[M(D_SES,'sendFunctionBreakpoints')],request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=NOADAPTER('function breakpoints')+[{'when':"vars.s.value.ready_for_breakpoints",'call':'raw-debug-session.send','input':{'session_id':"= input.session_id",'command':'setFunctionBreakpoints','arguments':{},'timeout_ms':0}}])
iface('debug-session','terminate','Terminate: terminate request when supported for launch, else disconnect with terminateDebuggee.',[M(D_SES,'terminate'),M(D_RAW,'terminate')],
  request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=[{'call':'debug-model.get-session','input':{'session_id':"= input.session_id"},'as':'s'},
            {'if':"!vars.s.value.raw",'then':[{'title':'Adapter already gone: act as if terminated','source':S(D_SES,427,430),'call':'debug-session.on-did-exit-adapter','input':{'session_id':"= input.session_id"}},{'return':{}}]},
            {'if':"vars.s.value.capabilities.supportsTerminateRequest && vars.s.value.request == 'launch'",'then':[
               {'call':'raw-debug-session.send','input':{'session_id':"= input.session_id",'command':'terminate','arguments':{'restart':False},'timeout_ms':0}},
               {'title':'Adapter event: terminated','source':S(D_RAW,142,144),'emit':'raw-debug-session.on-adapter-event','input':{'session_id':"= input.session_id",'event':'terminated','reason':''}},{'return':{}}]},
            {'call':'raw-debug-session.shutdown','input':{'session_id':"= input.session_id",'terminate_debuggee':True}}])
iface('debug-session','disconnect','Disconnect without terminating the debuggee (attach sessions; optionally suspend).',[M(D_SES,'disconnect')],request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=[{'call':'raw-debug-session.shutdown','input':{'session_id':"= input.session_id",'terminate_debuggee':False}}])
iface('debug-session','add-repl-expression','Evaluate a REPL input in the focused frame and append it to the session\'s REPL.',[M(D_SES,'addReplExpression')],request=obj({'session_id':st('session-1'),'expression':st('add(1, 2)')}),response=ob(),
  behavior=[{'call':'debug-session.evaluate','input':{'session_id':"= input.session_id",'thread_id':1}},
            {'call':'debug-model.update-session','input':{'session_id':"= input.session_id",'update':{'last_repl_expression':"= input.expression"}}}])
iface('debug-session','remove-repl-expressions','Clear the session\'s REPL.',[M(D_SES,'removeReplExpressions')],request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=[{'call':'debug-model.update-session','input':{'session_id':"= input.session_id",'update':{'last_repl_expression':None}}}])

# ---------- debug service ----------
iface('debug-service','start-debugging','Workspace trust, onDebug activation, save before start, resolve the configuration by name, then create the session.',[M(D_SVC,'startDebugging')],
  request=obj({'config':{'type':['object','null'],'default':None},'config_name':{'type':['string','null'],'default':None},'no_debug':bo(False),'started_by_user':bo(True),'save_before_start':bo(True),'language_id':st('typescript')}),
  response=obj({'started':bo()}),errors=[{'code':'configuration-missing-in-launch-json','status':0,'retryable':False}],
  behavior=[{'call':'workspace-trust-request-service.request-workspace-trust','input':{'message':'Debugging executes build tasks and program code from your workspace.'},'as':'trust'},
            {'choice':'trust','default':"= vars.trust.value.trusted == true ? 'trusted' : 'denied'",'options':{'trusted':[],'denied':[{'title':'Trust refused: do not debug','source':S(D_SVC,356,359),'return':{'started':False}}]}},
            {'set':{'state.initializing':True,'state.has_debugged':True}},
            {'call':'extension-service.activate-by-event','input':{'activation_event':'onDebug','activation_kind':'normal'}},
            {'if':"input.save_before_start && config['debug-save-before-start'] != 'none'",'then':[{'title':'saveAllBeforeDebugStart','source':S('src/vs/workbench/contrib/debug/common/debugUtils.ts',377,390),'call':'editor-service.save-all','input':{'reason':'explicit'}}]},
            {'set':{'vars.config':"= input.config"}},
            {'if':"vars.config == null && input.config_name != null",'then':[{'call':'configuration-manager.get-configuration','input':{'name':"= input.config_name"},'as':'named'},{'set':{'vars.config':"= vars.named.value.config"}},
               {'if':"vars.config == null",'then':[{'set':{'state.initializing':False}},{'title':"Configuration is missing in 'launch.json'",'source':S(D_SVC,436,440),
                  'fail':{'code':'configuration-missing-in-launch-json','message':"= 'Configuration ' + input.config_name + ' is missing in launch.json.'"}}]}]},
            {'call':'debug-service.create-session','input':{'config':"= vars.config",'no_debug':"= input.no_debug",'started_by_user':"= input.started_by_user",'language_id':"= input.language_id"},'as':'created'},
            {'set':{'state.initializing':False}},
            {'return':{'started':"= vars.created.value.started"}}])
iface('debug-service','create-session','Resolve the debugger and configuration, check concurrent sessions, run the preLaunchTask, validate type/request, then create the session.',[M(D_SVC,'createSession')],
  request=obj({'config':{'type':['object','null']},'no_debug':bo(False),'started_by_user':bo(True),'language_id':st('typescript')}),response=obj({'started':bo(),'session_id':st()}),
  behavior=[{'set':{'vars.config':"= input.config == null ? {} : input.config"}},
            {'if':"!has(vars.config.type)",'then':[{'call':'adapter-manager.guess-debugger','input':{'language_id':"= input.language_id"},'as':'guess'},
               {'if':"vars.guess.value.type == null",'then':[{'title':'No debugger guessed: nothing to start','source':S(D_SVC,492,500),'return':{'started':False,'session_id':''}}]},
               {'set':{'vars.config':"= merge({'request': 'launch', 'name': 'Launch ' + vars.guess.value.type}, merge(vars.config, {'type': vars.guess.value.type}))"}}]},
            {'set':{'vars.sid':"= 'session-' + string(state.next_session_seq)",'state.next_session_seq':"= state.next_session_seq + 1"}},
            {'call':'configuration-manager.resolve-configuration-by-providers','input':{'config':"= vars.config"},'as':'byp'},
            {'set':{'vars.cfg':"= merge({'preLaunchTask': null, 'postDebugTask': null, 'stopOnEntry': false, 'request': ''}, vars.byp.value.config)"}},
            {'call':'debug-model.get-sessions','as':'existing'},
            {'if':"input.started_by_user && vars.existing.value.sessions.exists(s, s.name == vars.cfg.name && s.type == vars.cfg.type && s.request == vars.cfg.request)",'then':[
               {'title':'Already running: confirm another instance','source':M(D_SVC,'confirmConcurrentSession'),'choice':'concurrent_session','default':'start_another','options':{'start_another':[],'cancel':[{'return':{'started':False,'session_id':''}}]}}]},
            {'call':'debug-task-runner.run-task-and-check-errors','input':{'task':"= vars.cfg.preLaunchTask"},'as':'task'},
            {'if':"vars.task.value.result == 'failure'",'then':[{'title':'preLaunchTask failed: do not start','source':S(D_SVC,545,548),'return':{'started':False,'session_id':''}}]},
            {'call':'adapter-manager.get-debugger','input':{'type':"= vars.cfg.type"},'as':'dbg'},
            {'if':"has(vars.dbg.value.missing) || (vars.cfg.request != 'attach' && vars.cfg.request != 'launch')",'then':[
               {'title':'Unsupported type or request: show error with "Install Extension"','source':S(D_SVC,559,580),'set':{'ctx.debug_error':"= has(vars.dbg.value.missing) ? 'debug type not supported' : 'request not supported'"}},{'return':{'started':False,'session_id':''}}]},
            {'if':"!vars.dbg.value.enabled",'then':[{'set':{'ctx.debug_error':'debugger disabled'}},{'return':{'started':False,'session_id':''}}]},
            {'call':'debug-service.do-create-session','input':{'session_id':"= vars.sid",'config':"= vars.cfg",'no_debug':"= input.no_debug"},'as':'done'},
            {'return':{'started':"= vars.done.value.started",'session_id':"= vars.sid"}}])
iface('debug-service','do-create-session','Register the session, then initialize and launch/attach it; adapter errors are shown and the start returns false.',[M(D_SVC,'doCreateSession'),M(D_SVC,'launchOrAttachToSession')],
  request=obj({'session_id':st('session-1'),'config':ob(),'no_debug':bo(False)}),response=obj({'started':bo()}),
  behavior=[{'call':'debug-model.add-session','input':{'session':{'id':"= input.session_id",'name':"= input.config.name",'type':"= input.config.type",'request':"= input.config.request",'state':'initializing','raw':False,'ready_for_breakpoints':False,'capabilities':{},'no_debug':"= input.no_debug",'post_debug_task':"= input.config.postDebugTask"}}},
            {'call':'debug-session.initialize','input':{'session_id':"= input.session_id",'type':"= input.config.type"},'as':'init','on_error':'continue'},
            {'if':"!vars.init.ok",'then':[{'title':'Initialize failed: show the error, return false','source':S(D_SVC,664,690),'set':{'ctx.debug_error':"= vars.init.error.message"}},{'return':{'started':False}}]},
            {'call':'debug-session.launch-or-attach','input':{'session_id':"= input.session_id",'config':"= input.config"},'as':'la','on_error':'continue'},
            {'if':"!vars.la.ok",'then':[{'set':{'ctx.debug_error':"= vars.la.error.message"}},{'return':{'started':False}}]},
            {'call':'debug-model.set-focus','input':{'session_id':"= input.session_id"}},
            {'return':{'started':True}}])
iface('debug-service','on-did-end-adapter','A session\'s adapter ended: run postDebugTask, end initializing state; with no sessions left, clear non-persistable data breakpoints.',[S(D_SVC,754,800)],
  request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=[{'call':'debug-model.get-session','input':{'session_id':"= input.session_id"},'as':'s'},
            {'if':"has(vars.s.value.post_debug_task) && vars.s.value.post_debug_task != null",'then':[{'title':'postDebugTask','source':S(D_SVC,770,777),'call':'debug-task-runner.run-task','input':{'task':"= vars.s.value.post_debug_task"},'on_error':'continue'}]},
            {'set':{'state.initializing':False,'ctx.debug_session_ended':"= input.session_id"}}])
iface('debug-service','stop-session','Stop a session (terminate or disconnect), or all sessions when none is given.',[M(D_SVC,'stopSession')],
  request=obj({'session_id':{'type':['string','null'],'default':None},'disconnect':bo(False)}),response=ob(),
  behavior=[{'call':'debug-model.get-sessions','as':'all'},
            {'set':{'vars.targets':"= input.session_id != null ? [input.session_id] : vars.all.value.sessions.map(s, s.id)"}},
            {'if':"size(vars.targets) == 0",'then':[{'title':'No sessions: cancel a pending start','source':S(D_SVC,966,972),'set':{'state.initializing':False}},{'return':{}}]},
            {'parallel':"= vars.targets",'as':'sid','join':{'need':'all'},'steps':[
               {'if':"input.disconnect",'then':[{'call':'debug-session.disconnect','input':{'session_id':"= vars.sid"}}],'else':[{'call':'debug-session.terminate','input':{'session_id':"= vars.sid"}}]}]}])
iface('debug-service','restart-session','Restart: save, then a DAP restart when supported, else terminate and launch again.',[M(D_SVC,'restartSession')],request=obj({'session_id':st('session-1')}),response=ob(),
  behavior=[{'call':'debug-model.get-session','input':{'session_id':"= input.session_id"},'as':'s'},
            {'if':"has(vars.s.value.capabilities.supportsRestartRequest) && vars.s.value.capabilities.supportsRestartRequest",'then':[{'call':'raw-debug-session.send','input':{'session_id':"= input.session_id",'command':'restart','arguments':{},'timeout_ms':0}},{'return':{}}]},
            {'call':'debug-session.terminate','input':{'session_id':"= input.session_id"}},
            {'call':'debug-session.initialize','input':{'session_id':"= input.session_id",'type':"= vars.s.value.type"}},
            {'call':'debug-session.launch-or-attach','input':{'session_id':"= input.session_id",'config':{'type':"= vars.s.value.type",'request':"= vars.s.value.request",'name':"= vars.s.value.name"}},'fill':True}])
iface('debug-service','add-breakpoints','Add breakpoints, store them, send them to the sessions, store again (adapter data).',[M(D_SVC,'addBreakpoints')],
  request=obj({'uri':st('file:///work/app/src/main.ts'),'breakpoints':arr(obj({'line_number':it(2)}))}),response=obj({'ids':arr(st())}),
  behavior=[{'call':'debug-model.add-breakpoints','input':{'uri':"= input.uri",'breakpoints':"= input.breakpoints"},'as':'added'},
            {'call':'debug-storage.store-breakpoints'},{'call':'debug-service.send-breakpoints','input':{'uri':"= input.uri",'session_id':None}},{'call':'debug-storage.store-breakpoints'},
            {'return':{'ids':"= vars.added.value.ids"}}])
iface('debug-service','update-breakpoints','Update breakpoint data, store, and send the file\'s breakpoints.',[M(D_SVC,'updateBreakpoints')],
  request=obj({'id':st('bp-1'),'uri':st('file:///work/app/src/main.ts'),'condition':{'type':['string','null'],'default':None},'mode':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'call':'debug-model.update-breakpoints','input':{'id':"= input.id",'condition':"= input.condition",'mode':"= input.mode"}},{'call':'debug-storage.store-breakpoints'},
            {'call':'debug-service.send-breakpoints','input':{'uri':"= input.uri",'session_id':None}}])
iface('debug-service','remove-breakpoints','Remove breakpoints (all when no id), store, and resend each affected file.',[M(D_SVC,'removeBreakpoints')],request=obj({'ids':{'type':['array','null'],'default':None}}),response=ob(),
  behavior=[{'call':'debug-model.remove-breakpoints','input':{'ids':"= input.ids"},'as':'rm'},{'call':'debug-storage.store-breakpoints'},
            {'parallel':"= vars.rm.value.uris",'as':'u','join':{'need':'all'},'steps':[{'call':'debug-service.send-breakpoints','input':{'uri':"= vars.u",'session_id':None}}]}])
iface('debug-service','enable-or-disable-breakpoints','Enable/disable one breakpoint (and resend its kind) or all breakpoints (resend everything).',[M(D_SVC,'enableOrDisableBreakpoints')],
  request=obj({'id':{'type':['string','null'],'default':None},'kind':st('source',enum=['source','function','exception','all']),'enabled':bo(True),'uri':st('file:///work/app/src/main.ts')}),response=ob(),
  behavior=[{'call':'debug-model.set-enablement','input':{'id':"= input.id",'kind':"= input.kind",'enabled':"= input.enabled"}},{'call':'debug-storage.store-breakpoints'},
            {'if':"input.kind == 'source'",'then':[{'call':'debug-service.send-breakpoints','input':{'uri':"= input.uri",'session_id':None}}]},
            {'if':"input.kind == 'all'",'then':[{'call':'debug-service.send-all-breakpoints','input':{'session_id':None}}]}])
iface('debug-service','set-breakpoints-activated','Activate/deactivate breakpoints and resend all.',[M(D_SVC,'setBreakpointsActivated')],request=obj({'activated':bo(True)}),response=ob(),
  behavior=[{'call':'debug-model.set-breakpoints-activated','input':{'activated':"= input.activated"}},{'call':'debug-service.send-all-breakpoints','input':{'session_id':None}}])
iface('debug-service','add-function-breakpoint','Add a function breakpoint; with a name it is stored and sent, without one the inline rename sends it later.',[M(D_SVC,'addFunctionBreakpoint')],request=obj({'name':st('',default='')}),response=ob(),
  behavior=[{'call':'debug-model.add-function-breakpoint','input':{'name':"= input.name"}},
            {'if':"input.name != ''",'then':[{'call':'debug-storage.store-breakpoints'},{'call':'debug-service.send-all-breakpoints','input':{'session_id':None}}]}])
iface('debug-service','add-data-breakpoint','Add a data breakpoint, store and send.',[M(D_SVC,'addDataBreakpoint')],request=obj({'data_id':st('x'),'access_type':st('write')}),response=ob(),
  behavior=[{'call':'debug-model.add-data-breakpoint','input':{'data_id':"= input.data_id",'access_type':"= input.access_type"}},{'call':'debug-storage.store-breakpoints'}])
iface('debug-service','remove-function-and-data-breakpoints','Remove function and data breakpoints (removeFunctionBreakpoints/removeDataBreakpoints).',[M(D_SVC,'removeFunctionBreakpoints'),M(D_SVC,'removeDataBreakpoints')],request=obj({'id':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'call':'debug-model.remove-function-breakpoints','input':{'id':"= input.id"}},{'call':'debug-model.remove-data-breakpoints','input':{'id':"= input.id"}},{'call':'debug-storage.store-breakpoints'}])
iface('debug-service','add-watch-expression','Add a watch expression and store the list.',[M(D_SVC,'addWatchExpression')],request=obj({'name':st('x',default='')}),response=ob(),
  behavior=[{'call':'debug-model.add-watch-expression','input':{'name':"= input.name"}},{'call':'debug-model.get-watch-expressions','as':'w'},{'call':'debug-storage.store-watch-expressions','input':{'watch_expressions':"= vars.w.value.watch_expressions"}}])
iface('debug-service','remove-watch-expressions','Remove one or all watch expressions and store the list.',[M(D_SVC,'removeWatchExpressions')],request=obj({'name':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'call':'debug-model.remove-watch-expressions','input':{'name':"= input.name"}},{'call':'debug-model.get-watch-expressions','as':'w'},{'call':'debug-storage.store-watch-expressions','input':{'watch_expressions':"= vars.w.value.watch_expressions"}}])
iface('debug-service','send-breakpoints','Send a file\'s enabled breakpoints to one or every non-noDebug session in parallel.',[M(D_SVC,'sendBreakpoints')],
  request=obj({'uri':st('file:///work/app/src/main.ts'),'session_id':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'call':'debug-model.get-breakpoints','input':{'uri':"= input.uri",'line_number':None,'enabled_only':True},'as':'bps'},
            {'call':'debug-model.get-sessions','as':'all'},
            {'parallel':"= vars.all.value.sessions.filter(s, (input.session_id == null || s.id == input.session_id) && !s.no_debug).map(s, s.id)",'as':'sid','join':{'need':'all'},'steps':[
               {'call':'debug-session.send-breakpoints','input':{'session_id':"= vars.sid",'uri':"= input.uri",'ids':"= vars.bps.value.breakpoints.map(b, b.id)"}}]}])
iface('debug-service','send-all-breakpoints','Send breakpoints of every file plus function breakpoints to one or all sessions.',[M(D_SVC,'sendAllBreakpoints')],request=obj({'session_id':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'call':'debug-model.get-breakpoints','input':{'uri':None,'line_number':None,'enabled_only':False},'as':'bps'},
            {'parallel':"= vars.bps.value.breakpoints.map(b, b.uri).filter(u, true)",'as':'u','join':{'need':'all'},'steps':[{'call':'debug-service.send-breakpoints','input':{'uri':"= vars.u",'session_id':"= input.session_id"}}]},
            {'call':'debug-model.get-sessions','as':'all'},
            {'foreach':"= vars.all.value.sessions.filter(s, (input.session_id == null || s.id == input.session_id) && has(s.capabilities.supportsFunctionBreakpoints) && s.capabilities.supportsFunctionBreakpoints).map(s, s.id)",'as':'sid','steps':[
               {'call':'debug-session.send-function-breakpoints','input':{'session_id':"= vars.sid"}}]}])
iface('debug-service','run-to','Run to cursor: add a temporary breakpoint if none, continue the focused thread; it is removed when the session stops.',[M(D_SVC,'runTo')],
  request=obj({'session_id':st('session-1'),'uri':st('file:///work/app/src/main.ts'),'line_number':it(2)}),response=ob(),
  behavior=[{'call':'debug-model.get-breakpoints','input':{'uri':"= input.uri",'line_number':"= input.line_number",'enabled_only':False},'as':'ex'},
            {'if':"size(vars.ex.value.breakpoints) == 0",'then':[{'call':'debug-service.add-breakpoints','input':{'uri':"= input.uri",'breakpoints':[{'line_number':"= input.line_number"}]},'as':'tmp'},{'set':{'ctx.run_to_temp_breakpoint':"= vars.tmp.value.ids[0]"}}]},
            {'call':'debug-session.continue','input':{'session_id':"= input.session_id",'thread_id':1}}])
iface('debug-lifecycle','should-veto-shutdown','onBeforeShutdown: veto only with active root sessions, debug.confirmOnExit=always and the user cancelling the confirmation.',[M(DC+'debugLifecycle.ts','shouldVetoShutdown'),M(DC+'debugLifecycle.ts','showWindowCloseConfirmation')],
  subscribe=['lifecycle-service.on-before-shutdown'],request=obj({'reason':st('close',enum=['close','quit','reload','load'])},['reason']),response=obj({'veto':bo()}),
  behavior=[{'call':'debug-model.get-sessions','as':'s'},
            {'if':"size(vars.s.value.sessions) == 0",'then':[{'return':{'veto':False}}]},
            {'if':"config['debug-confirm-on-exit'] == 'never'",'then':[{'return':{'veto':False}}]},
            {'choice':'confirm','default':'stop_debugging','options':{'stop_debugging':[{'return':{'veto':False}}],'cancel':[{'return':{'veto':True}}]}}])
iface('debug-task-runner','run-task','Run a task by label for debugging (getTask, then run); a missing task rejects with "Could not find the task".',[M(D_TR,'runTask')],
  request=obj({'task':{'type':['string','null'],'default':None}}),response=obj({'exit_code':{'type':['integer','null']}}),errors=[{'code':'could-not-find-the-task','status':0,'retryable':False}],
  behavior=[{'if':"input.task == null",'then':[{'return':{'exit_code':None}}]},
            {'call':'task-service.get-task','input':{'identifier':"= input.task"},'as':'t'},
            {'if':"vars.t.value.task == null",'then':[{'fail':{'code':'could-not-find-the-task','message':"= 'Could not find the task ' + input.task + '.'"}}]},
            {'call':'task-service.run','input':{'task':"= vars.t.value.task",'run_source':'system'},'as':'sum'},
            {'return':{'exit_code':"= vars.sum.value.exit_code"}}])
iface('debug-task-runner','run-task-and-check-errors','Run the preLaunchTask and decide: success on exit 0 or debugAnyway; showErrors/abort fail; prompt asks the user. A task error offers Debug Anyway / Configure Task / Cancel.',[M(D_TR,'runTaskAndCheckErrors')],
  request=obj({'task':{'type':['string','null'],'default':None}}),response=obj({'result':st(enum=['success','failure'])}),
  behavior=[{'if':"input.task == null",'then':[{'return':{'result':'success'}}]},
            {'call':'debug-task-runner.run-task','input':{'task':"= input.task"},'as':'r','on_error':[
               {'title':'Task error dialog: Debug Anyway / Configure Task / Cancel','source':S(D_TR,146,191),'choice':'task_error','default':'cancel','options':{'debug_anyway':[{'return':{'result':'success'}}],'cancel':[{'return':{'result':'failure'}}]}}]},
            {'if':"vars.r.value.exit_code == 0 || config['debug-on-task-errors'] == 'debugAnyway'",'then':[{'return':{'result':'success'}}]},
            {'if':"config['debug-on-task-errors'] == 'showErrors'",'then':[{'call':'markers-view.open'},{'return':{'result':'failure'}}]},
            {'if':"config['debug-on-task-errors'] == 'abort'",'then':[{'return':{'result':'failure'}}]},
            {'title':"preLaunchTask terminated with exit code: prompt",'source':S(D_TR,94,145),'choice':'prompt','default':'abort','options':{
               'debug_anyway':[{'return':{'result':'success'}}],'show_errors':[{'call':'markers-view.open'},{'return':{'result':'failure'}}],'abort':[{'return':{'result':'failure'}}]}}])
iface('breakpoint-widget','close','Close the widget; on accept, update the existing breakpoint or add a new one with the condition.',[M(DB+'breakpointWidget.ts','close',480)],
  request=obj({'success':bo(True),'condition':st('a > 1')}),response=ob(),
  behavior=[{'if':"input.success && state.visible",'then':[
               {'if':"state.breakpoint_id != null",'then':[{'call':'debug-service.update-breakpoints','input':{'id':"= state.breakpoint_id",'uri':"= state.uri",'condition':"= input.condition",'mode':None}}],
                'else':[{'call':'debug-service.add-breakpoints','input':{'uri':"= state.uri",'breakpoints':[{'line_number':"= state.line_number",'condition':"= input.condition"}]}}]}]},
            {'set':{'state.visible':False}}])
iface('breakpoint-widget','show','Show the breakpoint widget at a line for a context (condition, log message, trigger) and an optional existing breakpoint.',[M(DB+'breakpointEditorContribution.ts','showBreakpointWidget')],
  request=obj({'uri':st('file:///work/app/src/main.ts'),'line_number':it(2),'context':st('condition'),'breakpoint_id':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'set':{'state.visible':True,'state.uri':"= input.uri",'state.line_number':"= input.line_number",'state.context':"= input.context",'state.breakpoint_id':"= input.breakpoint_id"}}])

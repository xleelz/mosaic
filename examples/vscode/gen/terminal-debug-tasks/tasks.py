from base import *
TK='src/vs/workbench/contrib/tasks/'; AT=TK+'browser/abstractTaskService.ts'; TTS=TK+'browser/terminalTaskSystem.ts'; TCON=TK+'browser/task.contribution.ts'; RAT=TK+'browser/runAutomaticTasks.ts'
config('task-allow-automatic-tasks','task.allowAutomaticTasks','string','off','off','Run folderOpen tasks automatically in trusted workspaces; "off" only blocks when the user set it explicitly, otherwise the user is prompted. No product.json override.',[S(TCON,537,548),'product.json'])
config('task-save-before-run','task.saveBeforeRun','string','always','always','Save dirty editors before running a task (always | never | prompt). No product.json override.',[S(TCON,554,567),'product.json'])
config('task-auto-run-wait-ms','RunAutomaticTasks extra wait','integer',10000,10000,'Code constant: with no automatic tasks found yet, wait up to 10 s for the task configuration to change.',[S(RAT,71,77)],extra={'constant':True})
SCHEMAS.append({'id':'TasksTask','summary':'A configured task (tasks.json) subset.','schema':obj({'label':st('build'),'type':st('shell'),'command':st('npm run build'),'group':st('build',default='none'),
  'is_background':bo(False),'instance_limit':it(1,default=1),'run_on':st('default',default='default'),'problem_matchers':arr(st(),default=[])})})
comp('tasks-contrib','Tasks contribution','workbench','Tasks workbench contribution module: task service, status bar, automatic tasks, extension points and commands.',[S(TCON,49,51),S(TCON,163),S(TCON,383),S(TCON,462)])
comp('task-service','TaskService','tasks-contrib','ITaskService (electron TaskService extending AbstractTaskService): resolves tasks, gates on workspace trust, saves before run, runs them on the task system and registers the task commands.',
  [CL(TK+'electron-browser/taskService.ts','TaskService'),CL(AT,'AbstractTaskService'),S(TK+'common/taskService.ts',28),S(TK+'electron-browser/taskService.ts',239)],
  state={'schema':obj({'workspace_tasks':ob(),'recently_used':arr(st()),'tasks_reconnected':bo()}),'initial':{'workspace_tasks':{},'recently_used':[],'tasks_reconnected':True}})
comp('terminal-task-system','TerminalTaskSystem','tasks-contrib','Runs tasks in terminals; tracks active tasks and their instance limits.',[CL(TTS,'TerminalTaskSystem')],
  state={'schema':obj({'active_tasks':ob()}),'initial':{'active_tasks':{}}})
comp('task-definition-registry','TaskDefinitionRegistryImpl','tasks-contrib','Task types contributed through the taskDefinitions extension point.',[CL(TK+'common/taskDefinitionRegistry.ts','TaskDefinitionRegistryImpl'),S(TK+'common/taskDefinitionRegistry.ts',85)],
  state={'schema':obj({'definitions':arr(st())}),'initial':{'definitions':[]}})
comp('problem-matcher-registry','ProblemMatcherRegistryImpl','tasks-contrib','Problem matchers and patterns (problemMatchers/problemPatterns extension points); tasks wait for it to be ready.',
  [CL(TK+'common/problemMatcher.ts','ProblemMatcherRegistryImpl'),CL(TK+'common/problemMatcher.ts','ProblemPatternRegistryImpl'),S(TK+'common/problemMatcher.ts',1430),S(TK+'common/problemMatcher.ts',1863)],
  state={'schema':obj({'matchers':arr(st()),'patterns':arr(st())}),'initial':{'matchers':['$tsc','$eslint-stylish'],'patterns':[]}})
comp('run-automatic-tasks','RunAutomaticTasks','tasks-contrib','Runs runOn=folderOpen tasks when the folder opens (trusted only), with a one-time permission prompt.',[CL(RAT,'RunAutomaticTasks'),S(TCON,49)],
  state={'schema':obj({'has_run_tasks':bo(),'has_prompted':bo()}),'initial':{'has_run_tasks':False,'has_prompted':False}})
comp('task-status-bar-contributions','TaskStatusBarContributions','tasks-contrib','Status bar entry with the number of running tasks.',[CL(TCON,'TaskStatusBarContributions'),S(TCON,163)])
comp('user-tasks-global-action-contribution','UserTasksGlobalActionContribution','tasks-contrib','Adds "Tasks: Open User Tasks" to the global manage menu.',[CL(TCON,'UserTasksGlobalActionContribution'),S(TCON,383)])
comp('task-registry-contribution','TaskRegistryContribution','tasks-contrib','Waits for the task definition and problem matcher registries and sets the task context keys.',[CL(TCON,'TaskRegistryContribution'),S(TCON,462)])

TRUST=lambda: [{'call':'workspace-trust-management-service.is-workspace-trusted','as':'trusted'},
  {'title':'_trust(): untrusted workspaces must be trusted first (modal request)','source':M(AT,'_trust'),'choice':'trust','default':"= vars.trusted.value.trusted == true ? 'trusted' : 'denied'",'options':{
     'trusted':[{'return':{'trusted':True}}],
     'granted':[{'call':'workspace-trust-request-service.request-workspace-trust','input':{'message':'Listing and running tasks requires that some of the files in this workspace be executed as code.'}},{'return':{'trusted':True}}],
     'denied':[{'call':'workspace-trust-request-service.request-workspace-trust','input':{'message':'Listing and running tasks requires that some of the files in this workspace be executed as code.'}},{'return':{'trusted':False}}]}}]
iface('task-service','trust','Task execution requires a trusted workspace; otherwise ask for trust.',[M(AT,'_trust')],response=obj({'trusted':bo()}),behavior=TRUST())
iface('task-service','get-task','Resolve a task by label/identifier among the workspace tasks (trust required).',[M(AT,'getTask')],request=obj({'identifier':st('build')}),response=obj({'task':{'type':['object','null']}}),
  behavior=[{'call':'task-service.trust','as':'t'},{'if':"!vars.t.value.trusted",'then':[{'return':{'task':None}}]},
            {'return':{'task':"= input.identifier in state.workspace_tasks ? state.workspace_tasks[input.identifier] : null"}}])
iface('task-service','get-workspace-tasks','The tasks configured in the workspace (tasks.json).',[M(AT,'getWorkspaceTasks')],response=obj({'tasks':arr()}),
  behavior=[{'return':{'tasks':"= state.workspace_tasks.map(k, state.workspace_tasks[k])"}}])
iface('task-service','run','Run a task: trust, then execute; a missing task is TaskErrors.TaskNotFound.',[M(AT,'run',1440)],
  request=obj({'task':{'type':['object','null'],'default':None},'run_source':st('user',enum=['user','system','folderOpen','reconnect'])}),response=obj({'exit_code':{'type':['integer','null']},'kind':st()}),
  errors=[{'code':'task-not-found','status':0,'retryable':False},{'code':'running-task','status':0,'retryable':False}],
  behavior=[{'call':'task-service.trust','as':'t'},{'if':"!vars.t.value.trusted",'then':[{'return':{'exit_code':None,'kind':'untrusted'}}]},
            {'if':"input.task == null",'then':[{'fail':{'code':'task-not-found','message':'Task to execute is undefined'}}]},
            {'call':'task-service.execute-task','input':{'task':"= input.task",'run_source':"= input.run_source"},'as':'r'},{'return':"= vars.r.value"}])
iface('task-service','execute-task','Save before run (task.saveBeforeRun), wait for problem matchers, run on the task system; an active instance follows the instance policy.',[M(AT,'_executeTask'),M(AT,'_saveBeforeRun'),M(AT,'_handleExecuteResult')],
  request=obj({'task':ob(),'run_source':st('user')}),response=obj({'exit_code':{'type':['integer','null']},'kind':st()}),
  behavior=[{'if':"config['task-save-before-run'] == 'always'",'then':[{'call':'editor-service.save-all','input':{'reason':'explicit'}}]},
            {'if':"config['task-save-before-run'] == 'prompt'",'then':[{'choice':'save_prompt','default':'save','options':{'save':[{'call':'editor-service.save-all','input':{'reason':'explicit'}}],'dont_save':[]}}]},
            {'call':'problem-matcher-registry.on-ready'},
            {'call':'terminal-task-system.run','input':{'task':"= input.task"},'as':'r'},
            {'if':"vars.r.value.kind == 'active'",'then':[
               {'if':"input.run_source == 'folderOpen' || input.run_source == 'reconnect'",'then':[{'return':{'exit_code':None,'kind':'active'}}]},
               {'title':'Instance limit reached: instance policy (default prompt: pick an instance to terminate)','source':S(AT,2124,2150),'set':{'ctx.task_instance_policy_prompt':True}},
               {'return':{'exit_code':None,'kind':'active'}}]},
            {'when':"input.run_source == 'user'",'set':{'state.recently_used':"= [input.task.label] + state.recently_used.filter(l, l != input.task.label)"}},
            {'return':"= vars.r.value"}])
iface('task-service','run-task-command','Tasks: Run Task with an optional label; an exact label match runs (attaching problem matchers), otherwise the quick pick opens.',[M(AT,'_runTaskCommand')],
  request=obj({'filter':st('build',default='')}),response=obj({'ran':bo()}),
  behavior=[{'if':"!state.tasks_reconnected",'then':[{'return':{'ran':False}}]},
            {'if':"input.filter != '' && input.filter in state.workspace_tasks",'then':[{'call':'task-service.run','input':{'task':"= state.workspace_tasks[input.filter]",'run_source':'user'}},{'return':{'ran':True}}]},
            {'title':'No exact match: show the task quick pick','source':M(AT,'_doRunTaskCommand'),'choice':'quick_pick','default':'dismissed','options':{
               'dismissed':[{'return':{'ran':False}}],
               'first':[{'if':"size(state.workspace_tasks) == 0",'then':[{'return':{'ran':False}}]},{'call':'task-service.run','input':{'task':"= state.workspace_tasks[state.workspace_tasks.map(k, k)[0]]",'run_source':'user'}},{'return':{'ran':True}}]}}])
iface('task-service','run-group-command','Run the default build or test task; none defined raises NoBuildTask/NoTestTask (shown with "Configure").',[M(AT,'_build'),M(AT,'_runTest')],
  request=obj({'group':st('build',enum=['build','test'])}),response=obj({'exit_code':{'type':['integer','null']}}),
  errors=[{'code':'no-build-task','status':0,'retryable':False},{'code':'no-test-task','status':0,'retryable':False}],
  behavior=[{'set':{'vars.found':"= state.workspace_tasks.filter(k, state.workspace_tasks[k].group == input.group)"}},
            {'if':"size(vars.found) == 0",'then':[{'fail':{'code':"= input.group == 'build' ? 'no-build-task' : 'no-test-task'",'message':"= 'No ' + input.group + ' task defined.'"}}]},
            {'call':'task-service.run','input':{'task':"= state.workspace_tasks[vars.found[0]]",'run_source':'user'},'as':'r'},{'return':{'exit_code':"= vars.r.value.exit_code"}}])
iface('task-service','terminate','Terminate a running task (trust required; no task system is a no-op success).',[M(AT,'terminate')],request=obj({'label':st('build')}),response=obj({'success':bo()}),
  behavior=[{'call':'task-service.trust','as':'t'},{'if':"!vars.t.value.trusted",'then':[{'return':{'success':True}}]},
            {'call':'terminal-task-system.terminate','input':{'label':"= input.label"},'as':'r'},{'return':"= vars.r.value"}])
iface('task-service','configure-action','Open tasks.json for configuring tasks.',[M(AT,'configureAction')],response=ob(),behavior=[{'call':'editor-service.open-editor','input':{'resource':'file:///work/app/.vscode/tasks.json'}}])

iface('terminal-task-system','run','Run a task unless its instance limit is reached (then report the active instance).',[M(TTS,'run')],request=obj({'task':'TasksTask'}),response=obj({'exit_code':{'type':['integer','null']},'kind':st()}),
  behavior=[{'set':{'vars.instances':"= state.active_tasks.filter(k, state.active_tasks[k].label == input.task.label)"}},
            {'if':"size(vars.instances) >= (has(input.task.instance_limit) ? input.task.instance_limit : 1)",'then':[{'title':'Instance limit reached: TaskExecuteKind.Active','source':S(TTS,270,274),'return':{'exit_code':None,'kind':'active'}}]},
            {'set':{'state.active_tasks':"= merge(state.active_tasks, {input.task.label: {'label': input.task.label, 'terminal': null, 'is_background': has(input.task.is_background) && input.task.is_background}})"}},
            {'call':'terminal-task-system.execute-command','input':{'task':"= input.task"},'as':'r'},{'return':"= vars.r.value"}])
iface('terminal-task-system','execute-command','Create the task terminal and wait for its process to exit (background tasks stay active).',[M(TTS,'_executeCommand'),M(TTS,'_createTerminal')],
  request=obj({'task':'TasksTask'}),response=obj({'exit_code':{'type':['integer','null']},'kind':st()}),
  behavior=[{'call':'terminal-service.create-terminal','input':{'executable':'/bin/bash','cwd':'file:///work/app','is_feature_terminal':True,'task_key':"= input.task.label",
               'reconnection_properties':"= size(has(input.task.problem_matchers) ? input.task.problem_matchers : []) > 0 ? dyn({'owner': 'Task'}) : dyn(null)"},'fill':True,'as':'term'},
            {'set':{'state.active_tasks':"= merge(state.active_tasks, {input.task.label: {'terminal': vars.term.value.persistent_process_id}})"}},
            {'if':"vars.term.value.launch_error != null",'then':[{'set':{'state.active_tasks':"= omit(state.active_tasks, input.task.label)"}},{'return':{'exit_code':1,'kind':'started'}}]},
            {'if':"has(input.task.is_background) && input.task.is_background",'then':[{'return':{'exit_code':None,'kind':'started'}}]},
            {'title':'terminal.onExit: the task process ended','source':S(TTS,1090,1152),'choice':'process_exit','default':'zero','options':{
               'zero':[{'set':{'state.active_tasks':"= omit(state.active_tasks, input.task.label)"}},{'return':{'exit_code':0,'kind':'started'}}],
               'nonzero':[{'set':{'state.active_tasks':"= omit(state.active_tasks, input.task.label)"}},{'return':{'exit_code':1,'kind':'started'}}]}}])
iface('terminal-task-system','terminate','Terminate an active task by disposing its terminal; unknown tasks report success=false.',[M(TTS,'terminate')],request=obj({'label':st('build')}),response=obj({'success':bo()}),
  behavior=[{'if':"!(input.label in state.active_tasks)",'then':[{'return':{'success':False}}]},
            {'when':"state.active_tasks[input.label].terminal != null",'call':'local-pty.shutdown','input':{'id':"= state.active_tasks[input.label].terminal",'immediate':False}},
            {'set':{'state.active_tasks':"= omit(state.active_tasks, input.label)"}},{'return':{'success':True}}])
iface('terminal-task-system','get-active-tasks','Active tasks.',[M(TTS,'getActiveTasks')],response=obj({'labels':arr(st())}),behavior=[{'return':{'labels':"= state.active_tasks.map(k, k)"}}])
iface('terminal-task-system','rerun','Rerun the last task (or the task in a given terminal).',[M(TTS,'rerun')],request=obj({'label':st('build')}),response=obj({'exit_code':{'type':['integer','null']}}),
  behavior=[{'call':'task-service.run','input':{'task':{'label':"= input.label",'type':'shell','command':'','group':'none','is_background':False,'instance_limit':1,'run_on':'default','problem_matchers':[]},'run_source':'user'},'as':'r'},{'return':{'exit_code':"= vars.r.value.exit_code"}}])
iface('problem-matcher-registry','on-ready','Resolves once problem matchers from extensions are read.',[M(TK+'common/problemMatcher.ts','onReady',1900)],response=ob(),behavior=[{'set':{'ctx.problem_matchers_ready':True}}])
iface('problem-matcher-registry','on-problem-matchers-extension-point','problemMatchers extension point handler.',[S(TK+'common/problemMatcher.ts',1863),S(TK+'common/problemMatcher.ts',1892,1910)],request=obj({'matchers':arr(st(),default=[])}),response=ob(),
  behavior=[{'set':{'state.matchers':"= state.matchers + input.matchers"}}])
iface('problem-matcher-registry','on-problem-patterns-extension-point','problemPatterns extension point handler.',[S(TK+'common/problemMatcher.ts',1430),S(TK+'common/problemMatcher.ts',1459,1470)],request=obj({'patterns':arr(st(),default=[])}),response=ob(),
  behavior=[{'set':{'state.patterns':"= state.patterns + input.patterns"}}])
iface('task-definition-registry','on-task-definitions-extension-point','taskDefinitions extension point handler.',[S(TK+'common/taskDefinitionRegistry.ts',85),S(TK+'common/taskDefinitionRegistry.ts',121,135)],request=obj({'types':arr(st(),default=[])}),response=ob(),
  behavior=[{'set':{'state.definitions':"= state.definitions + input.types"}}])
iface('run-automatic-tasks','try-run-tasks','On folder open: if trusted and not explicitly turned off, find runOn=folderOpen tasks; run them when allowed, else prompt once.',[M(RAT,'_tryRunTasks'),M(RAT,'_runWithPermission')],
  request=obj({'user_set_off':bo(False)}),response=obj({'ran':it()}),
  behavior=[{'call':'workspace-trust-management-service.is-workspace-trusted','as':'tr'},
            {'choice':'trust','default':"= vars.tr.value.trusted == true ? 'trusted' : 'untrusted'",'options':{'trusted':[],'untrusted':[{'return':{'ran':0}}]}},
            {'if':"state.has_run_tasks || (config['task-allow-automatic-tasks'] == 'off' && input.user_set_off)",'then':[{'return':{'ran':0}}]},
            {'set':{'state.has_run_tasks':True}},
            {'call':'task-service.get-workspace-tasks','as':'ws'},
            {'set':{'vars.auto':"= vars.ws.value.tasks.filter(t, has(t.run_on) && t.run_on == 'folderOpen')"}},
            {'if':"size(vars.auto) == 0",'then':[{'title':'No automatic tasks: wait up to 10 s for the task config, then give up','source':S(RAT,70,82),'wait':"= config['task-auto-run-wait-ms']"},{'return':{'ran':0}}]},
            {'if':"config['task-allow-automatic-tasks'] != 'on'",'then':[
               {'if':"state.has_prompted",'then':[{'return':{'ran':0}}]},
               {'set':{'state.has_prompted':True}},
               {'title':'Prompt: allow automatic tasks in all trusted workspaces?','source':M(RAT,'_showPrompt'),'choice':'allow','default':'disallow','options':{'allow':[],'disallow':[{'return':{'ran':0}}]}}]},
            {'foreach':"= vars.auto",'as':'t','steps':[{'call':'task-service.run','input':{'task':"= vars.t",'run_source':'folderOpen'}}]},
            {'return':{'ran':"= size(vars.auto)"}}])

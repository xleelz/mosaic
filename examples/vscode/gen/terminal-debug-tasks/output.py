from base import *
OB='src/vs/workbench/contrib/output/browser/'; OS=OB+'outputServices.ts'; OCON=OB+'output.contribution.ts'; OCM='src/vs/workbench/contrib/output/common/outputChannelModel.ts'
comp('output-contrib','Output contribution','workbench','Output workbench contribution module: OutputService, the Output view, and OutputContribution (which registers the output actions).',[S(OCON,52),S(OCON,835)])
comp('output-service','OutputService','output-contrib','Output channels of the window, the active channel (remembered in workspace storage), log levels and view filters.',
  [CL(OS,'OutputService'),S('src/vs/workbench/services/output/common/output.ts',1) if False else S(OCON,52)],
  state={'schema':obj({'channels':ob(),'active_channel':{'type':['string','null']},'stored_active_channel':st(),'filters':ob(),'log_levels':ob()}),
         'initial':{'channels':{},'active_channel':None,'stored_active_channel':'','filters':{'trace':True,'debug':True,'info':True,'warning':True,'error':True,'categories':''},'log_levels':{}}})
comp('output-channel','OutputChannel','output-contrib','Output channel models (delegated, file-backed, multi-file); content per channel.',[CL(OS,'OutputChannel'),CL(OCM,'DelegatedOutputChannelModel')],
  state={'schema':obj({'contents':ob()}),'initial':{'contents':{}}})
comp('output-contribution','OutputContribution','output-contrib','Workbench contribution that registers the output actions and the per-channel "show" commands.',[CL(OCON,'OutputContribution'),S(OCON,835)])
comp('output-view-pane','OutputViewPane','output-contrib','The Output view (filters, category toggles).',[CL(OB+'outputView.ts','OutputViewPane')])
comp('output-link-computer-worker','outputLinkComputerMain','output-contrib','Web worker that computes links in output text.',[S('src/vs/workbench/contrib/output/common/outputLinkComputerMain.ts',9),CL('src/vs/workbench/contrib/output/common/outputLinkComputer.ts','OutputLinkComputer')],layer='worker')
stub('logger-service','set-log-level','platform-core','Set the log level of a logger resource.',request=obj({'resource':st(),'log_level':st('debug')}),response=ob())
stub('file-service','write-file','platform-core','Write a file.',request=obj({'resource':st('file:///work/app/output.log'),'content':st()}),response=ob())

iface('output-service','on-did-register-channel','A channel was registered: create its model; it becomes active if none is or it was the stored active channel.',[M(OS,'onDidRegisterChannel'),M(OS,'instantiateChannel')],
  request=obj({'id':st('tasks'),'label':st('Tasks'),'log':bo(False),'user':bo(False)}),response=ob(),
  behavior=[{'set':{'state.channels':"= merge(state.channels, {input.id: {'label': input.label, 'log': input.log, 'user': input.user}})"}},
            {'call':'output-channel.create','input':{'channel_id':"= input.id"}},
            {'if':"state.active_channel == null || state.stored_active_channel == input.id",'then':[{'call':'output-service.set-active-channel','input':{'channel_id':"= input.id"}}]}])
iface('output-service','set-active-channel','Set the active channel and remember it in workspace storage.',[M(OS,'setActiveChannel')],request=obj({'channel_id':{'type':['string','null']}}),response=ob(),
  behavior=[{'set':{'state.active_channel':"= input.channel_id",'state.stored_active_channel':"= input.channel_id == null ? '' : input.channel_id"}}])
iface('output-service','show-channel','Show a channel in the Output view (an unknown id leaves no active channel).',[M(OS,'showChannel')],request=obj({'id':st('tasks'),'preserve_focus':bo(True)}),response=obj({'active':{'type':['string','null']}}),
  behavior=[{'set':{'vars.cid':"= input.id in state.channels ? input.id : null"}},
            {'if':"state.active_channel != vars.cid",'then':[{'call':'output-service.set-active-channel','input':{'channel_id':"= vars.cid"}},{'publish':'output-service.on-active-output-channel','delivery':'sync','input':{'id':"= input.id"}}]},
            {'call':'views-service.open-view','input':{'id':'workbench.panel.output'}},
            {'return':{'active':"= state.active_channel"}}])
iface('output-service','on-active-output-channel','onActiveOutputChannel event.',[S(OS,312,313)],kind='event',request=obj({'id':st()}),response=ob())
iface('output-service','get-active-channel','The active output channel.',[M(OS,'getActiveChannel')],response=obj({'id':{'type':['string','null']}}),behavior=[{'return':{'id':"= state.active_channel"}}])
iface('output-service','set-log-level','Set a log channel\'s level when it can be set (log channels only).',[M(OS,'setLogLevel'),M(OS,'canSetLogLevel')],request=obj({'channel_id':st('tasks'),'log_level':st('debug')}),response=obj({'set':bo()}),
  behavior=[{'if':"!(input.channel_id in state.channels) || !state.channels[input.channel_id].log",'then':[{'return':{'set':False}}]},
            {'call':'logger-service.set-log-level','input':{'resource':"= 'output:' + input.channel_id",'log_level':"= input.log_level"}},
            {'set':{'state.log_levels':"= merge(state.log_levels, {input.channel_id: input.log_level})"}},{'return':{'set':True}}])
iface('output-service','register-compound-log-channel','Register a compound channel combining several log channels and return its id.',[M(OS,'registerCompoundLogChannel')],request=obj({'ids':arr(st('tasks'))}),response=obj({'id':st()}),
  behavior=[{'set':{'vars.id':"= 'compound:' + input.ids.join(',')"}},
            {'call':'output-service.on-did-register-channel','input':{'id':"= vars.id",'label':"= input.ids.join(', ')",'log':True,'user':True}},{'return':{'id':"= vars.id"}}])
iface('output-service','remove-channel','Remove a channel (onDidRemoveChannel); if it was active, show the first remaining one.',[M(OS,'onDidRemoveChannel')],request=obj({'id':st('tasks')}),response=ob(),
  behavior=[{'set':{'state.channels':"= omit(state.channels, input.id)"}},
            {'if':"state.active_channel == input.id",'then':[{'call':'output-service.set-active-channel','input':{'channel_id':"= size(state.channels) > 0 ? state.channels.map(k, k)[0] : null"}}]}])
iface('output-service','save-output-as','Save channel content to a file chosen in the save dialog.',[M(OS,'saveOutputAs')],request=obj({'channel_id':st('tasks'),'path':st('file:///work/app/output.log')}),response=ob(),
  behavior=[{'call':'output-channel.get-content','input':{'channel_id':"= input.channel_id"},'as':'c'},{'call':'file-service.write-file','input':{'resource':"= input.path",'content':"= vars.c.value.content"}}])
iface('output-service','toggle-filter','Toggle a log level filter or a category filter of the Output view.',[S(OS,287,295)],request=obj({'filter':st('debug')}),response=ob(),
  behavior=[{'if':"input.filter in state.filters",'then':[{'set':{'state.filters':"= merge(state.filters, {input.filter: !state.filters[input.filter]})"}},{'return':{}}]},
            {'set':{'state.filters':"= merge(state.filters, {'categories': state.filters.categories.contains(',' + input.filter + ',') ? state.filters.categories.replace(',' + input.filter + ',', '') : state.filters.categories + ',' + input.filter + ','})"}}])
iface('output-channel','create','Create a channel model (empty content).',[M(OS,'createOutputChannelModel')],request=obj({'channel_id':st('tasks')}),response=ob(),
  behavior=[{'set':{'state.contents':"= merge(state.contents, {input.channel_id: ''})"}}])
iface('output-channel','append','Append output to a channel (MainThreadOutputService and internal writers).',[M(OS,'append')],request=obj({'channel_id':st('tasks'),'output':st('> build\n')}),response=ob(),
  errors=[{'code':'channel-not-registered','status':0,'retryable':False}],
  behavior=[{'if':"!(input.channel_id in state.contents)",'then':[{'title':'Channel is not registered yet','source':S(OS,589,592),'fail':{'code':'channel-not-registered','message':"= 'Channel ' + input.channel_id + ' is not registered yet'"}}]},
            {'set':{'state.contents':"= merge(state.contents, {input.channel_id: state.contents[input.channel_id] + input.output})"}}])
iface('output-channel','clear','Clear a channel.',[M(OS,'clear')],request=obj({'channel_id':st('tasks')}),response=ob(),
  behavior=[{'when':"input.channel_id in state.contents",'set':{'state.contents':"= merge(state.contents, {input.channel_id: ''})"}}])
iface('output-channel','get-content','Load a channel\'s text model (provideTextContent).',[M(OS,'provideTextContent')],request=obj({'channel_id':st('tasks')}),response=obj({'content':{'type':['string','null']}}),
  behavior=[{'return':{'content':"= input.channel_id in state.contents ? state.contents[input.channel_id] : null"}}])
iface('output-link-computer-worker','compute-links','Worker main: compute file links in output lines.',[S('src/vs/workbench/contrib/output/common/outputLinkComputerMain.ts',9),M('src/vs/workbench/contrib/output/common/outputLinkComputer.ts','$computeLinks')],
  request=obj({'text':st('src/main.ts(2,5): error')}),response=obj({'links':arr(st())}),
  behavior=[{'title':'bootstrapWebWorker(create): the worker computes links per line','source':S('src/vs/workbench/contrib/output/common/outputLinkComputerMain.ts',9),'return':{'links':"= input.text.contains('.ts') ? [input.text.split('(')[0]] : []"}}])
iface('output-service','update-active-channel-context','Constructor listener: onActiveOutputChannel sets the activeOutputChannel context key.',[S(OS,344)],subscribe=['output-service.on-active-output-channel'],request=obj({'id':st()}),response=ob(),
  behavior=[{'set':{'ctx.active_output_channel_context':"= input.id"}}])

import json, re
inv={(e['name'],e['file'],e['line']):e for e in json.load(open('/home/lbethay/workplace/mosaic/examples/vscode/inventory.json'))['entries'] if e['kind']=='vscode-command'}
W='src/vs/workbench/contrib/'
def cslug(cid): return re.sub(r'-+','-',('cmd-'+re.sub(r'[^a-z0-9]','-',cid.lower()))).strip('-')[:64]
def st(i, inp=None, title=None, src=None, **kw):
    d={}
    if title: d['title']=title
    if src: d['source']=src
    d['call']=i; d['input']=inp or {}
    if 'as_' in kw: kw['as']=kw.pop('as_')
    d.update(kw); return d
TV=W+'remote/browser/tunnelView.ts'
PORT={'type':'object','properties':{'value':{'type':'string'},'remote_host':{'type':'string','default':'localhost'},'remote_port':{'type':'integer','default':3000},'forwarded':{'type':'array','items':{'type':'string'},'default':[]}}}
def forward_beh(handler_src):
    return [
     {'if':'!has(input.value) || input.value == ""','then':[{'title':'Input box dismissed: nothing is forwarded','source':TV+':1173-1176','return':{}}]},
     {'title':'Port number or address (3000 or host:2000)','source':TV+':1119-1131','set':{'vars.port':"= int(input.value.contains(':') ? input.value.split(':')[1] : input.value)",'vars.host':"= input.value.contains(':') ? input.value.split(':')[0] : 'localhost'"}},
     {'if':"vars.port >= config['remote-max-port-number']",'then':[{'title':'Port number must be < 65536','source':TV+':1123-1124','fail':{'code':'invalid-port-number','message':'Port number must be ≥ 0 and < 65536.'}}]},
     {'if':"(vars.host + ':' + string(vars.port)) in input.forwarded",'then':[{'title':'Port is already forwarded','source':TV+':1127-1128','fail':{'code':'already-forwarded','message':'Port is already forwarded'}}]},
     st('remote-explorer-service.forward',{'remote_host':'= vars.host','remote_port':'= vars.port','elevate_if_needed':True},'Forward through the remote explorer service',handler_src,as_='t'),
     {'return':{'host':'= vars.host','port':'= vars.port'}}]
CMDS=[
 # (component, comp class/summary, src for component, cmd id, file, line, request, behavior)
 ('tunnel-view-commands','tunnelView.ts module-level port commands',TV+':1531-1570','remote.tunnel.forwardInline',TV,1542,PORT,forward_beh(TV+':1151-1154')),
 ('tunnel-view-commands',None,None,'remote.tunnel.forwardCommandPalette',TV,1543,PORT,forward_beh(TV+':1177-1180')),
 ('tunnel-view-commands',None,None,'remote.tunnel.closeInline',TV,1544,PORT,[st('remote-explorer-service.close',{'remote_host':'= input.remote_host','remote_port':'= input.remote_port','reason':'user'},'Stop forwarding the selected ports',TV+':1238')]),
 ('tunnel-view-commands',None,None,'remote.tunnel.closeCommandPalette',TV,1556,PORT,[{'if':'size(input.forwarded) == 0','then':[st('command-service.execute-command',{'command_id':'remote.tunnel.forwardCommandPalette','args':[]},'No forwarded ports: run Forward a Port instead',TV+':1253-1255'),{'return':{}}]},st('remote-explorer-service.close',{'remote_host':'= input.remote_host','remote_port':'= input.remote_port','reason':'user'},'Stop forwarding the picked port',TV+':1251-1252')]),
 ('tunnel-view-commands',None,None,'remote.tunnel.open',TV,1557,PORT,[st('opener-service.open',{'resource':"= 'http://localhost:' + string(input.remote_port)"},'Open the local URI in the browser',TV+':1283')]),
 ('tunnel-view-commands',None,None,'remote.tunnel.openPreview',TV,1558,PORT,[st('opener-service.open',{'resource':"= 'http://localhost:' + string(input.remote_port)"},'Open the local URI (preview opener allowed)',TV+':1319')]),
 ('tunnel-view-commands',None,None,'remote.tunnel.openCommandPalette',TV,1559,PORT,[st('opener-service.open',{'resource':"= 'http://localhost:' + string(input.remote_port)"},'Pick a forwarded port and open it',TV+':1333-1360')]),
 ('tunnel-view-commands',None,None,'remote.tunnel.copyAddressInline',TV,1560,PORT,[st('clipboard-service.write-text',{'text':"= 'localhost:' + string(input.remote_port)"},'Copy the local address',TV+':1374-1378')]),
 ('tunnel-view-commands',None,None,'remote.tunnel.copyAddressCommandPalette',TV,1567,PORT,[st('clipboard-service.write-text',{'text':"= 'localhost:' + string(input.remote_port)"},'Pick a port and copy its address',TV+':1397-1410')]),
 ('tunnel-view-commands',None,None,'remote.tunnel.changeLocalPort',TV,1568,PORT,[st('remote-explorer-service.close',{'remote_host':'= input.remote_host','remote_port':'= input.remote_port','reason':'other'},'Close the old forward',TV+':1454'),st('remote-explorer-service.forward',{'remote_host':'= input.remote_host','remote_port':'= input.remote_port','local_port':'= int(input.value)'},'Forward again on the new local port',TV+':1456-1460')]),
 ('tunnel-view-commands',None,None,'remote.tunnel.setProtocolHttp',TV,1569,PORT,[st('remote-explorer-service.forward',{'remote_host':'= input.remote_host','remote_port':'= input.remote_port','protocol':'http'},'Re-forward with protocol http',TV+':1503-1511')]),
 ('tunnel-view-commands',None,None,'remote.tunnel.setProtocolHttps',TV,1570,PORT,[st('remote-explorer-service.forward',{'remote_host':'= input.remote_host','remote_port':'= input.remote_port','protocol':'https'},'Re-forward with protocol https',TV+':1503-1511')]),
 ('tunnel-view-commands',None,None,'remote.tunnel.label',TV,1532,PORT,[st('remote-explorer-service.set-editable',{'remote_host':'= input.remote_host','remote_port':'= input.remote_port','edit':'label'},'Inline edit of the port label; on finish tunnelModel.name()',TV+':1085-1092')]),
 ('tunnel-panel','TunnelPanel (Ports view)',TV+':686','remote.tunnel.privacy${privacyOption.id}',TV,779,PORT,[st('remote-explorer-service.close',{'remote_host':'= input.remote_host','remote_port':'= input.remote_port','reason':'other'},'Close, then re-forward with the chosen privacy',TV+':1481'),st('remote-explorer-service.forward',{'remote_host':'= input.remote_host','remote_port':'= input.remote_port','privacy':'public'},None,None)]),
 ('remote-electron-commands','remote electron-browser module commands',W+'remote/electron-browser/remote.contribution.ts:218-276','workbench.action.files.openLocalFileFolder',W+'remote/electron-browser/remote.contribution.ts',220,None,[st('file-dialog-service.pick-file-folder-and-open',{'force_new_window':False,'available_file_systems':['file']},'Pick a local file or folder from a remote window')]),
 ('remote-electron-commands',None,None,'workbench.action.files.openLocalFile',W+'remote/electron-browser/remote.contribution.ts',229,None,[st('file-dialog-service.pick-file-and-open',{'available_file_systems':['file']},'Pick a local file from a remote window')]),
 ('remote-electron-commands',None,None,'workbench.action.files.openLocalFolder',W+'remote/electron-browser/remote.contribution.ts',237,None,[st('file-dialog-service.pick-folder-and-open',{'available_file_systems':['file']},'Pick a local folder from a remote window')]),
 ('remote-electron-commands',None,None,'workbench.action.files.saveLocalFile',W+'remote/electron-browser/remote.contribution.ts',247,None,[st('file-dialog-service.pick-file-to-save',{'available_file_systems':['file']},'Save to a local file from a remote window')]),
 ('remote-electron-commands',None,None,'workbench.remote.action.closeUnusedPorts',W+'remote/electron-browser/remote.contribution.ts',256,{'type':'object','properties':{'ports':{'type':'array','items':{'type':'object'},'examples':[[{'remote_host':'localhost','remote_port':3000,'has_running_process':False},{'remote_host':'localhost','remote_port':8080,'has_running_process':True}]]}}},
   [{'title':'Close forwarded ports without a running process','source':W+'remote/electron-browser/remote.contribution.ts:268-280','foreach':'= input.ports.filter(p, p.has_running_process == false)','as':'p','steps':[st('remote-explorer-service.close',{'remote_host':'= vars.p.remote_host','remote_port':'= vars.p.remote_port','reason':'user'})]}]),
 ('remote-status-indicator',None,None,'workbench.action.remote.close',W+'remote/browser/remoteIndicator.ts',209,None,[st('host-service.open-window',{'remote_authority':None},'Reopen the window without a remote authority',W+'remote/browser/remoteIndicator.ts:217')]),
 ('remote-status-indicator',None,None,'workbench.action.remote.extensions',W+'remote/browser/remoteIndicator.ts',235,None,[{'title':'Registered only when the gallery is enabled','source':W+'remote/browser/remoteIndicator.ts:225','set':{'vars.ok':True}},st('extensions-workbench-service.open-search',{'search':'@recommended:remotes'},None,W+'remote/browser/remoteIndicator.ts:245-248')]),
 # extensions
 ('extensions-contributions-electron',None,None,'workbench.extensions.action.openExtensionsFolder',W+'extensions/electron-browser/extensions.contribution.ts',66,None,[st('native-host-service.show-item-in-folder',{'path':'/home/dev/.vscode-oss/extensions'},'Reveal the extensions folder',W+'extensions/electron-browser/extensionsActions.ts:28-45')]),
 ('extension-dependency-checker',None,None,'workbench.extensions.installMissingDependencies',W+'extensions/browser/extensionsDependencyChecker.ts',29,{'type':'object','properties':{'missing':{'type':'array','items':{'type':'string'},'default':[]}}},
   [{'if':'size(input.missing) == 0','then':[{'title':'No missing dependencies','source':W+'extensions/browser/extensionsDependencyChecker.ts:62-66','return':{'installed':[]}}]},
    {'title':'Install each missing dependency','source':W+'extensions/browser/extensionsDependencyChecker.ts:62-80','foreach':'= input.missing','as':'dep','steps':[st('extensions-workbench-service.install',{'id':'= vars.dep','version':'','install_pre_release_version':False,'pinned':False})]},
    {'return':{'installed':'= input.missing'}}]),
 ('extensions-viewlet-views-contribution',None,None,'workbench.extensions.installLocalExtensions',W+'extensions/browser/extensionsViewlet.ts',221,{'type':'object','properties':{'ids':{'type':'array','items':{'type':'string'},'default':[]}}},
   [{'title':'Pick local extensions and install them in the remote server','source':W+'extensions/browser/extensionsViewlet.ts:238-240','foreach':'= input.ids','as':'id','steps':[st('extensions-workbench-service.install',{'id':'= vars.id','version':'','install_pre_release_version':False,'pinned':False})]}]),
 ('extensions-viewlet-views-contribution',None,None,'workbench.extensions.actions.installLocalExtensionsInRemote',W+'extensions/browser/extensionsViewlet.ts',246,{'type':'object','properties':{'ids':{'type':'array','items':{'type':'string'},'default':[]}}},
   [{'title':'Pick remote extensions and install them locally','source':W+'extensions/browser/extensionsViewlet.ts:254-256','foreach':'= input.ids','as':'id','steps':[st('extensions-workbench-service.install',{'id':'= vars.id','version':'','install_pre_release_version':False,'pinned':False})]}]),
 # update
 ('update-contribution',None,None,'update.check',W+'update/browser/update.ts',320,None,[st('abstract-update-service.check-for-updates',{'explicit':True})]),
 ('update-contribution',None,None,'update.downloadNow',W+'update/browser/update.ts',322,None,[st('abstract-update-service.download-update',{'explicit':True})]),
 ('update-contribution',None,None,'update.install',W+'update/browser/update.ts',324,None,[st('abstract-update-service.apply-update',{})]),
 ('update-contribution',None,None,'update.restart',W+'update/browser/update.ts',327,None,[st('abstract-update-service.quit-and-install',{})]),
 ('update-actions','update.contribution.ts module actions',W+'update/browser/update.contribution.ts:214-217','update.checkForUpdate',W+'update/browser/update.contribution.ts',214,None,[st('abstract-update-service.check-for-updates',{'explicit':True},None,W+'update/browser/update.contribution.ts:131-132')]),
 ('update-actions',None,None,'update.downloadUpdate',W+'update/browser/update.contribution.ts',215,None,[st('abstract-update-service.download-update',{'explicit':True})]),
 ('update-actions',None,None,'update.installUpdate',W+'update/browser/update.contribution.ts',216,None,[st('abstract-update-service.apply-update',{})]),
 ('update-actions',None,None,'update.restartToUpdate',W+'update/browser/update.contribution.ts',217,None,[st('abstract-update-service.quit-and-install',{})]),
 # sync
 ('user-data-sync-workbench-contribution',None,None,'workbench.userDataSync.actions.turnOn',W+'userDataSync/browser/userDataSync.ts',769,{'type':'object','properties':{'authentication_providers':{'type':'integer','default':1}}},
   [{'if':'input.authentication_providers == 0','then':[{'title':'No authentication providers are available','source':W+'userDataSync/browser/userDataSync.ts:493-495','set':{'ctx.sync_notification':'Error while turning on Settings Sync. No authentication providers are available.'}},{'return':{}}]},
    {'title':'Ask what to sync','source':W+'userDataSync/browser/userDataSync.ts:496-499','choice':'configure','default':'turn-on','options':{'cancel':[{'return':{}}],'turn-on':[]}},
    st('user-data-sync-workbench-service.turn-on',{},'Turn on via the workbench sync service',W+'userDataSync/browser/userDataSync.ts:503',as_='r',on_error=[
       {'if':"error.code in ['incompatible-local-content', 'gone', 'upgrade-required']",'then':[{'title':'Client version not compatible with the sync service','source':W+'userDataSync/browser/userDataSync.ts:518-528','set':{'ctx.sync_notification':'upgrade-required'}},{'return':{}}]},
       {'if':"error.code in ['unauthorized', 'forbidden']",'then':[{'title':'Authentication failed','source':W+'userDataSync/browser/userDataSync.ts:546-549','set':{'ctx.sync_notification':'auth-failed'}},{'return':{}}]},
       {'title':'Error while turning on Settings Sync','source':W+'userDataSync/browser/userDataSync.ts:551-555','set':{'ctx.sync_notification':'turn-on-failed'}},{'return':{}}])]),
 ('user-data-sync-workbench-contribution',None,None,'workbench.userData.actions.cancelTurnOn',W+'userDataSync/browser/userDataSync.ts',827,None,[st('user-data-sync-workbench-service.turnoff',{'everywhere':False},None,W+'userDataSync/browser/userDataSync.ts:842')]),
 ('user-data-sync-workbench-contribution',None,None,'workbench.userData.actions.signin',W+'userDataSync/browser/userDataSync.ts',851,None,[st('user-data-sync-workbench-service.sign-in',{},None,W+'userDataSync/browser/userDataSync.ts:866')]),
 ('user-data-sync-workbench-contribution',None,None,'workbench.userDataSync.actions.syncNow',W+'userDataSync/browser/userDataSync.ts',1009,None,[st('user-data-sync-workbench-service.sync-now',{},None,W+'userDataSync/browser/userDataSync.ts:1023')]),
 ('user-data-sync-workbench-contribution',None,None,'workbench.userDataSync.actions.turnOff',W+'userDataSync/browser/userDataSync.ts',1029,None,
   [{'title':'Confirm turning off (optionally everywhere)','source':W+'userDataSync/browser/userDataSync.ts:669-681','choice':'confirm','default':'turn-off','options':{'cancel':[{'return':{}}],'turn-off':[st('user-data-sync-workbench-service.turnoff',{'everywhere':False})],'turn-off-everywhere':[st('user-data-sync-workbench-service.turnoff',{'everywhere':True})]}}]),
 ('user-data-sync-workbench-contribution',None,None,'workbench.userDataSync.actions.configure',W+'userDataSync/browser/userDataSync.ts',1056,{'type':'object','properties':{'disable':{'type':'array','items':{'type':'string'},'default':['extensions']}}},
   [{'title':'Choose what to sync (multi-select quick pick); unselected resources are disabled','source':W+'userDataSync/browser/userDataSync.ts:642-667','foreach':'= input.disable','as':'r','steps':[st('user-data-sync-enablement-service.set-resource-enablement',{'resource':'= vars.r','enabled':False})]}]),
 ('user-data-sync-workbench-contribution',None,None,'workbench.userDataSync.actions.acceptMerges',W+'userDataSync/browser/userDataSync.ts',1150,{'type':'object','properties':{'side':{'type':'string','default':'local'}}},[st('user-data-sync-service.accept',{'resource':'settings','side':'= input.side'},'Save the merge preview and accept it',W+'userDataSync/browser/userDataSync.ts:1164-1166')]),
 ('user-data-sync-workbench-contribution',None,None,'DownloadSyncActivityAction',W+'userDataSync/browser/userDataSync.ts',1180,None,[st('user-data-sync-service.save-remote-activity-data',{'location':'file:///home/dev/Downloads/sync-activity.json'},'Download the sync activity',W+'userDataSync/browser/userDataSync.ts:1184-1190')]),
 ('user-data-sync-workbench-contribution',None,None,'workbench.actions.syncData.reset',W+'userDataSync/browser/userDataSync.ts',1217,None,[st('user-data-sync-workbench-service.reset-synced-data',{},None,W+'userDataSync/browser/userDataSync.ts:1229')]),
 ('user-data-sync-conflicts-view-pane','UserDataSyncConflictsViewPane',W+'userDataSync/browser/userDataSyncConflictsView.ts:33','workbench.actions.sync.acceptRemote',W+'userDataSync/browser/userDataSyncConflictsView.ts',141,None,[st('user-data-sync-workbench-service.accept',{'side':'remote'},None,W+'userDataSync/browser/userDataSyncConflictsView.ts:157')]),
 ('user-data-sync-conflicts-view-pane',None,None,'workbench.actions.sync.acceptLocal',W+'userDataSync/browser/userDataSyncConflictsView.ts',161,None,[st('user-data-sync-workbench-service.accept',{'side':'local'},None,W+'userDataSync/browser/userDataSyncConflictsView.ts:177')]),
 ('user-data-sync-data-views','UserDataSyncDataViews',W+'userDataSync/browser/userDataSyncViews.ts:37','workbench.actions.sync.editMachineName',W+'userDataSync/browser/userDataSyncViews.ts',102,{'type':'object','properties':{'name':{'type':'string','examples':['work-laptop']}}},[st('user-data-sync-machines-service.rename-machine',{'name':'= input.name'},'Rename the machine',W+'userDataSync/browser/userDataSyncViews.ts:724')]),
 ('user-data-sync-data-views',None,None,'workbench.actions.sync.turnOffSyncOnMachine',W+'userDataSync/browser/userDataSyncViews.ts',123,None,[{'title':'Confirm, then disable sync on the selected machine','source':W+'userDataSync/browser/userDataSyncViews.ts:135-137','choice':'confirm','default':'turn-off','options':{'cancel':[{'return':{}}],'turn-off':[st('user-data-sync-machines-service.set-enablements',{'disabled':True},None,W+'userDataSync/browser/userDataSyncViews.ts:690')]}}]),
 ('user-data-sync-data-views',None,None,'workbench.actions.sync.${viewId}.replaceCurrent',W+'userDataSync/browser/userDataSyncViews.ts',271,None,[{'title':'Confirm replacing the current data','source':W+'userDataSync/browser/userDataSyncViews.ts:288-295','choice':'confirm','default':'replace','options':{'cancel':[{'return':{}}],'replace':[st('user-data-sync-service.replace',{})]}}]),
 ('user-data-sync-electron-commands','userDataSync electron-browser module actions',W+'userDataSync/electron-browser/userDataSync.contribution.ts:15-60','workbench.userData.actions.openSyncBackupsFolder',W+'userDataSync/electron-browser/userDataSync.contribution.ts',18,None,
   [{'title':'Reveal the newest backup folder, or say none exists','source':W+'userDataSync/electron-browser/userDataSync.contribution.ts:30-41','choice':'exists','default':'yes','options':{'yes':[st('native-host-service.show-item-in-folder',{'path':'/home/dev/.config/Code - OSS/User/sync'})],'no':[{'set':{'ctx.sync_notification':'Local backups folder does not exist'}}]}}]),
 ('user-data-sync-electron-commands',None,None,'DownloadSyncActivityAction',W+'userDataSync/electron-browser/userDataSync.contribution.ts',45,None,[st('user-data-sync-workbench-service.download-sync-activity',{},None,W+'userDataSync/electron-browser/userDataSync.contribution.ts:54')]),
]
comps=[]; ifaces=[]; flows=[]; seen=set(); existing={'tunnel-view-commands':0}
known={'remote-status-indicator','extensions-contributions-electron','extension-dependency-checker','extensions-viewlet-views-contribution','update-contribution','user-data-sync-workbench-contribution'}
for (cid,cname,csrc,cmd,f,line,req,beh) in CMDS:
    assert (cmd,f,line) in inv, (cmd,f,line)
    if cid not in known and cid not in seen:
        comps.append({'id':cid,'name':cname,'kind':'module','layer':'remote','parent':'remote','sources':[csrc],'summary':cname,'attributes':{'owner':'remote-server'}})
    seen.add(cid)
    name=cslug(cmd if not cmd.startswith('DownloadSync') else 'workbench.userData.actions.downloadSyncActivity')
    if (cid,name) in {(i['component'],i['name']) for i in ifaces}: name=name+'-'+str(line)
    if 'DownloadSync' in cmd and 'electron' in f: name=name+'-electron'
    i={'component':cid,'name':name,'kind':'command','attributes':{'command_id':cmd},'summary':f'{cmd}','sources':[f'{f}:{line}'],'behavior':beh}
    if req: i['request']=req
    ifaces.append(i)
    fid=('rs-'+name)[:64]
    flows.append({'id':fid,'name':cmd,'entry':{'caller':'user','interface':f'{cid}.{name}'}})
def B(c,n,owner,**kw): d={'component':c,'name':n,'kind':kw.pop('kind','function'),'summary':kw.pop('summary',f'{c}.{n} (boundary)'),'attributes':{'boundary':True,'owner':owner}}; d.update(kw); return d
ifaces+=[B('remote-explorer-service','forward','workbench-shell',request={'type':'object','properties':{'remote_host':{'type':'string'},'remote_port':{'type':'integer'}}}),
 B('remote-explorer-service','close','workbench-shell'),B('remote-explorer-service','set-editable','workbench-shell'),
 B('opener-service','open','platform-core',request={'type':'object','required':['resource'],'properties':{'resource':{'type':'string','examples':['https://github.com/microsoft/vscode/pull/1']},'allow_commands':{'type':'boolean','default':False},'open_external':{'type':'boolean','default':False},'open_to_side':{'type':'boolean','default':False}}},response={'type':'object','properties':{'opened':{'type':'boolean'},'via':{'type':'string'}}}),B('clipboard-service','write-text','workbench-shell'),
 B('file-dialog-service','pick-file-folder-and-open','workbench-shell'),B('file-dialog-service','pick-file-and-open','workbench-shell'),B('file-dialog-service','pick-folder-and-open','workbench-shell'),B('file-dialog-service','pick-file-to-save','workbench-shell'),
 B('native-host-service','show-item-in-folder','workbench-shell'),
 B('abstract-update-service','check-for-updates','main-process',kind='ipc'),B('abstract-update-service','download-update','main-process',kind='ipc'),B('abstract-update-service','apply-update','main-process',kind='ipc'),B('abstract-update-service','quit-and-install','main-process',kind='ipc'),
 B('user-data-sync-workbench-service','turn-on','workbench-shell'),B('user-data-sync-workbench-service','turnoff','workbench-shell'),B('user-data-sync-workbench-service','sign-in','workbench-shell'),B('user-data-sync-workbench-service','sync-now','workbench-shell'),
 B('user-data-sync-workbench-service','reset-synced-data','workbench-shell'),B('user-data-sync-workbench-service','accept','workbench-shell'),B('user-data-sync-workbench-service','download-sync-activity','workbench-shell')]
def S(fid,alias,**inp): d={'flow':fid,'as':alias}; d.update({'input':inp} if inp else {}); return d
F=lambda n: next(f['id'] for f in flows if f['name']==n)
scen=[
 {'id':'remote-server-tunnel-commands','fixtures':['one-window-folder'],'steps':[
   S(F('remote.tunnel.forwardInline'),'fwd',value='3000',forwarded=[]),S(F('remote.tunnel.forwardInline'),'fbig',value='65536',forwarded=[]),S(F('remote.tunnel.forwardInline'),'fdup',value='3000',forwarded=['localhost:3000']),
   S(F('remote.tunnel.forwardCommandPalette'),'big',value='70000',forwarded=[]),
   S(F('remote.tunnel.forwardCommandPalette'),'dup',value='localhost:3000',forwarded=['localhost:3000']),
   S(F('remote.tunnel.closeInline'),'ci'), S(F('remote.tunnel.closeCommandPalette'),'cp',forwarded=['localhost:3000']),
   S(F('remote.tunnel.closeCommandPalette'),'cpe',forwarded=[]),
   S(F('remote.tunnel.open'),'o'),S(F('remote.tunnel.openPreview'),'op'),S(F('remote.tunnel.openCommandPalette'),'ocp'),
   S(F('remote.tunnel.copyAddressInline'),'ca'),S(F('remote.tunnel.copyAddressCommandPalette'),'cap'),
   S(F('remote.tunnel.changeLocalPort'),'clp',value='4000'),S(F('remote.tunnel.setProtocolHttp'),'h'),S(F('remote.tunnel.setProtocolHttps'),'hs'),
   S(F('remote.tunnel.label'),'lb'),S(F('remote.tunnel.privacy${privacyOption.id}'),'pv'),
   S(F('workbench.remote.action.closeUnusedPorts'),'cu')],
  'expect':["steps.fbig.result.error.code == 'invalid-port-number' && steps.fdup.result.error.code == 'already-forwarded' && steps.fwd.result.value.port == 3000 && steps.big.result.error.code == 'invalid-port-number' && steps.dup.result.error.code == 'already-forwarded'",
            "calls['remote-explorer-service.forward'] == 5 && calls['remote-explorer-service.close'] == 5",
            "calls['clipboard-service.write-text'] == 2 && calls['opener-service.open'] == 3",
            "trace.exists(e, e.type == 'call.start' && e.interface == 'command-service.execute-command' && e.input.command_id == 'remote.tunnel.forwardCommandPalette')"]},
 {'id':'remote-server-remote-window-commands','fixtures':['one-window-folder'],'steps':[S(F(c),'s%d'%i) for i,c in enumerate(['workbench.action.files.openLocalFileFolder','workbench.action.files.openLocalFile','workbench.action.files.openLocalFolder','workbench.action.files.saveLocalFile','workbench.action.remote.close','workbench.action.remote.extensions','workbench.extensions.action.openExtensionsFolder'])],
  'expect':["calls['host-service.open-window'] == 1 && calls['native-host-service.show-item-in-folder'] == 1",
            "state['extensions-workbench-service@w1'].last_search == '@recommended:remotes'"]},
 {'id':'remote-server-update-commands','fixtures':['one-window-folder'],'steps':[S(F(c),'u%d'%i) for i,c in enumerate(['update.check','update.downloadNow','update.install','update.restart','update.checkForUpdate','update.downloadUpdate','update.installUpdate','update.restartToUpdate'])],
  'expect':["calls['abstract-update-service.check-for-updates'] == 2 && calls['abstract-update-service.download-update'] == 2 && calls['abstract-update-service.apply-update'] == 2 && calls['abstract-update-service.quit-and-install'] == 2",
            "trace.filter(e, e.type == 'call.start' && e.interface == 'abstract-update-service.check-for-updates').all(e, e.input.explicit)"]},
 {'id':'remote-server-extension-install-commands','fixtures':['one-window-folder'],'config':{'product-extensions-gallery-service-url':'https://marketplace.example/_apis/public/gallery'},
  'steps':[S(F('workbench.extensions.installMissingDependencies'),'none',missing=[]),S(F('workbench.extensions.installMissingDependencies'),'deps',missing=['ms-python.python']),
           S(F('workbench.extensions.installLocalExtensions'),'loc',ids=['ms-python.python']),S(F('workbench.extensions.actions.installLocalExtensionsInRemote'),'rem',ids=[]),
           {'flow':'rs-ext-query-installed','as':'list'}],
  'expect':["steps.none.result.value.installed == [] && steps.deps.result.ok","steps.list.result.value.user.exists(e, e.id == 'ms-python.python')","'ms-python.python' in state['extensions-profile-scanner-service'].profile_extensions"]},
 {'id':'remote-server-sync-commands','fixtures':['one-window-folder'],'config':{'product-configuration-sync-store-url':'https://sync.example/v1'},
  'state':{'user-data-sync-enablement-service':{'enabled':True},'user-data-sync-service':{'status':'has-conflicts','conflicts':['settings']},'settings-synchroniser':{'status':'has-conflicts'}},
  'steps':[S(F(c),'c%d'%i) for i,c in enumerate(['workbench.userDataSync.actions.turnOn','workbench.userData.actions.cancelTurnOn','workbench.userData.actions.signin','workbench.userDataSync.actions.syncNow','workbench.userDataSync.actions.turnOff','workbench.userDataSync.actions.configure','workbench.userDataSync.actions.acceptMerges','workbench.actions.syncData.reset','workbench.actions.sync.acceptRemote','workbench.actions.sync.acceptLocal','workbench.actions.sync.editMachineName','workbench.actions.sync.turnOffSyncOnMachine','workbench.actions.sync.${viewId}.replaceCurrent','workbench.userData.actions.openSyncBackupsFolder'])]
           +[{'flow':f['id'],'as':'dl%d'%j} for j,f in enumerate(x for x in flows if x['name']=='DownloadSyncActivityAction')]+[{'flow':'rs-sync-status','as':'st'}],
  'expect':["steps.st.result.value.status == 'idle' && steps.st.result.value.conflicts == []",
            "!state['user-data-sync-enablement-service'].resources.extensions && state['user-data-sync-machines-service'].current_machine.disabled",
            "calls['user-data-sync-workbench-service.turn-on'] == 1 && calls['user-data-sync-workbench-service.turnoff'] == 2 && calls['user-data-sync-workbench-service.accept'] == 2"]},
 {'id':'remote-server-sync-command-refusals','fixtures':['one-window-folder'],
  'choices':{'user-data-sync-workbench-contribution.cmd-workbench-userdatasync-actions-turnoff.confirm':'turn-off-everywhere','user-data-sync-electron-commands.cmd-workbench-userdata-actions-opensyncbackupsfolder.exists':'no','user-data-sync-data-views.cmd-workbench-actions-sync-turnoffsynconmachine.confirm':'cancel','user-data-sync-data-views.cmd-workbench-actions-sync-viewid-replacecurrent.confirm':'cancel','user-data-sync-workbench-contribution.cmd-workbench-userdatasync-actions-turnon.configure':'cancel'},
  'steps':[S(F('workbench.userDataSync.actions.turnOn'),'noauth',authentication_providers=0),S(F('workbench.userDataSync.actions.turnOn'),'cancel'),
           S(F('workbench.userDataSync.actions.turnOff'),'off'),S(F('workbench.userData.actions.openSyncBackupsFolder'),'bk'),S(F('workbench.actions.sync.turnOffSyncOnMachine'),'tm'),S(F('workbench.actions.sync.${viewId}.replaceCurrent'),'rc')],
  'expect':["ctx.sync_notification == 'Local backups folder does not exist'","calls['user-data-sync-workbench-service.turn-on'] == 0 && !state['user-data-sync-machines-service'].current_machine.disabled",
            "trace.exists(e, e.type == 'call.start' && e.interface == 'user-data-sync-workbench-service.turnoff' && e.input.everywhere)"]},
]
for code,alias in [('gone','g'),('unauthorized','u'),('eio','x')]:
    scen.append({'id':f'remote-server-sync-turn-on-command-error-{code}','flow':F('workbench.userDataSync.actions.turnOn'),'fixtures':['one-window-folder'],
      'faults':[{'target':'user-data-sync-workbench-service.turn-on','type':'error','code':code}],
      'expect':[f"result.ok && ctx.sync_notification == '{ {'gone':'upgrade-required','unauthorized':'auth-failed','eio':'turn-on-failed'}[code] }'", "trace.exists(e, e.type == 'call.start' && e.interface == 'user-data-sync-workbench-service.turn-on')"]})
PART={'components':comps,'interfaces':ifaces,'flows':flows,'scenarios':scen}

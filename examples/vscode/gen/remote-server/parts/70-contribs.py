W='src/vs/workbench/contrib/'
def slug(s):
    import re
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])','-',s).lower()
# (registration file, line, class, component id, ctor src, phase, summary, extra behavior steps)
EB=W+'extensions/browser/extensions.contribution.ts'
EE=W+'extensions/electron-browser/extensions.contribution.ts'
RB=W+'remote/browser/remote.contribution.ts'
RS=W+'remote/browser/remoteStartEntry.contribution.ts'
RC=W+'remote/common/remote.contribution.ts'
RE=W+'remote/electron-browser/remote.contribution.ts'
UP=W+'update/browser/update.contribution.ts'
US=W+'userDataSync/browser/userDataSync.contribution.ts'
UE=W+'userDataSync/electron-browser/userDataSyncUtilChannel.contribution.ts'
def call(i, inp=None, **kw):
    d={'call':i,'input':inp or {}}
    if 'as_' in kw: kw['as']=kw.pop('as_')
    d.update(kw); return d
C=[
 (EB,2128,'ExtensionsContributions','extensions-contributions',W+'extensions/browser/extensions.contribution.ts:630-670','Restored','Binds server context keys, tracks the gallery manifest status and registers the Extensions global actions and quick access.',[call('extension-gallery-manifest-service.get-extension-gallery-manifest-status',as_='st')]),
 (EB,2129,'StatusUpdater','status-updater',W+'extensions/browser/extensionsViewlet.ts:1025-1034','Eventually','Shows the Extensions activity badge (outdated plus action-required count) and refreshes it on changes.',[]),
 (EB,2130,'MaliciousExtensionChecker','malicious-extension-checker',W+'extensions/browser/extensionsViewlet.ts:1072-1081','Eventually','Every 5 minutes, uninstalls installed extensions reported as malicious.',None),
 (EB,2131,'KeymapExtensions','keymap-extensions',W+'extensions/common/extensionsUtils.ts:27-40','Restored','Checks for other keymap extensions whenever an extension changes.',[]),
 (EB,2132,'ExtensionsViewletViewsContribution','extensions-viewlet-views-contribution',W+'extensions/browser/extensionsViewlet.ts:105-114','Restored','Registers the Extensions viewlet views (and, with a remote server, the install-local-in-remote actions).',[]),
 (EB,2133,'ExtensionActivationProgress','extension-activation-progress',W+'extensions/browser/extensionsActivationProgress.ts:20-52','Eventually','Shows "Activating Extensions..." window progress while activations run (5 s cap).',[]),
 (EB,2134,'ExtensionDependencyChecker','extension-dependency-checker',W+'extensions/browser/extensionsDependencyChecker.ts:22-37','Eventually','Registers workbench.extensions.installMissingDependencies.',[]),
 (EB,2135,'ExtensionEnablementWorkspaceTrustTransitionParticipant','extension-enablement-workspace-trust-transition-participant',W+'extensions/browser/extensionEnablementWorkspaceTrustTransitionParticipant.ts:16-56','Restored','When workspace trust is enabled, updates extension enablement on trust changes (reloads a remote window when losing trust).',
   [{'if':"config['security-workspace-trust-enabled']",'then':[{'title':'Add the trust transition participant','source':W+'extensions/browser/extensionEnablementWorkspaceTrustTransitionParticipant.ts:25-30','set':{'ctx.trust_participant':True}}]}]),
 (EB,2136,'ExtensionsCompletionItemsProvider','extensions-completion-items-provider',W+'extensions/browser/extensionsCompletionItemsProvider.ts:20-50','Restored','Completion of extension ids in settings.json for extensions.supportUntrustedWorkspaces.',[]),
 (EB,2137,'ExtensionEnablementContextKeysContribution','extension-enablement-context-keys-contribution',W+'extensions/browser/extensionEnablementContext.ts:34-51','Restored','Keeps per-extension enablement context keys in sync with running extensions.',[]),
 (EB,2138,'UnsupportedExtensionsMigrationContrib','unsupported-extensions-migration-contrib',W+'extensions/browser/unsupportedExtensionsMigrationContribution.ts:15-29','Eventually','Migrates unsupported extensions on the remote and web servers (the shared process handles the local one).',[]),
 (EB,2139,'TrustedPublishersInitializer','trusted-publishers-initializer',W+'extensions/browser/extensions.contribution.ts:2079-2109','Eventually','One-time migration trusting the publishers of installed user extensions.',[call('extensions-profile-scanner-service.scan-profile-extensions')]),
 (EB,2140,'ExtensionMarketplaceStatusUpdater','extension-marketplace-status-updater',W+'extensions/browser/extensionsViewlet.ts:1140-1147','Eventually','Badge reflecting the gallery manifest status.',[call('extension-gallery-manifest-service.get-extension-gallery-manifest-status')]),
 (EB,2142,'ExtensionStorageCleaner','extension-storage-cleaner',W+'extensions/browser/extensions.contribution.ts:2070-2075','Eventually','(Registered on web only) removes extension storage left by outdated versions.',[call('extension-storage-service.remove-outdated-extension-versions')]),
 (EB,2145,'ExtensionToolsContribution','extension-tools-contribution',W+'extensions/browser/extensions.contribution.ts:2116-2124','AfterRestored','Registers the extension search language-model tool.',[]),
 (EE,72,'ExtensionsContributions','extensions-contributions-electron',W+'extensions/electron-browser/extensions.contribution.ts:58-68','Restored','Registers the shared-process channel extensionRecommendationNotification and the Open/Clean Up Extensions Folder actions.',
   [{'title':"sharedProcessService.registerChannel('extensionRecommendationNotification')",'source':W+'extensions/electron-browser/extensions.contribution.ts:64','set':{'ctx.channel_extension_recommendation_notification':True}}]),
 (EE,73,'ExtensionsAutoProfiler','extensions-auto-profiler',W+'extensions/electron-browser/extensionsAutoProfiler.ts:45-70','Eventually','Profiles an unresponsive extension host after measuring the perf baseline.',[]),
 (EE,74,'RemoteExtensionsInitializerContribution','remote-extensions-initializer-contribution',W+'extensions/electron-browser/remoteExtensionsInit.ts:122-134','Restored','On a first connection to a new remote with sync on, installs the synced extensions there.',
   [call('user-data-sync-enablement-service.is-enabled',as_='en'),{'if':'!vars.en.value.enabled','then':[{'title':'Settings sync off: nothing to initialize','source':W+'extensions/electron-browser/remoteExtensionsInit.ts:141-171','return':{}}]},call('remote-authority-resolver-service.resolve-authority',{'authority':'ssh-remote+dev-box'})]),
 (EE,75,'InstallRemoteExtensionsContribution','install-remote-extensions-contribution',W+'extensions/electron-browser/remoteExtensionsInit.ts:33-44','Restored','Installs on the remote the locally installed extensions listed for remote installation, and retries failed ones.',[]),
 (EE,76,'DebugExtensionsContribution','debug-extensions-contribution',W+'extensions/electron-browser/debugExtensionHostAction.ts:256-302','Restored','Attaches the debugger to stored extension-host/renderer debug ports.',[]),
 (RB,40,'ShowCandidateContribution','show-candidate-contribution',W+'remote/browser/showCandidate.ts:16-37','BlockRestore','Web embedder port-candidate filter.',[]),
 (RB,41,'TunnelFactoryContribution','tunnel-factory-contribution',W+'remote/browser/tunnelFactory.ts:22-99','BlockRestore','Installs the embedder tunnel factory as tunnel provider.',[]),
 (RB,42,'RemoteAgentConnectionStatusListener','remote-agent-connection-status-listener',W+'remote/browser/remote.ts:791-800','Eventually','Subscribes to the remote connection state (see on-did-state-change).',[]),
 (RB,43,'RemoteStatusIndicator','remote-status-indicator',W+'remote/browser/remoteIndicator.ts:140-184','BlockStartup','Remote status bar entry and the Remote menu actions.',[]),
 (RB,44,'ForwardedPortsView','forwarded-ports-view',W+'remote/browser/remoteExplorer.ts:66-86','Restored','Enables the Ports view and its badge.',[]),
 (RB,45,'PortRestore','port-restore',W+'remote/browser/remoteExplorer.ts:192-203','Eventually','Restores forwarded ports once environment tunnels are known (remote.restoreForwardedPorts).',[call('remote-explorer-service.restore')]),
 (RB,46,'AutomaticPortForwarding','automatic-port-forwarding',W+'remote/browser/remoteExplorer.ts:217-253','Eventually','Starts output- or process-based automatic port forwarding (remote windows only).',[]),
 (RB,47,'RemoteMarkers','remote-markers',W+'remote/browser/remote.ts:670-679','Eventually','Copies the server performance marks into the timer service.',[call('remote-agent-environment-channel.get-environment-data')]),
 (RB,48,'InitialRemoteConnectionHealthContribution','initial-remote-connection-health-contribution',W+'remote/browser/remoteConnectionHealth.ts:30-44','Restored','Checks the first connection: unsupported glibc prompt, ARM32 banner, success/failure telemetry.',None),
 (RS,12,'RemoteStartEntry','remote-start-entry',W+'remote/browser/remoteStartEntry.ts:27-44','Restored','Shows the web remote start entry when the tunnel extension is installed and enabled.',[]),
 (RC,150,'LabelContribution','label-contribution',W+'remote/common/remote.contribution.ts:39-43','BlockStartup','Registers the vscode-remote label formatter for the remote OS.',[call('remote-agent-environment-channel.get-environment-data')]),
 (RC,151,'RemoteChannelsContribution','remote-channels-contribution',W+'remote/common/remote.contribution.ts:72-83','Restored','Registers the download channel and the logger channel client on the remote connection.',
   [{'title':"connection.registerChannel('download', DownloadServiceChannel)",'source':W+'remote/common/remote.contribution.ts:80','set':{'ctx.channel_download':True}}]),
 (RC,152,'RemoteInvalidWorkspaceDetector','remote-invalid-workspace-detector',W+'remote/common/remote.contribution.ts:90-115','BlockStartup','Validates the remote workspace exists once the remote environment resolves.',[]),
 (RE,197,'RemoteAgentDiagnosticListener','remote-agent-diagnostic-listener',W+'remote/electron-browser/remote.contribution.ts:41-72','Eventually','Answers vscode:getDiagnosticInfo with remote diagnostics.',[]),
 (RE,198,'RemoteExtensionHostEnvironmentUpdater','remote-extension-host-environment-updater',W+'remote/electron-browser/remote.contribution.ts:76-94','Eventually','On ConnectionGain re-resolves the authority and updates the extension host env.',[call('remote-authority-resolver-service.resolve-authority',{'authority':'ssh-remote+dev-box'})]),
 (RE,199,'RemoteTelemetryEnablementUpdater','remote-telemetry-enablement-updater',W+'remote/electron-browser/remote.contribution.ts:101-115','BlockRestore','Pushes the telemetry level to the remote.',[]),
 (RE,200,'RemoteEmptyWorkbenchPresentation','remote-empty-workbench-presentation',W+'remote/electron-browser/remote.contribution.ts:127-156','BlockRestore','In an empty remote window opens the Explorer and toggles the terminal.',[]),
 (RE,202,'WSLContextKeyInitializer','wsl-context-key-initializer',W+'remote/electron-browser/remote.contribution.ts:166-193','BlockRestore','(Windows) wslFeatureInstalled context key.',[]),
 (UP,34,'ProductContribution','product-contribution',W+'update/browser/update.ts:168-214','Restored','Shows release notes after a major.minor update; stores the current version.',[]),
 (UP,35,'UpdateContribution','update-contribution',W+'update/browser/update.ts:224-268','Restored','Tracks update state context keys and badges; registers the update.* global activity commands.',[]),
 (UP,36,'SwitchProductQualityContribution','switch-product-quality-contribution',W+'update/browser/update.ts:361-368','Restored','Web: registers the switch to Insiders/Stable action.',[]),
 (UP,37,'DefaultAccountUpdateContribution','default-account-update-contribution',W+'update/browser/update.ts:483-502','Eventually','Sets the internal org on the update service from the default account.',[call('abstract-update-service.set-internal-org')]),
 (UP,38,'UpdateTitleBarContribution','update-title-bar-contribution',W+'update/browser/updateTitleBarEntry.ts:88-148','Restored','Title-bar update entry.',[]),
 (UP,39,'PostUpdateWidgetContribution','post-update-widget-contribution',W+'update/browser/postUpdateWidget.ts:49-71','Restored','Registers _update.showUpdateInfo and shows the post-update widget on startup.',[]),
 (US,84,'UserDataSyncWorkbenchContribution','user-data-sync-workbench-contribution',W+'userDataSync/browser/userDataSync.ts:96-153','Restored','When a sync store is configured: badges, conflict tracking, sync actions and views.',
   [call('user-data-sync-store-management-service.get-user-data-sync-store',as_='store'),{'if':'vars.store.value.url == ""','then':[{'title':'No sync store (OSS): no sync actions or views are registered','source':W+'userDataSync/browser/userDataSync.ts:124','return':{'registered':False}}]},{'set':{'ctx.sync_actions_registered':True}}]),
 (US,85,'UserDataSyncTrigger','user-data-sync-trigger',W+'userDataSync/browser/userDataSyncTrigger.ts:23-46','Eventually','Triggers a sync when a user-data editor or the Extensions viewlet becomes visible.',[call('user-data-auto-sync-service.trigger-sync',{'sources':['extensionsViewlet']})]),
 (US,86,'UserDataSyncReportIssueContribution','user-data-sync-report-issue-contribution',W+'userDataSync/browser/userDataSync.contribution.ts:24-33','Eventually','Offers to report an issue on auto-sync errors.',[]),
 (UE,25,'UserDataSyncUtilChannelContribution','user-data-sync-util-channel-contribution',W+'userDataSync/electron-browser/userDataSyncUtilChannel.contribution.ts:16-22','BlockStartup','Exposes IUserDataSyncUtilService to the shared process.',
   [{'title':"sharedProcessService.registerChannel('userDataSyncUtil') serving IUserDataSyncUtilService",'source':W+'userDataSync/electron-browser/userDataSyncUtilChannel.contribution.ts:21','set':{'ctx.channel_user_data_sync_util':True}},
    {'title':'IUserDataSyncUtilService (implemented by workbench-shell UserDataSyncUtilService)','source':'src/vs/platform/userDataSync/common/userDataSync.ts:645','set':{'ctx.util_service':True}}]),
]
def fix(steps):
    out=[]
    for s in steps:
        s=dict(s)
        if 'as_' in s: s['as']=s.pop('as_')
        out.append(s)
    return out
MAL=[call('extension-gallery-service.get-extensions-control-manifest',as_='cm',on_error='continue'),
     {'if':'!vars.cm.ok','then':[{'return':{}}]},
     call('extensions-profile-scanner-service.scan-profile-extensions',as_='inst'),
     {'foreach':'= vars.inst.value','as':'ext','steps':[{'if':'vars.ext.id in vars.cm.value.malicious','then':[
        {'title':'Uninstall the malicious extension','source':W+'extensions/browser/extensionsViewlet.ts:1083-1120','call':'extensions-workbench-service.uninstall','input':{'id':'= vars.ext.id'}}]}]},
     {'title':'Check again in 5 minutes','source':W+'extensions/browser/extensionsViewlet.ts:1083-1095','set':{'ctx.malicious_checked':True}}]
HEALTH=[{'title':'Only for remote windows','source':W+'remote/browser/remoteConnectionHealth.ts:41-43','set':{'ctx.health_checked':True}},
  {'choice':'environment','default':'supported','options':{
     'supported':[{'title':'remoteConnectionSuccess telemetry, then measure latency','source':W+'remote/browser/remoteConnectionHealth.ts:142-149','set':{'ctx.remote_health':'ok'}}],
     'unsupported-glibc':[{'title':'Unsupported OS prompt: Allow or Cancel','source':W+'remote/browser/remoteConnectionHealth.ts:46-84','choice':'allow','default':'allow','options':{
         'allow':[{'title':'Allowed: show the unsupported-glibc banner','source':W+'remote/browser/remoteConnectionHealth.ts:96-107','set':{'ctx.remote_health':'unsupported-allowed'}}],
         'cancel':[{'title':'Not allowed: reopen the window locally','source':W+'remote/browser/remoteConnectionHealth.ts:108-110','call':'host-service.open-window','input':{'remote_authority':None}},{'set':{'ctx.remote_health':'reopened-local'}}]}}],
     'failed':[{'title':'getRawEnvironment failed: remoteConnectionFailure telemetry only','source':W+'remote/browser/remoteConnectionHealth.ts:151-173','set':{'ctx.remote_health':'failed'}}]}}]
comps=[]; ifaces=[]; mods={}
existing={'remote-agent-connection-status-listener'}
for (f,line,cls,cid,src,phase,summ,extra) in C:
    if cid not in existing:
        comps.append({'id':cid,'name':cls,'kind':'module','layer':'remote','parent':'remote','sources':[src],'summary':summ,'attributes':{'owner':'remote-server','phase':phase}})
    beh=[{'title':f'{cls} constructor','source':src,'set':{f'ctx.started_{cid.replace("-","_")}':True}}]
    if cid=='malicious-extension-checker': beh+=MAL
    elif cid=='initial-remote-connection-health-contribution': beh+=HEALTH
    else: beh+=fix(extra)
    ifaces.append({'component':cid,'name':'start','kind':'event','summary':f'{cls}: workbench contribution startup ({phase})','sources':[src],'behavior':beh})
    mods.setdefault(f,[]).append((line,cls,cid,phase))
names={EB:'extensions-browser-contribution-registrations',EE:'extensions-electron-contribution-registrations',RB:'remote-browser-contribution-registrations',RS:'remote-start-entry-contribution-registrations',RC:'remote-common-contribution-registrations',RE:'remote-electron-contribution-registrations',UP:'update-contribution-registrations',US:'user-data-sync-contribution-registrations',UE:'user-data-sync-util-channel-contribution-registrations'}
flows=[]; steps=[]
for f,lst in mods.items():
    mid=names[f]
    comps.append({'id':mid,'name':f.split('/')[-3]+'/'+f.split('/')[-2]+'/'+f.split('/')[-1]+' registrations','kind':'module','layer':'remote','parent':'remote','sources':[f"{f}:{min(l for l,*_ in lst)}-{max(l for l,*_ in lst)}"],'summary':'Workbench contributions this file registers with the contribution registry, instantiated by the workbench at their lifecycle phase.','attributes':{'owner':'remote-server'}})
    beh=[{'title':f'registerWorkbenchContribution({cls}, {ph})','source':f'{f}:{l}','call':f'{cid}.start','input':{}} for (l,cls,cid,ph) in lst]
    ifaces.append({'component':mid,'name':'instantiate-contributions','kind':'event','summary':'The workbench instantiates these registered contributions as it reaches each lifecycle phase (registry owned by workbench-shell).','sources':[f"{f}:{l}" for (l,*_) in lst][:1],'behavior':beh})
    fid='rs-startup-'+mid.replace('-contribution-registrations','')
    flows.append({'id':fid,'name':f'Workbench startup: contributions of {f.split("contrib/")[1]}','entry':{'caller':'workbench','interface':f'{mid}.instantiate-contributions'}})
    steps.append({'flow':fid,'as':fid.replace('-','_')})
for s,d in [('extension-storage-service','remove-outdated-extension-versions'),]:
    ifaces.append({'component':s,'name':d,'kind':'function','summary':'removeOutdatedExtensionVersions','sources':['src/vs/platform/extensionManagement/common/extensionStorage.ts:43-60'],'behavior':[{'return':{'removed':0}}]})
ifaces += [
 {'component':'remote-explorer-service','name':'restore','kind':'function','summary':'IRemoteExplorerService.restore (boundary)','attributes':{'boundary':True,'owner':'workbench-shell'}},
 {'component':'host-service','name':'open-window','kind':'function','summary':'IHostService.openWindow (boundary)','request':{'type':'object','properties':{'remote_authority':{'type':['string','null']}}},'attributes':{'boundary':True,'owner':'workbench-shell'}},
 {'component':'abstract-update-service','name':'set-internal-org','kind':'ipc','summary':'IUpdateService.setInternalOrg (boundary)','attributes':{'boundary':True,'owner':'main-process'}},
 {'component':'user-data-sync-store-management-service','name':'get-user-data-sync-store','kind':'function','summary':'userDataSyncStore: from product.json configurationSync.store (undefined in OSS)','sources':['src/vs/platform/userDataSync/common/userDataSyncStoreService.ts:80-87'],
  'response':{'type':'object','properties':{'url':{'type':'string'}}},'behavior':[{'return':{'url':"= config['product-configuration-sync-store-url']"}}]},
]
scen=[
 {'id':'remote-server-startup-contributions-local-window','fixtures':['one-window-folder'],'steps':steps,
  'expect':["ctx.started_extensions_contributions && ctx.started_user_data_sync_util_channel_contribution && ctx.channel_download && ctx.channel_user_data_sync_util",
            "ctx.remote_health == 'ok' && ctx.trust_participant && ctx.malicious_checked",
            "!has(ctx.sync_actions_registered) && trace.exists(e, e.type == 'note' && e.title == 'No sync store (OSS): no sync actions or views are registered')"]},
 {'id':'remote-server-startup-contributions-sync-store-and-malicious','fixtures':['one-window-folder'],
  'config':{'product-configuration-sync-store-url':'https://sync.example/v1','product-extensions-gallery-service-url':'https://marketplace.example/_apis/public/gallery'},
  'state':{'user-data-sync-enablement-service':{'enabled':True},'marketplace-gallery-endpoint':{'malicious':['ms-python.python']},
           'extensions-profile-scanner-service':{'profile_extensions':{'ms-python.python':{'id':'ms-python.python','version':'2026.18.0','source':'gallery','pinned':False,'is_builtin':False},'redhat.vscode-yaml':{'id':'redhat.vscode-yaml','version':'1.0.0','source':'gallery','pinned':False,'is_builtin':False}}}},
  'choices':{'initial-remote-connection-health-contribution.start.environment':'unsupported-glibc','initial-remote-connection-health-contribution.start.allow':'cancel'},
  'steps':steps,
  'expect':["ctx.sync_actions_registered && ctx.remote_health == 'reopened-local'",
            "!('ms-python.python' in state['extensions-profile-scanner-service'].profile_extensions) && 'redhat.vscode-yaml' in state['extensions-profile-scanner-service'].profile_extensions",
            "calls['remote-authority-resolver-service.resolve-authority'] >= 2"]},
 {'id':'remote-server-startup-remote-health-variants','fixtures':['one-window-folder'],
  'choices':{'initial-remote-connection-health-contribution.start.environment':'unsupported-glibc'},
  'steps':[{'flow':'rs-startup-remote-browser','as':'a'}],
  'expect':["ctx.remote_health == 'unsupported-allowed'"]},
 {'id':'remote-server-startup-remote-health-failed','fixtures':['one-window-folder'],'config':{'security-workspace-trust-enabled':False},
  'choices':{'initial-remote-connection-health-contribution.start.environment':'failed'},
  'steps':[{'flow':'rs-startup-remote-browser','as':'a'},{'flow':'rs-startup-extensions-browser','as':'b'}],
  'expect':["ctx.remote_health == 'failed' && !has(ctx.trust_participant)"]},
]
PART={'components':comps,'interfaces':ifaces,'flows':flows,'scenarios':scen}

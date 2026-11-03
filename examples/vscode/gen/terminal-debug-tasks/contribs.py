from base import *
from code import find
DB='src/vs/workbench/contrib/debug/browser/'; DC='src/vs/workbench/contrib/debug/common/'; TB='src/vs/workbench/contrib/terminal/browser/'; TE='src/vs/workbench/contrib/terminal/electron-browser/'
TCO='src/vs/workbench/contrib/terminalContrib/'; TG='src/vs/workbench/contrib/testing/'; TK='src/vs/workbench/contrib/tasks/browser/'
DCON=DB+'debug.contribution.ts'; TGCON=TG+'browser/testing.contribution.ts'; TKCON=TK+'task.contribution.ts'
def ctor(f,cls_):
    c=find(f,r'^(export )?(abstract )?class %s\b'%cls_)
    r=method(f,'constructor',c)
    return S(f,*r) if r else S(f,c)
ex={c['id'] for c in COMPS}
# (feature, comp id, class, impl file, registration "file:line", summary, behavior-or-None)
CONTRIBS=[
 ('terminal','terminal-main-contribution','TerminalMainContribution',TB+'terminalMainContribution.ts',S(TB+'terminal.contribution.ts',64),'Waits for Restored, registers the terminal editor resolver and embedder terminals.',None),
 ('terminal','remote-terminal-backend-contribution','RemoteTerminalBackendContribution',TB+'remoteTerminalBackend.ts',S(TB+'terminal.contribution.ts',65),'Registers the remote backend only with a remote connection.',
   [{'if':"!input.has_remote",'then':[{'title':'No remote authority: nothing to register','source':S(TB+'remoteTerminalBackend.ts',43,49),'return':{}}]},{'call':'terminal-instance-service.did-register-backend','input':{'backend':'remote'}}]),
 ('terminal','local-terminal-backend-contribution','LocalTerminalBackendContribution',TE+'localTerminalBackend.ts',S(TE+'terminal.contribution.ts',29),'Creates LocalTerminalBackend and registers it with the instance service.',
   [{'call':'terminal-instance-service.did-register-backend','input':{'backend':'local'}}]),
 ('terminal','terminal-native-contribution','TerminalNativeContribution',TE+'terminalNativeContribution.ts',S(TE+'terminal.contribution.ts',30),'Sets the native window-count delegate and listens for open-file and OS resume events.',None),
 ('terminal','terminal-auto-replies-contribution','TerminalAutoRepliesContribution',TCO+'autoReplies/browser/terminal.autoReplies.contribution.ts',S(TCO+'autoReplies/browser/terminal.autoReplies.contribution.ts',58),'Installs terminal.integrated.autoReplies on every backend (pty host auto responder).',
   [{'foreach':"= config['terminal-integrated-auto-replies']",'as':'reply','index':'match','steps':[{'set':{'ctx.terminal_auto_reply_installed':"= vars.match"}}]}]),
 ('terminal','terminal-chat-enabler','TerminalChatEnabler',TCO+'chat/browser/terminalChatEnabler.ts',S(TCO+'chat/browser/terminal.chat.contribution.ts',21),'Sets the "has terminal chat agent" context key from the chat agents.',None),
 ('terminal','shell-integration-timeout-migration-contribution','ShellIntegrationTimeoutMigrationContribution',TCO+'chatAgentTools/browser/terminal.chatAgentTools.contribution.ts',S(TCO+'chatAgentTools/browser/terminal.chatAgentTools.contribution.ts',65),'Migrates the deprecated chat shell-integration timeout setting to terminal.integrated.shellIntegration.timeout.',None),
 ('terminal','output-location-migration-contribution','OutputLocationMigrationContribution',TCO+'chatAgentTools/browser/terminal.chatAgentTools.contribution.ts',S(TCO+'chatAgentTools/browser/terminal.chatAgentTools.contribution.ts',81),'Migrates the legacy "none" chat terminal output location to "chat".',None),
 ('terminal','chat-agent-tools-contribution','ChatAgentToolsContribution',TCO+'chatAgentTools/browser/terminal.chatAgentTools.contribution.ts',S(TCO+'chatAgentTools/browser/terminal.chatAgentTools.contribution.ts',185),'Registers the run-in-terminal and related chat agent tools.',None),
 ('terminal','agent-host-sandbox-forwarder','AgentHostSandboxForwarder',TCO+'chatAgentTools/browser/agentHostSandboxForwarder.ts',S(TCO+'chatAgentTools/browser/terminal.chatAgentTools.contribution.ts',186),'Forwards terminal sandbox settings to the agent host.',None),
 ('terminal','terminal-telemetry-contribution','TerminalTelemetryContribution',TCO+'telemetry/browser/terminalTelemetry.ts',S(TCO+'telemetry/browser/terminal.telemetry.contribution.ts',9),'Reports terminal creation telemetry.',None),
 ('terminal','terminal-wsl-recommendation-contribution','TerminalWslRecommendationContribution',TCO+'wslRecommendation/browser/terminal.wslRecommendation.contribution.ts',S(TCO+'wslRecommendation/browser/terminal.wslRecommendation.contribution.ts',78),'Recommends the WSL extension when wsl.exe is used on Windows.',None),
 ('debug','debug-status-contribution','DebugStatusContribution',DB+'debugStatus.ts',S(DCON,75),'Status bar entry with the selected launch configuration.',None),
 ('debug','debug-progress-contribution','DebugProgressContribution',DB+'debugProgress.ts',S(DCON,76),'Shows DAP progress events as window progress.',None),
 ('debug','debug-title-contribution','DebugTitleContribution',DB+'debugTitle.ts',S(DCON,78),'Puts the focused session state in the window title.',None),
 ('debug','debug-tool-bar','DebugToolBar',DB+'debugToolBar.ts',S(DCON,80),'The floating debug toolbar.',None),
 ('debug','debug-content-provider','DebugContentProvider',DC+'debugContentProvider.ts',S(DCON,81),'Text model provider for debug: sources loaded through the adapter.',None),
 ('debug','status-bar-color-provider','StatusBarColorProvider',DB+'statusbarColorProvider.ts',S(DCON,82),'Colors the status bar while debugging.',None),
 ('debug','disassembly-view-contribution','DisassemblyViewContribution',DB+'disassemblyView.ts',S(DCON,83),'Context key for whether the focused debugger supports disassembly.',None),
 ('debug','debug-lifecycle','DebugLifecycle',DC+'debugLifecycle.ts',S(DCON,84),'Registers the onBeforeShutdown veto listener.',None),
 ('debug','debug-chat-context-contribution','DebugChatContextContribution',DB+'debugChatIntegration.ts',S(DCON,85),'Debug context for chat.',None),
 ('debug','call-stack-editor-contribution','CallStackEditorContribution',DB+'callStackEditorContribution.ts',S(DCON,109),'Editor contribution: top stack frame decorations.',None),
 ('debug','breakpoint-editor-contribution','BreakpointEditorContribution',DB+'breakpointEditorContribution.ts',S(DCON,110),'Editor contribution: breakpoint gutter decorations and the breakpoint widget.',None),
 ('debug','debug-editor-contribution','DebugEditorContribution',DB+'debugEditorContribution.ts',S(DCON,111),'Editor contribution: debug hover, exception widget, inline values.',None),
 ('debug','repl-accessibility-announcer','ReplAccessibilityAnnouncer',DC+'replAccessibilityAnnouncer.ts',S(DCON,710),'Announces REPL output to screen readers.',None),
 ('debug','debug-watch-accessibility-announcer','DebugWatchAccessibilityAnnouncer',DC+'debugAccessibilityAnnouncer.ts',S(DCON,711),'Announces watch value changes to screen readers.',None),
 ('tasks','run-automatic-tasks','RunAutomaticTasks',TK+'runAutomaticTasks.ts',S(TKCON,49),'Tries to run folderOpen tasks once tasks are reconnected and on trust changes.',
   [{'call':'run-automatic-tasks.try-run-tasks','input':{'user_set_off':False}}]),
 ('tasks','task-status-bar-contributions','TaskStatusBarContributions',TKCON,S(TKCON,163),'Running tasks status bar entry.',None),
 ('tasks','user-tasks-global-action-contribution','UserTasksGlobalActionContribution',TKCON,S(TKCON,383),'Global "Open User Tasks" menu item.',None),
 ('tasks','task-registry-contribution','TaskRegistryContribution',TKCON,S(TKCON,462),'Waits for task definitions and problem matchers, then sets context keys.',[{'call':'problem-matcher-registry.on-ready'}]),
 ('testing','testing-content-provider','TestingContentProvider',TG+'common/testingContentProvider.ts',S(TGCON,142),'Text content for test output/message URIs.',None),
 ('testing','testing-peek-opener','TestingPeekOpener',TG+'browser/testingOutputPeek.ts',S(TGCON,143),'Opens the failure peek automatically when a run fails (testing.automaticallyOpenPeekView).',None),
 ('testing','testing-progress-trigger','TestingProgressTrigger',TG+'browser/testingProgressUiService.ts',S(TGCON,144),'Opens the testing view / results according to settings when runs start.',None),
 ('testing','testing-chat-agent-tool-contribution','TestingChatAgentToolContribution',TG+'common/testingChatAgentTool.ts',S(TGCON,145),'Registers the run-tests chat agent tool.',None),
 ('testing','testing-output-peek-controller','TestingOutputPeekController',TG+'browser/testingOutputPeek.ts',S(TGCON,147),'Editor contribution: the test output peek.',None),
 ('testing','testing-decorations','TestingDecorations',TG+'browser/testingDecorations.ts',S(TGCON,148),'Editor contribution: run/debug gutter decorations.',[{'call':'testing-decoration-service.sync-decorations'}]),
 ('testing','code-coverage-decorations','CodeCoverageDecorations',TG+'browser/codeCoverageDecorations.ts',S(TGCON,149),'Editor contribution: coverage decorations.',None),
 ('output','output-contribution','OutputContribution','src/vs/workbench/contrib/output/browser/output.contribution.ts',S('src/vs/workbench/contrib/output/browser/output.contribution.ts',835),'Registers the output actions (registerActions) at the Restored phase.',None),
]
EXTPTS={'terminal':[('terminal-contribution-service.on-terminal-extension-point',{'profiles':[]}),('terminal-quick-fix-service.on-quick-fixes-extension-point',{'selectors':[]})],
  'debug':[('adapter-manager.on-debuggers-extension-point',{'debuggers':[]}),('adapter-manager.on-breakpoints-extension-point',{'languages':[]}),('debug-visualizer-service.on-visualizers-extension-point',{'visualizers':[]})],
  'tasks':[('task-definition-registry.on-task-definitions-extension-point',{'types':[]}),('problem-matcher-registry.on-problem-matchers-extension-point',{'matchers':[]}),('problem-matcher-registry.on-problem-patterns-extension-point',{'patterns':[]})],
  'testing':[],'output':[]}
GROUP={'terminal':'terminal-contrib','debug':'debug-contrib','tasks':'tasks-contrib','testing':'testing-contrib','output':'output-contrib'}
starts={k:[] for k in GROUP}
for feat,cid,klass,f,reg,sm,beh in CONTRIBS:
    if cid not in ex:
        comp(cid,klass,GROUP[feat],sm,[CL(f,klass),reg]); ex.add(cid)
    else:
        for c in COMPS:
            if c['id']==cid and reg not in c['sources']: c['sources'].append(reg)
    b=[{'title':klass+' constructor','source':ctor(f,klass)}]+(beh or [])
    req=obj({'has_remote':bo(False)}) if cid=='remote-terminal-backend-contribution' else ob()
    iface(cid,'start','Workbench contribution startup ('+klass+'): '+sm,[ctor(f,klass),reg],behavior=b,request=req,response=ob())
    starts[feat].append(cid+'.start')
for feat,g in GROUP.items():
    steps=[{'call':s} for s in starts[feat]]
    steps+=[{'title':'Extension point handler runs once extensions are registered','call':ep,'input':inp} for ep,inp in EXTPTS[feat]]
    iface(g,'start-contributions','The workbench instantiates this module\'s registered contributions in their phases (registerWorkbenchContribution2 / registerEditorContribution), and its extension point handlers run once extensions are scanned.',
      [c['sources'][0] for c in COMPS if c['id']==g],behavior=steps,response=ob())

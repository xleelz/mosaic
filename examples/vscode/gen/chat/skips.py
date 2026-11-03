import json,re
u=json.load(open('uncovered.json'))
R={
'dev':"developer or internal command with no user-visible behavior",
'ui':"UI toggle: no state beyond the layout",
'voice':"not modeled: voice, speech-to-text, dictation and read-aloud features (audio capture/transcription/TTS) are outside the modeled chat request flows",
'agent':"not modeled: agent sessions, agent host, local model and cloud sandbox management UI; the agent host process is the agents area's and these session types are not modeled in this fragment",
'custom':"not modeled: AI customization management (prompt/instruction/agent/skill/hook files, plugins, marketplaces) outside the modeled request flows",
'setup':"not modeled: Copilot setup, sign-in, entitlement/plan management (the chat setup flow is not modeled in this fragment)",
'misc':"not modeled: tips, pet, feedback/survey, telemetry and onboarding UI with no effect on chat requests",
'content':"not modeled: actions on rendered response content (code blocks, anchors, references, terminal output, copy/insert/apply)",
'rest':"not modeled: chat command outside the modeled flows (submit/cancel/queue/new chat/tools/editing/import-export/inline chat); listed by group in notes/chat.md",
'svc_agent':"not modeled: agent session / agent host / remote agent host service; outside the modeled chat request flows",
'svc_voice':"not modeled: voice and speech service (audio capture, transcription, playback)",
'svc_custom':"not modeled: customization, plugin, prompt-file or automation service outside the modeled request flows",
'svc_ui':"not modeled: UI rendering/state service (rendering is out of scope)",
'svc_tel':"not modeled: telemetry, feedback, tips or pet service with no effect on chat requests",
'svc_rest':"not modeled: chat service not on the modeled request/tool/editing/inline paths; listed in notes/chat.md",
}
def cmd(e):
    n=e['name'];f=e['file'];nl=n.lower()
    if n in ('workbench.action.chat.toggleAgentMode','workbench.action.chat.switchToNextModel','workbench.action.chat.switchToNextPinnedModel','workbench.action.chatEditor.newChat','chatEditing.multidiff.explain'): return 'rest'
    if n=='workbench.action.chat.applyInEditor': return 'content'
    if n.startswith('_') or 'developer' in f.lower() or 'developer' in nl or re.search(r'inspect|logInput|logChat|debugAgentHost|profileAgentHost|stopAgentHostProfile|openStorageFolder|simulate|resetOnboarding|resetGrowth|resetCopilotHarness|resetSpeechToTextIntro|resetDismissedTips|exportAgentTracesDB|NetworkDiagnostics|generateDebugReport|restartLocalAgentHost|OpenAgentHostStateFile|TrustedCA',n): return 'dev'
    if re.search(r'agentsVoice|voice|speech|Speech|Voice|dictation|Dictation|ReadAloud|readChatResponseAloud|Listening|keywordActivation|transcript',n+f): return 'voice'
    if re.search(r'agentSession|AgentSession|agentHost|AgentHost|localModel|LocalModel|cloudSandbox|MissionControl|agentsWindow|AgentsWindow|tunnelHost|agentsParallelWork|unifiedQuickAccess|UnifiedAgentsBar|Codex|showAgentSessionsQuickAccess|showCommandsQuickAccess|showFilesQuickAccess|openSessionIn|pickAgentSession|clearHistory|chatSessions/|continueInCopilot|ExportAgentHostDebugLogs|openAgentHostChat|openAgentDebugPanel|AgentDebugLog',n+f): return 'agent'
    if re.search(r'aiCustomization|Plugin|plugin|promptSyntax|configure\.|Instructions|generateAgent|generatePrompt|generateSkill|generateHook|configureToolSets|ConfigureAgents|createPlugin|ListExtensionPromptFiles|_listExtensionPromptFiles|installRecommendation|agentPlugins',n+f): return 'custom'
    if re.search(r'chatSetup|Setup|SignIn|upgradePlan|AdditionalSpend|Quota|showExtensionsUsingCopilot|configureCodeCompletions|tryPromo|manageSettings|openFeatureSettings',n+f): return 'setup'
    if re.search(r'Tip|tip|pet\.|chatPet|Helpful|reportIssue|FeedbackSurvey|flushUserInteraction|planReviewFeedback|Telemetry',n+f): return 'misc'
    if re.search(r'codeblock|CodeBlock|chatInlineAnchorWidget|chatReferencesContentPart|chatResourceGroupWidget|chatTerminalToolProgressPart|copy|Copy|insertIntoNotebook|CompareEdits|CompareBlock|openLinkWith|KatexMath|chatImageUtils|toolOutput',n+f): return 'content'
    if re.search(r'focus|Focus|toggle|Toggle|show|Show|hide|Hide|next|Next|previous|Previous|Prev|find|Find|collapse|Orientation|Sidebar|sortBy|filter|Picker|picker|ToSide|InEditor|InNewWindow|InSidebar|openChat|chat\.open$|chat\.toggle$|newChatWindow|quickchat|QuickChat|quickChat|Placeholder|accessib|Accessib|viewChanges|reviewChanges|explain|openFileInDiff|switchToNext|chatEditor\.newChat|clearSearchResults|ContextUsage|selectRepository|dismiss|Dismiss',n+f): return 'ui'
    return 'rest'
def svc(e):
    f=e['file'];n=e['name']
    if re.search(r'agentSessions|remoteAgentHost|AgentHost|electron-browser',f+n): return 'svc_agent'
    if re.search(r'agentsVoice|voice|Voice|speech|Speech|Dictation|Mic|Tts',f+n): return 'svc_voice'
    if re.search(r'aiCustomization|plugins|promptSyntax|automations|Customization|Plugin|Prompts',f+n): return 'svc_custom'
    if re.search(r'Telemetry|OTel|Survey|Tip|Pet|Feedback|Stats',f+n): return 'svc_tel'
    if re.search(r'widget/|Widget|Accessibility|Paste|Carousel|Hover|Layout|Pill|Notice|Presenter|Anchor|StateCache|CodeCompare|Status|QuickChat|CodeBlockContext|Attachment',f+n): return 'svc_ui'
    return 'svc_rest'
out=[];cnt={}
for e in u:
    c=cmd(e) if e['kind']=='vscode-command' else svc(e)
    cnt[c]=cnt.get(c,0)+1
    out.append({'kind':e['kind'],'name':e['name'],'file':e['file'],'line':e['line'],'reason':R[c],'_g':c})
json.dump(out,open('skips_g.json','w'),indent=1)
json.dump([{k:v for k,v in o.items() if k!='_g'} for o in out],open('/home/lbethay/workplace/mosaic/examples/vscode/skips/chat.json','w'),indent=1)
print(cnt)
for g in ['rest','svc_rest','ui']:
    print(g,[o['name'] for o in out if o['_g']==g])

"""Generate contrib.yaml and contribflows.yaml: one component per chat-area workbench/editor
contribution, a constructor interface narrating the constructor's registrations (quoted code
lines), the extension-point handlers, and the startup entry that instantiates them in phase order."""
import json, os, re, yaml
ROOT = '/home/lbethay/.cache/mosaic-bench/vscode-1.144.0'
HERE = os.path.dirname(os.path.abspath(__file__))
inv = [e for e in json.load(open(os.path.join(HERE, '..', '..', 'inventory.json')))['entries'] if e.get('area') == 'chat']
CUSTOM = {'ChatSlashCommandsContribution'}       # constructor modeled by hand in ext.yaml
RENAME = {'InlineChatController': 'inline-chat-controller'}
C = 'src/vs/workbench/contrib/chat/'
dirs = ['src/vs/workbench/contrib/chat', 'src/vs/workbench/contrib/inlineChat', 'src/vs/workbench/contrib/agentsVoice', 'src/vs/workbench/services/chat']
allfiles = []
for d in dirs:
    for r, _, fs in os.walk(os.path.join(ROOT, d)):
        if '/test' not in r:
            allfiles += [os.path.join(r, f) for f in fs if f.endswith('.ts')]
cache = {}
def L(p):
    if p not in cache:
        cache[p] = open(p).read().split('\n')
    return cache[p]
def findclass(name, pref):
    pat = re.compile(r'^(export )?(abstract )?class ' + re.escape(name) + r'\b')
    for p in [os.path.join(ROOT, pref)] + allfiles:
        ls = L(p)
        for i, l in enumerate(ls):
            if pat.match(l):
                ctor = None
                for j in range(i + 1, min(len(ls), i + 400)):
                    if re.match(r'^(export )?(abstract )?class ', ls[j]):
                        break
                    if re.match(r'^\t(public |private |protected )?constructor\(', ls[j]):
                        k = j
                        while k < len(ls) - 1 and not ls[k].startswith('\t}') and not ls[k].rstrip().endswith('{ }'):
                            k += 1
                        ctor = (j + 1, k + 1)
                        break
                return os.path.relpath(p, ROOT), i + 1, ctor, ls
    return None
def kebab(n):
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', n)
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:64].rstrip('-')
INTERESTING = re.compile(r'register|\.bindTo\(|\.set\(|executeCommand|storageService\.|setHandler|onDid|onWill|autorun|createInstance')
comps, ifaces, steps = [], [], {}
order = ['BlockStartup', 'BlockRestore', 'AfterRestored', 'Eventually', 'editor-contribution', 'contribution-registry', 'other']
for e in inv:
    if e['kind'] != 'workbench-contribution':
        continue
    reg = L(os.path.join(ROOT, e['file']))[e['line'] - 1]
    m = re.search(r'WorkbenchPhase\.(\w+)', reg)
    phase = m.group(1) if m else (e.get('via') if e.get('via') in ('editor-contribution', 'contribution-registry') else 'other')
    cf, cl, ctor, ls = findclass(e['name'], e['file'])
    cid = RENAME.get(e['name'], kebab(e['name']))
    if e['name'] not in RENAME:
        comps.append({'id': cid, 'name': e['name'], 'kind': 'module', 'layer': 'ai', 'parent': 'inline-chat' if 'inlineChat' in e['file'] else 'chat',
                      'sources': [f"{cf}:{cl}", f"{e['file']}:{e['line']}"], 'summary': f"Workbench contribution {e['name']} ({'phase ' + phase if m else phase}).", 'attributes': {'owner': 'chat'}})
    steps.setdefault(phase, []).append({'title': f"{e['name']} ({phase})", 'source': f"{e['file']}:{e['line']}", 'call': f"{cid}.constructor"})
    if e['name'] in CUSTOM:
        continue
    beh = []
    if ctor:
        a, b = ctor
        body = [(n, ls[n - 1].strip()) for n in range(a, b + 1)]
        picks = [(n, t) for n, t in body if INTERESTING.search(t) and not t.startswith(('@', '//', '}', ')', ']')) and len(t) >= 20 and not t.startswith('registerTriggers')][:5]
        if not picks:
            picks = [(n, t) for n, t in body if t and not t.startswith('@') and not t.startswith('//') and t not in ('super();', ') {', '}', '{') and 'constructor(' not in t][:2]
        for n, t in picks:
            beh.append({'title': t[:140], 'source': f"{cf}:{n}"})
        isrc = [f"{cf}:{a}-{b}"] if b > a else [f"{cf}:{a}"]
    else:
        isrc = [f"{cf}:{cl}"]
        beh.append({'title': f"{e['name']} has no constructor of its own; the base class constructor runs", 'source': f"{cf}:{cl}"})
    beh.append({'return': {'started': True}})
    ifaces.append({'component': cid, 'name': 'constructor', 'kind': 'function', 'summary': f"{e['name']} constructor: the contribution's startup registrations (narrated from the code).",
                   'sources': isrc, 'request': {'type': 'object'}, 'behavior': beh})
ids = {c['id'] for c in comps}
ep = [
 ('chat-extension-point-handler', 'chatParticipants', C + 'browser/chatParticipant.contribution.ts:106', None),
 ('language-model-tools-extension-point-handler', 'languageModelTools', C + 'common/tools/languageModelToolsContribution.ts:42', None),
 ('language-model-tools-extension-point-handler', 'languageModelToolSets', C + 'common/tools/languageModelToolsContribution.ts:152', None),
 ('chat-views-welcome-handler', 'chatViewsWelcome', C + 'browser/viewsWelcome/chatViewsWelcomeHandler.ts:45', C + 'browser/viewsWelcome/chatViewsWelcomeHandler.ts:61'),
 ('chat-context-contribution', 'chatContext', C + 'browser/contextContrib/chatContext.contribution.ts:21', C + 'browser/contextContrib/chatContext.contribution.ts:59'),
 ('language-models-service', 'languageModelChatProviders', C + 'common/languageModels.ts:1047', C + 'common/languageModels.ts:1318'),
 ('chat-sessions-service', 'chatSessions', C + 'browser/chatSessions/chatSessions.contribution.ts:65', C + 'browser/chatSessions/chatSessions.contribution.ts:384'),
 ('chat-output-renderer-service', 'chatOutputRenderers', C + 'browser/chatOutputItemRenderer.ts:294', C + 'browser/chatOutputItemRenderer.ts:105'),
 ('extension-agent-plugin-discovery', 'chatPlugins', C + 'common/plugins/agentPluginServiceImpl.ts:1239', C + 'common/plugins/agentPluginServiceImpl.ts:1292'),
]
comps += [
 {'id': 'extension-agent-plugin-discovery', 'name': 'ExtensionAgentPluginDiscovery', 'kind': 'module', 'layer': 'ai', 'parent': 'chat', 'sources': [C + 'common/plugins/agentPluginServiceImpl.ts:1267'], 'summary': 'Discovers agent plugins contributed by extensions (chatPlugins extension point).', 'attributes': {'owner': 'chat'}},
]
epsteps = []
for comp, epn, line, handler in ep:
    name = 'handle-' + kebab(epn) + '-extension-point'
    beh = [{'title': f"setHandler for '{epn}': read every extension's contributions, register the added and dispose the removed", 'source': handler or line}, {'return': {'handled': True}}]
    ifaces.append({'component': comp, 'name': name, 'kind': 'event', 'summary': f"Handles the '{epn}' extension point.", 'sources': [line] + ([handler] if handler else []), 'request': {'type': 'object'}, 'behavior': beh})
    epsteps.append({'title': f"Extension point {epn}", 'source': line, 'call': f"{comp}.{name}"})
allsteps = [s for ph in order for s in steps.get(ph, [])]
ifaces.append({'component': 'chat', 'name': 'instantiate-contributions', 'kind': 'function',
               'summary': "Workbench startup: the chat area's registered workbench and editor contributions are instantiated in phase order (BlockStartup, BlockRestore, AfterRestored, Eventually), then the chat extension points' handlers run.",
               'sources': [C + 'browser/chat.shared.contribution.ts:3360-3428'], 'request': {'type': 'object'},
               'behavior': allsteps + epsteps + [{'return': {'instantiated': len(allsteps)}}]})
yaml.safe_dump({'components': comps, 'interfaces': ifaces}, open(os.path.join(HERE, 'contrib.yaml'), 'w'), sort_keys=False, width=200)
yaml.safe_dump({'flows': [{'id': 'chat-contributions-startup', 'name': 'Chat contributions at workbench startup',
   'description': 'The workbench contribution registry (workbench-shell) instantiates every chat contribution by phase; the extension point handlers then see the contributed participants, tools, providers and session types.',
   'entry': {'caller': 'workbench', 'interface': 'chat.instantiate-contributions'}, 'sources': [C + 'browser/chat.shared.contribution.ts:3360']}],
 'scenarios': [{'id': 'chat-contributions-startup-all', 'flow': 'chat-contributions-startup', 'fixtures': ['one-window-folder'],
   'state': {'chat-slash-command-service': {'commands': {}}},
   'expect': [f"result.ok && result.value.instantiated == {len(allsteps)}",
              "calls['chat-setup-contribution.constructor'] == 1 && calls['inline-chat-controller.constructor'] == 1",
              f"trace.filter(e, e.type == 'call.start' && e.interface.endsWith('.constructor')).size() == {len(allsteps)}",
              "trace.exists(e, e.type == 'call.start' && e.interface == 'language-models-service.handle-language-model-chat-providers-extension-point')",
              "'clear' in state['chat-slash-command-service@w1'].commands && 'rename' in state['chat-slash-command-service@w1'].commands"]}]},
 open(os.path.join(HERE, 'contribflows.yaml'), 'w'), sort_keys=False, width=200)
print(len(comps), 'components', len(ifaces), 'interfaces')

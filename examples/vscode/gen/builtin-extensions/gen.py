"""Generator for the builtin-extensions fragment (reconciliation round).

Inputs: the hand-written parts (common.yaml, deep_git.yaml, deep_ts.yaml, deep_md.yaml,
scenarios.yaml), data.json (inventory commands with titles and registration sites, from
gather.py), git_cmds.json (git command method bodies, from analyze_git.py), and exthost's
fragment for the vscode-api contracts. Output: fragments/builtin-extensions.yaml and
skips/builtin-extensions.json.
"""
import json, re, os, copy, yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = '/home/lbethay/.cache/mosaic-bench/vscode-1.144.0'
OUT = os.path.abspath(os.path.join(HERE, '..', '..'))
data = json.load(open(f'{HERE}/data.json'))
cmds, acts = data['cmds'], data['acts']
gitc = json.load(open(f'{HERE}/git_cmds.json'))
exthost = yaml.safe_load(open(f'{OUT}/fragments/exthost.yaml'))


def slug(cid):
    return ('cmd-' + cid.lower().replace('.', '-').replace('_', '-'))[:64]


def load(p):
    return yaml.safe_load(open(f'{HERE}/{p}'))


def kebab(s):
    return re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', s).lower()


doc = {'configs': [], 'schemas': [], 'components': [], 'interfaces': [], 'flows': [], 'scenarios': [], 'fixtures': []}
for p in ['common.yaml', 'deep_git.yaml', 'deep_ts.yaml', 'deep_md.yaml', 'scenarios.yaml']:
    part = load(p)
    for k in doc:
        doc[k] += part.get(k, []) or []

PKG = {c['id']: f"{c['file']}:{c['line']}" for c in cmds}
SITE = {c['id']: c['site'] for c in cmds}
TITLE = {c['id']: (c['title'] or c['id']).replace('\n', ' ') for c in cmds}

SKIP = {
    'notebook.cellOutput.copy': 'an entry another area owns (notebook-webview): ipynb only contributes it to menus; the handler is registered by the workbench notebook contribution (cellOutputActions.ts)',
    'notebook.cellOutput.openInTextEditor': 'an entry another area owns (notebook-webview): ipynb only contributes it to menus; the handler is registered by the workbench notebook contribution (cellOutputActions.ts)',
    'notebook.cellOutput.addToChat': 'an entry another area owns (notebook-webview): ipynb only contributes it to menus; the handler is registered by the workbench notebook chat contribution (notebook.chat.contribution.ts)',
    'github.copilot.debug.generateInlineEditTests': 'not an entry point: contributed in package.json but never registered in the copilot sources at 1.144.0 (no handler exists)',
    'github.copilot.chat.clearTemporalContext': 'not an entry point: contributed in package.json but never registered in the copilot sources at 1.144.0 (no handler exists)',
}

EXT_ID = {'copilot': 'GitHub.copilot-chat'}


def ext_id(d):
    return EXT_ID.get(d, 'vscode.' + d)


def comp_for(c):
    e = c['ext']
    if e == 'git':
        return 'git-extension' if c['id'].startswith('git.api.') else 'git-command-center'
    if e == 'typescript-language-features':
        return 'typescript-command-manager'
    if e == 'markdown-language-features':
        if c['site'] is None or 'extension.shared.ts' in (c['site'] or ''):
            return 'markdown-editor-provider'
        return 'markdown-command-manager'
    if e == 'copilot':
        return 'copilot-chat-extension'
    return e + '-extension'


ACT = {
    'configuration-editing': 'extensions/configuration-editing/src/configurationEditingMain.ts:12',
    'copilot': 'extensions/copilot/src/extension/extension/vscode-node/extension.ts:38',
    'css-language-features': 'extensions/css-language-features/client/src/node/cssClientMain.ts:15',
    'debug-auto-launch': 'extensions/debug-auto-launch/src/extension.ts:63',
    'debug-server-ready': 'extensions/debug-server-ready/src/extension.ts:327',
    'emmet': 'extensions/emmet/src/node/emmetNodeMain.ts:12',
    'extension-editing': 'extensions/extension-editing/src/extensionEditingMain.ts:11',
    'git-base': 'extensions/git-base/src/extension.ts:12',
    'github': 'extensions/github/src/extension.ts:22',
    'grunt': 'extensions/grunt/src/main.ts:357',
    'gulp': 'extensions/gulp/src/main.ts:399',
    'html-language-features': 'extensions/html-language-features/client/src/node/htmlClientMain.ts:18',
    'ipynb': 'extensions/ipynb/src/ipynbMain.node.ts:10',
    'jake': 'extensions/jake/src/main.ts:332',
    'json-language-features': 'extensions/json-language-features/client/src/node/jsonClientMain.ts:20',
    'merge-conflict': 'extensions/merge-conflict/src/mergeConflictMain.ts:9',
    'mermaid-markdown-features': 'extensions/mermaid-markdown-features/src/extension.ts:13',
    'npm': 'extensions/npm/src/npmMain.ts:26',
    'php-language-features': 'extensions/php-language-features/src/phpMain.ts:13',
    'references-view': 'extensions/references-view/src/extension.ts:13',
    'search-result': 'extensions/search-result/src/extension.ts:20',
    'simple-browser': 'extensions/simple-browser/src/extension.ts:50',
    'terminal-suggest': 'extensions/terminal-suggest/src/terminalSuggestMain.ts:242',
    'tunnel-forwarding': 'extensions/tunnel-forwarding/src/extension.ts:77',
}
DEEP_EXT = {'git', 'typescript-language-features', 'markdown-language-features'}
MODEL_EXTS = {'emmet', 'references-view', 'github', 'npm', 'debug-auto-launch'}


def act_range(d):
    lines = open(f'{ROOT}/extensions/{d}/package.json').read().split('\n')
    s = next(i for i, l in enumerate(lines) if '"activationEvents"' in l)
    e = next(i for i in range(s, len(lines)) if lines[i].strip().startswith(']'))
    return f'extensions/{d}/package.json:{s+1}-{e+1}'


def snippet(site, maxlen=14):
    f, l = site.rsplit(':', 1)
    l = int(l)
    lines = open(f'{ROOT}/{f}').read().split('\n')
    end = l
    depth = 0
    for i in range(l - 1, min(l - 1 + maxlen, len(lines))):
        depth += lines[i].count('(') + lines[i].count('{') - lines[i].count(')') - lines[i].count('}')
        end = i + 1
        if depth <= 0:
            break
    return f, l, end, '\n'.join(lines[l - 1:end])


# ------------------------------------------------------------------ macros in hand-written parts
MACROS = {
    'GOTO_PROJECT': [
        {'title': 'Only with an active JS/TS editor', 'source': 'extensions/typescript-language-features/src/commands/goToProjectConfiguration.ts:21-22',
         'choice': 'active_js_ts_editor', 'default': 'present', 'options': {
             'present': [{'call': 'lazy-client-host.get-value'},
                         {'title': 'openProjectConfigForFile asks tsserver for projectInfo, then opens the config file',
                          'source': 'extensions/typescript-language-features/src/commands/goToProjectConfiguration.ts:23',
                          'call': 'typescript-service-client.execute', 'input': {'command': 'projectInfo', 'args': {}, 'token': {'canceled': False}}}],
             'absent': [{'return': {'opened': False}}]}}],
    'SOURCE_ACTION_SORT': [{'title': 'Run the sortImports source action', 'source': 'extensions/typescript-language-features/src/languageFeatures/organizeImports.ts:176-179',
                            'call': 'vscode-api.commands-execute-command', 'input': {'command_id': 'editor.action.sourceAction', 'args': [{'kind': 'source.sortImports', 'apply': 'first'}]}}],
    'SOURCE_ACTION_UNUSED': [{'title': 'Run the removeUnusedImports source action', 'source': 'extensions/typescript-language-features/src/languageFeatures/organizeImports.ts:176-179',
                              'call': 'vscode-api.commands-execute-command', 'input': {'command_id': 'editor.action.sourceAction', 'args': [{'kind': 'source.removeUnusedImports', 'apply': 'first'}]}}],
    'TSGO_UPDATE': [
        {'set': {'vars.enable': "= input.command_id.endsWith('enableTsgo')"}},
        {'title': 'The TypeScript Go extension is not installed (no fixture installs it)', 'source': 'extensions/typescript-language-features/src/commands/useTsgo.ts:48-57',
         'call': 'vscode-api.window-show-error-message', 'input': {'message': 'The TypeScript Go extension is not installed.', 'items': ['Open on GitHub']}},
        {'if': "config['js-ts-experimental-use-tsgo'] == vars.enable", 'then': [
            {'title': 'Already set', 'source': 'extensions/typescript-language-features/src/commands/useTsgo.ts:65-68', 'return': {'updated': False}}]},
        {'title': 'Update js/ts.experimental.useTsgo', 'source': 'extensions/typescript-language-features/src/commands/useTsgo.ts:91',
         'call': 'vscode-api.workspace-configuration-update', 'input': {'section': 'js/ts.experimental.useTsgo', 'value': '= vars.enable', 'global': True}},
        {'return': {'updated': True}}],
    'INSERT_LINK': [
        {'title': 'Only with an active text editor', 'source': 'extensions/markdown-language-features/src/commands/insertResource.ts:20-23',
         'choice': 'active_editor', 'default': 'present', 'options': {'present': [], 'absent': [{'return': {'inserted': False}}]}},
        {'title': 'Pick files with the open dialog', 'source': 'extensions/markdown-language-features/src/commands/insertResource.ts:25-32',
         'call': 'vscode-api.window-show-open-dialog', 'input': {'canSelectMany': True}},
        {'title': 'createInsertLinkEdit, applied to the active editor', 'source': 'extensions/markdown-language-features/src/commands/insertResource.ts:77-82',
         'return': {'inserted': True}}],
}

# ------------------------------------------------------------------ git command behaviors
READ_ONLY = {'getRefs', 'getCommit', 'getStashes', 'getBranch', 'getWorktrees', 'getWorktreeDetails', 'getRemoteRefs',
             'getCommitTemplate', 'getEmptyTree', 'diffBetweenWithStats', 'exec', 'findTrackingBranches'}
SUB = {'fetchDefault': 'fetch', 'fetchAll': 'fetch', 'fetchPrune': 'fetch', 'fetch': 'fetch', 'pull': 'pull', 'pullWithRebase': 'pull',
       'pullFrom': 'pull', 'sync': 'pull', 'checkout': 'checkout', 'revert': 'reset', 'rm': 'rm', 'move': 'mv', 'mergeAbort': 'merge',
       'merge': 'merge', 'rebase': 'rebase', 'rebaseAbort': 'rebase', 'cherryPick': 'cherry-pick', 'cherryPickAbort': 'cherry-pick',
       'addRemote': 'remote', 'removeRemote': 'remote', 'popStash': 'stash', 'applyStash': 'stash', 'getStashes': 'stash',
       'deleteTag': 'tag', 'renameBranch': 'branch', 'getRefs': 'for-each-ref', 'getCommit': 'show', 'getBranch': 'symbolic-ref',
       'getWorktrees': 'worktree', 'getWorktreeDetails': 'worktree', 'deleteWorktree': 'worktree', 'getRemoteRefs': 'ls-remote',
       'getCommitTemplate': 'cat-file', 'getEmptyTree': 'hash-object', 'diffBetweenWithStats': 'diff', 'exec': 'rev-parse',
       'findTrackingBranches': 'for-each-ref', 'ignore': 'check-ignore', 'closeDiffEditors': None}
THIS = {'_push': 'push', '_sync': 'pull', '_checkout': 'checkout', '_branch': 'branch', '_deleteBranch': 'branch', '_stash': 'stash',
        '_createTag': 'tag', '_createWorktree': 'worktree', '_stashDrop': 'stash', '_cleanAll': 'clean', '_cleanTrackedChanges': 'checkout',
        '_cleanUntrackedChanges': 'clean', '_revertChanges': 'checkout', '_unstageChanges': 'reset', '_stageChanges': 'hash-object',
        'runGitMerge': 'merge', 'publish': 'push'}
COMMIT_OPTS = {
    'git.commitAmend': {'amend': True}, 'git.commitSigned': {}, 'git.commitStaged': {}, 'git.commitStagedSigned': {},
    'git.commitStagedAmend': {'amend': True}, 'git.commitAll': {'all': True}, 'git.commitAllSigned': {'all': True},
    'git.commitAllAmend': {'all': True, 'amend': True}, 'git.commitNoVerify': {'no_verify': True},
    'git.commitStagedNoVerify': {'no_verify': True}, 'git.commitStagedSignedNoVerify': {'no_verify': True},
    'git.commitAmendNoVerify': {'amend': True, 'no_verify': True}, 'git.commitSignedNoVerify': {'no_verify': True},
    'git.commitStagedAmendNoVerify': {'amend': True, 'no_verify': True}, 'git.commitAllNoVerify': {'all': True, 'no_verify': True},
    'git.commitAllSignedNoVerify': {'all': True, 'no_verify': True}, 'git.commitAllAmendNoVerify': {'all': True, 'amend': True, 'no_verify': True},
    'git.commitEmpty': {'empty': True}, 'git.commitEmptyNoVerify': {'empty': True, 'no_verify': True},
}
WIN = {'showWarningMessage': 'window-show-warning-message', 'showErrorMessage': 'window-show-error-message',
       'showInformationMessage': 'window-show-information-message', 'showQuickPick': 'window-show-quick-pick',
       'showInputBox': 'window-show-input-box', 'showOpenDialog': 'window-show-open-dialog',
       'showTextDocument': 'window-show-text-document', 'withProgress': 'window-with-progress', 'createTerminal': 'window-create-terminal'}
EXEC_CMDS = set()  # command ids whose behavior goes through commands.executeCommand


def git_behavior(cid):
    g = gitc[cid]
    src = f"extensions/git/src/commands.ts:{g['start']}-{g['end']}"
    title = TITLE.get(cid, cid)
    if cid in COMMIT_OPTS:
        opts = {'amend': False, 'all': False, 'empty': False, 'no_verify': False}
        opts.update(COMMIT_OPTS[cid])
        return [{'title': f"{g['method']}: commitWithAnyInput with {', '.join(k for k, v in COMMIT_OPTS[cid].items() if v) or 'default'} options",
                 'source': src, 'call': 'git-command-center.commit-with-any-input', 'input': opts}]
    steps = []
    for kind, name in g['hits']:
        st = None
        if kind == 'repo':
            if name == 'add':
                st = {'call': 'git-repository.add', 'input': {'resources': [], 'update': False}}
            elif name == 'refresh':
                st = {'call': 'git-repository.refresh'}
            elif name in SUB and SUB[name] is None:
                continue
            else:
                st = {'call': 'git-repository.operation', 'input': {'operation': name, 'subcommand': SUB.get(name, kebab(name)), 'read_only': name in READ_ONLY}}
        elif kind == 'this' and name in THIS:
            st = {'call': 'git-repository.operation', 'input': {'operation': name.lstrip('_'), 'subcommand': THIS[name], 'read_only': False}}
        elif kind == 'this' and name in ('pickRef', 'pickStash'):
            st = {'call': 'vscode-api.window-show-quick-pick', 'input': {'placeholder': title}}
        elif kind == 'this' and name == 'promptForBranchName':
            st = {'call': 'vscode-api.window-show-input-box', 'input': {'placeholder': 'Branch name'}}
        elif kind == 'model':
            if name == 'getRepository':
                st = {'call': 'git-model.get-repository', 'input': {'uri': 'file:///work/app'}}
            elif name in ('openRepository', 'openParentRepository'):
                st = {'call': 'git-model.open-repository', 'input': {'repo_path': '/work/app'}}
            elif name == 'close':
                st = {'call': 'git-model.close', 'input': {'root': '/work/app'}}
            else:
                continue
        elif kind == 'window' and name in WIN:
            api = WIN[name]
            if api.endswith('-message'):
                st = {'call': f'vscode-api.{api}', 'input': {'message': title}}
            else:
                st = {'call': f'vscode-api.{api}', 'input': {'title': title}}
        elif kind == 'exec':
            st = {'call': 'vscode-api.commands-execute-command', 'input': {'command_id': name, 'args': []}}
            EXEC_CMDS.add(cid)
        else:
            continue
        st['on_error'] = 'continue' if st['call'].startswith('vscode-api.window-show') else 'propagate'
        if st['on_error'] == 'propagate':
            del st['on_error']
        steps.append(st)
        if len(steps) == 3:
            break
    if not steps:
        return [{'title': f"{g['method']}: {title} (editor, clipboard or view work through the window API)", 'source': src}]
    steps[0]['title'] = f"{g['method']}: {title}"
    steps[0]['source'] = src
    return steps


# ------------------------------------------------------------------ command-level extension behaviors
API_PATTERNS = [
    (r'window\.(showQuickPick|showInputBox|showOpenDialog|showTextDocument|withProgress|createTerminal|showInformationMessage|showWarningMessage|showErrorMessage)\(', 'window'),
    (r'env\.openExternal\(', 'openExternal'),
    (r'tasks\.executeTask\(', 'executeTask'),
    (r'debug\.startDebugging\(', 'startDebugging'),
]


def level_behavior(c, comp):
    site = c['site']
    f, l, end, text = snippet(site)
    call = re.search(r"registerCommand\([^,]+,\s*(?:async\s*)?(?:\([^)]*\)\s*=>\s*\{?\s*)?(?:return\s+|await\s+)?([\w.]+)", text)
    fn = call.group(1) if call else 'the registered callback'
    steps = []
    if c['ext'] == 'emmet':
        steps.append({'title': 'validate(): an active text editor is required', 'source': 'extensions/emmet/src/util.ts:107-117', 'call': 'emmet-extension.validate', 'as': 'v'})
        steps.append({'if': '!vars.v.value.valid', 'then': [{'return': {'ran': False}}]})
    steps.append({'title': f"{c['id']}: {fn}", 'source': f'{f}:{l}-{end}' if end > l else f'{f}:{l}',
                  'set': {'state.last_command': c['id']}})
    for pat, kind in API_PATTERNS:
        m = re.search(pat, text)
        if not m:
            continue
        if kind == 'window':
            api = WIN[m.group(1)]
            steps.append({'call': f'vscode-api.{api}', 'input': {'message': TITLE[c['id']]} if api.endswith('-message') else {'title': TITLE[c['id']]}, 'on_error': 'continue'})
        elif kind == 'openExternal':
            steps.append({'call': 'vscode-api.env-open-external', 'input': {'target': 'https://github.com'}})
        elif kind == 'executeTask':
            steps.append({'call': 'vscode-api.tasks-execute-task', 'input': {'task': c['id']}})
        elif kind == 'startDebugging':
            steps.append({'call': 'vscode-api.debug-start-debugging', 'input': {'name': c['id']}})
    steps.append({'return': {'ran': True}})
    return steps


# ------------------------------------------------------------------ assemble
deep_names = {i['component'] + '.' + i['name'] for i in doc['interfaces']}
for i in doc['interfaces']:
    i['sources'] = [PKG[s[4:]] if isinstance(s, str) and s.startswith('PKG:') else s for s in i.get('sources', [])]
    if isinstance(i.get('behavior'), str):
        i['behavior'] = copy.deepcopy(MACROS[i['behavior']])

act_exts = sorted({a['file'].split('/')[1] for a in acts})
cmd_exts = sorted({c['ext'] for c in cmds})
level_exts = sorted((set(act_exts) | set(cmd_exts)) - DEEP_EXT)

new_components, new_ifaces, new_flows = [], [], []
routers = {}   # component -> {command_id: iface}
modeled = {}   # command_id -> handler interface (registered in commands-registry)
skips, used = [], set()
git_targets = []
for c in cmds:
    if c['id'] in SKIP:
        skips.append({'kind': 'extension-command', 'name': c['id'], 'file': c['file'], 'line': c['line'], 'reason': SKIP[c['id']]})
        continue
    comp = comp_for(c)
    name = slug(c['id'])
    k = 2
    while f'{comp}.{name}' in used:
        name = slug(c['id'])[:61] + '-' + str(k)
        k += 1
    used.add(f'{comp}.{name}')
    iid = f'{comp}.{name}'
    if comp == 'git-command-center':
        git_targets.append(iid)
    else:
        routers.setdefault(comp, {})[c['id']] = iid
    if iid in deep_names:
        modeled[c['id']] = 'git-command-center.run-command' if comp == 'git-command-center' else iid
        continue
    srcs = [f"{c['file']}:{c['line']}"]
    if c['site'] and not c['site'].startswith(c['file']):
        srcs.append(c['site'])
    title = TITLE[c['id']]
    beh = None
    if comp == 'git-command-center':
        g = gitc[c['id']]
        srcs = [f"{c['file']}:{c['line']}", f"extensions/git/src/commands.ts:{g['start']}-{g['end']}"]
        beh = git_behavior(c['id'])
        summ = f"{c['id']}: {title}. CommandCenter.{g['method']}."
    elif comp == 'markdown-editor-provider':
        summ = f"{c['id']}: {title}. Registered by registerMarkdownEditorCommands; calls MarkdownEditorProvider.executeCommand, which forwards it to the active Markdown editor webview and ignores it when none is active."
        srcs.append('extensions/markdown-language-features/src/extension.shared.ts:94-105')
        beh = [{'title': 'provider.executeCommand(commandId)', 'source': 'extensions/markdown-language-features/src/extension.shared.ts:101',
                'call': 'markdown-editor-provider.execute-command', 'input': {'command': c['id']}}]
    elif c['ext'] in MODEL_EXTS and c['site']:
        summ = f"{c['id']}: {title}"
        beh = level_behavior(c, comp)
    else:
        summ = f"{c['id']}: {title}" if title else c['id']
    iface = {'component': comp, 'name': name, 'kind': 'command', 'summary': summ, 'sources': srcs, 'request': 'BuiltinCommandRequest'}
    if beh:
        iface['behavior'] = beh
        modeled[c['id']] = 'git-command-center.run-command' if comp == 'git-command-center' else iid
    new_ifaces.append(iface)
# API-only commands with deep handlers
for cid, iid in [('typescript.tsserverRequest', 'typescript-command-manager.cmd-typescript-tsserverrequest'),
                 ('markdown.api.render', 'markdown-command-manager.cmd-markdown-api-render'),
                 ('markdown.api.reloadPlugins', 'markdown-command-manager.cmd-markdown-api-reloadplugins')]:
    routers.setdefault(iid.split('.')[0], {})[cid] = iid
    modeled[cid] = iid

# command-level extension components and their activate
for d in level_exts:
    cid = comp_for({'ext': d, 'id': '', 'site': ''})
    srcs = [ACT[d]] + ([act_range(d)] if d in act_exts else [])
    evs = [a['name'].split(' ', 1)[1] for a in acts if a['file'].split('/')[1] == d]
    ncmd = sum(1 for c in cmds if c['ext'] == d and c['id'] not in SKIP)
    depth = 'modeled' if d in MODEL_EXTS else 'command-level'
    comp = {'id': cid, 'name': f'{ext_id(d)} extension', 'kind': 'module', 'layer': 'extensions', 'parent': 'builtin-extensions',
            'summary': f'Built-in extension {ext_id(d)}: its activate entry point' + (f' and its {ncmd} contributed commands.' if ncmd else '.'),
            'sources': srcs, 'attributes': {'owner': 'builtin-extensions', 'extension': ext_id(d), 'depth': depth},
            'state': {'schema': {'type': 'object', 'properties': {'activated': {'type': 'boolean'}, 'last_command': {'type': 'string'}}},
                      'initial': {'activated': False, 'last_command': ''}}}
    new_components.append(comp)
    first_cmd = next((c['id'] for c in cmds if c['ext'] == d and c['id'] not in SKIP), None)
    beh = [{'title': f'activate() of {ext_id(d)}', 'source': ACT[d], 'set': {'state.activated': True}}]
    if first_cmd:
        beh.append({'title': 'Register its commands with vscode.commands.registerCommand', 'source': SITE.get(first_cmd) or ACT[d],
                    'call': 'vscode-api.commands-register-command', 'input': {'command_id': first_cmd}})
    beh.append({'return': {'activated': True}})
    new_ifaces.append({'component': cid, 'name': 'activate', 'kind': 'function',
                       'summary': f'activate() of {ext_id(d)}' + (f"; activation events: {', '.join(evs)}" if evs else '; activated through its contributions'),
                       'sources': srcs,
                       'request': {'type': 'object', 'properties': {'extension_id': {'type': 'string', 'default': ext_id(d)}, 'activation_event': {'type': 'string', 'default': evs[0] if evs else '*'}}},
                       'behavior': beh})
    new_flows.append({'id': f'{d}-activate', 'name': f'{ext_id(d)} activation', 'tags': [], 'sources': srcs,
                      'entry': {'caller': 'exthost-runtime', 'interface': f'{cid}.activate', 'input': {'extension_id': ext_id(d)}}})

new_ifaces.append({'component': 'emmet-extension', 'name': 'validate', 'kind': 'function',
                   'summary': "validate(): emmet actions need an active text editor; without one they show 'No editor is active'.",
                   'sources': ['extensions/emmet/src/util.ts:107-117'], 'response': {'type': 'object', 'properties': {'valid': {'type': 'boolean'}}},
                   'behavior': [{'choice': 'active_editor', 'default': 'present', 'options': {
                       'present': [{'return': {'valid': True}}],
                       'absent': [{'title': 'No editor is active', 'source': 'extensions/emmet/src/util.ts:109-111',
                                   'call': 'vscode-api.window-show-information-message', 'input': {'message': 'No editor is active'}},
                                  {'return': {'valid': False}}]}}]})

# routers (each component's own registrations: its internal dispatch)
ROUTER_FLOW = {}
for comp, table in sorted(routers.items()):
    flow_id = comp.replace('-extension', '') + '-commands'
    ROUTER_FLOW[comp] = flow_id
    targets = sorted(set(table.values()))
    new_ifaces.append({'component': comp, 'name': 'execute-registered-command', 'kind': 'function',
                       'summary': 'This component\'s own command registrations: the callback that vscode.commands.registerCommand stored for each id (internal dispatch; the seam is command-service.execute-command).',
                       'sources': [SITE.get(next(iter(table)), None) or 'extensions/' + next(c['ext'] for c in cmds if c['id'] == next(iter(table))) + '/package.json'],
                       'request': 'BuiltinCommandRequest',
                       'behavior': [{'call': f"= state.registrations[input.command_id]", 'targets': targets, 'input': '= input', 'as': 'ran'},
                                    {'return': '= vars.ran.value'}]})
    new_flows.append({'id': flow_id, 'name': f'Run a command registered by {comp}', 'sources': [], 'entry': {'caller': 'user', 'interface': f'{comp}.execute-registered-command', 'input': {'command_id': next(iter(table)), 'args': []}}})
for c in doc['components'] + new_components:
    if c['id'] in routers:
        st = c.setdefault('state', {'schema': {'type': 'object', 'properties': {}}, 'initial': {}})
        st['schema'].setdefault('properties', {})['registrations'] = {'type': 'object'}
        st['initial']['registrations'] = routers[c['id']]
    if c['id'] == 'git-command-center':
        repo_cmds = [k for k, v in gitc.items() if v['repo_opt']]
        c['state'] = {'schema': {'type': 'object', 'properties': {'repository_commands': {'type': 'array', 'items': {'type': 'string'}}}},
                      'initial': {'repository_commands': sorted(repo_cmds)}}
for f in new_flows:
    if not f['sources']:
        del f['sources']
    if not f.get('tags'):
        f.pop('tags', None)


def walk(steps, fn):
    for s in steps or []:
        fn(s)
        for k in ('then', 'else', 'steps'):
            walk(s.get(k), fn)
        for o in (s.get('options') or {}).values():
            walk(o, fn)
        if isinstance(s.get('on_error'), list):
            walk(s['on_error'], fn)
        for b in s.get('branches') or []:
            walk(b, fn)


def fix_targets(s):
    if s.get('targets') == 'TARGETS_GIT':
        s['targets'] = sorted(git_targets)


doc['components'] += new_components
doc['interfaces'] += new_ifaces
doc['flows'] += new_flows
for i in doc['interfaces']:
    walk(i.get('behavior'), fix_targets)

# ------------------------------------------------------------------ vscode-api: copy exthost's contracts
ext_ifaces = {i['name']: i for i in exthost['interfaces'] if i['component'] == 'vscode-api'}
ext_schemas = {s['id']: s for s in exthost['schemas']}
used_api = set()


def collect(s):
    c = s.get('call')
    if isinstance(c, str) and c.startswith('vscode-api.'):
        used_api.add(c.split('.', 1)[1])


for i in doc['interfaces']:
    walk(i.get('behavior'), collect)
EXT_OF = {}
for c in doc['components']:
    a = c.get('attributes', {})
    if 'extension' in a:
        EXT_OF[c['id']] = a['extension']
PREFIX_EXT = [('git', 'vscode.git'), ('typescript', 'vscode.typescript-language-features'), ('lazy-client-host', 'vscode.typescript-language-features'),
              ('markdown', 'vscode.markdown-language-features'), ('md-', 'vscode.markdown-language-features')]


def ext_of(comp):
    if comp in EXT_OF:
        return EXT_OF[comp]
    for p, e in PREFIX_EXT:
        if comp.startswith(p):
            return e
    return 'vscode.git'


def req_schema(n):
    r = ext_ifaces[n].get('request')
    if isinstance(r, str):
        r = ext_schemas[r]['schema']
    return r or {}


ALIAS = {
    'command': lambda m: m.get('command_id'),
    'rest': lambda m: m.get('args'),
    'callback': lambda m: {},
    'options': lambda m: ({'log': m['log']} if 'log' in m else None) or ({'modal': m['modal']} if 'modal' in m else ({'title': m['title']} if 'title' in m else ({'placeHolder': m['placeholder']} if 'placeholder' in m else None))),
    'glob_pattern': lambda m: ({'pattern': m['glob_pattern']} if 'glob_pattern' in m else None),
    'show_options': lambda m: ({'view_column': m['column']} if 'column' in m else None),
    'name_or_configuration': lambda m: ({'name': m['name']} if 'name' in m else None),
    'task': lambda m: ({'name': m['task']} if 'task' in m else None),
}
DEFAULT = {'object': {}, 'string': '', 'array': [], 'boolean': False, 'integer': 0}


def normalize(comp):
    def fn(s):
        c = s.get('call')
        if not (isinstance(c, str) and c.startswith('vscode-api.')):
            return
        n = c.split('.', 1)[1]
        if n not in ext_ifaces:
            return
        sch = req_schema(n)
        props = sch.get('properties') or {}
        req = set(sch.get('required') or [])
        mine = dict(s.get('input') or {})
        out = {}
        for p, ps in props.items():
            if p == 'extension_id':
                out[p] = ext_of(comp)
            elif p in ALIAS and ALIAS[p](mine) is not None:
                out[p] = ALIAS[p](mine)
            elif p in mine:
                out[p] = mine[p]
            elif p in req:
                t = ps.get('type')
                t = t[0] if isinstance(t, list) else t
                out[p] = copy.deepcopy(DEFAULT.get(t, {}))
        if n == 'window-create-output-channel' and 'log' in mine:
            out['log'] = mine['log']  # coordinator decision: output-service (terminal-debug-tasks) reads a top-level log
        s['input'] = out
    return fn


for i in doc['interfaces']:
    if i['component'] != 'vscode-api':
        walk(i.get('behavior'), normalize(i['component']))
# replace my vscode-api stubs with copies of exthost's contract
mine_extra = {i['name']: i for i in doc['interfaces'] if i['component'] == 'vscode-api' and i['name'] not in ext_ifaces}
doc['interfaces'] = [i for i in doc['interfaces'] if i['component'] != 'vscode-api']
need_schemas = set()
for n in sorted(used_api):
    if n in ext_ifaces:
        src = ext_ifaces[n]
        stub = {'component': 'vscode-api', 'name': n}
        for k in ('kind', 'summary', 'sources', 'request', 'response', 'errors'):
            if k in src:
                stub[k] = copy.deepcopy(src[k])
        stub['attributes'] = {'boundary': True, 'owner': 'exthost'}
        for k in ('request', 'response'):
            if isinstance(stub.get(k), str):
                need_schemas.add(stub[k])
        doc['interfaces'].append(stub)
    elif n in mine_extra:
        m = mine_extra[n]
        m['kind'] = 'function'
        doc['interfaces'].append(m)
    else:
        doc['interfaces'].append({'component': 'vscode-api', 'name': n, 'kind': 'function', 'summary': n,
                                  'sources': ['src/vscode-dts/vscode.d.ts'], 'attributes': {'boundary': True, 'owner': 'exthost'},
                                  'request': 'ExthostApiArgs', 'response': 'ExthostApiResult'})
        need_schemas |= {'ExthostApiArgs', 'ExthostApiResult'}
for sid in sorted(need_schemas):
    doc['schemas'].append(copy.deepcopy(ext_schemas[sid]))
ext_comp = next(c for c in exthost['components'] if c['id'] == 'vscode-api')
for c in doc['components']:
    if c['id'] == 'vscode-api':
        c.clear()
        c.update(copy.deepcopy(ext_comp))
        c['attributes'] = dict(c.get('attributes') or {}, boundary=True, owner='exthost')
        c.pop('state', None)

# ------------------------------------------------------------------ registry seed (decision 6)
doc['components'].append({'id': 'commands-registry', 'name': 'CommandsRegistry', 'kind': 'module', 'parent': 'platform',
                          'summary': "platform-core's command registry (stub); builtin-extensions seeds its modeled commands in builtin-extensions-seed.",
                          'sources': ['src/vs/platform/commands/common/commands.ts'], 'attributes': {'boundary': True, 'owner': 'platform-core'}})
doc['fixtures'].append({'id': 'builtin-extensions-seed',
                        'summary': "The commands the built-in extensions register, keyed by id, naming the interface that handles each (decision 6). Git commands all name createCommand's wrapper, git-command-center.run-command.",
                        'state': {'commands-registry': {'commands': {k: {'handler': v} for k, v in sorted(modeled.items())}}}})

# ------------------------------------------------------------------ scenarios: generated batches
COMPS_OF = {i['component'] + '.' + i['name']: i for i in doc['interfaces']}
OPEN = {'git-model': {'state': 'initialized', 'repositories': ['/work/app']}, 'git-repository': {'root': '/work/app'}}
gen_sc = []


def batch(sid, steps, ifaces, state=None, choices=None):
    sc = {'id': sid, 'fixtures': ['one-window-folder'], 'steps': steps,
          'expect': [f"trace.filter(e, e.type == 'call.start' && e.interface in {json.dumps(sorted(ifaces))}).size() >= {len(set(ifaces))}"]}
    if state:
        sc['state'] = state
    if choices:
        sc['choices'] = choices
    gen_sc.append(sc)


# git: commands through createCommand's wrapper, isolated when they leave the extension host or close the repository
git_cmds = [c for c in cmds if c['ext'] == 'git' and comp_for(c) == 'git-command-center' and c['id'] not in SKIP and c['id'] not in ('git.refresh', 'git.stage', 'git.stageAll', 'git.commit')]
solo, grouped = [], []
for c in git_cmds:
    hits = gitc[c['id']]['hits']
    if c['id'] in EXEC_CMDS or any(list(h) == ['model', 'close'] for h in hits):
        solo.append(c)
    else:
        grouped.append(c)
for n in range(0, len(grouped), 20):
    chunk = grouped[n:n + 20]
    batch(f'builtin-extensions-git-command-center-{n // 20 + 1}',
          [{'interface': 'git-command-center.run-command', 'caller': 'user', 'input': {'command_id': c['id'], 'args': []}} for c in chunk],
          [f"git-command-center.{slug(c['id'])}" for c in chunk], state={'git-model@eh1': OPEN['git-model'], 'git-repository@eh1': OPEN['git-repository'], 'git-binary': {'staged': ['src/main.ts']}})
for c in solo:
    batch(f"builtin-extensions-git-{slug(c['id'])[4:]}"[:64],
          [{'interface': 'git-command-center.run-command', 'caller': 'user', 'input': {'command_id': c['id'], 'args': []}}],
          [f"git-command-center.{slug(c['id'])}"], state={'git-model@eh1': OPEN['git-model'], 'git-repository@eh1': OPEN['git-repository']})
# routers of the other components: their modeled commands
for comp, table in sorted(routers.items()):
    ids = [cid for cid in table if 'behavior' in COMPS_OF.get(table[cid], {}) and table[cid] not in ('typescript-command-manager.cmd-typescript-restarttsserver',)]
    if not ids:
        continue
    exec_ids = [cid for cid in ids if 'commands-execute-command' in json.dumps(COMPS_OF[table[cid]].get('behavior'))]
    plain = [cid for cid in ids if cid not in exec_ids]
    for n in range(0, len(plain), 25):
        chunk = plain[n:n + 25]
        batch(f"builtin-extensions-{ROUTER_FLOW[comp]}-{n // 25 + 1}",
              [{'flow': ROUTER_FLOW[comp], 'input': {'command_id': cid, 'args': []}} for cid in chunk], [table[cid] for cid in chunk])
    for cid in exec_ids:
        batch(f"builtin-extensions-{slug(cid)[4:]}"[:64], [{'flow': ROUTER_FLOW[comp], 'input': {'command_id': cid, 'args': []}}], [table[cid]])
# activation of every command-level extension
level_acts = [f'{comp_for({"ext": d, "id": "", "site": ""})}.activate' for d in level_exts]
for n in range(0, len(level_acts), 12):
    chunk = level_exts[n:n + 12]
    batch(f'builtin-extensions-activate-extensions-{n // 12 + 1}',
          [{'flow': f'{d}-activate'} for d in chunk], [f'{comp_for({"ext": d, "id": "", "site": ""})}.activate' for d in chunk])
batch('builtin-extensions-emmet-no-active-editor', [{'flow': 'emmet-commands', 'input': {'command_id': 'editor.emmet.action.balanceOut', 'args': []}}],
      ['emmet-extension.validate', 'vscode-api.window-show-information-message'], choices={'emmet-extension.validate.active_editor': 'absent'})
doc['scenarios'] += gen_sc

# ------------------------------------------------------------------ fix round
# fixround/*.yaml (sorted): an entry whose key (id, or component.name for interfaces) exists
# replaces it in place; others are appended. See notes/builtin-extensions.md, "Fix round".
def _key(sec, e):
    if sec == 'interfaces' and 'id' not in e:
        return e['component'] + '.' + e['name']
    return e.get('id')


for p in sorted(os.listdir(f'{HERE}/fixround')):
    if not p.endswith('.yaml'):
        continue
    part = yaml.safe_load(open(f'{HERE}/fixround/{p}')) or {}
    for sec, items in part.items():
        if sec in ('schema_version', 'id'):
            continue
        lst = doc.setdefault(sec, [])
        idx = {_key(sec, e): i for i, e in enumerate(lst)}
        for e in items or []:
            k = _key(sec, e)
            if k in idx:
                lst[idx[k]] = e
            else:
                idx[k] = len(lst)
                lst.append(e)

# Commands the fix round modeled that are not extension-command inventory entries: register them
# in commands-registry too. emmet.expandAbbreviation: emmetCommon.ts:33 registerCommand.
FIXROUND_COMMANDS = {'emmet.expandAbbreviation': 'emmet-extension.cmd-emmet-expandabbreviation'}
_seed = next(f for f in doc['fixtures'] if f['id'] == 'builtin-extensions-seed')
_cmds = _seed['state']['commands-registry']['commands']
for _k, _v in FIXROUND_COMMANDS.items():
    _cmds[_k] = {'handler': _v}
_seed['state']['commands-registry']['commands'] = dict(sorted(_cmds.items()))

# ------------------------------------------------------------------ write
out = {'schema_version': 1, 'id': 'vscode'}
for k in ['configs', 'fixtures', 'schemas', 'components', 'interfaces', 'flows', 'scenarios']:
    out[k] = doc[k]


class D(yaml.SafeDumper):
    pass


D.ignore_aliases = lambda *a: True
with open(f'{OUT}/fragments/builtin-extensions.yaml', 'w') as f:
    f.write('# builtin-extensions fragment of the VS Code 1.144.0 ontology (extensions/**).\n'
            '# Generated by examples/vscode/gen/builtin-extensions/gen.py from the hand-written parts in that\n'
            '# directory and the inventory; see notes/builtin-extensions.md.\n')
    yaml.dump(out, f, Dumper=D, sort_keys=False, width=140, allow_unicode=True)
json.dump(skips, open(f'{OUT}/skips/builtin-extensions.json', 'w'), indent=1)
print('components', len(out['components']), 'interfaces', len(out['interfaces']), 'flows', len(out['flows']),
      'scenarios', len(out['scenarios']), 'modeled commands', len(modeled), 'skips', len(skips))

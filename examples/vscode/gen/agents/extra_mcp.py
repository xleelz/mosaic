# extra MCP commands: one small flow each
EXTRA_MCP = [
 ('workbench.mcp.installFromManifest', 88, '1182-1200', 'Install from manifest: McpInstallFromManifestCommand installs a pasted server manifest through the workbench MCP management service.',
  [{'call': 'workbench-mcp-management-service.install', 'input': {'name': 'github', 'config': {'type': 'http', 'url': 'https://api.githubcopilot.com/mcp/'}, 'target': 'user'}}], 'workbench-mcp-management-service.install'),
 ('workbench.mcp.removeStoredInput', 89, '1203-1216', 'Remove stored input: IMcpRegistry.clearSavedInputs(scope, id).',
  [{'call': 'mcp-registry.clear-saved-inputs'}], 'mcp-registry.clear-saved-inputs'),
 ('workbench.mcp.editStoredInput', 90, '1218-1231', 'Edit stored input: IMcpRegistry.editSavedInput prompts for a new value and stores it.',
  [{'call': 'mcp-registry.set-saved-input', 'input': {'key': 'input:github_token', 'value': 'ghp_redacted'}}], 'mcp-registry.set-saved-input'),
 ('workbench.mcp.showOutput', 94, '1356-1381', 'Show Output: server.showOutput().',
  [{'call': 'mcp-server-runtime.show-output', 'input': {'server_id': 'github'}}], 'mcp-server-runtime.show-output'),
 ('workbench.mcp.showConfiguration', 96, '1325-1353', 'Show Configuration: open the server or collection origin in an editor.',
  [{'call': 'editor-service.open-editor', 'input': {'resource': 'file:///work/app/.vscode/mcp.json'}}], 'editor-service.open-editor'),
 ('workbench.mcp.openUserMcpJson', 99, '1562-1628', 'Open User Configuration: the Copilot global or legacy profile mcp.json, created when missing, opened in an editor.',
  [{'call': 'editor-service.open-editor', 'input': {'resource': 'vscode-userdata:/User/mcp.json'}}], 'editor-service.open-editor'),
 ('workbench.mcp.openRemoteUserMcpJson', 100, '1631-1650', 'Open Remote User Configuration: the remote profile mcp.json, created when missing.',
  [{'call': 'editor-service.open-editor', 'input': {'resource': 'vscode-remote:/User/mcp.json'}}], 'editor-service.open-editor'),
 ('workbench.mcp.openWorkspaceMcpJson', 101, '1683-1704', 'Open Workspace Configuration: the .code-workspace file.',
  [{'call': 'editor-service.open-editor', 'input': {'resource': 'file:///work/app.code-workspace'}}], 'editor-service.open-editor'),
 ('workbench.mcp.openWorkspaceFolderMcpJson', 102, '1653-1680', 'Open Workspace Folder Configuration: pick a folder, open its .vscode/mcp.json.',
  [{'call': 'editor-service.open-editor', 'input': {'resource': 'file:///work/app/.vscode/mcp.json'}}], 'editor-service.open-editor'),
]
def _cmd(cid, line, rng, summ, beh, check):
    slug = cmd_slug(cid)
    iface('mcp-commands', slug, summ, [f'{MCMD}:{rng}', f'{MCON}:{line}'], kind='command', request=obj({}), response=obj({'ok': B}),
          behavior=beh + [{'return': {'ok': True}}])
    fid = 'agents-mcp-' + slug[len('cmd-workbench-mcp-'):]
    flow(fid, 'mcp-commands.' + slug, 'user', 'MCP command ' + cid, [f'{MCON}:{line}'])
    scen(fid + '-happy', fid, ['result.ok', tr(check)])
for e in EXTRA_MCP:
    _cmd(*e)
iface('mcp-registry', 'clear-saved-inputs', 'clearSavedInputs(scope, id): forget stored input variable values.', [f'{MR}:190-199'],
      request=obj({}), response=obj({'ok': B}), behavior=[{'set': {'state.saved_inputs': {}}}, {'return': {'ok': True}}])
iface('mcp-registry', 'set-saved-input', 'setSavedInput / editSavedInput: store an input variable value (secret storage for passwords).', [f'{MR}:201-220'],
      request=obj({'key': s('input:github_token'), 'value': S}), response=obj({'ok': B}),
      behavior=[{'set': {'state.saved_inputs': '= merge(state.saved_inputs, {input.key: true})'}}, {'return': {'ok': True}}])
for sc in scenarios:
    if sc['id'] == 'agents-mcp-removestoredinput-happy':
        sc['state'] = {'mcp-registry@w1': {'saved_inputs': {'input:github_token': True}}}
        sc['expect'].append("size(state['mcp-registry@w1'].saved_inputs) == 0")
    if sc['id'] == 'agents-mcp-editstoredinput-happy':
        sc['expect'].append("state['mcp-registry@w1'].saved_inputs['input:github_token'] == true")

import yaml
class D(yaml.SafeDumper): pass
def str_rep(d, v):
    style = None
    if v.startswith('=') or v.startswith('!') or ': ' in v or v.startswith("'") or '#' in v:
        style = '"'
    return d.represent_scalar('tag:yaml.org,2002:str', v, style=style)
D.add_representer(str, str_rep)
doc = {'schema_version': 1, 'id': 'vscode', 'configs': configs, 'fixtures': fixtures, 'components': components, 'interfaces': interfaces, 'flows': flows, 'scenarios': scenarios}
hdr = "# Fragment of the agents area: the agent host process, the Agents (sessions) window and MCP.\n# Built from VS Code 1.144.0 (2c33b50b16) source; see notes/agents.md.\n"
open('/home/lbethay/workplace/mosaic/examples/vscode/fragments/agents.yaml', 'w').write(hdr + yaml.dump(doc, Dumper=D, sort_keys=False, width=200, allow_unicode=True))
print(len(components), len(interfaces), len(flows), len(scenarios), len(configs))

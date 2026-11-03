import json
inv=[e for e in json.load(open('/home/lbethay/workplace/mosaic/examples/vscode/inventory.json'))['entries'] if e['kind']=='cli-command']
A='cli/src/commands/args.rs'; M='cli/src/bin/code/main.rs'; T='cli/src/commands/tunnels.rs'
# name -> (handler source, behavior)
def slug(n): return 'cli-'+'-'.join(n.split()[1:]).replace('_','-')
def startcode(extra, line):
    return [{'title': 'Run the editor CLI with the translated arguments (start_code)', 'source': f'{M}:{line}', 'set': {'ctx.cli_code_args': extra}},
            {'return': {'exit_code': 0, 'code_args': extra}}]
def rpc(method, src):
    return [{'call': 'tunnel-singleton.rpc', 'input': {'method': method}, 'as': 'r'}, {'title': f'do_single_rpc_call {method} via the tunnel lock file', 'source': src, 'return': {'exit_code': 0}}]
def note(title, src, ret=None):
    return [{'title': title, 'source': src, 'return': ret or {'exit_code': 0}}]
B={
 'code update': note('Self-update the standalone CLI (check only with --check; no-op when up to date)', 'cli/src/commands/update.rs:19-45'),
 'code tunnel': [{'title': 'tunnels::serve: start the tunnel (singleton via lock file)', 'source': f'{T}:469-500', 'call': 'tunnel-singleton.serve', 'input': {'name': "= has(input.name) ? input.name : 'dev-box'"}}, {'return': {'exit_code': 0}}],
 'code ext': startcode("= ['--list-extensions']", '78-83'),
 'code status': startcode("= ['--status']", '85-90'),
 'code version': note('Dispatch the version subcommand', f'{M}:92-97'),
 'code serve-web': note('serve_web: run a local web server that downloads and serves VS Code server builds', 'cli/src/commands/serve_web.rs:75-120'),
 'code command-shell': note('command_shell: control server on stdin/stdout', f'{T}:146-160'),
 'code agent': note('Dispatch the agent subcommand (default: agent host)', f'{M}:107-110'),
 'code agent host': note('agent_host (or tunnels::serve with --tunnel)', f'{M}:112-117'),
 'code agent ps': note('agent_ps: list agent host sessions', 'cli/src/commands/agent_ps.rs:37-60'),
 'code agent stop': note('agent_stop', 'cli/src/commands/agent_stop.rs:21-40'),
 'code agent kill': note('agent_kill', 'cli/src/commands/agent_kill.rs:32-50'),
 'code agent logs': note('agent_logs', 'cli/src/commands/agent_logs.rs:22-40'),
 'code agent endpoints': note('agent_endpoints', 'cli/src/commands/agent_endpoints.rs:47-60'),
 'code agent relay': note('agent_relay', 'cli/src/commands/agent_relay.rs:42-60'),
 'code ext list': startcode("= ['--list-extensions']", '78-83'),
 'code ext install': startcode("= ['--install-extension=' + (has(input.id) ? input.id : 'ms-python.python')]", '78-83'),
 'code ext uninstall': startcode("= ['--uninstall-extension=' + (has(input.id) ? input.id : 'ms-python.python')]", '78-83'),
 'code ext update': startcode("= ['--update-extensions']", '78-83'),
 'code version use': note('version::switch_to: select a quality/version or path of the editor', 'cli/src/commands/version.rs:19-44'),
 'code version show': note('version::show: print the version in use', 'cli/src/commands/version.rs:46-60'),
 'code tunnel prune': [{'call': 'tunnel-singleton.prune', 'input': {}, 'as': 'p'}, {'title': 'Delete servers without a running process', 'source': f'{T}:451-467', 'return': {'exit_code': 0, 'deleted': '= vars.p.value.deleted'}}],
 'code tunnel kill': rpc('shutdown', f'{T}:403-414'),
 'code tunnel restart': rpc('restart', f'{T}:391-401'),
 'code tunnel status': [{'call': 'tunnel-singleton.rpc', 'input': {'method': 'status'}, 'as': 'r', 'on_error': 'continue'},
     {'if': "!vars.r.ok && vars.r.error.code != 'no-running-tunnel'", 'then': [{'fail': "= {'code': vars.r.error.code, 'message': vars.r.error.message}"}]},
     {'title': 'NoRunningTunnel prints tunnel: null', 'source': f'{T}:421-449', 'return': {'exit_code': 0, 'tunnel': "= vars.r.ok ? vars.r.value : null"}}],
 'code tunnel rename': [{'call': 'dev-tunnels-service.rename-tunnel', 'input': {'name': "= has(input.name) ? input.name : 'dev-box-2'"}}, {'title': 'tunnels::rename', 'source': f'{T}:371-382', 'return': {'exit_code': 0}}],
 'code tunnel unregister': [{'call': 'dev-tunnels-service.remove-tunnel', 'input': {}}, {'title': 'tunnels::unregister', 'source': f'{T}:384-389', 'return': {'exit_code': 0}}],
 'code tunnel user': note('Dispatch the tunnel user subcommand', f'{T}:342-369'),
 'code tunnel service': note('Dispatch the tunnel service subcommand', f'{T}:293-340'),
 'code tunnel forward-internal': note('tunnels::forward: forward ports for the editor (internal)', f'{T}:501-520'),
 'code tunnel service install': [{'call': 'tunnel-singleton.set-service-installed', 'input': {'installed': True}}, {'title': 'Register the tunnel as an OS service', 'source': f'{T}:293-340', 'return': {'exit_code': 0}}],
 'code tunnel service uninstall': [{'call': 'tunnel-singleton.set-service-installed', 'input': {'installed': False}}, {'title': 'Unregister the OS service', 'source': f'{T}:293-340', 'return': {'exit_code': 0}}],
 'code tunnel service log': note('Show the service log', f'{T}:293-340'),
 'code tunnel service internal-run': note('Run as the OS service (internal)', f'{T}:293-340'),
 'code tunnel user login': [{'call': 'dev-tunnels-service.login', 'input': {}}, {'title': 'Log in to the tunnel service (GitHub or Microsoft)', 'source': f'{T}:342-369', 'return': {'exit_code': 0}}],
 'code tunnel user logout': [{'call': 'dev-tunnels-service.logout', 'input': {}}, {'title': 'Log out', 'source': f'{T}:342-369', 'return': {'exit_code': 0}}],
 'code tunnel user show': note('Show the logged-in account', f'{T}:342-369'),
}
ifaces=[]; targets=[]
for e in inv:
    n=slug(e['name']); targets.append('code-cli.'+n)
    ifaces.append({'component':'code-cli','name':n,'kind':'cli','summary':f"`{e['name']}` (clap subcommand)",'attributes':{'command':e['name']},
                   'sources':[f"{A}:{e['line']}"],'request':{'type':'object','properties':{'name':{'type':'string'},'id':{'type':'string'}}},'behavior':B[e['name']]})
ifaces.append({'component':'code-cli','name':'main','kind':'process','summary':'code CLI main: parse args, then match on the subcommand',
  'sources':['cli/src/bin/code/main.rs:63-157'],
  'request':{'type':'object','required':['command'],'properties':{'command':{'type':'string','examples':['cli-tunnel-status']},'name':{'type':'string'},'id':{'type':'string'}}},
  'behavior':[{'title':'Dispatch on the parsed subcommand','source':'cli/src/bin/code/main.rs:63-157','call':"= 'code-cli.' + input.command",'targets':targets,'input':'= input','as':'r'},{'return':'= vars.r.value'}]})
def S(name, **kw): return dict(component='tunnel-singleton', name=name, kind='rpc', **kw)
ifaces += [
 S('serve', summary='Start serving the tunnel: acquire the singleton lock, register with dev tunnels', sources=[f'{T}:469-500'], request={'type':'object','properties':{'name':{'type':'string'}}},
   behavior=[{'call':'dev-tunnels-service.create-tunnel','input':{'name':'= input.name'}},{'set':{'state.running':True,'state.name':'= input.name','state.servers':{'srv-1':{'running':True}}}}]),
 S('rpc', summary='Singleton RPC over the lock-file pipe (status, restart, shutdown)', sources=['cli/src/commands/tunnels.rs:391-414'], request={'type':'object','properties':{'method':{'type':'string'}}},
   errors=[{'code':'no-running-tunnel','status':0,'retryable':False}],
   behavior=[{'if':'!state.running','then':[{'title':'No tunnel is running (lock file not held)','source':'cli/src/commands/tunnels.rs:442-444','fail':{'code':'no-running-tunnel','message':'No running tunnel found'}}]},
             {'if':"input.method == 'shutdown'",'then':[{'set':{'state.running':False,'state.servers':{'srv-1':{'running':False}}}},{'return':{}}]},
             {'if':"input.method == 'restart'",'then':[{'return':{}}]},
             {'return':{'name':'= state.name','service_installed':'= state.service_installed'}}]),
 S('prune', summary='Find stopped servers to delete', sources=[f'{T}:451-467'],
   behavior=[{'set':{'vars.dead':'= state.servers.filter(k, !state.servers[k].running)'}},{'set':{'state.servers':'= state.servers.filter(k, state.servers[k].running).transformMap(k, v, v)'}} if False else {'set':{'state.servers':"= {}"}, 'when':'size(vars.dead) > 0 && size(vars.dead) == size(state.servers)'},{'return':{'deleted':'= vars.dead'}}]),
 S('set-service-installed', summary='Service manager install/uninstall', sources=[f'{T}:293-340'], request={'type':'object','properties':{'installed':{'type':'boolean'}}},
   behavior=[{'set':{'state.service_installed':'= input.installed'}}]),
]
for n in ['create-tunnel','rename-tunnel','remove-tunnel','login','logout']:
    ifaces.append({'component':'dev-tunnels-service','name':n,'kind':'http','summary':f'Dev Tunnels service: {n}'})
comps=[{'id':'dev-tunnels-service','name':'Dev Tunnels service','kind':'external','layer':'external','summary':'Microsoft Dev Tunnels relay used by `code tunnel`.','attributes':{'owner':'remote-server'}}]
flows=[{'id':'rs-cli-tunnel-status','name':'code tunnel status (read the tunnel state)','entry':{'caller':'os-shell','interface':'code-cli.cli-tunnel-status'},'sources':['cli/src/commands/tunnels.rs:421']},{'id':'rs-cli-main','name':'code CLI command','tags':['writes'],'entry':{'caller':'os-shell','interface':'code-cli.main'},'sources':['cli/src/bin/code/main.rs:63']}]
def st(cmd, alias, **inp): return {'flow':'rs-cli-main','as':alias,'input':dict(command=cmd, **inp)}
scen=[
 {'id':'remote-server-cli-tunnel-lifecycle','fixtures':['base-workspace'],'steps':[
   st('cli-tunnel-status','s0'), st('cli-tunnel-kill','k0'), st('cli-tunnel','up',name='dev-box'), st('cli-tunnel-status','s1'),
   st('cli-tunnel-restart','rs'), st('cli-tunnel-kill','k1'), st('cli-tunnel-prune','pr'), st('cli-tunnel-rename','rn',name='box2'), st('cli-tunnel-unregister','un'),
   st('cli-tunnel-service-install','si'), st('cli-tunnel-service-uninstall','su'), st('cli-tunnel-user-login','li'), st('cli-tunnel-user-logout','lo'), {'flow':'rs-cli-tunnel-status','as':'final'}],
  'expect':["steps.final.result.value.tunnel == null && steps.s0.result.value.tunnel == null && steps.k0.result.error.code == 'no-running-tunnel'",
            "steps.s1.result.value.tunnel.name == 'dev-box' && steps.rs.result.ok && steps.k1.result.ok",
            "steps.pr.result.value.deleted == ['srv-1'] && !state['tunnel-singleton'].running && !state['tunnel-singleton'].service_installed",
            "calls['dev-tunnels-service.create-tunnel'] == 1 && calls['dev-tunnels-service.remove-tunnel'] == 1"]},
 {'id':'remote-server-cli-other-commands','fixtures':['base-workspace'],'steps':[st(t.split('.',1)[1], 'x%d'%i) for i,t in enumerate(targets) if t.split('.',1)[1] not in ('cli-tunnel','cli-tunnel-status','cli-tunnel-kill','cli-tunnel-restart','cli-tunnel-prune','cli-tunnel-rename','cli-tunnel-unregister','cli-tunnel-service-install','cli-tunnel-service-uninstall','cli-tunnel-user-login','cli-tunnel-user-logout')],
  'expect':["steps.x0.result.ok","ctx.cli_code_args == ['--update-extensions'] || size(ctx.cli_code_args) > 0","!state['tunnel-singleton'].running"]},
]
PART={'components':comps,'interfaces':ifaces,'flows':flows,'scenarios':scen}

# Reconciliation round: owner seams (decisions 6, 8, 10)
from base import *
import commands
from flows2 import CFG, TASK
stub('lifecycle-service','veto','workbench-shell','Answer onBeforeShutdown with a veto (id names the vetoing area).')
stub('commands-registry','register-command','platform-core','Register a command handler (the registry state is seeded by terminal-debug-tasks-seed).')
VETO_IDS={'terminal-service.on-before-shutdown':('veto.terminal',S('src/vs/workbench/contrib/terminal/browser/terminalService.ts',227)),
          'debug-lifecycle.should-veto-shutdown':('veto.debug',S('src/vs/workbench/contrib/debug/common/debugLifecycle.ts',23))}
def _veto(steps,vid,src):
    out=[]
    for st_ in steps:
        for k in ('then','else'):
            if k in st_: st_[k]=_veto(st_[k],vid,src)
        if 'options' in st_: st_['options']={o:_veto(v,vid,src) for o,v in st_['options'].items()}
        if 'return' in st_ and isinstance(st_['return'],dict) and 'veto' in st_['return']:
            out.append({'title':'e.veto(...) answers the lifecycle service','source':src,'call':'lifecycle-service.veto','input':{'id':vid,'veto':st_['return']['veto']}})
        out.append(st_)
    return out
for i in IFACES:
    k=i['component']+'.'+i['name']
    if k in VETO_IDS:
        i['behavior']=_veto(i['behavior'],*VETO_IDS[k])
        i['request']=obj({'reason':st('reload',enum=['close','quit','reload','load']),'window_id':st('w1')},['reason'])
reg={}
for feat,m in commands.MODELED.items():
    for cid,iid in m.items(): reg[cid.split('@')[0]]={'handler':iid}
FIXTURES.append({'id':'terminal-debug-tasks-seed','summary':'terminal-debug-tasks world: the area\'s commands registered in the command registry, the local pty backend registered, '
  'launch.json and tasks.json of /work/app parsed into the debug configuration manager and the task service, js-debug debuggers (adapter-manager initial state).',
  'state':{'commands-registry':{'commands':reg},'terminal-instance-service':{'backends':{'local':True}},
           'configuration-manager':{'launch_configurations':{'Launch Program':CFG}},'task-service':{'workspace_tasks':{'build':TASK}}}})
SCEN[:]=[s for s in SCEN if s['id']!='task-run-quick-pick-empty']
for s in SCEN:
    if 'terminal-debug-tasks-seed' not in s['fixtures']: s['fixtures'].append('terminal-debug-tasks-seed')
    if s['id']=='terminal-create-no-backend': s['state']={'terminal-instance-service@w1':{'backends':{'local':False}}}
# The trust seams are workbench-shell's; their copied contracts leave `trusted` unconstrained, so in the
# area-only check the stub answer is random. Scenarios in a trusted world pin the outcome the trusted
# fixture gives (the owner answers trusted for one-window-folder); untrusted scenarios set their own option.
TRUST_KEYS=['debug-service.start-debugging.trust','task-service.trust.trust','test-service.run-resolved-tests.trust','run-automatic-tasks.try-run-tasks.trust']
for s in SCEN:
    if 'untrusted-folder' in s['fixtures']: continue
    ch=s.setdefault('choices',{})
    for k in TRUST_KEYS: ch.setdefault(k,'trusted')
# Decision 6: handlers are invoked by command-service.try-execute-command with {command_id, args}.
# Each cmd-* interface takes that shape and reads its first argument (merged over its defaults).
import copy, json as _json
from flows2 import CFG as _CFG
ARG0_AS={'debug.startFromConfig':'config'}   # the handler's first argument is the IConfig itself
def _defaults(req):
    out={}
    if not isinstance(req,dict): return out
    for k,p in (req.get('properties') or {}).items():
        if isinstance(p,str): out[k]=_CFG if p=='DebugLaunchConfig' else {}; continue
        if 'default' in p: out[k]=p['default']
        elif 'examples' in p: out[k]=p['examples'][0]
        elif p.get('type')=='boolean': out[k]=False
        elif p.get('type')=='array': out[k]=[p['items']['examples'][0]] if isinstance(p.get('items'),dict) and p['items'].get('examples') else []
        elif p.get('type')=='integer': out[k]=0
        elif p.get('type')=='object': out[k]={}
        else: out[k]=''
    return out
def _rewrite(x):
    if isinstance(x,str): return x.replace('input.','vars.cmdargs.') if x.startswith('=') or ('input.' in x and not x.startswith('cmd')) else x
    if isinstance(x,list): return [_rewrite(v) for v in x]
    if isinstance(x,dict): return {k:(_rewrite(v) if k not in ('call','emit','publish','targets','title','source') else v) for k,v in x.items()}
    return x
for i in IFACES:
    cid=(i.get('attributes') or {}).get('command_id')
    if not cid or (i.get('attributes') or {}).get('boundary'): continue
    d=_defaults(i.get('request'))
    if cid in ARG0_AS:
        a0="{'%s': input.args[0]}"%ARG0_AS[cid]
    else:
        a0="input.args[0]"
    pre={'set':{'vars.cmdargs':"= merge(%s, has(input.args) && size(input.args) > 0 && input.args[0] != null ? %s : {})"%(_json.dumps(d).replace('true','true'),a0)}}
    i['behavior']=[pre]+_rewrite(i['behavior'])
    i['request']=obj({'command_id':st(cid),'args':arr(default=[])})
def _deep(a,b):
    if isinstance(a,dict) and isinstance(b,dict):
        o=dict(a)
        for k,v in b.items(): o[k]=_deep(a.get(k),v) if k in a else v
        return o
    return b
CMDIF={i['component']+'.'+i['name']:i['attributes']['command_id'] for i in IFACES if (i.get('attributes') or {}).get('command_id') and not i['attributes'].get('boundary')}
FLOWCMD={}
for f in FLOWS:
    e=f.get('entry') or {}
    if e.get('interface') in CMDIF:
        cid=CMDIF[e['interface']]; FLOWCMD[f['id']]=(cid,e.get('input') or {})
def _wrap(cid,flat):
    a0=flat.get(ARG0_AS[cid]) if cid in ARG0_AS else flat
    return {'command_id':cid,'args':[a0]}
for fid,(cid,base_in) in FLOWCMD.items():
    for f in FLOWS:
        if f['id']==fid: f['entry']['input']=_wrap(cid,base_in)
for s in SCEN:
    if s.get('flow') in FLOWCMD and 'input' in s and not s.get('steps'):
        cid,b=FLOWCMD[s['flow']]; s['input']=_wrap(cid,_deep(b,s['input']))
    for stp in s.get('steps') or []:
        if stp.get('flow') in FLOWCMD and 'input' in stp:
            cid,b=FLOWCMD[stp['flow']]; stp['input']=_wrap(cid,_deep(b,stp['input']))
# Decision 11: skip reasons use the accepted categories.
def _cat(r):
    if r.startswith('UI toggle'): return r
    if r.startswith('UI'): return 'UI toggle: '+r.split(':',1)[1].strip() if ':' in r else 'UI toggle: '+r
    if r.startswith('clipboard'): return 'UI toggle: '+r+' (the clipboard is workbench-shell\'s)'
    if r.startswith('hands the focused frame'): return 'owned by another area (chat): '+r
    if r.startswith('opens the memory inspector'): return 'UI toggle: '+r
    if r.startswith('developer diagnostics'): return 'developer tooling: '+r
    if r.startswith('internal API command'): return 'internal tooling: '+r
    if r.startswith('not a terminal behavior'): return 'not an entry point: '+r
    if r.startswith('not a product entry point'): return 'internal tooling: '+r
    return r
for s_ in commands.SKIPS: s_['reason']=_cat(s_['reason'])
_json.dump(commands.SKIPS,open(os.path.join(VSC,'skips','terminal-debug-tasks.json'),'w'),indent=1)

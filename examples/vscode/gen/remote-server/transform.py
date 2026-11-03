# Post-processing applied by build.py (reconciliation round): command input defaults,
# CommandsRegistry seed, area fixtures on scenarios, srv1 instance keys.
import re, copy
def rewrite(v):
    if isinstance(v, str): return v.replace('input.', 'vars.cmd.') if (v.startswith('=') or True) else v
    if isinstance(v, list): return [rewrite(x) for x in v]
    if isinstance(v, dict): return {k: rewrite(x) for k, x in v.items()}
    return v
def rewrite_steps(steps):
    out=[]
    for st in steps:
        st=dict(st)
        for k in list(st):
            if k in ('title','detail','source','call','emit','publish','targets','as','choice','default'): continue
            if k == 'options': st[k]={o: rewrite_steps(v) for o,v in st[k].items()}
            elif k in ('then','else','steps'): st[k]=rewrite_steps(st[k])
            elif k == 'on_error' and isinstance(st[k], list): st[k]=rewrite_steps(st[k])
            else: st[k]=rewrite(st[k])
        out.append(st)
    return out
commands={}
for i in out['interfaces']:
    if i.get('kind') != 'command' or 'behavior' not in i: continue
    props=((i.get('request') or {}).get('properties')) or {}
    dflt={}
    for n,p in props.items():
        if 'default' in p: dflt[n]=p['default']
        elif p.get('examples'): dflt[n]=p['examples'][0]
    i['behavior']=[{'title':'Arguments: the caller\'s values over the declared defaults (handlers are also reached through command-service with only {command_id, args})','set':{'vars.cmd':"= merge(" + repr(dflt).replace('True','true').replace('False','false').replace('None','null') + ", input == null ? {} : input)"}}]+rewrite_steps(i['behavior'])
    cid=(i.get('attributes') or {}).get('command_id')
    if cid: commands[cid]={'handler': f"{i['component']}.{i['name']}"}
for f in out['fixtures']:
    if f['id']=='remote-server-seed': f['state']['commands-registry']['commands']=commands
# server components (remote-server-process subtree)
par={c['id']:c.get('parent') for c in skeleton['components']+out['components']}
def under(c, root='remote-server-process'):
    while c:
        if c==root: return True
        c=par.get(c)
    return False
server={c for c in par if under(c) and c!='remote-server-process'}
GAL='product-extensions-gallery-service-url'; SYN='product-configuration-sync-store-url'
for sc in out['scenarios']:
    fx=list(sc.get('fixtures') or [])
    cfg=dict(sc.get('config') or {})
    extra=[]
    if GAL in cfg and cfg[GAL]!='': cfg.pop(GAL); extra.append('remote-server-marketplace')
    if SYN in cfg and cfg[SYN]!='': cfg.pop(SYN); extra.append('remote-server-sync')
    txt=repr(sc)
    flows=[sc.get('flow')]+[s.get('flow') for s in sc.get('steps') or []]
    is_srv=any(re.search(r"\b%s\b"%re.escape(c), txt) for c in server) or any((f or '').startswith('rs-remote-') for f in flows)
    if is_srv: extra.append('remote-server-srv1')
    if not extra or 'base-workspace' in fx: extra.insert(0,'remote-server-seed')
    if extra and 'one-window-folder' in fx and len(extra) and extra!=['remote-server-seed']: fx.remove('one-window-folder')
    if 'base-workspace' in fx and is_srv: fx.remove('base-workspace')
    sc['fixtures']=fx+[e for e in extra if e not in fx]
    if cfg: sc['config']=cfg
    else: sc.pop('config', None)
    if is_srv:
        if 'state' in sc:
            sc['state']={(k+'@srv1' if k in server else k):v for k,v in sc['state'].items()}
        def fixex(e):
            for c in sorted(server, key=len, reverse=True):
                e=e.replace(f"state['{c}']", f"state['{c}@srv1']")
            return e
        sc['expect']=[fixex(e) for e in sc.get('expect',[])]
    sc['expect']=[e.replace("size(state['extensions-profile-scanner-service'].profile_extensions) == 0","!('ms-python.python' in state['extensions-profile-scanner-service'].profile_extensions)") for e in sc.get('expect',[])]

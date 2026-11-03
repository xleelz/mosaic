import sys, re, json, yaml
import os
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,HERE)
VSC=os.path.abspath(os.path.join(HERE,'..','..'))
from code import lines, match_end, find, cls, method, match_end_body
FIXTURES=[]; COMPS=[]; IFACES=[]; FLOWS=[]; SCEN=[]; CONFIGS=[]; SCHEMAS=[]
def S(f,a,b=None):
    return f"{f}:{a}" if b is None or b==a else f"{f}:{a}-{b}"
def M(f,name,start=1,end=None):
    r=method(f,name,start,end)
    if not r: raise Exception(f"method {name} not in {f}")
    return S(f,*r)
def CL(f,name,full=False):
    r=cls(f,name)
    if not r: raise Exception(f"class {name} not in {f}")
    return S(f,r[0],r[1]) if full else S(f,r[0])
def L(f,pat,start=1):
    l=find(f,pat,start)
    if not l: raise Exception(f"{pat} not in {f}")
    return l
def LS(f,pat,start=1,span=0):
    l=L(f,pat,start); return S(f,l,l+span) if span else S(f,l)
def BLK(f,pat,start=1):
    l=L(f,pat,start); return S(f,l,match_end(f,l))
def comp(id,name,parent,summary,sources,kind='module',state=None,attributes=None,description=None,capacity=None,layer='workbench'):
    c={'id':id,'name':name,'kind':kind,'layer':layer,'parent':parent,'summary':summary,'sources':sources}
    if description: c['description']=description
    a={'owner':'terminal-debug-tasks'}
    if attributes: a.update(attributes)
    c['attributes']=a
    if state is not None: c['state']=state
    if capacity: c['capacity']=capacity
    COMPS.append(c); return c
def iface(component,name,summary,sources,behavior=None,request=None,response=None,kind='function',errors=None,subscribe=None,attributes=None,store=None,description=None):
    i={'component':component,'name':name,'kind':kind,'summary':summary,'sources':sources}
    if description: i['description']=description
    if attributes: i['attributes']=attributes
    if request is not None: i['request']=request
    if response is not None: i['response']=response
    if errors: i['errors']=errors
    if subscribe: i['subscribe']=subscribe
    if store: i['store']=store
    if behavior is not None: i['behavior']=behavior
    IFACES.append(i); return i
BPARENT={'platform-core':'platform','workbench-shell':'workbench','exthost':'exthost-bridge','main-process':'main-process','files-search-scm':'workbench','editor':'editor','chat':'workbench','remote-server':'remote','agents':'agents','notebook-webview':'workbench','workbench-contribs':'workbench'}
BCOMPS=set()
import glob as _glob
OWN_C={}; OWN_I={}; OWN_S={}
for _f in sorted(_glob.glob(os.path.join(VSC,'fragments','*.yaml'))):
    if _f.endswith('terminal-debug-tasks.yaml'): continue
    _d=yaml.safe_load(open(_f))
    for _s in _d.get('schemas',[]) or []: OWN_S[_s['id']]=_s['schema']
    for _c in _d.get('components',[]) or []:
        if not (_c.get('attributes') or {}).get('boundary'): OWN_C[_c['id']]=_c
    for _i in _d.get('interfaces',[]) or []:
        if not (_i.get('attributes') or {}).get('boundary'): OWN_I[_i['component']+'.'+_i['name']]=_i
def _inline(x):
    if isinstance(x,str) and x in OWN_S: return _inline(OWN_S[x])
    if isinstance(x,dict):
        if '$ref' in x and x['$ref'] in OWN_S: return _inline(OWN_S[x['$ref']])
        return {k:_inline(v) for k,v in x.items()}
    if isinstance(x,list): return [_inline(v) for v in x]
    return x
def stub(component,name,owner,summary,request=None,response=None,kind='function',errors=None,attributes=None,parent=None):
    if component not in BCOMPS:
        BCOMPS.add(component)
        oc=OWN_C.get(component)
        if oc:
            COMPS.append({'id':component,'name':oc.get('name',component),'kind':oc.get('kind','service'),'parent':oc.get('parent'),'summary':'Boundary reference to a component owned by '+owner+'.','attributes':{'boundary':True,'owner':owner}})
        else:
            COMPS.append({'id':component,'name':component,'kind':'service','parent':parent or BPARENT[owner],'summary':'Boundary reference to a component owned by '+owner+'.','attributes':{'boundary':True,'owner':owner}})
    oi=OWN_I.get(component+'.'+name)
    if oi:
        kind=oi.get('kind',kind); request=_inline(oi.get('request')); response=_inline(oi.get('response')); errors=oi.get('errors')
        summary=summary+' (contract copied from the owner fragment)'
    a={'boundary':True,'owner':owner}
    if attributes: a.update(attributes)
    i={'component':component,'name':name,'kind':kind,'summary':summary,'attributes':a}
    if request is not None: i['request']=request
    if response is not None: i['response']=response
    if errors: i['errors']=errors
    IFACES.append(i); return i
def flow(id,name,entry_iface,description,sources,caller='user',inp=None,tags=None,on=None):
    e={'caller':caller,'interface':entry_iface}
    if inp is not None: e['input']=inp
    if on: e['on']=on
    f={'id':id,'name':name,'description':description,'entry':e,'sources':sources}
    if tags: f['tags']=tags
    FLOWS.append(f); return f
def scen(id,name,expect,flow=None,fixtures=('one-window-folder',),inp=None,state=None,choices=None,faults=None,steps=None,config=None,description=None):
    s={'id':id,'name':name}
    if flow: s['flow']=flow
    if description: s['description']=description
    s['fixtures']=list(fixtures)
    if config: s['config']=config
    if inp is not None: s['input']=inp
    if state: s['state']=state
    if choices: s['choices']=choices
    if faults: s['faults']=faults
    if steps: s['steps']=steps
    s['expect']=expect
    SCEN.append(s); return s
def config(id,key,typ,value,default,summary,sources,owner=None,extra=None):
    a={'key':key}
    if owner: a.update({'boundary':True,'owner':owner})
    if extra: a.update(extra)
    CONFIGS.append({'id':id,'type':typ,'value':value,'default':default,'summary':summary,'sources':sources,'attributes':a})
# schema helpers
def obj(props,required=None,**kw):
    o={'type':'object','properties':props}
    if required: o['required']=required
    o.update(kw); return o
def st(ex=None,**kw):
    o={'type':'string'}
    if ex is not None: o['examples']=[ex] if not isinstance(ex,list) else ex
    o.update(kw); return o
def it(ex=None,**kw):
    o={'type':'integer'}
    if ex is not None: o['examples']=[ex]
    o.update(kw); return o
def bo(default=None):
    o={'type':'boolean'}
    if default is not None: o['default']=default
    return o
def arr(items=None,**kw):
    o={'type':'array','items':items or {}}
    o.update(kw); return o
def ob(**kw):
    o={'type':'object'}; o.update(kw); return o
def slug(cmd):
    s=re.sub(r'[._]','-',cmd).lower()
    s=re.sub(r'[^a-z0-9-]','-',s)
    s=re.sub(r'-+','-',s).strip('-')
    return 'cmd-'+s[:60]
class Q(str): pass
def q_repr(dumper,data):
    return dumper.represent_scalar('tag:yaml.org,2002:str',data,style='"')
def str_repr(dumper,data):
    if data.startswith('=') or data.startswith('!') or ': ' in data or data in ('on','off','yes','no','null','true','false') or re.match(r'^[0-9.]+$',data):
        return dumper.represent_scalar('tag:yaml.org,2002:str',data,style='"')
    return dumper.represent_scalar('tag:yaml.org,2002:str',data)
class D(yaml.SafeDumper): pass
D.add_representer(str,str_repr)
D.add_representer(Q,q_repr)
def emit(path):
    doc={'schema_version':1,'id':'vscode','configs':CONFIGS,'fixtures':FIXTURES,'schemas':SCHEMAS,'components':COMPS,'interfaces':IFACES,'flows':FLOWS,'scenarios':SCEN}
    with open(path,'w') as fh:
        fh.write('# terminal-debug-tasks fragment of the VS Code 1.144 ontology (built from code).\n# Generated from a reading of the code at 2c33b50b16; see notes/terminal-debug-tasks.md.\n')
        yaml.dump(doc,fh,Dumper=D,sort_keys=False,width=200,allow_unicode=True)

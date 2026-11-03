import json,re,os,glob,collections,sys
ROOT='/home/lbethay/.cache/mosaic-bench/vscode-1.144.0'
mine=json.load(open('/tmp/exthost_mine.json'))
rpc=[e for e in mine if e['kind']=='exthost-rpc']
# registerSingleton map
reg={}
for f in glob.glob(ROOT+'/src/vs/**/*.ts',recursive=True):
    if '/test/' in f: continue
    try: s=open(f).read()
    except: continue
    for m in re.finditer(r'registerSingleton\(\s*(I\w+)\s*,\s*(\w+)',s):
        reg.setdefault(m.group(1),[]).append((m.group(2),f[len(ROOT)+1:]))
def kebab(n):
    n=re.sub(r'([a-z0-9])([A-Z])',r'\1-\2',n)
    n=re.sub(r'([A-Z]+)([A-Z][a-z])',r'\1-\2',n)
    return n.lower()
def impl_of(iname):
    c=reg.get(iname)
    if not c: return None
    # prefer electron/desktop impl
    for cls,f in c:
        if 'electron' in f: return cls
    return c[0][0]
def body(s,i):
    j=s.index('{',i); d=0
    for k in range(j,len(s)):
        if s[k]=='{': d+=1
        elif s[k]=='}':
            d-=1
            if d==0: return s[j:k+1]
    return s[j:]
out={}
cache={}
for e in rpc:
    shape,meth=e['name'].split('.',1)
    det=e.get('detail','')
    m=re.match(r'implemented by (\w+) \((.+)\)',det)
    info={'shape':shape,'method':meth,'impl':None,'file':None,'field':None,'service':None,'svc_impl':None}
    if m:
        cls,f=m.group(1),m.group(2); info['impl']=cls; info['file']=f
        s=cache.get(f) or open(os.path.join(ROOT,f)).read(); cache[f]=s
        inj=dict((a,b) for b,a in re.findall(r'@(I\w+)\s+(?:private|protected|public)?\s*(?:readonly\s+)?(\w+)',s))
        mm=re.search(r'(?:async\s+|public\s+|override\s+)*%s\s*(?:<[^>]*>)?\('%re.escape(meth),s)
        if mm:
            b=body(s,mm.end())
            for fm in re.finditer(r'this\.(\w+)(?:\.(\w+))?',b):
                fld=fm.group(1)
                if fld in inj:
                    info['field']=fld; info['service']=inj[fld]; info['svc_method']=fm.group(2); info['svc_impl']=impl_of(inj[fld]); break
            info['line']=s[:mm.start()].count('\n')+1
        info['inj']=sorted(set(inj.values()))
    out[e['name']]=info
json.dump(out,open('/tmp/exthost_gen/rpc_targets.json','w'),indent=1)
c=collections.Counter((v['impl'] or '?').startswith('MainThread') for v in out.values())
print(c)
mt=[v for v in out.values() if (v['impl'] or '').startswith('MainThread')]
print('mainthread with service',sum(1 for v in mt if v['service']), 'of', len(mt))
for v in mt:
    if not v['service']: print('  no svc',v['shape'],v['method'],v['inj'][:6])

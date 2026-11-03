import json,re
ROOT='/home/lbethay/.cache/mosaic-bench/vscode-1.144.0/'
F='src/vs/workbench/api/common/extHost.api.impl.ts'
L=open(ROOT+F).read().split('\n')
starts={}
for i,l in enumerate(L):
    m=re.search(r'const (\w+): typeof vscode\.(\w+) = \{',l)
    if m: starts[m.group(2)]=i
order=sorted(starts.items(),key=lambda x:x[1])
mine=json.load(open('/tmp/exthost_mine.json'))
api=[e for e in mine if e['kind']=='extension-api']
res={}
for e in api:
    _,ns,fn=e['name'].split('.')
    st=starts.get(ns)
    if st is None: res[e['name']]=None; continue
    nxt=min([s for n,s in order if s>st]+[len(L)])
    found=None
    for i in range(st,nxt):
        if re.match(r'\s*(async\s+)?%s\s*(<[^>]*>)?\s*\('%fn,L[i]) or re.match(r'\s*%s\s*[:,]'%fn,L[i]) or re.match(r'\s*get %s\('%fn,L[i]):
            found=i+1;break
    # find end: next line at same indent starting with '},' 
    end=found
    if found:
        ind=len(L[found-1])-len(L[found-1].lstrip())
        for j in range(found, min(found+80,nxt)):
            l=L[j]
            if l.strip() and (len(l)-len(l.lstrip()))<=ind:
                end=j+1 if l.strip().startswith('}') else j
                break
    res[e['name']]=(found,end)
json.dump(res,open('/tmp/exthost_gen/api_lines.json','w'),indent=0)
for k,v in res.items():
    if not v or not v[0]: print('MISSING',k)
print(len(res))
tgt={}
for k,v in res.items():
    s='\n'.join(L[v[0]-1:v[1]])
    m=re.findall(r'\b(extHost\w+|extensionService|extHostCommands)\.(\w+)',s)
    tgt[k]=m[:3]
json.dump(tgt,open('/tmp/exthost_gen/api_targets.json','w'),indent=0)
for k in res: print(k, res[k], tgt[k][:2])

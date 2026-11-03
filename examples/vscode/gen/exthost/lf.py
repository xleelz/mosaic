import json,re,os
HERE=os.path.dirname(os.path.abspath(__file__))+'/'
ROOT='/home/lbethay/.cache/mosaic-bench/vscode-1.144.0/'
F='src/vs/workbench/api/common/extHostLanguageFeatures.ts'
s=open(ROOT+F).read(); L=s.split('\n')
tg=json.load(open(HERE+'api_targets.json'))
mine=json.load(open(HERE+'mine.json'))
proto={e['name'].split('.',1)[1]:e['line'] for e in mine if e['kind']=='exthost-rpc' and e['name'].startswith('MainThreadLanguageFeaturesShape.')}
out={}
for api,t in tg.items():
    if not api.startswith('vscode.languages.') or not t or t[0][0]!='extHostLanguageFeatures': continue
    meth=t[0][1]
    m=re.search(r'\n\t(%s)\(extension: IExtensionDescription'%meth,s)
    if not m: print('nometh',api,meth); continue
    ln=s[:m.start()].count('\n')+2
    # body end
    i=s.index('{',m.end()); d=0
    for k in range(i,len(s)):
        if s[k]=='{': d+=1
        elif s[k]=='}':
            d-=1
            if d==0: break
    end=s[:k].count('\n')+1
    body=s[i:k]
    r=re.findall(r'this\._proxy\.(\$\w+)\(',body)
    rr=[x for x in r if x.startswith(('$register','$set'))] or r
    rpc=rr[0] if rr else None
    mt=open(ROOT+'src/vs/workbench/api/browser/mainThreadLanguageFeatures.ts').read()
    mm=re.search(r'\n\t(?:async )?%s\('%re.escape(rpc),mt) if rpc else None
    mtl=mt[:mm.start()].count('\n')+2 if mm else None
    out[api]={'method':meth,'line':ln,'end':end,'rpc':rpc,'proto_line':proto.get(rpc),'mt_line':mtl}
    print(api.split('.')[-1],rpc,proto.get(rpc),mtl)
json.dump(out,open(HERE+'lf.json','w'),indent=1)

import json,re,sys
ROOT='/home/lbethay/.cache/mosaic-bench/vscode-1.144.0/'
e=json.load(open('/home/lbethay/workplace/mosaic/examples/vscode/gen/editor/editor_inv.json'))
cmds=[x for x in e if x['kind']=='vscode-command']
out=[]
for x in cmds:
    lines=open(ROOT+x['file']).read().split('\n')
    n=x['name']
    hits=[i+1 for i,l in enumerate(lines) if ("'"+n+"'") in l or ('"'+n+'"') in l]
    lab=None
    if hits:
        h=hits[0]
        for j in range(h-1,min(h+8,len(lines))):
            m=re.search(r"localize2?\(\s*(?:\{[^}]*\}|'[^']*')\s*,\s*\"([^\"]+)\"",lines[j])
            if m: lab=m.group(1);break
    out.append(dict(x,idline=hits[0] if hits else None,label=lab,regtext=lines[x['line']-1].strip()))
json.dump(out,open('cmds.json','w'),indent=1)
for o in out:
    if not o['idline']: print('NOID',o['name'],o['file'].split('/')[-1],o['line'],o['regtext'][:100])
print(sum(1 for o in out if o['label']), len(out))

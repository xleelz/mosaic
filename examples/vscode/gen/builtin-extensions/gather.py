import json, re, os, subprocess, sys
ROOT='/home/lbethay/.cache/mosaic-bench/vscode-1.144.0'
inv=json.load(open('/home/lbethay/workplace/mosaic/examples/vscode/inventory.json'))['entries']
cmds=[x for x in inv if x['kind']=='extension-command']
acts=[x for x in inv if x['kind']=='activation-event']
nls={}
def title(ext, line):
    f=f'{ROOT}/extensions/{ext}/package.json'
    lines=open(f).read().split('\n')
    # search nearby lines for "title"
    for i in range(line-1, min(line+8,len(lines))):
        m=re.search(r'"title"\s*:\s*"([^"]*)"', lines[i])
        if m:
            t=m.group(1)
            if t.startswith('%'):
                if ext not in nls:
                    p=f'{ROOT}/extensions/{ext}/package.nls.json'
                    nls[ext]=json.load(open(p)) if os.path.exists(p) else {}
                v=nls[ext].get(t.strip('%'))
                if isinstance(v,dict): v=v.get('message')
                t=v or t
            return t
    return ''
def regsite(ext, cid):
    d=f'{ROOT}/extensions/{ext}/src'
    if not os.path.isdir(d): d=f'{ROOT}/extensions/{ext}'
    pats=[f"registerCommand('{cid}'", f'registerCommand("{cid}"', f"@command('{cid}'", f"= '{cid}'", f"'{cid}'", f'"{cid}"']
    for p in pats:
        r=subprocess.run(['grep','-rnF','--include=*.ts','--exclude-dir=test','--exclude-dir=node_modules','--exclude-dir=out','--exclude-dir=dist',p,d],capture_output=True,text=True).stdout.strip().split('\n')
        r=[x for x in r if x and '.test.' not in x and '/test/' not in x]
        if r:
            f,l,_=r[0].split(':',2)
            return os.path.relpath(f,ROOT)+':'+l, p
    return None, None
out=[]
for c in cmds:
    ext=c['file'].split('/')[1]
    t=title(ext,c['line'])
    site,pat=regsite(ext,c['name'])
    out.append(dict(ext=ext,id=c['name'],file=c['file'],line=c['line'],title=t,site=site,pat=pat))
json.dump(dict(cmds=out,acts=acts),open('/home/lbethay/workplace/mosaic/examples/vscode/gen/builtin-extensions/data.json','w'),indent=1)
from collections import Counter
print(Counter((o['ext'], o['site'] is not None) for o in out))
for o in out:
    if not o['site']: print('NOSITE',o['ext'],o['id'])

import json,re,subprocess
ROOT='/home/lbethay/.cache/mosaic-bench/vscode-1.144.0/'
out=json.load(open('cmds.json'))
def label_near(lines,h):
    for j in range(max(0,h-3),min(h+10,len(lines))):
        m=re.search(r"localize2?\(\s*(?:\{[^}]*\}|'[^']*')\s*,\s*[\"']([^\"']+)[\"']",lines[j])
        if m: return m.group(1)
    m=None
    return None
for o in out:
    if o['idline'] and o['label']: 
        o['idfile']=o['file']; continue
    if o['idline']:
        o['idfile']=o['file']
        lines=open(ROOT+o['file']).read().split('\n')
        o['label']=label_near(lines,o['idline'])
        continue
    n=o['name']
    r=subprocess.run(['grep','-rnF',"'"+n+"'",ROOT+'src/vs/editor','--include=*.ts'],capture_output=True,text=True).stdout.strip().split('\n')
    r=[x for x in r if x and '/test/' not in x]
    if r:
        f,l,_=r[0].split(':',2); f=f[len(ROOT):]
        o['idfile']=f;o['idline']=int(l)
        lines=open(ROOT+f).read().split('\n')
        o['label']=label_near(lines,int(l))
    else:
        o['idfile']=None
json.dump(out,open('cmds.json','w'),indent=1)
for o in out:
    if not o['idline']: print('NOID',o['name'],o['file'],o['line'])
print(sum(1 for o in out if o['label']), len(out))

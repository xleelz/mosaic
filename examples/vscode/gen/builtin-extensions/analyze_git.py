import re, json, collections
ROOT='/home/lbethay/.cache/mosaic-bench/vscode-1.144.0'
lines=open(f'{ROOT}/extensions/git/src/commands.ts').read().split('\n')
cmds=[]
for i,l in enumerate(lines):
    m=re.match(r"\s*@command\('([^']+)'(.*)\)\s*$", l)
    if m: cmds.append((m.group(1), i))
out={}
for idx,(cid,i) in enumerate(cmds):
    # method header is next non-decorator line
    j=i+1
    while lines[j].strip().startswith('@'): j+=1
    # find end: line == '\t}' after j
    k=j+1
    while k < len(lines) and lines[k] != '\t}': k+=1
    body='\n'.join(lines[j:k+1])
    pats=[('repo', r"\brepository\.(\w+)\("), ('repo', r"\brepo\.(\w+)\("), ('this', r"this\.(\w+)\("), ('model', r"this\.model\.(\w+)\("),
          ('exec', r"commands\.executeCommand(?:<[^>]*>)?\('([^']+)'"), ('window', r"window\.(show\w+|createTerminal|withProgress)\("), ('env', r"env\.(\w+)\.?(\w*)\(")]
    hits=[]
    for kind,p in pats:
        for m in re.finditer(p, body):
            hits.append((m.start(), kind, m.group(1)))
    hits.sort()
    out[cid]={'start':i+1,'end':k+1,'method':re.sub(r'\(.*','',lines[j].strip()).replace('async ',''),'hits':[(h[1],h[2]) for h in hits[:6]], 'repo_opt': 'repository: true' in lines[i]}
json.dump(out,open('git_cmds.json','w'),indent=0)
c=collections.Counter(v['hits'][0][0] if v['hits'] else None for v in out.values())
print(len(out),c)
for k,v in list(out.items())[:200]:
    print(k, v['method'], v['hits'][:3])

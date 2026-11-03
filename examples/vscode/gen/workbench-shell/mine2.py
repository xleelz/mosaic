import json,re
d=json.load(open('/home/lbethay/workplace/mosaic/examples/vscode/inventory.json'))
own=['src/vs/workbench/browser/','src/vs/workbench/common/','src/vs/workbench/services/']
exc=['src/vs/workbench/services/extensions/','src/vs/workbench/services/textfile/','src/vs/workbench/services/workingCopy/','src/vs/workbench/services/search/','src/vs/workbench/services/chat/']
def mp(f): return any(f.startswith(o) for o in own) and not any(f.startswith(x) for x in exc)
mine=[]
for e in d['entries']:
    if e['kind']=='service':
        impls=re.findall(r'(\w+) \(((?:src|extensions)/[^:)]+)',e.get('detail',''))
        if impls:
            # owned if any non-standalone impl in my path; prefer workbench impl
            wb=[i for i in impls if 'standalone' not in i[1]]
            if any(mp(f) for _,f in wb): mine.append(e)
            continue
        if mp(e['file']): mine.append(e)
        continue
    if e['kind'] in ('exthost-rpc',): continue
    if mp(e['file']): mine.append(e)
json.dump(mine,open('/tmp/wbs/mine.json','w'),indent=1)
from collections import Counter
print(len(mine),Counter(e['kind'] for e in mine))

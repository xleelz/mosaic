import json,fnmatch,sys
d=json.load(open('/home/lbethay/workplace/mosaic/examples/vscode/inventory.json'))
own=['src/vs/workbench/browser/','src/vs/workbench/common/','src/vs/workbench/services/']
exc=['src/vs/workbench/services/extensions/','src/vs/workbench/services/textfile/','src/vs/workbench/services/workingCopy/','src/vs/workbench/services/search/','src/vs/workbench/services/chat/']
mine=[]
for e in d['entries']:
    f=e['file']
    if any(f.startswith(o) for o in own) and not any(f.startswith(x) for x in exc):
        mine.append(e)
# exthost-rpc entries are owned by impl area; service by registerSingleton impl
json.dump(mine,open('/tmp/wbs/mine.json','w'),indent=1)
from collections import Counter
print(len(mine),Counter(e['kind'] for e in mine))

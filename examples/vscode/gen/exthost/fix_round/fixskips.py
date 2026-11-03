import json, re, yaml, glob
import os, sys
ws=os.path.normpath(os.path.dirname(os.path.abspath(__file__)) + '/../../..') + '/'
SK=sys.argv[1]
comps=set(); ifaces=set()
for f in glob.glob(ws+'fragments/*.yaml')+[ws+'skeleton.yaml']:
    d=yaml.safe_load(open(f))
    for c in d.get('components') or []: comps.add(c['id'])
    for i in d.get('interfaces') or []: ifaces.add(i['component']+'.'+i['name'])
s=json.load(open(SK))
modeled={'IExtHostEditorTabsShape.$acceptEditorTabModel','IExtHostEditorTabsShape.$acceptTabOperation','ExtHostDocumentSaveParticipantShape.$participateInSave',
 'ExtHostSearchShape.$provideTextSearchResults','ExtHostDebugServiceShape.$provideDebugVisualizers','MainThreadDebugServiceShape.$registerDebugVisualizer',
 'MainThreadDebugServiceShape.$unregisterDebugVisualizer','ExtHostCommandsShape.$executeContributedCommand','ExtHostChatAgentsShape2.$invokeAgent','MainThreadLanguageModelsShape.$tryStartChatRequest','MainThreadAuthenticationShape.$getSession','ExtHostAuthenticationShape.$getSessions','MainThreadAuthenticationShape.$ensureProvider'}
out=[]; bad=[]
for x in s:
    if x['name'] in modeled: continue
    r=x['reason']
    if re.search(r'\bcovered by\b', r, re.I) and 'covered_by' not in x:
        cov=None
        m=re.search(r'held by ([a-z0-9-]+)', r)
        if m:
            cov = m.group(1) if m.group(1) in comps else None
            if cov is None: cov='vscode-api'
        else:
            m=re.search(r'forwards to ([a-z0-9.-]*[a-z0-9])', r)
            t=m.group(1)
            if t in ifaces: cov=t
            elif t.split('.')[0] in comps: cov=t.split('.')[0]
        if not cov:
            own=re.search(r'plumbing: ([a-z0-9-]+)\.', r).group(1)
            if own not in comps and own.startswith('main-thread-notebook-'): own='main-thread-notebooks-and-editors'
            if own in comps:
                cov=own
                x['reason']=re.sub(r'; covered by .*$', '; its target has no entity in the merged model, so it is covered by the %s customer component' % own, r)
        if cov: x['covered_by']=cov
        else: bad.append(x['name']+' '+r)
    out.append(x)
json.dump(out, open(SK,'w'), indent=1)
print(len(s), len(out), 'unresolved', len(bad)); print('\n'.join(bad[:20]))

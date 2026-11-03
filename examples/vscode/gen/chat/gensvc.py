"""Generate services.yaml: one component per chat-area service (its registered implementation),
citing the createDecorator line, and a startup flow narrating each registerSingleton."""
import json, os, re, yaml
ROOT = '/home/lbethay/.cache/mosaic-bench/vscode-1.144.0'
HERE = os.path.dirname(os.path.abspath(__file__))
inv = [e for e in json.load(open(os.path.join(HERE, '..', '..', 'inventory.json')))['entries'] if e.get('area') == 'chat' and e['kind'] == 'service']
core = yaml.safe_load(open(os.path.join(HERE, 'core.yaml')))
ext = yaml.safe_load(open(os.path.join(HERE, 'ext.yaml')))
existing = {}
for d in (core, ext):
    for c in d['components']:
        for s in c.get('sources', []):
            existing[s] = c['id']
files = []
for d in ['src/vs/workbench/contrib/chat', 'src/vs/workbench/contrib/inlineChat', 'src/vs/workbench/contrib/agentsVoice', 'src/vs/workbench/services/chat', 'src/vs/sessions', 'src/vs/workbench']:
    for r, _, fs in os.walk(os.path.join(ROOT, d)):
        if '/test' in r:
            continue
        files += [os.path.join(r, f) for f in fs if f.endswith('.ts')]
    if d == 'src/vs/workbench/services/chat':
        break
cache = {}
def L(p):
    if p not in cache:
        cache[p] = open(p).read().split('\n')
    return cache[p]
def kebab(n):
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', n)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1-\2', s)
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:64]
comps, steps, flowsteps = [], [], []
taken = set()
for e in inv:
    name = e['name']
    reg = None
    for p in files:
        for n, l in enumerate(L(p)):
            m = re.search(r'registerSingleton\(\s*' + re.escape(name) + r'\s*,\s*(\w+)', l)
            if m:
                reg = (os.path.relpath(p, ROOT), n + 1, m.group(1)); break
        if reg: break
    impl = reg[2] if reg else None
    cls = None
    if impl:
        for p in files:
            for n, l in enumerate(L(p)):
                if re.match(r'^(export )?(abstract )?class ' + re.escape(impl) + r'\b', l):
                    cls = (os.path.relpath(p, ROOT), n + 1); break
            if cls: break
    deco = f"{e['file']}:{e['line']}"
    if deco in existing:
        continue
    cid = kebab(impl or name[1:])
    if cid in taken:
        cid = kebab(name[1:])
    taken.add(cid)
    srcs = [deco] + ([f"{reg[0]}:{reg[1]}"] if reg else []) + ([f"{cls[0]}:{cls[1]}"] if cls else [])
    summ = f"{impl or name[1:]}: the registered implementation of {name}." if reg else f"{name} (createDecorator); no registerSingleton in the chat tree, the service is created by its owner with the instantiation service."
    comps.append({'id': cid, 'name': impl or name[1:], 'kind': 'service', 'layer': 'ai', 'parent': 'inline-chat' if 'inlineChat' in e['file'] else 'chat',
                  'sources': srcs, 'summary': summ, 'attributes': {'owner': 'chat', 'service_id': name}})
    flowsteps.append({'component': cid, 'title': f"{name} -> {impl}" if impl else f"{name} (no singleton registration)", 'source': f"{reg[0]}:{reg[1]}" if reg else deco})
yaml.safe_dump({'components': comps, 'flows': [{
    'id': 'chat-service-registrations', 'name': "Chat services registered for the window's instantiation service",
    'description': "Each chat-area service identifier (createDecorator) and the implementation registerSingleton binds to it; the instantiation service creates them on first use (Delayed) or at startup (Eager).",
    'sources': ['src/vs/workbench/contrib/chat/browser/chat.shared.contribution.ts:3472'],
    'steps': flowsteps}]}, open(os.path.join(HERE, 'services.yaml'), 'w'), sort_keys=False, width=200)
print(len(comps), 'service components;', sum(1 for s in flowsteps if '->' in s['title']), 'with registerSingleton')

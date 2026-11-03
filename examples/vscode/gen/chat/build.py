"""Build examples/vscode/fragments/chat.yaml from the parts in this directory.

usage: python3 -I build.py   (run from anywhere)

- merges the parts (later parts override earlier entities with the same id);
- copies the owner's contract (kind, request, response, errors; component kind/layer/parent)
  onto every boundary stub, inlining the owner's named schemas;
- normalizes every cmd-* interface so it also accepts command-service's {command_id, args};
- adds this area's commands to the commands-registry rows of the chat-seed fixture;
- adds chat-seed to every scenario's fixtures;
- finally applies the fix-round patches in fixround/ (NN-*.py scripts, then NN-*.yaml entity
  upserts, in name order) verbatim, after every transformation above.
"""
import copy, glob, json, os, re, sys, yaml

HERE = os.path.dirname(os.path.abspath(__file__))
VS = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(VS, 'fragments', 'chat.yaml')
PARTS = ['core.yaml', 'boundary.yaml', 'contrib.yaml', 'services.yaml', 'ext.yaml', 'final.yaml', 'flows.yaml', 'contribflows.yaml', 'extflows.yaml']

CORE_COMMANDS = {
    'chat-execute-actions.cmd-workbench-action-chat-submit': 'workbench.action.chat.submit',
    'chat-execute-actions.cmd-workbench-action-edits-submit': 'workbench.action.edits.submit',
    'chat-execute-actions.cmd-workbench-action-chat-cancel': 'workbench.action.chat.cancel',
    'chat-execute-actions.cmd-workbench-action-chat-sendtonewchat': 'workbench.action.chat.sendToNewChat',
    'chat-queue-actions.cmd-workbench-action-chat-queuemessage': 'workbench.action.chat.queueMessage',
    'chat-queue-actions.cmd-workbench-action-chat-steerwithmessage': 'workbench.action.chat.steerWithMessage',
    'chat-queue-actions.cmd-workbench-action-chat-removependingrequest': 'workbench.action.chat.removePendingRequest',
    'chat-queue-actions.cmd-workbench-action-chat-removeallpendingrequests': 'workbench.action.chat.removeAllPendingRequests',
    'chat-new-actions.cmd-workbench-action-chat-newchat': 'workbench.action.chat.newChat',
    'chat-actions.cmd-workbench-action-chat-clearinputhistory': 'workbench.action.chat.clearInputHistory',
    'chat-actions.cmd-workbench-action-chat-resettrustedtools': 'workbench.action.chat.resetTrustedTools',
    'chat-tool-actions.cmd-workbench-action-chat-accepttool': 'workbench.action.chat.acceptTool',
    'chat-tool-actions.cmd-workbench-action-chat-skiptool': 'workbench.action.chat.skipTool',
    'chat-editing-actions.cmd-chatediting-acceptallfiles': 'chatEditing.acceptAllFiles',
    'chat-editing-actions.cmd-chatediting-discardallfiles': 'chatEditing.discardAllFiles',
    'chat-editing-actions.cmd-chatediting-acceptfile': 'chatEditing.acceptFile',
    'chat-editing-actions.cmd-chatediting-discardfile': 'chatEditing.discardFile',
    'chat-import-export.cmd-workbench-action-chat-export': 'workbench.action.chat.export',
    'chat-import-export.cmd-workbench-action-chat-import': 'workbench.action.chat.import',
    'inline-chat-actions.cmd-inlinechat-start': 'inlineChat.start',
    'inline-chat-actions.cmd-inlinechat2-keep': 'inlineChat2.keep',
    'inline-chat-actions.cmd-inlinechat2-close': 'inlineChat2.close',
    'inline-chat-actions.cmd-inlinechat2-cancel': 'inlineChat2.cancel',
}


def fix(o):
    if isinstance(o, dict):
        return {('on' if k is True else ('off' if k is False else k)): fix(v) for k, v in o.items()}
    if isinstance(o, list):
        return [fix(x) for x in o]
    return o


def addfill(o):
    if isinstance(o, dict):
        if 'call' in o and 'input' in o and 'fill' not in o:
            o['fill'] = not str(o['call']).startswith('file-service.')
        for v in o.values():
            addfill(v)
    elif isinstance(o, list):
        for x in o:
            addfill(x)
    return o


def iid(i):
    return (i.get('component') or i['id'].split('.')[0]) + '.' + (i.get('name') or i['id'].split('.', 1)[1])


def load_owners():
    comps, ifaces, schemas = {}, {}, {}
    for f in sorted(glob.glob(os.path.join(VS, 'fragments', '*.yaml'))):
        if f.endswith('/chat.yaml'):
            continue
        try:
            d = fix(yaml.safe_load(open(f)))
        except Exception as e:
            print('owner fragment unreadable, skipped:', os.path.basename(f), file=sys.stderr)
            continue
        for s in d.get('schemas') or []:
            schemas[s['id']] = s['schema']
        for c in d.get('components') or []:
            if not (c.get('attributes') or {}).get('boundary'):
                comps[c['id']] = c
        for i in d.get('interfaces') or []:
            if not (i.get('attributes') or {}).get('boundary'):
                ifaces[iid(i)] = i
    return comps, ifaces, schemas


def inline(s, schemas, depth=0):
    if depth > 12:
        return s
    if isinstance(s, str) and s in schemas:
        return inline(copy.deepcopy(schemas[s]), schemas, depth + 1)
    if isinstance(s, dict):
        if '$ref' in s and isinstance(s['$ref'], str):
            ref = s['$ref'].split('/')[-1]
            if ref in schemas:
                return inline(copy.deepcopy(schemas[ref]), schemas, depth + 1)
        return {k: inline(v, schemas, depth + 1) for k, v in s.items()}
    if isinstance(s, list):
        return [inline(x, schemas, depth + 1) for x in s]
    return s


def zero(p):
    if 'default' in p:
        return p['default']
    t = p.get('type')
    if isinstance(t, list):
        t = [x for x in t if x != 'null'][0]
    if 'examples' in p:
        return p['examples'][0]
    return {'string': '', 'integer': 0, 'number': 0, 'boolean': False, 'array': [], 'object': {}}.get(t, '')


def sub_input(o):
    if isinstance(o, str):
        return re.sub(r'(?<![A-Za-z0-9_.])input\.', 'vars.cmd_in.', o)
    if isinstance(o, list):
        return [sub_input(x) for x in o]
    if isinstance(o, dict):
        return {k: sub_input(v) for k, v in o.items()}
    return o


def apply_fixround(d):
    def key(sec, e):
        return e['component'] + '.' + e['name'] if sec == 'interfaces' else e['id']

    def upsert(sec, items):
        lst = d.setdefault(sec, [])
        idx = {key(sec, e): n for n, e in enumerate(lst)}
        for e in items:
            k = key(sec, e)
            if k in idx:
                lst[idx[k]] = e
            else:
                idx[k] = len(lst)
                lst.append(e)

    def get(sec, k):
        for e in d[sec]:
            if key(sec, e) == k:
                return e
        raise KeyError(k)

    def remove(sec, k):
        d[sec] = [e for e in d[sec] if key(sec, e) != k]

    fdir = os.path.join(HERE, 'fixround')
    for f in sorted(glob.glob(os.path.join(fdir, '*.py'))):
        exec(open(f).read(), {'d': d, 'upsert': upsert, 'get': get, 'remove': remove, 'yaml': yaml, 'Y': yaml.safe_load})
    for f in sorted(glob.glob(os.path.join(fdir, '*.yaml'))):
        p = yaml.safe_load(open(f)) or {}
        for sec in ['configs', 'components', 'interfaces', 'flows', 'scenarios', 'fixtures']:
            if p.get(sec):
                upsert(sec, p[sec])


def main():
    docs = [addfill(fix(yaml.safe_load(open(os.path.join(HERE, p))))) for p in PARTS if os.path.exists(os.path.join(HERE, p))]
    out = {'schema_version': 1, 'id': 'vscode'}
    for k in ['configs', 'components', 'interfaces', 'flows', 'scenarios', 'fixtures']:
        seen, items = {}, []
        for d in docs:
            for e in (d or {}).get(k) or []:
                key = iid(e) if k == 'interfaces' else e['id']
                if key in seen:
                    items[seen[key]] = e
                else:
                    seen[key] = len(items)
                    items.append(e)
        if items:
            out[k] = items
    comps, ifaces, schemas = load_owners()
    for c in out['components']:
        a = c.get('attributes') or {}
        if a.get('boundary') and c['id'] in comps:
            o = comps[c['id']]
            for f in ('kind', 'layer', 'parent'):
                if f in o:
                    c[f] = o[f]
    for i in out['interfaces']:
        a = i.get('attributes') or {}
        if a.get('boundary') and iid(i) in ifaces:
            o = ifaces[iid(i)]
            for f in ('kind', 'request', 'response', 'errors'):
                if f in o:
                    i[f] = inline(copy.deepcopy(o[f]), schemas)
                elif f in i and f != 'kind':
                    del i[f]
    # cmd-* normalization and registry rows
    rows = {}
    for i in out['interfaces']:
        if not i.get('name', '').startswith('cmd-') or (i.get('attributes') or {}).get('boundary'):
            continue
        cmd = (i.get('attributes') or {}).get('command') or CORE_COMMANDS.get(iid(i))
        if cmd:
            i.setdefault('attributes', {})['command'] = cmd
            rows[cmd] = {'handler': iid(i)}
        req = i.get('request') or {}
        props = req.get('properties') or {}
        defaults = {n: zero(p) for n, p in props.items()}
        if 'behavior' in i:
            i['behavior'] = [{'set': {'vars.cmd_in': '= merge(' + json.dumps(defaults) + ', input)'}}] + sub_input(i['behavior'])
        if req.get('required'):
            req['required'] = []
    for fx in out.get('fixtures', []):
        if fx['id'] == 'chat-seed':
            fx.setdefault('state', {})['commands-registry'] = {'commands': rows}
    for s in out.get('scenarios', []):
        fxs = s.get('fixtures') or ['one-window-folder']
        if 'chat-seed' not in fxs:
            s['fixtures'] = fxs + ['chat-seed']
    apply_fixround(out)
    yaml.safe_dump(out, open(OUT, 'w'), sort_keys=False, allow_unicode=True, width=200)
    print('wrote', OUT, {k: len(v) for k, v in out.items() if isinstance(v, list)})


main()

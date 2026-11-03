# Parse vscode.d.ts function signatures for the API entries this area owns.
import json, re, os
HERE = os.path.dirname(os.path.abspath(__file__)) + '/'
ROOT = '/home/lbethay/.cache/mosaic-bench/vscode-1.144.0/'
src = open(ROOT + 'src/vscode-dts/vscode.d.ts').read()
lines = src.split('\n')
mine = json.load(open(HERE + 'mine.json'))
def split_params(s):
    out, depth, cur = [], 0, ''
    s = s.replace('=>', '~~')
    for ch in s:
        if ch in '<({[': depth += 1
        if ch in '>)}]': depth -= 1
        if ch == ',' and depth == 0: out.append(cur); cur = ''
        else: cur += ch
    if cur.strip(): out.append(cur)
    return [p.strip() for p in out]
def snake(n): return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', n).lower()
res = {}
for e in mine:
    if e['kind'] != 'extension-api': continue
    _, ns, fn = e['name'].split('.')
    # namespace block
    m = re.search(r'(?:export )?namespace %s \{' % ns, src)
    start = m.end()
    nxt = re.search(r'\n\t(?:export )?namespace \w+ \{', src[start:])
    block = src[start:start + nxt.start()] if nxt else src[start:]
    sigs = []
    for sm in re.finditer(r'(?:export )?function %s\s*(<[^(]*>)?\(' % fn, block):
        j = sm.end(); d = 1; k = j
        while d:
            if block[k] == '(': d += 1
            elif block[k] == ')': d -= 1
            k += 1
        params = re.sub(r'\s+', ' ', block[j:k-1])
        rest = block[k:k+200]
        ret = re.match(r'\s*:\s*([^;]+);', rest)
        sigs.append((split_params(params), ret.group(1).strip() if ret else ''))
    props = {}; reqsets = []
    for ps, ret in sigs:
        req = set()
        for p in ps:
            mm = re.match(r'(\.\.\.)?(\w+)(\?)?\s*:\s*(.+)$', p)
            if not mm: continue
            isrest, name, opt, typ = mm.groups()
            n = snake(name)
            t = typ.strip()
            if isrest or t.endswith('[]') or t.startswith('readonly ') and t.endswith('[]'): js = {'type': 'array'}
            elif t == 'string': js = {'type': 'string'}
            elif t == 'number': js = {'type': 'integer'}
            elif t == 'boolean': js = {'type': 'boolean'}
            elif t in ('Uri',): js = {'type': 'string', 'format': 'uri'}
            elif t == 'DocumentSelector': js = {'type': 'string', 'examples': ['typescript'], 'description': 'DocumentSelector; modeled as a language id'}
            else: js = {'type': 'object'}
            js['description'] = (js.get('description', '') + ' ' if js.get('description') else '') + f"{name}{'?' if opt else ''}: {t}"
            if n not in props: props[n] = js
            if not opt and not isrest: req.add(n)
        reqsets.append(req)
    required = sorted(set.intersection(*reqsets)) if reqsets else []
    res[e['name']] = {'properties': props, 'required': required, 'returns': sorted({r for _, r in sigs}), 'overloads': len(sigs)}
json.dump(res, open(HERE + 'api_params.json', 'w'), indent=1)
for k, v in list(res.items())[:8]: print(k, list(v['properties']), v['required'], v['returns'])
print(sum(1 for v in res.values() if v['overloads'] == 0), 'missing')

"""Small DSL that writes parts/<name>.yaml for gen.py.

Each part module (parts_src/<name>.py) builds a Part with commands, contributions, components,
stubs and scenarios; `python3 builder.py <name>...` writes parts/<name>.yaml.
"""
import os, sys, importlib, re
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
C = 'src/vs/workbench/contrib/'


def slug(cid):
    s = re.sub(r'[._]', '-', cid).lower()
    s = re.sub(r'[^a-z0-9-]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return ('cmd-' + s)[:64].rstrip('-')


# ---- step helpers ----
def call(iface, input=None, title=None, source=None, as_=None, on_error=None, **kw):
    s = {}
    if title: s['title'] = title
    if source: s['source'] = src(source)
    s['call'] = iface
    if input is not None: s['input'] = input
    if as_: s['as'] = as_
    if on_error is not None: s['on_error'] = on_error
    s.update(kw)
    return s


def ret(v, title=None, source=None):
    s = {}
    if title: s['title'] = title
    if source: s['source'] = src(source)
    s['return'] = v
    return s


def fail(code, message, title=None, source=None):
    s = {}
    if title: s['title'] = title
    if source: s['source'] = src(source)
    s['fail'] = {'code': code, 'message': message}
    return s


def iff(cond, then, els=None, title=None, source=None):
    s = {}
    if title: s['title'] = title
    if source: s['source'] = src(source)
    s['if'] = cond
    s['then'] = then
    if els is not None: s['else'] = els
    return s


def choice(name, default, options, title=None, source=None):
    s = {}
    if title: s['title'] = title
    if source: s['source'] = src(source)
    s['choice'] = name
    s['default'] = default
    s['options'] = options
    return s


def sets(d, title=None, source=None):
    s = {}
    if title: s['title'] = title
    if source: s['source'] = src(source)
    s['set'] = d
    return s


def note(title, source=None):
    s = {'title': title}
    if source: s['source'] = src(source)
    return s


def publish(topic, input, source=None, title=None):
    s = {}
    if title: s['title'] = title
    if source: s['source'] = src(source)
    s['publish'] = topic
    s['input'] = input
    s['delivery'] = 'sync'
    return s


def foreach(expr, as_, steps):
    return {'foreach': expr, 'as': as_, 'steps': steps}


def src(s):
    """'preferences/browser/x.ts:12-14' -> full path; full paths pass through."""
    return s if s.startswith('src/') else C + s


class Part:
    def __init__(self, name):
        self.name = name
        self.components, self.stubs, self.interfaces, self.scenarios, self.configs = [], [], [], [], []
        self.seed = {}
        self._bcomps = set()
        self._stubs = set()
        self._comps = set()

    # boundary stubs: owner contracts are applied by gen.py when the owner defines them
    def stub(self, iface, owner, request=None, response=None, kind='function'):
        comp, name = iface.split('.', 1)
        if comp not in self._bcomps:
            self._bcomps.add(comp)
            self.components.append({'id': comp, 'attributes': {'boundary': True, 'owner': owner}})
        if iface in self._stubs:
            return iface
        self._stubs.add(iface)
        s = {'component': comp, 'name': name, 'kind': kind, 'attributes': {'boundary': True, 'owner': owner}}
        if request: s['request'] = request
        if response: s['response'] = response
        self.stubs.append(s)
        return iface

    def comp(self, id, name, parent, sources, summary, kind='module', state=None):
        c = {'id': id, 'name': name, 'kind': kind, 'parent': parent, 'summary': summary, 'sources': [src(x) for x in sources]}
        if state is not None:
            c['state'] = state
        self._comps.add(id)
        self.components.append(c)
        return id

    def iface(self, comp, name, summary, sources, behavior, request=None, response=None, kind='function', errors=None, attributes=None, subscribe=None):
        i = {'component': comp, 'name': name, 'kind': kind, 'summary': summary, 'sources': [src(x) for x in sources]}
        if attributes: i['attributes'] = attributes
        if subscribe: i['subscribe'] = subscribe
        i['request'] = request if request is not None else {'type': 'object'}
        if response: i['response'] = response
        if errors: i['errors'] = errors
        i['behavior'] = behavior
        self.interfaces.append(i)
        return f'{comp}.{name}'

    def cmd(self, comp, cid, entry, handler, summary, behavior, request=None, scen=None, errors=None):
        """entry: 'file:line' of the inventory registration; handler: 'file:a-b' or list."""
        hs = handler if isinstance(handler, list) else ([handler] if handler else [])
        iid = self.iface(comp, slug(cid), summary, [entry] + hs, behavior, request=request, kind='command', errors=errors, attributes={'command': cid})
        for sc in (scen if scen is not None else [{}]):
            self.scenario_for(iid, sc)
        return iid

    def scenario_for(self, iid, sc):
        sid = sc.get('id') or (iid.split('.', 1)[1].replace('cmd-', ''))
        sid = re.sub(r'[^a-z0-9-]+', '-', re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', sid).lower())
        sid = f'workbench-contribs-{self.name}-{sid}'[:61].rstrip('-')
        base, n = sid, 2
        while any(x['id'] == sid for x in self.scenarios):
            sid = f'{base}-{n}'; n += 1
        step = {'interface': iid, 'caller': sc.get('caller', 'user'), 'as': 's'}
        if 'input' in sc: step['input'] = sc['input']
        else: step['input'] = {}
        s = {'id': sid, 'fixtures': sc.get('fixtures', ['one-window-folder', 'workbench-contribs-seed'])}
        if sc.get('name'): s['name'] = sc['name']
        pre = sc.get('pre', [])
        post = sc.get('post', [])
        s['steps'] = pre + [step] + post
        for k in ('choices', 'state', 'config', 'faults', 'topology'):
            if k in sc: s[k] = sc[k]
        ex = list(sc.get('expect', []))
        if not sc.get('fails'):
            ex.insert(0, 'steps.s.result.ok')
        s['expect'] = ex
        self.scenarios.append(s)

    def write(self):
        out = {'configs': self.configs, 'components': self.components, 'stubs': self.stubs, 'seed': self.seed,
               'interfaces': self.interfaces, 'scenarios': self.scenarios}

        class D(yaml.SafeDumper):
            pass
        D.ignore_aliases = lambda self, data: True
        with open(os.path.join(HERE, 'parts', 'wc-' + self.name + '.yaml'), 'w') as fh:
            fh.write(f'# generated by builder.py from parts_src/{self.name}.py\n')
            yaml.dump(out, fh, Dumper=D, sort_keys=False, width=200, allow_unicode=True)


def called(iface, cond=None):
    c = f"e.type == 'call.start' && e.interface == '{iface}'"
    if cond:
        c += ' && ' + cond
    return f'trace.exists(e, {c})'


if __name__ == '__main__':
    sys.path.insert(0, os.path.join(HERE, 'parts_src'))
    for n in sys.argv[1:]:
        m = importlib.import_module(n)
        p = m.build()
        p.write()
        print(n, 'interfaces', len(p.interfaces), 'scenarios', len(p.scenarios))

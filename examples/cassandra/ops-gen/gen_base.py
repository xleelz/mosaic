"""Shared helpers for generating the ops fragment."""
import json, re, yaml

ROOT = '/home/lbethay/.cache/cassandra-bench/cassandra-5.0.9/'
INVF = '/home/lbethay/workplace/mosaic/examples/cassandra/inventory.json'
J = 'src/java/org/apache/cassandra/'
SS = J + 'service/StorageService.java'
SSM = J + 'service/StorageServiceMBean.java'
SP = J + 'service/StorageProxy.java'
SPM = J + 'service/StorageProxyMBean.java'
NT = J + 'tools/NodeTool.java'
NP = J + 'tools/NodeProbe.java'
CD = J + 'service/CassandraDaemon.java'
SC = J + 'service/StartupChecks.java'
CFG = J + 'config/Config.java'
YAML = 'conf/cassandra.yaml'

INV = json.load(open(INVF))['entries']
INVJ = {e['name']: e for e in INV if e['kind'] == 'jmx-operation'}
INVC = {e['name']: e for e in INV if e['kind'] == 'cli-command'}

_lines = {}


def src_lines(path):
    if path not in _lines:
        _lines[path] = open(ROOT + path).read().split('\n')
    return _lines[path]


def kebab(name):
    name = name.split('.')[-1]
    return re.sub(r'[^a-z0-9]+', '-', re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', name).lower()).strip('-')


def jmx(name):
    """Citation of a JMX operation's declaration line, from the inventory."""
    e = INVJ[name]
    return '%s:%d' % (e['file'], e['line'])


def cmd_src(name):
    e = INVC[name]
    return '%s:%d-%d' % (e['file'], e['line'], e['end_line'])


def class_line(path, cls):
    for i, l in enumerate(src_lines(path), 1):
        if re.search(r'\b(class|interface|enum)\s+' + cls + r'\b', l):
            return '%s:%d' % (path, i)
    raise KeyError((path, cls))


def check_line(path, line, needle):
    """Assert a cited line contains a needle, so citations stay honest."""
    l = src_lines(path)[line - 1]
    if needle not in l:
        raise AssertionError('%s:%d does not contain %r: %r' % (path, line, needle, l))
    return '%s:%d' % (path, line)


SHIFTS = []


def _find(path, line, needle, window=40):
    ls = src_lines(path)
    if needle in ls[line - 1]:
        return line
    for d in range(1, window + 1):
        for cand in (line - d, line + d):
            if 1 <= cand <= len(ls) and needle in ls[cand - 1]:
                SHIFTS.append('%s:%d -> %d (%s)' % (path.split('/')[-1], line, cand, needle[:40]))
                return cand
    raise AssertionError('%s:%d does not contain %r: %r' % (path, line, needle, ls[line - 1]))


def rng(path, lo, hi, needle=None):
    if needle:
        n = _find(path, lo, needle)
        hi += n - lo
        lo = n
    assert hi <= len(src_lines(path)), (path, hi)
    return '%s:%d-%d' % (path, lo, hi)


def at(path, line, needle=None):
    if needle:
        line = _find(path, line, needle)
    return '%s:%d' % (path, line)


DOC = {'components': [], 'interfaces': [], 'schemas': [], 'configs': [], 'flows': [], 'scenarios': []}
_ids = set()


def add(kind, ent):
    key = (kind, ent.get('id') or (ent['component'] + '.' + ent['name']))
    if key in _ids:
        raise KeyError('duplicate %s' % (key,))
    _ids.add(key)
    DOC[kind].append(ent)
    return ent


def comp(id, name, parent, summary, sources, kind='module', state=None, layer='ops', attrs=None, description=None):
    c = {'id': id, 'name': name, 'kind': kind, 'layer': layer, 'parent': parent, 'summary': summary,
         'sources': sources if isinstance(sources, list) else [sources]}
    if description:
        c['description'] = description
    if attrs:
        c['attributes'] = attrs
    if state is not None:
        c['state'] = state
    return add('components', c)


def stub_comp(id, name, parent, owner, path, cls=None):
    return add('components', {'id': id, 'name': name, 'kind': 'module', 'parent': parent,
                              'summary': '%s (boundary stub; %s models its internals).' % (name, owner),
                              'sources': [class_line(path, cls or name.split('.')[-1])],
                              'attributes': {'boundary': True, 'owner': owner}})


def iface(component, name, summary, sources, request=None, response=None, behavior=None, errors=None,
          kind='function', attrs=None, description=None, latency=None):
    i = {'component': component, 'name': name, 'kind': kind, 'summary': summary,
         'sources': sources if isinstance(sources, list) else [sources]}
    if description:
        i['description'] = description
    if attrs:
        i['attributes'] = attrs
    if request is not None:
        i['request'] = request
    if response is not None:
        i['response'] = response
    if errors:
        i['errors'] = errors
    if latency is not None:
        i['latency_ms'] = latency
    if behavior is not None:
        i['behavior'] = behavior
    add('interfaces', i)
    return component + '.' + name


def stub(component, name, owner, request=None, response=None, errors=None, kind='function', summary=None, sources=None):
    i = {'component': component, 'name': name, 'kind': kind,
         'summary': summary or ('%s.%s, owned by %s (boundary stub).' % (component, name, owner)),
         'attributes': {'boundary': True, 'owner': owner}}
    if sources:
        i['sources'] = sources if isinstance(sources, list) else [sources]
    if request is not None:
        i['request'] = request
    if response is not None:
        i['response'] = response
    if errors:
        i['errors'] = errors
    add('interfaces', i)
    return component + '.' + name


def schema(id, summary, sch):
    add('schemas', {'id': id, 'summary': summary, 'schema': sch})
    return id


def flow(id, name, entry_iface, sources, description=None, input=None, caller='operator', repeat=None, tags=None):
    f = {'id': id, 'name': name, 'entry': {'caller': caller, 'interface': entry_iface},
         'sources': sources if isinstance(sources, list) else [sources]}
    if input is not None:
        f['entry']['input'] = input
    if repeat:
        f['entry']['repeat'] = repeat
    if description:
        f['description'] = description
    if tags:
        f['tags'] = tags
    return add('flows', f)


FIXTURE = ['three-node-rf3']


def config(id, type_, value, default, summary, sources):
    return add('configs', {'id': id, 'type': type_, 'value': value, 'default': default, 'summary': summary,
                           'sources': sources if isinstance(sources, list) else [sources]})


def scenario(id, flow, name, expect, input=None, state=None, faults=None, choices=None, description=None, config=None, steps=None, fixtures=None):
    s = {'id': id, 'flow': flow, 'name': name, 'fixtures': list(fixtures or FIXTURE)}
    if description:
        s['description'] = description
    if config:
        s['config'] = config
    if steps:
        s['steps'] = steps
    if input is not None:
        s['input'] = input
    if state is not None:
        s['state'] = state
    if faults:
        s['faults'] = faults
    if choices:
        s['choices'] = choices
    s['expect'] = expect
    return add('scenarios', s)


def obj(props=None, required=None, **kw):
    o = {'type': 'object'}
    if props is not None:
        o['properties'] = props
    if required:
        o['required'] = required
    o.update(kw)
    return o


def s_(ex=None, default=None, enum=None, desc=None):
    o = {'type': 'string'}
    if desc:
        o['description'] = desc
    if enum:
        o['enum'] = enum
    if default is not None:
        o['default'] = default
    if ex is not None:
        o['examples'] = ex if isinstance(ex, list) else [ex]
    return o


def i_(ex=None, default=None, minimum=None, maximum=None, desc=None):
    o = {'type': 'integer'}
    if desc:
        o['description'] = desc
    if minimum is not None:
        o['minimum'] = minimum
    if maximum is not None:
        o['maximum'] = maximum
    if default is not None:
        o['default'] = default
    if ex is not None:
        o['examples'] = ex if isinstance(ex, list) else [ex]
    return o


def n_(ex=None, default=None, desc=None):
    o = {'type': 'number'}
    if desc:
        o['description'] = desc
    if default is not None:
        o['default'] = default
    if ex is not None:
        o['examples'] = ex if isinstance(ex, list) else [ex]
    return o


def b_(default=None, desc=None):
    o = {'type': 'boolean'}
    if desc:
        o['description'] = desc
    if default is not None:
        o['default'] = default
    return o


def a_(items, default=None, desc=None, ex=None):
    o = {'type': 'array', 'items': items}
    if desc:
        o['description'] = desc
    if default is not None:
        o['default'] = default
    if ex is not None:
        o['examples'] = [ex]
    return o


def err(code, summary=None, status=None, retryable=None):
    e = {'code': code}
    if status is not None:
        e['status'] = status
    if retryable is not None:
        e['retryable'] = retryable
    if summary:
        e['summary'] = summary
    return e


def note(title, source, detail=None, **action):
    st = {'title': title, 'source': source}
    if detail:
        st['detail'] = detail
    st.update(action)
    return st


def dump(path):
    out = {'schema_version': 1, 'id': 'cassandra'}
    for k in ('components', 'interfaces', 'schemas', 'configs', 'flows', 'scenarios'):
        out[k] = DOC[k]

    class D(yaml.SafeDumper):
        pass

    def str_rep(dumper, data):
        style = None
        if data.startswith('=') or data.startswith('!') or ': ' in data or data.startswith('*') or data.startswith('&'):
            style = '"'
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style=style)

    D.add_representer(str, str_rep)
    with open(path, 'w') as f:
        f.write('# Fragment: ops (operations surface) for the Apache Cassandra 5.0.9 ontology.\n'
                '# Generated from code reading; see notes/ops.md for entry points, skips and gaps.\n')
        yaml.dump(out, f, Dumper=D, sort_keys=False, width=1000, allow_unicode=True, default_flow_style=False)

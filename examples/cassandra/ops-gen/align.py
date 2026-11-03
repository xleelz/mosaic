"""Copy owners' contracts onto ops boundary stubs (request/response/kind/errors), inlining owner schema refs."""
import yaml, glob, json, copy, os
FR = '/home/lbethay/workplace/mosaic/examples/cassandra/fragments/'


def load_owners():
    owners, schemas = {}, {}
    for f in sorted(glob.glob(FR + '*.yaml')):
        if f.endswith('/ops.yaml'):
            continue
        area = os.path.basename(f)[:-5]
        cache = '/tmp/ops_work/owner_cache_%s.json' % area
        try:
            d = yaml.safe_load(open(f)) or {}
            json.dump({'schemas': d.get('schemas') or [], 'interfaces': d.get('interfaces') or []}, open(cache, 'w'))
        except Exception as ex:
            print('WARN: %s does not parse right now (%s); using the cached copy' % (area, str(ex).splitlines()[0]))
            d = json.load(open(cache)) if os.path.exists(cache) else {}
        sch = {s['id']: s['schema'] for s in d.get('schemas') or []}
        for i in d.get('interfaces') or []:
            if (i.get('attributes') or {}).get('boundary'):
                continue
            iid = i.get('id') or (i['component'] + '.' + i['name'])
            owners[iid] = (area, i, sch)
        schemas[area] = sch
    return owners, schemas


def inline(node, sch, depth=0):
    """Inline a schema reference (string id, '#/schemas/id' or {$ref}) and every nested schema position."""
    if depth > 12:
        return {'type': 'object'}
    if isinstance(node, str):
        ref = node[len('#/schemas/'):] if node.startswith('#/schemas/') else node
        return inline(copy.deepcopy(sch.get(ref, {'type': 'object'})), sch, depth + 1)
    if not isinstance(node, dict):
        return node
    out = {}
    if '$ref' in node:
        ref = node['$ref']
        ref = ref[len('#/schemas/'):] if ref.startswith('#/schemas/') else ref
        out.update(inline(copy.deepcopy(sch.get(ref, {'type': 'object'})), sch, depth + 1))
    for k, v in node.items():
        if k == '$ref':
            continue
        if k == 'properties' and isinstance(v, dict):
            out[k] = {pk: inline(pv, sch, depth + 1) for pk, pv in v.items()}
        elif k == 'items' and isinstance(v, dict):
            out[k] = inline(v, sch, depth + 1)
        elif k in ('oneOf', 'anyOf', 'allOf') and isinstance(v, list):
            out[k] = [inline(x, sch, depth + 1) for x in v]
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_owner_components():
    comps = {}
    for f in sorted(glob.glob(FR + '*.yaml')):
        if f.endswith('/ops.yaml'):
            continue
        area = os.path.basename(f)[:-5]
        try:
            d = yaml.safe_load(open(f)) or {}
        except Exception:
            continue
        for c in d.get('components') or []:
            if not (c.get('attributes') or {}).get('boundary'):
                comps[c['id']] = (area, c)
    return comps


def align(doc):
    owners, _ = load_owners()
    report = []
    oc = load_owner_components()
    for c in doc['components']:
        if (c.get('attributes') or {}).get('boundary') and c['id'] in oc:
            area, o = oc[c['id']]
            for k in ('kind', 'name', 'layer'):
                if k in o:
                    c[k] = o[k]
            c['attributes']['owner'] = area
    for i in doc['interfaces']:
        if not (i.get('attributes') or {}).get('boundary'):
            continue
        iid = i['component'] + '.' + i['name']
        if iid not in owners:
            continue
        area, o, sch = owners[iid]
        for k in ('kind',):
            if k in o:
                i[k] = o[k]
        for k in ('request', 'response'):
            if k in o and o[k] is not None:
                i[k] = inline(copy.deepcopy(o[k]), sch)
            elif k in i:
                del i[k]
        if o.get('errors'):
            i['errors'] = copy.deepcopy(o['errors'])
        elif 'errors' in i:
            del i['errors']
        i['attributes']['owner'] = area
        report.append((iid, area))
    return report, owners

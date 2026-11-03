import json
g = json.load(open('/tmp/ops_work/groups.json'))
out = []
for key, grp in g.items():
    for kind, name, f, line in grp['items']:
        out.append({'kind': kind, 'name': name, 'file': f, 'line': line, 'reason': grp['reason']})
inv = {(e['kind'], e['name'], e['file'], e['line']) for e in json.load(open('/home/lbethay/workplace/mosaic/examples/cassandra/inventory.json'))['entries']}
assert all((o['kind'], o['name'], o['file'], o['line']) in inv for o in out)
assert len({(o['kind'], o['name']) for o in out}) == len(out)
json.dump(out, open('/home/lbethay/workplace/mosaic/examples/cassandra/skips/ops.json', 'w'), indent=1)
print(len(out))

import json, re, collections, sys
inv = json.load(open('/home/lbethay/workplace/mosaic/examples/cassandra/inventory.json'))['entries']
notcov = set()
for l in open('/tmp/ops_work/cov.txt'):
    m = re.match(r'\s+- (\w[\w ]*?) ([\w-]+) "(.*)" (\S+):(\d+)', l.rstrip())
    if m:
        notcov.add((m.group(2), m.group(3)))
def mine(e):
    f, k = e['file'], e['kind']
    if k in ('jmx-operation', 'cli-command', 'python-cli'):
        return True
    if k == 'java-main':
        return f.startswith('tools/') or '/tools/' in f or f.endswith(('CassandraDaemon.java', 'utils/DynamicList.java'))
    if k in ('scheduled-task', 'background-task', 'stage-task'):
        return any(p in f for p in ('/utils/', '/metrics/', '/security/', '/tracing/', '/concurrent/', '/config/', '/audit/', '/fql/', '/db/virtual/', 'CassandraDaemon.java', 'StartupChecks.java', 'DataResurrectionCheck.java'))
    return False
M = [e for e in inv if mine(e)]
cov = [e for e in M if (e['kind'], e['name']) not in notcov]
unc = [e for e in M if (e['kind'], e['name']) in notcov]
print('mine', len(M), 'covered', len(cov), 'not covered', len(unc))
json.dump({'covered': cov, 'uncovered': unc}, open('/tmp/ops_work/mine.json', 'w'), indent=1)
c = collections.Counter((e['kind'], e['file'].split('/')[-1]) for e in unc)
for k, v in sorted(c.items()):
    print(v, k)

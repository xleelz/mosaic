set -e
# Rebuilds fragments/ops.yaml, notes/ops.md and skips/ops.json. Scratch files go to /tmp/ops_work.
mkdir -p /tmp/ops_work
cd /home/lbethay/workplace/mosaic/examples/cassandra/ops-gen
python3 -I gen_main.py > /tmp/ops_work/gen.log 2>&1 || { cat /tmp/ops_work/gen.log; exit 1; }
cd /home/lbethay/workplace/mosaic
python3 -I -c "import json; d=json.load(open('examples/cassandra/inventory.json')); [e.pop('skip', None) for e in d['entries']]; json.dump(d, open('/tmp/ops_work/inventory_noskip.json','w'))"
export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
go run ./internal/devtools/check -f examples/cassandra/skeleton.yaml -f examples/cassandra/fixtures.yaml -f examples/cassandra/fragments/ops.yaml --code /home/lbethay/.cache/cassandra-bench/cassandra-5.0.9 --strict-citations --inventory /tmp/ops_work/inventory_noskip.json -v 2>&1 | grep -v "^✓" > /tmp/ops_work/cov.txt || true
python3 -I /home/lbethay/workplace/mosaic/examples/cassandra/ops-gen/skips.py | head -1
python3 -I /home/lbethay/workplace/mosaic/examples/cassandra/ops-gen/groups.py | grep -E "unassigned|total"
python3 -I /home/lbethay/workplace/mosaic/examples/cassandra/ops-gen/notes.py
grep -v "^  - " /tmp/ops_work/cov.txt | grep -E "validation|scenarios:|citations|^coverage:|!|✗" | head -20
python3 -I /home/lbethay/workplace/mosaic/examples/cassandra/ops-gen/skipsjson.py

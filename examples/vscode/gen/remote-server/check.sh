# usage: check.sh [merged] [extra args]  -- area-only by default; "merged" runs the full merged gate
cd /home/lbethay/workplace/mosaic
export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
if [ "$1" = merged ]; then shift; F=""; for f in examples/vscode/fragments/*.yaml; do F="$F -f $f"; done; MM="--min-modeled 0.5"
else F="-f examples/vscode/fragments/remote-server.yaml"; MM=""; fi
go run ./internal/devtools/check -f examples/vscode/skeleton.yaml -f examples/vscode/fixtures.yaml -f examples/vscode/worlds.yaml $F $EXTRA \
  --code /home/lbethay/.cache/mosaic-bench/vscode-1.144.0 --strict-citations --inventory examples/vscode/inventory.json --behavior-coverage --lint hollow --no-mocks $MM "$@"

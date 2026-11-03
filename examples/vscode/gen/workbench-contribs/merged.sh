#!/bin/sh
# usage: merged.sh [FRAGMENT_OVERRIDE] [extra check args]
# Runs the merged gate with this area's fragment, or an override file. An override must be named
# workbench-contribs.yaml (the modeled gate matches the fragment by file name).
# LOCAL=1 drops other areas' scenarios that name a fixture nobody defines (their in-progress edits),
# so a half-finished fragment elsewhere doesn't hide this area's results; the real gate never sets it.
cd /home/lbethay/workplace/mosaic
export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
MINE=${1:-examples/vscode/fragments/workbench-contribs.yaml}; [ $# -gt 0 ] && shift
DIR=examples/vscode/fragments
if [ -n "$LOCAL" ]; then
  rm -rf /tmp/wbc-local && mkdir -p /tmp/wbc-local
  python3 examples/vscode/gen/workbench-contribs/local_filter.py $DIR /tmp/wbc-local "$MINE"
  DIR=/tmp/wbc-local
fi
F=""; for f in $DIR/*.yaml; do case $f in *workbench-contribs.yaml) ;; *) F="$F -f $f";; esac; done
go run ./internal/devtools/check -f examples/vscode/skeleton.yaml -f examples/vscode/fixtures.yaml -f examples/vscode/worlds.yaml $F -f $MINE \
  --code /home/lbethay/.cache/mosaic-bench/vscode-1.144.0 --strict-citations \
  --inventory examples/vscode/inventory.json --behavior-coverage --lint hollow --no-mocks --min-modeled 0.5 "$@"

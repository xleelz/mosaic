#!/bin/sh
# The full merged gate (docs/PIPELINE.md), run from the mosaic root.
cd "$(dirname "$0")/../../../.." || exit 1
WS=examples/vllm
F=""; for f in $WS/fragments/*.yaml; do F="$F -f $f"; done
CONTRACTS=""; for f in $WS/contracts/*.yaml; do [ -e "$f" ] && CONTRACTS="$CONTRACTS --contract $f"; done
exec .claude/skills/mosaic-generate/scripts/mcheck -f $WS/skeleton.yaml -f $WS/fixtures.yaml -f $WS/worlds.yaml $F \
  --code $HOME/.cache/mosaic-bench/vllm-0.32.0 --strict-citations --inventory $WS/inventory.json \
  --min-modeled 0.5 --min-substantive 0.5 --max-trivial 0.35 \
  --tests $WS/test-targets.json --features $WS/profile.yaml --strict-features \
  --behavior-coverage --no-mocks \
  --lint hollow,trivial,racy,seam-names,unknown-inputs,exemptions,internal-assertions,clock-ids $CONTRACTS \
  --profile $WS/profile.yaml --strict-stubs --explore 'race|concurr' --schedules 20 --replay-dir $WS/replay "$@"

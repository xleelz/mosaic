#!/bin/sh
# Assemble examples/vllm/fragments/scheduler-kv.yaml from the pieces in this directory.
set -e
here=$(cd "$(dirname "$0")" && pwd)
out="$here/../../fragments/scheduler-kv.yaml"
{
  cat "$here/body.yaml"
  echo
  cat "$here/interfaces_kv.yaml"
  echo
  cat "$here/interfaces_sched.yaml"
  echo
  cat "$here/interfaces_misc.yaml"
  echo
  cat "$here/interfaces_r4.yaml"
  echo
  cat "$here/interfaces_r5.yaml"
  echo
  cat "$here/flows.yaml"
  echo
  python3 -I "$here/fixtures.py"
  echo
  python3 -I "$here/round3.py"
  python3 -I "$here/round4.py"
  python3 -I "$here/round5.py"
  python3 -I -c "import sys,yaml; a=yaml.safe_load(open(sys.argv[1])); [a['scenarios'].extend(yaml.safe_load(open(p))['scenarios']) for p in sys.argv[2:]]; sys.stdout.write(yaml.safe_dump(a, sort_keys=False, width=100000))" "$here/scenarios.yaml" "$here/round3_scenarios.yaml" "$here/round4_scenarios.yaml" "$here/round5_scenarios.yaml"
} > "$out"
echo "wrote $out"

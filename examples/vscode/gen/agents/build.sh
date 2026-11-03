#!/bin/sh
# Builds examples/vscode/fragments/agents.yaml and skips/agents.json, then applies the fix-round patches.
cd "$(dirname "$0")" && cat build1.py build2.py build3.py build4.py build5.py fix5.py extra_mcp.py recon.py recon_cmds.py recon_fix.py fill.py build6.py > /tmp/agents_all.py && python3 -I /tmp/agents_all.py && python3 -I fix_round/apply.py

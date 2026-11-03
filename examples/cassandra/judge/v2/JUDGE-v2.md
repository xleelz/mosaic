# Judge brief, round 2

Follow `../JUDGE.md` in full, with these changes.

- **The model** is the migrated `examples/cassandra/cassandra.json`: 1,571 scenarios, all passing,
  under the full quality gate. It now uses mosaic's DESIGN §11 features: instances n1–n4,
  `parallel` joins, deadlines, configs, the shared fixtures in `examples/cassandra/fixtures.yaml`
  and multi-step scenarios. Read §11 and `.claude/skills/mosaic-simulation/references/` first.
- **Your scenarios** must use the shared fixtures (`fixtures: [three-node-rf3]` and so on).
  Multi-step scenarios, instance faults (`instance: n2`) and trace assertions are allowed.
  **No mocks**, and never edit the model or the fragments.
- **Expectations.** Round 1 verified and corrected the expectations against the code. Each
  `judge/<group>.md` lists them in its "verified expectation" column. Use those corrected
  expectations, but re-check every one you rely on against the code (cite it). If you find a
  round 1 correction wrong, say so.
- **Score independently.** Don't read round 1's scores or root causes until you've scored a case
  yourself. Afterwards, compare them, and for each case say whether it improved, regressed or is
  unchanged, and why.
- **Debugging.** Use `check --scenario REGEX --trace`. The model is merged, so run:
  `go run ./internal/devtools/check -q -f examples/cassandra/cassandra.json -f examples/cassandra/judge/v2/scenarios/<CASE>.yaml --scenario '^bench' --trace`.
- **Outputs** go in `judge/v2/<group>.md`, `judge/v2/<group>.json` and
  `judge/v2/scenarios/<CASE>.yaml`.
- **Simulator gaps.** List the ones still open, and note any that DESIGN §11 resolved.

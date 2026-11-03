# Fix round 4 (vLLM): coverage

Round 3 paid the debt, and the gate is clean. The first blind measure then showed the model is
mostly **incomplete**, not wrong:
- the benchmark passed 65 of 105 steps;
- the test oracle passed 2 of 36;
- 24 oracle tests failed on parts of vLLM the model doesn't have.

This round makes the model cover what vLLM's tests and users actually exercise.

- `BRIEF.md`, `RECONCILE.md`, `FIXES.md` and `FIXES3.md` still apply. So do DESIGN §15–17 and the
  `mosaic-simulation` skill. New since round 3:
  - `streams_when` (per-call streaming);
  - CEL `indexOf`/`lastIndexOf`;
  - process-exit signals (`exit:<component>@<instance>`, and `wait: {signals: [...]}`);
  - `check --steps`, to print step results.
- **You may now read** `judge2/` and `oracle2/` (round 3's blind measure), and
  `reconcile/round3/coordinator-x4.md`.
- **Never read** `BENCHMARK3.md` or `oracle3/`. They are this round's blind measure.
- **Breaking changes toward the code are welcome.** List each one, with the callers it breaks.
  Fix through your generator; `config-platform` edits its fragment directly. Before reporting, run
  `.claude/skills/mosaic-generate/scripts/mcheck` with the full `-f` list and
  `--stage examples/vllm/fragments/<area>.yaml --accept`.

## Your list

1. **Blind findings.** Every model bug and wrong claim that `oracle2/<area>.md` and
   `judge2/*.md` attribute to your area. Fix each against the judge's **corrected** expectation.
   Re-run those scenarios (`judge2/scenarios/`, `oracle2/<area>.yaml`) unedited. A scenario that
   still fails is fixed, or explained in your notes with a code citation.
2. **Coverage: `reconcile/round4/coverage-<area>.md`.** It lists the functions your area's tests
   call that no citation in the model covers, ranked by how many tests call them. It also lists
   the inventory skips your tests still exercise.
   - Work **down the ranking**. Model each function as the code does: inputs, decisions, errors,
     state, and calls to other components. Give it scenarios that assert boundary behavior (`io`,
     `result`, `steps.*`).
   - Group related functions into one interface where the code does (a class's public method and
     its private helpers).
   - Cover at least the **top 25** rows, or every row if there are fewer, and every test-hit skip.
     A row may be declined only with a reason in your notes: it belongs to another area (name it),
     or it is numeric, tensor or byte-level work that a refinement should model.
   - Unskip what the tests exercise. Remove the entry from `skips/<area>.json` once it is modeled.
3. **Your unit tests.** `build-oracle/round4/<area>.json` holds 6 fresh tests. Translate them
   into `build-oracle/round4/<area>.{yaml,md}`. Fix the model until each passes or is
   untranslatable for a stated reason.
4. **Keep the gate where it is.** Thresholds don't go back up. New interfaces need real
   citations, unknown-inputs stays 0, clock-ids stays 0, racy stays 0, and new race or concurrency
   scenarios are tagged.

## Verify

- Run the full gate as `docs/PIPELINE.md` documents it, with `--profile examples/vllm/profile.yaml`
  and `--code ~/.cache/mosaic-bench/vllm-0.32.0`.
- Re-run the coverage report:
  `python3 .claude/skills/mosaic-generate/scripts/coverage_gaps.py examples/vllm --out-dir /tmp/cov-<area>`.
- Rebuild `vllm.json`.

**Exit criteria:**
- the merged gate passes;
- your blind findings are fixed or answered;
- your function-level coverage rose, with the top 25 rows modeled or declined with a reason;
- your round-4 tests pass, or are untranslatable for a stated reason;
- no earlier measure regresses: judge, judge2, oracle, oracle2, and build-oracle rounds 3 and 4.

## Report (≤150 words)

- the blind findings fixed;
- function-level reach before and after (from the report header);
- the rows you declined, and why;
- your unit tests: passing, out of 6;
- your breaking changes, with the callers they break;
- what's still open.
